# NO0445 Assign-boundary forwarding audit plan

日期：2026-07-13

## 1. Objective

[NO0444](./NO0444_remaining_register_read_machine_audit_gate_20260713.md) 已排除 remaining register-read：明确独立 read
slot copy 只有 direct `0.225%`。latest direct operation profile 中，下一个尚未按 current machine/source 收口、且理论上界超过
1% 的 operation kind 是 `kAssign`：

```text
scheduled static kAssign comments    73,644
profile samples                         395
unique sampled operations               374
direct total share                  5.9176%
compute share                       7.0662%
```

这里的 395 不能整体解释为 copy。按 NO0403 既有机器归因，它们拆为：

| Machine mechanism | Samples | Direct total share |
| --- | ---: | ---: |
| `payload_compute` | 140 | 2.097% |
| `changed_compare` | 67 | 1.004% |
| `activation_propagation` | 52 | 0.779% |
| `slot_writeback` | 46 | 0.689% |
| `entry_active_scan` | 38 | 0.569% |
| `operand_or_state_read` | 28 | 0.419% |
| `runtime_helper` | 12 | 0.180% |
| `changed_accumulate` | 11 | 0.165% |
| other/unresolved | 1 | 0.015% |

目标是判断 remaining `kAssign` 是否形成了 GrhSIM 独有的“operand value -> declared result slot -> changed/activation ->
consumer”透传边界，并量化可安全把 result alias/forward 到 operand 的真实机器上界。

## 2. Existing optimization boundary

当前 `redundant-elim` 已消除同宽、同 signedness、临时 source、single-user 的普通 assign，并能把满足条件的内部 source
直接重绑到 output result。剩余 sampled blocks 多为声明值或跨 schedule 边界，例如：

```cpp
const bool next_value = grhsim_value_storage_ref<std::uint8_t>(...);
const bool changed = (value_bool_slots_[result] != next_value);
supernode_active_curr_[...] |= ...changed...;
value_bool_slots_[result] = next_value;
```

也有无 change detect 的 slot write、wide assign 和 event/clock assign。后两类可能需要独立历史值，不能把“语义上是
assign”直接等同于“结果 storage 可删”。本方向也不同于
[NO0227](./NO0227_words_assign_fusion_negative_ab_20260709.md) 的 wide helper 字符串级 producer/assign fusion；本轮审计的
对象是 schedule/value activation 边界。

## 3. Phase A: existing-artifact machine/source audit

本阶段不重编、不重跑仿真或 perf。逐个解析 NO0357 的 73,644 个 generated `kAssign` blocks，并把 395 个既有 samples
按 `_op_N` 精确连接。要求 395/395 sample rows、374/374 unique operations 全连接，recorded line 必须落在对应 block；
否则停止。

每个 block 输出并互斥分类：

- result storage：scalar slot、wide slot、packed-lane special path；
- operand shape：direct scalar slot、direct wide slot、state ref、same-supernode typed local、fused expression；
- emitted effects：next-value payload、changed compare、deferred accumulate、activation、event edge、slot writeback；
- sampled instruction ownership：payload/copy、compare、write、activation/framework 或 fused/ambiguous；
- width、batch、supernode、result family 和 sample multiplicity。

只有“operand 已有稳定 storage/ref，result 又独立 compare/store”的 block 才计入 forwarding 上界。fused complex RHS、
event edge、clock assign、wide helper 和 line-attribution framework 不计为可删 copy。

## 4. Phase B: structural eligibility diagnostic

若 Phase A 的同一 source/effect class 达到 67 samples/direct 1%，再新增默认关闭、只输出 TSV 的 emitter diagnostic，连接：

- operand/result type、width、signedness 和 materialization；
- producer/result owner supernodes、same-supernode/unscheduled users 和完整 boundary fanout；
- top-level input/output/inout、event sample、waveform、packed-lane 与其他 protected-value 判定；
- source change predicate 能否 all-or-none 直接激活 result 的全部 consumer；
- result 是否还承担独立 old-value、edge classification 或 public storage 语义。

诊断开关必须通过 unset/0/1 generated-code identity gate。若 Phase A 没有单类达到 67 samples，则不修改 emitter，直接停止
本方向。

## 5. GSim and machine gates

对 sampled 数最高的 2-3 个 result families，在 same-FIR GSim source 中确认对应值是直接 operand alias/typed local，还是同样
保留 member、`$old`、changed compare 和 `activeFlags`。只把 GSim 没有的中间结果层计为差异。

进入实现还需同时满足：

1. 同一可证明安全的 structural class 至少 67 samples/direct 1%；
2. 其中独立 compare/store/activation 指令占主要部分，而非真实 RHS payload；
3. source change 能完整替代 result change，且初始化 full-pass、跨 batch/cycle activation 和 fixed-point 语义不变；
4. production-identical O3 object probe 的 aggregate instructions/bytes 明确下降，不能只减少 C++ 行数。

任何一项失败即停止，不跑低上界 runtime。通过后才另起实现、功能和受控 SimTop A/B 文档。

## 6. Planned artifacts

```text
build/logs/xs_perf/no0445/analyze_assign_boundaries.py
build/logs/xs_perf/no0445/assign_sample_rows.tsv
build/logs/xs_perf/no0445/{source_shape,effect,machine_role,result_family}_summary.tsv
build/logs/xs_perf/no0445/analysis_summary.txt
build/logs/xs_perf/no0445/gsim_assign_crosscheck.txt
```
