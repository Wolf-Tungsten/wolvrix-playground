# F17：ingest→hier-flatten 的三项结构性提速方案

日期：2026-11-03；状态更新：2026-11-04。F17.1 首轮与 v2 的验证/测量是历史证据，
首轮热点 1/4 预算未达到。当前集成候选的 r4 回归、207 份 oracle 和 36 组分配基准已通过。
整机 `complete-r1` 曾因 bulk result 来源继承遗漏导致 flat JSON 失败；r5 已修复，
`complete-r2` 的 ingest/flatten 完整 JSON、诊断和配置身份均与 F16 一致。最终性能结果和
未达预算的项目见 §7 与 [F17.1 结果](F17.1-grh-storage-results.md)。

范围：只覆盖原始 `SimTop.fir` 到 hier-flatten 返回，包括 FIRRTL/mixed ingest、
八个前置 pass 和 hier-flatten。flatten 之后的 simplify、GrhSIM 和 emit 不在本文范围。
本文依据既有 F15/F16 测量、源码审计和一次输入 census 提出方案。
F17.1 的新增实测见 [实施结果](F17.1-grh-storage-results.md)；下文“预算”是设计目标，
与实际达到的收益区分记录。

三项按优先级排列：

| 编号 | 内容 | 地位 |
| --- | --- | --- |
| **F17.1** | GRH core 底层整体替换为单一 SoA 存储，取消 frozen/mutable 双布局 | **P0，性能基础**；F17.2 依赖它，F17.3 的构图成本也由它决定 |
| F17.2 | hier-flatten 由逐 op 重建改为 SoA 列块拼接 | P0，在 F17.1 之上实现 |
| F17.3 | 前端一次解析、一次分析的模块级流水 | P0，第 1–2 步与 F17.1 无依赖，可并行推进 |

## 1. 差距的性质

| 指标 | node 开启（F16 三轮中位数） | node 关闭（单轮） | GSIM parse+Init（F14） |
| --- | ---: | ---: | ---: |
| ingest | 136.207 s | 113.013 s | 5.213 + 71.278 s |
| 八个前置 pass | 49.775 s | 23.957 s | — |
| hier-flatten | 122.404 s | 68.411 s | （Init 内递归展开） |
| 连续墙钟 | **308.525 s** | **205.778 s** | **76.491 s** |
| 相对 GSIM | 4.03× | 2.69× | 1× |

F12–F16 已完成分配器策略、Operation 快照、字符串查找、node key 缓存和
并行 lowering 等局部修复，连续墙钟从 513.804 s 降到 308.525 s。剩余 perf
已无单一主导热点。F16 最终采样中，flatten 的 SymbolTable `try_emplace`、
`mi_new`、`_Hash_bytes`、memmove 和 `~Graph` 合计约 39% self CPU；ingest 的
memcmp、`mi_new`、`try_emplace` 和 `_Hash_bytes` 合计约 26%；前置 pass 的
`Graph::opKind` 单项 11.43%。这些成本平摊在每个 op、value、名字和属性上，
来源是 GRH 的存储形状：每个对象都是一组独立堆块，属性和来源是字符串，
访问还要做模式分派。不先换掉这一层，上层流程改造只能把同样的单位成本搬到别处。

GSIM 实现并不精巧：节点名用 `std::string`，表达式节点逐个 `new`，Init 单线程运行。
它更快的原因是工作量少：**每个模块只解析一次，然后由 `visitInst` 递归直接向同一张
flat graph 构图**（`reference/gsim/src/AST2Graph.cpp:820`），并且表达式是 `ENode`
树，不是每个 primitive 都带独立符号、SrcLoc 和 use-list 的 Operation/Value 对。
F16 基线的工作量是（不是当前集成候选的实现状态）：

```text
文本 → index（全 token 扫描）→ validate（串行 parse 全部模块，AST 丢弃）
     → resolve（parse 可达模块 + Semantics::analyze(true)）
     → lower（新建 Semantics，analyze() 再做一次）→ 模块图（mutable 布局）
     → 8 个前置 pass（逐图串行）→ freeze 10,040 个源图（重打包为 frozen 布局）
     → hier-flatten 逐 value/op 重建 top 图（mutable 布局）→ 删除源图
```

## 2. 新证据：香山 FIRRTL 几乎没有层次复用

本轮对冻结输入按行统计 `module/extmodule` 与 `inst ... of ...`
（结果在 `ptmp/firrtl-ingest/F17/instance-census.txt`）：

| 项目 | 数量 |
| --- | ---: |
| module/extmodule 定义 | 10,008 |
| inst 语句 | 10,271 |
| 被实例化不止一次的定义 | 22 |
| 超出“一定义一实例”的额外实例 | 264（2.6%） |

Chisel/firtool 已按参数和实例把模块唯一化，例如 `OthersEntry_282`、
`OthersEntry_283` 是不同定义。因此模块级 GRH 几乎不提供复用：约 97% 的
hier-flatten 工作就是把整份设计**完整复制一次**。ingest 图 40.95 GB JSON，
flat 图 37.92 GB JSON，也说明了这一点。按 definition 缓存展开计划的思路
（F16-remaining §3）在这种输入上几乎没有可摊销对象，只有让复制本身变便宜
（F17.1 的连续列）或不再逐 op 复制（F17.2 的块拼接）才有意义。

## 3. F17.1（P0，基础）：GRH core 底层整体替换为单一 SoA 存储

**目标：Graph 只有一种存储布局，全部为列式连续数组加图级 payload 池。构图、克隆、
析构和访问都不再按对象分配堆块或搬运字符串。公开语义、ID 契约和 JSON schema 不变。**

### 3.1 F16 基线布局（替换前）

`Graph` 同时持有 `std::optional<GraphView> view_` 和 `std::optional<GraphBuilder> builder_`
（`grh.hpp:951–952`），`frozen()` 即 `!builder_`。

| | mutable：`GraphBuilder` | frozen：`GraphView` |
| --- | --- | --- |
| 拓扑 | AoS：每个 `OperationData` 有 operands、operandUseIndices、results、attrs 四个 `std::vector`（`grh.hpp:577`） | SoA + CSR：`opOperandRanges_/operands_`、`opResultRanges_/results_`、`opAttrRanges_/opAttrs_` |
| use-list | `vector<vector<ValueUser>>`，每个 value 一个堆块（`grh.hpp:623`） | `valueUserRanges_` + 连续 `useList_` |
| shape | 每个 value 一个 `vector<int64_t>` | `valueShapeRanges_` + `valueShapeDims_` |
| ID | 稳定，删除留 tombstone | freeze 时按存活顺序压紧重编号（`grh.cpp:2274`） |
| 属性/来源 | **两种布局相同**：`AttrKV{std::string key; variant value}`，约 64 字节，长字符串另有堆块；`optional<SrcLoc>` 含 4 个 `std::string` | |
| 符号 | **两种布局相同**：Graph 级 `SymbolTable`（map 与 deque 各存一份文本，`grh.cpp:439–480`），加各自的 `symbolIndex_` | |

成本来源：

1. **freeze/thaw 是整图重建。** freeze 重新打包成 CSR；thaw（`ensureBuilder` → `fromView`，
   `grh.cpp:5182/809`）把 CSR 展开回每 op 四个 vector，并复制全部属性和 SrcLoc。
2. **每次访问都做模式分派。** `grh.cpp` 中有 31 处 `if (builder_)`、61 处 `view_` 引用；
   `Graph::opKind`（`grh.cpp:4242`）在前置 pass 中 self 占 11.43%。
3. **热路径都在最贵的布局中。** lowering（`lower.cpp` 中 `replaceAllUses/eraseOp/
   replaceOperand/eraseValue` 调用数为 0，纯追加）、前置 pass 和 flatten 的 top 图都在 mutable
   AoS 中构造。frozen 布局只是 flatten 的临时复制源。
4. **payload 由每个对象各自拥有。** 无论哪种布局，克隆、移动、析构都要逐个处理字符串。

双布局并没有隔离出稳定的外部依赖：`GraphBuilder`/`GraphView` 在 `core/grh.*` 之外只出现在
两个测试文件中；`freeze()` 在 13 个文件中共有 34 处引用，生产语义依赖只有 `hier_flatten`
（frozen 源图的 per-definition 缓存）和 `activity_schedule`（freeze 后按稠密 ID 建表）。

### 3.2 原始设计与最终实存布局

**原始设计草图：** 以下是实施前的目标示意，不是最终 C++ 字段声明。
其中曾计划打包 flags、将 use-list 的两个字段拆列，并省略切片的池指针；
最终实现采用下面列出的实际类型。

```text
value 列：symbol[] width[] flags[]（signed/type/domain/in/out/inout/alive 打包）
          def[] srcLoc[] shape[] users{offset,count,cap}[]
op 列：   kind[] symbol[] srcLoc[] alive[]
          operands{offset,count,cap}[] results{offset,count,cap}[] attrs{offset,count,cap}[]
边数组：  operandValues[] operandUseIndex[] resultValues[] useOps[] useOperandIndex[]
属性：    attrKey[] attrTag[] attrPayload[]（见 3.3）
payload 池：strings / int64s / doubles / bitWords / stringLists / shapeDims / srcLocs
```

**最终实存布局：** `Graph::store_` 是 `shared_ptr<GraphStore>`，构图和 compact 后始终访问
这一个后端。`GraphStore` 继承 `GraphPayload`，其实体列和拓扑池对应 `grh.hpp` 中的下列类型：

| 结构 | 实际内容 |
| --- | --- |
| `ValueColumns` | `width_ / isSigned_ / type_ / domain_` 为 `PagedColumn<T,256>`，普通构图用平坦 vector、块导入可保留共享页；`symbol_` 为 `vector<SymbolId>`；`isInput_ / isOutput_ / isInout_ / alive_` 各为 `vector<uint8_t>`；`shape_ / srcLoc_` 各为 `vector<RecordId>`；`definingOp_` 为 `vector<OperationId>` |
| `OperationColumns` | `kind_` 为 `PagedColumn<OperationKind,256>`，`symbol_ / srcLoc_ / alive_` 为普通固定字段列；`operands_ / results_` 为 `vector<PoolVector<ValueId>>`；`operandUseIndices_` 为 `vector<PoolVector<size_t>>`；`attrs_` 为 `vector<PoolVector<RecordId>>` |
| `GraphStore::valueUsers_` | `vector<PoolVector<ValueUser>>`，每个 value 一个 use-list 描述符，不在 `ValueColumns` 内 |
| `TopologyPools` | 主 `vector<ValueId> operands / results`、拥有接管 edge vector 的 `retainedEdges`、`vector<size_t> operandUseIndices`、`vector<ValueUser> users`、`vector<RecordId> attrs`，以及 `ShapePool shapes` |
| `GraphPayload` | `attrKeys_ / attrTags_ / attrPayloads_` 三列、`srcLocs_` record 表、按值类型分开的列表池，以及与符号表共享的 `StringPool` |

`ValueRow` / `OperationRow` 只是同一下标各列的引用集合，不是逐实体另存的对象。
flags 没有打包；`ValueType` 和 `LogicDomain` 的底层类型均为 uint8_t。
use-list 中的实际元素是 `ValueUser{OperationId operation; uint32_t operandIndex;}`，
没有拆成原草图的 `useOps[] / useOperandIndex[]`。

- **切片（slice）：** 可变长关系用 `PoolVector<T>` 描述，每个描述符实际保存
  `vector<T>* pool_` 和三个 `size_t`：`offset_ / size_ / capacity_`，64 位平台共 32 字节。
  描述符不拥有独立元素堆块，实际元素在对应的图级 vector 中。
  给切片追加时，如果切片位于数组尾部或还有剩余 capacity，原地写入；
  否则把切片搬到数组尾部并加倍 cap，旧位置成为垃圾。lowering、flatten 都是“建 op → 立即加
  operands”的常见模式。`operandUseIndices` 保存对应 value 的 use-list **局部下标**，
  配合末项换入的删除方式保持 O(1) 反向关系删除。
- **删除：** 置 alive=0，保留 tombstone；切片内容成为垃圾。与现有 mutable 语义一致。
- **`compact()`：** 回收全部垃圾，按存活顺序重编号 value/op，校验并排序端口，结果与现在
  F16 `freezeImpl` 的编号和顺序**完全一致**。公开 `freeze()` 保留为它的名字，契约不变。
  `frozen()` 改为“自上次 compact 以来未修改”，由 `compacted_` 标志记录；`hier_flatten` 的缓存依据
  不变。修改一张已 compact 的图不再需要 thaw，只是清除该标志。
- **访问：** 所有访问器直接读同一 GraphStore，没有 frozen/mutable 模式分派；部分固定类型列内部
  区分平坦 vector 与固定页目录。builder 时期需要的 alive 检查保留。
  `operations()`/`values()` 的 ID 列在创建时追加，删除时标记 tombstone；下一次枚举只过滤
  ID 列中的标记，不重扫实体列或创建另一份图布局。
- **ID：** 不改变现有契约。修改期间 ID 稳定，`freeze()`/`compact()` 重编号，`generation` 字段保持现状。
  稳定 ID 和以 ID 序列化的方案另议，不在 F17 范围内。

### 3.3 类型不固定的属性如何列式存储

每条属性是定长三元组，变长内容放入按类型分开的图级池：

```text
attrKeys_[]     uint32   内置 key 编号或 StringId
attrTags_[]     uint8    Bool | Int | Double | String | BoolList | IntList | DoubleList | StringList
attrPayloads_[] uint64   标量本身，或指向池的 {offset:u32, count:u32}
```

| `AttributeValue` 分支 | 存储位置 | payload |
| --- | --- | --- |
| `bool` / `int64_t` / `double` | 直接存在 payload | 值本身 |
| `std::string` | 字符串池：单一字节 arena，按内容去重 | `StringId` |
| `vector<int64_t>` | int64 池 | `{offset, count}` |
| `vector<double>` | double 池 | `{offset, count}` |
| `vector<bool>` | 按位打包的 uint64 池 | `{wordOffset, bitCount}` |
| `vector<string>` | `StringId` 列表池 | `{offset, count}` |

- **key：** `detail::kBuiltinAttributeKeys` 是含 82 个 key 的编译期有序文本表，包含
  `regSymbol`、`constValue`、`eventEdge` 和 `firrtl.node.*` 等。写入时二分查表，命中后用
  最高位置 1 的 uint32_t 编码，不进入字符串 hash。其它 key 用图级 StringPool 的普通
  StringId。并行 lowering 的 worker 使用各图独立的池，不需要池间锁。
- **顺序：** 现有规则要求每个 op 的属性按 key 文本字典序排列（`grh.cpp:2128`，node 属性依赖它）。
  插入时按 key 文本排序；内置 key 的字典序名次预先算好，JSON 输出顺序不变。
- **修改：** 覆盖标量就地改写；覆盖变长值时追加到池中并改指向，旧内容成为垃圾，由
  `compact()` 回收。增删 key 改变 op 的属性切片，规则同 3.2。
- **体积：** 每条属性约 13 字节，现在 `AttrKV` 约 64 字节，另加长字符串堆块。字符串池去重会把
  `regSymbol` 目标、`originModules` 路径、node key 和 SrcLoc 文件名等重复文本压成每图一份。
- **值类型不变：** 第一步不改变任何属性的值类型。例如 `constValue` 仍以 `"8'b…"` 文本存入字符串池
  （`lower.cpp:268`），保证 JSON 字节相同。改为真正的位向量属于语义变更，另行处理。
  按 op kind 为热点 key 建专用列也不在第一步做，只有 profile 证明通用布局仍不够时才考虑。

### 3.4 其它 payload

- **SrcLoc：** 图级 `SrcLocId` 表，file/origin/pass/note 进入字符串池。value/op 只存 4 字节 ID，
  0 表示无来源；lowerer 中同一语句产生的多个 op 共享同一个 ID。
- **shape：** 去重的 dims 池，value 存 `ShapeId`，0 表示标量。
- **符号表：** 与 GraphPayload 共用 StringPool 的同一份 arena 字节；StringPool 用
  `textById_`、整数 hash 索引 `idsByHash_` 和完整文本碰撞链 `hashNext_` 维护 StringId。
  SymbolTable 使用 `symbolsByStringId_` 数组登记 StringId → SymbolId，另有
  `vector<string_view> textById_` 按 SymbolId 借用同一份字节，不重复按文本建表。
  StringId 与 SymbolId 是不同命名空间：属性出现某段文本不会预留同名符号。
  GraphStore 的 `symbolIndex_` 再将已绑定的 SymbolId 映射到 `{实体种类,index}`。
  符号、名字碰撞规则、`_val_N` 内部名的生成和跳号规则都不变。临时名不入表另议，不在 F17 范围。

### 3.5 公开 API 的变化

- F16 的 `opAttrs()` 返回 `span<const AttrKV>`，共 64 处调用，属于暴露布局的借用接口。当前改为返回
  `AttrRange`，元素 `AttrRef` 提供 `key()`（string_view）和 `value()`（借用的 `AttrValueView`，
  分支为 bool/int64/double/string_view/span/bit-span/string-list 视图），逐处机械迁移。
- `opAttr(key)`、`opSrcLoc()`、`valueSrcLoc()` 仍返回拥有型 `optional`，按需构造。
  `setAttr` 仍接收拥有型 `AttributeValue`。`getOperation()`（278 处）保持拥有语义。
- `valueShape()`、`opOperands()`、`opResults()`、`valueUsers()` 继续返回 span，指向池或切片。
  失效规则统一为“图的任何修改或 compact 都使借用失效”，与现在 builder 的规则相同。

### 3.6 实施步骤

1. **S0 计数基线：** 在现有实现中加低开销计数（只在 profile 开关下启用）：每阶段堆分配次数、
   SymbolTable 插入数、属性条数/字节、SrcLoc 字节、freeze/thaw 次数。小 fixture 与整机各记录一次。
2. **S1 API 先行：** 引入 `AttrRange`/`AttrRef`/`AttrValueView`，先在现有 `AttrKV` 存储上实现，
   迁移 64 处调用。与存储替换解耦，单独回归。
3. **S2 新存储：** 实现 `GraphStore`、payload 池和 `compact()`。旧实现在过渡期保留为测试 oracle：
   同一操作序列在新旧实现上执行，逐字段比较全部访问器结果、compact/freeze 后的编号和 JSON。
4. **S3 切换并删除：** `Graph` 改用 `GraphStore`，删除 `GraphBuilder`/`GraphView`/`fromView`/
   `freezeImpl` 及 31 处模式分派。`hier_flatten`、`activity_schedule` 的 `frozen()`/`freeze()`
   用法按 3.2 的新定义核对。两个直接测试 builder/view 的测试改为测试 `GraphStore`。
5. **S4 测量：** 按 F16 的同一配置测一次 ingest→flatten，并与 S0 计数对照。

**预算：** 构图和克隆路径的堆分配摊还到每 op 近 0；ingest、前置 pass 和 flatten 中
`mi_new`、memmove、`_Hash_bytes`、`try_emplace`、`Graph::opKind`、`~Graph` 这几类 self CPU
合计降到 F16 的 1/4 以下；峰值 RSS 明显低于 F16 基线（node 关闭时 ingest 为 69.8 GB）。
墙钟收益在 S4 测量后登记，不预先承诺。

**验收：** ingest/flat 两个终点的完整 JSON SHA 与 F16 相同
（ingest `2335818f…1928`，flatten `1143a549…3d23c`）；JSON roundtrip 字节身份；
6,007 条诊断按序相同；现有 81 项 CTest、FIRRTL workflow、Python ingest 和 GrhSIM flow 全部通过。
新增 core 回归覆盖：
- 新旧存储对同一操作序列的逐字段差分；
- compact 编号、端口排序和 canonical 顺序与旧 freeze 一致；
- 非尾部切片追加触发搬迁，以及删除后的 use-list 一致性；
- 借用 span 在修改和 compact 后的失效边界；
- 每种 `AttributeValue` 分支的 store/load 文本和字节身份；属性按 key 字典序；
- 多图并行构造时 payload 池互不干扰。

### 3.7 当前实现状态（2026-11-04）

S0 的默认关闭逻辑计数已保留：符号插入、属性/SrcLoc 写入与字节、实体创建、compact
和 thaw。`WOLVRIX_GRH_PROFILE=1` 启用它们，Python benchmark 在各阶段读取累计值。
这些逻辑事件不等同于堆分配次数。新增默认关闭的 `WOLVRIX_MIMALLOC_STATS` 构建选项，
以分配器公开统计接口记录 native 真实分配数；单独诊断运行，不能混入正式计时。

S1 已将全部生产 operation 属性调用迁移至 `AttrRange` / `AttrRef` / `AttrValueView`。
`opAttrs()` 与 `opAttrRange()` 都返回借用视图，key/value 通过方法读取；字符串为
string_view，数字列表为 span，bool/string 列表为借用 range。序列化直接写这些视图，
clone 与 flatten 的属性导入使用 `setAttrView()`，无逐属性的拥有型中间副本。

S2/S3 的存储切换已实现：`GraphStore` 是唯一可变后端，`GraphBuilder`、`GraphView`、
`fromView`、`freezeImpl`、冻结镜像 capture 与 frozen/mutable 模式分派已删除。
value/op 标量列、图级可变切片、use-list backlink、属性 key/tag/payload 三列、
SrcLocId、去重 ShapeId 和共享字符串池均实际承接 mutation 与读取。
属性覆盖就地改 record，变长垃圾由 compact 回收。SymbolId reservation 与字符串
内容去重分离，payload 文本不会预留同名符号；compact 保留全部 symbol reservation。

`compact()` 在同一列布局中准备新的紧凑池并一次性提交，保持存活顺序、稠密 ID、
端口名字排序和 use-list canonical 顺序。修改 compact 后的图直接写原列，不再 thaw。
clone 直接借用列与 payload，按来源 ID 缓存 SrcLoc 导入。`getOperation()` 仍返回拥有字段、
连接列表和属性的快照。`getValue()` 复制固定字段、名字、shape 和 SrcLoc，但 `Value::users()`
首次调用仍从原 Graph 延迟读取；需要跨图修改或销毁保留 users 时，应提前读取并复制。
两类快照携带的实体 ID 都受 compact 重编号影响。图级 metadata 接口仍保留。

存活 ID 列的实现对 §3.2 原始设计作了一个明确取舍：创建时直接追加，删除标记 tombstone，
下一次枚举仅在 ID 列中过滤，避免每次删除都移动后续 ID 所造成的批量删除 O(n²)。
它不重扫实体列、不重建另一份布局；端口访问也不再复制到 Graph 缓存。

新增回归覆盖 legacy canonical golden、compact 前后精确 JSON、非尾部切片迁移、
use-list 增删、8 种属性、来源/shape 去重、同图/跨图属性复制、垃圾回收及并行图池隔离。
首轮快照曾通过 81/81、Python/workflow/model 回归、整机双终点 SHA、6,007 条按序诊断
和完整 ingest roundtrip；其正式单轮为 **283.678 s**、70.614 GiB，六类热点剩余 **48.60%**，
未达到 ≤25% 预算。v2 的独立构图/clone 36 组分配基准及 oracle 也有自己的历史快照。
这些结果只证明各自归档版本，不能转作当前源码或当前加载库的结果。

当前集成候选在单一 GraphStore 上加入了 F17.2 所需的共享所有权：value 的
width/isSigned/type/domain 和 operation kind 使用 256 行 PagedColumn；普通构图仍用平坦 vector，
完整目标页仅在来源选行物理连续、属于同一缓冲区时共享，不足页和非连续范围复制。
来源起点无需按 256 行对齐。目标写入共享页时复制该页；平坦来源之后写入可能复制整列。
symbol、shape、来源 record、端口/定义标记和属性 record 仍独立建立并重定位。
数值 PayloadPool 保留分段缓冲区，StringArena 保留字符页，StringId 列表按稠密映射重写；
没有将整张来源 GraphStore move 到目标。单次使用且可删除来源的拓扑接管见 §4、§7。

当前已限定 prefix 只提前 compact 安全来源，保留 top/positional 端口次序，并增加非序列化
source-freeze receipt，详见 §7。r4 已通过 **81/81 CTest、9 项 Python ingest、72 项 FIRRTL workflow、
5 项 GrhSIM flow 及模型执行、FIRRTL comb 模型执行**；当前源码也通过 207 份完整 oracle JSON
与 36 组独立分配基准。`complete-r1` 曾暴露块 result 发布遗漏旧 `addResult` 条件来源继承，
r5 已修复。最终 `complete-r2` ingest/flatten 两个终点均为 F16 的完整 SHA，6,007 条诊断、
metadata、source 指纹和 pipeline 全部一致。正式 fused perf 已完成，预算未达项目按实测登记。
分版本证据和待补项目见 [F17.1 实施结果](F17.1-grh-storage-results.md)。
实现与 API 约束见 [GRH 数据结构](../../wolvrix/docs/grh/grh-storage.md)。

## 4. F17.2（P0）：flatten 由“逐 op 重建”改为 SoA 列块拼接

**目标：hier-flatten 的成本从 O(op×(分配+hash+字符串)) 降到 O(op) 的整数重定位，并可以并行。
依赖 F17.1。**

F16 基线：对每个实例的每个 value 调用 `createValue`，受保护名字
执行 `makeHierName` 后 `internUniqueSymbol`；对每个 op 执行 `createOperation`、逐 operand
`addOperand`（同时维护 use-list backlink）、逐属性 `rewriteAttr`，复制 SrcLoc，并为每个 op
新建一份 `originModules` 的 `vector<string>{prefix}`。node 关闭时这些成本仍在。
flatten 开始时还要串行 freeze 10,040 个源图，结束时逐个析构源图（`~Graph` 占 self 4.22%）。

方案与当前实现边界：

1. **源图在合法 barrier 后并行 compact。** 全部模块发布并依次完成 §5 的跨图/局部链后，
   由局部链执行器在 retention metadata 发布后并行 `compactForFlatten()`，只处理非 top、
   至少被 instance 内联引用且全部 instance/blackbox 引用均有完整 named maps 的来源；
   top ports 和 positional ABI 保持原次序。不能在 lowering 刚完成时
   越过 xmr-resolve、multidriven 或 blackbox 边界。flatten 保留 source-freeze fallback：
   普通 ingest/第三方调用未 compact 的来源，仍仅在全部引用有完整 named port maps 时 freeze；
   positional 引用跳过，freeze 失败保留原 inline 诊断边界，不要求所有调用方使用新 prefix。
2. **DFS 事件与 run 区间预分配。** 按旧 DFS 遍历保存 value 进入、operation run、instance/DPI
   边界与退出事件，逐事件预留名字及实体区间。一个实例的 operation 可以有多个 run：
   来源 `P1、instance C、P2` 必须追加为 `P1 run、C 的 runs、P2 run`，不能把整个实例的
   op 强行放成一个连续块。每个 run 内的整数重定位使用确定范围，结果与 worker 完成顺序无关。
3. **列块拼接与所有权。** 固定类型列共享范围见 §3.7；数值 payload 和字符串页保留缓冲区，
   StringId、属性原型、SymbolId 和实体 ID 按目标域重定位。可独占消费的单次使用来源，在全部
   metadata 读取后把 operands/results 原缓冲区交给目标 retainedEdges，原位改写有效切片并删除源图。
   需要保留或多次使用的来源建立独立目标拓扑；没有整张 GraphStore 的无条件接管，来源图仍会析构，
   被目标持有的缓冲区继续存活。接管只限 `preserveFlattenedModules=false` 且无 blackbox 保留需求。
4. **端口合并。** 子图同类型端口 value 与父侧实参使用定向 union-find，保留原父侧代表；
   results/valueDef 先发布，所有端口等价确定后每条 operand 只按最终代表重定位一次，最后重建 use-list。
   type/shape view、output alias 和其它原边界 assign 仍按旧规则保留，不能任意合并定义身份。
5. **名字与来源。** 受保护符号的层次名、declared symbol 与碰撞规则仍按原算法生成，只对需要
   命名的对象执行；`originModules` 和 node qualification 在块内是同一实例前缀，按块计算一次后
   批量写入（借助 F17.1 字符串池，每块只存一份前缀字符串）。
6. **并行。** 多块属性先一次性分配目标 records/切片，再并行填写不相交范围；operand 最终映射
   使用同一个 pass 生命周期的 BlockExecutor。符号和池准备仍按确定顺序协调；
   use-list 在全部块就位后统一生成。异常退出也先补全已导入边的反向关系，不提供整批事务回滚。
7. **边界逻辑不变。** XMR、DPI 复用、generate groups、端口类型转换和既有诊断都在端口/边界上，
   数量少，仍走现有精细路径；只有块内部批量化。

**预算：** flatten 68.411 s（node 关）/ 122.404 s（node 开）→ **≤ 10 s**。

**验收：** flat 图完整 JSON SHA 与 F16 `1143a549…3d23c` 相同；有序诊断、declared symbols、
originModules、node qualification 和 SrcLoc 按原格式还原。补充回归覆盖单实例接管、多实例复制、
嵌套 24 层、名字碰撞、XMR 跨块、端口宽度/类型转换，以及并行与串行拼接结果逐字节一致。

## 5. F17.3（P0）：一次解析、一次严格分析与合法跨图边界的模块级流水

**目标：ingest 从“3 次 parse + 2 次 analyze + 大量主线程串行”变为一次模块 parse、接口摘要固定点、
一次严格 analyze 紧接 lower，并将可证明 graph-local 的 pass 链和 compact 移入 worker。
主线程保留接口协调、确定性发布与跨图 barrier。**

F16 基线与实施前提：

- `firrtl.cpp:136–141` 先 `indexFile`（Lexer 扫描全部 body token），再 `validate`。
  `validate`（`parser.cpp:812–839`）**串行** parse 每个模块后丢弃 AST，
  并对每条 statement/expression 拼接分类字符串，写入 `map<string,…>` 计数。
  生产 ingest 只使用 success/diagnostics，这份 census 是纯开销。（第 1 步已处理，见 §7。）
- `mixed.cpp:402` 对可达模块再次 parse（结果进入 AST cache），并执行 `analyze(true)`。
  该调用不是只分析接口，它包含完整 collect、memory port、全部 statement、约束求解和
  guard 归一化（`semantic.cpp:800`）。
- `lower.cpp:1130` 在 worker 中新建 `Semantics`，执行 `analyze()`，然后才开始构图。
- F16 采样：主线程在 worker 窗口前后分别占 **46.0 / 45.0 s** 用户 CPU，窗口内几乎为 0。
  10 个 worker 的忙碌窗口只有约 37 s，最忙和最闲 worker 相差 2.55×。
  也就是说，113–136 s 的 ingest 中只有约三分之一的时间是并行的。
- 原“八个前置 pass 都是 graph-local”的前提不成立。xmr-resolve 会创建跨图端口/写入者，
  multidriven-guard 依赖完整的跨模块 inout drive 摘要，blackbox-guard 需要完整 catalog 并可能发布 stub；
  这三步都必须在对应发布 barrier 上完成。其余局部链才可按图流水，见下面第 3 步。

方案：

1. **合并 index/validate/parse（已部分实施）：** index 只定位模块字节区间，不 tokenize body。
   每个模块只解析一次，得到 arena AST；语法错误按源码模块顺序归并诊断，
   不可达模块同样被解析以保留原有语法报错。`validate` 的 constructs 统计只留给显式 census。
2. **拆出接口摘要：** worker 解析后先产出体积小的 `InterfaceSummary`，包括端口类型、
   未知宽度/Reset 约束变量，以及对子模块端口的约束边。主线程只在这些摘要上跑层次宽度/
   Reset 固定点，不再对模块体做完整 `analyze(true)`。边界已完全确定的模块（XiangShan 中
   绝大多数）一轮即可收敛。
3. **一次严格分析与合法局部流水：** 接口确定后，同一 worker 用持有的 AST 执行唯一一次严格
   `analyze()`，紧接 lowering，随后释放 AST/Semantics。完整模块 catalog 和 linking 发布之后，
   按原八步次序执行下列链；它不是把八步塞进同一个 lowering 任务：

   ```text
   全部图发布/link verify
     → xmr-resolve（跨图 barrier）
     → [mux-tree-fold → register-write-normalize → mux-tree-fold(guarded) → memory-read-retime]
        （每图 worker 按此顺序执行；诊断/retention 按原 pass→graph 顺序发布）
     → multidriven-guard → blackbox-guard（完整设计协调边界）
     → [latch-transparent-read]（每图 worker）
     → retention metadata 发布 → 仅安全来源并行 compactForFlatten → hier-flatten
   ```

   `runGraphPipeline` 只接收声明了 graph-local kernel 的 pass；对 continue-on-error、
   不保持 dialect 集合或初始 dialect 不受支持的链，退回普通逐阶段执行，保留失败与诊断边界。
   生产链由显式 `IngestPipeline::GrhPreFlatten` 接入，普通 `Ingest` 保留原终点。
   Python 完整生产链消费 prefix report 后跳过已执行八步；旧库不支持该参数或 bringup 等
   不同 pass 列表继续原脚本路径，不能静默减少前置步骤。
   提前 compact 的安全集合在完整设计上计算，排除所有 top 与任何 positional/不完整 named-map 引用；
   它不等于局部链的全部目标图。一次性 epoch receipt 将提前完成的 source-freeze 工作留给
   flatten 原日志边界消费，不写 JSON 或 metadata。
4. **调度：** 按 body 字节数从大到小提交任务（GSIM `firParser.cpp` 已采用该策略），
   GraphId/诊断顺序由预分配和按源码顺序归并保证。linked verify、CombLoopElim 改为
   逐图并行（只有 pending/未证明的图才需要检查），跨图检查留在主线程。

**预算：** ingest + 前置 pass 从 136.2 + 49.8 s（node 开）/ 113.0 + 24.0 s（node 关）
→ **≤ 50 s 墙钟**。其中主线程串行部分目标 ≤ 15 s；worker 部分是一次 parse、
一次 analyze 和一次构图（构图单位成本由 F17.1 决定），按 10 线程并行。

**验收：** 6,007 条诊断按序相同（包括语法错误、宽度/Reset 推断错误和 comb-loop 警告顺序）；
ingest 与 flatten 终点完整 JSON SHA 不变；1/2/4/10 线程结果逐字节一致；
新增回归覆盖未知宽度跨层传播、Reset 推断、mixed FIRRTL↔SV 交替依赖、不可达模块语法错误，
以及 pass 失败时的诊断边界。

## 6. 合计预算、顺序与共同门禁

| 阶段 | F16 基线（node 开） | F17 目标 |
| --- | ---: | ---: |
| ingest + 前置 pass | 186.0 s | ≤ 50 s（F17.3，构图成本依赖 F17.1） |
| hier-flatten | 122.4 s | ≤ 10 s（F17.2，依赖 F17.1） |
| 连续墙钟 | 308.5 s | **≤ 60 s，低于 GSIM 76.5 s** |

目标按 annotations 开启的验收配置设定，不靠关闭 node、bringup 或跳过 pass 来达成。
这些目标是设计预算，需要逐项测量确认；任何一项不达标时，记录实际值和原因，
不得改写目标来宣告完成。

实施顺序：

1. **F17.1 S0–S4（主线）：** 计数基线 → `AttrRange` API 迁移 → `GraphStore` 与差分 oracle →
   切换并删除双布局 → 整机测量。这是其余两项的性能基础，最先投入。
2. **F17.3 第 2 步（可并行）：** 接口摘要与宽度/Reset 固定点只涉及前端，不依赖 core 存储，
   可与 F17.1 同时推进。
3. **F17.2 + F17.3 第 3–4 步：** 在 F17.1 完成后实现列块拼接；按 §5 合法 barrier
   将 graph-local 链和 `compact()` 移入 worker，并行化逐图 verify/CombLoopElim。

暂不纳入 F17：稳定 ID 与以 ID 序列化、临时名不入表、属性值类型化（如 `constValue` 位向量）、
按 op kind 的专用属性列。这些都会改变 ID 契约、JSON 字节或属性语义，需在 F17.1 测量后另行决定。

共同门禁：所有构建和测试都通过 Makefile target 执行；性能证据使用同一冻结
`SimTop.fir`（SHA-256 `cc46aae1…dc754a`）、CPU 0–31、10 lowering worker 和实际加载库
身份记录。每个候选至少记录 ingest/前置 pass/flatten 墙钟、CPU、峰值 RSS、分配次数和
两个终点的完整图 SHA。日志和临时产物放在 `ptmp/firrtl-ingest/F17/`。

## 7. 当前集成候选的实施状态与最终验收（2026-11-04）

本节描述最终源码路径，并将首轮/v2 与修复前 r1 保留为历史证据。r5 已通过 81/81 C++、9 项
Python、72 项 workflow、5 项 GrhSIM flow 与模型、FIRRTL comb 模型、207 份完整 oracle JSON
和 36 组分配基准。`complete-r2/identity-comparison.json` 的 ingest/flatten 完整图、metadata、
source fingerprints、pipeline 和 6,007 条按序诊断全部通过；r1 的 bulk SrcLoc 继承遗漏已修复。
最终正常 native 快照和 fused perf 证据见 F17.1 结果文末。

F17.2 r3 的 unified Make 验证随后通过 81/81 CTest。新增/补齐的直接用例包括 24 层嵌套
single-instance consume（eager/global1/global4 完整 JSON 与诊断一致）、resolved XMR nested
实例（含 child 前后的普通 runs）、global-plan boundary diagnostics（输入/输出宽度、同宽度
kind、domain、递归失败及 partial graph JSON）、retained-page ownership isolation，以及
bulk result SrcLoc inheritance（缺失、显式/空 record、operation/value 无来源和 String/Logic
两类）。这份 r3 CTest 结果只覆盖代码回归；整机两个终点的完整 SHA、6,007 条诊断和正式
性能仍以 complete-r2/final-r2 证据及原有未达预算结论为准。

### 7.1 F17.3：解析、接口摘要与严格分析生命周期

- index 先识别 circuit/header 和模块 body 的字节区间，正常输入不 tokenize 整个 body。
  只有初次 circuit/header index 失败时，才重跑旧 token index，以保留更早 body lexical error
  的诊断选择；这是错误输入的兼容 fallback，不是有效输入的第二轮扫描。
- 生产 scan 使用按 body 字节数降序、受 lowerThreads 限制的 worker，完成每模块一次 parse
  并提取 InterfaceSummary；语法诊断仍按源码模块顺序发布，不可达模块也解析。
  显式 `validate` 的 constructs census API 保留，生产路径不再为 census 丢弃一次完整 AST。
- 私有 `parseSharedModule` 缓存解析成功/失败并共享 ModuleBody，不复制 compatibility API 的 Arena。
  InterfaceSummary 保存宽度约束网络、端口/子实例端点、Reset 组、依赖及延迟检查；
  层次宽度/Reset 固定点只评估摘要，不重新构建完整 Semantics。
  提取摘要本身仍遍历模块语义结构；非字面量 reset init 在摘要 worker 中临时记录连接/guard，
  算出原有 constant proof 后释放，不将完整 guard/connection/Semantics 保留到主线程。
- 接口稳定后，worker 持有 AST 执行一次严格 `analyze()` 并立即 lowering；不再排队保存全体模块
  的严格 Semantics。GraphId/图对象由协调线程确定，catalog 按原依赖发布顺序插入，
  异常在原 ensureFirrtl 依赖访问点重抛。任务结束释放 AST 和摘要缓存，设计发布后再清理残留缓存。
- mixed 中 SV 后来暴露的 FIRRTL 模块先按原规则链接依赖，再进入相同 lowering worker 路径；
  单线程和兼容入口仍可串行执行相同严格分析/构图，不通过改变 lazy error 顺序来取得并行。

### 7.2 F17.3：前置链、发布 barrier 与生产入口

当前 `completePipeline` 已按 §5 的真实依赖拆为 XMR、四步 graph-local 链、两个整设计 guard、
latch 局部尾链。graph-local worker 在单张图内顺次执行局部链；协调线程按原 pass→graph
次序归并诊断/日志，并按每个阶段的图状态发布 node retention。最终 retention 写入完成后，
仅对安全来源并行 `compactForFlatten()`。安全集合要求非 top、至少一个 instance 内联引用，
且所有 instance/blackbox 引用的 input/output/inout named maps 均完整、唯一并覆盖实际端口；
无该组端口时允许省略 map。top、positional 或不完整映射来源保持端口次序。
跨图 port/writer、inout 摘要和 blackbox stub 都在合法 barrier 后可见。

`PassManager::runGraphPipeline` 只接受 graph-local kernel；continue-on-error、不保持 dialect、
初始 dialect 不支持或已有错误的路径保留普通阶段执行。linked verify 和 CombLoopElim
可对需要检查的图并行，结果仍按原顺序发布；有效的 local-cycle proof 可免除重复局部检查。
全局 dialect 摘要按 revision 缓存，但缓存不取消修改后的重新检查或未知 dialect 诊断。

F17.3 的 cycle proof 已具体落地：Graph 的 `mutationEpoch_` 与非序列化
`localCyclesChecked()/markLocalCyclesChecked()` 绑定，lower 成功且无 pending 时记录当前代数；
属性/annotation-only 的 ensure 修改可恢复该证明，拓扑或类型 mutation 自动递增代数并使证明
失效，compact 不伪造新的检查结果。`verifyLinkedDesign` 以 `pendingCombLoopCheck` 或
proof 缺失/失效为 gate，构造不可变 graph-name selection，只将待检查图提交给 CombLoopElim；
成功后仅标记实际检查的图。SV/外部链接图默认无 proof，仍走检查。selection 在图间并行时只读
共享，summary/report 继续按旧全局顺序发布。proof 失效、选图和 1/2/4/10 worker 的回归已
通过；整机完整 identity 仍以固定 10-worker 的 complete-r2 为最终证据。

生产 C++/Python 入口显式选择 `grh-pre-flatten`，返回八步的阶段诊断、worker 时间和 prefix 墙钟。
完整 Python 生产链核对 report 顺序后，跳过已在 native 执行的八步；bringup/其他 pass 前缀和
不支持新 keyword 的历史库保留旧脚本路径。性能对照须使用连续 prefix 墙钟，不能把 worker CPU
和重叠阶段之和当成墙钟，也不能重复计入 fused read_sources 已执行的八步。

### 7.3 F17.2：全局 DFS 计划与来源所有权

全局计划已记录 DFS 有序事件并按事件分配名字、value 与 operation run；实例边界打断父 run，
保留旧 operation ID/JSON 次序。value 类型四列及 op kind 可保留 256 行页面；payload/text
共享与独立 record 的范围见 §3.7。所有符号、shape、SrcLoc 和语义符号引用仍进入目标编号域。

result 定义先发布，端口只做保持父侧代表的定向 union/find。所有端口关系确定后，多块属性
按预分配区间填写，每条 operand 最后解析一次代表；一个 BlockExecutor 跨批复用线程。
定义发布保持普通 addResult 的来源规则：result 没有来源记录而 operation 有来源记录时继承；
已有 result 来源保持原样。`complete-r1` 暴露了遗漏此规则导致的 flat JSON 差异，
当前源码已补齐；r2 完整整机身份已重验通过。
单次使用、允许删除且无 blackbox 保留需求的来源，在完成 metadata 读取后调用
`consumeBlockTopology`：接过原 edge 缓冲区，原位重定位 operands，保留已发布的 result ID，
随后从 Design 删除来源。多次使用或保留来源建立独立目标边；不共享可变实体身份。
正常与异常退出都在交还普通 Graph API 前重建 users/backlink。

source-freeze fallback 仍保留：未就绪来源只有在全部引用具备完整 named port maps 时才 freeze，
positional 引用继续跳过。freeze 失败仍交原 inline 诊断处理，不强行改变端口位置语义。
`Graph::compactForFlatten()` 只在实际 compact 成功后记录当前 mutation epoch 的非序列化 receipt；
原本已 compact 的图不新建 receipt。flatten 在原 gate 对 compact 来源调用
`consumePreparedFlattenFreeze()`：仅当 epoch 一致且仍 compact 时返回 true，将提前完成的工作
计入原日志的 `frozen`；其余记为 `already-frozen`。每次调用都清空 receipt，修改使其失效，
普通 compact/freeze 也会清空，因此不能重复记账。receipt 不进入 metadata、JSON 或 store/load。
日志仍使用原 `source freeze eligible=... frozen=... already-frozen=... skipped-positional=... failed-freeze=...`
格式。最终实测已登记；“提前完成且保持工作记账”只计入 `frozen` 日志，不能据此宣称整机
freeze 成本已经消失。五项计数、prefix 与 flatten 的实际耗时见 F17.1 结果文末。

当前实现不改变 §3.6、§4、§5 和 §6 的任何预算、JSON/诊断或线程一致性要求。最终 fused 实测
为 ingest+pre-flatten 约 84.90 s、flatten 约 110.40 s、连续约 195.45 s、峰值 RSS 约
67.2 GiB；六类 self CPU 合计为 F16 的 36.31%，因此 ≤50/10/60 s 和 ≤25% 热点预算仍未达成。
独立统计版整机连续 native 分配为 1,172,032,695；1,048,576-op 构图/clone/import 基准为
0.000496–0.002582 events/op。性能不达标按实测记录，方案和原始目标保持不变。
完整历史与最终证据见 [F17.1 结果](F17.1-grh-storage-results.md)。
