# NO00002: 关闭 XS emit 文本级共享（shape-twin / branch-block 折叠）以消除共享体调用与参数间接开销

| 字段 | 值 |
|---|---|
| 父节点 | NO00001（当前最佳，无迂回） |
| 角色 | 优化 |
| 状态 | ACCEPTED |
| 锚定指标 | M-share（cpu_blk_*+cpu_shape_* 扁平样本占比）；M-tput（dynOps/Host） |
| 指标阈值 | M-share ≤1%（基线 36.29%）；M-tput ≥ +6%（基线 1.2894 Gop/s） |
| 回退预算 | 新组 Host 均值 ≤ 旧组均值 ×1.025（≤79.08 s） |
| RUN_ID | no00002_gen_20260924 / no00002_build_20260924 / no00002_bench_20260924 / no00002_profile_20260924 / no00002_dyn_20260924 |
| 工作区 | ptmp/no00002_disable_text_share_20260924/ |

## 基础选定（BASELINE）

- **父节点**：NO00001（当前最佳指针，wolvrix `4de8c01`，Host 77.155 s）。本节点直接在其代码状态上改动，无迂回。
- **基线测量（配置未变，复用父节点归档值，不重跑）**：
  - Host time 100k：**77.155 s**（3 次有效均值 77.260/77.092/77.114，SD 0.091 s，极差/均值 0.22%）。
  - M1 相位：compute 59.250 s（76.9%）、commit 16.790 s（21.8%）、publish 0.860 s（1.1%）；evals=200102、rounds=401257。
  - M2 任务级分布：cpu_task_* 49.76%、**cpu_blk_* 23.70%（3682/15538）、cpu_shape_* 12.59%（1956/15538），共享体合计 36.29%**；cpu_write_cell 2.66%；eval 3.55%。
  - M4 动态计数（确定性）：dynOps = **99,479,933,605**；boundary 写 22,134,521,354 次。
  - 派生吞吐基线：M-tput = 99,479,933,605 / 77.155333 = **1.2894 Gop/s**。
- **对照二进制**：旧构建（"old"）= NO00001 归档的 `ptmp/no00001_anchor_profile_20260923/flow-base/emu/emu`（2026-09-24 00:23 构建，未改动），3+3 交替时现场复跑，不使用跨窗口历史数据。
- **输入核对**：与 NO00001 相同（`coremark-2-iteration.bin` sha256 `c764afb8…f1732f83e8`，`riscv64-nemu-interpreter-so` sha256 `094c1c4a…207ff9e`），输入未变。
- **资源配置**：与 NO00001 完全一致：`XS_EMU_CPU=2`、`XS_EMU_THREADS=1`、`XS_NUM_CORES=1`、`XS_SIM_MAX_CYCLE=100000`、waveform/commit/RAM trace 全关；编译 `VM_BUILD_JOBS=32`（=nproc）。flow 配置全默认（`CPU_TARGET_BATCH_COUNT=0`、`PACK_BIT_REGISTERS=1`、`CLONE_SHARED_COMPUTE=1`、`BITWISE_PREDICATES=1`），同 NO00001。
- **计时边界与止损线**：
  - 生成：make 启动 → 完整 C++ 与 Makefile 生成完成，墙钟 <1800 s；超时 `TIMEOUT_KILLED`。
  - 编译：emu 编译启动 → 可执行文件完成，墙钟 <1800 s；超时 `TIMEOUT_KILLED`。
  - 仿真：仅 emu 执行区间。比较基线值预注册为 77.155333 s，运行截止 = ×1.5 = **115.733 s**，超时 `REGRESSION_KILLED`。
  - 每次仿真运行前对 emu 二进制 `posix_fadvise(DONTNEED)` 驱逐页缓存（benchmark_grhsim_ir.py 内建）。
- **复现方法**：父节点代码状态 = wolvrix `4de8c01` + 根仓库 NO00001 提交；本节点仅改根仓库 XS flow 脚本与 Makefile（wolvrix 子模块不动）。

## 假设提出（HYPOTHESIS）

- **假设**：XS emit 当前强制开启的两级文本级共享——whole-task shape-twin 折叠（`--shape-twin-share`，231 个共享 body 服务 1080 个任务）与活动守卫分支块折叠（`--branch-shape-share`，2294 个共享 body 服务 10645 个调用点）——在运行时引入显著的逐执行开销：共享 body 为 `noinline`，全部差异常量（状态/boundary 偏移、begin/count、掩码等）经 per-instance 静态参数数组以内存加载方式取用（实例：`cpu_task_1127` 仅 39 行，向 `cpu_shape_93` 传入 ~1500 项 u32 参数数组），编译器无法跨调用边界做立即数寻址、常量传播与跨 op 寄存器分配，另有调用/返回与 active_word 引用合并开销。**关闭两级共享后，同样的动态工作量（dynOps 不变）将以更低的逐 op 成本执行，M-tput 显著提升。** 反向风险：源码自 6.63M 行膨胀至约 10.7M 行（shape 实例 +1.7M 行、block 实例 +2.4M 行），icache/分支预测足迹变大可能抵消部分收益；净效应由本节点实测裁定。
- **创新点**：把"编译时间换运行时"的文本共享默认项反转为"运行时优先"默认项；共享机制与 hotness 引导冷折叠通路保留（opt-in），不做删除。本节点是方法论重启后首个对该机制的运行时代价做定量裁定的实验。
- **瓶颈证据（本分支实测）**：
  1. NO00001 M2：共享体（cpu_blk_* + cpu_shape_*）扁平样本占比 **36.29%**（23.70% + 12.59%），与 compute 相位占比 76.9% 同为最大单类开销归因；任务级分布长尾，单任务最高仅 1.35%，面向全体 compute 的结构性机制是唯一大杠杆。
  2. 生成代码直接观察：shape 包装任务把全部偏移常量放入静态数组（见上例），共享 body 内每次状态/boundary 访问须先加载参数再计算地址，相比内联立即数寻址每次访问多一条 load + 地址运算。
  3. 编译预算余量：NO00001 编译仅 191.20 s（门槛 1800 s，余量 ~9.4×），展开后预估 ~300–500 s（按行数 +62% 近似线性外推），仍在预算内——共享机制当初所换取的编译时间当前并不稀缺。
- **微观指标与总目标的定量关系**：
  - M-share（结构指标）：gperftools 200 Hz 扁平样本中 cpu_blk_* + cpu_shape_* 占比，基线 **36.29%**（5638/15538，NO00001 M2 同口径）。该占比度量"经共享体间接执行"的执行量份额，是本节点改动直接作用的结构量。
  - M-tput（效率指标）：dynOps / Host = 有效 op 吞吐，基线 **1.2894 Gop/s**。Host ≈ dynOps / M-tput（compute 占 99.5% 的模型求值由 op 执行主导）；dynOps 由 IR 与调度决定，本节点不改 IR/调度，故 M-tput 提升按比例传导为 Host 下降：**M-tput +6% ⇒ Host ≈ −5.7% ≈ −4.4 s ≈ 剩余差距（30.1 s）的 ~15%**。开销估计区间：共享体 36.29% 样本中若 25–45% 为间接开销，则总收益 9–16%，扣除 icache 反向效应预取下限 6%。
- **预注册**：
  - M-share 阈值：新构建 profile 占比 **≤1%**（测量：scripts/profile_grhsim_ir.py + grhsim_cpu_profile.py 同口径，样本 ≥10000，运行 VALID_DIAGNOSTIC；关闭共享后两类符号不复存在，预期实测即 0%）。
  - M-tput 阈值：**≥ +6%**（≥1.3668 Gop/s，即 dynOps 不变下 Host ≤ 72.78 s）。dynOps 以新构建 dynamic-stats 插桩运行复测一次，须与父节点 99,479,933,605 逐键精确一致（确定性来源：固定输入 + 固定 IR/调度，插桩不改变行为已由 NO00001 验证）；Host 取 3+3 新组均值。
  - 回退预算：新组 Host 均值 ≤ 旧组均值 ×**1.025**（≤79.08 s）；即便允许回退也定量记录。
  - 最终性能提升判据：同一时间窗口 3+3 交替（预注册顺序 old1,new1,old2,new2,old3,new3），**全部 3 次新运行均优于全部 3 次旧运行**（n=3+3，等价 Mann-Whitney U 单侧 p≤0.05）方可判定提升真实。
  - 证伪标准：M-share ≤1% 达标而 M-tput 提升 **< +1%**（Host 变化落入噪声）→ 机制性证伪：文本共享的运行时代价不显著（参数间接开销被 icache/局部性收益抵消），登记机制证伪表。
  - 实现瑕疵路线：编译 TIMEOUT_KILLED（>1800 s）→ 回 IMPLEMENTED 改用 hotness 引导冷折叠变体（保留共享、按热度剔除热组）重测；等价性失败（INVALID）→ 同为实现瑕疵排查。
  - 验收：全流程门槛通过 + 100k 端点精确匹配（`instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`，退出 0，无 mismatch）+ M-share 与 M-tput 双达标 + 回退未破预算。

## 代码实施（IMPLEMENTED）

- **改动**（仅根仓库，wolvrix 子模块不动，冻结面零改动）：
  1. `scripts/wolvrix_xs_grhsim_ir.py`：新增 opt-in 开关 `--shape-twin-share` / `--branch-shape-share`（`action="store_true"`，默认关闭）；`emit_options` 仅在显式开启时写入 `shape_twin_share` / `branch_shape_share`。`--branch-shape-hotness` 隐含开启 `branch_shape_share`（hotness 只在折叠开启时有意义），保留既有冷折叠通路。
  2. `Makefile`：新增 `XS_WOLF_GRHSIM_IR_SHAPE_TWIN_SHARE` / `XS_WOLF_GRHSIM_IR_BRANCH_SHAPE_SHARE`（默认空=关闭），在 `xs_wolf_grhsim_ir` 配方中透传；附注释说明该共享以运行时换编译时间、验证默认保持任务完全内联。
- **语义约束**：改动只切换 C++ 代码形态（`noinline` 共享 body + 静态参数数组 ↔ 任务内联立即数），不改 GrhSIM IR、mapping、调度、fanout、布局与任何 op 语义；C++ 侧两开关本来就是 `false` 默认（`cpu_emit.cpp:4575,4579`），全部 `test_cpu_emit` 用例长期在无共享路径上验证。动态工作量（dynOps）与行为端点由不变性保证，仍以等价检查实测确认。
- **与父节点差异**：emit C++ 形态——无 `cpu_blk_*` / `cpu_shape_*` 共享 body 与包装任务，全部任务体内联展开（预估源码 6.63M → ~10.7M 行）；其余（IR JSON、mapping、调度、布局、init、driver）逐字节一致为预期。
- **聚焦测试**：
  - `make test_benchmark_grhsim_ir`：通过。
  - `make run_hdlbits_grhsim_ir DUT=001`：通过（`dut_001 passed`）。
  - 脚本语法与 CLI：`ast.parse` 通过；`--help` 显示两新开关。

## 结果测试（TESTED）

### 全流程门槛

| 区间 | 实测 | 门槛 | 判定 |
|---|---|---|---|
| SV→C++ 生成 | 786.01 s | <1800 s | 通过 |
| C++ 编译（-j32） | 195.95 s | <1800 s | 通过 |

生成物核对：4439 个任务文件、零 blocks/shapes 文件、零 cpu_blk_*/cpu_shape_* 引用，生成 C++ 9.62M 行（父节点 6.63M 行，+45%）；emit 步骤 15.46 s（父节点 82.59 s）。编译时间几乎不变（195.95 vs 191.20 s）：共享机制在当前编译预算下没有可观测的编译时间收益。

### 100k 等价检查

3+3 复测全部 6 次运行 + M1/M2/M4 三次诊断运行，端点均精确匹配 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`，退出 0，DIFFTEST 无 mismatch → 100k 等价成立。

### 最终性能（3+3 交替复测）

预注册执行顺序 old1,new1,old2,new2,old3,new2→new3；比较口径：同一二进制各自 3 次、同窗口交替、CPU 2、`posix_fadvise` 驱逐页缓存、止损线 115.733 s（未触发）。old = NO00001 归档二进制（flow-base，共享开启），new = 本节点构建（共享关闭）。

| 组 | 3 次 Host（s） | 均值（s） | 样本 SD（s） | 端点/退出 |
|---|---|---|---|---|
| old | 77.697 / 77.386 / 77.197 | 77.427 | 0.252 | 全部 VALID |
| new | 69.849 / 70.404 / 70.150 | **70.134** | 0.278 | 全部 VALID |

统计：改善 **−9.42%**（对本窗口 old 均值；对归档 77.155 s 为 −9.10%）；Cohen d = −27.47；Cliff δ = −1.0；3 次新运行全部优于 3 次旧运行，Mann-Whitney U=0，单侧精确 p=0.05 → **秩次判据通过，提升真实**。对 gsim 归档 46.965 s ≈ **1.493×**，剩余差距 ~23.2 s（父节点为 1.643× / ~30.1 s）。

### 微观指标测量

- **M-share（锚定，阈值 ≤1%）**：新构建 gperftools 200 Hz profile（14065 样本 ≥10000，VALID_DIAGNOSTIC，端点精确匹配）中 cpu_blk_* = 0、cpu_shape_* = 0 样本，合计 **0.00%**（基线 36.29%）→ **达标**。分类分布：compute_task 66.20%、commit_task 17.86%、main_other 10.88%（父节点 45.75%，−34.9 pt）、evaluator 4.15%。
- **M-tput（锚定，阈值 ≥+6%）**：dynOps 经新配置 dynamic-stats 插桩构建复测 = **99,479,933,605**，与父节点逐键精确一致（32143 行计数 diff 为空；确定性来源：固定输入 + 不变 IR/调度）。M-tput = 99,479,933,605 / 70.134333 = **1.4184 Gop/s**，对基线 1.2893 Gop/s **+10.0%**（对本窗口 old 均值口径 +10.4%）→ **达标**。
- **M1 相位（诊断）**：tick_total 69.702 s；model_step 69.345 s（99.49%）。compute **51.486 s**（父节点 59.250 s，**−7.76 s / −13.1%**），commit 16.931 s（+0.14 s，噪声内），publish 0.860 s（不变）。evals=200102、rounds=401257 与父节点完全一致——工作量结构不变，收益全部来自逐 op 成本下降。
- **M4 结构量**：supernode 激活/执行、commit 入口、port_eval/fire 等全部计数与父节点逐键一致（见上 dyn diff 为空）。

### 回退与预算核对

回退预算 ≤ ×1.025（79.08 s）：实测 −9.42%，无回退。正确性与生成/编译门槛全部通过。

### 判定

**ACCEPTED**。判定依据：

1. 全流程门槛通过（生成 786.01 s、编译 195.95 s，均 <1800 s）；全部计入运行端点精确匹配、退出 0、无 mismatch（100k 等价成立）。
2. M-share 0.00% ≤ 1% 达标：文本级共享体从执行路径中完全移除。
3. M-tput +10.0% ≥ +6% 达标，且 dynOps 逐键不变证立"同工作量、低成本"机制：compute 相位 −7.76 s 即收益主体，与预注册定量关系（+6% ⇒ −4.4 s）方向一致、幅度更大（共享体间接开销占比估计偏保守）。
4. 最终性能 −9.42%，秩次判据通过（p=0.05），无回退；新均值 70.134 s 更新当前最佳指针，对 gsim 剩余差距收敛至 1.493×。
5. 附带结论：关闭共享后编译时间几乎不变（+2.5%），且 emit 步骤 82.59→15.46 s——该共享机制在当前编译预算下无编译时间收益，其运行时代价是纯损失；hotness 冷折叠通路保留为 opt-in 备日后编译压力场景。
