# GrhSIM-IR Candidate: Packed Activity Mask Checks

- Date: 2026-09-10
- Status: IDEA
- Root source inspected: `ca73185b52553d7009d88bd69890cacca89c8166`
- GrhSIM source inspected: `c3dfad0cc19e29943b65d815ae180fdbd42f1bee` (clean worktree)
- Candidate implementation: not started

## Problem and hypothesis

The validated activity guard skips inactive task bodies. The archived model has 5,749 C++ files and 5,595 scheduled task calls, of which 5,594 are guarded. This total includes domain guards and does not count only activity guards. Source inspection of `lib/grhsim/backend/cpu_emit.cpp` at the GrhSIM commit above confirms that `ActivityDrivenCompute` guards emit a short-circuit OR of one byte access per partition child. `DomainGatedCommit` instead checks one domain-arm byte. The hypothesis is that grouping consecutive activity words into packed machine-word loads will reduce load and branch overhead while preserving the exact active-word predicate. Neither the source inspection nor the archived file counts establish that these checks dominate runtime.

The generic trigger is an activity task's existing runtime byte offset set. For example, the predicate for offsets 8 through 15 could become one eight-byte load compared against zero. Offsets 8 and 10 alone must retain separate checks: loading the gap at offset 9 could observe an unrelated flag. Loads must cover only consecutive bytes belonging to the predicate and stay within the runtime buffer. Any implementation must use defined, alignment-safe access (such as fixed-size `memcpy`), rather than assuming a byte array is aligned for integer dereferences. Domain guards remain unchanged. No module names, frozen IR, or existing GRH passes are involved.

## Expected mechanism and comparison

The comparison is the current activity-guard commit `c3dfad0cc19e29943b65d815ae180fdbd42f1bee`, using the archived gsim baseline from M0. The expected benefit is lower evaluator overhead during rounds where most tasks are inactive; the risk is incorrect packing or alignment handling. A focused generated-shape test must prove the packed predicate covers exactly the original word set before any full CoreMark run.

## Fixed experiment configuration

The later implementation step must reuse XiangShan revision `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`, `ready-to-run/coremark-2-iteration.bin` (SHA-256 `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`), top `SimTop`, 50,000 cycles, CPU 2, `XS_EMU_THREADS=1`, `DIFFTEST` enabled, and waveform/commit/RAM traces disabled. The archived host used 32 build jobs; recheck CPU availability before selecting parallel build jobs. Generation, build, and simulation must use the existing Makefile targets and unique `RUN_ID`. Generation and compilation each have a 1,800-second deadline. The archived activity-guard comparison value is 284.699 s (mean of two runs), so the simulation stop threshold is 427.0485 s. Stop and kill the process tree at this threshold, or immediately on an observed failure.

## Planned evidence and decision gate

This step performed read-only source and archive inspection; no build, test, generation, or simulation was executed. Candidate timings, speedup percentages, and equivalence results are unmeasured. Before implementation, count the actual consecutive-offset runs per activity task to establish whether enough predicates qualify. Source-level OR chains may already be optimized by the compiler, and packed loads lose short-circuit behavior; therefore the performance hypothesis remains uncertain. This direction changes guard evaluation only, unlike the rejected ready dispatcher, which changed scheduling and call dispatch.

The next step should measure qualifying structure and then decide whether to implement this candidate. Focused validation would use `make test_grhsim_cpu_emit`, with behavioral cases for every byte position, all-zero input, gaps, and buffer boundaries. Exact full-flow commands and environment must be recorded before execution after inspecting the Makefile. Full validation requires two independent 50k runs with exit status 0 and matching difftest checkpoints, plus generation and compilation below 1,800 s. Acceptance also requires the goal's absolute simulation target; improvement alone is insufficient.

## Decision and archive

Register as IDEA only. Current best remains 284.699 s versus the archived gsim measurement of 20.640 s; this record claims no improvement. This execution completes the previously uncommitted IDEA archive and does not begin implementation.

References: [activity-guard measurements](grhsim-ir-candidate-activity-guard-20260910.md), [M0 baseline](grhsim-ir-m0-baseline-20260910.md), and [goal and experiment index](grhsim-ir-xiangshan-coremark-50k.goal.md). These reports are already Git-tracked; this report and its index entry are to be committed together. No temporary artifact is used as an evidence link.
