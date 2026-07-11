# NO0333 Batch function page-alignment runtime gate

日期：2026-07-12

## 1. 口径与稳定性

承接 [NO0332](./NO0332_batch_function_page_alignment_functional_gate_20260712.md)，固定 CPU138、NUMA
node 1，执行 aligned NO0286 / aligned NO0300 / aligned NO0286 的 CoreMark 50k。采集 host cycles、
instructions、frontend empty slots 和 cmask6 full-empty cycles，三轮四项均为 `100.00%` 调度。

运行前全机 load 约 `3~7/384`。每轮前都检查 CPU138 与 SMT sibling 330；目标 CPU 基本连续空闲，
sibling 只有单秒约 4%~6% 的零星系统活动，没有持续负载。两次 old Host time spread 为 `0.398%`，
cycles spread 为 `0.387%`，A/B/A 稳定性通过，因此未插入额外未对齐 baseline。

三轮功能终点均为 guest cycles `50001`、`cycleCnt = 49996`、`instrCnt = 73580` 和 terminal PC
`0x80001312`，无 mismatch、assertion 或 abort。

## 2. 原始计数

| Run | Host time (ms) | Host cycles | Instructions | Frontend empty slots | cmask6 cycles |
| --- | ---: | ---: | ---: | ---: | ---: |
| aligned old1 | 89,523 | 327,744,565,034 | 188,838,978,815 | 1,534,986,346,803 | 205,067,850,300 |
| aligned new | 84,029 | 307,690,075,823 | 172,879,736,157 | 1,441,309,238,237 | 192,374,026,484 |
| aligned old2 | 89,167 | 326,477,265,021 | 188,838,735,063 | 1,527,533,918,961 | 203,843,469,717 |

以两次 old 均值计算：

| Metric | Aligned old mean | Aligned new | Absolute delta | Per-cycle delta |
| --- | ---: | ---: | ---: | ---: |
| Host time | 89,345 ms | 84,029 ms | -5.950% | - |
| Host cycles | 327,110,915,027.5 | 307,690,075,823 | -5.937% | - |
| Instructions | 188,838,856,939 | 172,879,736,157 | -8.451% | -2.673% |
| Frontend empty slots | 1,531,260,132,882 | 1,441,309,238,237 | -5.874% | +0.067% |
| cmask6 cycles | 204,455,660,008.5 | 192,374,026,484 | -5.909% | +0.030% |

按 NO0317 的定义继续拆分：

| Metric | Aligned old mean | Aligned new | Absolute delta | Per-cycle delta |
| --- | ---: | ---: | ---: | ---: |
| Latency slots (`6 * cmask6`) | 1,226,733,960,051 | 1,154,244,158,904 | -5.909% | +0.030% |
| Bandwidth slots | 304,526,172,831 | 287,065,079,333 | -5.734% | +0.216% |

页对齐后 frontend empty 与 full-empty density 都约持平，NO0300 减少的 8.45% instructions 转化为
5.94% cycles 收益，不再出现“工作减少但 frontend latency/cycle 上升”的反转。

## 3. 与未对齐门禁的关系

同一 CPU、同一负载的 [NO0317](./NO0317_no0286_no0300_frontend_latency_itlb_gate_20260712.md) 给出：

| Relative new vs old | Unaligned NO0317 | Aligned NO0333 |
| --- | ---: | ---: |
| Host cycles | +4.219% | -5.937% |
| Frontend empty slots/cycle | +2.945% | +0.067% |
| cmask6 cycles/cycle | +6.617% | +0.030% |
| Bandwidth slots/cycle | -9.581% | +0.216% |

cycles 相对关系摆动 `10.16` percentage points，且摆动准确伴随 full-empty frontend density 消失。
这直接证明 native address layout 足以覆盖 NO0300 的约 4% 回退。

但 4 KiB alignment 不是中性控制。与 NO0317 未对齐绝对值交叉比较：

| Alignment effect | NO0286 old | NO0300 new |
| --- | ---: | ---: |
| Host cycles | +10.608% | -0.171% |
| Frontend empty slots | +13.745% | -0.210% |
| cmask6 cycles | +17.833% | -0.220% |

使用 NO0328 的另一组未对齐 cycles，old/new alignment effect 仍为 `+11.154%/-0.867%`，方向不变。
因此反转主要来自页对齐破坏了 NO0286 的有利布局，而不是显著改善 NO0300。把所有 batch 放在相同 page
offset 还可能引入 op-cache/branch-predictor alias；不能把本 probe 直接保留为优化，也不能据此声称唯一根因
就是低 12-bit 累计漂移。

## 4. 结论与下一步

本轮建立了比 cache/TLB miss-count 更直接的因果关系：在 batch body、symbol size、动态工作和 guest 行为
全部不变时，仅改变函数地址即可让 old/new 相对性能摆动约 10 percentage points，并同步消除 NO0300 的
full-empty frontend density 回退。当前性能问题属于 generated native code layout 对超大 batch 的高度敏感，
而不是 ordered affine loop 动态指令本身更慢。

下一步不继续使用全同 offset 的 4 KiB alignment。应对照 GSim 更细的 `subStep` 粒度，优先做低扰动布局
实验：保持 16-byte 默认 alignment 和 batch body 不变，只重排 archive 中 sched objects，观察无 padding 的
地址顺序是否能稳定改变 cycles/cmask6；若成立，再设计 deterministic hotness/order，而不是依赖偶然链接顺序。

## 5. 产物

```text
build/logs/xs_perf/no0329/align4k_old1_emu.log
build/logs/xs_perf/no0329/align4k_old1_perf.csv
build/logs/xs_perf/no0329/align4k_new_emu.log
build/logs/xs_perf/no0329/align4k_new_perf.csv
build/logs/xs_perf/no0329/align4k_old2_emu.log
build/logs/xs_perf/no0329/align4k_old2_perf.csv
```
