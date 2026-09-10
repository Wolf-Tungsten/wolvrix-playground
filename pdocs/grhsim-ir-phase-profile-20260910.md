# GrhSIM-IR Phase Profiling Preparation

- Date: 2026-09-10
- Status: IMPLEMENTED / FOCUSED TESTS PASS; full 50k profile pending
- Root baseline: `9e712b5`
- GrhSIM baseline: `7b3432b29f87cae70dfba6f929078a2632d6b066`
- Instrumentation commit: `93d55ae` (wolvrix)

## Question and hypothesis

The latest validated scalar-staging model averages 279.9485 s, with overlapping ranges relative to the earlier baseline. Static counts have not identified which runtime phase dominates. This step prepares measurement of compute dispatch, commit dispatch, and publication within each convergence round. The hypothesis under test in the later measurement step is that one of these phases accounts for enough runtime to direct the next optimization. No phase share is assumed now.

## Intended mechanism and scope

Use the existing model `set_runtime_profile_enabled` and `dump_runtime_profile` interfaces already called by XiangShan's `EMU_RUNTIME_PROFILE` control. The current IR implementation throws when enabled. Add cumulative nanosecond counters using `steady_clock` only when enabled, timing contiguous compute/commit task segments and `cpu_publish`. Do not change task ordering, guards, state semantics, frozen GRH passes, XiangShan, or workload sources. Count completed evals and rounds; measure full eval duration separately so setup, arm transfer, output copy, and instrumentation gaps are not misattributed to task execution.

This execution implements and tests the instrumentation only. A later execution will collect the full 50k profile and assess its perturbation; no profiling or optimization result is prefilled. The profiler-off path must perform no clock reads, though added conditionals may still have overhead. Profiling-enabled times are diagnostic and must not be presented as an uninstrumented performance benefit.

## Validation plan

Use the existing `make test_grhsim_cpu_emit` target, adding enabled/disabled model replay and counter-lifecycle checks to the generated scalar staging fixture. Verify identical model results, completed-eval/round counts, timing containment, paused counters, reset/enable semantics, and dump output. The completed focused results are recorded below; full-model measurement remains pending.

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

## Decision and next step

Mark instrumentation IMPLEMENTED with focused tests passing. Full-model generation/compilation timing, profiled 50k equivalence, profiling perturbation, and XiangShan phase shares remain unmeasured. Keep the prior `7b3432b` source and 279.9485 s measurement as the validated performance baseline; this new source has not replaced it as a measured best.

The next goal execution should generate and compile the instrumented model through Make, run it with profiling off to establish the changed source's baseline, then collect the enabled diagnostic profile and verify the same architectural endpoint. Record runtime-profile and waveform/trace settings separately. Apply the 419.92275 s stop-loss and 1,800 s generation/build deadlines, and do not treat instrumentation timing as speedup data. Choose a new optimization only after the resulting phase measurements are archived. The approximately 40 s objective remains unmet.

## Archive

References: [scalar staging baseline](grhsim-ir-candidate-scalar-stage-elision-20260910.md) and [goal/index](grhsim-ir-xiangshan-coremark-50k.goal.md), both tracked in Git. The profiler implementation, backend documentation, and tests are committed in wolvrix at `93d55ae`. This report and index are archived together with that submodule pointer in the containing root commit. Temporary test output is reproduced above and is not an archival dependency. Source and staged archive whitespace checks passed.
