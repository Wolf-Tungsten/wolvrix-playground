# F32：两次 DCE 之间的 pass 语义与 GSIM 对齐（计划与进展）

建立日期：2026-11-16。收尾日期：2026-11-18。最新状态：**按用户初步接受当前对齐结果及性能的决定收尾；保留 package-v31 实现，停止本轮性能优化与差异追查。P4 唯一同名对应率为 99.62505091%；第二次 DCE 删除 GRH 21,717 / GSIM 121,487 个 Node。严格全图语义证明及原定正式性能门未通过，未归因差异和未批准前驱问题保留。最终记录见 §9.36**。

本阶段接续已完成的 [F31](F31-dce-alignment-plan.md#1041-f31-完成最终-v51-库存与-dce-后对应占比)，
将新 SemanticTree / SemanticNode 支持推进到第二次 DCE，统一 GRH 与 GSIM
在这段流程中的 Node 转换规则，支持组合数组更新，并将 `kArrayUpdate` 正式
更名为 **`kCombArrayUpdate`**。基础能力完成后逐边界比较语义、修复差异，最后
按对应 pass 与整个窗口测量性能；本轮最终接受范围见 §9.36。

本文件统一记录 F32 的计划、实施进展、工具合同、验证证据和未完成项。
F32 后续更新均写入本文件，不再拆出独立 F32 说明文档；index 和 steps 仅保留入口。
计划和局部测试不表示整机捕获、严格全图语义证明或正式性能验收已通过。
用户此前授权实施 F32.0–F32.5；2026-11-17 进一步要求“继续完成F32，现在转到阶段6和7”。
F32.6 测量与 F32.7 证据整理已执行。2026-11-18 用户明确表示“我接受这个性能了”及
“先初步接受这个结果，完成F32的文档更新然后提交”，本轮依此收尾。
该人工接受不将 F32.5 语义门或原定 F32.6 正式性能门改记为通过。

本轮用户要求“严格按照二值处理，集中修改后统一测试”。当前 F32 窗口以显式
`semantics=2state` 为实施和验收口径，X/Z 按二值仿真策略解释为0；原始 FIRRTL
保留的 FourState 类型标签不再作为保留高位算术需求的理由。以下历史计划和
证据中的四态要求保留其原语境，不能用来扩大本轮退出条件；U3 的四态公共
求值问题不是本轮二值行为验收要求。Node 身份、真实操作槽、状态/外部效果、
来源和继承差异仍须如实记录。新增实现、调用入口及待验事项见 §9.32。

阅读入口：§1–8 为原计划与退出条件，§9 为实施进展（最终接受与保留项见 §9.36），
§10 为待人工审核的前驱问题；[§11 来源诊断](#f32-window-origin-audit)、
[§12 库存与结构索引复用](#f32-inventory-seed)、
[§13 有限重建证明](#f32-reconstruction-certificates)、
[§14 同端逐 pass anchor 证明](#f32-pass-anchor-preservation) 保存工具合同、命令及验证范围。

## 1. 范围与不可越过的边界

### 1.1 唯一实施窗口

```text
GRH：
  第一次 dead-code-elim（不含，只提供输入 P0）
    → expr-opt → used-bits → split-nodes
    → 第二次 dead-code-elim（包含，输出 P4）
  停止

GSIM：
  第一次 RemoveDeadNodes（不含，只提供输入 P0）
    → ExprOpt → UsedBits → SplitNodes
    → RemoveDeadNodes1（包含，输出 P4）
  停止
```

共四个 pass。`AfterSplitNodes` 是 GSIM 的观察边界，不是第五个 pass。
`ConstantAnalysis`、后续 DCE、AliasAnalysis、PatternDetect、CommonExpr、
方言转换、分图、emit 和仿真性能均不纳入 F32；不得为了运行旧脚本而继续执行。

实际入口依据：

- [GSIM main.cpp](../../reference/gsim/src/main.cpp) 中第一次 DCE 后依次调用
  `exprOpt`、`usedBits`、`splitNodes`、`removeDeadNodes`，之后才到 ConstantAnalysis。
- [GRH flow](../../scripts/grhsim_flow.py)、
  [香山入口](../../scripts/wolvrix_xs_grhsim.py) 及
  [pass 文档](../../wolvrix/docs/transform/grhsim-transforms.md) 保持上述顺序。

### 1.2 前驱问题须单独人工审核

实施可以修改四个关注 pass 及其必要的公共支持设施，也可以按本计划做新名字的
机械迁移。机械更名涉及 ingest、前驱 pass 或未迁移后端时，只调整符号、接口、
格式与诊断，不附带改变它们的语义、优化策略或支持范围。

发现 ingest、xmr-resolve、hier-flatten、comb-loop-elim、split-static-array、
第一次 DCE 的问题时，提交独立审核项，给出最小复现、语义证据、建议补丁、
受影响边界和验证计划；**收到明确人工同意后，才能应用该前驱修复并更换基线**。
一般性的 F32 启动同意、时间经过或未回复不视为批准。

第二次 DCE 与第一次 DCE 共用实现。若修改公共 DCE/helper 会改变第一次 DCE
的语义或 P0 输出，也属于上述前驱修复。先用原始输入复核 P0；有变化就单列
审核，不能借第二次 DCE 的范围直接改变第一轮行为。尚未获批的问题可隔离分析，
不能写成已经修复或“GRH 额外能力”的已解释差异。

F31 按用户要求在 v51 收尾，其已冻结差异不自动重开。F32 必须区分 P0 继承
差异和本窗口新产生的差异；窗口内对已有差异的传播、放大和消失仍需记账。

## 2. 已核实的起点与实现缺口

### 2.1 输入与参考身份

规划起点主仓库为 `4ca7a20`，wolvrix 为
`e09a9826b44fa87da829049b6ffb310a107757ce`，GSIM 为
`bb4ddb7d48a8cd9c2f48347602b7ae5362f52cac`。实施每轮另记完整提交、工作树
补丁摘要、构建配置、冻结包与 binary hash，不把这些起点写成后续最新实现。

完整输入沿用 `build/xs/rtl/rtl/SimTop.fir`，SHA-256：

```text
b313a3ecd154cbd9279b14403709806b95fb136cf44b475e9def46a926ecb26b
```

ingest manifest 为 `ptmp/semantic-bindings/F26/grh/ingest-request.json`。
启动时重新校验输入和 manifest，冻结到 `ptmp/firrtl-ingest/F32/` 的本轮清单。

F31 最终第一次 DCE 后，GRH / GSIM Node 为 **5,635,937 / 6,020,694**，
其中 **5,617,898** 个 GRH Node 有唯一 GSIM 同名对应，占 **99.67992900%**。
这些是历史起点的静态名称数据，不能作为 F32 新捕获或语义对齐率。
完整保留集见 F31 §10.41；不覆盖、不改写原始 F31 捕获。

### 2.2 规划起点的源码状态

| 位置 | 已有能力 | F32 必须补齐 |
| --- | --- | --- |
| [PassManager gate](../../wolvrix/lib/core/transform.cpp) | 已支持新树和 ArrayUpdate 到第一次 DCE；三个中间 pass 仍被拒绝 | 逐 pass 完成维护和验证后开放，不能只加 allowlist |
| [ExprOpt](../../wolvrix/lib/transform/grhsim/expr-opt.cpp) | 同分支 Mux 改为 Assign，保留显式 DCE 边界 | 新 Node 的成员、anchor、binding 与源上下文同步；数组更新的完整结构判等 |
| [UsedBits](../../wolvrix/lib/transform/grhsim/used-bits.cpp) | 标量/状态前缀需求与缩宽；索引完整需求；四态算术保护 | 数组更新的区域需求；缩宽后的 sourceWidth、projection、binding 与 Node 维护 |
| [SplitNodes](../../wolvrix/lib/transform/split_nodes.cpp) | 无符号标量纯表达式的安全静态位段子集 | 真实父子关系、切片几何、新身份及成员归属；组合数组更新；与 GSIM 拆分规则的差距 |
| [DCE](../../wolvrix/lib/transform/dead_code_elim.cpp) | F31 已支持数组更新反向区域需求、更新组裁剪及 Node 回收 | 验证前三 pass 改写后的宽度、投影、别名、控制和引用，处理窗口内新暴露的问题 |
| GSIM SplitNodes / exchange | 创建 `$hi_lo` slice Node，原父标记为 SPLITTED_NODE | 当前导出活集合可能漏新成员、仍保留原父；先修生产库存和身份对应，再比较 |

以上为启动时的静态源码检查结论，实施与复现结果见 §9。GSIM 的具体库存问题见
[splitNodes.cpp](../../reference/gsim/src/splitNodes.cpp)、
[Node.cpp](../../reference/gsim/src/Node.cpp) 和
[SemanticNodeExchange.cpp](../../reference/gsim/src/SemanticNodeExchange.cpp)：
当前切片复制未完整记录新的 semantic identity / lineage，现有 liveNodes 收集
不能直接被当作这一步的完整后态库存。

GSIM 当前 ExprOpt 与 UsedBits 保持原 Node 身份和名字：前者改表达式与依赖，
后者改 Node/expression/memory 的有效前缀宽度。SplitNodes 还覆盖符合条件的
unsigned register，并成对拆 current/next；GRH 当前仅有标量纯表达式子集，
寄存器拆分是需要实质对齐的差距，不能列作 GRH 额外能力。

普通 GRH verifier 成功也不等于新树已验证。每个阶段须覆盖
`validateSemanticTree()`、实际 source/binding 一致性和行为 oracle；不要只依赖
现有 pass 内局部 `verifyWhole`。旧测试及 JSON 文档中落后的 gate 描述同步修正。

## 3. 双端统一的 Node 转换合约

先在两个 producer 中实现合约，再让 reader 读取真实结果；禁止由离线工具
补造身份、修改库存名字、猜测父子或隐藏差异以提高匹配比例。

| 转换 | 必须维护的语义与身份 |
| --- | --- |
| 原位表达式改写 | 逻辑 Node 仍表示同一结果时保留 ID、路径、名字；同步实际 op、anchor、边界及依赖，不因删一个表达式分支而删除整个 Node |
| 缩宽 | 保留逻辑身份，明确旧宽到新宽的位映射、符号/逻辑域及 source projection；不能让原始全宽 binding 偷指新窄值 |
| 已证明的转发/合并 | 明确代表值、源身份和被改写的每个 user/operand slot；证据包括完整源上下文、状态/外部绑定；不靠名字或成员集合并集代替证明 |
| 真正拆分 | producer 记录父到子、位段/数组坐标、旧到新端点映射；子项分配新 ID，保留确定且无冲突的名字；退休身份不复用 |
| 新辅助 op | 根据真实所属 Node/共享关系维护 membership；不能一个 helper 或一组更新凭空新增一个具名 Node |
| 第二次 DCE | 从真实可观察根追踪，回收死 op、成员和 Node；保留项必须能追到具体语义根与操作槽位 |

两端同样遵守原始及存活 Node 保名、新成员避让已用名和本次退休名的原则。
允许 GRH/GSIM 物理表达不同，但须给出同一逻辑转换及端点映射；不得为迎合
某一端现有实现而削弱参考端语义。GSIM 的错误同样复现、修复和验证。

成员和边界覆盖 state current/next、读写端口、clock/reset、formal port、
observer、DPI/system task 及事务控制。移除条件或切片后要刷新真实依赖和所有
引用，避免 dangling、共享 op 错归属和同名不同身份。

前三个 pass 不隐式调用 simplify 或 DCE，不做无关全树清扫；真正的结构替换
仍应当场维护 Node 与引用。库存分别记录“具名 Node 存在/退休状态”和“从根
可达性”：P1–P3 中因表达式改写失去消费者、但尚未经 DCE 退休的具名 Node
仍在库存及分母中，不能借导出提前删除。真正拆分已退休的父项单列，新子项完整
纳入；没有独立 Node 身份的残留物理 op 行也单列，不能据此新增具名 Node。
失去使用的旧物理行留给第二次 DCE 清理。

`SemanticId` 与物理 OperationId/ValueId 分开记录。PassManager compact 可在
同一 Session 内重排物理索引；跨快照不得按索引连接。跨端稳定来源、路径与名字
只能建立候选，功能关系另有证据。遇到多候选或缺少映射应明确报歧义。

## 4. `kCombArrayUpdate` 更名与支持合约

### 4.1 更名迁移方案

更名保持 F30 的值语义，统一为一个 canonical op：

- enum、descriptor、字符串、diagnostic、当前文档与测试统一为 `kCombArrayUpdate`。
  builder/view/entry、verify/evaluate helper 及头文件按 `CombArrayUpdate`
  命名同步迁移；不保留第二套 enum 或重复语义实现。
- 新 writer 采用基础 dialect **`grh:4`**，只写新 kind；容器布局未变，
  `formatVersion` 保持 **5**。该格式迁移已实施，验证结果见 §9。
- loader 保留合法 `grh:2` 普通图及 `grh:3` 旧图读取；仅在 `grh:3` 的
  load 边界将旧 `kArrayUpdate` 归一为新 op，照常严格验证。`grh:2` 不接受
  数组更新，`grh:3` 不接受新 kind，`grh:4` 不接受旧 kind；未知版本明确拒绝。
  重写旧图只输出新版本。旧兼容入口不扩散到普通 IR API 或新快照。
- 对齐工具识别格式版本并规范 kind；保留原始版本和 hash。历史文档、冻结包、
  F30/F31 证据保持旧名字，不批量改写成“过去已使用新名”。
- 审计 C++/Python 通用 kind 路径、store/load、fixtures、Make/CMake 源清单
  和调用方；前驱只做已授权的机械迁移，其他语义变化适用 §1.2。

正反例须验证旧图读入、新图 roundtrip、版本/kind 错配拒绝、非法更新组拒绝，
以及更名前后的类型、结果、Node 归属不变。旧 loader 应明确拒绝新版本。

### 4.2 固定操作语义

```text
result = kCombArrayUpdate(
    base,
    enable0, index00, ..., index0(k0-1), data0,
    enable1, index10, ..., index1(k1-1), data1, ...
) { indexCounts = [k0, k1, ...] }
```

`base` 是初始数组；第 j 组 `enable` 是 1-bit 使能，接着的 `kj` 个索引
按外维到内维寻址，`data` 是目标叶或后缀子数组。组按列表顺序执行，后写覆盖
相交区域；所有输入都是进入 op 前的不可变值，唯一结果是最终数组。`kj=0`
表示整数组更新，不是广播。它是 Pure op，不代表状态写或事件。

例如 `base.shape=[2,3]`、叶宽 8，`indexCounts=[1,2]`：

```text
r = kCombArrayUpdate(base, en0, row, rowData, en1, i, j, byte)
// rowData.shape=[3]，byte 为 8-bit 标量
// 先条件更新 r[row][:]，再条件更新 r[i][j]；重合时第二组优先
```

完整类型、边界、未知控制和 X/Z payload 仍按 [F30 §1–2](F30-array-update.md)
定义：确定越界跳过该组；未知控制使用四态 mux merge，不能直接视为 false。
FourState、signedness、多维 shape 和完整索引宽度不得在优化中丢失。

### 4.3 各 pass 的实质支持

| Pass | 数组更新支持的完成含义 |
| --- | --- |
| ExprOpt | 结构判等包含完整类型/逻辑域、base、按序更新组及其 enable/index/data；不同顺序、shape、控制不得误合并；合法同分支改写保持 Node/source/binding |
| UsedBits | 按需求区域和逆写入顺序分析 base/data；仅对已证明必然覆盖的区域消去前值需求；条件/未知/动态重叠保留真实可能依赖；控制和索引需求独立于 payload 缩宽 |
| SplitNodes | 对可证明的静态元素/位段生成等价投影并记录父子几何；动态/跨组共享的边界有明确理由；不能为了通过而先整体降为 packed shift/mask 或忽略更新组 |
| 第二 DCE | 正确消费缩宽、投影和结构替换结果，裁剪死区域/更新组与身份，同时保持后写优先、旧值、状态与外部观察语义 |

阶段内可先做安全透传，以运行局部验证；**全量保守标活或直接跳过整个 op
不代表最终支持完成**。GSIM 没有同名 op 不构成缺口解释，需比较其带索引赋值
与 GRH 更新组表达的同一函数、控制和可观察行为。

## 5. 分阶段实施与退出条件

依赖顺序为 F32.0 → F32.1 → F32.2 → F32.3 → F32.4 → F32.5 → F32.6 → F32.7。
差异定位和小用例准备可并行，正式全图对齐须先通过基础门，性能验收须使用
语义收敛后的冻结版本。F32.0–F32.5 未完成严格全图语义验收，具体证据见 §9；
用户已授权 F32.6–F32.7，并于2026-11-18初步接受现有结果与性能，按下表
F32.7 的用户接受例外收尾。原定正式 F32.6 验收仍要求语义与性能门均通过，
本次不改变这些门的计算结果或未来默认阈值。

本轮按上述用户二值要求应用这些退出条件：语义 oracle、控制/索引和算术
缩宽按 `2state` 解释；历史列出的完整 X/Z 保持不作为当前二值验收门。
二值解释不豁免 source/binding、Node/成员、真实消费者或跨端值的证据要求，
也不将历史四态捕获自动重标为新的二值捕获。集中修改结束后统一运行相关回归。

| 阶段 | 交付 | 退出条件 |
| --- | --- | --- |
| **F32.0 输入与边界冻结** | 冻结原始输入/manifest、双端版本、P0–P4、停止位置、定时身份及前驱审核清单 | 新鲜原生 prefix 得到可验证 P0；与 F31 起点差异有账；证明 P4 后不再执行任何 pass |
| **F32.1 Node 合约与更名基础** | 落实 §3–4；修双端 producer 库存、SplitNodes 新身份/lineage；迁移 API、持久化与 reader | 更名 roundtrip/负例和身份不变通过；最小拆分后库存无漏项/退休父误计；引用闭合；gate 仍逐项受控 |
| **F32.2 ExprOpt 迁移** | 新 Node/source/binding 维护，安全判等和 CombArrayUpdate；对照 GSIM cast、零宽、Mux/When 等实际规则 | 语义正反例、Node 不变式及单步前后 oracle 通过；不隐式 DCE；只开放已完成的 pass |
| **F32.3 UsedBits 迁移** | 位/区域需求、数组更新逆序覆盖、类型缩宽与投影同步；审计 signed/四态/状态与索引 | 独立预期需求和前后行为都通过；动态控制不丢依赖；全部新类型/成员/binding 验证通过 |
| **F32.4 SplitNodes 与第二 DCE 集成** | 补 GSIM 对应拆分能力，支持组合数组更新，维护真实父子映射与命名；接通第二 DCE | 拆分覆盖全部真实消费者需求，投影/重组后可观察行为等价；静态/动态边界有测试；P0→P4 小流水通过；无 dangling/漏 Node；P0 语义不变，否则走前驱审核 |
| **F32.5 全图语义对照与修复** | 双端最新原生五边界数据；逐 pass 差异台账、最小复现、修复与能力差异证据 | 四个 pass 的新增可修差异均已修；额外能力逐项有语义证据；继承项/待审核项单列；未解释新增项为 0 才可宣称语义验收完成 |
| **F32.6 性能验收** | 正确性冻结后运行双端交错样本；四个 pass 及窗口整体的正式统计 | 全部满足 §7；失败/超时/高抖动及资源情况如实保留，不用合计掩盖单 pass 回退 |
| **F32.7 文档与收尾** | 写最终版本、支持矩阵、数据、限制和批准记录；清理可重建中间件，保留完整最终证据 | 语义与性能门均通过后标完成；有未通过项则明确保持进行中，除非用户另外接受收尾范围 |

F32.2–F32.4 每步都测试：无 SemanticTree、带新树、带新 op、带新树和新 op
四种入口，以及不支持的后续 pass 在修改图前拒绝。不能在新树无法维护时静默
清空或降级为旧提示模型，也不能直接开放整个后续流水线。

必要用例覆盖同/异表达式、深 DAG/共享值、零宽、signed 扩展、四态高位未知、
宽索引/越界、同址和交叠后写、不同维数/后缀写、整数组写、未知 enable/index、
X/Z 数据、state current/next、clock/reset、DPI/system task/formal/observer。
按实际改写增加有区分度的正反例；不机械堆重复测试。使用独立 oracle 或小宽穷举，
不能让两端共用同一错误重写公式而互相通过。
拆分仅须生成实际观察区间；只有全宽确实受观察时才要求重组完整原值，不为
满足测试而额外保留无用位段。

## 6. 原生捕获、比较与差异证据

### 6.1 五个边界

| 边界 | GRH | GSIM |
| --- | --- | --- |
| P0 | 第一次 DCE 后 | 第一次 RemoveDeadNodes 后 |
| P1 | expr-opt 后 | ExprOpt 后 |
| P2 | used-bits 后 | UsedBits 后 |
| P3 | split-nodes 后 | SplitNodes / AfterSplitNodes 边界 |
| P4 | 第二次 DCE 后 | RemoveDeadNodes1 后 |

权威数据从相同完整原始 FIRRTL 正常 ingest 得到，每端同一轮采集五个快照，
保存真实 Node、connection、类型、源映射和拆分关系。不能用旧 JSON load
替代原生 prefix：JSON 未保存全部临时 SemanticBindings/source 上下文。
fixture/checkpoint 可用于定位，但不能代替完整最终验收。

默认以静态库存和 producer 当场记录的身份/投影关系完成核查，不将大型 trace
捕获或 trace 重放设为本阶段的必需步骤。已有原生编辑/trace 能力仍应保持正确，
局部回归覆盖其一致性；不能由事后猜测 lineage 补齐生产端缺失。

### 6.2 比较口径

逐个边界记录双方总量、共同候选、缺项、歧义；逐个 pass 比较转换前后的
函数、完整类型、width/signedness/shape/domain、操作数角色与有向依赖、
状态读写/事件/可观察效果，以及缩宽和拆分几何。先做结构与规范化比较，
表示不同的候选继续用独立 oracle、局部等价证明或反例确认。

每项差异登记 `first_boundary`、来源身份、受影响 Node 数、输入证据、消费者
链、语义原因、修复/批准状态和重验结果。区分以下维度，不混算为“已解释”：

- P0 已存在的 F31/前驱差异及它在本窗口的传播；
- F32 新产生的错误或优化缺失，分别记录 GRH/GSIM 责任端；
- 表示不同但有证据证明等价的转换；
- GRH 额外语义所必需的保留或依赖差异；
- 尚待人工批准的前驱问题，以及仍未解释的项。

额外能力的解释必须具体到“哪个 clock、哪次 DPI/system task 调用、哪个
四态/事件/外部观察规则，经什么 op/slot 使用这个 Node”，保存可核验链路。
“存在值需求”“有 user”“为了保守”只能描述现象，不能作为语义归因。
普通缺少优化、漏维护身份、错误拆分及单纯别名残留不能包装成额外能力。

唯一同名比例单独展示，分母为该边界全部存在且未退休的具名 GRH Node，包含
尚待显式 DCE 处理的无消费者项；它不能代替语义通过率或根可达性统计。
区间内新增差异要求应修尽修；无法证明的项明确保留，不能靠调名字、删导出行、
缩小输入、跳过 op 或把差异移到窗口外完成验收。

## 7. 性能完成门

### 7.1 指标和抖动

沿用前阶段默认的合理抖动带：相对 **3%** 或绝对 **10 ms**，取较大值。
对四个对应 pass **分别**判定，并对 P0→P4 **整个窗口**另判定：

```text
median(GRH) <= median(GSIM) + max(0.03 * median(GSIM), 0.010 s)
```

单 pass 和窗口五项必须全部满足。某一步更快不能抵消另一步越界；“比 GRH
改造前更快”、F22 历史计时、不同 checkpoint/机器的 GSIM 时间均不能替代验收。
F30 接受既有实测性能的决定不转移为 F32 阈值豁免。

### 7.2 可比较的正式测量

- 使用同机、相同 CPU 亲和/线程策略、Release 配置、依赖和输入，分别冻结
  binary/package；两端串行交错运行，每端至少 **3 个有效新样本**，记录每轮
  顺序和系统负载。不同时运行两个大图来互相争抢内存/CPU。
- 正式生产计时关闭 trace、库存导出、外部 verify、profile；正确性另轮执行。
  保留生产必需的 Node 维护、改写、依赖更新、prune/compact 和框架成本。
  不得移到 P0 前或 P4 后以缩小分母；共同准备成本须有明确归属并计入窗口。
- prefix ingest/前驱/第一次 DCE 仍正常运行以产生真实 P0，单独报告时间，
  不计入四 pass 分母。窗口计时包含其中发生的所有必需维护；同时输出原生
  pass timer 与窗口墙钟，差值需能对账。
- GSIM 当前第一 DCE timer 为 `RemoveDeadNodes#0`，第二次为
  **`RemoveDeadNodes1#0`**；UsedBits / SplitNodes 的 timer 标签当前分别为
  `{g->usedBits()}#0` / `{g->splitNodes()}#0`，不能用边界名字猜定时器。
  GRH 分次 `run_pass` 也可能重置 ordinal；报告显式保存逻辑序号、call/stage
  和实际 timer label，不依赖模糊 grep。
- 保存全部 wall/user/system/RSS、原始 pass 样本、中位数/范围、失败和 guard
  退出信息。抖动过大先定位负载/内存压力，重跑整组配对样本，不能挑最快值。
  若另提供 trace 模式性能结论，应另成组计量并标明，不能混入默认样本。

运行前核对可用内存和磁盘。初始资源保护沿用 F31 的 96 GiB RSS、memory PSI
25% 持续 8 秒，具体配置随本轮 manifest 保存；压力大时暂停大图并调整运行
安排。guard 是资源保护，不是通过标准；被杀、超时和未完成样本均不得当作有效
耗时。只清理本阶段可重建中间产物，保留 F31 冻结证据。

## 8. Make 入口、产物与最终记录

复用现有 `make test_grhsim_transforms`、`make test_f30_array_update`、
`make test_f31_dce` 及双端公共 exchange 基础；这些入口的历史结果不代表
F32 已通过。实施时根据实际改动选相关回归，并同步旧 gate 预期。

现有 `benchmark_f31_dce` 停在第一次 DCE；`benchmark_f22_xiangshan` 只覆盖
checkpoint 上的 ExprOpt/UsedBits。二者不能直接承担 F32 正式验收。GSIM 的
snapshot CLI allowlist 目前也止于第一次 DCE，须扩展至本轮四个观察点并精确
停止于 P4，配套负例防止误跑后续 pass。

以下六个项目 Makefile 入口现均已实现；性能工具的实际验证和样本状态见 §9.34。
先实现入口再运行，不直接拼装
cmake/ctest/compiler/pip 或 Python 工作流命令：

| 入口 | 用途 |
| --- | --- |
| `make test_f32_foundation` | 更名、持久化、Node 编辑/库存、版本负例及逐 pass gate |
| `make test_f32_passes` | 双端关注 pass 的小例、oracle、SemanticTree/source/binding 与四 pass 集成 |
| `make capture_f32_pipeline` | 双端原始 FIRRTL 新鲜运行，采 P0–P4 并在 P4 停止 |
| `make compare_f32_semantics` | 对五边界和四次变换比较，生成差异与证据台账 |
| `make benchmark_f32_passes` | 无导出/trace 的正式交错样本、资源保护和完整定时 |
| `make compare_f32_performance` | 四 pass 与整体窗口五项判定，输出全部样本及阈值 |

构建日志、冻结 manifest、临时脚本和大图数据均存
`ptmp/firrtl-ingest/F32/<revision>/<purpose>/`；持续回归脚本和 Make 入口入库，
测试 fixture 沿项目目录规则，测试产物写 `wolvrix/build/artifacts/`。
报告至少保留 `manifest`、五边界库存摘要、Node 转换映射、逐项差异表、
修复/人工批准记录、性能原始样本与结论、校验和和复现入口。

最终在本文件追加实施记录，并同步 [index.md](index.md) 与 [steps.md](steps.md)：
逐阶段写实际版本、Make 命令、结果与限制。只有已完成的阶段才改状态；尤其
区分“可安全运行”“Node 维护完整”“语义已对齐”“性能达标”。最初制定规划时
未执行代码变更或捕获；随后实施的实际结果按轮次记录于下文。

## 9. 实施进展

以下各小节按实施时间保留当时的状态、决定及未提交记录；这些历史状态不代表
最终收尾状态。2026-11-18用户初步接受后的最终记录以§9.36为准。

### 9.1 首批基础改造（2026-11-16）

当前各子阶段仍为进行中，以下结果只覆盖已列出的代码与专项，不能代替完整
F32.5 全图验收，也不表示窗口性能已达标。

- 完成 `kCombArrayUpdate`、对应 builder/view/helper 和 core 头源文件的机械
  更名；writer 已改 `grh:4`，loader 在合法 `grh:3` 读取边界兼容旧名，容器
  保持 v5。更名前后的语义实现保持不变，前驱只改调用符号。
- 增加 binding 的 `sourceBitOffset/sourceBitWidth`，独立于原始 `sourceWidth`，
  并提供按值/Node 索引读取和验证后替换 API；替换不删除现存边界引用。
- 增加原生位段父子记录及静态 `bit-slices.tsv`，不依赖启用 trace；快照身份
  包含观察阶段。增加轻量 `node-endpoints.tsv` 保存真实绑定/候选锚点的类型，
  支持后续逐边界类型/投影比较，不将候选锚点冒称精确来源。
- ExprOpt 改为保留 Mux 与两臂各自的逻辑身份，原位去掉条件和舍弃臂，正确
  迁移保留臂 slot；不再通过集合合并制造额外 owner。结构判等排除独立状态/
  外部效果，使用显式栈防止深表达式递归溢出；修复不同输入无 definition 时
  被误判相等的情况。

首批 `make test_f32_foundation`（以既有 `.venv`、`WOLF_ENV_SOURCED=1` 执行）
通过 **5/5**：`transform-f32-foundation`、`array-update-tests`、
`grh-semantic-tree`、`store-semantic-tree-json`、`transform-pass-manager`。
证据为 `ptmp/firrtl-ingest/F32/tests/`；覆盖新旧 dialect 正反例、身份/槽位、
有序更新判等和 binding 原子替换等。这是首批构建的结果，后续修改须继续复验。

GSIM 新增 `test-post-dce-semantic-nodes` 的首次专项已通过：小例五边界 Node
数量为 `[14,14,14,17,16]`，记录 6 条真实位段关系，35 组独立可观察值检查和
3 项 CLI 负例通过；历史回归仍在复核。UsedBits 和 SplitNodes 实现/专项并行
进行；原生完整 P0–P4 捕获、差异修复及语义验收尚未执行。

本轮启动时主机约 178 GiB available，磁盘约 1.2 TiB 可用；不并行运行两个
大图。没有修改 F31 保留数据，没有应用需要人工批准的前驱语义修复。

### 9.2 原生四 pass 小流水和工具首轮验证

`make test_f32_passes F32_WORK=ptmp/firrtl-ingest/F32/native-v1` **13/13 通过**。
包括新的 `transform-f32-{foundation,used-bits,split-nodes,pipeline}`，以及
grhsim-transform、DCE/数组更新、FIRRTL 数组更新、SemanticTree、store 和
PassManager 回归。完整日志见 `native-v1/tests/`。

pipeline 用真实 FIRRTL ingest 正常执行前驱及第一次 DCE，再依次运行四个
关注 pass；在有/无 SemanticTree 两种模式下，各边界用 256 组样本和 P0
对比可观察结果，并检查 Node/use-list、五个静态快照及后续未迁移 pass 的
拒绝边界。独立 UsedBits 已覆盖 22 组场景；SplitNodes 首轮包含标量位段、
动态/未知数组写、寄存器 current/next 与显式第二 DCE，后续正在补充真实
多维 source binding、mask/重叠/observer 等更强检查。

发现并修复的窗口内四态问题：UsedBits 原有十六进制输出会泛化不完整 nibble
中的混合 X/Z 位，改为按需二进制表示。共享测试 oracle 的 Mux 原先把未知
控制当作 true，现按四态条件合并，并增加直接 X/Z 真值用例；这是测试设施
修正，未修改前驱生产语义。

`make test_f32_capture_contract` **8/8 通过**。新增捕获入口会从完整原始输入
运行到 P4，绑定输入/冻结包/依赖身份；有后代进程 RSS 保护、精确定时和停止
边界，默认输出五个静态库存及完整表达式/物理图，不启 trace。
GSIM 首个完整香山捕获保存至 `capture-v1/gsim/`，该轮最终被资源守卫中止，
详见 §9.3；GRH 冻结包待 SplitNodes 补强回归定稿后构建。全图差异分析尚未开始，不能提前标记
F32.1–F32.5 通过；正式性能 F32.6 没有启动。

### 9.3 全图捕获资源记录与窗口内补强

`capture-v1/gsim/` 从原始完整香山输入正常产生 P0–P2，随后在 SplitNodes
达到 process-tree RSS **96.04 GiB**，被 96 GiB 守卫正常终止；P3/P4 缺失。
当时 memory PSI 为 0、进程 Swap 为 0。该轮只保留作诊断与资源证据，不能
作为完整捕获或正式性能样本。原始原因与状态分别见 `guard.json`、
`summary.json` 和 `native-timing.jsonl`，不删除或覆盖。

确认进程已清理、主机 available 回升至约 177.5 GiB 后，串行启动
`capture-v2/gsim/`，使用最新冻结二进制及完整结构导出；RSS 守卫调整为
**144 GiB**，PSI 25% 持续 8 秒不变。该轮已完整结束，guard 为
`completed/child_completed`，没有被控制终止。P0–P4 Node 数分别为
`[6020694,6020694,6020694,6043532,5922045]`。该轮普通 JSON 仍缺少 null
WHEN 分支槽位等证据，只用于诊断；修正导出后的候选另建目录，不覆盖 v2。
仍禁止另一大图并行。

GSIM ExprOpt 的窗口内复现发现：两个 null 子树比较可能崩溃、表达式判等
漏比较 memory/clock/reset/字符串等功能字段、保留 cast 会中断对子节点的
遍历。已在 ExprOpt 本地修复并通过三个原生专项；未改前驱共用的
`checkENodeEq`。v1 使用修复前冻结包，v2 才包含这些修复。

SplitNodes 强化专项已验证真实多维 source binding、重叠切片、mask、多读写
端口和静态快照；随后继续补齐 unsigned arithmetic 拆分与寄存器 next 表达式
切点传播，未将这些优化缺失归为 GRH 额外能力。比较器首轮合约 **13/13**
通过，正在补原生数组更新结构和实际小捕获集成；缺失边界、unsupported 与
仅结构相同均不计为功能对齐通过。

### 9.4 来源和观察边界复核（2026-11-17）

`native-v3/tests/` 的原生联合回归 **13/13 通过**；包括深层共享 DAG 判等、
常量不同字面量相等/不同 payload、切片几何判等反例以及窗口小流水。
UsedBits 的 writer endpoint 重绑改为显式保留 operand boundary use；
原公共 API 默认行为保持不变，前驱调用不受影响。显式位区间另校验原数组
projection 完全落到一个 leaf 时的实际宽度，保留原始 `sourceWidth`。
SplitNodes 新增多事件 writer 检查，clock/reset 绑定保持实际事件值和槽位，
不能统一改指最后一个事件输入。

扩大机械更名回归时，F30 套件首轮 **26/27** 通过，唯一失败是
`grhsim-dialect-tests` 仍断言基础 dialect 为 3；已更新为当前 4，待下一轮重验。
F31 Python 流水入口首次因指定的新目录尚无冻结包而未执行任何用例；将在
新包冻结后明确指定包路径重跑，不记录为已通过。
冻结 package-v1 后重跑该入口，首轮发现静态快照新增两个 sidecar 与旧精确
文件清单冲突；更新清单后 `f31-package-regression-v2/pipeline-tests/test.log`
**7/7 通过**，包含原生 prefix、源上下文、状态等价和小例 journal 兼容性。
这些小例兼容回归不代表运行了完整香山 trace 校验。

捕获工具合约 **8/8**、语义比较器合约 **24/24** 通过；新增原生有序数组
赋值、动态/多维/整数组更新、后写顺序、越界和 WHEN 空分支正反例。
GRH `node-endpoints.tsv.width` 与 GSIM details 均为 **leaf width**；完整物理
GRH JSON 中的 value width 才是 packed total width，禁止比较器再次除 shape。
Make 比较入口已修正为由脚本创建全新输出目录，日志放在其同级。

仍在收敛的证据缺口：GSIM 普通 JSON 的空分支、reset/辅助 tree 与 memory
storage 引用；GRH 拆分对共享 A/B 值必须使用原 consumer/operand slot 的
精确 source witness，以及直接复用具名值时的真实 forward 边。全部限定在
导出和关注窗口内，不借此改变前驱语义。最终包和全图验收等待这些修复定稿。

新增 `make audit_f32_prefix` 对新鲜 P0 与冻结 F31 原生 Node/connection 行
做流式指纹核查，忽略本轮 session/stage 元数据，保留行数、hash 和首批差异。
静态行一致仅说明库存/依赖未漂移，不等同于功能证明。
首个实际结果 `capture-v2/gsim-prefix-audit.json` 确认 GSIM 新鲜 P0 的完整
Node 和 connection 行均与 F31 冻结后态逐行指纹一致；GRH 待新包捕获后复核。

### 9.5 首个冻结 GRH 包与跨端实际小图

`native-v4/tests/` 联合回归 **13/13**，F30 扩回归
`f30-regression-v2/tests/` **27/27**，F31 原生回归
`f31-native-regression/tests/` **13/13** 通过。source witness 回归覆盖共享
A/B 物理值的独立 target/slot、Concat 整段转发、已知数组后写直接转发，
不从 owner 集合生成源边。此前扩大回归的旧 dialect 断言失败已修复重验。

经 `make py_install` 构建并以 `make snapshot_f30_package` 冻结
`package-v1/`。该包绑定完整源码/依赖与 native hashes；它是首轮诊断包，
后续发现的缺陷不回写到该包。真实捕获入口的 GRH smoke 已完成，证据
`capture-smoke-v1/grh/`；与 GSIM 相同的 `post-dce-semantic-nodes.fir`
运行到 P4 后停止，Node 数为 `[14,14,14,16,15]`，五边界验证均通过。

`comparison-smoke-v1/` 对最新实际双端产物比较，GSIM 数量为
`[14,14,14,17,16]`。由此复现真实窗口缺口：寄存器拆分释放旧全宽 writer 后，
GRH 没有重访上游 `selected`，它继续保留全宽身份；GSIM 已拆为两段 128 位。
已定位为处理顺序问题并进入修复，不归为额外语义能力。P0 继承的 clock/state
边差异和未证状态转移另记，名称对应不等于功能通过。

语义工具已提供 `--inventory-only`、`--resume`、`--structure-stage` 和
`--structure-node-limit`；结构索引及逐 Node 证明分批落 SQLite、可断点继续。
捕获合约 **9/9**；比较合约 **36 项（34 通过，2 项依实际产物路径选择执行）**，
另一次指定 GSIM 原生产物的 reader 集成 **36/36** 通过。共同 0/1 输入域的
条件表达式证明与完整四态证明分列，状态/effect、缺字段和 unsupported 仍未证；
partial/P0 继承未证/未配对项均不能让全域验收通过。

GSIM v3 也已完整完成，五边界 Node 数同 v2，wall 850.771 秒、采样峰值 RSS
101.598 GiB；这些仍是带导出的正确性运行。进一步导出审计补齐 reset/辅助
tree、memory storage/端口引用、功能 flags、空槽位和不在调度列表中的存活
具名 Node；新最终候选将在窗口内修复定稿后重捕，旧 v2/v3 不作为完整语义证据。

GRH 首轮完整原始香山捕获已启动于 `capture-v1/grh/`，使用冻结 package-v1，
完整五边界结构、144 GiB/PSI 守卫，与 GSIM 大作业串行。尚未完成；确认的新
顺序缺口会在下一诊断/最终包重验。F32.1–F32.5 的全图完成门仍未通过。

### 9.6 小图实差修复与后续证据

GRH SplitNodes 将删除全宽 writer 后的数据/mask 原 producer 放入有限去重
重访队列，不遍历新增 helper 扩散优化。真实 ingest smoke 现已得到 P3 **17**、
P4 **16**，`selected` 的两段 128 位 child 与 GSIM 对应；第二次 SplitNodes
无 changed，DesignStamp 和几何不变。源边迁移同时支持原 target/value 的
显式无 user forward witness。有 slot/无 user 的共享 A/B 共 6 组回归通过，
没有以 owner 笛卡尔积补边。联合 `native-v5/tests/` **13/13 通过**，正在
构建下一冻结包；package-v1 与其原始全图继续保留诊断身份。

GSIM 最小 `post-dce-zero-width.fir` 复现 P3 的 370 条未解析依赖的同类原因：
UsedBits 把未使用高位结果缩为零宽，SplitNodes 更新树时跳过该 Node，留下
对退休父项的引用。删除这一窗口内跳过后保留 Node/空值语义并更新子引用，
最小用例从失败转为通过；三套原生回归通过，正在完成扩大导出回归。

GSIM `SimJTAG.TCK` 的单项 `external_binding` 缺方向另有
`post-dce-secondary-clock.fir` 最小复现：extmodule 的第二个 clock port
被 ingest 设为 `NODE_OTHERS`，现存字段不足以恢复真实端口方向。
这是 **P0 继承的前驱审核项**，建议保留显式方向并正确建立外部输出绑定；
未修改 ingest，也未将其算成已解释或已修复的窗口差异。

状态比较新增独立条件转移证据，实际小图 P0–P2 的 current/next 端点可证明
在共享已定义 old state、paired 0/1 输入和相同 posedge 采样下的转移相同。
检查 writerOrder、enable、mask、reset 优先级及精确 clock 对应；异步 reset-only
step、多事件及 unsupported 情况仍未证。初始化另记：GRH 的原始 X 初值不改，
GSIM 当前结构缺少初始策略，不能由转移等价推导全轨迹或完整四态等价。
比较合约现为 **43 项（41 通过、2 个外部样本按路径选执行）**；全域验收
未因新增条件证明而放宽。

### 9.7 全图资源处理、GSIM v4 完成与 GRH 重跑（2026-11-17）

`capture-v1/grh/` 首轮在 SplitNodes 中被 PSI 守卫停止，P0–P2 完整、P3/P4
未完成；reason 为 `cgroup_pressure`，memory PSI some/full **59.05%**
持续 **8.0235 秒**，进程 RSS **89.695 GiB**、进程 Swap 0。当时 cgroup
charge 约 155.28 GiB，包含约 88.66 GiB anon 和 57.51 GiB file；本 cgroup
和父 service 的 `memory.high/memory.max` 均为 `max`。这是实际压力失败，
不能当作完整全图或有效性能样本，也不能靠提高 PSI 阈值掩盖。

新增 `make release_f32_cache`，仅对已经 finalized 的 F32 捕获常规文件给出
`POSIX_FADV_DONTNEED` 建议，不删文件、不改内容、不触碰 F31 冻结数据。
首轮处理 56 个大文件、140.39 GiB 文件范围，无错误；主机 Cached 从约
64.78 GiB 降至 12.96 GiB，原始报告为 `closed-capture-cache-release.json`。
捕获工具新增默认开启的每边界 cache 释放，关闭 snapshot/store 后同步再建议
释放，hash 验证后再建议释放已读 artifact；单独记录成本，不改变原生 pass timer。
可用 `--no-release-snapshot-cache` 禁用。工具合约 **13/13** 及实际 GSIM 小图
验证通过；已经启动的 GSIM v4 使用此前脚本，不冒称包含此新策略。

SplitNodes 资源复核发现，当前完整图有 15,105,986 条原生 boundary rows，
其中 13,048,885 条无 user；语义 connections 去重后 8,942,539 条，二者不能
混作同一个规模。原来源 witness 的全图复制现已改为按实际待拆 target
提前保存的惰性快照：只复制候选表达式及状态拆分涉及的 Node 原始 incoming
rows，保持原 target/value/user/slot 证据和生命周期，避免复制全部无 user 行。
新增独立只读 `validateSemanticBindings()` endpoint 校验：检查 source 位区间
与实际标量/完整选中 leaf 的宽度，以及 register-next 的实际 writer data slot、
register-current 的实际 reader result；校验不修改 DesignStamp，也不改变旧
`addSemanticBinding`/tree validator 的前驱契约。共享值、先后改写和拒绝非法
endpoint 的回归已纳入 [native-v6 13/13 日志](../../ptmp/firrtl-ingest/F32/native-v6/tests/test.log)。

最新 endpoint exporter 已升级为 `grh.semantic-node-endpoints.v2`，记录原始
source width/signedness、数组 projection 和 source bit offset/width；比较器
明确区分 v2 native-binding 的完整来源几何与 v1/候选证据，不将后者计为完整。
追加后的 [native-v7 联合回归](../../ptmp/firrtl-ingest/F32/native-v7/tests/test.log)
仍为 **13/13 通过**。经 `make py_install` 和 `make snapshot_f30_package`
重新构建、冻结 [package-v4 identity](../../ptmp/firrtl-ingest/F32/package-v4/identity.json)，
其源码内容 SHA-256 为
`eb9f6c7d04b96f9d70eb5a6ad3630770b7fc9fc0c630b3dabce7c84e540235ea`。
[实际小图捕获](../../ptmp/firrtl-ingest/F32/capture-smoke-v4/grh/summary.json)
P0–P4 Node 数为 **14 / 14 / 14 / 17 / 16**，每界 endpoint 均为 v2。
完整香山 `capture-v2/grh/` 已使用此包重新启动，144 GiB RSS / PSI25% 持续
8 秒守卫及默认 snapshot cache release 均开启。本轮随后在 SplitNodes 报
`SemanticId pool capacity` 而失败，见 [capture 报告](../../ptmp/firrtl-ingest/F32/capture-v2/grh/summary.json)。
[原生 timer](../../ptmp/firrtl-ingest/F32/capture-v2/grh/timings/split-nodes-0.jsonl)
记录 **179.254 秒，complete=false**；这是未完成 pass 的诊断耗时。
[守卫报告](../../ptmp/firrtl-ingest/F32/capture-v2/grh/guard.json) 为
`child_exit`、returncode=1，未触发 RSS/PSI 终止，采样进程 Swap 为 0。
P0–P2 表 footer 完整、各有 **5,635,937** 个 Node，P3/P4 未产生；不能把
这些局部数据或小图结果写成完整 GRH 窗口或有效性能样本。

GSIM [capture-v4 报告](../../ptmp/firrtl-ingest/F32/capture-v4/gsim/summary.json)
现已 **completed，native returncode=0**，使用完整字段/库存及零宽引用修复。
同一原生 run 产生五个不同 snapshot ID，原始输入 SHA-256 与 §2.1 一致，
明确在 `RemoveDeadNodes1` 停止。各表 footer 均完整，Node/details 行数一致：

| 边界 | Node 数 | connection 行数 | bit-slice 行数 |
| --- | ---: | ---: | ---: |
| P0 | 6,020,694 | 9,506,107 | 0 |
| P1 | 6,020,694 | 9,501,159 | 0 |
| P2 | 6,020,694 | 9,473,595 | 0 |
| P3 | 6,043,532 | 9,510,550 | 31,170 |
| P4 | 5,922,045 | 9,361,136 | 31,170 |

五份完整结构声明 `gsim.node-structure.v1`、`nodeStructureComplete=true`、
`assignmentOrder=native-vector-order`，capture 报告保存各文件 hash。
这说明原生导出合约齐备，不代表行为已经比较通过；五界 external_binding
coverage 仍为 **partial，1,151 resolved / 1 unresolved**，未隐藏该缺口。
[资源守卫](../../ptmp/firrtl-ingest/F32/capture-v4/gsim/guard.json) 记录
144 GiB / PSI25% 持续 8 秒，**3,718** 次采样后以 `child_completed` 正常结束；
native maxRSS **101.59 GiB**，采样进程 Swap 为 0。报告总 wall **931.45 秒**
包含 prefix、五界结构/库存导出和 hash 校验；`formal_performance_sample=false`，
未启 trace 或 trace validation，不能作为 §7 正式性能样本。

新鲜 P0 静态审计现已分别覆盖
[GSIM v4](../../ptmp/firrtl-ingest/F32/capture-v4/gsim-prefix-audit.json) 和
[GRH v2](../../ptmp/firrtl-ingest/F32/capture-v2/grh-prefix-audit.json)：
两端各自的 Node/connection 行指纹均与冻结 F31 完全一致，无首批行差异。
GSIM 报告 `capture_complete=true`，GRH 报告明确
`capture_complete=false`；后者只核验失败轮中完整的 P0，不将后续失败隐藏。
这证明已审计的静态 P0 库存/依赖未漂移，不能代替函数等价或完整窗口验收。
早期 GSIM v2 及 GRH v1 审计继续作为对应旧轮证据保留。

捕获工具合约 **13/13** 通过。此前比较器合约为 **45 项中 43 项通过、
2 项可选原生集成跳过**，见
[tools-v4 日志](../../ptmp/firrtl-ingest/F32/tools-v4/tool-tests/semantics-contract.log)。
最新 reader 实际集成与剩余缺口见 §9.8；GSIM 单端完整捕获不替代完整双端
语义验收，F32.6 尚未启动。

### 9.8 Reader 固定诊断与 SplitNodes 后续缺口（2026-11-17）

本轮 reader 已锁定，[reader-diagnosis-v4 合约日志](../../ptmp/firrtl-ingest/F32/reader-diagnosis-v4/tool-tests/semantics-contract.log)
记录 **65/65 通过、零 skip**，包括最终 GSIM 原生产物五界、空槽/有序部分
赋值，以及推宽后真实 HEAD/TAIL/DSHR 等表达式记录；不再用早期有 skip 的
45 项摘要充当此次实测证据。

[comparison-smoke-v4-reader-v4 报告](../../ptmp/firrtl-ingest/F32/comparison-smoke-v4-reader-v4/summary.json)
五界各有 **5 个独立 anchor** 在报告限定的共同二态边界前提下已证；对应
`low/high/regLow/regHigh/collision` 仍因 F32-U2 继承的无关成员而保持
`owned_operations_not_reached_from_anchor`。报告明确
`anchor_proof_does_not_prove_membership_or_full_Node=true`，因此不将独立
anchor 证明提升为完整 Node 或四态行为通过，也未在 F32 窗口清扫前驱成员。

同一小图 P0–P2 各两个 state endpoint 只有共同 defined old-state / posedge
采样前提下的 transfer 检查；初始化和完整四态状态行为仍未证明。P3/P4 各
**4 个**拆分后 state endpoint 报 `unpaired_GRH_subgraph_boundary`，是本窗口
新暴露的 metadata 缺口，尚在修复与验证，不能归入 P0 已有状态证明或额外能力。
小图整体仍为 **semantic_acceptance=false**。

SplitNodes 当前针对逐 parent 退休导致共享 member 历史池重复复制，以及
新 next writer enable constant 的归属缺口进行修复与验证；这些修复尚未完成
新包与全图验证，不先记录为已修复。当前仍**没有完整 GRH P0–P4 捕获**，
没有完整双端语义验收，也没有正式性能验收。

### 9.9 SplitNodes 共享归属池与控制 cone 修复

容量异常已用有界原生实验定位到历史成员列表的重复分配，而非真实 Node ID
用尽：2,048 个 Node 共享一个 value/op，逐项退役使 pool 从 2,048 增至
2,100,192；一次 `replaceSemanticNodes` 批量退役保持 2,048。逐项追加也有
同类增长，原始数据见
[semantic-pool-diagnostic](../../ptmp/firrtl-ingest/F32/semantic-pool-diagnostic/analysis.md)。
未扩大 pool 上限，也未修改 core/ingest/前驱语义。

窗口内 SplitNodes 改为一次退役全部父项、按实际 physical op 批量合入 child
归属并保留首次追加顺序。`claimCone` 从实际 child/控制操作数出发，迁移本次
helper 或原 parent 拥有的纯计算，在原 value/user/slot 或显式 forward source
边界停步；不根据其他 owner 反推源。原 next enable 常量和四态完整表达式投影
的局部计算因而获得实际使用它们的 child 归属，原 F32-U2 仍保持独立继承项。
原 parent 的反向成员表用于判断拥有关系，避免逐 child 扫描共享 op 的巨大
owner 列表。

128 个共享父项的回归在修改前以 pool 增量 **9,025** 失败，修改后为
**1,024** 并通过。`split-pool-final-local/split-nodes/tests/` 定向套件和
`native-v8/tests/` 联合 **13/13** 通过，随后 `make py_install` 及
`make snapshot_f30_package` 冻结 `package-v5/`。实际
`capture-smoke-v5/grh/` 五界完成，`comparison-smoke-v5/` 中拆分状态端点
已不再报 GRH 未配对控制边界；P3/P4 四个端点推进到
`missing_native_state_expression_tree`，正在核查 GSIM 辅助树及 reader 条件。
初始化、完整四态和完整 Node 仍未通过。`capture-v3/grh/` 已以该包启动最新
原始全图，144 GiB / PSI25%8s、每边界 cache release，尚未完成。

随后 reader 按原生 CURRENT 的 `ZERO_RESET=3` 与显式 null 执行树处理无
reset 情形；同步 reset 仍要求真实 `OP_RESET` 执行树，存在的辅助槽另作
一致性校验，不由 NEXT 的枚举或父树猜测语义。
`reader-diagnosis-v5/tool-tests/semantics-contract.log` **68/68、零 skip**；
`comparison-smoke-v5-reader-v5/` 的 P0–P2 各 2 个、P3/P4 各 4 个状态端点
条件转移全部通过。初始化仍 `unverified`、完整四态仍未证，U2 的完整成员
问题仍单列；未放宽全图验收，也未修改冻结 GSIM producer。

另外，实际小图
[split-strategy-probe](../../ptmp/firrtl-ingest/F32/split-strategy-probe/report.md)
确认三类策略差异：GRH 的 whole-user 门阻止切分、普通 producer Cat 边界未
参与切分、较窄片段缺少 GSIM 的静态 B/C/delta 收益门槛。P0–P2 两端均
16 Nodes 且零库存差异，P3/P4 为 GRH 17 / GSIM 18。这些属于优化策略差距，
不能解释为额外能力；尚未在这一版同时改写策略，后续结合完整图证据处理。

### 9.10 最新 GRH 全图的边界迁移校验失败

`capture-v3/grh/` 已结束，仍为 **failed**：P0–P2 完整，SplitNodes 最终校验
报 `semantic boundary operand evidence differs`，P3/P4 未捕获。native timer
为 **78.659576909 秒、complete=false**，不可作为有效完整 pass 或性能样本。
本轮采样峰值 RSS **78.9966 GiB**、进程 Swap 0、PSI some avg10 最大值 0；
守卫为 `child_exit / returncode=1`，未触发资源保护。

已越过上一轮身份池容量失败的位置，但出现了后续真实边界 operand/slot 证据
不一致。正在检查 ordinary/state/retry 连续改写中的 pending witness 运输，
须复现并修复实际来源迁移，不能丢弃不合法行或根据 owner 猜源来通过校验。
同时补充失败状态的独立诊断导出和具体 Node/op/slot 诊断；失败诊断不进入
权威 P0–P4 快照，不补造 complete。当前仍没有完整 GRH 全图或双端语义验收。

该错误已在小图精确复现：保留的别名 A 指向 `useA$2_0/$5_3` 两个 child，
记录的是 XOR 源值，而对应 user 已被后续生产式拆分改成读取 Concat 的 Assign。
修复让新 child 边立即进入 Graph 正式边界表，沿既有 operand transport
运输实际 value；去掉 prepareNode 的旧 incoming/outgoing 缓存，finish 只读取
最后一次改写后的 live rows。保持原 source/kind 和真实 user/slot，不从当前
owners 重建来源，不丢弃校验失败行。原始 slot 与显式 forward 两种回归从
失败转为通过，`native-v9/tests/` 联合 **13/13** 通过。

`package-v6/` 已经 Make 构建并冻结，`capture-smoke-v6/grh/` 完整；
`comparison-smoke-v6/` 中状态条件转移仍为 P0–P2 各 2、P3/P4 各 4 通过，
其余限制不变。`capture-v4/grh/` 已用新包和相同资源门启动，尚未结束。
捕获工具另以 **16/16** 合约验证失败状态诊断导出；原始 pass 失败始终保留，
诊断结构单列为 `non_authoritative/mutated_failed_state`，不进入 P3/P4。

### 9.11 首个完整 GRH 五界捕获与全图比较准备（2026-11-17）

`package-v6/` 的 [capture-v4/grh 报告](../../ptmp/firrtl-ingest/F32/capture-v4/grh/summary.json)
现已 **completed**，从 §2.1 相同完整原始 FIRRTL 正常执行 prefix 和四个
关注 pass，在第二次 DCE 后停止；没有执行后续优化或 emit。五个快照来自
同一 run，各界 Node inventory/footer 完整，endpoint 均为
`grh.semantic-node-endpoints.v2`：

| 边界 | GRH Node 数 |
| --- | ---: |
| P0 | 5,635,937 |
| P1 | 5,635,937 |
| P2 | 5,635,937 |
| P3 | 7,029,767 |
| P4 | 7,003,972 |

[本轮 GRH P0 审计](../../ptmp/firrtl-ingest/F32/capture-v4/grh-prefix-audit.json)
为 `capture_complete=true / static_rows_unchanged=true`：Node **5,635,937**、
connection **8,957,763** 行均与冻结 F31 完全一致，无首批行差异。GSIM 最新
完整生产物仍为 §9.7 的 `capture-v4/gsim/`，其已完成 P0 审计继续有效。
这些审计只确认前驱静态库存/依赖未漂移，不将其提升为行为等价证明。

[资源守卫](../../ptmp/firrtl-ingest/F32/capture-v4/grh/guard.json) 以
`completed / child_completed / returncode=0` 正常结束，限制仍为 144 GiB
RSS 与 PSI25% 持续 8 秒。**2,646** 次采样的峰值进程 RSS **77.309 GiB**，
进程 Swap 0，memory PSI some/full avg10 最大值均为 0。报告总 wall
**662.719 秒**包含 ingest/prefix、验证、五界导出及 hash 校验。

四个原生 pass timer 均为 `complete=true`，保留为本轮捕获诊断：

| 逻辑 pass | 原生秒数 | 原始 timer 文件 |
| --- | ---: | --- |
| ExprOpt | 9.169546810 | [expr-opt-0.jsonl](../../ptmp/firrtl-ingest/F32/capture-v4/grh/timings/expr-opt-0.jsonl) |
| UsedBits | 20.052003984 | [used-bits-0.jsonl](../../ptmp/firrtl-ingest/F32/capture-v4/grh/timings/used-bits-0.jsonl) |
| SplitNodes | 70.980679804 | [split-nodes-0.jsonl](../../ptmp/firrtl-ingest/F32/capture-v4/grh/timings/split-nodes-0.jsonl) |
| 第二次 DCE | 36.176694819 | [dead-code-elim-1.jsonl](../../ptmp/firrtl-ingest/F32/capture-v4/grh/timings/dead-code-elim-1.jsonl) |

第二次 DCE 的逻辑 occurrence 为 1，但分次 `run_pass` 的原生标签重置为
`dead-code-elim#0`，按实际调用/文件绑定，不能用标签字符串误配第一次 DCE。
本轮 `formal_performance_sample=false`，没有 trace 或 trace validation；
单轮正确性捕获及其原生计时不构成 F32.6 的正式交错性能验收。

最新原生联合回归仍为 [native-v9 13/13](../../ptmp/firrtl-ingest/F32/native-v9/tests/test.log)，
reader 为 §9.9 的 **68/68、零 skip**；
[捕获合约](../../ptmp/firrtl-ingest/F32/tool-tests/capture-contract.log) 为
**16/16**。`comparison-v1/` 正以 `--inventory-only` 对最新双端五界建立
SQLite 索引，截至本次记录尚无完整比较结果；库存比较也不能代替后续结构、
条件状态转移及四态语义证明。

三例 SplitNodes 策略差距已由 §9.9 的实际 probe 确认。正在按 GSIM 的实际
B/C/delta 收益门槛、producer component 和 whole-value 重建规则进行窗口内
对齐，尚未形成新版本，不能将策略修改计入 `package-v6` 或本轮捕获结果。
**完整捕获不等于语义或性能验收**：F32.5 仍进行中，F32.6–F32.7 未启动；
初始化、完整四态、完整 Node 与前驱人工审核项继续按既有边界保留。

### 9.12 比较数据库查询计划修正

`comparison-v1` 的未完成库存建库已主动停止，进程 exit 130，保留
`inventory_complete=false`，没有最终 summary，不作为可恢复的完整比较结果。
原始双端 v4 捕获不变。停止依据是只读 `EXPLAIN QUERY PLAN`
在 SQLite 3.45.1 上确认四处索引顺序不匹配：canonical edge/slice 的跨端
反连接会扫描对侧表；按 child 找切片以及 P4 切片历史存在检查不能使用完整
等值键。真实 P3 切片已有百万级，重复扫描不适合作为后续全量工作流。

原始 current/candidate plan 见
`reader-plan-audit/plans.json`，运行/容量与恢复边界见
`README-comparison-scale.md`。正在按实际查询键补齐索引并回归，再以新 reader
身份和新 comparison 目录重建；只改变索引，不改变原生产物、配对候选或证明
规则，也不把建库中断写成语义失败或成功。

纯索引修订已完成，`reader-index-v6/tool-tests/semantics-contract.log`
**70/70、零 skip**。新增回归在关闭自动索引时验证四处完整键 SEARCH，并
核对旧/新索引下所有小图差异行相同。新 reader SHA-256 为
`cd4aa9ad9f0f203a5a576616a44d2a1754030ecec22358da9733344434ac12f7`；
`comparison-v2/` 已以该身份启动新的完整库存建库，尚无最终结果。

### 9.13 原生结构预建与独立身份审查

`comparison-v2/structure/P0/` 原生结构预建已正常结束（exit 0），
`index.json` 绑定两份 v4 原生 JSON 的路径、字节数和 SHA-256，记录
GRH **5,635,937 Nodes / 15,922,640 ops / 15,404,491 values**，GSIM
**6,020,694 Nodes**，数据库约 25 GiB。它只完成结构索引，没有配对或证明结果；
须等完整库存建库结束后才以同一 reader 恢复 P0 证明，不重复建库或读取未提交行。

随后 P2 独立结构预建也已正常结束（exit 0），记录 GRH **5,635,937 Nodes /
16,079,259 ops / 15,561,110 values**、GSIM **6,020,694 Nodes**，绑定
`capture-v4` 的真实 UsedBits 后结构。P1 正在按同一入口预建；这些均是有界
流式 SQLite 索引工作，不在内存中另载一份生产全图，也不产生行为验收结论。

完整 v4 中已定位一例窗口新丢失的 source witness：逻辑别名 61745
`cpu.l_soc.socMisc.xbar.x1_nodeOut_1.d.bits.opcode` 与 7671834
`cpu.l_soc.socMisc.xbar.out.d.bits.opcode_2` 共享物理 anchor 60091。
target 63673 `cpu.l_soc.socMisc.xbar.beatsDO_opdata_2` 在 P2 明确读取
7671834；P3 拆分匿名 Assign helper 后变成两源歧义。这里的物理 ID 均为
各自 `design.json` 命名空间，不能与 endpoint runtime ID 混用。
该问题是窗口改写证据丢失，不能按 P0 已存在别名解释为继承，也不是额外能力。

新 SplitNodes 策略正在限制候选为真实逻辑 anchor，并进一步为共享同一
ValueId 的独立 SemanticId 分别规划静态收益、选择实际 user/slot、生成 child
和退休父身份。物理投影可以共享，但不能用 `owners.front()`、所有消费者的
并集或“物理值无用户”代替各逻辑身份的实际来源证据。上述源码和新增回归尚在
修改，**不属于已冻结 package-v6 或 v4 捕获结果**；新包、完整回归和全图重验
尚待完成。

验收口径另经只读审阅：现有 reader 的 `semantic_acceptance` 要求五界整图
配对及完整证明覆盖，P0 的 F31 继承差异、初始化和完整四态未证均使其保持
false。该字段不改义、不放宽。F32 窗口还需独立核查每次改写、新差异及继承
传播；同名、同 reason 或差异净数量下降只能作线索，不能证明继承或语义保持。
已补充基于真实同端 SemanticId/父子几何的[独立来源诊断工具](#f32-window-origin-audit)，
Make 入口为 `audit_f32_window_origins` / `test_f32_window_origin_contract`，
独立小型 fixture 最新 **25/25、零 skip**。它拒绝未完成或带 SQLite sidecar 的
输入，来源关系与语义证书分列；尚无证书导入器，`window_acceptance=false`
表示工具覆盖未完成，不把待证条目数当作新错误数。默认每表 10,000 行 /
64 MiB 数据库；映射仍驻内存，未对生产比较库运行，不宣称生产规模就绪。
当前 F32.5 尚未验收，F32.6–F32.7 未启动。

### 9.14 SplitNodes 静态策略与独立身份修复通过联合回归

新实现已按 GSIM 静态 B/C/delta 规则处理 scalar producer/reference component，
允许有 whole user 时按实际收益拆分，并以真实 Concat 重建这些用户。
同一 anchor 上的每个 SemanticId 独立收集 source/target/user/slot 引用、规划
切片及退休；未拆 owner 的 anchor、原 op 归属和原来源继续保留。已知只属于
B/C 的歧义槽不阻止 A 的独立引用，未知来源不猜选、不扩大为 owner 全集。
无返回值 effect 和 writer 的引用推导携带真实 root user/slot。

新 Concat helper 归属实际 consumer，只沿确有 child source 的重建路径补
membership，在已存在的 child anchor 停步。匿名 helper 不作为独立 Node
优化，避免 §9.13 的源证据丢失。producer component 推导使用显式栈；
不兼容的 mux/bitwise 分区按完整计算处理。只有实际可生成的 scalar register
family 才发布 state cut；当前限恰好一项 Constant init，Random/Fill/Readmem/
多步初始化保留原形且不向下游发布虚拟分区。多 writer/mask 的生产成本按完整
计算，原 clock/reset/enable、写入顺序和四态行为保留。组合数组更新仍使用
静态区域投影及原四态 oracle，不借此绕过 scalar 收益门槛。

`native-v10` 曾为 12/13：旧 `grhsim-transform-tests` 的 8-bit 两读者用例
强制要求拆分，与新收益门槛冲突。仅增加这些测试 fixture 的真实独立静态
读者及补区间，保留原语义、属性和 oracle 断言；production 未增加旧策略开关。
`native-v11`、最终 [native-v12](../../ptmp/firrtl-ingest/F32/native-v12/tests/test.log)
均 **13/13** 通过。最终新增回归覆盖 A/B 同 consumer 不同 slots、不同
logical target 共用同一 physical Eq slot、创建顺序反转、局部歧义、深 DAG、
effect 成本和不可拆状态的虚拟 cut 保护。

只读小图排查另确认：普通 FIRRTL direct/hierarchy 的内部 Node 和顶层输出
由独立 Assign 隔开，未发现 output gate 阻止内部拆分的实际例；无用户 gate
也没有已证的新阻断例。保留现有条件，不为假设扩大修改范围。原始证据在
`port-anchor-probe/review.md` 与 `unused-producer-probe/review.md`。
本轮正在安装并冻结新包，实际双端 probe 与完整 GRH 重捕获尚待完成；
**上述回归不替代新生产物与 F32.5 验收**。

### 9.15 package-v7 实际小图与新暴露的来源缺口

`make py_install` 和冻结 `package-v7/` 已完成，四份有效 native alias 输入的
实际 before/after 验证全部通过：仅 A 拆成 128/128，B/C 的身份、原来源和
slot 保留，创建顺序反转结果相同；原 `{B,C}` 候选仍为 `[8,9]`，不含 A。
12 条 resolved 的共享 consumer 小图仅因 A 展开变为 14 条 resolved，完整
连接 multiset 无额外或缺失边。`unused-condition` 的 H 拆分与公共连接也与
冻结 GSIM 相同，P4 两端均 6 Nodes。实测记录已写入
`alias-split-probe/review.md` 和 `unused-producer-probe/review.md`。

三策略实际 probe 中，P0–P2 两端均 16 Nodes、零静态差异；P3 均 18 Nodes、
拆分几何完全一致。但 [comparison-v7](../../ptmp/firrtl-ingest/F32/split-strategy-probe/comparison-v7/summary.json)
仍有新来源问题：mixed child 到达投影值时过早将其当作完整源边界，漏掉真实
Slice helper 的成员；无 user 的原 forward 行也未迁移到 whole 重建的实际
槽，P4 因而 GRH 16 / GSIM 18，producer children 被回收。实际 state smoke
另发现旧 writer 删除时 tombstone 掉其 state_update 关系，P3/P4 GRH 0 条、
GSIM 2 条；虽然共同 defined old-state/posedge 的条件 transfer 仍为 4 个
端点通过，不能据此忽略缺边。

完整 GRH 重捕获尚未启动，先用这三个实际反例补齐窗口 producer。修复需让
投影 cone 在真实完整输入处发布源边、以原 forward slot Origin 运输身份，
并在删除旧 writer 前单独保留结构 state_update 关系，映射到对应范围的真实
child writer/current。不得恢复旧 operand 缓存或按共享值猜源；新版本仍待
联合回归、冻结和上述实际小图重验。

独立来源工具已在 `window-origin-smoke-v7-v2/` 完成真实小图集成。报告为
126 个身份延续、20 个 producer projection、4 个 unresolved-origin；后四项
是 operation-only 的 NEXT 父项缺物理几何，明确报 incomplete geometry，
不把 value=0 的占位行当作真实 0-bit 值而误报越界。它仍不证明转换语义，
未扩大到生产规模。

全图库存建库现已读完 v4 双端 P0–P4，仍在派生配对、依赖差异、lifecycle
和切片关系，尚未发布完整结果。P0/P1/P2 三个独立原生结构索引均已正常
完成；这些产物属于 v4，不能冒充尚未生成的新版本。

为后续新生产物避免重复解析完全相同的库存，另新增
[独立 inventory seed 助手](#f32-inventory-seed)，小图 **14/14、零 skip**。
仅在源比较已完成关闭、reader 身份相同、双侧冻结 hash 各自有效且除首行
metadata 外 header/rows/footer 逐字一致时，复制原始分区；当前 run/snapshot
身份来自新捕获，所有派生表重新计算。报告明确沿用既有 resume 的 cache
信任，不声称独立重验旧数据库每行。成功 receipt 先于完整 checkpoint 发布，
未改锁定 reader；未执行生产 seed，也未实现结构索引复用。实际小图可由
未修改的 reader 恢复并得到与 fresh 相同的结果。

### 9.16 package-v8 实际小图重验与完整 GRH 重捕获

§9.15 的四项窗口来源缺口已修复：投影 cone 在真实完整源输入处发布边界，
完整类型/几何相同才替换旧槽；无 user 的 forward 按原始 slot Origin 运输到
实际 child 槽；删除旧 writer 前保存真实结构 state_update，按同范围配对
NEXT/CURRENT 和新 writer；同值 sibling child 以父 SemanticId、范围及实际
op/slot 区分，不以 ValueId 选择身份。未恢复旧 operand 缓存，也未修改前驱。

联合回归 [native-v16](../../ptmp/firrtl-ingest/F32/native-v16/tests/test.log)
**13/13 通过，0.62 s**；`make py_install` 和冻结 `package-v8/` 均已完成。
以下真实小图均使用此冻结包，GSIM 沿用相应未变的冻结输入：

| 小图 | 实际结果 | 尚未证明的范围 |
| --- | --- | --- |
| 三策略 `split-strategy-probe/comparison-v8` | P0–P2 两端各 16 Nodes，静态差异为 0；P3/P4 两端各 18，presence/type/connection/split geometry 差异为 0 | P3/P4 各两个 whole Eq 因 Concat 与 OR/SHL 表达不同、超过穷举预算仍为 unverified；不是已发现反例 |
| 状态 `comparison-smoke-v8` | 五界两端均为 14/14/14/17/16；P3/P4 各两条 resolved state_update、零 unresolved；条件 posedge transfer 在 P0–P2 各 2、P3/P4 各 4 个端点通过 | U2 五个输出 membership 缺口仍为继承；初始化、完整四态、完整 Node 未证；clock 与跨 child 依赖差异继续调查 |
| 重复 child `repeated-child-probe/comparison-v8` | P3/P4 两端各 5 Nodes，5 resolved、零 unresolved；low child5 只在 Concat slot1，high child6 只在 slot0；P4 均保留；机械断言通过 | P3/P4 的 y 各一个同类 whole Eq 仍为 unverified |
| 四组独立别名 `alias-split-probe` v8 | independent/reverse 各 10 resolved，shared-slot 为 11 resolved 加原一条 unresolved `[8,9]`，shared-consumer 为 14 resolved；B/C 原身份、原 Eq 槽及完整连接 multiset 保留，只有 A 生成 128/128 children | 原 B/C 歧义没有消除，也没有猜选为 A |

重复 child 的两次只读人工复核确认 unsigned256
`Concat(high128, low128)` 与 `OR(SHL(high128,128), low128)` 在共同二态下
恒等，宽度、符号和槽顺序一致；这是人工语义复核，未升级 reader 的工具证明
状态，未证明四态。详细证据在
[重复 child 报告](../../ptmp/firrtl-ingest/F32/repeated-child-probe/report.md)、
[别名报告](../../ptmp/firrtl-ingest/F32/alias-split-probe/review.md) 和
[第二视角审查](../../ptmp/firrtl-ingest/F32/review/whole-rebuild-source-review.md)。

使用 `package-v8` 的完整 `capture-v5/grh/` 在 `hier-flatten#0` 被资源守卫
终止，Make exit 2、child -15，原因为 `cgroup_pressure`：父 cgroup 的 some
avg10 为 32.83%，超过 25% 持续 8.024 s。最后样本的进程 RSS/HWM 为
82,432,589,824 bytes（约 76.77 GiB），进程 Swap 为 0；不是 144 GiB RSS
上限触发。ingest 已完成（163.374 s），尚未产生 P0–P4，不能记为窗口 pass
失败或完整数据。该轮保留 summary、guard、samples 和日志，不覆盖失败。
先等待全图库存派生结束、资源压力回落，再以新目录串行重试；完成后须重新
做 F31/P0 静态审计，再使用实际新产物比较。完整 GSIM 仍为 v4，
不因 GRH 窗口修复重复运行未变的参考端。`comparison-v2` 仍在派生旧 v4
全图库存，尚无最终 summary；不读写活动数据库、不复建同一库存。

上述小图均未通过严格整图 `semantic_acceptance`。F32.5 继续进行，
正式 F32.6 性能验收与 F32.7 收尾均未启动。

### 9.17 state child 精确投影与 package-v9

v8 的两条跨 NEXT child 依赖已定位为真实生产结构冗余：两个 NEXT child
都拥有 whole `Concat(high128,low128)` 后各自 Slice，原生 source 边也确实
同时列两源，不是 reader 造边。`slice(concat(H,L),127:0)=L` 及高半的对应
等式是 0/1/X/Z 的逐位恒等。修前具体 op、槽及位段见
[证据报告](../../ptmp/firrtl-ingest/F32/state-child-dependency-v8/report.md)。

SplitNodes 现依据原生 incoming row、仍存活的 original op/slot、已登记
parent/range 和真实 child reconstruction 精确投影，整 child 用独立 Assign
建立槽，严格子区间只 Slice 对应 child；membership 与 source 同步收窄。
同值 sibling 仍以各自父身份/范围/槽区分，真正 whole consumer 继续重建。
未改变前驱、clock/event、真实 writer 或 state_update。

新增 public dependency 断言在修前失败、修后通过；新增 `cat(h,h)` 到拆分
state 的用例亦通过。[native-v17](../../ptmp/firrtl-ingest/F32/native-v17/tests/test.log)
联合 **13/13，0.64 s**。安装并冻结 `package-v9/` 完成，实际
`capture-smoke-v9/grh` 和 `comparison-smoke-v9` 已正常结束：五界两端仍
14/14/14/17/16，P3/P4 各两条 resolved state_update、条件 transfer 各四项
通过；跨 child 的两条冗余依赖消失。剩余 dependency 差异只有 GSIM
clock→CURRENT：P0–P2 各一条，P3/P4 各两条。

该 clock 差异由真实模型明确解释：GSIM CURRENT 自带 clockId，GRH CURRENT
只含 declaration/read，clock 位于 NEXT writer 的真实 clock slot，经同范围
state_update 连接 CURRENT；P0 已是如此，拆分只传播到两个 child。
这里记录转换合同的继承传播，不补造 CURRENT operand，不修改 ingest；完整
初始化/四态状态行为及 U2 五项 membership 仍未证，reader 差异行原样保留。

完整 `capture-v6/grh/` 已用 package-v9 在没有生产库存比较并发的条件下启动，
守卫仍为 RSS 144 GiB、PSI 25% 持续 8 s。当前正在捕获，尚不能代替已完成
的 v4 数据；结束后须重新审计 P0。

### 9.18 查询计划第二次修正与有限重建证明

旧 `comparison-v2` 已停止（session exit 130），`inventory_complete=false`，
无最终 summary，不具备 resume/seed 资格。该决定依据新的确切 SQL 计划：
`unique_names` 的 CTAS `min(id)` 缺 INTEGER affinity，su/tu 索引只命中
engine/stage；另一个 missing-name slice LEFT JOIN 也只按 stage 查找。
小图上的完整 SQL、现有/候选 EXPLAIN 和结果集合等价证据见
[审查报告](../../ptmp/firrtl-ingest/F32/reader-derive-audit/report.md)。

reader 仅将 unique_names 改为显式类型表再 INSERT，并为 canonical_slices
增加六字段 native identity 索引。Node 转换、配对及证明策略不变。
正式回归加实际 GSIM 集成 **72/72、零 skip**，见
[reader-index-v7-native](../../ptmp/firrtl-ingest/F32/reader-index-v7-native/tool-tests/semantics-contract.log)。
新 SHA-256 为 `564c8a57e290372bf30d72c497b8fba52d52103b0ed00d40129c5742ae978f95`。
待新完整捕获完成后在新目录比较，不对旧不完整库改索引或伪装为 checkpoint。
P0/P1/P2 旧原生结构索引仍是独立已完成产物；能否复用取决于新旧原生 JSON
的完整 hash，不因 Node 数一致直接复用。

另新增[独立有限重建证明器](#f32-reconstruction-certificates)，不调用或
修改 reader/normalizer。它按真实 boundary op/slot、稳定 SemanticId 和已存
pair 验证 unsigned128 高/低源、256-bit SHL/OR/Concat 及 Eq 的类型和身份，
逐位验证重建后用 Eq congruence 证明当前 anchor 表达式。
**41/41** 正反测试与独立复跑通过；两个 closed-v8 实际小图共 **6/6**
证书成功、零失败，原 comparison 的全部 38 文件 hash/清单未变。

证书的明确前提是配对 H/L/C 边界的当前值相等且每位为定义明确的 0/1。
它不证明 producer、pass 前后保持、原始 source binding、完整 Node、FourState
或初始化，不能关闭窗口或整图 gate；原 reader 六项 unverified 保持不变。
F32.5 继续，F32.6–F32.7 未启动。

### 9.19 数组独立 owner、producer SPACE 与 package-v10

数组分支曾在已分离 A/B 原生 source witness 后，仍使用全部物理 users
求 demandedRanges；B 的动态读取因此阻止 A 的静态投影。新的完整 source
小例在修前失败：两个有独立身份的 A child 共用同一 payload，B 保留动态读。
修复只将需求输入改为实际 selected users。`native-v18` **13/13，0.72 s**，
覆盖 A 两 child 独立槽及 public connections、B 原 source、不经猜测的 P4
身份和 X/Z payload；未改 scalar 收益策略。

另确认 producer `!direct` 推导中，不支持的 kind 最终必然返回无 references
的 SPACE，却仍先遍历所有输入。新增确定性工作量回归的 cut/source/oracle
均通过，修前访问数为 2053；严格限定的提前 SPACE 后为 **1**，direct 引用
传播、切点和实际表达式不变。`native-v19` **13/13，0.63 s**。逻辑证据在
`review/producer-space-before.md`，不把小图访问量当作全图耗时或正式性能样本。

冻结 `package-v9` 的完整 v6 在 SplitNodes 超过 699 s 尚未返回；因上述已证
冗余且新源码已修复，主动中断 session（exit 130）。P0–P2 有闭合数据，
P3/P4 没有；host 进程核查确认 capture/guard 已退出。中断未让 supervisor
完成 finally，其原 summary/guard 仍为 running，保留不改写；另有
[operator-stop 记录](../../ptmp/firrtl-ingest/F32/capture-v6/operator-stop.md)。
该目录不可被当作完整、可恢复或可作 cache-release 输入的捕获。

安装并冻结 `package-v10/` 已完成，使用它的完整 `capture-v7/grh/` 已在新目录
单独启动。当前尚无新的完整双端数据，也没有生产 comparison 正在运行。

数组支持复核另明确：动态写在已知静态输出坐标上已通过完整宽度 index
Eq/And/四态有序 Mux 实质投影；动态读/whole consumer 的保留是当前算法边界，
不能笼统归因于“共享语义必须保留”。scalar B/C/delta 当前不作用数组，
不能据此声称数组成本已与 GSIM 对齐。实际 FIRRTL 的具名 shaped Assign
包装内部更新时还可能被候选 gate 跳过。详细矩阵和现有证据见
[数组审查](../../ptmp/firrtl-ingest/F32/review/comb-array-update-support.md)；
正在针对两个真实输入补双端 P0–P4 小图，**F32.4 的数组闭环仍待完成**，
不以手工 GSIM-shaped reader fixture 代替实际参考端 pass。

`index_f32_structure` 现支持很窄的 P0–P2 `--reuse-from`，在新旧原生 JSON
完整 SHA/bytes 一致、精确 schema、三张派生表为空且闭合无 sidecar 时，
copy/reflink 到独立 inode，校验源不变及复制 hash 后最后发布新 marker。
本地与独立 **28/28**，小图 resume 结果与 fresh 相同；未操作生产数据库。
它沿用历史 builder cache 信任，不声称重证全部原始索引行；合同见
[结构复用说明](#f32-structure-reuse)。完整输入是否可复用仍待实测。

F32.1–F32.5 继续实施，F32.6–F32.7 未启动，未提交。

### 9.20 实际数组双端结果与 v7 资源失败

`array-native-probes-v10/` 已对 `f32-pipeline.fir` 和
`f31-pruned-named-array-update.fir` 的原文件做四次捕获、两次比较，全部通过
Make 正常结束。现有 GSIM 直接接受原 FIRRTL 6/public/connect，无须转换输入；
每对输入 SHA 一致。pipeline 两端各界均 10 Nodes，pruned 均 6。
原生 IDs、真实 op/slot、赋值顺序与未证项见
[实际数组报告](../../ptmp/firrtl-ingest/F32/array-native-probes-v10/README.md)。

两例的 GRH P2 均为 shaped Assign 包内部非 anchor 的 CombArrayUpdate，
P3 保持不变；GSIM 的对应数组也保持原形。GSIM 对数组引用及数组/多赋值
producer component 返回 SPACE，故不能照搬 packed scalar 的 B/C/delta
去宣称数组应该拆分。当前 GRH 实际 shaped Assign 的投影触达和策略仍需
明确闭环，未据此盲目扩大拆分。

pipeline 已复现一项真正新 P2 差距：GSIM bank 的 leaf width 从 8 变为 3，
shape 仍为 [4]；GRH 仍保留 leaf8。原因已定位为 UsedBits 虽有区域需求，
却只为 scalar prefix 提供 materialization，shaped Assign/CombArrayUpdate
缺少逐 cell 的叶位缩宽。正在补最小反例与窗口修复；不能把 packed32 简单
截成12，原 cell1 的 bit8 必须重排到新 bit3，原索引仍须保留完整宽度。
原 sourceWidth8/shape 与新的 sourceBitWidth3 也须分别维护。

两例全数组值在 P0 已含第一次 DCE 的 unused cell 裁剪差异；其新窗口证明
应关注真实读取的投影，不假设未观察 cell 相等，也不擅修该前驱。pipeline
selected 只读 bank[1][2:0]，pruned out 只读 staging[1]。这些 P0 项和新 P2
缩宽缺口分开登记。

完整 `capture-v7/grh` 在 hier-flatten 被 PSI 守卫正常终止，Make exit2、
child -15，reason=cgroup_pressure；some avg10=50.41%，持续 8.0268 s。
最后 RSS/HWM=83,337,252,864 bytes（约77.62 GiB），进程 Swap0，尚无 P0。
捕获 scope 的 OOM/high/max 事件计数均为0；未进入 F32 窗口，不记为窗口语义失败。
停止后 cgroup file cache 约75.0GB。针对已停止任务的明确文件集合，通过
本地 Make 对62个文件、合计390,733,844,161 bytes做 POSIX_FADV_DONTNEED
（含fdatasync），零错误；这不是删除，也不表示释放了同等大小的常驻内存。
service memory.current 从约79.9GB降至56.9GB，PSI avg10回落0。
记录在 `closed-cache-advice/receipt.json`。没有修改守卫阈值或系统参数。

目前无生产全图或库存比较运行。先完成数组缩宽的小图修复/回归，再冻结新包
并串行重捕获，避免重跑尚有已知窗口差距的版本。F32.4/F32.5 仍未完成；
正式 F32.6 与收尾 F32.7 未启动。

### 9.21 暂停时的最新停点（2026-11-17）

用户已暂停 F32 实施。以下状态补齐暂停前最后一批尚未写入 §9.20 的工作；
此次文档合并未恢复实现、构建、测试、捕获或性能验收。

- **最新冻结版本仍为 package-v10**，对应 native-v19 联合 13/13。
  它不包含下述新 UsedBits 修改。
- **UsedBits 数组逐 cell 叶位缩宽已经写入源码**，覆盖 Constant、Assign、Mux、
  ArrayCreate、CombArrayUpdate 和 SliceArray 的物化及 binding sourceBitWidth；
  原索引保留完整宽度。真实 pipeline 的 bank 现可从 leaf8 缩至 leaf3。
  修前 `native-v20-before-fixed` 按预期失败，修后
  [native-v20-first](../../ptmp/firrtl-ingest/F32/native-v20-first/tests/test.log)
  的 UsedBits + pipeline **2/2 通过**。
- **这批修改尚未完成验收**：最终 13 项联合回归未运行；大 shape 的物化规模限制、
  巨大 shape 负例和 IR 增长记录未完成，当前仍逐 cell 枚举；signed packed
  扩展专项回归未验证。尚未安装、冻结或做完整重捕获。
- **named-array wrapper 四组专项测试已写入源码，但未构建或运行**。
  覆盖 static-only / mixed whole+dynamic 用户、完整原生来源、身份与槽位，
  unknown 控制、X/Z 及 P4 可观察行为；不能计为已通过。
- **实际保留 shaped Assign 的结论已修正**：双端真实 P2→P3 均保留数组，
  现有证据未发现该选择造成结果、身份或引用错误。它是优化策略边界，不能仅因
  未触发 direct-update 投影就定为语义支持缺口；动态写本身也不是保留理由。
  direct CombArrayUpdate 的静态投影已有实质支持，稳定 typed array Node
  仍须维护真实用户和有序更新语义。新增 wrapper 测试用于核实这项合同。
- **有限重建证明器兼容性回归已更新为 45/45、零 skip**，只明确接受两个完整
  四文件 reader/dependency 身份组；旧六项证书原字节不变。具体合同见
  [§13](#f32-reconstruction-certificates)，未据此升级任何完整语义门。
- **最新已完成的生产双端五界捕获仍是 v4**。v5/v7 因前驱 PSI 守卫失败，
  v6 主动中断，comparison-v2 不完整且不能 resume/seed。
  尚无当前修复版本的整图语义结论，正式 F32.6 和收尾 F32.7 未启动。

暂停交接时确认没有后台 Make、生产捕获或比较任务；未提交。恢复实施须从上面的
未验收修改与回归继续，不能将 native-v19 的通过结果套用到当前新增源码。

### 9.22 恢复实施、数组回归与 package-v11（2026-11-17）

用户重新要求实施 F32.0–F32.5，恢复 §9.21 的未验收工作；前驱审核规则、
原始输入与四 pass 窗口不变，F32.6–F32.7 仍未启动。

- 当前新增数组缩宽及 named-array wrapper 测试已完成联合回归：
  [native-v20-resumed](../../ptmp/firrtl-ingest/F32/native-v20-resumed/tests/test.log)
  **13/13**，此前未运行的 wrapper 四组测试现已实际执行。
- UsedBits 的 `resizeCells` 增加等宽、相同 cell stride 的类型视图快速路径：
  保持 packed 位图，只生成 typed Assign，避免 signedness 或 scalar/array
  view 不同却为每个 cell 生成 SliceStatic。新增 **65,536 cells** 回归，
  用独立标量的真实缩宽触发 reconstruction，检查数组保持 leaf8/shape[65536]，
  并约束新增 op 不超过8；分别在无树及有树下验证身份、binding 和 verifier。
  该检查覆盖类型视图路径，不声称实际改变 leaf stride 的巨大数组已完成规模验收。
- 新增合法等宽 signed packed→array 重排的前后四态 oracle 对照，覆盖正数、
  负数位图与跨 cell 位。最初试写的 10→16 Assign 不符合等宽契约，已改为
  合法 16→16 view；该试验失败不作为生产缺陷。真正的 signed 扩展专项及
  实际 leaf stride 改变时的大 shape 上界仍待补齐。
- 最终源码联合回归
  [native-v22-view-fastpath](../../ptmp/firrtl-ingest/F32/native-v22-view-fastpath/tests/test.log)
  **13/13**。通过 `make py_install` 安装后用 `make snapshot_f30_package`
  冻结 [package-v11](../../ptmp/firrtl-ingest/F32/package-v11/identity.json)，
  source content SHA256 为 `b783f63775a7e2c7fd346f649a0c5829f386a45077dd3f7df5b8e410e439254b`。
- `array-native-probes-v11/` 使用两个原始 tracked FIRRTL 文件和同一 manifest，
  四次双端原生捕获均 completed，两次比较均 analyzed。pipeline 各界 10/10 Nodes，
  pruned 各界 6/6；两例 P0–P4 的 physical geometry 均全部对应，
  **pipeline bank 的 P2 leaf8→leaf3 新差距已消除**。P1–P4 的 first_seen_here
  均为0。pipeline 仍有2项结构差异，pruned 仍有3项连接和2项结构差异，
  均已在 P0 出现；这不证明其传播已完全验收。
  [pipeline 比较](../../ptmp/firrtl-ingest/F32/array-native-probes-v11/pipeline/comparison/summary.json)
  和 [pruned 比较](../../ptmp/firrtl-ingest/F32/array-native-probes-v11/pruned/comparison/summary.json)
  的严格 `semantic_acceptance` 仍为 **false**，未验证的 membership/anchor、
  四态及前驱来源项照常保留，未放宽比较门。
- 已启动 package-v11 的完整 `capture-v8/grh`，沿用默认 RSS/PSI 资源守卫、
  无 trace、P4 后停止。尚无本轮完整生产捕获或语义结论，后续须检查实际进程
  和 summary，再决定继续等待或处理终态；不能把小图结果外推到完整输入。

F32.0–F32.5 保持进行中，尚未达到 §5 的全部退出条件。

### 9.23 SplitNodes 来源索引与新生产捕获（2026-11-17）

`capture-v8/grh` 的 package-v11 完整输入运行已通过前驱、ExprOpt、UsedBits，
P0–P2 的 `semantic_validate` 全部 valid。其 UsedBits 原生计时为
20.989668897 s（单轮诊断，不是正式性能样本）。随后 SplitNodes 长时间运行，
期间 RSS 约72.7 GB、进程 Swap0、采样 PSI avg10 为0。

静态源码审查发现，`splitExpressions` 的来源选择对每个 user、每个逻辑 alias
重复扫描同一 value 的 boundary rows，并重复执行 owners 线性查找；即使是
无法产生非空内部切片的单比特值也进入规划。已修为局部 target→source 集合索引、
每个真实 user/slot 只求一次 witness、单比特提前返回。来源集合、歧义拒绝、
别名独立规划、greedy cut 规则和真实槽位绑定不变；未改前驱或 DCE。
这证明消除了上述重复扫描，不据此宣称全部 SplitNodes 已达到线性复杂度。

- [native-v23-witness-index](../../ptmp/firrtl-ingest/F32/native-v23-witness-index/tests/test.log)
  联合回归 **13/13**，包含现有 exact alias、原生 forward、双亲重建、同值
  sibling 和静态/动态数组用户的语义及槽位正反例。
- 已安装并冻结 [package-v12](../../ptmp/firrtl-ingest/F32/package-v12/identity.json)，
  source content SHA256 为 `7b5836704636b5c30339535613e2e064ea8c5c55243d3aa58e9c8f93d465f52f`。
  `array-native-probes-v12/` 对两个原文件重新完成四次捕获、两次比较。
  [Make 验证记录](../../ptmp/firrtl-ingest/F32/witness-index-validation/result.log)
  确认 v11/v12 的两例 × 五界 × 四份原生 TSV **40/40 表正文逐字节相同**；
  只排除 session/snapshot 元数据行，不改写生产库存或 proof reason。
- 小图严格 `semantic_acceptance` 继续为 false；pipeline 的
  `new_differences_not_present_at_P0=0` 与
  `new_unproved_node_results_since_P0=3` 同时保留，二者含义不同，
  不能用前者否定新的未证明结果。v11 的独立来源审计亦已运行：pipeline /
  pruned 分别有196 / 133项未闭合 obligation；包含来源、跨端候选、缺少转换
  证书和工具覆盖，不是新错误数。两例 `window_acceptance=false`，
  certificate ingestion 尚未实现；来源关系不被冒充为语义证明。
- 为切换到已验证的来源索引版本，主动中断旧版 `capture-v8` launcher，
  exit130；随后确认 handle 已不存在且资源采样停止。
  [operator-stop 记录](../../ptmp/firrtl-ingest/F32/capture-v8/operator-stop.md)
  保留原因和最后状态。骤停使 summary/guard 的 running marker 未刷新，
  不修改这些原始文件；它们不能证明进程仍在运行，也不构成 completed、
  资源守卫失败或语义失败。v8 缺少 P3/P4，不可作为完整比较或 seed 来源。
- 最新 package-v12 的完整 **`capture-v9/grh` 已启动**，继续使用相同原输入、
  manifest 与默认资源守卫。当前完整生产双端五界证据仍为历史 v4；
  v9 结束后需核查 P0 与 F31 行级一致性，再完成 GSIM 与全图对照。

F32.0–F32.5 继续实施；未验收项仍包括最新整图、逐项窗口转换证明、
真实 leaf-stride 改变的大 shape 规模边界及 signed 扩展专项。
F32.6–F32.7 未启动，未提交。

### 9.24 数组重排修复、规模预算与逐 pass 局部证明（2026-11-17）

本轮重新核实 v9：host `pgrep` 已无捕获/比较进程，原始资源采样只到
SplitNodes，P3/P4 不存在。原 summary/guard 的 running marker 不是活跃句柄；
终止原因与退出码未知，不能据此认定语义失败。原文件未改，补记
[观测记录](../../ptmp/firrtl-ingest/F32/capture-v9/observed-stopped.md)。
已以相同原输入、manifest、冻结 package-v12 和默认守卫另开
`capture-v10/grh`，P0–P2 semantic validation 均 valid，目前仍在 SplitNodes；
尚无本轮完整五界结论。只读调用栈采样因 ptrace 限制未成功，未修改系统配置。

**UsedBits 的真实数组重排缺陷已修复**：原 `[2]`/leaf8 到 `[4]`/leaf4 的
等宽 view 只观察 cell2 低位时，前后同时缩宽曾把原 bit8 错放到新 cell1。
现在先恢复输入原 packed 布局，再按输出原 cell 边界投影。双向 reshape、
有/无 SemanticTree 各遍历全部65,536个16-bit输入，并独立核对
`(raw >> 8) & mask`，不只依赖前后使用同一个 oracle。

**规模边界现已实施并验证**：每个 shaped value 的逐 cell 物化预算为65,536。
超预算时在需求传播前保留全叶及相关读取宽度，防止源先缩宽后被迫做巨大重建；
未改变 packed 布局的 type-only view 继续走无逐 cell 展开的路径。
4,097和65,536 cells 的 leaf8→3 均逐坐标核对真实 slice 几何和前后独立预期，
新增 op 分别为4,101和65,540。65,537和100,000,000 cells 保留leaf8，新增0；
巨大未变化 reshape 配合独立标量真实缩宽仅新增1。以上覆盖有/无树、binding、
身份、64-bit索引和 verifier；100M负例不执行巨大位图 oracle。
该预算按值计算，不是全图增长总上限；规模正例只验 UsedBits。
附带大规模 P3/P4 的先前试跑超180s，尚未定位具体 pass，未计为通过。

**signed 扩展专项已通过**：合法显式 Slice-MSB/Replicate/Concat 的10→16扩展，
在P0/P2/P3/P4逐位核对独立模型；定义值覆盖1024个输入×两种selector，
另含X/Z sign、未知selector、跨cell读取和source projection。
本轮还修正test-only四态oracle的逐位Z融合及一位signed比较问题，生产继承
缺陷另列F32-U3，未擅改前驱。

最终 [native-v24 联合回归](../../ptmp/firrtl-ingest/F32/native-v24-budget-reshape/tests/test.log)
**13/13**，成功测试的详细诊断另存
[last-test.log](../../ptmp/firrtl-ingest/F32/native-v24-budget-reshape/tests/last-test.log)。
通过 `make py_install` 安装并由 `make snapshot_f30_package` 冻结
[package-v13](../../ptmp/firrtl-ingest/F32/package-v13/identity.json)，source content SHA256
为 `90753abe7b07e734b70efbfe19b9287400165f470a1d191ca0d547a15abdb820`。
`array-native-probes-v13/` 已用两个原始 tracked 文件完成四次捕获和两次比较；
严格 `semantic_acceptance` 仍为 false，不把局部回归外推为整图通过。

新增的[同端逐 pass anchor 证明器](#f32-pass-anchor-preservation)已通过16项合同，
在原生v12两例中穿透真实formal input到可观察输出；仅证明任意定义0/1输入下的
当前typed anchor保持。pipeline四段分别10/9/10/9项，pruned每段6项；
bank缩宽/死区域删除、完整Node、四态、source binding、state/effect/初始化、
退休与跨端等价仍未证明。工具、来源审计和严格比较门均未放宽，详情见§14。

F32.0–F32.5继续实施；完整最新双端五界、窗口逐项转换证据及来源几何仍未验收。
F32.6–F32.7未启动，未提交。

### 9.25 SplitNodes 再次拆分新 child 的原生失败与身份映射（2026-11-17）

共享宽值的规划还存在按alias重复遍历users/consumer锥的问题，已改为逐user
归类原生witness、按owner索引用户和有对应原生来源行的consumer；单owner
fallback、缺witness全拒绝、多来源局部拒绝与greedy切分规则不变。
128/512 alias及歧义/缺witness正反例检查真实槽位、几何、独立输出及实际工作量
计数。[native-v25](../../ptmp/firrtl-ingest/F32/native-v25-shared-alias-index/tests/test.log)
联合 **13/13**。已安装并冻结
[package-v14](../../ptmp/firrtl-ingest/F32/package-v14/identity.json)，source content SHA256
为 `982189a6af1cea41cf01124f33904d9b1f8b4aef8bd4262b6af6b96092091548`。
两个原始小图完成四次捕获和两次比较，
[正文比较](../../ptmp/firrtl-ingest/F32/alias-index-validation/result.log)证明v13/v14
两例×五界×四表共 **40/40** 正文逐字节相同；严格语义门仍未通过。

准备切换冻结版本时，v10已自行结束，向原supervisor发信号返回“No such process”；
**没有人为中断该次运行**。其
[summary](../../ptmp/firrtl-ingest/F32/capture-v10/grh/summary.json) 为failed，
[guard](../../ptmp/firrtl-ingest/F32/capture-v10/grh/guard.json)为child_exit/returncode1，
SplitNodes报 `Semantic boundary refers to an invalid Node`。
原生timer1398.708189694s、complete=false，不是有效性能样本。
失败后物理图已保存，不能作为P3；P3/P4缺失。
[prefix audit](../../ptmp/firrtl-ingest/F32/capture-v10/prefix-audit.json)确认完整P0的
Node/connection表正文与F31 v51逐字节相同；只证明静态起点未变。

该失败已在11-op最小例中精确复现：非拓扑Concat把一个新child整宽转发到
原有producer的Value，随后遍历原producer时，又把这个新child作为parent拆分。
收尾退休父集合后，外层split仍引用已退休的child。
[修前实际失败](../../ptmp/firrtl-ingest/F32/invalid-node-before-v2/split-nodes/tests/test.log)
明确给出phase=finish-child-source、source=outer$127_0/live=false及真实user/slot。
正在修复新身份的owner级规划边界，并补原alias和state-forward的依赖运输回归；
不能只删除非法边或仅检查child存在。当前不启动有此已知错误的下一次完整捕获。

同时补齐原生物理ID到JSON局部ID的可选映射。JSON writer会重新稠密编号，
直接以端点物理index连接JSON anchor不成立；此前无map的synthetic保留投影
正例不足以证明绑定身份，已在§14.4收紧并更正。新producer和StoreJson共用
遍历编号，默认不导map；显式导出时冻结图/会话/边界及index/generation，
verifier核对实际anchor和defining op。当前native专项 **2/2**、capture合同
**19/19**、局部proof合同 **21/21**；新包实际mapped捕获尚待安装后验证。
这些局部合同不代表完整Node、FourState、状态效果或窗口语义已通过。

F32.0–F32.5继续实施；当前没有生产捕获/比较进程，F32.6–F32.7未启动。

### 9.26 child 生命周期、部分 X/Z 保留与实际 ID 映射（2026-11-17）

§9.25 的最小生命周期失败已修复。新 child 不进入本轮表达式或 state
current/next 的再拆计划，中央 prepare 入口同时拒绝误重入。整宽投影若借用
仍可能改写的原始 producer/state-read 端点，先创建等宽 typed Assign，再将
同一个值放入 pieces、实际用户槽位和 child anchor；不能在用户改写后才包一层。
wrapper 保留原生 operand origin，收尾按最终真实 reconstruction 槽位运输依赖。
无 SemanticTree 时直接保留原值，不增加身份隔离 helper。

普通 alias 和 state 两个回归均要求原 producer/current/next 仍可拆成64-bit
children，同时新 child 保持128-bit及完整 binding。incoming 精确匹配
`(source,kind,user,slot,value)` 全集；原 data/forward 两种证据各两行均保留。
P3/P4 同时核对 raw outgoing 全集、公开连接和行为。
[定向回归](../../ptmp/firrtl-ingest/F32/invalid-node-after-v7/split-nodes/tests/test.log)
1/1通过，[独立只读审核](../../ptmp/F32/gsim-v4-current-identity-audit/split-forward-review.md)
未发现新增阻断项。完整设计的该失败尚待新捕获确认，不能以最小例代替。

另修复 SplitNodes 两处部分未知值的文本化：constant projection 和 register
member initializer 对含未知位的值使用 Binary，定义值继续使用 Hex。
强制 Hex 曾把 `x01` 等混合位投影中的已知位也变成X。
[修前](../../ptmp/firrtl-ingest/F32/unknown-literals-before/tests/test.log)全部8组失败，
[修后](../../ptmp/firrtl-ingest/F32/unknown-literals-after/tests/test.log)全部通过：
两个混合X/Z pattern × constant/state × 有/无树，在P0/P3/P4逐位检查独立预期；
state 无 writer/clock，避免初始化错误在观察前被覆盖。

[native-v26](../../ptmp/firrtl-ingest/F32/native-v26-lifecycle-unknown-map/tests/test.log)
联合 **15/15**，详细诊断保存在同目录 `last-test.log`。经 `make py_install`
安装并冻结 [package-v15](../../ptmp/firrtl-ingest/F32/package-v15/identity.json)，
source content SHA256：
`f474a013bc5ec41b3c3c0ece90d7e6f103018d2780b206bf85c2f10fbe1f10b9`。
两例原始FIRRTL已完成四次原生捕获、两次比较和两次同端proof；GRH两例的
十个边界均实际导出并冻结 serialization map，当前 verifier 已消费实际映射。
[v14/v15正文比较](../../ptmp/firrtl-ingest/F32/array-native-probes-v15/v14-body-comparison.log)
仍为40/40逐字节相同。§14记录本轮有限anchor结果；投影及严格语义门未通过。

**UsedBits 的数组寄存器缺优化已由双端实际复现，正在修复**：
[depth2 register](../../ptmp/firrtl-ingest/F32/depth2-probes-v14/register/grh-native/summary.json)
在P2中，GSIM current/next从leaf8、shape[2]变为leaf3、shape[2]，GRH的
storage仍为packed16/leaf8（read结果可变3，writer data仍8）。这是F32.3须补齐的
差距，不能归为额外能力。相同流程的
[depth2 memory](../../ptmp/firrtl-ingest/F32/depth2-probes-v14/memory/grh-native/summary.json)
实际两端都保留leaf8，不能仅凭参考源码推断此例有memory缩宽差距。
当前完整GRH重捕等待这项已知窗口差距修复；另在补显式observable边界回归。

完整GSIM v4经[独立身份审计](../../ptmp/F32/gsim-v4-current-identity-audit/report.md)
**89/89**核验通过：当前binary、122个完整源码文件、原始完整输入、20张TSV与
5份完整结构hash全部一致，实际native command及P4停止位置也一致，故可复用
该原生参考捕获，无须重复运行。审计不补造构建来源或语义证书，原external binding
限制仍保留。已安全释放本轮关闭大文件的cache，原始文件全部保留。

U4已在原始ingest和每个prefix复现并登记§10，未恢复旧binding schema、
未应用前驱修复。F32.0–F32.5仍未完成；F32.6–F32.7未启动，未提交。

### 9.27 数组寄存器逐叶缩宽、外部观察与 memory 范围（2026-11-17）

**UsedBits的数组寄存器差距已修复**。需求按原leaf取所有读区域的低位前缀
并迭代传播至writers；indices、enable和events保持完整需求。状态packed总宽
按cells×newLeaf更新，读结果与writer data/mask按原cell stride重排，支持多维
后缀及flat packed payload。constant initializer逐cell截取，Fill只缩其单leaf
值并保留start/count；X/Z写Binary。65,536-cell预算前置保护state，超预算、
array random/readmem及不能如实表达源几何的入口保持保守，未宣称这些缺口已支持。
共享`stateUses`的merger仍明确限制为scalar，避免扩大窗口外合并策略。

legacy RegisterCurrent/Next与operation-only MemoryStorage的原始sourceWidth、
shape、offset不变，保留区间改为每leaf实际前缀；原represented区间不匹配oldLeaf
时不猜测映射。维护仅用线性binding扫描及调用内索引，不按每个state重扫全图。
这些旧binding的维护由手工合法IR回归验证；实际FIRRTL仍缺U4的新树原生源合同。

[数组修前](../../ptmp/firrtl-ingest/F32/array-state-before/tests/test.log)保存了8组缺优化失败；
[专项最终](../../ptmp/firrtl-ingest/F32/array-state-after-v4/tests/test.log)通过新旧UsedBits两目标。
新测试覆盖10组实际缩宽、9组保守边界、8组scalar/array及offset0/4的storage
区间正反例，并按独立逐cell模型核对初始化、动态掩码更新及每位X/Z。
过程中发现P0解释器原掩码位运算会把未写Z变X，已仅修test-only oracle：
依GRH的逐位procedural-if规范，mask1直接写data，mask0/X/Z保留原位；128项
独立四态真值表验证。生产SV emitter的partial-index动态mask分支也有相似位运算，
本轮只有静态代码证据、没有执行复现；它位于窗口外，未修改，不能写成已修生产问题。

[observable专项](../../ptmp/firrtl-ingest/F32/observable-after-v2/tests/test.log)三目标通过。
新回归在P0–P4、有/无树各141样本，以普通双word独立模型核对posedge/negedge、
reset、disabled事件、同拍双事件、状态、DPI held-return及调用顺序/次数。
DPI、display和正式output各有独立128-bit计算链及低3-bit用户，分别验证完整
观察保护；8-bit控制总线先经合法1-bit reduction，检查高位有效控制未被截断。
raw source/op/slot/kind和Clock/Reset binding精确核对，public连接按规范化的
dependency检查。这里只覆盖定义值事件、解释器DPI模型和正式output port，
没有真实FFI、assert/assume/cover或未知事件的完整验收结论。

[native-v27](../../ptmp/firrtl-ingest/F32/native-v27-array-state-observables/tests/test.log)
联合17/17后曾冻结package-v16。其
[实际depth2复核](../../ptmp/firrtl-ingest/F32/depth2-probes-v16/readout.md)确认register
storage16→6、leaf8→3及读写3位，但也发现新规则额外缩窄了memory。
参考`usedBits.cpp`将NODE_READER显式置为全宽sink，因此该memory保持leaf8是
明确策略，不能把意外扩展写成已对齐。现只对canonical `firrtl.memory` 数组声明
排除本次新增缩宽；普通数组寄存器继续缩宽，scalar `firrtl.memoryPipeline`
维持原策略，不靠名字分类。真实FIRRTL的有/无树memory负例
[修前](../../ptmp/firrtl-ingest/F32/memory-policy-before/tests/test.log)均失败，
[修后](../../ptmp/firrtl-ingest/F32/memory-policy-after/tests/test.log)新旧UsedBits及native
pipeline三目标通过，同时断言declaration/read/write/mask/control/index宽度。

[native-v28](../../ptmp/firrtl-ingest/F32/native-v28-register-memory-policy/tests/test.log)
最终联合 **17/17**，详细诊断另存同目录last-test.log。
经Make安装并冻结[package-v17](../../ptmp/firrtl-ingest/F32/package-v17/identity.json)，
source content SHA256：
`589051a7c019fa880e4f166a7056c9c92e319e83b8a95bf5dbacb4bd1924bfed`。
两个原始组合数组小图再次完成四次mapped原生捕获、两次比较和两次有限proof，
[v14/v17正文](../../ptmp/firrtl-ingest/F32/array-native-probes-v17/v14-body-comparison.log)
仍40/40相同；严格门仍false，pipeline相对P0新增unproved仍3。
[depth2-v17原生复核](../../ptmp/firrtl-ingest/F32/depth2-probes-v17/readout.md)已确认：
register storage16→6、indexed read8→3及writer data8→3；memory storage16、
leaf8、实际read8及writer data/mask8均保持。两例五界validation及map完整。
GRH formal data保持8，而GSIM register输入缩3；memory命名reader的GRH纯组合
别名缩3，而GSIM NODE_READER保持8。这些差异均保留在严格比较中，没有改名或
删行消除。register/memory分别35/40个unproved pair，严格门仍false。
实际bank/current-next仍缺原生source记录，unit中的旧binding维护不能补造它们。

完整[capture-v11](../../ptmp/firrtl-ingest/F32/capture-v11/grh/summary.json)使用package-v16，
已被[资源守卫](../../ptmp/firrtl-ingest/F32/capture-v11/grh/guard.json)在hier-flatten
停止，**没有P0**；reason=cgroup_pressure、returncode=-15。限制为RSS144GiB、
PSI25%持续8s；触发采样RSS84,392,976,384 bytes、cgroup file63,840,219,136 bytes、
PSI some avg10=41.16。这是资源失败，不能归为pass语义错误或有效性能样本。
原始文件均保留；下一次完整捕获先复核并释放已关闭artifact的cache，资源守卫不关闭。

当前仍无最新完整GRH五界验收，双端全图库存、逐项新增差异及语义证据继续实施。
F32.0–F32.5未完成，F32.6–F32.7未启动，未提交。

### 9.28 关闭缓存审计与 v17 完整重捕获（2026-11-17）

[宿主资源审计](../../ptmp/firrtl-ingest/F32/resource-audit-v11/report.md)确认
v11的supervisor与benchmark均已退出，无旧F32捕获、比较、索引或seed进程；
scope及相关祖先当前`memory.high/max=max`，没有当前有限high/hard限制。
这不能反推失败瞬间的配置，也不能把祖先累计OOM计数归因于v11。

通过已有`make release_f32_cache`，对12个summary/guard均已终结的capture根
中151个闭合文件发出POSIX_FADV_DONTNEED，零错误。提示范围为
412,196,270,571 bytes，**不是实测释放量**；scope文件缓存实测约64.00→20.21 GB，
最终PSI avg10/60为0，宿主MemAvailable约177.7 GiB。全部文件保留。
stale v6/v8/v9及旧比较库的额外范围在preflight停止：部分`/proc/fd`权限不足，
无法完成更严格的closed-file检查；未对额外范围发提示，未改原始状态、WAL或权限。
这是内核进程可见性限制，不是automatic approval review拒绝。

已使用冻结[package-v17](../../ptmp/firrtl-ingest/F32/package-v17/identity.json)
完成新的完整`capture-v12/grh`，沿用原始输入和manifest，无trace，默认
RSS96GiB、PSI25%持续8s、每边界闭合cache释放。
[summary](../../ptmp/firrtl-ingest/F32/capture-v12/grh/summary.json)与
[guard](../../ptmp/firrtl-ingest/F32/capture-v12/grh/guard.json)均completed，
returncode0；同一原生run的五个独立snapshot及全部artifact hash已冻结。
实际pass_calls仅含五个prefix及四个窗口pass，最后为`dead-code-elim#1`，
之后仅P4验证/导出及文件校验，没有执行后续pass。
P0–P4的`semantic_validate.valid=true`，Node数依次为
**5,635,937 / 5,635,937 / 5,635,937 / 5,647,421 / 5,625,865**。
此前v10的invalid Node故障在本次完整SplitNodes与P3/P4验证中未再出现。
[prefix审计](../../ptmp/firrtl-ingest/F32/capture-v12/prefix-audit.json)确认P0
Node/connection表正文与F31 v51逐字节相同；这是静态起点保持，不是功能证明。
四个pass原生complete=true诊断计时分别9.363/21.469/1284.312/27.817s，
全捕获1822.157s、最大RSS80,581,956KiB；不属于F32.6正式性能验收。

完整GSIM v4的[当前身份审计](../../ptmp/F32/gsim-v4-current-identity-audit/report.md)
89/89通过，可复用其原始捕获。历史comparison-v1/v2均为未完成inventory、
无完整summary且保留WAL，reader身份亦旧，**包括GSIM分区在内均不能seed**；
不得删除sidecar或补写seal绕过。已在新的
`comparison-v3/`重新建立十界库存，目前仍在读入，尚无完整checkpoint或summary。
旧P0/P1结构索引的[只读预审](../../ptmp/firrtl-ingest/F32/resource-audit-v11/structure-reuse-readiness.md)
已确认目录闭合、当前14表schema匹配、三张派生表为空，前后file stamp不变；
随后现有严格helper已实际完成P0/P1全文hash/bytes、schema/空表及独立inode复制，
receipt保存在[新P0](../../ptmp/firrtl-ingest/F32/comparison-v3/structure/P0/reuse.json)和
[新P1](../../ptmp/firrtl-ingest/F32/comparison-v3/structure/P1/reuse.json)。
source与copy全文hash分别为P0 `503505de6bb93288029db5b7a3e1801e19cf3f639a7cec3a37cfd80db5b7ac2f`、
P1 `f88db69fce395622dc8fff074a9f029f79331a2ec173d8e319e36c59cffd3610`；
原库身份前后不变，只复用无proof的原生索引，全部配对/证明仍须重算。

[退出项复核](../../ptmp/firrtl-ingest/F32/v17-depth2-endpoint-identity-audit/exit-gaps.md)
区分了U4已复现的原生数据合同缺口、有限proof工具/证书接入范围和待完成全图证据。
独立map审计的5194项机械检查不提升为行为或完整Node证书；当前生产source
geometry分支仍在candidate门前拒绝，strict门保持false。
[SplitNodes静态规模审查](../../ptmp/firrtl-ingest/F32/split-scaling-v17-review.md)
另发现逐helper扫描Node成员、逐用户查原projection及逐投影扫描全部pieces的
潜在平方路径；尚未定位历史180s超时，也未据此修改冻结源码。
现有65,536-cell规模正例实际只运行UsedBits与verify，P3/P4集成不能算通过。

为隔离这项集成缺口，使用冻结v17包完成[局部JSON诊断](../../ptmp/firrtl-ingest/F32/large-pipeline-v17/report.md)：
17/65/257 cells、有/无树共6/6，分别运行UsedBits、SplitNodes、第二DCE；
24个保存边界均通过native graph/semantic验证，5个定义输入×3个output×24界的
360项独立`raw & 7`预期检查通过。逐pass日志、原fixture及快照保留。
这是合成JSON局部诊断，不是raw-FIRRTL权威P0，也未补旧binding；不证明source、
完整Node或X/Z，不构成F32.6。随后独立run-v2的4,097 cells有/无树及65,536 cells
有树均完成P4；**65,536 cells无树在SplitNodes内180s超时**，无P3/P4，
保留部分summary及stage日志，不能算通过或行为反例。正在定位此实际规模缺口，
历史C++超时没有逐pass日志，仍不能与本次自动等同。

[cast/零宽原生专项](../../ptmp/firrtl-ingest/F32/cast-zero-v17/report.md)两组合法
FIRRTL均完成双端五界。定义输入穷举144组、P0/P1两端6208项独立预期输出全通过；
3104项跨端及3104项同端P0→P1比较复用相同向量，不重复计为独立样本。
GRH恰3个相同臂Mux改Assign、2个不同臂保留，Node/member/anchor及原生map身份不变，
没有隐式DCE。零宽值在direct ingest已消除，GSIM P1对4个width0 Node写OP_INT(0)，
这是实际规范化差异，未放宽gate。50条端点的物理join通过而source仍unknown；
不证明X/Z、state/effects、完整Node或全图语义。

F32.0–F32.5继续实施，最新完整GRH五界现已取得，全图语义验收仍未完成。
U1–U4均未获批准、未应用；F32.6–F32.7未启动，未提交。

### 9.29 SplitNodes lookup 修复、完整规模闭环与 package-v18（2026-11-17）

针对§9.28的实际无树规模缺口，[独立源码复核](../../ptmp/firrtl-ingest/F32/large-pipeline-v17/independent-hotspot-review.md)
确认匿名图中每个3-bit helper查询同一个N槽Concat时，旧direct component路径会
反复展开并过滤全部N个operand。该静态N×N路径不是旧180s超时的完整profile归因。
窗口内修复只改SplitNodes：无树、单source、当前Concat且单result时直接按真实
`valueUsers`逐operand槽加入全宽reference，保持重复槽计数；保存原projection
operation集合替代逐user线性查找；对按源坐标升序且不重叠的assembly pieces用
`lower_bound`定位相交区间，保留原有gap检查、拼接顺序及来源记录。
没有修改前驱、greedy切分策略、新树source合同或strict gate。
[已应用补丁审查](../../ptmp/firrtl-ingest/F32/large-pipeline-v17/applied-lookup-review.md)
逐项检查实时use-list、重复槽位、全部assemble调用及state/reconstruction顺序，
未发现具体回归；此项是只读源码审查，不独立构成运行证明。

原C++ `largeArrayLeafStride`现将4,097和65,536 cells有/无树正例真正推进至
SplitNodes和第二DCE，每步打印flushed进度，验证图/新树闭合、独立`raw & 7`
输出及既有legacy binding维护。65,537和100,000,000 cells仍只检查UsedBits
预算拒绝，未声称完成后续规模集成。新增四组匿名Concat重复source用例
`(copies,consumers)=(1,1),(4,1),(1,4),(2,2)`，分别检查真实槽计数敏感的切分
结果及行为。经既有Make入口，
[SplitNodes专项](../../ptmp/firrtl-ingest/F32/lookup-fix-v1/split-nodes/tests/test.log)通过；
[native-v29联合回归](../../ptmp/firrtl-ingest/F32/native-v29-split-lookups/tests/test.log)
**17/17通过，26.64s**，其中SplitNodes 25.04s。

已由`make py_install`安装并冻结
[package-v18](../../ptmp/firrtl-ingest/F32/package-v18/identity.json)。source content为
`79d404c1f27b8df1cbf2d16ba6b89a689aaa8f256c12386c652c27210136f37d`，
native core为`a90e6db6e0baa013652f78fc6b99a9067efb7c8445acabe29c03294f064293fd`；
dependency content仍为`c2b75c632ae6acd7b21a19660a718d8f989c54b84b3a96a2917d5504623cbcc7`。
v17包、capture-v12、比较和旧超时证据均保留原身份，没有将其改称v18结果。

用同一未修改JSON诊断及逐字节相同输入完成
[v18局部重放](../../ptmp/firrtl-ingest/F32/large-pipeline-v18/report.md)：
17/65/257/4,097/65,536 cells有/无树共**10/10完成P4**，40个保存边界全部
通过ordinary graph及semantic验证、600项独立定义值输出检查、139,944项逐cell
P2原stride8→leaf3几何检查。65,536无树的SplitNodes原生call本次0.430s，
有树19.491s；它们是与inventory I/O并行的单次诊断，不能计算严格加速比、
拆分三处修改各自贡献或作为F32.6验收。无树P3/P4的135,182/21 ops已实际取得；
有树为139,279/23 ops。合成JSON没有旧binding；原C++联合回归另行覆盖该项。
两种证据都不证明raw-FIRRTL全图、完整Node/source或X/Z行为。

当前包的[两例原始FIRRTL mapped小捕获](../../ptmp/firrtl-ingest/F32/array-native-probes-v18/report.md)
已完成双端五界、严格比较及同端有限证明，4次capture child均return0，10次GRH
semantic验证通过。[独立机械检查](../../ptmp/firrtl-ingest/F32/array-native-probes-v18/audit.json)
1,759项通过，40/40原生表体、10/10 map表体及10/10完整JSON与v17逐字节相同。
同端anchor证明62通过/2未证，0反例证书；跨端80对完整语义仍未证，80条端点
仍为candidate/source_width=-1。pipeline的3项相对P0新增unproved结果为同一个
sameArms在P1/P2/P3的membership理由，未升级为反例；pruned该项为0。
单独的source、FourState、state/effects、退休及完整Node门均保持false。
[sameArms逐物理槽诊断](../../ptmp/firrtl-ingest/F32/v18-expropt-membership/report.md)
另通过342项独立检查：新增uncovered member仅为native op(2,0)的匿名纯Not，
其result(12,0)在P1–P3无user/anchor/formal绑定，P4随显式DCE删除。
Mux实际条件/废弃arm槽及活动依赖在P1已更新，named Node/anchor保留；
raw无slot的旧来源记录仍存在，但没有被导为活动连接。此项符合§3保留待DCE
物理行的合同，与U2的P0无关owner不同，未建立维护反例。原strict未证结果、
完整Node及FourState限制保持，不靠提前清扫membership使reader转绿。

当前冻结包的新原始全图捕获
[capture-v13/grh](../../ptmp/firrtl-ingest/F32/capture-v13/grh/guard.json)
沿用原输入/manifest、无trace、默认RSS96GiB及PSI25%持续8s守卫，
在`hier-flatten#0`因`cgroup_pressure`停止：some/full avg10为31.82%，持续8.023s，
child returncode=-15。最后采样RSS81,024,131,072 bytes，低于RSS阈值；
不能将cgroup文件缓存压力等同于该进程RSS。没有P0或窗口pass结果，不是语义反例。
它与comparison-v3的派生I/O并行；并行事实不构成压力单因归因。
失败summary、guard、资源样本与日志保留，待比较结束后串行重试，未放宽守卫。
不能把v17完整五界或局部重放代作v18全图结果。
`comparison-v3`现已完成v17双端十界库存及派生台账，详见下表。
[一次只读schema诊断](../../ptmp/firrtl-ingest/F32/comparison-v3-monitor/report.md)
于15:19核对到`derive()`的`types_identity`已存在，而末尾两个difference索引尚未
可见，进度只能定位到其间的canonical-edge/差异派生范围，不能确定当前语句。
仅以normal live-WAL只读连接读取schema并立即关闭，没有查询inventory数据、
checkpoint或处理sidecar；TEMP表属于writer，外部看不到不代表未创建。
空内存schema的EXPLAIN显示canonical-edge的五路连接与DISTINCT临时B-tree，
这是可能成本依据，不是实际运行profile或死锁判断；reader冻结身份保持不变。
随后writer继续CPU/I/O推进；15:33发布`inventory_complete=true`，15:37完成
[summary](../../ptmp/firrtl-ingest/F32/comparison-v3/summary.json)和完整difference台账，
进程退出并关闭WAL/SHM。整个inventory-only比较5423.038s，`status=analyzed,complete=true`。

| 边界 | GRH Node | GSIM Node | 唯一同名候选 | 占GRH | type差异 | split_geometry差异 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| P0 | 5,635,937 | 6,020,694 | 5,617,898 | 99.679929% | 26,968 | 0 |
| P1 | 5,635,937 | 6,020,694 | 5,617,898 | 99.679929% | 26,968 | 0 |
| P2 | 5,635,937 | 6,020,694 | 5,617,898 | 99.679929% | 51,807 | 0 |
| P3 | 5,647,421 | 6,043,532 | 5,627,151 | 99.641075% | 51,474 | 15,833 |
| P4 | 5,625,865 | 5,922,045 | 5,604,031 | 99.611900% | 46,062 | 15,833 |

相对P0新增difference记录为971,121个**边界行次**，不能视为等量独立根因或行为
反例。五界合计2,039,004个未配对Node行次、29,165,282条不完整source端点；
仍有28,084,876对未做结构证明，`full_native_structure_compared=false`。
本次`new_unproved_node_results_since_P0=0`只是未请求structure的结果，绝不表示
新增语义问题为0；strict `semantic_acceptance=false`。P0候选数与F31最终一致，
不把同名比例或库存闭合当作功能证明。接下来对有索引的新增类型/几何/连接差异
做有限抽样定位；完整台账保留，不修改或解释掉原始计数。

[已完成的有界台账审阅](../../ptmp/firrtl-ingest/F32/comparison-v3-triage/report.md)
以immutable只读连接保存48个边界实例（24个不同category/key）及35个名称的
实际类型/端点历史；SQL、EXPLAIN和逐query预算在
[triage.json](../../ptmp/firrtl-ingest/F32/comparison-v3-triage/triage.json)。
使用stage/key/name/primary索引定位，没有读全量JSON或ledger、hash/copy大库。
21次selection触及预算而中断，不能据空样本断言没有新增项。数据库前后
size/mtime/inode/device不变，未生成sidecar；这是v17诊断，尚非v18结果。

优先线索有：P1 `d_last_beats1_opdata→d_last_beats1`在GRH失去依赖而GSIM保留，
需确认真实Assign RHS；P2 `t1_train_r...rasAction$NEXT_0`与输出元素新增共享
Concat/Assign的数组及scalar候选，reader因物理类型不唯一而未证，须检查真实
状态/operand及逐cell重组；P2三个`aw_bits_T_21/22/23`在GRH保持48而GSIM缩为43，
需核对消费者；P3 `fuType_0`新child传播P0已存在的alias-source歧义，不能按新key
数重复记成新根因。`indexedLSTable.out_plaInput`的7-bit父变为3+4-bit子以及
另一端退休父名，说明新增presence/connection可能源于表示变化，但仍缺重建值
证明。本次没有建立行为反例或把任何项按名称解释掉。

上述P1三项已进一步作[实际局部锥检查](../../ptmp/firrtl-ingest/F32/p1-actual-cone/report.md)：
仅经闭合P0/P1结构索引的Node→真实serialized anchor/member及producer索引定位，
marker与冻结capture的完整JSON身份一致，未将物理ID猜作serialized ID。
三者P0实际Mux的两个1-bit臂均为`1'b0`，P1实际anchor经Assign链到0，
故选择器0/1/X/Z共12个局部情况均保持0，支持GRH消除该选择器依赖。
GSIM两界仍保留Mux，真臂引用的width0在P0已存在；其规范化/扩展合同和跨端
值证明未由本检查建立。原strict标记不变，也不将有限局部结果等同完整Node。

另完成当前v18包的[合成缩宽family](../../ptmp/firrtl-ingest/F32/window-triage-probes-v1/report.md)：
两组原始FIRRTL为48→43及4→3位，七个独立`not(a)`中间值分别经Assign/Not/
And/Mux/Add/Sub/Mul使用，双端四次捕获均完成P0–P4。普通逻辑均缩宽，算术上游
GRH保持48/4、GSIM缩为43/3，与GRH FourState算术保守full-demand路径一致。
actual map/operand槽及170端点机械关联、140位宽断言通过；独立stdlib oracle
穷尽小例512向量并检查大例72向量，两端五界40,880项预期输出全通过。
110项冻结artifact校验和10次GRH验证通过；跨端20,440与同端32,704次比较复用
相同输入，不增加独立样本数。此例没有取出生产aw节点的真实消费者，**不能据此
把E001–E003标为已解释**；170端点仍为candidate，未证明源/XZ/state/fullNode。
随后[实际aw局部锥](../../ptmp/firrtl-ingest/F32/aw-actual-cone/report.md)经已闭合
P2索引的小型查询取得Mux/Or/Assign与shape[1]读取，即时依赖为
`T_21/T_22→T_23→WIRE.addr`。继续沿12个具名routing步骤查到48-bit地址hold
寄存器，以及`ram._wIdx_T`的49-bit FourState Sub→low43 SliceStatic；GSIM
对应候选Sub和hold均为43-bit。745次有界索引query未触预算、未扫全图，实际
operand槽将该保守算术需求路径与原aw值连上。它支持真实保留宽度的解释，但
未重放全部UsedBits需求决策、排除其他完整物理users或证明跨端行为，仍不把
三项升级为完整已解释语义差异。

比较结束后已启动独立输出`capture-v14/grh`，仍使用package-v18、同原始输入与
默认守卫，单独串行重试v13的资源失败。该重试也在P0前的`hier-flatten#0`
因`cgroup_pressure`停止，child=-15；[原始guard](../../ptmp/firrtl-ingest/F32/capture-v14/grh/guard.json)
记录some/full avg10=35.96%，最后进程RSS60,954,476,544 bytes，cgroup
file80,088,621,056 bytes。串行并未消除已关闭派生文件的缓存；这些采样不能
证明唯一压力来源。失败未产生P0或窗口结果，冻结源码未变，未放宽守卫。
[资源审阅](../../ptmp/firrtl-ingest/F32/capture-v14/resource-review.md)对照成功v12
启动时file20,213,624,832 bytes与v14启动时100,121,161,728 bytes。随后确认
comparison-v3已关闭且无sidecar、有界triage连接结束，经已有
`release_f30_analysis_cache`仅对该指定目录的5个派生文件提出DONTNEED，
文件总长192,077,022,045 bytes；没有打开数据库、删除或改写内容。
[执行记录](../../ptmp/firrtl-ingest/F32/capture-v14/comparison-cache-release.log)
及同目录cache-before/after观测保留：scope file由80,116,273,152降到
7,545,876,480 bytes，PSI avg10=0；文件总长不是实际回收量。
已由同一Make入口启动新目录`capture-v15/grh`，保持package-v18、原始输入/
manifest、完整structure和默认96GiB/25%持续8s守卫；最终结果见§9.30。
U1–U4未获批准、未应用；F32.0–F32.5继续实施，F32.6–F32.7未启动，未提交。

### 9.30 v18 完整五界与同端数据精确一致性（2026-11-17）

[capture-v15/grh summary](../../ptmp/firrtl-ingest/F32/capture-v15/grh/summary.json)
及[guard](../../ptmp/firrtl-ingest/F32/capture-v15/grh/guard.json)现均completed、
child return0；原输入/manifest、package-v18源码/库/dependency身份均保持。
五界semantic valid，Node依次为5,635,937 / 5,635,937 / 5,635,937 /
5,647,421 / 5,625,865。实际调用恰为五个prefix与四个窗口pass，以
`dead-code-elim#1`结束；之后仅P4验证/导出及artifact校验，没有运行后续pass。
[P0起点审计](../../ptmp/firrtl-ingest/F32/capture-v15/prefix-audit.json)
另确认Node/connection表正文与F31 v51逐字节相同。这是静态起点保持，不是行为证明。

当前四pass原生complete timer为8.989 / 21.134 / 1338.200 / 27.961s，
对应call为9.108 / 21.252 / 1338.323 / 28.083s；全捕获1889.604s，
maxRSS83,292,336KiB。它们仅是诊断计时与guard证据，不是F32.6正式测量，
不据此判断性能回退或达标。此前v13/v14失败保持原状，没有修改阈值。

新增`audit_f32_capture_identity` Make入口及
[`scripts/audit_f32_capture_identity.py`](../../scripts/audit_f32_capture_identity.py)
只审核两个已完成GRH捕获的数据身份，不读取、hash或复制comparison数据库/ledger。
它核对各自冻结输入、manifest、source/dependency/native包、guard command、
完整pass序列及五界验证；每轮run/graph一致、每界snapshot及exporter session
独立，侧表绑定该界session。生产每次snapshot建立新的exporter session，不能
要求五界exchange session相同或从它推断底层Session历史。两侧均有map时当前
明确拒绝，presence混合也拒绝，不补造映射；本次真实全图均未导map。

四表仅忽略首行meta，其header/全部rows/footer逐字节比较，同时校验各自完整
hash/bytes、schema、footer计数与冻结artifact；完整JSON则逐字节及hash比较，
不解析或忽略任何JSON字段。所有输入前后检查stamp，小metadata再检查最终hash。
相同数据发布equal，不同数据发布different；身份/hash/guard错误只发failed。
新[17项合同](../../ptmp/firrtl-ingest/F32/capture-equality-contract/report.md)
覆盖真实包验证路径的微型fixture、不同metadata相同body、差异/伪hash/footer、
mixed run/session、未完成guard、map拒绝、运行中变化与receipt写失败，均通过。
没有修改锁定比较器、seed或proof身份。

工具已对实际v17 capture-v12与实际v18 capture-v15串行执行，
[receipt](../../ptmp/firrtl-ingest/F32/capture-v15/data-identity-v17-v18/receipt.json)
为completed/equal：**20/20原生表体及5/5完整JSON精确相同**，125.766s。
每轮的source/package/native及run/snapshot身份分别保留；不会把v17文件改称
v18产物。这建立已捕获数据在新包的运输范围，允许继续使用v17台账定位相同数据，
没有新建v18跨端比较summary，也没有重新证明旧数据库每行或任何新命题。
`semantic_acceptance_evaluated`、behavior/source/fullNode/serialized endpoint
proof均明确false。§9.29台账的971,121新增边界行次及未证来源/结构限制继续有效；
不能把精确同端数据相同写成跨端语义验收。

针对P2数组state线索，完成[两组八元素UInt2寄存器合成诊断](../../ptmp/firrtl-ingest/F32/p2-state-array-triage/report.md)。
mixed-CURRENT中前四cell完整2-bit输出使其保留2，后四只看low1而缩为1；full-RHS
中完整sampled数据旁路保留2，所有state/current/NEXT缩为1。双端四次小捕获均
return0、十次GRH验证通过，实际map/端点/operand及regSymbol或GSIM配对检查
分别覆盖2,232映射（2,077个非相同编号）、499端点、1,577操作槽及240writer槽。
每界先按fixture/stage独立断言预期state宽度，再以1,024组定义投影prestate/
输入/enable/上升沿向量检查245,760项输出及163,840项逐cell转移，均通过。
实际full-RHS从原16-bit shape[8]数据按14/12/.../0源位提取，再Concat为8-bit并
重设shape[8]，writer取1-bit，完整RHS输出另走原2-bit cell；没有用packed低8位
替代逐cell low1。NEXT下多个形状的candidate本身不能构成接线错误。
这些是合成独立有限例，不是E040–E042实际原始锥重现；初始X、XZ转移、完整
source/Node仍未证。诊断工具补上定义十进制0解析及独立宽度断言后复查通过，
没有修改或重跑原生捕获来迎合检查。

同端全量审计和P0起点检查结束后，通过已有`release_f32_cache`对v12/v15两个
已闭合capture的42个文件提出DONTNEED，91,774,552,765 bytes、零错误。
[记录](../../ptmp/firrtl-ingest/F32/capture-v15/closed-capture-cache-release.json)
保留全部文件，scope file观测降至约7.79GB；该文件长度不是实际回收量。

F32.0–F32.5仍未达到全部退出条件。U1–U4未应用；U4第一步可审阅diff及回归计划
已按§1.2单独提出确认，未收到批准即保持未应用。F32.6–F32.7未启动，未提交。

### 9.31 UsedBits operand 辅助锚点修复与 v19 原始重现（2026-11-17）

E040–E042 已从同名/类型线索推进到[原始 GRH 槽位诊断](../../ptmp/firrtl-ingest/F32/p2-actual-grh/report.md)
及[原始 GSIM 树诊断](../../ptmp/firrtl-ingest/F32/p2-actual-gsim/report.md)。
GRH cell0 的选中输入 Node7718512 与 NEXT9448437 在 P1 真实共享 serialized
SliceArray 结果344495；NEXT 另有 reset 常量1328317。P2 该结果由2缩为1，
原16-bit/shape[8]输入按14/12/…/0源位重组为8-bit/shape[8]，逐cell保留low1。
十个新辅助op只属于输入 Node，但旧实现将其结果同时追加到输入和NEXT的完整
anchor集合，使public依赖出现 NEXT→输入。实际writer的data slot1仍为344495，
enable、两个posedge事件及main/reset writerOrder均保持；本例不需要迁移最终
writer anchor。原生物理ID与serialized ID经真实anchor/member分别取得，没有
按数字相等猜测映射。GRH使用2,845次、GSIM使用114次有界索引查询，未重扫巨型
原始文件；历史cache信任与局部锥前沿均保留。GSIM八对current/NEXT同样2→1，
各RHS保持2，NEXT数据实际有OP_BITS[0:0]，配对、clock与cell索引均已检查。

修复局限于[UsedBits](../../wolvrix/lib/transform/grhsim/used-bits.cpp)：
operand辅助op保留type、operand、partition、origin、operation membership、
旧member提示及位置；其新结果不继承原op结果的完整SemanticId anchors。
低位无操作路径直接返回原输入，真实结果及writer/binding/operand替换路径继续
保持原锚点。公共rewrite helper及前驱实现未改。新增原始FIRRTL原生回归先在
旧实现[明确失败](../../ptmp/firrtl-ingest/F32/native-v30-helper-anchor-before/tests/test.log)，
诊断为`operand reconstruction added complete result anchors to bank$NEXT_0`；
修复后[joint native 17/17](../../ptmp/firrtl-ingest/F32/native-v32-helper-anchor-joint/tests/test.log)
通过，4.40s。回归检查精确原锚点、非空且有归属的无锚点辅助值、逐cell缩宽及
有限输出/状态效果；已有scalar、array、signed、XZ、writer slot和显式DCE用例
一并通过。这是producer身份维护缺陷，未由这些检查建立仿真行为反例。

`make py_install`后经原有snapshot入口冻结
[package-v19](../../ptmp/firrtl-ingest/F32/package-v19/identity.json)：

| 身份 | SHA-256 |
| --- | --- |
| source content | `5c9dcf8e1c8acb5d5a78d4f19205f8696183af2db025a3b93702a3f7ee3eeb1a` |
| core library | `3e2361810808351ed9785159d63d94012f16504fab83d34bbb350635596322c3` |
| Python extension | `bb5a163433518b3af3d130bbc420c49ca5febdee22fac3fb1f561dd9b1b60b82` |
| dependencies | `c2b75c632ae6acd7b21a19660a718d8f989c54b84b3a96a2917d5504623cbcc7` |

两组[新v19八cell捕获审计](../../ptmp/firrtl-ingest/F32/p2-state-array-v19/report.md)
复用冻结GSIM控制，不重跑参考端。两个新child均return0，十界semantic valid；
P0/P1 JSON与v18精确相同，P2物理结构、库存及membership保持，去掉额外anchors。
实际map覆盖2,232行，其中2,077行的native/serialized编号不同；端点499→315。
最终auditor独立检查formal clock、预期state宽、P1原锚点及tree context/boundaries，
使用16交替加24逐cell basis模式，即40 old×40 data×enable×edge＝每界6,400组
定义投影向量，3,396,681项断言、1,536,000输出及1,024,000逐cell转移通过。
该flat例缺少独立具名selected input，旧/新均无目标reverse edge；它只重现
额外anchors，明确保留为负控制，不能称作原始E040依赖重现。

另从原始FIRRTL建立[aggregate-state重现](../../ptmp/firrtl-ingest/F32/p2-alias-native-v19/variants/report.md)：
父模块逐cell连接嵌套Vec-of-Bundle输入，子模块整体连接aggregate寄存器，使
selected input与NEXT共享真实SliceArray结果。前三个不重现的variant原样保留。
成功例双包P0–P4物理图及operation ownership精确相同；P0/P1 public边无差异，
P2–P4各移除八条NEXT→selected input及八条parent input→NEXT辅助路径，
没有新增边，原selected input→NEXT全部保留。P4 DCE只剩每cell三个helper，
实际bit offset及packing位置另行检查。真实map/端点/槽位关联及独立预期state宽
通过；每界1,024组有限向量得到424,320项断言、163,840输出及81,920转移检查。
该例没有reset writer，不模拟未知初始化/XZ，也未穷尽八cell独立状态。

原始全图的新v19 [capture-v16/grh](../../ptmp/firrtl-ingest/F32/capture-v16/grh/summary.json)
现已完成；同输入/manifest及96GiB RSS、PSI25%持续8s守卫保持，串行执行，
[guard](../../ptmp/firrtl-ingest/F32/capture-v16/grh/guard.json) completed/child return0，
五界semantic valid，精确五个prefix加四个窗口pass，在第二次DCE/P4停止。
Node依次为5,635,937 / 5,635,937 / 5,635,937 / 5,647,419 / 5,625,863。
[P0/F31复核](../../ptmp/firrtl-ingest/F32/capture-v16/prefix-audit.json)确认Node与
connection表正文保持；P0/P1完整JSON的最终冻结SHA与v18相同。四pass原生
诊断timer为9.132 / 21.489 / 1349.427 / 28.217s，全捕获1917.440s，
maxRSS81,151,564KiB；这些不作为F32.6性能验收或回退结论。

对已关闭P2作[完整逐行诊断](../../ptmp/firrtl-ingest/F32/p2-actual-grh/v19-full-P2-diagnostic.json)：
5,635,937个Node中74,257个改变，共移除75,736处anchor；其余Node字段及全部
47,355,138条非Node行精确相同，没有新增或替换anchor。原始cell0–2的输入端点
11→1、NEXT12→2，三条false reverse及三条parent279887→NEXT边移除，
原输入→NEXT保持且所选入边没有新增。原receipt记录扫描时parent仍running，
该历史状态保留；现经[最终绑定](../../ptmp/firrtl-ingest/F32/p2-actual-grh/v19-full-P2-final-binding.json)
及[独立link复核](../../ptmp/firrtl-ingest/F32/p2-actual-grh/v19-full-P2-receipt-links.json)
将六个旧/新结构及TSV的既有全量hash、未变stamp和最终artifact路径/大小/
metadata/footer逐一绑定，不重复hash巨型文件。结论仅针对P2，不重标§9.29台账。

[原始P3/P4定点复查](../../ptmp/firrtl-ingest/F32/p2-actual-grh/v19-P3-P4-selected-review.md)
再顺序读取12个已完成TSV，保存全部六个target的incident边和端点。两界均恰好
移除同六条边，没有新增incident边，输入→NEXT及parent→输入保持。v19输入
每cell一个SliceArray candidate，NEXT另加reset Constant，全部1-bit unsigned
scalar FourState；精确native value/op generation及类型tuple从P3到P4保持。
这不将无map的native物理编号连接到serialized ID，也不证明完整行为或归属。

P3/P4分别比v18少两个Node，不能据P2物理相同外推P3/P4。小型
[bit-slice表复核](../../ptmp/firrtl-ingest/F32/p2-actual-grh/v19-slice-inventory-delta.json)
核对最终hash及全部几何：各界17,483→17,476条，12个父不再拆分而7个父新增拆分，
旧24条子几何消失、新17条出现，共有父的几何保持。子项−7与退休父项−5相抵
得live Node−2；另有11,665条共有几何的child ID因分配顺序改变。此为完整小表
库存对账，尚未独立证明19个变化父的每个选择或其值；跨包必须按父/位区间关联，
不能按child编号认定同一来源。

[19个变化父的有界审阅](../../ptmp/firrtl-ingest/F32/p3-split-delta-families/report.md)
以383次索引query保存实际名称、旧P2锚点、owned op槽位、type及前沿。
5106958、5112688、5127709三个真实例同时锚定辅助Slice和最终Assign结果；
`splitSemanticValue`遇到另一个不同anchor便只维护投影cone而保留父项，故误加
helper anchor会阻止退休。实际149→141位输入链另显示同一范围可从两个consumer
anchor重复收集；`referenceRanges`及`greedyPlan`按这些出现次数计算端点与跨越数。
随后[实际v19 P2 Node选择](../../ptmp/firrtl-ingest/F32/p3-split-delta-families/v19-P2-selected-Nodes.json)
顺序读取完整5,635,937行Node数组后停止，1,185,020,708 bytes、2.955s，
绑定最终artifact与未变stamp，未打开physical sections。19项真实名称及全部
operation membership精确相同；恰好5106958、5112688、5127709各去掉上述一个
helper anchor，保留9711748、9726530、9764109，其余16项anchor数组保持。
这直接确认三个旧退休阻挡在新P2已移除；完整planner输入及其间重写仍未重放，
不能称为19项cut因果或行为证明。12个不再拆分的父本身原有零/一个锚点，
它们须从consumer范围变化另行解释，不能套用多锚点退休阻挡。

实际`out_plaInput`父2430332也已单独作
[P3/P4 JSON选择](../../ptmp/firrtl-ingest/F32/p3-actual-split/selected-json-summary.json)
及[消费槽位审计](../../ptmp/firrtl-ingest/F32/p3-actual-split/consumer-transport.json)。
历史P2父是7-bit Assign，输入为具名src Node2429999；上述新P2选择也直接确认
父anchor4714049/member4700443及src anchor4712924。P3/P4父退休，真实child
9727427/28各有一个SliceStatic，分别取该界真实src的[2:0]/[6:3]，unsigned
FourState及3/4宽保持。P3真实Concat按高child、低child顺序重建完整7位。
每界两条incoming及48条child outgoing boundary均核对真实user/operand/value
与slice区间，原receipt的41/48条对应到历史P2消费者的精确投影。
随后[七条取反路径闭环](../../ptmp/firrtl-ingest/F32/p3-actual-split/inversion-closure.md)
另行选择P3/P4真实`out_invInputs`子项9727420–26：每界7 Node、23 op、24 value，
Slice→Assign→Not至真实anchor的全部局部producer/type闭合，实际membership及
七条incoming槽位逐项匹配。各bit函数均为`Not(source7[i])`，与历史P2取反结果
对应位相同；128个定义源值/界，共2,048次值比较及56次抽象Not检查通过，
[独立审阅](../../ptmp/firrtl-ingest/F32/p3-actual-split/inversion/independent-review.md)
确认。原41条投影和新增7条局部取反函数分开保留；每界另100条outgoing行仅
确认anchor端点值，未检查下游user槽位或函数，不能称完整消费者/Node等价。
另以[实际record重放oracle](../../ptmp/firrtl-ingest/F32/p3-actual-split/reconstruction-oracle.json)
穷尽各界7-bit自由源的128个定义值，13,184次child/重组/消费投影比较通过。
逐bit身份只覆盖这些实际Slice/Concat线路上的抽象0/1/X/Z符号，不证明运行时
XZ/完整Node/参考端值等价。共享选择仍有无关缺失type/producer前沿，明确保留；
P4选择中没有整值Concat不代表全图不存在。后续取反选择顺序读取两界JSON，
73.663/71.748s，以最终metadata/bytes及未变stamp绑定，不另行重hash或建索引；
该局部自由源前提仍未证明上游source或跨端值相同。

[独立审阅](../../ptmp/firrtl-ingest/F32/p2-actual-grh/full-P2-independent-review.md)
确认stream parser符合实际serializer布局，额外补查alias例的双向map双射、898端点、
708完整连接行、全部非anchor字段及metadata身份；无新增行为/完整Node证明。

E001–E003另补[实际槽位的条件需求重放](../../ptmp/firrtl-ingest/F32/aw-actual-cone/demand-report.md)：
以实际low43 Sub结果有非零需求为明确前提，FourState Sub要求full49输入，
经真实Concat/Assign/Mux/地址routing/Or反推T21/T22/T23均需full48。40个高位
X/Z局部例显示提前截掉bit43–47会把low43由全X变成定义值；16个定义例保持
模2^43等式。这只读取此前小型实际receipt和当前source，未新增native运行。
没有独立证明该seed到可观察根的liveness、重放整个queue、穷尽users或建立
GSIM可达XZ反例，故没有将这三项升级为完整已解释差异。

全部原生捕获/大文件选择结束后，经已有`release_f32_cache`向v15/v16的42个
闭合文件提出DONTNEED，文件总长91,750,788,959 bytes、零错误，
[cache记录](../../ptmp/firrtl-ingest/F32/capture-v16/closed-capture-cache-release.json)
保存前后观测；保留所有内容，文件长度不代表实际回收量。

source geometry、丢弃位不可观察性、初始X/XZ/reset完整行为、全Node及整机
等价尚未证明；`semantic_acceptance=false`。U1–U4未批准、未应用，U4此前
具体diff的确认仍待回复；窗口内独立工作继续。F32.0–F32.5未达到全部退出条件，
F32.6–F32.7未启动，未提交。

### 9.32 显式二值窗口、统一调用入口与待验状态（2026-11-17）

本轮按用户“严格按照二值处理”的要求，给 `expr-opt`、`used-bits`、
`split-nodes` 增加显式 `-semantics=2state|4state` 参数，Python 接口对应
`semantics="2state"`。三个 pass 的独立 API 默认保留 `4state` 模式；F32
捕获和二值生产调用明确选择 `2state`，不依赖 frontend 的类型标签推断。
原始逻辑类型、Node 身份及来源字段保持原义，不通过重标类型或补写来源
把旧捕获包装为二值结果。

当前修改包括：ExprOpt 按所选模式比较常量臂；UsedBits 在二值模式下以
有限位宽模运算传播 Add/Sub/Mul 的前缀需求，并按同一模式解释常量
enable/index、缩宽常量和状态初值；SplitNodes 将所选模式用于常量索引、
常量/初值投影和算术前缀。兼容的四态路径保留 X/Z，并用二进制字面量保存
部分未知位，避免十六进制 nibble 序列化丢失已知位。这是窗口实现的显式
语义选择，不是对 U3 公共四态求值器的前驱修复。

`scripts/capture_f32_pipeline.py` 默认 `--semantics 2state`，向三个窗口 pass
显式传参，并在新 summary 记录 `window_semantics`；GSIM 捕获只接受二值
模式。`scripts/grhsim_flow.py` 的生产窗口和
`scripts/wolvrix_xs_grhsim.py::firrtl_canonical_pipeline()` 同步显式传入
`semantics="2state"`。四个窗口 pass 的顺序及 P4 停止位置保持原合同。

新增回归覆盖 ExprOpt 显式二/四态常量判等、UsedBits 二值模运算和
SplitNodes 在保留 FIRRTL FourState 标签时的显式二值路径；它们与当前
capture/canonical caller 合同集中修改后统一验证。此前
[two-state-v3 联合日志](../../ptmp/firrtl-ingest/F32/two-state-v3/tests/test.log)
中的17/17及
[capture合同19/19](../../ptmp/firrtl-ingest/F32/two-state-v3/tool-tests/capture-contract.log)
属于更早的中间工作树；其后 ExprOpt 和调用入口仍有修改，不能作为当前
最终工作树通过的证明。当前验证与冻结结果如下。

- [v4 原生联合回归](../../ptmp/firrtl-ingest/F32/two-state-v4/tests/test.log)
  17/17通过；八组工具合同共245项，3项按既有条件skip。新增真实捕获发现
  原生无尺寸常量 `0` 未被二值reader接受，已修复。补充X/Z使能、索引、payload
  的二值数组集成与无尺寸常量合同后，[v6原生](../../ptmp/firrtl-ingest/F32/two-state-v6/tests/test.log)
  17/17及[reader](../../ptmp/firrtl-ingest/F32/two-state-v6/tool-tests/semantics-contract.log)
  76项通过（3 skip）。UsedBits二值Add/Sub/Mul各穷尽256×256输入、两种树入口；
  数组用例检查未知enable→0、`x1`索引→1及payload逐位清零，并推进SplitNodes/第二DCE。
- 经`make py_install`安装并冻结[package-v20](../../ptmp/firrtl-ingest/F32/package-v20/identity.json)，
  source content为`1a78b84cf3c6d614995e82550859bbef272039dc2c9828af500a43f382e39b0b`，
  dependencies仍为`c2b75c632ae6acd7b21a19660a718d8f989c54b84b3a96a2917d5504623cbcc7`。
  冻结后新增的两项回归只改测试，生产实现相同；完整source身份以该包为准。
- 两组原始FIRRTL均完成显式二值双端五界：[pipeline GRH](../../ptmp/firrtl-ingest/F32/two-state-v4/raw-probes/pipeline/grh/summary.json)、
  [GSIM](../../ptmp/firrtl-ingest/F32/two-state-v4/raw-probes/pipeline/gsim/summary.json)、
  [pruned GRH](../../ptmp/firrtl-ingest/F32/two-state-v4/raw-probes/pruned/grh/summary.json)、
  [GSIM](../../ptmp/firrtl-ingest/F32/two-state-v4/raw-probes/pruned/gsim/summary.json)。
  GRH十界semantic valid，原生map冻结；三个窗口pass逐call记录parameters.semantics。
  [pipeline严格比较](../../ptmp/firrtl-ingest/F32/two-state-v5/pipeline-comparison/summary.json)
  仍有3个新增unproved（sameArms在P1–P3的残留member），
  [pruned严格比较](../../ptmp/firrtl-ingest/F32/two-state-v4/raw-probes/pruned/comparison/summary.json)
  新增该项0；source/full Node及严格gate未通过，未将待DCE物理行提前删除。
- 当前[合成算术专项](../../ptmp/firrtl-ingest/F32/two-state-width-v20/independent-audit.json)
  双端四次capture及20个边界完成，4→3位穷举512输入、48→43位检查290输入，
  共56,140项输出按独立整数公式通过；另有4,013项身份/槽位断言、998 map行，
  其中598 native/serialized编号不同。此为合成定义值证据，未证明原始aw链完整值。
- 扩展[完整flow](../../ptmp/firrtl-ingest/F32/two-state-v4/caller-tests/driver.log)
  有5项error，涉及窗口外blackbox-guard新树gate及旧checkpoint配置；
  [XS工作流](../../ptmp/firrtl-ingest/F32/two-state-v4/caller-tests/xs-driver.log)
  85项中4项失败，涉及旧semanticIds断言和mux-tree-fold/constant-analysis等gate。
  未扩大F32支持窗口或放宽gate以使这些完整后端用例通过。

当前reader只对summary明确记录`window_semantics=2state`且三个GRH窗口call参数
一致的捕获启用二值正规化；跨端模式不一致拒绝。X/Z按二/八/十六进制实际bit清零，
支持原生无尺寸十进制，完整Node/source/state门保持。历史capture缺该字段时仍沿用
旧的保守证明语境，不离线补写标签。当前完整香山[新capture-v17](../../ptmp/firrtl-ingest/F32/capture-v17/grh/summary.json)
使用package-v20、原始输入/manifest和默认96GiB/25%持续8s守卫，已通过P0–P2
semantic验证。该次在SplitNodes运行约906秒后于19:49:44按用户要求停止，
无P3/P4；历史summary/guard的running标记已失效，原证据保留。后续修复及重测见下节。

历史 package-v19/capture-v16 及 v17 comparison-v3 保持原身份，不补写
`window_semantics`，不将旧的四态保守算术解释用于当前二值差异验收。
新的逐 pass 差异对照仍须绑定实际新包、新捕获及 reader 身份；现有有限
proof工具拒绝未知字面量的命题不能直接证明二值 X/Z→0 解释的全部行为。
source geometry、成员/退休、状态/外部效果和新增差异覆盖仍未完成，
`semantic_acceptance` 保持未通过。U1–U4 的前驱补丁未批准、未应用；其中
U3 仅作为历史四态问题记录，不阻塞本轮二值行为验收。F32.0–F32.5 继续
实施，F32.6–F32.7 未启动，未提交。

### 9.33 SplitNodes 超时修复与有界重测（2026-11-17）

[采样诊断](../../ptmp/firrtl-ingest/F32/split-timeout-diagnosis/reason-report.md)
确认每个源分别分析消费者时重复复制全部入边；45秒CPU采样中，
`semanticBoundaryUsesForNode`及其vector扩容/push合计52.93%独占样本。
修改只涉及窗口内SplitNodes查询及GRH只读索引接口：按源值/目标Node选择较小
的现有索引，借用行号并过滤完整ValueId、目标、source和实际user/slot。
通配边、其他owner抑制fallback及单owner fallback规则保持，span不跨图修改保存。

新增64源共享消费者回归，约束`focused-boundary-visits`并验证拆分几何与
第二DCE后行为。[本次原生回归](../../ptmp/firrtl-ingest/F32/split-fix-v1/tests/test.log)
17/17通过（SplitNodes测试3.08秒）；独立静态复核见
[review.md](../../ptmp/firrtl-ingest/F32/split-fix-v1/review.md)。
外部supervisor新增可选阶段超时，并验证native占用GIL时仍能停止进程组；
capture合同23项及resource guard合同19项通过。额外CPU采样的准备和收尾均在pass计时外。

已通过`make py_install`安装并冻结[package-v21](../../ptmp/firrtl-ingest/F32/package-v21/identity.json)，
source content为`a4c63aafc456ec06a93ad0a21a6bffc6b61dd5f571d9df5d030ff35d48e860ee`，
dependencies仍为`c2b75c632ae6acd7b21a19660a718d8f989c54b84b3a96a2917d5504623cbcc7`。
[capture-v18](../../ptmp/firrtl-ingest/F32/capture-v18/grh/summary.json)
从原始SimTop.fir及原manifest重新运行，显式二值、五边界并在第二DCE停止；
SplitNodes的wall上限180秒，启用99Hz诊断采样。该次在180.219秒时触发
`phase_timeout`并退出，P3/P4未产出；采样零丢失，约178.707秒CPU。
`component`独占39.36%，component结果表插入9.97%；入边复制已不再主导，
重复DAG推导仍然明显。证据见[首轮新采样](../../ptmp/firrtl-ingest/F32/split-fix-v1/perf-self.txt)。
现有GSIM capture-v4同阶段完整native计时96.437122381秒，只作历史单次参考。

按用户要求重新对照GSIM：其`componentMap/componentEMap`先按图序推导，
`genReferSegment`按消费者累计`nodeSegments`，拆分后通过去重`reInferQueue`
删除旧区间、重推并更新影响节点。GRH当前仍按源/消费者查询，不能把物理值
缓存直接当作带source owner及实际slot上下文的引用结果。
第二轮在单源direct查询的只读范围内建立实际use-list依赖闭包：沿结果传播，
按value owner边界停止；无关子树仅保留宽度，不反复构建Component。
闭包在每个消费者查询内重建，不跨图修改保留。成员归属改查op的反向owner索引。

新增128源平衡Concat DAG、跨操作归属的匿名结果、Mux selector-only路径及
SPACE引用去重回归。平衡用例直接推导3200次、依赖访问3456次。
[原生17项](../../ptmp/firrtl-ingest/F32/split-fix-v2/tests/test.log)通过，
最后新增SPACE用例后的[SplitNodes专项](../../ptmp/firrtl-ingest/F32/split-fix-v2/final-space/split-nodes/tests/test.log)
通过（3.64秒）；[独立复核](../../ptmp/firrtl-ingest/F32/split-fix-v1/pruning-review.md)
未发现正确性阻塞。已安装并冻结
[package-v22](../../ptmp/firrtl-ingest/F32/package-v22/identity.json)，source content为
`28de19e8679b6b6fca6292e096e8217246eaf72e1c6dac8e9806c504fb76a9a8`。
该冻结后仅补充测试，生产实现保持；依赖身份同前。
[capture-v19](../../ptmp/firrtl-ingest/F32/capture-v19/grh/summary.json)
再次从原始FIRRTL执行，在180.232秒时自动停止；采样仍以component为主
（41.24%独占），无P3/P4。局部直接引用剪枝不足以完成本次性能修复。

后续保存P2短诊断增加可选工作量日志，确定ROB的`_walkCandidates`与
`_commitCandidates`命名转发链在producer路径反复展开。已新增两层优化：
非展开命名边界的producer结果若必含SPACE，可直接返回原有whole Source回退；
其余producer子component按完整ValueId和expand标记复用，并记录所有可能
影响边界解释的singleton owner区间。只有target在该区间外才复用外部target
基准结果；cycle命中的调用不发布缓存。每次表达式改写前、stateCuts更新时
清空缓存，并在Design revision变化后拒绝旧缓存。详见
[memo复核](../../ptmp/firrtl-ingest/F32/split-fix-v3/memo-review.md)。

192层命名位运算链访问769次；192层fully-valid Assign链访问385次、命中191次。
[原生17项](../../ptmp/firrtl-ingest/F32/split-fix-v4/tests/test.log)及新增用例后的
[最终SplitNodes专项](../../ptmp/firrtl-ingest/F32/split-fix-v4/final/split-nodes/tests/test.log)
均通过。安装并冻结[package-v25](../../ptmp/firrtl-ingest/F32/package-v25/identity.json)，
source content为`2491d7739b5ba983e05f530e38e283997c635d4211fe07c048c51c77446c8fb2`，
依赖身份同前；冻结后仅测试/文档变动，不改生产代码。

[保存P2诊断原生计时](../../ptmp/firrtl-ingest/F32/split-fix-v3/run-v3/split-timing.jsonl)
完整返回106.182995345秒，162515次改写、30531352次producer缓存命中。
诊断wrapper在native返回和profile收尾后把消息list误当dict，导致汇总状态失败；
原失败证据保留，工具已修正，未将该summary改成成功。说明见
[probe-result.md](../../ptmp/firrtl-ingest/F32/split-fix-v4/probe-result.md)。
保存JSON未恢复全部临时source binding，因此该次只作性能诊断。
[capture-v20](../../ptmp/firrtl-ingest/F32/capture-v20/grh/summary.json)
已用package-v25从原始FIRRTL/manifest完整执行并正常退出。显式二值、180秒SplitNodes
上限、CPU采样及原五边界保留；supervisor为completed、returncode=0、无超时。
五个SemanticTree检查均valid=true、error_count=0；五界文件哈希核验完成，第二DCE后停止。
修复前capture-v17与本轮capture-v20的P0/design.json通过cmp逐字节比较，
6,922,759,015字节完全相同，未改变第一次DCE后的窗口输入。
包含ingest、prefix、五界导出和最终核验的整次capture为691.14秒，不能当作pass耗时。

| 对应原生pass（秒） | GRH capture-v20 | GSIM capture-v4 |
| --- | ---: | ---: |
| ExprOpt | 9.491547034 | 24.697746563 |
| UsedBits | 22.441102232 | 9.224102814 |
| SplitNodes | 114.412411551 | 96.437122381 |
| 第二DCE | 28.121047659 | 41.647102156 |

SplitNodes完整返回、未超时；GRH比历史GSIM单次慢17.975秒（18.639%）。
GRH调用层114.547932930秒含包装开销；上表统一采用scope=pass的steady_clock原生计时。
这不是新的一组双端正式性能验收，GSIM是历史capture，本轮GRH启用99Hz诊断采样。

| 第二DCE后P4完整库存 | GRH | GSIM | GRH − GSIM |
| --- | ---: | ---: | ---: |
| Nodes | 5,625,297 | 5,922,045 | -296,748 |
| 连接记录 | 9,172,539 | 9,361,136 | -188,597 |

[P4唯一名称库存报告](../../ptmp/firrtl-ingest/F32/split-fix-v4/P4-inventory/summary.json)
已完成两端nodes.tsv哈希、完整footer和唯一递增ID检查：唯一同名候选5,604,205个，
占GRH 99.62505091%；未配对GRH 21,092个、GSIM 317,840个。统计98.75秒，
semantic_comparison_performed=false、semantic_acceptance=false，不能称为语义对齐率。

两端TSV均有complete footer；GRH另有217,478条未解析dependency记录，GSIM有1条
未解析external_binding记录，不能从完整记录数推出连接语义覆盖完整或双端等价。
GSIM旧summary没有window_semantics字段，保留未声明状态，不回填标签。
独立[身份/计时审计](../../ptmp/firrtl-ingest/F32/split-fix-v4/evidence-audit.md)
确认当前生产源码与冻结包一致；[最终静态复核](../../ptmp/firrtl-ingest/F32/split-fix-v4/final-review.md)
未发现本次性能修改的正确性阻塞。CPU报告保存于
[perf-self.txt](../../ptmp/firrtl-ingest/F32/split-fix-v4/perf-self.txt)，零丢失样本，
旧的全部入边复制不再占主导；component和referenceRanges仍占25.43%与10.69%独占样本。
本次完成SplitNodes修复及重测，不改变U1–U4状态，也不表示F32整体语义验收通过。

### 9.34 阶段 6 测量与阶段 7 证据整理（2026-11-17）

用户要求“继续完成F32，现在转到阶段6和7”，已开始执行。当前选择的行为口径
仍是显式 `semantics=2state`，范围仍止于第二次 DCE。U1–U4 没有新的批准或实现。
阶段 6 可以先收集当前冻结版本的新样本；F32.5 尚未证明的差异和来源问题仍
阻止正式验收与整体完成。全量 P4 的 99.62505091% 仅为唯一同名对应率。

新增 `benchmark_f32_passes` 和 `compare_f32_performance` 两个 Make 入口，
配套 runner/comparator 契约回归。runner 从完整原始 FIRRTL 和 manifest 正常
运行 prefix，保持实际 P0，关闭 trace、快照、库存导出、外部 verify、profile。
四个原生 pass timer 与整个连续窗口分别保存。GRH 原生 timer 的 ordinal 随
独立调用重置，故第二 DCE 的逻辑身份显式记为 `dead-code-elim#1`，保留原生
`dead-code-elim#0`；GSIM 对应 `RemoveDeadNodes1#0`。不靠边界名猜计时。

GSIM 仅增加 `F32Window#0` 连续 `steady_clock` timer：第一 DCE 的 P0 边界末尾
起计时，第二 DCE 的 P4 边界入口结束，包含四次调用之间的框架与维护成本，
排除捕获导出。原生构建通过 `make f32_gsim_benchmark_build` 完成，小例窗口 timer
smoke 通过。独立审查发现 `phase6-tools/phase6/build/gsim-build.log` 已被后续
no-op 构建覆盖，现存文件不能证明原始完整编译命令；冻结源码的默认 `-O3`
配置、binary/source 哈希和 clang 22.1.2 身份可核验，实际命令留档缺口保留。
Make target 已改为每次独立日志名，当前运行的冻结样本未被修改或重启。
runner 的 4 项契约回归通过。comparator 的 16 项契约回归通过，包括真实首个
GRH 样本的只读 schema/native/guard 校验；非交错顺序、旧样本、重叠、guard/hash
篡改、遗漏/失败、原生 timer 身份、单项回退和整窗独立门均有负例。

首组 `phase6-v1` 已启动，使用 package-v25、同一原始输入 SHA 和新构建的
GSIM binary SHA `fb3a1381b3e37b197a771ae167e3ae0ba65f8aa4760d9cf406707e058649c468`。
固定 CPU 2、单线程，顺序为 GRH / GSIM / GRH / GSIM / GRH / GSIM，每端三轮；
RSS 96 GiB、memory PSI 25% 持续 8 秒保护，双方 SplitNodes 均有 180 秒 watchdog。
完整 group/config/native/package/input 身份和每轮系统负载、guard、资源样本保留。
首对样本均已正常退出，原生计时如下；每端三轮尚未完成，不能将单次结果当作
正式中位数。连续窗口包含框架成本，与四项原生计时和分别对账。

| 首对新样本，秒 | GRH 01 | GSIM 02 |
| --- | ---: | ---: |
| ExprOpt | 9.173242512 | 25.243053675 |
| UsedBits | 20.554388929 | 9.242198681 |
| SplitNodes | 120.252687358 | 100.283722185 |
| 第二 DCE | 26.122619471 | 39.409364019 |
| 连续窗口 | 176.756217308 | 174.178532032 |
| 窗口减原生 pass 和 | 0.653279038 | 0.000193472 |

GRH 样本 03、05 均在 hier-flatten 前驱阶段触发 memory PSI 资源保护，未进入窗口：
`reason=cgroup_pressure`、`returncode=-15`，RSS 峰值 60.327 GiB；父 cgroup 的
some avg10 为 39.43%，超过 25% 持续 8.061 秒。不是 SplitNodes 超时或窗口
错误。05 的 RSS 为 70.479 GiB，some avg10 34.91%，持续 8.039 秒。
六轮全部执行结束，GSIM 三轮成功、GRH 仅一轮成功。原始组状态为
`completed-with-failures`；[正式比较报告](../../ptmp/firrtl-ingest/F32/phase6-report-v1/summary.json)
为 `incomplete`、`passed=false`，保留全部六个样本并拒绝两个失败项，没有计算
假冒的 GRH 三轮中位数。GSIM 三轮 UsedBits 为 9.2422 / 9.2944 / 9.2188 秒，
SplitNodes 为 100.2837 / 100.6556 / 99.8453 秒。首对 UsedBits 与 SplitNodes
超容差，窗口总量不能抵消单项回退。
文件缓存/direct reclaim 活动增大是实际观测，压力根因尚待排查，不推定为 OOM。

整组结束后保留原 runner/guard/comparator 副本于 `phase6-v1/tools/`，再应用
下一版监控补丁：GSIM 完成 SplitNodes 后切到第二 DCE，进度仅在阶段变化时写入；
group 固定 runner/guard 哈希，child 前后实际观测 affinity/environment 并核对。
新 runner 8/8 契约回归通过。所有旧样本保持原始数据，不补写新观测字段。
GSIM build target 改独立日志名；首组运行期间生产 pass 和 package-v25 未改变。

`make release_f32_cache` 对 5 个已关闭且 guard 已结束的捕获目录执行
POSIX_FADV_DONTNEED，94 个文件、236,114,050,977 bytes，无错误；只释放缓存建议，
不删除内容、不清全系统缓存。报告为 `phase6-tools/closed-capture-cache-release-v1.json`。
UsedBits 源码与 GSIM 对照发现可避免的 operand 快照、重复区域/属性复制，但尚无
该 pass 的热点占比。已新增 `make profile_f32_used_bits`，小例原始 prefix、perf
setup/finish 和 UsedBits stop smoke 通过；当前用原始完整 FIRRTL/package-v25
运行独立采样，资源守卫保留。此诊断明确不作为正式性能样本，完整验证仍在 pass 内。

独立[runner复核](../../ptmp/firrtl-ingest/F32/phase6-tools/runner-review.md)另发现
GSIM polling 没有在 native SplitNodes 返回后把阶段切到第二 DCE，后续 DCE
可能被 watchdog 计入 SplitNodes。已完成的三轮 GSIM 均没有触发此误杀；原始 timer
仍可核验。组结束后已应用和测试上述修正。旧组 child affinity/environment 主要由
父进程继承和源代码证明，summary 仅复制 group 配置，保留未独立观测的限制。

```bash
WOLF_ENV_SOURCED=1 make --no-print-directory benchmark_f32_passes \
  PYTHON=.venv/bin/python \
  F32_WORK=ptmp/firrtl-ingest/F32/phase6-tools \
  F32_PACKAGE=ptmp/firrtl-ingest/F32/package-v25 \
  F32_GSIM_BENCH_BUILD=ptmp/firrtl-ingest/F32/phase6-tools/gsim-build \
  F32_BENCH_GROUP=ptmp/firrtl-ingest/F32/phase6-v1 \
  F32_BENCH_ARGS='--repeats 3 --cpus 2 --split-timeout 180'
```

GRH 连续窗口从 ExprOpt 调用前起，到第二 DCE 返回止；timer 文件解析、哈希和
最终结果整理在窗口后完成。中间的轻量诊断结果检查和阶段进度写入保留在窗口内，
不从墙钟扣除；`framework_overhead_s` 对账原生 pass 和与连续窗口差值，另记
`progress_write_s`。该进度字段也包含首个窗口调用前的起始进度写入，不能将其
机械地从窗口减掉。阶段 7 的要求审计和工具复核放在临时
`ptmp/firrtl-ingest/F32/phase7-audit/`，最终支持矩阵、数据、限制和批准记录仍
整合在本文；尚未清理冻结证据或标记完成。

#### 9.34.1 UsedBits 采样与最小性能改动（2026-11-18）

package-v25 的独立原始输入 UsedBits 采样已正常退出，guard returncode=0，
原生 pass 为 **20.831661997 秒**。ingest 248.309 秒、hier-flatten 42.872 秒；
本次未触发资源保护。诊断报告位于
[used-bits-profile-v1/summary.json](../../ptmp/firrtl-ingest/F32/phase6-tools/used-bits-profile-v1/summary.json)，
[CPU 独占热点](../../ptmp/firrtl-ingest/F32/phase6-tools/used-bits-profile-v1/profile/perf-self.txt)
无丢失样本：validateSemanticTree 12.71%、其名称集合 insert 12.03%、
simplifyUsedBits 12.42%、opOperands 5.97%、opKind 5.92%、opResults 4.03%。
这是独占采样归因，不能把整行占比当作可直接消除的成本；本轮仍非正式样本。

依据实际热点，已集中应用三处存储/复制改动：名称去重使用现有
slang::flat_hash_set，保留同一 `(parent,name)` 判等、hash 与检查顺序；UsedBits
repair sweep 复用自有 operand vector，仍在 helper/operand 修改前独立快照；
SplitNodes 只移动调用内已用完的 inputs 和完成 memo 发布后的 root 返回值，
不移动共享 completed 子项或 producer memo 项。所有 descriptor/tree/binding/
retention 验证与维护仍在原生计时内，前驱语义和 P0 基线没有借此修复。
名称容器的[独立复核](../../ptmp/firrtl-ingest/F32/phase6-tools/validation-opt-review.md)
未发现正确性阻塞；联合
[17/17 回归](../../ptmp/firrtl-ingest/F32/phase6-opt-v1/tests/test.log)通过。

通过 make py_install 与 snapshot_f30_package 安装并冻结
[package-v26](../../ptmp/firrtl-ingest/F32/package-v26/identity.json)。诊断工具新增
`--finish-window`，小例已验证经过 SplitNodes/第二 DCE 后停止，并保留 180 秒
SplitNodes watchdog。当前完整原始输入诊断仅在 UsedBits 采样，后续两 pass 不
采样、不导出；用于确定收益和下一步优化，不作为新六轮正式交错组。
SplitNodes 其余候选见
[静态分析](../../ptmp/firrtl-ingest/F32/phase6-tools/split-analysis.md)；尚未把建议
或正在准备的后续补丁算入 package-v26、回归结果或性能结论。

package-v26 原始输入诊断已完整退出：ExprOpt 6.453574148、UsedBits 18.544938068、
SplitNodes 115.665756396、第二 DCE 26.362959318 秒，guard 正常完成。
随后优化 producer 调用内 Key：仅生产者推导归一 user/slot，direct witness 仍
保留真实槽位；UsedBits 分析阶段复用已检查的 kind/args/results，repair 仍读取
当前操作数。新增共享菱形与循环回退回归，联合
[17/17](../../ptmp/firrtl-ingest/F32/phase6-opt-v2/tests/test.log)通过；菱形实际
producer visits=259，低于 268 上限。独立
[源码复核](../../ptmp/firrtl-ingest/F32/phase6-tools/opt-v2-review.md)无阻塞。
已安装并冻结 [package-v27](../../ptmp/firrtl-ingest/F32/package-v27/identity.json)，
其原始输入诊断也正常退出，原生计时如下。两轮都仅对 UsedBits 采样，均无导出，
不是正式交错性能组，不把不同版本或诊断数据合并成中位数。

| 原生 pass，秒 | package-v26 诊断 | package-v27 诊断 | GSIM 首组 02 |
| --- | ---: | ---: | ---: |
| ExprOpt | 6.453574148 | 6.312975123 | 25.243053675 |
| UsedBits | 18.544938068 | 17.634365424 | 9.242198681 |
| SplitNodes | 115.665756396 | 109.354562054 | 100.283722185 |
| 第二 DCE | 26.362959318 | 25.820503962 | 39.409364019 |

原始报告为 [v26](../../ptmp/firrtl-ingest/F32/phase6-opt-v1/profile-window-full/summary.json)
及 [v27](../../ptmp/firrtl-ingest/F32/phase6-opt-v2/profile-window-full/summary.json)。
UsedBits 和 SplitNodes 仍有单项差距；后续 descriptor 条件读取与局部容器改动
不属于这两个冻结包或上表结果；后续实施与数据如下。

#### 9.34.2 package-v28/v29 与中断恢复（2026-11-18）

[package-v28](../../ptmp/firrtl-ingest/F32/package-v28/identity.json) 包含 descriptor
按非默认 operand/result 约束读取计数、仅有 schema 时读取属性的改动；保留
count/schema/custom verifier 的检查顺序和诊断。新增 descriptor 独立正反例。
SplitNodes 的调用内 `completed/active` 改用现有 flat 容器，保留 key、判等、
循环处理和 memo 发布。原始输入
[诊断](../../ptmp/firrtl-ingest/F32/phase6-opt-v3/profile-window-full/summary.json)
正常退出，原生 UsedBits **16.569697619**、SplitNodes **101.074374680**、第二 DCE
**25.712871142 秒**。UsedBits 外层调用为 16.718192102 秒，不与原生 timer 混用。
峰值 RSS 83,010,584 KiB。此单轮仅 UsedBits 采样，仍非正式交错验收。

[package-v29](../../ptmp/firrtl-ingest/F32/package-v29/identity.json) 再复用 validator
调用内不变的 Path 列表、Node 名称及成员 range；UsedBits 首次 remember 使用一次
checked `valueLogicalType` 读取原始宽度与 scalar/Logic 标志。全部检查仍执行，
aggregate shape 的复制成本保留在测量中。独立
[复核](../../ptmp/firrtl-ingest/F32/phase6-tools/opt-v4-independent-review.md)无阻塞，
[联合20/20](../../ptmp/firrtl-ingest/F32/phase6-opt-v4/tests/test.log)通过，已安装并冻结。
本轮没有继续叠加未经测量的 UsedBits 改动。

恢复时通过宿主机进程表确认旧 `phase6-opt-v4` 诊断已没有活跃进程；其仅到
ingest、guard 零样本的过期 running 文件保留原样，不视为完成。新
`phase6-resume-v29` 被 guard 在 ingest 终止：父 cgroup PSI some 53.99%，持续
8.222 秒，RSS 11,102,232,576 bytes，未进入窗口。
[缓存释放v2](../../ptmp/firrtl-ingest/F32/phase6-tools/closed-capture-cache-release-v2.json)
后空闲内存约25→104 GiB；同包 retry 完成 ingest 246.125秒后在 hier-flatten
再次触发保护：PSI some 33.21%，持续8.038秒，RSS 80,848,371,712 bytes。
两次失败均有原始 summary、guard 和逐样本资源记录，不计有效性能样本。

随后对20个已关闭且guard终结的捕获目录执行
[缓存释放v3](../../ptmp/firrtl-ingest/F32/phase6-tools/closed-capture-cache-release-v3.json)：
264个文件、650,890,339,487 bytes，无错误，空闲内存升至约152 GiB。
操作仅为 `POSIX_FADV_DONTNEED`，未删除证据或更改系统缓存设置。
同一 package-v29、CPU2、96GiB RSS / PSI25%8秒、SplitNodes180秒守卫的
`phase6-resume-v29-retry2/profile-window-full` 已完整正常退出，guard returncode=0，
2085个资源样本，峰值RSS 82,540,388 KiB。原生 ExprOpt / UsedBits / SplitNodes /
第二DCE分别为 **5.699700710 / 16.401229077 / 101.769180584 / 25.482129303秒**。
UsedBits采样无丢失，validator18.14%、simplifyUsedBits16.97%、opKind及opOperands
各6.83%、opResults4.43%独占。这些是单轮诊断，未组成正式中位数；不能从各项和
推定连续窗口验收。失败记录继续保留，也不放宽资源或性能门。

恢复后通过 Make 重验工具合同：runner **8/8**、comparator **20通过/1 skip**、
guard **19/19**；日志见
[resume-tool-tests.log](../../ptmp/firrtl-ingest/F32/phase6-tools/resume-tool-tests.log)。
skip 是须显式指定组路径的可选真实样本检查，不计为通过。随后指定原首组
`F32_PERFORMANCE_RUNNER_GROUP=.../phase6-v1` 重验 **21/21、零skip**，见
[resume-actual-tests.log](../../ptmp/firrtl-ingest/F32/phase6-tools/resume-actual-tests.log)。
该只读检查接受组中实际成功的四个样本的schema/hash/guard合同，不把失败的
两轮GRH变为有效样本，原组仍未通过。

#### 9.34.3 package-v30 的 operation 输入视图实验（2026-11-18，已撤回）

新增 `Graph::opInputs`，复用既有 operation ID/存活检查，一次读取 kind 与
有序 operands/results span。边列表不复制，不新增 generation 规则，不代替
ValueId 检查；任何图修改后视图失效。UsedBits 仅在 dense sizing、remember、
sink seeding 和 queue propagation 四个只读位置使用。未跨 narrowing/repair
修改保存 span，Scope、effects、定点传播、Node/binding、验证及保留成本不变。

[联合21/21](../../ptmp/firrtl-ingest/F32/phase6-opt-v5/tests/test.log)通过，包含新
`grh-op-inputs` 的有序重复边、空边、多结果、借用与修改后重取及各类错误ID
诊断。经 `make py_install` 安装并冻结
[package-v30](../../ptmp/firrtl-ingest/F32/package-v30/identity.json)，source content
SHA为 `33577af5384412441ec71534f26fec9925dbc94629ce6f932268f32d238018a2`。
独立完整原始输入[诊断](../../ptmp/firrtl-ingest/F32/phase6-opt-v5/profile-window-full/summary.json)
已正常退出，guard returncode=0，2093个资源样本，峰值RSS 83,188,368 KiB。
四项原生 timer 为 **5.425728913 / 16.920045810 / 101.358646908 / 26.004685899秒**。
UsedBits较v29单次诊断高0.519秒；单次采样不证明因果或正式回退。
零丢失采样中 `opInputs` 独占14.82%，其余kind/operands/results合计7.62%。
[冻结二进制ABI审查](../../ptmp/firrtl-ingest/F32/phase6-tools/opinputs-abi-review.md)
确认40-byte内存返回及调用方重载，前两个扫描还读取未使用的kind；没有证据
证明收益。因此工作树撤回该API、四处替换及专属测试/文档，v30包、测试、
profile和反汇编证据全部保留。没有把大结构换成显式output指针并宣称消除ABI成本。
冻结v30仍可通过以下入口复现：

```bash
WOLF_ENV_SOURCED=1 make --no-print-directory profile_f32_used_bits \
  PYTHON=.venv/bin/python F32_WORK=ptmp/firrtl-ingest/F32/phase6-opt-v5 \
  F32_PACKAGE=ptmp/firrtl-ingest/F32/package-v30 \
  F32_USED_BITS_PROFILE=ptmp/firrtl-ingest/F32/phase6-opt-v5/profile-window-full \
  F32_USED_BITS_PROFILE_ARGS=--finish-window
```

#### 9.34.4 package-v31 的局部查询复用（2026-11-18）

相对v29仅保留两类局部优化：SemanticTree validator的forward operation/anchor
成员在原有nonzero/range/generation/alive守卫后读取已验证row的语义Range，
保留完全相同的offset/count越界检查、空Range检查及诊断；短于64的owner列表
直接使用原有线性搜索，较大列表仍保留cache与fallback。reverse扫描、名字、
重复、计数、边界和no-tree路径不变。UsedBits的state reference扫描共用一条
AttrRange并借用字符串，保持regSymbol优先、类型错误、空值和未决target行为；
narrowing每次迭代复用当前results/kind，span均在修改前消费，repair仍重新读取。

[联合20/20](../../ptmp/firrtl-ingest/F32/phase6-opt-v6/tests/test.log)通过（4.84秒），
包含0/63/64 owner、forward重复/错误generation/越界/erased成员的完整诊断顺序，
以及双Node模式共26项state reference拒绝/优先级/eligibility/latch回归。
[独立源码审查](../../ptmp/firrtl-ingest/F32/phase6-tools/v31-final-review.md)未发现
相对冻结v29的正确性阻碍，不证明全量语义或收益。
已安装并冻结[package-v31](../../ptmp/firrtl-ingest/F32/package-v31/identity.json)，
source content SHA `b3fef4403819858259b38e7f32c623bf8badaa8834ac8b95d51ae8f74325e166`，
依赖content SHA不变。此前启动的
[完整诊断](../../ptmp/firrtl-ingest/F32/phase6-opt-v6/profile-window-full/summary.json)
已正常结束，guard completed、returncode=0，2076个资源样本，峰值RSS
82,437,816 KiB。ExprOpt / UsedBits / SplitNodes / 第二DCE 的原生耗时分别为
**5.103925285 / 15.736832943 / 100.892530492 / 25.640234749秒**；ExprOpt 取同目录
`timings/expr-opt.jsonl`，其余取 summary 中原生 timer。守卫、CPU2、原始输入与
P4停止点不变，仍非正式性能样本。用户已接受性能，不再据此启动优化或新测量组。

### 9.35 阶段 7 支持矩阵与保留限制

本节是当前实现的支持和证据清单；F32.7 按用户初步接受的范围收尾，
`semantic_acceptance=false` 保留。最终接受决定见 §9.36；临时审查稿不替代本文。

| 项目 | 当前实现与已测范围 | 限制与未证明事项 |
| --- | --- | --- |
| 流水和 gate | 原始 FIRRTL prefix 后 ExprOpt / UsedBits / SplitNodes / 第二 DCE；新树与 CombArrayUpdate 在支持窗口可用，后续不支持 pass 在修改前拒绝 | 不宣称后端、ConstantAnalysis、转换或整机 flow 已支持新模型；扩展完整 flow 有既有窗口外 gate 失败 |
| 二值入口 | 三个窗口 pass 可显式选 2state，当前生产入口和 capture 选择该模式；X/Z 按 0，类型/来源身份保留 | 直接 API 默认兼容 4state；历史未声明模式的 capture 不回填标签；U3 不属于当前二值行为门 |
| ExprOpt | 深 DAG 迭代结构比较，包含有序 operand、完整类型和功能属性；相同分支 Mux 转 Assign，维护真实 surviving source slot；不隐式 DCE | 局部 oracle 和身份回归通过；严格小流水仍有 3 个新增未证明结果，不能宣称全量 Node 语义通过 |
| UsedBits | scalar prefix、状态/效果/端口观察、2state 算术低位需求、数组逐 cell 区间、有序更新逆向覆盖与重建、普通寄存器数组逐叶缩宽 | 动态读展开至多 256 blocks，改变 stride 至多物化 65,536 cells/value；随机多 cell stream、不支持 tiling/source geometry 保留原布局；不是全图增长总预算 |
| memory / state | FIRRTL memory reader 保留全宽需求；状态写的 payload/mask、事件与初值有局部回归 | 小图 sampled-state/event oracle 不替代实际全量状态/外部效果证明；缺失来源端点保持 unknown |
| SplitNodes | unsigned scalar pure expression、CombArrayUpdate 静态投影及支持的动态控制；GSIM cut/reference 策略；独立 scalar register families 的 current/next、writer/event 同步 | signed expression、random 或 shaped state families 不暴露未支持的 cuts；whole observer 只重组所需范围，不能将静态成本估计称为运行频率 |
| Node 生命周期 | 拆分退休父，分配新 child 身份、命名与实际 slice lineage；真实 op/operand witness；DCE 独立回收 | 物理/序列化 ID 映射仅证明身份，不能从名字补 source geometry/current-next；U4 原始来源合同缺口仍在 |
| 性能修复 | 借用较小边界索引、反向 owner 索引、focused dependency、producer component memo；full ValueId、target owner 与 rewrite/state/revision 失效受控；v31 validator/UsedBits 局部查询复用 | v31 单轮诊断 UsedBits / SplitNodes 为15.737 / 100.893s；UsedBits仍慢于历史GSIM。用户接受当前性能并停止优化；正式组仍有效GRH1/GSIM3、未通过，必要维护保留在计时内 |

v31 原生联合[20/20回归](../../ptmp/firrtl-ingest/F32/phase6-opt-v6/tests/test.log)通过；
更早的[17/17回归](../../ptmp/firrtl-ingest/F32/split-fix-v4/tests/test.log)及
[focused SplitNodes](../../ptmp/firrtl-ingest/F32/split-fix-v4/final/split-nodes/tests/test.log)
亦保留。局部整数算术 56,140 个预期输出与 4,013 项身份/槽位检查证明其各自有限
fixture，不证明完整实际运算锥或所有 Node/effects。严格小流水
`two-state-v5/pipeline-comparison/summary.json` 仍有 23 个未证明配对和 50 个
不完整 source-geometry endpoint；全量 P4 目前只有完整名称库存比较。

针对这3个新增结果，已用原 package-v20 小流水捕获建立
[sameArms只读台账](../../ptmp/firrtl-ingest/F32/phase7-audit/dead-member-ledger/summary.json)：
P0 的 `kNot` 成员通过实际 Mux operand slot2 可达；P1 将该 Mux 改为 Assign
并丢弃 slot2 后，该成员在P1–P3仍存在，但输出没有物理消费者、anchor或边界引用，
P4第二DCE才删除。SemanticNode9五界均存在。台账校验原始捕获hash、序列化到
原生ID映射、同run/graph和冻结源码，未将序列化编号当作跨界身份。
这说明具体残留成员的产生与回收过程，符合显式DCE边界；没有演化trace证明
每次中间身份修改，且原始source geometry仍unknown。strict reader的23个
未证明结果和 `semantic_acceptance=false` 保持原样，不能外推至v29或完整设计。

U1（GSIM 第二个外部 Clock 方向/绑定）、U2（unused guard 共享常量 membership）、
U4（新树原生 source provenance）保持未批准、未应用。U4 的 artifact catalog-only
提议补丁未编译、未测试，且不能单独补齐 endpoint；完整范围见 §10。
本次转入阶段 6、7 没有替代这些前驱问题所需的独立批准。

[全量比较可行性复核](../../ptmp/firrtl-ingest/F32/phase7-audit/next-action-review.md)
确认当前完整 GRH capture-v20 明确 `2state`，完整 GSIM capture-v4 没有模式标签，
当前 reader 会在创建新输出前拒绝配对。不得回填旧捕获标签。当前可用磁盘约61GiB，
历史主库存DB自身为92GiB，结构索引每界约25GiB；`--structure-node-limit` 不限制
完整库存/结构建库成本。故未启动新的全量比较或删除冻结证据。小例重跑不能
证明package-v31或补齐实际全量来源；新捕获身份和充足空间仍是全量比较前提。

上述完整新鲜交错样本、五项性能门和实际全量差异/来源/Node退休及state/effect
证明作为未完成的正式验收项保留。用户已接受本轮结果，不继续这些工作；若未来
重开正式验收，应冻结届时版本并重新组成完整配对组。保留F31和当前冻结捕获、
失败、库存/SQLite差异证据；本次收尾不删除这些记录。

### 9.36 F32 按用户初步接受收尾（2026-11-18）

用户先明确接受当前性能并要求停止性能优化，随后在了解第二次DCE的Node数量
与差距尚未逐项归因后，要求“先初步接受这个结果，完成F32的文档更新然后提交”。
本轮据此完成文档和实现提交，停止本轮性能优化及进一步差异追查；接受范围仍为
显式`semantics=2state`的P0→ExprOpt→UsedBits→SplitNodes→第二DCE/P4。
不扩展到ConstantAnalysis或后端，不将人工接受改写为严格全图语义证明通过。

#### 最终实现与测量身份

保留实现为package-v31（source content SHA见§9.34.4），v30 operation输入视图
实验已撤回。v31原生联合20/20通过并完成独立审查；提交前的最终回归记录见下。
完整五界Node库存仍来自package-v25的GRH capture-v20与历史GSIM capture-v4，
不能把它标记为v31重新导出的库存，也不回填历史GSIM的语义标签。

| 四阶段原生计时（秒） | v31单轮诊断 | 历史GSIM三轮中位数 |
| --- | ---: | ---: |
| ExprOpt | 5.103925285 | 25.243053675 |
| UsedBits | 15.736832943 | 9.242198681 |
| SplitNodes | 100.892530492 | 100.283722185 |
| 第二DCE | 25.640234749 | 39.410537602 |

v31数据见[诊断汇总](../../ptmp/firrtl-ingest/F32/phase6-opt-v6/profile-window-full/summary.json)
及同目录原生timings；GSIM见
[首组性能报告](../../ptmp/firrtl-ingest/F32/phase6-report-v1/summary.json)。用户接受性能时
已查看的v29四项为5.700/16.401/101.769/25.482秒；v31是此前已启动诊断的补记，
没有再开启性能流程。正式组仍只有1个有效GRH与3个有效GSIM，另两次GRH前驱PSI
失败，不满足原定样本数；该报告未通过的状态保持原样。

#### 第二次DCE与最终Node库存

| 边界/变化 | GRH capture-v20 | GSIM capture-v4 |
| --- | ---: | ---: |
| P0：第一次DCE后 | 5,635,530 | 6,020,694 |
| P3：SplitNodes后、第二DCE前 | 5,647,014 | 6,043,532 |
| P4：第二DCE后 | 5,625,297 | 5,922,045 |
| 第二DCE删除（P3−P4） | **21,717（0.385%）** | **121,487（2.010%）** |

原始计数见[GRH汇总](../../ptmp/firrtl-ingest/F32/capture-v20/grh/summary.json)与
[GSIM汇总](../../ptmp/firrtl-ingest/F32/capture-v4/gsim/summary.json)。两端P0已差385,164个Node；
SplitNodes净增分别为11,484与22,838，P3差396,518。第二DCE的删除量差99,770，
P4仍差296,748。此算术分解不能证明GRH漏删或把全部差距归因为提前删除。
已有[小例](../../ptmp/firrtl-ingest/F32/unused-producer-probe/review.md)验证删除时机及
待删Node先拆分再回收的机制，但整机99,770个差额尚未逐项归因。

P4中5,604,205个GRH Node有唯一GSIM同名候选，占GRH **99.62505091%**；
GRH/GSIM未配对分别为21,092/317,840。该值是名称库存对应率，不是行为等价率。
见[完整P4库存](../../ptmp/firrtl-ingest/F32/split-fix-v4/P4-inventory/summary.json)。

#### 保留限制与提交验证

严格全图语义门未通过。严格小流水仍有23个未证明配对、50个不完整来源端点与
3个新增未证明结果；小例死成员台账不替代完整来源与Node/effects证明。
U1/U2/U4未批准、未应用；U3的四态问题不属本轮二值行为验收范围。
本次用户接受当前结果，不包含对这些前驱修复的批准。完整支持矩阵和未证事项
见§9.35，原始失败报告、冻结包、捕获、索引与差异台账均保留。

提交前通过既有Make目标统一复核，未新跑性能组或整机捕获：

| 检查 | 本次结果 | 日志 |
| --- | --- | --- |
| `test_f32_passes` | **20/20通过**，4.83秒 | [原生联合回归](../../ptmp/firrtl-ingest/F32/final-acceptance/native/tests/test.log) |
| GSIM `test-post-dce-semantic-nodes` | 通过；五界、35项oracle、6条slice、3项负例及4项partial assignment | [GSIM汇总](../../ptmp/firrtl-ingest/F32/final-acceptance/gsim/summary.json)、[driver](../../ptmp/firrtl-ingest/F32/final-acceptance/gsim-test.log) |
| 11组F32工具合同、resource guard、F31 pipeline | **312项运行，309通过，3项可选集成跳过，0失败**；其中package-v31的F31 pipeline **7/7** | [工具driver](../../ptmp/firrtl-ingest/F32/final-acceptance/tool-regression-driver.log)、[各组结果](../../ptmp/firrtl-ingest/F32/final-regression-result.md) |
| `test_xs_firrtl_workflow`扩展范围检查 | **81/85通过，4项失败**，不计全套通过 | [XS工作流](../../ptmp/firrtl-ingest/F32/final-acceptance/xs-firrtl-workflow.log) |
| 三仓库diff空白检查 | 通过 | `git diff --check`，主仓库、wolvrix及reference/gsim |

三项跳过是可选原生GSIM wrapper、partial/null-slot及HEAD/TAIL/DSHR集成，不计为通过；
独立GSIM专项已如上运行。性能合同21/21使用实际phase6-v1组验证证据处理，不改写
正式性能门。XS四项失败涉及旧`semanticIds`序列化断言、窗口外`mux-tree-fold`与
`constant-analysis`新树gate，以及旧nonsink checkpoint配置；此前§9.32已记录这组
扩展flow限制。本轮保留失败，不扩大支持边界或修改前驱以让整套后端检查变绿。

原生回归入口为：

```bash
WOLF_ENV_SOURCED=1 make --no-print-directory test_f32_passes \
  F32_WORK=ptmp/firrtl-ingest/F32/final-acceptance/native
```

工具检查使用主Makefile的`test_f32_*_contract`、`test_f32_inventory_report`、
`test_f30_resource_guard`与`test_f31_pipeline`；输出统一位于
`ptmp/firrtl-ingest/F32/final-acceptance/`，F31_PACKAGE指向冻结package-v31。
GSIM检查使用其Makefile的`test-post-dce-semantic-nodes`，复用
`ptmp/firrtl-ingest/F32/gsim-dev/build`并将POST_DCE_TEST_OUTPUT指向上述final-acceptance/gsim。
用户要求的本地提交包含两个子模块实现/测试及主仓库工具、文档和子模块指针；
不提交ptmp运行产物，不执行推送。

| 子模块 | 本次提交 | 内容 |
| --- | --- | --- |
| wolvrix | `87aeeab` | F32新树/组合数组更新、四pass支持、二值入口、局部查询优化和回归 |
| reference/gsim | `f59b7d7` | 五界原生捕获、身份/ExprOpt与零宽引用修复、计时和专项回归 |

主仓库本节所在提交同步上述指针、工具、Make入口与文档。运行身份仍以原冻结包
和capture中的完整hash为准；提交号不用于回填或更改历史测量身份。

## 10. 前驱人工审核项

### F32-U1：GSIM extmodule 第二个 Clock 端口丢失方向和输出绑定

状态：**已复现、未获批准、未应用修复**；属于 P0 继承项，不能放进窗口内补丁。

复现 fixture 为
[`post-dce-secondary-clock.fir`](../../reference/gsim/test/post-dce-secondary-clock.fir)：

```firrtl
extmodule TwoClocks :
  input clock : Clock
  output tck : Clock
  defname = TwoClocks
```

实例的输入 clock 接顶层 clock、输出 tck 接顶层 tck。正常原生 prefix 到第一次
DCE 后，`ext.tck` 仍 `isClock=true`，但 kind 为 `NODE_OTHERS` 且没有输出
assignment tree，public exchange 报 `unsupported_native_external_port_direction`。
原始 JSON 和库存见 `gsim-dev/secondary-clock-evidence/`；完整香山每边界的
同类项为 `SimJTAG.TCK`。

依据 `AST2Graph.cpp::visitExtModule`，遍历 ext ports 时只记录首个 clock 到
`extNode->clock`，把后续 clock 的 type 改为 `NODE_OTHERS`，且所有 clock
均不加入 member。随后构造外部输出值只遍历 member，故第二 clock output
还会缺少真实 `OP_EXT_FUNC` 输出绑定。不能仅在 exporter 用 `isClock` 猜方向，
也不能只恢复字符串就声称执行语义修好。

建议审核后单独修改：在 port 建图时保留原始方向；将外部参数/端口顺序和
执行用主 clock 分开；按真实方向对包括额外 clock output 在内的全部端口构造
外部绑定，审查 `clockOptimize` 对这些输出/下游状态的模型。受影响边界从
ingest/P0 开始，须更换基线并重验 F31 继承项，不能把新旧 P0 混合比较。

建议验证至少包含额外 clock input/output 两种顺序、两个 output clock、非 clock
普通端口回归、JTAG 下游状态/事件，以及真实外部模型驱动第二 clock 时的输出
与采样行为。当前只提交复现和建议，不实施此前驱语义变化。

### F32-U2：ingest 未使用的 guard(1) 请求使共享常量多归属

状态：**实际小图已定位、未获批准、未应用修复**；属于 P0 继承的 membership
问题，不通过 F32 清扫把它隐藏。

同一个实际 smoke 的 `low/high/regLow/regHigh/collision` 五个输出 Node 的
anchor 表达式都闭合，但成员中多一个共享 `1'b1` 常量。P0 为 op11/value18，
真实用户仅 state writer op12 的 enable slot0；P4 为 op7，真实用户为拆分后
writer op22/op24。该常量不能物理删除，问题在于五个输出并未使用却被列为 owner。
证据为 `comparison-smoke-final-v2` 的 `owned_operations_not_reached_from_anchor`
及对应 `capture-smoke-v1/grh` 原生物理图。

定位在 `ingest/firrtl/lower.cpp`：静态无条件 connect 先调用 `guard(1)`，
`guard()` 立即记录当前 Node 为该缓存 guard 的 consumer；随后 whole connect
直接使用 data、不消费 enable，`finishGuardSemantics()` 仍把常量归属给所有
曾请求 guard 的 Node。建议审核后将 consumer 登记推迟到真实使用 enable 的
位置，或在确认无条件 whole connect 后避免请求 unused guard，保持需要该
guard 的 writer/条件赋值真实归属。

建议验证无条件 whole connect、conditional connect、数组 partial update、
共享 guard 的真实/无关用户及 F31 库存/来源闭合。若应用会从 ingest 起改变
membership，须单独批准并重验 P0；目前窗口保留并登记该继承问题。

### F32-U3：公共四态条件求值丢失部分相同 Z 位

状态：**底层函数已直接复现，生产调用链已定位；未获批准、未应用前驱修复**。

GRH [Mux 合同](../../wolvrix/docs/grh/grh-ir.md#627-数据选择kmux) 规定未知
selector 时逐位融合，相同 Z 位保留 Z。最小输入为 `mux(1'bx, 2'bz0, 2'bz1)`，
规范结果为 `2'bzx`。本轮
[原生测试诊断](../../ptmp/firrtl-ingest/F32/native-v24-budget-reshape/tests/last-test.log)
直接记录 vendored `SVInt::conditional` 返回 **`2'bxx`**：其整向量不完全相同
时，将任一分支未知的位都设为 X，丢失了相同的 Z 位。

生产 `lib/transform/const_fold.cpp` 的 Mux 常量折叠和
`lib/core/comb_array_update.cpp` 的叶内更新求值均调用该公共函数。
后者的最小等价数组输入是单叶 base=`2'bz1`、enable=`1'bx`、payload=`2'bz0`；
正常有序更新应为 `2'bzx`。这两个调用在 F32 窗口前已存在，更名未改变求值
语义；修公共函数或 helper 会影响前驱，须按 §1.2 单独审核。

本轮仅修正 **test-only oracle**：以 `logic_t` 逐位读取，四态相同则保留该位，
否则设 X；避免一位 signed `SVInt` 比较的符号扩展干扰。
新增 mixed-Z Mux 真值表和 unknown-enable 数组更新的 P0/P3/P4 独立位预期，
联合13/13通过。这不表示生产公共求值器已经修复。

建议审核后统一公共逐位融合实现，覆盖已知/未知 selector、相同 Z 且其他位
不同、signed/unsigned、多字宽值，以及 const-fold、组合数组更新和前驱 P0
回归；保留原始 F31/F32 捕获，只有明确批准后才能更换基线。

<a id="f32-source-provenance-gap"></a>

### F32-U4：新 Node 模型缺少原生 source provenance 合同

状态：**原始 ingest 与每个 prefix 已复现；未获批准、未应用前驱修复**。
这使 §14.4 的真实保留投影证明缺少必要输入，不将缺口归因于窗口内 UsedBits。

只读复现使用冻结 package-v14；
[诊断结果与输入/包/artifact hash](../../ptmp/firrtl-ingest/F32/U4-source-provenance/summary.json)、
[最小直连输入](../../ptmp/firrtl-ingest/F32/U4-source-provenance/minimal.fir)、
[状态数组输入](../../ptmp/firrtl-ingest/F32/U4-source-provenance/state-array.fir)、
[原始 ingest 请求](../../ptmp/firrtl-ingest/F32/U4-source-provenance/state-array/ingest-request.json)
与 [Make 复现入口](../../ptmp/firrtl-ingest/F32/U4-source-provenance/Makefile)
保留在同一 artifact 目录。诊断从原始输入分别观察 ingest、xmr-resolve、
hier-flatten、comb-loop-elim、split-static-array 和第一次 DCE：

| 原始输入 | ingest 及前三个 prefix | split-static-array / 第一次 DCE |
| --- | --- | --- |
| `a:UInt<8>` 直接连 `y:UInt<8>` | 每界2条 `anchor-candidate` | 每界2条 `anchor-candidate` |
| 六个8-bit cell的寄存器，含普通写和reset写 | 每界5条 candidate及1条operation-only | 每界22条 `anchor-candidate` |

全部12个边界 `semantic_validate.valid=true`，但所有 candidate 的
`source_width/source_bit_width=-1/-1`。两例
[直连原始detail](../../ptmp/firrtl-ingest/F32/U4-source-provenance/minimal/ingest-details/node-details.jsonl)、
[状态原始detail](../../ptmp/firrtl-ingest/F32/U4-source-provenance/state-array/ingest-details/node-details.jsonl)
都以完整 requested-node/legacy-binding 范围报告 `bindings=0`。
状态例实际存在两个有序 writer、clock operand、reset使用及state_update边；
无anchor的 `r$NEXT` 被exchange导为operation-only，`source_width=0`只是占位，
不证明原寄存器源宽为零。结构验证通过不能补出缺失的源几何。

这并非简单漏调旧 `addSemanticBinding`：
[F28 §6](F28-semantic-tree-refactor-plan.md#6-核心与持久化迁移)
明确将旧bindings移出新模型创建、验证和统计主路径；
`tests/ingest/test_firrtl_semantic_tree.cpp::requireCovered` 还明确要求
`semanticBindings().empty()`，防止恢复retired schema。
`Lowerer::run()`创建每个leaf时持有原始类型、shape与shapeFieldDepths，
但新SemanticNode只保存名字、path、members和anchors，没有原始源几何。
`semantic_exchange.cpp`目前仅从旧collection导出 `native-binding`；
新树anchors走空的临时binding而得到candidate。缺口已在任何prefix之前存在。

建议审核的是**新树原生provenance与全部维护路径**：原始leaf记录不可变的
源身份、ground类型/符号、leaf width、shape及field depths；当前endpoint另存
Node、真实value/op及generation、角色/operand或result slot，以及source轴和
逐leaf bit区间。membership与anchor不因补provenance而改变。状态current/next
须对应实际reader和每个有序writer，clock/reset须对应实际operand；不能用
`$NEXT`名字或first-owned-op猜造单一anchor。UsedBits按每cell保留前缀，
SplitNodes/array split按真实几何组合投影，未知或不支持项保持unknown。

[具体补丁范围、记录合同与回归建议](../../ptmp/firrtl-ingest/F32/U4-source-provenance/proposed-change.md)
覆盖Graph/tree API、clone/import/compact/erase/replace、store/load版本化、
exchange、FIRRTL及所有prefix、窗口维护和严格reader。完整U4仍没有可直接
应用的生产diff：动态writer区域、memory/effect角色、实例来源身份和endpoint
合同仍需分步实现与审核，不从名字或当前物理宽度反推原始来源。

现已另行准备**仅保存原始声明定义叶**的
[第一里程碑提议diff](../../ptmp/firrtl-ingest/F32/U4-source-provenance/proposal-leaves-v1/source-leaves.patch)
及[范围/回归报告](../../ptmp/firrtl-ingest/F32/U4-source-provenance/proposal-leaves-v1/report.md)。
七个生产文件的修改仅存在于artifact副本，补丁SHA-256为
`e9be4e723196e12b251b02447374951080ce41709571f0946c26cfc6947a80e3`，
562行/30,722 bytes；`git apply --check`通过，**未应用、未编译、未测试**。
独立强source ID的immutable catalog保存实际FIRRTL已推断声明叶的unit/circuit/
module、原始declaration/field tokens及ground/width/sign/shape/depths；相同
定义精确intern，冲突拒绝。实例来源明确unknown，不建立Node/value/op/writer
或endpoint关系；probe、实例代理、未决宽度及不在该声明路径的memory/effect
没有伪造记录。catalog随clone/compact/prune/Node退休保留，appendTree及真实
hier_flatten分别导入定义。它不能补全现有candidate的原始端点或关闭U4。

提议的两条writer均改JSON v6，严格loader读v5时来源为空/unknown，读v6时
检查新字段、整数ID/几何、重复定义和重复对象key。
[生命周期审查](../../ptmp/firrtl-ingest/F32/U4-source-provenance/proposal-leaves-v1/lifecycle-review.md)
及[持久化审查](../../ptmp/firrtl-ingest/F32/U4-source-provenance/proposal-leaves-v1/persistence-review.md)
仅为静态检查；catalog字符串开销、解析对象新增bool的layout/内存及v6全模式
roundtrip均未测量。现proof loader只收v5，会拒绝v6；此补丁不修改exchange、
reader或strict gate。它改变ingest/prefix metadata及格式，仍必须按§1.2单独
批准后才能应用，并以新包/P0重新验证，不能重标历史捕获。

审批后须验证scalar/signed/Bundle/多维数组/零宽、current/next/多writer/reset、
clock关系、层次导入与生命周期、所有JSON模式及坏输入拒绝，再冻结新包与新P0，
重验F31库存和所有prefix；U1/U2/U3保持独立继承项。当前不回填历史capture，
不放宽strict gate，也不将局部anchor值证明提升为source或完整Node验收。

<a id="f32-window-origin-audit"></a>

## 11. 窗口来源诊断

`scripts/audit_f32_window_origins.py` 是 F32.5 的独立诊断工具。它从已完成且
已关闭的比较库存中追踪同端 Node 的原生身份和真实 bit-slices，并列出仍需
证明的窗口事项。它不导入、不修改 `compare_f32_semantics.py`，也不修改
该比较器的严格 `semantic_acceptance` 门槛。

来源关系只能回答“这个当前 Node 从哪个原生 Node、哪个位区间产生”。
它不能证明 UsedBits、CommonExpr、SplitNodes 或 DCE 保持了值、FourState、
状态、初始化或效果语义。目前没有语义转换证书的导入和核验器，因此所有
报告都保持 `window_acceptance=false`、
`semantic_transformation_certificates_checked=0`。这表示证书能力缺失；
逐个 Node 列出缺失证书不表示每个转换都存在错误。这些条目包含工具尚未
实现的覆盖范围，不能把总条数作为新发现错误数或需要修复的事项总数。

### 11.1 输入与执行

输入目录必须包含锁定比较器的 `summary.json` 和 `comparison.sqlite`。
summary 必须是 `wolvrix.f32.semantic-comparison.v1`、`status=analyzed`、
`complete=true`，包含原始 FIRRTL SHA-256，以及 GRH、GSIM 各自的 P0–P4
五个快照。同一端五个快照必须共享一个非空 run_id，snapshot_id 彼此不同，
库存行数须与 summary 一致。

调用方须保证没有写入者。工具在打开数据库前拒绝 `-wal`、`-shm`、
`-journal`，使用 SQLite `mode=ro&immutable=1` 和 `query_only`，并在读取
前后核对数据库身份、大小、mtime、ctime、SHA-256 和 summary 原始字节。
这些检查不替代“输入已经关闭”的约定。工具不连接正在运行的比较数据库。

默认上限是每张表 10,000 行、数据库 64 MiB。可以明确提高上限来读取较大的
已关闭输入，不能把拒绝超限的结果记作完整审计。通过仓库 Make 目标运行：

```sh
make --no-print-directory audit_f32_window_origins \
  F32_ORIGIN_COMPARISON=ptmp/firrtl-ingest/F32/comparison-closed \
  F32_ORIGIN_WORK=ptmp/firrtl-ingest/F32/window-origin-audit-1
```

例如明确允许每表一百万行和 1 GiB 数据库：

```sh
make --no-print-directory audit_f32_window_origins \
  F32_ORIGIN_COMPARISON=ptmp/firrtl-ingest/F32/comparison-closed \
  F32_ORIGIN_WORK=ptmp/firrtl-ingest/F32/window-origin-audit-large-1 \
  F32_ORIGIN_ARGS='--max-rows 1000000 --max-database-bytes 1073741824'
```

输出目录须是仓库 `ptmp/` 内尚不存在的新目录。日志位于该目录同名的
`.log` 文件。失败时可能留下部分 JSONL，但不会发布成功的 `summary.json`。
工具不覆盖已有输出。

数据库行使用游标读取，JSONL 报告逐行写出，计数增量累计。身份、端点、
详情、切片和来源索引仍驻内存，空间随这些行数和 payload 大小增长；提高
上限须为这些索引预留内存。没有执行生产规模的容量或性能验收。

### 11.2 来源规则

| classification | 含义 |
| --- | --- |
| `unchanged-identity` | 同一端、同一 run 的原生 ID 连续存在，name、token path、native name 均保持。只证明身份延续。 |
| `producer-projection` | 新 Node 通过真实切片记录连到 P0 原生 ID，具有可组合的标量位区间。只证明生产者来源。 |
| `new` | 本边界首次出现该 ID，未提供可用的生产者 lineage。 |
| `unresolved-origin` | 名称缺失或变化、退休后复现、lineage 歧义或循环、几何不足等，不能完成来源关联。 |

P0 只能作为自身的身份起点，不能充当已经通过语义验收的基线。name 必须是
非空 token path 用 `.` 连接的当前 canonical name，native name 也须存在。
仅有名称相同或名称后缀相似不能建立来源。token path 原样保留，用来避免
把 canonical 字符串相同误解为 token 身份相同。

`slices` 的每条输入有以下字段：

| 字段 | 定义 |
| --- | --- |
| `engine` | GRH 或 GSIM 的独立原生身份空间。 |
| `stage` | 该关系出现的边界，P0–P4 编码为 0–4。 |
| `parent` | 生产者父 Node 的原生 ID。 |
| `child` | 本轮产生的子 Node 的原生 ID。 |
| `low` | 子 Node 的第 0 位在父 Node 中的起始 bit offset。 |
| `width` | 连续投影的位数，必须为正数且等于子 Node 的标量位宽。 |

本工具只接受首次在 P3 SplitNodes 边界发布的生产者投影。父 Node 必须在
P2 输入边界存在，或是同一 P3 内首次出现且有真实 lineage 的新 Node；更早
就已退休的 ID 不能作为 P3 输入。P4 累积携带的同一条关系按第一次发布
去重。缺少数组轴映射时不把数组当作标量处理。递归来源检查有 64 层预算，
超限保持 unresolved，不猜测来源。

例如 P2 中 `parent=7` 为 16 位，P3 发布
`parent=7, child=20, low=4, width=8`，则 child 20 的 P0 投影为
`{low:4,width:8}`。同一 P3 再发布
`parent=20, child=21, low=2, width=3`，child 21 的投影为
`{low:6,width:3}`。这些关系不要求子 Node 的名字具有特定后缀，也不证明
child 21 的逻辑表达式正确。

同一 ID 的物理类型变化会保留已经确定的身份祖先，但清空未由证据支持的
P0 bit 投影。例如 P0 为 16 位、P1 变为 8 位，不能直接假定 P1 保留原来的
低 8 位；后续子切片也不能凭这个假定组合 P0 坐标。

GRH 物理几何只取 `value_id>0` 且非 `operation-only` 的端点。只有
operation 的记录可能使用 `value_id=0,width=0,logic_domain=none`；这个 0
不是实际的零位宽 value。若父 Node 只有这种记录，其几何为未知，后续非零
宽子切片应记录 incomplete geometry 并保持 unresolved，不能诊断成越界，
也不根据 `state$NEXT` 等名称或 GSIM 同名节点补出父位宽或源 binding。

### 11.3 报告与待证明事项

`origins.jsonl` 每行记录一个端、一个边界、一个 Node。记录包含 run、snapshot、
当前名称和 token path、来源分类、P0 ID、可用的标量投影、实际 slice 行定位、
物理几何和源 binding 几何检查结果，以及原始库存/端点/详情表的 rowid。
`semantic_preservation_proved` 始终为 false。

GRH 的 `source_binding_geometry_checked` 只表示已记录的 v2 native binding
几何通过独立一致性检查：源位区间合法、保留轴与物理 shape 相符、叶子位宽
一致、source_signed 和逻辑域合法，并且有实际 value。它不证明完整 binding
语义或逻辑语义，也不把 anchor-candidate 提升为
binding。GSIM 的 node-details sidecar 没有提供对应的原始源 binding，报告
明确保留这个缺口；不从跨端同名关系借用 binding。

`window_obligations.jsonl` 逐行记录以下未关闭事项：

- P1–P4 每个存活 Node 的转换语义证书缺失。
- 每个相邻边界消失的原生 ID 的退休语义证书缺失，附上此前来源和实际发布的
  子切片；拥有子切片或发生 DCE 都不能自动证明退休安全。
- 来源、命名、物理几何和源 binding 几何缺口。
- 跨端同名 candidate 仍非 lineage 或语义证明；没有 candidate 的对应关系仍待证明。
- 上游每一条差异仍需来源和语义审查。相同 reason/key、差异数量减少都不能
  关闭差异，历史 slice 涉及的 ID 可以已经退休。

`summary.json` 使用 `wolvrix.f32.window-origin-audit.v1`，记录输入数据库与
summary 的 hash、原始 FIRRTL hash、上限、来源计数、未关闭事项计数、两个
JSONL 的 hash。`upstream_semantic_acceptance` 原样记录上游结果，
`upstream_gate_modified=false`。`obligations_are_error_count=false` 明确计数
包含工具覆盖缺口；`memory_model.resident` 明确列出驻内存映射，
`production_scale_validated=false`。默认上限或显式扩大上限均不构成生产规模
就绪声明。本工具不能把 F32.5 或后续阶段标记为完成。

### 11.4 验证范围

新增的独立 fixture 测试未导入锁定比较器。执行命令为：

```sh
WOLF_ENV_SOURCED=1 make --no-print-directory test_f32_window_origin_contract \
  F32_WORK=ptmp/firrtl-ingest/F32/window-origin-local \
  PYTHON=/home/gaoruihao/wksp/wolvrix-playground/.venv/bin/python
```

结果为 25/25 通过、零 skip。日志：
`ptmp/firrtl-ingest/F32/window-origin-local/tool-tests/window-origin-contract.log`。
覆盖身份和真实切片组合、同名新 ID、改名/缺名、位宽变化、节点退休、陈旧父节点、
歧义/循环/超界/超深 lineage、缺 binding、伪完整标记、畸形几何、非法
source_signed/逻辑域、运行中输入和
SQLite sidecar 拒绝、显式容量上限、输入不变性、流式读取后的连接关闭，以及
读取期间输入变化时不发布成功 summary。

补充回归复现了 closed v7 smoke 中 P0–P2 的 operation-only `state$NEXT`
端点及 P3 的两个 128 位子节点：父几何保持未知，子来源未解析，避免把未知
父位宽误报为 0 位越界；另覆盖非 value 记录与真实物理 value 混合时的选择。

本轮只读取自建的小型 fixture，没有读取生产比较数据库，没有执行全图
comparison 或 native build，也没有修改严格比较器及其测试。

<a id="f32-inventory-seed"></a>

## 12. 库存与结构索引复用

`scripts/seed_f32_inventory.py` 从一个已完成并关闭的比较缓存中复制明确选定、
静态行完全相同的 `(engine, stage)` 分区。它创建新的比较目录和当前运行的
`inputs.json`，随后由未修改的 `compare_f32_semantics.py --resume` 继续
当前输入的结构证明。它不修改锁定 reader，也不复用旧语义验收结论。

此工具采用与现有 reader resume 相同的缓存信任前提：原比较由相同的锁定
reader/dependency 实现完成，`inputs.json.inventory_complete=true`，
原缓存及其来源可信且已冻结。**它没有重新独立证明旧 SQLite 中的每一行都
对应原始 TSV**。receipt 明确记录 `independent_source_row_revalidation=false`
和这个信任边界；当前数据库 hash 固定的是本次采用的缓存身份，不能追溯
证明一个来源不明的数据库。

### 12.1 复用条件和数据边界

源比较须有 `status=analyzed, complete=true` 的 summary、完整 inputs
checkpoint，两者 snapshots 一致。checkpoint 的四份实现 hash 必须与当前
`comparison_identity()` 一致：reader、F28 normalizer、bitvector 和 exchange
验证器。原 capture summary 必须仍匹配该 checkpoint 的冻结 hash。原比较、
新 GRH 和新 GSIM 的原始 FIRRTL SHA-256 必须一致。

源数据库不能有 `-wal`、`-shm` 或 `-journal`。使用只读 immutable SQLite
attachment，目标使用新文件，不改源数据库。源数据库和 summary/inputs/
capture summary 在本次工作前后检查完整 SHA-256 及 dev、inode、size、mtime、
ctime；发现变化则不发布完整 checkpoint。

每个选定分区检查以下四份 TSV：

| engine | 必须同时一致的文件 |
| --- | --- |
| GRH | nodes、connections、node-endpoints、bit-slices |
| GSIM | nodes、connections、node-details、bit-slices |

新旧文件各自须匹配其 capture artifact 的路径、全文 SHA-256 和 bytes。
新旧首行 `#meta` 各自按 reader 的 schema/identity/header 规则核对，不把旧
身份替换到新输入中。每端五个边界的当前 run_id 必须相同、snapshot_id 必须
互异；其他 sidecar 的身份须与本边界 nodes 一致，具体字段遵循 reader 的
对应 sidecar 契约。

只允许第一行 `#meta` 不同。其余 **header、所有行和 footer 必须逐字节
相同，顺序、换行和 JSON 空白也必须相同**。工具用固定大小 chunk 同时比较
原始字节并计算全文/body hash，不把 JSON 解析成对象后比较，不进行名称、ID
或 payload 修补。footer 行数与原始换行数一致，源 Node/footer 元数据还须与
原完成 checkpoint 的 snapshot 记录一致。任意 body 差异都是 reuse miss，
该分区调用原 `ingest_snapshot()` 正常解析。

例如旧文件和新文件分别为：

```text
#meta {run_id:old, snapshot_id:old-P0, ...}
node_id  name_path_json  native_name
7        ["result"]     result
#footer {complete:true,rowCount:1,nodeInventoryComplete:true}
```

```text
#meta {run_id:new, snapshot_id:new-P0, ...}
node_id  name_path_json  native_name
7        ["result"]     result
#footer {complete:true,rowCount:1,nodeInventoryComplete:true}
```

上面是省略 TSV 转义和 JSON 引号的示意。若首行分别通过各自身份核对，下面
三行完全一致，可复用静态行，但新 checkpoint 必须记录 `new/new-P0`。若把
`result` 改名、改 ID、改 footer 空白，均不得复用这个分区。

只复制五张原始主表的相关分区：`inventory`、`connections`、`endpoints`
（GRH）、`details`（GSIM）、`slices`。每个分区实际复制其中四张表，列和
row count 必须与 reader schema 和源 TSV footer 一致。endpoint 的 ordinal
依赖行顺序，因此不能只做无序集合比较。

这些主表没有显式的 run/snapshot/capture 路径列。endpoints/details payload
来自对应的 TSV 行，并由同一 reader 确定性归一化；这些行的实际字段也不能
修改。若未来 payload 嵌入运行身份或来源路径，导致 body 不同，就正常 ingest，
不能先去掉这些字段再复用。

未请求和未命中的分区都调用当前 reader 的 `ingest_snapshot()`。全部主表
就绪后，重新执行原 `derive()`、`lifecycle()`、`slice_geometry()`。
`pairs`、`types`、差异、结构/状态证明、诊断和 anchor proof 都从新库产生；
跨边界检查能观察本轮 P3/P4 的变化。源库中的旧 derived/proof 行不会复制。

### 12.2 输出与后续证明

默认请求 `grh:P0 grh:P1 grh:P2`，但是否命中完全取决于实际字节检查，不能
因为本轮只改 SplitNodes 就假定前缀相同。只通过项目 Make 入口执行：

```sh
make --no-print-directory seed_f32_inventory \
  F32_SEED_SOURCE=ptmp/firrtl-ingest/F32/comparison-old-closed \
  F32_COMPARE_GRH=ptmp/firrtl-ingest/F32/capture-new/grh \
  F32_COMPARE_GSIM=ptmp/firrtl-ingest/F32/capture-new/gsim \
  F32_SEED_WORK=ptmp/firrtl-ingest/F32/comparison-new-seeded \
  F32_SEED_REUSE='grh:P0 grh:P1 grh:P2'
```

源比较必须在这整个工作期间保持关闭、冻结；不要同时对它启动 proof resume。
输出必须是仓库 `ptmp/` 内的新目录，不覆盖原结果。成功时输出为：

- `comparison.sqlite`：新主表、全新 derived 行，无旧 proof。
- `inputs.json`：真正的当前 `comparison_identity()` 和当前 sidecar 的
  run/snapshot/count/coverage；完成封存后才设 `inventory_complete=true`。
- `seed-receipt.json`：`wolvrix.f32.inventory-seed.v1`，记录源 DB 和原 marker/
  summary 的完整 hash 与前后 stat、所有请求分区的旧新 TSV artifact、全文
  hash、body hash、metadata、前后 stat，以及命中/正常 ingest 分区和缓存信任说明。

成功 receipt 先原子发布，完整 checkpoint 最后发布；即使在两个发布步骤间
中断，也不能留下缺 receipt 却允许 resume 的缓存。

seed 不发布语义 `summary.json`，`semantic_acceptance_evaluated=false`。
开始写新库后若失败，receipt 标为 failed，checkpoint 保持不完整，不能 resume。
检查通过后，可直接用原 Make 目标先做当前 P0 小批次：

```sh
make --no-print-directory compare_f32_semantics \
  F32_COMPARE_GRH=ptmp/firrtl-ingest/F32/capture-new/grh \
  F32_COMPARE_GSIM=ptmp/firrtl-ingest/F32/capture-new/gsim \
  F32_COMPARE_WORK=ptmp/firrtl-ingest/F32/comparison-new-seeded \
  F32_COMPARE_ARGS='--resume --structure-stage P0 --structure-node-limit 2'
```

原 reader 会重新检查当前冻结 artifact，建立当前原生结构索引并做证明。seed
不会更改任何严格验收门槛，也不能单独标记 F32.5 完成。

<a id="f32-structure-reuse"></a>

### 12.3 结构索引的设计边界

库存 seed 本身不复用结构索引。独立的现有 `index_f32_structure.py` 入口新增了
窄 `--reuse-from`，仅用于 P0–P2 已完成、未用于比较证明的预建库。GRH 与 GSIM
两份当前原生 JSON 的完整 bytes/SHA 各自必须与旧 marker 相同；当前 capture
须 completed、原始 FIRRTL input SHA 相同，并满足当前冻结 artifact 合同。
旧 marker 只含 schema、双端路径/hash/bytes 和 counts，没有独立绑定 builder
hash 或数据库 hash。因此仍须信任原生 builder 来源及其实现兼容性；此工具保留
reader 原有的 closed-cache trust，不宣称独立重推了所有 cached raw rows 或
重数了 marker counts。reader 当前的 derive/slice SQL 索引优化不改变原生
`structure_index()` builder；这项兼容性核查独立于文件级 reader SHA。

结构 SQLite 没有显式 capture run/snapshot/path 列，但原生 payload 内的路径
也是必须保持的输入内容。新目录须重建 marker，绑定当前 JSON 路径，并在复用
receipt 中记录当前捕获身份。已有 `compare_structure()` 会重写 `pairs`，
checker 还会写 `native_type_evidence` 和 `disconnected_members`；因此不能
直接把旧库硬链接给新比较。新入口使用 `cp --reflink=auto --sparse=always`
建立不同 inode 的复制/CoW 副本。三张可变表只要任意非空即拒绝，**不会清表后
将已用过的证明缓存伪装成 prebuilt**。源目录只允许数据库和 `index.json`，
拒绝 WAL/SHM/journal、proof-progress 及其他文件。

源与副本均以 immutable/read-only 打开，只读取 `sqlite_schema` 和三张空表的
`SELECT 1 LIMIT 1`。预期 schema 直接取自当前 `structure_index()` 的两个
literal schema 脚本，在独立内存库创建后比较；必须精确匹配 14 张表、5 个
显式索引和 SQLite autoindexes，拒绝额外表、view、trigger、列或缺失索引。
不会打开旧主 comparison DB，也不会复制主库的 pairs、types、differences、
structural、diagnoses、anchor proof 或 state transfer 结果。

复制前后记录源数据库 SHA/stat，副本必须同 SHA、不同 inode。原生 JSON、
capture summaries、旧 marker 和实现身份也须保持不变。模块加载时记录四项
实现文件哈希，reuse 开始/结束核对。先发布独立 `reuse.json` receipt，再复核
sidecar、目录、数据库/原生输入/metadata stat 与实现身份，最后发布绑定当前
路径的 `index.json` seal。失败不会留下可被 reader 接受的 index marker。

生产复用由主任务在 full capture 完成后执行，示例 P0（GSIM 参数须指向该次
实际使用的 completed capture）：

```sh
WOLF_ENV_SOURCED=1 make --no-print-directory index_f32_structure \
  F32_STRUCTURE_STAGE=P0 \
  F32_STRUCTURE_REUSE_FROM=ptmp/firrtl-ingest/F32/comparison-v2/structure/P0 \
  F32_COMPARE_GRH=ptmp/firrtl-ingest/F32/capture-new-completed/grh \
  F32_COMPARE_GSIM="$F32_CURRENT_GSIM" \
  F32_STRUCTURE_WORK=ptmp/firrtl-ingest/F32/comparison-new/structure/P0
```

P1/P2 各自选择对应 stage/source/output；helper 不从旧 comparison 完成状态
推断 prebuilt 是否可用。全部库存派生和语义证明仍由新 comparison 重算。
本次只在小图验证，不复制 25 GiB 生产索引，也未扫描 full capture 哈希。

结构索引测试入口 `make test_f32_structure_index_contract` 共 **28/28 PASS**，
包含原有 7 项 prebuild 合同及 21 项具体复用/拒绝条件，日志为
`ptmp/firrtl-ingest/F32/structure-reuse-local/tool-tests/structure-index-contract.log`。
小图验证了 P0/P1/P2 同内容新路径、源 hash/stat 不变、复制 inode 隔离、
空缓存要求、精确 schema、防 sidecar、拒绝 hardlink/损坏副本、实现身份变化、
receipt 发布期间输入变化及失败不发 seal。reader 小图正常 resume 的结果与
fresh 一致，且测试明确禁止重新调用 `structure_index()`。
独立审查复跑同样 28/28 PASS（0.834 s），日志为
`ptmp/firrtl-ingest/F32/structure-reuse-independent-review/tool-tests/structure-index-contract.log`。

### 12.4 验证与成本

执行：

```sh
WOLF_ENV_SOURCED=1 make --no-print-directory test_f32_inventory_seed_contract \
  F32_WORK=ptmp/firrtl-ingest/F32/inventory-seed-local \
  PYTHON=/home/gaoruihao/wksp/wolvrix-playground/.venv/bin/python
```

14/14 测试通过，零 skip。日志为
`ptmp/firrtl-ingest/F32/inventory-seed-local/tool-tests/inventory-seed-contract.log`。
包含部分命中+P3 正常 ingest、全命中时 Python ingest 零调用、当前真实运行
身份、所有表的 footer 空白变化也 miss、冻结/完成/sidecar/实现 hash 拒绝、
源 DB 内容与 stat 不变、源在过程中变化导致不完整 checkpoint、旧 proof 不复制、
receipt 先于完整 checkpoint 且最后发布失败时回到不完整状态。

关键集成测试实际由未修改 reader 从 seed checkpoint resume，完成 P0 两个
Node 的结构检查，并与同一当前输入 fresh 建库的原始表、派生表、结构诊断、
anchor/state proof 及差异结果比较一致；其余边界保持 not_requested。

节省的是命中分区逐行 TSV 解码、JSON 字段解析与归一化、Python 批量组装的
成本。原始文件 hash/逐字节扫描、源数据库前后完整 hash、SQL 复制、索引和
derived SQL、当前结构索引及 proof 仍需执行。工具按 chunk 比较 TSV，不保存
整图 Python 对象；锁定 reader 的其余资源开销没有改变。只验证了小图功能，
没有做生产规模性能/容量验收，不承诺具体节省时长。

本轮没有打开生产 comparison-v2，也没有运行全图 seed 或额外全图构建。

<a id="f32-reconstruction-certificates"></a>

## 13. 有限重建证明

`scripts/prove_f32_reconstruction.py` is an independent, deliberately narrow
verifier for six small P3/P4 anchor-expression gaps. It leaves the closed F32
reader result `unverified` and never updates its database, ledger, or summary.
The supported expression is:

```
GRH:  Assign(Eq(Concat(H:UInt128, L:UInt128):UInt256, C:UInt256)):UInt1
GSIM: Eq(Or(Shl(H:UInt128, 128):UInt256, L:UInt128):UInt256, C:UInt256):UInt1
```

For each listed actual GRH/GSIM boundary pair, the premise assumes equal current
bits taking arbitrary defined values 0 or 1. H, L, and C are independent paired
boundaries. The verifier proves equality of these **current typed anchor
expressions under that premise**. It does not prove that their producers compute
equal values. In particular, repeated-child H and L remain different free
boundary identities even when GRH gives them the same physical Value anchor.

The certificate does not establish FourState/X/Z behavior, initialization,
complete Node behavior, original source binding, generated executable behavior,
or preservation across a pass. All corresponding report fields and global
`semantic_acceptance` remain false. This tool is not consumed by the existing
reader or window-origin gates; passing it does not reduce the reader's original
unverified count or incomplete source-geometry count.

### 13.1 Proof rule and operand evidence

Rule `unsigned-concat128-shl128-or256-eq-congruence.v1` replays every bit lane.
It uses the unsigned, finite-width meanings stated in the rule, without a SAT
solver, random vectors, an increased exhaustive budget, or the reader's
normalizer.

| Bits, in ascending order | GRH concat | GSIM shift | Zero-extended GSIM L | OR |
|---|---|---|---|---|
| 0..127 | L[0..127] | zero | L[0..127] | L[0..127] |
| 128..255 | H[0..127] | H[0..127] | zero | H[0..127] |

Unsigned extension happens before the UInt256 shift/OR. The two 256-lane maps
must match exactly. Both Eq operands then compare that vector to the same paired
C256 vector; Eq congruence and a type-preserving GRH assignment give the UInt1
anchor result. The report records the deterministic witness hash, widths,
source pairs, bit ranges, static shift, and rule sequence.

The loader establishes the applicability of that rule from the native dumps:

- GRH must be one flat v5 graph. The selected Node must own exactly the reachable
  `kAssign`, `kEq`, and `kConcat` operations, with one output anchor and exact
  arities. Widths are 1 for Eq/Assign, 256 for Eq operands/Concat output, and
  128 for each Concat operand. Every relevant value is unsigned scalar logic.
  A native `4state` domain is allowed only because the explicit proof premise
  restricts all free bits to defined 0/1 values.
- Raw `semanticTree.boundaryUses` identify H/L by target Node, Concat operation,
  operand index 0/1, and value. The actual source Node must anchor that value.
  C needs the exact Eq slot or one unique native generic boundary row. The
  target must have exactly those three incoming rows. Each source's actual
  GSIM partner comes from the closed comparison's `pairs` table.
- Compact JSON Value/Operation IDs are local to that dump. Native endpoint TSV
  physical IDs are **not** joined numerically to them. Sidecar type evidence is
  joined only by stable semantic Node ID; compact producer/operand relationships
  are checked within the JSON. Positive fixtures deliberately use different
  physical IDs and different GRH/GSIM semantic IDs.
- GSIM needs its complete v1 native structure and memory inventory, exactly one
  complete output assignment tree, a correctly targeted lvalue, and the exact
  typed Eq/OR/SHL/leaf shape above. Leaf `nodeId` must be the source's actual
  partner for that operand slot. Tree-local expression ID, native expression
  ID, and native Node ID are separate namespaces. The loader checks width,
  unsignedness, opcode, arity, static parameters, exact seven-entry inventory,
  and sidecar/native Node type agreement. Memory, clock, state-pair, reset-tree,
  extra assignment, and partial structure cases are unsupported.

Names are irrelevant to this proof. It does not infer boundary equality from
canonical names, a shared physical Value ID, or shared source expressions.
Alternative equivalent orientations, signed variants, or widths other than this
rule remain unsupported and unverified.

### 13.2 Frozen inputs and historical reader identity

The tool does not import `compare_f32_semantics.py`, `semantic_bitvector.py`, or
any other custom loader/normalizer. It records its own frozen source hash as the
standalone loader-and-lemma implementation. Its closed-comparison input accepts
only two explicitly approved **complete four-file identity groups**:

| Group | `compare_f32_semantics.py` SHA-256 |
|---|---|
| `closed-v8-reader-cd4aa9ad` | `cd4aa9ad9f0f203a5a576616a44d2a1754030ecec22358da9733344434ac12f7` |
| `typed-index-reader-564c8a57` | `564c8a57e290372bf30d72c497b8fba52d52103b0ed00d40129c5742ae978f95` |

Both groups require these same three exact dependency entries:

| Shared dependency | SHA-256 |
|---|---|
| `compare_f28_semantic_tree.py` | `0007e3ca9135bf4548d0dbeb001ce642376e03a3d15b776b2aaafaa560378702` |
| `semantic_bitvector.py` | `9c4ac1486b8533bbfceb4be715195a15340ca3bc0fb3c334b8bbb41246487acf` |
| `semantic_node_exchange.py` | `d837080317ed9ceabdda95c92ccec4719f600cf75571648a4e207f2582451acf` |

The first group is recorded in closed `comparison-v8` inputs. The second reader
contains the reviewed typed temporary-table/index corrections; its three proof
dependencies are byte-identical to the first group's. Matching uses equality of
the entire four-entry dictionary, including filenames. Unknown hashes, swapped
dependency hashes, extra entries, missing entries, and renamed keys are rejected
before connecting to the comparison database. Because the three dependencies
are identical between groups, either approved reader hash with those exact
dependencies is one valid group; there is no distinct invalid mixture of those
two readers alone.

New receipts record the actually matched `comparison_implementation_group`, the
complete input identity in `historical_comparison_implementation`, and the
standalone verifier's separate current SHA in `proof_implementation`. Rejected
groups report `comparison_implementation_group=null`. These fields make no
claim that the on-disk reader was imported or has the recorded comparison hash.
Neither a reader nor a normalization implementation is called. The old six
certificates and their original verifier hash remain archived unchanged; adding
a group does not rewrite or upgrade them.

`summary.json` must be completed/analyzed with full native structures compared;
`inputs.json` must have `inventory_complete=true` and the same five-boundary
snapshot records. Capture-summary paths and hashes must match the checkpoint.
Both captures must be completed native raw-FIRRTL runs, have the same original
input SHA, and supply all five distinct snapshots of one run per engine.
The requested pair must be an actual stored pair whose exact old result is
`unverified / nonidentical_expression_exceeds_exhaustive_bit_budget`.

Every frozen TSV and native structure must match its captured path, byte count,
and hash. TSV metadata, escaping, schema/header, footer completeness, counts,
snapshot/run identity, and Node inventory are checked. Selected structures are
decoded with duplicate-key and duplicate-ID rejection. Native structure Node
inventories must equal the corresponding TSV inventories. The comparison
database, comparison metadata/ledger, capture metadata/artifacts, and verifier
source receive hashes and file stat checks before/after the proof.

SQLite WAL, SHM, or journal sidecars are rejected before connecting and rechecked
afterward. SQLite opens with `mode=ro&immutable=1`, `query_only=ON`, and
`trusted_schema=OFF`. The tool retains the historical reader's **closed cache
trust** for stored comparison pairs/results; hashing a database does not
independently rederive its entire cache. It independently checks the selected
native expressions and type evidence and states paired-boundary equality as a
premise. It does not certify source/build archives or rebind original source
geometry from the captures.

The tool has a fixed small-input envelope: at most six explicit P3/P4 targets,
128 Nodes per snapshot, 4096 operation/value entries or TSV rows per table,
2 MiB per normal input, 16 MiB for the comparison database, and 32 MiB total
frozen inputs. This workflow uses only closed small probes; the tool has not
been run against the active production comparison or full graphs. The guards
enforce completed/closed state and small size, rather than a path blacklist.
A failure or unsupported input yields nonzero CLI status and no
certificates; one failed target discards all certificates in that invocation.
The output must be a new directory under repository `ptmp/`.

### 13.3 Make workflows

Run the focused portable tests through the project Makefile:

```sh
WOLF_ENV_SOURCED=1 make --no-print-directory test_f32_reconstruction_contract \
  F32_WORK=ptmp/firrtl-ingest/F32/reconstruction-local \
  PYTHON=/home/gaoruihao/wksp/wolvrix-playground/.venv/bin/python
```

The tests exercise mixed, producer, and shared-Value repeated-child shapes at
P3/P4, distinct cross-engine IDs, and negative mutations of shift, widths,
unsignedness, operand order, source/lvalue identity, boundary rows, inventories,
reader/dependency hashes, input hashes, and closed-state requirements. They also
check no input bytes or SQLite sidecars change and that CLI failures carry no
certificate.

The focused contract run passed **41/41**, with no skips, in 1.657 s. Its log is
`ptmp/firrtl-ingest/F32/reconstruction-local/tool-tests/reconstruction-contract.log`.
After the explicit two-group compatibility extension, the focused contract run
passed **45/45**, with no skips, in 1.722 s. Its separate log is
`ptmp/firrtl-ingest/F32/reconstruction-identity-local/tool-tests/reconstruction-contract.log`.
The added cases accept the new exact group and reject unknown dependency/reader
hashes, approved hashes under wrong dependency filenames, and extra/missing or
renamed identity keys, before SQLite connection. The new verifier source SHA is
`edd6048b84cadd6cc9ef3ee9c9ca9defeab2c938ecf5bb802682756ac17b2c89`.
No current-freeze actual proof was run as part of this compatibility change.

For the closed split-strategy comparison, choose a fresh output path:

```sh
WOLF_ENV_SOURCED=1 make --no-print-directory prove_f32_reconstruction \
  F32_WORK=ptmp/firrtl-ingest/F32/reconstruction-local \
  F32_RECONSTRUCTION_COMPARISON=ptmp/firrtl-ingest/F32/split-strategy-probe/comparison-v8 \
  F32_COMPARE_GRH=ptmp/firrtl-ingest/F32/split-strategy-probe/grh-v8 \
  F32_COMPARE_GSIM=ptmp/firrtl-ingest/F32/split-strategy-probe/gsim \
  F32_RECONSTRUCTION_WORK=ptmp/firrtl-ingest/F32/reconstruction-local/split-strategy-v1 \
  F32_RECONSTRUCTION_TARGETS='P3:10:10 P3:11:11 P4:10:10 P4:11:11' \
  PYTHON=/home/gaoruihao/wksp/wolvrix-playground/.venv/bin/python
```

For `repeated-child-probe`, use its `comparison-v8`, `grh-v8`, and `gsim`
directories, a fresh output directory, and targets `P3:3:3 P4:3:3`.
Names shown here explain the preselected probe only; the CLI selects by explicit
boundary and actual Node IDs.

### 13.4 Closed-v8 application results

Both Make invocations completed successfully against the existing closed small
`comparison-v8` inputs: **6/6 conditional current anchor-expression certificates,
0 failures**. Each certificate replays all 256 lanes with actual H/L/C paired
boundary identities. The original reader result for every target remains
`unverified / nonidentical_expression_exceeds_exhaustive_bit_budget`.

| Probe | Boundary | Output GRH/GSIM Node | H pair | L pair | C pair | Local result |
|---|---|---|---|---|---|---|
| split-strategy | P3 | 10/10 | 18/18 | 17/17 | 3/3 | Conditional anchor expression proved |
| split-strategy | P3 | 11/11 | 20/20 | 19/19 | 3/3 | Conditional anchor expression proved |
| split-strategy | P4 | 10/10 | 18/18 | 17/17 | 3/3 | Conditional anchor expression proved |
| split-strategy | P4 | 11/11 | 20/20 | 19/19 | 3/3 | Conditional anchor expression proved |
| repeated-child | P3 | 3/3 | 6/6 | 5/5 | 2/2 | Conditional anchor expression proved |
| repeated-child | P4 | 3/3 | 6/6 | 5/5 | 2/2 | Conditional anchor expression proved |

For repeated-child, the two GRH source Nodes 5 and 6 both anchor compact Value
1. Exact Concat operand-slot witnesses and GSIM leaf Node identities preserve
them as separate paired boundary premises. No producer equality is inferred.

Evidence lives under `ptmp/firrtl-ingest/F32/reconstruction-local/`:

- `split-strategy-v1/summary.json` contains four certificates, 57 frozen input
  receipts, and `failures=[]`; its SHA-256 is
  `5223f29af62672908eff62edf8e20273ce365c37ec40cbeee59298d4f33fcf51`.
- `repeated-child-v1/summary.json` contains two certificates, 57 frozen input
  receipts, and `failures=[]`; its SHA-256 is
  `9c3913453f03c957f0badc0f6cd7d69fe27bea0c8ae8d1b951ce50f31cca6637`.
- `split-strategy-v1.log` and `repeated-child-v1.log` record the successful CLI
  summaries and `semantic_acceptance=false`.
- `closed-v8-before.sha256` and `closed-v8-after.sha256` have identical file sets
  and hashes for all **38 files** beneath both original comparison directories.
  `closed-v8-after-check.log` records 38 successful checksum checks. No original
  comparison bytes changed. Each proof receipt separately checked all 57
  consumed inputs' before/after hashes and file stats, and rejected/rechecked
  SQLite WAL/SHM/journal sidecars.

Both receipts bind historical reader SHA
`cd4aa9ad9f0f203a5a576616a44d2a1754030ecec22358da9733344434ac12f7`
and the three historical dependency hashes above, separately from the current
standalone verifier SHA
`4d64bc8033402faa74914e58f1a49dd2d96738077d2fc4141c303ac8b204dfb8`.
They explicitly report `reader_called=false`, `normalizer_called=false`, and
`historical_comparison_implementation_is_current_code_claim=false`.

Every certificate and both summaries keep `reader_results_modified`,
`four_state_behavior_proved`, `initialization_proved`,
`full_node_behavior_proved`, `source_binding_proved`,
`paired_producer_equivalence_proved`,
`pass_transformation_preservation_proved`, and `semantic_acceptance` **false**.
The premise is equal arbitrary defined 0/1 current H/L/C boundary bits. The
certificates do not close the reader's strict gates, the source-geometry window
gate, or the global F32 acceptance gate, and are not ingested by those gates.
An independent read-only receipt review confirmed all six target/source pairs,
the 57 before/after input identities per run, the 38-file comparison manifests,
the separated implementation identities, and these unchanged strict gates.
The later two-group compatibility change rechecked both archived receipt hashes
above and left their bytes unchanged. Their original standalone implementation
identity remains the original `4d64bc80...` value recorded in those receipts.

<a id="f32-pass-anchor-preservation"></a>

## 14. 同端逐 pass 的有限 anchor 保持证明

`scripts/prove_f32_pass_preservation.py` 从原生 GRH P0–P4 中重放四次相邻边界
的纯组合锥。它证明的命题是：**在每个 formal input bit 均为任意定义的
0/1 值，且前后具有相同原生 formal input binding 的前提下，指定存活 Node
的当前 typed anchor 值保持不变**。它穿透中间 Node，一直追到实际 formal
input；不把同名中间 Node 或中间 anchor 直接假定为前后相等的自由变量。

这比来源关系多提供一项实际的同端转换证据，但仍不是完整 Node 或整个
窗口的验收证书。`FourState` 类型可以作为原生类型读入；本命题只覆盖其中
定义的 0/1 输入。未知字面量、signed 运算、状态/效果、未支持运算或未绑定
叶子使对应锥保持 unproved，不转换成零，也不跳过后继续宣称通过。

### 14.1 输入、身份和执行

输入为已完成 comparison 的 `summary.json`、`inputs.json` 及其引用的 GRH
原生 capture。comparison 必须 `status=analyzed,complete=true`，checkpoint
必须 `inventory_complete=true`，二者快照身份完全相同。这里只消费 comparison
checkpoint 的原生冻结身份，不读取或复用其派生 SQLite proof 结论。

原生 capture 必须是 raw FIRRTL、无 trace、full structure 的 completed 五界
运行。复用 §13 的严格原生文件 loader，核验 capture summary、TSV 和 structure
的路径、字节数、hash、五个独立 snapshot 与同一 run，以及 structure/TSV 的
Node 库存一致。消费文件及两个 verifier 源文件读取前后均检查 hash 和 stat；
源码还须符合当前已加载模块身份。没有证书导入，也不会打开或修改原比较库。

formal input 的同端身份来自原生 `firrtl.semanticPortNames:string[]` 与
`firrtl.semanticPortNodes:int[]`、真实 formal port 及其唯一 Node anchor 的联合
校验。metadata 类型、名字和 Node ID 的唯一性、完整 formal port 库存、实际
input/output anchor 都须成立。前后 graph symbol、sourceUnit、circuit、单一
flattened root path、formal port 的方向/顺序/Node ID/name 和 input 类型必须
保持一致。仅有名字相同不建立身份；compact ValueId/OperationId 可以重排。

```sh
WOLF_ENV_SOURCED=1 make --no-print-directory test_f32_pass_preservation_contract \
  PYTHON=.venv/bin/python3 \
  F32_WORK=ptmp/firrtl-ingest/F32/pass-preservation-native-map-development

WOLF_ENV_SOURCED=1 make --no-print-directory prove_f32_pass_preservation \
  PYTHON=.venv/bin/python3 \
  F32_PRESERVATION_COMPARISON=ptmp/firrtl-ingest/F32/array-native-probes-v13/pipeline/comparison \
  F32_PRESERVATION_GRH=ptmp/firrtl-ingest/F32/array-native-probes-v13/pipeline/grh \
  F32_PRESERVATION_WORK=ptmp/firrtl-ingest/F32/pass-preservation-v13-pipeline-new
```

输出须为 `ptmp/` 中未存在的新目录；失败不会发布成功 summary。输出为
`anchor_certificates.jsonl`、`symbolic_terms.json` 和
`wolvrix.f32.pass-anchor-preservation.v1` 的 `summary.json`。每项证书记录真实
前后 anchor ValueId、Node ID、边界、类型域、proof premise 及结果；两个报告
artifact 和所有消费文件的 hash 保留在 summary 中。

### 14.2 重放规则与预算

每个位表示为共享 arena 中的精确 tuple，比较使用完整结构的 hash-cons
identity；SHA-256 只用于 artifact/诊断，不作为符号等式的充分条件。重放规则：

| 操作 | 逐位规则 |
| --- | --- |
| Constant | 只接受明确的定义值；二/十/十六进制按结果有限位宽截断或补零。X/Z literal 保持 unproved。 |
| Assign / Concat / SliceStatic | 无符号有限位宽截断/补零、低位优先拼接、原生静态区间；切片须在输入内。 |
| Not / And / Or / Xor | 保留有序操作和真实 operand bit；Not 暂只接受等宽。 |
| Mux | 保留真实 select、yes、no；只化简常量 select 或逐位结构完全相同的两臂，控制须为一位。 |
| SliceArray | 只接受定义的静态 index；须在外维界内，结果 shape/width 是真实后缀。动态读取与越界读取保持 unproved。 |
| CombArrayUpdate | 按原生组顺序重放。逐维用完整 index 与每个实际坐标做定义值相等比较，再与 enable 相与；每个目标叶按这个条件 mux payload/prior。后写覆盖前写，控制与索引不受 payload 叶宽影响。 |

数组 `shape=[d0,...,dn]`，叶数 `N=prod(shape)`、叶宽 `W=packedWidth/N`。
rank 为 `r` 的一组写入，后缀叶数 `S=prod(shape[r:])`；目标 leaf 的 payload
来自 `(leaf % S)*W`。每轴坐标按真实 stride 求出，不把多维数组压成索引位截断。
`r=0` 覆盖全数组，`r=n+1` 更新标量叶。索引确定越界时没有坐标相等，因而不
写任何叶；不会截短 index 来强行落入数组。未知索引/enable 不在本命题的定义值
前提内；若由 unknown literal 产生，会拒绝相应锥。

本工具沿用小捕获 loader 的上限：每个文件 2 MiB、合计 32 MiB、每界最多128
Node、4096个 Value/Operation、TSV 最多4096数据行。新增上限为每个 packed
value 4096 bit、共享符号项100000、递归锥深度128；遇到符号项/深度预算保持
unproved，非法或超出类型/文件预算的输入使运行失败。没有生产规模能力或性能
验收。物理 anchor 几何变化不自动假设“保留低位”；仅 §14.4 的严格原生 source
binding 规则可产生有限的保留投影证书。Node 新增/退休同样需要独立证书。

### 14.3 当前原生结果与独立复核

初版复核后的 [16项合同](../../ptmp/firrtl-ingest/F32/pass-preservation-audit-final/tool-tests/pass-preservation-contract.log)
全部通过；后续带原生映射的21项合同与 v13 结果见 §14.4。除冻结输入与原生身份正反例，还覆盖 dynamic index 全宽、更新顺序、
改变真实输入绑定、metadata 类型/ID/图上下文漂移、未知字面量、signed/state
拒绝、符号预算，以及二维后缀更新/标量更新/整数组更新。二维后缀结果以独立
整数 oracle 枚举256个 payload和两个 row index，共512组，而非只比较同一个
符号器对自身的输出；确定越界写入不产生更新，静态越界读取不发布证明。

| 原生 v12 capture | P0→P1 | P1→P2 | P2→P3 | P3→P4 |
| --- | --- | --- | --- | --- |
| [pipeline audited](../../ptmp/firrtl-ingest/F32/pass-preservation-v12-pipeline-audited-final/summary.json) | 10 proved / 0 unproved | 9 / 1 | 10 / 0 | 9 / 1 |
| [pruned audited](../../ptmp/firrtl-ingest/F32/pass-preservation-v12-pruned-audited-final/summary.json) | 6 / 0 | 6 / 0 | 6 / 0 | 6 / 0 |

pipeline 的 `low/high/selected` 三个 formal output 在四次转换都获得上述条件下的
值保持证据。`selected` 的证明穿透完整动态组合数组写与静态读投影，不借用
中间 bank 的相等假设。bank 在 UsedBits 改变叶宽，第二 DCE 清掉未观察区域，
两项仍 unproved；这不把不可观察区域的物理变化错误报告为语义错误。

单项证书保持 `complete_node_preservation_proved=false`；summary 保持
`four_state_behavior_proved=false`、`full_node_membership_proved=false`、`source_bindings_proved=false`、
`state_effects_initialization_proved=false`、`retirement_proved=false`、
`cross_engine_equivalence_proved=false`。`window_acceptance` 与
`semantic_acceptance` 始终 false，`upstream_gate_modified=false`，
`certificate_ingestion_implemented=false`；原 reader 和 §11 的未关闭事项计数
不变。这些结果不能宣称 F32.5 或整个窗口已通过。

### 14.4 原生 source binding 约束的保留投影

新增 `native-source-leaf-prefix-preservation.v1` 规则支持同一存活 Node 的叶宽
缩窄，结果单列为 `retained_projection_preservation_proved`。它要求已冻结并
通过 hash/字节数/stat 检查的原生 `node-endpoints.tsv` 中，每个 Node 恰有一条
`role=value,evidence=native-binding` 的 v2 记录。`anchor-candidate`、缺少源宽度
或多条歧义记录均不能建立这项证明。

还必须提供已冻结的原生 `serialization-id-map.tsv`。StoreJson 会把当前存活
Value/Operation 重新稠密编号，端点 TSV 则使用物理 index/generation，两者
数值相等也不能当作绑定证据。新 map 具有
`grh.native-serialization-map.v1`、run/session/snapshot/stage、graph index/
generation/symbol 元数据，逐行记录 `kind,serialized_id,native_index,native_generation`。
两端 JSON 与原生 map 的 value/op 库存必须完整双射；端点的 value index与
generation 须映射到该 Node 的实际 serialized anchor，operation index与
generation 须映射到这个 anchor 的真实 defining op，kind 也必须一致。
非定义 op、缺失/重复映射、错误角色、错误 generation 均不能通过。

snapshot 默认不写该全图 map。新 native API 的
`semantic_snapshot(...,emit_serialization_id_map=True)` 显式启用；capture 对应
`F32_CAPTURE_ARGS='--dump-structure --serialization-id-map'`。capture 在同一个
Session 中紧接 snapshot 调用只读 StoreJson，中间没有 pass；两者共用
`forEachSerializedValue/Operation` 的 live-range 编号规则。map 与其余原生
artifact 一同 hash 冻结，跨图/会话/边界直接拒绝。旧 capture 没有 map 时保持
unproved，不离线猜测或补造映射。

前后必须具有相同的 sourceWidth、source shape、source signedness、原始 shape
field-depths 与投影轴；当前规则只接受所有数组轴完整保留、source bit offset
都为0的叶前缀。实际物理 shape、signedness、logic domain、叶宽必须逐项与
sidecar 相符。`source_bit_width=-1` 仅按原生约定解释为完整 sourceWidth；实际
保留宽度必须等于当前物理叶宽，且不超出原始 source 区间。未知、错误类型、
非法区间和 source geometry 漂移保持 unproved。

有了上述实际几何，旧/新叶宽分别为 `B/A`，每个 cell 的保留位按
`old[cell*B + bit] == new[cell*A + bit]`（`bit=0..A-1`）逐位重放并比较同一个
formal-rooted 符号锥。不能把旧 packed value 的低 `cellCount*A` 位当作每个
cell 的低位。该状态明确保留 `anchor_value_preservation_proved=false`、
`full_width_anchor_equality_proved=false` 和
`discarded_bits_unobservable_proved=false`；它只证明保留区域的值，不证明丢弃
区域无消费者。实际输出的值保持由原有独立 output anchor 证书承担。

早期20项合同中的 synthetic 投影正例只检查了 source 几何和 Node ID，未证明
native endpoint 到 serialized anchor 的实际绑定；其充分性结论已撤回。那些
历史运行没有发布真实 capture 的 projection 通过项；原 anchor 等式结果不受
该缺口影响。当前 [21项合同](../../ptmp/firrtl-ingest/F32/pass-preservation-native-map-development/tool-tests/pass-preservation-contract.log)
已补齐显式原生映射并全部通过。新增正例为四个独立8-bit cell缩成各3-bit；负例包含 cell 换序、
错误packed前缀映射，以及candidate、sourceWidth/offset/shape/axis/depth/
signedness/物理宽度等13种源几何变更。另一个完整五界冻结 fixture 通过真实
TSV loader、完整物理/serialized 映射与 artifact hash 链产生投影证书；发布后修改 source offset 会先因
原生 artifact hash 不符而失败，不能发布新的成功 summary。

机械 producer 与 StoreJson 共享编号已通过
[native 2/2](../../ptmp/firrtl-ingest/F32/native-serialization-map-tests/tests/test.log)：
实际删除对象制造物理编号空洞后检查生成的 map、generation、StoreJson 的 value/op 编号
与 operand slots，确认默认不导 map 且导出不修改图。
[capture 19/19](../../ptmp/firrtl-ingest/F32/native-serialization-map-contract/tool-tests/capture-contract.log)
覆盖显式开关、五界导出、map artifact hash 冻结、跨 session 与缺文件拒绝。
以上为机械合同测试；package-v15的实际mapped捕获结果另见本节末尾。

此前已完成的package-v13两例已用当前 verifier 分别重放：

| 原生 v13 capture | P0→P1 | P1→P2 | P2→P3 | P3→P4 |
| --- | --- | --- | --- | --- |
| [pipeline](../../ptmp/firrtl-ingest/F32/pass-preservation-v13-pipeline-native-map-check/summary.json) | 10 anchor proved / 0 unproved | 9 / 1 | 10 / 0 | 9 / 1 |
| [pruned](../../ptmp/firrtl-ingest/F32/pass-preservation-v13-pruned-native-map-check/summary.json) | 6 / 0 | 6 / 0 | 6 / 0 | 6 / 0 |

**本轮真实 capture 没有产生新的保留投影通过项。** pipeline 的 bank 在 P1/P2
仍是 `anchor-candidate,source_width=-1,source_bit_width=-1`，虽然物理叶宽
8→3、shape为[4]，也不能伪造原始 source 几何。工具明确记录
`retained projection requires one actual native source binding per Node`；P4
bank 的死区域改变仍因符号 lane 不同保持 unproved。上表中的三个实际输出
四段保持证据继续有效；没有用它们补造 bank binding。严格 gate、FourState、
完整 Node、退休与跨端证明的限制仍全部保持 §14.3 所述状态。

该source缺口已由 [F32-U4](#f32-source-provenance-gap) 的原始ingest与逐prefix
实验复现，并非仅由窗口后的candidate推测。显式serialization map能证明
物理/serialized身份，不能提供新树未保存的原始source几何；补上map后也必须
继续对这些实际bank投影保持unproved，直到单独审核的新树provenance修复完成。

package-v15现已完成实际mapped捕获。复现入口为
[mapped-probes Makefile](../../ptmp/firrtl-ingest/F32/mapped-probes-v15.Makefile)，
通过已有项目targets从同一原始tracked FIRRTL捕获双端五界，再比较和重放；
没有向旧capture补写map。两例GRH summary均为`completed,serialization_id_map=true`，
十个边界的map已冻结hash并通过真实loader的完整库存双射检查。实际端点仍为
candidate，故未进入要求native-binding的source anchor/defining-op证明分支。

另以独立stdlib脚本直接审计真实candidate的**机械身份关联**，不调用proof或
reader实现。结果见 [审计报告](../../ptmp/firrtl-ingest/F32/v15-endpoint-identity-audit/report.md)、
[逐端点完整结果](../../ptmp/firrtl-ingest/F32/v15-endpoint-identity-audit/endpoint-links.jsonl)
与 [冻结hash和完整库存](../../ptmp/firrtl-ingest/F32/v15-endpoint-identity-audit/summary.json)：
十界80/80 candidate经各自原生index/generation map对应其Node的真实JSON anchor；
其中40条对应真实defining op/result slot/kind，40条对应实际formal input且无def。
完整map双射覆盖202个value及162个op；大量物理与serialized编号不同，未直接
按相等数字连接。全部80条当前leaf width/shape/signed/domain与anchor一致，
leaf width严格按packed total/product(shape)计算。实际operation-only为0，
所以没有真实数据覆盖该无value分支，不能声称完成operation-only值绑定。
该审计不证明生产source_geometry分支已执行，不改gate或原始source字段；
候选的`source_width/source_bit_width=-1/-1`仍未补值，U4及所有语义限制保持。

| 原生 v15 mapped capture | P0→P1 | P1→P2 | P2→P3 | P3→P4 |
| --- | --- | --- | --- | --- |
| [pipeline](../../ptmp/firrtl-ingest/F32/array-native-probes-v15/pipeline/preservation/summary.json) | 10 anchor proved / 0 unproved | 9 / 1 | 10 / 0 | 9 / 1 |
| [pruned](../../ptmp/firrtl-ingest/F32/array-native-probes-v15/pruned/preservation/summary.json) | 6 / 0 | 6 / 0 | 6 / 0 | 6 / 0 |

实际map支持已验证，但没有新增保留投影通过项；U4的candidate仍被拒绝。
[pipeline严格比较](../../ptmp/firrtl-ingest/F32/array-native-probes-v15/pipeline/comparison/summary.json)
仍有3个相对P0新增的unproved Node结果，
[pruned严格比较](../../ptmp/firrtl-ingest/F32/array-native-probes-v15/pruned/comparison/summary.json)
该项为0；两者`semantic_acceptance`及所有§14.3的完整语义标记仍为false。

后续package-v17的depth2 register/memory也完成
[独立机械身份审计](../../ptmp/firrtl-ingest/F32/v17-depth2-endpoint-identity-audit/report.md)：
十界5,194检查通过，实际78条端点中，58条candidate对应18个真实defining op和
40个formal input；另外20条operation-only均经map关联到其Node真正owned member。
此轮实际执行了v15没有样本的operation-only分支，明确不建立value、current/next
writer角色或源几何关系。完整map双射为216 values及196 ops；所有source字段原样
保留，`source_geometry_proved`和`semantic_acceptance`仍false。没有修改生产reader，
这些独立审计结果不代表生产`source_geometry()`接受过candidate。
