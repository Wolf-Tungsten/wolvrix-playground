# NO0499 SimTop pure-event word profile 10k gate

日期：2026-07-13

## 1. Scope and functional endpoint

承接 [NO0498](./NO0498_simtop_pure_event_word_profile_100cycle_smoke_gate_20260713.md)，以
`EMU_RUNTIME_PROFILE=1` 执行 CoreMark/NEMU difftest 10k cycles，1k interval progress：

```text
exit             0
guest cycles    10,001
cycleCnt         9,996
instrCnt           458
terminal PC 0x800027c6
```

10 个 progress checkpoints 去除 `host_ms` 后与 NO0360 direct baseline 逐字节一致；1k through 8k 保持 3 instructions，9k/10k
分别为 238/458，commit/trap PC 完全一致。负向扫描未发现 `input_fullpass_blocked`、difftest mismatch、assertion、abort、
segfault、fatal 或 error。

日志与 TSV：

```text
build/logs/xs_perf/no0499/profile_functional_10k.log
build/logs/xs_perf/no0499/pure_event_word_10k.tsv
```

host time `12,729 ms` 受 profile 与主机负载影响，不作性能结论。

## 2. Profile closure

```text
rows           22
eligible      107
hit     1,075,350
miss    1,291,582
total   2,366,932
miss ratio 54.5678%
bad rows        0
```

TSV、getter 与 dump aggregate 精确闭合，每行 `total = hit + miss`。若开启 bypass，1,291,582 个 edge-miss active-word
dispatch 可在 underlying clear 后直接越过；这对应约 10,332,656 次固定 entry-bit tests，尚未把 active payload work 计入。

最大 active batches：

| Batch | Eligible | Hit | Miss | Total | Miss ratio |
|---:|---:|---:|---:|---:|---:|
| 35 | 37 | 371,850 | 372,486 | 744,336 | 50.04% |
| 58 | 21 | 211,050 | 214,074 | 425,124 | 50.35% |
| 21 | 8 | 80,400 | 110,975 | 191,375 | 57.99% |
| 41 | 5 | 50,250 | 90,265 | 140,515 | 64.24% |
| 30 | 6 | 60,300 | 61,015 | 121,315 | 50.29% |

batches 16/18/27/50 及 51/57 的 miss ratio 约 66.61%，但绝对 total 小于前三个热点。

## 3. Decision

10k 功能/profile gate 通过，且 miss ratio 从 100-cycle 的 53.48% 保持为 54.57%。但 10k 只提交 458 instructions，仍
主要覆盖启动阶段。下一步执行 50k profile，覆盖约 73.6k instructions 的 CoreMark 主体；50k endpoint 与 TSV 通过后，
再 fresh emit/build bypass candidate并做 fixed-ASLR 性能 A/B/A。
