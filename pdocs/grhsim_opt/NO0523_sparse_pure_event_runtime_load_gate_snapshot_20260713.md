# NO0523 Sparse pure-event runtime load-gate snapshot

日期：2026-07-13

## 1. Fresh survey

按 [NO0522](./NO0522_simtop_sparse_pure_event_fixed_aslr_runtime_plan_20260713.md) 对全部 CPU 做五秒 `mpstat`
采样，并分别按两个 NUMA node 的 SMT pair-min idle 排序：

```text
NUMA1 best: CPU101/293  idle=97.60/98.19%  pair-min=97.60%
NUMA0 best: CPU26/218   idle=93.15/93.80%  pair-min=93.15%
required:                                        >=99.00%
```

两个 socket 都未达到 survey gate，因此没有进入独立三秒 quiet gate，也没有启动 PMU preflight、baseline 或 hybrid emu。
NO0522 当前正式 PMU 样本数仍为 0。

## 2. Resource evidence

survey 后 load average 升到 `252.91/299.36/245.11`。进程快照包含一个约 `8652% CPU` 的 `llvm-bolt`、两组约
`800% CPU` 的 `emu-verilator`、一组约 `773% CPU` 的 `emu`，以及多组持续占核的 `emu-gsim`。这与 50k 功能运行中
10k->20k host 时间突增的现象一致。

## 3. Decision

不放宽 sibling idle `>=99%` 与 baseline spread `<=1%` 门限，不生成失真的 A/B/A，也不把 NO0521 raw 179.9s 当作
hybrid 性能。runtime 等共享负载恢复后重新 fresh survey；等待期间转去做不依赖 wall time 的 source/object/结构审计。

下一条候选方向是审计 event-pure supernode 的 active-id packing：NO0484 中还有 246 个 event/non-event mixed words；若能仅靠
重排 active IDs 将同 batch、同 exact event 的节点聚成 pure words，就可能扩大现有 whole-word bypass 覆盖，同时避免
NO0486 mixed-word mask filter 的静态回退。先做只读上界与约束审计，不直接修改 schedule/emitter。
