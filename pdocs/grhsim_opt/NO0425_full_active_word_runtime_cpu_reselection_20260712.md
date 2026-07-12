# NO0425 Full active-word runtime CPU reselection

日期：2026-07-12

## 1. Rejected CPU191 gates

按 [NO0424](./NO0424_full_active_word_fixed_aslr_runtime_plan_20260712.md) 的 99% quiet gate，在任何 PMU run 前
对 CPU191/383 连续尝试四次：

| attempt | CPU191 idle | CPU383 idle | result |
| ---: | ---: | ---: | --- |
| 1 | 96.68% | 97.32% | reject |
| 2 | 100.00% | 97.66% | reject |
| 3 | 100.00% | 97.01% | reject |
| 4 | 98.33% | 97.67% | reject |

每次都至少有一秒出现约 5%~9% 用户态活动，通常落在 sibling CPU383；等待和 10 秒 pidstat 后仍复现，因此
CPU191/383 不再适合本组长达约 80 秒的 50k runtime。四份 rejected log 保留，未启动 candidate preflight，
没有 perf CSV 或可误用的性能样本。

## 2. Immediate NUMA1 resurvey

将 survey 进程固定到 CPU0，重新对 NUMA1 的 96 对 SMT siblings 做五秒采样。结果中：

```text
CPU191/383: 98.20% / 97.40%
CPU131/323: 99.40% / 100.00%  (best current pair)
```

CPU131/323 同属 node/socket/core `1/1/131`，与原计划微架构和 NUMA 条件一致。因此在任何 PMU 样本前将
正式运行核修正为 CPU131，sibling 监控改为 CPU323。

## 3. Locked configuration

从下一次 candidate 100-cycle preflight 起，整组固定为：

```text
taskset CPU=131
SMT sibling=323
NUMA node=1
ASLR=setarch -R
```

每轮前仍执行三秒 `>=99%` quiet gate，不因后续 survey 排名变化而换核。NO0424 的 event、功能、baseline
spread 和 layout caveat 均不变；本轮 absolute cycles 不与其他 CPU 的历史 GSim 数据直接相除。
