# 触发键驱动的静态调度方案

## 1. 目标

为后续仿真器准备一套静态调度计划，使运行时 `eval()` 不必全图重算，而是只执行本拍必需的操作。

这里的“触发键驱动”是指调度分组与运行时执行门控围绕以下要素展开：

- 可观察 `sink op`
- 触发键
- 共享组合逻辑锥

来构造更细粒度的静态执行组。

运行时模型仍然对齐 Verilator 风格：

```cpp
void eval();
```

`eval()` 内部以预先构建好的 `TKDGroup` 为单位调度。

核心优化目标：

- output 相关逻辑始终可得
- 事件判定逻辑先算
- 只有对应事件真正触发时，才计算该事件组下的 reg/mem 写口数据逻辑锥
- 多个事件组共享的公共逻辑只计算一次

## 2. 概念梳理

### 2.1 `op` 是最小调度单元

本方案规定 `op` 是最小调度单元。module、`always` block 和 process 都不作为调度单元。

这意味着：

- 静态分析、分组、拓扑排序都围绕 `op` 展开
- 运行时是否执行某段逻辑，也以“某个 `op` 是否落在本次要执行的 `TKDGroup` 中”为准
- `value` 只是依赖边上的数据载体，不单独参与调度；某个 `value` 被计算出来，等价于其定义 `op` 已经执行

除非后文显式说明，否则一个 `op` 不会再被拆成更细粒度的调度片段。

### 2.2 `sink op`

本方案把“会产生可观察效果，或其结果必须在本拍对外可见”的 `op` 统称为 `sink op`。

当前 `sink op` 至少包括：

- storage write sink：
  - `kRegisterWritePort`
  - `kMemoryWritePort`
  - `kLatchWritePort`
- effect sink：
  - 无返回值的 `kDpicCall`
  - 无返回值的 `kSystemTask`
- top-level observable sink：
  - 其 result 直接连接到 top-level `output` port value 的任何 `op`
  - 其 result 直接连接到 top-level `inout` 的 `out` value 的任何 `op`
  - 其 result 直接连接到 top-level `inout` 的 `oe` value 的任何 `op`

这里补一条边界说明：

- `inout` 不仅有输出值 `out`，还有输出使能 `oe`；`oe` 同样影响外部可观察行为，因此也必须视为 sink
- 这里的“直接连接”必须严格按 port 绑定关系判断，不能按传递闭包判断；否则 top-level 可观察值的整个上游组合锥都会被提前并入 `sink op`，后续再基于 `sink op` 扩张 `TKDGroup` 就失去分层意义
- 对 top-level observable sink，还需要做一步正规化：如果某个 `op` 的 result 一方面直接绑定到 top-level `output` / `inout.out` / `inout.oe`，另一方面又继续被其它 `op` 使用，那么真正进入 `SinkTKDGroup` 的不应是这个 `op` 本体，而应是一个位于该 result 与 top-level port 绑定之间的专用 sink 节点
- 在概念模型里，这个专用 sink 节点可以理解成一个新插入的 `kAssign`
- 当前草案允许在正规化阶段真正插入这个 `kAssign`
- 正规化完成后，后续 `TKDGroup` 构建过程再把 graph 视为 frozen
- 若调度输入 graph 仍允许 `kXMRWrite` 存在，那么它本质上也是 side-effect sink，也应并入 `sink op` 集合；若本方案前置要求先完成 `xmr-resolve`，则可暂不纳入当前正文

### 2.3 触发键

每个事件敏感的 `sink op` 都有一个触发键（`TriggerKey`）。

触发键有两种形态：

- 空键：记作空串，表示该 `op` 不依赖边沿触发事件
- 非空键：记作一串连续的二元组

```text
<valId1, posedge><valId2, negedge>...
```

其中每个二元组表示一个事件项：

- `valId`：事件信号对应的 value id
- `eventEdge`：边沿类型，目前取值为 `posedge` 或 `negedge`

这里采用“键”这个名字，因为更关注它的规范化、判等、去重和分组索引能力；原始语法外观不重要。

为了判断两个触发键是否等价，需要先把它规范化。规范化规则定义为：

1. 把触发键展开成若干个 `(valId, eventEdge)` 二元组
2. 先按 `valId` 升序排序
3. 对相同 `valId`，再按 `eventEdge` 排序；本文固定 `negedge < posedge`
4. 对完全相同的二元组去重
5. 规范化后的二元组序列作为该触发键的唯一表示

因此，两个触发键相等，当且仅当它们规范化后的二元组序列完全相同。

补充约束：

- 同一 `valId` 的 `posedge` 和 `negedge` 是两个不同事件项，不能互相去重
- 空触发键的规范形式仍为空触发键

### 2.4 调度组：`TKDGroup`

`TKDGroup`（Trigger-Key-Driven Group）是 `op` 的集合，也是运行时的直接调度单位。

不要把 `TKDGroup` 理解成“某个时钟域”的同义词。它表示结合可观察 sink、触发键和共享逻辑后得到的调度组。

一个 `TKDGroup` 只表达“这批 `op` 被一起调度”，不改变 `op` 之间原有的数据依赖关系；组内执行顺序仍由后续静态排序确定。

对 `TKDGroup`，先给出两个基础约束：

- 任意两个 `TKDGroup` 不相交
- 任意一个 `op` 至多属于一个 `TKDGroup`

也就是说，`TKDGroup` 在当前草案中构成参与本调度方案的 `op` 集合上的一个不交划分。

### 2.5 输入约束

本方案的输入对象是单个 `GRH Graph`，也就是说，后文所有 `op`、`value`、use-def 关系、top-level port 绑定关系，都是在同一个 `GRH Graph` 内部讨论的。

因此本方案在已经完成必要规整的单图表示上工作，不直接处理带层次结构的原始设计表示。

输入 `GRH Graph` 必须满足以下约束：

- 图中不再存在 `kInstance`
- 图中不再存在 `kBlackbox`
- 图中不再存在各类 `kXMR*`
- 图在进入 `TKDGroup` 正式构建之前完成必要正规化

也就是说，进入 `TKDGroup` 构建阶段之前，输入 graph 必须已经完成：

- 层次展开或等价规整
- `xmr-resolve` 或等价规整

这些约束之所以必须前置，是因为否则：

- “直接连接到 top-level port” 的判定会变得不稳定
- use-def 逆向回溯会穿越层次边界
- `sink op`、`TriggerKey`、`TKDGroup` 的语义边界都会变得不清晰

因此“单个无层次残留的 `GRH Graph`”是本方案的输入前提，不属于构建过程中顺便兼容的可选情况。

还需要额外强调一点：本方案的数据结构大量引用 `ValueId` 和 `OperationId`。这类 id 只在当前这份 `GRH Graph` 的当前结构上稳定；一旦跨 graph 读写、重建 graph、插删 op/value，id 都可能失稳。

因此本 pass 有一个明确约束：

- 步骤 1 正规化阶段允许对 `GRH Graph` 做必要的结构修改
- 正规化完成后，`TKDGroup` 构建阶段不再修改 `GRH Graph` 的结构
- 可以补充少量不影响 id 稳定性的 attribute
- 最终结果发布到 pass 指定的 scratchpad 路径下，而不是回写成新的 graph 结构

也就是说，`ValueId` / `OperationId` 的稳定性是相对于“正规化完成后的 frozen graph”来讨论的。

这里的“最终结果”至少包括：

- `SinkTKDGroup` / `TriggerTKDGroup` / `SimpleTKDGroup` 的成员信息
- `TKDGroup` 之间的依赖关系
- 每个 `TKDGroup` 的 `AffectedSinkSet`
- 最终的 `TKDGroup` 拓扑序

### 2.6 scratchpad 组织约束

scratchpad 的职责是让本 pass 向其它流程发布最终结果，不应用来堆放本 pass 内部的大量中间状态。

因此有两条基本约束：

- 仅发布后续流程确实需要消费的最终结果
- 中间 worklist、visited 标记、临时分桶、阶段性列表默认只存在于 pass 内存中，不写入 scratchpad

本 pass 的最终发布路径固定组织为：

```text
tkds/<modulePath>/...
```

其中：

- `modulePath` 表示当前目标 `GRH Graph` 对应的模块路径标识
- 同一个 module 的全部 TKD 结果都集中发布到这一前缀下
- 不同 module 的结果天然隔离，避免 scratchpad key 冲突

推荐形式：

```text
tkds/<modulePath>/meta
tkds/<modulePath>/pools/triggerKeys
tkds/<modulePath>/pools/affectedSinkSets
tkds/<modulePath>/groups/sink
tkds/<modulePath>/groups/trigger
tkds/<modulePath>/groups/simple
tkds/<modulePath>/index/opToTkdGroup
tkds/<modulePath>/plan/edges
tkds/<modulePath>/plan/topoOrder
```

其中：

- `meta`
  - 版本、构建参数、graph 标识等元信息
- `pools/triggerKeys`
  - `TriggerKey` intern 池的最终内容
- `pools/affectedSinkSets`
  - `AffectedSinkSet` intern 池的最终内容
- `groups/sink`
  - 全部 `SinkTKDGroup` 的最终结果
- `groups/trigger`
  - 全局 `TriggerTKDGroup` 的最终结果
- `groups/simple`
  - 全部 `SimpleTKDGroup` 的最终结果
- `index/opToTkdGroup`
  - 统一的 `opId -> TKDGroupId` 映射
- `plan/edges`
  - 最终 `TKDGroup` 级依赖边
- `plan/topoOrder`
  - 最终 `TKDGroup` 拓扑序

若后续确实需要保留某些中间结果用于调试，应放到：

```text
tkds/<modulePath>/debug/...
```

并且默认关闭，不进入常规产物。

## 3. `TKDGroup` 构建总览

本章先给出一版整体构建思路，只定义大步骤、阶段产物和关键注意点，不提前展开到具体数据结构与实现细节。后续章节再分别细化每一步。

### 3.1 总体目标

`TKDGroup` 的构建目标是：从原始 `op` 图出发，先识别真正需要被调度关注的 `sink op` 与触发相关逻辑，再把其余组合逻辑按“驱动了哪些 sink group”这一等价关系压缩成一组组不交的 `TKDGroup`，最终把原始 `op` 级依赖图降低为 `TKDGroup` 级依赖图。

构建完成后，运行时只需要按 `TKDGroup` 级计划执行，无需每拍重走全图。

除分组本身以外，构建阶段还必须为每个 `TKDGroup` 记录一个附加属性：

- 该 `TKDGroup` 的 `AffectedSinkSet`

这个属性在后文统一记作 `AffectedSinkSet(·)`。

更具体地说：

- 对任意 `TKDGroup` `G`，`AffectedSinkSet(G)` 表示从 `G` 中至少一个 `op` 出发，沿 data dependency 路径最终可到达的全部 `SinkTKDGroup` 的集合
- 对任意单个 `op`，`AffectedSinkSet(op)` 表示从该 `op` 出发，沿 data dependency 路径最终可到达的全部 `SinkTKDGroup` 的集合

后文不再混用“驱动哪些 sink group”“最终影响到哪些 sink group”“影响范围摘要”等不同叫法，统一都用 `AffectedSinkSet` 表示。

记录这份集合的目的，是为了让运行时能够基于“本拍哪些 `SinkTKDGroup` 需要求解”，快速反推出：

- 哪些 `SimpleTKDGroup` 需要求解
- 哪些 `TriggerTKDGroup` 需要保留为全局前置阶段

也就是说，`TKDGroup` 构建的产物不只是“若干 group + group 间依赖边”，还包括每个 group 的 `AffectedSinkSet`。

这些产物是本 pass 的最终逻辑产物。常规模式下，只有在步骤 4 完成后才统一发布到 `tkds/<modulePath>/...` 下；中间阶段结果默认留在 pass 内部，不单独写入 scratchpad。

### 3.2 步骤 1：正规化并收集 `sink op`，按 `TriggerKey` 形成 `SinkTKDGroup`

第一步先做 `sink op` 正规化，再收集全部 `sink op`，然后按 `TriggerKey` 对这些 `sink op` 分组，形成一批种子组，记为 `SinkTKDGroup`。

这一阶段的核心工作是：

- 对 top-level observable sink 做正规化
- 若某个 `op` 的 result 既直接连接到 top-level 输出分量，又被其它 `op` 使用，则在该 result 与 top-level port 绑定之间插入一个专用 `kAssign`
- 枚举输入图中的全部 `sink op`
- 为每个事件敏感的 `sink op` 提取规范化后的 `TriggerKey`
- 将 `TriggerKey` 相同的 `sink op` 归入同一个 `SinkTKDGroup`
- 对空 `TriggerKey` 的 `sink op`，也按相同规则进入对应的 `SinkTKDGroup`

这一步结束后，graph 进入 frozen 状态。后续全部 `TKDGroup` 构建、依赖分析和拓扑排序，都基于这份正规化后的 frozen graph 进行。

这一步的直觉是：

- `sink op` 决定了“哪些效果值得调度”
- `TriggerKey` 决定了“这些效果在什么触发条件下被一起考虑”

因此 `SinkTKDGroup` 是整个方案的第一层种子结构。

引入这一步正规化之后，`SinkTKDGroup` 中承载的 top-level observable sink 都是边界清晰的专用 sink。上游普通逻辑继续留在后续的 `SimpleTKDGroup` 候选集合中，不会因为“同一个 `op` 既是对外可观察点，又被内部复用”而混淆分组边界。

### 3.3 步骤 2：构建全局 `TriggerTKDGroup`

第二步单独抽出触发判定逻辑。

把所有非空 `TriggerKey` 中涉及的事件 value 合并起来，统一作为起点，沿 use-def 链逆向追溯其定义 `op`，收集出驱动这些触发 value 的逻辑，形成唯一的全局 `TriggerTKDGroup`。

这里的“沿 use-def 链逆向追溯”具体指：

- 从某个被使用的事件 value 出发
- 回到其定义 `op`
- 再继续沿该 `op` 的 operands 向上游回溯

这一阶段的目标是单独抽出“为了判断全部触发键是否命中，必须先算出来的逻辑”。某个 sink 的完整数据逻辑锥不在这一步求出。

这样做的收益是：

- 触发判定逻辑可以作为全局独立前置阶段先执行
- 后续只有在对应触发真的命中时，才需要进入更深的数据逻辑锥

当前草案明确采用“唯一 `TriggerTKDGroup`”的设计，理由是：

- 触发相关逻辑本质上接近时钟树 / 复位树附近的判定逻辑
- 在真实场景中，这部分逻辑规模通常远小于普通数据通路
- 采用唯一 `TriggerTKDGroup` 可以显著简化后续的调度约束与实现复杂度

### 3.4 步骤 3：从 `SinkTKDGroup` 逆向扩张，构建 `SimpleTKDGroup`

第三步处理剩余的普通逻辑 `op`。

以每个 `SinkTKDGroup` 为起点，沿 use-def 链逆向遍历其上游逻辑，为沿途每个 `op` 确定它驱动了哪些 `SinkTKDGroup`。然后把“驱动的 `SinkTKDGroup` 集合完全相同”的 `op` 归并成新的 `SimpleTKDGroup`。

也就是说，这一步按“下游可达的 sink 组集合”分组，不按 `TriggerKey` 分组。

因此，对每个 `SimpleTKDGroup` 来说，它对应的就是自己的 `AffectedSinkSet(G)`，并且这是后续运行时剪枝判定的核心元数据。

这一阶段需要遵守一个明确约束：

- 已经放入 `SinkTKDGroup` 的 `op`，不再放入新的 `SimpleTKDGroup`
- 已经放入 `TriggerTKDGroup` 的 `op`，不再放入新的 `SimpleTKDGroup`

因此 `SimpleTKDGroup` 只覆盖剩余的普通中间逻辑 `op`。

构建完成后，预期会得到多个互不相交的 `SimpleTKDGroup`，并与前面的 `SinkTKDGroup`、`TriggerTKDGroup` 一起组成最终的 `TKDGroup` 集合。

### 3.5 步骤 4：对全部 `TKDGroup` 做依赖建边与拓扑排序

当前三步完成后，原始 `op` 图已经被压缩成若干个 `TKDGroup`。

第四步需要：

- 在 `TKDGroup` 之间按数据依赖关系建边
- 验证 `TKDGroup` 级图是无环的
- 对该图做一次拓扑排序
- 产出最终的 `TKD` 级静态调度方案

在运行时语义上，是否需要求解某个 `TKDGroup`，取决于 `AffectedSinkSet(G)` 是否与“本拍需要求解的 `SinkTKDGroup` 集合”相交。

因此第 4 步输出的调度计划，后续也默认会依赖每个 `TKDGroup` 携带的这份 `AffectedSinkSet` 元数据。

其中有一个额外约束需要提前钉住：

- 唯一的全局 `TriggerTKDGroup` 必须先于所有其它 `TKDGroup` 求值

因此在建立 `TKDGroup` 级依赖图并交给 `toposort` 之前，除了普通数据依赖边以外，还要额外加入一类“触发前置边”：

- 从全局 `TriggerTKDGroup` 指向每个其它 `TKDGroup`

这样做是为了把“先完成触发判定，再执行其它 group”这一调度约束显式编码进 `TKDGroup` 级图；它不表示普通 dataflow 依赖。

这里直接复用现有 `toposort` 组件即可，不需要重新发明新的排序器。

如果后续实现与本文当前设想一致，那么最终运行时执行对象就是这份 `TKDGroup` 拓扑序列，以及与之配套的触发门控信息。

### 3.6 三类 `TKDGroup` 的角色分工

在当前草案里，`TKDGroup` 可以先分为三类：

- `SinkTKDGroup`
  - 直接承载 `sink op`
  - 是整个构图过程的种子
  - 对任意 `SinkTKDGroup` `S`，有 `AffectedSinkSet(S) = {S}`
- `TriggerTKDGroup`
  - 唯一且全局
  - 负责计算全部触发键中的事件 value
  - 是 sink 是否需要进一步执行的前置判定逻辑
  - `AffectedSinkSet(TriggerTKDGroup)` 等于所有非空 `TriggerKey` 所关联的 `SinkTKDGroup` 集合
- `SimpleTKDGroup`
  - 承载其余普通逻辑
  - 通过 `AffectedSinkSet` 相同这一等价关系形成
  - 每个 `SimpleTKDGroup` 都显式携带自己的 `AffectedSinkSet`

后文如果需要，可以再继续引入更细的子类或执行属性；但在目前阶段，这三类已经足够支撑整体方案描述。

### 3.7 关键注意点

#### 3.7.1 必须严格控制构图开销

输入图可能非常大，规模可能达到 100M+ `op` 节点。

因此后续每一步在落实现时都必须遵守以下原则：

- 任何数据结构都要控制常数开销，避免为每个 `op` 挂过重的附加状态
- 任何遍历都要尽量做到单次扫描或少量多次扫描，避免高重叠度的重复回溯
- 分组键、集合表示、依赖边表示都要优先选择紧凑编码，避免直接堆 STL 大对象
- `AffectedSinkSet` 会被频繁查询，因此其表示必须特别注意压缩与判交效率
- 步骤 1 结束后应把 graph 视为 frozen，避免任何会导致 `ValueId` / `OperationId` 重排或失稳的结构修改

也就是说，本方案虽然在概念上分四步，但实现上不能写成四个彼此独立、各自全图回扫的大 pass。

#### 3.7.2 需要证明 `TKDGroup` 级图无环

后续章节需要证明：如果输入图本身不存在组合逻辑环，那么按本草案构建出的 `TKDGroup` 级图也不会有环。

这个证明应从 `sink op` 的结构特点入手。

当前直觉是：

- `SinkTKDGroup` 中的 top-level observable sink 经过步骤 1 正规化后，边界是清晰的；对外可观察绑定与普通内部复用已经被拆开表示
- 全局 `TriggerTKDGroup` 只服务于触发判定，本身处于对应事件 value 的上游
- `SimpleTKDGroup` 只是把普通组合逻辑按相同下游 sink 集合做压缩，不会改变原图依赖方向
- 额外加入的“触发前置边”统一从全局 `TriggerTKDGroup` 指向其它 group，不会形成指回 `TriggerTKDGroup` 的反向强制边
- 因为输入图无组合环，而分组只是在保持依赖方向不变的前提下做节点收缩，再叠加方向单一的触发前置边，所以 `TKDGroup` 级图理论上仍应无环

这个结论在直觉上成立，但后文仍需要把它写成更严谨的论证，尤其要明确：

- 哪些边会出现在 `TKDGroup` 级图中
- 为什么不会出现从某个 group 再绕回自身上游的路径
- 为什么 `sink op` 的边界性质足以阻止 group 级回环
- 为什么 `TriggerTKDGroup -> 其它 group` 这一类全局前置边不会破坏无环性

第 4 章给出正式证明。

## 4. `TKDGroup` 级图无环性证明

本章证明：在第 2 章输入约束成立、且第 3 章所述构建过程成立时，最终得到的 `TKDGroup` 级依赖图一定是无环图。

### 4.1 证明前提

先把后文用到的前提列清楚。

前提 1：输入 `GRH Graph` 的 use-def 图对本次调度语义而言是无环的。

- 这是前置输入保证
- 读口 / 写口已经分离
- 状态更新不会在同一轮组合求值里形成回边

因此，正规化完成后的 frozen `GRH Graph` 可以看成一张无环的 `op` 级依赖图。

前提 2：top-level observable sink 已经在步骤 1 中完成正规化。

- 若某个 `op` 既驱动 top-level 输出分量，又被内部逻辑继续使用，则步骤 1 会在 port 绑定前插入专用 `kAssign`
- 进入 `SinkTKDGroup` 的是这个专用 sink，而不是原始被复用的普通 `op`

因此，`SinkTKDGroup` 的边界在证明阶段是清晰的。

前提 3：`TKDGroup` 级图中的边只有两类。

- data dependency edge
  - 若存在 `opA ∈ GA`、`opB ∈ GB`，且 `opA` 的 result 被 `opB` 使用，则建立 `GA -> GB`
  - 这里要求 `GA != GB`
- trigger precedence edge
  - 从全局 `TriggerTKDGroup` 指向每个其它 `TKDGroup`

后文只需要证明：这两类边合在一起仍不会形成环。

### 4.2 三类 group 的结构性质

#### 4.2.1 `SinkTKDGroup` 没有指向其它 group 的 data edge

对 storage write sink、`kSystemTask`、无返回值 `kDpicCall` 而言，它们本身没有 result，自然不可能再作为其它 `op` 的上游定义点。

对 top-level observable sink 而言，步骤 1 已经完成正规化：

- 真正进入 `SinkTKDGroup` 的是插入到 top-level port 绑定前的专用 `kAssign`
- 该 `kAssign` 的结果只用于 top-level 可观察绑定

因此，在 `TKDGroup` 级 data dependency graph 中，不存在从 `SinkTKDGroup` 指向其它 group 的 data edge。

换句话说，`SinkTKDGroup` 在 data dependency graph 里总是终点。

#### 4.2.2 全局 `TriggerTKDGroup` 没有来自其它 group 的 data edge

`TriggerTKDGroup` 的构造方式是：

- 把所有非空 `TriggerKey` 的事件 value 作为起点
- 沿 use-def 链向上游完整回溯
- 把驱动这些事件 value 的所有相关 `op` 都收进全局 `TriggerTKDGroup`

因此，如果某个 `op` 还能通过 data edge 驱动 `TriggerTKDGroup` 中的某个 `op`，那么它也应当在这次逆向回溯中被收进 `TriggerTKDGroup`。

所以在构建完成后，不存在从其它 group 指向 `TriggerTKDGroup` 的 data edge。

换句话说，全局 `TriggerTKDGroup` 在 data dependency graph 里总是源点。

#### 4.2.3 `SimpleTKDGroup` 的 data edge 会让 `AffectedSinkSet` 严格下降

先看单个 `op` 的性质。

若存在 data edge `u -> v`，那么任何能从 `v` 到达的 `SinkTKDGroup`，也一定能从 `u` 到达。因为 `u` 的结果先流到 `v`，再流向这些 sink。

因此：

```text
AffectedSinkSet(u) ⊇ AffectedSinkSet(v)
```

再看 group 级。

若存在 data edge `GA -> GB`，且 `GA`、`GB` 都是 `SimpleTKDGroup`，则：

- `AffectedSinkSet(GA) ⊇ AffectedSinkSet(GB)`

并且这个包含关系一定是严格的。

原因是：

- 若两者集合完全相同，那么 `GA` 与 `GB` 中的 `op` 应当在步骤 3 中被归并进同一个 `SimpleTKDGroup`
- 现在它们是两个不同的 `SimpleTKDGroup`，说明它们的 `AffectedSinkSet` 一定不同

因此对任意 `SimpleTKDGroup -> SimpleTKDGroup` 的 data edge，都有：

```text
AffectedSinkSet(source) ⊋ AffectedSinkSet(target)
```

这给出了一个严格单调下降的良序量。

### 4.3 data dependency graph 无环

现在只考虑 data dependency edge，证明由它们构成的 `TKDGroup` 级图无环。

假设反设存在一个环：

```text
G0 -> G1 -> ... -> Gk -> G0
```

分情况讨论。

情况 1：环中包含某个 `SinkTKDGroup`。

这不可能。因为根据 4.2.1，`SinkTKDGroup` 没有指向其它 group 的 data edge，它不能作为环上的继续出发点。

情况 2：环中包含全局 `TriggerTKDGroup`。

这也不可能。因为根据 4.2.2，全局 `TriggerTKDGroup` 没有来自其它 group 的 data edge，它不能作为环上的回流终点。

情况 3：环只由 `SimpleTKDGroup` 构成。

这同样不可能。因为根据 4.2.3，沿着环每走一步，`AffectedSinkSet` 都必须严格下降：

```text
AffectedSinkSet(G0) ⊋ AffectedSinkSet(G1) ⊋ ... ⊋ AffectedSinkSet(Gk) ⊋ AffectedSinkSet(G0)
```

有限集合不可能沿严格真包含关系绕一圈又回到自身，因此矛盾。

综上，只由 data dependency edge 构成的 `TKDGroup` 级图一定无环。

### 4.4 加入 trigger precedence edge 后仍然无环

现在把第 3 章步骤 4 中额外加入的 trigger precedence edge 也考虑进来。

这类边的形式只有一种：

```text
TriggerTKDGroup -> X
```

其中 `X` 是任意其它 `TKDGroup`。

这些边不会引入环，原因有两点：

- 它们全部从全局 `TriggerTKDGroup` 单向流出
- 根据 4.2.2，不存在从其它 group 回到 `TriggerTKDGroup` 的 data edge

因此一条包含 trigger precedence edge 的路径，一旦离开 `TriggerTKDGroup`，就不可能再回到 `TriggerTKDGroup`。这类边只能把 `TriggerTKDGroup` 更明确地固定为全局源点，不会制造回环。

### 4.5 结论

在以下条件同时成立时：

- 输入 `GRH Graph` 本身无组合环
- 读口 / 写口已经分离
- top-level observable sink 已经在步骤 1 中正规化
- `TKDGroup` 按第 3 章所述规则构建
- group 间边只包含 data dependency edge 与 `TriggerTKDGroup -> 其它 group` 的 trigger precedence edge

则最终得到的 `TKDGroup` 级图一定是 DAG。

因此第 3 章步骤 4 中对全部 `TKDGroup` 使用 `toposort` 是有理论保证的，不需要额外处理 group 级环。

## 5. 步骤 1 细化：`sink op` 正规化、收集与 `SinkTKDGroup` 构建

本章细化第 3 章步骤 1，目标是在满足大图性能约束的前提下，完成以下工作：

- 对 top-level observable sink 做正规化
- 收集全部 `sink op`
- 为每个事件敏感的 `sink op` 提取规范化后的 `TriggerKey`
- 按 `TriggerKey` 构建 `SinkTKDGroup`
- 产出这一步的内部结果

### 5.1 本步输入与输出

输入是第 2 章约束下的单个 `GRH Graph`。

在本步开始时：

- 图中已经没有 `kInstance`
- 图中已经没有 `kBlackbox`
- 图中已经没有各类 `kXMR*`

在本步结束时：

- top-level observable sink 的边界已经完成正规化
- graph 进入 frozen 状态
- pass 内部已经具备 `SinkTKDGroup` 的完整结果

本步至少需要得到以下内部结果：

- `sinkOpList`
  - 全部 `sink op` 的线性列表
- `sinkTriggerKeyId`
  - 每个 `sink op` 对应的 `TriggerKey` intern id
- `sinkGroupList`
  - 全部 `SinkTKDGroup` 的线性列表
- `sinkGroupMembers`
  - 每个 `SinkTKDGroup` 的成员 `op`
- `sinkGroupTriggerKeyId`
  - 每个 `SinkTKDGroup` 对应的 `TriggerKey` intern id
- `opToSinkGroup`
  - `sink op -> SinkTKDGroup` 的映射

这些结果供本 pass 的后续步骤直接消费，默认不单独发布到 scratchpad。

### 5.2 本步总流程

步骤 1 推荐拆成四个子阶段：

1. top-level observable sink 正规化  
2. 单次扫描识别全部 `sink op`  
3. 为每个 `sink op` 提取并 intern `TriggerKey`  
4. 按 `TriggerKey` 建立 `SinkTKDGroup`

这四个子阶段里，真正允许修改 graph 结构的只有第一个子阶段。

从第二个子阶段开始，graph 就视为 frozen。

### 5.3 子阶段 A：top-level observable sink 正规化

这一步只处理 top-level port 绑定相关的 observable sink。

需要先枚举：

- `graph.outputPorts()`
- `graph.inoutPorts()` 中的 `out`
- `graph.inoutPorts()` 中的 `oe`

对每个 top-level 可观察 value，找到其定义 `op`。

若该 value 满足以下条件：

- 直接绑定到 top-level `output` / `inout.out` / `inout.oe`
- 同时还被其它内部 `op` 使用

则需要在该 value 与 top-level port 绑定之间插入专用 `kAssign`。

插入后的目标是：

- top-level port 改为绑定到这个新 `kAssign` 的 result
- 原始 value 继续保留给内部普通逻辑使用
- 新 `kAssign` 成为真正的 top-level observable sink

这样处理之后，top-level 可观察边界与内部复用边界被拆开，后续 `SinkTKDGroup` 的成员就都是边界清晰的 sink。

这一步有两个实现约束：

- 只处理直接 port 绑定，不做传递闭包扩张
- 只在确实存在“对外可观察 + 内部复用”冲突时插入 `kAssign`；不要为所有 output/inout 绑定无差别插桩

### 5.4 子阶段 B：单次扫描识别全部 `sink op`

正规化完成后，对 graph 的 `operations()` 做一次线性扫描，识别全部 `sink op`。

建议按 `OperationKind` 直接分类，避免额外的多轮筛选。

当前至少要识别以下几类：

- storage write sink
  - `kRegisterWritePort`
  - `kMemoryWritePort`
  - `kLatchWritePort`
- effect sink
  - 无返回值 `kDpicCall`
  - `kSystemTask`
- top-level observable sink
  - 正规化后专用于绑定 top-level `output` / `inout.out` / `inout.oe` 的 `kAssign`

对每个识别出的 `sink op`，至少记录以下信息：

- `opId`
- `OperationKind`
- 所属 `TriggerKey` 的 intern id
- 需要时记录对应的 top-level port 绑定类别

这里要强调两个点：

- `sink op` 收集应当是一次线性扫描，时间复杂度目标为 `O(|Ops|)`
- top-level observable sink 的识别应当依赖正规化后的明确边界，而不是再次从所有普通 `op` 结果上反查 port 绑定

### 5.5 子阶段 C：提取并 intern `TriggerKey`

对每个 `sink op`，需要提取它的 `TriggerKey`。

提取规则与第 2 章保持一致：

- 空键：没有事件触发项
- 非空键：由若干 `(valId, eventEdge)` 二元组组成

当前可按下述方式提取：

- `kRegisterWritePort`
  - 从事件 operands 与 `eventEdge` 属性提取
- `kMemoryWritePort`
  - 从事件 operands 与 `eventEdge` 属性提取
- `kLatchWritePort`
  - `TriggerKey` 为空键
- 无返回值 `kDpicCall`
  - 若带事件语义，则按其事件 operands 与 `eventEdge` 提取
  - 若不带事件语义，则为空键
- `kSystemTask`
  - 按其事件语义提取；无事件时为空键
- top-level observable `kAssign`
  - 为空键

提取出的 `TriggerKey` 必须先规范化，再做 intern。

推荐的 intern 流程是：

1. 生成临时二元组序列
2. 按第 2 章规则排序和去重
3. 在全局 `TriggerKey` 池中查找是否已有完全相同的键
4. 若已有则复用已有 id
5. 若没有则分配新 id

本步后续所有分组逻辑都只使用 `TriggerKeyId`，不再反复操作原始二元组序列。

### 5.6 子阶段 D：按 `TriggerKey` 建立 `SinkTKDGroup`

当每个 `sink op` 都拥有稳定的 `TriggerKeyId` 后，就可以按该 id 建立 `SinkTKDGroup`。

当前草案中，`SinkTKDGroup` 的分组键就是：

```text
SinkTKDGroupKey := TriggerKeyId
```

因此：

- `TriggerKeyId` 相同的 `sink op` 进入同一个 `SinkTKDGroup`
- `TriggerKeyId` 不同的 `sink op` 进入不同的 `SinkTKDGroup`

建议在实现上维护：

- `TriggerKeyId -> SinkTKDGroupId`
- `SinkTKDGroupId -> member op list`
- `opId -> SinkTKDGroupId`

对任意 `SinkTKDGroup` `S`，其 `AffectedSinkSet(S)` 按定义恒为 `{S}`，因此这一步就已经能得到对应最终值。

### 5.7 数据结构建议

考虑到输入图可能达到 100M+ `op`，本步数据结构要尽量贴近线性内存布局。

建议优先采用以下形式：

- `std::vector<OpId>` 或等价紧凑数组存储 `sink op` 线性列表
- `std::vector<TriggerKeyId>` 按 sink 顺序平行存储 key id
- `std::vector<SinkTKDGroupId>` 按 sink 顺序平行存储 group id
- `opId -> small integer` 使用稠密数组或压缩索引，避免高频哈希查找
- `TriggerKey` 实体放到 intern 池中，group 侧只引用 `TriggerKeyId`

不建议的做法包括：

- 为每个 `op` 单独挂一个堆分配对象
- 在扫描过程中频繁构造和销毁大 `std::vector`
- 对同一个 `sink op` 多次重复解析 `eventEdge`
- 在普通 `op` 上重复做 top-level port 反查

### 5.8 性能约束

本步必须满足以下性能目标：

#### 5.8.1 图扫描次数要少

推荐上限：

- 1 次 top-level port 绑定扫描
- 1 次正规化后的 `op` 线性扫描

不要把“识别 sink”“提取 `TriggerKey`”“建立组”拆成多轮全图回扫。

#### 5.8.2 `TriggerKey` 处理要做 intern

大设计里大量时序写口会共享同一套时钟 / 复位触发键。

如果不做 intern：

- 会反复保存相同二元组序列
- 会显著放大内存占用
- 也会放大后续比较成本

因此 `TriggerKey` 必须以“规范化序列 + intern id”的形式存储。

#### 5.8.3 正规化插桩要最小化

步骤 1 允许改图，但插桩范围必须严格受控。

只在以下情况下插入专用 `kAssign`：

- 某个 value 直接绑定 top-level 输出分量
- 同一个 value 还被内部其它 `op` 使用

其余没有内部复用的 top-level 绑定不需要插桩。

#### 5.8.4 本步结果要直接服务后续步骤

本步内部结果的数据布局要直接服务后续步骤，避免第 2 步、第 3 步再做昂贵重整。

尤其是以下映射要一次建好：

- `opId -> SinkTKDGroupId`
- `SinkTKDGroupId -> TriggerKeyId`
- `SinkTKDGroupId -> member op list`

### 5.9 本步完成后的状态

当第 5 章描述的步骤 1 完成后，系统应处于以下状态：

- graph 已经完成 sink 正规化
- graph 已经 frozen
- 所有 `sink op` 都已经被识别
- 所有 `sink op` 都已经绑定到唯一的 `TriggerKeyId`
- 所有 `SinkTKDGroup` 都已经构建完成
- 对任意 `SinkTKDGroup` `S`，都有 `AffectedSinkSet(S) = {S}`

在这个状态上，后续第 6 章可以继续展开步骤 2，也就是全局 `TriggerTKDGroup` 的构建。

## 6. 步骤 2 细化：全局 `TriggerTKDGroup` 构建

本章细化第 3 章步骤 2，目标是在正规化后的 frozen graph 上，以尽可能低的额外开销构建唯一的全局 `TriggerTKDGroup`。

这一步的核心任务是：

- 找出所有非空 `TriggerKey` 真正引用到的事件 root value
- 以这些 root value 为并集起点做一次全局 use-def 逆向回溯
- 收集全部驱动触发判定所需的 `op`
- 产出全局 `TriggerTKDGroup` 及其元数据

### 6.1 本步输入与输出

本步输入包括两部分：

- 第 5 章结束后的 frozen `GRH Graph`
- 第 5 章产生的步骤 1 产物

本步至少依赖以下步骤 1 产物：

- `sinkGroupList`
- `sinkGroupTriggerKeyId`
- `opToSinkGroup`
- `TriggerKey` intern 池本体

本步至少需要得到以下内部结果：

- `triggerRootValueList`
  - 参与触发判定的去重后 root value 列表
- `triggerGroupMemberOps`
  - 全局 `TriggerTKDGroup` 的成员 `op`
- `opInTriggerGroup`
  - `opId -> bool` 或等价标记
- `triggerGroupId`
  - 唯一全局 `TriggerTKDGroup` 的 id
- `triggerGroupAffectedSinkSet`
  - `AffectedSinkSet(TriggerTKDGroup)`

这一步不修改 graph 结构。

### 6.2 本步总流程

步骤 2 推荐拆成四个子阶段：

1. 从 `SinkTKDGroup` 收集全部非空 `TriggerKey`
2. 从这些 `TriggerKey` 中展开并去重事件 root value
3. 以 root value 并集为起点做一次全局逆向回溯
4. 物化唯一的全局 `TriggerTKDGroup`

这四个子阶段的设计目标是：

- 不按每个 `sink op` 单独做回溯
- 不按每个 `SinkTKDGroup` 单独做回溯
- 整个步骤 2 对同一个 `op` 最多访问一次

### 6.3 子阶段 A：收集全部非空 `TriggerKey`

这一步不应从 `sink op` 重新扫描开始，而应直接复用第 5 章已经完成的 `SinkTKDGroup` 分组结果。

推荐做法是：

- 顺序扫描 `sinkGroupList`
- 读取每个 `SinkTKDGroup` 的 `TriggerKeyId`
- 过滤掉空键
- 对非空 `TriggerKeyId` 做去重

这里优先从 `SinkTKDGroup` 而不是从 `sink op` 出发，有两个原因：

- 相同 `TriggerKey` 的 `sink op` 在步骤 1 已经被聚合
- 以 group 为粒度扫描能显著减少重复展开同一 `TriggerKey` 的次数

本子阶段结束后，应得到：

- `activeTriggerKeyIdList`
  - 全部参与本次 trigger 构建的非空 `TriggerKeyId`

同时也可以直接得到：

- `AffectedSinkSet(TriggerTKDGroup)`
  - 它等于全部非空 `TriggerKey` 对应的 `SinkTKDGroup` 集合

换句话说，哪些 `SinkTKDGroup` 带非空 `TriggerKey`，全局 `TriggerTKDGroup` 就最终影响哪些 `SinkTKDGroup`。

### 6.4 子阶段 B：展开并去重事件 root value

有了 `activeTriggerKeyIdList` 后，就可以到 `TriggerKey` intern 池中取出每个 key 的规范化二元组序列。

对每个非空 `TriggerKey`：

- 枚举其中全部 `(valId, eventEdge)` 事件项
- 提取其中的 `valId`
- 把这些 `valId` 记为候选 trigger root value

这里有一个关键点：

- 对步骤 2 而言，是否 `posedge` / `negedge` 只影响“本拍是否触发”的判定逻辑
- 但在构建 `TriggerTKDGroup` 时，逆向追溯的根是对应的事件 value 本身

因此本子阶段做 group 成员收集时，根集合只需要按 `valId` 去重，不需要把 `(valId, eventEdge)` 当作不同回溯根。

本子阶段结束后，应得到：

- `triggerRootValueList`
  - 全部去重后的事件 root value

### 6.5 子阶段 C：做一次全局 use-def 逆向回溯

这是本步的核心。

从 `triggerRootValueList` 的并集出发，做一次全局 use-def 逆向回溯：

1. 取一个 root value
2. 查它是否有定义 `op`
3. 若无定义 `op`，说明它是 graph 输入或等价源值，停止在该点
4. 若有定义 `op`，且该 `op` 尚未访问，则：
   - 把该 `op` 加入全局 `TriggerTKDGroup`
   - 把该 `op` 的全部 operands 继续压入待访问 worklist
5. 重复直到 worklist 为空

这一步只做一次全局回溯，不按 root 分别重复跑。

原因很直接：

- 多个 `TriggerKey` 很可能共享同一段时钟树 / 复位树逻辑
- 若按 key 或按 sink group 分开回溯，会在共享上游逻辑上产生大量重复工作
- 全局并集回溯可以保证共享段只访问一次

### 6.6 回溯边界与停止条件

在子阶段 C 中，回溯边界需要明确。

#### 6.6.1 无定义值立即停止

若某个 value 没有定义 `op`，则停止回溯。

这类 value 通常包括：

- input port value
- inout input value
- 其它 graph 外源值

#### 6.6.2 已访问 `op` 不重复展开

若某个定义 `op` 已经被纳入全局 `TriggerTKDGroup`，则不重复展开其 operands。

这条规则保证：

- 每个 `op` 最多入组一次
- 每条共享上游逻辑只展开一次

#### 6.6.3 遇到 `sink op` 视为异常

按当前模型，trigger 判定逻辑的上游不应依赖 `sink op`。

原因是：

- storage write sink、`kSystemTask`、无返回值 `kDpicCall` 本身不产生可继续传播的普通数据结果
- top-level observable sink 在步骤 1 中已经被隔离到专用 `kAssign`

因此如果在 trigger 逆向回溯中遇到已分类为 `sink op` 的 `op`，应将其视为输入不符合预期，至少要打诊断。

这条约束也和第 4 章里的无环性证明保持一致。

### 6.7 子阶段 D：物化唯一全局 `TriggerTKDGroup`

当子阶段 C 结束后，所有被访问到的 `op` 就构成全局 `TriggerTKDGroup` 的成员集合。

这一步需要把它物化成稳定的内部结果，至少包括：

- `triggerGroupId`
- `triggerGroupMemberOps`
- `opInTriggerGroup`
- `triggerGroupAffectedSinkSet`

这里再次强调：

- 全局 `TriggerTKDGroup` 只有一个
- 它的成员由所有非空 `TriggerKey` 的事件 root value 的并集共同决定
- 它的 `AffectedSinkSet` 等于全部带非空 `TriggerKey` 的 `SinkTKDGroup` 集合

### 6.8 数据结构建议

这一步的实现重点是“全局并集回溯 + 稠密 visited 标记”。

建议优先采用：

- `std::vector<ValueId>` 作为 `triggerRootValueList`
- `std::vector<OpId>` 作为 `triggerGroupMemberOps`
- `std::vector<uint8_t>` 或等价位图作为
  - `valueSeen`
  - `opSeen`
  - `triggerKeySeen`
- `std::vector<ValueId>` 作为回溯 worklist

推荐的数据流形态是：

- 先按 `TriggerKeyId` 去重
- 再按 `ValueId` 去重 root
- 最后对 `OpId` 做一次全局 visited 回溯

不建议的做法包括：

- 为每个 `SinkTKDGroup` 单独跑一次 DFS / BFS
- 为每个 `TriggerKey` 单独维护一份 visited 集
- 在回溯过程中反复分配临时哈希集合
- 在已经有 intern id 的前提下重新重复解析所有 `eventEdge`

### 6.9 性能约束

本步必须满足以下性能目标。

#### 6.9.1 只做一次全局回溯

步骤 2 的设计核心就是“并集回溯”。

正确的复杂度目标应当接近：

- `O(|active trigger keys| + |trigger roots| + |visited ops in trigger cone|)`

而不是：

- `O(sum over each sink group of its trigger cone size)`

后者在共享时钟树很大的设计里会明显失控。

#### 6.9.2 先按 `TriggerKeyId` 去重，再按 `ValueId` 去重

这两层去重都必要：

- 不先按 `TriggerKeyId` 去重，会对同一时钟域重复展开同一组事件项
- 不再按 `ValueId` 去重，会让共享 root value 被重复压入 worklist

这两层去重都应使用紧凑的整数 id 标记结构，不要依赖高频字符串比较。

#### 6.9.3 不要重复读取 `sink op` 级事件信息

第 5 章已经把 `TriggerKey` 做了规范化和 intern。

因此本步应当：

- 直接消费 `TriggerKeyId`
- 从 intern 池取事件项

不要重新从每个 `sink op` 的 operands / attributes 上重复解析一次事件信息。

#### 6.9.4 `opInTriggerGroup` 必须可 `O(1)` 查询

后续步骤 3 在构建 `SimpleTKDGroup` 时，需要快速跳过已经属于 `TriggerTKDGroup` 的 `op`。

因此本步输出的成员判断结构必须支持：

- `O(1)` 或接近 `O(1)` 的 `op ∈ TriggerTKDGroup` 查询

最直接的方式就是按 `OpId` 建稠密位图或字节标记。

### 6.10 本步完成后的状态

当第 6 章描述的步骤 2 完成后，系统应处于以下状态：

- graph 仍保持 frozen
- 全部非空 `TriggerKey` 都已经被收集
- 所有事件 root value 都已经去重
- 全局 `TriggerTKDGroup` 已经构建完成
- 对任意 `op`，都可以快速判断它是否属于 `TriggerTKDGroup`
- `AffectedSinkSet(TriggerTKDGroup)` 已经可用

在这个状态上，后续第 7 章可以继续展开步骤 3，也就是 `SimpleTKDGroup` 的构建。

## 7. 步骤 3 细化：`SimpleTKDGroup` 构建

本章细化第 3 章步骤 3，目标是在 frozen graph 上，把所有剩余普通逻辑 `op` 按 `AffectedSinkSet` 相同这一等价关系归并为若干个 `SimpleTKDGroup`。

这一步的核心任务是：

- 为每个普通 `op` 计算 `AffectedSinkSet(op)`
- 跳过已经属于 `SinkTKDGroup` 或 `TriggerTKDGroup` 的 `op`
- 把 `AffectedSinkSet(op)` 相同的普通 `op` 归并成 `SimpleTKDGroup`

### 7.1 本步输入与输出

本步输入包括：

- frozen `GRH Graph`
- 第 5 章产生的 `SinkTKDGroup` 结果
- 第 6 章产生的全局 `TriggerTKDGroup` 结果

本步至少依赖以下前序步骤产物：

- `sinkGroupList`
- `opToSinkGroup`
- `opInTriggerGroup`
- `triggerGroupId`
- `AffectedSinkSet(TriggerTKDGroup)`

本步至少需要得到以下内部结果：

- `opAffectedSinkSetId`
  - 每个普通 `op` 对应的 `AffectedSinkSet` intern id
- `simpleGroupList`
  - 全部 `SimpleTKDGroup` 的线性列表
- `simpleGroupMembers`
  - 每个 `SimpleTKDGroup` 的成员 `op`
- `opToSimpleGroup`
  - `opId -> SimpleTKDGroupId`
- `simpleGroupAffectedSinkSet`
  - 每个 `SimpleTKDGroup` 的 `AffectedSinkSet`

这里的“普通 `op`”指：

- 不属于任何 `SinkTKDGroup`
- 不属于全局 `TriggerTKDGroup`
- 本身属于可调度的可执行逻辑 `op`

这里需要明确排除一类“声明性 / 载体性 `op`”。

这类 `op` 不参与 `TKDGroup` 调度，即使它们也不属于 `SinkTKDGroup` 或 `TriggerTKDGroup`，也不应进入 `SimpleTKDGroup`。当前至少包括：

- `kRegister`
- `kMemory`
- `kLatch`
- `kDpicImport`

如果后续 IR 再引入其它只表达声明、符号、对象定义、导入信息的 `op`，也应归入这一类并排除出 `TKDGroup`。

### 7.2 本步总流程

步骤 3 推荐拆成四个子阶段：

1. 确定参与本步的 candidate `op` 集
2. 计算每个 candidate `op` 的 `AffectedSinkSet(op)`
3. 对 `AffectedSinkSet` 做 intern
4. 按 `AffectedSinkSetId` 构建 `SimpleTKDGroup`

整个步骤 3 的关键点是：

- 不按每个 `SinkTKDGroup` 分别做一次逆向 DFS
- 不按每个普通 `op` 单独做一次下游可达性搜索
- 必须把 `AffectedSinkSet` 计算做成共享结果可复用的全局传播

### 7.3 子阶段 A：确定 candidate `op` 集

先对 graph 的全部 `op` 做一次线性扫描，确定哪些 `op` 属于本步候选集合。

判定规则很直接：

- 若 `op ∈ SinkTKDGroup`，跳过
- 若 `op ∈ TriggerTKDGroup`，跳过
- 若 `op` 是声明性 / 载体性 `op`，跳过
- 其余可执行逻辑 `op` 进入 candidate 集

因此，本步的 candidate 集不是“所有剩余 `op`”，而是“所有剩余、且真正参与求值的普通逻辑 `op`”。

这里建议同时建立一个稠密状态数组，例如：

- `0`: 非 candidate
- `1`: candidate

这样后续传播和分组都可以直接按 `OpId` 做 `O(1)` 判定。

### 7.4 子阶段 B：计算 `AffectedSinkSet(op)`

这是本步的核心。

目标是对每个 candidate `op` 计算：

```text
AffectedSinkSet(op)
```

根据定义，它等于从该 `op` 出发沿 data dependency 路径最终可到达的全部 `SinkTKDGroup` 的集合。

#### 7.4.1 推荐做法：全局反向传播

这一步推荐采用多源、全局、单调的反向传播，而不是按 sink group 分别回溯。

基本思路是：

1. 把所有 `sink op` 作为传播源
2. 对每个 `sink op`，把其所属的 `SinkTKDGroupId` 作为初始标签
3. 沿 use-def 反方向，把 sink 影响集合逐步向上游传播
4. 当某个 candidate `op` 的 `AffectedSinkSet` 发生增长时，再继续把增长后的集合传播到它的定义上游
5. 直到所有 candidate `op` 的 `AffectedSinkSet` 收敛

这里的“沿 use-def 反方向传播”具体指：

- 若 `u -> v` 是一个 data dependency edge
- 则 `AffectedSinkSet(v)` 的新增项需要继续传播到 `u`

#### 7.4.2 为什么这一步会收敛

这一步的传播是单调的：

- 每个 `op` 的 `AffectedSinkSet(op)` 只会增长，不会删除元素
- graph 本身无环
- `SinkTKDGroup` 数量有限

因此传播一定在有限步内收敛。

#### 7.4.3 推荐的实现形态

这一步推荐维护：

- `opAffectedSinkSetId`
  - 当前 `op` 的集合 intern id
- `opPending`
  - 当前 `op` 是否在传播 worklist 中
- `worklist`
  - 发生集合增长、需要继续向上游传播的 `op`

初始化时：

- 每个 `sink op` 对应的上游 operand 定义点获得该 sink 所属 `SinkTKDGroupId`
- 多个 sink 对同一上游 `op` 的影响在这里自然做并集

传播时：

- 读出当前 `op` 的 `AffectedSinkSet`
- 向其所有 operand 的定义 `op` 合并传播
- 如果上游 `op` 的集合变大，则把该上游 `op` 放入 worklist

### 7.5 边界条件

#### 7.5.1 遇到无定义 value 直接停止

若某个 operand value 没有定义 `op`，则在该点停止传播。

这类 value 通常包括：

- input port value
- inout input value
- 其它 graph 外源值

#### 7.5.2 不跨越 `SinkTKDGroup`

若某个上游定义 `op` 本身已经属于 `SinkTKDGroup`，则不继续把它作为普通 candidate 展开。

理由很简单：

- `SinkTKDGroup` 已经是单独的边界 group
- 本步只负责剩余普通逻辑的 `AffectedSinkSet` 计算

#### 7.5.3 不跨越 `TriggerTKDGroup`

若某个上游定义 `op` 已经属于全局 `TriggerTKDGroup`，则不继续把它纳入 `SimpleTKDGroup` 候选。

对应影响已经通过：

- `opInTriggerGroup`
- `AffectedSinkSet(TriggerTKDGroup)`

在后续调度中单独处理。

### 7.6 子阶段 C：对 `AffectedSinkSet` 做 intern

由于大图中大量普通 `op` 会共享同一个 `AffectedSinkSet`，这一步必须做集合 intern。

推荐方式是：

1. 用规范形式表示一个 `AffectedSinkSet`
2. 在全局集合池中查重
3. 相同集合复用已有 `AffectedSinkSetId`
4. 不同集合分配新 id

这里的规范形式建议满足：

- 成员 `SinkTKDGroupId` 升序
- 无重复

这样既方便比较，也方便后续按 id 直接分组。

### 7.7 子阶段 D：按 `AffectedSinkSetId` 构建 `SimpleTKDGroup`

当每个 candidate `op` 都拥有稳定的 `AffectedSinkSetId` 后，就可以按这个 id 构建 `SimpleTKDGroup`。

当前草案中：

```text
SimpleTKDGroupKey := AffectedSinkSetId
```

因此：

- `AffectedSinkSetId` 相同的 candidate `op` 进入同一个 `SimpleTKDGroup`
- `AffectedSinkSetId` 不同的 candidate `op` 进入不同的 `SimpleTKDGroup`

建议同时建立：

- `AffectedSinkSetId -> SimpleTKDGroupId`
- `SimpleTKDGroupId -> member op list`
- `opId -> SimpleTKDGroupId`

本步结束后，每个 `SimpleTKDGroup` 的 `AffectedSinkSet` 也就自然确定。

所有未进入任何 `TKDGroup` 的声明性 / 载体性 `op` 会继续保留在 graph 中，但不属于调度计划的一部分。

### 7.8 数据结构建议

这一步的数据结构设计重点是“集合合并成本”。

建议优先采用：

- `std::vector<AffectedSinkSetId>` 按 `OpId` 平行存储
- `std::vector<uint8_t>` 作为
  - `opIsCandidate`
  - `opPending`
- `std::vector<OpId>` 作为传播 worklist
- `AffectedSinkSet` intern 池

对 `AffectedSinkSet` 的具体底层表示，建议按 `SinkTKDGroup` 总数选型：

- 若 `SinkTKDGroup` 总数不大，可使用定长 bitset 或分块 bitset
- 若 `SinkTKDGroup` 总数较大且大多数集合稀疏，可使用升序 id 列表或压缩位图

无论选择哪种底层表示，都应满足：

- 集合并集操作足够快
- 可稳定生成规范形式
- 可被 intern
- 可高效做相等比较

### 7.9 性能约束

本步必须满足以下性能目标。

#### 7.9.1 不做 per-sink-group 重复回溯

禁止的实现方式：

- 对每个 `SinkTKDGroup` 单独向上游跑一遍 DFS / BFS

因为这会在共享组合逻辑上产生灾难性的重复访问。

正确方向是：

- 用全局多源反向传播一次性求出全部 candidate `op` 的 `AffectedSinkSet`

#### 7.9.2 集合增长驱动 worklist

只有当某个 `op` 的 `AffectedSinkSet` 真的变大时，才允许它再次进入 worklist。

否则：

- 会在大设计里产生大量无效重复传播
- 会把复杂度从“接近线性”放大成“接近边数乘以重复次数”

#### 7.9.3 `opToSimpleGroup` 必须支持 `O(1)` 查询

后续第 8 章构建 group 级依赖边时，需要频繁把 `op` 映射到所属 `TKDGroup`。

因此：

- `opToSimpleGroup`
- `opId -> SinkTKDGroupId`
- `opInTriggerGroup`

都应是 `O(1)` 或接近 `O(1)` 查询。

#### 7.9.4 `AffectedSinkSet` intern 必须复用

如果不做 intern：

- 大量相同集合会被重复存储
- group 构建阶段无法直接按 set id 分桶
- 后续比较与判交成本都会升高

因此 `AffectedSinkSet` 必须和 `TriggerKey` 一样，具备稳定的 intern id。

### 7.10 本步完成后的状态

当第 7 章描述的步骤 3 完成后，系统应处于以下状态：

- 所有普通 candidate `op` 都已经拥有稳定的 `AffectedSinkSetId`
- 所有 `SimpleTKDGroup` 都已经构建完成
- 对任意普通 `op`，都可以快速判断其所属 `SimpleTKDGroup`
- 对任意 `SimpleTKDGroup`，其 `AffectedSinkSet` 已经可用
- 所有声明性 / 载体性 `op` 仍保留在 graph 中，但不属于任何 `TKDGroup`

在这个状态上，后续第 8 章可以继续展开步骤 4，也就是 `TKDGroup` 级依赖建边与拓扑排序。

## 8. 步骤 4 细化：`TKDGroup` 级依赖建边与拓扑排序

本章细化第 3 章步骤 4，目标是把前面已经构建好的：

- `SinkTKDGroup`
- 全局 `TriggerTKDGroup`
- `SimpleTKDGroup`

统一提升到 `TKDGroup` 级，建立依赖边，并产出最终拓扑序。

### 8.1 本步输入与输出

本步输入包括：

- frozen `GRH Graph`
- 第 5 章的 `SinkTKDGroup`
- 第 6 章的全局 `TriggerTKDGroup`
- 第 7 章的 `SimpleTKDGroup`

本步至少依赖以下前序步骤产物：

- `opToSinkGroup`
- `opInTriggerGroup`
- `opToSimpleGroup`
- `SinkTKDGroup` / `TriggerTKDGroup` / `SimpleTKDGroup` 的成员信息
- 每类 group 的 `AffectedSinkSet`

本步至少需要得到以下内部结果：

- `tkdGroupList`
  - 全部 `TKDGroup` 的线性列表
- `opToTkdGroup`
  - `opId -> TKDGroupId`
- `tkdGroupEdgeList`
  - `TKDGroup` 级依赖边
- `tkdGroupTopoOrder`
  - 最终拓扑序

### 8.2 本步总流程

步骤 4 推荐拆成四个子阶段：

1. 统一 `TKDGroupId` 空间
2. 建立 `opId -> TKDGroupId` 映射
3. 扫描 op 级依赖边并提升为 `TKDGroup` 级边
4. 注入 trigger precedence edge 并做 `toposort`

### 8.3 子阶段 A：统一 `TKDGroupId` 空间

前面几章构建的是三类不同 group。

在本步开始时，建议先把它们统一到同一个 `TKDGroupId` 空间中。

推荐顺序可以是：

1. 全部 `SinkTKDGroup`
2. 全局 `TriggerTKDGroup`
3. 全部 `SimpleTKDGroup`

只要最终 id 稠密且稳定，具体顺序不是关键。

统一 id 空间后，每个 `TKDGroupId` 至少应携带：

- group kind
  - `sink`
  - `trigger`
  - `simple`
- member op list
- `AffectedSinkSet`

### 8.4 子阶段 B：建立 `opId -> TKDGroupId`

这一步要把前面分散的成员关系压成统一映射。

推荐做法是一次线性扫描：

- 若 `op ∈ SinkTKDGroup`，映射到对应 sink `TKDGroupId`
- 否则若 `op ∈ TriggerTKDGroup`，映射到 trigger `TKDGroupId`
- 否则若 `op ∈ SimpleTKDGroup`，映射到对应 simple `TKDGroupId`
- 否则标记为“未参与 TKD 调度”

这里应保留一个显式的未参与状态，而不是隐式用 `0` 或未初始化值代替。

因为后面扫描 op 级边时，需要区分：

- 边跨两个有效 `TKDGroup`
- 边的一端不属于任何 `TKDGroup`

### 8.5 子阶段 C：扫描 op 级依赖边并提升为 `TKDGroup` 级边

这一步推荐做一次 graph 级线性边扫描。

对每个 `opA`：

- 枚举其 results
- 枚举这些 result 的 users
- 找到被使用方 `opB`
- 读出 `GA = TKDGroup(opA)`
- 读出 `GB = TKDGroup(opB)`

之后分情况处理：

- 若 `GA` 或 `GB` 为空，跳过
- 若 `GA == GB`，跳过
- 否则记录一条候选 group edge `GA -> GB`

这一步只提升普通 data dependency edge，不处理 trigger precedence edge。

#### 8.5.1 为什么一次边扫描就够

前面几章已经把所有 group 成员都物化好了。

因此本步不需要再做任何 reachability 分析，只需要做：

- `op -> group` 查询
- `group -> group` 候选边提升

这一步的复杂度目标应接近：

- `O(|op-level edges touched|)`

### 8.6 子阶段 D：边去重、注入 trigger precedence edge、做 `toposort`

子阶段 C 扫描得到的候选 group edge 可能有大量重复。

因此需要先做一次 group edge 去重。

推荐方式有两类：

- 收集所有候选边后排序去重
- 对每个源 group 维护紧凑的目标集合，再输出去重结果

在 data dependency edge 去重完成后，再注入 trigger precedence edge：

- 从全局 `TriggerTKDGroup` 指向每个其它 `TKDGroup`

这里是否要跳过已经存在的同向 data dependency edge，不影响语义；最终只需要保证边集里无重复。

当全部边准备完成后，就可以直接调用 `toposort` 组件。

若 `toposort` 失败，则说明：

- 输入 graph 违反了前置无环假设
- 或者步骤 1~3 的实现偏离了本文定义

在当前理论模型下，这里不应出现环。

### 8.7 `AffectedSinkSet` 在本步中的角色

本步不再重新计算任何 `AffectedSinkSet`。

它在本步中的作用有两个：

1. 作为 `SimpleTKDGroup` 已经完成的分组依据
2. 作为后续运行时 `need-solve` 判定的直接元数据

也就是说：

- 第 8 章负责建边和排序
- 不负责重新传播 sink 影响集合

### 8.8 数据结构建议

本步的数据结构重点是“边扫描”和“边去重”。

建议优先采用：

- `std::vector<TKDGroupId>` 按 `OpId` 平行存储 `opToTkdGroup`
- `std::vector<std::pair<TKDGroupId, TKDGroupId>>` 存候选边
- `std::vector<TKDGroupId>` 存最终拓扑序

若 group 边数可能很大，也可以考虑：

- 按源 group 分桶
- 对桶内目标 id 排序去重

不建议的做法包括：

- 在边扫描过程中对每条边做高频字符串级判断
- 在 `op -> group` 查询上使用重哈希结构
- 在边去重上为每个 group 频繁分配零散小对象

### 8.9 性能约束

本步必须满足以下性能目标。

#### 8.9.1 只做一次 op 级边扫描

构建 `TKDGroup` 级依赖边时，不应对 graph 做多轮重复遍历。

推荐上限：

- 1 次统一的 op 级边扫描
- 1 次候选边去重

#### 8.9.2 `opToTkdGroup` 必须是稠密映射

边扫描阶段会极高频查询：

- `opA -> TKDGroupId`
- `opB -> TKDGroupId`

因此这个映射必须是：

- 稠密数组
- 或等价的 `O(1)` 结构

#### 8.9.3 group 边去重要后置批处理

大设计里，同一对 group 之间可能被许多 op 级边重复触发。

因此更合理的方式通常是：

- 先批量收集候选边
- 再集中排序去重

而不是在扫描每一条 op 级边时都立刻做重型去重判断。

#### 8.9.4 不重新做 reachability

第 5~7 章已经完成了：

- sink 正规化
- trigger 逆向并集回溯
- `AffectedSinkSet` 传播
- `SimpleTKDGroup` 构建

因此第 8 章不能再重复做新的 reachability / cone 分析，否则整体复杂度会失控。

### 8.10 本步完成后的状态

当第 8 章描述的步骤 4 完成后，系统应处于以下状态：

- 全部 `TKDGroup` 已统一到同一 id 空间
- `opId -> TKDGroupId` 已经稳定可查
- 全部 `TKDGroup` 级依赖边已经构建完成
- trigger precedence edge 已经注入
- 最终 `TKDGroup` 拓扑序已经生成

到这里，静态调度计划的主体结构就已经完整具备了。后续若需要，可以再继续补运行时求解策略、`need-solve` 判定流程，以及代码生成接口。

### 8.11 最终 scratchpad 发布

步骤 1 到步骤 4 结束后，本 pass 再统一把最终结果发布到 `tkds/<modulePath>/...` 下。

默认应发布的内容建议限制为：

- `tkds/<modulePath>/meta`
- `tkds/<modulePath>/pools/triggerKeys`
- `tkds/<modulePath>/pools/affectedSinkSets`
- `tkds/<modulePath>/groups/sink`
- `tkds/<modulePath>/groups/trigger`
- `tkds/<modulePath>/groups/simple`
- `tkds/<modulePath>/index/opToTkdGroup`
- `tkds/<modulePath>/plan/edges`
- `tkds/<modulePath>/plan/topoOrder`

各条目的推荐内容如下：

- `tkds/<modulePath>/meta`
  - 方案版本
  - 构建时间或构建轮次
  - 对应 graph 标识
  - 统计信息，例如 `sinkGroup` / `simpleGroup` 数量、group 边数量
- `tkds/<modulePath>/pools/triggerKeys`
  - `TriggerKeyId -> TriggerKey` 的 intern 池内容
  - 每个 `TriggerKey` 的规范化事件项序列
  - 空键的固定 id
- `tkds/<modulePath>/pools/affectedSinkSets`
  - `AffectedSinkSetId -> {SinkTKDGroupId...}` 的 intern 池内容
  - 每个集合的规范化成员序列
- `tkds/<modulePath>/groups/sink`
  - 全部 `SinkTKDGroup` 的定义
  - 每个 group 的成员 `op`
  - 每个 group 对应的 `TriggerKeyId`
  - 每个 group 的 `AffectedSinkSet`
- `tkds/<modulePath>/groups/trigger`
  - 唯一全局 `TriggerTKDGroup` 的定义
  - 成员 `op`
  - 对应的事件 root value 集
  - `AffectedSinkSet(TriggerTKDGroup)`
- `tkds/<modulePath>/groups/simple`
  - 全部 `SimpleTKDGroup` 的定义
  - 每个 group 的成员 `op`
  - 每个 group 对应的 `AffectedSinkSetId`
  - 每个 group 的 `AffectedSinkSet`
- `tkds/<modulePath>/index/opToTkdGroup`
  - 统一的 `opId -> TKDGroupId` 映射
  - 对未参与调度的 `op` 使用显式空值或哨兵值
- `tkds/<modulePath>/plan/edges`
  - 去重后的 `TKDGroup` 级依赖边列表
  - 每条边的 `srcGroupId` 与 `dstGroupId`
  - 若需要，也可附带边类型，区分 `dataDependency` 与 `triggerPrecedence`
- `tkds/<modulePath>/plan/topoOrder`
  - 最终 `TKDGroupId` 拓扑序列
  - 若运行时需要 phase 信息，也可在此处附带预切分后的 phase 边界

以下内容默认不发布：

- worklist
- visited 位图
- 去重前候选边
- 阶段性 root 列表
- 仅供本 pass 内部复用的临时索引

如果需要问题定位或性能剖析，可在 debug 模式下额外发布：

- `tkds/<modulePath>/debug/...`

但这不属于常规产物，默认关闭。
