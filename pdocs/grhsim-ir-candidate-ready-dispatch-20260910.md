# GrhSIM-IR Candidate: Ready-Bit Dispatcher

- Date: 2026-09-10
- Status: REJECTED / FUNCTIONALLY VALID, PERFORMANCE REGRESSION
- Validated source baseline: GrhSIM `c3dfad0cc19e29943b65d815ae180fdbd42f1bee`

## Hypothesis and change

The activity-guard evaluator still visits the scheduled task list on every
convergence round. This candidate indexed runtime activation bytes to task IDs,
stored pending tasks in schedule-ordered bitsets, and dispatched each ready task
through a generated member-function table. Same-round back-edges were deferred
to the next round so the schedule order remained deterministic.

The focused emitter suite passed, the model generation completed a stable JSON
round trip, and the multi-job emulator build completed. The candidate source was
then discarded after the full run showed a large regression; the repository
source remains the activity-guard baseline.

## Validation and result

The required smoke run used `XS_SIM_MAX_CYCLE=1000`, one emulator thread, CPU 2,
NEMU difftest, and waveform/trace output disabled. It exited 0 at the intentional
cycle limit without a mismatch. The full run used the same fixed XiangShan
revision, CoreMark image, top, CPU binding, and trace settings with a 50,000-cycle
limit. It exited 0 and matched the activity-guard architectural checkpoint:

| Run | Simulation (s) | Instructions | `cycleCnt` | Terminal PC |
|---|---:|---:|---:|---|
| full | 737.862 | 73,580 | 49,996 | `0x80001312` |

The result is functionally valid, but it is approximately 2.59x slower than the
activity-guard mean of 284.699 s. No second full run was started because the
single valid measurement already rejected the performance hypothesis.

## Analysis and decision

The generated dispatch loop rescans all ready-bit words from word zero for every
task and invokes task bodies through a member-function pointer. The scan adds
work proportional to the number of dispatched tasks, while the indirect call
prevents the direct-call inlining and prediction opportunities used by the
activity-guard evaluator. These costs explain the observed regression.

Reject this candidate. Its architectural result is useful as a correctness
check, but its timing is not performance evidence for the approximately 40 s
goal. The current best source remains the committed activity-guard candidate.
