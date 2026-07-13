# NO0524 Event-pure active-id packing audit plan

日期：2026-07-13

## 1. Motivation and current coverage

承接 [NO0523](./NO0523_sparse_pure_event_runtime_load_gate_snapshot_20260713.md)，在 runtime load gate 等待期间审计一个不依赖
wall time 的后续方向。NO0479/NO0483 的 source-backed 分类为：

```text
event-pure supernodes                         1,611
current pure-event words / nodes / samples  107 / 856 / 125
event/non-event mixed groups/nodes/samples  246 / 749 / 182
multi-event mixed groups/nodes/samples         2 /   6 /   1
```

若只按 `(batch, exact-event)` 无约束装箱，50 个 event keys 最多形成 `181` 个 full 8-node words，覆盖 `1,448` 个节点，
相对当前最多新增 `74` words / `592` nodes，剩余 `163` nodes。这个数字只是理论上界，不是实现候选。

## 2. Correctness constraint

当前 emitter 将 `activeIdBySupernode[supernode]` 直接设为 final topo index；`buildScheduleBatches()` 又按 topo order 扫描，
并假定相同 active-word index 连续。active IDs 同时进入 boundary/input/state activation masks。因此不能独立置换 active IDs，也不能
把 event-pure 节点跨依赖任意搬动，否则会破坏单轮 topo evaluation、word clear/restore 和 batch grouping。

首个合法候选只能是等价 final topo reorder：

- 只交换 DAG 上不可达、处于同一合法 frontier/level 的 compute supernodes；
- 重新生成一致的 active IDs、fanout masks、active words 与 batch source；
- 保持每条 DAG edge 的 source topo index 小于 destination；
- commit phase、state read sets 与 graph/supernode partition 完全不变。

## 3. Audit stages

1. 用现有 TSV 精确重算 current coverage 与 per `(batch,event)` unconstrained min/max sample coverage；
2. 统计 event-pure 节点在 topo index 上的 run、word-boundary fragmentation，以及每个 batch 需要跨越多少 non-event nodes；
3. 若无约束收益达到 direct samples 1%，再导出或重建 final supernode DAG level，模拟只在同 level 内 stable partition 的合法 packing；
4. 记录 legal full words、新增覆盖、被 level/batch/event/partial-word 各自阻挡的节点；
5. 只有 legal packing 仍新增至少 `67/6,675` direct samples，且 active-word 数、batch count、max ops/lines 不增，才进入默认
   关闭的 topo reorder implementation plan。

## 4. Stop conditions

以下任一成立即停止，不修改生产 emitter：

- 主要收益需要跨 DAG level 或跨 batch 搬动；
- legal 新增 sample coverage 小于 direct 1%；
- 为形成 pure words需要增加 active words/batches，或破坏 current level-id deterministic order；
- full words 增加但代表 O3 object 的 text/instructions/memory/jumps 不能同时不差于当前 hybrid。

本篇只声明审计计划。分析产物放在 `build/logs/xs_perf/no0524/`，已有 NO0479/NO0483 文件只读复用、不覆盖。
