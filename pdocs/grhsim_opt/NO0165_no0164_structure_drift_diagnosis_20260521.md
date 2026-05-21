# NO0165: NO0164 Structure Drift Diagnosis

Date: 2026-05-21

## Context

`NO0164` 原本用于验证 `WOLVRIX_GRHSIM_STATE_STORAGE_REF_ALIASES=0` 的 XiangShan runtime 影响。20k difftest 结果明显负向：

| model | 20k host ms |
| --- | ---: |
| `NO0162` baseline | `98988` |
| `NO0154` current improved | `103348` |
| `NO0164` state alias off | `166369` |

但后续复查 `activity_schedule_supernode_stats.json` 后，发现 `NO0164` 不是一个干净的 state-alias A/B。它和 `NO0154` 的 compute supernode / DAG 规模相同，但 activation source 结构明显漂移。

## Structure Comparison

| artifact | compute supernodes | dag edges | boundary values | boundary activation edges | constant activation edges | state-read activation edges | other-compute activation edges |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `tmp/no0151_xs_no_storage_ref_aliases/grhsim_emit` | `74430` | `485905` | `1151073` | `2216514` | `4749` | `9367` | `2202365` |
| `tmp/no0152_xs_storage_ref_alias_min4/grhsim_emit` | `74430` | `485905` | `1151073` | `2216514` | `4749` | `9367` | `2202365` |
| `tmp/no0162_xs_assign_fullword_fastpath/grhsim_emit` | `74430` | `485905` | `1151073` | `2216514` | `4749` | `9367` | `2202365` |
| `tmp/no0154_xs_current_coremark50k/grhsim_emit` | `73656` | `670160` | `1276942` | `2462201` | `4749` | `9367` | `2448052` |
| `tmp/no0164_xs_state_alias_off_structure/grhsim_emit` | `73656` | `670160` | `1905504` | `3090763` | `259808` | `382870` | `2448052` |

Key observations:

- `NO0164` 与 `NO0154` 的 `compute_supernodes=73656`、`dag_edges=670160` 相同。
- `NO0164` 的 `boundary_values` 从 `1276942` 增加到 `1905504`。
- `NO0164` 的 `boundary_activation_edges` 从 `2462201` 增加到 `3090763`。
- 增量主要来自 source 类 activation：
  - `constant_activation_edges`: `4749 -> 259808`
  - `state_read_activation_edges`: `9367 -> 382870`
  - `other_compute_activation_edges` 保持 `2448052`

这说明 `NO0164` 的 runtime 回退同时混入了 activation propagation / source materialization 结构变化。`WOLVRIX_GRHSIM_STATE_STORAGE_REF_ALIASES=0` 本身只应影响 generated C++ 的 state slot 访问形态，不应改变 activity schedule 图结构；因此当前数据不能作为纯 alias 开关 A/B。

## Correction To NO0164

`NO0164` 的 20k runtime 负向结论仍成立：该产物不能进入 50k，且当前形态不应合入。

但 `NO0164` 不能支持更强结论“关闭 state ref alias 本身导致 61%-68% runtime 回退”。更准确的表述是：

- state alias off 产物 runtime 大幅回退；
- 但该产物的 schedule activation 结构也发生明显漂移；
- 回退至少被 `boundary_values`、`boundary_activation_edges`、`constant_activation_edges`、`state_read_activation_edges` 的膨胀混杂；
- 需要先解释为什么 `NO0164` 相对 `NO0154` 增加了 source activation edges，再决定是否继续做干净的 state-alias A/B。

## Next Step

当前不应继续 fresh emit 验证 alias 开关。优先诊断：

- 为什么 `NO0154` 与 `NO0164` 在相同 `compute_supernodes/dag_edges` 下，`constant_activation_edges` 和 `state_read_activation_edges` 暴涨；
- 是否是 stats 语义变化、source clone/materialize 变化，或 emit 配置漂移；
- 为什么 `NO0151/NO0152/NO0162` 能保持较低 `dag_edges=485905`、`BAE=2216514`，而 `NO0154/NO0164` 漂到 `dag_edges=670160`；
- 恢复或解释低 BAE 结构，再做 runtime A/B。

