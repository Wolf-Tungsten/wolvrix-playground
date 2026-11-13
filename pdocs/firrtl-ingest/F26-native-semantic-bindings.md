# F26：GrhSIM 全流程对齐与 SemanticTree 原生绑定

历史记录：本文描述 F28 重构前的来源树与绑定模型，百分比和流程支持范围仅适用
当时版本。当前 Path／单一叶 Node、JSON v5 与 pass 支持边界以
[F28](F28-semantic-tree-refactor-plan.md) 为准。旧 schema 专用的离线分析脚本及
Make 入口已清理，大型临时产物亦已删除；下文命令、文件和测试结果保留历史含义。

2026-11-12。本轮将来源身份及具体端点绑定写入生产 IR。F26 仅维护本文，
以前的离线审计和证明产物保留在 `ptmp/` 作为历史证据。
生产流程不调用那些脚本，也不依赖 Init dump、split map 或名称后缀恢复来源。

当前生产流程自动维护两侧来源元数据；跨 GRH／GSIM 的配对、核验和比例统计仍由
`measure_semantic_alignment.py` 读取普通
checkpoint 完成。SemanticTree 尚未直接输出到 GSIM node ID 的最终映射表，
因此“跨工具对齐完全内建、无需外部脚本”的目标尚未完成。
本轮全量节点完整对应率为 **99.940245%**，排除显式空源后为 **99.971600%**；
FIRRTL 范围的 op 至少有一个完整对应 owner 的比例为 **99.945505%**。
这些是来源对应与归属覆盖，不是表达式或功能等价结论。

## 完整 GrhSIM 流程与当前对齐位置

截至 2026-11-12，需要分别记录三种进度：

- **生产流程实现**：FIRRTL canonical 主线已接通全部 22 个生成阶段，并支持后续编译、
  链接和整机仿真。F24 冻结版本已有指定窗口的动态正确性证据。
- **GSIM 优化阶段覆盖**：ordinary GRH 的阶段顺序已接到 `comm-expr` 后的最后一次
  DCE，再进入 GrhSIM 转换／分图／调度／C++ 生成；部分优化只实现 GSIM 的安全子集。
- **本次 F26 全量对齐测量**：GRH 停在第 **4** 阶段 `comb-loop-elim` 后；GSIM 停在
  splitArray 后的 TopoSort／InferAllWidth、首次 DCE 之前。本文的 99.940245% 节点对应率
  和 99.945505% op 归属覆盖率只属于这一对检查点，第 5–22 阶段尚无本轮逐阶段全量比例。

### FIRRTL canonical 主线：22 个生成阶段

以下顺序来自当前
[`firrtl_canonical_pipeline()`](../../scripts/wolvrix_xs_grhsim.py)、
[`finish_simulation_graph()`](../../scripts/grhsim_flow.py) 和根
[Makefile](../../Makefile) 的 `xs_firrtl_pipeline_manifest`。
这是 F26 使用的 FIRRTL／mixed-source 路线；SV 的 full／bringup 流程另有前序 pass，
不能用其列表代替此表。GSIM 一列表示职责与优化边界的对应，不表示两侧输出图完全相同。

| 序号 | GrhSIM 生成阶段 | GSIM 对照或阶段职责 | F26 本轮测量位置／产物 |
| ---: | --- | --- | --- |
| 1 | `ingest-firrtl` | `parseFIR → AST2Graph(Init)`：建立类型、状态、运算与来源 | 当前测量前序 |
| 2 | `xmr-resolve` | 解析跨层引用；GSIM 构图内处理相应来源关系，无独立同名 pass | 当前测量前序 |
| 3 | `hier-flatten` | 展开实例；GSIM AST2Graph 已形成展开图 | 当前测量前序 |
| **4** | **`comb-loop-elim`** | 消除 GRH 假组合环；结构参考 GSIM `detectLoop → TopoSort`，类型取 `InferAllWidth` | **本轮 GRH `post-elim.json`，全量来源／owner 核验到此** |
| 5 | `split-static-array` | `splitArray`：静态数组及状态成员化 | 本轮未执行；GSIM 在本轮对照前已执行对应拆分 |
| 6 | `dead-code-elim` | 首次 `RemoveDeadNodes` | 本轮未执行 |
| 7 | `expr-opt` | `ExprOpt` | 本轮未执行 |
| 8 | `used-bits` | `UsedBits` | 本轮未执行 |
| 9 | `split-nodes` | `SplitNodes` | 本轮未执行 |
| 10 | `dead-code-elim` | `RemoveDeadNodes1`：SplitNodes 后清理 | 本轮未执行 |
| 11 | `constant-analysis` | `ConstantAnalysis` | 本轮未执行 |
| 12 | `dead-code-elim` | ConstantAnalysis 后的 `RemoveDeadNodes` | 本轮未执行 |
| 13 | `alias-analysis` | `AliasAnalysis` | 本轮未执行 |
| 14 | `pattern-detect` | `PatternDetect` | 本轮未执行 |
| 15 | `comm-expr` | `CommonExpr`；兼容名 `common-expr` | 本轮未执行 |
| 16 | `dead-code-elim` | CommonExpr 后的最后一次 `RemoveDeadNodes` | 本轮未执行；canonical ordinary GRH 优化前缀结束，可保存 post-opt flat checkpoint |
| 17 | `grhsim-dialect-translate` | 状态写入、事件和 effect 的仿真语义转换；GSIM 无一对一独立阶段 | 本轮未执行；`logic_domain=2state`，产出 `converted` checkpoint |
| 18 | `split-event-and-output` | 提取 Event／Output 计算、采样与效果顺序 | 本轮未执行；产出 `event-output-split` checkpoint |
| 19 | `split-nonsink-and-sink` | 分离 General 计算与状态／效果 sink，区分 small／large sink | 本轮未执行；产出 `nonsink-sink-split` checkpoint |
| 20 | `partition-nonsink` | 建立可激活 node／supernode；与 GSIM `graphPartition/Replication` 有职责交叉，无一对一结构关系 | 本轮未执行；产出 `nonsink-partitioned` checkpoint |
| 21 | `partition-sink` | 按 clock／fire、写优先级及 enable 生成执行分组和 SinkSchedule | 本轮未执行；产出 `sink-partitioned` checkpoint，并在当前 session 建立 schedule |
| 22 | `emit-grhsim-cpp` | 生成单线程模型 C++ 与模型 Makefile；GSIM 后端最终生成 C++ | 本轮未执行；产出供后续编译的模型 publication |

22 个阶段包括 ingest 与 emit，共 20 次 transform pass，四次显式 DCE 分别计数。
此 FIRRTL canonical 主线没有额外的 `simplify` 阶段。第 17 阶段也叫旧名
`grh-to-grhsim`，第 18–21 阶段兼容对应的 `grhsim-*` pass 名。
这些转换仍在 GRH 上完成，没有独立的 CPU planning IR。

生产流程中第 16 阶段后保存的 post-opt flat checkpoint，与本轮第 4 阶段的
[`post-elim.json`](../../ptmp/semantic-bindings/F26/grh/post-elim.json) 是不同落点。
第 17 阶段的 post-conversion／pre-partition 两种 dump 之间没有 transform。
可选 store/load roundtrip 属于 verification，resume 时重建 SinkSchedule；它们不增加
上述 22 个生成阶段。

### GSIM 对照主线与本轮截断位置

GSIM 当前顺序见 [`main.cpp`](../../reference/gsim/src/main.cpp)：

```text
parseFIR → AST2Graph(Init)
→ splitArray → detectLoop → TopoSort → InferAllWidth  ← F26 当前 GSIM 测量终点（首次 DCE 前）
→ RemoveDeadNodes → ExprOpt → UsedBits → SplitNodes → RemoveDeadNodes1
→ ConstantAnalysis → RemoveDeadNodes
→ AliasAnalysis → PatternDetect → CommonExpr → RemoveDeadNodes
→ graphPartition → Replication → GenerateStmtTree → InstsGenerator → cppEmitter(Final)
```

当前 GRH 保留完整数组来源，GSIM 已经拆数组，因此本轮允许一个 SemanticTree SID
对应多个 GSIM 物理成员。这是两侧所选检查点的表示差异，不能理解为 GRH 已执行
第 5 阶段，也不能用来源覆盖率推导两侧存活图或后端分区完全一致。

### 已有后续证据与尚未完成的对齐

| 流程范围 | 已有证据 | 当前能确认的范围与缺口 |
| --- | --- | --- |
| 第 1–4 阶段 | 本文当前 native-binding 全量扫描 | 已有来源／owner 比例及未完整对应 TSV；完整函数与状态等价仍未证明 |
| 第 5 阶段 | [F21 拆分检查](F21-dead-code-elim-plan.md#151-dce-前的状态成员已全量对齐)：历史可映射的 4,832 个状态族、58,255 个元素集合一致 | 只覆盖该历史样本的状态成员，不能外推到全部 value，也未使用本轮新 checkpoint 重新测量 |
| 第 6 阶段及后续 DCE | [F21](F21-dead-code-elim-plan.md) 的存活集合、状态及 DAG 对比 | 仍有双向保留差异；后续含标量的共同 278,596 个寄存器单元中，GRH 独有保留 284、GSIM 独有保留 67，未匹配单元另列；不是全量结构 100% 对齐 |
| 第 7–8 阶段 | [F22](F22-expr-opt-used-bits.md) 独立 pass 回归及 XiangShan 全图规模／耗时检查 | `expr-opt/used-bits` 已接入；这些证据不提供两侧全图结构一致率 |
| 第 9–16 阶段 | [F23 ConstantAnalysis](F23-constant-analysis.md)、[Alias／Pattern／CommonExpr](F23-alias-pattern-common.md) 及 [pass 范围](../grhsim.md#3-pass-划分与流水线) | 已实现对应优化阶段及安全子集；SplitNodes 主要覆盖无符号 scalar 纯表达式，Alias 限类型一致 scalar view，Pattern 主要覆盖 concat 比较，CommonExpr 限纯 scalar 表达式；未取得本轮逐阶段全量对齐比例 |
| 第 17–22 阶段 | [F24 正确性 checkpoint](F24-correctness-checkpoint.md) 的完整生成与专项回归 | 转换、分图、调度和 emit 路线接通；没有 GSIM 后端逐 pass 一对一结构验收，本轮未重测这些阶段的来源绑定覆盖 |
| 生成后编译及仿真 | F24 冻结 v14 的 fresh 完整编译、100k 窗口 NEMU 无差异、与 Verilator 231,568 条 commit 精确匹配 | 指定输入、策略、窗口和代码身份的动态证据；不是全输入等价，也不是本轮新增 native-binding 源码的全链重新验收 |

F24 的历史动态通过与本文末节保留的局部时钟／复位差异可以同时成立：测试窗口通过
不证明未覆盖输入及事件上的行为相等。性能对齐属于 [F25](F25-simulation-performance.md)，
不能从本轮来源对应率推导性能已对齐。

### 生成以后的编译、链接与运行

```text
原始 SimTop.fir + 外部 SV／资源／选项清单
→ canonical 22 阶段 → 模型 C++／Makefile
→ 编译模型与 difftest harness → archive／链接 → emu/emu
→ reset／时钟驱动 → CoreMark 仿真／NEMU difftest → 提交记录／结果比较
```

入口均由根 Makefile 提供：

| Make target | 执行范围 |
| --- | --- |
| `xs_firrtl_grhsim`／`xs-firrtl-grhsim` | 从原始 FIRRTL／mixed-source 清单执行 22 个生成阶段 |
| `xs_firrtl_grhsim_build_emu` | 使用生成模型，编译模型和 harness 并链接 `emu/emu`；journal 名为 `compile-grhsim-cpp`，不计入 22 阶段 |
| `xs_firrtl_grhsim_emu` | 先生成模型，再调用 build target |
| `run_xs_firrtl_grhsim_emu` | 运行已构建的 CoreMark／difftest 仿真；运行配置和观察窗口另行记录 |

因此当前明确的终点是：**完整实现已到仿真执行；F26 本轮新原生来源／归属对齐的
全量测量只到第 4 阶段。第 5 阶段以后的实现、历史局部核验和动态通过，各自按上表
保留范围，尚不能合称整个流程已经完全对齐。**

## 生产接口

`Graph::semanticBindings()` 与原有 value/op `semanticIds` 分开：后者表示归属，
前者表示具体来源端点。绑定引用 SemanticTree ID、实际 ValueId 和可选的操作上下文。
角色包括 value、predicate、register-current、register-next、clock、reset、
memory-read-address、memory-storage 和 effect。JSON 的 `semanticBindings` 随普通
checkpoint 自动保存／加载；不需要专用导出流程。

FIRRTL lowering 在声明、WHEN、状态写入、内存和 effect 的产生位置建立绑定：

- WHEN 按实际源行建立 Predicate 节点，绑定真实 Boolean 根。多处相同条件可以共享值，
  各处源身份仍独立保留；空块和常量条件也有端点。
- 原始数组保留完整 shape、元素宽度／符号和 shapeFieldDepths。例如
  `a : {b : UInt<8>[2]}[3]` 的 shape 为 `[3,2]`，field depths 为 `[0,1]`。
  零宽／零元素源保留显式空绑定，不创建假值。
- register-current 指向完整读值；register-next 指向一次实际写入的数据及 writer 操作。
  enable、索引、clock 和 reset 仍由实际 writer 表达，不能把一条写入当作完整 next-state。
- projection 为空表示完整源，否则每个源轴一项。`-1` 包括未选择和动态选择的轴；
  动态写入必须结合操作索引解释，不能据此断言覆盖所有成员。
- memory-storage／effect 直接绑定实际 storage／task 操作，没有伪造结果值。
  空 memory-storage 可以没有执行对象。

GRH 核心维护 clone、RAUW、compact、删除、tree pruning 和序列化时的绑定有效性。
flatten 的两条路径同时迁移 SID、值和 writer；全局路径在端口代表确定后发布绑定，
随后才允许消费子图。comb-loop 拆分只在完整重组值上迁移来源绑定，片段保留原有 owner，
不冒充完整来源端点；生成值同时保留原逻辑域。

GSIM 在 AST 构图时保存 token 组成的源 path、scopeDepth、源 shape／field depths、
角色和原始轴。singleton removal、dup、重命名和 splitArray 在节点自身传播投影。
深度 1 内存替换保留 memory-storage 来源，当前／下一状态的物理角色独立表达。
effect 源行来自 lexer 的关键词位置，避免 reduction 的下一行位置。

两侧数组可以是一对多，Module／聚合仍是结构容器。实现辅助 op 继续归属于真实源节点，
不为每个辅助 op 伪造 GSIM 值端点。接口说明见
[FIRRTL combinational](../../wolvrix/docs/ingest/firrtl-combinational.md)、
[GRH JSON](../../wolvrix/docs/grh/grh-json-spec.md) 和
[GSIM source inventory](../../reference/gsim/docs/json-source-inventory.md)。

## 验证

- `make test_semantic_bindings`：8/8，通过核心绑定、角色校验、JSON、三个 XMR suite、
  两种 flatten、comb-loop 完整重组及 TwoState／FourState 回归。
- `make test_semantic_binding_alignment`：同一份 FIRRTL 的正常生产前序流程，直接读取
  当前 GRH 绑定和 GSIM 节点元数据；TopoSort、InferAllWidth 各 18 个节点，缺失均为 0。
  包括数组拆分、singleton、bundle/vector 交错、改名冲突、current/next、WHEN 和 effect。
- GSIM 的 semantic-lineage、source-aggregate、memory、expression 四项 Make 回归通过。
- `make test_firrtl_comb test_firrtl_state test_firrtl_memory test_ingest_mixed` 通过，
  包含生成和执行的仿真模型。

完整 F26 已使用当前实现重跑 GRH 的 ingest → xmr-resolve → hier-flatten → comb-loop-elim，
以及 GSIM 的 splitArray → TopoSort → InferAllWidth。新产物位于
[`ptmp/semantic-bindings/F26/`](../../ptmp/semantic-bindings/F26/)，历史产物未覆盖。
GRH checkpoint 共 8,780,799 个 SemanticTree 节点；452 个 false loop 全部修复，
0 个 unresolved false loop。实际输入 SHA-256 仍为
`b313a3ecd154cbd9279b14403709806b95fb136cf44b475e9def46a926ecb26b`。

普通 checkpoint 已原生包含 9,451,150 条 GRH 绑定。两侧各有 156,703 个 predicate、
976 个 memory-read-address 端点和 7,836 个 effect；这是原生导出计数，
不是离线补造的配对，也不以计数相同代替逐项等价。GRH 的 4,877 个 memory-storage
包含 GSIM 中保留为 memory 的 3,324 个及已转换为寄存器的来源；GSIM 对后者另保留
`originRole`。GSIM 普通节点仍为 9,631,690 个，另有 3,324 个 memory。
计数位于两侧的 `binding-counts.tsv`。

GRH 新 checkpoint SHA-256 为
`f541d4444e272675f05a88109c29f7eb8ee5f1363db4f879c8b401a1cd843a8b`，
峰值 RSS 73,479,904 KiB。本次本地 user systemd 不可用，因此完整重跑走普通 Make
路径；不宣称施加了 systemd 内存上限。失败的 cap 启动记录单独保留为
`grh/resource-cap-unavailable.json`，完成状态以 `grh/summary.json` 为准。

此处完整 F26 重跑验证了生产端的生成、传播和导出，没有将小 fixture 的 0 缺失外推为
F26 全量行为等价。已知 FIRRTL 派生时钟／async reset 模型差异见本文末节；
来源绑定不会消除或掩盖该差异。

## 完整 F26 原生导出的对应比例

本次直接连接上述当前 GRH checkpoint 和 GSIM `SimTop_1InferAllWidth.json`。
后者在 splitArray／TopoSort 后补充位宽，尚未执行 removeDeadNodes。
只读取生产端保存的 token path、role、shape、field depths 和投影，不读取 FIRRTL
文本、Init graph 或 split map 恢复来源。数组必须覆盖全部源成员，不能以一个成员
代表整个数组。计数按唯一 SID，多个绑定不会重复计算一个节点。

| SemanticTree 状态 | 节点数 | 占全部 8,780,799 个 SID |
| --- | ---: | ---: |
| 完整对应 | 8,775,552 | 99.940245% |
| 部分对应的结构容器 | 931 | 0.010603% |
| 类型检查未通过 | 1,562 | 0.017789% |
| 显式空源（零宽／零元素） | 2,754 | 0.031364% |

完整对应包含 8,276,380 个直接来源端点、479,566 个原生 aggregate 和 19,606 个
原生 scope；结构对应要求自身有原生记录，且非空后代均完成对应，允许显式空成员
不生成执行对象。剔除空源后的完整对应率为 99.971600%；剩余 2,493 个 SID
未达到完整对应，不能称 100%。非空直接来源端点的完整对应率为 99.981131%。

1,562 个未通过项均已找到同路径、同角色和同 shape 的原生来源，但 sourceWidth／
signed 与 GSIM 物理节点的类型检查未通过：其中 1,553 个 value、9 个
register-current。抽查 MPORT 的 NODE_WRITER 物理 width 为 0，而 FIRRTL 数据源宽度
为正：GSIM 将深度 1 memory 转成寄存器时迁走写入表达式，遗留 writer 无赋值，
随后宽度推断为 0；这些不能当作 FIRRTL 空源。9 个 register-current 的 GSIM 物理
width 也均为 0，GRH 中 8 个源宽度为 1、`currState` 为 4，均为无符号。
931 个 scope／aggregate 因上述后代未通过而列为部分
对应。没有将它们通过路径存在强行计入完整对应。

全量 34,347,436 个 op 中，排除仅归属于原生 external-instance 根的 5,082 个 op，
FIRRTL 实现范围分母为 34,342,354；此排除保守地包含部分边界 adapter，FIRRTL
extmodule 接口字段及其连接仍保留。

| op 归属状态 | op 数 | 占 FIRRTL 范围 op |
| --- | ---: | ---: |
| 全部直接 owner 完整对应 | 34,322,775 | 99.942989% |
| 至少一个完整对应，其他 owner 未全通过 | 864 | 0.002516% |
| 没有完整对应的直接 owner | 18,715 | 0.054495% |

因此按“每个 op 至少属于一个完整对应节点”的要求，覆盖 34,323,639 个 op，
比例为 99.945505%。包含上述外部范围时，全部 owner 完整对应率为 99.942997%，
至少一个完整 owner 的比例为 99.945513%。

结果见 [summary.json](../../ptmp/semantic-bindings/F26/alignment/summary.json)，
以及 [unaligned-nodes-ops.tsv](../../ptmp/semantic-bindings/F26/alignment/unaligned-nodes-ops.tsv)。
TSV 包含 2,493 个未完整对应节点及 19,579 个未达到“全部 owner 完整对应”的 op
（包括上述 864 个已有部分完整 owner 的 op）。空源和外部排除项不列作缺失。
可用 `make measure_semantic_alignment` 重新测量普通 checkpoint；生产流程不依赖此统计脚本。
`make test_semantic_alignment_measurement` 的 17 项覆盖统计器的数组投影、结构、类型、
空源、effect、memory depth、外部边界及 op 分类。

这里是来源对应率与归属率，不是功能等价率。register-next、clock、reset 和
memory-read-address 辅助绑定尚未逐角色验证，不能从本表推导完整状态转移等价。

## 两侧表示与脚本匹配方式

两侧物理 ID 各自独立。共同来源身份由相对顶层的 FIRRTL 路径 token 和 role 表示，
脚本随后核对类型、数组形状与成员覆盖；GSIM 物理 `name` 不参与匹配。

### GRH：来源树、端点绑定与 op 归属

`semanticTree.nodes` 按导出顺序从 1 分配 SID。每个节点的 `parent`、`name`
记录父子关系；沿父链重建源路径，顶层 module 名省略，element 使用 `"[i]"` token。
实例声明与 flatten 后追加的 module 可能具有相同路径，脚本保留所有 SID 并分别核验。

`semanticBindings` 将 SID 绑定到实际 GRH ValueId 或 OperationId，并记录 role、
sourceWidth、sourceSigned、shape、shapeFieldDepths 和可选 projection。
`sourceWidth` 是源元素宽度，独立于实际 value 的整个数组打包宽度。

下面使用已有 `dump-semantic-lineage.fir` fixture 的 `bundle.data : UInt<8>[2]`
说明，仅摘录相关字段。其树路径为顶层 → `bundle`（SID 5）→ `data`（SID 6），
因此重建的 token path 是 `["bundle","data"]`。绑定为：

```json
{
  "semantic": 6,
  "role": "value",
  "value": 4,
  "sourceWidth": 8,
  "sourceSigned": false,
  "shape": [2],
  "shapeFieldDepths": [1]
}
```

这表示 SID 6 的完整来源端点为 GRH Value 4，源类型含两个无符号 8 位元素。
projection 省略表示整个来源。

### GSIM：物理节点上的来源与拆分投影

GSIM 的普通 node／memory 直接保存 `semantic.path`、role、shape、shapeFieldDepths
及 indices，width／sign 位于物理节点上。本例 splitArray 后的两个节点为：

```json
[
  {
    "id": 15, "width": 8, "sign": 0,
    "semantic": {
      "path": ["bundle", "data"], "role": "value",
      "shape": [2], "shapeFieldDepths": [1], "indices": [0]
    }
  },
  {
    "id": 16, "width": 8, "sign": 0,
    "semantic": {
      "path": ["bundle", "data"], "role": "value",
      "shape": [2], "shapeFieldDepths": [1], "indices": [1]
    }
  }
]
```

indices 与源 shape 等长，具体下标表示已选择的源成员，`-1` 表示该轴仍由此物理
节点整体表示；`dimension` 必须与保留轴相符。模块与聚合结构则通过
`sourceScopes/sourceAggregates.semanticPath` 表示，不要求各有一个可执行物理 node。

### shapeFieldDepths：数组轴在字段路径的哪一层

每项表示从根声明出发，遇到该数组轴之前已经经过多少个字段。根声明名、模块及
实例路径不计入这个字段数；它与 shape 一一对应。

| FIRRTL 类型 | 元素访问示例 | 叶路径 | shape | shapeFieldDepths |
| --- | --- | --- | --- | --- |
| `bundle : {data : UInt<8>[2]}` | `bundle.data[0]` | `bundle.data` | `[2]` | `[1]` |
| `bundle : {data : UInt<8>}[2]` | `bundle[0].data` | `bundle.data` | `[2]` | `[0]` |
| `a : {b : UInt<8>[2]}[3]` | `a[0].b[1]` | `a.b` | `[3,2]` | `[0,1]` |

前两行的叶路径、元素类型和 shape 都相同，但下标分别落在 `data` 之后与
`bundle` 之后。shapeFieldDepths 保留这个区别，防止把“字段为数组”与
“结构体组成数组”当作同一来源布局。

### 核验规则与 op 覆盖的含义

1. 路径逐 token 精确相等后，按 role 找到候选。`scopeDepth` 和独立的 `line`
   字段不直接参与比较；WHEN／effect 的行号已由生产端编码到来源 token 中。
2. 比较 shape、shapeFieldDepths、源元素位宽与符号。effect 是操作端点，跳过位宽／
   符号比较；memory 还比较存储深度。深度 1 内存转寄存器时，使用原生
   `originRole=memory-storage` 保留来源，当前端点贡献覆盖，next 端点不重复计算。
3. 对全部合格 GSIM 投影求精确覆盖并集，必须覆盖完整源 shape。本例得到
   **SID 6 → GSIM `{15,16}`**；只匹配一个成员时仅算部分对应。无需一对一物理映射。
4. 结构节点要求原生 scope／aggregate 存在，非空后代完整对应且没有额外未解决来源；
   显式空源单列，不要求生成执行节点。当前主端点角色为 value、register-current、
   predicate、memory-storage、effect，其他辅助角色不据此视作已核验。
5. 对每个 GRH op 读取直接 `semanticIds`，查询其 owner SID 的对应状态。例如本 fixture
   的 op 9 为 `kConcat`，`semanticIds:[6]`，SID 6 完整对应便计入其归属覆盖。
   “至少一个 owner 完整对应”与“全部 owner 完整对应”分别统计。

op 覆盖没有逐个比较 GRH op 与 GSIM 运算，也没有求值或比较绑定 ValueId 背后的表达式。
因此 99.945505% 是归属覆盖率，不能称为 op 运算语义等价率。

## 已知行为差异与验证范围

既有局部行为验证使用同一份 FIRRTL 的历史 GRH v2／GSIM v6 checkpoint，
不同于本文当前原生绑定的 checkpoint；历史证明数量不并入本次对应比例。
完整状态转移、时钟事件、初值、整机可达性和四态 X/Z 等价仍未证明。

已确认的局部差异位于
`cpu.l_soc.socMisc.debugModule.dtm.tapIO_controllerInternal.activeInstruction`。
该 FIRRTL 寄存器使用 `asClock(eq(asUInt(clock), UInt<1>(0)))` 反相时钟，
异步复位值为 1。GRH 保留该复位，历史 GSIM 在 clockOptimize 后将状态驱动折成
常量 0，并失去 active reset；局部 `jtag_reset=1` 复位事件得到 GRH=1、GSIM=0。
最小 FIRRTL case 编译运行也复现了该差异。尚未证明此局部赋值的整机可达性，
也未修补相应时钟模型；新增来源绑定不构成该行为差异已消除的证据。
真实端点对照见
[actual-clock-state-check.tsv](../../ptmp/firrtl-ingest/F26/deep-audit/state-clock/actual-clock-state-check.tsv)，
最小执行反例见
[clock-counterexample.json](../../ptmp/firrtl-ingest/F26/deep-audit/state-clock/clock-counterexample.json)。

外部 SV ClockGate 的 latch／组合门控模型差异属于本次排除范围；FIRRTL 派生时钟及
异步复位的上述缺口仍保留。memory 地址流水及普通寄存器的部分数据函数有历史局部
证明，clock event、更新条件、未知初值和未定义读写碰撞等状态语义仍需逐项验证。
当前生产端已保留原始 WHEN 的 predicate 绑定，历史“没有独立谓词来源”不再描述
当前来源接口，但谓词绑定存在仍不等于完整表达式已证明。

需要复查历史证明时，直接使用其保留的
[完整 ledger](../../ptmp/firrtl-ingest/F26/expression-verification/round2/report/verification.tsv)、
[未解决项](../../ptmp/firrtl-ingest/F26/expression-verification/round2/report/unresolved-nodes-ops.tsv)
和 [输入身份及统计](../../ptmp/firrtl-ingest/F26/expression-verification/round2/report/summary.json)。
这些证据保持历史检查范围，当前状态以本文的原生导出统计及明确未验证项为准。
