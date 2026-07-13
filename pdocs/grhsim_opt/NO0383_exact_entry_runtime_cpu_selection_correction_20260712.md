# NO0383 Exact-entry runtime CPU selection correction

日期：2026-07-12

## 1. CPU138 quiet gate 连续失败

按 [NO0382](./NO0382_exact_entry_fixed_aslr_runtime_plan_20260712.md) 在任何 PMU run 前检查 CPU138 及其 SMT sibling
CPU330。五次三秒 gate 均未同时达到 `>=99%`：

| Attempt | CPU138 idle | CPU330 idle | Decision |
| --- | ---: | ---: | --- |
| 1 | 97.66% | 98.00% | reject |
| 2 | 100.00% | 98.67% | reject |
| 3 | 98.01% | 96.35% | reject |
| 4 | 97.66% | 97.33% | reject |
| 5 | 98.67% | 97.33% | reject |

期间全机 load average 约 `1.68~5.46/384`，没有其他 emu/perf/编译任务，因此不是全机饱和。将整个监控 shell
绑定到 CPU0 后 attempt 5 仍失败，排除了本次 `mpstat`/编排进程自身偶然落到目标核这一主要混淆。

`pidstat`/process-tree 检查在 CPU330 一侧观察到多线程 VS Code server 进程树，在 CPU138 一侧观察到 CI Runner
进程树；它们的 affinity 都覆盖 0-383，且存在周期性用户态脉冲。无法也不应移动或终止其他用户进程，所以继续等待
CPU138/330 不再是可靠门禁策略。五个 rejected attempts 原样保留，未启动任何 perf run。

## 2. NUMA1 全核 survey

将 survey 进程绑定 CPU0，对 NUMA1 的 96 对物理核做五秒 `mpstat`。共有 17 对 sibling 的最低 idle `>=99%`；
最高的候选为：

| Primary | Sibling | Primary idle | Sibling idle | Min |
| ---: | ---: | ---: | ---: | ---: |
| 147 | 339 | 99.60% | 99.60% | 99.60% |
| 148 | 340 | 100.00% | 99.40% | 99.40% |
| 150 | 342 | 99.40% | 99.80% | 99.40% |
| 138 | 330 | 99.20% | 97.80% | 97.80% |

CPU147/339 与 CPU138/330 同属 socket 1、NUMA node 1 和相同微架构，因此选择 CPU147 作为本轮新的运行核，CPU339
作为 sibling 监控核。

## 3. 口径修正

NO0382 除 CPU 编号外保持不变：

```text
taskset: CPU147
NUMA:    node1
sibling: CPU339
ASLR:    setarch -R
order:   exact baseline / direct / exact baseline
```

每轮前 CPU147/339 仍必须三秒平均 idle `>=99%`；现场 baseline/direct/baseline 和 baseline cycles spread `<=1%`
继续承担机器负载控制，因此相对 direct effect 有效。

由于运行核发生变化，本轮 absolute cycles 不直接除以 [NO0344](./NO0344_fixed_aslr_gsim_grhsim_direct_compare_gate_20260712.md)
在 CPU138 上的历史 GSim cycles。可以跨轮比较 direct 相对 baseline 的百分比与 NO0365/NO0373 的方向，但若要更新
absolute GrhSIM/GSim cycles gap，必须另行在 CPU147 上现场重跑 GSim baseline。

下一步先对 CPU147/339 重新执行 quiet gate，再做 direct 100-cycle 五事件 preflight；不得把此前五个 rejected
CPU138 attempts 当作有效 preflight。
