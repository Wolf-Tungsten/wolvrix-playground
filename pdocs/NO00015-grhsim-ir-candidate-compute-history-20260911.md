# Compute-Task Private Event History Sharing

- Node: `compute_history_20260911_01`
- Status: ACCEPTED; candidate mean 182.415 s vs control 213.636 s (−14.6141%), all gates passed
- Root baseline: `3164609`; wolvrix baseline: `c8b8676aee27efbf701e62d86c37e3ca86b576e3`.

## Hypothesis

Extend the accepted commit-side private event history sharing
([shared-history](NO00011-grhsim-ir-candidate-shared-history-20260910.md)) to eligible
compute tasks. The [residual-hotspots profile](NO00014-grhsim-ir-residual-hotspots-20260910.md)
shows the out-of-line `cpu_write_scalar<bool>` staging helper now holds
**8.7076%** of flat samples, with 13,763 of its 16,255 static call sites
(84.7%) in compute tasks — the assert/DPI task class that tops the compute
ranking (top-10 compute tasks all from this class, 6.5508% of compute
samples). Publication holds another 5.0300% of eval time, driven per pending
record.

Generated evidence (task_5048, representative of the class): each of ~500
assertions emits a guard `en_i && (!hist_i && clk)` reading its private
one-bit history from visible state, followed by an unconditional
`cpu_write_scalar<bool>(state_i, hist_i, ..., clk)` staging the same clock
into that history. Because the sampled clock toggles every eval, every sample
takes the helper's slow path (pending `push_back`, dirty set, shadow store)
and adds one publish record per eval — the fast path never applies. All
histories in such a task sample the same event value with the same constant
initializer, exactly the pattern that commit-side sharing collapsed
8,192 histories into 2 representatives in task 5121; it was scoped to commit
tasks only, leaving this compute-side class untouched.

Soundness for compute tasks rests on the same visible-vs-shadow separation
already relied on by the commit side: guards read the history from
**visible** state (`cpu_at<bool>(cpu_objects.get(), ...)`), while the sample
stages into the shadow and is published after the phase. Within one
invocation every guard therefore observes the pre-invocation value, whether
or not histories share a representative. With identical constant
initializers, all aliased histories hold the same visible value at every
read by induction. Eligibility must re-prove, per task, from generic IR
properties only: one-bit two-state history, identical known constant
initializer, single unconditional sampling site per history in the task, no
reads or writes outside this task, and compatible publication targets (the
representative must arm every consumer the aliased histories armed — in this
class the only consumer is the sampling task itself). Random initializers,
mixed event values or polarities, observed/signed histories, and any external
access fall back to the current emission. This node changes history
ownership in compute tasks; it does not touch guards, DPI behavior, sampling
order, or publication timing.

Exploratory local target: 4-8% total Host-time reduction. Bounds from the
profile: the helper's compute-side share is roughly 7% of runtime and
eligible sample calls should collapse by about two orders of magnitude
(~500 → ~1 per task per eval); the pending-record reduction additionally
relieves part of the 5.03% publication share. Falsification criteria:
eligibility covers only a negligible fraction of the 13,763 sites; or the
change is sound but the measured benefit against a matching-source control
is within noise / below the standing >3% gate. At most two refinements of
this mechanism are allowed; a different core mechanism would be a new node.

## Baseline and gates recorded before execution

- Control: the accepted edge-snapshot executable
  (`ptmp/edge_snapshot_20260910_01/flow`, wolvrix `c8b8676`), whose archived
  unprofiled candidate pair is 217.336 / 214.007 s, mean **215.6715 s**.
  A fresh isolated local control is run before any candidate; a final
  control is allowed to resolve drift.
- Preselected simulation stop-loss: 1.5 × 215.6715 = **323.50725 s**
  process-group KILL, applied to every run including controls, selected
  before any run of this node.
- Full SV generation and C++ compilation each have a **1800 s** KILL
  deadline; resume-from-IR is disabled for the candidate generation.
- Any TIMEOUT_KILLED, REGRESSION_KILLED, non-zero exit, crash, assertion,
  or NEMU mismatch marks the run INVALID, rejects this node, and ends its
  performance experiments.
- Acceptance requires: focused emitter tests passing; both build gates;
  two independent candidate 50k runs plus control(s) with NEMU PASS and the
  exact accepted endpoint (73,580 instructions, cycleCnt 49,996, terminal PC
  0x80001312, guest cycles 50,001); and Host-time improvement beyond the
  standing >3% gate against the local control, beyond observed noise.
- Fixed configuration (rechecked at entry): XiangShan
  `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`; CoreMark SHA-256
  `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`; top
  SimTop, DIFFTEST/NEMU; 50,000 cycles; CPU 2 via taskset; explicit
  `XS_EMU_THREADS=1`; waveform/commit/RAM trace off; 32 compile jobs;
  gsim 20.640 s reference reused unchanged.
- Temporary artifacts under `ptmp/compute_history_20260911_01/`. Frozen GRH,
  GRH passes, XiangShan, and workload sources remain untouched; no module
  names are used as triggers.

## IMPLEMENTED

The CPU emitter gains `planComputeSharedHistories()`
(`wolvrix/lib/grhsim/backend/cpu_emit.cpp`), invoked after the existing
commit-side planner. It groups event histories of `core.dpi.call` and
`core.system.task` ops inside ActivityDrivenCompute tasks by
(unit, event value, history state type, constant initializer). A history is
eligible only when all of the following hold, from generic IR/layout/schedule
properties: exactly one object reference in the whole model (total privacy),
exactly one constant `core.init.const` initializer (no random initialization),
one-bit two-state logic whose state type equals the event value type with a
one-byte layout slot, projected with a nonempty publication target span, and
not already batched or aliased. Within a group, aliases are added only when
the candidate's publication target span is identical to the representative's
(same activate/arm entries), so a change to the representative wakes exactly
what each member would have woken. Grouping is per scheduler unit because all
ops in one unit sample under the same active-word bit; histories in different
units of the same task are never merged, since their sampling conditions can
diverge. Guards keep reading visible state through the existing alias
resolution (`object()`), and `stage()` already skips aliased members, so only
the representative's unconditional sample remains per group. No runtime
helper, pending ABI, schedule, or GRH change is involved; polarity needs no
key because value sequences are identical across polarities. Diagnostics gain
`compute_history_aliases=` / `compute_history_alias_units=` counters (named
to avoid the existing `history_shared_states` substring checks).

`WOLF_ENV_SOURCED=1 make --no-print-directory test_grhsim_cpu_emit` exited 0;
CTest passed in **66.63 seconds**. The new `testComputeHistorySharing` fixture
builds twelve clock-posedge `display` system tasks with private one-bit
histories (eight zero-initializer, two one-initializer, one history shared by
two calls). The mapper spreads them over six same-task units; assertions
verify exactly five same-unit aliases and five units (no cross-unit or
cross-initializer merging), all twelve guarded calls still emitted, exactly
seven remaining sample sites (five representatives plus the shared history's
two unconditional samples). Existing scoreboards passed unchanged, including
the CDC fixture's shared-event-history coverage check (10,756 samples, 1,182
simultaneous edges, 20 async resets), dual RAM (9,731 samples), history
scoreboards, and the commit-side sharing/edge-snapshot assertions. One
refinement was needed during testing: the new diagnostic fields were renamed
so they cannot collide with substring eligibility checks on
`history_shared_states=0 ` in the CDC fixture. This is the final test
version; no semantic change was needed after the first passing run.

## Generation, Compilation and Coverage

Full SV generation (fresh directory, resume disabled) used the established
command template with `RUN_ID=compute_history_20260911_01_generate`; it exited
0 with Make wall **609.89 s** (user 704.91, sys 24.51), PASS against the
1800 s gate. The flat GRH and read-argument files are byte-identical to the
accepted edge-snapshot control, and the fresh-session GrhSIM IR store/load
round-trip is stable. No GRH transformation, XiangShan, or workload source
was changed.

32-job compilation (`RUN_ID=compute_history_20260911_01_compile`, clang++
C++20 -O3) exited 0 with a linked emu in **254.56 s** (user 6101.97, sys
454.19), PASS against the 1800 s gate. The candidate executable is
125,563,464 bytes vs the control's 126,255,688; size is not an instruction
count but shows the emission change survives compilation.

Static source comparison (`make analyze_grhsim_history_sharing`, baseline
`ptmp/edge_snapshot_20260910_01/flow/model`, candidate this node's model):

| Static measure | Control | Candidate |
|---|---:|---:|
| Bool initializer assignments | 399,130 | 399,130 |
| Unique initialized bool addresses | 113,717 | 100,335 |
| `cpu_write_scalar<bool>` call sites | 16,255 | **2,873** |
| History batch sites | 212 | 212 |
| Cached commit edge predicates / uses | 496 / 226,510 | 496 / 226,510 |
| Changed tasks (of 5,595) | — | 51 |
| Bytes in changed task files | 20,903,160 | 19,176,579 |
| Total C++ bytes | 1,272,717,975 | 1,270,991,394 |

**13,382** private compute-side histories were redirected to representatives
(−82.33% of all scalar staging call sites), across 51 changed compute tasks —
the assert/DPI class targeted by the hypothesis. The commit-side measures
(snapshot count/uses, batch sites) are exactly unchanged, confirming the
mechanism touches only compute tasks. Static counts are emission-site
observations, not runtime frequency; the simulation below is the benefit
measurement.

## Simulation

All builds and the read-only analyzer finished before any simulation; runs
were sequential and isolated. Template (per label/run_id/flow):

```bash
WOLF_ENV_SOURCED=1 XS_EMU_THREADS=1 EMU_PHASE_TIMING=0 EMU_RUNTIME_PROFILE=0 make --no-print-directory run_xs_wolf_grhsim_ir_emu RUN_ID="$run_id" XS_GRHSIM_IR_BUILD="$flow" XS_LOG_DIR=ptmp/compute_history_20260911_01/logs XS_SIM_MAX_CYCLE=50000 XS_EMU_CPU=2 XS_PROGRESS_EVERY_CYCLES=0 XS_WAVEFORM=0 XS_COMMIT_TRACE=0 XS_RAM_TRACE=0 XS_WAVEFORM_PATH= WOLVRIX_GRHSIM_WAVEFORM=0 XS_EMU_PREFIX="timeout --signal=KILL 323.50725s /usr/bin/time -p -o $PWD/ptmp/compute_history_20260911_01/$label.time taskset -c 2 stdbuf -oL -eL" > "ptmp/compute_history_20260911_01/$label.log" 2>&1
```

| label | run_id | flow |
|---|---|---|
| control | compute_history_20260911_01_control | ptmp/edge_snapshot_20260910_01/flow |
| run1 | compute_history_20260911_01_run1 | ptmp/compute_history_20260911_01/flow |
| run2 | compute_history_20260911_01_run2 | ptmp/compute_history_20260911_01/flow |

| Run | Host s | Exec wall s | Exit | NEMU / endpoint | Stop-loss |
|---|---:|---:|---:|---|---|
| Control (edge-snapshot, isolated) | 213.636 | 213.67 | 0 | PASS / exact | NONE |
| Candidate 1 | 182.379 | 182.41 | 0 | PASS / identical | NONE |
| Candidate 2, independent process | 182.451 | 182.48 | 0 | PASS / identical | NONE |

Every run reports 73,580 instructions, cycleCnt 49,996, terminal PC
0x80001312, guest cycles 50,001, with no mismatch, ABORT, bad trap,
assertion, or segmentation fault. The preselected 323.50725 s deadline was
never approached. Candidate mean is **182.415 s**; the two candidates differ
by 0.072 s (0.0395% of the mean). The local control is 0.9438% below the
archived 215.6715 s mean, showing small session drift. Primary comparison:
`(1 - 182.415 / 213.636) * 100 = ` **14.6141%** Host-time reduction against
the contemporaneous isolated control; against the archived control mean it
would be 15.4200%. The margin exceeds the >3% gate by nearly fivefold and
the candidate spread is two orders of magnitude smaller than the gain, so no
final control was needed to resolve drift. No profiler or waveform was
enabled; no failed run was used as evidence.

## Final Decision and Archive

**ACCEPTED.** Compute-task private event history sharing produces a
reproducible local benefit far beyond noise: two independent 50k NEMU PASS
runs at 182.379 / 182.451 s against an isolated same-session control at
213.636 s (−14.6141%), with byte-identical flat GRH, stable IR round-trip,
full generation 609.89 s and 32-job compilation 254.56 s (both under the
1800 s gates), and focused emitter tests including a new same-unit lockstep
fixture passing in 66.63 s. Statically, 13,382 redundant private histories
across 51 compute tasks collapsed to per-unit representatives
(16,255 → 2,873 staging call sites); the runtime result is consistent with
removing their per-eval slow-path staging and publish records. This is a
local node result, not the ~40 s objective: the new best mean is
**182.415 s**, still 142.415 s above it. The gain exceeds the 4-8%
exploratory estimate; no post-change profile separates how much came from
staging-call elimination versus publication relief.

The retained change touches only the CPU emitter, its focused tests, and the
node documentation: wolvrix `lib/grhsim/backend/cpu_emit.cpp` (new compute
sharing planner plus two diagnostic counters) and
`tests/grhsim/test_cpu_emit.cpp` (new fixture), committed as one submodule
commit; the root commit records this report, the updated goal index, and the
submodule pointer. Frozen GRH, GRH passes, XiangShan, and workload sources
are unchanged; generated models, logs, and binaries stay untracked under
`ptmp/`.

Search review: three accepted mechanisms now compose (shared commit history,
commit edge snapshots, compute history sharing). Remaining bounded
directions from the residual-hotspots evidence: the un-shared commit outlier
class (task 5141 at 2.2560%, bound ~3-4%), the publication path (~5%), and
the guard machinery inside assert tasks (per-task invariant event loads).
Repeating this sharing family further has no remaining coverage of
consequence: commit and compute histories are now both deduplicated.
