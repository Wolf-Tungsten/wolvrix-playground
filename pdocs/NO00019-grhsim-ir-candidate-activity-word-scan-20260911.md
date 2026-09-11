# Word-Packed Activity Scans

- Node: `activity_word_scan_20260911_01`
- Status: IN PROGRESS (IDEA/BASELINE recorded before any candidate work)
- Root baseline: `74e55ee` (commit-port-arm accepted); wolvrix baseline: `cc420ba` (commit-port-arm, accepted NO00018).

## Hypothesis

The accepted [commit-port-arm node](NO00018-grhsim-ir-candidate-commit-port-arm-20260911.md)
(mean 87.0055 s) leaves three dense byte-granularity **emptiness scans** as
shared fixed costs, executed every round or every commit-task execution:

1. **Evaluator per-round task dispatch**: the round loop emits
   `if(cpu_flags[N])cpu_task_X();` for all 5,595 tasks
   (`grhsim_SimTop.cpp` eval body). Measured on the current best build:
   5,588 single-byte checks (5,075 compute-task bytes in three consecutive
   runs, 513 commit-task domain bytes sparsely over range 0..966) plus 7
   multi-word tasks → **1.126 G byte checks/run** at 201,258 rounds.
2. **Domain-arm handoff**: 461 DomainArm slots copied and cleared per round
   (`cpu_flags[s]=cpu_next_arms[s];cpu_next_arms[s]=0;`, slots over range
   0..966) → **92.8 M slot updates/run**.
3. **Commit pflags port walk** (NO00018 mechanism): each main-path
   execution walks its task's `cpu_pflags` words
   (`{armed=cpu_pflags[W];if(armed){…}}`). Static walk words: 24,303 over
   511 commit tasks; with the per-task execution counts from the NO00018
   diagnostic (path structure unchanged since): **1.195 G byte checks/run**.

A fresh gperftools flat profile of the accepted executable
(`ptmp/post_cpa_profile_20260911/`, 17,208 samples, nominal 86.470 s CPU,
50k NEMU PASS with the exact accepted endpoint; run under the preselected
130.50825 s stop-loss, never approached) attributes: compute_task 52.16%
(spread flat over 2,662 tasks, top-10 only 3.1%), commit_task 29.77%
(top task_5141 1.27%), harness 9.19% (frozen), **evaluator `eval()` 6.56%
(≈5.7 s)**, external 2.16%; helpers `cpu_stage_cell` 2.27%,
`cpu_write_scalar<bool>` 1.64%, `cpu_direct_state_changed` 1.10%. The
evaluator scan and the pflags walk live inside the `eval()` 6.56% and the
flat commit-task mass respectively; combined dynamic scan volume is
**≈2.4 G byte checks/run**.

Mechanism: **word-granularity emptiness prefilter** — for every dense
byte-range scan over the contiguous `cpu_flags` / `cpu_next_arms` /
`cpu_pflags` arrays, emit a `uint64_t` test per 8 bytes (via `std::memcpy`
load, no aliasing/alignment UB): if the word is zero, all eight byte tests
are provably no-ops and are skipped; otherwise the original per-byte logic
runs unchanged inside the group. Applied uniformly to (a) the evaluator
dispatch runs (tasks whose checked bytes fall in the covered span; sparse
commit singletons grouped by array range, non-task bytes simply not tested
inside), (b) the domain-arm handoff (group test on
`next_arms|flags` — a slot needs the copy/clear only when either side is
non-zero), and (c) each commit task's pflags walk (task-local consecutive
word range packed 8:1, scalar tail).

Soundness: the prefilter is a pure read-path shortcut. A zero word means
every covered byte test would find its byte zero: no task would run, no
domain slot would change (handoff writes `flags=0` over an already-zero
byte and clears an already-zero `next_arms`), no port word would consume
or evaluate anything (armed bits persist when non-zero, and a non-zero
byte forces group entry). State contents, arm propagation, pending
records, fanout, and the round/`again` structure are bit-identical. No
queue, no reordering, no indirect dispatch — the dense in-order scan and
its flags are untouched (this is not the excluded ready-queue/indirect
direction of NO00005/NO00006).

Novelty: the campaign so far reduced *what work is armed* (seed-elision,
commit-port-arm); this node reduces *the cost of discovering that nothing
is armed*, a fixed tax every accepted mechanism still pays at byte
granularity. Hierarchical word activity tests are new to this evaluator —
flags are stored per byte and scanned per byte today.

Local target: >3% total Host-time reduction (standing gate). Model: scan
cost 1.5–3 ns/check; removed checks ≈2.2 G (packing keeps ~1/8 plus
non-zero-group handling) → projected **net +4% to +7%**, conservative
floor +3%.

Falsification (pre-registered): static coverage measured above (99.9% of
dispatch checks packable; all 24,303 walk words in per-task consecutive
ranges; dynamic scan volume ≈2.4 G/run). Rejection rule: if implementation
cannot pack ≥80% of the dynamic scan mass, or the focused emitter tests
show any semantic deviation, or the realized candidate gain over the
isolated control is within noise (<3%), the hypothesis is rejected with
evidence. First attempt; at most one refinement retry.

## Baseline and gates recorded before execution

- Control: the accepted commit-port-arm executable
  (`ptmp/commit_port_arm_20260911_01/flow`, wolvrix `cc420ba`), archived
  unprofiled pair 87.085 / 86.926 s, mean **87.0055 s**. A fresh isolated
  local control is run this node before any candidate; a final control is
  allowed to resolve drift.
- Preselected simulation stop-loss: 1.5 × 87.0055 = **130.50825 s**
  process-group KILL, selected before any 50k run of this node and applied
  to every 50k simulation run including controls, the profile run and
  candidates. (Instrumented diagnostic builds, if any, get an explicit
  diagnostic-only KILL bound recorded here and are never performance
  evidence.)
- Full SV generation and C++ compilation each have a **1800 s** KILL
  deadline; resume-from-IR is disabled for candidate generation.
- Any TIMEOUT_KILLED, REGRESSION_KILLED, non-zero exit, crash, assertion,
  or NEMU mismatch marks the run INVALID, rejects this node, and ends its
  performance experiments.
- Acceptance requires: focused emitter/schedule/mapping tests passing;
  both build gates; two independent candidate 50k runs plus control(s)
  with NEMU PASS and the exact accepted endpoint (73,580 instructions,
  cycleCnt 49,996, terminal PC 0x80001312, guest cycles 50,001); Host-time
  improvement beyond the >3% gate against the local control, beyond
  observed noise.
- Fixed configuration (rechecked at entry): XiangShan
  `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`; CoreMark SHA-256
  `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`; top
  SimTop, DIFFTEST/NEMU; 50,000 cycles; CPU 2 via taskset; explicit
  `XS_EMU_THREADS=1`; waveform/commit/RAM trace off; host 32 CPUs; gsim
  20.640 s reference reused unchanged.
- Temporary artifacts: fresh control-side profile under
  `ptmp/post_cpa_profile_20260911/` (diagnostic, never performance
  evidence); candidate work under `ptmp/activity_word_scan_20260911_01/`.
  Frozen GRH, GRH passes, XiangShan, and workload sources remain
  untouched; no module names are used as triggers.

## Falsification gate

Static facts established this node (read-only; scripts and outputs under
`ptmp/post_cpa_profile_20260911/` and `ptmp/activity_word_scan_20260911_01/`):

- Fresh flat profile of the accepted build (17,208 samples, nominal
  86.470 s, NEMU PASS, exact endpoint): compute_task 52.16% across 2,662
  sampled tasks (top-10 = 3.1% — no per-task lever); commit_task 29.77%
  across 158 sampled tasks; evaluator `eval()` 6.56%; harness 9.19%;
  external 2.16%.
- Dispatch scan (eval body parse): 5,588 single-byte task checks —
  5,075 bytes in three consecutive compute runs (3,722/1,174/179) and 513
  commit singletons over bytes 0..966 — plus 461 handoff slots over the
  same 0..966 range; 201,258 rounds → 1.126 G checks + 92.8 M slot
  updates per run.
- Pflags walk (commit task files parse): 511 tasks walk 24,303 distinct
  words; joined with NO00018 diagnostic per-task path counts (stable /
  sample-only / main structure unchanged by NO00018) → 1.195 G dynamic
  byte checks per run; every task's walk words form one consecutive range
  (packable 8:1 with a scalar tail).
- Combined dynamic scan mass ≈ **2.4 G byte checks/run**; the prefilter
  removes ≈7/8 of the zero-case checks (armed/non-zero fractions are a
  few percent at worst: port-arm fraction ≤3.49% per NO00018, task-flag
  occupancy per round is far below one per word).
- Cost model: 1.5–3 ns per byte check (load+test+branch over hot arrays)
  → current scan cost ≈3.6–7.2 s; post-pack ≈0.6–1.2 s; **projected net
  +4% to +7% of total Host time**, clearing the +3% floor even at the
  most conservative parameter combination.

**Falsification gate: PASSED.** Proceeding to implementation.

## IMPLEMENTED

Mechanism (emitter-local, no IR/mapping/schedule changes):

- `cpu_emit.cpp` header emission gains
  `cpu_word8(const std::uint8_t*, offset, bytes)` — a constant-size
  `std::memcpy` into a zeroed `uint64_t` (no aliasing or alignment UB; byte
  order is irrelevant for an emptiness test; `bytes` is always a literal,
  narrowed for tail groups so reads never cross the array end).
- **Dispatch packing** (eval body): the per-task checks are first collected
  as entries; maximal runs of adjacent single-byte checks that share one
  aligned 8-byte flags bucket (and the same phase, so the profile ticks stay
  at the exact transition points) are wrapped in
  `if(cpu_word8(cpu_flags.data(),base,n)){ … }` with the original per-task
  `if(cpu_flags[N])cpu_task_X();` lines inside, in original order. Groups
  with fewer than two checks and all multi-word/unconditional tasks emit
  byte-identical text to the control.
- **Domain-arm handoff packing**: DomainArm slots (sorted by offset) sharing
  a bucket are wrapped in
  `if((cpu_word8(cpu_next_arms…)|cpu_word8(cpu_flags…))!=0){ … }`; both sides
  are tested because the handoff also *clears* `cpu_flags[s]` when
  `next_arms[s]` is zero — a slot needs work only when either side is
  non-zero. Buckets with a single slot stay scalar.
- **Commit pflags walk packing** (`taskBody`): the armed-port walk is
  collected per word first (op order preserved), then emitted in 8-word
  groups over the task's consecutive word range with a `cpu_word8` prefilter
  on `cpu_pflags`; per-word blocks (`armed` test, per-bit edge-guard
  evaluation, consumption, write-back) are textually unchanged inside.
  Single-word groups stay scalar.
- Soundness: a zero prefilter word proves every covered byte test would find
  zero — no task would run, no slot would change (handoff on an
  already-zero pair writes zeros over zeros), no port word would consume or
  evaluate (armed bits persist precisely because a non-zero byte forces
  group entry). No queue, no reordering, no indirect dispatch: the dense
  in-order scan, all flags, arm/publish paths and the round/`again`
  structure are untouched.
- Diagnostics: the emitter now reports `dispatch_packed_checks`,
  `handoff_packed_slots`, `port_arm_walk_packed_words` after writing the
  model (the pre-write summary line is unchanged).

Focused tests: `test_grhsim_cpu_emit` passes in 67.94 s with the mechanism
verified present in generated fixture code — 41 fixture models carry the
`cpu_word8` helper; packed dispatch groups
(`if(cpu_word8(cpu_flags.data(),0,8)){if(cpu_flags[0])cpu_task_2();…`),
packed handoff groups and packed pflags walk groups (including narrowed
2/3/4-byte tails) all appear and are exercised by the Verilator
differential runs (private_commits, cpu_cdc, cpu_dual_ram,
history_batches, history_scan variants, …). One bring-up fix: the compute
condition text had to stay paren-exact because the suite textually asserts
`if(cpu_flags[N])cpu_task_X();` per activity-driven task.
`test_grhsim_cpu_schedule` and `test_grhsim_cpu_mapping` also pass.

## Generation, Compilation and Coverage

Full SV generation (fresh directory, resume disabled) with
`RUN_ID=activity_word_scan_20260911_01_generate` exited 0: Make-level wall
**612.45 s** — under the 1800 s gate. The flat GRH is byte-identical to the
accepted commit-port-arm control (SHA-256
`518f41485197156a91ff13df2eacb72f23dd63fec9bbc29fd0a6ffe1b8ace923` both
sides) and the GrhSIM IR store/load round-trip is verified stable by the
flow. No GRH transformation, XiangShan, or workload source was changed.

Static source comparison (control `ptmp/commit_port_arm_20260911_01/flow/model`
vs this node's model, read-only counting by
`ptmp/activity_word_scan_20260911_01/compare_models.py`):

| Static measure | Control | Candidate |
|---|---:|---:|
| `cpu_word8` helper emitted | no | yes |
| Dispatch task checks | 5,588 | 5,588 (same calls, same order) |
| Dispatch packed groups | 0 | **758** |
| Domain-arm handoff slots | 461 | 461 (same slots) |
| Handoff packed groups | 0 | **121** |
| Pflags walk words | 24,303 | 24,303 (same words) |
| Walk packed groups (≥2 words) | 0 | **3,027** covering **23,898** words (98.3%) |
| Task files | 5,595 | 5,595 |

32-job compilation (`RUN_ID=activity_word_scan_20260911_01_compile`,
clang++ C++20 -O3) exited 0 with a linked emu in **263.03 s** wall, PASS
against the 1800 s gate (control: 256.08 s). The candidate executable is
138,486,480 bytes vs the control's 137,954,000 (+0.39%). A 2k-cycle smoke
run exited 0 with no assertion before the full runs.

## Simulation

All builds and the read-only static analysis finished before any
simulation; runs were sequential and isolated, unprofiled
(`EMU_RUNTIME_PROFILE=0`), with the preselected 130.50825 s stop-loss
never approached. Template identical to the control template with
`RUN_ID=activity_word_scan_20260911_01_{control,run1,run2}`.

| Run | Flow | Host s | Exit | NEMU / endpoint | Stop-loss |
|---|---|---:|---:|---|---|
| Control (commit-port-arm, isolated) | commit_port_arm flow | 87.585 | 0 | PASS / exact | NONE |
| Candidate 1 | this node | 67.364 | 0 | PASS / identical | NONE |
| Candidate 2, independent process | this node | 69.082 | 0 | PASS / identical | NONE |

Every run reports 73,580 instructions, cycleCnt 49,996, terminal PC
0x80001312 (EXCEEDING CYCLE/INSTR LIMIT), guest cycles 50,001, with zero
`mismatch` occurrences and no ABORT, bad trap, assertion, or segmentation
fault. Candidate mean is **68.223 s**; the two candidates differ by
1.718 s (2.5% of the mean). Primary comparison:
`(1 - 68.223 / 87.585) * 100 = ` **22.1061%** Host-time reduction against
the contemporaneous isolated control; against the archived control mean
87.0055 s it is 21.5871%. The margin (~19.4 s) is ~11x the candidate
spread, so no final control was needed to resolve drift (the isolated
control sits 0.67% above the archived mean, within normal session drift).
No profiler or waveform was enabled; no failed run was used as evidence.

The realized gain exceeds the pre-registered model (+4% to +7%). The model
priced the removed byte checks as plain load+test+branch work (~2.4 G/run);
the extra factor is branch-predictor pressure: the dense per-round dispatch
of ~5.6k branches plus ~24k per-execution port-walk branches saturate the
BTB on this design, so each skipped byte check removed a likely-mispredicted
branch, not just a load. Word packing cuts the executed branch count ~8x
and shrinks the dispatch loop's code footprint ~8x. (Post-hoc phase
diagnostic below quantifies where the win landed; the mechanism's exact
state/arm/publish semantics are unchanged, and the 50k endpoints are
bit-identical.)

Post-hoc phase diagnostic (separate `EMU_RUNTIME_PROFILE=1` run on the
candidate, NEMU PASS with the exact endpoint, 69.033 s diagnostic Host —
not performance evidence): eval 68.86 s with **compute 44.82 s (65.1%)**,
**commit 22.13 s (32.1%)**, publication 1.83 s (2.7%), evals 100,102 and
rounds 201,258 — the round structure is bit-identical to the control
(2.0105 rounds/eval). Against the control's diagnostic split (compute
53.48 / commit 31.61 / publish 1.93 s), **compute fell 16.2%** (compute
dispatch packing plus the next-round-attributed handoff packing) and
**commit fell 30.0%** (commit dispatch packing plus the pflags walk
packing), while publish is unchanged — matching the mechanism's predicted
sites of action.

## Final Decision and Archive

**ACCEPTED.** Word-packed activity scans produce a reproducible local
benefit far beyond noise and beyond the >3% gate: two independent 50k NEMU
PASS runs at 67.364 / 69.082 s (mean **68.223 s**) against an isolated
same-session control at 87.585 s (−22.1061%), with byte-identical flat
GRH, stable IR round-trip, full generation 612.45 s Make wall and 32-job
compilation 263.03 s (both under the 1800 s gates), and focused
emitter/schedule/mapping tests passing (67.94 s emitter suite with packed
dispatch, handoff and pflags-walk groups verified present and exercised in
the fixture differential runs). Statically, all 5,588 dispatch checks are
covered by 758 word groups, all 461 handoff slots by 121 groups, and
23,898 of 24,303 pflags walk words (98.3%) by 3,027 groups; round
structure (201,258 rounds / 100,102 evals) and the exact 50k endpoint are
unchanged. This is a local node result, not the ~40 s objective: the new
best mean is **68.223 s**, still 28.2 s above it; compute is again the
majority phase (44.82 s, 65.1%).

The realized +22.1% exceeds the pre-registered +4..+7% model, which priced
byte checks as plain load+test work; the excess is attributed to
branch-predictor (BTB) capacity relief from removing ~2.4 G mostly-cold
per-byte branches per run. This does not change the verdict: the gain is
measured directly, twice, with the control interleaved in the same
session.

The retained change touches only the CPU emitter and its documentation:
wolvrix `lib/grhsim/backend/cpu_emit.cpp` (`cpu_word8` helper, packed
dispatch/domain-handoff emission in `eval()`, grouped pflags walk in
`taskBody()`, post-write pack diagnostics) and
`docs/grhsim_ir/backends/cpu.md` (new "CPU C++ 活动扫描字打包" section),
committed as one submodule commit; the root commit records this report,
the updated goal index and goal doc, and the submodule pointer. Frozen
GRH, GRH passes, XiangShan, and workload sources are unchanged; generated
models, logs, and binaries stay untracked under `ptmp/`.

Search review: seven accepted mechanisms now compose (shared commit
history, commit edge snapshots, compute history sharing, compute guard
hoisting, state-read change arming, commit-port change arming, word-packed
activity scans). The dense-scan fixed tax is eliminated as a cost center
(evaluator-side phases: compute 53.48→44.82 s, commit 31.61→22.13 s at
unchanged round structure). Remaining bounded directions: the 44.82 s
compute phase (genuine change-driven work plus the seeded system/DPI
layer, flat across 2,662 tasks — needs input-granular or value-level
mechanisms); commit residue 22.13 s (event sampling incl. unbatched
multi-reference histories in tasks 5141/5142, memory-cell staged ports,
stable-history scans); publication 1.83 s; the ~9% frozen harness; gsim
reference 20.640 s. This is the second node since the last review; the
campaign is not stuck in low-yield tuning (previous nodes −40.35%,
−12.54%, this node −22.11%).
