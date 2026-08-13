# 005. 通用 cold SystemTask / standalone assertion hints

这是 `fd12d83f5150cc98540ed3e8f2af3b79f8054da0` 中四项正收益热路径改动的第一项。
它发生在 RWA 之后，和 [004](004_a_assertion_guard.md) 的严格成对 outer guard
不同：本项扩大了可以安全标成冷门的**通用** SystemTask/assertion 形状。[^design][^landing]

## 做了什么

生成器对满足“无返回、无输出、仅有保护性副作用”条件的 standalone `xs_assert_v2`
以及合资格的 `SystemTask` guard 发射 `unlikely`。只改变分支权重和布局，保留原条件、
调用顺序、错误/断言触发和 DPIC 语义；不能证明无副作用的节点不会被标记。[^source]

## 为什么这样做

正常仿真很少走断言失败和保护性 task 路径，但这些代码若与主 schedule 紧邻，会占用
热路径的前端空间。把它们移到 cold layout 可以减少取指干扰。与 #004 的差异在于：
#004 要求一对相邻操作共享条件，本项只依赖单个操作可证明的副作用属性，所以覆盖更广。
[^design]

## 收益（SimTop 50k walltime）

采用 full-gen150 的 `final-minus-one` 配对：每个 candidate 只删除本项，其余三项仍在。
因此该数字是组合中的边际收益，而不是从 RWA baseline 独立测出的收益。[^ablation]

| 对比 | control（ms） | candidate（ms） | 减少（ms） | 相对改善 | ABBA / BAAB | gap |
|---|---:|---:|---:|---:|---:|---:|
| 去掉 #005 → full | 52,365.25 | 51,693.75 | 671.50 | **1.282339%** | 1.327670% / 1.236974% | 0.090697 pp |

四项一起从 native RWA endpoint `53,749.25 ms` 降到 `51,575.00 ms`，减少
`2,174.25 ms`、改善 `4.045173%`；不要把四个 leave-one-out 百分比相加。[^landing]

## 落地状态与边界

该提示以 generic default 进入 C++ emitter，Python/XS 流程继承；没有 SimTop 专用名字
表或额外开关。它只负责 SystemTask/assertion 形状，不能替代 #004 的相邻配对证明。[^landing]

### 数据来源（尾注）

[^design]: [`TNO0205`：四项候选的机制边界](../grhsim_opt_thj/TNO0205_simpletes_extended_bestpath_direct_ablation_result_20260731.md)。
[^ablation]: [`TNO0205`：full-gen150 final-minus-one 表（#005）](../grhsim_opt_thj/TNO0205_simpletes_extended_bestpath_direct_ablation_result_20260731.md)，含绝对 walltime、ABBA/BAAB 和 gap。
[^landing]: [`TNO0207`：四项 Wolvrix landing/regression](../grhsim_opt_thj/TNO0207_four_positive_wolvrix_landing_and_regression_20260731.md)、[`TNO0208`：native endpoint](../grhsim_opt_thj/TNO0208_four_positive_simpletes_repin_and_native_50k_20260731.md)。
[^source]: Wolvrix `fd12d83f...` 的 `lib/emit/grhsim_cpp.cpp` 中 SystemTask/standalone assertion cold emission；可用 `git show fd12d83f5150cc98540ed3e8f2af3b79f8054da0 -- lib/emit/grhsim_cpp.cpp` 复核。
