# F27：原生 Node 演化、后态重放与逐 pass 对齐

历史记录：本文基于 F28 前的 source-SID／binding 模型，不能作为新叶 Node
模型的 split 支持声明。旧 schema 的离线重放、对齐、审计和一次性 benchmark
脚本及 Make 入口已清理；原生 producer 的可选 trace 设施保留，F28 新树在
未迁移的 pass／trace 入口明确拒绝。历史大型临时产物已清理，下文数字、命令
和路径记录完成时证据；当前结构及范围以 [F28](F28-semantic-tree-refactor-plan.md) 为准。

日期：2026-11-12；完整重放扩展于 2026-11-13。状态：两端整机 before＋原生 trace 的独立全字段重放，以及完整已记录 trace／终态的跨端比较均已完成。79,279,752 个后态实体和 2,321,461 条原生事件全部计入；GSIM 来源 counterpart 为 8,854,534/9,635,014（91.90%），完整联合通过仍为 0/79,279,752。已建立全节点可重放与差异证据，不代表全图语义对齐。旧 source-endpoints／fingerprint-only 全量审计保留为历史证据，不能代替新标准。本阶段全部进展统一记录在本文件，不改写 F26 的冻结结论；最终结果见第 9.6 节。

先前按 **GRH 源 SemanticTree SID → GSIM 来源端点** 测得 **8,277,942 / 8,780,799 = 94.273220%** 的来源覆盖率；这不是用户要求的“当前语义计算节点及其 op 集合”对齐率。该统计允许 GRH 的一个 wildcard 聚合视图覆盖多个 GSIM 成员，不能据此认定两端物理拆分粒度一致。详细分母、别名及剩余项见第 9.7 节，split 数量及成员粒度排查见第 9.8 节；正确的 Node 对应单位及当前实现缺口见第 9.9 节。

## 1. 目标与阶段边界

用户要求把对齐能力放进正常前序流程，使 SemanticTree 及其原生 binding 在变换后自动保留可核验的对应关系。F27 在 F26 的来源身份与绑定基础上，从 `split-static-array`／`splitArray` 建立完整节点演化：哪个对象被删除、改写、拆分或合并，为什么变化，以及如何从前态重建后态。验收包括此 pass 未拆分的标量、状态、memory 和辅助节点，不以数组成员覆盖代替全节点核验。

当前比较边界是：

```text
GRH:  ingest-firrtl → xmr-resolve → hier-flatten → comb-loop-elim
      → [before] split-static-array [after]

GSIM: parse → AST2Graph/Init
      → [before] splitArray（含 splitOptionalArray）[after]
      → detectLoop → TopoSort → InferAllWidth
```

trace 的来源、原因及前后关系由实际 pass 内部产生。分析器只消费原生 trace，不能从物理名称后缀、FIRRTL 文本或历史 split map 恢复缺失身份。原生指针生成的 split map 可以在生产者内复用，但不是分析端猜测对应的替代入口。

F26 的 post-elim 对照、F21 的历史成员集合或 F24 的动态正确性不能代替本阶段 split 前后测量。F27 当前不覆盖后续 DCE、ExprOpt、UsedBits 或后端分区的全量演化；公共 writer 和 schema 预留这些 pass 的接入能力。

### 1.1 新验收：从 before 重放完整后态

验收对象是 pass 边界的全部存活物理节点，包括标量、状态、memory、数组及辅助节点。GRH 纳入 operation、value 及 graph context；GSIM 纳入 ordinary Node 和 memory Node，其内部有序 assignment／reset 表达式以完整 DAG 记录。可推导的反向 uses、调度缓存、分配器及已经废弃的 AST 缓存不是独立语义节点，排除范围由 header 明示。parent 等父级／归属引用单列；其中既有存活 owner，也有前序转换留下的非 live owner，不能全部称为历史／dead 对象。

```text
N0 = before 库存
N1 = apply(N0, 原生 mutation 序列)    # 此步骤不得读取 after 作为变化载荷
assert N1 == 实际 after 库存          # 全 ref、全字段及依赖关系独立核验

GRH 的重放 N1／原生事件 ← 原生来源身份 → GSIM 的重放 N1／原生事件
```

这是 **pass 边界的结构重放**：记录该次执行实际提交的变化，并验证它足以重建后态；不声称重新运行 pass 算法，也不把事件理由本身当作电路行为等价的证明。两端物理粒度不同，跨端比较必须保留一对多和无法对应的节点，不能仅统计数组或有来源的节点。

这里重建的是约定库存中的节点字段载荷，并非可以直接装载执行的原生 C++ 对象快照。GSIM 的 `parent` 保留完整 typed ref；正常 memory／ext port 用它访问 owner，而 depth-one memory 转 register 后的旧 port 也可能继续指向已移出 live 库存的 owner。当前 reader 将父级／归属引用统一计入 `historical_references`，该计数名不证明它们全是历史对象，也不证明这些 owner 上下文已复原。可执行对象恢复还需要补充非 live owner 的必要上下文及缓存重建规则；本轮不将字段重放通过扩展为该结论。

新增合约在既有 schema 上显式声明 `replayContract="native-field-delta.v1"`，只允许 `inventoryScope="all-live"`。变化由正常 C++ pass 的 recorder 原生产生；Python 只负责重放、核验及输出差异。每条 mutation 关联真实 `eventSeq`，不能靠后态差分自动编造遗漏的事件或理由；未被原生事件解释的变化会使 trace 失败。

| mutation | 前置条件 | 对重放状态的作用 |
| --- | --- | --- |
| `create` | typed ref 原先不存在，`expect={}` | 以完整 `set` 新建实体 |
| `erase` | 现有完整实体等于 `expect` | 删除实体，`set={}`、`unset=[]` |
| `update` | 将覆盖／删除的旧字段精确符合 `expect` | 用 `set` 修改顶层字段，用 `unset` 删除字段，其余从 before 继承 |

`seq` 必须连续，`record/stage/ref` 不得通过字段修改，空修改和重复处分不得通过。unchanged 节点由 before 原样继承。after 仅作为独立 oracle；缺失变化、错误旧值、活跃依赖的失效引用、共享表达式同 ID 不同内容，以及额外／缺失后态节点均必须失败。正式结果见本文件末尾的重放验证记录；下文旧全量覆盖比例不等于新的重放或行为等价比例。

## 2. 三类对象必须区分

| 对象 | 标识与内容 | 能证明什么 |
| --- | --- | --- |
| 物理实体 | `ref={kind,id,generation}`；GSIM 为 `gsim-node`，GRH 为 `grh-operation` 或 `grh-value` | 同一引擎一次 pass 前后的实际实体身份；数字 ID 不能跨引擎比较 |
| 源语义端点 | `sources[]` 中的原生 token `path`、`role`、原始数组形状、字段深度、projection 与源类型 | 对应哪个 FIRRTL 源对象及哪些源成员；GRH 一个物理实体允许携带多个来源 |
| 当前物理布局 | `physical={width,signed,shape}`；GRH 可另带 `packedWidth` | 该实体当前的元素类型和未消去维度；不能拿总 packed 宽度与 GSIM 元素宽度直接比较 |

例如，源对象 `state : UInt<8>[2]` 的某成员可以表示为：

```json
{
  "ref": {"kind": "gsim-node", "id": 16, "generation": 0},
  "physical": {"width": 8, "signed": false, "shape": []},
  "sources": [{
    "path": ["state"], "role": "register-current",
    "shape": [2], "shapeFieldDepths": [0], "projection": [0],
    "width": 8, "signed": false
  }]
}
```

`projection=-1` 表示该源轴全部成员，非负值表示固定坐标。拆分后 source shape 仍为 `[2]`，成员物理 shape 为 `[]`；不能把成员的原始 source shape 也改成 `[]`。此前被消去的单元素轴同样保留在源几何中：GSIM 消去轴固定为 0，GRH 原生绑定也可保留 singleton wildcard；二者覆盖范围相同，但后者不计为具体成员。`shapeFieldDepths` 标记轴插在源字段路径的哪一层，用来区分数组与 bundle 交错布局。

memory 的存储深度与数据叶子的 source shape 分开记录。depth-one memory 转寄存器保留 `originRole=memory-storage` 和 `storageDepth`；`register-current` 与 `register-next` 仍是各自物理角色。比较存储来源时可以归并 current 的 originRole，不能把 next 再算成第二份存储。

## 3. 统一 JSONL 合约

schema 为 `wolvrix.node-evolution.v1`，记录依次包含 header、前后 entity 库存、event 和完整 footer。entity 库存与事件之间只要求依赖在文件完成时能够解析，不要求事件引用的最终 after entity 已经写在它前面。

header 必须包含：

```json
{
  "record": "header",
  "schema": "wolvrix.node-evolution.v1",
  "engine": "gsim",
  "pass": "splitArray",
  "graph": "NodeEvolution",
  "inventoryScope": "all-live",
  "implicitIdentity": true
}
```

`inventoryScope=all-live` 表示该引擎约定范围内的全部存活物理实体。GSIM 当前范围是 ordinary Nodes 加 memory Nodes，不含另行导出的 source scopes 和 source aggregates。GRH 还提供 `source-endpoints` 库存模式，只纳入有原生 source binding 的端点及其要求的实体；该模式必须如实标记，不能把来源端点库存称为全部 GRH operation/value。两端库存范围和物理对象数不要求相同。

每个 entity 有 `stage=before|after`、typed ref、`sources[]` 和 physical。GSIM ref 的 generation 显式为 0；GRH ID 可复用，因此 generation 必须随原生 ID 一起记录。`name` 只供阅读，不能参与跨端对应。`opKind` 描述物理种类。

`structure` 用于让同 ID 的内容变化可观察。旧版 GSIM trace 只有双 64 位诊断 fingerprint，不能重放表达式；新版 `native-expression-dag-v1` 保留该诊断值并增加完整 assignment/reset 根、ENode ID、op/opName、类型、常量、整数参数、Node/memory 引用和有序 children。共享 ENode 在不同 owner 内保留相同 ID，消费者检查定义一致及 DAG 闭合；clock、register pair、memory 参数／ports 等真实关系同样进入载荷。allocator 地址与重算得到的调度缓存边不参与。GRH 新增真实 symbol、位置、完整 value binding context、所有 state port 的 target 类型，以及 graph metadata／ports／declared symbols／generate groups。

event 的公共字段为：

```json
{
  "record": "event", "seq": 1,
  "action": "rewrite", "reason": "static_indexed_array_access",
  "before": [{"kind": "gsim-node", "id": 9, "generation": 0}],
  "after": [{"kind": "gsim-node", "id": 16, "generation": 0}],
  "geometry": {"partition": false},
  "steps": []
}
```

支持 `split/rewrite/replace/delete/retain/merge/create`。reason 是实际触点给出的稳定代码，不能由分析器事后编造。主 event 的 before/after 只引用相应 pass 边界库存；一个边界 ref 最多处分一次、生成一次。新增或消失的实体必须有 event，同 ID 的 physical、source 或 structure 变化也必须有前后 event；其余实体可按 `implicitIdentity` 继承身份。

### 原生步骤为何需要归并

一次 pass 可以先拆 parent、再重写新成员的表达式、最后绑定新 current/next 成员。直接把这三步都当主 event，会让新成员出现在不存在的 before 库存中，或者被重复生成。因此 pass 内先记录真实步骤，writer 在结束时按共享 typed ref 的连通分量归并：

1. 保留每步原始 action、reason、refs 和组件内顺序；两端当前 producer 均保留 geometry 和全局 step 序号。第 9.4 节冻结的旧 GRH 全量 trace 尚无逐 step geometry 和全局序号，不能用新版 producer 的能力补述旧证据。
2. 共享新成员的步骤与其原 split 合并；同 ID 后续再次改写也合并。
3. 主 event 投影到真正的 before/after 库存，过滤仅存在于 pass 内或回滚掉的中间实体。
4. 细粒度证据保存在 `steps[]`，允许其中出现边界库存以外的中间 ref。

GSIM 只有一个纯 split 步骤构成的主 event 才声明 `geometry.partition=true`；混合重写组件保守为 false，各原生 split step 保留自身的分区关系。GRH 当前 step API 不声明 partition，统一为 false。false 不表示来源缺失，而是不对组件宣称无重叠划分；端点覆盖通过显式 source projection 的并集核验。

边界 event 的 action 是归并结果：多个步骤中的 merge／replace 可以归为 rewrite，GRH 也会根据边界实体数量归为 split。真实变换类型与原因以 `steps[]` 为准，不能用主 action 数量冒充真实 merge 次数。steps 在每个组件内保持记录顺序；两端当前 producer 另输出原生全局 `step.seq`。该序号描述真实记录顺序；后态重放使用的是关联这些边界事件的字段 mutation，不能把仅有 refs 和理由的 step 当作完整中间态变化载荷。

正常完成的最后一行必须为：

```json
{"record":"footer","complete":true,"beforeCount":13,"afterCount":16,"eventCount":8}
```

没有完整 footer、库存计数不闭合、重复处分/生成、悬空边界 ref 或同 ID 变化没有 event，均不得作为有效 trace。可选 `inputIdentity` 记录输入 SHA256；GSIM 的 `--trace-input-sha256` 由调用方计算并传入，producer 校验格式并标注 `authority=caller`，不冒充自身计算了摘要。

## 4. 原生触点与证据链

| 层次 | 实际位置 | 原生证据 |
| --- | --- | --- |
| GSIM 拆分决策 | `getSplitArray`、`checkNodeSplit` | 自依赖/cycle、动态写索引、未拆聚合输入、动态 consumer 等实际判定 |
| GSIM parent/member | `graph::splitArrayNode`、`Node::arrayMemberNode` | 真正 Node 指针及原始轴 projection；parent 与成员关系不依靠名称 |
| GSIM 同 ID 改写 | `ExpTree::updateWithSplittedArray`、`ArrayRewriteOwners` | 实际改写返回 changed，同时按共享原生表达式指针通知全部 owner，记录 `split_array_shared_expression_rewrite`，不只依赖逐 owner 的 changed 返回值 |
| GSIM 状态配对 | `splitOptionalArray` 中 `bindReg` | 新 current/next 成员的双向原生指针 |
| GRH 拆分与回滚 | `GraphSplitter` | 静态选择转发、视图物化、动态/不支持保留、选择事务回滚 |
| GRH 状态族改写 | `StateSplitter` | member 声明、静态读写重写、whole read 重建、writer projection 与符号冲突重命名 |
| GRH source binding | `captureBindings`、`memberBinding`、`bindMemberRead`、`bindMemberWriter` | 从变换前原生 binding 得到 source endpoint，按真实成员坐标投影并重新绑定 |
| 独立核验 | `scripts/audit_semantic_evolution.py` | 库存/event 闭合、同端来源覆盖守恒、两端最终 source projection 并集比较 |

流程是“原生生产者记录 → 完整性核验 → 同端前后覆盖 → 跨端覆盖比较 → 定位真实 pass 触点修复”。分析器不参与电路变换，也不补写来源身份；它是验证正常流程的消费者。

分析器使用磁盘 SQLite 索引完整库存与源投影，避免把整机 JSON 全部载入 Python。来源集合的并集比较支持一个 source 多个物理承载者，不能把 value、operation 或别名的重复绑定直接当成缺失，也不能只比较 member 数量忽略具体坐标。按源回溯强制采用 source key→该源端点→edge 主键的查询顺序，已在有效全量库核对执行计划，避免共享 value 或整个 before 库存被逐源反复扫描。跨端 summary 只有比较与 TSV 全部完成才标记 `complete=true, integrity=valid`，中断不能产生成功结论。

## 5. GSIM 实现与已取得的结果

实现文件：

- `reference/gsim/include/NodeEvolution.h`、`src/NodeEvolution.cpp`：可复用 writer、前后库存、structure fingerprint、步骤连通分量归并与 complete footer。
- `reference/gsim/src/splitArray.cpp`：实际决策/拆分/表达式改写/配对触点。
- `reference/gsim/include/config.h`、`src/main.cpp`：默认关闭的 `--trace-node-evolution=PATH` 及可选 `--trace-input-sha256=HEX`。
- `reference/gsim/Makefile` 的 `test-node-evolution`、`test/node-evolution.fir`、`scripts/check_node_evolution.py`：原生回归入口。

目前 trace 的 before/after 库存流式写出；内存保留的是原生步骤 refs、原因和连通分量索引，不保存全量表达式副本。structure 按实体即时计算。requested trace 无法打开或写入失败会令 producer 失败，避免误把不完整文件当作成功。

| 已执行 Make 目标 | 结果 | 证据 |
| --- | --- | --- |
| `test-node-evolution` | 首轮 13→16、20 steps→8 events；补共享表达式回归后 19→23、25 steps→11 events，3 个保留 ID 的 structure 变化均有双侧 event | `ptmp/F27/gsim-tests/boundary-make.log`、`shared-expression-final.log` |
| 同目标的开关透明性检查 | trace 开启/关闭的 Init、TopoSort JSON 逐字节相同 | `ptmp/F27/gsim-tests/` 与其 `plain/` |
| 同目标的失败检查 | 非法输入 SHA、无法写入的 trace 路径均非零退出 | `invalid-sha.log`、`unwritable-trace.log` |
| 同目标的公共 API 生命周期检查 | 1 个合法及 12 个非法调用序列通过：必须 before→steps→after→finish，拒绝重复 footer、无效 stage 或结束后继续写；正常 trace 及 Init／TopoSort 与修补前逐字节相同 | `ptmp/F27/gsim-tests/lifecycle-make.log`、`ptmp/F27/lifecycle-tests/lifecycle/` |
| `test-semantic-lineage` | 通过：三个阶段的 source path、singleton/交错形状、拆分及重命名来源保留 | `ptmp/F27/gsim-tests/boundary-make.log`、`ptmp/F27/semantic-lineage-tests/` |
| `test-source-aggregate-inventory` | 通过：source aggregate/scope、address 状态、depth-one replacement、split 成员及重命名身份回归 | 同日志、`ptmp/F27/aggregate-tests/` |

fixture 实际覆盖 `direct_array_self_dependency`、`static_indexed_array_access`、`paired_register_array_split`、`register_member_pair_bound`、`split_array_reference_rewrite`、`split_array_shared_expression_rewrite`、`dynamic_write_index`、`dynamic_consumer_index`、`unsplit_aggregate_input` 和 `unsupported_array_node_kind`。没有用该 fixture 宣称所有稳定 reason 分支均已执行。

构建和回归全部通过现有或新增 Make 目标。旧 `reference/gsim/build` 的 dependency 文件引用已失效 GMP 路径，首次复用构建因此失败；随后改用隔离目录 `ptmp/F27/gsim-native` 和已有 F26 GMP package，最终上述三个目标联合执行 exit0。可用 producer 为 `ptmp/F27/gsim-native/gsim/gsim`；前期原始逐步 event 版本的日志不作为最终边界 schema 的通过证据。

### 全量首轮保留为失败证据

首轮 `ptmp/F27/full/gsim.jsonl` 虽有 complete footer，独立审计仍发现 32 个共享表达式 owner 漏事件，不能作为通过证据。其库存为 7,829,556→9,635,014，事件 2,069,594；修复后的新 trace 和独立核验结果见第 7 节。`ptmp/F27/full/gsim.log` 记录 cycle 路径拆分 856 个数组、optional split 233,875 个数组；原生 split 步数和归并后的 boundary event 数量不可互换。

## 6. GRH 状态 binding 修复与 trace 接入

当前工作树中的修复针对 state scalarization 后 source binding 仍指向旧聚合端点、或生成的成员读写缺少正确成员坐标的问题。该问题不能通过给生成 op 复制全部 owner SemanticIds 来解决：owner 表示归属，binding 必须明确指向对应 value/operation 及源 projection。

`StateSplitter` 在改写前捕获受影响 whole read 与 writer 的 binding；`memberBinding` 检查源元素宽度、未固定的源轴与实际状态族维度，逐轴将真实 linear member index 转成原始 source coordinates，保留 singleton 轴。静态 indexed writer 已选择成员时避免再次错误投影。

成员读通过 `bindMemberRead` 绑定到实际 scalar result；成员写通过 `bindMemberWriter` 重新指向真实 target writer/data，并保存非 next-data 的上下文角色。不能解释的几何不应被伪装为完整匹配；当前代码增加 binding 兼容性检查，在不支持时保守保留状态族。trace 记录 source 投影迁移、whole read 的 aggregate/packed 重建和 writer 分拆，从而把修复放在变换现场。

动态数组写的 `indexed-update` 仅描述 register-next 的单个写贡献：被消费轴必须是实际 writer 下标对应的前缀，payload 必须严格等于目标状态去掉该前缀后的类型和形状，不能只核对总位宽。wildcard 表示可能更新域；enable、mask、writerOrder、clock/reset 仍由真实 writer 描述，因此它不是完整 next-state 表达式。同 payload 的不同 writer 分别记录，动态贡献不进入具体静态成员对齐计数。source-only 库存允许 index operand 的 producer 不在库存中；`indexConstants` 来自原生常量分析，不能声称分析器对所有常量已独立做数值复算。

普通 array writer 的操作数依次为 `enable, index[0..n), data, events...`，masked writer 在 data 后还有 mask；`eventEdge` 的长度决定事件操作数数量。分析器从这个真实布局独立推导 n，再核对 source 中的 consumedAxes 与 indexOperands。例如 `r:UInt<64>[64]`、`write(enable,i,d64,clock)` 记录 `projection=[-1]`、`consumedAxes=[0]`、`payloadShape=[]`，表示本次 d64 可能写入 r 的任一成员；不会把 d64 当作 4096-bit 全数组值或 64 份 broadcast。

已加入 `SplitStaticArrayOptions` 的可选 trace 路径、输入 SHA 与 `traceSourceEndpoints`，多图 trace 要求路径含 `{graph}`。`GraphSplitter` 和 `StateSplitter` 使用公共 `GraphEvolutionTrace` 记录实际步骤。trace 默认关闭；无论开关，正常 pass 都维护相同的原生 binding。

既有正常 pipeline 的调用点即可直接开启，不需要 capture 脚本来生成关系：

```python
session.run_pass("split-static-array", design="design.main",
                 trace_node_evolution="ptmp/F27/split-{graph}.jsonl",
                 trace_input_sha256=verified_firrtl_sha256,
                 trace_source_endpoints=False)
```

GSIM 在普通命令中增加 `--trace-node-evolution=ptmp/F27/gsim.jsonl` 及可选 `--trace-input-sha256=HEX` 即可。`capture_semantic_evolution` 只是批量运行这些正常接口并保存输入／producer 身份；auditor 和摘要脚本只读取证据，不参加 source binding 或演化关系生成。

### GRH 回归与实现终态

公共 helper 按边界流式输出，不保留 entity JSON 副本。writer context 保留在 operation 的 `structure.bindings`，value 则保留去重后的来源端点、定义、类型和 owner，避免仅因克隆 writer 上下文就把共享 clock value 误记成表达式改写。原生 fill writer 显式标记 `realization=broadcast`；原始位序明确的整段 scalar 容器标记 `realization=packed, packing=row-major-lsb-first`，核验总位宽而不把 packed 容器宽度当元素宽度。

| 已执行目标 | 实际结果 | 证据 |
| --- | --- | --- |
| `make test_semantic_bindings` | 8/8 CTest 通过，包含新增 operation binding 替换失败后保持原记录的检查 | `ptmp/F27/grh-tests/core-bindings.log` |
| `make test_native_semantic_evolution` | C++ 1/1、Python 2 项通过；33 个原生 trace 全部严格核验通过，before 1,615、after 1,817、events 75；28 rewrite、40 split、7 retain；类型／几何未验证数均为 0，实际回滚 reason 已覆盖；10 条 indexed-update 贡献，索引依赖通知 4 步；删除依赖边的 3 个负控均拒绝 | `ptmp/F27/grh-tests/context-watch-make.log`、`native-audit-summary.json` |
| `make test_semantic_evolution_integration` | 2 项测试通过：开关透明、二次 split 幂等、两阶段 trace chain 连续、source-only 来源投影完整、checkpoint 身份正例及 3 个负例 | `ptmp/F27/integration/test.log`、`summary.json` |
| `make test_semantic_evolution_audit` | 已通过 53 项测试：不完整／重复／悬空记录、漏事件、错误投影、类型与存储深度、packed/broadcast/indexed-update、真实 writer 下标数／事件尾部／上下文负控、输入身份和已验证索引篡改、按 source 回溯与删除原因、scalar 大分母不能掩盖数组成员缺口、延后查询索引仍保持即时重复拒绝、不完整输入拒绝、只读诊断不写索引也不提升有效状态、source 查询计划及比较中断负控等 | `ptmp/F27/audit-tests/test.log`、`ptmp/F27/source-query-plan-tests.log` |

集成样例的 all-live 库存为 149→158，source-only 为 19→25；两种模式的唯一 source projection 集合分别为 16→22，完全相同。二次 split 为 158→158、0 event，普通导出 JSON 与首次输出逐字节相同。trace 开／关与 source-only 模式的普通 JSON SHA256 均为 `05c716cac553850565c6879efff8bbc27d006aad3d76e64521b925ff9cd2066e`。

## 7. 两端集成与全量测量

集成入口为 `make capture_semantic_evolution`，独立消费者为 `make audit_semantic_evolution`／`make audit_native_semantic_evolution`。driver 记录输入内容 SHA、实际映射的 GRH producer libraries 和 GSIM binary 身份；恢复 checkpoint 时必须验证 manifest 中的 dump SHA 和唯一 FIRRTL source SHA，不能把任意 checkpoint 配上当前 FIRRTL 文件名就宣称同输入。trace 的 `authority=caller` 不代替这条 manifest 链。

### 小图：从演化差异倒推正常流程修复

输入为 `reference/gsim/test/dump-semantic-lineage.fir`，SHA256 为 `b6dac1365bc1c0d40423585b9e3243db2eb0191c657681333137eb5dc7cbc992`。两端完整库存和来源守恒均通过，修复前后电路实体数均为 GRH 149→158、GSIM 14→18。

| 观测 | 修复前 | 修复后 |
| --- | --- | --- |
| 具体叶端点投影（含普通 scalar）在 GRH 有相同端点 | 14/18，77.7778% | **18/18，100%** |
| 其中：原始 source 数组的具体成员投影 | **4/8，50%** | **8/8，100%** |
| 缺失具体成员投影 | 4 | **0** |
| 跨端 source group | 13 aligned、1 GRH-only clock、1 type-unverified predicate | 相同；成员补齐没有冒充类型或辅助角色证明 |
| layout | 11 exact、2 different、1 GRH extra-view、1 side-only | 11 exact、3 GRH extra-view、1 side-only |

缺口来自 `bundle.data` 与 `child.values.data`：GSIM 有 `[0]/[1]` 和 `[0,0]/[0,1]` 成员；GRH 原本只有整数组绑定。原生 trace 表明对应 source base 没有成员投影迁移事件，而非名称匹配失败。

因此在 `GraphSplitter` 中维护正常静态读的成员来源：从已有 binding 出发，沿实际位序保持的 Assign／ArrayCreate／Concat／StaticSlice 关系组合 offset，将投影绑定到真实读结果及成功选择的已有 value。端口数组保留 SliceArray 时同样维护该读关系；不跨算术／Mux 猜测来源，也不为未读取成员创建保活节点。每次迁移记录 `static_source_projection_bound`／`source_member_projection_transferred`，保留父聚合为明确 alias。

修复前证据：`ptmp/F27/shared-before-projection/audit/`；修复后：`ptmp/F27/shared/audit/summary.json`、`differences.tsv`、`trace-violations.tsv`。后者库存有效、同端来源守恒、没有 trace violation。剩余 TSV 中 clock 是两端辅助角色输出范围不同，predicate 是 GSIM 在 InferAllWidth 前仍为未知宽；三组 aggregate alias 不再算成员缺失。

数组分母 8 为 bundle.data 2 个、child.values.data 2 个、state current 2 个、state next 2 个。`array_member_alignment_percent` 只计原始 source rank>0 且每轴有明确坐标的 GSIM 成员，singleton 的 wildcard 也不算明确成员；仍以 wildcard 保留的 GSIM 数组不在此分母中，须另看整源覆盖和 aggregate view。旧 `gsim_member_alignment_percent` 包含 rank0 scalar，保留作兼容指标；不能用大量 scalar 稀释数组拆分差异。成员坐标命中与类型核验也分别报告。

### SimTop 全量：采集与审计

输入与 checkpoint 复用 F26 冻结身份：FIRRTL SHA `b313a3ecd154cbd9279b14403709806b95fb136cf44b475e9def46a926ecb26b`；post-elim JSON SHA `f541d4444e272675f05a88109c29f7eb8ee5f1363db4f879c8b401a1cd843a8b`。GSIM 为 all-live，GRH 为明确标记的 source-endpoints 模式；后者不声称全量 GRH op/value 库存覆盖。

首轮 GRH capture 暴露 helper 对共享 clock/reset 的来源列表使用线性重复扫描，在数十万来源处形成二次复杂度；该次已中止，部分文件 `grh-initial-incomplete.jsonl` 无完整 footer，不作为通过证据。已改用哈希索引并在冲突时精确比较原生路径、类型和几何，保留全部真实来源；重新安装后启动 fresh capture。

全量审计随后找到了两类实际缺口，而没有把 producer 的 complete 当作审计通过：

- **GSIM 漏事件 32 个**：同一 bundle memory 的多个读口共享地址 ENode，第一个 owner 修改共享表达式后，后续 owner 遍历时已没有旧 array 引用，原 changed 返回值无法说明所有 owner 都发生了变化。修复在真实表达式改写位置通知全部原生 alias owner，新增 `split_array_shared_expression_rewrite`。反例在修复前失败、修复后通过，普通 Init／TopoSort 导出开关透明。原始 32 项列表保留于 `ptmp/F27/full/gsim-inspect/inventory-violations.tsv`。
- **GRH 动态 indexed next contribution**：例如 `timeStamp[64]` 的 writer 以运行时 index 选择目标成员，其 data 仅为 scalar64。原 binding 的 wildcard 表示可能更新的源范围，不能当作整数组数据，也不能假装 broadcast。helper 补充明确的 `indexed-update`、writerRef、被消费的源轴、实际索引及 payload suffix；auditor 根据原生 writer 操作数和 state target 核验，并把动态写贡献单列，不计成静态具体成员对应。全 trace 几何诊断共扫描 20,066,933 个实体，发现 21,430 条不满足旧整数组视图假设的端点、732 种 width／shape／role／stage 组合。只读分类已逐条核验真实 indexed writer/indexCount/dataOperand 与精确 suffix，**21,430/21,430、732/732 均被解释，剩余类别 0**，before/after 各 10,715 条。关联到 21,604 个实际 writer 上下文，含 4,336 个固定消费轴，促使 helper 按 writer 区分同 payload 的动态写贡献。旧 trace 没有 stateTarget，实际声明类型仍由新 trace 严格复核，不用分类结果替代新 trace 通过。

GSIM 修复后的 fresh capture 在 `ptmp/F27/full-gsim-fixed/`：194.864 s，before 7,829,556、after 9,635,014、events 2,069,626，较首轮多 32 个完整边界事件；实际 producer 备份为该目录的 `producer-gsim`，SHA256 为 `6533de57de6f919d284b23a8b4775186885d4fe80de51ed54974a864bd75cafa`。独立审计已通过，库存有效、来源投影守恒、违例 0；after 仍有 5,715,838 个实体类型未知，不能视为类型证明。boundary action 为 rewrite 2,056,445、split 2,997、retain 10,184，包含步骤归并，不代表只拆了 2,997 个数组。trace SHA 为 `52c758553303435df96c045ec58763346ad590ad4ee12b77a63fdc9b83811054`，结果见 `native-audit/summary.json`。旧 invalid 索引不作为复用通过证据。

GRH 第一份完整 fresh trace（补 indexed-update 之前）为 `ptmp/F27/full/grh.jsonl`，旧几何审计未通过。补 indexed-update 的新 trace 为 `ptmp/F27/full-grh-fixed/grh.jsonl`，source-endpoints 库存仍为 8,225,895→11,841,038，events 105,981；checkpoint 加载 272.536 s、含 trace 的 split 126.540 s、当前进程峰值 RSS 50,445,992 KiB。这些不是无 trace 的 pass 性能。完整输入／manifest／映射 producer 身份见该目录的 `capture-summary-grhsim.json`；实际映射的 `_wolvrix.so` SHA 为 `bf8c441d49a7ef28bee8dc07bbf61486f036e5b55e32249c7edd3335e022622f`，`libwolvrix-lib.so` SHA 为 `c517edcb96fccca930bf3ecb64b5c02608485fcdc896d9e7d544ea71a91005db`。

该轮全量索引完成后又发现 **126 个同 ID 变化漏事件**，因此仍为 invalid，不作为跨端通过证据。完整递归分类证实：64 个 operation 均为 `kRegisterWriteArrayPort`，仅 `structure.bindings[].indexConstants[]` 改变；62 个 value 仅 `sources[].indexConstants[]` 改变，其余字段差异 0。实际索引 producer 被静态选择改写，`indexConstants` 从 null 变为 0，writer 本身的 operands／attrs 未变化，但它及 data value 上的写贡献证据发生了变化。全清单与递归差异保留在 `ptmp/F27/full-grh-fixed/inventory-inspection/`。修复须在实际索引改写位置通知原生依赖的 writer／payload，不能通过删除 diagnostic 字段或分析器 diff 补事件掩盖变化。

已在 `GraphSplitter` 的实际静态选择改写触点增加 `indexed_update_index_rewritten`，同一步显式关联 producer／result、依赖的 writer 和 payload。依赖只沿原生 `constantIndex` 支持的最多 16 层等宽 Logic Assign 链登记；每次通知前解除旧链、重新登记当前链，既处理 A→Assign(B) 后 B 才被改写的次序，也排除已断开的关联。三个 fixture 覆盖直接改写、A／B 两种顺序和共享 payload 的两个 writer；无关选择不关联这些 writer，删除依赖边的负控均被审计拒绝。trace 关闭时不建立依赖索引，正常变换和 binding 决策不受影响。

修复后的全量新采集在 `ptmp/F27/full-grh-context-fixed/`，capture 与独立审计均已通过：source-endpoints 8,225,895→11,841,038，boundary events 105,617，read 264.962 s／含 trace 的 split 131.492 s，进程峰值 RSS 50,463,028 KiB。新增依赖边把原先分离的步骤连成同一因果组件，因此主事件数量减少，原始步骤仍保留。实际映射 `libwolvrix-lib.so` SHA 为 `12328bcc4ccf11a5054e0721856e0f8d3b8ec6154ab8dc0a51c5c2d01f0e807f`，其他输入与 producer 身份见 `capture-summary-grhsim.json`；两个实际 producer 库已备份在该目录。

为提前排除其他问题，另对旧索引进行只读事件预检：21,606 条 indexed-update 描述、105,981 个 event 均通过对应检查，来源守恒违例 0。输出为 `ptmp/F27/full-grh-fixed/event-preflight/event-inspection.json`，明确标记 `integrity=unvalidated`，既未重新验证总库存／trace SHA，也未写 validated metadata；它不替代新 trace 的完整审计。

### SimTop 两端独立审计终态

| 项目 | GRH：source-endpoints | GSIM：all-live |
| --- | ---: | ---: |
| before 实体 | 8,225,895 | 7,829,556 |
| after 实体 | 11,841,038 | 9,635,014 |
| before 源端点记录 | 8,345,803 | 7,829,556 |
| after 源端点记录 | 14,629,714 | 9,635,014 |
| boundary events | 105,617 | 2,069,626 |
| after 类型未知实体 | 0 | 5,715,838 |
| after 存储几何未知实体 | 0 | 0 |
| 库存／事件闭合 | 通过 | 通过 |
| 来源投影守恒违例 | 0 | 0 |

GRH 的 writer-layout-v2 独立检查核验 21,606 条 indexed-update 描述，全部通过；boundary action 为 99,859 split、881 rewrite、4,877 retain。GRH trace SHA 为 `44e4bb59bc7c81b8453f78db0f5b0e2f61934f2bdeb79e3529dd46f5f5131314`。GSIM 的来源几何守恒不等于未知宽度已证明一致，1,632,178 个 event 仍涉及未验证类型。

完整 Make 日志为 `ptmp/F27/full/grh-context-fixed-capture-make.log`、`grh-context-fixed-audit-make.log`、`gsim-fixed-audit-make.log`；结果分别为 `ptmp/F27/full-grh-context-fixed/native-audit/summary.json` 和 `ptmp/F27/full-gsim-fixed/native-audit/summary.json`。两份 `trace-violations.tsv` 均仅有表头。跨端比较使用这两个已完成的索引，并重新核验完整 trace SHA 与 writer-layout-v2，不复用旧 invalid 索引。

### SimTop 跨端结果

`ptmp/F27/full-fixed-cross/audit/summary.json` 为 `integrity=valid, complete=true`，两端 trace SHA 复核及各自守恒均通过。默认比较全部原生角色，共 **8,105,337 个 source path＋role 组**，不是 SemanticTree SID 或物理 Node/op 分母。

| 来源组状态 | 数量 | 含义 |
| --- | ---: | --- |
| aligned | 2,132,174 | 源类型、原始几何及覆盖范围一致；不代表表达式／行为等价 |
| type_unverified | 5,689,503 | 源几何与覆盖一致，GSIM 在 InferAllWidth 前类型未知 |
| indexed_update_contribution | 3,799 | 动态写贡献单列，不冒充完整 next-state 值 |
| source_projection_mismatch | 7 | 下述未写成员的 next 端点模型差异 |
| GSIM-only | 3,585 | GRH 库存中没有同源角色；需结合零宽／范围分类 |
| GRH-only | 276,269 | GSIM 库存中没有同源角色；含辅助角色范围差异 |

未发现 source type、shape、field-depth 或 storage-depth 冲突。以 GSIM 的 7,829,068 个 source 组为分母，7,825,483 个能在 GRH 找到同路径／角色，即 **99.954209%**；这一身份存在率包含类型未知、写贡献及 7 个覆盖差异，不能称为已证明的类型／值对齐率。

| 具体投影指标 | 数量／比例 |
| --- | ---: |
| GSIM 数组具体成员（原始 source rank>0、全轴坐标明确） | 2,100,649 |
| GRH 存在相同具体成员投影 | 1,324,236，**63.039375%** |
| 缺少相同具体成员投影 | 776,413，36.960625% |
| 缺口中仍被 GRH wildcard 几何范围覆盖 | 774,494 |
| 具体投影命中或 wildcard 几何覆盖 | 2,098,730 / 2,100,649，**99.908647%** |
| 无同源 GRH 几何视图 | 1,919 |
| 包含普通 scalar 的旧叶端点指标 | 8,838,913 / 9,618,296，91.896870% |

具体成员缺口不自动等于源覆盖丢失：GRH 可保留 wildcard 聚合视图，GSIM 则已经生成具体成员。最终布局为 7,538,868 组投影集合完全相同，189,987 组 GSIM 具体成员齐备但 GRH 有额外投影，96,628 组投影集合不同，279,854 组仅一端有该角色。全部差异及原生事件回溯在 `audit/differences.tsv`；其采样 ref 数量有上限，完整实体和关系保留在原生 trace 与 SQLite 中。

`make summarize_semantic_evolution_differences F27_OUTPUT=ptmp/F27/full-fixed-cross` 对完整 **10,334,438,437-byte** TSV 流式分类，严格核对其有效／完成状态、缺口总数及所有单边源组计数。TSV SHA 为 `14380e01bc9835412f1d74688d3a7d4955ccabce2681009237221b9328872c98`。结果在 `array-member-summary/`：

- `array-member-differences.tsv`：94,025 个数组缺口组，保留源坐标、缺口数、双方原生原因和可回溯文件位置，约 88 MiB。
- `source-side-only-differences.tsv`：全部 279,854 个单边角色组，约 105 MiB。
- `summary.json`：按 status／role／layout／来源宽度与 originRole／原生 reason 分类；13 项摘要测试通过。

774,494 个 wildcard 覆盖缺口中，774,493 个是聚合／singleton 视图差异，另 1 个为已单列的 indexed-update 贡献；后者不能称为完整 next-state 值。99.908647% 只表示来源几何范围存在，包含未知类型和写贡献，不是同值／行为等价证明。

无 GRH 几何视图的 1,919 个成员分为：

| 类型 | 源组 | 成员数 |
| --- | ---: | ---: |
| 已知零宽 GSIM-only：value／current／next | 29 | 744 |
| depth-one memory 转 register 后的 memory-storage next | 8 | 8 |
| 普通正宽 GSIM-only next | 3 | 1,160 |
| 七个已有 source 组中缺少未写 next 成员 | 7 | 7 |

全部单边组的范围也已核对：GRH-only 276,269 全部为 **clock 195,145＋reset 81,124**；GSIM-only 3,585 分为已知零宽 855、零轴 574、类型未知 593、memory-storage 来源的 register-next 1,553，以及其他正宽 register-next 10。未知宽度的单边来源保留为未核验，不能推断它们一定是零宽，也不能把 depth-one memory 的 next 再计作第二份 memory storage。

其中 10 个普通正宽 next 源已另行沿原生库存核验：GSIM before 每源一个 next，`assignTreeCount` 全为 0；GRH before／after 的 current 均存在，next 写贡献均为 0。GSIM after 为 debug_realCfiPc 的 64 个、releaseVioMask 的 72 个、sbuffer.debug_mask 的 1,024 个及其余七个 scalar，共 1,167 个 next 槽位，其中只有 1,160 个进入数组成员分母。after 的赋值计数使用明确标记的样本，结合 before 全集为空及 splitArray 只分发既有 assignment trees 的实现，不夸称逐个检查了所有 after 表达式。逐源证据为 `register-next-model/normal-next-summary.tsv` 和 `normal-{grh,gsim}/source-inspection.json`。因此这 1,160 个数组缺口也未发现实际 writer binding 丢失。

### 七个覆盖差异由原生演化链定位到 split 之前

| FIRRTL 源对象（共同前缀略） | 无实际 writer 的成员 | GRH Next 覆盖：before→after | GSIM |
| --- | ---: | --- | --- |
| backend.inner.fpRegion.fpDataPath.fpRegFile.mem | 0 | 255/256→255/256 | whole next→256 个配对成员 |
| backend.inner.intRegion.intDataPath.intRegFile.mem | 0 | 223/224→223/224 | whole next→224 个配对成员 |
| backend.inner.vecRegion.vecDataPath.v0RegFilePart0.mem | 0 | 21/22→21/22 | whole next→22 个配对成员 |
| backend.inner.vecRegion.vecDataPath.v0RegFilePart1.mem | 0 | 21/22→21/22 | whole next→22 个配对成员 |
| backend.inner.vecRegion.vecDataPath.vfRegFile.mem | 0 | 127/128→127/128 | whole next→128 个配对成员 |
| backend.inner.vecRegion.vecDataPath.vlRegFile.mem | 0 | 31/32→31/32 | whole next→32 个配对成员 |
| socMisc.debugModule.debug.dmInner.dmInner.sbErrorReg | 3 | 3/4→3/4 | whole next→4 个配对成员 |

前六项完整前缀为 `cpu.l_soc.core_with_l2.core`，最后一项为 `cpu.l_soc`。六个 RegFile 的 GRH before／after writer 投影均为 `[1..N-1]`；sbErrorReg 为 `[0],[1],[2]`，每轴两个真实 writer。GSIM 所有缺口成员均有 registerPair，但 **assignTreeCount=0**。对应 GRH current 成员仍存在，说明不是状态／current 来源丢失，也不是 split 丢掉 writer binding。逐源前后投影、实际实体及事件证据见 `ptmp/F27/full-fixed-cross/register-next-model/`。

GRH 既有 `register-next` binding 记录实际 writer data 的贡献，静态写同样受 enable／mask／writerOrder 限定；GSIM paired next slot 可在无 assignment 时仍存在。不能为这七处补假 writer 或把其他独立 scalar 的 binding 贴上去。后续若要求 slot 级统一，应新增独立的 state-next-slot 端点、绑定真实状态声明并随真实成员声明迁移，同时保留 writer-contribution；完整 next-state 值则需另行构造含 hold／优先级／mask／reset 的正规转移表达式。本轮保留差异，并未声称已经实现该扩展。

## 8. 结论限制

1. 第 7 节的历史全量证据只证明原生实体演化、来源身份与成员覆盖；新重放验证另见第 9 节。重放验证结构后态可还原，仍不等于跨端电路行为等价；完整端点对应也不能推出操作实现一一相同。
2. GSIM splitArray 位于 InferAllWidth 前，部分原生 width 为 `-1`。必须保留 unknown/unverified；不能把 `-1` 当成通配符后报告类型已证明一致。补充后续类型证据必须记录其对应原生身份与阶段。
3. all-live 和 source-endpoints 是不同库存范围，跨端比例以明确的 source key/role/geometry 分母统计，不能直接相除物理 Node/op 数。
4. 同一源对象可有多个别名或 current/next 等端点；projection 覆盖采用集合并集，partition 声明才额外要求互不重叠。
5. 原生 source scopes/aggregates 属于结构来源对象，不是本阶段物理 node 库存；FIRRTL 外部模块接口与其 SV 实现同样须区分，不用 SV 内部名称补 source identity。
6. 小图 18/18 不能扩展成整机 100%。本轮整机数据为第 7 节的显式投影 63.039375%／含 wildcard 的几何范围 99.908647%；未知类型、辅助角色、空 next slot 和 memory 表示差异均保留，未转换成一一同值对齐结论。
7. 无物理 value/operation 的零宽或空数组绑定不进入本阶段物理库存；分母也不是 F26 的全部 SemanticTree SID。trace 最大单行／单个组件大小仍影响消费者内存，磁盘索引不等于任意单行解析都使用固定内存。

## 9. 完整节点载荷与独立重放验证

### 9.1 实现与真实漏项修复

- GRH 的 `GraphEvolutionTrace` 保留全部 operation／value 的精确结构、attrs、symbol、SrcLoc、port 标记、source binding context、state target 等；独立 graph entity 保留 metadata、端口引用、declared symbols 和 generate groups。反向 uses 从有序 operands 派生。before／changed-body 采用磁盘 spool 与 offset 索引，避免在内存缓存整图 JSON。
- GSIM 的 `NodeEvolutionTrace` 原生记录完整表达式 DAG、assignment/reset 根、共享 ENode 身份、常量／整数参数、clock／reset、current-next 配对、memory 参数／ports 和来源信息。before 和 mutation 采用磁盘 spool；主事件和真实 steps 继续保留。
- 完整 context 揭示 GRH state writer 拆分会改变既有 clock/reset value 的绑定上下文。已在真实 binding 提交点记录 `state_writer_bindings_transferred`，同时记录符号及 declared metadata 的真实变化；没有靠边界差分自动补理由。
- GSIM 数组成员命名冲突会重命名已有标量，例如源字段 `bundle.data_0` 与拆分得到的 `bundle.data[0]` 物理名称冲突。旧 fingerprint／sources 视图看不到 name 变化；已在实际重命名处记录 `split_member_name_collision_rename`，来源 token 不变。
- 两端都拒绝用纯 `retain` 组件解释实际字段变化。漏标量事件、只通知共享表达式的一个 owner、无事件变化均不能产生合格的重放证据。
- 跨端表达式比较保留 GSIM reference ENode 自身的类型约束。引用表达式的宽度／符号与其指向的 Node 不一致时，明确记为 `reference_expression_type_differs_from_native_node`，不丢掉这层类型后判为相等；未知宽度仍记为未核实。宽度与符号各有独立负控。
- 复用已有 replay 时，除 trace SHA 与原生事件归属检查外，再核对当前重构库存与独立 oracle 的完整字段，以及已记录依赖的 owner／active target 闭合。旧 oracle 没有 body 时按原 tracePath／offset 读取真实 after。只改变缓存 entity.body、保持摘要／trace／metadata 不变的负控也必须失败；不会把这种复核说成重新执行全部 mutation 或表达式 DAG 检查。

普通 pass 的 binding 修复始终执行；trace 只是可选记录能力。历史独立重放程序 `replay_semantic_evolution.py` 不参与匹配或修补。重构 SQLite 中的 `entity.body` 只来自 before 和 mutation；`oracle` 是独立验证库存，不提供重构载荷。首版只保存其文件位置和摘要，再逐实体读取实际 JSON；并行优化版另外保存实际 after 的 canonical JSON TEXT。当前有正文的库存通过两个 typed ref 有序游标比较完整原文，同时检查严格键顺序、两向缺失／额外 ref 和 NULL；此前整机运行使用的 SQL BINARY 路径同样核对完整原文。所有路径都检查完整字段，摘要仅预筛及确认文件身份，强制摘要相等的篡改负控仍必须失败。

### 9.2 回归证据

| 验证 | 已验证结果 | 证据 |
| --- | --- | --- |
| 33 个 GRH 原生 pass 用例 + 完整 metadata 用例 + GSIM 主用例 | 1,674 before + 345 mutations → 1,882 重构后态；1,882 个实体完整字段等值；3,133 条 active 依赖闭合，2 条父级／归属引用单列 | `ptmp/F27/replay-tests/native-summary.json` |
| 独立 replay 正负控制 | 33 项通过；覆盖错误／缺失 delta、旧值、创建／删除、共享 DAG、闭包、retain、双向事件边界、implicit identity、generation 和完整 footer；即使强制摘要相同，真实字段篡改仍失败；已有证据只读复核不修改原索引／summary，并保留 caller 的 TEMP 配置与无关 TEMP 表 | `ptmp/F27/independent-review/temp-store-reader.log` 及 `ptmp/F27/replay-tests/test.log` |
| 普通 Session 集成 | 3/3 通过：trace 开关不改变普通存储 JSON；split 幂等；首次及第二次 split 均独立重放通过；checkpoint 身份链仍验证，memory／scalar reset 用例通过 | `ptmp/F27/independent-review/ordered-oracle-integration.log` |
| 全节点跨端比较回归 | scalar rewrite、unknown 内部宽度、部分写、四态／二态、memory 分类，以及类别／状态／TSV 行数闭合 | `ptmp/F27/replay-comparison-tests/` |

GSIM 既有 `test-node-evolution` 还对 semantic-lineage、memory-inventory、source-aggregates 和共享表达式正负例执行完整重放，保留 13 个 lifecycle 检查与普通输出一致性检查。两端 producer 均已编译，`make py_install` 完成；不是只生成离线分析结果。

### 9.3 两端完整小图比较

四个用例均通过普通 `Session`／GSIM 流程产生 trace，随后分别独立重放，再比较两端最终节点及原生事件。数组、标量、状态、memory、effect、无 source 辅助节点和 graph context 均进入清单，没有先过滤成数组投影：

| 输入 | GRH before → after／mutations | GSIM before → after／mutations |
| --- | --- | --- |
| `reference/gsim/test/node-evolution.fir` | 204 → 211／24 | 19 → 23／15 |
| `reference/gsim/test/dump-semantic-lineage.fir` | 150 → 159／29 | 14 → 18／15 |
| `reference/gsim/test/dump-source-aggregates.fir` | 218 → 224／16 | 38 → 41／11 |
| `wolvrix/tests/transform/data/node-evolution-memory.fir` | 245 → 250／34 | 26 → 30／18 |

合计 **914 before + 162 mutations → 956 个 after，全字段逐一重放一致**。新 memory 用例没有外部实现依赖，覆盖 cmem bundle 的共享地址及读写、smem 读写、scalar regreset／enable 和数组状态。旧 `dump-memory-inventory.fir` 的跨端 capture 因 Echo 缺少外部 SV 实现绑定而拒绝；失败日志保留，未放宽前端或将其当作通过。

原始结果目录为 `ptmp/F27/replay-cross-native/{node-evolution,semantic-lineage,source-aggregates,memory-native}/`。最新 `compare-complete-events/` 目录提供：

| 产物 | 内容 |
| --- | --- |
| `all-nodes.tsv` | 每个重构后态物理节点恰好一行，含类别、typed ref、来源对应、物理类型及事件定位 |
| `unmatched-nodes.tsv` | 无原生来源或无跨端 counterpart 的节点；不把所有辅助节点都假设为已对应 |
| `unaligned-nodes.tsv` | 尚未满足所比字段一致的全部节点，包括已有来源 counterpart 但类型／表达式未核实者；source status 与 comparison status 分列 |
| `before-groups.tsv` | 两端真实 before 源组、实体与布局；事件所触及的前态直接读取原生 before，未触及实体经过身份及库存检查后继承 |
| `final-groups.tsv` | 两端原生来源锚点、最终布局、支持的表达式结构、unknown／unsupported 原因、before presence／layout、差异来源，以及来源边界关系与原生事件摘要 |
| `evolution-events.tsv` | 全部原生边界事件、有序完整 `native_steps` 及事件级 `event_geometry`，一次保存完整关系 |
| `event-source-relations.tsv` | 每个事件前后真实来源锚点；避免在每个后态节点重复打印大型组件 |
| `trace-groups.tsv` | 从事件 before／after 来源锚点并集比较边界关系与原生 trace；包含 delete-only，缺少原生来源的事件逐端单列 `unanchored` |
| 两端 `replay.sqlite` | 可按 typed ref 查询完整重构节点内容、实际 oracle 的位置、原生 event／mutation |

这里的 `source-correspondence` 只表示找到同一原生 source path／role／projection。GRH 常把 GSIM 一个 Node 内的计算分成许多 op/value，所以物理数量不相同；无直接来源的辅助 op 必须留在清单中，后续才能增加表达式层级的对应。当前四态／二态域、GSIM 未推导的内部宽度、state-next／reset 与 memory 转移正规化仍会使跨端表达式判定为 unsupported／需审阅。`complete=true` 表示清单生成和审计完整，不表示全图语义等价。

本小节此前四个真实用例的比较结果保存在各用例的 `compare-complete-events/`。844 个 GRH 后态实体中，198 个有同源 counterpart、620 个没有直接原生来源、26 个没有另一端 counterpart；112 个 GSIM 后态 Node 中，106 个有同源 counterpart、6 个没有。**956 个实体在该轮全部仍需跨端字段审阅**，不能把上述来源存在数称为完整结构／值对齐。它们各自的 before→after 精确重放已通过；跨端表达式与状态正规化仍有明确缺口。第 9.5 节记录新版 producer／完整 trace 联合比较的重采集结果。

同轮完整事件对照覆盖 GRH 24 个、GSIM 30 个原生事件，唯一事件计数全部闭合；输出共 104 行，其中 101 个来源组、3 个无来源单端事件。40 个双方均有事件的来源组全部保留边界表示差异，61 个来源组仅一侧有事件；没有用另一侧的隐式 identity 伪造一个原生事件。trace 对照不再以 final groups 为唯一入口，因此删除后没有最终节点的事件同样进入核验。完整大组件只保存一次，分组行记录事件 ID、局部边界和摘要，可回查全部原始内容；新增事件对照与完整 geometry 导出负控后比较回归为 37/37。

`trace-groups.tsv` 和 `final-groups.tsv` 中的 `native_trace_comparison` 比较的是原生事件摘要：action、reason、typed-ref kind 的数量，以及有序 steps 的 action／reason／边界数量摘要。`equal-summary` 仅表示这些摘要一致，`different-native-summary` 表示摘要不同；summary 的 `native_trace_comparison_scope` 明确记录此范围。来源边界关系另按前后 source anchors 与 disposition 比较。`evolution-events.tsv` 的 `event_geometry` 原样保存事件级 geometry（包括 partition）；`native_steps` 保存完整有序 steps，包括逐 step refs 和 geometry。当前尚未建立两端 intermediate 节点的逐一映射，也未将事件级或逐 step geometry 的跨端等价纳入摘要比较；摘要一致不能称完整 trace 相等。新增 caller 回归核对事件级 partition 和带 typed-ref 的 step geometry 不丢失，比较回归为 37/37。

差异倒推使用真实 before 布局和事件关系，分别标记 pass 前已单边、原有布局差异、pass 后新增显式视图、pass 后布局差异、前态类型未知或语义仍未核实。保留 whole-array holder 的一侧与只生成 member 的一侧会产生新视图差异，不能仅凭该标签断言功能错误。另一个必须处理的情况是：op 本身未修改，但其 result value 的来源 binding 已变化；因此 before 的 op 来源要按真实 before result edge 重新传播，不能把 after 的来源锚点直接复制回去。

重放入口为 `replay_native_semantic_evolution`；全节点跨端入口为 `compare_semantic_replay`，可以通过 `F27_COMPARE_FLAGS` 指定已完成的两端 replay 目录，复用前须再次验证 trace SHA256 和索引元数据。对应回归为 `test_semantic_evolution_replay`、`test_semantic_replay_comparison` 及 `test_semantic_evolution_integration`。

### 9.4 SimTop 新标准全量验证

本轮重新采集 `all-live + native-field-delta.v1`；第 7 节旧 trace 不复用作重放证明。FIRRTL SHA256 仍为 `b313a3ecd154cbd9279b14403709806b95fb136cf44b475e9def46a926ecb26b`；GRH 从 F26 冻结 post-elim checkpoint 恢复并验证其 manifest 链。该 checkpoint 内也包含已绑定的 SimJTAG SV 实现：整图结构重放照常核验，FIRRTL 来源分组不把其 SV 内部节点当成 FIRRTL 来源缺失。

两端原生采集已完整结束，producer 均报告 `replayComplete=true`，GRH 未解释变更违例为 0：

| 引擎 | before 全部实体 | after 全部实体 | 原生事件 | 原生 mutation |
| --- | ---: | ---: | ---: | ---: |
| GSIM | 7,829,556 | 9,635,014 | 2,069,994 | 4,122,611 |
| GRH | 68,044,130 | 69,644,738 | 251,467 | 8,912,385 |

GRH trace 为 104,201,882,698 bytes，checkpoint 读取 255.09s、pass + 完整 trace 749.99s、峰值 RSS 49.97GiB；实际 producer 库已冻结在 `replay-full-grh/producer/`。GSIM capture 为 419.72s。两端后续独立重放仍以严格合约执行，不以 producer 自报代替独立 oracle 核验。

为避免大图 JSON 解析串行占用全部审计时间，消费者增加有界多进程准备：每批最多 4MiB／2,048 records，在途最多 `2×workers` 批，主进程仍按原序提交库存并串行应用 mutation／event。真实 GRH 前 100,000 实体基准为 0 worker 55,649/s、4 worker 123,847/s、8 worker 124,006/s，因此整机 GRH 采用 `F27_REPLAY_FLAGS='--workers 4'`。该基准只测 ingestion，不产生 validated metadata，也不冒充重放通过。

依赖存在性复核改为从真实 `entity` 主键投影出只含 typed ref 的磁盘 TEMP 表，再检查 owner 和 active target；保持原始重构库存与 oracle 不变。200,000 个真实 Node body＋1,000,000 条确定性合成依赖的独立基准中，target 检查含构表从 19.413s 降到 0.921s，owner＋target 从 38.494s 降到 1.716s。该基准明确 `benchmarkOnly`，不是整机通过证据，也不外推整机倍数；原库前后 SHA 一致、query_only 恢复、缺 owner／target、历史引用及重复调用均有回归。产物为 `ptmp/F27/closure-benchmark-200k-1m/summary.json`；优化没有热修改此前已运行的 legacy reader，随后启动的 reader-v3 已使用该路径。

有正文的 oracle 比较同样经过独立基准：200,000 个真实 canonical body 的副本中，原 SQL 检查为 8.655s，有序双游标为 1.180s；原库与副本 SHA 保持不变，双向库存和原 TEXT 均逐项核对。证据为 `ptmp/F27/oracle-benchmark-200k/summary.json`，也明确 `benchmarkOnly`；legacy offset oracle 保持读取真实 after 的核验路径。该优化没有热修改此前已运行的 legacy 进程；随后启动的 reader-v3 已使用有序双游标。

独立重放状态以各结果目录的 `summary.json` 为准。GSIM 的有效结果在 `ptmp/F27/replay-full-gsim/independent-replay/`；GRH 保留旧 `independent-replay/` 未完成产物，最终采用已 complete／valid 的 `independent-replay-v3/`。旧进程曾因大正文表上的最后引用查询耗时较长而可逆暂停；v3 使用完整正文有序比较与紧凑引用表，不重采集 producer，也不重跑 FIRRTL ingest 或原生 pass。跨端选择写入 `ptmp/F27/replay-full-cross-v2/selected-grh-replay.txt`，消费者及 SHA 冻结在该目录的 `consumer/`。上一轮 `replay-full-cross/` 因第 9.5 节的删除事件联合判定漏洞在入口复核期间中断，其 summary 为 invalid／interrupted，不能用作最终比较证据；旧快照及产物保留。修复后的 v2 整机比较现已 exit0、complete／valid，最终数字见第 9.6 节。

GSIM 整机独立重放已完成，进程 exit0，summary 为 `complete=true, integrity=valid`：

| GSIM 独立核验项 | 结果 |
| --- | ---: |
| before + 原生 mutations → 重构 after | 7,829,556 + 4,122,611 → 9,635,014 |
| mutation update／create／erase | 1,825,079／2,051,495／246,037 |
| actual-after 库存及完整字段一致 | 9,635,014 / 9,635,014 |
| 活跃依赖闭合 | 27,043,220 |
| 单列父级／归属引用（计数名 historical_references） | 11,827 |

证据为 `ptmp/F27/replay-full-gsim/independent-replay/summary.json`，trace SHA256 为 `cd082f6c2bc2a8981a28af60166251337eb9785466324a8048b0085c8c2a38c5`。该完成结果证明 GSIM 自身 before＋trace 重构完整后态，不代表 GRH／GSIM 跨端已对齐。进入全量跨端比较前仍使用当前 reader 合约复核缓存。

GRH reader-v3 现已 exit0，`independent-replay-v3/summary.json` 为 complete／valid；trace SHA256 为 `b5631e2e66769d0d1c48bb3f24122ac4bcc36cf89951e7aba35e74d99dcffa9a`：

| GRH 独立核验项 | 结果 |
| --- | ---: |
| before＋原生 mutations → 重构 after | 68,044,130＋8,912,385 → 69,644,738 |
| mutation update／create／erase | 7,289,479／1,611,757／11,149 |
| actual-after 库存及完整字段一致 | 69,644,738 / 69,644,738 |
| 活跃依赖闭合 | 199,278,345 |
| 单列父级／归属引用 | 0 |

因此本轮冻结 producer 的两端整机 **75,873,686 个 before＋13,034,996 条 mutations → 79,279,752 个 after** 已逐实体、逐字段独立核验通过，范围不按数组筛选。GRH 的完整 oracle 比较于日志 03:35:45 结束，随后完成全部表达式及引用闭合检查才写出有效 summary；旧进程日志或 producer 自报不代替该证据。跨端 trace／终态比较是另一项验收，已完成的联合结果见第 9.6 节。

### 9.5 完整已记录 trace 与终态的联合验收

跨端比较新增独立 `full_native_trace_comparison`，覆盖事件实际记录的字段、完整有序 steps、geometry，以及这些字段内部的 typed refs。事件运行内的 `seq` 仅作定位；step 顺序与原生 `step.seq` 保留。边界 ref 列表忽略顺序但保留重数，其余列表保留顺序。不能只凭 action／reason／数量摘要判完整 trace 相等。

typed ref 使用真实 before／重放 after 的存在性和原生 source anchors 归一化。仅在 pass 内存在的中间 ref、没有 source 的 ref、同一事件内多个物理 ref 共享同一来源身份而不能唯一映射，均明确为 unsupported；不根据名称或数字 ID 建立跨端关系。事件内重复来源集合只保存一次，引用其 count／SHA；同摘要必须有完全相同的 canonical 正文，负控覆盖强制摘要碰撞。`full-native-traces.tsv` 和 SQLite 的 `event_full_trace` 保存完整归一化载荷，`trace-groups.tsv` 与 `final-groups.tsv` 保存比较状态和不支持原因。

验收字段统一为 `full_comparison_status`：只有终态 layout／支持的表达式／source boundary 关系均相等，且完整已记录 trace 比较为 equal，才是 `full-comparison-equal`。旧 `comparison_status=compared-fields-equal` 保留并注明仅比较的字段范围，不能替代联合验收。`all-nodes.tsv`、`unmatched-nodes.tsv`、`unaligned-nodes.tsv` 均保留新字段及原因；未对齐清单按联合验收输出。只改 geometry 的负控验证旧字段仍可相等，而联合验收必须失败。

这里比较的是 producer **实际记录的完整载荷**。两侧均未记录的中间状态或几何不能算已证明；第 9.4 节旧 GRH 整机 producer 的 step 字段缺口仍然存在。新的原生 GRH producer 已加入全局 `step.seq`，选择步骤记录 base ref、物理形状和 bit offset／width，状态成员另记 element／coords；partition 仍保守为 false。refs＋geometry 是步骤证据，完整边界节点的生成仍由 native field mutations 完成。

本轮还从实际来源差异修复前序流程：`GraphSplitter::selectStateValue` 直接复用现有叶子时，现在同样调用原生 `bindSelection`。此前整数组 writer 的 data／mask 若没有额外创建 slice，数组成员来源不会传到复用叶子；例如 `bundle.a[0]` 在 GSIM 有成员来源，GRH 只有 whole-array 来源。修复发生在正常 pass 内，不依赖分析脚本。C++ 回归同时核对 data／mask 的来源、坐标及实际 writer operands；`make test_native_semantic_evolution` 通过，Python 原生审计 3/3，日志为 `ptmp/F27/grh-step-geometry/make.log`。

完整比较初轮回归为 51/51，日志为 `ptmp/F27/replay-comparison-tests/full-native-test.log`，覆盖仅修改事件／step geometry、typed ref、顺序、额外字段、来源歧义、中间 ref、非法 generation，以及强制摘要碰撞。随后补上同源别名的 delete-only 事件负控：GRH 删除 B、保留同源 A，而 GSIM 仅保留 A 时，最终 A 的字段虽然一致，该来源的完整 trace 必须显示单侧删除。此前 final group 只取存活实体的 after event membership，会漏掉 B 的删除；现在改取 `event_source` 的 before／after 并集。一个事件双 stage 只计一次，独立事件即使 payload 相同仍保留重数。跨端完整载荷已经校验的窄 `trace_event_digest` 用来读取摘要，避免每个来源重读大型 event 正文。

修前失败证据在 `ptmp/F27/replay-comparison-tests/delete-only-before-fix.log`；修后完整回归为 **55/55**，日志为同目录 `delete-only-after-fix.log`，包含单侧删除负控、双侧匹配删除正控、事件重数、缺失摘要和索引查询计划。当前整机比较使用 `ptmp/F27/replay-full-cross-v2/consumer/`，SHA 清单同目录保存，Make 入口通过 `F27_COMPARE_SCRIPT` 指定快照。缓存复核新增逐阶段进度日志，校验范围不变；reader 37/37 再次通过，日志为 `ptmp/F27/full-acceptance-fix/replay-tests.log`。新的小图和整机最终数字以各目录有效 summary 为准。

窄表路径经过独立元数据查询基准：真实小图的 11,539-byte 原生事件重复 91 次，构造明确标记 synthetic 的约 1MiB 组件；128 个事件、4,096 次查询、64MiB SQLite cache 下，宽表查询为 6.150s，窄表为 0.034s。两路逐项结果相同，源库及 fixture 的 SHA 均未改变；该结果只证明元数据读取放大，不能外推整机加速倍数。证据为 `ptmp/F27/cached-contract-scale/event-signatures-benchmark/summary.json`，标记 benchmarkOnly，不能用作重放通过证据。

本轮更新后的普通 producer 已重新采集第 9.3 节四个真实用例，并用冻结的完整 trace consumer 分别独立重放／比较。结果在 `ptmp/F27/replay-cross-native-v4/<case>/comparison/`，四份 summary 均为 complete／valid；仍为 **914 before＋162 mutations → 956 after**，全部后态字段独立一致，GRH 24 个／GSIM 30 个原生事件均完整计入。`source-aggregates` 中 GSIM 有来源 counterpart 的节点由 37/41 增至 39/41，新增的两个对应即 `bundle.a[0]`、`bundle.a[1]`；其余字段／状态正规化缺口没有隐藏。

非数组改写的具体证据在 `node-evolution/gsim.jsonl`：标量 `result` 的 ref 始终为 `gsim-node:5:0`，physical 始终是 8-bit、shape=[]。event 3／step 6 的 reason 为 `split_array_reference_rewrite`，mutation 1 修改其完整 structure。内部 ENode 50 从引用数组 Node 10、children=[51] 的索引表达式，变成直接引用成员 Node 22、children=[]，索引 ENode 51 随之移出该表达式 DAG。重放从标量前态应用该 structure delta，实际后态独立核验通过；没有因外层 Node 不是数组而跳过此变化。

| v4 全节点联合口径 | GRH | GSIM |
| --- | ---: | ---: |
| 全部 after 实体 | 844 | 112 |
| 有来源 counterpart，仍需联合审阅 | 198 | 108 |
| 无直接原生来源，单列 unanchored | 620 | 0 |
| 有来源但无另一端 counterpart | 26 | 4 |
| full-comparison-equal | 0 | 0 |

这组结果证明“完整重放能力已在全部节点上实际执行，跨端完整比较能够保留差异”，不证明全部节点已语义等价。主要未核实项仍包括四态／二态、内部宽度、state／memory 转移及辅助节点对应；不同物理变换的原生步骤也不能仅凭同源判为相同。`make test_semantic_evolution_integration` 另外通过 3/3，核对 trace 开关透明性、split 幂等、连续 trace 链和普通 Session 里的独立全字段重放；日志为 `ptmp/F27/source-member-fix/integration-make.log`。该新 producer 的实际库 SHA 保存在各 capture-summary 中，不能与第 9.4 节旧整机 producer 混用。

缓存复核继续保持全部归属及闭包约束；只将存活实体的存在性查询改为共用一次 `main.entity` 精确主键投影，actual-after 完整正文仍由原有独立路径核对。异常时显式关闭 oracle 游标，确保 TEMP 清理及 query_only 恢复。reader 回归已增至 37/37，证据为 `ptmp/F27/cached-contract-scale/replay-make.log`；四个真实用例复用已完成 replay 的 `comparison-cached-v5/` 也全部 complete／valid，956 个实体的联合结果不变。加入删除事件修复后，同四图 `comparison-cached-v6/` 全部 complete／valid，节点及事件库存计数闭合，联合通过仍为 0/956。整机 reader-v3 已按启动时定义完成；缓存优化用于已完成的 v2 整机跨端比较，不重放第三次。

全局联合验收必须同时检查全部最终节点和全部原生事件。没有后态节点的删除事件、无来源事件仍在 `trace-groups.tsv` 单列，不能以最终节点通过率将其略去；`all_events_accounted_for=true` 表示全部事件已计入，不表示这些事件跨端相等。

### 9.6 整机完整 trace／终态跨端比较的最终结果

`ptmp/F27/replay-full-cross-v2/summary.json` 为 **complete=true、integrity=valid**，进程 exit0。`all_nodes_accounted_for`、`before_nodes_accounted_for`、`all_events_accounted_for` 均为 true。冻结 consumer 的三文件 SHA 再次通过，包含第 9.5 节的 delete-only 联合判定修复；独立只读复核确认各分区计数闭合。比较入口重新核验两端 trace SHA、缓存身份、完整实际 after 正文、归属及活跃依赖；没有再次执行 native mutations 或表达式 DAG 检查，后两项由第 9.4 节 fresh replay 的有效证据提供。

| 整机全部物理实体 | GRH | GSIM |
| --- | ---: | ---: |
| before | 68,044,130 | 7,829,556 |
| after | 69,644,738 | 9,635,014 |
| 唯一原生事件 | 251,467 | 2,069,994 |
| 有原生来源 counterpart，联合仍待审阅 | 22,168,293（31.83%） | 8,854,534（91.90%） |
| 无直接原生来源，unanchored | 46,490,606 | 0 |
| 有来源但无 counterpart，unpaired | 985,839 | 780,480 |
| full-comparison-equal | 0 | 0 |

before 中由显式事件覆盖的 GRH／GSIM 实体分别为 7,679,764／2,081,300，其余 60,364,366／5,748,256 通过严格 identity 继承；两端分别加总到完整 before。后态类别覆盖标量、状态、memory、数组、effect、辅助实体和 GRH graph context，没有按数组过滤。GRH 物理粒度比 GSIM 细，31.83% 的分母包含全部 op/value 和无来源辅助实体，也包含 checkpoint 内 SV 实现；不能把它当作 FIRRTL 语义节点的对应率。FIRRTL 来源组仍只按原生 source anchors 建立。

最终来源组共 **10,286,659**，其中双方都有实体的 8,854,046 组全部为 expression unsupported，不能判为完整结构或行为相等。其 layout 分为相等 2,876,769、类型未核实 5,699,672、不同 277,605；另有单边 1,432,613 组（GRH-only 652,133、GSIM-only 780,480）。未核实项包括四态／二态域、GSIM split 边界尚未推导的内部宽度、state／memory 转移正规化和辅助物理节点对应；来源 projection 的 wildcard 与具体坐标也不由分析器猜作同一身份。

真实 before 驱动的差异归因如下；这些是互斥的来源组标签及优先级分类，不是功能错误数：

| difference_origin | 来源组数 |
| --- | ---: |
| before-type-unverified | 5,696,528 |
| new-after-view | 2,041,396 |
| semantics-unverified | 1,655,783 |
| preexisting-unpaired | 416,327 |
| after-view-unpaired | 225,223 |
| preexisting-layout-difference | 181,042 |
| newly-paired-view | 70,360 |

trace 表共 **4,816,098 行**：4,661,192 个来源组和 154,906 个 GRH 无来源事件。全部 251,467＋2,069,994 个唯一事件均计入，不能用 group-event memberships 代替唯一事件数。双方都有原生事件的 1,602,280 个来源组中，完整已记录 trace 比较为 different 11,141、different-and-unsupported 1,591,139，完整相等为 0；184 组仅 source-boundary relation 相等，仍不是完整 trace 相等。最终来源组另有 5,376,563 个 `full-native-trace:equal`，其中包含空 trace／implicit identity，不能解读为同等数量的实际变化事件已对齐。

因此，当前已证明全部约定节点字段可以从自身 before＋原生 mutations 精确生成 after；跨端完整联合通过为 **0/79,279,752**，表示仍未证明全图对齐，不表示这些电路全有功能错误。`behavioral_equivalence_proven=false`。本整机结果沿用第 9.4 节冻结 producer；新 step geometry／seq 和直接复用叶子的成员 binding 修复仍以第 9.5 节四图新采集证据为准，不能声称已在整机重新采集验证。

最终文件均在 `ptmp/F27/replay-full-cross-v2/`：

- [summary.json](../../ptmp/F27/replay-full-cross-v2/summary.json)：完整计数、验收范围和两端缓存复核结果。
- [unaligned-nodes.tsv](../../ptmp/F27/replay-full-cross-v2/unaligned-nodes.tsv)：按联合验收打印全部未通过的 node／op／value，含 ref、类别、来源、counterparts、事件及原因；本轮全部 79,279,752 个实体均在其中。
- [all-nodes.tsv](../../ptmp/F27/replay-full-cross-v2/all-nodes.tsv)、[unmatched-nodes.tsv](../../ptmp/F27/replay-full-cross-v2/unmatched-nodes.tsv)：全部后态与无来源／无 counterpart 的子集。
- [before-groups.tsv](../../ptmp/F27/replay-full-cross-v2/before-groups.tsv)、[final-groups.tsv](../../ptmp/F27/replay-full-cross-v2/final-groups.tsv)：真实前态、最终联合结果及差异归因。
- [trace-groups.tsv](../../ptmp/F27/replay-full-cross-v2/trace-groups.tsv)、[evolution-events.tsv](../../ptmp/F27/replay-full-cross-v2/evolution-events.tsv)、[full-native-traces.tsv](../../ptmp/F27/replay-full-cross-v2/full-native-traces.tsv)：全部事件分组、完整原生步骤／geometry 与归一化载荷。

### 9.7 历史源 SID 覆盖统计：不等同于当前计算 Node 对齐

本节只记录源 SID 覆盖；先前把它作为当前 Node 对齐比例回答，抽象单位不正确。分母是 **split 后全部 8,780,799 个 GRH SemanticTree 源 SID**，不是 GRH 当前语义计算子图数或 GSIM Node 数。分子是能在实际 GSIM split 后库存找到原生来源对应 Node 的 SID 数；每个 SID 只计一次，允许一个 SID 对应多个数组成员，也允许多个别名 SID 对应同一个 GSIM Node。数组完整覆盖按原始 source shape 上全部成员投影的并集核验，不能用任意一个成员代替整个数组。GSIM 的 source scope／aggregate 描述记录不计入 Node 分子。

| 按 SID 分类 | 数量 | 占全部 SemanticTree SID |
| --- | ---: | ---: |
| 找到 GSIM 固有 Node，来源几何范围完整覆盖，允许 wildcard 聚合视图 | **8,277,942** | **94.273220%** |
| 仅覆盖部分源成员 | 0 | 0% |
| 无 primary Node binding 的模块／聚合容器 | 499,774 | 5.691669% |
| 无 primary binding 的其余源节点 | 329 | 0.003747% |
| 显式空源：零宽／零元素 | 2,754 | 0.031364% |

499,774 个容器包含 9,751 个 module scope 和 490,023 个 aggregate。全部有非空 primary binding 的 8,277,942 个 SID 均找到 GSIM Node，且本轮两侧投影各自完整覆盖源成员；没有部分覆盖或未解决的非空 SID 歧义。容器与空源仍保留在总分母中，因此不能把这个结果写成全部 SemanticTree node 的 100%。F26 的 99.940245% 包含 scope／aggregate 结构记录的对应，本节只把 GSIM 固有 Node 计入分子，两者口径不同。

其中 1,296,184 个 SID 是已核实的同源别名。例如实例端口 `cpu.clock` 的 field SID 22 与展开模块端口的 declaration SID 26780 均原生绑定到 GRH value 14。分析器只在来源路径、角色、shape、field depths、完整源类型签名及原生 value／operation target 集合全部相同时接受这种别名；仅同名或 target 不同不解除歧义。每个别名 SID 仍各计一次，GSIM 目标允许复用。

数据取自第 9.4／9.6 节已验证的冻结整机 capture：不可变源树和原生 before binding 提供 SID 身份及别名证据，实际 after anchors 提供两侧来源成员覆盖。本次没有重新执行 producer 或 replay，也未将第 9.5 节后续 producer 修复算入整机结果。本指标证明已记录的原生来源身份与几何覆盖，**不证明物理类型、完整 trace、状态转移或行为等价**，也不单独证明每个别名 SID 的 after binding 载荷均已保留。

结果为 complete，非空 SID 的未解决歧义数为 0；`make test_semantic_sid_alignment` 的 17 项回归通过。`make measure_semantic_sid_alignment` 自动生成本口径及逐 SID 清单，只读消费生产流程已导出的关系，不参与生成或修补这些关系。

- [summary.json](../../ptmp/F27/semantic-sid-alignment/summary.json)：主分子 `native_gsim_found`、完整覆盖 `native_gsim_full`、总分母、别名数及证据范围。
- [sid-status.tsv](../../ptmp/F27/semantic-sid-alignment/sid-status.tsv)：全部 8,780,799 个 SID 各一行，含两侧源成员数、交集及分类。
- [measurement.log](../../ptmp/F27/semantic-sid-alignment/measurement.log)、[existence-summary.log](../../ptmp/F27/semantic-sid-alignment/existence-summary.log)：全量读取及存在率汇总日志。

### 9.8 split 前后数量变化排查：源 SID 与实际成员不同

针对“split 后 GRH 相对 GSIM 从多变少，是否说明 split 使节点减少”的排查，原生 trace 显示：**两端实际物理库存均净增加；不变的是 GRH 源 SemanticTree 的 SID 数量。** 第 9.7 节的 SID 存在率不能用于判断物理拆分程度。此前把固定源 SID 与另一端物理 Node 放在同一张 split 前后表中，容易把相对数量变化理解为 GRH 自身节点减少。

| 冻结整机库存 | before | after | 新建 | 删除 | 净增 |
| --- | ---: | ---: | ---: | ---: | ---: |
| GRH 源 SemanticTree SID | 8,780,799 | 8,780,799 | 0 | 0 | 0 |
| GRH 全部物理 operation/value/graph-context | 68,044,130 | 69,644,738 | 1,611,757 | 11,149 | 1,600,608 |
| GSIM 固有 Node，含 memory | 7,829,556 | 9,635,014 | 2,051,495 | 246,037 | 1,805,458 |

物理增删数来自第 9.4 节 fresh replay 的原生 mutations；分别有 7,289,479／1,825,079 个实体原位更新，两端所有实际 after 完整字段均独立核验一致。这是结构重放证据，不表示两端行为等价。GRH 全物理库存包含 checkpoint 中的 SV 实现，不能作为仅 FIRRTL 的 node 对应率分母。另外 `Session.semantic_stats.operation_rows/value_rows` 仅统计具有非空 SemanticIds 的物理实体，并非全图总数；这两项实际也分别从 34,347,436／7,460,434 增至 35,223,742／7,587,278。

代码原因是 `GraphSplitter::projectedBinding` 和 `StateSplitter::memberBinding` 复制原生 binding，保留 `binding.semantic`，通过真实 target 和 projection 区分新成员；split 不调用 `SemanticTree::addNode`。例如源 SID 10 对应 `r:UInt<8>[2]`，拆分后可有 `(SID 10, projection=[0])→r_0` 和 `(SID 10, projection=[1])→r_1`，源 SID 仍只有一个。状态成员由 `splitFamily` 真正创建，已有 C++ 回归还明确要求拆分前后 source identity 不变。因此 SID 数量恒定不是没有生成成员的证据。

但这次排查也确认一个尚未解决的对齐问题：**GRH 组合数组按静态读取按需转发／物化，仍可保留整数组 wildcard；GSIM 的 `splitArrayNode` 则把父 Node 移出 live 库存并枚举成员。** 第 7 节旧 source-endpoints 整机对照中，2,100,649 个 GSIM 具体数组成员只有 1,324,236 个在 GRH 找到相同具体 projection，即 63.039375%；其余 776,413 中有 774,494 个仍被 GRH wildcard 范围覆盖。这个已存在的成员粒度差异不能被第 9.7 节 94.273220% 的来源覆盖率替代。该 63.039375% 属于旧 producer/capture，并非本轮新采集的整机比例。剩余 1,919 个无几何视图的分类和 split 前已存在的 next 槽位差异见第 7 节，现有证据不能归因为 split 丢失实际 writer。

本轮另外通过普通 `capture_semantic_evolution` Make 入口重新采集 `dump-semantic-lineage.fir`，开启正常 pass trace，并导出 `post-split.json`：源 SID 为 22→22，GRH 物理实体 150→159、GSIM Node 14→18；两端各自 before＋mutations 的完整后态重放均 complete／valid。原生来源审计中，GSIM 全部 18 个叶端点和其中 8 个具体数组成员都在 GRH 找到对应，来源守恒无违例。这个小图验证正常流程确实产生新成员，不外推整机成员已经全部对齐。

本次只修正文档中的解释并留存调查证据，没有为了增加统计数而修改源树或 split 电路。后续 split 对齐应以正常导出的 `(source SID, role, projection, 实际 target)` 成员端点及其原生演化关系作为对象，分别记录保留聚合体、具体成员和辅助物理实体，不能继续用原始 source SID 个数代替实际成员数。

- [inventory-counts.tsv](../../ptmp/F27/split-count-investigation/inventory-counts.tsv)：两份整机原生库存及本轮小图的 before/after、实际增删与净变化。
- [GRH 整机重放](../../ptmp/F27/replay-full-grh/independent-replay-v3/summary.json)、[GSIM 整机重放](../../ptmp/F27/replay-full-gsim/independent-replay/summary.json)：本节全量原生增删数的依据。
- [本轮小图 capture](../../ptmp/F27/split-count-investigation/semantic-lineage/capture-summary.json)、[来源审计](../../ptmp/F27/split-count-investigation/semantic-lineage/audit/summary.json)、[GRH 重放](../../ptmp/F27/split-count-investigation/semantic-lineage/grh-replay/summary.json)、[GSIM 重放](../../ptmp/F27/split-count-investigation/semantic-lineage/gsim-replay/summary.json)：本轮普通生产入口的采集与核验结果。

### 9.9 纠正 Node 对应单位：当前语义计算子图

**GSIM Node 应对应 GRH 中一个有明确边界的当前语义计算单元：入口 values＋实现该计算的 op 子图＋出口 value／effect／state 端点＋必要控制和状态上下文。** 这是需要建立的显式对象，不能用原始 SemanticTree SID 个数、所有物理 op/value 个数或来源投影覆盖率代替。

GSIM `Node::assignTree` 是有序赋值表达式列表，表达式内部的 `ENode` 才承载具体运算；Node 另有 clock、resetTree、regNext 及 memory owner 等上下文。例如 `y=mux(c,a+b,d)`，GSIM 的 y Node 可以内含 add 和 mux 两个 ENode，GRH 对应实现 y 的 add/mux 等 op 及相应数据流子图。遇到 a/b/c/d 对应的其他计算节点时，以它们的出口作为入口边界，不把它们的完整实现递归并入 y。

GRH 现有三种关系尚不能直接充当这个显式对象：

- SemanticTree SID 表示源身份；一个 SID 可在 split 后有多个成员，也可能与其他 SID 成为别名。
- `opSemanticIds`／`valueSemanticIds` 表示多对多归属；同 SID 的所有 op 不能无条件合并为一个当前 Node，成员、current/next、共享实现和控制辅助可能混在其中。
- `semanticBindings` 提供来源 role、projection 与实际 value／operation 端点；它提供计算边界的锚点，但本身不是完整 op 子图及其成员表。

因此需要在正常流程中显式维护当前计算单元身份、输入输出边界、op／value 成员及共享关系，保留源 SID 作为 provenance。split 的 trace 应记录计算单元从一个数组单元演化为多个成员单元，以及未拆分 consumer 单元内部 op 子图的改写；状态的 current/next、memory/effect 等角色要按真实端点分别建模。共享 op 可以被多个单元引用，顺序赋值与控制上下文必须保留，不能只保存无边界的 op ID 集合。

**截至本次澄清，该显式计算单元及其逐 pass 成员维护尚未完整实现，也没有可据此报告的整机 Node 对齐比例。** 已完成的物理字段重放与源覆盖审计仍各自有效，但不能冒充这一目标已达成。第 9.7 节 94.273220% 只保留为历史来源覆盖结果。
