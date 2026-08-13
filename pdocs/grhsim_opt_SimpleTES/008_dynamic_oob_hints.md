# 008. 动态 shift/index 越界 fallback 的冷分支提示

这是 `fd12d83f5150cc98540ed3e8f2af3b79f8054da0` 中四项热路径改动的第四项，也是收益
最小的一项。它只改变动态索引的分支权重，保留越界时的原有行为。[^design]

## 做了什么

scalar 是单个 C++ 标量可以表示的值；更宽的 HDL 位向量由多个通常为 64 bit 的 word
表示。对这些值的动态 shift/index 操作，生成器将 `shift >= 64`、scalar index 越界
和 word index 越界等 fallback 条件写成 `unlikely`。fallback 是输入超出正常范围时
采用的保守路径，例如移位量达到 64 时返回零，或索引 helper 返回 OOB 哨兵并执行原有
处理。正常范围内的 load/store 以及这些越界结果都不变；这里没有 C++ exception，
“越界语义”仅指原有 fallback 行为。静态常量路径不依赖这项提示。[^source]

## 为什么这样做

在合法索引占绝大多数的仿真中，越界处理是保护性慢路径。把它放入 cold layout 可让
编译器把正常的 shift/index 计算保持连续，并减少前端为低概率分支预留的空间。因为
这是纯 hint，是否有可测收益必须由 50k walltime 决定，不能仅凭生成代码大小判断。
[^design]

## 收益（SimTop 50k walltime）

full-gen150 final-minus-one 直接消融中，control 移除本项并保留另外五项，candidate
为完整六项。另外五项包括后来被排除的两个候选，因此它衡量的是六项组合中的边际贡献；最终落地
四项有独立 endpoint。[^ablation]

| 对比 | control（ms） | candidate（ms） | 减少（ms） | 相对改善 | ABBA / BAAB | gap |
|---|---:|---:|---:|---:|---:|---:|
| 去掉 #008 → full | 51,778.50 | 51,652.75 | 125.75 | **0.242861%** | 0.197044% / 0.288655% | 0.091610 pp |

两种 order 同向，但收益低于该轮预先约定的可信线；该可信线至少为 1%，若 control
自身波动更大则取 control spread。它之所以仍随四项一起落地，是因为
四项组合的整体 endpoint 明确改善（RWA→four：`53,749.25→51,575.00 ms`，
`+4.045173%`），且该 hint 对语义无侵入。[^landing]

## 落地状态与边界

本项进入 generic C++ emitter 默认，Python 和 XiangShan（XS）集成流程继承；没有按
SimTop 的具体索引值或变量名硬编码。若未来编译器/负载变化使它成为负收益，应单独重测并回退，不应把四项
总收益作为本项的独立保证。[^landing]

### 数据来源（尾注）

[^design]: [`TNO0205`：四项动态 OOB hint 的候选说明](../grhsim_opt_thj/TNO0205_simpletes_extended_bestpath_direct_ablation_result_20260731.md)。
[^ablation]: [`TNO0205`：#008 final-minus-one direct ablation](../grhsim_opt_thj/TNO0205_simpletes_extended_bestpath_direct_ablation_result_20260731.md)，含绝对 walltime、ABBA/BAAB 与 gap。
[^landing]: [`TNO0207`：四项落地与回归](../grhsim_opt_thj/TNO0207_four_positive_wolvrix_landing_and_regression_20260731.md)、[`TNO0208`：repin/native 50k endpoint](../grhsim_opt_thj/TNO0208_four_positive_simpletes_repin_and_native_50k_20260731.md)。
[^source]: Wolvrix `fd12d83f...` 的 dynamic shift/index OOB emitter；可用 `git show fd12d83f5150cc98540ed3e8f2af3b79f8054da0 -- lib/emit/grhsim_cpp.cpp` 复核。
