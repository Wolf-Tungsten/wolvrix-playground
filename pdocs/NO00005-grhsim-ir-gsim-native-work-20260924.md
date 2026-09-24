# NO00005: gsim 环比微观口径建立——原生动态指令量 / CPI / 分支与缓存行为 / 函数级归因，分解 2.041× 差距（诊断）

| 字段 | 值 |
|---|---|
| 父节点 | NO00004（当前最佳，无迂回） |
| 角色 | 诊断 |
| 状态 | ACCEPTED |
| 锚定指标 | M-vol（两侧原生动态指令量及模型净指令量）、M-cpi（两侧原生 CPI）；辅证 M-br / M-dl1 / M-il1 / M-attr / M-shape |
| 指标阈值 | 诊断节点以交付定量基线为验收（口径与判定线见「假设提出 · 预注册」） |
| 回退预算 | 无性能语义改动；当前最佳指针不动（55.864 s），如实登记 |
| RUN_ID | no00005_perfstat_20260924 / no00005_icache_20260924 / no00005_nodiff_20260924 / no00005_record_20260924 |
| 工作区 | ptmp/no00005_gsim_native_compare_20260924/ |

## 基础选定（BASELINE）

- **父节点**：NO00004（当前最佳指针，GrhSIM-IR PGO 构建 Host 55.864 s）。诊断节点，无代码分叉、无迂回；产出 gsim 侧首批微观口径与差距分解，供后续优化节点锚定。
- **基线测量（配置未变，复用父节点与 goal 锚点归档值，不重跑）**：
  - GrhSIM-IR 当前最佳：Host **55.864 s**（NO00004，3 次有效均值，SD 0.270 s；PGO 二进制 sha256 `7f70191ca216d4b740a075f3c8f06d3b5cd9f8be5d7a5be134819902345eace3`，归档于 `ptmp/no00004_compiler_pgo_20260924/flow/emu/emu`）；端点 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`。
  - gsim+PGO 锚点：Host **27.376 s**（3 次有效均值，SD 0.065 s；二进制 sha256 `4e099ee9e763262765d2f4bdc2235eed360c46e2093ec83ffb35b4078f7a8827`，`build/xs/gsim-pgo/gsim-compile/emu`）；端点 `instrCnt=238550、cycleCnt=99998、guest=100001、PC=0x80000b40`。
  - 差距：**2.041×（~28.5 s）**。
  - GrhSIM-IR 侧既有微观基线：dynOps = **99,479,933,605**（确定性，传递链锁定；per_eval=497,146，evals=200,102，rounds/evals=2.0054）；M1 相位（PGO 后）：compute 47.145 s / commit 7.006 s / publish 0.880 s / difftest 0.263 s；M3 静态：total_ops 3,531,463、supernode 32,101（均值 110.01 op）；生成 C++ 9.62M 行。
  - gsim 侧既有口径：仅静态 supernode stats JSON（`--dump-stats-json` 内建）与 Host/端点；**无任何动态工作量/单价口径**——本节点建立。
- **对照二进制**：gsim+PGO 归档（`build/xs/gsim-pgo/gsim-compile/emu`）与 GrhSIM-IR PGO 归档（NO00004 flow 归档），两侧均为 clang 22.1.2 LLVM IR PGO 三阶段构建（口径对等，goal 锚点节）。
- **输入核对**（sha256，与 NO00001–NO00004 相同，输入未变）：
  - `testcase/xiangshan/ready-to-run/coremark-2-iteration.bin` = `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`
  - `testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so` = `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`
- **资源配置**：与 NO00001–NO00004 完全一致：`XS_EMU_CPU=2`、`XS_EMU_THREADS=1`、`XS_NUM_CORES=1`、`XS_SIM_MAX_CYCLE=100000`、waveform/commit/RAM trace 全关；perf 注入经 `XS_EMU_PREFIX` 覆盖（profile_grhsim_ir.py 既有模式），不改运行目标的命令结构。
- **PMU 口径核查（本机实测，`perf stat -x,` 探针）**：通用计数器可同时计数 5 个事件（100% enabled）；`cycles:u / instructions:u / branches:u / branch-misses:u / L1-dcache-loads:u / L1-dcache-load-misses:u / L1-icache-load-misses:u / iTLB-load-misses:u / dTLB-load-misses:u` 可用；LLC 事件本机 `<not supported>`（口径缺口，登记）；`perf_event_paranoid=-1`。
- **计时边界与止损线**：
  - 诊断节点无生成/编译区间（不重建任何产物）。
  - 仿真：仅 emu 执行区间。GrhSIM-IR 侧运行截止 = 55.864333×1.5 = **83.796 s**；gsim 侧 = 27.376×1.5 = **41.064 s**（基线有多次测量，比较值取归档均值，预注册于此）；perf stat/record 开销实测 <3%，远低于截止余量；超时 `REGRESSION_KILLED`，失败 `INVALID`。
  - 每次运行前对 emu 二进制 `posix_fadvise(DONTNEED)` 驱逐页缓存。
  - perf stat/record 运行为**插桩诊断运行**：其 Host 时间如实记录但**不混入**未插桩性能基线；计数类指标（instructions 等）为计数器读数，不受采样开销影响。

## 假设提出（HYPOTHESIS）

- **假设（诊断性）**：GrhSIM-IR 对 gsim+PGO 的 2.041× Host 差距可在同一机器上分解为 **原生动态指令量之比 × 原生 CPI 之比**（Host ≈ native_cycles / 频率；同窗口同 CPU 下频率因子抵消；native_cycles = instructions × CPI）。两个因子分别对应核心科学问题的两侧：**指令量比**度量"同一 guest 负载在两种 IR 表达/映射下展开为多少宿主工作量"（op 粒度、求值结构、活动性利用）；**CPI 比**度量"逐指令成本"（代码形态、分支/缓存行为对编译器与微架构的响应）。本节点建立两侧口径、定量给出各因子，并把指令量归因到函数/类别粒度（GrhSIM-IR：compute_task / commit_task / evaluator / 助手 / 框架 / 参考模型；gsim：subStep / 模型框架 / 框架 / 参考模型），形成首个任务级环比表（同时修复 NO00004 标记失效的任务级 profile 链路——以 perf record + 符号名为基础的分类，不再依赖 gperftools 地址区间假设）。
- **创新点**：方法论重启后首个 gsim 环比画像节点；此前所有微观指标仅在 GrhSIM-IR 自身历史纵向对比（同比），本节点把每个可取得的维度横向锚定到 gsim（用户 2026-09-24 指示第 2 条）。gsim 侧缺动态口径，先建口径再对比，差距本身即瓶颈证据。
- **瓶颈证据（本分支实测）**：
  1. 剩余差距 28.5 s，而 NO00004 普查已证 op 计数削减类方向枯竭（四类融合 <0.6%）；下一步方向选择（工作量削减 vs 逐 op 成本削减 vs 结构映射）缺少 gsim 侧工作量/单价口径，无法定量立项。
  2. NO00001 M2/NO00004：任务级分布长尾（单任务 ≤1.35%），必须面向类别与结构；类别级指令量环比（compute/commit/框架）直接给出各类别的收益上限。
  3. GrhSIM-IR 生成代码 9.62M 行、4,439 个任务函数，gsim 模型为 subStep 函数族（数量级待测）——代码形态差异的定量后果（指令量、icache 行为）尚未测量。
- **微观指标与总目标的定量关系**：
  - **M-vol-full** = 生产口径（difftest 开）全程 `instructions:u`；**M-vol-model** = 无 difftest 诊断运行的 `instructions:u`（模型净工作量，difftest-off 不改变模型行为，端点字段复核）；框架份额 = full − model。**指令量比（model 口径）× CPI 比 ≈ Host 比**——哪个因子大，下一优化节点就立项于哪类机制（工作量：求值结构/活动性/op 粒度；CPI：代码形态/分支/局部性）。每 1.0 的指令量比 ≈ 28.5 s 差距中按比例可消的部分。
  - **M-cpi** = cycles:u / instructions:u（同 run 配对）；**M-br** = branch-misses / 1k instructions；**M-dl1** = L1-dcache-load-misses / L1-dcache-loads；**M-il1** = L1-icache-load-misses / 1k instructions（第二事件组）；iTLB/dTLB misses / 1k instructions（第二事件组）。这些是 CPI 差的归因量。
  - **M-attr** = perf record（cycles:u，999 Hz，flat）函数级样本份额表：GrhSIM-IR 侧按符号分类（cpu_task_N → eval() 源文本解析得 compute/commit 相位映射，两参数 tick 形式；助手函数、evaluator、框架、nemu、libc），gsim 侧（SSimTop::subStepN、SSimTop 其他、框架、nemu、libc）；给出两侧 Top 函数 Pareto。
  - **M-shape** = 静态形态对比：生成源码行数、函数计数、.text 段大小、supernode 计数/规模（gsim stats JSON vs NO00001 M3 归档值）、gsim enode op mix vs GrhSIM-IR M3 op mix。
  - 计数类指标（instructions、branch-misses 等）在固定输入+固定二进制下近似确定（PMU 计数）；以同侧 3 次重复实测离散度验证（预注册判定线见下）。时间类读数（perf 运行 Host）仅记录不入基线。
- **预注册**：
  - 执行顺序（pass1 主事件组 3+3 交替）：**gsim1, ir1, gsim2, ir2, gsim3, ir3**；pass2（icache/TLB 事件组）gsim, ir 各 1 次；pass3（difftest-off）gsim, ir 各 1 次；pass4（perf record）gsim, ir 各 1 次。
  - 主事件组（5 事件，100% enabled）：`cycles:u, instructions:u, branch-misses:u, L1-dcache-loads:u, L1-dcache-load-misses:u`；第二事件组：`cycles:u, instructions:u, L1-icache-load-misses:u, iTLB-load-misses:u, dTLB-load-misses:u`。
  - 有效性门槛：全部计入运行端点精确匹配各自期望（ir `240349,99996,100001,0x80000c0c`；gsim `238550,99998,100001,0x80000b40`），退出 0，无 mismatch（difftest-off 运行无 difftest 行属预期，仅核对 instr/cycle/guest/PC 四字段）；任一运行失败该次作废补跑。
  - 离散度判定线：pass1 同侧 3 次 instructions 极差/均值 ≤ **0.5%**（近似确定性的预期量级）；超出则如实报告并将结论降为区间表述。
  - 分解闭合线：指令量比 × CPI 比 与 原生 cycles 比的偏差 ≤ **3%**（同窗口频率因子残余），超出则记录分解缺口并给出归因限定。
  - 证伪标准：本节点为诊断节点，无机制假设可证伪；若任一画像链路无法产出 VALID 数据（PMU 事件不可用、record 符号化失败、difftest-off 行为改变），记录口径缺口，对应指标不交付。
  - 验收（诊断节点）：全部有效性门槛通过 + 离散度/闭合判定线达标 + M-vol / M-cpi / M-br / M-dl1 / M-il1 / M-attr / M-shape 基线表交付 + 差距分解结论。最终性能如实登记（当前最佳指针不动）。

## 代码实施（IMPLEMENTED）

诊断节点，无生产语义改动（不改 wolvrix 子模块、不改发射源、不改任何构建产物；冻结面零改动）。改动为测量设施：

1. **`Makefile`**：
   - 新增 `XS_EMU_DIFF_ARGS`（默认 `--diff <nemu-so>`，行为不变），`run_xs_gsim_emu` 与 `run_xs_wolf_grhsim_emu` 的 echo/实命令两处统一引用；诊断可用 `XS_EMU_DIFF_ARGS=--no-diff` 关闭参考模型加载（difftest `args.cpp` 内建 `--no-diff` 选项；探测确认省略 `--diff` 会回退 `$NEMU_HOME` 并 FATAL，故必须显式 `--no-diff`）。
   - 新增 `analyze_grhsim_native_work`（驱动新脚本；变量 `GRHSIM_NATIVE_IR_FLOW / GSIM_BUILD / OUTPUT / PAIRS / IR|GSIM_BASELINE_SECONDS / PASSES`）与 `test_grhsim_native_work_compare`。
2. **`scripts/grhsim_native_work_compare.py`**（新）：四个 pass 全部经项目 Make 运行目标 + `XS_EMU_PREFIX` 注入 perf（profile_grhsim_ir.py 既有模式），逐运行 `posix_fadvise` 驱页缓存、进程组看门狗（截止+30 s SIGKILL）、端点精确校验；perf stat CSV、perf report 行、eval() 任务→相位映射（兼容一参/两参 tick）、两侧符号分类器均为纯函数并有单测。nodiff pass 传 `XS_EMU_DIFF_ARGS=--no-diff`；difftest 附着证据串为 `The reference model is`（两侧共有；`[DIFFTEST_INIT]` 在 --no-diff 下也打印，不可作证据——短周期探针实测）。
3. **`scripts/grhsim_cpu_profile.py`**（修复 NO00004 标记的失效链路）：`task_phases` 的相位边界切分从一参 tick 字面量改为兼容两参（边沿分裂）形式的正则；该失效实为 NO00003 tick 签名变化所致（源文本解析，与 PGO 函数重排无关——NO00004 报告归因据此订正）。
4. **`scripts/test_grhsim_native_work_compare.py`**（新）：12 个单测覆盖四个解析器与两侧分类器（含 mangled 符号形态）。

- **语义约束**：不改任何仿真语义、IR、emit、调度与二进制；`XS_EMU_DIFF_ARGS` 默认值保持原命令逐字节等价；nodiff 仅用于模型净工作量诊断（difftest 只观察/比对，不反哺模型，端点四字段复核行为不变）。
- **与父节点差异**：无性能语义差异；当前最佳指针与归档二进制不变。
- **聚焦测试**：
  - `make test_grhsim_native_work_compare`：12 测试通过。
  - `make test_grhsim_cpu_profile` / `make test_benchmark_grhsim_ir`：通过（回归）。
  - `make -n analyze_grhsim_native_work ...`：干跑展开正确。
  - 短周期探针（-C 100/2000，非计入运行）：gsim 侧 perf stat 注入 5 事件 100% 计数、`--no-diff` 正常到达端点、perf record→report→demangle 符号链（`SSimTop::subStepN()`）可用、gsim 端点日志格式核对（`instrCnt/cycleCnt/Guest cycle spent/Host time spent/EXCEEDING...pc` 与 ir 侧同构；`cycles=...max_cycles=` 与 `Difftest enabled` 为 ir 侧独有，解析器已按侧适配）。

## 结果测试（TESTED）

### 全流程门槛

诊断节点，预注册声明无生成/编译区间（不重建任何产物）；仿真止损线（ir 83.796 s / gsim 41.064 s）全部运行未触发。

### 运行登记与有效性

预注册顺序：pass1 `gsim1, ir1, gsim2, ir2, gsim3, ir3`；pass2（icache 事件组）、pass3（nodiff）、pass4（record）各 gsim→ir 1 次；另加 1 次 gperftools 交叉验证运行（VALID_DIAGNOSTIC，11078 样本 ≥10000）。全部 13 次运行端点精确匹配各自期望（ir `240349,99996,100001,0x80000c0c`；gsim `238550,99998,100001,0x80000b40`）、退出 0、无 mismatch → 全 VALID。Host 读数为 perf 插桩诊断值（不入性能基线）：

| 运行 | gsim Host (s) | ir Host (s) |
|---|---|---|
| pass1 三次 | 27.479 / 27.166 / 27.220（均值 27.288，SD 0.167） | 55.783 / 55.723 / 56.026（均值 55.844，SD 0.160） |
| pass2 icache | 27.242 | 55.805 |
| pass3 nodiff | 26.971 | 55.008 |
| pass4 record | 27.384 | 55.552 |

对未插桩锚点（gsim 27.376 / ir 55.864）偏差均 ≤0.4%，perf stat/record 开销在噪声内。

### M-vol / M-cpi（锚定指标）与差距分解

pass1（生产口径，difftest 开，5 事件 100% 计数）：

| 指标 | gsim+PGO | GrhSIM-IR+PGO | 比（ir/gsim） |
|---|---|---|---|
| instructions:u（3 次均值） | 196,545,332,110 | 479,295,135,474 | **2.4386×** |
| cycles:u（3 次均值） | 135,244,296,950 | 276,688,677,478 | 2.0458× |
| CPI | 0.6881 | 0.5773 | **0.8389** |
| instructions / guest cycle | 1,965,434 | 4,792,903 | 2.4386× |
| Host（插桩读数均值，s） | 27.288 | 55.844 | 2.0464× |

- 离散度判定线（≤0.5%）：gsim 3 次 instructions 极差/均值 **1.3e-8**、ir **1.9e-6** → 计数近确定性，达标。
- 分解闭合：`cycles 比 = instructions 比 × CPI 比` 为同 run 恒等式（2.0458 = 2.4386×0.8389，偏差 2e-16）；非平凡的频率闭合——两侧有效频率 4.9547 / 4.9561 GHz（差 0.03%）→ Host 比 = cycles 比（2.0464 vs 2.0458，偏差 0.03%）→ **同窗口频率因子抵消，分解成立**（闭合线 ≤3% 达标）。
- **结论：2.04× Host 差距几乎全部由原生动态指令量（2.44×）构成；GrhSIM-IR 的逐指令成本反而优 16%（CPI 0.577 vs 0.688）。** 反事实换算：ir 以 gsim 的指令量运行 ≈ **22.9 s**（优于 gsim 的 27.3 s）；ir 指令量以 gsim 的 CPI 运行 ≈ 66.6 s。剩余差距的治理方向是**工作量削减**，不是逐指令成本。

### M-vol-model（nodiff 模型净工作量，`XS_EMU_DIFF_ARGS=--no-diff`）

| 指标 | gsim | ir | 比 |
|---|---|---|---|
| 模型净 instructions | 195,309,051,595 | 478,051,881,960 | **2.4477×** |
| 参考模型+difftest 指令（full−net） | 1.236 G（0.629%） | 1.243 G（0.260%） | ≈1.006 |

nodiff 运行端点四字段与生产口径完全一致（行为不变性复核 ✓）。**口径一致性铁证：两侧参考模型绝对指令量 1.243G vs 1.236G（差 0.6%）**——同一 nemu 解释执行同一 guest 负载，两边框架开销绝对值相等，量纲自洽；指令量比在模型净口径下升为 2.4477×（框架对 gsim 占比更大，稀释了其全程比值）。difftest 参考的时间成本（高 CPI 解释器）：ir 侧 full−nodiff = 0.836 s、gsim 侧 0.317 s。

### M-br / M-dl1 / M-il1 / TLB（CPI 归因，pass1+pass2）

| 指标 | gsim | ir | ir/gsim |
|---|---|---|---|
| branch-misses / Kinst | 3.760 | 2.296 | 0.611 |
| L1-dcache miss 率 | 3.898% | 4.754% | 1.220 |
| L1-icache miss / Kinst | 2.717 | 1.742 | 0.641 |
| iTLB miss / Kinst | 2.263 | 1.838 | 0.812 |
| dTLB miss / Kinst | 0.0034 | 0.0020 | — |
| loads / instr | 0.5045 | 0.4735 | 0.938 |

CPI 归因：gsim 逐指令成本更高的主要候选是分支误预测密度（+64%）与取指侧局部性（icache +56%、iTLB +23% 每指令 miss）——与其 327 个巨型 subStep 函数（.text 78.6 MB，均值 ~240 KB/函数）的代码形态一致；ir 的小任务函数群 + PGO 热路径布局在取指/分支维度更优，代价是 L1d miss 率略高（4.75% vs 3.90%，状态/帧访问更分散）。净效应 ir CPI 优 16%。**CPI 侧对 ir 已无大空间，且后续工作量削减须警惕回吐该优势。**

### M-attr 函数级归因（pass4，perf record 999 Hz flat；gsim 27k / ir 56k 样本）

| ir 类别 | 份额 | 折算指令/周期 | gsim 类别 | 份额 | 折算指令/周期 |
|---|---|---|---|---|---|
| compute_task（3950） | 80.18% | 3.843 M | model_step（327 subStep） | 97.97% | 1.926 M |
| commit_task（489） | 10.85% | 0.520 M | libc | 0.72% | 0.014 M |
| model_infra（publish/chg 检测等） | 3.64% | 0.174 M | harness | 0.45% | 0.009 M |
| evaluator（eval() 分发） | 3.57% | 0.171 M | difftest_ref | 0.45% | 0.009 M |
| libc / harness / ref / external | 1.24% | 0.059 M | model_infra / external | 0.17% | 0.003 M |

- 顶部函数：gsim 最高 `SSimTop::subStep296()` 3.72%，前 20 名 ≤0.74% 起长尾；ir 最高任务 `cpu_task_3970()` 0.77%，`eval()` 3.57%（含内联任务）、`cpu_direct_state_changed` 1.44%（change 检测热点，属 model_infra）。**两侧均为长尾，无单点热点。**
- 结构观察：ir 的 compute_task 一类（3.843 M/cycle）即为 gsim 全部模型执行（1.926 M/cycle）的 **2.00×**；ir 另有 commit + model_infra + evaluator 三类结构性开销合计 **0.865 M/cycle（18.1%）**，在 gsim 侧无对应类别（其 model_infra 仅 0.12%）。
- **双链路交叉验证（修复后的 gperftools 链路，NO00004 失效项闭合）**：同二进制 gperftools 200 Hz（11078 样本，VALID_DIAGNOSTIC）经修复的 `task_phases`（两参 tick）分类：compute_task **80.51%** / commit_task **10.96%** / evaluator 3.65%（task_coverage=4439，3950+489 相位计数与 NO00001 M2 一致）；与 perf record 的 80.18% / 10.85% / 3.57% 相差 ≤0.4 pp（采样误差内）→ 两条独立采样链路互证，任务级 profile 链路修复实证。
- ir 折算交叉核对：commit_task 52.0 G instr ≈ 每次 commit 入口 1,572 instr（入口 33.08M，M4）≈ 每 boundary 写 2.35 instr（写 22.13G，M4），量纲自洽；evaluator 85.5k instr/eval（分发/flag 扫描/轮次管理）；difftest_ref 份额 0.26%×full = 1.246 G 与 nodiff 差分 1.243 G 吻合（差 0.3%）。

### M-shape 静态形态对比

| 指标 | gsim（FIRRTL→gsim） | GrhSIM-IR（SV→GRH→grhsim-ir） |
|---|---|---|
| 生成模型源码 | 14.31 M 行（329 cpp + 1 h） | 9.63 M 行（4540 cpp + 1 hpp） |
| .text 段 | 78.58 MB | 122.77 MB（1.56×） |
| 模型函数粒度 | **327 个 subStep**（~240 KB/函数） | **4,439 个 cpu_task**（~28 KB/函数）+ helpers |
| supernode 数 | 84,643（always-active 111） | 32,101 |
| 静态 op/enode 计数 | 5,018,786 op-typed enodes（+1,137,900 OP_INT 常量） | 3,531,463 ops |
| op 混合 Top | MUX 13.1%、WHEN 11.5%、OR 8.8%、INDEX_INT 8.7%、AND 7.7%、CAT 5.7%、EQ 4.8%、BITS 4.2%、ADD 2.3% | and 25.9%、or 19.4%、mux 9.5%、concat 6.3%、sliceStatic 5.7%、bitSelect 5.2%、eq 4.8%、add 2.9%（M3 归档） |

静态 op 计数口径不同（FIRRTL enode 含 WHEN/常量节点，GRH op 为字级语义 op），不可直接比值——**动态原生指令量（M-vol）才是 IR 无关的工作量口径**，静态形态仅作映射结构注解：gsim 以粗函数粒度（327 函数）+ 细 supernode（84.6k）活动驱动；ir 以细函数粒度（4.4k 任务）+ 粗 supernode（32.1k）+ 显式 commit/publish 相位。

### 口径缺口登记

- LLC 事件本机 PMU `<not supported>`，LLC 行为未测（L1/TLB 已覆盖主归因）。
- gsim 侧无动态 enode/op 计数口径（须插桩 gsim codegen，涉参考面，本节点规避）；gsim 无相位拆分（单 step 模型，M1 类口径不适用）。
- perf record 小份额类（<1%）受采样误差限制（gsim ref 0.45% ↔ nodiff 差分 0.63%）。

### 判定

**ACCEPTED**（诊断节点，交付定量基线）。判定依据：

1. 全部 13 次计入运行端点精确匹配、退出 0、无 mismatch；止损线未触发；无生成/编译区间（预注册）。
2. 离散度判定线达标（instructions 极差/均值 gsim 1.3e-8、ir 1.9e-6，均 ≤0.5%）；分解闭合线达标（频率因子 0.03% ≤ 3%）。
3. 基线表交付齐全：M-vol（全程 2.4386× / 模型净 2.4477×）、M-cpi（0.8389，ir 优）、M-br/M-dl1/M-il1/TLB、M-attr（双链路互证，NO00004 失效 profile 链路修复并实证）、M-shape。
4. **核心结论（瓶颈证据）**：对 gsim+PGO 的 2.04× Host 差距由**原生动态指令量 2.44×**单因子构成，ir 逐指令成本已优 16%——总目标的剩余路径是**模型净工作量削减**（求值结构与 op→指令映射密度），不是 CPI；候选方向与收益上限：compute 表达密度（3.86 instr/dynOp → ~2 的映射优化，上限约 −39% 总指令 ≈ −22 s）、commit/boundary 机制（0.52 M/cycle，上限 ~10%）、evaluator/infra 结构开销（0.35 M/cycle，上限 ~7%）；同时须保护已取得的 CPI 优势（分支/取指布局）。
5. 当前最佳指针不动（55.864 s，无性能语义改动）；最终性能如实登记。

（附：gsim 侧新口径——模型净 1.953 M instr/guest cycle、CPI 0.688、branch-miss 3.76/Kinst、icache-miss 2.72/Kinst、model_step 97.97% 集中——供后续节点环比引用。）
