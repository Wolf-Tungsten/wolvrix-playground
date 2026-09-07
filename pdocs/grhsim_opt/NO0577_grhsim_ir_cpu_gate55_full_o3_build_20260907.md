# NO0577 GrhSIM IR CPU Gate55 Full O3 Build

- 日期：2026-09-07
- 前置：[NO0574](./NO0574_grhsim_ir_cpu_bounded_functions_20260907.md)

## Completed Build

gate55 使用已有 `target-batch-count=0` 参数保留函数体积上限，不改变 phase、event、
activity 或 DPI 调度策略。完整生成、fresh-load 和 stable round-trip 已退出 0，
耗时 96.793 秒；输出目录为 `ptmp/xs_emit_make_gate55`。

随后经既有根 Makefile 完成全模型 O3 编译、归档和 harness 链接：

```sh
/usr/bin/time -v make --no-print-directory xs_wolf_grhsim_ir_build_emu \
  VM_BUILD_JOBS=8 GRHSIM_MODEL_CXXFLAGS='-std=c++20 -O3' WOLF_ENV_SOURCED=1 \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=ptmp/xs_emit_make_gate55 \
  TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" CCACHE_DIR="$PWD/ptmp/cpu_emit_ccache" \
  > ptmp/grhsim_gate55_full_o3_build.log 2>&1
```

- Exit status: 0。
- Wall time: 11:58.60；user time: 5262.52 秒。
- 最大报告 RSS: 935696 KiB。
- 模型包含 1 个 driver、170 个 init 和 6084 个 task，共 6255 个对象。
- 完整构建日志包含 6253 条 O3 编译命令；另两个 task 对象来自同目录此前的 O3 probe，
  不是复用旧 O0 模型对象。probe 日志为 `ptmp/grhsim_gate55_o3_task_probe.log`。
- 模型库：`ptmp/xs_emit_make_gate55/libgrhsim_SimTop.a`。
- 链接产物：`build/xs/grhsim-ir/emu/grhsim-compile/emu`；运行入口
  `build/xs/grhsim-ir/emu/emu` 已指向 gate55，不再是 gate53 O0 版本。

gate54 的大函数构建此前已依据实际编译耗时主动停止，退出 130，产物保留；
不是编译器失败。本记录补齐 NO0574 中“构建中”的后续结果，不覆盖历史记录。

## Scope

完整 O3 构建通过不等于仿真功能或性能通过。独立 1k 运行结果见
[NO0578](./NO0578_grhsim_ir_cpu_gate55_o3_runtime_20260907.md)。
XiangShan 10k/50k、完整多时钟 DUT 门禁及 50k 性能要求仍未完成。
