# TNO0067：RepCut load phase Host-only 对照

日期：2026-11-13（America/Los_Angeles）。承接 [TNO0066](./TNO0066_current_repcut_bottleneck_and_next_direction_20261113.md)，本篇记录把 GrhSIM RepCut 的 load phase 从 worker pool 改为 Host-only 的隔离实验。该候选只修改 wrapper common object，模型 archive、RTL、分区、memory 配置和 DiffTest 均保持不变；实验结果不进入默认配置。

## 构建与边界

baseline 使用当前 final binary，candidate 只把：

```cpp
run_phase_workers_(load_step_fns_);
```

替换为：

```cpp
run_host_phase_(load_step_fns_);
```

两侧模型 archive 的成员集合相同，candidate archive 只有 `wolvi_repcut_grhsim_sim_common.o` 的 payload 变化。binary SHA 为：

```text
baseline  c241fe00bb67687f9770c4300665e40f0ca42c5706c7a644b4169e971b7fcfc8
candidate bde96bbf1b58071fe6d289e3bb287d4bda73a5f7e274a9b9af04bed878584046
```

构建记录在 [load-host-candidate build](../../build/xs/repcut-short-profitability-20261112/load-host-candidate/build.json)，候选源和独立 harness 在 [load-host-candidate](../../build/xs/repcut-short-profitability-20261112/load-host-candidate/)。

## 功能与放置门

node030、CPU96–127、NUMA1 strict bind、ASLR disabled、Clang 23、CoreMark 100,000 周期、完整 DiffTest/NEMU。双方均完成 10,000 周期 smoke、100,000 周期 verify、100,000 周期 warmup；8 对 AB/BA 共 16 个正式样本全部通过线程 affinity、NUMA locality、code-page 和 binary identity 检查。

两侧功能签名完全一致：

```text
pc            0x80000c1a
instr_count  250838
cycle_count  99995
guest_cycles 100001
stop_reason  cycle-limit
workload     Running CoreMark for 2 iterations
```

机器可读结果和逐对数据在 [load-host-compare](../../build/xs/repcut-short-profitability-20261112/load-host-compare/runs/)。

## Walltime 结果

| 指标 | baseline | Host-only load | 配对变化 | 95% CI | candidate 更快 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Host time | 13.277875 s | 13.730000 s | **+3.4111%** | **[+2.9125%, +3.9012%]** | 0/8 |
| 外部 walltime | 13.397524 s | 13.841310 s | **+3.3173%** | **[+2.8483%, +3.7809%]** | 0/8 |

配对数据见 [pairs.csv](../../build/xs/repcut-short-profitability-20261112/load-host-compare/runs/pairs.csv)，汇总见 [summary.json](../../build/xs/repcut-short-profitability-20261112/load-host-compare/runs/summary.json)。bootstrap 使用固定 seed `20261102`、10,000 次重采样。

## Phase 归因

8 对正式样本中的累计 phase timing 平均值：

| phase | baseline | Host-only load | 变化 |
| --- | ---: | ---: | ---: |
| input_load | 465.654 ms | 892.592 ms | **+91.7%** |
| part_eval | 11113.526 ms | 11145.146 ms | +0.28% |
| global_update | 1411.471 ms | 1409.261 ms | −0.16% |

候选的总变慢几乎由 input load 增加解释。当前每个 step 有 32 个独立的顶层输入赋值，worker pool 并行执行它们的收益高于 Host 顺序遍历；load phase 的单次工作量虽小，但在 200,102 个 step 上反复触发，串行化会积累成明显固定成本。part_18、part_19、part_23 的 eval 排名基本不变，说明该实验没有改变真正的 compute critical path。

## 结论与后续

Host-only load 候选拒绝，不修改默认 wrapper。这个结果同时排除了“load barrier 可以简单删除”这一假设：当前实现中 load worker pool 是有价值的。

下一步不再改 load 的执行并行度，而是做 phase barrier tail 诊断：为 load/eval/update 记录每个 worker 的完成时间和最后完成 lane，区分 barrier 等待、part 任务不平衡和真正的分区计算时间。只有证明某个 phase 存在稳定的长尾，才考虑按 phase 合并短任务或调整 worker 分配；不直接修改 `pause` 轮询或引入动态 atomic work queue。
