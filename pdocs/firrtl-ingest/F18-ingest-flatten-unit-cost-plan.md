# F18：F17 未达预期的原因与下一步方案

日期：2026-11-04。状态：方案，未实施。

范围与 F17 相同：原始 `SimTop.fir` 到 hier-flatten 返回，node annotations 开启。
本文所有数字都标明来源。“预算”是设计目标，不是已测收益。

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

### 3.2 ingest 时间线（`fp/run1`，按调用栈分类，采样 322.7 CPU s）

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
3. 合入默认关闭的阶段计时。`fp/source` 已有未构建、未运行的 `StageTimer`，可作起点。
4. 验收指标改为**各阶段墙钟 + 总 CPU + 单线程占比**，不再使用固定函数族比例。

### F18.1 node provenance 结构化（最大项，实测上界 69.5 s）

现状：`firrtl.node.*` 是 `vector<string>` 形式的 canonical key，每次改写都要解析、限定、校验、
写回。flatten 中 `copyQualified` 18.3 s，`recordRetention` 5.8 s，inventory 5.1 s。

1. **census 只算一次（先做，改动小）：** 在终点和实际需要时计算，不再每 pass 每图计算。
   metadata 终值不变；需核对中间阶段的错误是否仍在原位置报告。
2. **key 改为结构化 ID：** `(ScopeId, 定义内 node 序号, field path id)`。实例路径进路径表，
   flatten 只加块级 ScopeId，不重写每个 op 的 key。`originModules` 同样由 ScopeId 推出。
3. **合并和校验走整数：** union/normalize 处理 ID 集合。入口完整校验一次，之后依赖类型保证。
4. **文本只在边界生成：** JSON、诊断和 inspect 按原格式生成，字典序、64 项上限和 degraded 计数
   按原语义处理，以完整 JSON SHA 为门禁。

预算：flatten 与前置 pass 合计减少 ≥ 45 s。无法达到 node 关闭水平，导出和分图仍需这些信息。

### F18.2 symbol 只标记有语义的信号（最先实施，已确认）

symbol 的本意是标记有语义的信号，不是给所有对象批量命名。当前每个临时 value/op 都拼接
`_val_N`/`_op_N`、hash、写字符串池并绑定符号；lowering 和 flatten 各付一次，`retain` 还要重新
intern 源图的全部内部名。flatten 中名字约占 24.4 s。

已确认：JSON 导出不要求名字和字节稳定。因此不再复现 `_val_N` 文本或跳号规则，也不需要任何
tagged SymbolId。

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
5. **显示名按需生成。** 新增 `Graph::valueDisplayName(id)`/`opDisplayName(id)`：有 symbol 返回其文本，
   否则由当前 ID 生成，并避开已有语义名字。显示名不是身份，compact 后可能变化。
   `symbolText(invalid)` 静默返回空串，这是主要风险，迁移时须逐处审计。
6. **JSON：** store 经显示名写引用，无 symbol 的对象写 `"tmp":true`。load 用局部表解析临时引用，
   不进 SymbolTable。端口绑定的 value 按语义名字载入，因为端口校验按 symbol 建表。
   旧 JSON 仍可读，其全部名字按语义名字载入。
7. **排序：** `store.cpp` 中 use-list 改为按 op ID 和 operand 下标排序。其它按名字排序的代码须逐处审计。
8. **下游边界。** GrhSIM IR 仍以 symbol 文本为身份，`grh-to-grhsim` 入口调用
   `Graph::materializeInternalSymbols()` 给顶层图的无 symbol 对象补名字，下游暂不改。
   这只是把这部分成本推迟到 flatten 之后，**不是消除**；整机 FIRRTL→C++ 须单独计入，
   后续应让 GrhSIM 也不再依赖临时名。SV emit 路径接收 const Design，不能使用该调用，
   需改用显示名或另设入口。

探针结果（2026-11-04，一次）：把默认 `createValue`/`createOperation` 全部改为无 symbol 后，
`make test_wolvrix` 为 62/81 通过，证实临时名本身不是核心图语义的必需品；19 项失败多为
GrhSIM pass 和测试夹具以 symbol 文本作身份（`regSymbol` 解析、时钟分组 key 等），以及
`transform-hier-flatten`、`store-text`、`firrtl-node-attributes`、`firrtl-cse-scope`、`ingest-mixed`
等项。失败原因未逐项确认。这是修改默认接口的结果，不代表第 1–2 条方案的结果，方案本身尚未跑过测试，
也没有性能数据。详见 `ptmp/firrtl-ingest/F18/logs/test1.log`。

验收（替代本项的字节 SHA 门禁）：

- 新增结构等价比较：对新旧 JSON 把临时名按首次出现顺序归一化后比较，语义名字、端口、属性、
  来源和拓扑必须一致；有效的顺序差异逐项解释并记录。
- 6,007 条诊断按序比较，临时名先归一化。
- 同一输入重复运行输出逐字节相同（确定性）。
- use-list 排序已改变，结构比较须把 `users` 当作集合；`"tmp"` 字段不参与比较。
- JSON store→load→store 保持临时对象无 symbol，且结果确定。
- 81 项 CTest、workflow、GrhSIM flow 及生成模型执行通过。

预算：flatten ≥ 15 s，并降低 lowering 和 `retain` 成本，同时让 F18.3 可以取消逐行符号绑定。
该预算只覆盖到 flatten 结束，不含第 8 条推迟到下游的成本。

### F18.3 flatten 真批量化（依赖 F18.1、F18.2）

合并到一张图不可避免要改写符号和 operand ID，但目标是整块改写，不是逐对象调用。

当前实现状态：

| 内容 | 现状 |
| --- | --- |
| value width/isSigned/type/domain、op kind | 已批量：共享页 |
| 单次使用来源的 operands/results | 已批量：接管缓冲区后原位改写 |
| 符号校验与绑定 | 逐行：`symbolIndex_.contains`、hash set 插入、`bindSymbol` |
| SrcLoc | 逐行 `importSrcLoc` |
| 属性 | 块内有分片，node 和 `originModules` 仍逐 op 处理 |
| 字符串池 | `retain` 逐条重新 intern |

改法：

1. **块级校验：** 输入来自已校验的 compact 图时，只校验块边界，不逐行检查。
2. **SrcLoc 整体映射：** 按记录表一次导入并建立映射数组，行上只查表；不逐行 import。
3. **符号不逐行绑定：** F18.2 后临时对象没有 symbol；只有语义对象走小表。
4. **ID 一次改写：** value/op 列、边和属性引用按块基址和映射数组改写一遍。
5. **字符串池：** 改为分段池，或只导入块中实际被属性引用的字符串，不逐条 `retain`。
   分段后同一文本可能有多个 ID，需先审计依赖 StringId 相等的代码
   （例如 `retentionCensus` 按指针聚合）。

**并行不作为本项目标。** 上述完成后再测单线程耗时。只有剩余逐块写入仍占主要部分时才启用线程池，
写入范围互不重叠，并须证明并行与串行结果逐字节一致。现有线程池接入不撤除，但不计入预算。

预算：块函数 18.7 s → ≤ 8 s（单线程）；flatten 总计 ≤ 25 s。

### F18.4 `Rob` 模块内并行（先做可行性评估）

模块级并行下，lowering 墙钟不可能低于 `Rob`。F18.1/2 可降低其单核成本，但关闭 node 后
仍有约 23 s，这与 flatten 不同：这里只有拆分任务才能突破下限。

先评估按语句分块 lowering：各块生成局部列，再用与 F18.3 相同的整块改写合并。难点是 connect
last-wins 的 driver 状态和跨块 value 引用，需证明结果与串行逐字节一致。若不可行，
记录实际下限，并接受 ingest 的墙钟受 `Rob` 限制。

### F18.5 ingest 串行尾部与单位成本

1. **发布段（约 8 s）：** `applyAnnotations` 约 4.3 s 在协调线程，移入 worker 或改为索引查找。
2. **verify（约 15 s 墙钟）：** 查明 3–4 核的原因；只检查未证明的图。
3. **parse/summary 并行衰减：** 0–11 s 从 5 核降到 2 核，用 F18.0 的计时查明是否为大模块长尾。
4. **语义层字符串表：** `Semantics` 的声明和 port 用 `std::map<string, …>`，memcmp 是 ingest
   最大叶函数之一。可在 parse 时 intern 标识符，AST 和 Semantics 用整数 NameId。

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

顺序：**F18.2 → F18.0 → F18.1 第 1 步 → F18.1 → F18.3**；F18.5 可并行推进；F18.4 先评估。
flatten 并行放在 F18.3 单线程结果之后，按实测决定。
每项单独 A/B，避免无法归因。

门禁沿用 F17：同一冻结输入、CPU 0–31、10 worker、annotations 开启；ingest/flatten 用 F18.2 的
结构等价比较代替与 F16 的 JSON SHA 比较；6,007 条诊断按序相同（临时名归一化后）；81 项 CTest 和全部 workflow
通过；构建和测试走 Makefile。性能结论必须来自无采样 formal 运行，并至少重复三次。
日志放在 `ptmp/firrtl-ingest/F18/`。

## 6. 待决定

1. 已确认：F18.2 最先实施，JSON 导出不要求名字和字节稳定。
2. F18.1 第 2 步是否允许内存中不再保存文本 key，只在边界生成。
3. 目标口径继续用 GSIM parse+Init 76.5 s，还是同时用 164.8 s 口径。

## 7. 未测量

- 未取得精确阶段计时：`fp/source` 的 `StageTimer`、census 和 compact 累计计时已写好，但未构建运行。
  §3.2 的跨度来自采样。
- Codex 分析任务在写出报告前被取消，本文由其运行数据和 perf.data 重新分析得出。
- 未测 analyze/lower 内部的详细分布，也未测 F18.4 的可行性。
- F18.2 的方案没有测试或性能结果；§4 只记录了一次修改默认接口的探针结果。
- `fp` 构建与 r2 有差异（`-fno-omit-frame-pointer`，后两次运行还带模块计时），不用于绝对性能结论。
