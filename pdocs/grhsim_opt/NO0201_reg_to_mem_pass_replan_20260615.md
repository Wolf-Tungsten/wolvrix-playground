# NO0201 Reg-to-Mem Pass Replan

记录日期：2026-06-15

## 目标

重新规划 `reg-to-mem` pass，目标是把被 SV scalarize 成一组 `kRegister` 的数组形态重新恢复成低成本 memory/array 访问形态。

本计划仅以本轮需求为设计输入。已有寄存器合并 pass 已从可构建源码、测试目标和 Python pass 入口中移除，后续实现不得复用其策略、命名启发或规划结论。

`reg-to-mem` 的目标插入位置是 `activity-schedule` 之前。GrhSIM 默认流程中建议放在 `memory-init-check` 之后、pre-schedule `stats` checkpoint 之前，使 checkpoint 与 schedule 都看到同一个结构。

该 pass 必须自己保证不引入环。它不能依赖后续 `comb-loop-elim` 或额外 repair pass 来修正 rewrite 后的图。

## 总体策略

`reg-to-mem` 分两级处理：

1. 真合并：读侧和写侧都满足严格闭包条件时，实际把一组 `kRegister` 改写为一个 `kMemory`。
2. 意向合并：读侧满足数组访问模式，但写侧不满足真合并条件时，不改变 IR 语义，只在相关 op 上打 attr，交给 `activity-schedule` 和 `grhsim-cpp` emit 做低成本数组索引。

两级处理共享同一套读侧候选发现逻辑。候选发现必须基于 op kind、operand/result 拓扑、value user 集合和必要 attrs，不允许按 register/value/op 名称匹配。

## 读侧候选发现

候选从 `kSliceArray` 或可解析的 `kSliceDynamic` 开始反向匹配：

```text
read_i   = kRegisterReadPort(reg_i)
packed   = kConcat(read_N-1, ..., read_1, read_0)
result   = kSliceArray(packed, index)
```

或：

```text
result = kSliceDynamic(packed, start)
start  = index * elementWidth
```

基础约束：

- slice 的 `oper[0]` 必须由一个 `kConcat` 定义。
- `kConcat` 的每个 operand 必须由 `kRegisterReadPort` 定义。
- 每个 read port 的 `regSymbol` 必须指向一个存在的 `kRegister`。
- 所有目标 register 必须是 `Logic`，位宽相同，signedness 相同。
- `kSliceArray.sliceWidth` 或 `kSliceDynamic.sliceWidth` 必须等于单个 register 的位宽。
- `kConcat` result 宽度必须等于 `elementWidth * elementCount`。
- concat operand 顺序定义 memory row 顺序。必须显式记录 `concat operand index -> row index -> regSymbol` 的映射，不能从名称推断。

首版只支持完整行读取。`kSliceArray` 必须读取完整 row；`kSliceDynamic` 只接受 `start = index * elementWidth` 或等价的 constant-fold 后形态，且 `sliceWidth == elementWidth`。带非零 lane offset 的 partial row select 不进入真合并。

## 真合并：读侧闭包条件

同一组 register 可以有多个读 anchor。每个 anchor 对应一套独立的 `read ports -> concat -> slice` 闭包，最终 lowering 成共享同一个 `kMemory` 的一个 `kMemoryReadPort`。

每个读 anchor 必须形成单出口闭包：

- 一个读 anchor 只允许产生一个最终 read result，即该 anchor 的 slice result。
- `kRegisterReadPort` result 的所有 users 都必须在闭包内。
- `kConcat` result 的所有 users 都必须是该 anchor 的 slice op。
- 闭包内部 op 产生的中间 value 不允许被闭包外 op 使用。
- slice result 可以有多个外部 users，因为它是闭包唯一输出。
- 目标 register symbols 不允许存在本次真合并事务外的其它 `kRegisterReadPort`。

多 anchor group 额外约束：

- 所有 anchor 必须覆盖同一组 `regSymbol`。
- 所有 anchor 的 row order 必须一致，即 `row -> regSymbol` 映射完全相同。
- 每个 anchor 可以有自己的读地址 value；不同 anchor 不要求共享地址。
- 每个 anchor 的 `kConcat` 和 `kRegisterReadPort` op 必须只属于一个 anchor，不允许两个 anchor 共享同一个中间 op。

闭包内成员：

- candidate `kRegisterReadPort` ops
- candidate `kConcat`
- candidate `kSliceArray` 或 `kSliceDynamic`
- 对 `kSliceDynamic` start 做规范化时识别出的纯地址计算不纳入闭包，除非它只服务该 slice 且实现选择删除它

闭包条件是防环条件的一部分。读侧 rewrite 对每个 anchor 用一个 `kMemoryReadPort(addr_i)` 替代原 `concat + slice`，动态输入仍是该 anchor 原 slice 的 index/address。rewrite 删除的是 register-read-to-concat 这条状态展开路径，不新增从 read result 回到 addr 的依赖。

## 真合并：写侧匹配

写侧必须把这些 register 的写口统一解释成同一个 indexed memory write：

```text
reg_i.write.updateCond = commonGuard && (addr == row_i)
reg_i.write.nextValue  = commonData
reg_i.write.mask       = commonMask
```

要求：

- 每个目标 register 必须被同一组写 family 覆盖。MVP 只接受一个 regular write family，加一个可选 reset/fill family。
- regular family 中所有 `kRegisterWritePort` 的 event operands 必须逐项相同，`eventEdge` attr 必须逐项相同。
- regular family 中所有 data operand 必须是同一个 `ValueId`，或通过后续明确支持的结构等价规则证明相同。MVP 只要求同一个 `ValueId`。
- regular family 中所有 mask operand 必须是同一个 `ValueId`，且位宽等于 row width。lowering 到 `kMemoryWritePort` 时直接复用这个 mask value。
- guard 必须能拆成相同的 common condition 加一个地址相等项。

guard 拆分规则：

1. 把 `kLogicAnd` 树拍平成 term 集合，允许穿过无语义的 `kAssign`。
2. 在每个 row 的 term 集合中找到唯一一个 equality term。
3. equality term 必须是 `addr == constant` 或 `constant == addr`，op kind 首版只接受 `kEq`，不接受 `kCaseEq`。
4. 所有 row 的 equality term 必须共享同一个 `addr` value。
5. equality 常量必须互不相同，并且和读侧 row 映射一致。首版只接受零基连续地址，常量集合必须正好是 `0..elementCount-1`。
6. 移除 equality term 后，剩余 term 集合必须相同。MVP 可以先要求它们引用同一批 `ValueId`，后续再加结构 hash。

如果 `addr` 位宽能表示 `elementCount` 之外的值，生成 memory write guard 时必须保留 in-domain 保护：

```text
memoryWrite.updateCond = commonGuard && (addr in {0, ..., elementCount-1})
```

当 `elementCount` 是 `2^addrWidth` 时，in-domain 保护可以省略。否则需要生成 OR-of-eq 或范围检查。不能让 memory write 在原来没有任何 row 被写的地址上发生。

## 真合并：reset/fill

如果原 register 组存在批量复位语义，真合并必须能等价支持这类复位，并用 `kMemoryFillPort` 表示。没有批量复位的候选不需要生成 fill。

设计上需要识别两种批量 reset 形态：

1. 独立 reset write family：

```text
reg_i.write.updateCond = resetGuard
reg_i.write.nextValue  = resetData_i
```

2. reset 与 regular write 合在同一个 write port：

```text
activeWriteGuard_i     = resetInactive && commonGuard && (addr == row_i)
reg_i.write.updateCond = resetGuard || activeWriteGuard_i
reg_i.write.nextValue  = mux(activeWriteGuard_i, commonData, resetData_i)
```

同一个 write port 的形态也允许 mux 条件使用 `resetGuard`：

```text
reg_i.write.nextValue = mux(resetGuard, resetData_i, commonData)
```

但无论 mux 条件选择哪一个 OR arm，pass 都必须把这个物理 `kRegisterWritePort` 拆成两条 logical write：

- logical regular write：`guard = activeWriteGuard_i`，`data = commonData`
- logical reset/fill write：`guard = resetGuard`，`data = resetData_i`

这里的 split 只改变匹配和 rewrite 语义，不要求原 IR 里先存在两条写口。rewrite 成功后，这个物理 `kRegisterWritePort` 只删除一次。

存在批量 reset 时的 lowering 结果：

```text
fill.updateCond = resetGuard
fill.data       = resetData
fill.events     = reset events

write.updateCond = activeCommonTerms && inDomain(addr)
write.addr       = addr
write.data       = commonData
write.mask       = commonMask
write.events     = regular events
```

没有批量 reset 时，只生成 regular `kMemoryWritePort`，不生成 `kMemoryFillPort`。

关键要求：

- resetGuard 必须在所有 row 上相同。
- reset/fill 与 regular write 的 update condition 必须互斥，或者 fill 必须在语义上严格优先。首版采用互斥 guard：同一 write port split 时，`activeWriteGuard_i` 的 common terms 中必须能看到 `!resetGuard`，否则拒绝真合并。
- `resetGuard || activeWriteGuard_i` 首版只接受二元 `kLogicOr`，以及 1-bit `kOr` 的等价形态；logical regular guard 内的 AND 拆分接受 `kLogicAnd`，以及 1-bit `kAnd` 的等价形态。
- 地址命中项首版接受 `kEq(addr, constant)` / `kEq(constant, addr)`；对全 1 row，也接受 `kReduceAnd(addr)` 作为 `addr == all_ones` 的等价形态。
- 如果所有 `resetData_i` 是同一个 row-width value，`kMemoryFillPort.oper[1]` 使用 row-width data。
- 如果每个 row reset value 不同，首版必须支持按当前 row order 构造 packed value，并让 `kMemoryFillPort.oper[1]` 使用 `elementWidth * elementCount` 的 packed data。
- 如果 reset value 既不同又不能构造稳定 packed data，拒绝真合并，转意向合并。
- `kRegister` declaration 上的 init 属性必须转换成等价 `kMemory` init 属性；无法转换时拒绝真合并。runtime reset 仍通过 `kMemoryFillPort` 表达，不塞进 declaration init。

当前首版实现边界：

- 支持独立 reset write family。独立 reset 与 regular write 使用同一 event family 时，首版仍拒绝，除非它们来自同一个物理 write port 的 `resetGuard || activeWriteGuard_i` / mux split。
- 支持同一物理 write port 的 `reset || activeWriteGuard` 加 mux data 形态，并把它 split 成 `kMemoryFillPort` + `kMemoryWritePort`。
- 已支持所有 row reset data 相同的 row-width fill，以及不同 row reset data 的 packed fill。
- 已支持把每个 `kRegister.initValue` 转成 `kMemory` 的 per-row literal init attrs。

## 真合并：IR rewrite 结果

真合并成功后：

- 删除目标 `kRegister` declarations。
- 新建一个 `kMemory`：
  - `width = elementWidth`
  - `row = elementCount`
  - `isSigned = register signedness`
- 读侧：
  - 对每个读 anchor 新建一个 `kMemoryReadPort(memSymbol)`。
  - 每个 `kMemoryReadPort.oper[0] = normalizedAddr_i`，来自对应 anchor 的 slice index/address。
  - 用各自 memory read result 替换对应原 slice result 的所有 users。
  - 删除所有候选 read/concat/slice 闭包中不再使用的 op。
- 写侧：
  - 用一个 `kMemoryWritePort` 替代 regular write family。
  - 可选新增一个 `kMemoryFillPort` 替代 reset/fill family。
  - 删除被替代的 `kRegisterWritePort`。
- 不引入额外 repair pass。rewrite 后必须立即做本地图合法性检查和拓扑/依赖检查，失败则回滚或不提交该候选。

## 意向合并

意向合并触发条件：

- 读侧 `kRegisterReadPort + kConcat + kSliceArray/kSliceDynamic` 模式匹配成功。
- 写侧真合并条件不满足。
- 读侧闭包可以不满足真合并的“全 register ownership”要求，因为意向合并不在 `reg-to-mem` pass 内改写 GRH IR；这里的“不改写”只表示 `kRegister*` op 仍作为语义节点存在，不表示生成模型保留旧 register state。

意向合并在 `reg-to-mem` pass 内只打 attr，不改变 operands/results，不删除 op，不把 `kRegister` 替换成 `kMemory`。但这是 IR 层约束，不是物理 state 约束。GrhSIM emit 一旦接受完整 intent group，必须把这一组 register 的物理存储迁移到新的 array-like 成员变量上；旧的 scalar register state member 必须删除，不能同时生成 scalar 镜像。闭包外针对这些 register 的普通 read/write 也必须通过 row 映射访问这个新成员变量。

建议 attr schema：

```text
regToMem.intent.version = 1
regToMem.intent.group   = "<graph-local-id>"
regToMem.intent.role    = "read" | "concat" | "slice"
regToMem.intent.mode    = "array-index"
```

在 `kConcat` 上记录：

```text
regToMem.intent.elementWidth = W
regToMem.intent.elementCount = N
regToMem.intent.regSymbols   = [row0Reg, row1Reg, ...]
regToMem.intent.operandRows  = [row index per concat operand]
```

在 `kRegisterReadPort` 上记录：

```text
regToMem.intent.group = group
regToMem.intent.row   = row_i
```

在 slice op 上记录：

```text
regToMem.intent.group       = group
regToMem.intent.sliceKind   = "slice-array" | "slice-dynamic"
regToMem.intent.elementWidth = W
```

`group` 必须由 graph-local stable counter 生成，不从符号名派生。attr 值必须使用当前 GRH 支持的 JSON-serializable 类型。

## activity-schedule 消费意向 attr

`activity-schedule` 看到同一个 `regToMem.intent.group` 时，要把该组打包成不可拆分的 compute node：

- group members 包括 participating `kRegisterReadPort`、`kConcat`、slice op。
- source clone 逻辑不能把 group 内部 read-to-concat use 拆散。
- 该 compute node 的 boundary inputs 是 slice index/address 以及其它非 group operand。
- 该 compute node 的唯一语义输出是 slice result。
- coarsen 和 DP 分段不能拆开 group 内成员。
- group 内部仍按本地 topo order emit。

这样调度层不会把大量 register read、concat 和 slice 分散到不同 compute node，避免 emit 端失去数组索引优化的上下文。

## grhsim emit 消费意向 attr

emit 看到完整 group 时，不生成运行时大规模 concat。

目标 code shape：

- 在生成模型里为意向合并组创建一个独立的 memory-like / array-like 成员变量，布局为 `row[elementCount]`，每行宽度为 `elementWidth`。
- 该成员变量接管这组 register 在 GrhSIM 生成模型里的物理存储；每个目标 register 的独立 scalar state member 必须删除。
- 原 GRH IR 中的 `kRegister` / `kRegisterReadPort` / `kRegisterWritePort` op 可以仍存在，但 emit 的 state allocation 要把每个 `regSymbol` 映射到该数组成员的对应 row；这些 op 只是访问数组 row 的语义入口，不再拥有独立 storage。
- 闭包外普通 register read/write 也必须通过这个 row 映射访问同一个数组成员，不能再访问或生成独立 scalar storage。
- 写侧不能保持一份原始 register state 镜像；原本写到 `reg_i` 的 update 必须直接 lowering 成对意向数组 `row_i` 的 update。
- 对 `kSliceArray(concat, idx)` 生成一次 row index 访问。
- 对可解析 `kSliceDynamic(concat, idx * W)` 生成同样的 row index 访问。
- 结果直接从意向数组成员读取 selected row，不物化 packed concat。

示意形态：

```cpp
// shape only
RegToMemIntentArray<W, N> reg_to_mem_group_X;
auto row = reg_to_mem_group_X.read(idx);
```

关键点是改变生成模型的内部内存排布，让意向合并组像 memory 一样成为独立成员变量。所有目标 register 的读写都落到这个成员变量的 row 上，读侧数组索引也访问同一个成员变量，避免运行时构造 `N * W` 位 packed 临时值。状态只允许有这一份；如果同时保留旧 scalar register state，就会产生双写一致性问题，必须视为错误实现。

如果 emit 发现 group attr 不完整、row width 不一致或某个目标 register 无法映射到该数组成员，必须整组回退普通 register/concat/slice emit。回退时不生成意向数组；接受 intent group 时不生成 scalar register state。两种物理 state 形态不能同时存在。

## 2026-06-16：CASE_024 intent index 修复记录

本节记录一次已经踩过的坑，后续改 `reg-to-mem intent` / `activity-schedule source clone` / `grhsim-cpp emit` 时必须复查。

复现案例：

```text
testcase/xs-bugcase/CASE_024
DUT: ICacheWayLookup
失败点: cycle=5 phase=high read_maybe_rvc
ref    = 0xcaff020313541415
grhsim = 0xcafe000013570000
```

根因不是 intent array 写入错误。调试确认 `state_reg_to_mem_rtm_intent_0/1_[1]` 在 GrhSIM 中已经写成了正确值；真正错误是读侧 index 仍为 `0`。

错误 code shape：

```cpp
state_reg_to_mem_rtm_intent_1_[value_u8_slots_[152]]
state_reg_to_mem_rtm_intent_0_[value_u8_slots_[151]]
```

`value_u8_slots_[151]` / `[152]` 来自 `readPtr_value` 的 cloned `kRegisterReadPort` result。activity schedule 的 source clone 会把 compute consumer 上的 source value 替换成 clone value，但 emit 对 register read source 常常直接 inline 成 state storage ref，不一定给 clone result 生成 materialized slot 赋值。于是 intent slice 专用路径如果强行用 `resolvedScheduleValueExpr()` 读取 persistent slot，就可能读到一个没有生产者的 value slot。

正确规则：

- intent array index 不能盲目依赖 materialized value slot。
- 对 intent `kSliceArray` / 可解析 `kSliceDynamic(index * W)` 的 index value，emit 应优先解析为稳定叶子表达式：
  - supernode local expr
  - stored value ref
  - input field
  - constant
  - `kRegisterReadPort` / `kLatchReadPort` 对应的 state ref
- 只有上述都不适用时，才回退到普通 `resolvedScheduleValueExpr()`。

修复点：

- `grhsim-cpp` 增加 intent index resolver，`readPtr_value` 这类 register read index 直接 emit 为 `grhsim_value_storage_ref(... state_logic_storage_ ...)` 或对应 state alias，而不是未赋值的 `value_u*_slots_[]`。
- `activity-schedule` 对 intent group 的 source operand 仍要确保 source owner node 存在；这保证真正需要 boundary slot 的场景有合法 producer，但不能替代 emit 侧的 stable index resolver。
- `transform-activity-schedule` 单测增加 register-read index 的 intent group 形态，防止 source clone + intent boundary 再次断链。

修复后的目标 code shape：

```cpp
state_reg_to_mem_rtm_intent_1_[static_cast<std::size_t>(
    static_cast<std::uint64_t>(grhsim_value_storage_ref<std::uint8_t>(state_logic_storage_, 1028)))]
```

验证命令：

```bash
cmake --build wolvrix/build --target wolvrix-lib emit-grhsim-cpp transform-activity-schedule
ctest --test-dir wolvrix/build --output-on-failure -R 'transform-activity-schedule|emit-grhsim-cpp'
ctest --test-dir wolvrix/build --output-on-failure -R transform-reg-to-mem

# CASE_024 走 Python skbuild 产物，必须重建 skbuild 里的 libwolvrix-lib.so。
cmake --build wolvrix/build/skbuild --target wolvrix-lib
make -C testcase/xs-bugcase/CASE_024 run \
  WOLVRIX_PY=python3 \
  PYTHONPATH=/home/gaoruihao/wksp/wolvrix-playground/wolvrix/build/skbuild/python
```

本次验证结果：

```text
[PASS] CASE_024 ICacheWayLookup ref == grhsim
```

## 2026-06-16：完整 XiangShan refillBuf intent index 断链记录

本节记录从完整 XiangShan `coremark` 波形里确认的同类问题。后续如果再看到前端 refill/assert mismatch，先检查这里，不要从上游请求路径盲猜。

失败入口：

```text
checker: testcase/xiangshan/difftest/src/test/csrc/difftest/checkers/refill.cpp:90
assert : testcase/xiangshan/src/main/scala/xiangshan/frontend/icache/ICacheMissUnit.scala:370
RTL    : build/xs/rtl/rtl/Slice_1.sv + RequestArb.sv + MSHRBuffer.sv
```

波形对比结论：

- 模块边界上游不是根因。`Slice_1.reqArb.task_s2_bits_mshrId` 在 GrhSIM 与 Verilator 都指向 `id=1`。
- `RequestArb.sv` 明确 `io_refillBufRead_s2_bits_id = task_s2_bits_mshrId`，所以这里不应该变成 `0`。
- 分叉点在 `Slice_1.refillBuf` 读侧：GrhSIM 在 `task_s2_bits_mshrId=1` 时实际用 `refill_id=0` 读 intent array，读出了旧的 source=84 数据；Verilator 同语义读 `id=1`，拿到正确 source=88 数据。

保留的取证文件：

```text
tmp/xs_regtomem_wave_20260616_161520/l2_request_arb_path_grhsim.tsv
tmp/xs_regtomem_wave_20260616_161520/l2_request_arb_path_verilator.tsv
tmp/xs_regtomem_wave_20260616_161520/l2_refill_grant_path_grhsim.tsv
tmp/xs_regtomem_wave_20260616_161520/l2_refill_grant_path_verilator.tsv
```

关键 IR 链：

```text
_op_10244627 kRegisterReadPort task_s2_bits_mshrId -> _val_9433263
_op_10246317 kAssign _val_9433263 -> reqArb.io_refillBufRead_s2_bits_id
_op_10306573 kAssign reqArb port -> Slice_1._reqArb_io_refillBufRead_s2_bits_id
_op_10304630 kSliceStatic [3:0] -> _val_9484938
_op_10304631/_op_10304636 kSliceArray intent rtm_intent_488/489 indexed by _val_9484938
```

错误 code shape：

```cpp
state_reg_to_mem_rtm_intent_209_[static_cast<std::size_t>(
    static_cast<std::uint64_t>(value_u8_slots_[84626]))]
```

`value_u8_slots_[84626]` 对应 `_val_9484938`，但生成 C++ 里没有 `_op_10304630` 的赋值。根因与 `CASE_024` 一致：intent slice 快路径直接用 schedule value slot 作为 index，而 index 的定义链被 source clone/inline 后没有物化成该 slot。

修复规则需要覆盖的不只是 `kRegisterReadPort` 叶子，也包括短组合链：

- `kAssign`
- `kSliceStatic`
- `kSliceDynamic`
- 常量、input、register/latch read leaf

当前 `grhsim-cpp` 修复是在 `resolvedRegToMemIntentIndexExpr()` 中优先调用 `pureExprForValue()`，并用 `totalOps <= 32` 限制索引表达式大小；解析失败才回退到 `resolvedScheduleValueExpr()`。这让完整 XiangShan 中的 refillBuf 下标直接从 `task_s2_bits_mshrId` state ref 派生，而不是读取未生产的 value slot。

期望修复后 code shape：

```cpp
state_reg_to_mem_rtm_intent_209_[static_cast<std::size_t>(
    static_cast<std::uint64_t>(
        static_cast<std::uint8_t>(
            (grhsim_value_storage_ref<std::uint8_t>(state_logic_storage_, 919120) >> 0) & UINT64_C(15))))]
```

特别注意：只构建 `wolvrix/build/libwolvrix-lib.so` 不会更新 `CASE_024` 使用的 Python 扩展路径。`wolvrix/build/skbuild/python/wolvrix/_wolvrix.so` 链接的是：

```text
wolvrix/build/skbuild/libwolvrix-lib.so
```

因此排查 xs-bugcase 时，如果生成 C++ 没有反映刚改的 emitter，先检查并重建 `wolvrix/build/skbuild`，不要误判为修复无效。

## 验证计划

最小单元测试：

- 真合并：`regRead + concat + sliceArray`，write guard 为 `wen && addr == const_i`，生成 `kMemoryReadPort + kMemoryWritePort`。
- 真合并：同上但 `sliceDynamic(index * W)`。
- 真合并：同一组 register 有多个读 anchor，生成多个共享同一 `kMemory` 的 `kMemoryReadPort`。
- 拒绝：多 anchor 的 row order 不一致。
- 真合并：同步 reset，生成 `kMemoryFillPort`。
- 真合并：异步 reset events，fill/write events 与原语义一致。
- 拒绝：concat result 被其它 op 使用。
- 拒绝：某个 register 有候选外 read port。
- 拒绝：write guard 地址常量不完整、不唯一或 common condition 不一致。
- 拒绝：row data/mask 不同。
- 意向合并：读侧命中但写侧不匹配，只产生 attrs，不改变 op 数和语义。
- 名称无关：随机化 register/op/value symbol 后仍能命中同样候选。

集成测试：

- `activity-schedule` 对意向 group 输出单个 compute node。
- `grhsim-cpp` 对意向 group 不物化 wide concat。
- true merge 后无需再跑 repair pass，activity schedule 能直接成功。

## 已定首版范围

- 读侧只支持完整行读取：`kSliceArray` 完整 row，或 `kSliceDynamic(start = index * W, sliceWidth = W)`。
- 写侧地址只接受零基连续地址：`0..N-1`。
- guard equality 首版只接受 `kEq`，不接受 `kCaseEq`。
- row reset value 不同的批量复位，首版必须支持 packed reset data，并用 packed-width `kMemoryFillPort.oper[1]` 表达。
