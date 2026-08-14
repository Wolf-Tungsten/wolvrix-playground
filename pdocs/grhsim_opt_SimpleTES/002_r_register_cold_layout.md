# 002. R：寄存器写入的结构化 cold-layout

R 是 exact-event 主线之后 RWA 路线的第一项增量，合入提交
`16a9f493687a21a5428f1e1327a69834ea60c9f5`。它建立在 001 的 exact-event
continuation（一次 compute/commit 轮次结束后是否继续下一轮的判断）上；没有
exact-event 时，R 的 selector（静态候选筛选器）不会形成同样的候选集合。RWA
是这轮探索中三个增量的简称：R 为本篇的 register-write 筛选，W 为后续的
MemoryWrite 提示，A 为 assertion 相关的外层 guard。[^design][^landing]

## 先理解本篇术语

GrhSIM 把同一个 supernode（由若干 IR，即中间表示操作组成的调度单元）中连续出现、
且共享同一精确事件表达式的一段写操作称为 **exact-event run**。精确事件表达式表示
生成器能明确写出触发该段操作的 posedge、negedge 或任意边沿条件。

run 内拥有相同写入条件的操作组成一个 **guard group**；guard 就是决定本次写入是否
执行的布尔条件。若一个 group 只有一项写操作，它就是 **singleton guard**。本篇的
**admission** 是生成 C++ 之前的静态准入判断：只有整段 run 中符合条件的寄存器写
达到阈值，才会对该 run 应用 cold-layout 提示。`unlikely(cond)` 只是告诉编译器
`cond` 通常为假，以便把低频代码移出高频直线路径；它不改变条件和写入语义。

## 做了什么

### 先看总结

R 不会少执行寄存器写入，而是扩大 `unlikely` 冷分支提示的适用范围。生成器仍先按
exact-event run 的结构做静态筛选；只有一段 run 中出现足够多的合格寄存器写，才把
其中符合条件的 guard 标成冷分支，未入选的代码继续使用原来的普通条件。

| 层面 | 旧生成形式 | 新生成形式 | 目的 / 边界 |
|---|---|---|---|
| run 准入 | 只覆盖至少 `1024` 个 singleton register-write guard 的大 run | singleton 门槛降到 `256`；或者 eligible register writes 总数达到 `2048` 也准入 | 把同一布局原则扩展到更多有足够规模的 run；MemoryWrite 不参与这里的计数 |
| guard 生成 | 未达到旧门槛时使用普通 `if (cond)` | run 准入后，合格的 register-write guard 使用 `if (unlikely(cond))` | 只给编译器冷热布局提示，不改变 `cond` 的求值或寄存器写入 |
| 保守限制 | 不满足旧大 run 条件时保持通用路径 | 恒真或静态已知非零的 guard 被排除；单个共享 guard group 最多 `2048` 项 | 避免把必经路径标冷或让一个过大的共享 group 进入；未通过时仍生成旧形式 |

**只需记住：R 把 001 已验证的 register-write cold-layout 从超大 singleton run
推广到更多经过结构筛选的 run。在已含 001 exact-event 的基线上加入 R 后，合并两种
运行顺序的 SimTop 50k walltime 为 `61,505.75→57,466.50 ms`，减少 `4,039.25 ms`、
改善 `6.567272%`。**[^ablation]

### 实现与边界

生成器先对 exact-event register-write run 做结构化 admission：singleton register
guard 的数量门槛从 `1024` 放宽到 `256`；即使 singleton 不足 `256`，当所有 eligible
register writes 的总数达到 `2048` 时也允许进入。eligible group 必须非空、不是恒真
guard、全部操作都是 `RegisterWritePort`，并且**单个共享 guard 的 group**最多包含
`2048` 项。这里的 `2048` 上限不限制整个 run 的长度。静态已知为非零的常量 guard
也被排除，因为把必定进入的分支标成冷分支明显不合理。[^design][^source]

run 通过 admission 后，生成器才把上述 eligible register-write guard 写成
`unlikely` cold branch；没有通过的 run，以及 run 内不符合条件的 group，仍保持原来的
普通条件。`RegisterWritePort` 是 Wolvrix IR 中表示一次寄存器提交写入的操作种类。
[^source]

这项改动只改变满足证明的寄存器写路径的代码布局，不删除寄存器写入、不改变 next/init
表达式（下一个值及初始值），也不按 SimTop 端口或变量名选择。R 的“R”是
register-write admission，不是一个独立的运行时开关名称。[^landing]

## 为什么这样做

前一阶段的单变量实验已证明，大块 singleton register guard 的冷分支提示可以改善
CPU 前端的代码供给。R 的目标是
把同样的原则扩展到较小、但仍有足够结构收益的寄存器 run，同时用上限和恒真排除避免
在过大的共享 guard group 或本来必定执行的路径上误标。由于条件语义不变，收益预期
来自编译器的 hot/cold block placement（冷热基本块布局）、分支预测和取指局部性；
这是一种由生成代码与 PMU 支持的解释，最终裁决仍只看端到端 walltime。[^ablation]

## 收益（SimTop 50k walltime）

这是在已经默认启用 exact-event 的 baseline 上构造的 direct `B→R` 配对。`B` 是不含
本篇 refinement 的基线，`R` 是只增加本篇机制的候选；direct 表示两侧只相差当前被测
机制，并不是“direct code generation”。每个 ABBA 顺序按
control-candidate-candidate-control 运行，BAAB 反向运行；pooled 数值合并两种顺序的
有效样本后分别取均值。绝对数值取 SimTop 50k 日志中的 `Host time spent` 毫秒：
[^ablation]

| 对比 | control（ms） | candidate（ms） | 减少（ms） | 相对改善 | ABBA / BAAB |
|---|---:|---:|---:|---:|---:|
| `B→R` | 61,505.75 | 57,466.50 | 4,039.25 | **6.567272%** | 6.722023% / 6.411125% |

配对的 PMU（CPU 硬件性能计数器）变化为 cycles `-6.687843%`、frontend no-ops
`-7.435799%`，retired instructions `+0.034669%`；执行的指令数没有明显减少，而周期和
前端空槽一起下降，这与“布局/前端收益而非删除大量动态工作”的解释一致。[^ablation]

RWA 链的最终落地回归（不是 R 单项的可加值）为落地前的 `B` baseline
`60,881.50 ms` → `54,088.00 ms`，减少 `6,793.50 ms`、改善 `11.158562%`，
ABBA/BAAB 分别 `11.135149%`/`11.182077%`。[^landing]

## 落地状态与边界

R 与 W、A 在同一 Wolvrix 提交中合入，通用 C++/Python 流程默认启用；没有给 SimTop
另设开关，也不依赖 `targeted-direct`（另一个 activity-bitmap gap-pack 实验开关）。
后续如果只撤回 R，必须重新生成并通过功能及 50k gate；gate 指功能正确性和正式
walltime 都必须满足的验收条件。本历史数据不把“只撤回 R、保留 W/A”当作已测组合。
[^landing]

### 数据来源（尾注）

[^design]: [`TNO0183`：R/W/A direct ablation 设计与阶段定义](../grhsim_opt_thj/TNO0183_simpletes_v2_direct_ablation_final_attribution_and_retention_decision_20260727.md)。
[^ablation]: [`TNO0183`：R 直接配对及 PMU 结果](../grhsim_opt_thj/TNO0183_simpletes_v2_direct_ablation_final_attribution_and_retention_decision_20260727.md)，含 control/candidate、ABBA/BAAB 和 spread gate。
[^landing]: [`TNO0188`：RWA Wolvrix landing、native 50k 与 generic default](../grhsim_opt_thj/TNO0188_rwa_landing_native_50k_performance_and_default_decision_20260727.md)；落地实现细节见 [`TNO0186`](../grhsim_opt_thj/TNO0186_rwa_wolvrix_landing_implementation_and_provenance_20260727.md)。
[^source]: Wolvrix `16a9f493...` 的 `lib/emit/grhsim_cpp.cpp`（R 的 admission、threshold 和 cold emitter）；可用 `git show 16a9f493687a21a5428f1e1327a69834ea60c9f5 -- lib/emit/grhsim_cpp.cpp` 复核。
