# NO0426 Full active-word PMU preflight gate

日期：2026-07-12

## 1. Quiet gate

按 [NO0425](./NO0425_full_active_word_runtime_cpu_reselection_20260712.md) 锁定 CPU131/323 后，首次三秒正式
quiet gate 为：

```text
CPU131 idle=99.00%
CPU323 idle=99.00%
```

两者均满足 NO0424 预声明的 `>=99%`，允许启动 candidate 100-cycle PMU preflight。此前 CPU191/383 的四次
rejected attempt 没有产生 PMU 样本。

## 2. Fixed-ASLR and function

preflight 使用 CPU131、NUMA1、`setarch -R`、CoreMark/NEMU difftest `-C 100`，执行 exit 0：

```text
difftest state=0x55555adfed30
Guest cycles=101
cycleCnt=96
instrCnt=0
terminal PC=0x0
```

`0x5555...` state 地址证明 PIE fixed-ASLR 链路已传递到 candidate。日志没有 mismatch、assert/abort、
segmentation fault、fatal/error 或 `input_fullpass_blocked`。

## 3. PMU scheduling

五事件同时 100% scheduled：

| event | count | scheduled |
| --- | ---: | ---: |
| cycles | 570,548,383 | 100.00% |
| instructions | 236,919,249 | 100.00% |
| frontend empty slots | 2,745,087,994 | 100.00% |
| frontend cmask6 cycles | 370,820,577 | 100.00% |
| backend stall slots | 160,500,585 | 100.00% |

100-cycle 计数主要是模型初始化，不作性能结论。本节只验证 event availability、无 multiplex 和绑定链路。

## 4. Artifacts and next gate

```text
build/logs/xs_perf/no0425/preflight_quiet_gate_attempt_1.log
build/logs/xs_perf/no0425/candidate_preflight_emu.log
build/logs/xs_perf/no0425/candidate_preflight_perf.csv
```

下一步在 CPU131/NUMA1/fixed-ASLR 下按 baseline/candidate/baseline 执行 50k，每轮前仍独立通过 quiet gate。
