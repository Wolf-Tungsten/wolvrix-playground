# NO0509 Pure-event bypass runtime load-gate snapshot

日期：2026-07-13

## 1. Reselected CPU gate results

按 [NO0508](./NO0508_pure_event_bypass_runtime_cpu_reselection_20260713.md) 锁定 CPU127/319 后，在 candidate
100-cycle PMU preflight 前执行三次独立三秒 quiet gate：

| Attempt | CPU127 idle | CPU319 idle | Decision |
|---:|---:|---:|---|
| 1 | 98.33% | 93.36% | reject |
| 2 | 96.66% | 91.69% | reject |
| 3 | 97.67% | 96.99% | reject |

三次都在 gate 后立即停止，没有启动 `perf stat`、candidate 或 NEMU。NO0507 至今没有任何正式 PMU 样本，不能从本阶段
形成性能比例。

## 2. Host-load evidence

期间全机 load average 约在 `133~154/384`，`vmstat` 的全机 idle 一度仅 `63%~66%`。进程快照显示多组共享 CI
Java elaboration、长跑 `emu`/`emu-gsim` 与 checkpoint workload 同时占用机器，工作线程会在 CPU 间迁移。第一次
NUMA1 survey 最佳 pair-min 仅 `94.79%`，第二次为 `96.99%`；短暂出现的 CPU127/319 `99.00/99.80%` 也没有在后续
独立 gate 中保持。同期 node0 从相同全核采样得到的最佳 pair-min 约 `98.00%`，换 socket 不能解决问题。

## 3. Decision

保持 [NO0507](./NO0507_simtop_pure_event_word_bypass_fixed_aslr_runtime_plan_20260713.md) 的 `>=99%` pre-run gate 和
现场 baseline/candidate/baseline，不静默放宽门限，也不把 NO0506 的高负载 raw time 当性能数据。PMU 阶段等待共享负载
恢复后继续，CPU 可在任何 preflight 样本产生前重新 survey；一旦 preflight 启动则必须锁定。

等待窗口内转去分析 NO0503 已确认的 batch 27 giant-function codegen cliff。该诊断只编译 generated-copy objects，不使用
wall time，可测试“隐藏 outer predicate 与内部 event equality 的编译期相关性”能否保留动态 miss bypass 同时避免
`+11.5 KiB/+1,789 instructions` 的整函数跳变。
