# GrhSIM IR 基础架构规划

状态：设计草案；基础落地切片见 `implementation-progress.md`。

本文规划在 Wolvrix 中实现 GrhSIM IR 所需的基础数据结构、原地 pass 框架、GRH lowering、
后端映射、Python/session 接口和迁移路径。GrhSIM IR 的具体执行语义、core 方言 op 和 CPU
后端字段仍以 `wolvrix/docs/grhsim_ir/` 下的正式文档为准；本文只决定这些语义如何被软件架构
承载。

本文已经采纳“GrhSIM 使用独立数据结构、semantic pass 原地修改”的设计方向。因此当前
`passes/overview.md` 中“pass 返回替代模型、依靠对象同一性失效 mapping、区分 run/build 入口”的
契约是 M0 阶段需要更新的已知差异；正式文档还需要补入 emit pass。实现时不能同时支持两套
mutation、失效和 pipeline 终态语义。当前基础切片只注册 `grhsim.verify`，但 `PassKind::Emit`、
独立 registry 和统一 pipeline 入口已经作为后续实现必须遵守的接口边界。

## 1. 结论

首版基础架构采用以下不可违背的边界：

1. GRH IR 与 GrhSIM IR 使用两套独立数据结构和两套独立 pass 框架。
2. 两者只通过 `GRH -> GrhSIM` 的单向 lowering 连接，不共享 node、value、ID、builder 或
   pass session 数据。
3. GrhSIM pass 原地修改唯一一份 `GrhSimModel`，不为每个 pass 复制整张模型。
4. 所有修改必须经过受控 editor；mapping 失效由模型 revision 判断，不依赖 C++/Python 对象
   同一性。
5. correctness-critical 的分析结果必须进入 `GrhSimModel` 或具体 `BackendMapping`，不得再通过
   未命名 session slot 从 pass 暗传给 emit pass。
6. 一个闭合 top 对应一个 `GrhSimModel`。首版要求 GRH 已经完成 XMR resolve 和 hierarchy
   flatten。
7. emit 是 GrhSIM pass 的一种；它只读消费 `GrhSimModel + BackendMapping` 并显式返回 artifact，
   不再反向查询 GRH 或 GRH pass context。
8. load/store 是 model 进入和离开 session 的持久化边界，必须支持独立 round-trip，不经过 GRH。

目标链路为：

```text
SystemVerilog
    -> GRH Design
    -> GRH normalization
    -> lower_grh_to_grhsim(top)
    -> GrhSimModel(core, mappings = {})
    -> GrhSIM semantic passes (in-place)
    -> backend mapping passes (in-place)
    -> backend emit pass (read-only)
    -> artifact/runtime
```

持久化链路与 GRH 解耦：

```text
GrhSIM bundle -> load_grhsim -> GrhSimModel -> store_grhsim -> GrhSIM bundle
```

## 2. 目标与非目标

### 2.1 目标

- 给 `I/O/S/F/G/Init/mappings` 提供可扩展、可验证、可序列化的原生 C++ 表示。
- 在千万级 op/value 上运行 pass 时只保留一份主模型，并允许 pass 使用与自身算法规模相称的
  临时内存。
- 为 core 等 semantic dialect、CPU/Corvus 等 backend，以及它们提供的 pass 建立彼此独立的
  registry、解析和验证入口。
- 让语义修改、mapping 修改、派生分析缓存的生命周期可被 pass manager 准确区分。
- 保留从 GrhSIM ID 到 GRH ID、源码位置和层次路径的可追踪关系。
- 逐步替换当前 `GRH + activity-schedule SessionStore + grhsim-cpp emitter` 链路，而不是一次性
  重写现有代码生成实现。
- 支持独立保存、加载和验证 GrhSIM 模型，使问题可以脱离 SystemVerilog/GRH 重放。

### 2.2 非目标

- 首版不支持带 `kInstance` 的层次化 GrhSIM model。
- 首版不提供 GrhSIM 到 GRH 的逆转换。
- 不要求 Python 逐节点 pass 获得与 C++ pass 相同的性能。
- 不在基础架构中固化 CPU 的具体分区或调度算法。
- 不要求 pass 失败时通过复制整模型来恢复修改前状态。
- 不把现有 GRH `OperationKind` 扩展成同时服务两套 IR 的公共 op 枚举。

## 3. 分层与依赖方向

### 3.1 逻辑分层

| 层 | 主要对象 | 职责 |
| --- | --- | --- |
| GRH | `grh::Design`, `grh::Graph` | 保存 RTL 结构、层次、源码符号并执行通用 RTL 变换 |
| Bridge | `GrhToGrhSimLowering` | 选择 top、检查前置条件、构建独立 GrhSIM model 和 provenance |
| GrhSIM IR | `GrhSimModel`, `SimGraph` | 保存后端无关的仿真状态转移语义 |
| GrhSIM Pass | `PassManager`, `PassRegistry`, editors | 执行 analysis、metadata、semantic、mapping 和 emit pass |
| Backend | `BackendMapping`, backend passes | 保存 data layout、partition、schedule 等实现决策并生成 artifact |
| Persistence | model reader/writer | 在文件与 session-owned model 之间执行独立 load/store |
| Runtime | backend runtime | 加载 emit pass 生成的 artifact 并执行模型 |

### 3.2 构建依赖

建议拆成以下逻辑 target；首个实现可以暂时仍链接进 `wolvrix-lib`，但 include 依赖必须保持
同样方向：

```text
wolvrix-grhsim-ir          # 不依赖 GRH
    ^
    +-- wolvrix-grhsim-pass
    +-- wolvrix-grhsim-core-dialect
    +-- wolvrix-grhsim-cpu

wolvrix-grh + wolvrix-grhsim-ir
    -> wolvrix-grh-to-grhsim

wolvrix-grhsim-ir + wolvrix-grhsim-cpu
    -> wolvrix-grhsim-cpu-emit

pybind
    -> 上述模块
```

禁止依赖：

- `grhsim-ir` 不能 include `core/grh.hpp`。
- GRH core 和 GRH transform 不能依赖任何 GrhSIM header。
- CPU/Corvus backend 不能修改 core dialect 的定义来保存自己的物理信息。
- emit pass 不能依赖 GRH `SessionStore` 才能获得 correctness-critical 数据。

只有 bridge、兼容 adapter 和顶层 Python 编排可以同时依赖 GRH 与 GrhSIM。

## 4. 目录规划

建议新增：

```text
wolvrix/include/grhsim/
  ir/
    ids.hpp
    model.hpp
    graph.hpp
    objects.hpp
    type.hpp
    attributes.hpp
    dialect.hpp
    verifier.hpp
    serialization.hpp
    model_io.hpp
  pass/
    pass.hpp
    pass_manager.hpp
    registry.hpp
    analysis_manager.hpp
    artifact.hpp
  convert/
    grh_to_grhsim.hpp
  dialect/
    core.hpp
    cpu.hpp
  backend/
    mapping.hpp
    cpu_mapping.hpp
    cpu_codegen.hpp

wolvrix/lib/grhsim/
  ir/
  pass/
  convert/
  dialect/
  backend/

wolvrix/tests/grhsim/
  ir/
  pass/
  convert/
  dialect/
  backend/
  data/
```

C++ namespace 对应为：

```text
wolvrix::lib::grhsim
wolvrix::lib::grhsim::ir
wolvrix::lib::grhsim::pass
wolvrix::lib::grhsim::convert
wolvrix::lib::grhsim::dialect
wolvrix::lib::grhsim::backend::cpu
```

这里的 `dialect::core` 与仓库已有的 `include/core/` 含义不同，不能把 core 方言文件直接放入
现有 `include/core/`。

## 5. `GrhSimModel` 所有权

### 5.1 顶层对象

建议运行时对象结构如下：

```text
GrhSimModel
  identity: ModelIdentity
  semantic_revision: uint64
  metadata_revision: uint64
  status: valid | poisoned

  semantic_dialects: DialectManifest
  interface: InterfaceTable
  inputs: InputTable
  outputs: OutputTable
  states: StateTable
  extern_functions: ExternFunctionTable
  graph: SimGraph
  init: InitTable

  mappings: MappingTable
  origins: OriginTable
```

其中：

- `inputs/outputs/states/extern_functions/graph/init` 对应正式模型的语义分量。
- `semantic_dialects` 固定模型语义分量所需的方言名、版本和 schema fingerprint。
- `interface` 保存模型名、公开端口名、顺序和 inout 分组，是调用 ABI 元数据；它不替代
  `I/O` 对象。
- `origins` 保存诊断和调试 provenance，不参与 `eval_G`。
- `mappings` 是派生实现方案，可以被释放和重建。
- `status = poisoned` 表示某次不可恢复的原地修改失败；这种模型只能诊断或丢弃，不能继续
  pass、序列化或 emit。

`GrhSimModel` 不可复制，允许 move。显式 deep clone 可以作为调试工具提供，但不能成为正常
pass 路径的一部分。

`ModelIdentity` 是进程内唯一、move 后保持不变的 128-bit token。新 lowering、新 load 和显式
deep clone 都创建新 identity；不能只用 revision 判断两个不同 model 的 mapping 是否兼容。
`semantic_revision` 和 `metadata_revision` 均从 1 开始。

### 5.2 一个 top 一个 model

GRH `Design` 可以有多个 top 和多个 module；首版 GrhSIM `SimGraph` 是一个闭合执行图。因此：

- lowering 必须显式指定一个 top；
- 每个 top 单独生成一个 `GrhSimModel`；
- 多 top 产物由 Python/session 或非语义性的 `GrhSimCompilation` 容器管理；
- model 内所有 ID 只在该 model 中有效。

不要为了保留 GRH `Design` 外形而给首版 GrhSIM 增加一层 module graph 集合。未来若确实需要
层次仿真，应单独定义 GrhSIM hierarchy dialect 和模型容器。

## 6. ID、符号和 provenance

### 6.1 ID

每类实体使用独立的 typed generational ID：

```cpp
template<typename Tag>
struct Id {
    uint32_t index = 0;
    uint32_t generation = 0;
};

using InputId = Id<InputTag>;
using OutputId = Id<OutputTag>;
using StateId = Id<StateTag>;
using FuncId = Id<FuncTag>;
using OpId = Id<OpTag>;
using ValueId = Id<ValueTag>;
```

约束：

- `index == 0` 为 invalid。
- ID model-scoped，不嵌入裸 model 指针，以控制每条边的内存。
- 删除 slot 时增加 generation；旧 ID 必须被 verifier/editor 拒绝。
- `ObjectRef` 是带 kind tag 的 `InputId | OutputId | StateId | FuncId`，不能用裸整数猜种类。
- backend 自己定义 `PartitionId/TaskId` 等 ID，不与 semantic ID 共用 allocator。

GRH ID 与 GrhSIM ID 不能共享数值身份。Bridge 使用临时映射表解析引用，完成 lowering 后释放
临时表。

### 6.2 符号和接口

所有重复字符串进入 model 级 `StringInterner`。IR record 只保存 `SymbolId`，不为每个 op/value
保存 `std::string`。

`InterfaceTable` 至少保存：

```text
ModelInterface
  model_name: SymbolId
  ports: InterfacePort[]

InterfacePort
  name: SymbolId
  kind: input | output | inout
  input: InputId?
  output: OutputId?
  output_enable: OutputId?
```

对于 GRH inout，首版固定映射为一个输入对象和两个输出对象，并通过同一个 `InterfacePort`
保留组合关系。具体 `in/out/oe` 方向必须先在正式语义文档中统一。

### 6.3 来源映射

`OriginTable` 使用紧凑 `OriginId`，一个 origin 可以包含：

```text
Origin
  source_kind: grh-op | grh-value | grh-port | generated | pass
  graph_symbol: SymbolId?
  source_index: uint32?
  source_generation: uint32?
  hierarchy_path: SymbolId?
  source_location: SourceLocation?
  producer_pass: SymbolId?
  note: SymbolId?
```

每个 GrhSIM object/op/value 只保存一个 `OriginId`。多个实体来自同一来源时共享 origin。一个
pass 合并多个来源时，可创建 interned origin-set；不得在每个节点中保存重复 vector。

`SourceLocation` 必须是 GrhSIM 自己的 POD，或从 GRH 中抽到不依赖任何 IR 的公共 support
模块；`grhsim-ir` 不能为了复用 `grh::SrcLoc` include `core/grh.hpp`。Bridge 只复制位置字段。

## 7. 紧凑 IR 存储

XiangShan 当前规模达到千万级 op 和 value。每个 record 多 16 字节就会增加约 160 MB，基础
实现不能以“每个实体一个 heap object + 多个 `std::vector` + 多个 `std::string`”起步。

### 7.1 Slot table 与 flat pool

建议 `SimGraph` 采用 slot table 加集中 flat pool：

```text
OperationRecord
  generation: uint32
  op_type: OpTypeId
  symbol: SymbolId
  origin: OriginId
  operands: Range32
  results: Range32
  object_refs: Range32
  parameters: Range32
  flags: uint32

ValueRecord
  generation: uint32
  type: TypeId
  symbol: SymbolId
  origin: OriginId
  flags: uint32

SimGraph
  op_slots: SlotTable<OperationRecord>
  value_slots: SlotTable<ValueRecord>
  operand_pool: Vector<ValueId>
  result_pool: Vector<ValueId>
  object_ref_pool: Vector<ObjectRef>
  parameter_pool: dialect-defined compact values
```

`Range32` 使用 32-bit offset/count。首版单个 model 的 pool 上限为 `2^32 - 1` 项；超过时必须
明确诊断，不能静默截断。

### 7.2 修改与碎片

对 variable-length range 的修改采用 free-span-reuse + append-new-range：

1. 优先从 size-class/free-span 索引复用足够大的 dead range；
2. 没有合适 free span 时，在对应 flat pool 末尾写入新内容；
3. 更新 record 的 range；
4. 旧 range 归还 free-span 索引并计入 dead bytes；
5. dead/total 超过阈值时运行显式 `compact-storage` maintenance；
6. compaction 只移动 pool 内容并更新 range，不改变实体 ID。

Free-span 索引本身必须紧凑，不能为每个小 range 创建 heap node。全图 bulk rewrite 可以使用
“新 relationship pool 构建完成后 swap”的专用模式，其峰值只包含被重建的 pool，不复制
object/value/op record；是否启用由 pass 根据 scratch budget 决定。

这避免每次插入 operand 都移动全局数组，也避免每个 op 独立分配小 vector。Pass manager 记录
每个 pool 的 live/dead byte 统计，用于决定是否 compact；不能在每个 pass 后无条件 compact。
Pass 看到的操作始终是：

```text
allocate new range -> update owner record -> release old range
```

pass 不得直接修改 pool offset。

### 7.3 Def-use

正式 IR 只以 op 的 operands/results 作为语义真源。为了支持高效原地 pass，可以按需维护派生的
`DefUseIndex`：

```text
DefUseIndex
  revision: uint64
  defining_op_by_value: compact dense array
  users_by_value: compact adjacency
```

规则：

- `DefUseIndex` 不参与序列化和模型语义；`ValueRecord` 不重复保存 producer。
- editor 可以增量维护它；无法低成本维护时将其标记 stale。
- pass 请求 producer/users 时由 `AnalysisManager` 按当前 semantic revision 重建。
- verifier 可从 results/operands 重新计算并抽查或全量比较，防止缓存漂移。

### 7.4 类型与参数驻留

- `TypeRef` 在内存中解析并驻留为 `TypeId`；序列化时恢复为方言名、定义名和参数。
- 相同的 `core.logic<width, signed, domain>` 只保存一次 type instance。
- op record 保存 `OpTypeId`，不重复保存 `"core.compute.add"` 字符串。
- parameter key 来自 dialect schema 的字段编号，不在每个 op 中重复保存 key 字符串。
- 常见小标量采用 inline tagged value；大数组和字符串放入共享 blob/string pool。

### 7.5 Pass scratch memory

`PassContext` 提供独立的、带统计的 scratch memory resource：

```text
PassScratch
  memory_resource
  soft_limit_bytes
  peak_bytes
```

- pass 的队列、临时映射、stamp array 和候选集合优先从 scratch 分配；
- pass 结束后统一释放，不混入 model arena；
- pass 可以声明 scratch soft limit，超过时给出带 pass 名的诊断；
- 大图算法优先使用 source-ID-indexed vector、bitset 和 stamp array，避免默认使用多个
  `unordered_map/unordered_set`；
- pipeline 统计同时报告 persistent model bytes 与 per-pass peak scratch bytes。

## 8. 原地修改模型

### 8.1 Editor 是唯一写入口

IR 的公开只读 API 返回 view/span；所有写操作经过 `ModelEditor`：

```cpp
class ModelEditor {
public:
    ValueId createValue(TypeId type, SymbolId symbol = {});
    OpId createOp(OpTypeId type, ...);
    StateId createState(TypeId type, SymbolId symbol = {});

    void replaceOperand(OpId op, uint32_t index, ValueId value);
    void replaceAllUses(ValueId from, ValueId to);
    void setParameter(OpId op, ParameterId key, ParameterValue value);
    void eraseOp(OpId op);
    void eraseValue(ValueId value);
};

class MappingEditor {
public:
    explicit MappingEditor(GrhSimModel& model, BackendId backend);
    // 只暴露目标 backend payload 的受控修改接口。
};
```

Editor 负责：

- graph/model 归属和 generation 检查；
- def-use/cache 更新或失效；
- dirty domain 记录；
- state 与 `Init` 全映射关系维护；
- dialect schema 的局部类型检查；
- dead range 和内存统计；
- 禁止 semantic pass 取得 `MappingEditor`；
- 禁止 backend pass 取得 `ModelEditor`。

不向 Python 或 pass 公开可写的底层 vector/map。

### 8.2 Revision

`semantic_revision` 初始为 1。一次成功 pass 无论执行多少个 editor 操作，最多增加一次 revision。

```text
pass begin
  -> on first semantic write:
         editor records semantic_dirty
         clear all backend mappings
         invalidate semantic analyses
  -> pass succeeds
  -> if semantic_dirty:
         semantic_revision += 1
     else:
         retain semantic_revision
  -> verifier
  -> commit pass result
```

第一次 semantic write 发生时，editor 立即清空并析构已有 mapping。这样 semantic pass 可以尽早
释放大 mapping 给自己的 scratch 腾出内存，也不会在修改过程中误读旧计划。Pass 成功后再把
`semantic_revision` 增加一次；若 pass 最终没有执行任何写操作，mapping 和 revision 都保持
不变。旧 analysis 也在第一次写时立即变为不可见，pass 不得跨 mutation 持有 analysis view。
Backend pass 创建/更新的 mapping 始终绑定当前 revision。

`interface` 中会影响公开 ABI 的字段和 `semantic_dialects` 也按 semantic mutation 处理；只修改
诊断文本或 provenance 不增加 semantic revision，但必须增加独立的 metadata revision，供调试
产物缓存判断是否可复用。

Mapping entry 至少保存：

```text
MappingEntry
  backend: BackendId
  bound_model_identity: ModelIdentity
  bound_semantic_revision: uint64
  backend_dialects: DialectManifest
  status: partial | complete
  payload: backend-defined
```

任何 identity/revision 不匹配的 mapping 都不得读取。语义变化后默认直接释放全部 mapping，
既减少误用风险，也及时回收其内存；binding 字段仍用于加载、API 组合和 verifier 的防御性检查。

### 8.3 Pass 失败

全模型 rollback 会抵消原地 pass 的内存收益。首版采用以下失败契约：

1. pass 在第一次写之前完成所有可预见的 legality/preflight 检查；
2. 需要复杂构造的数据先在 pass-local 临时对象中完成，再通过 editor 批量提交；
3. pass 一旦开始提交，应只调用已验证参数的 no-fail mutation 路径；
4. 若 pass 在修改后仍不可恢复地失败，model 标记为 `poisoned`，pass manager 立即停止；
5. poisoned model 不得继续运行 transform/mapping/emit pass，也不得 store；调用方可以保留它做
   诊断，或从 session 删除并由上一个持久检查点 load 重建；
6. debug/test 构建可以提供可选 mutation journal，但生产路径不依赖全量 undo log。

每个 pass 仍应尽量保证“失败后模型结构合法”。`poisoned` 是处理内部异常和 verifier 失败的
最后防线，不是普通参数错误的控制流。

上述 poisoned 规则只针对 semantic pass。Backend mapping pass 失败或 backend verifier 失败时，
manager 删除该 backend 本次修改的 mapping，semantic model 和其他 backend mapping 保持有效；
只有检测到 semantic storage/ID 被越权破坏时才 poison 整个 model。

### 8.4 ID 稳定与 compaction

- 普通 pass 不重编号存活实体。
- erase 后 slot 可复用，但 generation 必须变化。
- flat pool compaction 不改变 ID。
- 只有显式 `renumber-model` 工具可以重编号；它属于语义模型重写，必须清空 mappings 和
  provenance 中依赖旧 ID 的派生索引。

## 9. 独立 Pass 框架

### 9.1 C++ 接口

建议接口为：

```cpp
enum class PassKind {
    Analysis,
    MetadataTransform,
    SemanticTransform,
    BackendMapping,
    Emit
};

struct ArtifactRecord {
    std::string kind;
    std::filesystem::path path;
    std::string digest;
    std::optional<BackendId> backend;
    ModelIdentity modelIdentity;
    uint64_t semanticRevision = 0;
};

struct PassResult {
    bool success = true;
    bool changed = false;
};

class Pass {
public:
    virtual ~Pass() = default;
    virtual std::string_view name() const noexcept = 0;
    virtual PassKind kind() const noexcept = 0;
    virtual PassResult run(PassContext& context) = 0;
};
```

`PassContext` 提供当前 model 的只读 view、按 kind 限制的 editor、各类 registry、diagnostics、
analysis manager、scratch memory、pass options，以及 emit pass 专用的 `ArtifactSink`。Pass 不保存
跨 `run()` 的 model 指针。

| Pass kind | 可写能力 | 额外约束 |
| --- | --- | --- |
| `Analysis` | 无 | 只能填充可丢弃的 analysis cache，`changed` 必须为 false |
| `MetadataTransform` | `MetadataEditor` | 只能修改 provenance 等非 ABI metadata |
| `SemanticTransform` | `ModelEditor` | 不暴露 backend mapping payload |
| `BackendMapping` | 目标 backend 的 `MappingEditor` | semantic model 只读，不能修改其他 mapping |
| `Emit` | 无；只能写 `ArtifactSink` | 声明所需 backend 和 mapping 完整度，`changed` 必须为 false |

`ArtifactSink` 面向流式大文件，不把生成代码或二进制放进 `PassResult` 内存。它先写同目录临时
文件，pass 和验证全部成功后再原子 rename；`ArtifactRecord` 由 manager 根据已提交 sink 构造，
只在 `PipelineResult` 中返回路径、类型、digest、model identity/revision 和 backend 等小型元数据。
Emit 失败时删除临时产物，不修改或 poison model。

首版禁止一个 pass 同时修改 semantic model 和 backend mapping，也禁止 emit pass 顺带修改二者。
需要多步工作的功能拆成多个 pass。CPU 代码生成器可以保留为 `cpu.emit-cpp` 内部使用的 C++
组件，但不能成为与 pass manager 平行的公开执行入口。

### 9.2 Pass manager

Pass manager 的固定流程：

1. 检查 model 非 poisoned，并在 pipeline 入口做 structural verify；
2. 从 `PassRegistry` 解析 descriptor，检查 kind、所需 dialect/analysis、目标 backend 和 mapping
   完整度；
3. 创建该 kind 唯一允许的 editor 或 `ArtifactSink`；
4. 运行 pass；
5. 对 mutation pass 比较 `changed` 与 editor dirty 状态；analysis/emit pass 的 `changed` 必须为
   false；
6. 按 dirty domain 更新 revision、清理 mapping 和 analysis cache；
7. 运行该 kind 对应的 incremental semantic 或 backend verifier；
8. semantic verifier 失败时按第 8.3 节 poison model；backend 失败只删除本次修改的目标 mapping；
   emit 失败只回收临时 artifact；
9. emit 成功后提交 `ArtifactSink`，把 `ArtifactRecord` 加入 pipeline result；
10. pipeline 结束时做 full structural verify，但不要求 model 必须带 mapping。

只有一个执行原语：

```cpp
PipelineResult run(GrhSimModel& model,
                   std::span<const PassInvocation> passes,
                   ArtifactSink& artifacts);
```

`PipelineResult` 包含 success、diagnostics、逐 pass report 和 artifacts。运行单个 pass 只是传入一个
元素的 pipeline。每个 pass 自己声明 `required_mapping = none | partial | complete`；例如
`cpu.emit-cpp` 声明 `backend = cpu` 和 `required_mapping = complete`，manager 在执行它之前自动做
identity/revision 检查和 CPU complete verify。

Pipeline 可以停在任意合法 semantic model 或 partial mapping，不存在独立的 `build` 终态。第一次
成功执行 `Emit` 后，后续只允许 `Analysis` 或其他 `Emit`，禁止再修改 metadata、semantic model
或 mapping，避免同一次 pipeline 返回的 artifact 对应不同模型阶段。

### 9.3 Analysis manager

允许保存纯派生、可随时重建的性能缓存，例如 def-use index、state reader index、SCC 和静止投影
`E`。每项缓存必须声明：

```text
AnalysisKey
  analysis_type
  semantic_revision
  option_fingerprint
```

限制：

- analysis 不能改变模型含义；
- 唯一由 model 推导的分析可以由 emit pass 临时重算，但 emit pass 不能要求某个先行 pass 通过
  analysis store 提供它；
- 分区、布局、调度启发式结果等非唯一实现选择必须物化到 mapping；
- semantic revision 变化后旧 analysis 不可见并尽快释放；
- 需要跨序列化保留或由 backend emit pass 消费的数据应进入 backend mapping，而不是 analysis
  store。

### 9.4 Registry、方言与命名

`PassRegistry`、`DialectRegistry` 和 backend registry 是三个独立扩展点。Pass 不属于 dialect，
也不写入 `DialectManifest`；它只在 descriptor 中声明依赖的 dialect 名称/版本、backend、analysis
和 mapping 完整度。一个扩展包可以同时向多个 registry 注册内容，但这不改变三者的生命周期和
序列化边界。

Pass 名称在 GrhSIM registry 内全局唯一，采用 `<provider>.<name>`：

```text
grhsim.canonicalize
grhsim.compact-storage
core.coalesce-ordered-writes
cpu.data-layout
cpu.partition
cpu.schedule
cpu.emit-cpp
```

- `grhsim.*` 是通用 IR pass，例如 `grhsim.canonicalize` 遍历已加载 dialect 提供的 fold/
  canonicalization hook；
- `core.*` 是理解 core dialect 特定语义的 pass，可以随 core 扩展包发布，但仍注册到
  `PassRegistry`；
- `cpu.*` 是 CPU backend 提供的 mapping 或 emit pass。

模型只保存实际使用的 dialect manifest；可选的 pipeline history 可以作为 provenance metadata
记录 pass 名和参数摘要，但不能成为重新解释模型所必需的隐藏状态。GRH 现有 `hier-flatten` 等
名称保留在 GRH registry。Python 可以提供统一列举界面，但创建 pass 时必须显式指定 IR kind。

## 10. Dialect 基础设施

### 10.1 Registry 与 manifest

`DialectRegistry` 是进程级定义表；`DialectManifest` 是某个 model 或 mapping 实际绑定的定义
快照：

```text
DialectManifestEntry
  name
  version
  schema_fingerprint
  role: semantic | backend
```

模型加载或 lowering 时解析字符串引用为紧凑 `TypeId/OpTypeId/FuncDeclId`。Pass 执行期间禁止
替换已绑定的 dialect 定义。Semantic dialect 升级必须走显式 migration，并视为 semantic
revision 变化。CPU 等 backend dialect 记录在对应 `MappingEntry` 中；新增或升级它只使该 mapping
变化，不能增加 model semantic revision，也不能影响其他 backend mapping。

### 10.2 Dialect 提供的能力

每个 semantic dialect 至少注册：

- type schema、参数解析、相等和打印；
- `InitSpec` schema 与验证；
- op 的 operand/result/object-ref/parameter schema；
- object ref 的 read/write effect；
- event operand 与 event-history ref 位置；
- operation verifier；
- 可选的 fold/canonicalization hook；
- 序列化版本迁移入口。

Backend dialect 可以额外注册物理大小、对齐、存储布局和 ABI 编码，但 backend 类型不得出现在
semantic `I/O/S/value` 中。

### 10.3 未知方言

独立的 bundle inspector 可以在不创建 `GrhSimModel` 的情况下保留和显示未知 dialect 的原始
payload。含未知 semantic dialect 的 bundle 不能正常 load 为 model，并且必须拒绝：

- semantic verify；
- 修改包含未知 op/type 的模型；
- 构建 backend mapping；
- emit 或执行。

不能把未知 op 当作纯组合 op，也不能把不支持的 system/DPI 调用删除。

## 11. GRH 到 GrhSIM lowering

### 11.1 前置条件

首版 bridge 接受一个指定 top，并要求：

- XMR 已 resolve；
- hierarchy 已 flatten，不含 `kInstance`；
- blackbox 已被拒绝或显式转换成已注册扩展方言；
- 组合环、multi-driven、memory init 等满足 core 方言的转换要求；
- 所有 GRH op 都存在明确的 core mapping；
- 2-state/4-state policy 是显式参数，不能从某个旧 pass 是否运行过来猜测；
- inout 方向、公开名字和排列已经完整。

Bridge 只做语义保持的表示转换。`memWriteSeq` 聚合、reg-to-mem、后端布局等非一对一优化应由
后续 GrhSIM semantic/backend pass 完成，除非正式 core 方言文档明确把它定义为 lowering
规范的一部分。

### 11.2 API

```cpp
struct LowerOptions {
    std::string top;
    LogicDomainPolicy logicDomain;
    bool keepDebugOrigins = true;
};

struct LowerResult {
    bool success = true;
    std::unique_ptr<GrhSimModel> model;
};

LowerResult lowerFromGrh(const grh::Design& design,
                         const LowerOptions& options,
                         LowerDiagnostics& diagnostics,
                         const DialectRegistry& dialects);
```

失败时不返回部分 model。Bridge 内部可以原地构建尚未发布的新 model；因为输出尚未进入
session，这不属于 pass rollback。

### 11.3 转换阶段

建议使用可测量的多阶段构建：

1. 验证 top 和 lowering 前置条件；统计 entity/pool 数量并 reserve。
2. 建立 type interning、interface 和 I/O 对象；为 GRH input 创建 `core.input.read`。
3. 为 storage declaration 创建 `S` 与完整 `Init` 条目。
4. 为 DPI import 创建 `F` 和 signature。
5. 为 GRH values/ops 分配 GrhSIM ID，保存紧凑的临时正向映射。
6. 填充 operands/results/object refs/parameters。
7. 创建 output write 和规范要求的 event-history state。
8. 建立 origins，释放 GRH-to-GrhSIM 临时哈希表。
9. 运行 full semantic verifier；成功后发布 model。

如果 GRH graph 的原始 ID index 足够紧凑，临时映射优先使用 vector 而非 `unordered_map`。

### 11.4 降低峰值内存

独立结构意味着 lowering 期间会短暂同时存在 GRH 与 GrhSIM。首版采用以下控制方式：

- 预扫描后一次 reserve，避免构建期反复扩容；
- type/string/origin interning；
- 映射使用按 source ID index 排列的紧凑数组；
- 每个转换阶段结束立即释放不再需要的临时索引；
- Python/session 提供显式 `consume=True`，仅在 lowering 成功后删除源 GRH Design；
- 大模型流水线在 lowering 前保存可选 GRH checkpoint，之后只保留 GrhSIM model。

首版不做“边读 GRH 边销毁 GRH node”的破坏式 lowering。它会使错误恢复和引用解析复杂化；
只有峰值数据证明上述方案仍不可接受时再单独设计 consuming lowerer。

## 12. Backend mapping

### 12.1 公共 envelope

后端 payload 没有统一字段，但公共基础架构需要统一 envelope：

```text
MappingEntry
  backend_id: BackendId
  backend_version: Version
  bound_model_identity: ModelIdentity
  bound_semantic_revision: uint64
  backend_dialects: DialectManifest
  status: partial | complete
  payload_type: MappingTypeId
  payload: backend-owned storage
```

后端通过 registry 注册 mapping factory、deleter、structural verifier、complete verifier、serializer
和 inspector。`MappingTable` 使用唯一所有权，语义变化时可以立即析构释放。

### 12.2 分阶段构建

CPU mapping 可以由多个 pass 原地推进：

```text
cpu.data-layout
  -> CpuBackendMapping{data_layout, partial}

cpu.partition
  -> CpuBackendMapping{data_layout, partition_tree, partial}

cpu.schedule
  -> CpuBackendMapping{data_layout, partition_tree, schedule_plan, complete}
```

每一步之后运行 structural verifier。Partial mapping 可以在 pipeline 结束后继续存在并被 store，
但不能被要求 complete mapping 的 pass 消费。`cpu.emit-cpp` 等 pass 运行前，由 manager 自动执行
CPU complete verifier。

### 12.3 调度显式化

当前 `activity-schedule` 通过 GRH `SessionStore` 传递 supernode、fanout、topo order 和 state
reader 等数据。迁移后，凡是决定生成代码执行行为的数据都必须成为 CPU mapping 的显式字段。

如果正式 `CpuBackendMapping::SchedulePlan` 当前字段不足以表达 compute/commit phase、activation
fanout、fixed-point round 或 event handling，应先扩展正式 CPU backend 文档，再迁移 emit pass；
不得在新架构中复制一套隐藏 session。

### 12.4 Emit pass

GrhSIM 不提供与 pass manager 平行的公开 emitter 接口，也不继承当前只接受 `grh::Design` 的
`emit::Emit`。每一种输出形式注册为 `PassKind::Emit`，例如：

```text
PassDescriptor
  name: cpu.emit-cpp
  kind: Emit
  backend: cpu
  required_mapping: complete
  required_dialects: [core, cpu]
```

`cpu.emit-cpp` 的 pass options 保存输出路径、代码生成模式等配置；生成内容写入 manager 提供的
`ArtifactSink`。backend 模块内部可以实现不公开的 `CpuCodegen` 辅助类，以复用表达式和 runtime
生成逻辑，但外部只能通过 pass registry/pipeline 调用它。它不能直接 include 或依赖当前携带
`grh::Design`、GRH `SessionStore` 的 `core/emit.hpp` 接口。

Manager 在运行 emit pass 前固定执行：

1. full semantic verify；
2. 查找 descriptor 指定的 backend mapping；
3. 检查 identity、semantic revision、backend dialect manifest 和 mapping status；
4. complete backend verify；
5. 以只读 view 运行 emit pass；
6. 成功后原子提交 artifact，失败则删除临时文件。

Emit pass 可以构造 pass-local 派生索引，但不能把索引写回 semantic model 或 mapping。生成的
`ArtifactRecord` 必须记录 model identity/revision 和 mapping fingerprint，使产物能追溯到精确
输入快照。

## 13. Python 与 Session

### 13.1 Session 所有权

`SessionHandle` 增加独立容器：

```text
SessionHandle
  designs: Map<String, DesignHandle>
  grhsim_models: Map<String, unique_ptr<GrhSimModel>>
  native_values: existing auxiliary values
  python_values: existing Python values
```

GrhSIM model 不能作为无类型的 `native_values` session slot 保存，否则生命周期、copy、rename、
kind 检查和 consume 行为无法可靠实现。

### 13.2 建议 API

```python
# 从 GRH lowering 或从 GrhSIM bundle load，二选一创建 model。
sess.lower_grhsim(
    design="design.main",
    top="SimTop",
    out_model="grhsim.main",
    logic_domain="2-state",
    consume=False,
)

sess.load_grhsim(
    "build/checkpoint.grhsim.json",
    out_model="grhsim.replay",
    load_mappings=True,
    backends=None,
    replace=False,
)

sess.run_grhsim_pass(
    "grhsim.canonicalize",
    model="grhsim.main",
)

result = sess.run_grhsim_pipeline(
    model="grhsim.main",
    passes=[
        ("grhsim.canonicalize", {}),
        ("core.coalesce-ordered-writes", {}),
        ("cpu.data-layout", {}),
        ("cpu.partition", {}),
        ("cpu.schedule", {}),
        ("cpu.emit-cpp", {"output": "build/sim.cpp"}),
    ],
)

sess.store_grhsim(
    model="grhsim.main",
    output="build/checkpoint.grhsim.json",
    mappings="complete",
    backends=None,
    include_origins=True,
)
```

约束：

- `consume=True` 仅在 lowering 完全成功后删除 `design` key。
- `load_grhsim` 只有在解析、方言绑定和 full verify 全部成功后才把新 model 插入 session；
  `replace=True` 也必须到最后一步才替换旧 key。
- `store_grhsim` 是只读一致性快照，不能保存 poisoned model；输出使用临时文件加原子 rename。
- Python model wrapper 是 opaque native handle，不把千万级 table 转成 Python list/dict。
- Python pass 只能通过受控的批量 editor API 修改模型。
- C++ 重 pass 在执行期间释放 GIL；同一 model 同时只允许一个 writer。
- `session.rename` 对 model 为 O(1) ownership move。
- `session.copy` 对 model 必须显式请求 deep copy并给出内存警告；不能隐式复制。
- GrhSIM 不沿用 GRH `dryrun=clone whole design`。分析型 dry-run 应使用只读 analysis pass；真正
  mutation dry-run 需要从 checkpoint 重新加载或显式 deep clone。
- 大图优先使用 `run_grhsim_pipeline`，让 manager 在整条 pipeline 的首尾各做一次 full verify，
  中间只做基于 dirty set 的增量验证；`run_grhsim_pass` 是单 pass 便利入口。
- 不提供 `build_grhsim` 和 `emit_grhsim` 基础 API：前者只是 backend mapping pass 序列，后者就是
  `PassKind::Emit`。默认 CPU 流程可以由 named pipeline preset 或普通 Python function 展开成
  pass list，但 preset 本身不是 pass，也不保存隐藏状态；展开后仍由同一个 manager 逐 pass 执行。
- `run_grhsim_pass` 和 `run_grhsim_pipeline` 返回 `PipelineResult`；大 artifact 只写磁盘，result
  中只保存 `ArtifactRecord`。

### 13.3 Python 编排与 C++ 执行

Python 负责选择 pass、参数和顺序；C++ manager 负责 `PassKind` 权限、revision、mapping 失效、
验证和 artifact 提交。Python 实现的 pass 可以满足相同 protocol，但必须操作 opaque editor/
sink，不能绕过 manager 直接写 model 内存或自行提交目标文件。Load/store 由 native model
reader/writer 完成，不把完整 JSON 或模型 table 强制物化到 Python。

## 14. Load、Store 与序列化

Load/store 是 model 的持久化边界，不是 backend build/emit 的别名。Load 没有输入 model，需要
创建并原子安装 session ownership；store 写的是可再次 load 的规范 GrhSIM bundle，而不是某个
backend artifact。因此二者使用成对的 session API，不注册伪装成 transform 的 pass。

### 14.1 Bundle schema

GrhSIM 使用与 GRH JSON 不同的格式：

```text
format: wolvrix.grhsim.v1
counts                    # 各 table 与 flat pool 的声明数量
semantic_dialects
interface
I/O/S/F/G/Init
semantic_fingerprint
mappings?                 # 由 store policy 决定
origins?                  # 由 store policy 决定
```

规则：

- 不序列化 raw pointer、进程级 registry index、`ModelIdentity`、revision、DefUseIndex、SCC 等
  进程内状态；
- 实体 ID 使用 bundle 内稠密索引；type/op 通过 bundle 内 type/string table 间接引用稳定的 dialect
  textual reference 和参数。Reader 必须重新绑定 registry 并检查 ID 连续性，不能把 bundle ID
  当作进程级 registry ID；
- `counts` 至少覆盖 string/dialect/type/object/value/op、operand/result/object-ref/parameter pool、
  Init 和 mapping，用于 reader 在读 payload 前检查范围并一次性 reserve；payload 完成后逐项核对；
- semantic fingerprint 只覆盖决定模型语义的字段，不受 origins、mapping 或 JSON 排版影响；
- 每个序列化 mapping 记录 semantic fingerprint、semantic/backend dialect manifest、backend
  version、configuration fingerprint、status 和 payload；
- JSON writer 输出稳定字段和实体顺序，便于 diff；
- 超大模型后续可以增加等价二进制编码，但 JSON/二进制共享同一逻辑 schema、fingerprint 和
  verifier。

### 14.2 Load

Native reader 只负责构造尚未发布的 model；session adapter 负责 key 的原子安装：

```cpp
struct ModelLoadOptions {
    bool loadMappings = true;
    std::vector<BackendId> backends; // empty means all bundled backends
};

ModelLoadResult loadGrhSimModel(const std::filesystem::path& path,
                                const ModelLoadOptions& options,
                                const DialectRegistry& dialects,
                                const BackendRegistry& backends,
                                ModelIoDiagnostics& diagnostics);
```

```python
sess.load_grhsim(
    path,
    *,
    out_model="grhsim.main",
    load_mappings=True,
    backends=None,
    replace=False,
)
```

固定流程：

1. 读取 header、schema version、实体数量和 dialect manifests，先检查整数溢出、资源上限和方言
   可用性；
2. 在 session 外构造临时 `GrhSimModel`，解析 textual reference 并预留紧凑 storage；
3. 校验 semantic fingerprint，运行 full structural/semantic verifier；
4. `load_mappings=True` 时，对每个 mapping 校验 fingerprint、dialect/backend version 和结构；标为
   complete 的 mapping 还要通过 complete verifier；任一失败则整个 load 失败；
5. 为 model 创建新的 runtime `ModelIdentity`，把 semantic/metadata revision 初始化为 1，并把
   已验证 mapping 重新绑定到这个 identity/revision；
6. 全部成功后才插入 `out_model`。`replace=True` 时也只在最后一步替换旧对象。

`load_mappings=False` 会跳过全部 mapping payload，只加载 semantic model 和 origins；`backends`
用于只加载选定 backend，`None` 表示 bundle 中的全部 backend。普通 load 遇到未知 semantic
dialect 必须失败；仅查看未知 bundle 应使用不创建 `GrhSimModel` 的 inspection API，不能把
opaque payload 放进可运行 model。

任何失败都销毁临时 model，保持 session 原 key 和已有 model 不变，不发布 partial model。

### 14.3 Store

```cpp
enum class MappingStorePolicy { None, Complete, All };

struct ModelStoreOptions {
    MappingStorePolicy mappings = MappingStorePolicy::Complete;
    std::vector<BackendId> backends; // empty means all mappings
    bool includeOrigins = true;
};

ModelStoreResult storeGrhSimModel(const GrhSimModel& model,
                                  const std::filesystem::path& output,
                                  const ModelStoreOptions& options,
                                  ModelIoDiagnostics& diagnostics);
```

```python
sess.store_grhsim(
    *,
    model="grhsim.main",
    output="build/main.grhsim.json",
    mappings="complete",       # "none" | "complete" | "all"
    backends=None,
    include_origins=True,
)
```

三个 mapping policy 的含义为：

- `none`：只保存 semantic model；
- `complete`：选择所有标为 complete 的 mapping，并要求它们逐一通过 complete verifier；合法
  partial mapping 不写出；这是默认值；
- `all`：选择所有 mapping；partial mapping 必须通过 structural verifier，complete mapping 还必须
  通过 complete verifier。

`backends=None` 表示在 mapping policy 允许的范围内保存全部 backend；显式列表只保存选中的
backend。请求不存在、失效或不满足所选 policy 的 mapping 必须报错，不能静默换成其他 mapping。

Store 在整个 fingerprint/编码过程持有 model 的 read lock，禁止并发 writer，以一份主模型直接
流式写出，不为一致性快照 deep clone。写出前必须确认 model 非 poisoned 并通过 full semantic
verify；被选中的 mapping 按 policy 验证。`include_origins=False` 只裁掉非语义 provenance，不改变
semantic fingerprint。

Writer 在目标目录创建临时文件，完成编码、flush/close 和最终校验后原子 rename。失败时删除
临时文件并保留既有目标文件；store 不改变任何 revision。文件、目录和 rename 失败都通过统一
diagnostics 返回。

### 14.4 大模型 I/O

- Reader 使用 streaming/SAX 风格解析并直接填充预留 table/pool，不能先构造完整 JSON DOM；
- writer 直接遍历 slot table/flat pool 流式编码，不能把完整 JSON string 留在内存；
- 声明的实体数量、range 和 blob 大小在 reserve 前执行可配置上限与溢出检查；
- load/store 分别报告 persistent model bytes、peak parser/writer scratch、读写字节数和各阶段耗时；
- round-trip 必须保持 semantic fingerprint；若包含 mapping，还必须保持其 configuration fingerprint
  和 partial/complete status。

## 15. Verifier 与诊断

### 15.1 验证级别

```text
Local verification
  editor 单次操作的 ID、类型和 schema 检查

Structural verification
  ID/ref、def-use、唯一 producer、range、Init 覆盖和 mapping 引用检查

Semantic verification
  dialect op/type/init、确定写入、事件、外部调用和 E 可推导性检查

Backend complete verification
  mapping 覆盖、布局、分区、调度和 backend capability 检查
```

默认策略：

- pipeline 入口运行一次 full structural verify；不在每个 pass 前重复 O(N) 全图扫描。
- 每个 pass 后根据 editor dirty set 运行 incremental structural verify；pipeline 边界再次运行
  full structural verify。
- semantic pass 后对受影响实体运行 dialect semantic verify；lowering、正常 load 完成、store 和
  emit pass 边界运行 full semantic verify。
- backend pass 后运行该 mapping 的 structural verify。
- descriptor 要求 complete mapping 的 pass（特别是 emit pass）运行前无条件执行对应 backend
  complete verify；store 选择 complete mapping 时同样执行。

### 15.2 诊断上下文

每条诊断至少包含：

- pass 名；
- model 名和 semantic revision；
- GrhSIM entity kind/ID；
- dialect op/type 名；
- 可用时的 GRH graph/entity、层次路径和 `SourceLocation`；
- mapping/backend/partition/task ID（后端错误）。

诊断系统可以复用现有 diagnostics/logging 基础类，但 GrhSIM diagnostics 类型和 context formatter
独立实现。

## 16. 与当前实现的迁移

### 16.1 兼容原则

迁移期保留现有：

```python
sess.emit_grhsim_cpp(design="design.main", ...)
```

最终它变成兼容门面：

```text
GRH precondition check
  -> lower to temporary GrhSimModel
  -> run cpu.data-layout / cpu.partition / cpu.schedule
  -> run cpu.emit-cpp
```

显式的新 API 使用 `run_grhsim_pipeline(model=..., passes=...)`。兼容门面稳定后再弃用 `design=`
入口。

### 16.2 禁止的迁移方式

- 不实现 `GrhSimModel -> temporary GRH -> old emitter` 的长期回转路径。
- 不让新 GrhSIM pass 继续把核心结果写入旧 `SessionStore`。
- 不让 old activity schedule 与新 CPU mapping 成为两个同时可修改的真源。
- 不为了复用旧 emitter 而在 GrhSIM node 中保留 `grh::Operation*`。

### 16.3 分阶段路线

#### M0：冻结契约

- 更新 pass 正式文档：从不可变返回值改为原地 mutation。
- 把 mapping 失效从对象同一性改为 model identity + semantic revision。
- 明确 emit 是 `PassKind::Emit`，并删除独立 build/emit 基础入口。
- 明确 `PassRegistry` 与 dialect/backend registry 相互独立，名称前缀只表示 provider。
- 明确 pass 失败后的 poisoned model 规则。
- 补齐 interface/inout、event-history 初始行为、effect 顺序和 CPU schedule 执行计划中的阻塞语义。

#### M1：IR kernel

- 实现 typed ID、slot table、flat pool、interner、对象表和 `SimGraph`。
- 实现只读 view、`ModelEditor`、revision 和 structural verifier。
- 加入 record/pool 内存统计与 compact-storage。

#### M2：Dialect 与序列化

- 实现 dialect registry/manifest。
- 注册 core 类型、InitSpec 和最小 op 集。
- 实现流式 GrhSIM JSON v1 reader/writer、session `load_grhsim`/`store_grhsim` 和 semantic verifier。
- 验证 load 原子发布、store 原子替换、mapping policy、新 runtime identity/revision 和稳定 fingerprint。

#### M3：GRH lowering

- 实现单 top flattened GRH 到 core model 的转换。
- 建立 interface/origin 映射。
- 提供 session `lower_grhsim(..., consume=...)`。
- 用小型 reference interpreter 验证 `eval_G`。

#### M4：原地 pass 框架

- 实现独立 pass manager、pass registry、analysis manager、`ArtifactSink` 和 Python binding。
- 移植第一批简单 semantic pass，验证 revision/mapping invalidation。
- 建立失败、poison、compaction 和大图内存测试。

#### M5：CPU mapping

- 实现 CPU mapping envelope、data layout、partition、schedule pass 和 verifier。
- 把当前 activity schedule 的 correctness-critical 结果物化进 CPU mapping。
- 在迁移期提供只读 legacy schedule adapter，但只允许一个方向生成新 mapping。

#### M6：CPU emit pass

- 提取/改造现有 `grhsim_cpp.cpp` 中可复用的表达式和 runtime 生成逻辑。
- 注册 `cpu.emit-cpp`，只读接受 GrhSIM model + complete CPU mapping，并通过 `ArtifactSink` 输出。
- 对同一 GRH 输入并行生成 legacy/new 产物，做执行结果和波形差分。
- 回归稳定后移除新 emit pass 对 GRH session schedule 的依赖。

## 17. 测试与验收

### 17.1 单元测试

- ID 创建、删除、slot 复用和 stale generation 拒绝。
- editor 对 operand/result/object ref 的更新及 def-use 重建。
- state 增删时 `Init` 全映射维护。
- semantic pass changed/no-change 的 revision 行为。
- semantic mutation 后所有 mapping 被释放。
- backend-only pass 不增加 semantic revision。
- partial/complete mapping 验证。
- 五种 `PassKind` 的 editor/sink 权限隔离和非法组合拒绝。
- pass registry 与 dialect registry 独立注册、缺失依赖和版本不匹配诊断。
- emit pass 的 complete mapping 前置验证、只读保证、artifact metadata 和失败清理。
- poisoned model 拒绝继续执行。
- dialect schema、未知 dialect 和版本不匹配诊断。
- JSON round-trip 保持模型语义和稳定输出。

### 17.2 Load/store 测试

至少覆盖：

- semantic-only、complete mappings 和包含 partial mappings 三种 round-trip；
- load 后生成新 model identity、revision 从 1 开始、mapping 正确重绑；
- `load_mappings=False` 跳过 mapping payload；
- fingerprint、schema、dialect/backend version 和 mapping payload 损坏的拒绝路径；
- load 失败及 `replace=True` 失败时原 session key 保持不变；
- store 失败时旧目标文件保持不变且临时文件被清理；
- `include_origins=False` 不改变 semantic fingerprint；
- 10M op 级 bundle 的 streaming I/O 峰值内存没有完整 DOM/string 副本。

### 17.3 Lowering 测试

至少覆盖：

- input/output/inout；
- 组合 op 的 operand/result/parameter 保持；
- register/latch/memory 的 state 与 Init；
- 多步骤 memory init；
- event-history 创建和 first-eval 行为；
- system function/task；
- DPI import/call 方向和结果顺序；
- unsupported op、未 flatten hierarchy、非法写冲突的失败诊断。

### 17.4 差分测试

建立三层 oracle：

```text
小图 GRH/现有 grhsim-cpp
          vs GrhSIM reference interpreter
          vs GrhSIM CPU generated code
```

对相同输入 trace 比较公开输出、持久状态、event 触发和可观察 effect trace。之后逐步扩大到
HDLBits、OpenC910 和 XiangShan。

### 17.5 内存验收

每个里程碑记录：

- model bytes/op；
- model bytes/value；
- operand/result/object-ref/parameter pool 大小；
- lowering 峰值 RSS；
- load/store 峰值 RSS 和 parser/writer scratch；
- 每个 pass 的峰值额外 RSS；
- dead range 比例和 compaction 前后变化；
- mapping 各分量大小；
- semantic mutation 后 mapping 内存是否立即释放。

首版不先拍脑袋冻结单 record 字节上限，但必须满足：

- 正常 semantic pass 不发生 O(model size) 的模型复制；
- no-change pass 不分配新的主 IR storage；
- mapping 失效后其 payload 可立即回收；
- synthetic 10M op/12M value 模型可以完成构建、一次 no-op pass、一次局部 rewrite、store/load 和
  verify；
- `consume=True` 后 session 不再同时持有完整 GRH 与 GrhSIM。

## 18. 正式语义文档的前置补充

以下问题会直接影响基础数据结构或 converter，在 M0 必须明确：

1. `InputObject/OutputObject/StateObject` 的名字、模型名和 inout 分组属于正式 model 字段还是
   非语义 interface metadata。
2. GRH Logic 到 `core.logic<..., domain>` 的 domain 从何处取得，2-state 优化在 lowering 前还是
   lowering 后执行。
3. event-history 在第一次 `eval()` 前的精确状态；不能仅规定“转换任选合法初值”。
4. 无 result 的 system task/DPI 等可观察操作如何表达必需顺序；若采用 effect token，需要加入
   core dialect schema。
5. 外部函数、随机数、文件等环境状态如何与 `eval_G : (I, S) -> (O, S)` 的确定性声明兼容。
6. `memWriteSeq` 是 GRH lowering 的多对一规则，还是一对一 lowering 后的 GrhSIM semantic pass。
7. CPU `SchedulePlan` 如何表达 fixed-point round、compute/commit phase、activation fanout 和
   convergence；这些数据是否全部属于 mapping。
8. mapping map 是否允许同一 backend 的多个配置实例；若允许，key 应从 `BackendId` 扩展为
   `MappingId{backend, configuration}`。

这些问题不应由 C++ record 布局或 emit pass 的临时行为替正式语义做决定。

## 19. 完成定义

满足以下条件时，可以认为 GrhSIM IR 基础架构完成：

- `grhsim-ir` 核心 target 不依赖 GRH header。
- flattened GRH 可以 lowering 为独立、可 round-trip、可 full verify 的 GrhSIM model。
- semantic pass 全部原地运行，mapping 通过 revision 自动失效，无整模型隐式复制。
- Python/session 能原子 lower/load、持有、rename、运行 pipeline 和 store GrhSIM model。
- backend mapping 和 emit 只通过同一 pass manager 执行，不存在独立 `build_grhsim`/
  `emit_grhsim` 基础入口。
- `cpu.emit-cpp` 的 correctness-critical 输入全部来自 model/mapping，不再来自 GRH SessionStore，
  并返回可追踪的 artifact metadata。
- semantic-only、complete mapping 和 partial mapping bundle 均按 store policy 完成稳定 round-trip；
  load/store 失败不破坏既有 session key 或目标文件。
- reference interpreter 与 CPU backend 在代表性测试上等价。
- 10M op/12M value 规模通过既定峰值内存和 pass 时间观测。
- 旧 `emit_grhsim_cpp(design=...)` 兼容入口可由 lowering + 新 pass pipeline 实现，且已有主流程
  无需一次性迁移调用方式。

## 20. 相关文档

本草案负责基础架构和迁移规划；以下正式文档负责语义契约。M0 接受本方案后，应先消除其中已
标出的 pass、mapping 和 schedule 差异，再开始实现：

- [GrhSIM IR Overview](../../../wolvrix/docs/grhsim_ir/overview.md)
- [GrhSIM Core Dialect](../../../wolvrix/docs/grhsim_ir/dialects/core.md)
- [GrhSIM IR Pass System](../../../wolvrix/docs/grhsim_ir/passes/overview.md)
- [GrhSIM CPU Backend](../../../wolvrix/docs/grhsim_ir/backends/cpu.md)
- [GrhSIM Current Scheduling](../../../wolvrix/docs/emit/grhsim-scheduling.md)
