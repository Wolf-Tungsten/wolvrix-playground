# GrhSIM Activity-Schedule Pass 草案

## 1. 基本目标与调度模型

GrhSIM 是基于 Wolvrix 框架和 GRH IR 构建的仿真器，将 GRH Design 转换为可执行的 C++ 代码。

`activity-schedule` pass 面向单个 GRH graph，输出活动度超图。活动度超图包含：

1. `activity supernode` 划分
2. `supernode` DAG 与拓扑序
3. `supernode` 的活动传播关系
4. `supernode` 的 `event-domain-set`
5. `head-eval supernode` 标记

### 1.1 输入前提

输入 graph 满足：

- 已展平
- 无 XMR
- 无 blackbox
- 无组合逻辑环
- 若存在 latch，已完成 `latch-transparent-read`

### 1.2 执行模型

GrhSIM 的接口模型：

1. 用户设置输入
2. 用户调用 `eval()`
3. 用户读取输出

GrhSIM 支持单线程和多线程。本文采用单线程 full-cycle、activity-driven 模型。

```text
for each cycle:
    seed_head_activity()
    for supernode in topo_order:
        if guard(supernode):
            eval(supernode)
            propagate_activity(supernode)
    commit_state_updates()
```

### 1.3 Supernode

`supernode` 是调度和代码生成的基本单元。一个 `supernode` 内包含多个 op；cpp emit 将其发射为一段连续的 C++ 求值代码。

采用 `supernode` 粒度的原因：

- 逐 op guard 开销过高
- 逐 op 发射破坏代码连续性

### 1.4 Guard

每个 `supernode` 都有 guard。guard 由两部分决定：

- `propagated_activity_present`
- `event_domain_set_hit`

```text
supernode_active =
    event_domain_set_hit
    && propagated_activity_present
```

定义：

- `propagated_activity_present`：当前 `supernode` 的活动位已被置位；来源可以是前驱 `supernode` 传播，也可以是 `eval()` 入口对首批节点的激活
- `event_domain_set_hit`：当前 `eval()` 命中了该 `supernode` 关联的某个 `event-domain`；空 `event-domain` 视为恒命中
- `head-eval supernode`：供 emit 查找 `eval()` 入口激活起点使用的 `supernode` 标记，不参与 guard 公式

## 2. 输入、输出与约束

### 2.1 输入参数

- `path`
  - 类型：graph path
  - 含义：指定一个待处理的 graph

- `supernode-max-size`
  - 类型：整数
  - 含义：单个 `supernode` 允许包含的 op 数量上限

- `enable-coarsen`
  - 类型：布尔
  - 含义：启用局部粗化

- `enable-chain-merge`
  - 类型：布尔
  - 含义：启用单入单出链式合并

- `enable-sibling-merge`
  - 类型：布尔
  - 含义：启用前驱集合相同的兄弟节点合并

- `enable-forward-merge`
  - 类型：布尔
  - 含义：启用局部数据搬运链合并

- `enable-refine`
  - 类型：布尔
  - 含义：启用分段后的局部 refine

- `refine-max-iter`
  - 类型：整数
  - 含义：局部 refine 的最大迭代轮数

- `enable-replication`
  - 类型：布尔
  - 含义：启用低成本边界 op 复制

- `replication-max-cost`
  - 类型：整数
  - 含义：允许复制的 op 成本上限

- `replication-max-targets`
  - 类型：整数
  - 含义：单个源 op 允许复制到的目标 `supernode` 数量上限

- `cost-model`
  - 类型：枚举
  - 取值：`edge-cut`
  - 含义：动态规划分段代价模型

### 2.2 Session 输出

输出写入 session，命名空间固定为：

```text
<path>.activity_schedule.xxx
```

当前输出：

- `<path>.activity_schedule.supernodes`
- `<path>.activity_schedule.supernode_to_ops`
- `<path>.activity_schedule.supernode_to_op_symbols`
- `<path>.activity_schedule.op_to_supernode`
- `<path>.activity_schedule.op_symbol_to_supernode`
- `<path>.activity_schedule.dag`
- `<path>.activity_schedule.topo_order`
- `<path>.activity_schedule.head_eval_supernodes`
- `<path>.activity_schedule.op_event_domains`
- `<path>.activity_schedule.value_event_domains`
- `<path>.activity_schedule.supernode_event_domains`
- `<path>.activity_schedule.event_domain_sinks`
- `<path>.activity_schedule.event_domain_sink_groups`

这些结果需要支持两类快速查询：

- `supernode -> op` 集合
- `op -> supernode`

所有以 `op` 为键或值的 session 输出，都绑定到本 pass 完成时的最终 frozen graph snapshot。
`op-symbol` 相关输出保留 phase A / phase B 内部稳定锚点，供调试、校验和跨 snapshot 对照使用。

### 2.3 实现约束

输入图规模可能达到 `100M+ op`。实现约束：

- 不做全图多轮高复杂度扫描
- 不为 `event-domain` 单独建立与原图同规模的重型中间图
- 分图和反标都复用现有 use-def 与 `supernode` 结果
- 算法尽量采用线性或接近线性的遍历方式
- 充分而合理地利用多线程并行加速
- 不把 `OperationId` 当作跨改图阶段的持久锚点；内部持久锚点使用 op symbol

### 2.4 并行化要求

当前实现仍为单线程。后续并行化优先放在以下步骤：

- `phase A1`
  - 按 op 分块收集局部依赖和候选集合

- `phase A3`
  - 在互不重叠区域并行收集粗化候选

- `phase A5`
  - 并行计算边界迁移收益

- `phase A6`
  - 并行筛选可复制边界 op

- `phase B1`
  - 并行识别 sink
  - 并行提取 `event-domain-signature`

- `phase B2`
  - 以 sink 或 `event-domain-signature` 为粒度并行反标

需要串行的步骤：

- `core/toposort` 的最终调用
- `phase A4` 的连续分段动态规划
- 涉及全局拓扑顺序变更的提交阶段

并行实现要求：

- 先做局部收集，再做集中提交
- 避免多个线程直接写共享 `supernode` 结构
- 保持结果确定性

## 3. phase A 分图

### 3.1 参数默认值

当前默认配置：

- `enable-coarsen = true`
- `enable-chain-merge = true`
- `enable-sibling-merge = true`
- `enable-forward-merge = true`
- `enable-refine = true`
- `enable-replication = true`
- `replication-max-cost = 2`
- `replication-max-targets = 8`
- `cost-model = edge-cut`

### 3.2 phase A1：建立划分视图

建立轻量级划分视图。当前实现直接物化：

- 参与划分的 op 列表
- op 之间的组合依赖
- 稳定拓扑序
- 每个 op 的内部稳定锚点

当前主结构：

- `topoOps`
- `topoSymbols`
- `topoKinds`
- `topoEdges`
- `topoPosByOpIndex`

`supernode` 级邻接关系不单独持久化，在后续 phase 中按当前划分结果重建。

划分对象限定为可执行求值 op。

- 不参与分图：`kRegister`、`kMemory`、`kLatch`
- 参与分图但按特殊语义处理：`kRegisterWritePort`、`kMemoryWritePort`、`kLatchWritePort`、`kSystemTask`、`kDpicCall`

这些特殊语义 op 在 phase A 中保留为稳定边界，不被粗化、跨段吞并或复制。原因有三点：

- `kRegisterWritePort`、`kMemoryWritePort`、`kLatchWritePort` 是状态更新落点，也是 phase B 的核心 sink 类型
- `kSystemTask`、`kDpicCall` 承载副作用或宿主交互语义，代码发射时通常需要独立处理
- 将它们并入普通组合 `supernode` 会混合纯组合求值与状态更新 / 副作用边界，增加 `event-domain` 反标、起点识别、调度次序和复制合法性判断的复杂度

GRH IR 已经提供分图所需的核心结构：

- SSA `Value` 单定义、多使用
- `valueDef`
- `valueUsers`
- `Operation.operands()`
- `Operation.results()`
- `OperationKind`
- `core/toposort` 组件

实现要求：

- 每个参与分图的 op 都必须有 symbol；若原 op 没有 symbol，则在进入分图阶段前补齐内部 symbol
- phase A 和 phase B 内部所有需要跨改图阶段保留的 op 归属关系，都使用 `SymbolId`
- 统计信息、工作队列、局部缓存仍可临时按当前 `OperationId` / `ValueId` 编址

拓扑排序直接使用 `wolvrix` 的核心 `toposort` 组件，不重复实现独立拓扑排序逻辑。

### 3.3 phase A2：初始化 supernode seed

初始化规则：

- 每个可参与划分的 op 先形成一个 seed `supernode`
- 状态写口和副作用 op 单独保留，作为稳定边界

这些 op 自身形成独立 `supernode`，并始终作为后续粗化、分段、refine、复制的阻隔点。

### 3.4 phase A3：局部粗化

局部粗化采用适合 GRH IR 的规则：

- `mergeOut1`
  - 出度为 1 的 `supernode` 向唯一后继合并

- `mergeIn1`
  - 入度为 1 的 `supernode` 向唯一前驱合并

- `mergeSiblings`
  - 前驱集合相同的兄弟 `supernode` 合并

- `mergeForwarders`
  - 局部数据搬运链聚合到相邻 `supernode`
  - 重点对象：`kAssign`、`kConcat`、`kSliceStatic`

这些规则都要求局部、线性或接近线性，不引入全局高复杂度搜索。

### 3.5 phase A4：动态规划分段

参考 GSim，在 coarse `supernode` 的拓扑序上做连续分段。

约束与代价：

- 连续分段
- `supernode-max-size` 为硬约束
- 切边数为主要代价

切边指分段后落在不同 `supernode` 之间的依赖边。

### 3.6 phase A5：局部 refine

局部 refine 在连续分段结果上做边界搬移，继续减少跨 `supernode` 切边。

当前实现采用相邻 segment 边界 cluster 的局部迁移：

1. 对每个相邻边界，检查左段末尾 cluster 能否移到右段
2. 检查右段开头 cluster 能否移到左段
3. 计算 cut gain
4. 提交单轮最佳正收益迁移
5. 迭代到收敛或达到 `refine-max-iter`

约束：

- 只在相邻 segment 之间移动
- 迁移对象是边界 cluster
- 不违反 `supernode-max-size`
- 不跨越稳定边界

收益函数：

- 内部化的边计正收益
- 新增切边计负收益

### 3.7 phase A6：复制低成本边界 op

`phase A6` 在分段和 refine 之后复制低成本边界 op，减少跨 `supernode` 依赖。

当前实现条件：

- 仅复制单结果 op
- 纯组合、无副作用、无状态语义
- 位于 `supernode` 边界，且存在跨 `supernode` consumer
- op 成本不超过 `replication-max-cost`
- 目标 `supernode` 数量不超过 `replication-max-targets`

当前候选类型：

- `kConstant`
- `kAssign`
- `kMux`
- `kConcat`
- `kReplicate`
- `kSliceStatic`
- `kSliceDynamic`
- 简单比较、逻辑、移位、`kAdd`、`kSub`

不复制到以下目标：

- 稳定边界 `supernode`

禁止复制的语义边界：

- `kSystemTask`
- `kDpicCall`
- `kRegisterWritePort`
- `kMemoryWritePort`
- `kLatchWritePort`
- `kRegisterReadPort`
- `kMemoryReadPort`
- `kLatchReadPort`
- `kRegister`
- `kMemory`
- `kLatch`

维护动作：

- 为复制 op 和 result 分配新 symbol
- 将目标 consumer 改写到复制后的 result
- 若原 op 结果已无剩余 use，删除原 op
- 更新 `supernode -> op-symbol`
- 最终在 `phase A7` 统一重建 DAG 和拓扑序

当前实现的复制粒度是单个边界 op，不做表达式树级递归复制。

### 3.8 phase A7：物化分图结果

物化结果包括：

- `activity supernode` 集合
- `supernode -> op`
- `op -> supernode`
- `supernode` DAG
- 拓扑序
- `supernode -> is_head_eval_supernode`

物化步骤：

1. 完成 `phase A` 内全部图改写
2. 对 graph 执行一次最终 `freeze()`
3. 遍历 frozen graph，建立 `op-symbol -> frozen OperationId`
4. 根据内部保存的 `op-symbol -> supernode` 关系，生成最终的 `supernode -> op` 和 `op -> supernode`
5. 在同一份 frozen snapshot 上计算 `supernode` DAG、拓扑序和 `head-eval supernode` 标记

这样可以避免在复制、删边、删 op 后直接持有失效的旧 `OperationId`。

`is_head_eval_supernode` 由分图结果直接确定，用于标记在一次 `eval()` 入口可能首先被激活的 `supernode`。判定条件为该 `supernode` 直接消费以下来源之一：

- graph 输入
- 状态读口

## 4. phase B event-domain 反标

### 4.1 phase B1：建立反标起点

sink 节点满足：

- 位于组合 use-def 路径的末端
- 代表状态更新、语句侧副作用或可观察输出边界

当前 sink 集合：

- `kRegisterWritePort`
- `kMemoryWritePort`
- `kLatchWritePort`
- 无返回值的 `kSystemTask`
- 无返回值的 `kDpicCall`
- result 最终直接绑定到 output port / inout out / inout oe 的 op

对每个 sink，需要识别：

- 哪些输入是 event value
- 每个 event value 对应的 event edge

在此基础上形成正规 `event-domain-signature`：

- 基本元素是 `(event value, event edge)`
- 按确定顺序排序
- 生成稳定签名

`event-domain` 可以为空。空 `event-domain` 表示该 sink 不受事件命中约束，在每次 `eval()` 中都可进入调度。

输出：

- sink op 集合
- `sink op -> event-domain-signature`
- `event-domain-signature -> sink op`

### 4.2 phase B2：反向标注 event-domain-set

从每个 sink 出发，沿 use-def 反向传播，把对应 `event-domain-signature` 标到经过的 op、value 和 `supernode` 上。反标使用 `phase A7` 产出的最终 frozen snapshot。

反标范围：

- sink op 的组合输入锥
- 输入锥上的中间 value
- 输入锥覆盖到的 `activity supernode`

反标停止条件：

- 到达输入端口
- 到达状态读口
- 到达另一个 sink 的边界
- 到达不参与当前传播的特殊语义节点

输出：

- `op -> event-domain-set`
- `value -> event-domain-set`
- `supernode -> event-domain-set`
