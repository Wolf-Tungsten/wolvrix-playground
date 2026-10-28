# TNO0365：干净初解的完整构建与最终运行

日期：2026-10-28。承接 [TNO0364](./TNO0364_grhsim_source_only_bootstrap_20261028.md)。

## 从 Verilog 开始的结果

默认新流程实际完成当前 Verilog 的原生前端转换、固定 memory 控制配置、六维权重图、8 份独立求解及最低可行完整图 km1 选择。最终选 seed 6，完整图 km1=39,450,970，8 份求解均满足容量条件；自动隔离 1 个超大不可拆 ASC。

随后 assignment replay、memory-write-coalesce、reg-to-mem、完整 32 分区 GrhSIM 发射、8,259 个对象的原始 O3/native 编译、section 对齐、按生成顺序归档和 Difftest harness 链接均完成。原生工具与求解器使用 GCC 13，模型使用 Clang 23；不使用 no-SLP。

本轮设计产物均在 `build/xs/grhsim32/` 重新生成。没有以旧 JSON、HGR、assignment、model archive 或 emu 为生成输入，也没有插入历史身份或执行计划 gate。

## 最终功能与 walltime

在 node030 CPU96–127 上完成 C100 smoke 和 8 次 C=100000 普通运行，全部通过 NEMU/周期终止检查。运行记录为 32 lane、31 background worker、Host 参与、push 更新和 all-spin。每次代码页覆盖为 88,080,384 B，实际 AnonHugePages 等于该值。

| 指标 | 8 次普通运行中位数 |
|---|---:|
| 进程 walltime | 13.394977 s |
| Host | 13.306500 s |

本表是新初解的运行结果，既不是插桩 walltime，也不是相对历史恢复版的新鲜 AB/BA；不能据此宣称超过或落后历史窗口的某个百分比。

两个 wrapper trace 运行也完成，自动按本轮关键路径得到来源优先级 p0、p2、p6。随后进入自动迁移的成本提取和提案评估，本记录形成时尚未发布最终迁移结论。

完整记录在 `build/xs/grhsim32/initial/runs/summary.json`，自动选择记录在 `build/xs/grhsim32/selection.json`。默认入口、运行方式和系统依赖见 [使用文档](../../docs/grhsim32.md)。
