# NO0584 GrhSIM IR CPU Unchanged State Runtime Rejection

- 日期：2026-09-07
- 前置：[NO0583](./NO0583_grhsim_ir_cpu_gate56_full_o3_build_20260907.md)

## Runtime Evidence

所有构建及其他回归结束后，通过既有 `make run_xs_wolf_grhsim_ir_emu` 运行 gate56：
`XS_SIM_MAX_CYCLE=1000`、waveform off、相同 image/NEMU/seed，进度间隔 100，
`XS_LOG_DIR=$PWD/ptmp`，`RUN_ID=20260907_gate56_o3_1000`。
日志为 `ptmp/grhsim_gate56_o3_1000.log`，进程已确认退出 0。

- 第一条指令仍在 cycle 600 的采样中出现，cycle 700 起为 3 条。
- 终态 `instrCnt=3`、`cycleCnt=996`、guest cycles 1001，没有 NEMU 报告不一致。
- Host time 68502 ms，稳定段约 65 ms/cycle。
- 相比 NO0578 的 gate55 57958 ms 历史同配置启动段，耗时增加约 18.2%。
- 生成 archive 从约 206 MiB 增至 229 MiB，emu 从约 177 MiB 增至 199 MiB。

这不是配套 50k 性能门禁，但足以拒绝把本次逐写口检查作为已获益的默认优化。
NO0579 的无效 pending 计数仍是真实证据；减少此计数不保证总耗时降低。
额外比较/分支和代码体积是下一步需区分的候选，本阶段没有 profile 证明其各自占比。

## Rejected Implementation

已通过局部反向补丁完整撤回 NO0580 的 `cpu_store`、event-history 前置比较、
标量 masked-write 前置比较以及新增保留成员名。恢复原 shadow/pending/publish
实现，不保留一个默认变慢的“优化”。gate56 生成源码、库、可执行文件及日志保留为
实验原始证据，不能继续当作当前推荐运行版本。

新增 `cancelled` 覆盖顺序、重复 eval、CDC 和双 RAM 测试保留；后端文档描述恢复为
真实的当前实现。撤回后 `make test_grhsim_cpu_emit` 再次退出 0，24.89 秒，全部
原有及新增样本通过。日志 `ptmp/grhsim_cpu_staging_restore_test.log`，完整结果
`ptmp/grhsim_cpu_staging_restore_test_details.log`。

## Baseline Selection

为避免把根 emu 的 gate56 链接产物错当 gate55，在新的项目内 harness 目录通过原
Makefile 重新链接现有 gate55 O3 模型库：

```sh
make --no-print-directory xs_wolf_grhsim_ir_build_emu \
  VM_BUILD_JOBS=8 GRHSIM_MODEL_CXXFLAGS='-std=c++20 -O3' WOLF_ENV_SOURCED=1 \
  XS_GRHSIM_IR_BUILD=ptmp/xs_gate55_baseline \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=ptmp/xs_emit_make_gate55 \
  TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" CCACHE_DIR="$PWD/ptmp/cpu_emit_ccache" \
  > ptmp/grhsim_gate55_baseline_harness.log 2>&1
```

该构建退出 0，只编译 harness 并链接原 gate55 库，没有重新生成/编译 6255 个模型
对象。运行入口为 `ptmp/xs_gate55_baseline/emu/emu`，后续显式传入相同
`XS_GRHSIM_IR_BUILD`，不依赖旧默认目录的时间戳或链接选择。
下一步推进真实 10k NEMU 功能窗口；50k 和性能验收仍未完成。
