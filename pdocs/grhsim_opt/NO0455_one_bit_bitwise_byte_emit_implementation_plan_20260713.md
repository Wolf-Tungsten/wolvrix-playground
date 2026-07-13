# NO0455 One-bit bitwise byte emit implementation plan

日期：2026-07-13

## 1. Scope

[NO0454](./NO0454_boolean_byte_normalization_machine_audit_gate_20260713.md) 只允许 assumed-byte operands + byte result
进入实现。本阶段实现默认关闭的最小 emitter candidate，不重排 schedule、不改 value/state storage layout，也不改变 changed、activation
或 commit。

配置：

```text
EmitOptions attribute: one_bit_bitwise_bytes
Environment:          WOLVRIX_GRHSIM_ONE_BIT_BITWISE_BYTES
Default:              false
```

默认关闭产物不能出现新 helper 或 byte-result source；unset/0 必须保持当前输出。开关只影响 result width 恰为 1 的
`kAnd/kOr/kXor/kNot/kXnor`，不改变 logical operators、compare、mux、reduce 或 width > 1 bitwise operations。

## 2. Expression representation

在 `ScalarLogicExpr` 增加 `byteBitResult` 属性。开关命中时：

- width-1 operand 移除仅用于 C++ truth normalization 的最外层 `static_cast<bool>` 与 redundant `uint64_t` cast；
- operand 包装为 always-inline `grhsim_assume_bit_u8(...)`，向 Clang/GCC 声明值域为 0/1；
- AND/OR/XOR 直接生成 byte bitwise expression；
- NOT/XNOR 以 XOR `UINT8_C(1)` 表示 1-bit complement，不能对 byte 直接 `~`；
- materialized `next_value` 和非 materialized local 均用 `std::uint8_t`；写入仍落到原 `value_bool_slots_`；
- downstream width-1 bitwise op 继续消费 assumed byte，不提前转回 bool。

helper 对 Clang 使用 `__builtin_assume(value <= 1)`，GCC 使用超范围 `__builtin_unreachable()`，其他编译器保守返回原值。helper 只在
开关开启的 generated runtime 中出现；不能把 packed state `uint8_t&` reinterpret 成 `bool&`。

## 3. Unit gates

新增专用 width-1 DAG fixture，至少覆盖：

1. materialized AND result 与 change propagation；
2. OR chain feeding AND，验证中间 local 保持 byte；
3. XOR/NOT/XNOR 的 0/1 语义；
4. state read + value slot operand；
5. default/unset、attribute=0、attribute=1 三种 emit。

source assertions：

- default/0 无 `grhsim_assume_bit_u8`，结果仍为 `const bool`；
- enabled runtime 有 helper，目标结果为 `const std::uint8_t`；
- enabled source 不含目标 state operand 的逐项 `static_cast<bool>`；
- width 8 AND 和 `kLogicAnd` 仍保持原形；
- NOT/XNOR 明确使用 `^ UINT8_C(1)`。

编译并运行 exhaustive 1-bit harness，枚举输入组合，对 default 与 candidate 输出逐项比较；同时运行现有
`emit-grhsim-cpp` 与 memory-fill tests。

## 4. Local O3 gate

对 fixture 的 default/candidate generated sched 使用 `clang++ -std=c++20 -O3`，比较目标函数：

- state2/state+slot 不再有 operand `cmpb/setne` pair；
- OR chain 不出现 raw-byte SLP 回退；
- candidate branch 与 memory-form instructions 不增加；
- candidate 总 instructions 至少减少 1 条。

若 fixture 通过，再 fresh emit current SimTop，先只编译 NO0454 命中的代表 batch 0/1/29/32/43，并按 source marker 连接目标块。
至少 3 个不同 source shapes 真删 normalization、且代表 objects 总 `.text`/branch/memory 不恶化，才扩展 full build。

## 5. Stop conditions

- 任何 1-bit truth table mismatch；
- default/unset source 改变；
- helper assumption 未被 O3 内联或 bool cast 重新出现；
- NOT/XNOR 高位补码污染；
- OR chain 再次 SLP 回退；
- representative SimTop objects 目标删指令但整体静态指标恶化。

命中任一条件即关闭候选并记录 gate，不进入 SimTop runtime。
