# hrbcut Pass Plan

## 核心思路
- 延续 repcut 的复制分割模式，但流程更轻量。
- 作用于已完成 hier-flatten、comb-loop-elim、strip-debug 处理的图。
- hrbcut 由用户指定待处理的 Graph symbol。
- 以 sink 节点（如 kRegisterWritePort、Output Value）为划分入口，先分组，再切分对应的输入逻辑锥。
- 当不同分区的逻辑锥共享组合逻辑时，在分区内复制该组合逻辑，保证等价性。
- 不采用 repcut 的超图划分方法，避免在 XiangShan 等大规模设计上产生高额开销。

## 用户可配置参数
- `target_graph_symbol`：待处理的 Graph symbol。
- `partition_count`：目标分区数，必须为 2 的指数。
- `balance_threshold`：平衡度阈值，用于模块 5 的解筛选（基于 `|balance - 0.5|`）。
- `target_candidate_count`：目标候选解数（模块 5）。
- `max_trials`：最大尝试次数（模块 5）。
- `split_stop_threshold`：递归二分的终止阈值（模块 4）。

## Sink 节点定义（GRH IR 口径）
- Output Value：Graph 的输出端口 Value（`isOutput = true`，包含 inout 的 out 分量）。
- kRegisterWritePort：寄存器写端口。
- kLatchWritePort：锁存器写端口。
- kMemoryWritePort：存储器写端口。
- strip-debug 后不应再出现 kSystemTask / kDpicCall；若仍存在则报告诊断错误。

## Source 节点定义（GRH IR 口径）
- Input Value：Graph 的输入端口 Value（`isInput = true`，包含 inout 的 in 分量）。
- kRegisterReadPort：寄存器读端口。
- kLatchReadPort：锁存器读端口。
- 常量 Operation（如 `kConstant`）。

## 组合节点定义
- 语义：不引入状态更新、无事件触发、无副作用；输出由当前输入以及（若引用）存储状态的当前值决定。
- 覆盖范围：6.2 类组合运算（算术/逻辑/比较/位操作、拼接与切片、选择/多路复用、类型/位宽转换、纯组合 `kAssign` 等），以及异步读 `kMemoryReadPort`。
- 例外：`kSystemFunction` 仅在 `hasSideEffects = false`（或未标记副作用）时视为组合节点。
- 排除项：kRegister/kLatch/kMemory 声明、kRegisterReadPort/kLatchReadPort、所有写端口及任何带 events 的操作；`kSystemTask` / `kDpicCall` 不应在 strip-debug 后出现，若出现则报诊断错误。

## 组合逻辑锥定义
对任一分组的 sink 集合，取所有 sink 的输入操作数作为起点，在同一 Graph 内沿 Value 的 `definingOp` 逆向遍历，仅穿过组合逻辑相关的 Operation；当遇到 Source 节点的输出（Input Value / inout 输入、kRegisterReadPort、kLatchReadPort）即停止。注意 Source 边界不包含 kMemoryReadPort（memory 读口不作为截断点），因为 memory 读必须与写口同分区，否则会隐式跨分区共享状态。该逆向可达的 Operation 与 Value 集合构成该分组的组合逻辑锥。

## atomicSinkCluster（ASC）
ASC 是不可分割的 sink 集合；分组时以 ASC 为原子单位，禁止拆分与复制。其目标是保证同一状态元素的读写口在同一分区内。

### ASC 生成规则
- 写口合并规则：共享同一 `regSymbol` / `latchSymbol` / `memSymbol` 的 k*WritePort 必须属于同一个 ASC。
- mem 不可分规则：若某个 sink 的组合逻辑锥中包含指向某个 kMemory 的 kMemoryReadPort，则该 sink 与该 memory 的所有 kMemoryWritePort 必须归并到同一个 ASC。
提示：kRegisterReadPort / kLatchReadPort 仅作为 Source 边界，不触发 ASC 合并；其输出可跨分区被其他 sink 使用。

## 分割打包规则（原子分组）
- kRegister 必须与其全部 kRegisterReadPort / kRegisterWritePort 同分区（通过 `regSymbol` 关联）。
- kLatch 必须与其全部 kLatchReadPort / kLatchWritePort 同分区（通过 `latchSymbol` 关联）。
- kMemory 必须与其全部 kMemoryReadPort / kMemoryWritePort 同分区（通过 `memSymbol` 关联）。
- k*ReadPort 不允许复制，必须与对应的状态部件同分区。
- kRegisterReadPort / kLatchReadPort 的结果允许跨分区使用，需要显式添加跨分区连接的模块端口。
- kMemoryReadPort 的结果不允许跨分区；若需跨分区必须先经寄存器/锁存器（或输出端口）显式边界化。
- 现有规则等价于对 memory 构造“寄存器/锁存器/output 闭包”，避免隐式跨分区状态流动。

## 算法模块
### 模块 1：组合逻辑权重函数
给定一个组合逻辑 Operation，返回其权重，权重用于逻辑锥负载估计。权重设计以**仿真时间开销评估**为导向。要求：
- 提供 pass 内置的权重表（按 OperationKind 分类）。
- 可结合 attrs 修正权重（如切片宽度、拼接项数、位宽等）。
- 非组合节点不参与该模块。

### 模块 2：平衡度计算
给定一个 Graph 与两个 ASC 集合 A、B，计算 A 与 B 各自逻辑锥的负载总和，并返回**平衡度浮点值**。要求：
- 对每个 ASC 先构建/复用其逻辑锥。
- 逻辑锥大小通过“组合逻辑权重函数”累加得到。
- 平衡度定义：设 `wA`、`wB` 为 A/B 的总权重，返回
  ```
  balance = wB / (wA + wB + kBalanceEpsilon)
  ```
  其中 `kBalanceEpsilon` 为固定的小正数，用于避免除零。结果范围为 [0, 1]；`0.5` 表示平衡，越接近 0 表示 A 更大，越接近 1 表示 B 更大。

### 模块 3：重叠度计算
给定两个 ASC 集合 A、B，计算其逻辑锥重叠部分的组合逻辑权重和。要求：
- 分别得到 A、B 的逻辑锥组合节点集合，取交集。
- 重叠节点的权重仅累计一次（去重求和）。
- 权重仍使用“组合逻辑权重函数”。

### 模块 4：递归二分平衡
给定一个 ASC 集合 `S`，以递归式的二分平衡方式生成更均衡的二分结果。流程：
- 初始化：从 `S` 中取出一半作为候选集 `H`（其余记为 `R`），将 `H` 随机拆成两份 `A`、`B`（各约为 `|S|/4`）。
- 计算比例：根据当前 `A/B` 的 `balance` 设定采样比例
  ```
  pB = balance
  pA = 1 - pB
  ```
- 迭代分配：若 `|R| > split_stop_threshold`，则取 `R` 的一半作为 `C`，更新 `R = R - C`，按 `pA:pB` 将 `C` 随机拆为 `C_A`、`C_B` 并分别归入 `A`、`B`；随后重新计算 `balance` 并继续迭代。
- 终止分配：当 `|R| <= split_stop_threshold` 时，将剩余 `R` 按 `pA:pB` 随机拆分并加入 `A`、`B`，结束。

伪代码：
```text
function split_recursive_balance(S, split_stop_threshold):
    H = random_half(S)
    R = S - H
    (A, B) = random_split(H)  # 约等分
    while |R| > split_stop_threshold:
        balance = compute_balance(A, B)
        pB = balance
        pA = 1 - pB
        C = random_half(R)
        R = R - C
        (C_A, C_B) = random_split_ratio(C, pA, pB)
        A += C_A
        B += C_B
    balance = compute_balance(A, B)
    pB = balance
    pA = 1 - pB
    (R_A, R_B) = random_split_ratio(R, pA, pB)
    A += R_A
    B += R_B
    return (A, B)
```

参数说明：
- `balance`：由“平衡度计算”模块返回的浮点值，范围 [0, 1]。
- `split_stop_threshold`：停止阈值，当剩余 ASC 数量不超过该阈值时进入终止分配流程。

### 模块 5：多次采样与最优选择
给定 ASC 集合 `S`，平衡度阈值 `balance_threshold`，目标候选数 `target_candidate_count`，以及最大尝试次数 `max_trials`。重复执行模块 4 获取候选二分，并从中选择重叠度最小的结果。要求：
- 每次调用模块 4 可并行执行，提升大图处理吞吐。
- 仅保留平衡度满足阈值 `balance_threshold` 的解；若不足 `target_candidate_count` 个，则继续尝试直至达到 `max_trials`。
- 始终保留“当前最平衡”的分配（即使不满足阈值 `balance_threshold`），用于兜底。
- 达到最大次数 `max_trials` 仍不足 `target_candidate_count` 个时，用已保留的最平衡方案补足；不再额外计算 rep。

伪代码：
```text
function multi_sample_select(S, balance_threshold, target_candidate_count, max_trials, split_stop_threshold):
    accepted = []
    best = null  # 最平衡的备选
    for i in 1..max_trials:
        (A, B) = split_recursive_balance(S, split_stop_threshold)  # 可并行
        balance = compute_balance(A, B)
        if best == null or |balance - 0.5| < |best.balance - 0.5|:
            best = {A, B, balance}
        if |balance - 0.5| <= balance_threshold:
            accepted.append({A, B, balance})
        if |accepted| >= target_candidate_count:
            break
    if |accepted| < target_candidate_count:
        accepted.append(best)  # 兜底
    # 仅对 accepted 计算一次重叠度，并选择最小者
    for each sol in accepted:
        sol.overlap = compute_overlap(sol.A, sol.B)
    return argmin(accepted, by=overlap)
```



## 算法步骤
### 步骤 1
高效建立 ASC 并记录结构：
- 用并查集（DSU）在 sink 层面做合并：为每个 sink 分配节点，按“写口合并规则”与“mem 不可分规则”执行 union。
- 预建索引以降低复杂度：`memSymbol -> {kMemoryWritePort sinks}`、`regSymbol -> {kRegisterWritePort sinks}`、`latchSymbol -> {kLatchWritePort sinks}`，以及 `sink -> {kMemoryReadPort memSymbol}`（由逻辑锥遍历得到）。
- union 流程：先按同一写口符号合并；再对每个 sink 的 `memSymbol` 集合，将该 sink 与对应 `kMemoryWritePort` sinks 合并。
- 生成 ASC 记录：对 DSU 根节点建立 ASC 条目，包含 `sinkOps`（该 ASC 内所有 sink Operation）、`memberOps`、`memberValues`；同时维护 `op -> ascId` 与 `value -> ascId` 的映射，便于后续填充逻辑锥成员。
性能提示：图规模很大时，避免重复遍历；尽量用一次性索引与 O(α(n)) 的 DSU 合并，所有集合存储使用稀疏结构/bitset 视规模权衡。

### 步骤 2
基于目标分区数递归二分：
- 输入目标分区数 `partition_count`（必须为 2 的指数）。
- 以当前 ASC 集合为起点，递归调用模块 5 进行二分，直到得到 `partition_count` 个分区。
- 每次二分产出的 `A/B` 即为子分区的 ASC 集合，作为下一层递归输入。
- 递归结束后，为每个分区形成独立的 ASC 记录集合。
性能提示：递归层数固定为 `log2(partition_count)`；模块 5 的多次采样可并行，注意限制总尝试次数避免指数级开销。

### 步骤 3
构建分区 Graph 与顶层封装：
- 按步骤 2 的分区结果，将原 Graph 划分为 `partition_count` 个子 Graph（每个分区对应一组 ASC 成员）。
- 为每个分区生成子模块，并显式补齐跨分区连线所需的端口。
- 新建一个与原 Graph 接口等价的顶层封装模块，实例化各分区子模块并建立连接关系，保证与原设计行为一致。
性能提示：
- 拆图前先批量预计算跨分区 Value 列表与端口映射，避免逐边扫描/插入。
- 复制 Operation/Value 时用 ID 映射表批量重建，避免频繁查符号表或多次分配。
- 端口生成采用延迟策略：仅对跨分区实际使用的 Value 创建端口，避免“全量导出”。
- 顶层封装连线用批量连接与预分配容器，避免 O(E) 逐条插入造成的内存抖动。

### 步骤 4
分图效果统计与报告：
- 统计每个分区的逻辑锥权重（使用模块 1/2 的权重口径）。
- 计算各分区权重的最大值、平均值及偏差（使用 `max/mean` 作为偏差指标）。
- 统计分图后总 Operation 数与原始图相比的增量（衡量复制开销）。
- 输出 JSON 格式统计结果，便于后处理与回归对比。
- 可选输出分区规模分布、跨分区连线数量等指标，便于诊断大图效果。
