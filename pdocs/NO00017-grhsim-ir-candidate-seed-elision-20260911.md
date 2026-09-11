# Seeded State-Read Layer Elision via Change Arming

- Node: `seed_elision_20260911_01`
- Status: ACCEPTED; candidate mean 98.915 s vs isolated control 165.820 s (−40.3461%), all gates passed
- Root baseline: `306830c094e5d9f2f2f7227d7f415d048e9fa382`; wolvrix baseline: `e19e58db2349831592463434126f4533f5d8302c` (compute-guard-hoist, accepted NO00016).

## Hypothesis

The accepted [compute-guard-hoist node](NO00016-grhsim-ir-candidate-compute-guard-hoist-20260911.md)
left a perfectly flat compute profile: fresh diagnostics on the accepted
executable (`ptmp/post_gh_profile_20260911/`, 34,409 samples, both runs NEMU
PASS with the exact endpoint) show compute tasks at **63.68%** of flat samples
spread across **3,230 tasks** (hottest compute task only 0.23%), phase split
compute **116.62 s (68.53%)** / commit 51.67 s (30.37%) / publication 1.80 s
(1.06%) of 170.17 s eval. No per-task or per-class mechanism can address this
mass.

Structural analysis of the generated evaluator shows the flat mass is
dominated by the **per-round seeded state-read layer**: the round loop seeds
1,716 active-word bytes arming **6,002 scheduler units** in 1,709 tasks every
round (201,258 rounds). These units statically contain ~121,847
change-detecting write sites plus the reads/logic feeding them. Per
`cpu_schedule.cpp:207-219`, a unit is seeded when it contains a
`core.system.function/task` or `core.dpi.call` (311 units) or reads a state
outside the **quiescence projection** (5,684 units) — the projection covers
only the output/event/history relevance cone
(`quiescenceStates`, `cpu_schedule.cpp:81`), so states whose values feed only
DPI-side sinks are untracked and their readers must re-execute every round
regardless of whether anything changed.

Static facts established this node (read-only, commands and scripts preserved
under `ptmp/post_gh_profile_20260911/`):

- Seeded units read **86,392 distinct states**; all but 383 have commit
  writers (the "never-written reader" sub-mechanism covers only 31 units —
  statically excluded).
- Readers per read state: median 1, mean 1.38, p90 1, max 882 — wakes under
  per-state change arming ≈ changed-states × 1.38, low overlap.
- Unit bodies: median 142 statements / 9 write sites / K=13 distinct read
  states (p90 K=41); 26.7% of units have K≤4 and ≥50 statements.
- Typical read states (offsets resolved against the IR layout, 1-based ids):
  `delayedWriteBack_*_valid_last_REG`, `ssit` predictor state, RAT difftest
  tables, `__reg_to_mem_*` register arrays, icache `readReqReg` — real,
  actively-written pipeline state, not constants.

Mechanism (conditional on the falsification gate below): make the seeded
state-read layer **change-driven** — a state-reading unit re-executes only
when at least one state it reads actually changed value since its last
execution, instead of every round. Publication already detects actual changes
(memcmp in `cpu_publish`, staging fast path) and already arms projected-state
readers via `cpu_targets` / memory readers via `cpu_read_offsets`; the
mechanism extends change notification to the states read by the seeded layer
(publish-side arming and/or per-unit version guards, exact form chosen from
the diagnostic data). Seeding remains for DPI/system units and for first-eval
initialisation. Soundness rests on: staging compares current-vs-next so only
real changes enqueue; publication runs before the next round; a reader
re-armed after publication reads the same committed value it would have read
under unconditional seeding; input/value arming paths are untouched.

Local target: >3% total Host-time reduction (standing gate); the seeded layer
bounds a large multiple of that if the measured skip rate is high.
Falsification (pre-registered): a diagnostic build counts publication
records / actual changes per round. If changed-states-per-round is so large
that change-armed readers would remain a substantial fraction of the 6,002
seeded units (skip rate too low to beat the >3% gate after tracking
overhead), the hypothesis is rejected with evidence and the node stops
without implementation. This is the first attempt; at most one refinement
retry.

## Falsification gate: PASSED with decisive margins

Two diagnostic-only builds of the accepted guard-hoist model (patched
generated source under `ptmp/post_gh_profile_20260911/diag_model`, never
performance evidence; both 50k runs NEMU PASS with the exact endpoint,
169.83 / 171.35 s Host under the 254.34 s stop-loss):

- Publish counters: 201,258 publish calls; **2,154.5 staged records/round**
  but only **431.1 actual changes/round** (memcmp-filtered at publish), of
  which **13.6/round touch non-projected states** and 26.0/round are memory
  cells. Staged-but-unchanged records are a separate observation, not used
  here.
- Sampled change identity (1,089,179 changes logged across five 500-publish
  windows): only **2,297 distinct states** change. Crossing with the static
  unit→state read map (readers/state median 1, mean 1.38): change-armed
  wakes per round = **mean 266.8 / median 234 / p90 560 / max 947 of 6,002
  seeded units — a 4.44% mean state-side wake fraction**. Value-fanout wakes
  add on top, but the bound leaves roughly an order of magnitude of headroom
  against the >3% acceptance gate even under large valuation errors.

## Baseline and gates recorded before execution

- Control: the accepted compute-guard-hoist executable
  (`ptmp/compute_guard_hoist_20260911_01/flow`, wolvrix `e19e58d`), archived
  unprofiled pair 169.410 / 169.710 s, mean **169.560 s**. A fresh isolated
  local control is run before any candidate; a final control is allowed to
  resolve drift.
- Preselected simulation stop-loss: 1.5 × 169.560 = **254.34 s**
  process-group KILL, applied to every run of this node including controls
  and diagnostics, selected before any run of this node.
- Full SV generation and C++ compilation each have a **1800 s** KILL
  deadline; resume-from-IR is disabled for any candidate generation (the
  diagnostic-only build may reuse checkpoints and is never performance
  evidence).
- Any TIMEOUT_KILLED, REGRESSION_KILLED, non-zero exit, crash, assertion, or
  NEMU mismatch marks the run INVALID, rejects this node, and ends its
  performance experiments.
- Acceptance requires: focused emitter tests passing; both build gates; two
  independent candidate 50k runs plus control(s) with NEMU PASS and the exact
  accepted endpoint (73,580 instructions, cycleCnt 49,996, terminal PC
  0x80001312, guest cycles 50,001); Host-time improvement beyond the >3%
  gate against the local control, beyond observed noise.
- Fixed configuration (rechecked at entry): XiangShan
  `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`; CoreMark SHA-256
  `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`; top
  SimTop, DIFFTEST/NEMU; 50,000 cycles; CPU 2 via taskset; explicit
  `XS_EMU_THREADS=1`; waveform/commit/RAM trace off; host 32 CPUs; gsim
  20.640 s reference reused unchanged.
- Temporary artifacts: diagnostics under `ptmp/post_gh_profile_20260911/`
  (profile pair + `diag_model`/`diag_flow` publish-counter build, never
  performance evidence); candidate work under
  `ptmp/seed_elision_20260911_01/`. Frozen GRH, GRH passes, XiangShan, and
  workload sources remain untouched; no module names are used as triggers.

## IMPLEMENTED

Mechanism (publish-side change arming, convergence semantics untouched):

- `cpu_schedule.cpp` (`buildSchedule`): a `core.state.read` /
  `core.state.memRead` op now always contributes its owner to the read
  states' commit-fanout rows (`stateEdges`), projected or not; `roundSeeds`
  is kept only for `core.system.function` / `core.system.task` /
  `core.dpi.call` owners. The quiescence projection (output/event/history
  closure E) is stored in the plan as `quiescenceProjection` (state-indexed
  bitmap) and still decides only the pending record's convergence
  (`again`) flag — so eval round structure, termination, and cross-eval
  deferral are bit-identical to the control semantics. Replicated E on the
  control IR: 437,592 of 508,487 states projected; non-projected 70,895.
- `model.hpp`: `CpuSchedulePlan` gains `quiescenceProjection`; serialized in
  `json.cpp` as bit-count + u64 words (round-trip covered by fixtures).
- `cpu_emit.cpp`: `projected_` is sourced from `quiescenceProjection`
  instead of fanout-row presence (row presence previously coincided with
  projection). Staging sites, `stageCell`, and the direct-commit path
  (`cpu_direct_state_changed`) pick up the extended rows automatically —
  pending records for newly tracked states carry their reader rows with
  `projection=false`; memory readers keep the existing read-offset arming
  (sound because the read index value itself is compute-fanout tracked).
- First-eval propagation is unchanged: init arms all active words (255), so
  every unit runs at least once; afterwards a state reader runs exactly when
  one of its read states actually changed or a value/input edge armed it —
  within-round compute→commit→publish ordering is preserved, and a reader
  re-armed by publish reads the same committed value it would have read
  under unconditional seeding (including the posedge register-chain timing:
  round-1 commit consumers always see pre-edge values).
- Soundness exclusions that stay seeded: every unit containing
  system-task/function or DPI ops (side effects / untracked external state).

Focused tests: `test_grhsim_cpu_emit` passes in **67.10 s** with the
mechanism active — including the private-commit fixture whose DPI-argument
scoreboard exercises exactly the non-projected state→compute→DPI path, the
CDC/dual-RAM/history fixtures, and the Verilator differential runs. Its
`testPrivateCommits` assertion was updated from the old invariant
("non-projected reads have no fanout rows") to the new one (all three read
states tracked, projection bitmap empty). `test_grhsim_cpu_schedule` passes
with: (a) `unitTests` assertions re-based on `quiescenceProjection` for E
and on `commitStateFanout` for tracked-read coverage, asserting the dead
state's reader is fanout-armed and no longer seeded while the external time
source stays seeded; (b) the schedule-trace differential simulator aligned
to the new convergence semantics (`again` only for projection rows, arming
for all) and extended with a four-register **non-projected tail** fixture
asserting `roundSeeds` empty / projection membership / reader fanout,
compared against dense evaluation every eval for 260 directed+random steps.
`test_grhsim_cpu_mapping` and `grhsim-ir-tests` (JSON round-trip) also pass.

## Generation, Compilation and Coverage

Full SV generation (fresh directory, resume disabled) with
`RUN_ID=seed_elision_20260911_01_generate` exited 0: flow script
**600.89 s**; Make-level wall including the cold editable-rebuild of the
wolvrix bindings **960.06 s** — both under the 1800 s gate. The flat GRH is
byte-identical to the accepted guard-hoist control (SHA-256
`518f41485197156a91ff13df2eacb72f23dd63fec9bbc29fd0a6ffe1b8ace923` both
sides) and the GrhSIM IR store/load round-trip is verified stable by the
flow. No GRH transformation, XiangShan, or workload source was changed.

Static source comparison (control `ptmp/compute_guard_hoist_20260911_01/flow/model`
vs this node's model, read-only counting):

| Static measure | Control | Candidate |
|---|---:|---:|
| Per-round seed stores in `eval()` | 1,716 | **51** |
| Seeded active-word bits | 6,032 | **358** |
| `cpu_write_scalar<bool>` staging sites | 2,873 | 2,873 |
| Bool initializers / unique addresses | 399,130 / 100,335 | identical |
| History batches / edge snapshots / uses | 212 / 496 / 226,510 | identical |
| Changed task files (of 5,595) | — | 565 |

The remaining 51 seed stores cover the active words containing DPI/system
ops (the soundness exclusion). Staging, history-sharing, and edge-snapshot
structures are untouched; the 565 changed task files differ only in staging
begin/count literals and direct-commit notification lines. Static counts
are emission-site observations, not runtime frequency; the simulation
below is the benefit measurement.

32-job compilation (`RUN_ID=seed_elision_20260911_01_compile`, clang++
C++20 -O3) exited 0 with a linked emu in **253.02 s** wall, PASS against the
1800 s gate. The candidate executable is 126,608,080 bytes vs the control's
124,392,144 (+1.8%, larger fanout literals). A 2k-cycle smoke run exited 0
with no assertion before the full runs.

## Simulation

All builds and the read-only static analysis finished before any simulation;
runs were sequential and isolated, unprofiled (`EMU_RUNTIME_PROFILE=0`), with
the preselected 254.34 s stop-loss never approached. Template identical to
the control template with `RUN_ID=seed_elision_20260911_01_{control,run1,run2}`.

| Run | Flow | Host s | Exit | NEMU / endpoint | Stop-loss |
|---|---|---:|---:|---|---|
| Control (guard-hoist, isolated) | compute_guard_hoist flow | 165.820 | 0 | PASS / exact | NONE |
| Candidate 1 | this node | 97.710 | 0 | PASS / identical | NONE |
| Candidate 2, independent process | this node | 100.120 | 0 | PASS / identical | NONE |

Every run reports 73,580 instructions, cycleCnt 49,996, terminal PC
0x80001312 (EXCEEDING CYCLE/INSTR LIMIT), guest cycles 50,001, with zero
`mismatch` occurrences and no ABORT, bad trap, assertion, or segmentation
fault. Candidate mean is **98.915 s**; the two candidates differ by 2.410 s
(2.44% of the mean). Primary comparison:
`(1 - 98.915 / 165.820) * 100 = ` **40.3461%** Host-time reduction against
the contemporaneous isolated control; against the archived control mean
169.560 s it would be 41.6635%. The margin exceeds the >3% gate by 13x and
is more than an order of magnitude above the candidate spread, so no final
control was needed to resolve drift (the isolated control sits 2.21% below
the archived mean, within normal session drift). No profiler or waveform was
enabled; no failed run was used as evidence.

Post-hoc phase diagnostic (separate `EMU_RUNTIME_PROFILE=1` run on the
candidate, NEMU PASS with the exact endpoint, 100.19 s diagnostic Host —
not performance evidence): eval 99.98 s with **compute 45.65 s (45.65%)**,
commit 52.36 s (52.36%), publication 1.93 s (1.93%), rounds/eval unchanged
at 2.0105. Against the control's diagnostic split (compute 116.62 / commit
51.67 / publish 1.80 s), compute fell **60.86%** while commit, publication,
and the round structure are untouched — exactly the mechanism's predicted
action. The 4.44% state-side wake estimate implied a larger ideal bound;
the realized 60.9% compute reduction (rather than ~90%) reflects
value-fanout wakes, the arming walk in publish, and code-layout effects, as
expected for a lower-bound static estimate.

## Final Decision and Archive

**ACCEPTED.** State-read change arming (seed elision) produces a
reproducible local benefit far beyond noise and far beyond the >3% gate:
two independent 50k NEMU PASS runs at 97.710 / 100.120 s against an
isolated same-session control at 165.820 s (−40.3461%), with byte-identical
flat GRH, stable IR round-trip, full generation 600.89 s script / 960.06 s
Make wall and 32-job compilation 253.02 s (all under the 1800 s gates), and
focused emitter/schedule/mapping/IR tests passing (67.10 s emitter suite
including the DPI-argument scoreboard that exercises the non-projected
path; the schedule-trace differential with the new non-projected-tail
fixture). Statically, per-round seed stores collapsed 1,716 → 51 (seeded
active-word bits 6,032 → 358, the DPI/system exclusion); staging sites
(2,873), history batches (212), edge snapshots (496 / 226,510 uses), and
bool initializers (399,130) are untouched. This is a local node result, not
the ~40 s objective: the new best mean is **98.915 s**, still 58.915 s above
it. The commit phase (52.36 s, 52.4% of eval) is now the majority cost;
compute is down to 45.65 s.

The retained change touches the CPU scheduler, the schedule plan and its
serialization, the CPU emitter's projection sourcing, backend documentation,
and focused tests: wolvrix `lib/grhsim/backend/cpu_schedule.cpp` (state
readers always commit-fanout-armed; round seeds only for system/DPI owners;
`quiescenceProjection` stored; diagnostics), `include/grhsim/ir/model.hpp`
(plan field), `lib/grhsim/io/json.cpp` (bitmap serialization),
`lib/grhsim/backend/cpu_emit.cpp` (projection sourced from the plan),
`docs/grhsim_ir/backends/cpu.md` (semantics updated),
`tests/grhsim/test_cpu_{emit,schedule,schedule_trace}.cpp` (re-based
invariants plus the non-projected-tail differential fixture), committed as
one submodule commit; the root commit records this report, the updated goal
index, and the submodule pointer. Frozen GRH, GRH passes, XiangShan, and
workload sources are unchanged; generated models, logs, and binaries stay
untracked under `ptmp/`.

Search review: five accepted mechanisms now compose (shared commit history,
commit edge snapshots, compute history sharing, compute guard hoisting,
state-read change arming). The seeded state-read layer is eliminated as a
cost center (compute 116.62 → 45.65 s); remaining bounded directions: the
commit phase (52.36 s) with task 5141 still the hottest single task (2.65%
pre-change profile) and the commit top-10 at 8.6%; the ~45.65 s compute
residue (DPI/system-seeded units plus genuinely change-driven work — needs
a fresh profile); the 80% staged-but-unchanged publish records observed in
the diagnostic (2,154 records/round vs 431 changes) as a staging-side
candidate; and the evaluator's fixed per-round cost. This is the third node
since the last review; the campaign is not stuck in low-yield tuning (this
node: −40.35%).
