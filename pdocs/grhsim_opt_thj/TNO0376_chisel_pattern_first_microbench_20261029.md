# TNO0376：广泛模式调查——首轮微基准、校准与反例

日期：2026-10-29。关联：[调查进度](./TNO0375_chisel_simulation_pattern_survey_progress_20261029.md)。
本记录冻结第一批结果；后续参数扩展及改进软件模型另篇记录。

## 范围和产物

- 词法扫描 1,507 个 Scala 文件、12 个源码组，整理出 46 项候选。
- 扫描冻结香山全部 7,412 个 schedule C++ 文件，共 1,685,265,822 字节。
- 原生 source CSV 共 7,519,299 条操作；保存选定 RTL 文件的 385,458 条归属统计，
  聚合成 2,455 个 RTL 文件/batch 组合。这些不是逐行时间。
- [覆盖与候选](../../wolvrix/build/artifacts/chisel-pattern-study/survey/report.md)、
  [完整覆盖清单](../../wolvrix/build/artifacts/chisel-pattern-study/survey/coverage.csv)、
  [操作证据](../../wolvrix/build/artifacts/chisel-pattern-study/survey/operation_evidence.json)。
- 本轮结果固定在 [node030-v2](../../wolvrix/build/artifacts/chisel-pattern-study/node030-v2/)，
  后续版本不覆盖此目录。

## 基准校准与失败记录

第一版直接比较生成模块 eval 与软件 helper，发现即使直连也存在约 10 ns 的模块
调用、输入变化检测和输出处理成本。不能把这个差额解释为某个 utility 的算法成本。
因此补了两项控制：`wire64` 与 `native_add64`；组合实验增加从真实生成代码抽取的
计算体，并采用与软件 helper 相同的单次函数调用 ABI。

抽取器保留原始 group 内算式、slot 访问和输出物化，去掉外层活动派发。它不是整机
中的独立时间测量，也不是完全无物化的数学表达式。每个输入都同时检查 normal eval、
抽取体和软件实现的输出一致。包含 state 的案例只比较完整周期模型，不抽取提交过程。

试运行发生并已修正：

1. Chisel 7.3.0 layer 默认生成外部 include；单字符串输出缺少辅助文件。改用与生产
   debug 类配置一致的 `--default-layer-specialization=enable`，保留断言，不用忽略 include 绕过。
2. `Bool.asUInt.pad(5)` 的动态类型路径触发 elaboration require。fixture 改为显式
   `Cat(0.U(4.W), bit)`；这是宽度表达修正，不是仿真性能优化。
3. 多 group 计算体仍引用局部 `activeWordFlags`。抽取器为保留的组体提供局部变量，
   并对所有样本做输出差分；未识别的派发格式拒绝抽取。

这些失败保存在早期 `run1`、`node030` 的日志中，未把失败样本混入正式计时。

## 条件与正确性

node030，AMD EPYC 9684X，CPU96，当前 Clang 和 `-std=c++20 -O3 -march=native`。
先完成所有编译，再串行计时。每个实例两组独立固定种子，random/sparse/hold99
三种分布各 100,000 次检查；较小输入空间另做穷举。每种分布 8 对 AB/BA，输入生成
不在计时区，保留结果 checksum。30 个实例均通过。

原始逐对数据在各 case 的 `measurement.json`，编译参数、输入哈希和二进制哈希在
`build.json`，机器信息在 `environment.json`。共享服务器上没有声明独占整机；这些
数据只用于局部微基准，不是香山 walltime。

## 首轮随机输入结果

以下为 ns/调用的中位数；软件列取与计算体配对的测量。小于约 1 ns 的差异必须结合
控制例子、重复分布和机器码理解，不能据此声称稳定整机收益。

| 实例 | 生成计算体 | 软件表达 | 解释 |
|---|---:|---:|---|
| 16-bit PopCount | 1.80 | 1.50 | 位求和已被 LLVM 向量化，但没有恢复为单次 popcount |
| 64-bit PopCount | 4.15 | 1.52 | 向量移位/掩码/归约仍较长，完整计数语义值得保留 |
| PriorityEncoder 64 | 19.90 | 约 1.5 | 位扫描是强候选；零输入语义由 wrapper 明确定义 |
| VecRotate 8×8 | 21.21 | 约 1.5 | 枚举旋转加 Mux1H 的数据重排成本显著 |
| GrayToBinary 32 | 17.97 | 约 1.8 | 逐 bit 前缀 xor 与 5 次字级 xor-shift 存在明显差异 |
| OnesMoreThan(12,3) | 10.46 | 约 1.5 | 递归组合条件的剩余计算较多 |
| 256 项完整 MuxLookup | 195.00 | 约 1.6 | 直接 LUT 强，但只证明该完整表实例，不能推广到全部 BitPat |
| DensePrefixSum 16 | 6.94 | 6.51 | 已被后端处理得较好，剩余差异很小 |
| RipplePrefixSum 16 | 6.63 | 6.51 | 与直接软件累计接近 |
| 小型 CAM 组合读 | 2.08 | 约 2.2 | 编译器已向量化/简化，简单扫描没有明显优势 |
| SEC encode 32 | 2.21 | 约 2.2 | 已有字级 parity，软件改写近乎无差异 |
| 4×16-bit 排序网络 | 2.52 | 15.25 | `std::sort` 反而慢约 5 倍；网络被编译为紧凑 cmov |
| CRC16/32-bit 输入 | 2.19 | 约 5.6 | 软件逐 bit 除法不如生成的 parity 网络，继续测试查表版本 |
| 直连控制 | 1.52 | 1.53 | 单函数调用和内存输入的基本成本 |

完整数值和所有分布以原始 JSON 为准。这里的 `sort4` 是所有元素有效、普通无符号键的
网络例子，不是 `HwSort` 完整的 valid/环形指针契约；`age8` 是明确缩小的单入队矩阵，
不是任意香山 AgeDetector 配置的替代实现。

## 机器码证据与新问题

PopCount 16/64 的计算体可见 `vpsrlvq`、掩码和 SIMD 归约。不能因为 C++ 很长就
认为编译器完全没有优化。GrayToBinary 保留逐位 `bextr/xor` 链；排序网络使用
`cmp/cmov`，解释了通用排序算法在小规模上退化的可能原因。没有 PMU 证据时，不把
分支存在直接解释为 branch miss，也不把大代码直接解释为 I-cache miss。

源码扫描还发现 `GatedRegNext` 自己比较新旧值并生成 enable，仿真提交也比较新旧值。
这可能产生冗余检查，但需要与普通 RegNext 做同语义对照，不能只凭源码判断。

## 下一批已开始的工作

- PopCount、优先编码、递归计数谓词、mux 和 LUT 的参数变体。
- CRC 查表和固定排序网络两个更合适的软件候选，保留第一版退化结果。
- 64-entry 状态表、flow Queue、真实 IndexableCAMTemplate 加有效位包装。
- GatedRegNext 与普通 RegNext 同语义对照。
- 从未分类源码和反向热点继续发现新模式；不以本轮 46 项为固定范围。
