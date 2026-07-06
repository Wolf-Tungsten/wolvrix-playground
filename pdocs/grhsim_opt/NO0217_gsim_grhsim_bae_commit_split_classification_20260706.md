# NO0217 GSim / GrhSIM BAE Commit Split Classification

记录日期：2026-07-06

关联：[`NO0212`](./NO0212_gsim_dp_stage_structure_gain_20260702.md)、[`NO0214`](./NO0214_cbaw_compute_node_builder_decision_20260703.md)、[`NO0215`](./NO0215_cbaw_multiplicity_reduction_action_plan_20260703.md)

状态：静态结构统计完成。本文回答两个问题：

1. 当前 GrhSIM 相比 GSim 多出来的 BAE 有多少来自 compute/commit 分离。
2. 当前 GrhSIM BAE 按 target kind、source kind 和 multiplicity 如何分类。

## 1. 统计口径

BAE 指 `boundary_activation_edges`，即跨 supernode 的 value -> target supernode 激活边数量。

GrhSIM 口径来自 `ActivityScheduleSummaryStats`：

- JSON 输出字段见 `../../wolvrix/lib/transform/activity_schedule.cpp` 中 `boundary_activation_edges` / `compute_compute_value_pairs` / `compute_commit_value_pairs` 的输出。
- `compute_commit_value_pairs` 在 target supernode kind 为 `Commit` 时累加，因此本文把它作为“compute/commit 分离暴露出来的 BAE”主口径。
- `commit_input_root_values` 是 commit 输入 root value 数，不是 target edge 数；本文不把它当作 BAE。

GSim 口径使用 strict cross-boundary 版本：

- `boundary_activation_edges=1367270`
- `activation_edges=1378667`
- `self_activation_edges=11397`

因此与 GrhSIM 对比时使用 `1367270`，避免把 same-supernode reactivation 混入 BAE。

## 2. 数据源

GrhSIM 当前默认产物：

```text
build/xs/grhsim/grhsim_emit/activity_schedule_supernode_stats.json
```

同日最新 `iter32` 实验产物与默认产物完全一致：

```text
build/xs/grhsim_iter32/grhsim_emit/activity_schedule_supernode_stats.json
```

GSim strict BAE 产物：

```text
tmp/no0214_gsim_rtprof_20260703/gsim-compile/model/SimTop_supernode_stats.json
```

旧 GSim 产物：

```text
build/xs/gsim/gsim-compile/model/SimTop_supernode_stats.json
```

旧产物中的 `boundary_activation_edges=1378667` 实际等同本轮 strict 产物的 `activation_edges`，包含 `11397` 条 self activation；本文不使用它作为 strict BAE。

## 3. 主结论

| 指标 | 数值 |
| --- | ---: |
| GSim strict BAE | `1367270` |
| GrhSIM BAE | `2253277` |
| GrhSIM - GSim | `886007` |
| GrhSIM / GSim | `1.648x` |
| GrhSIM over GSim | `+64.80%` |

按 target kind 拆分 GrhSIM BAE：

| target kind | BAE | 占 GrhSIM BAE |
| --- | ---: | ---: |
| compute -> compute | `1902754` | `84.44%` |
| compute -> commit | `350523` | `15.56%` |
| total | `2253277` | `100.00%` |

因此：

- commit 分离解释 GrhSIM 总 BAE 的 `15.56%`。
- 如果只看 GrhSIM 相比 GSim 多出来的 `886007` 条 BAE，commit 分离解释 `39.56%`。
- 扣掉 commit 分离后，GrhSIM compute->compute 仍有 `1902754` 条，比 GSim strict BAE 多 `535484` 条，仍是 GSim 的 `1.392x`。

结论：commit 分离是显著贡献项，但不是 GrhSIM BAE 偏高的主因。剩余主要空间仍在 compute-compute boundary propagation 和 value-target multiplicity。

## 4. GrhSIM source kind 分类

按 source kind 粗分：

| source group | BAE | 占 GrhSIM BAE |
| --- | ---: | ---: |
| other compute | `2109864` | `93.64%` |
| state read | `130101` | `5.77%` |
| constant | `12470` | `0.55%` |
| memory read | `842` | `0.04%` |

Top source kind：

| source kind | BAE | 占 GrhSIM BAE | source values |
| --- | ---: | ---: | ---: |
| `kAnd` | `470258` | `20.87%` | `233198` |
| `kLogicAnd` | `361942` | `16.06%` | `208422` |
| `kAssign` | `240895` | `10.69%` | `73702` |
| `kMux` | `217460` | `9.65%` | `188341` |
| `kSliceStatic` | `181726` | `8.07%` | `89770` |
| `kEq` | `164839` | `7.32%` | `76546` |
| `kRegisterReadPort` | `130101` | `5.77%` | `129899` |
| `kOr` | `105613` | `4.69%` | `57547` |
| `kLogicOr` | `96493` | `4.28%` | `92592` |
| `kConcat` | `54670` | `2.43%` | `25355` |

## 5. Multiplicity 分类

other-compute 内部：

| 指标 | 数值 | 占比口径 |
| --- | ---: | ---: |
| single-target values | `780655` | `61.10%` of all boundary values |
| single-target edges | `780655` | `34.65%` of GrhSIM BAE |
| multi-target values | `357423` | `27.97%` of all boundary values |
| multi-target edges | `1329209` | `58.99%` of GrhSIM BAE |
| other-compute unique source-target pairs | `637595` | `30.22%` of other-compute edges |
| duplicate edges vs unique pairs | `1472269` | `69.78%` of other-compute edges |

解释：

- GrhSIM 的 BAE 偏高不只是 supernode 数或 DAG edge 问题。
- other-compute 的 duplicate target multiplicity 很高，`1472269` 条 duplicate edges 占 other-compute edges 的 `69.78%`。
- 后续 CBAW / DP / refinement 的硬 gate 仍应优先看 `boundary_activation_edges` 与 `compute_compute_value_pairs`，不能只看 `dag_edges`。

## 6. Boundary value 与 commit root 补充

| 指标 | 数值 |
| --- | ---: |
| boundary_values | `1277770` |
| commit_input_root_values | `350578` |
| compute_commit_value_pairs | `350523` |
| direct_source_inputs_to_commit_supernodes | `13343` |

`commit_input_root_values` 与 `compute_commit_value_pairs` 只差 `55`，但语义不同：

- `commit_input_root_values` 是 commit node 输入 root value 去重计数。
- `compute_commit_value_pairs` 是 value 到 commit target supernode 的 BAE edge 计数。

本文所有“commit 分离贡献 BAE”的比例都使用 `compute_commit_value_pairs`。

## 7. 变体对照

| 产物 | BAE | compute->compute | compute->commit | commit 占比 |
| --- | ---: | ---: | ---: | ---: |
| `build/xs/grhsim` | `2253277` | `1902754` | `350523` | `15.56%` |
| `build/xs/grhsim_iter8` | `2359493` | `2008970` | `350523` | `14.86%` |
| `build/xs/grhsim_iter16` | `2263054` | `1912531` | `350523` | `15.49%` |
| `build/xs/grhsim_iter32` | `2253277` | `1902754` | `350523` | `15.56%` |

观察：

- `compute_commit_value_pairs` 在这些变体中保持 `350523` 不变。
- BAE 的主要变化全部来自 compute->compute。
- 这与 NO0212 的结论一致：当前 partition/DP 主要影响 compute-compute target multiplicity，commit target 项基本固定。

## 8. 后续判断

后续若要继续追 GrhSIM vs GSim BAE gap，应按如下优先级拆：

1. 先固定 GSim strict BAE 口径，避免把 `self_activation_edges` 算进对照。
2. GrhSIM 先拆 `compute_commit_value_pairs`，明确 commit 分离固定项。
3. 对剩余 `compute_compute_value_pairs` 继续按 source kind、root value、fanout bucket、target supernode multiplicity 做 ROI。
4. CBAW 验收继续要求 `boundary_activation_edges` 与 `compute_compute_value_pairs` 同时下降；`dag_edges` 单独下降不足以证明 runtime 方向正确。
