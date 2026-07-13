# NO0500 SimTop pure-event word profile 50k gate

日期：2026-07-13

## 1. Functional gate

承接 [NO0499](./NO0499_simtop_pure_event_word_profile_10k_gate_20260713.md)，以
`EMU_RUNTIME_PROFILE=1` 执行 CoreMark/NEMU difftest 50k cycles。五个 10k checkpoints 去除 `host_ms` 后与 NO0361
direct baseline 逐字节一致：

| Cycle | Instr | Commit PC | Trap PC |
|---:|---:|---|---|
| 10,000 | 458 | `0x80001cdc` | `0x800027c6` |
| 20,000 | 14,121 | `0x8000043a` | `0x80000440` |
| 30,000 | 27,809 | `0x8000043a` | `0x80000442` |
| 40,000 | 43,350 | `0x80000432` | `0x80000428` |
| 50,000 | 73,580 | `0x800012f8` | `0x80001312` |

终点为 exit 0、guest cycles `50,001`、cycleCnt `49,996`、instrCnt `73,580`、terminal PC `0x80001312`。
负向扫描未发现 `input_fullpass_blocked`、difftest mismatch、assertion、abort、segfault、fatal 或 error。

日志与 TSV：

```text
build/logs/xs_perf/no0500/profile_functional_50k.log
build/logs/xs_perf/no0500/pure_event_word_50k.tsv
```

raw host `134,531 ms` 受 profile 与主机负载影响，不作性能结论。

## 2. Dynamic closure

```text
rows             22
eligible        107
hit       5,355,350
miss      6,948,664
total    12,304,014
miss ratio   56.4748%
bad rows          0
miss words/cycle 138.973
```

22-row TSV、getter 和 dump aggregate 精确闭合，每行 `total = hit + miss`。all-hit count 对每个 eligible word 都是
`50,050`，与统一 clock-posedge event 一致；额外 miss 来自 data/activation 在非目标边沿触发。

## 3. Hot batches and opportunity

| Batch | Eligible | Hit | Miss | Total | Miss share |
|---:|---:|---:|---:|---:|---:|
| 35 | 37 | 1,851,850 | 1,911,992 | 3,763,842 | 27.52% |
| 58 | 21 | 1,051,050 | 1,367,394 | 2,418,444 | 19.68% |
| 21 | 8 | 400,400 | 581,671 | 982,071 | 8.37% |
| 41 | 5 | 250,250 | 450,265 | 700,515 | 6.48% |
| 30 | 6 | 300,300 | 364,228 | 664,528 | 5.24% |

前五个 batches 覆盖总 miss `67.29%`，并与 NO0489 object probe 的 hot batches 重合。6,948,664 个 miss words 对应
约 55,589,312 次固定 entry-bit tests；bypass 还会越过 active payload producers/side effects，但本 profile 未统计 active-bit
popcount，故不虚报 payload 数。

miss ratio 从 100-cycle/10k 的 `53.48%/54.57%` 上升到 50k 的 `56.47%`，不是只存在于 reset 阶段。

## 4. Decision

50k function/profile gate 通过，dynamic opportunity 足够进入 `pure_event_compute_word_bypass=1` 的 production fresh
emit/build/function gate。候选保持 profile off，避免计数插桩影响性能；功能通过后按 fixed-ASLR、固定 CPU/NUMA 和高负载相邻
baseline/bypass/baseline 夹测评估真实收益。
