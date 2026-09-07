# NO0596 GrhSIM IR CPU Gate57 Phase Profile

- 日期：2026-09-07
- 前置：[NO0595](./NO0595_grhsim_ir_cpu_gate57_50k_serial_performance_20260907.md)

## Probe and Result

仅在 ptmp/xs_emit_make_gate57/grhsim_SimTop.cpp 临时加入阶段计时与 publish 计数，
复用 NO0579 的 steady-clock 探针形式。公开头文件、所有 task、IR、mapping 和 DPI
不变。通过既有 `make xs_wolf_grhsim_ir_build_emu` 增量编译一个 driver 对象及链接，
再通过 `make run_xs_wolf_grhsim_ir_emu` 运行同配置 1k，均退出 0。

- 构建日志：`ptmp/grhsim_gate57_profile_build.log`。
- 运行日志：`ptmp/grhsim_gate57_profile_1000.log`。
- 保留的探针源码：`ptmp/xs_emit_make_gate57/gate57_profile.hpp`。

| Counter | Gate57 |
| --- | ---: |
| Evals | 2102 |
| Rounds | 4278 |
| Compute including round seeds | 17979.499 ms |
| Commit | 21050.276 ms |
| Publish including counters | 1187.964 ms |
| Pending entries | 159871274 |
| Compared bytes | 2308378142 |
| Changed pending entries | 40691077 |
| Copied bytes | 851666312 |
| Pending entries larger than 64 bytes | 2943384 |
| Compared bytes from those large entries | 1859682153 |

终态仍是 3 条指令、cycleCnt=996、guest=1001，NEMU 启用且没有不一致。
host time 40236 ms，含探针，不替代 NO0592 的无探针 40631 ms。

## Attribution

相同窗口的 gate55 pending 为 1754577592，history batching 后降至 159871274，
但比较字节数完全相同。批次的粗粒度发布会多复制部分未变字节，不能把 changed-entry
数量下降解释为逻辑状态变化减少。Evals/rounds 与 gate55 相同。

当前约 52.3% 阶段时间在 commit、44.7% 在 compute、3.0% 在 publish。history
批量暂存有效减少了登记和扫描，但没有消除普通写口成本，也没有改善 compute。
因此不把大数组 memcpy 或 publish 本身单独认定为下一轮首要根因；仅优化 commit
也不足以把已测得的 13.52 倍差距完全消除。

## Restored Baseline

测量结束后已通过反向补丁撤去全部 include、计时和计数语句。`cmp -s` 确认 gate57
driver 与未带探针的 gate55 driver 逐字节一致；history batching 本来只改 task。
再次通过原 Makefile 增量构建与链接，退出 0，日志
`ptmp/grhsim_gate57_profile_restore.log`。探针 header 留作证据但不再被包含。

没有把短窗口阶段归因当作 50k 性能验收，DPI 和 event 策略始终未改。
