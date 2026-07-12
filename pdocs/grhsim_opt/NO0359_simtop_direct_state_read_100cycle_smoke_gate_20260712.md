# NO0359 SimTop direct state-read 100-cycle smoke gate

日期：2026-07-12

## 1. 口径

承接 [NO0358](./NO0358_simtop_direct_state_read_build_gate_20260712.md)，对 NO0300 baseline 与 direct state-read
emu 并行运行相同的 CoreMark/NEMU difftest 100-cycle smoke：

```text
image: testcase/xiangshan/ready-to-run/coremark-2-iteration.bin
diff:  testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so
seed:  0
limit: -C 100
EMU_PROGRESS_EVERY_CYCLES=100
EMU_RUNTIME_PROFILE unset
```

所有命令均先执行 `source env.sh`。本轮是功能检查，未固定 CPU、未控制 ASLR、两边并行运行，因此 host time
不用于性能结论。

## 2. 结果

| Model | Exit | Guest cycles | Model cycles at progress | `cycleCnt` | `instrCnt` | Commit/trap PC |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| NO0300 baseline | 0 | 101 | 100 | 96 | 0 | `0x0 / 0x0` |
| direct state-read | 0 | 101 | 100 | 96 | 0 | `0x0 / 0x0` |

两边均成功初始化 DUT memory、CoreMark image 和 NEMU reference，并在预期的 cycle limit 退出。关键功能字段逐项
一致。日志负向扫描均未发现：

```text
input_fullpass_blocked
difftest mismatch
assert / abort
segmentation fault
fatal / error
```

日志：

```text
build/logs/xs_perf/no0359/no0300_baseline_smoke_100.log
build/logs/xs_perf/no0359/direct_state_read_smoke_100.log
```

## 3. 覆盖边界与下一步

100 cycles 时 `instrCnt=0`、PC 仍为 0，因此本轮只验收模型构造、复位/初始化推进和 difftest 接线，不足以证明
direct path 在真实指令提交中的语义。下一步运行 baseline/direct 10k cycle，要求 guest cycles、`cycleCnt`、
`instrCnt`、terminal PC 和 progress checkpoint 全部一致；通过后再执行 50k 完整功能门禁。
