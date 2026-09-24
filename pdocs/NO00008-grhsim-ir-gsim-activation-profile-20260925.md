# NO00008: gsim 动态激活口径建立——super 激活/动态 enode/逐 super fire 分布，dynOps 差距三因子测量分解（诊断）

| 字段 | 值 |
|---|---|
| 父节点 | NO00004（当前最佳，诊断节点无代码分叉） |
| 角色 | 诊断 |
| 状态 | ACCEPTED |
| 锚定指标 | M-gact（gsim super 激活/cycle）、M-gwork（gsim 动态 node/enode 执行/cycle）；交付双侧因子分解表 F（changes × act/change × work-per-activation） |
| 指标阈值 | 诊断节点以交付定量基线为验收（口径与判定线见「假设提出 · 预注册」） |
| 回退预算 | 无性能语义改动；当前最佳指针不动（55.864 s），如实登记 |
| RUN_ID | no00008_rtprof_build_20260925 / no00008_rtprof_run_20260925 |
| 工作区 | ptmp/no00008_gsim_activation_profile_20260925/ |

## 基础选定（BASELINE）

- **父节点**：NO00004（当前最佳指针，GrhSIM-IR PGO 构建 Host 55.864 s）。诊断节点，无代码分叉、无迂回；产出 gsim 侧首批动态激活口径与 dynOps 差距的测量分解，供后续优化节点锚定阈值。
- **立项动机（为什么是现在）**：NO00005 把 2.041× Host 差距分解为原生指令量 2.4477× × CPI 0.8389，剩余路径是模型净工作量削减；NO00006/NO00007 分别证伪 dynOps 两个乘数（单元尺寸、单位内输入精度），两条证伪登记都指向激活结构因子（**变化流密度**、**act/change**、**单 pass 调度**）作为剩余候选。但 gsim 侧这些因子目前全部是**估计值**：激活率 ~10.6%/cycle 是 NO00006 的 instr 加权推断，changes/cycle 无测量，逐 super 执行分布无数据。下一个优化节点（监测值密度、扇出精度、commit 结构）的预注册阈值无法用估计值辩护——本节点先用 gsim 原生 runtime profile 设施把动态口径测实。
- **测量路径（零冻结面改动）**：gsim 源码树（`reference/gsim`）当前版本内建 runtime profile codegen 选项（`cppEmitter.cpp` `emitRuntimeProfile()`，env `GSIM_EMIT_RUNTIME_PROFILE` 控制；计数器：active_supernodes / nodes / ref_enodes / non_ref_enodes / 逐 super `runtimeProfileFireCount[]` + emit 期静态 cost TSV + stats JSON）；difftest `gsim.mk:29,50-52` 有既有变量通路 `GSIM_EMIT_RUNTIME_PROFILE`（模型 codegen 与 harness `-DGSIM_RUNTIME_PROFILE` 两侧均经命令行变量注入，冻结的 difftest 文件零改动）；difftest `emu.cpp:101,361` 既有 `EMU_RUNTIME_PROFILE` 链路（init 启用计数、退出 dump）。模型经根仓库新 Make 目标重新生成到**独立构建目录** `build/xs/gsim-rtprof`（未跟踪产物）；锚定二进制（`build/xs/gsim-pgo`、NO00004 flow 归档）不触碰。该路径与 NO00005 规避的"插桩 gsim codegen"不同：不修改、不补丁任何 gsim/difftest 源文件，仅使用源码树已合并的既有特性与变量通路（与 `--dump-stats-json` 同类）。
- **基线测量（配置未变，复用归档值，不重跑）**：
  - GrhSIM-IR 当前最佳：Host **55.864 s**（NO00004，3 次有效均值，SD 0.270 s）；端点 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`。
  - gsim+PGO 锚点：Host **27.376 s**（3 次有效均值，SD 0.065 s）；端点 `instrCnt=238550、cycleCnt=99998、guest=100001、PC=0x80000b40`。差距 **2.041×（~28.5 s）**。
  - ir 侧动态因子（NO00001 M4 / NO00006 dyn-old 归档，当前代码态同计数器定义逐键一致）：
    - dynOps = **99,479,933,605**（994,792/guest cycle；evals=200,102，per_eval=497,146）；
    - supernode 激活 **993,413,585**（9,934/cycle），body 执行 904,557,815（9,045/cycle），quiescence 跳过 8.94%；
    - boundary 写 **22,134,521,354**（221,343/cycle），真变化 **1,267,630,634**（**12,675 changes/cycle**，变化率 5.73%），silent 7.07%；
    - ops/unit 均值 110.01；boundary results 812,234（25.30/unit）；chg/act 31.36%；productive 29.88%；
    - compute_task 3.843 M instr/cycle（3.86 instr/dynOp）；commit_task 0.520 M；model_infra 0.174 M；evaluator 0.171 M（NO00005 M-attr）。
  - gsim 侧静态（`build/xs/gsim-pgo/gsim-compile/model/SimTop_supernode_stats.json`，NO00007 勘察引用同源）：supernodes **84,643**；active_source_nodes（监测值）**442,722**；activation_edges **1,379,970**（**3.117 consumer/监测值**）；always_active **111**；静态 enode 口径（NO00005 M-shape）：op-typed enodes 5,018,786（+1,137,900 OP_INT 常量）。
  - gsim 侧动态（本节点前仅有估计）：激活率 ~10.6%/cycle（NO00006 instr 加权推断）、动态 enode ~532k/cycle（由估计派生）——**均被本节点测量取代**。
- **输入核对**（sha256，与 NO00001–NO00007 相同，输入未变）：
  - `testcase/xiangshan/ready-to-run/coremark-2-iteration.bin` = `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`
  - `testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so` = `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`
- **代码状态核对**：wolvrix `dc3e3cb`（工作区干净）；根仓库 `6a05c53`（NO00007 提交）；xiangshan/reference 子模块不动。冻结面（GRH IR、GRH 已有 pass、XiangShan 与测试源码）零改动；reference/gsim 零改动（仅用既有特性）；根仓库改动仅为测量设施（Makefile 目标 + 分析脚本 + 单测）。
- **资源配置**：与 NO00001–NO00007 一致：`XS_EMU_CPU=2`、`XS_EMU_THREADS=1`、`XS_NUM_CORES=1`、`XS_SIM_MAX_CYCLE=100000`、waveform/commit/RAM trace 全关；编译 `VM_BUILD_JOBS=32`；测量时机器空载；逐次 `posix_fadvise(DONTNEED)` 驱页缓存。
- **计时边界与止损线**：
  - 诊断构建（模型重生成 + emu 编译）：墙钟如实记录；诊断构建不走全流程门槛（先例 NO00001/NO00007：诊断构建计时不进门槛），但参照量级登记（gsim 侧归档：模型生成 ~769 s、编译 ~385 s）。
  - 诊断仿真：计数器插桩使 emu 减速，时间不进任何性能基线；运行上限 **300 s**（NO00001 起先例）；超时记 `REGRESSION_KILLED`（诊断口径），失败 `INVALID`。
  - 本节点无生产构建、无 3+3 性能复测（无性能语义改动）。

## 假设提出（HYPOTHESIS）

- **假设（诊断性）**：ir 与 gsim 的模型工作量差距（compute 3.843 M vs model_step 1.926 M instr/cycle）可在各自口径内分解为 **changes × act/change × work-per-activation** 三因子。ir 侧三因子已实测（12,675 changes/cycle × 0.784 act/change × 110.01 ops/body ⇒ 994.8k dynOps/cycle，闭合）；gsim 侧静态结构（442,722 监测值、3.117 consumer/值、84,643 supers、~59.3 op-typed enode/super）暗示其变化流密度显著更低，但动态值未测。本节点测量 gsim 三因子，给出闭合的双侧因子表 F，定量回答：2.04× 指令差距中，**变化事件数**、**每变化激活数**、**每激活工作量**、**每 op 指令密度**各占多少——直接决定下一优化节点的立项方向（监测值密度削减 / 扇出精度 / 每激活工作量 / 表达密度）。
- **创新点**：本分支首个 gsim 侧**动态**激活口径（原生 runtime profile 设施在本 goal 树首次启用；与 NO00005 的 PMU/采样口径互补——那是"花了多少周期/指令"，这是"执行了多少 super/enode/变化检测"）；逐 super fire 计数 × 静态 cost TSV 连接给出 gsim 侧首个 op 执行 Pareto 与 super 类别归因（n_sink 标记的状态写 super ≈ ir 的 commit 对应物，a_succ 标记的监测成员数 ≈ ir 的 boundary 写变化检测对应物）。
- **瓶颈证据（本分支实测）**：见 BASELINE 立项动机与基线表——NO00006/NO00007 两条证伪均把"激活率/扇出精度结构"指为剩余主因，但 gsim 侧动态因子缺失使该结论停留在静态推断（激活率 10.6% 为估计，其闭合误差未评估）；M-attr 显示 ir 的 commit+infra+evaluator 结构开销 0.865 M/cycle（18.1%）在 gsim 侧"无对应类别"，但 gsim 的寄存器更新工作折叠在 subStep 内未分离——其真实份额须由逐 super 数据回答。
- **微观指标与总目标的定量关系**：
  - **M-gact** = gsim `active_supernodes / guest cycles`（runtime profile 行，确定性计数）。与总目标关系：activations 是 gsim 模型工作的调度量子；与 ir 的 9,934 act/cycle 同维度环比。
  - **M-gwork** = `nodes / cycles`（动态 member node 求值）与 `total_enodes / cycles`（动态表达式树节点）两行。gsim 的 node ≈ ir 的 boundary+local value 求值、enode ≈ ir 的 op——口径差异在报告中显式标注，跨侧比值仅作量级参照；同侧内 instr/M-gwork = gsim 的每动态节点指令密度 k_gsim（与 ir 3.86 instr/dynOp 同维度，回答"每 op 密度是否还有空间"——此前仅由 10.6% 估计值推断 ~3.6）。
  - **M-gchg（派生）** = (active_supernodes − always_active_fires) / 3.117（静态 unique activation edges / 监测值）；派生依据：稳态下 flag 置位 ≈ flag 消费 = 激活数，每变化事件平均置 3.117 个 consumer 位；always-active super（111 个）每 cycle 无条件激活须先扣除。派生量与实测量分栏登记，不确定度在报告中评估。
  - **因子表 F**：双侧 changes/cycle、act/change、work/activation、dynOps(dynEnodes)/cycle、instr/dynOp(enode)、instr/cycle，给出逐因子比值与闭合残差（指令比 = 各因子比之积，残差 ≤10% 判闭合，超出登记缺口）。
  - **逐 super 分布**：fire TSV × 静态 TSV 连接 → gsim op 执行 Pareto（Top super 份额、长尾形态对 ir M2/M-attr）；n_sink>0 super 的 fire 加权份额 = gsim 状态写工作（ir commit 0.520 M/cycle 的对应物）；Σ fire×a_succ = gsim 变化检测比较次数/cycle（ir 221,343 boundary 写检测/cycle 的对应物）。
- **预注册**：
  - **测量方法与运行秩序**：`make xs_gsim_emu_rtprof`（新目标，`GSIM_EMIT_RUNTIME_PROFILE=1`，构建目录 `build/xs/gsim-rtprof`）→ `make run_xs_gsim_emu XS_GSIM_BUILD=build/xs/gsim-rtprof`，经 `XS_EMU_PREFIX` 注入 `EMU_RUNTIME_PROFILE=1`、`GSIM_SUPERNODE_TSV=<ptmp 路径>`、`taskset -c 2`（既有注入模式，不改运行目标命令结构）；逐次 posix_fadvise 驱页缓存；共 2 次运行。
  - **有效性门槛**：两次运行端点精确匹配 `instrCnt=238550、cycleCnt=99998、guest=100001、PC=0x80000b40`，退出 0，无 mismatch（插桩不改变行为）。
  - **确定性门槛**：两次运行的 `[GSIM_RUNTIME_PROFILE]` 四计数与 fire TSV **逐字节一致**（固定输入下确定性计数）；不一致则排查非确定来源并降级相关结论。
  - **模型一致性门槛**：再生成模型的 `SimTop_supernode_stats.json` 与锚定构建 `build/xs/gsim-pgo/gsim-compile/model/` 同名文件逐字节一致（证明同一 RTL/FIRRTL/codegen 参数，唯一差异为计数器注入；生成 cpp 因计数器行与 8192 KB 文件切分位移不做逐字节要求）。
  - **闭合判定线**：因子表 F 指令比闭合残差 ≤10%（ir 侧残差已由 M-vol/M-attr 闭合；gsim 侧 model_step 1.926 M/cycle 对 M-gwork×k_gsim）。
  - **证伪标准**：本节点为诊断节点，无机制假设可证伪；若 runtime profile 链路无法产出 VALID 数据（构建失败、端点不符、计数非确定），记录口径缺口，对应指标不交付。
  - **验收（诊断节点）**：全部有效性/确定性/一致性门槛通过 + M-gact/M-gwork/M-gchg/变化检测对比口径/逐 super Pareto/类别归因交付 + 因子表 F 闭合 + 当前最佳指针不动（55.864 s 如实登记）。

## 代码实施（IMPLEMENTED）

诊断节点，无生产语义改动（不改 wolvrix 子模块、不改 reference/gsim、不改 difftest/测试源码、不改任何锚定构建产物；冻结面零改动）。改动为测量设施（均根仓库）：

1. **`Makefile`**：
   - 新增 `XS_GSIM_RTPROF_BUILD`（默认 `build/xs/gsim-rtprof`，独立构建目录，不触碰锚定的 `build/xs/gsim` 与 `build/xs/gsim-pgo`）。
   - 新增 `xs_gsim_emu_rtprof` 目标：镜像 `xs_gsim_emu` 的 difftest `gsim.mk` 调用，唯一差异为命令行注入 `GSIM_EMIT_RUNTIME_PROFILE=1`（gsim.mk 既有变量通路：codegen 经 env 传至 gsim 二进制，harness 经 `-DGSIM_RUNTIME_PROFILE`；冻结的 difftest 文件零改动）。
   - 新增 `analyze_gsim_runtime_profile`（驱动新脚本；变量 `GSIM_RTPROF_IR_DYN_LOG / GSIM_RTPROF_OUTPUT / GSIM_RTPROF_RUNS / GSIM_RTPROF_CUTOFF`）与 `test_gsim_runtime_profile_compare`。
2. **`scripts/gsim_runtime_profile_compare.py`**（新）：
   - 纯函数解析器（单测覆盖）：`[GSIM_RUNTIME_PROFILE]` 行、fire TSV、静态 cost TSV、stats JSON、生成 cpp 内 `runtimeProfile*Weight[i] = N;` 权重赋值、`[grhsim-dyn]` 日志（totals/kind/sn 行）；因子表 `factor_table` 与逐 super `super_pareto` 为纯函数。
   - 编排：模型一致性门（再生成 `SimTop_supernode_stats.json` 与锚定 `build/xs/gsim-pgo/.../model` 同名文件逐字节比对）→ 2 次诊断运行（`make run_xs_gsim_emu XS_GSIM_BUILD=build/xs/gsim-rtprof`，`XS_EMU_PREFIX` 注入 `EMU_RUNTIME_PROFILE=1` + `GSIM_SUPERNODE_TSV` + `taskset -c 2`，逐次 `posix_fadvise` 驱页缓存，进程组看门狗 cutoff+30 s SIGKILL，端点精确校验）→ 确定性门（两次 profile 行与 fire TSV 完全一致）→ 因子表 + Pareto + 类别归因，输出 `summary.md/json`。
   - ir 侧动态计数从归档日志解析（`GSIM_RTPROF_IR_DYN_LOG`）；dynOps 由传递链锁定值（99,479,933,605）作为参数输入，不重算。
3. **`scripts/test_gsim_runtime_profile_compare.py`**（新）：17 个单测覆盖全部解析器、因子表与 Pareto。

- **语义约束**：不改任何仿真语义、IR、mapping、调度与锚定二进制；runtime profile 计数器只读不写模型状态（计数开销为诊断口径，时间不进基线）；`GSIM_EMIT_RUNTIME_PROFILE` 默认 0，既有 `xs_gsim_emu`/`xs_gsim_emu_pgo` 目标行为逐字节不变。
- **与父节点差异**：无性能语义差异；当前最佳指针与归档二进制不变。
- **聚焦测试**：
  - `make test_gsim_runtime_profile_compare`：17 测试通过。
  - `make test_grhsim_native_work_compare` / `make test_benchmark_grhsim_ir`：通过（回归）。
  - `make -n xs_gsim_emu_rtprof` / `make -n analyze_gsim_runtime_profile`：干跑展开正确（`GSIM_EMIT_RUNTIME_PROFILE=1` 注入点 4 处一致）。

## 结果测试（TESTED）

- **构建门槛（诊断口径，如实登记，不进性能门槛）**：`make xs_gsim_emu_rtprof`（RUN_ID=no00008_rtprof_build_20260925）exit=0，墙钟 **1093.59 s**（gsim 模型 codegen 765.8 s + difftest emu 编译 ~328 s，与归档量级 ~769 s / ~385 s 相符）。日志 `ptmp/no00008_gsim_activation_profile_20260925/build.log`、`build.time`；产物 `build/xs/gsim-rtprof/emu`（保留，复现依赖）。
- **模型一致性门槛（通过）**：`cmp` 确认再生成模型 `build/xs/gsim-rtprof/gsim-compile/model/SimTop_supernode_stats.json` 与锚定 `build/xs/gsim-pgo/...` 同名文件**逐字节一致**（同一 RTL/FIRRTL/codegen 参数，唯一差异为计数器注入）。
- **运行登记**（分析输出 `ptmp/no00008_gsim_activation_profile_20260925/analysis2/`，逐次 posix_fadvise 驱页缓存，`taskset -c 2`）：

  | 运行 | Host s（墙钟） | 端点（instrCnt/cycleCnt/guest/PC） | 判定 |
  |---|---|---|---|
  | run1 | 66.753 | 238550 / 99998 / 100001 / 0x80000b40 | VALID |
  | run2 | 66.772 | 238550 / 99998 / 100001 / 0x80000b40 | VALID |

  插桩 + 非 PGO 构建使 Host ~66.8 s（对锚定 PGO 27.376 s 的减速含计数开销与优化等级差异；诊断口径，不进任何性能基线）。
- **有效性门槛（通过）**：两次运行端点均精确匹配预注册值，退出 0，无 mismatch。
- **确定性门槛（通过）**：两次 `[GSIM_RUNTIME_PROFILE]` 计数完全一致（active_supernodes=1,763,193,623；nodes=82,915,274,031；ref_enodes=268,455,065,090；non_ref_enodes=157,214,921,320）；fire TSV（84,643 super 行）`cmp` 逐字节一致（`fire-1.tsv` = `fire-2.tsv`）。
- **过程备注**：首次分析（`analysis/`，失败残留）因 difftest `common.cpp` `setlocale(LC_NUMERIC,"")` 在本机 zh_CN.UTF-8 下把 instrCnt 打印为千分位逗号格式（`238,550`）导致端点解析失败；修复 `scripts/grhsim_native_work_compare.py` `endpoint_fields` 容忍逗号（附单测）后重跑（`analysis2/`）全门槛通过。
- **微观指标（M-gact / M-gwork / M-gchg）**（guest_cycles=100,001）：
  - **M-gact = 17,631.8 super 激活/cycle**（总 1,763,193,623）——取代 NO00006 的估计值（instr 加权推断 ~10.6%/cycle ≈ 8,972/cycle）：实测激活率 **20.83%**（17,631.8/84,643，含 111 个 always-active super 的 11.1 M 次激活），估计值低估约 2 倍。
  - **同尺寸激活率分桶（事后增补，fire TSV × 静态 TSV n_comp 分桶）**：n_comp∈[55,65] 的 1,083 个 super 实测激活率 **20.44%/cycle**（[40,80] 桶 5,137 个为 22.55%）——NO00006 引用的"同尺寸 ~10.6%"估计证伪为低估约一半，ir 27.4% 对 gsim 的同尺寸差距实为 **1.34×** 而非 2.6×（口径：gsim n_comp 计 member node、ir ops/unit 计 op，粒度近似而非等同；NO00006"激活率结构是主因"的推断强度据此下调，与本节点因子表"变化流密度仅 1.175×"一致）。
  - **M-gwork**：动态 member node **829,144.4/cycle**；动态 enode **4,256,657.3/cycle**（ref 2,684,550.7 + non_ref 1,572,149.2）；**241.42 enode/激活**。gsim 每 enode 指令密度 = model_step 1.926 M / 4.257 M = **0.452 instr/enode**（ir 为 3.863 instr/dynOp）。
  - **M-gchg（派生）** = (17,631.8 − 111) / 1.624 = **10,786.9 changes/cycle**（consumers/value = unique_activation_edges/监测值 = 719,095/442,722 = 1.624）。
  - **变化检测对比**：gsim Σ fire×a_succ = **87,964.7 次/cycle**（super 内监测成员变化比较）；ir boundary 写检测 = **221,343 次/cycle** → **ir 2.52×**。
  - **类别归因**：n_sink>0 super 的 fire 份额 = **54.21%**——过半 gsim 激活携带 sink 写（ir commit 类别的结构对应物，但 gsim 内联于 subStep 未单列）。
- **因子表 F**（ir 侧取归档 M-vol/M-attr 实测，gsim 侧本节点实测；guest_cycles=100,001）：

  | 因子 | gsim | ir | ir/gsim |
  |---|---|---|---|
  | changes/cycle | 10,786.9（派生，下界） | 12,676.2 | 1.175 |
  | act/change | 1.635 | 0.714（bodies/change） | — |
  | work/activation | 241.42 enode | 109.98 dynOp/body | 0.456 |
  | 动态 work/cycle | 4,256,657.3 enode | 994,789.4 dynOp | 0.234 |
  | instr/work | 0.452 | 3.863 | 8.538 |
  | compute instr/cycle | 1.926 M（model_step） | 3.843 M | 1.995 |
  | **指令比闭合** | 0.234 × 8.538 / 1.995 = **1.000** | | **残差 0% ≤ 10%（通过）** |

- **逐 super Pareto**（fire TSV × 静态 cost TSV 连接，按动态 enode work 排序）：分布**高度分散**——Top 8 合计 7.78%、Top 20 合计 15.60%，单点最高仅 1.25%（cpp_id=80392，SUPER_VALID，1,289 members，52,204 enodes，100,101 fires）。头部可见 8 个同构大 super（cpp_id 75351–75420，各 9,913 members / 48,445 enodes / 79,509 fires / a_succ=119，合计 7.23%）——疑似宽度-8 复制结构。**结论：gsim 侧无单点热点，super 级优化只能面向同构族/类别，个案无空间。**
- **口径缺口与不确定度登记**：
  1. **M-gchg 为派生量**：consumers/value 取 unique activation edges 口径 1.624（预注册文中"3.117（unique）"系笔误——3.117 = 1,379,970/442,722 为含重复边口径；派生按 unique 执行，重复边对同一 super 的置位幂等）；同 cycle 多变化合并为一次激活使派生值为**下界**；且两侧"变化"值域不同（ir = 812,234 个 boundary 值的写变化；gsim = 442,722 个监测值的变化）。
  2. instr/enode 0.452 的分子（model_step 1.926 M instr/cycle）取自 NO00005 M-attr 的 PGO 构建 perf 归因，非本 rtprof 构建实测；仅作同维度密度参照。
  3. enode（gsim 表达式树节点）与 dynOp（ir op）语义不同，跨侧 work 比仅作粒度参照；两侧各自内部闭合（gsim 10,786.9 × 1.635 × 241.42 = 4.257 M enode/cycle；ir 12,676.2 × 0.714 × 109.98 = 994.8 k dynOp/cycle）。
  4. gsim 侧无 productive/silent 率对应口径（需额外插桩，本节点未做）。
  5. sink fire share 以静态 n_sink>0 计 fire 份额，未按 sink 写工作量加权。
- **结论（定量基线交付）**：
  1. **2.0× 指令差距在测量口径内完全闭合于"每单位工作指令密度"**（ir/gsim = 8.54×）：ir 每 dynOp 3.86 instr vs gsim 每 enode 0.45 instr，而粒度覆盖仅 4.28×（0.234 动态 work 比），净 1.995× ≈ compute 指令比。变化流密度（1.175×）与每激活工作量均非主因。
  2. gsim 每次变化扇出 1.64 个 super 激活、每激活 241 enode；ir 每 body 产出 1.4 个变化、每 body 110 dynOp——两侧调度量子结构差异定量成立。
  3. ir boundary 写变化检测频次为 gsim 监测比较的 2.52×（221,343 vs 87,965 次/cycle）——ir evaluator/commit 结构开销（M-attr 0.865 M/cycle）的量化对应物。
  4. 对下一优化节点的方向排序（由因子表直接读出）：**每 dynOp 指令密度**（8.54×，主因子）> boundary 检测频次（2.52×）> 变化流密度（1.18×）；gsim super 个案优化无空间（Pareto 平坦，Top 20 仅 15.6%）。
- **判定**：预注册门槛全部通过（有效性 ✓、确定性 ✓、模型一致性 ✓、闭合残差 0% ≤ 10% ✓）；M-gact / M-gwork / M-gchg / 变化检测对比 / 逐 super Pareto / 类别归因全部交付；当前最佳指针不动（55.864 s，如实登记）。**ACCEPTED（诊断节点，定量基线交付）。**
