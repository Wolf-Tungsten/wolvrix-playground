# RepCut Debug Sink / ASC 改造草案

## 1. 背景

当前 XiangShan repcut 流程是：

1. 对 `SimTop` 先执行 `strip-debug`
2. 生成：
   - `SimTop_logic_part`
   - `SimTop_debug_part`
3. 仅对 `SimTop.logic_part` 执行 `repcut`
4. runtime 将 `debug_part` 作为特殊相位先执行

这套流程可以工作，但有两个明显问题：

1. `strip-debug` 先人为制造了一条很大的 logic/debug 边界。
2. 大量本来只是“服务于 debug side-effect op 的输入值”，被迫通过 wrapper 端口和 runtime scatter/publish 路径搬运。

现有 timing 现象也与此一致：

- `debug_part->eval()` 本身不是主要成本。
- `debug_scatter` 曾长期是关键热点。
- 当前问题的本质不是“debug op 必须成为一个独立 graph”，而是“这些 op 不能被错误复制或切散”。

因此，本草案的核心方向是：

- 取消“先 strip，再 repcut”的建模方式。
- 直接在 `repcut` 内把 debug 相关 side-effect op 当作 `sink`。
- 让这些 op 通过 ASC（Atomic Sink Cone）机制与其输入组合锥一起参与分区。

## 2. 核心判断

### 2.1 这些 op 的本质属性不是“要被剥离”

更准确的属性是：

- 它们是 side-effect / external-interaction 的终点。
- 它们不能被复制到多个 partition。
- 它们也不应该被切成“op 在一边、组合准备逻辑在另一边”。

因此，对 `repcut` 来说，最自然的建模不是：

- “把 debug 子图先整体拆出去”

而是：

- “把这些 op 作为 `sink`，让其前驱组合锥并入同一个 ASC”

### 2.2 ASC 语义与这个需求天然匹配

当前 `repcut` 已经具备以下结构：

- `SinkRef` 支持 `Operation` 型 sink
- `collectSinks()` 负责枚举 sink
- `collectAscCone()` 从 sink 的 operand 反向收集组合锥
- ASC 最终作为 partition 过程中的不可分原子单元

这意味着只要把目标 debug op 纳入 sink 集合，就能自然获得：

1. sink op 自身不会被切开
2. 其输入组合锥会尽量与它落在同一个 ASC
3. 后续分区不会要求复制这些 op

## 3. 适用对象

### 3.1 直接 side-effect sink

建议第一版直接纳入 sink 分类的 op：

- `kDpicCall`
- `kSystemTask`

原因：

- 两者都属于明确的 side-effect 终点。
- 若复制到多个 partition，语义大概率直接错误。
- 它们非常适合被视为 ASC 的终点。

本草案明确不覆盖：

- `kInstance`
- `kBlackbox`

原因不是它们也适合当 sink，而是要通过 repcut guard 直接禁止它们进入 partition 阶段。

## 4. 目标结构

目标不是继续生成：

- `*_logic_part`
- `*_debug_part`

而是：

- 直接对原 graph 做 repcut
- 部分 partition 因为含有 debug/effect sink，被标记为特殊 phase

换句话说，改造后的核心语义应为：

- debug op 仍然在 partition 结果中存在
- 但它们是普通 `part_*` 中的成员，而不是前置 strip 形成的一个独立 graph
- 某些 `part_*` 会因为含有 effect sink 而获得特殊调度属性

## 5. 方案总览

### 5.1 Phase A/B：把 debug op 视为 sink

#### 当前状态

当前 `isSinkOpKind()` 只把以下 op 视为 sink：

- `kRegisterWritePort`
- `kLatchWritePort`
- `kMemoryWritePort`

这意味着：

- `kDpicCall`
- `kSystemTask`

不会形成 `Operation sink`

#### 改造方向

扩展 sink 分类：

- storage sink
- effect sink

其中 effect sink 至少包括：

- `kDpicCall`
- `kSystemTask`

#### 预期结果

这些 op 一旦进入 `collectSinks()`：

- 会以 `SinkRef::Kind::Operation` 进入 sink 集合
- `collectAscCone()` 会从其 operands 回溯组合输入锥
- sink + comb cone 会进入同一 ASC

这样就不再需要先靠 `strip-debug` 为它们手工造一个“不可切分区域”。

### 5.2 Phase B guard：允许新的 operation sink 种类

当前 ASC guard 默认假设：

- `Operation` 型 sink 必须是 write port

这需要同步放宽。

新的 guard 语义应为：

- sink op 必须属于“允许的 sink kind 集合”
- 该集合包含 storage sink 和 effect sink

否则即使 `collectSinks()` 放进去了，后面的校验仍会失败。

### 5.3 Pass guard：禁止 `kInstance` / `kBlackbox` 进入 repcut

本草案增加一个明确约束：

- 进入 repcut 的目标 graph 中不允许再有 `kInstance`
- 进入 repcut 的目标 graph 中不允许再有 `kBlackbox`

也就是说，repcut 的 guard 应保证：

- side-effect sink 只考虑 `kDpicCall` / `kSystemTask`
- 层次结构 op 不在本次 repcut 支持范围内

这样做的直接收益是：

- 不需要讨论 `kInstance` / `kBlackbox` 是否应作为 sink
- 不需要为它们设计跨分区结果传播规则
- 不需要把普通层次边界误纳入 ASC 语义

如果 guard 触发，诊断应直接说明：

- repcut 目标 graph 仍残留 `kInstance` / `kBlackbox`
- 需要在进入 repcut 之前先完成层次展开、实例消除或其它前置规整

### 5.4 移除对 `strip-debug` 的硬依赖

当前 `repcut` 在 pass 入口处会对以下 op 直接报错：

- `kSystemTask`
- `kDpicCall`

报错语义是：

- `strip-debug should remove system tasks/dpi calls before repcut`

这条限制必须删除。

否则新的 sink 方案根本无法在原 graph 上工作。

删除这条依赖后，`repcut` 应改为：

- 自己消费这类 op
- 自己决定它们如何进入 ASC 和 partition

## 6. Phase E：跨分区值规则要同步修正

这是本改造中最关键的一处补丁。

### 6.1 仅仅把 op 当 sink 还不够

因为当前 phase-e 对跨分区值的许可规则很保守。

大致上当前允许的 cross value 只有：

- top input / inout input
- `kRegisterReadPort`
- `kLatchReadPort`
- `kConstant`

而大量“effect sink 产生的结果值”如果被其它 partition 使用，按现状会被判成 forbidden cross。

这会带来一个矛盾：

- op 不能复制
- 但它的结果又可能必须跨 partition 使用

所以 phase-e 需要补一条新规则。

### 6.2 新规则

对于满足以下条件的值，允许跨 partition：

1. 定义 op 属于 effect sink
2. 该值语义上允许被下游逻辑观察
3. 跨分区传播只传 value，不复制 defining op

形式上：

- `allowed = true`
- `requiresPort = true`

语义上：

- 允许把 sink 的输出结果作为边界值传递
- 不允许因此复制 sink op 本身

### 6.3 这与“不复制 debug op”并不矛盾

这里需要明确区分两件事：

- 复制 op
- 传递 op 的结果值

本草案禁止的是前者，不是后者。

也就是说：

- `kDpicCall` 不能在多个 partition 各放一份
- 但它的一份执行结果可以通过 cross-partition value 传给其它 partition

## 7. Runtime / Manifest 改造

### 7.1 不再依赖 `debug_part` 名称

当前 partitioned runtime 有一个强假设：

- 存在名为 `debug_part` 的特殊单元
- 该单元先 scatter / eval / publish
- 然后其它 `part_*` 再执行

这个假设来自旧流程：

- `strip-debug` 先显式造出 `debug_part`

如果改为“debug op 作为 sink 并入 repcut”，runtime 就不应再依赖固定模块名。

### 7.2 新的 runtime 语义

应改为基于 partition 属性调度，而不是基于实例名调度。

建议在 manifest 或 graph attr 中标记：

- `phase = early`
- `phase = normal`

规则：

- 含有 effect sink 的 partition 标记为 `early`
- 普通 partition 标记为 `normal`

运行时执行语义：

1. 执行全部 `early` partition
2. 立即发布其输出
3. 再执行 `normal` partition
4. 最后统一 writeback

这样 runtime 仍能满足：

- DPI / device 返回值在同 step 内被普通逻辑消费

同时不再需要单独的 `debug_part` graph。

## 8. 与旧方案相比的预期收益

### 8.1 减少人为边界

旧方案先把整个 debug 模块切成一个独立 graph。

这会强迫：

- 大量只服务于 debug op 的前驱值
- 通过 wrapper 边界和 runtime scatter 路径搬运

新方案中：

- debug op 直接作为 sink 进入 ASC
- 它所依赖的组合锥会尽量就地并入同一 partition

因此预计会减少：

- `debug_scatter`
- 与 debug 相关的 boundary port 数量
- 纯搬运型 bridge value 数量

### 8.2 更符合 RepCut 原始抽象

旧方案是：

- 先做一层 IR 级人工拆图
- 再做超图分区

新方案是：

- 直接在超图构建阶段表达“哪些 op 是不可切终点”

从建模上更统一，也更容易维护。

### 8.3 保持“不复制 debug op”的约束

通过 ASC 机制，这些 op 会被稳定收束到单一 partition。

因此可以同时满足：

- 不复制 side-effect op
- 不强制前置 strip
- 保留必要的结果值跨 partition 传播

## 9. 风险与边界

### 9.1 repcut 前置规整必须保证图中无 `kInstance` / `kBlackbox`

本草案将层次结构 op 排除在支持范围之外。

这意味着流程上必须保证：

- 进入 repcut 前，目标 graph 已不再含有 `kInstance`
- 进入 repcut 前，目标 graph 已不再含有 `kBlackbox`

如果这个前提不成立，repcut 应直接 fail fast，而不是静默退化。

### 9.2 effect sink 输出是否允许跨 partition 需要精确定义

并不是所有 side-effect op 的结果都应该自由跨分区。

需要按具体语义区分：

- 哪些结果只是状态观察值，可以传播
- 哪些结果若跨 partition 会引入额外时序/相位问题

第一版建议至少覆盖已经在现有 runtime 中被证明必须“先 eval 再消费”的那类 debug/device 返回值。

### 9.3 runtime 仍然保留 early-phase 成本

这套方案的目标不是完全消除 debug special path。

它消除的是：

- 前置 strip-debug
- 大量人为 boundary copy

它不消除的是：

- 某些 effect partition 必须早执行的调度事实

因此 runtime 仍会有 special phase，只是 special phase 的粒度从：

- 固定 `debug_part`

变成：

- 含 effect sink 的 partition

## 10. 分阶段实施建议

### 阶段 1：最小功能闭环

目标：

- 在不跑 `strip-debug` 的情况下让 `repcut` 接受 `kDpicCall` / `kSystemTask`

改动：

- 扩展 `isSinkOpKind()`
- 扩展 `collectSinks()`
- 扩展 phase-b guard
- 新增 guard：拒绝残留 `kInstance` / `kBlackbox`
- 移除入口处对 `kDpicCall` / `kSystemTask` 的报错

暂不处理 runtime phase 属性重构。

### 阶段 2：补齐 phase-e cross 规则

目标：

- 允许 effect sink 结果值合法跨 partition

改动：

- 扩展 `CrossPartitionValue` 判定逻辑
- 新增按 defining op kind 或 effect/debug attr 的允许规则

### 阶段 3：runtime 从 `debug_part` 特判切换到 `phase` 特判

目标：

- 消除 runtime 对固定实例名 `debug_part` 的依赖

改动：

- manifest 增加 partition phase 信息
- runtime 调度按 phase 执行

## 11. 结论

本草案的结论是：

- debug 相关 op 的正确建模不是“先 strip 成独立模块”
- 而是“作为不可复制的 `sink` 进入 ASC”

具体来说：

1. `kDpicCall` / `kSystemTask` 应直接作为 `Operation sink`
2. repcut guard 应禁止 `kInstance` / `kBlackbox` 进入 partition 阶段
3. 这些 sink 的输入组合锥通过 ASC 机制与其绑定
4. phase-e 允许其结果值跨 partition 传播，但不允许复制 op
5. runtime 对特殊调度的判断从 `debug_part` 名称切换到 partition phase

这样可以同时满足：

- 不复制 debug/effect op
- 减少人为 strip-debug 边界
- 降低 debug scatter / bridge copy
- 保持现有 early-phase 语义可表达

这比“先 strip-debug，再对 logic_part 做 repcut”更符合 RepCut/ASC 的原始抽象，也更接近问题本质。
