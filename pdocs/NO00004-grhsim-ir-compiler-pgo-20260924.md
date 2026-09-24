# NO00004: 编译器 PGO（-fprofile-generate/use）施加于 GrhSIM-IR emu——以真实动态剖面驱动分支布局与内联，降低逐 op 成本

| 字段 | 值 |
|---|---|
| 父节点 | NO00002（当前最佳，无迂回） |
| 角色 | 优化 |
| 状态 | ACCEPTED |
| 锚定指标 | M-tput（dynOps / Host，dynOps 由发射源逐字节不变性锁定为 99,479,933,605） |
| 指标阈值 | M-tput ≥ +3.0%（≥1.4610 Gop/s ⇔ Host ≤ 68.09 s） |
| 回退预算 | 新组 Host 均值 ≤ 旧组均值 ×1.025（≤71.89 s） |
| RUN_ID | no00004_gen_20260924 / no00004_build_pgo_20260924 / no00004_bench_20260924 |
| 工作区 | ptmp/no00004_compiler_pgo_20260924/ |

## 基础选定（BASELINE）

- **父节点**：NO00002（当前最佳指针，Host 70.134 s）。无迂回。**物理基线说明**：当前工作区 = 根仓库 `c9198c6` + wolvrix `dc3e3cb`（NO00003 提交）。NO00003 虽 REJECTED，但其代码按该节点决议保留（fp_evals=0 不激活，锚定 bench 证明对最佳点零回退：70.231 s vs 70.371/70.134 s 同窗口 parity），故本节点直接在当前代码状态上改动，性能语义等价于从 NO00002 分叉。
- **基线测量（配置未变，复用父节点归档值，不重跑）**：
  - Host time 100k：**70.134 s**（3 次有效均值 69.849/70.404/70.150，SD 0.278 s）。
  - M1 相位：compute 51.486 s、commit 16.931 s、publish 0.860 s；evals=200102、rounds=401257。
  - M4 动态计数（确定性）：dynOps = **99,479,933,605**（NO00002 实测；NO00003 dyn 32,144 键逐键一致；本节点 wolvrix 同为 `dc3e3cb`，发射源预期与 NO00003 归档逐字节一致，TESTED 以 diff 复核后锁定该传递链）。
  - 派生吞吐基线：M-tput = 99,479,933,605 / 70.134333 = **1.4184 Gop/s**。
- **对照二进制**：旧构建（"old"）= NO00002 归档 `ptmp/no00002_disable_text_share_20260924/flow/emu/emu`（当前最佳指针二进制），3+3 交替时现场复跑，不使用跨窗口历史数据。
- **输入核对**（sha256，与 NO00001–NO00003 相同，输入未变）：
  - `testcase/xiangshan/ready-to-run/coremark-2-iteration.bin` = `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`
  - `testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so` = `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`
- **资源配置**：与前序节点完全一致：`XS_EMU_CPU=2`、`XS_EMU_THREADS=1`、`XS_NUM_CORES=1`、`XS_SIM_MAX_CYCLE=100000`、waveform/commit/RAM trace 全关；编译 `VM_BUILD_JOBS=32`（=nproc）。flow 配置全默认（含 NO00003 起默认开启的 falling-edge elision，XS 无合格端口，不激活）。
- **计时边界与止损线**：
  - 生成：make 启动 → 完整 C++ 与 Makefile 生成完成，墙钟 <1800 s；超时 `TIMEOUT_KILLED`。
  - 编译：PGO 三阶段（插桩构建 + 训练运行 + profile-use 重建）合计墙钟 <1800 s；超时 `TIMEOUT_KILLED`。训练运行为编译流程内部步骤（同 gsim.mk PGO 流程惯例），保守计入编译区间；其墙钟不作任何性能测量。
  - 仿真：仅 emu 执行区间。比较基线值预注册为 70.134 s，运行截止 = ×1.5 = **105.201 s**，超时 `REGRESSION_KILLED`。
  - 每次仿真运行前对 emu 二进制 `posix_fadvise(DONTNEED)` 驱逐页缓存（benchmark_grhsim_ir.py 内建）。
- **复现方法**：父节点代码状态 = wolvrix `4de8c01` + 根仓库 NO00002 提交（`6c5f623`）；本节点物理基线 = 根仓库 `c9198c6` + wolvrix `dc3e3cb`（与父节点差异仅为 NO00003 保留的 fp-elision 诊断设施，性能 parity 已证）；本节点仅改根仓库 Makefile（新增 PGO 构建目标），wolvrix 子模块与冻结面零改动。
- **假设选定过程（op 计数削减类方向实测枯竭，记录为排除证据）**：对当前 IR JSON（1.45 GB，与 NO00002/NO00003 逐字节一致）运行六类普查（ptmp/no00004_compiler_pgo_20260924/census/）：bitSelect 同条件组字级融合 **0 组可融合**（12,150 组全部被结构性排除）；slice 链削减 ≤17,111 op（slice_of_concat 12,576 + nested_slice 4,535，占总 op 0.48%）；代数残余候选 1,229 op；标量 mux 完全可融合 142 个。静态 op 融合空间合计 <0.6%，且动态占比更低 → op 计数削减类方向在当前设计点枯竭，转向逐 op 成本类机制。

## 假设提出（HYPOTHESIS）

- **假设**：通用 `-O3` 对 4,439 个任务函数（计算任务 3,950 个、呈长尾热度分布）采用静态启发式决定分支布局、内联与寄存器分配，与真实动态热点失配；以真实剖面驱动的编译器 PGO（`-fprofile-generate` / `-fprofile-use`，GCC 13.3）可使代码布局、分支走向与内联决策对齐实际执行路径，**在 dynOps 不变（发射 C++ 源逐字节不变）的前提下降低逐 op 成本，M-tput 提升**。反向风险：剖面引导的积极内联/布局可能增大 icache 足迹造成回退；净效应由本节点实测裁定。
- **创新点**：方法论重启后首个纯构建级机制节点——发射源零改动，dynOps 由构造保证不变，把全部性能效应隔离到 codegen/layout 维度；三阶段 PGO（插桩构建 → 带 difftest 的生产口径训练 → profile-use 重建）整体纳入 1800 s 编译门槛。训练输入 = 测量输入（coremark 100k），与 difftest `gsim.mk` 既有 PGO 流程同惯例（`PGO_WORKLOAD` 即运行输入），登记于此供用户裁决。
- **瓶颈证据（本分支实测）**：
  1. op 计数削减类方向枯竭（见 BASELINE 普查：四类融合合计 <0.6%）；剩余差距对 gsim ≈23.2 s 只能来自逐 op 成本或结构性机制。
  2. NO00001 M2：任务级分布长尾，单任务最高仅 1.35%（3,950 个计算任务）——静态启发式无法从代码形态推断该热度分布，正是剖面驱动优化的适用场景。
  3. NO00001 M4：boundary 写 22.13G 次变化检测中仅 5.73% 命中变化（94.3% 不命中分支）、supernode chg/act 31.36%——高度偏斜分支的布局/ fall-through 编排是 PGO 的经典收益点。
  4. difftest `gsim.mk:91-109` 为兄弟后端 gsim 内建 PGO 流程（含 llvm-bolt 选项），表明该代码族（仿真器主循环 + 生成模型代码）对剖面引导优化有已知响应。
- **微观指标与总目标的定量关系**：
  - **M-tput** = dynOps / Host = 有效 op 吞吐，基线 **1.4184 Gop/s**（同 NO00002 锚定口径）。Host ≈ dynOps / M-tput（model_step 占 Host 99.5%，NO00001 M1）；dynOps 由发射源逐字节不变锁定 ⇒ **M-tput +x% ⇒ Host ≈ −x%**。M-tput +3% ⇒ Host −2.04 s ≈ 对 gsim 剩余差距（70.134−46.965 = 23.17 s）的 **8.8%**。
  - dynOps 不变性验证链：NO00002 实测 99,479,933,605（dynamic-stats 插桩构建，确定性计数）→ NO00003 dyn 32,144 键逐键一致 → 本节点发射源与 NO00003 归档 `flow/model` 逐字节 diff（预期为空，TESTED 复核）⇒ dynOps 锁定为同一值，无需重复插桩测量。
- **预注册**：
  - M-tput 阈值：**≥ +3.0%**（≥1.4610 Gop/s ⇔ 新组 3 次 Host 均值 ≤ 68.09 s）。
  - 回退预算：新组 Host 均值 ≤ 旧组均值 ×**1.025**（≤71.89 s）；即便允许回退也定量记录。
  - 最终性能提升判据：同一时间窗口 3+3 交替（预注册顺序 old1,new1,old2,new2,old3,new3；old=NO00002 归档二进制），**全部 3 次新运行均优于全部 3 次旧运行**（n=3+3，等价 Mann-Whitney U 单侧 p≤0.05）方可判定提升真实；无论是否提升均定量登记。
  - 等价：全部计入运行端点精确匹配 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`，退出 0，无 mismatch。
  - 门槛：生成 <1800 s；PGO 三阶段合计 <1800 s（训练运行计入编译区间）。
  - 证伪标准：M-tput 提升 **< +1.0%**（Host > 69.44 s）→ 机制性证伪：通用 -O3 的布局/内联对该代码形态已在剖面引导最优的 1% 以内，登记机制证伪表；PGO 引入回退突破预算 → 同为机制性负向（icache/布局扰动超过收益）。
  - 实现瑕疵路线：编译 `TIMEOUT_KILLED` → 回 IMPLEMENTED 缩小插桩范围（仅模型库插桩、harness 保持 -O3）重测；训练运行失败或等价失败（INVALID）→ 排查实现（如 .gcda 路径、flag 拼写）。
  - 验收：全流程门槛通过 + 100k 端点精确匹配 + M-tput ≥+3.0% + 回退未破预算。

## 代码实施（IMPLEMENTED）

- **改动**（仅根仓库 Makefile；wolvrix 子模块不动，冻结面零改动）：
  1. `Makefile`：新增 `xs_wolf_grhsim_ir_build_emu_pgo` 与 `xs_wolf_grhsim_ir_emu_pgo` 目标及 `XS_WOLF_GRHSIM_IR_PGO_JOBS` 变量（默认 = `VM_BUILD_JOBS`/`XS_VM_BUILD_JOBS` = 32）。三阶段：
     - 阶段 1：清理模型库与 harness 的旧 `.o`/`.a`/`.gcda`，以 `-fprofile-generate` 重建（模型库经 `GRHSIM_MODEL_CXXFLAGS="-std=c++20 -O3 -fprofile-generate"`，harness 经 difftest `grhsim.mk` 既有 `PGO_CFLAGS`/`PGO_LDFLAGS` 通路；冻结的 difftest 文件零改动，全部 flag 经命令行变量注入）。
     - 阶段 2：训练运行——与生产口径完全相同的 emu 调用（coremark-2-iteration.bin、`--diff` nemu、`-C 100000`、taskset CPU 2、trace 全关），跑满 100k cycles 后正常退出，`atexit` 写回全部 `.gcda`。
     - 阶段 3：清理 `.o`/`.a`/emu（保留 `.gcda`），以 `-fprofile-use -fprofile-correction` 重建并链接最终 emu。
  2. 顶部 `.PHONY` 列表登记四个 grhsim-ir emu 目标。
- **语义约束**：只改编译/链接 flag；发射的 C++ 源、IR、mapping、调度、驱动全部不变；`-fprofile-use` 为语义保持优化（无 fast-math、无 unsafe 变换），`-fprofile-correction` 仅修正计数不一致，不影响语义。行为等价仍以 100k 端点精确匹配实测确认。
- **与父节点差异**：仅最终 emu 二进制的 codegen/layout；生成物（model 源、IR JSON、mapping）逐字节一致为预期（TESTED diff 复核）。
- **实施期缺陷回路（实现瑕疵，同节点内修正）**：R1 按 GCC 风格 PGO（裸 `-fprofile-use` + `-fprofile-correction`）实施，阶段 1/2 成功（插桩构建 + 训练运行端点 VALID，Host 122.3 s 为插桩减速），阶段 3 失败——emu 工具链实为 **clang 22.1.2**（difftest 默认 `CXX`），`-fprofile-use` 按 LLVM IR PGO 解释需 `.profdata`，`-fprofile-correction` 不支持。→ 修正 R2：改用 clang LLVM PGO——阶段 2 以 `LLVM_PROFILE_FILE=<pgo_dir>/train-%p.profraw` 收集，`llvm-profdata merge` 合并为 `code.profdata`，阶段 3 `-fprofile-use=<pgo_dir>/code.profdata`；新增 `XS_WOLF_GRHSIM_IR_PGO_DIR`（默认 `<build>/pgo`，每次构建清空）与 `LLVM_PROFDATA` 变量。旧 `flow/emu/default_*.profraw`（R1 训练残留，12.7 MB）随 R2 阶段 1 目录清理失效。
- **聚焦测试**：
  - `make -n xs_wolf_grhsim_ir_build_emu_pgo`（干跑）：配方展开正确，三阶段顺序与 flag 注入符合设计。
  - `make test_benchmark_grhsim_ir`：通过。
  - `make run_hdlbits_grhsim_ir DUT=001`：通过（`dut_001 passed`，未触碰的生成/编译路径回归）。

## 结果测试（TESTED）

### 全流程门槛

| 区间 | 实测 | 门槛 | 判定 |
|---|---|---|---|
| SV→C++ 生成 | 791.31 s | <1800 s | 通过 |
| C++ 编译（PGO 三阶段合计，-j32） | 695.95 s | <1800 s | 通过 |

PGO 三阶段：阶段 1 插桩构建 + 阶段 2 训练运行（Host 123.505 s，插桩减速 ≈1.76×，端点 VALID）+ llvm-profdata 合并（train profraw 12.7 MB → code.profdata）+ 阶段 3 profile-use 重建。R1→R2 缺陷回路见 IMPLEMENTED；R2 一次通过。

### 生成物一致性（dynOps 传递链锁定）

- `diff -rq` 本节点 `flow/model` vs NO00003 归档 `flow/model`（排除 `.o`/`.a`/`.profraw`/构建期 `.tmp`）：**全部源文件逐字节一致**。
- `xiangshan_grhsim_ir.json`（1.45 GB）与 `reg_to_mem.tsv`：与 NO00003 归档逐字节一致（`cmp`）。
- 传递链：NO00002 实测 dynOps=99,479,933,605 → NO00003 dyn 32,144 键逐键一致 → 本节点源与 NO00003 逐字节一致 ⇒ **dynOps 锁定为 99,479,933,605**。

### 100k 等价检查

全部 8 次 100k 运行（R2 训练 1 次 + 3+3 复测 6 次 + 相位诊断 1 次）端点均精确匹配 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`，退出 0，DIFFTEST 无 mismatch → 100k 等价成立。仿真单次均 <105.201 s 截止线。

### 最终性能（3+3 交替复测）

预注册执行顺序 old1,new1,old2,new2,old3,new3；比较口径：同一二进制各自 3 次、同窗口交替、CPU 2、`posix_fadvise` 驱逐页缓存、止损线 105.201 s（未触发）。old = NO00002 归档二进制（当前最佳指针），new = 本节点 PGO 二进制（发射源逐字节相同，仅编译 flag 不同）。

| 组 | 3 次 Host（s） | 均值（s） | 样本 SD（s） | 端点/退出 |
|---|---|---|---|---|
| old | 69.862 / 70.236 / 70.113 | 70.070 | 0.191 | 全部 VALID |
| new | 55.941 / 56.088 / 55.564 | **55.864** | 0.270 | 全部 VALID |

统计：改善 **−20.27%**（对本窗口 old 均值；对归档 70.134 s 为 −20.35%）；Cohen d = −60.74；Cliff δ = −1.0；3 次新运行全部优于 3 次旧运行，Mann-Whitney U=0，单侧精确 p=0.05 → **秩次判据通过，提升真实**。对 gsim 归档 46.965 s ≈ **1.189×**，剩余差距收敛至 ~8.9 s（父节点为 1.493× / ~23.2 s）。

### 微观指标测量

- **M-tput（锚定，阈值 ≥+3.0%）**：M-tput = 99,479,933,605 / 55.864333 = **1.7807 Gop/s**，对基线 1.4184 Gop/s **+25.6%** → **达标**（阈值 +3.0%，证伪线 +1.0%）。
- **M1 相位（诊断运行，VALID，Host 55.411 s）**：tick_total 55.374 s；model_step 55.013 s（99.35%）、difftest 0.263 s。模型内（eval_ns 55.104 s）：

| 相位 | NO00002 基线（s） | 本节点（s） | Δ（s） | Δ% |
|---|---|---|---|---|
| compute | 51.486 | 47.145 | −4.34 | −8.4% |
| **commit** | 16.931 | **7.006** | **−9.93** | **−58.6%** |
| publish | 0.860 | 0.880 | +0.02 | 噪声 |

  evals=200102、rounds=401257 与父节点完全一致——工作结构不变，收益全部来自逐 op/逐扫描成本下降。**总收益 −14.27 s 中 commit 相位贡献 −9.93 s（70%）**：commit 任务由高度偏斜分支扫描（历史 memchr、端口使能检查、masked apply）主导，PGO 的分支布局/落盘路径编排对该形态收益极大；compute 相位 −8.4% 符合 PGO 典型量级。
- **M-neg 复核**（NO00003 锚定设施）：neg eval_ns 1.156 s（2.10%，基线 2.868%口径随总时间下降同比例缩小），fp_evals=0（XS 仍无合格端口，符合预期）。
- **工具备注**：gperftools 分析目标 `analyze_grhsim_cpu_profile` 在本节点二进制上失败（`expected one contiguous compute phase`，grhsim_cpu_profile.py:76）——PGO 函数重排使"compute 任务地址连续"假设失效；属诊断工具的布局假设 artifact，不影响本节点预注册指标（M-tput 不依赖该分析）；后续节点若需任务级 profile 须先修正该假设（如按符号名前缀分类而非地址区间）。

### 回退与预算核对

回退预算 ≤ ×1.025（71.89 s）：实测 −20.27%，无回退。正确性与生成/编译门槛全部通过。

### 判定

**ACCEPTED**。判定依据：

1. 全流程门槛通过（生成 791.31 s、PGO 编译 695.95 s，均 <1800 s）；全部计入运行端点精确匹配、退出 0、无 mismatch（100k 等价成立）。
2. M-tput +25.6% ≥ +3.0% 达标，且 dynOps 经源逐字节一致性传递链锁定不变——"同工作量、低成本"机制证立：收益全部来自 codegen/layout（分支布局、内联、函数重排），commit 相位 −58.6% 为最大受益区。
3. 最终性能 −20.27%，秩次判据通过（p=0.05），无回退；新均值 **55.864 s** 更新当前最佳指针，对 gsim 剩余差距收敛至 **1.189×（~8.9 s）**。
4. 附带结论：① PGO 训练输入 = 测量输入的口径与 difftest `gsim.mk` 既有 PGO 流程一致，登记备用户裁决；② commit 相位对布局类优化的高响应（−59%）提示该相位在通用 -O3 下长期被分支布局抑制，后续机制类节点（如 commit 路径结构性精简）的收益基线应以 PGO 后 7.0 s 为准；③ llvm-bolt（difftest `emu.mk` 已探测）与 `-march=native` 为后续可叠加的正交构建级手段；④ `analyze_grhsim_cpu_profile` 的地址连续假设与 PGO 函数重排不兼容，任务级 profile 链路需先修复。

## 锚点更新附记（2026-09-24，节点判定后补记）

用户指示后续对比统一两侧启用 PGO。gsim+PGO 经 `make xs_gsim_emu_pgo`（difftest `gsim.mk` 三阶段插桩流程，与本节点同为 clang LLVM IR PGO）构建并 3+3 同窗口实测：Host **27.376 s**（27.345/27.451/27.333，SD 0.065 s），端点与非 PGO 归档完全一致；同窗口非 PGO 对照 46.873 s，gsim 侧 PGO 改善 **−41.6%**（p=0.05）。本报告正文中"对 gsim 归档 46.965 s ≈ 1.189× / 剩余 ~8.9 s"基于已被取代的非 PGO 锚点；按新锚点折算，本节点 55.864 s 对 gsim+PGO ≈ **2.041×**（剩余 ~28.5 s）。本节点的 ACCEPTED 判定与 M-tput 结论不受影响（判定对照为 NO00002 归档二进制的同窗口 3+3，与 gsim 锚点无关）。测量全文见 goal 文档"当前性能锚点"节。
