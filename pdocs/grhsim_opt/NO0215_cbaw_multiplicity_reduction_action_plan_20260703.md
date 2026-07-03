# NO0215 CBAW Multiplicity Reduction Action Plan

记录日期：2026-07-03

关联：[`NO0210`](./NO0210_cross_boundary_activation_work_partition_plan_20260629.md)、[`NO0211`](./NO0211_cbaw_p0_evaluator_rollout_progress_20260701.md)、[`NO0212`](./NO0212_gsim_dp_stage_structure_gain_20260702.md)、[`NO0213`](./NO0213_cbaw_coarsen_improvement_plan_20260702.md)、[`NO0214`](./NO0214_cbaw_compute_node_builder_decision_20260703.md)、[`NO0216`](./NO0216_cbaw_profile_work_scope_progress_20260703.md)

状态：阶段 A/B 已执行，阶段 C/D/E 待执行。本文接 NO0214 的决策：不 fork 独立 compute-node builder，继续当前 CBAW atom/materialization/evaluator 路径，优先推进 exact-delta coarsen、DP 后 gap 收敛、P7 refinement 和 top multiplicity 诊断。

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
