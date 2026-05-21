# NO0096: gsim/grhsim Frontend Pressure Evidence

Date: 2026-05-21

## Goal

Pin down the current evidence for the roughly 10x XiangShan CoreMark gap between `gsim` and `grhsim`, without another fresh emit.

This is a short evidence note. It does not claim root-cause closure by itself.

## Runtime Gap

Existing 50k logs:

| model | log | host time |
| --- | --- | ---: |
| `gsim` | `tmp/xs_grhsim_gsim_struct_20260506_144707/logs/gsim_coremark_50k.log` | `32492ms` |
| early `grhsim` | `tmp/xs_grhsim_gsim_struct_20260506_144707/logs/grhsim_coremark_50k.log` | `282707ms` |
| current `grhsim no0162` | `build/logs/xs/xs_wolf_grhsim_20260521_no0162_fullword_fastpath_50k.summary.log` | `350265ms` |

`no0162` is about `10.78x` slower than the `gsim` reference on this log pair.

The 50k `no0162` progress log shows normal difftest-enabled execution to the cycle limit:

| cycle | host_ms |
| ---: | ---: |
| 10000 | 23471 |
| 20000 | 98988 |
| 30000 | 177659 |
| 40000 | 257876 |
| 50000 | 350253 |

## Static Code Shape

Existing generated artifacts:

| metric | `gsim` | `grhsim no0162` | ratio |
| --- | ---: | ---: | ---: |
| generated `.cpp` files | 331 | 1036 | 3.13x |
| generated `.cpp` lines | 13,729,995 | 20,863,956 | 1.52x |
| top-level scheduled functions | 329 `subStep*` | 994 `eval_*_batch_*` | 3.02x |
| emu file size | 56,020,248 B | 115,609,560 B | 2.06x |
| emu `.text` | 55,892,978 B | 114,315,479 B | 2.05x |

The current `grhsim` model has about 2x code text and about 3x top-level dispatch functions versus `gsim`. This is enough to make frontend/cache/iTLB pressure plausible, but not enough alone to explain the full 10x runtime gap.

## Existing Perf Evidence

Earlier perf documents already show the missing multiplier:

- `NO0087`: `grhsim` 50k was about `11.6x` slower while retired host instructions were only `3.45x`; IPC dropped from `0.42` to `0.12`.
- `NO0089`: dynamic branches were `7.60x`, branch misses `8.69x`, L1I misses `6.39x`, iTLB loads `6.67x`.
- `NO0145`: a good `grhsim` point still had `IPC=0.17`, `branch-miss-rate=38.08%`, and `iTLB-load-miss-rate=52.58%`.
- `NO0150/NO0151`: later runs still showed frontend/branch symptoms, including `stalled-cycles-frontend=86.51%` in the recorded 20k perf stat.

Current `no0162` 20k perf report also shows no single dominant helper:

| bucket | listed overhead |
| --- | ---: |
| `eval_compute_batch_*` | about `62%` |
| `eval_commit_batch_*` | about `34%` |
| `apply_commit_scalar_state_write_table` self | about `1.09%` |

So the gap is distributed across generated model evaluation, not a single runtime helper.

## Stronger Current Hypothesis

The root cause is generated-code shape, specifically frontend-heavy control flow plus generic state/value access:

1. `grhsim` dispatches many more scheduled functions per eval round.
2. Batch bodies contain many active checks, changed flags, slot aliases, and generic storage references.
3. The larger `.text` and branch/control-flow footprint match the measured low IPC, high branch miss, and high iTLB pressure.
4. The commit helper/table path is visible but not sufficient as a standalone explanation; previous helper specialization and inline-table experiments were neutral or negative.

## What This Rules Out

Do not treat these as primary next steps without new evidence:

- Fresh emit as a default diagnostic step.
- Direct `grhsim_value_storage_ref` text replacement.
- Storage-ref alias threshold tuning.
- Commit scalar table helper specialization alone.
- Inline commit scalar tables alone.
- Current active batch worklist form.
- `ctz` active dispatch.

These were either already negative, too noisy, or too local for the observed gap.

## Next A/B Gate

The next useful experiment should be no-fresh-emit and should test one structural claim at a time:

1. Patch existing `tmp/no0162_xs_assign_fullword_fastpath/grhsim_emit` artifacts.
2. Rebuild only `libgrhsim_SimTop.a` and relink the existing difftest emu.
3. Run CoreMark 20k with difftest.
4. Accept the direction only if runtime moves and perf changes in the expected bucket.

Preferred first A/B: reduce top-level batch dispatch or combine generated code regions without changing schedule semantics. This directly tests whether dispatch/frontend fragmentation is causal.

Avoid another fresh emit until a no-fresh prototype shows movement.
