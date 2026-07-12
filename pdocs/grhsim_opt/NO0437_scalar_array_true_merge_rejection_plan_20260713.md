# NO0437 Scalar-array true-merge rejection plan

日期：2026-07-13

## 1. Objective

[NO0436](./NO0436_current_commit_machine_source_attribution_gate_20260713.md) 定位 140 个 latest direct
flattened states，对应 79 个 same-FIR GSim array bases；143 个 instruction samples 约为 commit/direct total 的
`16.475%/2.142%`，通过后续诊断门槛。

本轮不实现 re-aggregation，先回答每个动态候选在 current reg-to-mem 中属于：

1. 已进入 discovery、但被 read closure / init / write shape / priority / shared storage 拒绝；
2. 已 true-merge，crosswalk 或 sampled state 连接有误；
3. 只形成 intent annotation；
4. 完全未进入 current concat/slice/name discovery。

只有共同 rejection class 仍覆盖 direct total 至少 1%（67 samples），才进入 lowering probe。

## 2. Full-group diagnostic switch

NO0357 reg-to-mem summary覆盖全部 4,318 groups，但 hardcoded verbose 条件只输出前 20、每 100、成员数
`>=500`、decoded-write 和 edge-padded groups，共 140 个 first/last records。现有日志不足以连接 79 个动态 bases。

在 `wolvrix/lib/transform/reg_to_mem.cpp` 增加默认关闭的环境诊断：

```text
WOLVRIX_REG_TO_MEM_PROFILE_ALL_GROUPS=1
```

它只能把 `verboseGroup` 扩展为所有 groups；不得改变 discovery、match、rewrite、stats、IR 或默认日志。值为空、`0`、
`false`、`off` 时关闭，其余非空值开启。启动时记录 `profile_all_groups=0/1`，避免日志口径不明。

## 3. Build and behavior gates

1. nested `transform-reg-to-mem` target 重新构建；
2. 默认环境运行 `ctest -R '^transform-reg-to-mem$'`；
3. 开启 full-group 环境再运行同一测试；
4. 两次均须 pass，默认日志不增加逐组输出；
5. editable reinstall 后确认 Python 加载新 native library。

该开关只有日志副作用；不为诊断更改 pass options、group 顺序或写回策略。若测试或同一 checkpoint summary 计数变化，
停止后续归因。

## 4. Targeted SimTop rerun

复用 NO0357 同一 pre-reg checkpoint、read args 和 current options：

```text
checkpoint = build/xs_grhsim_event_order_src_20260710/grhsim/wolvrix_xs_pre_reg_to_mem.json
resume     = WOLVRIX_XS_GRHSIM_RESUME_FROM_PRE_REG_TO_MEM_JSON=1
stop       = WOLVRIX_XS_GRHSIM_STOP_AFTER_PRE_SCHED=1
```

driver 在 reg-to-mem 后、activity-schedule 前退出，不运行 schedule/C++ emit。要求 summary 精确复现 NO0357：

```text
groups=4318
true_groups=835
edge_padded_true_groups=174
intent_candidate_groups=760
intent_groups=254
true_skipped=3483
```

full log 应为每个可处理 group 输出 first/last members 和实际 match/rewrite stage；总 transform 计数或阶段配置与 NO0357
不一致时作废。

## 5. Candidate connection

对 NO0436 的 140 flattened states：

1. 从 first/last register 构造只允许数字 row index 变化的 group pattern；
2. 连接 group ID、members、element width、anchors、decoded/edge/shared 属性和最终 outcome；
3. 未命中任何 pattern 标为 `discovery_missing`，不能按相似前缀强配；
4. 对每个 rejection reason 汇总 states/samples/aggregate bases；
5. 复核 PTW bitmap、L2 PMU、DCache meta、FTQ 和 uTage 五个头部。

已知旧日志中 L2 PMU/uTage/FTQ 为 `branch_not_in_update`，PTW bitmap/DCache meta 未见 group；这些只是 preflight，
不替代全量结果。

## 6. Decision

若某个可修正 rejection/discovery class 覆盖至少 67 samples，并能以统一结构规则识别，则下一阶段只做该 class 的
默认关闭 transform probe。若信号分散、主要是必要动态索引/多写优先级/读闭包，或任何放宽会重开已否决的全局
preserve-aggregate，则停止 re-aggregation，回到 compute payload。

## 7. Planned artifacts

```text
build/logs/xs_perf/no0437/{build,test_default,test_all_groups,install}.log
build/logs/xs_perf/no0437/simtop_reg_to_mem_all_groups.log
build/logs/xs_perf/no0437/scalar_array_group_connection.tsv
build/logs/xs_perf/no0437/{outcome,rejection,base}_summary.tsv
build/logs/xs_perf/no0437/connection_summary.txt
```
