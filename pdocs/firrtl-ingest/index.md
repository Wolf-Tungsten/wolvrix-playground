# FIRRTL 输入支持推进文档

建立日期：2026-10-30。已完成 F01 目录/读取层迁移和 F02 属性/作用域基础；
FIRRTL parser、真实混合读取、完整 node CSE 与 nonsink 消费仍待后续阶段。
阶段状态及实际验证见下表。

目标是在 Wolvrix 内实现不依赖 CIRCT 的 FIRRTL 前端，与现有 SV 前端共同
构建设计。FIRRTL `node` 的表达式归属和结果边界以 op attribute 保存，经过
普通 GRH 优化与仿真转换后，先按 GSIM 模式比较完整 node 表达式并有条件
合并，再由 nonsink 分图构建工作节点和超节点。分图前保留不同 node 的内部
计算边界。数组保留 shape，Bundle 按现有 SV struct 规则递归拆成字段。

## 文档入口

| 文档 | 内容 |
| --- | --- |
| [architecture.md](architecture.md) | 源码组织、混合读取、类型与时序语义、node 属性及分图合约 |
| [steps.md](steps.md) | F00–F11 的依赖、交付、Make 验证入口及退出条件 |

## 已确定的设计决策

| 项目 | 决策 |
| --- | --- |
| FIRRTL 实现 | 自有 C++ lexer/parser、类型检查与 lowering；运行和构建均不链接或调用 CIRCT/firtool |
| ingest 目录 | `lib/core/ingest.cpp` 迁移为 `lib/ingest/sv.cpp`；新增 `lib/ingest/firrtl.cpp` 和共享 driver |
| 公开头文件 | 统一放在 `include/ingest/`；删除旧 `include/core/ingest.hpp`，同步迁移全部调用方 |
| 混合输入 | 一次读取事务同时接收 FIRRTL 与 SV，先解析接口及跨语言引用，再 elaboration、链接到统一 GRH |
| 聚合类型 | Bundle/struct 递归拆字段；Vector/数组维度迁移到叶子 shape，端口也保留数组 |
| node 持久化 | 使用有版本的 `firrtl.node.*` op attrs；整体 node 合并后保留全部源身份 |
| CSE 粒度 | node 内局部简化；跨 node 只对完整表达式判等，并按 GSIM 门槛合并；分图前不抽取跨 node 的公共内部 op |
| 初始共享门槛 | 等价组至少 5 个，或结果位宽 >256，或组中至少一个 node 有多个后继；判等和实际合并分开 |
| node 的使用 | 以优化后的完整 node 为初始工作单位，支持显式语义拆分和超节点合并；归属确定后在同一执行 leaf 内做 op 级 CSE |
| 无注解输入 | 纯 SV 及原生无 node 信息的区域继续现有分图；FIRRTL 片段仍保留作用域屏障 |
| 正确性 | 混合绑定、旧值采样、写优先级、memory 语义、DPI/效果均纳入验收 |
| 性能 | 分别测量输入路线、完整 node CSE 和 node 分图的收益；不预先承诺整机提升百分比 |

## 阶段看板

| 阶段 | 交付 | 状态 |
| --- | --- | --- |
| F00 | 固定输入、特性清单和对照基线 | 待实施 |
| F01 | ingest 目录迁移和公共读取边界 | 已完成（2026-10-30，验证见 steps.md） |
| F02 | node attribute schema、CSE 作用域及验证器 | 已完成（2026-10-30，验证见 steps.md） |
| F03 | FIRRTL parser、版本检查和模块接口索引 | 待实施 |
| F04 | 类型推导、组合语义、Bundle/Vector 和 node lowering | 待实施 |
| F05 | 寄存器、复位及有序数组写 | 待实施 |
| F06 | memory、效果及目标版本特性 | 待实施 |
| F07 | FIRRTL/SV 混合 elaboration、链接和 Python API | 待实施 |
| F08 | GSIM 模式 node 级 CSE、属性传递和 checkpoint | 待实施 |
| F09 | 利用 node 的 nonsink 分图 | 待实施 |
| F10 | 香山混合输入和差分正确性 | 待实施 |
| F11 | 前端/node CSE/分图性能消融、默认策略和正式文档 | 待实施 |

本方案的 CSE 依据是本地 GSIM `a3ecb26` 的 `commonExpr()`：遍历 node 的
完整表达式树判等，以整个 node 为消除单位，并保留小型、低扇出的重复计算。
具体作用域、阶段顺序与验收见 [architecture.md](architecture.md) 第 8–10 节。

## 推进记录规则

每阶段开始时核对两仓状态、输入身份及前置阶段；完成后在本表记录状态，并在
[steps.md](steps.md) 对应阶段追加实际提交、Make 命令、结果和证据目录。
未通过退出条件的阶段保持进行中，后续阶段可以做独立准备，不能把缺失语义
包装为已支持。设计变更先同步架构合约，再调整实现和回归。

工作流日志、临时源码和测量数据放在 `ptmp/firrtl-ingest/Fxx/`；CMake 测试
fixture 放在 `wolvrix/tests/ingest/data/`，测试产物沿用
`wolvrix/build/artifacts/`。不提交生成的香山 FIRRTL、SV 或仿真模型。
