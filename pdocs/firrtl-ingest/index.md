# FIRRTL 输入支持推进文档

建立日期：2026-10-30。已完成 F01 目录/读取层迁移和 F02 属性/作用域基础；
F03 parser 和接口索引已完成，冻结输入通过香山全模块语法与接口验收。
F04 组合 lowering、Bundle/Vector 和真实 node 标注已完成，验收见 F04-acceptance.md。
F05 寄存器、复位及有序数组写已完成，验收见 F05-acceptance.md。
F06 memory、效果与目标版本特性已完成，验收见 F06-acceptance.md。
F08 完整 node CSE、属性传播和 checkpoint 已完成，验收见
F08-acceptance.md。F09 已将 node 改为不阻碍 simplify 的 op 级软提示，
撤除 source-node 隔离并接入统一 nonsink 分图。设计与实际验收分别见
F09-plan.md、F09-acceptance.md；F02/F08 验收记录保留历史含义。
2026-10-31 当前决定：先形成统一 node——有 FIRRTL 提示按提示，无提示按
MFFC；再按 node 数划分 supernode，不感知内部 op 数/work。F09.6 已实现并验收，见 [F09.6-acceptance.md](F09.6-acceptance.md)，
取代前次“单 node 超 work 预算豁免”的规划。

目标是在 Wolvrix 内实现不依赖 CIRCT 的 FIRRTL 前端，与现有 SV 前端共同
构建设计。FIRRTL `node` 与 ops 的关联以 attribute 保存；普通 GRH 优化与
仿真转换不受来源标注限制，允许跨 node CSE、内联、重关联和 DCE。分图
以优化后的真实 op 图为准，有提示按提示构建 node，其余按 MFFC。共享和
语义冲突在 node 构建层规范化；supernode 只组合完整 node，按 node 数
限制容量。数组保留 shape，Bundle 按现有 SV struct 规则递归展平。

## 文档入口

| 文档 | 内容 |
| --- | --- |
| [architecture.md](architecture.md) | 源码组织、混合读取、类型与时序语义、node 属性及分图合约 |
| [steps.md](steps.md) | F00–F11 的依赖、交付、Make 验证入口及退出条件 |
| [firrtl-parser.md](../../wolvrix/docs/ingest/firrtl-parser.md) | 已实现 parser 的语法、接口签名、资源与验证边界 |
| [F03-acceptance.md](F03-acceptance.md) | F03 逐项验收、目标构造矩阵、冻结输入和复验命令 |
| [firrtl-combinational.md](../../wolvrix/docs/ingest/firrtl-combinational.md) | F04 类型、连接、聚合、逻辑域及 node lowering 的实际支持范围 |
| [F04-acceptance.md](F04-acceptance.md) | F04 逐项验收、组合执行样例和实际回归证据 |
| [firrtl-state.md](../../wolvrix/docs/ingest/firrtl-state.md) | F05 状态类型、初始化、复位屏障及有序读写的实际支持范围 |
| [F05-acceptance.md](F05-acceptance.md) | F05 逐项验收、FIRRTL/SV 多周期记分板和最终模型回归证据 |
| [firrtl-memory.md](../../wolvrix/docs/ingest/firrtl-memory.md) | F06 memory 归一化、延迟、mask、冲突及四态策略 |
| [firrtl-effects.md](../../wolvrix/docs/ingest/firrtl-effects.md) | F06 effects、layer、Probe、annotation 和外部引用边界 |
| [F06-acceptance.md](F06-acceptance.md) | F06 验收矩阵、目标模块执行和专项/全量回归证据 |
| [mixed.md](../../wolvrix/docs/ingest/mixed.md) | F07 混合读取、参数 specialization、ABI、黑盒源及事务式发布 |
| [F07-acceptance.md](F07-acceptance.md) | F07 交替层次仿真、负例、Python 和完整回归证据 |
| [node-cse.md](../../wolvrix/docs/ingest/node-cse.md) | 当前可选整体 node 判等、软提示策略和配置迁移 |
| [F08-acceptance.md](F08-acceptance.md) | F08生产变换审计、回归和真实大模块属性成本 |
| [F09-plan.md](F09-plan.md) | 当前两层分图设计：提示/MFFC 构建 node，按 node 数划分 supernode；F09.6 已实现 |
| [F09.6-acceptance.md](F09.6-acceptance.md) | 当前统一 node / Node DAG / 节点容量、迁移及代表模块验收 |
| [F09-acceptance.md](F09-acceptance.md) | F09.0–F09.5 实施、结构透明性、回归及真实模块消融结果 |
| [inputs.json](inputs.json) | FIRRTL、生成 SV、fixture、规范及语法统计的冻结身份 |

## 已确定的设计决策

| 项目 | 决策 |
| --- | --- |
| FIRRTL 实现 | 自有 C++ lexer/parser、类型检查与 lowering；运行和构建均不链接或调用 CIRCT/firtool |
| ingest 目录 | `lib/core/ingest.cpp` 迁移为 `lib/ingest/sv.cpp`；新增 `lib/ingest/firrtl.cpp` 和共享 driver |
| 公开头文件 | 统一放在 `include/ingest/`；删除旧 `include/core/ingest.hpp`，同步迁移全部调用方 |
| 混合输入 | 一次读取事务同时接收 FIRRTL 与 SV，先解析接口及跨语言引用，再 elaboration、链接到统一 GRH |
| 聚合类型 | Bundle/struct 递归拆字段；Vector/数组维度迁移到叶子 shape，端口也保留数组 |
| node 持久化 | 有版本的 `firrtl.node.*` op attrs，表达当前直接关联，允许多对多、部分保留和降级 |
| simplify | node 不进入功能键、CSE 作用域或重写准入；优化后合并/更新提示，维护不了则降级，不加属性载体或保活根 |
| GSIM 策略迁移 | F09 已撤除普通优化屏障；独立整体选项采用 gsim-soft-v2，只消费仍可证明的候选，门槛不限制 primitive CSE |
| node 构建 | 有可用 FIRRTL 提示按提示构建 node；其余按 MFFC，均不因 op 数或 work cap 拆分；共享/语义冲突先规范化 |
| supernode 分组 | 统一 Node DAG，每 node 容量权重为 1，按 max-supernode-nodes 分组，不读取内部 op 数/work |
| 无注解输入 | SV、FIRRTL 无提示逻辑和混合 glue 都按 MFFC 构建 node，进入同一 Node DAG；无根不等于无提示 |
| 混合分组 | 链接后的真实 ValueId 连接两种输入，不按 node/wire 名称匹配；语言来源不阻止合法跨界合并 |
| 正确性 | 混合绑定、旧值采样、写优先级、memory 语义、DPI/效果均纳入验收 |
| 性能 | 分别测量输入路线、完整 node CSE 和 node 分图的收益；不预先承诺整机提升百分比 |

## 阶段看板

| 阶段 | 交付 | 状态 |
| --- | --- | --- |
| F00 | 固定输入、特性清单和对照基线 | 进行中；F03 输入身份已冻结，整机依赖及基线验收待补 |
| F01 | ingest 目录迁移和公共读取边界 | 已完成（2026-10-30，验证见 steps.md） |
| F02 | node attribute schema、CSE 作用域及验证器 | 历史实现已完成；F09 已迁移为 schema 2 / soft-node-v2 |
| F03 | FIRRTL parser、版本检查和模块接口索引 | 已完成（2026-10-30，冻结输入和验收见 F03-acceptance.md） |
| F04 | 类型推导、组合语义、Bundle/Vector 和 node lowering | 已完成（2026-10-31，验收见 F04-acceptance.md） |
| F05 | 寄存器、复位及有序数组写 | 已完成（2026-10-31，验收见 F05-acceptance.md） |
| F06 | memory、效果及目标版本特性 | 已完成（2026-10-31，验收见 F06-acceptance.md） |
| F07 | FIRRTL/SV 混合 elaboration、链接和 Python API | 已完成（2026-10-31，完整验收见 F07-acceptance.md） |
| F08 | GSIM 模式 node 级 CSE、属性传递和 checkpoint | 历史实现已验收；F09 已迁移普通优化与独立 CSE 配置 |
| F09 | 统一 node 构建与 nonsink 分图 | F09.0–F09.5 为旧版验收；F09.6 提示/MFFC node + 按 node 数划 SN 已完成（F09.6-acceptance.md） |
| F10 | 香山混合输入和差分正确性 | 待实施 |
| F11 | 前端/node CSE/分图性能消融、默认策略和正式文档 | 待实施 |

F08 曾以本地 GSIM `a3ecb26` 的 `commonExpr()` 为依据保留源表达式边界。
当前方案保留 simplify 自由：之后才按提示/MFFC 形成执行 node，再按
node 数形成 SN；迁移及阶段顺序见 [architecture.md](architecture.md) 第 8–10 节。

## 推进记录规则

每阶段开始时核对两仓状态、输入身份及前置阶段；完成后在本表记录状态，并在
[steps.md](steps.md) 对应阶段追加实际提交、Make 命令、结果和证据目录。
未通过退出条件的阶段保持进行中，后续阶段可以做独立准备，不能把缺失语义
包装为已支持。设计变更先同步架构合约，再调整实现和回归。

工作流日志、临时源码和测量数据放在 `ptmp/firrtl-ingest/Fxx/`；CMake 测试
fixture 放在 `wolvrix/tests/ingest/data/`，测试产物沿用
`wolvrix/build/artifacts/`。不提交生成的香山 FIRRTL、SV 或仿真模型。
