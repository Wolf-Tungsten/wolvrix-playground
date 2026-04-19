# NO0008 Activity-Schedule Topo 延后与 Supernode-DP 重构计划（2026-04-19）

本记录用于回答两个问题：

1. 现在 `activity-schedule` 的 `topo` 是否放得过早。
2. `tail` / `sink` special partition 能否完全不依赖 `topo`。

相关背景可参考：

- [`NO0004 GrhSIM Default XiangShan 结构边与 Step 激活统计`](./NO0004_grhsim_default_xiangshan_activation_instrument_20260418.md)
- [`NO0007 GSim / GrhSIM Supernode Edge-Step Tracking Snapshot`](./NO0007_gsim_grhsim_supernode_edge_step_tracking_20260418.md)
- [`activity-schedule tail merge 阶段记录`](../draft/activity-schedule-tail-merge-stage-record-20260419.md)

## 1. 当前判断

结论先写清楚：

- `sink-supernode` 可以基本不依赖“partition 级 topo 排序”。
- `tail-supernode` 不能在当前语义下“完全不依赖 topo”。
- 真正可以后移的，不是 `op` 级 topo，而是 `partition/supernode` 级 topo。
- 因此这次更合理的重构目标是：
  - 保留 `buildActivityOpData()` 的 `op` DAG topo。
  - 把 `canonicalizePartition()` 这类 `supernode` 排序尽量延后到 DP 前。
  - DP 直接面向 `coarse supernode DAG` 做 topo，而不是先把整个 `partition` 改写成 topo 顺序。

## 2. 为什么不能把 topo 全删掉

当前代码里至少有两类 topo，不能混为一谈：

### 2.1 `op` 级 topo

`buildActivityOpData()` 会先把所有可分区 op 做一次 DAG topo，得到：

- `topoOps`
- `topoPosByOpIndex`
- `topoEdges`

这一步不是“为了 DP 先排 supernode”，而是为了给后续所有 partition 阶段提供统一的偏序坐标。

### 2.2 `partition/supernode` 级 topo

`canonicalizePartition()` 会基于当前 cluster DAG 再做一次 topo，把 cluster 重新排成一个线性顺序；`materializeFinalPartition()` 末尾也会再对最终 supernode DAG 做一次 topo。

这里面真正显得“过早”的，是前者反复发生在：

- `sinkPartition`
- `tailPartition`
- `initial partition`
- `coarsen` 每轮 merge 之后
- `DP` 前
- `DP` 后

这些 topo 主要是在维护“当前 `partition.clusters` 的顺序”，而不是在提供新的依赖信息。

## 3. `sink` / `tail` 对 topo 的真实依赖

### 3.1 `sink-supernode`

`sink-supernode` 的语义本质上只是：

- 找出 sink op
- 按稳定顺序分块

它并不依赖 `partition` 已经 topo 化；当前实现只是复用了 `opData.topoOps` 这条稳定序列。

所以：

- `sink` 不需要 `canonicalizePartition()`
- `sink` 也不要求先有 `supernode topo`
- 只要有一条稳定的 op 顺序即可

因此，`sink` 基本可以从“早期 supernode topo”里完全解耦。

### 3.2 `tail-supernode`

`tail-supernode` 当前语义是“从 residual DAG 尾部反向吸收”：

- 如果一个 residual op 只服务一个已存在 `tail-supernode`，就吸进去
- 如果它服务多个 supernode，或没有 residual 后继，就自己成为 seed

这个判断依赖一个关键前提：

- 当处理某个前驱 op 时，它的 residual consumer supernode 状态必须已经稳定

当前实现是用“reverse topo 单遍扫描”来保证这个前提。

如果完全不要 topo，就必须换成另一套机制，例如：

1. 先建立 residual DAG 的出边计数和“consumer-supernode 集合”
2. 从所有 residual leaves 出发做 worklist 归约
3. 当前驱的所有 residual 后继都已归属后，再决定它是吸收还是自成 seed

这本质上仍然是在求一种偏序，只是把“显式 topo”换成“动态 peel / worklist topo”。它不是小改，而是一次算法级重写。

所以我的判断是：

- `sink` 可以做到近乎 topo-free
- `tail` 不能简单做到 topo-free
- 如果硬要把 `tail` 也做成 topo-free，那应该视为 Phase 2 的独立升级，而不是当前 DP 重构的一部分

## 4. 推荐的重构方向

### 4.1 重构目标

本轮先做“延后 partition topo”，不做“彻底去掉 op topo”。

目标是：

- `sink` / `tail` / `initial partition` / `coarsen` 期间，不再频繁改写 `partition.clusters` 的顺序
- DP 前一次性基于当前 coarse partition 建出 `supernode DAG`
- 对这个 `supernode DAG` 做 topo
- DP 直接消费“topo 后的 coarse supernode 视图”
- DP 输出 segment 后再 materialize 最终 supernode

这样可以避免“先 topo，后续 DP 又重新切开”的额外顺序抖动。

### 4.2 核心设计

建议新增一个只服务 DP 的中间视图，例如：

- `DpClusterTopoView`

它至少包含：

- `clusterOrder`
- `orderedMembers`
- `orderedPreds`
- `orderedSuccs`
- `originalClusterIdByTopoIndex`

语义是：

- 原始 `WorkingPartition` 保持本地构造顺序，不强行重排
- `buildClusterView()` 仍然负责从 cluster membership 恢复 DAG
- DP 前新增一步，把 coarse cluster DAG topo 成一个临时视图
- `buildDpSegments()` 和 `refineSegments()` 改为消费这个临时 topo 视图
- `materializeSegments()` 再把 segment 映射回原始 cluster id

这样 `topo` 的目标就直接是“DP 输入 supernode”，而不是提前改写整个 `partition`

## 5. 分阶段计划

### Phase A：把 `partition topo` 从 special partition / coarsen 中抽离

目标：

- 去掉 `sinkPartition = canonicalizePartition(...)`
- 去掉 `tailPartition = canonicalizePartition(...)`
- 去掉 `initial partition` 构建后的立即 topo
- 让 `rebuildPartitionFromDsu()` 不再隐式 `canonicalizePartition(...)`

要求：

- `buildClusterView()`、`tryMergeOut1()`、`tryMergeIn1()`、`tryMergeSiblings()`、`tryMergeForwarders()` 在“cluster 顺序非 topo”时仍然保持语义正确
- 如果某些 merge pass 只是为了稳定日志顺序而依赖 topo，需要把这种依赖改成显式排序，而不是全量 topo

验收点：

- special partition 统计不变
- coarsen 后 cluster 覆盖集合不变
- 不引入新的 cycle

### Phase B：新增 DP 专用的 supernode topo 视图

目标：

- 在 DP 前，只对 `coarse supernode DAG` 做一次 topo
- topo 结果只存在于 DP 输入视图里，不直接改写 `WorkingPartition`

要求：

- 新增 `buildDpClusterTopoView(...)`
- `buildDpSegments()` 改为按 `ordered cluster` 运行
- `refineSegments()` 使用同一套 ordered view
- segment materialize 时保留原始 cluster membership

验收点：

- `dpSupernodeCount`、最终 supernode 数、最终 DAG 边数与重构前同口径对齐
- DP 前后的日志可直接对照同一批 coarse cluster，而不是对照多次重排后的 cluster id

### Phase C：只在最终导出阶段保留 final supernode topo

目标：

- `materializeFinalPartition()` 仍然保留最终 supernode DAG topo
- emitter / export session 继续消费最终 `build.topoOrder`

理由：

- 这一层 topo 是导出调度顺序的正式产物，不应删除
- 真正要减少的是“构造期反复 topo”，不是“结果导出 topo”

验收点：

- `activity_schedule.topo_order` 语义不变
- `grhsim_cpp` emitter 不需要跟着大改

### Phase D：评估是否做“tail topo-free”升级

这一阶段不建议和前 3 个阶段绑在一起。

只有在下面条件满足时，才值得继续：

- Phase A-C 已验证稳定
- DP 重构后仍确认 tail 构建本身是明显热点
- 或者确实需要把 tail 语义升级成更强的 residual-DAG 归约框架

如果继续做，建议方向是：

- 用 worklist / peel 机制替代单次 reverse-topo 扫描
- 明确维护 residual consumer-supernode 集
- 必要时先对 residual 子图做 SCC condensation，再做归约

这属于“算法升级”，不是“顺序调整”。

## 6. 风险判断

主要风险有三个：

1. 当前若干 merge pass 虽然表面只依赖 DAG，但实现上默认了 cluster id 近似 topo 顺序；把早期 topo 拿掉后，可能暴露隐藏顺序依赖。
2. DP 现在默认消费“线性 cluster 序列”；如果只加临时 topo 视图而不把 segment 映射关系设计清楚，很容易在 materialize 阶段把 cluster id 弄乱。
3. 如果把“延后 partition topo”和“tail topo-free 重写”同时做，定位回归会非常困难。

因此建议严格拆成两类改动：

- 当前轮只做“partition topo 延后 + DP 直接面向 supernode topo”
- 后续单独评估“tail topo-free”

## 7. 最终建议

对“`tail` / `sink` 能否完全不依赖 topo”这个问题，我的最终建议是：

- `sink`：可以，应该顺手做掉
- `tail`：理论上可以重写成不显式依赖 topo 的 DAG 归约，但不建议作为当前主线
- 当前最值得做的升级，是把“早期 repeated partition topo”收缩为“DP 前一次 coarse-supernode topo + 导出前一次 final-supernode topo”

也就是说，优先级应当是：

1. 保留 `op` topo
2. 去掉构造期反复 `canonicalizePartition()`
3. DP 前直接 topo `coarse supernode`
4. 以后再考虑 `tail topo-free`

这条路径改动边界更清晰，也更符合你提出的“让 topo 直接服务 DP，而不是让 DP 迁就早期 topo”的目标。

## 增量更新（2026-04-19）

本轮讨论后，这个议题的方向已经确认，后续实现以此为准：

- 保留前面的 `op topo`
  - 即继续保留 `buildActivityOpData()` 产出的 `topoOps / topoPosByOpIndex / topoEdges`
- 不再让后续 `partition` 在多个阶段反复 `canonicalizePartition()`
- 后面的 `supernode topo` 单独服务 DP
  - 在 DP 前基于 `coarse supernode DAG` 构造一次临时 topo 视图
  - `buildDpSegments()` / `refineSegments()` 只消费这份视图
  - 不用这一步 topo 去改写整个 `WorkingPartition`
- 最终导出阶段仍保留 final supernode topo
  - 继续用于 `activity_schedule.topo_order` 和 emitter 调度顺序

一句话收口就是：

- 前面的 topo 保留给 `op` 级依赖坐标
- 后面的 topo 收缩为“只给 DP 和最终导出服务的 supernode topo”

## 增量更新（2026-04-19，代码已落地）

当前代码已经按上面的主线完成第一轮重构，落地点在：

- `wolvrix/lib/transform/activity_schedule.cpp`

本轮实际改动为：

- 保留 `buildActivityOpData()` 的 `op topo`
- 去掉构造期几处早期 `canonicalizePartition()`
  - `sinkPartition`
  - `tailPartition`
  - `initial partition`
  - `DP` 前的 `partition`
  - `DP` 后 materialize 完的 `partition`
- `rebuildPartitionFromDsu()` 不再在 merge 之后隐式 topo 化
- 新增一个只服务 DP 的临时 topo 视图
  - 先基于 coarse partition 建 `ClusterView`
  - 再构造 topo-ordered cluster view
  - `buildDpSegments()` / `refineSegments()` 改为消费这份视图
  - `materializeSegments()` 也直接基于这份 DP 视图回收最终分段
- final materialize/export 阶段的 final supernode topo 保持不变

这意味着当前代码已经满足本议题确认过的目标：

- 前面的 `op topo` 保留
- 后面的 `supernode topo` 单独服务 DP
- 最终导出阶段继续保留正式 supernode topo

本轮已通过聚焦验证：

```bash
cmake --build wolvrix/build -j4 --target transform-activity-schedule emit-grhsim-cpp
ctest --test-dir wolvrix/build --output-on-failure -R '^(transform-activity-schedule|emit-grhsim-cpp)$'
```

结果：

- `emit-grhsim-cpp`：Passed
- `transform-activity-schedule`：Passed
