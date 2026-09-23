# NO00001: 锚点复核与首批微观指标基线（诊断）

| 字段 | 值 |
|---|---|
| 父节点 | 无（根节点） |
| 角色 | 诊断 |
| 状态 | ACCEPTED |
| 锚定指标 | Host time 100k（3 次有效均值，EMU 自带计时） |
| 指标阈值 | 见「假设提出 · 预注册」；诊断节点以交付定量基线为验收 |
| 回退预算 | 无代码改动，预期 Δ=0；新构建均值相对既有归档基线回退 >1% 即触发漂移排查 |
| RUN_ID | no00001_anchor_20260923 / no00001_base_20260923 |
| 工作区 | ptmp/no00001_anchor_profile_20260923/ |

## 基础选定（BASELINE）

- **父节点**：无。方法论重启后的根节点，无迂回。
- **代码状态**：wolvrix 子模块 `4de8c01`（`Revert "feat: carry srcloc from GRH through grhsim into emitted cpp comments"`，即 `7b1fd50` 的 revert；树内容与 `110d68f` 逐字节一致，已验证 `git diff 110d68f HEAD` 为空）；根仓库仅 pdocs 文档改动；xiangshan 子模块未动。冻结面（GRH IR、GRH pass、XiangShan、测试源码）零改动。
- **输入核对**（sha256）：
  - `testcase/xiangshan/ready-to-run/coremark-2-iteration.bin` = `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`
  - `testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so` = `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`
- **锚点来源**：
  - gsim：Host 46.965 s（emu 编译于 2026-09-10 01:50:26，`build/xs/gsim/emu` sha256 `a0704df4a9bf9a2eae99a1d56b901678d56a8165aa0c0087f8cfe68ac49f0b3f`），`instrCnt=238550`、`cycleCnt=99998`、IPC 2.385548、末端 PC `0x80000b40`。配置未变，归档值复用；本节点另做 3 次 sanity 复测验证跨窗口可比性（见结果测试）。
  - GrhSIM-IR：本节点以当前源码（`4de8c01`）全量重建并实测定标，定标值写入索引作为当前最佳。
- **资源配置**：机器 AMD Ryzen 9 7950X3D（32 逻辑核），`XS_EMU_CPU=2`、`XS_EMU_THREADS=1`、`XS_NUM_CORES=1`、`XS_SIM_MAX_CYCLE=100000`、waveform/commit/RAM trace 全关；编译 `VM_BUILD_JOBS=32`（=nproc）。测量时机器空载。
- **计时边界与止损线**：
  - 生成：make 启动 → 完整 C++ 与 Makefile 生成完成，墙钟 <1800 s；超时 `TIMEOUT_KILLED` 并隔离产物。
  - 编译：emu 编译启动 → 可执行文件完成，墙钟 <1800 s；同上。
  - 仿真：仅 emu 执行区间。运行截止 = 77.155333×1.5 = **115.733 s**（定标后以本基线为准），超时 `REGRESSION_KILLED`；gsim sanity 截止 = 46.965×1.5 = 70.4475 s。
  - 每次仿真运行前对 emu 二进制 `posix_fadvise(DONTNEED)` 驱逐页缓存（benchmark_grhsim_ir.py 内建）。
- **复现方法**：本节点为根节点，无父节点代码重建需求；wolvrix 固定在 `4de8c01`，全量 SV→C++ 生成后编译测量。

## 假设提出（HYPOTHESIS）

- **假设**：
  - H1（源码可定标）：当前源码状态（wolvrix `4de8c01`）经完整 SV→C++ 生成与编译产出的新二进制，100k 行为端点不变（`instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`），3 次有效运行均值离散度 ≤1%，可作为后续节点的稳定定标基线。
  - H2（噪声底可分辨）：同一时间窗口内同二进制 3 次复测的极差/均值 ≤ 3%，即以 3+3 交替协议可分辨 ≥3% 量级的真实性能变化。
  - H3（画像可交付）：相位分解（EMU_PHASE_TIMING/EMU_RUNTIME_PROFILE）、任务级 CPU 分布（gperftools 200 Hz）、静态 op 混合（IR JSON 普查）、动态执行计数（dynamic-stats 插桩构建）四类微观指标可在本分支稳定测得，形成定量基线表。
- **创新点**：无（诊断节点）。交付方法论重启后的首个定量参照系，供后续节点锚定。
- **瓶颈证据**：定标基线 77.155 s 对 gsim 归档 46.965 s ≈ **1.643×**（对本节点 gsim sanity 均值 47.051 s ≈ 1.640×），剩余差距 ~30.1 s。差距在模型求值内部的分布（相位/任务/op 维度）未定量化，本节点建立画像。
- **微观指标与总目标的定量关系**：
  - M0 Host time 100k：总目标本身。
  - M1 相位分解：emu 打印 `tick_total_us / single_cycle_us / model_step_us / difftest_us / tick_misc_us` 与模型内 `evals / rounds / eval_ns / compute_ns / commit_ns / publish_ns`。`model_step_us/tick_total_us` 为模型求值占比，即可优化核心；`difftest_us` 为对照框架固定开销，构成优化不可及部分；阶段节省比例 α 对总时间的传导 = α×（阶段占比）。同时给出 `rounds/evals`（平均收敛轮数）等活动性结构量。
  - M2 任务级 CPU 分布：gperftools 200 Hz 扁平样本映射到生成函数（任务），`样本占比 × Host 时间 = 该任务秒数`，Pareto 表给出单点优化的收益上限；样本数 ≥10000 保证占比统计误差 <1 个百分点。
  - M3 静态 op 混合：IR JSON 普查（`grhsim_op_mix_stats.py`）给出 op 种类 × 位宽 × 存储类的静态计数；与 M2 结合把热点任务归因到 op 构成，决定 emit 策略类优化的覆盖面。
  - M4 动态执行计数：`--dynamic-stats` 插桩构建打印各 op 类 wr/ch/silent 计数、supernode 激活/执行/变化计数、commit 入口计数、round 直方图。`silent/wr`（发射但未改变状态）度量活动性剪枝类优化的上限；`chg/act` 为状态变化率基线。动态计数为固定输入下的确定性计数，用精确比对。插桩构建仅作诊断，其时间不进性能基线。
- **预注册**：
  - M0 定标：新构建 3 次有效均值全部 VALID（端点精确匹配、退出 0、无 mismatch）；样本 SD 与极差如实记录，离散度 ≤1% 判定可定标。
  - 回退预算：诊断节点无代码改动，新构建均值相对既有归档基线回退 **≤1%** 视为噪声内；超出即排查构建/机器漂移并如实记录。
  - 噪声底（H2）：报告每组 (max−min)/mean 与样本 SD；判定线 3%。
  - M1–M4 判定：测量完成且所属运行端点 VALID 即交付；M2 样本数 ≥10000；M4 插桩构建端点必须 VALID（插桩不改变行为）。
  - gsim sanity：3 次复测均值相对归档 46.965 s 的偏离如实记录（仅锚点有效性确认，不参与验收门）。
  - 证伪标准：H1 证伪 = 新构建端点变化或离散度 >1% → 须更换代码状态重新定标；H2 证伪 = 同窗口同二进制极差 >3% → 后续节点判定阈值须重设；H3 证伪 = 任一画像链路无法产出 VALID 数据 → 记录缺口。
  - 验收（诊断节点）：全流程门槛通过 + 100k 等价成立 + M0–M4 基线表交付（含 H1/H2 结论）。最终性能如实登记；本节点以实测建立当前最佳指针（无代码改动）。

## 代码实施（IMPLEMENTED）

无生产代码改动。聚焦测试：

- `make test_benchmark_grhsim_ir`：通过。
- `make run_hdlbits_grhsim_ir DUT=001`（wolvrix `4de8c01`）：通过。

## 结果测试（TESTED）

### 全流程门槛

| 区间 | 实测 | 门槛 | 判定 |
|---|---|---|---|
| SV→C++ 生成 | 880.22 s | <1800 s | 通过 |
| C++ 编译（-j32） | 191.20 s | <1800 s | 通过 |

### M0 定标与噪声底

wolvrix `4de8c01` 全量重建（flow-base），3 次有效运行：77.260 / 77.092 / 77.114 s，均值 **77.155 s**，样本 SD 0.091 s，极差/均值 0.22%。端点全部精确匹配 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`，退出 0，无 mismatch → **H1 成立**，定标为当前最佳。

噪声底：同窗口同二进制 3 次复测极差/均值 0.22%（SD 0.091 s），远优于 3% 判定线 → **H2 成立**，3+3 交替协议可分辨 ≥3% 变化；本节点实测分辨率约 0.5%。

### gsim sanity

3 次复测 46.881 / 47.100 / 47.171 s，均值 **47.051 s**，相对归档 46.965 s 偏离 +0.18% → 归档锚点有效，跨窗口可比。

### M1 相位分解（EMU_PHASE_TIMING，诊断运行，不计入性能基线）

tick_total = 77.332 s；其中 model_step = 76.969 s（**99.53%**），difftest = 0.331 s（0.43%），single_cycle_other = 0.017 s，tick_misc = 0.015 s。模型求值内部（eval_ns 总计 77.059 s）：

| 相位 | 时间（s） | 占 eval |
|---|---|---|
| compute | 59.250 | 76.9% |
| commit | 16.790 | 21.8% |
| publish | 0.860 | 1.1% |

活动性结构量：evals = 200102，rounds = 401257，平均收敛轮数 rounds/evals = **2.0054**。

### M2 任务级 CPU 分布（gperftools 200 Hz，VALID_DIAGNOSTIC）

样本数 **15538**（≥10000 达标），周期 5000 µs，名义 CPU 时间 77.69 s。分类占比：

| 类别 | 样本 | 占比 |
|---|---|---|
| main_other（emu 主循环/调度/difftest 等） | 7108 | 45.75% |
| compute_task（3950 个计算任务合计） | 5219 | 33.59% |
| commit_task（489 个提交任务合计） | 2513 | 16.17% |
| evaluator | 551 | 3.55% |
| external（libc 等） | 117 | 0.75% |
| unmapped / main_unresolved | 30 | 0.19% |

热点函数 Pareto（扁平样本）：`GrhSIM_SimTop::eval()` 3.55%；`cpu_write_cell<bool,1>` 2.66%；`cpu_task_3964` 1.35%；`cpu_blk_0` 1.17%；`cpu_task_3974` 1.11%；`cpu_direct_state_changed` 0.99%。单任务最高仅 ~1.35%，呈长尾分布，无单一热点任务 → 单点任务级优化收益上限低，优化须面向类别（compute/commit 全体）或结构性机制。

### M3 静态 op 混合（IR JSON 普查）

total_ops = 3531463，values = 3379131；结果位宽 narrow(1..64) = 3337258、wide(>64) = 28226。op 种类 Top：and 25.85%、or 19.37%、mux 9.52%、concat 6.28%、sliceStatic 5.65%、bitSelect 5.17%、eq 4.77%、add 2.87%、state.read 2.85%、state.regWrite 2.84%。boundary results 合计 812234（producer 以 and 29.99%、or 12.36%、mux 10.32%、sliceStatic 9.78% 为主）。supernode 共 32101 个，op 数均值 110.01（p50=120，p99=128，max=4096），boundary result 均值 25.30；compute local frame 均值 140.31 字节（p90=272，max=4168）。

### M4 动态执行计数（dynamic-stats 插桩构建，诊断运行）

插桩构建端点 VALID（`instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`，退出 0，无 mismatch）→ 插桩不改变行为。插桩使 emu 减速（wall 140.09 s vs 基线 77.155 s），属诊断运行，时间不进性能基线；首次按 115.733 s 止损运行至 80k cycles 被 `REGRESSION_KILLED`，改以 300 s 上限完成（记录于此，止损线仅约束未插桩基线运行）。

结构量与活动性基线（确定性计数，固定输入下逐次一致）：

- evals = 200102，rounds = 401257，rounds/evals = 2.0053（与 M1 独立测量 2.0054 互洽）。
- supernode 激活 993413585 次，body 执行 904557815 次，quiescence 跳过 88855770 次（8.94%）；productive group calls = 29.88%；supernode chg/act 均值 **31.36%**（31612 个 unit）。
- 调度桶分布（按动态 op 数）：other 95.36%（31287 units）、every_round 4.27%（316 units）、multi_round 0.37%（9 units）。
- commit 入口 33078833 次；port_eval 669591914、port_fire 470856003，fire/eval = 70.32%；publish calls 401257，pending/call = 69.23%；input checks 1400714、changes 200105。
- 动态 compute op 执行总量（body 加权）= **99479933605**，per_eval = 497146。Top：and 26.02%、or 21.59%、mux 11.63%、eq 6.90%、bitSelect 4.77%、concat 4.24%、sliceStatic 3.60%、state.read 3.40%、add 3.11%——与 M3 静态构成一致。
- boundary 写活动：总写 22134521354 次，变化 1267630634 次（**5.73%**），silent（发射但未改变状态）1565541060 次（**7.07%**）→ 活动性剪枝类优化在 boundary 写上的收益上限约 7%；变化率最高的 op 类为 sliceArray 52.25%、sub 27.38%、shl 23.01%、ge 20.45%、concat 17.58%、prioritySelect 16.59%。

### 判定

**ACCEPTED**。判定依据：

1. 全流程门槛通过（生成 880.22 s、编译 191.20 s，均 <1800 s）；所有计入基线的运行端点精确匹配、退出 0、无 mismatch（100k 等价成立）。
2. H1 成立：当前源码（wolvrix `4de8c01`）全量重建可定标，3 次有效均值 77.155 s、SD 0.091 s、极差/均值 0.22% ≤ 1%，定标值登记为当前最佳指针。
3. H2 成立：噪声底 0.22%，3+3 交替协议可分辨 ≥3% 变化，后续节点判定阈值无需重设。
4. H3 成立：M1 相位分解、M2 任务级 CPU 分布（15538 样本 ≥10000）、M3 静态 op 混合、M4 动态执行计数四类画像全部产出 VALID 数据，定量基线表如上。
5. gsim sanity 47.051 s 与归档 46.965 s 偏离 +0.18%，跨窗口可比性确认；当前基线对 gsim ≈ 1.643×，剩余差距 ~30.1 s。

瓶颈证据结论：模型求值占总时间 99.5%，其中 compute 76.9%、commit 21.8%；任务级分布呈长尾（单任务最高 1.35%），无单点热点；boundary 写 silent 率 7.07%、supernode chg/act 31.36% 给出活动性类优化的定量上限。后续优化节点应面向 compute 相位全体（op 构成以 and/or/mux 为主）或结构性机制，而非单任务级修补。
