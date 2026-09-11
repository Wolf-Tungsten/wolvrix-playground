# GrhSIM-IR Phase Profiling: Implementation and Full-Model Measurement

- Date: 2026-09-10
- Status: VALIDATED / DIAGNOSTIC PROFILE; full 50k off/on PASS, absolute performance target unmet
- Root baseline: `9e712b5`
- GrhSIM baseline: `7b3432b29f87cae70dfba6f929078a2632d6b066`
- Instrumentation commit: `93d55ae` (wolvrix)

## Question and hypothesis

The latest validated scalar-staging model averages 279.9485 s, with overlapping ranges relative to the earlier baseline. Static counts have not identified which runtime phase dominates. This step prepares measurement of compute dispatch, commit dispatch, and publication within each convergence round. The hypothesis under test in the later measurement step is that one of these phases accounts for enough runtime to direct the next optimization. No phase share is assumed now.

## Intended mechanism and scope

Use the existing model `set_runtime_profile_enabled` and `dump_runtime_profile` interfaces already called by XiangShan's `EMU_RUNTIME_PROFILE` control. The baseline IR implementation threw when enabled. Add cumulative nanosecond counters using `steady_clock` only when enabled, timing contiguous compute/commit task segments and `cpu_publish`. Do not change task ordering, guards, state semantics, frozen GRH passes, XiangShan, or workload sources. Count completed evals and rounds; measure full eval duration separately so setup, arm transfer, output copy, and instrumentation gaps are not misattributed to task execution.

The preparation execution implemented and tested the instrumentation only. Full 50k profiling and perturbation measurement were deferred to a later execution, whose completed results are recorded below. The profiler-off path must perform no clock reads, though added conditionals may still have overhead. Profiling-enabled times are diagnostic and must not be presented as an uninstrumented performance benefit.

## Validation plan

Use the existing `make test_grhsim_cpu_emit` target, adding enabled/disabled model replay and counter-lifecycle checks to the generated scalar staging fixture. Verify identical model results, completed-eval/round counts, timing containment, paused counters, reset/enable semantics, and dump output. The focused results and subsequent full-model measurement are recorded separately below.

For subsequent full measurements, retain XiangShan `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`, CoreMark SHA-256 `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`, top SimTop, DIFFTEST, 50,000 cycles, CPU 2, `XS_EMU_THREADS=1`, waveform/commit/RAM traces off, and explicitly record `EMU_RUNTIME_PROFILE`. Reuse gsim 20.640 s and the uninstrumented scalar baseline 279.9485 s. The diagnostic simulation deadline remains 419.92275 s, and each generation/build deadline remains 1,800 s with process-tree termination. Compilation must use multiple jobs chosen from available CPUs.

## Implementation

The generated model now exposes cumulative `CpuRuntimeProfile` data through `cpu_runtime_profile()` and prints one `[grhsim-cpu-phase]` line through the existing dump interface. Enabling starts fresh counters; disabling pauses without clearing; init clears counters while retaining enable state. The fields are completed evals, entered rounds, complete eval nanoseconds, compute nanoseconds, commit nanoseconds, and publication nanoseconds.

Each enabled eval snapshots the flag and starts a steady-clock timer. After round seeding, a phase timer starts. Emission detects changes between contiguous ActivityDrivenCompute and commit segments from the existing task sequence and adds the previous segment's duration at each transition. It times the final task segment and publication separately. It neither groups nor reorders task execution. Guards are included in their task segment, even when they skip the body. Total eval timing finishes after arm transfer, output copy, and any strobe flush. Adjacent timing/bookkeeping overhead perturbs the buckets slightly; the residual is unbucketed work, not necessarily a single bottleneck. Failed evals may leave partial round counters, and their profile must be discarded.

The off path snapshots a false flag and bypasses every clock read and counter update. It still adds state and branches and may alter generated-code layout, so no zero-overhead or unchanged-performance claim is made. There are no added threads or per-task timers. No frozen IR/pass, XiangShan, or workload source was modified. This instrumentation is not itself a speedup candidate.

## Focused validation results

One invocation of the existing Makefile suite completed with exit 0. The command had a 1,800 s hard kill limit, used the target's two parallel build jobs on the 32-CPU host, and inherited CPU affinity. Generated fixture execution was serial and used ASan/UBSan. No full XiangShan generation or simulation was run in this preparation step.

```bash
mkdir -p ptmp/phase_profile_impl_20260910_01
WOLF_ENV_SOURCED=1 timeout --signal=KILL 1800s /usr/bin/time -p make --no-print-directory test_grhsim_cpu_emit RUN_ID=phase_profile_impl_20260910_01 > ptmp/phase_profile_impl_20260910_01/test.log 2>&1
```

The complete Make invocation took 78.05 s wall time (user 90.48 s, sys 14.49 s). CTest reported 1/1 passed in 68.04 s; all existing emitter regressions and Verilator comparisons completed. The new test replays identical inputs through one profiling-enabled and one profiling-disabled model, checking all ten register/history output pairs for 2,048 evals. It verifies disabled counters stay zero, phase totals fit within total eval time, disabling preserves all counters across 16 more evals, re-enabling starts a new measurement, and init resets counters without losing enable state.

The generated fixture emitted these diagnostics:

```text
[grhsim-cpu-phase] evals=2048 rounds=3071 eval_ns=14902785 compute_ns=1259186 commit_ns=6244935 publish_ns=2737207
phase profile PASS replay_evals=2048 pause_evals=16
```

These are tiny-fixture test measurements, not XiangShan phase shares, and are not used to select an optimization or claim performance improvement. The dump values demonstrate that the diagnostic interface returns complete numeric fields; runtime durations are intentionally not asserted to exact constants. No timeout or sanitizer failure was reported.

## Preparation-stage decision and next step

At the preparation archive, instrumentation was marked IMPLEMENTED with focused tests passing. Full-model generation/compilation timing, profiled 50k equivalence, profiling perturbation, and XiangShan phase shares were then unmeasured. The prior `7b3432b` source and 279.9485 s measurement remained the validated performance baseline; the new source had not replaced it as a measured best.

The planned next execution was to generate and compile the instrumented model through Make, run it with profiling off to measure the changed source, then collect the enabled diagnostic profile and verify the same architectural endpoint. Its controls were separate runtime-profile and waveform/trace settings, the 419.92275 s stop-loss, and 1,800 s generation/build deadlines. The resulting measurement follows; the approximately 40 s objective remains unmet.

## Full-model measurement

### Scope and controls recorded before execution

This measurement step starts from root `d0601df` and clean GrhSIM implementation `93d55ae7d53d592c5d20e5f83863f1241fb0fcbb`. The preceding implementation/focused-test step changed authoritative source and supplied passing evidence. This execution advances the same instrumentation to full-model measurement; it does not implement another optimization.

XiangShan revision and CoreMark SHA-256 were rechecked and match the fixed identity above. The host reports 32 CPUs and 187 GiB RAM. RUN_ID is `phase_profile_50k_20260910_01`. Generate from SV with resume disabled, refreshing the Python emitter through the target's existing dependency; compile with 32 jobs; then run the same binary once with `EMU_RUNTIME_PROFILE=0` and once with `EMU_RUNTIME_PROFILE=1`. Both runs use CPU 2, one emulator thread, 50,000 cycles, NEMU difftest, `EMU_PHASE_TIMING=0`, and waveform/commit/RAM traces off. The off run measures the changed code; the on run supplies diagnostic phase proportions. This pair alone cannot establish a small causal instrumentation overhead beyond host noise.

The preselected performance comparison is the archived uninstrumented 279.9485 s mean, with a 419.92275 s simulation stop-loss for both runs. Generation and compilation each have their own 1,800 s process-group kill deadline. No measurements are assumed before completion. Reuse the archived gsim 20.640 s result.

### Full SV generation

```bash
mkdir -p ptmp/phase_profile_50k_20260910_01/tmp ptmp/phase_profile_50k_20260910_01/ccache ptmp/phase_profile_50k_20260910_01/pip-cache
TMPDIR="$PWD/ptmp/phase_profile_50k_20260910_01/tmp" CCACHE_DIR="$PWD/ptmp/phase_profile_50k_20260910_01/ccache" PIP_CACHE_DIR="$PWD/ptmp/phase_profile_50k_20260910_01/pip-cache" CMAKE_BUILD_PARALLEL_LEVEL=32 WOLF_ENV_SOURCED=1 /usr/bin/time -p -o ptmp/phase_profile_50k_20260910_01/generation.time timeout --signal=KILL 1800s make --no-print-directory xs_wolf_grhsim_ir PYTHON="$PWD/.venv/bin/python" RUN_ID=phase_profile_50k_20260910_01 XS_GRHSIM_IR_BUILD=ptmp/phase_profile_50k_20260910_01/flow XS_LOG_DIR=ptmp/phase_profile_50k_20260910_01/logs XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=ptmp/phase_profile_50k_20260910_01/flow/model XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0 XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0 > ptmp/phase_profile_50k_20260910_01/generation.log 2>&1
```

The timer includes Make's Python installation dependency and final IR round-trip check, providing an upper bound on the required complete SV→C++/Makefile interval. Generation completed with exit 0 in **606.29 s** (user 706.56 s, sys 25.54 s), PASS against 1,800 s. The script's internal total was 593.547 s; stable IR round-trip verification passed. The flat GRH checkpoint and include/define argument file were each byte-identical to the archived scalar-stage run's corresponding file.

The generated model has **5,749 C++ files, totaling 1,298,657,451 bytes**. Inspection confirms the new profile API and exactly three phase tick calls in the full evaluator: compute, commit, publication. In this schedule the compute and commit tasks each form one contiguous segment per round; no task reordering or per-task clock reads were introduced.

### Compilation

```bash
TMPDIR="$PWD/ptmp/phase_profile_50k_20260910_01/tmp" CCACHE_DIR="$PWD/ptmp/phase_profile_50k_20260910_01/ccache" WOLF_ENV_SOURCED=1 /usr/bin/time -p -o ptmp/phase_profile_50k_20260910_01/compile.time timeout --signal=KILL 1800s make --no-print-directory xs_wolf_grhsim_ir_build_emu RUN_ID=phase_profile_50k_20260910_01 XS_GRHSIM_IR_BUILD=ptmp/phase_profile_50k_20260910_01/flow XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=ptmp/phase_profile_50k_20260910_01/flow/model VM_BUILD_JOBS=32 XS_EMU_THREADS=1 EMU_THREADS=1 WOLVRIX_GRHSIM_WAVEFORM=0 > ptmp/phase_profile_50k_20260910_01/compile.log 2>&1
```

Compilation completed with exit 0 in **477.30 s** (user 7,292.98 s, sys 468.27 s), PASS against 1,800 s. This used the existing build-only target with a fresh model/output directory and an independent deadline. The newly linked executable is **134,059,704 bytes**; the 5,749 model objects total **150,530,760 bytes**. Logs confirm `clang++ -std=c++20 -O3` model compilation and no compiler/linker errors. XiangShan and wolvrix source worktrees remain clean.

### Profiling-disabled simulation

```bash
WOLF_ENV_SOURCED=1 XS_EMU_THREADS=1 EMU_PHASE_TIMING=0 EMU_RUNTIME_PROFILE=0 make --no-print-directory run_xs_wolf_grhsim_ir_emu RUN_ID=phase_profile_50k_20260910_01_off XS_GRHSIM_IR_BUILD=ptmp/phase_profile_50k_20260910_01/flow XS_LOG_DIR=ptmp/phase_profile_50k_20260910_01/logs XS_SIM_MAX_CYCLE=50000 XS_EMU_THREADS=1 XS_EMU_CPU=2 XS_PROGRESS_EVERY_CYCLES=0 XS_WAVEFORM=0 XS_COMMIT_TRACE=0 XS_RAM_TRACE=0 XS_WAVEFORM_PATH= WOLVRIX_GRHSIM_WAVEFORM=0 XS_EMU_PREFIX="timeout --signal=KILL 419.92275s /usr/bin/time -p -o $PWD/ptmp/phase_profile_50k_20260910_01/off.time taskset -c 2 stdbuf -oL -eL" > ptmp/phase_profile_50k_20260910_01/off.log 2>&1
```

The execution-prefix timer encloses taskset/stdbuf and emu, excluding Make setup and generation/compilation. The preinstalled 419.92275 s kill deadline applies to this same execution process group. The off run completed with exit 0, Host time **287.162 s**, and execution wall **287.19 s** (user 287.11 s, sys 0.04 s). NEMU difftest was enabled with no mismatch; the endpoint is **73,580 instructions, cycleCnt 49,996, terminal PC 0x80001312, guest cycles 50,001**, exactly matching the archived scalar-staging endpoint. No runtime-profile line, assertion failure, ABORT, bad trap, or segmentation fault appeared. Stop-loss result is NONE.

### Profiling-enabled simulation

The same executable and fixed input are now measured with the sole runtime-setting change `EMU_RUNTIME_PROFILE=1`; log/timer identities are separate. The preselected stop-loss remains 419.92275 s.

```bash
WOLF_ENV_SOURCED=1 XS_EMU_THREADS=1 EMU_PHASE_TIMING=0 EMU_RUNTIME_PROFILE=1 make --no-print-directory run_xs_wolf_grhsim_ir_emu RUN_ID=phase_profile_50k_20260910_01_on XS_GRHSIM_IR_BUILD=ptmp/phase_profile_50k_20260910_01/flow XS_LOG_DIR=ptmp/phase_profile_50k_20260910_01/logs XS_SIM_MAX_CYCLE=50000 XS_EMU_THREADS=1 XS_EMU_CPU=2 XS_PROGRESS_EVERY_CYCLES=0 XS_WAVEFORM=0 XS_COMMIT_TRACE=0 XS_RAM_TRACE=0 XS_WAVEFORM_PATH= WOLVRIX_GRHSIM_WAVEFORM=0 XS_EMU_PREFIX="timeout --signal=KILL 419.92275s /usr/bin/time -p -o $PWD/ptmp/phase_profile_50k_20260910_01/on.time taskset -c 2 stdbuf -oL -eL" > ptmp/phase_profile_50k_20260910_01/on.log 2>&1
```

The on run completed with exit 0, Host time **292.350 s**, and execution wall **292.38 s** (user 292.29 s, sys 0.04 s). NEMU difftest was enabled; no mismatch, ABORT, bad trap, assertion failure, or segmentation fault appeared. It independently reproduced **73,580 instructions, cycleCnt 49,996, terminal PC 0x80001312, guest cycles 50,001**. Stop-loss result is NONE. The runtime-profile enabled banner and the complete diagnostic line appeared:

```text
[grhsim-cpu-phase] evals=100102 rounds=201258 eval_ns=292123004506 compute_ns=164123997494 commit_ns=113199450847 publish_ns=14719460343
```

These measurements include phase-clock/bookkeeping perturbation. The model executes both clock edges and reset evals; profiling starts before emulator reset, after model init. Thus completed evals are not guest cycles. The observed average is **201258 / 100102 = 2.010529 convergence rounds per eval**. This does not identify redundant rounds or prove that rounds can be removed safely.

### Timing comparison and phase analysis

| Configuration | Host time (s) | Execution wall (s) | Equivalence / exit |
|---|---:|---:|---|
| Archived gsim | 20.640 | Not archived | NEMU PASS / 0; M0 cycle-accounting limitation applies |
| Archived scalar staging, two runs | 284.075; 275.822 | 284.10; 275.85 | Both NEMU PASS / 0 |
| Archived scalar staging mean, preselected comparison | 279.9485 | 279.975 | Validated performance baseline |
| Instrumented source, profiling off | 287.162 | 287.19 | NEMU PASS / 0 |
| Same executable, profiling on | 292.350 | 292.38 | NEMU PASS / 0; diagnostic |

The off run is `(287.162 / 279.9485 - 1) * 100 = +2.5767%` above the archived baseline mean. The on run is **5.188 s**, or `(292.350 / 287.162 - 1) * 100 = +1.8066%`, above off, and 4.4299% above the old mean. These are observed differences, not estimates of causal clock overhead or statistically established regressions. There is only one run per new configuration, performed sequentially after compilation; host drift, thermal state, and scheduling noise are uncontrolled. The archived scalar runs span 8.253 s. Off and on results must not be averaged into a new performance baseline because their measurement settings differ. The new source's extra fields, branches, and code layout can also affect off performance.

| Measured region | Seconds | Share of total model eval time |
|---|---:|---:|
| Compute dispatch and task segment | 164.123997494 | 56.1832% |
| Commit dispatch and task segment | 113.199450847 | 38.7506% |
| Publication | 14.719460343 | 5.0388% |
| Eval residual outside these segments | 0.080095822 | 0.0274% |
| Complete successful evals | 292.123004506 | 100% |

The residual is calculated directly as `eval_ns - compute_ns - commit_ns - publish_ns`; it is positive and phase intervals do not overlap. Host time exceeds eval time by **0.226995494 s**, but the timing scopes differ, so this gap is not a dedicated measurement of difftest or any other one subsystem. The fractions use `eval_ns`, not Host time, as denominator. Guards are charged to their phase even when they skip task bodies. The profiler does not separate dispatch, task arithmetic, state staging, or cache misses within those segments.

Compute plus commit account for **94.9338%** of measured eval time. Publication alone is not the main runtime cost for this workload. As a diagnostic Amdahl-style bound, eliminating its entire measured 14.7195 s while holding all other costs fixed would still leave about **277.6305 s** of this on run. Eliminating all compute alone would leave **128.2260 s**; eliminating all commit alone would leave **179.1505 s**. These are arithmetic bounds under a fixed-cost assumption, not implemented transformations or predicted speedups. Reaching about 40 s will require major reductions across compute/commit work or their shared scheduling/evaluation mechanism. The profile cannot yet attribute the cost to specific tasks, op classes, or duplicated work.

The full generation **606.29 s** and compilation **477.30 s** each pass the strict 1,800 s gate; both simulations pass the 419.92275 s stop-loss. The new source adds only 1,532 C++ bytes relative to the archived generated model, while executable size increased by 2,363,432 bytes. This supports treating generated code layout as a possible confounder, but does not establish why runtime changed. No frozen GRH/pass, XiangShan, or workload sources were modified. Generation's flat checkpoint matched the previous validated frozen input byte for byte.

### Measurement decision and next step

Mark this instrumentation **VALIDATED for diagnostic use**, with focused tests plus full-model off/on equivalence and complete generation/build gates. It is not an accepted optimization or a new measured best. Retain uninstrumented source `7b3432b29f87cae70dfba6f929078a2632d6b066`, mean **279.9485 s**, and the **419.92275 s** same-configuration stop-loss for the next search step. Reuse gsim 20.640 s. The approximately 40 s objective remains unmet.

This execution completed the planned measurement step and tested no additional optimization. The next goal execution should localize hot functions/task work within compute and commit, using this phase split to guide one deeper profiling investigation. Distinguish dispatch/guard costs from task bodies and relate hotspots to generic IR operations or scheduling dependencies before choosing an optimization. Do not prioritize a publication-only change as sufficient for the absolute goal, and do not infer safe round elimination from the 2.010529 rounds/eval average. A stronger instrumentation-overhead estimate would require repeated or interleaved controls; the present evidence is sufficient for the broad phase-ranking decision, not for claiming a small speedup or precise overhead.

## Archive

References: [scalar staging baseline](NO00008-grhsim-ir-candidate-scalar-stage-elision-20260910.md), [M0 baseline](NO00001-grhsim-ir-m0-baseline-20260910.md), and [goal](grhsim-ir-xiangshan-coremark-50k.goal.md)/[index](grhsim-ir-xiangshan-coremark-50k.index.md), all tracked in Git. The profiler implementation, backend documentation, and tests are committed in wolvrix at `93d55ae`; preparation was archived at root `d0601df`. This full-measurement report update and goal/index are archived together in the containing root commit, retaining that submodule pointer. Temporary output is reproduced and analyzed above and is not an archival dependency. Source and archive whitespace checks passed; all linked reports are tracked. No generated files are included in the archive.
