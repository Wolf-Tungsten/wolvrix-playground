# RepCut Phase-B 性能分析（collect_cones_progress）

## 1. 背景与结论

在当前 XiangShan 规模样例中，`phase-b/ascs` 的主要瓶颈已经从 `collect_mem_symbols` 转移到 `collect_cones`。

- 日志证据（`build/logs/xs-repcut/xs_repcut_20260304_190245.log`）：
  - `collect_mem_symbols_done elapsed_ms=4274`
  - `collect_cones_done elapsed_ms=548425`
  - `build_ascs_ms=553613`
- 结论：`collect_cones` 占 `buildAscs` 约 **99.1%** 时间，是当前 Phase-B 的绝对瓶颈。

## 2. 慢的直接原因（基于日志 + 代码）

### 2.1 进度抖动非常大，说明负载极不均匀

- `collect_cones_progress=1000/328558 elapsed_ms=153056`：前 1000 个 ASC 就耗时 153s。
- 全量到 `328000/328558` 时 `elapsed_ms=548188`。
- 统计上，按每 1000 ASC 的时间块：
  - P50 约 `416ms`
  - P95 约 `4624ms`
  - 最大块 `153056ms`
- 这表明“按 ASC 数量均匀切片”并不代表“按工作量均匀切片”。

### 2.2 ASC 内重复遍历严重（按 sink 重复 DFS）

代码位置：`wolvrix/lib/transform/repcut.cpp:694-751` 与 `wolvrix/lib/transform/repcut.cpp:962-968`。

- 当前实现是“**每个 sink 调一次 `collectCone`**”。
- `collectCone` 内部 `visited` 是函数局部 `unordered_set<NodeId>`（`wolvrix/lib/transform/repcut.cpp:700`），只在单 sink 生效。
- 同一 ASC 里的多个 sink（尤其 mem 合并后的大 ASC）共享大量逻辑锥，导致反复从头走同一子图。
- 日志也显示大 ASC 客观存在：`max_asc_sinks=17939`、`max_asc_comb_ops=237318`。

### 2.3 哈希容器路径过重

代码位置：`wolvrix/lib/transform/repcut.cpp:700-732`。

- 热路径里频繁做哈希插入：
  - `visited.insert(node)`
  - `asc.combOps.insert(node)`
  - `asc.values.insert(value)`
- `total_asc_comb_ops=321477234` 说明插入量非常大，`unordered_set` 的哈希/rehash 常数开销会被放大。

### 2.4 `asc.values` 目前只写不读，产生额外纯开销

代码位置：
- 写入：`wolvrix/lib/transform/repcut.cpp:705,732`
- `repcut.cpp` 内未找到读取 `asc.values` 的路径。

这意味着当前 `collect_cones` 里一部分哈希插入是“无消费开销”。

### 2.5 递归 + `std::function` 增加热路径常数成本

代码位置：`wolvrix/lib/transform/repcut.cpp:702-737`。

- 每次 `collectCone` 都构造递归 lambda（`std::function`）。
- 在亿级访问量下，这类调用开销会累积成可见时间。

## 3. 优化方案（按风险/收益排序）

## 3.1 P0：先补齐观测（低风险，必须先做）

给 `collect_cones_progress` 增加每批统计，至少包含：

- `batch_sink_count`
- `batch_unique_comb_ops`
- `batch_visited_nodes`
- `batch_revisit_hits`
- `batch_elapsed_ms`
- Top-K 慢 ASC（`asc_id` + `sink_count` + `comb_ops_count`）

目标：先确认慢块到底由“超大 ASC”还是“容器/实现常数”主导。

## 3.2 P1：低风险快改（预计立刻见效）

1) 去掉 `asc.values` 热路径写入（或挂 debug 开关）

- 删除 `collectCone` 中 `asc.values.insert(...)`。
- 预期：直接减少一条哈希写路径和内存膨胀。

2) 用显式栈替换递归 `std::function`

- 把 `traverse` 改为 `std::vector<ValueId> stack` 的迭代版。
- 预期：降低函数包装和递归开销，提升 cache locality。

3) 给重容器增加 `reserve` 保护

- 基于 `asc.sinks.size()` 做启发式 `reserve`，减少 rehash 次数。

## 3.3 P2：核心算法改造（主要收益来源）

### 从“每 sink 一次 DFS”改为“每 ASC 一次多源 DFS”

核心思想：

- 对同一 ASC，先收集所有 sink 的起始 value，做一次统一遍历。
- `visited` 从“每 sink 私有”提升为“每 ASC 共享”。
- 用版本戳数组代替 `unordered_set`：
  - `std::vector<uint32_t> visitStamp(nodeCount, 0)`
  - `epoch` 每个 ASC 自增

伪代码：

```cpp
for (AscId aid = 0; aid < ascs.size(); ++aid) {
    ++epoch;
    stack.clear();
    for (sink in ascs[aid].sinks) {
        push sink roots to stack;
    }
    while (!stack.empty()) {
        ValueId v = pop(stack);
        if (isSourceValue(v)) continue;
        NodeId n = valueDefToNode(v);
        if (visitStamp[n] == epoch) continue;
        visitStamp[n] = epoch;
        if (!isCombOp(n)) continue;
        ascs[aid].combOps.insert(n);
        push operands(n) to stack;
    }
}
```

预期收益：

- 对大 ASC（`max_asc_sinks=17939`）可显著消除跨 sink 重复遍历。
- 这是当前最可能把 `collect_cones` 从 548s 拉回到分钟以内的方案。

## 3.4 P3：进一步优化（中风险）

1) `asc.combOps` 改为 `vector<NodeId>` + stamp 去重

- 遍历时“首次命中就 push_back”。
- 后续消费多数是遍历，不依赖哈希查找；vector 更轻。

2) 融合 `collect_cones` 与 `build_node_to_ascs`

- 当前先构建 `asc.combOps`，再在 `buildPieces` 中二次遍历填 `nodeToAscs`。
- 可在 collect 阶段直接写入 `nodeToAscs`（配套去重 stamp），减少一次全量扫描。

3) 并行化按 ASC 分片

- 大图可将 ASC 范围切给线程池。
- 每线程维护本地栈和本地 epoch/stamp 视图，避免锁争用。

## 4. 建议落地顺序

1. P0（观测补齐）
2. P1（去 `asc.values` + 迭代 DFS + reserve）
3. P2（ASC 级多源 DFS + stamp）
4. 视 profiling 决定是否做 P3（vector 化 / 融合 / 并行）

## 5. 验收指标

功能一致性：

- `ascs` 数量、`sinkToAsc` 映射保持一致。
- `phase-c` 生成的超图节点/边规模一致或在可解释范围内（仅顺序变化可接受）。

性能指标（建议门槛）：

- `collect_cones_done elapsed_ms` 下降 **>= 60%**（548s -> <= 220s）
- `build_ascs_ms` 下降 **>= 50%**
- 峰值内存不超过基线 +20%

## 6. 优化实施记录（2026-03-04）

### 6.1 分阶段结果对比（XiangShan 同规模日志）

| 阶段 | 日志 | collect_mem_symbols | collect_cones | build_ascs_ms | build_pieces_ms | phase-b elapsed |
|:--|:--|--:|--:|--:|--:|--:|
| 基线 | `build/logs/xs-repcut/xs_repcut_20260304_190245.log` | 4274 ms | 548425 ms | 553613 ms | 19999 ms | 573789 ms |
| P1+P2 | `build/logs/xs-repcut/xs_repcut_20260304_192737.log` | 4674 ms | 250306 ms | 255957 ms | 10247 ms | 266349 ms |
| P2 增强（容器/邻接优化） | `build/logs/xs-repcut/xs_repcut_20260304_200326.log` | 4403 ms | 99173 ms | 104552 ms | 9789 ms | 114538 ms |

关键收益（相对基线）：

- `collect_cones`: `548425 -> 99173 ms`，约 **5.53x** 加速（-81.91%）。
- `build_ascs_ms`: `553613 -> 104552 ms`，约 **5.30x** 加速（-81.12%）。
- `phase-b`: `573789 -> 114538 ms`，约 **5.01x** 加速（-80.04%）。

### 6.2 `collect_cones_progress` 抖动改善

按每 1000 ASC 分块统计：

- 基线（190245）：P50 `416ms`，P95 `4624ms`，max `153056ms`
- P1+P2（192737）：P50 `236ms`，P95 `2989ms`，max `8225ms`
- P2 增强（200326）：P50 `85ms`，P95 `1466ms`，max `2038ms`

说明热点长尾已显著收敛，但仍有局部慢块（如 114k、200k、227k~229k 一带）。

### 6.3 已落地代码项

1) P1：

- 移除 `asc.values` 热路径写入（该字段在 `repcut.cpp` 内无消费）。
- 递归 + `std::function` 改为显式栈迭代。

2) P2：

- 从“每 sink 一次 DFS”改为“每 ASC 一次多源遍历”。
- 引入版本戳（stamp + epoch）做 O(1) 去重。

3) P2 增强：

- `asc.combOps` 从 `unordered_set<NodeId>` 改为 `vector<NodeId>`（唯一性由 stamp 保证）。
- 锥扩展从 operand/value 路径改为直接走 `phaseA.inNeighbors`，减少热路径反查开销。

4) P3（并行）已实现，待性能验证：

- `collect_cones` 支持多线程动态分块（chunk=64，默认最多 8 线程）。
- 每线程私有 `visitStamp + epoch + stack`，避免共享写冲突。
- 已通过功能编译与测试（见 6.4），下一轮用 xs 日志量化收益。

### 6.4 回归测试

- 2026-03-04 本地构建通过：`cmake --build wolvrix/build -j$(nproc)`
- 2026-03-04 CTest 全通过：`31/31`（`ctest --test-dir wolvrix/build --output-on-failure`）

## 7. 后续建议

- 先跑一轮带并行的 xs-repcut 日志，确认 `collect_cones_done` 与 `build_ascs_ms` 的增益上限。
- 若并行收益低于预期，优先补充慢块 ASC 画像（`sink_count`/`comb_ops_count` Top-K）再做针对性调度。
