# 03 atom 层次存废与 comb-loop-atom 建模

问题：GRH IR 翻译成初始 grhsim AM 时本没有 atom 概念，atom 这一层是否还要保留？不保留会不会更好？本文档先核查事实，再给出结论：atom 作为调度"层"取消，概念收缩为 **comb-loop-atom**——只打包纯组合逻辑 SCC，在分图问题中作为不可分割节点建模其输入输出结构。

## 1. 事实核查

**初始形态比"一个 block"更极端：零 block。** `LinearProgram` 没有任何 block 概念（`blockCount/blockSize` 只存在于 `ScheduledProgram`，`wolvrix/include/grhsim/am/program.hpp:478-480`）；文档明确禁止"把 LinearProgram 当单 Block 运行"的 fallback（`wolvrix/docs/grhsim/grhsim-am-pipeline.md:103-128`）。所有 block 都是 `ProductionActivityScheduleStage::schedule` 在调度时创建的。lowering 产出 = 平坦指令列表 + SchedulingFacts。

**atom = 指令依赖图的 SCC**，图里只有两种边（`buildInstructionGraph`，`wolvrix/lib/grhsim/am/production_activity_schedule.cpp:126-173`）：

- def-use 边（排除 state-write target 操作数和 `Changed*` 的 old 操作数）；
- ordered effect 边：同 target 写指令组（多写 priority）、memory write priority、DPI 外部调用序、无显式组的 host 指令隐式链。

关键推理：**ordered effect 边自身不可能成环**（组内 ordinal 递增、隐式链程序序递增），所以任何多指令 SCC 都至少含一条 def-use 回边，即**真实组合逻辑环**。含 state/host effect 的环直接编译报错，只有纯 compute 环被保留为单 atom。

**实践中 atom 100% 是单指令。** 全部 19 次 XiangShan 构建统计（4.66M–4.95M 指令）一致显示 `atoms == linear_instructions`、`oversized_atoms=0`、`max_atom_instructions=1`（如 `build/logs/xs/xs_wolf_grhsim_am_build_20260728_085621.log:11`）。多指令 atom 只在单测手工构造的环里出现。**真实电路上，SCC 收缩是恒等映射。**

**atom 身份不出调度器。** emitter / interpreter / validator 全文无 "atom"；下游只认 block。atom 只是调度器内部的中间容器。

**commit 侧本就与 atom 无关。** 写指令 `results` 恒为空 → 结构上不可能进 def-use 环 → commit atom 恒为单指令；commit 有序性靠 ordered effect 边 + (eventRank, guardRank) Kahn 优先级 + "commit 连续后缀"不变量，没有一条依赖 atom 身份。

## 2. 结论：atom 层取消，收缩为 comb-loop-atom

**（a）作为"层次"，atom 不保留。** 它在真实电路上不聚合任何东西，保留一个命名层只会误导后来者以为它有语义。概念模型简化为：

```
指令图 →（环收缩归一化）→ coarsen → 分段 DP → blocks
```

**（b）环收缩作为前置归一化步骤不可省**，理由是正确性而非分区质量：

- block 执行语义的硬前提：act.f 只允许指向更大 BlockId，act.b 只能来自 commit block——**运行时无法表达跨 compute block 的后向激活**，组合环必须收缩进一个块，否则编译失败（"AM coarsened cluster graph is cyclic"）；
- effect 环的两条诊断（state/host effect 环、纯 ordered 环）挂在 SCC 这步，去掉会变成静默错序；
- "环收缩节点自成一块"的 oversized 例外是环的唯一合法出口。

实践中它是恒等映射、成本极低，正确姿势是当作"输入归一化"而不是一个"层"。

**（c）对分区质量本身，保留与否无直接影响。** 真正决定分区质量的仍是 coarsen + 序 + DP 那一段（01 文档 §6 的结论不变）。

**（d）概念收缩为 comb-loop-atom。** atom 保留下来的唯一职能是处理组合逻辑环，名实相符地定义为：

```
comb-loop-atom := 指令依赖图中一个多指令的纯 compute SCC
```

- **纯 compute**：SCC 内不含任何 state write（RegisterWrite/MemoryWrite/MemoryFill/LatchWrite）和 host effect（SystemFunction/SystemTask/DpiCall）；可含 MemoryRead 与纯逻辑/算术指令。
- **多指令**：单指令不成环（SSA 值不可能自依赖），所以 comb-loop-atom 节点数 ≥ 2。
- 现有实现的行为**已经就是这个语义**（含 state/host effect 的环在 `orderAtomInstructions` 直接编译报错，`production_activity_schedule.cpp:479-508`），因此"收缩"是命名与概念澄清，**零行为变更**。

随之简化的词汇表：

- "commit atom" 消失：写指令恒为单节点，compute/commit 退化为**指令上的一个标志位**，不再是 atom 的分类。
- "oversized atom 例外"改述为：comb-loop-atom 不可分割，其重量超过块容量时自成一块（现有 `activity_schedule.cpp:537-538` 行为不变）。
- 环诊断保留在环收缩这一步，与 comb-loop-atom 的识别同点发生。

## 3. 分图问题中的建模

学习/划分问题的输入图：

```
G = (V_instr ∪ V_loop, E)
V_instr：单指令节点，特征 = opcode embedding(46) + 位宽 + 结构度
V_loop ：comb-loop-atom 节点（不可分割的超节点）
E      ：def-use 边（带位宽权重）+ ordered effect 边
```

环收缩后 G 必为 DAG（effect 环是编译错误），learn-to-order / 分段 DP 直接适用。

comb-loop-atom 节点的三个建模要素：

1. **重量 W** = 内部指令工作量之和（指令字数）。不可分割 → 参与容量约束时是"重石头"，超上限自成一块。
2. **输入边界** = 从 SCC 外部消费的 def-use 输入值集合。若所在块被激活，这些输入就是跨边界 activation 成本的一部分——与现有 DP cost（跨段去重 incoming activation variable 数）的口径一致。
3. **输出边界** = 被 SCC 外部消费的结果值集合。影响 fanout/后续块的激活面。

对 GNN 特征：给 comb-loop-atom 一个独立的类型 embedding（第 47 类），附加聚合统计——内部指令数、opcode 直方图、总位宽、入/出边界大小、内部最长路径。**注意它在训练数据里极度稀有（香山为零）**，学不到什么偏好；但它的处理主要由硬约束决定（不可分割、自成块），稀有性可以接受。真出现时的正确性由约束保证，而非由模型保证。

## 4. 一个需要盯住的语义点：单 pass 执行

当前实现对纯 compute 环是"确定性排成**单 pass** 顺序"执行（`orderAtomInstructions` :494-499），即环体只 evaluation 一遍、不迭代到不动点。这意味着：

- 现在 W = Σ指令工作量，单遍成本；
- 如果未来为了支持真实组合环语义而改成**定点迭代**，comb-loop-atom 的执行成本要乘迭代次数，cost model 与特征（内部深度）都要相应调整。
- 这个语义选择不影响分图建模（不可分割性与边界建模不变），只影响重量标定。记在这里防忘。

## 5. 对 topo-partition-proj 的影响

1. **粒度问题收敛了。** 02 文档 open question 1 的"op 粒度 vs atom 粒度"之问基本消解：AM 侧 atom ≈ 单指令，学习问题直接定义在 **AM 指令图**上——46 种 opcode、全香山 4.66M 节点、单层、无调度产物。这比 legacy GRH op 图（5.4M、kind 词表不同）更贴近生产路径，且语义固定性更纯粹（lowering 后、调度前，最规范的形式）。
2. **导出点应挂在 LinearProgram 层**（调度前），而不是复用 legacy 的 compute-op-dag 导出。指令图 + SchedulingFacts 就是学习管线的全部输入；导出器内顺带做环收缩（恒等映射 + 环检查），输出节点带 `is_comb_loop_atom` 标志 + 聚合统计；香山数据上该标志恒假，代码路径用单测的构造环覆盖。
3. **多层/coarsen 的必要性更强了。** 4.66M 节点的指令图不能直接进 GNN 全图推理（或要采样/分层），Herrmann 式 coarsen 内嵌学习的方案权重上升。
4. **commit 侧独立成问题。** commit 块由 (event, guard) 分桶 + 有界合并形成，语义约束强、自由度小，学习价值低；学习聚焦 compute 侧即可。
5. **词汇统一**：本文档起，研究文档中不再使用"atom"指代调度单位，只说"指令节点 / comb-loop-atom / cluster / block"。

## 6. 落地清单

研究项目侧（立即生效）：

- Phase 0 导出器按"LinearProgram 直导指令图"设计（见上节第 2 条）。

生产代码侧（可选、独立的小重构）：

- 把调度器内 atom 相关标识符重命名为 comb-loop-atom 语义（`production_activity_schedule.cpp`、`activity_schedule.cpp` 及对应文档）。纯重命名 + 注释澄清，无行为变更；优先级低，不阻塞研究线。

## 7. 修正记录

- 02 文档 §2 中"atom 粒度特征 = 46 维指令直方图"的描述作废：atom 实践中是单指令，特征退化为单指令特征。
- 02 文档 §6 问题 1 中"atom 粒度（~37.5k 块）"有误：37.5k 是调度**产物** block 数，不是 atom 数；atom ≈ 4.66M 单指令。
