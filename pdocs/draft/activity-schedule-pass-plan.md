# GrhSIM Activity-Schedule Pass 草案

## 1. 基本目标与调度模型

GrhSIM 是基于 Wolvrix 框架和 GRH IR 构建的仿真器，将 GRH Design 转换为可执行的 C++ 代码。

`activity-schedule` pass 输出活动度超图，核心结果包括：

1. `supernode` 划分
2. `supernode` 依赖 DAG 与拓扑序
3. `supernode` 的活动传播关系与 `event-domain-set`

### 1.1 输入前提

输入 graph 满足：

- 已展平
- 无 XMR
- 无 blackbox
- 无组合逻辑环

### 1.2 单线程调度模型

接口模型：

1. 用户设置输入
2. 用户调用 `eval()`
3. 用户读取输出

执行模型：

```text
for each cycle:
    for supernode in topo_order:
        if guard(supernode):
            eval(supernode)
            propagate_activity(supernode)
    commit_state_updates()
```

GrhSIM 支持单线程和多线程。本文采用单线程 full-cycle、activity-driven 模型。

### 1.3 Supernode

`supernode` 是调度和代码生成的基本单元。一个 `supernode` 内包含多个 op；cpp emit 将其发射为一段连续的 C++ 求值代码。

采用 `supernode` 粒度的原因：

- 逐 op guard 开销过高
- 逐 op 发射破坏代码连续性

### 1.4 Guard

每个 `supernode` 都有 guard。guard 由两个因素决定：

- 活动度传播
- `event-domain-set`

抽象形式：

```text
supernode_active =
    event_domain_set_hit
    && propagated_activity_present
```

定义：

- `propagated_activity_present`：某个拓扑前驱完成求解，并修改了当前 `supernode` 输入侧依赖的信号
- `event_domain_set_hit`：当前 `eval()` 命中了该 `supernode` 关联的某个 `event-domain`；空 `event-domain` 视为恒命中
- `is_head_eval_supernode`：供后续 emit 查找调度起点使用的 `supernode` 标记，不参与 `supernode_active` 判定

## 2. 整体流程与输出约束

### 2.1 流程

1. 建立 `activity supernode`
2. 反向标注 `event-domain-set`

sink 节点指带事件语义的状态更新节点，例如 `kRegisterWritePort`。

### 2.2 输出数据结构

输出至少包含：

- `activity supernode` 集合
- `supernode -> op` 映射
- `op -> supernode` 映射
- `supernode` 依赖关系与拓扑序
- `supernode -> is_head_eval_supernode`
- `supernode -> event-domain-set` 映射
- `event-domain-signature -> sink op` 集合

需要支持双向快速查询：

- 给定 `supernode`，快速得到其中包含的 op
- 给定 op，快速得到其所属 `supernode`

### 2.3 实现约束

输入图规模可能达到 `100M+ op`。实现约束：

- 不做全图多轮高复杂度扫描
- 不为 `event-domain` 建立与原图同规模的重型中间图
- `event-domain-set` 标注复用已有 use-def 和 `supernode` 结果
- 算法尽量采用线性或接近线性的遍历方式

## 3. phase A 分图

### 3.1 phase A pass 参数

第一版先收敛为以下参数：

- `supernode-max-size`
  - 类型：整数
  - 含义：单个 `supernode` 允许包含的 op 数量上限
  - 作用阶段：`phase A4`

- `enable-coarsen`
  - 类型：布尔
  - 含义：是否启用局部粗化
  - 作用阶段：`phase A3`

- `enable-chain-merge`
  - 类型：布尔
  - 含义：是否启用单入单出链式合并
  - 作用阶段：`phase A3`

- `enable-sibling-merge`
  - 类型：布尔
  - 含义：是否启用前驱集合相同的兄弟节点合并
  - 作用阶段：`phase A3`

- `enable-forward-merge`
  - 类型：布尔
  - 含义：是否启用局部数据搬运链合并
  - 作用阶段：`phase A3`

- `enable-refine`
  - 类型：布尔
  - 含义：是否启用分段后的局部 refine
  - 作用阶段：`phase A5`

- `refine-max-iter`
  - 类型：整数
  - 含义：局部 refine 的最大迭代轮数
  - 作用阶段：`phase A5`

- `cost-model`
  - 类型：枚举
  - 取值：`edge-cut`
  - 含义：动态规划分段代价模型
  - 作用阶段：`phase A4`

第一版默认配置可以先固定为：

- 开启 `enable-coarsen`
- 开启 `enable-chain-merge`
- 开启 `enable-sibling-merge`
- 开启 `enable-forward-merge`
- 开启 `enable-refine`
- `refine-max-iter` 取较小默认值
- `cost-model = edge-cut`

### 3.2 phase A1：建立划分视图

建立轻量级划分视图，包含：

- 参与划分的 op 列表
- op 之间的组合依赖
- 稳定拓扑序
- 每个 op 的局部统计信息，例如 fanin、fanout、跨边数

参与分图的对象限定为可执行求值 op。`kRegister`、`kMemory`、`kLatch` 这类声明 op 不进入分图对象集合。`kRegisterWritePort`、`kMemoryWritePort`、`kLatchWritePort`、`kSystemTask`、`kDpicCall` 保留在划分视图中，后续按固定语义处理。

### 3.3 phase A2：初始化 `supernode` seed

初始化规则：

- 每个可参与划分的 op 先形成一个 seed `supernode`
- 状态写口和副作用 op 在 seed 阶段单独保留，作为稳定边界

### 3.4 phase A3：局部粗化

局部粗化采用适合 GRH IR 的规则。

`mergeResetAll`、`mergeWhenNodes` 这类 GSim 规则不直接适用于 GRH IR。GRH IR 中 reset 优先级和控制结构已经落到普通 use-def 图与写口语义中，不再保留单独的 when/reset 树形结构，因此没有必要沿用这两类规则。

第一版局部粗化规则收敛为：

- `mergeOut1`
  - 将出度为 1 的 `supernode` 向唯一后继合并

- `mergeIn1`
  - 将入度为 1 的 `supernode` 向唯一前驱合并

- `mergeSiblings`
  - 将前驱集合相同的兄弟 `supernode` 合并

- `mergeForwarders`
  - 将局部数据搬运链聚合到相邻 `supernode`
  - 重点对象包括 `kAssign`、`kConcat`、`kSliceStatic` 等低成本搬运 op

这些规则都属于局部、线性或接近线性的合并，不引入全局高复杂度搜索。

### 3.5 phase A4：动态规划分段

参考 GSim，在 coarse `supernode` 的拓扑序上做连续分段。

约束与代价：

- 连续分段
- `supernode-max-size` 为硬约束
- 切边数为主要代价

切边指分段后落在不同 `supernode` 之间的依赖边。

### 3.6 phase A5：局部 refine

`phase A5` 对应 GSim 中的 refine 思路，在已有分段结果上做局部迁移，继续减少跨 `supernode` 切边。

基本步骤：

1. 生成候选迁移
2. 计算每个候选迁移的收益
3. 检查合法性约束
4. 提交收益为正的迁移
5. 迭代到收敛或达到 `refine-max-iter`

候选迁移生成：

- 从边界 op 出发构造候选
- 候选目标限定为相邻 `supernode`，或局部可达的前驱/后继 `supernode`
- 第一版优先支持单 op 迁移

收益计算：

- 以切边减少量作为主要收益
- 迁移后内部化的边记为正收益
- 新增的跨 `supernode` 边记为负收益
- 第一版不引入按位宽、活动概率或 profile 的加权模型

合法性检查：

- 只考虑相邻或局部可达的 `supernode`
- 只移动单个 op 或很小的局部片段
- 不破坏拓扑顺序
- 不违反 `supernode-max-size`
- 不跨越状态写口和副作用边界

提交更新：

- 更新 `supernode -> op`
- 更新 `op -> supernode`
- 更新局部切边统计
- 必要时更新 `supernode` DAG 和拓扑序

refine 完成后进入 `phase A6`。

### 3.7 phase A6：复制低成本边界 op

`phase A6` 参考 GSim 的 replication 优化，在动态规划分段和局部 refine 之后复制低成本边界 op，减少跨 `supernode` 依赖。

该 phase 的目标不是改变拓扑结构，而是把位于边界上的低成本纯计算 op 下沉到消费它们的后继 `supernode`，缩短跨 `supernode` 的 use-def 边。

输入：

- `phase A5` 输出的 `activity supernode`
- `supernode` DAG
- `supernode -> op` / `op -> supernode` 映射

输出：

- 更新后的 `activity supernode`
- 更新后的 `supernode` DAG
- 更新后的 `supernode -> op` / `op -> supernode` 映射

可复制 op 需要同时满足以下条件：

- 属于纯组合计算
- 无副作用
- 无状态语义
- 表达式规模小，复制成本低
- 位于 `supernode` 边界，且存在跨 `supernode` consumer

第一版可优先考虑的候选类型：

- `kAssign`
- `kMux`
- `kConcat`
- `kSliceStatic`
- `kSliceDynamic`
- 简单逻辑和算术 op

禁止复制的 op 包括：

- `kSystemTask`
- `kDpicCall`
- `kRegisterWritePort`
- `kMemoryWritePort`
- `kLatchWritePort`
- `kRegisterReadPort`
- `kMemoryReadPort`
- `kLatchReadPort`
- 声明 op，例如 `kRegister`、`kMemory`、`kLatch`

这些 op 不能复制的原因分别是：

- `kSystemTask`、`kDpicCall` 具有副作用
- 写口 op 具有状态更新语义
- 读口 op 直接绑定状态对象，复制后会引入额外状态读取节点
- 声明 op 不是求值节点

复制触发条件：

- 原 op 的计算成本低于阈值
- 原 op 至少连接到一个外部 `supernode`
- 复制后可减少跨 `supernode` 边
- 复制不会引入新的语义歧义

复制后的维护要求：

- 新复制出的 op 需要有新的 op id
- consumer 改写到复制后的 op result
- 原 op 保留或删除取决于本 `supernode` 内是否仍有使用者
- `supernode` DAG、`supernode -> op`、`op -> supernode`、局部统计信息都要同步更新

### 3.8 phase A7：物化分图结果

物化结果包括：

- `activity supernode` 集合
- `supernode -> op` 映射
- `op -> supernode` 映射
- `supernode` DAG 与拓扑序
- `supernode -> is_head_eval_supernode`

`is_head_eval_supernode` 由分图结果直接确定，用于标记在一次仿真头部需要首先进入调度的 `supernode`。

### 3.9 利用 GRH IR

分图 phase 直接利用 GRH IR 现有结构：

- SSA `Value` 单定义、多使用
- `valueDef` 查找 producer op
- `valueUsers` 查找 consumer op
- `Operation.operands()` / `Operation.results()` 遍历 use-def 边
- `OperationKind` 驱动 seed 初始化、粗化规则、边界判定

实现要求：

- 以 op 为分图基本单位，以 value 为依赖边载体
- 复用 `Graph` 现有 op/value 编号
- 统计信息采用按 `OperationId` / `ValueId` 编址的数组存储
- 核心步骤围绕顺序扫描、局部更新、一次建索引展开

## 4. phase B event-domain 反标

### 4.1 phase B1：建立反标起点

收集带事件语义的 sink 节点，并提取其 `event-domain` 信息。

sink 节点判定规则：

- 位于组合 use-def 路径的末端
- 代表状态更新、语句侧副作用或可观察输出边界

第一版 sink 节点包括：

- `kRegisterWritePort`
- `kMemoryWritePort`
- `kLatchWritePort`
- 无返回值的 `kSystemTask`
- 无返回值的 `kDpicCall`
- result 直接连接到 output/inout 输出分量的 op

对每个 sink 节点，需要显式识别：

- 哪些输入是 event value
- 每个 event value 对应的 event edge

在此基础上形成正规的 `event-domain` 签名：

- 基本元素是 `(event value, event edge)`
- 按确定顺序排序
- 生成稳定签名，供后续聚类和去重

`event-domain` 可以为空。空 `event-domain` 表示该 sink 不受事件命中约束，在每次 `eval()` 中都可进入调度，用于覆盖纯组合路径。

`phase B1` 输出：

- sink op 集合
- sink op -> `event-domain-signature`
- `event-domain-signature -> sink op` 集合

### 4.2 phase B2：反向标注 `event-domain-set`

从每个 sink 节点出发，沿 use-def 反向传播，把对应的 `event-domain-signature` 标到经过的 op、value 和 `supernode` 上。

反标范围：

- sink op 的组合输入锥
- 输入锥上的中间 value
- 输入锥覆盖到的 `activity supernode`

反标停止条件：

- 到达输入端口
- 到达状态读口
- 到达另一个 `event-domain` sink 的边界
- 到达不参与当前传播的特殊语义节点

`phase B2` 输出：

- `op -> event-domain-set`
- `value -> event-domain-set`
- `supernode -> event-domain-set`
