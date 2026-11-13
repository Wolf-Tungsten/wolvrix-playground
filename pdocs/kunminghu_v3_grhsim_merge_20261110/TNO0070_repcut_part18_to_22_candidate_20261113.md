# TNO0070：RepCut part18 -> part22 候选复测

日期：2026-11-13（America/Los_Angeles）。承接 [TNO0069](./TNO0069_repcut_local_partition_rebalance_20261113.md)，本篇记录把相同 piece 从 part 18 移到 part 22 的候选。该候选使用和 TNO0069 相同的冻结 RTL、memory graph、emitter 选项、Clang 23.1.2 和 node030 placement。

## 构建与功能门

候选 assignment 为 `piece_800268_p18_to_22`，binary SHA256 为：

```text
bbde8c204f0ba95cff0fe4df4bf528ef8a690860994de89192f3e1f92ab7e27b
```

候选重放和 binary 位于 `../../build/xs/repcut-short-profitability-20261112/current-part-18-to-22/`。完整的 assignment、binary/config 身份和两组汇总数据位于 `../../build/artifacts/repcut-short-profitability-20261112/current-part-18-to-22/`。第一次 paired runner 尝试因 baseline 的少量 NEMU/library 页落到 NUMA0 被 placement gate 拒绝，拒绝证据单独保留在该目录的 `runs-initial-rejected/`，不计入性能统计。

两次有效尝试均在 CPU96–127、NUMA1、关闭 ASLR、32 个 pinned worker 和完整 DiffTest/NEMU 下通过 10k smoke、100k verify、100k warmup 及 workload 签名检查。第一次有效尝试发现 verify 日志可能带有 host-only 的 `[codepage-retry]` 进度行；该行不属于 guest UART，已在 `scripts/grhsim_single_baseline.py` 的 parser 中过滤，并通过 17 项 `scripts/test_grhsim32.py`。guest 签名保持：PC `0x80000c1a`、250838 instructions、99995 model cycles、100001 guest cycles、cycle-limit、CoreMark 输出一致。

## 两组 8 对 AB/BA

每组均使用 8 对 AB/BA、100,000 周期。两组的逐对 CSV 和 summary JSON 分别在 `../../build/xs/repcut-short-profitability-20261112/current-part-18-to-22-compare/runs-retry2/` 和 `runs-retry3/`。

| 组 | Host baseline | Host candidate | Host delta / CI | 外部 wall baseline | 外部 wall candidate | wall delta / CI |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| retry2 | 13.939125 s | 13.399500 s | −3.768% / [−6.528%, −1.048%] | 14.049760 s | 13.955013 s | −0.490% / [−6.016%, +6.210%] |
| retry3 | 13.642000 s | 13.459125 s | −1.337% / [−3.111%, +1.382%] | 13.758596 s | 13.571038 s | −1.356% / [−3.215%, +1.409%] |

retry2 的 Host CI 全部低于零，但 retry3 的 Host 和两组外部 wall CI 都跨零。retry2 的外部 wall 受 candidate 首个正式样本 code-page setup 约 3.2 s 影响；retry3 没有同样的 setup 长尾。两组都显示平均方向为 candidate 更快，但没有达到稳定整机 walltime 门。

## Phase 和 critical lane

两组有效运行的 phase 方向一致。以 retry3 为例，baseline 到 candidate 的平均 phase 为：

| phase | baseline | candidate |
| --- | ---: | ---: |
| input_load | 469.291 ms | 442.637 ms |
| part_eval | 11440.758 ms | 11254.707 ms |
| global_update | 1437.625 ms | 1470.577 ms |

part 18 的 eval 从约 41.564 us 降到 30.253 us，但 part 22 从约 19.014 us 增到 37.972 us；part 19 仍是新的最长 lane（约 40.404 us），part 23 约 37.301 us。候选确实降低了原 part 18 的工作，但没有稳定降低整体 critical path 到可测 walltime 收益的程度。

## 结论

`part18 -> part22` 作为结构方向是有效的局部重平衡，但两组独立 8 对结果的 bootstrap CI 均不能证明稳定 walltime 加速，因此不替换 TNO0069 的 `part18 -> part17` 实验候选，也不修改默认 assignment。下一步若继续优化，应围绕 part 19/23 做更小的 boundary swap，并把 code-page setup 与 global update 增量一起纳入验收；当前最可靠的实验候选仍是 TNO0069。


## 增量更新 2026-11-13：执行边界与 parser 回归

按用户最新要求，停止手动 swap 和运行后候选选择，本篇及 TNO0069 均只保留历史记录。整理时进一步发现 retry 过滤误伤行内 `[CYCLE_LIMIT]` 的既有 UART 拼接语义，已修复并将 retry 回归用例移至 baseline 日志测试；58 项相关 Python 测试通过。没有因此重算或重跑本篇性能数据。详见 [TNO0071](./TNO0071_cleanup_and_branch_checkpoint_20261113.md)。
