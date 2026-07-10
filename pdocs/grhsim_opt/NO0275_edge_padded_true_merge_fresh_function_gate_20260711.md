# NO0275 Edge-padded true-merge fresh function gate

日期：2026-07-11

## 目标与口径

对 [NO0274](./NO0274_edge_padded_packed_priority_true_merge_20260711.md) 做 fresh C++、emu build 和
SimTop difftest。fresh 流程从固定的 pre-reg-to-mem checkpoint 重新执行当前 `reg-to-mem`、
activity schedule、C++ emit 和全部 C++ 编译，不复用旧 generated source 或 object。

本轮运行期间系统 load average 约为 `93~102/384`。10k/50k 的 Host time 只用于确认进程正常，
不作为性能结论；性能必须在后续固定 CPU 的相邻 old/new 配对窗口重新测量。

## Fresh 产物

```text
build/xs_grhsim_no0274_rob_true_merge_20260711/grhsim
build/logs/xs/xs_wolf_grhsim_build_no0274_rob_true_merge_20260711.log
```

生成和编译均成功。`reg-to-mem` fresh 结果与 NO0274 stop-after 一致：

```text
groups=4315
true_groups=825
edge_padded_true_groups=171
```

这里的改写范围大于目标 8 个 ROB group：新的通用 edge-padding discovery 与 packed-write matcher
还恢复了其他满足完整 closure/write-family 条件的 storage。后续功能门禁针对整个 fresh emu，而不只
验证 `debug_VecOtherPdest`。

## Generated C++ 结构门禁

目标 ROB 结构：

| generated shape | NO0271 old | NO0274 new |
| --- | ---: | ---: |
| target `kRegisterWritePort` | `2816` | `0` |
| target `kMemoryWritePort` | `0` | `16` |
| target `kMemoryFillPort` | `0` | `8` |
| target `std::array<uint8_t, 352>` state | `0` | `8` |

每个 lane memory 有两路 indexed write，对应原来的两路有序 WB family；generated guard 均包含
`addr < 352` domain check。8 个 fill 保留原 group-wide reset 语义。

全图静态规模相对 NO0271：

| metric | NO0271 old | NO0274 new | delta |
| --- | ---: | ---: | ---: |
| generated C++ bytes | `1515674089` | `1492206672` | `-1.5483%` |
| executable `.text` | `103993490` | `103250046` | `-0.7149%` |
| supernodes | `69113` | `68237` | `-1.2675%` |
| DAG edges | `664215` | `639249` | `-3.7587%` |
| boundary activation edges | `2284102` | `2263684` | `-0.8939%` |
| compute-compute value pairs | `2008189` | `2003496` | `-0.2337%` |
| compute-commit value pairs | `275913` | `260188` | `-5.6993%` |

这些静态变化只说明改写已传递到 emitter/schedule，不直接代表 runtime 收益。

## SimTop functional gate

10k difftest：

```text
Guest cycles: 10001
instrCnt: 458
cycleCnt: 9996
terminal PC: 0x800027c6
mismatch / ABORT: 0 / 0
Host time: 11261ms (non-performance run)
```

50k difftest：

```text
Guest cycles: 50001
instrCnt: 73580
cycleCnt: 49996
terminal PC: 0x80001312
mismatch / ABORT: 0 / 0
Host time: 85915ms (non-performance run)
```

日志：

```text
build/logs/xs/xs_wolf_grhsim_no0274_rob_true_merge_10k_20260711.log
build/logs/xs/xs_wolf_grhsim_no0275_rob_true_merge_50k_function_20260711.log
```

## 结论与下一步

fresh 结构与 10k/50k 功能门禁均通过，目标 2816 个 scalar write 已实际从 executable source 中
消失。下一阶段以 NO0271 emu 为 old、NO0274 emu 为 new，先检查固定 CPU 及 SMT sibling 的空闲
状态，再做 old/new/old 50k perf-stat；若共享负载波动明显，以两次 old 的稳定性决定是否接受结果。
