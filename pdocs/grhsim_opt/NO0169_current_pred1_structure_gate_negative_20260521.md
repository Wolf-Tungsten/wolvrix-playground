# NO0169: Current Pred1 Structure Gate Negative

Date: 2026-05-21

## Context

`NO0168` showed that the `NO0167` monotonic C2 fix did not restore the old fast structure under `max_preds=2`. This follow-up uses `max_preds=1` with the current code to determine whether the old `NO0151/NO0162` baseline is still reproducible.

This is also structure-only from the existing post-stats checkpoint. No full C++ emit, model build, or runtime was performed.

## Result

Artifact:

```text
tmp/no0169_xs_c2_pred1_current_structure
```

| metric | `NO0162` fast structure | `NO0154` slow structure | `NO0169` current pred1 |
| --- | ---: | ---: | ---: |
| small-sibling merges | `329802` | `91002` | `45590` |
| clusters after coarsen | `3084571` | `3323371` | `3368783` |
| compute supernodes | `74430` | `73656` | `73382` |
| dag edges | `485905` | `670160` | `675691` |
| boundary values | `1151073` | `1276942` | `1875581` |
| boundary activation edges | `2216514` | `2462201` | `3058810` |
| constant activation edges | `4749` | `4749` | `235114` |
| state-read activation edges | `9367` | `9367` | `377945` |
| other-compute activation edges | `2202365` | `2448052` | `2445718` |

This proves the old fast structure is no longer reproducible even with `max_preds=1`.

## Interpretation

The main current regression is not just the `max_preds=2,candidate_budget=250000` candidate-budget issue from `NO0166`.

Current code has another structure drift source:

- `max_preds=1` now produces only `45590` small-sibling merges, not `329802`;
- `boundary_values/BAE` remain in the exploded band;
- `constant/state-read activation edges` remain hundreds of thousands instead of the old `4749/9367`.

The strongest local suspect is the final-DAG/materialization change in `activity_schedule.cpp`:

```text
skipDagEdge = !splitForward
...
if (!skipDagEdge) add dag edge
...
always add valueFanout
```

That shape can create activation fanout for values whose DAG edge was intentionally skipped. It explains why BAE/source edges grow much more than the useful DAG structure.

Next step: make `valueFanout` follow the same skip decision as the DAG edge, or otherwise explicitly classify why skipped-DAG operands still require activation. This needs a correctness check because the change was likely introduced to fix cross-supernode materialization.

