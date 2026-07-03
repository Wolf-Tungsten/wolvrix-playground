# NO0213 CBAW Coarsen Improvement Plan

日期：2026-07-02

状态：计划，2026-07-02 已追加本轮实现与 stop-after 验证结果。本文接在 [`NO0210`](./NO0210_cross_boundary_activation_work_partition_plan_20260629.md)、[`NO0211`](./NO0211_cbaw_p0_evaluator_rollout_progress_20260701.md) 和 [`NO0212`](./NO0212_gsim_dp_stage_structure_gain_20260702.md) 之后，只讨论 `activity-schedule` 中 `partition_policy=cbaw` 的 P5 coarsen 提升。本文不把未验证的语义收益写成结论；所有改动都必须先通过结构指标与日志 accounting 证明。2026-07-03 起，NO0210 的独立 P4 ATE safe-merge 阶段已退役；本文后续的 P0-P4 是 coarsen 改进子步骤编号，二者不再对应。

## 1. 目标

当前 r22 CBAW 已通过 P8 structure gate，但从日志看，过 gate 主要依赖 P5 的 plain structural contraction 加 P7 boundary FM/swap 兜底，而不是文档最初要求的完整语义 coarsen。

本轮目标不是继续增加 FM 轮数，而是提升 P5 coarsen 本身：

- 让 coarsen 的接受规则直接对准三项主指标：`boundary_activation_edges / dag_edges / compute_compute_value_pairs`。
- 让 accepted candidates 的来源从几乎纯 `plain_out1/plain_in1`，推进到可解释的 `aggregate / MFFC / guard / sink-cone` 贡献。
- 降低 P7 对结果的决定性，避免 runtime pass 只靠 FM/swap 把边界最后几千个 target 拉回 plain 以下。
- 保持 NO0210 的边界：compute-only、profile-free、plain-gated、近线性；不把 plain partition 作为 CBAW 初始解。

## 2. 已有事实

完整 XiangShan plain gate baseline：

```text
boundary_activation_edges = 2446334
dag_edges                 = 703270
compute_compute_pairs     = 2095811
```

关键 CBAW 运行结果：

| run | 变体 | P5 accepted | P7 | P8 | cbaw_boundary | Δboundary | cbaw_dag | Δdag | cbaw_compute | Δcompute |
| --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| r10 | 1 round, 4096 cap | 4096 | off | fail | 4266927 | +1820593 | 4020376 | +3317106 | 3916404 | +1820593 |
| r12 | 1 round, 65536 cap | 65536 | off | fail | 2860326 | +413992 | 670626 | -32644 | 2509803 | +413992 |
| r18 | 8 rounds + FM8 | 374045 | on | fail | 2449817 | +3483 | 680909 | -22361 | 2099294 | +3483 |
| r20 | 8 rounds + FM16 | 374045 | on | fail | 2446954 | +620 | 678681 | -24589 | 2096431 | +620 |
| r22 | 8 rounds + swap + FM8 | 374045 | on | pass | 2445198 | -1136 | 681653 | -21617 | 2094675 | -1136 |

r22 P5 candidate accounting：

```text
generated:
  heavy_value_use 26961261
  plain_out1      2398129
  plain_in1       2008939
  plain_siblings  3340686
  aggregate_hint  12625153
  mffc_dominance  26961261
  guard_hint      25320505
  sink_cone       11947865

accepted:
  plain_out1      178042
  plain_in1       180352
  aggregate_hint  8633
  mffc_dominance  7018
```

从这些结果能确定三点：

1. r10 的 `heavy_value_use` 主导 contraction 会造成严重结构回退，不能作为默认接受优先级。
2. r12/r18/r20/r22 的改善主要来自 `plain_out1/plain_in1` 加上 P7；r22 中 `aggregate_hint + mffc_dominance` 只占 accepted 的约 4.2%，`guard_hint/sink_cone/plain_siblings/heavy_value_use` 为 0。
3. P7 FM/swap 有效但已经进入边际收益区：FM8 到 FM16 仍未过 gate，r22 需要 swap + FM8 才过，而且最终 margin 只有 `boundary -1136`。

因此，下一步不能把 r22 解释为“语义 coarsen 已成功”。更准确的结论是：CBAW materialization/gate 已打通，但 P5 coarsen 仍主要是结构链合并，语义候选尚未成为主要贡献。

## 3. 当前实现形状

当前 P5 `tryMergeNodeCbaw(...)` 的候选来自 cluster value-use 边。对每条 `from -> to` value-use edge，会生成或附加以下 kind：

- `heavy_value_use`
- `plain_out1`：source cluster 只有一个 succ
- `plain_in1`：target cluster 只有一个 pred
- `aggregate_hint`：任一端带 aggregate 或 reg-to-mem intent label
- `guard_hint`：任一端带 guard-like label
- `sink_cone`：任一端带 sink-cone label
- `mffc_dominance`

当前候选排序先按 kind priority，再按 `targetGain/dependencyGain/computeGain`。同一个 pair 只保留一个 kind：

```text
plain_out1/plain_in1
  > plain_siblings
  > aggregate_hint/mffc_dominance
  > guard_hint/sink_cone
  > heavy_value_use
```

当前 P5 接受条件：

- `targetGain != 0`
- merged op count 不超过 `maxOpInComputeSupernode`
- 每轮一个 cluster 只能参与一次 accepted merge
- pair 必须是单向直接边
- local cycle-safe 条件：source 只有一个 succ，或 target 只有一个 pred，或二者在 cluster topo 中相邻
- 每轮最多 `65536` merges，最多 `8` 轮
- batch 之后再做一次 topo backstop，不通过则截断 accepted prefix

当前 coarsen 之后仍会运行一次 DP segment packing；CBAW 下该 DP 使用 unit value weight 和默认 segment penalty。若 `fmRefineMaxRounds != 0`，再运行 P7 CBAW boundary FM move/swap。

## 4. 问题归因

### 4.1 P5 gain 不是文档要求的三指标真实 gain

NO0210 §11.7 要求 P5 gain 使用 incident use groups 精确计算，并按：

```text
cross_boundary_target_count
supernode_dependency_edge_count
compute_materialized_value_target_count
```

词典序排序。

当前实现的 `targetGain` 主要来自 pair 间直接 value-use edge weight，`dependencyGain` 对 direct edge 通常是 1，`computeGain` 也复用 weight。这解释了 r12 的形状：`dag_edges` 已低于 plain，但 `boundary_activation_edges` 与 `compute_compute_value_pairs` 仍高出 `413992`。它说明局部直接边收益不能代表全局 materialized target-count delta。

### 4.2 semantic kind 目前更多是标签，不是独立语义规则

`guard_hint` 和 `sink_cone` 当前只在“已有 value-use pair 的任一端带 label”时生成候选，并没有实现 NO0210 §11.8 描述的：

- 同 guard domain 且有 value-use 关系；
- 同 sink label 且 role-compatible；
- unknown / union_guard / multi_sink 只诊断；
- semantic split penalty 只能作为 plateau tie-break。

日志也支持这个判断：r22 中 `guard_hint` 生成 `25320505`、`sink_cone` 生成 `11947865`，但 accepted 都是 0。

`mffc_dominance` 当前名称也强于实现含义：它对每条 value-use edge 都会生成候选，尚未证明 pair 属于真实 MFFC/dominance 关系。r22 中 `mffc_dominance` accepted 只有 `7018`，说明它还没有形成稳定的语义粗化主线。

### 4.3 kind attribution 是 lossy 的

同一 pair 只保留一个 `kind`。如果一个 pair 同时满足 plain、aggregate、guard 等条件，日志只会记最终胜出的 kind。这样会低估语义重叠，也无法回答：

- guard/sink 是真的没有好候选，还是被更高优先级 kind 覆盖？
- aggregate/MFFC accepted 是自身规则有效，还是只是 plain_out/in 的重名候选？
- rejected_cycle/stale/no_gain 是否集中在某类语义候选？

当前 detail log 只输出 `generated_by_kind / accepted_by_kind / reject_resource_by_kind`，缺少 `evaluated/reject_no_gain/reject_cycle/stale` 的 per-kind 明细。

### 4.4 P7 在替 P5 还债

r18/r20/r22 的结果显示，P7 boundary FM/swap 是 pass 的关键因素。r22 最终只比 plain 少 `1136` 个 boundary targets，而 P7 log 中 `fm_gain=158463`。不能仅凭这个值反推出精确的 coarsen-only 指标，因为当前没有明确的 after-coarsen / after-DP / after-FM stage dump；但它足以说明 P7 的调整量远大于最终 pass margin。

下一步需要把 P5/PDP/P7 分段指标落盘，避免继续用最终 P8 结果倒推 coarsen 质量。

## 5. 改进计划

### P0：补齐 coarsen 诊断，不改行为

目标：先把 P5 的真实问题暴露出来，避免继续靠最终 P8 指标猜测。

实现项：

1. 在 `ComputeNodeMaterializePerfStats` 中补齐 per-kind：
   - `generated`
   - `dedup_selected`
   - `dedup_lost_tag`
   - `evaluated`
   - `accepted`
   - `rejected_no_gain`
   - `rejected_resource`
   - `rejected_cycle`
   - `stale`

2. 候选从单 `kind` 改成：
   - `primary_kind`
   - `semantic_tags` bitset/list
   - `selected_reason`

   这样可以同时回答“按当前优先级算 accepted 是 plain_out1”与“该 pair 是否也属于 aggregate/guard/sink”。

3. 增加三段 structure stats：
   - after P5 coarsen, before DP segment
   - after DP segment, before P7 FM
   - after P7 FM/swap

   每段至少输出：
   - `boundary_activation_edges`
   - `dag_edges`
   - `compute_compute_value_pairs`
   - `cluster_count / segment_count / compute_supernode_count`
   - segment op-count p50/p90/p99/max

4. P7 增加 top blocked move accounting：
   - size block 来源 segment fill histogram
   - cycle block 的 pred/succ segment relation
   - top value fanout roots 的 before/after target count

出门槛：

- r22 重新跑 stop-after，最终三项指标不变或只存在可解释的 accounting 输出变化。
- detail log 能解释 `guard_hint/sink_cone` accepted 为 0 的主因：被覆盖、无 exact gain、resource、cycle 或 stale。

### P1：把 P5 gain 改成 incident exact delta

目标：不再用 direct edge weight 代表全局收益。

实现项：

1. 为每个 cluster 维护 incident value fanout：
   - source values by cluster
   - target values by cluster
   - value -> source cluster
   - value -> target cluster set

2. 对 candidate pair `(A, B)` 计算假设 contraction 后的三指标 delta：

```text
delta_boundary_targets
delta_dag_edges
delta_compute_compute_pairs
```

只扫描 A/B incident values 与相邻 quotient edges，避免全图重算。

3. 排序规则改为：

```text
delta_boundary_targets
delta_dag_edges
delta_compute_compute_pairs
semantic_tie_break
resource_slack
topo_order
```

其中 delta 表示“减少量”。默认只接受词典序正收益；boundary 为负收益的候选先只 report，不进入 accepted。

4. 保留 current direct-edge weight 作为 tie-break 和调试字段，不再作为主 gain。

出门槛：

- r12 类单轮实验中，不能再出现 `dag_edges` 明显降低但 `boundary_activation_edges` 大幅升高的 accepted set。
- P5 accepted 数可以下降；以三项主指标为准，不以 merge 数为目标。

### P2：candidate 队列分层，避免 plain hint 吞掉语义候选

目标：让语义候选有可解释的评估通道，而不是全部挤进一个 pair priority。

实现项：

1. 建立分层 candidate queues：
   - structural chain：`plain_out1/plain_in1`
   - sibling/hyperedge：`plain_siblings`
   - semantic cone：`aggregate / MFFC / passthrough`
   - guard/sink：`guard_domain / sink_cone`

2. 每轮评估时先统一计算 exact delta，再按收益合并，而不是先按 kind priority 固定压制。

3. 引入 per-class budget，但 budget 只限制评估量，不保证 accepted 数。任何类都必须满足三指标 exact gain。

4. 对同一 pair 的多 tag 保留 attribution：
   - accepted primary kind
   - accepted semantic tags
   - losing tags

出门槛：

- 能回答 r22 accepted 的 `plain_out1/plain_in1` 中有多少同时属于 aggregate/MFFC/guard/sink。
- 语义类 accepted 为 0 时，日志必须显示具体 reject 分布，而不是只能看到 generated 很大。

### P3：把语义候选做实

目标：只落地已有文档和已有代码能支撑的语义规则，不新增未经证据支持的大规则。

#### P3.1 MFFC/dominance

当前代码已有 `computeMffcRep(...)` 和 MFFC coverage 统计，但 CBAW coarsen 没有把它作为真实同锥规则使用。

计划：

- 用 `computeMffcRep(...)` 给 compute node/cluster 标注 MFFC rep。
- `mffc_dominance` 只对同 rep 或明确 producer-consumer cone 关系的 pair 生成。
- 若无法证明同锥关系，不再标为 `mffc_dominance`，只保留 `heavy_value_use` 或普通 structural tag。

#### P3.2 Aggregate

当前 aggregate 只看任一端是否为 concat/slice/动态 slice 等 shape。

计划：

- 按 common aggregate root 或 reg-to-mem intent group 建立 aggregate family。
- 只在 family 内或 family producer-consumer 边上生成 `aggregate_hint`。
- 对超 cap family 先 split，再生成 split 间 merge hint，避免大量 `rejected_resource`。

#### P3.3 Guard

当前 guard 只看 endpoint 是否 guard-like。

计划：

- 给 guard-like op 归一化 guard domain key。
- 只对 same-domain 且有 value-use 关系的局部 pair 生成 `guard_hint`。
- `unknown / union_guard` 只记 debug label，不进入 accepted queue。
- guard 只能作为 exact-gain plateau tie-break，不允许为了 guard domain 合并牺牲 boundary/compute target。

#### P3.4 Sink-cone

当前 sink-cone 只记录 endpoint 是否触达 sink。

计划：

- sink label 必须包含 sink op kind、state symbol、operand role。
- 只对同 sink label 且 role-compatible 的 producer/consumer cone pair 生成候选。
- multi-sink cluster 只诊断，不直接生成 candidate。

出门槛：

- `guard_hint/sink_cone` 若仍 accepted 为 0，需要证明原因是 exact gain 不足或 resource/cycle gate，而不是候选定义过宽造成排序噪声。
- `mffc_dominance` 的 generated 数不应再等于全部 value-use edge 数；否则说明它仍只是重名 heavy edge。

### P4：降低 P7 兜底依赖

目标：coarsen 后的 partition 不需要大量 FM 才接近 plain boundary。

实现项：

1. 每次 P5/DP 后输出 `fm_required_estimate`：
   - after-DP boundary 与 plain 的差值
   - P7 actual gain
   - final margin

2. 新增 coarsen quality gate：
   - after-DP `dag_edges <= plain`
   - after-DP `boundary_activation_edges` 不允许明显高于 plain；具体阈值先由 P0 stage dump 确定，不在本文硬猜。

3. P7 仍保留，但作为 refinement，不作为主要 pass 条件。

出门槛：

- FM8 pass 不应只靠千级 margin；如果 final margin 小于 P7 gain 的 1%，视为 coarsen 质量不足，继续 P5。

## 6. 验证矩阵

每个阶段都跑两类验证。

小图：

- `ctest --test-dir wolvrix/build --output-on-failure -R transform-activity-schedule`
- 覆盖 candidate attribution、exact delta、resource reject、cycle reject、guard/sink 诊断。

完整 XiangShan stop-after：

```text
WOLVRIX_XS_GRHSIM_PARTITION_POLICY=cbaw
WOLVRIX_XS_GRHSIM_FM_REFINE_MAX_ROUNDS=0/4/8
WOLVRIX_XS_GRHSIM_CBAW_PLAIN_BOUNDARY_BASELINE=2446334
WOLVRIX_XS_GRHSIM_CBAW_PLAIN_DAG_BASELINE=703270
WOLVRIX_XS_GRHSIM_CBAW_PLAIN_COMPUTE_COMPUTE_BASELINE=2095811
```

必须记录：

- P5 after-coarsen stats
- after-DP stats
- after-FM stats
- per-kind accepted/reject 分布
- P8 gate

## 7. 成功标准

最低标准：

- 不回退 r22：P8 仍 pass，`boundary_activation_edges / dag_edges / compute_compute_value_pairs` 全部 `<= plain`。
- per-kind accounting 足以解释每类候选的去向。
- `mffc_dominance`、`guard_hint`、`sink_cone` 的定义与实现名称一致。

推进标准：

- FM rounds 从 8 降到 4 或更低时仍能 pass。
- after-DP boundary gap 明显小于当前需要 P7 修复的量。
- accepted semantic-tagged candidates 占比上升，并且不是靠放宽三项主指标得到。

拒绝标准：

- 任何改动只增加 accepted merge 数，但三项主指标没有改善。
- 任何 semantic rule 让 `boundary_activation_edges` 或 `compute_compute_value_pairs` 回退，却只靠最终 FM 拉回。
- 任何实现依赖 plain partition 作为 CBAW 初始解。

## 8. 下一步提交顺序

1. `docs: add cbaw coarsen improvement plan`
2. `feat: add cbaw coarsen stage metrics and per-kind accounting`
3. `feat: score cbaw coarsen candidates with incident exact delta`
4. `feat: keep multi-tag candidate attribution`
5. `feat: make mffc and aggregate cbaw candidates semantic`
6. `feat: narrow guard and sink-cone cbaw candidates`
7. `test: add cbaw coarsen exact-delta and semantic-candidate cases`

## 9. 2026-07-02 实现与验证记录

本轮已把 P0-P4 中对 P5 coarsen 可直接落地的部分接入 `activity-schedule`：

- `ComputeNodeMaterializePerfStats` 增加 CBAW coarsen per-kind/per-tag accounting，覆盖 `generated / dedup_selected / dedup_lost_tag / evaluated / accepted / rejected_no_gain / rejected_resource / rejected_cycle / stale`，并记录 `selected_reason`。
- NO0210 P4 ATE safe-merge 已从主流水线退役；本轮实现不依赖等触发集合并，只保留 P1 trigger 诊断与 P8 trigger gate 字段。
- CBAW candidate 从单一 `kind` 改为 `primaryTag + tags`，同一 pair 的 plain、aggregate、MFFC、guard、sink、passthrough 等 attribution 不再互相覆盖。
- P5 排序改为 incident exact delta 词典序优先：`delta_boundary_targets / delta_dag_edges / delta_compute_compute_pairs`，再用 semantic tie-break、direct weight、resource slack 和 topo order 打破平局。
- exact delta 覆盖 direct internalized value targets、shared incoming fanout、common pred/succ DAG collapse，以及 common commit successor collapse。
- 语义 candidate 已收窄：`mffc_dominance` 只标 same real MFFC rep，`aggregate_hint` 只标 same aggregate family 或 reg-to-mem group，`guard_hint` 只标 same guard domain，`sink_cone` 只标 same sink label 且排除 multi-sink cluster；新增 `passthrough` tag。
- stage stats 已输出 after-P5 / after-DP / after-FM 三段，并导出到 session key `<graph>.activity_schedule.cbaw_coarsen_stats`。
- P7 增加 size-block fill histogram、cycle-block relation 和 `fm_required_estimate`。

完整 XiangShan stop-after 主验证命令口径：

```text
WOLVRIX_XS_GRHSIM_PARTITION_POLICY=cbaw
WOLVRIX_XS_GRHSIM_FM_REFINE_MAX_ROUNDS=8
WOLVRIX_XS_GRHSIM_CBAW_PLAIN_BOUNDARY_BASELINE=2446334
WOLVRIX_XS_GRHSIM_CBAW_PLAIN_DAG_BASELINE=703270
WOLVRIX_XS_GRHSIM_CBAW_PLAIN_COMPUTE_COMPUTE_BASELINE=2095811
WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1
RUN_ID=no0213_cbaw_exact_fm8_stop_after_activity_20260702
```

日志：

- FM8：`build/logs/xs/xs_wolf_grhsim_build_no0213_cbaw_exact_fm8_stop_after_activity_20260702.log`
- FM4：`build/logs/xs/xs_wolf_grhsim_build_no0213_cbaw_exact_fm4_stop_after_activity_20260702.log`
- FM0：`build/logs/xs/xs_wolf_grhsim_build_no0213_cbaw_exact_fm0_stop_after_activity_20260702.log`

三轮运行结果均为 `EXIT=0`，在 `activity-schedule` 后按预期停止。

结构结果：

| stage | boundary | vs plain | dag | vs plain | compute-compute | vs plain | compute supernodes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| after P5 coarsen | 3160612 | +714278 | 2520174 | +1816904 | 2810089 | +714278 | 871778 |
| after DP before FM | 2621811 | +175477 | 650955 | -52315 | 2271288 | +175477 | 71842 |
| after FM | 2356253 | -90081 | 609345 | -93925 | 2005730 | -90081 | 71842 |
| final P8 replay | 2359493 | -86841 | 609375 | -93895 | 2008970 | -86841 | 71872 |

最终 P8 gate：

```text
runtime_allowed=1 reason=pass
plain_boundary=2446334 cbaw_boundary=2359493
plain_dag=703270 cbaw_dag=609375
plain_compute_compute=2095811 cbaw_compute_compute=2008970
```

这比 r22 的 `boundary/compute -1136` margin 明显放大到 `86841`，DAG margin 从 `21617` 放大到 `93895`。但 after-DP boundary 仍比 plain 高 `175477`，当前不能声称 P7 已经变成可移除的微调阶段。

FM round matrix：

| FM rounds | P8 | boundary | vs plain | dag | vs plain | compute-compute | vs plain | fm_gain |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | fail: `structure_regression` | 2625051 | +178717 | 650985 | -52285 | 2274528 | +178717 | 0 |
| 4 | pass | 2394593 | -51741 | 624948 | -78322 | 2044070 | -51741 | 230458 |
| 8 | pass | 2359493 | -86841 | 609375 | -93895 | 2008970 | -86841 | 265558 |

FM4 已满足“FM rounds 降到 4 仍 pass”的推进标准；FM0 仍 fail，说明 P5+DP 本身还不能单独过 plain boundary/compute gate。

P5 coarsen accounting 关键结果：

```text
candidates=36077932 evaluated=4366853 accepted=524288
reject_no_gain=0 reject_resource=819494 reject_cycle=1993417 stale=1029654
selected_reason=exact_delta:23050563,exact_delta_semantic_tie:3469591
accepted_by_kind=aggregate_hint:690,guard_hint:1835,heavy_value_use:1852,
                 mffc_dominance:202,plain_in1:39097,plain_out1:98928,
                 plain_siblings:381684
accepted_by_tag=aggregate_hint:23606,guard_hint:13979,heavy_value_use:142604,
                mffc_dominance:50386,passthrough:1374,plain_in1:50319,
                plain_out1:98928,plain_siblings:381684,sink_cone:1414
```

解释：

- `accepted_by_kind` 是 primary attribution；`accepted_by_tag` 是 multi-tag overlap，因此语义标签实际命中不再被 `plain_*` 覆盖。
- `plain_siblings` 成为主贡献，说明 exact delta 后 sibling/hyperedge queue 已能安全吃掉共同 fanout/共同 pred 结构。
- `guard_hint` 和 `sink_cone` 不再是 0 accepted；同时保留 reject 分布：

```text
guard_candidates=1014416 guard_accepted=13979
guard_reject_resource=140477 guard_reject_cycle=488828 guard_stale=224235
sink_candidates=16971 sink_accepted=1414
sink_reject_resource=98 sink_reject_cycle=3194 sink_stale=3393
```

P7 仍有实质贡献：

```text
fm_moves=172472 fm_rounds=8 fm_gain=265558
after_dp_boundary_gap=175477
p7_actual_boundary_gain=265558
final_margin=90081
final_margin_ppm_of_p7_gain=339214
fm_reject_size_fill=50_75:138625,75_90:525705,90_95:477715,95_100:2793472,ge100:10608513,lt50:18662
fm_reject_cycle_relation=pred_after:2145206,succ_before:3428112,unknown:69740
```

所以本轮满足最低标准：P8 仍 pass，三项最终结构指标全部 `<= plain`，per-kind/per-tag accounting 足以解释候选去向，MFFC/aggregate/guard/sink 的实现定义与名称更一致。推进标准中“FM rounds 降到 4 或更低仍 pass”已通过 FM4 验证；“after-DP boundary gap 明显小于当前需要 P7 修复的量”尚未成立，后续若要关闭 FM 或降到 FM0，仍必须继续优化 P5/DP。

小图验证：

```text
cmake --build wolvrix/build --target transform-activity-schedule -j2
ctest --test-dir wolvrix/build --output-on-failure -R transform-activity-schedule
```

均通过。新增覆盖：

- direct chain multi-tag exact-delta accounting：primary `plain_out1`，tags 含 `mffc_dominance/passthrough`，`selected_reason=exact_delta_semantic_tie`。
- sibling exact-delta merge：共同 pred 的 sibling consumers 合并，root 不被合并，`accepted_by_kind=plain_siblings:1`。

全量验证：

```text
cmake --build wolvrix/build -j2
ctest --test-dir wolvrix/build --output-on-failure
```

全量 build 通过；全量 CTest 为 `46/48` 通过，当前残留失败是非 activity-schedule 目标：

- `transform-comb-lane-pack`：`Expected one packed kAnd for storage frontier rewrite`
- `transform-repcut`：`expected repcut partition static feature export`
