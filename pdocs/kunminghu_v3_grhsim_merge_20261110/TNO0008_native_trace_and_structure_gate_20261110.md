# TNO0008 双版本 native trace 与结构门

## 功能和 placement 结果

两侧均通过 10,000 周期 smoke，以及 seed 0/1 各一次 100,000 周期完整 NEMU/DiffTest trace。每个运行检查 CPU96、恰好单线程、ASLR disabled、NUMA1 本地 binary/library/anonymous state。按用户约定跳过外部 CPU 空闲准入检查。

| 观测项 | before | after |
| --- | ---: | ---: |
| trace records（两个 seed 均相同） | 100,000 | 99,999 |
| trace 首 cycle | 0 | 0 |
| trace 末 cycle / 日志 cycleCnt | 99,996 | 99,995 |
| Guest cycles | 100,001 | 100,001 |
| instrCnt | 238,535 | 250,838 |
| 最后提交 PC | `0x80000cde` | `0x80000c1a` |
| workload 输出 | `Running CoreMark for 2 iterations\n` | 同 before |

每个版本的两个 seed 均有相同功能签名。前后版本的固定周期提交进度不同，符合 [TNO0004](./TNO0004_upstream_rtl_schema_memory_20261110.md) 的 DefaultConfig/微架构变化；各自通过完整参考模型检查。trace 验证遵循 [TNO0007](./TNO0007_trace_cycle_coverage_20261110.md)，不要求不同 schema 原始记录相等。

原始 trace、命令、运行依赖、二进制身份、监控和 locality 记录保存在 [single-verification](../../build/xs/kunminghu-v3-grhsim-merge-20261110/single-verification/)。[verification-complete.json](../../build/xs/kunminghu-v3-grhsim-merge-20261110/single-verification/verification-complete.json) 为通过标记。正式计时会复用冻结的验证产物并再次核对身份，关闭 trace。

## native 静态结构

| 指标 | before | after | 变化 |
| --- | ---: | ---: | ---: |
| GRH operations | 7,175,390 | 8,147,853 | +13.553% |
| GRH values | 6,804,292 | 7,613,504 | +11.893% |
| compute supernodes | 63,142 | 77,041 | +22.012% |
| commit supernodes | 468 | 346 | −26.068% |
| DAG edges | 520,467 | 631,727 | +21.377% |
| boundary activation edges | 1,977,124 | 2,459,911 | +24.419% |
| compute nodes | 1,080,896 | 1,361,481 | +25.959% |
| state-read activation edges | 94,173 | 112,897 | +19.883% |
| memory-read activation edges | 47,830 | 40,373 | −15.591% |
| binary bytes | 79,340,032 | 104,473,224 | +31.678% |

机器可读汇总：[native-functional-structure.json](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/native-functional-structure.json)。after harness 重编译的来源更正单独保存在 [after-single-harness-update.json](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/after-single-harness-update.json)，保留首次源码快照以便追溯。

此阶段不输出性能结论：trace 运行时存在诊断 I/O，且 RepCut 构建流程仍在执行。正式 native/RepCut 前后 8 对 AB/BA 将另文记录。
