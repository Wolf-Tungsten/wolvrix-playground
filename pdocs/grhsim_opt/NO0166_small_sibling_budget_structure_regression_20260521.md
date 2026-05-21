# NO0166: Small-Sibling Budget Structure Regression

Date: 2026-05-21

## Context

`NO0165` 发现 `NO0164` 不是干净的 state-alias A/B，并留下一个待解释问题：为什么 `NO0151/NO0152/NO0162` 保持低 `dag_edges/BAE`，而 `NO0154/NO0164` 漂到高 `dag_edges/BAE`。

本轮不做 fresh emit，只复查现有产物的 `activity_schedule_supernode_stats.json`、文档配置和当前 `activity_schedule.cpp` small-sibling 合并逻辑。

## Key Finding

低 BAE 版本和高 BAE 版本的核心差异不是 C1/C2/C4 主体是否存在，而是 small-sibling 阶段的候选枚举被参数组合意外收窄。

| artifact | small sibling max preds | small sibling candidate budget | small sibling merges | clusters after coarsen | compute supernodes | dag edges | BAE | 50k runtime |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `NO0151` | implicit `1` | `250000` | `329802` | `3084571` | `74430` | `485905` | `2216514` | `347835ms` |
| `NO0162` | implicit `1` | `250000` | `329802` | `3084571` | `74430` | `485905` | `2216514` | `350265ms` |
| `NO0154` | `2` | `250000` | `91002` | `3323371` | `73656` | `670160` | `2462201` | `367333ms` |
| `NO0164` | `2` | `250000` | `91002` | `3323371` | `73656` | `670160` | `3090763` | 20k `166379ms` |

The important delta:

- `max_preds=1`: `329802` small-sibling merges, `dag_edges=485905`, `BAE=2216514`.
- `max_preds=2` with the same `candidate_budget=250000`: only `91002` merges, `dag_edges=670160`, `BAE=2462201` before the additional `NO0164` source-edge drift.

This means the attempted "relax max preds to 2" did not expand the effective merge set. It reduced it.

## Code-Level Explanation

Current `tryEssentMergeSmallSiblings(...)` has two separate paths:

- `maxPreds == 1`:
  - walks each parent and groups all small children whose sole predecessor is that parent;
  - this path is not capped by `candidateBudget` in the same way as the generic entries path;
  - on XiangShan it produced `329802` accepted merges.

- `maxPreds != 1`:
  - builds a flat `entries` vector by scanning clusters for each `predCount`;
  - stops once `entries.size() >= candidateBudget`;
  - with `maxPreds=2` and `candidateBudget=250000`, the enumeration stopped early and only produced `91002` sibling merges.

So `maxPreds=2,candidateBudget=250000` is not a monotonic relaxation of `maxPreds=1`. It changes the candidate enumeration algorithm and makes the budget bind before the high-value parent-local groups from the `maxPreds=1` path are recovered.

## Runtime Interpretation

This explains why `NO0154` lost the structure benefit even though it was described as the same C1/C2/C4 dynamic body:

- it had fewer final compute supernodes, but worse dependency/activation shape;
- `dag_edges` increased by `184255` vs `NO0151/NO0162`;
- `BAE` increased by `245687` before the later `NO0164` source-edge explosion;
- CoreMark 50k regressed from the `143-144 cycles/s` band to about `136 cycles/s`.

The lesson is that "fewer compute supernodes" is not a sufficient success metric. For this workload, preserving low DAG/BAE and high-value sibling coalescing matters more than shaving another ~774 compute supernodes.

## Direction

The C1+C2+C4 dynamic主体 should treat `maxPreds=1` sibling merge as the stable baseline until the generic `maxPreds>1` path is made monotonic.

Concrete next steps:

- do not use `max_preds=2,candidate_budget=250000` as the default主体配置;
- either restore `WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_MAX_PREDS=1` for runtime experiments;
- or change the implementation so the `maxPreds>1` path first includes the full `maxPreds==1` parent-local grouping, then adds pred-count >1 candidates within a separate budget;
- use `small_sibling_merges`, `dag_edges`, `boundary_values`, and `BAE` as structure gates before any fresh build/runtime.

For the current root-cause thread, this accounts for the `NO0151/NO0162 -> NO0154` structural regression. `NO0154 -> NO0164` still has an extra source-edge/source-materialization drift documented in `NO0165`.

