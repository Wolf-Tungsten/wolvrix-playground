# NO0207 Activity-Schedule Compute Supernode 概率驱动划分升级计划

记录日期：2026-06-25
状态：**规划文档**（未落地；含 2026-06-25 用户决策更新，见 §9.1）。本文把 `ptmp/new-partition-algo/` 的两篇新算法草案落到当前 `activity-schedule` 实现上，给出分阶段、可门控、可 A/B 的升级路线。
关联：
- 输入草案：`../../ptmp/new-partition-algo/partitioning-problem-v2.md`（问题定义 v2）、`../../ptmp/new-partition-algo/partitioning-algorithm.md`（算法描述）
- [`NO0070`](./NO0070_grhsim_activity_schedule_computenode_rewrite_plan_20260505.md)：computeNode / commitSupernode 中间层重构（本文复用其框架，不推翻）
- [`NO0185`](./NO0185_xs_components_aligned_coarsen_strategy_20260523.md)：当前 plain coarsen 已验证口径（coarsen 不看 cap、DP 看 cap）
- [`NO0093`](./NO0093_essent_mffc_activity_schedule_plan_20260518.md)：早期 ESSENT/MFFC 主线（其 `enable_essent_*` 路径已从当前源码移除）
- [`NO0189`](./NO0189_grhsim_gsim_supernode_cost_tsv_instrument_plan_20260611.md) / [`NO0190`](./NO0190_grhsim_gsim_unified_cost_model_comp_src_sink_plan_20260612.md)：统一 runtime 成本模型 `T = Σ f(i)·(c·n…)` 与 TSV 插桩（本文要求划分目标函数与之同源）
- [`NO0206`](./NO0206_commit_activation_mask_group_plan_20260624.md)：commit 侧 `a_succ` 优化（与本文 compute 侧划分正交，互不覆盖）

---

## 1. 背景与动机

### 1.1 当前 compute supernode 划分的真实形态

当前 `activity-schedule` 的 compute 侧划分（锚点 `wolvrix/lib/transform/activity_schedule.cpp`）是**纯结构贪心**，没有任何概率 / 激活 / 节点成本模型：

| 环节 | 当前实现 | 锚点 |
| --- | --- | --- |
| 分类 | `Source / Sink / Compute / Declaration / Unsupported` | `classifyActivityOp` (`:3120`) |
| 种子 | 反向建树形成 computeNode（唯一 consumer 吸收 / common-expr 独立），等价于「每 op 或局部表达式树一个簇」 | `buildComputeNodeRewrite` (`:5937`)、`makeSeedPartition` (`:1157`) |
| 粗化 | 三条启发式 merge：单出 / 单入 / 同前驱兄弟，唯一约束是 `maxOps` 上限 | `tryMergeNodeOut1/In1/Siblings` (`:5509/:5603/:5403`)，循环在 `materializeComputeNodeSchedule` (`:6417`) |
| 分段 | DP，代价是**跨边条数**（edge-cut count），约束是 `maxOpInComputeSupernode` | `buildComputeSupernodeSegments` (`:5697`)、`buildDpSegments` (`:1980`) |
| 成本模型 | 仅 `costModel = "edge-cut"`；簇间 `weights` 只是跨边**重数计数**，不是 `p(e)·W` | `activity_schedule.hpp:45`、`valueEdges.weights` (`:4558`) |

实测确认：`mffc` / `essent` / `probab` 在当前 `activity_schedule.cpp` 中**一次都不出现**（46 处 `activation` 全是字面量），即 [`NO0093`](./NO0093_essent_mffc_activity_schedule_plan_20260518.md) 的 `enable_essent_mffc_build` / `enable_essent_coarsen` 路径已从主路径移除。当前唯一在跑的就是上表的 plain coarsen（[`NO0185`](./NO0185_xs_components_aligned_coarsen_strategy_20260523.md) 固化口径）。

### 1.2 核心缺口：划分决策与 runtime 成本脱节

[`NO0190`](./NO0190_grhsim_gsim_unified_cost_model_comp_src_sink_plan_20260612.md) 已经把**运行时**成本建成：

```
T = Σ_i f[i] · ( c_comp·n_comp[i] + c_src·n_src[i] + c_sink·n_sink[i] + c_const·n_const[i] + c_succ·a_succ[i] )
```

其中 `f[i]` 是超节点 i 的激活次数。但**划分阶段**优化的却是「跨边条数」——它对以下三件事完全盲视：

1. **激活频率 `f[i]`**：当前 DP 把每条跨边等价看待，不区分「几乎每周期都激活的边」与「极少激活的边」。而 runtime 成本里 `f[i]` 是一等乘子。
2. **节点真实成本 `W(S)`**：当前用 op 计数封顶，不区分 `kAdd`/`kMux`（便宜）与状态读 / 宽位运算（贵）。[`NO0190`](./NO0190_grhsim_gsim_unified_cost_model_comp_src_sink_plan_20260612.md) §11.6 的 4× 缺口正是「每 op 不等价」。
3. **激活概率耦合**：合并两个**共激活**的簇（同前驱、同时变化）几乎零额外成本；合并两个**反相关**的簇会让每次激活都做无用执行（低内聚 `φ`）。当前 sibling merge 抓到了「同前驱」的结构形状，但没有概率量化，无法区分「同前驱且共激活」与「同前驱但分支互斥」。

`ptmp/new-partition-algo/` 两篇草案正是补这三件事：用**静态变化概率 `π(v)`** 把划分目标函数改写成与 runtime 成本同构的形式，再用 **MFFC 种子 + 概率驱动贪心粗化**在 50M 规模上线性求解。本文的任务是把它接到上面的现有实现上，而不是另起炉灶。

### 1.3 升级红线（贯穿全文）

- **不推翻 [`NO0070`](./NO0070_grhsim_activity_schedule_computenode_rewrite_plan_20260505.md) 框架**：computeNode / commitSupernode 两类中间层、两阶段 emit 不动点、source clone 语义、reg-to-mem intent 不可分组（`collectRegToMemIntentComputeGroups` `:4342`）全部保留。本文只替换**划分决策层**（种子选择 + 粗化增益 + DP 代价），不碰 emitter，不碰 commit 侧。
- **必须可门控、可 A/B**：新路径挂在独立开关后，默认仍是 [`NO0185`](./NO0185_xs_components_aligned_coarsen_strategy_20260523.md) plain coarsen，直到 50k runtime gate 证明收益。
- **50M 规模约束优先于求精**：沿用 [`NO0070`](./NO0070_grhsim_activity_schedule_computenode_rewrite_plan_20260505.md) 的复杂度红线——线性 / 近线性，禁止 per-root 全图扫描，禁止 `roots*ops`。[`NO0185`](./NO0185_xs_components_aligned_coarsen_strategy_20260523.md) 记录的 `final_materialize` 卡死（`compute_nodes=6635278` 后长时间无输出）是前车之鉴。
- **目标函数与 runtime 成本同结构**：划分用的节点成本 `w(v)` 沿用 [`NO0190`](./NO0190_grhsim_gsim_unified_cost_model_comp_src_sink_plan_20260612.md) 的**类别划分** comp/src/sink/const，但**不继承其回归出的 `c_*` 数值**（2026-06-25 决策：那批回归系数已判无效）；各类单位成本作为占位常量，留待实现后参数扫描标定（§9.1）。激活频率 `f[i]` 首版用静态激活概率 `P(S 激活)` 作代理估计，**不做 runtime profiling 回灌**（2026-06-25 决策，§9.1）。

---

## 2. 输入草案要点（两篇 ptmp 文档摘要）

> 仅摘录与落地相关的部分，完整定义见 `../../ptmp/new-partition-algo/`。

### 2.1 问题定义 v2（`partitioning-problem-v2.md`）

- **节点权重** `w(v) = nodeCost(v)·bitwidth(v)`；**节点变化概率** `π(v) ∈ [0,1]`；**边概率** `p(u,v) = π(u)`。
- **目标函数（精确）**：`Cost(P) = Σ C_check(S_i) + Σ W(S_j)·P(S_j 激活)`，其中 `P(S_j 激活) = 1 - Π(1 - p(S_i,S_j))`。
- **Union-Bound 近似**（`p≪1`）：`Cost ≈ Σ C_check + Σ p(S_i,S_j)·W(S_j)`。**草案自带警示**：时钟驱动组合逻辑 `p→1` 时近似严重高估，须退回精确式。
- **分支预测感知 `C_check`**：激活概率 `≈0` 或 `≈1` 时检查几乎零分支预测失误；`≈0.5` 时每次都可能 miss（`+C_bp_miss`，建议 5~10×）。
- **约束**：① 超图无环（硬，保证 Singular 单次求值）；② 内聚度 `φ(S)=Σ w·π / (W·P(激活)) ≥ φ_min`（建议 0.5~0.8）；③ 权重上限 `W_max`；④ footprint 上限 `F_max`（草案原文写「L1 容量」；本文按**宿主 x86 L1D** 标定，见 §9.1）。
- **量化指标**：共激活相关 `ρ(u,v)`、入边界集中度 `χ`、MFFC 覆盖率 `η`、权重-边界乘积 `ψ`、高活跃比例 `γ`。
- **静态概率传播**：源先验（时钟 1.0、数据 0.05~0.2、寄存器读 0.1~0.3、常量 0）；按拓扑序传播（`kMux`/算术用乘积补，`kAssign/kSlice` 透传）；**结构相关性修正**——同源（追溯到同一寄存器）的输入不用乘积补，取 `max`，避免高估。
- **多精度策略**：层次 1 结构启发式 / 层次 2 静态概率 + 相关性修正（默认）/ 层次 3 profiling 迭代（长仿真）。

### 2.2 算法描述（`partitioning-algorithm.md`）

针对 `|V|~50M、|E|~100~200M` 的近线性局部增量算法：

- **数据结构**：原图 CSR（只读）；超图只存簇间聚合 `EdgeInfo{count, total_prob}`，邻居 key 是 supernode id；`node_to_supernode` 延迟更新（合并不立即重写内部成员，最后一次 `O(|V|)` 路径压缩）；候选用**桶队列**（按增益分桶，`O(1)` 取）。
- **阶段一**：一次正向拓扑 + 概率传播（源代表追踪做相关性修正）+ 高活跃连通分量识别。
- **阶段二**：**MFFC 线性近似种子**——反向拓扑一遍，`rep[u]`：sink 自成根；所有 fanout 同 `rep` 则继承；否则 `rep=NONE`（分割点）。按 `rep` 分组成初始 supernode，天然无环、`η=1`。
- **阶段三**：贪心粗化，候选只来自**共享前驱的兄弟**（搜索 `Σ_P |out(P)|²`，远小于 `|P|²`）；**三层无环检查**（直接边 `O(1)` / 拓扑区间 `[min,max]` `O(1)` / 限深 BFS `O(b^d)`，允许少量误判后期修复）；增益 `Δ = Saved - Increased - ΔC_check`，只读边界聚合；高活跃簇放宽 `φ`、增益阈值降为 0。
- **阶段四**：精修，只移动边界节点到直接邻居簇，局部增益 + 无环校验，固定 3~5 轮。
- **收尾**：并查集路径压缩重命名、超图拓扑序、按超节点 emit。
- **误判处理**：限深 BFS 可能让超图出环，粗化后做一次全局 Kahn（此时 `|P|` 已小），检测到环回滚导致环的那次合并。

---

## 3. 与当前实现的逐项差距

| v2 概念 | 当前实现状态 | 升级动作 | 落点 |
| --- | --- | --- | --- |
| `π(v)` 静态概率传播 | **不存在** | 新增传播 pass，挂在 `buildActivityOpData` 拓扑之后 | Phase A |
| 源代表 / 相关性修正 | 不存在 | 概率传播时维护 source representative | Phase A |
| `w(v)=nodeCost·bitwidth` | 仅 op 计数 / 跨边重数 | 新增节点成本表，**类别**对齐 [`NO0190`](./NO0190_grhsim_gsim_unified_cost_model_comp_src_sink_plan_20260612.md) comp/src/sink/const；系数为占位常量、实现后扫描微调（不沿用已失效的回归 `c_*`） | Phase B |
| 超图聚合 `EdgeInfo{count,total_prob}` | `valueEdges.weights` 只有 count | 扩展为带 `total_prob`、`W`、`change_weight`、`footprint`、`[min,max]topo`、`active_prob` 缓存 | Phase C |
| MFFC 种子 | **已由 computeNode builder 实现**：反向建树（唯一 consumer 吸收 + reconvergent + common-expr 独立）= MFFC 线性近似，与种子同粒度 | 不新增 `rep[u]` pass；**目标 `η→1`，允许修改 builder 构建方法**补齐 absorb 规则 | Phase D |
| 概率驱动增益粗化 | 三启发式 merge，无增益函数 | sibling-coalescing 候选 + 桶队列 + `Δ` 增益 | Phase E |
| 三层无环检查 | merge 内隐式保拓扑 + DisjointSet | 显式 直接边 / 拓扑区间 / 限深 BFS + 全局回滚 | Phase E |
| 内聚 / 权重 / footprint 约束 | 仅 `maxOps` | 粗化停止条件加 `φ_min`/`W_max`/`F_max`（`F_max`=宿主 x86 L1D） | Phase E |
| 概率加权 DP 代价 | `cutCost = 跨边条数` | `cutCost = Σ p(e)·W(succ)`（首版 `f` 由静态 `P(激活)` 估计，不回灌） | Phase F |
| FM 边界精修（草案阶段四） | `refineSegments`（`:2121`）**已写但未接线**；compute-node DP 后直接 flatten，无精修 | 复活/重写为概率增益 FM：移动边界 computeNode，保无环 + `φ/W/F` | Phase G |
| 分支预测感知 `C_check` | 不存在 | 增益 `ΔC_check` 项按 `P(激活)` 分段 | Phase E/F |
| profiling 迭代（层次 3） | `EMU_RUNTIME_PROFILE`/TSV 已有 `f[i]` | **暂缓**：首版只用层次 2 静态概率（2026-06-25 决策） | Phase H（暂缓） |
| 高活跃区域加速 | 不存在 | 阶段一识别 + 粗化放宽约束 | Phase E |

---

## 4. 升级总体策略

把划分决策层抽象成一个可替换的 **PartitionPolicy**，挂在 computeNode DAG 建好之后、最终 materialize 之前（即 `materializeComputeNodeSchedule` `:6417` 内的 coarsen+DP 段）：

```
buildComputeNodeRewrite (:5937)          ← computeNode builder = MFFC 种子层（NO0070 已实现）
        │  computeNode DAG（= MFFC 反链，天然无环）
        ▼
materializeComputeNodeSchedule (:6417)
   ├─ [现状] plain coarsen (out1/in1/siblings) + edge-cut DP   ← 默认保留
   └─ [新增] ProbabilityPartitionPolicy                        ← 本文，门控开启
            ├─ A 概率传播 π（在 buildActivityOpData 后、建树前，op 层）
            ├─ B 节点成本 w(v)（类别对齐 NO0190；系数占位待扫描）
            ├─ C 超图聚合（以 computeNode=MFFC 为节点：EdgeInfo+/active_prob）
            ├─ D MFFC 校验（η 覆盖率；computeNode 即种子，不新增 rep[u] pass）
            ├─ E 概率驱动粗化（合并 MFFC 种子：增益+三层无环+φ/W/F）
            ├─ F 概率加权 DP 分段
            └─ G FM 边界精修（概率增益移动边界 computeNode，保无环+φ/W/F）
        │  computeSupernode 划分
        ▼
materializeFinalPartition (:2622)        ← 不变
```

注：MFFC 种子（D）与 computeNode（builder）是**同一粒度**，不是叠加的两层——所以 A/B 在 op 层先行，D 只校验 builder 的种子是否忠实 MFFC，真正的概率算法落在 E（合并种子）、F（DP）与 G（FM 精修）。

新增开关（`ActivityScheduleOptions`，`activity_schedule.hpp:31`）：

```cpp
std::string partitionPolicy = "plain";   // "plain" | "prob"
// 以下数值全是占位默认，实现后由参数扫描标定（§9.1），不要当作已确认口径
double piDataInput = 0.1, piRegRead = 0.2, piHighThreshold = 0.9;  // 层次 2 静态先验
double phiMin = 0.6;                      // 内聚度下限
std::size_t footprintMaxBytes = 32 * 1024;  // 宿主 x86 L1D 容量假设，按目标机标定
double cBpMiss = 8.0;                     // 分支预测失误惩罚（相对 C_check_fast）
std::size_t fmRefineMaxRounds = 4;        // Phase G FM 边界精修轮数（prob 路径生效）
// 层次 3 runtime profiling 回灌：首版不实现（2026-06-25 决策），故无 runtimeProfileJson
```

默认 `partitionPolicy="plain"` 时行为与今天**逐字节一致**（这是回归安全的基准）。

---

## 5. 分阶段实施

### Phase A：静态概率传播基础设施

- 在 `buildActivityOpData`（`:1047`，已产出 `topoOps`/`topoEdges`/`topoKinds`）之后增加一次正向遍历，按草案 §7.2 规则填 `pi[op]`（`std::vector<float>`，长度 = topo 节点数）。
- 源先验按 `classifyActivityOp`（`:3120`）：`kConstant=0`、`kRegisterReadPort/kLatchReadPort=piRegRead`、`kMemoryReadPort` 走地址传播、graph input 时钟=1.0 / 数据=piDataInput。
- **相关性修正**：每个节点维护 source representative（单前驱继承、多源标记 multi）；两输入同源时用 `max(π)` 替乘积补（草案 §7.3 简化实现）。
- 复杂度 `O(|V|+|E|)` 一遍；导出 `pi_histogram`、`high_activity_nodes`、`multi_source_nodes` 统计。
- **单测**：`kMux` sel 高概率→输出≈1；同寄存器两切片拼接不翻倍；常量链恒 0。

### Phase B：节点成本模型 `w(v)`（类别对齐 NO0190，系数占位待扫描）

- 新增 `nodeCost(OperationKind)` 表，**类别**与 [`NO0190`](./NO0190_grhsim_gsim_unified_cost_model_comp_src_sink_plan_20260612.md) §2/§3 完全一致：comp（ALU/mux/slice/concat）/ src（reg/mem/latch 读）/ sink（不进 compute 划分）/ const。`w(v) = c_class·bitwidth(v)`。
- **系数不继承 NO0190 回归值**：2026-06-25 决策判定之前那批 `c_*` 回归无效，不引用。`c_class` 先用一组占位常量（量级参考草案附录：comp=1、src 高于 comp、const 轻量物化），实现后由参数扫描（§9.1）确定。
- **关键**：内存读在 [`NO0190`](./NO0190_grhsim_gsim_unified_cost_model_comp_src_sink_plan_20260612.md) §3 归 src，本文 `w(v)` 同步，避免划分把 `kMemoryReadPort` 当廉价 comp。
- footprint：`Σ bitwidth·B_logic`（2-state=1 / 4-state=2），用于 `F_max` 约束；**`F_max` 取宿主 x86 L1D**（仿真器执行机器的 L1 数据缓存），非被仿真 XiangShan 的 cache。

### Phase C：超图聚合结构

- 在 computeNode 簇层（`NodeClusterView`，`:5017`）每簇维护：`W`、`change_weight=Σ w·π`、`footprint`、`active_prob`（缓存，失效重算）、`[min_topo,max_topo]`、`in/out EdgeInfo{count,total_prob}`（key=邻居簇 id）。
- 复用现有 `valueEdges`（`:4558`）的 packed-pair 聚合，只把 `weights`(count) 扩成 `{count, total_prob}`。
- 合并时 `O(boundary)` 增量更新（草案 §5.4）；`node_to_supernode` 延迟到收尾路径压缩（现有 `DisjointSet` `:1002` 可直接承载）。

### Phase D：MFFC 种子对齐（computeNode builder 即种子层，不新增聚合 pass）

**结论：草案的「MFFC 种子」与现有 computeNode 是同一粒度，不是可叠加的两层。** `buildComputeNodeRewrite`（`:5937`）的反向建树——唯一 consumer 吸收、reconvergent（同一 computeNode 内多 operand 使用不算 shared boundary，[`NO0070`](./NO0070_grhsim_activity_schedule_computenode_rewrite_plan_20260505.md) §4）、common-expr 独立——就是草案 §4.1 `rep[u]` 线性近似 MFFC 的生产级实现，且额外正确处理 source clone / `kMemoryReadPort` / sink 边界 / intent 组，这些是裸 `rep[u]` 不覆盖的。

因此本阶段：

- **不**在 computeNode DAG 之上再加一遍 `rep[u]`：那要么是 no-op，要么本质是 coarsen（属于 Phase E），正是本计划早期草案把「建种子」与「合并种子」混淆之处。
- 把草案 `rep[u]` 当作**规范 / 校验 oracle**：新增 `mffc_coverage_eta` 统计，验证 computeNode 是否忠实 MFFC（`η→1`）。
- 若 `η<1`（builder absorb 规则缺陷，如本应 reconvergent 吸收却误判 boundary），**直接修改 `buildComputeNodeRewrite` 的构建方法**补齐规则直到忠实 MFFC（2026-06-25 决策：必须保证 computeNode 对 MFFC 忠实，构建方法可改），而非叠加第二遍 pass。
- reg-to-mem intent 组（indivisible，`:5950`）整体作为一个不可拆 MFFC 种子。

> 范围界定：本阶段**允许并预期修改 `buildComputeNodeRewrite` 的 absorb 规则**以保证忠实 MFFC；但不主张用裸 `rep[u]` 整体**替换** builder——那会丢掉 [`NO0070`](./NO0070_grhsim_activity_schedule_computenode_rewrite_plan_20260505.md) 围绕 source clone / sink / intent 的正确性机器（裸 `rep[u]` 对这些一无所知）。即：**改规则可以，弃 builder 不可**。

### Phase E：概率驱动贪心粗化

- **候选生成**：保留并升级 `tryMergeNodeSiblings`（`:5403`，已按前驱 hash 分桶）为「共享前驱兄弟」主候选源；out1/in1（`:5509/:5603`）作为链式补充。每簇候选数封顶（草案 §5.1，top-k）。
- **增益**：`Δ = Saved - Increased - ΔC_check`（草案 §5.3），全部只读边界聚合（Phase C）。`ΔC_check` 按合并后 `active_prob` 落在 `[0.2,0.8]` 与否加 `cBpMiss`（草案 §4.4）。
- **桶队列**：按 `Δ` 分桶 `O(1)` 取，邻居合并使增益失效则出桶重算。
- **三层无环检查**（草案 §5.2）：直接边 → 拓扑区间 `[min,max]` → 限深 BFS（`d=2~3`）；允许误判，粗化后一次全局 Kahn 检测环并回滚（草案 §9.4）。
- **停止条件**：无正增益 / `φ(S_c)<φ_min` / `W>W_max` / `footprint>F_max` / `|P|` 达目标（草案 §5.5）。
- **高活跃加速**（草案 §5.6）：`H` 簇放宽 `φ_min`、增益阈值=0。
- **复杂度红线**：候选只在局部邻居，禁止全图重扫；每轮输出 timing 与簇数 delta（沿用 `ComputeNodeMaterializePerfStats` `:652`，tail-stop 阈值 `:987`）。

### Phase F：概率加权 DP 分段

- `buildDpSegments`（`:1980`）/`buildComputeSupernodeSegments`（`:5697`）的 `cutCost` 从「后继边条数」改为 `Σ_{跨段后继} p(e)·W(succ)`（草案 §4.3），段内边不计（现有逻辑已减内部边）。
- 频率项 `f` 首版用**静态** `P(succ 激活)` 作代理（上式 `p(e)` 已隐含静态激活概率），**不**接 runtime profiling 回灌（2026-06-25 决策）；与 [`NO0190`](./NO0190_grhsim_gsim_unified_cost_model_comp_src_sink_plan_20260612.md) 的 `T` 同结构，差别只在 `f` 是静态估计而非实测。
- 保留 `maxOpInComputeSupernode` cap 与 `sinkOnly`/`fixedBoundary` 不混约束（[`NO0185`](./NO0185_xs_components_aligned_coarsen_strategy_20260523.md)：coarsen 不看 cap、DP 看 cap，**不变**）。

### Phase G：FM 边界精修（概率增益，草案阶段四）

DP（Phase F）给出按 cap 切分的 computeSupernode 后，做 Fiduccia-Mattheyses 风格的边界精修（草案 problem-v2 §9 / algorithm §6 阶段四）。**当前 compute-node 路径 DP 后直接 `flattenNodeSegments`，无精修**；代码里的 `refineSegments`（`:2121`）是按 edge-cut 写的、且**未接线的 dead code**——本阶段复活并重写它，接到 `buildComputeSupernodeSegments`（`:6630`）之后。

- **移动单位**：边界 computeNode（有跨 supernode 边的 computeNode），整体移动到**直接邻居 supernode**；不拆 computeNode 内部 op（保持 MFFC 种子完整，[`NO0070`](./NO0070_grhsim_activity_schedule_computenode_rewrite_plan_20260505.md)：computeNode 是移动/计数单位）；内部 computeNode 不动。
- **增益**：移动 `v: S_a→S_b` 的净增益只看 `v` 的邻接边——`S_a` 内变跨边的 `p(e)·W` 增量 vs `S_b` 内变内部边的 `p(e)·W` 减量，复用 Phase B 的 `w`/`π` 与 Phase C 的边界聚合，`O(deg(v))`。
- **约束**：移动后仍须 ① 超图无环（拓扑区间快速校验，草案 §6.3）；② `φ_min`/`W_max`/`F_max` 不破。
- **停止**：固定 3~5 轮（`fmRefineMaxRounds`）；每轮按增益排序，单个 computeNode 单轮只移一次；单轮移动数 < 边界 computeNode 总数 1% 则停（草案 §6.4）。
- **门控/基准**：受 `partitionPolicy="prob"` 控制；因 `refineSegments` 现未接线、plain 路径本就无精修，默认 plain 仍逐字节一致。
- **连续性不是要求（已核实 2026-06-25）**：`flattenNodeSegments`（`:5811`）对每个 supernode 的 op 按全局 `nodeTopoPos` 重排，final materialize 的 `build.topoOrder = topoOrderForDag(build.dag)`（`:6948`）由**真实 quotient DAG** 算执行序——二者**都不要求 supernode 为连续 topo 区间**，FM 打散连续性不影响物化正确性。连续性只长在生产端 `buildComputeSupernodeSegments`（`:5697`，1-D 连续分段 DP），是产出性质而非消费要求。
- **唯一硬约束是 quotient 无环**（problem-v2 约束1）：连续段时无环免费，FM 一旦打散就必须**自己在每次 move 上保无环**（拓扑区间校验，草案 §6.3）。final materialize 的 `topoOrder.size() != supernodeToOps.size()`（`:6960`，Kahn 检出环后）是**硬报错 backstop**、非静默修复，FM 不得依赖它兜底，须前置拒绝成环 move。
- **FM 落地形式**：改 cluster→supernode 归属 → 重建每 supernode 成员表 → 复用现有 `flattenNodeSegments`（本就接受任意成员集合），无需新物化路径。
- **复杂度红线**：只动边界、局部增益，禁止全图重扫；每轮输出移动数与 timing。

### Phase H：profiling 迭代（层次 3）——首版暂缓

**2026-06-25 决策：首版不做 runtime profiling 概率回灌。** 整条流水线只用层次 2 静态概率（Phase A）。本节保留为后续可选方向，不在首版实现范围内：

- 待层次 2 在 50k gate 上证明结构/runtime 收益后，再评估是否值得引入回灌。
- 届时可借 [`NO0189`](./NO0189_grhsim_gsim_supernode_cost_tsv_instrument_plan_20260611.md)/[`NO0190`](./NO0190_grhsim_gsim_unified_cost_model_comp_src_sink_plan_20260612.md) 已有的 per-supernode `f[i]`/`a_succ[i]` TSV，把经验频率 `π̂(v)=n̂/N` 覆盖静态先验、重划分重编译一次；收敛性（一次是否够、多次是否值回编译开销）另行评估。

### Phase I：门控、统计与验收

- 新增 `partition_policy`、`pi_*`、`phi`、`footprint`、`mffc_coverage_eta`、`high_activity_gamma`、`coactivation_merges`、`fm_refine_moves` 等统计列，进 `activity_schedule_supernode_stats.json`。
- 复用 `tools/grhsim_opt_metrics.py` 的 gate（`c2-alias-off` 之外新增 `prob-partition` 结构 gate）与 `xs-components` matrix、`coremark50k-fast` runtime gate（[`NO0184`](./NO0184_coremark50k_runtime_gate_20260521.md)）。

---

## 6. 风险与权衡

1. **Union-Bound 在 `p→1` 失真**（草案 §4.3 自带警示）：时钟驱动组合逻辑概率接近 1。落地时高活跃区域（`π≥π_high`）必须走精确式 `1-Π(1-p)` 或直接进高活跃合并路径，**不**用 union-bound 估其激活概率。
2. **概率先验不确定**：`π_data/π_reg` 是猜的占位值。首版不靠 profiling 纠正（层次 3 暂缓），故层次 2 只用于**相对排序**（合并谁先），绝对标定靠实现后参数扫描（§9.1）；不要在没 gate 前就声称收益。
3. **50M 规模卡死复发**：[`NO0185`](./NO0185_xs_components_aligned_coarsen_strategy_20260523.md) 的 `final_materialize` 长时间无输出是真实历史。Phase C 的延迟更新 + Phase E 的局部候选 + 桶队列是直接对策，但每阶段必须有 timing 日志，先在 `xs-components` 与单组件上验证近线性，再放 full XiangShan。
4. **限深 BFS 误判**：可能让超图出环；依赖粗化后全局 Kahn 回滚（草案 §9.4）。回滚次数须统计，过多说明 `d` 太小。
5. **与 [`NO0206`](./NO0206_commit_activation_mask_group_plan_20260624.md) 正交**：本文只动 compute 侧划分，commit 侧 `a_succ` 分组独立推进，两者在 `value_fanout` 边界对齐即可，互不阻塞。
6. **系数全为占位**：[`NO0190`](./NO0190_grhsim_gsim_unified_cost_model_comp_src_sink_plan_20260612.md) 先前回归出的 `c_*` 已判无效、不引用（2026-06-25 决策）。所有成本/概率/约束数值都是占位常量，靠实现后参数扫描标定（§9.1）；划分对系数比例的敏感度需在扫描中观察，标定前不得据其下结论。

---

## 7. 验收指标

**结构（xs-components matrix，先行）**
- `XsPlruLarge` 等 case 的 `compute_supernodes` 与 GSIM 对齐（参照 [`NO0185`](./NO0185_xs_components_aligned_coarsen_strategy_20260523.md)：3 vs 3）。
- `mffc_coverage_eta` 接近 1；`boundary_activation_edges` 不高于 plain coarsen。
- `partition_policy="plain"` 时输出与今天逐字节一致（回归基准）。

**规模（full XiangShan）**
- `activity-schedule` 在 `compute_nodes≈6.6M` 规模下不再出现 `final_materialize` 长时间无输出，全程有 timing；总耗时不劣于 [`NO0185`](./NO0185_xs_components_aligned_coarsen_strategy_20260523.md) 的 `~277118ms`。

**Runtime（CoreMark 50k，带 difftest）**
- 相对 [`NO0198`](./NO0198_xiangshan_coremark50k_runtime_profile_no_preserve_20260615.md) 基线（`grhsim 351.592s`、gap `7.33x`）有可测量改善，且功能不回退（`run_xs_wolf_grhsim_emu` 对齐）。
- 经 `tools/grhsim_opt_metrics.py --gate coremark50k-fast` 机判通过。

---

## 8. 明确不做（边界）

- 不改 emitter 两阶段不动点（[`NO0070`](./NO0070_grhsim_activity_schedule_computenode_rewrite_plan_20260505.md) §9）。
- 不改 commit / sink 聚类与 `maxOpInCommitSupernode`（commit 侧归 [`NO0206`](./NO0206_commit_activation_mask_group_plan_20260624.md)）。
- 不动 source clone 语义（`cloneSourceUsesForCompute` `:3256`）与 reg-to-mem intent 不可拆约束。
- 不引入复杂全局表达式等价分析（[`NO0070`](./NO0070_grhsim_activity_schedule_computenode_rewrite_plan_20260505.md) 复杂度红线）。
- 默认 `partitionPolicy` 不切到 `"prob"`，直到 50k gate 证明收益。
- 首版不做 runtime profiling 概率回灌（层次 3，Phase H 暂缓）；只用静态层次 2 概率。

---

## 9. 决策与待定

### 9.1 已决策（2026-06-25，用户答复）

1. **不引用旧 `c_*` 回归系数**：[`NO0190`](./NO0190_grhsim_gsim_unified_cost_model_comp_src_sink_plan_20260612.md) 先前回归出的 `c_*` 判定无效。`w(v)` 只沿用其**类别划分**（comp/src/sink/const），单位成本作为占位常量，由下面第 3 条的参数扫描标定。
2. **必须保证 computeNode 忠实 MFFC，可改构建方法**：目标 `mffc_coverage_eta→1`；若现 builder absorb 规则导致 `η<1`，**直接修改 `buildComputeNodeRewrite`**（不叠加第二遍 `rep[u]`，也不弃用 builder）。
3. **所有数值参数留待实现后扫描微调**：概率先验、`φ_min`、`W_max`、`F_max`、`c_class`、`cBpMiss` 现在都无法确认，需在实现后扫描并据 gate 微调；本文给的全是占位量级。
4. **`F_max`/footprint 按宿主 x86 标定**：仿真器跑在 x86 机器上，约束的是**宿主 CPU 的 L1 数据缓存**（让单个 supernode 的读写工作集落在 host L1D），与被仿真的 XiangShan 自身 cache 无关；具体容量按目标开发机标定。
5. **首版不做 runtime profiling 概率回灌**（层次 3，Phase H 暂缓）：只用层次 2 静态概率；待 50k gate 证明收益后再评估回灌。

### 9.2 仍待定（实现期回答）

1. 占位概率/成本量级能否在 `xs-components` 上得到与 GSIM 对齐的结构（先于扫描的 sanity check）。
2. `mffc_coverage_eta` 实测值；若 `η<1`，缺口具体来自哪条 absorb 规则（reconvergent 误判 / cap 截断 / source clone 边界）。
3. 高活跃区域识别的连通阈值与合并优先级具体取值。
4. 参数扫描的搜索空间与 gate 口径（哪些参数联动、以 50k runtime 还是结构指标为主目标）。

---

## 10. 关联文档

- 输入草案：`../../ptmp/new-partition-algo/partitioning-problem-v2.md`、`../../ptmp/new-partition-algo/partitioning-algorithm.md`
- 框架：[`NO0070`](./NO0070_grhsim_activity_schedule_computenode_rewrite_plan_20260505.md)
- 当前口径：[`NO0185`](./NO0185_xs_components_aligned_coarsen_strategy_20260523.md)、[`NO0093`](./NO0093_essent_mffc_activity_schedule_plan_20260518.md)
- 成本模型：[`NO0189`](./NO0189_grhsim_gsim_supernode_cost_tsv_instrument_plan_20260611.md)、[`NO0190`](./NO0190_grhsim_gsim_unified_cost_model_comp_src_sink_plan_20260612.md)
- 基线 / gate：[`NO0198`](./NO0198_xiangshan_coremark50k_runtime_profile_no_preserve_20260615.md)、[`NO0184`](./NO0184_coremark50k_runtime_gate_20260521.md)
- 正交方向：[`NO0206`](./NO0206_commit_activation_mask_group_plan_20260624.md)
