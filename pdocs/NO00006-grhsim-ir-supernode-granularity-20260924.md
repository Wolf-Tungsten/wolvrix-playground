# NO00006: compute supernode 粒度扫描（max-op 128→64）——活动精度/op 求值量曲线定标（优化）

| 字段 | 值 |
|---|---|
| 父节点 | NO00004（当前最佳；NO00005 为无代码改动的诊断节点，代码状态同源） |
| 角色 | 优化 |
| 状态 | REJECTED |
| 锚定指标 | M-act（动态 compute op 执行量 dynOps/cycle，确定性计数）；辅 M-tput（原生 instr/cycle） |
| 指标阈值 | M-act 降 ≥25%（预测 −40%~−55%）；M-tput 降 ≥6%（预测 −6%~−15%） |
| 回退预算 | Host 相对 55.864 s 允许回退 ≤+3%（≤57.540 s）；超出即负向结果 |
| RUN_ID | no00006_gen_20260924 / no00006_dyn_old_20260924 / no00006_dyn_new_20260924 / no00006_perfstat_20260924 / no00006_bench_20260924 |
| 工作区 | ptmp/no00006_supernode_granularity_20260924/ |

## 基础选定（BASELINE）

- **父节点**：NO00004（当前最佳指针，Host 55.864 s，PGO 构建）。无迂回：NO00005 为诊断节点、无代码改动，代码状态与 NO00004 同源（wolvrix `dc3e3cb` + 根仓库 `9bdda6d`）。本节点在其上改动唯一变量：compute supernode 粒度上限。
- **代码状态核对**：wolvrix `dc3e3cb`（工作区干净，`git status` 空）；根仓库 `9bdda6d`（工作区干净）；xiangshan 子模块未动。冻结面零改动。
- **输入核对**（sha256，与 NO00001–NO00005 相同）：
  - `coremark-2-iteration.bin` = `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`
  - `riscv64-nemu-interpreter-so` = `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`
- **基线测量（配置未变，复用归档值，不重跑未插桩基线）**：
  - Host：NO00004 归档 **55.864 s**（3 次有效均值，SD 0.270 s；PGO 二进制 `ptmp/no00004_compiler_pgo_20260924/flow/emu/emu`，端点 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`）。
  - 原生指令量：NO00005 归档 **479,295,135,474 instr**（3 次均值，极差/均值 1.9e-6，近确定）= **4.793 M instr/guest cycle**；其中 compute_task 80.18%（3.843 M/cycle）、commit_task 10.85%（0.520 M）、model_infra 3.64%、evaluator 3.57%。
  - M-act 基线：dynOps = **99,479,933,605**（NO00001 M4 动态插桩构建，确定性计数；per_eval=497,146，evals=200,102）。传递链：NO00002 报告 dynOps 逐键不变；NO00003→NO00004 发射源逐字节一致。**但 NO00003 起发射器含边沿分裂计时改动，为保证计数器定义同源，本节点用当前 wolvrix（`dc3e3cb`）对旧分区 checkpoint（NO00004 归档 `xiangshan_grhsim_ir.json`）重发 dynamic-stats 诊断构建，重测同计数器基线**（预期与 99.48G 一致，若不一致以重测值为基线并记录偏移）。
  - 静态结构基线（NO00001 M3）：supernode 32,101，op 均值 110.01（p50=120，p99=128，max=4096），boundary results 812,234（占 op 23%），boundary 写 22.13 G/cycle 换算 221 k/cycle。
- **gsim 环比口径（本节点新建立的活动粒度维度，估计法与假设须随指标一并登记）**：
  - 静态：supernode 84,643，op-typed enodes 5,018,786 → 均值 **59.3 enode/super**；subStep 函数 327 个、.text 67.1 MB（`nm --print-size` 实测）；源码 node= 赋值语句 3,412,030。
  - 动态估计：模型 instr/cycle = 1.926 M（NO00005 实测）= Σ(激活 super × 其静态指令数)。设 instr/enode 均匀 k ∈ [3.6, 5.3]（67.1 MB≈18.1 M instr ÷ [5.02 M, 3.41 M] enode 两口径），得 **enode 求值/cycle ∈ [363 k, 535 k]**；instr 加权活动率 ≈ 10.6%。**口径缺口**：gsim 无动态 enode 计数器（NO00005 登记，插桩 gsim codegen 涉参考面），本估计为区间，不作为精确判定依据。
  - 对比（ir 实测）：ir supernode 激活 9,934 次/cycle（993.4 M/100 k，M4）× 110 op = 995 k dynOps/cycle；gsim 估计激活 ~9 k supers/cycle × ~40–59 enode = 363–535 k。**两侧激活次数同量级，每次激活的 op 量差 ~2–2.6× —— op 求值量差距是粒度（每次激活执行的 op 数）驱动的。**
- **资源配置**：与 NO00001–NO00005 一致：`XS_EMU_CPU=2`、`XS_EMU_THREADS=1`、`XS_NUM_CORES=1`、`XS_SIM_MAX_CYCLE=100000`、waveform/commit/RAM trace 全关；编译 `VM_BUILD_JOBS=32`（=nproc，实测）；测量时机器空载；每次仿真运行前 `posix_fadvise(DONTNEED)` 驱逐 emu 页缓存。
- **计时边界与止损线**：
  - 生成：make 启动 → 完整 C++ 与 Makefile 生成完成，墙钟 <1800 s（NO00004 实测 880 s 量级；粒度细化会增加函数数，余量足够）；超时 `TIMEOUT_KILLED` 隔离产物。
  - C++ 编译：PGO 三阶段（插桩构建→训练→profile-use 重建）合计 <1800 s（NO00004 实测 695.95 s）；超时同上。
  - 仿真：仅 emu 执行区间。运行截止 = 55.864×1.5 = **83.796 s**（基线取归档均值，预注册）；dynamic-stats 插桩诊断运行参照 NO00001 先例放宽至 300 s 上限（时间不进基线）。
  - perf stat 运行为插桩诊断运行，Host 读数记录但不入性能基线；instructions 计数不受采样开销影响。

## 假设提出（HYPOTHESIS）

- **假设**：GrhSIM-IR 的 compute supernode 粒度（上限 128 op，均值 110）处在"活动精度—结构开销"折曲线的过粗侧。每次激活执行整个 body（代码形态已核实：unit 内 op 无条件顺序执行），而激活由任一 boundary 输入变化触发（扇出置 unit flag），69% 的激活不产生任何 boundary 变化（M4：productive group calls=29.88%）。把粒度上限降至 64（逼近 gsim 的 59.3 enode/super 工作点）将按子锥精度跳过未激活子图，**dynOps/cycle 显著下降**；若 boundary 写回/扇出/调度扫描的增长低于 op 求值量的节省，原生 instr/cycle 与 Host 净改善。单变量实验同时为后续结构节点（锥级子守卫、boundary 成本治理）定标响应曲线。
- **创新点**：方法论重启后首个分区粒度单变量响应实验；以 gsim 的工作点（59.3 enode/super、~10.6% 活动率）为环比锚，直接检验核心科学问题的一个可迁移命题——**"同一负载的 op 求值量由激活粒度决定，每激活 op 数 ≈ 粒度上限"**。同时订正 NO00005 的一个候选方向表述：其"compute 表达密度 3.86→~2 instr/dynOp"的目标假设 gsim 逐 op 更密，本节点基础选定阶段的实测证据表明 **gsim 逐 enode 成本反而更高（静态 3.6–5.3 instr/enode vs ir 3.86 instr/dynOp 动态实测）**，gsim 的优势在 op 求值量（2–2.6× 更少）与无 commit/infra/evaluator 结构相位（0.865 M/cycle），不在逐 op 密度——密度方向（ir 已 3.86 instr/op，gsim 更胖）不是差距主因。
- **瓶颈证据（本分支实测 + 本节点基础选定阶段新增）**：
  1. NO00005：2.04× Host = 2.44× instr × 0.84 CPI（ir 优）；compute_task 3.843 M instr/cycle = 995 k dynOps × 3.86。
  2. 本节点实测反汇编（PGO 二进制）：常规 compute 任务（cpu_task_500/70）指令构成 alu 53%、load+store 35–40%（其中 stack 溢出/帧 ~20–29%）、控制 ~10%；最小编译实验证实 `std::byte` 帧 + `cpu_at` 模式在 LLVM IR 层被完全提升为 SSA（task_500 编译后 0 alloca、0 memset）——**帧不是成本，寄存器溢出才是**；gsim 侧 subStep296 实测 111,528 instr / 8,580 node 赋值 = 13.0 instr/enode、stack 占 64%（巨型函数溢出），证明 gsim 逐 op 更胖，其优势不在密度。
  3. M4（NO00001）：supernode 激活 993.4 M、productive 29.88%、chg/act 31.36%、quiescence 跳过 8.94%——激活计数两侧同量级（ir 9.93 k vs gsim ~9 k /cycle），每激活 op 数 110 vs ~40–59 是求值量差距的结构性来源。
  4. 粒度上限实际束缚：M3 p50=120、p99=128（上限 128 绑定，合并器想合更多被截断）——当前工作点是上限人为设定而非自然锥结构，向细侧有可扫空间。
- **微观指标与总目标的定量关系**：
  - **M-act** = dynamic-stats 构建的 `total_dynamic_compute_ops`（`make analyze_grhsim_dynamic` 输出；固定二进制+固定输入下为确定性计数，逐次一致；确定性来源：计数器为执行路径上的精确递增，不含采样）。Host ≈ instr × CPI / 频率；instr 中 compute 部分 ≈ dynOps × 3.86 → M-act 每 −10% ≈ compute instr −10% ≈ 总 instr −8% ≈ Host −4.5 s（CPI 不变假设，NO00005 频率闭合 0.03% 支持该线性传导）。
  - **M-tput** = 生产口径（difftest 开）perf stat `instructions:u` 全程计数 ÷ 100 k guest cycle；基线 4.793 M/cycle。该指标直接度量"映射到宿主的工作量"，与总目标的定量关系同 NO00005（instr 比 × CPI 比 = Host 比）。
  - 辅助登记：静态 unit 数/均值（生成日志 `compute_supernodes=` + IR JSON 普查）、boundary 写总量（dynamic-stats Σwr）、instr/dynOp 密度（预期上升，为机制代价而非失败）、rounds/evals、evaluator 份额（perf record 可选）。
- **预注册**：
  - **判定阈值**：M-act 降 ≥25%（预测 −40%~−55%：粒度 110→~55–65 且子锥精度接近 gsim 工作点）；M-tput 降 ≥6%（预测 −6%~−15%：op 节省 −0.6~−1.3 M/cycle 对 boundary 写回 +0.3~+0.5 M、扇出 +0.1 M、调度扫描 +0.05 M 的净值）。两阈值同时达成且门槛通过为 `ACCEPTED`。
  - **回退预算**：Host 3+3 交替均值相对 55.864 s 回退 ≤+3%（≤57.540 s）；实际值如实登记，改善亦如实登记。
  - **证伪标准**：
    - F1：M-act 降 <15% → unit 内活动锥近乎一致（合并未引入异构激活），粒度前提机制性不成立 → `REJECTED`。
    - F2：M-act 降 ≥25% 但 M-tput 降 <3% → boundary 写回+扇出+调度增长吞没 op 节省，粒度方向在该工作点机制性不成立 → `REJECTED`（机制证伪表登记增长率，供锥级子守卫方向引用——后者不增 boundary）。
    - 正确性/门槛失败（`INVALID`/`TIMEOUT_KILLED`/`REGRESSION_KILLED`）→ 按实现瑕疵处理，节点内修正重测。
  - **测量方法与运行秩序**：
    - M-act：当前 wolvrix 对**新**（cap64，本节点全流生成）与**旧**（cap128，NO00004 归档 checkpoint）两个 mapped checkpoint 分别重发 dynamic-stats 诊断构建（同计数器定义），各跑 100k 生产配置，`make analyze_grhsim_dynamic` 取 `total_dynamic_compute_ops`；端点四字段精确匹配方计入。确定性计数精确比对，不做统计检验（说明确定性来源）。
    - M-tput：新 PGO 二进制 perf stat 3 次（事件组 `cycles:u,instructions:u` 等，同 NO00005 pass1），与 NO00005 归档 ir 值（479.295 G，3 次均值）比对；gsim 侧 196.545 G 作环比锚。计数近确定性（NO00005 实测极差/均值 ≤1.9e-6），阈值按点估计判定并报告离散度。
    - Host：3+3 交替，顺序 **old1,new1,old2,new2,old3,new3**（预注册），同窗口、CPU 2、逐次 fadvise；任一构建 `INVALID` 该次作废补跑，两组各保 3 次有效；报告均值、离散度与秩次判据（全部 3 次新优于全部 3 次旧方判提升真实）。
    - 生成/编译门槛：墙钟计时写 `*.time`，超时即 `TIMEOUT_KILLED`。

## 代码实施（IMPLEMENTED）

- **实施内容（单变量配置实验，零 C++/Python 语义改动）**：全流生成调用追加 `XS_WOLF_GRHSIM_IR_MAX_OP_IN_COMPUTE_SUPERNODE=64`（Makefile:931 既有接线 → `scripts/wolvrix_xs_grhsim_ir.py --max-op-in-compute-supernode 64` → 映射管线 `cpu.st.merge-compute-supernodes` 的上限参数；管线默认值 128 见 `wolvrix/lib/grhsim/backend/cpu_partition.cpp:541`）。wolvrix 子模块、发射源、脚本零改动；冻结面零改动。判定后若 `ACCEPTED`，把 64 固化进 Makefile 默认值再提交；若 `REJECTED`，工作区无可回退代码改动（实验全部经命令行变量与 ptmp 产物完成）。
- **语义约束**：粒度上限只改变 compute supernode 的合并截断点，等价于把同一组 op 的激活分组细化；op 语义、调度拓扑序、commit/publish 相位、boundary 读写语义均不变（分组合法是管线既有能力，cap 为其参数）。等价性以 100k 端点四字段精确匹配判定。
- **与父节点差异**：唯一差异 = compute supernode 粒度上限 128→64；预期静态 effect：unit 数 32,101 → ~55k–65k，boundary 值比例上升。
- **聚焦测试**：
  - knob 接线干跑：`make -n xs_wolf_grhsim_ir ... XS_WOLF_GRHSIM_IR_MAX_OP_IN_COMPUTE_SUPERNODE=64` 输出含 `--max-op-in-compute-supernode 64`（1 处，实命令行）→ 接线正确。
  - 同计数器 dynOps 基线链：当前 wolvrix（`dc3e3cb`）对 NO00004 归档 mapped checkpoint 重发 dynamic-stats 构建（`make reemit_grhsim_ir GRHSIM_REEMIT_DYNAMIC_STATS=1`，reemit 49.92 s 先例）+ `xs_wolf_grhsim_ir_build_emu` 编译（229.53 s 先例）——消除 NO00003 边沿分裂发射改动带来的计数器定义漂移风险。
  - 驱动脚本（ptmp 内，节点证据的一部分）：`dyn_old_build.sh`（基线链）、`dyn_run.sh`（300 s 上限诊断运行 + fadvise + CPU 2）、`gen_build_pgo.sh`（全流 gen + PGO 三阶段，各 1800 s 门槛）、`measure.sh`（perf stat 四 pass + 3+3 bench）。

（执行进度记录随阶段推进追加。）

- **执行记录**：同计数器基线链闭合——dyn-old（cap128，当前 wolvrix 重发）`total_dynamic_compute_ops=99,479,933,605`，与 NO00001 M4 逐键一致（totals 行 grp_pub=854663081 等全等），NO00003 发射改动不影响计数器定义；端点四字段精确匹配，退出 0。全流 gen 日志含 `cpu.st.merge-compute-supernodes {'max_op_in_compute_supernode': 64}` → knob 生效证据。

## 结果测试（TESTED）

### 全流程门槛

| 区间 | 实测 | 门槛 | 判定 |
|---|---|---|---|
| SV→C++ 生成 | 774.92 s（`gen.time`，exit=0） | <1800 s | 通过 |
| C++ 编译（PGO 三阶段合计，-j32） | 629.94 s（`build.time`，exit=0；插桩训练运行 Host 120.65 s，较 NO00004 插桩训练 148.67 s −18.8%——早期工作量信号） | <1800 s | 通过 |

### 等价性与运行有效性

全部计入运行端点四字段精确匹配 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`、退出 0、无 mismatch：sanity 1 次、dyn-old/dyn-new 各 1 次、native 四 pass 13 次、bench 6 次（harness 逐运行校验）。止损线（83.796 s）未触发；dyn 插桩运行按预注册 300 s 上限完成。

### 静态分区响应（knob 生效确认）

| 指标 | cap128（NO00004） | cap64（本节点） | Δ |
|---|---|---|---|
| compute supernode 数 | 32,101 | 58,346 | 1.817× |
| op/unit 均值（p50） | 110.01（120） | 60.53（60） | −45.0% |
| boundary results（静态） | 812,234 | 830,897 | +2.30% |
| boundary results/unit | 25.30 | 14.24 | −43.7% |
| 任务函数数 / 生成代码行 | 4,439 / 9.62 M | 4,738 / 10.19 M | +6.7% / +5.9% |

### M-act（锚定指标，确定性计数；同计数器基线链闭合）

| 指标 | cap128（dyn-old 重测） | cap64（dyn-new） | Δ |
|---|---|---|---|
| **total_dynamic_compute_ops** | **99,479,933,605** | **83,557,057,049** | **−16.01%** |
| per_eval | 497,146.1 | 417,572.3 | −16.01% |
| supernode 激活 sn_act | 993,413,585 | 1,595,930,620 | **+60.64%** |
| ops/activation（换算） | 100.15 | 52.35 | −47.72% |
| sn_act pos / neg | 928.6 M / 64.8 M | 1,470.2 M / 125.7 M | +58.3% / +94.0%（neg 份额 6.52%→7.88%） |
| grp_pub（扇出发布） | 854,663,081 | 1,298,125,500 | +51.89% |
| boundary 写总量（Σwr） | 22,134,521,354 | 18,989,969,258 | **−14.21%** |
| chg/act 均值 | 31.36% | 28.52% | −2.84 pp |
| quiescence 跳过率 | 8.94% | 11.08% | +2.14 pp |
| rounds 结构 | 199049×2+1053×3 | 同左逐键一致 | 0 |

**判定：M-act −16.01% 未达预注册阈值 ≥25%（F1 证伪线 <15% 以 1.0 pp 之差未触发）。** 机制分解：粒度按预期减半（ops/activation −47.7%），但**激活数 +60.6%**（扇出发布 +51.9%：同一逻辑消费者被摊入更多单元，value→consumer-unit 边数随单元数增长）——净弹性仅 ≈−0.2（单元数 +81.7% 换 dynOps −16.0%）。F2 情景未发生：boundary 写非但不增反而 −14.2%（随 op 求值量同步下降）。

### M-tput（perf stat，生产口径 difftest 开；近确定性计数）

| 指标 | cap128（NO00005 归档） | cap64（本节点 3 次） | Δ |
|---|---|---|---|
| instructions:u（3 次均值） | 479,295,135,474 | 450,308,346,634（spread/mean 2.0e-6） | **−6.05%** |
| cycles:u | 276,688,677,478 | 276,802,313,789 | +0.04% |
| CPI | 0.5773 | 0.6147 | **+6.49%** |
| branch-misses /Kinst | 2.296 | 3.155 | +37.4% |
| L1-icache miss /Kinst | 1.742 | 2.077 | +19.2% |
| iTLB miss /Kinst | 1.838 | 1.949 | +6.0% |
| L1-dcache miss 率 | 4.754% | 4.735% | ≈0 |
| 模型净 instr（nodiff） | 478,051,881,960 | 449,066,041,242 | −6.07%（对 gsim 差距 2.4477×→2.2993×） |

**判定：M-tput −6.05% 达预注册阈值 ≥6%（边际达成）；但被 CPI +6.49% 完全抵消（cycles +0.04%）。** 每消除 1 dynOp 仅省 1.82 条指令（平均密度 3.86 的 47%——被跳过的恰是最便宜的静默重算 op），同时细分结构抬升前端/分支成本：branch-miss 密度 +37%（2.296→3.155，ir 对 gsim 3.76 的分支优势大部丧失）、icache +19%——NO00005 警示的"工作量削减须警惕回吐 CPI 优势"在此兑现。相位归因（perf record）：compute 80.18→81.00%、commit 10.85→10.71%、**evaluator 3.57→4.55%（+0.98 pp，调度扫描增长）**、model_infra 3.64→2.19%。gsim 锚点同窗口复核稳定：196.545 G instr / 27.362 s（归档 196.545 G / 27.376 s）。

### Host（3+3 交替，预注册顺序 old1,new1,old2,new2,old3,new3）

| 组 | 3 次有效（s） | 均值 | SD |
|---|---|---|---|
| old（NO00004 PGO 归档） | 56.045 / 56.009 / 55.308 | 55.787 | 0.416 |
| new（cap64 PGO） | 56.290 / 55.820 / 55.410 | 55.840 | 0.440 |

Δ = **+0.09%**；秩次判据不通过（max(new) 56.290 > min(old) 55.308），Mann-Whitney 单侧精确 p=0.65，Cohen d=+0.12。**Host 持平**，回退预算（+3%）未突破；提升不成立。

### 定量复盘与判定依据（负向结果）

预注册验收要求 M-act ≥25% 与 M-tput ≥6% **同时**达成；M-act −16.01% 未达标 → 负向结果。二选一判定：

- **非实现瑕疵**：knob 行为与假设的机制路径逐环吻合——粒度 −45%（静态）、ops/activation −47.7%（动态）、boundary 值 +2.3%、计数器基线链闭合、等价性/门槛全绿；不存在"假设成立而实现有误"的证据。
- **机制性错误（判定）**：假设的核心前提是"激活次数由设计固有传播决定、近似不随粒度变化"，实测**激活数随单元数近线性增长（+60.6% vs 单元数 +81.7%）**——激活由 value→consumer-unit 扇出边密度驱动，细化把同一消费者集合摊入更多单元，每激活 op 节省被激活增长抵消（弹性 ≈−0.2 而非 −1.0）。残余 instr 节省（−6.05%）再被 CPI 恶化（+6.49%，dispatch 分支 +37%、icache +19%）全数吞没，Host 持平。

**判定：REJECTED。** 机制证伪表登记：①尺寸上限细化不能有效降低 dynOps（弹性 ≈−0.2，激活数受扇出边密度控制）；②gsim 的低 op 求值量并非粒度效应——同尺寸（~60 op）下 ir 单元激活率 27.4%/cycle 对 gsim ~10.6%（instr 加权估计）仍差 ~2.6×，差距主因在**激活率/扇出精度结构**（gsim 单 pass 静态序 + 逐 super 精确扇出）而非单元大小；③细化的 CPI 代价单调为负。后续节点方向修正：激活率机制（支撑集纯化锥、输入端口级精度、扇出结构/单 pass 调度）优先于尺寸参数；尺寸上限 128 维持（无证据支持移动）。

### 产物登记

- 新 PGO 二进制：`ptmp/no00006_supernode_granularity_20260924/flow/emu/emu`（参与 bench 的 sha256 见 `bench/preregister.json`）；dyn-old/dyn-new 诊断构建及 `[grhsim-dyn]` 日志、native 四 pass summary、bench summary 均归档于 `ptmp/no00006_supernode_granularity_20260924/`。
- 当前最佳指针不动（NO00004，55.864 s）；本节点最终性能 55.840 s（3+3 均值，对归档 −0.04%，噪声内持平）如实登记。
- 代码改动：无（实验全程经命令行变量完成；REJECTED 判定 → 不把 64 固化进 Makefile，工作区保持父节点状态）。
