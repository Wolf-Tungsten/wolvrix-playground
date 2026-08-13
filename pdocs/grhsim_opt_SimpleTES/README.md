# SimpleTES 已合入 Wolvrix 主线的优化

本目录按时间顺序记录了 **SimpleTES 首次建立研究基线之后，真正合入 Wolvrix 集成主线** 的 GrhSIM 优化。这里的“主线”指当前工作使用的 Wolvrix 集成分支（`thj/gsim-calibrate-2`），而不是声称这些提交已经进入远端 `origin/main`。目标不是罗列 patch 名称，而是说明每个改动解决了什么问题、为什么可能有效，以及在 SimTop 50k 上到底带来了多大 walltime 变化。

## 怎么读这些数字

文中“收益”统一指 SimTop 50k 的 `Host time spent`（walltime）。给定同一轮实验中的 control 和 candidate，计算方式是：

`相对收益 = (control walltime - candidate walltime) / control walltime`。

因此正数表示 candidate 更快；“绝对收益”是两者相差的毫秒数。每一行数字只在它自己的配对实验基线内成立，不能把不同轮次的百分比直接相加。ABBA/BAAB 是交错顺序的两组复测；文中同时给出它们，是为了让读者看到缓存和运行顺序造成的波动。除非另有说明，所有结果都来自已有 TNO 文档，本次没有重新运行性能测试。

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
| [001 exact-event 组合策略](001_exact_event.md) | 只有存在相关事件时才继续提交检查，并把重复谓词、标量 next 值和冷分支布局整理到一起 | 74,773.25 → 61,284.00 ms，减少 13,489.25 ms，+18.040208% |

这一阶段使用的是 `commit_exact_event_policy`。早期候选曾借用 `active_mask_gap_pack_policy=targeted-direct`，但依赖审计证明两者没有逻辑或数据依赖；主线版本已经解耦，gap-pack 仍保持关闭。[^exact]

### 第二阶段：RWA

| 文档 | 一句话摘要 | 直接配对的结果 |
|---|---|---|
| [002 R：寄存器冷布局](002_r_register_cold_layout.md) | 对满足结构条件的寄存器写 guard 才采用冷分支布局 | 61,505.75 → 57,466.50 ms，+6.567272% |
| [003 W：MemoryWrite singleton hint](003_w_memorywrite_hint.md) | 在 R 已选中的运行中，把 singleton MemoryWrite guard 标为 `unlikely` | 57,031.25 → 55,965.00 ms，+1.869589% |
| [004 A：成对 assertion 外层 guard](004_a_assertion_guard.md) | 对相邻、同条件且无可观察输出的 SystemTask/assertion 对做外层冷门保护 | 55,485.00 → 54,050.50 ms，+2.585383% |

R、W、A 是有先后依赖的增量，不是三个可以在同一 baseline 上横向相加的独立百分比。最终 RWA 端点在另一轮 native 复测中为 60,881.50 → 54,088.00 ms（+11.158562%）。[^rwa]

### 第三阶段：四个正收益热路径改动

下列四篇使用 `final-minus-one` 消融：每项都从已经包含其余改动的 full-gen150 版本退掉一项。因此它们是“在当时完整组合上该项的边际贡献”，而不是从最初 baseline 独立重建的收益。

| 文档 | 一句话摘要 | 直接配对的结果 |
|---|---|---|
| [005 冷 SystemTask/assertion hints](005_cold_systemtask_assert_hints.md) | 扩大通用的无返回/无输出冷门分支提示覆盖 | 52,365.25 → 51,693.75 ms，+1.282339% |
| [006 hot word helpers always-inline](006_always_inline_helpers.md) | 给选定的高频 word helper 加统一的 always-inline 提示 | 52,032.75 → 51,645.75 ms，+0.743762% |
| [007 常量 MemoryRead](007_constant_memoryread.md) | 能证明行号恒定时直接加载常量行，并删掉不可能触发的 OOB 清理 | 51,964.75 → 51,585.00 ms，+0.730784% |
| [008 动态 shift/index OOB hints](008_dynamic_oob_hints.md) | 只把越界 fallback 标为 `unlikely`，不改变正常路径语义 | 51,778.50 → 51,652.75 ms，+0.242861% |

四项全部启用后的 native 端点（RWA → four-positive）是 53,749.25 → 51,575.00 ms，减少 2,174.25 ms、+4.045173%。[^four]

### 第四阶段：TRBS 热事件表示

TRBS 面向的是**结构上很热的输入事件边**，不是 persistent logic state。三篇分别记录同一条 T→TR→TRB→TRBS 链上的三个增量：

| 文档 | 一句话摘要 | 直接配对的结果 |
|---|---|---|
| [009 TR：typed event storage](009_trbs_event_storage.md) | 用 typed event-edge 存储替代 byte arena，并选择可复用的热点事件槽 | 51,333.75 → 49,923.00 ms，+2.748192% |
| [010 TRB：decoded exact-posedge bool](010_trbs_posedge_decode.md) | 为精确 posedge 事件预解码一个 bool，避免热路径反复解释 enum | 50,024.75 → 48,474.75 ms，+3.098466% |
| [011 TRBS：batch-local bool snapshot](011_trbs_batch_snapshot.md) | 在 schedule batch 内把稳定的热点 bool 保存为局部快照 | 48,449.75 → 47,495.50 ms，+1.969566% |

整条链 B → TRBS 的配对结果为 51,562.00 → 47,632.25 ms（+7.621407%）。后来把“原始 slot 数量门槛”改成按 posedge 使用次数和覆盖 batch 数计算的原则化门禁，结果 47,567.25 → 47,597.00 ms（-0.062543%，在噪声范围内），所以它是可维护性修正，不应被当作额外性能收益。[^trbs]

### 第五阶段：typed-state

typed-state 处理的是**持久化逻辑状态和值桶**，与 TRBS 的事件边生命周期不同。实验中有四个节点 B/S8/SB/SBV，但真正的增量优化是三项：

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

## 设计边界与可复现性

这些改动依据生成器能够证明的事件形状、类型和控制流属性选择候选，不读取 SimTop 变量名、ValueId 或特定 workload 的名字，也不在 SimTop wrapper 中单独打开开关。Wolvrix 的 C++/Python 流程继承生成器的 generic default；SimpleTES 后续研究也以合入后的 generic default 作为 baseline。相关默认值、功能回归和源码指纹见各阶段的 landing 文档。[^rwa][^four][^trbs][^typed]

当前继续运行的 SimpleTES 实例仍固定在启动时的代码提交；本目录只增加说明文档，不改动其 executable pin。若要让未来实例从最新主线开始，应在启动新轮次时显式更新 baseline commit。

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
