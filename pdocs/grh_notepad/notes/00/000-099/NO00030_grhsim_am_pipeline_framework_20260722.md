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

1. The production AM scheduler now classifies indivisible DAG atoms as `Compute`, `Commit`,
   or `Isolated`. Pure instructions and state reads use the compute cap
   `maxInstructionsPerBlock` (default 128); state-targeted reg/latch/memory writes use the
   independent `maxCommitInstructionsPerBlock` cap (default 4096); both are bounded by
   `maxStateWritesPerBlock` (default 4096). Same-class Kahn-ready atoms can coarsen only when
   all limits hold. Host calls remain isolated until a typed merge rule is proved; raw
   `changed` is compute-class but keeps its direct-event lifetime and activation rules.
   Oversized indivisible atoms remain whole and are reported. Final state/memory watchers are
   still materialized only at their final write frontier.
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

### Incremental update 2026-07-23 (full SimTop Block/TU boundary)

The legacy scheduler's `supernode` and an AM normal `Block` are corresponding activity-driven
execution units. A Block is therefore an indivisible semantic unit for C++ emission: the
emitter may pack complete Blocks into multiple translation units, but it must never split one
Block's instruction sequence across translation units. The generated `_part_N.cpp` suffix
means a physical continuation containing later complete Block cases, not part of a Block.

The canonical legacy plain result contains 72,682 supernodes (72,180 compute and 502 commit).
The fresh AM event-bucket schedule contains 51,600 normal Blocks plus B0:

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

Fresh artifact audit for
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

### Current full-design gates

Full SimTop schedule, bounded multi-TU emit, per-TU compilation, archive creation, difftest
link, and the 100-cycle smoke gate are now closed. The active blocker is the first incorrect
architectural event at cycle 568; 2k/20k/50k remain open.

### Remaining acceptance order

The gates must close in this order; a small generated-model test cannot substitute for a
later gate:

1. Emit the complete SimTop as bounded multi-TU C++ with no partial publication.
2. Compile every shard and create `libgrhsim_SimTop.a`.
3. Link the XiangShan difftest emu and resolve all 34 DPI symbols.
4. Run CoreMark/NEMU difftest at 100 and 2,000 cycles; fix the first semantic mismatch.
5. Measure the sparse runtime at 2,000 cycles and adjust AM block coarsening only if the
   remaining dispatch/activation profile requires it.
6. Run 20,000 and 50,000 cycles with no mismatch, assertion, fatal termination, or skipped
   difftest.

The existing fast 50k gate expects `max_cycles=50000`, `guest_cycle_spent=50001`,
`guest_instr_cnt=73580`, `guest_cycle_cnt=49996`, and host time no greater than 355,000 ms.
Meeting those values on the legacy route is only a baseline; the same result must be produced
by an AM-built emu before this migration milestone is complete.
