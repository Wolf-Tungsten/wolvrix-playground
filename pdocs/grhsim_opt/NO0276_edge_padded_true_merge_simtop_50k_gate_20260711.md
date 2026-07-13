# NO0276 Edge-padded true-merge SimTop 50k gate

日期：2026-07-11

## 目标与性能环境

对 [NO0275](./NO0275_edge_padded_true_merge_fresh_function_gate_20260711.md) 的 fresh emu 做固定
CPU old/new/old 50k gate。old 为 NO0271 TAGE true-merge，new 为 NO0274 edge-padded/packed-priority
true-merge；两者使用相同 FIR、checkpoint、schedule 配置和编译选项。

全机 load average 约为 `95~101/384`，因此没有沿用已经被其他任务持续占满的 CPU140。扫描全部
physical-core/SMT pair 后选择 CPU65，sibling 为 CPU257。运行前 5 秒平均 idle 为
`98.4%/99.6%`，各 run 后复检仍约为 `97%~99%`。三个 run 均由 `taskset -c 65` 固定，并同时采集：

```text
cycles:u,instructions:u,branches:u,branch-misses:u
```

所有 event 均为 `100%` scheduled。

## Functional status

三个 paired run 的功能终点完全一致：

```text
Guest cycles: 50001
instrCnt: 73580
cycleCnt: 49996
terminal PC: 0x80001312
mismatch / ABORT: 0 / 0
```

## CPU65 old/new/old

| run | Host time | host cycles | instructions | branches | branch misses |
| --- | ---: | ---: | ---: | ---: | ---: |
| NO0271 old 1 | `103824ms` | `371600087602` | `193658014470` | `15322478048` | `5881246379` |
| NO0274 new | `86277ms` | `308487317278` | `190862465853` | `15156416715` | `5510081435` |
| NO0271 old 2 | `104002ms` | `371376929489` | `193658014541` | `15322477939` | `5881131973` |

old 两次 Host time spread 为 `0.1713%`，host cycles spread 为 `0.0601%`，说明高全机 load 下选定
core 的局部窗口仍稳定。以 old 均值为 baseline：

| metric | old mean | new | delta |
| --- | ---: | ---: | ---: |
| Host time | `103913.0ms` | `86277ms` | `-16.9719%` |
| host cycles | `371488508545.5` | `308487317278` | `-16.9591%` |
| instructions | `193658014505.5` | `190862465853` | `-1.4435%` |
| branches | `15322477993.5` | `15156416715` | `-1.0838%` |
| branch misses | `5881189176.0` | `5510081435` | `-6.3101%` |
| branch-miss rate | `38.3828%` | `36.3548%` | `-2.0280pp` |
| IPC | `0.521303` | `0.618704` | `+18.6843%` |
| guest cycles/s | `481.181` | `579.540` | `+20.4411%` |

Host time 与 cycles 的下降一致，且两次 old 包住 new，因此结果不是单次频率或全机负载漂移。当前
CPU65 的 absolute Host time 与历史 CPU140 不可横向比较；本结论只使用同核相邻 old/new/old。

## 收益边界

NO0273 中 ROB `debug_VecOtherPdest` 只占旧 branch-miss profile 的约 `2.40%`，而本轮总 branch
misses 下降 `6.31%`、cycles 下降约 `16.96%`。因此不能把全部收益归因于目标 2816 个 scalar
write。NO0274 全图 true groups 从 NO0271 的 `575` 增至 `825`，其中 `171` 个为 edge-padded
true-merge；它们共同改变了 commit guard、state-read activation、batch layout 和 cache footprint。

本轮可以确认的是：通用改写整体功能正确且性能显著为正；若要量化 ROB 单项贡献，需要另做只控制
group 范围的诊断 probe，不能从全图 A/B 直接反推。

## 日志

```text
build/logs/xs_perf/no0276/cpu65_preflight_before_old1_20260711.log
build/logs/xs_perf/no0276/paired_old_no0271_cpu65_50k_run1.log
build/logs/xs_perf/no0276/paired_old_no0271_cpu65_50k_run1_perf_stat.csv
build/logs/xs_perf/no0276/paired_new_no0274_cpu65_50k.log
build/logs/xs_perf/no0276/paired_new_no0274_cpu65_50k_perf_stat.csv
build/logs/xs_perf/no0276/paired_old_no0271_cpu65_50k_run2.log
build/logs/xs_perf/no0276/paired_old_no0271_cpu65_50k_run2_perf_stat.csv
```

## 结论与下一步

edge-padded/packed-priority true-merge 应保留：fresh 10k/50k difftest 和稳定 old/new/old performance
gate 均通过，50k throughput 提高 `20.44%`。下一步对 new 做 branch-miss post-profile，确认旧
batch84 ROB 热点是否消失，并从新的 commit/compute 头部继续与 GSim generated state 结构对照。
