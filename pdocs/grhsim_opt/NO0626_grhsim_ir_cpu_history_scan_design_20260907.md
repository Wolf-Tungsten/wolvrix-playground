# CPU history-range edge rejection design

- Date: 2026-09-07
- Evidence: [NO0625](./NO0625_grhsim_ir_cpu_gate60_phase_profile_20260907.md).

## Motivation and Legacy Boundary

The existing gate59 sampling-only path rejects inactive event levels, but a
high posedge input still scans all commit guards in later fixed-point rounds
whose histories have already sampled high. Gate60 spends 9286.151 ms in
high-clock commit. Task 5602, a prior measured hot task, contains 4096 distinct
posedge histories in 172 contiguous byte ranges. This is a testable opportunity,
not proof that all its measured time is redundant scanning.

Legacy registerEventSamples shares edge slots by event ValueId and exactEventExpr
tests edge kinds. Do not copy that identity assumption onto independent IR
histories: different initial values and sampling ownership are observable.
Instead retain every semantic guard and use a read-only scan of actual current
history bytes as a conservative early rejection before the existing body.
No new return-by-value wide helper, allocation, copying or mutable cache is needed.

## Algorithm

Within an already eligible DomainGatedCommit task, group actual event/history
pairs by (ValueId, posedge/negedge), keeping the existing eight-term limit.
For each group whose histories are unsigned two-state one-bit values in
one-byte slots, sort and deduplicate offsets, then form exact contiguous ranges.
Use a scan only with at least 16 distinct histories and average range length
at least four. Other groups retain their existing level-only possibility test.

- Posedge group: current event is high AND any history byte is zero.
- Negedge group: current event is low AND any history byte is one.
- Task possibility is the OR of these groups; enables remain out of this test.

Read through cpu_objects, never cpu_shadow. std::memchr scans directly through
existing storage; multiple ranges use a constexpr offset/size table and an
early-return loop. No gaps, padding or unrelated states enter a range. A found
byte only chooses the unchanged full body, not an unconditional write. A false
aggregate chooses the existing sampling-only path, preserving each nonbatched
history sample in original order and all eligible private batches afterward.

## Correctness and Gate

The check is false only if every optimized event guard is false and every
unoptimized event level is incapable of its edge. History bytes may differ;
no representative-history substitution is allowed. Commit does not alter
visible guard histories before publication: normal direct writes exclude
history observers. Current event Value slots are also unchanged by commit.
Pending history overwrites must still occur on the sampling-only path.

General/AlwaysScanCommit, including shared-history conflict fallback, retain
their existing route. The optimization neither changes schedule/mapping nor
introduces fine-grained commit activation, DPI policy or fullpass execution.

Regression must cover distinct initial histories including a match only at the
last byte, both edge directions in a multi-event op, fixed-level data changes,
repeated evals, reinitialization, sparse ranges, and unchanged general/shared
fallback. Run the complete CPU suite and HDLBits, then independent XiangShan
generation/build and serial benchmarks. Reject or revise on measured regression;
do not claim completion from code shape or a short-window improvement.
