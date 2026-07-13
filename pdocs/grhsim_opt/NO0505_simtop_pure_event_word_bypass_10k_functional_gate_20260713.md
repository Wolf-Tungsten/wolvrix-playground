# NO0505 SimTop pure-event word bypass 10k functional gate

日期：2026-07-13

## 1. Scope

承接 [NO0504](./NO0504_simtop_pure_event_word_bypass_100cycle_smoke_gate_20260713.md)，使用相同 profile-off
production candidate 执行 CoreMark/NEMU difftest 10k cycle：

```text
EMU_RUNTIME_PROFILE unset
WOLVRIX_GRHSIM_PURE_EVENT_WORD_TSV unset
EMU_PROGRESS_EVERY_CYCLES=1000
seed=0
limit=-C 10000
```

日志：

```text
build/logs/xs_perf/no0505/bypass_functional_10k.log
```

本轮只判功能，未固定 CPU/ASLR，host time 不作性能结论。

## 2. Endpoint gate

```text
exit                 0
guest cycles    10,001
cycleCnt         9,996
instrCnt           458
terminal PC  0x800027c6
```

终点与 NO0360 direct-state-read baseline 精确一致。负向扫描未发现 `input_fullpass_blocked`、difftest mismatch、
assertion、abort、segfault、fatal 或 error，也没有 profile dump。

## 3. Checkpoint identity

两侧各有 10 个 1k progress checkpoints。去掉 `host_ms` 后逐字节 diff 为 0：

| Guest range | `instr` | `commit_pc` | `trap_pc` |
|---|---:|---|---|
| 1k through 8k | 3 | `0x10000008` | `0x0` |
| 9k | 238 | `0x80001cdc` | `0x800027c6` |
| 10k | 458 | `0x80001cdc` | `0x800027c6` |

这覆盖了复位等待、启动跳转和首批真实 CoreMark 指令提交。

## 4. Decision

10k functional gate 通过。下一步执行 50k，并要求五个 10k checkpoints、73,580 instructions 与 NO0361/NO0500
精确一致；通过后才进入 fixed-ASLR PMU 夹测。
