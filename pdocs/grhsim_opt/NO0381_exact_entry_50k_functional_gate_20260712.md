# NO0381 Exact-entry 50k functional gate

日期：2026-07-12

## 1. 口径

承接 [NO0380](./NO0380_exact_entry_10k_functional_gate_20260712.md)，串行运行 exact-entry baseline/direct 的
CoreMark + NEMU difftest 50k：

```text
image: testcase/xiangshan/ready-to-run/coremark-2-iteration.bin
diff:  testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so
seed:  0
limit: -C 50000
EMU_PROGRESS_EVERY_CYCLES=10000
EMU_RUNTIME_PROFILE unset
```

命令先执行 `source env.sh`。本轮只判功能，没有固定 CPU/NUMA/ASLR；baseline 完成后才运行 direct，raw host time
不形成性能结论。

## 2. 终点门禁

| Model | Exit | Guest/model cycles | `cycleCnt` | `instrCnt` | Commit/trap PC |
| --- | ---: | --- | ---: | ---: | --- |
| NO0300 exact-entry | 0 | 50,001 / 50,000 | 49,996 | 73,580 | `0x800012f8` / `0x80001312` |
| Direct exact-entry | 0 | 50,001 / 50,000 | 49,996 | 73,580 | `0x800012f8` / `0x80001312` |

两侧均完成真实 CoreMark 执行并保持 NEMU difftest。负向扫描未发现 mismatch、assertion、abort、segmentation
fault、fatal 或 `input_fullpass_blocked`。

## 3. 检查点一致性

两份日志各有 5 个 10k checkpoints。去掉 `host_ms` 后：

- exact-entry baseline/direct 逐字节一致；
- 与 [NO0361](./NO0361_simtop_direct_state_read_50k_functional_gate_20260712.md) 的未 padding NO0300 baseline 逐字节
  一致；
- 50k 终点均为 73,580 instructions 和同一 commit/trap PC。

统一 harness、inter-entry padding 和 baseline tail 都没有改变 50k 范围内的可见功能或 cycle 时序。

日志：

```text
build/logs/xs_perf/no0381/baseline_exact_entry_50k.log
build/logs/xs_perf/no0381/direct_exact_entry_50k.log
```

## 4. 下一步

exact-entry 两侧已通过 10k/50k 功能门禁。下一步检查 CPU/NUMA 负载，再执行 CPU138、NUMA1、fixed-ASLR 的
baseline/direct/baseline 五事件 A/B/A；以 baseline cycles spread `<=1%` 和五事件 100% 调度为硬门禁，判断入口
严格同址后 direct 的实际 cycles 方向。
