# NO0317 NO0286 / NO0300 frontend latency and ITLB gate

日期：2026-07-12

## 1. 口径

按 [NO0316](./NO0316_frontend_latency_itlb_pmu_plan_20260712.md) 对无 profile NO0286 / NO0300
执行 old / new / old：固定 CPU138、NUMA node 1，运行 CoreMark 两迭代、NEMU difftest 和 `-C 50000`。
五事件为 frontend empty slots、同事件 `cmask=6`、两级 ITLB miss 去向和 host cycles；三轮五项均为
`100.00%` 调度。

运行前全机 load 相对 384 个逻辑 CPU 很低。old1 前 CPU138/330 四秒平均空闲 `97.24%/99.75%`；
new 前发现单秒瞬态占用后等待并复查，三秒平均空闲 `98.33%/99.67%`；old2 前连续三秒二者均
`100%` 空闲。

## 2. 功能与稳定性

三轮均得到：

```text
Guest cycle spent: 50001
cycleCnt = 49996
instrCnt = 73580
terminal PC = 0x80001312
```

无 assertion、abort 或 difftest mismatch。Host time 分别为 `80,857 / 84,202 / 80,739 ms`；两次 old
spread 仅 `0.146%`。host cycles 的 old spread 为 `0.135%`，而 new 相对 old 均值增加 `4.219%`，
A/B/A 稳定性通过。

## 3. Frontend latency / bandwidth 分解

按本机 perf metric 定义：

```text
latency_slots = 6 * cmask6_cycles
bandwidth_slots = frontend_empty_slots - latency_slots
```

下表 old 为两次均值：

| Metric | NO0286 old mean | NO0300 new | Absolute delta | Per-cycle delta |
| --- | ---: | ---: | ---: | ---: |
| host cycles | 295,739,560,709.5 | 308,217,707,982 | +4.219% | - |
| frontend empty slots | 1,346,217,169,288 | 1,444,337,390,924 | +7.289% | +2.945% |
| frontend latency slots | 1,041,075,729,735 | 1,156,791,437,052 | +11.115% | +6.617% |
| frontend bandwidth slots | 305,141,439,553 | 287,545,953,872 | -5.766% | -9.581% |

NO0300 的 empty-slot density 回退全部来自整周期 frontend 无 op 的 latency 类空窗；剩余 bandwidth
空槽显著下降。这排除了“decoder 平均每周期少供给一些 op”作为当前主要方向，但还不能区分 branch
redirect、op-cache miss 或其他 frontend latency 来源。

## 4. ITLB 结果

| Metric | NO0286 old mean | NO0300 new | Absolute delta | Per-cycle delta |
| --- | ---: | ---: | ---: | ---: |
| L1 ITLB miss, L2 hit | 111,735,127 | 100,109,583 | -10.405% | -14.032% |
| L1 ITLB miss, L2 miss | 615,202,037.5 | 588,905,043 | -4.275% | -8.150% |
| combined | 726,937,164.5 | 689,014,626 | -5.217% | -9.054% |

两类 ITLB miss 的绝对值和 density 都下降，因此 NO0300 增加的 frontend latency 不是 instruction address
translation miss。结合 [NO0315](./NO0315_no0286_no0300_native_stall_pmu_gate_20260712.md) 的 I-cache
access/miss density 均下降，cache/TLB 容量或 miss 数量不再是下一步重点。

## 5. 结论与下一步

当前证据链为：dynamic work 下降、backend stall density 下降、I-cache 和 ITLB miss density 下降、frontend
bandwidth slots 下降，但 full-empty frontend latency slots/cycle 增加 `6.62%`。下一阶段应直接采集：

- retired taken branch / taken mispredict；
- decoder redirect 和 non-control-flow redirect；
- op-cache access / miss 或 decoder/op-cache dispatch source。

若 redirect density 恶化，则回到 ordered-write 引起的全局 compute batch 重排，定位新增的 hot-path taken jump
或错误布局；若 redirect 不恶化但 op-cache miss 恶化，则检查函数/基本块在 op cache 中的覆盖和边界。

## 6. 产物

```text
build/logs/xs_perf/no0316/frontend_itlb_old1_emu.log
build/logs/xs_perf/no0316/frontend_itlb_old1_perf.csv
build/logs/xs_perf/no0316/frontend_itlb_new_emu.log
build/logs/xs_perf/no0316/frontend_itlb_new_perf.csv
build/logs/xs_perf/no0316/frontend_itlb_old2_emu.log
build/logs/xs_perf/no0316/frontend_itlb_old2_perf.csv
```

