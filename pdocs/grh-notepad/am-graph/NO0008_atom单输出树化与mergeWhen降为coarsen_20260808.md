# NO0008 atom 单输出树化与 mergeWhen 降为 coarsen

日期：2026-08-08
状态：已完成并验收（difftest 73,580/49,996 逐位一致 ×cap48/cap128 两档；
host 306.6s 对基线 −1.0%；默认 maxAtomsPerBlock 改 48；主指标
cross_values_compute_network 515,057→424,315）

## 1. 目标

按 gsim 的层级语义重构"同条件 mux 合并"的落地位置：

1. **atom 单输出树化**：atom 以单个根输出为键折叠其独占输入锥（mux 根树为
   首要形态，即"when 树"），取代 NO0006 按 select 变量全局归组的多输出
   MuxMerge atom。
2. **mergeWhen 降为 coarsen sweep**：同条件合并不是 atom 形成规则，而是
   partition-am-compute-graph 内 coarsen 段的第一个 merge sweep（atom →
   cluster 的 DSU 合并），与 gsim `mergeWhenNodes`（mergeNodes.cpp:78，
   graphCoarsen 内、mergeOut1 之前）层级对齐。
3. **emit 融合回到块级**：emitter 的 if-else 融合不再依赖 MuxMerge atom，
   改为块内同 select 连续段检测（mergeWhen 保证同组成员落同块）。

非目标：本立项不动 commit 图分区；不追求条件等价证明（仍按 select 变量结构
相等归组）；不在本立项处理 supernode-align 线的其余病灶（array-split、
coarsen 预算等，见该线 NO0014 §6）。

## 2. 背景与诊断（为什么重构）

- supernode-align NO0014 实测：解开 mux 全局融合 cross_values −79,708
  （525,331 → 445,623）；mux 输出跨块率 AM 25.0% vs gsim OP_MUX 2.1%。
- 根因是**层级错误**而非想法错误（2026-08-08 会话裁定）：
  - gsim 合并的产物是 supernode（多成员调度单位，多输出是常态），图节点
    永远单输出（一个 node = 一个信号 + 整棵表达式树，when 树折叠在节点内）；
  - NO0006 把合并产物做成了 atom，而 NO0007 裁定 atom 是分区基元（不可
    分割）——多输出 atom 出度巨大，`mergeOut1`（要求出度 1）永远无法
    吸收它，且按 select 全局归组无局部性门控，输出四散被钉死在同一块。
  - 门槛方向也全部相反：gsim 只并大组（> MergeWhenSize=5）、带拓扑波前
    就绪门控（隐含局部性）；NO0006 只并小组（> T=512 整组放弃）、无局部性。
- 对既有裁定的修正：
  - NO0006 §12.4"特性保留且默认开启（atom 路线）"——**修正**：if-else 发射
    特性保留，但合并层级从 atom 降为 cluster + 块级 emit；
    NO0006 §12.3 记录的 cross_values +22% 回退预期由本立项收复。
  - NO0007"atom 即分区大小单位"裁定**不变**，本立项正是靠它推出"多输出
    结构不得成为 atom"。
  - supernode-align NO0014 §6 P-B（mux 融合策略修正，待拍板）——**本文
    即为拍板结论**：降为 coarsen（cluster 级）+ emit 级。

## 3. 概念映射与架构公理（用户裁定，2026-08-08）

| 阶段 | gsim | grhsim am |
|---|---|---|
| 图基元（冻结后不可变） | node（单输出表达式树） | atom（单输出树） |
| 粗化中间态 | supernode（1 节点起步，coarsen 后多成员） | cluster（DSU 合并 atom） |
| DP 切出的终态（激活单位） | supernode（同名原地推进） | block（物化进 program） |

层数与 gsim 一致；gsim 的 supernode 一名覆盖中间态与终态，AM 显式拆分
cluster/block 使阶段边界在术语层面显式。cluster 只是分区器内部的 DSU 根 +
member 计数 + resort 序列位置，不是物化 IR 制品。

**架构公理（atom 冻结不变量）**：atom 内容在 atom 形成阶段结束后不可变；
mergeWhen 及其后的一切操作（mergeOut1/In1/Sublings、resort、DP）只改变
atom 的 cluster/block 归属（DSU/指针移动），与 gsim"node 进 partition 后
只改 `member->super`"严格平行。emitter 可完全信任 atom 结构（单输出树），
if/else 融合、SCC 收敛等信息可安全挂在 atom 上。现状代码已满足该不变量
（分区器从不回写 atom；唯一的 atom 表改写 mergeMuxSelectAtoms 发生在分区
之前），本立项保持并强化之。

## 4. 设计要点（立项裁定，实施时细化）

### 4.1 atom 单输出树化（atom 形成阶段，split/opt-am-compute-graph 侧）

1. 以**单个根输出**为键做锥吸收：结果仅被唯一消费者使用的指令可被吸进
   消费根的 atom（自底向上折叠），复用 mergeMuxSelectAtoms 的独占使用
   不动点机制，但归组键从"同 select 组"改为"单根"。
2. 屏障规则不变：interface/observable/external_read 等 pinned 变量不进锥
   （保持图外可观测）；commit 侧不吸收；comb-loop SCC atom 保持特例、
   不参与吸收也不被拆。
3. 树尺寸不设 cap：激活单位是 block 不是 atom（NO0006 §10 的激活粒度
   顾虑不适用于单输出树——gsim 的 node 也无 cap，超大树由 DP oversized
   自成段兜底）。实施时实测最大 atom 尺寸复核此判断。
4. 成员保 atom 内拓扑序（def-before-use 天然满足锥前置语义）。
5. atom 需携带分区/发射用元数据：根指令、根 opcode（识别 mux 根）、
   select 变量 id（mux 根时），供 mergeWhen 与 emitter 使用。
6. `mergeMuxSelectAtoms` 退役：其锥吸收机制移植到本 pass；MuxMerge atom
   kind 清除（含 emitter 的 MuxAtomPlan 路径）。

### 4.2 mergeWhen coarsen sweep（partition-am-compute-graph 内）

1. 位置：`enableCoarsening` 段首、mergeOut1 之前
   （grhsim_am_compute_graph_partition.cpp:442 段内），与 gsim
   graphCoarsen 的调用序一致（mergeNodes.cpp:53）。
2. 移植 gsim 三道门（参数化，默认值照 gsim）：
   - 资格：atom 根为 mux（单输出 when 树 atom）；
   - 归组：按 select 变量 id 分组，**组尺寸 > MergeWhenSize（默认 5）才
     合并**（只并大组；小扇出组留在普通 atom/块级融合兜底，相当于 gsim
     When2muxBound 的效果，无需独立机制）；
   - 局部性：拓扑波前就绪门控（移植 cond 队列算法到 atom DAG：组内成员
     的其他依赖全部就绪、与 select 生产者同波前时才成组合并）。
3. 合并动作仅 DSU 合并（atom rid → cluster），不触碰 atom 内容（§3 公理）。
4. 成环安全：合入前 anyPath 检查或事后一轮修复（gsim #if 0 分支有
   anyPath 先例；AM 侧沿用现有 SCC 解合并思路，实施时定）。

### 4.3 emit 块级融合（emitter 侧）

1. MuxMerge atom 驱动的 MuxAtomPlan 融合路径随 atom kind 一并移除。
2. 恢复块级同 select 融合：块内连续同 select mux 段检测（NO0006 的
   planMuxRuns 思路，作为唯一机制复活），或 materialize 透传 cluster/run
   元数据。v1 取前者（零 IR 改动）；需保证 materialize 把同 cluster 成员
   在块内排连续（mergeWhen 成员本就同块，块内排序策略实施时核实）。
3. 段首一次求值 select，`if (S) {...} else {...}` 两臂逐条赋值；臂简化
   规则沿用 NO0006。

### 4.4 pass 顺序（最终形态）

```
... → opt-am-compute-graph（图形 rewrite；atom 单输出树化在此完成或
      在 split 时原生形成，实施时定）
    → partition-am-compute-graph：
        Kahn 定序 → mergeWhen（新）→ mergeOut1 → mergeIn1 →
        mergeSublings → resort(LIFO Kahn) → Kernighan DP → blocks
    → materialize → emit（块级 same-select 融合）
```

## 5. 分阶段工作计划

- **P0 基线快照**：记录现行基线（cap128：cross_values_compute_network、
  块数、atom 数；host 309.7s；difftest 73,580/49,996；AM 套件 14/14）。
- **P1 atom 单输出树化**：新 atom 形成 pass + mergeMuxSelectAtoms 退役 +
  MuxMerge kind/MuxAtomPlan 清除；单测（折叠正确性、屏障、确定性）；
  本阶段允许 emit 融合暂时退化为逐条三元（P3 恢复）。
- **P2 mergeWhen sweep**：coarsen 段首插入；参数链
  （ActivityScheduleOptions → CLI → Makefile → wolvrix_xs_grhsim_am.py，
  仿 muxAtomMax 既有链路）；单测（归组门控、波前门控、成环安全）。
- **P3 emitter 块级融合恢复**：连续段检测 + if-else 发射 + 臂简化；
  文本断言测试与行为等价测试（复用 NO0006 测试资产改造）。
- **P4 生产验证**：canonical 发射 → 指标（cross_values、块数、原子形态
  分布、ge2）→ emu 构建 → difftest 50k → host 计时；与 P0 基线和
  supernode-align NO0014 的消融预测（−80k 起）对照。

## 6. 验证标准

- 语义不变：canonical difftest 73,580/49,996 逐位一致；AM 套件全绿。
- 形态指标：cross_values 收复 NO0006 §12.3 的 +22% 回退并向
  NO0014 解开融合水平（445,623 或更低）靠近；mux 输出跨块率从 25.0%
  向 gsim OP_MUX 2.1% 量级收敛；atom 数/块数变化如实记录。
- 运行时：host 以 309.7s（NO0007 基线）为参照，不回退为目标。
- 架构公理不被破坏：分区器零 atom 回写（代码审查 + 测试钉住）。

## 7. 开放问题（实施时裁决）

1. atom 树化的折叠范围上限是否真的不需要（超大树的激活/编译期代价实测）。
2. mergeWhen 是否只收"终端"mux 根（结果直喂状态写或少消费者）——gsim
   无此显式限制，v1 不加，实测再议。
3. atom 树化后 atom 数与 gsim node 数（现口径 0.8608x）的偏离方向与
  幅度；统计口径脚本是否需同步（supernode-align 线）。
4. 块内同 cluster 成员连续性由 materialize 显式保证还是排序自然达成，
   实施时核实并钉测试。

## 8. 关联

- supernode-align NO0014（图病灶定位，本立项裁定其 P-B）、NO0013
  （统计口径）；supernode-align NO0010（对齐目标定义）。
- am-graph NO0006（被修正的 atom 级合并与其 emit 资产）、NO0007（atom
  一等公民化，其"atom 即分区单位"裁定是本立项的推理支点）。
- gsim 对照源码：`reference/gsim/src/mergeNodes.cpp`（mergeWhenNodes/
  when2mux）、`reference/gsim/src/graphPartition.cpp`（graphCoarsen/
  graphInitPartition）、`reference/gsim/src/main.cpp:56-57`
  （MergeWhenSize=5 / When2muxBound=2 默认值）。

## 9. 增量更新 2026-08-08：P0 基线快照（实施前）

以下基线均为既有会话实测（supernode-align NO0013/NO0014、cap24 实验），
作为本立项各阶段的对照锚点：

- 语义验收口径：canonical difftest 50k = **73,580 instr / 49,996 cycles**，
  要求逐位一致；AM 套件 **14/14**。
- 运行时基线：host **309.7s**（NO0007 P3 后，cap128 默认配置）；
  cap24 块对齐实验 338.2s（+9.2%，双输形态的负面对照）。
- 形态基线（cap128 默认 T=512 MuxMerge 开启）：
  - 生产 cross_values_compute_network **515,057**（对 gsim 178,151 =
    **2.8911x**）；离线实验室复现 525,331（±2-5% 带内）。
  - compute 块数 **22,565**（gsim supernode 88,375，余量 3.9x —— 块
    过大、过度激活）；节点数比 **0.8608x**（AM atom / gsim node）。
  - mux 输出跨块率 AM 25.0% vs gsim OP_MUX 2.1%（NO0014 §4）。
- 实验室消融锚点（cap128，cross_values）：解开 mux 全局融合 −79,708；
  链预算 256→7000 −78,183；两者叠加 374,295（NO0014 §4 表）。
- 参数链基线：`muxAtomMax=512`（本立项移除）、`maxAtomsPerBlock=128`、
  `dpCoarsenAtomBudget=0(→256)`、`dpSegmentPenalty=1.0`、
  `dpRefinementRounds=10`。

## 10. 增量更新 2026-08-08：实施记录（P1–P3 落地）

**落地内容**（wolvrix 仓，AM 套件全绿、全量 ctest 仅剩 3 个既有归档失败）：

- **P1 tree-atom fold**：`foldSingleOutputTreeAtoms`（
  `grhsim_am_compute_graph_optimize.cpp`）取代并删除 `mergeMuxSelectAtoms`。
  规则：compute 侧、单指令 atom、纯副作用、单结果、非 pinned、恰好一个
  依赖使用的指令折叠进其唯一消费者（消费者同为单指令 compute atom）。
  屏障覆盖 commit 侧、comb-loop SCC（双向）、pinned（interface/
  observable/external）。折叠关系是指令 DAG 上的静态森林，汇合且确定性；
  根为集合唯一汇点、成员拓扑序（根恒在最后，硬校验）。`AmAtomKind`：
  `MuxMerge` 退役、`Tree` 新增；signature 新语义：mux 根 compute atom
  （Singleton/Tree）记 select 变量 id，其余 compute atom 与 CombLoopScc
  记 `kInvalidAtomSignature`，CommitEvent 仍记事件 rank。折叠后重建
  atom 表 + atom DAG（SCC 硬校验兜底，理论上不可能成环）+ 两张诱导子图。
  `muxAtomMax` 参数链（options/CLI/Makefile/python）整体移除。
- **P2 mergeWhen sweep**：`partitionAmComputeGraph` 的 coarsen 段首、
  mergeOut1 之前（gsim graphCoarsen 调用序）。gsim 队列算法忠实移植
  （cond 队列 + condWait + 波前就绪门控），两处确定性/健壮性修正：
  condWait 用 rid 有序的 `std::set<uint32_t>`（gsim 用指针序），主循环
  改为 `while (!pending || !conds || !condWait)`（gsim 结构在"源点全是
  cond"时一次都不处理，移植时修正）。资格：signature != 无效值且
  select 有 compute 侧生产者 atom（state/interface select 的组 v1 不
  并，记录为限制）；只动 DSU 归属（member/alive/parent），sweep 后立即
  重建 rid 邻接供 out1/in1 看到 cluster。融合锚点
  `AmComputeActivityGraph::atomFusionAnchor`：组成员共享组内最小
  minInstruction，最终块分组 Kahn 以 `(block, 锚点或自身 minInstruction,
  minInstruction, atom)` 排序使同组成员块内相邻。统计：`coarsenWhenGroups/
  coarsenWhenMerges` 进 coarsen-dp stats。
- **P3 emitter 块级融合**：`planMuxFusionRuns` 取代 `planMuxMergeAtoms`
  （MuxAtomPlan 机制整体删除）。run = 块内相邻、根指令为 mux 且 select
  相同的 atom 连续段（select 从根指令推导，不信 signature）；锥成员按
  atom 序前置，根 mux 序列走既有 `emitMuxRun` 单 if/else；run 在 select
  变化、非合格 atom、或锥引用前序 run 根结果（防 use-before-def）处
  断开。`muxAtomFused` 统计口径不变（融合臂条数）。
- **参数链**：`ActivityScheduleOptions.mergeWhenMinGroup`（默认 5，
  <2 关闭）→ CLI `--merge-when-min-group` → Makefile
  `XS_WOLF_GRHSIM_AM_MERGE_WHEN_MIN_GROUP` → wolvrix_xs_grhsim_am.py。
- **测试**：`grhsim-am-mux-atom` 重写为 `grhsim-am-tree-atom`（折叠/
  链式/pinned 根/comb-loop 屏障/commit 边界/确定性 6 例）；
  test_program_atoms 改 Tree 语义（显式元数据往返、单成员 Tree 拒收、
  materialize 携带 atom 层）；test_cpp_emitter 改三个融合用例（Tree
  atom + 隐式 singleton 的 run 融合、pipeline 全链路融合、select 变化
  断 run 不融合）；test_production_activity_schedule 既有用例适配
  （pinned/Observable 屏障保住链式拓扑语义），新增 mergeWhen 三例
  （同 select 聚类/最小组门控/波前排链）。

**生产冒烟**（canonical emit，默认配置）：

- fold：`atoms=1,122,663`（3,032,212 指令 → 折叠 1,909,549 条进入树）、
  `tree_atoms=354,614`、`mux_rooted_atoms=116,366`、最大树 2,065 指令；
  oversized atom 916 个（各自独占一块，gsim oversized 同构）。
- mergeWhen：`when_groups=1,251`、`when_merges=37,610`。
- 分区：compute 块 **8,940**（基线 22,565；gsim 88,375），commit 块 481。
- 发射：融合 if/else 结构生产可见（`mux_atom_fused=65,191`），形态抽查
  符合两相发射设计（锥前置 + 单 if/else 多臂）。
- 形态指标（supernode_align_metrics，对 gsim flat prod 基线）：
  - **cross_values_compute_network 385,604 = 2.1645x**（基线 515,057 /
    2.8911x；−25.1%，收复 NO0006 §12.3 的 +22% 回退后继续下探）；
  - cross_values_compute_consumer 1.9961x；legacy cross_values 2.8998x；
  - compute_compute_value_pairs 1,254,243 vs gsim 1,303,530（0.962x，
    首次进入 1x 以内）；incoming_copy_cost 4,282,702 vs 1,314,227
    （3.259x，跨界值的多块扇出仍是残余大头）；
  - nodes 0.3688x（AM atom 1,122,663 vs gsim instruction 3,043,902 ——
    AM 树折叠比 gsim 信号粒度更激进，口径注记见 §7.3）。
- difftest 与 host 计时：见 §11。

## 11. 增量更新 2026-08-08：P4 生产验证（cap128 验收 + 容量扫描）

**语义验收（cap128 默认档）**：coremark 50k difftest **73,580 / 49,996
逐位一致**（IPC 1.471718，与基线逐位相同）。

**host 计时（cap128）**：**325.7s**，对 NO0007 基线 309.7s **+5.2%**——
形态指标大幅改善的代价是块变大（cap128 按 atom 计，atom 树化后块均值
≈119 atom ≈ 320 指令，为旧块形 ~135 指令的 2.4 倍），激活粒度变粗。
容量语义已随树化改变：cap 的单位从"近似指令"变成"树节点"（对齐 gsim
node），旧容量档不再可直接沿用。

**离线实验室容量扫描**（新图，`/tmp/plab_no0008`，lab 无 mergeWhen
sweep，故绝对值略高于生产；曲线形状可靠）：

| cap | blocks | cross_values_compute_network（lab） |
|---|---:|---:|
| 24 | — | 428,502 |
| 32 | — | 424,655 |
| 48 | 25,750（均 43.6 atom ≈ 118 指令） | 415,999 |
| 64 | 19,455（均 57.7） | 408,163 |
| 96 | — | 399,180 |
| 128 | — | 391,732（生产口径 385,604，mergeWhen 再省 ~6k） |

曲线平坦（cap128→48 仅 +6.2%），块数近似 1/cap 缩放——容量换取活度的
自由度很大。选 **cap48** 做生产确认点（块形 ≈ 旧 116-135 指令/块）。

**cap48 生产形态**（数据集 `xs_am_no0008_cap48_20260808`）：compute 块
21,563（supernodes 22,044，块均值 50.9 atom ≈ 137 指令）；
cross_values_compute_network **424,315 = 2.3818x**（lab 预测 415,999，
偏差 +2.0% 在复现带内）；mux_atom_fused=64,781。对比：基线 515,057
（2.8911x）→ cap48 424,315（2.3818x）→ cap128 385,604（2.1645x）。

**cap48 验收**：difftest **73,580 / 49,996 逐位一致**；host **306.6s =
对 NO0007 基线 −1.0%**（噪声带内持平，性能不回退达标）。

**两档总结与默认裁定**：

| 配置 | host | cross_values_compute_network | compute 块 |
|---|---:|---:|---:|
| NO0007 基线（MuxMerge） | 309.7s | 515,057（2.8911x） | 22,565 |
| NO0008 cap128 | 325.7s（+5.2%） | 385,604（2.1645x） | 8,940 |
| NO0008 **cap48（新默认）** | **306.6s（−1.0%）** | **424,315（2.3818x）** | 21,563 |

`maxAtomsPerBlock` 默认值 128 → **48**（options/分区输入/split context/
CLI/Makefile 五处同步），理由：树化后 atom 均值 ~2.7 指令，cap48 的块
形（≈137 指令）对应旧 128 singleton 时代的有效粒度；cap128 作为
supernode-align 线的形态最优点保留（一行 Makefile 覆盖即可切换）。

**口径注记（2026-08-08 用户裁定）**：上表两档的块数（9,421 / 22,044）
均远低于 gsim 的 88,375，cross 读数对 AM 有偏袒，**不作为对齐结论**；
块数对齐（±10%）口径下的当前权威读数为生产 cap9（83,521 块，含
mergeWhen）**461,760 = 2.5920x**（详见 supernode-align NO0010 增量
更新 2026-08-08）。

**遗留**（交 supernode-align 线）：~~state/interface select 的 mergeWhen
组 v1 不并（生产者 atom 缺失）~~ **【已解决，2026-08-08】** 虚拟锚点 +
SCC 精确解散落地，生产 140 组存活/64 解散，指标中性（NO0010 增量(三)
有完整归因弧线）；emitter 融合只盖 mux 根（gsim
mergeExpTree 的表达式树内 when 合并更强）；非 mux 根树（如 or 根含
嵌套 mux）的融合覆盖；容量/形态联合寻优（P-D）在新图上重启。
