# TNO0062 Stage 8 plain-DP segment-penalty structure scan

日期：2026-07-15

状态：完成 current-default NO0300 plain-DP `0.5/1.0/1.5/2.0` 结构扫描；默认 identity 已闭合，选择低侧 `0.5` 与高侧 `2.0` 继续 fresh emit、O3 build 和 SimTop 50k。

## 1. 实验对象

本轮按 [TNO0061](./TNO0061_stage8_plain_dp_penalty_sweep_plan_20260715.md) 只改变：

```text
WOLVRIX_XS_GRHSIM_DP_SEGMENT_PENALTY_PPM
= 500000 / 1000000 / 1500000 / 2000000
```

其余生成配置保持仓库当前默认 NO0300：ASLR 关闭，direct state-read、pure-event bypass/profile/packing、post-DP refine、Kahn pack、local/common-owner clone 和 full-active-word consume 均关闭，final topo 为 `level-id`。四点均源自 canonical pre-reg-to-mem checkpoint：

```text
build/worktrees/activity_baseline_20260714/build/xs_activity_baseline/grhsim/wolvrix_xs_pre_reg_to_mem.json
sha256=55823181a7d73d77f99c3c5e59a09ad3e474051d8eac4c37eb03aaa23db00308
```

首次并行 `make xs_wolf_grhsim_emit` 时，多个 target 同时执行共享 `py_install`，竞争 `wolvrix/build/skbuild`，导致 p050/p150/p200 在进入脚本前失败。该失败与 activity schedule 无关。后续在 binding 已安装后直接调用 `scripts/wolvrix_xs_grhsim.py`，使用隔离输出目录；p050 通过既有 `ENABLE_STATS` 路径写出 post-reg-to-mem JSON，p150/p200 通过 `RESUME_FROM_STATS_JSON` 只读同一 graph checkpoint。没有并发 editable build，也没有改变 pass 输入。

## 2. 默认 identity

p100 显式传入 `1000000 PPM`，native/XS 日志分别记录：

```text
dp_segment_penalty_ppm=1000000
activity-schedule DP segment penalty: ppm=1000000
```

fresh stats 与 2026-07-14 current-default NO0300 baseline 逐字节相同：

```text
e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77
cmp_status=0
```

这同时闭合了 C++ 默认值、CLI/Python binding 和 XS 环境变量接线没有改变 inactive/default 行为。

## 3. 结构结果

绝对值如下；commit partition 在四点均保持 `485`，compute-commit pairs 均保持 `262225`。

| PPM | total SN | compute SN | DAG | boundary values | total BAE | compute pairs | ops mean | outdeg p99 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 500000 | 63903 | 63418 | 529017 | 1000466 | 1983746 | 1721521 | 91.453 | 99 |
| 1000000 | 63726 | 63241 | 528622 | 1000463 | 1983923 | 1721698 | 91.707 | 100 |
| 1500000 | 63722 | 63237 | 528583 | 1000463 | 1983927 | 1721702 | 91.713 | 100 |
| 2000000 | 63583 | 63098 | 528510 | 1000471 | 1984205 | 1721980 | 91.913 | 100 |

相对 p100 的变化为：

| PPM | compute SN | DAG | boundary values | total BAE | compute pairs |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 500000 | +177 (+0.280%) | +395 (+0.075%) | +3 (+0.0003%) | -177 (-0.0089%) | -177 (-0.0103%) |
| 1500000 | -4 (-0.006%) | -39 (-0.007%) | 0 | +4 (+0.0002%) | +4 (+0.0002%) |
| 2000000 | -143 (-0.226%) | -112 (-0.021%) | +8 (+0.0008%) | +282 (+0.0142%) | +282 (+0.0164%) |

方向符合 plain-DP 目标：降低 penalty 会接受更多 segment 换取少量 BAE；提高 penalty 会接受少量 BAE 换取更少 segment。变化幅度都很温和，且没有 commit、cap、topo 或功能不变量失败。

## 4. 候选决策

- `1.5` 的 SN、DAG、BAE 变化都低于 `0.01%`，不单独 build；
- `0.5` 是低 penalty 侧唯一有可见变化的点，虽然 BAE 仅下降 `177`，但 compute SN 只增加 `0.28%`，按软结构口径继续 50k，避免漏掉 active/layout 的非线性收益；
- `2.0` 是高 penalty 侧代表点，compute SN 减少 `143`，总 BAE 只增加 `282`，继续检查函数/dispatch 减少是否能抵消边开销。

因此下一步对 p050、p200 分别执行 fresh emit、O3 build、fixed-ASLR 功能门禁和 SimTop 50k。默认值仍保持 `1000000`，结构结果本身不支持修改仓库默认。

## 5. 产物

```text
build/xs_activity_stage8_dp_p050_20260715/grhsim/grhsim_emit/activity_schedule_supernode_stats.json
build/xs_activity_stage8_dp_p100_20260715/grhsim/grhsim_emit/activity_schedule_supernode_stats.json
build/xs_activity_stage8_dp_p150_20260715/grhsim/grhsim_emit/activity_schedule_supernode_stats.json
build/xs_activity_stage8_dp_p200_20260715/grhsim/grhsim_emit/activity_schedule_supernode_stats.json
build/logs/xs/xs_wolf_grhsim_build_activity_stage8_dp_p050_20260715.log
build/logs/xs/xs_wolf_grhsim_build_activity_stage8_dp_p150_20260715.log
build/logs/xs/xs_wolf_grhsim_build_activity_stage8_dp_p200_20260715.log
```
