# NO0571 GrhSIM IR CPU Gate54 Full O3

- 日期：2026-09-07
- 前置：[NO0570](./NO0570_grhsim_ir_cpu_gate54_array_init_20260907.md)

## Build

复用 gate54 新目录中的两个已确认 O3 对象，通过既有根 Makefile build-only 入口启动
完整模型和 XiangShan harness 构建；未重新生成、未复用 gate53 O0 对象。

```sh
make --no-print-directory xs_wolf_grhsim_ir_build_emu VM_BUILD_JOBS=2 \
  GRHSIM_MODEL_CXXFLAGS='-std=c++20 -O3' WOLF_ENV_SOURCED=1 \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=ptmp/xs_emit_make_gate54 \
  TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" CCACHE_DIR="$PWD/ptmp/cpu_emit_ccache" \
  > ptmp/grhsim_gate54_full_o3_build.log 2>&1
```

日志确认 clang O3 参数，全部 170 个 init 对象已完成。00:34 开始编译 task_1/task_2，
源文件分别约 20/19 MiB；00:41 观测时编译会话仍存活，尚无 task 对象或错误。
此时不把长时间无日志视为退出，也未取消/重启或降低优化级别。

计划在完整链接后，通过 `run_xs_wolf_grhsim_ir_emu` 依次检查启动段、10k/50k NEMU
对照及实际指令推进，日志和临时文件继续放在项目 ptmp。当前未达到运行验收。

## Build Route Change

后续 task_2/task_1 分别在约 563/670 秒后完成，得到可用 O3 对象，而非编译器错误。
独立 gate55 使用原 pass 的 target-batch-count=0 将函数规模恢复到配置边界，并通过
全模型生成/round-trip、两个小 task 的 O3 编译（合计 0.82 秒）。根据此证据停止
gate54 正在编译的大函数路线，会话退出码 130；源文件、日志、已完成对象均保留。
这不是完整 gate54 构建通过，也不是编译失败或超时退出。

后续完整 O3 构建转向 gate55，详见
[NO0574](./NO0574_grhsim_ir_cpu_bounded_functions_20260907.md)。
