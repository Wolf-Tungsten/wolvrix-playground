# 006. 高频 word helpers 的 always-inline 提示

这是 `fd12d83f5150cc98540ed3e8f2af3b79f8054da0` 中的第二项四项热路径优化。它针对
生成 C++ 中反复出现的标量 word 操作 helper，不依赖某个 SimTop 变量。[^design]

## 做了什么

对选定且调用频率高的 helper 统一发射 `GRHSIM_ALWAYS_INLINE`，覆盖 truncation、
assign/clear、insert、concat、slice、bitwise 和 reduce 等小型 word 操作。宏在编译器
不支持时退化为普通 inline/空定义；helper 的输入、输出和边界行为没有改变。[^source]

## 为什么这样做

这些函数体很小，但在 schedule 热点中调用很多。明确的 always-inline 提示可以让编译器
把调用点与相邻 guard/值传播放在一起，减少 call/return 边界并暴露更多常量和依赖关系。
这是编译器提示，不保证每个编译器都强制内联；所以只以实际 walltime 判断是否值得保留。
[^design]

## 收益（SimTop 50k walltime）

同一 full-gen150 final-minus-one 消融中，去掉本项、保留其余三项的结果为：[^ablation]

| 对比 | control（ms） | candidate（ms） | 减少（ms） | 相对改善 | ABBA / BAAB | gap |
|---|---:|---:|---:|---:|---:|---:|
| 去掉 #006 → full | 52,032.75 | 51,645.75 | 387.00 | **0.743762%** | 0.729058% / 0.758479% | 0.029421 pp |

四项组合的实际 RWA→four endpoint 为 `53,749.25→51,575.00 ms`（+4.045173%），是
组合口径，不是四个边际值的算术和。[^landing]

## 落地状态与边界

宏和 helper 选择进入通用 emitter 默认路径，C++/Python 共同生效；没有只给 SimTop
打开的选项。未被选择的 helper 保留原实现，避免对大而复杂的函数强制内联造成代码膨胀。
[^landing][^source]

### 数据来源（尾注）

[^design]: [`TNO0205`：四项优化机制与候选范围](../grhsim_opt_thj/TNO0205_simpletes_extended_bestpath_direct_ablation_result_20260731.md)。
[^ablation]: [`TNO0205`：#006 final-minus-one direct ablation](../grhsim_opt_thj/TNO0205_simpletes_extended_bestpath_direct_ablation_result_20260731.md)。
[^landing]: [`TNO0207`：四项 landing/regression](../grhsim_opt_thj/TNO0207_four_positive_wolvrix_landing_and_regression_20260731.md) 和 [`TNO0208`：repin/native 50k](../grhsim_opt_thj/TNO0208_four_positive_simpletes_repin_and_native_50k_20260731.md)。
[^source]: Wolvrix `fd12d83f...` 的 `GRHSIM_ALWAYS_INLINE` 定义及 word helper emitter；可用 `git show fd12d83f5150cc98540ed3e8f2af3b79f8054da0 -- lib/emit/grhsim_cpp.cpp` 复核。
