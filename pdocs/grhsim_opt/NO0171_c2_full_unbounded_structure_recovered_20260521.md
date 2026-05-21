# NO0171: C2 Full Unbounded Structure Recovered

Date: 2026-05-21

## Context

After `NO0170`, source-edge explosion was fixed, but `max_preds=2,candidate_budget=250000` still stayed in the `NO0154` structural band.

Reviewing the older `NO0093` notes showed that the `329802` small-sibling fast structure came from C2 full:

```text
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_MAX_PREDS=0
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_CANDIDATE_BUDGET=0
```

So this run validates the current code with the `NO0170` valueFanout fix plus the old unbounded C2 full configuration.

This is structure-only from the existing post-stats checkpoint. No full C++ emit, model build, or runtime was run.

## Artifact

```text
tmp/no0171_xs_c2_full_unbounded_valuefanout_fix_structure
```

## Result

| metric | `NO0162` fast artifact | `NO0154` slow artifact | `NO0170` valueFanout fixed, pred2 budget250k | `NO0171` valueFanout fixed, C2 full |
| --- | ---: | ---: | ---: | ---: |
| small-sibling merges | `329802` | `91002` | `110547` | `329802` |
| clusters after coarsen | `3084571` | `3323371` | `3303826` | `3084571` |
| compute supernodes | `74430` | `73656` | `73655` | `74430` |
| dag edges | `485905` | `670160` | `662888` | `485905` |
| boundary values | `1151073` | `1276942` | `1273991` | `1151073` |
| boundary activation edges | `2216514` | `2462201` | `2453879` | `2216514` |
| constant activation edges | `4749` | `4749` | `4749` | `4749` |
| state-read activation edges | `9367` | `9367` | `9367` | `9367` |
| other-compute activation edges | `2202365` | `2448052` | `2439730` | `2202365` |
| compute-compute value pairs | `1858400` | `2104087` | `2095765` | `1858400` |

`NO0171` exactly recovers the old fast structural stats:

- `small_sibling_merges=329802`
- `compute_supernodes=74430`
- `dag_edges=485905`
- `boundary_values=1151073`
- `BAE=2216514`

## Interpretation

The recent structural regression has two independent causes:

1. `max_preds=2,candidate_budget=250000` is not the old fast C2 setting. The fast structure is C2 full (`max_preds=0,candidate_budget=0`).
2. The final DAG/materialization `skipDagEdge` change must keep `valueFanout` aligned with skipped DAG edges. Otherwise source activation edges explode even when DAG stats look only moderately worse.

For the main performance-alignment thread, `NO0171` is the first clean structure recovery point after the recent drift.

## Next Gate

The next useful step is full emit/build/CoreMark 20k, then 50k only if 20k is not negative:

- full C++ emit using `NO0171` settings;
- model build;
- difftest emu link;
- CoreMark 20k with difftest;
- CoreMark 50k only if the 20k gate is near the `NO0162/NO0151` band.

