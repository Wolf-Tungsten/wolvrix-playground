# NO0321 NO0286 / NO0300 op-cache and dispatch-source gate

日期：2026-07-12

## 1. 口径与有效性

按 [NO0320](./NO0320_op_cache_dispatch_source_pmu_plan_20260712.md) 对无 profile NO0286 / NO0300
执行 fixed CPU138、NUMA node 1 的 old / new / old CoreMark 50k。三轮功能终点均为 `50001` guest cycles、
`cycleCnt = 49996`、`instrCnt = 73580` 和 terminal PC `0x80001312`；无 assertion、abort 或 difftest
mismatch，五事件均为 `100.00%` 调度。

Host time 为 `81,049 / 84,577 / 80,681 ms`；old spread 为 `0.455%`。host cycles old spread 为
`0.462%`，NO0300 相对 old 均值回退 `4.487%`。该 baseline 漂移高于前两组但仍约为候选差异的十分之一，
且方向与既有 A/B/A 一致，门禁有效。

运行前全机 load 相对 384 个逻辑 CPU 很低；捕获到 CPU138/330 单秒 `3%/5%` 瞬态后等待复查，正式
old2 前 CPU138 三秒全空闲、CPU330 平均空闲 `99.67%`。

## 2. 原生计数

下表 old 为两次均值；per-work 使用 [NO0312](./NO0312_no0286_no0300_dynamic_work_gate_20260712.md)
的 `work_total`：

| Metric | NO0286 old mean | NO0300 new | Absolute | Per cycle | Per work |
| --- | ---: | ---: | ---: | ---: | ---: |
| host cycles | 296,031,635,661.5 | 309,315,911,509 | +4.487% | - | +9.185% |
| op-cache access | 57,903,436,611.5 | 55,479,990,073 | -4.185% | -8.300% | +0.123% |
| op-cache miss | 51,755,657,851 | 49,472,046,603 | -4.412% | -8.518% | -0.114% |
| derived op-cache hit | 6,147,778,760.5 | 6,007,943,470 | -2.275% | -6.472% | +2.119% |
| decoder-dispatched ops | 292,566,476,017 | 273,605,654,168 | -6.481% | -10.497% | -2.276% |
| op-cache-dispatched ops | 36,700,917,985 | 35,967,645,540 | -1.998% | -6.207% | +2.408% |
| decoder + op-cache dispatch | 329,267,394,002 | 309,573,299,708 | -5.981% | -10.019% | -1.754% |

供给侧派生比率为：

| Ratio | NO0286 | NO0300 | Relative delta |
| --- | ---: | ---: | ---: |
| op-cache miss / access | 89.3827% | 89.1710% | -0.237% |
| op-cache dispatch share | 11.1462% | 11.6185% | +4.237% |

## 3. 解释

op-cache access 与 miss 的绝对值/per-cycle 都下降，per-work 约持平，miss rate 也小幅改善。dispatch 侧没有
出现更多退回 decoder：decoder ops/work 下降 `2.28%`，op-cache dispatch share 反而提高 `4.24%`。

因此 [NO0317](./NO0317_no0286_no0300_frontend_latency_itlb_gate_20260712.md) 中 full-empty frontend
latency slots/cycle `+6.62%` 不能归因于 op-cache miss 数量或供给份额恶化。结合此前 I-cache、ITLB、redirect
和 resync 结果，常见的全局 frontend 计数均未与 latency 增量同向。

## 4. 结论与下一步

停止继续扩大全局 aggregate counter 列表。下一步直接对
`de_no_dispatch_per_slot.no_ops_from_frontend,cmask=0x6` 做固定 period sampling，分别生成 NO0286 / NO0300
函数级和指令级分布，并与 NO0303 的 compute/commit cycles profile 连接。目标是回答增加的 full-empty 周期
集中在哪些 generated compute/commit functions 和基本块，再对这些位置检查汇编控制流、函数布局或长延迟
frontend 恢复路径。

## 5. 产物

```text
build/logs/xs_perf/no0320/opcache_old1_emu.log
build/logs/xs_perf/no0320/opcache_old1_perf.csv
build/logs/xs_perf/no0320/opcache_new_emu.log
build/logs/xs_perf/no0320/opcache_new_perf.csv
build/logs/xs_perf/no0320/opcache_old2_emu.log
build/logs/xs_perf/no0320/opcache_old2_perf.csv
```

