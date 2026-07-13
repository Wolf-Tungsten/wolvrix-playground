# NO0380 Exact-entry 10k functional gate

日期：2026-07-12

## 1. 口径

承接 [NO0379](./NO0379_exact_entry_explicit_link_build_gate_20260712.md)，并行运行 exact-entry baseline/direct 的
CoreMark + NEMU difftest 10k：

```text
image: testcase/xiangshan/ready-to-run/coremark-2-iteration.bin
diff:  testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so
seed:  0
limit: -C 10000
EMU_PROGRESS_EVERY_CYCLES=1000
EMU_RUNTIME_PROFILE unset
```

命令先执行 `source env.sh`。本轮未固定 CPU/NUMA/ASLR，两个进程并行，只判功能；raw host time 不形成性能结论。

## 2. 结果

| Model | Exit | Guest/model cycles | `cycleCnt` | `instrCnt` | Terminal PC |
| --- | ---: | --- | ---: | ---: | --- |
| NO0300 exact-entry | 0 | 10,001 / 10,000 | 9,996 | 458 | `0x800027c6` |
| Direct exact-entry | 0 | 10,001 / 10,000 | 9,996 | 458 | `0x800027c6` |

两侧均提交首条指令并启用 difftest。负向扫描未发现 mismatch、assertion、abort、segmentation fault、fatal 或
`input_fullpass_blocked`。

两份日志各有 10 个 1k progress checkpoints；去掉 `host_ms` 后两侧逐字节一致，并且与
[NO0360](./NO0360_simtop_direct_state_read_10k_functional_gate_20260712.md) 的未 padding NO0300 baseline 逐字节一致。
因此 padding 和统一 harness 没有改变复位等待、启动跳转或 CoreMark 初始可见时序。

日志：

```text
build/logs/xs_perf/no0380/baseline_exact_entry_10k.log
build/logs/xs_perf/no0380/direct_exact_entry_10k.log
```

## 3. 下一步

10k 功能门禁通过，但只覆盖 458 条 guest instructions。下一步串行运行两侧 50k，比较五个 10k checkpoints 和
73,580 条指令终点；通过后才进入 fixed-ASLR A/B/A。
