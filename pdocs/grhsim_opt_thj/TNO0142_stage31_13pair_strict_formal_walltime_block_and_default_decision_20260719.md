# TNO0142 Stage 31 13-pair strict formal walltime block and default decision

日期：2026-07-19

状态：13-pair extended strict 在 N0 ABBA try1 中产生 3 个各自完全有效的样本，但
最后一个 control 在外部负载突增后未通过三次 whole-node admission，整组作废；N1
三次 admission 均明显不合格，没有启动 emu。当前没有任何完整 order，更没有双 NUMA
balanced `Host time spent`，因此 `cofire-strict-extended` 和 Stage30 `cofire-strict` 都
保持 C++ default-off，不能从不完整样本声称收益或回退。

## 1. 正式协议与绑定

control/strict12/strict13/image/NEMU 使用 TNO0141 的每 node 独立 `/dev/shm` inode。
本轮从机器即时负载中选择 N0 CPU86/SMT278，避免继续使用当时被 Java/功能任务占用的
CPU43；N1 使用 CPU139/SMT331。正式 workload 的实际绑定为：

```text
taskset -c <target> \
  numactl --physcpubind=<target> --membind=<node> \
  perf stat ... -- \
  setarch x86_64 -R <node-local-emu> \
    -i <node-local-image> --diff <node-local-nemu> -b 0 -e 0 -C 50000
```

N0/N1 helper 分别为 CPU191/95，monitor 覆盖目标 node 的全部 192 hardware threads。
每个样本先做 30 秒 admission：`mean_idle>=99%`、`min_idle>=95%`、target/sibling
`>=98%`；运行期除 target 外 191 threads 继续要求 mean/min。runner 同时检查：

- emu 页面本地率 `>=99.9%` 且至少 20,000 pages；NEMU 本地率 `>=95%` 且至少 100 pages；
- 五项 PMU scheduled、task-clock、context-switch rate、migration=0；
- `Cpus_allowed_list`、fixed ASLR personality、50k 功能终点；
- 唯一一个正的 SimTop `Host time spent`。

每条顶层命令与 runner 都先 source 仓库 `env.sh`。本轮没有降低门槛，也没有终止或
迁移外部任务。

## 2. N0 ABBA try1：前三样本有效、整组作废

raw group：

```text
build/logs/xs_perf/page_local_retest_stage7plus_20260716/groups/n0/
  stage31_deferred_activation_13pair_strict_extended_abba_try1/
```

前三个样本的 `run_status/placement/monitor/perf/scheduler/function/affinity/walltime_ok`
全为 1，功能终点全为 `instrCnt=73,580`、`cycleCnt=49,996`、guest=`50,001`：

| sample | variant | walltime_ms | instructions | emu pages N0/N1 | runtime mean/min idle |
| --- | --- | ---: | ---: | --- | --- |
| a1 | control | 74,499 | 164,223,551,908 | `21,260 / 0` | `99.415% / 95.920%` |
| b1 | strict13 | 74,452 | 164,203,155,058 | `21,272 / 0` | `99.409% / 97.610%` |
| b2 | strict13 | 74,532 | 164,203,155,111 | `21,272 / 0` | `99.387% / 96.010%` |

NEMU placement 均为 `115 / 0` pages。instructions 只作诊断；严格样本比 control 少约
20.397 million instructions，与 691 个 tracked values 的删除方向一致，但缺少 a2，不能
构造 control mean 或 A/B delta。

各样本 admission 的绝对 whole-node idle 为：

```text
a1 attempt1: threads=192 mean=99.349115% min=97.330%
b1 attempt1: threads=192 mean=99.387500% min=95.590%
b2 attempt1: threads=192 mean=99.307396% min=95.460%
a2 attempt1: threads=192 mean=99.274583% min=92.560%
a2 attempt2: threads=192 mean=97.310104% min=87.990%
a2 attempt3: threads=192 mean=86.602865% min=64.180%
```

a2 三次均失败，因此 runner 没有启动第四个 emu。不能把前三个样本与后续 attempt
拼接，也不能把两个 strict 样本均值 `74,492 ms` 与单个 control `74,499 ms` 当作正式
比较。

driver raw log：

```text
build/logs/xs_perf/stage31_deferred_activation_13pair_strict_extended_n0_abba_try1_driver.log
sha256=5a308d9b5c99a5d1b7849be790f8fbc231dd6e46cff561be8385d7795f4aa239
bytes=4505
```

## 3. N1 ABBA try1：admission 阻断

N1 使用同一 staging 规则和 CPU139/SMT331，三个 30 秒 admission 的绝对值为：

```text
a1 attempt1: threads=192 mean=96.980365% min=40.430%
a1 attempt2: threads=192 mean=96.935469% min=31.660%
a1 attempt3: threads=192 mean=96.263854% min=36.190%
```

三次均远低于 formal gate，未启动 emu，因此没有 N1 walltime/PMU 样本。driver：

```text
build/logs/xs_perf/stage31_deferred_activation_13pair_strict_extended_n1_abba_try1_driver.log
sha256=072732c19ea5a7f610ce8d1ffe366ff9c70a6d91f1a262e9184d4a76c93191fc
bytes=1310
```

N0 在同一阶段先通过三个样本、随后负载突增，N1 则从首窗就被重负载占用。这再次说明
两个 socket 的物理拓扑虽对称，实验环境并不对称；node 差异来自同时运行任务和
file-page placement，而不是 `taskset/numactl` 语法把 N1 绑定错了。

## 4. Default decision

1. 13-pair implementation、static、O3/link 和功能都通过，保留显式实验入口。
2. N0 try1 不完整，N1 无样本；没有 ABBA/BAAB 双 order，更没有双 NUMA等权 walltime。
3. `cofire-strict-extended` C++ 默认保持 `off`；XS 不设置独立默认。
4. Stage30 12-pair 仍只有 TNO0139 的单 N0 ABBA 完整组，也继续保持 `off`。
5. 后续安静窗口必须新建完整 attempt；只接受 fresh page-local、whole-node
   ABBA+BAAB 的绝对 `Host time spent`。cycles/instructions/static work 不能改变本结论。
