# TNO0068：RepCut phase tail 诊断与下一步分区方向

日期：2026-11-13（America/Los_Angeles）。承接 [TNO0067](./TNO0067_repcut_load_barrier_ablation_20261113.md)，本篇记录当前 final binary 的 phase-window 诊断。该诊断只替换 common wrapper object，模型 archive 的其它成员保持不变，不作为正式 walltime binary。

## 诊断对象

使用当前 final 32 线程 RepCut package，在 node030、CPU96–127、NUMA1、ASLR disabled、完整 DiffTest/NEMU、CoreMark 100,000 周期运行两次。诊断 wrapper 记录每个 phase 的 dispatch、Host 批次、worker residual wait 和 phase 总时间。binary SHA：

```text
dd51db47ddfd2171d1a025b958129c4bfba05eba9ef8a59f0941b49b222bdc17
```

原始 trace 和 timing 保存在 [phase-sync-current](../../build/xs/repcut-short-profitability-20261112/phase-sync-current/)，构建和运行脚本分别为 [build_phase_sync_current.py](../../build/artifacts/repcut-short-profitability-20261112/build_phase_sync_current.py) 和 [run_phase_sync_current.py](../../build/artifacts/repcut-short-profitability-20261112/run_phase_sync_current.py)。两次运行的功能签名、线程放置和 NUMA gate 均通过。

## 结果

两次采样的 phase 汇总基本一致，以下取第二次结果：

| phase | total | Host 批次 | residual wait | wait / total |
| --- | ---: | ---: | ---: | ---: |
| load | 465.261 ms | 77.517 ms | 191.723 ms | 41.21% |
| normal eval | 11078.260 ms | 2593.198 ms | 8320.098 ms | 75.10% |
| normal update | 1395.829 ms | 145.928 ms | 1054.047 ms | 75.51% |

early eval 和 early update 为空。dispatch 部分每个 phase 约 0.16–0.20 s，远小于 phase 主体；因此不能把现有 75% wait 比例解释成锁或条件变量开销。

## 解释边界

当前 wrapper 的 `run_phase_batch_` 按函数列表和 worker index 做静态连续分配；32 个 normal-eval part task 基本是一 lane 一分区。Host lane 是 lane 9/CPU105，而最慢 eval 分区是：

| 分区 | eval 平均时间 |
| --- | ---: |
| part_18 | 约 40.5 us/step |
| part_19 | 约 39.1 us/step |
| part_23 | 约 36.7 us/step |
| part_14 | 约 30.7 us/step |
| part_15 | 约 30.3 us/step |

Host 完成自身 lane 后等待其它 worker 是正常的 phase critical-path 行为。把 load 改成 Host-only 已经证明了“减少一轮 worker dispatch”会使 input_load 从约 466 ms 增加到约 893 ms，并使总 Host time 增加 3.41%；因此不能通过简单删除 worker pool 或直接修改 `pause` 解决问题。

## 下一步方向

下一步应回到 partition critical path，而不是通用 runtime barrier：

1. 先用当前 part timing 和图结构筛选 part_18/19/23 的可拆分边界，计算候选移动对最大 eval lane 的影响，同时估算新增跨分区 update/copy 成本。
2. 优先尝试保持 32 个 lane 数量不变的局部 re-cut 或 boundary swap，避免全图重新分区导致 seed/RTL 变化不可归因。
3. 每个候选先做结构审计：part operation/compute 数、boundary edges、宽 copy 数、commit/update 规模；只有 critical-path 下降且 communication 增量受控才生成 binary。
4. 候选 binary 通过 10k/100k DiffTest、CPU/NUMA/ASLR gate 后，再做至少 8 对 AB/BA。仅当最长 lane 和总 walltime 同时改善，才保留分区候选。

可以继续保留 phase-sync 诊断作为验证工具，但不应把 `wait / total` 直接当作可回收收益。它表示其它 lane 的计算时间；真正可优化的量是 part_18/19/23 的计算和它们引起的跨分区传播。

## 结论

当前 worker barrier 的主要问题是静态 lane 之间的工作不均衡，而不是 load dispatch 或同步原语本身。下一轮最有价值的实验是局部 partition rebalance，目标是压低 part_18/19/23 的最长路径，并严格衡量新增 update/copy 成本。
