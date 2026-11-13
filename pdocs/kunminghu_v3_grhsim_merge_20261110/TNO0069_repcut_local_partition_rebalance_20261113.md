# TNO0069：RepCut 局部分区重平衡候选验收

日期：2026-11-13（America/Los_Angeles）。承接 [TNO0068](./TNO0068_repcut_phase_tail_diagnosis_20261113.md)，本篇记录针对当前 final seed7 分区的局部重平衡实验。实验只改变 assignment，保留同一份 RTL、memory graph、GrhSIM emitter 选项、Clang 23.1.2 和运行时 placement。

## 候选与构建

根据两次 phase-sync 采样和结构 evaluator，选择 `piece_800268_p18_to_17`：将 part 18 的一个 piece 移到 part 17。候选使用冻结的 after `DefaultConfig` 图和当前 final 生成参数重新 replay/emit，未重新求解全图。候选 binary 已独立编译，身份如下：

```text
baseline: 115520112 bytes
  c241fe00bb67687f9770c4300665e40f0ca42c5706c7a644b4169e971b7fcfc8
candidate: 115572816 bytes
  e07fb67017a5d8978f95391cf7a6d8b33b48c1a366f9971515bd2fea8d07ee78
```

assignment、重放日志和候选 binary 位于 `../../build/xs/repcut-short-profitability-20261112/current-part-18-to-17/`；配对运行元数据位于 `../../build/xs/repcut-short-profitability-20261112/current-part-18-to-17-compare/`。结构 evaluator 的完整候选报告见 `../../build/artifacts/repcut-short-profitability-20261112/current-part-evaluation-v2/report.json`，assignment 见 `../../build/artifacts/repcut-short-profitability-20261112/current-part-proposals/piece_800268_p18_to_17.assignment`。

本次小型归档（assignment、binary/config 身份、functional summary、逐对 CSV 和汇总 JSON）位于 `../../build/artifacts/repcut-short-profitability-20261112/current-part-18-to-17/`。

## 功能和 placement gate

在 node030 上使用 CPU96–127、32 个 pinned RepCut worker、NUMA1、关闭 ASLR、完整 DiffTest/NEMU 和 CoreMark 两次迭代。baseline 与 candidate 均通过 10,000 周期 smoke、100,000 周期 verify、100,000 周期 warmup 以及所有正式样本的线程和 locality 检查。两侧签名完全一致：

```text
pc            0x80000c1a
instr_count   250838
cycle_count   99995
guest_cycles  100001
stop_reason   cycle-limit
output        Running CoreMark for 2 iterations
```

## 8 对 AB/BA walltime

正式测量关闭 trace 和诊断计数，执行 8 对交替 AB/BA。完整逐对数据在 `../../build/xs/repcut-short-profitability-20261112/current-part-18-to-17-compare/runs/pairs.csv`，汇总在 `../../build/xs/repcut-short-profitability-20261112/current-part-18-to-17-compare/runs/summary.json`。

| 指标 | baseline | part18 -> part17 | 配对变化 | 95% bootstrap CI |
| --- | ---: | ---: | ---: | ---: |
| Host time | 12.888875 s | 12.664500 s | −1.738952% | [−2.140991%, −1.361514%] |
| 外部 walltime | 13.000638 s | 12.774943 s | −1.734020% | [−2.145611%, −1.341637%] |

候选 8/8 对更快。CI 使用固定 seed `20261102`、10,000 次 paired bootstrap；所有样本均已通过功能和 placement gate，因此没有被拒绝样本进入统计。

## Phase 变化与解释

8 对 timing JSONL 的平均 phase 如下：

| phase | baseline | candidate | 变化 |
| --- | ---: | ---: | ---: |
| input_load | 459.534 ms | 433.781 ms | −5.604% |
| part_eval | 10756.309 ms | 10528.022 ms | −2.122% |
| global_update | 1390.599 ms | 1413.311 ms | +1.633% |

局部 part eval 的平均变化为：

| part | baseline | candidate |
| --- | ---: | ---: |
| part_17 | 19.496 us | 34.912 us |
| part_18 | 39.015 us | 28.547 us |
| part_19 | 38.093 us | 38.801 us |
| part_23 | 35.598 us | 34.718 us |

因此候选压低了原最长的 part 18，但迁移成本使 part 17 变重，新的 critical lane 是 part 19。walltime 收益与 part_eval 下降方向一致，global update 的小幅回升没有抵消它。该结果支持“局部 re-cut 有效”，但不表示当前候选已经是最优 assignment。

## 结论和后续边界

`part18 -> part17` 是当前第一个通过完整功能/placement gate 且 8 对 CI 全部低于零的局部分区候选。它应保留为实验 retained candidate，不覆盖当前正式 seed7 配置。下一步应围绕新的 part 19/23 critical path 做更小的 boundary swap，并把 `part_17` 上升的 eval 与新增 update 成本纳入候选门；只有新的候选在相同 8 对验收中继续改善，才考虑替换 retained assignment。


## 增量更新 2026-11-13：停止手动选择

用户随后要求暂时不要进行手动选择或运行后选择。本篇结果仅保留为历史候选，不替换正式 seed7；上文继续 boundary swap 和按实测更新 retained 的建议不再作为执行依据。新分支与整理范围见 [TNO0071](./TNO0071_cleanup_and_branch_checkpoint_20261113.md)。
