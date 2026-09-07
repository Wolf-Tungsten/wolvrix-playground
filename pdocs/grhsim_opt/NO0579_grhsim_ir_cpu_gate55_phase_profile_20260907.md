# NO0579 GrhSIM IR CPU Gate55 Phase Profile

- 日期：2026-09-07
- 前置：[NO0578](./NO0578_grhsim_ir_cpu_gate55_o3_runtime_20260907.md)

## Probe Boundary

普通用户的 Linux perf 受 `perf_event_paranoid=4` 限制，环境没有 valgrind；本阶段
没有申请额外权限或安装外部工具。仅在项目内 gate55 生成 driver 加临时 C++ steady-clock
计时及 publish 计数，不改 header/对象布局、task 实现、event 或 DPI 行为。
探针支持文件保存在 `ptmp/xs_emit_make_gate55/gate55_profile.hpp`。

探针只修改 driver，使用已有 `make xs_wolf_grhsim_ir_build_emu` 增量 O3 编译和链接，
再用已有 `make run_xs_wolf_grhsim_ir_emu` 执行相同的 1000-cycle image/NEMU 窗口。
运行使用 `XS_WAVEFORM=0`、`XS_WAVEFORM_PATH=`、`XS_LOG_DIR=$PWD/ptmp`、
`XS_PROGRESS_EVERY_CYCLES=100`、`RUN_ID=20260907_gate55_profile_1000`。
所有进程已确认退出 0；构建和运行日志分别为
`ptmp/grhsim_gate55_profile_build.log`、`ptmp/grhsim_gate55_profile_1000.log`。

## Measurements

| Counter | Observed |
| --- | --- |
| eval calls | 2102 |
| fixed-point rounds | 4278 |
| compute, including round seeds | 17948.308 ms |
| commit tasks | 34888.293 ms |
| publish, including probe counters | 6102.875 ms |
| pending entries processed | 1754577592 |
| bytes compared in publish | 2308378142 |
| entries whose final bytes changed | 622841777 |
| bytes copied back to visible objects | 636366591 |
| pending entries larger than 64 bytes | 83471 |
| compared bytes from those large entries | 426791536 |

总 host time 58959 ms；终态仍是 cycle limit、3 条指令、cycleCnt=996，没有 NEMU
报告不一致。阶段计时含探针开销，不替代无探针的 57958 ms 基线，不报告加速比。

证据改变了下一步优先级：commit/publish 占阶段计时约 70%，pending 记录中约 64.5%
最终没有变化，且绝大多数是小尺寸状态。当前不能把整数组 memcpy 当作首要根因。
既有 `stage()` 无条件登记每个 event history，标量写也在计算最终 masked 值之前登记；
这些路径值得先按 legacy 的“变化后再记录/激活”策略收窄。

## Probe Removal

测量后已用局部反向补丁撤去 gate55 driver 的全部探针调用及 include，并通过相同
Makefile 增量 O3 构建重新链接，退出 0。恢复日志为
`ptmp/grhsim_gate55_profile_restore.log`。不覆盖原始 gate55 运行日志；未修改的
task 对象始终保持原 O3 实现。单独保留的探针 header 不再被 driver 引用。

后续不变更新入队修复见
[NO0580](./NO0580_grhsim_ir_cpu_unchanged_state_staging_20260907.md)。
