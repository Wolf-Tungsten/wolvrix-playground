# 004. A：SystemTask/assertion 成对外层 cold guard

A 是 RWA 链的第三项增量，和 R、W 一起合入 Wolvrix 提交
`16a9f493687a21a5428f1e1327a69834ea60c9f5`。它不是“关闭 assertion”，而是只重排
一个可以证明无额外可观察结果的相邻代码对。[^design][^landing]

## 做了什么

当相邻的 `SystemTask` 与 `xs_assert_v2` 满足以下结构条件时，emitter 在它们外面加
一个 `unlikely` guard：两者使用同一条件/同一事件，assertion 无 return/output，且
内部 DPIC/SystemTask 条件仍保持原样。若任一证明不成立，保持旧的逐条生成；因此
不会改变 assertion 的触发语义、SystemTask 顺序或 DPIC 可观察行为。[^source]

## 为什么这样做

这类检查通常是调试/保护路径，正常仿真中很少触发，但逐条放在热 schedule 中会让
编译器把保护逻辑和主计算混在一起。外层 cold guard 让两条相关路径共享一次判断，
同时把正常路径保持紧凑。门禁依赖相邻结构和副作用证明，而不是 SimTop 的名字或
固定 workload。[^design]

## 收益（SimTop 50k walltime）

在已经包含 R、W 的 RWF baseline 上，A 的 direct `RWF→RWFA` 配对为：[^ablation]

| 对比 | control（ms） | candidate（ms） | 减少（ms） | 相对改善 | ABBA / BAAB |
|---|---:|---:|---:|---:|---:|
| `RWF→RWFA` | 55,485.00 | 54,050.50 | 1,434.50 | **2.585383%** | 2.380091% / 2.789407% |

为了与实际默认组合对照，no-F 的 B→RWA pooled 为
`60,583.50→53,992.75 ms`，减少 `6,590.75 ms`、改善 `10.878787%`；随后 native
landing 复测的完整 RWA endpoint 为 `60,881.50→54,088.00 ms`，改善
`11.158562%`。这些是不同 baseline 的端点，不应当当作 A 单项数字相加。[^landing]

## 落地状态与边界

A 与 R/W 同提交进入通用 C++ emitter 默认路径，Python 流程继承；没有为 SimTop 单独
开启。后续四项热路径中的 #005 是更通用的 standalone assertion/SystemTask hint，
它扩展覆盖面但不等同于本篇严格的“成对外层 guard”。[^landing][^later]

### 数据来源（尾注）

[^design]: [`TNO0183`：A 的结构定义和 direct ablation 设计](../grhsim_opt_thj/TNO0183_simpletes_v2_direct_ablation_final_attribution_and_retention_decision_20260727.md)。
[^ablation]: [`TNO0183`：RWF→RWFA 绝对 walltime、ABBA/BAAB 和 PMU](../grhsim_opt_thj/TNO0183_simpletes_v2_direct_ablation_final_attribution_and_retention_decision_20260727.md)。
[^landing]: [`TNO0185`：RWA endpoint/f-repeat](../grhsim_opt_thj/TNO0185_simpletes_v2_f_repeat_and_rwa_endpoint_decision_20260727.md) 与 [`TNO0188`：native landing/default](../grhsim_opt_thj/TNO0188_rwa_landing_native_50k_performance_and_default_decision_20260727.md)。
[^later]: [README 总目录](README.md)中的“四个正收益热路径”阶段及 [005](005_cold_systemtask_assert_hints.md)。
[^source]: Wolvrix `16a9f493...` 的 `lib/emit/grhsim_cpp.cpp` 中 assertion/SystemTask nested guard；可用 `git show 16a9f493687a21a5428f1e1327a69834ea60c9f5 -- lib/emit/grhsim_cpp.cpp` 复核。
