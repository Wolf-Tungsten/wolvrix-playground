# TNO0036 Stage 3 explicit-off SimTop identity

记录日期：2026-07-14

状态：Stage 3 explicit-off 在 current-default NO0300 fresh checkpoint 上完成 stop-after-activity-schedule identity；stats 原始 JSON 与 baseline 逐字节一致，default path 未发生结构漂移。

## 1. 配置

复用 [TNO0022](./TNO0022_fresh_current_default_no0300_baseline1_20260714.md) 的 pre-reg-to-mem checkpoint，Stage 1/2 均关闭，显式设置：

```text
enable_local_shared_compute=false
local_shared_compute_max_fanout=2
local_shared_compute_max_width=64
local_shared_compute_max_clones=4096
local_shared_compute_max_cloned_op_ppm=5000
post_dp_refine_policy=off
kahn_level_pack_policy=off
stop_after_activity_schedule=true
```

本轮仍是默认 NO0300 生成语义；修改 inactive fanout/width 默认不会进入 clone discovery。

## 2. Identity 结果

candidate 与 current-default baseline stats SHA256 均为：

```text
e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77
```

原始 JSON `cmp=0`；递归比较 `182/182` 个 scalar leaf，mismatch `0`。关键字段：

| Metric | baseline | explicit off |
| --- | ---: | ---: |
| graph ops / values | `7,204,108 / 6,833,009` | `7,204,108 / 6,833,009` |
| total / compute / commit SN | `63,726 / 63,241 / 485` | `63,726 / 63,241 / 485` |
| DAG edges | `528,622` | `528,622` |
| boundary values | `1,000,463` | `1,000,463` |
| total BAE | `1,983,923` | `1,983,923` |
| local shared compute clones | `0` | `0` |

activity schedule 用时 `167,659 ms`，全脚本 `336,123 ms`；wall `5:37.98`，peak RSS `28,326,928 KiB`，exit `0`，无残留大图进程。

## 3. 产物与结论

```text
build/logs/xs/xs_wolf_grhsim_build_activity_stage3_local_clone_off_identity_20260714.log
build/xs_activity_stage3_local_clone_off_identity_20260714/grhsim/grhsim_emit/activity_schedule_supernode_stats.json
```

该结果与 [TNO0035](./TNO0035_stage3_true_clone_implementation_and_correctness_20260714.md) 的 default/explicit-off unit identity 一起证明：关闭 Stage 3 时不进入 discovery、graph mutation 或二次 rewrite，当前默认基线保持不变。下一步只开启 Stage 3 standalone，先看真实 clone 数和 exact structure，再决定 full emit/50k。
