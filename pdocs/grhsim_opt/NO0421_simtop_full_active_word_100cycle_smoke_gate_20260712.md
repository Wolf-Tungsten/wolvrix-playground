# NO0421 SimTop full active-word 100-cycle smoke gate

日期：2026-07-12

## 1. Configuration

承接 [NO0420](./NO0420_simtop_full_active_word_build_gate_20260712.md)，运行 candidate O3 emu：

```text
image: testcase/xiangshan/ready-to-run/coremark-2-iteration.bin
diff:  testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so
seed:  0
limit: -C 100
EMU_PROGRESS_EVERY_CYCLES=100
EMU_RUNTIME_PROFILE unset
```

所有命令均先 `source env.sh`。本轮不固定 CPU/ASLR，host time 不作性能结论。日志：

```text
build/logs/xs_perf/no0421/full_word_smoke_100.log
```

## 2. Result

执行 exit 0，终点与 NO0359 的 NO0300/direct 结果逐项一致：

```text
guest cycles=101
model/host progress cycles=100/100
cycleCnt=96
instrCnt=0
commit_pc=0x0
trap_pc=0x0
```

负向扫描 0 命中：

```text
input_fullpass_blocked
difftest mismatch
assert / abort
segmentation fault
fatal / error
```

## 3. Coverage and next gate

本轮只覆盖模型构造、memory/image/reference 初始化和 reset 推进，尚未提交 guest 指令。下一步运行 10k
CoreMark/NEMU difftest，要求 10 个 1k progress checkpoints 以及 guest cycles、instruction count、terminal PC
与 NO0360 对齐；通过后再进入 50k。
