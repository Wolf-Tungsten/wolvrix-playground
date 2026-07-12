# NO0422 SimTop full active-word 10k functional gate

日期：2026-07-12

## 1. Configuration

承接 [NO0421](./NO0421_simtop_full_active_word_100cycle_smoke_gate_20260712.md)，运行相同 candidate：

```text
image: testcase/xiangshan/ready-to-run/coremark-2-iteration.bin
diff:  testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so
seed:  0
limit: -C 10000
EMU_PROGRESS_EVERY_CYCLES=1000
EMU_RUNTIME_PROFILE unset
```

所有命令均先 `source env.sh`。本轮只判功能，不用 host time 评价性能。日志：

```text
build/logs/xs_perf/no0422/full_word_functional_10k.log
```

## 2. Terminal gate

执行 exit 0，终点与 NO0360 的 NO0300/direct 完全一致：

```text
guest cycles=10,001
model cycles=10,000
cycleCnt=9,996
instrCnt=458
terminal PC=0x800027c6
```

模型提交首条指令并启用 NEMU difftest。负向扫描 0 命中，包括 `input_fullpass_blocked`、difftest mismatch、
assert/abort、segmentation fault 和 fatal/error。

## 3. Checkpoint gate

candidate 与 `build/logs/xs_perf/no0360/direct_state_read_functional_10k.log` 各有 10 个 1k progress
checkpoints。抽取每行 `[EMU_PROGRESS]` 子串并去掉 `host_ms` 后，10/10 逐字节一致：

```text
1k..8k: instr=3   commit_pc=0x10000008 trap_pc=0x0
9k:     instr=238 commit_pc=0x80001cdc trap_pc=0x800027c6
10k:    instr=458 commit_pc=0x80001cdc trap_pc=0x800027c6
```

因此 reset 等待、启动跳转与 CoreMark 初段的外部可见周期行为均未偏移。

## 4. Next gate

10k 只执行 458 条指令。下一步运行 50k CoreMark/NEMU difftest，按 10k interval 与 NO0361 比较全部
checkpoints，并要求最终 73,580 instructions、guest/model cycles 和 PC 完全一致后才进入性能 gate。
