# NO0372 Direct state-read 4 KiB alignment 50k gate

日期：2026-07-12

## 1. 口径

承接 [NO0371](./NO0371_direct_state_read_align4k_10k_gate_20260712.md)，对 direct aligned emu 串行运行
CoreMark/NEMU difftest 50k：

```text
image: testcase/xiangshan/ready-to-run/coremark-2-iteration.bin
diff:  testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so
seed:  0
limit: -C 50000
EMU_PROGRESS_EVERY_CYCLES=10000
EMU_RUNTIME_PROFILE unset
```

命令先执行 `source env.sh`。启动时全机 load 为 `10.34/10.52/8.99`（384 CPUs），足以作串行功能检查；
本轮没有固定 CPU、NUMA 或 ASLR，不使用 raw Host time 评价性能。

## 2. 终点门禁

| Model | Exit | Guest cycles | Model cycles | `cycleCnt` | `instrCnt` | Terminal PC |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| direct aligned | 0 | 50,001 | 50,000 | 49,996 | 73,580 | `0x80001312` |

结果与 [NO0361](./NO0361_simtop_direct_state_read_50k_functional_gate_20260712.md) 的 direct unaligned 严格
一致。负向扫描没有发现 mismatch、assertion、abort、segmentation fault、fatal/error 或
`input_fullpass_blocked`。

## 3. 检查点一致性

去掉 `host_ms` 后，五个 10k progress checkpoints 与 unaligned direct 逐字节一致：

| Cycle | `instr` | `commit_pc` | `trap_pc` |
| ---: | ---: | --- | --- |
| 10,000 | 458 | `0x80001cdc` | `0x800027c6` |
| 20,000 | 14,121 | `0x8000043a` | `0x80000440` |
| 30,000 | 27,809 | `0x8000043a` | `0x80000442` |
| 40,000 | 43,350 | `0x80000432` | `0x80000428` |
| 50,000 | 73,580 | `0x800012f8` | `0x80001312` |

本轮 raw Host time 为 `80,643 ms`，NO0361 unaligned 历史值为 `78,272 ms`。两轮不相邻、没有固定 CPU/地址，
也不是 A/B/A，因此这个 `+3.03%` 差异不形成 alignment 性能结论。

## 4. 下一步与产物

direct aligned 已通过 build、10k 和 50k 功能门禁。下一步按 NO0368 预声明口径检查全机 load 及 CPU138/330
空闲度，再执行 fixed-ASLR aligned NO0300 / aligned direct / aligned NO0300 五事件 A/B/A；三轮仍需重复验证
50k 功能终点。

```text
build/logs/xs_perf/no0368/direct_align4k_functional_50k.log
```
