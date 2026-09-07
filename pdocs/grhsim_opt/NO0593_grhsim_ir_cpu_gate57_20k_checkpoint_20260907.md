# NO0593 GrhSIM IR CPU Gate57 20k Checkpoint

- 日期：2026-09-07
- 前置：[NO0592](./NO0592_grhsim_ir_cpu_gate57_1k_runtime_20260907.md)

## Live 50k Run

同一次 `make run_xs_wolf_grhsim_ir_emu` 的 50000-cycle 运行已越过 20000 cycles。
日志为 `ptmp/grhsim_gate57_o3_50000.log`；进程句柄确认仍存活，没有重新启动，
也没有把上限缩为 10k/20k。期间没有并行构建、其他仿真或修改待测二进制。

| Checkpoint | Instructions | Commit PC | Trap PC |
| --- | ---: | --- | --- |
| 10000 | 458 | 0x80001cdc | 0x800027c6 |
| 20000 | 14121 | 0x8000043a | 0x80000440 |

10k 的 host elapsed 为 388608 ms。NEMU difftest 已启用，暂未报告不一致；
CoreMark 两次迭代的启动提示已输出。

将日志中每个 `[EMU_PROGRESS] host_cycles=` 之后的字段抽出，去掉 `host_ms`，
按 `host_cycles` 对照 NO0587 的 legacy 50k 日志，前 20 个逐千周期采样完全一致。
抽取接受 guest 文本与进度标记同一行的情况，没有仅匹配行首而遗漏 9k-12k。

## Not a Terminal Gate

这不是独立 20k 进程的退出结果，也不是 50k 通过。日志中的周期检查提示同时显示
`max_cycles=50000`，实际运行仍继续。当前只能证明已观察到的提交进度一致，
不能当作全状态波形等价、完整程序完成或性能达标。

后续继续等待该进程的真实 50k 终态，再核对全部 50 个采样和最终计数；正式性能
对照还需在 IR 结束后串行复测 legacy。目标继续未完成。
