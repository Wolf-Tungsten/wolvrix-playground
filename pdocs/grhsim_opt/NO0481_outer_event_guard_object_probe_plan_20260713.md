# NO0481 Outer event guard object probe plan

日期：2026-07-13

## 1. Scope

基于 [NO0480](./NO0480_event_pure_compute_supernode_audit_gate_20260713.md)，选择 batches 58/21/35/41/24/30：

- 855 个 event-pure supernodes；
- 4,527 条 transient producer declarations；
- 2,918 个 SystemTask + 2,665 个 DPIC；
- 151 profile samples/direct `2.262%`。

只修改 NO0357 generated source 副本，不修改 emitter/production objects。

## 2. Transformation

对 audit TSV 中精确记录的每个 payload scope，在第一个 producer/comment 前增加：

```cpp
if (event_edge_slots_[slot] == grhsim_event_edge_kind::{pos,neg}edge) {
```

并在 payload scope 末尾闭合。supernode entry、active-bit clear、outer dispatch/restore 均保持原位。内部每个 SystemTask/DPIC
exact guard 不删除、不重排，由 `-O3` 自行做 redundant-condition elimination。

transform gate 要求：

- 每个插入点重新解析后仍对应同一 supernode/payload；
- candidate 与 baseline 的原始 source lines byte-exact，仅多两条 brace/guard lines；
- mixed/external-write/non-event supernodes 0 修改；
- production source/object SHA 前后不变。

## 3. Object gate

用 NO0357 PCH、`clang++ -std=c++20 -O3` 各重编 6 个 baseline/candidate objects。baseline rebuild `.text` 必须与
production 一致。

进入 emitter implementation 的条件：

1. aggregate `.text`、instructions、memory-form、jumps 均不增加，且无单对象明显回退；
2. calls 不增加；
3. representative debug block 的 edge-false branch 位于 producer slot/state loads 之前，并越过完整 payload；
4. posedge path 保持原 side-effect call order，内部 redundant edge checks 至少不增。

若 object gate 通过，下一阶段先设计默认关闭 emitter 开关、结构测试和动态 event hit/miss counter；在 miss 比例未知前不直接把
151/308 samples 解释为 runtime 收益，也不先跑 SimTop 性能。
