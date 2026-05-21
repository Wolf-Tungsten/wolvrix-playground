# NO0167: C2 Small-Sibling Monotonic Fix

Date: 2026-05-21

## Context

`NO0166` 找到 `NO0154` 结构回退的原因：`max_preds=2,candidate_budget=250000` 走 generic entries path，反而只做了 `91002` 次 small-sibling merge；而 `max_preds=1` 的 parent-local path 能做 `329802` 次 merge，并保持低 `dag_edges/BAE`。

本轮修 C2 small-sibling merge 的单调性：`maxPreds>1` 不应丢掉 `maxPreds==1` 已经能得到的 sibling 合并收益。

## Implementation

Changed:

- `wolvrix/lib/transform/activity_schedule.cpp`
- `wolvrix/tests/transform/test_activity_schedule_pass.cpp`

Implementation rule:

- extract the old `maxPreds == 1` parent-local single-predecessor sibling grouping into a shared helper;
- always run that helper first for `maxPreds > 1`;
- let generic entries enumeration handle only multi-predecessor candidates (`predCount >= 2`);
- keep `candidateBudget` scoped to the generic multi-pred entries, so it cannot starve the single-pred baseline.

This makes `maxPreds=2` a monotonic extension of `maxPreds=1` for the high-value single-predecessor sibling groups.

## Local Verification

Build:

```sh
cmake --build wolvrix/build --target transform-activity-schedule -j32
```

Result:

```text
[100%] Built target transform-activity-schedule
```

Test:

```sh
ctest --test-dir wolvrix/build --output-on-failure -R '^transform-activity-schedule$'
```

Result:

```text
1/1 Test #21: transform-activity-schedule ......   Passed    0.01 sec
100% tests passed, 0 tests failed out of 1
```

New regression coverage:

- `essent_coarsen_small_siblings_budget_preserves_single_pred`
- uses `essentSmallSiblingMaxPreds=2` and `essentSmallSiblingCandidateBudget=1`
- expects `essent_small_sibling_merges=1`

This covers the intended property: a tight multi-pred candidate budget must not suppress the single-pred sibling merge baseline.

## Expected XiangShan Gate

This change has not yet been validated with a fresh XiangShan emit. The next fresh structure-only gate should use the current C1/C2/C4 dynamic body with `max_preds=2,candidate_budget=250000` and check:

- `essent_small_sibling_merges` should recover near the `NO0151/NO0162` baseline `329802`, plus any extra valid multi-pred merges;
- `dag_edges` should return near `485905`, not remain at `670160`;
- `boundary_activation_edges` should return near `2216514` before testing runtime;
- `constant_activation_edges` and `state_read_activation_edges` should not show the `NO0164` source-edge explosion.

Only after that structure gate should we run model build and CoreMark 20k/50k.

