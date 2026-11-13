# TNO0063：短条件收益门的动态复查与公共因子成本

日期：2026-11-12（America/Los_Angeles）。本篇进一步检查 [TNO0058](./TNO0058_short_predicate_profitability_revision_20261112.md) 的 before 退化观测，以及 [TNO0062](./TNO0062_short_predicates_default_enabled_20261112.md) 的 128 谓词门遗漏的 after 收益。先固定现有源码、工具身份和产物，再进行隔离诊断。

## before 退化不能直接归因到全部 39 个范围

原版 39 个改写范围分布于 before 的 part_1/5/18/21/22；累计 eval 最慢的 part_11、part_26 并没有源改写。因此原有约 +0.78% 的整机观测不能直接证明这些范围的布尔计算普遍变慢。

在初始宽规则 on/off 版本中，对每个实际活动范围加入调用计数和 `lfence; rdtsc` 起止计时。插桩位于原活动 guard 内，不改变条件或状态。每图执行两组反向次序，共四次 100k 完整 DiffTest，node030、CPU96–127、NUMA1、ASLR off。on/off 调用数逐范围完全一致，功能签名和放置门通过。**该插桩包含时间戳本身的成本，只用于范围归因，不作为正式 walltime。**

| 图 | 范围数 | 每次总调用 | off 范围计时总量均值 | on 范围计时总量均值 |
|---|---:|---:|---:|---:|
| before seed2 | 39 | 906,891 | 197,499,569 TSC ticks | 126,099,877 TSC ticks |
| after seed7 | 456 | 20,169,331 | 9,986,746,790 TSC ticks | 5,050,203,482 TSC ticks |

以上是并行范围累计值，不能相加或换算成整机 walltime。before 的 part_22 多个范围实际减少约 30%–83% 的范围计时，part_5 大多小幅改善；part_1/18/21 的多数范围仅执行一次。after 则有大量持续执行的短条件集合，128 以下的集合仍贡献相当多的计算节省。少量 after 范围确有局部退化，继续需要收益约束。

## before 原 binary 的独立 8 对复测

使用与上轮相同的 A/B binary、CoreMark/NEMU 和 performance 配置，关闭插桩，重新完成 smoke、100k 验证、预热及 8 对 AB/BA。新记录与旧结果分别保存。

| 指标 | A 均值 | B 均值 | 配对变化 | 95% CI |
|---|---:|---:|---:|---:|
| Host time | 11.403500 s | 11.408375 s | **+0.0442%** | **[−0.5796%, +0.6036%]** |
| 外部 walltime | 11.491567 s | 11.494289 s | **+0.0247%** | **[−0.5482%, +0.5422%]** |

本轮 22 次运行通过完整 DiffTest 和放置门，3/8 对 B 更快。固定 bootstrap seed `20261102`，10,000 次配对重采样，没有外部 CPU 空闲准入检查。

原 +0.78% 观测没有在这轮稳定复现；两轮都保留。当前证据不足以将旧差异确定为输入打包开销，代码布局和环境波动仍可能参与。不能把“全部 39 个范围都低效”当作收益门依据。

## 更细的候选规则

对相同 mask/family 的谓词去重。对 AND 和 OR 分别估计公共因子复用：每次选择出现最多的二元项，计一次运算并在所有表达式中共享；次数相同时按输入编号确定顺序。剩余每个 n 项表达式计 n−1 次运算。这个算法只计算 `C`，不改写布尔函数。

候选门保留已验证的 `P >= 128` 路径。对 `16 <= P < 128`，在原稳定性、字段数、64 输入和复用检查外，要求：

```text
C >= 2 * P + I
P = 不同 mask/family 谓词数
I = 稳定输入数
C = 扣除估计公共因子后的二元布尔运算数
```

这里是用于排序/筛选的成本单位，**不等于真实机器指令数或周期数**。两个单位/谓词和一个单位/输入体现逐谓词比较与共享输入词的开销；公共因子估计给普通 lowering 已有的复用机会留出空间。它仍是启发式规则，需要实际对测。

静态预审预计：before 0 个范围，after seed7 **196 个**，after seed1 **189 个**。相比原 128 门的 51/43 个，恢复更多中等集合，并仍保留 before 源码完全回退的可能。算法仅在 16–127 个谓词、至多 64 个输入时执行，限定生成阶段成本，不依赖分区名、模块名、opcode 或 revision。

本阶段开始进行候选源码、完整 emitter 与性能验证；本篇不把静态覆盖数当作最终收益。

## 产物

- [工作树起点](../../build/artifacts/repcut-short-profitability-20261112/start.json)、[起点源码](../../build/artifacts/repcut-short-profitability-20261112/start-source/)
- [before 动态摘要](../../build/artifacts/repcut-short-profitability-20261112/before-profile-summary.json)、[after 动态摘要](../../build/artifacts/repcut-short-profitability-20261112/generated-profile-summary.json)
- [诊断构建脚本](../../build/artifacts/repcut-short-profitability-20261112/profile_build.py)、[诊断运行脚本](../../build/artifacts/repcut-short-profitability-20261112/profile_run.py)、[原始日志](../../build/xs/repcut-short-profitability-20261112/)
- [before 复测汇总](../../build/xs/repcut-short-profitability-20261112/recheck-broad-before/summary.json)、[逐对 CSV](../../build/xs/repcut-short-profitability-20261112/recheck-broad-before/pairs.csv)
- [结构特征](../../build/artifacts/repcut-short-profitability-20261112/scope-features.json)、[公共因子成本](../../build/artifacts/repcut-short-profitability-20261112/factor-costs.json)、[成本计算脚本](../../build/artifacts/repcut-short-profitability-20261112/factor_cost.py)
