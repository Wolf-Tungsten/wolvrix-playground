# NO0212 GSim DP 阶段图结构收益 Profile

记录日期：2026-07-02

关联：[`NO0038`](./NO0038_gsim_init_to_graphpartition_stage_changes_20260428.md)、[`NO0210`](./NO0210_cross_boundary_activation_work_partition_plan_20260629.md)、[`NO0211`](./NO0211_cbaw_p0_evaluator_rollout_progress_20260701.md)

状态：profile 完成。本文记录 `reference/gsim` 的 `graphPartition()` 中 DP 阶段到底带来多少图结构收益，并补充 GrhSIM `activity-schedule` plain 路径同口径拆分。GSim 口径限定为完整 XiangShan `SimTop.fir`、当前 XS gsim 默认 `--supernode-max-size=15`；GrhSIM 口径限定为完整 XiangShan post-stats checkpoint、当前 XS plain 默认 `max_op_in_compute_supernode=108`。GSim 已补齐 stage-level `boundary_activation_edges` 统计，DP 前后不再只看 quotient graph。

## 1. 结论

`gsim` 的 DP 阶段本身收益很大。本文只把 **coarsen 后 / DP 前** 作为 DP baseline：DP 把 supernode DAG 边从 `1168392` 降到 `646204`，减少 `522188` 条，DP 前后边数降幅为 `522188 / 1168392 = 44.69%`。

同一口径下，supernode 数从 `294107` 降到 `84863`，减少 `209244` 个，降幅 `71.15%`。

补齐 activation 统计后，结论更精确：GSim DP 把严格跨 supernode 的 `boundary_activation_edges` 从 `1548518` 降到 `1367521`，减少 `180997`，降幅只有 `11.69%`。它把 `unique_boundary_activation_edges` 从 `1303334` 降到 `714471`，降幅 `45.18%`，基本贴近 quotient edge 降幅；但每个 unique pair 上仍保留较高 multiplicity，所以真正的 value-target activation work 降幅远小于 DAG 边降幅。

但放到整个 `graphPartition()` 看，最大压缩来源仍是 coarsen，DP 是第二段收益：

| 阶段 | supernodes | supernode edges | avg out-degree |
| --- | ---: | ---: | ---: |
| partition 前 | `2708056` | `4902042` | `1.810170` |
| coarsen 后 / DP 前 | `294107` | `1168392` | `3.972677` |
| DP 后 | `84863` | `646204` | `7.614673` |

关键解释：

- DP 显著减少 supernode 和跨 supernode 边，是真实结构收益，不是只改分布。
- 本文主口径中的 `44.69%` 只相对于 DP 前边数 `1168392` 计算，不混入 partition 前或 coarsen 前的全流程变化。
- 若按更接近 runtime activation work 的 `boundary_activation_edges` 看，GSim DP 的收益是 `11.69%`，明显低于 quotient edge 的 `44.69%`。
- DP 对点的压缩快于对边的压缩，所以平均出度从 `3.97` 升到 `7.61`。这不是 DP 无效，而是更粗粒度 segment 吸收了大量节点后，剩余跨 segment fanout 更集中。
- `node_count`、`edge_count`、`dep_edge_count` 在 DP 前后不变，说明本轮观测的是纯 supernode 边界重组，不是节点集合变化。

## 2. Profile 口径

输入：

```text
build/xs/rtl/rtl/SimTop.fir
```

`gsim`：

```text
reference/gsim HEAD = 4a8e04f + stage activation stats instrumentation
```

参数：

```text
--supernode-max-size=15
--cpp-max-size-KB=8192
--sep-mod=__DOT__
--sep-aggr=__DOT__
--dump-stats-json
--dump-stages=DpProfileAfterCoarsen,DpProfileAfterInitPartition
--stop-after-stage=DpProfileAfterInitPartition
```

这里使用 `15`，因为顶层 XS flow 当前默认：

```make
XS_GSIM_SUPERNODE_MAX_SIZE ?= 15
```

## 3. 采样方法

`reference/gsim` 已新增持久化 profiling 支持：

- `graphCoarsen(); resort();` 之后：`DpProfileAfterCoarsen`
- `graphInitPartition(); orderAllNodes();` 之后：`DpProfileAfterInitPartition`
- `GraphStatsJsonDumper` 额外输出 `activation_edges`、`boundary_activation_edges`、`self_activation_edges`、`unique_boundary_activation_edges`、`boundary_active_source_nodes` 等字段。

这两个 stage 通过 `--dump-stages=DpProfileAfterCoarsen,DpProfileAfterInitPartition` 选择；通过 `--stop-after-stage=DpProfileAfterInitPartition` 可在 DP 后直接退出，避免进入后续 `replicationOpt/generateStmtTree/instsGenerator/cppEmitter`。

GSim stage stats 的 activation 口径为结构口径：按当前 supernode 分组重算 `Node::updateActivate()` 等价的 target supernode 集合，`boundary_activation_edges` 只统计 target 与 source supernode 不同的 cross-supernode target；`activation_edges` 是全量 target，包含 same-supernode reactivation。

## 4. 原始产物

本轮保留的 profile 产物：

```text
tmp/no0212_gsim_dp_boundary_profile_20260702/SimTop_DpProfileAfterCoarsen_Stats.json
tmp/no0212_gsim_dp_boundary_profile_20260702/SimTop_DpProfileAfterInitPartition_Stats.json
```

本轮命令停在 `DpProfileAfterInitPartition`，没有生成后续 stage stats。

```text
reference/gsim/build/gsim/gsim --supernode-max-size=15 --cpp-max-size-KB=8192 --sep-mod=__DOT__ --sep-aggr=__DOT__ --dump-stats-json --dump-stages=DpProfileAfterCoarsen,DpProfileAfterInitPartition --stop-after-stage=DpProfileAfterInitPartition --dir tmp/no0212_gsim_dp_boundary_profile_20260702 build/xs/rtl/rtl/SimTop.fir
```

## 5. 详细结构数据

### 5.1 DP 前后总量

| 指标 | DP 前 | DP 后 | delta | 变化 |
| --- | ---: | ---: | ---: | ---: |
| `supernode_count` | `294107` | `84863` | `-209244` | `-71.15%` |
| `supernode_edge_count` | `1168392` | `646204` | `-522188` | `-44.69%` |
| `avg_out_degree` | `3.972677` | `7.614673` | `+3.641996` | `+91.68%` |
| `activation_edges` | `1549695` | `1378918` | `-170777` | `-11.02%` |
| `boundary_activation_edges` | `1548518` | `1367521` | `-180997` | `-11.69%` |
| `self_activation_edges` | `1177` | `11397` | `+10220` | `+868.31%` |
| `unique_activation_edges` | `1303705` | `719605` | `-584100` | `-44.80%` |
| `unique_boundary_activation_edges` | `1303334` | `714471` | `-588863` | `-45.18%` |
| `active_source_nodes` | `452383` | `442190` | `-10193` | `-2.25%` |
| `boundary_active_source_nodes` | `451390` | `430954` | `-20436` | `-4.53%` |
| `node_count` | `2708070` | `2708070` | `0` | `0.00%` |
| `edge_count` | `4902060` | `4902060` | `0` | `0.00%` |
| `dep_edge_count` | `5352002` | `5352002` | `0` | `0.00%` |

### 5.2 每个 supernode 的 member 分布

| 指标 | DP 前 | DP 后 | 变化 |
| --- | ---: | ---: | ---: |
| mean | `9.20777` | `31.9111` | `+246.57%` |
| median | `1` | `14` | `+1300.00%` |
| p90 | `11` | `34` | `+209.09%` |
| p99 | `86` | `283` | `+229.07%` |
| max | `9913` | `9913` | `0.00%` |

### 5.3 每个 supernode 的 ENode 分布

| 指标 | DP 前 | DP 后 | 变化 |
| --- | ---: | ---: | ---: |
| mean | `46.9897` | `162.765` | `+246.38%` |
| median | `9` | `62` | `+588.89%` |
| p90 | `53` | `156` | `+194.34%` |
| p99 | `404` | `1447` | `+258.17%` |
| max | `272726` | `272726` | `0.00%` |

## 6. 与 `NO0038` 的关系

`NO0038` 已经记录过 `RemoveDeadNodes3 -> graphPartition` 的总体变化：

- `node_count` 不变：`2708070 -> 2708070`
- `supernode_count` 从 `2708056` 压到 `48437`

本轮在当前 `--supernode-max-size=15` 口径下重新拆开 `graphPartition()` 内部阶段，得到：

- coarsen：`2708056 -> 294107`
- DP：`294107 -> 84863`

由于 `NO0038` 使用的历史参数/代码口径与本轮不完全一致，最终 supernode 绝对值不直接混用；但共同结论一致：`graphPartition()` 不改 node 集合，只重组 supernode 边界。

## 7. 对后续 partition 工作的含义

1. `gsim` DP 是有效的强基线。任何 GrhSIM/CBAW 新 partition 方案都不应只和 pre-DP/coarsen 图比较；必须和 DP 后 final supernode graph 比。
2. 只看 supernode 数或 unique quotient edge 会误导。DP 显著减少 supernode，但平均出度上升，且 `boundary_activation_edges` 的降幅远小于 unique edge 降幅，说明结构 gate 必须同时看 `supernodes`、`dag_edges/supernode_edges`、out-degree 分布和 value-target activation work。
3. DP 的主要收益是沿 topo 连续 segment 进一步吃边界，而不是改 node 集合。GrhSIM 后续如果做局部 exact cut / refinement，应保留类似“先有强 coarsen，再做边界代价 DP/refine”的两段式视角。
4. 在完整 gsim `graphPartition` 中，coarsen 仍是 DP 之前的重要压缩阶段。后续要解释 gsim 结构优势时，应明确区分 coarsen 收益和 DP 前后收益。

## 8. GrhSIM plain activity-schedule DP 前后

本轮给 GrhSIM `activity-schedule` 现有 `initial_*` summary 字段接上真实赋值，采样点为：

- DP 前：plain compute coarsen 后、`buildComputeSupernodeSegments()` 前；
- DP 后：`buildComputeSupernodeSegments()` 后 materialize 出来的 final schedule；
- 主口径使用 `WOLVRIX_XS_GRHSIM_SPLIT_OVERSIZE_COMPUTE_NODES=0`，避免 post-DP oversize split 把纯 DP 结果混入 38 个额外 supernode；
- 默认 XS flow 仍保留对照：`split_oversize_compute_nodes=true` 时 final compute supernodes 为 `72180`。

Profile 命令输入：

```text
WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1
WOLVRIX_XS_GRHSIM_POST_STATS_JSON=build/xs/grhsim/wolvrix_xs_post_stats.json
WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1
WOLVRIX_XS_GRHSIM_SPLIT_OVERSIZE_COMPUTE_NODES=0
```

原始产物：

```text
/tmp/no0212_grhsim_plain_dp_profile_nosplit/activity_schedule_supernode_stats.json
build/logs/xs/xs_wolf_grhsim_no0212_plain_dp_profile_nosplit_20260702.log
```

### 8.1 纯 DP 前后结构收益

| 指标 | DP 前 | DP 后 | delta | 变化 |
| --- | ---: | ---: | ---: | ---: |
| `compute_supernodes` | `464998` | `72142` | `-392856` | `-84.49%` |
| `dag_edges` | `1631814` | `702047` | `-929767` | `-56.98%` |
| `boundary_activation_edges` | `2672176` | `2447238` | `-224938` | `-8.42%` |
| `compute_compute_value_pairs` | `2319074` | `2094136` | `-224938` | `-9.70%` |
| `compute_commit_value_pairs` | `353102` | `353102` | `0` | `0.00%` |
| `boundary_values` | `1322618` | `1320402` | `-2216` | `-0.17%` |

解释：

- GrhSIM plain DP 对 quotient DAG 很有效：compute supernode 数降 `84.49%`，DAG 边降 `56.98%`。
- 但对 runtime 更硬的 cross-boundary activation work 收益有限：`boundary_activation_edges` 只降 `8.42%`，且下降全部来自 compute-to-compute target，commit target 完全不变。
- DP 后平均出度上升：`1631814 / (464998 + 502) = 3.51` 到 `702047 / (72142 + 502) = 9.66`。和 GSim 类似，DP 合并大量节点后，剩余跨 supernode fanout 更集中。
- `boundary_values` 几乎不变，说明 DP 主要减少 target supernode 数和 quotient DAG 边，不改变跨边界 value 集合。

### 8.2 默认 XS flow 对照

默认 `split_oversize_compute_nodes=true` 会在 DP 后把 10 个超大 compute node 切出 48 个 compute supernode，因此 final compute supernodes 为 `72180`。该默认口径下：

| 指标 | DP 前 | 默认 final | delta | 变化 |
| --- | ---: | ---: | ---: | ---: |
| `compute_supernodes` | `464998` | `72180` | `-392818` | `-84.48%` |
| `dag_edges` | `1631814` | `702085` | `-929729` | `-56.98%` |
| `boundary_activation_edges` | `2672176` | `2451342` | `-220834` | `-8.26%` |
| `compute_compute_value_pairs` | `2319074` | `2098240` | `-220834` | `-9.52%` |

默认 split 对主结论影响很小：点数多 `38`、DAG 边多 `38`、boundary activation 多 `4104`。后续如果讨论“纯 DP”，使用 nosplit；如果讨论当前 XS runtime 默认结构，使用 split 默认值。

### 8.3 与 GSim DP 的对照

这里使用补齐后的 GSim stage activation stats。对齐口径是“source value/node 到 target supernode 的 cross-supernode target 次数”，不是只看 unique quotient edge。

| 路径 | DP 前 supernodes | DP 后 supernodes | 点降幅 | DP 前 DAG/edge | DP 后 DAG/edge | 边降幅 | DP 前 BAE | DP 后 BAE | BAE 降幅 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| GSim `graphPartition` | `294107` | `84863` | `71.15%` | `1168392` | `646204` | `44.69%` | `1548518` | `1367521` | `11.69%` |
| GrhSIM plain activity-schedule | `464998` | `72142` | `84.49%` | `1631814` | `702047` | `56.98%` | `2672176` | `2447238` | `8.42%` |

这个表把口径对齐后，结论变成：

1. 在 quotient graph 口径下，GrhSIM plain DP 的点/边压缩比例不弱于 GSim DP。
2. 在 cross-supernode `boundary_activation_edges` 口径下，两者 DP 收益都远小于 DAG edge 收益：
   - GSim：`44.69%` edge drop，但 BAE 只降 `11.69%`
   - GrhSIM：`56.98%` edge drop，但 BAE 只降 `8.42%`
3. GSim 的 `unique_boundary_activation_edges` 从 `1303334` 降到 `714471`，降幅 `45.18%`，说明 DP 确实吃掉了大量 unique boundary pair；但 BAE 只降 `11.69%`，说明 remaining pair 上的 multiplicity 仍然是 runtime work 的硬成本。
4. GrhSIM plain 的 `compute_compute_value_pairs` 从 `2319074` 降到 `2094136`，降幅 `9.70%`，和 BAE 降幅一致；`compute_commit_value_pairs` 完全不变。

因此，之前只用 GSim `supernode_edge_count` 和 GrhSIM `boundary_activation_edges` 对照是不完整的。补齐 GSim BAE 后，真正要追的是两边共同暴露出来的问题：DP 能明显压 unique quotient graph，但不能等比例压 value/node-to-target-supernode 的 activation multiplicity。这也解释了为什么 NO0210/NO0211 后续要把 `boundary_activation_edges` 和 `compute_compute_value_pairs` 放进 CBAW 的硬 gate，而不能只看 supernode 数或 DAG 边。
