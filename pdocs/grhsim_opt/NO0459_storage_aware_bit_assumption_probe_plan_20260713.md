# NO0459 Storage-aware bit assumption probe plan

日期：2026-07-13

## 1. Correction and objective

[NO0458](./NO0458_simtop_one_bit_and_or_representative_static_gate_20260713.md) 停止了对每个 width-1 AND/OR
operand 无差别插入 helper 的 broad candidate。下一步不是简单采用 raw-state-only assumption，因为 generated storage
类型核对显示：

```text
logicCppType(width=1): bool
value_bool_slots_:    std::array<std::uint8_t, 651848>
state_logic_storage_: byte-addressed storage, width-1 read as std::uint8_t
```

因此 materialized bool slot 与 packed state byte 都需要显式 0/1 assumption；只有 C++ `bool` local、comparison、
logical/reduce result 等由类型系统已知为 0/1 的 operand 才可能省掉 helper。本阶段先分类和小 O3 probe，不修改 emitter、
不重新 fresh emit SimTop。

## 2. Source classification

扫描 NO0457 的 66 个 compute sources 中全部 2,080,384 个 helper call sites，按 immediate argument source 互斥分类：

1. `value_bool_slots_` byte load；
2. `state_logic_storage_` width-1 byte load；
3. width-1 `state_reg_to_mem` / packed memory byte load；
4. C++ bool local / public port；
5. compare、logical、reduce 或显式 bool expression；
6. nested candidate byte expression；
7. constant 或其他 unresolved expression。

分类器必须逐文件流式扫描，call 总数与 NO0458 精确一致；不得用固定长度 regex 将 nested argument 错归为 leaf。
对 unresolved 输出 top shapes，直到至少 `99.9%` calls 可解释。

## 3. O3 probes

扩展 NO0454 的三种 shape，比较：

- current bool baseline；
- broad assumed-byte operands + byte result；
- storage-aware：byte storage load 保留 helper，C++ bool/comparison/reduce operand 直接 cast 为 byte，result 仍为 byte；
- nested byte result 不重复包 helper。

至少覆盖 packed state + value slot、state + compare、bool local + bool local、OR chain feeding AND。storage-aware 必须：

- 保留 NO0454 三种目标 shape 的 normalization 删除；
- 不增加 branch/memory-form；
- nested chain helper 数严格小于 broad candidate；
- 不依赖 UB assumption 作用于未审计的非 0/1 storage。

## 4. Decision gate

只有分类证明可移除的冗余 helper 占比足够大，且 O3 probe 在全部 shapes 不回退，才修改 emitter 和 fixture。修改后仍先
fresh emit 同一 SimTop，再编 batch `0/1/29/32/43`；五个 objects 的 aggregate memory/jumps 必须不高于 NO0357，
并要求 batch 0/1 不再出现 NO0458 的大幅 jump 增长。

若 storage-aware probe 不能同时保留 normalization 删除与消除 branch 回退，则停止 one-bit byte emit 整体方向，保留开关
默认关闭，不再用进一步局部 allowlist 追逐低于 direct 1% 的 57/12 sample 子类。
