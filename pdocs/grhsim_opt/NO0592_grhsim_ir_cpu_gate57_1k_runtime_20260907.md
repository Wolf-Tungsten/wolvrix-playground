# NO0592 GrhSIM IR CPU Gate57 1k Runtime

- 日期：2026-09-07
- 前置：[NO0591](./NO0591_grhsim_ir_cpu_gate57_full_o3_build_20260907.md)

## Actual Runtime

通过既有 Makefile 的 run-only 入口运行 gate57，没有重新生成、安装或构建：

```sh
make --no-print-directory run_xs_wolf_grhsim_ir_emu WOLF_ENV_SOURCED=1 \
  XS_GRHSIM_IR_BUILD=build/xs/grhsim-ir XS_SIM_MAX_CYCLE=1000 \
  XS_WAVEFORM=0 XS_WAVEFORM_PATH= XS_LOG_DIR="$PWD/ptmp" \
  XS_PROGRESS_EVERY_CYCLES=1000 RUN_ID=20260907_gate57_o3_1000 \
  TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" > ptmp/grhsim_gate57_o3_1000.log 2>&1
```

进程退出 0，NEMU difftest 已在首条指令提交后启用，未报告不一致。

- host/model cycles: 1000。
- `instrCnt=3`、`cycleCnt=996`、guest cycles 1001。
- commit PC `0x10000008`、trap PC `0x0`。
- 退出原因：`EXCEEDING CYCLE/INSTR LIMIT`，不是程序完成。
- host time: 40631 ms。

## Short-Window Comparison

gate55 相同 1k 的既有无探针结果为 57958 ms，gate57 本次为 40631 ms，下降
约 29.9%。运行期间没有并行构建或其他由本任务启动的仿真；没有修改 event、DPI、
IR 或公开 ABI。这个单次跨轮短窗口对照支持保留 history batching 继续验证，
不构成重复测量的置信区间，更不等于与 legacy 的 50k 性能对齐。

## Next Gate Started

后续真实 IR 50k 已通过同一 Makefile 入口启动，其他参数相同，改为：

- `XS_SIM_MAX_CYCLE=50000`。
- `RUN_ID=20260907_gate57_o3_50000`。
- 日志 `ptmp/grhsim_gate57_o3_50000.log`。

将逐千周期对照 NO0587 的 legacy 功能轨迹，检查经过 10k 后的指令推进和 50k
终态。记录时仍在运行，不能计作 50k 通过；期间不并行构建或其他仿真。
