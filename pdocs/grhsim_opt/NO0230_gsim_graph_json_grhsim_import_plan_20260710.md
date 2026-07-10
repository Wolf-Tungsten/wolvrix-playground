# NO0230 GSim Optimized Graph JSON -> GrhSIM Import Plan

记录日期：2026-07-10

关联：[`NO0212`](./NO0212_gsim_dp_stage_structure_gain_20260702.md)、[`NO0218`](./NO0218_grhsim_compute_node_granularity_profile_20260706.md)、[`NO0221`](./NO0221_xs_gsim_grhsim_unified_stats_coremark50k_20260709.md)、[`NO0219`](./NO0219_declared_value_compute_node_boundary_plan_20260706.md)

状态：方案制定。本文只定义 GSim 导出图结构、JSON schema、GrhSIM 导入点与验证路线，不包含实现结果。

## 1. 目标

为了继续定位 GSim / GrhSIM 性能 gap，新增一条实验路径：

```text
FIRRTL -> GSim 前端优化图 -> JSON -> GrhSIM 读取 -> GRH IR -> activity-schedule -> GrhSIM emit/run
```

目标是把 GrhSIM 的 schedule / emit / runtime 放到更接近 GSim 前端图结构的输入上，隔离以下问题：

- 性能 gap 是来自 GSim 前端优化图更好，还是来自 GrhSIM activity-schedule / emit / runtime 自身；
- GSim 的 node / ENode / state 粒度转成 GRH 后，GrhSIM 的 boundary activation、checks、commit hotspot 是否仍存在；
- 尽可能保留 GSim 符号和节点来源，方便后续 waveform、static/runtime stats、热点 supernode 反查。

## 2. 导出阶段选择

主方案的导出点定义为：

```text
PreGraphPartition = CommonExpr -> RemoveDeadNodes 之后，graphPartition() 之前
```

对应当前 GSim main flow：

```text
Init
SplitArray
DetectLoop
TopoSort
InferAllWidth
RemoveDeadNodes
ExprOpt
UsedBits
SplitNodes
RemoveDeadNodes1
ConstantAnalysis
RemoveDeadNodes
AliasAnalysis
PatternDetect
CommonExpr
RemoveDeadNodes
<export PreGraphPartition JSON>
graphPartition
Replication
GenerateStmtTree
InstsGenerator
Final
```

理由：

- 这是“最贴近 supernode 建立但尚未建立”的优化后图：GSim 已完成前端图优化、常量/死节点/别名/公共表达式处理，但还没有进入 `graphPartition()` 的 supernode coarsen / DP / refine。
- GrhSIM 读取后仍要在 `activity-schedule` 前转换成 GRH IR，让现有 activity-schedule 负责 compute / commit 划分，而不是直接导入 GSim 最终 supernode。
- 若导出点放在 `DpProfileAfterCoarsen` 或 `DpProfileAfterInitPartition`，JSON 会混入 GSim supernode partition 决策，难以判断 GrhSIM activity-schedule 是否能独立复现收益。

可选扩展：同一 schema 支持 `DpProfileAfterCoarsen` / `DpProfileAfterInitPartition` snapshot，字段中带 `supernodes`。这些 snapshot 用于对照和诊断，不作为第一版 GrhSIM import 默认输入。

## 3. 总体设计原则

1. **GSim JSON 贴近 GSim 自身结构。** 导出 `Node`、`ENode`、`ExpTree`、node edge、dep edge、state/port/member 信息；不直接导出 wolvrix GRH JSON。
2. **GrhSIM 读取时转换成 GRH IR。** importer 是明确的 translation layer，把 GSim node / expression tree 映射为 `OperationKind`、`Value`、ports、state declarations 和 declared symbols。
3. **符号信息优先保留。** 所有 GSim `Node::name` 进入 string table；能判定为 RTL 声明或可调试对象的 symbol 进入 `declared_symbols`，由 GRH `graph.addDeclaredSymbol()` 承接。
4. **ID 稳定且可 join。** 节点、表达式节点、tree、symbol 都使用 JSON 内稳定整数 ID；不要用指针地址。后续 stats 可用 `gsim_node_id` / `gsim_enode_id` / `grh_symbol` join。
5. **大设计可承载。** XiangShan JSON 预计很大，默认用 compact JSON + string table，避免在每条 edge 中重复长路径名。

## 4. JSON 顶层 schema

格式名：

```text
gsim.optimized-graph.v1
```

顶层结构：

```json
{
  "format": "gsim.optimized-graph.v1",
  "producer": {
    "tool": "gsim",
    "version": "UNKNOWN",
    "command": "gsim ...",
    "input": "SimTop.fir"
  },
  "stage": {
    "name": "PreGraphPartition",
    "after": "RemoveDeadNodesBeforeGraphPartition",
    "before": "graphPartition",
    "supernodes_materialized": false
  },
  "top": "SimTop",
  "separators": {
    "module": "__DOT__",
    "aggregate": "__DOT__"
  },
  "summary": {},
  "symbols": [],
  "declared_symbols": [],
  "ports": {},
  "states": [],
  "nodes": [],
  "enodes": [],
  "expr_trees": [],
  "edges": {},
  "supernodes": []
}
```

`supernodes` 在 `PreGraphPartition` 默认为空；若导出 DP stage snapshot，则填充当前 GSim supernode 分组和 supernode edge。

## 5. Symbol table

### 5.1 字段

```json
{
  "sid": 42,
  "name": "core__DOT__frontend__DOT__icache__DOT__valid_0",
  "kind": "state",
  "declared": true,
  "declared_reason": "node_state",
  "source": {
    "node": 10021,
    "field": "name"
  },
  "aliases": [
    {
      "kind": "gsim_raw",
      "name": "core$frontend$icache$valid_0"
    }
  ]
}
```

字段含义：

| 字段 | 含义 |
| --- | --- |
| `sid` | JSON 内 symbol id，数组内唯一 |
| `name` | importer 创建 GRH symbol 时使用的主名字 |
| `kind` | `port` / `state` / `memory` / `node` / `expr` / `internal` / `debug` |
| `declared` | 是否应进入 GRH `declaredSymbols` |
| `declared_reason` | `port` / `node_state` / `memory` / `named_wire` / `debug_keep` / `manual` |
| `source` | 来源 node / enode / tree，便于反查 |
| `aliases` | 原始 GSim 名、分隔符转换前名字、后续 normalize 名 |

### 5.2 declared symbol 策略

第一版采用保守保留：

- ports：`NODE_INP`、`NODE_OUT`、`NODE_EXT_IN`、`NODE_EXT_OUT`；
- state：`NODE_REG_SRC` / `NODE_REG_DST` 的 canonical register symbol、`NODE_MEMORY`；
- memory port：`NODE_READER`、`NODE_WRITER`、`NODE_READWRITER` 的 port symbol；
- named compute node：有稳定 `Node::name` 且不是 importer 合成临时值的 `NODE_OTHERS`；
- debug keep：后续可由 `--gsim-graph-declared-filter=` 控制的额外符号。

不把每个 ENode synthetic symbol 默认 declared。ENode 需要 symbol 以构造 GRH op/value，但这些 symbol 应标记为 `internal`，避免重现 `NO0219` declared hard boundary seed 爆炸问题。

GRH 承接规则：

```text
for sid in declared_symbols:
    sym = graph.internSymbol(symbols[sid].name)
    graph.addDeclaredSymbol(sym)
```

同时，每个由 importer 创建的 value / op 都记录来源属性：

```text
gsim.node_id
gsim.enode_id
gsim.tree_id
gsim.symbol_sid
gsim.node_type
gsim.op_type
```

这些属性不替代 declared symbol，只用于 diagnostics / stats join。

## 6. Node schema

```json
{
  "id": 10021,
  "name": 42,
  "type": "NODE_REG_SRC",
  "status": "VALID_NODE",
  "width": 1,
  "signed": false,
  "used_bit": 1,
  "dimensions": [],
  "order": 8112,
  "lineno": 123456,
  "parent": null,
  "members": [],
  "clock": 88,
  "reset": "UINTRESET",
  "as_reset": "EMPTY",
  "reg_next": 10022,
  "trees": {
    "assign": [],
    "val": null,
    "reset": 701,
    "reset_cond": 702,
    "reset_val": 703,
    "mem": null
  },
  "memory": null
}
```

`name` 引用 `symbols[].sid`。没有稳定名字的 node 可以省略 `name`，importer 生成 `gsim.node.<id>` 内部 symbol。

memory node / port 补充字段：

```json
{
  "memory": {
    "depth": 2048,
    "rlatency": 0,
    "wlatency": 1,
    "member_role": null,
    "parent_memory": null
  }
}
```

memory port member 继续用 `members` 表达，并由 importer 按 GSim 枚举解释：

- `NODE_READER`: `addr` / `en` / `clk` / `data`
- `NODE_WRITER`: `addr` / `en` / `clk` / `data` / `mask`
- `NODE_READWRITER`: `addr` / `en` / `clk` / `rdata` / `wdata` / `wmask` / `wmode`

## 7. ENode / ExpTree schema

ENode 是全局表，tree 只引用 root / lvalue：

```json
{
  "id": 90001,
  "op": "OP_ADD",
  "width": 8,
  "signed": false,
  "is_clock": false,
  "reset": "UNCERTAIN",
  "node_ref": null,
  "memory_node": null,
  "values": [],
  "str_val": "",
  "children": [90002, 90003]
}
```

leaf node reference：

```json
{
  "id": 90002,
  "op": "OP_EMPTY",
  "width": 8,
  "signed": false,
  "node_ref": 10021,
  "children": []
}
```

constant：

```json
{
  "id": 90003,
  "op": "OP_INT",
  "width": 8,
  "signed": false,
  "values": [255],
  "str_val": "hff",
  "children": []
}
```

tree：

```json
{
  "id": 701,
  "owner_node": 10022,
  "slot": "assign[0]",
  "root": 90001,
  "lvalue": 90004
}
```

设计选择：

- ENode ID 全局唯一，便于不同 node / tree 共享 common expression；
- `node_ref` 保留 GSim 叶子引用，不提前改写为 GRH value；
- `OP_READ_MEM` 保留为 ENode op，importer 再映射为 GRH `kMemoryReadPort`；
- `OP_STMT_*` 理论上不应出现在 `PreGraphPartition`，若出现第一版 importer 直接报 unsupported。

## 8. Edge schema

node-level graph edge：

```json
{
  "edges": {
    "next": [[1, 2], [2, 3]],
    "dep": [[10, 20]]
  }
}
```

含义：

- `next` 对应 GSim `Node::next`；
- `dep` 对应 GSim `depNext`，用于表达非 adjacent 的激活清理依赖；
- importer 第一版不直接把 `next` 当 GRH data edge，而是用于校验 expression tree 推导出的 value users 是否覆盖 GSim dependence；
- `activity-schedule` 的真实依赖仍从 GRH value def-use、state read/write 关系重建。

可选 supernode snapshot：

```json
{
  "supernodes": [
    {
      "id": 1234,
      "order": 567,
      "members": [1, 2, 3],
      "next": [1235, 1240],
      "dep_next": []
    }
  ]
}
```

`PreGraphPartition` 不依赖此字段。导出 DP stage 时可填充，用于与 `NO0212` 统计口径对齐。

## 9. GSim -> GRH IR 映射

### 9.1 state / ports

| GSim | GRH |
| --- | --- |
| `NODE_INP` / `NODE_EXT_IN` | input `Value` + input port |
| `NODE_OUT` / `NODE_EXT_OUT` | output `Value` + output port |
| `NODE_REG_SRC` + `NODE_REG_DST` pair | `kRegister` declaration + read/write ports |
| `NODE_MEMORY` | `kMemory` declaration |
| `NODE_READER` | `kMemoryReadPort` |
| `NODE_WRITER` | `kMemoryWritePort` |
| `NODE_READWRITER` | read side `kMemoryReadPort` + write side `kMemoryWritePort` |

register canonical symbol：

```text
if NODE_REG_SRC.reg_next points to NODE_REG_DST:
    state symbol = common normalized register name
else:
    state symbol = current node name
```

importer 必须保留 `EMPTY_REG` / `CONSTANT_NODE` 等 status 信息。第一版只导入 `VALID_NODE` 和必要的 empty reg state；其他 status 默认报错或按 diagnostics 记录后跳过，避免静默语义偏差。

### 9.2 expression op

| GSim OPType | GRH OperationKind |
| --- | --- |
| `OP_INT` | `kConstant` |
| `OP_ADD` / `OP_SUB` / `OP_MUL` / `OP_DIV` / `OP_REM` | `kAdd` / `kSub` / `kMul` / `kDiv` / `kMod` |
| `OP_LT` / `OP_LEQ` / `OP_GT` / `OP_GEQ` / `OP_EQ` / `OP_NEQ` | compare ops |
| `OP_AND` / `OP_OR` / `OP_XOR` / `OP_NOT` | bitwise ops |
| `OP_ANDR` / `OP_ORR` / `OP_XORR` | reduce ops |
| `OP_DSHL` / `OP_DSHR` / `OP_SHL` / `OP_SHR` | dynamic/static shift |
| `OP_HEAD` / `OP_TAIL` / `OP_BITS` / `OP_BITS_NOSHIFT` | `kSliceStatic` |
| `OP_INDEX_INT` / `OP_INDEX` | `kSliceArray` / `kSliceDynamic` as applicable |
| `OP_CAT` / `OP_GROUP` | `kConcat` |
| `OP_MUX` / lowered `OP_WHEN` | `kMux` |
| `OP_ASUINT` / `OP_ASSINT` / `OP_CVT` / `OP_PAD` / `OP_SEXT` | cast/assign/sign-extension lowering using existing GRH attrs |
| `OP_READ_MEM` | `kMemoryReadPort` |
| `OP_EXT_FUNC` | `kDpicCall` or unsupported, depending on target metadata |

Unsupported in first bring-up:

- `OP_PRINTF` / `OP_ASSERT` / `OP_EXIT`：需要单独 side-effect model；
- `OP_STMT_SEQ` / `OP_STMT_WHEN` / `OP_STMT_NODE`：不应出现在默认导出点；
- `OP_WRITE_MEM` as expression：应由 memory writer node 处理，若仍在 expression 内先报错。

### 9.3 value construction

ENode 转 GRH 时按 expression DAG memoize：

```text
memo[(tree_id, enode_id)] -> ValueId
```

规则：

- `node_ref` leaf：返回对应 GSim node 的 current value；
- `OP_INT`：创建 `kConstant` op 和 result value；
- normal op：递归转换 child value，创建 GRH op 和 result value；
- owner node assignment：把 root value connect 到 owner node value，按 owner node type 生成 assign / state write / output drive。

如果同一个 ENode 对象被多个 tree 共享，第一版可按 `enode_id` 全局 memoize；若发现 width/sign/context 会改变语义，则退回 `(tree_id, enode_id)` memoize，并在 stats 中记录 duplication。

## 10. GrhSIM 接入点

第一版必须直接实现 C++ loader，不能使用 Python 中间转换。XiangShan 优化图 JSON 规模会很大，Python `json.load -> 生成 GRH JSON -> read_json_file` 会把内存放大到不可控，并且会把首轮问题变成 Python 转换器吞吐问题，而不是 GSim 图到 GRH IR 的真实接入问题。

新增 wolvrix C++ loader：

```text
wolvrix/lib/core/load_gsim_graph.cpp
wolvrix/include/core/load_gsim_graph.hpp
```

loader 要求：

- 复用或抽出当前 `load.cpp` 的 JSON tokenizer / parser 基础设施，但为 GSim graph schema 单独做 schema reader；
- 对 `symbols` / `nodes` / `enodes` / `expr_trees` 建紧凑索引，不构造二次 JSON DOM；
- 用 string interning 承接 symbol table，长路径名只保留一份；
- 解析和 GRH 构造分阶段执行：先建 symbol/node/enode 索引，再转换 state/ports，再转换 expression tree；
- diagnostics 必须能报告 `gsim.node_id` / `gsim.enode_id` / `gsim.tree_id`，方便从大 JSON 中定位问题；
- P0 即以完整 XiangShan JSON 可读取为目标设计内存占用，不接受“小 case Python bridge 先跑”的路径。

Python session API：

```python
sess.read_gsim_graph_json_file(path, out_design="design.main")
```

XS wrapper 增加环境变量：

```text
WOLVRIX_XS_GRHSIM_GSIM_GRAPH_JSON=/path/to/SimTop_PreGraphPartition.json
```

流程：

```text
if WOLVRIX_XS_GRHSIM_GSIM_GRAPH_JSON is set:
    read_gsim_graph_json_file(...)
    skip read_sv
    skip pre_sched_pipeline
    skip reg_to_mem_pipeline
    run activity-schedule
    emit_grhsim_cpp
else:
    keep current flow
```

理由：GSim JSON 已经是 GSim 前端优化后的图，不能再套 wolvrix 的 `hier-flatten` / `simplify` / `reg-to-mem`，否则会混入两套前端优化。

## 11. GSim 导出实现

新增命令行：

```text
--dump-optimized-graph-json=/path/to/out.json
--dump-optimized-graph-stage=PreGraphPartition
```

或复用 stage 机制：

```text
--dump-json --dump-stages=PreGraphPartition --stop-after-stage=PreGraphPartition
```

建议新增显式选项，不复用当前 `--dump-json` 的轻量调试格式，避免 schema 语义混淆。

实现位置：

- `reference/gsim/include/config.h`：新增输出路径与 schema 选择；
- `reference/gsim/src/main.cpp`：在最后一次 `RemoveDeadNodes` 后、`graphPartition()` 前插入 `PreGraphPartition` boundary；
- `reference/gsim/src/GraphDumper.cpp`：保留旧 `GraphJsonDumper`，新增 `OptimizedGraphJsonDumper`；
- writer 使用 streaming 输出，不先构造完整 JSON DOM。

## 12. 验证 gate

### Gate A：schema 自洽

- JSON 可 parse；
- `symbols.sid`、`nodes.id`、`enodes.id`、`expr_trees.id` 唯一；
- 所有 node / enode / tree / edge 引用存在；
- `declared_symbols` 都能解析到 symbol table；
- `summary` 中 node/enode/tree/edge 计数与数组实际大小一致。

### Gate B：importer 单测

最小 case：

- combinational add/mux/slice/concat；
- register read/write/reset；
- memory read/write/readwrite；
- input/output/inout；
- constant and common expression；
- unsupported side-effect op 触发清晰 diagnostics。

### Gate C：结构对齐

对同一 GSim JSON：

- 导入后的 GRH `operation_kinds` 与 GSim `node_types` / `op_types` bucket 对齐；
- declared symbol 数、port 数、state 数与 GSim summary 对齐；
- `activity_schedule_supernode_stats.json` 可生成；
- `gsim_node_id -> grh op/value` 反查覆盖率达到阈值。

### Gate D：GSim 行为对齐

HDLBits small cases 不作为本路线的验证对象。原因是这些 case 当前没有对应 Chisel/FIRRTL 版本，GSim 不能直接消化；把它们纳入 gate 会把问题变成“如何给 HDLBits 造一条 GSim 输入链”，偏离本方案。

验证对象必须满足：

- 能由 GSim 原生 flow 读取并生成 emu；
- 使用与导出 JSON 完全相同的 FIRRTL 输入和 GSim 参数；
- 符合 GSim 的单时钟假设。多时钟/异步行为不作为 P0 correctness 目标。

逐级跑：

```text
GSim 可消化的 Chisel/FIRRTL micro cases
xs-components selected FIRRTL cases
XiangShan 2k smoke against native GSim
XiangShan CoreMark 50k against native GSim
```

行为对齐口径：

- golden 是同一输入、同一 GSim 单时钟语义下的 GSim 原生 emu；
- GrhSIM importer 路径只要求对齐 GSim 行为，不要求对齐当前 SV/GRH flow 的多时钟或 Verilator 语义；
- Verilator / 当前 GrhSIM SV flow 只可作为额外 sanity，不作为本路线 P0 pass/fail 判据。

### Gate E：性能诊断

导入路径生成的 GrhSIM 与当前 GrhSIM 对比：

- static supernodes、activation edges、activation checks；
- runtime activation_count、weighted checks、weighted edges；
- commit hotspot 是否消失或转移；
- host time 是否向 GSim 靠拢。

如果 GSim JSON import 后 GrhSIM 仍慢，则 gap 更可能在 activity-schedule / emit / runtime；如果明显加速，则前端 IR 形态是主因。

## 13. 风险与处理

| 风险 | 处理 |
| --- | --- |
| GSim `Node` / `ENode` 语义不完整，无法恢复 GRH | 第一版先 fail-fast，列 unsupported op/node；不要静默近似 |
| memory readwrite port 语义映射错误 | 单独 gate `NODE_READER` / `NODE_WRITER` / `NODE_READWRITER`，对照 GSim generated C++ |
| declared symbol 太多导致 activity-schedule seed 变细 | `declared_symbols` 只保留调试必要对象；ENode synthetic 不 declared；提供 filter |
| JSON 过大 | GSim 侧 string table + integer refs + compact mode；GrhSIM 侧第一版即 C++ loader + 紧凑索引；必要时支持 `.json.zst` 作为传输格式，但逻辑格式仍是 JSON |
| GSim separator 与 GRH symbol 不一致 | JSON 同时保存 raw alias 和 importer name；XS flow 默认使用 `--sep-mod=__DOT__ --sep-aggr=__DOT__` |
| side-effect op 尚未支持 | 第一版先跳过不含 side-effect 的 subset，XiangShan 若必须支持再单独补 `SystemTask` / `DpicCall` 映射 |

## 14. 实施顺序

1. GSim 增加 `PreGraphPartition` stage boundary 和 `OptimizedGraphJsonDumper`，先只导出 `symbols/nodes/enodes/expr_trees/edges/summary`。
2. 在 wolvrix 中新增 C++ `LoadGSimGraphJson`，先实现 schema parse、紧凑索引和 ref check；validator 直接复用 loader diagnostics。
3. 在 C++ loader 内实现最小 importer，把 combinational + register + memory subset 转成 GRH design。
4. 接 Python API 和 `WOLVRIX_XS_GRHSIM_GSIM_GRAPH_JSON`，跑 `activity-schedule` stop-after gate。
5. 补 declared symbol 承接和 source attrs，接 stats join。
6. 扩到 GSim 可消化的 FIRRTL micro cases、xs-components 和 XiangShan smoke，补 unsupported op，并始终以 native GSim 行为为 golden。
7. 跑 CoreMark 50k，和 `NO0221` 统一 JSON stats 做同口径对比。

第一版成功标准：

```text
GSim PreGraphPartition JSON -> GrhSIM importer -> activity-schedule -> emit
能在至少一个 GSim 可消化的 xs-components/FIRRTL case 上对齐 native GSim 行为，并能输出 declared-symbol 可反查的 stats。
```

XiangShan 50k 作为第二阶段 gate，不应阻塞 schema 和 importer P0 落地。

## 15. 增量更新 2026-07-10：GSim 导出 P0 已落地

本次已先落实 GSim 侧 optimized graph JSON 导出，不包含 GrhSIM C++ loader。

代码改动位于 `reference/gsim`：

- `include/config.h`：新增 `DumpOptimizedGraphJson`、`OptimizedGraphJsonPath`、`OptimizedGraphJsonStage`。
- `include/graph.h`：新增 `graph::dumpOptimizedGraphJson(...)`。
- `src/main.cpp`：新增 CLI，并在最后一次 `RemoveDeadNodes` 后、`graphPartition()` 前插入 `PreGraphPartition` boundary。
- `src/GraphDumper.cpp`：新增 `OptimizedGraphJsonDumper`，输出 `gsim.optimized-graph.v1`。

新增 CLI：

```text
--dump-optimized-graph-json=/path/to/out.json
--dump-optimized-graph-stage=PreGraphPartition
```

当前只支持 `PreGraphPartition`。如果传入其他 stage，gsim 会直接报错：

```text
Error: --dump-optimized-graph-stage=BadStage is unsupported; only PreGraphPartition is implemented.
```

当前 JSON 已包含：

- `producer` / `stage` / `top` / `separators`
- `summary`
- `symbols` / `declared_symbols`
- `ports`
- `states`
- `nodes`
- `enodes`
- `expr_trees`
- `edges.next` / `edges.dep`
- `supernodes`（`PreGraphPartition` 下为空数组）

实现细节：

- node / enode 引用使用 GSim 原始 `Node::id` / `ENode::id`。
- `expr_trees` 使用导出器内稳定递增 ID。
- symbol table 按字符串去重，node 名字只保留一份。
- `declared_symbols` 第一版按导出侧保守策略标记 ports、register/memory state、memory port、named `NODE_OTHERS`；后续 GrhSIM loader 仍可按需求过滤。
- `edges` 直接输出 node id pair，不再重复长字符串。

验证：

```text
make -C reference/gsim build-gsim
```

结果：通过。当前环境使用 clang 22，Makefile 仅提示 clang-19 recommended。

小 FIRRTL 导出验证：

```text
reference/gsim/build/gsim/gsim \
  --dir=/tmp/gsim_opt_export_test \
  --dump-optimized-graph-json=/tmp/gsim_opt_export_test/repro-usefulreset.optimized.json \
  --stop-after-stage=PreGraphPartition \
  reference/gsim/test/repro-usefulreset.fir
```

随后用 Python `json.load` 检查：

- `format == gsim.optimized-graph.v1`
- `stage.name == PreGraphPartition`
- `summary.node_count/enode_count/expr_tree_count` 与数组长度一致
- `symbols[].sid` 连续
- `declared_symbols` 全部指向有效 symbol
- `ports/states/edges` node refs 全部存在
- `enodes[].children` refs 全部存在

该 case 结果：

```text
node_count=18
enode_count=76
expr_tree_count=25
symbol_count=18
edge_count=20
dep_edge_count=22
json_check=ok
```

下一步：实现 GrhSIM C++ `LoadGSimGraphJson`，直接读取该 schema 并转换为 GRH IR。
