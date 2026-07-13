# TNO0018 Event-pure word bypass development

记录日期：2026-07-13

来源范围：`NO0477..NO0494`，原始记录见 [NO0477](../grhsim_opt/NO0477_side_effect_event_first_object_probe_plan_20260713.md) 至 [NO0494](../grhsim_opt/NO0494_pure_event_compute_word_dynamic_profile_gate_20260713.md)。

状态：从失败的 per-condition/per-supernode guard 收敛到 pure-event whole active-word bypass；默认关闭的 emitter 与 profile 能力已实现并通过 synthetic gate。

## 1. 失败的细粒度 guard

将 exact event 移到 side-effect `&&` 最前，7 个 objects 的 text/instructions/memory 全部回退；debug 证明 data producer 已在 `if` 前执行，无法跳过 negedge work。

compute-supernode 审计随后识别：

```text
event-pure supernodes  1,611 / 63,241
producers              8,246
side effects          11,472
profile samples          308 / direct 4.614%
```

per-supernode outer guard 能正确越过 producer，但 aggregate text/jumps 小幅增加；mixed active-word mask filter 聚合到 355 groups 后仍使 6/6 objects 全面回退。这两种形态都停止。

## 2. Pure-event whole word

active-word 分类为：

```text
pure-event words         107
event/non-event mixed    246
multi-event mixed          2
```

只对同一 exact event 的完整 8-node pure word 建 wrapper。首个 else-zero 形态增加 jumps；将 restore 放入 event-hit wrapper、edge-false 直接越过完整 dispatch 后，代表 78 words 的 aggregate：

```text
text          -1,862 bytes
instructions  -379
memory forms  -239
jumps          -65
calls            0 delta
```

debug 证明 edge-false 在 underlying clear 后直接到下一 word，8 个 entry tests、payload 与 restore 全部被跳过。

## 3. Emitter implementation

默认关闭的 `pure_event_compute_word_bypass` 只接受：

- homogeneous complete compute word；
- 同一非 true exact event；
- transient producer + side-effect payload；
- 无 materialized/state/activation 写入；
- mixed/multi-event/once-only/commit/fullpass/full-word-consume 均拒绝。

default/explicit-zero source byte-identical，hit/miss synthetic harness 与 emitter/memory-fill 回归通过。

## 4. Dynamic profile support

独立默认关闭的 profile 复用 runtime-profile dump，按 batch 输出 eligible/hit/miss/total。profile-only 与 combined synthetic 均精确闭合：

```text
eligible=2 hit=4 miss=6 total=10
```

## 5. 阶段结论

event guard 只有提升到 homogeneous pure active-word 才同时减少 entry tests 与 payload，细粒度 guard 会增加 CFG。实现与 profile 已具备，下一步在 fresh SimTop 上闭合 107 words 的真实动态机会与 production codegen。

## 6. 规则审计与关键数据

记录类型：pure-event whole-word bypass 的候选发现与实现 gate。单一议题边界是“能否在不改变 event/activation 语义的前提下，于 edge-false 时跳过完整 active word”。本阶段只做到 object/synthetic gate，尚未运行 SimTop 候选性能。

| Stage | Coverage / object result | Decision |
| --- | --- | --- |
| event-pure supernode audit | `1,611/63,241` nodes，308/6,675 samples=`4.614%` | 过 1% |
| word aggregation | 355 groups/354 words；107 pure words | 进入 word probe |
| mixed-word mask | text/instr/memory/jumps=`+0.059/+0.071/+0.050/+0.298%` | 停止 |
| pure word, else-zero | text/instr/memory=`-834/-99/-107`，jumps `+8` | 停止 |
| pure word, restore-inside | text/instr/memory/jumps=`-1,862/-379/-239/-65` | 通过 |

最终代表 probe 覆盖 78 pure words、624 nodes、3,127 producers、92 profile samples；debug 证明 edge-false 越过 8 个 entry tests、payload 与 restore。Synthetic dynamic profile 精确闭合 `eligible=2, hit=4, miss=6, total=10`。这些都是实现/对象正确性数据，不含 guest cycles、host walltime 或 perf。来源见 [NO0480](../grhsim_opt/NO0480_event_pure_compute_supernode_audit_gate_20260713.md)、[NO0486](../grhsim_opt/NO0486_active_word_event_mask_object_probe_gate_20260713.md)、[NO0490](../grhsim_opt/NO0490_pure_event_word_restore_inside_probe_gate_20260713.md) 与 [NO0494](../grhsim_opt/NO0494_pure_event_compute_word_dynamic_profile_gate_20260713.md)。
