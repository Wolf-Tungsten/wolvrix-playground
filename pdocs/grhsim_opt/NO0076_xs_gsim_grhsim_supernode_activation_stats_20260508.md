# NO0076 XS GSim / GrhSIM Supernode Activation Stats Snapshot

> 归档编号：`NO0076`。目录顺序见 [`README.md`](./README.md)。
>
> 本文档只保留本轮复核后的最终结论：
>
> - `supernode` 总数
> - `supernode` 间 `boundary_activation_edges`
> - `grhsim cloned source / compute op` 与 `gsim ref / non-ref enode` 的对比
> - `grhsim compute node` 图与 `gsim graphPartition` 入口 `node/superNode` 图的结构差异

## 1. 复核口径

本次以 2026-05-08 重跑产物为准。

数据来源：

- `gsim`
  - [`../../build/xs/gsim/gsim-compile/model/SimTop_supernode_stats.json`](../../build/xs/gsim/gsim-compile/model/SimTop_supernode_stats.json)
  - [`../../build/xs/gsim/gsim-compile/model/SimTop_0Final_Stats.json`](../../build/xs/gsim/gsim-compile/model/SimTop_0Final_Stats.json)
  - [`../../build/logs/xs/gsim_topology_compare_20260509.log`](../../build/logs/xs/gsim_topology_compare_20260509.log)
- `grhsim`
  - [`../../build/xs/grhsim/grhsim_emit/activity_schedule_supernode_stats.json`](../../build/xs/grhsim/grhsim_emit/activity_schedule_supernode_stats.json)
  - [`../../build/logs/xs/xs_wolf_grhsim_build_20260508_no0076_recheck.log`](../../build/logs/xs/xs_wolf_grhsim_build_20260508_no0076_recheck.log)
  - [`../../build/logs/xs/xs_wolf_grhsim_build_20260509_topology_compare.log`](../../build/logs/xs/xs_wolf_grhsim_build_20260509_topology_compare.log)
  - [`../../build/xs/grhsim/wolvrix_xs_post_stats.json`](../../build/xs/grhsim/wolvrix_xs_post_stats.json)

对齐关系固定为：

- `grhsim cloned source op` 对应 `gsim ref enode`
- `grhsim compute op` 对应 `gsim non-ref enode`

其中：

- `grhsim cloned source op`
  - 取 `activity-schedule timing detail` 中的 `source_clones_in_compute_nodes`
- `grhsim compute op`
  - 按 [`../../wolvrix/lib/transform/activity_schedule.cpp`](../../wolvrix/lib/transform/activity_schedule.cpp) 中 `classifyActivityOp(...)` 口径重算
  - `Source = {kConstant, kRegisterReadPort, kLatchReadPort}`
  - `Sink = {kRegisterWritePort, kLatchWritePort, kMemoryWritePort, kMemoryFillPort}`
  - `Declaration = {kRegister, kMemory, kLatch, kDpicImport}`
  - `Compute = total - Source - Sink - Declaration - HierLike`
- `gsim ref enode`
  - 取 `enode_node_ref_count`
- `gsim non-ref enode`
  - 取 `enode_unique_count - enode_node_ref_count`

## 2. 最终结论

### 2.1 `supernode` 数量

| 指标 | `gsim` | `grhsim` | 差异 |
| --- | ---: | ---: | ---: |
| `supernodes` | `84714` | `84257` | `-457` (`-0.54%`) |

### 2.2 `supernode` 间激活边

| 指标 | `gsim` | `grhsim` | 差异 |
| --- | ---: | ---: | ---: |
| `boundary_activation_edges` | `1378665` | `2346640` | `+967975` (`+70.21%`) |

### 2.3 `ref/non-ref enode` vs `cloned source/compute op`

本次复核后的准确数值：

| 指标 | 数值 |
| --- | ---: |
| `grhsim cloned source ops` | `2234939` |
| `grhsim compute ops` | `4390655` |
| `gsim ref enodes` | `8793011` |
| `gsim non-ref enodes` | `5018941` |

对应比值：

| 对齐项 | `gsim` | `grhsim` | 比值 |
| --- | ---: | ---: | ---: |
| `ref/cloned-source` | `8793011` | `2234939` | `3.93x` |
| `non-ref/compute` | `5018941` | `4390655` | `1.14x` |

### 2.4 `compute node` vs `gsim node` 入口图结构

本节是针对“进入超节点划分流程前”的补充统计。

口径说明：

- `gsim before_coarsen`
  - `graphPartition()` 入口处，每个 `Node` 基本对应一个初始 `SuperNode`
  - 取 [`../../build/logs/xs/gsim_topology_compare_20260509.log`](../../build/logs/xs/gsim_topology_compare_20260509.log) 中 `stage=before_coarsen`
- `grhsim compute_node_dag`
  - `activity-schedule` 建好的 `compute node` DAG
  - 这是 `compute_node_coarsen` 和最终 `compute supernode` 划分之前的图
  - 取 [`../../build/xs/grhsim/grhsim_emit/activity_schedule_supernode_stats.json`](../../build/xs/grhsim/grhsim_emit/activity_schedule_supernode_stats.json) 与 [`../../build/logs/xs/xs_wolf_grhsim_build_20260509_topology_compare.log`](../../build/logs/xs/xs_wolf_grhsim_build_20260509_topology_compare.log)

注意：

- 这里的 `gsim` 统计来自 2026-05-09 的 topology instrumentation，用来补足 2026-05-08 文档没有记录的入口图结构。
- 该 instrumentation 不替换上文 2026-05-08 的最终 supernode / activation 结论。

#### 2.4.1 划分入口图总量

| 指标 | `gsim before_coarsen` | `grhsim compute_node_dag` | `grhsim / gsim` |
| --- | ---: | ---: | ---: |
| nodes | `2708056` | `1349448` | `0.498x` |
| direct DAG edges | `4902042` | `3890740` | `0.794x` |
| weighted/direct edges | `4902042` | `3890740` | `0.794x` |
| avg direct out-degree | `1.810` | `2.883` | `1.593x` |

如果把 `gsim dep_next_edges` 也作为宽口径依赖边：

| 指标 | `gsim before_coarsen dep_next` | `grhsim compute_node_dag` | `grhsim / gsim` |
| --- | ---: | ---: | ---: |
| edges | `5351984` | `3890740` | `0.727x` |
| avg out-degree | `1.976` | `2.883` | `1.459x` |

直接结论：

- `grhsim compute node` 图的节点数不是偏大，而是只有 `gsim graphPartition` 入口节点数的约一半。
- 但边数没有按同等比例下降：
  - 节点数为 `49.8%`
  - direct edge 数仍为 `79.4%`
  - 所以平均出度从 `1.810` 升到 `2.883`
- 这说明问题不只是“compute node 太多”，而是“compute node 被提前合并后，跨 node 依赖仍然保留得过多”，入口图已经呈现更粗、更密的形态。

#### 2.4.2 coarsen 后、初始划分前的中间图

两边 coarsen 之后的结构也不一致：

| 指标 | `gsim after_coarsen` | `grhsim clusters_after_coarsen` | `grhsim / gsim` |
| --- | ---: | ---: | ---: |
| nodes / clusters | `294107` | `1031636` | `3.508x` |
| direct DAG edges | `1168392` | `3396823` | `2.907x` |
| weighted DAG edges | `1352111` (`dep_next`) | `3546564` | `2.623x` |
| avg direct out-degree | `3.973` | `3.293` | `0.829x` |
| avg weighted/dep out-degree | `4.597` | `3.438` | `0.748x` |

这个阶段的形态和入口图相反：

- `gsim graphCoarsen` 很激进：
  - `2708056 -> 294107`，只剩 `10.86%`
  - direct edges `4902042 -> 1168392`，只剩 `23.83%`
- `grhsim compute_node_coarsen` 明显弱很多：
  - `1349448 -> 1031636`，仍剩 `76.45%`
  - direct edges `3890740 -> 3396823`，仍剩 `87.31%`
- 因此进入初始划分时，`grhsim` 中间图比 `gsim after_coarsen` 大很多：
  - node/cluster 数 `3.51x`
  - direct edge 数 `2.91x`

这解释了为什么最终 `supernode` 数量已经接近时，`boundary_activation_edges` 仍然偏大：

- `grhsim` 的入口 compute node 已经更粗、更密；
- 后续 coarsen 又没有像 `gsim graphCoarsen` 那样把大量局部 node 和 edge 吃掉；
- 最终 DP/segment 划分虽然把 supernode 数量压到和 `gsim` 接近，但它面对的是一个中间边集更大的图。

#### 2.4.3 final supernode 图与 activation edge 放大

补充看 final 图的“拓扑边 -> activation edge”放大：

| 指标 | `gsim` | `grhsim` | `grhsim / gsim` |
| --- | ---: | ---: | ---: |
| final supernodes | `84714` | `84257` | `0.995x` |
| final DAG edges | `645829` | `~676010` | `1.047x` |
| boundary activation edges | `1378665` | `~2345057` | `1.701x` |
| boundary activation / DAG edge | `2.135` | `3.469` | `1.625x` |

这里 `grhsim` final DAG 的唯一拓扑边只比 `gsim` 多约 `4.7%`，但 activation edge 多约 `70%`。这说明偏大的主体不只是 unique supernode pair 数，而是同一 supernode pair 上承载了更多 boundary value / activation value。

`grhsim` 自身的 activation 统计也支持这一点：

| 指标 | 数值 |
| --- | ---: |
| `other_compute_activation_edges` | `2318635` |
| `other_compute_unique_supernode_pairs` | `664366` |
| `other_compute_duplicate_activation_edges` | `1654269` |
| duplicate / other_compute_activation | `71.35%` |
| other_compute activation / unique pair | `3.49` |

相比之下，`gsim` final stats 中：

| 指标 | 数值 |
| --- | ---: |
| `boundary_activation_edges` | `1378665` |
| `unique_activation_edges` | `719230` |
| boundary / unique | `1.92` |

所以当前 `grhsim` 的问题可以进一步收窄为：

- final supernode 数量已经不是主因；
- final unique DAG edge 数也不是唯一主因；
- 更关键的是，`compute node` 入口图把多个 boundary value 留在同一跨 supernode pair 上，导致 activation edge multiplicity 明显高于 `gsim`。

#### 2.4.4 对 compute node 形态的判断

从图结构量化看，怀疑是成立的，但要更精确地表述：

1. `grhsim compute node` 不是比 `gsim node` 更细，而是更粗：
   - `1349448` vs `2708056`
   - 约为 `gsim` 入口 node 数的 `49.8%`

2. 它同时更密：
   - direct avg out-degree `2.883` vs `1.810`
   - 即使用 `gsim dep_next` 宽口径对比，`grhsim` 仍是 `1.459x`

3. `grhsim compute_node_coarsen` 相对 `gsim graphCoarsen` 明显不足：
   - `gsim` coarsen 后只剩 `10.86%` 节点
   - `grhsim` coarsen 后仍剩 `76.45%` clusters
   - coarsen 后 `grhsim` clusters 是 `gsim` after_coarsen 的 `3.51x`

4. 最终割边多的直接机制不是 supernode 数量偏多，而是 activation multiplicity 偏高：
   - final supernode 数基本对齐
   - final DAG edge 只多约 `4.7%`
   - boundary activation edge 却多约 `70%`
   - `grhsim other_compute` 中约 `71.35%` 是同一 pair 的 duplicate activation edge

因此，当前最可能的结构性原因是：

- `grhsim compute node` 在构建时把 producer cone 合并得过粗；
- 共享值/边界值没有像 `gsim` 的 `Node + ExpTree/ENode` 结构那样保留足够局部性；
- 后续 coarsen 又未能有效吞掉这些跨 compute-node boundary；
- 最终 supernode 划分虽然数量对齐，却在相同或接近的 supernode pair 上携带了更多 activation values。

## 3. 结论摘要

本轮重跑复核后，最终只保留以下事实：

1. `supernode` 数量已经基本对齐：
   - `gsim = 84714`
   - `grhsim = 84257`

2. `boundary_activation_edges` 仍然显著偏大：
   - `gsim = 1378665`
   - `grhsim = 2346640`

3. 在指定对齐关系下：
   - `grhsim cloned source ops = 2234939`
   - `gsim ref enodes = 8793011`
   - `ref / cloned-source = 3.93x`
   - `grhsim compute ops = 4390655`
   - `gsim non-ref enodes = 5018941`
   - `non-ref / compute = 1.14x`

4. 入口图结构上，`grhsim compute node` 比 `gsim graphPartition` 入口 `node/superNode` 更粗但更密：
   - nodes `1349448` vs `2708056`，只有 `0.498x`
   - direct edges `3890740` vs `4902042`，仍有 `0.794x`
   - avg direct out-degree `2.883` vs `1.810`，为 `1.593x`

5. `grhsim` final 割边偏大更像是 activation multiplicity 问题：
   - final DAG edge 只约 `1.047x`
   - boundary activation edge 却约 `1.701x`
   - `other_compute_duplicate_activation_edges / other_compute_activation_edges = 71.35%`
