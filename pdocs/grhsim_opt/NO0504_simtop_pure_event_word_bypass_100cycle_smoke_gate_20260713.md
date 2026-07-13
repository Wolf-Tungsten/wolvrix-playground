# NO0504 SimTop pure-event word bypass 100-cycle smoke gate

日期：2026-07-13

## 1. Scope

承接 [NO0503](./NO0503_simtop_pure_event_word_bypass_build_codegen_gate_20260713.md)，使用 profile-off production
candidate 执行 CoreMark/NEMU difftest 100-cycle smoke：

```text
EMU_RUNTIME_PROFILE unset
WOLVRIX_GRHSIM_PURE_EVENT_WORD_TSV unset
EMU_PROGRESS_EVERY_CYCLES=100
seed=0
limit=-C 100
```

日志：

```text
build/logs/xs_perf/no0504/bypass_smoke_100.log
```

本轮未固定 CPU/ASLR，host time 不作性能结论。

## 2. Functional result

```text
exit                 0
guest cycles       101
model cycles       100
cycleCnt            96
instrCnt              0
commit/trap PC      0/0
```

以上字段与 NO0359 direct-state-read baseline 逐项一致。DUT memory、CoreMark image 和 NEMU reference 初始化成功；
负向扫描未发现 `input_fullpass_blocked`、difftest mismatch、assertion、abort、segfault、fatal 或 error。日志中也没有
runtime/profile dump，证明 profile 环境没有泄漏到 production smoke。

## 3. Decision

100-cycle smoke gate 通过，但该区间仍无 guest instruction commit。下一步执行 10k CoreMark/NEMU difftest，要求 10 个
1k checkpoints 和终点与 NO0360 direct baseline 精确一致。
