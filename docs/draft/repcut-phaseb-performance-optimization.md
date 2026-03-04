# RepCut Phase-B 性能优化计划（collect_mem_symbols）

## 1. 背景

在大图（如 XiangShan 规模）上，`repcut phase-b/ascs: collect_mem_symbols` 成为主要耗时阶段。
当前日志显示每 20k sinks 的批次耗时波动大，说明该阶段负载不均，且存在重复计算。

## 2. 现象与初步判断

- 现象不是“持续变慢”，而是批次之间耗时抖动明显。
- 每个 sink 独立 DFS，`visited` 仅在单 sink 内生效，导致共享子锥被重复遍历。
- 命中热点 memory symbol 时，DSU 合并次数增多，批次耗时会突增。

## 3. 优化目标

1. 显著降低 `collect_mem_symbols` 总耗时。
2. 降低批次 P95 耗时与抖动。
3. 在不改变 ASC 语义规则前提下优化实现。

## 4. 分阶段实施方案

### Step A：观测增强（先做，低风险）

按批次新增统计日志：

- `visited_nodes`
- `mem_symbol_hits`
- `unique_mem_symbols`
- `dsu_unions`
- `batch_elapsed_ms`

目的：先区分瓶颈是“遍历”还是“合并”。

### Step B：visited 结构优化（低风险，高性价比）

将每 sink 的 `unordered_set<NodeId> visited` 改为“版本戳数组”：

- `vector<uint32_t> visitStamp(nodeCount, 0)`
- `uint32_t epoch` 每个 sink 递增
- 访问判断：`visitStamp[node] == epoch`
- 标记访问：`visitStamp[node] = epoch`

收益：减少哈希分配与 rehash 常数开销。

### Step C：可达 memSymbol 缓存（核心收益）

做 memoization，缓存“某节点向上可达 memSymbol 集合”：

- Key：`NodeId` 或 `OperationId`
- Value：`vector<MemSymbolId>`（建议符号先 intern 为整数）
- 组合规则：当前节点结果 = 子节点并集 + 本节点命中

收益：消除共享子锥重复 DFS。

### Step D：DSU union 路径优化（中风险）

- 单 sink 内先对 mem symbol 去重，再批量 union。
- 对热点 symbol（对应 write sinks 很多）做统计并优化合并策略。

### Step E：并行化（最后考虑）

- 可并行：sink 到 memSymbols 的收集（线程本地结果）。
- 建议串行：最终 DSU 合并（或分段合并后归并）。

## 5. 数据结构建议

为降低字符串成本：

- `unordered_map<string, uint32_t> memSymbolToId`
- `vector<string> idToMemSymbol`

内部集合和缓存都优先使用整数 ID。

## 6. 验收标准

满足以下至少两项：

1. `collect_mem_symbols` 总耗时下降 ≥ 30%。
2. 批次 P95 耗时下降 ≥ 30%。
3. 峰值内存增长不超过基线 +20%。
4. `asc_count` 与 `sinkToAsc` 结果与优化前一致。

## 7. 回归与风险控制

- 功能回归：`transform-repcut`、`transform-pass-manager` 通过。
- 语义回归：对比优化前后 Phase-B 输出一致性。
- 降级策略：提供开关可退回“无缓存”路径。

## 8. 推荐执行顺序

1. Step A + Step B
2. Step C
3. 视 profiling 结果决定 Step D / Step E

## 9. 当前实施结果（2026-03-04）

- Step A：已完成（批次统计字段已落日志：`visited_nodes` / `mem_symbol_hits` / `unique_mem_symbols` / `dsu_unions` / `batch_elapsed_ms`）。
- Step B：已完成（`visited` 从每 sink `unordered_set<NodeId>` 切换为版本戳数组）。
- Step C：已完成（节点级可达 `memSymbol` 缓存 + `memSymbol` 整数化 intern）。

关键结果：

- `repcut phase-b/ascs: collect_mem_symbols_done elapsed_ms=4274`

前后对比描述：

- 优化前（Step C 前基线）：`collect_mem_symbols_done elapsed_ms=276829`。
- 优化后（Step C 完成后）：`collect_mem_symbols_done elapsed_ms=4274`。
- 绝对下降：`272555 ms`；相对下降约 `98.46%`（约 `64.8x` 加速）。

备注：

- 本轮 Step C 按当前决策直接上线实现，未添加防御性回退开关。
