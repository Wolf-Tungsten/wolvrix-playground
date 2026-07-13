# NO0525 Sparse pure-event high-load A/B/A

日期：2026-07-13

## 1. Scope

承接 [NO0522](./NO0522_simtop_sparse_pure_event_fixed_aslr_runtime_plan_20260713.md) 与
[NO0523](./NO0523_sparse_pure_event_runtime_load_gate_snapshot_20260713.md)。服务器仍处于高负载，未满足正式
`sibling idle >= 99%` gate；按本轮明确允许的“先在 CPU28 做初步 A/B/A”口径，执行一次
`baseline -> hybrid -> baseline`。本篇结果只用于判断方向和噪声量级，不替代 NO0522 的正式 runtime gate。

运行固定为：

```text
logical CPU             28
SMT sibling             220
NUMA memory node        0
ASLR                     setarch $(uname -m) -R
workload                 XiangShan CoreMark, seed=0, -C 50000
runtime profile          unset
progress instrumentation EMU_PROGRESS_EVERY_CYCLES=0
PMU schedule             five events, all samples 100.00%
```

候选是 NO0516 fresh hybrid emu `eed8e615...`，baseline 是 NO0357 direct-state-read emu
`cad7eca0...`。每个样本前记录 CPU28/220 的 3 秒 `mpstat`，原始文件位于
`build/logs/xs_perf/no0525/`。

## 2. Discarded first attempt

最初的 baseline1 会话在约 40k cycle 后意外消失：emu log 只有 10k/20k/30k/40k 进度，
`baseline1_perf.csv` 为 0 字节，且没有残留 emu/perf 进程。该不完整样本被明确作废并覆盖重跑，未进入下表。

## 3. Complete A/B/A samples

五项事件依次为 host `cycles`、`instructions`、frontend empty slots、frontend `cmask=6` 和 backend stalls：

| Sample | Host cycles | Instructions | Frontend empty | Frontend cmask6 | Backend stalls | Host ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline1 | 903,696,969,842 | 166,888,353,356 | 5,035,304,638,282 | 791,713,948,013 | 92,252,138,220 | 329,632 |
| hybrid | 965,083,345,014 | 164,519,086,973 | 5,404,400,714,638 | 853,810,071,211 | 100,166,118,293 | 351,791 |
| baseline2 | 684,398,522,260 | 166,888,269,841 | 3,709,371,404,880 | 570,742,343,674 | 98,503,829,981 | 244,335 |

三次运行的五项 PMU `time_running/time_enabled` 比例均为 `100.00%`。三次功能终点也完全一致：

```text
exit / guest cycles / cycleCnt / instrCnt  0 / 50,001 / 49,996 / 73,580
terminal PC                                0x80001312
difftest state pointer                     0x55555aea2d30
```

`input_fullpass_blocked`、mismatch、assertion、abort、segfault、fatal、error 与 profile 泄漏扫描为 0。

## 4. Noise diagnosis

两次相同 baseline 的 host-cycle 均值为 `794,047,746,051`，但 A/A 极差已达到均值的 `27.617791%`。
因此 hybrid 相对 baseline 均值的 `+21.539712%`、相对 baseline1 的 `+6.792805%` 和相对 baseline2 的
`+41.011898%` 都不能解释为代码回退。

这一判断也得到 stall event 的支持：baseline A/A 的 frontend empty、frontend cmask6 和 backend stall 极差分别为
baseline 均值的 `30.325497%`、`32.437239%` 和 `6.554649%`。三个样本启动前的 CPU28/220 平均 idle 分别为
`95.65/92.64%`、`95.65/95.65%`、`98.00/94.98%`；短 survey 没有捕获运行中持续数分钟的共享资源争用。

动态 host instructions 则不同：两次 baseline 只相差 `0.000050%`，hybrid 相对其均值减少 `1.419647%`。
这个结果与 NO0518 的 O3 静态指令减少方向一致，说明 sparse pure-event code shape 确实减少了执行指令；但在本轮
高负载下，不能把它换算成 host cycles 或仿真速度收益。

## 5. Decision

- 保留本轮为高负载初测与噪声证据，不接受任何 cycle 侧正/负性能结论；
- NO0522 的正式 fixed-ASLR A/B/A 仍保持零有效样本，等待 quiet gate 后重跑；
- hybrid 的功能 gate 继续通过，且动态 instructions 的 `-1.42%` 可作为后续静态分析的辅助证据；
- 当前先转回不依赖共享机器 wall time 的 final-DAG legal packing audit，避免继续消耗失真的 50k 样本。

