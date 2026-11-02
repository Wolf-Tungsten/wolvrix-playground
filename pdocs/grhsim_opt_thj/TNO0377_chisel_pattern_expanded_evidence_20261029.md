# TNO0377：参数扩展、生产末端规则与广泛调查结果

日期：2026-10-29。承接 [首轮实验](./TNO0376_chisel_pattern_first_microbench_20261029.md)。

## 覆盖与实验身份

目录已由初始六个方向扩展为 51 项开放候选，来自 1,507 个 Scala 文件和 12 个源码组。
既包含 Chisel/util，也包括具体设计中的年龄矩阵、压缩译码、浮点表示转换、延迟寄存器映射、
门控更新、直方图以及高扇出传播。未匹配目录的文件仍完整列在 inventory.json 中。
这表示可复查的词法覆盖和定向源码审阅，不是 1,507 个文件都已人工逐行审核。

最终主实验在 [node030-normalized-v5](../../wolvrix/build/artifacts/chisel-pattern-study/node030-normalized-v5/)。
47 个实例均通过两组种子、五种输入分布，每组 100,000 个输入／周期；小空间另做穷举。
合计 47,463,120 个检查步骤。状态例子比较时钟沿前与沿后输出，增加了表项遍历、队列满空与
同时入出队、CAM 多重命中及有效位、直方图边界。每种分布 8 对 AB/BA，共 1,880 对。

验证器还注入了一个错误软件输出，确认差分会以 mismatch 拒绝；证据在
[fault-check](../../wolvrix/build/artifacts/chisel-pattern-study/fault-check/result.json)。

## 与生产末端变换对齐

早期 raw 实验经过正常 frontend 和 emitter，但没有应用分区后两步 storage 规则。
从 normalized-v4 开始补上 memory-write-coalesce、reg-to-mem；后者使用与当前
`grhsim32_partition replay` 一致的 VerilatorV1 profitability，enableIntent=false。
最终 v5 使用同一配置。小模块仍不复现 32 分区、跨模块传播或整机通信。

在 `table64_indexed`，变换日志显示 64 个 single-write register，但没有发现可合并的组；
归一化 GRH 仍有 64 个 kRegister、64 个 kRegisterWritePort、63 个 kMux。
`decoded_write_discovery` 的 max_update_terms=2，源码该识别分支要求至少 64 个
decoded write alternatives；这里的 wide_update 指 alternatives，不能误读成数据位宽。
因此不是 profitability 拒绝了已识别数组，而是当前结构没有进入候选集合。
这是 Chisel 层保留 indexed-storage 语义可能有价值的具体依据。

## 组合体随机输入结果

下表使用去掉外层派发、保留真实算式和 slot 物化的计算体；软件时间来自同一对照序列。
所有结果只适用于列明参数、当前 Clang 和 AMD EPYC 9684X / -march=native。

| 实例 | 生成计算体 ns | 软件 ns | 配对变化中位数 | 8 对变化范围 |
|---|---:|---:|---:|---:|
| popcount16 | 1.80 | 1.52 | -14.9% | -29.7% ～ +1.5% |
| popcount32 | 2.27 | 1.50 | -33.9% | -40.3% ～ -27.5% |
| popcount64 | 4.15 | 1.52 | -63.5% | -67.2% ～ -59.1% |
| priority16 | 4.04 | 1.52 | -62.4% | -66.2% ～ -58.8% |
| priority64 | 19.97 | 1.51 | -92.4% | -93.1% ～ -91.6% |
| ones_recursive | 10.39 | 1.53 | -85.3% | -86.8% ～ -82.4% |
| ones_recursive16 | 18.30 | 1.53 | -91.6% | -92.5% ～ -90.7% |
| rotate8 | 21.29 | 1.51 | -92.9% | -93.6% ～ -92.1% |
| barrel8 | 7.49 | 1.52 | -79.6% | -81.5% ～ -77.6% |
| gray_decode32 | 17.94 | 1.50 | -91.6% | -92.3% ～ -90.7% |
| decode16 | 3.88 | 1.50 | -61.2% | -64.9% ～ -57.5% |
| decode_table | 196.21 | 1.52 | -99.2% | -99.3% ～ -99.2% |
| bit_extract64 | 1.68 | 1.53 | -8.8% | -18.1% ～ +0.1% |
| bit_deposit16 | 1.79 | 1.40 | -21.8% | -27.9% ～ -14.7% |
| prefix_dense | 6.95 | 6.54 | -5.9% | -8.6% ～ -5.6% |
| prefix_ripple | 6.67 | 6.53 | -2.0% | -2.4% ～ -1.4% |
| mux1h8 | 1.94 | 1.80 | -6.9% | -15.5% ～ +1.1% |
| ecc32 | 2.22 | 2.22 | +0.2% | -1.5% ～ +1.4% |
| crc16 | 2.23 | 5.65 | +154.1% | +152.9% ～ +157.7% |
| crc16_table | 6.96 | 1.59 | -77.6% | -79.3% ～ -76.0% |
| sort4 | 2.51 | 16.44 | +553.5% | +479.4% ～ +563.1% |
| sort4_network | 2.51 | 2.77 | +10.4% | +9.2% ～ +11.2% |
| guarded_div32 | 1.66 | 2.32 | +40.0% | +27.3% ～ +58.6% |
| wire64 | 1.65 | 1.51 | -8.6% | -17.7% ～ +0.6% |

## 从结果得到的判断

- **语义丢失有实质成本的例子**：优先编码、Gray 解码、旋转、重复选择、递归基数判断、
  完整 LUT。它们适合继续研究明确语义操作或编译器 combine。
- **需要看参数与布局**：16/32/64 位 PopCount 的差异不同；真实香山 count 的分散输入
  进一步削弱了 popcount 的收益，见下一篇冻结代码实验。
- **已经较紧凑的例子**：parity、SEC encode、部分 mux、前缀累计。不能按源代码树层数
  推算可消除的机器指令数。
- **软件算法也会退化**：std::sort 对 4 元素随机键远慢于生成的条件移动网络；固定软件
  网络接近，但未自动超过生成实现。CRC 位串行除法较慢，改成同一多项式的查表后才改善。
- **ISA 与部署条件**：UIntCompressor/UIntExtractor 的软件候选使用 BMI2 pext/pdep；
  只在本机目标指令集下成立。非 BMI2 有循环 fallback，未测量其跨架构性能。
- **guard 不是自动优化理由**：guarded_div32 的生成体在随机输入下优于直接 if 软件写法。
  这里除数被显式置为奇数；没有把除零语义不同的版本放进比较。
- **改变表示比换指令更大**：状态表、CAM 与 histogram 的整体软件组件较小，但时间差
  同时包含独立模块的调度、提交和观察成本；不能据此直接报整机收益。

## 状态与观察范围对比

| 实例 | 完整模型 ns | 软件组件 ns | 观察契约 |
|---|---:|---:|---|
| table16 | 33.21 | 6.17 | 动态读 + 所有表项 xor |
| table64 | 204.11 | 7.64 | 动态读 + 所有表项 xor |
| table64_indexed | 181.51 | 3.06 | 只读动态索引端口 |
| cam8_state | 33.10 | 7.96 | 真实 IndexableCAMTemplate + valid 包装 |
| queue8 | 30.72 | 3.76 | pipe=false, flow=false |
| queue8_flow | 32.15 | 3.62 | pipe=false, flow=true |
| histogram8 | 29.83 | 6.21 | 8 个裁剪桶；无日志与 mean |
| gated_reg64 | 22.12 | 1.53 | 自比较 enable |
| plain_reg64 | 22.95 | 1.51 | 普通 RegNext |

GatedRegNext 和普通 RegNext 的独立轮次有小差异，但没有同一可执行文件中专门针对这两种
硬件写法做配对，因此不能把跨 case 的差值报告成源代码优化收益。现阶段没有证据支持
把这类 utility 一概禁用。

## 暂未进入模型替换的具体边界

- **SRT16Divider** 有 7 态控制、kill_w/kill_r、特殊输入路径和数据相关迭代。
  用 host 除法得到最终数值并不证明每拍 ready/valid 和取消语义相同。
- **HardFloat / YunSuan** 包含 recoded 表示、非规格化数、NaN、舍入和异常标志；
  当前未实现覆盖这些规则的完整软件模型，不把 host float 当等价实现。
- **MIMOQueue** 的各端口 fire 影响后续端口指针和整体指针更新，还带 flush/perf 分支。
  本轮单端口 Queue 的结果不推广到它。
- **MaskedRegMap** 源码明确增加 RegNext 以降低扇出；软件表必须保留延迟写入及读写函数。
- **HwSort** 含 invalid 元素稳定性与 CircularQueuePtr 比较。本轮无符号排序实验只覆盖
  比较交换机制，不覆盖完整模块契约。
- **AgeDetector** 多入队顺序和无效项处理与缩小单端口例子不同。时间戳替换还需要
  回绕、可观察状态和非法输入域证明。
- **ClockGate**、多时钟/异步复位需要事件/透明相位模型；不能仅用逐拍 enable 代替。
- **DPI、日志、性能观测** 具有调用顺序和可见状态；本轮从未通过删除它们制造收益。

这些条目在目录里保留源码、成本假设、替代方向和限制；并未冒充已确认热点或已通过等价。

## 可复查入口

- [中文交互报告](../../wolvrix/build/artifacts/chisel-pattern-study/survey/report.html)
- [中文全文与案例卡片](../../wolvrix/build/artifacts/chisel-pattern-study/survey/report.md)
- [全部逐分布 CSV](../../wolvrix/build/artifacts/chisel-pattern-study/node030-normalized-v5/results.csv)
- [哈希与采样完整性校验后的结果](../../wolvrix/build/artifacts/chisel-pattern-study/node030-normalized-v5/validated_results.json)
- [用法](../../docs/chisel-simulation-pattern-study.md)

## 增量更新 2026-10-29：覆盖补充与 CRC 反证

源码清单从 1,507 扩大到 1,583：新增固定 Chisel sources.jar 中此前未列入的 75 个
CIRCT/FIRRTL 等 Scala 文件，以及仓库中的一份配置源码。最终 Chisel jar 的 332 个
Scala 文件均已登记；主要用于补齐 elaboration/接口可行性，不暗示这些宿主代码每拍执行。

CRC 部分需要更新判断：同一生成计算体在不同 binary 的基线时间不同。追加同一 binary、
共同调用循环后，查表不再优于生成体，位串行仍退化。原表保留，但“查表后改善”仅适用于
原实验上下文，不能作为推荐替换结论；完整反证见
[TNO0379](./TNO0379_chisel_crc_call_context_control_20261029.md)。

所有 51 个候选现已逐项补齐硬件结构目的、已有优化/实证、明确处置和下一步条件。
最终交付与接口工作边界见 [TNO0380](./TNO0380_chisel_pattern_delivery_and_ir_design_20261029.md)。
