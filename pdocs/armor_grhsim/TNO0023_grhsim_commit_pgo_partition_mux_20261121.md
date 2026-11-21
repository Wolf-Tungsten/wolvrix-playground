# TNO0023　GrhSIM 成块提交、PGO、计算组划分与条件 mux

## XiangShan 计时

同一 PGO 设置下，三组规则、160 超节点上限、最多 16 个寄存器的原生成块提交组合，在 CoreMark 的配对耗时变化为 **−9.01%**，未用于训练的 MicroBench 为 **−10.85%**。

| 同轮对照（前 → 后） | 前 / s | 后 / s | 同轮变化 | 95% 配对区间 | 后者更快 |
| --- | ---: | ---: | ---: | ---: | ---: |
| CoreMark，无 PGO，原样 → 成块提交 | 85.04 | 82.03 | −3.53% | [−4.23%, −2.71%] | 4/4 |
| CoreMark，PGO 原样 → 仅三组 | 78.46 | 76.67 | −2.28% | [−2.70%, −1.79%] | 4/4 |
| MicroBench，PGO 原样 → 仅三组 | 74.22 | 71.73 | −3.36% | [−3.90%, −2.70%] | 4/4 |
| CoreMark，PGO 三组 → 三组加成块提交 | 76.67 | 72.73 | −5.14% | [−5.37%, −4.81%] | 4/4 |
| MicroBench，PGO 三组 → 三组加成块提交（正式版） | 68.91 | 65.56 | −4.87% | [−5.14%, −4.61%] | 4/4 |
| CoreMark，PGO 三组和成块提交，mux 门槛 16 → 8 | 72.73 | 73.08 | +0.47% | [−0.13%, +1.39%] | 1/4 |
| CoreMark，PGO 原样 → 三组、108 上限、正式四寄存器块 | 78.21 | 75.82 | −3.06% | [−7.29%, +4.40%] | 3/4 |
| MicroBench，PGO 原样 → 三组、108 上限、正式四寄存器块 | 71.24 | 65.56 | −7.96% | [−9.04%, −7.36%] | 4/4 |
| CoreMark，PGO 原样 → 三组、160 上限、正式宽块 | 86.11 | 78.24 | −9.01% | [−10.78%, −5.82%] | 4/4 |
| MicroBench，PGO 原样 → 三组、160 上限、正式宽块 | 79.18 | 70.58 | −10.85% | [−11.55%, −10.11%] | 4/4 |

CoreMark 的无 PGO 分项和相对三组的 −5.14% 使用静态零表改动前的原生实现。MicroBench 的 −4.87% 已使用静态零表。这些分项的上限均为 108，每块最多四个寄存器。表内百分比均为同轮直接比较。

**默认配置与可用产物。** XiangShan 单模型完整 PGO 入口自动选用三组规则和成块提交，计算超节点上限 160，底层计算节点与拆分上限均为 108。数据块最多 16 个寄存器、总长最多 16 字节，条件 mux 门槛 16。逐参数重新发射后，正式 Make 入口生成的 140 个模型构建输入和调度统计与计时使用的对应模型完全一致。设置 `WOLVRIX_XS_GRHSIM_PGO_GROUPS=0` 可使用普通生成默认值进行 PGO 训练，单项开关和显式容量也经过回归。[Make 入口核验](../../build/armor-gap-followup-v1/make-default16/identity.json) · [对照的 PGO 可执行文件](../../build/armor-gap-followup-v1/joint/build/emu) · [实际训练 profile](../../build/armor-gap-followup-v1/joint/build/grhsim.profdata)

在最终 160 上限下，宽块相对四寄存器块的独立计时为 CoreMark −0.56%（区间跨零）、MicroBench −0.70%（四轮均快）。条件 mux 保留门槛 16。按 CoreMark 恢复提前求值的小 mux 在 MicroBench 上出现反向结果。按访问次数过滤末端迁移覆盖的操作很少，默认流程不启用局部移动。后续若继续做局部移动，可以把能否在同一轮激活和移动所带入的输入边计入候选得分，并沿用同容量、同起点的对照。

上表运行固定在 node030 CPU 96，使用 NUMA 1 的本地代码和数据页、单线程、固定 ASLR 与相同 NEMU。每个版本独立预热一次，之后同一轮交错运行。每轮请求 100,000 周期，模拟器报告 100,001 guest cycles。秒数为四次外部 walltime 均值，百分比为四个同轮耗时比的均值减一，区间是固定种子的配对 bootstrap。PGO 同时覆盖 DiffTest harness 和模型，各候选都用自己的 CoreMark 窗口训练。MicroBench 未参与训练。两个窗口都启用 DiffTest。[原始计时](./data/TNO0023_times.csv) · [运行代码](../../build/armor-gap-followup-v1/measure.py)

## 寄存器提交

在同一事件和同一写使能组内，生成器查找全掩码、单写者标量寄存器。若物化的新值槽连续且与旧值字段同型、同序，便先比较整块。相等时跳过，相异时执行原有的逐项写入和读者通知。已有的 lockstep 和 same-reader 写组有优先权。多写者、部分掩码、直接引用可变状态的新值走原有路径。另一个独立改动把同事件下的连续布尔使能合并，最多八个同时为假时跳过相应写组。定义数据块的上限为 16 字节，可配置其中的最大寄存器数。[实现](../../wolvrix/lib/emit/grhsim_cpp.cpp) · [选项](../../wolvrix/docs/emit/grhsim-scheduling.md) · [执行计划的工作量](../../wolvrix/docs/emit/grhsim_execution_plan.md)

| 静态代码中的覆盖 | 每块最多 4 个，无三组 | 每块最多 4 个，有三组 | 每块最多 16 个，有三组 |
| --- | ---: | ---: | ---: |
| 数据比较块 | 33,356 | 35,724 | 18,964 |
| 被覆盖的寄存器写点 | 116,486 | 122,317 | 122,829 |
| 其中 64 位写点 | 4,706 | 7,266 | 7,266 |
| 使能块 / 使能组 | 5,307 / 41,820 | 5,307 / 41,820 | 5,307 / 41,820 |

两行覆盖计数的单位分别为寄存器写点和使能组，存在重叠。TNO0022 的文本原型覆盖 91,672 个数据写点。生成器现在能同时安排旧值字段和布尔使能槽，扩展到了 64 位寄存器。ABI 的字段间距若不连续，生成代码退回逐项检查。[生成模型计数](../../build/armor-gap-followup-v1/shapes.log)

机器码检查发现，Clang 23 在无 PGO 的批次 88 把四个相邻布尔值编成一条 32 位加载、一条比较和一个条件跳转。在批次 70，直接用临时零数组比较八个使能时，虽然有了 64 位内存比较，每个比较点仍会把零写到栈上。改为共享 `static constexpr std::array<bool, 8>` 后，这个批次的该类栈写从 391 条降到 0。用于源码对照的两个目标文件加行号后，代码段分别与原编译逐字节相同。同为上限 108、每块最多四个寄存器的两个全开版本共有 140 个构建输入，除了静态零表及 5,307 个引用点，其余源内容完全一致。在该版本最终链接的 PGO ELF 中，批次 70 从地址 `0x4af5bd3` 起连续用 `cmpq $0,disp(%rbx)` 检查使能。[最终 ELF 短反汇编](../../build/armor-gap-followup-v1/machine/final-commit70-prefix.asm) · [数据块反汇编](../../build/armor-gap-followup-v1/machine/grhsim_SimTop_sched_88.asm) · [使能块反汇编](../../build/armor-gap-followup-v1/machine/zero/zero.asm) · [源文件核对](../../build/armor-gap-followup-v1/final/source-comparison.json)

在 CoreMark 诊断运行中，每 guest cycle 的无 PGO 退休指令由 3,569,913 降到 3,318,975，分支由 278,918 降到 180,350。整 ELF 的代码段同时从 84,997,442 B 增至 85,347,666 B。少走逐项检查的执行路径足以抵消这个版本增加的代码。各候选的整 ELF 代码段和独立热点函数的大小均已保存。[PMU 原始结果](../../build/armor-gap-followup-v1/pmu/) · [ELF 代码段与函数大小](../../build/armor-gap-followup-v1/elf-sizes.json)

对 160 上限下的两种块宽，在每个实际发射的数据或使能块比较处记录访问次数和结果。CoreMark 每拍观测如下，计时 ELF 均不含这些计数器。[插桩源代码](../../build/armor-gap-followup-v1/block_visits.py) · [块宽 4](../../build/armor-gap-followup-v1/block-visits-combo160/counts/result.json) · [块宽 16](../../build/armor-gap-followup-v1/block-visits-joint/counts/result.json)

| 数据块路径 | 最多 4 个寄存器 | 最多 16 个寄存器 |
| --- | ---: | ---: |
| 整块比较 / guest cycle | 25,739 | 10,529 |
| 整块含变化的比例 | 2.44% | 4.94% |
| 进入逐项路径的寄存器 / guest cycle | 1,944 | 3,183 |
| 被块覆盖的寄存器访问 / guest cycle | 94,686 | 94,839 |

覆盖量近似不变，每拍少约 15,210 次整块比较，多约 1,239 次逐项检查。使能块配置相同，两边均为每拍 5,298 次比较，只有 9.73% 需要进入组内。普通提交路径在不匹配时仍按原顺序执行写入与通知。[最终版 PMU](../../build/armor-gap-followup-v1/pmu/joint/result.json)

## PGO 构建入口

`xs_wolf_grhsim_emu` 收到 `PGO_WORKLOAD` 时，先从相同的生成源码编译插桩版，运行指定负载，合并 profile，清理插桩产物后重编模型和 harness，再发布 `emu` 和 `grhsim.profdata`。Clang 23 插桩编译关闭 SLP，profile-use 编译使用完整优化。三个选项组为事件区域、条件 mux（包括输入缓存与共享臂）和 covered state views。PGO 时自动选择这三组，单组或底层标志的显式配置可覆盖相应默认值。设置 `WOLVRIX_XS_GRHSIM_PGO_GROUPS=0` 可同时关闭这些 PGO 自动设置。单模型 PGO 同时默认启用成块提交，设置 `WOLVRIX_GRHSIM_COMMIT_COMPARE_BLOCKS=0` 可关闭成块提交。[构建目标](../../Makefile) · [PGO 驱动](../../scripts/xs_grhsim_pgo.py) · [XS 选项](../../scripts/wolvrix_xs_grhsim.py)

在已配置的工作区复现正式版可用下列命令。测试时 Clang 与 llvm-profdata 均为 23.1.2，harness 和模型都开了 `-march=native`。命令复用当前工作区的 XiangShan 设置。

```bash
source env.sh
make xs_wolf_grhsim_emu \
  PGO_WORKLOAD="$NOOP_HOME/ready-to-run/coremark-2-iteration.bin" \
  PGO_MAX_CYCLE=100000 \
  CC=clang CXX=clang++ LLVM_PROFDATA=llvm-profdata \
  EMU_OPTIMIZE="-O3 -march=native" GRHSIM_MODEL_CXXFLAGS="-std=c++20 -O3 -march=native"
```

实测正式版从 TNO0017 的同一 pre-reg-to-mem 检查点重新执行后续 pass 和生成流程，通过上述 Make 目标训练并回编。本轮没有重跑原始 Chisel elaboration。各选项实验复用同一检查点或经校验的旧模型。PGO 三组的 MicroBench 配对为 74.22 s → 71.73 s，耗时 −3.36%，四轮均更快。旧的无 PGO 对照在 TNO0020。[正式构建实参](../../build/armor-gap-followup-v1/final_build.sh) · [MicroBench 配对](../../build/armor-gap-followup-v1/timing/micro-groups/summary.json) · [TNO0020](./TNO0020_xiangshan_cv32_groups_20261120.md)

## 计算组划分

TNO0022 的 662,030 个值对应普通组合生产者、**只有一个外部目标组**。其中 290,633 个目标是提交组，371,397 个是计算组。逐一检查能否把生产簇完整移入唯一的读者计算组，原上限 108 下，33,761 个值符合容量条件，15,291 个还符合现有拓扑顺序。硬上限放到 160 时这两个数字变成 193,386 和 107,311。计数包括其他边和隐式提交依赖，仍是单个候选的上界。多个候选可争用同一空位，移动可制造新的输入边，还有 7,029 个候选值在旧组内也有读者。[原始分类](../../build/armor-gap-followup-v1/single-reader.tsv) · [审计代码](../../scripts/armor_single_reader_audit.cpp)

把原调度的组访问计数与完整生产簇对应，160 上限下上述 107,311 个候选里，目标组比原组更冷 35,414 个、访问次数相同 26,830 个、更热 45,067 个。这里比较移动前的累计访问次数，同次数的两个组仍可能在不同轮激活。按候选对应的操作数和目标与原组的访问差排序，可以作为后续闭环试验的起点。[逐上限带访问分类的审计](../../build/armor-gap-followup-v1/single-reader.tsv)

两项调度实验中，底层计算节点的拆分上限固定为 108，PGO 组与新提交优化都关闭。`cap160` 只放宽超节点上限。`refine` 的初始 coarsen / DP 仍取 108，为后续移动留下容量，在最大 160 内只接受既有 strict 策略允许的移动，受 32,768 次和总操作数 10% 的预算约束。实际移动 32,768 次，涉及 427,356 个操作，没有交换。两者使用相同的 1,316,098 个底层计算节点。[调度选项](../../wolvrix/docs/transform/activity-schedule.md) · [实际移动与拒绝数](../../build/armor-gap-followup-v1/refine/emit.log)

| 静态量 | 原 108 | 直接 160 | 初始 108，移动上限 160 |
| --- | ---: | ---: | ---: |
| 最终计算组 | 75,692 | 52,464 | 75,692 |
| 分段前的边界值 | 1,209,565 | 1,101,002 | 1,209,565 |
| 最终边界值 | 1,207,694 | 1,098,630 | 1,182,912 |
| 最终跨组激活边 | 2,387,296 | 2,174,039 | 2,237,141 |
| 普通组合生产者、单外部目标的值 | 662,030 | 593,890 | 700,131 |
| 组大小中位数 / p99 | 100 / 108 | 143 / 160 | 100 / 156 |

直接 160 的边界值少了 9.03%，其中绝大部分已在初始粗化阶段兑现。保持初始目标 108 后再移动，最终边界值少 2.05%、激活边少 6.29%，单外部目标的值反而更多。一个多目标值减少到一个目标也会增加这个计数。[基线统计](../../build/armor-expression-default-v1/default/model/activity_schedule_supernode_stats.json) · [160 统计](../../build/armor-gap-followup-v1/cap160/model/activity_schedule_supernode_stats.json) · [局部移动统计](../../build/armor-gap-followup-v1/refine/model/activity_schedule_supernode_stats.json)

分别在三个未开条件 mux 的模型的每个计算组入口插一个计数器，只用插桩版观察组访问。下表的“普通操作”用每组访问数乘组内普通组合操作标记数，去掉常量、寄存器/锁存器/存储器读。比较点一列同法统计物化值的 `!= next_value` 站点。退休指令、L2 指令填充和预测失败来自各自无观察器的 PGO ELF 上独立的 `perf stat`，取用户态整进程计数除以 100,001。[组访问插桩](../../build/armor-gap-followup-v1/group_activity.py) · [PMU 记录](../../build/armor-gap-followup-v1/pmu/)

| 每 guest cycle | 计算组访问 | 组内普通操作 | 物化值比较点 | 退休指令 | L2 指令填充 | 分支预测失败 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 原 108 | 18,077 | 245,288 | 144,593 | 3,832,469 | 29,026 | 11,166 |
| 直接 160 | 13,851 | 258,466 | 147,511 | 3,923,402 | 27,040 | 9,762 |
| 初始 108，移动上限 160 | 18,669 | 246,120 | 142,057 | 3,873,526 | 32,236 | 11,627 |

| 同轮对照（前 → 后） | 前 / s | 后 / s | 同轮变化 | 95% 配对区间 | 后者更快 |
| --- | ---: | ---: | ---: | ---: | ---: |
| CoreMark，PGO 原 108 → 直接 160 | 78.21 | 79.13 | +1.17% | [+0.83%, +1.37%] | 0/4 |
| CoreMark，PGO 原 108 → 初始 108、移动上限 160 | 78.21 | 83.55 | +6.82% | [+2.79%, +13.96%] | 0/4 |
| CoreMark，三组、成块提交，108 → 160 | 75.82 | 71.35 | −5.65% | [−10.03%, −3.31%] | 4/4 |
| MicroBench，三组、成块提交，108 → 160（node029） | 76.66 | 72.88 | −4.93% | [−5.97%, −3.89%] | 4/4 |

直接放宽后，计算组访问变化 −23.38%，每次访问涉及的普通操作从 13.57 个升至 18.66 个，导致每拍这部分工作增加 5.37%。同一配置的分支预测失败和 L2 指令填充都下降。容量检查、静态边数和组内动态工作量需要分别检验。

为检验热组放大的假设，另用已有的 strict 末端迁移策略，只移动输出交给共同目标、检查后确有边界净收益的终端计算节点。两个版本均采用初始 108、硬上限 160、每个候选最多 32 个操作、最多 32,768 次移动和 10% 操作预算。热度版加了一项约束，即训练中目标组的访问次数不高于原组。用于筛选的计数来自原 108 分组，各个 ELF 的 Clang PGO 仍各自独立训练。[对照选项](../../build/armor-gap-followup-v1/terminal.py) · [训练组访问次数](../../build/armor-gap-followup-v1/terminal-heat-fires.tsv)

| 同轮对照（前 → 后） | 前 / s | 后 / s | 同轮变化 | 95% 配对区间 | 后者更快 |
| --- | ---: | ---: | ---: | ---: | ---: |
| CoreMark，相同末端迁移，引入热度过滤（node029） | 90.72 | 89.91 | −0.87% | [−1.68%, +0.20%] | 3/4 |
| CoreMark，原 108 → 带热度过滤的末端迁移（node029） | 92.72 | 89.91 | −3.01% | [−4.10%, −2.02%] | 4/4 |

MicroBench 的末端移动辅助试验出现明显外部负载差异，第四轮无过滤版本耗时 245.5 s，SMT 兄弟线程仅 25.6% 空闲。四轮中有两轮更快、两轮更慢，无法确认热度过滤的留出收益。CoreMark 独立 PMU 下无过滤和过滤版本分别为每拍 3,826,057 和 3,828,303 条指令。[MicroBench 原始运行](../../build/armor-gap-followup-v1/timing/heat-micro/rounds.json)

联合配置中的方向出现了变化。三组与每块四个的成块提交同时开启时，108 → 160 把静态边界值从 1,126,910 降至 1,039,932。退休指令从每拍 3,437,127 降到 3,386,173，分支预测失败从 12,696 降到 11,458，L2 指令填充从 28,328 降到 26,893。用新的分组再次对 mux 两臂计数，即使静态根数从 11,448 减到 11,143，动态跳过的估计 IR 操作也从每拍 40,343 增至 44,701。这些量说明两项改动发生了交互，尚不能把所有加速都归给 mux。[组合模型统计](../../build/armor-gap-followup-v1/combo160/model/activity_schedule_supernode_stats.json) · [较大组的 mux 动态计数](../../build/armor-gap-followup-v1/obs160/counts/summary.json)

末端移动的覆盖也可直接解释。无热度筛选时成功移动 961 个计算节点、981 个操作，减少 961 个边界值。加过滤后，965 个候选因目标更热被排除，2,417 个剩余合法候选里又有 1,821 个与已选移动共享组。实际移动 596 个节点、616 个操作，减少 596 个边界值，均未耗尽移动预算。加大预算对这次选择没有帮助。[无热度筛选记录](../../build/armor-gap-followup-v1/terminal/emit.log) · [热度筛选与冲突原因](../../build/armor-gap-followup-v1/terminal-heat/emit.log)

## 条件 mux

在原 108 调度上，仅开条件 mux 一组与原样 PGO 做相同 CPU 的成对 IBS 采样。两边的活动调度统计哈希和 97 个调度文件中对应的组 ID 顺序完全一致。将有行号的时间落到生成的计算组，按该组中有私有操作的 mux 臂分类。下表只列组内所有已识别条件 mux 均属同一类别的组。估算用同次运行的 `cycles:u` 乘该类 IBS 样本比例，单位为每个 guest cycle 的宿主周期。[ELF 与对应源码核对](../../build/armor-gap-followup-v1/paired-samples/source-check.json) · [原始分组样本](../../build/armor-gap-followup-v1/paired-samples/comparison.json)

| 组内条件 mux 的形状 | 保持提前求值 | 条件求值 | IBS 样本数，前 / 后 |
| --- | ---: | ---: | ---: |
| 只有真臂含可移动计算 | 63,369 | 42,731 | 5,332 / 3,594 |
| 只有假臂含可移动计算 | 49,001 | 48,271 | 4,123 / 4,060 |
| 两臂都有可移动计算 | 15,355 | 10,712 | 1,292 / 901 |

此处采样覆盖整个组，也包括组内的非 mux 语句。两次整进程 PMU 为 283.04 万和 280.74 万宿主周期/guest cycle，仅一次配对。条件版 236,124 个样本中仅 4,676 个能直接落到已发射的 mux 条件或臂，涉及 2,497 个根。为核对差异的方向，另在三组全开模型的每处条件 mux 对两条臂分别计数，插桩版只用于观察。16 门槛下，每拍因不选中而跳过的 40,343 个私有 IR 操作里，约 29,442 个来自只有真臂有私有计算的根，2,029 个来自只有假臂有私有计算的根。[按根插桩](../../build/armor-gap-followup-v1/observe_mux.py) · [原始臂计数](../../build/armor-gap-followup-v1/obs16/counts/summary.json)

降低 `WOLVRIX_GRHSIM_CONDITIONAL_MUX_MIN_OPS` 的对照只改变原有纯度、标量宽度和私有性证明通过后的规模门槛。16 → 8 时，静态根数 11,448 → 31,898，实际每拍选择 2,597 → 7,962 次，估计跳过的计算 40,343 → 60,676 个 IR 操作。后一个数按动态访问乘静态臂内操作数计算，部分操作可被 Clang 消去。第三个版本 `guided` 保留阈值 8 的结构，仅将 CoreMark 中每次选择平均跳过不足一个 IR 操作的 12,944 个已执行小型单臂根恢复原有提前求值，独立重新训练 PGO。该规则只在生成 C++ 上试验。[可配置门槛](../../wolvrix/docs/emit/grhsim-conditional-mux-cones.md) · [8 的动态统计](../../build/armor-gap-followup-v1/obs8/counts/summary.json) · [选择与源码改写](../../build/armor-gap-followup-v1/profile_mux.py)

下列宽度及选择规则的辅助对照在 node029，不跨主机换算耗时。各组固定一个物理核心和 NUMA 1、独立本地运行副本，轮换位置，训练都用 CoreMark。参照均使用同一份临时零表写法、PGO 三组与成块提交。

| 同轮对照（前 → 后） | 前 / s | 后 / s | 同轮变化 | 95% 配对区间 | 后者更快 |
| --- | ---: | ---: | ---: | ---: | ---: |
| CoreMark，mux 门槛 16 → 8 | 79.92 | 80.05 | +0.12% | [−1.38%, +1.62%] | 2/4 |
| CoreMark，门槛 8 → 按训练选择恢复部分提前求值 | 80.05 | 77.78 | −2.77% | [−5.57%, −0.34%] | 4/4 |
| CoreMark，块宽 4 → 16，mux 门槛 16 | 79.92 | 77.62 | −2.88% | [−5.45%, −1.28%] | 4/4 |
| MicroBench，mux 门槛 16 → 8 | 77.62 | 76.91 | −0.91% | [−1.65%, −0.16%] | 4/4 |
| MicroBench，门槛 8 → 按训练选择恢复部分提前求值 | 76.91 | 77.32 | +0.53% | [+0.03%, +1.13%] | 1/4 |
| MicroBench，块宽 4 → 16，mux 门槛 16 | 77.62 | 75.92 | −2.17% | [−3.10%, −1.39%] | 4/4 |

| 同轮对照（前 → 后） | 前 / s | 后 / s | 同轮变化 | 95% 配对区间 | 后者更快 |
| --- | ---: | ---: | ---: | ---: | ---: |
| CoreMark，PGO 原样 → 只加成块提交 | 92.70 | 87.27 | −5.84% | [−6.92%, −4.79%] | 4/4 |
| CoreMark，PGO 原样 → 三组、108 上限、正式四寄存器块（编译机复测） | 92.70 | 84.39 | −8.95% | [−10.17%, −7.73%] | 4/4 |

用最终生成器重新生成最多 16 个寄存器的版本，保留共享静态零表，在 node030 NUMA 0 复测上限 108。其中一轮 CoreMark 的四寄存器块对照耗时 183.5 s，SMT 兄弟线程仅 30.3% 空闲。MicroBench 原 PGO 对照也有一轮达到 303.1 s。原始秒数收录在 CSV，这两组辅助计时不用于选择默认值。[CoreMark 各轮](../../build/armor-gap-followup-v1/timing/wide-core/rounds.json) · [MicroBench 各轮](../../build/armor-gap-followup-v1/timing/wide-micro/rounds.json)

在完整 PGO 配置上固定 160 上限后，将相同的两份 ELF 放回 CPU 96，分别在两个负载直接比较块宽。最早在 NUMA 0 的联合对照出现了 235.39 s 的 CoreMark 样本，SMT 兄弟线程空闲率 17.96%。该系列作为诊断保留，表中采用固定 CPU 96 的整组复测。[排除记录](../../build/armor-gap-followup-v1/timing/joint-core/excluded.json)

| 同轮对照（前 → 后） | 前 / s | 后 / s | 同轮变化 | 95% 配对区间 | 后者更快 |
| --- | ---: | ---: | ---: | ---: | ---: |
| CoreMark，上限 160，块宽 4 → 16 | 79.14 | 78.70 | −0.56% | [−1.19%, +0.34%] | 3/4 |
| MicroBench，上限 160，块宽 4 → 16 | 72.03 | 71.53 | −0.70% | [−1.24%, −0.16%] | 4/4 |

node029 各轮 SMT 兄弟线程的最低空闲率为 CoreMark 扩展 98.32%、MicroBench 扩展 97.65%、发布版复测 100.00%。该机负载可变，细小差异以 node030 CPU 96 的对应结果为主。最早的 node029 调度预热碰到同核竞争，已在正式采样前终止，其中原 108、直接 160、局部移动的 CoreMark 对照已在 node030 复测。各次运行的顺序、核心、同核空闲率、二进制哈希都保存在 CSV。

重新用同一个阈值 8 的插桩 ELF 运行 MicroBench，直接跟踪上述 12,944 个根。CoreMark 上保持条件求值每次平均跳过 0.054 个私有 IR 操作，MicroBench 上为 0.080 个。后者有 1,073 个根跨过每次一个操作的筛选线。将这批根全部提前求值，每 guest cycle 重新执行的估计 IR 量分别为 189 和 224。这是训练分布偏移的实测证据。原始样本有限，操作数只占整机一部分。[训练与留出逐根计数](../../build/armor-gap-followup-v1/obs8/microbench/transfer.json)

## 核验

完成 20 个“实现 × 负载”的逐记录对照，每个与冻结参考匹配 99,999 条 DiffTest 活跃字段记录。正式四寄存器块、宽块、160 与宽块组合均覆盖两个窗口。CoreMark 终点 PC 为 0x80000c1a、提交 250,838 条指令，另外逐行核对全部 35,063 行期末性能计数。MicroBench 终点 PC 为 0x80000446、提交 138,514 条指令，该运行方式不导出期末计数。所有正式计时均检查终点、负载输出及 DiffTest 状态。[逐记录与终点结果](../../build/armor-gap-followup-v1/verify/)

39 个 XS Python 选项与 Make 入口测试和 12 个相关原生 CTest 通过。额外 8 项 mux 缓存、逐组通知、提交与宽状态兼容性测试全部通过。增加工作量归因和重新构建 Python 绑定后，对应的 4 项与 9 项重跑也通过。提交测试包括多个时钟、使能、掩码、多写者、已有聚合写、重复初始化，并用 O0 和带 ASan/UBSan 的 O3 检查模型输出。PGO 驱动另有小模型验证，确认训练失败时上一次发布的文件仍可用。[Python 测试](../../build/armor-gap-followup-v1/python-tests.log) · [原生回归](../../build/armor-gap-followup-v1/ctest-regression.log) · [工作量归因回归](../../build/armor-gap-followup-v1/test-work-model.log) · [兼容性回归](../../build/armor-gap-followup-v1/ctest-compat.log) · [重建后的接口回归](../../build/armor-gap-followup-v1/retest-api.log) · [PGO 驱动验证](../../build/armor-gap-followup-v1/flow-smoke/result.log)

两个窗口均沿用 GrhSIM 既有的组合 DPI 行为。TNO0022 对 GSIM 对齐这两处 DPI 后的 52.99 s 是上一轮数据，本轮只比较 GrhSIM 各版本。工作负载长度、PGO 训练窗口和目标机器均固定，新选项在更长窗口和其他设计上的表现仍待验证。[TNO0022](./TNO0022_grhsim_gsim_gap_causes_20261121.md)
