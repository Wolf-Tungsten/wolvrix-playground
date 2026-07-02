# NO0211 CBAW P0 Evaluator Rollout Progress

记录日期：2026-07-01

关联：[`NO0210`](./NO0210_cross_boundary_activation_work_partition_plan_20260629.md)

状态：P0-P8 rollout 完成。本文从 P0 地基尺子开始滚动记录 `CrossBoundaryActivationWork` 路线落地进展；截至 2026-07-02，CBAW 路径已在完整 XiangShan 上通过 P8 structure gate，并按 [`NO0210`](./NO0210_cross_boundary_activation_work_partition_plan_20260629.md) §11.10 完成 full emit、emu build、correctness smoke 与 CoreMark 50k runtime。P4 ATE equal-trigger merge 仍因 `trigger_signature_saturation` 默认关闭。

## 1. 本轮目标

按 NO0210 §11.2，P0 的首要目标是能对现有 materialized partition 做只读 replay：

- 复算 `cross_boundary_target_count`，对齐现有 `boundary_activation_edges`；
- 复算 `supernode_dependency_edge_count`，对齐现有 `dag_edges`；
- 复算 `compute_materialized_value_target_count`，对齐现有 `compute_compute_value_pairs`；
- 输出 source-kind / target-kind matrix；
- 给出 plain compute supernode 的 resource vector 分布，并把默认 cap 来源写入 stats。

## 2. 已落地实现

新增 session 输出：

```text
<graph>.activity_schedule.cbaw_stats
```

该 JSON 当前包含：

- `value_use_groups`
- `cross_boundary_target_count`
- `supernode_dependency_edge_count`
- `compute_materialized_value_target_count`
- `compute_commit_value_target_count`
- `cross_boundary_value_bytes`
- `cross_boundary_consumer_use_count`
- `canonical_value_use_groups`
- `canonical_cross_boundary_target_count`
- `canonical_supernode_dependency_edge_count`
- `canonical_compute_materialized_value_target_count`
- `canonical_compute_commit_value_target_count`
- `canonical_cross_boundary_consumer_use_count`
- `source_clone_canonicalized_groups`
- `clone_width_mismatch_groups`
- `target_kind_matrix`
- `source_kind_matrix`
- `source_target_kind_matrix`
- `quotient_dag_cycle_detected`
- `replay_boundary_activation_delta`
- `replay_dag_edge_delta`
- `replay_compute_compute_delta`
- `canonical_boundary_activation_delta`
- `canonical_dag_edge_delta`
- `canonical_compute_compute_delta`
- `compute_supernode_op_count_p50/p90/p99/p995/max`
- `resource_op_count_cap`
- `resource_op_count_baseline_exceptions`
- `resource_p50/p90/p99/p995/max/cap/baseline_exceptions`
- `top_roots`

同时新增日志行：

```text
activity-schedule cbaw p0 replay: ...
```

用于完整 XiangShan 跑法中直接观察 replay delta 和 resource cap 来源。

## 3. 当前口径

P0 输出分成两层口径。

第一层是 **materialized replay**。它以当前 `ActivityScheduleBuild::valueFanout` 为 replay 输入。`valueFanout` 已经是按 `(value, target supernode)` 去重后的 materialized fanout，因此可以精确复算 NO0210 P0 的三项硬对齐指标：

- `cross_boundary_target_count == boundary_activation_edges`
- `supernode_dependency_edge_count == dag_edges`
- `compute_materialized_value_target_count == compute_compute_value_pairs`

这三个字段是 P0 出门槛，完整 XiangShan 上要求 `replay_boundary_activation_delta / replay_dag_edge_delta / replay_compute_compute_delta` 全为 0。

第二层是 **canonical ValueUseGroup diagnostics**。它从 final graph operand use 独立扫描，按 `rewrite.canonicalValues` 把 source clone 合并到 canonical value，并按 target supernode 去重，输出：

- `canonical_*` 指标；
- `source_clone_canonicalized_groups`；
- `clone_width_mismatch_groups`；
- `top_roots`。

这层用于验证 NO0210 §3.5 的 `CanonicalValueInvariant`，但不覆盖 materialized replay 主指标。原因是现有 activity-schedule 为了把 source clone 放进 compute supernode，会有“canonical source value -> cloned compute supernode”的诊断边；这类边帮助解释 clone 合并，但不等同于现有 emitted stats 的 `boundary_activation_edges`。

`cross_boundary_consumer_use_count` 从 canonical graph operand use 重新扫描，保留为诊断项。`cross_boundary_value_bytes` 使用 materialized value width 的 byte cost 作为 width-aware 派生统计。

资源预算已扩为只读 resource vector：

- `op_count`
- `live_value_bytes`
- `temporary_bytes`
- `emitted_code_units`
- `helper_call_count`
- `branch_count`

每个分量输出 `p50/p90/p99/p99.5/max/cap/baseline_exceptions`。默认 cap 来自 plain compute supernode 的 p99.5；超过该 cap 的 supernode 计入 baseline exception。`resource_op_count_*` 保留为兼容快捷字段。

## 4. P0 完成边界

P0 已完成：

- independent canonical ValueUseGroup scan；
- materialized replay 三项主指标对齐；
- source/target kind matrix；
- source clone canonical 合并诊断与 width mismatch 诊断；
- quotient DAG cycle check；
- top root report；
- 六分量 resource vector 的 plain 分布与 cap 来源。

后续阶段才处理的内容：

- 真正的 CSR 存储格式与 candidate accounting，进入 P3/P5；
- plain-vs-candidate top worsening / improvement diff report，需要有 candidate partition 后才有意义，进入 P5/P8；
- resource vector 的 runtime 标定与 hard gate 接入，进入 P3/P5。

## 5. 验收计划

本轮代码验收：

```text
cmake --build wolvrix/build --target transform-activity-schedule
ctest --test-dir wolvrix/build --output-on-failure -R transform-activity-schedule
```

后续完整 XiangShan 前验时，要求 `replay_boundary_activation_delta / replay_dag_edge_delta / replay_compute_compute_delta` 全为 0；若非 0，先归因 valueFanout 与 summary 的口径差异，不进入 P1。

## 6. 增量更新 2026-07-01：P1 ATE 只读前验接入

按 [`NO0210`](./NO0210_cross_boundary_activation_work_partition_plan_20260629.md) §11.3，P1 已开始实施 `feat-trigger-ate-readonly`。本次只扩展 `cbaw_stats` 与日志，不改变 plain / prob partition，不生成 CBAW atom 或新 supernode。

当前 P1 口径：

- P3 atom builder 尚未存在，因此 P1 先用当前 materialized compute supernode 作为 atom 代理，做 zero-profile trigger 判别力前验。
- trigger source 包含 state read、memory read、latch read，以及无 defining op 的 graph input value；constant 不计 trigger。
- trigger 签名使用 256-bit Bloom-style signature、4 个 hash，在 current quotient DAG 上按 topo 顺序向后传播。
- 输出 `trigger_signature_popcount_*` 与 Bloom cardinality 估算 `trigger_estimated_count_*`，用于观察是否整体饱和。
- 等触发桶统计分为 all bucket 与 non-empty bucket；P4 的安全等触发集合并候选默认应看 non-empty bucket。
- “等触发桶若全合并可内化边界上界”目前只计 compute->compute target，保持 NO0210 的 compute-only 边界；commit target 不纳入 ATE 可内化上界。

新增 JSON 字段包括：

```text
trigger_signature_bits
trigger_signature_hash_functions
trigger_saturation_threshold_bits
trigger_volatile_source_values
trigger_compute_supernodes_with_trigger
trigger_empty_compute_supernodes
trigger_signature_popcount_p50/p90/p99/p995/max
trigger_estimated_count_p50/p90/p99/p995/max
trigger_signature_saturated_compute_supernodes
trigger_signature_saturated_ratio_ppm
trigger_equal_bucket_count
trigger_equal_bucket_multi_count
trigger_equal_bucket_covered_supernodes
trigger_equal_bucket_covered_supernode_ratio_ppm
trigger_equal_bucket_largest
trigger_non_empty_equal_bucket_count
trigger_non_empty_equal_bucket_multi_count
trigger_non_empty_equal_bucket_covered_supernodes
trigger_non_empty_equal_bucket_covered_supernode_ratio_ppm
trigger_non_empty_equal_bucket_largest
trigger_equal_bucket_internalizable_boundary_targets
trigger_non_empty_equal_bucket_internalizable_boundary_targets
trigger_equal_bucket_internalizable_compute_targets
trigger_non_empty_equal_bucket_internalizable_compute_targets
trigger_equal_bucket_internalizable_dependency_edges
trigger_non_empty_equal_bucket_internalizable_dependency_edges
trigger_ate_equal_merge_recommended
trigger_ate_no_go_reason
```

新增日志行：

```text
activity-schedule cbaw p1 trigger: ...
```

该日志输出 volatile source 数、trigger popcount p50/p99、饱和比例、non-empty 等触发桶覆盖率、non-empty 可内化 compute targets，以及 P1 的初步 go/no-go reason。

已补小图测试：

- `top` case 检查 P1 字段进入 `cbaw_stats`。
- `cbaw_trigger_equal_chain` case 构造两个由同一 input 触发的连续 compute supernode，验证 `trigger_non_empty_equal_bucket_internalizable_compute_targets == 1`、`trigger_non_empty_equal_bucket_internalizable_dependency_edges == 1`，且 `trigger_ate_equal_merge_recommended == 1`。

本轮验证：

```text
cmake --build wolvrix/build --target transform-activity-schedule
ctest --test-dir wolvrix/build --output-on-failure -R transform-activity-schedule
```

结果：两项均通过。

## 7. 增量更新 2026-07-02：P1 完整 XiangShan 前验结论

已用完整 XiangShan `SimTop`、plain partition、`stop_after_activity_schedule` 跑完 P0/P1/P2 只读前验：

```text
PYTHONPATH=wolvrix/build/skbuild/python \
WOLVRIX_XS_GRHSIM_RESUME_FROM_PRE_REG_TO_MEM_JSON=1 \
WOLVRIX_XS_GRHSIM_PRE_REG_TO_MEM_JSON=build/xs/grhsim/wolvrix_xs_pre_reg_to_mem.json \
WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1 \
WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE=108 \
WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMPUTE_NODE=108 \
WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE=4096 \
python3 scripts/wolvrix_xs_grhsim.py \
  build/xs/wolf/wolf_emit/xs_wolf.f SimTop \
  build/xs/grhsim_no0210_p2_r3/grhsim_emit \
  build/xs/grhsim_no0210_p2_r3/xs_wolf_grhsim.json \
  build/xs/grhsim/grhsim_emit/wolvrix_read_args.txt \
  info --waveform off --perf off
```

关键日志：

```text
activity-schedule cbaw p0 replay: cross_boundary_target_count=2446334 supernode_dependency_edge_count=703270 compute_materialized_value_target_count=2095811 boundary_delta=0 dag_delta=0 compute_compute_delta=0 op_count_p99=108 op_count_p995=108 op_count_cap=108 op_count_exceptions=0
activity-schedule cbaw p1 trigger: volatile_sources=266123 popcount_p50=256 popcount_p99=256 saturated_ratio_ppm=788774 non_empty_equal_bucket_covered_ppm=821318 non_empty_internalizable_compute_targets=1132677 ate_equal_merge_recommended=0 no_go_reason=trigger_signature_saturation
activity-schedule cbaw p2 semantic: seed_groups=1492018 merge_hint_groups=1552930 debug_labels=4896754 rtm_groups=351 mffc_groups=1396066 plain_out1=29864 plain_in1=5041 aggregate_families=140546 guard_domains=1123504 sink_labels=169157 passthrough_chains=95601 top_root_attributed=45
```

结论：

- P0 完整 XiangShan replay 出门槛已过：`boundary_delta / dag_delta / compute_compute_delta` 全为 `0`。
- P1 ATE 判别力前验触发 kill criterion：`trigger_signature_saturated_ratio_ppm=788774`，`popcount_p50=256` 且 `popcount_p99=256`，说明 256-bit Bloom 签名在完整 XiangShan 上大面积近全集饱和。
- 因此 P4 的 ATE equal-trigger merge 默认关闭；后续只保留 trigger 膨胀 gate 与 `no_go_reason=trigger_signature_saturation` 记录，主线继续 P3/P5 的纯 CBAW net-cut。

## 8. 增量更新 2026-07-02：P2 语义只读统计接入

按 [`NO0210`](./NO0210_cross_boundary_activation_work_partition_plan_20260629.md) §11.4，P2 已实现为只读 annotation/report，不改变 plain / prob partition，不生成 CBAW atom 或新 supernode。

新增 `cbaw_stats` 字段覆盖：

- `semantic_seed_groups / semantic_merge_hint_groups / semantic_debug_labels`
- `semantic_rtm_intent_groups / semantic_rtm_intent_ops`
- `semantic_mffc_groups / semantic_mffc_covered_ops / semantic_mffc_split_groups`
- `semantic_plain_out1_hints / semantic_plain_in1_hints / semantic_plain_sibling_groups / semantic_plain_sibling_members`
- `semantic_aggregate_families / semantic_aggregate_seed_groups / semantic_aggregate_merge_hint_groups`
- `semantic_guard_domains / semantic_guard_domain_members / semantic_guard_unknown_ops`
- `semantic_sink_cone_labels / semantic_sink_cone_members / semantic_sink_cone_multi_sink_ops`
- `semantic_passthrough_chains / semantic_passthrough_ops`
- `semantic_hierarchy_debug_labels`
- `semantic_top_root_*` 与 `semantic_top_root_attribution`
- `semantic_rule_seed_groups / semantic_rule_merge_hint_groups / semantic_rule_debug_labels`

实现边界：

- P2 只统计 `SeedGroup / MergeHintGroup / DebugLabel` 覆盖与 top-root 归因，不参与 gain、candidate queue、resource hard gate 或 materialization。
- `HierarchyInfo` 只输出 debug label 计数，不进入 candidate 或 gain。
- 完整 XiangShan 上 export session 为 `22362ms`，未触发 P2 近线性 kill criterion。实现中避免按 canonical value 重扫高 fanout users；sink-cone 诊断按实际 result users 扫描，并限制每 supernode 的诊断 label 数。

本轮验证：

```text
cmake --build wolvrix/build --target transform-activity-schedule
cmake --build wolvrix/build/skbuild --target wolvrix-lib
ctest --test-dir wolvrix/build --output-on-failure -R transform-activity-schedule
```

结果：通过。完整 XiangShan `stop_after_activity_schedule` 也通过，日志保存在：

```text
build/logs/xs/xs_wolf_grhsim_no0210_p2_r3_stop_after_activity_20260702.log
```

## 9. 增量更新 2026-07-02：P3 atom 与接口闭环

按 [`NO0210`](./NO0210_cross_boundary_activation_work_partition_plan_20260629.md) §11.5，P3 已实现为只读 atom/partition/replay 闭环，不改变 plain / prob partition，不把 plain replay 作为 CBAW 初始解。

新增 `cbaw_stats` 字段覆盖：

- `cbaw_atom_count`
- `cbaw_atom_op_count_p50/p90/p99/p995/max`
- `cbaw_atom_quotient_edges / cbaw_atom_quotient_cycle_detected`
- `cbaw_atom_resource_*`
- `cbaw_atom_kind_counts`
- `cbaw_atom_rtm_intent_atoms / cbaw_atom_mffc_atoms / cbaw_atom_passthrough_atoms / cbaw_atom_aggregate_atoms / cbaw_atom_guard_atoms`
- `cbaw_atom_plain_replay_*`

实现边界：

- atom 层按当前 compute-node/MFFC chunk 建立，并保留 materialized split chunk 边界，确保可以表达现有 plain supernode partition。
- atom quotient DAG 直接从 atom 间 value dependency 构建并校验无环。
- atom resource vector 使用与 P0 supernode resource 相同的六分量口径。
- plain materialize replay 通过 atom partition assignment 重新计算 fanout、DAG edge 与 compute materialized value target；该 replay 只证明新接口没有引入 stats 偏差，不作为 P5 CBAW coarsen 的起点。

本轮验证：

```text
cmake --build wolvrix/build --target transform-activity-schedule
cmake --build wolvrix/build/skbuild --target wolvrix-lib
ctest --test-dir wolvrix/build --output-on-failure -R transform-activity-schedule
```

结果：通过。

完整 XiangShan `SimTop`、plain partition、`stop_after_activity_schedule` 也通过，日志保存在：

```text
build/logs/xs/xs_wolf_grhsim_no0210_p3_r1_stop_after_activity_20260702.log
```

关键日志：

```text
activity-schedule cbaw p0 replay: cross_boundary_target_count=2446334 supernode_dependency_edge_count=703270 compute_materialized_value_target_count=2095811 boundary_delta=0 dag_delta=0 compute_compute_delta=0 op_count_p99=108 op_count_p995=108 op_count_cap=108 op_count_exceptions=0
activity-schedule cbaw p1 trigger: volatile_sources=266123 popcount_p50=256 popcount_p99=256 saturated_ratio_ppm=788774 non_empty_equal_bucket_covered_ppm=821318 non_empty_internalizable_compute_targets=1132677 ate_equal_merge_recommended=0 no_go_reason=trigger_signature_saturation
activity-schedule cbaw p2 semantic: seed_groups=1492018 merge_hint_groups=1552930 debug_labels=4896754 rtm_groups=351 mffc_groups=1396066 plain_out1=29864 plain_in1=5041 aggregate_families=140546 guard_domains=1123504 sink_labels=169157 passthrough_chains=95601 top_root_attributed=45
activity-schedule cbaw p3 atom: atom_count=1396096 quotient_edges=3679158 quotient_cycle=0 op_count_p99=56 op_count_p995=108 op_count_cap=108 plain_replay_supernodes=71871 plain_replay_boundary_delta=0 plain_replay_dag_delta=0 plain_replay_compute_compute_delta=0
```

结论：

- P3 出门槛已过：atom quotient DAG 无环，`quotient_cycle=0`。
- atom resource 分布可解释：`op_count_p99=56`、`op_count_p995=108`、`op_count_cap=108`。
- 等价 plain materialize replay 没有引入统计偏差：`plain_replay_boundary_delta / plain_replay_dag_delta / plain_replay_compute_compute_delta` 全为 `0`。
- P3 之后仍不启用 P4 equal-trigger merge；P1 已给出 `no_go_reason=trigger_signature_saturation`，后续主线进入 P5 纯 CBAW net-cut，P4 只保留 gate/report 与默认关闭记录。

## 10. 增量更新 2026-07-02：P4-P8 gate rollout

本轮把 CBAW 从只读 P3 推到可独立 materialize 的 `partitionPolicy=cbaw` 路径，并在完整 XiangShan 上跑到 `stop_after_activity_schedule`。

已落地内容：

- P4 ATE：保留日志和 gate，默认关闭。完整 XiangShan 仍触发 `trigger_signature_saturation`，因此不启用 equal-trigger merge。
- P5 CBAW coarsen MVP：生成 heavy value-use、plain structural hint、aggregate、guard、sink-cone、MFFC/dominance 候选；每轮用 bounded one-shot DSU contraction 接受候选，最后用一次 Kahn topo backstop 保证 quotient DAG 无环。当前每轮上限为 `4096` merges。
- P6 guard/sink candidates：guard 与 sink-cone 候选已进入 accounting；本轮未被接受。
- P7 refinement：当前只做 `report_only` 日志。由于 P5/P8 结构 gate 已失败，未继续启用 FM/local exact。
- P8 output/gate：CBAW 使用 arbitrary acyclic materialization，不走 1-D DP 连续分段；small graph 可内部跑 plain baseline，大图通过外部 plain baseline 三项指标驱动 `cbaw_gate_stats`。

新增外部 baseline 入口：

```text
-cbaw-plain-boundary-baseline
-cbaw-plain-dag-baseline
-cbaw-plain-compute-compute-baseline
```

XiangShan 脚本对应环境变量：

```text
WOLVRIX_XS_GRHSIM_CBAW_PLAIN_BOUNDARY_BASELINE
WOLVRIX_XS_GRHSIM_CBAW_PLAIN_DAG_BASELINE
WOLVRIX_XS_GRHSIM_CBAW_PLAIN_COMPUTE_COMPUTE_BASELINE
```

这样完整 XiangShan 不需要在 CBAW run 内部再 materialize 一次 plain baseline，也能得到真实 P8 gate 结论。

本轮验证：

```text
cmake --build wolvrix/build --target transform-activity-schedule
ctest --test-dir wolvrix/build --output-on-failure -R transform-activity-schedule
cmake --build wolvrix/build/skbuild --target wolvrix-lib
python3 -m py_compile scripts/wolvrix_xs_grhsim.py
```

结果：通过。

完整 XiangShan `SimTop`、CBAW partition、`stop_after_activity_schedule` 也通过，日志保存在：

```text
build/logs/xs/xs_wolf_grhsim_no0210_p5_cbaw_r10_stop_after_activity_20260702.log
```

关键日志：

```text
activity-schedule progress: cbaw_plain_gate_baseline external boundary=2446334 dag=703270 compute_compute=2095811
activity-schedule cbaw p4 ate: enabled=0 reason=trigger_signature_saturation ate_equal_merge_recommended=0 saturated_ratio_ppm=344838 trigger_estimated_p99=355
activity-schedule cbaw p5 coarsen: candidates=15073893 evaluated=92886 accepted=4096 reject_no_gain=808 reject_resource=7926 reject_cycle=79807 stale=1057 clusters_before=1396066 clusters_after=1391970 quotient_cycle=0
activity-schedule cbaw p6 guard-sink: guard_candidates=3422571 guard_accepted=0 sink_candidates=1517040 sink_accepted=0 semantic_guard_domains=1123504 semantic_sink_labels=391493
activity-schedule cbaw p7 refine: enabled=0 mode=report_only fm_moves=0 local_exact_rois=0 reason=coarsen_gate_first
activity-schedule cbaw p8 gate: runtime_allowed=0 reason=structure_regression structural_pass=0 trigger_pass=1 resource_pass=1 dag_pass=1 plain_boundary=2446334 cbaw_boundary=4266927 plain_dag=703270 cbaw_dag=4020376 plain_compute_compute=2095811 cbaw_compute_compute=3916404 cbaw_trigger_p99=355
```

结构对比：

| 指标 | plain baseline | CBAW r10 | ratio |
| --- | ---: | ---: | ---: |
| `boundary_activation_edges` / `cross_boundary_target_count` | 2,446,334 | 4,266,927 | 1.744x |
| `dag_edges` / `supernode_dependency_edge_count` | 703,270 | 4,020,376 | 5.717x |
| `compute_compute_value_pairs` / `compute_materialized_value_target_count` | 2,095,811 | 3,916,404 | 1.869x |

结论：

- P5/P6 的 CBAW path 可以在完整 XiangShan 上完成 stop-after，candidate accounting 完整，`quotient_cycle=0`。
- P8 gate 正确阻止 runtime：`reason=structure_regression`，三项主结构指标均高于 plain，尤其 DAG 边为 `5.717x`。
- 本轮没有执行 build、correctness smoke 或 CoreMark runtime；这是 NO0210 §11.10 的预期 gate 行为，不是漏测。
- P7 仍未实现为有效 refinement。当前 CBAW coarsen 离 plain gate 太远，先继续修 P5 candidate/gain/initial partition，比在结构回退结果上启用 FM/local exact 更有价值。

下一步：

- 优先降低 P5 的 `dag_edges` 回退，检查为什么 accepted candidates 只来自 `heavy_value_use`，而 `plain_out1/plain_in1/plain_siblings/aggregate/guard/sink_cone/mffc_dominance` 没有贡献。
- 把 CBAW gain 从局部 direct-edge 近似推进到真正 incident use group delta，避免低质量 merge 造成 quotient DAG 爆炸。
- 只有当 CBAW coarsen 后结构接近 plain gate，再启用 P7 FM/local exact；否则 P7 只应保持 report-only。

## 11. 增量更新 2026-07-02：P7/P8 收敛与 XiangShan runtime

本轮继续推进 P5/P7/P8，使 CBAW 从 r10 的结构回退收敛到可进入 build/runtime 的 P8 pass。

新增实现：

- P5 coarsen 每轮上限从 `4096` 提升到 `65536`，并把 coarsen iteration 上限提升到 `8`。
- P7 启用 CBAW boundary FM refinement，默认 `WOLVRIX_XS_GRHSIM_FM_REFINE_MAX_ROUNDS=4`，可通过环境变量调整。
- P7 增加 capacity-neutral exact two-cluster swap refinement：当单点 FM move 因目标 size cap 被拒绝时，尝试用一个反向候选形成等容量 swap，并用 incident value fanout 的 exact CBAW target-count delta 接受。
- P8 gate 使用外部 plain baseline 三项指标，只有 `boundary_activation_edges / dag_edges / compute_compute_value_pairs` 全部 `<= plain` 且 trigger/resource/DAG gate 通过时才允许 runtime。

本轮 C++/Python 验证：

```text
cmake --build wolvrix/build --target transform-activity-schedule
ctest --test-dir wolvrix/build --output-on-failure -R transform-activity-schedule
cmake --build wolvrix/build/skbuild --target wolvrix-lib
```

结果：通过。

完整 XiangShan plain gate baseline：

```text
boundary_activation_edges=2446334
dag_edges=703270
compute_compute_value_pairs=2095811
```

stop-after 收敛记录：

| run | 变体 | FM rounds | P8 | `cbaw_boundary` | Δboundary | `cbaw_dag` | Δdag | `cbaw_compute_compute` | Δcompute |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| r17 | coarsen8 | 4 | fail | 2459301 | +12967 | 684520 | -18750 | 2108778 | +12967 |
| r18 | coarsen8 | 8 | fail | 2449817 | +3483 | 680909 | -22361 | 2099294 | +3483 |
| r19 | coarsen8 | 12 | fail | 2447650 | +1316 | 679331 | -23939 | 2097127 | +1316 |
| r20 | coarsen8 | 16 | fail | 2446954 | +620 | 678681 | -24589 | 2096431 | +620 |
| r21 | coarsen8 + swap | 4 | fail | 2454399 | +8065 | 685240 | -18030 | 2103876 | +8065 |
| r22 | coarsen8 + swap | 8 | pass | 2445198 | -1136 | 681653 | -21617 | 2094675 | -1136 |

r22 stop-after 关键日志：

```text
build/logs/xs/xs_wolf_grhsim_no0210_p5_cbaw_r22_swap_fm8_stop4_stop_after_activity_20260702.log

activity-schedule cbaw p7 refine: enabled=1 mode=cbaw_boundary_fm fm_moves=92239 fm_rounds=8 fm_gain=158463.000000 fm_candidates=282454 fm_reject_size=17799153 fm_reject_cycle=6440431 local_exact_rois=0
activity-schedule cbaw p8 gate: runtime_allowed=1 reason=pass structural_pass=1 trigger_pass=1 resource_pass=1 dag_pass=1 plain_boundary=2446334 cbaw_boundary=2445198 plain_dag=703270 cbaw_dag=681653 plain_compute_compute=2095811 cbaw_compute_compute=2094675 cbaw_trigger_p99=355
```

full emit/build：

```text
build/logs/xs/xs_wolf_grhsim_build_no0210_r22_cbaw_fm8_full.log
build/xs/grhsim_no0210_p5_cbaw_r22_swap_fm8_full/
```

结果：

- full emit 再次通过 P8：`runtime_allowed=1 reason=pass`。
- `write_grhsim_cpp` 完成：`46087ms`；完整 Python flow total：`292782ms`。
- generated model：`sched_cpp_files=127`，`total_cpp_files=167`，`sched_cpp_bytes=1577051494`。
- emu link 成功：`build/xs/grhsim_no0210_p5_cbaw_r22_swap_fm8_full/grhsim-compile/emu`。

correctness smoke：

```text
build/logs/xs/xs_wolf_grhsim_no0210_r22_cbaw_fm8_smoke2k.log
```

结果：difftest enabled，首条指令已提交，运行到显式 `XS_SIM_MAX_CYCLE=2000` cap 后正常退出，无 mismatch。`Host time spent: 4223ms`。

CoreMark 50k runtime：

```text
build/logs/xs/xs_wolf_grhsim_no0210_r22_cbaw_fm8_coremark50k.log
build/metrics/xs/no0210_r22_cbaw_fm8_coremark50k_metrics.json
```

结果：

| 指标 | 数值 |
| --- | ---: |
| `XS_SIM_MAX_CYCLE` | 50000 |
| `guest_instr_cnt` | 73580 |
| `guest_cycle_cnt` | 49996 |
| `guest_cycle_spent` | 50001 |
| `guest_ipc` | 1.471718 |
| `emu_host_time_ms` | 347528 |

`scripts/grhsim_opt_metrics.py --gate coremark50k-fast` 通过：

```text
gate=coremark50k-fast pass=true
emu_host_time_ms=347528 <= 355000
difftest_enabled=true
cycle_limit_reached=true
guest_instr_cnt=73580
guest_cycle_cnt=49996
guest_cycle_spent=50001
```

结论：

- NO0210 §11.10 的 P8 build/runtime gate 已闭环：结构 gate pass 后执行 full emit、build、smoke 与 50k runtime，且 runtime 通过当前 `coremark50k-fast` gate。
- CBAW r22 相对 plain gate baseline 降低 `boundary_activation_edges` 与 `compute_compute_value_pairs` 各 `1136`，`dag_edges` 降低 `21617`。
- P4 ATE equal-trigger merge 仍不应启用；当前通过的是 P5 coarsen + P7 FM/swap + P8 gate 组合。
