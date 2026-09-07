# NO0570 GrhSIM IR CPU Gate54 Array Init

- 日期：2026-09-07
- 前置：[NO0569](./NO0569_grhsim_ir_cpu_array_initialization_20260907.md)

## Full-Model Generation

通过已有 `make xs_wolf_grhsim_ir`，从
`build/xs/grhsim/wolvrix_xs_pre_reg_to_mem.json` 恢复完整 XiangShan，应用全部八个 CPU
mapping pass 和新初始化 emitter。

- 新生成目录：`ptmp/xs_emit_make_gate54`，生成前不存在，未覆盖 gate53。
- 新 checkpoint：`ptmp/xs_ir_gate54.json`。
- Fresh-session round-trip：`ptmp/xs_ir_gate54_roundtrip.json`。
- 日志：`ptmp/grhsim_gate54_generation.log`，嵌套日志
  `ptmp/xs_wolf_grhsim_ir_20260907_gate54_array_init.log`。
- 总耗时 88,429 ms；C++ emission 11,438 ms，fresh load 8,866 ms。
- 命令退出 0，日志确认两份 checkpoint stable round-trip 完全一致。

真实 XiangShan 初值已通过严格范围、literal、覆盖预检，无 array 全量清零占位；此项
是全模型生成验证，不是 gate54 运行验证。

## Optimized Build Path

检查 `testcase/xiangshan/difftest/grhsim.mk` 确认默认
`GRHSIM_MODEL_CXXFLAGS=-std=c++20 -O3`。旧生成 Makefile 不跟踪 flags 变化，故不能
对 gate53 已有 O0 对象仅修改变量后声称完成优化构建。本阶段使用全新 gate54，定向
编译前确认其中无 `.o`。

通过生成 Makefile 的既有目标启动 driver 和 init_59 的 clang O3 编译：

```sh
make --no-print-directory -C ptmp/xs_emit_make_gate54 -j 2 \
  grhsim_SimTop.o grhsim_SimTop_init_59.o CXX=clang++ \
  CXXFLAGS='-std=c++20 -O3' \
  TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" CCACHE_DIR="$PWD/ptmp/cpu_emit_ccache" \
  > ptmp/grhsim_gate54_o3_driver_init.log 2>&1
```

启动日志已确认两个编译命令均使用 O3，尚待 object 和退出码确认。
该定向编译不等于完整 170 init/514 task 编译、archive/harness 链接或运行。

## Remaining Goal

继续复用 gate54 O3 对象完成全模型编译、默认栈启动、10k/50k NEMU 对照；随后按原计划
完成全量 HDLBits、多时钟及性能报告。此前 gate53 的 1k/三条指令证据仍只是启动段，
不能用它或本 gate 的生成成功替代 CoreMark 50k 验收。

## O3 定向编译结果

上述 Makefile 命令后续退出 0，两个对象均由本次 O3 命令新生成：driver object 约
5.0 MiB，init_59 object 约 24 KiB。init_59 的反汇编入口只保存五个寄存器，未见原先
MiB 级栈预留；反汇编保存于 `ptmp/grhsim_gate54_init59_o3_disassembly.log`。
这确认优化编译路径可用以及该初始化 TU 未重新引入大数组栈临时值，不表示所有 task
栈帧、完整优化模型运行或性能门禁已通过。

本阶段结束时没有遗留运行中的构建/仿真进程。gate54 已有的两个 O3 对象可由后续
`make xs_wolf_grhsim_ir_build_emu` 在相同 O3 配置下复用；模型 archive 尚未生成，
IR emu 入口仍是上一轮 gate53 O0 二进制，不能将其计时记为 gate54。
