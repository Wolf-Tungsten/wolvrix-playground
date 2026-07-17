# TNO0106 Stage 7+ P1 cap8192 strict window rejection

记录日期：2026-07-17

状态：P1 `cap4096/default` 对 `cap8192` 的 strict window 尚未形成有效性能组。初始 N0 survey 通过，N1 因 CPU104 明显忙碌失败；N0 ABBA try1 的首个 control 虽通过 pre-gate，但运行期 whole-node monitor minimum idle 降至 `94.710%`，因此该样本和未完成的整组 ABBA 全部作废。随后 N0 retry survey 也失败。本轮没有可用 PMU 对照，不拼接未来样本；下次从 attempt2 重新完整执行 ABBA+BAAB。

## 1. 对象与 page-local staging

P1 只比较 current C++ native-hybrid 下的 commit cap：

```text
A/control:   s14_default   commit cap 4096
B/candidate: s14_cap8192   commit cap 8192
```

两份 ELF 已分别复制到 N0/N1 独立 `/dev/shm` inode。staging 审计为：

| node | binary | inode | size | SHA256 |
| --- | --- | ---: | ---: | --- |
| N0 | `s14_default` | `5340` | `93,694,944` | `51b74981b0a23d93dc860e13f82248a3ec0c21153117df3f7889da55be918788` |
| N0 | `s14_cap8192` | `5346` | `93,671,816` | `28e871c4e66598b05659355b8027838f1a5e770beef803ec0434c0ef396bc1f7` |
| N1 | `s14_default` | `5343` | `93,694,944` | `51b74981b0a23d93dc860e13f82248a3ec0c21153117df3f7889da55be918788` |
| N1 | `s14_cap8192` | `5350` | `93,671,816` | `28e871c4e66598b05659355b8027838f1a5e770beef803ec0434c0ef396bc1f7` |

路径为：

```text
/dev/shm/grhsim_page_local_retest_tanghaojin_20260716_v1/n0/s14_default
/dev/shm/grhsim_page_local_retest_tanghaojin_20260716_v1/n0/s14_cap8192
/dev/shm/grhsim_page_local_retest_tanghaojin_20260716_v1/n1/s14_default
/dev/shm/grhsim_page_local_retest_tanghaojin_20260716_v1/n1/s14_cap8192
```

同一 binary 的双 node SHA 相同，不同 node inode 独立；因此没有再次混用 NFS file-backed page cache。正式样本仍须逐 run 用 `numa_maps` 验证实际页归属，不能只凭复制动作推断。

## 2. 初始双 node survey

whole-node admission 标准继续固定为：mean idle `>=99%`、minimum idle `>=95%`、target 与 SMT sibling 各 `>=98%`。初始 30 秒 survey 结果：

| node | mean idle | min idle | min CPU | target | sibling | 判定 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| N0 | `99.091%` | `95.620%` | CPU214 | CPU43 `98.300%` | CPU235 `98.170%` | PASS |
| N1 | `99.183%` | `62.150%` | CPU104 | CPU139 `99.100%` | CPU331 `99.870%` | FAIL |

N1 仍是 whole-node minimum gate 失败，而不是目标核或 sibling 失败；没有启动 N1 perf，也没有降低 gate 或干预外部进程。原始 survey：

```text
build/logs/xs_perf/page_local_retest_stage7plus_20260716/stage14_cap8192_strict_p1_survey_20260717/n0.log
build/logs/xs_perf/page_local_retest_stage7plus_20260716/stage14_cap8192_strict_p1_survey_20260717/n1.log
```

## 3. N0 ABBA try1 首个 control 作废

N0 初始 survey 通过后，以 CPU43、sibling CPU235 和 helper CPU191 启动 ABBA try1。绑定继续使用：

```bash
taskset -c 43 \
    numactl --physcpubind=43 --membind=0 \
    perf stat ... -- \
    setarch x86_64 -R <node-local-emu> ... -C 50000
```

首个 A1/control 的 30 秒 pre-gate 通过：

```text
whole-node mean idle = 99.125%
whole-node min idle  = 96.160% (CPU214)
CPU43                = 98.370%
CPU235               = 98.330%
gate-to-run gap      = 7 ms
```

运行期间除 target 外的 191 个 logical CPU monitor 为：

```text
mean_idle=99.189
min_idle=94.710
```

minimum idle 低于 `95%` 硬门槛，所以 `monitor_ok=0`。其它 gate 均通过：

```text
run_status=0
placement_ok=1
monitor_ok=0
perf_ok=1
scheduler_ok=1
function_ok=1
affinity_ok=1
```

placement 显示 `emu` 的 `21,264` 页和 `nemu.so` 的 `115` 页均在 N0，远端页为 `0`；affinity 为 CPU43，ASLR personality 为 `00040000`。这些通过项不能覆盖 runtime monitor 失败。虽然 `a1_perf.csv` 已写出计数，但该数据不进入任何均值、delta 或趋势判断。

runner 在首个无效样本后停止，未形成 B1/B2/A2。因此不能把 A1 与未来安静窗口中的三个样本拼成 ABBA，也不能把它与旧 cap 实验对照。整个 `stage14_cap8192_strict_p1_abba_try1` 只作为 rejection artifact 保留：

```text
build/logs/xs_perf/page_local_retest_stage7plus_20260716/groups/n0/stage14_cap8192_strict_p1_abba_try1/
```

## 4. Retry survey 再次拒绝

try1 停止后的 N0 retry survey 为：

| mean idle | min idle | min CPU | CPU43 | CPU235 | 判定 |
| ---: | ---: | ---: | ---: | ---: | --- |
| `98.873%` | `93.110%` | CPU5 | `97.090%` | `99.400%` | FAIL |

这次同时违反 whole-node mean、minimum 和 target CPU 三项门槛，因此没有立即重启 attempt2。原始证据：

```text
build/logs/xs_perf/page_local_retest_stage7plus_20260716/stage14_cap8192_strict_p1_survey_20260717/n0_after_abba_try1.log
```

## 5. 结论与重测边界

本轮只证明当前窗口不满足严格协议，没有产生 cap8192 相对 current cap4096 的性能结论。不能使用无效 A1 的 PMU，也不能据此修改 commit cap 默认；current C++ native default 继续保持 `4096`。

下次 N0 whole-node gate 恢复后，从新目录 `attempt2` 完整运行：

```text
ABBA: default / cap8192 / cap8192 / default
BAAB: cap8192 / default / default / cap8192
```

两组都必须独立满足 pre-gate、运行期 monitor、placement、PMU、scheduler、affinity、ASLR 和功能门禁。N1 也必须等待 CPU104 等整 node 负载消失后再按镜像 CPU139/sibling331 执行；不允许用 N0 单边或跨时间拼接替代双 node closure。

执行入口仍为：

```text
build/logs/xs_perf/page_local_retest_stage7plus_20260716/run_balanced_pair.sh
```
