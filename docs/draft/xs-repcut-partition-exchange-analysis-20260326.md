# XiangShan RepCut 分区数据交换特征分析（2026-03-26）

## 1. 分析对象

本文联合分析以下两份原始数据：

- timing 数据：[build/logs/xs-repcut/xs_verilator_repcut_20260326_155642.timing.jsonl](/workspace/wolvrix-playground/build/logs/xs-repcut/xs_verilator_repcut_20260326_155642.timing.jsonl)
- 分区静态特征：[build/xs/repcut/work/SimTop_repcut_k32.partition_features.jsonl](/workspace/wolvrix-playground/build/xs/repcut/work/SimTop_repcut_k32.partition_features.jsonl)

分析目标是回答两个问题：

1. 这 32 个分区在跨分区数据交换上各自呈现什么特征。
2. 这些交换特征与 `scatter / gather / eval` 时间之间有什么关系。

## 2. 数据口径与限制

`partition_features.jsonl` 中只有两类记录：

- `partition_static_feature_summary`
- `partition_static_features`

其中 `partition_static_features` 仅提供“每个分区”的聚合交换统计，例如：

- `cross_in_value_count`
- `cross_out_value_count`
- `cross_in_word_count`
- `cross_out_word_count`

因此，本文能分析的是：

- 每个分区的边界输入压力
- 每个分区的边界输出压力
- 分区是偏“吸入型”还是偏“输出型”
- 这些压力与 `scatter / gather / eval` 的相关性

本文不能直接分析的是：

- `part_i -> part_j` 的点对点交换矩阵
- 任意两分区之间的精确交换边数

如果后续需要“分区对分区”的矩阵或热图，需要额外导出边级别或 adjacency 级别数据。

下文中把：

- `cross_in_*` 视为该分区在 step 开始时需要从其他分区接收的数据规模
- `cross_out_*` 视为该分区在 step 结束后需要向其他分区发布的数据规模

这是基于字段命名和 timing 相关性做的推断，不是文件内显式定义。

## 3. 全局交换画像

`partition_static_feature_summary` 给出的全局唯一跨分区 value 数是：

- `cross_value_count = 1,573,894`

把 32 个分区的入边界和出边界分别求和后，可以看到：

- 全部分区 `cross_in_value_count` 之和：`1,573,894`
- 全部分区 `cross_out_value_count` 之和：`1,573,894`
- 因而按“端点”统计的总交换量：`3,147,788 values`

按 word 统计：

- 全部分区 `cross_in_word_count` 之和：`1,844,484`
- 全部分区 `cross_out_word_count` 之和：`1,844,484`
- 总交换端点量：`3,688,968 words`

这说明两件事：

1. 每个跨分区 value 在全局 summary 中只记一次。
2. 每个跨分区 value 在分区视角上会同时体现在某个分区的 `cross_out_*` 和另一个分区的 `cross_in_*`。

整体分布有明显长尾：

- 平均每个分区总交换量：`98,368.375 values`
- 中位数：`50,972.5 values`
- 平均每个分区总交换字数：`115,280.25 words`
- 中位数：`51,402.5 words`

均值显著高于中位数，说明交换负载集中在少数热点分区，而不是平均铺开。

### 3.1 交换量最大的分区

按 `cross_in_value_count + cross_out_value_count` 排序：

| part | cross_in | cross_out | total values | share |
| --- | ---: | ---: | ---: | ---: |
| `part_26` | `40,862` | `464,294` | `505,156` | `16.05%` |
| `part_30` | `314,296` | `186,530` | `500,826` | `15.91%` |
| `part_25` | `119,183` | `143,877` | `263,060` | `8.36%` |
| `part_23` | `146,402` | `100,942` | `247,344` | `7.86%` |
| `part_8` | `41,827` | `159,770` | `201,597` | `6.40%` |
| `part_14` | `42,479` | `144,073` | `186,552` | `5.93%` |

前 6 个分区合计占全部交换端点量的 `60.50%`。这意味着：

- 通信热点高度集中
- 后续优化不能只看“平均每个 part”，必须盯住少数高边界流量分区

## 4. 分区方向性分类

这里按 `cross_in / cross_out` 比值把分区分成三类：

- `in-heavy`：`cross_in / cross_out >= 2`
- `out-heavy`：`cross_in / cross_out <= 0.5`
- `balanced`：其余情况

统计结果如下：

| category | part count | avg total cross values | avg scatter us | avg gather us | avg eval us |
| --- | ---: | ---: | ---: | ---: | ---: |
| `in-heavy` | `16` | `43,755.9` | `726.894` | `79.409` | `108.806` |
| `out-heavy` | `5` | `195,992.4` | `309.109` | `280.184` | `292.550` |
| `balanced` | `11` | `133,430.2` | `284.229` | `378.907` | `388.042` |

可以看到比较清楚的模式：

1. `in-heavy` 分区的平均 `scatter` 最高，明显高于 `gather`。
2. `out-heavy` 分区的平均 `gather` 和 `eval` 都更重，说明这类分区更像“汇出端”或“结果集散端”。
3. `balanced` 分区虽然方向性不极端，但平均 `eval` 最高，说明这类分区往往既有较重边界交换，也承载更重的内部逻辑。

### 4.1 典型 `in-heavy` 分区

最典型的一组是：

- `part_16`
- `part_17`
- `part_18`
- `part_19`
- `part_20`
- `part_21`
- `part_22`

这些分区的共同特征是：

- `cross_in_value_count` 大多在 `48k ~ 50k`
- `cross_out_value_count` 非常小，只有几百到几千
- `scatter_avg_us` 在 `1118 ~ 1190 us`
- `gather_avg_us` 只有 `11 ~ 34 us`

这批分区几乎是纯输入驱动型分区，step 时间几乎全部花在把输入边界数据装进来。

### 4.2 典型 `out-heavy` 分区

最典型的是：

- `part_26`：`cross_out_value_count = 464,294`
- `part_14`：`cross_out_value_count = 144,073`
- `part_8`：`cross_out_value_count = 159,770`

这些分区都具有很强的输出属性，其中 `part_26` 是整个 k32 切分里最突出的“发布端”。

## 5. 与 Timing 的相关性

下面用 Pearson 和 Spearman 相关系数，把静态交换特征和 timing 做 join 分析。

| relation | Pearson | Spearman |
| --- | ---: | ---: |
| `scatter_avg_us` vs `cross_in_value_count` | `0.143` | `0.717` |
| `scatter_avg_us` vs `cross_in_word_count` | `0.035` | `0.649` |
| `gather_avg_us` vs `cross_out_value_count` | `0.503` | `0.885` |
| `gather_avg_us` vs `cross_out_word_count` | `0.445` | `0.882` |
| `scatter+gather` vs `cross_total_value_count` | `0.272` | `0.482` |
| `eval_avg_us` vs `cross_total_value_count` | `0.361` | `0.629` |
| `eval_avg_us` vs `op_count` | `0.775` | `0.938` |
| `eval_avg_us` vs `estimated_node_weight_sum` | `0.731` | `0.883` |

这里可以支持几个判断：

1. `gather` 和 `cross_out` 的关系最稳定，排序相关性非常强。
2. `scatter` 和 `cross_in` 也有明显单调关系，但线性关系弱于 `gather`。
3. `eval` 与交换量有一定关系，但更强的决定因素仍然是 `op_count` 和 `estimated_node_weight_sum`。

这意味着：

- `scatter/gather` 更多反映的是边界通信压力
- `eval` 更多反映的是分区内部的逻辑规模和计算复杂度

## 6. 通信热点与异常点

### 6.1 `scatter` 主导热点

按 `scatter_avg_us` 排名前 8 的分区：

| part | cross_in | cross_out | scatter us | gather us | eval us |
| --- | ---: | ---: | ---: | ---: | ---: |
| `part_21` | `49,361` | `282` | `1189.675` | `12.150` | `25.903` |
| `part_22` | `48,901` | `345` | `1171.551` | `11.351` | `25.033` |
| `part_19` | `49,560` | `1,469` | `1168.138` | `33.902` | `29.856` |
| `part_17` | `48,789` | `3,174` | `1159.261` | `27.174` | `29.388` |
| `part_18` | `49,443` | `1,473` | `1142.609` | `21.908` | `56.383` |
| `part_16` | `49,254` | `1,095` | `1140.802` | `18.741` | `63.746` |
| `part_20` | `49,589` | `506` | `1118.648` | `16.636` | `45.720` |
| `part_1` | `41,216` | `15,967` | `859.810` | `106.094` | `59.468` |

这些分区的一个鲜明特征是：`scatter + gather` 基本占掉分区 step 时间的绝大部分。

占比最高的几个分区：

- `part_22`：`97.93%`
- `part_21`：`97.89%`
- `part_17`：`97.58%`
- `part_19`：`97.58%`

也就是说，这些分区不是“内部算得慢”，而是边界装载本身就是主要成本。

### 6.2 `gather` 主导热点

按 `gather_avg_us` 排名前 6 的分区：

| part | cross_out | gather us | scatter us | eval us |
| --- | ---: | ---: | ---: | ---: |
| `part_5` | `70,743` | `1019.480` | `221.427` | `135.031` |
| `part_30` | `186,530` | `661.353` | `174.851` | `781.993` |
| `part_12` | `29,534` | `464.189` | `81.552` | `337.374` |
| `part_26` | `464,294` | `455.562` | `311.424` | `100.014` |
| `part_9` | `32,435` | `408.928` | `332.998` | `271.767` |
| `part_8` | `159,770` | `385.856` | `313.252` | `575.516` |

这里最值得注意的是：

- `part_5` 并不是最大输出分区，但 `gather` 时间是全局最高
- `part_26` 的输出量远高于所有其他分区，但 `gather` 时间只排第 4

所以 `gather` 并不只由输出条目数决定，还受边界值布局、宽度分布和打包方式影响。

### 6.3 单位交换成本异常

把 `scatter_avg_us / cross_in_value_count` 和 `gather_avg_us / cross_out_value_count` 看作“每个边界 value 的平均处理成本”，单位记为 `ns/value`。

平均水平：

- `scatter_per_in_value_ns` 均值：`13.650`
- `gather_per_out_value_ns` 均值：`17.143`

#### `scatter` 单位成本最高的分区

| part | scatter ns/value |
| --- | ---: |
| `part_21` | `24.102` |
| `part_22` | `23.958` |
| `part_17` | `23.761` |
| `part_19` | `23.570` |
| `part_16` | `23.162` |

#### `scatter` 单位成本最低的分区

| part | scatter ns/value |
| --- | ---: |
| `part_30` | `0.556` |
| `part_27` | `2.141` |
| `part_12` | `3.033` |
| `part_23` | `4.609` |
| `part_5` | `5.219` |

#### `gather` 单位成本最高的分区

| part | gather ns/value |
| --- | ---: |
| `part_21` | `43.085` |
| `part_29` | `42.253` |
| `part_2` | `33.665` |
| `part_24` | `33.011` |
| `part_22` | `32.901` |

#### `gather` 单位成本最低的分区

| part | gather ns/value |
| --- | ---: |
| `part_26` | `0.981` |
| `part_25` | `1.956` |
| `part_14` | `2.240` |
| `part_8` | `2.415` |
| `part_3` | `3.214` |

这个结果非常关键：

1. 通信总量大，不一定单位成本高。
2. `part_30` 和 `part_26` 是高流量但低单位成本的代表。
3. `part_21` 和 `part_22` 则是流量不算全局最高，但单位通信成本很差的代表。

因此，优化优先级不能只看交换量，还要看单位交换成本。

### 6.4 `eval` 热点更多由分区内部规模决定

`eval_avg_us` 最高的几个分区是：

- `part_31`：`1264.527 us`
- `part_30`：`781.993 us`
- `part_29`：`618.012 us`
- `part_8`：`575.516 us`
- `part_3`：`532.448 us`

这些分区中，`part_30` 和 `part_8` 同时也是高通信分区，但 `part_31` 并不是最大的通信热点，却是最大的 `eval` 热点。

结合相关系数：

- `eval` 对 `op_count` 的 Pearson 是 `0.775`
- `eval` 对 `estimated_node_weight_sum` 的 Pearson 是 `0.731`

可以认为 `eval` 主要看内部图规模，而不是单纯看分区边界流量。

## 7. 可以支持的结论

基于这两份原始数据，可以比较稳地得出以下结论：

1. k32 切分的跨分区交换负载非常不均衡，热点集中在少数分区。
2. `part_26`、`part_30` 是全局最大的交换中心，前 2 个分区已经占掉 `31.96%` 的全部交换端点量。
3. `part_16 ~ part_22` 这一串分区是典型的 `in-heavy` 组，性能主要受 `scatter` 限制。
4. `part_26` 是最典型的 `out-heavy` 分区，但它的 `gather` 单位成本并不高，说明它更像“流量大但处理路径高效”。
5. `part_21`、`part_22` 是最值得优先怀疑的通信低效分区，因为它们的 `scatter` 和 `gather` 单位成本都异常高。
6. `part_5` 是最突出的 `gather` 热点，输出量不是最大，但写回/发布路径代价非常高。
7. `eval` 热点和边界交换存在关联，但决定性因素更接近分区内部 op 规模，而不是边界流量本身。

## 8. 下一步建议

如果后续目的是继续优化性能，建议优先按下面顺序推进：

1. 先看 `part_21`、`part_22`、`part_17`、`part_19` 的 `scatter` 实现路径，确认是否存在低效的输入搬运、重复索引或不连续布局。
2. 单独检查 `part_5` 的 `gather` 发布逻辑，重点看边界值打包和 writeback 路径。
3. 对比 `part_26` / `part_30` 与 `part_21` / `part_22` 的 wrapper 生成结果，找“高流量但高效”和“流量一般但低效”之间的结构差异。
4. 如果要真正分析“分区之间”的交换拓扑，补充导出 pairwise edge 统计，否则无法定位 `part_i -> part_j` 的具体热点连边。
