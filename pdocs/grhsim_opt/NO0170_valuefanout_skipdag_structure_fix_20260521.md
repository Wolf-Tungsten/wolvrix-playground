# NO0170: ValueFanout Skip-DAG Structure Fix

Date: 2026-05-21

## Context

`NO0168/NO0169` showed that current scheduler output had source-edge explosion:

- `constant_activation_edges` grew from `4749` to hundreds of thousands;
- `state_read_activation_edges` grew from `9367` to hundreds of thousands;
- `BAE` grew above `3.0M`.

The local suspect was final DAG/materialization code in `activity_schedule.cpp`: it could skip a DAG edge for non-forward split-local dependency, but still record that operand in `valueFanout`.

## Fix

Changed:

- `wolvrix/lib/transform/activity_schedule.cpp`

Rule:

- if a final DAG edge is skipped by `skipDagEdge`, the corresponding `valueFanout` entry is skipped too.

This keeps activation fanout aligned with actual inter-supernode propagation. Otherwise local/non-forward split dependencies become false boundary activation edges.

This is layered on top of the `NO0167` small-sibling monotonic candidate fix.

## Verification

Local:

```sh
cmake --build wolvrix/build --target transform-activity-schedule -j32
ctest --test-dir wolvrix/build --output-on-failure -R '^transform-activity-schedule$'
python3 -m pip install --no-build-isolation -e wolvrix
```

Result:

```text
transform-activity-schedule: Passed
editable wolvrix reinstall: success
```

XiangShan structure-only gate:

```text
tmp/no0170_xs_valuefanout_skip_fix_structure
```

It uses `WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1` and `WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1`; no full C++ emit, model build, or runtime was run.

## Structure Result

| metric | `NO0162` fast | `NO0154` slow | `NO0168` before valueFanout fix | `NO0170` after fix |
| --- | ---: | ---: | ---: | ---: |
| small-sibling merges | `329802` | `91002` | `110547` | `110547` |
| compute supernodes | `74430` | `73656` | `73655` | `73655` |
| dag edges | `485905` | `670160` | `662888` | `662888` |
| boundary values | `1151073` | `1276942` | `1903204` | `1273991` |
| boundary activation edges | `2216514` | `2462201` | `3083092` | `2453879` |
| constant activation edges | `4749` | `4749` | `260289` | `4749` |
| state-read activation edges | `9367` | `9367` | `383040` | `9367` |
| other-compute activation edges | `2202365` | `2448052` | `2439730` | `2439730` |
| compute-compute value pairs | `1858400` | `2104087` | `2724978` | `2095765` |

The fix works for the source-edge explosion:

- `constant_activation_edges`: `260289 -> 4749`
- `state_read_activation_edges`: `383040 -> 9367`
- `boundary_values`: `1903204 -> 1273991`
- `BAE`: `3083092 -> 2453879`

## Remaining Gap

`NO0170` is back near `NO0154` structure, not the older `NO0162` fast structure:

- `dag_edges=662888` remains far above `485905`;
- `BAE=2453879` remains above `2216514`;
- small-sibling merges are only `110547`, not `329802`.

So the source-edge/materialization bug is fixed, but the C2 sibling merge loss remains. The next step should focus on why current C2 only sees `110547` single/multi sibling merges when old fast artifacts recorded `329802`.

