# NO0401 Production scalar-load realization plan

日期：2026-07-12

## 1. Problem

[NO0400](./NO0400_direct_scalar_read_locality_dynamic_gate_20260712.md) 的 `10.050B` saved 是 generated C++ source
references 上界。Clang/O3 可能把同一 slot 的多次引用合成一次 load；如果不检查 production object，直接生成 typed local
可能只增加 locals/register pressure 和布局扰动，而不减少 instructions。

## 2. Exact-code line mapping

目标是 NO0357 production direct 的 compute batches 0..65。每个 sched translation unit 用相同 PCH 和
`clang++ -std=c++20 -O3` 重编，只增加 `-gline-tables-only`。逐 object dump `.text`，要求 debug-line object 与原 O3
object SHA256 完全相同；任一不同时，该 object 不进入统计。

class layout probe 固化五个 scalar array base offsets；`base + slot_index * element_size` 得到每个 canonical slot 在
`this` 中的唯一 displacement。反汇编筛选这些 memory operands，再用 `addr2line -i` 的 inline caller frame 映射回
`grhsim_SimTop_sched_N.cpp` source line和 supernode block。这样 `std::array::operator[]` 被归到 runtime header 的访问也能
回到真实 caller line。

## 3. Metrics

对 NO0392 每个 `candidate=1` row，记录：

```text
source_saved_per_fire  = operand_touches - 1
machine_accesses       = production instructions reading that slot in the supernode block
machine_redundant      = max(machine_accesses - 1, 0)
dynamic_machine_saved  = machine_redundant * NO0399 direct fire
```

`machine_accesses=0` 表示 load 被跨表达式/控制流 hoist 或以其他合并形式实现，不把它强行修正为 1。统计全模型、
touch threshold、batch、compute62 和代表 rows，并报告无法映射的 candidate/displacement/address 数。

## 4. Preflight cases

先检查全局 top、compute62 top 和 touch=2/3/4 代表。line-table object 的 `.text` 必须与 production byte-identical，
随后才扩展到 66 个 compute objects。代表结果只用于验证方法，不作为全局结论。

## 5. Decision

若全量 dynamic machine redundant：

1. 低于 source saved 上界的 `10%`，或
2. 低于 NO0388 direct compute `139.750B` instructions 的 `1%`，

则停止 typed-local 实现，结论为 source-level 假热点/已被 O3 大幅消除。只有同时超过两条门槛、且无法映射比例足够低，
才实现默认关闭的只读 typed local cache，并重新走 SimTop 功能与 exact-entry runtime gate。

本篇只声明全量 realization 方法；尚未形成 66-batch 结论。
