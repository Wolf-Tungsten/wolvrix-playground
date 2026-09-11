# GrhSIM-IR Candidate: Elide Unchanged Scalar Shadow Writes

- Date: 2026-09-10
- Status: VALIDATED / LOWEST OBSERVED MEAN; absolute performance target unmet
- Root baseline: `92b03b1` (packed-guard screen archived)
- GrhSIM baseline: `c3dfad0cc19e29943b65d815ae180fdbd42f1bee`, clean worktree
- Candidate simulator implementation: GrhSIM commit `7b3432b` (parent `c3dfad0`)

## Problem, hypothesis, and control

The previous packed-guard screen found only six qualifying two-byte predicates, so this step examines state staging instead of refining that direction. The current IR emitter's typed `cpu_stage<T>` first copies the visible state into shadow and pushes a pending descriptor on the first write, then returns a reference for assignment. Even an unchanged write becomes dirty and later reaches `cpu_publish`'s runtime-size comparison.

The legacy emitter at the same GrhSIM revision already avoids this work: `apply_scalar_state_write_bool` and `apply_scalar_state_write_u8` select `shadowTouched ? shadowData : stateData`, compare the requested value or masked result with that effective value, and return before marking pending when equal. This is the performance and semantic reference for the candidate. It uses caller-owned storage and does not allocate a wide return value.

Hypothesis: apply this existing strategy to two-state scalar IR writes of at most 64 bits, including full assignments of event histories and masked register writes that currently use staging. Compare with the existing activity-guard baseline while preserving task order, shadow publication boundaries, projection/fanout activation, and memory behavior. Trigger only from op semantics, type/width, and write attributes; no module names or frozen GRH changes.

## Correctness boundary

Let visible value be V and dirty flag be D; the effective value is shadow S if D is set, otherwise V. Normalize and merge the requested write using that effective value. If unchanged, return. If changed and clean, enqueue exactly once; update S and leave V untouched until publication. If already dirty, update S without enqueueing again. Never cancel a pending record merely because S becomes equal to V: later writes and publication still follow the existing order.

Example: V=0, writes 1 then 0. The second write must compare against S=1 and update S to 0; a comparison against V alone would incorrectly skip it. A partial mask must preserve bits from the effective shadow, not stale visible state. Event sampling must remain outside the edge-taken branch where the current emitter places it. Batched histories, memory cells, wide values, and direct-commit states require their existing paths until separately proven applicable.

## Planned method and fixed input

This execution prepares one structural baseline, not a performance experiment. Add a read-only Makefile analysis target to count every typed stage site in the retained activity-guard generated tasks, separating full assignments, masked references, scalar types, distinct state IDs, task coverage, and projection metadata. Results will be written after execution; no counts or speedup are assumed now.

The later workload must remain XiangShan revision `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`, CoreMark binary SHA-256 `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`, top `SimTop`, 50,000 cycles, DIFFTEST/NEMU enabled, CPU 2, `XS_EMU_THREADS=1`, and waveform/commit/RAM trace disabled. Reuse archived gsim 20.640 s and activity-guard mean 284.699 s. Generation and compilation each require <1,800 s with process-tree termination at the deadline; simulation stop-loss is 427.0485 s. Select parallel compilation jobs after checking available CPUs. No gsim rerun is planned.

## Completed structural baseline

Added `analyze_grhsim_scalar_staging` and a read-only script that scans all unpacked task files, requires one matching definition per task, and checks their IDs against all direct evaluator calls. Every occurrence of `cpu_stage<` must parse as either a full assignment or an `auto &cpu_next` reference. Repeated state IDs must retain identical type, offset, fanout range, and projection metadata. These checks protect the count against unsupported source forms; they are not a simulation equivalence proof.

The analysis read the retained activity-guard model whose archived generation is 87.709 s with a stable JSON round trip. It ran once, serially with inherited affinity, and exited 0. No generation, compilation, or simulation was performed. `PYTHON` was the Makefile default `python3`. Exact command from the repository root:

```bash
mkdir -p ptmp/scalar_stage_screen_20260910_01
WOLF_ENV_SOURCED=1 make --no-print-directory analyze_grhsim_scalar_staging RUN_ID=scalar_stage_screen_20260910_01 GRHSIM_STAGE_MODEL=ptmp/activity_guard_20260910/flow/grhsim-ir/model/grhsim_SimTop.cpp > ptmp/scalar_stage_screen_20260910_01/analysis.log 2>&1
```

These paths specify execution inputs and output, not evidence references. The results needed to review the decision follow in full.

| Measure | Count |
|---|---:|
| Task files/definitions matched to evaluator calls | 5,595 |
| All typed stage sites | 22,222 |
| Typed full assignments | 21,073 |
| Typed masked references | 1,149 |
| Distinct states across typed sites | 18,251 |
| Eligible scalar sites | 21,073, all full `bool` assignments |
| Eligible scalar distinct states | 17,102 |
| Tasks containing eligible scalar sites | 122 |
| Eligible states with repeated static sites | 3,339 |
| Eligible states spanning multiple tasks | 0 |
| Scalar sites marked projection=true | 21,073 |
| Eligible states with zero fanout count | 0 |
| Existing direct-commit sites, outside candidate scope | 192,348 |
| Byte-range stage sites, outside candidate scope | 6,910 |
| Memory-cell stage sites, outside candidate scope | 38,955 |

All 1,149 masked typed references use wide `std::array<std::uint64_t,N>` storage: N=2:774 sites, N=3:123, N=4:110, N=5:7, N=6:2, N=8:114, N=9:9, N=13:9, and N=64:1. None is an eligible scalar masked site in this particular input. The emitter maps `bool` to unsigned one-bit two-state logic; the scalar C++ integer types likewise require two-state widths at most 64. Thus the proposed generic scalar rule is type-based, even though the observed workload opportunity consists entirely of bool full assignments.

The audit reported `PASS: task/dispatch coverage, typed-call coverage, state metadata consistency`. The scalar share of typed sites is `21073 / 22222 * 100 = 94.8294483%`. This denominator excludes direct commit, batched ranges, and memory cells; it is not the share of all state writes or runtime cost. Repeated static sites may belong to mutually exclusive paths, so they do not prove multiple writes execute in the same round. They do establish that a single-writer assumption cannot be inferred from this source count.

## Structural analysis and decision

Advance this single candidate to a structural BASELINE. The old helper demonstrates the intended unchanged-write shortcut, and the current generated model has a substantial, precisely enumerated set of full scalar assignments still using unconditional staging. Implementing the shortcut is justified for evaluation; accepting its performance is not. Most ordinary scalar register writes already use direct commit, while event-history values may change on every edge; either observation could limit the actual savings. No dynamic fraction of unchanged writes has been measured. No parameter refinement or second candidate was attempted in this execution.

The next goal execution should implement this candidate in the IR emitter, preserving existing pointer/caller-owned storage. Validate effective-shadow comparison, clean no-op writes, dirty no-op writes, 0→1→0 restoration, repeated masked writes, and event-history sampling through `make test_grhsim_cpu_emit`. Existing direct-commit and conflicting-history fixtures provide useful coverage, but must be inspected for these specific assertions before claiming equivalence. Wider scalar types and masks need meaningful behavioral coverage even though the XiangShan typed-stage inventory contains only bool full assignments. Follow that with the goal's bounded full workload and independent rerun in the appropriate later validation step.

| Performance evidence | Current value | This candidate |
|---|---|---|
| Archived gsim simulation | 20.640 s | Reused; not rerun |
| Activity-guard simulation | 289.305 / 280.093 s; mean 284.699 s | Unmeasured |
| Generation / compilation | Archived 87.709 s / approximately 515.7 s | Not started |
| Equivalence / speedup | Activity-guard baseline verified in linked archive | Not tested / unmeasured |
| Simulation stop-loss | 1.5 × 284.699 = 427.0485 s | Not triggered; no run |

At the structural stage these counts did not alter the current best or satisfy the approximately 40 s objective. The archived resumed-flat generation number alone could not prove the full SV-to-C++ timing requirement; that boundary is measured in the later full validation below.

## Implementation and focused validation

### Scope recorded before implementation

Starting from root `2d9ace1` and clean GrhSIM `c3dfad0`, this execution advances only this candidate to IMPLEMENTED. The emitter will use an effective-shadow comparison for full scalar assignments and staged scalar masked writes, preserving the existing publication queue and visible-state boundary. Planned validation is `make test_grhsim_cpu_emit`, including new scalar-width and repeated-write behavior checks plus the existing Verilator/sanitizer suites. Full XiangShan generation, compilation, and 50k performance are deferred to the subsequent validation step; no result is prefilled here.

### Implemented change

GrhSIM commit `7b3432b` changes only the IR CPU emitter, its backend documentation, and its focused unit-test sources/fixtures. Frozen GRH IR/passes and XiangShan/test workload sources are unchanged. `cpu_write_scalar<T>` reads visible or shadow storage according to the dirty flag and skips equal normalized values. The first change appends one existing-format pending record and writes the complete scalar into caller-owned shadow storage without copying the old scalar. Dirty writes update that same slot. Masked scalar emission merges against the effective value and invokes the same helper. Existing wide, memory, batched-history, and direct-commit paths are retained. The helper name is reserved against input-port collisions.

The unit fixture contains ten lanes with two writers each: unsigned widths 1, 5, 8, 13, 32, 64 and signed widths 5, 13, 32, 64. Observed event histories prevent whole-task history elision from hiding the sampling behavior. The test exposes the generated fixture's private section before compiling all its translation units; production emitter visibility is unchanged. Direct helper checks prove clean no-ops create no pending entry, dirty no-ops do not duplicate entries, visible state does not update early, writes 0→1→0 restore the original value, pre-existing staged data is respected, and changed projected values publish. The eval-driven portion uses an independent integer-mask scoreboard for zero masks, disjoint masks, restoration, randomized masks, disabled writes, falling-edge sampling, and stable-high data changes.

### Command and observed results

One invocation ran through the existing Makefile target. The host reported `nproc=32`; the focused target uses two compilation jobs, including generated-model builds. Test execution used inherited affinity and serial model evaluation, with ASan/UBSan on the new generated fixture. This is a functional test measurement, not a CoreMark performance comparison. The entire command had an 1,800 s kill deadline and completed normally:

```bash
mkdir -p ptmp/scalar_stage_impl_20260910_01
WOLF_ENV_SOURCED=1 timeout --signal=KILL 1800s /usr/bin/time -p make --no-print-directory test_grhsim_cpu_emit RUN_ID=scalar_stage_impl_20260910_01 > ptmp/scalar_stage_impl_20260910_01/test.log 2>&1
```

| Check | Observed result |
|---|---|
| Complete Make target | exit 0; real 71.08 s, user 82.52 s, sys 13.22 s |
| CTest focused executable | 1/1 passed; 60.95 s |
| New scalar staging fixture | `scalar staging PASS lanes=10 edges=10240` |
| Existing chain / scalar Verilator comparisons | PASS, 4,136 / 4,196 samples |
| Existing wide / wide-state Verilator comparisons | PASS, 3,072 / 2,048 samples |
| Existing CDC comparison and scoreboard | PASS, 10,756 samples; 1,182 simultaneous edges; 20 async resets |
| Existing dual-RAM comparison and scoreboard | PASS, 9,731 samples; 293 simultaneous edges; 424 changed writes; 15 async resets |
| Existing history-batch fixture | PASS, 4,636 samples; 4 resets |
| Timeout or sanitizer failure | None reported |

These results cover local scalar semantics and existing regressions, not XiangShan 50k equivalence. The signed/narrow lanes compare only the declared-width bits against the scoreboard, while the emitter continues to normalize storage with the existing signed-width rules. No generation/compile timing for the full workload was collected; neither gsim nor CoreMark was rerun. The comparison value remains 284.699 s and the future simulation stop threshold remains 427.0485 s.

### Decision and next step

Mark IMPLEMENTED with focused tests passing. Preserve `c3dfad0` as the best full-workload validated baseline; `7b3432b` is an experimental implementation whose speed and 50k behavior are unproven. The next goal execution should run this same candidate through bounded full generation, parallel compilation, and single-threaded CoreMark validation, with exact timing boundaries and immediate stop-loss. Do not select a new candidate before recording this one's result. The approximately 40 s goal remains unmet.

## Full-workload validation

This step started from root `7f8f75b` and clean implementation `7b3432b29f87cae70dfba6f929078a2632d6b066`. XiangShan revision and CoreMark SHA-256 were rechecked and match the fixed input above; the host reports 32 CPUs. RUN_ID is `scalar_stage_50k_20260910_01`. The experiment generated from SV (resume disabled), included the existing `py_install` dependency to refresh the Python emitter, compiled with 32 jobs, and completed two 50k runs on CPU 2 with one emulator thread and no waveform/trace. The comparison and stop-loss selected before running were 284.699 s and 427.0485 s. Each generation/build process tree had a preinstalled 1,800 s kill deadline. Commands and outcomes were appended as each phase completed.

### Generation command

```bash
mkdir -p ptmp/scalar_stage_50k_20260910_01/tmp ptmp/scalar_stage_50k_20260910_01/ccache ptmp/scalar_stage_50k_20260910_01/pip-cache
TMPDIR="$PWD/ptmp/scalar_stage_50k_20260910_01/tmp" CCACHE_DIR="$PWD/ptmp/scalar_stage_50k_20260910_01/ccache" PIP_CACHE_DIR="$PWD/ptmp/scalar_stage_50k_20260910_01/pip-cache" CMAKE_BUILD_PARALLEL_LEVEL=32 WOLF_ENV_SOURCED=1 /usr/bin/time -p -o ptmp/scalar_stage_50k_20260910_01/generation.time timeout --signal=KILL 1800s make --no-print-directory xs_wolf_grhsim_ir PYTHON="$PWD/.venv/bin/python" RUN_ID=scalar_stage_50k_20260910_01 XS_GRHSIM_IR_BUILD=ptmp/scalar_stage_50k_20260910_01/flow XS_LOG_DIR=ptmp/scalar_stage_50k_20260910_01/logs XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=ptmp/scalar_stage_50k_20260910_01/flow/model XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0 XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0 > ptmp/scalar_stage_50k_20260910_01/generation.log 2>&1
```

The timer encloses the Make invocation, including its Python installation dependency and the final IR round-trip check. It therefore provides an upper bound on SV→C++/Makefile generation, not just emission time. The archived resumed-flat timing is a different boundary and is not used for a generation speedup percentage.

### Generation result and compilation start

Generation completed with exit 0: Make wall time **605.75 s** (user 704.65 s, sys 25.61 s), PASS against 1,800 s. The script's internal total was 592.915 s. Selected internal intervals were SV ingest 75.530 s, xmr-resolve 55.131 s, hier-flatten 39.403 s, comb-loop-elim 57.399 s (zero loops), and simplify 280.177 s. Stable IR round-trip verification passed. A bytewise `cmp` of the newly generated flat GRH checkpoint against the frozen baseline completed with exit 0; include/define argument files were also byte-identical. The emitted header contains `cpu_write_scalar`, confirming the refreshed Python emitter used the candidate. These observations establish input identity without changing any GRH passes.

The generated model contains **5,749 C++ files and 1,298,655,919 C++ bytes**. Text enumeration finds **21,073 `cpu_write_scalar` call sites in 122 task files**, matching the structural baseline's eligible sites. This is emitted-source coverage only, not a dynamic count. Compilation logs show `clang++ -std=c++20 -O3` for model translation units. The object/link completion result is recorded separately below.

Compilation used the generated Makefile and existing emu build target, with a fresh output directory and 32 model compilation jobs. Its own 1,800 s deadline started at the following invocation.

```bash
TMPDIR="$PWD/ptmp/scalar_stage_50k_20260910_01/tmp" CCACHE_DIR="$PWD/ptmp/scalar_stage_50k_20260910_01/ccache" WOLF_ENV_SOURCED=1 /usr/bin/time -p -o ptmp/scalar_stage_50k_20260910_01/compile.time timeout --signal=KILL 1800s make --no-print-directory xs_wolf_grhsim_ir_build_emu RUN_ID=scalar_stage_50k_20260910_01 XS_GRHSIM_IR_BUILD=ptmp/scalar_stage_50k_20260910_01/flow XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=ptmp/scalar_stage_50k_20260910_01/flow/model VM_BUILD_JOBS=32 XS_EMU_THREADS=1 EMU_THREADS=1 WOLVRIX_GRHSIM_WAVEFORM=0 > ptmp/scalar_stage_50k_20260910_01/compile.log 2>&1
```

### Compilation result and first simulation start

Compilation completed with exit 0 in **471.77 s** (user 7,277.06 s, sys 465.86 s), PASS against 1,800 s. The emu target exists and resolves to the newly linked executable, **131,696,272 bytes**; all model objects total **148,167,152 bytes**. XiangShan's source worktree remains clean. Compilation used 32 jobs; this parallelism is not a simulation speedup.

The first full run used the exact archived workload and default progress setting (0), with explicit CPU 2 binding and `XS_EMU_THREADS=1` in both environment and Make variables. The `timeout` wrapper was installed immediately around the emulator execution prefix, so its 427.0485 s deadline excluded model generation/compilation and Make setup. `/usr/bin/time` measured the execution prefix including `taskset`/`stdbuf` startup; the emulator's own Host time was also retained for direct comparison with the archived baseline.

```bash
WOLF_ENV_SOURCED=1 XS_EMU_THREADS=1 EMU_PHASE_TIMING=0 make --no-print-directory run_xs_wolf_grhsim_ir_emu RUN_ID=scalar_stage_50k_20260910_01 XS_GRHSIM_IR_BUILD=ptmp/scalar_stage_50k_20260910_01/flow XS_LOG_DIR=ptmp/scalar_stage_50k_20260910_01/logs XS_SIM_MAX_CYCLE=50000 XS_EMU_THREADS=1 XS_EMU_CPU=2 XS_PROGRESS_EVERY_CYCLES=0 XS_WAVEFORM=0 XS_COMMIT_TRACE=0 XS_RAM_TRACE=0 XS_WAVEFORM_PATH= WOLVRIX_GRHSIM_WAVEFORM=0 XS_EMU_PREFIX="timeout --signal=KILL 427.0485s /usr/bin/time -p -o $PWD/ptmp/scalar_stage_50k_20260910_01/run1.time taskset -c 2 stdbuf -oL -eL" > ptmp/scalar_stage_50k_20260910_01/run1.log 2>&1
```

### First run result and independent repeat

The first run exited 0 at 50,000 cycles with NEMU difftest enabled and no mismatch. The endpoint is **73,580 instructions, cycleCnt 49,996, terminal PC 0x80001312**, exactly matching activity guard. Host time is **284.075 s**; execution-prefix wall time is **284.10 s** (user 284.02, sys 0.04). No stop-loss occurred. The single-run change against 284.699 s is approximately **-0.2192%**, much smaller than the archived baseline's 9.212 s spread. This is insufficient evidence of a speedup, so one independent repeat is now justified to characterize this candidate's measurement rather than accept noise.

The second invocation reused the same built emu and all input/resource/trace settings. Its separate RUN_ID and timing/log files are recorded below; the same 427.0485 s stop-loss applied.

```bash
WOLF_ENV_SOURCED=1 XS_EMU_THREADS=1 EMU_PHASE_TIMING=0 make --no-print-directory run_xs_wolf_grhsim_ir_emu RUN_ID=scalar_stage_50k_20260910_01_rerun XS_GRHSIM_IR_BUILD=ptmp/scalar_stage_50k_20260910_01/flow XS_LOG_DIR=ptmp/scalar_stage_50k_20260910_01/logs XS_SIM_MAX_CYCLE=50000 XS_EMU_THREADS=1 XS_EMU_CPU=2 XS_PROGRESS_EVERY_CYCLES=0 XS_WAVEFORM=0 XS_COMMIT_TRACE=0 XS_RAM_TRACE=0 XS_WAVEFORM_PATH= WOLVRIX_GRHSIM_WAVEFORM=0 XS_EMU_PREFIX="timeout --signal=KILL 427.0485s /usr/bin/time -p -o $PWD/ptmp/scalar_stage_50k_20260910_01/run2.time taskset -c 2 stdbuf -oL -eL" > ptmp/scalar_stage_50k_20260910_01/run2.log 2>&1
```

### Independent repeat result and final comparison

The independent repeat exited 0 at 50,000 cycles, with NEMU difftest enabled and no mismatch. It exactly reproduced the first run's **73,580 instructions, cycleCnt 49,996, terminal PC 0x80001312**, and guest-cycle count 50,001. Host time was **275.822 s**; execution-prefix wall time was **275.85 s** (user 275.77, sys 0.04). Both complete logs were checked for mismatch, ABORT, bad trap, assertion failure, and segmentation fault; none appeared. The two tool process handles returned exit 0. Stop-loss result is NONE for both, using the preselected 427.0485 s limit.

| Model / run | Host simulation (s) | Execution wall (s) | Exit / equivalence |
|---|---:|---:|---|
| Archived gsim | 20.640 | Not archived | 0 / NEMU PASS; backend cycle-accounting limitation described in M0 |
| Activity guard, first | 289.305 | Not archived | 0 / PASS |
| Activity guard, repeat | 280.093 | Not archived | 0 / PASS |
| Activity guard, mean | 284.699 | — | Comparison selected before experiment |
| Scalar staging, first | 284.075 | 284.10 | 0 / PASS |
| Scalar staging, independent repeat | 275.822 | 275.85 | 0 / PASS |
| Scalar staging, mean | **279.9485** | **279.975** | Both complete runs valid |

The first and second Host-time changes against the fixed 284.699 s comparison value are -0.2192% and -3.1180%. The mean change is `(279.9485 / 284.699 - 1) * 100 = -1.6686%`. Against original pack-0 M0 304.197 s, the mean is 7.9713% lower. The current mean remains **13.5634 times** the measured gsim 20.640 s, and approximately seven times the 40 s target.

Generation **605.75 s** and compilation **471.77 s** each pass the strict 1,800 s gate. Generation covers the complete SV route, and its flat-GRH result is byte-identical to the frozen baseline. There is no comparable archived full-SV generation interval for activity guard, so no generation percentage is claimed. The old compilation number is approximate; the present exact Make wall time is used to establish the gate, not a causal compilation speedup.

### Decision, limitations, and next step

Keep `7b3432b29f87cae70dfba6f929078a2632d6b066` as the candidate with the lowest observed mean and mark it VALIDATED, not ACCEPTED. This execution completed one candidate experiment, including an independent rerun, and no other optimization was tested. The implementation passed focused regressions, both full-workload comparisons, and both build-time gates; the absolute simulation target is still not met.

The 4.7505 s difference in means is smaller than the baseline's 9.212 s spread and the candidate's 8.253 s spread. The ranges overlap. Two repetitions are insufficient to establish a statistically reliable speedup or isolate host drift, temperature, and scheduling noise. Retaining the measured minimum is a provisional search choice, not a claim that the optimization reliably saves 1.67%. The static site count does not reveal how many writes were unchanged at runtime, and the old direct-commit path already handles most ordinary scalar register writes.

For subsequent experiments using this source and identical settings, the updated measured comparison value is **279.9485 s**, giving a 1.5× simulation limit of **419.92275 s**. Reuse the existing gsim measurement. The next search step should quantify time in compute, commit, and publication before selecting another optimization; this experiment does not establish which phase dominates. The overall goal remains active because the approximately 40 s performance requirement is unfulfilled.

## Archive

References: [previous structural screen](NO00007-grhsim-ir-candidate-activity-mask-pack-20260910.md), [activity-guard baseline](NO00003-grhsim-ir-candidate-activity-guard-20260910.md), [M0](NO00001-grhsim-ir-m0-baseline-20260910.md), [goal](grhsim-ir-xiangshan-coremark-50k.goal.md)/[index](grhsim-ir-xiangshan-coremark-50k.index.md), [analysis script](../scripts/grhsim_scalar_stage_stats.py), and [Makefile](../Makefile). The implementation, backend documentation, and unit fixtures are committed in the wolvrix submodule as `7b3432b`; the root archive must commit that submodule pointer with this report and index update. Temporary output is fully summarized above and is not an archival dependency.
