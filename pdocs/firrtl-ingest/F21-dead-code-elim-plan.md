# F21：comb-loop-elim 后静态数组拆分、独立 DCE、SemanticTree 回收与 GSIM 对齐计划

日期：2026-11-06；2026-11-07 完成实施与验收，2026-11-08 完成拆分闭环复核。状态：**F21 原验收已完成；后续按审查结论新增 split-static-array，将拆分与独立 DCE 的默认声明保护关闭，并扩展到状态数组按需成员化、符号冲突及增量切片工作队列。** §1–§8 是实施前规划，原实测见 §9–§11，归因见 §12，组合数组实现见 §13，状态数组实现见 §14；最新 split 后全对齐证据、post-DCE 双向差异、删除矩阵、DAG 与性能见 §15。

## 1. 目标与既定决策

F20 已验收 `ingest → hier-flatten → comb-loop-elim` 的结构对齐。F21 在同一终点之后增加一次独立的
`dead-code-elim`，回答三个问题：

1. 现有 op 级 DCE 能否在保持现有保活语义的前提下删除无效计算，并同步回收不再被引用的 SemanticTree 子树？
2. 在同一份香山输入上，GrhSIM 的 DCE 与 SemanticTree 回收能否以可接受的墙钟和额外内存完成？
3. 与 GSIM 首次 `RemoveDeadNodes` 相比，两端实际删除和保留了哪些 Node，删除后的 Node DAG 有何差异？

已确定的边界：

- **最大限度复用现有 `DeadCodeElimPass`**，沿用 op/value 反向可达性工作列表、状态族传播和全部保活根；
  不另写一套 FIRRTL 专用 DCE。
- **GrhSIM 仍做 op 级分析。** 不复刻 GSIM 的 Node/ENode 活跃性、`sortedSuper` 遍历或 node 级删除算法；
  Node DAG 只在优化完成后用于统计与对照，不参与删除决策。
- **SemanticId 不保活任何电路 op/value。** SemanticTree 回收是 DCE 后的来源信息垃圾回收，不是另一套电路活跃性分析。
- **独立执行一次 DCE。** 新调用紧跟 `comb-loop-elim`，位于后续 `grh.verify` / `simplify` / `memory-init-check` 之前；
  F21 的删除和性能统计只针对这一次，不混入 `simplify` 的迭代轮次。
- **原定保持 `keep_declared_symbols=True`（后续审查已推翻）。** §1–§12 按该约束实施并归因；§13 起拆分与独立 DCE 改为默认 False，其余 pass 的默认行为不变，端口、效果和外部边界仍始终保活。
- F20 的 `align-bare` 保持为前置基线；F21 从同一 `post-elim` 分叉，不回写或重解释 F20 结果。
- 节点更少不是唯一的“更优”判据。必须先通过可观察边界与行为回归，再比较共同起始 Node 的双向删除矩阵和共同存活 Node 的 DAG。

## 2. 现状核查

### 2.1 现有 DCE 可直接复用的部分

实现位于 `wolvrix/lib/transform/dead_code_elim.cpp`，公开入口位于
`wolvrix/include/transform/dead_code_elim.hpp`，并已在 `wolvrix/lib/core/transform.cpp` 的 pass factory 中注册为
`dead-code-elim`。因此不需要新增一个同名或 FIRRTL 专用 pass。

当前算法已经具备：

- 从端口、声明符号、实例/黑盒、系统函数/任务、DPI 和 XMR 写等根开始反向传播活跃性；
- 对 register/latch 的声明、读口和写口按 `regSymbol` / `latchSymbol` 做状态族传播；
- 使用 op/value 工作列表到达自身不动点，而不是逐轮调用 `simplify`；
- 删除死 op 后清理无用户、无定义且非端口的 value；
- 通过 `keepDeclaredSymbols()` 保留声明锚点；
- 独立 `Stats::{operationsVisited,opsRemoved,valuesRemoved}` 和寄存器诊断报告；
- frozen graph、死寄存器族、活寄存器族、声明寄存器和报告的基础测试。

当前还有 `ingest::node::DeadRootBatch`，用于旧 `firrtl.node.*` 元数据。F21 保留其兼容行为，但不把它当成
SemanticTree 回收机制，也不让旧属性参与活跃性判断。

`SimplifyPass` 内部历史上也会调用 DCE。F21 不重构这部分既有逻辑；新增的是独立 pipeline 调用，不能用
`simplify` 的总耗时或后续内部 DCE 的删除量冒充本次独立 DCE 的结果。

### 2.2 现有缺口

1. `DeadCodeElimPass` 删除 op/value 后不会回收 SemanticTree，死来源分支及其名称字节仍保留。
2. `SemanticTree` 当前只有追加接口，没有删除或压缩接口。节点保存在连续数组中，ID 是数组下标，
   父节点先于子节点；直接删一个元素会使后续 ID 和 parent 全部失效。
3. value 和 op 都保存 SemanticId 列表。只遍历 op 会误删顶层输入等“没有定义 op、但仍有存活 value”的合法来源。
4. SemanticId 列表存在顺序、重复项及长列表驻留，不能借助逐行 setter 无序重建或意外去重；
   重编号后还要保持列表存储与哈希索引一致。
5. `wolvrix/docs/transform/dead-code-elim.md` 仍描述为“只由 simplify 间接调用”，与现有 factory 和本次独立使用不符，
   实施时必须同步更新。

### 2.3 插入位置与共享 pipeline 边界

FIRRTL/mixed 当前 full 路线在 `scripts/wolvrix_xs_grhsim.py` 中为：

```text
… → hier-flatten → comb-loop-elim → grh.verify → simplify → grh.verify → memory-init-check
```

bringup 路线为：

```text
… → hier-flatten → comb-loop-elim → memory-init-check
```

F21 在两条 FIRRTL/mixed 路线中都插入一次：

```text
… → hier-flatten → comb-loop-elim → dead-code-elim → 原后续阶段
```

这些 Python 列表也被其他入口引用。实施时用 pipeline 组合函数生成 **FIRRTL/mixed 变体**，不要无意中改变纯 SV
的既有 pass 序列；`read_source_pipeline` 的 flatten 前八阶段保持不变。现有 workflow 测试需同时证明：
FIRRTL 变体恰有一次独立 DCE、位置正确，纯 SV 基线不被隐式改写。

### 2.4 F20 对照基线

输入继续使用同一份 `SimTop.fir`：SHA-256
`cc46aae1a379d9e62132b76b0702685ba67761c87815067f770b0743d7dc754a`。

- GrhSIM 起点为 F20 最终的 `post-elim`，只经过 ingest、hier-flatten 和 comb-loop-elim；
  §3.12 记录当前为 **34,307,850 op**，454 个 false loop 全部修复，SemanticId 缺失为 0。
- GSIM 使用 `splitArray → detectLoop → topoSort → inferAllWidth` 后的首次 `RemoveDeadNodes`，
  不进入 `ExprOpt`、`UsedBits`、`SplitNodes` 或后续常量/别名/CSE。
- F20 预检中 GSIM 首次删除为 **9,631,690 → 6,012,371 Node**，删除 3,619,319；
  `RemoveDeadNodes` 内部计时为 **36.913 s**。整轮含解析、前序 pass 和 dump 为 8:07.57，
  不能把整轮墙钟当成 GSIM DCE 时间。
- F20 消环后的共同普通 Node DAG 基线为精确率 99.8130%、召回率 99.9744%；
  这些数字属于 DCE 前，不作为 F21 的结果或保证。

## 3. SemanticTree 回收合约

### 3.1 删除条件

对每张完成 op/value DCE 的 Graph，以所有**存活** op/value 的 SemanticId 为直接引用集合 `R`：

- `R` 中每个节点的全部祖先必须保留，以维持原有实例路径和字段路径；
- 一个分支只有在其中不再有任何存活 op/value 引用时才可删除；
- 某节点自身没有直接引用、但有存活后代引用时，作为路径祖先保留，不把祖先节点数当成活跃逻辑 Node 数；
- SemanticTree 根始终保留，即使最终只剩根；
- 无 SemanticTree 的图跳过回收，电路 DCE 行为不变。

因此，“一个 Tree 节点内部 op 全被删除”还需要满足**它及后代也不再被任何存活 value 引用**才能删除。
顶层 input、某些端口或别名可以没有定义 op 但仍有活 value；仅按 op 数删除会破坏合法边界。此类
“零 op、有活 value”的节点必须单列统计，不能误报为漏删。

实例 `Module` 子树和同名实例 `Declaration` 的结构关联也要保持：若一个实例仍有存活来源，保留路径所需的
模块节点和实例声明；若整个实例无存活引用，则成组回收。不能留下 F20 投影器无法解释的半棵实例结构。

SemanticTree 回收不改变 op/value 拓扑，不添加保活 op，不复制计算，也不把多个 SemanticId 合并成一个。
共享 op 携带多个来源时，只要 op 存活，其全部直接来源及必要祖先都保留。

### 3.2 批量压缩与重编号

不提供逐节点 erase 的热路径，以免连续数组产生 O(N²) 搬移。建议在 Graph 层增加一个内部批量入口，
由 SemanticTree 提供紧凑重建能力，步骤如下：

1. 扫描存活 value/op 的 SemanticId，使用按树大小分配的位图/字节数组标记 `R`；
2. 沿 parent 做祖先闭包，并补齐实例结构关联；
3. 按原数组顺序生成 `oldToNew`，保留下来的节点维持相对顺序和 parent-before-child；
4. 一次性重建节点数组和名称字符数组，修正 parent、`nameOffset/nameSize`，被删名称字节一并回收；
5. 按 `oldToNew` 批量重映射所有存活 value/op 的来源列表，保持列表顺序、重复项和空列表语义；
6. 重建或安全失效长列表驻留哈希，不能留下按旧 ID 内容建立的索引；
7. 校验所有存活 SemanticId 有效、路径与压缩前一致，然后一次性提交新树和来源存储。

JSON 仍使用 v4，格式不变。SemanticId 本来就是图内局部编号，允许在变换后改变；跨阶段身份继续使用
F20 的路径键 K，而不是数字 ID。final GRH compaction 是否执行由既有 pipeline 决定，单独计时，
不混入 DCE+SemanticTree 回收的本体时间。

实现需要分别保证：

- **电路透明性：** 除已判定死亡的 op/value 外，SemanticTree 回收不修改任何存活电路实体；
- **来源一致性：** 不出现半重编号树、悬空 ID、错误 parent 或名称偏移；
- **确定性：** 相同输入重复执行得到相同的存活路径、来源列表和序列化结果；
- **幂等性：** 第二次独立 DCE 不再删除 op/value/tree 节点，`changed=false`；
- **dirty 调度：** 只有电路变化才唤醒既有 `redundant-elim`，仅来源回收不触发额外 simplify 工作。

### 3.3 统计

扩展 DCE 的结构化统计，至少按 Graph 报告：

- 输入/存活/删除的 op、value、operand 边；
- 活跃性根分类及仅由声明锚点保活的 op/value/state 数；
- SemanticTree 压缩前后节点数（按 Module/Declaration/Expression/Field/Element 分类）、名称字节数；
- 直接引用数、保留祖先数、重映射 SemanticId 数、长列表驻留数；
- “零 op、有活 value”、共享来源、空实例子树等分类计数；
- op 活跃性、删除、tree 标记/重建、SemanticId 重映射各子阶段墙钟；
- DCE 前后当前 RSS 与流程峰值 RSS。

正式性能运行只保留低开销计数和子阶段计时；逐节点样本、详细路径和 dump 仅在诊断运行开启。

## 4. 实施分解

### F21.0 冻结基线与测量入口

- 固定 F20 最终 `post-elim` 的图身份、SemanticTree 统计、fragment map、GSIM split-array map 和两端二进制身份。
- 新增 `make test_transform_dead_code_elim`，直接构建并运行现有 `transform-dead-code-elim` CTest。
- 新增 F21 专用 benchmark/compare Make 入口；不得直接调用 Python、CMake、CTest 或编译器组成工作流。
- 性能实验只测量 F21 DCE 与 GSIM 首次 RemoveDeadNodes，不保留旧 DCE 库快照，也不设置旧 DCE 性能对照。
- 记录当前完整 CTest 基线。F20 最终为 76/84，既有 8 项失败不能写成 F21 新增或全部通过；
  当前工作树已有 sink 相关修改，也不得被 F21 覆盖或混入归因。

### F21.1 实现 SemanticTree 批量回收

主要落点：

- `wolvrix/include/core/semantic_tree.hpp`
- `wolvrix/lib/core/semantic_tree.cpp`
- `wolvrix/include/core/grh.hpp`
- `wolvrix/lib/core/grh.cpp`
- `wolvrix/tests/grh/test_semantic_tree.cpp`
- `wolvrix/tests/store/test_semantic_tree_json.cpp`

先完成小树、共享来源、长列表、实例结构和 JSON 往返，再接入 DCE。回收 API 不承载电路 liveness。

### F21.2 接入现有 DCE 并加入 FIRRTL pipeline

主要落点：

- `wolvrix/lib/transform/dead_code_elim.cpp`：在现有 op/value 删除完成后调用批量来源回收，补充统计；
  保留原有根、状态族和旧 `DeadRootBatch` 行为。
- `wolvrix/tests/transform/test_dead_code_elim_pass.cpp`：新增 SemanticTree 与独立调用回归。
- `scripts/wolvrix_xs_grhsim.py`：通过组合函数生成 FIRRTL/mixed full 与 bringup 变体，在 comb-loop-elim 后插入一次 DCE；
  不改 flatten 前八阶段，不隐式改变纯 SV 路线。
- `scripts/benchmark_xs_firrtl_ingest.py`：增加独立 F21 实验模式；原 `--align-bare` 仍停在 post-elim，
  不因生产列表变化而丢失基线。
- `wolvrix/docs/transform/dead-code-elim.md`、`wolvrix/docs/transform/simplify.md`、架构与流程文档：
  更新独立用法、SemanticTree 回收和实际阶段顺序。

### F21.3 功能与来源回归

- 完成 §5 的小图、真实 FIRRTL、生成模型和 JSON/ASAN 回归。
- 从同一 checkpoint 分叉比较 DCE 前后，不通过减少输出、效果或声明锚点获得删除量。
- F21 功能门禁通过后才发布全量性能与 Node 对比；失败时先修根规则或来源映射，不调低对照指标。

### F21.4 性能测量与必要实现优化

- 按 §6 测量包含 SemanticTree 回收的 F21 DCE 与 GSIM 首次 RemoveDeadNodes。
- 若未达性能门槛，优先优化已测热点，例如 op operands/results 的临时快照、重复符号属性查询、
  SemanticId 标记/重映射的额外副本；不得改成语义不同的简化流程。
- 每次实现优化后复验相同 op/value 删除集合、存活来源路径和输出行为，并重新测量 F21 与 GSIM。

### F21.5 Node 删除能力与 DAG 对照

- 将 F20 已在使用的流式投影、显式 split-array 映射和 guard/WHEN_COND 收缩逻辑固化为受版本控制的
  `scripts/grhsim_f21_dce_compare.py` 及小 fixture；不要长期依赖 `ptmp/firrtl-ingest/F20/*.py`。
- 复用 F20 的 K、生成节点分类、memory/状态特殊分类和二分边文件格式；数字 SemanticId 重编号不影响 K。
- 输出 §7 的删除矩阵、节点分类、DAG、差异归因和性能报告，写入 F21 实施结果后再更新阶段看板。

## 5. 正确性验证矩阵

### 5.1 SemanticTree 与 DCE 小图

至少覆盖：

| 场景 | 预期 |
| --- | --- |
| 完整死锥属于一个 Expression | op/value 删除后该分支及空祖先被回收 |
| 节点自身无 op，但存活 value 仍引用 | 保留该来源；顶层 input 等边界不被误删 |
| 父节点无直接引用、子节点仍活 | 父作为路径祖先保留，K 不变 |
| 一个 op 携带多个来源且仍活 | 全部直接来源保留，列表顺序与重复项不变 |
| 来源完全死亡的多实例子树 | Module 与实例 Declaration 成组回收，其他实例路径不变 |
| declared/DontTouch 根无输出消费者 | 按现有规则保活，SemanticTree 不反向删除它 |
| 死 register/latch 族 | 声明、读写口及其输入锥按现有规则处理，空来源分支回收 |
| 活状态及 reset/write cone | 状态和必要计算、来源保持完整 |
| 无 SemanticTree 的 SV/普通 GRH | 跳过树回收，遵循既有 DCE 保活与删除语义 |
| 有/无来源标注的等价图 | 规范化 op/value 删除集合一致，标注不成为保活根 |
| ≥64 项列表、共享列表和重复 ID | 重编号后内容、顺序、驻留与哈希查找正确 |
| frozen/tombstone、clone、compact | 无悬空 span 或旧 ID，第二次 DCE 幂等 |
| store→load→store | v4 字节和 SHA-256 一致，所有 ID 与 parent 有效 |

加入负控：故意保留一个死分支、删错一个活分支、漏重映射一个长列表、错误删除 input-only 来源，
相应断言必须失败，防止“树变小”空转通过。

### 5.2 FIRRTL 与生成模型

- 在现有 FIRRTL comb/state/memory/effects fixture 中增加未使用 node/wire/register、共享表达式、
  Bundle/Vector、数组状态、memory 端口、效果和 DontTouch 的组合用例。
- 对 DCE off/on 使用同一输入和初始化策略，实际编译并运行生成 C++；逐周期输出、状态记分板、
  效果次数/顺序和 FourState/TwoState 策略下的观察一致。
- `comb-loop-elim → dead-code-elim → grh.verify` 顺序回归通过，false loop 修复数和真环失败语义不变。
- JSON 重载后再次运行 DCE，结果与直接内存路线一致；Python `run_pass` 的独立入口实际执行，而非只检查注册名。
- 完整 native、shared flow、workflow、HDLBits 和相关 FIRRTL/GrhSIM 测试按现有基线无新增失败。
- F21 不以结构对齐替代 F10 整机动态等价；若本轮未生成并运行整机 emu，必须明确保留该未验证项。

建议验证入口（新目标先加入 Makefile）：

```bash
make test_transform_dead_code_elim
make test_grh_semantic_tree test_f19_semantic_json test_f19_semantic_json_asan
make test_transform_comb_loop_elim test_firrtl_state test_firrtl_memory
make test_grhsim_flow test_xs_firrtl_workflow
make test_f21_dce test_f21_dce_asan
make test_wolvrix
```

其中 `test_f21_dce_asan` 至少覆盖 `transform-dead-code-elim`、`grh-semantic-tree` 和 SemanticTree JSON 往返；
不能只运行不包含新 DCE 代码的旧 ASAN 目标。

## 6. 性能实验

### 6.1 两种测量对象

| 对象 | 起点 | 测量范围 |
| --- | --- | --- |
| F21 DCE | F20 最终 post-elim checkpoint | 独立 DCE + SemanticTree 回收，分子阶段计时 |
| GSIM 首次 RemoveDeadNodes | 同一 SimTop.fir | `removeDeadNodes()` 内部计时，不含解析、前序 pass 和 dump |

主要对照使用 `DeadCodeElimPass::run()` 本体墙钟，与 GSIM 的 `RemoveDeadNodes` 内部计时对应；
Python `session.run_pass` 外层墙钟另行记录，用于包含 PassManager、诊断和既有 retention 处理的集成成本，两个口径不得混用。

JSON load/store、最终 Graph compaction、GSIM 图 dump 和连续 ingest→DCE 总墙钟分别报告，不能塞入 pass 本体。
GSIM 的整进程峰值 RSS 包含解析与前序图，只能作背景；两端额外内存以 DCE 前当前 RSS、阶段内采样峰值和
阶段后当前 RSS 对照，不能直接拿两个整进程 max RSS 的差值宣称 pass 内存收益。

### 6.2 测量规程

- 同一机器、CPU 亲和性和线程配置；逐次固定并记录 F21 native 与 GSIM 构建身份，pass 本体均按单线程比较。
- 正式运行不开启 perf、逐节点日志或图 dump；诊断采样另列。
- F21 DCE 与 GSIM 各至少测量三次并轮换顺序，报告中位数、最小/最大值。
- checkpoint 加载完成后先记录图与来源计数，再开始 DCE 计时；每次使用独立 Design，避免前次 tombstone 或缓存影响。
- 同时记录绝对墙钟、每百万输入 op/operand 的 GrhSIM 吞吐、每百万输入 Node/prev-next 的 GSIM 吞吐，
  以及按共同起始 K 归一的时间。不同 IR 单位的吞吐只作辅助，不能单独据此判胜。
- 另跑一次从原始 FIRRTL 的连续 `ingest → flatten → comb-loop-elim → DCE`，验证真实接入位置与总成本；
  该连续时间不与 GSIM DCE 本体直接比较。

### 6.3 性能判定提案

以下是实施前登记的门槛，不是已测结果：

1. F21 在完整 SimTop 上连续三次完成，结果确定，无超时、异常或 SemanticId 错误。
2. DCE+SemanticTree 回收总复杂度保持近线性：
   `O(op + value + operand + storage-port + SemanticId + SemanticTree-node + retained-name-byte)`；
   不出现逐树节点全图扫描或逐节点数组搬移。
3. 目标为 F21 pass 中位数不超过同机 GSIM 首次 RemoveDeadNodes 中位数的 **1.0×**；
   若未达到，保留实测差距并继续按子阶段优化，不能拿旧 GSIM 整轮或不同机器数据凑通过。
4. SemanticTree 回收相对 DCE 前当前 RSS 的额外峰值目标为 **≤2 GiB 且 ≤5%**；
   同时报告回收后的净内存变化，防止只记录临时分配而忽略旧树未释放。
5. 若结构功能已完成但性能门槛未达，F21 状态必须保留“性能未达标”，不得仅凭 pass 能跑完就记全部完成。

## 7. Node 删除能力与 DAG 对齐

### 7.1 比较阶段和实体口径

| 路线 | DCE 前 | DCE 后 |
| --- | --- | --- |
| GrhSIM | F20 最终 post-elim | 一次独立 dead-code-elim + SemanticTree 回收 |
| GSIM | TopoSort/InferAllWidth 后、首次 RemoveDeadNodes 前 | 首次 RemoveDeadNodes 后，未进入 ExprOpt |

沿用 F20 的 K 和显式 split-array map；GSIM split 成员可还原到原始父 Node，GRH fragment 继承逐来源归属。
普通 Node、guard/WHEN_COND、寄存器 SRC/DST、memory storage、memory port、顶层端口、效果、外部边界、
零宽和 SV 实现分别计数。`NODE_MEMORY` 是否计入总数必须明确列出两种口径，不能混在普通 Node 中。

同时报告：

- **原始量：** GRH op/value/SemanticTree 节点与 GSIM Node/ENode 的各自前后数量；
- **可比较量：** 按 K 投影后的 Node 数与 DAG；
- **来源树物理量：** SemanticTree 的祖先/字段/实例节点只用于内存和来源完整性，不直接等同于 GSIM Node。

### 7.2 共同起始 Node 的删除矩阵

设 DCE 前双方已匹配的普通及特殊 K 集合为 `C`，GrhSIM/GSIM 删除后的存活集合分别为 `Sg` 和 `Ss`：

| 分类 | 定义 | 含义 |
| --- | --- | --- |
| 双方删除 | `C \ (Sg ∪ Ss)` | 共同死逻辑 |
| 仅 GrhSIM 删除 | `(C ∩ Ss) \ Sg` | GrhSIM 更细的潜在收益，须逐项解释 |
| 仅 GSIM 删除 | `(C ∩ Sg) \ Ss` | GrhSIM 的保留项，须区分保活根与漏删 |
| 双方保留 | `C ∩ Sg ∩ Ss` | 后续 DAG 的共同比较集合 |

每项再按 op 数、位宽、模块和 Node 类别加权，并给出 Top 20 模块与有界样例。仅由 GrhSIM 声明锚点保活的项
单列“策略性保留”，不从实际图中删除，也不为了实验关闭锚点。另设排除已知表示差异后的分析视图，但实际生产数字始终放在主表。

### 7.3 DCE 后的 Node DAG

做两组报告，避免把删除差异伪装成边差异：

1. **各自前后：** 两端分别报告 DCE 前后 Node/edge 数、入度/出度 p50/p90/p99/max、孤立节点、
   最大度数节点和 SCC 数；GRH 在 comb-loop-elim 后不应引入新环。
2. **共同存活集合：** 仅在“双方保留”的 K 上取诱导子图，沿用 F20 的 guard/WHEN_COND 收缩和
   prev/next、无 dep 边口径，报告共同边、两端独有边、精确率、召回率、度数分布及 Top 20 模块。

删除矩阵使用 DCE 前的 `C`；DAG 主比较使用 DCE 后的共同存活集合。不能继续复用旧 candidates/unmatched
而不重建存活集合，也不能把一端已经删除的节点产生的零度数当成另一端 DAG 错误。

沿用 F20 G3 的实验有效性要求：匹配对数非零、分类计数闭合、显式 split map 无未解析项、生成节点收缩无残余 SCC，
精确率/召回率目标均 ≥99%，未解释边 ≤0.5%。工具或映射失败时先修对照器，不据此评价 DCE 能力。

### 7.4 “删除能力更优”的判定

op 级 DCE 理论上可以删到 GSIM 整 Node 删除无法表达的细粒度，但这只是待验证假设；现有声明锚点和状态族保护
也可能使 GrhSIM 更保守。最终按以下顺序判定：

1. 可观察边界、声明锚点、效果和生成模型行为回归全部通过；
2. 共同起始 K 的删除矩阵及分类闭合，无未解释的活逻辑误删；
3. 主要报告“仅 GrhSIM 删除 / 仅 GSIM 删除”的数量和原因，而非只比较原始总 Node；
4. 若仅 GrhSIM 删除显著更多、共同存活 DAG 不劣化且差异均有解释，才可得出本轮 Node 级删除能力更强；
5. 若结果相反或各有胜负，按模块/类别如实报告，不把 op 级更细直接等同于最终 Node 数必然更少。

## 8. 交付、证据与退出条件

所有临时图、日志、性能数据和大型对照文件放在 `ptmp/firrtl-ingest/F21/`，不提交生成 FIRRTL、SV、模型或大 JSON。
建议新增：

- `make test_f21_dce`：汇总独立 DCE、SemanticTree、FIRRTL 顺序和生成模型检查；
- `make test_f21_dce_asan`：在 ASAN 下覆盖新 DCE、SemanticTree 回收和 JSON 往返；
- `make benchmark_f21_dce`：冻结输入上的 F21 DCE 与 GSIM 性能及 F21 子阶段统计；
- `make f21_dce_compare`：生成删除矩阵、Node DAG、差异归因和汇总 JSON；
- 如需重新采集 GSIM，新增对应 Make 包装，不直接拼接底层构建/运行命令。

F21 完成必须同时满足：

- [x] 复用现有 op 级 DCE，无 GSIM Node 级分析移植，无 SemanticId 保活根；
- [x] SemanticTree 空来源子树被批量回收，存活路径、来源列表、实例结构、JSON 往返和幂等全部正确；
- [x] FIRRTL/mixed full 与 bringup 均在 comb-loop-elim 后独立执行一次 DCE，后续 simplify 配置不变，纯 SV 序列未被隐式修改；
- [x] 声明锚点、端口、效果、外部边界、状态族及实际生成模型行为无回归，完整测试相对既有失败基线无新增失败；
- [x] 完整 SimTop 性能数据齐全并达到 §6.3 门槛；若未达到，F21 保持“性能未达标”，不记全部完成；
- [x] 给出共同起始 Node 的双向删除矩阵、最终 Node 分类数量、共同存活 Node DAG 和未解释差异；
- [x] 更新 DCE、FIRRTL 架构/流程文档及 F21 实施结果，所有命令均通过项目 Makefile 执行。

本计划审查通过后才开始实现；本文不预先宣称 GrhSIM 一定删除更多 Node，也不预先宣称性能已经达到 GSIM 水平。


## 9. 实施结果（2026-11-07，持续更新）

### 9.1 实现落点

- `SemanticTree::buildPruned` 非破坏式构造压缩树与 `oldToNew`；`Graph::pruneSemanticTree`
  收集存活 op/value 的直接来源，保留祖先及实例 Module/Declaration 关联，并一次性提交树、
  SemanticId 池和长列表哈希。无删除时不触碰 Graph revision。
- 现有 DCE 在 op/value 删除后调用上述回收。活跃性、状态族、声明锚点和旧 `DeadRootBatch`
  完全复用；SemanticId 不参与保活。仅电路变化唤醒 `redundant-elim`，纯来源变化不唤醒。
- op operands/results 在分析期间借用只读 span，首次删除前才结束借用；消除了逐 op vector 拷贝，
  活跃性与删除集合不变。SemanticId 重映射在原整数池内完成，避免额外整池副本。
- FIRRTL/mixed full 与 bringup 通过 `firrtl_grh_pipeline` 在 `comb-loop-elim` 后插入一次独立 DCE；
  纯 SV 保持原 pipeline。`--f21-dce` 保存 post-elim 与 post-dce，`benchmark_f21_dce`
  则直接从相同 post-elim 重复加载，不比较旧 DCE。
- GSIM 对照复用 `removeDeadNodes()`，只补充 JSON 的 `id/status` 导出；节点算法未改变。
  当前源码需单独构建，仓库内已有 GMP 头文件和静态库用于隔离构建。

### 9.2 全量删除规模

三轮最终实现的删除集合、SemanticTree 统计和 2,414 个声明寄存器符号检查完全一致：

| 指标 | post-elim | post-dce | 删除 | 删除比例 |
| --- | ---: | ---: | ---: | ---: |
| GRH operation | 34,307,850 | 26,417,446 | 7,890,404 | 23.00% |
| GRH value | 33,693,874 | 25,850,702 | 7,843,172 | 23.28% |
| SemanticTree 节点 | 13,221,574 | 11,295,667 | 1,925,907 | 14.57% |
| 直接 SemanticId（存活行） | 43,584,124 | 34,067,571 | 9,516,553 | 21.84% |
| SemanticTree 名称字节 | 158,044,678 | 138,406,108 | 19,638,570 | 12.43% |
| v4 JSON 字节 | 10,744,198,148 | 8,391,980,862 | 2,352,217,286 | 21.89% |

`post-dce` 中仍有 6,989,127 个 value 来源行和 26,417,446 个 operation 来源行；
按 kind 检查所有 operation 的 SemanticId 缺失均为 0。未做 Graph compaction 的内存池可能仍含墓碑行，
JSON roundtrip 后只保留存活关联，不能把底层 pool 数量误当成存活来源数量。

### 9.3 三轮性能

正式输入为同一份 10,744,198,148 字节 post-elim checkpoint，SHA-256
`bf19d62ab53682e40a774e76d676e16eddfd631217eae3d71359e7cc620c71c6`。
两端均测 pass 本体，JSON load/store、GSIM dump 和其他前序阶段不计入。

| 轮次 | F21 DCE + SemanticTree 回收 | GSIM 首次 RemoveDeadNodes |
| --- | ---: | ---: |
| 1 | 16.348 s | 35.805 s |
| 2 | 17.090 s | 36.252 s |
| 3 | 16.354 s | 33.802 s |
| **中位数** | **16.354 s** | **35.805 s** |

F21 中位数为 GSIM 的 **0.457×**，达到 §6.3 的 1.0× 门槛。
F21 analysis、op/value 删除和 SemanticTree 回收的中位数分别为 **12.996 / 2.546 / 0.484 s**。
第三轮 GSIM 使用无 dump 运行；前两轮 dump 不计入其 `RemoveDeadNodes` 内部计时。

RSS 增量三轮为 988,616 / 1,251,412 / 988,616 KiB，中位数 **988,616 KiB（约 966 MiB）**。
DCE 前当前 RSS 中位数约 22,611,072 KiB，增量约 **4.37%**，同时满足额外峰值 ≤2 GiB 和 ≤5% 的门槛。
这里比较的是 pass 前后当前 RSS，不是包含 JSON 加载与其他进程的整进程 max RSS。

### 9.4 已通过的验证

- `test_transform_dead_code_elim`、`test_grh_semantic_tree`、`test_f19_semantic_json`、
  `test_transform_simplify` 和 `test_f21_dce_tools` 全部通过。
- ASAN 下 `transform-dead-code-elim`、`grh-semantic-tree`、`store-semantic-tree-json`、
  `firrtl-semantic-tree` **4/4** 通过；借用 span 后复验仍通过。
- 完整 CTest 修改前后均为 **76/84**，失败名单不变，无 F21 新增失败。
  `grhsim-sink-schedule-tests` 对应工作树已有 sink 修改，其余为旧 provenance/node 表示问题。
- FIRRTL workflow 为 **67/73**，仍只有旧 node 属性断言 2 项和中文 locale 断言 4 项失败；
  shared flow 的旧 policy/CSE 元数据失败单独记录，不冒充 F21 通过项。
- `test_transform_comb_loop_elim`、`test_firrtl_state`、`test_firrtl_memory` 实际执行回归通过。
- 原始 FIRRTL 的连续生产入口 `f21_grh_dce` 已跑通：454 个 false loop 全部修复，
  独立 DCE 为 19.066 s（与其他工作并行，非正式计时样本）；post-dce 统计与 checkpoint 路线一致。
- 全量 post-dce 的 Module 路径重复数、声明寄存器符号不匹配数均为 0（检查 2,414 个寄存器）；
  8,391,980,862 字节 JSON 的 store→load→store 字节数和 SHA-256 完全一致。


## 10. Node 删除能力与 DAG 对照（2026-11-07）

### 10.1 对照集合与删除矩阵

候选通过 `Init candidates → GRH unmatched → split-array coarsening` 生成，最终与 F20 同为
**7,242,474** 个名称。另有 196 个名称未进入本轮共同可解析集合，作为 split-array/聚合名称映射差异单列，
不计入任一端删除收益。矩阵使用其余 **7,242,278 个 K**，每项互斥且合计闭合：

| 分类 | K 数 | 占共同集合 |
| --- | ---: | ---: |
| 双方均删除 | 1,386,911 | 19.1502% |
| 仅 GrhSIM 删除 | **681** | **0.0094%** |
| 仅 GSIM 删除 | **1,149,622** | **15.8738%** |
| 双方均保留 | 4,705,064 | 64.9667% |

GrhSIM 删除 1,387,592 个 K，GSIM 删除 2,536,533 个 K。
**本实验不支持“op 级 DCE 必然带来更优的 Node 级删除”这一假设；GSIM 的整 Node 删除明显更多。**
op 级分析在编译期更细且本轮更快，但最终 Node 数还受声明锚点、状态/数组表示和两端的活跃性模型影响，
不能用 op 粒度替代最终结构评价。

仅 GSIM 删除的主要模块为 Rob（96,055）、RAB（48,668）、StoreQueue（46,983）、
`ctrlBlock$dispatch`（21,981）及多个 issue queue；仅 GrhSIM 删除仅 681 个 K，主要是
`l_simMMIO$axi42tl`、`l_simMMIO$axi4xbar` 等局部组合形式。

对仅 GSIM 删除的 K 做直接 op/value 关联检查：

- **289,042** 个 K 命中声明符号，占该集合约 25.14%，属于需要单独解释的保活类别；
- 记录 **67,184** 次 `kRegisterReadArrayPort` 直接关联（同一 K 可命中多条 op），体现 GRH 的动态数组/状态读表示；
- 直接关联均为单来源，没有发现多来源共享 op/value 是这批差异的主因；
- 其余大量关联是 `kAssign`、常量、concat、mux、slice 和条件逻辑，反映两端的别名与中间表达式表示差异。
  这些直接关联不是新的根可达性证明，不能据此把全部保留项都称为正确删除或漏删。

证据：`compare-final4/deletion-report.json`、`retained-associations.json`、
`candidates-final3/{gsim-probe.json,grh-probe.json,split-map-stats.json}`。


### 10.2 共同存活 Node DAG

在双方均保留的 4,705,064 个 K 上取诱导子图，沿用 F20 的 guard/WHEN_COND 收缩、显式 split map、
prev/next 且无 dep 边口径：

| 指标 | GrhSIM | GSIM |
| --- | ---: | ---: |
| 投影边 | 6,882,142 | 6,879,616 |
| 共同边 | **6,877,133** | **6,877,133** |
| 各自独有边 | 5,009 | 2,483 |
| 精确率 / 召回率 | **99.9272%** | **99.9639%** |

两端入度 p50/p90/p99 均为 **1/2/3**，出度均为 **1/1/8**；最大入度均为 12,288，
最大出度均为 11,169。4,082 个 K 存在度数差异。生成节点收缩后的残余 SCC 为 0，
显式 split map 未解析新增节点为 0，名称歧义涉及 32 条边并按既定规则排除。

独有边占各自边集合约 0.073% 和 0.036%，低于 §7.3 的 0.5% 上限；这些边差异及 §10.1 的
196 个名称映射差异仍是后续分类对象，不能写成图完全等价。DAG 对齐良好只说明共同存活结构可比，
不推翻 §10.1 的删除能力结论，也不替代 F10 的整机动态等价验证。

## 11. 验收结论（2026-11-07）

F21 的实现、性能实验和结构对照已完成：

- 复用了现有 op 级 DCE，没有移植 GSIM 的 Node 级活跃性分析；SemanticId 不是保活根。
- SemanticTree 空来源子树可批量回收，存活路径、实例结构、列表顺序/重复项和 JSON 往返正确。
- FIRRTL/mixed full 与 bringup 均在 comb-loop-elim 后独立执行一次 DCE，后续 simplify 配置不变，
  纯 SV 序列未改变；原始 FIRRTL 连续入口已验证。
- 三轮 F21 DCE 中位数 16.354 s，优于 GSIM 的 35.805 s；内存门槛同时满足。
- 最终删除矩阵证明 **GSIM 的 Node 删除更多，而非 GrhSIM 更优**；共同存活 DAG 的高精确率/召回率
  为后续 pass 对齐提供了可靠基线。

剩余边界：F10 的整机 C++/emu 和动态等价不在 F21 范围内；196 个名称映射差异及少量独有边继续分类，
但均不构成本轮门槛失败。`test_wolvrix` 与 workflow 的既有失败按基线保留，没有包装为全绿。

## 12. “为什么 GSIM 删除更多”归因（2026-11-07）

本节只分析 §10 的 F21 DCE 与 GSIM 首次 `RemoveDeadNodes`，不引入旧 DCE 基线。
本节描述的是开启声明保护时的历史生产策略；最新默认策略已由后续审查修改，见 §13。

### 12.1 主因是保活边界不同，而不是 op 工作列表更弱

从同一 post-elim checkpoint 额外执行一次诊断 DCE，唯一变化是 `keep_declared_symbols=False`。
该运行最初只用于归因；当时的生产配置为 True，后续 §13 才把 False 改为拆分与独立 DCE 的默认值。

| 共同起始 K 的分类 | F21 生产配置 | 诊断：关闭声明锚点 |
| --- | ---: | ---: |
| 双方删除 | 1,386,911 | 2,364,563 |
| 仅 GrhSIM 删除 | 681 | 1,339 |
| 仅 GSIM 删除 | 1,149,622 | 171,970 |
| 双方保留 | 4,705,064 | 4,704,406 |

关闭声明锚点后，仅 GSIM 删除项减少 **977,652（85.0412%）**，剩余 171,970（14.9588%）。
同时额外删除 4,199,472 个 op 和 3,744,198 个 SemanticTree 节点。这证明声明锚点及其反向逻辑锥是最大来源；
§10 的 289,042 个直接声明符号关联只是其中一部分，不能用直接关联数代替完整逻辑锥影响。

边界差异有明确源码依据：

- GRH 把 FIRRTL `DontTouchAnnotation` 的目标及其聚合字段注册为声明锚点，见
  `wolvrix/lib/ingest/firrtl/annotations.cpp:149-199`；DCE 从声明 value/state 根开始传播，见
  `wolvrix/lib/transform/dead_code_elim.cpp:574-629`。
- GSIM 的 annotation 语法规则解析并丢弃 JSON，见 `reference/gsim/parser/syntax.y:353-355`；首次 DCE 的根只有
  output、special node 和外部模块边界，见 `reference/gsim/src/deadNodes.cpp:55-83`，没有 DontTouch 根。

具体反例是 `difftest_timer`：FIRRTL 在 `ptmp/xs/rtl/rtl/SimTop.fir:820587` 对其设置 DontTouch，
在 `ptmp/xs/rtl/rtl/SimTop.fir:9375084-9375093` 定义计数器及写回逻辑。GRH 生产配置保留它们，
GSIM 首次 DCE 删除整个逻辑锥；关闭声明锚点的诊断 GRH 运行也删除它们。因此，这部分“GSIM 删除能力更强”
实际是两端观察边界合约不同，不能作为关闭生产声明保护的理由。

### 12.2 两端数组拆分的范围与最终保留形态不同

先澄清 F21 的实际阶段：GRH 已经在独立 DCE 前执行 `comb-loop-elim`，因此不能笼统写成“GSIM 拆数组、
GRH 没拆数组”。`comb-loop-elim` 确实执行数组 fragmentation，但它是 loop-local 消环变换：
先重定向 loop 入口，仍不能消环时才拆分 loop values；需要 full view 的下游还会重新拼接完整 value。
它不规范化 loop 之外的普通常量数组读，见 `wolvrix/docs/transform/comb-loop-elim.md:46-84`、
`wolvrix/docs/transform/comb-loop-elim.md:86-117`、`wolvrix/lib/transform/comb_loop_elim.cpp:4510-4554`。

GSIM 则在首次 `RemoveDeadNodes` 前执行 `splitArray` / `splitOptionalArray`，把可拆数组的引用和写回树分配到独立成员，
见 `reference/gsim/src/splitArray.cpp:383-453`、`reference/gsim/src/splitArray.cpp:560-650`。
所以准确差异是 **GSIM 的全局数组成员化与 GRH 的 loop-local 消环及 full-view 保留形态不同**，不是有没有调用拆数组 pass。
§10 的比较器已把 GSIM 存活成员映射回原父 K，多出来的删除不是“父数组被拆分”的计数假象。

RAB 对照进一步确认了它没有被 `comb-loop-elim` 有效拆开：

- `commitCandidates.info.pdest` 在 flatten 和 post-elim 中都是 value 9421555、宽 72、`shape:[9]`，见
  `ptmp/firrtl-ingest/F20/remove-memory-bounds-bare/flatten.json:23313129` 和同目录 `post-elim.json:23313129`。
- 其 packed 写链在两个 checkpoint 中保持相同 op ID 和依赖，包括第 8 路写入的 op 9020083 `kConcat` 及
  op 9077203 `kAssign`，见 flatten 的 `55436154-55436402`、post-elim 的 `56605305-56605553`。
- 该样本的来源 SemanticId 2749277、2749633、2756703、2772200 及声明节点 2749629、2756699 均未出现在
  `post-elim-fragments.json` 的 `sourceSemanticIds` 中。数字 op/SemanticId 只在这两个 F20 checkpoint 内对照；
  DCE 后 store 会重排 ID，不能用 no-declared 图中的 ID 回查这张 fragment map。

RAB 的源级行为是：`commitCandidates` 在 `ptmp/xs/rtl/rtl/SimTop.fir:1857813-1857822` 写入 9 个元素，
后续提交逻辑在 `ptmp/xs/rtl/rtl/SimTop.fir:1873140-1873327` 只读第 0–7 个元素。
GSIM 的第 8 个 `commitCandidates__DOT__info__DOT__ldest_8` 没有后继，因而可连同其输入锥删除。
GRH 的静态数组写通过 `slice + concat` 维护完整 packed accumulator，读则对整个 value 生成 `kSliceArray`，
见 `wolvrix/lib/ingest/firrtl/lower.cpp:357-377`、`wolvrix/lib/ingest/firrtl/lower.cpp:601-620`。
一个读 op 活跃时，整个 accumulator 都是其 operand，因此其他存活元素会把第 8 个元素一起保活；即使分析是 op 级，
也不能从现有可达性标记中推出“只删除第 8 个元素”。
因此，**op 级更细不等于在 post-elim 的数组 value 表示下一定具有更细的 Node 删除结果。**

no-declared 图中的完整根路径也定位到了具体聚合点：第 8 元素的 `_WIRE_24.info.pdest` 经该图 op 4456387 的
`kConcat` 进入完整 `commitCandidates.info.pdest`，op 4499368 保持该 accumulator，随后 op 4419727 的
`kSliceArray` 为第 7 路 `_io_commits_info_7_T_3.info.pdest` 读取它，见
`ptmp/firrtl-ingest/F21/no-declared-compare/root-trace-rab-full.json:11315-11399`。
这是“第 7 路活跃导致第 8 路输入锥也被保留”的直接数据流证据。

对无声明锚点图中的五个代表样本做端口/效果根与状态族重放，RAB、DTLB、dispatch、issue queue 和 `cpu$clock`
都能到达 `kSystemTask`，不是无根节点或漏遍历。RAB 路径最终进入 RAT 的 assertion；这进一步说明差异在效果根之前的
依赖粒度。五样本路径报告见 `ptmp/firrtl-ingest/F21/no-declared-compare/root-traces.json`（长路径带截断标记），
RAB 的完整路径另存 `root-trace-rab-full.json`；只读诊断器为 `scripts/trace_f21_retained.py`。
F21 把 DCE 放在 `comb-loop-elim` 后的位置没有问题；需要另外处理的是 post-elim 仍存在的聚合依赖。

### 12.3 时钟与状态族是另一组表示差异，但不能夸大其数量

GRH 把时钟作为写口和效果操作的真实 operand，见 `wolvrix/lib/ingest/firrtl/lower.cpp:507-520`；
活跃 op 会沿 operands 保活时钟别名及驱动锥。GSIM 把时钟保存在 `Node::clock` 元数据中，
普通 `Node::updateConnect` 的 prev/next 来自 assign tree，并不覆盖所有时钟使用；首次 DCE 前还会执行
`clockOptimize`，见 `reference/gsim/src/Node.cpp:7-44`、`reference/gsim/src/clockOptimize.cpp:170-260`。
因此，即使根集合一致，时钟别名链的删除结果也可以不同。本次 `cpu$clock` 的 GRH 根路径确实到达 `kSystemTask`。

GRH 还会在某个状态读口活跃时保活该状态的声明及全部写口，见
`wolvrix/lib/transform/dead_code_elim.cpp:548-571`、`wolvrix/lib/transform/dead_code_elim.cpp:677-691`；
GSIM 对 REG_SRC、memory reader/writer 使用自己的配对传播规则，见 `reference/gsim/src/deadNodes.cpp:68-82`。
这些规则不能仅按 Node 数量判断谁“更正确”。

关闭声明锚点后的 171,970 个剩余项中，记录到 14,477 次 `kRegisterReadArrayPort` 直接关联（同一 K 可命中多条 op），
另有 5,136 个唯一 K 的名称含 clock/Clock。这些只是有重叠的关联统计，不是互斥根因数量。
RAB 等五个样本已验证根路径，但尚未把全部剩余项逐一归因；数组拆分范围和最终保留形态是已确认的重要结构因素，
不能把全部剩余项都宣称为数组或时钟问题。

### 12.4 结论与后续方向

1. 当时的最大因素是声明/DontTouch 保活边界，解释 85.0412% 的仅 GSIM 删除差异。
2. 其余差异不能归因于 SemanticTree 回收或 op 工作列表漏删。两端数组拆分的范围、full-view 保留形态以及时钟/状态表示，
   使同一可观察根之前的可删除集合不同。
3. 当时建议新增全局静态 scalarization，而不是把 loop-local `comb-loop-elim` 当成 GSIM `splitArray` 的等价物。
   后续审查明确要求实现该 pass，并把拆分与 DCE 的默认声明保护关闭；实现见 §13。DCE 不前移，也不改成 GSIM Node 算法。
4. 本节只解释结构差异，没有新增整机动态等价证据；不能把 GSIM 删除更多直接称为语义更优。

诊断入口为 `f21_dce_no_declared`、`f21_dce_matrix`、`f21_trace_retained`；`test_f21_dce_tools` 的
3 个小图测试覆盖删除矩阵、split 成员 ID 和状态族根路径。证据位于
`ptmp/firrtl-ingest/F21/no-declared{,-compare}/`。§9–§11 是开启声明保护时的历史正式结果；
当前默认配置及最新结果见 §13。

## 13. split-static-array 与默认不保护声明（2026-11-07）

### 13.1 最新决策与边界

后续审查确认：缺少的是对标 GSIM `splitOptionalArray` 的全局静态数组成员化，而不是再调整 DCE 的位置。
因此新增独立 `split-static-array`，当前 FIRRTL/mixed full 与 bringup 均为：

```text
comb-loop-elim → split-static-array → dead-code-elim → 原后续阶段
```

- 拆分与独立 DCE 默认 `keep_declared_symbols=False`，不把声明/DontTouch 锚点作为额外保活根，与 GSIM 对齐；
  声明数组也允许拆分。显式 True 仍恢复 DCE 的声明保护。
- `PassContext` 和 `PassManagerOptions` 使用可选覆盖值；未覆盖时按 pass 选择默认值。
  只有 `split-static-array` 和 `dead-code-elim` 默认 False，其他 pass 保持原默认行为，避免扩大回归。
- Python `Session.run_pass` 与 native 入口采用相同的按 pass 默认规则。生产入口显式记录各阶段配置；
  flatten 前八阶段及其声明策略不变。
- 端口、状态族、实例/黑盒、系统任务、DPI 和 XMR 等边界的处理不因声明默认值改变；独立 DCE 仍为 op/value 分析，
  不混入 simplify，也不引入 GSIM Node/ENode 活跃性算法。

### 13.2 实现

实现位于 `wolvrix/lib/transform/split_static_array.cpp`，公开头文件为
`wolvrix/include/transform/split_static_array.hpp`，factory 名称为 `split-static-array`。采用按需成员化而非预先复制完整数组：

1. 检查 `kSliceArray` 的全部索引，接受可解析且在界内的常量索引，按行主序计算静态位段；
2. 穿过等宽 `kAssign` 和 `kSliceStatic`，直接选择 `kArrayCreate` 元素，选择完全落在单个 `kConcat` 操作数内的位段；
3. 对 shaped `kMux` 分别选择两个分支，再生成所选的标量/子数组 MUX；相同选择通过缓存复用；
4. 原读的结果 value 不变，读取 op 改为 `kAssign`。只有需要新视图时才创建 `kAssign`、`kSliceStatic` 或 `kMux`，
   未读元素不预先物化；原聚合链由后续独立 DCE 回收；
5. 动态/越界索引、端口数组、状态读口、跨界 concat 和不满足 node 共享约束的情况保守保留。
   MUX 分支失败按逆序回滚临时 op/value；首次实际创建时批量预留列容量，避免大图反复扩容。

新 op 合并原读和直接生产者的 `originModules` 与 FIRRTL node 属性。SemanticId 不再逐层构造并集：
优先沿用原读，原读没有来源时才回退到直接生产者；新 value 采用同一规则。无引用语义分支仍由独立 DCE 统一回收。
图遍历使用 `Pass::graphs()`，支持 graph-kernel 并行选择。

### 13.3 正确性证据

新增 `wolvrix/tests/transform/test_split_static_array_pass.cpp`，覆盖：

- 声明数组默认被删除、显式 True 时聚合及驱动锥保留；
- concat/assign、二维 arrayCreate 行主序选择、shaped MUX、动态读拒绝和 factory 参数检查；
- 未读元素经独立 DCE 删除，SemanticTree 空分支回收，图并行和 `grh.verify`；
- MUX 条件在递归创建前复制，避免 operand span 因图扩容悬垂。

当前验证结果：`test_transform_split_static_array` 通过；ASAN 下 split、DCE、SemanticTree 和 JSON 共 **5/5** 通过；
`test_f21_dce_tools` **3/3** 通过。全量 CTest 为 **77/85**，新增 split 测试通过，其余 8 项失败名单与原基线一致。
FIRRTL workflow 为 **67/73**，仍是旧 node 属性断言 2 项及中文 locale 断言 4 项。

原始 FIRRTL 连续入口 `make f21_grh_dce F21_WORK=ptmp/firrtl-ingest/F21/continuous-split` 已完整跑通，
`success=true`，454 个 false loop 全部修复；split 为 20.254 s、独立 DCE 为 48.417 s。
其 post-elim SHA-256 与冻结图输入一致，最终 post-DCE SHA-256 也与 v3 完全一致；
pipeline 记录 split/DCE 均为 `keep_declared_symbols=False`，其余阶段保持原配置。
证据为 `ptmp/firrtl-ingest/F21/continuous-split/{timing.json,prefix-identity.json}`。

这些结果不包含新的整机 C++/emu 动态等价证明，不能把 Node 数或 DAG 指标直接当作行为等价。

### 13.4 SimTop 最终规模、耗时与内存

最终当前代码从同一 post-elim（SHA-256 `bf19d62ab53682e40a774e76d676e16eddfd631217eae3d71359e7cc620c71c6`）
执行 split 和独立 DCE，均使用 `keep_declared_symbols=False`。证据为
`ptmp/firrtl-ingest/F21/split-static-array-v3/summary.json`。

| 指标 | post-elim | post-split | post-DCE |
| --- | ---: | ---: | ---: |
| operation_rows | 34,307,850 | 34,393,897 | 19,250,843 |
| `semantic_stats.value_rows` | 8,613,880 | 8,650,426 | 5,809,010 |
| SemanticTree nodes | 13,221,574 | 13,221,574 | 7,272,123 |
| SemanticId pool | 43,584,124 | 43,710,779 | 43,710,779 |

split 新建 86,047 op；最终相对 post-elim 净删除 **15,057,007 op** 和 **5,949,451 SemanticTree 节点**。
`value_rows` 使用 `semantic_stats` 口径，不与比较器读取的原始 `vals_records` 混用。

同阶段单轮墙钟如下；GSIM 数字来自同一份 SimTop 的 `gsim-run10`，不是把整轮解析/dump 时间计入优化：

| 实现 | 数组拆分 | 独立 DCE | 合计 |
| --- | ---: | ---: | ---: |
| GrhSIM split-static-array + dead-code-elim | 26.542 s | 49.630 s | 76.172 s |
| GSIM splitArray + 首次 RemoveDeadNodes | 52.338 s | 34.994 s | 87.332 s |

GrhSIM 合计少 **11.160 s（约 12.8%）**，但独立 DCE 本身比 GSIM 慢 **14.636 s**；
收益来自更快的静态拆分，不能表述为 DCE 单项全面更快。

最终 RSS 增量为 **8,386,996 KiB（约 8.0 GiB）**，峰值 **30,995,904 KiB（约 29.6 GiB）**。
首次实际创建时预留 131,072 个 value/op 降低了扩容成本，但内存仍然偏高，不能把本实现称为低内存开销；
后续若要降低峰值，需要继续处理 frozen graph 新增实体的整列重分配。

### 13.5 共同 K 删除矩阵与 RAB 闭合

共同起始 K 为 7,242,278。最终矩阵为：

| 分类 | 数量 |
| --- | ---: |
| 双方删除 | 2,423,115 |
| 仅 GrhSIM 删除 | 31,166 |
| 仅 GSIM 删除 | 113,418 |
| 双方保留 | 4,674,579 |

GSIM 净多删 **82,252** 个 K，删除能力已接近但未完全对齐。
最终 post-DCE 在 v2/v3 的 SHA-256 均为 `d3823b0cb76256364b75af137c905557f41bd864082327d5287c5c928fbb9936`，
证明容量优化前后最终图一致。

§12 的 RAB 样本也已闭合：`_commitCandidates_WIRE_24__DOT__info__DOT__pdest` 在最终 GrhSIM 与 GSIM 图中均不存活；
`commitCandidates__DOT__info__DOT__pdest` 父 K 仍存活，是因为其他元素确实被使用。静态拆分已经切断第 7 路读取对第 8 路输入锥的聚合保活。

### 13.6 共同存活 Node DAG

对双方保留的 4,674,579 个共同 K 做依赖投影和 guard 收缩，结果为：

| 指标 | 数量/比例 |
| --- | ---: |
| 共同边 | 6,177,389 |
| 仅 GrhSIM 边 | 669,079 |
| 仅 GSIM 边 | 445,749 |
| 精确率 | 90.2274% |
| 召回率 | 93.2698% |

两端 guard 收缩产生的 SCC 均为 0；GrhSIM 的 guard path collision、未解析 operand 和缺失 op SemanticId 均为 0。
`max_operation_groups=1`，没有由多来源并集造成的单 op 多目标组。

DAG 差异明显大于共同 K 删除差异。成员化后的直接元素依赖、SemanticTree 回收及来源映射差异都会改变投影边，
这些差异尚未逐边闭合，不能仅凭删除数量或较高召回率宣称结构/语义完全对齐。最终证据为
`ptmp/firrtl-ingest/F21/split-static-array-v2/compare/{deletion-report.json,dag/dag-report.json}`；
另有 196 个既有名称映射差异继续保留为未闭合项。

## 14. 状态数组扩展（2026-11-07）

### 14.1 拆分前的状态元素分布

只读诊断工具 `scripts/analyze_f21_state_elements.py` 按 GrhSIM 数组寄存器符号、GSIM split-map `parentName/memberId`
及 shape 做显式映射。输入为 §13 的 GrhSIM post-DCE 和 GSIM 首次 RemoveDeadNodes；4,832 个可映射状态族全部闭合，
无成员数、父类型或索引错误。报告为 `ptmp/firrtl-ingest/F21/split-static-array-v2/compare/state-element-report.json`。

| 分类 | 状态族 | 元素总数 | GSIM 存活 | 表示差异 |
| --- | ---: | ---: | ---: | ---: |
| 全部 | 4,832 | 58,255 | 43,968 | 14,287 |
| 两端全部保留 | 4,231 | 40,678 | 40,678 | 0 |
| GSIM 部分保留 | 574 | 17,469 | 3,290 | 14,179 |
| GSIM 整组删除 | 27 | 108 | 0 | 108 |

GrhSIM 聚合声明对应多保留 14,287 个元素（24.52%）；位宽加权差异为 21,487 bit。407 个存活率不足 25%
的状态族贡献 12,780 个差异元素，说明主要收益集中在少量低利用率数组。该数字是状态成员的表示差异上限，
不是可安全删除的普通 Node 数，也不包含其输入锥。

读写形态决定了扩展范围：

| 读取形态 | 状态族 | 表示差异 | 占比 |
| --- | ---: | ---: | ---: |
| 含 whole read | 1,963 | 13,448 | 94.13% |
| 仅静态元素读 | 2,853 | 839 | 5.87% |
| 静态子数组读 | 16 | 0 | 0% |

因此只支持 `kRegisterReadArrayPort` 不能解决主差异，whole read/write 必须纳入第一版。纯静态读取族中有
2,823/2,853 个满足“GSIM 存活元素数等于 GrhSIM 静态读取元素集合”。代表 IssueQueue `fuType` 同时具有
whole read、whole write 和静态读；GrhSIM 保留全部 36 个元素，而两端实际需要的集合均为 `{0,1,5,6,9}`。

### 14.2 实现机制

`split-static-array` 在原有组合数组拆分前增加整状态族改写，DCE 仍保持独立 op/value 分析：

1. 按 `regSymbol` 收集声明和全部读写；至少一个读口才考虑拆分。动态、越界、部分维度索引或未知状态引用使整族跳过。
2. 为每个行主序元素创建标量寄存器。静态数组读写直接改接成员读写口，去掉索引并保留 enable、事件和 `writerOrder`。
3. whole read 用成员读逐层重建多维 `kArrayCreate`；扁平或其他 tiling result 通过 `kAssign` 保留原 value。
   沿等宽别名找到的相关 `kSliceStatic` 也进入现有成员选择重写。
4. whole write 复用组合选择逻辑拆分 next-value/mask，递归上限为 256；fill 转成成员普通写。
   无法穿过生产者时保留普通静态切片，不为了删除率改变状态语义。
5. `Constant` 初始化逐成员切片，完整非随机 `Fill` 转成成员 `Constant`；Readmem、随机和复杂多段初始化跳过。
6. 所有端口改接后删除原声明。默认不保护声明时把声明标记转移到成员；显式 `keep_declared_symbols=True` 时
   声明状态族保守跳过，组合数组的原有行为不变。
7. 成员名冲突按 GSIM 方式处理：非端口 value 或寄存器声明先加 `_0` 后缀，并同步更新所有 `regSymbol`、
   声明标记和受影响状态族的候选成员名；端口、其他 op 类型或后缀仍冲突时跳过当前状态族。

成员声明和端口复制原操作属性、来源位置与 SemanticId，成员 value 沿用原读结果来源，后续仍可映射回父 K。
空来源分支继续由独立 DCE 回收。具体规则同步记录在 `wolvrix/docs/transform/split-static-array.md`。

### 14.3 小图与内存安全验证

`wolvrix/tests/transform/test_split_static_array_pass.cpp` 新增 whole read/write、自保持、扁平 whole-read 视图、
多维数组、初始化切片、masked/whole 写口、fill、未读成员 DCE、动态索引拒绝、声明保护、寄存器/value 符号冲突及
超过 64 层的 next-value 选择链用例。符号冲突用例同时检查读写口引用更新。原组合数组用例保持通过。

- `test_transform_split_static_array` 通过；
- `test_transform_dead_code_elim`、`test_transform_simplify`、`test_transform_comb_loop_elim`、
  `test_firrtl_state`、`test_firrtl_memory` 和 `test_f21_dce_tools`（4/4）通过；
- `test_f21_dce_asan` 为 5/5，通过状态拆分新增用例和既有 SemanticTree/DCE 检查；
- 全量 `test_wolvrix` 为 77/85，失败名单与 §13 的既有基线完全相同，没有新增失败；
- `test_xs_firrtl_workflow` 为 67/73，仍是旧 node 属性断言 2 项及中文 locale/退出码断言 4 项。

### 14.4 v2 删除矩阵与代表样本闭合

首轮 `state-split-v1` 证实状态声明和端口可以改写，但代表 `fuType` 的 36 个成员仍全部保留。根路径显示，
whole write 的 next-value 退回到整值 `kSliceStatic`，原输入锥仍被保活。选择器只有深度或循环重入两类正常失败路径；
将递归上限从 64 提高到 256 后，代表链不再回退，并新增 80 层 `kAssign` 回归用例。该结果说明成员选择必须覆盖
实际 FIRRTL 展开深度，不能用小图的浅链推断上限。

`state-split-v2` 使用相同 post-elim 输入（SHA-256 `bf19d62ab53682e40a774e76d676e16eddfd631217eae3d71359e7cc620c71c6`）。
最终矩阵见 `ptmp/firrtl-ingest/F21/state-split-v2/compare/deletion-report.json`：

| 分类 | §13 组合数组拆分 | §14.4 状态数组扩展 | 变化 |
| --- | ---: | ---: | ---: |
| 双方删除 | 2,423,115 | 2,497,556 | +74,441 |
| 仅 GrhSIM 删除 | 31,166 | 42,764 | +11,598 |
| 仅 GSIM 删除 | 113,418 | 38,977 | -74,441 |
| 双方保留 | 4,674,579 | 4,662,981 | -11,598 |

仅 GSIM 删除项减少 65.63%；按共同 K 计算，GrhSIM 从净少删 82,252 变为净多删 3,787。该结果只表示删除矩阵，
不构成两端语义等价证明。

代表状态已按精确成员索引闭合：

- ALU0 `fuType` 从 36 个声明降为 `{0,1,5,6,9}`，与 GSIM 完全一致；
- ALU1 `fuType` 从 36 个声明降为 `{0,1,6,8}`，与 GSIM 完全一致；
- 原 `_compEnqVec_0_T_1000` 已退出“仅 GSIM 删除”集合。

post-DCE 规模为 18,195,415 op 和 7,150,627 个 SemanticTree 节点，较 §13 分别再减少 1,055,428 和 121,496。
`state-split-v2/summary.json` 中的时间受并行回归影响，仅作中间记录，最终性能以独立复测为准。

完整初始集合的 post-split 状态分布报告为 `state-element-post-report.json`：11,015 个可映射状态族中 10,716 个
成员集合精确一致（97.29%），GrhSIM 保留 43,788 个元素、GSIM 保留 43,968 个，净差 180。不同集合 299 个，
GrhSIM 多留 725 个、少留 905 个；这些差异需要按成员逐项解释，不能只看总数抵消。

与 §14.1 完全相同的原 post-DCE 存活队列另存 `state-element-post-report-survivors.json`。58,255 个元素中，
GrhSIM 删除 14,467 个、GSIM 删除 14,287 个；4,832 个族中 4,533 个成员集合完全一致（93.81%），299 个仍有差异。
原 14,287 个粗粒度表示差异因此已消除并略有反超，但 176 个族仍保留聚合表示，剩余 725/905 个双向差异
仍需单独归因。

### 14.5 符号冲突修复与最终状态分布

`state-split-v2` 中 176 个聚合跳过族并非都由动态访问造成。典型例子是 `entries$REG`：其静态成员名 `REG_2`
与另一个真实数组寄存器冲突，初版因此跳过整个静态族。v4 按 GSIM 方式给既有声明加 `_0`，同步更新所有读写口、
声明标记和受影响状态族的候选成员名；非端口 value 也支持安全重命名，端口和其他 op 类型仍拒绝处理。
新建端口全部进入引用表，避免后续只改声明而漏改读写口。

代表 `entries$REG` 最终仅保留 `{9,10,11,16,17,18,19}`，与 GSIM 一致。最终同队列报告为
`ptmp/firrtl-ingest/F21/state-split-v4/compare/state-element-post-report-survivors.json`：

| 指标 | v2 | v4（符号冲突修复） |
| --- | ---: | ---: |
| 精确匹配状态族 | 4,533 | 4,556 |
| 有差异状态族 | 299 | 276 |
| 保留聚合表示的族 | 176 | 64 |
| GrhSIM 删除元素 | 14,467 | 14,728 |
| GSIM 删除元素 | 14,287 | 14,287 |
| GrhSIM 多留 / 少留元素 | 725 / 905 | 464 / 905 |

最终 GrhSIM 比 GSIM 多删除 441 个状态元素，精确匹配率为 94.29%。464/905 的剩余双向差异仍需单独归因，
不能写成全部状态族已完全对齐。

v4 最终为 18,185,402 op 和 7,150,579 个 SemanticTree 节点，post-DCE SHA-256 为
`c20d9eaadaa4f118996a547686e9cfbcf3711e213f61ef2a4cd66f6c54ffc072`。
单轮 split 为 52.319 s、独立 DCE 为 47.806 s，合计 100.124 s；与 v3 的 101.641 s 同量级。
相比 §13 的 76.172 s 和 GSIM 的 87.332 s，状态成员化增加了实现成本，不能把删除收益描述为同时降低了编译时间。
RSS delta 为 10,421,664 KiB，报告峰值为 34,273,500 KiB，仍属于高内存实现。

### 14.6 最终删除矩阵

`ptmp/firrtl-ingest/F21/state-split-v4/compare/deletion-report.json` 的最终共同 K 结果如下：

| 分类 | v2 | v4（最终） |
| --- | ---: | ---: |
| 双方删除 | 2,497,556 | 2,497,574 |
| 仅 GrhSIM 删除 | 42,764 | 42,786 |
| 仅 GSIM 删除 | 38,977 | 38,959 |
| 双方保留 | 4,662,981 | 4,662,959 |

符号冲突修复使仅 GSIM 删除再减少 18、仅 GrhSIM 删除再增加 22，最终 GrhSIM 净多删 3,827 个共同 K。
普通 K 的改善小于状态元素的改善，说明冲突族的主要收益是更精确的状态表示及相应输入锥，而不是名称变化本身。

### 14.7 共同存活 Node DAG

`ptmp/firrtl-ingest/F21/state-split-v4/compare/dag/dag-report.json` 的共同存活 K 为 4,662,959，边投影和 guard 收缩结果如下：

| 指标 | §13 | v4（最终） |
| --- | ---: | ---: |
| 共同边 | 6,177,389 | 6,072,721 |
| 仅 GrhSIM 边 | 669,079 | 715,179 |
| 仅 GSIM 边 | 445,749 | 507,721 |
| 精确率 | 90.2274% | 89.4639% |
| 召回率 | 93.2698% | 92.2844% |

两端 guard 收缩后的 SCC 均为 0，GrhSIM 未解析 operand 为 0，`max_operation_groups=1`。
精确率下降 0.7635 个百分点、召回率下降 0.9854 个百分点；成员化后的直接元素依赖和来源归属变化增加了投影边差异。
因此，删除矩阵和状态元素的改善不能与 DAG 完全对齐或语义等价混为一谈，仍需按模块继续分析剩余边差异。

### 14.8 连续生产入口与验收边界

原始 FIRRTL 连续入口已执行：

```bash
source env.sh && make f21_grh_dce F21_WORK=ptmp/firrtl-ingest/F21/continuous-state-split
```

`timing.json` 记录 `success=true`，pipeline 中 split 与独立 DCE 均为 `keep_declared_symbols=False`，454 个 false loop
全部修复。split 为 42.247 s、独立 DCE 为 46.599 s，二者 diagnostics 均为空。post-elim 与冻结输入的
SHA-256 `bf19d62ab53682e40a774e76d676e16eddfd631217eae3d71359e7cc620c71c6` 完全一致，最终 post-DCE
SHA-256 与 §14.5 的 v4 同为 `c20d9eaadaa4f118996a547686e9cfbcf3711e213f61ef2a4cd66f6c54ffc072`，
证明连续生产路线与冻结 checkpoint 路线输出确定且一致。

最终验证包括专项测试、`test_f21_dce_tools` 4/4、ASAN 5/5、全量 CTest 77/85 和 FIRRTL workflow 67/73；
后两组失败名单及类别保持既有基线，没有新增失败类型。

本轮没有新增整机 C++/emu 动态等价证明，也没有宣称全部差异闭合：仍有 38,959 个仅 GSIM 删除 K、
464/905 个状态元素双向差异，以及 §14.7 的 DAG 投影差异。最终结论是状态成员化显著增强独立 DCE 的删除能力并
闭合主要代表样本，而不是语义或性能全面优于 GSIM；split+DCE 的时间和峰值内存均高于 §13 与 GSIM 对照。

## 15. 先核对 split 再核对 DCE 的闭环（2026-11-08）

### 15.1 DCE 前的状态成员已全量对齐

本轮按“先比较 split 后、再比较 DCE 后”的顺序核查，不用调整 DCE 保活策略弥补拆分错误。冻结输入仍为
`ptmp/firrtl-ingest/F21/continuous/post-elim.json`，SHA-256 为
`bf19d62ab53682e40a774e76d676e16eddfd631217eae3d71359e7cc620c71c6`。拆分输出直接保存为 `post-split.json`，
不经过 DCE；GSIM 对照改用首次 `RemoveDeadNodes` 之前的 `SimTop_0TopoSort.json`，成员身份继续使用同一 split-map。
报告为 `ptmp/firrtl-ingest/F21/state-split-v13/compare/state-element-post-split-pre-dce.json`。

| 指标 | split 后、DCE 前 |
| --- | ---: |
| 可映射状态族 | 4,832 |
| 成员集合精确一致的状态族 | 4,832 |
| 元素总数 / GrhSIM 多留 / 少留 | 58,255 / 0 / 0 |
| 成员化 / 保留聚合表示的族 | 4,768 / 64 |
| 映射问题 | 0 |

因此，在本对照覆盖的 4,832 个状态族上，**split 本身产生的状态声明和成员索引已经与 GSIM 完全一致**。
64 个保留聚合表示的族不是统计漏项：它们与 GSIM 一样整组保留。后续 DCE 差异必须按实际使用链另行分析，
不能再笼统归因于状态声明没有拆开。

### 15.2 本轮实际修复

实现仍位于 `wolvrix/lib/transform/split_static_array.cpp`，DCE 算法及根规则未改：

1. 缓存命中当前切片自己的 result 时先失效重算，并跳过 `selected == results[0]`，避免生成 `R = assign(R)`。
2. 状态 next-value 的 `selectStateValue` 和嵌套 `select` 无法展开时，生成的 `kSliceStatic` 都登记为待重写切片。
3. 连续成员选择生成 `kArrayCreate`；其类型与原切片不同时增加显式 `kAssign`，不再把形状转换隐含在位宽转换中。
4. whole-read 视图发现穿透等宽 `kAssign`、`kConcat`、`kArrayCreate`、`kSliceArray`、`kSliceStatic` 以及数据分支等宽的
   `kMux`；扁平选择可跨多个 concat 操作数，并按原顺序重建 concat。
5. 成员名忽略大小为 1 的维度；符号迁移使用 `lookupSymbol`，避免重命名后 intern 冲突导致无效 ID。
6. `GraphSplitter::run` 改为增量工作队列。每次选择后，把本轮新建的 op 追加到遍历尾部，使“先出现的静态切片、
   后改写的数组读”能够继续成员化；失败回滚时同时取消对应切片登记，避免访问已删除 op。

新增回归覆盖跨 concat/成员组/嵌套视图、跨状态族 fallback、退化维度、单元素和 memory 跳过、声明符号冲突，
以及两个队列专门场景：早期 `kSliceStatic` 经由后期二维数组读最终只保留 `queued_0_0`，以及 300 层选择失败回滚后
不访问失效 op。相关实现约束同步写入 `wolvrix/docs/transform/split-static-array.md`。

### 15.3 DCE 后状态元素仍未完全对齐

最终报告为 `ptmp/firrtl-ingest/F21/state-split-v13/compare/state-element-post-dce.json`，映射问题仍为 0：

| 指标 | GrhSIM | GSIM |
| --- | ---: | ---: |
| 精确一致的状态族 | 4,771 / 4,832 | 同左 |
| 存活状态元素 | 44,284 | 43,968 |
| 删除状态元素 | 13,971 | 14,287 |
| 相对另一端多留 / 少留元素 | 332 / 16 | 16 / 332 |
| 多留 / 少留位宽 | 563 / 16 bit | 16 / 563 bit |

61 个差异族全部已是成员表示，**没有未拆聚合表示造成的差异**。这闭合了“split 是否对齐”的前提，但不等于 DCE 后
每个成员集合也相同。GrhSIM 净多留 316 个元素，不能用这个净差掩盖双向差异，也不能直接称为删除能力或语义更优。

7 个少留族分别为：

- `loadQueueReplay` 的 `s2_replayUop`、`s2_replayUop_1`、`s2_replayUop_2` 三个 `exceptionVec` 均缺 `{3}`；
- `rob$r_3`、`csr_io_csrio_exception_delay$REG__DOT__bits__DOT__exceptionVec` 及其 `REG_1` 对应族均缺 `{14,17}`；
- `rob$enqPtrGenModule$enqPtrVec__DOT__flag` 只留 `{0}`，GSIM 保留全部 8 个元素。

这些少留可能来自 op 级删除更细，也可能是拆分或活跃性错误；本轮没有新增整机动态等价证明，故不通过强制保活凑数量，
也不把它们一律归类为合法优化。其余多留头部样本包括两个 StoreUnit 的 `s2_in.exceptionVec`（GrhSIM 23、GSIM 5）
和 8 个 `enqRob_req_*_bits_r.exceptionVec`（GrhSIM 24、GSIM 7）。相对地，`StoreUnit_0/s3_in.exceptionVec`
已在两端精确保留 `{3,6,7,15,19,23}`，证明相关静态成员路径可以正确闭合。

GrhSIM 多留项的完整分组如下。“多留”严格定义为 `grhSurvivingIndices - gsimSurvivingIndices`，不是 GrhSIM 全部存活成员；
共 54 个状态族，与上述 7 个少留族不重叠。为可读性，路径省略公共前缀 `cpu$l_soc$core_with_l2$core$`，以 `/` 分隔模块实例、
以 `.` 分隔字段；原始完整 symbol 见对照报告。所有下标均从 0 开始。

| 状态族 | 多留下标 | 族数 | 元素数 | 位宽 |
| --- | --- | ---: | ---: | ---: |
| `memBlock$inner$StoreUnit_{0,1}/s2_in.uop.exceptionVec` | `{0,1,2,4,5,8,9,10,11,12,13,14,16,17,18,20,21,22}` | 2 | 36 | 36 bit |
| `memBlock$inner$lsq$storeQueue/uncacheUop.exceptionVec` | 同上 | 1 | 18 | 18 bit |
| `backend$inner$ctrlBlock/enqRob_req_{0..7}_bits_r.exceptionVec` | `{4,5,6,7,8,9,10,11,13,14,15,16,17,18,19,21,23}` | 8 | 136 | 136 bit |
| `backend$inner$ctrlBlock$renamePipeDispatch/dataVec` 的下述 7 个成员 | `{0..7}` | 7 | 56 | 224 bit |
| `memBlock$inner$dcache$dcache$cacheCtrlOpt$CtrlUnitPseudoErrorPipelineConnect0/data.valid` | `{1..7}` | 1 | 7 | 7 bit |
| 下述 14 个 Load/Vector Split 相关 `exceptionVec` | `{5,13,21}` | 14 | 42 | 42 bit |
| `memBlock$inner$lsq$loadQueue$uncacheBuffer/entries_{0..15}/req.uop.exceptionVec` | `{5,19}` | 16 | 32 | 32 bit |
| `memBlock$inner$StoreUnit_{0,1}/s1_in.uop.exceptionVec` | `{6}` | 2 | 2 | 2 bit |
| `memBlock$inner$dtlb_ld_tlb_ld/req_out.fullva` | `{3}` | 1 | 1 | 64 bit |
| `memBlock$inner$loadMisalignBuffer/req.uop.exceptionVec` | `{4}` | 1 | 1 | 1 bit |
| `memBlock$inner$storeMisalignBuffer/req.uop.exceptionVec` | `{6}` | 1 | 1 | 1 bit |
| **合计** | — | **54** | **332** | **563 bit** |

`renamePipeDispatch/dataVec` 的 7 个成员均多留全部 8 个元素：`singleStep`、`vpu.isFpToVecInst`、`vpu.lastUop`、
`waitForRobIdx.flag` 的元素宽度均为 1 bit，`vpu.vl`、`vpu.vuopIdx`、`waitForRobIdx.value` 分别为 8、7、9 bit，
合计 56 个元素、224 bit。

14 个多留下标为 `{5,13,21}` 的族分别为：

- `memBlock$inner$LoadUnit_{0,1,2}/s1_in_r.uop.exceptionVec`；
- `memBlock$inner$VlSplitConnectLdu{,_1}/data.uop.exceptionVec`；
- `memBlock$inner$lsq$loadQueue$uncacheBuffer/pipelineReg_{2,3,4}.io_out_bits_r.uop.exceptionVec`；
- `memBlock$inner$vlSplit_{0,1}` 下的 `VSSplitSkidBuffer/dataBuffer.uop.exceptionVec`、
  `splitBuffer/uopq.uop.exceptionVec` 和 `splitPipeline/s1_in_r.uop.exceptionVec`。

其中 `exceptionVec` 共多留 268 个元素，占元素数的 80.7%，合计 268 bit；其他状态共 64 个元素、295 bit。
这些族在 split 后、DCE 前的成员集合均与 GSIM 相同，因此差异发生在 DCE 活跃性传播阶段，而不是未拆数组造成的表示差异。
该清单只记录两端存活集合之差，不把多留项直接判定为可安全删除，也不替代逐成员动态正确性验证。

对代表成员的实际根追踪见 `state-split-v12/member-trace/remaining-roots.json`。`enqRob` 路径包含 45 个 concat、
44 个静态切片并到达 DPIC；`s2_in` 和 `singleStep` 也分别到达 DPIC/系统任务。这排除了“SemanticTree 统计虚增存活”
这一解释，但并未证明两端所有相关根和表达式完全等价。后续应逐个比较剩余使用链，而不是继续扩大拆数组范围或引入
GSIM 的 Node 级 DCE。

### 15.4 当前规模与回归

v13 的最终 `post-dce.json` SHA-256 为
`358806dc5cabb7ded2c12e4680603ff018b04d9a363fdf1f78e19073a5b4aa56`，包含 **18,242,935 op** 和
**7,137,638 个 SemanticTree 节点**；SemanticId 校验没有模块路径重复或寄存器符号不匹配，自赋值 `kAssign(x,x)` 为 0。
`post_split_semantic_stats.operation_rows=35,167,778`，split 与 DCE 仍为两个独立阶段，未混入 simplify。

- split、DCE、simplify、comb-loop-elim、FIRRTL state/memory 专项均通过；F21 工具测试 **5/5**，ASAN **5/5** 通过。
- 全量 CTest 为 **77/85**，失败仍为 `grhsim-sink-schedule-tests`、`transform-hier-flatten`、
  `transform-origin-attribution`、`firrtl-node-attributes`、`firrtl-comb`、`firrtl-aggregate`、`ingest-mixed`、
  `firrtl-node-pipeline`，与既有基线相同。
- FIRRTL workflow 为 **67/73**，仍是旧 node 属性断言 2 项及中文 locale/退出码断言 4 项。

这些回归不包含新的整机 C++/emu 动态等价证明。最终性能、共同 K 删除矩阵、DAG 和连续生产入口结果记录于后续小节。

### 15.5 共同 K 删除矩阵与 Node DAG

对 7,242,278 个共同起始 K，最终 `state-split-v13/compare/deletion-report.json` 为：

| 分类 | 数量 |
| --- | ---: |
| 双方删除 | 2,504,751 |
| 仅 GrhSIM 删除 | 46,623 |
| 仅 GSIM 删除 | 31,782 |
| 双方保留 | 4,659,122 |

GrhSIM 净多删 **14,841** 个共同 K。相对 §14 的旧结果，本轮修复继续减少仅 GSIM 删除项，但两端仍各有独有删除集合；
不能把 op 级分析概括为必然严格优于 GSIM，也不能用净删除数代替逐成员、逐节点的正确性验证。

共同存活的 4,659,122 个 K 的 DAG 投影和 guard 收缩结果为：

| 指标 | 数量/比例 |
| --- | ---: |
| 共同边 | 6,012,126 |
| 仅 GrhSIM 边 | 804,589 |
| 仅 GSIM 边 | 529,549 |
| 精确率 | 88.1968% |
| 召回率 | 91.9049% |

两端收缩后的 SCC 均为 0；GrhSIM 未解析 operand、guard path collision 和缺失 op SemanticId 均为 0，
`max_operation_groups=1`。证据为 `state-split-v13/compare/dag/dag-report.json`。DAG 指标仍未闭合，且比 §14 的旧投影更低；
这反映成员化后真实依赖及来源投影的差别，不是 SemanticTree 节点数统计错误，也不是已证明的仿真语义差异。
当前结果不支持“Node DAG 已对齐”或“未来仿真性能必然更好”的结论。

#### post-DCE 存活并集的总边数

为计入单边保留节点相关的边，将上述共同存活顶点扩大为 `grh-survivors.txt` 与 `gsim-survivors.txt` 的并集：
**4,737,527 = 4,659,122 + 46,623 + 31,782** 个 Node。两端分别在各自的 post-DCE 图上取边，
继续使用显式 split map、prev/next 且无 dep 边、guard/WHEN_COND 收缩及有向边去重。这里的“全量”是既有 K 映射范围内
双方全部 post-DCE 存活节点的并集，不包含原始 dump 中无法映射到 K 的节点，也不把 GRH op operand 数与 GSIM 原始边记录数混比。

| 指标 | GrhSIM | GSIM | GrhSIM−GSIM |
| --- | ---: | ---: | ---: |
| 收缩前去重投影边 | 6,794,940 | 6,818,223 | -23,283 |
| **收缩后 DAG 总边** | **6,858,586** | **6,880,937** | **-22,351** |
| 共同边 | 6,012,126 | 6,012,126 | 0 |
| 仅本端边 | 846,460 | 868,811 | -22,351 |

因此，全量收缩 DAG 中 GrhSIM 比 GSIM 少 **22,351 条边（GSIM 总量的 0.3248%）**；两端独有边合计
**1,715,271 条**，不能用较小的净差代替结构差异。共同边与共同存活子图完全相同；扩大到存活并集后，GrhSIM 增加
41,871 条边，GSIM 增加 339,262 条边，所以总边数关系由共同子图的 GrhSIM 多 275,040 条变为全量的 GrhSIM 少 22,351 条。
两端计数均满足“共同边 + 仅本端边 = 总边”，未解析 operand、split 新节点、guard collision 和收缩 SCC 均为 0。

证据为 `state-split-v13/compare/dag-all-survivors/dag-report.json`，顶点并集为
`state-split-v13/compare/post-dce-survivor-union.txt`。新增 `f21_dce_dag` 入口允许通过
`F21_DAG_CANDIDATES`、`F21_DAG_UNMATCHED` 和 `F21_DAG_OUT` 选择顶点集合及输出目录；默认 `f21_dce_compare`
仍只统计共同存活集合，原口径未改变。

#### ROB 独有边的逐条归因

对目标模块恰好为 `cpu$l_soc$core_with_l2$core$backend$inner$ctrlBlock$rob` 的 **113,226 条** GrhSIM 独有边逐条分类。
完整清单为 `state-split-v13/compare/dag-all-survivors/grh-only-edges.tsv`。分析先检查 GSIM 两跳路径，再对剩余 185 个源做不限深度可达性搜索；
每个源预算 1,000,000 次访问，无截断。为覆盖 `enqOH_6_0` 等不在共同 K 并集中的中间节点，GSIM 输入扩展到全部 **6,012,332** 个有效节点，
额外纳入 **252,715** 个 ordinary Node；此时 GSIM 原始投影/收缩边分别为 7,630,245/7,882,587。默认共同节点 DAG 口径未改，
全节点模式只用于本次路径归因。

| 类别 | 数量 | post-elim 已有直连 | GSIM 中的对应结构及结论 |
| --- | ---: | ---: | --- |
| split 父数组两跳路径 | 109,677 | 0 | GSIM 经 split 父数组节点连接同一源和目标；GrhSIM split 后暴露成员直连 |
| 普通算术中间节点两跳路径 | 7 | 7 | `_snapshotPtrVec_*_diff_T_1` 等普通中间表达式，非数组父节点 |
| difftest 长别名路径 | 120 | 0 | 经 `difftest` / `difftest_commit` 的 `otherwpdest` 中转 |
| 指针更新长路径 | 86 | 0 | 经 deq/walk/snapshot pointer 更新链中转 |
| `_frontendCommit_T{,_1..6}` | 3,319 | 0 | GSIM 无对应路径；split 成员视图的 SemanticId 归属造成，见下文操作证据 |
| `_commitInfo_T{,_1..7}` → `commitInfo.ftqIdx` | 16 | 16 | 动态 `robDeqGroup` 选择索引在 GRH operand 投影中可见，GSIM prev/next 无对应路径 |
| `ctrlBlock.clock` → `rob.clock` | 1 | 1 | 层次时钟端口边，目标不在 GSIM 存活集合中 |
| **合计** | **113,226** | **24** | 其余 113,202 条均为 split/DCE 阶段后出现的直连 |

按路径长度汇总，109,684 条有两跳路径，206 条有更长路径，3,336 条在全部有效节点上仍无 GSIM 路径。两跳项中 109,677 条经过
split 父数组，只有 7 条经过普通算术节点。长路径项分为 120 条 difftest 别名和 86 条指针链。**它们不都是 `canEnqueue` 的完全相同形式，
但均不是“GSIM DCE 删除了活跃依赖、GrhSIM 漏删”的证据。**

`canEnqueue` 的代表对照为：GSIM `_canEnqueue_T_3 → canEnqueue_1 → _enqOH_T_10009`，归并父数组后是两跳；
GrhSIM split 选中成员后直接形成 `_canEnqueue_T_3 → _enqOH_T_10009`。这条直连在 post-elim 不存在，不是 ingest 原始多余依赖。

`_frontendCommit` 不能仅凭名字判断为错误的 `OR` 数据位替换。FIRRTL 原始定义为 `or(commitValid[0], commitValid[1])`
（`ptmp/xs/rtl/rtl/SimTop.fir:3765089`）。post-DCE 中：

- 原 `kOr` 仍在 op **2199075**，其两个输入来自数组成员视图；原 OR 结果 value 为 **2205672**；
- `_T_842010` 的 concat 在 op **3102046** 中使用成员 value **17469959**，不是上述 OR 结果；
- 成员视图与原消费表达式共享 SemanticId **944489**，所以 DAG 把成员到 concat 的依赖标成 `_frontendCommit_T → _T_842010`。

因此，这 3,319 条属于 split 后“成员 value 继承父表达式语义”的归属差异，而不是把 OR 结果错误接到 valid 数据位。
全部 3,319 条在 post-elim 均无直连；代表操作的原始 FIRRTL、op/value 和根路径证据已保存。

16 条 `_commitInfo` 边在 post-elim 已存在。`_commitInfo_T = bits(deqPtrVec[0].value, 2, 0)` 是 `robDeqGroup[_commitInfo_T]`
的选择索引（`SimTop.fir:2930195`），后续 `rawInfo[0].ftqIdx` 又参与 `commitInfo[0].ftqIdx` 更新（`SimTop.fir:2933955`）。
GRH 将动态读索引进 operand 投影，GSIM dump 的 prev/next 中没有对应路径；这也不是 split 或 DCE 新产生的逻辑。

因此，本次 ROB 闭合结果不支持“为了删除这些边而修改 DCE 根规则或强行保活/删除节点”。若后续要对齐图形态，应分别处理数组语义归属、
别名/索引投影和层次端口表示，而不是删除实际逻辑。上述结论仅限 ROB，不外推到其他模块的独有边；路径与操作归属分析也不替代
表达式级等价或整机动态验证。

证据统一在 `ptmp/firrtl-ingest/F21/rob-ingest-investigation/`：`summary.json` 为闭合汇总，
`edge-paths-all-gsim-nodes/edge-paths.tsv` 为逐边路径，`all-pre-split-closure.tsv` 为全量 post-elim 闭合，
`post-elim-dag/dag-report.json` 为 split 前图。新增 `f21_rob_edge_paths` 复用该分析；工具回归 **7/7** 通过，
默认投影仍丢弃未匹配中间节点，只有显式 `include_unmatched` 的路径分析保留它们。

### 15.6 连续生产入口与 checkpoint 确定性

原始 FIRRTL 连续入口已执行：

```bash
source env.sh && make f21_grh_dce \
  F21_WORK=ptmp/firrtl-ingest/F21/continuous-state-split-v13
```

`timing.json` 为 `success=true`，454 个 false loop 全部修复；split 和独立 DCE 的 `keep_declared_symbols` 均为 False，
diagnostics 均为空。该运行与矩阵分析并行，split 61.306 s、DCE 50.237 s 仅作过程记录，不作为性能基线。
关键证据是两条路线得到完全相同的图：

- `post-elim` SHA-256 均为 `bf19d62ab53682e40a774e76d676e16eddfd631217eae3d71359e7cc620c71c6`；
- `post-dce` SHA-256 均为 `358806dc5cabb7ded2c12e4680603ff018b04d9a363fdf1f78e19073a5b4aa56`。

因此，最新连续生产管线 `comb-loop-elim → split-static-array → dead-code-elim` 与冻结 checkpoint 的专项 benchmark
在输入和最终图上均一致，而不是仅在单元测试或独立脚本中可用。

### 15.7 无并行干扰的三轮性能复测

最终在 CPU 2 上独立运行三轮，不与回归、DAG 投影或其他大图任务并行；不保存额外 JSON，不计入加载、dump 和后续 simplify。
入口为：

```bash
source env.sh && make benchmark_f21_dce \
  F21_DCE_WORK=ptmp/firrtl-ingest/F21/state-split-v13-performance \
  F21_DCE_INPUT=ptmp/firrtl-ingest/F21/continuous/post-elim.json \
  F21_DCE_RUNS=3 F21_DCE_CPU=2 \
  F21_DCE_BENCH_ARGS="--split-static-array --validate-semantic --sample-rss"
```

| 轮次 | split | 独立 DCE | split+DCE | 采样峰值 RSS |
| --- | ---: | ---: | ---: | ---: |
| 1 | 45.378 s | 57.075 s | 102.452 s | 35,604,896 KiB |
| 2 | 50.462 s | 57.084 s | 107.546 s | 40,568,512 KiB |
| 3 | 45.867 s | 57.033 s | 102.900 s | 41,056,192 KiB |
| 中位数 | **45.867 s** | **57.075 s** | **102.900 s** | **40,568,512 KiB** |

三轮的 post-split/post-DCE 结构化统计及 SemanticTree 回收结果完全一致，SemanticId 校验均通过。
DCE 内 analysis、op/value 删除和 SemanticTree 回收的中位数分别为 **6.803 s、49.500 s、0.419 s**。
证据为 `ptmp/firrtl-ingest/F21/state-split-v13-performance/summary.json`。

同一份 SimTop 的 GSIM run9 同阶段计时为 split 49.664 s、首次 `RemoveDeadNodes` 34.992 s，合计 **84.656 s**。
GrhSIM 的 split 中位数少 3.797 s，但独立 DCE 多 22.083 s，合计多 **18.244 s（约 21.6%）**。
因此，当前实现能够在同等规模输入上确定性地完成 op 级 DCE 和 SemanticTree 回收，但没有在总编译时间上优于 GSIM；
不能把 split 的加速或节点删除数量称为 DCE 单项性能优势。

三轮采样峰值 RSS 中位数为 40,568,512 KiB（约 38.7 GiB）；第一轮新进程的峰值为 35,604,896 KiB（约 34.0 GiB）。
后续轮的分配器保留使起点和峰值变化较大，RSS delta 中位数仅为 2,319,872 KiB，第三轮甚至为负，
因此不能把 delta 当成实现的真实内存需求，也不能据较低 delta 宣称内存问题已经解决。当前主要未闭合工程项是
独立 DCE 删除阶段耗时、较高内存峰值、post-DCE 双向状态差异和 DAG 独有边，而不是 split 的正确插入位置或成员命名。

## 16. 整体复核与全量边差异分类

### 16.1 v13 整体基线

最终图仍为 `state-split-v13/post-dce.json`，含 18,242,935 op 和 7,137,638 个 SemanticTree 节点；SemanticTree 节点数不等于
ordinary Node 数。split 后、DCE 前的 4,832 个状态族、58,255 个元素与 GSIM 全对齐，post-DCE 状态元素为：

| 指标 | GrhSIM | GSIM |
| --- | ---: | ---: |
| 保留 / 删除状态元素 | 44,284 / 13,971 | 43,968 / 14,287 |
| 精确一致状态族 | 4,771 / 4,832 | 同左 |
| 相对另一端多留 / 少留元素 | 332 / 16 | 16 / 332 |
| 多留 / 少留位宽 | 563 / 16 bit | 16 / 563 bit |

GrhSIM 净多保留 316 个元素、547 bit；61 个差异族全部为成员表示，没有未拆聚合造成的差异。共同起始的 7,242,278 个 K 中，
双方删除 2,504,751、仅 GrhSIM 删除 46,623、仅 GSIM 删除 31,782、双方保留 4,659,122；GrhSIM/GSIM 分别保留
4,690,904/4,705,745 个 Node，GrhSIM 净多删 14,841。全部存活并集为 4,737,527 个 Node。

| DAG 顶点范围 | GrhSIM 总边 | GSIM 总边 | GrhSIM−GSIM |
| --- | ---: | ---: | ---: |
| 共同存活的 4,659,122 个 Node | 6,816,715 | 6,541,675 | +275,040 |
| 全部存活并集的 4,737,527 个 Node | 6,858,586 | 6,880,937 | -22,351 |

共同存活子图的共同边/GrhSIM 独有/GSIM 独有边为 6,012,126/804,589/529,549，精确率 88.1968%、召回率 91.9049%；
全部存活并集则为 6,012,126/846,460/868,811，精确率 87.6584%、召回率 87.3737%，不重合边合计 **1,715,271**。
全量入度 p50/p90/p99/max 两端均为 1/2/3/12,288；出度 GrhSIM 为 1/1/9/10,176，GSIM 为 1/1/8/11,169；
362,999 个 Node 的度数不同。两端收缩 SCC、未解析 operand 和 guard path collision 均为 0，`max_operation_groups=1`。

§15.5 的 ROB 专项已闭合 113,226 条 GrhSIM 独有边：109,677 条 split 父数组两跳、7 条普通两跳、120 条 difftest 长路径、
86 条指针长路径、3,319 条 split 语义归属、16 条动态索引及 1 条层次时钟边。ROB 内未见 DCE 漏删活跃依赖的证据，
但不能外推；§16.2 因而对两个方向的全部不重合边继续按形成原因分类。上述数字均不替代整机动态等价证明。

### 16.2 全部 1,715,271 条不重合边的形成原因分类

对 GrhSIM 独有的 846,460 条和 GSIM 独有的 868,811 条边分别做全量分类，不使用 ROB 的结论外推。分类同时记录：
端点在另一端是否存活、另一端两跳/长路径、源节点是否被绕过、split 父数组角色，以及 split 前是否存在同一条直连。
路径搜索不限深度，每源预算 1,000,000 次访问，**无截断源**。GrhSIM 方向的参考图包含 GSIM 全部 6,012,332 个有效节点及
252,715 个额外 ordinary 中间节点；GSIM 方向使用同一存活并集上的 GRH 投影。split 前 GrhSIM 边集与 §15 独立复算的
SHA-256 均为 `92074e4d5ba221250b5adf6b6d6df1a856ed4db7166ac2c8a9fce70903043a48`。

四个总量类别如下：

| 形成类别 | GrhSIM 独有 | GSIM 独有 | 合计 |
| --- | ---: | ---: | ---: |
| 至少一个端点仅在本端存活 | 41,871 | 339,262 | **381,133** |
| split 父数组相关路径或断链 | 442,047 | 496,895 | **938,942** |
| 非 split 父节点的两跳/绕过/长路径 | 277,442 | 12,208 | **289,650** |
| 两端均非 split 父节点且无路径 | 85,100 | 20,446 | **105,546** |
| **合计** | **846,460** | **868,811** | **1,715,271** |

更细的十类计数为：

| 分类 | GrhSIM 独有 | GSIM 独有 | 合计 | 形成原因 |
| --- | ---: | ---: | ---: | --- |
| 单边端点 | 41,871 | 339,262 | 381,133 | 至少一个端点在另一端已被删除，另一端无法形成对应边 |
| split 父数组两跳 | 434,868 | 464 | 435,332 | 参考端经父数组中转，本端成员化后形成直连 |
| 非父数组两跳 | 30,301 | 5,348 | 35,649 | 普通算术、赋值或端口中间节点 |
| split 父数组源绕过 | 4,070 | 52 | 4,122 | 参考端为 `u → 父数组 → target`，本端为 `u → target` |
| 非父数组源绕过 | 4,245 | 237 | 4,482 | 普通中间源节点被绕过 |
| 长路径 | 242,896 | 6,623 | 249,519 | 别名、指针或表达式更新链超过两跳 |
| 无路径：源为父数组、目标非父数组 | 1,009 | 290,380 | 291,389 | 父数组源在另一端被绕过或不再承担数据流 |
| 无路径：源非父数组、目标为父数组 | 1,550 | 197,233 | 198,783 | 父数组目标在另一端被替换或不再承担数据流 |
| 无路径：源和目标均为父数组 | 550 | 8,766 | 9,316 | 两端父数组之间的驱动被成员化替代 |
| 无路径：源和目标均非父数组 | 85,100 | 20,446 | 105,546 | 非数组直连或表达式归属差异，按 split 前状态继续细分 |

`no_path` 表示在当前对照 DAG 中没有路径，不等价于源代码级没有依赖，也不自动意味着某端语义错误。
对全部 605,034 条无路径边，split 前交叉结果为：

| 方向 | split 前状态 | 数量 | 形成解释 |
| --- | --- | ---: | --- |
| GrhSIM 独有 | 本端 split 前已有，GSIM split 前没有 | 132 | 早期 GrhSIM 独有直连 |
| GrhSIM 独有 | 两端 split 前均没有 | 88,077 | split/DCE 阶段新形成的直连，参考端此前和当前均无同一路径 |
| GSIM 独有 | **两端 split 前均有，当前 GrhSIM 无路径** | **516,153** | GrhSIM split/DCE 删除或绕过了原先存在的路径 |
| GSIM 独有 | 仅 GSIM split 前已有 | 672 | split 前即存在的表达差异 |

GrhSIM 的全部 88,209 条无路径边在 GSIM split 前图中均不存在；GSIM 的全部 516,825 条无路径边在 GSIM split 前图中均存在。
这解释了为什么不能用 ROB 的“多数为中转表示差异”概括全图：**GSIM 独有边的大头是 GrhSIM split/DCE 删除原路径，
GrhSIM 独有边的大头之一则是 split/DCE 新暴露的直连。**这些仍是结构事实，不是语义正确性或 DCE 删除能力的单独证明。

无路径边的分布也支持上述形成机制：

- GSIM 方向的高扇出来源包括 `dispatch$fuTypeOH` 10,969、`minIQSelAll` 7,680、`rob$canEnqueue` 4,942、
  `issueQueueALU2...$fuTypeVec` 3,360 和 `rab$deqPtrOHVec` 2,464；主要是 split 父数组/one-hot 向量源被绕过的边。
- GrhSIM 方向的目标模块包括 `intBusyTable` 8,028、`fpBusyTable` 6,120、`rob` 3,326、`vecBusyTable` 1,524；
  另有 `debugModule$_T_443` 1,023 和 `_frontendCommit_T{,_1..6}` 合计 3,337 个来源边。后者已在 §15.5 用原 OR、
  成员 value 和 concat op 验证为 split 语义归属，而非把 OR 结果错误接到 valid 位。

split 前两端的 DAG 独有边仅为 GrhSIM 13,585、GSIM 1,994，远小于 post-DCE 差异，说明主要分化确实发生在 split/DCE。
完整机器汇总为 `ptmp/firrtl-ingest/F21/global-edge-differences/summary.json`；逐边数据为 `grh-only-full/edge-paths.tsv`
和 `gsim-only-full/edge-paths.tsv`，split 前交叉为 `grh-no-path-reference-pre.tsv`、`gsim-no-path-reference-pre.tsv`，
源模块和源节点完整排名均保存在同目录。路径工具回归 **7/7** 通过；本分析未修改 ingest、split 或 DCE 实现。

### 16.3 全部 array-typed value 对比

状态元素只覆盖寄存器/存储数组，不能回答所有 array-typed value 是否对齐。本节比较所有 GRH `shape` 与 GSIM `dimension`，包括 `[1]`；
GRH `w` 为打包总位宽，GSIM `width` 为元素位宽，未知 `width=-1` 单独归类而不当作真实宽度不一致。记录数保留同一语义名称的多个 value 版本，
同时报告唯一名称数，不能用记录数直接推断物理存储量。split 后使用 `post-split.json` 对 GSIM `SimTop_0TopoSort.json`，post-DCE 使用
`post-dce.json` 对 `SimTop_2RemoveDeadNodes.json`，并纳入 split map、生产者 op、形状和符号检查。

| 唯一名称类别 | split 后、DCE 前 | post-DCE |
| --- | ---: | ---: |
| 几何精确匹配 | 10,380 | 2,851 |
| 仅 GrhSIM | 281,596 | 96,405 |
| 仅 GSIM | 5,057 | 4,926 |
| 形状不一致 | 367 | 81 |
| GSIM 未知宽度 | 259 | 0 |
| **并集名称总数** | **297,659** | **104,263** |

| value 记录指标 | split 后、DCE 前 | post-DCE |
| --- | ---: | ---: |
| GrhSIM 全部 array value 记录 | **629,573** | **128,636** |
| GSIM 全部 dimensioned Node 记录 | **16,063** | **7,858** |
| GrhSIM-only 记录 | 597,569 | 112,765 |
| 精确匹配名称的 GrhSIM 记录 | 24,467 | 15,163 |
| 形状不一致名称的 GrhSIM 记录 | 685 | 708 |
| 未知宽度名称的 GrhSIM 记录 | 6,850 | 0 |
| 无法命名的 GrhSIM 记录 | 2 | 0 |

DCE 对 array value 的回收是显著的，但不能把剩余记录全部视为运行时数组逻辑：

| 项目 | split 后 | post-DCE | 降幅 |
| --- | ---: | ---: | ---: |
| 全部 GrhSIM array value 记录 | 629,573 | 128,636 | **79.57%** |
| GrhSIM-only 记录 | 597,569 | 112,765 | **81.13%** |
| split 父数组相关记录 | 476,851 | 89,227 | **81.29%** |
| GrhSIM-only `kArrayCreate` | 16,094 | 513 | **96.81%** |
| GrhSIM-only `kAssign` | 292,524 | 21,703 | **92.58%** |
| GrhSIM-only `kConstant` | 251,650 | 84,767 | **66.32%** |
| GrhSIM-only `kMux` | 31,036 | 3,951 | **87.27%** |

split 父数组记录中，与父几何相同的记录从 442,958 降到 85,847，成员化后不同于父几何的记录从 33,893 降到 3,380。
post-DCE 的 112,765 条 GrhSIM-only 记录按生产者分为：`kConstant` 84,767、`kAssign` 21,703、`kMux` 3,951、
`kRegisterReadPort` 836、`kRegisterReadArrayPort` 517、`kArrayCreate` 513、`kOr` 172、`kSliceArray` 165、`kSliceStatic` 141。
因此，**常量并不代表每周期动态计算，但赋值、mux 和成员视图仍需在最终生成代码中核查求值与调度成本。**

形状差异已全部归因：split 前的 367 项全部为 `[4,1]` 与 `[4]` 之类的退化维度 1；post-DCE 的 81 项中，
48 项为退化维度，33 项为成员化导致的外层维度减少，**没有其他形状不一致，也没有符号不一致**。split 前的 259 个
`element_width_mismatch` 全部确认是 GSIM `width=-1`，不是实际类型错误；post-DCE 无未知宽度项。

结论是：状态成员集合对齐并不意味着所有 array value 的表示一致。GrhSIM 的 DCE 已回收大多数 array value，
但仍保留比 GSIM 更多的常量和中间打包视图，后续优化应针对这些视图的去重、alias 消除和标量化，而不是只检查状态元素数量。
最终报告为 `ptmp/firrtl-ingest/F21/array-values/post-split-final-v2.json`、`post-dce-final.json`，综合汇总为
`array-values/summary.json`；工具回归 **8/8** 通过，未修改生产实现。

### 16.4 `latchedInst.vpu.lastUop` 个案：GRH 保活、GSIM 删除（2026-11-09）

本节固定当前追踪对象：

```text
cpu$l_soc$core_with_l2$core$backend$inner$ctrlBlock$decode$decoderComp$
  latchedInst__DOT__vpu__DOT__lastUop
```

#### 修复前 GRH：保活的是一条伪可达的 assertion 数据链

修复前的 GRH post-DCE JSON 仍同时包含该字段的声明、读口和写口。这里的
`continuous-srcline-v14/post-dce.json` 与 `current-dce-lastuop/post-dce.json`
都来自旧 lowering；下表的 ID 与后者一致。后者附带的
`ptmp/firrtl-ingest/F21/current-lowering-dce/oldtrace.json` 保存了完整 200-entity
反向路径，末端为 `vfofBuffer$_op_1` 的 `kSystemTask:assert`。因此下述路径描述的是
修复前图，不能与本节后面的 current-lowering/post-dce 结果混读。

| 对象 | 证据 |
| --- | --- |
| `kRegister id=4963936` | `ptmp/firrtl-ingest/F21/continuous-srcline-v14/post-dce.json:30181690` |
| `kRegisterReadPort id=4963937`，结果 `value=5004983` | 同文件 `:30181691` |
| `kRegisterWritePort id=5001566` | 同文件 `:30219320` |

从该旧图读值反向追踪，实际链为：

```text
5004983
  -> kAssign 5070845                         (:30288599)
  -> kConcat 5070847                         (:30288601)
  -> kAssign 5089818 -> value 5012990        (:30307572)
  -> kSliceArray 5086293([8], index=5013459)  (:30304047)
  -> vfofBuffer assertion input
```

`5012990` 是 `[8]` 数组值（`:12505910`），而 `5013459` 不是可解析的常量索引。因此
`split_static_array.cpp:73-114` 的 `constantIndex()` 无法得到索引，`:302-313` 会跳过这个动态
`kSliceArray`；修复前 DCE 在 `dead_code_elim.cpp:688-690` 对 live operation 的全部 operands 做
`markValueLive()`，没有 element-sensitive mask（当前 region-aware 分支见
`dead_code_elim.cpp:918-923`）。于是整个数组值的依赖（包括 `lastUop`）进入 assertion cone。

最终的可观察根是：

```text
id=12324541
sym=...vfofBuffer$_op_1
kind=kSystemTask, name=fatal, firrtl.effectKind=assert, firrtl.line=7223730
```

证据为 `post-dce.json:37542295`；对应源码是
`testcase/xiangshan/src/main/scala/xiangshan/mem/vector/VfofBuffer.scala:61` 的
`XSError(entriesIsFixVl && valid && enqValid, ...)`。DCE 在
旧版 DCE 的 `dead_code_elim.cpp:632-641` 把 `kSystemTask` 当作 observable root，随后在
`:644-660` 由 value 找定义 op，在 `:678-685` 对 state read/write/decl 按精确
`regSymbol` 保活 storage family。因此 GRH 的 DCE 认为该寄存器被这条 root 的 whole-value
动态数组路径读到了；但结合 Chisel 的后续 field overwrite，这条是 aggregate-copy 造成的
过近似依赖，不是 assertion 的真实语义依赖，也不是因为 `exceptionVec` 和 `lastUop` 被
放进同一个 `StorageInfo`。FIRRTL lowering 在 `wolvrix/lib/ingest/firrtl/lower.cpp:1028-1053`
对 aggregate 的每个 leaf 生成独立的 symbol、register 和 read port。

#### GSIM：删除的是没有语义消费者的 decode nested field

GSIM pre-DCE 的目标节点存在：

```text
SimTop_0TopoSort.json:4287509
NODE_REG_SRC ...latchedInst__DOT__vpu__DOT__lastUop
```

同一个 assertion 在 GSIM pre/post 都存在，post-DCE 仍为
`NODE_SPECIAL id=5844578`（`SimTop_2RemoveDeadNodes.json:3023534`），其输入边也仍在
`:13486901`、`:13486995`。因此 GSIM 没有把 assertion 删除，也没有把一条仍需的
`lastUop -> assertion` 活边剪掉。

这里必须区分“assertion 名称相同”和“assertion 依赖哪个 `lastUop`”。源码中的 assertion
读取的是 `entries.uop.vpu.lastUop` 与 `enqBits.vpu.lastUop`（`VfofBuffer.scala:47-61`）。
`vfofBuffer.io.in` 的数据来自 `issueVldu`（`MemBlock.scala:1351-1352`），最终接到
`backend.io.mem.vecIssue`（`XSCore.scala:201-203`）。IssueQueue 在 bulk copy 后又明确执行
`enq.bits.payload.og1Payload.vpu.lastUop := s0_enqBits.lastUop`
（`IssueQueue.scala:328-334`；生成 FIRRTL 为 `SimTop.fir:6005736`），这里右值是
**顶层** `lastUop`，不是 `decode.decoderComp.latchedInst.vpu.lastUop`。

而目标 nested register 在 DecodeUnitComp 中只随 `csBundle := latchedInst` 做了 aggregate copy
（`DecodeUnitComp.scala:193-200`）；DecodeUnitComp 实际重写的是顶层
`csBundle.lastUop`（`:197-203`）。传给 `VecExceptionGen` 的 nested field 虽有结构性连接
（`SimTop.fir:3391010` 附近），但 `VecExceptionGen.scala:42-58` 只读取 `decodedInst.fuType`、
`vtype`、`vstart` 等，完全没有读取 `decodedInst.vpu.lastUop`。因此该 nested register
没有 assertion 的真实 effect consumer。

`reference/gsim/src/deadNodes.cpp:55-67` 从 output、`specialNodes` 和外部节点沿 `prev`
反向遍历；`:85-94` 将未访问节点标记为 `DEAD_NODE`，`:102` 删除并在后续
`reconnectAll()` 重建连接。目标的 reachability 记录为
`ptmp/firrtl-ingest/F21/anchor-alignment/gsim-reachability.tsv:7`
（`exhausted_without_root`, `reachable_count=205`），post-DCE 中该精确名称、其
`csBundle/fixedDecodedInst/uopsSeq` decode 链均消失。

关键结构事实是，GSIM pre-DCE 的目标 `lastUop` 只连接到 decode 内部的
`csBundle.vpu.lastUop_0..64 -> fixedDecodedInst -> uopsSeq`
（`SimTop_0TopoSort.json:9722098+`、`:9705763`、`:9713268`、`:9726266`）。
`vfofBuffer` 的输入来自另一条独立 source：

```text
memBlock.inner.io.ooo_to_mem.vecIssue.1.0.bits.vpu.lastUop
  -> vfofBuffer.io.in.bits.vpu.lastUop_1
```

证据为 `SimTop_2RemoveDeadNodes.json:12523989`。所以 GSIM 的实际结果是：目标不在
assertion 所需的 issue-queue `lastUop` 反向 cone 中，被标死后连同局部连接删除；assertion
仍由 `specialNodes` root 保活，并继续使用另一条由顶层 `lastUop` 重新生成的 issue path。
GSIM 的 `splitArray.cpp:383-450` 逐元素重写数组连接，`:586-613` 只在变量索引或后继
连接需要时阻止 optional split，因而不会把 decode nested field 当作 assertion 的真实输入。

“连接消失”发生在图重建阶段，而不是一个单独的删边规则：
`reference/gsim/src/Node.cpp:7-26` 的 `Node::updateConnect()` 从存活节点的
assignTree 叶子重新建立 `prev/next`；`reference/gsim/src/graph.cpp:3-16` 的
`reconnectAll()` 先清空关系，再对剩余节点调用该逻辑。由于 `lastUop` 所在的
`csBundle` 等 decode 节点已经被 `removeNodes(DEAD_NODE)` 删除，重连时自然没有
两端节点可恢复这条边。

#### JSON 粒度边界

当前保存的 `SimTop_0TopoSort.json` 和 `SimTop_2RemoveDeadNodes.json` 只有 `nodes` 与
`edges`；对两个文件执行 `rg 'assignTree|enode|expTree|enodes'` 没有匹配。GSIM 代码实际支持
更细的表达式树导出：`reference/gsim/src/GraphDumper.cpp:315-343` 只有在
`DumpAssignTree` 打开时才写 `assignTrees`，`:367-432` 才序列化 ENode 的 `op/children`；
CLI 开关在 `reference/gsim/src/main.cpp:124-130` 的 `--dump-assign-tree`。因此当前
artifact 的 JSON 确实是 Node/edge 投影，不能从 JSON 单独观察完整 ENode；本节关于
“GSIM pre-DCE 没有跨到 assertion 的 `lastUop` 字段路径”的结论来自 Node/edge 证据和
GSIM DCE 源码，若要审计 mux、动态 index 的 ENode 内部结构，需要重新导出
`--dump-json --dump-assign-tree`。

本个案的归因由此固定为：GRH 的过保活来自 aggregate copy、后续 field overwrite 未被
精确建模，再叠加动态数组的 whole-value liveness 和 op-level operand 传播；GSIM 能删掉
目标连接，是因为该 nested field 没有语义消费者，而 assertion 保留的是 issue path 的
另一份顶层 `lastUop`。后续若修改 GRH，应优先让 aggregate connect/field overwrite 和
动态 `kSliceArray` 都具备元素级依赖表示，再评估 DCE，而不是把 bundle leaf 合并到同一
寄存器 storage family。

本节此前“assertion 保留但 `lastUop -> assertion` 连接在 GSIM 中从未形成”的表述过于
宽泛，容易把“目标 nested field 没有语义依赖”误读成“assertion 不读取任何 `lastUop`”。
正确表述是：assertion 读取 `lastUop`，但读取的是 IssueQueue 从顶层字段重生成的那一份；
被 GSIM 删除的是 DecodeUnitComp 的 `latchedInst.vpu.lastUop`。如果没有上述 Chisel/FIRRTL
overwrite 证据，单凭 Node JSON 确实不能断言 GSIM 删除正确；本次代码证据补上了这个缺口。

#### 修复方案（2026-11-09）

修复目标是让 GRH 得到和 FIRRTL/GSIM 相同的字段覆盖语义，同时保留真正的 assertion
输入。不能删除 `kSystemTask` root，也不能按寄存器名给 `lastUop` 加特判；那会把仍然需要
的 issue-queue `lastUop` 一起删掉。

第一处改动在 FIRRTL lowering。`semantic.cpp:488-505` 已经把 bundle connect 展开到 leaf，
但 `lower.cpp:595-649` 把每次数组成员写都物化成 packed `kConcat(prior slices, new
field, prior slices)`，`Driver::current` 只保存这个整数组达式。后续 leaf 覆盖后，旧
`prior` 仍然作为 operand 留在图中。应把 `Driver` 的当前值改成按 leaf/range 保存来源，
或者在 materialize 前维护等价的 interval provenance：

* 无条件静态写覆盖的区间直接替换旧 source；已覆盖区间不得再挂在最终 driver DAG 上；
* 部分写只保留未覆盖区间的 prior source；
* 动态索引写必须保守保留可能未覆盖的元素，并保留 index/valid 条件；不能把动态写错误
  地收窄成一个静态元素。

第二处改动在 `dead_code_elim.cpp:688-690`。当前实现对 live operation 的所有 operands
  调用 `markValueLive`，因此一个 scalar `kSliceArray` 会把整个 array 及其历史 aggregate
  source 标活。应改成 shape/bit region demand 的反向 transfer：`kAssign` 原样传递，
  `kSliceStatic` 反向映射区间，`kConcat` 按拼接偏移分发 demand，`kMux` 只把条件按 1 bit
  保活并把 demand 传给数据分支，静态 `kSliceArray` 只传给选中的元素，动态
  `kSliceArray` 传给可能被选中的元素集合。`kRegisterWrite*` 仍按 storage family 保活，
  但 data operand 必须使用该 region，而不是整个 value。`grhsim/used-bits.cpp:280-340`
  已有 scalar `SliceStatic/Concat/Mux` transfer，可作为实现入口；数组需将 demand 扩展为
  lazy interval/element set，避免给整机每个宽 aggregate 分配位图。

这两层不能只做其中一层：只有 DCE 区域传播而 lowering 仍保留错误的 aggregate prior，
它仍可能把旧 source 视为真实未覆盖元素；只有 lowering provenance 而 DCE 仍按 whole-value
传播，`kSliceArray` 仍会把整个历史数组拉活。回归 fixture 应覆盖 `bundle := source`、
逐 leaf 覆盖、动态数组写读和 IssueQueue 的 `vpu.lastUop := topLevel.lastUop`，并断言：
Decode nested `latchedInst.vpu.lastUop` 被删除，assertion/system task、IssueQueue 的
top-level `lastUop` 路径和必要的 entry register 仍保留。

#### 实施与复测（2026-11-09）

上述两层修复已经落地：`lower.cpp:57-72,606-703` 为静态 indexed write 维护区间
provenance，完全覆盖的旧 piece 不再进入最终 `kConcat`；动态 indexed write 在物化后回到
保守的 mask/shift 路径。`dead_code_elim.cpp:35-80,851-918` 增加区间 liveness，并对
`kConcat`、静态 slice、数组 slice、mux 和寄存器写口做反向区域传播。数组写口的数据位置由
`firstEventOperandIndex` 解析，因此异步 reset 的 clock/reset 不会被误当成 data。

验证结果：`make test_transform_dead_code_elim`、`make test_transform_split_static_array`、
`make test_firrtl_state` 均通过。修复前已有 F21 `post-split.json`/`post-dce.json` 与 GSIM
split map 的状态元素对齐结果为 155 个状态族、4132 个元素；GRH 和 GSIM 均保留 1786、
删除 2346，155/155 个族的 surviving member index 集合完全相同，
`remaining_surplus_elements=0`、`grh_fewer_elements=0`。这项统计只证明数组状态族的
成员集合一致，不能证明标量 `latchedInst.vpu.lastUop` 已被删除。

随后使用当前 lowering 从同一 F21 FIRRTL 重新生成了
`ptmp/firrtl-ingest/F21/current-lowering/{ingest,post-split,post-dce}.json`。阶段耗时为：
ingest 约 77.8 s、hier-flatten 58.568 s、comb-loop-elim 40.715 s、split-static-array
31.191 s、dead-code-elim 509.694 s；所有阶段诊断成功，post-dce 文件为 5,339,683,393
字节（SHA-256 前缀 `546f87d1ea7f7a9a`）。精确符号
`cpu$l_soc$core_with_l2$core$backend$inner$ctrlBlock$decode$decoderComp$latchedInst__DOT__vpu__DOT__lastUop`
在 post-split 中出现 3 次，分别是 `kRegister`、`kRegisterReadPort`、
`kRegisterWritePort`；在新 post-dce 中出现 0 次，说明声明、读口和写口均被删除。
同一新 post-dce 仍保留
`cpu$l_soc$core_with_l2$core$memBlock$inner$vfofBuffer$entries__DOT__uop__DOT__vpu__DOT__lastUop`
的 `kRegister`、`kRegisterReadPort` 和 3 个 `kRegisterWritePort`，并保留
`...vfofBuffer$_op_0.._op_3` 的 `kSystemTask`（`firrtl.effectKind=assert`、
`name=fatal`）。因此 DCE 删除的是 DecodeUnitComp 的 nested source，保留的是 assertion
实际使用的 IssueQueue/vfofBuffer entry 状态。

用新图重新执行状态族对齐后，`ptmp/firrtl-ingest/F21/current-lowering/post-split-state-report.json`
仍得到 155 个族、4132 个元素，GRH/GSIM 都保留 1786、删除 2346，
`exact_families=155`、`remaining_surplus_elements=0`、`grh_fewer_elements=0`。
该脚本只收集带非空 `shape` 的 aggregate/array register；width=1、`shape=[]` 的标量
寄存器不会进入这 155 个族。因此这个对齐结果与 nested `lastUop` 的 0 命中结果是互补的，
不能用前者替代后者。

还做了隔离实验：把旧 `state-split-v13/post-split.json`（输入 SHA-256 前缀
`d4c0b08b8f24281b`）交给当前 DCE，输出
`ptmp/firrtl-ingest/F21/current-dce-lastuop/post-dce.json` 仍保留该符号 3 次（声明、读口、
写口；读值为 `5004983`）。只有把旧图换成当前 lowering 生成的
`current-lowering/post-split.json` 后，DCE 才将其降为 0 次。这说明根因主要是 lowering
中历史 aggregate `kConcat` 的 provenance；区域 liveness 是必要的第二层，但单独更新
DCE 无法修复旧图已经错误挂上的历史来源。

最终代码对同一 11GB `post-split.json` 的不落盘 DCE smoke 也通过：总耗时 81.06 s，
分析 41.54 s、删除 38.40 s，SemanticTree 删除 6,083,936 个节点，无崩溃或诊断错误。

#### 16.5 全部寄存器（包含标量）的 GRH/GSIM 对齐（2026-11-10）

为避免数组状态统计漏掉 `shape=[]` 的寄存器，当时新增一次性分析工具，现归档于
`ptmp/firrtl-ingest/F21/retired-tools/analyze_f21_all_registers.py`，保留历史复查，
不作为生产入口。它把每个 GRH `kRegister` 和每个 GSIM
`NODE_REG_SRC` 都当作状态单元；GSIM 的 split-array parent 先按
`split-array-map.json` 展开为 `memberName`。DCE 前使用 GSIM
`SimTop_1TopoSort.json`，DCE 后使用 `SimTop_3RemoveDeadNodes.json`；`SimTop_0Init.json`
只用于 parent/member 映射，不能替代 DCE 前图。

结果保存于 `ptmp/firrtl-ingest/F21/current-lowering/all-register-alignment.json`，
完整差异列表保存于
`ptmp/firrtl-ingest/F21/current-lowering/all-register-diffs-toposort/{grh_only_survive,gsim_only_survive}.tsv`：

* GRH 从 284,131 个寄存器（标量 272,475、aggregate 11,656）降到 156,885 个（标量 149,294、aggregate 7,591）。
* GSIM DCE 前有 284,855 个源寄存器（标量 280,348、aggregate 4,507），展开后 DCE 后为 156,110 个单元。
* 两边 DCE 前名称交集为 278,596：两边都保留 152,533，两边都删除 125,712，GRH 独有保留 284，GSIM 独有保留 67。
  交集口径下 GRH 保留 152,817（54.8525%），GSIM 保留 152,600（54.7747%）。名称未匹配的 GRH/GSIM 单元分别为 5,535/6,259，另行列出，不能当作 DCE 差异。
* `decode...latchedInst__DOT__vpu__DOT__lastUop` 在两边 DCE 前都存在，DCE 后都删除；`vfofBuffer.entries...vpu__DOT__lastUop` 在两边均保留。
* `decode...latchedInst__DOT__vpu__DOT__vl` 是当前一个真实的 GRH-only 保留项：GRH 保留、GSIM 删除。GRH 追踪显示它的 350 节点路径最终到 `kDpicCall`，因此需要单独核查 DPIC root 口径，不能把它与已修复的 `lastUop` 混为同一问题。

#### 全寄存器口径复测（2026-11-10）

此前的状态报告只统计带非空 `shape` 的 aggregate/array register。当时改用现已归档的
`ptmp/firrtl-ingest/F21/retired-tools/analyze_f21_all_registers.py`，把所有 GRH `kRegister` 和 GSIM
`NODE_REG_SRC` 都作为状态单元，`shape=[]` 标量也计入；GSIM 的 split-map parent 在比较前
展开为 member 单元。DCE 前使用 GSIM `SimTop_1TopoSort.json`，DCE 后使用
`SimTop_3RemoveDeadNodes.json`；`SimTop_0Init.json` 只用于 split-map 的原始映射，不作为
DCE 前计数。

结果记录在
`ptmp/firrtl-ingest/F21/current-lowering/all-register-alignment.json`：

| 工具/阶段 | 总寄存器单元 | 标量 | aggregate |
| --- | ---: | ---: | ---: |
| GRH post-split | 284,131 | 272,475 | 11,656 |
| GRH post-DCE | 156,885 | 149,294 | 7,591 |
| GSIM TopoSort | 284,855 | 280,348 | 4,507 |
| GSIM RemoveDeadNodes | 156,110 | 153,718 | 2,392 |

两边 DCE 前能够按精确符号匹配的单元为 278,596 个；未匹配的 5,535 个 GRH 单元和
6,259 个 GSIM 单元单独报告，未计入 retention matrix，因为其中包含不同的 memory、
debug/blackbox 以及 aggregate 表示。共同集合的结果是：

| 结果 | 单元数 |
| --- | ---: |
| 两边都保留 | 152,533 |
| 两边都删除 | 125,712 |
| GRH 保留、GSIM 删除 | 284（标量 275、aggregate 9） |
| GSIM 保留、GRH 删除 | 67（标量 65、aggregate 2） |

因此共同集合上的 retention 为 GRH `152,817/278,596=54.8525%`，GSIM
`152,600/278,596=54.7747%`；两边的净差是 217 个单元，不能再概括成“所有寄存器
完全对齐”。完整差异列表在
`ptmp/firrtl-ingest/F21/current-lowering/all-register-diffs-toposort/`。

本次目标的精确状态是：

| 状态符号 | GRH before/after | GSIM before/after |
| --- | --- | --- |
| `decode.decoderComp.latchedInst.vpu.lastUop` | 1 / 0 | 1 / 0 |
| `memBlock.vfofBuffer.entries.uop.vpu.lastUop` | 1 / 1 | 1 / 1 |
| `decode.decoderComp.latchedInst.vpu.vl` | 1 / 1 | 1 / 0 |

所以 `lastUop` 修复后已经与 GSIM 对齐；全寄存器口径暴露出的下一个 GRH-only 标量是
`latchedInst.vpu.vl`。它的 GRH root trace 进入 `kDpicCall`，目标符号为
`v_difftest_ArchVecRegState`，路径经过 `kConcat`、动态 `kSliceArray`、IssueQueue/vldMgu
和 `endpoint$vrf$dpic$implementation$io_value_0`，见
`ptmp/firrtl-ingest/F21/current-lowering/lastuop-trace/vl-trace-full.json`。
GSIM post-DCE 中该 decode `vl` 及其 DecodePipe `vl` 节点均不存在。这个差异需要单独按
`vl` 的 field-level 连接继续审计，不能归回已经修复的 `lastUop` assertion 路径。
