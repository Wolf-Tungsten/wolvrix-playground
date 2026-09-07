# NO0594 GrhSIM IR CPU Gate57 50k Functional Gate

- 日期：2026-09-07
- 前置：[NO0593](./NO0593_grhsim_ir_cpu_gate57_20k_checkpoint_20260907.md)

## Actual IR 50k Completed

既有 gate57 O3 模型通过项目 run-only Makefile 入口实际执行完整 50000-cycle
XiangShan CoreMark 窗口，进程已退出 0；没有缩短窗口或用 legacy 运行替代 IR。

```sh
make --no-print-directory run_xs_wolf_grhsim_ir_emu WOLF_ENV_SOURCED=1 \
  XS_GRHSIM_IR_BUILD=build/xs/grhsim-ir XS_SIM_MAX_CYCLE=50000 \
  XS_WAVEFORM=0 XS_WAVEFORM_PATH= XS_LOG_DIR="$PWD/ptmp" \
  XS_PROGRESS_EVERY_CYCLES=1000 RUN_ID=20260907_gate57_o3_50000 \
  TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" > ptmp/grhsim_gate57_o3_50000.log 2>&1
```

NEMU difftest 在首条指令提交后启用，并持续运行到周期上限。未报告 NEMU 不一致、
断言、BAD TRAP 或其他运行错误。运行期间没有并行构建或其他本任务启动的仿真，
也未修改模型或待测二进制。

| Terminal Field | Value |
| --- | --- |
| Host/model cycles | 50000 |
| Instructions | 73580 |
| cycleCnt | 49996 |
| Guest cycles | 50001 |
| IPC | 1.471718 |
| Commit PC | 0x800012f8 |
| Trap/limit PC | 0x80001312 |
| Seed | 0 |
| Host time | 2073729 ms |
| Exit | 0, EXCEEDING CYCLE/INSTR LIMIT |

## Reference Comparison

对照 [NO0587](./NO0587_grhsim_legacy_50k_functional_reference_20260907.md) 的
`ptmp/grhsim_legacy_50000_reference.log`，独立抽取两路进度字段，剔除 host_ms
和 ANSI 颜色。检查不是只看最后一条：

- reference 恰好 50 个采样，IR 恰好 50 个采样。
- IR host_cycles 必须严格按 1000、2000、...、50000 连续递增，拒绝缺失或重复。
- 每个采样的 host/model cycles、instr、commit PC、trap PC 和 core 全部相同。
- 周期上限退出行、instrCnt/cycleCnt/IPC 行、Seed/Guest-cycle 行三项全部相同。
- 检查输出：`reference_samples=50 ordered_matching_samples=50 terminal_checks=3 failure=0`。

抽取在任意行位置识别进度标记，覆盖 guest 启动文本与标记同一行的 9k-12k。
10k 检查点也匹配 458 条指令，但它是本次 50k 运行的前缀，不伪称独立 10k 进程。
此前独立 gate55 10k 终态仍见 NO0586。

## Completion Boundary

本记录补齐实际 IR 50k/NEMU 功能窗口，不是整个 CoreMark 程序完成或全状态波形
等价证明。DPI 保持 compute + 可选 event + 真实调用，void call 未删除。

CPU 专项、多时钟 DUT 和 history 反例验证见 NO0588；完整 HDLBits 162/162 见
NO0590。gate57 的功能证据支持保留 history batching，但 2073729 ms 显示性能
仍有显著差距，不能宣布规划整体完成。

IR 退出后已串行启动既有 legacy 50k 的配套测量，日志为
`ptmp/grhsim_legacy_50000_serial_gate57.log`。性能结论单独归档，不沿用 NO0587
曾与 IR 10k 并行的耗时作为正式配套基线。50k 不差于 legacy 5% 的要求仍未通过。
