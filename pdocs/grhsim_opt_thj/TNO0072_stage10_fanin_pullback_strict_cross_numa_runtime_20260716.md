# TNO0072 Stage 10 fanin pullback strict cross-NUMA runtime

记录日期：2026-07-16

状态：Stage 10 strict 完成 current-default NO0300 fixed-ASLR 跨 NUMA quiet 50k A/B/A。NUMA0 cycles `-0.0903%`，NUMA1 `+0.7464%`；最坏 socket 是温和回退且 frontend 指标同步变差，因此不启用默认，保留显式 strict 入口。

## 1. 对象与方法

- A：Stage 7 fresh rollback emu，仓库当前默认 NO0300；
- B：Stage 10 strict emu，仅应用 84 个 final-fanin complete compute-node moves；
- workload：CoreMark，50k cycles，NEMU diff；
- ASLR：`setarch x86_64 -R`；
- NUMA0：CPU/sibling `32/224`、membind 0；
- NUMA1：CPU/sibling `154/346`、membind 1。

每个 socket 串行执行 A/B/A。每个样本运行前对两个 SMT sibling 做 3 秒 `mpstat` gate，平均 idle 均须 `>=99%`；gate 到 run 的 gap 必须 `<=5s`。正式样本实际 gap 为：

```text
NUMA0 A1/B/A2  8 / 8 / 7 ms
NUMA1 A1/B/A2  9 / 7 / 8 ms
```

NUMA0 A1 在第 2 次 gate 通过；NUMA1 A1/B/A2 分别在第 6/2/2 次通过。运行只在通过 gate 后开始，因此前面的 rejected windows 不进入数据。

## 2. NUMA0 结果

| PMU | A1 | B strict | A2 | B vs A mean |
| --- | ---: | ---: | ---: | ---: |
| cycles | `281,987,341,305` | `281,102,519,848` | `280,725,669,069` | `-0.090272%` |
| instructions | `172,881,261,859` | `172,835,001,573` | `172,881,261,333` | `-0.026758%` |
| frontend empty | `1,287,374,891,669` | `1,282,214,402,466` | `1,279,667,984,223` | `-0.101832%` |
| frontend empty `cmask>=6` | `166,654,941,410` | `165,351,481,923` | `165,413,506,163` | `-0.411206%` |
| backend stalls | `94,176,561,389` | `93,751,306,292` | `93,890,115,892` | `-0.299928%` |

控制 cycles spread 为 `-0.447422%`，低于 1% 有效性门槛。所有五项事件均为 100% scheduled。该 socket 上 strict 是中性微增益，不到 1%。

## 3. NUMA1 结果

| PMU | A1 | B strict | A2 | B vs A mean |
| --- | ---: | ---: | ---: | ---: |
| cycles | `305,943,988,712` | `308,322,167,165` | `306,131,856,538` | `+0.746393%` |
| instructions | `172,881,267,846` | `172,835,009,466` | `172,881,267,757` | `-0.026757%` |
| frontend empty | `1,430,464,008,118` | `1,445,161,963,719` | `1,432,824,632,461` | `+0.944204%` |
| frontend empty `cmask>=6` | `190,573,254,772` | `192,549,348,650` | `190,929,250,759` | `+0.942639%` |
| backend stalls | `94,249,213,832` | `93,871,530,456` | `93,313,739,654` | `+0.096025%` |

控制 cycles spread 为 `+0.061406%`，两侧非常稳定；五项事件也全部 100% scheduled。instructions 的静态 work 减少在两个 socket 上一致，但 NUMA1 frontend 供给约退化 `0.94%`，抵消并反转该收益。

## 4. 功能与样本有效性

六个样本均得到相同 guest 终点：

```text
Guest cycles  50001
cycleCnt      49996
instrCnt      73580
PC            0x80001312
```

没有 diff mismatch、assert、fatal 或异常退出。所有 perf 文件包含五个目标事件且各自 scheduled 100%。因此两组 A/B/A 都是有效正式样本，不以 wall time 或 rejected gate window 代替 PMU 结论。

## 5. 默认决定

strict 的最坏 socket cycles 为 `+0.7464%`，未达到明显退化的 1% 线，但也没有跨 socket 的正向收益；NUMA1 frontend 两项接近 `+1%`，说明这 84 个局部 move 仍会通过代码布局改变前端行为。结论：

- `finalFaninPullbackPolicy` 默认继续 `off`；
- 保留 `strict` 作为可复现实验入口及后续组合候选；
- 不继续放宽同一 common-source/min-gain 漏斗来追求更大 move 集合；
- 下一阶段从生成 C++/object 与 perf 的变化归因入手，寻找能改善 batch/layout 或减少更大 activation work、而非只减少 254 个静态 BAE 的 schedule 方案。

原始数据：

```text
build/logs/xs_perf/activity_stage10_fanin_strict_20260716/

## 增量更新 2026-07-17：walltime headline 绝对值补录

当前最终性能 headline 改为 host walltime。原文 PMU 表已有 cycles/instructions 等绝对值，但未列 host wall 原值；以下直接抄录 `Host time spent`，单位为 milliseconds，顺序为各 node 的 `A1 / B strict / A2`：

| node | A1 | B strict | A2 | 原始 emu 文件前缀 |
| --- | ---: | ---: | ---: | --- |
| NUMA0 | `77,098` | `76,862` | `76,761` | `build/logs/xs_perf/activity_stage10_fanin_strict_20260716/{n0_a1,n0_b,n0_a2}_emu.log` |
| NUMA1 | `83,545` | `84,170` | `83,579` | `build/logs/xs_perf/activity_stage10_fanin_strict_20260716/{n1_a1,n1_b,n1_a2}_emu.log` |

walltime 相对两侧 control 均值分别为 NUMA0 `-0.087743%`、NUMA1 `+0.727603%`，与原 cycles 方向一致；本补录不改变 strict 默认关闭的结论。
```
