# NO0215 CBAW Multiplicity Reduction Action Plan

记录日期：2026-07-03

关联：[`NO0210`](./NO0210_cross_boundary_activation_work_partition_plan_20260629.md)、[`NO0211`](./NO0211_cbaw_p0_evaluator_rollout_progress_20260701.md)、[`NO0212`](./NO0212_gsim_dp_stage_structure_gain_20260702.md)、[`NO0213`](./NO0213_cbaw_coarsen_improvement_plan_20260702.md)、[`NO0214`](./NO0214_cbaw_compute_node_builder_decision_20260703.md)、[`NO0216`](./NO0216_cbaw_profile_work_scope_progress_20260703.md)、[`NO0219`](./NO0219_declared_value_compute_node_boundary_plan_20260706.md)、[`NO0220`](./NO0220_declared_value_boundary_cbaw_ab_final_perf_20260706.md)

状态：阶段 A/B/C 已执行，阶段 D/E 待执行；已追加 declared-boundary hard seed A/B，结论是不作为 CBAW 默认配置。本文接 NO0214 的决策：不 fork 独立 compute-node builder，继续当前 CBAW atom/materialization/evaluator 路径，优先推进 exact-delta coarsen、DP 后 gap 收敛、P7 refinement 和 top multiplicity 诊断。

## 1. 目标

本轮目标是把 current CBAW 从“final P8 pass，但依赖 P7 修复 after-DP gap”推进到“P5/DP 本身显著降低 boundary/value-target multiplicity，P7 只做 refinement”。

当前基线：

| 指标 | plain baseline | current CBAW FM8 | current vs plain |
| --- | ---: | ---: | ---: |
| `boundary_activation_edges` | `2446334` | `2359493` | `-86841` |
| `dag_edges` | `703270` | `609375` | `-93895` |
| `compute_compute_value_pairs` | `2095811` | `2008970` | `-86841` |

当前 stage gap：

| stage | boundary | vs plain | dag | vs plain | compute-compute | vs plain |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| after P5 coarsen | `3160612` | `+714278` | `2520174` | `+1816904` | `2810089` | `+714278` |
| after DP before FM | `2621811` | `+175477` | `650955` | `-52315` | `2271288` | `+175477` |
| after FM8 | `2356253` | `-90081` | `609345` | `-93925` | `2005730` | `-90081` |
| final P8 replay | `2359493` | `-86841` | `609375` | `-93895` | `2008970` | `-86841` |

关键缺口：

- after-DP boundary / compute-compute 仍比 plain 高 `175477`。
- final DAG 已低于 GSim 和 plain，但 BAE 仍是 fresh GSim 的 `1.726x`。
- current GrhSIM CBAW 还缺少同日 `GRHSIM_EMIT_RUNTIME_PROFILE=1` 动态 work 数据，不能完整解释 host gap。

## 2. 非目标

- 不新增默认启用的独立 compute-node builder。
- 不把 GSim `ENode` 当作 GSim `Node` 使用。
- 不以 accepted merge 数、DAG edge 数单项下降作为成功标准。
- 不让 P7 FM 成为唯一 pass 条件；P7 仍保留，但必须能解释和缩小其必要修复量。
- 不引入会显著增加 full emit/build 编译重尾的方案，除非先在 stop-after 数据上证明结构收益明显。

## 3. 阶段 A：补齐最新动态 profile 口径

目的：把 NO0214 暂缺的 current CBAW dynamic work 数据补齐，为后续判断“结构改善是否转为 runtime 改善”提供同日口径。

执行记录：见 [`NO0216`](./NO0216_cbaw_profile_work_scope_progress_20260703.md)。本阶段已在独立 build dir 完成 profile-enabled build/run，并产出 current dynamic work summary。

行动：

1. 用 current CBAW 配置重新 emit/build 一份 profile-enabled GrhSIM emu：
   - `GRHSIM_EMIT_RUNTIME_PROFILE=1`
   - 仍使用 current `partition_policy=cbaw`、FM8、同一 plain baseline。
2. 跑 CoreMark 50k：
   - `EMU_RUNTIME_PROFILE=1`
   - `WOLVRIX_GRHSIM_SUPERNODE_TSV=<run-dir>/grhsim_supernode_fire.tsv`
3. 解析并生成 summary：
   - `compute_fire`
   - `commit_fire`
   - `total_fire`
   - `compute_work`
   - `commit_work`
   - `total_work`
   - top supernodes by `f` and by `f * static_work`
4. 与 fresh GSim profile 对齐：
   - GSim `active_supernodes=766629270`
   - GSim `nodes=35103020807`
   - GSim `total_enodes=181026882379`
   - GSim no-profile/profile host time `46237ms / 44777ms`

验收：

- 产出一份可复用的 summary JSON，记录 emu path、build timestamp、runtime log、TSV path 和主要 counters。
- 若 profile-enabled build 编译成本过高，必须记录失败点和最大 TU / 最大 object 规模；不能用旧 NO0077 数据替代 current CBAW 结论。

## 4. 阶段 B：top multiplicity 诊断

目的：把 `boundary_activation_edges` 的高值拆到具体 root/value/atom/supernode 形态上，回答“问题集中在哪里”。

行动：

1. 在 CBAW stats 中新增 top root report，按以下 key 排序：
   - after-P5 boundary target count
   - after-DP boundary target count
   - after-FM boundary target count
   - `after_dp - after_fm` 修复量
   - compute-compute target count
2. 每个 top root 至少输出：
   - root value id / defining op kind / width bucket
   - producer atom id / producer compute node id
   - root 所属 semantic tags：aggregate、MFFC、guard、sink、passthrough、plain
   - external target supernode count
   - compute target count
   - involved cluster / segment ids before and after DP
   - 是否命中 high-fanout bucket 或 shared-source bucket
3. 新增 top-root stage delta 表：
   - after-P5 -> after-DP
   - after-DP -> after-FM
   - final replay delta
4. 新增 compute-node shape report：
   - top root 涉及的 compute node op count
   - source clones count
   - compute-like ops count
   - compute users / external targets
   - root 是否被切散到多个 atom / segment

验收：

- 能列出造成 after-DP `+175477` gap 的 top roots，并说明 top N 覆盖率。
- 能把 P7 的 `fm_gain=265558` 拆到 root / segment move 类型，而不是只看到总 gain。
- 若 top roots 高度集中，进入阶段 C/D 的 ROI 优先路径；若分散，则优先调整 DP 全局成本模型。

### 4.1 执行记录（2026-07-03）

本阶段已落地 top-root 诊断导出，并用完整 XiangShan stop-after 复跑。为避免 16/64 的早期采样过窄，本轮将每个排序 key 的采样上限调到 `128`，最终 report cap 调到 `512`；实际输出 `315` 条 root report。

新增/更新产物：

- CBAW 详细 JSON：`tmp/no0215_phase_b_20260703/grhsim/grhsim_emit/activity_schedule_cbaw_stats.json`
- supernode summary：`tmp/no0215_phase_b_20260703/grhsim/grhsim_emit/activity_schedule_supernode_stats.json`
- stop-after log：`build/logs/xs/xs_wolf_grhsim_build_no0215_phase_b_stop_after_20260703.log`

导出侧改动：

- `activity_schedule` 的 `cbaw_stats` session value 新增 pybind text exporter。
- `scripts/wolvrix_xs_grhsim.py` 新增 `activity_schedule_cbaw_stats.json` 导出，并在 `activity_schedule_supernode_stats.json` 中记录轻量索引。
- top-root report 字段覆盖 root value、def op、width/fanout bucket、producer atom/compute-node/supernode、semantic tags、P5/DP/FM/final targets、stage delta、compute-node shape 和 split 计数。

验证命令：

```text
cmake --build wolvrix/build --target transform-activity-schedule -j2
ctest --test-dir wolvrix/build --output-on-failure -R transform-activity-schedule

WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1
WOLVRIX_XS_GRHSIM_PARTITION_POLICY=cbaw
WOLVRIX_XS_GRHSIM_FM_REFINE_MAX_ROUNDS=8
make xs_wolf_grhsim_emit RUN_ID=no0215_phase_b_stop_after_20260703 ...
```

验证结果：

| 项 | 结果 |
| --- | --- |
| focused build | PASS |
| focused CTest | PASS |
| XiangShan stop-after | PASS |
| `activity-schedule` time | `251251ms` |
| total script time | `281384ms` |
| final `boundary_activation_edges` | `2359493` |
| final `dag_edges` | `609375` |
| final `compute_compute_value_pairs` | `2008970` |

stage delta：

| transition | boundary delta | compute-compute delta |
| --- | ---: | ---: |
| after P5 -> after DP | `-538801` | `-538801` |
| after DP -> after FM | `-265558` | `-265558` |
| after FM -> final replay | `+3240` | `+3240` |

top-root coverage：

| reported roots | after-DP targets | after-DP coverage | after-P5 targets | after-FM targets | final targets | sampled DP->FM repair |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| top 10 | `18430` | `0.7029%` | `72505` | `19198` | `19198` | `0` |
| top 20 | `23330` | `0.8898%` | `80497` | `24070` | `24070` | `29` |
| top 50 | `34571` | `1.3185%` | `91738` | `35284` | `35284` | `56` |
| top 100 | `50480` | `1.9253%` | `122338` | `51205` | `51205` | `112` |
| top 200 | `69623` | `2.6555%` | `171307` | `70077` | `70077` | `537` |
| reported 315 | `72793` | `2.7764%` | `182311` | `71928` | `71928` | `1859` |

关键判断：after-DP total targets 是 `2621811`，reported 315 roots 只覆盖 `72793`（`27764ppm`）。top multiplicity 不集中，不能只靠少数 root ROI 解决 after-DP `+175477` gap；阶段 C 可以保留 top-root ROI，但阶段 D 的 DP 全局成本模型优先级更高。

top after-DP roots：

| rank | value | def | width | tags | P5 | DP | FM | final | P5->DP | DP->FM | cn ops | clones |
| ---: | ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | `56691` | `kLogicNot` | `1` | `guard|mffc` | `28176` | `5658` | `5790` | `5790` | `-22518` | `132` | `1` | `0` |
| 2 | `12806` | `kOr` | `1` | `guard|mffc` | `19621` | `4830` | `4915` | `4915` | `-14791` | `85` | `7` | `1` |
| 3 | `4405065` | `kLogicAnd` | `1` | `guard|mffc` | `4295` | `1659` | `1659` | `1659` | `-2636` | `0` | `2` | `0` |
| 4 | `4626865` | `kOr` | `>256` | `aggregate|guard|mffc` | `1267` | `1258` | `1258` | `1258` | `-9` | `0` | `60` | `34` |
| 5 | `56640` | `kNot` | `1` | `guard|mffc` | `3495` | `1171` | `1258` | `1258` | `-2324` | `87` | `1` | `0` |
| 6 | `4405063` | `kLogicOr` | `1` | `guard|mffc` | `5261` | `1022` | `1406` | `1406` | `-4239` | `384` | `1` | `0` |
| 7 | `17992` | `kLogicNot` | `1` | `guard|mffc` | `4680` | `855` | `914` | `914` | `-3825` | `59` | `1` | `0` |
| 8 | `49772` | `kAssign` | `1` | `guard|mffc` | `1907` | `662` | `668` | `668` | `-1245` | `6` | `9` | `3` |
| 9 | `49771` | `kAssign` | `1` | `guard|mffc` | `1903` | `659` | `666` | `666` | `-1244` | `7` | `9` | `3` |
| 10 | `49770` | `kAssign` | `1` | `guard|mffc` | `1900` | `656` | `664` | `664` | `-1244` | `8` | `9` | `3` |

top DP->FM repair roots：

| rank | value | def | width | tags | DP | FM | repair | DP segment | FM segment |
| ---: | ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | `1861286` | `kAnd` | `1` | `aggregate|guard|mffc` | `31` | `1` | `30` | `38815` | `38815` |
| 2 | `1860890` | `kAnd` | `1` | `aggregate|guard|mffc` | `31` | `3` | `28` | `38811` | `38811` |
| 3 | `1860785` | `kAnd` | `1` | `aggregate|guard|mffc` | `31` | `4` | `27` | `38815` | `38815` |
| 4 | `1860389` | `kAnd` | `1` | `aggregate|guard|mffc` | `32` | `6` | `26` | `38788` | `38788` |
| 5 | `1860580` | `kAnd` | `1` | `aggregate|guard|mffc` | `32` | `6` | `26` | `38800` | `38800` |
| 6 | `1860681` | `kAnd` | `1` | `aggregate|guard|mffc` | `32` | `6` | `26` | `38796` | `38796` |
| 7 | `1861192` | `kAnd` | `1` | `aggregate|guard|mffc` | `31` | `5` | `26` | `38819` | `38819` |
| 8 | `1860671` | `kAnd` | `1` | `aggregate|guard|mffc` | `32` | `7` | `25` | `38796` | `38796` |
| 9 | `1861190` | `kAnd` | `1` | `aggregate|guard|mffc` | `31` | `6` | `25` | `38819` | `38819` |
| 10 | `1861065` | `kAnd` | `1` | `aggregate|guard|mffc` | `31` | `7` | `24` | `38823` | `38823` |

reported roots 聚合：

| 维度 | key | roots | after-DP targets | sampled repair |
| --- | --- | ---: | ---: | ---: |
| tag | `mffc` | `315` | `72793` | `1859` |
| tag | `guard` | `207` | `46890` | `1505` |
| tag | `aggregate` | `204` | `34809` | `1465` |
| tag | `passthrough` | `28` | `6344` | `83` |
| def | `kSliceStatic` | `43` | `14454` | `36` |
| def | `kAssign` | `42` | `11597` | `140` |
| def | `kOr` | `11` | `9145` | `0` |
| def | `kLogicNot` | `6` | `7266` | `20` |
| def | `kMux` | `35` | `6998` | `72` |
| def | `kAnd` | `101` | `6081` | `1316` |

阶段 B 结论：

- top after-DP roots 多数是 `guard|mffc`、1-bit、high-fanout 形态，但 top 10 只覆盖 `0.7029%`，top 315 也只有 `2.7764%`；问题是长尾分布，不是少数 root 集中爆炸。
- top after-DP roots 的 `split_atom_count/split_segment_count` 基本是 `1/1`，说明它们不是因为单个 compute node 被切散到多个 atom/segment 才成为 top root。
- sampled DP->FM repair 合计 `1859`，只占 P7 global `fm_gain=265558` 的 `0.70%`；现有 root report 能证明 P7 修复分散，但还不能替代阶段 E 的 full move attribution。
- 阶段 C 应保留 high-fanout `guard|mffc` root 的局部候选注入，但不应把 ROI-only 作为主线；阶段 D 应优先做 boundary-weighted / compute-compute-weighted DP cost variants。
- builder-local refinement 不满足阶段 F 触发条件：top multiplicity 没有稳定集中在少数 compute-node/atom 形态。

## 5. 阶段 C：P5 exact-delta coarsen 继续收敛

目的：减少 after-P5 的 multiplicity 债务，避免 DP/P7 后面大量还债。

当前 after-P5 明显回退：

```text
boundary +714278
dag      +1816904
compute  +714278
```

行动：

1. 增加 top-root aware candidate injection：
   - 对阶段 B 中 top roots 的 producer/consumer cone 生成局部候选。
   - 候选仍必须通过 exact delta，不能因为属于 top root 就绕过三项主指标。
2. 引入 boundary-regression guard：
   - P5 batch 级别记录 accepted prefix 对 top roots 的累计 delta。
   - 若某一 batch 对 global boundary 为正收益但集中制造 top-root regression，降级该候选 priority 或延后到 DP 后 refinement。
3. 改善 semantic candidate 的 ROI 选择：
   - aggregate/MFFC/guard/sink 候选只在 top roots 或高外部 target density 区域扩大评估预算。
   - 避免全图扩大 candidate queue 造成编译和 stop-after 时间爆炸。
4. 维护 per-kind/per-tag acceptance 目标，但不把语义占比当硬指标：
   - 语义 tag accepted 增加是辅助信号。
   - 三项主指标和 after-DP gap 才是主信号。

阶段门槛：

| 级别 | after-DP boundary gap | final P8 | FM 依赖 |
| --- | ---: | --- | --- |
| C1 | `< +120000` | pass | FM8 allowed |
| C2 | `< +80000` | pass | FM4 pass |
| C3 | `< +50000` | pass | FM2/FM4 matrix |
| C4 stretch | `<= 0` | pass | FM0 pass |

### 5.1 执行记录（2026-07-03）

本阶段已落地保守的 ROI candidate injection 和 regression guard 诊断，默认行为保持 exact-delta 主排序稳定：

- 新增 `top_root_roi` / `high_density_roi` candidate tag。
- 对 high-fanout root 的 target clusters 做 bounded pair injection。
- 对高外部 target-density cluster 的 aggregate/MFFC/guard/sink bucket 做 bounded semantic ROI injection。
- ROI-only candidates 单独排序并追加在普通 exact-delta candidates 后，避免扰动既有 exact-delta 排序。
- 若 injected ROI pair 后续被普通 candidate 命中，丢弃 injected ROI tags，按普通 candidate 重建。
- 新增 batch prefix gain / ROI budget / top-root guard 统计：`top_root_roi_values`、`top_root_roi_candidates`、`high_density_roi_buckets`、`high_density_roi_candidates`、`roi_budget_skipped`、`accepted_prefix_*_gain`、`accepted_prefix_top_root_boundary_gain`、`top_root_guard_demoted`、`top_root_guard_risk_accepted`。
- 新增小图测试 `cbaw_top_root_roi_consumer_pair`，验证 top-root ROI stats 能导出。

验证命令：

```text
cmake --build wolvrix/build --target transform-activity-schedule -j2
ctest --test-dir wolvrix/build --output-on-failure -R transform-activity-schedule

WOLVRIX_XS_GRHSIM_PARTITION_POLICY=cbaw
WOLVRIX_XS_GRHSIM_CBAW_PLAIN_BOUNDARY_BASELINE=2446334
WOLVRIX_XS_GRHSIM_CBAW_PLAIN_DAG_BASELINE=703270
WOLVRIX_XS_GRHSIM_CBAW_PLAIN_COMPUTE_COMPUTE_BASELINE=2095811
WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1
WOLVRIX_XS_GRHSIM_FM_REFINE_MAX_ROUNDS=8
make xs_wolf_grhsim_emit RUN_ID=no0215_phase_c_observe_stop_after_20260703 ...
```

验证结果：

| 项 | 结果 |
| --- | --- |
| focused build | PASS |
| focused CTest | PASS |
| XiangShan FM8 stop-after | PASS |
| stop-after log | `build/logs/xs/xs_wolf_grhsim_build_no0215_phase_c_observe_stop_after_20260703.log` |
| activity-schedule time | `258791ms` |
| total script time | `289020ms` |

stage metrics：

| stage | boundary | vs plain | dag | vs plain | compute-compute | vs plain |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| after P5 coarsen | `3160612` | `+714278` | `2520174` | `+1816904` | `2810089` | `+714278` |
| after DP before FM | `2621811` | `+175477` | `650955` | `-52315` | `2271288` | `+175477` |
| after FM8 | `2356253` | `-90081` | `609345` | `-93925` | `2005730` | `-90081` |
| final P8 replay | `2359493` | `-86841` | `609375` | `-93895` | `2008970` | `-86841` |

新增 ROI / guard stats：

| stat | value |
| --- | ---: |
| `top_root_roi_values` | `130127` |
| `top_root_roi_candidates` | `65536` |
| `high_density_roi_buckets` | `13126` |
| `high_density_roi_candidates` | `32768` |
| `roi_budget_skipped` | `5` |
| `accepted_prefix_boundary_gain` | `1130224` |
| `accepted_prefix_dag_gain` | `1510519` |
| `accepted_prefix_compute_compute_gain` | `1130224` |
| `accepted_prefix_top_root_boundary_gain` | `506438` |
| `top_root_guard_demoted` | `14866` |
| `top_root_guard_risk_accepted` | `0` |

阶段 C 结论：

- final P8 仍 pass：`runtime_allowed=1 reason=pass`，三项指标均优于 plain。
- C1 未达成：after-DP boundary gap 仍为 `+175477`，没有降到 `< +120000`。
- 本阶段保留为 conservative/diagnostic default；此前更激进的 ROI ordering 会扰动 exact-delta candidate order 并造成结构回退，因此默认实现不让 ROI-only candidate 抢占普通 candidate。
- 因 stop-after 未达到阶段 C 门槛，本阶段当时不按门槛进入 full emit/build 和 runtime；后续为回答 coarsen 轮数对最终仿真性能的影响，补跑了 8/16/32 轮 full build + 50k runtime，对比见 5.3。该实验仍限定在 Phase C coarsen 分析内，不进入 Phase D。

### 5.2 Phase C 无收益归因（2026-07-03）

核心结论：最终 `observe` 版本没有收益不是因为 ROI 没有生成，而是因为 conservative ordering 让 ROI-only candidates 排在普通 exact-delta candidates 之后，而普通候选已经足够填满每轮 `65536` accepted merge cap；因此 accepted merge set 与 Phase B 完全一致。

Phase B 与 Phase C observe 对照：

| 指标 | Phase B | Phase C observe | 判断 |
| --- | ---: | ---: | --- |
| selected candidates | `26520154` | `26554263` | Phase C 多 `34109` 个 selected unique pairs |
| evaluated | `4366853` | `4366853` | evaluated prefix 完全没变 |
| accepted | `524288` | `524288` | 8 轮都打满 `65536` cap |
| reject_resource | `819494` | `819494` | 完全一致 |
| reject_cycle | `1993417` | `1993417` | 完全一致 |
| stale | `1029654` | `1029654` | 完全一致 |
| after-P5 boundary | `3160612` | `3160612` | 完全一致 |
| after-DP boundary | `2621811` | `2621811` | 完全一致 |
| final boundary | `2359493` | `2359493` | 完全一致 |

直接证据：

- `top_root_roi_candidates=65536`，但 `evaluated_by_kind` 没有 `top_root_roi`，`accepted_by_kind` / `accepted_by_tag` 也没有 `top_root_roi`。
- `high_density_roi_candidates=32768`，但 observe 版本没有任何 `high_density_roi` accepted。
- Phase C observe 的 `evaluated_by_kind` 与 Phase B 完全相同：`aggregate_hint=194158`、`guard_hint=734359`、`heavy_value_use=1984541`、`mffc_dominance=178280`、`passthrough=12948`、`plain_in1=195772`、`plain_out1=409091`、`plain_siblings=657704`。
- `activity_schedule_cbaw_stats.json` 与 Phase B 文件字节级相同，top-root stage report 也完全相同；ROI 只改变了 coarsen log 中的候选统计，没有改变最终 schedule。

ROI 候选的去向：

| ROI 来源 | generated | no-gain | primary selected | lost tag | 说明 |
| --- | ---: | ---: | ---: | ---: | --- |
| `top_root_roi` | `65536` | `0` | `5340` | `18124` | 约 `42072` 个命中已有普通候选并被 conservative dedup 丢弃；剩余 ROI-only 排在普通候选后，未进入 evaluated prefix |
| `high_density_roi` | `32768` | `12130` | `0` | `10705` | 大量无 exact gain；剩余主要作为 semantic ROI tag，observe 下没有 accepted |

早期更激进 ordering 的结果说明：让 ROI 进入 accepted prefix 并不自动带来收益，反而会替换掉更强的普通 exact-delta merge。

| variant | after-P5 boundary | after-DP gap | final boundary | ROI accepted 信号 | 结论 |
| --- | ---: | ---: | ---: | --- | --- |
| Phase B / observe | `3160612` | `+175477` | `2359493` | none | 保守版本无结构变化 |
| `promote` | `3168706` | `+200451` | `2366854` | no top-root accepted tag | ordering 扰动，结构变差 |
| `preserve` | `3169457` | `+201079` | `2367161` | `top_root_roi:6893`、`high_density_roi:99` accepted by tag | ROI 生效但 after-DP 更差 |
| `guarded` | `3169457` | `+201079` | `2367161` | `top_root_roi:6938`、`high_density_roi:158` accepted by tag | guard 未阻止结构回退 |
| early `stop_after` | `3937236` | `+474480` | `2618925` | `top_root_roi:27246`、`high_density_roi:3149` accepted by tag | 强推 ROI 造成 structure regression |

关键解释：

- `accepted_prefix_top_root_boundary_gain=506438` 是普通 accepted candidates 已经覆盖到的 top-root delta，并不是 Phase C 额外收益；Phase B 没有这个 counter，所以不能把它当作新增 gain。
- `preserve/guarded` 把 `accepted_prefix_top_root_boundary_gain` 提高到约 `540122`，但全局 `accepted_prefix_boundary_gain` 从 `1130224` 降到 `1121379`，after-DP gap 从 `+175477` 变为 `+201079`。这说明 top-root-local delta 与全局 exact-delta 排序存在冲突。
- top-root ROI 的采样方式主要在 high-fanout root 的 target clusters 之间造 pair；这些 pair 对单个 root 有局部收益，但常常不如普通候选在 global boundary / dag / compute-compute 三项上的综合收益。
- 阶段 B 已证明 after-DP top-root coverage 很分散：reported 315 roots 只覆盖 `72793 / 2621811 = 2.7764%`。因此少量 top-root ROI 即使局部命中，也很难撬动 `+175477` 的 after-DP gap。

Phase C 若继续，不应再简单提高 ROI priority。更合理的 Phase C 内继续方向是先做诊断增强：按 candidate 记录 “would-have-ranked / skipped-by-cap / displaced-gain” 采样，比较 ROI 候选与被替换普通候选的三项 exact delta，再决定是否存在不伤害 global gain 的局部插入窗口。

### 5.3 CBAW coarsen max-iterations 对最终仿真性能的影响（2026-07-03/04）

目的：只改变 `cbaw_coarsen_max_iterations`，比较 `8/16/32` 轮对 full emitted emu 的 CoreMark 50k no-profile runtime 影响。三组均使用：

- `partition_policy=cbaw`
- `WOLVRIX_XS_GRHSIM_FM_REFINE_MAX_ROUNDS=8`
- plain baseline `boundary=2446334 dag=703270 compute_compute=2095811`
- `XS_SIM_MAX_CYCLE=50000`
- 独立 build dir：`build/xs/grhsim_iter8`、`build/xs/grhsim_iter16`、`build/xs/grhsim_iter32`

结构与构建成本：

| coarsen max iterations | final boundary | final DAG | final compute-compute | compute supernodes | activity-schedule total | coarsen time | emit total |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `8` | `2359493` | `609375` | `2008970` | `71872` | `260637ms` | `142805ms` | `337322ms` |
| `16` | `2263054` | `663775` | `1912531` | `73848` | `367418ms` | `258681ms` | `444485ms` |
| `32` | `2253277` | `643038` | `1902754` | `74577` | `581654ms` | `474912ms` | `659856ms` |

固定 50k cycles runtime：

| coarsen max iterations | runtime log | host time | vs 8 rounds | vs previous |
| ---: | --- | ---: | ---: | ---: |
| `8` | `build/logs/xs/xs_wolf_grhsim_no0215_cbaw_iter8_runtime50k_20260703.log` | `323287ms` | baseline | baseline |
| `16` | `build/logs/xs/xs_wolf_grhsim_no0215_cbaw_iter16_runtime50k_20260703.log` | `315241ms` | `-8046ms` / `-2.49%` | `-2.49%` |
| `32` | `build/logs/xs/xs_wolf_grhsim_no0215_cbaw_iter32_runtime50k_20260703.log` | `304837ms` | `-18450ms` / `-5.71%` | `-10404ms` / `-3.30%` |

三组 runtime 均在同一 PC 触发 cycle limit：

- `pc = 0x80001312`
- `instrCnt = 73580`
- `cycleCnt = 49996`
- `IPC = 1.471718`

判断：

- 从最终仿真性能看，`32` 轮最好：CoreMark 50k host time 相比 `8` 轮下降 `5.71%`，相比 `16` 轮下降 `3.30%`。
- 从结构收益看，`8 -> 16` 是主要收益段：final boundary 下降 `96439`；`16 -> 32` 只再下降 `9777`，边际结构收益明显变小。
- 从构建成本看，`16 -> 32` 很贵：activity-schedule total 从 `367418ms` 增到 `581654ms`，coarsen time 从 `258681ms` 增到 `474912ms`。
- 因此若目标是单次最终仿真性能，`32` 轮值得保留；若目标是日常迭代构建效率，`16` 轮是更均衡点。当前还不建议继续盲目提高到 64：32 轮后 tail merge delta 已降到最后一轮 `1122` clusters，下一步应先重跑确认 runtime 抖动，再决定是否探索更高轮数或更精确的 tail-stop 门槛。

### 5.4 coarsen 策略有效性观察（2026-07-04）

从 8/16/32 轮 full build 的 `accepted_by_kind` 看，当前 CBAW coarsen 的主收益来源不是 ROI，而是 `plain_siblings`。

| coarsen max iterations | total accepted | `plain_siblings` accepted | 占比 | 第二梯队 |
| ---: | ---: | ---: | ---: | --- |
| `8` | `524288` | `381684` | `72.8%` | `plain_out1=98928`、`plain_in1=39097` |
| `16` | `885830` | `601456` | `67.9%` | `plain_out1=150756`、`plain_in1=109823` |
| `32` | `946108` | `640417` | `67.7%` | `plain_out1=161204`、`plain_in1=112375` |

判断：

- `plain_siblings` 是当前最有效的 primary accepted kind，贡献约 `68%~73%` 的 accepted merges。
- `plain_out1` / `plain_in1` 是稳定第二梯队，尤其 `16/32` 轮后 `plain_in1` 贡献明显上升。
- `heavy_value_use`、`guard_hint`、`mffc_dominance` 生成和 tag 命中很多，但作为 primary accepted kind 的占比不高，更像候选发现/语义辅助来源。
- `top_root_roi` / `high_density_roi` 不是当前主收益来源；32 轮里 `top_root_roi` primary accepted 也只有 `792`，`high_density_roi` 主要作为 tag 或 no-gain 被消耗。此前强行提升 ROI priority 已导致结构回退，因此不能只按 root-local 目标抢占全局 exact-delta 排序。

工程含义：默认 coarsen 策略应继续保护 `plain_siblings` 的排序优势。若 Phase C 继续优化，不应简单 promote ROI，而应先量化 ROI 候选会替换掉哪些 `plain_siblings/plain_out1/plain_in1` 候选，以及被替换候选的 global boundary / DAG / compute-compute exact delta。

### 5.5 declared-value hard seed boundary A/B（2026-07-06）

目的：验证 NO0219 的 declared value compute-node seed 截断边界是否能改善 CBAW 路线的最终性能。详细记录见 [`NO0220`](./NO0220_declared_value_boundary_cbaw_ab_final_perf_20260706.md)。

本轮不是 stop-after 结构判断，而是两组都完成 fresh emit / fresh emu build，并各跑两次 CoreMark 50k no-profile：

| 组 | build dir | runtime logs |
| --- | --- | --- |
| baseline | `tmp/no0219_cbaw_ab_base_20260706/grhsim` | `build/logs/xs/xs_wolf_grhsim_no0219_cbaw_ab_base50k_20260706.log`, `build/logs/xs/xs_wolf_grhsim_no0219_cbaw_ab_base50k_r2_20260706.log` |
| declared-boundary | `tmp/no0219_cbaw_ab_decl_20260706/grhsim` | `build/logs/xs/xs_wolf_grhsim_no0219_cbaw_ab_decl50k_20260706.log`, `build/logs/xs/xs_wolf_grhsim_no0219_cbaw_ab_decl50k_r2_20260706.log` |

最终 runtime：

| run | baseline | declared-boundary | delta |
| --- | ---: | ---: | ---: |
| r1 | `300360ms` | `312784ms` | `+12424ms` / `+4.14%` |
| r2 | `304073ms` | `319724ms` | `+15651ms` / `+5.15%` |
| average | `302216.5ms` | `316254.0ms` | `+14037.5ms` / `+4.65%` |

结构信号：

| 指标 | baseline | declared-boundary | delta |
| --- | ---: | ---: | ---: |
| seed `compute_nodes` | `1396066` | `2204668` | `+57.92%` |
| final supernodes | `75074` | `75498` | `+0.56%` |
| final `boundary_activation_edges` | `2253277` | `2273631` | `+0.90%` |
| final `dag_edges` | `643038` | `628567` | `-2.25%` |
| final `compute_compute_value_pairs` | `1902754` | `1923108` | `+1.07%` |
| final `state_read_activation_edges` | `130101` | `183886` | `+41.34%` |

declared hard boundary 生效计数：

- `boundary_declared=3022197`
- `declared_boundary_values=1214544`
- `declared_boundary_edges=2808640`
- `declared_cut_fixed=351`
- `declared_cut_fatal=0`

判断：

- hard boundary 确实保留了 declared 语义切点，seed 层明显变细。
- CBAW 能把大量额外 seed 合回，final supernode 只小幅增加。
- 但 final DAG 的改善没有转化为 runtime 收益；BAE / compute-compute 小幅上升，state-read activation 明显上升。
- 两次 CoreMark 50k final runtime 均慢，平均回退 `4.65%`，复测最高 `5.15%`。

因此，declared-value hard seed boundary 不进入 CBAW 默认配置。后续若继续利用 declared 语义，应把它改成 CBAW soft hint / attribution，而不是默认 hard boundary。

## 6. 阶段 D：DP 后 gap 收敛

目的：让 DP 不只压 DAG，也压 value-target multiplicity。

NO0212 已证明 GSim DP 也存在类似现象：edge 下降 `44.69%`，BAE 只下降 `11.69%`。因此本阶段只做受控 DP 成本改动，不假设 DP 自动解决 BAE。

行动：

1. 加 DP cost variants，默认关闭：
   - `unit`：当前口径，作为 baseline。
   - `boundary-weighted`：segment cut cost 使用 value external target count。
   - `compute-compute-weighted`：加入 compute target count。
   - `mixed`：词典序或加权组合，先只 stop-after。
2. 对 top roots 做 DP pin / soft affinity 实验：
   - producer 与主要 consumers 尽量同 segment。
   - 只允许在 op cap / cycle-safe / resource budget 内生效。
3. 增加 DP 后解释报告：
   - DP 使哪些 roots 的 BAE 降低。
   - DP 使哪些 roots 的 BAE 上升。
   - DAG 降低是否以 top-root multiplicity 增加为代价。
4. 建立 DP A/B matrix：
   - FM0 / FM4 / FM8
   - structure-only stop-after
   - full emit/build 仅在 stop-after pass 或接近 pass 时执行。

验收：

- DP variant 不能只降低 `dag_edges`；必须同时降低 after-DP `boundary_activation_edges` 或 `compute_compute_value_pairs`。
- 若 after-DP DAG 回退但 BAE 明显下降，需要进入 code-shape/runtime gate，不能只凭结构表通过。
- 任何 DP variant 若让 final CBAW runtime 回退，默认不保留。

## 7. 阶段 E：P7 refinement 从兜底变成可解释微调

目的：P7 继续保留，但需要缩小和解释其工作量。

当前 P7 数据：

```text
after_dp_boundary_gap=175477
p7_actual_boundary_gain=265558
final_margin=90081
fm_moves=172472
```

行动：

1. 固化 FM round matrix：
   - FM0、FM2、FM4、FM8 每次都跑 stop-after。
   - 记录 final margin、P7 gain、move count、blocked size/cycle distribution。
2. 增加 P7 move attribution：
   - move root id
   - from/to segment
   - delta boundary / dag / compute-compute
   - semantic tags
   - 是否来自阶段 B top roots
3. 区分 P7 move 类型：
   - top-root repair
   - size-fill repair
   - cycle-safe local swap
   - semantic tie repair
4. 尝试 pre-FM targeted local refinement：
   - 只对阶段 B top roots 允许 small local move/swap。
   - 若能减少 FM8 move count 或让 FM2/FM4 pass，才保留。

验收：

- 短期：FM4 pass 保持，FM8 final margin 不回退。
- 中期：FM2 pass 或 FM4 final margin 高于 current FM8 的 `86841`。
- 长期：FM0 pass 或 after-DP gap `<= 0`。

## 8. 阶段 F：builder 相关实验的触发条件

本阶段默认不启动。只有阶段 B 证明 top multiplicity 稳定集中在少数 compute-node/atom 形态，并且 C/D/E 无法在现有 atom 上收敛，才允许做 builder-local refinement。

允许形式：

- 默认关闭。
- 只对 top ROI 生效。
- 不改变 CBAW 全局 materialization/evaluator 口径。
- 必须复用 P0/P3 replay 校验。
- 必须输出三项主指标 before/after exact delta。

禁止形式：

- 新增默认 builder 主线。
- 只展示 node 数下降而不展示 BAE / compute-compute / runtime。
- 引入明显 full build 编译重尾。

## 9. 验证矩阵

每个阶段按以下顺序推进：

1. 小图测试：

```text
cmake --build wolvrix/build --target transform-activity-schedule -j2
ctest --test-dir wolvrix/build --output-on-failure -R transform-activity-schedule
```

2. Full XiangShan stop-after：

```text
WOLVRIX_XS_GRHSIM_PARTITION_POLICY=cbaw
WOLVRIX_XS_GRHSIM_CBAW_PLAIN_BOUNDARY_BASELINE=2446334
WOLVRIX_XS_GRHSIM_CBAW_PLAIN_DAG_BASELINE=703270
WOLVRIX_XS_GRHSIM_CBAW_PLAIN_COMPUTE_COMPUTE_BASELINE=2095811
WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1
WOLVRIX_XS_GRHSIM_FM_REFINE_MAX_ROUNDS=0/2/4/8
```

3. Full emit/build：

- 只对 stop-after 达到阶段门槛的 variant 执行。
- 记录最大 sched cpp、最大 object、链接时间和 emu size。

4. Runtime：

- CoreMark 50k no-profile：作为实际速度 gate。
- CoreMark 50k profile-enabled：只在需要解释 dynamic work 时跑。

## 10. 成功标准

最低成功：

- final P8 三项指标全部 `<= plain`。
- CoreMark 50k no-profile 不慢于 current CBAW FM8；若有 1-3% 抖动，必须至少重跑一次确认。
- 新增诊断能解释 top after-DP gap 和 P7 修复来源。

推进成功：

- after-DP boundary gap 从 `+175477` 降到 `< +80000`。
- FM4 pass 且 final margin 不低于 current FM8 的 `86841`。
- GSim-normalized BAE ratio 从 `1.726x` 明显下降。

强成功：

- after-DP boundary gap `<= 0` 或 FM0 pass。
- GrhSIM profile-enabled dynamic work 不回退，且 no-profile host time 有可测改善。

拒绝标准：

- 只降低 DAG，不降低 BAE / compute-compute。
- 只靠 FM8 拉回结构 gate，after-DP gap 不变或变大。
- stop-after 指标改善但 full emit/build 出现新的编译重尾。
- runtime 回退且无法由 profile instrumentation 或噪声解释。

## 11. 推荐提交顺序

1. `docs: add cbaw multiplicity reduction plan`
2. `feat: export cbaw top multiplicity roots`
3. `feat: attribute cbaw p7 moves by root`
4. `feat: add cbaw dp boundary-weighted variants`
5. `feat: inject top-root cbaw coarsen candidates`
6. `feat: add targeted cbaw pre-fm refinement`
7. `test: cover cbaw top-root and dp-cost diagnostics`
8. `docs: record cbaw profile-enabled current baseline`

每个提交都必须能独立说明结构指标、运行命令和是否进入下一阶段。没有 stop-after 数据的算法改动不进入 full runtime。
