# Gate61 generation and source identity

- Date: 2026-09-07
- Implementation: [NO0627](./NO0627_grhsim_ir_cpu_history_scan_implementation_20260907.md).

Project-local make py_install completed successfully. Independent generation,
fresh-session load and stable roundtrip through make xs_wolf_grhsim_ir exited
0 in 94386 ms. Logs: ptmp/grhsim_gate61_py_install.log and
ptmp/grhsim_gate61_generation.log. The command follows NO0620 with gate61
output/build/log identifiers and the same flat GRH checkpoint, Python,
target_batch_count=0, explicit empty XS_WOLF_DEPS and ptmp temporary directory.

cmp of ptmp/xs_ir_gate60.json and ptmp/xs_ir_gate61.json exited 0: complete IR
and CPU mapping are byte-identical. Fresh roundtrip output is
ptmp/xs_ir_gate61_roundtrip.json; generated sources are ptmp/xs_emit_make_gate61.

The generated-directory comparison excludes old objects/archive and the unused
gate60 probe header. Exactly 95 task sources differ, all commit tasks (IDs in
5570..6081). Header, driver, runtime, initializers, compute tasks and generated
Makefile remain unchanged. Log: ptmp/grhsim_gate61_source_diff.log.

Scan markers describe 95 event groups, 184371 history members and 2078 exact
contiguous ranges. Task 5602 has 4096 histories in 172 ranges, matching the
earlier source audit. These are grouped scan inputs, not dynamic hit counts or
a claimed runtime speedup. Original sampling-only and full-body branches remain.

The independent existing xs_wolf_grhsim_ir_build_emu target is now building all
O3 model objects/harness with VM_BUILD_JOBS=8. Log:
ptmp/grhsim_gate61_full_o3_build.log. HDLBits remains in progress, log
ptmp/grhsim_gate61_hdlbits.log, artifacts ptmp/hdlbits-grhsim-ir-IajCyN.
Wait for both sessions to finish before serial ordinary-binary benchmarks.
Gate59/gate60 references are preserved and the full goal remains open.
