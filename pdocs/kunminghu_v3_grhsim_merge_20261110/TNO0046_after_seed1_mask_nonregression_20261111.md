# TNO0046：独立 after seed1 的掩码规则对照

日期：2026-11-11（America/Los_Angeles）。收益门见 [TNO0044](./TNO0044_reduction_mask_default_profitability_guard_20261111.md)，before 的无变化门见 [TNO0045](./TNO0045_before_seed2_mask_nonregression_20261111.md)。

## 控制条件与构建

使用独立 after seed1 分区图，Clang 23、完整 DiffTest/NEMU。A 为此前通过验证的单指令修正版，B 仅开启带“至少 16 个不同谓词”门槛的掩码规则。

双方均保留相同的 `grhsim_Gpart_2_model_sched_77.o` 修正对象，其 SHA256 为 `0c2189a66609399887e7d49eab1dd826378035bb1a93f2fec4f10e18ff70d484`。构建检查该源文件没有被新规则改变，并检查新 archive 内对象与原修正对象逐字节一致。Clang 修复不是本次对照变量，具体原因见 [TNO0035](./TNO0035_after_seed1_clang23_mask_codegen_20261111.md)。

重新发射后比较 9,306 个源码/头文件，仅 40 个 C++ 文件变化，header/layout 保持一致。恢复掩码谓词为旧表达式并删除 pack 声明后，40 个文件全部逐字节等于原文件。命中 114 个节点、46,181 个谓词。

对实际表达式进行 Clang 23 编译后检查：**1,264,174 组输入、619,567,387 次谓词结果比较全部通过**。输入包括满足每个 mask 的模式、逐位翻转、零/全一、walking one/zero 和固定种子随机值。检查报告见 [kernel-check/report.json](../../build/xs/reduction-mask-default-20261111/after1/kernel-check/report.json)。

候选 binary 为 115,530,576 B，SHA256 `92ba6db280c1385d4463eaa486f45c1bd575a68adaca82fce2b9f1e5608399e9`；原 binary 为 117,517,136 B。只重编译变化对象，复用原 harness 和其他模型对象。

## 功能与正式性能

node030、CPU96–127、32 个单核 affinity 线程、NUMA1 bind、ASLR off、相同 performance code-page/preload/pinning。CoreMark 100,000 周期上限，关闭 trace 和额外 profile，保留双方既有 phase timing，不做外部 CPU 空闲准入检查。

双方各经过 10k smoke、100k 验证与预热，再串行完成 8 对 AB/BA。共 22 次运行全部通过 DiffTest、功能签名、线程 affinity、ASLR、NUMA 和 code-page 门；没有拒绝样本。

| 指标 | A 均值 | B 均值 | 逐对变化均值 | bootstrap 95% CI | B 更快 |
|---|---:|---:|---:|---:|---:|
| Host time | 21.919625 s | 14.794625 s | **−32.5048%** | **[−32.7662%, −32.1516%]** | 8/8 |
| 外部 walltime | 22.026181 s | 14.897311 s | **−32.3653%** | **[−32.6175%, −32.0215%]** | 8/8 |

Host 中位数 21.9315 → 14.7735 s，逐对 delta 中位数 −32.7310%。使用固定 seed `20261102`、10,000 次配对 bootstrap。没有按计时高低剔除样本。

同版本的 PC、指令数、cycle_count、Guest cycles、终止原因和 UART 输出一致：`0x80000c1a`、250,838、99,995、100,001、cycle-limit、`Running CoreMark for 2 iterations\n`。

这份不同分区同样获得稳定收益，未观察到性能退化。此结果与 after seed7 的实验时间窗口不同，不能据绝对秒数重新排序两个优化后分区；本次只判断每份图内部的开关差异。

## 归档

- [综合报告](../../build/artifacts/reduction-mask-default-20261111/report.json)
- [逐对 CSV](../../build/xs/reduction-mask-default-20261111/measure-after1/pairs.csv)、[逐对 JSON](../../build/xs/reduction-mask-default-20261111/measure-after1/pairs.json)、[summary](../../build/xs/reduction-mask-default-20261111/measure-after1/summary.json)
- [源码还原审计](../../build/xs/reduction-mask-default-20261111/after1/transformation-audit.json)、[输入及修正对象身份](../../build/xs/reduction-mask-default-20261111/after1/inputs.json)
- [运行日志、命令与放置证据](../../build/xs/reduction-mask-default-20261111/measure-after1/)
