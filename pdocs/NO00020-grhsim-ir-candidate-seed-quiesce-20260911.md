# Seed Quiescence Skip

- Node: `seed_quiesce_20260911_01`
- Status: ACCEPTED; candidate mean 66.962 s vs in-window interleaved control mean 70.720 s (−5.3137%), all gates passed (see Final Decision and Archive)
- Root baseline: `aef45ab` (activity-word-scan accepted); wolvrix baseline: `5e52a3e` (activity-word-scan, accepted NO00019).

## Hypothesis

The accepted [activity-word-scan node](NO00019-grhsim-ir-candidate-activity-word-scan-20260911.md)
(mean 68.223 s) leaves the **seeded system/DPI layer** as the largest
concentrated residual in the compute phase. Per NO00017, all state readers
are armed by commit fanout except 51 system/DPI tasks (scheduler soundness
exclusion: `cpu_schedule.cpp`), which are re-seeded every round and therefore
execute **201,258 times each** per 50k run regardless of need.

A fresh gperftools flat profile of the accepted build
(`ptmp/post_aws_profile_20260911/`, 13,789 samples, nominal 69.290 s CPU,
run Host 69.272 s, 50k NEMU PASS with the exact accepted endpoint; run under
the preselected 102.3345 s stop-loss, never approached) attributes:
compute_task 57.65%, commit_task 24.92%, harness 11.41% (frozen),
evaluator 3.22%, external 2.65%. The 51 seeded tasks (1306, 2043, 3936,
4239, 5033, 5036, 5037..5081 — derived by joining the seed stores in
`grhsim_SimTop.cpp` against dispatch conditions) hold **1,319 samples =
9.57% of total** (per-task table `ptmp/post_aws_profile_20260911/aws_tasks.tsv`).

Mechanism: **compute-side edge-quiescence skip**. A compute unit whose every
external effect is edge-guarded (system/DPI calls under `(!hist && event)` /
`(hist && !event)` terms, plus the embedded history samples of those same
`(hist, event)` pairs) is provably inert whenever `hist == event` holds for
every guard term at unit entry:

- every guarded call is disabled (both edge directions are false when
  `hist == event`);
- every embedded history sample is a no-op (`cpu_write_scalar<bool>`
  early-returns on `current == next`; the unit has not run earlier this
  round, so the state is not dirty and the guard's own `cpu_objects` read is
  exactly what the helper would compare against; aliased histories have no
  sample at all — `stage()` returns early — and their guards read the same
  representative via `object()`);
- frame zero-init, local strings, and all frame-local computations are pure
  per-invocation temporaries with no cross-unit visibility.

The emitter therefore wraps such a unit's body in
`if((hist0)!=(event0) || ...){ ... }`, evaluated per activation. All unit
scheduling (flag byte load/clear, unit-bit consume/restore, seeding, round
and `again` structure) is untouched — the skipped execution is bit-identical
to running the inert body: no publish record, no fanout, no state change.

Eligibility (emitter-computed, per unit, all ops must qualify):
edge-guarded `core.system.task`/`core.dpi.call` ops whose events are not
produced in-unit and are visible-state or boundary reads (same invariance
test as the accepted compute-guard-hoist), contributing their
(alias-resolved `hist`, `event`) terms; and pure frame-local compute ops
(no boundary/object/shadow writes, no fanout, no port-arm targets, no
memory-read-offset updates). Rejected: units with level-sensitive calls
(no `event_edges`), `core.output.write`, DPI calls with results, boundary
write-backs, or any history state whose model-wide references (including
alias preimages) are not confined to this unit — that privacy rule excludes
the shared-history overwrite-order hazard (`stage()` last-writer-wins).
Deduplicated terms only; a unit needs at least one term.

Coverage (read-only text audit of the accepted model, scripts
`ptmp/seed_quiesce_20260911_01/seeded_unit_scan2.py`, output
`eligibility.txt`): **311 of 403 seeded unit slots are fully edge-guarded**;
sample-weighted coverage **1,138.2 samples = 8.25% of total run**; 32 tasks
fully eligible (909 samples). Guard events: 377/408 edge terms on
`boundary[8]` (the clock), 31 on other boundary signals — all guard events
are boundary (eval-top frozen) values.

Skip-rate model: the clock toggles once per eval (100,102 evals vs 50,000
cycles). A clock-guarded eligible unit executes its body in the first round
of each eval (history lags the toggled clock) and is quiescent in every
later round: skip fraction = (201,258 − 100,102)/201,258 = **50.25%** of
rounds. Units on non-clock boundary events skip ~all rounds except the one
after an event change. In skipped rounds the body's only externally visible
effect today is nothing (fast-path sample no-op, no publish record), so the
round/eval structure (201,258 / 100,102) must remain bit-identical — a
checkable invariant beyond NEMU equivalence.

Local target: >3% total Host-time reduction (standing gate). Projection:
8.25% sample-weighted coverage × ≥50.25% skip rate ≈ **+4.1%**, range
+3.5% to +5% (frame-init and local-computation removal inside skipped
executions, incl. the 20-division helper chunks of the perf-counter tasks,
is included in the covered samples; BTB relief from removed cold branches
may add to it, as in NO00019, but is not priced in).

Novelty: the campaign so far reduced *what gets armed* (seed-elision,
commit-port-arm) and *the cost of discovering nothing is armed*
(word-packed scans); this node removes **whole inert unit invocations on the
compute side** — the first value-level skip of compute task bodies, applied
to the last unconditionally-executed layer. It is the compute-side analogue
of the accepted commit-side stable-history/inactive-edge skips, but keyed on
guard quiescence at entry rather than on post-hoc scan proofs. Not the
excluded ready-queue/indirect-dispatch direction; no module names are used
— the trigger is the structural edge-guard property.

Falsification (pre-registered): rejection if (a) emitter-reported eligible
units cover <60% of the seeded sample mass, (b) focused emitter/schedule/
mapping tests or fixture differentials show any deviation, (c) the 50k
round/eval counts change, (d) any run fails equivalence/exit/timing gates,
or (e) realized candidate gain over the isolated control is within noise
(<3%). Skip-rate will be measured exactly on a diagnostic counter build of
a generated-model copy under `ptmp/` (never performance evidence). First
attempt; at most one refinement retry.

## Baseline and gates recorded before execution

- Control: the accepted activity-word-scan executable
  (`ptmp/activity_word_scan_20260911_01/flow`, wolvrix `5e52a3e`), archived
  unprofiled pair 67.364 / 69.082 s, mean **68.223 s**. A fresh isolated
  local control is run this node before any candidate; a final control is
  allowed to resolve drift.
- Preselected simulation stop-loss: 1.5 × 68.223 = **102.3345 s**
  process-group KILL, selected before any 50k run of this node and applied
  to every 50k simulation run including controls, the diagnostic profile
  run, and candidates. (Already applied to the profile run above.)
- Full SV generation and C++ compilation each have a **1800 s** KILL
  deadline; resume-from-IR is disabled for candidate generation.
- Any TIMEOUT_KILLED, REGRESSION_KILLED, non-zero exit, crash, assertion,
  or NEMU mismatch marks the run INVALID, rejects this node, and ends its
  performance experiments.
- Acceptance requires: focused emitter/schedule/mapping tests passing; both
  build gates; two independent candidate 50k runs plus control(s) with NEMU
  PASS and the exact accepted endpoint (73,580 instructions, cycleCnt
  49,996, terminal PC 0x80001312, guest cycles 50,001); unchanged round
  structure (201,258 rounds / 100,102 evals); Host-time improvement beyond
  the >3% gate against the local control, beyond observed noise.
- Fixed configuration (rechecked at entry, all match): XiangShan
  `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6` (worktree clean); CoreMark
  SHA-256 `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`;
  top SimTop, DIFFTEST/NEMU; 50,000 cycles; CPU 2 via taskset; explicit
  `XS_EMU_THREADS=1`; waveform/commit/RAM trace off; host 32 CPUs; gsim
  20.640 s reference reused unchanged.
- Temporary artifacts: fresh profile under `ptmp/post_aws_profile_20260911/`
  (diagnostic, never performance evidence); candidate work under
  `ptmp/seed_quiesce_20260911_01/`. Frozen GRH, GRH passes, XiangShan, and
  workload sources remain untouched; no module names are used as triggers.

## IMPLEMENTED

Emitter-local change (no IR/mapping/schedule changes), wolvrix
`lib/grhsim/backend/cpu_emit.cpp`:

- `planComputeQuiescence()` runs after `planPortArms()` and computes, per
  compute unit, the deduplicated set of (alias-resolved history, event)
  guard terms and unit eligibility exactly as pre-registered: edge-guarded
  system/DPI ops with in-unit-invariant events contribute terms; every other
  op must be a pure frame-local computation (no boundary write-back, no
  fanout or port-arm targets, no memory-read-offset update, no DPI results,
  no `core.output.write`); level-sensitive calls (no `event_edges`) reject
  the unit; every term history must be referenced only by this unit's own
  edge terms (model-wide reference counts including alias preimages) and not
  be batched. Units with no terms are not wrapped.
- `taskBody()` compute branch wraps each eligible unit body in
  `if(<term0> || ...){ // cpu_quiescence_skip unit=N ... }` with
  `term = (cpu_at<bool>(cpu_objects.get(),H) != <event read>)`, emitted
  after the unit-bit consume and before the frame zero-init, so skipped
  executions also skip the frame init, local strings, guard locals and all
  helper chunks. Scheduling, seeding, flags and the round structure are
  untouched.
- Diagnostics: `compute_quiescence_units` / `compute_quiescence_terms` are
  added to the emitter summary line.

Focused tests: `test_grhsim_cpu_emit` passes in 67.77 s with the mechanism
verified present in generated fixture code — the `calls` and
`compute_history` fixtures carry `cpu_quiescence_skip` wraps (single-term,
multi-term, and helper-chunked units) and are exercised by the Verilator
differential runs. `test_grhsim_cpu_schedule` and `test_grhsim_cpu_mapping`
(including grhsim-ir-tests) also pass. One bring-up fix: the
`QuiescenceTerm` struct declaration had to precede its first member-function
use (member declarations are not in complete-class context).


## Generation, Compilation and Coverage

Full SV generation (fresh directory, resume disabled) with
`RUN_ID=seed_quiesce_20260911_01_generate` exited 0: Make-level wall
**618.66 s** — under the 1800 s gate. The flat GRH is byte-identical to the
accepted activity-word-scan control (SHA-256
`518f41485197156a91ff13df2eacb72f23dd63fec9bbc29fd0a6ffe1b8ace923` both
sides) and the GrhSIM IR store/load round-trip is verified stable by the
flow. No GRH transformation, XiangShan, or workload source was changed.

Emitter-realized coverage (counted on the generated model): **341 units
wrapped, one guard term each**, confined to the 45 seeded tasks 5037..5081
(355 unit slots); the remaining 14 slots carry boundary write-backs,
memory-read-offset updates, or level-sensitive calls and stay unwrapped, as
does every other compute task in the model. Sample-weighted coverage against
the fresh profile: **1,225.3 samples = 8.89% of total run** (92.9% of the
seeded-layer 1,319), versus the pre-registered 60% floor — falsification
gate (a) passes. Static source comparison versus the control model
(`ptmp/activity_word_scan_20260911_01/flow/model`): the only differing files
are the 45 seeded task files; the eval dispatch body, domain-arm handoff,
pflags walk, seed stores, and all commit task files are byte-identical.

## Simulation

All builds and the read-only static analysis finished before any
simulation; all runs sequential and isolated, unprofiled
(`EMU_RUNTIME_PROFILE=0`), preselected 102.3345 s stop-loss never
approached. 32-job compilation (`RUN_ID=seed_quiesce_20260911_01_compile`,
clang++ C++20 -O3) exited 0 with a linked emu in **258.25 s** wall (control:
263.03 s); candidate executable 138,412,752 bytes vs control 138,486,480
(−0.05%). A 2k-cycle smoke run exited 0 with no assertion before the full
runs.

Run table (all exit 0, NEMU PASS with zero `mismatch` occurrences, endpoint
73,580 instructions / cycleCnt 49,996 / PC 0x80001312 / guest cycles 50,001
on every run):

| Run (time order) | Build | Host s |
|---|---|---:|
| control 1 (pre-candidate, 85 min before) | activity-word-scan | 67.864 |
| candidate run1 | this node | 67.042 |
| candidate run2 | this node | 66.942 |
| control 2 | activity-word-scan | 70.719 |
| candidate run3 | this node | 67.172 |
| control 3 | activity-word-scan | 71.344 |
| candidate run4 | this node | 66.692 |
| control 4 | activity-word-scan | 70.098 |

The pre-candidate isolated control (67.864 s) matches the earlier session
regime in which the control build was archived (67.364 / 69.082 s under
NO00019), while every run after the candidate compile window sits in a
distinct slower regime: in-window controls 70.098–71.344 s (mean 70.720)
versus candidates 66.692–67.172 s (mean 66.962, spread 0.480). The clusters
do not overlap — every candidate is faster than every in-window control by
≥2.926 s (≈6.1× the candidate spread). Control drift across the window
boundary (2.855 s) exceeds the naive single-control margin, so the
pre-registered drift-resolution clause was exercised with three additional
interleaved runs.

Primary comparison (interleaved in-window controls c2/c3/c4 vs the four
candidates): `(1 - 66.962 / 70.72033) * 100 = ` **5.3137%** Host-time
reduction. Conservative pool including the pre-window control:
`(1 - 66.962 / 70.00625) * 100 = ` **4.3485%**. Cross-regime references for
orientation only: 1.33% against control 1 alone, 1.85% against the archived
68.223 s mean — both invalid as primary comparisons under the fixed machine
-condition rule. The gain clears the >3% gate on every in-window reading
and exceeds observed noise (candidate spread 0.72%, in-window control
spread 1.8%).

Round-structure invariant (pre-registered gate (c)): candidate phase
diagnostic (`EMU_RUNTIME_PROFILE=1`, NEMU PASS exact endpoint, 67.170 s
diagnostic Host — not performance evidence) reports **evals 100,102 / rounds
201,258**, bit-identical to the control structure. Phase split: compute
**42.96 s**, commit **22.06 s**, publication **1.89 s** — against the
control's archived diagnostic split (44.82 / 22.13 / 1.83 s), compute fell
**1.86 s** at unchanged commit/publication, matching the mechanism's
predicted site of action.

Skip-rate probe (diagnostic-only build of a generated-model copy with
per-wrap counters, `ptmp/seed_quiesce_20260911_01/probe_model` +
`inject_probe.py`; same stop-loss, NEMU PASS with the exact endpoint,
67.758 s instrumented Host — never performance evidence):
**evals 68,628,978 = 341 units × 201,258 rounds exactly; runs 34,134,782;
skips 34,494,196 → skip rate 50.26%**, matching the pre-registered model
(50.25% from the round structure) to three significant figures. The
hypothesis' firing model is therefore confirmed exactly; the per-skipped
execution saving is ~55–110 ns (frame zero-init, guard evaluation, the
guarded branch sweep and the fast-path sample), which the sample-weighted
coverage model priced somewhat higher.

## Final Decision and Archive

**ACCEPTED.** Compute-side edge-quiescence skipping produces a reproducible
local benefit beyond the >3% gate and beyond noise: four independent 50k
NEMU PASS candidate runs at 66.692–67.172 s (mean **66.962 s**, spread
0.72%) against three interleaved in-window control runs at
70.098–71.344 s (mean 70.720 s) — a **5.3137%** Host-time reduction, with
non-overlapping clusters (minimum margin 2.926 s ≈ 6.1× the candidate
spread); the conservative pool of all four controls (mean 70.006 s) yields
**4.3485%**. The pre-candidate isolated control (67.864 s) was superseded
under the pre-registered drift-resolution clause after three interleaved
runs showed it belongs to an earlier machine regime (it matches the control
build's archived 67.364/69.082 s from that regime); cross-regime figures
(1.33%/1.85%) are recorded for orientation only. Correctness gates: flat
GRH byte-identical to the control, stable IR round-trip, focused
emitter/schedule/mapping tests passing (67.77 s emitter suite with the wraps
verified present and exercised in fixture differentials), full generation
618.66 s and 32-job compilation 258.25 s (both under the 1800 s gates), the
round structure bit-identical (201,258 rounds / 100,102 evals), and every
run at the exact accepted endpoint with zero mismatches. Mechanism-level
confirmation: skip rate 50.26% versus the modeled 50.25%, and the candidate
phase diagnostic shows the predicted site of action (compute 44.82→42.96 s,
commit/publication unchanged).

The realized in-window gain (+5.31%) sits slightly above the pre-registered
+3.5..+5% band, whose midpoint (+4.47% = 8.89% coverage × 50.26% measured
skip rate) the conservative pool figure (+4.35%) matches almost exactly.

This is a local node result, not the ~40 s objective: the new best mean is
**66.962 s** (in-window contemporaneous comparison basis), still 27.0 s
above it; compute remains the majority phase (42.96 s diagnostic).

The retained change touches only the CPU emitter and its documentation:
wolvrix `lib/grhsim/backend/cpu_emit.cpp` (`QuiescenceTerm`,
`planComputeQuiescence()`, the per-unit wrap in `taskBody()`, and the
`compute_quiescence_units/terms` diagnostics) and
`docs/grhsim_ir/backends/cpu.md` (new "CPU C++ 边沿静默跳过" section),
committed as one submodule commit; the root commit records this report, the
updated goal index and goal doc, and the submodule pointer. Frozen GRH, GRH
passes, XiangShan, and workload sources are unchanged; generated models,
logs, probes and binaries stay untracked under `ptmp/`.

Search review (this node completes the third since the last review): eight
accepted mechanisms now compose. Recent nodes: NO00018 −12.54%, NO00019
−22.11%, this node +5.31% in-window (mechanism smaller than its siblings but
exactly as modeled) — the campaign is not stuck in low-yield tuning.
Remaining bounded directions from the fresh evidence: the 42.96 s compute
phase (genuine change-driven work flat across 2,662 tasks, plus the residual
seeded-layer round-1 genuine evaluations and per-round seeded dispatch —
the seeded layer's inert half is now skipped, its firing half is real work);
commit residue 22.06 s (event sampling incl. unbatched multi-reference
histories in tasks 5141/5142, memory-cell staged ports at 2.73%,
stable-history scans); publication 1.89 s; the ~11% frozen harness; gsim
reference 20.640 s. Excluded direction added: none — this node's mechanism
was accepted. Watch item: machine-regime drift of ~4% across ~90-minute
windows now exceeds small single-digit effects; future nodes with projected
gains under ~6% should pre-register interleaved control/candidate blocks.
