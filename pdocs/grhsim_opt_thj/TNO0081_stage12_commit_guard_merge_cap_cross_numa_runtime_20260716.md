# TNO0081 Stage 12 commit guard merge-cap cross-NUMA runtime

记录日期：2026-07-16

状态：完成 `8192/16384/32768` 三档 current-default NO0300 fixed-ASLR 跨 NUMA 50k。`8192` 与 `32768` 出现明显 socket 方向反转，`16384` 在两个 socket 都回退；默认保持 `4096`，停止全局 merge-cap 粗扫。

## 1. 方法

- workload：CoreMark，50k cycles，NEMU diff；
- control：Stage 10 same-poststats/current-code explicit-off emu，即当前仓库默认 NO0300；
- ASLR：`setarch x86_64 -R`；
- NUMA0：CPU/sibling `59/251`、membind 0；
- NUMA1：CPU/sibling `124/316`、membind 1；
- 每个 socket 串行执行 `control/8192/16384/32768/control`；
- 每个样本运行前对两个 SMT sibling 做 3 秒 `mpstat` gate，二者平均 idle 均须 `>=99%`；
- PMU：cycles、instructions、frontend empty、frontend empty `cmask>=6`、backend stalls。

两个 control 之间包含多个候选和被拒绝的 quiet window，不能假定五个样本严格等时间距。以下 delta 按每个 perf 区间的实际时间中点，在前后 control 之间线性插值；原始 PMU 文件仍完整保留，未通过的 gate window 不进入性能数据。

quiet gate 情况：

| socket | 样本顺序 | pass attempt | gate-to-run gap |
| --- | --- | --- | --- |
| NUMA0 | A1/8192/16384/32768/A2 | `1/3/2/14/34` | `6/6/7/8/7 ms` |
| NUMA1 | A1/8192/16384/32768/A2 | `12/2/3/1/1` | `6/8/7/7/7 ms` |

## 2. 原始 cycles 与 instructions

| socket | PMU | control A1 | 8192 | 16384 | 32768 | control A2 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| NUMA0 | cycles | `298,166,612,103` | `299,473,894,371` | `312,292,275,804` | `331,371,684,802` | `309,635,771,101` |
| NUMA0 | instructions | `172,881,447,243` | `172,755,368,014` | `172,867,523,848` | `173,094,914,996` | `172,881,449,091` |
| NUMA1 | cycles | `284,216,688,930` | `306,080,610,709` | `305,854,344,429` | `282,765,825,980` | `284,051,706,620` |
| NUMA1 | instructions | `172,881,439,444` | `172,755,359,289` | `172,867,515,087` | `173,094,894,742` | `172,881,439,813` |

NUMA0 control cycles 漂移 `+3.8466%`，frontend/cmask6 分别漂移 `+5.1454%/+6.4856%`，因此只用 A 均值会错误估计候选时刻。NUMA1 control 很稳定：cycles `-0.0580%`、frontend `+0.1364%`。两个 socket 的 control instructions 均近似 byte-stable，变化不超过 `1848` instructions。

## 3. 插值后的候选差异

| cap | socket | cycles | instructions | frontend empty | frontend `cmask>=6` | backend stalls |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 8192 | NUMA0 | `-0.2601%` | `-0.07293%` | `-1.3272%` | `-1.3125%` | `+4.6788%` |
| 8192 | NUMA1 | `+7.7085%` | `-0.07293%` | `+9.9754%` | `+12.7821%` | `+2.1022%` |
| 16384 | NUMA0 | `+3.2876%` | `-0.00805%` | `+3.8544%` | `+5.3772%` | `-14.0911%` |
| 16384 | NUMA1 | `+7.6457%` | `-0.00805%` | `+10.0752%` | `+12.9365%` | `+0.1952%` |
| 32768 | NUMA0 | `+8.5196%` | `+0.12348%` | `+10.6787%` | `+13.7094%` | `-6.7560%` |
| 32768 | NUMA1 | `-0.4663%` | `+0.12347%` | `-0.4922%` | `-0.6249%` | `-1.2571%` |

## 4. 解释

三档的 host instructions 在两个 socket 精确复现相同方向和幅度：

```text
8192   -0.07293%
16384  -0.00805%
32768  +0.12347%
```

这说明 PMU 样本本身稳定，也说明 commit BAE 单调下降没有转化为 host work 单调下降。`8192` 只减少 `597` 个 compute-to-commit pairs，却获得最大的 instruction 收益；`32768` 减少 `2243` pairs，instructions 反而增加。对应的静态检查已发现 active-update site 在 `16384 -> 32768` 增加 32 个，且 commit 合并会重排全局 value-slot 编号。

cycles 的主要变化与 frontend empty/cmask6 同向：

- `8192` 在 NUMA0 接近中性略好，但在控制稳定的 NUMA1 回退 `7.71%`；
- `16384` 两边 cycles/frontend 均回退，不存在可采用的一侧；
- `32768` 在 NUMA1 接近中性略好，却在 NUMA0 回退 `8.52%`；
- backend 小项在 NUMA0 自身也有 `-2.09%` control 漂移，不单独用来推翻 cycles/frontend 结论。

因此 `8192/32768` 都是此前多次出现的 code-layout socket 方向反转，`16384` 则是跨 socket 一致回退。不能用 instructions 小幅下降或跨 socket 平均值掩盖最坏 socket。

## 5. 功能与 PMU 完整性

十个正式样本的五项 PMU 均 100% scheduled，guest 终点全部为：

```text
guest cycles  50001
cycleCnt      49996
instrCnt      73580
PC            0x80001312
```

没有 diff mismatch、assert、fatal、abort 或异常退出。原始数据与原子 gate 脚本位于：

```text
build/logs/xs_perf/activity_stage12_commit_guard_merge_cap_20260716/
```

## 6. 决定

- `maxCommitOpsPerSupernode` 默认保持 `4096`；
- 保留高 cap 的有序 two-level coarsening 作为显式实验入口，但不在当前 XS 默认启用；
- 停止继续放大全局 cap，`16384 -> 32768` 的结构收益已接近饱和且 runtime 恶化；
- 下一阶段优先隔离 commit partition 对 value-slot/compute CPP 的全局重排，或只合并有明确动态收益的 event/cluster，再用同样的 current-default NO0300 fixed-ASLR 双 socket 50k 裁决。

## 增量更新 2026-07-17：绝对数值补录/勘误

原文只完整列出 raw cycles/instructions，另外三个 PMU 事件只列了插值后的相对变化。现从 10 份原始 `perf stat -x,` CSV 补录五项绝对计数；没有从百分比反推。每个 node 的样本顺序和数量均为 `control A1 / cap8192 / cap16384 / cap32768 / control A2`，共 5 个，双 node 共 10 个。

事件与单位为 `cycles:u`（cycles count）、`instructions:u`（retired-instruction count）、`de_no_dispatch_per_slot.no_ops_from_frontend:u`（frontend-empty slots count）、`cpu/de_no_dispatch_per_slot.no_ops_from_frontend,cmask=0x6/u`（frontend-empty `cmask>=6` cycles count）和 `de_no_dispatch_per_slot.backend_stalls:u`（backend-stall slots count）。

| node | 顺序 | sample | cycles | instructions | frontend empty | frontend `cmask>=6` | backend stalls |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| N0 | 1 | control A1 | `298,166,612,103` | `172,881,447,243` | `1,381,025,449,224` | `182,219,457,353` | `96,560,327,520` |
| N0 | 2 | cap8192 | `299,473,894,371` | `172,755,368,014` | `1,375,463,258,016` | `181,951,518,844` | `100,693,259,561` |
| N0 | 3 | cap16384 | `312,292,275,804` | `172,867,523,848` | `1,461,188,976,163` | `196,562,629,863` | `82,320,797,671` |
| N0 | 4 | cap32768 | `331,371,684,802` | `173,094,914,996` | `1,577,803,037,706` | `215,624,797,036` | `88,856,389,586` |
| N0 | 5 | control A2 | `309,635,771,101` | `172,881,449,091` | `1,452,084,661,672` | `194,037,400,676` | `94,541,001,513` |
| N1 | 1 | control A1 | `284,216,688,930` | `172,881,439,444` | `1,296,899,813,752` | `168,363,019,234` | `96,837,923,714` |
| N1 | 2 | cap8192 | `306,080,610,709` | `172,755,359,289` | `1,426,761,306,521` | `189,929,175,010` | `98,562,257,762` |
| N1 | 3 | cap16384 | `305,854,344,429` | `172,867,515,087` | `1,428,581,758,006` | `190,237,970,483` | `96,395,125,624` |
| N1 | 4 | cap32768 | `282,765,825,980` | `173,094,894,742` | `1,291,863,302,902` | `167,433,063,618` | `94,707,806,458` |
| N1 | 5 | control A2 | `284,051,706,620` | `172,881,439,813` | `1,298,668,160,010` | `168,523,697,032` | `95,629,962,733` |

原始路径前缀为 `build/logs/xs_perf/activity_stage12_commit_guard_merge_cap_20260716/`，文件依次为：

```text
n0_a1_perf.csv / n0_c8192_perf.csv / n0_c16384_perf.csv / n0_c32768_perf.csv / n0_a2_perf.csv
n1_a1_perf.csv / n1_c8192_perf.csv / n1_c16384_perf.csv / n1_c32768_perf.csv / n1_a2_perf.csv
```

10 份 CSV 的五个事件均为 `100.00%` scheduled。本补录只恢复 raw counters，不修改原文时间插值、旧协议局限或默认 cap 结论。

## 增量更新 2026-07-17：walltime headline 绝对值补录

最终性能 headline 采用 host walltime。以下是每个 node 按 `control A1 / cap8192 / cap16384 / cap32768 / control A2` 顺序从 `*_emu.log` 直接读取的 milliseconds：

| node | control A1 | cap8192 | cap16384 | cap32768 | control A2 |
| --- | ---: | ---: | ---: | ---: | ---: |
| N0 | `82,339` | `85,418` | `89,356` | `93,096` | `84,671` |
| N1 | `77,675` | `83,600` | `83,557` | `77,256` | `77,609` |

原始路径前缀为 `build/logs/xs_perf/activity_stage12_commit_guard_merge_cap_20260716/`，文件名与前一节 PMU CSV 的 `n{0,1}_{a1,c8192,c16384,c32768,a2}_emu.log` 一一对应。按通过 gate 的 `run_start_ns + wall/2` 做同一实际时间中心插值，walltime candidate deltas 为：N0 `+3.207308%/+7.411815%/+11.091921%`，N1 `+7.651030%/+7.620319%/-0.474710%`（cap8192/cap16384/cap32768）。因此 N0 cap8192 在 cycles 的 `-0.2601%` 近中性观测并非 wall 正收益，默认 `4096` 的决定更稳固。
