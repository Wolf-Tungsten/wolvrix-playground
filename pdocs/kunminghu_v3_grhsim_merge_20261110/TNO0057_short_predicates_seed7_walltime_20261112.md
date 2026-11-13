# TNO0057：短条件共享的 after seed7 验收

日期：2026-11-12（America/Los_Angeles）。实现和安全边界见 [TNO0056](./TNO0056_short_predicate_masks_implementation_20261112.md)，优化目标来自 [TNO0055](./TNO0055_after_current_hotspots_20261112.md)。

## 生成与独立功能检查

A 为已开启长条件掩码和宽 concat 归约的 after seed7；B 仅增加 `WOLVRIX_GRHSIM_SHORT_CONCAT_REDUCTION_MASKS=1`。冻结同一 GRH、assignment、Clang 23/O3/native、harness 与完整 DiffTest/NEMU；不重新分区。

9,434 个 source/header 中只有 **153 个 sched C++** 变化，header/layout 相同。命中 **456 个 compute 范围**：part_18 为 **202** 个，part_10 为 141 个、part_11 为 102 个，其余分布于 6/13/15/19/20/31。源码审计确认原活动范围顺序及原长字段 pack 均不变。

变化文件总源码从 56,783,011 降至 39,077,340 B。binary 116,474,480 → 115,106,416 B，候选 SHA256：

```text
a20663a2e4136f953bd4e1109eae38b0dfad640f2a70c73f6cf6886ed215c6f7
```

提取全部匹配范围的实际旧表达式和新 mask compare，用相同 Clang 23/O3 编译比较。覆盖 **35,281 个不同谓词、1,320,538 组输入、125,230,559 次结果比较，全部通过**。输入包含零/全一、walking bit、满足每个 mask 的输入及逐位破坏、固定随机值。每个匹配 mask 都能在旧代码中找到对应归约调用或已经生成的 Boolean 快照，不以抽象参考替代实际旧表达式。

提取过程最初遇到一次 NFS 文件可见性延迟，随后补充旧 Boolean bad-bit/any-bit 快照的解析；这些是检查脚本问题，没有模型输出 mismatch，失败日志保留，最终结果为 `kernel-check-r3`。

新增短规则的字段边界、低复用、重复字段等 focused 测试通过；原长掩码、宽归约与完整 emitter 回归通过。Clang 23 O0/O3、ASan/UBSan 均覆盖新规则，17 项 Python 测试通过。

## 完整运行与 walltime

node030、CPU96–127、32 个 singleton affinity 线程、NUMA1 严格 bind、ASLR disabled，相同 performance/code-page/preload/pinning。CoreMark 100k、完整 DiffTest，无 trace 或额外计数，不检查外部 CPU 空闲。

双方各经过 10k smoke、100k 验证和预热，随后 8 对 AB/BA。**22 次全部通过，拒绝 0 次**。100k 签名与基线完全相同：PC `0x80000c1a`、指令数 250,838、model cycles 99,995、guest cycles 100,001、cycle-limit，以及相同 CoreMark 启动输出。

| 指标 | A 均值 | B 均值 | 每对变化均值 | 95% CI | B 更快 |
|---|---:|---:|---:|---:|---:|
| Host time | 14.725625 s | 13.704750 s | **−6.9284%** | **[−7.7137%, −6.1937%]** | 8/8 |
| 外部 walltime | 14.834962 s | 13.824815 s | **−6.8046%** | **[−7.6022%, −6.0449%]** | 8/8 |

Host delta 中位数 −6.6580%。bootstrap seed `20261102`，10,000 次配对重采样，全部有效样本纳入统计。本窗口绝对时间与此前不同，不能用跨窗口秒数相减判断累计收益。

## 瓶颈变化

以下为正式 8 次候选/基线运行的累计分项中位数，分区并行运行，不可相加为 walltime：

| 项目 | A | B | 变化 |
|---|---:|---:|---:|
| part_eval phase | 12.6657 s | 11.5400 s | −8.89% |
| part_18 eval | 9.4958 s | **8.4828 s** | **−10.67%** |
| part_19 eval | 8.4110 s | **8.3071 s** | −1.24% |
| part_23 eval | 7.6683 s | 7.5725 s | −1.25% |
| global_update phase | 1.3703 s | 1.3806 s | +0.75% |

part_18 已接近 part_19，单独继续削减 part_18 的整机收益将受到其他分区限制。后续应重新核对关键路径，特别关注 TNO0055 定位的 part_19 输入变化检测与激活传播。

机器码变化也与目标对应：part_18/batch_160 **107,248 → 38,754 B**，batch_125 **49,475 → 25,036 B**；batch_161 80,990 → 71,920 B。规则未强行覆盖不满足稳定输入或 64 输入边界的集合。

## 归档

- [完整报告](../../build/artifacts/repcut-short-reduction-20261112/generated-report.json)、[检查状态](../../build/artifacts/repcut-short-reduction-20261112/checks.json)
- [源码比较](../../build/xs/repcut-short-reduction-20261112/generated/source-comparison.json)、[活动范围与旧 pack 审计](../../build/xs/repcut-short-reduction-20261112/generated/transformation-audit.json)、[输入身份](../../build/xs/repcut-short-reduction-20261112/generated/inputs.json)
- [实际表达式检查](../../build/xs/repcut-short-reduction-20261112/kernel-check-r3/report.json)、[提取脚本](../../build/artifacts/repcut-short-reduction-20261112/check_kernels.py)
- [summary](../../build/xs/repcut-short-reduction-20261112/measure-generated/summary.json)、[CSV](../../build/xs/repcut-short-reduction-20261112/measure-generated/pairs.csv)、[逐对记录](../../build/xs/repcut-short-reduction-20261112/measure-generated/pairs.json)、[功能门](../../build/xs/repcut-short-reduction-20261112/measure-generated/functional.json)

before seed2 和独立 after seed1 的回归继续独立归档，默认策略在这些结果完成后决定。
