# NO0595 GrhSIM IR CPU Gate57 50k Serial Performance

- 日期：2026-09-07
- 前置：[NO0594](./NO0594_grhsim_ir_cpu_gate57_50k_functional_gate_20260907.md)

## Paired Runtime Measurement

先完成 gate57 IR 50k，再启动既有 legacy 二进制的相同 50k 窗口；两次不重叠，
期间没有本任务发起的并行构建或其他仿真。两路使用同一 CoreMark image、NEMU、
seed 0、波形关闭、每千周期进度输出、日志区间和默认线程配置。

IR 命令见 NO0594。legacy 命令：

```sh
make --no-print-directory run_xs_wolf_grhsim_emu WOLF_ENV_SOURCED=1 \
  XS_GRHSIM_BUILD=build/xs/grhsim XS_SIM_MAX_CYCLE=50000 \
  XS_WAVEFORM=0 XS_WAVEFORM_PATH= XS_LOG_DIR="$PWD/ptmp" \
  XS_PROGRESS_EVERY_CYCLES=1000 RUN_ID=20260907_legacy_50000_serial_gate57 \
  TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" > ptmp/grhsim_legacy_50000_serial_gate57.log 2>&1
```

两个进程均退出 0，NEMU 均已启用且未报告不一致。重新比较本次两份日志，50 个
严格连续的采样及三项终态全部匹配：73580 条指令、cycleCnt=49996、guest=50001，
limit PC 为 0x80001312。不是拿先前并行测量的 legacy 耗时作分母。

## Result: Performance Gate Failed

| Metric | Value |
| --- | ---: |
| IR gate57 50k host time | 2073729 ms |
| Legacy serial 50k host time | 153356 ms |
| IR / legacy time | 13.522321 |
| IR time overhead | 1252.232% |
| Legacy time times 1.05 | 161023.80 ms |
| IR reduction needed to reach that threshold | 92.235% |

因此实际 IR 50k 功能门禁通过，但规划的“不差于 legacy 5%”性能要求明确未通过。
history batching 的 1k 相对 gate55 改善约 29.9%，不足以填补整体差距，不能据此
宣布 CPU backend 规划全部完成。

这是两路既有二进制的一次串行同运行参数对照，不是多次重复统计，没有固定 CPU
亲和性或控制系统频率，也没有重新构建两路以统一所有编译选项。它足以暴露当前
数量级性能差距，不作为精细优化置信区间或最终性能验收依据。

## Next Evidence Required

下一步应对 gate57 做新的 compute/commit/publish 分阶段计时及 pending 统计，
通过现有 Makefile 增量构建和运行，探针与日志仍留在 ptmp，测后恢复普通二进制。
不能把 gate55 的阶段占比直接当作 history batching 后的归因。

优先核查普通状态写口的逐项暂存/发布成本和宽值无条件 fanout 激活，所有 helper
继续以 legacy 的指针、输出缓冲和原地写策略为参考。这里只列待验证方向，没有
按猜测修改代码；不重新引入已被实测拒绝的 cpu_store，不更改 DPI 或 event 策略。

目标保持 active，后续仍需性能归因、有效优化及相同范围的功能/性能复验。
