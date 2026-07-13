# NO0371 Direct state-read 4 KiB alignment 10k gate

日期：2026-07-12

## 1. 口径

承接 [NO0370](./NO0370_direct_state_read_align4k_build_gate_20260712.md)，对 direct aligned emu 运行与
[NO0360](./NO0360_simtop_direct_state_read_10k_functional_gate_20260712.md) 相同的 CoreMark/NEMU difftest：

```text
image: testcase/xiangshan/ready-to-run/coremark-2-iteration.bin
diff:  testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so
seed:  0
limit: -C 10000
EMU_PROGRESS_EVERY_CYCLES=1000
EMU_RUNTIME_PROFILE unset
```

命令先执行 `source env.sh`。本轮没有固定 CPU/NUMA/ASLR，只判功能，raw host time 不用于性能比较。

## 2. 结果

| Model | Exit | Guest cycles | Model cycles | `cycleCnt` | `instrCnt` | Terminal PC |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| direct aligned | 0 | 10,001 | 10,000 | 9,996 | 458 | `0x800027c6` |

结果与 NO0360 的 direct unaligned 严格一致。负向扫描没有发现 mismatch、assertion、abort、segmentation fault、
fatal/error 或 `input_fullpass_blocked`。

两份日志各有 10 个 1k progress checkpoints。去掉 `host_ms` 后逐字节比较无差异：1k 至 8k 均为 3 条指令、
`commit_pc=0x10000008`；9k/10k 分别为 238/458 条指令，`commit_pc=0x80001cdc`、
`trap_pc=0x800027c6`。

本轮 raw Host time 为 `9,922 ms`，unaligned 历史 10k 为 `10,120 ms`；两者未固定地址、CPU，也不是 A/B/A，
不形成性能结论。

## 3. 下一步与产物

direct aligned 已覆盖真实指令提交并通过 10k 功能门禁。下一步串行运行 50k，要求五个 10k checkpoints、
73,580 条指令终点和 PC 与 NO0361 unaligned direct 严格一致后，才进入 fixed-ASLR 性能夹测。

```text
build/logs/xs_perf/no0368/direct_align4k_functional_10k.log
```
