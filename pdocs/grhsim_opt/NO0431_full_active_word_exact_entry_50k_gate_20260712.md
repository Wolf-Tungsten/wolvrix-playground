# NO0431 Full active-word exact-entry 50k gate

日期：2026-07-12

## 1. Runs

承接 [NO0430](./NO0430_full_active_word_exact_entry_10k_gate_20260712.md)，串行运行 exact baseline 与 padded
candidate CoreMark/NEMU difftest：

```text
seed=0
limit=-C 50000
EMU_PROGRESS_EVERY_CYCLES=10000
EMU_RUNTIME_PROFILE unset
```

本轮只判功能，host time 不用于性能结论。

## 2. Terminal gates

两侧均 exit 0：

```text
guest/model cycles=50,001/50,000
cycleCnt=49,996
instrCnt=73,580
terminal PC=0x80001312
```

没有 mismatch、assert/abort、fatal/error、segmentation fault 或 `input_fullpass_blocked`。

## 3. Checkpoint gates

exact baseline、exact candidate 和 NO0423 production candidate 各有 5 个 10k checkpoints。去掉 `host_ms` 后：

```text
exact baseline vs exact candidate:        5/5 byte-exact
exact candidate vs production candidate: 5/5 byte-exact
```

完整 instruction/PC 序列仍为 `458, 14,121, 27,809, 43,350, 73,580`，证明 padding probe 在 CoreMark
高活动区间也保持可见语义。

日志：

```text
build/logs/xs_perf/no0431/exact_baseline_50k.log
build/logs/xs_perf/no0431/exact_candidate_50k.log
```

## 4. Conclusion

exact-entry baseline/candidate 已通过 10k 和 50k 双边功能门禁。下一步另起 fixed-ASLR PMU plan，现场选择安静
CPU 并执行 exact baseline/candidate/baseline 五事件 A/B/A；不能复用 NO0427 native baseline 的绝对计数。
