# NO0384 Exact-entry runtime CPU reselection

日期：2026-07-12

## 1. CPU147/339 未通过正式 preflight gate

按 [NO0383](./NO0383_exact_entry_runtime_cpu_selection_correction_20260712.md) 选择 CPU147/339 后，在 direct 100-cycle
PMU preflight 前又执行两次独立 quiet gate：

| Attempt | CPU147 idle | CPU339 idle | Decision |
| --- | ---: | ---: | --- |
| 1 | 100.00% | 98.33% | reject |
| 2 | 93.69% | 97.67% | reject |

两次命令都在 quiet gate 立即停止，尚未启动 `perf stat` 或 emu，因此不存在跨 CPU 的 PMU 样本需要丢弃。

## 2. 即时 NUMA1 resurvey

共享任务会在可运行 CPU 间迁移，第一次 survey 的最佳核不能长期代表当前状态。因此将 survey 本身固定到 CPU0，等待
后重新对 NUMA1 的 96 对物理核做五秒采样。当前结果：

| Primary | Sibling | Primary idle | Sibling idle | Min |
| ---: | ---: | ---: | ---: | ---: |
| 188 | 380 | 99.80% | 99.40% | 99.40% |
| 128 | 320 | 99.20% | 99.20% | 99.20% |
| 134 | 326 | 99.20% | 99.20% | 99.20% |
| 147 | 339 | 99.40% | 98.60% | 98.60% |

共有 15 对 sibling 的最低 idle `>=99%`。CPU188/380 是即时 survey 中最安静的一对，且与此前候选同属 socket 1、
NUMA node 1 和相同微架构。

## 3. 最终选择与锁定规则

正式 preflight 和整组 A/B/A 改用：

```text
taskset: CPU188
sibling: CPU380
NUMA:    node1
ASLR:    setarch -R
```

这是任何 perf run 之前的最后一次 CPU 选择。CPU188/380 必须先通过独立三秒 `>=99%` quiet gate；一旦 100-cycle
preflight 启动，后续 exact baseline/direct/exact baseline 全部锁定 CPU188，不因中途 survey 排名变化而换核。每轮
前 gate 不通过时只等待并重试同一核。

相对性能仍由同核 A/B/A 和 baseline spread 控制。与 NO0383 相同，本轮不跨核复用历史 CPU138 GSim 的绝对 cycles；
若需要 absolute GSim gap，另做 CPU188 上的现场 GSim 夹测。

下一步重新执行 CPU188/380 quiet gate，通过后才运行 direct 100-cycle 五事件 preflight。
