# NO0385 Exact-entry PMU preflight gate

日期：2026-07-12

## 1. CPU188/380 quiet gate

按 [NO0384](./NO0384_exact_entry_runtime_cpu_reselection_20260712.md) 锁定 CPU188/380 后，第一次三秒 gate 为
`100.00%/98.33%`，在 perf 前拒绝并保留。等待后第二次三秒采样为：

```text
CPU188 idle: 100.00%
CPU380 idle: 100.00%
load average: 4.09 / 5.39 / 5.89 on 384 CPUs
```

第二次通过 `>=99%` 门限后才启动 direct 100-cycle preflight。

## 2. PMU 接线结果

运行固定为 CPU188、NUMA1 和 `setarch -R`，事件与 NO0382 一致：cycles、instructions、frontend empty、
frontend cmask6 和 backend stalls。五项均为 `100.00%` 调度：

| Event | Count | Schedule |
| --- | ---: | ---: |
| cycles | 561,139,744 | 100.00% |
| instructions | 238,628,393 | 100.00% |
| frontend empty | 2,698,462,515 | 100.00% |
| frontend cmask6 | 363,651,284 | 100.00% |
| backend stalls | 154,447,676 | 100.00% |

100-cycle 计数只验证 PMU 接线和调度，不形成性能结论。

## 3. 功能与 fixed-ASLR 门禁

direct preflight 以 exit 0 到达：

```text
Guest/model cycles: 101 / 100
cycleCnt:           96
instrCnt:           0
terminal PC:        0x0
difftest state:     0x55555b079d30
```

负向扫描没有 mismatch、assertion、abort、fatal、segmentation fault 或 `input_fullpass_blocked`。fixed-ASLR、CPU、
NUMA 和五事件链路均可用，允许在同一 CPU188 上进入 exact-entry baseline/direct/baseline 50k A/B/A。

产物：

```text
build/logs/xs_perf/no0385/quiet_gate_attempt_{1,2}.log
build/logs/xs_perf/no0385/direct_100cycle_emu.log
build/logs/xs_perf/no0385/direct_100cycle_perf.csv
```
