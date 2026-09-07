# NO0603 GrhSIM IR CPU Gate58 10k Functional Gate

- 日期：2026-09-07
- 前置：[NO0602](./NO0602_grhsim_ir_cpu_gate58_1k_serial_pair_20260907.md)

## Independent 10k Run

direct commit 的 gate58 通过既有 run-only Makefile 入口独立运行 10000 cycles，
进程已退出 0。没有在运行期间修改模型、重建或并行执行其他仿真。

```sh
make --no-print-directory run_xs_wolf_grhsim_ir_emu WOLF_ENV_SOURCED=1 \
  XS_GRHSIM_IR_BUILD=ptmp/xs_gate58 XS_SIM_MAX_CYCLE=10000 \
  XS_WAVEFORM=0 XS_WAVEFORM_PATH= XS_LOG_DIR="$PWD/ptmp" \
  XS_PROGRESS_EVERY_CYCLES=1000 RUN_ID=20260907_gate58_o3_10000 \
  TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" > ptmp/grhsim_gate58_o3_10000.log 2>&1
```

| Terminal Field | Value |
| --- | --- |
| Host/model cycles | 10000 |
| Instructions | 458 |
| cycleCnt | 9996 |
| Guest cycles | 10001 |
| IPC | 0.045818 |
| Commit PC | 0x80001cdc |
| Limit/trap PC | 0x800027c6 |
| Host time | 358864 ms |
| Exit reason | EXCEEDING CYCLE/INSTR LIMIT |

NEMU 在首条指令后启用，未报告不一致、断言或 BAD TRAP。9k 为 238 条指令，
10k 为 458 条，已越过前 8k 的低活动启动段，输出 CoreMark 启动文本。

## Reference Check

与 NO0586 的 `ptmp/grhsim_legacy_o3_10000.log` 比较，剔除 host_ms/ANSI 颜色，
十个采样必须严格按 1000..10000 连续出现，全部周期/指令/PC/core 字段相同。
另核对周期上限退出行、instrCnt/cycleCnt/IPC 行、Seed/Guest-cycle 行，均一致。

检查结果：`reference_samples=10 ordered_matching_samples=10 terminal_checks=3 failure=0`。
处理了 guest 文本与进度标记同一行的情形，没有漏掉 9k/10k。

## Remaining Gates

本轮证据是 gate58 的独立 10k 功能通过，不能替代其 50k。当前 direct commit
已有全套 CPU、非 E/DPI 旧值反例、三个多时钟 DUT、162/162 HDLBits 和 10k；
新实现的实际 50k 与配套性能仍未验证。gate57 的已完成 50k 基线继续保留。

相邻 1k A/B 仅改善约 6.5%，并伴随编译时间增加，距离最终性能要求仍很远。
后续需要继续定位 compute/commit 成本，所有候选最终仍须完成 50k 及性能验收；
不以小幅加速宣布目标完成。当前全部构建/安装/运行进程已终态结束，DPI 策略不变。
