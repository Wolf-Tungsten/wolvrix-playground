# Gate59 phase profile

- Date: 2026-09-07
- Precondition: [NO0616](./NO0616_grhsim_ir_cpu_gate59_50k_serial_performance_20260907.md).
- Status: fresh phase measurement completed; task-level follow-up and normal
  binary restoration pending at this record.

## Probe

Only ptmp/xs_emit_make_gate59/grhsim_SimTop.cpp was instrumented. Public model
header, tasks, IR, mapping, runtime helpers and DPI stayed unchanged. The probe
is ptmp/xs_emit_make_gate59/gate59_profile.hpp. It follows NO0596's steady-clock
boundaries: compute includes round seeds, commit ends before cpu_publish, and
publish includes its entry/byte counters. Eval entry setup, arm rollover and
output refresh are outside these three stage timers.

The actual 50k executable was preserved as ptmp/grhsim_gate59_50k_verified_emu.
Before instrumentation, the gate59 driver matched gate58 byte-for-byte. The
existing make xs_wolf_grhsim_ir_build_emu target rebuilt one driver object and
linked; make run_xs_wolf_grhsim_ir_emu ran the same 1k configuration. Both exited
0. Logs: ptmp/grhsim_gate59_profile_build.log and
ptmp/grhsim_gate59_profile_1000.log.

## Results

| Metric | Result |
| --- | ---: |
| Evals / rounds | 2102 / 4278 |
| Compute | 15423.304 ms (58.36%) |
| Commit | 10047.332 ms (38.02%) |
| Publish | 957.586 ms (3.62%) |
| Pending entries | 80605800 |
| Compared bytes | 2108541922 |
| Changed pending entries / copied bytes | 38015872 / 835476988 |
| Entries over 64 bytes / their compared bytes | 2943384 / 1859682153 |
| Direct-change helper calls / targets | 792762 / 792762 |
| Host time including probe | 26445 ms |

| Input clock | Compute ms | Commit ms | Publish ms |
| --- | ---: | ---: | ---: |
| 0 | 7087.367 | 520.795 | 431.821 |
| 1 | 8335.936 | 9526.537 | 525.764 |

Final state remains 3 instructions, cycleCnt=996, guest=1001, sampled commit
PC=0x10000008, trap PC=0; Difftest enabled with no mismatch. The probe timing is
not a replacement for the normal-binary 50k measurement.

## Interpretation

Compute is now the largest measured component. Commit remains substantial and
is concentrated in high-clock evals; the low-clock sampling-only path accounts
for only 5.18% of commit time. Evals/rounds match the prior gate57 profile, so the
observed optimization did not reduce the number of G applications.

Pending counts are lower than gate57, but history batching and direct state
writes alter the meaning of those counts; they are not logical state-change
counts. The direct helper counter includes only calls emitted for E states, not
all direct writes. Large pending entries include history batches, not just
memory objects. Publish is not the primary remaining measured cost.

Next, instrument task call sites in the same driver to locate the expensive
functions without changing task bodies. Account for per-call timer overhead;
do not infer a specific wide helper or fanout bottleneck solely from the phase
totals. All probes must be removed and the normal binary rebuilt before moving
to implementation or another ordinary benchmark.
