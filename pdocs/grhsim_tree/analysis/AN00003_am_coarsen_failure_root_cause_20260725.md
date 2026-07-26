# AN00003 为什么 AM 化后 coarsen 失效？（根因分析）

- 记录日期：2026-07-25
- 关联：ST00008（coarsen+dp 剪枝）、AN00002、AN00001
- 问题：legacy 路线的迭代 coarsen 能把 GRH compute DAG 压到 32,034 簇（mean 178 op），移植到 AM atom DAG 后只压到 1,992,995 簇（mean ~2.5 指令）。根因是什么？

## 1. 现象数据

| 口径 | legacy（GRH compute DAG） | AM（atom DAG） |
| --- | --- | --- |
| 节点 | 6,473,680（含常量节点，导出时刻较早，仅供结构对比） | 4,731,246 compute atom（+219k commit atom） |
| 边 | 9,343,709（pair 去重） | 7,462,930（pair 去重）+ ordered-effect 链边 |
| coarsen 结果（修复前） | 32,034 簇（mean 178 op） | 1,992,995 簇（mean ~2.5 指令） |

度数分布对比（均为 pair 去重）：

| 桶 | legacy out | AM out | legacy in | AM in |
| --- | --- | --- | --- | --- |
| 0 | 5.4% | 12.7% | 32.2% | 11.2% |
| 1 | **79.2%** | **66.1%** | 11.8% | 33.8% |
| 2 | 11.6% | 15.9% | 42.7% | 47.3% |
| ≥3 | ~4% | ~5% | ~13% | ~8% |

结论一（推翻初步猜测）：**AM atom 图并没有"宽到不可合并"**——66% 节点出度为 1（legacy 79%），链状结构基本保留，边密度甚至更低（mean out 1.58 vs 1.44 同一量级）。ordered-effect 链边与 def-use 平行边的影响没有先验估计的那么大。

## 2. 根因：tail-stop 实现 bug 使 coarsen 固定 3 轮截断

诊断计数器（随 `coarsen-dp block formation stats` 输出）显示修复前行为：`rounds=3`，out1 轮合并 1,431,956、in1 轮 323,192、sibling 轮 983,103——**每轮都还在大量合并，远未收敛，却停了**。

代码检视确认 bug（`wolvrix/lib/grhsim/am/grhsim_am_activity_schedule.cpp` 原实现）：

```cpp
rebuildClusterGraph();                              // 轮初重建，更新 graph.count
const std::size_t clustersBefore = graph.count;
const bool changed = coarsenRound(pass);            // 合并只改 DSU，不更新 graph.count
const std::size_t clusterDelta = clustersBefore - graph.count;  // 恒为 0！
```

`graph.count` 只在下一轮轮初重建时才更新，所以 `clusterDelta` 恒为 0 → 每轮都被判定"收益枯竭"（<1024）→ 固定在第 3 轮（`kCoarsenTailMaxConsecutiveIters=3`）tail-stop 截断。叠加"单轮单规则 + 每簇每轮至多合并一次"的严格无环设计（长链每轮只能并一节），3 轮只能完成 2.74M 次合并（58%），最终 mean 2.5 指令/簇。

**修复（2026-07-25）**：`clusterDelta` 改用本轮实际合并数（每次 union 恰好减少一个簇）。修复后：`rounds=25`，簇 4,731,246 → **739,294**（mean ~6.4 指令，budget=16），合并 out1 1.88M / in1 0.42M / sibling 1.69M，coarsen_ms=1,471。coarsen 机制本身在 AM 图上确实有效——初步猜测的"图太宽"不成立。

## 3. 反转观察：更深的 coarsen 反而产生更多边界

修复版（深 coarsen，739k 簇）vs 修复前（浅 coarsen，2.0M 簇）vs greedy，同 cap128：

| 指标 | greedy | 浅 coarsen+DP | 深 coarsen+DP |
| --- | --- | --- | --- |
| compute blocks | 36,963 | 37,667 | 38,763 |
| detectors | 1,875,970 | 1,675,451 | **1,889,778（比 greedy 还高）** |
| activation 边 | 3,218,269 | 2,973,867 | 3,108,536 |

反直觉但可解释：DP 段上限 128 指令。浅 coarsen（簇均 2.5 指令）给 DP ~50 个细粒度簇/段的放置自由度，可以把段边界放在跨值最少的位置；深 coarsen（簇均 6.4、部分顶到 16 指令）后每段只有 ~8-20 个簇，边界位置选择变粗，切必经过更稠密的区域。**coarsen 深度与 DP 边界优化自由度存在 trade-off**，budget 应当显著小于段上限（cap/8 当前取值合理甚至偏大）。

## 4. 结论

1. "AM 化后 coarsen 不起作用"的**根因是实现 bug（tail-stop 恒 0 截断在 3 轮），不是图结构问题**；AM atom 图的链状度（66% out-1）与 legacy（79%）同量级。
2. 修复后 coarsen 收敛正常（25 轮、739k 簇），但静态指标反而变差（detectors 高于 greedy）——深 coarsen 压缩了 DP 的边界优化自由度。
3. 结合 ST00008 的 runtime 结论（静态 cut 是弱代理、block exec 由共生激活决定），coarsen 深度/DP 边界质量都不是 runtime 的一阶杠杆；原语成本（ST00003/04）仍是唯一未证伪方向。

## 5. 对树搜索的影响

- coarsen 截断 bug 已修复并保留在工具链（诊断计数器随 stats 输出，后续节点可直接用）；
- ST00008 修复版 codp128 的 2k 门控复测结果见节点文档（静态指标更差，预期仍回归，补测只为闭环强制任务的公平性）；
- 新认知写回候选池依据：块形成/划分方向整体降级，原语成本方向（ST00003/04）确认为主攻。
