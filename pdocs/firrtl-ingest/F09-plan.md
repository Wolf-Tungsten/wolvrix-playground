# F09：op 级软提示与统一 nonsink 分图

状态：2026-10-31 已完成 F09.0–F09.5，实现及证据见
[F09-acceptance.md](F09-acceptance.md)。本设计取代上一版“完整 node 先收缩成
不可分 atom”的要求，已撤除 F02/F08 的 source-node 优化屏障。F08 验收
保留历史含义，当前行为以 schema 2 / soft-node-v2 及本阶段验收为准。

## 1. 目标与基本规则

FIRRTL node lowering 后对应一组 GRH ops。把 op 与源 node 的关联记录在
op attributes 中，作为后续分图的可选参考，不建立独立 node 执行 IR，
不把源 node 当作不可分割的计算单元。SV 没有这些提示时，使用相同的
op DAG、分图算法和成本判断。

核心约束是：**node 标注不改变程序语义，不限制 simplify 的合法变换。**
普通 CSE、常量/别名传播、内联、重关联、mux/bit packing/写归一化和 DCE
不因 source-node 身份不同、根需要保留或提示难以传递而停止。属性不能
进入功能判等键，不能额外决定 CSE 作用域，也不能隐含 DontTouch。

phase、真实状态/效果、写优先级、类型、既有声明锚点和实际执行 owner
仍按普通 GRH/GrhSIM 规则约束变换。这些规则不是 node 提示产生的。
node hint 的开关不绕过这些正确性检查。

F07 的模块/端口/类型绑定负责跨语言连接，F09 使用链接后的 ValueId 和
operands。无需按名字给 FIRRTL node 寻找 SV wire，也无需让 SV 重建
已经丢失的源表达式边界。

## 2. 属性表达关联，不表达所有权

继续使用 GRH op attrs 承载，不增加 IR op kind 或独立 node 容器。已有
members/roots/rootResults/origins 的类型和身份编码可复用，但旧 schema/
policy 的强约束必须修订并版本化，不能仅修改分图选项后宣称完成迁移。

| 信息 | 新合约 | 不能解释为 |
| --- | --- | --- |
| members | 当前 op 与哪些源 node 的计算有关；允许多对多、重叠和部分保留 | 独占 owner、完整表达式证明、必须同组 |
| roots / rootResults | 仍能准确映射时保留的源结果关联 | 必须保留的执行 op、持久槽或完整根清单 |
| origins | 历史诊断来源 | 当前依赖、等价证明、归组亲和度 |
| 最终 partition owner | 分图后实际 leaf/supernode 身份 | source-node 身份的直接复制 |

分图可按 node key 建立临时 `key → 当前 ops` 索引。它是允许相交的提示
集合或超边，不要求构成 partition。一个 op 最终仍只有一个执行 owner。
多 node key 相交不做传递 union，否则一次 CSE 就可能把大量表达式强行
粘成一组。不同实例使用限定 key；phase copies 的相同来源不能合并 owner。

缺少 root、区域不封闭、非凸、覆盖不完整都可以是正常优化结果。提示可
局部采用、降级或忽略；不能要求重建完整 node 才允许继续优化/分图。
序列化属性的类型、版本和 result 序号仍须合法；格式损坏按加载/验证规则
处理，不能把“区域不完整”和“IR 格式损坏”混为一谈。

## 3. simplify 先执行，提示随结果维护

F09.0 必须审计并移除 node 信息对变换准入的影响，不能只把 `cseScope`
置空而留下 `mayInline`、`rootCarrier`、`annotated` 短路和 retention 断言。
已发现的入口包括 `lib/ingest/node_attributes.cpp` 的作用域/根工具，
`lib/transform/redundant_elim.cpp` 和 `grhsim/{simplify.cpp,rewrite.hpp}`
的 CSE/内联/根保留，以及 `mux_tree_fold.cpp`、`register_write_internal.hpp`
和 `register_write_normalize.cpp` 的 annotated 快速拒绝。路径相对 wolvrix；
审计覆盖所有调用方，保留真实 owner/效果约束而非直接删除整个安全判断。

| 变换 | 正常优化 | 提示维护 |
| --- | --- | --- |
| primitive CSE | 按功能、类型、operands 和实际 owner 等既有规则共享 | 代表 op 合并直接成员关联，去重；多来源允许共存 |
| 常量/别名传播 | 直接用常量或输入替换 | 有准确结果映射时更新；否则清除失效根、记录降级，不加 kAssign 载体 |
| 内联/重关联/融合 | 不检查 source-node 是否相同 | 对实际参与重写的 op 做有界传播；不能证明的分组信息降级为诊断来源 |
| 显式分裂/克隆 | 按普通语义规则产生新 ops | 可复制适用成员关联，结果根只按准确映射更新；提示不制造新依赖 |
| DCE | 无真实消费者即按原规则删除 | 删除或记录消亡提示；node inventory 不作为活跃根 |

不把每个 producer 的来源递归传播到所有消费者；引用另一个 node 的结果
不等于属于其内部计算。只传播本次重写实际涉及的关联，不建立无界上游
来源闭包。多对多集合按稳定规则去重；设置明确元数据预算，超预算时降级
提示并报告，不能拒绝优化、静默截出虚假完整区域或拖慢整个流程。

如果某次变换无法准确维护可选关联，应先完成合法变换，再移除/降级相关
提示。不能把不准确的 members 全部改写成 origins 后又用 origins 分组。
提示减少可以影响分图质量，不应改变计算结果或阻止生成模型。

### 3.1 与 F08 / GSIM 的关系

F08 的 source-node 隔离原本用于保留 GSIM 式重复内部计算；新决定撤销
这项默认约束。普通 CSE 可以合并不同 node 的相同内部 op，也可以合并
SV 与 FIRRTL 的相同 op，前提是现有功能和执行约束允许。

GSIM 的“等价组 ≥5、结果 >256 bit 或多后继”门槛不再决定普通 CSE 的
许可。`firrtl-node-cse=off` 不能解释为禁止跨 node 的 primitive CSE；保留
的整体 node 分析/额外优化仅作用于仍可证明的候选，不能通过冻结前序
simplify 维持候选。F09.0 须明确该选项的保留/废弃及配置迁移，不把新路线
继续标成 `source-node-v1` / `gsim-v1`。

F08-acceptance.md 继续记录已实现的历史行为；它不证明新软提示合约已经
实现。旧 checkpoint 必须明确区分策略，拒绝不兼容恢复或显式迁移，不
静默重解释已经发生过的优化。

## 4. 在同一 op 图上参考提示

```text
FIRRTL / SV → 同一 GRH op DAG + 可选 node attrs
→ 普通 simplify / 仿真转换（不受 node 提示限制）
→ 当前 nonsink op DAG + 临时提示索引
→ 同一候选生成、吸收、coarsen/segment
→ 最终 leaf/supernode → 现有后续简化与调度
```

统一引擎始终以 ops 和真实边为基础。提示可以建议“这些 ops 值得一起
考虑”、调整候选搜索顺序或在物理成本相同的候选间择优；不预先收缩成
不可回退的 atom，不设置 must-link、cannot-cut 或 mandatory-root。

首版使用固定既有成本：相同 node 关联只增加候选/决定确定性 tie-break，
不为提示来源设置低活动率或无限权重。候选必须通过真实依赖、owner、
效果、预算和 quotient 无环检查，成本不接受时可以拆开或完全忽略提示。
后续若加入亲和度/切边惩罚，必须是有界、可关闭、单独版本化和独立对照
的启发式，不能压过硬约束或冒充真实运行成本。

例如：

```firrtl
node n1 = xor(and(a, b), c)
node n2 = or(and(a, b), d)
```

普通 CSE 可以产生：

```text
t = and(a,b)   members={N1,N2}
x = xor(t,c)   members={N1}
y = or(t,d)    members={N2}
```

临时提示集合为 `N1={t,x}`、`N2={t,y}`。分图可以把三者放在同一组，
也可以保留真实共享边将 x/y 分组；不会因为两个集合共享 t 就强制合并
全部 ops。若后续 bounded clone 有收益，可按既有规则复制 t 并更新关联。

混合区域 `FIRRTL N → SV adapter → FIRRTL M` 同理：adapter 没有提示也
能参与共同合并；N/M 的部分 ops 可以跨源边界形成一组，其他 ops 留在
别组。提示之间的边界和提示集合内部的边界都不是绝对分图边界。

## 5. 成本、预算和最终 owner

`max-node-work`、`max-supernode-work` 对两种输入采用同样规则。源 node
超预算时允许按真实 op DAG 切开，无需为了切开提示集合另做“语义片段”
变换；调度正确性仍需验证。只有单个 op 本身超过预算时，才使用共同的
不可分 op 例外，与来源无关。shape 保留数组、Bundle 叶子展平不变。

共同成本逐步加入边界存储/比较/发布 bytes、固定调度、执行工作和额外
求值代理；同一可执行 op 只归属/计费一次。node 结果不强制发布，内部值
切开后可以发布，一切由真实跨 owner 消费者决定。常量/alias 不因有提示
单独制造 activity bit、持久槽或复制。

区分 source association、最终 leaf 和 supernode 即可，不新增必须保留的
source atom 层。当前 emitter 按 supernode 执行，simplify 按实际完整 leaf
隔离；这一限制来自已有执行模型。不同 source key 不增加新屏障，同一个
source key 也不授权跨 owner CSE。需要融合 leaf 时使用共同合法性规则。

bounded clone、叶内 CSE 后复核真实边界、工作量及预算，重建 writer
prerequisite 和 SinkSchedule，保留 effects、旧值采样和 mux 需求求值。

## 6. 配置和降级合约

保留计划中的 `firrtl-nodes=off|prefer|auto`，仅控制分图是否参考提示，
原型默认 off；不能改变普通 simplify 的准入规则。

- off：忽略分图提示，走共同 op 基线；保留属性及配置中独立启用的优化。
- prefer：参考当前可用关联，不保证某个 node 保持完整；无提示或提示
  未采用时仍正常处理，报告实际原因。
- auto：按相同软提示策略消费可用关联，无关联即共同基线；不能升级为
  强制完整区域策略。默认策略仍由 F11 决定。

schema/策略、算法与 cost revision、requested/resolved 选项进入配置和
checkpoint identity。旧八项 nonsinkConfig、旧 source-node policy 以及
F08 的 node CSE 选项必须在 F09.0/5 明确迁移；不能仅清属性后重用旧身份。

正常优化造成的提示合并、拆散、消失或无法恢复根，报告为共享/降级/删除，
不作为 simplify 失败。保留类型/版本/序号等表示层验证，不再要求每个
历史 node 在每个 checkpoint 具有活跃根和封闭计算区域。

## 7. 分步交付

| 子步骤 | 交付 | 通过条件 |
| --- | --- | --- |
| F09.0 去除提示屏障 | 修订 schema/policy、成员合并/根维护与 retention；审计 CSE/inline/annotated 短路及全部生产 passes | 有/无标注的普通优化结构等价；不因来源限制优化，不新增属性载体；旧配置明确迁移 |
| F09.1 提示索引 | 在当前 phase/owner 的 op 图上构建允许重叠、不完整的有界关联索引 | 多对多/不同实例/phase copies/alias/常量/丢失根正确降级，不按相交集合传递 union |
| F09.2 软提示分图 | 同一 op 引擎参考提示生成候选及 tie-break，固定旧 cost | 同 node 可拆、不同 node 可合、混合区域可合；无额外预算豁免或强制发布，off 复现基线 |
| F09.3 独立成本改进 | 共同 bytes/重算代理，必要时单独试验有界亲和度 | 不猜源活动率；提示、物理成本和亲和度分别消融，具有发布/额外执行证据 |
| F09.4 owner 与 clone | 最终 leaf、合法融合、bounded clone、局部 simplify 和依赖重建 | source key 不限制重写、不越过实际 owner；行为、effects、writer 依赖和预算通过 |
| F09.5 配置与验收 | Make/Python、恢复迁移、报告及真实模块 | 0%/部分/完整关联覆盖和 SV/mixed 回归通过，提示消费/忽略均可审计 |

已新增 `make test_grhsim_firrtl_nodes`、`make inspect_firrtl_partitions`，复用
已有 transforms、flow、node pipeline、CPU compiled 和 mixed 测试。修改
旧的“跨源 node 必须不共享/内联”断言，增加新的标注透明性与提示拆分回归，
不能只删除旧测试或把放宽限制误当作无语义风险的单行修改。

## 8. 验证和收益归因

首先验证标注透明性：同一初始计算图克隆两份，一份带标注、一份在测试中
仅移除 node 相关非功能信息；固定正常优化和执行约束，关闭独立的整体
node 优化/分图提示消费者。普通 simplify 的规范化计算图应一致，忽略
实体 ID、来源和诊断名字。另用行为记分板验证结果；仅行为一致不足以
证明提示没有挡住优化。

然后验证提示的分图效果：同一份已 simplify 的 checkpoint，保留完全
相同 attrs，固定 cost、clone、leaf 设置和 trace，仅切 off/prefer。
这里不能删 attrs 来模拟 off。成本改进、亲和度及 clone/leaf 融合分别
做独立对照；SV 前端与 FIRRTL 前端的端到端比较另行记录。

必须覆盖：不同 node 的公共子表达式被普通 CSE 共享、SV/FIRRTL 跨来源
CSE、内联/重关联、折叠为输入/常量后无载体、DCE、共享/拆散提示、超预算
node 正常切开、非凸/重叠集合、交错语言、Vector、phase copies、sink
私有锥、effects 和 writer prerequisite。最终验证每 op 唯一 owner、
quotient 无环、真实消费者激活、重复求值及旧值采样。

报告区分来源覆盖与实际采用：覆盖 ops/工作量、多成员 op、消失/降级关联、
候选采用/忽略原因、提示集合被切分数、跨来源合并、leaf/SN 分布、边界
bytes 与 clone 额外求值；另记元数据容量和分析 wall/RSS。使用诊断计数
解释发布/激活变化，正式计时关闭计数，不以 node 完整率作为成功标准。

F09 完成不代表整机通过；F10 负责香山混合输入及差分，F11 负责性能消融
和默认策略。此前 F08 的强隔离测量保留为历史样本，不充当新路线基线。

## 9. 实施结果

- schema 2 / soft-node-v2；每 op 的 members/roots/origins 分别上限 64，
  超限清除可选标注并计数，不拒绝合法重写。roots 丢失/重复、非凸集合合法。
- 普通与生产 GrhSIM 优化的标注/去标注结构对照通过；跨 node/SV 的 primitive
  CSE、inline、fold、packing、mux/write normalization 和 DCE 不受源提示限制。
- nonsink 使用现存 members，局部 leaf/cluster key 集合上限 256；只对等权
  coarsening 和同成本 segmentation 排序。off 保留 attrs 且复现共同基线。
- 独立 legacy/bytes 成本、可选 leaf fusion、有预算和实际输入可达性约束的
  单轮 clone 均已实现。bytes 是静态代理试验，尚无性能获益结论。
- 新配置版本化，旧 source-node checkpoint 要求重新 ingest，旧八字段 nonsink
  配置要求从 split checkpoint 重启。Make/Python/恢复及报告已接入。
- RenameTable 六组实验使用 SHA 相同的 split checkpoint；提示确实参与分图，
  但部分边界指标变差。Queue2 bytes 模式 compute 调用增加；默认仍为
  off/legacy/unfused，整机正确性和正式性能结论留给 F10/F11。
