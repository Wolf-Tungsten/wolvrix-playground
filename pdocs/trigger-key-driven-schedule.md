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
  - `kSystemTask`
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
- 所有核心输出都写入 pass scratchpad，而不是回写成新的 graph 结构

也就是说，`ValueId` / `OperationId` 的稳定性是相对于“正规化完成后的 frozen graph”来讨论的。

这里的“核心输出”至少包括：

- `SinkTKDGroup` / `TriggerTKDGroup` / `SimpleTKDGroup` 的成员信息
- `TKDGroup` 之间的依赖关系
- 每个 `TKDGroup` 的 `AffectedSinkSet`
- 最终的 `TKDGroup` 拓扑序

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

这些产物都应写入 scratchpad。当前草案不要求把它们回写成新的 `GRH Graph` 结构。

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
