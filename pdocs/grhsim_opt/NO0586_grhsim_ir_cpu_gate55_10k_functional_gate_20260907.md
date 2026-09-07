# NO0586 GrhSIM IR CPU Gate55 10k Functional Gate

- 日期：2026-09-07
- 前置：[NO0584](./NO0584_grhsim_ir_cpu_unchanged_state_runtime_rejection_20260907.md)

## Actual IR Runtime

使用已去除临时探针的 gate55 O3 模型及独立 harness，显式选择路径，避免运行默认
目录中保留的 gate56 负结果产物：

```sh
make --no-print-directory run_xs_wolf_grhsim_ir_emu WOLF_ENV_SOURCED=1 \
  XS_GRHSIM_IR_BUILD=ptmp/xs_gate55_baseline XS_SIM_MAX_CYCLE=10000 \
  XS_WAVEFORM=0 XS_WAVEFORM_PATH= XS_LOG_DIR="$PWD/ptmp" \
  XS_PROGRESS_EVERY_CYCLES=1000 RUN_ID=20260907_gate55_o3_10000 \
  TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" > ptmp/grhsim_gate55_o3_10000.log 2>&1
```

终态退出 0。RAM/image/NEMU 初始化完成，首条指令提交后启用 difftest；运行越过
启动窗口，输出 `Running CoreM` 前缀，未报告断言或 NEMU 不一致。

- host/model cycles: 10000。
- `instrCnt=458`、`cycleCnt=9996`、guest cycles 10001。
- 最后 commit PC `0x80001cdc`、trap PC `0x800027c6`。
- 退出原因：`EXCEEDING CYCLE/INSTR LIMIT`，不是 CoreMark 程序完成。
- 报告 host time: 556818 ms。

## Legacy Progress Comparison

既有 legacy 二进制经 `make run_xs_wolf_grhsim_emu` 在同 image/NEMU/seed、waveform
关闭条件下独立启动 10000-cycle 窗口，显式 `XS_GRHSIM_BUILD=build/xs/grhsim`，
`RUN_ID=20260907_legacy_o3_10000`。日志 `ptmp/grhsim_legacy_o3_10000.log`，退出 0。

| Host/Model Cycles | Both: Instructions | Both: Commit PC | Both: Trap PC |
| --- | --- | --- | --- |
| 1000-8000 | 3 | 0x10000008 | 0x0 |
| 9000 | 238 | 0x80001cdc | 0x800027c6 |
| 10000 | 458 | 0x80001cdc | 0x800027c6 |

对日志抽取十个 `[EMU_PROGRESS]` 采样行并去除 host_ms 后执行 diff，连同最终
instrCnt/cycleCnt/IPC 和 guest-cycle 行完全一致，diff 退出 0。因此长期停留在前三条
指令符合本 image 的 legacy 启动窗口，不能单独判为 IR 卡死。

## Coverage Boundary

本记录补齐实际 10k XiangShan/NEMU 功能窗口，不是全状态波形等价证明，也不替代
50k 门禁。legacy 功能参考在 IR 运行期间并行执行，报告耗时不构成正式性能 A/B；
已有隔离 1k 证据仍明确显示性能差距巨大。

恢复原 state staging 后的 `make py_install` 也已退出 0，日志为
`ptmp/grhsim_cpu_staging_restore_install.log`。当前源代码及已安装包不含被拒绝的
cpu_store 优化；新增三 DUT 多时钟回归继续保留。

后续候选约束见 [NO0585](./NO0585_grhsim_ir_cpu_history_batch_design_20260907.md)，
但候选尚未实现。IR 50k 和配套性能验收仍未完成，目标保持未完成。
