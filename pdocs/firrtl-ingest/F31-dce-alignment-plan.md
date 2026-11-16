# F31：DCE 规则、ArrayUpdate 与 Node 图演化对齐

日期：2026-11-16。状态：**已完成，按用户要求在 v51 收尾，不再继续消除剩余 DCE 差异。** 最终 DCE 后 GRH 为 **5,635,937** 个 Node，其中 **5,617,898** 个在 GSIM 的 DCE 后库存中有唯一同名对应，占 **99.67992900%**。13/13 套原生回归及静态 snapshot API 回归通过；最新完整捕获未启用 trace、未做 trace 校验。最终计数、剩余差异和清理范围见 §10.41。

本文 §10.1–10.40 保留历史实施记录，旧“继续收敛”状态均由 §10.41 的完成状态覆盖。收尾已清理旧版本的大型快照、trace、缓存及一次性诊断脚本；小型历史报告保留，指向已清理原始数据的旧链接仅作历史索引。完整原始双端基线与最终 v51 静态捕获保留。

## 1. 目标与范围

在 F30 的正常 `ingest → xmr-resolve → hier-flatten → comb-loop-elim →
split-static-array` 基础上，打通下一次独立 `dead-code-elim`，与 GSIM 的
**首次** `RemoveDeadNodes` 对齐，完成三项工作：

1. 确认两侧 DCE 的可观察根、依赖传播和删除规则，统一存活 Node 的身份与命名合约。
2. 支持 F28 SemanticTree 与 F30 `kArrayUpdate`，正确维护真实 IR、Node、连接和演化证据。
3. 从 split 后的良好对应关系出发，区分既有差异、GSIM 准备阶段差异、DCE 删除差异及共同存活图的连接差异。

本轮只覆盖这一次独立 DCE；GSIM 后续 ExprOpt、UsedBits、SplitNodes、
ConstantAnalysis、AliasAnalysis、CSE 及其他 DCE 调用分别归属后续阶段。
GRH 不通过运行整个 simplify 达到本轮终点，也不复制 GSIM 的 Node/ENode
活跃性实现；继续使用 GRH 实际 op/value/状态依赖分析。

SemanticTree 的维护和 evolution 记录属于正常 pass。导出与比较工具用于
验收和归因，不参与电路优化，不在导出后修补 Node 名称或重建演化关系。

## 2. F30 起点与精确阶段边界

源码基线：主仓库 `3c13895`，wolvrix `aae86a3`，GSIM `c2535b3`。
输入仍为完整 `build/xs/rtl/rtl/SimTop.fir`，SHA256：
`b313a3ecd154cbd9279b14403709806b95fb136cf44b475e9def46a926ecb26b`。
GRH 使用 F30 同一 ingest manifest，正式运行从原始 FIRRTL 开始，不读取 checkpoint。

F30 最终完整导出基线如下，详细证据见 [F30](F30-array-update.md)：

| split 后指标 | GRH | GSIM |
| --- | ---: | ---: |
| 原生 Node | 9,476,863 | 9,635,014 |
| 唯一同名候选对 | 9,472,866 | 9,472,866 |
| 无同名候选 Node | 3,997 | 162,148 |

候选对占 GRH 99.957824%，是名称库存对应，尚不是全图功能等价证明。
F30 另有 95 个 GSIM-only 拆分父、72 个 GRH-only 拆分父、83 个存活 residual
父，以及 6,550 个共同拆分父的原始坐标 vector 差异；这些均带入 F31 归因。

两侧实际边界：

```text
GRH : raw ingest → XMR → flatten → comb → split → [G0] → DCE → [G1]
GSIM: raw FIRRTL → Init → splitArray → [S0]
      → DetectLoop → TopoSort → InferAllWidth → [S1] → RemoveDeadNodes#0 → [S2]
```

F30 对应关系位于 G0/S0；本轮 DCE 五文件分别覆盖 **G0→G1** 和 **S1→S2**。
单独保存 S0→S1 的准备阶段快照、身份检查及连接差量，把当前运行的 F30
候选关系桥接到 S1，不能将 S0 直接冒充 GSIM DCE-before。

GSIM `src/main.cpp:425–436` 确认上述顺序。DetectLoop 主要检查环，TopoSort
建立顺序；三步均不增删或改名 Node，完整图仍校验这一不变量。
InferAllWidth 会改写 ENode 的 PAD/SEXT/BITS 等结构，甚至裁去
不再贡献的 concat 分支，因此公共表达式依赖可能改变。当前 native `prev`
与这些改写后的真实依赖也须核对，不能预设二者始终相同。
首次 DCE 使用唯一 pass instance/ordinal，不能只凭多次出现的
`RemoveDeadNodes` 字符串选择比较终点。

主报告关注 FIRRTL 来源及其外部接口；辅助 SV 实现另列，不计作 FIRRTL
未对齐。范围划分必须由 ingest unit/source 等证据支持，完整图总库存仍
同时报告，不能按未匹配名字批量排除。外部接口及副作用的保活不因统计范围改变。

## 3. F31 开始时的现状与缺口

本节记录 F30 基线的缺口；当前实现和验收结果见第 10 节，表中的入口门禁、
旧文档及 exchange 限制不代表实施后的现状。

| 项目 | 当前源码事实 | F31 工作 |
| --- | --- | --- |
| GRH pass 入口 | `lib/core/transform.cpp:52–68` 的支持边界仍截止 split；DCE 会拒绝 F28 树或残留 ArrayUpdate | 完成新树、更新 op 及回归后开放 DCE；后续未迁移 pass 继续明确拒绝 |
| GRH ArrayUpdate | `lib/transform/dead_code_elim.cpp:917–919` 的 default 会保守标活全部 operands，但没有专用分支，正常新流程尚不可达 | 明确保守支持，再增加安全的组裁剪和位需求传播 |
| GRH Node 回收 | `Graph::pruneSemanticTree` 当前只调用 `pruneEmptyPaths`，不会退役死叶 Node | 显式判定、删除死叶及清理归属、anchor、binding、连接；保留合法空 op 边界 |
| GRH 现成基础 | 删除 op/value 已维护 membership/binding 并通知 observer；DCE 有工作列表、root mask、位区间及状态族 | 复用这些基础，接入有原因的 Node 演化事务 |
| GSIM DCE | `src/deadNodes.cpp` 按根及 `prev` 标活，标记 DEAD 后清理容器并 reconnect；未新建、改名、内联或合并 Node | 固化删除规则与身份检查，补运行时删除记录 |
| GSIM exchange | 当前 session/stage/API 主要固定为 Init→SplitArray | 泛化 pass/stage/instance，支持 DCE 前后快照及原生删除事务 |
| 既有 DCE 文档 | 仍描述旧树的整分支压缩、oldToNew 和 SemanticId 重编号 | 更新为 F28 单一叶 Node、稳定 ID 和显式退役；不沿用 F21 旧身份约定 |

主要实现落点：GRH 的 `lib/transform/dead_code_elim.cpp`、
`lib/core/{transform,grh,semantic_tree,semantic_exchange}.cpp` 及相应头文件；
GSIM 的 `src/{deadNodes,main,SemanticNodeExchange}.cpp` 及相关接口。

## 4. 共同 DCE 规则与命名合约

### 4.1 Node 只删除，存活身份不变

对每端的一次 DCE，令 B/A 为前后实际公开 Node ID 集合，要求：

```text
A ⊆ B
deleted = B − A
∀ n ∈ A: id、name、path tokens、原生身份均与 before 相同
```

数字 ID 只在同一端、同一次运行中追踪，不能要求两端或不同运行的数字相等。
跨端匹配从 DCE-before 冻结的一对一候选出发，经各自原生 ID 追踪后态。

- 不分裂、不合并、不新建公开 Node，不将死 Node 的名字回填给其他 Node。
- `r_3`、`r_3_0` 等原有名字原样保留；删除 `r_2` 后不移动其余下标。
- current/`$NEXT`、多维及单元素轴的已有命名均不重算；DCE 不借机修复 F30 坐标表示差异。
- 容器擦除、排序和内部存储压缩不改变公开 Node ID；禁止删后重建同名 Node 冒充存活身份。
- GRH 内部死 op、无效更新组和无效连接可以删除，存活 Node 的 op 集合可以收缩；这是保持 ID 的实现变化。
- Path 是结构索引，只删除失去全部叶的路径；flatten 后保留根与存活直接叶，不重新组织层次。

Node 名字/路径的变化数量必须为 **0**，新 Node 数必须为 **0**。
若准备阶段或其他优化改变身份，必须在独立阶段中解释，不能藏在 DCE 事务里。

### 4.2 跨端保留必须可解释

在 DCE-before 建立并冻结一对一 Node 候选，只对这组共同候选比较两端的原生
ID 后态。令 `D_GRH` 和 `D_GSIM` 分别是该候选集合中由 GRH、GSIM 删除的 Node。
不再要求 `D_GSIM ⊆ D_GRH`；对 `D_GSIM − D_GRH` 中每个 GSIM 删除而 GRH
保留的 Node，F31 必须给出可重放、可核验的保留解释：

```text
GSIM 删除、GRH 保留 = 必须归因
有原生依赖证据的语义例外 = explained retention
缺少充分原生依赖证据 = unexplained retention，验收失败
GRH 删除而 GSIM 保留 = 允许的 GRH 额外删除，仍检查 GRH 自身正确性
```

解释必须从该 Node 沿实际 Value/op/operand/状态或事件依赖到活跃根，不接受仅有
名称、Node 类型、粗粒度 reason mask 或共享 owner 标签。可接受的例子包括：到活跃
register/latch writer 的 clock/reset 依赖，以及到活跃 FIRRTL `SystemTask` 的
实际时钟 operand 依赖。若 GSIM 首次 DCE 未以对应 Node/ENode 边保留这些显式事件
依赖，GRH 的保留可以是语义例外；例外不是自动放行，仍须证明具体 endpoint、
消费 op、operand slot、依赖路径和 live root。不得按 `clock` 名称、`system_task`
root mask 或某一整类 Node 批量豁免。未能唯一配对的 Node 在 `node-differences.tsv`
独立统计并保留本端生命周期证据；由于没有唯一 GSIM peer，它们不计入跨端
explained/unexplained 门禁，也不能被报告为已证明的跨端语义例外。

### 4.3 根、状态与副作用

以下表格先固定已有安全规则；发现差异时根据真实可观察性修复不正确的一侧。

| 类别 | GRH 现状 | GSIM 首次 DCE 现状与核对项 |
| --- | --- | --- |
| 端口 | input/output/inout 边界保持 | output 是根；所有 INP/OUT 受删除保护；区分“端口存活”与“所有输入锥均为根” |
| 声明/DontTouch | 默认 `keep_declared_symbols=False`；True 是单独受保护模式 | 不把普通声明当额外根；比较运行固定使用相同保护策略 |
| 组合计算 | 从结果需求反向传播实际 operands/位区间 | 沿 `prev` 传播，未拆数组按完整 Node 保活；核对 ENode/lvalue 索引依赖 |
| register/latch | 活跃状态族保声明、必要读口与全部 writer，继续传播数据、使能、索引、事件 | 活 REG_SRC 保 next、resetTree；两端必须保留实际 clock/reset/event 依赖 |
| memory | FIRRTL memory 降成 register/数组端口，沿状态族保活；未观测写不是独立根 | 活 READER 联动 WRITER/READWRITER；空 memory 回收也须记录 |
| 外部边界 | instance/blackbox/DPI/XMRWrite 等按既有规则保留 | 活 EXT/EXT_IN/EXT_OUT 为根，EXT_OUT 联动外部成员 |
| FIRRTL effects | printf/stop/assert 等的实际系统调用、条件与显式 clock operand 保留 | specialNodes 为根；GSIM 未保留实际 SystemTask clock 依赖时，GRH 可提交逐 Node 语义例外；首次 DCE 不顺带做常假条件折叠 |

活状态的 clock 和 live SystemTask 的 clock 都可能是 GSIM 已删除而 GRH 合法保留的
依赖，但必须有到实际 clock operand 的完整证据，不能仅按 Node 名称含 `clock`
豁免。GRH 从活 state writer 与 SystemTask 的实际 operand 传播需求；GSIM DCE 对
state clock 显式沿 `Node::clock` 保活，SystemTask clock 是否进入其 `prev`/event
依赖则按具体 FIRRTL 语义与原生 ENode 证据核实。reset、memory 控制和动态 LHS
索引同样按实际依赖检查。

当前未解释 mismatch 的代表项 `difftest_timer$NEXT` 由 GRH 以
`implementation:system_task` 保留，GSIM 则以 `unobservable_state_family` 删除；
对应 `difftest_timer` current Node 已在两侧删除。该 `$NEXT` 和此前统计的
64,782 个同类 `$NEXT` mismatch 均不能归因于 clock。现有交换证据没有记录
触发 `activeState` 的 state operation kind、`regSymbol`、完整 owner 或活性来源，
因此尚不能判定是 DCE 状态族关联还是其他 operation liveness 传播错误；当前
证据也不足以把根因归到 hier-flatten。即使最终证明这是 GRH 额外建模的 live
effect/state dependency，也必须在该 Node 上给出 operation、operand 与真实语义
目标的证据后才能列为 explained retention；否则仍是未解释保留。后续需补足
原生 witness，再按证据修复。

SemanticId、来源名字和 trace 都不是电路保活根。GRH 继续按 op/value
需求分析，但须为叶 Node 建立明确的保留/退役规则：

- 保留仍有实际活跃边界、有效需求 anchor、活状态或副作用实现的 Node。
- `ops.empty()` 不是充分删除条件：input、合法零宽边界及有活 anchor 的叶可以没有定义 op。
- 物理 Value 因尚有 users 而保留，不自动表示它有有效位需求；区分占位值与有效边界，避免死 anchor 造成虚假保活。
- 同一 op 属于多个 Node 时，死 Node 可移除自己的归属，其他活 Node 的真实实现必须保持；不能把共享 op 的存活直接等同于所有 owner 均活。
- 若仍有无法安全归属的存活实现，明确保留并归因 residual；不能留下无主实现或为了数量一致误删。

这些判定由 pass 的实际需求及边界规则给出，不能由名称匹配率驱动。

## 5. kArrayUpdate 的 DCE 支持

### 5.1 输入契约与第一阶段

沿用 [GRH IR 定义](../../wolvrix/docs/grh/grh-ir.md) 的多维、有序、快照语义：

```text
r = ArrayUpdate(base, enable0, indices0..., data0, ...)
    {indexCounts=[k0,k1,...]}
```

每组先读取进入 op 前的不可变输入，后写覆盖前写；k=0 为整数组更新，
0<k<R 用前缀下标寻址剩余后缀轴的子数组，k=R 为单叶。
data.shape 必须等于 base.shape[k:]。四态控制使用既有逐叶 mux 语义，
X/Z 控制不能按 false 处理，确定写入 data 的 X/Z 必须保留。

复用 `ArrayUpdateView`、现有常量索引解析及 F30 几何检查。先建立正确的
保守路径：结果有需求时保留 base 和全部组的实际 operands；整个结果死亡
且 op 无其他可观察贡献时删除该纯 op。完成 Node 维护后才解除入口门禁。
该步骤打通流程，但不代替下一步精度验收。

### 5.2 有证据的更新组与位区间分析

令 D 为最终累计结果需求，按更新组**从后向前**分析；位坐标使用 F30 的
行主序平坦位图，映射到 data 时减去该组目标范围起点，保留全部数组轴。

| 更新组条件 | 需求与裁剪规则 |
| --- | --- |
| enable 确定为 0，或任一下标确定越界 | 该组没有贡献，可整体移除 |
| 静态合法目标 T，与 D 无交集 | 对所有当前可观察结果无贡献，允许裁去该组 |
| 静态合法 T，enable 确定为 1 | 向 data 传播 `D∩T` 的局部需求，再从前序需求扣除 T |
| 静态 T，enable 未知/X/Z | 保留 data、控制和 prior；不能从前序需求扣除可能保持旧值的区间 |
| 动态或不能证明的索引 | 保守保留可能贡献的 base、data 和控制；第一版不做未经证明的动态范围缩减 |
| 较晚的确定整数组覆盖 | 可以截断更早的动态组和 base 的需求；全部 RHS 仍遵守快照依赖 |
| 多组部分重叠 | 只扣除确定覆盖部分，保持后写优先级及未覆盖区间 |

例如 `[2,3]`、8 位叶数组：先动态写单叶，再以确定 enable 写整个数组，
结果只依赖后组 data；若后组 enable 未知，则前组与 base 仍可能贡献。
静态写 `[1]` 覆盖全局位 `[24,48)`，其 data 的局部坐标是 `[0,24)`，
不能把状态/数组全局位偏移直接套到较窄 payload。

裁剪必须修改真实 operands 与 `indexCounts`，然后再回收无需求生产者。
不能只停止标活 enable/index/data，却让存活 ArrayUpdate 仍引用可能贡献的
已删定义。所有组均被移除时，按等价性证明将原结果改为 base 的等宽
Assign 等合法形式；不能生成违反 M≥1 契约的空 ArrayUpdate。

位需求与 root reason 分别累计；reason 不增加但区间扩大时仍要传播。
按分析不动点的最终需求决定裁剪，避免早期局部需求导致过早删除。
不能证明的场景回到保守规则。禁止将动态更新展开为整数组 shift/mask、
逐成员动态 mux 或复制更新 op 来换取表面 Node 对齐。

## 6. 原生插桩与演化证据

两端复用现有公共格式，每次 DCE 输出五文件：

```text
before.nodes.tsv        before.connections.tsv
evolution.tsv
after.nodes.tsv         after.connections.tsv
```

nodes/connections 是 pass 前后独立捕获的静态实际图；evolution 必须在
pass 分析、删除及实现变更时记录，在 pass 结束时提交和导出。
不允许事后用 before/after 差集合成 evolution。

- 删除 Node 采用既有 `delete` 事件或删除事务中的 `decision outcome=delete`，记录具体 reason；GRH 同时写入结构化 `dce_deletion` 负面证明摘要：锚点/有需求锚点数、owned/live-owned op 数、端口/边界/state/memory/零宽分类。计数描述本端捕获事实，不把任一代表 operation 伪称为删除原因；无新成员，不产生 split/merge lineage。公开连接采用批量原生提交，逐 Node 原因仍分别保留，避免每个删除都触发全图扫描。
- 存活 Node 的内部组裁剪或归属更新可记录同 ID 的 `replace`；不解释成新 Node。
- 存活 Node 的 owned operation 被删除时，记录同 ID 的 `replace`，包含删除数量、
  operation ID 顺序 hash 和首末 ID；它证明 Node 内部实现集合变化，不替代逐边依赖因果证明。
- ArrayUpdate operand/index 组裁剪和未需求 operand 归零的 `replace` decision
  必须引用实际被改写的 operation ID。
- 删除原因至少区分无可观察需求、死状态族、无活端口 memory、死 owner/anchor、空路径回收；路径回收不计作 Node 删除。
- 保活证据包含根类别、实际依赖引用、状态族联动；ArrayUpdate 精化附更新组序号及需求/覆盖区间，必要时引用 index 证据。
- 原因来自 pass 的分析事实。删除证据覆盖全部实际删除 Node，不能只输出 sample 或用通用“DCE”替代可区分的原因。
- 沿用现有列和事件；decision outcome 扩展为 retain/replace/delete，两端 writer、通用 reader/replay 与兼容测试同时支持，delete decision 必须对应实际退役的 before Node。
- Graph 删除前捕获 ID、名字和成员上下文，提交后不引用死亡对象；GSIM 历史 allNodes 中的 DEAD 项不能再进入后态库存。

验收要求 `replay(before, evolution) == after`，涵盖全部 Node 与 connection
记录，不仅校验数量。保持 ID 的连接未改变时保留 connection ID；端点不得
死亡，unresolved/candidates 及 coverage 状态也参与精确重放。
失败、超时或中断不写成功 footer；两侧产物绑定同一输入 SHA、root、
pass instance、前后 snapshot 和实际二进制/源码身份。

## 7. 前后图比较与差异归因

### 7.1 冻结 before 对应关系，建立删除矩阵

从当前完整运行的 G0/S0 建立唯一候选，并经 S0→S1 桥接。G0/S1 的
候选固定后，仅以各端原生 ID 判定后态存活，禁止 DCE 后重新猜名字配对。

| 同一 before 候选对 | GRH 删除 | GRH 保留 |
| --- | --- | --- |
| GSIM 删除 | 双方删除 | **逐 Node 待解释**：检查 GRH 的根、状态族、组/位需求、anchor 或残留实现；有充分因果证据则 explained，没有则 unexplained 并导致验收失败 |
| GSIM 保留 | 允许的 GRH 额外删除，检查 GRH 删除证据及电路正确性 | 共同存活，进入连接和结构比较 |

验收门禁只失败于“GSIM 删除、GRH 保留且没有充分证据解释”的 Node；有证据的
保留作为 explained retention 单列，不要求 GRH 为匹配 GSIM 而删除。“GRH 删除、GSIM 保留”计入
允许的额外删除数，不作为方向性违规。精确相等不是本项目的删除质量要求。
只有 analyzer 给出的 `unexplained` 保留计入失败数。

原本无唯一候选的 Node 单列它在本端的删除/保活及证据，不混进上述分母。
同时报告两端总库存、共同 before 候选数、双方删除/单侧删除/共同存活数，
以及共同存活中仍保持一对一身份的比例。

### 7.2 比较完整连接，区分新增与继承差异

对 dependency、state_update、storage_read/write、external_binding 等 kind
分别比较；保留 unresolved 与覆盖状态，不把未解析边当作不存在。
共同存活 Node 的类型化边按固定 before 映射比较，循环状态关系使用原图，
不能先压成普通组合 DAG 而丢掉状态语义。

DCE 的真实依赖不应凭空增加。前后连接新增、存活端点间删边、解析状态变化
均单列；若由 ArrayUpdate 裁剪、原有保守边清理或公开边界变化产生，必须
给出具体运行时证据。新增且无法解释的连接属于验收失败。

每项差异归入以下有证据的阶段/原因，无法确定的保持 unresolved：

1. split 前后已存在的库存、拆分粒度、residual 或坐标表示差异。
2. GSIM 准备阶段的宽度/表达式/连接变化及 native prev 一致性问题。
3. DCE 根、真实依赖、状态/reset/clock/memory/副作用规则不同。
4. GRH ArrayUpdate 组覆盖与位需求精度、Node owner/anchor 生命周期差异。
5. 导出覆盖不足、候选不唯一、辅助 SV 范围等证据边界。

`dce_deletion` 说明某个 GRH Node 满足了哪个退役规则和判定输入；它不是某条
新增/删除 connection 的 mutation-time 因果记录。删除规则证据、operation-set
摘要与逐边 support witness 分别表述，不相互替代。

计划产物：`summary.json`、`node-deletion-matrix.tsv`、`node-name-changes.tsv`、
`node-differences.tsv`、`connection-differences.tsv`、`attribution.tsv`，
加两侧原生五文件和 GSIM preparation bridge。逐行关联 before/after ID、
事件/原因、根或依赖证据，所有分类之和必须闭合；不得套用 F21/v11 的
旧后态 ID、旧连接匹配或旧删除统计。

## 8. 实施顺序与验收

| 阶段 | 工作与完成条件 |
| --- | --- |
| F31.0 规则确认 | 固化本文规则表、命名/ID 不变量、GSIM 首次 DCE 与准备阶段边界；更正过时 DCE 文档 |
| F31.1 正常流程打通 | 迁移新树叶生命周期，接入两端原生事务/删除记录，ArrayUpdate 保守支持；通过回归后开放 DCE 门禁 |
| F31.2 ArrayUpdate 精化 | 实现静态组裁剪、逆序覆盖、局部 region 映射及动态后备；验证真实 IR 与观测值 |
| F31.3 完整图比较 | raw ingest 跑到首次 DCE，精确 replay、身份检查、删除矩阵与连接归因；修复已证明不正确的一侧 |
| F31.4 性能与收尾 | trace 开关结果一致、第二次 DCE 幂等；通过 §9 的 GSIM 性能门，记录剩余差异及证据边界 |

正确性回归至少覆盖：

- 死纯锥、端口、无定义 op 的合法 anchor、零宽边界、空树及共享 op 多 owner。
- 名字碰撞 `r_3/r_3_0`、current/NEXT、多维成员；活 ID/name/path 全部不变。
- 死/活状态族、门控/别名 clock、reset、writer 顺序、memory 读写联动及外部/effect 根。
- ArrayUpdate 的 k=0/前缀/单叶、多组重叠、静态/动态索引、超宽确定 OOB、enable=0/1/X/Z、未知索引、四态 data、快照别名和后写覆盖。
- 位需求延迟扩大、多个消费者需求并集、局部/全局坐标及 size-one 轴。
- 所有组删除后的合法 IR、仍可能贡献的 operand 定义、原生五文件完整 replay、无死亡端点和 trace 开关一致。

新增精度回归不仅检查删除数量，还运行 `grh.verify` 与独立数值/多周期
Oracle，对比相同可观察输出与效果。Node 注解开关不改变电路语义；Node
及连接的单侧删留差异必须能回溯到规则与证据。GRH 再次执行 DCE 应不再
发生电路/Node 变化；GSIM 至少验证库存、身份和公开图幂等。

构建、安装、测试及脚本执行均经项目 Makefile；实施时先添加 F31 目标。
日志及数据统一置于 `ptmp/firrtl-ingest/F31/`。本规划未预设 DCE 后数量、
匹配率或耗时，也不把 F30 已接受的性能记录自动视为 F31 验收通过。

## 9. 性能硬约束：DCE 必须接近 GSIM

用户明确要求：**DCE pass 的性能要和 GSIM 差不多。** F31 同时满足
正确性与性能才算完成；GRH 关闭和开启 semantic trace 的 DCE 都对照
**同一个 GSIM 无 trace 的首次 RemoveDeadNodes**，只允许合理抖动。
不使用较慢的 GSIM trace 模式放宽分母，不用 F30 的历史接受记录豁免本轮。

### 9.1 等价工作与计时边界

| 比较项 | 纳入 pass 本体预算 |
| --- | --- |
| GRH `dead-code-elim` | 活跃性及位区间分析、ArrayUpdate 组裁剪、op/value 删除、Node 归属和 anchor/binding 清理、死叶退役、路径回收、必要连接维护，以及开启 trace 时的现场记录与事务提交 |
| GSIM `RemoveDeadNodes#0` | 根和依赖遍历、DEAD 标记、Node/状态/memory 容器清理及 reconnectAll |

本体按原生 pass 入口到正常返回的 wall time 计时。实现拆成子函数或
延后提交，不得把正常流程必须完成的 Node/连接维护与 trace 现场工作移到
预算外。只有静态 before/after 快照插桩、TSV 导出和独立 replay/结构校验
另行计时；同时报告完整 DCE 边界成本及其相对 GSIM 本体的差值和比例。
Node 维护等子阶段可细分诊断，但不能从正式本体合计扣除。
复用现有 `benchmark_f29_pass_trace.py` 时须审计 `pass_s` 与
`semantic_exchange_finish` 的边界；若 finish 中仍有必要提交或连接收敛，
必须计回本体，不能直接照搬旧计时字段。

GSIM 的 DetectLoop/TopoSort/InferAllWidth 是准备阶段，不混进 DCE 分母；
GRH 的 split、后续 simplify 和全部前序 ingest 时间也不混进 DCE 本体。
完整 ingest→DCE 墙钟另列。不能把 split 的 **45.904 s/91.808 s** 套作
本轮 DCE 的参考时间或超时。

### 9.2 生产性能门与 trace 诊断

按最新验收口径，生产路径是关闭 semantic trace 的 GRH DCE。它继续对照同一
完整图 GSIM 无 trace 首次 DCE，并沿用相对 **3%**、绝对下限 **10 ms** 的固定
抖动带；GSIM 和 GRH no-trace 各至少三次有效完整图样本，以中位数判定。
trace 不在生产性能路径中，不再要求三轮或通过 3% 抖动门；至少运行一轮完整图
trace 作为诊断，并要求它在既有 **2×GSIM** DCE watchdog 内完成。该界限仅用于
排除明显失控的 trace 性能，不能替代 no-trace 的正式性能门。

```text
G = median(GSIM_no_trace_first_DCE_wall_s)
R_off = median(GRH_DCE_no_trace_wall_s)
R_on  = one-or-more diagnostic trace observations
jitter = max(G * 0.03, 0.010 s)
limit = G + jitter

R_off <= G            : pass
G < R_off <= limit    : within_jitter（允许，明确标注）
R_off > limit         : regression（失败）
R_on <= 2 * G         : trace diagnostic acceptable
R_on > 2 * G          : trace diagnostic too_slow

只有 R_off 参与与 GSIM 同阶段相近的生产性能验收。trace 样本仍绑定同一冻结
源码、二进制、输入和环境，完整记录本体及 snapshot/export 成本；trace 超过
2×G 或 watchdog 中止时，诊断失败并阻止 F31 完成。
```

不能按 Node/op 删除量或吞吐量归一化后，把实际耗时超限写成通过；
删除更多或语义更精确也不豁免性能门。未达标时定位并修复热点，再复验
相同正确性和对齐指标；F31 不标为性能验收完成。

独立硬超时按冻结的 GSIM DCE 中位数 **2×G** 派生。它只是提前失败上限，
不代表允许性能慢到两倍；即使没有超时，只要超过 limit 仍然失败。
不根据本轮结果放宽抖动带或选取更慢参考。

### 9.3 测量与实现要求

- 使用完整香山原始 FIRRTL，从正常 ingest 跑至本轮 DCE；小图只做正确性回归，不代替速度验收，不读取 checkpoint。
- 同机、同 CPU/线程策略、构建优化与实际参数；先串行冻结至少三次 GSIM 基准，供正式分母和 2×G 超时使用，再串行采集 GRH no-trace 至少三次和 trace 至少一次。冻结后的基准不按 GRH 结果重选；记录源码、二进制、输入 SHA、全部样本及中位数。
- 正式性能运行关闭结构校验、额外全图统计和 profiler；必要的低开销运行计数保留，正确性诊断运行单列，不混作正式性能样本。
- 记录 wall/user/system、峰值 RSS、before/after 实际工作量及 trace 开关。大型分析与原生运行串行执行，避免内存和 I/O 竞争。
- 关闭 trace 时不构造逐节点原因、路径文本或导出库存；开启时增量记录并批量提交，避免逐 op/Node 删除触发全图扫描、名称索引重建或全量连接重算。
- 不能关闭必要 Node 维护、丢失删除证据或改变保活规则换取速度；trace 开关的最终 IR 和公开 Node 图必须一致。
- 环境噪声超出固定抖动带时补做相同条件测量，保留较慢原始样本，不临时放宽门槛或只挑最快一轮。

最终表格至少列出 G、R_off、R_on、limit、差值、比例、判定，以及快照/
导出/校验和完整边界成本。尚未实测的数据保持未验收，不预填通过。

## 10. 实施与证据进度（尚未完整验收）

已实现两侧首次 DCE 的原生五文件、GSIM S0→S1 静态桥接、稳定身份删除合约、
GRH ArrayUpdate 逆序组需求与真实 operands/indexCounts 改写。GRH 为零需求但
仍占据拼接/数组槽位的值建立同类型内部零，避免删除生产者后产生新未定义依赖；
保留的 native source 引用按实际 operand 槽位重映射，不为合成零继承旧 source。

GRH retain 证据记录根类别、anchor/实际实现 op、首次产生需求的 op，唯一
consumer owner 可作为原生 Node witness。共享同一物理 anchor 的多个 Node
仍可能保守保留，以 `shared_anchor_demand` 明示；未能证明精确归属的活实现
以 residual 单列，不称作精确命名需求。residual 的判定不依赖已有 residual
标记或 op 遍历先后。私有 Node JSONL 仍只覆盖身份/成员；公共五文件是连接
精确 replay 的验收来源。性能 trace 的缓存后态仅用于性能样本，完整正确性
导出另开独立实际图校验，不将缓存自洽冒充实际图相等。

截至当前，已通过原生 DCE/ArrayUpdate、SemanticTree 与 pass-manager 回归；
8 个 raw FIRRTL fixture 各运行 trace 开/关完整前序流程，检查真实 IR、Node、
连接一致、身份不变、二次 DCE 幂等和原生计时。两个专项 AU bundle 独立
精确 replay，所有边已解析；8 个 fixture 中继承的 ambiguous 边原样保留或
随死目标删除，不能将这些 fixture 全部称为已完全解析。后续补丁须继续复验。

完整香山 GSIM 无 trace 的首次 DCE 三个原始样本为：

| 样本 | 本体 wall time |
| --- | ---: |
| reference-1 | 34.652619107 s |
| reference-2 | 34.590027680 s |
| reference-3 | 34.532081244 s |
| 中位数 G | **34.590027680 s** |
| 固定验收上限 | **35.6277285104 s** |
| 独立硬超时 2×G | **69.180055360 s** |

证据目录为 `ptmp/firrtl-ingest/F31/full-gsim/reference-{1,2,3}/`，包含原生
steady_clock JSONL、冻结二进制/源码身份、输入 SHA、全部日志及 RSS guard。
三个样本已完成，完整图性能验收见第 10.4 节。

### 10.1 候选版本与历史性能证据

`package-v2` 的完整图初步实测为关闭 trace **30.069679739 s**、开启
**36.285773439 s**。开启模式比固定上限慢 **0.658044929 s**，该候选
未通过性能验收；各只有一次样本，也不能据此给出正式中位数。
证据保留在 `full-grh/{no-trace-1,trace-1}/`，不删除较慢样本。

`package-v3` 收窄有结果 op 的公共 membership 通知，保留私有 observer、
实际 anchor、精确 boundary、状态及 fallback 读者通知；必要的连接维护和
提交仍在原生 pass 返回前完成。7 项原生兼容回归通过。冻结包的 raw FIRRTL
验证覆盖 8 个 fixture × trace 开关，实际 IR、Node 和连接一致，存活身份
保持，二次 DCE `changed=false`。10 份原生专项 bundle 和 8 份 raw bundle
均独立精确 replay；专项 bundle 的边完整且全部解析。raw fixture 遗留
`ambiguous-native-boundary` 为 F30SplitProjections 的 3→3 和 NodeEvolution
的 2→1，其余 6 个为 0→0，无新增未解析边。

完整图正确性导出开启独立实际图校验、结构校验与二次 DCE 幂等检查，单列为
诊断样本，不混入正式性能组。v3 的正式关闭/开启样本另建目录，各至少三轮，
保持同一冻结版本并交替串行运行。全部候选的历史性能证据继续保留。

v3 第一对正式原始样本为关闭 **30.050960409 s**、开启 **35.993696831 s**；
开启比固定上限慢 **0.365968321 s**，仍未验收，证据保留在
`v3-full-grh/{no-trace-1,trace-1}/`。后续候选继续优化逐条 decision 的存储与
字符串分配，现场捕获的事实、必要维护和 pass 内 commit 均不能删减。

`package-v4` 将 decision 改为紧凑记录：复用 pass/reason 模板、单 blocker
内联、多 blocker 连续保存，anchor/op/demanding-op 以数值现场捕获。导出
仅做确定性文本编码，reason/detail/ordinal 格式保持原样。独立审查确认
模板生命周期、扩容、跨事务与 abort checkpoint 安全；7 项原生兼容测试、
冻结包的 16 条 raw 流程及 18 份精确 replay 通过。完整图再次通过实际后态
核验、结构校验及二次 DCE 幂等，库存和 v3 相同。诊断本体为
**35.464762181 s**，仅作为诊断记录，正式三轮另行验收。

v4 正式第一组的 GRH no-trace 三次均有效：**30.344893001、29.754162855、
30.061342835 s**，中位数 **30.061342835 s**。trace 前两次为
**43.730061669、37.781680252 s**，均超过 35.627728510 s 上限，不能以
中位数抵销单轮性能回退；第三次在 DCE 前被外部 cgroup PSI 资源保护终止
（native summary 仍为 running、DCE timer 未生成），作为失败/无效环境样本保留，
不计入有效耗时。该批 trace 未通过性能验收。

trace-1 的 DCE 期间用户 CPU 34.863348 s、系统 CPU 8.860666 s；约 7.189 s
cgroup PSI 与 2,094,981 页 direct reclaim 增量同时出现。trace correctness 在
相当长度窗口内系统 CPU 1.171173 s、PSI 约 0.639 s。trace-2 DCE 系统 CPU
为 3.043 s，并伴随 PSI。环境有约 98 GB file cache/大量 dirty pages，因此
全图静态 TSV 输出可能污染后续 pass 的宿主缓存并增加回收压力；这些迹象
支持资源干扰假设，但不能证明 v4 的计算时间本身不超标，也不能把样本改判通过。

Decision 原生库存初始 reserve 为 9,476,863 项，而 trace footer 有 9,507,643
条（含 ArrayUpdate 内部 replace 决策）。v4 因此仍会在末尾发生 vector 容量
增长；按 56-byte 项和 libstdc++ 翻倍策略，最多额外申请约 1.06 GB 并搬迁约
531 MB。v5 以初始 N/32 余量和显式 N/32 增长消除这次翻倍；所有记录照常保留。
这项修复尚未经过完整性能验收。

宿主缓存回收不在 benchmark/pass 内执行。`POSIX_FADV_DONTNEED` 是 advisory，dirty
pages 不保证回收；绝不使用全局 drop_caches。v5 正式样本组开始前对已完成旧
exchange 文件做定向观测；每个 trace 样本结束后、下一轮启动前，对刚完成的五个
TSV bundle 执行同一观测。每个诊断独立写报告，pass 计时完全不包含诊断动作；
原始 v2-v4 失败样本仍保留且没有改判。v5 六个样本都从原始 FIRRTL 开始，交替
串行运行、共用相同 GSIM 分母，cache 控制条件按此协议一致。

`diagnose_f31_exchange_cache` 当时作为独立诊断 Make 目标实现（该一次性工具及入口
已在 F31 收尾清理），仅接受明确指定
F31_WORK 下的完整五 TSV bundle，拒绝其他文件及符号链接，记录每个文件的
mincore 驻留率、fadvise 返回码、inode/stat identity，以及 meminfo/cgroup/PSI
前后数据。它不执行 fdatasync、不写删换 TSV、不触碰全局 cache，报告明确说明
advisory 不保证回收；单测 5/5 通过。对 8 个已完成 bundle 的诊断请求总量
69,849,620,660 bytes，约 11.51 s；每个文件均从 100% 驻留到 0%，文件身份
不变。采样 cgroup file cache 从 93.33 GB 降至 23.48 GB，PSI some 累计只增加
约 0.124 ms。原始 JSON 在 `cache-diagnostic-v4/report.json`。

这证明旧静态 exchange 产物确实保留了大量干净 cache 页；它解释 v4 样本发生
回收压力的合理性，但不能单独证明 v4 的超限全由此导致。v4 性能失败样本仍
完整保留、不改判。v5 每轮 trace 结束后的报告分别位于
`v5-full-grh/trace-{1,2,3}/cache-diagnostic.json`；只对已经完成的静态 TSV
请求定向回收，并在每份报告中核验驻留变化及文件身份。该处理发生在 pass 外，
不计入 DCE，也不作为 DCE 算法提速。

### 10.2 完整图实际后态正确性

GSIM `full-gsim/correctness/` 与 GRH `v3-full-grh/correctness/` 均从同一完整
原始 FIRRTL 正常执行。两端在导出后态前，重新遍历实际 Node/连接图，核对
现场 trace 所维护的缓存；不以 replay 自洽代替实际图核验。GRH 另通过
`semantic_validate`、`grh.verify`，并实际断言二次 DCE 的 `changed=false`。

| 实际公开图库存 | GRH before | GRH after | GSIM before | GSIM after |
| --- | ---: | ---: | ---: | ---: |
| Node | 9,476,863 | 5,764,084 | 9,635,014 | 6,020,694 |
| connection | 15,288,964 | 9,026,371 | 15,568,445 | 9,506,107 |

GSIM 此处包含 memory 容器 Node，不能与日志中排除该容器的 `countNodes`
数值混用。GRH after 仍有 336,756 条未解析 dependency，GSIM 有 1 条未解析
external binding；这些边及其 candidates 全部保留在导出中，不将它们统计为
已完全解析。静态库存和实际图验证通过，跨端匹配及离线逐事件 replay 仍另验。

小图上已经实测 trace 开关的实际 IR/公开图一致；完整图两侧的诊断运行均为
trace 模式，正式无 trace 样本仅计时，不能据此宣称完整图已做 trace/plain
实际后态逐图对照。当前证明范围为公开 Node/连接图的结构和演化，不是整个
电路的全输入功能等价证明。

### 10.3 实施和回归

v5 实现了 `kArrayUpdate` 的多维、有序更新组需求裁剪，原位维护 operands 和
`indexCounts`，所有组消失时转为 Assign，并以同类型内部零维持仍需的槽位；
不产生逐元素位运算展开。DCE 仅删除公开 Node，存活 Node 身份、名字和路径
保持不变。Node delete/retain decisions 在 pass 中捕获；紧凑存储保留全部 witness
事实和原有导出文本。正式 timing 仍包含 GRH op/value/Node 和连接维护、evolution
捕获及 commit；trace 输出前后的静态导出/验证另列完整边界。

验证结果：

- 原生 DCE/ArrayUpdate 与 trace compatibility 七项 C++ suite 通过，覆盖跨多次
  decision 容量增长、多个 blocker、witness、ordinal、abort 和 exact TSV。
- `test_f31_pipeline` 在 v5 frozen package 上 2/2 通过；16 个 fixture/mode
  组合 IR/Node/连接一致、身份保持、二次 DCE 幂等；10 份专项 bundle 和 8 份
  raw bundle exact replay。无新增 unresolved 边；fixture inherited ambiguous
  边仍仅 F30SplitProjections 3→3、NodeEvolution 2→1。
- F31 performance contract 21/21、alignment analyzer 21/21、cache diagnostic
  5/5 通过；GSIM exchange 与 GRH exchange 源码均 `diff --check` 通过。
- v5 完整 XiangShan trace correctness 导出重新遍历实际公开图核验、
  `semantic_validate`/`grh.verify` 通过，二次 DCE `changed=false`。
- alignment analyzer 覆盖 GRH snapshot 未重复导出 root/input SHA 的兼容契约：
  两者从已验证的 DCE evolution header 继承；snapshot 若声明则必须相同。

### 10.4 完整图性能验收

v5 冻结包为 `package-v5`，GRH 与 GSIM 均使用完整原始 FIRRTL SHA
`b313a3ecd154cbd9279b14403709806b95fb136cf44b475e9def46a926ecb26b`、同机
Clang 22.1.2 Release `-O3`。GSIM 使用既有三个原始 no-trace 首次 DCE 样本，
`G=34.590027680 s`、上限 `35.6277285104 s`、硬超时 `69.180055360 s`。正式
样本固定路径为 `v5-full-grh/{no-trace,trace}-{1,2,3}/summary.json`，所有运行
完整 ingest；trace 开关按 off/on 交替，同一 frozen package 与参考分母。

| 模式 | 三次 GRH pass wall（秒） | 中位数 | 相对 GSIM | 与 GSIM 差值 | 判定 |
| --- | --- | ---: | ---: | ---: | --- |
| 无 trace | 29.945212193, 29.654194348, 29.814568445 | 29.814568445 | 86.19% | -4.775459235 s | pass |
| 有 trace | 34.547200168, 34.687910816, 34.927274048 | 34.687910816 | 100.28% | +0.097883136 s | within_jitter |

固定抖动 `max(3%G,10ms)=1.0377008304 s`。两种模式每个单轮都低于
35.6277285104 s，且没有样本触发 `2×G` 硬超时；比较器报告
`status=passed`、`hard_limit=passed`。原生 DCE median 分别 29.565940258 s 和
34.424437402 s；trace 模式的完整 before/after exchange 设置+导出中位数分别
21.502585076 s 和 20.736553840 s，完整 DCE boundary median 76.959854286 s。
这些静态导出不从 pass wall 中扣改，但单独报告；`within_jitter` 表示在允许
范围内，不表示严格快于 GSIM。

机器可读结果和 TSV 在 `v5-full-grh/performance-comparison/`；原始六样本和三
份 cache 诊断报告均保留在 `v5-full-grh/`。v4 的未通过组保留在 `v4-full-grh/`，
后续结果没有覆盖或删除失败证据。

### 10.5 完整图 DCE 对齐与差异归因

完整归因使用同一 SHA 的 F31 GRH DCE、GSIM 首次 `RemoveDeadNodes#0`、
GSIM preparation bridge 和 splitArray bundle。运行从既有原始 exchange bundles
重放，不重新 ingest FIRRTL。结果在 `ptmp/firrtl-ingest/F31/v5-alignment-final/`；
`report/summary.json` 为 `complete=true`、`passed=false`。该历史报告曾按旧单向
删除契约把 GSIM 删除而 GRH 保留的 **110,668** 个 Node 标成方向性违规；此标签
不再是现行验收结论，这批 Node 应按 §4.2 逐项归因。另有 GRH DCE 后 **156,181**
条新增公开连接需要语义复核。报告生成时的旧摘要只列出了连接 issue，不能视为
当前解释性门禁的验收结果。

| DCE 实际 Node 库存 | GRH | GSIM |
| --- | ---: | ---: |
| before | 9,476,863 | 9,635,014 |
| after | 5,764,084 | 6,020,694 |
| 删除 | 3,712,779 | 3,614,320 |
| 新建/改名存活 Node | 0 / 0 | 0 / 0 |
| 带原生删除轨迹的实际删除 | 3,712,779 | 3,614,320 |

从 split 前状态冻结唯一 name-path 候选，共 9,472,866 对；其中 5,650,140
对两侧都存活，占 **59.6455%**，共同存活 Node 的 ID/name/path 一致率为
**100%**。矩阵为：双方删除 3,492,336，双方保留 5,650,140，GRH 删除而
GSIM 保留 219,722，GRH 保留而 GSIM 删除 110,668。另有未能唯一配对的
GRH 3,997 个和 GSIM 162,148 个；它们按本端删留状态保留在
`node-differences.tsv`，未混入固定配对分母。双方实际删除都被运行时轨迹
覆盖，generic deletion reason 数为 0；原因标签、逐 Node 证据及连接差异分别
见 `node-deletion-reason-counts.tsv`、`node-deletion-matrix.tsv` 和
`connection-differences.tsv`。

阶段桥接核对通过：GSIM S0→S1 的 9,635,014 个 Node 身份不变，公开连接键
没有变化；split after 与 preparation before、preparation after 与 DCE before
的快照匹配。DCE 图的跨端连接差异中，1,254,981 条属于 split 时已有差异，
170,328 条被归到 DCE 阶段出现。GRH after 有 336,756 条 unresolved dependency；
GSIM after 有 1 条 unresolved external binding，均保留在导出中。

| DCE 连接变化 | GRH | GSIM |
| --- | ---: | ---: |
| 删除且 incident to deleted Node | 6,227,346 | 6,062,338 |
| 删除但两端 Node 均存活 | 191,428 | 0 |
| 新增且两端 Node 均存活 | 156,181 | 0 |

GRH 的 156,181 条新增边全部为 dependency：129,272 条 unresolved，26,909
条 resolved。原生轨迹将它们记录在 DCE 的 `replace` 事件下，事件原因是
`complete-pass:dead-code-elim`，没有逐边的 producer/IR 依赖因果证据。代表性
样本中，before 的 `prefetcher.io.metaRead.resp.entries.bits.code_0_0` Node
已被删除，而 target `prefetcher._s1_sramMetaInfo_selectedEntry_T_4` 存活；after
出现从 `ctrlUnitOpt.io.injecting` 到该 target 的 resolved edge，以及来自
`metaArray._WIRE_3.bits.code`、`metaArray._WIRE_2.bits.code_0` 的 unresolved
候选边。这个样本证明公开边集和来源解析状态发生了变化，不能单凭 trace 判定
这些新边等价、错误，或必然来自真实 IR 的新依赖。因此 analyzer 按契约将这
156,181 条边标记为 `requires_semantic_review`，全图验收保持未通过，不把它们
作为已解释的 DCE 结果。

本次 analyzer 的 identity 兼容修复只接受 GRH snapshot 省略 root/input SHA，
并以该 bundle 已验证的 evolution header 为依据；若 snapshot 声明了不一致值
仍拒绝。单测 21/21 通过。全图 replay、矩阵和连接比较本身已完成；后续若要
将 F31 标为整体通过，需给新增连接补上可检查的 IR/owner 因果归属，或证明并
修复产生错误边的一侧，再重跑相同全图归因。

### 10.6 operation 变更证据补强（待完整图复验）

为缩小 connection change 的因果盲区，GRH exchange 现在在实际删除 owned
operation 时按 Node 汇总删除数、operation ID 顺序 hash 及首末 ID；不把
operation/enode 列表加入静态 Node 格式，也不为全部公开连接增加 provenance
字段。DCE 的 ArrayUpdate 和未需求 operand 替零 decision 同时引用具体改写
operation ID。小型原生 trace 回归与 exchange replay 已验证格式可重放。

该摘要只能证明对应 Node 的内部 operation 集合确实变化，不能单独证明某一条
新增 connection 是该 operation 变化的正确结果。v7 完整图还新增了逐条
connection 的 after-state support witness，见 10.8。operation 摘要与这些 witness
都不能单独证明某一条新增 connection 是哪次 DCE operation 改写造成的。10.5
中的 `passed=false` 状态不变；mutation-causality trace、跨端语义归因、
trace/no-trace 完整图一致性和修改后的 GSIM 性能门仍待验收。

### 10.7 v6 单次 trace 性能样本（完整图验收未更新）

`v6-trace-evidence-check/performance-trace-1/` 已从原始 XiangShan FIRRTL 完整
跑过 ingest、comb、split 和首次 DCE，guard 正常返回，summary 为 `passed`；
输入 SHA 与 v5 相同。单次 trace DCE 的 wrapper wall 为 **34.568198951 s**，
native pass timer 为 **34.326622979 s**；冻结 GSIM 中位数 `G=34.590027680 s`，
wrapper wall/G 为 **99.94%**，该样本本身低于 G。完整 DCE boundary（含快照设置
和导出）为 78.623137878 s，整次 raw-ingest 流程为 213.462576624 s，最大
process RSS 为 83,676,100 KiB。

该目录约 **8.6G**，其中 evolution TSV 约 4.76 GB；后续边级分析应复用这份
bundle，避免重复导出。它只有一轮 trace、没有对应的 v6 no-trace 样本，且
`verify=false`；因此它是性能观察样本，不构成三轮中位数门禁或完整图正确性/
alignment 验收。10.5 中 156,181 条新增连接的语义归因状态保持未通过。

### 10.8 v7 完整图逐边 after-state support 验证

当前源码与依赖冻结为
`v7-connection-evidence/package/identity.json`，从原始 FIRRTL 运行，没有加载
checkpoint。输入 SHA 与前序样本相同；GRH `verify=true`，exchange 在 DCE 后重走
实际图并对 bundle 做完整 replay。流程耗时 246.181 s，最大 RSS 为
86,111,184 KiB；其中 GRH native DCE 为 **34.589088454 s**，wrapper pass wall 为
**34.822957031 s**。冻结 GSIM 中位数 `G=34.590027680 s`，native DCE 为
99.997% `G`；单轮 wrapper wall 也低于 `G + max(3%G,10ms)`。这是一次带完整
校验的诊断样本，不替代三轮性能门或 full-graph trace/no-trace parity。

`evolution.tsv` footer 和 Python replay reader 对新增 dependency 的 ID 集合做
精确覆盖校验：请求数 **156,181**、有 witness 的连接数 **156,181**、witness
记录数 **289,875**、`missing_native_boundary` 数 **0**。witness 把边连接到最终
图中找到的 source Node、target Node、value、消费侧 operation/operand；若有
boundary reference，还记录 reference operation/operand；并记录 value 的定义
operation。Unresolved edge 的 supporting Node 必须属于该边候选源集合。

完整 replay 返回 `replay_exact=true`，before/after 节点数分别为 9,476,863、
5,764,084，connection 数分别为 15,288,964、9,026,371。reader contract
47/47 通过，GRH 的四项 F31 C++ 回归 4/4 通过。bundle 为 **8.8G**，其中
evolution TSV 约 4.6G；F31 工作目录约 142G，验收后文件系统可用空间约 790G。
本次没有重跑全图跨端 SQLite/TSV analyzer，也没有复制第二份大 bundle。

这些记录严格是 `postpass-native-walk` support evidence：它们证明每一条新增边
能由 DCE 后 GRH 图中的边界引用或 value ownership 规则重新导出，并由 reader
核对端点和候选源。它们不是 DCE mutation-causality trace，不能回答具体哪次
operand rewrite、operation 删除或 Node 裁剪导致该 edge 新增，也不证明该边和
GSIM 的对应关系语义正确。故 10.5 的 156,181 条连接仍是
`requires_semantic_review`；后续需补 mutation-time 证据，再据证据修复并重验。

### 10.9 v10 owner-set 缓存诊断

v10 使用当前 working-tree 源码冻结包 `v10-owner-cache/package/`，从相同 raw
XiangShan FIRRTL 完整运行，复用三份 GSIM 首次 DCE 样本。trace、连接 evidence、
实际图校验和二次 DCE 幂等检查均开启。性能参考仍为 `G=34.590027680 s`，
允许上限为 `35.6277285104 s`，独立 watchdog 为 `69.180055360 s`。

完整图实际校验通过，第二次 DCE 为 `changed=false`；Python reader 返回
`complete=true`、`replay_exact=true`。Node/connection 数量与 v7-v9 相同：before
分别为 9,476,863 / 15,288,964，after 分别为 5,764,084 / 9,026,371。mutation
记录为 57,966 条；新增连接 evidence 请求和连接覆盖均为 156,181，witness
记录 289,875，缺失支持数为 0，但精确匹配 mutation 的 witness 仍为 0。
因此 replay 与 after-state 支持证据通过，mutation 因果归因仍未建立。

本轮 native DCE 为 **46.406547690 s**，wrapper pass wall 为
**46.644289456 s**，超过 GSIM 上限；最大 RSS 为 84,794,388 KiB。pass 计时不含
静态 snapshot 导出，但包含 DCE 所需维护、commit 和 mutation trace 捕获。全程
资源 guard 正常完成，完整图 validation 通过；这不改变性能门未通过的结论。

该轮资源样本显示 DCE 期间 PSI `avg10` 曾达到 36.16%，高于 25% 的保护线的样本
共 32 条，dirty file cache 在约 2.49–8.52 GiB 间变化；guard 没有观察到达到其
连续超时条件。与 v9 相比，v10 wall 增加约 4.59 s，其中 user CPU 只增加约
0.39 s，system CPU 增加约 4.20 s。因此这轮性能结果不能单独归因于 owner-set
缓存算法，也不能据此判定该缓存无效；PSI 和写回压力是明确的混杂因素。

跨版本诊断还显示，v8 在不导出 mutation owner list 时 native DCE 为
**34.930336723 s**；v9 逐条复制、排序 owner list 时为 **41.812282667 s**；v10
在 exchange 端缓存 owner set 后为 **46.406547690 s**；v11 将 owner span 查询移到
cache miss 后，native DCE 为 **40.003954645 s**。`Graph::opSemanticIds()` 返回
`std::span<const SemanticId>`，不是 vector；v10 调用端没有逐条分配 owner vector。
v11 将 span 查询次数从 57,966 降至 13,394 个不同 operation，但 v10→v11 的 wall
改善不能归因于此，因为 user CPU 基本不变而 system CPU 明显下降。

v11 的 trace native DCE 仍高于 **35.6277285104 s** 上限；该轮 PSI `avg10` 峰值
18.95%，未超过 25% 保护线，dirty file cache 从约 2.49 GiB 升至 8.48 GiB。
v11 的同阶段无 trace 参考来自相邻的 v10 冻结包：native DCE **29.528851210 s**，
低于 GSIM 中位数。当前 DCE 的 observer 仍使用 node-based
`std::unordered_map` 做 operation owner-set 查询；下一项实现尝试改用已有的
`slang::flat_hash_map`，减少逐 owner-set 的独立节点分配。该替换需经原生回归和
新的全图 trace 实测，不能预先记为性能修复。

性能门仍标记为**未通过**。PSI、dirty-page 写回与 DCE wall 的关系尚未被证明；
后续样本需同时核对资源曲线，并在低干扰条件下复测后再归因。

本 bundle 约 **8.9G**，全图运行结束后文件系统可用空间约 **761G**。本轮没有
覆盖或删除历史样本，也没有重跑完整跨端 analyzer。

### 10.11 GRH Node 退役判定的结构化证据

GRH DCE 的每条 `decision outcome=delete` 现在额外携带 `dce_deletion`。该对象
保留规则名、anchor 总数与有需求 anchor 数、Node owned operation 数与当前
live-owned operation 数，以及 `port_root`、`protected_boundary_root`、
`state_family`、`memory_node`、`zero_width_boundary` 分类。特别地，
`dead_owner_anchor` 可同时显示该 Node 的 anchor 无需求、但仍有 operation 因
其他 owner 而存活；因此不会把“operation 活着”错误解释为该 Node 必须保留，
也不会把代表 op ID 写成删除原因。

这些统计只在 SemanticNode exchange observer 开启时收集，沿用现有 anchor 和
operation-owner 扫描；无 trace 路径不分配统计数组。`transform-dead-code-elim`
回归用 `r_3/r_3_0` 案例核对了 retired Node 的 1 个 anchor / 0 个 demanded
anchor / 2 个 owned op / 1 个 live-owned op，并确认 retain witness 的
`demanded_by_operation` 没有被伪用于 delete。四项 F31 C++ suite 通过。

公共 Python exchange verifier 现在也校验 `dce_deletion` 的精确字段、规则名、计数边界、
分类类型及其与 delete decision 的一致性；旧 GSIM 和历史 bundle 可继续读取。Analyzer
报告结构化删除证据覆盖的 Node 数和按原生规则分组的数量，完整 detail 仍保留在 Node
matrix 证据中。exchange 合约 50/50、F31 analyzer 21/21 通过。

这是退役规则输入的本端证据，不构成 GRH 与 GSIM 的 Node 生存差异归因，也不
解决 §10.5 中 156,181 条新增 dependency 的 mutation-time 因果链。新的全图
trace 导出及复验尚未运行；v12 正式性能组仍按 §10.10 保持未完成。v13 包随后
加入本节描述的结构化证据，不能沿用 v12 性能样本作为 v13 性能结论。

### 10.10 v12 冻结包性能复测与磁盘记录

当时的 v12 冻结包位于 `v12-flatmap-final/package/`，其源码内容 SHA256 为
`8d893ef394235d6e4d9498f51799fbf7aea5ba3e276e0c9e78bc040365ed13e7`，完整输入
仍为原始 SimTop FIRRTL，SHA256 与 §2 相同。GSIM 三个正式参考样本未变，
`G=34.590027680 s`、允许上限 `35.6277285104 s`、独立 DCE watchdog
`69.180055360 s`。

目前只存在一份可计入性能组的 v12 no-trace 样本：`no-trace-1/summary.json`
报告 DCE boundary **29.945410237 s**、native timer **29.661822852 s**，pass
返回成功。`full-trace-1/summary.json` 的 pass wall 为 **35.372179452 s**，但
开启了完整验证并导出 8.8G exchange bundle；这是正确性诊断样本，不纳入正式
性能组。它不能与 `no-trace-1` 一起构成正式三轮交替样本。

之后四次全图尝试均被资源 guard 在 `xmr-resolve` 阶段终止，尚未进入 DCE，
不得计作慢速 DCE 样本或门禁失败：`trace-perf-1/`、`no-trace-2/`、
`perf-no-trace-2/` 和 `perf-no-trace-2b/`。guard 记录均为
`reason=cgroup_pressure`；触发时 cgroup PSI `avg10` 为 **29.00–45.39%**，
GRH 进程峰值 RSS 为 **62.45–74.43 GiB**。这表明运行环境当时存在持续内存
回收压力，不能据这些中断归因于 DCE 实现。停止时没有遗留基准进程。

磁盘复核时 `ptmp/` 总占用约 **832G**，F31 v12 目录约 **8.9G**，文件系统
尚余约 **743G**。历史对齐报告中的大 TSV 与已完成 trace bundle 均保留；四个
失败尝试各只留下约 3 MB 的日志/资源样本，本次没有删除或覆盖任何证据。

v12 包按当时的验收规则记录为未完成。按当前更新后的规则，无 trace 仍缺两次
同一 v12 冻结包样本；trace 的完整验证运行不能用作低开销 trace 诊断样本，需
另有至少一次关闭校验的 trace 运行。v12 历史结果不并入当前 v14 包的正式组。
下一次复测应在 cgroup PSI 稳定低于 guard 线时，从正常原始 FIRRTL ingest
开始，按 no-trace/trace 串行交替补齐；不得复用 checkpoint 或把 v5 样本并入
v12 中位数。全图连接归因的 156,181 条新增 GRH dependency 仍按 §10.5 标记
`requires_semantic_review`，本轮没有用重导出或离线名称猜测替代 mutation-time
因果证据。

### 10.12 v13 当前包与资源中断

v13 冻结包位于 `v13-current/package/`，其源码内容 SHA256 为
`33c2984028a85dadcd2c1cf9c635d8cdc50f1a3151eed85cfc1c8d9e9f96730c`。相对 v12，
本版增加 GRH DCE 删除 decision 的结构化 `dce_deletion` 证据及对应 verifier 和
回归；这不是 DCE 性能优化。相关 exchange 合约 50/50、F31 analyzer 21/21、
原生 DCE C++ suite 4/4 已通过，实际删除 bundle 的 replay 为 `replay_exact=true`。

v13 唯一全图性能尝试 `v13-current/no-trace-1/` 从原始 FIRRTL 开始，在
`xmr-resolve` 完成后、DCE 开始前被 resource guard 中止。summary 记录
`reason=cgroup_pressure`，采样时 GRH 进程 RSS 约 62.9 GiB、所在 cgroup 内存约
173 GiB，memory PSI `avg10=40.38%`；没有 DCE timer，因此它不是 DCE 超时或性能
失败，也不构成有效样本。v13 的 no-trace 与 trace 有效性能样本目前均为 0；
v12 的单次 no-trace 结果不能并入 v13。

当前资源只读检查：F31 证据目录约 189 GB，文件系统可用约 743 GB；主机可用内存
约 181 GiB，swap 已用约 7 GiB。v13 中止目录约 108 MB。本记录没有删除历史产物，
也没有启动全图任务。下次性能复测需等待资源压力稳定，并串行从原始 FIRRTL
执行；每个新全图 trace 预计约占 8.9 GB，应预留足够空间并持续监测 cgroup PSI。

### 10.13 v8–v13 实现迭代简表

| 版本 | 主要变化 | 可用性能证据 |
| --- | --- | --- |
| v8 | mutation trace 基线 | 单次 trace 诊断：native DCE 34.930 s；不构成三轮门禁 |
| v9 | mutation 记录增加 owner-list 复制与排序 | 单次 trace 诊断：41.812 s，超过 GSIM 上限；另一轮被资源 guard 中止 |
| v10 | exchange 侧缓存 operation owner set | no-trace native 29.529 s 单次观察；trace 46.407 s 且受 PSI/系统时间干扰 |
| v11 | owner span 查询移至 cache miss，减少查询次数 | 单次 trace native 40.004 s；没有同包 no-trace 对照组 |
| v12 | owner-set 容器改用 flat hash map | 单次有效 no-trace native 29.662 s；一次完整验证 trace 35.133 s 为诊断样本；三轮门禁未完成 |
| v13 | 为 Node 删除 decision 增加结构化退役规则证据 | 全图尝试在 DCE 前因 cgroup PSI 中止，DCE 样本为 0 |

这些是不同源码/二进制包的历史观察，不可跨版本拼成性能组。性能门仍以同一
冻结包、完整原始 FIRRTL、GSIM 参考及三轮串行样本为准。

### 10.14 Candidate-prune 事务证据（小图通过，全图待验）

当前工作树的 GRH exchange 在 Node 删除的 native commit 中识别严格的
unresolved dependency 候选裁剪：before connection 必须在同一事务被删除；after
connection 必须是同 target/kind/reason 的新 ID，且候选集合恰好等于旧候选减去
同一事务退役的 Node。来源不唯一或结果不匹配时不产生 transition evidence。
evolution header 声明 `connection_transition_trace=candidate-prune.v1`，事件证据
记录 source connection、created connection 和被删候选 Node；reader 对这些关系
逐项校验。该证据覆盖候选过滤这类结构变化，不宣称证明更深层逻辑依赖等价。

原生小图用 `[A,B,C] → [B,C]` 验证删除 A 后的连接演化，`grh-semantic-tree`
1/1 通过；独立 exchange reader 返回 `complete=true`、`replay_exact=true`、
transition evidence 1 条。公共 Python exchange contract 52/52 通过，覆盖正确
重放与伪造 transition 拒绝。小图产物位于
`ptmp/firrtl-ingest/F31/native-transition-tests/`，新增 reader 产物约 20 KB。

F31 analyzer 已接入这一已验证表：有确证的 connection 差异单独归类为
`introduced_by_dce_candidate_prune`，其他新增 dependency 继续要求语义复核。
小型 analyzer 回归 22/22 通过，验证 within-DCE 和 cross-engine GRH after-only
视图使用相同分类、状态和原生证据；无 transition 证据的新增边仍为
`requires_semantic_review`。该更改尚未对完整 XiangShan bundle 验证；它不能直接
回答 156,181 条新增边中有多少能由候选裁剪解释。完整 trace 尝试及资源中断
见 §10.15。

### 10.15 v14 全图尝试与 cache 复核

v14 包位于 `v14-current/package/`，working-tree source content SHA256 为
`6731110501d790dfbb39bd8cc659c0bcd4ac623033c536a7eaa753b05377add2`，native
library SHA256 为 `6bd31f07c86545287f14abb773ce7289f26ccc38a87c49715a8d309e96d3bbd9`。
两个 raw-ingest pipeline fixture 通过（2/2），exchange contract 52/52、
`grh-semantic-tree` 1/1、F31 analyzer 22/22 通过。

新的 `full-trace-candidate-prune-1/` 从原始完整 FIRRTL 开始，ingest 用时
47.78 s，随后在 `xmr-resolve` 完成后触发资源 guard；没有进入 hier-flatten、
split-static-array 或 DCE。中止采样的进程 RSS 为 **66.66 GiB**，cgroup 内存为
**179.64 GB**，PSI `avg10=28.46%`。这是 `cgroup_pressure` 中断，不是 pass 超时、
DCE 性能失败或功能失败；目录约 **3.2 MB**，没有完整图 exchange 文件，不能用于
F31 对齐或性能报告。

中止后 cgroup 仍有约 **110.5 GB** inactive file cache。按既有诊断工具，对 v7–v12
六个已完成 bundle 请求了合计 **56.12 GB** 的五文件 TSV `mincore/fadvise` 观测；
文件身份全部不变，实际驻留接近 0，cgroup file cache 仅减少约 **8 MB**。因此这
六个 bundle 不是本次主要 cache 来源，不能据此认定 cache 处理解决了资源压力。
诊断报告为 `v14-current/cache-diagnostic-after-guard.json`。再次运行前需等待
cgroup 压力稳定，并重新评估可用内存；本轮不在相同条件下立即重试。

### 10.16 v14 性能复验与完整图归因

按 trace 仅作诊断的性能口径，v14 完整图正式 no-trace 三轮使用 GSIM 首次
`RemoveDeadNodes#0` 中位数 **34.590027680 s** 作生产性能参考。GRH 三轮为
**29.896948902、30.330890972、30.004222121 s**，中位数 **30.004222121 s**，
为 GSIM 的 **86.74%**；正式上限 `G + max(3%G,10ms)` 为 **35.627728510 s**，
三轮均低于上限，判定通过。trace 诊断单轮为 **41.785219844 s**，为 GSIM 的
**1.208 倍**，低于 `2×G = 69.180055360 s` 诊断上限。比较器报告
`status=passed`、`hard_limit=passed`；性能合约测试 **22/22** 通过。机器可读
报告及样本位于 `v14-current/perf-relaxed/performance-comparison/`。

完整图 alignment 使用相同 SHA 的 v14 GRH DCE bundle 与 GSIM DCE、preparation、
split bundles。分析完整结束，GRH/GSIM exchange 均 `replay_exact=true`，报告
`complete=true`、`passed=false`。按当时的单向删除契约，固定候选中的 **110,668**
个 GRH 保留、GSIM 删除 Node 被标成删除方向违规；该判断已由 §4.2 的解释性门禁
取代。另有 GRH DCE 后 **156,181** 条新增
dependency 连接需要语义复核，其中 **129,272** 条 unresolved、**26,909** 条
resolved；此次 GRH evolution 声明启用了 `candidate-prune.v1`，但 footer 的
connection transition evidence 数为 **0**。当前 matcher 只接受同一事务中旧的
unresolved candidate edge 被删除，且新候选集合严格等于旧候选减去该事务删除的
Node。零条匹配说明这些新增边不符合该精确投影关系；不能据此推断 operation
改写等更广义的因果关系不存在。
这不是资源中断，也不代表这些边已被证明错误；它们仍是未解释差异。

| v14 DCE 对齐指标 | 数量 |
| --- | ---: |
| 冻结的唯一 before 候选 | 9,472,866 |
| 两侧都存活的候选 | 5,650,140（59.6455%） |
| 双方删除 | 3,492,336 |
| GRH 删除、GSIM 保留 | 219,722 |
| GRH 保留、GSIM 删除（旧口径待归因） | 110,668 |
| 共同存活身份保持 ID/name/path | 100% |
| GRH 删除且 incident 的连接 | 6,227,346 |
| GRH 删除但两端存活的连接 | 191,428 |
| GRH 新增且两端存活、待归因的连接 | 156,181 |

跨端 after 图差异中 **1,254,981** 条继承自 split，**170,328** 条归于 DCE
阶段出现。完整产物位于 `v14-current/perf-relaxed/alignment/`；报告和 TSV
共约 **133 GB**，本轮没有清理它们。文件系统剩余空间约 **602 GB**。性能门
已完成；F31 尚需按修订口径解释 GRH 保留并补齐新增连接的 mutation-time 证据，
再重新通过完整图归因。允许的 GRH 额外删除单列报告，不要求为了匹配 GSIM 而
恢复这些 Node。

clock 例外核查补充：GSIM split-before 中 `cpu.l_soc.socMisc.clock` 有
`live_clock_dependency` 证据，属于真实活状态时钟。旧审计只确认
`cpu.l_soc.io.clock` 的 GSIM 状态 clock target 链为空；这没有排除该 Node 是 live
FIRRTL `SystemTask` 的 clock operand，因此不能沿用“不是 clock 例外”的结论。
必须用完整的 source/value/user/operand slot 和 live SystemTask 根证据复核。FIRRTL
lowering 目前已补充 SystemTask clock 的精确 boundary use；DCE 必须只沿 live
target、实际 live operand 槽传播并导出 witness。hier-flatten 保留 SemanticNode
身份并合并物理 Value 是 F28 的既定表示，不能单独说明保留正确或错误；名称、
层级和 reason mask 均不能构成豁免。

### 10.17 验收口径修订与保留 witness

GSIM 删除而 GRH 保留不再自动算失败。全图 analyzer 改为输出
`node-retention-explanations.tsv`，其中每个固定候选 mismatch 都列出
`explained` 或 `unexplained`、证据类型和原生 witness；只有未解释数为 0 才通过。
例外必须能从具体 GRH Node 沿真实 Value、live operation、operand slot、state 或
effect 依赖到活动根。`clock` 名称、`system_task` reason mask 和宽泛 owner 标签
不能单独作为解释。

SystemTask 的 clock operand 位于最后一个 operand。FIRRTL lowering 输出指向实际
task/user、clock Value 和 clock operand slot 的 `kind=clock` boundary use；DCE 同时
记录 live task 的最后一个 operand slot 与 Value。analyzer 只有在 boundary source、
target、user、slot、Value 和 target Node 的 SystemTask root witness 全部相同时才
接受。活状态时钟同理：state writer 记录 `firrtl.clockOperand`，保留证据同时带出
active writer 的 slot 和 Value，analyzer 要求与 boundary use 完全一致。其余保留
继续列为 unexplained，不能因为加入了 clock/system-task 类别就批量通过。

旧 v16 交换 bundle 只有 `demand:*`/`implementation:*` 标签和部分数值 witness，
没有新版本的 operand-slot/root 证据，不能在本修订口径下追认为 explained。已有的
44,562 只是旧单向门禁下的 mismatch 计数，不是修订后的未解释数。

### 10.18 精确 root witness 与当前验证状态

DCE 的 retained decision 为 SystemTask clock 导出 `effect_root_operation`、
`effect_root_clock_operand`、`effect_root_clock_value`；state writer 对应导出
`active_state_operation`、`active_state_clock_operand`、`active_state_clock_value`。
analyzer 的正例要求 boundary 的 user、operand slot、value 与 root witness 一致；
错 slot、错 value、错误 boundary kind 都不能将 GRH 保留归为 explained。FIRRTL
register、memory writer 和 SystemTask lowering 现在记录 clock operand 索引，并将
clock boundary reference 关联到实际消费操作。

精确 operand-use 检查也找出 `kArrayUpdate` liveness callback 原先没有传 operand
槽位的问题：boundary source 虽然已随组压缩重映射，活下来的下标仍因 wildcard
记录而被拒绝。现在 base、enable、各维 index 和 data 都带原始 operand 槽传播；
对应的 native 回归已覆盖组压缩后的动态下标来源。

当前实现快照为 `v17-current/package-v3`，source content SHA-256 为
`778bb5a6fba86d594460826730a567bf26e61085a33f5c2ce63dc2160aee629f`。28 项 F31
alignment analyzer 测试、5 项 native DCE/FIRRTL 测试全部通过，native 覆盖也检查
实际 state-writer trace 的 `active_state_clock_operand/value`。完整 XiangShan raw
FIRRTL trace 尚未完成：`full-grh-trace`、`full-grh-trace-retry1`、
`full-grh-trace-retry2`、`full-grh-trace-v2` 和 `full-grh-trace-v3` 均被默认资源
guard 在 FIRRTL 初始化阶段终止，原因是 cgroup memory PSI 连续 8 秒超过 25%；
最新 v3 的 RSS 约 50.9 GiB、cgroup memory.current 约 168.5 GiB，触发时 PSI avg10
为 28.58%。这些尝试都没有完成 `read_sources`，没有进入后续 DCE，也没有产生修订口径下的
全图保留解释数。guard 配置未放宽，失败记录完整保存在
`ptmp/firrtl-ingest/F31/v17-current/`；待内存压力稳定后需从原始 `SimTop.fir`
重跑，再用同 SHA 的 GSIM exchange 计算全图 explained/unexplained 数。最后一次
raw 尝试使用当前 `package-v3`。资源 guard 同时采样 benchmark 子 cgroup 和
`user@1000.service` 父 cgroup；`memory.high`/`memory.max` 均无限，失败不是 OOM，
而是两级 cgroup 任一 PSI 连续越过阈值时停止。此前 v2 的 native library SHA 与
v3 相同；v3 source snapshot 还包含了最新的 native clock-witness test。

### 10.19 通用保留因果链

验收以“每个 GSIM 已删除、GRH 仍保留的固定候选都能解释”为准，clock 和
SystemTask 只是可解释原因的例子，不构成自动豁免。v17 的 clock-only witness
不能解释普通 data-demand、共享 anchor 或活副作用依赖；旧 reason mask 也没有根
身份和依赖路径。为此，DCE 在 semantic exchange trace 中新增
`liveness_provenance="dce-causality.v1"`，把因果事实作为 `evolution.tsv` 的
`provenance` records 导出，不把长链编码塞进 Node 的 reason 字符串。

Provenance 含三种记录：`root` 指向具体输出/声明 Value、声明 storage operation
或可观察 operation；`edge` 记录 Value 到定义 operation、operation 到确切 operand
slot/Value、以及活跃 state read 到声明和 writer 的 family 传播；`start` 将每个保留
Node 关联到自己的 live anchor、live owned operation、精确 boundary use 或零宽
SemanticBinding。boundary start 必须与真实 operation operand edge 的 user、slot 和
Value 一致。analyzer 从该 Node 自身的起点反向沿因果边到 root；zero-width binding
只凭原生 `source_width=0` 或 shape 中的零轴解释。缺起点、断链、错误 slot/value、
无 root 和只有名字/mask 的证据都计为 unexplained。旧 bundle 可继续 replay，但
没有 `dce-causality.v1` 的固定 mismatch 不追认为 explained。

这组 provenance 只在 observer/semantic trace 开启时收集；普通 no-trace DCE 不保存
因果边，也不做结果槽查找或 binding 扫描。为让根与依赖都处于同一完整 pass 事务，
public DCE trace scope 已提前至 liveness 分析开始处。小型 native 导出已观察到
output port → assign operand → Value definition，以及 SystemTask root → clock
operand/boundary 的链。普通 output 链的 native 断言已加入
`transform-dead-code-elim`；F31 analyzer/parser 的 provenance schema、根可达、断链、
边界槽/value 和零宽 binding 用例均通过。54 项 exchange parser、33 项 F31 analyzer、
2 项 DCE/ArrayUpdate 原生回归通过；两份 C++ exchange fixture 均以
`verify_f31_exchange` 做过完整 replay 校验。

全图运行使用 v18 frozen package `ptmp/firrtl-ingest/F31/v18-causality/package/`
（source content SHA-256 `8ba762db86bbe51ec4c795b5bfdbbcdfcf6c9df782ff9d2f1a0004fe2594ab9d`，
native library SHA-256 `ec28767bc75263f926d4f4002635c2ace19ecfc35e5bcca1fc8f8dc8bbc36a27`）、
完整原始 `SimTop.fir` SHA-256 `b313a3ecd154cbd9279b14403709806b95fb136cf44b475e9def46a926ecb26b`，不加载
checkpoint，保留 96 GiB RSS / 25% PSI 连续 8 秒的原资源 guard。参考是同输入 SHA
的三份 GSIM 原始首次 DCE 样本，GSIM 中位数 34.590027680 s。v18 尝试两次，均在
FIRRTL `read_sources`/initialization 阶段、未进入 DCE 前由原 guard 因
`user@1000.service`/benchmark cgroup memory PSI 连续超过 25% 而停止。第二次峰值进程
RSS 为 53.5 GiB，cgroup 记账 181.9 GB、PSI avg10 29.37%；不是 DCE trace 写盘错误，
也没有 OOM。当前没有 v18 的全图 provenance 或 explained/unexplained 结果，v17 的
44,562 旧 mismatch 数不能复用。运行记录保留于
`ptmp/firrtl-ingest/F31/v18-causality/full-grh-trace/`；没有放宽 guard。待资源压力较低
时仍须从原始 FIRRTL 重跑，统计 provenance 行数和文件体积，并使用同 SHA 的 GSIM
exchange 生成全图报告。只有新 analyzer 报告的 unexplained retention 为 0，才通过
解释性验收。

### 10.20 重新确认解释性验收口径与 v19 资源中止

验收检查冻结的一对一 before 候选中 **GSIM 删除、GRH 保留** 的每个节点：GRH
不必为了匹配 GSIM 而删除它，但必须从该 GRH Node 的实际保留起点，沿可重放的
Value/operation/operand、状态族或副作用依赖到达活跃根。`clock` 和 SystemTask 是
可能的语义原因，不是名称级豁免；没有具体活跃消费者及依赖链仍记为
`unexplained`。双方都保留的候选不属于这项跨端保留差异门禁；GRH 额外删除仍单独
报告并检查本端正确性。

2026-11-15 使用 v18 frozen package、原始完整 `SimTop.fir` 和既有 GSIM 基准，
在新目录 `v19-explained-retention/full-grh-trace/` 重试。输入 SHA、源码包身份及
96 GiB RSS / PSI 连续 8 秒 25% guard 均未改变。运行在 FIRRTL initialization 阶段、
尚未进入 DCE 时被原 guard 终止；RSS 峰值约 50.3 GiB，cgroup `memory.current`
约 182.3 GB，触发时 cgroup PSI avg10 约 30.61%。本次没有 OOM，也没有生成 DCE
provenance 或全图 explained/unexplained 结果，因此不以此前任何旧 mismatch 数替代
验收。失败摘要保存在该运行目录。中止后 PSI 仍在回落，本轮不立即重试；待压力重新
稳定后仍需从原始 FIRRTL 完成 trace，再运行同输入身份的全图 analyzer。

### 10.21 保留解释口径与严格 root 实体校验

用户再次确认验收目标：GSIM 删除、GRH 保留不要求 GRH 为数量一致而删除；应逐个
解释 GRH 为什么保留。clock、SystemTask 是可能成立的例外，前提是它们由实际活跃
依赖证明。该口径不改变 §4.2 的冻结候选范围，也不把名称、类型或 reason mask 当作
解释；无法连到真实根的保留仍是 `unexplained`。

provenance parser 增加 root 实体一致性约束：`output_port`/`declared_value` 必须是
Value 根且不得附带 operation/storage 字段；`declared_storage` 必须是带具体符号、
operation kind 和 declaration identity 的 operation 根；`observable_operation` 必须
带 operation kind 与精确 root identity/generation。native DCE emitter 对这些 operation
root 无条件写出 identity 字段；parser 接受合法的零值 identity，而不会把它误判为字段
缺失。已补充非法实体类型、缺失 storage 身份和缺失可观察根 identity 的拒绝用例。

严格规则的轻量验证已通过：semantic exchange contract **54/54**，F31 analyzer
**33/33**，最新 native build 的 DCE/ArrayUpdate/SemanticTree/pass-manager 回归 **4/4**。
完整图尚未完成。最新从 raw `SimTop.fir` 开始的 v20 trace 在 XMR 阶段后被原资源 guard
中止，峰值 RSS 75.4 GiB、PSI avg10 51.59%、cgroup 记账约 151.2 GiB，且 cgroup
swap 已用约 7.05 GiB；它没有进入 DCE，因此没有 provenance 或全图
explained/unexplained 结论。guard 未放宽，宿主 swap 仍接近耗尽；再次完整运行前先
重新检查压力和构建/运行策略，不用旧 mismatch 数替代新口径验收。

root 分支的原生验证也已补齐：native `transform-dead-code-elim` fixture 实际导出
`declared_storage` declaration/write 两条带 storage symbol 与 declaration identity
的记录，并由 pipeline replay verifier 检查；`f28-memory-effects` raw FIRRTL fixture
导出的多条 `kSystemTask` 根包含 task identity 与 clock slot。最新 frozen package 位于
`ptmp/firrtl-ingest/F31/v25-storage-root/package/`，源于当前 working tree；两项 F31
pipeline 测试再次全通过，其中包含 raw FIRRTL ingest、trace/no-trace 等价和 fixture
replay。该包验证仍只是小型/中型 fixture，不能替代完整 XiangShan trace 与全图
explained/unexplained 报告。

### 10.22 v29 完整图诊断与缓存驻留核查

本次先核对实际进程与记录：`v28-full-trace/full-grh-trace/` 的 summary/guard
仍写着 running，但相应进程已不存在，也没有结束记录或 DCE timer；该历史尝试
不计作成功、性能样本或经 guard 证实的中止。新尝试另建
`v29-causality-run/full-grh-trace/`，使用 v28 冻结包（source content SHA-256
`2341d40e2082a5decf2d455a809ee943a9ccc11417f8ac1c863866c9a87419e4`），从
原始完整 FIRRTL 启动，打开 `--connection-evidence`，同时要求实际后态核验、
结构校验与二次 DCE 幂等。96 GiB RSS、25% PSI 连续 8 秒的 guard 保持原值。

v29 的 raw ingest **140.458 s**、XMR **0.348 s** 均完成；随后 guard 以
`cgroup_pressure` 终止任务。最后采样进程 RSS **81,770,807,296 bytes**，
子 cgroup memory.current **163,466,440,704 bytes**，PSI avg10 **54.26%**，
越线持续 **8.025 s**。本次未进入 DCE，没有 provenance、完整图保留解释或
有效性能样本；不得把该中止归因为 DCE 运行慢。

终止后通过已有 Make 诊断目标，对 19 份已完成两端五文件 bundle 观测了
**171,901,815,281 bytes**，实际驻留从 **6,935,372,426 bytes** 降至 0；再对
明确指定的 F30/F31 已完成 alignment 的 23 个 SQLite 文件观测了
**564,334,411,776 bytes**，实际驻留从 **31,694,589,952 bytes** 降至 0。
所有文件 inode/stat identity 均不变，未删除或重写证据。报告分别为
`v29-causality-run/cache-diagnostic.json` 和 `cache-diagnostic-alignment.json`。
这些仅为 pass 外的定向 advisory cache 诊断，不计入 DCE 性能，也不证明下一次
运行一定无压力；新代码仍须重新冻结并从 raw FIRRTL 实测。

### 10.23 因果证据收紧与连接退役解释

保留 provenance 现在为 `owned_operation` 写出真实 `owner_count`。共享 op 的
membership 仍可核验 boundary target 确实拥有 consumer，但只有唯一 owner 可
将该 operation 单独作为本 Node 的保留起点。incoming port alias 不再输出普通
anchor 起点，必须经过精确的 boundary user/slot/value 解释。parser 限制 observable
与 declared-storage root 的 operation kind 为 DCE 原生根类别；纯组合操作不能
伪装成可观察根。SystemTask 经状态族到其他 writer clock 的实际路径允许解释，
仍核验直接 SystemTask clock consumer 自身的 clock slot。analyzer 缓存已证明的
rooted predecessor，完整搜索失败后才缓存无根结论，覆盖共享长链及环。

连接演化新增 `boundary-retirement.v1`：在 Graph 退役 Node 前捕获实际 boundary
use 或 value owner；correctness after-walk 只为请求的新增边捕获连续的
Value→definition operation→operand 路径。transition 逐项关联原 before edge、
同事务退役 source、真实起点和新连接的全部 source/candidate support；缺路径或
支持不足仍要求复核。另补 unresolved 候选裁剪到唯一 source 时转 resolved 的证据。
该规则解释公开依赖的投影变化，不声称已经证明跨端逻辑等价或覆盖全部新增边。

四项 native DCE/ArrayUpdate/SemanticTree/pass-manager 回归通过；新建的 boundary、
owner 退役及 candidate-resolved 三份真实 native bundle 均以独立 reader 验证
`complete=true`、`replay_exact=true`，各有一条 transition。parser **60/60**、
analyzer **40/40** 通过。记录分别在 `v30-retention-proof/`、
`v30-native-transition/` 与 `boundary-retirement-{reader,analysis}/`。
当前 GSIM 使用新目录 `v30-gsim-reproduce/` 两次执行 Make 原生回归均通过；
checker 额外核验 alias/gated clock 的实际 prev 与 live-clock blocker。旧 gsim-dev
失败日志早于已修正的合法 clock-gate fixture，不作为当前回归结论。

### 10.24 全图 provenance 超时与紧凑记录修复

缓存条件改变后，`v29-causality-run/full-grh-trace-cache-controlled/` 用同一 v28
包重新从 raw FIRRTL 开始：ingest **143.027 s**、flatten **42.473 s**、comb
**9.848 s**、split **41.221 s** 均完成，before snapshot setup **23.500 s**。
DCE 确实开始，并在 **69.238 s** 被既有 **69.180055360 s** watchdog 停止；
最后 PSI avg10 为 **0**，RSS 约 **83.07 GB**。这是本版新增 provenance 的
trace 性能失败，不是 DCE 前的资源中止；没有成功 native DCE timer，不计有效样本。

中止留下 **11,940,766,166 bytes** 的 `.liveness.pending`，最后完整 record ID 为
**62,232,000**，仍在记录 value-definition edge。当前修复将现场 API 改为强类型
root/edge/start/boundary/binding，使用固定 **40-byte** numeric record、640 KiB
批缓冲及 binary spool；clock/slot、原生 ID/generation、root/storage identity、
owner count、完整稀有 binding 均在现场保存。commit flush 和事务维护仍包含在
pass 内，finish 仅按捕获事实编码原五文件 JSON/TSV，不查询 IR 重建原因。该补丁
尚待新的 native/pipeline/完整图实测，不能凭记录变小预先宣称通过性能门。

另新增 `benchmark_f31_dce --actual-state` 与 `compare_f31_dce_equivalence` Make
目标：分别导出 trace 开/关的实际序列化 IR、全量 Node/类型化 connection inventory，
并对第二次 DCE 再导出。比较时重新解析真实 TSV、要求 Node inventory complete，
核对输入、全部 source/依赖/包身份和第二次实际图一致；不信任 summary 中自报的
图 hash。连接仅忽略 exchange-local connection ID，Node 身份保持精确，未解析边
与 candidates/reason 均参与比较。IR 比较省略 source locations，保留逻辑结构。
该独立正确性动作发生在 DCE 计时后，不混入正式性能样本。

equivalence 合约 **6/6**、用现有 v28 包验证新 actual-state 流程及 raw fixtures
的 pipeline **3/3** 通过，证据在 `v31-equivalence-{contract,strict}/`。这些小图
只证明新增验收流程可用；当前源码仍需重新冻结后执行完整图实际状态比较、
explained/unexplained 与新增连接归因，以及同一最终包的性能复验。

### 10.25 v32 冻结包与紧凑 provenance 验证

v32 冻结包为 `v32-compact-provenance/package/`，source content SHA-256
`04cddae066779faea35fe1a4c5cadc060f75286803b3f53e0ec1e5ec8ebd732f`，native
library SHA-256 `83c797ff916eeb73521e77fe296596a0fb92fbda4cd66e5d437a8a5fcb20811e`。
紧凑记录的七项原生兼容回归通过；跨批缓冲的 **16,392** 条事实由独立 reader
确认 `complete=true`、`replay_exact=true`。额外故障注入把私有 spool 路径变为
目录以模拟落盘失败，验证 commit 出错后不能继续事务或发布成功 footer；该
修复后的 native SemanticTree 回归亦通过，冻结包包含修复。

使用该包运行的 pipeline **4/4** 通过，包含 8 个 raw FIRRTL fixture 的 trace
开关、实际 IR/Node/连接相同、二次 DCE 幂等、AU/native fixture replay、三类新
transition 与紧凑 provenance replay，以及新增 actual-state 对比流程。日志在
`v32-compact-provenance/pipeline/`。完整图正确性运行已从原始 `SimTop.fir`
启动到 `full-grh-correctness-trace/`，开启 connection evidence 与 actual-state；
结果须以其最终 summary、native timer 和完整 bundle 为准，尚不预填通过。

该完整图尝试已经返回首次 DCE：边界 wall **60.489329666 s**、native timer
**60.246409434 s**，低于 **69.180055360 s** watchdog；原生本体为 GSIM 中位数
的约 **1.742 倍**。这是开启校验的正确性诊断，不能替代关闭额外校验的正式
trace 诊断样本，更不替代 no-trace 三轮。当前 export 与后续实际图验证仍在进行，
尚无最终 replay、保留解释和全图新增连接归因结论。

随后完整运行已成功结束：`summary.json status=passed`，raw ingest 到验证结束
**868.354 s**；快照导出 **135.412 s**，实际状态与二次 DCE 校验 **419.914 s**。
after inventory 为 **5,686,678 Node / 9,026,371 connection**；实际后态 cache
核验、`semantic_validate`、`grh.verify` 和二次 DCE `changed=false` 均通过。
两次独立实际 IR 的 SHA-256 同为
`d11651a283e40ebe30e7844c8f3568eaf1e0806ebc6209054e61b93fdaf6b172`，全量
Node/连接指纹亦完全相同。trace 开关的完整图相等仍需配对 no-trace 正确性运行。

native footer 含 **128,648,618** 条 provenance、**148,220** 条现场 boundary
retirement、**11,965** 条 transition；新增 dependency 请求 **156,199**，实际
support records **289,893**，其中缺 support 的记录 **9**。这只是现场导出
库存，不能替代独立 replay 或未解释保留/连接数；完整 analyzer 尚待执行。
reader 为这批大图改用按 relation 的部分索引，并消除 provenance 在 evolution
派生缓存中的重复 JSON 存储；完整事实仍保存于专用表及原始 TSV，stream 的
ordinal/ID/count/footer 校验不减。相关 parser **61/61**、analyzer **40/40**
通过，日志在 `v32-reader-single-provenance/`。

同一冻结包的 `full-grh-correctness-no-trace/` 也已成功：raw 流程与实际状态
校验总计 **665.493 s**，DCE 边界 **31.024255535 s**、native **30.773348014 s**。
trace/no-trace 的首次与第二次 DCE 共四份实际 IR、Node 与 connection 指纹全部
相同，完整库存为上述 **5,686,678 / 9,026,371**；独立 comparator 另从实际
TSV 重建并核对，不能仅引用 summary 自报 hash。此 no-trace 样本开启了额外
正确性校验，不计入正式三轮性能组。

独立 comparator 已完成：`v32-compact-provenance/equivalence/verification.json`
为 `complete=true, passed=true`。它从四份真实 TSV 重建库存，确认上列 IR、
Node 与连接指纹以及第二次 DCE 相等，并核对冻结输入、source/依赖/包身份。
该结果证明 v32 trace 开关不改变实际后态；不替代保留规则与新增连接的因果验收。

### 10.26 v35 三项结构修正（验证中）

有界连接诊断 `v32-connection-diagnostic/report.json` 指出尚未覆盖的
**124,416 ambiguous / 19,809 resolved / 9 missing input boundary** 新增边。
诊断只抽取各类少数案例并读取有限 provenance/索引范围，不作为完整图验收。
其中相同 use 的投影变化不需要经过 definition→operand 步：原 source 的精确
`(Value ID/generation,user ID/generation,operand slot)` 与 after 全部 source/
candidate support 完全相同时，允许空路径。仍要求旧边与旧 source 同事务退役；
user=0、通配 slot、named boundary 和缺少任一候选 support 都不能用此规则。

缺 input boundary 的案例涉及真实顶层 input Node（如 reset、uart.in.ch），
不能通过保留所有共享物理 Value 的 flattened alias 修复。DCE 现在按已有
`firrtl.semanticPortNames/Nodes` 正式映射、实际 input/inout Port Value 及精确
Node anchor/非 operation binding 三者交叉保护原 Node，导出 `input_port`
结构起点（含实际 port_name、port_kind 与 Value generation）。此保护不把未用
input 的逻辑锥加入 liveness 根。

另发现旧回归允许存活操作失去最后一个原 owner，违反 §4.3。修正先计算普通
Node/boundary 固定点，再同时保留所有没有普通存活 owner 的 live operation
完整原 owner 集合；不能按遍历顺序任选一个身份。原本 ownerless 的辅助操作
仍允许 ownerless；其他普通 owner 存活时，dead 共享 owner 仍退役。新增
`residual` group 记录原 operation/generation、完整 owner_ids、普通保留数 0
及 `preserve_original_owner_set` 规则，所有保留 owner 明确输出 `residual:`
decision，并继续传播其精确 boundary 依赖。reader 核验完整原 membership/
owner_count、所有 after 存活及 residual decision；analyzer 还必须找到该实际
operation 到原生根的路径。泛泛 shared membership 仍不能独立解释保留。

三项 native 修正及正反回归已加入源码，统一 build、冻结和完整图验证待执行。
当前版本的 trace/off 正确性、全图 explained/unexplained 和正式三轮 no-trace
与 trace 性能门仍未完成，不提前记为通过。

v35 已冻结到 `v35-current/package/`：source content SHA-256 为
`c40bd08e4cd55ade687706863574af983d24b8ec26d6f411bb31873ebb825399`，native
library SHA-256 为 `d36d053790931f8827cbba765690af0361a2a9bf183528ebbf86e5c0e20384cd`。
统一 native 兼容 **7/7**、ArrayUpdate 额外 ownerless zero 复用及全 fixture
before-owned/after-survivor 不变量 **1/1** 通过。reader **68/68**、小图完整流程
**4/4** 通过，包含三个真实 residual bundle 及 **16,393** 条 compact spool
事实重放。六份零步投影 native bundle 均独立精确重放：exact resolved/candidate
各有一条 transition，named/wildcard 四项反例均为零条。证据在
`v35-current/{trace-compat,array-owner-invariant,pipeline,native-replay,spool-replay}/`。

为避免新完整图缓存耗尽磁盘，仅将 v14 旧派生缓存五个 SQLite 文件无损归档；
原始 TSV、native bundle、报告、日志、冻结包均保留。每个 archive 在取代冗余
未压缩表示前必须解压核对完整 SHA-256 和字节数，并保存恢复路径及原 metadata。
固定范围 Make 工作流和五项安全回归日志在 `v35-current/storage/`；完整归档
结果以 v14 report 目录内 `derived-cache-archive-manifest.json` 为准。

归档已完成：原五个缓存 **123,479,601,152 bytes** 压缩为
**9,819,100,878 bytes**，完整解压 hash/size 核验一致，释放
**113,660,500,274 bytes（105.85 GiB）**。完整 native v35 前仍使用固定
96 GiB RSS / PSI 25% 持续 8 s guard，没有放宽资源限制。

v35 的 `full-grh-correctness-trace/` 已通过：raw 全流程 **832.126 s**，DCE
边界 **59.896265280 s**、native **59.642231380 s**，快照导出 **119.629 s**。
实际库存为 **5,698,937 Node / 9,026,371 connection**；实际 IR SHA-256 为
`346ed508c037db101cef181e80e4cf227662b96b54fd5004eb9042bd7118ea30`，首次与
第二次 DCE 的实际 IR/Node/连接签名相等，第二次 `changed=false`。新增保留的
12,259 个 Node 来自本轮身份/残余规则修复，逐项分类仍以完整 analyzer 为准。
native footer 有 **128,695,807 provenance / 148,203 boundary retirement**；
新增 dependency **156,181** 条，导出同数 transition，缺 support **0**。
这证明现场捕获库存完整，尚不替代独立 reader 对每项事实的校验。

### 10.27 存活端点删边证据门禁补全（v36 开发中）

验收复审发现 §7.2 的另一真实缺口：旧 analyzer 对新增连接有严格因果门禁，
但对存活端点间删边仅保存 edit(seq/reason)，并未要求逐边 mutation 原因。
v16 完整报告中该类 GRH 删边为 **4,656** 条，GSIM 为 0。受限旧缓存 probe
识别出具体例子 `immBits_12`（7681198）→`_jalAbstract_imm1_T`（146864）：
两端均存活，target 的 operation 348723 确有 `undemanded_operand_defined_zero`
裁剪，但被裁 Value 的 live mask 为 0，旧 trace 没有它的 source anchor/
native boundary。op owner 与同 target mutation 只说明相关，不能补造因果链。
诊断在 `v35-current/removed-edge-audit/report.json`，该项尚未验收。

v36 将在 `replaceOperands` 破坏原引用前捕获精确 native boundary：原连接 ID、
mutation ID、source/target、Value/generation、user operation/generation、
operand slot 和 boundary kind。仅在旧边同事务退役、全部原端点原身份存活、
每个原 candidate 都有精确支持，且 mutation 真正删除/替换 Value 时输出
`pruned_operand_boundary`；只移动 slot、泛泛 owner、名称或 after 反推均无效。
捕获还必须以裁剪前原生 walker 实际发出的完整 connection key 为准，逐项
匹配实际 use 和 reference context；仅在同 target 的 cached edge 中找到 source
不能证明该引用参与过此边，不可达 owned-operation 引用与交叉 candidate 组
均必须拒绝。批次现场缓存仅在显式 rewrite 边界内使用，不以 deferred Design
revision 猜测图是否改变。
reader 校验原 before edge、完整 candidate 支持、mutation old use 及最终无同 key
边；analyzer 对仍缺精确证据的存活端点删边输出单独失败门禁。v35 本轮完整图
保留为诊断证据，不因其新增边库存完备而宣称全部连接变化已解释。

v35 native 完整诊断额外占用约 61 GiB，故同样以固定范围、完整解压哈希验证
归档 v15 旧派生五缓存，保留所有原生 TSV、报告和日志。v36 的正式性能组与
完整图解释性验收继续等待修复完成后的同一冻结包，不沿用旧包结果。

v36 reader **79/79**、analyzer **53/53** 已通过，日志在
`v36-removed-boundary/python-tests/`，包括两端存活删边的双端门禁、完整候选
支持、原始 use/generation、同身份 implementation touch、退役/改名、后续事件
重建同 key 及伪造中间边反例。v15 五缓存归档已完成，完整解压核验后释放
**113,376,424,637 bytes（105.59 GiB）**；manifest 保存在其原 report 目录。

v36 冻结包为 `v36-removed-boundary/package/`，source content SHA-256
`477f4299c49fa98cd3046436f52c3ef188e679558e1706b58135196d681e393b`，native
library SHA-256 `5d361e77307678c0c65b6bd9ac89b578ab17b2c10ba044f4935a328c8be6e7f9`。
补强后 native **7/7** 通过，24 份真实 bundle 全部独立精确重放；四种合法
boundary kind、abort 恢复、原身份 touch 各为 1 record/1 connection，完整
候选为 2/1，实际采用的重叠组为 3/2，16 个反例均为 0/0。独立源码复审确认
此前的不可达引用/交叉组归因缺口已关闭，批次生命周期只跨越修改前的回调。
小图完整流程 **5/5** 通过，包括这 24 个 fixture 和 trace/off 实际状态比较。
`full-grh-correctness-trace/` 已从 raw FIRRTL 启动，最终删边覆盖与性能仍以该
轮实际完成结果及其后的独立分析为准，不预填通过。

该轮首次 DCE 已返回：调用边界 **59.752031598 s**、native **59.509208282 s**，
snapshot setup **22.746 s**，低于固定 **69.180055360 s** watchdog。该正确性
诊断开启 before/after connection evidence 与实际状态验证，不能混入正式性能组。
证据导出、二次 DCE 与完整解释性门禁此时仍未结束。

### 10.28 实际引用上下文的删边捕获（v37 开发中）

v36 完整 raw 正确性运行已结束，总计 **834.852 s**；首次和二次 DCE 的实际
IR/Node/连接签名一致，二次 `changed=false`，库存仍为 **5,698,937 Node /
9,026,371 connection**。新增 dependency transition 仍为 **156,181**、缺 support
为 **0**，但删边 record/connection 均为 **0**。因此该运行只证明电路与新增边
诊断通过，不能作为全部连接变化已解释的验收结果。

现场 walker 使用的引用包含 exact、wildcard、named、selected-read，以及原 Value
owner fallback。v37 在原始完整 key 真正发出时同时捕获实际 consumer use 和其
reference context，仍要求原始端点原身份存活、确切 destructive mutation、全部
候选来源支持，以及最终无同 key 连接。新 header 为 `pruned-operand-support.v1`；
新增 `support_kind`、reference target/op/generation/slot、Value 定义 op/generation，
fallback 不伪造 boundary。字段与示例见 [DCE 文档](../../wolvrix/docs/transform/dead-code-elim.md)。

v37 reader **88/88**、analyzer **57/57**、native 兼容 **7/7** 通过，原生捕获与
reader 已经独立源码复审；具体日志在 `v37-removed-support/{python-tests,native}/`。
冻结包为 `v37-removed-support/package/`，source content SHA-256 为
`1d26c7c7aa284facf2ad5a2972f331aa9d7d86fb987fb19ff19a85d473f50452`，native
library SHA-256 为 `5ae75085f6b29b8f17f52fff1a8fa15966e962d9e5485b238c9ccc5577f75f64`。
29 份原生删边 bundle 全部独立精确重放，总计 **18 record / 15 connection**；
小图完整流程 **6/6** 通过。新增 raw FIRRTL 中，ArrayUpdate 产生 **3/3 named**
证据，状态读取 Concat 产生 **1/1 selected-read** 证据，scalar concat 控制为
**0/0**；trace/off 实际 IR、Node、连接与二次 DCE 幂等均通过。日志与逐条证据在
`v37-removed-support/pipeline-final/`。

同包完整 raw 正确性 trace 已启动；完整图删边覆盖、独立解释性验收及正式性能
仍待运行，不提前记为通过。

首轮在 DCE 开始后因父 cgroup PSI 持续超过 **25% / 8 s** 被既有资源守卫
终止；当时进程 RSS **84,186,861,568 bytes**，未达 96 GiB RSS 门。该轮无完成
footer，不计有效样本。保留失败目录后，仅对 v35/v36 旧完整产物及本次失败目录
执行文件级 `dd iflag=nocache count=0` 缓存建议，没有修改文件内容；Cached 从
约 91.2 GiB 降至 65.1 GiB，父 PSI avg10 回落到 0.01%。同包 retry1 已在原样
96 GiB / PSI 25% 持续 8 s 资源门和 69.180055360 s DCE watchdog 下启动。

retry1 首次 DCE 已正常返回：native **61.508859990 s**、调用边界
**61.746657273 s**，snapshot setup **22.146 s**、export **125.371 s**。完整
footer 仍有 **156,181** 条新增 transition、缺 support **0**；删边证据变为
**34 record / 34 connection**。这些是捕获库存，不能代替全部存活端点删边
覆盖检查。首次 actual-after 的 IR/Node/连接签名与 v36 完全一致，二次实际
状态导出与独立解释性验收仍在进行。

retry1 已完整结束，总计 **841.818 s**，actual-after/repeated 的实际 IR、Node、
连接签名完全一致，二次 DCE `changed=false`，资源守卫正常完成。
新增轻量完整库存诊断通过 Make 运行，仅用 **25 MiB** bitmap、峰值约 **47 MiB**
RSS 扫描 2.58 GB 的静态库存及有 footer 数量闭合的 bounded evolution tail。
它发现全部存活端点间消失的连接为 **42,516** 条，其中 **34** 条有 support，
**42,482** 条未覆盖（**38,124 resolved / 4,358 ambiguous**，均为 dependency）。
此诊断不验证端点 body 身份或完整 replay，不能替代 analyzer，但已足以证明本轮
捕获仍不完整，因此暂不运行已知不能通过的全图最终解释性验收和正式性能组。
`immBits_12` → `_jalAbstract_imm1_T`（connection 172636）仍在首批缺口中。
诊断及 **11/11** 工具回归在 `v37-removed-support/removed-surviving-audit/`；
仍须定位真实 boundary/anchor 生命周期与 operand mutation 的关系后补捕获。

### 10.29 间接 operand 路径的现场证明（v38 开发中）

缩小后的 raw FIRRTL 反例保留完整 `immBits` 作为第二个输出，保证来源 member
Node 全部存活；Concat 的高位读却没有需求，DCE 会将其替换成零。v37 下稳定出现
**13** 条 `immBits_8..20 -> packed` 的存活端点删边而 support 为 **0**。
实际路径为 `Concat operand Value -> Assign definition -> member Value`，旧连接
由更深一层 Assign 的 operand 引用发出；旧捕获要求终端 use 的 op/Value 与
Concat mutation 完全相同，因此漏掉合法的间接因果关系。该诊断仍走正常 raw
ingest/prefix/DCE，trace/off 实际状态及幂等通过；证据在 `v38-causality-probe/`。

v38 的 `pruned-operand-support.v2` 保留 mutation 的原 op/generation/slot/Value，
另外记录从该 Value 到原生边界终端的逐步 `path`，每步为真实 Value 定义 op
及其 operand。native 在 rewrite 前检查每一步真实定义和 slot，reader 从 mutation
原 use 起逐步核对链、终端 reference context、完整候选与最终删边。空路径仍是
直接引用；不同 source 的路径和终端证据不可拼接。v36/v37 格式兼容验证仍保留。
实现与回归进行中，尚未重新冻结或运行完整图。

v38 实现现已冻结到 `v38-transitive-support/package/`：source content SHA-256
`511fbdf3d4472242d10a4291f3ed54c9a991207eda80955d10f41ba1254b6c5c`，native
library SHA-256 `c6456bb07a3ee1da10a7bc48a7de14bf1a3b50bf28dffb44cba99b2dcb8f0f9c`。
reader **95/95**、analyzer **61/61** 通过，native 路径、arena 生命周期、generation、
完整 key/candidate 与按路径内容去重均已独立源码复审。统一 native 兼容 **7/7**、
35 份删边 bundle 的独立精确重放及小图完整流程 **6/6** 通过。
retained scalar concat 反例现为 **13 record / 13 connection**，每条路径长度 **1**，
全部存活端点删边的未覆盖数为 **0**；named ArrayUpdate 仍为 **3/3**、selected-read
Concat 仍为 **1/1**，均为空路径。trace/off 实际状态与二次 DCE 幂等通过。
同包完整 raw trace 已启动，正式完整覆盖及性能仍未记为通过。

v38 完整 trace 的首次 DCE native **60.526045530 s**、调用边界
**60.759857539 s**，低于原 watchdog；snapshot export **120.038 s**。
完整 footer 的删边证据为 **581/581**，新增 transition **156,181**、缺 support
**0**。完整库存诊断仍有 **42,516** 条存活端点删边，其中 **41,935** 条未覆盖
（**37,577 resolved / 4,358 ambiguous**）。原 `immBits` 例子现已覆盖；新的
resolved 例子是 connection **303193**，source **7714453**
`...icache.mainPipe.difftest_refill.data_0` → target **254118**
`...mainPipe._difftest_packed_T`；ambiguous 例子为 connection **1020040**，target
**705070** `...pmp._rdata_T_1`，候选 **9456459 / 9644621**。
这些缺口继续阻止连接验收。首次 actual-after 签名仍与 v36/v37 完全相同；
第二次导出进行中。下一步仅针对这两个 target 做变更前路径和破坏操作的原生
诊断，先确认实际原因，不从 after 名称或同 target 标签合成证明。

v38 完整 raw 正确性运行已结束，wall **834.610 s**，actual-after/repeated
IR/Node/连接签名相同且二次 `changed=false`，固定资源守卫通过。
但 **41,935** 条缺少解释的删边继续阻止最终验收。新增证据表明 target 254118
由 `residual:dpic_call;operation=624775` 保留，内部 **10** 个 op 被删除；这是
没有 operand rewrite 的实现收缩，仍需逐边精确路径/删除证据。

独立冻结的 `v39-removal-probe/package/` 仅增加显式环境开关控制的两个 target
原生探针，记录完整旧 key、变更前 walker path 与实际 operation/operand/anchor
破坏事件。Make benchmark 的 `--diagnostic-stop-after-dce` 仅允许这类 ptmp
定向探针，强制标记 verify/diagnostic，首次 DCE 后不发布完整 exchange，不能
计入正式性能或验收。该 raw 诊断已启动，v38 的冻结完整产物保持独立。

为后续完整 replay 腾空间，v16 固定五份派生 SQLite 缓存已无损归档，保留所有
raw TSV、native bundle、报告、日志与冻结包；每个 archive 均完整解压比对 hash
和字节数，释放 **113,661,610,928 bytes（105.85 GiB）**。7/7 安全回归及执行日志
位于 `v38-{causality-probe,transitive-support}/`，恢复信息在 v16 原目录的
`derived-cache-archive-manifest.json`。

### 10.30 实际 anchor 定义删除的逐边证据（v40 开发中）

v39 定向探针记录确认两类缺口都没有 operand rewrite：connection 303193 的
路径从 target anchor Value **785889** 经 Assign **624791**、Concat **624790**
到仍活的 Assign **624789**；实际先删除 624790，再删除 624791。connection
1020040 从 anchor Value **3146758** 经 Assign **3049911 / 3049910** 到仍活的
SliceStatic **35034243**，终端 fallback 来源为 **9456459 / 9644621**；实际先
删除 3049910，再删除 3049911。target 因其他活实现保留，原 anchor 定义锥则
消失，故不能用不存在的 destructive operand mutation 解释这些旧边。

该探针随后因调试回调读取已擦除 Value 而 **SIGABRT**；它没有完成完整运行或
发布有效 footer，不计入正确性、覆盖率或性能验收。冻结的 v39 仅保留为诊断。
v40 源码移除全部临时 native probe，benchmark 的临时
`--diagnostic-stop-after-dce` 也已删除。

v40 增加独立 `connection_anchor_removal_trace=dead-anchor-cone.v1`。DCE 在第一
个死 op 删除前批量预备 surviving target 的真实原连接路径；擦除定义 op 前的
实际 `operationRemoved` 再核对 anchor Value 的定义与 target 归属，产生独立
`dead_anchor_definition` fact。`dead_anchor_cone` 连接 evidence 从该 fact 的
Value/op/generation 起步，保留非空真实路径和终端 boundary/fallback context。
两种原因的 record/connection 合计仍由原 footer 字段闭合，anchor 另有独立计数。
reader 同时检查完整原候选、端点身份、同事务退役和最终无同 key；所有 anchor
fact 的 target 必须原身份存活，即便该 fact 最终没有产生删边 evidence。
字段定义及最小例子见 [DCE 文档](../../wolvrix/docs/transform/dead-code-elim.md)。

bounded 库存审计已支持两种 cause，并同时闭合总计与 anchor 子计数，回归
**13/13**；移除探针参数后的 benchmark resource guard 回归 **2/2**。
原生实现、reader/analyzer 回归和新包完整图验证仍在进行；**41,935** 条旧包
未覆盖数不因新代码存在而视为已解决。96 GiB RSS、PSI 25% 持续 8 s 和
69.180055360 s watchdog 均保持原样。

v40 reader **107/107**、analyzer **65/65** 已通过；新增跨后续事务的 source、
candidate、target 改名/退役反例，保证删边证据的所有端点最终仍与 before body
完全相同。独立 native 源码复审未发现剩余阻断项，统一 native 兼容 **7/7**
通过。原生新矩阵为 **12** 个 anchor bundle，预期 **8 facts / 7 evidence records /
6 connections**，包括多事实中先过滤一个 target、再将 internal fact ID 2 连续
导出为 ID 1 的反例。此时安装、冻结与 Python 独立重放仍在进行，尚未记为通过。

v40 已冻结为 `v40-dead-anchor-cone/package/`，source content SHA-256
`1cd46c114b7870016bafa14b7c1d342656efd673883b13131a482c6d33a6a5d2`，native
library SHA-256 `752acabcaa8f2561cabff420fd51de2e83533d746cfc8d7b13eed67bebea416c`。
同包小图流程 **7/7** 通过；35 个 operand 与 12 个 anchor 原生 bundle 全部由
Python reader 独立精确重放，新矩阵实际数量与上述预期一致，原 v2 的
**21 records / 18 connections** 不变。raw retained scalar 的 **13/13**、named
ArrayUpdate 的 **3/3**、selected-read 的 **1/1** 仍通过，trace/off actual state
及二次 DCE 幂等通过。完整 raw SimTop trace 已启动；完整覆盖、独立 analyzer、
正式 trace/off 与性能组仍待结果。live validation 脚本的 SHA-256 保存于
`v40-dead-anchor-cone/validation-script-sha256.txt`，不只依靠 schema v1 标识门禁。

v40 完整 raw trace 已在冻结包上完成，wall **835.521 s**，实际 IR SHA 与 v38
相同；before/after/repeated 的 Node 与连接签名一致，二次 DCE `changed=false`。
首次 native DCE **60.959319789 s**、调用边界 **61.196474022 s**，通过原始
**69.180055360 s** watchdog；benchmark RSS 峰值 **86,324,908,032 bytes**，低于
96 GiB，资源守卫 status `completed`，没有改变 96 GiB / PSI 25% 连续 8 s 限制。
新增依赖 transition **156,181**、缺 support **0**；删除证据总计 **46,693 record /
38,370 connection**，其中 operand **581/581**，anchor **46,112 records /
37,789 connections**，anchor deletion fact **12,196**。

footer 闭合的全库存审计再次确认 **42,516** 条存活端点间删边：有证据 **38,370**，
未覆盖 **4,146**（**3,616 resolved / 530 ambiguous**），均为 dependency，零
source-less。现有 root 原生审阅指出 walker 对 owned-op root 和 anchor direct-root
emission 的 canonical witness 路径可能解释覆盖限制，但这些仍是代码层假设；
正为 connection **9300457**（target **5650183**）与 **12834972**（target
**7713035**）获取首次全图原生 walk witness/root path 与同批实际删除 op 的对应证据。
在确认 incidence 和修复/证明所有连接之前，不运行预计失败且高内存的完整
alignment analyzer，也不运行 trace/off 最终比较或正式三轮性能。

### 10.31 原始 canonical walker 根与删除回调对应（v41/v42 诊断）

v41 是单独冻结的环境门控探针包。第一次完整尝试在 flatten 因父 cgroup PSI
>25% 连续 8 s 被 guard 终止；没有放宽守卫。只对明确的旧/失败任务文件运行
dd iflag=nocache count=0 后 retry1 成功完成，wall **462.299 s**，完整 trace
status=passed，guard completed。native DCE **60.757004243 s**，低于
69.180055360 s watchdog；这不是正式性能样本。其 footer 与 v40 相同，库存审计
仍为 **42,516 / 38,370 / 4,146**。

定向探针在构造初始 exchange cache、DCE 尚未修改 operands 时，针对两个目标
按正常 walker root 顺序记录原 before key 与 canonical evidence path；实际删除只由
operationRemoved callback 记录。connection **9300457–9300461** 均指向
**5650183**（cpu.l_soc.core_with_l2.core.memBlock.inner.ptw.ptw.resp_pte_r$NEXT），
该 target 没有 anchors。它的两个 kRegisterWritePort root operation
**25705011、25721253** 都是 resultless。connection **9300457** 的原 canonical
witness 以 root op **25705011** 开始，path 长度为 **1**，是该 op 的 clock
boundary；9300458、9300459 等也以这两个 resultless root 开始。真实 callback 随后
记录了 root ops 和 helper chain ops 的删除。故这组旧边确实经过 DCE 删除的
resultless owned-op root，且包括直接 root emission；anchor-result-only 的
dead_anchor_cone 不可能捕获它。

connection **12834972** 指向 **7713035**
(...ctrlUnitOpt.io.metaRead.resp.entries.valid_0_0)，原 canonical 路径从
anchor Value **748796** 起，经过 13 个 Value/op-use 项到 fallback terminal
Value **751881**，其完整 unresolved candidate 集为 **242587 / 7713603**。target
anchor 的 def op **684013** 及其他 target-owned path ops 在当前 callback 清单中没有
删除记录；但 v41 未监视原 canonical path 上的每个 operation 与 terminal value
definition，因此缺少记录不能证明这些操作存活。v42 为原路径中每个 op ID 与
fallback terminal 的 value-definition op ID 增加了实际 removal callback 监视。

### 10.32 operation-path watcher retry（v42/v43）

v42 扩大了 watcher：除 canonical path 上每个 user operation 外，也监视 witness
terminal value 的 definition operation。v42 在 DCE setup 阶段被原有 PSI guard
终止，尚未进入 native DCE timer；canonical-walker 文件仍只有 2 个
`target_roots`、14 个 `old_connection` 和 28 个 `canonical_witness`，没有任何
`operation_removed`。

v43 冻结了仅供诊断的控制：
`WOLVRIX_DEAD_ANCHOR_DIAGNOSTIC_NO_LIVENESS=1` 跳过可选 liveness provenance
写入，保留 DCE 决策和实际 `operationRemoved` 回调；
`--diagnostic-stop-after-dce` 在 native DCE 完成后停止并将报告标为
`diagnostic_only`，不会完成 semantic exchange 发布。该包 source content SHA-256
为 `f65c1715eadba7de75b111a83aec358e0ee42dbe7cfe21694ef8ab868d4dfea5`，native
library SHA-256 为
`9e8b7a2df95d5e2c900699e02e317efca23fb62457e9e309430dea8b8e8aeaf4`；native
compatibility 7/7 通过。

v43 使用原有 **96 GiB RSS / PSI 25% sustained 8 s** guard 和
**69.180055360 s** DCE watchdog，没有放宽阈值。修正 benchmark 所需 GSIM
reference 参数后，两次尝试在 hierarchy flatten 阶段因 parent cgroup PSI 被
终止；第三次在 DCE 阶段、native timer 与 removal callback 之前因同一 guard
终止，RSS 约 **84.0 GiB**、观测 PSI avg10 **56.68%**。该次 probe 仍只有 2 个
`target_roots`、14 个 `old_connection`、28 个 `canonical_witness`，零个
`operation_removed`。因此 v43 没有确定 connection **12834972** 的路径操作或
terminal definition **595807** 是否被删除，也没有改变剩余 **4,146** 个缺口的
分类。

截至 v43 的研究状态仍禁止在 uncovered surviving-endpoint removals 非零时运行
完整 analyzer；full trace/off actual-state equivalence、zero-uncovered inventory、
正式三轮 no-trace performance gate 均未完成。分析工具现有两条模式，不能替代
这些前置证据或正式样本：

- `make analyze_f31_dce_alignment_fast` 是每轮迭代的诊断入口。它仍校验 bundle、
  replay、输入与 root 身份、Node 因果解释、连接新增/删边、owner 覆盖及全部
  功能分类，只省略大型全量 TSV。它输出精确总数、最多 25 个未解释 Node 的
  path/ID/证据样例和 `diagnostic_only=true`；样例有界，不能把未列出的项目解释
  为零。其报告 `passed` 固定为 null，`acceptance_eligible=false`，不得作为最终
  验收通过信号。
- `make analyze_f31_dce_alignment` 生成正式完整 TSV 报告，仍是最终报告入口。
  两者都复用 `F31_ANALYSIS_CACHE` 下的 SQLite 验证缓存。缓存条目绑定所有输入
  文件内容 SHA-256、验证/报告代码 SHA-256、输入类别和 SQLite 自身身份；命中时
  执行只读 quick-check、结构和库存计数核验。损坏或身份变化按 miss 重建，缓存
  前会做空间余量检查。输入内容哈希仍需完整读取 bundle，这是确保旧缓存不会
  被误用的成本。快速路径省掉重复 replay、全量 TSV 及其写入流量；connection
  gap 因果审计本身仍需运行，不能仅凭热缓存承诺小于 20 分钟。报告记录实际
  wall time，可据完整香山输入测量确认是否满足 20 分钟目标。

实施验证新增 `make test_f31_analysis_fast_contract`：快速和完整摘要必须有相同
功能门计数，且覆盖 unexplained Node、连接差异、owner 违规和缓存失效。下一次
full diagnostic 应在 parent cgroup 压力降低后重试，仍使用相同 guard/watchdog；
不得用 no-liveness 的 diagnostic-only 结果替代完整 provenance trace 或正式性能
样本。性能门继续按本计划 §9：no-trace 三轮对比 GSIM 首次 DCE 中位数和既定
抖动带，trace 仅诊断并受 2×GSIM watchdog 约束。

### 10.33 最新完整静态捕获与多保留 Node 的语义分类（2026-11-16）

按本次用户要求，从完整原始 `build/xs/rtl/rtl/SimTop.fir` 重新捕获四份全量
Node/connection 表；没有启用 trace、重放 trace 或执行 trace 校验。入口为
[最新捕获说明](../../ptmp/firrtl-ingest/F31/full-node-structure-20261116/README.md)，
精确文件身份、阶段和 footer 见
[summary.json](../../ptmp/firrtl-ingest/F31/full-node-structure-20261116/summary.json)。

| 引擎 | 首次 DCE 边界 | Node 数 | 连接数 |
| --- | --- | ---: | ---: |
| GRH | before：post-split-static-array | 9,476,863 | 15,288,964 |
| GRH | after：post-dead-code-elim | 5,698,937 | 9,026,371 |
| GSIM | before：InferAllWidth | 9,635,014 | 15,568,445 |
| GSIM | after：RemoveDeadNodes0 | 6,020,694 | 9,506,107 |

GRH 前后来自同一次 raw FIRRTL 运行。GSIM 当前导出入口每次仅支持一个阶段，
前后来自同一冻结 binary、同一输入的两次独立 raw 运行；只建立静态身份一致性，
不据此声称完成单次运行生命周期验证。八份 TSV 位于上述目录的
`{grh,gsim}/{before,after}/{nodes,connections}.tsv`，Node 库存完整，连接中的
partial/unresolved 状态原样保留。跨快照不按 `connection_id` 数字直接连接。

输入 SHA-256 仍为 §2 所列值。GRH 冻结内容与最新 v45 包一致，source content
SHA-256 为 `91832e0ea7514ec5da1d7c12f645ae673adcac9bceb4126d813e53e60792a0e3`；
GSIM binary SHA-256 为
`4ec000f5a15a3ef7fc42d3dce56a52df1224c633d6e5a446b6188302c71e9aab`。
完整来源绑定见捕获目录 `package/identity.json` 和 `gsim/native/identity.json`。

只以 `'.'.join(name_path_json tokens)` 规范化，冻结 before 两侧均唯一的
**9,472,866** 对 Node，随后按各端原生 ID 检查 after；幸存 Node 的整行身份不变。
不以 native name 猜测路径，不把无对应 Node 混入配对分母。

| 固定 before 候选的删留结果 | Node 对数 |
| --- | ---: |
| 双方删除 | 3,557,262 |
| 双方保留 | 5,649,926 |
| **GRH 保留、GSIM 删除** | **45,742** |
| GRH 删除、GSIM 保留 | 219,936 |
| **合计** | **9,472,866** |

before 无唯一对应：GRH **3,997**、GSIM **162,148**。全库存删除量分别为
GRH **3,777,926**、GSIM **3,614,320**；其与配对删除量的差额来自无对应项。
完整清单和计数见
[node-deletion-counts](../../ptmp/firrtl-ingest/F31/full-node-structure-20261116/node-deletion-counts/summary.json)。

#### 10.33.1 回答“为什么多保留”的主分类

`demand/shared_anchor_demand/implementation/residual` 等原生规则标签不能回答
跨端语义差异。本次改为核对实际 Value、op、operand slot、共同存活 peer、
状态声明及 GSIM 的具体归一化路线，按主原因去重：

下表是深入调查前冻结的初始分类；其中 12,869 个目标的后续细化见 §10.36，
当前未解释数已降为 10,679。原始清单保留，便于核对分母及新增解释。

| 具体原因 | Node 数 | 已查明的差异 |
| --- | ---: | --- |
| **无用户的字段/元素别名** | **26,080** | 无 owned op、无确定或候选用户、无实际边界使用；同一物理 Value 的另一个 peer 在两侧均存活。GRH 多保留了名字，并非独立硬件功能。 |
| **有歧义候选用途的同值别名** | **4,202** | 无 owned op 或确定用户，但仍出现在 29,400 条 unresolved candidate 连接中；尚不能断言哪个身份可以删除。 |
| 断言事件时钟及其门控计算锥 | 135 | GRH SystemTask 有真实 clock operand；GSIM AST→special Node 省略 assertion clock，失去该依赖。 |
| JTAG TCK 域的状态、数据和复位锥 | 699 | GSIM 将外部 TCK 和 `Eq(TCK,0)` 当常量时钟并清除更新/reset；GRH 保留真实 helper 状态行为。 |
| 深度 1 memory 的地址 | 520 | GRH indexed read/write 仍消费地址；GSIM 将 memory 降为寄存器。读、写地址各 260 个。 |
| 普通单元素数组的索引及越界检查 | 34 | GRH 保留 indexed port 和 `index < 1` guard；GSIM 标量化时消掉 dummy dimension。 |
| 深度 1 memory 写端口身份 | 1,203 | GRH MPORT 字段仍拥有 masked writer；GSIM 把写树移入寄存器，清空原端口。 |
| **跨端原因尚未闭合** | **12,869** | 已知某些 GRH 依赖或结构，尚不能具体解释 GSIM 为什么删除对应 Node。 |
| **合计** | **45,742** | |

在这份初始分类中，已有具体模型/身份差异说明的是 **28,671** 个，其中 26,080 个属于应研究
回收的冗余名字；不能把所有非 `unexplained` 项都称为“必要的语义例外”。
4,202 个歧义别名的必要性仍未解决。目前也没有证明一个可独立计数的“仅因支持
DPI 而多保留”类别；路径到达 DPI 根本身不足以解释两侧差异。

主类先判身份冗余，再判物理值的根用途。原生所选路径中 179 个目标通向 assertion
clock，其中 44 个已证实为无用户别名，优先计入第一类；剩余 135 个包括 116 个
anchor 起点和 19 个 residual owner 起点。后者有实际 clock 实现路径，仍不能据此
声称这个源级名字自身不可退休。当前分类只选择一个已证明的主原因，不声称遍历
全部替代根；本节的 12,869 集合固定保存，后续细化以该集合为分母。

#### 10.33.2 具体证据与边界

- **别名**：`cpu.l_soc.io.pll0_ctrl_0`（GRH 7671204）无实现 op、无用户，
  store-local anchor Value 58734 的 peer 是 `cpu.l_soc.socMisc.pll_ctrl_regs_0`
  （GRH 60808 / GSIM 175987），后者在两侧均存活。26,080 个别名中，物理来源为
  selection 14,464、state read 5,633、comb 5,674、constant 86、aggregate 222、
  indexed state read 1；这些是物理来源，不能替代别名产生阶段的调查。
- **断言时钟**：`cpu.l_soc.io.clock`（GRH 26879 / GSIM 13436）从 native Value
  40456 经 7 步实际路径到 SystemTask 41216 的 clock slot 3。owner 为
  `cpu.l_soc.socMisc.xbar.effect@824577`，对应 FIRRTL 第 824577 行的
  `circt_chisel_ifelsefatal`。GSIM parser 保留 clock child 0，但 special Node
  构造时没有访问它；GRH 实际将其加入 operand。不能把它泛写成 system-task mask。
- **JTAG**：所选路径涉及 122 个实际状态族、255 个 writer；248 个 writer 的
  clock 经 Assign 到 helper 寄存器 `cpu$jtag$implementation$__jtag_TCK`，7 个到
  `Eq(同一 TCK, 1'b0)`。TMS/TDI 的真实角色是 writer data，reset 是 async reset
  event，不能统称 clock Node。
- **深度 1 memory**：`cpu.l_soc.socMisc.tl2axi4.nodeOut_w_deq_q.MPORT.data`
  （GRH 76019 / GSIM 41967）无 anchor，但拥有 masked writer 41521；实际 storage
  的 `firrtl.memoryDepth=1`。GSIM 将 writer 移入 reg 后该端口无用户。520 个地址和
  1,203 个端口 peer 在最新 GSIM-before 均为零出边。
- **单元素数组**：34 个 index 的其他 35 个组合直接用途全部是
  `kLt(index, 1'b1)`，回到同一 port 的读 mux guard 或写 enable；已排除其他直接
  用户，不能只根据 extent=1 就推定该 index 全部可删。

全量分类、逐 Node 证据和源码审计见
[语义分析报告](../../ptmp/firrtl-ingest/F31/full-node-structure-20261116/semantic-retention/README.md)、
[semantic-causes.tsv](../../ptmp/firrtl-ingest/F31/full-node-structure-20261116/semantic-retention/semantic-causes.tsv)、
[semantic-causes.jsonl](../../ptmp/firrtl-ingest/F31/full-node-structure-20261116/semantic-retention/semantic-causes.jsonl)
及 [GSIM 源码审计](../../ptmp/firrtl-ingest/F31/full-node-structure-20261116/semantic-retention/gsim-source-audit.md)。

最新四份静态库存是身份基准；细粒度 rooted path 与 after-IR 读取已有 v40 产物。
此前已确认两版完整 GRH before/after Node 库存逐行相同，输入、manifest 相同，
相关语义规则未变；这些是绑定到最新库存的历史同规则证据，不冒充本次新捕获的
依赖 trace。stored op/Value ID 与 native ID 会重编号，只按实际桥接关系连接，
不按数字相等连接。本次未执行 trace 校验，也未完成历史正式验收门。

### 10.34 下一步：别名产生与 12,869 个实际消费者

当前先做源码和已有静态数据调查，不修改优化器，不重跑完整 native 图或 trace。

1. **追溯别名产生阶段。** 分别核对 FIRRTL binding、`hier-flatten` 的端口 Value
   替换/名字归属迁移、`split-static-array` 的字段/元素 Node 建立。区分“源级名字
   已存在”“多个名字开始共享 Value”和“拆分后生成元素身份”，不凭最终结果把三者
   都归因于 flatten。GSIM 侧同时核对对应源级 Node、普通 connect、单元素数组及
   memory 标量化；所有固定配对目标在 GSIM-before 有独立身份，但这并不证明两侧
   物理别名表示相同。
2. **确定正确回收位置。** 优先在 DCE 中区分物理 Value 的存活和每个 SemanticNode
   身份的实际需求。保留 F30 before 身份与稳定 ID 约定；不能为减少 after 库存而在
   flatten 阶段批量擦掉源名。对无独立用户、无端口/事件/副作用边界的 alias，可
   规划只退休多余身份，继续保留被真实用户消费的 peer 和物理值。4,202 个候选别名
   先解歧，不能照搬 26,080 个的删除条件。
3. **固定 12,869 个调查分母。** 使用
   [unexplained.tsv](../../ptmp/firrtl-ingest/F31/full-node-structure-20261116/semantic-retention/unexplained.tsv)，
   为每个目标输出实际消费 op、operand slot/角色、consumer owner 名称，以及最近
   的具体 state writer/event/SystemTask/DPI 端点。无 anchor 的 owner 从自身 owned
   op 起步；共享 Value 的 consumer 不能自动归给每个别名。
4. **闭合跨端删除原因。** 对 GRH 有、GSIM 无的实际消费者边，核对 GSIM-before
   原表达式及准备阶段是否已删除 operand，或是否沿用等价 peer、清除了无效 writer、
   省略事件依赖。进一步检查实际 enable/mask、索引、bit slice 和状态族范围；只有
   找到具体结构/规则差异后才能从未解释集合移出。`InferAllWidth`、宽运算、到达
   DPI 或某种 root mask 均不能单独作为理由。
5. **形成可实施修复和最小回归。** 按已证明的原因分别规划 alias 身份退休、无效
   state writer/array 依赖裁剪或模型差异处理；先记录真实边界与反例，再确定代码
   落点和 Makefile 回归入口。此处的调查不自动授权把 GSIM 的缺失语义复制到 GRH。

### 10.35 别名的来源与正确消除位置

源码和实际对象调查见
[alias-origin-plan.md](../../ptmp/firrtl-ingest/F31/full-node-structure-20261116/semantic-retention/alias-origin-plan.md)。
结论是 **源身份建立、物理 Value 共享、DCE 名字回收三个步骤共同形成当前结果**，
不能简单把全部别名归因于 `hier-flatten`。

| 阶段 | 实际动作 | 与多保留的关系 |
| --- | --- | --- |
| FIRRTL ingest | `lower.cpp:301–329,1358–1385` 建立声明/字段身份；`:911–920` 给普通 connect 创建 Assign | 源别名名字本来就存在；不是为了统计而补出的名字。 |
| hier-flatten | `hier_flatten.cpp:942–1030` 复用端口 Value 代表；`:2429–2461` 按代表 Value union 既有 semantic anchors | 多个内部端口名字可共用物理值，但仍保持独立身份。`SemanticTree::flatten()` 只展开名字路径。 |
| split-static-array | `split_static_array.cpp:302–369` 建立所有 scalar member；`:407–441` 为实际 leaf 追加身份；`:2011–2015,2106–2110` 可直接复用已有叶值 | 生成元素名字，即使该元素没有消费者。两个元素同接一源时，名字不同而 Value 可相同。 |
| DCE | `dead_code_elim.cpp:1569–1599` 仅排除 incoming-port alias；其他 anchor 只要 `liveValueMask != 0`，便把每个 Node 都标为 demanded | **共同物理值的用途被推广给每个普通别名，这是无用户名字继续保留的直接规则。** |

GSIM **也有这些源名和拆分元素 Node**。`AST2Graph.cpp` 独立分配对象，
`splitArray.cpp:680–735` 为各 scalar member `new Node`；`Node.cpp:13–38` 从实际
表达式建立每个名字自己的 `prev/next`，`deadNodes.cpp:59–111` 沿这些关系反向标活。
所以它可以删除无消费者的 member，同时保留相同上游及有消费者的另一 member。
不能说“GSIM 没有别名”，也不能把它的源 Node 与 GRH 的多身份同 Value 表示等同。

具体例子：原 FIRRTL `8746626–8746630` 声明 `resetReg : Reset[2]`，两个元素都接
`reset_sync_resetSync.o_reset`，后续使用 `[1]`。GRH 的 `cpu.l_soc.resetReg_0`
（7671418）与存活的 `resetReg_1_0`（7671419）及上游输出（55004）共用 v54178。
`resetReg_0` 无 owned op、无确定或候选用途，仍因共同活值保留；GSIM 可以删除它。
这是重复源名字的存活问题，与新增 clock/DPI 功能无关。

**修复优先落 DCE 的 anchor→demanded 判定，保留 flatten/split 的物理共享与 before
身份。** 对普通 field/member alias，核对实际 semantic source、user、operand slot
和需求位，不能只看共同 Value 有用户；若无独立实现或身份用途，只退休多余 Node，
保留 Value、producer、live peer 及稳定 ID。已有 `replaceSemanticNodes` 支持这类退休。
不添加 dummy Assign，也不在 split 时漏建未使用元素来改变 before 对齐。

实现边界包括真实 top formal、keep/probe/XMR/external binding、零宽/零形状、
state current/next、必要 residual owner、实际 clock/reset/event/data 用途；4,202 个
歧义别名继续保守处理。26,080 是已记录自身用途均为空的分析集，尚非已完成反事实
验证的无条件删除清单。没有完整逐阶段 lineage，不能给全部对象指定唯一 creator pass。

最小实施顺序：先扩展现有 input-alias/slot-demand 回归到普通字段和重复数组元素；
再测穿过 parent/child 端口的同一例子；补上述受保护边界和歧义来源反例；最后只在
必要时补 flatten/split 的身份使用记录，并按 §10.34 重新计数。所有 build/test 通过
现有 Makefile 目标；本次尚未实施优化器修改或运行这些回归。

### 10.36 对原 12,869 个目标的实际消费者调查与新增语义原因

固定调查分母的 SHA-256 为
`102dcc12c0c0c4e1fd2a677f2f0e99553a277783b0c4ba462cbe1533a251d6a0`。
没有覆盖原始 `unexplained.tsv` 或初始八类报告。实际消费者全量表见
[nodes.tsv](../../ptmp/firrtl-ingest/F31/full-node-structure-20261116/semantic-retention/unexplained-consumers/nodes.tsv)、
[nodes.jsonl](../../ptmp/firrtl-ingest/F31/full-node-structure-20261116/semantic-retention/unexplained-consumers/nodes.jsonl)，
可读实例和边界见
[消费者报告](../../ptmp/firrtl-ingest/F31/full-node-structure-20261116/semantic-retention/unexplained-consumers/README.md)。

#### 10.36.1 “被谁使用”已落到真实 op/slot/owner

全表覆盖 12,869 个目标、10,704 个不同 anchor Value、22,285 个实际消费 operand
slot、20,376 个消费 op；直接 consumer 全部有实际 semantic owner 名称。1,242 个
无 anchor 目标从自身拥有的实现及原 residual group 单列，而不是伪造 Value 用户。
JSON 保存每个消费者的操作、slot、enable/data/index/clock/reset 等角色及 owner。

实际直接用途包括 ArrayUpdate entry index **545**、数组选择 index **735**、
state data **588**、state enable **19**、async reset event **19**、clock **3**、
task argument **135** 等；这是非互斥的实际用途统计，不能当作跨端保留原因分类。
所选原生路径的已映射端点包括 SystemTask 5,547、scalar writer 2,969、array writer
939、array-mask writer 56；部分路径尚有更近的未映射 op，表中明确标记，不称为完整
最短路径。共享 Value 的物理消费者也不自动证明每个名字自身必要。

例如 `cpu.l_soc.io.systemjtag.reset`（26890）真实进入 Assign **13895254 slot0**，
owner 为 `cpu.l_soc.jtag_reset_sync_resetSync.reset`；所选路径随后通向 DTM assertion
**187363** 的 enable。这说明它实际承担复位/断言控制依赖，不能按终点简单叫 clock。
`dmOuter.io_innerCtrl_source.io.enq.bits.resumereq`（137780）则直接进入 writer
**145942 slot2**，写 `mem.resumereq$NEXT` 的 data，属于 debug 请求的跨域存储数据。

无 anchor 的 1,242 个目标分为 **81** 个独占活跃状态实现、**469** 个单 owner
residual 实现、**692** 个多 owner residual 成员，涉及 605 个原 residual group。
后者需要继续判定每个身份的必要性；一个共享 op 存活不能证明整个 owner 集都必要。
检查所选 writer 的 enable/mask 的 Assign 终点，没有发现 literal-zero 实例；这只排除
该项直接常量检查，不能据此证明所有 guard 可满足。

#### 10.36.2 新增解释 2,190 个，剩余 10,679 个

| 原 12,869 个目标的新增主原因 | 去重 Node 数 | 真实差异 |
| --- | ---: | --- |
| 更广 debug/CDC 的 TCK 状态域 | **1,486** | 路径跨实际 TCK writer family；GSIM 常量化该域时钟、清掉更新和 reset，GRH 保留真实状态行为。 |
| 单元素组合数组的 ArrayUpdate 索引 | **545** | 实际只消费常量 0 index；GSIM 标量化 `[1]` 数组时删除对应 lvalue 索引。 |
| 被 GSIM 旁路的中间 clock 名字 | **150** | GRH 实际 writer clock operand 经该名字；GSIM 存活消费者直接使用同一根时钟。 |
| 被后续完整赋值覆盖的旧 CSR 条件锥 | **9** | GRH 仍保留早期 ordered writers；GSIM 构图时清掉被后写覆盖的旧树。 |
| **新增已解释** | **2,190** | |
| **仍未闭合跨端原因** | **10,679** | 仍保留全部真实消费者和待查事项，不以通用需求标签补齐。 |
| **原固定集合合计** | **12,869** | |

TCK 多标签命中 **1,487** 个：57 个 family 的全部 104 个 writer 已逐一沿实际 clock
operand 追到 `cpu$jtag$implementation$__jtag_TCK`，不是按 debug 名字推断。另 33 个
family、7 个目标未获得相同证明，未提升。Node **141087** 同时是已证明的单元素
ArrayUpdate index，主类优先取更直接的 index 消除，因此 TCK 主类新增 **1,486**。
此处沿用 §10.33 已核实的 GSIM 同一 TCK 常量化规则；它解释实际模型差异，仍不声称
每个共享源名字都不可退休。全体 TCK 主类由 699 增至 **2,185**。

**ArrayUpdate 索引**不是原来的 554 个 state-port index。新组实际涉及 5 个 `[1]`
组合数组：debug dmInner 1 个、v0Rat arch_table_next 8 个、v0Rat difftest_table_next
520 个、vlRat 两个 table_next 各 8 个。每个目标的全部直接用途都是对应索引，
Assign origin 为 `1'b0`，GSIM-before peer 全部零出边。例 Node **2554210**
`v0Rat._WIRE_8` 的 v5139934 被 ArrayUpdate **5129904 slot2** 消费；owner 是
`v0Rat.difftest_table_next`。该 op 的 520 组布局为 `base, enable,index,data, ...`，
base/output shape 均为 `[1]`。这是可安全研究消除的具体索引冗余，而非新增功能根。

**clock 旁路**与 JTAG 常量化不同。例 `cpu.l_soc.io.rtc_clock`（26895 / GSIM 13452），
实际存活 writer **90951** 的 clock slot2 沿 Assign 链经过它的精确 anchor v26542，
最终到 `cpu$rtcClock`。对应存活 GSIM consumer **7341374** 的唯一实际入源直接是
`cpu.rtcClock`（7360915），已不经过中间名字。150 项中 145 项落到 top clock、5 项
落到 `cpu$rtcClock`。另 105 个候选尚未闭合实际 state event operand，不计入此类。

**CSR 后写覆盖**的三个具体链为 mstatus 的 SD `_T/_T_1/_T_2`、FS
`_T_48/_T_49/_T_50`、SPP `_T_62/_T_63/_T_64`。以 Node **3887825** `_T_2` 为例：
v7608472 → Mux **7631733/7631737 slot0** → writer **7631736/7631740 order0/1**
的 enable。后一个完整 `when/else` 已用 **7631936/7631940 order2/3** 覆盖同一字段。
GRH `dead_code_elim.cpp:1017` 仍标活该族所有 writer；GSIM
`AST2Graph.cpp:1473–1485` 的 `saveWhenTree()` 在当前树没有缺失分支时执行
`assignTree.clear()`，旧条件链没有实际 next-state 用户。完整后写的语义是
`Qnext = p1 ? D1 : Qold`，早期 `p0/D0` 已无影响；后一组缺 else 时不能作此推断。
仅上述 9 个已核实所有用途，不将 mstatus 前缀的 **1,285** 个一并归类。

新增精确证据见
[GSIM 侧调查](../../ptmp/firrtl-ingest/F31/full-node-structure-20261116/semantic-retention/unexplained-gsim/README.md)、
[完整 TCK family 时钟证明](../../ptmp/firrtl-ingest/F31/full-node-structure-20261116/semantic-retention/unexplained-consumers/debug-cdc-family-clocks.jsonl)、
[CSR 后写覆盖](../../ptmp/firrtl-ingest/F31/full-node-structure-20261116/semantic-retention/csr-write-priority/README.md)。
按真实 Node ID 合并、核对路径/GSIM peer、检查交集后的结果为
[refinement-summary.json](../../ptmp/firrtl-ingest/F31/full-node-structure-20261116/semantic-retention/refinement-summary.json)、
[当前全部 45,742 个分类](../../ptmp/firrtl-ingest/F31/full-node-structure-20261116/semantic-retention/semantic-causes-refined.tsv)、
[新增逐 Node 证据](../../ptmp/firrtl-ingest/F31/full-node-structure-20261116/semantic-retention/unexplained-refinements.jsonl)
和 [剩余 10,679 项](../../ptmp/firrtl-ingest/F31/full-node-structure-20261116/semantic-retention/unexplained-remaining.tsv)。
汇总入口是 `semantic-retention/Makefile.followup` 的 `summarize-unexplained-refinements`。

当前 45,742 项中，具体模型/身份差异已有 **30,861** 项；另有 **4,202** 项歧义
别名和 **10,679** 项未闭合。下一步按实际收益规划：先修普通 alias 的身份退休规则，
再扩展后写完整覆盖的 CSR 实例与最小回归，并规划单元素 ArrayUpdate 的零索引消除。
剩余调查从已提取的 2,675 个源到共同存活 consumer 的 3,546 条跨端缺边入手，逐项
核对实际表达式；另外关注 692 个多 owner residual 的身份必要性、995 个 indexed/fill
writer 全 operand 保守传播目标及 248 个 indexed-read 整族传播目标。这些集合有
交集，只是具体调查入口，尚不算新增原因。没有把一般 `InferAllWidth` 或 DPI 路径
当成已证明差异。本次仅分析、写文档和整理已有静态证据，未修改优化器、未跑 trace。

### 10.37 实施三项语义裁剪并从原始 FIRRTL 重新导出

本节落实用户随后批准的三项修改：普通别名身份回收、标量 CSR 后写覆盖、
单元素 ArrayUpdate 索引消除。§10.35–10.36 是实施前调查记录；本节报告实施结果。
GSIM 源码和二进制未改，本轮只重新运行 GRH，比较沿用上一轮冻结 GSIM 静态库存。

#### 10.37.1 真实 IR 与身份处理

- **别名身份回收。** DCE 不再将共同物理 Value 的需求无条件推广给每个普通别名。
  候选必须没有活 owned op，另一个 peer 必须同时拥有活 producer 并锚定该值。
  按原生 exact op/slot、selected-read、named forwarding 证据确定有需求的实际
  source；缺失或歧义来源仍保守保留。端口、状态、零宽和非 Value/Predicate
  binding 等边界不按普通别名退役，named forwarding 链再做需求闭包。
  只退休多余 Node，物理值、活 producer 和必要 peer 不因此删除。
  用途在位需求去重前按 slot 记录；候选共享值与边界来源建索引，避免逐值扫描整个
  consumer 的 boundary 列表。规则不读取离线导出的连接表或目标清单。
- **CSR 后写覆盖。** 新增私有 `lib/transform/write_coverage.hpp`，在状态族标活
  前过滤有证明的冗余写口，随后普通 DCE 回收 writer 和专属条件/数据锥。只处理
  完整标量 register、唯一有效 `writerOrder` 和相同事件/边沿。分别证明 enable
  已知 1/0；四态 `p/!p` 不作恒真，缺 else、不同事件、mask 和 indexed writer
  仍保守保留。前面没有剩余 writer 的 Qold 写回可删，后续压制早期写的 Qold 保留。
  每族最多 64 writer，DNF/原子各 64、truth 缓存 256、证明 100,000 步；证明超限
  整族回退，不按 CSR 名字或旧调查中的 9 个 ID 特判。
- **单元素索引消除。** 对 ArrayUpdate 中 extent=1、可证明 index=0 的轴，不再
  传播旧 index 依赖；在真实 op 中将对应 slot 换成有定义的同 LogicalType 匿名零。
  `indexCounts` 与 `base,enable,index...,data` 布局保持合法；同完整类型零值共享，
  归属既有 consumer Node，不创建新公开身份。X/Z、动态、非零、越界和非单元素
  索引保守处理。该项覆盖组合 ArrayUpdate，不宣称已实现 memory/state-port 标量化。

公开 before 名字仍由原 ingest/flatten/split 流程建立。三项修改均在本次独立 DCE
内部生效；存活 Node 不重编号、不改名，不在输出后修补 Node 统计。

#### 10.37.2 最小回归与新运行入口

新增三个独立回归可执行：`transform-f31-dce-alias-retirement`、
`transform-f31-dce-write-coverage`、`transform-f31-dce-singleton-index`。
别名用例覆盖同值不同 slot、无/歧义证据、转发链、端口/状态/keep/时钟和特殊 binding；
CSR 用例用独立 ordered-write interpreter 穷举条件 0/1/X、初态与事件组合，比对
DCE 前后结果，并覆盖有/无 SemanticTree 的 20 个运行变体；单元素用例检查真实
operand 替换、1/65 位零、类型缓存、frozen graph、owner/observer/原生边界、
四态 oracle 和二次 DCE 幂等性。输入夹具补齐了与前端一致的 formal identity 映射，
前后公开连接完整性检查均通过。

通过统一 Makefile 入口运行新三套及已有 DCE、ArrayUpdate、SemanticTree、
pass-manager、comb-loop、split-static-array、simplify 共 **10/10 套回归**：
[test.log](../../ptmp/firrtl-ingest/F31/v46-semantic-pruning/tests/test.log)。
随后通过 `make py_install` 安装，`snapshot_f30_package` 冻结实际使用的新 native 包、
源码与依赖。工作入口是
[Makefile](../../ptmp/firrtl-ingest/F31/v46-semantic-pruning/Makefile)，
冻结身份见 [identity.json](../../ptmp/firrtl-ingest/F31/v46-semantic-pruning/package/identity.json)。

新捕获从完整原始 `SimTop.fir` 和原 F26 ingest manifest 开始，输入 SHA-256 仍为
`b313a3ecd154cbd9279b14403709806b95fb136cf44b475e9def46a926ecb26b`。
流程为 `ingest → xmr-resolve → hier-flatten → comb-loop-elim → split-static-array
→ before snapshot → 一次 dead-code-elim → after snapshot`，不读取旧 after IR。
保持 RSS 96 GiB 和 PSI 25% 持续 8 秒的资源保护。运行前仅对已有 artifact 页使用
`POSIX_FADV_DONTNEED` 释放干净文件缓存，无删除文件；父 cgroup PSI 回到 0。
本轮没有开启 trace，没有生成 evolution，也没有运行 trace 校验。

#### 10.37.3 新鲜全量导出

输出位于 [v46-semantic-pruning](../../ptmp/firrtl-ingest/F31/v46-semantic-pruning/README.md)：

| GRH 静态库存 | 新 DCE-before | 新 DCE-after | 上一轮 DCE-after |
| --- | ---: | ---: | ---: |
| Node | **9,476,863** | **5,643,352** | 5,698,937 |
| 连接 | **15,288,964** | **8,967,026** | 9,026,371 |

三项修改合计比原 after 多删除 **55,585 个 Node**、减少 **59,345 条连接**。
新 DCE 共删除 3,833,511 个原 before Node。四个 TSV 的 SHA-256、metadata、
completion footer 和行数核对完成，见
[summary.json](../../ptmp/firrtl-ingest/F31/v46-semantic-pruning/summary.json) 和
[SHA256SUMS](../../ptmp/firrtl-ingest/F31/v46-semantic-pruning/SHA256SUMS)。
全量文件为
[before/nodes.tsv](../../ptmp/firrtl-ingest/F31/v46-semantic-pruning/grh/before/nodes.tsv)、
[before/connections.tsv](../../ptmp/firrtl-ingest/F31/v46-semantic-pruning/grh/before/connections.tsv)、
[after/nodes.tsv](../../ptmp/firrtl-ingest/F31/v46-semantic-pruning/grh/after/nodes.tsv)、
[after/connections.tsv](../../ptmp/firrtl-ingest/F31/v46-semantic-pruning/grh/after/connections.tsv)。

捕获总用时 299.893 s；原生 DCE timing 为 **38.282 s**（外层调用 38.518 s）。
峰值 RSS **83,217,324 KiB，约 79.4 GiB**；guard 状态 completed、子进程返回 0，
见 [guard.json](../../ptmp/firrtl-ingest/F31/v46-semantic-pruning/grh/guard.json)。
这是本次静态捕获的观测值，不替代历史正式性能验收。

“全量”表示全部原生公开 Node 和连接记录均写出，包含无法唯一解析的 dependency
记录。新 after 的 dependency 为 resolved **8,589,861**、unresolved **215,023**，
覆盖仍为 partial；原 after 的 unresolved 为 336,756。state_update、storage_read、
storage_write 的覆盖均 complete，分别为 154,810、3,798、3,534 条。没有过滤
unresolved 以使结果显得完整，也不把静态文件完整性检查称为功能等价证明。

#### 10.37.4 固定候选上的删除结果

新旧 GRH 的 **9,476,863 条 before Node 身份逐行完全相同**（不比较运行 metadata）。
新 after 严格为旧 after 的子集，所有存活 Node 行保持原 ID、名字与路径，没有新增
或改名。固定 before 唯一配对仍为 **9,472,866**，见
[comparison.json](../../ptmp/firrtl-ingest/F31/v46-semantic-pruning/comparison.json)。

| 固定 before 候选分类 | 原库存 | 新库存 |
| --- | ---: | ---: |
| 两侧都删 | 3,557,262 | **3,581,287** |
| 两侧都留 | 5,649,926 | **5,618,366** |
| GSIM 删、GRH 留 | 45,742 | **21,717** |
| GRH 删、GSIM 留 | 219,936 | **251,496** |

目标方向减少 **24,025** 项，约 **52.52%**。另有 31,560 个双方原来都留的 Node
被本次 GRH 优化删除，因此反向删除差异增加；三项是 GRH 的语义裁剪，不以复制 GSIM
库存为规则，也不能将目标方向改善宣称为全部跨端差异都缩小。

下表沿用 §10.36 的**实施前主原因标签**，仅报告实际 after 成员状态；它不是三项
优化各自的独立消融实验，不能把未解释类的删除自动归成某个新原因。

| 原 45,742 项主类 | 原数 | 本次新删 | 仍保留 |
| --- | ---: | ---: | ---: |
| 无用户共享值别名 | 26,080 | **20,629** | 5,451 |
| 共享值歧义候选别名 | 4,202 | **183** | 4,019 |
| assertion event clock | 135 | 12 | 123 |
| JTAG/TCK 状态模型差异 | 2,185 | 32 | 2,153 |
| depth-one memory 地址 | 520 | 0 | 520 |
| depth-one memory writer 身份 | 1,203 | 0 | 1,203 |
| 普通单元素 array index | 34 | 0 | 34 |
| 单元素 ArrayUpdate index | 545 | **545** | **0** |
| GSIM clock 旁路身份 | 150 | 0 | 150 |
| 旧 CSR 覆盖条件链 | 9 | **6** | 3 |
| 原未闭合跨端原因 | 10,679 | 2,618 | 8,061 |
| **合计** | **45,742** | **24,025** | **21,717** |

545 个 ArrayUpdate 零索引目标已全部删除；CSR 的 SD `_T/_T_1/_T_2` 和 FS
`_T_48/_T_49/_T_50` 已删除，SPP `_T_62/_T_63/_T_64` 三项仍保留。
共享值别名不按原离线数量无条件删除，必须满足本节的原生 source/peer/binding 安全
条件。原 45,742 项的逐 Node 新状态见
[original-45742-current-status.tsv](../../ptmp/firrtl-ingest/F31/v46-semantic-pruning/original-45742-current-status.tsv)，
全部 55,585 个本次新删 Node 见
[newly-removed-vs-original.tsv](../../ptmp/firrtl-ingest/F31/v46-semantic-pruning/newly-removed-vs-original.tsv)，
当前目标方向 21,717 项见
[gsim-deleted-grh-retained.tsv](../../ptmp/firrtl-ingest/F31/v46-semantic-pruning/node-deletion-counts/gsim-deleted-grh-retained.tsv)。

SPP 三项的保留边界已做局部检查：新 after 的稳定 Node 链仍为
`3887886 → 3887887 → 3887888 → 3889885`；在历史同规则物理 IR 上，按当前
有界证明逻辑做局部 replay，在 `writerOrder=12` 构建 enable 条件时触发 **64 项
DNF 上限**，整族保守回退。此时 truth cache=231、atoms=19、steps=9,224，
没有触发其他三个上限。仅扩大 cache 或递归深度不能改变该触发点。
SD/FS 的局部证明最大项数分别为 3/14，与新库存的六项删除一致。
这解释了当前算法的覆盖限制，**不证明 SPP 旧条件链在电路语义上必需**。
局部 replay 使用已有静态 IR，按名字/稳定 Node 与新库存核对，不以旧物理 op/Value
数字对接新运行，也不冒充本次原生决定 trace。证据和复现入口见
[CSR SPP audit](../../ptmp/firrtl-ingest/F31/v46-semantic-pruning/csr-spp-audit/README.md)。
本轮保持该有界保护，未放宽预算或再次重捕获。

别名残留也未直接标成“语义必需”。按旧原生边界/producer membership 与本次稳定
Node 状态连接的轻量静态检查，5,451 个原“无用户别名”中有 **33** 个具有通向当前
存活 Node 的旧 named forwarding；4,019 个原歧义别名中有 **107** 个同类旁证。
例如 `intRegion.io.wakeUpToDispatch.8.bits.pdestCopy_0`（7907689）原生转发到
`fpRegion.io.wakeUpFromInt.8.bits.pdestCopy_6/7/8`（7910473/74/75），这些目标本次
仍存活。这说明“公开表没有自身 exact/candidate 出边”不等于“原生名字关系没有用途”。
所有残留别名在旧静态结构中仍有拥有 producer 的同值 peer，peer Node 本次也存活，
因此现有数据不支持将残留统一归因为 peer 缺失。

剩余 **5,418 / 3,912** 项还没有逐项归因。首个普通别名样本
`rat.intRat._t1_bypass_WIRE_0`（8157479）有单个非 formal anchor 和存活 producer
peer；其历史 mux 的两个 owner 分别是 `_t1_bypass_T_0`（8157503）与
`t1_bypass$NEXT_0`（9479393），本次均存活。旧原生 data forwarding 只为前一 owner
提供 source，没有为生成的 `$NEXT` co-owner 提供对应证据；按当前“每个 demanded
slot 的每个 owner 都须证明唯一 source”的规则，会保守保留同值别名。相邻 8157480
同形。这指出了后续可改进的具体来源映射缺口，不能解释成该无用户名字本身有必要
计算，也没有把两个样本的原因直接推广到全组。
其他对象仍须区分 source 缺失、歧义、binding 等保守分支；本轮没有逐 Node 原生
决定记录，不能补造完整归因。
全量事实与稳定身份样本见
[retained-alias-audit-summary.json](../../ptmp/firrtl-ingest/F31/v46-semantic-pruning/retained-alias-audit-summary.json) 和
[retained-alias-audit.jsonl](../../ptmp/firrtl-ingest/F31/v46-semantic-pruning/retained-alias-audit.jsonl)。
这些是历史原生结构与新库存的旁证，不是本次 decision trace 或功能必要性证明。

### 10.38 v47：修正 next-state 来源缺口，继续收敛

用户指出“怎么还有别名残留”后，本轮没有把 v46 的保守结果当作别名回收完成。
修正生成 co-owner 的来源证明、CSR 预算失败处理，并扩展 singleton 索引裁剪，
再用新冻结包从完整原始 FIRRTL 捕获；GSIM 继续使用原冻结静态库存。
工作与全量文件入口见
[v47 README](../../ptmp/firrtl-ingest/F31/v47-alias-source-closure/README.md)。

#### 10.38.1 修正内容与限制

**next-state co-owner。** `split-static-array` 将重建的表达式归属追加到生成 next
Node，而原生 source reference 可能只属于普通表达式 owner。v46 要求同一 demanded
op/slot 的每个 owner 都有独立来源，因此一个 `$NEXT` co-owner 缺证就保留全部共享
值别名。现在仅在以下真实结构全部成立时补足这一情况：

1. 原生 `state_update` 的 source 是该 owner，target 是实际 storage declaration 的
   current owner；若原 relation 带 user，必须是对应 writer。split 会将成员化关系的
   user 清空，因此 user=0 可由下述实际 writer 结构恢复上下文，hold 本身不够。
2. 该 owner 实际拥有存活 scalar `RegisterWritePort`，它的 `regSymbol` 对应同一个
   scalar register；同 owner 多 storage、indexed writer 或不相符 current 均不接受。
3. 真正 consumer 在 writer data 的反向纯组合闭包内，每步仍拥有该 next owner。
   不穿 ReadState/External/效果，不从 writer enable/clock 出发。
4. 同一实际 op/slot 的其他来源已存在且一致；只补 missing，不覆盖已有歧义或冲突，
   普通 owner 缺证仍保守。未按 `$NEXT` 名字匹配，也未任意选择同值 peer。

每 owner 最多 4,096 项，总缓存 100,000 op、16,384 owner、1,000,000 步，超限
保守。本次聚合统计为 fallback slot **8,130**、work **825,195**、cached op
**23,416**、owner **10,450**，没有碰到全局 proof 预算。见
[dce-phase-stats.json](../../ptmp/firrtl-ingest/F31/v47-alias-source-closure/grh/dce-phase-stats.json)。
这里是一次正常 pass 的聚合统计，未启用逐 Node 演化、依赖 trace 或 trace 校验。

**CSR 分段证明。** 后段复杂 enable 的 64-term 超限不再撤销此前已经完成的同事件
覆盖证明。失败 writer 与未分析 writer 是 unknown，不能当 disabled；完整 DNF 的
后续联合证明继续使用原工作计数。原 64 terms/atoms、256 truth cache、100,000
steps 未扩大。反例仍覆盖四态 X、不同 event、部分写和压制早写的 `else Qold`。
新全量 after 已确认 SD/FS/SPP 的原 **9 个目标全部删除**，并非只用小回归推断收益。
`state_update` 是公开连接库存，不能据其汇总行数不变推断实际 writer 未减少。

**singleton 状态索引。** 已知零、extent=1 的同型裁剪扩展到 `SliceArray` 和
`RegisterReadArrayPort` / `RegisterWriteArrayPort` / `RegisterWriteArrayMaskPort`。
状态维长读取真实 declaration 的 shape。真实 index slot 替换为同类型匿名零后，
原 producer/Node 才可回收；operation kind/layout、data/mask/enable/event 和现有
状态位需求规则不变。X/Z、动态、非零/越界、非 singleton 索引仍保守。
原 **520 个 depth-one memory 地址目标全部删除**；原 34 个普通单元素 array
index 仍存活，说明其其他实际用途尚未被本次规则消除，未宣称全体 singleton 问题完结。

#### 10.38.2 回归与新全量结果

11/11 回归通过，见
[test.log](../../ptmp/firrtl-ingest/F31/v47-alias-source-closure/tests/test.log)。
别名测试新增 15 组 next-state 正反例，包括 hold、普通 missing owner、错误 storage、
enable/clock 旁路、foreign owner、冲突、闭包预算及 frozen/ID/幂等检查。
新增 `transform-f31-dce-singleton-state-index` 检查 state read/write/masked-write 和
SliceArray 的真实 slot 替换、1/65-bit、维度、unknown enable、动态/X/Z/OOB、
frozen graph、布局、无新 Node 和二次 DCE；支持的 legacy oracle 做前后观察比较，
SliceArray X/Z 则要求整个图保持不变，避免用不支持该情形的 oracle 编造结果。

原始输入 hash、manifest 与阶段均不变。新旧 before 的 **9,476,863 个 Node 身份行
逐行相同**，新 after 同时为原始 after 和 v46 after 的子集，存活行不改名、不重编号。
完整比较见
[comparison.json](../../ptmp/firrtl-ingest/F31/v47-alias-source-closure/comparison.json)。

| 指标 | v46 | v47 |
| --- | ---: | ---: |
| GRH before Node | 9,476,863 | **9,476,863** |
| GRH after Node | 5,643,352 | **5,637,687** |
| GRH after connections | 8,967,026 | **8,959,217** |
| GSIM 删、GRH 留 | 21,717 | **16,458** |
| GRH 删、GSIM 留 | 251,496 | **251,902** |
| 两侧都删 | 3,581,287 | **3,586,546** |
| 两侧都留 | 5,618,366 | **5,617,960** |

本轮新删 **5,665** 个 Node，其中目标方向 **5,259** 个、原双方都留 **406** 个。
相对最初原始 after 累计新删 61,250，原目标 45,742 项已减少到 16,458。

| 原目标主类 | v46 留 | v47 留 | 本轮新删 |
| --- | ---: | ---: | ---: |
| 无用户共享值别名 | 5,451 | **1,231** | **4,220** |
| 歧义候选别名 | 4,019 | **4,019** | 0 |
| 原未解释类 | 8,061 | **7,545** | 516 |
| depth-one memory 地址 | 520 | **0** | **520** |
| 旧 CSR 条件链 | 3 | **0** | **3** |
| assertion event clock | 123 | 123 | 0 |
| TCK 状态模型差异 | 2,153 | 2,153 | 0 |
| depth-one memory writer 身份 | 1,203 | 1,203 | 0 |
| 普通单元素 array index | 34 | 34 | 0 |
| GSIM clock 旁路身份 | 150 | 150 | 0 |

此处继续沿用实施前主类，不把 516 个原未解释项的删除自动宣称为新的语义归因。
按“具体语义原因仍未完整闭合”的保守口径，当前为 **12,795 = 7,545 + 1,231 +
4,019**；此前 17,531 是 v46 口径，已被本轮推进更新。

四个 TSV 的 metadata、footer、hash 与行数核对完成，见
[summary.json](../../ptmp/firrtl-ingest/F31/v47-alias-source-closure/summary.json) 和
[SHA256SUMS](../../ptmp/firrtl-ingest/F31/v47-alias-source-closure/SHA256SUMS)。
新 after dependency 为 resolved 8,582,418、unresolved 214,657，覆盖仍 partial；
state/storage 类 complete。捕获 298.058 s、峰值 RSS 82,079,356 KiB（约 78.3 GiB），
96 GiB RSS / 25% PSI 持续 8 秒的 guard 正常结束。尚未替代历史正式等价/性能验收。

后续优先核对歧义 native source 集合是否会错误连带保留集合外别名，以及 split
packed 重建 view 的多 owner residual；不删状态根，也不把“存在值需求”充当语义解释。

### 10.39 v48：死状态族的 next 别名不再因历史 writer 身份永久保留

v47 仍遗漏一种真实过度保留：状态声明/current 与 writer 已全部死亡，但 next
身份锚定了另一个活表达式的共享 RHS。DCE 曾将全部状态 op owner 标为 `state`，
不区分 writer 是否活；旧 `state_update` 又赋予 required boundary，因此普通
别名回收无法进入。例 Node 9445449 原来关联 current 9445441；后者和 writer 已死，
after 只剩共享 RHS 到 next 的依赖，已不承担真实状态职责。

v48 不清除原 state 证据，而增加独立的真实 dead-family 证明：source 必须实际
拥有已死 scalar register writer；全部状态职责属于同一已死 storage；声明及所有
writer 无活需求；关系无 Value、target 拥有同一声明；若带 user，完整 ID/generation
必须匹配 source-owned dead writer。只有该关系可不再阻挡普通共享值别名回收，
随后仍要求活 producer peer、完整无歧义的实际 source 用途，named forwarding
闭包会恢复真实具名用户。无 writer hold、活 family、错误 current、多 family、
current-read 身份、formal/zero/special binding、opaque 关系和缺证仍保护。
每 owner 最多 4,096 项，总 owner 16,384、工作 1,000,000 步，超限保留。

新增 17 组实际 DCE 正反例，11/11 套回归通过。新冻结包从相同原始 FIRRTL、
manifest 和 pass 阶段重跑，未启 trace、未做 trace 校验。完整产物见
[v48 README](../../ptmp/firrtl-ingest/F31/v48-dead-state-alias/README.md)；
[comparison.json](../../ptmp/firrtl-ingest/F31/v48-dead-state-alias/comparison.json)
确认 before 9,476,863 身份行逐行相同，after 是原始及 v47 after 的稳定身份子集。

| 指标 | v47 | v48 |
| --- | ---: | ---: |
| GRH after Node | 5,637,687 | **5,636,238** |
| GRH after connections | 8,959,217 | **8,957,768** |
| GSIM 删、GRH 留 | 16,458 | **15,009** |
| GRH 删、GSIM 留 | 251,902 | **251,902** |
| 两侧都删 | 3,586,546 | **3,587,995** |
| 两侧都留 | 5,617,960 | **5,617,960** |
| 原普通无用户共享值别名 | 1,231 | **38** |
| 原歧义候选别名 | 4,019 | **3,973** |
| 原未解释类 | 7,545 | **7,351** |
| 原 assertion event clock 类 | 123 | **107** |

新增删除 **1,449** 项全部属于目标方向，其中普通别名 1,193、原歧义类 46、
原未解释类 194、原 assertion 类 16。分类是固定历史主类，16 项不能解释成删除
真实 clock 根；此前按名字诊断的 1,198 也不是生产证明删除数。其他历史类保持
v47 计数。保守尚未完整闭合为 **11,362 = 7,351 + 38 + 3,973**。

捕获 299.526 s、峰值 RSS 84,003,080 KiB（约 80.1 GiB），96 GiB RSS / PSI 25%
持续 8 秒 guard 正常完成。after dependency resolved 8,581,015、unresolved
214,611，覆盖仍 partial；state/storage complete。GSIM 沿用未修改的原冻结库存。

继续调查两项明确缺口：split packed reconstruction 的 shared residual helper
归属，以及普通 co-owner 的原生 source 丢失。后者已发现实际 shared Assign 的部分
owner 有唯一精确 source、另一些投影/分发 owner 完全缺少同一 Value 的原生 source
记录，公共 candidate 集合不能替代原生记录。这属于来源维护/证明缺口，尚不能
归为电路语义必须保留；后续优先在 split 增加归属时核对来源维护。

### 10.40 v49：完整已知来源集合与 packed helper 归属

本轮修正另两种过度保留，并补充精确来源与 named fallback 的优先关系。
完整产物见 [v49 README](../../ptmp/firrtl-ingest/F31/v49-retention-closure/README.md)。

**已知多源集合。** 旧实现把同一真实 user/slot 的多个非零原生 source 压成 0，
导致不在任何来源集合中的别名也整 Value 保留。现在保留完整原生集合，精确与通配
并存取并集、原优先级不变；集合内全部身份保留，普通 owner 缺证仍保守。next 缺证
仅在其他来源单一且一致、真实 payload 证明成立时补足，冲突标记不会被后一个 owner
重置。实际集合外 9502100–9502104 **5/5 删除**；两真实 writer 的历史来源集合是
8298430–8298436，而不是公共 walker 的候选 fallback。

**named fallback。** 对已回收 alias 的 user0 data 引用，只有 target 对该 Value 的
全部真实 slot 来源精确、整个 Value 用途完整、source/target 都未被真实用途选中，
且没有特殊根时才允许精确来源覆盖旧 named fallback。真实 forwarding 链、target
同时被选中、同 target 多 slot 中仍有 named/missing、clock/state/formal/special/
opaque 均保守。回归已验证此规则，但固定 33 个 named-forwarding 候选 **33/33
仍留**，不能把该修正当作这组实际原因或收益。

**packed helper。** split 重建会让多个已无普通身份需求的 scalar member 共同
认领 packed helper，实际物理用途却只通向同一个活 writer.data。新增只读 planner
仅接纳纯 Assign/Concat/ArrayCreate/SliceStatic、无活 result anchor/真实具名用途/
formal/state/特殊绑定的 owner。全部实际 live users 须闭合于同一个已有 next owner
的 scalar/indexed writer.data，严格匹配 storage/current 与精确 state_update；
enable/index/clock、foreign anchor、多 consumer、缺证均拒绝。原 owner 共享组的
全部活实现都证明同一终点后才统一迁移，预算失败不发布任意子集。不改物理运算、
writer operands 或状态根，不新造 Node；最终 owned-op 起点、计数、witness 重算。

原生聚合为 **123 op、1,080 memberships、32,889 work、0 budget exhaustion**。
实际新增的 228 个原未解释项全部属于固定历史 692 个 multi-owner residual，
该组仍留 464；scBiasResp 固定 32 项 **全删**，包含在 228 内。历史 469 个
single-owner residual、37 个 unique-state 本轮均未改变。见
[稳定 Node 交集审计](../../ptmp/firrtl-ingest/F31/v49-retention-closure/residual-audit/README.md)。
未把旧 user0 记录改造成精确 op/slot 来源，新输入 source 覆盖仍 partial。

| 指标 | v48 | v49 |
| --- | ---: | ---: |
| GRH before Node | 9,476,863 | **9,476,863** |
| GRH after Node | 5,636,238 | **5,636,005** |
| GRH after connections | 8,957,768 | **8,957,763** |
| GSIM 删、GRH 留 | 15,009 | **14,776** |
| GRH 删、GSIM 留 | 251,902 | **251,902** |
| 两侧都删 | 3,587,995 | **3,588,228** |
| 两侧都留 | 5,617,960 | **5,617,960** |
| 原普通别名 | 38 | **33** |
| 原歧义候选别名 | 3,973 | **3,973** |
| 原未解释类 | 7,351 | **7,123** |

新增删除 **233** 项全部为目标方向，没有重新引入 Node。before 身份逐行与原始
基线相同，新 after 为原始/v48 after 的稳定身份子集；比较现在同时记录新删与新留，
不以“每次只能少不能多”替代正确性验证。固定 9,472,866 候选对保持不变。
12/12 套回归通过；新增 source-set/named fallback、sticky 冲突及 helper 真实 DCE
正反例，helper 用四态 oracle 比较前后状态/输出，检查冻结图、ID、幂等和最终证据。

捕获 **308.256 s / RSS 82,208,292 KiB（约 78.4 GiB）**，原 96 GiB RSS / PSI
25% 持续 8 秒 guard 正常完成；未启 trace、未做 trace 校验。after dependency
resolved=8,581,015、unresolved=214,606，仍 partial；state/storage complete。

当前保守未闭合 **11,129 = 7,123 + 33 + 3,973**。普通别名 33、原歧义类 3,973、
历史完整唯一来源的 22 项本轮均未改善，不能用“值有需求”或历史零出边敷衍解释。
旧 JSON 不存 transient SemanticBinding，必须读取当次真实 bindings/anchors/owned
ops/原生引用来判断这些 Node 的实际保护条件。下一步静态 detail 设计复用
semantic_snapshot 的可选 Node 清单，不采集演化/trace，见
[设计](../../ptmp/firrtl-ingest/F31/v47-alias-source-closure/next-batch/node-detail-design.md)；
该接口尚未实施，不能把设计当作已获得的证明。split 增加共享归属时的来源维护也
仍需查证和修正，继续收敛目标保持进行。

### 10.41 F31 完成：最终 v51 库存与 DCE 后对应占比

按用户要求，DCE 对齐在本节记录的实际实现和库存收尾，F31 标记为**已完成**。
剩余差异作为已知限制冻结；不再实施转发别名 canonicalization 或继续逐项收敛。
本节覆盖之前各轮的进行中状态，不宣称两端达到 100% 结构或功能等价。

实现提交：wolvrix `e09a9826b44fa87da829049b6ffb310a107757ce`，GSIM
`bb4ddb7d48a8cd9c2f48347602b7ae5362f52cac`；主仓库同时固定这两个子模块版本。

最终 GRH 使用 v51 冻结包，从相同原始 `SimTop.fir` 和 ingest manifest 完整执行
`ingest → xmr-resolve → hier-flatten → comb-loop-elim → split-static-array → DCE`。
输入 SHA-256 仍为 §2 所列值。GSIM 沿用未修改的完整冻结基线，before 为
`InferAllWidth` 后，after 为首次 `RemoveDeadNodes` 后。最终捕获、完整库存
及校验和见 [v51 README](../../ptmp/firrtl-ingest/F31/v51-helper-static-closure/README.md)、
[summary.json](../../ptmp/firrtl-ingest/F31/v51-helper-static-closure/summary.json) 和
[SHA256SUMS](../../ptmp/firrtl-ingest/F31/v51-helper-static-closure/SHA256SUMS)。

**所需最终占比 = 5,617,898 / 5,635,937 × 100% = 99.67992900%。**
分母为 DCE 后**全部 GRH Node**，包括 helper 及未配对身份；分子要求对应的
GSIM Node 在其 DCE 后库存中仍存活。对应按现有 FIRRTL `name_path_json` token
用 `.` 连接的规范路径确定，并要求两端唯一；不按 physical ID 跨端匹配，不把
仅存在于 GSIM before、随后已删除的 Node 计入分子。这是静态唯一同名对应率。

| 最终指标 | 数量 |
| --- | ---: |
| GRH DCE-before Node | 9,476,863 |
| GRH DCE-after Node（分母） | **5,635,937** |
| GSIM DCE-after Node | 6,020,694 |
| 双方 DCE 后都存活且唯一同名（分子） | **5,617,898** |
| GRH after 未找到 GSIM after 对应 | **18,039（0.32007100%）** |
| 其中：GSIM 已删、GRH 仍留 | 14,770 |
| 其中：原始库存即无 GSIM 对应 | 3,269 |
| GRH 已删、GSIM 仍留 | 251,964 |
| 双方都删的固定对应项 | 3,588,234 |

计数闭合：`5,617,898 + 14,770 + 3,269 = 5,635,937`。固定 before 唯一同名
候选仍为 9,472,866。详细矩阵及逐项目标清单见
[Node 删除计数](../../ptmp/firrtl-ingest/F31/v51-helper-static-closure/node-deletion-counts/summary.json)、
[GSIM 删而 GRH 留清单](../../ptmp/firrtl-ingest/F31/v51-helper-static-closure/node-deletion-counts/gsim-deleted-grh-retained.tsv)，
接受终点与分母定义另存
[final-metrics.json](../../ptmp/firrtl-ingest/F31/closeout/final-metrics.json)。

v51 是最后一批已实施并验证的改动：packed helper 证明加入纯 Mux，并对唯一真实
writer、唯一匹配 current、完整无冲突 source-scope `state_update` 的 user0 场景
恢复 writer 上下文；特殊 binding、多个 current/writer、控制槽和整组缺证仍拒绝。
聚合为 543 个 op 归属迁移、1,500 条 membership 释放、47,399 步、0 次预算耗尽。
相对 v49 新删 68 个 Node、无重新保留；其中 6 个属于原目标差异，另外 62 个是
双方原来均保留的身份，因此反向差异从 251,902 增至 251,964，不能把 68 全算作
目标方向收益。原 LoadUnit 六个 Mux residual 候选已全部回收。

残留普通别名 33、历史来源歧义候选 3,973、原未解释类 7,117，保守未闭合计数
为 11,123。这些均保留为已知差异；普通 33 的具体位置为唤醒数据副本 21、异常位
常量副本 1、预取 selector 副本 3、L2 tag 转发 8，当前规则尚未归一这些真实具名
转发身份。此限制不再作为本阶段未完成项。

13/13 套原生回归和冻结包 snapshot API 回归通过。before 的 9,476,863 条身份
与原始基线逐行相同，after 为原始/v49 after 的稳定身份子集，存活 ID/名字不变。
v50 静态 detail reader 误读 inactive tombstone 的问题已修复并覆盖 compact
前后回归；v50 整体失败记录保留为摘要，最终依据为完整成功的 v51。v51 捕获
301.256 s、峰值 RSS 82,475,364 KiB，96 GiB RSS / PSI 25% 持续 8 秒 guard
正常完成。没有启用 trace、生成 evolution 或进行 trace 校验，也未重做整机动态
功能等价或正式性能验收。

收尾清理移除 3,882 个旧中间文件、772,464,635,516 字节（约 719.4 GiB）：
旧版本大型库存、trace、派生缓存、临时包及一次性脚本。另移除 `scripts/` 下
历史缓存归档、缓存驻留诊断、连接 gap probe 三组工具及其专项测试，共 6 个
脚本，并同步删除 Make 入口。持续使用的 DCE 构建/回归、静态交换、benchmark、
alignment 及等价/性能比较基础保留。完整原始双端基线、最终 v51 before/after、
冻结包、测试和小型历史报告保留；F31 目录由约 736 GiB 降到约 17 GiB。
删除清单和结果见
[cleanup-plan.json](../../ptmp/firrtl-ingest/F31/closeout/cleanup-plan.json)、
[cleanup-result.json](../../ptmp/firrtl-ingest/F31/closeout/cleanup-result.json)。
