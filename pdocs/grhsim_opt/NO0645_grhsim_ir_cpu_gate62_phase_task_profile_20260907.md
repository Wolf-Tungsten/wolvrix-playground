# Gate62 phase/task profile and restoration

- Date: 2026-09-07
- Baseline: [NO0644](./NO0644_grhsim_ir_cpu_gate62_50k_serial_performance_20260907.md).

Only the generated driver was temporarily instrumented. It retained the prior
phase/pending counters and additionally timed each task call, reporting the top
40 tasks for each clock level. Macro wrappers were defined after the model
header, so task implementations/declarations and dispatch conditions were not
modified. The existing Makefile rebuilt one driver object and linked, then
ran 1k without concurrent workloads. Both commands exited 0.

| Metric | Result |
| --- | ---: |
| Evals / rounds | 2102 / 4278 |
| Compute / commit / publish | 11158.037 / 7532.509 / 923.530 ms |
| Host including probes | 19630 ms |
| Pending / compared bytes | 80605800 / 2108541922 |
| Changed / copied bytes | 38015872 / 835476988 |
| Entries over 64 bytes / their bytes | 2943384 / 1859682153 |
| Direct E helper calls / targets | 792762 / 792762 |

| Clock | Rounds | Compute ms | Commit ms | Publish ms |
| --- | ---: | ---: | ---: | ---: |
| 0 | 2102 | 4897.423 | 474.711 | 419.838 |
| 1 | 2176 | 6260.614 | 7057.798 | 503.692 |

Task-body sums were compute 4660.135/6010.750 ms and commit
458.183/7034.678 ms at clock 0/1. Top high-clock commit tasks include 5636
(193.794 ms), 5637 (182.872 ms), 5640 (174.724 ms), 5624 (172.410 ms), and
5614 (171.756 ms), each called 2103 times. Top low-clock compute tasks include
5534 (37.619 ms), 5547 (35.913 ms), 5536 (35.253 ms) and 5548 (34.300 ms),
each called 2102 times. The top-40 high-clock list is dominated by commit;
this does not mean unlisted compute tasks cost zero.

All pending/byte/direct counters and total rounds match the earlier gate61
profile. Terminal remains 3 instructions, cycleCnt=996, guest=1001,
commit PC=0x10000008, trap PC=0, NEMU enabled/no mismatch. Per-task clocks add
instrumentation overhead; these numbers are attribution, not ordinary-binary
performance evidence or a directly comparable phase-only benchmark.

The hot task 5636 has sparse clock/reset history pairs and does not qualify
for the previous dense edge scan. Its original sampling-only branch still
stages individual histories, including stable values. This motivates examining
a whole-task no-op predicate, not skipping histories based on level alone.

All driver probes were removed via apply_patch. The driver matches
ptmp/grhsim_gate62_normal_driver.cpp, the Makefile restoration build exited 0,
and cmp against ptmp/grhsim_gate62_50k_verified_emu exited 0. Binary SHA-256:
0b29bcee26710ee4de444743979228ac9eb761eae579f45f21fb24346f177e1a.
The unused ptmp/xs_emit_make_gate62/gate62_profile.hpp preserves the probe.
Logs: ptmp/grhsim_gate62_profile_build.log, ptmp/grhsim_gate62_profile_1000.log,
ptmp/grhsim_gate62_profile_restore.log. All sessions are terminal.
