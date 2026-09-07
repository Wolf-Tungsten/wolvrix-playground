# NO0583 GrhSIM IR CPU Gate56 Full O3 Build

- 日期：2026-09-07
- 前置：[NO0580](./NO0580_grhsim_ir_cpu_unchanged_state_staging_20260907.md)

## Build Result

```sh
/usr/bin/time -v make --no-print-directory xs_wolf_grhsim_ir_build_emu \
  VM_BUILD_JOBS=8 GRHSIM_MODEL_CXXFLAGS='-std=c++20 -O3' WOLF_ENV_SOURCED=1 \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=ptmp/xs_emit_make_gate56 \
  TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" CCACHE_DIR="$PWD/ptmp/cpu_emit_ccache" \
  > ptmp/grhsim_gate56_full_o3_build.log 2>&1
```

终态退出 0，6255 条真实 O3 编译命令覆盖 driver、170 个 init、6084 个 task，
完整 archive 和 emu 链接成功。Wall 13:48.87，user 6132.73 秒，最大报告 RSS
915412 KiB。模型 archive 约 229 MiB，emu 约 199 MiB。

gate55 的 IR checkpoint 与 gate56 逐字节相同，batch 配置相同；本次是独立输出目录
的完整重编译，不混用旧对象。构建期间运行了多时钟测试和 HDLBits 复验，构建耗时
不作为生产性能证据。之后的运行等待这些工作全部结束。

实际 1k 测量及撤回决定见
[NO0584](./NO0584_grhsim_ir_cpu_unchanged_state_runtime_rejection_20260907.md)。
