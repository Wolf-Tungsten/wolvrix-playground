# Wide bitwise true-change activation implementation

- Date: 2026-09-07
- Design: [NO0634](./NO0634_grhsim_ir_cpu_wide_bitwise_activity_design_20260907.md).

## Changes

The CPU emitter now emits cpu_bitwise_words_changed for tracked wide
and/or/xor/not results. Each word is computed, normalized, compared and stored
in place; the scalar changed result guards the existing activation code.
Local results still use the original pointer helpers. No shared legacy runtime,
model, schedule, DPI, event, history or publication changes were made.
The helper name is reserved against model-port shadowing, with a rejection test.

Files: wolvrix/lib/grhsim/backend/cpu_emit.cpp,
wolvrix/tests/grhsim/test_cpu_emit.cpp,
wolvrix/tests/grhsim/data/cpu_bitwise.mk and cpu_bitwise_main.cpp,
wolvrix/docs/grhsim_ir/backends/cpu.md.

## Verification

Both existing root Makefile targets test_grhsim_cpu_schedule and
test_grhsim_cpu_emit exited 0. The initial complete CPU suite took 37.30s;
the final suite after name protection took 37.47s.

For each of tracked and local generated models, the new ASan/UBSan test passed:

- 1792 helper cases covering all four operations, seven widths from 65 to 4097,
  unequal/scalar input lengths, arbitrary input padding, unchanged outputs,
  first/final-word changes, dirty old padding, and exact lhs/rhs output aliases.
- Output compared to the unchanged legacy pointer helpers; changed compared to
  an independent pre-call output snapshot versus expected output. Snapshots
  exist only in the test, not generated runtime code.
- 8192 model evals / four resets, including repeated identical inputs, mixed
  scalar/wide operands and an independent per-word output scoreboard.
- Structural checks require exactly four guarded helper calls in the tracked
  variant and zero in the local variant; local sources retain all four legacy
  helper calls. The fixtures explicitly control compute supernode size.

Logs: ptmp/grhsim_gate62_cpu_tests.log,
ptmp/grhsim_gate62_cpu_tests_initial_detail.log,
ptmp/grhsim_gate62_cpu_tests_final.log,
ptmp/grhsim_gate62_cpu_tests_final_detail.log.

Emitter SHA-256:
88a9605dc090737b48a27a9b8517c021f07376933f7df1592f8915c5b01ff5fb.
Scheduler remains 7f7f253903d2c7ffe6a79fc7f8f19cba5f1b53fd64a00d107932ba5f1b53fd64.

## Remaining gates

Project-local make py_install is running before independent gate62 generation
and HDLBits. There is no gate62 XS build, runtime or performance result yet.
Gate61 remains the ordinary reference. Arithmetic/shift true-change paths and
final candidate 50k / legacy+5% remain incomplete.

## Erratum 2026-09-07

The scheduler fingerprint above contains a transcription error. The measured
SHA-256 is 7f7f253903d2c7ffe6a79fc7f8f19cba5f353a5a80a00d107932ba5f1b53fd64,
unchanged from gate61. Project-local make py_install has since exited 0;
independent XS generation and HDLBits are now running.
