# NO0433 Full active-word exact-entry PMU preflight gate

日期：2026-07-13

## 1. Quiet gate

按 [NO0432](./NO0432_full_active_word_exact_entry_runtime_plan_20260712.md) 继续锁定 CPU131/323。第一次三秒检查为：

```text
CPU131 idle=96.99%
CPU323 idle=95.00%
```

该次低于 `>=99%` 门槛，在启动 perf 前拒绝，没有产生 PMU 样本。第二次检查为：

```text
CPU131 idle=99.00%
CPU323 idle=100.00%
```

两核均通过，允许在 CPU131 上执行 exact candidate 100-cycle preflight。

## 2. Fixed-ASLR and function

preflight 使用 CPU131、NUMA1、`setarch -R`、CoreMark/NEMU difftest `-C 100`，执行 exit 0：

```text
difftest state=0x55555aea2d30
Guest cycles=101
model cycles=100
cycleCnt=96
instrCnt=0
terminal PC=0x0
```

state 地址与 exact baseline 布局一致；相比 NO0426 native candidate 的 `0x55555adfed30`，说明 exact-entry
padding 已将候选恢复到 baseline 的固定装载布局。日志没有 mismatch、assert/abort、segmentation fault、fatal/error
或 `input_fullpass_blocked`。

## 3. PMU scheduling

五事件同时 100% scheduled：

| event | count | scheduled |
| --- | ---: | ---: |
| cycles | 526,182,718 | 100.00% |
| instructions | 236,919,219 | 100.00% |
| frontend empty slots | 2,478,021,820 | 100.00% |
| frontend cmask6 cycles | 326,059,068 | 100.00% |
| backend stall slots | 160,790,293 | 100.00% |

100-cycle 计数由模型初始化主导，不用于性能结论。本轮只验证 event availability、无 multiplex、CPU/NUMA 绑定、
fixed-ASLR 地址和功能链路。

## 4. Artifacts and next gate

```text
build/logs/xs_perf/no0432/preflight_quiet_gate_attempt_1.log
build/logs/xs_perf/no0432/preflight_quiet_gate_attempt_2.log
build/logs/xs_perf/no0432/exact_candidate_preflight_emu.log
build/logs/xs_perf/no0432/exact_candidate_preflight_perf.csv
```

下一步按 exact baseline/candidate/baseline 执行 50k A/B/A；每轮前仍独立要求 CPU131/323 三秒平均 idle
均 `>=99%`。
