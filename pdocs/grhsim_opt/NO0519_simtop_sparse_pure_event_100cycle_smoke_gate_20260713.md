# NO0519 SimTop sparse pure-event 100-cycle smoke gate

日期：2026-07-13

## 1. Scope

承接 [NO0518](./NO0518_simtop_sparse_pure_event_build_codegen_gate_20260713.md)，使用 profile-off fresh hybrid emu 执行
CoreMark/NEMU difftest 100-cycle smoke：

```text
EMU_RUNTIME_PROFILE unset
WOLVRIX_GRHSIM_PURE_EVENT_WORD_TSV unset
EMU_PROGRESS_EVERY_CYCLES=100
seed=0
limit=-C 100
log=build/logs/xs_perf/no0519/hybrid_smoke_100.log
```

本轮未固定 CPU/ASLR，host time 只作执行记录。

## 2. Result

```text
exit                 0
guest cycles       101
model cycles       100
cycleCnt            96
instrCnt              0
commit/trap PC      0/0
host time          249 ms
```

guest/model/cycleCnt/instr/PC 与 NO0359 baseline、NO0504 plain bypass 逐项一致。DUT memory、CoreMark image 与 NEMU
reference 初始化成功；`input_fullpass_blocked`、mismatch、assertion、abort、segfault、fatal、error 负向扫描为 0，profile
状态/TSV 泄漏扫描也为 0。

## 3. Decision

100-cycle smoke gate 通过。该区间仍无 guest instruction commit，下一步执行 10k 并对齐 NO0360 的 10 个 1k checkpoints
与 458-instruction endpoint。
