# NO0361 SimTop direct state-read 50k functional gate

日期：2026-07-12

## 1. 口径

承接 [NO0360](./NO0360_simtop_direct_state_read_10k_functional_gate_20260712.md)，对 NO0300 baseline 与 direct
state-read emu 串行运行相同的 CoreMark/NEMU difftest 50k cycle：

```text
image: testcase/xiangshan/ready-to-run/coremark-2-iteration.bin
diff:  testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so
seed:  0
limit: -C 50000
EMU_PROGRESS_EVERY_CYCLES=10000
EMU_RUNTIME_PROFILE unset
```

所有命令均先执行 `source env.sh`。两边串行执行以避免模型间资源争用，但本轮仍未固定 CPU、NUMA 和 PIE load
base，也未做 A/B/A，因此只判功能。

## 2. 终点门禁

| Model | Exit | Guest cycles | `cycleCnt` | `instrCnt` | Terminal PC | Result |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| NO0300 baseline | 0 | 50,001 | 49,996 | 73,580 | `0x80001312` | PASS |
| direct state-read | 0 | 50,001 | 49,996 | 73,580 | `0x80001312` | PASS |

两边都完成 73,580 条指令的 NEMU difftest，功能终点与 NO0300 历史可信结果一致。负向扫描未发现 difftest
mismatch、assertion、abort、segmentation fault、fatal/error 或 `input_fullpass_blocked`。

## 3. 逐检查点一致性

去掉 `host_ms` 后，五个 10k progress checkpoints 以及 cycle-limit/终点行逐字节一致：

| Cycle | `instr` | `commit_pc` | `trap_pc` |
| ---: | ---: | --- | --- |
| 10,000 | 458 | `0x80001cdc` | `0x800027c6` |
| 20,000 | 14,121 | `0x8000043a` | `0x80000440` |
| 30,000 | 27,809 | `0x8000043a` | `0x80000442` |
| 40,000 | 43,350 | `0x80000432` | `0x80000428` |
| 50,000 | 73,580 | `0x800012f8` | `0x80001312` |

这覆盖了 CoreMark 从启动到稳定执行的多个阶段，direct state-read 没有改变可见模拟时序或指令轨迹。

## 4. 非受控 host time

串行 raw host time 为：

```text
NO0300 baseline     84,981 ms
direct state-read   78,272 ms
raw delta           -7.89%
```

运行前/后 load average 为 `6.75/10.63/10.53` 和 `2.74/6.67/8.97`，相对 384 个逻辑 CPU 都不高；但两个
PIE binary 的 CPU、NUMA 和 load base 未固定，且 baseline 只有一次。`-7.89%` 只作为后续受控实验的方向性观测，
不是可接受的性能结论。

日志：

```text
build/logs/xs_perf/no0361/no0300_baseline_functional_50k.log
build/logs/xs_perf/no0361/direct_state_read_functional_50k.log
```

## 5. 下一步

fresh SimTop 已依次通过 build、100-cycle、10k 和 50k 功能门禁。下一步先记录 fixed-ASLR 性能方案，再检查
目标 CPU 和同 NUMA node 的负载，以 NO0300/direct/NO0300 串行夹测采集 cycles、instructions、frontend/backend
stall 等 PMU；baseline spread 必须受控，且所有三轮功能终点仍需一致。
