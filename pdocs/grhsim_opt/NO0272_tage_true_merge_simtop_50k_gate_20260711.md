# NO0272 TAGE true-merge SimTop 50k gate

日期：2026-07-11

## 目标与口径

对 [NO0271](./NO0271_tage_shared_packed_true_merge_20260711.md) 的 fresh emu 做 SimTop 功能、
CPU140 old/new/old 性能和 branch-miss post-profile gate。old 为已通过功能门槛的 NO0269 packed
active scan 产物，new 仅增加本轮 `reg-to-mem` 改写。

性能测试前系统 load 约 `12~25/384`；CPU140 和 SMT sibling CPU332 的空闲采样约为
`100%/95%~100%`。三个 run 均固定 CPU140，四个 perf event 同时采集且均为 `100%` scheduled。

## Functional gate

10k fresh run：

```text
Guest cycles: 10001
instrCnt: 458
cycleCnt: 9996
terminal PC: 0x800027c6
mismatch / ABORT: 0 / 0
Host time: 11316ms
```

日志：

```text
build/logs/xs/xs_wolf_grhsim_no0271_tage_true_merge_10k_20260711.log
```

三个 paired 50k run 的功能状态完全一致：

```text
Guest cycles: 50001
instrCnt: 73580
cycleCnt: 49996
terminal PC: 0x80001312
mismatch / ABORT: 0 / 0
```

因此 new 中间 run 同时通过完整 50k difftest gate。

## CPU140 old/new/old

| run | Host time | cycles | instructions | branches | branch misses |
| --- | ---: | ---: | ---: | ---: | ---: |
| NO0269 old 1 | `98646ms` | `361824461499` | `199862205623` | `17134609598` | `7728593406` |
| TAGE true-merge | `85053ms` | `311976022625` | `193657974107` | `15322448029` | `5884805434` |
| NO0269 old 2 | `98498ms` | `361323189136` | `199862182733` | `17134596025` | `7726511015` |

old 两次 Host time 只差 `0.15%`。以 old 均值为 baseline：

| metric | old mean | new | delta |
| --- | ---: | ---: | ---: |
| Host time | `98572.0ms` | `85053ms` | `-13.7148%` |
| host cycles | `361573825317.5` | `311976022625` | `-13.7172%` |
| instructions | `199862194178` | `193657974107` | `-3.1042%` |
| branches | `17134602811.5` | `15322448029` | `-10.5760%` |
| branch misses | `7727552210.5` | `5884805434` | `-23.8464%` |
| branch-miss rate | `45.0991%` | `38.4064%` | `-6.6927pp` |
| IPC | `0.552756` | `0.620746` | `+12.3002%` |
| guest cycles/s | `507.254` | `587.880` | `+15.8948%` |

性能日志：

```text
build/logs/xs_perf/no0271/paired_old_no0269_cpu140_50k_run1.log
build/logs/xs_perf/no0271/paired_old_no0269_cpu140_50k_run1_perf_stat.csv
build/logs/xs_perf/no0271/paired_new_tage_true_merge_cpu140_50k.log
build/logs/xs_perf/no0271/paired_new_tage_true_merge_cpu140_50k_perf_stat.csv
build/logs/xs_perf/no0271/paired_old_no0269_cpu140_50k_run2.log
build/logs/xs_perf/no0271/paired_old_no0269_cpu140_50k_run2_perf_stat.csv
```

## Branch-miss post-profile

new 使用与 NO0270 相同的 `branch-misses:u, period=500000, dwarf=8192`：

```text
samples: 11763
lost samples: 0
event count (approx.): 5881500000
Guest cycles: 50001
Host time: 85693ms
```

old/new 按符号类聚合：

| class | old share | new share | old absolute approx. | new absolute approx. |
| --- | ---: | ---: | ---: | ---: |
| commit batches | `68.19%` | `58.12%` | `5.269B` | `3.418B` |
| compute batches | `31.21%` | `41.09%` | `2.411B` | `2.417B` |

commit branch misses 约下降 `35.12%`，compute 绝对量仅变化 `+0.22%`。这说明本轮总 miss 下降主要
来自 commit scalar guard 消失，而不是 workload 或 compute 执行量变化。

按 generated source 映射，old 的 32768 个 TAGE scalar writes 分布在 commit batch
`100/101/109/112/114/115/116/119/120`，branch-miss share 合计 `22.64%`，约 `1.749B`。new 的
64 个 indexed memory writes 集中在 batch103，该 batch share 为 `1.70%`，约 `0.100B`；batch
包络下降约 `94.28%`。batch 内仍有其他 commit work，因此该值是 source-mapped batch 包络，不是
逐 operation 精确计数，但与总 miss、commit absolute 和 generated structure 三项证据一致。

profile 产物：

```text
build/logs/xs_perf/no0271/tage_true_merge_simtop_50k_branch_misses.data
build/logs/xs_perf/no0271/tage_true_merge_simtop_50k_branch_misses_run.log
build/logs/xs_perf/no0271/tage_true_merge_simtop_50k_branch_misses_symbols.report
build/logs/xs_perf/no0271/commit103_branch_misses_annotate.report
```

## 结论与下一步

TAGE true-merge 功能正确，并在稳定 old/new/old 窗口中把 SimTop 50k Host time 降低 `13.71%`、
guest throughput 提高 `15.89%`。目标 scalar guard 的 branch-miss 包络基本消失，证明 NO0270 的
根因判断成立，本实现应保留。

新的 branch-miss 头部不再由单个 4096-row TAGE batch 主导；前三个 commit batch 为
`95/84/88`，share 分别为 `3.07%/2.92%/2.88%`。下一阶段应从这三个 batch 的 generated source
和 GSim 对应状态结构重新归因，继续优先寻找可恢复的 aggregate storage，而不是做全局 branchless
改写。
