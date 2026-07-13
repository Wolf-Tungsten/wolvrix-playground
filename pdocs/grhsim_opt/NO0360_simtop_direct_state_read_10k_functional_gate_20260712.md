# NO0360 SimTop direct state-read 10k functional gate

日期：2026-07-12

## 1. 口径

承接 [NO0359](./NO0359_simtop_direct_state_read_100cycle_smoke_gate_20260712.md)，对 NO0300 baseline 与 direct
state-read emu 并行运行相同的 CoreMark/NEMU difftest 10k cycle：

```text
image: testcase/xiangshan/ready-to-run/coremark-2-iteration.bin
diff:  testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so
seed:  0
limit: -C 10000
EMU_PROGRESS_EVERY_CYCLES=1000
EMU_RUNTIME_PROFILE unset
```

所有命令均先执行 `source env.sh`。本轮未固定 CPU、未控制 ASLR、两边并行运行，只判功能，不使用 host time
评价性能。

## 2. 终点门禁

| Model | Exit | Guest cycles | `cycleCnt` | `instrCnt` | Terminal PC | Result |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| NO0300 baseline | 0 | 10,001 | 9,996 | 458 | `0x800027c6` | PASS |
| direct state-read | 0 | 10,001 | 9,996 | 458 | `0x800027c6` | PASS |

两边均提交首条指令并启用 difftest，最终五项功能字段严格一致。负向扫描未发现 difftest mismatch、assertion、
abort、segmentation fault、fatal/error 或 `input_fullpass_blocked`。

## 3. 逐检查点一致性

两份日志各有 10 个 1k progress checkpoints。去掉 `host_ms` 后，所有 checkpoint 以及 cycle-limit/终点行
逐字节一致：

| Guest range | `instr` | `commit_pc` | `trap_pc` |
| --- | ---: | --- | --- |
| 1k through 8k | 3 | `0x10000008` | `0x0` |
| 9k | 238 | `0x80001cdc` | `0x800027c6` |
| 10k | 458 | `0x80001cdc` | `0x800027c6` |

这说明 direct path 不仅到达同一终点，而且复位等待、启动跳转和 CoreMark 初始执行的可见时序均未发生偏移。

日志：

```text
build/logs/xs_perf/no0360/no0300_baseline_functional_10k.log
build/logs/xs_perf/no0360/direct_state_read_functional_10k.log
```

## 4. 下一步

10k 已覆盖真实指令提交，但 CoreMark 只执行 458 条指令。下一步串行运行 baseline/direct 50k cycle，并按 10k
间隔比较全部 progress checkpoints；要求 guest cycles、`cycleCnt`、`instrCnt`、commit/trap PC 与 NO0300 严格
一致后，才允许进入性能夹测。
