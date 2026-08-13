# 002. R：寄存器写入的结构化 cold-layout

R 是 exact-event 主线之后 RWA 路线的第一项增量，合入提交
`16a9f493687a21a5428f1e1327a69834ea60c9f5`。它建立在 001 的 exact-event
continuation 上；没有 exact-event 时，R 的 selector 不会形成同样的候选集合。[^design][^landing]

## 做了什么

生成器先对 exact-event 中的 register-write run 做结构化 admission：singleton
register guard 的数量门槛从 `1024` 放宽到 `256`，或者当 eligible register writes
达到 `2048` 时允许进入；同时要求 run 不超过 `2048`，并排除已知恒真的 guard。通过
门禁的 run 才把寄存器写条件布局成 cold branch（`unlikely`），未通过的 run 保持
原来的普通条件。[^design][^source]

这项改动只改变满足证明的寄存器写路径的代码布局，不删除寄存器写入、不改变 next/init
表达式，也不按 SimTop 端口或变量名选择。R 的“R”是 register-write admission，
不是一个独立的运行时开关名称。[^landing]

## 为什么这样做

001 已证明大块 singleton register guard 的冷分支提示可以改善前端布局。R 的目标是
把同样的原则扩展到较小、但仍有足够结构收益的寄存器 run，同时用上限和恒真排除避免
在小样本或本来就热的路径上误标。由于条件语义不变，收益预期来自编译器的 hot/cold
block placement、分支预测和取指局部性；这是一种基于生成代码形态的解释，最终裁决仍
只看端到端 walltime。[^ablation]

## 收益（SimTop 50k walltime）

这是在 exact-event baseline 上逐步构造的 direct `B→R` 配对；绝对数值是同一轮
ABBA+BAAB 的 `Host time spent` 毫秒：[^ablation]

| 对比 | control（ms） | candidate（ms） | 减少（ms） | 相对改善 | ABBA / BAAB |
|---|---:|---:|---:|---:|---:|
| `B→R` | 61,505.75 | 57,466.50 | 4,039.25 | **6.567272%** | 6.722023% / 6.411125% |

配对的 PMU 变化为 cycles `-6.687843%`、frontend no-ops `-7.435799%`，instructions
`+0.034669%`；这与“布局/前端收益而非删除大量动态工作”的解释一致。[^ablation]

RWA 链的最终落地回归（不是 R 单项的可加值）为旧 RWA baseline
`60,881.50 ms` → `54,088.00 ms`，减少 `6,793.50 ms`、改善 `11.158562%`，
ABBA/BAAB 分别 `11.135149%`/`11.182077%`。[^landing]

## 落地状态与边界

R 与 W、A 在同一 Wolvrix 提交中合入，通用 C++/Python 流程默认启用；没有给 SimTop
另设开关，也不依赖 `targeted-direct`。后续如果只撤回 R，必须重新生成并通过功能及
50k gate，本历史数据不把“只撤回 R、保留 W/A”当作已测组合。[^landing]

### 数据来源（尾注）

[^design]: [`TNO0183`：R/W/A direct ablation 设计与阶段定义](../grhsim_opt_thj/TNO0183_simpletes_v2_direct_ablation_final_attribution_and_retention_decision_20260727.md)。
[^ablation]: [`TNO0183`：R 直接配对及 PMU 结果](../grhsim_opt_thj/TNO0183_simpletes_v2_direct_ablation_final_attribution_and_retention_decision_20260727.md)，含 control/candidate、ABBA/BAAB 和 spread gate。
[^landing]: [`TNO0188`：RWA Wolvrix landing、native 50k 与 generic default](../grhsim_opt_thj/TNO0188_rwa_landing_native_50k_performance_and_default_decision_20260727.md)；落地实现细节见 [`TNO0186`](../grhsim_opt_thj/TNO0186_rwa_wolvrix_landing_implementation_and_provenance_20260727.md)。
[^source]: Wolvrix `16a9f493...` 的 `lib/emit/grhsim_cpp.cpp`（R 的 admission、threshold 和 cold emitter）；可用 `git show 16a9f493687a21a5428f1e1327a69834ea60c9f5 -- lib/emit/grhsim_cpp.cpp` 复核。
