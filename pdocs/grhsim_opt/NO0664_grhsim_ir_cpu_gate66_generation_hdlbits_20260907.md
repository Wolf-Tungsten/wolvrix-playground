# Gate66 combined repair generation and HDLBits

- Date: 2026-09-07
- Candidate: NO0659 helpers plus NO0661 local activity/mask coalescing.
- Status: generation/roundtrip and full HDLBits passed; independent O3 running.

Project-local make py_install exited 0. Emitter SHA256:
a37ad00df6259a12485c908394150e238025dcd48e73c2f68012654b8772156f.
Schedule SHA256 is unchanged:
7f7f253903d2c7ffe6a79fc7f8f19cba5f353a5a80a00d107932ba5f1b53fd64.
make test_grhsim_cpu_schedule exited 0 after the local-word repair.

Existing make xs_wolf_grhsim_ir used the same flat checkpoint and explicit
target_batch_count=0. Generation/fresh roundtrip exited 0 in 208053 ms;
ptmp/xs_ir_gate66.json is byte-identical to gate63, including mapping.
Model directory: ptmp/xs_emit_make_gate66. Versus helper-only gate65, exactly
5569 compute task sources, driver and header differ; commit, initialization,
shared runtime and generated Makefile remain identical.

Static compute activation statements: 155414 local writes and 1701385 global
writes, versus gate63's 2510273 global writes. The total 1856799 agrees with
the earlier word-mask coalescing census. These are source counts, not dynamic
instruction counts or evidence of speedup.

make run_all_hdlbits_grhsim_ir_tests exited 0 with ordered DUT001-162 and
162 pass records; artifacts ptmp/hdlbits-grhsim-ir-8tutO3. Logs:
ptmp/grhsim_gate66_py_install.log, ptmp/grhsim_local_activity_schedule_tests.log,
ptmp/grhsim_gate66_generation.log, ptmp/grhsim_gate66_source_diff.log,
ptmp/grhsim_gate66_hdlbits.log.

Existing make xs_wolf_grhsim_ir_build_emu started an independent O3 build
with XS_GRHSIM_IR_BUILD=ptmp/xs_gate66, VM_BUILD_JOBS=8 and
GRHSIM_MODEL_CXXFLAGS='-std=c++20 -O3'. Original session 5934 remains running;
log ptmp/grhsim_gate66_full_o3_build.log. Gate64 packing-only session 95253
also remains running. No simulation is running concurrently. Await original
sessions, then compare ordinary binaries serially; do not restart on an
observation timeout. Gate63/legacy and both intermediate models remain preserved.
