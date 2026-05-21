# NO0097: no0162 Hot Batch Anatomy

Date: 2026-05-21

## Goal

Use existing `no0162` generated artifacts to decide whether the next no-fresh A/B should target top-level batch dispatch or batch-internal code shape.

No fresh emit, no build, no simulation.

## Artifact

- Generated model: `tmp/no0162_xs_assign_fullword_fastpath/grhsim_emit`
- Existing perf data: `build/logs/xs/no0162_fullword_fastpath_coremark20k.perf.data`

## Batch Shape Summary

Static counts:

| metric | value |
| --- | ---: |
| `eval_*_batch_*` functions | 994 |
| sched `.cpp` files | 994 |
| total active-block checks | 74,945 |
| average active-block checks per batch | 75.4 |
| max active-block checks in one batch | 296 |
| active/storage/value related matches | 1,115,989 |
| slot/storage refs in sched files | 4,850,483 |

This means the cost is not just 994 top-level C++ calls. Each batch body contains substantial internal active dispatch and slot/storage access code.

## Top Commit Batches

Top commit batches from the existing 20k perf report are mostly single-active-block functions:

| batch | perf overhead | lines | active blocks | commit table calls | storage refs | value slots |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 990 | 0.91% | 59,862 | 1 | 30 | 4,096 | 5,242 |
| 951 | 0.91% | 56,555 | 1 | 19 | 4,096 | 8,042 |
| 977 | 0.83% | 59,147 | 1 | 61 | 4,096 | 5,094 |
| 979 | 0.82% | 61,182 | 1 | 6 | 4,096 | 5,092 |
| 968 | 0.79% | 64,187 | 1 | 6 | 4,096 | 5,011 |
| 923 | 0.75% | 61,392 | 1 | 12 | 4,096 | 3,583 |
| 943 | 0.70% | 59,681 | 1 | 15 | 4,096 | 5,696 |
| 955 | 0.64% | 61,826 | 1 | 51 | 4,096 | 6,131 |

All these hot commit batches have exactly one active block and 4,096 storage refs. That points to huge commit supernode bodies and generic state/value access, not top-level dispatch overhead.

Across the whole generated model:

| metric | value |
| --- | ---: |
| files with `apply_commit_scalar_state_write_table` | 88 |
| commit table calls | 3,732 |
| max table calls in one file | 192 in `sched_914` |

The helper is visible, but its self time is only about `1.09%` in the existing perf report. The surrounding batch bodies are the larger problem.

## Top Compute Batches

Representative top compute batches:

| batch | perf overhead | lines | active blocks | changed flag refs | storage refs | value slots |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 259 | 0.39% | 43,969 | 80 | 9,142 | 2,210 | 7,162 |
| 576 | 0.38% | 47,995 | 80 | 6,195 | 632 | 14,433 |
| 261 | 0.38% | 44,230 | 80 | 9,289 | 2,240 | 7,120 |
| 869 | 0.38% | 6,276 | 80 | 404 | 0 | 3,866 |
| 854 | 0.37% | 10,650 | 8 | 180 | 75 | 1,960 |

Compute heat comes from many active-block tests plus changed-flag propagation, while commit heat comes from very large single active blocks.

## Interpretation

The next A/B should not start by only reducing the 994 top-level calls. The hot commit functions already have one active block, so merging or wrapping top-level calls would not remove their dominant internal code.

Stronger target:

1. Reduce huge commit batch body footprint without increasing BAE or commit supernode count in the way NO0134 did.
2. Reduce per-supernode storage/value alias bulk in hot commit batches without repeating the known-bad direct storage-ref text replacement.
3. For compute batches, target active-block dispatch and changed-flag fanout, not outer function call count.

## Next No-Fresh A/B Candidate

A useful no-fresh prototype should operate on existing `no0162` generated files and answer one of these:

- Can hot commit batches reduce their always-emitted alias/code footprint while preserving the same active condition and same schedule?
- Can compute batches group repeated active-block changed-flag writes into denser word-level operations without changing activation semantics?

Any prototype must rebuild only the existing generated model archive and run 20k CoreMark with difftest before being considered.
