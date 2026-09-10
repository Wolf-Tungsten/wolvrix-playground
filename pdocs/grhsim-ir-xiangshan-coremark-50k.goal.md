# Goal: 优化 GrhSIM-IR 单线程 XiangShan CoreMark 50k

## 目标声明

在不修改冻结的 GRH IR、GRH 上已有 pass、XiangShan 源码和测试源码的前提下，优化 GrhSIM-IR 路线的单线程 XiangShan CoreMark 50k 仿真性能。

验收同时满足以下条件：

- 仿真行为与参考结果等价，且单线程 GrhSIM-IR 仿真时间达到或优于约 40 秒的 gsim 参照值。
- 从 SV 生成 C++ 的总耗时小于 30 分钟。
- 生成的 C++ 编译耗时小于 30 分钟。
- 仿真过程不使用多线程，但编译阶段必须使用多线程（根据机器CPU核数判定）；性能数据必须标明 CPU 绑定、输入、cycle 范围和是否启用 waveform/trace。

“小于 30 分钟”是硬门槛：任何生成或编译步骤达到超时时间，必须立即终止进程，实验记为失败，不得把部分产物或部分结果当作成功数据。

## 允许与禁止

允许的方向包括：扩展 GrhSIM-IR 语义；增加高性能 op 和对应 emit 方法；改善分区及调度算法；在行为等价证明覆盖的范围内做子图替换、常量传播或状态访问优化；减少生成代码体积和运行时开销。

禁止：修改已冻结的 GRH IR 及 GRH 上的 pass；修改 XiangShan 和测试相关源码；采用多线程加速仿真；加入针对特定模块名称匹配的优化算法。优化必须依据 IR 结构、op 语义、依赖关系、位宽、读写属性等通用特征触发。

## 基线与统一执行纪律

一次 goal 执行只允许推进一个搜索步骤，并且必须形成一个完整、可审计的实验归档：从一个明确的问题假设开始，完成该步骤所需的实现或基线准备、测试、判定和报告/索引更新，然后结束本次执行。不得在同一次执行中连续挑选或测试多个候选，也不得把多个未完成候选合并成一个“步骤”。下一步搜索必须在后续 goal 执行中开始，并以前一步已提交的归档为输入。

实验文档采用渐进式补充方式维护，而不是一次性写完。开始搜索时先记录问题、假设、预期机制和对照方案（至少达到 `IDEA`）；确定实现后补充改动范围、输入和执行目标；完成每个阶段后立即补写对应的方法、结果、分析和决策；实验结束前补齐归档引用、提交检查和索引。每次 goal 执行结束时，文档必须反映本次已经完成的证据，未执行的内容明确留空或标为未完成，不得预填结果或事后用记忆替代原始记录。

每个实验都必须使用同一输入和可比较的基线。同一机器、固定输入及相同 CPU 绑定和 trace 设置下，首次建档时完成一次 gsim 运行并记录实际时间，后续实验直接复用该已归档的 gsim 基线，不得为每个实验重复测试 gsim。当前 GrhSIM-IR 基线应在需要比较的代码基线发生变化时更新；若机器、输入、CPU 绑定或 trace 设置变化，必须重新建立相应基线。不得把“约 40 秒”当作测量值。

所有构建、生成、编译、测试和仿真只能通过仓库已有 Makefile 目标执行。禁止手拼 `cmake`、`ctest`、编译器、链接器或脚本命令；若工作流缺少 Makefile 目标，先单独补充目标，再使用该目标。命令、参数和环境必须完整写入实验记录。

单线程仿真必须明确设置并记录线程参数（例如 `XS_EMU_THREADS=1`，以及 CPU 绑定设置）。生成阶段和编译阶段可以按现有 Makefile 机制使用并行编译，但不得将其冒充为单线程仿真收益。

命令日志和临时工作流产物必须放入 `ptmp/`；不得把实验产物写入 `/tmp` 或提交生成目录。每次实验使用唯一 `RUN_ID`，代码变更用 git commit 标识。临时产物只用于实验现场分析，正式档案遵守以下归档纪律。

## 归档与证据纪律

档案不得引用任何尚未添加到 Git 或不能添加到 Git 的文件。所有文件引用必须指向已经受 Git 跟踪的文件；新增报告及其引用的可提交附件必须一并添加并提交。禁止以未跟踪日志、被忽略的统计文件、波形、生成的 C++、二进制或本机绝对路径作为结论依据的引用，也不得通过强制添加生成目录来绕过限制。

如果分析依赖这些临时产物，必须将分析结果整理成论文式的文字实验报告，写入 `pdocs/` 并提交。报告必须自包含：读者仅凭 Git 中的档案即可理解实验方法、测量结果和结论，无需访问原始临时文件。不得用“详见日志”、文件路径或文件哈希替代分析正文。

每份实验分析至少包含：

- 问题与假设：优化针对的通用瓶颈、预期机制和对照方案。
- 实验方法：源码版本、输入身份、Makefile 目标及参数、资源配置、计时边界、重复次数和等价性检查方法。复现命令中的产物路径仅表示执行配置，不作为证据引用。
- 结果：直接写入各次测量值、基线对比表、变化百分比及计算口径；必要时摘录关键诊断文本或统计数据，并解释其含义。
- 分析与限制：观察到的事实、对原因的解释、噪声或混杂因素、证据不足之处；不得把推测写成已验证结论。
- 决策：接受、拒绝或精化重试的理由，包括失败、超时和无收益的结果。

失败实验也必须形成并提交分析报告。实验索引只能链接到已纳入 Git 的报告；实验归档完成以相关报告和索引的 Git 提交为准。临时产物即使被删除，也不得影响档案的可读性和结论审查。

## 时间与结果判定

将总流程拆成三个可审计区间：

1. **SV→IR/C++ 生成**：从 Make 目标启动到生成目标 C++ 和其 Makefile 完成。墙钟时间必须 `< 1800 s`。
2. **C++ 编译**：从 C++ 编译目标启动到 emu 可执行文件完成。墙钟时间必须 `< 1800 s`。
3. **仿真**：只统计 emu 执行区间；记录 cycle 上限、退出状态、仿真秒数和等价性结果。

建议使用仓库已有目标 `xs_wolf_grhsim_ir`、`xs_wolf_grhsim_ir_emu`、`run_xs_wolf_grhsim_ir_emu` 及其依赖目标；gsim 和现有 GrhSIM 路线使用对应的 `run_xs_gsim_emu`、`run_xs_wolf_grhsim_emu`。实际采用的目标以当时 Makefile 为准并原样记录。

超时处理规则：启动前确定 1800 秒截止时刻；到达截止时刻立即杀掉该步骤及其子进程，记录 `TIMEOUT_KILLED`，清理或隔离未完成产物，并停止该实验的后续性能比较。超时实验可以用于定位瓶颈，但不能作为收益证据。

仿真也采用即时止损。启动仿真前必须确定当前可比较基线的时间；若运行中已能确认编译/运行失败，立即终止并记为 `INVALID`。若墙钟时间达到基线时间的 1.5 倍（即比基线慢 50%），立即杀掉仿真及其子进程，记录 `REGRESSION_KILLED`，实验记为失败，不再等待 cycle 上限或继续收集性能数据。该阈值按同一输入、cycle 范围、CPU 绑定和 trace 设置下的单次基线时间计算；若基线有多次测量，使用实验开始前确定并记录的比较值。被止损的部分输出只能用于失败分析，不能作为收益证据。

行为等价是性能数据的前置条件。至少检查仿真退出状态、difftest/参考结果和关键日志；任何 mismatch、崩溃、非零退出或输入不一致都标记为 `INVALID`，不得比较其速度。

## 实验生命周期

每个设想按以下状态推进：`IDEA` → `BASELINE` → `IMPLEMENTED` → `VALIDATED` → `ACCEPTED` 或 `REJECTED`。只有 `VALIDATED` 才能进入性能比较，只有满足全部时间门槛并有可复现数据才能 `ACCEPTED`。

状态按阶段逐步落档：`IDEA` 步骤只登记假设和预期，不要求虚构实验结果；后续 goal 执行每次只把同一设想推进一个阶段或完成一次围绕它的实验。若该步骤在生成、编译或仿真阶段触发超时/回退止损，立即结束本次执行并提交失败记录，再由后续执行决定是否转向新设想。

同一设想允许少量精化重试，建议最多 2 次。重试必须说明改动假设和预期指标；连续重试看不到明确收益、触碰时间门槛或出现等价性风险时，立即标记 `REJECTED`，转向新的独立方法。不得通过反复微调同一参数消耗迭代。

优先级建议按“运行时间收益 / 生成时间增量 / 编译时间增量 / 等价性风险”排序。先用统计、代码尺寸、supernode/partition 分布和热点测量缩小问题，再实施改动；没有测量依据的优化只登记为候选，不直接作为主线。

## 单次实验记录模板

将以下模板复制到本文件末尾，或另存为 `pdocs/experiments/<ID>.md`。档案索引必须链接到每个实验记录。

```markdown
## <ID> <简短名称>

- 日期：
- 状态：IDEA | BASELINE | IMPLEMENTED | VALIDATED | ACCEPTED | REJECTED
- commit：
- 假设：哪个通用瓶颈、为什么预期有效、预期影响哪个阶段
- 改动范围：文件/模块；确认未触碰禁止项
- 输入固定项：XiangShan revision、CoreMark binary、top、cycle 范围、定义、waveform/trace
- 执行目标：逐字记录 Makefile target 和变量；禁止填手工底层命令
- 资源约束：CPU 绑定、仿真线程数、编译 jobs、内存（如已知）
- 生成耗时：`<秒数>`；结果 `PASS | TIMEOUT_KILLED | FAIL`
- 编译耗时：`<秒数>`；结果 `PASS | TIMEOUT_KILLED | FAIL`
- 仿真耗时：`<秒数>`；退出状态：；等价性：`PASS | INVALID`
- 仿真止损阈值：基线比较值 `<秒数>`；1.5× 阈值 `<秒数>`；止损结果 `NONE | REGRESSION_KILLED`
- 代码规模：C++ 文件数、总行数/字节数、目标文件或二进制大小（可得时）
- 关键计数：IR op、partition/supernode 数量、最大/平均规模、热点统计
- 对比：gsim 时间；当前 GrhSIM-IR 基线时间；本实验时间；变化百分比
- 结论：接受/拒绝及证据
- 后续：最多列一个精化重试，否则提出新的设想
- 实验方法：计时边界、重复次数、等价性检查方法及结果
- 结果正文：各次测量值、基线对比表、变化百分比及计算口径
- 分析正文：关键统计/诊断摘录及解释、瓶颈机制、噪声与限制
- 归档引用：仅链接已纳入 Git 的报告或附件；临时产物的分析直接写入正文
- 提交检查：本报告、引用文件和实验索引均已添加到 Git，并随归档提交

记录应在实验推进过程中逐段填写；本模板允许先提交只有假设的 `IDEA` 记录，后续 goal 执行再补充同一记录或关联报告。
```

## 档案索引与阶段门

在本文件末尾维护实验索引表，按时间顺序记录 ID、状态、仿真时间、生成时间、编译时间和结论。每周或每完成 3 个实验，整理一次“当前最佳方案”和“已排除方向”，避免重复尝试。

阶段门如下：

- **M0 基线**：固定输入，完成 gsim 与当前 GrhSIM-IR 的可复现实测。
- **M1 定位**：有热点或结构统计，提出至少 3 个互不相同的候选方向。
- **M2 快速筛选**：候选通过小规模等价检查和生成/编译时间门槛。
- **M3 完整验证**：在 CoreMark 50k 上完成单线程全流程，等价且无超时。
- **M4 收敛**：记录最终最佳 commit、完整命令、全部计时和已知限制；将自包含的实验分析报告和索引提交到 Git，检查所有文件引用均已纳入 Git；只有此时 goal 才可关闭。

## 完成条件

当且仅当 M4 记录完整且已提交到 Git，最佳 GrhSIM-IR 方案在固定输入下满足仿真目标、生成 `<30 min`、编译 `<30 min`，并有行为等价证据和至少一次独立复跑，goal 才算完成。若所有候选均未达标，提交失败分析档案和下一轮候选，不得用缺失数据宣称完成。

goal 的“完成一次”定义为完成一个搜索步骤并提交该步骤的增量归档；它不等同于关闭本 goal。只有达到 M4 的最终条件，整个优化 goal 才可关闭。

## 阶段记录

### M0 基线：已完成

固定输入为 XiangShan revision `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`、`ready-to-run/coremark-2-iteration.bin`（SHA-256 `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`）、top `SimTop`、50,000 cycles、`DIFFTEST`，waveform/trace 全部关闭。仿真绑定 CPU 2，明确设置 `XS_EMU_THREADS=1`；机器 `nproc=32`，编译使用多 job。

gsim 运行 20.640 s，退出 0，73,584 instructions，`cycleCnt=49998`，terminal PC `0x8000131e`。当前 GrhSIM-IR pack 0 运行 304.197 s，退出 0，73,580 instructions，`cycleCnt=49996`，terminal PC `0x80001312`；两者均启用 NEMU difftest 且无 mismatch。GrhSIM-IR 生成 87.993 s、编译 502.33 s，均小于 1,800 s。完整方法和限制见 [M0 report](grhsim-ir-m0-baseline-20260910.md)。

### M1 定位：已完成

GrhSIM-IR pack 0 生成 5,749 个 C++ 文件，其中 5,595 个是 task 文件，5,081 个 task 文件含 active-word 逻辑。`eval()` 每轮无条件调用 5,595 个 task；这解释了大量 task body 在 activity byte 为零时仍被进入。IR 规模为 4,530,736 operations、4,285,682 values、508,487 states。基于该证据登记了三个互不相同的方向：

1. **局部 frame 初始化**：移除每次 active supernode 调用的 `std::byte cpu_local[N]{}` 清零。
2. **activity-driven outer guard**：在 evaluator 调用 activity task 前 OR 检查该 task 的 active-word bytes。
3. **target batch packing**：把 `XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT` 设为 64，减少 translation units。

候选 1 和 2 完成了 50k 等价实验，候选 3 完成了生成及部分编译筛选；独立报告记录了各自的通用触发条件，未使用模块名称匹配。

### M2 快速筛选：已完成

| 候选 | 生成 | 编译 | 等价性 | 筛选结论 |
|---|---:|---:|---|---|
| frame initialization | 86.12 s PASS | 466.12 s PASS | 50k PASS | 拒绝：305.17 s，比基线慢 0.320% |
| activity outer guard | 87.709 s PASS | 约 515.7 s PASS | 50k 两次 PASS | 保留：平均 284.699 s，比基线快 6.410% |
| batch count 64 | 594.922 s PASS | 未完成，无 emu | 无可比较运行 | 拒绝本轮筛选；无速度结论 |

所有完成的生成/编译阶段均小于 1,800 s。候选 3 的 680 个 C++ 文件和 169 个已生成 object 只作为结构筛选事实，未被当作性能证据。详细结果见各候选报告。

### M3 完整验证：部分完成

activity outer guard 使用 GrhSIM source commit `c3dfad0cc19e29943b65d815ae180fdbd42f1bee` 完成两次独立 50k 运行：289.305 s 和 280.093 s，均退出 0、NEMU difftest PASS、73,580 instructions、`cycleCnt=49996`、terminal PC `0x80001312`。生成和编译没有超时。它是当前最佳可复现方案，但平均 284.699 s 仍为 gsim 的 13.794 倍，未达到约 40 s 目标，因此 M3 的性能验收不通过。

ready-queue dispatcher 完成生成、稳定 round-trip 和编译，但首次 50k 仿真在 cycle 0 触发 XiangShan RTL assertion，`instrCnt=0`、`pc=0x0`，退出 2；因此没有计入性能数据，详见 [ready-queue report](grhsim-ir-candidate-ready-queue-20260910.md)。该方向拒绝。

ready-bit dispatcher 完成 focused 测试、生成、稳定 round-trip、编译和一次完整 50k 仿真；仿真退出 0 且对拍通过，但耗时 737.862 s，约为 activity-guard 平均值的 2.59 倍。该方向拒绝，详见 [ready-dispatch report](grhsim-ir-candidate-ready-dispatch-20260910.md)。

### M4 收敛：档案完成，性能目标未完成

M0、M1、M2、M3 的自包含报告、实验索引、当前最佳 commit、完整命令、限制和失败方向均已纳入 Git。由于最佳方案尚未达到约 40 s 仿真目标，不能关闭 goal。下一轮应从 task-call/生成代码剩余成本提出新的、独立且有统计依据的候选；不得重复 frame 初始化或把 batch64 的未完成编译当作收益。

## 实验索引

| ID | 日期 | 状态 | 仿真(s) | 生成(s) | 编译(s) | 结论 |
|---|---|---|---:|---:|---:|---|
| [M0 baseline](grhsim-ir-m0-baseline-20260910.md) | 2026-09-10 | BASELINE / VALIDATED | 20.640 gsim; 304.197 IR | 87.993 IR | 502.33 IR | 固定输入和热点已建立 |
| [frame-init](grhsim-ir-candidate-frame-init-20260910.md) | 2026-09-10 | REJECTED | 305.17 | 86.12 | 466.12 | 清零移除无收益，慢 0.320% |
| [activity-guard](grhsim-ir-candidate-activity-guard-20260910.md) | 2026-09-10 | VALIDATED / BEST | 289.305; 280.093 | 87.709 | 约 515.7 | 平均快 6.410%，仍慢于目标 |
| [batch-packing](grhsim-ir-candidate-batch-packing-20260910.md) | 2026-09-09 | REJECTED / INCOMPLETE | — | 594.922 | 未完成 | 680 files，但无完整编译和仿真 |
| [ready-queue](grhsim-ir-candidate-ready-queue-20260910.md) | 2026-09-10 | REJECTED / INVALID | cycle 0 failure | 589.254 | 约 707 | RTL assertions, 0 instructions; no timing result |
| [ready-dispatch](grhsim-ir-candidate-ready-dispatch-20260910.md) | 2026-09-10 | REJECTED / REGRESSION | 737.862 | 87.647 | 约 700 | 功能通过但比 activity-guard 慢约 2.59 倍 |
| [activity-mask-pack](grhsim-ir-candidate-activity-mask-pack-20260910.md) | 2026-09-10 | IDEA | — | — | — | 将 activity guard 的多字节检查压缩为分组机器字加载，待实现验证 |
