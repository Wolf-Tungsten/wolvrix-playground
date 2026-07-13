# NO0520 SimTop sparse pure-event 10k functional gate

日期：2026-07-13

## 1. Scope and endpoint

承接 [NO0519](./NO0519_simtop_sparse_pure_event_100cycle_smoke_gate_20260713.md)，使用相同 profile-off hybrid emu
执行 CoreMark/NEMU difftest 10k：

```text
EMU_PROGRESS_EVERY_CYCLES=1000
seed=0
limit=-C 10000
log=build/logs/xs_perf/no0520/hybrid_functional_10k.log
```

结果：

```text
exit                 0
guest cycles    10,001
cycleCnt         9,996
instrCnt           458
terminal PC  0x800027c6
host time       19,918 ms
```

## 2. Checkpoint identity

从日志提取全部 10 个 1k `[EMU_PROGRESS]` rows，去掉 `host_ms` 后分别与 NO0360 baseline、NO0505 plain bypass
逐字节 diff，两个 diff 均为 0：

- 1k through 8k: instr=`3`、commit PC=`0x10000008`、trap PC=`0x0`；
- 9k: instr=`238`、commit/trap PC=`0x80001cdc/0x800027c6`；
- 10k: instr=`458`、commit/trap PC=`0x80001cdc/0x800027c6`。

`input_fullpass_blocked`、mismatch、assertion、abort、segfault、fatal、error 与 profile 泄漏扫描均为 0。当前主机负载高，
`19,918 ms` 只作功能执行记录，不与历史 raw host time 比较。

## 3. Decision

10k functional gate 通过。下一步执行 50k，并要求五个 10k checkpoints 与 NO0361/NO0506 逐项一致，终点保持
`73,580` instructions 与 PC `0x80001312`。
