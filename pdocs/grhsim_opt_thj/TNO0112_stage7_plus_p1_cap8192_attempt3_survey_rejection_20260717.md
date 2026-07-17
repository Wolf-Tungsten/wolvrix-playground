# TNO0112 Stage 7+ P1 cap8192 attempt3 survey rejection

记录日期：2026-07-17

状态：P1 `cap4096/default` 对 `cap8192` 的 attempt3 在正式运行前被双 node admission 拒绝。N0 的 30 秒 whole-node survey 通过，N1 的 logical CPU112 minimum idle 只有 `60.020000%`，低于 `95%` 硬门槛；因此没有启动任何 `perf stat` 或 SimTop 50k，没有 walltime/PMU 样本，也没有创建 attempt3 group 目录。本记录只裁决机器窗口，不产生 cap8192 性能结论。

## 1. Runner 与 admission protocol 复核

本轮继续比较 [TNO0106](./TNO0106_stage7_plus_p1_cap8192_strict_window_rejection_20260717.md) 和 [TNO0111](./TNO0111_stage7_plus_p1_cap8192_attempt2_survey_rejection_20260717.md) 的同一对象：

```text
A/control:   s14_default   commit cap 4096
B/candidate: s14_cap8192   commit cap 8192
```

执行前只读复核 `run_formal.sh` 与 `run_balanced_pair.sh`，确认正式 runner 仍保持以下约束：

- workload 同时使用 `taskset -c`、`numactl --physcpubind` 与 `numactl --membind`；
- binary、CoreMark image 和 `nemu.so` 都必须来自 node-local `/dev/shm` staging，N0/N1 使用独立 inode；
- `setarch x86_64 -R` 对应 current NO0300 fixed-ASLR 基线；
- pre-run gate 检查对应 node 的 `192` 个 logical CPU，运行期检查除 target 外的 `191` 个 logical CPU；mean idle `>=99%`、minimum idle `>=95%`、target 与 SMT sibling 各 `>=98%`，门槛未降低；
- 按 [TNO0110](./TNO0110_walltime_headline_criterion_and_re_evaluation_20260717.md)，正式样本还必须存在唯一且为正整数的 `Host time spent`，并写出 `walltime_count=1`、`walltime_ok=1`。

镜像核配置保持 N0 target CPU43 / sibling CPU235 / helper CPU191，N1 target CPU139 / sibling CPU331 / helper CPU95。attempt3 先分别执行双 node 30 秒 survey，只有两侧同时通过才允许进入 ABBA+BAAB；本轮未满足这一入口条件。

## 2. Attempt3 absolute survey result

| node | logical CPU count | mean idle | minimum idle | minimum CPU | target idle | sibling idle | 判定 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| N0 | `192` | `99.283177%` | `96.960000%` | CPU212 | CPU43 `99.600000%` | CPU235 `99.030000%` | PASS |
| N1 | `192` | `99.044479%` | `60.020000%` | CPU112 | CPU139 `98.160000%` | CPU331 `99.470000%` | **FAIL: minimum** |

N1 的 CPU count、whole-node mean、target 与 sibling 均通过，但 CPU112 的 minimum 明确低于 `95%`。不能用 `99.044479%` 的高平均值掩盖单核持续污染，也不能因为 N0 已通过就只跑单 node。原始 survey 为：

```text
build/logs/xs_perf/page_local_retest_stage7plus_20260716/stage14_cap8192_strict_p1_attempt3_survey_20260717/n0.log
build/logs/xs_perf/page_local_retest_stage7plus_20260716/stage14_cap8192_strict_p1_attempt3_survey_20260717/n1.log
```

## 3. N1 外部负载旁证

survey 前后的只读进程检查再次观察到两个未绑定到本任务镜像核的外部进程：

| PID | process | observed CPU / load | affinity | memory nodes | 与 survey 的关系 |
| ---: | --- | --- | --- | --- | --- |
| `2816950` | `htop` | survey 前约 `37.8%` CPU、位于 CPU112；survey 后迁移到 CPU176 | `0-383` | `0-1` | CPU112 正是 N1 minimum CPU；可迁移进程与该低 idle 同时出现 |
| `859143` | Java/Bloop daemon | 约 `29.9%` CPU、观测于 CPU104 | `0-383` | `0-1` | 同属 N1 的额外外部负载，但不是本轮 minimum CPU |

以上只用于解释 admission rejection，不把瞬时 `ps` 数字替代 30 秒 `mpstat` gate，也不声称能逐采样唯一归因。本任务没有 kill、renice 或修改这些进程的 affinity。

## 4. Walltime 与后续边界

由于 N1 survey 失败，本轮没有调用 balanced runner，N0/N1 的 ABBA 与 BAAB 均为零正式样本。不存在可接受的：

```text
Host time spent
walltime_count / walltime_ms / walltime_ok
perf CSV / PMU counters
placement / runtime-monitor result
attempt3 group directory
```

因此 current C++ native commit cap 继续保持 `4096`；这来自既有 walltime 证据和本轮没有新增有效样本，而不是 attempt3 测得 cap8192 回退。下一次必须重新进行双 node admission；只有两侧同时通过后，才从全新目录完整执行 ABBA+BAAB，按 binary header 映射 control/candidate，并以每个样本的绝对 `Host time spent`、两种顺序 wall delta、combined wall delta 与 control/candidate spread 裁决。cycles 只保留为诊断指标。
