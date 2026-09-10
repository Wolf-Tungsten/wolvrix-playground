# Compute-Task Event Guard Hoisting

- Node: `compute_guard_hoist_20260911_01`
- Status: IDEA / BASELINE recorded; not yet implemented
- Root baseline: `24349282318a7a7a625453ee72bebe085a1a0195`; wolvrix baseline: `767240530a717b9d6d749d31766538c2ab1e4762`.

## Hypothesis

The accepted [compute-history node](grhsim-ir-candidate-compute-history-20260911.md)
aliased 13,382 private compute-side event histories to per-unit
representatives. A side effect not yet exploited: the event **guards** of the
aliased ops are now textually identical within a scheduler unit — every guard
in the assert/DPI class evaluates `en_i && (false || (!hist_rep && clk))` with
the same representative history object and the same boundary clock. Static
count on the accepted compute-history model: 13,763 compute-style guard
expressions across 51 tasks, of which **13,381 are repeats** of an identical
expression already evaluated earlier in the same unit (each task has only 8
distinct guard texts, one per unit key). Each repeated guard reloads the
history byte from visible state and the clock byte from the boundary — about 2
loads per guard, ~1,008 loads per task invocation, across the 51 tasks that
top the compute ranking.

Fresh profile on the accepted compute-history executable (diagnostic runs
`post_ch_profile_20260911_phase/cpu`, both NEMU PASS with the exact endpoint,
35,919 samples): compute 70.05% / commit 28.87% / publication 1.02% of eval
time (publication collapsed from 5.03%, so that direction is spent);
`cpu_write_scalar<bool>` fell 8.71% → 0.88%; the assert/DPI class still tops
the compute ranking (top-10 compute tasks all from this class, 3.23% of all
samples, ~51 tasks × ~0.3% each ≈ 12-16% class total). The remaining body
cost of this class is dominated by the per-assertion guard machinery now that
staging collapsed 16,255 → 2,873 sites.

Mechanism: per scheduler unit in an `ActivityDrivenCompute` task, group
event-guarded ops (`core.dpi.call` / `core.system.task`) by the resolved guard
key — for each edge, the tuple (event value id, alias-resolved history state
id, polarity) — and for every key used by ≥2 ops, emit one
`const bool cpu_cevent_<unit>_<n> = (false || ...);` at unit entry and rewrite
each grouped op's `if(en && (guard))` as `if(cpu_cevent_<unit>_<n> && en)`.
This mirrors the accepted commit-side `commitEdgeSnapshots`, but on compute
tasks and with the conjunct order swapped so the hoisted event test
short-circuits the per-assertion enable load on the (roughly half) invocations
where the sampled clock is on the wrong edge.

Soundness, from generic IR/layout/schedule properties only:

- Within one task invocation, visible state (`cpu_objects`) is stable: staging
  writes go to shadow, publication runs after the phase (the same invariant
  the commit-side snapshots rely on). The only compute-side writes to visible
  state are `core.output.write` ops and DPI result publication into
  read-aliased results; a unit containing either (`core.output.write`, or a
  `core.dpi.call` with any results) is excluded entirely.
- The event value must be invariant during the unit: it is eligible only if
  it is a read alias (i.e. a visible-state read) or its layout slot is
  `Boundary`, and it is not among the results produced by any op in the same
  unit (boundary slots can be written by in-unit producers). Per-unit scoping
  makes cross-unit production safe by construction.
- Conjuncts are pure loads, so swapping `en && guard` to `guard_local && en`
  is semantics-preserving; sampling order, DPI behavior, shadow/publish
  timing, and fanout activation are untouched. Histories need no privacy
  requirement here: hoisting only caches reads within a single invocation.
- Helper-chunked units hoist per helper chunk (chunk = sequential op range of
  one generated function), same rules.

Local target: 3-6% total Host-time reduction. Bound: the assert/DPI class
holds ~12-16% of runtime; the hoisted expression eliminates ~97% of its guard
re-evaluations (13,381/13,763), each saving ~2 loads plus half the enable
loads. Falsification: the measured gain against a matching-source isolated
control is within noise / below the standing >3% gate; or equivalence fails.
This is the first attempt at this mechanism; at most one refinement retry.

## Baseline and gates recorded before execution

- Control: the accepted compute-history executable
  (`ptmp/compute_history_20260911_01/flow`, wolvrix `7672405`), archived
  unprofiled pair 182.379 / 182.451 s, mean **182.415 s**. A fresh isolated
  local control is run before any candidate; a final control is allowed to
  resolve drift.
- Preselected simulation stop-loss: 1.5 × 182.415 = **273.6225 s**
  process-group KILL, applied to every run including controls, selected
  before any run of this node.
- Full SV generation and C++ compilation each have a **1800 s** KILL
  deadline; resume-from-IR is disabled for the candidate generation.
- Any TIMEOUT_KILLED, REGRESSION_KILLED, non-zero exit, crash, assertion, or
  NEMU mismatch marks the run INVALID, rejects this node, and ends its
  performance experiments.
- Acceptance requires: focused emitter tests passing; both build gates; two
  independent candidate 50k runs plus control(s) with NEMU PASS and the exact
  accepted endpoint (73,580 instructions, cycleCnt 49,996, terminal PC
  0x80001312, guest cycles 50,001); and Host-time improvement beyond the
  standing >3% gate against the local control, beyond observed noise.
- Fixed configuration (rechecked at entry): XiangShan
  `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`; CoreMark SHA-256
  `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`; top
  SimTop, DIFFTEST/NEMU; 50,000 cycles; CPU 2 via taskset; explicit
  `XS_EMU_THREADS=1`; waveform/commit/RAM trace off; 32 compile jobs; gsim
  20.640 s reference reused unchanged.
- Temporary artifacts under `ptmp/compute_guard_hoist_20260911_01/`.
  Diagnostic profiles under `ptmp/post_ch_profile_20260911/` (runs above are
  diagnostic-only and never performance evidence). Frozen GRH, GRH passes,
  XiangShan, and workload sources remain untouched; no module names are used
  as triggers.

## IMPLEMENTED

The CPU emitter gains `planComputeEdgeGuards()`
(`wolvrix/lib/grhsim/backend/cpu_emit.cpp`), invoked after
`planComputeSharedHistories()`. For every `ActivityDrivenCompute` task it
walks each scheduler unit (active-word child partitions) and first computes a
unit-wide exclusion set: the unit is skipped entirely if it contains a
`core.output.write` op or a `core.dpi.call` with results (the only compute-side
writes to visible state), and every value produced by any op in the unit is
recorded. It then groups `core.dpi.call` (history base 1) and
`core.system.task` (history base 0) ops with `event_edges` by the resolved
key — per edge, (event value id, alias-resolved history state id, polarity
string). An op joins a group only if every edge's event value is invariant
during the unit invocation: a read alias (visible-state read) or a
`CpuStorageKind::Boundary` slot, and not produced anywhere in the unit.
Groups of two or more ops get a `cpu_cevent_<unit>_<n>` local holding the
shared `eventGuard` expression. Histories need no privacy requirement:
hoisting only caches reads within one invocation, and visible state is stable
during any task because staging writes shadow and publication runs after the
phase (the same invariant the commit-side `commitEdgeSnapshots` relies on).

Emission rewires the four guard sites: `dpiCall` and `systemTask` accept an
optional cached guard name and emit `if(cpu_cevent_<unit>_<n> && <condition>)`
(the remaining conjuncts — `cpu_first_eval`, once-task flags — keep their
place), swapping pure-load conjuncts so the hoisted event test short-circuits
the per-call condition load. Non-chunked units emit the local at unit entry
and pass an op→name map through `computeGroup`→`compute`. Helper-chunked
units emit the local at unit entry and pass it as an extra `bool` parameter to
exactly the chunk helpers that consume it (declaration, definition, and call
site derive the same ordered parameter list from the plan). Grouping is
unit-wide even for chunked units, so a value produced in one chunk correctly
disqualifies hoisting for the whole unit. Sampling order, DPI behavior,
staging, fanout activation, and publication timing are untouched. Diagnostics
gain `compute_guard_snapshots=` / `compute_guard_snapshot_uses=` counters
(appended after the compute-history fields; existing substring checks are
preserved).

`WOLF_ENV_SOURCED=1 make --no-print-directory test_grhsim_cpu_emit` exited 0;
CTest passed in **66.56 seconds**. The extended `testComputeHistorySharing`
fixture (twelve clock-posedge `display` tasks in six same-unit pairs) now
additionally asserts `compute_guard_snapshots=6 compute_guard_snapshot_uses=12
`, exactly six `const bool cpu_cevent_` locals, twelve `if(cpu_cevent_` uses,
and that the raw `(false ||` guard expression survives only in the six locals.
All existing scoreboards passed unchanged, including the CDC fixture (10,756
samples, 1,182 simultaneous edges, 20 async resets), dual RAM (9,731 samples),
history scoreboards, commit-side sharing/edge-snapshot assertions, and the
Verilator differential runs at the end of the suite. One refinement was needed
during implementation: grouping was first per helper chunk, which found no
repeats because the mapper splits small units into single-op chunks; grouping
is now unit-wide with helper-parameter passing. This is the final test
version; no semantic change was needed after the first passing run.

## Generation, Compilation and Coverage

Full SV generation (fresh directory, resume disabled) used the established
command template with `RUN_ID=compute_guard_hoist_20260911_01_generate`; it
exited 0 with Make wall **601.22 s** (user 692.65, sys 25.35), PASS against
the 1800 s gate. The flat GRH is byte-identical to the accepted
compute-history control (SHA-256
`518f41485197156a91ff13df2eacb72f23dd63fec9bbc29fd0a6ffe1b8ace923` both
sides), and the fresh-session GrhSIM IR store/load round-trip is stable. No
GRH transformation, XiangShan, or workload source was changed.

32-job compilation (`RUN_ID=compute_guard_hoist_20260911_01_compile`, clang++
C++20 -O3) exited 0 with a linked emu in **251.18 s** (user 6051.69, sys
455.33), PASS against the 1800 s gate. The candidate executable is
124,392,144 bytes vs the control's 125,563,464.

Static source comparison (control `ptmp/compute_history_20260911_01/flow/model`,
candidate this node's model; read-only counting, commands preserved in
`ptmp/compute_guard_hoist_20260911_01/static_guards.txt`):

| Static measure | Control | Candidate |
|---|---:|---:|
| `(false ||` guard expressions (all tasks) | 19,149 | **5,842** |
| `const bool cpu_cevent_` hoisted locals | 0 | **323** |
| `if(cpu_cevent_` guarded-call uses | 0 | **13,630** |
| `cpu_write_scalar<bool>` staging sites | 2,873 | 2,873 |
| Commit `cpu_edge_snapshot` decls | 496 | 496 |

The 13,307 eliminated guard expressions equal 13,630 grouped uses minus the
323 surviving locals; the arithmetic closes exactly. Commit-side measures
(edge snapshots, staging sites) are exactly unchanged, confirming the
mechanism touches only compute-task guards. Static counts are emission-site
observations, not runtime frequency; the simulation below is the benefit
measurement.

## Simulation

All builds and the read-only static analysis finished before any simulation;
runs were sequential and isolated. Template (per label/run_id/flow):

```bash
WOLF_ENV_SOURCED=1 XS_EMU_THREADS=1 EMU_PHASE_TIMING=0 EMU_RUNTIME_PROFILE=0 make --no-print-directory run_xs_wolf_grhsim_ir_emu RUN_ID="$run_id" XS_GRHSIM_IR_BUILD="$flow" XS_LOG_DIR=ptmp/compute_guard_hoist_20260911_01/logs XS_SIM_MAX_CYCLE=50000 XS_EMU_CPU=2 XS_PROGRESS_EVERY_CYCLES=0 XS_WAVEFORM=0 XS_COMMIT_TRACE=0 XS_RAM_TRACE=0 XS_WAVEFORM_PATH= WOLVRIX_GRHSIM_WAVEFORM=0 XS_EMU_PREFIX="timeout --signal=KILL 273.6225s /usr/bin/time -p -o $PWD/ptmp/compute_guard_hoist_20260911_01/$label.time taskset -c 2 stdbuf -oL -eL" > "ptmp/compute_guard_hoist_20260911_01/$label.log" 2>&1
```

| label | run_id | flow |
|---|---|---|
| control | compute_guard_hoist_20260911_01_control | ptmp/compute_history_20260911_01/flow |
| run1 | compute_guard_hoist_20260911_01_run1 | ptmp/compute_guard_hoist_20260911_01/flow |
| run2 | compute_guard_hoist_20260911_01_run2 | ptmp/compute_guard_hoist_20260911_01/flow |

| Run | Host s | Exec wall s | Exit | NEMU / endpoint | Stop-loss |
|---|---:|---:|---:|---|---|
| Control (compute-history, isolated) | 183.520 | 183.483 | 0 | PASS / exact | NONE |
| Candidate 1 | 169.410 | 169.382 | 0 | PASS / identical | NONE |
| Candidate 2, independent process | 169.710 | 169.681 | 0 | PASS / identical | NONE |

Every run reports 73,580 instructions, cycleCnt 49,996, terminal PC
0x80001312, guest cycles 50,001, with no mismatch, ABORT, bad trap,
assertion, or segmentation fault. The preselected 273.6225 s deadline was
never approached. Candidate mean is **169.560 s**; the two candidates differ
by 0.300 s (0.177% of the mean). The local control is 0.606% above the
archived 182.415 s mean, showing small session drift. Primary comparison:
`(1 - 169.560 / 183.520) * 100 = ` **7.6068%** Host-time reduction against
the contemporaneous isolated control; against the archived control mean it
would be 7.0470%. The margin exceeds the >3% gate by 2.5x and the candidate
spread is more than an order of magnitude smaller than the gain, so no final
control was needed to resolve drift. No profiler or waveform was enabled; no
failed run was used as evidence.

## Final Decision and Archive

**ACCEPTED.** Compute-task event guard hoisting produces a reproducible
local benefit far beyond noise: two independent 50k NEMU PASS runs at
169.410 / 169.710 s against an isolated same-session control at 183.520 s
(-7.6068%), with byte-identical flat GRH, stable IR round-trip, full
generation 601.22 s and 32-job compilation 251.18 s (both under the 1800 s
gates), and focused emitter tests including the extended same-unit fixture
passing in 66.56 s. Statically, 13,630 repeated guard evaluations across the
51 assert/DPI-class tasks collapsed into 323 per-unit locals (`(false ||`
guard expressions 19,149 -> 5,842; the delta matches 13,630 - 323 exactly);
staging sites (2,873) and commit-side edge snapshots (496) are untouched.
This is a local node result, not the ~40 s objective: the new best mean is
**169.560 s**, still 129.560 s above it. The gain lands slightly above the
3-6% exploratory estimate; the hoisted-first conjunct order also removes the
per-call condition load on wrong-edge invocations, which the static counts
do not separate from the pure load elimination.

The retained change touches only the CPU emitter, its focused tests, and the
node documentation: wolvrix `lib/grhsim/backend/cpu_emit.cpp` (compute guard
planner, emission rewiring, two diagnostic counters) and
`tests/grhsim/test_cpu_emit.cpp` (extended fixture assertions), committed as
one submodule commit; the root commit records this report, the updated goal
index, and the submodule pointer. Frozen GRH, GRH passes, XiangShan, and
workload sources are unchanged; generated models, logs, and binaries stay
untracked under `ptmp/`.

Search review: four accepted mechanisms now compose (shared commit history,
commit edge snapshots, compute history sharing, compute guard hoisting). The
guard-hoist family is now exhausted on the compute side (remaining
`(false ||` expressions are commit-side or singleton guards); the same
single-invocation caching argument could extend to commit task 5141 (2.60%,
4,094 repeated 2-term edge predicates, IR-shared histories that need a
stability-during-commit proof rather than privacy), which is the largest
remaining concentrated task. Publication collapsed to 1.02% and is spent as
a direction. Remaining bounded directions: task 5141 commit guard caching
(~2-3% bound), the flat 3,193-task compute mass (no concentrated generic
pattern identified yet; would need a new mechanism), or a fresh profile
after this node.
