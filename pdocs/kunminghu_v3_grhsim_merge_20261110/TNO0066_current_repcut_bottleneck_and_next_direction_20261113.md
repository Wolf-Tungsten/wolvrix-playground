# TNO0066：当前 RepCut GrhSIM 瓶颈与下一步方向

日期：2026-11-13（America/Los_Angeles）。本篇基于最终短条件成本门 binary 的两次动态采样，重新检查已有优化是否仍然对应当前整机热点，并给出下一轮实验入口。没有修改生产代码或默认配置。

## 对象与测量边界

对象是 `generated-final` 的 Clang 23 binary，SHA256 为：

```text
c241fe00bb67687f9770c4300665e40f0ca42c5706c7a644b4169e971b7fcfc8
```

两次采样均为 CoreMark 100,000 周期、完整 DiffTest/NEMU、CPU96–127、NUMA1、ASLR disabled、32 个 pinned lane。采样只用于归因，不作为新的 walltime 结论；原始数据保存在 [current-hotspots](../../build/xs/repcut-short-profitability-20261112/current-hotspots/)，采样入口在 [current_hotspots.py](../../build/artifacts/repcut-short-profitability-20261112/current_hotspots.py)。

## 当前真正的成本分布

`cycles0` 的 200,102 个 step 统计如下；`cycles1` 的比例和排序相同：

| 阶段 | 总时间 | 占 step 时间 |
| --- | ---: | ---: |
| input load | 477.707 ms | 3.58% |
| part eval | 11,408.203 ms | 85.40% |
| global update | 1,472.579 ms | 11.02% |

按分区汇总的 eval 平均时间为 643.579 微秒/step，最大三个分区是 part_18 40.890 微秒、part_19 40.271 微秒、part_23 39.030 微秒。三者分别对应：

- part_18：短条件/译码计算仍有成本，但剩余 compute batch 已经分散；单个 batch 不再代表整个分区。
- part_19：`eval_with_input_changes` 占该 CPU 的约 8.8–9.0%，是最大的单个非等待函数，主要落在输入比较、XOR delta、活动传播和 previous-input snapshot。
- part_23：`eval_with_input_changes` 约 4.7–5.3%，`run_update_final_part_23_` 约 4.1–4.2%，宽数据更新和 commit batch 共同形成限制。

动态采样中 part_18、part_19、part_23 对应 CPU114、115、119；worker loop 在这些 CPU 上占约 34–38%。这个符号位于 atomic work/stop 的 `pause` 轮询，表示阶段同步后的等待，不能直接当成可消除的译码计算。

## 对已有优化的重新判断

短条件和宽 concat 规则在冻结图上有完整功能门和配对收益，不能据此断言它们已经是全局最优。短条件的 `C >= 2P + I` 是生成期启发式估计，不是目标 CPU 的实际指令成本；继续放宽字段或谓词门，会重新把低收益布尔表达式和输入打包成本引入生成代码。因此本轮不继续扩大 Boolean lowering。

输入 dirty tracking 也不是一块尚未使用的空白。最终生成代码中，part_19 的 previous-input 数组共 6,513 个 64 位 word，其中 4,979 个来自已有 tracked 输入；part_23 共 1,656 个 word，最大的 439/144/142/135 word 输入也已经 tracked。part_19 最大的未追踪宽输入只有 125、101、99 word，part_23 的对应未追踪项为 60、50、49 word。把所有 `copy_changed_wide_words_` 盲目替换为 tracked 版本会增加 producer dirty bit 写入和 update 分支，收益没有证据支持。

当前更值得怀疑的是运行时调度边界：每个 step 有 32 个 load、32 个 eval 和 32 个 update 任务，GrhSIM 的 load 阶段仍调用 `run_phase_workers_`，而 Verilator 路径已经使用 Host-only 的 `run_host_phase_`。load 的 32 个输入赋值总和只有约 4.18 微秒/step，却触发一轮完整 worker release/complete 同步。它和每个 step 的 eval/update barrier 一起解释了 perf 中大量 worker wait；这部分并不是已有译码规则能消除的。

## 下一步实验

先做一个仅改 runtime wrapper 的隔离候选：GrhSIM 的 load phase 改为 `run_host_phase_(load_step_fns_)`，不改 model、partition、input snapshot 或 memory 配置。Host 顺序执行 32 个顶层输入赋值后直接进入 normal eval，语义依赖不变。

候选必须按以下顺序验收：

1. 当前 final binary 的 10,000 周期 smoke 和 100,000 周期完整 DiffTest；
2. 检查 workload 输出、guest cycles、终止条件、NUMA/CPU placement；
3. 与当前 final binary 做 8 对 AB/BA，关闭 trace/profile，比较外部 walltime 和 Host time；
4. 同时记录 input load、part eval、global update 三个阶段，确认减少的是 barrier，而不是把成本转移到 Host；
5. 只有配对 bootstrap CI 全部低于零且功能逐拍一致，才考虑默认启用。

如果 Host-only load 没有收益，第二步再做 phase scheduler 的专项诊断：输出每个 phase 的 worker 完成时间和 barrier tail，评估是否需要拆分单个热点分区或改变同步策略。不要直接修改 `pause` 轮询或把 worker 改成动态队列，因为当前每个 phase 正好有 32 个 part task，动态队列本身可能只增加 atomic 成本。

只有在调度对照排除后，才进入输入传播的局部试验。优先对象是 part_19 的 125/101/99 word 未追踪端口和 part_23 的 60/50/49 word 端口；每次只转换 2–4 条边，并要求事件/commit previous-value 依赖证明通过。若 update_push 增长抵消 eval snapshot 的下降，则回退该候选。更大范围的 sparse previous-input snapshot 作为第三阶段，不能和 dirty tracking 同时引入。

## 结论

当前瓶颈已经从“如何减少译码布尔表达式”转移到“每周期三阶段调度、输入变化传播和少数关键分区的最长路径”。已有 Boolean 优化应保留，但不应继续作为下一轮默认优化入口。最小、可验证、最可能同时减少 wait 和固定开销的方向是先隔离 GrhSIM load barrier；之后再根据 phase tail 和输入快照的因果数据决定是否优化 scheduler 或少量未追踪宽输入。
