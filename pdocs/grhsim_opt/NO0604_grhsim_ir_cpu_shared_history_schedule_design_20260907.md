# Shared-history schedule counterexample and design

- Date: 2026-09-07
- Status: counterexample reproduced; implementation verification pending.
- Scope: CPU schedule correctness; DPI phase/events/ingest unchanged.

## Evidence

Before implementing the inactive-edge commit optimization, the history fixture
was extended with two posedge registers QA/QB sharing one history H. Commit order
is A then B. An independent G scoreboard reads the same old H for both guards,
updates QA/QB, and publishes H=B, iterating until all three are unchanged.

The unchanged gate58 implementation failed at sample 2:

1. A=1, B=0, H initially 0, data=42: A captures 42; final H=0.
2. A=1, B=0, data=77: the guard for A is still true, but its domain is not armed.

Command and failure log:

```sh
make --no-print-directory test_grhsim_cpu_emit WOLF_ENV_SOURCED=1 > ptmp/grhsim_cpu_shared_history_baseline_test.log 2>&1
```

The command exited 2; CTest reported the history fixture failure at sample 2.
This is a scheduler counterexample, not evidence against direct scalar commits.
No new inactive-edge emitter path had been implemented when it failed.

## Correction

Use the existing writer analysis in cpu.st.build-schedule. A history can support
change-driven domain gating only when every writer samples the same ValueId.
For distinct samples or a normal state writer, mark every consuming commit
domain's tasks AlwaysScanCommit. Preserve tree domains, task ordering, event
guards, history staging, next-arm and projection semantics. Same-value sharing
remains gated. Schedule verification recomputes this decision; JSON contains
the execution choice, with no session-only or emitter-only scheduling rule.

Private history batching remains valid inside such edge-domain functions:
non-private histories stay in their original staging order, and private batches
remain at the function end. General domains and compute calls do not participate.

The proposed sampling-only performance path is deferred until this correction
has passed schedule, emitted-runtime and full-model compatibility checks. Legacy
commit dispatch was inspected at grhsim_cpp.cpp::analyzeCommitSupernodeEvent;
its event aggregation does not establish the shared-history invariant above.

## Verification Plan

- Independent G scoreboard: asynchronous A/B toggles, repeated A=1/B=0 with
  changed data, repeated identical eval, four init cycles, exposed QA/QB/H.
- Keep private batches, same-clock sharing, observed history, distinct initial
  histories and ordinary disabled history writer checks.
- Schedule tests: same-value sharing stays gated, different-clock sharing and
  ordinary history writers fall back, corrupt execution rejected, JSON roundtrip.
- Use Makefile targets only. A dedicated test_grhsim_cpu_schedule target was
  added because the repository had no schedule-suite Makefile entry.
- Check the existing XiangShan mapping with the new verifier before claiming
  that the correction leaves its generated code or performance unchanged.

Gate58's verified 10k and gate57's verified 50k remain historical evidence only;
the full goal, including the 50k performance requirement, is not complete.
