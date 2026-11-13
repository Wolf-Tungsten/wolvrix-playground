# TNO0060：128 谓词门下 after seed7 的功能与性能验收

日期：2026-11-12（America/Los_Angeles）。本篇验证 [TNO0058](./TNO0058_short_predicate_profitability_revision_20261112.md) 收紧后的规则。before 的完全回退已由 [TNO0059](./TNO0059_short_predicates_before_identity_20261112.md) 验证；初始 16 谓词门的 −6.93% 不作为本版结果。

## 生成与功能证据

冻结 after seed7 的 partitioned graph、assignment、完整 DiffTest harness、CoreMark/NEMU 和 Clang 23.1.2 参数。A 为已有长字段掩码与宽归约基线，B 只增加短条件共享掩码。新旧 9,434 个 source/header 文件集合一致，只有 **35 个 C++ 文件**变化，全部 header/layout 不变。

共保留 **51 个范围、13,496 个不同谓词**：part_10 为 19 个范围，part_11 为 23 个，part_18 为 9 个。保留范围的完整源码与初始版逐字一致，其余范围与 A 逐字一致；这个子集对应先前实际表达式检查的 **239,371 个向量、65,564,927 次比较**，全部通过。

收紧版 focused fixture 通过 127/128 个不同谓词、64/65 输入、4/15 字段、重复字段、局部写入、副作用、数值用途和混合归约回退，以及属性/环境变量优先级和关闭父规则的检查。开启、关闭、关闭父规则三种模式分别在 Clang O0/O3、ASan/UBSan 下运行 12,000 组输入，每组重复 eval 两次。参考检查按组拆成函数，保持全部比较，避免单个巨型函数拖慢测试编译。启用该规则的完整 emitter 回归也通过。

## 8 对 AB/BA

node030、CPU96–127、NUMA1 严格 bind、ASLR off、performance 模式，保持相同 code-page/preload/thread-pinning 配置。关闭 trace/runtime-profile 诊断；沿用双方相同的阶段 timing。没有外部 CPU 空闲准入检查。每侧依次 smoke 10k、完整 DiffTest 100k、预热 100k，再交替执行 8 对 100k 计时。

**22 次运行全部通过，无拒绝样本。** 每次 100k 运行共同签名为 PC `0x80000c1a`、instruction count `250838`、cycle count `99995`、Guest cycles `100001`、`cycle-limit`，输出 `Running CoreMark for 2 iterations`。

| 指标 | A 均值 | B 均值 | 配对变化均值 | bootstrap 95% CI | B 更快 |
|---|---:|---:|---:|---:|---:|
| Host time | 14.370625 s | 14.053750 s | **−2.2009%** | **[−2.8019%, −1.4895%]** | 8/8 |
| 外部 walltime | 14.474478 s | 14.159606 s | **−2.1713%** | **[−2.7603%, −1.4667%]** | 8/8 |

配对 bootstrap 使用固定 seed `20261102`、10,000 次重采样。改善稳定，但小于初始宽覆盖版；这是避免 before 退化所接受的覆盖代价。

## 剩余瓶颈

下面为本轮 8 次正式样本的累计分项中位数，单位 ms；并行分区时间不能相加为 walltime。

| 分项 | A | B |
|---|---:|---:|
| part_eval 阶段 | 12,321.327 | 11,976.352 |
| global_update 阶段 | 1,332.036 | 1,332.008 |
| input_load 阶段 | 434.213 | 413.463 |
| part_18 eval | **9,204.272** | **8,998.482** |
| part_19 eval | 8,093.247 | 8,042.846 |
| part_23 eval | 7,384.599 | 7,333.619 |

part_18 eval 下降约 **2.24%**，仍为累计 eval 最慢分区；part_19 和 part_23 仍是后续限制。part_18 `batch_160` 的机器码由 **107,248 bytes** 缩为 **40,962 bytes**；batch_125/147/161 在本版保持原大小。不要将初始宽覆盖版的函数大小或 −10.67% part_18 改善套用到此版本。

候选 binary 为 116,032,112 bytes，SHA256：

```text
34cd97f095e88a7bc2f4bed6eac8ac7794eabad0927af8b924fe883d984cf78a
```

本篇完成 seed7 验收。默认策略还需结合独立 seed1 对照，不以单个分区方案的收益直接决定。

## 归档

- [正式报告](../../build/artifacts/repcut-short-reduction-20261112/strict-generated-report.json)、[逐对 CSV](../../build/xs/repcut-short-reduction-20261112/measure-strict-generated/pairs.csv)、[原始运行与放置证据](../../build/xs/repcut-short-reduction-20261112/measure-strict-generated/)
- [源码子集审计与表达式检查映射](../../build/xs/repcut-short-reduction-20261112/strict-generated/strict-source-audit.json)、[逐文件比较](../../build/xs/repcut-short-reduction-20261112/strict-generated/source-comparison.json)
- [边界测试通过记录](../../build/artifacts/repcut-short-reduction-20261112/strict-focused-pass.json)、[完整 emitter 回归](../../build/artifacts/repcut-short-reduction-20261112/strict-regression-pass.json)
- [输入身份](../../build/xs/repcut-short-reduction-20261112/strict-generated/inputs.json)、[配置](../../build/xs/repcut-short-reduction-20261112/strict-generated/configuration.json)、[构建日志](../../build/artifacts/repcut-short-reduction-20261112/strict-build.log)
