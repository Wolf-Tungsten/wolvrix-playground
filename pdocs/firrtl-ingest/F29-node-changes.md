# F29：统一 Node 修改、数组拆分与公共交换格式

日期：2026-11-13。状态：两个 pass 的 Node 维护及双端公共导出已实现，五文件
重放通过真实 FIRRTL 小图验收。静态快照可独立插桩，evolution 来自 pass 运行中的
实际事务；未运行本阶段整机对比。早期原生格式与本轮公共格式的验收记录分别列出。

## 合约与范围

接续 F28 的唯一具名叶 Node，迁移正常生产链中的
`comb-loop-elim → split-static-array`。Node 始终包含实际 GRH op 集合及必要
value anchors；内部路径只组织名字。flatten 后的新成员也直接连接根。

Node 修改采用三种语义：

| 操作 | 前态 → 后态 |
| --- | --- |
| 增加 `add` | 空集 → 一个或多个 Node |
| 删除 `delete` | 一个或多个 Node → 空集 |
| 替换 `replace` | 一个或多个 Node → 一个或多个 Node |

拆分、合并、改名、op 成员或 anchor 更新都使用 replace。原位更新保持 ID；
新对象分配新 ID，删除的 ID 不复用。前后版本由 trace 的事件顺序区分，
不向 Node 添加来源角色、投影或多种 Node 类型。

pass 在实际变换现场给出原因，通过统一修改接口维护树并记录前后完整 Node
定义。事件包含顺序、操作、原因、前后 ID、名字、parent、实际 op 与 anchor
引用。未变化 Node 隐含保留。独立重放仅消费 before 和事件，actual after
作为核验对象；漏掉库存变化的事件、非法前态、重复创建和重复成员引用均不能通过。
这里重放的是 Node 的身份、名字与成员引用，不是完整 operation/value 内容，
也不证明电路行为等价；原位 op 内容改写由现场显式触发同 ID replace。

## 原生接口与持久化

`Graph::semanticNodeState(id)` 返回唯一的 Node 定义：

```text
SemanticNodeState {
    id, parent, name,
    operations: [OperationId...],
    anchors: [ValueId...]
}
```

`Graph::replaceSemanticNodes(beforeIDs, afterStates)` 是统一修改入口；
`addSemanticNode`、`eraseSemanticNode`、`renameSemanticNode` 提供同一编辑语义的便捷接口。
after 中 ID 为 0 的定义分配新 ID；非零 ID 只能来自 before，表示保留身份。
变更前核验名字、Path、实际实体引用与 ID；修改同步更新 op/anchor 的正反成员关系。
多个 Node 可以共享同一个实际 op。名称索引按需构建，不为每次修改扫描整树。

JSON v5 新增可选的 `nextNodeId` allocator 高水位，防止保存、加载后重新使用
已退役 ID；旧 v5 未带此字段仍可读取。运行时 trace observer 不序列化或复制到克隆图。

`SemanticNodeEvolution` 在 pass 的真实改写范围执行
`begin(reason) → 实际修改 → commit()`，由 Graph 的修改通知捕获受影响前态。
仅改变 op 内容而不改变成员引用时，pass 调用 `touchOperation` 生成同 ID replace。
回滚实际 IR 和成员后取消事务，不发布临时状态。关闭 trace 仍执行相同的 Node
维护，无 trace observer、trace 快照或输出。

新 trace 使用 `wolvrix.semantic-node-evolution.v1` 与
`semantic-node-replace.v1`：header 保存静态 Path 上下文；`node` 行保存 before／after
库存；`event` 行保存递增 seq、action、reason 及完整 before／after 定义；
op/value 引用保存原生 ID 和 generation。成功 footer 声明 `complete`、
`replayComplete` 及库存／事件数量。producer 用磁盘快照缓存核验库存闭合，
独立消费者只从 before 与事件重放，再与实际 after 比较。

trace 内的 op ID 是运行时 ID，StoreJson 可能重新编号导出 op，不能直接用两个
文件里的裸 op 数字做对应。F29 的重放直接核验 trace 自带的实际 after 库存。

## 两个 pass 的身份规则

`comb-loop-elim` 的 slice retarget 与物理 bit fragmentation 改写 Node 内部
实现，保留命名计算对象的 ID。partial fragment 不是原 Node 的完整输出
anchor；最终完整重组视图才可以接替该 anchor。共享 op 的多个成员关系必须
同步维护。失败修复使用 SCC 局部 journal 回滚实际变更，不能发布临时 Node
或残留成员；不为每次修复复制整张图。环外 consumer 的操作数被改写时，也记录
其所属 Node 的同 ID replace。

修复中增加 `replaceImplementationResult`：只修改实际 def/result 边，不把
原输出的完整 Node anchor 移给第一个局部 fragment。完整重组成功后才转移
原 anchor，避免 fragment 冒充整个命名输出。

`split-static-array` 真正成员化一个命名数组时，将父 Node 替换为新的同层
成员 Node；消费者自身的 ID 保留，只替换其实现。寄存器 current/next
分别成员化并维持实际状态对应。多维成员按行主序命名，size-one 轴遵循
GSIM 的省略规则。端口、memory、动态访问及不能支持的对象保留明确边界。

全部成员都建立，例如 `a: UInt<8>[2]` 只有 `a[0]` 被读，也产生
`a_0` 和 `a_1`，而非只为读取位置建立一个 Node。`r/r$NEXT` 成对替换为
`r_0/r_1/r$NEXT_0/r$NEXT_1`。flat 树中的成员仍直接连接根。
新成员按实际 anchor／writer 实现锥收集 op，不把旧数组全部 op 分配给每个成员。

具名 alias 是实际 Node DAG 边界：`a → b=a → b[index]` 中，`a` 可以拆分，
但 `b` 保留，`b[0]` 也保留对 `b` 的读边界，不绕到 `a_0`。
旧 packed scaffold 仍供未拆 alias 使用时，转交给真实 consumer；旧数组的
op 集合已清空就退役其 Node，并解除旧 anchor 成员关系，同时保留仍存活的 IR value。
本次产生的无用纯 scaffold 局部回收，不运行全图 DCE。

current／next／别名 family 的名字变化在发布前一起检查；冲突使整族保留，
不会发布半组成员。尚有不能解释的非 scaffold 实现时，显式保留 residual 父
Node 并单列计数。已知不支持的条件在变更前检查；意外异常不承诺整张 IR 回滚，
失败 trace 不写成功 footer。更完整的支持矩阵见
[split-static-array](../../wolvrix/docs/transform/split-static-array.md)。

## GSIM 对照边界

GSIM 正常流程为 Init → SplitArray → DetectLoop → TopoSort。
splitArray 包含数组依赖破环和 optional split，detectLoop 只检查。
GRH 在 comb-loop-elim 后先核验 Node 内部变化，再以两个 pass 完成后的
Node 库存对照 GSIM SplitArray 的实际存活 Node。

修正 GSIM 的 SplitArray dump：不再包含 DEAD 父 Node，并加入实际存活的新成员。
原生 trace 顶层事件统一为 add/delete/replace，保留内部 split／rewrite／retain
步骤和实际字段 mutation；未变对象的保留用 identity replace 表达。

GSIM 新增原生 `nodePath`，在真实 split／rename 现场更新当前身份名字，原始
`semantic.path` 继续保存来源名字。变化后缀按需分配，不为所有 Node 复制整条路径。
跨端优先用 `nodePath` 定位候选，再比较实际成员子图或原生演化关系。
数字 ID 只在各端内部有效，名字相同本身不证明实现相等。

## 验证与记录

生产链现在支持：

```text
FIRRTL ingest → xmr-resolve → hier-flatten
             → comb-loop-elim → split-static-array
```

两个 pass 在正常运行时直接维护 SemanticTree，外部脚本只用于回归、导出比较
与证据核验。后续未迁移 pass 仍拒绝新树；本次未扩展到 DCE 及更后阶段。

所有构建、回归与采集经项目 Make 入口，日志及临时产物位于
`ptmp/firrtl-ingest/F29/`。

```sh
make test_f29_semantic_nodes
make test_f29_node_replay
make test_f29_gsim
make test_f28_semantic_comparison
make test_f29_pipeline
```

采集单个输入可使用 `make capture_f29_semantic_tree F29_INPUT=...`，
随后 `make compare_f29_semantic_tree`。Python 中给任一个 pass 设置
`trace_semantic_nodes="ptmp/.../pass.{graph}.nodes.jsonl"` 即开启正常流程中的
可选 trace；多图路径须含 `{graph}`。旧 F27 的 `trace_node_evolution`
保留为物理兼容流，不能用于新版 SemanticTree。

实测结果与未核实项见下方验收记录。

## 早期原生格式验收记录（历史）

原生 CTest **22/22 通过**（最终一轮 15.92 s）。覆盖核心 1→2→1 编辑、共享
op、错误名字／引用拒绝、已退役 ID 与 JSON 保存加载、trace 事务／重放，以及
两个 pass 的新树路径；另包含 8 种无事务 erase 拒绝后 IR 不变的场景。
comb 回归明确覆盖“环外 consumer 的成员与 anchor 不变，但输入实现变化”时
仍必须出现同 ID replace。split 回归覆盖旧父 Node 已退役而 packed value
仍被保留 alias 使用。

独立 Node 重放 **10/10**，比较器 **22/22**，位向量规范化 **20/20** 通过。
重放负例包括遗漏事件、错误前态、非法 action／cardinality、重复成员、复用
退役 ID 和未完成 trace。GSIM 的 evolution／lifecycle／replay、source inventory、
semantic lineage 与 expression inventory 目标通过；主演化样例为 19→23 Node，
11 个原生事件、15 个字段 mutation，实际后态精确重放。

另直接读取 C++ 实际改写产物独立重放，避免只验证未变化的 comb 库存：
scalar false-loop 为 **7→7** Node、array false-loop 含环外 consumer 为 **8→8**，
两者各 1 个 replace；状态拆分为 **2→4**、1 个 replace，三条 trace 均精确重放。
`test_f29_semantic_nodes` 已包含这项核验，产物为 `tests/native-trace-replay.json`。

本节记录当时正常入口的 7 个 FIRRTL fixture：分别运行 trace 关闭和开启两次，
flatten／comb／split 三个阶段的 GRH JSON 完全一致；14 条 GRH pass trace
均独立重放闭合，7 条 GSIM 原生 trace 也精确重放。7 个 fixture 的 comb 阶段
没有实际 Node 修改，实际 false-loop 改写由上述 C++ 样例单独覆盖。

以下 before 为 GRH flatten／GSIM Init，after 为 GRH comb+split／GSIM SplitArray：

| fixture | GRH before→after | GSIM before→after | after 唯一候选 | after 结构核实 |
| --- | ---: | ---: | ---: | ---: |
| f28-arrays | 9→10 | 9→10 | 10 | 5 |
| f28-bundles | 19→19 | 19→19 | 19 | 15 |
| f28-state | 13→15 | 14→16 | 15 | 4 |
| f28-hierarchy | 17→17 | 17→17 | 17 | 6 |
| f28-comb-boundaries | 11→11 | 11→11 | 11 | 7 |
| f28-memory-effects | 17→17 | 18→18 | 15 | 4 |
| node-evolution | 19→23 | 19→23 | 23 | 8 |
| **合计** | **105→112** | **107→114** | **110** | **49** |

以 GRH after 的 **112** 个 Node 为分母：唯一 GSIM 候选 **110/112 = 98.2143%**；
已核实归一化类型／连接结构 **49/112 = 43.75%**；尚未核实结构 **61**，
未配对 **2**。这里的结构核实仍以已配对 anchor 为前提，不证明 X/Z 行为。
after 全部 **289 个实际 GRH op** 有 Node 成员关系，覆盖 **100%**；flatten
阶段同样没有未归属 op。一个 op 可以有多个 Node owner，不以成员边数替代 op 数。

从 **105 个 GRH before Node** 比较原生演化关系：**99 一致、4 逐父身份未核实、
2 未配对、0 已确认关系不同**。未核实的 4 个是 f28-state 的
`array/array$NEXT` 及 node-evolution 的 `state/state$NEXT`：整组替换可精确
重放，但 2→4 未给逐父子映射。未配对的 2 个是 f28-memory-effects 的
`delayedReader$ADDR0/delayedReader$ADDR0$NEXT`。它们也解释了候选缺口。

数组 alias 回归中，旧 `staging` Node 已消失，`staging_0/staging_1` 存活，
GRH 与 GSIM 都为 **9→10**；保留 alias 的 `staticRead` 边界结构也已核实。
不会把仍供 alias 使用的 packed value 当成必须保留旧 Node 身份的理由。

日志：`native/tests/test.log`、`tests/consumer-final-v2-command.log`、
`tests/gsim-final-command.log`、`tests/pipeline.log`。汇总为 `pipeline/summary.json`；
逐 Node 状态在 `pipeline/<fixture>/comparison-split-static-array/grh-nodes.tsv`，
原生演化关系在 `pipeline/<fixture>/trace-relations/node-relations.tsv`。
以上路径均相对 `ptmp/firrtl-ingest/F29/`。

## 公共 SemanticNode 交换格式

用户在本轮明确：Node 和连接是**插桩时刻的静态快照**，evolution 是 **pass
自身运行中产生、结束后导出的轨迹**。不把静态文件设计为跨 pass 的历史版本库。
一次 pass 用五个文件刻画：

```text
before.nodes.tsv
before.connections.tsv
evolution.tsv
after.nodes.tsv
after.connections.tsv
```

也可独立插桩只输出 `nodes.tsv` 与 `connections.tsv`，无需启用 trace。
内部 op/ENode 不进入公共文件。初版原生写 UTF-8 TSV；消费者可原样导入 SQLite，
导入器不生成 Node、不猜连接、不从 after 补事件。

### 静态 Node 与连接

Node 列固定为 `node_id, name_path_json, native_name`。
node_id 是本端实际 Node 的稳定身份，删除后不复用；不增加 version 字段。
name_path_json 是当前名字的 token 数组，不含 graph 根；无可靠名字时为 NULL。
GRH 用可逆 flat 路径，GSIM 用当前 identityPath，不能按下划线猜层级。
native_name 仅供诊断；跨端数字 ID 不相等，名字相同也不证明计算等价。

连接列固定为：

```text
connection_id  source_node_id  target_node_id  kind  resolution  candidate_sources_json  reason
```

kind 为 `dependency/state_update/storage_read/storage_write/external_binding/unknown`。
dependency 表示实际实现读取了源 Node 的输出，包含数据、条件、索引、clock/reset
等，不记录内部操作数位置、次数或位段。state_update 为 next→current 的跨时刻
提交，storage_read 为 storage→reader，storage_write 为 writer→storage。
黑盒绑定按实际边界方向，不把任意输入连到全部输出。调度约束不是公开数据边。

resolved 连接有唯一 source，candidate_sources 为 []，reason 为 NULL；按
`(source,target,kind)` 去重。unresolved 的 source 为 NULL，candidate_sources
保存按 ID 排序去重的原生候选，reason 必填；它是诊断对象，不是已经成立的边。
诊断按 `(target,kind,candidates,reason)` 去重，不展开候选的笛卡尔积。
unknown 只能 unresolved。真实自引用保留，但 output anchor 本身不制造自引用。

connection_id 在一次 trace 中稳定；连接定义改变时删旧加新，ID 不复用。
单独采集的两份 snapshot 不要求独立分配的 connection_id 相同，比较时使用公开
端点与 kind；同一个 trace 的 before/evolution/after 必须使用同一连接 ID 空间。

每份静态表第一行是 `#meta<TAB>{紧凑JSON}`，第二行是 TSV 列名，最后一行是
`#footer<TAB>{紧凑JSON}`。meta 包含 schema=`semantic-node-exchange.v1`、engine、
run_id、graph_id、exchange_session_id、snapshot_id、stage、table；这些身份为
非空字符串，同一时刻的两表共享 snapshot_id。footer 包含 complete、rowCount，
Node 表另含 nodeInventoryComplete，连接表另含按类别统计的 connectionCoverage。
meta/footer 中的 JSON 不额外 TSV 转义；普通单元格对反斜杠、tab、LF、CR 使用
`\\/\t/\n/\r` 转义，NULL 为 `\N`，空串与 NULL 不同。JSON 单元先紧凑编码，
再做 TSV 转义。文件使用 UTF-8、LF，库存按 node_id／connection_id 排序。

### pass 原生 evolution

固定列为：

```text
record  seq  ordinal  action  reason  subject  side  object_id  detail_json
```

| record | 含义 |
| --- | --- |
| header | seq=0/ordinal=0；detail 含 schema、命名空间、pass、mode=trace、before_snapshot_id、after_snapshot_id、输入身份 |
| event | seq=1..N 连续，ordinal=0；action 为 add/delete/replace，reason 为实际改写原因 |
| edit | subject=node/connection、side=before/after；object_id 与 detail 中完整公开定义的 ID 相同 |
| lineage | 可选；subject=node、side=before、object_id 为父；detail 含 to_node_id、relation=split/merge/derive 和可选 coordinates |
| footer | 最后 seq 的末尾；含事件数、before/after 的 Node 与连接数量、coverage、complete/replayComplete |

同 seq 所有行共享连续 ordinal。edit 的 detail_json 保存完整对象定义，字段
与对应静态表一致，但 ID 为 JSON 整数，name_path_json/candidate_sources_json
为 JSON 数组／NULL，而非二次编码的字符串。无需引用 after 文件来补齐定义。

add 的 before 集合为空，delete 的 after 集合为空，replace 两侧均非空。
集合包含 Node 与连接，支持任意 M→N；未被引用的对象隐含保持。
同 ID 实现变化即使公开 Node 行完全相同也可记录同 ID replace。
Node 退役时 incident 连接和 unresolved 候选必须显式处理，不允许消费者隐式
cascade。连接定义变化一律删旧加新。同一原子事件提交后的所有端点必须存活。

多对多替换只证明整组变换，不自动建立旧父×新成员关系。lineage 仅来自真实
split/merge 现场；消费者原位改写不会因此成为新成员的父。状态 current/next
各自记录原生父子映射。消费者检查血缘端点属于同一事件对应侧，但省略内部
实现后不能独立判定任意形式合法的映射真伪，现场正确性另由原生回归验证。

### 插桩与校验边界

正常流程维护命名 boundary reference，导出开关不决定维护是否发生。
GRH 多个 Node 共享同一 anchor 时，必须使用真实具名引用／use 证据区分 source；
不能取第一个 owner 或做 owner 笛卡尔积。flatten/xmr 重定位、comb/split
的真实引用替换要同步维护。GSIM 从当前生效表达式与 state/storage/external
字段取连接，不能直接复用包含调度约束的 prev/next。

pass 内 begin/touch/split/commit 记录真实变化，事件暂存于私有 journal，
pass 结束后导出 evolution。事务可覆盖一个实际原子改写，GSIM 拆分状态族时
可覆盖整个 splitArray，以免半组配对状态对外暴露。提交时据实际修改现场的
dirty 对象和原生前后状态确定 delta，不能靠最终两个 dump 离线猜变化原因。
after 静态表独立从实际原生状态采集，不以 replay 缓存冒充。

校验严格按以下方向进行：

```text
before.nodes + before.connections + evolution
        → 独立重建 Node / connection 库存
        → 与实际 after.nodes / after.connections 逐字段比较
```

校验器先完成重放再打开 after，检查完整前态、action/cardinality、ID 退役、
显式连接删除、唯一连接与血缘引用。零事件 pass 同样能导出五文件并核验。
两个 snapshot 可单独验证完整性，不要求启用演化追踪。

nodeInventoryComplete、connectionCoverage 与 replayComplete 分别报告：
重放已导出对象完整不代表所有真实连接已覆盖，也不证明隐藏实现或行为等价。
比较分别报告 Node 候选、resolved 连接和有证据的血缘，不用名字候选率代替
整个图的对齐率。大图校验使用 SQLite；不把内部 op/enode 库存导进公共表。

### 双端使用入口

GRH 的导出直接读取当前 SemanticTree 和实际 IR。假设 `session` 的
`design.main` 已运行至 flatten，可独立取静态快照，也可围绕一个 pass 记录：

```python
session.semantic_snapshot(design="design.main", output="ptmp/f29/flatten",
                          stage="hier-flatten")
session.semantic_exchange_start(design="design.main", output="ptmp/f29/split",
                                stage="before-split", pass_name="split-static-array")
session.run_pass("split-static-array", design="design.main")
session.semantic_exchange_finish(design="design.main", stage="split-static-array")
```

`comb-loop-elim` 使用相同接口。多个 top 时传入 `top`；每张图只能有一个活动
recorder。静态导出不要求 recorder；开启 recorder 不要求旧 JSONL trace。
中途失败或没有 finish 不发布成功 evolution。C++ 对应
`writeSemanticSnapshot` 和 `SemanticNodeExchange`，头文件为
`wolvrix/include/core/semantic_exchange.hpp`。

GSIM 的原生 CLI 支持：

```sh
gsim --semantic-node-exchange=ptmp/f29/gsim-split \
  --semantic-node-exchange-mode=trace --stop-after-stage=SplitArray input.fir
gsim --semantic-node-exchange=ptmp/f29/gsim-init \
  --semantic-node-exchange-mode=snapshot --semantic-node-exchange-stage=Init \
  --stop-after-stage=Init input.fir
```

snapshot 可选 Init 或 SplitArray，只写两份静态文件，不挂 pass 运行 observer；
trace 记录 Init→SplitArray 的现场事务并写五份文件。GSIM 的 SplitArray
同时包含数组依赖破环与拆分，不虚构独立的 comb pass。

双端产物使用同一个消费者校验。SQLite 是对已导出对象的存储，可供查询；
它不参与生产 Node 或补全演化：

```sh
make verify_f29_exchange F29_EXCHANGE_BUNDLE=ptmp/f29/split \
  F29_EXCHANGE_ARGS='--database ptmp/f29/split.sqlite --report ptmp/f29/split-report.json'
make verify_f29_exchange F29_EXCHANGE_BUNDLE=ptmp/f29/flatten \
  F29_EXCHANGE_ARGS='--snapshot'
make test_f29_exchange_contract
make test_f29_exchange_gsim
make test_f29_exchange_pipeline
```

数据库保存 before/after/current 的 Node、连接及原始 evolution 行；公共重放
不需要内部 op/ENode。上方早期验收数字属于旧原生格式，公共格式结果另列。

### 公共五文件验收

公共格式契约回归 **24/24** 通过：覆盖拆分、合并、增加、删除、仅连接变化、
同 ID 实现变化及零事件；遗漏事件、错误前态、篡改 after、悬空 incident 边、
复用退役 ID、非法 lineage、伪造 coverage、未完成文件与非法换行均拒绝。
错误前态用例同时删除 after 文件，确认校验失败发生在打开 after 之前。

正常入口的 7 个 FIRRTL fixture 共验证 **21 组五文件产物**：GRH 的 comb 和
split 各 7 组，GSIM 的 SplitArray 7 组，全部精确重放。另独立导出并验证
**42 组两文件静态快照**，与对应 trace 时刻的 Node 和连接定义一致。
GRH 插桩开启／关闭时三个阶段的完整 JSON 逐字节相同；GSIM 原有
trace 关闭／开启输出比较及 Node evolution／lineage／inventory 回归也通过。

最终安装产物复跑后的跨端摘要如下。Node 数量和连接数是各端自己的静态库存；
`matched` 只统计按公开路径建立候选后、端点与 kind 相同的 resolved 连接，
不表示内部 op/ENode 或时序行为等价：

| fixture | GRH Node | GSIM Node | GRH resolved | GSIM resolved | GRH unresolved | matched |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| f28-arrays | 10 | 10 | 10 | 10 | 0 | 10 |
| f28-bundles | 19 | 19 | 19 | 19 | 0 | 19 |
| f28-state | 15 | 16 | 18 | 23 | 0 | 14 |
| f28-hierarchy | 17 | 17 | 16 | 16 | 0 | 16 |
| f28-comb-boundaries | 11 | 11 | 13 | 13 | 0 | 13 |
| f28-memory-effects | 17 | 18 | 25 | 26 | 0 | 16 |
| node-evolution | 23 | 23 | 25 | 32 | 2 | 25 |

状态／memory 的连接差异是两端当前 IR 表示差异；`node-evolution` 的两条
unresolved 是缺少精确片段投影证据时的保守诊断。它们没有被候选名称或笛卡尔
积伪造为 resolved。nested register-read 的 producer、动态 index/guard 和
真实 self-reference 已由 native boundary 回归覆盖；writer 自身 anchor 不会
再制造伪自边。

原生 CTest **22/22** 通过。C++ 实际 false-loop scalar／array 改写的公共文件
也由同一独立消费者精确重放，回归包含 fragment 输入重排时的真实具名引用、
失败回滚及环外 consumer。公共 split 样例额外验证逐父 lineage 和同 ID touch；
writer 内部消费自身 anchor 不生成自边，带原生 self-reference 证据的自边保留。

公共文件与报告位于 `ptmp/firrtl-ingest/F29/exchange-pipeline/`；
`summary.json` 保存每个 fixture、每个 pass 的完整重放结果及静态 coverage。
GRH 产物在 `<fixture>/grh-traced-{comb-loop-elim,split-static-array}/`，
GSIM 在 `<fixture>/gsim-trace/`。日志位于同级 `tests/` 下：
`exchange-contract-final-command.log`、`exchange-native-final-command.log`、
`exchange-pipeline-final-command.log`、`gsim-snapshot-independent-command.log`、
`exchange-gsim-regression-command.log`。

## 证据边界与后续项

Node 库存匹配、演化关系一致、成员锥结构相符是三个不同结论。重放通过只说明
before 加原生事件完整解释 after 的 Node 定义；跨端演化关系相符也不能代替
op／ENode 结构或电路行为核验。四态 X/Z、状态、memory、效果及不能规范化的
结构继续保留 unverified，不能合并到“全部语义已对齐”的比例。

多对多 replace 保证整组 Node 可重建，但未记录逐父成员映射时，不从名字后缀
推断对应。例如 current／next 的 2→4 替换，逐父演化仍标为 identity-unverified。
memory 读地址的状态边界仍需单独确定两个阶段的对应关系。

另有两个保守或表示边界：跨状态 family 的 whole-array 依赖可能因另一 family
尚未拆分而保留；复用本 pass 新建的 scalar view 可以形成真实 op 共享，但其
成员锥边界可能比 GSIM 的 alias 引用更宽。相关对象仍需结构核验，不能仅用
库存数量确认对齐。

本次验收范围为 7 个真实 FIRRTL fixture；没有运行 F29 的整机 SimTop 比较。
F28 已记录的整机比例仅描述 flatten 阶段，不能移用为本阶段结果。

## Trace 性能调查

确认并修复了三处 recorder 热路径。Semantic connection traversal 不再在每次
事务提交时扫描全部 op/value 以确定标记数组上界；访问标记按实际 ID 扩容，
并在一次 exchange 中复用。split-array 每个成员的 lineage 去重从线性扫描改为
有序键索引，提交时的 before/after 端点检查改为预建 ID 集合。另将
`validate_at_finish=false` 改为真正跳过结束时的全图重算和重复库存核验，footer
直接使用 exchange 已维护的连接库存；开启校验时仍执行完整核验。Boundary-use
四类反向索引也改用 row→bucket-slot 和 swap-pop 删除，避免高扇出引用批量删除
时反复压缩 vector。后者适用于有无 recorder 两种运行。

新增 benchmark 的单侧模式直接使用 ingest/flatten 得到的图；只有 `both`
模式才克隆同一图给 no-trace 和 trace 两侧。`node-evolution.fir` 三次顺序测量的 split
中位数为：no-trace pass **0.1689 ms**，trace pass 内部 **0.2367 ms**，增加
**0.0678 ms / 40%**；trace setup **0.1150 ms**，finish **0.0934 ms**，含导出的
阶段总计 **0.4577 ms**。之前单次数据为 pass 0.2679 ms、setup 0.1554 ms、
finish 0.1241 ms、总计 0.5488 ms；方向上约减少 17% 的 traced 阶段总耗时，
但前后样本数不同，不能当作严格 A/B 加速比例。小图中 recorder 的固定快照
及文件写入仍大于 pass 本身。

同一输入的 SimTop 全图尝试记录到：1.671 GB FIRRTL ingest **43.70 s**、
XMR **0.46 s**、hier-flatten **62.06 s**、flattened graph clone **28.33 s**；
no-trace `comb-loop-elim` **22.57 s**，峰值约 **87.3 GiB**。no-trace
`split-static-array` 持续单核计算超过 **10 分钟**，没有返回，因此停止了该次
基准，尚未开始 trace 侧。这个全图尝试不能说明 trace 的完整 SimTop 开销；它
说明当前无法用该输入给出 split 的 trace/no-trace 对比。后续应先定位这一
no-trace split 长耗时，再做完整全图 A/B。

验证：F28/F29 原生 CTest **22/22**；原生五文件 pipeline 测试通过；上述
NodeEvolution comb/split 包均由公共消费者验证为 `replay_exact=true`。小图计时、
全图中断记录及验证日志分别位于
`ptmp/firrtl-ingest/F29/trace-performance-fix-node-evolution/`、
`ptmp/firrtl-ingest/F29/trace-performance-fix-simtop/` 和
`ptmp/firrtl-ingest/F29/trace-performance-fix-validation/`。

2026-11-13 再次只测 no-trace `split-static-array`，输入 SHA256 与上次相同；
ingest **43.51 s**、XMR **0.46 s**、hier-flatten **61.46 s**、克隆 **28.28 s**。
split 再次运行超过 **10 分钟**且没有返回，随后停止；因此仍没有 pass 完成时间，
也没有启动 trace 对照。单独 no-trace 模式由
`F29_PASS_TRACE_MODE=no-trace` 选择。summary 和完整日志在
`ptmp/firrtl-ingest/F29/retest-split-no-trace-20261113/`。

### 大图性能门槛（2026-11-14）

后续性能验证只使用原始 `build/xs/rtl/rtl/SimTop.fir`（1,671,325,062 bytes，
SHA256 `b313a3ecd154cbd9279b14403709806b95fb136cf44b475e9def46a926ecb26b`），
重新执行 ingest、XMR 和 flatten，不读取 checkpoint，不再用小图作为性能依据。
F24 v14 的历史 split 耗时为 **24.522773 s**，本轮使用四舍五入后的
**24.523 s × 2 = 49.046 s** 作为 split 单独的硬超时；超时立即判失败。
旧基准来源为 `ptmp/firrtl-ingest/F24/full-native-v14/logs/`
`xs_firrtl_stage_full-native-v14.jsonl`，是历史记录，不是当前源码的 A/B 测量。

`make benchmark_f29_pass_trace` 默认通过 `py_install` 更新原生库；报告同时
记录实际加载的 `_wolvrix.so` 和 `libwolvrix-lib.so` 的路径及 SHA256。
超时由独立 watchdog 进程执行，避免 C++ 持有 Python GIL 时无法及时中断。
只对 `session.run_pass("split-static-array")` 计时，前序、trace setup/finish
分别记录。`F29_PASS_TRACE_SKIP_COMB=1` 仅用于隔离 split 的诊断；默认运行
正常的 `comb-loop-elim → split-static-array` 前序。

| 大图诊断版本（no-trace，skip-comb） | ingest | flatten | split | 结果 |
| --- | ---: | ---: | ---: | --- |
| `indexed-members-20261114` | 43.629 s | 60.920 s | 49.095 s | 超时失败 |
| `indexed-bindings-20261114` | 43.032 s | 61.710 s | 49.094 s | 超时失败 |
| `indexed-declarations-20261114` | 43.788 s | 60.910 s | 49.095 s | 超时失败 |

上述失败产物在 `ptmp/firrtl-ingest/F29/<版本>/`。49.09 s 是 watchdog
实际终止时刻，不能当成 pass 的完成耗时。每次超时都会写入失败的
`summary.json`、`no-trace/timing.json` 和 `split-timeout.marker`。

`indexed-declarations` 的大图分段计时进一步确认：后段共享 op 的 owner 列表
约有 **8.5 万项**，每个数组的准备、选择和 cone 迁移仅几十微秒，而
`finish()` 用约 **8～11 ms** 重复复制、去重和发布整条 owner 列表。这是
修复声明表删除后仍超时的主要证据。

针对该路径新增 `Graph::updateOpSemanticIds(op, removed, added, preserveOrder)`：
默认保留已有 owner 的顺序，仅为本次增删建立查询表，按净变化维护反向 membership 和
observer；不再为整条旧/新列表反复建立哈希集合。split 的 `finish()` 直接
保留已有外部 owner，只补充 result 或实际下游推导出的新 owner。父 Node
删除、anchor/connection 清理和名称释放仍按原时序执行。另将 Graph 声明
符号表改为 slot 索引与 swap-pop 删除，SemanticBinding 按 Node 建立清理
索引，连接反推按 ValueId 索引 target 的引用。这些修改尚需以下大图完成
结果确认，不能以中途进度代替通过。

后续正常前序（包含 comb）的大图运行同样执行 49.046 s 门槛；
`owner-delta-normal`、`mutable-owners-normal`、`empty-bindings-normal` 和
`leaf-fast-normal` 仍全部超时失败，尚无这些版本的 split 完成时间。comb
分别完成，并通过整张图的 SemanticTree 结构校验；split 超时时不执行结束校验。
`empty-bindings-normal` 第一轮成员化的汇总为 prepare **3.65 s**、select
**8.43 s**、anchor **6.88 s**、finish **6.93 s**、cleanup **9.45 s**。

因此进一步将共享组合 scaffold 的归属更新显式设为集合更新，用专属块的
owner→slot 索引执行增删；状态 declaration/port 仍走保序路径，避免改变
state-family 的命名规划顺序。另为出边建立 value/user 索引，保留原匹配顺序；
空 SemanticBinding 索引立即返回，ArrayCreate 直接持有所选 operand，空叶
Node 创建省去通用 replacement 的临时集合与重复名称校验。性能验收仍以
原始大图完整返回和校验结果为准。

后续检查还发现静态选择的归属传递错误：`x = a[0]` 改写时，通用
`inheritOrigin` 会把 packed producer 的 `{a[0], a[1], ...}` 全部合入读取
op 的 consumer owners；`selectionBoundary` 只能替换旧 parent，无法清掉
无关的成员。这既污染 Node 的 op 集合，也可能在每个元素上反复合并整条
owner 列表。split 私有元数据 helper 现独立继承 `originModules`，原地改写
保留 consumer owners，只由 `selectionBoundary` 执行精确的 parent→member
映射；新建 view 仍按 source/projection 显式设置 owners。共享
`inheritOrigin` 的其他调用者未改变。

`F29_PASS_TRACE_PROFILE_SPLIT=1` 可对同一原始大图仅采集 split 的 perf 栈，
仍执行 49.046 s 硬超时；采样准备和收尾在 pass 计时之外。符号快照校验
已加载库与未剥离构建库的 `.text` 一致，分析产物全部写入本次运行目录。
`make report_f29_split_profile F29_PASS_TRACE_WORK=<运行目录>` 生成报告。
采样结果属于诊断，最终性能验收仍需同库的无采样完整运行。

大图 split 的首次有效 perf 记录为 `perf-projection-20261114`：4K 样本、
0 lost samples，约 46.69 CPU s，仍在 49.046 s 硬超时失败。主要 self
热点为 anchor（6.27%）、SelectionKey 链式哈希查找（5.91%，另 hash
2.03%）、operand use 删除（4.09%）和 OperationId 集合插入（3.85%）；
增量 owner 更新本身为 0.56%，没有证据再把它当作当前唯一瓶颈。

随后 `flat-selection-20261114` 无采样大图仍超时，但第一轮 select 从
8.45 s 降到 **6.34 s**、finish 从 5.80 s 降到 **4.76 s**；超时时静态
读取已扫描 29,360,128 / 30,464,365 个 op。后续将局部成员/连接查询和
四种 boundary 反向索引换为 flat map，保留 bucket 内 vector 次序；anchor
用 SmallVector 缓存已解析 parent/member，省去单元素临时堆分配和重复查询。

`GraphStore::eraseOperand` 改为删除目标 use 后更新后缀位置，避免每次完整
拆除并重建所有 operands 的 reverse uses。`Graph::validateUseLists()`
同步纳入通用 `grh.verify`，只读检查 operand、slot、user 的双向一致性；
大图 benchmark 可通过 `F29_PASS_TRACE_VERIFY_AFTER=1` 在 split 计时之外
执行完整 verifier。未运行小图基准或小图测试。

`flat-boundaries` 和 `direct-columns` 仍触发 49.046 s 门槛：后者第一轮
数组化约 **29.30 s**、state **3.53 s**、静态读取 **10.73 s**，已开始
第二次 fallback view 处理。`smaller-membership` 增加末段采样后确认：全部
读取改写已完成，超时发生在 final packed-view cleanup，其约 2.46 CPU s
样本中 **47.95%** 为 `SemanticTree::removeOperation`。据此为大 Node 的
随机非头删除懒建 entity→slot/previous 索引；小列表和连续删头仍走原快路，
成员迭代、释放 slot 及重复成员的首匹配删除语义保持原样。

公共 trace 进一步按输出内容缩减通知：纯 op membership 更新仅对无结果
的 effect op 触摸公共记录，因为公共 Node 不包含 op 列表；物理改写、
anchor、boundary、lineage 和 legacy observer 的通知继续保留。
commit 仍即时捕获原生节点/连接差量、校验 lineage、固定连接 ID 并更新
运行期缓存，再 move 到 journal；JSON/TSV 格式化移到 finish。journal
拥有完整数据，不借用最终 IR 反推历史。输出先写临时文件，flush/close
成功后发布，未完成的导出不产生成功 evolution 文件。trace setup、pass、
finish 分别计时；启用 `VALIDATE_AFTER` 时 finish 还会在计时外重新从实际
IR 生成全图连接并核对 trace 缓存。

`indexed-member-removal-20261114` 的变换主体在约 **48.85 s** 到达 done
marker，但临时对象析构结束、`run_pass` 返回前仍越过 49.046 s，因此依旧
是超时失败，未执行结束校验，不能用 marker 时间声称通过。后续将懒建
Node 名称索引由逐项分配的 unordered multimap 改为 flat hash→head 和
Node ID next 数组；完整 parent/name 比较处理哈希碰撞，公开 Node 布局、
名称唯一性校验、退休 ID 规则不变。另复用 cleanup queue 容量，临时小列表
使用 SmallVector，命名规划用完整键的 flat map，boundary target 去重与
追加共享一次 bucket 查询。所有临时对象析构仍在 pass 的计时及硬超时内。

**无 trace 大图首次通过**：`flat-name-index-20261114` 使用原始 FIRRTL 和
正常 comb 前序，ingest **42.812 s**、XMR **0.362 s**、flatten **61.497 s**、
comb **20.062 s**、split **46.473 s**（包含临时对象析构并完整返回），低于
49.046 s 门槛。split 后 SemanticTree 校验 **valid=true/error_count=0**
（7.097 s）；完整 `grh.verify` **passed**（12.861 s），包含新增 use-list
双向检查，两种校验均在 pass 计时外。峰值 RSS **75,436,924 KiB**，约
**71.94 GiB**。这仍为历史 24.523 s 的约 **1.895 倍**，不能称为已恢复
历史速度。完整 summary、实际原生库路径/SHA 和日志位于
`ptmp/firrtl-ingest/F29/flat-name-index-20261114/`。开启 trace 的完整大图
计时及双侧五文件回放/比较仍待完成。

`native-journal-trace-20261114` 首轮真实大图：comb pass **20.204 s**，
setup **22.845 s**，finish（含全量实际 IR 核验和导出）**20.068 s**，
SemanticTree 校验通过；comb 五文件已完整导出。split setup **22.817 s**，
但 pass 在第一轮 array-split commit 阶段触发 **49.046 s 超时失败**，
没有成功 split 五文件。采样约 46.32 CPU s、0 lost；全 pass touch 为
12.89%，连接向量扩容为 14.74%；提交段约 14.57 CPU s 中连接向量扩容
占 46.88%。因此继续优化运行期 pending/affected/lineage 查询和连接生成，
不能把 no-trace 通过当成 trace 也通过。

`flat-trace-pending-20261114` 将 pending/forced/lineage 查询换成 flat 容器，
affected 用追加后排序去重，保留原提交顺序。正常原始大图前序中 comb
pass **18.341 s**、setup **22.681 s**、finish **19.836 s**，校验通过；
split setup **22.609 s**，但 split 再次触发 **49.046 s 超时失败**。
第一轮提交有 **3,644,820** 个 pending Node，重算 **3,450,700** 个存活
target；仅处理前 **1,048,576** 个 target 就累计 **77,131,730** 条 raw
连接，而 setup 全图 **7,671,189** 个 target 只有 **14,946,542** 条 raw
连接、**12,986,525** 条 unique 连接。采样约 **46.36 CPU s**、0 lost，
连接向量扩容的 self 占比升至 **21.90%**。这次仍没有成功 split 五文件，
后续应提前消除每个 target 内完整语义相同的连接，不能删掉合法候选来缩小输出。

`target-compact-trace-20261114` 先尝试每个 target 结束时完整排序去重、
按旧连接数预留容量、移动归并差量，并为无 native value ref 的非 root
fallback 单独按值去重；仍在第一轮提交触发 **49.046 s 超时失败**。
提交段采样中连接向量扩容仍占 **49.86%**，说明等单个 target 完成再去重
尚不能控制临时连接膨胀。该版本没有完整 split 导出结果。后续将相同完整
连接的去重提前到 emit，哈希冲突必须以完整连接相等确认，不能用哈希值
代替语义身份。

benchmark 的异常路径也使用实际 `monotonic` 结束时刻完成 watchdog，
原子记录失败的 timing/summary；watchdog/perf 清理异常单独记录，保留
原始 pass 异常。正常返回、异常返回和超时都不能绕过独立的 split 门槛。

`emit-dedup-trace-20261114` 把完整连接去重提前到每次 emit，仍触发
**49.046 s 超时失败**，但首次取得整轮连接收集统计：**124,279,780**
条 raw、**121,110,794** 条 unique，含 **66,732,943** 次 resolved 和
**57,546,837** 次 unresolved emit；最大候选集合 **131**，单 target
最多 **18,435** 次 emit。因此之前“主要是重复连接”的推断不成立，
去重并不能消除这些不同的临时连接。

根因是公共事务边界早于一次完整 IR 改写：`array_split` 提交发生在 state
成员化、静态 slice 重写和 packed-view 清理之前。此时 Node 已拆分，
物理 slice 仍可连到整条 packed array，通用连接遍历会走其全部元素，
产生大量不代表 pass 最终图的依赖。GSIM 的公共 exchange 则在完整
`splitArray` 后提交一次。GRH 公共 exchange 因而改为完整
`split-static-array` 范围的事务：原生运行期间持续记录 touch、added 和
parent→member 坐标 lineage，最终清理后、pass 返回前提交。legacy
内部阶段 JSONL 的原 reason/commit 保留。lineage 端点仍须属于事务的
before/after，遇到不满足的链直接失败，禁止过滤、按最终名字补造，或
依赖离线脚本推断。这项改动的最终耗时与连接结果仍需原始大图验证。

`pass-scope-trace-20261114` 已实际运行完整 pass 事务：原始 ingest
**42.575 s**、flatten **58.831 s**、comb **19.054 s**。split 已完成
state、全部静态读取及最终 packed-view 清理，随后进入最后公共提交，
但尚未完成就再次触发 **49.046 s 超时失败**。不能把 rewrites-done
当作 pass 成功，也没有完整 split 五文件。该轮不再提前构造 1.21 亿条
中间态连接；进一步根据采样优化最终提交及普通 IR 追加成本。

分页列检查发现 `PagedColumn::resize` 每次扩大时精确 reserve 页目录，
目录容量耗尽后每新增一页（256 行）都会搬迁全部既有目录，破坏几何增长；
`emplace_back` 又先默认写新行再覆盖实际值。现恢复页目录几何增长，
追加只写一次，保留 saved 的别名保护、共享页 COW、shrink 和复制统计。
边界反向索引小 bucket 使用内联两项的 SmallVector，保留索引顺序与
对外 span；仍需下一轮统一原生库的大图验证实际收益。

`geometric-columns-trace-20261114` 的新库完成原始 ingest **42.908 s**、
flatten **60.503 s**、comb **18.992 s**，comb 校验通过。split 再次触发
**49.046 s 超时失败**，但最终公共提交已完成 Node 差量和旧连接整理，
开始重算 **3,713,480** 个存活 target；处理 **2,097,152** 个 target 时
raw 为 **6,323,608**，已消除之前第一轮过早提交的上亿条临时连接。
此时仍未完成提交，没有最终 split 五文件。分页 resize 已不再是主要采样
热点；接下来优化普通 operand 批量改写、boundary 索引和最终只读连接遍历，
仍保持同一超时门槛。

`bulk-parallel-trace-20261114` 通过正常构建安装后使用原始大图：ingest
**41.245 s**、flatten **58.262 s**、comb **18.522 s**，comb 校验通过。
主体采用批量 operand 替换、metadata 单次扫描、target/source 稠密边界索引；
最终 fresh connections 对 **3,713,480** 个 target 用四个只读 worker
重算。主线程预建惰性索引，worker 独立持有 workspace，join 后归并排序，
setup 与实际 IR 核验仍串行。收集加归并约 **2.752 s**，得到 **9,027,194**
条受影响连接，随后差量计算也已完成。最终缓存发布仍触发 **49.046 s
超时失败**，尚无完整 split 五文件。下一步针对缓存发布减少重复索引维护，
不能将 fresh/diff 完成当作整个 pass 返回。

`bulk-cache-trace-20261114` 关闭 perf 采样，正常大图 comb **18.612 s**
并通过校验；split 仍触发 **49.046 s 超时失败**。最终 public diff 为
删除 **3,167,510** 条连接、创建 **7,898,317** 条连接，Node 变更载荷为
before **212,092**、after **1,803,591**。公开 Node、连接缓存已更新，
超时发生在 incoming 派生索引重建之前；尚未完整返回或执行结束校验。
四线程连接收集与合并约 **2.623 s**，结果仍为 **9,027,194** 条。
这些是阶段诊断计时，不是 pass 完成时间；本轮仍没有成功 split 五文件。

`final-cache-trace-20261114` 将最终提交后不再使用的 incoming/consumer
派生索引标记为脏，后续事务开始时才重建；公开 Node、连接、ID、lineage
和 journal 仍在 pass 返回前完整固定。原始 ingest **42.411 s**、flatten
**58.627 s**、comb pass **18.752 s**，comb 校验通过。split 完整返回
**48.413 s**，首次低于 **49.046 s** 门槛，但结束时从实际 IR 串行重算
发现 runtime cache 的连接内容不同，因此**整体失败，尚未成功导出 split
五文件**。双方连接数同为 **17,717,332**，相等的数量不能证明内容相等；
实际 split 后 Node 为 **9,262,688**，之前为 **7,671,189**。首个差异
target **5510199**（`...bankedDataArray._bank_addrs_0_1_T_1`）出现两个
候选来源。后续诊断须确认它是否进入受影响 target 集合，再修复原生变更
通知，不能跳过实际 IR 核验或从最终图补造 evolution。

`diagnose-cache-trace-20261114` 再次从原始 FIRRTL ingest，split 完整返回
**48.325 s**，但结束核验仍失败。`verification-differences.tsv` 全量归并
得到 **82 个 target、164 条双向差异**（actual-only 和 cached-only 各
82 条），全部 `target_recomputed=0`。首个实际候选为
`[5510197,8976803]`。这证明是受影响 target 漏通知，而非四线程重算与
串行核验结果不同。应记录连接提取时实际读取的 fallback value→target
关系（包括当时没有 owner 的 value），在原生 owner 或实现 cone 变化时
通知读者。补丁的正确性与耗时仍须同一大图及硬超时验证。

**带 trace 大图首次完整通过**：`fallback-readers-trace-20261114` 经正常
`make py_install` 构建新库，再从原始 **1,671,325,062 字节 SimTop.fir**
ingest，不读 checkpoint。ingest **42.216 s**，flatten **57.768 s**，
comb pass **18.732 s**。split 完整返回 **47.709 s**，低于独立硬超时
**49.046 s**；计时包含最终原生提交和同步析构。结束时串行遍历实际 IR，
对 runtime cache 的 Node 与连接逐项核验通过，SemanticTree 校验为
`valid=true, error_count=0`，含双向 use-list 的 `grh.verify` 通过。
split 五文件完整导出，目录为
`ptmp/firrtl-ingest/F29/fallback-readers-trace-20261114/trace/split-static-array/`。

修复采用连接遍历现场捕获的 fallback value→target 关系：初始
**20,552,145** 条读取，最终受影响部分捕获 **39,233,485** 条读取，
包括 owner 为空的值。紧凑反向索引在 value owner 或实现 cone 修改时
通知读者；同事务内每个 value 至多扫描一次读者链。最终重算存活 target
**3,713,562**，比失败版本增加的 **82** 个恰好覆盖诊断差异。
普通提交即使公开连接不变也替换读集合；最终提交保留已捕获读集合，
下一事务再更新派生索引。lineage 仍严格检查端点，使用已有有序载荷查询，
省去两个临时 hash set。没有从最终 IR 补造 evolution。

split 的 trace setup **23.256 s**，finish（含实际 IR 全量核验与 TSV
格式化/I/O）**35.658 s**，SemanticTree 校验 **7.069 s**，GRH verify
**12.575 s**，整体 **126.299 s**；这些计时与 **47.709 s** 的 pass
执行时间分别报告。此结果证明原生 trace 缓存与实际图一致，公共文件
消费者独立重放及 GSIM 对比仍须另行完成，不代表跨端全部对齐。

**同版本无 trace 大图复测通过**：`fallback-readers-no-trace-20261114`
重新从 FIRRTL ingest **41.425 s**、flatten **58.799 s**，没有读取
checkpoint 或克隆图。两轮输入 SHA256 及实际加载的原生库 SHA256 完全相同。
无 trace 的 comb **19.846 s**、split **39.199 s**；SemanticTree 和
`grh.verify` 均通过。split 开 trace 的执行时间增加 **8.510 s**
（约 **21.7%**）；两种模式均通过 **49.046 s** 独立硬超时。
上述比较不包含 trace setup/finish，不等同于开启导出的整体耗时。

随后 `full-split-fallback-readers-20261114` 的 GSIM 原始大图在 Init 后
导出失败：depth=1 scalar memory 降为 register 后，旧 writer 仍保留
`NODE_WRITER` 和指向 DEAD memory 的历史 parent，公共 extractor 误生成
`writer→dead-memory` 存储边。修复仅接受原生 `sourceReplacements` 可确认
且写表达式已迁移清空的旧 writer，停止生成这条过期关系；其他非法目标
仍报错。没有将已退休 memory 加回库存或虚构到 replacement 的连接。
正常 `make -C reference/gsim build-gsim` 构建通过后，继续在
`full-split-fallback-readers-v2-20261114` 重跑原始大图导出。

该 GSIM 重跑已完整导出五文件，从原始输入到导出完成 **322.358 s**。
Init 前后边界对应的 before Node 为 **7,829,556**，SplitArray 后为
**9,635,014**；实际拆分必须数组 **856**、可选数组 **233,875**。
`g->splitArray()`（含原生公共提交）**117.369 s**，它与 GRH
`split-static-array` 的历史 **24.523 s** 基线不是同一计时对象。
GRH 由 **7,671,189** 增至 **9,262,688**；两端数量不能代替匹配比例。
文件消费者独立重放与跨端比较正在同一目录运行，未完成前不声明其通过。

原始全图导出的 **after 名称候选比较**已完成：GRH **9,262,688** 个
SemanticTree 叶 Node 中，**9,218,505** 个能在 GSIM 找到唯一同名候选，
占 **99.523000%**；GRH 未找到唯一对应 **44,183** 个，GSIM 额外未匹配
**416,509** 个。输出为该目录 `node-names-v2/after.candidates.tsv` 和
`node-names-v2/after.unmatched.tsv`，summary 保留原生身份和输入 hash。

比较须先统一本轮 FIRRTL 路径表示：GRH flatten 后的
`["difftest.exit"]` 与 GSIM `["difftest","exit"]` 归一为 `difftest.exit`，
然后在每侧重新检查唯一性，碰撞仍列未匹配。当前 FIRRTL lexer 的原生
identifier 不含点，不能将此规则泛化为任意 SV 路径的无损转换。该候选率
不证明全部连接、演化或电路功能等价；完整文件重放尚在继续。

同一入口的 before 名称候选为 **7,668,660 / 7,671,189**，即
**99.967032%**；GRH 未对应 **2,529** 个、GSIM 未对应 **160,896** 个。
这里 before 是 GRH 的 **comb 后/split 前** 对 GSIM **Init**，不能将
其视为两条完整 pass 链共同起点。after 与 before 的 GRH 未匹配净增
**41,654** 个，仍需按实际 lineage 和命名/拆分策略逐项分析。
公共 Node 名称比较完整报告在 `node-names-v2/summary.json`；它独立于
全部连接的 SQLite 重放，既不读取 GRH checkpoint，也不生成 trace。

after 的 GRH **44,183** 个未匹配已逐条结合两侧本次 before/after 库存
和原生 split lineage 复核，结果如下。该表替代先前按数字后缀猜测的名称
模式分类；统计单位都是 **GRH after Node**，第二类按成员计数，第一类
按保留父 Node 计数，不能将这两列数量直接解释为数组家族数量。

| 原生证据分类 | GRH 未匹配 Node 数 |
| --- | ---: |
| GSIM 拆分并退休父 Node，GRH 保留父 Node、无 split lineage | 34,715 |
| GRH 拆分为成员，GSIM 保留父 Node、无 split lineage | 5,891 |
| before 父路径唯一对应、原生拆分坐标相同，但 after 名称不同 | 941 |
| GSIM 同一公共路径有两个活跃 Node，名称匹配无法唯一选择 | 104 |
| 两侧均拆分，GRH 仍保留父 Node，GSIM 退休父 Node | 3 |
| GRH `$ADDR0` 与 GSIM `.$address` 名称差异 | 976 |
| GRH `.$storage` 与 GSIM 无该层的名称差异 | 1,553 |
| **合计** | **44,183** |

两侧拆分粒度不同共 **40,606** 个，占未匹配 **91.9041%**。另有
**1,045** 个成员可通过 before 父路径与原生坐标找到唯一对侧成员，
但名字不同或公共名字碰撞；这没有回填原来的同名候选率。
全部条目均已归类，无 `unexplained`，但分类覆盖不代表功能等价。

地址与 storage 的 **2,529** 个差异在 split 前已存在。复核 before
未匹配 GRH ID 集合，与这两类 after ID 集合完全相同，因此本次 split
新增差异为其余 **41,654** 个。GRH 本侧没有路径碰撞或缺路径；不能把
GSIM 的 104 个重名直接解释为对应物消失。

逐条证据在
[`unmatched-analysis/unmatched-reasons.tsv`](../../ptmp/firrtl-ingest/F29/full-split-fallback-readers-v2-20261114/unmatched-analysis/unmatched-reasons.tsv)，
含两端 Node/父 ID、坐标、拆分成员数量、证据等级和说明；汇总在同目录
`summary.json`。分析直接读取本次已完成重放的 SQLite 和 Node 库存，
没有重新 ingest、执行 pass 或读取 GRH checkpoint。执行入口为
`make analyze_f29_unmatched F29_FULL_WORK=ptmp/firrtl-ingest/F29/full-split-fallback-readers-v2-20261114`，
本次分析耗时 **6.807 s**。

分类中存在 **422** 个 `endpoint.*.dpic` 名字，但其实际来源是 FIRRTL
extmodule（如原输入行 **8819471** 的 `DiffExtRefillEvent` 和 **8819483**
的 `inst dpic`），不能按名字将它们排除为 FIRRTL 之外的 SV。

文件消费者独立重放的 GRH 部分现已通过：comb **566.337 s**、split
**981.068 s**。消费者只从 before 与原生 evolution 重建 current，再与
独立 after 逐字段双向比较；连接端点和候选必须仍是活跃 Node，退休 ID
不得重用。因此此结果覆盖全部 Node 和公开连接，不限于数组，也不只比较
数量。数据库分别为 `grh-comb.sqlite` 和 `grh-split.sqlite`。

相邻阶段全量连续性校验通过（**29.110 s**），即 `comb.after` 与
`split.before` 的 Node ID/完整载荷及完整连接定义一致；连接 ID 仅在各
exchange 内有效，连续性比较不跨 session 混用。GSIM split 的独立文件
重放也通过（**977.099 s**），数据库为 `gsim-split.sqlite`。这些是每侧
演化链自洽证据；跨端 `evolution_alignment_verified` 仍为 false，不能
根据两个 event/action 数量相同推断两侧演化等价。

**修正路径表示后的全图比较完成**：`comparison.json` 与
`summary.json` 的 `comparison_report_complete=true` 已保存。它与独立
Node TSV 比较得到相同的 before/after 候选数。after 的已解析连接为
GRH **17,119,382**、GSIM **15,568,444**；限制为两端点均具有唯一公共
名称候选并对 `(source,target,kind)` 去重后，可比较连接分别为
**14,303,968**、**14,226,058**，交集 **13,322,215**。
这占 GRH 可比较连接约 **93.14%**、GSIM 可比较连接约 **93.65%**。
GRH 后态另有 **597,950** 条未解析依赖连接，GSIM 有 **1** 条未解析
external binding。未解析项保留在原生库存和重放中，不按候选源猜成确定边。

before 的可比较连接为 GRH **12,981,467**、GSIM **12,823,543**，
交集 **12,479,539**；仍须注意 before 比较阶段不同。GRH split 记录
**1,803,116** 条 split lineage，GSIM **2,051,495** 条；公共事务各为
一次 replace，GRH comb 另有 **253** 次 replace。上述 action/lineage
计数仅描述各侧轨迹，不用于证明跨侧演化等价。当前结果是性能门槛、
双侧原生导出、每侧完整重放与静态对比均完成，仍有拆分粒度和连接差异。

### 2026-11-14：未匹配的原因与证据边界

**GRH 保留、GSIM 拆分的原因。** 当前 GRH 的组合数组拆分先递归要求
具名上游数组可拆，再检查 `hasUnsplitArrayInput`；
`canSplitSemanticArray` 仅接受 Assign、ArrayCreate、Concat、Mux，
不接受 RegisterReadPort。state 阶段在实际拆分任何 family 前先决定全部
eligibility；whole write payload 含未拆上游时，family 被置为 unsupported。
整个 pass 只运行一次 state 阶段，后续第二轮只重试组合数组。因此 state
边界可能继续阻断下游整条数组依赖链，尚未通过联合 worklist 重新判断。
源码入口为 `wolvrix/lib/transform/split_static_array.cpp` 的
`GraphSplitter::splitSemanticArrays`、`canSplitSemanticArray`、
`StateSplitter::run`。

本次边界与 lineage 直接确认的样本包括：

- `...StoreUnit_1._s0_uop_T.srcType`：GRH **5767702** 保留且无 split
  lineage，GSIM **5801638** 退休并拆成 **4** 个成员。GRH 的 before
  连接可继续追到 `s0_vecstin`、`io.vecstin`、`VsSplitConnectStu_1.io.out`
  和 `data.uop.srcType`，这些父 Node 在本次 after 也均保留且无 lineage。
- `...LoadUnit_1.io.sbuffer.uop.srcState`：GRH **5443109** 保留，GSIM
  拆 **4** 个；GRH before 依赖指向 **5740295** `s1_in.uop.srcState`，
  再指向 **5740746** `s1_in_r.uop.srcState`，本次 after 三者都保留。

这些样本确认了未拆边界沿依赖链传播的现象。旧 F28 IR 可辅助定位 producer
种类，但不作为本次运行的直接 IR 证据；当前公共五文件未给每个保留 Node
记录首个拒绝规则，不能据此把全部 **34,715** 个归为同一个 skip 原因。

**GRH 拆分、GSIM 保留的原因。** GSIM 的 `checkNodeSplit` 依据原始
lvalue 的索引判断：动态写触发 `dynamic_write_index`，整数组赋值且存在
未拆上游触发 `unsplit_aggregate_input`；动态消费也会阻止可选拆分。
GRH 在 FIRRTL lowering 时已将非寄存器动态写转换成 packed shift、mask、
And/Or、Mux，后面的 SemanticNode eligibility 没有同样的原始动态 lvalue
证据。两侧前序表示与拆分政策因此不同，名称规则无法消除此差异。

- `...lsq.loadQueue.loadQueueRAW.willRevoke`：GRH **5830492** 拆 **32**
  个成员，GSIM **5874032** 保留且无 lineage。原始 SimTop.fir 第
  **7252196、7252202、7252208** 行存在 `willRevoke[lastAllocIndex[k]]`
  动态写，与 GSIM 动态写保留规则一致。
- `...decoderComp.fixedDecodedInst.vecWen`：GRH **2405856** 拆 **65**
  个成员，GSIM **2365536** 保留。原 FIRRTL 的上游 `csBundle.vecWen`
  在 **3398475、3404899** 行动态写，**3408010** 行整体连接；本次 GSIM
  before 确认 **2365447 → 2365536**，两者 after 均保留，支持未拆上游
  整体赋值的阻断解释。不能将这两个样本的规则推广为全部 **5,891** 个的
  已记录运行时首因。

**成员命名与碰撞。** **941** 个不同名成员全部具有唯一对应的 before
父路径和相同原生坐标：**184** 个 GSIM 名字在父名后额外出现 `_0`，
**653** 个 GRH 名字如此，另 **104** 个 GRH 名字在成员坐标后追加 `_0`。
原预期名字或父名均被另一个原生 split child 占用，支持碰撞处理/拆分顺序
不同的解释。GSIM `Node::arrayMemberNode` 碰撞时改已有对象名并追加 identity suffix，
新成员又继承父 suffix；GRH state 拆分也有自身的冲突改名路径。因此不能
把全部命名差异单独归咎一端。已退休父 Node 的中途同 ID rename 没有公开
after 对象，边界快照与 lineage 本身不能直接证明该中间事件。

**104** 个公共重名中，每条都有两个活跃 GSIM child，来自不同 before
parent；利用 GRH 成员的父路径和坐标能唯一选择一个。典型情形是二维
`_WIRE_` 的坐标 `[2,0]` 与原始 `_WIRE_2` 的坐标 `[0]` 都生成
`_WIRE_2_0`。GRH 将前者命名为 `_WIRE_2_0_0`，GSIM 公共路径仍发生
碰撞。GSIM 的 `nameExist` 只查 `allSignals`，新创建的 array member
没有加入该表，新成员之间的名字碰撞会漏检；GRH 的查询包含当前树和
计划新增成员。这解释了不同父 Node 的成员能在 GSIM 中同时占用同名，
并非本轮 FIRRTL 点号归一化引入。细查结果在
[`collision-analysis/name-differences.tsv`](../../ptmp/firrtl-ingest/F29/full-split-fallback-readers-v2-20261114/collision-analysis/name-differences.tsv)
及同目录 `exceptional-nodes.tsv`、`summary.json`。

**3 个残留父 Node。** `...ctrlBlock.rob.commitInfo.ftqIdx.flag`
（GRH **1811547**）、`ftqIdx.value`（**1811548**）、`ftqOffset`
（**1811549**）两侧均拆成 **8** 个成员，坐标全集相同；GSIM 退休父
Node，GRH 仍保留父 Node。`SemanticArrayNodes::finish` 在父 Node
仍有 op 找不到新 owner 时设 `residual=true`，只有无 residual 才删除
父 Node。这里应继续检查 op 归属迁移，不能直接删父 Node 而丢失覆盖。

**前序命名的 2,529 项。** GRH `Lowerer::pipeline` 使用 `$ADDR0`/
`$NEXT`，GSIM 的 MemoryReadAddress 公共身份使用 `.$address`；memory
storage 的显式层级和 depth=1 memory 转 register 的身份规则也不同。
**976** 个地址名差异与 **1,553** 个 storage 名差异均为 split 前已有，
由库存和生成规则支持，不视为已经证明电路功能对应。

后续修补优先级是：先统一组合/state 的拆分决策与依赖重试机制，并在
ingest 保留原始动态写证据；随后统一碰撞命名和父 Node 的 op 迁移收尾；
最后统一 memory 地址/storage 公共身份规则。公共 trace 还需为每个
拆分/保留决定导出具体 reason 和 blocker Node ID，使下轮可以按运行时
证据统计每项拒绝原因。目前已全量解释差异形态，尚未全量记录每个保留
Node 的运行时首因，也未证明跨端功能等价。

### 组合数组有序更新 op 设计（待实现）

该草案已转入 [F30：组合数组的多维有序更新](F30-array-update.md)，后续正式
合约、实施步骤与验收记录以 F30 为准；以下保留 F29 调查时的设计背景。

本节只确定设计，不表示已添加 operation 或修改生产 lowering。当前非寄存器
组合数组动态写在 FIRRTL lowering 中提前变成整数组宽度的 shift/mask/merge；
split 的局部投影不会普遍消除这些宽运算。GSIM 则保留数组左值索引，完整元素
写可直接生成 `a[i][j] = data`。本设计为 GRH 保留同样的寻址和写入顺序信息，
使后端可以初始化一个结果缓冲区后执行多次局部更新。

#### 操作数与唯一必需属性

新增纯组合操作 **`kArrayUpdate`**，一个结果，支持一到多次有序更新：

```text
result = kArrayUpdate(
    base,
    enable0, index00, ..., index0(k0-1), data0,
    enable1, index10, ..., index1(k1-1), data1,
    ...
) { indexCounts = [k0, k1, ...] }
```

| 项目 | 定义 |
| --- | --- |
| `base` | 更新前的数组 value，必须为 Logic 且 shape 非空 |
| `enableJ` | 第 J 次更新的一位无符号标量使能 |
| `indexJ*` | 第 J 次更新的下标，从最外层到最内层，均为无符号标量 Logic |
| `dataJ` | 此次覆盖区域的完整值；可以是叶元素或后缀子数组 |
| `indexCounts` | 必需的 `int64[]` 属性，每项表示对应更新的下标数 |
| `result` | 执行全部更新后的数组，完整类型与 base 相同 |

更新数 `M = indexCounts.size()`，要求 `M >= 1`。每组有 `kJ+2` 个 operand，
总数必须严格等于 `1 + Σ(kJ+2)`。第 J 组开始位置为
`1 + Σ(L<J)(kL+2)`：该位置是 enable，随后 kJ 个 index，最后一个是 data。
实现提供统一只读 accessor 解码所有组，线性遍历只计算一次前缀偏移，避免
消费方各自解析或反复扫描前缀。verifier 对组长度累加、shape 乘积和宽度
计算执行溢出检查，再用于操作数索引或地址计算。

属性只记录操作数分组；不重复保存 `updateCount`、`offsets`、`shape`、
`strides`、`writerOrder` 或数据 Value ID。更新数来自列表长度，优先级来自
列表顺序，维度和元素宽度来自 base 类型。静态下标使用普通 constant operand，
动态下标也使用 operand，不把运行时依赖藏进属性。无需嵌套 JSON 属性。

#### 多维、子数组与完整类型

对 rank 为 R 的 base，每组允许 **`0 <= kJ <= R`**：

- `kJ == R`：更新一个叶元素。
- `0 < kJ < R`：消费 shape 的前 kJ 个维度，更新剩余维度构成的整个子数组。
- `kJ == 0`：更新整个数组；enable 为真时整体覆盖，作为有序序列中的一次操作。

不同组可以使用不同 kJ；不是要求每次更新相同维数。只支持从外向内的前缀
寻址，和现有 `kSliceArray` 及寄存器数组端口一致；不把任意步长、列切片或
位掩码偷偷编码为 indexCounts。Bundle 字段已经属于各自的数组叶 value。

若 base 的 shape 为 `[D0,...,D(R-1)]`、叶宽为 E，第 J 次更新要求：

```text
dataJ.shape = base.shape[kJ:]
dataJ.width = E * product(base.shape[kJ:])
```

data 的 kind、叶宽、signedness、logic domain 必须与 base 对应的子数组
完整类型一致，等总宽但不同 shape 不得静默接收。索引不限制为 32 位，先按
其完整无符号值判断合法性，再计算宿主地址，避免截断使越界变成合法地址。
TwoState 数组只接受 TwoState 控制；FourState 数组允许两态或四态控制。
使能不允许数组形状或多位 truthiness；生产者须显式转换为一位。

例如 base 为 `UInt<8>` 叶、shape `[2,3,4]`：

```text
%r = kArrayUpdate(
    %base,
    %en0, %i, %j, %k, %byte,
    %en1, %row, %plane,
    %en2, %i2, %j2, %vector
) { indexCounts = [3, 1, 2] }
```

其中 byte 为 8 位标量，plane 为 width=96、shape `[3,4]`，vector 为
width=32、shape `[4]`。对应的确定地址执行次序是：

```text
r = base
if en0: r[i][j][k] = byte
if en1: r[row] = plane
if en2: r[i2][j2] = vector
```

各组独立检查 bounds；某次越界只跳过该次，后面的组继续执行。如果后面的
plane/vector 覆盖前面写入的 byte，以后面的值为准。`indexCounts=[0,3]`
则可表达先受控地覆盖整个数组，再覆盖某个元素。

#### 值语义、顺序与四态

操作是 **Pure**，不是无时钟的 state writer：不带 `regSymbol`、事件、隐式
状态或隐藏中间结果，不修改 base。定义 `A0=base`，第 J 组产生 `A(J+1)`，
唯一公开结果为 `AM`。列表顺序决定覆盖次序；不能按下标、使能或名称重排。
每个 enable、index、data operand 都是 op 外部的不可变输入快照，不随
内部数组累积器变化。若后次 RHS/索引依赖前次更新后的值，就保留两个 op，
不能把依赖删除后直接合成一组独立输入。

四态规范以逐叶元素选择为定义，避免宿主 `if(X)` 或未知索引被直接忽略。
对完整目标坐标 `t=[t0,...,t(R-1)]`，第 J 组：

```text
matchJ(t) = enableJ & AND(L<kJ)(indexJL == tL)
A(J+1)[t] = mux4(matchJ(t), dataJ[t[kJ:]], AJ[t])
```

这里 `==`、`&` 和 `mux4` 使用 GRH 既有四态比较、按位与、Mux 语义；空
索引集合的 AND 为真，标量 data 没有后缀下标。该公式是语义定义，不要求
后端生成逐元素相等比较。坐标比较先将 index 与 tL 零扩展到至少能完整表示
两者的共同宽度，不能把目标坐标截到 index 位宽而误匹配多个元素；bounds
比较还需能表示维长度本身。已知地址与使能走直接下标写的快路径；已知越界或
使能为 0 不更新；未知使能/地址影响的位通过既有 Mux 规则融合。确定写入的
data 中的 X/Z 原样传递，不因按位 Or 而把 Z 变成 X。

这是新 op 的固定语义，不增加 `unknownIndexPolicy` 等模式属性。现有 packed
shift/mask lowering 在未知索引或 Z 数据上的结果可能更悲观，迁移必须专门
比较并记录这些差别，不能声称旧宽位运算与新的索引更新在所有四态输入上
天然等价。当前 CPU 仿真器只接受显式 TwoState，快速代码生成仍需先遵循
既有 grh-to-grhsim 逻辑域转换，不能在此 op 内自行把未知值当作零。

#### 仿真代码生成与缓冲区

TwoState 的目标代码为在调用方提供的结果存储中初始化一次，依次局部写：

```cpp
copy_array(result, base);  // 最多一次完整 base 初始化；无需时由证明消除
if (en0 && i < 2 && j < 3 && k < 4) result[i][j][k] = byte;
if (en1 && row < 2) copy_subarray(result[row], plane);
if (en2 && i2 < 2 && j2 < 3) copy_subarray(result[i2][j2], vector);
```

不为每次更新分配或返回一个完整 `std::array`，不反复 pack/unpack，也不为
完整元素写生成整数组 shift/mask。子数组复制沿用现有指针/调用方输出缓冲区
策略。所有 RHS 的语义快照必须保持：仅当 base 独占且已到最后一次使用，
并证明后续 operand 不会读到被覆盖存储时，才允许复用 base 缓冲区；存在
alias 时先保存必要的 data/indices/enable 或使用独立结果存储。

成本是“至多一次必要的 base 初始化 + 各次实际覆盖区域的更新”。整数组复制
仍可能为 O(数组大小)，子数组写仍可能为 O(子数组大小)，不能宣称整个 op
普遍 O(更新次数)。安全地消除 base 初始化还需证明必定覆盖所有输出且 base
无实际依赖，不能因为 base 是 invalid 就跳过初始化。

#### 前序流程与验收边界

FIRRTL driver 先积累有序的连接意图，在依赖/别名安全的范围内生成多次更新
op；最终读取仍按 FIRRTL 最终连接语义解释。现有静态 splice 路线可以保留，
不为凑成一个 op 而把已解决的静态范围依赖重新聚合成整数组依赖。跨具名
SemanticNode 的 base 边界保持；普通多次更新仍是同一 Node 的内部实现。
寄存器和 memory 的真实写端口继续走其状态/事件语义。

`comb-loop-elim` 需要按输出区域反推各次覆盖、base 和 data 的依赖，已知
必然覆盖的范围可以去掉旧值依赖；动态索引则保守覆盖可能目标范围。不能只
把新 op 当黑盒连接全部输入，否则会重新制造数组元素之间的假环。
`split-static-array` 识别原始动态下标后默认保留数组，trace 记录保留原因及
blocker；静态组可以按实际覆盖关系投影拆分，按同样的顺序执行。必须破环的
拆分与可选拆分分开记录原因，不能为提高名称匹配率强制生成逐槽 Mux。

实现需同时覆盖 core kind/描述符与 verifier、store/load、FIRRTL driver、
两个 pass、逻辑域转换及 CPU/SV emit；不支持新 op 的路径须在修改图前报错。
新增公共 op 时还需明确 GRH dialect 版本与读写兼容策略，不能让旧 loader
误读未认识的语义。

正确性验收应覆盖：混合 rank、静态/动态混合坐标、重复与重叠写、越界后继续、
未知控制/data、子数组与 base 别名、后次读取前次结果的不可融合边界，以及
原有静态局部假环。性能验收用原始 SimTop 全图，先统计生成代码中实际保留
的宽 shift/mask、整数组复制和索引更新，再测最终仿真周期耗时；ingest/pass
耗时不能代替运行性能结论。此设计尚未实施，也没有新的性能实测结果。
