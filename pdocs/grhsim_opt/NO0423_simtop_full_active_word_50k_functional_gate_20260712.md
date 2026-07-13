# NO0423 SimTop full active-word 50k functional gate

日期：2026-07-12

## 1. Configuration

承接 [NO0422](./NO0422_simtop_full_active_word_10k_functional_gate_20260712.md)，运行：

```text
image: testcase/xiangshan/ready-to-run/coremark-2-iteration.bin
diff:  testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so
seed:  0
limit: -C 50000
EMU_PROGRESS_EVERY_CYCLES=10000
EMU_RUNTIME_PROFILE unset
```

所有命令均先 `source env.sh`。本轮只判功能，未固定 CPU/ASLR，host time 不作性能结论。日志：

```text
build/logs/xs_perf/no0423/full_word_functional_50k.log
```

## 2. Terminal gate

执行 exit 0 并完成 73,580 条 guest instruction 的 NEMU difftest：

```text
guest cycles=50,001
model cycles=50,000
cycleCnt=49,996
instrCnt=73,580
terminal PC=0x80001312
```

负向扫描 0 命中，包括 `input_fullpass_blocked`、difftest mismatch、assert/abort、segmentation fault 和
fatal/error。

## 3. Checkpoint gate

candidate 与 `build/logs/xs_perf/no0361/direct_state_read_functional_50k.log` 各有 5 个 10k checkpoints。
抽取 `[EMU_PROGRESS]` 并去掉 `host_ms` 后，5/5 逐字节一致：

| cycle | instr | commit PC | trap PC |
| ---: | ---: | --- | --- |
| 10,000 | 458 | `0x80001cdc` | `0x800027c6` |
| 20,000 | 14,121 | `0x8000043a` | `0x80000440` |
| 30,000 | 27,809 | `0x8000043a` | `0x80000442` |
| 40,000 | 43,350 | `0x80000432` | `0x80000428` |
| 50,000 | 73,580 | `0x800012f8` | `0x80001312` |

## 4. Conclusion and next gate

100-cycle、10k 和 50k 三层 SimTop 功能门禁全部通过，且没有重现 `input_fullpass_blocked`。下一步先单独
记录 fixed-ASLR paired runtime 计划，再选择安静的同 NUMA CPU，执行 NO0357/full-word/NO0357 A/B/A。
若机器负载或目标 sibling 不稳定，则拒绝样本或重跑 baseline，不用裸 host time 评价性能。
