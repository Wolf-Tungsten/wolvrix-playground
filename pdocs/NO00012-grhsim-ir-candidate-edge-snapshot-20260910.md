# Commit Edge Snapshots

- Node: `edge_snapshot_20260910_01`
- Status: ACCEPTED
- Root baseline: `530863b`; wolvrix baseline: `2804734fcf690ee3be26a5abd848397c56e459a8`.

## Hypothesis

Compute each repeated edge predicate once per eligible commit task invocation.
The preceding shared-history optimization redirects histories but still emits
the same visible-history and event loads before every state write. Calls that
stage state or activate consumers may prevent the C++ compiler from proving
those loads invariant. Explicit boolean snapshots express the IR invariant and
remove redundant edge evaluation across intervening writes without reordering
those writes. This node changes predicate evaluation, not history ownership.

The existing [phase profile](NO00009-grhsim-ir-phase-profile-20260910.md) attributed
38.7506% of eval time to commit. That profile predates history sharing and is
only a search clue, not a current bound. In the accepted generated model, task
5121 repeats two identical event/history terms before thousands of writes.
Task identities are observations only; eligibility must be semantic. The
exploratory target is a further 3-10% runtime reduction. Even perfect removal
cannot remove the payload writes, compute, or publication costs. Static coverage
and final source size will establish how much code this actually reaches.

Only domain-gated tasks already proven eligible for private history sharing
participate. Every history has one constant initializer, one sampling owner,
and no visible writes or observers inside commit; event operands retain their
pre-commit boundary snapshot. Cache keys include event identity, resolved history
identity, and edge polarity. Distinct initial histories and mixed polarities
must remain distinct. Cache lifetime is one task invocation, including each
convergence round. Sampling and publication timing remain unchanged.

## Method and Gates

Reuse the accepted shared-history executable as the exact-source control;
its archived 50k Host times are 272.706 and 265.188 seconds, mean 268.947.
Preselect that mean for a 403.4205-second simulation process-group deadline
(1.5x). Full SV generation and compilation each have a 1800-second KILL
deadline. Any timeout, invalid run, mismatch or regression stop rejects this
node and ends performance experiments. No results are prefilled.

Keep XiangShan revision, CoreMark binary, SimTop, NEMU, CPU 2, 50,000 cycles,
explicit `XS_EMU_THREADS=1`, and disabled waveform/trace/profiling as in the
[accepted baseline](NO00011-grhsim-ir-candidate-shared-history-20260910.md). Recheck input
identities before execution. Compile with all 32 available CPUs. Reuse gsim
20.640 seconds; no gsim rerun is justified by an unchanged configuration.

First run `make test_grhsim_cpu_emit`, covering distinct initial histories,
positive/negative edges, derived clocks, reset, memory writes, and fallback.
Then generate from full SV into a fresh directory, compile, and run an isolated
control and two independent candidates sequentially. Full-generation timing
starts at Make and ends at complete C++/Makefile output; compilation ends at
the linked emu. Simulation timing wraps emu only. Acceptance requires NEMU
PASS with the baseline endpoint, both build gates, independent repeat, and
greater than 3% improvement beyond observed noise. An additional control is
allowed to resolve drift; at most two implementation refinements are allowed.

All temporary artifacts belong under `ptmp/edge_snapshot_20260910_01/`.
Final measurements, commands, limitations and decision are recorded below.

## IMPLEMENTED

The CPU emitter records task IDs that passed the existing whole-task sharing
proof. Before the payload sequence it groups predicates by structured IR keys,
emits one boolean for groups with at least two uses, and passes that boolean
to regWrite, memWrite, memFill and memWriteSeq emission. Singleton guards remain
inline. The snapshots are after the existing early exits, and before all
payload writes. No runtime helper or helper ABI changes are involved.

`WOLF_ENV_SOURCED=1 make --no-print-directory test_grhsim_cpu_emit` exited 0;
CTest passed in **66.69 seconds**. New assertions check private eligibility,
fallback for observed/signed histories, exactly `count-2` uses for the repeated
predicate in the mixed-initializer fixture, and actual consumption of the
snapshot in all four write forms. Existing executable scoreboards exercise
positive/negative and derived clocks, reset, distinct initial histories, sparse
layouts, memory operations, CDC and scalar/wide behavior under sanitizers.
The CDC scoreboard passed 10,756 samples, including 1,182 simultaneous edges
and 20 async resets; dual RAM passed 9,731 samples, 293 simultaneous edges and
15 async resets. History scoreboards passed 4,632 samples per executable case.

The [source analyzer](../scripts/grhsim_history_sharing_stats.py) now counts
snapshot declarations and independently verifies their actual guard-use count
against each emitter marker. It was exercised through
`make analyze_grhsim_history_sharing` on the generated compact fixture: two
tasks, one snapshot and 30 uses, with the two distinct-initializer predicates
left inline. This is a static measurement, not a runtime benefit claim.

Input identities were rechecked: XiangShan
`4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`, CoreMark SHA-256
`c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`,
NEMU shared library SHA-256
`094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`.
`nproc` reports 32. Root and submodule worktrees were clean before this node.

Full generation command (fresh output directory, no resumed IR):

```bash
TMPDIR="$PWD/ptmp/edge_snapshot_20260910_01/tmp" CCACHE_DIR="$PWD/ptmp/edge_snapshot_20260910_01/ccache" PIP_CACHE_DIR="$PWD/ptmp/edge_snapshot_20260910_01/pip-cache" CMAKE_BUILD_PARALLEL_LEVEL=32 WOLF_ENV_SOURCED=1 /usr/bin/time -p -o ptmp/edge_snapshot_20260910_01/generation.time timeout --signal=KILL 1800s make --no-print-directory xs_wolf_grhsim_ir PYTHON="$PWD/.venv/bin/python" RUN_ID=edge_snapshot_20260910_01_generate XS_GRHSIM_IR_BUILD=ptmp/edge_snapshot_20260910_01/flow XS_LOG_DIR=ptmp/edge_snapshot_20260910_01/logs XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=ptmp/edge_snapshot_20260910_01/flow/model XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0 XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0 > ptmp/edge_snapshot_20260910_01/generation.log 2>&1
```

## Generation, Compilation and Coverage

Generation exited 0 with Make wall **611.87 s**, user 712.38, sys 25.65.
The internal script took 598.851 s; only the outer Make timing is the gate.
Flat GRH and read arguments compare byte-identical to the accepted control.
Fresh-session GrhSIM IR load/store round-trip passed. No GRH transformation
or workload source was changed.

```bash
TMPDIR="$PWD/ptmp/edge_snapshot_20260910_01/tmp" CCACHE_DIR="$PWD/ptmp/edge_snapshot_20260910_01/ccache" WOLF_ENV_SOURCED=1 /usr/bin/time -p -o ptmp/edge_snapshot_20260910_01/compile.time timeout --signal=KILL 1800s make --no-print-directory xs_wolf_grhsim_ir_build_emu RUN_ID=edge_snapshot_20260910_01_compile XS_GRHSIM_IR_BUILD=ptmp/edge_snapshot_20260910_01/flow XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=ptmp/edge_snapshot_20260910_01/flow/model VM_BUILD_JOBS=32 XS_EMU_THREADS=1 EMU_THREADS=1 WOLVRIX_GRHSIM_WAVEFORM=0 > ptmp/edge_snapshot_20260910_01/compile.log 2>&1
```

Compilation exited 0 with a linked emu in **255.12 s**, user 6082.54,
sys 458.19, using clang++ C++20 -O3 and 32 jobs. Both 1800 s gates pass.

The complete source comparison command was:

```bash
WOLF_ENV_SOURCED=1 make --no-print-directory analyze_grhsim_history_sharing PYTHON="$PWD/.venv/bin/python" GRHSIM_HISTORY_BASELINE=ptmp/shared_history_20260910_01/flow/model GRHSIM_HISTORY_CANDIDATE=ptmp/edge_snapshot_20260910_01/flow/model > ptmp/edge_snapshot_20260910_01/static.log 2>&1
```

| Static measure | Control | Candidate |
|---|---:|---:|
| Total task files | 5,595 | 5,595 |
| Bool initializer assignments | 399,130 | 399,130 |
| Unique initialized bool addresses | 113,717 | 113,717 |
| Bool stage call sites | 16,255 | 16,255 |
| History batch sites | 212 | 212 |
| Cached edge predicates | 0 | 496 |
| Payload references to cached predicates | 0 | 226,510 |
| Total C++ bytes | 1,294,071,427 | 1,272,717,975 |
| Bytes in the 496 changed task files | 152,024,304 | 130,670,852 |

All 496 eligible tasks have one repeated predicate. This removes 226,014
repeated evaluations at static emission sites and 21,353,452 source bytes,
while preserving all state/history staging sites. Static counts do not measure
runtime frequency or compiler elimination. The read-only analyzer briefly
overlapped the start of control execution; a final control will check drift
and provide a comparison without that overlap if needed for acceptance.

Compiled output also changed: task 5121's object file decreased from 542,344
to 389,232 bytes; the complete emu decreased from 131,277,192 to 126,255,688
bytes. These sizes include object/executable metadata and are not instruction
counts. They establish that the emitted simplification survives compilation,
but cannot establish execution-time savings by themselves.

## Simulation

Run the existing shared-history control, then two new candidate processes
sequentially. Each uses the preselected 403.4205 s limit. The exact template is:

```bash
WOLF_ENV_SOURCED=1 XS_EMU_THREADS=1 EMU_PHASE_TIMING=0 EMU_RUNTIME_PROFILE=0 make --no-print-directory run_xs_wolf_grhsim_ir_emu RUN_ID="$run_id" XS_GRHSIM_IR_BUILD="$flow" XS_LOG_DIR=ptmp/edge_snapshot_20260910_01/logs XS_SIM_MAX_CYCLE=50000 XS_EMU_THREADS=1 XS_EMU_CPU=2 XS_PROGRESS_EVERY_CYCLES=0 XS_WAVEFORM=0 XS_COMMIT_TRACE=0 XS_RAM_TRACE=0 XS_WAVEFORM_PATH= WOLVRIX_GRHSIM_WAVEFORM=0 XS_EMU_PREFIX="timeout --signal=KILL 403.4205s /usr/bin/time -p -o $PWD/ptmp/edge_snapshot_20260910_01/$label.time taskset -c 2 stdbuf -oL -eL" > "ptmp/edge_snapshot_20260910_01/$label.log" 2>&1
```

| label | run_id | flow |
|---|---|---|
| control | edge_snapshot_20260910_01_control | ptmp/shared_history_20260910_01/flow |
| run1 | edge_snapshot_20260910_01_run1 | ptmp/edge_snapshot_20260910_01/flow |
| run2 | edge_snapshot_20260910_01_run2 | ptmp/edge_snapshot_20260910_01/flow |
| control-final | edge_snapshot_20260910_01_control_final | ptmp/shared_history_20260910_01/flow |

Host time comes from emu. Wall time wraps emu plus taskset/stdbuf startup and
excludes Make setup. Every run must exit 0 with NEMU enabled, no failure,
73,580 instructions, cycleCnt 49,996, terminal PC 0x80001312 and 50,001 guest
cycles. No profiler or waveform is enabled.

Control completed with exit 0, NEMU enabled and no mismatch/assertion/failure:
Host **271.579 s**, wall 271.61, user 271.52, sys 0.05. All endpoint counters
match the expected values above. This local control was observed before starting
candidate run1; the preselected 403.4205 s deadline remains unchanged.

Candidate run1 exited 0: Host **217.336 s**, wall 217.37, user 217.29,
sys 0.05. NEMU remained enabled without mismatch or failure, and all four
endpoint values match the control. The single-run reduction against the local
control is **19.9732%**. Independent run2 and a final control are required
before acceptance; the latter removes the first control's analyzer overlap
and tests temporal drift. No performance result is inferred for those runs.

Candidate run2 exited 0: Host **214.007 s**, wall 214.04, user 213.97,
sys 0.04. NEMU again passed with exactly the same architectural endpoint.
Both candidates ran to the full 50k limit without a stop-loss. Their mean is
**215.6715 s**, with a 3.329 s range (1.5436% of the mean). The implementation
was unchanged after the focused test; there were no refinement attempts.
The final control was then run to establish the final comparison.

Final control exited 0 with NEMU enabled and no mismatch, assertion, crash or
stop-loss: Host **270.194 s**, wall 270.22, user 270.14, sys 0.05. It reproduces
the same endpoint and ran without the source analyzer. Final results:

| Run | Host s | Execution wall s | Exit | NEMU / endpoint |
|---|---:|---:|---:|---|
| Control, brief analyzer overlap at start | 271.579 | 271.61 | 0 | PASS / identical |
| Candidate 1 | 217.336 | 217.37 | 0 | PASS / identical |
| Candidate 2, independent process | 214.007 | 214.04 | 0 | PASS / identical |
| Final control, no analyzer overlap | 270.194 | 270.22 | 0 | PASS / identical |

The primary performance comparison excludes the first control's overlap:
`(1 - 215.6715 / 270.194) * 100 = 20.1790%` reduction in Host time.
Using both controls' mean, 270.8865 s, gives 20.3831%. Even the slower candidate
against the faster control gives 19.5630%, comfortably beyond the 3% gate.
The controls differ by 1.385 s and candidates by 3.329 s; exact percentages
remain sensitive to host drift, but neither observed range overlaps.

## Final Decision and Archive

**ACCEPTED.** Repeated edge snapshots produce reproducible local benefit.
The complete SV route passed in 611.87 s, compilation passed in 255.12 s,
focused semantic and sanitizer scoreboards passed, and two independent 50k
NEMU runs match the expected architectural endpoint. All four simulations
completed before the fixed 403.4205 s deadline. No stages were omitted,
no failed performance run was used, and no implementation retry was needed.

This is a local performance result, not completion of the approximately 40 s
optimization program: the candidate mean remains 175.6715 s above that target.
It is stronger than the initial 3-10% estimate. Source/object shrinkage and the
timings are consistent with avoiding repeated loads and reducing code footprint;
there is no post-change profile that separates those effects or establishes a
new compute/commit percentage. No broader mechanism is claimed from this data.

The retained change touches only the CPU emitter, backend documentation and
focused emitter assertions in wolvrix. The root archive extends the existing
read-only analyzer and updates this report and the goal index. Frozen GRH,
GRH passes, XiangShan and workload sources remain unchanged. Generated sources,
objects, binaries, logs and profiles stay under `ptmp/` and are not committed.
Retained implementation: wolvrix commit `c8b8676` (`perf(grhsim): reuse private
commit edge predicates`). The root archive containing this report records that
submodule pointer together with the analyzer and goal index. Each repository
has one final node commit; no intermediate implementation commits were made.

Search review: task-level private-history sharing and predicate reuse compose
successfully. Ready queues/indirect dispatch and frame-zeroing removal are
previously rejected directions; small activity-mask packing had insufficient
coverage. Future nodes should measure the new residual compute, payload commit
and publication costs before selecting another mechanism. A broad mechanism
for repeated compute or state activation is more promising than repeatedly
tuning this predicate cache. No next node is started in this execution.
