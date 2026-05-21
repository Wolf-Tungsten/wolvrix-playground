# NO0103: Per-Entry Commit Scalar Build 与 20k 无效运行

Date: 2026-05-21

## 背景

`NO0102` 已确认 per-entry commit scalar activation 在 XiangShan fresh emit 的结构 gate 通过。本轮复用 `NO0102` 已生成的 C++ 产物，做 build 与带 difftest 的 CoreMark 20k 验证。

本轮没有再次 fresh emit。

## Build

复用模型目录：

```text
tmp/no0102_xs_per_entry_commit_scalar_diag/grhsim_emit
```

先编译 `libgrhsim_SimTop.a`：

```sh
/usr/bin/time -p make -C tmp/no0102_xs_per_entry_commit_scalar_diag/grhsim_emit -j32 CXX=clang++
```

结果：

```text
real 108.91
user 3343.61
sys 56.22
libgrhsim_SimTop.a 129M
grhsim_SimTop.hpp.pch 15M
```

随后链接 difftest emu：

```sh
/usr/bin/time -p make -C testcase/xiangshan/difftest emu \
  NOOP_HOME=/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan \
  BUILD_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/no0103_per_entry_commit_scalar_build_runtime/noop_home_build \
  GEN_CSRC_DIR=/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/build/generated-src \
  NUM_CORES=1 WITH_CHISELDB=0 WITH_CONSTANTIN=0 \
  GRHSIM=1 \
  GRHSIM_MODEL_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/no0102_xs_per_entry_commit_scalar_diag/grhsim_emit \
  WOLVRIX_GRHSIM_WAVEFORM=0 \
  CXX=clang++
```

结果：

```text
real 7.45
tmp/no0103_per_entry_commit_scalar_build_runtime/noop_home_build/grhsim-compile/emu 118M
```

## 20k Runtime

命令口径：

```sh
cd tmp/no0103_per_entry_commit_scalar_build_runtime/noop_home_build

EMU_PROGRESS_EVERY_CYCLES=5000 /usr/bin/time -p ./grhsim-compile/emu \
  -i /home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff /home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 20000
```

结果无效：

```text
[EMU_PROGRESS] host_cycles=5000 model_cycles=5000 instr=0 commit_pc=0x0 trap_pc=0x0 core=0 host_ms=4994
[EMU_PROGRESS] host_cycles=10000 model_cycles=10000 instr=0 commit_pc=0x0 trap_pc=0x0 core=0 host_ms=9696
[EMU_PROGRESS] host_cycles=15000 model_cycles=15000 instr=0 commit_pc=0x0 trap_pc=0x0 core=0 host_ms=14420
[EMU_PROGRESS] host_cycles=20000 model_cycles=20000 instr=0 commit_pc=0x0 trap_pc=0x0 core=0 host_ms=19126
Core 0: EXCEEDING CYCLE/INSTR LIMIT at pc = 0x0
Host time spent: 19127ms
real 19.13
```

该结果不能作为性能收益数据，因为模型没有提交任何指令。

## 对照

用现有可运行基线 `build/xs/grhsim/grhsim-compile/emu` 跑同一条 20k 命令：

```text
The first instruction of core 0 has commited. Difftest enabled.
[EMU_PROGRESS] host_cycles=5000 model_cycles=5000 instr=3 commit_pc=0x10000008 trap_pc=0x0 core=0 host_ms=17565
[EMU_PROGRESS] host_cycles=10000 model_cycles=10000 instr=458 commit_pc=0x80001cdc trap_pc=0x800027c6 core=0 host_ms=38193
[EMU_PROGRESS] host_cycles=15000 model_cycles=15000 instr=5532 commit_pc=0x80000130 trap_pc=0x8000014e core=0 host_ms=79168
[EMU_PROGRESS] host_cycles=20000 model_cycles=20000 instr=14121 commit_pc=0x8000043a trap_pc=0x80000440 core=0 host_ms=130104
Host time spent: 130112ms
real 130.12
```

这说明运行命令与 difftest 口径本身有效；问题在本轮新生成的 per-entry 模型或其 emit 参数，不是运行方式。

## 判定

- Build gate 通过：`libgrhsim_SimTop.a` 和 difftest `emu` 均成功生成；
- Runtime gate 未通过：20k 带 difftest 运行没有提交指令，`pc=0x0`；
- 因此不能继续跑 50k，也不能把 `19.13s` 解读为提速；
- 下一步应先诊断功能启动问题，重点查 per-entry commit scalar table 是否破坏 reset/clock 相关 commit 写入或 activation。

## 下一步

建议下一篇 `NO0104` 做最小功能诊断：

- 对比 `NO0102` per-entry model 与当前可运行 baseline model 的 reset/clock/event activation；
- 在 per-entry 模型上插桩 `difftest_step`、`difftest_exit`、`reset`、`clock`、首条 commit 相关信号；
- 必要时只关闭 `WOLVRIX_XS_GRHSIM_EMIT_PER_ENTRY_COMMIT_SCALAR_ACTIVATIONS` 做同参数 emit 对照，确认是否是该 codegen 选项引入功能问题；
- 在功能恢复前不做 50k runtime 或 perf。

本轮结束后检查进程，无 `wolvrix_xs_grhsim.py`、`grhsim-compile/emu`、`clang++`、`make`、`perf record` 遗留进程。
