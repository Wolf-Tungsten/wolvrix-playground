# GrhSIM-IR Candidate: Elide Unchanged Scalar Shadow Writes

- Date: 2026-09-10
- Status: BASELINE / STRUCTURAL; simulator implementation pending
- Root baseline: `92b03b1` (packed-guard screen archived)
- GrhSIM baseline: `c3dfad0cc19e29943b65d815ae180fdbd42f1bee`, clean worktree
- Candidate simulator implementation: not started

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

## Analysis and decision

Advance this single candidate to a structural BASELINE. The old helper demonstrates the intended unchanged-write shortcut, and the current generated model has a substantial, precisely enumerated set of full scalar assignments still using unconditional staging. Implementing the shortcut is justified for evaluation; accepting its performance is not. Most ordinary scalar register writes already use direct commit, while event-history values may change on every edge; either observation could limit the actual savings. No dynamic fraction of unchanged writes has been measured. No parameter refinement or second candidate was attempted in this execution.

The next goal execution should implement this candidate in the IR emitter, preserving existing pointer/caller-owned storage. Validate effective-shadow comparison, clean no-op writes, dirty no-op writes, 0→1→0 restoration, repeated masked writes, and event-history sampling through `make test_grhsim_cpu_emit`. Existing direct-commit and conflicting-history fixtures provide useful coverage, but must be inspected for these specific assertions before claiming equivalence. Wider scalar types and masks need meaningful behavioral coverage even though the XiangShan typed-stage inventory contains only bool full assignments. Follow that with the goal's bounded full workload and independent rerun in the appropriate later validation step.

| Performance evidence | Current value | This candidate |
|---|---|---|
| Archived gsim simulation | 20.640 s | Reused; not rerun |
| Activity-guard simulation | 289.305 / 280.093 s; mean 284.699 s | Unmeasured |
| Generation / compilation | Archived 87.709 s / approximately 515.7 s | Not started |
| Equivalence / speedup | Activity-guard baseline verified in linked archive | Not tested / unmeasured |
| Simulation stop-loss | 1.5 × 284.699 = 427.0485 s | Not triggered; no run |

The structural counts do not alter the current best or satisfy the approximately 40 s objective. The full SV-to-C++ timing boundary also remains a final acceptance requirement: the archived resumed-flat generation number alone cannot prove it.

## Archive

References: [previous structural screen](grhsim-ir-candidate-activity-mask-pack-20260910.md), [activity-guard baseline](grhsim-ir-candidate-activity-guard-20260910.md), [M0](grhsim-ir-m0-baseline-20260910.md), [goal/index](grhsim-ir-xiangshan-coremark-50k.goal.md), [analysis script](../scripts/grhsim_scalar_stage_stats.py), and [Makefile](../Makefile). Stage and commit the new script/report, Makefile target, and index together. Temporary output is fully summarized above and is not an archival dependency. Simulator source remains the clean baseline commit.
