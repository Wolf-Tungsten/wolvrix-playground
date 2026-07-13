# NO0364 SimTop direct state-read PMU preflight gate

日期：2026-07-12

## 1. 资源与运行口径

按 [NO0362](./NO0362_simtop_direct_state_read_fixed_aslr_runtime_plan_20260712.md)，正式 A/B/A 前检查主机与目标核：

```text
load average             6.60 / 6.81 / 8.67 on 384 CPUs
available memory         936 GiB
CPU138 3-second idle     100.00%
CPU330 3-second idle      99.67%
other emu/C++ compile    none
```

随后对 direct emu 运行 fixed-ASLR、CPU138、NUMA1 的 CoreMark/NEMU difftest `-C 100`，并同时采集计划中的
五项 PMU。所有命令均先执行 `source env.sh`。

## 2. PMU 接线

按 [NO0363](./NO0363_perf_csv_cmask_schedule_parser_correction_20260712.md) 修正后的 CSV verifier，五项事件均
无 multiplex：

| Event | Count | Scheduled |
| --- | ---: | ---: |
| cycles | 553,383,059 | 100.00% |
| instructions | 239,306,275 | 100.00% |
| frontend empty slots | 2,648,245,198 | 100.00% |
| frontend cmask6 cycles | 355,018,832 | 100.00% |
| backend stall slots | 157,244,749 | 100.00% |

100-cycle 计数包含模型初始化和很少的模拟工作，不用于性能比较；本节只验收 event availability 和 simultaneous
scheduling。

## 3. 功能与 fixed-ASLR

preflight 以 exit 0 完成：

```text
Guest cycles        101
cycleCnt             96
instrCnt               0
terminal PC          0x0
difftest state       0x55555aea1d30
```

日志未出现 mismatch、assertion、abort、fatal/error 或 `input_fullpass_blocked`。固定 `0x5555...` state address
表明 `setarch -R` 已传递到 direct PIE；正式运行仍会检查两次 baseline 地址一致。

## 4. 产物与下一步

```text
build/logs/xs_perf/no0362/direct_event_preflight_emu.log
build/logs/xs_perf/no0362/direct_event_preflight_perf.csv
```

PMU 与功能 preflight 通过。下一步按预声明顺序串行执行 NO0300 / direct / NO0300 50k；每轮前复核目标核空闲，
最终以两次 baseline host cycles spread `<=1%` 决定是否接受性能比值。
