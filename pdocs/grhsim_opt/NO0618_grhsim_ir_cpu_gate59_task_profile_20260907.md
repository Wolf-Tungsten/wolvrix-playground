# Gate59 task profile and restored baseline

- Date: 2026-09-07
- Precondition: [NO0617](./NO0617_grhsim_ir_cpu_gate59_phase_profile_20260907.md).

## Evidence

The driver-only task-call probe completed the 1k Makefile run: 3 instructions,
cycleCnt=996, guest=1001, no NEMU mismatch, host 27432 ms. Logs are
ptmp/grhsim_gate59_task_profile_build.log and
ptmp/grhsim_gate59_task_profile_1000.log. Per-call timers add overhead; these
numbers rank work and are not ordinary-binary performance measurements.

| Phase | Task time ms | Calls | Top 24 time ms |
| --- | ---: | ---: | ---: |
| Compute | 15935.722 | 23824182 | 4428.130 |
| Commit | 10023.501 | 888029 | 4532.879 |

Top compute tasks are 5564/5565/5566 (353.620/337.158/325.385 ms), each called
4278 times. Task 5527 takes 184.541 ms and contains 512 string-constant
assignments, including assertion filenames/messages constructed before the
actual call guards. Some constants in the other top tasks are much longer.
Actual formatting and DPI/system calls remain guarded; this is not evidence
that those calls execute unconditionally or that wide helpers dominate.

Legacy grhsim_cpp.cpp uses staticConstStringExpr and valueRef to reference
constant string literals without mutable value storage. The new CPU emitter
instead creates per-invocation string objects and assigns literals to them.
This is the next independently testable candidate, not a proven explanation
of the entire 8.85x performance gap.

## Restoration

All phase/task probes were removed from the generated driver. The normal
driver matches gate58 byte-for-byte. The existing Makefile build completed;
log: ptmp/grhsim_gate59_profile_restore.log. Probe headers remain unreferenced
in ptmp as evidence. No production emitter/schedule change was made by profiling.

Rechecked SHA-256 of both ptmp/xs_gate59/emu/emu and the 50k verified backup
ptmp/grhsim_gate59_50k_verified_emu:
e3447dc332f3fd6649da7a1b1a59add38733080b62bb376c620c2f0cab057dbd.
Thus the baseline is restored to the actual 50k-validated binary without
requiring another simulation to establish identity.

## Candidate Boundary

Resolve immutable string constants at their use sites, omit their standalone
assignments and string-slot lifetime setup. Keep std::string expressions for
generic consumers so comparisons, muxes and inout copies retain value semantics.
This moves construction into existing call guards, without changing ingest,
DPI compute placement, conditions/events/history, void-call preservation, IR,
mapping, scheduling or dynamic string storage. Initialization activates every
compute supernode; immutable constants need no later change notifications.
Tests must cover local and boundary constants, shared consumers, escaping,
real void DPI counts, dynamic strings and reinitialization. Runtime benefit
requires an independent candidate measurement; the overall gate remains open.
