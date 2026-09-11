# Change-Armed Commit Write Ports

- Node: `commit_port_arm_20260911_01`
- Status: ACCEPTED; candidate mean 87.0055 s vs isolated control 99.475 s (−12.5352%), all gates passed
- Root baseline: `1cfb1b8` (seed-elision accepted); wolvrix baseline: `098d6e5` (seed-elision, accepted NO00017).

## Hypothesis

The accepted [seed-elision node](NO00017-grhsim-ir-candidate-seed-elision-20260911.md)
(mean 98.915 s) leaves the commit phase as the majority cost. A fresh
gperftools flat profile of the accepted executable
(`ptmp/post_se_profile_20260911/`, 19,950 samples, nominal 100.249 s CPU,
50k NEMU PASS with the exact accepted endpoint; run under the preselected
148.3725 s stop-loss, never approached) attributes:

| Category | Samples | % |
|---|---:|---:|
| commit_task (514 tasks) | 9,461 | 47.42 |
| compute_task (5,081 tasks) | 7,353 | 36.86 |
| main_other (emu harness, frozen) | 1,664 | 8.34 |
| evaluator (`eval()` body) | 1,141 | 5.72 |
| external libraries | 300 | 1.50 |
| publication (separate phase) | inside evaluator/publish | 1.93 s by phase timer |

Inside commit, task_5141 alone holds 932 samples (4.67% of total); the
top-10 commit tasks hold 3,126 (15.7%); 149 of 514 commit tasks are sampled.
Out-of-line helpers: `cpu_stage_cell` 2.0%, `cpu_write_scalar<bool>` 1.21%,
`cpu_direct_state_changed` 1.03%.

Structural analysis of the hot commit tasks (generated source, read-only):
each is a 20-29k-line DomainGatedCommit body with 1,890-4,096 direct-commit
write ports; existing fast paths (stable-history whole-task skip via memchr,
inactive-edge sample-only path, shared edge snapshots) are already present.
The residual cost is the **main-path port walk**: when the domain is armed
and an edge is pending, every port executes
`if((cpu_edge_snapshot_N) && enable){ load current; value=(current&~mask)|(data&mask); if(current!=value){write; fanout;} }`.
The dominant "enable" (boundary offset 26284, ~24k ports across the top
tasks) is a **constant-1** produced in task_1310, so it filters nothing;
per port the walk reduces to load data + load current + compare + branch,
almost always finding `current==value` (the NO00017 diagnostic measured
only 431.1 actual state changes/round across ~122k walked ports).

Mechanism: make commit write-port evaluation **change-armed**. A port is
evaluated at an edge only if at least one of its operand boundary values
(enable/mask/data) was change-published since its last evaluation; otherwise
the evaluation provably ends in `current==value` (no write, no fanout), so
skipping it is unobservable. Arming hooks are emitted inline at the compute
write sites of port-operand values (a new per-port-group activity-flag
array `cpu_pflags` armed with the same mask-OR pattern as existing compute
fanout), requiring compare-on-write for operand values that currently store
without change detection (verified: sampled operand data values have plain
stores, zero compare sites). Eligibility (v1): direct-commit scalar ports
(unique writer, so `current` is stable between the port's evaluations) whose
guard+value expressions read only boundary values (event values excluded —
covered by domain arming); staged shared-state, memory-cell, wide, and
history-adjacent ports stay on the existing always-walk path. History
sampling stays unconditional per task; edge snapshots, stable-history scan
and inactive-edge paths are unchanged; publish, projection and round
structure are bit-identical (skipped ports make no state modification and
no notification, exactly as their `current==value` outcomes do today).

Soundness argument: boundary operand values change only through compute
change-publishes; between two evaluations of a port its operands are
therefore identical unless an arm was raised, and the arm survives until
the port is next evaluated at a fired edge (sample-only and stable-skip
paths do not consume arm bits). A skipped port would have recomputed the
same value and found `current==value` (direct-commit target state is
written only by this port), so state contents, fanout notifications,
pending records and the round/`again` structure are exactly preserved.

Local target: >3% total Host-time reduction (standing gate); the mechanism
addresses up to the no-op share of the 47.4% commit mass. Falsification
(pre-registered, measured before implementation): a diagnostic-only
instrumented build counts (a) per-task executions and early-path splits,
(b) change events per operand boundary offset, (c) store-site executions
of operand values. Combined with the static operand map
(`ptmp/post_se_profile_20260911/`), it estimates the armed-port fraction
per main-path execution and the added compute-side compare cost. Rejection
rule: if the projected net benefit (commit walk reduction minus added
compute cost) cannot reach +6% of total with clear margin — e.g. because
the armed fraction stays high (operands toggle every edge) or the
compare cost on hot compute write sites eats the win — the hypothesis is
rejected with evidence and the node stops without implementation. This is
the first attempt; at most one refinement retry.

## Baseline and gates recorded before execution

- Control: the accepted seed-elision executable
  (`ptmp/seed_elision_20260911_01/flow`, wolvrix `098d6e5`), archived
  unprofiled pair 97.710 / 100.120 s, mean **98.915 s**. A fresh isolated
  local control is run before any candidate; a final control is allowed to
  resolve drift.
- Preselected simulation stop-loss: 1.5 × 98.915 = **148.3725 s**
  process-group KILL, applied to every 50k simulation run of this node
  including controls, diagnostics and candidates, selected before any run
  of this node. (Instrumented diagnostic builds are never performance
  evidence; if a diagnostic build legitimately needs more time it is run
  with an explicit larger diagnostic-only KILL bound recorded here, and
  its wall time is never compared against the stop-loss.)
- Full SV generation and C++ compilation each have a **1800 s** KILL
  deadline; resume-from-IR is disabled for any candidate generation (the
  diagnostic-only build may reuse checkpoints and is never performance
  evidence).
- Any TIMEOUT_KILLED, REGRESSION_KILLED, non-zero exit, crash, assertion,
  or NEMU mismatch marks the run INVALID, rejects this node, and ends its
  performance experiments.
- Acceptance requires: focused emitter/schedule tests passing; both build
  gates; two independent candidate 50k runs plus control(s) with NEMU PASS
  and the exact accepted endpoint (73,580 instructions, cycleCnt 49,996,
  terminal PC 0x80001312, guest cycles 50,001); Host-time improvement
  beyond the >3% gate against the local control, beyond observed noise.
- Fixed configuration (rechecked at entry): XiangShan
  `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`; CoreMark SHA-256
  `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`; top
  SimTop, DIFFTEST/NEMU; 50,000 cycles; CPU 2 via taskset; explicit
  `XS_EMU_THREADS=1`; waveform/commit/RAM trace off; host 32 CPUs; gsim
  20.640 s reference reused unchanged.
- Temporary artifacts: diagnostics under `ptmp/post_se_profile_20260911/`
  (flat profile pair + static maps, never performance evidence); candidate
  work under `ptmp/commit_port_arm_20260911_01/`. Frozen GRH, GRH passes,
  XiangShan, and workload sources remain untouched; no module names are
  used as triggers.

## Falsification gate

Static facts established this node (read-only, scripts and outputs preserved
under `ptmp/post_se_profile_20260911/`):

- Full per-task sample attribution (`tasks.tsv`, 19,950 samples): commit
  tasks hold 9,461 samples (47.42% of total) across 149 sampled of 514
  tasks; compute tasks 7,353 (36.86%) across 2,510 sampled of 5,081;
  evaluator body 5.72%; emu harness 8.34% (frozen); external 1.50%.
- Hot commit tasks are DomainGatedCommit bodies of 20-29k lines with
  1,890-4,096 direct-commit bool write ports each; the existing
  stable-history memchr skip is present in 117 task files and the
  inactive-edge sample-only path in 513 of 514.
- Eligible-port parse (`commit_ports.tsv`, line-state-machine over the
  uniform generated template): **183,858 direct-commit bool ports** carry a
  guard of the form `(edge) && enable` with a boundary-only value
  expression (192,348 direct-commit ops exist in total; 8,490 lack the
  fanout-notify line and are equally eligible but were not matched by the
  strict template); **46,847** other guard blocks (staged / memory / wide /
  non-template) remain always-walked. The top-20 sampled commit tasks hold
  65,776 of the eligible ports (e.g. task_5114 4,096/4,096 eligible).
- Operand map (`operands.tsv` / `operand_fanout.tsv`): the eligible ports
  read **162,953 distinct boundary offsets** (463,479 port-operand reads,
  ≈2.5 per port). The dominant shared enable/mask (offset 26284, fanout
  110,536 across 502 tasks) is a **constant-1** produced once in task_1310
  with an existing compare — it filters nothing and arms nothing.
- Change-detection hooks: only 4,926 operand offsets (3.0%) have an
  existing compute-side change compare, but those cover 52.8% of
  port-operand reads; the other 158,027 offsets store plainly
  (`store_sites=1` each; every operand offset has exactly one writer task).

Diagnostic runtime counters (instrumented build, never performance
evidence): the instrumented emu (per-task dispatch counters, early-path
counters, and change-event counters on all 162,953 operand stores — 4,926
existing compare forms + 158,025 plain stores wrapped) ran 50k at 119.2 s
Host (instrumentation overhead ~19%, under the 148.3725 s stop-loss) with
NEMU PASS, the exact accepted endpoint, and the round structure preserved
(evals 100,102 / rounds 201,258). Results (`diag_dump.tsv` +
`gate_analysis.py`):

- Hot commit tasks execute ~200,204 times each (every round); tasks with
  the stable-history skip split into ~100k stable / ~50k sample-only /
  ~50k main; task_5141 (no stable skip) runs 100,207 main paths.
- **Armed-port fraction upper bound: 3.49% of guard walks** (per-task
  0.10%-16.24%, mostly 1-3%; the bound counts every store-site change
  event, including wiggles that re-arm idempotently, so the true armed
  fraction is lower).
- Cost side: 1.832G plain-store executions/run (these would gain the new
  compare) and 49.8M existing-compare executions — modeled at ≈2.4 s added
  compute time, already subtracted below.
- Projected net benefit (calibrated walk cost 4.18 ns/port; model:
  scan=1×walk per 8-port word, armed body=2-4×walk, non-walk share
  haircut 0.5-0.9): **net +10.80% (worst parameter combo) to +24.34% of
  total time**. The most conservative combination clears the
  pre-registered +6% threshold and the >3% standing gate.

**Falsification gate: PASSED.** Proceeding to implementation.

## IMPLEMENTED

Mechanism (emitter-local, no IR/mapping/schedule changes):

- `cpu_emit.cpp` (`planPortArms`, called from `validate()` after the existing
  plan passes): a `core.state.regWrite`/`latchWrite` op is change-armed when
  (a) its target is a direct-commit state (unique writer ⇒ `current` is
  stable between the port's evaluations), and (b) all three operands
  (enable/data/mask) are boundary-resident 2-state scalar logic values, not
  state.read aliases, produced only by `core.compute.*` / `core.state.read` /
  `core.state.memRead` / `core.input.read` (all store through the grouped
  change-publish path). Each task numbers eligible ops in op order, 8 per
  `cpu_pflags` activity byte (member emitted in the model header;
  `init()` fills 255 = all armed, so first evaluation walks everything).
- Arming (compute side): `computeGroup`'s changed-flag grouping key gains
  the port-arm signature, so values feeding commit ports receive a change
  compare even without existing fanout; the group tail emits
  `cpu_pflags[word] |= -changed & mask` next to the existing fanout masks
  (`armPorts()`). Constant operands have no change events and never re-arm,
  which is correct.
- Consumption (commit side, `taskBody` + `commit()` refactor): event
  sampling stays unconditional in original op order (shared-history
  overwrite order preserved); armed write blocks move after all unarmed
  ops into per-word groups
  `{armed=cpu_pflags[W]; if(armed){consumed=0; if(armed&bit){if(edge){consumed|=bit; if(en){body}}}…; cpu_pflags[W]&=~consumed;}}`.
  A bit is consumed only when the port's edge guard (shared snapshot var or
  inline edge expression, `true` for latch) fires; otherwise it persists
  across rounds/evals. Stable-history whole-task skips and inactive-edge
  sample-only paths do not consume bits. `commitEdgeGuard()` and
  `directCommitBody()` are factored out of `commit()` and shared by both
  paths; ineligible ops emit byte-identical code to the control.
- Soundness: a skipped port's operands are unchanged since its last
  consumption and its target state has a unique writer, so re-evaluation
  would find `current==value` and produce no write and no notification —
  state contents, pending records, fanout activations and the round/`again`
  structure are bit-identical to the control semantics. Armed blocks only
  reorder writes of disjoint unique-writer states while boundary values
  are stable, which is unobservable (the same argument as direct commit
  itself).

Focused tests: `test_grhsim_cpu_emit` passes in **67.56 s** with the
mechanism active and verified present in generated fixture code
(`private_commits` carries 3 armed ports — bool, signed 5-bit int8,
uint64 — emitted with the intended armed-group shape and exercised by the
DPI-argument scoreboard and repeated-eval fixture; after the eligibility
fixes, armed ports also appear in `cpu_cdc` (6), `cpu_dual_ram` (2),
`history_batches` (18) and `random_history` (32), all covered by the
Verilator differential runs). During bring-up three eligibility bugs were
found and fixed: `PortArmTarget` declaration order (signature visibility),
a 14-vs-13 character prefix-compare that had rejected every
`core.compute.*` producer (found because no fixture armed any ports), and
`core.input.read` initially missing from the allowed producer set (needed
by small fixtures; input values re-store through the same grouped compare
path when their supernode is input-fanout armed).
`test_grhsim_cpu_schedule` and `test_grhsim_cpu_mapping` also pass.

## Generation, Compilation and Coverage

Full SV generation (fresh directory, resume disabled) with
`RUN_ID=commit_port_arm_20260911_01_generate` exited 0: Make-level wall
**611.30 s** (venv/bindings already warm this node; the seed-elision node
recorded 600.89 s script / 960.06 s cold Make wall) — under the 1800 s
gate. The flat GRH is byte-identical to the accepted seed-elision control
(SHA-256 `518f41485197156a91ff13df2eacb72f23dd63fec9bbc29fd0a6ffe1b8ace923`
both sides) and the GrhSIM IR store/load round-trip is verified stable by
the flow. No GRH transformation, XiangShan, or workload source was changed.

Static source comparison (control `ptmp/seed_elision_20260911_01/flow/model`
vs this node's model, read-only counting):

| Static measure | Control | Candidate |
|---|---:|---:|
| Direct-commit write ports | 192,348 | 192,348 (same IR) |
| Change-armed ports | 0 | **192,340** (8 ineligible) |
| `cpu_pflags` bytes | — | 24,303 |
| Compute-side arm mask sites | — | 291,411 |
| New compare-on-write sites | — | ≈158k (operand values) |
| Task files | 5,595 | 5,595 |

32-job compilation (`RUN_ID=commit_port_arm_20260911_01_compile`, clang++
C++20 -O3) exited 0 with a linked emu in **256.08 s** wall, PASS against
the 1800 s gate (control: 253.02 s). The candidate executable is
137,954,000 bytes vs the control's 126,608,080 (+8.96%, added compares and
armed-group code). A 2k-cycle smoke run exited 0 with no assertion before
the full runs.

## Simulation

All builds and the read-only static analysis finished before any
simulation; runs were sequential and isolated, unprofiled
(`EMU_RUNTIME_PROFILE=0`), with the preselected 148.3725 s stop-loss never
approached. Template identical to the control template with
`RUN_ID=commit_port_arm_20260911_01_{control,run1,run2}`.

| Run | Flow | Host s | Exit | NEMU / endpoint | Stop-loss |
|---|---|---:|---:|---|---|
| Control (seed-elision, isolated) | seed_elision flow | 99.475 | 0 | PASS / exact | NONE |
| Candidate 1 | this node | 87.085 | 0 | PASS / identical | NONE |
| Candidate 2, independent process | this node | 86.926 | 0 | PASS / identical | NONE |

Every run reports 73,580 instructions, cycleCnt 49,996, terminal PC
0x80001312 (EXCEEDING CYCLE/INSTR LIMIT), guest cycles 50,001, with zero
`mismatch` occurrences and no ABORT, bad trap, assertion, or segmentation
fault. Candidate mean is **87.0055 s**; the two candidates differ by
0.159 s (0.18% of the mean). Primary comparison:
`(1 - 87.0055 / 99.475) * 100 = ` **12.5352%** Host-time reduction against
the contemporaneous isolated control; against the archived control mean
98.915 s it is 12.0401%. The margin exceeds the >3% gate by 4x and is ~70x
the candidate spread, so no final control was needed to resolve drift (the
isolated control sits 0.57% above the archived mean, within normal session
drift). No profiler or waveform was enabled; no failed run was used as
evidence.

Post-hoc phase diagnostic (separate `EMU_RUNTIME_PROFILE=1` run on the
candidate, NEMU PASS with the exact endpoint, 87.249 s diagnostic Host —
not performance evidence): eval 87.07 s with **compute 53.48 s (61.4%)**,
**commit 31.61 s (36.3%)**, publication 1.93 s (2.2%), rounds/eval
unchanged at 2.0105. Against the control's diagnostic split (compute
45.65 / commit 52.36 / publish 1.93 s), **commit fell 39.6%** while compute
rose 17.2% (the added compare-on-write cost, matching the gate model's
direction) and the round structure is untouched — exactly the mechanism's
predicted action. The gate projected net +10.8% to +24.3%; the realized
12.5% sits inside that range near its conservative end, consistent with
the armed-fraction being an upper-bound estimate plus code-layout effects.

## Final Decision and Archive

**ACCEPTED.** Change-armed commit write ports produce a reproducible local
benefit far beyond noise and beyond the >3% gate: two independent 50k NEMU
PASS runs at 87.085 / 86.926 s against an isolated same-session control at
99.475 s (−12.5352%), with byte-identical flat GRH, stable IR round-trip,
full generation 611.30 s Make wall and 32-job compilation 256.08 s (both
under the 1800 s gates), and focused emitter/schedule/mapping tests
passing (67.56 s emitter suite with armed ports verified in five fixtures
including the CDC, dual-RAM, history-batch and private-commit differential
coverage). Statically, 192,340 of 192,348 direct-commit ports are
change-armed through 24,303 `cpu_pflags` bytes and 291,411 compute-side
arm sites; the commit phase fell 52.36 → 31.61 s (−39.6%) at unchanged
round structure. This is a local node result, not the ~40 s objective: the
new best mean is **87.0055 s**, still 47.0 s above it; compute is again
the majority phase (53.48 s, 61.4%).

The retained change touches only the CPU emitter and its documentation:
wolvrix `lib/grhsim/backend/cpu_emit.cpp` (port-arm planning, grouping,
arming/consumption emission, `cpu_pflags` member and init, diagnostics) and
`docs/grhsim_ir/backends/cpu.md` (new "CPU C++ 提交端口变化武装" section),
committed as one submodule commit; the root commit records this report,
the updated goal index and goal doc, and the submodule pointer. Frozen
GRH, GRH passes, XiangShan, and workload sources are unchanged; generated
models, logs, and binaries stay untracked under `ptmp/`.

Search review: six accepted mechanisms now compose (shared commit history,
commit edge snapshots, compute history sharing, compute guard hoisting,
state-read change arming, commit-port change arming). The no-op commit
walk is eliminated as a cost center (commit 52.36 → 31.61 s); remaining
bounded directions: the 53.48 s compute phase (now 61.4% — the seeded
DPI/system layer runs every round at ~2-4% by the fresh profile's top
compute tasks, the rest is genuine change-driven work and needs a fresh
profile); the added compare-on-write cost itself (+7.83 s compute —
reducible by sharing compares across fanout-equal values or by cheaper
arming granularity); commit residue 31.61 s (memory-cell staged ports and
the always-walked ineligible share); the evaluator's fixed per-round cost
(5.72% including the dense per-round domain-arm handoff); and the 8.34%
frozen harness. This is the first node since the last review; the campaign
is not stuck in low-yield tuning (previous node −40.35%, this node
−12.54%).
