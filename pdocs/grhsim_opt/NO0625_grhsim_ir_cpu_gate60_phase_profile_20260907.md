# Gate60 phase profile and restoration

- Date: 2026-09-07
- Baseline: [NO0624](./NO0624_grhsim_ir_cpu_gate60_10k_functional_gate_20260907.md).

Only the generated driver was temporarily instrumented, with the same phase
boundaries and pending counters as NO0617. New per-clock round counts were also
collected. The existing Makefile rebuilt one driver object and linked, then ran
1k without concurrent builds/simulations. Both commands exited 0.

| Metric | Gate60 |
| --- | ---: |
| Evals / rounds | 2102 / 4278 |
| Compute | 10831.274 ms |
| Commit | 9761.305 ms |
| Publish | 908.257 ms |
| Host including probe | 21517 ms |
| Pending / compared bytes | 80605800 / 2108541922 |
| Changed / copied bytes | 38015872 / 835476988 |
| Entries over 64 bytes / their bytes | 2943384 / 1859682153 |
| Direct E helper calls / targets | 792762 / 792762 |

| Clock | Rounds | Compute ms | Commit ms | Publish ms |
| --- | ---: | ---: | ---: | ---: |
| 0 | 2102 | 4840.526 | 475.154 | 410.234 |
| 1 | 2176 | 5990.748 | 9286.151 | 498.023 |

The functional terminal is unchanged: 3 instructions, cycleCnt=996, guest=1001,
commit PC=0x10000008, trap PC=0, no NEMU mismatch. Pending/byte counts and total
rounds exactly match gate59's phase probe. Compute is reduced from its prior
15423.304 ms; commit remains a large high-clock cost. These are instrumented
phase results, not a new ordinary-binary 50k performance gate.

Logs: ptmp/grhsim_gate60_profile_build.log,
ptmp/grhsim_gate60_profile_1000.log and ptmp/grhsim_gate60_profile_restore.log.
All probes were removed by apply_patch, the driver matches its normal backup,
and the existing Makefile restoration build exited 0. cmp of the restored
executable against ptmp/grhsim_gate60_10k_verified_emu exited 0; SHA-256 remains
49d364aae00ebff82d92b1ed348dde26249b2a2dc25c8b98696e46619d5f0f2a.
The unused probe header remains in ptmp for reproducibility. All sessions are
terminal and no production implementation changed during profiling.
