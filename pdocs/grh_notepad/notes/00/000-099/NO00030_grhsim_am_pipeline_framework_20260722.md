---
id: NO00030
date: 2026-07-22
title: GRHSIM-AM activity-aware pipeline framework
kind: plan
status: active
area: architecture
topic: grhsim-am
tags: [grhsim, am, activity-schedule, cpp-emit, memory-model, scalability]
parents: []
related: [NO00024, NO00027]
supersedes: []
---

# NO00030 GRHSIM-AM activity-aware pipeline framework (2026-07-22)

> Archive ID: `NO00030`. The existing `grh_notepad` management tree is absent in the
> current worktree, so this note does not restore or rewrite its deleted topic index.

## Background

The legacy GrhSIM path schedules GRH operations first and passes several session side
tables to a C++ emitter that still reads the GRH graph. This makes activity grouping
depend on GRH operation classes and keeps memory access semantics implicit until emit.

The target ownership flow is:

```text
normalized GRH
    -> am::LinearProgram
    -> AM activity scheduler
    -> am::ScheduledProgram / ExecutableModel
    -> AM C++ emitter
```

The design document is
[GRHSIM-AM lowering, scheduling, and C++ emit pipeline](../../../../../wolvrix/docs/grhsim/grhsim-am-pipeline.md).

## Evidence

- The final AM Program already requires an EntryBlock, active normal Blocks, and explicit
  `changed`/`act`; an unscheduled single instruction region therefore cannot use the final
  Program type.
- The legacy scheduler exports `supernode_to_ops`, `op_to_supernode`, `value_fanout`,
  `topo_order`, and related GRH-ID structures from
  `wolvrix/lib/transform/activity_schedule.cpp`.
- The legacy emitter reloads those structures together with the Graph near
  `EmitGrhSimCpp::emitImpl`, so its input is not yet an AM Program.
- At 100M instructions, one extra dense `u32` array costs about 400 MB. Nested vectors,
  per-operation strings, high-cardinality hash maps, and simultaneous full copies of the
  linear and scheduled IR are not viable.

## Decisions

1. Use separate move-only `LinearProgram` and `ScheduledProgram` types. Only the latter is
   executable and accepted by a future AM emitter.
2. Keep ports in a non-semantic `ProgramInterface`; labels are optional diagnostics and
   cannot define the integration ABI.
3. Store dense zero-based 32-bit IDs, opcode/operand/result SoA and CSR arenas, sparse typed
   opcode attributes, a dense string table (with interning owned by lowering), compact init
   tables, and Block offsets with an optional instruction permutation. Identity Block order
   does not materialize the four-byte-per-instruction permutation.
4. Reserve `UINT32_MAX` as the invalid ID and reject an individual arena that exceeds the
   32-bit limit. This covers the index range needed by the stated 100M case without paying
   64-bit offset cost on every instruction; offset-backed tables cap logical records at
   `UINT32_MAX - 1` so the trailing sentinel stays within that limit. This does not prove
   the memory or peak-RSS gate.
5. Scheduling facts and def-use/access/DAG indexes are transient. The semantic schedule is
   materialized only as Blocks, `changed`, and `act.f/act.b` in the final Program.
6. Reuse the legacy emitter only after a new `ExecutableModel` input boundary. Graph and
   `activity_schedule.*` session keys must not remain inputs to the final AM backend.

## Scale budget

For 100M instructions, 100M variables, 250M operands, and 100M results, the analytical
compact-core budget is roughly 3.2-3.6 GB when it includes a worst-case explicit scheduled
instruction permutation, but excludes large literal/init payloads. Identity Block order can
elide that permutation. A CSR def-use index adds about 1.8 GB. The scheduler target is a
6-8 GB peak plus explicitly reported literal, debug, and output buffers. These figures are
planning estimates; no 100M synthetic RSS/no-copy gate has run yet.

## Incremental update 2026-07-22 (framework hardening)

The initial framework is present under:

```text
wolvrix/include/grhsim/am/
wolvrix/lib/grhsim/am/
wolvrix/tests/grhsim/am/
```

Implemented so far:

- compact Program storage, read-only views, per-arena size/capacity telemetry, and 32-bit
  per-arena limit checks. Compile-time assertions pin the hot-table ABI used by the scale
  budget (`Opcode = 1 B`, dense IDs/CSR offsets = 4 B, Variable metadata = 8 B), and tests
  cross-check those widths through `ProgramStorageStats`;
- move-only linear and scheduled builders, including `ProgramReserve`,
  `ScheduledProgramReserve`, streaming Block construction, and identity-layout permutation
  elision;
- typed init, DPI, call, slice, and activation records;
- structural/semantic validator entry points for Program, interface, scheduling facts, and
  ownership artifacts, including opcode/type signatures, state and memory targets,
  `changed` old ownership, activation events, slice bounds, system/DPI signatures, enum
  values, and the Linear-only normal form. Artifact checks now also enforce exact external
  input/output role sets, State roles on every state/memory target, interface-input write
  isolation, and private `changed` old/result boundaries. B0 coverage uses latest-definition
  provenance, accepts truth-preserving OR aggregation, and rejects overwritten input/event
  proofs. These remain scaffold validators rather than the final AM semantic gate;
- `LinearProgramArtifact`, `ExecutableModel`, stage interfaces, and pipeline orchestration;
- a staged `pipeline.lower(...)` then `pipeline.run(LinearProgramArtifact&&, ...)` API, so a
  caller can release GRH before scheduling; an existing diagnostics error does not consume
  the owned artifact;
- a limited baseline smoke scheduler that watches external inputs in B0, keeps the semantic
  stream in B1, and uses state `changed + act.b` for conservative convergence. It rejects
  `HostRead`/`HostEffect` and ordered-effect groups whose semantic order disagrees with the
  linear instruction order, rejects forward def-use it cannot topologically schedule, derives
  all state read-write targets from opcode traits, and releases SchedulingFacts before growing
  scheduled storage; it is not a production scheduler or a differential oracle;
- negative contract coverage for self-backed builder spans, invalid init/type/opcode/DPI
  records, state/change/activation semantics, B0 input coverage, ordered-effect rejection,
  host-interaction rejection, input write isolation, and legal ScheduledProgram non-SSA forms;
- corrected scheduled block-permutation reserve accounting and mutation-free preflight for
  rejected convenience Block/activation appends;
- direct staged-lifecycle and representative no-copy ownership tests, full per-arena
  size/capacity/element-width accounting, scheduled synthetic-tail reserve checks, and
  nonallocating 32-bit arena/offset/current-plus-additional overflow tests;
- linear-time typed-attribute completeness checks and bit-packed changed-private validation,
  avoiding an `O(I log A)` finish pass and a two-ID-per-detector privacy scratch list;
- CMake integration.

Verification for the current revision:

```text
PASS cmake --build wolvrix/build -j8 --target grhsim-am-program grhsim-am-pipeline
PASS ctest --test-dir wolvrix/build -R '^(grhsim-am-program|grhsim-am-pipeline)$' --output-on-failure (2/2)
PASS cmake --build wolvrix/build -j8 --target transform-activity-schedule emit-grhsim-cpp emit-grhsim-cpp-memory-fill
PASS ctest --test-dir wolvrix/build -R '^(grhsim-am-program|grhsim-am-pipeline|transform-activity-schedule|emit-grhsim-cpp|emit-grhsim-cpp-memory-fill)$' --output-on-failure (5/5, 95.69 s)
PASS git diff --check && git -C wolvrix diff --check
PASS rg -n '[[:blank:]]+$' over all new AM sources/tests/docs returned no matches
```

This is not a claim that final AM validation, GRH lowering, memory-aware partitioning, the
AM C++ emitter, or the 100M scale gate has been completed.

## Framework-stage completion audit (historical snapshot)

The framework-only objective is closed by direct code evidence: Graph lowering has an
owned `LinearProgramArtifact` boundary; scheduling consumes it and produces an
`ExecutableModel`; the emitter interface accepts only that model; public contracts,
implementations, and tests follow the documented directory ownership; compact storage,
reserve, and telemetry APIs encode the 100M-aware design; and Phase 1-5 work is separated
into explicit future gates. This paragraph records the earlier framework-only milestone;
the concrete implementation state is superseded by the full-XiangShan update below.

## Open risks at the framework milestone (historical)

- The validators remain short of the final instruction-set gate. Host system binding
  uniqueness/signatures, final-call dependency order, full `changed` result ownership and
  epoch behavior, ordered-effect group completeness, B0 activation-target reachability to
  every actual reader, and jointly complete edge-event decompositions still require the real
  scheduler graph or an execution-aware validation boundary.
- Calling `ScheduledProgramBuilder::reserve()` after a tightly reserved LinearProgram can
  still relocate GiB-scale prefix arenas. Production lowering must reserve a predictable
  synthetic tail up front, or the affected storage must become segmented.
- Scheduler dependency-edge counts and phase high-water/release telemetry are not
  implemented.
- The staged `lower -> release Graph -> run artifact` route permits the no-double-copy
  lifecycle. The convenience `run(const Graph&)` retains Graph until return and cannot be
  used as evidence for that gate.
- No 100M synthetic RSS test had been run at this milestone. Full normalized-GRH lowering
  and a concrete AM C++ emitter were still absent at that point.

## Next phases at the framework milestone (superseded)

1. Complete the remaining final-gate semantics, establish representative HDLBits/C910/XS
   timing and RSS baselines plus the small differential corpus, then close the compact
   container memory gates with measured evidence.
2. Implement full normalized GRH to LinearProgram lowering for every documented opcode.
3. Replace the baseline two-Block scheduler with CSR-based memory-aware partitioning while
   treating the baseline only as a smoke bridge until a reference executor and differential
   corpus prove an oracle-quality subset.
4. Add an AM interpreter/reference executor and compare full execution with activity-aware
   execution.
5. Add `ExecutableModel -> C++` model construction at the legacy emitter's model-build
   boundary, then run HDLBits and large-design shadow gates.

## Incremental update 2026-07-22 (full XiangShan AM emit)

This section is the current implementation status and supersedes the historical completion
and next-phase statements above. The real completion target remains:

```text
full emit -> model compile -> XiangShan emu link
          -> CoreMark 100 -> 2k -> 20k -> 50k difftest
```

### Full-design evidence

The current concrete lowering, production scheduler, and C++ emitter accept the complete
XiangShan `SimTop` checkpoint:

```text
input:
  build/xs/grhsim/wolvrix_xs_post_stats.json
  size                                      3,077,399,486 bytes

lowering:
  graph operations                              5,268,574
  linear AM instructions                        5,080,563
  linear AM variables                           5,498,848

production schedule:
  scheduled instructions                        9,574,478
  scheduled variables                           9,579,216
  Blocks                                        1,021,857
  changed detectors                             2,040,184
  activation targets                            4,791,892
  scheduled estimated storage                 475,499,773 bytes

full emit command:
  wolvrix/build/bin/grhsim-am-lower-json \
    build/xs/grhsim/wolvrix_xs_post_stats.json \
    SimTop \
    --emit ptmp/grhsim_am_xs_20260722/am_emit_host_semantics

full emit result:
  exit status                                            0
  emit time                                          5,934 ms
  emitted artifacts                                      3
  peak RSS                                       28,481,592 KiB
  grhsim_SimTop.cpp                         1,679,120,625 bytes
  grhsim_SimTop.cpp                              29,400,887 lines
  grhsim_SimTop.hpp                                   6,265 bytes
```

The peak is still dominated by parsing the 3.08 GB JSON checkpoint. Releasing the Graph
before scheduling reduces current RSS to about 1.3 GiB; the single-TU emitter then finishes
at about 8.1 GiB current RSS. This run proves complete per-instruction C++ generation for the
current XiangShan design. It does not prove that the generated 1.68 GB translation unit is
compilable or that its runtime behavior is correct.

The persisted earlier failures at wide `concat` and `system.task` are obsolete. Current
XiangShan census and the successful full emit show no remaining design-used hard reject:

- no `SystemFunction`;
- no wide `div`/`mod`;
- no inout model port;
- no DPI integral wider than 64 bits;
- no DPI output/inout String or String return;
- system tasks are 7,235 `fwrite` calls and one `finish` call.

### Host and XiangShan wrapper semantics

The AM C++ emitter now implements the XiangShan-required host boundary:

- condition plus OR-of-events gating for `system.task` and `dpi.call`;
- Normal/Once/Final task lifecycle, public idempotent `finalize()`, and structured
  finish/stop/fatal state without forcing process exit;
- incremental task formatting, including wide signed/unsigned logic and calls with 2,000
  formatting arguments;
- typed `extern "C"` DPI declarations, stable String input snapshots, 1-bit ABI as
  `std::uint8_t`, and output/return commit only after a normal host return;
- `mem.fill`, `mem.read`, masked `mem.write`, out-of-range address behavior, and Array
  `changed.any` differential coverage between the Interpreter and generated C++.

The generated-model host test now covers `%b`, `%x`, a 352-bit unsigned `%d`, exactly 2,000
`%d` arguments, JTAG-shaped four-`uint8_t*` output ABI, a signed 64-bit input, signed 32-bit
and unsigned 64-bit outputs, and signed 32/64-bit returns. The focused
`grhsim-am-cpp-emitter-host` test passes (`1/1`, 1.22 seconds). This representative coverage
does not replace the final link of all 34 XiangShan DPI imports.

The XiangShan GRHSIM wrapper detects the structured termination API when present, calls
`finalize()` once, stops later evaluations after termination, and maps the exit status into
`get_difftest_exit()`. The existing `difftest/grhsim.mk` contract already matches the AM
model names (`grhsim_SimTop.hpp`, `GrhSIM_SimTop`, `libgrhsim_SimTop.a`, and `Makefile`), so
the first AM link does not require a second wrapper or a new consumer ABI.

### Historical physical blockers

The initial full AM emit above was blocked by physical code generation, not by a missing
XiangShan opcode: it retained one C++ string per scheduled instruction, assembled a single
1.68 GB translation unit with 1,021,857 switch cases, emitted about 2.04 million static
changed-result clears, and linearly scanned every Block on every epoch. The three-artifact
result recorded above is therefore historical evidence for opcode coverage only, not the
current emitter layout.

### Incremental update 2026-07-22 (activity scheduling and bounded runtime)

The following implementation replaces those software-level blockers while keeping the AM
boundary `LinearProgramArtifact&& -> ExecutableModel -> C++ emitter`; it does not import the
legacy Graph/session scheduling tables.

1. As implemented on 2026-07-23, the production AM scheduler classifies SCC-condensed DAG
   atoms as `Compute` or `Commit`; `BlockClass::Isolated` no longer exists. Pure instructions,
   state reads, DPI/system calls, and `SystemFunction` use the compute cap
   `maxInstructionsPerBlock` (default 128). State-targeted reg/latch/memory writes use the
   independent `maxCommitInstructionsPerBlock` cap (default 4096); both classes are bounded by
   `maxStateWritesPerBlock` (default 4096). Same-class Kahn-ready atoms can coarsen when the
   limits and commit-event bucket rules hold. Raw `changed` remains compute-class and retains
   its direct-event lifetime and activation rules. Oversized indivisible atoms remain whole
   and are reported. Final state/memory watchers are materialized only at their final write
   frontier.

   An indivisible DAG atom is exactly one SCC of the instruction dependency graph; a singleton
   SCC is one atom. The scheduler has no non-SCC contraction rule. A DPI/system/effect sequence
   and multiple writes to one state target contribute directed ordering edges only. They may
   span atoms and Blocks when those edges remain ordered. Multiple writes still use one watcher
   at the final scheduled writer frontier; when earlier and final writers occupy different
   Blocks, a local `reduce.or` normalizes the writer guard to an unsigned one-bit event before
   runtime `act.f` propagation reaches that frontier without contracting the writers.

2. The AM C++ emitter now produces bounded staged multi-TU output:

   ```text
   grhsim_SimTop.hpp
   grhsim_SimTop_support.hpp
   grhsim_SimTop_runtime.cpp
   grhsim_SimTop_blocks_N.cpp
   Makefile                         # exact ordered SRCS, no wildcard
   ```

   `blocksPerSource` defaults to 2,048. Instruction code is written directly to the current
   block shard, so the all-instruction string vector, whole-model source buffer, and giant
   generated block switch are gone. Files are generated in a staging directory and published
   with rollback; a failed size limit leaves no partial artifact set.
3. Generated model activity now uses 64-Block current/next words plus a summary bitset over
   non-empty words. It consumes active Blocks in ascending `BlockId`; `act.f` updates the
   current epoch and `act.b` the next epoch. The initial full `B1..Bn` sweep and epoch
   boundaries remain unchanged. `changed` uses `set_changed_result`, a bit-packed dirty set,
   and a vector of actually fired results, so only fired events are cleared at eval/epoch
   boundaries rather than emitting one store per detector.

Commit writes have a stricter per-instruction event lifetime than Pending host calls.
`RegisterWrite`, `MemoryWrite`, and `MemoryFill` use **consume-on-event**, not
complete-on-write: once a commit instruction observes any triggering event during an
`eval()`, that event instance is consumed for that instruction. Other consumers of the same
event may still observe it independently. A false guard, an out-of-range `MemoryWrite`
address, or a zero write mask suppresses the state/memory mutation but must not preserve the observed
event for replay after a new operand capture. A later attempt requires a new event instance.

The XiangShan commit-path investigation confirmed that Block 36995 recaptures its guard and
address operands for every new activation batch; it does not reuse an old operand capture.
The state that survived across batches was the pending event. Restoring that old event and
testing it against newly captured operands is exactly the replay forbidden by consume-on-event.
Capture-batch integrity remains an independent runtime invariant.

Focused verification for this incremental implementation:

```text
PASS cmake --build wolvrix/build -j8 --target \
  grhsim-am-production-schedule grhsim-am-cpp-emitter \
  grhsim-am-cpp-emitter-host grhsim-am-end-to-end
PASS ctest --test-dir wolvrix/build --output-on-failure \
  -R '^(grhsim-am-production-schedule|grhsim-am-cpp-emitter|grhsim-am-cpp-emitter-host|grhsim-am-end-to-end)$' (4/4, 5.69 s)
```

`grhsim-am-cpp-emitter` includes a 131-Block generated-model regression that crosses activity
word boundaries: entry `act.f` reaches B64, B64 forwards to B130 in the same epoch, and B130
uses `act.b` to execute B65 in the next epoch. It also asserts that generated source uses the
packed activity/dirty-result paths and no longer contains the dense activity scan or static
per-result clear path.

### Implemented 2026-07-23: removed the `Isolated` scheduling class

`Isolated` was an implementation policy, not an AM semantic class. The production scheduler
now has only compute and commit scheduling phases: `BlockClass::Isolated`, its ready queue, its
statistics, and its unconditional no-coarsen path have been removed. Every non-commit host
instruction, including `SystemFunction`, enters the compute phase and may share a Block with
other compute instructions under the normal instruction cap.

DPI/system/effect order and same-target write priority remain explicit directed edges; neither
an ordered call sequence nor a common state target contracts instructions into an atom.
`system.task` and `dpi.call` retain their instruction-local condition/event gating and
Normal/Once/Final lifecycle. Execution opportunity, however, now follows the merged Block's
union activation domain rather than a private host Block. Eventful task/DPI instructions can
self-filter unrelated activation through their event predicate; eventless task/DPI and
`SystemFunction` may be invoked more often when another member activates the shared Block.
That repeated execution is the explicit behavior of the current host-as-compute policy, not a
reason to restore `Isolated`. Directed edges preserve observable call order, but equivalence
of call counts to the pre-lowering source still requires the per-call trace differential gate;
it is not proved merely by ScheduledProgram validity.

Focused scheduler coverage now checks that ordered and implicit host sequences can split or
coarsen without becoming oversized atoms, that a posedge-driven host call can share a compute
Block, and that a `SystemFunction` coarsened with its ordinary producer runs again after an
input change. Same-target writers split at commit caps while retaining one final watcher; the
frontier path also covers signed one-bit writer guards normalized to unsigned events. Runtime
regressions cover next-epoch activation of an earlier writer and a chained `A -> B -> C`
writer frontier using local guarded `act.f`, with no static transitive closure.

### Historical pre-removal snapshot: full SimTop Block/TU boundary

The legacy scheduler's `supernode` and an AM normal `Block` are corresponding activity-driven
execution units. A Block is therefore an indivisible semantic unit for C++ emission: the
emitter may pack complete Blocks into multiple translation units, but it must never split one
Block's instruction sequence across translation units. The generated `_part_N.cpp` suffix
means a physical continuation containing later complete Block cases, not part of a Block.

The following event-bucket run predates removal of `BlockClass::Isolated`. Its physical
Block/TU evidence remains valid for that generated model, but its `isolated` count and total
Block count are historical and do not describe the current scheduler. The canonical legacy
plain result contains 72,682 supernodes (72,180 compute and 502 commit). That historical AM
schedule contains 51,600 normal Blocks plus B0:

```text
compute       37,321
isolated      13,763
commit           515
input sink         1
normal total  51,600
with B0       51,601
```

These counts need not be identical. The legacy graph contains 7,337,088 operations and
6,745,531 values, including 2,068,514 per-use source clones; subtracting the clones gives the
fresh raw Graph counts of 5,268,574 operations and 4,677,017 values. Legacy also uses compute
cap 108 and a different coarsen/DP partition, while AM uses cap 128 and SCC/Kahn-ready packing.
Even legacy nosplit/default variants differ by 38 compute supernodes, so the count is not a
semantic constant and AM must not be artificially split to approach 70k.

Historical artifact audit for
`ptmp/grhsim_am_xs_phase_20260722/grhsim_emit_event_buckets`:

```text
block TUs                         392
complete Block cases          51,601 (IDs 0..51600)
missing/duplicate/cross-TU IDs      0 / 0 / 0
largest single Block             B51108
B51108 case bytes              6,441,416
B51108 exclusive TU bytes      6,441,640
all other block TUs            <= 4 MiB
runtime TU bytes               14,837,679
```

Every model compile command was independently wrapped in a hard 900-second timeout. All 392
Block TUs and the runtime TU compiled successfully and `libgrhsim_SimTop.a` was created; no
single translation unit reached the timeout. The parallel full-model build wall time was
16:07.80, which is not the per-file acceptance metric. The archive then linked into a fresh
XiangShan difftest emu with all DPI symbols resolved.

CoreMark/NEMU results for that fresh emu:

```text
100 cycles   PASS, guest cycle 101, exit 0
2,000 gate   FAIL, SIGSEGV in NEMU map_read after a bad DUT ArchEvent
first bad    difftest cycle 568: exception=2, pc=0x10000080, inst=0
legacy       cycle 568: first commit pc=0x10000000, inst=0x0010029b
```

There were no earlier AM commits. The NEMU crash is downstream of the incorrect DUT exception;
it is not evidence of a TU boundary failure. The 20k and 50k gates were not run because the 2k
gate is required to pass first.

### Incremental update 2026-07-23 (post-`Isolated` XiangShan rerun)

The complete `SimTop` pipeline was rerun after SCC-only atom formation and removal of the
`Isolated` class. Every linear instruction is a singleton SCC in this input; ordered host/effect
sequences and same-target writes remain edges and therefore do not reduce the atom count:

```text
linear AM instructions                   5,080,563
SCC atoms                                5,080,563
oversized atoms                                  0

compute Blocks                              37,423
commit Blocks                                  515
input sink Block                                  1
normal Blocks                               37,939
normal Blocks plus B0                       37,940

changed detectors                        2,022,159
activation targets                       3,556,634
writer-frontier activations                      0
scheduled instructions                   9,532,818
emitted artifacts                              411
```

`writer-frontier activations=0` is a property of this XiangShan input and schedule, not an
absence of the mechanism; focused interpreter tests cover split same-target frontiers and a
multi-level runtime frontier chain.

The full emit completed in 47.22 seconds with peak RSS 28,458,200 KiB. The generated model
build completed in 15:20.43; `libgrhsim_SimTop.a` is 843 MiB and the model directory is
3.1 GiB. Linking the XiangShan difftest emu took 1.68 seconds with peak RSS 971,808 KiB; the
resulting emu file is 503 MiB.

CoreMark/NEMU localization for that newly built emu is:

```text
-C 100      PASS
-C 571      PASS
-C 572      FAIL, SIGSEGV
-C 2000     FAIL, SIGSEGV
first bad model tick approximately cycleCnt 568
-C 20000    NOT RUN
-C 50000    NOT RUN
```

The 2k acceptance gate fails consistently with the smaller 572-cycle boundary. The 20k and
50k gates were not attempted after that first failure.

### Incremental update 2026-07-24/25 (wide-result shift lowering and XiangShan rerun)

The consume-on-event v7 model passed the 2,000-cycle gate (`instrCnt=3`,
`cycleCnt=1996`) but failed the required 20,000-cycle gate at `cycleCnt=8250`.
All five observed RefillBuffer cache lines were zero, so the 50,000-cycle gate was not run.
The failing GRH chain was a one-bit `SliceStatic`, followed by `Shl` with a 514-bit
result, then a 514-bit `MemoryWritePort`. The old lowering executed the shift at the
one-bit lhs width and widened only afterward, irreversibly truncating bits 1..513. The
full checkpoint contains 5,400 `kShl` operations; 3,376 have a result wider than lhs,
including 2,048 instances of 1 -> 514.

The lowering now chooses `BV<result width, lhs signedness>` as the native Type for
`kShl` / `kLShr` / `kAShr`, coerces lhs before the shift, and retains the existing
post-shift `assign` when the mapped result Signedness differs. Preserving lhs Signedness
is required for the eight signed-lhs/unsigned-result `kAShr` instances in this checkpoint.
Constant folding now applies the same resize-before-shift rule. None of the 3,376 wide
`kShl` operations in the fresh XiangShan JSON has a direct or recursively constant lhs,
and that JSON has no wide `kLShr` or `kAShr`, so the adjacent constant-fold fix does not
change the v8 product. Focused coverage checks wide `Shl`, signed wide `LShr`, signed
wide `AShr`, and their constant-fold counterparts. All eight `grhsim-am-*` CTests and
the newly registered `transform-const-fold` CTest pass.

The fresh v8 product was regenerated from
`ptmp/grhsim_am_gsim_define_v5_20260724/wolvrix_xs_post_stats.json` (SHA-256
`a2f50b37834dbf97be15f336a6e05ccc59f87a499187f2d15edd78dc1fd727ea`):

```text
linear AM instructions                   4,950,236
compute Blocks                              36,963
commit Blocks                                  497
input sink Block                                  1
normal Blocks                               37,461
normal Blocks plus B0                       37,462
changed detectors                        1,875,970
activation targets                       3,218,269
commit groups                                    1
commit operand captures                    256,085
scheduled instructions                   8,992,117
emitted artifacts                              426
```

The saved lower log records 40.26 seconds with peak RSS 28,027,228 KiB for fresh
lower/schedule/emit. The contemporaneous `/usr/bin/time -v` terminal record reports
6:19.79 with peak RSS 6,126,112 KiB for the fresh model and emu build; that build-time
record was not saved as a separate log. The resulting emu SHA-256 is
`addf9dccfdae7cd2c21620782b99faa2d817d5b1749ea5bd5f3e10f11957d212`.

CoreMark/NEMU gates for that emu were run strictly in order, starting the next gate only
after the preceding gate passed:

```text
-C 2000     PASS, instrCnt=3,     cycleCnt=1996,  host=140574 ms
-C 20000    PASS, instrCnt=14121, cycleCnt=19996, host=1542760 ms
-C 50000    PASS, instrCnt=73580, cycleCnt=49996, host=4178703 ms
             guestCycles=50001, IPC=1.471718, exit=0
```

Difftest remained enabled throughout; no mismatch, refill failure, assertion, or crash
occurred. The 50k instruction/cycle counters exactly match the existing functional
baseline. Runtime does not: 4,178,703 ms is 11.77x the 355,000 ms performance target.
This closes the functional gates, not the performance gate.

### Current full-design gates

Full SimTop schedule, bounded multi-TU emit, per-TU compilation, archive creation, difftest
link, and the strict 2k -> 20k -> 50k functional sequence are now closed on the fresh v8
model. The 50k architectural counters match the legacy baseline. The active blocker is
performance: host time is 4,178,703 ms rather than the existing <= 355,000 ms target.

### Remaining acceptance work

The ordered functional sequence above is complete. Remaining work is:

1. Profile the fresh 50k run and reduce its 4,178,703 ms host time toward the existing
   <= 355,000 ms target without changing the now-closed architectural counters.
2. Complete any still-required per-call host trace differential gate for the host-as-compute
   policy; ScheduledProgram validity and CoreMark counters do not prove host call-count parity.
3. Audit and separately fix signed widened `kShl` / `kLShr` parity in the SystemVerilog emitter;
   that backend is not used by the GRHSIM-AM v8 functional product.

The existing fast 50k gate expects `max_cycles=50000`, `guest_cycle_spent=50001`,
`guest_instr_cnt=73580`, `guest_cycle_cnt=49996`, and host time no greater than 355,000 ms.
Meeting those values on the legacy route is only a baseline; the same result must be produced
by an AM-built emu before this migration milestone is complete.
