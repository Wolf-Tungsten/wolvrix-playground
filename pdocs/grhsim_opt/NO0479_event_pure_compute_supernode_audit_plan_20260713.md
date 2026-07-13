# NO0479 Event-pure compute supernode audit plan

日期：2026-07-13

## 1. Corrected hypothesis

[NO0478](./NO0478_side_effect_event_first_object_probe_gate_20260713.md) 证明只交换 side-effect `if` 内的 `&&` 顺序不能
跳过 data producer，因为 producer 已在 `if` 前执行。代表 supernode 23604 的结构是：

1. ordinary activity bit 命中后进入 compute supernode；
2. 先从 bool slots 计算 assertion condition locals；
3. 再由多个 SystemTask/DPIC 各自检查同一个 clock posedge。

该 supernode 的 ordinary activation 来自 data-change propagation；非 posedge 激活仍执行全部 condition producer。same-FIR GSim
中对应 assertion producer 与 `gAssert` 位于同一个 `oldFlag` block，没有逐 side-effect edge guard。这不证明 GSim 的 event
调度细节相同，但确认 GrhSIM 的重复 exact-event shape 不是共同 C++ 结构。

本阶段改为审计能否生成：

```cpp
if (event_edge_slots_[0] == grhsim_event_edge_kind::posedge) {
    // pure transient condition producers
    // SystemTask / DPIC in original schedule order
}
```

outer guard 必须位于 producer 之前；supernode active bit 仍在 guard 外正常消费。

## 2. Historical boundary

[NO0034](./NO0034_sink_activation_event_delta_plan_20260427.md) 收窄的是 register/memory commit sink activation，并明确记录
SystemTask/DPIC 已移出 sink。本阶段只处理 compute-side event-only supernode，不重复 commit 优化。

[NO0250](./NO0250_simtop_event_fullpass_order_fix_20260710.md) 规定 event eval 必须保持 compute -> commit -> clear edge ->
post-commit compute 的顺序。本阶段不改变 round、edge clear 或 commit 顺序，只在 exact event 为 false 时跳过无外部结果的 compute
payload。

## 3. Full static audit

扫描 NO0357 的 66 个 `eval_compute_batch_*` generated sources，以 supernode 为单位记录：

- SystemTask/DPIC 数量及规范化 `(event_slot, edge_kind)` keys；
- local producer declarations 与 source span；
- 是否写 `value_*_slots_`、state/memory、activation flags 或 change accumulators；
- 是否包含非 side-effect call、无 explicit event side effect 或 mixed event keys；
- NO0448 的 5,590 compute profile rows 中落入该 supernode 的 samples。

`event_pure` 必须同时满足：

1. 至少一个 explicit-event SystemTask/DPIC，且所有 side effects 共享一个 exact edge key；
2. guard 内候选 payload 只产生 lexical locals 或执行这些 side effects；
3. 不写 materialized value/state/memory，不传播 activation/change，不产生其他可见 call；
4. active-word consume/restore 结构不纳入 guard，不改变 fixed-point scheduling。

模糊块一律归入 rejection reason，不按 assertion 字符串或相邻注释猜测 purity。

## 4. Gate

若 event-pure supernodes 覆盖少于 67 个 direct instruction samples（direct `1%`），只记录结构结论并停止。

若过门槛，再独立规划 generated-copy object probe：只给 representative hot batches 的完整 event-pure payload 增加 outer exact-event
guard，保留内部 guards 交给 `-O3` 消除。必须证明：

- baseline rebuild `.text` 与 production 一致，production SHA 不变；
- candidate whole-object instructions/memory/jumps 不增加；
- debug machine code 在 edge-false transfer 之后不再执行 producer slot loads/logic；
- mixed/non-event supernodes byte-exact 未改。

object gate 通过后才考虑默认关闭 emitter 开关和 SimTop 功能回归，不直接运行性能测试。
