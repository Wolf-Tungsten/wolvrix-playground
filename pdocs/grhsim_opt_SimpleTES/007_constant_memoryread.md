# 007. 常量 MemoryRead 行的直接加载与 OOB 清理消除

这是 `fd12d83f5150cc98540ed3e8f2af3b79f8054da0` 的第三项四项热路径优化。它只处理
生成器能够证明 row index 恒定的 MemoryRead，不等同于后来被否决的通用 residual
MemoryRead 优化。[^design][^excluded]

## 做了什么

当 `constLogicIndexValue` 证明 MemoryRead 的行号是常量时，emitter 直接生成对应的
constant-row load，并把访问标记为 always-in-range；因此删掉了对该路径不可能触发的
out-of-bounds 清理分支。若行号仍动态或证明失败，原有边界检查和清理完整保留。[^source]

## 为什么这样做

常量证明消除了每次读取都要做的索引计算和不可能分支，同时给编译器一个稳定的数组
元素/别名关系。门禁是语义证明，不是基于 SimTop 名称、行号字符串或 workload 的
特判；这也是它与 residual MemoryRead 候选的原则性区别。[^design][^excluded]

## 收益（SimTop 50k walltime）

在 full-gen150 的 final-minus-one 配对中，去掉本项、保留其余三项：[^ablation]

| 对比 | control（ms） | candidate（ms） | 减少（ms） | 相对改善 | ABBA / BAAB | gap |
|---|---:|---:|---:|---:|---:|---:|
| 去掉 #007 → full | 51,964.75 | 51,585.00 | 379.75 | **0.730784%** | 0.695707% / 0.765856% | 0.070149 pp |

完整四项 native endpoint 的 RWA→four 结果为 `53,749.25→51,575.00 ms`，减少
`2,174.25 ms`、改善 `4.045173%`；该端点是组合验证。[^landing]

## 落地状态与排除项

常量行证明和直接 load 进入 generic default。另有 residual MemoryRead 与 physical
zero-tail 消融：早期结果分别为 `-0.115054%`、`-0.247575%`，同 binary 复测为
`+0.023230%`、`-0.049291%`，跨过零且不到 1%，所以没有合入。不能用那些负/零结果
否定本篇的 constant-row proof。[^excluded]

### 数据来源（尾注）

[^design]: [`TNO0205`：四项候选机制及 constant MemoryRead 语义](../grhsim_opt_thj/TNO0205_simpletes_extended_bestpath_direct_ablation_result_20260731.md)。
[^ablation]: [`TNO0205`：#007 final-minus-one walltime 表](../grhsim_opt_thj/TNO0205_simpletes_extended_bestpath_direct_ablation_result_20260731.md)。
[^landing]: [`TNO0207`：四项 landing/regression](../grhsim_opt_thj/TNO0207_four_positive_wolvrix_landing_and_regression_20260731.md) 与 [`TNO0208`：native endpoint](../grhsim_opt_thj/TNO0208_four_positive_simpletes_repin_and_native_50k_20260731.md)。
[^excluded]: [`TNO0205`：residual MemoryRead/physical zero-tail 重测与排除结论](../grhsim_opt_thj/TNO0205_simpletes_extended_bestpath_direct_ablation_result_20260731.md)。
[^source]: Wolvrix `fd12d83f...` 的 constant row proof、direct load 和 impossible OOB clear emission；可用 `git show fd12d83f5150cc98540ed3e8f2af3b79f8054da0 -- lib/emit/grhsim_cpp.cpp` 复核。
