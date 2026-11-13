# F28：SemanticTree 重构与 ingest→flatten 接通规划

日期：2026-11-13。状态：**首阶段已完成：统一 Path／Node 及 ingest→xmr→flatten 已接通，原生 22/22 回归、整机库存及跨端核验完成；剩余结构差异与未核实项明确列出**。本文件是 F28 唯一规划与实施记录入口。

## 1. 目标与范围

SemanticTree 的职责改为：在统一 GRH IR（包括 GrhSIM 方言）之上显式组织计算 Node，建立 GSIM Node 与 GRH op 集合之间的对应关系。GSIM 的 ENode 是 Node 内部表达式运算；GRH 的 op 是相应的实现运算，但两者不要求逐条一对一。

本次采用用户确定的结构：

- **只有一种 Node**，始终是叶节点，具有名字并包含一组实际 GRH op。
- 树的内部条目只表示路径，用于共享前缀和高效处理；不再区分 Module、Declaration、Expression、Predicate、Field、Element。
- `hier-flatten` 同时展平 IR 与 SemanticTree；结束后只有根路径与直接连接根的 Node 叶子。
- 关系由正常 ingest、xmr-resolve 和 hier-flatten 维护；普通导出直接获得完整 Node 和 op 成员。

F28 首阶段接通 `ingest-firrtl → xmr-resolve → hier-flatten`，并完成这条链所必需的核心生命周期、验证、持久化和 Python inspect 迁移。GSIM 对照边界采用 `AST2Graph/Init`，不跨入 `splitArray`、`detectLoop` 或 `InferAllWidth`。flatten 图中实际外部实例仍按真实边界处理；“全部叶子挂根”不要求删除 blackbox/external IR。

split、DCE、ExprOpt、GrhSIM 转换／分图等后续 pass 的 Node 演化维护另行推进。本阶段只设计必要的身份和成员接口，不把 F27 的物理重放或旧来源覆盖率当成新 Node 模型的完成证据。

## 2. 替换现有模型

现有 `SemanticNodeKind` 混合路径容器与源对象，op/value 通过 `semanticIds` 关联来源，`semanticBindings` 再补充九类端点角色。flatten 通过整树 append 保留层次，split 又通过 projection 增加端点而不增加源 SID。这个模型服务来源追踪，不能直接承担当前计算 Node 的库存与变换。

F28 直接替换这一模型，不再以旧 source SID 为新 Node 的定义，不保留旧六种 kind 作为并行主模型。旧的 source shape、field-depth、role、projection 等不继续作为每个 Node 的必填身份信息；类型、数组形状、寄存器／memory／effect 语义来自真实 IR。具体调试来源仍使用已有 SrcLoc 等设施，不为来源重建第二套 Node。

F26/F27 文档和 dump 保留历史身份。94.273220% 表示旧来源覆盖，不是新模型的 Node 对齐率；F28 不沿用其分母或成功结论。

## 3. 新数据结构与不变量

### 3.1 Path 与 Node

概念上的最小布局如下；名字和成员集合使用 Graph 所有的紧凑存储，不要求每个记录独立分配容器：

```text
Path:
    id, parentPath, nameSegment

Node:
    id, parentPath, name, ops[]
    anchors[]                 # 必要的实际 ValueId 边界引用
```

Path 与 Node 是两种结构记录，不是不同语义种类的 Node。根属于 Path，根及内部路径均没有 op；Node 没有子节点，也没有 `NodeKind`／`role` 字段。`anchors` 仅引用实际 GRH value，用于输入、别名和多输出边界等无法从 op 集合唯一确定的情况；不复制一套类型、状态或表达式载荷。无此需要时为空。

必须满足：

1. 每个 Node 的 parent 是本树有效 Path；禁止给 Node 添加子项。
2. 每个 Path 只组织路径；空路径可裁剪，不能作为无归属 op 的兜底 owner。
3. Node 的 op 集合去重，每个引用均为本 Graph 的存活 OperationId；value anchors 同样有效。
4. 一个实际 op 可以被多个 Node 引用，显式表示共享实现；不得为凑互斥分组复制电路。
5. Node 可以没有 op，例如顶层输入和保留的端口别名；空 op 不等于 dead，也不能自动裁掉。
6. 所有纳入 FIRRTL 范围的存活 op 都有明确 Node 成员归属；没有归属的实现必须在生产现场处理，不能塞到 module/root 使覆盖率通过。
7. Node 是分析对象；不改变 op 的执行次数、CSE 许可、调度和 IR 功能语义，不用新增无效 assign／identity op 保住 Node。

### 3.2 身份、名字与成员

Node ID 与 Path ID 分离，Node ID 是 Graph 内的对象身份，不再用树数组下标兼做 source SID。存活对象原位改写或换 parent 不改变 Node ID；单纯裁剪路径或重排存储不为 Node 重编号。跨 Graph 复制分配新 ID，返回显式映射；不得要求与 GSIM 数字 ID 相等。

名字在 ingest 时是所在路径中的局部名；flatten 后是包含完整实例／字段前缀的限定名。限定名编码必须可逆、确定并处理用户标识符中的分隔符；完整字符串只在必要时构造／驻留一次，不在每个 op 上复制。派生名字由正常生产者分配并处理冲突，不能靠消费者解析 `$NEXT`、`_0` 等后缀恢复身份。

`ops[]` 是 Node→op 成员关系的权威表示；实现可使用共用成员池和范围／索引。op→Node 的反向索引用于查询和维护，由同一 API 同步更新或按需生成，不形成两套可分别修改的事实。原有 op/value `semanticIds` 接口应迁移或退出，不能继续把旧 source owner 与新 Node member 混在一个整数域中。

Node 名称用于定位与阅读；IR 数据流决定成员子图的连接。比较单元时不能只有 op ID 列表：应读取实际 op 操作数、结果、属性及边界引用。共享 op 允许子图重叠；输入 Node、state current/next、memory/effect 的真实边界均须保留。

### 3.3 Node 建立粒度

下列对象全部采用同一个 Node 结构，表中的名称仅说明对象，不引入类型枚举：

| 对象 | ingest 阶段的处理 |
| --- | --- |
| 端口、wire、FIRRTL 命名 node 的数据叶 | 每个实际命名计算端点一个 Node，记录对应运算；Bundle 中间层只作路径 |
| 数组数据叶 | 在 split 前是一个 Node，数组 shape 留在 IR；不为未来成员提前建 Element 子节点 |
| 寄存器 | 对照 GSIM current／next 的真实对象分别建立具名 Node，状态声明／read 与完整 next 更新运算分别关联；不是新 Node 类型 |
| memory 与实际 port／地址 pipeline | 按构图中真实对象建立 Node，运算和 owner 关系从 IR 读取，不展开存储深度成一棵来源树 |
| 条件、effect、其他辅助计算 | 只在存在独立计算边界时建立具名 Node；纯内部运算留在使用者 Node 的 op 集合 |
| 输入、零宽、未赋值端点 | 允许空 op 集合，通过真实 value anchor 或明确的生产者空对象策略保留身份；单列统计，不能伪造运行时计算 |

current／next 与 memory 映射必须先用小图逐一锁定真实成员集合，不能把单个 guarded writer 的 data 输入当作完整 next。多个 writer 的顺序、enable、mask、clock/reset 仍由实际 IR 表示；Node 引用其完整实现，不复制新的角色 schema。

### 3.4 简例

```text
ingest：
root
  u                       # Path
    b                     # Path
      y                   # Node：ops={add, mux, 必要出口连接}
      data                # Node：ops={数组计算}，shape 留在 IR

hier-flatten 后：
root
  u.b.y                   # Node：ops={搬迁后的 add, mux, 出口连接}
  u.b.data                # Node：ops={搬迁后的数组计算}
```

例如 `y=mux(c,a+b,d)`，Node y 内部包含 add 和 mux；a/b/c/d 若对应其他具名 Node，其值是 y 的输入边界，不把这些 Node 的全部实现递归合并到 y。flatten 不执行 split，因此 `u.b.data` 此时仍是一片叶子。未来 split 应创建多个同层成员 Node，通过演化记录联系原 Node，不能把原 Node 改为容器。

## 4. 正常 ingest 流程

在 FIRRTL lowering 建立真实计算对象时创建 Node，在 op 创建、共享、writer 完成和端点发布时登记成员，不再导出后遍历旧 SID 猜 op 集合。

需要替换的主要触点：

- `lib/ingest/firrtl/lower.cpp` 的 declaration/field/predicate/generated semantic 创建逻辑：统一为 Path 或 Node 创建。
- `currentSemantic_`／`setOpSemantic`：改为当前 Node 构建上下文和成员登记；命名对象之间的表达式引用必须保留边界。
- `finishGuardSemantics`、常量缓存和其他共享实现：一次生产实际 op，向所有使用它的 Node 登记共享成员；不因缓存命中漏记。
- 寄存器、memory、effect lowering：登记实现这些对象的完整 op 集合与必要 value anchors；不从九类 binding 逆推 Node。
- 前序 `xmr-resolve`：其创建、替换、删除的 op 同步更新成员引用，未 flatten 的路径仍是有效路径。

每个模块模板只创建本图的 Path／Node 及本图 op 引用。实例化由 flatten 复制，不把父图的实例端口占位符和子图端口定义都当成两个同名计算对象。真正不同的具名端点即使共享同一个 value，也不能因此无条件合并；保留还是消除取决于实际端口桥接与 GSIM 构图对象边界。

## 5. hier-flatten 同步展平

flatten 直接产出新结构，不先深拷贝完整来源树再跑一次离线展平。

1. 为目标图建立根 Path，准备每个实例的 Node、op 和 value 搬迁映射。
2. 遍历模板的 Node 叶子，以实际实例前缀生成限定名，复制为目标根的直接子 Node；不同实例分配不同 Node ID。
3. 在普通 scalar、bulk、global-plan 路径中复用真实 op/value relocation；通过该映射搬迁 `ops[]` 与 anchors。
4. 端口 union-find／alias 的最终代表确定后，发布 Node 成员与边界；正确处理保留／消除的 bridge op，不引用已删除的 instance op 或原子图实体。
5. 父图 top 本身的 Node 同样迁移到根的一层叶子；删除不再需要的 Path。源模块 Graph 释放前完成全部引用转换。
6. 提交前验证所有 Node 直接连根、无重复逻辑端点、无悬空成员、无跨 Graph 引用。有 SemanticTree 时在展开前保存原 top 的精确事务快照；错误返回／异常都恢复原 top 的 IR、树、成员和 ID，不发布半棵新树。源模块的语义保持 compact／freeze 属于准备步骤，不回滚其物理布局；破坏性 topology consume 在这条路径停用，提交成功后才删除源模块。

现有 `appendSemanticTree`、`copiedSemanticRoot + oldSID - 1` 等整树连续搬迁假设退出。全局计划与普通 flatten 都使用显式 Node 映射；允许对紧凑 op 区块批量搬迁，不能回退成每个 Node 再扫描全图。

端口占位符去重、符号冲突重命名、生成块／数组实例路径必须在 producer 中处理并保留显式映射。不能在消费者按最终显示名猜别名，也不能为了与 GSIM 数量相同任意删／补 Node。

## 6. 核心与持久化迁移

| 层次 | 必须完成的改动 |
| --- | --- |
| `include/core/semantic_tree.hpp`、`lib/core/semantic_tree.cpp` | 替换六类节点与父子混合模型，提供 Path／Node、成员增删、显式 remap、flatten 和 verifier 接口 |
| `include/core/grh.hpp`、`lib/core/grh.cpp` | Graph 持有新结构；clone/import/compact/erase 同步更新实际 op/value 引用；路径回收不能删除空 op 输入 Node |
| FIRRTL ingest、xmr、hier-flatten | 在正常构图和变换现场维护 Node，不保留来源树构建作为主路径 |
| `lib/core/store.cpp`、Graph 导出路径、`lib/core/load.cpp` | 所有 JSON 模式一致保存 Path、Node 名字、稳定 ID 和实际 op／value 引用，引用按导出 ID 映射，严格验证 |
| Python Session inspect／stats | 直接导出新 Node 和 op 成员；分别报告路径、Node、成员引用和唯一覆盖 op 数 |
| 旧 bindings／owner 消费者 | 退出新模型的创建、验证和统计主路径；逐一迁移调用或显式阻止不支持的新模型流程 |

持久化已从 GRH JSON v4 升至 **v5**。新 `semanticTree` 保存根路径、内部路径与统一 Node 记录，不再写六种 kind 或旧来源 bindings 作为必要载荷。Node／Path ID 显式保存，不把文件记录顺序作为对象身份。

旧 v4 checkpoint 不自动转换成新 Node 模型，实施后通过正常 ingest 重新生成；不存在可靠的纯字段替换能把旧 source SID 还原成实际计算 Node。store/load/Graph 导出、Python、规范与测试在同一阶段同步更新，不出现两个写出 schema。

旧消费者清单至少包括 split-static-array、DCE 的 prune、NodeEvolution writer、GrhSIM partition-nonsink 和 provenance reader。它们不能把新 Node ID 当成旧 source SID 静默运行：首阶段未迁移到的流程需清楚报告支持边界，并维持库可构建和相关回归状态；不以自动去掉 SemanticTree 继续执行伪装支持。后续逐 pass 迁移使用新 Node 的创建／替换／删除／成员更新接口。

## 7. 实施步骤

| 步骤 | 交付与退出条件 | 当前状态 |
| --- | --- | --- |
| F28.1 | 新核心结构与不变量；Node 身份、命名、成员共享、空 op／anchors 的小例子锁定 | 已实施，核心回归通过 |
| F28.2 | Graph 生命周期、验证与 JSON v5；clone/compact/import/roundtrip 精确保留引用 | 已实施，三种 JSON 模式及生命周期回归通过 |
| F28.3 | FIRRTL ingest 正常构图维护 Node；覆盖组合、Bundle/数组、状态、memory/effect、共享计算 | 已实施，含无 writer hold、混合 ABI helper 与 elided port 专项回归；发布前检查实际 op 归属 |
| F28.4 | xmr-resolve 与全部 hier-flatten 路径原生迁移；flatten 后根直接连接全部 Node | 已实施，普通／全局计划、混合层次及零宽端口回归通过 |
| F28.5 | Python 正常 inspect／统计、新旧消费者迁移边界、相关文档和 Make 入口 | 已实施；首轮六小图、最终 ABI 专项和整机的正常 inspect／validate 均通过 |
| F28.6 | GSIM Init 小图逐 Node／成员核验，再完成冻结整机 ingest→flatten 测量与差异清单 | 已完成库存及检查范围内核验，完整差异／未核实清单见 9.6；不等于全部行为对齐 |

实施保持小步可构建；临时内部过渡在阶段退出前清理，不以长期双写旧来源树和新 Node 为最终方案。

## 8. 验收与统计

### 8.1 原生结构与生命周期

- ingest：内部全为 Path，Node 全为叶子；没有旧类型枚举参与建图或判定。
- flatten：每个 Node 的 parent 都是根，内部 Path 数为 0（统计时根另列）；不存在模块／Bundle 容器伪装的 Node。
- `Node→op` 与反向成员查询一致、去重且全部有效；被共享 op 不重复执行。
- FIRRTL 范围的存活 op 有明确成员归属；输入等空 op Node 保留有效边界，空集合不能因 prune 消失。
- 两个相同模块实例有独立 Node ID、正确前缀及各自 op 副本；端口别名只依据真实映射处理。
- clone、compact、Graph import、两类 flatten 实现和 JSON 往返都保存相同的语义对象、名字、成员和边界；失败不发布残缺结构。

### 8.2 必备小图

| 用例 | 要核验的内容 |
| --- | --- |
| `y=mux(c,a+b,d)` | 一个 y Node 含 add/mux，输入由其他端点引用，不把输入实现吞入 y |
| 嵌套 Bundle、数组与数组交错字段 | 路径只组织叶子；split 前一个数组数据叶仍是一个 Node |
| 两级层次、多次实例化、同名局部变量 | flatten 限定名唯一可读，全部挂根，op relocation 精确 |
| 输入直通／别名／输出端口桥接 | 空 op Node 合法，anchors 不丢，父占位符不与子端点重复计数 |
| 两个 Node 共用常量、guard 或表达式 | 共享 op 成员均可见，IR 保持一份，无错误吞并边界 |
| 多 writer、masked/indexed state、clock/reset | current/next 都是同一种 Node；完整更新实现和上下文可从 IR 读取 |
| memory、depth-one replacement、地址 pipeline、effect | 所有真实 Node 对象可定位，辅助实现覆盖，未支持差异明确失败／列出 |
| 名字含分隔符、生成名字冲突、零宽／未赋值 | 名字编码和冲突策略确定，空对象独立统计，不能把容器计入 Node |

优先扩展 `tests/grh/test_semantic_tree.cpp`、`tests/ingest/test_firrtl_semantic_tree.cpp`、`tests/transform/test_hier_flatten_pass.cpp` 与 `tests/store/test_semantic_tree_json.cpp`；fixture 按所属模块存放。

### 8.3 GSIM Init 对照与全量结果

比较对象是 **GRH Node 叶子与 GSIM 实际 Node**。GSIM 侧复用正常 Init 导出；若缺少必要字段，改进生产端导出。两端数字 ID 独立，不能按相同数字匹配，也不能只以同名或集合数量相同判断对齐。生产者保留可核验的命名对象对应，比较后再读取实际表达式／op 子图和跨 Node 输入边界；布局与状态等未核实项单列。

正常 inspect 和验收报告至少同时给出：

| 指标 | 计数对象 |
| --- | --- |
| `path_count` | 根以外的内部路径数；flatten 后必须为 0 |
| `node_count` | 统一 Node 叶子的实际数量 |
| `op_membership_count` | 去重后的 Node-op 关系总数 |
| `covered_unique_op_count`／`uncovered_op_count` | 实际 op 并集覆盖；共享成员不能重复抬高覆盖数 |
| `shared_op_count`／`empty_op_node_count` | 共享实现与空 op 叶子单列 |
| Node 配对与未配对数 | 两端分别作为分母，记录一对一／多对多关系，不能用来源投影并集冒充 Node 命中 |
| Node 子图核验结果 | 入口边界、内部连接及实际运算的通过／差异／未核实分开 |

F28 要求受支持小图中 Node 身份与成员结构可解释、差异无漏项；冻结整机必须给全量库存、op 归属清单、双方未对应 Node 和具体原因，不预先承诺节点数相等或 100% 行为等价。所有端点模型缺口必须在本阶段明列，不把类型未知当成功，也不把表达式正规化尚未实现当作功能错误。

测量记录 FIRRTL 内容身份、两端 producer 身份、阶段、耗时、峰值内存、JSON 大小与成员存储规模。内部路径使用整数／字符串驻留和批量映射，避免每 Node 扫全图、反复拼完整路径或每 op 保存全名；与同输入旧 ingest→flatten 基线报告实际开销。

### 8.4 Make 入口与文档

实施复用 `make test_grh_semantic_tree`、`make test_firrtl_semantic_tree`、`make test_f19_semantic_json` 等目标；增加 `test_f28_semantic_tree`（联合原生回归）、`capture_f28_semantic_tree`（普通生产链和 GSIM Init）、`compare_f28_semantic_tree`（只读库存／子图核验）及 `test_f28_semantic_comparison`。比较器不创建、修补或重建 Node；不需要它辅助正常 SemanticTree 构图。全部构建、执行和测量通过 Make；禁止直接调用编译器、CMake、CTest 或 Python 代替项目流程。

工作流日志及比较输出放在 `ptmp/firrtl-ingest/F28/`；C++ 测试产物沿用 `wolvrix/build/artifacts/`。实施时同步更新 GRH JSON／SemanticTree 规范、hier-flatten 文档、Python inspect 合约，以及本目录 index/steps。F28.6 完成前，状态始终如实标记为规划／实施中。

## 9. 当前记录

- 2026-11-13：完成现有 core、lowering、flatten、store/load、Python 与后续消费者的只读调查；确定上述替换方案与首阶段范围。
- 2026-11-13：实施新 Path／Node 核心与紧凑成员池，Node→op／anchor 与反向索引统一维护；正常 ingest／xmr／flatten、JSON v5、Python 统计同步迁移。
- 普通和全局 flatten 使用显式 Node 映射；具名端点共享 value 时仍保持独立。graph 的 `firrtl.semanticPortNames/Nodes` 与实例的 `semanticPortNames/Nodes` 在 producer 发布 formal-port→Node 关系，包含零宽／空数组，无需消费者猜名字。
- `make test_f28_semantic_tree` 当前 **22/22 通过**，覆盖核心、store/load、FIRRTL、XMR、flatten，以及后续未迁移 pass 的无变更拒绝；包含 hold／特殊名字／高共享重载、事务回滚与混合 ABI 成员维护。
- 首轮 GSIM Init 与 GRH ingest→flatten 全量 capture 和跨端库存比较已完成，见 9.2–9.3；据此补齐混合 ABI helper 的生产现场归属，并重新采集验证。

### 9.1 真实小图的当前证据

通过正常 FIRRTL ingest、xmr、flatten 和 GSIM Init 导出六个 fixture，结果位于
`ptmp/firrtl-ingest/F28/small/`。首轮生产者安装后已复采，以下统计保持一致；dump 保留真实 source locations。

| fixture | GRH Node | GSIM Node（含 memory） | 唯一名称候选 | typed 结构核验 | 未核实 | GRH 未配对 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| comb-boundaries | 11 | 11 | 11 | 7 | 4 | 0 |
| arrays | 9 | 9 | 9 | 4 | 5 | 0 |
| bundles | 19 | 19 | 19 | 15 | 4 | 0 |
| hierarchy | 17 | 17 | 17 | 6 | 11 | 0 |
| state | 13 | 14 | 13 | 4 | 9 | 0 |
| memory-effects | 17 | 18 | 15 | 4 | 11 | 2 |
| 合计 | **86** | **88** | **84（97.67%）** | **40（46.51%）** | **44** | **2** |

212/212 个实际 GRH op 有归属，共 243 条成员关系；12 个实际 op 被多个 Node
共享，23 个 Node 的 op 集合为空。每张 flatten 图均只剩一个根 Path。

名称只定位候选；两个未配对 Node 是 memory 读地址 current/next，GSIM 有显式
read-address role／endpoint，但尚无与 GRH 地址 pipeline stage 的对应证据。
GSIM 另有独立 when-condition Node；GRH 的相应 helper 是实际使用者的成员，
没有为数量相等额外造 Node。

所有真实 fixture 的 GRH IR 都是 FourState。`structural_checked` 只表示在已配对
入口边界前提下，实际类型和连接的正规形相符，不证明 X/Z 行为；二态
`expression_checked` 为 0。未核实还包括 state/memory/effect、动态数组索引及
未连接到 anchor 的构图遗留 op；64 条此类成员关系逐条写入
`grh-disconnected-members.tsv`。这些 op 实际存在并有明确归属，不能为提高比例
在消费者中忽略，也不能将尚未核实的表示差异称为功能错误。

只读比较器单测 `make test_f28_semantic_comparison` 首轮 **11/11 通过**。它读取实际
Node、ops、anchors 与 GSIM assignTrees，输出两端库存、Node-op／anchor 关系、
未配对及未核实清单；不参与正常生产 Node。

ABI 修复前原生联合回归 `make test_f28_semantic_tree` 曾为 **21/21 通过**。
新增事务测试覆盖原 ID 空洞、符号、metadata、
op/anchor 成员、retained topology，以及先成功展开实例后发生诊断失败或异常时的恢复。
无新树的旧流程保留原 topology consume 优化；新树路径用同一批量 operand 搬迁，
仅保存展开前的小 top，不复制展开后的整机图。

ABI 修复前 Python 原生库 SHA-256：

- `_wolvrix.so`：`fe23b3839b31e5d410cdcc1e87695508d0ae6ae78ceaaa7dd175f74398ac260e`。
- `libwolvrix-lib.so`：`147646eab05293297b1edaa94366f7e9778dd97d3486e8f1dc655ca873ec87af`。

### 9.2 冻结整机首轮原生结果（ABI 成员修复前）

正常 Make capture 已完成，记录为
`ptmp/firrtl-ingest/F28/full/capture-summary-grh.json`。输入是
`build/xs/rtl/rtl/SimTop.fir`（1,671,325,062 bytes），内容 SHA-256：
`b313a3ecd154cbd9279b14403709806b95fb136cf44b475e9def46a926ecb26b`。
复用 F26 的 `ingest-request.json`，包含辅助 SV、启用 layer、10 个 lowering
线程及相同 invalid/init 策略，不重新生成 FIRRTL。

| 原生库存 | ingest 后（全部模板图合计） | hier-flatten 后 |
| --- | ---: | ---: |
| SemanticTree／根 Path | 9,487 | 1 |
| 内部 Path（不含根） | 490,374 | **0** |
| Node 叶子 | 8,314,878 | **7,671,189** |
| 实际 op（含混合 SV） | 34,324,316 | 34,343,482 |
| Node-op 成员关系 | 37,184,331 | 36,559,714 |
| anchor 成员关系 | 8,104,409 | 7,460,932 |
| 唯一已归属 op | 34,322,634 | 34,338,400 |
| 尚无归属 op（待按真实来源分类） | 1,682 | 5,082 |
| 被共享 op | 66,698 | 57,219 |
| 空 op Node | 333,971 | 2,354 |

ingest 的分母是所有模块模板及父图实例端口占位符；flatten 使用真正实例展开
并按显式 formal/actual 关系复用端口 Node，不能把两个阶段的聚合数量直接解释成
一个 pass 应该拆出多少叶子。flatten 后名称空间占 743,365,468 bytes；实际成员／
anchor 引用共 44,020,646 条。结构校验 `valid=true/error_count=0`。

整体实际 op 归属比例为 99.9852%。这个分母包含辅助 SV；不能将剩余 5,082 个
一概称为 FIRRTL 漏项或一概排除为 SV。只读比较器按真实 `loc.pass` 和输入清单
逐项分类：`ingest-firrtl` 明确为 FIRRTL，`loc.file` 精确对应清单 SV 输入时才
确认 SV；其余保留 unknown，输出原始位置。全量中确认 FIRRTL 漏归属为 **0**，
清单 SV 为 **69**，自动分类 unknown 为 **5,013**。其中 4,080 项带有原生
`generated-sv:fnv1a64:…` 位置身份，来自 `mixed.cpp` 仅对 `svGraphs_` 执行的
`canonicalizeGeneratedLocations`；另外 **933** 项没有 loc。实际 IR 审阅已将它们
分解为 **900 个 ABI 桥接 op**（446 Constant、446 SliceArray、8 ArrayCreate）和
**33 个 SV DPI 声明**。900 项由 mixed adapter 根据 FIRRTL 端口签名现场创建，
位于 FIRRTL array／Bundle 端点与 SV scalar 端口之间，不能当成纯 SV body 排除。
33 个 DPI import 则都通过原生 `targetImportSymbol` 引用关联到 SV call，
其中 32 组位于生成 SV、1 组位于清单 SimJTAG.v。
FIRRTL lower 发布时另有完整成员门禁。

| 测量阶段 | F28 wall 秒 |
| --- | ---: |
| ingest-firrtl（含原生 inspect/validate） | 56.900 |
| xmr-resolve（含原生 inspect/validate） | 2.588 |
| hier-flatten（含原生 inspect/validate） | 92.843 |
| ingest→flatten 合计 | **152.332** |
| 写出保留 source locations 的 JSON／内容身份计算 | 75.366 |

capture 峰值 RSS 为 71,649,584 KiB（68.33 GiB）。同输入 F26 记录前三阶段合计
158.809 秒，整轮峰值 73,479,904 KiB；这只是其中一份历史记录，不能作为
F28 无性能回退的证据。其余旧记录及明确的计时口径差异见 9.7。
旧峰值还包含 comb-loop-elim，不能称为单一改动的严格消融实验。

flatten JSON 为 29,287,677,246 bytes，SHA-256：
`58547e65c528421ca60d3eb337953bd2a091d253c06ba06bde3f525dcb3b2ecf`。
GSIM Init capture 也已完成：152.878 秒、峰值 47,992,704 KiB、JSON
14,060,884,925 bytes，dump SHA-256：
`bed512cbeaaa6d9b2445f07c5a88159919a1084131d0154b23e71926528c0d86`。
GSIM producer SHA-256：
`6533de57de6f919d284b23a8b4775186885d4fe80de51ed54974a864bd75cafa`。

全量 GSIM Node 库存、候选／实际子图核验及双方差异见下一节；本节原生结构
完成不代表全部跨端语义核验通过。

### 9.3 首轮全量跨端 Node 核验与剩余接口缺口

两端库存是 GRH **7,671,189** 个 Node、GSIM **7,829,556** 个实际 Node
（`nodes` 7,826,232，另 `memories` 3,324）。唯一候选 **7,668,660** 对，分别占
GRH 99.967032%、GSIM 97.945018%；两端未配对数分别为 **2,529**、**160,896**。
候选依据生产者限定路径和显式端点信息定位，仍须检查实际子图。

| GRH Node 的首轮核验状态 | 数量 | 占全部 GRH Node |
| --- | ---: | ---: |
| 值类型／连接正规形相符，四态行为未证明 | 5,081,943 | 66.247136% |
| 未核实 | 2,463,698 | 32.116247% |
| 正规形或 geometry 存在差异 | 123,019 | 1.603650% |
| 未找到唯一候选 | 2,529 | 0.032968% |
| 合计 | 7,671,189 | 100% |

所有真实 IR 仍为 FourState，`expression_checked/interface_checked` 二态结论为 0。
第一行检查以对应的真实 anchor 边界为前提，不是整个状态机或 X/Z 行为等价证明。
第三行只证明当前正规形／布局比较不相同，不自动证明功能错误。

全量核验中修正了比较器对 Bundle memory 的候选位置解释：GSIM 的
`semantic.scopeDepth` 明确指出 memory 名字所在位置，因此 GRH 对照路径应为
`ram.$storage.field`，不能把 `$storage` 放在字段末尾。原生 Node／成员没有修改。
已有磁盘库存中新增／修正 2,825 对候选；这些 storage Node 的 anchor 数均为 0，
因此不改变其它已核验 Node 的边界前提，只需核验变化的 pair，并重出结果清单。
刷新后报告记录实际 input 内容身份和此复用依据；不重新构造 Node。

全部产物位于 `ptmp/firrtl-ingest/F28/full/comparison/`：

- `summary.json`：两端库存、GRH 分母的独立比例、来源分类与比较限制。
- `grh-nodes.tsv`、`gsim-nodes.tsv`：每个实际 Node 的库存和候选／核验状态。
- `grh-node-members.tsv`、`grh-node-anchors.tsv`：实际成员事实；共享关系保留。
- `unpaired-grh.tsv`、`unpaired-gsim.tsv`：双方没有唯一候选的完整清单。
- `unverified-or-different.tsv`：未核实及正规形／布局差异，逐 Node 给原因。
- `uncovered-ops.tsv`：全部 5,082 个未归属 op，保留严格来源分类和位置。
- `grh-disconnected-members.tsv`：未连接到输出 anchor 的实际构图成员。

这些只读文件用于审阅正常 producer 的结果；正常 ingest、xmr、flatten、store
和 inspect 不依赖比较器，也不依赖刷新入口辅助维护 SemanticTree。

### 9.4 混合 ABI 生产现场修复与最终原生复采

首轮清单暴露的 900 个接口 helper 已在 `mixed.cpp::Transaction::adapter`
创建现场登记到其实际服务的 FIRRTL port Node，同时赋予 `ingest-firrtl-abi`
位置身份。adapter 从 FIRRTL `PortLeafSignature.fieldPath` 建 Path／Node，发布
包含 elided port 的 formal 映射。真实 offset Constant、SliceArray、ArrayCreate
及 signedness view assign 都使用同一成员 API；不在导出后反推 owner。

仅逻辑 formal value 作为 anchor；物理 SV port 临时值不额外成为 anchor。
内部 implementation instance 仅承载有实际数据端口的临时成员，flatten 后删除；
零宽／空数组 Node 保持空 op、空 anchor，不用 transport op 保活。
无 SemanticTree 的 SV body 保持无 FIRRTL 成员。flatten 仍在原 FIRRTL 外部
实例处记录一次真实边界，即使其 adapter 现在具有树；内部实现不重复计数。

最终原生联合回归 **22/22 通过**，日志
`ptmp/firrtl-ingest/F28/tests/make-abi-final.log`。新增专项覆盖 singleton Bundle、
signed view、重复实例、参数 specialization、全部端口 elide、普通／全局
flatten、annotations 关闭及保留 source locations 的 JSON v5 往返。纯空 SV
实现可能被既有导入流程消除；all-elided fixture 用有真实 `$display` body
的 SV 实现验证空接口，此处未扩展空实现导入能力。

最终安装后以同一冻结 FIRRTL 和请求重新执行普通生产链；GSIM Init 未改变，
复用 9.2 的原始 capture。新证据位于 `ptmp/firrtl-ingest/F28/full-abi/`，
`capture-summary-grh.json` 为 `complete=true`。

| 最终原生库存 | ingest 后（全部模板图合计） | hier-flatten 后 |
| --- | ---: | ---: |
| SemanticTree／根 Path | 10,008 | 1 |
| 内部 Path（不含根） | 490,489 | **0** |
| Node 叶子 | 8,317,670 | **7,671,189** |
| 实际 op（含混合 SV） | 34,324,316 | 34,343,482 |
| Node-op 成员关系 | 37,188,023 | **36,560,614** |
| anchor 成员关系 | 8,107,201 | 7,460,932 |
| 唯一已归属 op | 34,324,055 | **34,339,300** |
| 尚无归属 op | 261 | **4,182** |
| 被共享 op | 67,219 | 57,219 |
| 空 op Node | 333,971 | **2,346** |

flatten 的 Node 数和 anchors 与首轮一致；实际新增 900 条成员关系，8 个
原本空集合的数组出口 Node 获得实际 ArrayCreate 实现。最终全部实际 op 的
归属率为 **99.987823%**，分母仍包含 SV。原生验证
`valid=true/error_count=0`，成员／anchor 引用共 **44,021,546** 条；
跨端结果及剩余 op 来源已按最终完整清单核实，见 9.6。

| 最终测量阶段 | wall 秒 |
| --- | ---: |
| ingest-firrtl（含 inspect/validate） | 59.717 |
| xmr-resolve（含 inspect/validate） | 2.694 |
| hier-flatten（含 inspect/validate） | 93.696 |
| ingest→flatten 合计 | **156.106** |
| JSON 写出及内容身份计算 | 76.261 |

峰值 RSS **74,929,460 KiB（71.46 GiB）**。最终 dump 为
29,287,993,994 bytes，SHA-256：
`b00cb25badb51a730ee91624c8a6c66098522249823a5b7c2ea0744ee3028646`。
最终安装 `_wolvrix.so` SHA-256 仍为
`fe23b3839b31e5d410cdcc1e87695508d0ae6ae78ceaaa7dd175f74398ac260e`；
实际实现库 `libwolvrix-lib.so` 已变为
`55b66166cb34182a439a05bc8107d4e18f94018e79c4cce989ec95b728cbe724`。

### 9.5 最终跨端复核的方法与边界

复采结果必须读入新的 `full-abi/comparison/`，保留首轮 dump、SQLite 和报告。
比较器允许复用首轮的已核验事实，但先流式检查新 dump 的全部实际对象：
root／Path、Node ID／名字／parent／anchors 必须一致，旧成员不得丢失；
全部 op/value 的 ID、字段、JSON 类型与物理载荷必须逐项一致，仅允许 `loc`
变化。新增成员必须引用真实 op，并精确等于本次预期的 900 条。
仅 external-instance 边界 metadata 的变化可单独记录，其余 metadata 必须一致。
任何前提不成立即拒绝复用，不能以旧摘要或相同总数代替逐对象核验。

上述前提成立时，未变化 Node 的实际 IR、成员和全部已配对 anchor 前提均未变，
因此保留其检查结果；仅重核成员有变化的 Node。新报告记录前后 capture 和库的
内容身份、全对象检查计数、成员新增与位置变化清单，完成后原子发布
`complete=true`。这些操作只核验正常生产结果，不参与 Node 生产，也不让
正常 ingest／flatten 依赖离线脚本。

只读比较器 `make test_f28_semantic_comparison` 最终 **20/20 通过**。
拒绝用例覆盖 ID／parent／anchor／成员删除、重复及无效引用、物理 op 类型、
value geometry、JSON 类型、root／metadata 改变，以及旧关系 TSV 残留；
失败时旧证据不变，新报告不能标记完成。

最终严格检查已通过 **7,671,189 个 Node、33,692,739 个 value、34,343,482 个
op、7,460,932 条 anchor 及唯一根 Path**。物理载荷变化、Node 身份变化、
anchor 变化、既有成员删除和 graph 边界 metadata 变化均为 **0**。
新增 **900** 条成员关系涉及 **59** 个 Node，另有 900 个 op 和 900 个 value
补充 ABI source location。因前述物理与边界前提全部核实，只重核这 59 个
Node，其余结果的复用有逐对象证据。

59 个受影响 Node 的逐项结果位于
`full-abi/affected-node-results.tsv`：32 个保持 `different`，27 个保持
`unverified`；新增实际成员没有使任何 Node 的核验状态桶改变。8 个 Node
由空成员变为非空成员，与最终原生空 Node 数下降 8 一致。

### 9.6 最终结果与退出结论

最终只读报告为 `full-abi/comparison/summary.json`，`complete=true`；
Make 比较耗时 **1,070.783 秒**，峰值 RSS **220,708 KiB（215.54 MiB）**。
完成表示全量库存、严格复核和清单写出已结束，不表示每个 Node 已验证通过。

| 最终两端库存与候选 | 数量 |
| --- | ---: |
| GRH Node 叶子 | **7,671,189** |
| GSIM 实际 Node（含 3,324 memory） | **7,829,556** |
| 唯一名称／端点候选 | **7,668,660** |
| 候选占 GRH／GSIM | **99.967032%／97.945018%** |
| GRH／GSIM 未配对 | **2,529／160,896** |

| 最终 GRH Node 核验状态 | 数量 | 占全部 GRH Node |
| --- | ---: | ---: |
| 给定已配对 anchor 边界下类型／连接正规形相符，四态行为未证明 | 5,081,943 | **66.247136%** |
| 未核实 | 2,463,698 | **32.116247%** |
| 正规形或 geometry 差异 | 123,019 | **1.603650%** |
| 未找到唯一候选 | 2,529 | **0.032968%** |
| 合计 | 7,671,189 | 100% |

最终 `expression_checked/interface_checked` 二态行为证明仍为 **0**。
名称候选不等于结构相符，结构相符不证明 X/Z、状态机或 memory/effect 行为。
`different` 只表示当前比较规则下的表示差异，不能直接解释成功能错误。
所有未核实及差异 Node 共 **2,586,717** 条，逐项保留原因，没有按比例隐藏。

成员清单由最终实际关系重新输出，共 **36,560,614** 条；anchor 清单共
**7,460,932** 条。在实际执行了 anchor 反向遍历的 Node 中，记录到
**7,011,870** 条不在该反向子图中的实际成员，保留在
`grh-disconnected-members.tsv` 中，既不忽略也不删除它们。state/memory/effect、
缺少唯一 anchor 或预算不足等情况可能提前退出，因此这不是全部成员的完整
连通性普查。共享、端口适配与构图遗留成员允许存在；是否已被当前子图核验
覆盖与是否具备真实 Node 归属是两件事。

本次新增断开成员恰为 **892** 条（446 Constant、446 SliceArray，涉及 51 个
Node）：它们从 FIRRTL 输入 anchor 正向计算 SV 消费端数据，当前 checker
从输出 anchor 反向找 producer，因此不能从输入 anchor 反向到达这些 helper。
这类断开记录本身不意味着 dead op；它们由 ABI 现场为输入适配创建，F28
尚未运行 DCE，也未对这 892 项另做完整活跃使用路径证明。
其余新增 8 个 ArrayCreate 直接产生输出 anchor，
可被反向遍历覆盖。892+8=900，与成员增量和空 Node 减量一致。

最终 `uncovered-ops.tsv` 为 **4,182** 项，严格自动分类为 FIRRTL 漏归属 **0**、
清单 SV **69**、unknown **4,113**。对保守的 unknown 进一步用实际生产位置和
调用引用复核后，剩余范围全部有 SV 证据：

| 未归属 op 的实际来源 | 数量 | 核验依据 |
| --- | ---: | --- |
| 生成 SV body | 4,080 | 原生 `generated-sv:fnv1a64:…` 身份；仅 `svGraphs_` 执行的位置规范化 |
| 清单 SV body | 69 | 实际 `loc.file` 对应同请求的 SimJTAG.v |
| SV DPI import 声明 | 33 | 实际 `targetImportSymbol`→声明 `sym`，共 115 处 SV call，33/33 声明均被引用 |

逐 op 来源证据为 `full-abi/manual-sv-origin.tsv`；它与最终未归属清单的实际
op ID 集合完全一致，遗漏／额外／重复均为 **0**。每行保存新旧 dump 身份及
严格复核状态。DPI 引用证据为 `full/comparison/sv-dpi-import-evidence.tsv`；
32 个 import 来自 generated SV 调用，1 个 `jtag_tick` 来自 SimJTAG.v:82。
全部 33 个声明在新旧 capture 的物理载荷和位置均未改变，因此旧引用证据可
明确关联至本次新捕获。自动 unknown 的保守分类保持原样，不伪装成自动证明。

最终审阅入口均在 `ptmp/firrtl-ingest/F28/full-abi/`：

- `capture-summary-grh.json`、`flatten.json`：正常原生链的库存、校验、耗时和完整对象。
- `comparison/summary.json`：最终状态、比例和逐对象复核依据。
- `comparison/grh-nodes.tsv`、`gsim-nodes.tsv`：两端完整 Node 库存。
- `comparison/grh-node-members.tsv`、`grh-node-anchors.tsv`：实际成员事实。
- `comparison/unpaired-grh.tsv`、`unpaired-gsim.tsv`、`unverified-or-different.tsv`：全部配对及检查缺口。
- `comparison/uncovered-ops.tsv`、`manual-sv-origin.tsv`：剩余 op 的原始分类与逐项来源证据。
- `comparison/native-member-additions.tsv`、`native-location-changes.tsv`、`affected-node-results.tsv`：本次 ABI 修复与受影响 Node 的完整变化。

F28 首阶段退出条件已满足：只有一种叶 Node；flatten 后内部路径为 0；
正常 producer 原生维护实际成员；冻结输入 FIRRTL／ABI 范围无未归属 op；
生命周期、事务、v5 往返、两种 flatten 与混合边界回归通过；两端全量库存和
所有检查缺口可审阅。原生回归 **22/22**、只读比较器回归 **20/20**。
后续工作使用此模型逐 pass 迁移，并分别解决剩余端点、类型、状态与表达式
核验缺口；本阶段不声称全部 Node 行为已对齐。

2026-11-13 两轮空间清理：按用户要求删除首轮 `full/flatten.json`、首轮大型
重复 TSV 及两轮 SQLite 索引；最新 `full-abi/flatten.json`、原始 GSIM Init、
最终 `full-abi/comparison/` 全部 TSV、摘要、capture 身份和小变化证据均保留。
报告仍记录完成时的核验结果；历史输入及索引不再齐备，不能直接重跑首轮
`--reuse-grh-from`，需先用相应 producer 版本重新生成所需输入／索引。
清理记录为 `ptmp/cleanup-20261113/` 及其 `deep/` 子目录。

### 9.7 性能复核：尚无同口径 A/B，存在验收链耗时增加的记录

不能用单个较慢的旧记录 158.809 秒与 F28 的 156.106 秒比较，就判定重构
没有拖慢流程。保留的旧摘要还有以下数据；均为同一冻结 FIRRTL／SV 输入、
10 个 lowering 线程、annotations 开启、invalid=zero、init=unknown。

| 记录 | ingest 秒 | XMR 秒 | flatten 秒 | 三阶段合计秒 |
| --- | ---: | ---: | ---: | ---: |
| `semantic-bindings/F26/grh` | 63.185 | 0.453 | 95.171 | 158.809 |
| `firrtl-ingest/F26/grh` | 50.189 | 0.455 | 74.822 | 125.466 |
| `F26/repaired/grh` | 45.520 | 0.449 | 45.549 | 91.518 |
| `F26/repaired-v2/grh` | 54.707 | 0.467 | 80.712 | **135.886** |
| F28 最终验收 | 59.717 | 2.694 | 93.696 | **156.106** |

相对较近的 `repaired-v2` 记录，F28 验收链总耗时增加 **20.220 秒（14.88%）**，
其中 ingest 增加 5.010 秒、XMR 增加 2.227 秒、flatten 增加 12.983 秒。
这些是现有采集结果的时间差，不是已隔离的重构净开销。

两种 driver 的计时边界不同：旧 `scripts/dump_f26_grh.py` 先保存 `wall_s`，
再执行 `semantic_stats`，且没有执行额外 `semantic_validate`；F28 的
`scripts/capture_f28_semantic_tree.py` 在每阶段 action 内执行
`semantic_validate` 和 `semantic_stats`，然后才停止计时。因此 F28 的
156.106 秒包含这些额外检查，而旧表中的时间不包含。上述各次 producer
内容身份也不同，并非同一受控环境的前后多轮实验。

这组历史记录只能说明验收链耗时不同，不能据此认定生产流程的回退比例。
去除外部检查的 F28 实测已补于 9.8；重构本身的净性能变化仍需用确定的
重构前版本、同输入／配置多轮 A/B 测量。JSON 写出及跨端离线比较应单列，
不加入生产前序耗时。

### 9.8 去除外部结构校验、统计与导出的三轮实测

按用户要求，在现有 `capture_f28_semantic_tree.py` 增加 `--timing-only`，
经原有 `make capture_f28_semantic_tree` 入口执行三轮顺序独立进程。
使用同一冻结 SimTop.fir、相同混合输入请求、10 个 lowering 线程和
`node_annotations=true`。三轮 source／request／已安装原生库身份一致，
实现库仍为 9.4 的 `55b66166…`，未修改或重新构建生产代码。

计时只围绕 `Session.read_sources(pipeline="ingest")` 及两个正常
`run_pass` 调用。没有调用额外 `semantic_validate`、`semantic_stats`，
没有 JSON 导出或 GSIM 执行；输入和库哈希、报告写出、返回诊断检查、
进程退出／Session 析构均不计入三阶段合计。原生 pass 内部正常的成员门禁
及结构检查保持开启，此测量不是关闭生产内部检查的特殊运行模式。

| 轮次 | ingest 秒 | XMR 秒 | flatten 秒 | 合计秒 |
| --- | ---: | ---: | ---: | ---: |
| 1 | 43.221 | 0.472 | 57.128 | **100.821** |
| 2 | 43.120 | 0.461 | 55.347 | **98.927** |
| 3 | 43.041 | 0.464 | 55.558 | **99.063** |

完整链总耗时中位数为 **99.063 秒**，范围 **98.927–100.821 秒**。
各阶段独立中位数分别为 **43.120／0.464／55.558 秒**；这些独立中位数
不要求相加等于总耗时中位数。三轮峰值 RSS 分别为
71,742,556／72,094,860／74,679,220 KiB。

因此当前 F28 正常三阶段调用约需 **99 秒**，不能再用包含额外检查的
156.106 秒代表这一计时范围。两组并非交错的同环境消融，不能把其差值
精确称为外部校验成本，也不能由此单独证明重构加速了多少。

产物为 `ptmp/firrtl-ingest/F28/timing-no-inspect/summary.json` 及
`run1`／`run2`／`run3` 下的 `timing-summary-grh.json`；每轮 `complete=true`，
Make 全部退出 0。小组合 fixture 先经同一 Make 入口确认该模式可运行；
脚本计时边界经独立只读复核。没有生成新的大 dump。

复验入口（每轮指定新的 `F28_WORK`）：

```sh
make capture_f28_semantic_tree WOLF_ENV_SOURCED=1 PYTHON=.venv/bin/python \
  F28_WORK=ptmp/firrtl-ingest/F28/timing-no-inspect/run-new \
  F28_INPUT=build/xs/rtl/rtl/SimTop.fir \
  F28_MANIFEST=ptmp/semantic-bindings/F26/grh/ingest-request.json \
  F28_CAPTURE_ARGS='--grh-only --timing-only'
```

### 9.9 提交前脚本清理与验证

删除 F26 旧来源 schema 以及 F27 旧 source-SID／offline replay 专用的
64 个分析／重放／benchmark 脚本与测试，不再把无法消费新 Node 的工作流
保留为当前入口。F20 的 v4 SemanticId coverage checker 和旧 bare-flatten
入口也退役；F19 JSON／ASan 的通用测试入口继续保留，实际测试使用当前 v5。
历史 F26/F27 文档保留结果，同时明确注明脚本退役及当前支持边界。

F28 保留正常 capture、只读 compare 及其回归。仍被比较器使用的 typed
bitvector normalizer 从 `f26_bitvector.py` 改名为 `semantic_bitvector.py`，
导入和独立回归同步迁移。GSIM 的正式 producer 库存／trace checker 仍由
Make 回归使用，全部保留；未复用的旧 F27 memory fixture 已删除。

提交前通过项目 Make 入口复验：

- `test_f28_semantic_tree`：**22/22**。
- `test_f28_semantic_comparison`：比较器 **20/20**，共用 normalizer **20/20**。
- GSIM `test-memory-inventory`、`test-source-aggregate-inventory`、
  `test-expression-inventory`、`test-semantic-lineage`、`test-node-evolution`：
  全部通过，包括13项trace生命周期检查、四图精确重放及无效事件负控。

日志位于 `ptmp/firrtl-ingest/F28/pre-commit/` 和 `tests/pre-commit-*.log`。
GSIM 本机缺少系统 GMP 开发头，复用了此前保留的本地 GMP 路径，经同一
Make 入口编译验证，没有安装或下载新依赖。
