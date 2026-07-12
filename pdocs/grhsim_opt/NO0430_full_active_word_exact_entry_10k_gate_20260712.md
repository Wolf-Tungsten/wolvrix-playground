# NO0430 Full active-word exact-entry 10k gate

日期：2026-07-12

## 1. Runs

承接 [NO0429](./NO0429_full_active_word_exact_entry_build_gate_20260712.md)，串行运行 exact baseline 与 padded
candidate：

```text
image: testcase/xiangshan/ready-to-run/coremark-2-iteration.bin
diff:  testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so
seed:  0
limit: -C 10000
EMU_PROGRESS_EVERY_CYCLES=1000
EMU_RUNTIME_PROFILE unset
```

本轮只判功能，未固定 CPU/ASLR，host time 不作性能结论。

## 2. Terminal gates

两侧均 exit 0：

```text
guest/model cycles=10,001/10,000
cycleCnt=9,996
instrCnt=458
terminal PC=0x800027c6
```

没有 mismatch、assert/abort、fatal/error、segmentation fault 或 `input_fullpass_blocked`。

## 3. Checkpoint gates

exact baseline、exact candidate 和 NO0422 production candidate 各有 10 个 1k checkpoints。抽取
`[EMU_PROGRESS]` 并去掉 `host_ms` 后：

```text
exact baseline vs exact candidate:       10/10 byte-exact
exact candidate vs production candidate: 10/10 byte-exact
```

因此 explicit link 和 66 个 executable-text pad 没有改变 reset、启动或 CoreMark 初段的可见周期行为。

日志：

```text
build/logs/xs_perf/no0430/exact_baseline_10k.log
build/logs/xs_perf/no0430/exact_candidate_10k.log
```

## 4. Next gate

下一步串行运行双边 50k，按 10k interval 比较 5 个 checkpoints，并要求 73,580 instructions 和最终 PC
与 NO0423 一致。通过后才规划 exact-entry PMU A/B/A。
