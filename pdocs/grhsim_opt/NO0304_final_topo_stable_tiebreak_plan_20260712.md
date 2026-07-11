# NO0304 Final-topo stable tie-break probe plan

日期：2026-07-12

## 1. 背景

承接 [NO0303](./NO0303_ordered_memory_write_affine_post_profile_20260712.md)。NO0300 相对 NO0286 的剩余回退以 compute 为主，且同编号 compute batch 的逻辑内容已经被全局重排。继续检查代码后确认当前放大链路为：

1. activity-schedule 构造 final supernode DAG；
2. `topoOrderForDag()` 按完整 Kahn frontier 分层；
3. 每层仅按临时 `supernodeId` 排序；
4. emitter 直接用 final topo 下标作为 active bit ID；
5. 连续 8 个 active IDs 组成 dispatch word，连续 words 再按 op/估算行数打包为 batch；
6. 同一顺序还参与 materialized value/state 的 locality layout。

`supernodeId` 是 compute partition、DP segment 和 commit packing 完成后按产出顺序重新分配的编号。ordered-write 虽然降低了 supernode/DAG/activation 数量，但也改变了大量后续编号，因此局部图改写可以经层内 tie-break 放大全局代码、bitmap、batch 和 slot 布局变化。

## 2. GSim 对照

`reference/gsim/src/topoSort.cpp` 与 `graphPartition.cpp::resort()` 不采用完整 frontier 分层。它们使用 ready stack，并在 `ORDERED_TOPO_SORT` 下按稳定 `SuperNode::id` 排 successor，然后沿刚释放的依赖继续遍历。两边不能直接等同，但这个对照说明 GSim 不依赖“当前 partition 结果中的连续临时编号 + 全层 barrier”来决定最终代码顺序。

本轮暂不复制 GSim 的 DFS/LIFO 行为，因为那会同时改变跨层顺序和 active-word 聚集形态，无法单独验证 NO0303 的 tie-break 假设。

## 3. Probe 设计

新增默认保持旧行为的 final-topo policy：

- `level-id`：现有行为，按拓扑层、再按 `supernodeId`；
- `level-op`：仍按完全相同的拓扑层，仅将层内 key 改为该 supernode 中最小 `OperationId.index`，最后才用 `supernodeId` 打破相同 key。

`OperationId.index` 对未受局部 rewrite 影响的 operation 保持稳定，适合作为第一版低成本布局 key。该 probe 不允许修改 supernode 成员、DAG、value fanout 或 activation target；它只允许改变 final topo、active ID、batch 和 storage layout。

XiangShan 流程通过 `WOLVRIX_XS_GRHSIM_FINAL_TOPO_POLICY=level-op` 开启，默认仍为 `level-id`。

## 4. 门禁

1. 单测构造同层独立 supernodes，证明 `level-op` 按最小 op ID 排序且结果仍满足全部 DAG 边；默认 `level-id` 结果不变。
2. 同一 graph 的 `level-id/level-op` 必须具有完全一致的 graph ops、supernode、DAG、boundary activation 和 compute/commit pair 统计。
3. fresh 生成 ordered-write disabled/enabled 两组 `level-op`，比较共同 op 的 batch overlap，判断稳定 key 是否降低 NO0303 的跨 batch 混排。
4. ordered-write enabled 的 `level-op` 通过 SimTop 10k/50k difftest 后，固定空闲 CPU 做 `level-id / level-op / level-id` 50k 配对。
5. 若 runtime 未改善则保持默认关闭，并根据结构/profile 决定是否继续 GSim-like ready-stack probe；不得仅凭 overlap 改善将其设为默认。

