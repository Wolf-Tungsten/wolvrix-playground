# 007. 常量 MemoryRead 行的直接加载与 OOB 清理消除

这是 `fd12d83f5150cc98540ed3e8f2af3b79f8054da0` 的第三项四项热路径优化。它只处理
生成器能证明读取范围的 MemoryRead；其中既包括合法常量 row 的直接下标，也包括
所有已知范围内读取的冗余清零消除。它不等同于后来被否决的 residual MemoryRead
优化。[^design][^excluded]

`MemoryRead` 是从模型化 memory 的某一行取值的 IR 操作；row index 决定读取哪一行。
OOB（out of bounds）表示该行号越过合法范围。这里的“常量”是生成时由 IR 证明的
常量表达式，不是通过观察 SimTop 运行时恰好总读同一行得出的猜测。

## 做了什么

### 先看总结

007 利用生成器已经证明的 memory 访问范围，做两个互补的简化：合法常量 row 直接变成
固定数组下标；任何已经证明不会越界的 materialized read，都不再先把目标临时值清零
再立刻用 load 覆盖。动态或可能越界的读取仍完整保留原检查。

| 场景 | 旧生成形式 | 新生成形式 | 目的 / 边界 |
|---|---|---|---|
| 合法常量 row | 某些非 2 次幂 memory 仍走动态索引/OOB 形式 | 证明 row 合法且恒定后直接发射字面量下标 | 去掉不需要的动态索引和边界分支；越界常量不适用 |
| 已知范围内的 materialized read | 先清零临时值，再用必定合法的 load 完整覆盖 | 直接 load，删除 zero-before-load | 去掉必然被覆盖的 store；适用于所有范围证明，不只常量 row |
| 未证明范围的读取 | 保留动态边界处理 | 继续使用原始 OOB 检查和 fallback | 不根据运行时观察猜测安全性，也不等同于未落地的 residual MemoryRead |

**只需记住：007 是“利用既有范围证明删除确定冗余”，不是把一般 MemoryRead 假定为
合法。在完整六项候选中先去掉本项、再恢复本项，合并两种运行顺序后的 walltime 从
`51,964.75` 降到 `51,585.00 ms`，减少 `379.75 ms`、边际改善 `0.730784%`。**[^ablation]

### 实现与边界

本项包含两个相关但适用范围不同的生成改动：

1. 对没有落入既有“memory 深度为 2 的幂”等快速路径的 MemoryRead，只有当
   `constLogicIndexValue` 能在生成时证明 row 是合法范围内常量，才直接发射字面量数组
   下标；动态 row、越界常量或证明失败都保留原有边界处理。
2. 对所有已经由任一结构证明为 `always-in-range`、并且需要把读取结果存入临时值的
   MemoryRead，删除“先把临时值清零，紧接着又用合法 load 完整覆盖”的冗余清零。这一
   范围不仅包括第一类常量行，也包括既有的 2 次幂或地址域证明路径。[^source]

所以“常量直接下标”和“已知范围内读取的 zero-before-load 消除”是两个增量，不能理解
成“只要 row 是常量，就自动删掉所有 OOB 处理”。

## 为什么这样做

合法常量证明让生成代码直接定位固定数组元素，并去掉该路径不需要的动态索引/OOB
分支；独立的 zero-before-load 消除则避免先写零再马上被合法 load 覆盖。两者门禁都
来自 IR 和 memory 范围证明，不是基于 SimTop 名称、行号字符串或 workload 的特判；
这也是它与 residual MemoryRead 候选的原则性区别。[^design][^excluded]

## 收益（SimTop 50k walltime）

在 full-gen150 的 final-minus-one 配对中，control 去掉本项、保留另外五项，candidate
是完整六项候选；其中两项后来被排除。因此这是六项组合中的边际结果，落地四项的总效果
由独立 endpoint 验证：[^ablation]

| 对比 | control（ms） | candidate（ms） | 减少（ms） | 相对改善 | ABBA / BAAB | gap |
|---|---:|---:|---:|---:|---:|---:|
| 去掉 #007 → full | 51,964.75 | 51,585.00 | 379.75 | **0.730784%** | 0.695707% / 0.765856% | 0.070149 pp |

完整四项 native endpoint 的 RWA→four 结果为 `53,749.25→51,575.00 ms`，减少
`2,174.25 ms`、改善 `4.045173%`；该端点是组合验证。[^landing]

## 落地状态与排除项

上述两项进入 generic default。另有两个不同候选：residual MemoryRead 给未被常量或
其他范围证明覆盖的动态读取 OOB fallback 增加 `unlikely`；physical zero-tail 针对
元素宽度不超过 8 bit、逻辑深度为 256..1024 且不是 2 的幂的小 memory，把物理行数
扩展到下一 2 的幂（例如 352→512），并让新增尾部行保持只读零。这样物理地址域内但
超出逻辑深度的读取可直接得到零，尝试省掉逻辑 OOB 判断。它们早期结果分别为
`-0.115054%`、`-0.247575%`，同 binary 复测为
`+0.023230%`、`-0.049291%`，跨过零且不到 1%，所以没有合入。不能用那些负/零结果
否定本篇的 constant-row proof。[^excluded]

### 数据来源（尾注）

[^design]: [`TNO0205`：四项候选机制及 constant MemoryRead 语义](../grhsim_opt_thj/TNO0205_simpletes_extended_bestpath_direct_ablation_result_20260731.md)。
[^ablation]: [`TNO0205`：#007 final-minus-one walltime 表](../grhsim_opt_thj/TNO0205_simpletes_extended_bestpath_direct_ablation_result_20260731.md)。
[^landing]: [`TNO0207`：四项 landing/regression](../grhsim_opt_thj/TNO0207_four_positive_wolvrix_landing_and_regression_20260731.md) 与 [`TNO0208`：native endpoint](../grhsim_opt_thj/TNO0208_four_positive_simpletes_repin_and_native_50k_20260731.md)。
[^excluded]: [`TNO0205`：residual MemoryRead/physical zero-tail 重测与排除结论](../grhsim_opt_thj/TNO0205_simpletes_extended_bestpath_direct_ablation_result_20260731.md)。
[^source]: Wolvrix `fd12d83f...` 的 constant row proof、direct load 和 impossible OOB clear emission；可用 `git show fd12d83f5150cc98540ed3e8f2af3b79f8054da0 -- lib/emit/grhsim_cpp.cpp` 复核。
