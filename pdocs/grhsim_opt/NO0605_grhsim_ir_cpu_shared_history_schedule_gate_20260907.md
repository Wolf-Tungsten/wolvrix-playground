# Shared-history schedule correction gate

- Date: 2026-09-07
- Status: schedule and CPU runtime regression passed; full XiangShan checkpoint
  accepted by the updated verifier.
- Design and original failure: [NO0604](./NO0604_grhsim_ir_cpu_shared_history_schedule_design_20260907.md).

## Implementation

cpu_schedule.cpp uses its existing writer graph to find histories whose writers
do not all sample the same ValueId. All tasks in their consuming commit domains
use AlwaysScanCommit, preserving domain/function/order metadata. No task, IR op,
history, event, activation-table format, or new runtime condition is introduced.
The existing canonical schedule verifier rejects a corrupted reversion to gated
execution. Same-event shared histories remain eligible for domain gating.

cpu_emit.cpp retains private-history batching for edge-domain tasks that now
always scan. Eligibility and staging semantics are unchanged; shared/observed/
ordinary-written histories are still individually staged in the original order.
DPI remains compute-side with optional events and actual void calls retained.

## Verification

```sh
make --no-print-directory test_grhsim_cpu_schedule test_grhsim_cpu_emit WOLF_ENV_SOURCED=1 > ptmp/grhsim_cpu_shared_history_fix_test.log 2>&1
make --no-print-directory audit_grhsim_cpu_emit WOLF_ENV_SOURCED=1 GRHSIM_AUDIT_MODEL=ptmp/xs_ir_gate58.json > ptmp/grhsim_cpu_shared_history_xs_audit.log 2>&1
```

Both commands exited 0. Schedule suite: 0.01 s. Full emitted CPU suite: 28.01 s.
The runtime details were preserved as ptmp/grhsim_cpu_shared_history_fix_details.log.

| Coverage | Result |
| --- | --- |
| Same-event sharing / distinct-event sharing / ordinary history writer | 0 / 2 / 1 edge domains fall back, respectively |
| Corrupt gated conflicting-history mapping | Rejected; JSON roundtrip passed |
| Independent shared-history G scoreboard | 4636 evals, four init cycles passed |
| Private history batching in fallback edge domains | 18 candidates, 6 private rejections, 12 states in 2 batches |
| Private non-E commits and real void DPI | 4612 evals, 4612 calls, four init cycles passed |
| CPU chain / Verilator | 4136 samples passed |
| Scalar / wide / wide-state CPU versus Verilator | 4196 / 3072 / 2048 samples passed |
| CDC CPU / Verilator / scoreboard | 10756 samples, 1182 simultaneous edges, 20 asynchronous resets passed |
| Dual RAM CPU / Verilator / scoreboard | 9731 samples, 293 simultaneous edges, 424 changed writes, 15 asynchronous resets passed |

The audit uses loadGrhSimModel, whose JSON reader calls verifyGrhSimModel and
therefore the updated canonical schedule verifier. Acceptance of the existing
gate58 checkpoint proves its stored schedule still equals the newly computed
schedule. No full-model compile or simulation was started for this check; this
is not a new 10k/50k runtime result or performance measurement.

Whitespace checks passed for the root and wolvrix worktrees. No commit was made.
All command logs and temporary outputs remained inside the project.

## Remaining Work

The sampling-only inactive-edge optimization is still unimplemented. Continue
performance work from the known gate58 baseline, preserving history writes and
operation order. Full HDLBits has not been rerun for this schedule correction;
the earlier 162/162 gate belongs to gate58 before this correction. Current-source
50k and the plan's legacy +5% performance requirement remain unproven.
