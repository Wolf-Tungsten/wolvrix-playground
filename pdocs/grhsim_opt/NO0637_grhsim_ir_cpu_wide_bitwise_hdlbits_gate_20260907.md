# Wide bitwise true-change HDLBits gate

- Date: 2026-09-07
- Candidate: [NO0635](./NO0635_grhsim_ir_cpu_wide_bitwise_activity_implementation_20260907.md).
- Generation: [NO0636](./NO0636_grhsim_ir_cpu_gate62_generation_20260907.md).

The existing root make run_all_hdlbits_grhsim_ir_tests target exited 0 using
the installed candidate and SKIP_PY_INSTALL=1. All 162 testbenches reported
passing. Log: ptmp/grhsim_gate62_hdlbits.log. Artifacts:
ptmp/hdlbits-grhsim-ir-Ajkt8b. Compiler caches and temporary files remained
under ptmp. This is a full HDLBits regression, not an XS performance test.

Final emitter SHA-256:
88a9605dc090737b48a27a9b8517c021f07376933f7df1592f8915c5b01ff5fb.
The preserved gate61 ordinary binary remains
314c2a9cdcd2050fc14a95a9135a123b9ca9c00ff992c41d205fe21a7c8b481c.
Root and wolvrix diff whitespace checks exit 0. All build/test/generation
sessions from this stage have terminated.

The gate62 generated model is ready for an independent O3 XS build through
make xs_wolf_grhsim_ir_build_emu. That build and candidate 1k/10k/50k runs
have not started. Keep gate59/gate60/gate61 references intact, compare serial
ordinary binaries before promotion, and retain the final legacy+5% criterion.
Arithmetic/shift true-change activation remains a separate implementation gap.
The overall multiclock/activity objective is still active and incomplete.
