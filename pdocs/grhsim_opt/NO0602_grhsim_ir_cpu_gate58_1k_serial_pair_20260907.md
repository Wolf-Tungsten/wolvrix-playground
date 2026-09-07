# NO0602 GrhSIM IR CPU Gate58 1k Serial Pair

- 日期：2026-09-07
- 前置：[NO0601](./NO0601_grhsim_ir_cpu_gate58_full_o3_build_20260907.md)

## Runtime Samples

全部使用现有 `make run_xs_wolf_grhsim_ir_emu`，同 image/NEMU/seed 0、1000-cycle
上限、关闭波形、每千周期进度，日志与 TMPDIR 在 ptmp。构建和其他仿真均已结束，
下面三个进程串行运行，全部退出 0。

| Run | Explicit build root | Host time | Log under ptmp |
| --- | --- | ---: | --- |
| Gate58 first | ptmp/xs_gate58 | 36990 ms | grhsim_gate58_o3_1000.log |
| Gate57 paired baseline | build/xs/grhsim-ir | 40412 ms | grhsim_gate57_pair58_1000.log |
| Gate58 paired repeat | ptmp/xs_gate58 | 37784 ms | grhsim_gate58_pair57_1000.log |

对应 RUN_ID 为 `20260907_gate58_o3_1000`、`20260907_gate57_pair58_1000` 和
`20260907_gate58_pair57_1000`；其余参数为：

```sh
WOLF_ENV_SOURCED=1 XS_SIM_MAX_CYCLE=1000 XS_WAVEFORM=0 XS_WAVEFORM_PATH= \
XS_LOG_DIR="$PWD/ptmp" XS_PROGRESS_EVERY_CYCLES=1000 TMPDIR="$PWD/ptmp/cpu_emit_test_tmp"
```

三次都提交 3 条指令，cycleCnt=996、guest=1001，commit PC=0x10000008、trap PC=0。
NEMU 均在首条指令后启用，没有不一致报告；退出原因均为周期上限。

## Limited Positive Result

本轮相邻 A/B 为 40412 -> 37784 ms，时间下降约 6.5%。第一次 gate58 与既有 gate57
40631 ms 相比下降约 9%，但不能只挑较好的那个数字。这里没有 CPU 亲和性/频率控制
或足够重复次数，不宣称精细统计置信区间。

目前支持保留 direct commit 作为小幅改善候选；收益远不足以消除 NO0595 的整体
差距，同时必须承担 NO0601 的编译时间上升。它不是最终性能门禁通过。

## Continued Functional Gate

随后通过同一 run-only Makefile 入口启动独立 gate58 10000-cycle 窗口，显式
`XS_GRHSIM_IR_BUILD=ptmp/xs_gate58`，`RUN_ID=20260907_gate58_o3_10000`，日志
`ptmp/grhsim_gate58_o3_10000.log`。记录时仍在运行，将核对越过前 8k 后的提交推进。

gate58 的实际 50k 与配套性能仍未验证；旧 gate57 50k 证据不转移。DPI 策略始终不变。
