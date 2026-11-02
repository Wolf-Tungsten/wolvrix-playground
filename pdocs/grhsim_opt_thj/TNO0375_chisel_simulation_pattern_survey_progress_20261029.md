# TNO0375：Chisel／Verilog 仿真表达广泛调查——范围与进度

日期：2026-10-29。状态：调查与实验进行中。

本记录延续 [batch 345 分析](./TNO0374_grhsim_p0_commit_batch345_detail_20261029.md)，
研究从单个热点扩展到库、设计代码和生成结构。用户明确要求广泛调查、持续记录，
不以预先指定的六种算子或固定数量结束。后续独立实验另建记录；本文件仅追加进度。

## 已确认的环境与边界

- 当前 XiangShan 构建使用 Chisel 7.3.0 / Scala 2.13.17。
- 使用现有 `grhsim32_fresh_rtl_20261028` 冻结产物与全 32 分区动态报告作整机线索。
- 原生编译配置为 `-std=c++20 -O3 -march=native`；微基准需要在计时机器上编译。
- 仿真 frontend 的 simplify 明确选择二态。研究中的二态检查不能作为四态 RTL 等价证明。
- Chisel 的 `IntrinsicExpr` 和 DPI 接口在本机 7.3.0 sources.jar 中可查。
  自定义 intrinsic 仍需消费者实现；现有 blackbox-guard 的 stub 不是仿真模型实现。
- 既有生成器已经有 priority mux、late index、scalar concat reduction 和 same-reader
  commit grouping；发现源码形态后必须检查这些优化是否已经消除成本。

## 源码入口与新发现

扫描覆盖 XiangShan 主设计、utility、Rocket Chip、CoupledL2、HuanCun、YunSuan、
openLLC 及其配套库，以及固定版本 Chisel 的源代码。Chisel util 目录当前有 63 个
Scala 源文件，既包含硬件构造也包含 annotation、文件加载等 elaboration 功能。
扫描结果必须区分“源码出现”“实际实例化”“运行时有成本”；词法命中不是调用图证明。

| 具体入口 | 已核实的结构 | 需要实验的问题 |
|---|---|---|
| [VecRotate](../../testcase/xiangshan/src/main/scala/utils/VecRotate.scala) | 枚举所有旋转，再 Mux1H；可存 one-hot 旋转量 | 软件旋转、数据布局和 one-hot 解码成本 |
| [PrefixSum](../../testcase/xiangshan/rocket-chip/src/main/scala/util/PrefixSum.scala) | ripple、dense、sparse 多种前缀网络 | 低电路深度是否增加软件操作总量 |
| [HwSort](../../testcase/xiangshan/utility/src/main/scala/utility/Sort.scala) | 小规模稳定比较交换网络，含 valid 与环形指针比较 | 稳定性、无效元素、指针回绕与软件排序契约 |
| [AgeDetector](../../testcase/xiangshan/src/main/scala/xiangshan/backend/issue/AgeDetector.scala) | 上三角年龄状态、按行归约、多个入队端口优先级 | 位图存储与提交方式；不能直接换成没有回绕契约的时间戳 |
| [CompressUnit](../../testcase/xiangshan/src/main/scala/xiangshan/backend/rename/CompressUnit.scala) | Scala 枚举生成真值表，再硬件译码 | 表查找与硬件化布尔网络；Scala 表构造本身没有每拍运行成本 |
| [IndexableCAMTemplate](../../testcase/xiangshan/utility/src/main/scala/utility/IndexableCAMTemplate.scala) | 每个查询并行比较所有表项，输出全命中位图 | 软件扫描／向量比较；哈希表不能丢掉重复键、多重命中和索引语义 |

## 实证方法已落地的约束

新增独立 fixture 发射工具 `grhsim32_pattern_emit`，复用现有 frontend、activity-schedule
和 GrhSIM emitter，默认构建目标不包含该研究工具。后续微基准优先直接调用真实 utility，
经 Chisel → RTL → GRH → C++ 生成 baseline；手写替代实现单独保留并做差分检查。

所有例子都记录实例化参数、输入分布、编译命令、代码身份、正确性检查和逐对原始计时。
研究目标包括失败、退化和已优化案例，不能通过筛掉这些结果制造“所有软件替代都快”的结论。
小模块的完整 eval 与纯计算切片会分别标注，绝不把调度开销误称为单个算子成本。

## 待完成

- 全源码覆盖清单、开放模式目录与每项处置。
- 真实库 fixture、基准和边界差分验证。
- 冻结香山 source span／batch／C++ 反向关联。
- 组合操作、算法块和有状态组件三种双实现接口草案。
- 逐主题实验结果、中文报告和后续优先级。

## 增量更新 2026-10-29：本轮交付与持续研究入口

上面的待完成项已形成可复查交付。最终覆盖 1,583 个源码文件、51 项模式；47 个参数
实例完成真实发射、差分和配对实验。完整结果、限制与优先级见
[TNO0380](./TNO0380_chisel_pattern_delivery_and_ir_design_20261029.md)。

研究过程中保留了排序软件替代退化、实际分散 PopCount 无明显收益，以及 CRC 调用
上下文改变结论的反证。目录并未封闭：浮点/多端口/多时钟等候选有明确的后续契约需求，
不能用简化模型的通过代替完整等价。每项当前处置写入 findings.csv 与中文案例卡片。
