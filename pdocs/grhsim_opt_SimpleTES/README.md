# SimpleTES 已合入 Wolvrix 主线的优化

本目录按时间顺序记录了 **SimpleTES 首次建立研究基线之后，真正合入 Wolvrix 集成主线** 的 GrhSIM 优化。这里的“主线”指当前工作使用的 Wolvrix 集成分支（`thj/gsim-calibrate-2`），而不是声称这些提交已经进入远端 `origin/main`。目标不是罗列 patch 名称，而是说明每个改动解决了什么问题、为什么可能有效，以及在 SimTop 50k 上到底带来了多大 walltime 变化。

## 先建立一个仿真执行模型

Wolvrix 的 GrhSIM **emitter（代码生成器）**先把硬件模型的中间表示整理成一份
**schedule（执行计划）**，再输出 C++ 仿真代码。读懂后续优化只需要掌握下面这条主线：

```text
输入或持久状态发生变化
  -> 激活负责读取它的 compute supernode
  -> compute 计算产生的新值沿 fanout 传播
  -> commit 把本轮结果写回寄存器等持久状态
  -> 若写回又激活了读取者，则开始下一轮 compute/commit
```

`supernode` 是调度器一次整体执行的一组操作。`compute supernode` 计算组合结果，
`commit supernode` 提交寄存器等状态写入。一次 compute 加 commit 称为一个
**fixed-point round（不动点迭代轮次）**；重复到没有待处理工作时，当前输入采样才算
稳定。调度器用 **activity bitmap（活动位图）**记录哪些 compute supernode 待运行，
每个 compute supernode 在位图中对应的 bit 位置就是它的 **active ID**。commit
supernode 每轮按 schedule 扫描，不靠该位图激活。

本文中的 **event edge（事件边沿）**指某个 event value 相对旧值的变化分类，例如
上升沿、下降沿或无边沿；该值可以来自外部输入，也可以来自 compute 结果。它不是调度
图中的一条 graph edge。**guard** 是决定写入或副作用是否执行的布尔条件；**run** 是
同一 supernode 中连续且共享同一精确事件表达式的一段 write-port 序列；**batch** 是
生成器安排在同一 C++ 函数中连续执行的一批计算。

## 怎么读这些数字

文中“收益”统一指 SimTop 50k 的 `Host time spent`（walltime）。给定同一轮实验中的 control 和 candidate，计算方式是：

`相对收益 = (control walltime - candidate walltime) / control walltime`。

因此正数表示 candidate 更快；“绝对收益”是两者相差的毫秒数。每一行数字只在它自己的配对实验基线内成立，不能把不同轮次的百分比直接相加。ABBA/BAAB 是交错顺序的两组复测；文中同时给出它们，是为了让读者看到缓存和运行顺序造成的波动。除非另有说明，所有结果都来自已有 TNO 文档，本次没有重新运行性能测试。

实验术语的具体含义如下：

* **baseline/control/candidate**：baseline 是一轮研究的起点；control 是某次配对中的
  旧侧；candidate 是只增加或移除被测改动的新侧。字母 `B` 只是当前实验的 baseline
  标签，不同阶段的 `B` 不一定是同一个二进制。
* **arm**：一个明确的实验变体。**direct pair** 指两侧只相差被测机制；
  **endpoint** 指从阶段起点到最终组合的整体对比；**marginal** 是某一项在指定组合
  上的边际贡献。
* **ABBA/BAAB**：分别按 control-candidate-candidate-control 和
  candidate-control-control-candidate 的顺序运行，降低机器随时间漂移和执行顺序
  对结论的影响。`pooled` 表示汇合两种顺序的样本后分别求均值。
* **order gap**：ABBA 与 BAAB 所得改善率之差；`pp` 是百分点，例如 1.2% 与 1.0%
  相差 0.2 pp。**control spread** 是 control 样本自身的相对极差，用来判断机器噪声。
* **final-minus-one/leave-one-out**：从完整候选中移除一项，与完整候选直接比较。
  它回答“这项在当前组合中贡献多少”，不等于该项从最早 baseline 单独启用的效果。
* **gate**：决定候选能否继续或合入的检查。**fail closed** 表示静态证明不成立时保留
  原有通用代码路径，而不是冒险应用优化。**fresh** 表示从固定源码身份重新生成和构建，
  不复用可能受污染的工作树产物。
* **native landing**：把实验 patch 整理进 Wolvrix 通用源码后，用默认 options 重新
  生成、构建并验证；这里的 `native` 指主线默认路径。文中 `native bool` 则专指实际
  C++ 类型 `bool`，两者不是同一概念。

性能测试关闭 **ASLR（地址空间随机化）**，并固定 **NUMA（处理器和内存的拓扑位置）**
及空闲的 **CCD（AMD 处理器中共享末级缓存的一组核心）**，目的是减少地址布局、跨节点
访存和共享缓存竞争带来的噪声。**PMU** 是 CPU 硬件性能计数器；cycles、retired
instructions、frontend/backend stall 只用于解释可能原因，是否保留仍由 50k walltime
决定。frontend stall 表示取指/解码供给不足，backend stall 表示执行端在等待数据或
执行资源。

## 合入时间线

SimpleTES 的第一版研究基线固定在 2026-07-20 的 Wolvrix 提交 `f17e90e…`；在此之前的手工修改不计入本目录。之后沿着同一条主线形成了五个落地节点：

| 编号 | 合入日期 | Wolvrix 提交 | 本目录内容 |
|---|---|---|---|
| 001 | 2026-07-25 | `8f6ba14397b0c3d00cb909153af1c6464f4f1ed9` | exact-event 组合策略 |
| 002–004 | 2026-07-27 | `16a9f493687a21a5428f1e1327a69834ea60c9f5` | R、W、A 三个 RWA 增量 |
| 005–008 | 2026-07-31 | `fd12d83f5150cc98540ed3e8f2af3b79f8054da0` | 四个独立的正收益热路径改动 |
| 009–011 | 2026-08-01 | `d3ed9dea975bddf01185dde5c548a69241a09de9` | TRBS 事件边表示的三个增量 |
| 012–014 | 2026-08-13 | `79ec2037b00f2d4894d72785277ebe3f5d37782d` | typed-state 的三个增量 |

提交顺序由 `git log --follow -- lib/emit/grhsim_cpp.cpp` 核对；首次 SimpleTES 基线和“之前没有 SimpleTES 合入”的说明见 TNO0156。[^history]

## 逐项目录

### 第一阶段：exact-event

| 文档 | 一句话摘要 | 直接配对的结果 |
|---|---|---|
| [001 exact-event 组合策略](001_exact_event.md) | 用精确事件限定是否需要下一轮计算，并合并重复谓词/next 值、优化冷分支布局 | 74,773.25 → 61,284.00 ms，减少 13,489.25 ms，+18.040208% |

这一阶段使用的是 `commit_exact_event_policy`。早期候选曾借用 `active_mask_gap_pack_policy=targeted-direct`，但依赖审计证明两者没有逻辑或数据依赖；主线版本已经解耦，gap-pack 仍保持关闭。[^exact]

### 第二阶段：RWA

| 文档 | 一句话摘要 | 直接配对的结果 |
|---|---|---|
| [002 R：寄存器冷布局](002_r_register_cold_layout.md) | 对满足结构条件的寄存器写 guard 才采用冷分支布局 | 61,505.75 → 57,466.50 ms，+6.567272% |
| [003 W：MemoryWrite singleton hint](003_w_memorywrite_hint.md) | 在 R 已选中的运行中，把 singleton MemoryWrite guard 标为 `unlikely` | 57,031.25 → 55,965.00 ms，+1.869589% |
| [004 A：成对 assertion 外层 guard](004_a_assertion_guard.md) | 对相邻且同条件/同事件的 SystemTask 与特定 assertion 增加外层冷 guard，同时保留内部复核与副作用 | 55,485.00 → 54,050.50 ms，+2.585383% |

R、W、A 按累计实验链依次测试：W 的 selector 逻辑上依赖 R-selected run；A 是独立的
SystemTask/`xs_assert_v2` 嵌套机制，但它的单项数字是在 RWF baseline 上测得。三项并非
从同一个 baseline 独立启用，百分比不能横向相加。最终 RWA 端点在另一轮 native 复测中
为 60,881.50 → 54,088.00 ms（+11.158562%）。[^rwa]

### 第三阶段：四个正收益热路径改动

下列四篇使用 full-gen150 的 `final-minus-one` 消融。full-gen150 当时共有六项改动；
每次从完整六项组合中移除被测项，因此另外五项仍然存在。六项中的 residual
MemoryRead 和 physical zero-tail 后来因复测不能确认正收益而被排除，最终只有下列
四项落地。这里的单项数字是“该项在六项组合中的边际贡献”，不是在 RWA baseline 上
单独启用它的收益；RWA 到最终四项的独立 endpoint 才是落地组合的总收益。

| 文档 | 一句话摘要 | 直接配对的结果 |
|---|---|---|
| [005 冷 SystemTask/assertion hints](005_cold_systemtask_assert_hints.md) | 给常规 schedule 中的非 final SystemTask 及数据接口满足条件的 standalone assertion 增加冷分支提示 | 52,365.25 → 51,693.75 ms，+1.282339% |
| [006 hot word helpers always-inline](006_always_inline_helpers.md) | 给选定的高频 word helper 加统一的 always-inline 提示 | 52,032.75 → 51,645.75 ms，+0.743762% |
| [007 常量 MemoryRead](007_constant_memoryread.md) | 合法常量行直接使用字面量下标，并删除所有已知范围内读取的冗余 zero-before-load | 51,964.75 → 51,585.00 ms，+0.730784% |
| [008 动态 shift/index OOB hints](008_dynamic_oob_hints.md) | 只把越界 fallback 标为 `unlikely`，不改变正常路径语义 | 51,778.50 → 51,652.75 ms，+0.242861% |

四项全部启用后的 native 端点（RWA → four-positive）是 53,749.25 → 51,575.00 ms，减少 2,174.25 ms、+4.045173%。[^four]

### 第四阶段：TRBS 热事件表示

TRBS 面向的是**结构上很热的输入事件边沿**，不是 persistent logic state。名称展开为：

* `T`：typed event storage，用有明确 C++ 元素类型的数组保存事件边沿；
* `R`：hot-event remap，把被选择的热点事件放到内部 slot 0；
* `B`：decoded bool，预先保存“该热点是否为上升沿”的布尔结果；
* `S`：batch snapshot，在每个执行 batch 开头把该布尔成员复制到局部变量。

`T/TR/TRB/TRBS` 是同一条消融链上的**累计节点**，不是四个用户配置选项。R 的直接
`T→TR` 测试为 -0.009026%，属于噪声范围内的中性承载步骤；可确认的正收益边际来自
T、B、S。下表按实际被测边界列出三项正收益机制：

| 文档 | 一句话摘要 | 直接配对的结果 |
|---|---|---|
| [009 T：typed event storage](009_trbs_event_storage.md) | 用 typed event-edge 存储替代 byte arena | 51,333.75 → 49,923.00 ms，+2.748192% |
| [010 TRB：decoded exact-posedge bool](010_trbs_posedge_decode.md) | 为精确 posedge 事件预解码一个 bool，避免热路径反复解释 enum | 50,024.75 → 48,474.75 ms，+3.098466% |
| [011 TRBS：batch-local bool snapshot](011_trbs_batch_snapshot.md) | 在 schedule batch 内把稳定的热点 bool 保存为局部快照 | 48,449.75 → 47,495.50 ms，+1.969566% |

整条链 B → TRBS 的配对结果为 51,562.00 → 47,632.25 ms（+7.621407%）。后来把“原始 slot 数量门槛”改成按 posedge 使用次数和覆盖 batch 数计算的原则化门禁，结果 47,567.25 → 47,597.00 ms（-0.062543%，在噪声范围内），所以它是可维护性修正，不应被当作额外性能收益。[^trbs]

### 第五阶段：typed-state

typed-state 处理的是**持久化逻辑状态和值桶**，与 TRBS 的事件边沿生命周期不同。
持久状态是寄存器、锁存器等跨 batch、跨仿真步骤继续保存的设计状态；materialized
value 则是为了让组合计算结果被多处复用而分配存储的中间值，不是 RTL 状态。实验中
有四个累计节点 B/S8/SB/SBV，但真正的相邻增量优化是三项：

| 文档 | 一句话摘要 | 直接配对的结果 |
|---|---|---|
| [012 S8：按字段和类型分区的 state storage](012_s8_typed_state.md) | 为不同 scalar kind/width 分配类型敏感的 state slot 和 struct 字段 | 48,023.50 → 44,595.25 ms，+7.138693% |
| [013 SB：persistent native bool](013_sb_native_bool.md) | 持久化 bool 不再走通用字节/打包表示，直接存 native `bool` | 44,760.25 → 44,195.25 ms，+1.262281% |
| [014 SBV：materialized kBool native bool](014_sbv_native_bool.md) | materialized value bucket 中的 kBool 也直接使用 native `bool` | 44,198.00 → 43,373.50 ms，+1.865469% |

B → SBV 的节点配对是 48,054.25 → 43,335.50 ms（+9.819631%）；主线落地后的 native 复测为 48,162.50 → 43,434.50 ms（+9.816766%）。[^typed]

## 没有合入的探索结果

记录“探索过但没有进入主线”同样重要：

* 早期 targeted-table/direct 候选的收益低于 1%，没有稳定超过噪声门槛；没有形成主线提交。
* targeted-direct gap-pack 依赖审计后，C/D 相对 exact-event 只得到 +0.155120%，且会把不相关的开关耦合到一起，因此保持关闭。[^exact]
* RWA 的 F（MemoryFill tier）重复结果约 +0.16%～+0.24%，跨顺序不稳定，未合入。
* residual MemoryRead 与 physical zero-tail 的复测跨过零且不到 1%，未合入；常量 MemoryRead（007）是另一条有明确结构证明的优化，不能混为一谈。[^four]
* HS 是更早的事件表示路线；TRBS 已经替代它，hot-event remap 本身近似中性（约 -0.009%），不能把 HS 再机械叠加到 TRBS 上。[^trbs]

## 代码生成术语速查

* **byte arena / typed storage / slot**：byte arena 是一整块没有元素类型的原始字节
  存储；typed storage 使用 `bool`、枚举或整数等明确类型的字段/数组。slot 是生成器
  给其中一个值分配的内部编号位置，不是外部端口号。
* **persistent state / materialized value**：前者真正保存 RTL 寄存器或锁存器的状态，
  后者只是为了复用而保存的组合中间结果。**owning storage** 指真正拥有这些值的字段
  或数组，而不是临时引用或访问表达式。
* **scalar / word / bucket**：scalar 是能由一个 C++ 标量表示的值；宽位向量拆成一个
  或多个通常为 64 bit 的 word。bucket 是按类型或 word 数把同类值归组的存储类别。
* **SystemTask / DPI-C / `xs_assert_v2`**：SystemTask 是 HDL 中 `$display`、`$fatal`
  等具有副作用的系统任务；DPI-C 是 SystemVerilog 调用 C/C++ 函数的接口；
  `xs_assert_v2` 是 XiangShan 用于报告断言的特定 DPI-C 函数。
* **OOB / fallback**：OOB 是 out of bounds，即索引或移位量越界。fallback 是这些少见
  情况采用的保守结果路径；把它标冷不等于删除越界语义。
* **hot/cold layout、`unlikely`、always-inline**：`unlikely` 只给编译器分支概率提示，
  便于把低频代码移出高频直线路径；always-inline 强烈要求把小 helper 函数体展开到
  调用点。两者都不改变硬件语义，实际机器码仍由 C++ 编译器决定。
* **alias analysis（别名分析）**：编译器判断两个内存访问是否可能指向同一位置的分析。
  更明确的对象和类型有机会减少保守依赖，但文中的别名、布局和寄存器驻留解释都是
  根据源码形态与 PMU 提出的原因假说，不替代端到端 walltime 证据。

## 设计边界与可复现性

这些改动依据生成器能够证明的事件形状、类型和控制流属性选择候选，不匹配 SimTop
变量名、特定 workload 名字或硬编码的 `ValueId` 编号，也不在 SimTop wrapper 中单独
打开开关。emitter 仍会把 `ValueId` 正常用作图中值的通用内部身份。Wolvrix 的
C++/Python 流程继承生成器的 generic default；SimpleTES 后续研究也以合入后的 generic
default 作为 baseline。相关默认值、功能回归和源码指纹见各阶段的 landing 文档。
[^rwa][^four][^trbs][^typed]

SimpleTES 实例会固定使用启动时的代码提交；修改本目录不会改变已经启动实例的
executable pin。若要让未来实例从最新主线开始，需要在启动新轮次时显式更新 baseline
commit。

## 最近的仿真二进制示例

作为体量参考，最近一份 typed-state 消融目录中的优化 candidate emu 为
`build/grhsim_typed_state_landing_20260813/arms/full_native_bool_values/emu`：文件时间
为 `2026-08-13 03:49:23 +0800`，大小 `83,705,920` bytes（约 `79.83 MiB`），是
`x86-64 ELF` 可执行文件，SHA-256 为
`7eed38e8e005e6a99f81e455265b3227036d8cd121fb71f3724c5df65622873f`。这是用于
typed-state 消融的 default-path candidate，provenance 中的 parent/Wolvrix pin 和
artifact 哈希可由 TNO0230 复核；它不是本次文档整理重新构建的产物。[^binary]

## 来源说明

正文中的脚注链接到 `pdocs/grhsim_opt_thj` 中的实验记录；这些记录包含原始 control/candidate walltime、ABBA/BAAB、门禁判断、功能回归和落地提交。源代码层面的提交顺序由 Wolvrix 子模块的 Git 历史核对。

[^history]: [TNO0156：SimpleTES bench 启动、首次基线与研究范围](../grhsim_opt_thj/TNO0156_simpletes_auto_research_bench_and_launch_gate_20260720.md)；提交顺序由 `git log --follow -- lib/emit/grhsim_cpp.cpp` 核对，提交全文分别为 `8f6ba14397b0c3d00cb909153af1c6464f4f1ed9`、`16a9f493687a21a5428f1e1327a69834ea60c9f5`、`fd12d83f5150cc98540ed3e8f2af3b79f8054da0`、`d3ed9dea975bddf01185dde5c548a69241a09de9`、`79ec2037b00f2d4894d72785277ebe3f5d37782d`。
[^exact]: [TNO0173：exact-event 单变量归因](../grhsim_opt_thj/TNO0173_gen20_gen24_fresh_cold_guard_hint_ablation_result_20260724.md)、[TNO0174：targeted-direct 依赖审计](../grhsim_opt_thj/TNO0174_gen24_targeted_direct_dependency_audit_and_landing_plan_20260725.md)、[TNO0176：exact-event 四臂正式结果](../grhsim_opt_thj/TNO0176_gen24_four_arm_function_formal_walltime_and_default_decision_20260725.md)、[TNO0179：落地后的 native canary](../grhsim_opt_thj/TNO0179_simpletes_v2_pinned_native_control_canary_and_continuation_ready_20260725.md)。
[^rwa]: [TNO0183：R/W/A 直接消融](../grhsim_opt_thj/TNO0183_simpletes_v2_direct_ablation_final_attribution_and_retention_decision_20260727.md)、[TNO0185：F 重测与 RWA 端点](../grhsim_opt_thj/TNO0185_simpletes_v2_f_repeat_and_rwa_endpoint_decision_20260727.md)、[TNO0188：RWA native 50k 与默认决策](../grhsim_opt_thj/TNO0188_rwa_landing_native_50k_performance_and_default_decision_20260727.md)。
[^four]: [TNO0205：四项正收益消融](../grhsim_opt_thj/TNO0205_simpletes_extended_bestpath_direct_ablation_result_20260731.md)、[TNO0206：RWA→gen150 端点复现](../grhsim_opt_thj/TNO0206_simpletes_rwa_to_gen150_endpoint_replication_20260731.md)、[TNO0207：四项落地与回归](../grhsim_opt_thj/TNO0207_four_positive_wolvrix_landing_and_regression_20260731.md)、[TNO0208：四项 repin 后 native 50k](../grhsim_opt_thj/TNO0208_four_positive_simpletes_repin_and_native_50k_20260731.md)。
[^trbs]: [TNO0213：TRBS 最优路径直接消融](../grhsim_opt_thj/TNO0213_hot_event_bestpath_direct_ablation_result_20260801.md)、[TNO0214：原则化 TRBS 门禁落地](../grhsim_opt_thj/TNO0214_principled_hot_event_landing_and_native_gate_20260801.md)、[TNO0215：TRBS repin 与继续研究](../grhsim_opt_thj/TNO0215_principled_hot_event_simpletes_repin_and_continuation_readiness_20260801.md)。
[^typed]: [TNO0229：typed-state 节点消融](../grhsim_opt_thj/TNO0229_typed_state_bestpath_ablation_node032_runtime_completion_20260813.md)、[TNO0230：typed-state 落地、回归与默认值](../grhsim_opt_thj/TNO0230_typed_state_wolvrix_landing_and_regression_20260813.md)。
[^binary]: [`TNO0230`：typed-state landing artifact 与 SHA-256](../grhsim_opt_thj/TNO0230_typed_state_wolvrix_landing_and_regression_20260813.md)，其中记录 `full_native_bool_values/emu` 的 `83,705,920` bytes、candidate provenance 和 binary identity。
