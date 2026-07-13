# NO0521 SimTop sparse pure-event 50k functional gate

日期：2026-07-13

## 1. Scope and endpoint

承接 [NO0520](./NO0520_simtop_sparse_pure_event_10k_functional_gate_20260713.md)，使用相同 profile-off hybrid emu
执行 CoreMark/NEMU difftest 50k：

```text
EMU_PROGRESS_EVERY_CYCLES=10000
seed=0
limit=-C 50000
log=build/logs/xs_perf/no0521/hybrid_functional_50k.log
```

结果：

```text
exit                 0
guest cycles    50,001
cycleCnt        49,996
instrCnt        73,580
terminal PC  0x80001312
host time      179,871 ms
```

## 2. Checkpoint identity

去掉 `host_ms` 后，五个 10k checkpoints 分别与 NO0361 direct-state-read baseline、NO0506 plain bypass 逐字节
diff，两个 diff 均为 0：

| Cycle | `instr` | `commit_pc` | `trap_pc` |
| ---: | ---: | --- | --- |
| 10,000 | 458 | `0x80001cdc` | `0x800027c6` |
| 20,000 | 14,121 | `0x8000043a` | `0x80000440` |
| 30,000 | 27,809 | `0x8000043a` | `0x80000442` |
| 40,000 | 43,350 | `0x80000432` | `0x80000428` |
| 50,000 | 73,580 | `0x800012f8` | `0x80001312` |

`input_fullpass_blocked`、mismatch、assertion、abort、segfault、fatal、error 与 profile 泄漏扫描均为 0。

## 3. Host-load caveat

运行前后 load average 为 `151.40/162.71/167.71` 与 `159.18/158.60/164.71`。10k checkpoint 的累计 host time
从 `16,986 ms` 到 20k 的 `87,701 ms`，明显受到共享负载扰动。本轮 `179,871 ms` 只证明 50k 功能，不是性能样本，
不能与 NO0357/NO0501 raw time 比较。

## 4. Decision

fresh hybrid 已通过 source、build、100-cycle、10k 和 50k 全部功能门禁，且没有复现 `input_fullpass_blocked`。下一步先按
NO0507 sibling-idle `>=99%` 规则重新做 CPU quiet survey；只有 quiet gate 通过才启动 fixed-ASLR
baseline/hybrid/baseline PMU。若继续高负载，则保持零性能样本并转去静态/机制分析，不放宽门限。
