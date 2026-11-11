# TNO0024 RepCut 历史 10 秒 anchor 复核

## 问题

此前确有约 9–10 秒的 32 线程 RepCut GrhSIM 结果。旧记录 TNO0359 的历史恢复版 walltime 中位数为 8.925 s；同一 binary 在本轮 node030 重新运行的中位数为 10.667 s。当前 merge-before retained binary 在同一复测中位数为 17.896 s。

因此“旧结果约 10 秒”与本轮“before 约 18 秒”不是同一个 binary。两侧的完整身份和复测数据见 [机器可读审计](../../build/artifacts/repcut-historical-anchor-audit-20261111/report.json)。

## 控制复测

使用当前 grhsim32_pair_compare.py runner，把历史恢复版 ELF 与 merge-before ELF 放进同一个新输出目录。两侧统一：

- node030，CPU96–127，32 个 pinned worker，NUMA1 strict membind；
- setarch -R，完整 DiffTest/NEMU，CoreMark 两轮，100,000 周期；
- 8 对 AB/BA、同一冻结 workload/NEMU、同一当前 runtime preload/code-page helper；
- 不做外部 CPU 空闲准入检查；每个样本检查 singleton affinity、codepage、内存 locality 和功能签名。

两侧共同终止条件和 CoreMark 输出通过，8 对样本全部有效：

| 版本 | 当前 runner Host 均值 / 中位数 | 当前 runner 外部 walltime 均值 / 中位数 |
| --- | ---: | ---: |
| 历史恢复版 anchor | 10.552 / 10.667 s | 10.653 / 10.764 s |
| merge-before retained | 17.770 / 17.896 s | 17.867 / 17.996 s |

merge-before 相对历史 anchor 的 Host time 为 **+68.420%**，固定 seed 20261102 的 95% CI 为 **[+66.519%, +70.090%]**，8/8 更慢。历史 anchor 的代码页覆盖为 85,983,232 B，merge-before 为 88,080,384 B；两侧均通过 codepage gate，不能用“没有大页”解释这次差距。

## 参数与 assignment 对齐审计

RepCut 的公共生成参数已经逐项对齐：两侧都是 `SimTop`、32 partitions、8 solver runs、`epsilon=0.05`，KaHyPar revision `135b23da324e6c35b0cde5a9a7db03200272f3b7`，`row_limit=2`、`strict_init=false`，以及同一组 24 个 `WOLVRIX_GRHSIM_*` options。当前 before 的 `selection.json` 选择 seed3，历史 anchor 则来自 `piece_982888_p11_to_5` 的历史恢复 preset；它不是本轮标准 pipeline 的 seed3 candidate。

两份 reduced HGR 的维度相同（`296526` vertices、`301184` hyperedges），文件大小也只差 68 B（329,633,099 vs 329,633,167 B）。真正不同的是 assignment 和其产生的跨分区闭包/序列化结果。排除保留的 part0 isolated entry 后，历史 assignment 的最大分区为 part18、23,303 entries（2.399x active-part average）；当前 seed3/candidate 的最大分区为 part1、32,560 entries（3.351x active-part average）。当前 candidate 与 seed3 的 assignment 统计相同，说明这次只移动的少量 migration atoms 没有改变主负载形状。

因此 `partitioned.json` 的 3,873,578,714 vs 4,355,233,374 B 不是由 `epsilon` 或 solver revision 漂移造成的，而是历史调优 assignment 与当前标准 retained candidate 不同造成的模型展开差异。历史 assignment 的分区负载更均匀，直接对应后面的 `part_eval` 和 barrier 差距。

## 差距来源

当前 runner 的 phase timing 显示差距主要在分区 eval：

| 指标（8 对中位数） | 历史 anchor | merge-before |
| --- | ---: | ---: |
| part eval 总和 / ms | 8,399.6 | 15,306.3 |
| global update / ms | 1,482.5 | 1,770.1 |
| 分区 eval 平均值之和 / us | 605.175 | 750.761 |
| 最慢分区 eval / us | 26.798 | 44.992 |

这表示当前 merge-before 的分区负载更不均衡，barrier 等待和最慢分区成本更高。生成包文件数量和总字节并不能代表运行速度：历史包有 7,815 个 C++、约 1.723 GB；merge-before 有 7,778 个 C++、约 1.719 GB，但当前最慢分区 eval 仍高约 68%。

还有两个构建差异需要保留：

- 历史 anchor 使用 Clang 23.1.2；merge-before binary 的 .comment 是 Ubuntu Clang 19.1.1。
- 历史 partitioned input SHA256 为 5508c94071580932bde8d70f41a3f29f00d842b7000bc72328ff7735378f47d3、3,873,578,714 bytes；merge-before 为 70df1e97d24a1755fd5106710085b2d52ce70fbbab84dc0d4255b11340095ba0、4,355,233,374 bytes。它们不是同一 partitioned graph。

所以当前证据支持的结论是：约 10 秒来自历史恢复版的 partitioned model、assignment、生成 binary 和 Clang 23 编译产物；merge-before 是重新生成的 retained candidate，具有不同的分区负载形状，并使用 Clang 19。当前实验的 +31.459% merge-before/after 结论仍然有效，但不能把 merge-before 当成历史 10 秒性能锚点。

原始数据：[审计 summary](../../build/xs/repcut-historical-anchor-audit-20261111/summary.json)、[逐对 CSV](../../build/xs/repcut-historical-anchor-audit-20261111/pairs.csv)、[逐对 JSON](../../build/xs/repcut-historical-anchor-audit-20261111/pairs.json)、[运行 manifest](../../build/xs/repcut-historical-anchor-audit-20261111/manifest.json)。本次旧 binary 只读复用，没有修改历史产物。
