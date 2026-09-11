# Shared Commit Event Histories

- Node: `shared_history_20260910_01`
- Status: ACCEPTED
- Root baseline: `719066a`; wolvrix baseline: `93d55ae7d53d592c5d20e5f83863f1241fb0fcbb`.

## Hypothesis and Gates

Private event histories sampled unconditionally by the same commit task can use one
representative per event value, type, and identical constant initializer. This removes
redundant history staging, publication, and stability scanning. The trigger uses only
IR ownership, event identity, initialization, and publication targets. No GRH pass,
frozen GRH, XiangShan source, or workload is changed.

The [function profile](NO00010-grhsim-ir-task-hotspots-20260910.md) measured commit tasks at
35.6047% of flat samples and the bool staging helper at 6.2184%; the independent
[phase profile](NO00009-grhsim-ir-phase-profile-20260910.md) measured commit at 38.7506%
and publication at 5.0388% of eval time. These overlapping measurements are not
additive. Generated tasks contain thousands of histories for very few events.
The hypothesis targets repeated work across commit tasks, not a hot module name.
A 5-20% total runtime reduction is the exploratory local target; removing all
commit/publication work would bound the opportunity at about 44% of eval time,
and this mechanism can remove only part of it. Static sharing without reproducible
runtime benefit is insufficient for acceptance.

Eligibility requires a one-bit unsigned two-state private history, a known constant
initializer, an unconditional sampling operation in a domain-gated commit task, and
exactly one publication target: that task's event domain. Histories in different
tasks, with different initial values, or with external reads/writes cannot share.
Visible history remains unchanged until publication; guards must not read pending
shadow values. Every representative retains the original domain wakeup.

Reject on semantic failure, either full generation/compile reaching 1800 seconds,
or simulation reaching the preselected conservative deadline 419.92275 seconds
(1.5 times archived best mean 279.9485 seconds). No further performance experiment
is allowed after a stop-loss. At most two refinements of this mechanism are allowed.
Acceptance requires focused semantic tests, full SV generation and compilation
each below 1800 seconds, two valid 50k candidate runs, and benefit beyond observed
noise against a matching-source control. An early evidence-based rejection is valid.
During validation the user explicitly lowered the performance acceptance threshold
to **greater than 3%**. Correctness, independent-repeat, noise, and build gates stay
in force. The original 5-20% hypothesis range above is retained as the prior estimate.

## Baseline Setup

The worktrees were clean at entry. XiangShan revision is
`4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`; CoreMark binary SHA-256 is
`c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`,
both rechecked. Host has 32 available CPUs. Use top SimTop, DIFFTEST/NEMU,
50,000 cycles, CPU 2, explicit `XS_EMU_THREADS=1`, and no waveform, commit/RAM
trace, runtime profiling, or phase profiling. Compile with 32 jobs.

Reuse gsim 20.640 seconds without rerunning. The current source's archived
unprofiled control is 287.162 seconds. A fresh run of that same existing executable
will establish a contemporaneous control; its already validated full generation
and compilation took 606.29/477.30 seconds. Candidate gates must use a new full SV
route, never a resumed IR checkpoint. Each experiment has a separate RUN_ID.
Timing wraps the complete Make generation/build target; simulation timing wraps
only the emu execution prefix. GNU timeout with KILL covers each process group.

Temporary logs and outputs are under `ptmp/shared_history_20260910_01/`.
Commands and measured outcomes will be recorded below as stages finish.

## IMPLEMENTED

The CPU emitter plans per-task aliases before history batches. Only tasks whose
entire history set satisfies the eligibility rules participate. Guards and scan
addresses resolve aliases; redundant stage calls are omitted. Existing state IDs,
IR layout, schedule, pending ABI, and arena allocation sizes remain unchanged.
Identical constant initializers may write the same representative repeatedly;
random initialization is excluded, so the RNG sequence is preserved. Stability
scans deduplicate representative addresses. No wide helper ABI changes were made.

`WOLF_ENV_SOURCED=1 make --no-print-directory test_grhsim_cpu_emit` exited 0;
CTest passed in 69.45 seconds. Existing semantic scoreboards cover distinct initial
histories, four resets, sparse layouts, derived clocks, regWrite/memWrite/memFill/
memWriteSeq, observed and signed fallback, plus shared/written history fallback.
The sharing count assertion proves 64 private histories with two event values and
two distinct initializers per event become four representatives (60 aliases).
CDC passed 10,756 samples including 1,182 simultaneous edges and 20 async resets;
dual RAM passed 9,731 samples including 293 simultaneous edges and 15 resets.
Wide, scalar, external-call, and phase-profile regressions also passed.
After adding an explicit random-initializer sharing rejection, the same Make
target passed again in 72.17 seconds. No emitter change was needed after the
first passing run; this is the final test version used for the node.

The preliminary control finished at Host 290.129 seconds, with NEMU enabled and
the expected 73,580 instructions / cycleCnt 49,996 / PC 0x80001312 / guest cycles
50,001. Its interval overlapped the focused test compilation, so it is excluded
from the performance decision. An isolated control is required after builds end.

## Full Generation

Full SV generation starts with a new output directory and resume disabled. The
timer includes Make setup and py_install, and the 1800-second deadline kills the
entire command group. The temporary path identifies configuration, not a formal
evidence dependency.

```bash
TMPDIR="$PWD/ptmp/shared_history_20260910_01/tmp" CCACHE_DIR="$PWD/ptmp/shared_history_20260910_01/ccache" PIP_CACHE_DIR="$PWD/ptmp/shared_history_20260910_01/pip-cache" CMAKE_BUILD_PARALLEL_LEVEL=32 WOLF_ENV_SOURCED=1 /usr/bin/time -p -o ptmp/shared_history_20260910_01/generation.time timeout --signal=KILL 1800s make --no-print-directory xs_wolf_grhsim_ir PYTHON="$PWD/.venv/bin/python" RUN_ID=shared_history_20260910_01_generate XS_GRHSIM_IR_BUILD=ptmp/shared_history_20260910_01/flow XS_LOG_DIR=ptmp/shared_history_20260910_01/logs XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=ptmp/shared_history_20260910_01/flow/model XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0 XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0 > ptmp/shared_history_20260910_01/generation.log 2>&1
```

Generation exited 0 in **615.95 seconds** (user 709.05, sys 26.24), including
py_install. Internal script time was 603.102 seconds. Full flat GRH and read-argument
files both compare byte-identical to the validated phase-profile control. Fresh
load/store GrhSIM IR round-trip was stable. Generation gate: PASS, no stop-loss.

The read-only [source comparison](../scripts/grhsim_history_sharing_stats.py) runs
through `make analyze_grhsim_history_sharing` with `GRHSIM_HISTORY_BASELINE` and
`GRHSIM_HISTORY_CANDIDATE` pointing to the control/candidate model directories.
It checks matching task inventories and initializer counts, then counts bool
initializer addresses, emitted staging sites, batch sites, and source sizes:

| Static measure | Control | Candidate |
|---|---:|---:|
| Bool initializer assignments | 399,130 | 399,130 |
| Unique initialized bool addresses | 399,130 | 113,717 |
| Bool staging call sites | 21,073 | 16,255 |
| History batch sites | 6,910 | 212 |
| Total C++ source bytes | 1,298,657,451 | 1,294,071,427 |
| Changed task source bytes | 156,610,328 | 152,024,304 |

Of 5,595 tasks, **496** changed. Initializer addresses demonstrate **285,413**
eliminated private history locations (71.5088% of all bool initializers, which also
include non-history states). This does not shrink the allocated arena. Source
shrinks by 4,586,024 bytes, only 0.3531% overall: payload operations remain.
Batch-site and staging-site counts are static syntax counts, not sample counts.
For example, task 5121 previously scanned 8,192 histories in two event groups;
its candidate scan uses two single-byte representatives and two scalar samples.
Other tasks fail whole-task eligibility and retain their original path, including
profile-leading task 5141. These task IDs describe observations, not selection rules.

## Compilation

```bash
TMPDIR="$PWD/ptmp/shared_history_20260910_01/tmp" CCACHE_DIR="$PWD/ptmp/shared_history_20260910_01/ccache" WOLF_ENV_SOURCED=1 /usr/bin/time -p -o ptmp/shared_history_20260910_01/compile.time timeout --signal=KILL 1800s make --no-print-directory xs_wolf_grhsim_ir_build_emu RUN_ID=shared_history_20260910_01_compile XS_GRHSIM_IR_BUILD=ptmp/shared_history_20260910_01/flow XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=ptmp/shared_history_20260910_01/flow/model VM_BUILD_JOBS=32 XS_EMU_THREADS=1 EMU_THREADS=1 WOLVRIX_GRHSIM_WAVEFORM=0 > ptmp/shared_history_20260910_01/compile.log 2>&1
```

The build uses `clang++ -std=c++20 -O3` and the existing generated-model Makefile.
It exited 0 in **246.50 seconds** (user 6247.58, sys 464.63), producing the linked
emu executable. Compilation gate: PASS, no stop-loss. The lower time than archived
477.30 seconds is not attributed solely to this change: compiler cache, filesystem
cache, and host conditions were not controlled for a compile-speed claim.

## Simulation Method

After all build/test processes ended, run an isolated current-source control and
two candidate processes sequentially. Their input and trace settings are identical.
Use the same preselected 419.92275-second kill limit for every run, including the
control. The control comparison is selected before candidate execution. If benefit
is near noise, a final control may check temporal drift. No profiler is loaded.

The exact run command is the following template (substitute the table values):

```bash
WOLF_ENV_SOURCED=1 XS_EMU_THREADS=1 EMU_PHASE_TIMING=0 EMU_RUNTIME_PROFILE=0 make --no-print-directory run_xs_wolf_grhsim_ir_emu RUN_ID="$run_id" XS_GRHSIM_IR_BUILD="$flow" XS_LOG_DIR=ptmp/shared_history_20260910_01/logs XS_SIM_MAX_CYCLE=50000 XS_EMU_THREADS=1 XS_EMU_CPU=2 XS_PROGRESS_EVERY_CYCLES=0 XS_WAVEFORM=0 XS_COMMIT_TRACE=0 XS_RAM_TRACE=0 XS_WAVEFORM_PATH= WOLVRIX_GRHSIM_WAVEFORM=0 XS_EMU_PREFIX="timeout --signal=KILL 419.92275s /usr/bin/time -p -o $PWD/ptmp/shared_history_20260910_01/$label.time taskset -c 2 stdbuf -oL -eL" > "ptmp/shared_history_20260910_01/$label.log" 2>&1
```

| label | run_id | flow |
|---|---|---|
| control | shared_history_20260910_01_control | ptmp/phase_profile_50k_20260910_01/flow |
| control-isolated | shared_history_20260910_01_control_isolated | ptmp/phase_profile_50k_20260910_01/flow |
| run1 | shared_history_20260910_01_run1 | ptmp/shared_history_20260910_01/flow |
| run2 | shared_history_20260910_01_run2 | ptmp/shared_history_20260910_01/flow |
| control-final | shared_history_20260910_01_control_final | ptmp/phase_profile_50k_20260910_01/flow |

The preliminary `control` row records the earlier overlapping run, not a second
isolated control. Wall timing includes taskset/stdbuf startup, excludes Make setup,
and is reported separately from emulator Host time. Both backends run NEMU with
the same reference library (SHA-256
`094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`).

The isolated control exited 0 at Host **294.208 seconds**, wall 294.24, user
294.15, sys 0.04. NEMU was enabled, with no mismatch/assertion/ABORT/bad trap or
segmentation failure. Endpoint: 73,580 instructions, cycleCnt 49,996, PC
0x80001312, guest cycles 50,001. This is the fixed local comparison selected
before starting candidate run1; retain the stricter 419.92275-second stop-loss.
Its difference from archived 287.162 seconds (+2.4536%) demonstrates temporal
variation and motivates comparison against this local control.

Candidate run1 and the independent run2 both exited 0, passed NEMU, and reproduced
the exact same endpoint: 73,580 instructions, cycleCnt 49,996, PC 0x80001312,
guest cycles 50,001. Host times were **272.706 / 265.188 seconds**, mean
**268.947 seconds**; execution walls were 272.74 / 265.22 seconds. No mismatch,
ABORT, bad trap, assertion, segmentation failure, or stop-loss occurred. Because
candidate times drifted by 7.518 seconds and the historical baseline range overlaps
run1, a final isolated control was started to distinguish a real benefit from host
drift.

The final control exited 0 with the same endpoint and no diagnostic failure: Host
**290.017 seconds**, wall 290.05, user 289.95, sys 0.06. The two valid controls
average **292.113 seconds**. Candidate mean change is
`(268.947 / 292.113 - 1) * 100 = -7.9303%`; against the final control alone it is
`-7.2651%`. Both exceed the user-adjusted 3% acceptance threshold. Candidate run1
and run2 remain 2.59% apart, so the exact gain is noisy; the sign and margin over
3% persist against both controls. The 1.5x stop-loss was not reached.

## Final Decision

**ACCEPTED** for this node. Correctness is established by two independent 50k
NEMU PASS runs with identical architectural endpoints and by focused semantic
scoreboards. Complete SV generation (615.95 s) and C++ compilation (246.50 s)
both pass the 1800 s gates. Static source accounting shows 285,413 redundant
private history locations redirected to representatives and 496 changed tasks.
The two candidate runs provide reproducible benefit beyond the user-requested 3%
threshold against two isolated controls. The exact absolute 40-second goal remains
unmet; this node contributes a measured local improvement.

The retained implementation is the current wolvrix working-tree change. No GRH,
XiangShan, or workload source changed. Generated models, logs, binaries, profiles,
and waveforms remain temporary under `ptmp/` and are not archive inputs. Before
the node commit, stage the wolvrix submodule changes first, then the root changes,
including this report, the goal index, Make target, and analyzer script.
