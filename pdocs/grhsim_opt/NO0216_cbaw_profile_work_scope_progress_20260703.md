# NO0216 CBAW Profile Work Scope Progress

记录日期：2026-07-03

关联：[`NO0215`](./NO0215_cbaw_multiplicity_reduction_action_plan_20260703.md)、[`NO0214`](./NO0214_cbaw_compute_node_builder_decision_20260703.md)、[`NO0213`](./NO0213_cbaw_coarsen_improvement_plan_20260702.md)

状态：阶段 A 已完成；阶段 B 衔接已执行，主记录见 [`NO0215`](./NO0215_cbaw_multiplicity_reduction_action_plan_20260703.md)。本文记录 NO0215 阶段 A：“补 current CBAW `GRHSIM_EMIT_RUNTIME_PROFILE=1` 动态 work 口径”。

## 1. 目的

NO0214 已确认 current CBAW 的最新结构和 host-time 数据，但 current `build/xs/grhsim/grhsim-compile/emu` 未用 `GRHSIM_EMIT_RUNTIME_PROFILE=1` 构建，因此 `EMU_RUNTIME_PROFILE=1` run 只有 host time，没有 GrhSIM supernode fire TSV，也没有 `compute_work / commit_work / total_work`。

本轮目标是构建一份独立 profile-enabled CBAW GrhSIM emu，并跑同一 CoreMark 50k workload，补齐 current CBAW 的动态 work 口径。

## 2. 固定口径

保持 current CBAW FM8 配置：

```text
WOLVRIX_XS_GRHSIM_PARTITION_POLICY=cbaw
WOLVRIX_XS_GRHSIM_FM_REFINE_MAX_ROUNDS=8
WOLVRIX_XS_GRHSIM_CBAW_PLAIN_BOUNDARY_BASELINE=2446334
WOLVRIX_XS_GRHSIM_CBAW_PLAIN_DAG_BASELINE=703270
WOLVRIX_XS_GRHSIM_CBAW_PLAIN_COMPUTE_COMPUTE_BASELINE=2095811
XS_WOLF_GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE=108
XS_WOLF_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE=4096
```

本轮额外打开：

```text
GRHSIM_EMIT_RUNTIME_PROFILE=1
EMU_RUNTIME_PROFILE=1
WOLVRIX_GRHSIM_SUPERNODE_TSV=<run-dir>/grhsim_supernode_fire.tsv
```

为避免覆盖 current baseline，使用独立目录：

```text
tmp/no0216_cbaw_profile_20260703/grhsim
```

输入 JSON 复用当前已验证的 pre-reg-to-mem checkpoint：

```text
build/xs/grhsim/wolvrix_xs_pre_reg_to_mem.json
```

## 3. 执行命令

profile-enabled emit/build：

```text
source env.sh
GRHSIM_EMIT_RUNTIME_PROFILE=1 \
WOLVRIX_XS_GRHSIM_PARTITION_POLICY=cbaw \
WOLVRIX_XS_GRHSIM_FM_REFINE_MAX_ROUNDS=8 \
WOLVRIX_XS_GRHSIM_CBAW_PLAIN_BOUNDARY_BASELINE=2446334 \
WOLVRIX_XS_GRHSIM_CBAW_PLAIN_DAG_BASELINE=703270 \
WOLVRIX_XS_GRHSIM_CBAW_PLAIN_COMPUTE_COMPUTE_BASELINE=2095811 \
make xs_wolf_grhsim_emu \
  RUN_ID=no0216_cbaw_profile_build_20260703 \
  XS_GRHSIM_BUILD=tmp/no0216_cbaw_profile_20260703/grhsim \
  XS_WOLF_GRHSIM_RESUME_FROM_PRE_REG_TO_MEM_JSON=1 \
  XS_WOLF_GRHSIM_PRE_REG_TO_MEM_JSON=/home/gaoruihao/wksp/wolvrix-playground/build/xs/grhsim/wolvrix_xs_pre_reg_to_mem.json \
  XS_WOLF_GRHSIM_ENABLE_STATS=0 \
  XS_WOLF_GRHSIM_RESUME_FROM_STATS_JSON=0 \
  XS_WOLF_GRHSIM_POST_STATS_JSON=/home/gaoruihao/wksp/wolvrix-playground/tmp/no0216_cbaw_profile_20260703/grhsim/wolvrix_xs_post_stats.json \
  XS_WOLF_GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE=108 \
  XS_WOLF_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE=4096 \
  XS_VM_BUILD_JOBS=32
```

CoreMark 50k runtime profile：

```text
source env.sh
EMU_RUNTIME_PROFILE=1 \
WOLVRIX_GRHSIM_SUPERNODE_TSV=/home/gaoruihao/wksp/wolvrix-playground/tmp/no0216_cbaw_profile_20260703/run/grhsim_supernode_fire.tsv \
make run_xs_wolf_grhsim_emu \
  RUN_ID=no0216_cbaw_profile50k_20260703 \
  XS_GRHSIM_BUILD=tmp/no0216_cbaw_profile_20260703/grhsim \
  XS_SIM_MAX_CYCLE=50000 \
  XS_WAVEFORM=0 \
  XS_WAVEFORM_FULL=0 \
  XS_COMMIT_TRACE=0 \
  XS_PROGRESS_EVERY_CYCLES=25000 \
  XS_LOG_BEGIN=0 \
  XS_LOG_END=0
```

汇总产物：

```text
tmp/no0216_cbaw_profile_20260703/no0216_cbaw_profile_work_summary.json
```

## 4. 当前进展

### 4.1 build 结果

build 成功，且确认 `GRHSIM_EMIT_RUNTIME_PROFILE=1` 生效：

| 项 | 值 |
| --- | --- |
| build log | `build/logs/xs/xs_wolf_grhsim_build_no0216_cbaw_profile_build_20260703.log` |
| build dir | `tmp/no0216_cbaw_profile_20260703/grhsim` |
| emu | `tmp/no0216_cbaw_profile_20260703/grhsim/grhsim-compile/emu` |
| emu size | `114961168` bytes |
| static TSV | `tmp/no0216_cbaw_profile_20260703/grhsim/grhsim_emit/grhsim_supernode_static.tsv` |
| static rows | `72369` data rows |
| activity-schedule | `240854ms` |
| write_grhsim_cpp | `49534ms` |
| emit total | `320131ms` |

本轮结构复现 current CBAW FM8：

| stage | boundary | dag | compute-compute |
| --- | ---: | ---: | ---: |
| after P5 coarsen | `3160612` | `2520174` | `2810089` |
| after DP before FM | `2621811` | `650955` | `2271288` |
| after FM | `2356253` | `609345` | `2005730` |
| final P8 replay | `2359493` | `609375` | `2008970` |

### 4.2 runtime 结果

CoreMark 50k profile run 成功：

| 项 | 值 |
| --- | ---: |
| runtime log | `build/logs/xs/xs_wolf_grhsim_no0216_cbaw_profile50k_20260703.log` |
| fire TSV | `tmp/no0216_cbaw_profile_20260703/run/grhsim_supernode_fire.tsv` |
| fire rows | `72369` |
| instr | `73580` |
| cycleCnt | `49996` |
| guest cycle spent | `50001` |
| IPC | `1.471718` |
| host time | `329743ms` |

runtime log 末尾确认：

```text
[GRHSIM_RUNTIME_PROFILE] supernode_fire_tsv=/home/gaoruihao/wksp/wolvrix-playground/tmp/no0216_cbaw_profile_20260703/run/grhsim_supernode_fire.tsv rows=72369
```

## 5. work 口径

NO0190 口径下：

```text
work_total = f * (n_comp + n_src + n_sink + n_const)
```

`a_succ` 是 static/topology 辅助列，不计入 `work_total`；summary JSON 里另存 `a_succ_work = f * a_succ`，用于后续诊断。

| phase | rows | nonzero rows | fire | work_comp | work_src | work_sink | work_const | work_total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| compute | `71872` | `71872` | `857550789` | `48921688198` | `14102729858` | `0` | `15456361058` | `78480779114` |
| commit | `497` | `438` | `8692250` | `0` | `0` | `13042933170` | `0` | `13042933170` |
| total | `72369` | `72310` | `866243039` | `48921688198` | `14102729858` | `13042933170` | `15456361058` | `91523712284` |

相对旧 2026-06-23 GrhSIM runtime-profile 口径：

| 指标 | 2026-06-23 | current CBAW NO0216 | delta |
| --- | ---: | ---: | ---: |
| total_fire | `912829533` | `866243039` | `-46586494` |
| compute_fire | `903887033` | `857550789` | `-46336244` |
| commit_fire | `8942500` | `8692250` | `-250250` |
| total_work | `96807800085` | `91523712284` | `-5284087801` |
| compute_work | `82652705865` | `78480779114` | `-4171976751` |
| commit_work | `14155094220` | `13042933170` | `-1112161050` |

旧数据只用于说明 current CBAW 比 2026-06-23 profile 口径降低了 dynamic work；本文的决策对照仍以本轮 2026-07-03 产物为准。

## 6. top supernodes

Top by fire：

| rank | supernode | phase | f | n_comp | n_src | n_sink | n_const | a_succ | work_total |
| ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | `71901` | commit | `200653` | `0` | `0` | `402` | `0` | `402` | `80662506` |
| 2 | `4104` | compute | `200098` | `57` | `24` | `0` | `24` | `1` | `21010290` |
| 3 | `4105` | compute | `200098` | `56` | `24` | `0` | `24` | `0` | `20810192` |
| 4 | `4106` | compute | `200098` | `56` | `24` | `0` | `24` | `0` | `20810192` |
| 5 | `4107` | compute | `200098` | `56` | `24` | `0` | `24` | `0` | `20810192` |

Top by work：

| rank | supernode | phase | f | n_comp | n_src | n_sink | n_const | a_succ | work_total |
| ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | `71872` | commit | `50050` | `0` | `0` | `42937` | `0` | `42937` | `2148996850` |
| 2 | `72081` | commit | `50050` | `0` | `0` | `18439` | `0` | `18439` | `922871950` |
| 3 | `71906` | commit | `50050` | `0` | `0` | `5130` | `0` | `5130` | `256756500` |
| 4 | `71875` | commit | `50050` | `0` | `0` | `4096` | `0` | `4096` | `205004800` |
| 5 | `71877` | commit | `50050` | `0` | `0` | `4096` | `0` | `4096` | `205004800` |

直接观察：

- top by fire 是一个高频 commit supernode 和一串高频 compute supernode。
- top by work 被大 sink-count commit supernode 主导，尤其 `71872` 的 `n_sink=42937`，单点 `work_total=2148996850`。
- 后续 top multiplicity 诊断不应只看 compute fire；需要同时把 top-by-work commit sink 与 boundary/value root 归因打通。

## 7. 与 fresh GSim 2026-07-03 对照

fresh GSim profile 来自：

```text
build/logs/xs/xs_gsim_no0214_rtprof50k_profile_20260703.log
```

GSim stdout 口径：

```text
active_supernodes=766629270
nodes=35103020807
ref_enodes=114467111515
non_ref_enodes=66559770864
total_enodes=181026882379
host_time=44777ms
```

对照表：

| 指标 | current CBAW GrhSIM NO0216 | fresh GSim profile | ratio |
| --- | ---: | ---: | ---: |
| host time | `329743ms` | `44777ms` | `7.364x` |
| dynamic fire / active supernodes | `866243039` | `766629270` | `1.130x` |
| compute fire / active supernodes | `857550789` | `766629270` | `1.119x` |
| GrhSIM work / GSim stdout total_enodes | `91523712284` | `181026882379` | `0.506x` |
| GrhSIM work / GSim stdout nodes | `91523712284` | `35103020807` | `2.607x` |

注意：GrhSIM `work_total` 是 TSV 静态列 join fire 后的 NO0190 work 口径；GSim 这里是 fresh stdout 的 `nodes/enodes`，不是同构 TSV work。上表只能说明动态规模的相对量级，不能把 `total_enodes` 直接解释成 GSim `work_total`。

host-time 对照：

| run | host time | ratio vs NO0216 |
| --- | ---: | ---: |
| GrhSIM current no-profile, 2026-07-03 | `321007ms` | `1.027x` |
| GrhSIM current `EMU_RUNTIME_PROFILE=1` but emit 未打开 runtime profile, 2026-07-03 | `331344ms` | `0.995x` |
| GSim no-profile, 2026-07-03 | `46237ms` | `7.132x` |
| GSim profile, 2026-07-03 | `44777ms` | `7.364x` |

## 8. 结论

NO0215 阶段 A 已补齐 current CBAW 的 dynamic work 口径，可替代 NO0214 中“缺少 current `GRHSIM_EMIT_RUNTIME_PROFILE=1` 数据”的空白。

本轮数据不支持把下一步改成“单独 fork 一个 compute-node builder”。理由：

- current CBAW 仍复用同一路径，静态结构与 NO0214 对齐，profile-enabled build 也通过，说明补 profile 不需要新 builder。
- dynamic fire 相对 fresh GSim active supernodes 是 `1.130x`，不是数量级膨胀；单靠 compute-node fire 规模不能解释 `7.364x` host gap。
- `total_work=91.52B` 中 compute work 占 `85.75%`，但 top-by-work 的最大单点来自 commit sink supernode；下一步诊断必须同时看 compute multiplicity 和 commit sink work。
- fresh GSim 只有 stdout `nodes/enodes`，没有同构 TSV work；后续如果要严格比较 work，需要补 fresh GSim static/fire TSV，而不是把 `enode` 当作 `node` 或 `work_total`。

因此 NO0215 后续优先级保持不变，但阶段 B 的 top multiplicity 诊断要扩展一项 runtime attribution：把 `top_by_fire/top_by_work` 的 supernode 映射回 root/value/atom/segment，并区分 compute work 与 commit sink work。阶段 C/D/E 继续以 exact-delta coarsen、DP 后 gap 收敛、P7 refinement 为主线。

## 9. 验收标准

- build 产出 profile-enabled `emu`。
- emit 产出 `grhsim_supernode_static.tsv`。
- runtime 产出 `grhsim_supernode_fire.tsv`。
- 50k bounded workload 正常跑满，`instr/cycle` 与 current CBAW no-profile run 对齐。
- NO0214 中缺失的 current CBAW dynamic work ratio 可用本轮数据替代。

验收状态：全部完成。

## 10. 阶段 B 衔接记录

阶段 B 已在同日继续执行，主记录写入 [`NO0215 §4.1`](./NO0215_cbaw_multiplicity_reduction_action_plan_20260703.md)。本处只记录与阶段 A 动态 work 结论的衔接：

- 阶段 B stop-after 继续使用 current CBAW FM8 固定口径，结构复现阶段 A build：`72369` supernodes，final `boundary=2359493`、`dag=609375`、`compute_compute=2008970`。
- 新增 CBAW top-root JSON：`tmp/no0215_phase_b_20260703/grhsim/grhsim_emit/activity_schedule_cbaw_stats.json`。
- 扩大采样后输出 `315` 条 top-root reports；reported roots 覆盖 after-DP targets `72793 / 2621811 = 2.7764%`。
- top after-DP roots 以 `guard|mffc`、1-bit high-fanout 形态为主，但覆盖率很低；结合阶段 A 的 dynamic work 结论，下一步不应转向独立 builder，而应优先做 DP 全局成本模型和分散型 P7 move attribution。

因此阶段 A 的结论保持不变：current work 数据不支持 fork 独立 compute-node builder；阶段 B 进一步说明 top multiplicity 不是少数 root 集中问题，阶段 C/D/E 仍按 NO0215 的 exact-delta coarsen、DP 后 gap 收敛、P7 attribution/refinement 顺序推进。
