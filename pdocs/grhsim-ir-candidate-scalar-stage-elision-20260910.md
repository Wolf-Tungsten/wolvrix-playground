# GrhSIM-IR Candidate: Elide Unchanged Scalar Shadow Writes

- Date: 2026-09-10
- Status: IMPLEMENTED / FOCUSED TESTS PASS; full workload validation pending
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

The structural counts do not alter the current best or satisfy the approximately 40 s objective. The full SV-to-C++ timing boundary also remains a final acceptance requirement: the archived resumed-flat generation number alone cannot prove it.

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

## Archive

References: [previous structural screen](grhsim-ir-candidate-activity-mask-pack-20260910.md), [activity-guard baseline](grhsim-ir-candidate-activity-guard-20260910.md), [M0](grhsim-ir-m0-baseline-20260910.md), [goal/index](grhsim-ir-xiangshan-coremark-50k.goal.md), [analysis script](../scripts/grhsim_scalar_stage_stats.py), and [Makefile](../Makefile). The implementation, backend documentation, and unit fixtures are committed in the wolvrix submodule as `7b3432b`; the root archive must commit that submodule pointer with this report and index update. Temporary output is fully summarized above and is not an archival dependency.
