# NO0498 SimTop pure-event word profile 100-cycle smoke gate

日期：2026-07-13

## 1. Scope

承接 [NO0497](./NO0497_simtop_pure_event_word_profile_build_gate_20260713.md)，对 profile-only emu 执行 CoreMark/NEMU
difftest 100-cycle smoke：

```text
EMU_RUNTIME_PROFILE=1
EMU_PROGRESS_EVERY_CYCLES=100
limit=-C 100
seed=0
```

日志与 TSV：

```text
build/logs/xs_perf/no0498/profile_smoke_100.log
build/logs/xs_perf/no0498/pure_event_word_100.tsv
```

本轮不固定 CPU/ASLR，host time 不作性能结论。

## 2. Functional result

```text
exit                 0
guest cycles       101
model cycles       100
cycleCnt            96
instrCnt              0
commit/trap PC      0/0
```

功能终点与 NO0359 的 NO0300/direct 两边精确一致。DUT memory、CoreMark image 和 NEMU reference 初始化成功；负向扫描
未发现 `input_fullpass_blocked`、difftest mismatch、assertion、abort、segfault、fatal 或 error。

## 3. Profile closure

```text
rows       22
eligible  107
hit     16,050
miss    18,452
total   34,502
miss ratio 53.4810%
bad rows    0
```

22-row TSV static eligible 求和为 107，dynamic hit/miss 与 dump aggregate 精确一致，每行均满足
`active_total = active_hit + active_miss`。

最大 active batches：

| Batch | Eligible | Hit | Miss | Total |
|---:|---:|---:|---:|---:|
| 35 | 37 | 5,550 | 5,661 | 11,211 |
| 58 | 21 | 3,150 | 3,192 | 6,342 |
| 21 | 8 | 1,200 | 1,527 | 2,727 |
| 41 | 5 | 750 | 1,165 | 1,915 |
| 30 | 6 | 900 | 918 | 1,818 |

100 cycles 尚无 guest instruction commit，但 active misses 已占 53.48%；这证明 whole-word bypass 有真实动态机会，仍不能代替
CoreMark 功能与稳态分布门禁。

## 4. Decision

smoke/profile dump gate 通过。下一步执行 profile-enabled 10k CoreMark/NEMU difftest，要求 endpoint 与 NO0360 精确一致，并
重新闭合 22-row TSV；10k 结果决定是否需要 50k profile。
