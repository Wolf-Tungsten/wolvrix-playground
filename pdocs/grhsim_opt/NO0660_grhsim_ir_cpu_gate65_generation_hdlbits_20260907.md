# Gate65 helper generation and HDLBits gate

- Date: 2026-09-07
- Candidate: NO0659 helper-only repair, target_batch_count=0 as in gate63.
- Status: generation/roundtrip and full HDLBits passed; XS runtime unmeasured.

make py_install exited 0 using the project .venv and project-local temporary,
ccache and pip cache directories. Installed emitter SHA256:
e9f8b175cebc7fca14ac46955d12955712c4807a289f6b4480f3870e411f2698.
Schedule SHA256 remains
7f7f253903d2c7ffe6a79fc7f8f19cba5f353a5a80a00d107932ba5f1b53fd64.

Existing make xs_wolf_grhsim_ir loaded the same flat checkpoint and emitted
ptmp/xs_emit_make_gate65. Generation/fresh roundtrip exited 0 in 152975 ms.
ptmp/xs_ir_gate65.json is byte-identical to ptmp/xs_ir_gate63.json, including
mapping. Exactly 38 compute task sources plus the generated header differ;
driver, runtime, initializers, commit sources and Makefile remain identical.
Generated tracked call counts: arithmetic 43, shift 40, matching audit coverage.

Existing make run_all_hdlbits_grhsim_ir_tests exited 0: ordered DUT001-162,
162 pass records, artifacts ptmp/hdlbits-grhsim-ir-bzsu1p. Logs:
ptmp/grhsim_gate65_py_install.log, ptmp/grhsim_gate65_generation.log,
ptmp/grhsim_gate65_source_diff.log and ptmp/grhsim_gate65_hdlbits.log.

Gate63 and legacy executable fingerprints remain unchanged from NO0656.
Gate64's packing-only O3 build remains running. Gate65 has no XS binary or
measured speedup yet. A separate local-activity-word source change is under
test; it is NOT included in these gate65 artifacts or this HDLBits result.
