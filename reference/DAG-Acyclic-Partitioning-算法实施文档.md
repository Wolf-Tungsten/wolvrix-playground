# DAG 无环划分 — 多层算法实施文档

> **来源**：Herrmann, J., Özkaya, M.Y., Uçar, B., Kaya, K., & Çatalyürek, Ü.V. (2019). *Multilevel Algorithms for Acyclic Partitioning of Directed Acyclic Graphs*. SIAM Journal on Scientific Computing, 41(4), A2117-A2145. DOI: 10.1137/18M1176865

---

## 第一部分：总体架构（两个层次的组合）

本文的算法由**两个独立层次**组合而成，必须分开理解：

| 层次 | 名称 | 本质 | 调用次数 |
|------|------|------|----------|
| **层次一** | **多层框架**（Multilevel Scheme） | 一次完整的三阶段流程（粗化 → 初始划分 → 展开细化） | **单次调用**（处理一次二分） |
| **层次二** | **递归二分**（Recursive Bisection） | 多次调用层次一，每次对当前子图做一次二分 | **多次调用**（约 log₂(k) 轮） |

### 1.1 层次一：多层框架（单次三阶段）

对**一张输入图**做一次二分时，多层框架只执行一轮：

```
输入: 一张 DAG 子图 G_sub
输出: 该子图的无环二分 (V0, V1)

        ┌─────────────┐
        │  多层框架   │  ←── 只执行一次（单次三阶段）
        │  (单次)     │
        └──────┬──────┘
               │
    ┌──────────┼──────────┐
    ↓          ↓          ↓
┌───────┐  ┌───────┐  ┌───────────┐
│ 粗化  │→ │ 初始  │→ │ 展开+细化 │
│阶段   │  │ 划分  │  │ 阶段      │
│(Coars)│  │(Init) │  │(Uncoars+  │
│       │  │       │  │ Refine)   │
└───────┘  └───────┘  └───────────┘
    │          │          │
    ↓          ↓          ↓
 图变小     最粗图     图逐层展开
 (多层)    二分划分    同时细化质量
```

> **核心**：多层框架本身是**一次性的**——从输入图开始，一层层粗化到最简图，做一次初始划分，再一层层展开回去并细化。整个过程对**一次二分**只做一次。

### 1.2 层次二：递归二分（多次调用）

如果目标是要把图划分成 $k$ 块（$k > 2$），就**递归调用**多层框架：

```
举例：k = 4 的完整流程

Round 1 (对整张图 G):
  调用多层框架一次 → 得到 (V0, V1)
         │
    ┌────┴────┐
    ↓         ↓
Round 2 (对 V0):
  调用多层框架一次 → 得到 (V00, V01)
         │
    ┌────┴────┐
    ↓         ↓
Round 3 (对 V1):
  调用多层框架一次 → 得到 (V10, V11)

最终结果：{V00, V01, V10, V11}

编号规则：左子树所有分区编号 < 右子树所有分区编号
（保证全局无环性）
```

> **论文原文**："We focus on two-way partitioning (sometimes called bisection), as this scheme can be used in a recursive way for multiway partitioning." — Introduction
>
> "We discuss only the bisection case, as we were able to improve the direct k-way algorithms we proposed before [15] by using the bisection heuristics recursively." — Introduction
>
> "We focus on partitioning the graph in two parts since we can handle the general case with a recursive bisection scheme." — Section 4

实验部分验证了 $k \in \{2, 4, 8, 16, 32\}$ 的递归二分效果，论文明确指出递归 bisection 优于先前工作中的 direct k-way 算法。

### 1.3 问题定义（DAGP）

**输入**：有向无环图 $G = (V, E)$，顶点权重 $w_u$，边成本 $c_{u,v}$，分区数 $k$，不平衡参数 $\varepsilon$。

**输出**：$k$-way 划分 $P = \{V_1, V_2, ..., V_k\}$。

**约束**：
1. **平衡约束**：$w(V_i) \leq (1+\varepsilon) \cdot \frac{\sum_{v \in V} w_v}{k}$
2. **无环约束**：存在一种编号方式，使得所有跨区边都从编号较小的分区指向编号较大的分区。即：对所有 $i < j$，不存在从 $V_j$ 到 $V_i$ 的边。

**目标**：最小化 edge cut（跨分区边的总权重）。

> **关键性质**：DAGP 是 NP-完全问题，且对 $k \geq 3$ 不存在常数因子近似算法。

### 1.4 术语定义

- **V**：DAG 的顶点集合（vertices）。
- **E**：DAG 的有向边集合（edges），$E = \{(u, v) \mid u, v \in V \text{ 且存在从 } u \text{ 指向 } v \text{ 的有向边}\}$。
- **source（源点）**：入度为 0 的顶点，即不存在任何入边 $(u, v) \in E$ 的顶点 $v$。在 DAG 中至少存在一个 source。
- **sink（汇点）**：出度为 0 的顶点，即不存在任何出边 $(v, u) \in E$ 的顶点 $v$。
- **predecessor（前驱）**：$Pred[v] = \{u \mid (u, v) \in E\}$，即存在直接入边指向 $v$ 的顶点集合。
- **successor（后继）**：$Succ[v] = \{u \mid (v, u) \in E\}$，即存在直接出边从 $v$ 出发的顶点集合。
- **ancestor（祖先）**：存在从某顶点到 $v$ 的有向路径的所有顶点。
- **descendant（后代）**：存在从 $v$ 到某顶点的有向路径的所有顶点。
- **top-level**：从任意 source 到该顶点的最长路径长度。

以下描述的是**一次多层框架**的内部流程。对于递归二分的每一轮，都要完整执行一次这个三阶段流程。

### 2.1 阶段一：粗化（Coarsening）

**目标**：将输入图逐层缩小，每层得到更小的 DAG，同时保持无环性。

**停止条件**：顶点数小于阈值（如 100）或每层缩减率小于阈值（如 1.1）。

#### 2.1.1 理论基础

本节所有讨论基于输入 DAG $G = (V, E)$，其中 $V$ 为顶点集合，$E$ 为有向边集合。

**定义（Top-level value）**：
$$top[u] = \text{从任意 source 到 } u \text{ 的最长路径长度}$$
- source 顶点的 $top = 0$
- 可在 $O(|V| + |E|)$ 内通过一次拓扑遍历计算
- 与所用的拓扑排序无关

**定理 4.1（可收缩边判定）**：
对于边 $(u,v) \in E$，将 $u$ 和 $v$ 收缩为单个顶点不产生环 **当且仅当** $G$ 中不存在不经过 $(u,v)$ 的 $u \leadsto v$ 路径。

**定理 4.2（可行聚类的充分条件）**：
设聚类 $C = \{C_1, ..., C_k\}$，若满足：
1. 对任意聚类 $C_i$ 内所有 $u, v$：$|top[u] - top[v]| \leq 1$
2. 对两个不同聚类 $C_i$ 和 $C_j$，对所有 $u \in C_i, v \in C_j$：
   - 要么 $(u,v) \notin E$，
   - 要么 $top[u] \neq top[v] - 1$

则收缩所有聚类后的粗化图保持无环。

> 条件1将聚类内顶点的 top-level 差异限制在1以内；条件2禁止某些跨聚类有向边，防止同时收缩多个聚类时形成环。

#### 2.1.2 算法 1：基于禁止边的聚类（CoTop）

**核心思想**：利用定理 4.2 的两个条件，通过维护"坏邻居计数"，在 $O(|V|+|E|)$ 内判断顶点能否加入某个聚类，无需显式环检测。

**数据结构**：
- `leader[u]`：顶点 $u$ 所在聚类的代表（初始为 $u$）
- `mark[u]`：标记 $u$ 是否已加入**非单例聚类**（即包含至少两个顶点的聚类；初始时每个顶点各自成单例聚类，合并后变为非单例）
- `weight[leader]`：聚类总权重
- `nbadnbrs[u]`：$u$ 的"坏邻居聚类"数量（违反定理 4.2 条件2的邻居聚类）
- `leaderbadnbrs[u]`：第一个坏邻居聚类的 leader（初始为 -1）

**算法流程**：

```
Algorithm 1: Clustering with forbidden edges (CoTop)
─────────────────────────────────────────────────
Input: DAG G=(V,E), 遍历顺序, 边优先级
Output: leader[] 数组

1. top[] ← CompTopLevels(G)          // O(|V|+|E|)

2. 初始化：
   对每个 u ∈ V：
     mark[u] ← false
     leader[u] ← u
     weight[u] ← w_u
     nbadnbrs[u] ← 0
     leaderbadnbrs[u] ← -1

3. 按遍历顺序处理每个顶点 u：
   若 mark[u] = true，跳过（u 已属于某个非单例聚类，不再处理）
   
   N ← ValidNeighbors(u, nbadnbrs, leaderbadnbrs, weight)
   // 选择满足以下条件的邻居聚类：
   //   (a) |top[u] - top[v]| ≤ 1（定理 4.2 条件1）
   //   (b) nbadnbrs[u] ≤ 1 且所有坏邻居在同一聚类（定理 4.2 条件2）
   //   (c) 目标聚类权重 + w_u ≤ 图总权重的 10%
   
   若 N = ∅，跳过（保持单例）
   
   BestNeigh ← BestNeighbor(N)       // 按边成本等优先级选择最佳邻居
   ℓ ← leader[BestNeigh]
   leader[u] ← ℓ
   weight[ℓ] ← weight[ℓ] + w_u
   
   // 更新邻居的坏邻居信息（u 加入新聚类后）
   对 v ∈ Neigh[u]：
     若 |top[u] - top[v]| > 1，跳过    // u 不可能成为 v 的坏邻居
     若 nbadnbrs[v] = 0：
       nbadnbrs[v] ← 1
       leaderbadnbrs[v] ← ℓ
     否则若 nbadnbrs[v] = 1 且 leaderbadnbrs[v] ≠ ℓ：
       nbadnbrs[v] ← 2       // v 有两个坏邻居聚类，不能再移动
   
   // 若 BestNeigh 原先是单例，更新其邻居
   若 mark[BestNeigh] = false：
     对 v ∈ Neigh[BestNeigh]：
       类似更新 nbadnbrs 和 leaderbadnbrs
   
   mark[BestNeigh] ← true
   mark[u] ← true

4. 返回 leader[]
```

**复杂度**：$O(|V| + |E|)$

**关键机制**：
- `nbadnbrs[v] = 2` 意味着 $v$ 有两个不同聚类的坏邻居，如果 $v$ 加入任一聚类都会违反定理 4.2 条件2，因此 $v$ 必须保持单例。

#### 2.1.3 算法 2：基于环检测的聚类（CoCyc）

**核心思想**：比 CoTop 更宽松，允许某些边界情况的聚类，但显式运行环检测来验证安全性。

**算法流程**：

```
Algorithm 2: Clustering with cycle detection (CoCyc)
─────────────────────────────────────────────────
Input: DAG G=(V,E), 遍历顺序, 边优先级
Output: leader[] 数组

1. top[] ← CompTopLevels(G)

2. 初始化：
   对每个 u ∈ V：
     markup_up[u] ← false      // u 是否在 top-level=t 的聚类中
     markup_down[u] ← false    // u 是否在 top-level=t+1 的聚类中
     leader[u] ← u

3. 按遍历顺序处理每个顶点 u：
   若 markup_up[u] 或 markup_down[u] 为 true，跳过
   
   对 v ∈ Neigh[u]（按边优先级）：
     若 |top[u] - top[v]| > 1，跳过
     
     若 v 是 u 的 successor (v ∈ Succ[u])：
       若 markup_up[v]，继续
       若 DetectCycle(u, v, G, leader) 返回 true，继续
       leader[u] ← leader[v]
       markup_up[u] ← true
       markup_down[v] ← true
       break
     
     若 v 是 u 的 predecessor (v ∈ Pred[u])：
       若 markup_down[v]，继续
       若 DetectCycle(u, v, G, leader) 返回 true，继续
       leader[u] ← leader[v]
       markup_down[u] ← true
       markup_up[v] ← true
       break

4. 返回 leader[]
```

**DetectCycle 函数**：
当考虑将 $u$ 加入 $v$ 的聚类 $C$（$C$ 包含 top-level 为 $t$ 和 $t+1$ 的顶点）时：
1. 从 $u$ 开始进行 BFS/DFS
2. 只遍历 top-level 与 $t$ 或 $t+1$ 差异 $\leq 1$ 的顶点
3. 若到达 $C$ 中已有顶点，说明收缩后会形成环，返回 true
4. 否则返回 false

> 从定理 4.2 的证明可知，如果加入 $u$ 会形成环，该环只经过 top-level 为 $t$ 或 $t+1$ 的顶点，因此搜索范围受限。

**复杂度**：最坏 $O(|V|(|V|+|E|))$，实际中接近 $O(|V|+|E|)$。

#### 2.1.4 混合粗化算法（CoHyb）

**核心思想**：结合 CoTop 和 CoCyc 的优点，避免 CoCyc 在大度顶点上的高开销。

**策略**：
- 定义"大度顶点"阈值：$\sqrt{|V|}/10$
- 当顶点 $u$ 和 $v$ 的度数都不超过阈值时：使用 CoCyc（环检测）
- 当 $u$ 或 $v$ 的度数超过阈值时：使用 CoTop（禁止边）

**复杂度**：介于 CoTop 和 CoCyc 之间，实践中接近线性。

> **实验结论**：CoHyb 是默认推荐的粗化算法，在 edge cut 和运行时间之间取得最佳平衡。

### 2.2 阶段二：初始划分（Initial Partitioning）

对**最粗图**（粗化停止后的最小图）进行无环 bisection。有两种方法。

#### 2.2.1 贪婪有向图增长（Greedy Directed Graph Growing）

**核心思想**：模拟标准 GP 中的 greedy graph growing，但严格保持无环性。分两阶段推进。

**算法流程**：

```
算法：Greedy Directed Graph Growing
──────────────────────────────────
Input: 最粗 DAG G=(V,E)
Output: 无环 bisection (V0, V1)

// 方向1：从 sources 开始，向 V0 填充
1. 所有顶点初始放入 V1
2. 堆 H ← 所有 source 顶点（入度为0）
   key(v) = 入边权重和（第一阶段）
   
3. 第一阶段：
   while |V0| < 0.9 × max_allowed_weight：
     v ← ExtractMax(H)
     将 v 移入 V0
     对 v 的每个 successor u：
       若 u 的所有 predecessor 都在 V0：
         将 u 插入 H
         
4. 第二阶段：
   key(v) = 入边权重和 - 出边权重和（实际增益）
   while 未达到平衡约束：
     v ← ExtractMax(H)
     将 v 移入 V0
     更新 H 中相关顶点

// 方向2：反向运行（从 sinks 开始，向 V1 填充）
5. 将上述过程反向：所有顶点放入 V0，向 V1 移动 sinks
   条件变为：successor 全在 V1 才能移动
   key 计算也反向（出边 - 入边）

6. 返回方向1和方向2中 edge cut 更优的结果
```

**关键点**：
- 顶点只有在所有 predecessor（或 successor）都进入目标分区后才可移动，这**天然保证无环性**
- 两阶段策略：先用入边权重快速填充（灵活性优先），再用实际增益精细调整（质量优先）
- 尝试两个方向（sources→V0 和 sinks→V1）并取更优者

#### 2.2.2 无向划分 + 无环性修复（UndirFix）

**核心思想**：利用成熟的无向图划分器（如 MeTiS）获得高质量划分，再修复无环性。

**算法 3：fixAcyclicityUp**
```
Input: G=(V,E), 划分 part[]
Output: 无环划分

按逆拓扑序遍历 u：
  若 part[u] = 0：
    对 v ∈ Pred[u]：
      part[v] ← 0    // 将 u 的所有 ancestor 强制放入 V0
返回 part
```

**算法 4：fixAcyclicityDown**
```
Input: G=(V,E), 划分 part[]
Output: 无环划分

按拓扑序遍历 u：
  若 part[u] = 1：
    对 v ∈ Succ[u]：
      part[v] ← 1    // 将 u 的所有 descendant 强制放入 V1
返回 part
```

**完整策略**：
1. 用无向图划分器（如 MeTiS）划分 DAG（忽略方向），得到 $(P_0, P_1)$
2. 尝试 4 种修复方式并取最优 edge cut：
   - 指定 $P_0=V_0, P_1=V_1$，用 fixAcyclicityUp
   - 指定 $P_0=V_0, P_1=V_1$，用 fixAcyclicityDown
   - 指定 $P_0=V_1, P_1=V_0$，用 fixAcyclicityUp
   - 指定 $P_0=V_1, P_1=V_0$，用 fixAcyclicityDown
3. 用 Boundary FM 细化（见阶段三）修复平衡性和 edge cut

> **实验数据**：
> - 仅 2/94 张图的无向划分天然无环
> - 修复后几何平均 normalized edge cut 为 0.0045（原始无向划分为 0.0012）
> - 平衡后 edge cut 为 0.0049
> - 结论：修复无环性使 cut 增加约 3.75 倍，但仍可控；获得平衡后增加极少

### 2.3 阶段三：展开与细化（Uncoarsening + Refinement）

**目标**：从粗化图开始，逐层将划分投影回更细的图，并在每层用局部搜索改进划分质量。最终回到原始图时得到最终划分。

#### 2.3.1 边界 FM 细化（Boundary FM Refinement）

**核心思想**：适应 Fiduccia-Mattheyses (FM) 算法到无环划分场景。这是无环划分的关键技术点。

**可移动性（Movability）定义**：
设当前无环 bisection 为 $(V_0, V_1)$，所有跨区边从 $V_0$ 指向 $V_1$。

- 顶点 $v \in V_0$ 可移至 $V_1$ **当且仅当**：
  - 所有 $v$ 的 successor 都在 $V_1$（或 $v$ 没有 successor）
- 顶点 $v \in V_1$ 可移至 $V_0$ **当且仅当**：
  - 所有 $v$ 的 predecessor 都在 $V_0$（或 $v$ 没有 predecessor）

> 这保证了移动后仍不存在从 $V_1$ 到 $V_0$ 的边。

**增益（Gain）计算**：
- 将 $v$ 从 $V_0$ 移至 $V_1$ 的增益：
$$gain(v) = \sum_{u \in Succ[v]} w(v,u) - \sum_{u \in Pred[v]} w(u,v)$$
- 反向移动（$V_1$ → $V_0$）的增益为上述值的负数

> **核心简化**：与标准 FM 不同，这里的增益是**静态的**！一旦顶点插入堆中，其增益无需更新。因为无环性约束保证了移动一个顶点不会影响其他顶点的跨区边计数（在边界意义上）。这极大地简化了实现——堆只需支持 insert, delete, extract-max，无需 decrease-key。

**算法流程**：

```
Algorithm: Boundary FM Refinement for Acyclic Bisection
─────────────────────────────────────────────────────
Input: 当前无环划分 (V0, V1)
Output: 改进后的划分

1. 计算每个顶点的同分区 successor/predecessor 计数：
   nSuccInSamePart[v] = |{u ∈ Succ[v] : u 与 v 同分区}|
   nPredInSamePart[v] = |{u ∈ Pred[v] : u 与 v 同分区}|
   
   可移动判定：
     v ∈ V0 可移动 ⇔ nSuccInSamePart[v] = 0
     v ∈ V1 可移动 ⇔ nPredInSamePart[v] = 0

2. 初始化两个最大堆：
   H0 ← V0 中所有可移动顶点，key = gain(v)
   H1 ← V1 中所有可移动顶点，key = gain(v)

3. 记录当前最佳划分和最佳 cut

4. 重复多轮 (pass)：
   a. 标记所有顶点为未移动
   b. 当 H0 或 H1 非空：
      i.   从 H0 和 H1 中选择增益最大的可移动顶点 v
      ii.  若移动 v 不违反平衡约束：
           将 v 移至另一分区
           标记 v 为已移动
           更新总 cut
           若当前 cut 为历史最佳，记录此划分前缀
      iii. 更新 v 的邻居的可移动状态：
           - 对 v 的每个 predecessor u：
             u 现在在另一分区有 successor → 更新 nSuccInSamePart[u]
             若 nSuccInSamePart[u] 从 1 变 0：u 变为可移动，插入 H0
             若 nSuccInSamePart[u] 从 0 变 1：u 变为不可移动，从 H0 删除
           - 对 v 的每个 successor u：
             类似更新 nPredInSamePart[u] 和 H1
   c. 回滚至最佳前缀划分

5. 返回最佳划分
```

#### 2.3.2 其他细化变体

- **边界 KL（Boundary Kernighan-Lin）**：基于顶点交换而非单向移动，适用于需要更大邻域搜索的场景
- **仅从最重分区移动**：用于非单位权重顶点，优先修复负载不平衡
- **推荐组合**：
  - 单位权重顶点：纯 Boundary FM
  - 非单位权重：1 pass Boundary KL + 1 pass Boundary FM（仅从最重分区移动）

---

## 第三部分：递归 k-way 的完整流程

### 3.1 算法流程

```
Algorithm: Recursive k-way DAG Partitioning
──────────────────────────────────────────
Input: DAG G=(V,E), 目标分区数 k, 不平衡参数 ε
Output: k-way 无环划分 P = {V_1, ..., V_k}

// 递归终止条件
1. 若 k == 1：
     返回 {V}

// 调用多层框架进行一次二分
2. (V0, V1) ← Multilevel_Bisection(G, ε)
   // 内部执行：
   //   粗化 → 初始划分 → 展开+细化（单次三阶段流程）

// 递归二分
3. k0 ← ⌊k/2⌋          // 左子树分区数
4. k1 ← k - k0           // 右子树分区数

5. 若 k0 > 1：
     P0 ← Recursive_k-way(V0, k0, ε)
   否则：
     P0 ← {V0}

6. 若 k1 > 1：
     P1 ← Recursive_k-way(V1, k1, ε)
   否则：
     P1 ← {V1}

7. 编号规则：
   P0 中的所有分区编号 < P1 中的所有分区编号
   （保证跨 V0-V1 的边仍然满足全局无环性）

8. 返回 P0 ∪ P1
```

> **关键**：每一轮递归都调用一次完整的多层框架（粗化 → 初始划分 → 展开细化）。多层框架本身不是递归的，但 k-way 是通过**多次调用**多层框架实现的。

### 3.2 示例：k = 4 的调用树

```
Round 1: Multilevel_Bisection(G)
         → (V0, V1)      [cut edges: V0 → V1]
         
Round 2: Multilevel_Bisection(V0)
         → (V00, V01)    [cut edges: V00 → V01]
         
Round 3: Multilevel_Bisection(V1)
         → (V10, V11)    [cut edges: V10 → V11]

最终编号：
  V00 → 分区 1
  V01 → 分区 2
  V10 → 分区 3
  V11 → 分区 4

跨区边方向：
  V00→V01 (1→2) ✓
  V10→V11 (3→4) ✓
  V0→V1 意味着 V00→V10, V00→V11, V01→V10, V01→V11 (1/2→3/4) ✓
  
全局无环性保证：所有跨区边都从小编号指向大编号。
```

---

## 第四部分：约束粗化与初始划分（CoHyb_CIP）

### 4.1 核心思想

在递归二分的**最顶层调用**（对整张图）时，先用 UndirFix 获得一个高质量的无环初始划分，然后在粗化时**约束只合并 finest-level 划分中属于同一分区的顶点**。这相当于把优质初始划分的信息注入到多层层次结构中。

> 注意：CoHyb_CIP 只在**递归树的根节点**使用（对整张图）。子图递归调用时不需要约束粗化，因为子图已经天然是一个无环子图。

### 4.2 算法流程（CoHyb_CIP）

```
Algorithm: Constraint Coarsening and Initial Partitioning (CoHyb_CIP)
─────────────────────────────────────────────────────────────────
Input: 原始 DAG G=(V,E)
Output: 无环二分 (V0, V1)

// 步骤1：在 finest 图上获得高质量初始划分
1. 运行 UndirFix 获得无环 bisection P = (V0, V1)：
   a. 用 MeTiS 划分 G（忽略方向）
   b. 用 fixAcyclicityUp/Down 修复无环性（4种方式取最优）
   c. 用 Boundary FM 细化平衡和 cut

// 步骤2：约束粗化（多层下降）
2. 从 finest 图 G0 开始，逐层粗化：
   对每一层 ℓ：
     使用 CoHyb 粗化，但附加约束：
       只允许合并 finest-level 属于同一分区（V0 或 V1）的顶点
     即：若 u 和 v 在步骤1的划分 P 中属于不同分区，则禁止合并
   直到达到最粗图 Gc

// 步骤3：约束初始划分
3. 在最粗图 Gc 上：
   每个粗化顶点的分区直接继承其 finest-level 顶点的分区归属
   （即投影 P 到 Gc 上）
   这天然提供一个无环初始划分

// 步骤4：标准展开与细化
4. 从 Gc 开始逐层展开到 G0：
   对每一层，将粗化顶点的分区投影到其展开的顶点
   用 Boundary FM 进行细化

5. 返回最终二分 (V0, V1)
```

> **实验结论**：CoHyb_CIP 是论文推荐的通用默认方案，在所有测试变体中表现最优。相比于单层 UndirFix，多层细化显著提升了质量；相比于无约束的 CoHyb，约束粗化进一步提升了质量。

---

## 第五部分：实验结论与推荐配置

### 5.1 实验验证结果

**粗化比较**：
- CoHyb 和 CoCyc 效果相近，均优于 CoTop
- CoHyb 提供最佳时间/质量折中

**约束粗化比较**：
- CoHyb_CIP > CoHyb_C（约束粗化但贪婪初始划分）> CoHyb（无约束）> UndirFix（单层）
- 约束粗化总是优于无约束版本

**vs 现有工作（Moreira et al. 进化算法）**：
- CoHyb_CIP 平均 edge cut 降低 26%（几何平均，比较平均 cut）
- CoTop 平均 edge cut 降低 37%
- 最佳 cut 比较：CoHyb_CIP 降低 48%，CoTop 降低 41%
- 所有划分满足 3% 平衡约束
- 运行时间：完整测试集约 30 分钟，远快于进化算法

**k-way 实验**：$k \in \{2, 4, 8, 16, 32\}$ 上递归 bisection 均优于 direct k-way。

### 5.2 场景化推荐配置

| 场景 | 推荐方案 | 理由 |
|------|---------|------|
| **通用 DAG** | **CoHyb_CIP** | 综合最优，edge cut 最低 |
| **Sources/Targets 需分离** | CoHyb（无约束）+ Greedy Growing | 避免 UndirFix 将大量顶点移动至同一分区 |
| **顶点度数较小** | CoTop（无约束）| 快速高效，禁止边方法已足够 |
| **k-way 划分** | 递归 Bisection | 论文证明递归 bisection 优于 direct k-way |

---

## 第六部分：实现要点

### 6.1 必须维护的核心数据结构

```cpp
// 图结构
vector<vector<int>> Pred, Succ;       // 前驱/后继邻接表
vector<int> top;                       // top-level 值

// 粗化阶段
vector<int> leader;                    // 聚类代表
vector<bool> mark;                     // 是否已入非单例聚类
vector<int> weight;                    // 聚类权重
vector<int> nbadnbrs;                  // 坏邻居聚类计数（CoTop）
vector<int> leaderbadnbrs;             // 第一个坏邻居的 leader（CoTop）

// 划分阶段
vector<int> part;                      // 分区归属 (0 or 1)

// 细化阶段
vector<int> gain;                      // 移动增益（静态）
priority_queue<pair<int,int>> H0, H1;  // 两个最大堆
vector<int> nSuccInSamePart;           // 同分区的 successor 数量
vector<int> nPredInSamePart;           // 同分区的 predecessor 数量
// 可移动判定：
//   V0→V1: nSuccInSamePart[v] == 0
//   V1→V0: nPredInSamePart[v] == 0
```

### 6.2 关键实现注意事项

1. **Top-level 计算**：使用拓扑排序（Kahn 算法）或 DFS，注意处理多个 source 的情况。source 的 $top = 0$。

2. **随机遍历顺序**：论文使用**随机化的深度优先拓扑序**，实践中比固定顺序效果更好。每次运行使用不同种子，取多次运行最佳结果。

3. **聚类大小限制**：单个聚类权重不超过图总权重的 10%，防止粗化过度不平衡。

4. **粗化停止条件**：顶点数 < 阈值（如 100）或每层缩减率 < 阈值（如 1.1）。

5. **增益静态性**：这是无环 FM 的核心简化——增益不随其他顶点移动而改变，堆无需 decrease-key，仅需 insert/delete/extract-max。

6. **递归 k-way 的编号规则**：递归二分后，左子树的所有分区编号必须小于右子树的所有分区编号，以保证跨区边的全局无环性。

7. **约束粗化的实现**：在 CoHyb 的 ValidNeighbors 中增加一个条件——目标聚类的 leader 在 finest-level 划分中与 $u$ 属于同一分区。

8. **堆的 delete 操作**：标准 priority_queue 不支持高效删除。若实现中需要频繁删除不可移动顶点，可考虑使用支持 lazy deletion 的自定义堆结构，或维护一个"有效"标记位。

---

*文档基于 Herrmann et al. (2019) SIAM J. Sci. Comput. 原文整理。核心架构：多层框架（单次三阶段） + 递归二分（多次调用）。*
