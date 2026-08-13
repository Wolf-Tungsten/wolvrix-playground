# 003. W：singleton MemoryWrite 的冷分支提示

W 是 RWA 链的第二项增量，合入 `16a9f493687a21a5428f1e1327a69834ea60c9f5`。
它建立在 [002](002_r_register_cold_layout.md) 的 R-selected runs 上：R 先决定
哪些 run 值得重排，W 再在这些 run 内处理 MemoryWrite guard。[^design][^landing]

## 做了什么

对于 R 已选中的 run，生成器识别 singleton `MemoryWritePort` 条件，并只把其 guard
标为 `unlikely`。W 不改变 R 的 admission threshold，也不改变 MemoryWrite 的地址、
数据、写入顺序或条件判断；不属于 R-selected run 的 MemoryWrite 仍使用原来的生成
形式。[^source]

## 为什么这样做

MemoryWrite 的 singleton guard 通常是大量提交条件中的冷分支。让编译器知道这一点，
可把写入慢路径移出热代码，并减少热前端被低概率分支打断的机会。W 刻意复用 R 的
结构门禁，避免另起一个只针对某个模型的启发式；因此它是 R 的依赖项，而不是
`targeted-direct` 的别名。[^design]

## 收益（SimTop 50k walltime）

在 R baseline 上的 direct `R→RW` 配对为：[^ablation]

| 对比 | control（ms） | candidate（ms） | 减少（ms） | 相对改善 | ABBA / BAAB |
|---|---:|---:|---:|---:|---:|
| `R→RW` | 57,031.25 | 55,965.00 | 1,066.25 | **1.869589%** | 1.521228% / 2.220306% |

这一项的 order gap 为 `0.699078 pp`。TNO0183 当时按预注册的“双 order 同向、
pooled 超过 control-spread 信任线”流程接受该结果；这个 gap 高于后来其他消融阶段
采用的 `0.25 pp` 复测线，因此不应事后把它描述成满足新复测线。PMU cycles
`-1.966156%`、frontend `-2.111833%`、instructions `+0.000600%`，支持“主要是
代码布局/前端供给”的解释。[^ablation]

作为组合背景，exact-event baseline 到 RW（不含 A）的 pooled 结果为
`60,513.50→55,394.00 ms`，减少 `5,119.50 ms`、改善 `8.460096%`；这个数字不能
和 R→RW 的 1.869589% 相加。[^ablation]

## 落地状态与边界

W 随 R/A 在 `16a9f493...` 合入通用 emitter 并默认启用，Python 继承 C++ 默认；没有
SimTop 专门选项。它必须在 R-selected 上下文中才有意义，单独打开而没有 R 的组合
没有被本轮性能数据验证。[^landing]

### 数据来源（尾注）

[^design]: [`TNO0183`：RWA 分层和 W 的机制定义](../grhsim_opt_thj/TNO0183_simpletes_v2_direct_ablation_final_attribution_and_retention_decision_20260727.md)。
[^ablation]: [`TNO0183`：R→RW direct pair、组合背景和 PMU](../grhsim_opt_thj/TNO0183_simpletes_v2_direct_ablation_final_attribution_and_retention_decision_20260727.md)。
[^landing]: [`TNO0186`：RWA landing implementation/provenance](../grhsim_opt_thj/TNO0186_rwa_wolvrix_landing_implementation_and_provenance_20260727.md) 与 [`TNO0188`：native 50k/default](../grhsim_opt_thj/TNO0188_rwa_landing_native_50k_performance_and_default_decision_20260727.md)。
[^source]: Wolvrix `16a9f493...` 的 `lib/emit/grhsim_cpp.cpp` 中 R-selected MemoryWrite singleton emission；可用 `git show 16a9f493687a21a5428f1e1327a69834ea60c9f5 -- lib/emit/grhsim_cpp.cpp` 复核。
