# activity-schedule sink / dom-sink 粗化升级计划

## 1. 目标

这次改造的目标不是继续单纯调大 `supernode-max-size`，而是先把靠近 side-effect sink 的组合锥预先糙化，减少：

- 重复激活
- 跨 supernode 激活传播
- sink 附近大量细碎 supernode 带来的调度开销

需求收敛为四点：

1. 先把 `sink op` 聚成 `sink-supernode`，其 op 数上限不再使用当前 `max-supernode-op`，而是引入新的 `max-sink-supernode-op`。
2. 再识别那些结果直接输入到 `sink-supernode` 的 op，称为 `dom-sink-op`；以每个 `dom-sink-op` 为独立种子，递归吸收“结果只给这个种子链使用”的独立前驱 op，形成 `dom-sink-supernode`，其 op 数上限使用新的 `max-dom-sink-supernode-op`。
3. 上述两步完成后，剩余 op 再走现有 coarsen + DP + refine 策略，后续合并仍受 `max-supernode-op` 约束。
4. 移除当前 replication 之后对过大 cluster 的强制拆分逻辑。

## 2. 当前实现与问题

当前 `activity-schedule` 主流程位于：

- `wolvrix/lib/transform/activity_schedule.cpp`
- `wolvrix/include/transform/activity_schedule.hpp`
- `wolvrix/lib/core/transform.cpp`

当前关键流程是：

1. `buildActivityOpData()`
2. `collectTailSinkTopoPositions()`
3. 对非 sink op 建 seed partition
4. 对非 sink 部分做 coarsen
5. 对非 sink 部分做 DP / refine
6. `appendTailSinkClusters(partition, tailSinkTopoPositions, options_.supernodeMaxSize)`
7. replication
8. `splitOversizedSymbolClusters(..., options_.supernodeMaxSize, ...)`
9. final materialize

现状有两个直接问题：

### 2.1 sink 预聚合已经存在，但仍然被普通阈值卡住

当前 `appendTailSinkClusters(...)` 本质上已经在做“把 tail sink 单独收起来再拼 cluster”，但它仍然用的是 `options_.supernodeMaxSize`。

这导致：

- sink-supernode 不能明显做大
- sink 附近仍然保留大量跨 supernode 边
- 为了保护普通 supernode 编译体量而设置的小阈值，也错误限制了 sink 粗化

### 2.2 replication 后强拆会破坏前面刻意做大的 cluster

当前 `splitOversizedSymbolClusters(...)` 会在 replication 后按 topo chunk 强制把超出 `supernodeMaxSize` 的 cluster 再切开。

这与本次目标直接冲突：

- 即使前面特意把 sink / dom-sink 区域做大
- replication 后仍可能被这一步重新打碎

所以这段逻辑必须整体移除，而不是继续补更多例外分支。

## 3. 新算法定义

### 3.1 sink-op

沿用当前 `isTailSinkOp(...)` 的判定范围：

- `kRegisterWritePort`
- `kLatchWritePort`
- `kMemoryWritePort`
- 无返回值的 `kSystemTask`
- 无返回 effect value 的 `kDpicCall`

这部分本次不改语义。

### 3.2 sink-supernode

定义：

- 将所有 `sink-op` 从普通 partition 流程中先摘出来
- 按 topo 顺序切成若干组
- 每组形成一个 `sink-supernode`

约束：

- 每个 `sink-supernode` 的 op 数上限使用 `max-sink-supernode-op`
- 不再使用 `supernode-max-size`

这里建议先复用当前 `appendTailSinkClusters(...)` 的“按 topo 顺序分块”语义，只把它前移成显式的初始阶段，并改用新阈值。

原因：

- 这是对现有实现侵入最小的升级
- 它已经符合“将 sink op 合成一组 sink-supernode”的需求方向
- 真正新增的核心复杂度应放在 `dom-sink-supernode`，而不是重新发明 sink 组内 cost model

### 3.3 dom-sink-op

定义：

- 某个非 sink op，如果它的结果被某个 `sink-supernode` 内的 op 直接消费，则该 op 为 `dom-sink-op`

更精确地说：

- 枚举 `sink-supernode` 内所有 op 的 operand
- 找到 operand 的 defining op
- 若 defining op 可分区、且不在 sink 集合内，则该 defining op 是 `dom-sink-op`

去重粒度：

- 按 op 去重
- 同一个 op 即使直接馈入多个 sink-supernode，也只作为一个 `dom-sink-op` 种子

### 3.4 dom-sink-supernode

定义：

- 以每个 `dom-sink-op` 为一个独立种子
- 递归向前吸收其“独立前驱 op”
- 所得 op 集合形成一个 `dom-sink-supernode`

这里“独立前驱 op”的判定建议明确为：

- 对候选前驱 op `pred`
- 若 `pred` 的所有可分区结果的所有可分区 users，都已经落在当前种子闭包内
- 则 `pred` 可以被吸收

也就是：

- 只吸收真正只服务于当前 `dom-sink` 链的前驱
- 任何被其它普通区域、其它 `dom-sink` 链、或其它 sink 链共享的 op，都不吸收

约束：

- 每个 `dom-sink-supernode` 的 op 数上限使用 `max-dom-sink-supernode-op`
- 不再使用 `supernode-max-size`

语义上要保证：

- 一个 `dom-sink-op` 只属于一个 `dom-sink-supernode`
- 已被 sink-supernode 覆盖的 op 不再参与 dom-sink 构造
- 已被一个 dom-sink-supernode 吸收的 op，不再被其它 dom-sink-supernode 重复吸收

## 4. 新的整体流程

建议把 `activity-schedule` 主流程改成下面这条线：

1. `buildActivityOpData()`
2. 识别 `sink-op`
3. 按 `max-sink-supernode-op` 构造 `sink-supernode`
4. 基于 `sink-supernode` 识别 `dom-sink-op`
5. 按 `max-dom-sink-supernode-op` 构造 `dom-sink-supernode`
6. 计算剩余普通 op 集合
7. 仅对剩余普通 op 建 seed partition
8. 仅对剩余普通 op 做 coarsen
9. 仅对剩余普通 op 做 DP / refine / materialize
10. 将普通 supernode + dom-sink-supernode + sink-supernode 合并为最终 pre-replication partition
11. `buildSymbolPartition()`
12. replication
13. 直接进入 final materialize

明确移除：

- `splitOversizedSymbolClusters(...)`

也就是说，新的结构里：

- sink / dom-sink 两类 special supernode 是“先做粗化，再让普通策略处理剩余图”
- 而不是“普通策略先跑完，最后再把 sink 补挂上去”

## 5. 需要落地的代码改动

### 5.1 选项与 CLI

新增配置项：

- `ActivityScheduleOptions::maxSinkSupernodeOp`
- `ActivityScheduleOptions::maxDomSinkSupernodeOp`

对应 CLI 选项建议新增：

- `-max-sink-supernode-op`
- `-max-dom-sink-supernode-op`

涉及文件：

- `wolvrix/include/transform/activity_schedule.hpp`
- `wolvrix/lib/core/transform.cpp`
- `wolvrix/docs/transform/activity-schedule.md`

默认值建议：

- 代码默认先回退到 `supernodeMaxSize`
- XiangShan / GrhSIM 实际流程里再显式传入更大的值

这样做的原因是：

- 不会悄悄改变现有所有调用方的行为
- 同时可以在目标 workload 上逐步把 sink / dom-sink 阈值放大

如果后续确认默认行为就应切到“大阈值模式”，再单独改默认值，不建议在这一版里同时做语义和调参双重变更。

### 5.2 初始 special cluster 构造

建议新增几组 helper，集中替换当前“尾部 sink 追加”的做法：

- `collectSinkTopoPositions(...)`
- `buildSinkSupernodePartition(...)`
- `collectDomSinkSeeds(...)`
- `buildDomSinkSupernodePartition(...)`
- `buildResidualTopoMask(...)`

实现原则：

- sink / dom-sink 两类 special cluster 先各自生成
- 普通区只看 residual mask
- 普通区继续复用现有 `makeSeedPartition()` / `tryMerge*()` / `buildDpSegments()` / `refineSegments()` / `materializeSegments()`

这样可以避免：

- 大改现有 DP / refine 逻辑
- 在 coarsen 阶段混入大量 special case

### 5.3 dom-sink 吸收规则

建议新增一套 user 查询辅助结构，避免在递归吸收时反复扫图：

- `value -> users`
- `op -> external partitionable users count`
- 或者直接缓存 `op -> downstream partitionable user ops`

判定某个前驱能否吸收时，只看“它的结果是否只给当前闭包用”：

- 若存在任何一个 partitionable user 不在当前闭包内，则不能吸收
- 若某个结果无 user，也可以吸收
- 非 partitionable user 不参与 dom-sink 独占性判断

这套规则要写清楚并固化到测试里，否则后面很容易把“只给它用”做成模糊语义。

### 5.4 删除 replication 后强拆

建议直接删除：

- `splitOversizedSymbolClusters(...)`
- 主流程中的 `postReplicationSplitMs`
- `postReplicationOversizedClusters`
- `postReplicationAddedClusters`
- summary / timing 中与 `replication split` 相关的统计

这是本次改动必须做的语义收口，不建议保留开关。

如果后续还需要“保护编译单元不被打爆”的兜底机制，应另起一套显式策略，而不是继续借用 `supernodeMaxSize` 在 replication 后做无差别强拆。

### 5.5 日志与统计

建议新增 summary 统计项：

- `sink_supernodes`
- `sink_ops`
- `dom_sink_supernodes`
- `dom_sink_seed_ops`
- `dom_sink_absorbed_ops`
- `normal_seed_supernodes`

这样才能判断这次升级到底有没有把 sink 附近的边界真正收进去。

## 6. 测试计划

测试至少补以下几类，位置：

- `wolvrix/tests/transform/test_activity_schedule_pass.cpp`

### 6.1 sink-supernode 大阈值不受普通阈值限制

构造：

- 多个 `RegisterWritePort` / `SystemTask` / `DpicCall`
- `supernodeMaxSize` 设很小
- `maxSinkSupernodeOp` 设较大

验证：

- sink op 会被聚成更大的 sink-supernode
- 普通 supernode 仍受 `supernodeMaxSize` 约束

### 6.2 dom-sink-op 吸收独占前驱

构造一条：

- `pred0 -> pred1 -> domSink -> sink`

其中 `pred0/pred1` 只服务于这条链。

验证：

- `pred0/pred1/domSink` 落在同一个 `dom-sink-supernode`
- sink 落在对应 `sink-supernode`

### 6.3 共享前驱不能被 dom-sink 吸收

构造：

- `shared -> domSinkA -> sinkA`
- `shared -> normalUse`

验证：

- `shared` 不能被并入 `dom-sink-supernode`
- 只允许 `domSinkA` 自身或其独占链被吸收

### 6.4 多个 dom-sink 种子保持独立

构造：

- `predA -> domA -> sink`
- `predB -> domB -> sink`

验证：

- `domA` 与 `domB` 各自成为独立种子
- 不会在 dom-sink 阶段互相并并

### 6.5 replication 后不再强拆

构造一个 replication 会放大目标 cluster 的用例。

验证：

- pass 结束后不再出现“超限后再 topo chunk 拆分”的行为
- 输出 supernode 的 op 数允许超过 `supernodeMaxSize`

这一条非常关键，因为它直接对应第 4 条需求。

## 7. 验收口径

这次改造完成后，应按下面的口径验收，而不是只看总 supernode 数：

1. sink 附近的跨 supernode value fanout 是否下降。
2. sink / dom-sink 区域的 supernode 数是否显著下降。
3. 普通区域的 supernode 仍然受 `supernodeMaxSize` 约束。
4. replication 后不会再把大 sink cluster 强拆回去。
5. 生成 C++ 体量没有出现无法接受的回退。

其中第 5 条不能再靠 `splitOversizedSymbolClusters()` 兜底，而要靠：

- `max-sink-supernode-op`
- `max-dom-sink-supernode-op`

这两个显式阈值控制。

## 8. 风险与开放项

### 8.1 dom-sink 的“只给它用”必须以 partitionable user 为准

如果把非 partitionable user 也算进去，很多本来应吸收的前驱会被误判成共享节点。

所以这里必须明确：

- dom-sink 吸收规则只看 partitionable user

### 8.2 replication 仍可能继续放大 special supernode

移除 post-replication 强拆后，最终 supernode op 数不再是 `supernodeMaxSize` 的硬上限。

这不是 bug，而是本次改动的目标之一。

但它带来的工程约束是：

- `max-sink-supernode-op`
- `max-dom-sink-supernode-op`

需要按实际编译单元承载能力调参，而不能无限放大。

### 8.3 第一版不建议同时重写 sink 内部 cost model

当前最重要的是把 special cluster 的阶段顺序和边界语义做对。

因此第一版建议：

- sink-supernode 继续按 topo chunk
- dom-sink-supernode 才引入新的“独占前驱吸收”逻辑

这样可以把风险集中在真正有收益的新部分。

## 9. 建议实施顺序

建议分三步落地：

1. 先加新参数与新流程骨架，完成 `sink-supernode` 前移，并删除 replication 后强拆。
2. 再实现 `dom-sink-op` 识别与独占前驱吸收。
3. 最后补日志、测试、脚本文档，并在 XiangShan 流程上调新阈值。

这样切分的原因是：

- 第一步就能先把“special cluster 不再受普通阈值 + 不再被后置强拆”这两个方向立住。
- 第二步再把真正的收益点 `dom-sink-supernode` 加进去。
- 第三步再做 workload 级调参与数据复核。
