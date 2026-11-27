# F37 Wolvrix IR 框架与方言解耦

本文以 F36 已提交的实现（主仓 `e1b9dd1`、Wolvrix `78b06ba`）为基线。差距与旧路径用于记录 F37 实施前的情况。

## 0. 术语与职责

从 F37 起，**Wolvrix IR** 指核心 IR 框架，角色类比 MLIR。**GRH** 和 **GRHSIM** 都是 Wolvrix IR 中的方言。方言定义具体 op，图提供容纳这些 op 的共用结构。

| 名称 | 职责 |
| --- | --- |
| Wolvrix IR | 提供 `Design`、`Graph`、`Operation`（op）、`Value` 和 `SemanticTree` 等核心数据结构，以及实体 ID、use-def、通用属性、结构校验和持久化机制。框架通过 `OpDefination` 接入具体 op。 |
| GRH（`grh`） | 定义 RTL op，包括组合运算、数组操作、状态声明与读写端口、层次和调用。FIRRTL 和 SystemVerilog 前端生成 GRH 方言 op。 |
| GRHSIM（`grhsim`） | 定义仿真所需的扩展 op，例如事件脉冲、接收脉冲的写端口和调用、Output 历史提交。转换后同一张 Wolvrix IR 图可以同时使用 GRH 和 GRHSIM op。 |
| GRHSIM 仿真流程 | 选择逻辑域，转换 op，构建 Event/General/Output 归属和调度，检查跨 op 的执行约束。CPU emitter 消费图和当前 session 的 `SinkSchedule`。这些职责由 pass 和后端承担。 |

`Operation` 是图中的 op 实例，`OpDefination` 派生类定义一种 op 的规则。技术文档用“Wolvrix IR 图 / 框架 / JSON 容器”描述共用机制，用“GRH 方言 op / GRHSIM 方言 op”描述具体语义。`include/core/` 下的公共声明统一位于 `wolvrix::lib::core`，包括图与语义树、op 定义和注册接口、load/store、通用 pass 与 emitter 接口，以及诊断等基础设施。内部辅助接口位于 `wolvrix::lib::core::detail`，其中 `serialization_ids.hpp` 为 JSON 写出和语义诊断的 ID 映射表提供同一套局部编号。仿真转换的 pass 名为 `grhsim-dialect-translate`。

## 1. 核心提供通用 IR 数据结构

**要求。** Wolvrix IR 核心负责图的存储、op 与 value 的连接及 use-def 等通用结构。所有具体 op 的定义都在核心之外，过去称为 Core Op 的基础 RTL op 归属 GRH 方言。仿真流程拥有执行阶段和图级执行约束，`grhsim.stage=converted` 不属于核心模型。

**SemanticTree。** `SemanticTree` 是 Wolvrix IR 的核心数据结构之一。`Graph` 持有这份结构，用它描述 op 的语义结构分区，记录分区的层次和 op 成员关系。图包含 `SemanticTree` 时，load/store 随图读写它，使用或改写分区的 pass 维护成员关系。诊断工具直接读取这份 IR 结构。Op 的数据依赖由 use-def 表达，Event/General/Output 等执行归属由 GRHSIM 仿真流程决定。[SemanticTree 定义](../../wolvrix/include/core/semantic_tree.hpp#L57) · [Graph 接口](../../wolvrix/include/core/wolvrix.hpp#L1426)

**目录约定。** 在 `wolvrix/lib/dialect/` 集中存放所有方言的 op 定义，按方言分目录。当前两个方言分别为 `wolvrix/lib/dialect/grh/` 和 `wolvrix/lib/dialect/grhsim/`，各自存放所属 op 的 `OpDefination` 派生类。

**属性键存储。** 核心提供可选的常用属性键预注册机制。GRH、GRHSIM 和 ingest 各自注册常用的键，其他键通过图的字符串池存储。属性的记录和读写接口共用同一套实现。[预注册接口](../../wolvrix/include/core/detail/attribute_keys.hpp#L10)

**F36 基线的差距。** GRHSIM 已在核心之外注册 op，但基础 op 仍由核心的 `OperationKind` 枚举、`kOperationNames` 和 `builtinDescriptors()` 定义。Graph 还会按具体写口 kind 分配 `writerOrder`。F36 的通用 verifier 和 PassManager 直接识别 GRHSIM 图级约束和阶段。[基础 op 枚举](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/include/core/grh.hpp#L38) · [内建描述符](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/lib/core/op_descriptor.cpp#L22) · [写入顺序](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/lib/core/grh.cpp#L5615) · `78b06ba:CMakeLists.txt`

### F36 核心库中的 `kCombArrayUpdate`

F36 在核心库单独编译 `wolvrix/lib/core/comb_array_update.cpp`。它解释 `kCombArrayUpdate` 的 `indexCounts` 和操作数分组，校验形状与类型，计算 2 态及 4 态更新结果，还以 `Graph::createCombArrayUpdate` 的形式把该 op 的构造逻辑加入通用 Graph 接口。

**整改要求。** 将 `kCombArrayUpdate` 的定义、构造、校验和求值统一放在 `wolvrix/lib/dialect/grh/ops.cpp`，与其他 GRH op 一起构建。`kCombArrayUpdate` 有自己的 `OpDefination` 派生类，源码随方言集中维护。使用方通过 GRH 方言构造或解释 op，Graph 只提供创建 op、连接 operands/results 和设置属性的通用接口。核心构建目标应能在缺少 GRH 方言的情况下独立构建与链接。内建描述符、枚举边界、名称映射以及 JSON loader 中针对该 op 的分支也要一并移出核心。[内建注册特判](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/lib/core/op_descriptor.cpp#L53) · [名称表](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/lib/core/grh.cpp#L3044) · [loader 专用校验](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/lib/core/load.cpp#L2010)

### 核心文本导出

**整改要求。** F37 统一实施时删除 `wolvrix/lib/core/store_text.cpp`，同步清理核心的 `StoreText` 接口和构建项。F36 的实现负责可读文本展示，还会按具体 op 类型标注操作数角色和状态类型。此类展示职责超出核心的 Graph、Op、Value 骨架。GRH JSON 持久化通过独立的 load/store 路径处理。[文本导出实现](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/lib/core/store_text.cpp#L125) · [核心文本接口](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/include/core/store.hpp#L102) · [核心构建清单](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/CMakeLists.txt#L125)

## 2. 每种 op 都是 OpDefination 的一个派生类

**要求。** 引入基类 `OpDefination`。每种 op 都有一个独立的具体派生类，基础 GRH op 和 GRHSIM op 均遵循这一规则。例如，GRH 加法和 GRHSIM 边沿检测各自对应一个 `OpDefination` 派生类。每个派生类通过统一接口为 load、store 和 verifier 提供该 op 的名称、操作数和结果约束、属性及校验规则。核心按 op 类型查找并使用对应的定义。

**F36 基线的差距。** `OpDescriptor` 是结构体。各 op 由同一结构体的表项和可选校验函数表示。名称解析先查核心枚举的名称表，再查扩展注册表。多数基础 op 的具体约束仍写在 `grh.verify` 的 kind 分支里。JSON loader 也直接处理 `kArrayUpdate` 的兼容名称，并对 `kCombArrayUpdate` 单独调用描述符校验。[描述符](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/include/core/op_descriptor.hpp#L19) · [名称解析](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/lib/core/grh.cpp#L3192) · [基础 op 校验](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/lib/transform/verify.cpp#L306) · [JSON 加载](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/lib/core/load.cpp#L1849)

## 3. Pass 自己判断能处理哪些 op

**要求。** 每个 pass 自己确认输入图中的 op 对本 pass 是否合法，遇到无法处理的 op 由该 pass 报错。Pass 可以直接依赖具体 op 类型，也可以复用定义和校验工具。Op 符合 `OpDefination` 说明它在 IR 中合法，能否参与某个变换由该 pass 判断。

**F36 基线的差距。** F36 的 PassManager 扫描 op，按所属方言调用 `supportsDialect()`，并可能在 pass 运行前统一拒绝。默认只接受 `grh`。PassManager 还通过 pass 名白名单决定哪些 pass 能处理 SemanticTree 和 `kCombArrayUpdate`。[Pass 接口](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/include/core/transform.hpp#L338) · [方言准入](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/lib/core/transform.cpp#L417) · [SemanticTree 和组合数组更新准入](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/lib/core/transform.cpp#L19)

## 4. 代码职责对照

| 范围 | F36 职责与耦合 | F37 归属 |
| --- | --- | --- |
| 图和实体存储 | `core/grh.hpp` 与 `grh.cpp` 同时实现通用实体和基础 op 枚举、名称表。存储槽的默认 kind 甚至引用 `kConstant`。 [实体与 op 枚举](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/include/core/grh.hpp#L38) · [列存储默认值](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/include/core/grh.hpp#L1169) | 将 kind 作为通用类型标识存储，通过定义接口解释。具体 op 的名称和规则由方言提供。 |
| 构造和状态 | `Graph::createArray` 创建 `kArrayCreate`，`createCombArrayUpdate` 创建 `kCombArrayUpdate`，`replaceAllUsesWithView` 创建 `kAssign`。核心按寄存器端口解释索引和写入顺序，`state.cpp` 识别寄存器与锁存器并处理 `InitSpec`。 [Graph 构造接口](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/include/core/grh.hpp#L1604) · [写入顺序](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/lib/core/grh.cpp#L5613) · [视图替换](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/lib/core/grh.cpp#L6974) · [状态语义](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/lib/core/state.cpp#L68) | 核心提供创建、连接、替换等图操作。具体构造、读写口布局和初始化语义由 GRH 方言及使用它的 pass 提供。 |
| 分析与导出 | 核心的 `semantic_exchange.cpp` 同时做通用实体记录、具体 RTL 表达式分类和寄存器读写导出。`store_text.cpp` 也解释具体 op 的展示角色。 [表达式分类](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/lib/core/semantic_exchange.cpp#L4002) · [F36 状态动作](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/lib/core/semantic_exchange.cpp#L4560) · [文本展示](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/lib/core/store_text.cpp#L125) | 保留共用结构与身份记录。依赖具体 kind 的观测由方言或相应采集工具提供。核心 `StoreText` 按第 1 节删除。 |
| 定义、验证和 JSON | 基础 op 走核心内建表和 verifier 的 kind 分支；扩展 op 走注册表。loader 特判 `grh` 版本、`kArrayUpdate` 迁移和 `kCombArrayUpdate` 验证，还按 `kInstance` / `kBlackbox` 处理关联。 [定义查询](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/lib/core/op_descriptor.cpp#L70) · [版本处理](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/lib/core/load.cpp#L1220) · [名称与版本迁移](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/lib/core/load.cpp#L1849) · [实例处理](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/lib/core/load.cpp#L2117) | 通用 load/store 和 verifier 通过统一接口使用各 op 的 `OpDefination`。op 校验规则归所属方言，版本与兼容分支按第 6 节删除。 |
| 转换、调度和发射 | `transform/grhsim/ops.cpp` 注册 GRHSIM op。同一文件还实现图级执行校验。转换保留状态声明、读端口及普通组合 op，改写时钟写入和调用并创建事件；分区 pass 建立归属，sink pass 发布 schedule，CPU emitter 生成 C++。 [op 注册](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/lib/transform/grhsim/ops.cpp#L276) · [转换映射](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/lib/transform/grhsim/grh-to-grhsim.cpp#L296) · [调度交付](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/lib/transform/grhsim/partition-sink.cpp#L466) | op 定义归 `lib/dialect/grhsim/`。转换条件、跨 op 校验、归属、调度和发射分别由相应流程和后端处理。 |
| Pass、绑定和构建 | PassManager 按方言和 pass 名预审。核心编入 `comb_array_update.cpp`、`state.cpp`、`store_text.cpp` 以及含 GRH 专用规则的 verifier。Python 按名调用 pass。 [Pass 准入](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/lib/core/transform.cpp#L417) · [构建清单](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/CMakeLists.txt#L113) · [Python 绑定](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/app/pybind/native/actions/transform.cpp#L160) | Pass 自己判定 op 支持范围。核心可在未链接 GRH 和 GRHSIM 方言时使用图骨架，完整工具按需组合方言、前端、pass 和后端。 |

### F36 协议基线

F36 的 JSON 容器带版本号 v5，`dialects` 中的 `grh:4` 和 `grhsim:2` 是方言版本。F37 按当前结构读写 JSON，并将 `grhsim.cpu.maskedOr` 注册在 GRHSIM 方言。 [当前 JSON 规格](../../wolvrix/docs/grh/grh-json-spec.md) · [GRHSIM op 定义](../../wolvrix/lib/dialect/grhsim/ops.cpp)

## 5. 文档梳理

- 两级 README 给出框架、方言和仿真工具的入口。IR 白皮书区分前五节的共用结构和第六节的 GRH op 语义。API 与存储文档沿用可用的现行 C++ 名称。
- JSON 规格描述当前图结构及 op 编码。GRHSIM 方言规格解释 op 契约，转换、分区、阶段恢复和 emitter 的约束由对应流程文档说明。
- F 系列历史报告继续记录各轮实测时的实现与名称。F37 索引链接本方案，作为后续代码迁移和文档整理的入口。

## 6. 开发期 IR 取消版本和兼容设计

**要求。** Wolvrix IR 尚未正式发布。F37 统一实施时删除 IR 容器、方言和 op 的版本设计及其保护逻辑，load/store、pass 与工作流只使用当时代码的格式、名称和接口。旧 checkpoint 从原始输入重新生成。

- 删除 JSON 的 `formatVersion`、方言版本映射以及对应的写出、读取与匹配逻辑。注册定义也删除版本字段、版本查询和冲突检查。方言身份与 op 名称用于查找定义。
- 删除旧格式迁移、旧名称映射及只为兼容旧产物而存在的分支。已查到的例子包括 `grh:2` / `grh:3` 放行、`kArrayUpdate` 改名迁移、`kAssignAs` 专用提示，以及草稿中的旧 `grhsim.stage` 恢复和旧 pass 名回退。对应兼容测试随实现清理。
- 校验按当前结构执行，包括引用完整性、名称唯一性、已注册 op 的类型及属性约束，以及 pass 能否处理输入 op。无法按当前定义读取的产物直接报错。

[JSON 版本检查](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/lib/core/load.cpp#L1181) · [方言版本查询](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/lib/core/op_descriptor.cpp#L106) · [旧 op 名处理](https://github.com/Wolf-Tungsten/wolvrix/blob/78b06ba80b2801fc3982faa81c821a98d5067608/lib/core/load.cpp#L1849)

## 7. 实施

- 核心在 `op_definition.hpp` 中声明 `OpDefination` 及注册、查询和校验接口。GRH 的 61 个 op 和 GRHSIM 的 14 个 op 分别定义在各方言的 `ops.cpp`。核心测试单独链接框架，通过自定义 op 验证注册、校验和 JSON 往返。 [核心接口](../../wolvrix/include/core/op_definition.hpp) · [核心独立测试](../../wolvrix/tests/grh/test_op_definition.cpp)
- 原 `state.hpp` 和 `state.cpp` 中的声明属性读写已并入 GRH 方言的 `builders.hpp` 和 `builders.cpp`。寄存器、锁存器的位宽、符号性和形状通过 `LogicalType` 读写，初始化通过 `InitSpec` 读写，数据保存在声明 op 的属性中。SV 与 FIRRTL ingest、相关 pass 和 emitter 共用这些接口。F35/F36 的分析和导出位于 transform 层。 [构造接口](../../wolvrix/include/dialect/grh/builders.hpp) · [语义导出](../../wolvrix/lib/transform/semantic_exchange.cpp)
- PassManager 调用 pass 自身的输入检查。GRHSIM 解释执行约束和流程配置，并在恢复检查点时重建当前 session 的 schedule。 [Pass 接口](../../wolvrix/include/core/transform.hpp) · [仿真验证](../../wolvrix/lib/transform/grhsim/validation.cpp)
- `partition-nonsink` 从 `SemanticTree` 获取成员关系。香山平坦图恢复通过同次写出的阶段记录识别预处理进度，旧 checkpoint 从原输入重新生成。 [分区分析](../../wolvrix/lib/transform/grhsim/partition-nonsink.cpp) · [平坦图恢复](../../scripts/wolvrix_xs_grhsim.py)

## 8. 方言命名与 op 定义整理计划

### 8.1 统一 op 的文本注册名与 C++ kind 命名

当前 GRH 的文本注册名沿用 `kAdd`、`kLatch` 等 C++ 常量拼写，GRHSIM 同时使用 `grhsim.edge-detect` 和 `grhsim.writeMask` 等拼写。两套方言统一使用带方言前缀的注册名，op 名称部分采用 lowerCamelCase，与 C++ `op` 子命名空间中的 kind 常量同名。全部 61 个 GRH op 使用 `grh.` 前缀。GRHSIM 中带连字符的名称同步改成驼峰式，已有的 `grhsim.writeMask`、`grhsim.cpu.maskedOr` 已符合这项命名规则。 [GRH 定义示例](../../wolvrix/lib/dialect/grh/ops.cpp#L546) · [GRHSIM 定义示例](../../wolvrix/lib/dialect/grhsim/ops.cpp#L293)

| 当前 C++ kind | 计划 C++ kind | 当前注册名 | 计划注册名 |
| --- | --- | --- | --- |
| `grh::op::kAdd` | `grh::op::add` | `kAdd` | `grh.add` |
| `grh::op::kLatch` | `grh::op::latch` | `kLatch` | `grh.latch` |
| `grh::op::kRegisterWriteArrayMaskPort` | `grh::op::registerWriteArrayMaskPort` | `kRegisterWriteArrayMaskPort` | `grh.registerWriteArrayMaskPort` |
| `grh::op::kCombArrayUpdate` | `grh::op::combArrayUpdate` | `kCombArrayUpdate` | `grh.combArrayUpdate` |
| `transform::grhsim::kEdgeDetect` | `grhsim::op::edgeDetect` | `grhsim.edge-detect` | `grhsim.edgeDetect` |

两个方言的 `OperationKind` 常量分别放在 `wolvrix::lib::dialect::grh::op` 和 `wolvrix::lib::dialect::grhsim::op`，使用 lowerCamelCase，去掉 `k` 前缀。pass 创建实例时传入 `graph.createOperation(grh::op::add)` 或 `graph.createTemporaryOperation(grhsim::op::edgeDetect)` 所示的 kind。表中计划列和建图示例的 `grh` 与 `grhsim` 分别简写两个方言命名空间。`Graph` 和 `OperationKind` 等核心类型位于 `wolvrix::lib::core`。 [建图接口](../../wolvrix/include/core/wolvrix.hpp#L1517)

文本注册名由各 op 的定义提供。一次迁移更新 JSON `kind`、`toString(OperationKind)` 的输出及其调用方，并检查读取这些名称的 Python 工具、诊断断言、测试夹具与现行规格。F35/F36 的导出包含 `native_kind` 或 `kind` 等字段，分类器和状态比较器须同步改用新名称。对齐继续按原有的 Node 名称、状态名称和访问形状定义计分。 [JSON 写出](../../wolvrix/lib/core/store.cpp#L1287) · [F35 分类器](../../scripts/f35_compare.py#L196) · [F36 状态类型解析](../../scripts/f36_state_port_compare.py#L118)

按第 6 节一次切换到新名称，不设版本字段、不注册旧名别名、不做双读、转换或回退。旧 Wolvrix IR JSON 和 checkpoint 从原始输入重建，现行测试夹具直接更新。历史报告保留记录时的名称。

### 8.2 将 GRHSIM 方言定义移出 transform 命名空间

当前 `include/dialect/grhsim/ops.hpp` 和 `lib/dialect/grhsim/ops.cpp` 位于方言目录，声明与实现仍使用 `wolvrix::lib::transform::grhsim`。将 GRHSIM 的 kind 常量、`OpDefination` 派生类、注册逻辑，以及直接解释这些 op 的属性和操作数布局的辅助接口归入 `wolvrix::lib::dialect::grhsim`。同步更新 pass、emitter、绑定与测试的引用，移除旧命名空间的这些声明，不加转发别名。 [GRHSIM 头文件](../../wolvrix/include/dialect/grhsim/ops.hpp#L9) · [GRHSIM 实现](../../wolvrix/lib/dialect/grhsim/ops.cpp#L13)

转换 pass、分区、调度和仿真流程的图级检查继续归 `wolvrix::lib::transform::grhsim`。例如，`grhsim.literalFormat` 由系统任务 op 的定义解释，`grhsim.partition` 的执行归属由分区流程解释。当前 emitter 用一个 `sim` 别名访问两类接口，迁移时按声明归属修改调用。依赖方向为 pass 使用方言接口，方言通过核心接口注册。GRHSIM 的 kind 常量位于 `wolvrix::lib::dialect::grhsim::op`。 [转换 pass](../../wolvrix/lib/transform/grhsim/grh-to-grhsim.cpp#L795) · [仿真流程校验](../../wolvrix/lib/transform/grhsim/validation.cpp#L159) · [Emitter 引用](../../wolvrix/lib/emit/grhsim/cpu-st-cpp.cpp#L39)

### 8.3 按 op 集中 GRH 定义

当前 `lib/dialect/grh/ops.cpp` 前半部集中放了大量自由 verifier 函数和 `AttrSchema` 数组，后面的派生类再引用它们。逐个整理 GRH 的 `OpDefination` 派生类。每个类就地给出构造参数、属性 schema 和该 op 的校验实现，包括适用的 `verify()`、`verifyInGraph()` 和 `verifySemanticBinding()`。单一 op 专用的校验函数收进类内。多个 op 共用的校验可保留小型辅助函数，各派生类明确声明自己采用的约束。类内属性 schema 使用静态生命周期，满足核心注册接口对 `std::span` 的要求。 [现有属性表](../../wolvrix/lib/dialect/grh/ops.cpp#L520) · [锁存器定义](../../wolvrix/lib/dialect/grh/ops.cpp#L812) · [定义接口](../../wolvrix/include/core/op_definition.hpp#L19)

每个 `OpDefination(...)` 基类构造调用旁都加简短注释，说明 op 的用途、效果类型、是否允许 CSE 和克隆、操作数与结果的数量范围，以及属性表的含义。有端口布局的 op 写出各槽位角色。以 `grh.latch` 为例，注释应能让读者直接看出 `Declaration` 是状态声明，两个 `false` 分别表示禁用 CSE 与克隆，两个 `0, 0` 分别是操作数和结果的数量范围，属性表要求整数 `width` 和布尔值 `isSigned`。GRHSIM 搬迁定义时同样采用这项注释约定。各 GRH op 继续集中在同一份 `ops.cpp`。

### 8.4 实施顺序与验收

1. 迁移两套方言的文本注册名及其使用点，并更新 GRH 的 C++ kind 常量。核对 61 个 GRH 和 14 个 GRHSIM op 的注册名都能由核心注册表往返解析，混合方言图能通过新名称的 JSON 往返。旧 GRH `k*` 名称和本次替换的 GRHSIM 连字符名称按未知 op 的通用路径报错。
2. 迁移两套方言的 op 定义和 C++ kind 常量。检查建图调用引用 `wolvrix::lib::dialect::<方言>::op` 中的常量，旧 kind 常量移除。运行核心独立注册及 GRHSIM 转换和验证测试。
3. 按 op 整理 GRH 定义并逐一检查构造注释。通过现有 `make test_wolvrix`、`make test_grhsim_flow` 和 `make test_xs_firrtl_workflow` 覆盖属性类型、端口布局、非法 op 诊断及当前格式的 checkpoint 恢复。
4. 运行 F35/F36 工具回归，再用当前构建重跑香山 `SimTop` 第四次 DCE 后的采集与比较。以 F37 最近一次全图结果为基线，核对 F35 的 Node 匹配和各类差异，以及 F36 的状态配对和读写访问结果。导出中的 op 文本名按新命名验证。 [F35 基线](../../ptmp/firrtl-ingest/F35/f37-20261127-used-bits/comparison.json) · [F36 基线](../../ptmp/firrtl-ingest/F37/alignment-20261127-used-bits/f36-comparison/summary.json)

### 8.5 实施结果

GRH 的 61 个 op 和 GRHSIM 的 14 个 op 已统一采用小驼峰注册名，如 `grh.add`、`grh.registerWriteArrayMaskPort`、`grhsim.edgeDetect` 和 `grhsim.cpu.maskedOr`。声明采用 `grh.registerDecl`，按位运算采用 `grh.bitAnd`、`grh.bitOr`、`grh.bitXor`、`grh.bitXnor` 和 `grh.bitNot`，使注册名的最后一段可直接作为对应的 C++ kind 常量名，并避开 C++ 保留字。GRHSIM 的 op 定义归 `wolvrix::lib::dialect::grhsim`。GRH 各派生类就地定义专用校验与属性 schema。 [GRH 定义](../../wolvrix/lib/dialect/grh/ops.cpp) · [GRHSIM 定义](../../wolvrix/lib/dialect/grhsim/ops.cpp)

原生回归通过 109 项，覆盖全部 75 个注册名的双向查询、混合方言 JSON 往返，以及旧注册名经未知 op 路径拒绝。F35 和 F36 工具回归分别通过 34 项和 9 项。 [原生回归](../../ptmp/firrtl-ingest/F37/dialect-naming/native-check.log) · [对齐工具回归](../../ptmp/firrtl-ingest/F37/dialect-naming/f35-f36-retest.log)

上述回归完成后，GRH 的 kind 常量和 `OpDefination` 派生类迁入 `wolvrix::lib::dialect::grh::op`。本次命名空间调整同步更新 C++ 调用点，沿用原有 JSON 注册名。 [GRH kind 定义](../../wolvrix/include/dialect/grh/ops.hpp)

用新构建从同一张香山 `SimTop` 第四次 DCE 后的图导出 Node 表和状态读写动作，使用与基线相同的冻结 GSIM 样本。

| 对齐口径 | 全图复测 |
| --- | --- |
| F35 Node | 2,499,594 / 2,515,898（99.35196%）。16,304 个未配对，名单和分类计数与基线一致。 |
| F36 状态与访问 | 147,100 个状态中，145,103 个同名同形（98.64242%），1,997 个未配对。已配对的状态中，145,007 个读写访问均一致，96 个存在读侧差异，写侧差异为 0。统计与基线一致。 |

[采集记录](../../ptmp/firrtl-ingest/F37/dialect-naming/capture/grh/capture.json) · [F35 对齐报告](../../ptmp/firrtl-ingest/F35/f37-dialect-naming/comparison.json) · [F36 对齐报告](../../ptmp/firrtl-ingest/F37/dialect-naming/f36-comparison/summary.json)

随后统一 `include/core/` 的命名空间。GRH 状态和数组构造等接口迁入 GRH 方言，内建 pass 工厂与语义导出接口归 `wolvrix::lib::transform`。原生构建和 Python 绑定构建通过。独立 core 注册、GRHSIM 方言、两项 JSON 往返和 PassManager 的定向测试通过 5 项，Python ingest session 测试通过 4 项。 [原生定向测试](../../ptmp/firrtl-ingest/F37/core-namespace/targeted.log) · [Python 定向测试](../../ptmp/firrtl-ingest/F37/core-namespace/python-smoke.log)

`allocator.hpp` 和 `toposort.hpp` 整体迁入 `core/detail`。图存储性能计数、JSON 属性可序列化检查和改写来源传播辅助函数也从公开头文件拆到 `core/detail`。`DirtyWorklist` 由 `simplify` 及其三个子 pass 共用，归 `lib/transform` 私有头文件。整理后 `include/core` 顶层有 10 个公开头文件，`core/detail` 有 13 个内部头文件。`GraphStore` 和 `GraphPayload` 仍是图存储诊断和属性视图的 C++ 接口类型。 [图存储诊断接口](../../wolvrix/include/core/wolvrix.hpp) · [定向测试](../../ptmp/firrtl-ingest/F37/core-detail/targeted.log)
