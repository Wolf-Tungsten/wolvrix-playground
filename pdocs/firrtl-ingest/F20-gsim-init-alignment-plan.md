# F20：FIRRTL ingest→flatten 与 GSIM AST2Graph 对齐实验计划

日期：2026-11-05；2026-11-06 追加 memory lowering 修复后复核。状态：F20.P1/P2 已完成，§3.7 的 bare 状态元件对齐、写口覆盖及 JSON 往返复核已完成；其余 G1–G5 结构对齐实验尚未开始。此前 P1/P2 回归结论保留作历史基线，不替代本轮证据。
§2 的数字是本计划预检的实测值，其余门槛都是实验前登记的提案，不是结果。

## 1. 要回答的问题

F18/F19 已打通 FIRRTL ingest→hier-flatten。工作假设是：其输出等价于 GSIM AST2Graph 后的初始图，
IR 形式不同，但 Node/ENode 在两边都有对应实体。F20 把这个假设变成可判定的实验：

> 同一份 `SimTop.fir`，**无重写 pass 的 flatten 图**与 **GSIM Init 图**，是否在状态与边界对象、
> Node、Node DAG、表达式内容四个层面足够一致，使后续可以把 GSIM pass 序列当作逐阶段的对照参考？

**不回答：** 功能正确性（F10 差分负责）、生成或运行性能（F14–F19）、flatten 之后的 simplify/分图。
结构对齐不能证明功能等价，功能等价也不能推出结构对齐。

## 2. 预检发现

输入均为 SHA-256 `cc46aae1…dc754a` 的 `SimTop.fir`。GSIM 数据来自 `ptmp/firrtl-ingest/F20/pilot-gsim-stats/`，
二进制为现有 `a3ecb26` 构建。GrhSIM 数据来自 F19 的两个 checkpoint，都不是 F20 的比较对象，只用来判断可行性：

- 原始 ingest：`F19/identity/ingest.json`，**按模块定义计数**（仍有 `kInstance`）。
- 带 prefix 的 flatten：`F19/size-experiment/minimal.json`，按实例计数，但已被 prefix pass 改写。

GSIM 按实例计数。设计有 9,487 个模块、10,271 条 `inst` 语句，因此定义计数与实例计数接近但不相等，跨口径比较只能作为线索。

### 2.1 GSIM Init 基线

| 项目 | Init 实测 |
| --- | ---: |
| Node 总数（不含 `NODE_MEMORY`，见 §2.4） | 7,826,232 |
| `NODE_MEMORY`（另计） | 3,324 |
| `NODE_OTHERS` | 7,413,352 |
| `NODE_REG_SRC` / `NODE_REG_DST` | 197,268 / 197,268 |
| `NODE_READER` / `WRITER` / `READWRITER` | 4,295 / 4,648 / 290 |
| `NODE_SPECIAL` | 7,836（assert 6,920 + printf 915 + exit 1） |
| `NODE_EXT` / `EXT_IN` / `EXT_OUT` | 111 / 1,137 / 14 |
| `NODE_INP` / `NODE_OUT` | 8 / 5 |
| Node 边 / dep 边 | 12,668,624 / 13,144,164 |
| 树槽位总数 | 9,744,643 |
| `assignTree` / `resetVal` / `resetCond` / `resetTree` / `memTree` / `effectClock` | 9,250,445 / 197,268 / 197,268 / 81,054 / 10,786 / 7,822 |
| 去重 ENode | 40,643,484 |
| 其中节点引用叶子 | 24,305,187 |
| 其中 `OP_INT` | 2,590,017 |
| 其中 `OP_INDEX_INT` + `OP_INDEX` | 6,625,893 |
| 其余（含 `OP_WHEN` 814,868、`OP_MUX` 1,570,504） | 7,122,387 |
| 每 Node ENode 数 | 均值 5.20，中位数 4，p99 20，最大 270,730 |
| 无 ENode 的 Node | 3,591（类型未确认） |

**这个 ENode 总数不等于活逻辑。** 它含 AST 构造遗留的树：写口用完后保留的 `memTree`（`OP_INFER_MEM` 4,450 很可能来自此处，
由代码推断，待 dump 确认），以及无复位寄存器的假复位（`resetCond` 为常量 0，`resetVal` 为自引用，见 `visitRegDef`）；
只有 81,054 个寄存器有真实 `resetTree`。比较时只用活树，见 §3.3。

### 2.2 对假设的修正

1. **Init 不是纯 AST 翻译，也没有宽度。** AST2Graph 结束前已执行 `addReset`、`addUpdateTree`、
   `clockOptimize`、`invalidArrayOptimize`、`removeDummyDim`（`AST2Graph.cpp:1623–1650`），
   而 `inferAllWidth` 在 Init 之后（`main.cpp:321`），Init 日志中 ENode 为 `width=-1`。
   GrhSIM 在 ingest 就完成了宽度推断。因此结构比较用 Init，宽度比较需要后续阶段（§3.3）。
2. **生产 prefix 不是中性的。** flatten 前的 8 个 pass 中有多个重写图。本计划按决定全部移除（§3.1）。
3. **SemanticTree 不含实例名，这是实现错误。** flatten 复制来源树时保留了模块名，路径成为定义路径，
   无法与 GSIM 的实例路径对应，也无法区分同一模块的两个实例。flatten 后只有少量 value 有名字
   （prefix checkpoint 中 25,990,263 个 value 里 665,371 个有 `sym`），无法替代树路径。**由 F20.P1 修正（§3.0）。**
4. **SemanticId 没有覆盖全部 op，原因是赋值范围过窄。** `currentSemantic_` 只在 lowering `node` 定义时设置
   （`lower.cpp:1085–1087`），`connect`、复位、`memories()`、`effects()`、`instances()` 都在其为 0 时运行。
   而 GSIM 的 ENode 只能通过 Node 的树槽位到达，所有权由结构保证（§2.4）。**由 F20.P2 修正（§3.0）。**
5. **两端抽象层次不同，主要差在 memory。** GSIM 的存储口是一个 Node 加少量 ENode，GrhSIM 在 lowering 就展开完整语义（§2.4）。
   op 数不能直接与 ENode 数比较，须分桶（§4 G4）。
6. **CHIRRTL memory 没有可归属的 SemanticTree 声明。** `collectMemory()` 只为标准 `mem` 建立
   `Semantics::Declaration` 并加入 `declarationOrder`；`smem/cmem` 只进入 `memories`，但其 storage
   `kRegister` 仍在 lowering 中创建（`memory.cpp:25–74`，`lower.cpp:722–733`）。因此 P2 不能直接把存储归到
   现有 memory 声明，必须按规则 5 补充 `SemanticNodeKind::Declaration`，且不得引入普通 value/op。

### 2.3 原始 ingest 的 SemanticId 覆盖（按模块定义）

34,187,631 个 op 中 22,268,731 个（65.1%）带 ID，缺 11,918,900 个。覆盖率与 prefix checkpoint 的 64.0% 接近，说明缺口来自 lowering，
不是 prefix。数据见 `ptmp/firrtl-ingest/F20/pilot-grh-stats/ingest-semantic-by-kind.txt`。

| kind | 无 ID | 有 ID 占比 | 可能来源（未逐调用点统计） |
| --- | ---: | ---: | --- |
| `kConstant` | 3,184,954 | 68.1% | connect、memory 等 `node` 之外的 lowering |
| `kAssign` | 2,622,128 | 68.8% | connect 连线 |
| `kSliceStatic` | 2,267,808 | 27.9% | connect 和部分写的位布局 |
| `kConcat` | 1,416,377 | 47.2% | 同上 |
| `kMux` | 516,545 | 75.5% | `when` 分支合并、guard |
| `kRegisterReadArrayPort` | 430,201 | 0% | `stateRead` 主动清零（`lower.cpp:482–486`） |
| `kSliceArray` | 423,230 | 86.3% | connect、memory |
| `kRegisterWritePort` | 314,435 | 0% | 状态写 |
| `kAnd` | 281,330 | 72.8% | guard、memory 使能 |
| `kNot` | 217,236 | 7.2% | 可能是 guard 和 memory |
| `kRegisterWriteArrayPort` | 127,323 | 0% | 状态写 |

**正面信号：** 源级运算几乎都已覆盖。多项带 ID 的 op 数与 GSIM ENode 数完全相等：

| GRH（带 ID） | GSIM | 两端计数 |
| --- | --- | ---: |
| `kEq` | `OP_EQ` | 460,741 |
| `kNe` | `OP_NEQ` | 14,312 |
| `kGe` / `kGt` / `kLe` | `OP_GEQ` / `OP_GT` / `OP_LEQ` | 41,681 / 8,977 / 9,125 |
| `kXor` | `OP_XOR` | 52,957 |
| `kSub` | `OP_SUB` | 11,736 |
| `kReduceAnd` | `OP_ANDR` | 14,511 |

这支持 Node/ENode 对应的假设，但不是全部相等（`kLt` 带 ID 64,008，`OP_LT` 44,447），定义计数与实例计数为何恰好相等也尚未解释。

早期曾按原始 `kRegister` 200,896 = 带 ID 195,155 + 无 ID 5,741 推测 `pipeline()` 约 1,128 个、`$$ADDR` 约 2,113 个。
该估算已被 §3.6 的 flat 和 GSIM Init 名称统计推翻：修复前原始模块定义图的分类为 plain 195,167、memory 4,613、pipeline 672、
clockHistory 220、collision 224；修复前 flat 的分类见 §3.6。GSIM 精确后缀为 `$$ADDR` 的寄存器实际是 488 个。

### 2.4 GSIM AST2Graph 如何构造边界和 memory

**实例。** GSIM 没有实例对象。`visitInst` 压入名字前缀，重新遍历子模块 AST（`AST2Graph.cpp:820`），每个实例都新建 Node 和 ENode。

| 项目 | GSIM | GrhSIM |
| --- | --- | --- |
| 结构 | 直接构造一张平图 | 每模块一张图加 `kInstance`，由 `hier-flatten` 合并 |
| 端口 | 每个实例端口叶子一个 Node，类型 `NODE_OTHERS`（仅顶层为 `INP`/`OUT`） | 父侧和子侧各一个 value，`bindEquivalentPort` 合并 |
| 引用 | 父侧 `cpu.x` 和子侧 `x` 解析到同一个 Node `cpu$x` | 映射到父侧 value |
| `connect cpu.x, y` | 该 Node 得到一棵只有引用叶子的树 | connect lowering 的 `kAssign` |
| 额外边界逻辑 | 无 | 类型不同时才有 `kAssign`（`hier_flatten.cpp` 的 `mapInputPortType`、`mapOutputPortType`） |

**memory。** 全设计 1,858 个端口都是 CHIRRTL `mport`（`infer` 1,436、`read` 198、`write` 198、`rdwr` 26），没有标准 `mem` 语句。

| 项目 | GSIM | GrhSIM |
| --- | --- | --- |
| 存储 | 每叶子一个 `NODE_MEMORY`，只进 `g->memory`，**不进 `allSignals`，因此不在 Init 统计内** | 每叶子一个带 `firrtl.memory` 的 `kRegister` |
| 端口 | 每端口每叶子一个 Node；`infer` 按使用方式定为读或写（`AST2Graph.cpp:703,1568–1575`） | 地址、时钟、使能、数据、掩码驱动 |
| 读 | `OP_READ_MEM(addr)` | 读口加使能、越界检查、poison mux |
| 读延迟 1 | 新增寄存器对 `port$$ADDR`（`allocAddrNode`） | `pipeline()` 寄存器 |
| 写 | `OP_WHEN(cond, OP_WRITE_MEM(addr, data))`（`whenConnect`） | `kRegisterWriteArrayMaskPort` 加使能、掩码跟踪、冲突逻辑 |
| 写冲突、越界 | 此阶段无 ENode，推测由后续阶段处理 | `kEq`、`kMux`、`kAnd`、`kLt` 等，按端口（冲突按写口对）展开 |

**外部模块。** 每实例一个 `NODE_EXT`，树为 `OP_EXT_FUNC(输入引用…)`，每个输出 Node 一棵 `OP_EXT_FUNC(ref ext)`；111 + 14 = 125，与 `OP_EXT_FUNC` 计数闭合。
`NODE_EXT` 名取 `module->name`，可能不是实例路径形式，需要单独映射。ClockGate 特判，直接构造 `Q = CK & (E | TE)`。
GrhSIM 则可能把带 SV 源的外部模块展开成普通 op（manifest 含 `SimJTAG.v` 和 resource roots），这些 op 没有 SemanticTree，由 P2 规则 9 处理。

**所有权。** Init 中 ENode 只能经 Node 的树槽位到达，但这不是严格划分：逐 Node 求和 40,673,487，去重 40,643,484，
差 30,003，即有 ENode 被多个 Node 共用（如聚合寄存器共用 `resetCond` 根，memory 端口叶子共用 `addr_enode`）。
所以**对齐要求的是完全覆盖，不是不相交划分**：每个 op 至少属于一个 Node，允许共享。

GSIM 还生成没有 FIRRTL 声明的 Node：`WHEN_COND_<lineno>`（`AST2Graph.cpp:1306`）和 `port$$ADDR`，须作为已知类别处理。

## 3. 实验设计

### 3.0 前置修正

两项都是实现修正，**先于 F20.0**，按 P1→P2 顺序实施，各自独立提交。P1 确定“属于哪个实例的哪个声明”，P2 保证“每个 op 都有归属”。
P1 只修正实例路径，不新增 memory 存储、端口或 `pipeline()` 的 SemanticId；这些归属全部由 P2 负责，不能只用 P1 做 memory 对齐。

#### F20.P1：SemanticTree 使用实例名

**问题。** `SemanticTree::appendTree` 整段复制来源树，复制后的根节点沿用来源模块名
（`semantic_tree.cpp:76–99`，调用点 `hier_flatten.cpp:1543`）。规定的行为是：flatten 后复制出的根节点使用**实例名**。
这修正 F19 决定 5 中“来源路径表达定义来源、实例名不进入 SemanticTree”的部分；“不恢复 Instance 节点、
SemanticId 为本地编号、整段复制”的决定不变。

| 实例 | 当前路径 | 修正后路径 |
| --- | --- | --- |
| `core0: Child` | `top/Child/n/bits` | `top/core0/n/bits` |
| `core1: Child` | `top/Child/n/bits` | `top/core1/n/bits` |
| 嵌套 `core0.lsu: Lsu` | `top/Child/Lsu/n` | `top/core0/lsu/n` |

根节点仍是顶层模块名。v4 JSON 字段和节点结构不变，改变的只是非根 `module` 节点 `name` 的含义。

**实现。**

1. `SemanticTree::appendTree(source, parent, rootName)` 和 `Graph::appendSemanticTree(source, parent, rootName)`
   增加**必填**参数，不提供默认值，避免调用方退回模块名。`rootName` 为空时抛 `std::invalid_argument`。
2. `hier_flatten.cpp` 传入 `state.nodeInstancePath.back()`。该值在 `inlineInstanceInfo` 中由实例名经
   `normalizeComponent` 和 `uniqueInstanceComponent` 得到，并已压栈（`hier_flatten.cpp:1070–1072,1299`），
   与 `inst$…` 符号使用同一段名字。缺少实例名时回退模块名的现有逻辑（`:1070`）同样适用；实施时须确认
   `inlineGraphContents` 只经由 `inlineInstanceInfo` 进入，路径栈为空时报错，不静默写入模块名。
3. 字符区只写一份根名：先追加 `rootName`，再追加来源字符区中根名之后的部分，其余节点偏移相应平移。
   不能只改根节点偏移而保留旧模块名字节：孤立字节会使 `name_bytes` 在 store→load 后变化，破坏 F19 的往返校验。
   实施时确认来源根名总在偏移 0（构造函数和 loader 均如此）。
4. 容量检查按新的字符总量计算，保持几何增长，不重新引入 F19 §6.1 的逐次精确 reserve 问题。

**测试和文档。**

- 更新 `tests/grh/test_semantic_tree.cpp`、`tests/store/test_semantic_tree_json.cpp` 中的调用和路径断言；
  `tests/ingest/test_firrtl_semantic_tree.cpp` 增加真实 FIRRTL flatten 用例。
- 新增覆盖：同一模块两个实例路径不同；三层嵌套得到完整实例路径；二次 flatten 保留内层实例名；
  实例名被 `uniqueInstanceComponent` 改写时与符号一致；空 `rootName` 被拒绝；store→load→store 字节一致且 `name_bytes` 不变。
- 同步 `wolvrix/docs/grh/grh-json-spec.md`（第 43、82 行附近）和 F19 文档决定 5、§4 示例（`Child` 改为实例名语义，并注明由 F20.P1 修正）。

**退出条件。**

1. `make test_grh_semantic_tree`、`make test_firrtl_semantic_tree`、`make test_f19_semantic_json`、
   `make test_f19_semantic_json_asan` 通过；`make test_wolvrix` 相对 F19 的 77/84 无新增失败。
2. 重新生成香山 flatten checkpoint：相对 F19，树节点数（12,940,224）、value/op 来源行数（6,056,621 / 17,040,867）和
   SemanticId 总数（23,745,580）**不变**。`name_bytes` 会变化，按新值记录。除非根 `module` 节点名外，checkpoint 内容应一致。
3. **路径唯一性：** 全设计不存在两个 Module 副本具有相同的完整实例路径。
4. **符号交叉校验：** 用 `declaredSymbols` 中带层次 `sym` 且有 SemanticId 的寄存器比较，树路径与 `inst$…` 符号前缀必须 100% 一致；memory/pipeline、loop 拆分等生成寄存器使用内部 `_op_N` 名称，按生成类别检查，不纳入声明符号比较。无 SemanticTree 的 SV 实现内部寄存器归父实例声明，只要求该实例路径是符号前缀，不要求包含 SV 内部寄存器名。
5. 全量 store→load→store 字节一致；flatten 墙钟与 F19 的 19.522 s 相比无明显退化（按 F19 formal 口径三轮中位数报告）。

#### F20.P2：所有 op 标注 SemanticId

**目标。** FIRRTL 路线上，ingest 和 flatten 之后**每个 op 都至少有一个 SemanticId**。这是 Node 对齐的前提：
未标注的 op 无法投影到 Node，G3、G4 都不成立。标注是完全覆盖，不是不相交划分，共享的 op 可以有多个 ID 或归入专门的生成节点。

**规则。** 归属按 op 的产生原因确定，不能由“先到先得”决定。

| # | 产生位置 | 归属 |
| --- | --- | --- |
| 1 | `node` 定义 | 现状不变：该声明叶子 |
| 2 | `connect`（含 `define`/`read`、`adapt`、位布局、分支合并、`drive`） | 被驱动叶子的 `driver.semantic`（`lower.cpp:525` 已取得 `driver`） |
| 3 | 复位写 | 该寄存器叶子 |
| 4 | `stateRead`、状态写口 | 读口归使用它的 Node，写口归被写寄存器。删除 `lower.cpp:483–486` 的清零；统计时读口归“引用”类，不计入运算（对应 GSIM 引用叶子） |
| 5 | `memories()` | 存储 `kRegister` 归 memory 声明；CHIRRTL 声明按下文补齐。端口的地址、使能、掩码、越界和 `pipeline()` 都归该端口叶子（`findDriver(port.name, leaf.fields).semantic`）。不再生成 collision/poison 或 clockHistory；写-写覆盖由显式 `writerOrder` 表达 |
| 6 | 共享且被缓存的 `guard()`（`guards_`） | **不能归第一个使用者。** 在树中新增专门的 `expression` 生成节点。guard 是决策图节点，**不**与 GSIM 的 `WHEN_COND` 一一对应，G3 按透明节点处理（§4）。event history 只由后端 `kEdgeDetect` 建立，裸 GRH 无 `clockPulse()` 节点 |
| 7 | `effects()`、`instances()` | `kSystemTask` 及其参数没有声明可归属，新增 `expression` 节点（名称含语句位置，供与 `NODE_SPECIAL` 按行号匹配）。`kInstance` 归实例声明，flatten 后消失 |
| 8 | `hier-flatten` 生成的边界 `kAssign`（`mapInputPortType`、`mapOutputPortType`） | 该端口叶子 |
| 9 | 无 SemanticTree 的来源图（SV，如 `SimJTAG.v`） | 这些 op 归 flatten 时父图中的实例声明，对应 GSIM 的 `NODE_EXT`。SV 自身不建 SemanticTree，ingest 覆盖统计时跳过，仍不在范围内 |
| 10 | flatten 后 `comb-loop-elim` 的 loop 拆分 | fragment value 继承原 value 的 SemanticId（无直接标注时取原定义 op）；克隆 op 继承其原 op 的 SemanticId 与 `originModules`；辅助 slice/concat 归被视图化的 value。禁止整环并集；`fragment-map-path` 导出原 value/op、位段和 fragment 的显式映射 |

规则 5 的 **CHIRRTL 补充约束**（本实验全部 memory 都属于此类）：

1. lowering 时为每个 `smem/cmem` 在 SemanticTree 中建立 `SemanticNodeKind::Declaration`，名称使用 memory 声明名；
   按 `memory.data` 的叶子补齐字段路径，得到 `实例路径/mem[/字段...]`。这里补的是 SemanticTree 节点，
   **不是** `Semantics::Declaration`：不得加入 `declarationOrder`，不得因此建立普通 value、driver 或 op。
2. 每个 storage `kRegister` 标注对应 memory 数据叶子的 SemanticId。`collectMemoryPort()` 已为 `mport` 建立独立声明，
   存储声明与端口声明在模块下保持同级，即 `实例路径/mem[...]` 与 `实例路径/r[...]`；不得把 `r` 嵌套到 `mem` 下，
   否则与 GSIM 的端口名不符。端口与存储的关联仍由读写的 storage/`regSymbol` 关系表达。
3. reader/writer/readwriter 的展开 op 归各自端口叶子组，与 GSIM 的 `OP_READ_MEM`/`OP_WRITE_MEM` 不做一一对应。
   `pipeline()` 归发起它的端口并保留生成类别；不能要求 SemanticTree 自动生成 GSIM 的 `port$$ADDR` 名称。

实施时 `grep` 所有 `createOperation`/`createTemporaryOperation` 调用点（`lower.cpp`、`comb_loop_elim.cpp` 和
`hier_flatten.cpp`），逐个对应到上表。上表未覆盖的调用点不能跳过，先补规则。若 flatten 路径上还有其他造 op 的位置，
按规则 8 处理并记录。其余生产 prefix pass 不属于 P2 范围，覆盖检查使用 §3.1 的 `align-bare` 产物。

**风险。**

- **成本：** 标注不增加 op。原始 ingest 约 1,192 万个 op 从无 ID 变为有 ID，预期增长是整数池每 op 一个 `uint32_t`（约 48 MB）、
  JSON 每 op 约 25 字节（约 300 MB），二者都是按字段宽度的估算，未实测。规则 5–7 的新树节点数和 lowering/flatten 的 CPU 开销未知，须实测。
  **时间预算放宽：** ingest→hier-flatten 连续墙钟从 F18 的 ≤75 s 放宽到 **≤150 s**（三轮 formal 中位数；F19 基线为 70.281 s）。
- **下游语义：** F09 的规则是“有提示按提示，无提示按 MFFC”。全部标注后“无提示”几乎不再出现，可能改变 node 构建。
  实施时须核查 SemanticId 的所有消费方；若 F18 后下游尚未使用 SemanticTree，则记录为后续阶段的约束，否则须先解决。
- **语义中性：** 标注不能改变电路。

**测试。**

- `tests/ingest/test_firrtl_semantic_tree.cpp` 增加全覆盖断言，并逐条覆盖规则 2–8：connect、when 分支、复位、memory 读写、共享 guard、效果、实例边界。
- `tests/transform/test_comb_loop_elim_pass.cpp` 增加规则 10：false-loop 拆分后所有 op 保留有效且相关的 SemanticId。
- 增加 `smem` + `read mport` 定向用例：断言 memory 与 mport 是模块下的同级 `Declaration`；storage `kRegister`
  归 memory 数据叶子，读口展开 op 和地址 `pipeline()` 归 mport 叶子；聚合数据逐叶检查；补充声明不得新增普通 value/op。
  flatten 两个实例后检查两组完整实例路径不同，并验证 store→load 后关联不丢失。
- 同一 guard 被两个 driver 使用时，归专门节点而不是其中任何一个。
- 混合 FIRRTL/SV 用例验证规则 9。
- `make test_f19_semantic_json`、ASAN 目标和 v4 往返继续通过。

**退出条件。**

1. 香山 ingest 和 `align-bare` flatten checkpoint 中**无 SemanticId 的 op 为 0**（`make f20_semantic_coverage` 按 kind 统计）。
2. 所有 SemanticId 有效且可解析到 K 或已知生成类别；CHIRRTL storage、端口及 `pipeline()` 的归属满足规则 5。
3. **拓扑不变：** op 总数和按 kind 计数、operand/result 拓扑与 P1 后的 checkpoint 一致，只有来源列表和树节点变化。原始 ingest 的 op 总数应仍为 34,187,631。
4. 全量 store→load→store 字节一致。
5. ingest→hier-flatten 连续墙钟三轮 formal 中位数 **≤ 150 s**。同时分别报告整数池大小、树节点数、checkpoint 体积和峰值 RSS，并更新 F19 基线的引用。
6. `make test_wolvrix` 相对 F19 无新增失败。

**本次实施复核（2026-11-05）：**
- `make test_f19_semantic_json` 6/6、ASAN 3/3、`test_transform_comb_loop_elim`、`test_f19_python_json` 通过；
  `make test_wolvrix` 维持 F19 的 77/84，七项均为既有旧 node/origin 测试，无新增失败。
- 全量 ingest 共 34,185,949 个范围内 op，缺失 0；另有 1,682 个无 SemanticTree 的 SV op，按规则 9 在 ingest 跳过，
  合计仍为基线的 34,187,631 个 op。`align-bare` flatten 共 34,215,668 个 op，缺失 0。
- Module 完整实例路径重复数 0；2,414 个声明寄存器符号不匹配数 0。ingest 与 flatten 的 store→load→store
  字节及 SHA-256 均一致，分别为 `77f091807d2d22869cefa5244a3158f1bfcfee15b1eeb81c8a6b01811dabaf59` 和
  `c49b10b5a41a4cfdd286127fb089f0157fe264494c165ecc3788d5f5e8a6dffd`。
- 单次 ingest→hier-flatten 为 123.04 s，低于 150 s 提案门槛；未执行三轮 formal，不能记作中位数验收。

**P2 性能修正（2026-11-05，已完成）：**
- SemanticId 的对外内容、顺序和 JSON 格式不变。单 ID 及不足 64 项的列表直接追加；64 项及以上列表按内容驻留，
  热缓存最多 4096 项，淘汰缓存入口不影响任何 op/value 已保存的 range。setter、compact、clone 和 JSON load 共用该存储路径。
- block remap 改为线性映射，不再逐项 `std::find`；目标子树按块检查一次，整数池按实际写入量几何增长，
  不按未去重总量预留。当时的整环并集实现使用哈希集合去重并保留首次出现顺序；现已被规则 10 的逐来源继承取代。
- 回归覆盖 300 项分组来源、fragment 映射及位段覆盖、相同长列表共享、5000 组列表缓存淘汰、单 ID 别名扩容和 64 项列表 JSON 往返；
  `semantic_stats` 同时报告逻辑 ID、实际池 ID 和驻留列表数，池大小只作性能观测，不作为 load 等价门禁。
- 初版对所有多 ID 列表驻留曾使生产三轮 formal 中位数退化到 94.50 s；8 项阈值将 op-loop 从约 201 s 降至约 108 s，
  但仍未达到优化前的 77.27 s 单次生产结果，因此最终采用 64 项阈值并继续验收，不能把中间版本视为性能通过。
- 随后在当前机器状态下复测同一优化前原生库，生产总墙钟为 93.09 s、flatten 为 30.63 s、峰值 RSS 为 44,105,080 KiB；
  64 项版本分别为 90.95 s、27.42 s、42,993,308 KiB。早先 77.27 s 与这些近期结果不属于同一机器状态，
  不能直接混合作为加速比依据。最终三轮生产 formal 为 85.896/89.226/97.425 s，中位数 89.226 s；
  flatten 为 24.962/28.417/36.663 s，中位数 28.417 s，峰值 RSS 中位数为 43,317,104 KiB。
  轮次波动较大，以上数字只用于同机对照，不宣称恢复到早先 70–77 s 水平。
- 最终 `align-bare` 的 ingest/flatten/连续墙钟为 52.283/53.345/105.628 s；优化前同口径为 55.271/73.055/128.327 s，
  连续墙钟下降 17.7%，flatten 接近 F19 bare 的 51.111 s。op-loop 从 398.709 s 降至 260.824 s。
  flatten 的逻辑 ID 仍为 104,797,236，实际池 ID 为 56,714,040，驻留列表 19 个；峰值 RSS 从 55,392,704 KiB
  降至 52,396,516 KiB。ingest 与 flatten checkpoint 的字节数和 SHA-256 均与优化前一致。
- 最终定向测试、ASAN 3/3 和 Python JSON 往返通过；完整 CTest 仍为 77/84，失败名单与 F19 基线一致，无新增失败。
- 最终全量 flatten 的 store→load→store 返回 `equal=true`，11,187,261,802 字节及 SHA-256 完全一致；
  原图与重载图的逻辑 ID 均为 104,797,236，Module 路径重复数及 2,414 个声明寄存器符号不匹配数均为 0。

P1、P2 之前产生的 checkpoint（含 `F19/identity`、`F19/size-experiment`）路径和归属都是旧语义，不能用于 Node 对齐，
只保留 §2 的计数用途。

### 3.1 GrhSIM 端：`align-bare`

```text
read_sources(pipeline="ingest", <F19 同一 manifest>)
  → hier-flatten（保存 flatten.json）
  → comb-loop-elim(fail_on_true_loop=True，保存 post-elim.json）
```

除 flatten 后的消环外，不运行其他 prefix pass；ingest 内不再提前执行 `comb-loop-elim`。生产 pipeline 本来就是
`hier-flatten → comb-loop-elim`，本次只是移除提前消环并显式保留真实环失败语义。移除的其他 prefix pass 如下：

| pass | 处置依据 |
| --- | --- |
| `mux-tree-fold`（两次） | 把 mux 树/逐元素写译码折回动态数组访问，GSIM Init 无对应 |
| `register-write-normalize` | 改写寄存器写结构，且带 `2state` 语义 |
| `memory-read-retime` | 改写读口时序结构 |
| `latch-transparent-read` | 改写 latch 读 |
| `xmr-resolve` | 本设计上预期无作用，不是对齐变量：F19 ingest checkpoint 中 `kXMR*` 为 0；该 op 只来自 SV 层次引用，FIRRTL lowering 不生成。若出现 XMR op，flatten 会直接报错（`hier_flatten.cpp:2317`），G0 同时断言 ingest 后 `kXMR*` 为 0 |
| `blackbox-guard` | 可创建 stub；同一 checkpoint 中 `kBlackbox` 为 0，预期无作用 |
| `multidriven-guard` | 属检查类 pass，对齐不依赖；是否有改写未逐行审计，移除即可规避 |

若 flatten 因移除 pass 报错，只加回**最少**的 pass，并在报告中记录原因和影响。

本次后移前的 `undefined-address-bare/flatten.json` 属于“ingest 已提前消环、flatten 后未再消环”的旧阶段；
本次生成的 `post-elim.json` 才用于与 GSIM `splitArray` 后的结构比较。此前的状态、Node 和 DAG 数字继续作为旧阶段诊断，
不得与新 checkpoint 混作同一阶段验收。

**Probe 不是 XMR，不关闭也不能关闭。** `SimTop.fir` 的跨模块引用都是 FIRRTL Probe：111,089 个 `output Probe<UInt/SInt>` 端口和同样数量的
`define`（全部在模块顶层，其中 13,196 个为 `define x = probe(y)`，其余逐层转发），以及 13,196 个 `connect a, read(b)`；没有
RWProbe、force、input Probe、带颜色或聚合 Probe。两端都在前端解决，方式相同：GSIM 把 Probe 类型解析成普通整型端口，把
`define`/`read` 解析成普通 connect（`syntax.y:145–147,275,278–279`）；GrhSIM 把 `probe`/`read` 直接求值为操作数并按定义写驱动
（`lower.cpp:396,566`）。因此这些 Probe 转发链应在两端都表现为普通 Node/边，是 G2、G3 的现成校验项，须单独报告匹配率。

Layer 也不造成差异：GSIM 无条件展开 `layerblock`（`syntax.y:371`），GrhSIM 按启用列表选择；而本设计只有 `Verification`
（7,836 个）和 `Assert`（6,920 个）块，都已启用。

差异如实记录、不归一化：两端的 invalid/四态策略（ingest 为 `unknown`/`4state`）、`SimJTAG.v` 走 SV 而 GSIM 走 extmodule。

### 3.2 对齐键

```text
K = 实例路径 + "$" + 声明名 + "__DOT__" + 字段路径
```

- **GSIM：** 运行时加 `--sep-aggr=__DOT__`，名字直接与 GRH 符号同形。须先验证 Node 总数和各类型计数
  与默认分隔符基线（§2.1）逐项相等，避免分隔符改变结构。去掉 `$NEXT` 后，`REG_DST` 与 `REG_SRC` 归为同一寄存器。
- **GrhSIM：** K 由 SemanticId 的树路径得到：去掉顶层根，Module 节点依次以 `$` 连接为实例路径，再加声明和字段。
- **实例端口自然合并：** P1 之后，父图声明 `cpu` 的字段 `x`（路径 `top/cpu/x`）和子图副本 `cpu` 的声明 `x`（路径同为 `top/cpu/x`）得到同一个 K，
  对应 GSIM 的单个 Node `cpu$x`。K 按路径文本比较，不看节点 kind。两个 value 合并后留下哪些 SemanticId 须在 F20.1 确认。
- **生成类别：** GRH 的 guard、效果节点（规则 6、7）和 GSIM 的 `WHEN_COND_*`、`port__DOT__ADDR*`、`NODE_EXT` 不走名字匹配，按 §3.4 处理。
- **独立交叉校验：** 见 P1 退出条件 4，并在 G0 中对 `align-bare` 产物复查。
- **第二键：** FIRRTL 行号（GSIM `Node::lineno` 与 GRH SrcLoc），用于效果对象匹配和未匹配项诊断。

不用 NO00020 的 `normalize_name()` 作主键：它把分隔符折叠成 `_`，会掩盖结构差异和误配。可作为未匹配项的末级诊断。

### 3.3 GSIM 端采集

| 阶段 | 用途 |
| --- | --- |
| `Init` | **主比较点**：名字、Node、Node 边、未拆数组的树结构 |
| `InferAllWidth` | 宽度与符号（经 `splitArray` 后要映射回原名） |
| 首次 `RemoveDeadNodes` | 只报告：把两端死节点差异从主比较中分离（实测 9,631,690→6,012,371，与 F14 一致） |

阶段实测：Node 数在 Init 为 7,826,232，TopoSort 和 InferAllWidth 均为 9,631,690，即拆数组后净增约 180 万，
所以宽度数据必须经拆分映射才能回到 Init 的 K。**不要使用 `SplitArray` 阶段的 dump**：`collectGraphNodes` 此时还在读旧的
`allNodes`（`GraphDumper.cpp:13–22`），实测 Node 数仍为 7,826,232 且含 246,037 个 `DEAD_NODE`，看不到新拆出的节点，
到 TopoSort 建立 `sortedSuper` 后才恢复正确。stats 采集到首次 `RemoveDeadNodes` 实测墙钟 8 分 9 秒、峰值 RSS 约 43.6 GiB。

**现有 dump 的缺口，须打补丁导出：**

- Node 的宽度、符号、维度、行号（JSON 的 Node 记录目前只有 `name/type/super`）；
- `resetTree`、`resetCond`、`resetVal`、`memTree`、`effectClock` 树（目前只导出 `assignTree`）；
- `g->memory` 中的 `NODE_MEMORY`（深度、延迟、`extraInfo`）及其端口成员。

F14 记录本机缺 `gmp.h` 无法重建 GSIM，本次复查仍未找到，须先解决（§6）。补丁只增加导出字段，并用 Stats 计数对比确认不改变图。

**活 ENode 口径：** `assignTree` + 真实 `resetTree`（含其 `resetCond`、`resetVal` 子树）+ `effectClock`。
排除写口遗留的 `memTree` 和无复位寄存器的假复位。读口的 `memTree` 已在 AST2Graph 中转入 `assignTree`，不重复计算。
活/遗留两部分都要报告，并与 §2.1 的总数闭合。

### 3.4 实体对应

| GSIM | GRH | 说明 |
| --- | --- | --- |
| Node（叶子） | 一个 K 下的 value/op 组 | 由 SemanticId 路径确定 |
| 实例端口 Node | 合并后的端口 value，及其 connect 的 `kAssign` | 只有引用叶子的树对应纯 `kAssign` |
| `NODE_REG_SRC`/`DST` | `kRegister` + 读写口 | 一个寄存器一组 |
| `NODE_MEMORY`（`g->memory`） | 带 `firrtl.memory` 的 `kRegister` | 使用规则 5 补充的同级 memory `Declaration` 路径，按数据叶子一对一，比较深度、宽度和读写延迟 |
| `READER/WRITER/READWRITER` | 独立 mport `Declaration` 的端口叶子组（规则 5） | 通过 storage/`regSymbol` 关联 memory；比较存储、地址来源、使能来源和数据来源，**不比 op 数** |
| `port$$ADDR` 寄存器对 | 读延迟的 `pipeline()` 寄存器 | 按所属端口匹配，数量差异须解释 |
| `NODE_SPECIAL` | `kSystemTask` 组 | 按行号和类型匹配 |
| `NODE_EXT*` | `kDpicCall` 或规则 9 的 SV 展开组 | 按实例匹配；内部 op 不比 |
| `WHEN_COND_*` | guard 生成节点 | 不一一对应；条件函数签名单独比较，DAG 中作为条件生成节点处理，不得直接丢弃条件依赖 |
| ENode 运算 | Operation | 按联合分类表比较，不是 1:1 |
| 引用叶子 `OP_EMPTY` | operand、读口 | 读口计入“引用”类，不计入运算 |
| `OP_INDEX_INT`/`OP_INDEX` | `kSliceArray` | 静态索引也可能折叠进别的形式 |
| `OP_WHEN`/`OP_MUX` | `kMux` 及条件更新结构 | 完整赋值可规范化为 mux；缺省分支按 latch/invalid 处理；寄存器和 memory 写按写使能处理 |
| `OP_PAD`、`OP_CVT`、`OP_AS*` | `kConcat`、`kSliceStatic`、`kAssign` | GRH lowering 显式展开（`firrtl-combinational.md`） |

未决：`clockOptimize`、`invalidArrayOptimize` 对 Node 的影响，以及 24 个 `$$copy$$copySrc` 派生状态的生成原因，留待 F20.1 确定。
`writer2Reg` 的 depth=1 且非数据数组转换规则及 1,553 个实例已由 §3.6 实测闭合。

### 3.5 `when` 与条件更新语义（2026-11-05 补充）

- GSIM 为每个 `when` 建立 `WHEN_COND_<lineno>`（`NODE_OTHERS`），用 `whenTrace` 记录嵌套分支，并通过
  `growWhenTrace()` 形成 `OP_WHEN(cond, trueValue, falseValue)`。空分支表示该路径无更新，不是可以忽略的语法细节。
  源码显式 `mux` 使用 `OP_MUX`，与 `OP_WHEN` 区分。
- 完整双分支赋值，或赋值前已有默认值的组合逻辑，可规范化为 mux。组合节点缺省分支可能形成 latch/保持；
  显式 `invalid` 则按未初始化策略处理，不能与 latch 混为一类。寄存器及 memory 写按写使能处理，不按组合 latch 处理。
- `invalidArrayOptimize()` 只在数组等适用场景把空缺补成 `OP_INVALID`，不是所有节点的统一 `OP_WHEN → OP_MUX` 转换。
  后端 `instsWhen()` 也只在两个分支均有有效值等条件满足时转成 `instsMux()`。因此主比较仍使用 Init 图。
- 对齐键采用“**目标 K + 条件函数 + 数据来源 K**”。GSIM 遍历 `OP_WHEN` 到实际赋值叶子并记录路径条件；
  GrhSIM 分别读取普通信号的 `kMux(enable, data, previous)`、寄存器写使能和 memory 写使能/掩码。
  条件函数另行比较来源和规范化签名；不能按 `OP_WHEN`/`kMux` 个数一一匹配，也不能只收缩 `WHEN_COND`/guard 而不保留条件语义。

### 3.6 状态元件数量首次闭合（2026-11-05）

输入为最终 `optimized-final-bare/flatten.json` 和 GSIM `SimTop_0Init.json`。`NODE_REG_DST` 与对应 SRC 是同一状态实体，
不得重复计数。这里比较的是数量及生成类别，不比较 Init 尚未推断的宽度。

| 类别 | GrhSIM | GSIM | 判定 |
| --- | ---: | ---: | --- |
| 普通 FIRRTL 寄存器，按规范化名字 join | 195,155 | 195,155 | 精确匹配 |
| SV 实现中的状态 | 15 | 不由 `NODE_REG_SRC` 表达 | 外部实现单独处理，不计为缺失 FIRRTL 声明 |
| 零宽寄存器 | 0（被 elide） | 48 | 已知表示差异，不计入非零状态匹配 |
| depth=1 memory 转寄存器 | 1,553 个带 `firrtl.memory` 的 `kRegister` | 1,553 对 REG_SRC/DST | 转换类别匹配，不属于 `NODE_MEMORY` |
| 其余 memory storage | 3,324 | 3,324 个 `NODE_MEMORY` | 精确匹配 |
| 同步读地址 pipeline | 488（`memoryPipeline` 的一部分） | 488 个精确后缀 `$$ADDR` 的 REG_SRC | 按端口继续比较 |
| 同步读使能、数据等额外 pipeline | 976 | 没有同名 `$$ADDR` | GrhSIM 实现特有的额外状态，不能全并入 `$$ADDR` |
| memory collision token | 488 | 无直接 Init 状态 | 当前 lowering 额外生成，属实现错误待修正，不作为合法对齐基线 |
| memory clock history | 484 | 无直接 Init 状态 | 当前 lowering 额外生成，属实现错误待修正，不作为合法对齐基线 |
| `$$copy$$copySrc` 派生状态 | 未找到同名 `kRegister` | 24 | 单列生成类别，下一步定位生成原因，不归入普通寄存器 |

**实现分层修正：** GRH 写口的 enable 与 event 独立，同 regSymbol 写口按显式 `writerOrder` 升序应用，
同地址重叠位由较大值覆盖，ops 数组位置不参与优先级判定；
事件历史由 `grh-to-grhsim` 的 `kEdgeDetect` 在后端建立，不在 FIRRTL lowering 生成 `kRegister`。
修复前 `clockPulse()` 在 GRH 层制造 clockHistory，后续 memory 读路径又制造 collision token 和冲突 mux，
既违反分层，也把本应由写口优先级决定的同址写结果改成 `invalid`。该 lowering 已删除；
`read-under-write=undefined` 固定采用 old 路径并逐 memory 发出 warning。下面的 484+488 只保留为修复前诊断数据，
不是合法对齐基线；修复后数量由本轮新 checkpoint 另行复核。

修复前数量闭式为：

```text
GrhSIM kRegister 202,483（修复前）
= 195,155 普通匹配 + 15 SV + 4,877 memory storage
  + 1,464 memoryPipeline + 484 clockHistory + 488 collision

GSIM REG_SRC 197,268
= 195,155 普通匹配 + 48 零宽 + 1,553 depth=1 转换
  + 488 $$ADDR + 24 copy 派生状态
```

其中：

- GrhSIM 的 `memoryPipeline = 1,464 = 3 × 488`，包含地址、使能和数据等寄存器；
  GSIM 的 `$$ADDR` 只表示地址寄存器，不能用全部 1,464 与 `$$ADDR` 直接比较。
- GrhSIM 的 depth=1 memory 共 1,569 个，其中 1,553 个被 GSIM 转成 REG_SRC/DST，
  其余 16 个仍保留为 `NODE_MEMORY`。memory storage 因而闭合为 `4,877 = 3,324 + 1,553`。
- `NODE_REG_DST` 不增加状态数量。`NODE_READER/WRITER/READWRITER` 是端口，不是额外 storage。

结论：**修复前状态元件的数量可按类别解释，但原始 `kRegister` 总数与 `NODE_REG_SRC` 总数没有直接可比性。**
下一步先复核已匹配普通寄存器的 K，再逐端口核对 `$$ADDR` 与 memory storage；
24 个 copy 派生状态须先定位生成原因，不能计入普通声明对齐。

证据：`ptmp/firrtl-ingest/F20/state-analysis/` 下的
`grh-register-categories.json`、`grh-memory-depth-categories.json`、`ordinary-register-name-join.json`、
`gsim-init-generated-reg-names.json`、`gsim-only-register-breakdown.json`，以及
`gsim-build/default-xiangshan/model/SimTop_0Init.json`。

### 3.7 memory lowering 修复后复核（2026-11-06，old 方案，已被 §3.8 取代）

输入为当前实现生成的 `writer-order-bare-v2/flatten.json`，native 快照为 `writer-order-native-v2`；
只经过 ingest→hier-flatten，不进入 GrhSIM 后半段。统计器同时复核旧 `optimized-final-bare/flatten.json`，
采用与旧分析一致的原名精确比较，仅将 GSIM `$$` 映射为 GRH `__DOT__`，不折叠其他 `$` 或下划线。

| 类别 | 修复前 GRH | 修复后 GRH | GSIM | 结论 |
| --- | ---: | ---: | ---: | --- |
| 普通寄存器原名精确匹配 | 195,155 | 195,155 | 195,155 | 保持一致；GRH 另有 15 个 SV 状态 |
| memory storage | 4,877 | 4,877 | 3,324 NODE_MEMORY + 1,553 转换项 | 数量及全部 depth 分布不变 |
| memoryPipeline | 1,464 | 488 | 488 个 `$$ADDR` | 数量相同，但语义角色不同，见下文 |
| memory clock history | 484 | 0 | 无 | 错误辅助状态已删除 |
| memory collision token | 488 | 0 | 无 | 错误辅助状态已删除 |
| **kRegister 合计** | **202,483** | **200,535** | 197,268 REG_SRC | 减少 1,948，不能只比较原始总数 |

修复后的数量闭式为：

```text
GRH kRegister 200,535
= 195,155 普通匹配 + 15 SV + 4,877 memory storage + 488 读数据 pipeline

GSIM REG_SRC 197,268
= 195,155 普通匹配 + 48 零宽 + 1,553 depth=1 转换 + 488 $$ADDR + 24 copy 派生状态

GRH - GSIM = 3,267 = 15 SV + 3,324 NODE_MEMORY - 48 零宽 - 24 copy
```

本闭式只比较 `kRegister`。另有 410 个 `kLatch`，与修复前相同，不混入 GSIM `NODE_REG_SRC` 的数量比较。

`memoryPipeline` 剩余 488 个来自 old/undefined 路径的“请求时组合读，再延迟数据”。
删除的 976 个是旧 collision 处理中按读阶段保存地址和使能的寄存器；另外删除 484 个 clock history
和 488 个 collision token，合计 `976 + 484 + 488 = 1,948`。因此这里的 **488 与 GSIM `$$ADDR` 数量相同只是数值闭合，
不是地址寄存器的一一对应**。旧文档把 1,464 分为 488 地址和 976 其他 pipeline 的描述只属于修复前结构。
后续应按端口比较“地址延迟”和“读数据延迟”的角色，不得宣称这部分语义已完全对齐。

全部 446,481 个写口都有唯一、非负的显式 `writerOrder`，缺失、负数和同状态重复均为 0；
修复前同一统计器报告 448,429 个写口缺少该属性。写口数减少 1,948，与删除的状态一一对应。
F20 SemanticId 检查覆盖 34,199,688 个 op，缺失为 0，SV 图也在本轮具有 SemanticTree。
全输入共 879 个 `read-under-write=undefined` memory，均发出固定采用 old 的 warning，没有将其当作 lowering 错误。

单次计时为 ingest 62.280 s、hier-flatten 90.068 s、连续 152.348 s，峰值 RSS 39,216,684 KiB；
旧对应值为 52.283 s、53.345 s、105.628 s 和 44,156,080 KiB。初次实现曾让每个新状态扫描整张图，
导致 ingest 长时间无法完成；当前已改为每图一次初始化。以上仅为单次同机测量，不作为正式性能回归结论。

全量 store→load→store 返回 `equal=true`，原图与往返图均为 11,198,307,685 字节，SHA-256 均为
`212a4a4b57ad9baa9f2a96fdb1ad6255cea581baa3e950e7529379bcff0fdca7`。两轮的 SemanticTree
节点数 13,221,574、operation rows 34,199,688、SemanticIds 104,781,256 均一致；2,414 个声明寄存器
符号不匹配数为 0，Module 完整实例路径重复数为 0。memory、state 定向测试及 ASAN 3/3 通过；
GrhSIM 后半段按后续重构计划另行复核，不属于本次 bare 状态对齐的验证范围。

证据：`ptmp/firrtl-ingest/F20/writer-order-state/{baseline-stats.json,current-stats.json,coverage.txt}`、
`writer-order-state/roundtrip/roundtrip-identity.json`、
`writer-order-bare-v2/{timing.json,prefix-identity.json,flatten-graph-identity.json}` 和
`writer-order-bare-v2/benchmark.log`。

### 3.8 undefined 地址延迟与 GSIM `$$ADDR` 对齐（2026-11-06）

§3.7 的 undefined→old 方案虽合法，但与 GSIM 在同址冲突时选择不同。当前实现改为：显式 old 仍延迟读数据，
显式 new 仍延迟地址和 enable；**undefined 只延迟地址，再组合读当前存储**，不再生成独立 enable pipeline，
并保留原始 `firrtl.readUnderWrite="undefined"` 属性。这样选择 new-value 碰撞行为；禁用读和 OOB 读不保证
沿用之前的 invalidPolicy 值，而由后端安全数组访问给出 don't-care 结果。写使能、写模式和写路径不变。

对 F20 原始 CHIRRTL 的词法复核发现 224 个同步读端口声明（198 个 `read`、26 个 `rdwr`）全部有显式
`when` guard；guard 已体现在地址 wire 的驱动中。展开后的 488 个 GSIM `$$ADDR` 对应 198 个
`NODE_READER` 和 290 个 `NODE_READWRITER`，所以省略的是重复的读有效状态，不是假定源端口没有使能。

输入为 `undefined-address-bare/flatten.json`，native 快照为 `undefined-address-native`，仍只经过
ingest→hier-flatten。端口 join 使用 GRH pipeline 的 SemanticId、memory 路径和 GSIM 全名精确比较：

| 检查项 | 结果 |
| --- | ---: |
| GRH `firrtl.memoryPipeline` | 488 |
| 与 GSIM `$$ADDR` 全名精确匹配 | **488 / 488** |
| GRH 缺失语义端口名 / GSIM 缺失 / GSIM 多余 | 0 / 0 / 0 |
| NODE_READER / NODE_READWRITER | 198 / 290 |
| 地址宽度符合对应 memory depth | **488 / 488** |
| 地址 pipeline 总位数 | 4,977 bit |
| §3.7 读数据 pipeline 总位数 | 41,128 bit |
| 减少状态位数 | **36,151 bit** |

因此这 488 个状态不再只是数量闭合，而是**端口、生成角色和地址宽度均对齐**。没有另外 488 个 enable
状态。普通寄存器匹配、memory storage、写口和总状态数不变：普通匹配 195,155，memory storage 4,877，
`kRegister` 合计 200,535，446,481 个写口的 `writerOrder` 检查仍全部通过。数量闭式更新为：

```text
GRH kRegister 200,535
= 195,155 普通匹配 + 15 SV + 4,877 memory storage + 488 地址 pipeline

GRH - GSIM REG_SRC = 3,267
= 15 SV + 3,324 NODE_MEMORY - 48 零宽 - 24 copy 派生状态
```

`make test_firrtl_memory test_firrtl_state test_grh_to_grhsim` 全部通过；测试新增两拍 undefined 只生成
两个地址宽度状态的断言，并覆盖 new-value 冲突和未门控禁用读。完整 CTest 为 76/84；剩余 8 项是此前未
收敛的 provenance、sink schedule 和 `firrtl-node-pipeline` 问题，memory、state 和 CPU 后端均通过。
879 个 undefined memory 仍逐 memory 发出 warning，文本已改为 new-value 碰撞及未门控禁用/OOB 读。

本次只证明 bare GRH 的结构和端口角色对齐，不把无效/OOB 的具体输出值视为对齐目标，也未宣称 GrhSIM
后半段已与 GSIM 动态等价。15 个 SV 状态、48 个零宽项和 24 个 copy 派生状态仍按原类别单列；copy 的
生成原因尚未查清。

证据：`ptmp/firrtl-ingest/F20/undefined-address-state/{current-stats.json,port-join.json}`、
`undefined-address-port-join.py`、`undefined-address-bare/{timing.json,prefix-identity.json}`、
`undefined-address-tests.log` 和 `undefined-address-full-ctest.log`。

### 3.9 后置 comb-loop-elim 与 GSIM splitArray 对比（2026-11-06）

ingest 不再提前执行 `comb-loop-elim`，真实组合环及 `firrtl.pendingCombLoopCheck` 保留到 `hier-flatten` 后。
生产 pipeline 继续保持 `hier-flatten → comb-loop-elim`，并显式设置 `fail_on_true_loop=True`，避免真实环降级为 warning。
F20 `align-bare` 同时保存 `flatten.json` 和 `post-elim.json`，后者才是本节输入。定向测试覆盖 flatten 后真实环失败、
两个 false loop 修复及并行身份；完整 CTest 为 **76/84**，与修改前相同，仍有既有 8 项 provenance/sink/node-pipeline 失败。

GSIM 使用已有二进制依次执行 `splitArray`、`detectLoop`、`topoSort`。日志为主循环拆 856 个数组、可选数组拆 233,875 个，
`NO Loop!`。`TopoSort` 含 9,631,690 个 Node 和 14,466,797 条 `prev/next` 边。采用 `TopoSort` 而不是 `SplitArray`
导出，因为后者仍读旧 `allNodes`，不能完整表示新拆节点。拆分成员按原 Node ID 和数组形状 coarsen 到原始 K；
2,051,495 个新拆节点全部归入可映射、ambiguous 和未解析类别，其中 110,334 个后两类不强行匹配。
共同普通组合候选为 **7,242,474**，覆盖旧候选 7,253,776 的 99.84%。

`post-elim.json` 含 34,365,358 个 op，SemanticId 缺失为 0。原始 DAG 和 loop-only 诊断归一化结果如下。
归一化只剔除已归因的 loop-only 差异，不是删除生产边，也不是 G3 验收。

| 指标 | 原始投影 | 剔除 loop-only 差异后的诊断口径 |
| --- | ---: | ---: |
| GSIM 边 | 11,063,175 | 不变 |
| GRH 边 | 13,641,883 | 11,080,122 |
| 共同边 | 11,060,347 | 不变 |
| GSIM 独有 | 2,828 | 不变 |
| GRH 独有 | 2,581,536 | 19,775 |
| 精确率 | **81.0764%** | **99.8215%** |
| 召回率 | **99.9744%** | **99.9744%** |

2,561,761 条多余边（99.24%）来自 loop 的 SemanticId 并集及其下游传播；非 loop 单 ID op 直接见证为 19,707 条，
其余 68 条未直接归因。loop 涉及 10,611 个组、1,130,705 个多 ID op，最大组为 815。差异高度集中在浮点除法器、
`vsMergeBuffer`、向量归约和其他矩阵结构。只删除多 ID op 本身产生的边并不够，后续单 ID `kAssign` 也会传播整组来源。

GSIM 独有的 2,828 条边中，530 条源 SemanticId 没有生产 op，2,298 条源有 op 但被其他结构绕过；后者尚未完全分类。
因此，**原始 G3 不通过，诊断口径显示的是较强的条件对齐，而不是已经证明两边消环后的图等价。** 下一步应优先给
loop split 增加逐 fragment 的精确归属或 range-aware 投影，再处理非 loop 边界和缺失边；暂不在此阶段比较表达式内容。

证据：`post-elim-bare/{flatten.json,post-elim.json,timing.json,prefix-identity.json,semantic-coverage.txt}`、
`post-elim-gsim/{SimTop_1TopoSort.json,SimTop_1TopoSort_Stats.json,split-map-stats.json}`、
`post-elim-dag/{dag-report.json,edge-attribution.json,missing-source-ops.json}` 和
`post-elim-full-ctest-2.log`。本阶段计时与其他验证重叠，只用于流程诊断，不作为正式性能结论。

### 3.10 显式 splitArray/fragment 映射与逐来源消环（2026-11-06）

GSIM 新增 `--dump-split-array-map=PATH`，直接导出 `splitArrayMap` 的父 Node、成员序号和成员 Node，不再从名称后缀猜测。
完整导出含 246,037 个父 Node、2,051,495 个成员；按 Node ID 对照 Init/TopoSort 后全部命中，名称不一致和未解析均为 0。
其中 104 个重名名称对应 208 个不同父节点的成员；旧 dump 的边只有名称，DAG 比较单独剔除这 208 个节点涉及的 352 条边，
其余 2,051,287 个成员按 ID 还原。`splitArray`/`splitOptionalArray` 数量仍为 856/233,875，与旧运行一致。

GRH `comb-loop-elim` 不再给新 op 盖整个 SCC 的 SemanticId 并集：fragment 继承原 value 归属，克隆 op 继承原 op 归属，
辅助 slice/concat 继承被视图化 value 的归属。`fragment-map-path` 导出的 ID 使用与 StoreJson 相同的图枚举顺序；
后续图变换后须重新导出。完整导出共 1,091,832 条 fragment、36,767 个原 value/op；全量校验的来源标注、fragment 标注、
位宽、位段覆盖和缺失实体错误均为 0。454 个 false-loop 仍全部修复，拆分计数不变，消环耗时为 43.810 s（旧值 42.751 s）。
post-elim op 数仍为 34,365,358，SemanticId 缺失为 0；SemanticId 总数从 185,257,660 降为 43,641,632。
序列化 ID 修正前后图 SHA-256 均为 `7bf377787096882f154f3f9dd70d81482d2a8498cf184c6515a482e76a38e998`，因此 DAG 结果复用。

| 指标 | §3.9 原始投影 | 显式映射与逐来源投影 |
| --- | ---: | ---: |
| GSIM 边 | 11,063,175 | 11,062,228 |
| GRH 边 | 13,641,883 | 11,080,118 |
| 共同边 | 11,060,347 | 11,059,400 |
| GSIM 独有 | 2,828 | 2,828 |
| GRH 独有 | 2,581,536 | 20,718 |
| 精确率 | **81.0764%** | **99.8130%** |
| 召回率 | **99.9744%** | **99.9744%** |

两端出度 p50/p90/p99 均为 1/1/7，入度均为 1/2/3。loop-only 差异降为 **0**；剩余 GRH 独有边中 20,689 条来自非 loop 单 ID op，
29 条未直接归因，GSIM 独有的 2,828 条仍需按 §3.9 的类别继续核查。G3 的精确率、召回率和 p99 偏差门槛已通过，
但不能据此宣称全部结构差异已解释或完整 GrhSIM 后端等价。投影组配对次数从 53,024,488,651 降为 30,819,171，
最大 op 组从 815 降为 1，guard 收缩后的残余 SCC 为 0。

定向消环回归覆盖逐组来源、位段覆盖、fragment JSON 和带 tombstone 的 StoreJson 往返，均通过；相关 ingest/memory 测试通过。
完整 CTest 仍为 **76/84**，失败仍是 §3.9 的既有 8 项。证据：`split-array-explicit/`、`post-elim-explicit-bare/`、
`post-elim-explicit-dag/`、`fragment-map-full-ctest.log`、`fragment-map-tombstone-test-3.log`。

### 3.11 非 loop 单 ID 多余边的闭合归因（2026-11-06）

对 §3.10 剩余 20,689 条非 loop 单 ID 边，逐条联合检查 witness op、TopoSort `prev/next` 可达性和 Init `prev/next` 可达性。
下表互斥且合计闭合。`Topo 可达` 包括路径长度 2/3/4/5/6/>6，分别为 5,983/2,298/674/209/130/3 条；
`仅 Init 可达` 包括 Init 直达 1,369 条和两跳 3 条。clock 分类采用大小写不敏感名称匹配，共 3,690 条。

| witness kind | Topo 可达 | clock alias | memory 专用边界 | 仅 Init 可达 | Init 也不可达 | 合计 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `kAssign` | 2,068 | 3,690 | 0 | 1,108 | 1,603 | 8,469 |
| `kAssign+kSliceStatic` | 304 | 0 | 0 | 0 | 0 | 304 |
| `kConcat` | 292 | 0 | 0 | 188 | 166 | 646 |
| `kConcat+kLt` | 0 | 0 | 545 | 0 | 0 | 545 |
| `kConcat+kRegisterReadArrayPort` | 0 | 0 | 24 | 0 | 0 | 24 |
| `kLt+kRegisterReadArrayPort` | 0 | 0 | 1,587 | 0 | 0 | 1,587 |
| `kLt+kSliceArray` | 0 | 0 | 1,707 | 0 | 0 | 1,707 |
| `kMux` | 707 | 0 | 0 | 0 | 125 | 832 |
| `kSliceArray` | 4,787 | 0 | 0 | 76 | 436 | 5,299 |
| `kSliceStatic` | 1,139 | 0 | 0 | 0 | 137 | 1,276 |
| **合计** | **9,297** | **3,690** | **3,863** | **1,372** | **2,467** | **20,689** |

各类含义如下。

1. **Topo 可达不是缺边，而是直达边与多跳边不同。** 例如浮点 `bits(cat(T10,0),55,41)` 在 GRH 被归约为 `bits(T10,54,40)`，
   GSIM 保留 `_T_10 → _T_11 → nxt_pre → target`；`new_vec` 和端口字段也有 source→中间节点→target 的路径。
   这些差异应做 alias/路径归一化，不应删除生产依赖。
2. **clock alias。** GSIM `clockOptimize()` 把中间 clock 重写为实际输入时钟，普通 DAG 不再保留逐级转发。
   GRH 的 `kAssign` 投影仍有这些边，应独立归一化，不能按组合数据流差异处理。
3. **memory 专用边界共 3,863 条。** `kLt` 的 3,839 条全部来自 `inBounds()`（`lower.cpp:820`），另 24 条是同类读口数据依赖。
   GRH 的 `kRegisterReadArrayPort` 还直接读取存储值；GSIM 的普通 `prev/next` 不表达这些存储/写侧关系。
   这些边应归 G1 memory 端口检查，不能按普通组合 DAG 缺边判错，也不能为对齐而删除越界保护。
4. **仅 Init 可达的 1,372 条是 SplitArray 后消失的直达依赖。** 数组拆分会改变最后连接和成员引用方式，需逐类检查 GSIM 的删除是否合理；
   当前结果不能作为“GSIM 必然正确”的证明。
5. **Init 也不可达的 2,467 条主要来自 last-connect/累计部分写和端口转发的中间形式。** 例如 `arFIFOMap` 先整体连接 `_arFIFOMap_WIRE`，
   随后逐元素覆盖；GRH 的部分写累积器仍带目标 K 的中间 op，GSIM `AST2Graph.cpp:963` 则清除被覆盖的旧赋值。
   `new_vec` 先清零再覆盖部分 bit、`IQSelUop/allSrcState` 的字段转发也属于这种形态差异。
   这表示两边的直接 K 投影不同，**不自动等于最终值不同，也不自动等于 GRH 实现正确**；需要 final-driver/last-connect
   感知投影及 G5 表达式签名复核。禁止只为消除数字而删生产边。

证据：`post-elim-explicit-dag/{nonloop-operation-examples.json,nonloop-edge-kinds.json,gsim-path-attribution.json,gsim-init-path-attribution.json}`。
上述计数与 `nonloop-operation-examples.json` 的 20,689 条 witness 集合逐类核对一致。29 条 guard-contracted-only 余量及 GSIM 独有的 2,828 条不在本节范围内。

### 3.12 删除 memory port 的重复 inBounds（2026-11-06）

§3.11 的 `kLt` 分析暴露出 `lower.cpp:820` 重复把地址越界比较并入 memory 读写 enable。本次仅删除该 memory 专用生成点，
不把其他动态状态索引比较或设计自身比较列为删除对象。memory 文档同步改为：enable 不再重复携带前端地址比较，
越界由后续状态读写路径处理。

全量结果：`kLt` 从 110,379 降为 99,593，删除 10,786 个；post-elim op 总数从 34,365,358 降为 34,307,850，减少 57,508。
454 个 false-loop 仍全部修复，fragment 的 1,091,832 条映射校验仍为全零错误，SemanticId 缺失仍为 0。
memory/ingest 定向测试通过，完整 CTest 仍是既有 8 项失败（76/84），无新增失败。

**DAG 没有因此改善，也不应要求它改善。** 修改前后 `grh-contracted-edges.u64` 完全逐字节一致，SHA-256 均为
`9fa5583e375ad5f00d0716109d9336ac77b264cb56ef6888270443c9f4277556`。精确率仍为 99.8130%，召回率仍为 99.9744%，
因为读口/写口本来就需要地址和存储数据依赖，删除比较 op 不等于删除真实依赖。

剩余 2,286 条 `kLt` witness 分解为 `kConcat+kLt` 545、`kLt+kRegisterReadArrayPort` 34、`kLt+kSliceArray` 1,707，
样例来自 `ibuffer.outputEntries`、debug halted status 等动态状态数组访问，不是刚删除的 memory port 比较。
另有 1,553 条纯 `kRegisterReadArrayPort` 的存储读数据依赖继续保留，不能借“删除重复保护”一并删除。
所以本次修正确认的是**多余比较 op 被移除**，不是 memory 边界语义或读写依赖被消除。

证据：`remove-memory-bounds-bare/{post-elim.json,post-elim-fragments.json,fragment-map-check.json,semantic-coverage.txt}`、
`remove-memory-bounds-dag/{dag-report.json,edge-attribution.json,nonloop-operation-examples.json}` 和
`remove-memory-bounds-{tests-2.log,full-ctest-2.log}`。

### 3.13 F20 验收结论（2026-11-06）

**F20 按 `ingest → hier-flatten → comb-loop-elim` 路线验收通过。** 本结论接受当前结构对齐程度，
不要求原始 op 数、原始状态总数或所有中间表达式形态一致，也不把 GrhSIM 后端动态等价、G4 表达式规模或 G5 表达式签名纳入本次验收。
接受依据如下。

| 层面 | 验收结果 |
| --- | --- |
| 普通 FIRRTL 寄存器 | 195,155 / 195,155，原名精确匹配 |
| memory storage | 4,877 = 3,324 NODE_MEMORY + 1,553 depth=1 转换项，depth 分布一致 |
| 同步读地址 pipeline | 488 / 488，端口角色、地址宽度与 `$$ADDR` 全部匹配 |
| 写口 | 446,481 个写口的 `writerOrder` 全部合法且唯一 |
| 普通组合候选 | 7,242,474，覆盖旧候选的 99.84% |
| SplitArray 成员 | 2,051,495 个全部按 ID 映射，未解析为 0 |
| false loop | 454 / 454 修复，SemanticId 缺失为 0 |
| Node DAG | 精确率 99.8130%，召回率 99.9744%，两端出度 p50/p90/p99 均为 1/1/7、入度均为 1/2/3 |

状态总数差 `200,535 - 197,268 = 3,267` 按 `15 SV + 3,324 NODE_MEMORY - 48 零宽 - 24 copy` 解释；
410 个 `kLatch` 单列。DAG 共同边为 11,059,400，GRH 独有 20,718 条，GSIM 独有 2,828 条，loop-only 差异为 0。
104 个重名名称涉及 208 个节点，DAG 比较仅排除其 352 条边，不再做名称猜测。

验收后仍需单列而非推翻本结论的事项：24 个 `$$copy$$copySrc` 派生状态原因未查清；20,718 + 2,828 条边差异需继续按类别复核；
last-connect/final-driver 和表达式签名属于后续 G4/G5 工作；GrhSIM 后端动态等价不在本次范围内。
memory 重复 `kLt` 已在 §3.12 删除，但真实地址与存储依赖保留，因此 DAG 数值不变化是预期结果，不是验收失败。

本次提交前的定向 memory、ingest、消环、JSON 往返和 fragment 校验均通过；完整 CTest 为 **76/84**，
失败仍是既有 8 项，未把完整测试集记为全绿。最终证据见 §3.10–§3.12 及本节所述 checkpoint。

## 4. 指标与判定

**门槛是实验前登记的提案。** 看到结果后如要修改，必须保留原值并写明理由；不能靠调门槛通过。

“已解释”是指：差异归入一个具名类别，附代码位置和最小复现样例，且类别计数闭合。只有说法没有计数不算解释。
无法归类的进入 `unexplained`，它才是门禁对象；所有比例报告原始值和解释后值两个口径。

### G0 实验有效性（全部必须满足）

- 输入 SHA-256 相同；`align-bare` 实际 pass 列表经日志确认；ingest 后 `kXMR*` op 为 0。
- **P1、P2 在 `align-bare` 产物上复查：** Module 路径唯一，符号交叉校验 100%，无 SemanticId 的 op 为 0。
- 闭合：各分类之和等于总数；GSIM 解析计数等于 Stats 计数；活/遗留 ENode 之和等于总数。
- 确定性：两端各跑两次，汇总指标逐字节一致（诊断顺序不比较）。
- `--sep-aggr` 与导出补丁不改变 Stats 计数。
- **负控：** 对小样例注入变异（删一个 connect、交换 mux 分支、改宽度、改名、去掉一个 memory 写口），每种变异都必须被对应指标检出。
  检不出就说明指标无效，整轮作废。
- **防空转：** 匹配对数非零，且达到预期量级。

### G1 状态与边界对象（硬门槛）

这些对象决定仿真状态空间，不能靠比例放行。

| 指标 | 门槛 |
| --- | ---: |
| 寄存器、memory 存储（来自 `g->memory`）、顶层端口、效果、外部边界：K 匹配，按位加权，双向 | ≥ 99.9% |
| 上述对象 `unexplained` | **0** |
| 已匹配对象的宽度/符号/shape 不一致 | **0** |
| memory 深度、读写延迟不一致 | **0** |
| memory 端口的存储、地址来源、使能来源、数据来源 | `unexplained` 为 0 |
| 效果对象（assert/printf/exit）计数 | 精确相等，或差值全部已解释 |
| `port$$ADDR` 与 `pipeline()` 寄存器 | 按端口闭合（验证 §2.3 的假设） |

### G2 Node 对应

| 指标 | 门槛 |
| --- | ---: |
| GSIM Node → GRH，按个数和按活 ENode 加权 | ≥ 99% |
| GRH 语义叶子 → GSIM，按个数和按 op 加权 | ≥ 99% |
| 双向 `unexplained` | ≤ 0.1% |
| 一对多/多对一的比例 | 只报告，超过 1% 须解释 |
| Probe 转发链匹配率 | 单独报告 |
| 实例端口匹配率 | 单独报告 |

预设的解释类别（须经实测核实）：零宽信号被 elide、GSIM 生成节点（`WHEN_COND_*`、`port$$ADDR`）、GRH 生成节点（guard、效果）、
GSIM 的 `clockOptimize`/`invalidArrayOptimize`/`writer2Reg`。

### G3 Node DAG（核心指标）

把 GRH op 图按 K 投影：一条 Node→Node 边表示 K₂ 的组内 op 读取了 K₁ 的值。P2 之后每个 op 都有归属，投影不再丢边。
GSIM 取 `prev/next`，不含 `depPrev/depNext`。这项指标不依赖两边 op 分解是否相同，且分图、激活传播都建立在这个 DAG 上，因此权重最高。

**生成节点收缩：** 比较前把两端的生成节点（GRH guard；GSIM `WHEN_COND_*`）收缩为透明，边直接连到它们的来源。
两边条件的组织方式不同（GRH 是决策图，GSIM 是每个 `when` 一个节点），不收缩会产生大量假差异。收缩前后的结果都报告。

| 指标 | 门槛 |
| --- | ---: |
| 已匹配 Node 之间的边（收缩后），精确率和召回率 | ≥ 99% |
| `unexplained` 边 | ≤ 0.5% |
| 入度/出度分布（p50/p90/p99/max） | 只报告，p99 偏差超过 20% 须解释 |
| 按模块的边差异 Top 20 | 逐个归类 |

### G4 表达式规模

SemanticId 覆盖已由 P2 和 G0 保证，这里不再设门槛。ENode 用活口径（§3.3）。op 分四个桶，**只有运算桶受比值门槛约束**：

| 桶 | 内容 | 处理 |
| --- | --- | --- |
| 运算 | 归属 Node 的算术、逻辑、比较、mux、切片、拼接 | 比值门槛 |
| 引用 | 读口、纯 `kAssign`（对应 GSIM 引用叶子） | 只报告 |
| memory 展开 | 规则 5 的端口逻辑 | 不比数量，按端口报告展开倍数；异常倍数须解释 |
| 生成 | guard、flatten 边界 | 只报告 |

| 指标 | 门槛 |
| --- | ---: |
| 运算桶联合分类（占任一端 ≥ 1% 的桶）规范化后比值 | 0.9–1.1 |
| 每 Node 规模比（GRH 运算 op / GSIM 活运算 ENode）p50 / p99 | 0.8–1.25 / ≤ 3 |
| 按模块差异 Top 20 | 逐个归类 |

分类复用 `compare_ir_shapes.py`，但分别报告原始比值和规范化比值。规范化规则（如 `pad` 展开为 concat）必须在看全量结果前根据 F20.1 小样例冻结。

### G5 表达式内容（签名）

对每个已匹配 Node，计算在 Node 边界截断的规范化结构签名。复用 `grhsim_paired_cone_diff.py` 的规范化思路
（PAD 透明、when/mux 链展平、常量按值、交换律排序、静态索引解码），但截断点改为 Node 边界。
Init 无宽度，签名不含中间宽度；宽度由 G1 和 `InferAllWidth` 阶段校验。memory 端口 Node 不计算签名，由 G1 的端口比较负责。

| 指标 | 门槛 |
| --- | ---: |
| 非 memory Node 签名匹配率，去重和按活 ENode 加权 | ≥ 95% |
| `unexplained` 不匹配，按活 ENode 加权 | ≤ 1% |
| 固定种子抽样 100 对不匹配并人工复核 | 分类错误 0 |
| 用独立实现的签名计算抽样复核匹配结果 | 一致 |

### 判定

| 结论 | 条件 | 后续 |
| --- | --- | --- |
| **充分对齐** | G0–G5 全部通过 | 以 GSIM 阶段为对照推进后续 pass 对比 |
| **有条件对齐** | G0–G3 通过；G4/G5 未达标，但差异都已解释且不改变 Node 划分 | 把差异登记为已知 lowering 差异，继续推进，同时标明受影响的比较项 |
| **不充分** | G0–G3 任一未通过，或 `unexplained` 超限 | 修 lowering/SemanticId 后重跑；G0 失败时先修工具 |

G3 通过而 G4/G5 未通过是可接受的中间状态：拓扑一致，只是表达式形态不同。反过来，G3 未通过时
不能用规模接近来放行，规模接近可能只是巧合。

## 5. 实施步骤

| 步骤 | 内容 | Make 入口 |
| --- | --- | --- |
| F20.P1 | SemanticTree 使用实例名（§3.0），通过退出条件后进入 P2 | 复用现有测试目标 |
| F20.P2 | 所有 op 标注 SemanticId（§3.0），通过退出条件后进入 F20.0 | `f20_semantic_coverage` |
| F20.0 | GSIM 导出补丁与构建；`align-bare` 入口 | `f20_grh_bare_flatten`；`f20_gsim_export` 待新增 |
| F20.1 | 小样例校准：用 F04–F06 现有 FIRRTL fixture 跑两端，定未决对应规则和规范化规则，跑负控 | 待新增 `test_f20_align` |
| F20.2 | **冻结**对应规则、规范化规则和门槛，先于全量比较提交 | — |
| F20.3 | 香山全量采集：两端各两次，流式降维成列式中间文件 | 待新增 `f20_align_collect` |
| F20.4 | 依次计算 G0→G5；前级未过时后级只作诊断 | 待新增 `f20_align_compare` |
| F20.5 | 差异归类，写 `F20-acceptance.md`，给出结论 | — |
| F20.6 | 仅报告：逐个加回 prefix pass，量化各 pass 对 G2–G5 的偏离，为生产 pipeline 决策提供依据 | 待新增 `f20_align_prefix_ablation` |

工具放在 `scripts/grhsim_f20_align.py`，尽量复用 `grhsim_gsim_module_compare.py`、`compare_ir_shapes.py`、
`grhsim_paired_cone_diff.py`。不能把整个 checkpoint 载入 Python：F19 精简版仅 C++ 加载就要 175 s，
应流式读取。证据放在 `ptmp/firrtl-ingest/F20/`，不提交大文件。

顺序：P1 → P2 → F20.0 + F20.1 + G1。G1 成本最低，又能最早暴露对应规则的问题。

## 6. 开放决策

1. **GSIM 重建：** 导出补丁需要 `gmp.h`。可选安装 `libgmp-dev`，或使用仓库中 `flake.nix` 的环境。
2. **门槛确认：** §4 的数值需要在 F20.2 冻结前确认。
3. **prefix 与生产的关系：** 如果只有无 prefix 的图能对齐，生产 prefix 是保留、后移还是取消，
   由 F20.6 的数据另行决定，不在 F20 内改动。
4. **节点 kind 命名：** P1 后非根 `module` 节点的 `name` 实际是实例名。本计划保留 `module` kind 以维持 v4 格式不变；
   是否改名（会影响 JSON 规范和 loader）待确认，不影响 F20 的对齐键。

## 7. 未测量

- P1、P2 尚未实施，§3.0 的退出条件均未验证；P2 的实际成本未知。
- `align-bare` 尚未运行。§2 的 GrhSIM 数字来自 F19 checkpoint，不能作为 G1–G5 的预期值。
- 11,918,900 个无 ID op 的逐调用点来源未统计，§2.3 的来源列是根据代码的推断。
- `--sep-aggr=__DOT__` 的结构中性尚未验证。
- 带 `--dump-assign-tree` 的 Init JSON 大小和耗时未测。
- `OP_INFER_MEM`、3,591 个无 ENode Node、`writer2Reg` 的确切情况未确认。
- 定义计数与 GSIM 实例计数在多个 kind 上恰好相等的原因未解释。
- SemanticId 的下游消费方未核查（P2 风险）。
