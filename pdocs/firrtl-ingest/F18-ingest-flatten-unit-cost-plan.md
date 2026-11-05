# F18：F17 未达预期的原因与下一步方案

日期：2026-11-05。状态：F18 全部实现与验收完成。F18.0 基线、fp 采样和报告均已通过；
F18.1 SemanticTree、F18.2 临时对象与 JSON v3、F18.3 flatten 批量化、F18.4 可行性结论及
F18.5 ingest 尾部优化均已实现；最终三轮 formal 中位数 70.64 s，达到 ≤75 s 目标。

范围为原始 `SimTop.fir` 到 hier-flatten 返回，node annotations 开启。F18 只打通并优化
FIRRTL ingest→flatten；旧 node JSON 兼容、SV SemanticTree 接入以及 flatten 后的 simplify、
GrhSIM 重构不在本阶段范围内。本文所有数字都标明来源。“预算”是设计目标，不是已测收益。

## 1. 结论

F17 不是失败：formal 连续墙钟从 308.5 s 降到 167.8 s（-45.6%），峰值 RSS 从 111.4 GiB
降到 66.2 GiB，native 分配从 29.9 亿次降到 11.7 亿次（-60.8%）。

但总 CPU 只从 440.8 s 降到 410.5 s（**-6.9%**）。墙钟收益基本来自 ingest 并行，
单位工作几乎没有变便宜。未达标的直接原因有四个：

1. **主要成本是 node 文本，不是内存布局。** 同一插桩构建关闭 node 后为 111.2 s，
   开启为 180.7 s，差 69.5 s（38.5%），其中 flatten 从 97.3 s 降到 47.0 s。
2. **flatten 的成本在文本和名字，不在搬运。** 采样中 node 文本占 35%、名字占 29%，
   按块函数只占 22%，`memcpy`/`memmove`/`memset` 叶函数只有 1.5 s。所谓“块拼接”也只有部分
   真正批量化。flatten 是单线程运行的（formal CPU 86.8 s、墙钟 85.4 s），但名字走共享哈希表，
   不适合靠并行解决，应先去掉这部分工作。
3. **`Rob` 限制了模块级并行。** 该模块单线程 28.8 s，大于 10 线程均摊的 15.7 s。
4. **F17 的热点指标选错了。** flatten 六类热点降到 F16 的 13%，墙钟却只到 70%：
   成本转移到了六类之外的 `internImpl`、`bindSymbol`、`copyQualified` 等函数。

F17.1 把 node 文本和临时名都排除在范围外，并且 ≤10/≤50/≤60 s 预算是在没有调用栈和
模块级数据时定的，这是方案本身的问题，不是实现偏差。

## 2. F17 文档需要更正的数字

`F17.1-grh-storage-results.md` 和 `index.md` 把 perf 采样运行的数字写成了无采样 formal 结果。

| 项目 | 文档值（`final-r2/perf/run/timing.json`） | formal（`final-r2/formal/timing.json`） |
| --- | ---: | ---: |
| ingest + pre-flatten | 84.90 s | **82.27 s** |
| hier-flatten | 110.40 s | **85.41 s** |
| 连续墙钟 | 195.45 s | **167.85 s** |
| 峰值 RSS | 约 67.2 GiB（70,445,176 KiB） | **66.2 GiB**（69,371,544 KiB） |

此外，F17 的 perf 只有叶函数：`--call-graph dwarf` 在这些二进制上无法展开，inclusive 约等于
self，所以 F17 没有可靠的调用方归因。本文尚未修改 F17 文档。

## 3. 证据

| 运行 | 构建 | ingest+前置 | flatten | 连续 | 用途 |
| --- | --- | ---: | ---: | ---: | --- |
| F17 formal | r2，无采样 | 82.27 | 85.41 | 167.85 | 唯一正式基线 |
| `F18/phase-profile` | r2，开逻辑计数和 perf stat | 98.11 | 94.95 | 193.19 | 计数、IPC |
| `F18/fp/run1` | frame-pointer，perf fp | 95.06 | 98.93 | 194.08 | 调用栈 |
| `F18/fp/module-run` | frame-pointer + 模块计时 | 83.35 | 97.27 | 180.72 | 模块耗时、node 开 |
| `F18/fp/node-off` | 同上 | 64.04 | 47.01 | 111.21 | node 关 |
| `F18/benchmark` | 当前工作树、F18 Makefile target、无采样 | 219.57（ingest + 前置） | 103.45 | 323.60 | 首个阶段计时基线；未固定 CPU，不能与 formal 基线作性能结论 |
| `F18/semantic-prefix` | 每实例深拷贝 SemanticTree、无采样、CPU 0–31 | 52.25 | 332.27 | 384.64 | F18.1 首版负面结果；定义树复制不可接受，随后改为共享定义树 |
| `F18/semantic-shared` | 共享定义树、来源块映射、annotations worker 化、无采样、CPU 0–31 | 51.30 | 22.31 | 73.70 | 共享实现的首次达标观测；仍需最终三轮 formal 复验 |
| `F18/final` | 完整实现、无采样、CPU 0–31、三轮中位数 | 51.03 | 19.60 | 70.64 | 正式结果；连续预算 ≤75 s 达成 |

`F18/benchmark` 使用冻结的 `F15/manifests/threads-10.json`，运行入口为
`make benchmark_f18_firrtl_ingest`，并打开 `WOLVRIX_FIRRTL_INGEST_PROFILE=1`。本次记录的
ingest 为 174.88 s（native CPU 175.23 s），前置 pass 合计 44.69 s，hier-flatten 为
103.45 s，连续墙钟 323.60 s，峰值 RSS 46.5 GiB（48,806,528 KiB）。阶段计时还记录了
parse/interface summary 31.01 s、index 33.00 s、interface fixed point 1.60 s、linked
verify passes 27.62 s；这些是当前实现的首次 F18 观测，尚未重复三次，也未施加 F17 的 CPU
亲和性门禁。

`F18/semantic-prefix` 使用相同冻结输入、10 worker 和 fused prefix，固定 CPU 0–31、关闭采样。
其中 ingest+前置为 52.25 s，flatten 为 332.27 s，说明按实例深拷贝定义树会引入比原文本路径更大的
成本。后续实现只创建实例节点、共享定义树，并将 SemanticId 改为实例与定义内节点的组合；该单次
负面结果只用于设计纠偏，不作为共享实现的性能结论。

`F18/semantic-shared` 在相同门禁下测得 ingest+前置 51.30 s、flatten 22.31 s、连续 73.70 s，
首次低于 75 s 预算。相对 F17 formal 分别约下降 37.6%、73.9% 和 56.1%。这是单次观测，且之后还
完成了 SrcLoc/字符串批量化与 ingest 尾部优化，最终结论仍以新的三轮 formal 中位数为准。

`F18/final` 三轮连续墙钟为 70.31/71.39/70.64 s，中位数 70.64 s，范围约 ±1.5%；flatten 为
19.60/19.45/19.86 s，中位数 19.60 s，范围约 ±2.1%。相对 F17 formal，ingest+前置中位数
51.03 s（-38.0%），flatten（-77.0%），连续（-57.9%）。prefix CPU 中位数 239.65 s，较 F17
410.5 s（-41.6%）；峰值 RSS 中位数约 42.3 GiB，较 66.2 GiB（-36.1%）。native 配置、库身份、
prefix 实现和重复配置/诊断一致性检查全部为 true。

诊断运行都慢于 formal，只用于比例和相对比较；各配置均为单次，未测重复波动。
`phase-profile` 的 flatten 内部 profile 含 `recursive-ms`/`op-loop-ms` 重叠计时，不能相加。

### 3.1 flatten 调用归因（`fp/run1`，采样 84.6 CPU s）

按工作类型互斥划分（调用栈先匹配者优先，四项相加为 84.6 s）：

| 工作 | CPU s | 占比 | 内容 |
| --- | ---: | ---: | --- |
| node 文本 | 29.2 | 34.5% | `copyQualified` 18.3、inventory 5.1、retention 5.8 |
| 名字 | 24.4 | 28.8% | 内部名 14.2、`retain` 6.5、层次名 0.2、块内 `bindSymbol` 约 3.5 |
| 块函数（不含 `bindSymbol`） | 18.7 | 22.1% | value/op 块、属性块、edges、接管、use-list |
| 其它 | 12.3 | 14.5% | metadata、计划、实例边界处理 |

`bindSymbol` 只统计其在对应类别前三叶函数中的部分，可能略低。全部 memcpy 类叶函数为 1.5 s。

函数 inclusive（有重叠，不可相加）：

| inclusive | 秒 | 占比 |
| --- | ---: | ---: |
| `inlineGraphContents` | 44.1 | 52.1% |
| 其中 `makeInternalOpSym` + `makeInternalValSym` | 14.2 | 16.8% |
| 其中 `appendValueBlock` | 9.9 | 11.7% |
| 其中 `prepareBlockImport`（主要是 `StringPool::retain`） | 6.5 | 7.7% |
| 其中 `appendOperationBlock` | 4.4 | 5.2% |
| `commitGlobalMetadata` | 23.9 | 28.3% |
| 其中 `copyQualified` | 18.3 | 21.6% |
| `recordRetention` | 5.8 | 6.8% |
| `BlockExecutor::run`（全部线程池工作） | 2.0 | 2.3% |

`internImpl` 共 20.4 s。直接调用方：`makeInternalOpSym` 6.3 s、`makeInternalValSym` 6.1 s、
`retain` 5.7 s、`internAttribute` 1.5 s；用户可见层次名的 `internUniqueSymbol` 几乎为 0。

逻辑计数（`phase-profile`）：flatten 写入 2,660 万 op、2,600 万 value，产生 5,321 万次符号插入、
5,162 万次 SrcLoc 写入、1.29 亿次属性写入，属性流量 13.05 GB，约每 op 4.9 次。
注意，F17 文档用过的“4 千万 op”是旧版本数字，当前 flat 约 2,660 万。

### 3.2 ingest 时间线（`fp/run1`，按调用栈分类，采样 322.7 CPU s；F18 首次阶段计时见 §3 表）

时间是该次 95 s 运行中的样本跨度，用于看形状；阶段 CPU 分类之间有重叠。

| 时间 | 阶段 | CPU s | 并行度/说明 |
| --- | ---: | ---: | --- |
| 0–11 s | parse + `summarizeInterface` | 39.1 | 从约 5 核衰减到约 2 核 |
| 11–14 s | `sourceIdentity`、接口解析 | 3.0 | 串行 |
| 14–55 s | 严格 analyze + `lowerModule` | 161.1 | 前 20 s 为 6–8 核，35–55 s 约 1 核 |
| 55–63 s | `applyAnnotations` 等发布 | 约 7 | 串行 |
| 63–78 s | linked verify（GrhVerify 15.4、CombLoop 10.0） | 约 27 | 3–4 核，协调线程 6.4 s |
| 78–89 s | 前置 pass 局部链（MuxTreeFold 16.6） | 约 25 | 3–5 核 |
| 89–95 s | `compactForFlatten` | 28.9 | 约 5 核 |

横跨多个阶段的 `retentionCensus` 为 **31.2 CPU s**（9.7%），`node::inspect` 为 12.8 CPU s。
代码上，每个 pass 都对每张图计算一次 census，但 metadata 只保留最后的值
（`transform.cpp:634`、`node_attributes.cpp:858`）。

### 3.3 模块分布（`fp/module-run`）

全部 9,487 个模块 analyze+lower 合计 157.4 CPU s，关闭 node 为 134.5 CPU s（-14.6%）。

| 模块 | FIRRTL 字节占比 | analyze s | lower s | 合计 s |
| --- | ---: | ---: | ---: | ---: |
| `Rob` | 13.9% | 4.74 | 23.97 | 28.77 |
| `LogPerfEndpoint` | 6.2% | 1.20 | 8.81 | 10.05 |
| `RenameBuffer` | 2.1% | 0.48 | 3.42 | 3.91 |

node 对 lowering 的影响远小于对 flatten 的影响；`Rob` 关闭 node 后 lower 仍有 18.49 s。
第 35–55 s 的单核窗口与 `Rob` 耗时相符（跨度对应是推断，耗时本身是实测）。

### 3.4 硬件计数（`phase-profile`，5 s 间隔）

flatten 前段 IPC 约 1.0、L3 miss 约 3/千指令；后段约 2.5、约 0.5/千指令。
前段是大哈希表上的 cache miss，后段是字符串解析和校验。

## 4. 方案

### F18.0 测量基线（先做）

1. 更正 §2 的 F17 数字。
2. 把 frame-pointer 隔离构建和 perf fp 流程做成 Makefile target，替换无效的 dwarf 采样。
3. 合入默认关闭的阶段计时。已新增 `benchmark_f18_firrtl_ingest` target，并完成首个
   `F18/benchmark` 运行；仍需固定 CPU 并至少重复三次。
4. 验收指标改为**各阶段墙钟 + 总 CPU + 单线程占比**，不再使用固定函数族比例。

### F18.1 SemanticTree 来源模型（最大项，实测上界 69.5 s）

现状：`firrtl.node.*` 是 `vector<string>` 形式的 canonical key，每次改写都要解析、限定、校验、
写回。flatten 中 `copyQualified` 18.3 s，`recordRetention` 5.8 s，inventory 5.1 s。问题不只是
字符串慢，而是 GRH 已有模块层次与来源信息彼此分离：flatten 消除电路实例边界后，只能给每个
op 的来源字符串重新拼接实例路径。

本项以 SemanticTree 取代这套文本属性，不再采用“给 canonical key 加一层字符串 interner”的方案。
已经确定的设计如下：

1. **每个 Graph 拥有一棵定义内的 SemanticTree。** 树描述模块、声明、FIRRTL node 表达式以及
   Bundle 字段、Vector 元素等来源关系。每个叶节点有图内 `SemanticId`；节点保存结构关系，不保存
   指向本 Graph value/op 的裸指针。数据结构保持语言中立，但 F18 只接入 FIRRTL，SV 来源树接入
   不在本阶段范围内。
2. **op 和 value 分别携带 `semanticIdList`。** op 的列表表示它直接参与哪些源表达式/node 的计算；
   value 的列表表示它当前对应哪些源声明、源 node 或源表达式结果。列表允许多来源，不能用单个
   `SemanticId` 替代。实现上使用与现有 value/op 列相同生命周期的整数列，compact、clone 和块导入
   必须同步重映射。
3. **删除旧来源属性，不复制旧角色。** 新通路不再生成或传播 `firrtl.node.members`、
   `firrtl.node.origins`、`firrtl.node.roots`、`firrtl.node.rootResults` 和 `originModules`。
   `SemanticId` 本身就是来源，因此无需重复保存 origins；value 与叶节点的关联已经表达 root，
   不再需要 roots/rootResults；实例模块路径沿 SemanticTree 的实例节点取得，不再逐 op 保存
   `originModules`。旧 JSON 兼容和旧字段重建不属于 F18，不为还原旧 schema 保留平行信息。
4. **flatten 只增加实例节点并组合整数。** 每个被展开实例先建立一个实例节点，定义树由
   `shared_ptr` 保持生命周期，不按实例复制。`SemanticId` 由实例节点与定义内节点组合而成，路径查询
   先沿实例链、再沿定义树还原。value/op 的 `semanticIdList` 以块为单位预分配并连续改写；共享叶节点
   必须结合实例上下文才是完整来源，源 Graph 删除后不得留下悬垂指针。
5. **变换只维护整数关联。** F18 只改造 FIRRTL lowering、ingest 内必要的 pre-flatten 适配和
   hier-flatten。多来源合并在整数列表上进行；诊断和 inspect 需要路径时沿树生成，不在热路径维护
   canonical 文本。flatten 后的 simplify、GrhSIM 分图/CSE/emit 以及 SV 的来源模型重构均另立阶段，
   不在 F18 中迁移，也不作为本阶段性能或功能验收范围。
6. **census 只算一次。** inventory、仍存在的结果和删除情况由 SemanticTree 及其关联导出，只在
   ingest/flatten 终点或实际消费者需要时计算，不再每 pass 每图重复扫描文本。中间阶段必须报告的
   表示错误仍保留在原位置。

验收：同一模块定义经两个实例展开后来源路径不混淆；Bundle/Vector 叶子的来源关联正确；op/value
多来源列表在必要的 pre-flatten 变换和 flatten 后不丢失、不产生重复；源 Graph 删除及目标 Graph
compact 后来源仍有效；重复运行的结构化来源关系确定；F18 通路不再产生上述五类旧属性。

预算：ingest→flatten 中来源信息相关工作减少 ≥ 45 s。69.5 s 是关闭 node 的诊断上界，不是收益承诺；
flatten 后的 simplify、GrhSIM 和导出成本不计入本项预算。

### F18.2 symbol 只标记有语义的信号，JSON 使用局部裸 ID（P0，最高优先级）

**P0 决议：** JSON 中的裸整数 ID 只表达当前 Graph 文件内的结构关联，不能作为跨文件、跨
`compact` 或跨变换的句柄；`sym` 只表示需要稳定保留的语义 symbol。临时 value/op 不生成
`tmp_*` 名字，不写入 `sym`，也不因 JSON round trip 进入 SymbolTable。这个边界先于其它 F18
性能改造完成，后续 runtime、flatten 和下游审计都以它为约束。

symbol 的本意是标记有语义的信号，不是给所有对象批量命名。当前每个临时 value/op 都拼接
`_val_N`/`_op_N`、hash、写字符串池并绑定符号；lowering 和 flatten 各付一次，`retain` 还要重新
intern 源图的全部内部名。flatten 中名字约占 24.4 s。

已确认：JSON 导出不要求临时对象的名字和 ID 跨运行稳定。因此不再复现 `_val_N`/`_op_N` 文本，
也不把临时对象塞进 `sym` 字段。`sym` 只表示必须保留的语义 symbol；结构关联使用当前 JSON
图内的局部整数 ID，ID 只在该份 JSON 内有效。这个 JSON 边界方案已优先于 F18.0 的测量工作交付；
后续 profiling 和大范围 provenance 改造均以该边界为基线。

设计：

1. **显式的临时构造接口。** 新增 `createTemporaryValue(type)`/`createTemporaryOperation(kind)`，
   产生无效 SymbolId，不写字符串池、SymbolTable 和 `symbolIndex_`。`createValue(type)`/
   `createOperation(kind)` 的默认行为先不改。`GraphStore` 的 add 和块追加路径接受无效 symbol，
   compact 跳过无效 symbol 的绑定。
2. **只切换批量路径。** FIRRTL lowering 的 `Lowerer::op`、assign、constant、register 读写口，以及
   hier-flatten 中无语义的 value/op 使用无 symbol 对象。pass 自身创建的少量对象暂不迁移。
3. **被引用的对象必须有 symbol。** `regSymbol`、`latchSymbol` 等属性按文本引用状态 op，所以
   register/latch/memory 状态、kInstance 和 kSystemTask 保留 symbol。例如 `lower.cpp` 中读取
   `getOperation(state).symbolText()` 的状态 op 必须显式取得名字。
4. **按语义判断，不按名字前缀判断。** `redundant_elim.cpp:195` 中无 symbol 必须算作内部值（当前逻辑
   遇到空名字会判为非内部）；`hier_flatten.cpp:1121` 的 `_val_` 前缀判断同样要覆盖无 symbol。
5. **显示名只用于人类可读边界。** 保留 `Graph::valueDisplayName(id)`/`opDisplayName(id)` 供诊断、
   inspect 和仍以文本为 ABI 的下游使用：有 symbol 返回其文本，否则由当前 ID 生成，并避开已有
   语义名字。显示名不是身份，compact 后可能变化，也不得写入 v3 JSON 的结构引用。
   `symbolText(invalid)` 静默返回空串，这是主要风险，迁移时须逐处审计。
6. **JSON 局部 ID（本项优先交付）：** 新的 Graph JSON 格式为每个 `vals`/`ops` 条目写一个
   graph-local `id`；ID 按本次导出的 live 条目顺序生成，使用正整数，既不等同于运行时
   `ValueId`/`OperationId`，也不进入语义身份。只有有 symbol 的 value/op 才写 `sym`；临时对象
   省略 `sym`，不写临时显示名，也不需要 `tmp` 标记。`ops.in`/`ops.out`、`ports.*.val`、
   `ports.inout.{in,out,oe}` 使用 value ID，`values.def` 与 `values.users[].op` 使用 operation ID。
   ID 的命名空间由字段决定（value 与 operation 可以各自从 1 开始），loader 通过局部表重定位，
   不把裸 ID 当作跨 JSON 或跨 compact 的稳定句柄。
   例如一个临时结果只写 `{"id": 3, "w": 8, ...}`，而有语义的输入写
   `{"id": 1, "sym": "in", ...}`；使用它们的 operation 写 `"in": [1, 2]`，不会在任何
   结构引用中出现 `tmp_val_*` 或 `tmp_op_*`。
7. **JSON 语义边界：** graph symbol、语义 value/op 的 `sym`、`declaredSymbols`、
   `generateGroups` 以及 `regSymbol`/`latchSymbol` 等属性继续使用稳定文本；它们不是结构边。
   F18.1 的 SemanticTree 不接旧 node canonical-key JSON，也不承担旧 node schema 的导入导出适配。
8. **版本与兼容：** 局部 ID 方案已将 Graph `formatVersion` 提升为 3，Store 只写新格式，
   Load 同时保留 v2 的字符串引用兼容。v3 loader 先建立 values 的 ID 表，再绑定 ports，随后
   建立 operations 的 ID 表并接入 edges；`def`/`users` 在两张表都完成后校验，或从 edges
   重建后校验，不能依赖 operation 的语义 symbol。两套 writer（`Graph::writeJson` 与 `StoreJson`）
   必须保持相同字段和引用规则。
9. **排序：** `vals`/`ops` 的导出顺序继续决定局部 ID；use-list 按 operation 局部 ID 和 operand
   下标排序。其它按名字排序的代码须逐处审计，但不能把局部 ID 写入语义属性。
10. **下游边界。** GrhSIM IR 仍以 symbol 文本为身份，`grh-to-grhsim` 入口调用
   `Graph::materializeInternalSymbols()` 给顶层图的无 symbol 对象补名字，下游暂不改。
   这只是把这部分成本推迟到 flatten 之后，**不是消除**；整机 FIRRTL→C++ 须单独计入，
   后续应让 GrhSIM 也不再依赖临时名。SV emit 路径接收 const Design，不能使用该调用，
   需改用显示名或另设入口。

历史探针（2026-11-04，已归档）：早期把默认 `createValue`/`createOperation` 全部改为无
symbol 后，`make test_wolvrix` 曾为 62/81；失败暴露了 GrhSIM/pass 和测试夹具仍把 symbol
文本当作身份（例如 `regSymbol` 解析、时钟分组 key）。随后恢复默认构造接口的原有 retention
行为，并保留显式临时对象 API、显示名边界和 JSON v3 局部 ID；当前实现已重新通过全量 CTest。
历史日志保留在 `ptmp/firrtl-ingest/F18/logs/test1.log`，当前门禁见下文的 `test2.log`。

验收（局部 ID 方案替代临时名归一化门禁）：

- 新增 v2→v3 结构等价比较：语义 `sym`、端口、属性、来源和拓扑必须一致；局部 ID 只按
  value/op 类型和引用关系比较，不比较其跨运行数值。
- v3 JSON 中临时 value/op 不含 `sym`，store→load→store 前后 SymbolTable 的 symbol 数量、
  文本和绑定对象完全一致；roundtrip 不得引入任何额外 symbol。
- 所有 operand/result/port/def/user 引用只能解析到对应 ID 类型的 live 实体，未知、重复、跨类型
  或指向错误命名空间的 ID 必须拒绝。
- v2 字符串引用仍可加载；加载旧 JSON 后重新导出为 v3，不得把旧临时显示名提升为语义 symbol。
- 诊断只按内容和严重级别校验，不比较顺序，也不要求为保序而排序或归一化；临时对象若需要展示，使用诊断专用显示文本，不回写 JSON `sym`。
- 同一输入重复运行输出保持确定；局部 ID 可因 compact/变换变化，但单份 JSON 内所有引用必须一致。
- 当前实现已覆盖两套 writer、v3 loader、v2 字符串兼容、临时对象 roundtrip 与引用一致性校验；
  `make test_wolvrix` 于 2026-11-04 以 `test2.log` 记录 **81/81 通过**。该结果只证明仓库
  CTest 门禁，workflow、GrhSIM flow、生成模型和固定 CPU 的三次性能重复仍待 F18 全流程门禁。

预算：flatten ≥ 15 s，并降低 lowering 和 `retain` 成本，同时让 F18.3 可以取消逐行符号绑定。
该预算只覆盖到 flatten 结束，不含第 8 条推迟到下游的成本。

### F18.3 flatten 真批量化（依赖 F18.1、F18.2）

合并到一张图不可避免要改写符号、operand ID 和 SemanticId，但目标是整块改写，不是逐对象调用。

当前实现状态：

| 内容 | 现状 |
| --- | --- |
| value width/isSigned/type/domain、op kind | 已批量：共享页 |
| 单次使用来源的 operands/results | 已批量：接管缓冲区后原位改写 |
| 符号校验与绑定 | 仅语义对象保留；临时对象无 symbol，哈希空间按实际 symbol 数预留 |
| SrcLoc | prepare 阶段一次导入完整记录映射，行上只做数组索引 |
| 属性 | 旧 node 和 `originModules` 已删除，其余属性继续块导入 |
| SemanticTree 与 semanticIdList | 共享定义树，每实例只加一个实例节点；value/op 来源按块预分配并连续改写 |
| 字符串池 | 仅懒加载并 intern 实际被属性或 SrcLoc 引用的文本 |

改法：

1. **块级校验：** 输入来自已校验的 compact 图时，只校验块边界，不逐行检查。
2. **SrcLoc 整体映射：** 按记录表一次导入并建立映射数组，行上只查表；不逐行 import。
3. **符号不逐行绑定：** F18.2 后临时对象没有 symbol；只有语义对象走小表。
4. **ID 一次改写：** value/op 列、边和 semanticIdList 按块基址和映射数组改写一遍；SemanticTree
   按实例块合并，不再进入逐 op 属性复制和文本限定路径。
5. **字符串池：** 改为分段池，或只导入块中实际被属性引用的字符串，不逐条 `retain`。
   分段后同一文本可能有多个 ID，需先审计依赖 StringId 相等的代码。

**并行不作为本项目标。** 上述完成后再测单线程耗时。只有剩余逐块写入仍占主要部分时才启用线程池，
写入范围互不重叠，并须证明并行与串行结果逐字节一致。现有线程池接入不撤除，但不计入预算。

预算：块函数 18.7 s → ≤ 8 s（单线程）；flatten 总计 ≤ 25 s。

### F18.4 `Rob` 模块内并行（可行性结论：本阶段不实施）

模块级并行下，lowering 墙钟不可能低于 `Rob`。F17 的模块计时为 analyze 4.74 s、lower 23.97 s；
关闭 node 后 lower 仍为 18.49 s。这些历史数字是可行性好评估的依据，不是当前实现的模块计时。

评估结论是不在 F18 按语句切分 `Rob`。当前 lowering 的 connection last-wins driver 状态、跨语句
value 引用、寄存器/memory 写口、guard 与 clock-pulse 缓存都按串行顺序维护；各块独立生成局部列后，
没有低成本且保持语义的合并边界。若改为两阶段依赖图 lowering 再确定性合并，已是新的前端架构，
不是 F18 的单位成本优化，不能用未证明的并行拆分换取墙钟。

F18 保留模块体最大优先的既有调度，并将 annotations 移入 lowering worker，消除协调线程的额外
串行成本。本阶段接受 `Rob` 的单模块下限；F18.4 不做模块内并行实现，也不将其列为剩余门禁。

### F18.5 ingest 串行尾部与单位成本

1. **发布段（约 8 s）：** `applyAnnotations` 已移入 lowering worker，串行路径保持原行为。
2. **verify（约 15 s 墙钟）：** 保留既有 `localCyclesChecked` 证明门控，只检查缺少证明的图。
3. **parse/summary 并行衰减：** 保留大模块优先调度，避免小模块先占满 worker 后留下 `Rob` 长尾。
4. **语义层字符串表：** `Semantics` 声明和 memory port 已改为透明哈希查找并按输入规模预留；
   诊断顺序不是约束。生成源位置另按原路径缓存 canonical 结果，未变化的 SrcLoc 不再重写。

## 5. 预算与顺序

| 阶段 | 现状（formal/比例） | F18 目标 | 主要依赖 |
| --- | ---: | ---: | --- |
| parse/接口 | 约 12 s | ≤ 8 s | F18.5 |
| analyze + lower | 约 36 s | ≤ 25 s | F18.1/2，低于此需 F18.4 |
| 发布 + verify | 约 20 s | ≤ 8 s | F18.1、F18.5 |
| 前置局部链 + compact | 约 15 s | ≤ 8 s | F18.1 |
| hier-flatten | 85.4 s | ≤ 25 s | F18.1/2/3 |
| 连续墙钟 | 167.8 s | **≤ 75 s** | — |

ingest 分段由 95 s 诊断运行按比例换算到 formal 82 s，只是估计。

flatten 目标按 §3.1 比例换算到 formal 85 s，再逐项估计：node 约 30 → 4 s，名字约 25 → 4 s，
块函数约 19 → 8 s，其它约 13 → 8 s，合计约 24 s。该估计不含并行。关闭 node 的实测（97.3 → 47.0 s）
说明第一项有依据；后三项未实测。

GSIM 对照有两个口径：parse+Init 为 76.5 s；若算到 `inferAllWidth` 为 164.8 s，这更接近
Wolvrix 已完成的宽度推断和环检查工作，但两边仍不等价。两个口径都应报告。
≤ 75 s 仅略低于 parse+Init 口径，余量很小，不保证达到。F18.4 可行时可进一步降低，但不计入目标。

顺序：**F18.2-JSON-ID（已完成）→ F18.2 runtime consumers → F18.0 → F18.1 SemanticTree
→ F18.3**；F18.5 可并行推进；F18.4 先评估。flatten 并行放在 F18.3 单线程结果之后，
按实测决定。每项单独 A/B，避免无法归因。

性能门禁沿用 F17：同一冻结输入、CPU 0–31、10 worker、annotations 开启；ingest/flatten 比较
拓扑、诊断内容和严重级别以及 SemanticTree 结构化来源关系，不与旧 node JSON 做 SHA 或字段兼容比较。
诊断顺序不是门禁，不要求按序相同、排序或归一化。功能门禁为 FIRRTL ingest、必要的 pre-flatten、
hier-flatten 和新增 SemanticTree 测试；flatten 后的 simplify、GrhSIM 及整机 workflow 另立阶段，
不要求 F18 完成它们对旧 node 属性删除的适配。构建和测试走 Makefile。性能结论必须来自无采样
formal 运行，并至少重复三次。日志放在 `ptmp/firrtl-ingest/F18/`。

## 6. 已确定边界

1. F18.2-JSON-ID 已完成优先交付；JSON 的 `sym` 只保留稳定语义 symbol，临时对象只用局部 ID。
2. F18.1 使用 SemanticTree 和 op/value 的 semanticIdList，不保留旧 node 文本 key，也不做旧 JSON 兼容。
3. F18 范围止于 hier-flatten；SV SemanticTree、flatten 后的 simplify 和 GrhSIM 重构另立阶段。
4. GSIM 对照同时报告 parse+Init 76.5 s 与 inferAllWidth 164.8 s 两个口径，不混为等价工作。
5. 诊断顺序不是约束；不得为保留旧顺序选择容器、限制并行或增加排序/归一化成本。

## 7. 未测量

- 最终三轮 formal 已完成并汇总到 `F18/final/summary.json`；frame-pointer perf 与报告也已通过，
  见 `F18/perf-fp-final/record.json`，采样墙钟 72.77 s，不用于替代无采样 formal 中位数。
- Codex 分析任务在写出报告前被取消，本文由其运行数据和 perf.data 重新分析得出。
- F18.4 已完成可行性结论：不在本阶段做 `Rob` 模块内并行，接受单模块下限，详见该节。
- F18.2 已有共享实现的正式性能观测；此前 `F18/formal/run1–run3` 使用 `fused_prefix=false`，
  只能作为重复稳定性观察，最终 A/B 改用 `F18/final/run1–run3` 的 fused formal 结果。
- `fp` 构建与 r2 有差异（`-fno-omit-frame-pointer`，后两次运行还带模块计时），不用于绝对性能结论。
- 全量 CTest 当前 76/83；7 项失败均依赖已删除的旧 node/origin 表示，不属于 F18 门禁。新增
  `grh-semantic-tree` 与 `firrtl-semantic-tree` 均通过，且两项在 ASAN 下也通过。旧
  `firrtl-node-pipeline` 对失效 metadata 的 `std::optional`/variant 未定义访问在 Release 下表现为段错误，
  ASAN 下为 `std::get: wrong index for variant`，不是新 SemanticTree 通路的内存错误。
