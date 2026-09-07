# Gate61 phase profile and restoration

- Date: 2026-09-07
- Baseline: [NO0632](./NO0632_grhsim_ir_cpu_gate61_10k_functional_gate_20260907.md).

The generated driver alone was instrumented with the phase boundaries and
pending counters from [NO0625](./NO0625_grhsim_ir_cpu_gate60_phase_profile_20260907.md).
The existing Makefile build and run targets both exited 0, without concurrent
builds or simulations during the 1k measurement.

| Metric | Gate61 |
| --- | ---: |
| Evals / rounds | 2102 / 4278 |
| Compute / commit / publish | 10355.885 / 7313.079 / 890.905 ms |
| Host including probe | 18575 ms |
| Pending / compared bytes | 80605800 / 2108541922 |
| Changed / copied bytes | 38015872 / 835476988 |
| Entries over 64 bytes / their bytes | 2943384 / 1859682153 |
| Direct E helper calls / targets | 792762 / 792762 |

| Clock | Rounds | Compute ms | Commit ms | Publish ms |
| --- | ---: | ---: | ---: | ---: |
| 0 | 2102 | 4495.767 | 445.331 | 402.329 |
| 1 | 2176 | 5860.119 | 6867.748 | 488.575 |

The 1k terminal remains 3 instructions, cycleCnt=996, guest=1001,
commit PC=0x10000008, trap PC=0, with NEMU enabled and no mismatch.
All counters and round counts match gate60. Commit cost decreased from
9761.305 ms, predominantly at clock high. Compute now exceeds commit cost;
these instrumented timings are not ordinary-binary 50k performance evidence.

Probes were removed with apply_patch. The driver matches
ptmp/grhsim_gate61_normal_driver.cpp. The restoration Makefile build exited 0;
cmp against ptmp/grhsim_gate61_10k_verified_emu exited 0. Binary SHA-256 remains
314c2a9cdcd2050fc14a95a9135a123b9ca9c00ff992c41d205fe21a7c8b481c.
The unused ptmp/xs_emit_make_gate61/gate61_profile.hpp records the probe.

Logs: ptmp/grhsim_gate61_profile_build.log,
ptmp/grhsim_gate61_profile_1000.log, ptmp/grhsim_gate61_profile_restore.log.
No production code changed during this measurement. All three sessions ended.
