# TNO0051：宽归约融合的 after seed7 功能与性能验收

日期：2026-11-12（America/Los_Angeles；实验于 11 日启动，产物目录沿用启动日）。实现见 [TNO0050](./TNO0050_wide_concat_reduction_implementation_20261111.md)，原瓶颈证据见 [TNO0048](./TNO0048_part18_remaining_hotspots_20261111.md)。

## 控制与源码审计

A 为已开启共享输入掩码的 after seed7，B 仅增加 `WOLVRIX_GRHSIM_WIDE_CONCAT_REDUCTION=1`。同一冻结 partitioned GRH、assignment、Clang 23.1.2、C++20/O3/native、harness、完整 DiffTest/NEMU。未重新分区，不叠加调用前检查或新 runtime 插桩。

重新生成并比较 9,434 个 source/header，只有 **95 个 sched C++** 变化，全部 header/layout 相同。融合 **296 处**宽局部 concat，其中 part_18 为 **60 处**、part_8 为 36 处；其他命中分区为 0/1/10/11/12/20/25/29/30。其余模型对象及 harness 原样复用。

变化文件源码总量 53,655,222 → 43,990,900 B。binary 117,241,040 → 116,474,480 B，减少约 0.654%。候选 SHA256：

```text
999c1f42a6bc3090a2801168f936432dd15777caaab4136705835dc7933be51a
```

## 功能检查

除 focused sanitizer 测试外，从实际 95 个变化文件中提取全部 296 个 concat 的旧 Words 构造和新 Boolean 表达式，用相同 Clang 23/O3 编译后比较。输入保留实际 bool/u16/u64 类型，覆盖全零、全一、逐字段翻转和固定随机种子，**440,372 组表达式比较全部通过**。独立检查将局部表达式输入当作自由变量，范围超过 CoreMark 的实际活动组合；它仍不等于完整 RVV 架构负载。

检查提取器先后补充了直接 slot、runtime `unlikely` 宏和 state alias 的处理；这些是独立 harness 的编译/解析问题，没有模型 mismatch。原失败提取日志保留，最终结果见 `kernel-check-r3`。完整 emitter 回归、旧标量归约和共享掩码回归通过。

双方各完成 10k smoke、100k DiffTest 验证和预热，之后 8 对 AB/BA；共 **22 次运行全部通过**，无拒绝样本。100k 功能签名相同：PC `0x80000c1a`、指令数 250,838、model cycle count 99,995、guest cycles 100,001、cycle-limit、输出 `Running CoreMark for 2 iterations`。

## 正式 walltime

node030、CPU96–127、32 个单核 affinity 线程、NUMA1 严格绑定、ASLR disabled，相同 performance code-page/preload/pinning。关闭 trace 和额外 profile，保留既有 phase timing。未进行外部 CPU 空闲准入检查。

负号表示 B 更快，bootstrap 固定 seed `20261102`，10,000 次配对重采样。

| 指标 | A 均值 | B 均值 | 配对 delta 均值 | 95% CI | B 更快 |
|---|---:|---:|---:|---:|---:|
| Host time | 13.815125 s | 13.400125 s | **−2.9829%** | **[−4.0868%, −1.9000%]** | 8/8 |
| 外部 walltime | 13.921100 s | 13.509892 s | **−2.9334%** | **[−4.0300%, −1.8636%]** | 8/8 |

Host 配对 delta 中位数 −2.7540%。结果表明该 frozen graph 有稳定收益；不能与此前其他时间窗口的绝对秒数直接相减或拼接为累计收益。

## 与瓶颈的对应

以下为 8 次正式样本的累计分项时间中位数，不是可直接相加的并行成本占比。

| 项目 | A | B | 变化 |
|---|---:|---:|---:|
| part_eval phase | 11.7404 s | 11.2560 s | −4.13% |
| part_18 eval | 8.8667 s | 8.4055 s | **−5.20%** |
| part_8 eval | 4.4276 s | 4.0459 s | −8.62% |
| part_19 eval | 7.5456 s | 7.4116 s | −1.78% |
| global_update phase | 1.3903 s | 1.3916 s | 基本相同 |

part_18/batch_160 机器码从 144,287 B 降到 **107,248 B（−25.67%）**；batch_147 从 23,803 降到 21,593 B。未命中的 batch_125 与 batch_161 大小保持 49,475 / 80,990 B。这与宽 concat 热点定位吻合：收益来自减少实际生成和执行工作，而不是减少功能覆盖。

part_18 仍是较慢分区，剩余短字段译码及条件复用可作为后续独立议题。默认启用仍需独立 before/after seed1 回归；本篇只报告此 frozen seed7 的验收结果。

## 归档

- [完整机器可读报告](../../build/artifacts/repcut-wide-reduction-20261111/generated-report.json)
- [源码对比](../../build/xs/repcut-wide-reduction-20261111/generated/source-comparison.json)、[图与编译器身份](../../build/xs/repcut-wide-reduction-20261111/generated/inputs.json)
- [实际表达式检查](../../build/xs/repcut-wide-reduction-20261111/kernel-check-r3/report.json)、[提取与编译脚本](../../build/artifacts/repcut-wide-reduction-20261111/check_kernels.py)
- [summary](../../build/xs/repcut-wide-reduction-20261111/measure-generated/summary.json)、[CSV](../../build/xs/repcut-wide-reduction-20261111/measure-generated/pairs.csv)、[完整逐对记录](../../build/xs/repcut-wide-reduction-20261111/measure-generated/pairs.json)、[功能门](../../build/xs/repcut-wide-reduction-20261111/measure-generated/functional.json)
- [配对驱动](../../build/artifacts/repcut-wide-reduction-20261111/measure.py)、[核验与汇总](../../build/artifacts/repcut-wide-reduction-20261111/report.py)

## 增量更新 2026-11-12：默认开启

before seed2 与独立 after seed1 的回归均完成，宽归约已随父规则默认启用，保留显式关闭。默认/on 源码一致性和最终检查见 [TNO0054](./TNO0054_wide_reduction_default_enabled_20261112.md)。本篇显式开启版本的性能记录保持不变。
