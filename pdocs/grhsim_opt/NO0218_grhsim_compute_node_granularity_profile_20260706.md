# NO0218 GrhSIM Compute Node Granularity Profile

记录日期：2026-07-06

关联：[`NO0212`](./NO0212_gsim_dp_stage_structure_gain_20260702.md)、[`NO0214`](./NO0214_cbaw_compute_node_builder_decision_20260703.md)、[`NO0217`](./NO0217_gsim_grhsim_bae_commit_split_classification_20260706.md)

状态：当天 fresh structure profile 已完成。本文回答一个窄问题：`grhsim compute node` 相比 `gsim graphPartition Node` 到底粗多少。

## 1. 结论

按 partition 入口 node 口径，猜测成立：当前 GrhSIM compute node 确实比 GSim Node 粗，平均约 `1.94x`。

计算：

```text
GSim node_count          = 2708070
GrhSIM compute_nodes     = 1396066
GrhSIM / GSim node count = 0.515521
GSim / GrhSIM node count = 1.939787
```

也就是说，同一个完整 XiangShan `SimTop` 上，GrhSIM 只有约 `51.55%` 的入口 compute nodes；反过来，每个 GrhSIM compute node 平均覆盖约 `1.94` 个 GSim partition Nodes 的粒度。

CBAW atom 口径也几乎一致：

```text
CBAW atom_count          = 1396096
CBAW atom / GSim Node    = 0.515532
GSim Node / CBAW atom    = 1.939745
```

这个结论不应和 `GSim ENode` 混用。`ENode` 是表达式树层级，`GSim Node` 才是和 GrhSIM compute node / CBAW atom 对齐的 partition 顶点口径。

## 2. 本次 profile 口径

GSim：

```text
reference/gsim/build/gsim/gsim \
  --supernode-max-size=15 \
  --cpp-max-size-KB=8192 \
  --sep-mod=__DOT__ \
  --sep-aggr=__DOT__ \
  --dump-stats-json \
  --dump-stages=DpProfileAfterCoarsen,DpProfileAfterInitPartition \
  --stop-after-stage=DpProfileAfterInitPartition \
  --dir tmp/no0218_compute_node_granularity_20260706/gsim \
  build/xs/rtl/rtl/SimTop.fir
```

GrhSIM：

```text
WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1
WOLVRIX_XS_GRHSIM_PARTITION_POLICY=cbaw
WOLVRIX_XS_GRHSIM_FM_REFINE_MAX_ROUNDS=8
WOLVRIX_XS_GRHSIM_CBAW_COARSEN_MAX_ITERATIONS=32
WOLVRIX_XS_GRHSIM_CBAW_PLAIN_BOUNDARY_BASELINE=2446334
WOLVRIX_XS_GRHSIM_CBAW_PLAIN_DAG_BASELINE=703270
WOLVRIX_XS_GRHSIM_CBAW_PLAIN_COMPUTE_COMPUTE_BASELINE=2095811
make xs_wolf_grhsim_emit \
  RUN_ID=no0218_compute_node_granularity_20260706 \
  XS_GRHSIM_BUILD=tmp/no0218_compute_node_granularity_20260706/grhsim \
  XS_WOLF_GRHSIM_RESUME_FROM_PRE_REG_TO_MEM_JSON=1 \
  XS_WOLF_GRHSIM_PRE_REG_TO_MEM_JSON=/home/gaoruihao/wksp/wolvrix-playground/build/xs/grhsim/wolvrix_xs_pre_reg_to_mem.json \
  XS_WOLF_GRHSIM_ENABLE_STATS=0 \
  XS_WOLF_GRHSIM_RESUME_FROM_STATS_JSON=0 \
  XS_WOLF_GRHSIM_POST_STATS_JSON=/home/gaoruihao/wksp/wolvrix-playground/tmp/no0218_compute_node_granularity_20260706/grhsim/wolvrix_xs_post_stats.json \
  XS_WOLF_GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE=108 \
  XS_WOLF_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE=4096
```

产物：

```text
tmp/no0218_compute_node_granularity_20260706/gsim/SimTop_DpProfileAfterCoarsen_Stats.json
tmp/no0218_compute_node_granularity_20260706/gsim/SimTop_DpProfileAfterInitPartition_Stats.json
tmp/no0218_compute_node_granularity_20260706/grhsim/grhsim_emit/activity_schedule_supernode_stats.json
tmp/no0218_compute_node_granularity_20260706/grhsim/grhsim_emit/activity_schedule_cbaw_stats.json
build/logs/xs/xs_wolf_grhsim_build_no0218_compute_node_granularity_20260706.log
```

本轮只跑 structure profile，没有重新 build / run emu。

## 3. 入口 node 粒度

| 指标 | GSim `graphPartition Node` | GrhSIM compute node | GrhSIM / GSim |
| --- | ---: | ---: | ---: |
| nodes | `2708070` | `1396066` | `0.515521x` |
| 反向粒度 | - | `2708070 / 1396066` | `1.939787x` |

CBAW atom 补充：

| 指标 | GSim `graphPartition Node` | GrhSIM CBAW atom | GrhSIM / GSim |
| --- | ---: | ---: | ---: |
| nodes / atoms | `2708070` | `1396096` | `0.515532x` |
| direct / quotient edges | `4902060` | `3679158` | `0.750526x` |
| avg out-degree | `1.810167` | `2.635319` | `1.455843x` |

直接解读：

- GrhSIM compute node / CBAW atom 的点数约为 GSim Node 的一半，因此平均 node 粒度约 `1.94x` 粗。
- 但边数没有按同等比例下降：CBAW atom quotient edges 仍是 GSim direct edges 的 `75.05%`。
- 所以入口图同时呈现“更粗、更密”：node count 低，avg out-degree 高。

## 4. 中间 coarsen 与 final 对比

### 4.1 coarsen 后 / DP 前附近

| 指标 | GSim after coarsen | GrhSIM after P5 coarsen | GrhSIM / GSim |
| --- | ---: | ---: | ---: |
| nodes / clusters | `294107` | `449958` | `1.529913x` |
| DAG / supernode edges | `1168392` | `1539168` | `1.317339x` |
| boundary activation edges | `1548518` | `2569549` | `1.659360x` |
| avg out-degree | `3.972677` | `3.420693` | `0.861059x` |

这里和入口 node 结论不矛盾：GrhSIM 入口 compute node 更粗，但当前 CBAW P5 coarsen 后的中间 cluster 绝对数仍比 GSim after-coarsen supernode 多 `1.53x`。原因是 GSim graphCoarsen 从 `2708056` 压到 `294107`，压缩非常激进；GrhSIM CBAW coarsen32 从 `1396066` 压到 `449958`，相对自身入口仍保留 `32.23%`。

### 4.2 final / DP 后附近

| 指标 | GSim after init partition | GrhSIM final CBAW | GrhSIM / GSim |
| --- | ---: | ---: | ---: |
| supernodes | `84863` | `75074` | `0.884649x` |
| compute supernodes | - | `74577` | - |
| commit supernodes | - | `497` | - |
| DAG / supernode edges | `646204` | `643038` | `0.995101x` |
| boundary activation edges | `1367521` | `2253277` | `1.647709x` |
| avg out-degree | `7.614673` | `8.565389` | `1.124852x` |

Final 图的点数和 DAG edge 已经不比 GSim 多：

- total supernodes 是 GSim 的 `0.885x`
- DAG edge 是 GSim 的 `0.995x`

但 BAE 仍是 GSim 的 `1.648x`。这说明当前主要差距不是 final 点数或 unique DAG edge，而是同一组跨 supernode 关系上携带了更多 value-target activation。

## 5. GrhSIM compute node 内部规模

本轮 GrhSIM compute-node builder 统计：

| 指标 | 数值 |
| --- | ---: |
| `compute_nodes` | `1396066` |
| `compute_node_ops_total` | `6429337` |
| `source_clones_in_compute_nodes` | `2047021` |
| `compute-like ops` = total - source clones | `4382316` |
| `ops / compute_node` | `4.605325` |
| `source_clones / compute_node` | `1.466278` |
| `compute-like ops / compute_node` | `3.139046` |
| `common_expr_compute_nodes` | `818757` |

CBAW atom op-count 分布：

| 指标 | value |
| --- | ---: |
| atom count | `1396096` |
| op-count p50 | `2` |
| op-count p90 | `7` |
| op-count p99 | `56` |
| op-count p99.5 | `108` |
| op-count max | `108` |

这给出了另一个侧面：GrhSIM compute node / atom 不是“每个只含一个表达式 node”的细粒度结构，而是已经吸收了多个 compute-like op 和 source clone 的小 MFFC-like 单元。

## 6. 节点内 op / ENode 数量对比

本节补充“节点内部 payload”口径。注意两边不是完全同构：

- GSim `nodes_enodes` 是每个 `Node` 关联表达式树里的 unique `ENode` 数，包含 ref/int/表达式 ENode。
- GrhSIM `compute_node_ops_total` 是 compute node 内的 GRH op 总数，包含 source clone。
- GrhSIM `compute-like ops` 是从 `compute_node_ops_total` 中扣除 `source_clones_in_compute_nodes` 后的补充口径。

### 6.1 partition 入口 node 内部规模

| 指标 | GSim Node `ENode` | GrhSIM compute node op | GrhSIM / GSim |
| --- | ---: | ---: | ---: |
| count | `2708070` | `1396066` | `0.515521x` |
| payload sum | `13822633` | `6429337` | `0.465131x` |
| mean payload / node | `5.104240` | `4.605325` | `0.902255x` |
| median / p50 | `4` | `2` | `0.500000x` |
| p90 | `6` | `7` | `1.166667x` |
| p99 | `12` | `56` | `4.666667x` |
| max | `270469` | `108` | `0.000399x` |

如果扣掉 GrhSIM source clone：

| 指标 | 数值 |
| --- | ---: |
| GrhSIM compute-like ops | `4382316` |
| compute-like ops / compute node | `3.139046` |
| compute-like mean / GSim Node ENode mean | `0.614988x` |
| compute-like payload sum / GSim Node ENode sum | `0.317039x` |

这个表说明一个细节：虽然 GrhSIM compute node 的数量只有 GSim Node 的一半，平均 node 粒度按“点数倒数”是 `1.94x` 粗，但“每个节点内部 op/enode 的平均 payload”并没有同步变大。GrhSIM total op mean 是 GSim per-Node ENode mean 的 `0.90x`；扣掉 source clone 后只有 `0.61x`。

真正更重的是尾部：GrhSIM CBAW atom 的 p99 op-count 是 `56`，GSim Node 的 p99 ENode-count 是 `12`，p99 层面 GrhSIM 是 `4.67x`。同时 GrhSIM atom 被 `108` cap 截断，而 GSim Node 仍有极端大表达式树，max 到 `270469`。

### 6.2 coarsen 后中间节点内部规模

| 指标 | GSim after-coarsen supernode ENode | GrhSIM after-P5 cluster op | GrhSIM / GSim |
| --- | ---: | ---: | ---: |
| count | `294107` | `449958` | `1.529913x` |
| mean payload / node | `46.989700` | `14` | `0.297938x` |
| median / p50 | `9` | `3` | `0.333333x` |
| p90 | `53` | `58` | `1.094340x` |
| p99 | `404` | `108` | `0.267327x` |
| max | `272726` | `1026` | `0.003762x` |

这里的形态更清楚：GrhSIM after-P5 cluster 数比 GSim after-coarsen supernode 多 `1.53x`，但单个 cluster 内部 payload 平均显著更轻。P90 接近，p99 和 max 反而远小于 GSim 的 after-coarsen supernode ENode。

### 6.3 final supernode 内部规模

| 指标 | GSim after-init-partition supernode ENode | GrhSIM final compute supernode op | GrhSIM / GSim |
| --- | ---: | ---: | ---: |
| count | `84863` | `74577` | `0.878793x` |
| mean payload / node | `162.765000` | `86.210722` | `0.529664x` |
| median / p50 | `62` | `96` | `1.548387x` |
| p90 | `156` | `108` | `0.692308x` |
| p99 | `1447` | `108` | `0.074637x` |
| max | `272726` | `108` | `0.000396x` |

Final 阶段也类似：GrhSIM compute supernode 的 p50 更高，因为 DP/cap 把大多数 compute supernode 填到接近 `108`；但平均值、p90/p99/max 都小于 GSim supernode ENode payload。也就是说，GrhSIM final BAE 偏高不是因为单个 final compute supernode 内部 op payload 比 GSim 更大；它更像是 value-target boundary 分布和 activation multiplicity 问题。

## 7. 判断

本轮 fresh profile 支持如下判断：

1. 如果问题是“GrhSIM compute node 相比 GSim Node 粗多少”，答案是约 `1.94x` 粗。
2. 这个结论在 CBAW atom 口径下也成立：`1396096 / 2708070 = 0.5155x`。
3. 从节点内部 payload 看，GrhSIM compute node 的平均 op 数并不比 GSim Node 的平均 ENode 数更大：total op mean 是 `0.90x`，compute-like mean 是 `0.61x`；但 p99 尾部更重，CBAW atom p99 是 GSim Node p99 的 `4.67x`。
4. 入口 compute node 更粗，并不等价于 final activation work 更低。当前 final DAG edge 已与 GSim 基本相同，但 BAE 仍高 `64.77%`。
5. 因此当前优化主线不应是继续单纯减少 compute node 数，也不应只盯单节点内部 op 数；更直接的目标仍是压 value-target multiplicity，尤其是 compute-compute boundary propagation。commit split 固定项已在 [`NO0217`](./NO0217_gsim_grhsim_bae_commit_split_classification_20260706.md) 中拆出。

一句话结论：**GrhSIM compute node 的静态入口粒度约为 GSim Node 的 `1.94x`，但当前 runtime 结构差距主要不在 node 数，而在跨 supernode activation multiplicity。**
