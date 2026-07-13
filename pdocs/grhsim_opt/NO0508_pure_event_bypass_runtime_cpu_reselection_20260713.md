# NO0508 Pure-event bypass runtime CPU reselection

日期：2026-07-13

## 1. Initial survey and rejection

按 [NO0507](./NO0507_simtop_pure_event_word_bypass_fixed_aslr_runtime_plan_20260713.md)，在任何 perf run 前对 NUMA1
做五秒 sibling-pair survey。共享 CI 负载很高，前两轮最佳 pair 分别为：

| Survey | Primary / sibling | Primary idle | Sibling idle | Min idle |
|---:|---|---:|---:|---:|
| 1 | 163 / 355 | 94.79% | 96.80% | 94.79% |
| 2 | 104 / 296 | 96.99% | 98.80% | 96.99% |

第二轮后临时锁定 CPU104/296，但三次独立三秒 quiet gate 均未同时达到 `>=99%`：

| Attempt | CPU104 idle | CPU296 idle | Decision |
|---:|---:|---:|---|
| 1 | 96.99% | 98.33% | reject |
| 2 | 95.32% | 97.66% | reject |
| 3 | 97.32% | 99.67% | reject |

所有 rejected attempts 都在 quiet gate 立即停止，没有启动 candidate、`perf stat` 或 NEMU，因此不存在需要丢弃的跨 CPU
性能样本。

## 2. Fresh NUMA1 survey

等待共享负载变化后重新对 NUMA1 全部 96 对 sibling 做五秒采样，最佳候选为：

| Primary | Sibling | Primary idle | Sibling idle | Min idle |
|---:|---:|---:|---:|---:|
| 127 | 319 | 99.00% | 99.80% | 99.00% |
| 125 | 317 | 100.00% | 98.80% | 98.80% |
| 159 | 351 | 98.80% | 99.40% | 98.80% |

CPU127/319 同属 socket 1、NUMA node 1 和同一物理 core，且是该快照唯一达到 pair-min `>=99%` 的候选。

## 3. Corrected lock

NO0507 除 CPU 编号外保持不变：

```text
taskset primary: CPU127
sibling monitor: CPU319
NUMA:             node1
ASLR:             setarch -R
order:            NO0357 / bypass / NO0357
```

下一步必须先让 CPU127/319 再通过独立三秒 `>=99%` quiet gate，之后才运行 candidate 100-cycle 五事件 preflight。
preflight 一旦启动，正式 A/B/A 全部锁定 CPU127，不再因即时 survey 排名变化而换核；每轮 gate 失败时只等待并重试。
