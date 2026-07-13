# NO0475 Corrected runtime-frame closure plan

日期：2026-07-13

## 1. Objective

[NO0474](./NO0474_residual_state_slot_template_audit_gate_20260713.md) 关闭 source-template 路线后，全局最大未复核域为
scope-corrected `runtime_frame_only=562` samples/direct `8.419%`。本阶段只做 corrected-key closure，确认 NO0408/NO0412
历史 helper gate 能否逐 IP 复用，而不是按相近数量直接套结论。

## 2. Current helper split

| runtime helper | samples |
| --- | ---: |
| `grhsim_mux_u64` | 186 |
| empty/line-0 | 138 |
| `grhsim_or_words_full` | 110 |
| `grhsim_and_words_full` | 75 |
| `grhsim_udiv_u64` | 26 |
| all other named helpers | 27 |

named mux 与 full-width logic 分别连接 NO0412、NO0408；udiv 与其余单类本身低于 67。风险集中在 138 个 empty helper。

## 3. Key-level replay

以 `(batch_id, offset)` 把 current empty 138 连接 NO0411 的 147-row `unknown_sample_rows.tsv`，要求 138/138 唯一命中，
并按旧 resolution/helper/machine class 重算。NO0411 中未进入 current empty 桶的旧 rows 必须能在 corrected ownership 中解释，不能
静默丢失。

## 4. Decision gate

只有 corrected unresolved 或新的单一 helper class 仍至少 67 samples/direct `1%`，才重新做 basic-block audit；否则复用历史
负向 gate，关闭 runtime-frame-only 域。

本阶段不重新编译、运行仿真/perf 或修改 emitter。闭合后转向 exact side-effect body 或其他未审计全局域。
