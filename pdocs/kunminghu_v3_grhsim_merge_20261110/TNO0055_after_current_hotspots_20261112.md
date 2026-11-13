# TNO0055：两轮译码优化后的 after 当前瓶颈

日期：2026-11-12（America/Los_Angeles）。在 [TNO0054](./TNO0054_wide_reduction_default_enabled_20261112.md) 默认开启宽归约之后，重新采样主线 after seed7，核对当前最慢分区及其剩余工作。没有修改生产代码或默认配置。

## 当前主线结果

主线对象是已开启共享 Boolean 掩码和宽 concat 归约的 after seed7，Clang 23 binary：

```text
999c1f42a6bc3090a2801168f936432dd15777caaab4136705835dc7933be51a
```

沿用 TNO0051 的正式 8 对中候选 B 数据，CoreMark 100k、完整 DiffTest、node030/CPU96–127、NUMA1 bind、ASLR off。以下是 8 个有效样本的累计分项时间中位数：

| 阶段 | 时间 |
|---|---:|
| part_eval | 11.2560 s |
| global_update | 1.3916 s |
| input_load | 0.4522 s |

part_eval 占三个阶段时间总和的比例中位数为 **85.91%**，仍是主要阶段。

| 分区 | eval 时间 | update_push 时间 |
|---|---:|---:|
| part_18 | **8.4055 s** | 0.5520 s |
| part_19 | **7.4116 s** | 0.6396 s |
| part_23 | **6.7652 s** | 0.9257 s |
| part_14 | 5.8815 s | 0.4318 s |
| part_15 | 5.7694 s | 0.4103 s |
| part_8 | 4.0459 s | 0.2115 s |

当前优先对象仍是 **part_18**，但 part_19 和 part_23 已是明确的后续限制。各分区并行运行，不能将这些时间相加为 walltime，也不能把 part_eval 与最大累计分区时间之差直接解释为调度开销；不同周期的最慢分区可能不同。

## 最新动态采样

对同一冻结 binary 新做两次 `perf record -e cycles:u -F 997 --sample-cpu`，均通过完整 DiffTest、功能签名、32 个 singleton affinity 线程、NUMA locality、ASLR 和 code-page 检查。没有外部 CPU 空闲准入检查。采样运行仅用于归因，不替代上述正式 walltime。

用 ELF 基址及符号解析重映射代码页，分别检查 CPU114/115/119，即 part_18/19/23。下表分母为各 CPU 上这个进程的全部用户态采样周期，包含等待，不是整机 walltime 占比：

| 类别 | part_18 | part_19 | part_23 |
|---|---:|---:|---:|
| compute batch | 55.11% | 40.23% | 39.14% |
| eval 主函数自身 | 2.99% | **8.52%** | 4.33% |
| commit batch | 3.19% | 3.22% | 4.59% |
| update 与 tracked copy | 3.10% | 4.06% | **5.91%** |
| worker loop | 33.28% | 39.40% | 42.01% |
| 未解析 | 1.15% | 3.15% | 2.41% |

其余为 output refresh 和其他已解析代码。worker loop 的高权重 IP 仍位于 stop/work atomic 的 `pause` 轮询，不能将它们当作译码计算或可直接回收的 walltime。

最热 10 个 compute batch 只占各自 compute 样本的 **13.02% / 14.77% / 12.30%**。当前成本分散，没有一个函数代表整个分区。

## part_18：短字段条件及组合译码仍是明确入口

part_18 最热 compute 仍包括 batch 160、242、161，分别占该 CPU 样本的 1.325%、0.869%、0.832%。对这些对象添加 line-table 调试信息，并验证 `.text` 与冻结 archive 逐字节相同后，将旧 binary 采样地址映射到当前源码。

batch_160 的源码行归因中，**95.90%** 的函数样本落在包含 `grhsim_reduce_and_u64` 的 Boolean 表达式行；batch_161 为 80.93%、batch_242 为 81.44%。这些比例包含字段读取、移位、AND 条件和外围 OR 组合，不能全部称为 helper 本体成本。

宽数组打包已消除，但 OR 的每个输入仍常由短 concat→AND 条件组成，重复读取、移位和条件组合仍在。batch_160/161 的命名输出明确涉及 `decodeChannels/uopBufferCtrlDecoder/uopSelectMod`；batch_242 是译码、dispatch 和 issue queue 的混合范围。不能把整个 part_18 都归为向量译码。

下一步优先审核短字段条件共享及 Boolean 表达式复用，继续按真实使用者、输入稳定性和收益门约束，不把最小字段数简单放宽后全图应用。

## part_19：输入变化与激活传播值得单独处理

`eval_with_input_changes` 是该 CPU 最显著的单个非等待函数，占 **8.52%**。将等机器码的源码行按实际区域归类：

| eval 主函数内部区域 | 占该函数样本 |
|---|---:|
| 输入变化比较、XOR delta 与激活传播 | **76.39%** |
| 上一拍输入快照更新及退出 | 10.47% |
| round/batch 调用与控制 | 7.14% |
| 入口及初始化 | 1.26% |
| 未定位到非零源码行 | 4.74% |

输入比较/激活区域本身约占 CPU115 全部采样的 **6.51%**。源码可见宽输入与 `prev_in` 比较、逐 word XOR、按 mask 聚合差异、写入 supernode 活动位；因此不能将整个 eval 主函数称为“batch 调用开销”。此外，末尾持续更新上一拍输入快照。

该路径可以作为第二优先级，审查已有变化信息是否被充分复用、是否能减少重复扫描和快照拷贝。当前没有做这项优化的因果对照，不能把上述占比直接作为预计整机收益。part_19 的 compute 本身也很分散，代表 batch_84 包含状态读取、打包与组合选择等混合工作。

## part_23：跨分区宽数据更新与状态工作

part_23 的 update_push 正式中位数为 **0.9257 s**，高于 part_18/19。新采样中可见 `copy_tracked_wide_words_<912>`、`<658>` 等宽数组拷贝/变化跟踪 helper；update/tracked-copy 共占 CPU119 样本约 5.91%，commit 约 4.59%。

其 eval 主函数的输入变化/激活区域占函数样本 70.22%，约占 CPU119 样本 3.04%，与 part_19 属于相似的分区接口工作。将来优化这条公共路径，可能同时覆盖多个分区；是否缩短整机等待仍需验证。

## 判断边界

- 当前首要方向：part_18 的短条件译码与表达式复用。
- 第二方向：part_19 的输入变化检测、活动传播及上一拍快照；part_23 的宽 copy/update 同时关注。
- [TNO0049](./TNO0049_part18_dispatch_guard_control_20261111.md) 的单纯 batch 调用前检查已未测出稳定收益，不因空调用多而重复默认开启。
- 这些分区包含混合硬件功能，当前证据不足以把成本统一归因于 DiffTest observer，也没有指向新的 Clang 功能错误。
- 如果“after”指独立 seed1，编号会不同：其最新正式 eval 中位数最慢为 **part_15 9.5789 s、part_16 8.6477 s、part_3 7.9836 s**。本轮新采样针对主线 seed7，不将两个分区方案混为同一个热点图。

## 归档

- [机器可读报告](../../build/artifacts/repcut-after-hotspots-20261112/report.json)
- [两次原始采样与放置证据](../../build/xs/repcut-after-hotspots-20261112/)、[采样脚本](../../build/artifacts/repcut-after-hotspots-20261112/profile.py)、[ELF 解析](../../build/artifacts/repcut-after-hotspots-20261112/analyze_samples.py)
- [六个对象的等机器码行映射](../../build/xs/repcut-after-hotspots-20261112/source-lines/report.json)、[行映射脚本](../../build/artifacts/repcut-after-hotspots-20261112/source_lines.py)
- [正式计时来源](../../build/artifacts/repcut-wide-reduction-20261111/generated-report.json)、[汇总脚本](../../build/artifacts/repcut-after-hotspots-20261112/report.py)
