# NO0088 Value-Guided Activity Schedule Experiments

记录日期：2026-05-11

## 背景

`NO0087` 确认 GrhSIM 与 GSim 的关键差异之一是调度粒度：GSim 的 Node 更接近 GrhSIM 的 declared/value 聚合单元，而 GrhSIM 当前把更多细粒度 value/op 暴露到 compute-node 与 activation 边界。

本轮实现并实测两类参数化改造：

- compute node 建树增加 value / declared-value budget。
- compute supernode 分段增加 value budget 或 target compute-supernode 数。

所有 XS 实验均从现有 `build/xs/grhsim/wolvrix_xs_post_stats.json` resume，没有重新读 SV。

## Baseline

对照基线使用 `NO0087` 当前 GrhSIM 数据：

| 指标 | Baseline |
| --- | ---: |
| supernodes | 85885 |
| compute_supernodes | 79801 |
| commit_supernodes | 6084 |
| dag_edges | 743311 |
| boundary_values | 1241969 |
| boundary_activation_edges | 2545743 |
| compute_nodes | 1380259 |
| compute_node_boundary_values | 4280434 |

## 实验 A：supernode value target

命令参数：

```text
RUN_ID=20260511_no0088_value_sched_a
XS_WOLF_GRHSIM_RESUME_FROM_STATS_JSON=1
XS_WOLF_GRHSIM_MAX_COMPUTE_NODE_IN_COMPUTE_SUPERNODE=18
XS_WOLF_GRHSIM_TARGET_COMPUTE_SUPERNODES=78630
XS_WOLF_GRHSIM_MAX_VALUE_IN_COMPUTE_NODE=0
XS_WOLF_GRHSIM_MAX_DECLARED_VALUE_IN_COMPUTE_NODE=0
```

结果：

| 指标 | A |
| --- | ---: |
| supernodes | 112440 |
| compute_supernodes | 106356 |
| commit_supernodes | 6084 |
| dag_edges | 1100581 |
| boundary_values | 1262423 |
| boundary_activation_edges | 3008989 |
| compute_compute_value_pairs | 2626743 |
| compute_commit_value_pairs | 382246 |
| compute_nodes | 1380259 |
| compute_node_boundary_values | 4280434 |

结论：失败。value target 在当前 cluster 粒度下变成切碎 supernode 的硬约束，compute_supernodes 从 79801 增到 106356，boundary_activation_edges 反而上升到 3008989。

## 实验 B：compute node value / declared-value budget

命令参数：

```text
RUN_ID=20260511_no0088_value_sched_b
XS_WOLF_GRHSIM_RESUME_FROM_STATS_JSON=1
XS_WOLF_GRHSIM_MAX_COMPUTE_NODE_IN_COMPUTE_SUPERNODE=18
XS_WOLF_GRHSIM_TARGET_COMPUTE_SUPERNODES=0
XS_WOLF_GRHSIM_MAX_VALUE_IN_COMPUTE_SUPERNODE=0
XS_WOLF_GRHSIM_MAX_VALUE_IN_COMPUTE_NODE=96
XS_WOLF_GRHSIM_MAX_DECLARED_VALUE_IN_COMPUTE_NODE=8
```

结果：

| 指标 | B |
| --- | ---: |
| supernodes | 98521 |
| compute_supernodes | 92437 |
| commit_supernodes | 6084 |
| dag_edges | 859790 |
| boundary_values | 1408614 |
| boundary_activation_edges | 2830557 |
| compute_compute_value_pairs | 2448311 |
| compute_commit_value_pairs | 382246 |
| compute_nodes | 1599378 |
| compute_node_boundary_values | 4600016 |

结论：失败。compute-node value cap 会阻止反向吸收，compute_nodes 从 1380259 增到 1599378，并引入更多 boundary/capacity spill，最终 activation 也变差。

## 实验 C：朴素 value-local ordering

尝试在 topo ready 集合中优先选择前一个 cluster 的后继，以增强 value locality。

命令参数：

```text
RUN_ID=20260511_no0088_value_sched_c_order
XS_WOLF_GRHSIM_RESUME_FROM_STATS_JSON=1
XS_WOLF_GRHSIM_MAX_COMPUTE_NODE_IN_COMPUTE_SUPERNODE=18
XS_WOLF_GRHSIM_TOPO_ORDER_MODEL=value-local
```

结果：失败并中断。该实现每次选择都扫描 ready 集合，百万级 cluster 上复杂度不可接受，运行约 10 分钟仍停在 `activity-schedule`，最终手动终止，未生成有效 stats。

## 当前保留与撤回

保留代码：

- `max_value_in_compute_node`
- `max_declared_value_in_compute_node`
- `max_value_in_compute_supernode`
- `target_compute_supernodes`

这些参数默认均为 `0`，因此默认行为回到旧路径。保留它们的目的只是让后续能快速复现实验或做小图验证。

撤回/禁用：

- 朴素 `value-local` topo ordering 实现已经移除。
- `topo_order_model` 当前只接受 `layer`。

## 结论

本轮没有找到有效方案。关键负结果是：

- value 数量不能直接作为硬 cap；它会切碎 compute node / supernode，造成更多跨边界 value。
- declared symbol value 对 compute node 建树有表达意义，但简单阈值不是优化目标函数。
- ordering 方向仍可能合理，但必须是线性或近线性的局部启发，不能在百万级 ready 集合上全扫描。

下一步应转向“保持 supernode 数量不变的局部交换/窗口重排”，只允许在固定 topo 窗口内改善 boundary value cut，并以 `boundary_activation_edges` 和 50k runtime 双指标验收。
