# 003. W：singleton MemoryWrite 的冷分支提示

W 是 RWA 链的第二项增量，合入 `16a9f493687a21a5428f1e1327a69834ea60c9f5`。
RWA 是本阶段三个增量的简称：R 为 register-write run 筛选，W 为本篇的 MemoryWrite
提示，A 为 assertion 相关的外层 guard。W 建立在 R-selected runs 上：R 先决定哪些
run 值得做 cold layout，W 再在这些 run 内处理 MemoryWrite guard。因此准确的依赖
方向是“W 依赖 R”，而不是 R 依赖 W。[^design][^landing]

## 先理解本篇术语

GrhSIM 把同一个 supernode（由若干 IR，即中间表示操作组成的调度单元）中连续出现、
且共享同一精确事件条件的一段写操作称为 **run**。**guard** 是决定一次写入是否执行
的布尔条件；拥有相同 guard 的写操作组成一个 guard group，group 中只有一个写操作时称为
**singleton**。singleton 在这里不表示单 bit、单字节或全设计唯一的存储端口。

`MemoryWritePort` 是 Wolvrix IR 中表示一次存储器写入的操作种类。`unlikely(cond)`
只是向编译器提供 `cond` 通常为假的分支概率提示，让它有机会把低频代码放到热路径
之外；条件仍会正常求值，写地址、写数据和写入顺序均不改变。

## 做了什么

### 先看总结

W 不会自行挑选新的 run；它先复用 R 的准入结果，再把这些 run 里恰好只有一次
MemoryWrite 的候选 guard 标成 `unlikely`。MemoryWrite 仍按原地址、数据、条件和
顺序执行，W 改变的只是生成 C++ 时提供给编译器的分支布局提示。

| 层面 | 旧生成形式 | 新生成形式 | 目的 / 边界 |
|---|---|---|---|
| 适用范围 | R-selected run 中的 MemoryWrite guard 仍是普通条件 | 仅在 R 已选中的 run 内继续筛选 MemoryWrite | 复用 R 的通用结构门禁；W 不会单独让一个 run 获得准入 |
| singleton 写入 | `if (cond)` 中执行一项 `MemoryWritePort` | `if (unlikely(cond))` 中执行同一项写入 | 让编译器可将低概率写入代码移出热路径；地址、数据和写入顺序不变 |
| 保守回退 | 所有不属于 R 提示范围的 MemoryWrite 保持普通生成 | 只有恰好一项 MemoryWrite、且 guard 不是静态已知非零常量时加提示 | 多项共享同一 guard、未被 R 选中的 run 或不合格 guard 均维持旧形式 |

**只需记住：W 是 R 之后的附加提示，而不是独立的 run selector。在 R 基础上加入 W
后，合并两种运行顺序的 SimTop 50k walltime 为 `57,031.25→55,965.00 ms`，减少
`1,066.25 ms`、改善 `1.869589%`。**[^ablation]

### 实现与边界

R 的 admission（静态准入判断）只统计 eligible register-write groups：当 singleton
register guard 达到 `256`，或 eligible register writes 总数达到 `2048` 时，run 才被
选中。MemoryWrite 本身不参与这项计数。对于已经由 R 选中的 run，W 再识别恰好只含
一个 `MemoryWritePort` 的 guard group，并把其 guard 标为 `unlikely`；静态已知为非零
的常量 guard 不处理，共享同一 guard 的多个 memory writes 也不作为 singleton 处理。
[^design][^source]

W 不改变 R 的 admission threshold，也不改变 MemoryWrite 的地址、数据、写入顺序或
条件判断。不属于 R-selected run 的 MemoryWrite，以及同一 group 内有多项写入的
MemoryWrite，仍使用原来的生成形式。[^source]

## 为什么这样做

MemoryWrite 的 singleton guard 在这个被 R 选中的结构里预期是低概率分支。让编译器
知道这一点，可把写入慢路径移出高频直线路径，并减少 CPU 前端的取指和解码受低概率
代码干扰。W 刻意复用 R 的通用结构门禁，不匹配 SimTop 的端口或变量名；它依赖 R，
也不是 `targeted-direct`（另一个 activity-bitmap gap-pack 实验开关）的别名。[^design]

## 收益（SimTop 50k walltime）

这是 direct `R→RW` 配对：control `R` 已含前一篇的 register 优化，candidate `RW`
在完全相同的基础上再增加 W；direct 表示两侧只相差 W。ABBA 表示按
control-candidate-candidate-control 运行，BAAB 是反向顺序，pooled 值合并两种顺序
的有效样本后分别取均值。SimTop 运行到 50k cycle，绝对值取日志中的
`Host time spent` walltime：[^ablation]

| 对比 | control（ms） | candidate（ms） | 减少（ms） | 相对改善 | ABBA / BAAB |
|---|---:|---:|---:|---:|---:|
| `R→RW` | 57,031.25 | 55,965.00 | 1,066.25 | **1.869589%** | 1.521228% / 2.220306% |

这一项的 **order gap**（ABBA 与 BAAB 所得改善率之差）为 `0.699078 pp`，其中 pp
表示百分点。TNO0183 当时按预注册的“双 order 同向、pooled 改善超过 control-spread
信任线”流程接受该结果；control spread 是 control 样本极差相对其均值的比例。这个
gap 高于后来其他消融阶段采用的 `0.25 pp` 复测线，因此不应事后把它描述成满足新
复测线。PMU（CPU 硬件性能计数器）cycles `-1.966156%`、frontend no-op
`-2.111833%`、retired instructions `+0.000600%`，说明指令数基本不变而周期和前端
空槽下降，支持“主要是代码布局/前端供给”的解释。[^ablation]

作为组合背景，exact-event baseline 到 RW（不含 A）的 pooled 结果为
`60,513.50→55,394.00 ms`，减少 `5,119.50 ms`、改善 `8.460096%`；这个数字不能
和 R→RW 的 1.869589% 相加。[^ablation]

## 落地状态与边界

W 随 R/A 在 `16a9f493...` 合入通用 emitter 并默认启用，Python 继承 C++ 默认；没有
SimTop 专门选项。emitter 是把 Wolvrix IR 和 schedule 生成 C++ 仿真源码的代码生成器。
W 必须在 R-selected 上下文中才有意义，单独打开而没有 R 的组合没有被本轮性能数据
验证。[^landing]

### 数据来源（尾注）

[^design]: [`TNO0183`：RWA 分层和 W 的机制定义](../grhsim_opt_thj/TNO0183_simpletes_v2_direct_ablation_final_attribution_and_retention_decision_20260727.md)。
[^ablation]: [`TNO0183`：R→RW direct pair、组合背景和 PMU](../grhsim_opt_thj/TNO0183_simpletes_v2_direct_ablation_final_attribution_and_retention_decision_20260727.md)。
[^landing]: [`TNO0186`：RWA landing implementation/provenance](../grhsim_opt_thj/TNO0186_rwa_wolvrix_landing_implementation_and_provenance_20260727.md) 与 [`TNO0188`：native 50k/default](../grhsim_opt_thj/TNO0188_rwa_landing_native_50k_performance_and_default_decision_20260727.md)。
[^source]: Wolvrix `16a9f493...` 的 `lib/emit/grhsim_cpp.cpp` 中 R-selected MemoryWrite singleton emission；可用 `git show 16a9f493687a21a5428f1e1327a69834ea60c9f5 -- lib/emit/grhsim_cpp.cpp` 复核。
