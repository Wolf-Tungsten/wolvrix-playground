# NO0034 Sink Activation Event-Delta Narrowing Plan 20260427

> 归档编号：`NO0034`。目录顺序见 [`README.md`](./README.md)。

这份文档细化一个新的 `grhsim` 运行时优化方向：对 `sink supernode` 的“进入 commit 前激活”做更窄的触发条件。核心结论是：

- 对 `kRegisterWritePort`
- 对 `kMemoryWritePort`

不再沿用“任一相关 operand 变化都激活 sink”的宽口径传播，而是只跟踪它们那些 `event` 信号的变动，再决定是否把对应 sink supernode 置 active。

这件事和 [`NO0029`](./NO0029_sink_supernode_event_cluster_plan_20260424.md) 互补：

- `NO0029` 优化的是 “sink 已经要跑了以后，代码块内部如何按 event guard 聚类”
- 本文优化的是 “sink 到底什么时候值得被激活”

它也建立在 [`NO0033`](./NO0033_activity_schedule_simplification_plan_20260427.md) 之后的当前前提上：

- `sink-supernode` 现在只保留本地 state write
- `SystemTask` / `DpicCall` 已不再进入 `sink`

因此，这轮可以更激进地把 `sink` 的激活条件直接收窄到 write 自身的时序语义。

## 1. 当前现状

当前 `grhsim_cpp` emitter 里，和这件事相关的机制已经有三层：

1. `activity-schedule` 把 `kRegisterWritePort` / `kLatchWritePort` / `kMemoryWritePort` 归入 `commit phase`
2. `emitChangedValueEffects(...)` 在某个 tracked value 发生变化时：
   - 先更新该 value 对应的 `event_edge_slots_[...]`，如果它本身是 event sample
   - 再通过 `boundaryFanoutByValue` 把所有下游 supernode 标成 active
3. `commit` supernode 真正执行时，又会用 `exactEventExpr(...)` 做一次精确 event guard 判断

相关代码位置：

- [`emitChangedValueEffects(...)`](../../wolvrix/lib/emit/grhsim_cpp.cpp)
- [`exactEventExpr(...)`](../../wolvrix/lib/emit/grhsim_cpp.cpp)
- `eval()` 里的 changed-input seed 与 `event_edge_slots_` 初始化：
  - [`grhsim_cpp.cpp`](../../wolvrix/lib/emit/grhsim_cpp.cpp)

这意味着当前模型其实是：

- 激活阶段：宽口径
- commit 执行阶段：窄口径

也就是先把很多 sink supernode 激活起来，再在 commit 内层发现 `eventExpr == false`，然后什么都不做。

## 2. 当前浪费点

### 2.1 典型冗余

对一个 `always_ff @(posedge clk)` 产生的 `kRegisterWritePort`，当前 sink 激活可能来自：

- `clk` 变化
- `updateCond` 变化
- `nextValue` 变化
- `mask` 变化
- 这些值上游任意组合值变化继续层层传下来的 fanout

但真正会让这条 write 在本轮 commit 中“有资格执行”的必要条件，其实只有：

- `clk` 对应的 event sample 发生变化
- 并且 `exactEventExpr` 命中要求的 edge kind

如果只是：

- 数据总线在时钟低电平期间频繁抖动
- `updateCond` 变化，但对应时钟边沿没有来
- memory write 的 `addr/data/mask` 在非 event 时刻变化

那么这条 sink write 被激活、被扫描、被进入 commit batch，最终都只是跑到：

```cpp
if (eventExpr) {
    ...
}
```

然后直接跳过。

### 2.2 成本落点

这类过宽激活至少会放大三类成本：

- `supernode_active_curr_[word] |= mask` 的重复设置
- commit batch 的 active-word 扫描与 helper 分发
- sink supernode 内层 guard 判断的空转次数

其中第一类尤其直接，因为当前 `emitChangedValuePropagation(...)` 是按 value fanout 把 active mask 打到 `supernode_active_curr_` 上的；只要数据路径上有变化，就会重复把 sink 置 active。

## 3. 关键观察

### 3.1 `kRegisterWritePort` / `kMemoryWritePort` 是 event-driven sink

对这两类 op：

- 它们没有结果值，不参与后续组合值传播
- 它们的唯一外部效果是 commit 时修改可见 state
- 它们是否“本轮应该被执行”，本质由 `eventEdge` 语义决定

当前 emitter 已经把这层语义显式编码成：

- `event_edge_slots_[...]`
- `grhsim_event_edge_kind::{none, posedge, negedge}`
- `exactEventExpr(...)`

因此，运行时其实已经知道：

- 哪些值是 event sample
- 当前 round 这些 sample 是否发生 edge
- 是 `posedge` 还是 `negedge`

缺的不是判定能力，而是“把这层信息提前用于 sink 激活”。

### 3.2 数据/地址/掩码变化本身不应驱动 sink 激活

对 event-driven write 来说：

- `cond`
- `data`
- `addr`
- `mask`

都应该被看作“event 到来时被采样的当前值”，而不是“单独足以触发 commit 调度的信号”。

只要 commit 阶段运行时读取的是这些值在当前 round 计算后的最新 materialized storage，那么：

- 没有 event 时，数据再怎么变化都不需要跑 sink
- 有 event 时，只要 sink 因 event 被激活一次，就能读到当前最新的 `cond/data/addr/mask`

这正是这轮优化成立的根本原因。

## 4. 语义边界

### 4.1 哪些 op 可以收窄

本轮建议只对下面两类 op 启用 event-delta sink activation：

| OperationKind | 是否纳入本方案 | 原因 |
| --- | --- | --- |
| `kRegisterWritePort` | 是 | 标准 edge-driven state write |
| `kMemoryWritePort` | 是 | 同样由 event 驱动，且 sink 空转开销更大 |
| `kLatchWritePort` | 否 | latch 是 level-sensitive，不应仅靠 event 变化激活 |

### 4.2 为什么暂时排除 `kLatchWritePort`

`kLatchWritePort` 虽然也在 `commit phase`，但它的语义不同：

- 它更像“条件成立时就应反映到 state”
- 不是严格的 edge-triggered write

因此不能简单收窄成“只看 event sample 的变化”。

本轮如果把 latch 也一起收窄，极容易漏掉“enable 保持为 1，但 data 变化仍需更新 latch”的场景。

### 4.3 允许的 false positive

这轮优化允许少量 false positive，但不能接受 false negative。

也就是说：

- 某个 sink 因 event sample 变化被激活了
- 但最终 `exactEventExpr(...)` 不命中

这是允许的，因为只是空转一次 commit guard。

但不能发生：

- 某个 write 实际应当执行
- 却因为 sink 没被激活而完全没进入 commit

因此实现上必须确保：

- 只要某条 `kRegisterWritePort` / `kMemoryWritePort` 的 `exactEventExpr` 可能命中，它所在 sink supernode 一定会被 event 相关索引覆盖到

## 5. 目标模型

### 5.1 一句话版本

把：

- `value change -> boundaryFanoutByValue -> sink active`

改成：

- `event sample delta -> event-trigger index -> sink active`

普通 compute supernode 以及 `kLatchWritePort` 仍保留现有 value-change 传播。

### 5.2 推荐触发粒度

建议直接按“event edge slot + edge kind”建索引，而不是只按“原始 event value 变了没”建索引。

原因：

- emitter 已经有 `event_edge_slots_[slot]`
- `exactEventExpr(...)` 已经区分：
  - `!= none`
  - `== posedge`
  - `== negedge`
- 直接复用 edge-kind 可以进一步减少无意义激活

建议的触发键：

```text
EventTriggerKey {
  slot_id,
  required_edge_kind   // any-change / posedge / negedge
}
```

其中：

- 如果 write guard 对某个 sample 只要求“任意边沿”，就用 `any-change`
- 如果明确要求 `posedge` 或 `negedge`，就按精确 edge kind 建索引

### 5.3 对 OR-event 的处理

如果某条 write 的 guard 是：

```text
posedge(a) || negedge(b)
```

则它应当在两个 trigger key 下都被索引到：

- `(slot(a), posedge)`
- `(slot(b), negedge)`

这样任一 trigger 命中时，都能把该 sink supernode 激活一次。

## 6. 对当前 emitter 的具体改造点

### 6.1 新增 event-driven sink 分类

在 emit model 构建阶段，为每个 `commit supernode` 做一次分类：

- `pure_event_driven_commit`
- `mixed_or_level_sensitive_commit`

判定建议：

1. supernode 中所有 commit op 都必须是 `kRegisterWritePort` 或 `kMemoryWritePort`
2. 每个 op 的 `eventEdge` 都必须能被规范化提取
3. supernode 内不混入 `kLatchWritePort`

只有满足上述条件的 supernode，才启用 event-delta 激活收窄。

### 6.2 新增 reverse index

建议在 `EmitModel` 中新增一组索引，名字可以类似：

```text
eventTriggeredCommitHeadsBySlotAndEdge
eventTriggeredInputHeadsByValue
```

推荐更直接的形态是：

```text
event_trigger_to_active_ids:
  (slot_id, any-change) -> [active_id...]
  (slot_id, posedge)    -> [active_id...]
  (slot_id, negedge)    -> [active_id...]
```

并且同步生成压缩好的 `ActiveMaskEntry`，避免运行时再临时聚合。

### 6.3 从 generic fanout 里剔除 event-driven sink

当前 `boundaryFanoutByValue` 是从 `schedule.valueFanout` 直接转成 `activeId` 列表的，天然会把 sink 也包含进去。

本轮建议：

- 对纯 event-driven commit supernode：
  - 不再让它们通过普通 `boundaryFanoutByValue` 被数据值变化激活
- 对 compute supernode 和含 latch 的 commit supernode：
  - 保持现有 `boundaryFanoutByValue` 逻辑不变

也就是说，最终要把 sink 激活路径分成两条：

1. `generic value fanout`
2. `event-triggered commit fanout`

### 6.4 输入 seed 也要同步收窄

当前 `inputHeadSupernodesByValue` 是按“某个 supernode 直接读取了该 input operand”构建的，因此 event-driven sink 也会被输入数据变化直接 seed。

本轮建议同步调整：

- 对纯 event-driven commit supernode：
  - 不再从 `inputHeadSupernodesByValue` 里直接 seed
- 只在对应 input 参与的 event slot 产生 edge 时，再通过 event-trigger index 去 seed

否则即使删掉了 `boundaryFanoutByValue` 里的 sink fanout，changed-input 入口仍会把它们重新激活回来，收益会被吃掉一大块。

### 6.5 commit 内 guard 逻辑保持不变

这轮优化只改变“进入 commit 之前是否置 active”，不改变 commit 内的精确语义。

也就是说，下面这些都应保持不变：

- `exactEventExpr(...)`
- `truthyLogicValueExpr(...)` 对 `updateCond` 的判断
- `emitWritePortBody(...)` 对实际 state write / reader reactivation 的逻辑

这样可以把语义风险压到最低：

- 运行体不变
- 只改外层调度触发条件

## 7. 推荐的数据结构

建议引入下面三类描述。

### 7.1 op 级 trigger 描述

```text
EventDrivenCommitOpInfo {
  op_id
  supernode_id
  trigger_keys[]    // 一个 op 可对应多个 edge slot
}
```

### 7.2 supernode 级分类

```text
CommitActivationMode {
  kGenericValueDriven,
  kEventDeltaDriven,
}
```

### 7.3 运行时发射索引

```text
CommitEventTriggerIndex {
  any_change[slot] -> active mask entries
  posedge[slot]    -> active mask entries
  negedge[slot]    -> active mask entries
}
```

这样 emitter 在生成 `eval()` 时就可以直接发射：

```cpp
if (event_edge_slots_[slot] == grhsim_event_edge_kind::posedge) {
    // OR 对应 active masks
}
```

而不再通过一大串 value-change fanout 间接到达 sink。

## 8. 运行时伪代码

### 8.1 当前更接近这样

```cpp
if (value_changed(x)) {
    if (x_is_event_sample) {
        event_edge_slots_[slot_x] = classify_edge(old_x, new_x);
    }
    activate_all_boundary_fanout_of_x();
}
```

### 8.2 目标形态

```cpp
if (value_changed(x)) {
    if (x_is_event_sample) {
        event_edge_slots_[slot_x] = classify_edge(old_x, new_x);
        activate_event_triggered_commit_heads(slot_x, event_edge_slots_[slot_x]);
    }
    activate_non_commit_or_generic_fanout_of_x();
}
```

其中：

- `activate_event_triggered_commit_heads(...)` 只覆盖纯 event-driven commit supernode
- `activate_non_commit_or_generic_fanout_of_x()` 不再包含这批 sink

这样同一个数据值变化就不会再把所有 clocked write sink 都重新 OR 一遍。

## 9. 和 `NO0029` 的协同关系

这轮方案最好不要单独看。

如果只做本文方案，不做 `NO0029` 的 event clustering，那么：

- sink 被激活的次数会下降
- 但一旦被激活，内部代码形态仍可能比较碎

如果只做 `NO0029`，不做本文方案，那么：

- 单次命中的 commit 代码更紧凑
- 但大量“其实本不该命中的 sink”仍会被频繁激活

因此推荐组合路线是：

1. 先做本文的 `event-delta activation narrowing`
2. 再继续推进 `NO0029` 的 `event-guard cluster`

前者降“命中次数”，后者降“单次命中成本”。

## 10. 预期收益

这轮预计收益主要来自运行时，而不是 emitter 编译期。

直接收益：

- 减少 `supernode_active_curr_[] |= mask` 的发射次数与执行次数
- 减少 commit phase 的无效 active-word 扫描
- 减少“event guard 外层条件恒 false”的空转

间接收益：

- sink 相关 `active flag` 热点会更集中在时钟/事件网络上
- data-path 抖动对 commit phase 的污染会下降
- 之后再做 perf trace 时，`round_active_in` / `round_active_words_in` 的 commit 部分会更可解释

## 11. 风险与约束

### 11.1 最大语义风险

最大风险不是“多激活了一次”，而是“少激活了一次”。

因此实现时要严格守住：

- event-delta 只对 `kRegisterWritePort` / `kMemoryWritePort` 启用
- 无法规范化 trigger key 的 op，一律回退到现有 generic 激活路径
- 只要 supernode 内混入 `kLatchWritePort`，整 node 回退

### 11.2 internal event sample 的一致性

当前 event sample 不只可能来自 input，也可能来自可 materialize 的内部逻辑值。

因此新索引不能只在 “changed input” 入口生效，还必须覆盖：

- compute 阶段内部 value change 触发的 event sample 更新

否则会出现：

- internal clock-like signal 在 compute 中变化了
- `event_edge_slots_` 被更新了
- 但对应 sink 没被 event index 激活

这也是为什么推荐把激活挂在 `emitChangedValueEffects(...)` 的 event-value 分支里，而不是只改 `eval()` 开头的 input seed。

### 11.3 supernode purity 很重要

如果一个 commit supernode 里同时混了：

- event-driven reg/mem write
- level-sensitive latch write

那么它就不能整体切到 event-delta 模式。

因此本文方案的收益大小，会明显依赖：

- `activity-schedule` 是否能把纯 event-driven sink supernode 尽量切干净

这也是它和 `NO0029`、`NO0033` 之间的真实耦合点。

## 12. 建议实施步骤

### Phase A：先做插桩，量化当前过宽激活

建议新增两组统计：

- `event_driven_sink_activations_total`
- `event_driven_sink_activations_by_non_event_operand`

以及按 supernode 统计：

- 被 event operand 激活多少次
- 被 data/cond/addr/mask 激活多少次

先确认 XiangShan 上到底有多少 sink 激活是纯浪费。

### Phase B：先做 emitter metadata，不改运行体

先在 emit model 里完成：

- supernode activation mode 分类
- `EventTriggerKey -> active ids` reverse index

但先不接入运行时，只把这些信息导出成 trace / debug dump，验证覆盖率。

验收点：

- 对所有 `kRegisterWritePort` / `kMemoryWritePort`
- 至少能提取出稳定、可去重的 trigger key

### Phase C：接入 runtime activation narrowing

接入点建议优先放在：

- `emitChangedValueEffects(...)` 的 event-sample 分支
- `eval()` 开头 changed-input event seed

并同步把纯 event-driven sink 从：

- `boundaryFanoutByValue`
- `inputHeadSupernodesByValue`

两条 generic 路径里剔除。

### Phase D：和 `NO0029` 联动收尾

在确认语义稳定后，再配合：

- event-homogeneous sink supernode
- guard-cluster chunking

继续压 commit 热路径。

## 13. 验收标准

功能验收：

- `kRegisterWritePort` / `kMemoryWritePort` 行为与当前版本完全一致
- `kLatchWritePort` 不受影响
- `state read` 的 reactivation 逻辑不变

结构验收：

- pure event-driven commit supernode 不再通过 generic value fanout 被数据值变化激活
- changed input 不再直接 seed 这批 sink

性能验收：

- XiangShan 50k 口径下，commit 相关 `active_words` / `executed_batches` 有可见下降
- 总体 `cycles/s` 有正向提升，且不引入 compile tail 回退

## 14. 结论

当前 `grhsim` 对 sink 的优化还主要停留在“被激活之后如何更高效执行”。但对 `kRegisterWritePort` / `kMemoryWritePort` 来说，更大的冗余其实发生在“本不该被激活却反复被激活”。

因此，本轮最值得推进的不是继续给 commit body 加局部小优化，而是先把它们的 activation trigger 收窄到 event-delta 这一层：

- 只有 event 变了，sink 才值得进场
- data/addr/mask/cond 只负责在 event 命中时被采样

这会比单纯压缩 commit body 更接近本质，也和当前 `event_edge_slots_`、`exactEventExpr(...)`、两阶段 `compute/commit` 结构天然一致。

## 增量更新 2026-04-28

### 本轮实现结论

基于本文方案，已在 `grhsim_cpp` emitter 中实际落过一版：

- 对纯 `event-driven` 的 `kRegisterWritePort` / `kMemoryWritePort`
- 从 generic `boundaryFanoutByValue` / `inputHeadSupernodesByValue` 激活路径中剥离
- 改为按 `event sample` 的 `edge kind` 单独触发对应 commit supernode

实现后完成了：

- `emit-grhsim-cpp` 定向回归
- XiangShan `grhsim` `coremark 50k` 口径复测

### 复测结果

本轮 XiangShan `50k` 结果：

- `RUN_ID=20260428_event_delta_50k`
- 运行日志：`build/logs/xs/xs_wolf_grhsim_20260428_event_delta_50k.log`
- 构建日志：`build/logs/xs/xs_wolf_grhsim_build_20260428_event_delta_50k.log`
- `Host time spent = 624396 ms`
- `guest cycle spent = 50001`
- 折算 `cycles/s = 80.077387`
- `instrCnt = 73580`
- `IPC = 1.471718`

对照 [`NO0033`](./NO0033_activity_schedule_simplification_plan_20260427.md) 中同为 `50k` 口径的当前基线：

- 旧基线 `cycles/s = 78.703347`
- 本轮 `cycles/s = 80.077387`

也就是说，这轮只有约 `+1.75%` 的提升，量级明显低于原先对“显著削减重复 sink 激活”的预期。

### 结论修正

结合实现复杂度与收益，当前判断是：

- 这不是一个值得继续保留在主线里的有效修改
- 运行时收益过小
- 引入了额外的 emitter 元数据、激活分流和语义维护复杂度
- 性价比不成立

因此，本轮代码实现已经撤回，当前保留本文档仅作为一次“已验证但无效”的方案记录。

后续应把它视为：

- 一个已做过验证的方向
- 但不是当前阶段推荐继续推进的主优化项

除非未来有新的插桩结果表明：

- sink 激活空转在更大 workload 下占比显著更高
- 或者可以用明显更低复杂度的方式复用同类思想

否则不建议再次投入实现。
