# GrhSIM-IR Candidate: Packed Activity Mask Checks

- Date: 2026-09-10
- Status: REJECTED / STRUCTURAL SCREEN
- Root source inspected: `ca73185b52553d7009d88bd69890cacca89c8166`
- GrhSIM source inspected: `c3dfad0cc19e29943b65d815ae180fdbd42f1bee` (clean worktree)
- Candidate implementation: not started; rejected before emitter changes

## Problem and hypothesis

The validated activity guard skips inactive task bodies. The archived model has 5,749 C++ files and 5,595 scheduled task calls, of which 5,594 are guarded. This total includes domain guards and does not count only activity guards. Source inspection of `lib/grhsim/backend/cpu_emit.cpp` at the GrhSIM commit above confirms that `ActivityDrivenCompute` guards emit a short-circuit OR of one byte access per partition child. `DomainGatedCommit` instead checks one domain-arm byte. The hypothesis is that grouping consecutive activity words into packed machine-word loads will reduce load and branch overhead while preserving the exact active-word predicate. Neither the source inspection nor the archived file counts establish that these checks dominate runtime.

The generic trigger is an activity task's existing runtime byte offset set. For example, the predicate for offsets 8 through 15 could become one eight-byte load compared against zero. Offsets 8 and 10 alone must retain separate checks: loading the gap at offset 9 could observe an unrelated flag. Loads must cover only consecutive bytes belonging to the predicate and stay within the runtime buffer. Any implementation must use defined, alignment-safe access (such as fixed-size `memcpy`), rather than assuming a byte array is aligned for integer dereferences. Domain guards remain unchanged. No module names, frozen IR, or existing GRH passes are involved.

## Expected mechanism and comparison

The comparison is the current activity-guard commit `c3dfad0cc19e29943b65d815ae180fdbd42f1bee`, using the archived gsim baseline from M0. The expected benefit is lower evaluator overhead during rounds where most tasks are inactive; the risk is incorrect packing or alignment handling. A focused generated-shape test must prove the packed predicate covers exactly the original word set before any full CoreMark run.

## Fixed experiment configuration

The later implementation step must reuse XiangShan revision `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`, `ready-to-run/coremark-2-iteration.bin` (SHA-256 `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`), top `SimTop`, 50,000 cycles, CPU 2, `XS_EMU_THREADS=1`, `DIFFTEST` enabled, and waveform/commit/RAM traces disabled. The archived host used 32 build jobs; recheck CPU availability before selecting parallel build jobs. Generation, build, and simulation must use the existing Makefile targets and unique `RUN_ID`. Generation and compilation each have a 1,800-second deadline. The archived activity-guard comparison value is 284.699 s (mean of two runs), so the simulation stop threshold is 427.0485 s. Stop and kill the process tree at this threshold, or immediately on an observed failure.

## Original IDEA evidence and decision gate

This step performed read-only source and archive inspection; no build, test, generation, or simulation was executed. Candidate timings, speedup percentages, and equivalence results are unmeasured. Before implementation, count the actual consecutive-offset runs per activity task to establish whether enough predicates qualify. Source-level OR chains may already be optimized by the compiler, and packed loads lose short-circuit behavior; therefore the performance hypothesis remains uncertain. This direction changes guard evaluation only, unlike the rejected ready dispatcher, which changed scheduling and call dispatch.

The next step should measure qualifying structure and then decide whether to implement this candidate. Focused validation would use `make test_grhsim_cpu_emit`, with behavioral cases for every byte position, all-zero input, gaps, and buffer boundaries. Exact full-flow commands and environment must be recorded before execution after inspecting the Makefile. Full validation requires two independent 50k runs with exit status 0 and matching difftest checkpoints, plus generation and compilation below 1,800 s. Acceptance also requires the goal's absolute simulation target; improvement alone is insufficient.

## Structural screening method and results

### Scope established before execution

This continuation starts from root commit `9b262c0a74f173954e340beb3430e3b52f6884aa`; the GrhSIM source is still the clean activity-guard commit above. This step will inspect the retained activity-guard generated model, compare each direct task guard with the bytes consumed by its task body, and count consecutive runs that can be packed. Preliminary text inspection finds only six multi-byte OR guards. That is not yet the final classification or decision. A Makefile analysis target will record the complete count under a unique `RUN_ID` in `ptmp/`. No candidate emitter modification or new simulation is planned until this structural screen establishes a useful scope.

### Completed audit

The change adds a read-only analysis script and `analyze_grhsim_activity_guards` Makefile target. It does not change the emitter, frozen GRH IR/passes, XiangShan, or test sources. The script supports the scalar direct-dispatch, unpacked-task emitter form used by the baseline, and fails on unsupported dispatch expressions or mismatched task files. It cross-checks each activity guard against the ordered byte loads in its task body, requires unique ownership, verifies runtime buffer bounds, and requires exact coverage of the flags initialized to 255. Domain guards must reference a single flag initialized to 1. Within each activity predicate, consecutive byte runs are divided into 8-, 4-, 2-, and 1-byte chunks without gaps or overreads. This is an optimistic count using alignment-safe loads; the current candidate has no 4- or 8-byte opportunities.

One analysis invocation completed with exit status 0. It read the existing artifact without generating, building, or simulating it. Exact command, from the repository root:

```bash
mkdir -p ptmp/activity_mask_pack_screen_20260910_01
WOLF_ENV_SOURCED=1 make --no-print-directory analyze_grhsim_activity_guards RUN_ID=activity_mask_pack_screen_20260910_01 GRHSIM_ACTIVITY_MODEL=ptmp/activity_guard_20260910/flow/grhsim-ir/model/grhsim_SimTop.cpp > ptmp/activity_mask_pack_screen_20260910_01/analysis.log 2>&1
```

`PYTHON` used the Makefile default `python3`. Analysis was serial, with inherited CPU affinity and no timing measurement. The input is the retained pack-0 activity-guard model for the fixed workload above; its generation record reports stable round-trip verification and the archived 87.709 s generation interval. The paths in the command are execution configuration, not evidence references. All results needed for the decision are reproduced here.

| Structural measure | Count |
|---|---:|
| Runtime flag buffer bytes | 6,056 |
| Direct task calls, also matched task definitions/files | 5,595 |
| Activity-driven tasks | 5,081 |
| Domain-guarded tasks | 513 |
| Unconditional tasks | 1 |
| Activity guards with one byte | 5,075 |
| Activity guards with two consecutive bytes | 6 |
| Activity guards with more than two bytes | 0 |
| Original activity predicate terms | 5,087 |
| Packed activity predicate terms | 5,081 |
| Terms removed | 6 (0.1179477%) |

All six qualifying guards are listed to make the narrow scope auditable. IDs are generated task IDs used for observation, never optimization triggers.

| Task | Runtime offsets | Scalar terms → packed terms |
|---|---|---|
| 180 | 1148, 1149 | 2 → 1 |
| 1355 | 2324, 2325 | 2 → 1 |
| 1356 | 2326, 2327 | 2 → 1 |
| 1357 | 2328, 2329 | 2 → 1 |
| 1358 | 2330, 2331 | 2 → 1 |
| 1359 | 2332, 2333 | 2 → 1 |

The audit returned `PASS: dispatch/files/body/initialization/bounds/unique ownership`. The percentage is `(5087 - 5081) / 5087 * 100`; it counts source predicate terms on a full scan. It does not count machine instructions, dynamic branch outcomes, or executed loads. Short-circuiting may avoid second-byte loads already, and the compiler may combine these predicates. No behavior-equivalence test was run because no simulator code was changed. Candidate generation, compilation, simulation time, speedup, and stop-loss result are all not applicable: those phases were not started. The 427.0485 s simulation stop threshold remains documented solely for any separately justified future experiment.

## Analysis, decision, and archive

Reject this candidate at structural screening. The proposal affects just six two-byte predicates and leaves the 5,595 task dispatch sites and task bodies in place. The initial expectation of widespread multi-byte predicates is contradicted by complete source enumeration. There is no evidence that these six sites account for a material fraction of the 284.699 s runtime, so this scope does not justify a full generation/build/50k experiment toward the approximately 40 s target. This is a search-priority decision, not proof of zero possible speedup or an upper bound on runtime improvement. No implementation refinement is scheduled for this direction.

Current best remains the activity-guard source commit above, with archived simulation times 289.305 and 280.093 s (mean 284.699 s), versus archived gsim 20.640 s. No baseline was rerun. The next goal execution should choose a new direction using these counts; this execution ends after committing this screen and its index update. The overall goal remains unmet.

References: [activity-guard measurements](grhsim-ir-candidate-activity-guard-20260910.md), [M0 baseline](grhsim-ir-m0-baseline-20260910.md), [goal and experiment index](grhsim-ir-xiangshan-coremark-50k.goal.md), [analysis script](../scripts/grhsim_activity_guard_stats.py), and [Makefile target](../Makefile). The report, index, script, and target form the same archival change. The existing reports are Git-tracked, and new files must be staged with this archive before committing. No temporary artifact is used as an evidence link.
