# NO0328 NO0286 / NO0300 L2 instruction PMU gate

日期：2026-07-12

## 1. 口径与有效性

按 [NO0327](./NO0327_ibs_fetch_probe_and_l2_plan_20260712.md) 对无 profile NO0286 / NO0300 执行
fixed CPU138、NUMA node 1 的 old / new / old CoreMark 50k。五事件为 host cycles、L1I miss、L2 instruction
access/hit/fill-miss。

三轮均得到 `Guest cycle spent = 50001`、`cycleCnt = 49996`、`instrCnt = 73580` 和 terminal PC
`0x80001312`；无 assertion、abort 或 difftest mismatch，五项均为 `100.00%` 调度。每轮均满足：

```text
L2 instruction access = L2 hit + L2 fill miss
```

闭合误差精确为 0。

Host time 为 `80,479 / 84,794 / 80,311 ms`，old spread `0.209%`。host cycles old spread `0.217%`，
NO0300 相对 old 均值回退 `5.469%`。本轮回退略高于此前约 4%，但 A/B/A baseline 稳定，且 counter 方向
不依赖 timing 的具体幅度。

运行前全机 load 为约 `4~10/384`；各轮 CPU138/330 均接近全空闲，old2 前分别为连续 `100%` 与平均
`99.67%` 空闲。

## 2. 原生计数

下表 old 为两次均值，per-work 使用 NO0312 的 `work_total`：

| Metric | NO0286 old mean | NO0300 new | Absolute | Per cycle | Per work |
| --- | ---: | ---: | ---: | ---: | ---: |
| host cycles | 294,285,496,406 | 310,381,255,462 | +5.469% | - | +10.212% |
| L1 instruction-cache miss | 38,160,786,024 | 37,002,238,987 | -3.036% | -8.064% | +1.324% |
| L2 instruction access | 29,844,396,875.5 | 28,312,273,505 | -5.134% | -10.053% | -0.868% |
| L2 instruction hit | 4,669,413,592 | 4,623,028,139 | -0.993% | -6.128% | +3.458% |
| L2 instruction fill miss | 25,174,983,283.5 | 23,689,245,366 | -5.902% | -10.781% | -1.671% |

L2 fill-miss rate 从 `84.3541%` 降到 `83.6713%`，相对改善 `0.809%`。

## 3. 结论

NO0300 的 L2 instruction fill misses 在绝对值、per cycle 和 per work 三个口径都下降，miss rate 也改善。
L2 access/work 同样下降。虽然较低代价的 L2 hits/work 增加 `3.46%`，总 access/work 仍下降，且数量占比从
miss 转向 hit，不能解释 NO0323 的 compute full-empty samples/work `+21.17%`。

至此 instruction fetch 的 miss-count 链条均未恶化：

- L1I access/miss：NO0315 中 per cycle 均下降；
- ITLB L1/L2 miss：NO0317 中 per cycle 均下降；
- op-cache miss rate/dispatch share：NO0321 中改善；
- L2 instruction access/fill miss：本轮 per work 与 per cycle 均下降。

因此不再正式运行 l3miss-only IBS profile；L2 fill miss 已下降，继续定位 L3 miss 函数不会解释总回退。

## 4. 下一步

进行只改 native code layout、不重跑 graph transform 的 probe，优先测试 generated batch function alignment。
该 probe 应直接复用 NO0300 generated C++，保持 graph/supernode/work/功能不变，先比较 text size、函数起始地址，
再做 10k/50k 功能与 fixed-CPU runtime/cmask6 gate。若对齐不能改善，则继续研究 batch section/order 或编译器
基本块布局，而不是回到 cache/TLB miss 数量。

## 5. 产物

```text
build/logs/xs_perf/no0328/l2_icache_old1_emu.log
build/logs/xs_perf/no0328/l2_icache_old1_perf.csv
build/logs/xs_perf/no0328/l2_icache_new_emu.log
build/logs/xs_perf/no0328/l2_icache_new_perf.csv
build/logs/xs_perf/no0328/l2_icache_old2_emu.log
build/logs/xs_perf/no0328/l2_icache_old2_perf.csv
```

