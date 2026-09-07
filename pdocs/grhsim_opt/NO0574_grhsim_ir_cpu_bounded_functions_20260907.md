# NO0574 GrhSIM IR CPU Bounded Functions

- 日期：2026-09-07
- 前置：[NO0571](./NO0571_grhsim_ir_cpu_gate54_full_o3_20260907.md)

## Measured Compile Cost

gate54 的 task_1/task_2 于 00:34:03 开始 clang O3 编译。task_2 对象于 00:43:26
完成（约 563 秒，2,804,024 bytes），task_1 于 00:45:13 完成（约 670 秒，3,713,520
bytes）。这是实际完成对象的观测，不是将日志静默当作编译失败。

两份源文件约 20/19 MiB，task_1 单方法约 309k 行。pack-emit-functions 的默认
target_count=64 沿用 legacy 的动态扩大规则：effective max 为配置 max 与
total/target_count 的较大者。原有 2048 ops / 8192 estimated lines 因此不构成
大图上的硬上限。当前 raw-buffer emitter 形态下的大函数 O3 优化成本需要实测约束。

## Gate55 Probe

开放既有 pass 的 target_count 参数到生产 Makefile/script：
`XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT` 对应 `--cpu-target-batch-count`。
缺省不传参数，保持默认行为；显式 0 关闭按目标 batch 数动态放大，仍使用原有
2048 ops/8192 estimated lines 打包边界。word/supernode 不被拆开，模型逻辑、活动位
和 compute/commit 语义不变；更细函数的调用成本是否影响运行性能另行验证。

gate55 通过原 Makefile 入口，从同一 flat GRH 重新生成，输出为
`ptmp/xs_emit_make_gate55`、`ptmp/xs_ir_gate55.json`、`ptmp/xs_ir_gate55_roundtrip.json`，
日志 `ptmp/grhsim_gate55_generation.log`。本次包含 NO0572/NO0573 的已测试修复，
没有降低优化级别，也没有复用不同 mapping 的对象。

此时 gate54 构建仍保留。先要求 gate55 生成/fresh-load/round-trip 与小函数 O3
编译证据，再决定是否切换完整构建；不得把定向编译或配置变化记为 50k 完成。

## Gate55 Evidence and Full Build

gate55 全模型生成、fresh-session load、stable round-trip 退出 0，总计 96,793 ms。
生成 6,084 个 task 文件，首两个约 280/314 KiB，最大 task 文件约 3.4 MiB。
通过生成 Makefile 编译 task_1/task_2，clang O3 两对象成功，合计 wall 0.82 秒、
user 1.48 秒、峰值 RSS 138,588 KiB。日志 `ptmp/grhsim_gate55_o3_task_probe.log`。
两种配置的单 task 包含工作量不同，不能把各自耗时之比称为同工作量加速比。

该结果支持选择较小函数作为完整优化构建路线。gate54 构建主动停止，退出 130，
未清理其产物。随后启动：

```sh
/usr/bin/time -v make --no-print-directory xs_wolf_grhsim_ir_build_emu \
  VM_BUILD_JOBS=8 GRHSIM_MODEL_CXXFLAGS='-std=c++20 -O3' WOLF_ENV_SOURCED=1 \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=ptmp/xs_emit_make_gate55 \
  TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" CCACHE_DIR="$PWD/ptmp/cpu_emit_ccache" \
  > ptmp/grhsim_gate55_full_o3_build.log 2>&1
```

日志已推进到 task_293。此时模型 archive/harness 链接尚未完成，不能运行旧 emu
冒充 gate55；8-way 编译只用于构建，后续运行性能对照不与构建并发。
