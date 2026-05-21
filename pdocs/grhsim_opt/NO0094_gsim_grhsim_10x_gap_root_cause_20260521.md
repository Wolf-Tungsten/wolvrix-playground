# NO0094: gsim vs grhsim 10x Gap Root-Cause Snapshot

Date: 2026-05-21

## Goal

Find the root cause of the roughly 10x XiangShan CoreMark runtime gap between `gsim` and `grhsim`, then use that cause to guide performance alignment.

This note intentionally avoids another fresh emit. The next useful work should be cheap A/B experiments on existing generated artifacts unless the experiment specifically changes emitter output.

## Baseline Evidence

Same CoreMark 50k style runs:

| model | log | host time |
| --- | --- | ---: |
| `gsim` | `tmp/xs_grhsim_gsim_struct_20260506_144707/logs/gsim_coremark_50k.log` | 32492 ms |
| early `grhsim` | `tmp/xs_grhsim_gsim_struct_20260506_144707/logs/grhsim_coremark_50k.log` | 282707 ms |
| current `grhsim no0162` | `build/logs/xs/xs_wolf_grhsim_20260521_no0162_fullword_fastpath_50k.summary.log` | 350265 ms |

`no0162` is about 10.8x slower than the `gsim` reference. The current full-word helper improvement is real relative to `xs_wolf_grhsim_20260521_codex_current_improved_50k.log` (`432935 ms` -> `350265 ms`), but it does not close the main gap.

20k perf runs show the same shape:

| model | perf data | host time |
| --- | --- | ---: |
| `gsim` | `build/logs/xs/gsim_coremark20k_20260521.perf.data` | 10573 ms |
| `grhsim no0162` | `build/logs/xs/no0162_fullword_fastpath_coremark20k.perf.data` | about 99 s |

Phase timing already showed this is not difftest dominated:

| model | total | model eval | difftest |
| --- | ---: | ---: | ---: |
| `gsim` 20k phase timing | 19287 ms | not separately instrumented | 65267 us |
| `grhsim no0162` 20k phase timing | 110409 ms | 110251621 us | 119173 us |

Conclusion: the gap is inside generated model evaluation.

## Code-Shape Differences

`gsim`:

- `build/xs/gsim/gsim-compile/model/SimTop330.cpp:17330` contains `SSimTop::step()`.
- `SSimTop::step()` calls 329 `subStep*()` functions.
- Hot time is distributed across `SSimTop::subStep*()` symbols; the top symbol is only about 2.2% in the 20k perf report.
- Generated activation writes are dense and compiler-visible, commonly `activeFlags[idx] |= cond << bit` or word-level masked OR.

`grhsim no0162`:

- `tmp/no0162_xs_assign_fullword_fastpath/grhsim_emit/grhsim_SimTop_eval.cpp` calls 884 compute batches and 110 commit batches per eval round.
- Perf top is concentrated under `GrhSIM_SimTop::eval()` with many hot `eval_commit_batch_9xx()` symbols.
- `apply_commit_scalar_state_write_table(...)` is itself visible in perf at about 1.09%, and the commit batches that call it dominate the top of the symbol list.
- Generated state access uses generic storage and repeated `grhsim_value_storage_ref(...)`.

20k perf symbol aggregation from `build/logs/xs/no0162_fullword_fastpath_coremark20k.perf.data`:

| bucket | listed overhead |
| --- | ---: |
| `eval_compute_batch_*` | 62.14% |
| `eval_commit_batch_*` | 33.58% |
| `apply_commit_scalar_state_write_table` self | 1.09% |
| other `grhsim_*` helpers | 1.62% |

The comparable `gsim` perf sample has 98.10% listed under `SSimTop::subStep*()`, but distributed across 329 substeps rather than split into `884 + 110` grhsim batch calls.

Top individual grhsim compute batches are very small:

| symbol | overhead |
| --- | ---: |
| `eval_compute_batch_259` | 0.39% |
| `eval_compute_batch_576` | 0.38% |
| `eval_compute_batch_261` | 0.38% |
| `eval_compute_batch_869` | 0.38% |
| `eval_compute_batch_854` | 0.37% |

Top individual commit batches are larger but still distributed:

| symbol | overhead |
| --- | ---: |
| `eval_commit_batch_990` | 0.91% |
| `eval_commit_batch_951` | 0.91% |
| `eval_commit_batch_977` | 0.83% |
| `eval_commit_batch_979` | 0.82% |
| `eval_commit_batch_968` | 0.79% |

This rules against a single hot helper or single broken batch as the main explanation.

Static counts in `no0162` generated code:

| item | count |
| --- | ---: |
| `apply_commit_scalar_state_write_table(` calls | 3734 raw matches, 3732 call sites/tables |
| `grhsim_value_storage_ref` occurrences | 1611417 |

Commit scalar table structure:

| metric | value |
| --- | ---: |
| tables | 3732 |
| entries | 22737 |
| homogeneous tables | 3363 |
| homogeneous entries | 19864 |
| mixed tables | 369 |

Homogeneous entries by kind:

| kind | entries |
| --- | ---: |
| bool | 4071 |
| u8 | 4129 |
| u16 | 604 |
| u32 | 117 |
| u64 | 10943 |

Most commit tables are statically homogeneous, but `no0162` still runs a per-entry `switch (entry.kind)` in `apply_commit_scalar_state_write_table`. This is a useful diagnostic entry point, but historical experiments show it is not enough by itself:

- NO0131 generated typed helpers for homogeneous tables. It reduced generic table calls to `371` and generated `3373` typed table calls, but 50k runtime became `351903 ms`, about `0.83%` slower than the comparison point.
- NO0143 inlined commit scalar tables and reduced `apply_commit_scalar_state_write_table(` to declaration/definition only, but 20k runtime regressed to `117531 ms`.

So the stronger conclusion is not "the `switch(kind)` is the root cause"; it is "commit-side generated-code shape is wrong". Removing one helper dispatch does not fix the deeper issues: many hot commit batches, generic state storage, fragmented calls, and larger code footprint when naively inlined.

## Current Root-Cause Hypothesis

The 10x gap is not explained by difftest, not explained by wide-word helpers alone, and not fixed by activity-schedule coarsening alone.

The strongest current root-cause candidate is generated-code shape:

1. `grhsim` emits a much more fragmented top-level schedule (`884 + 110` batch calls versus `gsim`'s 329 substeps).
2. Both compute and commit batch bodies carry more generic storage/helper machinery than gsim's direct generated C++.
3. `grhsim` commit-side code is table/helper driven, while `gsim` emits direct specialized state updates.
4. `grhsim` state access remains generic (`state_logic_storage_` plus `grhsim_value_storage_ref`), reducing compiler visibility and adding address calculation/indirection.
5. `grhsim` activation writes are less aggressively coalesced than `gsim`'s word-level masked OR style.

The immediate bottleneck candidate is commit-side generated-code shape, especially batch fragmentation and generic state access. Helper dispatch is only a symptom and already has negative A/B evidence when attacked directly.

## No-Fresh-Emit A/B Plan

Use existing `tmp/no0162_xs_assign_fullword_fastpath` artifacts.

Priority A/B candidates:

1. Reduce compute/commit batch fragmentation without changing activity scheduling. Patch generated `eval()` or generated batch grouping to reduce top-level calls, then relink and run 20k. This tests call/front-end fragmentation while preserving the existing scheduled bodies.
2. Reduce generic storage/helper machinery in compute batches first, because perf aggregation shows `eval_compute_batch_*` is about 62% of listed overhead. Candidate: direct typed storage refs or more scalarized/direct value access in hot generated files.
3. Reduce commit-side state storage indirection for one dominant typed class, especially homogeneous `u64`, toward direct typed arrays or precomputed typed pointers. This tests whether `grhsim_value_storage_ref` and generic storage layout are the commit-side cost driver.
4. Compare compile/runtime after changing batch granularity in the generator only if a no-fresh-emit prototype shows movement.

Avoid repeating direct helper-specialization experiments unless there is new perf evidence, because NO0131 and NO0143 already showed that removing `switch(kind)` or inlining tables alone is negative.

Also avoid repeating `GRHSIM_EMIT_ACTIVE_BATCH_WORKLIST=1` as currently implemented. NO0122 generated `schedule_batch_active_` and `mark_active_word_batches`, but 50k regressed to `651563 ms` versus the `358037 ms` comparison point. That experiment was not a perfectly clean A/B because the schedule also changed, but it is enough evidence that the current switch-based batch worklist implementation is not a safe primary direction.

No-fresh-emit rebuild command:

```sh
NOOP_HOME=/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan \
make -C /home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/difftest \
  grhsim-build-emu \
  BUILD_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/no0162_xs_assign_fullword_fastpath_emu \
  GEN_CSRC_DIR=/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/build/generated-src \
  NUM_CORES=1 WITH_CHISELDB=0 WITH_CONSTANTIN=0 \
  GRHSIM=1 \
  GRHSIM_MODEL_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/no0162_xs_assign_fullword_fastpath/grhsim_emit \
  WOLVRIX_GRHSIM_WAVEFORM=0
```

This target uses `testcase/xiangshan/difftest/grhsim.mk`; it rebuilds `libgrhsim_SimTop.a` from the existing generated model directory and relinks `tmp/no0162_xs_assign_fullword_fastpath_emu/grhsim-compile/emu`. It does not run `wolvrix_xs_grhsim.py` and does not emit new model C++.

## Rejected Or Weak Directions

Do not repeat these as primary next steps without new evidence:

- C4 dynamic with `DOWN_MERGE=1`.
- ctz active dispatch.
- global ternary mux.
- standalone `slice_u64_words`.
- storage-ref alias threshold tuning.
- scalar mux trivial simplification.

## Acceptance Criteria For Root-Cause Closure

The root cause should not be considered closed until at least one no-fresh-emit A/B shows a clear runtime movement and corresponding perf movement:

- 20k CoreMark with difftest still passes to cycle limit.
- Runtime changes in the expected direction.
- Perf top shows reduced `apply_commit_scalar_state_write_table` or reduced `eval_commit_batch_9xx` weight.
- The change can be mapped back to a concrete generator change.
