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
- `<path>.activity_schedule.op_to_supernode`
- `<path>.activity_schedule.dag`
- `<path>.activity_schedule.topo_order`
- `<path>.activity_schedule.head_eval_supernodes`
- `<path>.activity_schedule.supernode_event_domains`
- `<path>.activity_schedule.event_domain_sinks`

这些结果需要支持两类快速查询：

- `supernode -> op` 集合
- `op -> supernode`

### 2.3 实现约束

输入图规模可能达到 `100M+ op`。实现约束：

- 不做全图多轮高复杂度扫描
- 不为 `event-domain` 单独建立与原图同规模的重型中间图
- 分图和反标都复用现有 use-def 与 `supernode` 结果
- 算法尽量采用线性或接近线性的遍历方式
- 充分而合理地利用多线程并行加速

### 2.4 并行化策略

适合并行的步骤：

- `phase A1`
  - 按 op 分块收集局部统计信息
  - 并行构建局部依赖边和局部候选集合

- `phase A3`
  - 在互不重叠的局部区域并行收集粗化候选
  - 合并提交按确定顺序执行

- `phase A5`
  - 并行计算候选迁移收益
  - 提交阶段串行，或按不相交写集批量提交

- `phase A6`
  - 并行筛选可复制边界 op
  - 复制提交按目标 `supernode` 分桶后合并

- `phase B1`
  - 并行识别 sink 节点
  - 并行提取 `event-domain-signature`

- `phase B2`
  - 以 sink 或 `event-domain-signature` 为粒度并行反标
  - 局部标注结果统一合并

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
- `cost-model = edge-cut`

### 3.2 phase A1：建立划分视图

建立轻量级划分视图，包含：

- 参与划分的 op 列表
- op 之间的组合依赖
- 稳定拓扑序
- 每个 op 的局部统计信息，例如 fanin、fanout、跨边数

划分对象限定为可执行求值 op。

- 不参与分图：`kRegister`、`kMemory`、`kLatch`
- 参与分图但按特殊语义处理：`kRegisterWritePort`、`kMemoryWritePort`、`kLatchWritePort`、`kSystemTask`、`kDpicCall`

GRH IR 已经提供分图所需的核心结构：

- SSA `Value` 单定义、多使用
- `valueDef`
- `valueUsers`
- `Operation.operands()`
- `Operation.results()`
- `OperationKind`
- `core/toposort` 组件

实现上直接复用 `Graph` 的 op/value 编号，统计信息采用按 `OperationId` / `ValueId` 编址的数组存储。
拓扑排序直接使用 `wolvrix` 的核心 `toposort` 组件，不重复实现独立拓扑排序逻辑。

### 3.3 phase A2：初始化 supernode seed

初始化规则：

- 每个可参与划分的 op 先形成一个 seed `supernode`
- 状态写口和副作用 op 单独保留，作为稳定边界

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

局部 refine 在已有分段结果上做局部迁移，继续减少跨 `supernode` 切边。

步骤：

1. 从边界 op 生成候选迁移
2. 计算候选收益
3. 检查合法性
4. 提交正收益迁移
5. 迭代到收敛或达到 `refine-max-iter`

候选迁移约束：

- 目标限定为相邻 `supernode` 或局部可达的前驱/后继 `supernode`
- 优先支持单 op 迁移
- 不破坏拓扑顺序
- 不违反 `supernode-max-size`
- 不跨越状态写口和副作用边界

收益函数：

- 迁移后内部化的边记为正收益
- 新增跨 `supernode` 边记为负收益

提交后同步更新：

- `supernode -> op`
- `op -> supernode`
- 局部切边统计
- 必要时更新 `supernode` DAG 与拓扑序

### 3.7 phase A6：复制低成本边界 op

`phase A6` 参考 GSim 的 replication 优化，在分段和 refine 之后复制低成本边界 op，减少跨 `supernode` 依赖。

输入：

- `activity supernode`
- `supernode` DAG
- `supernode -> op`
- `op -> supernode`

输出：

- 更新后的 `activity supernode`
- 更新后的 `supernode` DAG
- 更新后的 `supernode -> op`
- 更新后的 `op -> supernode`

可复制 op 条件：

- 纯组合计算
- 无副作用
- 无状态语义
- 表达式规模小，复制成本低
- 位于 `supernode` 边界，且存在跨 `supernode` consumer

候选类型：

- `kAssign`
- `kMux`
- `kConcat`
- `kSliceStatic`
- `kSliceDynamic`
- 简单逻辑和算术 op

禁止复制：

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

复制触发条件：

- 原 op 计算成本低于阈值
- 原 op 至少连接到一个外部 `supernode`
- 复制后可减少跨 `supernode` 边

复制后的维护：

- 为复制出的 op 分配新 op id
- 将目标 consumer 改写到复制后的 result
- 原 op 是否保留取决于本 `supernode` 内是否仍有使用者
- 同步更新 `supernode` DAG、映射与局部统计信息

### 3.8 phase A7：物化分图结果

物化结果包括：

- `activity supernode` 集合
- `supernode -> op`
- `op -> supernode`
- `supernode` DAG
- 拓扑序
- `supernode -> is_head_eval_supernode`

`is_head_eval_supernode` 由分图结果直接确定，用于标记在一次 `eval()` 入口可能首先被激活的 `supernode`。判定条件为该 `supernode` 直接消费以下来源之一：

- graph 输入
- 状态读口
- 外部可注入活动源

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

从每个 sink 出发，沿 use-def 反向传播，把对应 `event-domain-signature` 标到经过的 op、value 和 `supernode` 上。

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
