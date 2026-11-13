# TNO0053：宽归约的独立 after seed1 回归

日期：2026-11-12（America/Los_Angeles）。承接 [TNO0050](./TNO0050_wide_concat_reduction_implementation_20261111.md) 的实现和 [TNO0051](./TNO0051_wide_reduction_seed7_walltime_20261112.md) 的 seed7 验收。before 的独立结果见 [TNO0052](./TNO0052_wide_reduction_before_nonregression_20261112.md)。

## 固定对象与 Clang 修正

A 为 TNO0046 已启用共享掩码的 after seed1，B 再启用宽归约。冻结同一 partitioned GRH、assignment、Clang 23/O3/native、harness、CoreMark、完整 DiffTest/NEMU。

保留同一 `grhsim_Gpart_2_model_sched_77.o` Clang 修正：生成检查确认该源码未变化，archive 提取后与原修正对象逐字节一致，SHA256 仍为 `0c2189a66609399887e7d49eab1dd826378035bb1a93f2fec4f10e18ff70d484`。本轮没有更改补丁或关闭其他编译优化。

9,306 个 source/header 中 **91 个 sched C++** 变化，融合 **285 处**宽 concat；全部 header/layout、活动范围及顺序一致。candidate 为 114,804,976 B，SHA256：

```text
aded8fa289c83a7606ff2174b5769b7b82cc1c84fcfdfc79271cf0eb9105bbcb
```

## 功能与性能

node030、CPU96–127、32 个单核 affinity 线程、NUMA1 bind、ASLR off，相同 performance/code-page/preload/pinning。没有 trace 或额外诊断计数，不进行外部 CPU 空闲准入检查。构建完成后才进行串行计时。

双方各完成 10k smoke、100k 完整 DiffTest、预热，然后 8 对 AB/BA。**22 次运行全部通过，拒绝 0 次**。100k 功能签名保持 PC `0x80000c1a`、指令数 250,838、model cycle count 99,995、guest cycles 100,001、cycle-limit，以及相同 CoreMark 启动输出。

| 指标 | A 均值 | B 均值 | 配对 delta 均值 | 95% CI | B 更快 |
|---|---:|---:|---:|---:|---:|
| Host time | 15.088375 s | 14.455375 s | **−4.1937%** | **[−4.6108%, −3.8623%]** | 8/8 |
| 外部 walltime | 15.196533 s | 14.566614 s | **−4.1435%** | **[−4.5614%, −3.8110%]** | 8/8 |

Host 配对 delta 中位数 −4.1337%。bootstrap 固定 seed `20261102`，10,000 次配对重采样。所有样本保留，没有按时间筛选。

该独立分区同样稳定加速，未观察到退化。三组实验不是同时窗口，不据其绝对秒数重新排序 seed7 与 seed1，也不将此结果解释为合并前后的净差异。

## 归档

- [完整报告](../../build/artifacts/repcut-wide-reduction-20261111/after1-report.json)
- [源码对比](../../build/xs/repcut-wide-reduction-20261111/after1/source-comparison.json)、[活动范围审计](../../build/xs/repcut-wide-reduction-20261111/after1/transformation-audit.json)、[修正对象及输入身份](../../build/xs/repcut-wide-reduction-20261111/after1/inputs.json)
- [summary](../../build/xs/repcut-wide-reduction-20261111/measure-after1/summary.json)、[CSV](../../build/xs/repcut-wide-reduction-20261111/measure-after1/pairs.csv)、[完整逐对 JSON](../../build/xs/repcut-wide-reduction-20261111/measure-after1/pairs.json)、[功能门](../../build/xs/repcut-wide-reduction-20261111/measure-after1/functional.json)
- [串行构建与测量完成记录](../../build/xs/repcut-wide-reduction-20261111/cross-complete.json)
