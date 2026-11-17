# TNO0044：按计算依赖和完整激活来源形成共享候选

承接 [TNO0043](./TNO0043_cv32_series_xiangshan_codegen_lineage_20261116.md)，本轮先实现共享候选形成规则，复用已有局部 SCC 细分。packed-array 元数据、对齐读取及 indexed-concat 捕获问题保留到独立实验，不与本轮合并。两种模型的固定三对验证已完成；规则与模型在测量后没有改动。

## 固定规则与对照

新增默认关闭的 `eventRegionsSharedConnected` / `-event-regions-shared-connected` / Python `event_regions_shared_connected`。保留完整 compute node、原 effect/event/intent 保护、32 个终点与 8192-op 上限。

1. 在同终点集合内，按真正的计算 def-use 边形成组件；constant 和 register-read 边不作为计算连接。
2. 无计算的读源节点只在全部出边属于同一组件时随组件移动。
3. 独立组件的全部外部非常量 ValueId 与直接读取的寄存器状态符号组成静态激活键。只有完整键相同且非空、来源已知，才合并。共同终点、部分输入重叠都不足以合并。
4. 候选的计算节点必须跨至少两个原组，且实际内部化旧计算边界，或发生上述完整激活键合并；仅抽走原本局部的计算或附带读源不算收益。
5. 未选中节点保留原分组。使用 TNO0037 的 quotient-SCC 算法，只细分造成环的余部，无法消除的循环候选回退。没有重新启用全量按终点拆分余部。

本轮没有改变 emitter、状态表达式预算或其他默认值。没有模型名称、运行次数、trace、walltime 或 PMU 输入生成规则；在测量前冻结规则。局部 SCC 是预先固定的组合，其收益不能全部归因到新候选形成。

两个整机使用相同的 native 库与生产源码快照，[交叉身份检查](../../build/xs/shared-connected-20261116-v1/cross-model-freeze.json)通过。新选项关闭时分别要求逐文件重现 TNO0042 corrected full；修复版 full 和同生成器的 no_shared 是共同版本控制。

- XiangShan：corrected full、新候选、corrected no_shared，3 轮正反序；完整 DiffTest，先 10k-cycle smoke 和两个 seed 的 100k-cycle trace，随后固定 100k-cycle 计时窗口。此范围不是完整 CoreMark 结束。
- CV32：corrected full、新候选、同归一化 RTL Verilator，完整 CoreMark 与总线 trace，3 轮正反序。
- 性能串行在 node030 CPU96、NUMA1、ASLR off、单线程执行，使用共同文件锁。所有样本保留；沿用 XS 原有 skip-external-idle-admission，CPU/NUMA/ASLR 等放置门仍强制。

## 结构与功能

| 指标 | 原共享 full | 新候选 |
| --- | ---: | ---: |
| XiangShan compute 区域 | 97,204 | 84,690 |
| XiangShan 细分旧组 | 10,388 | 2,433 |
| XiangShan 接受共享候选 | 6,542 | 10,544 |
| CV32 全部区域 | 39 | 25 |
| CV32 状态视图 | 91 | 91 |
| CV32 其中复合表达式 | 70 | 70 |
| CV32 受跟踪值 | 118 | 117 |

新规则先形成 99,088 个 XiangShan 计算组件，发生 20,663 次完整激活键合并，67,857 个组件缺少所要求的跨组收缩，24 个超过既有大小上限。候选可以来自原来整个终点池超过上限、但分解后的组件满足上限的集合，因此候选数量不能解读为旧 6,542 个候选的简单子集。局部细分一轮，没有未解决循环候选；commit 顺序保留，最终精确依赖重建通过。

CV32 的 91 个视图逐项核对 value/source/mode，70 个复合表达式逐项核对 value/ops/mode，身份一致。原 6 个共享组保留 5 个，共 1526 ops；新形成组未触发 SCC 细分。仅统计视图数相同不足以作此结论，所以同时检查了具体身份和生成证明条件。

CV32 完整功能及总线 trace 通过。独立计数使用重新构建的诊断模型，与对应生成源码、header 和 probe 顺序逐项核对：

| CV32 每 guest cycle | full | 新候选 |
| --- | ---: | ---: |
| compute 区域执行 | 17.0759 | 13.5421 |
| scalar 比较 | 82.8356 | 84.5730 |
| scalar 变化 | 17.1461 | 16.4422 |
| 活动位 OR 源码执行 | 28.5263 | 28.6241 |
| 固定点轮数 | 3.0000 | 3.0000 |
| commit 区域执行 | 6.0000 | 6.0000 |

275 项可比值/缓存/条件计算计数中，264 项相同，11 项比较次数变化；保留值的变化次数、缓存访问/未命中、译码访问和条件锥分支计数保持一致。10 个比较原属 full 的多个细分余部，新版本回到同一个原始组，因此执行更频繁；另一个比较多执行 3 次。变化检查总量上升，不能用区域数降低直接推断运行收益。[计数证据](../../build/cv32e40p/shared-connected-v1/count-analysis.json)、[变化检查归属](../../build/cv32e40p/shared-connected-v1/changed-check-ownership.json)。

## ELF 与数据布局

| XiangShan compute ELF 静态指标 | corrected full | 新候选 | corrected no_shared |
| --- | ---: | ---: | ---: |
| 指令 | 14,108,784 | 13,755,365 | 14,274,240 |
| 条件跳转 | 590,476 | 563,299 | 544,689 |
| 内存操作数指令（不含 lea/nop） | 5,632,177 | 5,480,957 | 5,730,723 |
| RSP 内存操作数指令 | 1,104,442 | 1,129,226 | 1,174,679 |

新版本相对 full 的 compute 静态指令减少 2.505%、条件跳转减少 4.603%，RSP 操作数反而增加 2.244%。这些不是退休指令或动态 spill 数，不能直接换算加速；相对 no_shared 的条件跳转仍多 3.417%。[完整静态报告](../../build/xs/shared-connected-20261116-v1/offline-structure/candidate.json)。

FTQ 的 64 个原始 concat op 符号全部匹配，现分布在 64 个不同组。对两侧同一组 4,096 个状态字段逐 lane 核对，并编译 offsetof 探针：全部 64 个数组的相邻 lane 状态字段地址步长，从 full 的 64 B 恢复为 1 B（源码从 lane63 向 lane0 赋值，因此报告中带负号）。这里没有启用 TNO0040 的显式 packed-access 布局规则，而是恢复独立读者集合后，既有布局规则自然得到连续排列。[全 bank 位置证明](../../build/xs/shared-connected-20261116-v1/offline-structure/ftq-bank-layout.json)。

其中 `packed_array_lanes_788579_0_…_GEN_15_` 的 ELF 构造核心为三条：从 `this+0x358ac9` 加载 64 B、向量 mask、写到 `this+0xa300`。两端地址与独立偏移探针吻合；该窗口没有逐字节 `vpinsrb` 拼接。该单数组的指令证据与全 bank 的布局证据分别记录，不将一个窗口的指令数外推到全部数组或所有动态周期。[偏移与反汇编](../../build/xs/shared-connected-20261116-v1/offline-structure/ftq-layout.json)、[窗口](../../build/xs/shared-connected-20261116-v1/offline-structure/ftq-array-windows.s)。

CV32 compute ELF 静态指令 10,576→10,565，条件跳转 181→153，RSP 操作数 2,059→2,183；compute 函数从四个变为三个。机器码总量变化很小，不能把其收益解释为大量计算消失。[CV32 ELF](../../build/cv32e40p/shared-connected-v1/machine-evidence/report.json)。

## 三对测量

CV32 已完成：新候选相对 corrected full 外部 walltime **−0.5686%**，bootstrap 95% CI **[−0.7037%, −0.4770%]**，3/3 对更快；相对同归一化 RTL Verilator **−3.7812%**，CI **[−4.1416%, −3.3665%]**。这是用户指定的三对初测，保留全部样本。[CV32 原始配对](../../build/cv32e40p/shared-connected-v1/pairs.json)、[统计](../../build/cv32e40p/shared-connected-v1/summary.json)。

XiangShan 外部 walltime：

| 对照 | 平均变化 | bootstrap 95% CI | 候选更快 |
| --- | ---: | --- | ---: |
| 新候选 / corrected full | **−8.0684%** | [−10.1439%, −5.6757%] | 3/3 |
| 新候选 / corrected no_shared | −0.7279% | [−2.2258%, +1.0049%] | 2/3 |
| corrected no_shared / corrected full | −7.4025% | [−8.0983%, −6.6141%] | 3/3 |

三轮原始 walltime（秒，始终按 full / 新候选 / no_shared 列出）：

| 轮 | full | 新候选 | no_shared | 实际顺序 |
| --- | ---: | ---: | ---: | --- |
| 0 | 124.570849 | 117.500534 | 116.331566 | full → 新候选 → no_shared |
| 1 | 124.884826 | 114.412480 | 115.524778 | no_shared → 新候选 → full |
| 2 | 123.290895 | 110.784409 | 113.306415 | full → 新候选 → no_shared |

host_ms 的对应变化为 −8.0724% 和 −0.7297%，与外部方向一致。候选三轮均快于 full，但相对关闭共享的区间跨零，不能据此宣称稳定超过 no_shared；候选自身也有时间波动，不把这一小样本区间解释为跨负载保证。不用该轮绝对时间与历史 before 版本跨轮相减。[原始轮次](../../build/xs/shared-connected-20261116-v1/measurement/rounds.json)、[完整统计](../../build/xs/shared-connected-20261116-v1/report.json)。

两 seed 的候选及 no_shared 轨迹各与 full 的 99,999 条记录一致，覆盖检查通过。独立审计复算所有统计，核对 XiangShan 的 21 次运行（其中 9 次正式样本）、4,297 次线程/CPU 快照及 437 次原始 NUMA 快照；CV32 的 9 次正式样本与 18 次首尾放置/NUMA 快照通过。没有重试、删样本或追加轮次。[XiangShan 审计](../../build/xs/shared-connected-20261116-v1/independent-review/review.json)、[CV32 审计](../../build/cv32e40p/shared-connected-v1/independent-review.json)、[串行顺序](../../build/xs/shared-connected-20261116-v1/serial-measurements.json)。

本轮在保留 CV32 原有视图优化的同时，改善了两边相对当前 full 的性能，并使 XiangShan 接近关闭共享的参考。主要结构变化是减少独立计算池化、恢复读者区分与连续状态布局；实际收益还包含代码分块、缓存机会和寄存器分配变化，不能逐项精确分摊。新开关保持默认关闭，生成规则没有运行反馈选优。

## 验证与产物

5 项 CTest 已通过：候选组件、局部 SCC、connected 生成模型、原事件区域和原局部 SCC 生成模型。生成模型检查包含多时钟、异步复位、存储器写前快照、掩码写入、effect 原上下文保护、O0 及 O3 ASan/UBSan。13 项已有协议/计数 Python 测试通过；12 项 Python 选项编译测试用当前 wrapper 函数隔离 native extension 后通过。首次隔离 runner 漏装一个 helper，补齐后通过，保留两份日志；不是生产规则或仿真失败。

[测试身份](../../build/xs/shared-connected-20261116-v1/test-validation.json)、[功能文档](../../wolvrix/docs/transform/activity-shared-event-regions.md)、[XiangShan 对照工具](../../scripts/xiangshan_shared_connected_compare.py)、[CV32 对照工具](../../scripts/cv32e40p_shared_connected_compare.py)、[分析脚本](../../scripts/shared_connected_analysis.py)、[XiangShan 产物](../../build/xs/shared-connected-20261116-v1/)、[CV32 产物](../../build/cv32e40p/shared-connected-v1/)。

最终源码身份、统计方向、串行执行、产物与文档链接检查见 [归档验证](../../build/xs/shared-connected-20261116-v1/validation.json)。
