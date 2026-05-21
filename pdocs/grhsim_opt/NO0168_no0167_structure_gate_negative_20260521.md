# NO0168: NO0167 Structure Gate Negative

Date: 2026-05-21

## Context

`NO0167` fixed one local C2 issue: `maxPreds>1` should preserve the single-predecessor sibling baseline before spending budget on multi-predecessor candidates.

This run validates that fix on XiangShan structure only. It uses the existing post-stats checkpoint and stops after `activity-schedule`; it does not emit full C++, build, or run CoreMark.

## Command Shape

```sh
WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1
WOLVRIX_XS_GRHSIM_POST_STATS_JSON=build/xs/grhsim/wolvrix_xs_post_stats.json
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SINGLE_PARENT_MERGE=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_SIBLING_MERGE=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE=0
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE=0
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_MAX_PREDS=2
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_CANDIDATE_BUDGET=250000
WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1
```

Artifact:

```text
tmp/no0168_xs_c2_small_sibling_monotonic_structure
```

## Result

| metric | `NO0162` fast structure | `NO0154` slow structure | `NO0168` after fix |
| --- | ---: | ---: | ---: |
| small-sibling merges | `329802` | `91002` | `110547` |
| clusters after coarsen | `3084571` | `3323371` | `3303826` |
| compute supernodes | `74430` | `73656` | `73655` |
| dag edges | `485905` | `670160` | `662888` |
| boundary values | `1151073` | `1276942` | `1903204` |
| boundary activation edges | `2216514` | `2462201` | `3083092` |
| constant activation edges | `4749` | `4749` | `260289` |
| state-read activation edges | `9367` | `9367` | `383040` |
| other-compute activation edges | `2202365` | `2448052` | `2439730` |

`NO0168` is still structurally bad:

- small-sibling merges improved only from `91002` to `110547`, far below the old `329802`;
- `dag_edges` remains near the slow `NO0154` band;
- `boundary_values/BAE` remain in the `NO0164/NO0161` exploded source-edge band;
- source activation explosion remains visible in `constant_activation_edges` and `state_read_activation_edges`.

## Interpretation

The `NO0167` monotonicity fix is not sufficient. It fixes a local candidate-enumeration bug, but the current scheduler still does not reproduce the old low-BAE C2 structure.

The next suspicion is the current final-DAG/materialization logic:

- current dirty `activity_schedule.cpp` has a `skipDagEdge` path that skips adding the DAG edge but still records `valueFanout`;
- this can inflate activation fanout without a matching DAG edge;
- that matches the observed symptom: source-edge BAE explodes while DAG shape does not improve.

Next step: compare `max_preds=1` under the same current code. If it also fails to reproduce `329802`, the regression is not caused by `max_preds=2` alone.

