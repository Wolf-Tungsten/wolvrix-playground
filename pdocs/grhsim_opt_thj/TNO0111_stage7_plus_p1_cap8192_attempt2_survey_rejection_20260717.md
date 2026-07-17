# TNO0111 Stage 7+ P1 cap8192 attempt2 survey rejection

记录日期：2026-07-17

状态：P1 `cap4096/default` 对 `cap8192` 的 attempt2 在 N0、N1 whole-node survey 阶段均被拒绝。两个节点的 target 与 SMT sibling idle 均通过，但 whole-node mean 和 minimum idle 均未达到硬门槛。因此 N0/N1 的 ABBA、BAAB 四项正式 run 均未启动，没有 walltime 或 PMU 样本，也没有创建 attempt2 group 目录；本记录不产生任何性能推导。

## 1. 对象与 admission protocol

比较对象继承 [TNO0106](./TNO0106_stage7_plus_p1_cap8192_strict_window_rejection_20260717.md)：

```text
A/control:   s14_default   commit cap 4096
B/candidate: s14_cap8192   commit cap 8192
```

attempt2 继续使用相同的双 node 独立 page-local staging 和镜像 CPU：N0 target CPU43 / sibling CPU235，N1 target CPU139 / sibling CPU331。whole-node admission 标准没有调整：

| gate | threshold |
| --- | ---: |
| logical CPU count | `192` |
| whole-node mean idle | `>=99%` |
| whole-node minimum idle | `>=95%` |
| target idle | `>=98%` |
| SMT sibling idle | `>=98%` |

## 2. Attempt2 absolute survey result

| node | CPU count | mean idle | min idle | min CPU | target idle | sibling idle | 判定 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| N0 | `192` | `98.226%` | `86.760%` | CPU29 | CPU43 `98.930%` | CPU235 `99.530%` | FAIL: mean/min |
| N1 | `192` | `97.155%` | `78.320%` | CPU160 | CPU139 `98.200%` | CPU331 `98.600%` | FAIL: mean/min |

N0、N1 的失败都来自 whole-node mean/minimum，而不是 target 或 sibling。对应原始 `mpstat` survey 为：

```text
build/logs/xs_perf/page_local_retest_stage7plus_20260716/stage14_cap8192_strict_p1_attempt2_survey_20260717/n0.log
build/logs/xs_perf/page_local_retest_stage7plus_20260716/stage14_cap8192_strict_p1_attempt2_survey_20260717/n1.log
```

admission 失败后 runner 没有进入正式运行。N0 ABBA、N0 BAAB、N1 ABBA、N1 BAAB 均为零样本，`groups/n0` 和 `groups/n1` 下没有创建对应的 attempt2 ABBA/BAAB 目录。

## 3. Walltime 与结论边界

[TNO0110](./TNO0110_walltime_headline_criterion_and_re_evaluation_20260717.md) 将 SimTop 50k `Host time spent` 定为最终 headline，但没有放宽 whole-node admission 或运行期硬门禁。本轮没有启动 emu，因此不存在可用的：

```text
Host time spent
walltime_count / walltime_ms / walltime_ok
perf CSV
PMU counters
```

survey idle 只能裁决机器窗口能否接纳正式 run，不能用于推导 cap8192 相对 cap4096 的性能。当前 C++ native commit cap 默认值继续保持 `4096`，原因是本轮没有新增有效性能证据，而不是本轮测得 cap8192 回退。

后续重试仍须等待节点同时满足既定门槛，并分别从空目录完整执行：

```text
ABBA: default / cap8192 / cap8192 / default
BAAB: cap8192 / default / default / cap8192
```

不能拼接 TNO0106 中 monitor-failed 的 A1，也不能拼接本轮 survey；不会因为 walltime 成为 headline 或机器暂时繁忙而降低 mean、minimum、target、sibling 门槛。
