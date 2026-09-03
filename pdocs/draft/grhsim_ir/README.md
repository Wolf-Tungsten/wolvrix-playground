# GrhSIM IR 草案

状态：初始规划。本文先冻结职责边界和最小不变量，不冻结 C++ 类名或最终序列化 schema。

## 1. 动机与目标

当前仿真链路大致是：

```text
flatten 后的 GRH -> activity-schedule -> session 中的隐式结果 -> grhsim emit
```

`activity-schedule` 和 emitter 之间没有一个可审计、可独立验证的数据契约。与此同时，GRH 的首要目标是表达可综合 RTL；仿真需要的动作可能包含 fixed-point 求值、事件采样、提交、外部调用和后端专用优化。把两类语义长期塞进同一套 IR，会使变换和代码生成的边界越来越模糊。

GrhSIM IR 的目标是把链路改成：

```text
GRH(flattened) -> lower/normalize -> SimGraph
                              -> PartitionTree
                              -> SchedulePlan
                              -> backend emit
```

基本原则：

- GRH 保持 RTL 分析和综合导向；GrhSIM IR 只承担仿真语义。
- 图中的值依赖、状态依赖和副作用顺序都必须显式表示，禁止用 session key 传递核心语义。
- 后端差异放在 dialect、调度模型和 emitter 中，不污染通用图语义。
- 每一层都可独立验证、序列化和回放；下游只依赖明确的上游契约。

非目标：首版不替换 GRH，不承诺一次支持所有仿真后端，也不在 IR 设计阶段追求最优分区或最优调度。

## 2. 三层模型

| 层 | 建议名称 | 负责什么 | 不负责什么 |
| --- | --- | --- | --- |
| 1 | `SimGraph` | 节点、值、类型、值边、效果边、方言属性和仿真语义 | 分区归属、worker 时间线 |
| 2 | `PartitionTree` | 层次化子图、边界端口、分区约束和商图 | 具体机器资源和执行时刻 |
| 3 | `SchedulePlan` | 分区任务、依赖、阶段、资源、同步和激活策略 | 重新定义节点语义 |

三层通过稳定 ID 引用，而不是保存指针或隐式查表：`NodeId`、`ValueId`、`StateId`、`TypeId`、`StorageId`、`PartitionId`、`TaskId`。一个可审计的产物应能单独回答“谁定义了这个值”、“它属于哪个分区”、“采用什么物理表示”和“何时由哪个资源执行”。

### 2.1 `SimGraph`

建议的最小对象如下：

```text
SimGraph
  nodes: SimNode[]
  values: SimValue[]
  value_edges: producer -> consumer
  effect_edges: ordered side-effect/control dependencies
  states: StateObject[]
  type_dialects: registered semantic types
  storage_contracts: logical lifetime/ownership/access rules
  dialects: registered operation dialects
```

`SimNode` 至少包含 `dialect/op_kind`、operands、results、source provenance、属性和 effect summary。`SimValue` 至少包含语义类型、可见性、生命周期、存储契约和可选的 state/memory 关联。`StateObject` 是一等对象，读写端口通过 `StateId` 与 `ValueId` 关联，并描述初值、current/next 或 staged transition、可见时机和写冲突规则。Value 在一个执行区间内应视为不可变 SSA 值，State 的改变只能经过显式 write/commit。

#### 类型和存储的扩展轴

不能把“逻辑类型”和“后端物理类型”混成一个字段。建议分三层记录：

1. `SemanticType`：仿真必须保持的类型语义，例如 `logic(width, signed, 2/4-state)`、`real`、`string`、aggregate、event/token；由通用或领域 dialect 扩展。
2. `StorageContract`：与后端无关的生命周期和访问要求，例如 `local-temporary`、`partition-boundary`、`persistent-state`、`staged-write`、`event-snapshot`、`external-handle`，以及共享、版本和原子性约束。
3. `RepresentationPlan`：某个 backend 对前两者的具体实现，包括物理 C++ 类型、布局、lane/字节序、对齐、所有权、访问器、初始化和提交路径。它是显式产物，不由 emitter 临时推断。

因此，类型/存储是可扩展的正交轴，而不是 GrhSIM 的第四层图结构：图保存语义和约束，backend lowering 根据分区及调度生成 `RepresentationPlan`。同一个 `SimGraph` 可以有多个 backend plan。

#### CPU/C++ 首版约定示例

CPU backend 至少应输出如下可审计标注；`cpp_type` 只是示例策略，最终由 `cpu-cpp` dialect 版本控制：

| 语义对象 | `cpp_type` 示例 | 存储路径与约束 |
| --- | --- | --- |
| 2-state 窄值，宽度 `<= 64` | `std::uint64_t`（另存逻辑宽度和 signedness） | 同一 partition 内优先局部 SSA；跨边界使用 typed boundary buffer |
| 4-state 窄值，宽度 `<= 64` | `LogicWord64 { bits, known }` | `known` 与 `bits` 同步更新，禁止退化成未标注的整数 |
| 宽 2-state 值 | `std::array<std::uint64_t, N>` | 明确 `word_bits`、lane 顺序、尾 word mask 和对齐 |
| 宽 4-state 值 | `LogicVec<N>` 或 `{bits[N], known[N]}` | 布局和 helper ABI 固定在 dialect，不由单个 op 自行选择 |
| persistent register/latch | 生成的 typed member 或 state arena slot | `current -> staged/next -> commit` 路径显式，提交后才对 reader 可见 |
| memory | `std::vector<Cell>`、`std::unique_ptr<Cell[]>` 或注册的 sparse container | 行布局、地址宽度、mask 写入、版本/锁策略和 owner 明确记录 |
| event baseline / temporary | typed round buffer 或 partition-local scratch | 生命周期限于指定 eval/round，不能误提升为 persistent state |

例如，一个 37-bit 4-state 状态不应只留下 `value_id` 和 `width=37`，而应能反查到类似：

```text
semantic_type = logic(width=37, signed=false, state=4)
representation = cpu-cpp::LogicWord64
storage = object_member(owner=SimTop, update=staged_then_commit, alignment=16)
```

C++ emitter 只消费这份计划生成声明、读写 accessor 和 commit 代码；若某个类型或存储契约没有 CPU dialect 能力声明，应在 verify/lowering 阶段失败。

通用方言只定义跨后端都能理解的语义类别，具体名字可以后续调整：

- pure compute、constant、IO/read boundary；
- state/memory read 和 write；
- event sample/edge、cycle/fixed-point boundary；
- external call、system task 等可能有副作用的操作。

每个 dialect 至少注册名称和版本，并为其 op 提供 schema、verifier、effect summary、可分区性约束和可用的 lowering/emit 能力声明。通用层可以保存未知 dialect 的带版本属性，但在没有对应能力声明时必须拒绝继续 emit，而不是静默按普通组合逻辑处理。

值边只表达数据流。会改变可观察行为的顺序不能藏在 emitter 中，应该通过效果边或显式 token 表达，例如：

```text
state read -> compute -> staged write -> commit -> state visible
event sample -> event-sensitive op
```

首版建议采用与当前 grhsim 一致的 full-cycle 模型：组合求值、事件判定和状态提交的边界显式化；后续再扩展到更细的时间轮或异步后端。`reg-to-mem`、memory normalization 等只影响仿真执行形态的变换，应作为 `sim` 方言上的 graph pass，而不是继续扩展 GRH 的综合语义。

### 2.2 `PartitionTree`

分区是 `SimGraph` 的子图视图和所有权描述，不复制节点语义。建议最小字段为：

```text
Partition
  id, parent, children
  owned_nodes
  boundary_inputs, boundary_outputs
  quotient_edges
  constraints, annotations
```

约束：

- 根分区覆盖目标图；同一层的子分区默认节点所有权互斥，子分区并集等于父分区的可分节点集合。
- 跨分区的值边和效果边都必须落成 boundary port；不能靠 emitter 推测 fanout 或顺序。
- 每个分区都有可验证的内部子图和对外契约。复制、镜像或共享节点必须用显式映射标注，不能破坏“所有权互斥”假设。
- 分区类型是提示和约束，不是硬编码的运行时语义。`compute-node`、`compute-supernode`、`commit`、`repcut` 都可以是不同的 annotation/kind。

这样既能表达 GSim 风格的两级聚合，也能表达 RepCut 的递归细分：

```text
root
  +-- compute-supernode
  |     +-- compute-node
  |     +-- compute-node
  +-- commit-partition
```

### 2.3 `SchedulePlan`

调度不是对图做一次拓扑排序，而是一个可嵌套、可换后端的执行数据结构：

```text
SchedulePlan
  backend_id, version
  tasks: {task_id, partition_id, phase, resource, activation}
  dependencies: {from, to, kind}
  synchronizations: barrier/join/queue...
  memory_model, determinism_policy
  backend_attributes
```

`SchedulePlan` 同时记录两类信息：

- 静态信息：分区间依赖、阶段顺序、资源绑定和同步点。
- 动态信息：输入/状态变化如何激活任务、事件谓词和本轮可重复执行规则。

父任务可以展开为子任务计划，因此调度层也保持嵌套。计划只能引用现存的 `PartitionId`，不能在 emit 阶段偷偷创建新的执行单元。

#### 首个后端：多核 CPU

第一版采用易验证的 fork-join 模型：

1. 每个 cycle/eval 根据 activation 生成 ready task 集合。
2. 无未满足值边或效果边的纯 compute 分区可分配给不同 worker。
3. 每个分区内部保持确定性的局部顺序；边界值通过版本化 buffer 或只读快照传递。
4. 在 commit、可观察输出和跨阶段边界设置显式 barrier/join。
5. 冲突写入必须由效果依赖或统一 commit 任务排序，禁止依赖 host data race。

先实现单线程执行同一 `SchedulePlan`，再打开多 worker；两者应共享验证器和语义，不维护两套 schedule。work-stealing、NUMA 感知和设备协同属于后续 CPU dialect/优化。

## 3. Pass 与编排系统

把当前“pass 写 session、emitter 读 session”改为一个显式编译单元：

```text
SimCompilationUnit {
  sim_graph
  partition_tree (optional until partitioning)
  representation_plans (optional until backend lowering)
  schedule_plan (optional until scheduling)
  analyses, provenance, diagnostics
}
```

每个 pass 声明：输入层、输出/修改层、所需 analysis、保留或失效的 analysis、参数和可验证的不变量。建议分为：

- `AnalysisPass`：只读，生成可缓存分析结果；
- `SimGraphPass`：规范化或重写图；
- `PartitionPass`：创建、细分、合并或重标注分区；
- `SchedulePass`：针对某个 backend 生成或调整计划；
- `EmitPass`：只读消费三层 IR，生成后端代码和 manifest。

图发生结构变化时，相关分区和调度默认标记为 stale；只有提供稳定 ID 映射和证明的 pass 才能保留它们。Pass manager 在层间和每个可配置检查点运行 verifier，并支持把三层 IR 序列化后单独回放。

建议的首条 pipeline：

```text
grh-to-sim (flattened)
  -> sim-normalize
  -> sim-reg-to-mem / other sim-only rewrites
  -> sim-analysis
  -> sim-partition (compute node/supernode or repcut)
  -> cpu-represent (type/layout/storage plan)
  -> sim-schedule(cpu)
  -> sim-verify
  -> emit(cpu)
```

最小 verifier 规则：

- graph：result 唯一定义、operand 类型匹配；纯值子图中的环必须通过显式 state/event/effect 边表达；所有副作用 op 都有完整 effect summary。
- type/storage：语义类型、表示类型和存储契约分别可追溯；表示布局满足宽度、lane、尾部 mask 和对齐约束；每个 state 的 read/write/commit 路径与 transition 规则一致。
- partition：节点所有权和父子关系闭合；每条跨分区值边/效果边都有 boundary 记录；分区不能引用不存在的 ID。
- schedule：任务引用现存分区；任务依赖覆盖对应商图和效果边；冲突写入有确定顺序或显式同步；嵌套计划的资源和阶段约束一致。

## 4. 序列化和诊断

首版优先使用带版本号的 JSON，便于代码审计；性能稳定后再增加二进制封装。建议一个 bundle 具有以下顶层信息：

```text
format: wolvrix.grhsim.bundle.v1
graph: ...
partitions: ...
backend_plans: ...
schedules: ...
dialects: ...
provenance: source/pass/version information
```

禁止把核心对象只存成未命名的 session slot。兼容期可以提供 `activity-schedule session -> PartitionTree/SchedulePlan` adapter，adapter 的结果必须能导出并通过同一套 verifier。诊断至少能按 ID、symbol、source location 互相反查。

## 5. 迁移和最小可行版本

| 阶段 | 交付 |
| --- | --- |
| A | 定义 `SimGraph` 核心对象、类型/存储契约、effect 语义、ID、JSON v1 和 verifier |
| B | 将现有 `activity-schedule` session 物化为 `PartitionTree + SchedulePlan`，legacy emitter 保持可用 |
| C | 把 compute node/supernode、commit/event 和现有 activation 规则迁入显式 pass |
| D | 迁移 `reg-to-mem` 等 sim-only pass，移除其对 GRH 综合语义的依赖 |
| E | 实现 CPU/C++ `RepresentationPlan`、单线程和多线程 emitter；以同一计划做确定性和功能回归 |
| F | 后端/方言扩展，最后再退役旧 session 适配层 |

MVP 的验收条件：

- 小图可以 bundle round-trip，图、分区、计划经 verifier 后不依赖隐藏 session；
- CPU/C++ emit 产物能从任一 `ValueId`/`StateId` 反查语义类型、物理类型、布局和存储路径；
- 两级嵌套分区可表达并可 emit；
- CPU 单线程结果与当前 grhsim 基线等价，多线程结果确定且无未声明冲突；
- 至少一个 HDLBits 用例和一个代表性大图完成 `lower -> partition -> schedule -> emit` 全链路。

## 6. 首版需要尽早决定的问题

1. full-cycle/fixed-point 是否作为通用核心时间模型，还是作为 CPU dialect 的一种实现。
2. effect edge 的粒度：按 state object、memory port，还是按更细的 token；多写冲突采用何种一致性规则。
3. replication/clone 节点的所有权和 provenance 如何序列化。
4. 动态 activation 是计划字段、运行时输入，还是独立的 activation dialect。
5. dialect 的版本兼容和后端能力声明格式。
6. 2-state/4-state 的默认 ABI、宽值 lane 布局，以及 dense/sparse memory 的统一接口。

建议先冻结的默认值是：通用核心只规定显式值边/效果边和提交边界，CPU 后端采用确定性的 fork-join；复杂优化留在后续方言和 pass 中。

## 7. 参考

- [GrhSIM 仿真模型形式化定义](./simulation-model.md)
- [GrhSIM 现状](../GrhSIM现状.md)
- [当前 activity-schedule 文档](../../../wolvrix/docs/transform/activity-schedule.md)
- [当前 GrhSIM 调度语义](../../../wolvrix/docs/emit/grhsim-scheduling.md)
- [GSim 式活动度感知仿真计划](../wolvrix-gsim-activity-aware-sim-plan.md)
