## 2026-04-16 XiangShan GrhSIM perf snapshot

### Method

- Binary: `build/xs/grhsim/grhsim-compile/emu`
- Build reused as-is, no rebuild.
- Workload: `testcase/xiangshan/ready-to-run/coremark-2-iteration.bin`
- Command:

```bash
cd build/xs/grhsim/grhsim-compile
/usr/bin/time -p perf record -o /tmp/xs_grhsim_perf_10000_20260416.data -F 999 -g -- \
  ./emu -i /workspace/gaoruihao-dev-gpu/wolvrix-playground/testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --no-diff -b 0 -e 0 -C 10000
```

- Raw artifacts:
  - `/tmp/xs_grhsim_perf_10000_20260416.data`
  - `/tmp/xs_grhsim_perf_10000_20260416.symbols.txt`
  - `/tmp/xs_grhsim_perf_10000_20260416.children.txt`

### Run result

- Simulated cycles: `10000`
- Retired instructions: `458`
- IPC: `0.045818`
- Host time: `236349 ms`
- Average host cost per eval/cycle: `23.635 ms`

### Function-level distribution inside eval path

`perf report --stdio --no-children --sort symbol` aggregation:

| bucket | self % | approx ms / eval | note |
| --- | ---: | ---: | --- |
| `GrhSIM_SimTop::eval_batch_*` | `67.34%` | `15.916` | main cost, includes inlined operator/helper logic |
| `GrhSIM_SimTop::commit_state_shadow_chunk_*` | `23.36%` | `5.521` | shadow-state copyback |
| `GrhSIM_SimTop::commit_state_updates` | `5.34%` | `1.262` | write-port commit / state update orchestration |
| `GrhSIM_SimTop::eval` | `2.65%` | `0.626` | top-level dispatcher / loop body |
| everything else | `1.31%` | `0.310` | libc/kernel/noise |

Key point:

- Current XiangShan `grhsim` cost is dominated by `eval_batch_*` execution itself.
- `commit` is still expensive, but secondary.
- At function granularity, almost no standalone helper symbol is visible. This means most operator/helper work is already inlined into batch bodies, so its cost is accounted inside `eval_batch_*` self time.

### Batch-level hotspot view

Top sampled batches by self overhead:

| batch | self % | emitted file | LOC |
| --- | ---: | --- | ---: |
| `eval_batch_9311` | `0.16%` | `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_9311.cpp` | `7613` |
| `eval_batch_8086` | `0.16%` | `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_8086.cpp` | `6118` |
| `eval_batch_9323` | `0.15%` | `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_9323.cpp` | `7613` |
| `eval_batch_9316` | `0.15%` | `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_9316.cpp` | `7613` |
| `eval_batch_9315` | `0.15%` | `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_9315.cpp` | `7613` |
| `eval_batch_9296` | `0.15%` | `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_9296.cpp` | `7613` |
| `eval_batch_9289` | `0.15%` | `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_9289.cpp` | `7613` |
| `eval_batch_8088` | `0.15%` | `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_8088.cpp` | `6107` |

Hotspot concentration is weak:

- top 8 batches sum to only `1.22%`
- top 32 batches sum to only `4.54%`
- top 128 batches sum to only `15.41%`
- total sampled `eval_batch_*` symbols with non-zero self time: `3933`

Interpretation:

- There is no single pathological batch dominating runtime.
- The problem is broad and structural: too many batches are still expensive when they do run.
- The hottest sampled batches cluster in late topo-order regions, especially `8xxx` and `9xxx`, but each individual batch is still only around `0.14%` to `0.16%`.

### Commit-side hotspot view

Top commit shadow chunks:

| chunk | self % |
| --- | ---: |
| `commit_state_shadow_chunk_63` | `1.41%` |
| `commit_state_shadow_chunk_64` | `1.09%` |
| `commit_state_shadow_chunk_62` | `0.97%` |
| `commit_state_shadow_chunk_61` | `0.93%` |
| `commit_state_shadow_chunk_59` | `0.91%` |
| `commit_state_shadow_chunk_60` | `0.81%` |
| `commit_state_shadow_chunk_42` | `0.73%` |
| `commit_state_shadow_chunk_41` | `0.56%` |

Concentration here is somewhat stronger than batches, but still not single-point:

- top 8 commit-shadow chunks sum to `7.41%`
- top 16 sum to `11.35%`
- top 32 sum to `17.50%`
- all `commit_state_shadow_chunk_*` sum to `23.36%`

Interpretation:

- `commit` cost is spread across many state-shadow chunks.
- This still points to structural copyback pressure rather than one bad chunk.

### Conclusion

This 10k-cycle `perf` run says:

1. The first optimization target remains `eval_batch_*` execution body, not dispatcher overhead.
2. The second target remains commit shadow/copyback volume.
3. Function-level `perf` does not show a single helper symbol dominating. The hot operator logic is already folded into batch self time.
4. There is no single “giant batch” to surgically fix for an order-of-magnitude gain. The runtime issue is distributed across thousands of batches.

Practical implication:

- The next wins are likely to come from making each active batch cheaper on average, not from chasing one outlier batch.
- Separately, reducing shadow commit traffic is still worthwhile because it is a stable `~28.7%` family cost (`commit_state_updates + commit_state_shadow_chunk_*`).

## 2026-04-16 Deeper eval_batch analysis

### Goal

- Determine whether `eval_batch_*` is limited primarily by front-end pressure, branch behavior, or data access.
- Determine whether the hottest batches are diverse, or whether they collapse into a few repeated emitted code shapes.

### Micro-architectural snapshot

Command:

```bash
perf stat -d -- build/xs/grhsim/grhsim-compile/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --no-diff -b 0 -e 0 -C 3000
```

Observed:

- Host time: `72.8 s` for `3000` cycles
- Instructions: `43.67 G`
- Cycles: `268.39 G`
- IPC: `0.16`
- Branches: `15.16 G`
- Branch misses: `1.95 G` (`12.87%`)
- L1D load misses: `1.41 G` (`5.09%` of L1D loads)

Interpretation:

- `eval_batch_*` is not just “doing a lot of arithmetic”.
- IPC is extremely low, and branch miss rate is extremely high for CPU-side code.
- This strongly suggests the hot path is dominated by huge amounts of control flow and scattered state/value accesses.

Additional front-end-oriented sample:

```bash
perf stat -e L1-icache-loads,L1-icache-load-misses,dTLB-loads,dTLB-load-misses,iTLB-loads,iTLB-load-misses -- \
  build/xs/grhsim/grhsim-compile/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --no-diff -b 0 -e 0 -C 200
```

Observed:

- `L1-icache-load-misses = 47.3 M`
- `L1-icache-loads = 1697.5 M`
- L1I miss rate about `2.79%`

Interpretation:

- Front-end pressure is real, not hypothetical.
- Even without trusting every TLB counter precisely, the L1I miss rate is already too high for code that is supposed to be a tight repeatedly executed simulator hot loop.
- Combined with the branch-miss result, this points to oversized, branch-heavy emitted batch bodies as a first-class problem.

### Hot-batch disassembly pattern

Using `perf annotate` on the existing `perf.data`:

- `GrhSIM_SimTop::eval_batch_9311`
- `GrhSIM_SimTop::eval_batch_8086`

Common repeated instruction pattern:

- test one activation/source predicate
- branch around the body
- load state/value slot
- apply change-mask merge logic
- write shadow/value slot back
- test touched flag / conflict flag
- append touched index

Interpretation:

- The hottest emitted code is not dominated by one expensive helper call.
- It is dominated by long straight-line repetition of small guarded update templates.
- This is exactly the kind of code shape that hurts branch prediction, instruction cache locality, and general front-end efficiency.

### Static shape of hottest eval batches

Method:

- Took the first `16` `eval_batch_*` symbols from `/tmp/xs_grhsim_perf_10000_20260416.symbols.txt`.
- Opened the corresponding emitted `grhsim_SimTop_sched_*.cpp` files.
- Counted rough structural markers in the generated C++.

Per-batch summary over those 16 hottest batches:

| metric | avg | median | min | max |
| --- | ---: | ---: | ---: | ---: |
| LOC | `7426.4` | `7614` | `6108` | `7614` |
| `// op` count | `575.9` | `576` | `575` | `576` |
| supernodes per batch | `8.0` | `8` | `8` | `8` |
| `if (` count | `1083.5` | `1160` | `538` | `1160` |
| `grhsim_*(` helper calls | `622.7` | `576` | `576` | `960` |
| `grhsim_mark_pending_write` count | `567.0` | `576` | `504` | `576` |
| `event_edge_slots_[]` refs | `1062.5` | `1149` | `459` | `1149` |
| `value_*_slots_[]` refs | `2284.6` | `2304` | `2137` | `2304` |
| `state_*_slots_[]` refs | `3070.1` | `3456` | `306` | `3456` |
| `supernode_active_curr_[...] |=` count | `2.9` | `0` | `0` | `26` |

Two especially important patterns:

- The `93xx` hot batch cluster is almost identical batch-to-batch:
  - about `7614` LOC
  - `576` ops
  - `1160` `if`s
  - `576` pending writes
  - `1146` to `1149` event-edge references
  - `3456` state-slot references
  - `0` activation ORs
- This looks like sink-heavy / state-update-heavy batches, not propagation-heavy batches.

- The `8086` / `8088` style hot batches are slightly shorter:
  - about `6.1k` LOC
  - still `575` to `576` ops
  - fewer `if`s
  - more helper calls
  - some activation ORs still present

Interpretation:

- The hottest batches are not diverse. A large fraction collapse into a few repeated structural templates.
- This is good news for optimization: emitter-level shape changes can pay off broadly.
- It also means deeper per-op runtime logging is not immediately necessary to choose the next optimization direction.

### Updated optimization priority for eval_batch

Priority 1:

- Reduce emitted branch density and repeated guarded update templates inside sink/state-heavy batches.
- In particular, attack the repeated:
  - predicate test
  - shadow-base select
  - masked merge
  - touched/conflict bookkeeping
  - touched-index append

Priority 2:

- Reduce front-end footprint of hot batches.
- Large repeated straight-line batches around `6k` to `7.6k` LOC are already showing measurable L1I pain.

Priority 3:

- Reduce random value/state pool traffic where possible, especially in sink-heavy write clusters.

Not the first priority right now:

- dispatcher-level batch scanning
- chasing one “bad” helper function
- chasing one pathological batch outlier

### Practical conclusion

For the current `eval_batch_*` optimization phase, a deeper analysis pass was necessary, and it already changed the recommendation:

- The next work should focus on restructuring emitted batch bodies, not on tiny arithmetic helper tweaks.
- A promising target is the sink/state-write template itself, because it appears in many of the hottest batches nearly verbatim.
- Additional intrusive runtime counters can be deferred until after the first emitted-code-shape simplification pass, unless that pass fails to move IPC / branch miss / L1I miss in the expected direction.

## 2026-04-16 Scalar state-write emit refactor: first perf result

### Change summary

Implemented a first emit-side compression for sink-heavy scalar state writes:

- Added non-inlined scalar state-write helpers in `grhsim_SimTop_state.cpp`
- Lowered continuous scalar register/latch write runs to:
  - one shared `eventExpr` guard
  - repeated helper calls
- Removed repeated in-batch expansion of:
  - shadow-base selection
  - masked merge
  - conflict bookkeeping
  - touched-index append

Observed emitted code shrink on previously hottest batches:

| batch | old LOC | new LOC | delta |
| --- | ---: | ---: | ---: |
| `9311` | `7613` | `1297` | `-83.0%` |
| `8086` | `6118` | `5420` | `-11.4%` |

### Rebuild

Command:

```bash
/usr/bin/time -p make xs_wolf_grhsim_emu WOLVRIX_GRHSIM_WAVEFORM=0 WOLVRIX_GRHSIM_PERF=0
```

Observed:

- full rebuild wall time: `650.10 s`
- GrhSIM model compile still uses `clang++ -std=c++20 -O3`

### Perf stat comparison: 3000-cycle main run

Command:

```bash
perf stat -d -- build/xs/grhsim/grhsim-compile/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --no-diff -b 0 -e 0 -C 3000
```

Before:

- host time: `72.8359 s`
- instructions: `43.6729 G`
- cycles: `268.3878 G`
- IPC: `0.16`
- branch miss rate: `12.87%`
- L1D miss rate: `5.09%`

After:

- host time: `55.2955 s`
- instructions: `61.5251 G`
- cycles: `203.7590 G`
- IPC: `0.30`
- branch miss rate: `5.90%`
- L1D miss rate: `3.77%`

Delta:

- host time: `-24.1%`
- cycles: `-24.1%`
- IPC: about `+87.5%`
- branch miss rate: `-54.2%`
- L1D miss rate: `-25.9%`

Per-eval host cost estimate:

- before: about `23.64 ms / eval`
- after: about `18.43 ms / eval`

Interpretation:

- This change materially improved the actual `eval_batch_*` hot path.
- The branch-miss collapse is the clearest confirmation that the repeated emitted write template was a major structural cost.
- IPC improvement is large enough that the change is not merely “slightly better code size”; it is reducing control-flow/pathology in a meaningful way.

### Perf stat comparison: 200-cycle front-end probe

Command:

```bash
perf stat -e L1-icache-loads,L1-icache-load-misses,dTLB-loads,dTLB-load-misses,iTLB-loads,iTLB-load-misses -- \
  build/xs/grhsim/grhsim-compile/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --no-diff -b 0 -e 0 -C 200
```

Before:

- host time: `8.998 s`
- `L1-icache-load-misses`: `47.29 M`
- L1I miss rate: `2.79%`
- `dTLB-load-misses`: `347.7 K`
- `iTLB-load-misses`: `21.52 M`

After:

- host time: `6.721 s`
- `L1-icache-load-misses`: `44.01 M`
- L1I miss rate: `2.73%`
- `dTLB-load-misses`: `180.8 K`
- `iTLB-load-misses`: `18.60 M`

Interpretation:

- Front-end pressure improved, but not dramatically.
- The stronger win is still from reducing branch/control-flow overhead.
- There is still substantial instruction-fetch / TLB pressure left in the emitted codebase.

### Updated conclusion

This first `eval_batch_*` emit refactor is clearly worth keeping:

- It gives a real end-to-end XiangShan speedup of about `24%` on the 3000-cycle perf probe.
- It validates the thesis that sink/state-write template explosion was one of the main structural bottlenecks.

But it is not enough for the long-term target:

- `18.4 ms / eval` is still far from the sub-`1 ms / eval` goal.
- The next major wins still need to come from broader batch-body simplification, not just this one template family.

## TODO: Next eval_batch optimizations

### P0. Scalar value change-detect template compression

Target template:

- `const auto next_value = ...;`
- `if (value_*_slots_[...] != next_value) { ... }`

Current scale:

- about `1.396M` `next_value` materializations
- about `1.410M` scalar `if (old != next_value)` guards

Why it matters:

- This is now the largest repeated template family left in emitted batch bodies.
- It often immediately feeds activation propagation and/or event-edge updates.

Possible direction:

- compress repeated scalar assignment/change-detect into typed helpers
- special-case pure “assign + activate” form
- special-case “assign + classify_edge + activate” form

Success metric:

- lower branch miss rate further
- lower `eval_batch_*` self time in `perf`
- reduce emitted LOC in hot early/mid batches

Status:

- pending

### P1. Value-change activation template compression

Target template:

- `supernode_active_curr_[...] |= ...`
- especially repeated fanout propagation after scalar value change

Current scale:

- about `2.457M` activation OR statements in emitted schedules

Why it matters:

- This is the single largest repeated emitted side-effect pattern.
- It is tightly coupled with P0, so compressing one without the other will leave a lot of overhead.

Possible direction:

- expand table-driven activation more aggressively
- canonicalize repeated fanout sets into shared static tables
- avoid re-emitting short unrolled activation clusters when loop/table form is cheaper

Success metric:

- lower branch count
- lower I-cache footprint in hot batches
- lower emitted total LOC

Status:

- pending

### P2. Scalar state-read / state-derived value compare-and-publish compression

Target template:

- `if (value_*_slots_[...] != state_logic_*_slots_[...]) { ... }`
- same logical family as scalar value change-detect, but RHS comes directly from state

Current scale:

- about `189k` direct scalar value-vs-state compare/update guards

Why it matters:

- This is another very common scalar publish pattern.
- It should be compressible using the same typed helper strategy as P0.

Possible direction:

- introduce typed “publish from state if changed” helpers
- fold direct state read + change detect + activation into one helper

Success metric:

- fewer repeated compare/store blocks
- smaller hot read-heavy batches

Status:

- pending

### P3. Wide value/state change-detect helper tightening

Target template:

- `if (grhsim_assign_words(...)) { ... }`
- `grhsim_merge_words_masked(...)`

Current scale:

- about `10,699` `grhsim_assign_words(...)` change checks
- about `1,813` `grhsim_merge_words_masked(...)` writes

Why it matters:

- The count is much lower than scalar templates, but each instance is individually expensive.

Possible direction:

- tighten helper implementation
- reduce temporary materialization
- specialize hottest widths if data shows concentration

Success metric:

- lower cycles per wide-heavy batch cluster
- improved `perf annotate` around wide helpers

Status:

- pending

### P4. Event-guard block coalescing

Target template:

- `if (((event_edge_slots_[...] == ...))) { ... }`

Current scale:

- about `12,344` explicit event-guard blocks

Why it matters:

- The first scalar state-write refactor already proved that shared event guards are valuable.
- There are likely more cases where same-event blocks can be merged further.

Possible direction:

- coalesce same-event scalar publish/update runs
- hoist event predicates and reduce repeated exact-event control flow

Success metric:

- lower branch miss
- smaller batch source size in event-heavy regions

Status:

- pending

## 2026-04-16 P0-P2 combined refactor: helperized scalar tracked update + centralized activation groups

### Change summary

Implemented P0-P2 together in `grhsim_cpp` emitter:

- scalar tracked value update now lowers to typed helpers:
  - `apply_tracked_scalar_value_bool`
  - `apply_tracked_scalar_value_u8`
  - `apply_tracked_scalar_value_u16`
  - `apply_tracked_scalar_value_u32`
  - `apply_tracked_scalar_value_u64`
- helper semantics are unified:
  - compare old/new
  - optional `grhsim_classify_edge`
  - optional same-word local activation via `activeWordFlags |= localMask`
  - optional global activation propagation via shared activation-group table
  - final store
- direct scalar state-read publish now uses the same helper path when the value is materialized and tracked
- per-site inline activation OR clusters were replaced by `activationGroupId + localMask` metadata
- stale `old_word` temporaries in remaining inline activation emit were removed

### Validation

- `cmake --build wolvrix/build -j8`: pass
- `make xs_wolf_grhsim_emit WOLVRIX_GRHSIM_WAVEFORM=0 WOLVRIX_GRHSIM_PERF=0`: pass
- XiangShan emit wall time:
  - `real 345.35 s`
  - `write_grhsim_cpp 192462 ms`

### Static emitted-code result

Schedule-side template counts after this refactor:

| metric | before | after |
| --- | ---: | ---: |
| scalar `next_value` materializations (`const auto next_value = static_cast<...>`) | `~1,395,941` | `21,600` |
| scalar `if (old != next_value)` guards | `~1,409,585` | `35,248` |
| total `const auto next_value = ...` in schedules | not recorded separately | `36,304` |
| direct scalar `value != state_*` publish guards | `~189,098` | `0` |
| inline `supernode_active_curr_[...] |= ...` in schedules | `~2,456,856` | `64,700` |
| helper calls `apply_tracked_scalar_value_*` | `0` | `1,563,444` |
| remaining inline local table blocks `kActivationMasks[]` in schedules | many | `15` |

Representative schedule file sizes:

| file | old LOC | new LOC | note |
| --- | ---: | ---: | --- |
| `grhsim_SimTop_sched_1.cpp` | not recorded | `2,370` | now helper-call heavy |
| `grhsim_SimTop_sched_8086.cpp` | `6,118` | `5,279` | moderate shrink |
| `grhsim_SimTop_sched_9311.cpp` | `1,297` | `1,297` | unchanged from previous sink-write refactor |

### Important side effect

The centralized activation-group registry is currently extremely large:

- `grhsim_SimTop_state.cpp`: `49 MiB`
- `grhsim_SimTop_state.cpp`: `965,283` LOC
- unique tracked activation groups emitted into `state.cpp`: `229,848`

Interpretation:

- P0/P1/P2 were structurally achieved on the schedule side.
- Branch-heavy compare/publish/activate templates were successfully collapsed.
- But the current P1 implementation shifted a large amount of code volume into one giant `state.cpp`.

This means the refactor is only half-finished from a compile-performance standpoint:

- schedule TUs should compile faster and be much smaller
- `state.cpp` is now a likely compile bottleneck
- the next step should focus on compressing activation-group metadata further, not just celebrating schedule shrink

### P5. Memory read / row-index template review

Target template:

- `const std::size_t row = grhsim_index_words(...);`

Current scale:

- about `889` row-index computations

Why it matters:

- Not the first bottleneck, but still worth keeping on the list for later.

Possible direction:

- hoist repeated row computation inside local clusters
- avoid duplicate bounds/default paths when the same row is reused

Success metric:

- local improvements in memory-heavy batches

Status:

- deferred

### P6. System-task / side-effect sink compression

Target template:

- `execute_system_task(...)`

Current scale:

- about `7,237` emitted system-task calls

Why it matters:

- Probably not the main performance bottleneck today.
- Keep it tracked because it still contributes code size in sink-heavy regions.

Possible direction:

- reduce repeated argument materialization where safe
- merge repeated formatting-side glue if it appears in hot batches

Success metric:

- secondary code-size reduction only

Status:

- deferred

### Execution order

Recommended order:

1. P0 scalar value change-detect compression
2. P1 activation template compression
3. P2 scalar state-read publish compression
4. Re-run XiangShan `perf`
5. P3 wide helper tightening
6. P4 event-guard coalescing

Rationale:

- P0 and P1 attack the largest remaining repeated template chain directly.
- P2 is structurally similar and should compose naturally with P0.
- P3/P4 are important, but should follow after the scalar template family is reduced.

## 2026-04-16 rollback: tracked scalar helperization reverted

Reason:

- The `apply_tracked_scalar_value_*` / activation-group helperization moved hot-path scalar publish logic out of line and regressed runtime.
- This section corrects the earlier mistaken perf reading: the `69.94s` result was measured on the helperized version, not on the intended rolled-back version.

Rollback scope:

- Reverted tracked scalar helper-call lowering in `wolvrix/lib/emit/grhsim_cpp.cpp`.
- Removed emitted `apply_tracked_scalar_value_*` helpers and activation-group tables from generated `state.cpp`.
- Restored expanded in-schedule `if (old != next) { edge; activate; assign; }` emission.
- Kept the earlier scalar state-write sink compression (`apply_scalar_state_write_*`).

Validation:

- `cmake --build wolvrix/build -j8`: pass
- `make xs_wolf_grhsim_emu WOLVRIX_GRHSIM_WAVEFORM=0 WOLVRIX_GRHSIM_PERF=0`: pass

Emit / build facts:

- XiangShan emit (`xs_wolf_grhsim_emit`) on 2026-04-16:
  - `write_grhsim_cpp = 188439 ms`
  - total emit path after stats-json resume: `313732 ms`
- activity-schedule result:
  - `supernodes = 84314`
  - `ops_mean = 64.796`
  - `ops_median = 71`
  - `ops_p90 = 72`
  - `ops_p99 = 72`
  - `ops_max = 72`
- generated artifacts after rollback:
  - `build/xs/grhsim/grhsim_emit/grhsim_SimTop_state.cpp = 28781 B`
  - `build/xs/grhsim/grhsim-compile/emu = 258875344 B`

Perf comparison (`coremark-2-iteration.bin`, `-C 3000`):

| version | host time | cycles | instructions | IPC | branch miss | L1D miss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| helperized wrong version | `69.94 s` | `258.25 G` | `64.44 G` | `0.25` | `4.64%` | `3.82%` |
| rolled-back current version | `60.88 s` | `224.68 G` | `61.57 G` | `0.27` | `5.97%` | `3.78%` |
| earlier better baseline | `55.30 s` | `203.76 G` | not re-collected here | `0.30` | `5.90%` | `3.77%` |

Interpretation:

- Rolling back helperization recovered about `9.06 s` host time, about `13%` faster than the helperized version.
- The rollback also reduced total cycles from `258.25 G` to `224.68 G`.
- Even after rollback, current runtime is still slower than the earlier `55.30 s` baseline, so the helperization revert is necessary but not sufficient.

## 2026-04-16 10000-cycle perf refresh

Command:

- `perf stat -d -- build/xs/grhsim/grhsim-compile/emu -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin --no-diff -b 0 -e 0 -C 10000`

Observed execution state:

- `pc = 0x800027c6`
- `instrCnt = 458`
- `cycleCnt = 9996`
- `IPC = 0.045818`

Perf result:

| run | host time | cycles | instructions | IPC | branch miss | L1D miss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `3000` cycles | `60.88 s` | `224.68 G` | `61.57 G` | `0.27` | `5.97%` | `3.78%` |
| `10000` cycles | `230.88 s` | `851.56 G` | `203.40 G` | `0.24` | `6.04%` | `3.81%` |

Interpretation:

- Perf shape stays broadly consistent after extending to `10000` cycles.
- The model does continue to make forward progress; this run no longer exhibits the earlier `pc=0x0 / instrCnt=3` early-stop signature.
- Average host cost is still about `23.1 ms / simulated cycle`, which is far above the target.
