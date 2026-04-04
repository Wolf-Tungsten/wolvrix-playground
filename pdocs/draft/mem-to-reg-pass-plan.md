# mem-to-reg-pass 细化实施草案

## 1. 目标与范围

### 1.1 目标
在 `transform` 流程中新增 `mem-to-reg` pass，将满足条件的 `kMemory` 降级为按行拆分的 `kRegister`，以降低小容量 memory 在后续流程中的处理复杂度。

### 1.2 本草案覆盖范围
- 候选筛选：`row <= row_limit`、`mask` 常量、`init` 简单可映射。
- IR 重写：
  - `kMemory` -> `row` 个 `kRegister`
  - `kMemoryReadPort` -> `row` 个 `kRegisterReadPort` + `kMux` 选择链
  - `kMemoryWritePort` -> `row` 个 `kRegisterWritePort` + 行使能逻辑
- 时序保持：保留写口事件列表（event operands）与 `eventEdge`。
- 验证与回归计划。

## 2. IR 语义基线（实现时必须遵守）

- `kMemoryWritePort` 语义：`oper[0]=updateCond`，`oper[1]=addr`，`oper[2]=data`，`oper[3]=mask`，`oper[4..]=events`，`attrs.eventEdge` 与 `events` 一一对应。
- `kRegisterWritePort` 语义：`oper[0]=updateCond`，`oper[1]=nextValue`，`oper[2]=mask`，`oper[3..]=events`，`attrs.eventEdge` 与 `events` 一一对应。
- 允许同一寄存器存在多个写口；因此 memory 每个 row 对应寄存器可承接多个来源写口。

## 3. Pass 接口与参数

## 3.1 Pass 名称
- `mem-to-reg`

### 3.2 参数
- `-row-limit <N>`：仅转换 `row <= N` 的 memory。
  - 默认建议：`32`（可按实际设计再调）。
- `-strict-init`（布尔，可选）：
  - 开启：仅接受“完全静态且可逐行落地”的 literal init。
  - 关闭（默认）：允许缺省 init，并按语义补零。

## 4. 候选筛选规则（Eligibility）

对每个 `kMemory mem`，满足以下条件才转换：

1. **行数限制**
   - `mem.row <= row_limit`。

2. **写掩码限制（全写口）**
   - 所有指向该 `memSymbol` 的 `kMemoryWritePort` 的 `oper[3]`（mask）必须为 `kConstant`。
   - 若存在非常量 mask，整块 memory 跳过（不部分转换）。

3. **初始化限制（simple init）**
   - 允许以下简单模式：
     - 无 init 属性（按默认零值处理）；
     - 仅 `literal` 初始化，且可解析为“行 -> 常量值”映射。
   - 不允许：`readmemh/readmemb`、`$random`、或无法静态求值的初始化表达式。

4. **结构完整性检查**
   - 目标 memory 的 read/write 端口均位于当前 graph 内可遍历到；
   - `eventEdge` 长度与 `events` 数量一致（若不一致先报错并跳过）。

## 5. 核心重写规则

## 5.1 `kMemory` -> 行寄存器集合

设：
- 行数 `R = row`
- 位宽 `W = width`
- memory 符号 `M`

生成 `R` 个寄存器：
- `M$row$0`, `M$row$1`, ..., `M$row$R-1`
- 每个 `kRegister`：
  - `width = W`
  - `isSigned = mem.isSigned`
  - `initValue = initMap[i]`（若存在）

其中 `initMap[i]` 由 memory init 线性化后得到：
- 未命中行使用 `0`（位宽对齐）。
- 多条 literal 初始化按原顺序覆盖（后者覆盖前者）。

## 5.2 `kMemoryReadPort` -> 多读口 + Mux

对每个 memory 读口：
1. 为每个行寄存器 `M$row$i` 生成 `kRegisterReadPort`，得到 `rowData[i]`。
2. 为每个 `i` 生成地址比较：`hit[i] = (addr == i)`。
3. 用 `kMux` 链/树将 `rowData` 聚合为单输出：
   - 语义：`out = rowData[addr]`（当 `addr` 越界时保持原 IR 约定，建议默认 0）。

建议实现：从高行号到低行号构建右结合 mux 链，保证确定性命名与稳定 diff。

## 5.3 `kMemoryWritePort` -> 多写口 + 行使能

对每个 memory 写口 `wp`：
1. 复制事件列表与边沿：
   - 新 `kRegisterWritePort` 的 `oper[3..]` 直接复用 `wp.oper[4..]`；
   - `attrs.eventEdge` 直接复制 `wp.eventEdge`。
2. 对每个行 `i` 生成行使能：
   - `hit[i] = (addr == i)`
   - `rowEn[i] = updateCond & hit[i]`
3. 为每行寄存器 `M$row$i` 生成一个写口：
   - `regSymbol = M$row$i`
   - `updateCond = rowEn[i]`
   - `nextValue = data`
   - `mask = constMask`（来自原 `wp.oper[3]`）
   - `events/eventEdge` 与原写口一致

说明：
- 由于 mask 已限定为常量，可直接沿用 `kRegisterWritePort` 的 mask 语义，无需额外位级拼接。
- 若 `constMask == 0`，可在构建时直接跳过该行写口（可选优化）。

## 5.4 符号与映射

pass 内维护：
- `memSymbol -> vector<regSymbol>`
- `oldReadPortOpId -> newReadValue`
- `oldWritePortOpId -> vector<newWritePortOpId>`

替换顺序建议：
1. 先建新 op/value；
2. 再替换旧 read 结果 uses；
3. 最后删除旧 read/write/memory op。

## 6. EventList 保持策略（重点）

为避免时序语义偏移，必须保证：

1. **逐写口保持**
   - 每个旧 `kMemoryWritePort` 拆出的所有新 `kRegisterWritePort` 使用同一组 `events` 与同一 `eventEdge`。
2. **顺序保持**
   - `events` 操作数顺序不变，`eventEdge[j]` 仍对应 `events[j]`。
3. **多写口保持**
   - 若 memory 原本存在多个写口，拆分后每个 row 允许对应多个写口，保持与原 IR 一致的“多写口并存”模型。

## 7. 实现落地分解（代码级）

## 7.1 文件落点
- 新增头文件：`wolvrix/include/transform/mem_to_reg.hpp`
- 新增实现：`wolvrix/lib/transform/mem_to_reg.cpp`
- 注册入口：`wolvrix/lib/core/transform.cpp`
  - include 新头文件
  - `availableTransformPasses()` 增加 `mem-to-reg`
  - `makePassByName()` 增加参数解析（`row-limit`、`strict-init`）
- 文档：`wolvrix/docs/transform/mem-to-reg.md`（后续实现完成后补齐）

## 7.2 类与流程建议

- `struct MemToRegOptions { int64_t rowLimit; bool strictInit; };`
- `class MemToRegPass : public Pass`
  - `run(Design&)`
  - `runOnGraph(Graph&)`
  - `collectCandidates(Graph&)`
  - `buildInitMap(const Operation& mem)`
  - `rewriteMemory(Graph&, Candidate&)`

图内流程：
1. 收集所有 `kMemory`；
2. 计算其 read/write 引用集；
3. 执行 eligibility；
4. 对候选执行重写；
5. 统计输出。

## 8. 统计与日志

建议输出：
- `memory_total`
- `memory_candidate`
- `memory_converted`
- `memory_skipped_row_limit`
- `memory_skipped_nonconst_mask`
- `memory_skipped_complex_init`
- `register_created`
- `readport_rewritten`
- `writeport_rewritten`

日志建议包含 graph 维度摘要，便于排查大图行为。

## 9. 验证计划

## 9.1 单元级 IR 用例（建议新增到 `wolvrix/tests/transform/data`）

1. `mem_row2_constmask_fullwrite`
   - 2 行 memory，全写 mask 常量，验证读写等价。
2. `mem_row4_constmask_partialwrite`
   - 常量部分 mask，验证位选择写入。
3. `mem_nonconst_mask_skip`
   - 含变量 mask，验证 pass 跳过。
4. `mem_complex_init_skip`
   - `readmemh` 或 `$random`，验证跳过。
5. `mem_eventlist_async_reset`
   - 多事件（如 `posedge clk` + `negedge rst_n`），验证拆分后 `events/eventEdge` 完整保留。

## 9.2 回归策略
- 与 `simplify` 串联跑一轮等价性检查（至少行为级仿真一致）。
- 在小图（hdlbits）和大图（xs 子图）各选 1~2 个样例做 smoke。

## 10. 风险与防护

1. **IR 膨胀风险**
   - `R` 行会放大读写口数量，故必须使用 `row_limit` 严格截断。
2. **越界地址语义风险**
   - 需统一定义 mux 默认分支（建议 0）并在文档声明。
3. **初始化语义偏移**
   - 仅支持 simple init；复杂 init 直接跳过，避免错误降级。
4. **多写口竞争语义**
   - 保持原事件列表和写口数量，不在本 pass 引入仲裁逻辑。

## 11. 分阶段实施建议

### Phase A（最小可用）
- 支持：`row_limit` + 常量 mask + 无 init。
- 目标：跑通结构重写与 eventList 保持。

### Phase B（完整 simple init）
- 加入 literal init 映射与覆盖顺序处理。

### Phase C（工程化）
- 完善统计、错误信息、文档与回归样例。

---

## 附：关键伪代码

```cpp
for (auto mem : graph.memories()) {
  if (!eligible(mem, options)) continue;

  auto rows = createRowRegisters(mem, initMap);

  for (auto rp : users.readPortsOf(mem)) {
    Value newData = lowerReadPortToMux(rp, rows);
    replaceAllUses(rp.result(0), newData);
    eraseOp(rp);
  }

  for (auto wp : users.writePortsOf(mem)) {
    auto events = wp.events();      // old oper[4..]
    auto edges  = wp.eventEdge();   // attrs
    for (int i = 0; i < mem.row(); ++i) {
      Value hit = buildAddrEq(wp.addr(), i);
      Value en  = buildAnd(wp.updateCond(), hit);
      createRegisterWritePort(rows[i], en, wp.data(), wp.maskConst(), events, edges);
    }
    eraseOp(wp);
  }

  eraseOp(mem);
}
```
