# NO0070 GrhSIM Activity-Schedule ComputeNode 重构计划

## 背景

当前 `activity-schedule` 流程已经叠加了多轮局部修补：

- sink supernode special partition
- source leaf absorb / clone
- macro node / common-expr seed
- coarsen fixed-point
- DP excluding sink
- compute / commit 两阶段 emit

这些概念在实现中互相穿插，导致两个问题：

1. 语义边界不清。`source op`、`sink op`、`macro node`、`supernode` 有时是 graph rewrite 单位，有时是 partition 单位，有时又是 emit 调度单位。
2. 大规模性能脆弱。近期 `macro/common-expr` 建立曾在 XiangShan 规模上退化到接近 `roots * ops`，表现为 `special_partition` 后长时间无输出。

后续不应继续在现有流程上打补丁，而应按 GSIM 的 `Node + ExprNode` 粒度重新定义中间层：先建立 `computeNode`，再以 `computeNode` 为基本单位做 topo / coarsen / DP，最后才得到 emitter 使用的 `computeSupernode`。

## 核心概念

### source op

`source op` 是可被复制到 computeNode 局部的叶子 op：

- `kConstant`
- `kRegisterReadPort`
- `kLatchReadPort`

性质：

- source op 不应因为自身 result 被多个 consumer 使用而形成跨 supernode boundary value。
- source op 只能被复制到 `computeNode` 内部，不能复制到 `commitSupernode`。
- `commitSupernode` 需要 source op result 时，必须保留对原始 source value 的输入依赖；不能把 source op clone 成 commit 内部 op，否则会破坏 compute/commit 两阶段调度语义。
- 原始 source op 只有在 result 直接 observable 或仍有必要保留 owner 时才保留；否则可以在 rewrite 后删除。
- graph input / inout input 这类外部输入 value 不是 source op，因为它们没有 defining op；它们作为反向建树的自然叶子停止。

`kMemoryReadPort` 不是 source op。它虽然读取状态，但它有地址 operand，地址本身可能来自 compute graph；因此必须按 compute op 建 `computeNode` 和 DAG 依赖，不能作为 source clone 放进 computeNode，否则会把地址依赖藏在 source 内部，破坏调度和 emitter 的局部值作用域。

### sink op

`sink op` 是 commit 阶段有状态副作用的写端：

- `kRegisterWritePort`
- `kLatchWritePort`
- `kMemoryWritePort`

现有 `kMemoryFillPort` 虽然不符合 `k*WritePort` 命名，但语义上是 memory commit side effect。实现中若仍保留该 op，应按 sink-like commit op 处理。

性质：

- sink op 只进入 `commitSupernode`。
- sink op 不进入 compute coarsen / DP。
- sink op 的直接 source 输入不得复制进 `commitSupernode`。
- `commitSupernode` 必须在最终调度模型中保留其输入 value 依赖，包括 computeSupernode -> commitSupernode 以及 source value -> commitSupernode 的依赖；但 commitSupernode 不作为 value producer 产生出边。

### compute op

`compute op` 是除 source / sink / 声明类 op 之外，参与 compute 阶段执行的 op。`kMemoryReadPort` 属于 compute op，因为它带地址数据依赖。

`kSystemTask` / `kDpicCall` 这类 op 不进入 sink，但也不需要额外 hard-boundary 保护。它们按普通 compute op 处理即可，因为本流程只复制 source op，不复制 compute op；普通 compute op 不会被复制到多个 consumer，也不会跨越 sink/commit 语义边界。

### computeNode

`computeNode` 是新的 activity-schedule 中间粒度，对标 GSIM 的 `Node + ExprNode`：

- 是 op 的集合。
- 可以包含普通 compute op。
- 可以包含复制进来的 source op。
- 可以包含原始 `kMemoryReadPort`，但不能包含复制出来的 `kMemoryReadPort` source clone。
- common expr 应形成独立 `computeNode`。
- `computeNode` 是 topo / coarsen / DP 的基本单位。
- `maxComputeNodeInComputeSupernode` 统计的是 `computeNode` 数量，不是 raw op 数量。
- `maxOpInComputeNode` 控制单个 `computeNode` 内最多包含多少 raw op，默认值取 `8192`。该参数只限制反向建树阶段形成的局部表达式树大小，不替代 `maxComputeNodeInComputeSupernode`。

注意：`computeNode` 不是最终 emitter supernode。最终 emit 使用的是 DP 后形成的 `computeSupernode`。

### commitSupernode 与 computeSupernode

`commitSupernode`：

- 由 sink op 聚类得到。
- 只在 commit 阶段执行。
- 受独立参数 `maxOpInCommitSupernode` 控制大小，单位是 commitSupernode 内的 sink op 数量。
- 按 event guard 聚类。

`computeSupernode`：

- 由 `computeNode` 经 topo / coarsen / DP 得到。
- 在 compute fixed-point 阶段执行。
- 受 `maxComputeNodeInComputeSupernode` 控制，单位是 `computeNode` 个数。

## 新流程

### 1. 分类

先在 `ActivityOpData` 或等价结构中明确标注每个 op：

- source op
- sink op
- compute op
- declaration / non-partition op

所有后续阶段只使用这个分类，不再通过多个 helper 重复推断。

### 2. 建立 commitSupernode

先扫描所有 sink op，建立 commit side partition：

1. 收集所有 sink op。
2. 对每个 sink op 检查直接 operand。
3. 如果 operand 的 def 是 source op，记录该 source value 是 commit cluster 的输入依赖；不得复制 source op，也不得改接 operand 到 commit 内部 clone。
4. commit partition 的成员只包含 sink op。
5. 按 event key 聚类。
6. 按 `maxOpInCommitSupernode` 切 chunk。

不变量：

- commitSupernode 内只允许 sink op。
- commitSupernode 不允许本地 source clone。
- commitSupernode 不包含普通 compute op。
- commitSupernode 不进入后续 compute DP。
- commitSupernode 的输入 value 关系必须保留到最终调度模型；commitSupernode 自身不作为 value producer 产生出边。

### 3. 收集 computeNode roots

完成 commitSupernode 后，以这些 value 作为 compute root：

- commitSupernode 中 sink op 的直接输入。
- graph output port value。
- graph inout port 的 `out` / `oe` 分量。

若 root value 由 source op 定义，computeNode builder 不为它建立 node；该 source value 作为最终调度模型中的输入依赖保留到对应 consumer，尤其是 direct source -> commitSupernode 依赖。

### 4. 反向建立 computeNode

从每个 root 反向建树，目标是形成 GSIM ExprNode 风格的局部表达式树。

建树受独立参数 `maxOpInComputeNode` 控制，默认值为 `8192`：

- 单位是 raw op 数量，包括当前 `computeNode` 内吸收的普通 compute op 和复制进来的 source op。
- 达到上限后，不再继续把 predecessor 吸收到当前 `computeNode`；该 predecessor 应形成边界依赖，必要时独立建 `computeNode`。
- 该参数用于防止异常大的局部表达式树拖垮 builder / emitter，不参与后续 coarsen / DP 的 computeSupernode 大小计数。

基本规则：

1. root 的 defining compute op 成为当前 `computeNode` 的 root op。
2. 反向查看 operand 的 defining op。
3. 遇到外部 input value，停止。
4. 遇到 source op，复制 source op 到当前 `computeNode`，停止继续穿越。
5. 遇到 `kMemoryReadPort`，按普通 compute op 处理，并继续反向处理其地址 operand。
6. 遇到 sink op，直接诊断报错；compute root 不应穿越 sink，出现这种边说明前置 commitSupernode / root 收集或 IR 语义已经错误。
7. 遇到普通 compute op：
   - 如果该 value 只有当前 `computeNode` 内的唯一 consumer，可吸收到当前 `computeNode`。
   - 如果该 value 有多个 consumer，即 common expr，先独立成一个 `computeNode`，当前 node 通过该 value 依赖它。

这里的 “唯一 consumer” 应按 compute/commit 语义判断，而不是简单用 raw `Value::users()` 个数：

- commitSupernode 的 direct source user 不应促使 source 被复制到 commit 内部，也不应算作 common expr boundary。
- source op result 不应成为 common expr boundary。
- 同一个 `computeNode` 内的多个 operand 使用不应导致该 predecessor 被误判为 shared boundary。

### 5. 建立 computeNode DAG

`computeNode` 建完后，先构造只服务 compute coarsen / DP 的 node-level DAG：

- node A 的 result 被 node B 使用，形成 A -> B。
- source clone 不形成 DAG 边。
- commitSupernode 不在 compute DAG 内。
- commitSupernode 的 input root 只作为 compute DAG 的 observable sink 边界，不作为 compute DAG node；direct source input 仅作为最终调度依赖，不进入 compute DAG。
- compute DAG 不是最终完整调度依赖图；它只用于 computeNode topo / coarsen / DP。

需要导出调试统计：

- `compute_nodes`
- `compute_node_ops_total`
- `source_clones_in_compute_nodes`
- `direct_source_inputs_to_commit_supernodes`
- `common_expr_compute_nodes`
- `compute_node_boundary_values`
- `commit_input_root_values`

### 6. topo / coarsen

拓扑排序以 `computeNode` DAG 为输入。

coarsen 也以 `computeNode` 为单位：

- merge 后的 cost 是 `computeNode` 数量之和。
- 不再用 raw op 数量限制 compute coarsen。
- merge 后必须保持 DAG 无环。

这个阶段产物仍不是 emitter supernode，而是 coarsened computeNode cluster。

### 7. DP

DP 输入是 topo-ordered coarsened computeNode cluster。

规则：

- `maxComputeNodeInComputeSupernode` 表示最多包含多少个 `computeNode`。
- sink / commitSupernode 不进入 DP。
- DP 输出 `computeSupernode`。
- `computeSupernode` 的成员是若干 `computeNode` 展开后的 op 集合。

### 8. 最终调度模型

最终 activity schedule 输出两类 supernode：

- `computeSupernode`
- `commitSupernode`

它们应在数据结构上显式区分，避免再用 `sinkOnly` 这类派生标志反复判断。

最终需要生成：

- `supernode_to_ops`
- `op_to_supernode`
- `value_fanout`
- `state_read_supernodes`
- `topo_order`
- `supernode_kind`

最终模型必须正确保留所有跨 supernode value 关系：

- computeSupernode -> computeSupernode
- computeSupernode -> commitSupernode
- source value -> commitSupernode

`value_fanout` 可以包含 computeSupernode 到 commitSupernode 的 consumer 边，用于表达 commitSupernode 对 compute value 的依赖。若 sink 直接消费 source value，最终模型必须以等价方式保留 source value 到 commitSupernode 的依赖，但不能通过复制 source op 到 commitSupernode 来实现。commitSupernode 不作为普通 value producer 产生出边；commit 后激活 reader 仍通过 state-read mapping 处理。

### 9. emit 保持当前两阶段语义

emitter 主流程保持 compute/commit 两阶段不动点：

1. compute 阶段：
   - 按调度顺序执行当前 active 集合中的 computeSupernode。
   - computeSupernode 内 value old/new 判断可以激活后继 computeSupernode。
   - 这些后继活性在同一次 compute 阶段调度扫描中被消费；compute 阶段结束时 active 集合自然清空。
2. commit 阶段：
   - 执行 compute 阶段通过 value 变化激活的 commitSupernode。
   - commitSupernode 使用 compute 阶段已经更新好的输入 value，按 event guard 执行 write shadow / state update。
   - state 改变后通过 state-read mapping 激活对应 reader computeSupernode。
3. eval 不动点判定：
   - 如果 commit 阶段没有激活新的 computeSupernode，则整个 eval 达到不动点并退出。
   - 如果 commit 阶段激活了新的 computeSupernode，则进入下一轮 compute 阶段。

本计划不要求改写 emitter 两阶段框架，只要求 schedule model 更干净。

## 关键不变量

1. source op 只允许复制到 computeNode；commitSupernode 不允许复制 source op。
2. sink op 只存在于 commitSupernode。
3. commitSupernode 不进入 compute DAG / coarsen / DP。
4. computeNode 是 coarsen / DP 的计数单位。
5. common expr 独立成 computeNode，而不是被多个 consumer 重复吸收。
6. 最终 `value_fanout` 必须保留 computeSupernode -> computeSupernode、computeSupernode -> commitSupernode，以及 direct source -> commitSupernode 依赖；不包含 commitSupernode 作为 value producer 的出边。
7. mixed sink/output root 不允许形成 quotient cycle。
8. computeNode 反向建树时不允许遇到 sink op；遇到即报错，不做静默截断。
9. `kMemoryReadPort` 按普通 compute op 处理，不允许 source clone。
10. `kSystemTask` / `kDpicCall` 按普通 compute op 处理；它们不需要额外 hard-boundary，因为 compute op 本身没有复制语义。

## 实施计划

### 全局复杂度约束

XiangShan 输入图规模很大，实现优先级是正确性和低复杂度，而不是在 builder 阶段做复杂全局优化。

实现约束：

- 目标复杂度应为线性或近线性，核心路径按 `ops + values + uses` 规模增长。
- 禁止 per-root 全图扫描，例如 `roots * ops` 或每个 root 分配/清空一份全图 `seen`。
- 避免为每个 op 保存“大量所属 root 集合”这类高扇出中间结构。
- 避免在 builder/coarsen/DP 之间反复大规模 materialize graph；必要 rebuild 必须有明确边界和 timing 日志。
- common expr 识别采用局部 fanout / owner 规则即可，先不引入复杂全局表达式等价分析。
- 所有大图阶段都应输出 timing 和关键规模统计，便于及时定位卡点。

### Phase A：数据结构重命名和显式分类

- 新增 `ActivityOpClass`：`Source` / `Sink` / `Compute` / `Declaration` / `Unsupported`。
- 新增 `SupernodeKind`：`Compute` / `Commit`。
- 先保留现有输出字段，但内部避免用 `sinkOnly` 推导阶段语义。

### Phase B：commitSupernode 前置

- 重写 sink partition，使其只处理 sink op。
- 记录 sink direct source input 依赖；禁止在 commitSupernode 内 clone source op。
- 保留 event clustering，并用 `maxOpInCommitSupernode` 控制 commit chunk 大小。
- 明确 commitSupernode 保留输入 value 依赖，但不作为 value producer 产生出边。

### Phase C：computeNode builder

- 删除当前 macro/common-expr seed 的混合实现。
- 从 commit input roots / outputs / inout outs 统一建 computeNode。
- 实现 source clone、unique predecessor absorb、common expr independent node。
- 反向建树遇到 sink op 时生成诊断错误，不继续 materialize schedule。
- 增加 `maxOpInComputeNode` 参数，默认 `8192`，作为单个 computeNode 的 raw op 上限。
- 增加小图单测覆盖：
  - source 直接喂 sink，验证 source 不被复制进 commitSupernode 且依赖保留。
  - source 直接喂 compute。
  - memory read 喂多个 compute root，验证 `kMemoryReadPort` 不被 source clone，地址依赖保留。
  - shared common expr 同时喂两个 compute root。
  - shared expr 只在同一 computeNode 内被多次使用。
  - mixed sink/output root。

### Phase D：node-level topo / coarsen / DP

- 将 `WorkingPartition::costs` 固定为 computeNode count。
- coarsen 输入改为 computeNode DAG。
- DP 输入改为 computeNode cluster。
- 删除 raw op count 作为 compute supernode size 的残余路径。

### Phase E：最终 materialize 与 emitter 对接

- 展开 computeSupernode / commitSupernode 到 `supernode_to_ops`。
- 保留现有 emitter two-phase eval。
- 校准 `state_read_supernodes` 和 `value_fanout`：
  - source result 只应在 direct source -> commitSupernode 等必要调度依赖中出现。
  - computeSupernode -> commitSupernode 的 value 边必须保留。
  - commitSupernode 不应出现在 value fanout producer。

## 验收指标

对 `testcase/xs-components`：

- `GRHSIM_SUPERNODE_MAX_SIZE=8` 时，size 确认按 computeNode 计数。
- computeSupernode 之间的 source boundary values 归零或接近归零，尤其 `kConstant` / `k*ReadPort` 不应再作为 compute schedule boundary value 主体；direct source -> commitSupernode 依赖允许保留。
- GrhSIM boundary values 接近 GSIM 同口径 boundary。
- GrhSIM 指令数不应因为 source/common expr 边界显著膨胀。

对 XiangShan：

- `activity-schedule` 在 `special_partition` 后必须稳定输出后续 timing，不允许出现 roots 扫描导致的长时间无日志。
- 输出 `compute_nodes` / `common_expr_compute_nodes` / `source_clones_in_compute_nodes` / `direct_source_inputs_to_commit_supernodes` 等统计，用于判断结构是否符合预期。
- `run_xs_wolf_grhsim_emu` 功能对齐不回退。

## 当前实现与目标流程的差距

当前实现已经包含部分目标形态，但仍不干净：

- 有 commit/sink special partition，但它和 macro seed、state-read-tail-absorb 仍交织。
- compute 侧 source clone 目前通过旧的 tail absorb 路径完成，命名和职责不匹配。
- macro node 已尝试对齐 GSIM ExprNode，但构建过程仍依赖 root/commonExpr 的局部规则，容易形成复杂边界。
- coarsen / DP 已有 `costs` 字段，但整体模型还没有把 `computeNode` 作为一等概念。

后续修改应以本文概念重写主路径，而不是继续扩展旧 helper。
