# TNO0052：before seed2 的宽归约回归

日期：2026-11-12（America/Los_Angeles）。实现见 [TNO0050](./TNO0050_wide_concat_reduction_implementation_20261111.md)，after seed7 收益见 [TNO0051](./TNO0051_wide_reduction_seed7_walltime_20261112.md)。本篇检查默认启用前，旧版 XiangShan 的 before seed2 是否退化。

## 构建与功能

复用既有 before seed2 的冻结 GRH、assignment、Clang 23/O3/native、harness 与完整 DiffTest/NEMU。候选同时记录共享掩码开关为 1，但 [TNO0045](./TNO0045_before_seed2_mask_nonregression_20261111.md) 已证明该开关在此图上不改变源码和 binary；本次新增代码变化来自宽归约融合。

7,857 个 source/header 中仅 **14 个 sched C++** 变化，融合 **65 处**宽 concat；全部 header/layout、活动范围及其顺序保持不变。命中以 OR 归约为主，另有一处 339 位 AND 归约。binary 98,878,808 → 98,783,920 B。候选 SHA256：

```text
27309399baffa03aeb1c8d538a7263bed934d0fd670f2269b54c1685ccd6c674
```

双方各完成 10k smoke、100k DiffTest、预热，再进行 8 对 AB/BA。**22 次运行全部通过，拒绝 0 次**。100k 签名保持 PC `0x80000cde`、指令数 238,535、model cycle count 99,996、guest cycles 100,001、cycle-limit，输出 `Running CoreMark for 2 iterations`。此签名只在 before 内部比较，不要求与 after 的微架构进度相等。

## 性能

node030、CPU96–127、NUMA1 bind、ASLR disabled、相同 performance/code-page/preload/pinning，完整 DiffTest。无 trace、无额外诊断计数，不检查外部 CPU 空闲。固定 seed `20261102`、10,000 次配对 bootstrap。

| 指标 | A 均值 | B 均值 | 配对 delta 均值 | 95% CI | B 更快 |
|---|---:|---:|---:|---:|---:|
| Host time | 10.960125 s | 10.913750 s | **−0.4137%** | **[−1.5717%, +0.5895%]** | 4/8 |
| 外部 walltime | 11.051515 s | 11.004209 s | **−0.4194%** | **[−1.6140%, +0.6004%]** | 4/8 |

Host 配对 delta 中位数 −0.3200%。未观察到稳定性能退化，也不能把跨零区间解释成确定的 before 加速或绝对零退化。`part_eval` 中位数 8.6820 → 8.6428 s，与总体接近不变的结果一致。

所有有效样本进入统计，没有按快慢筛选。保留这份独立对照，不将其与 after 的绝对 walltime 拼接比较。

## 归档

- [完整报告](../../build/artifacts/repcut-wide-reduction-20261111/before-report.json)
- [源码对比](../../build/xs/repcut-wide-reduction-20261111/before/source-comparison.json)、[活动范围审计](../../build/xs/repcut-wide-reduction-20261111/before/transformation-audit.json)、[输入身份](../../build/xs/repcut-wide-reduction-20261111/before/inputs.json)
- [summary](../../build/xs/repcut-wide-reduction-20261111/measure-before/summary.json)、[CSV](../../build/xs/repcut-wide-reduction-20261111/measure-before/pairs.csv)、[逐对 JSON](../../build/xs/repcut-wide-reduction-20261111/measure-before/pairs.json)、[功能门](../../build/xs/repcut-wide-reduction-20261111/measure-before/functional.json)
- [跨图构建脚本](../../build/artifacts/repcut-wide-reduction-20261111/cross_build.py)、[配对脚本](../../build/artifacts/repcut-wide-reduction-20261111/cross_measure.py)
