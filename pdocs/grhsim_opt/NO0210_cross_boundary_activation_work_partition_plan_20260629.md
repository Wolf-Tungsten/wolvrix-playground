# NO0210 Cross-Boundary Activation Work Compute Supernode 划分算法框架

记录日期：2026-06-29

状态：**规划文档**。本文是在 [`NO0207`](./NO0207_activity_schedule_prob_partition_upgrade_plan_20260625.md)、[`NO0208`](./NO0208_activity_schedule_prob_partition_rollout_progress_20260625.md)、[`NO0209`](./NO0209_prob_fm_runtime_failure_reflection_20260628.md) 之后，对 compute supernode 划分路线的重新规划。目标不再是沿着 plain 或 prob/FM 修补，而是设计一条以 **cross-boundary activation work** 为第一目标的划分算法。**CBAW 是继 plain、prob/FM 之后的第三条平行 partition 路径；它不是 plain 的补丁、后处理、局部修补 pass 或参数扩展。**

术语约定：

- `cross_boundary_activation_work`：一个 value 被传播到外部 supernode 时带来的激活传播和 value materialization 工作量。按当前 stats 口径，它是去重后的 `(value, target supernode)` 数，对应历史统计里的 `boundary_activation_edges`，不是原始 consumer use 数。
- `cross_boundary_target_count`：所有跨边界 `(value, target supernode)` 对数，对应 `boundary_activation_edges`。
- `supernode_dependency_edge_count`：最终 compute supernode DAG 的唯一依赖边数，对应 `dag_edges`。
- `compute_materialized_value_target_count`：target 为 compute supernode 的跨边界 `(value, target supernode)` 对数，对应 `compute_compute_value_pairs`。
- `cross_boundary_consumer_use_count`：未按 target supernode 去重的跨边界 consumer use 数量。它可用于诊断高 fanout value，但不对应当前 `boundary_activation_edges`，不能作为主验收口径。
- `cross_boundary_value_bytes`：`cross_boundary_target_count` 的 width-aware 版本，只作为 tie-break / 诊断指标。
- `supernode_resource_pressure`：单个 compute supernode 的资源压力归一化上界，用来合并 op 数、live value footprint、temporary footprint、emitted code shape 等共线约束。

范围：

- 只关注 **compute supernode** 部分。commit supernode、commit activation mask、fixed-point 调度不在本文算法目标内。
- 输入规模按完整 XiangShan 图设计，要求线性或近线性；禁止全图 all-pair、禁止 per-root 全图扫描。
- plain 只作为最终验收基线、接口 replay 对照和有限 structural hint 来源，不作为算法设计边界或前置骨架。新算法可以完全替换当前 out1/in1/siblings + DP 的 compute 划分路径，并应作为与 plain / prob/FM 并列的第三条路径独立 materialize。

---

## 1. 背景判断

### 1.1 207-209 给出的负结论

[`NO0207`](./NO0207_activity_schedule_prob_partition_upgrade_plan_20260625.md) 的初始假设是：如果静态概率 `π` 足够合理，就可以把划分目标从 edge-cut 推向 `p(e) * W(succ)`，再通过概率粗化和 FM 精修降低 runtime。[`NO0208`](./NO0208_activity_schedule_prob_partition_rollout_progress_20260625.md) 确实把 `π` 从饱和模型修到了 transition-density 模型，也实现了 cost / hypergraph / prob coarsen / mixed DP / FM。

但 [`NO0209`](./NO0209_prob_fm_runtime_failure_reflection_20260628.md) 的 CoreMark 50k 结果否定了这条路线作为主线继续推进：

| 指标 | plain | prob_dp1_fm4 | ratio |
| --- | ---: | ---: | ---: |
| `dag_edges` | 702,085 | 1,390,609 | 1.98x |
| `boundary_activation_edges` | 2,451,342 | 2,890,748 | 1.18x |
| `compute_compute_value_pairs` | 2,098,240 | 2,537,646 | 1.21x |
| CoreMark 50k host time | 326,433 ms | 628,792 ms | 1.93x slower |

核心教训：

1. **概率不是可靠主目标**。没有 runtime profile 时，`π` 即使分布看起来合理，也不能代表 workload 上真实 firing frequency。
2. **weighted-boundary 不是 runtime 硬代理**。weighted 指标在 prob 内部改善，不代表相对 plain 结构变好。
3. **cross-boundary activation work / DAG 边 / compute-to-compute value pairs 是硬成本**。它们直接对应 activation propagation、跨 supernode value materialization 和 quotient DAG 调度压力，不能作为二级统计事后观察。
4. **supernode 数不是主指标**。`prob_dp1_fm4` supernode 数略少，但 cross-boundary activation work 和 DAG 边显著更多，runtime 跟着回退。

因此新路线必须把跨边界工作量本身放进数学目标函数，而不是继续先优化概率，再希望 cross-boundary activation work 顺带下降。

### 1.2 新路线定位

本文规划的算法暂命名为 **CrossBoundaryActivationWork partitioning**。

路线边界：CBAW 的落地形态应是 **plain / prob/FM / CBAW 三条并列入口**。plain 可以提供 baseline stats、resource cap 校准、materialize replay 对照和少量结构 hint，但 CBAW 的 atom、candidate、gain、accept gate、refinement 与 materialization 都由本文定义的 value-use / CBAW pipeline 裁决；不得把 CBAW 实现成“先跑 plain，再对 plain 结果做修补”的后处理模式。

它不是：

- 不是在 plain partition 结果上做增量修补、cleanup 或局部 refinement；
- 不是 plain coarsen 的参数扫描；
- 不是 prob coarsen 的 gain 修补；
- 不是 FM rounds / DP cost 的继续调参；
- 不是必须依赖 runtime profile 才能产出 partition 的 workload-specific partition。**（2026-06-29 收紧：本路线完全不使用 runtime profile，包括早先设想的“校准 / gate”用途；firing-frequency / over-eval 成本改由 §2.6 与 §9 的静态 trigger 模型 profile-free 表达。）**

它是：

- 一个以 **directed value-use graph** 表达 compute value producer/consumer 关系的划分器；
- 一个以 **cross-boundary target count / supernode dependency edges / compute materialized value targets** 为主目标的多级近线性算法；
- 一个使用 **plain structural hint / merge hint groups / guard / aggregate / sink-cone / MFFC** 提供候选和约束的算法，而不是只看裸图邻接形状；
- 一个保证输出 quotient DAG 无环、满足 compute supernode resource budget 的 compute-only partition path。
- 一个与 plain / prob/FM 并列运行、并由同一 stats gate 比较优劣的独立 partition pipeline。

### 1.3 本次梳理移除的旧口径

本文不再保留以下早期表述：

1. `boundary_activation_edges` 不是原始 consumer use 数；它来自 `value_fanout` 中去重后的 target supernode 数。因此主目标使用 `cross_boundary_target_count`，`cross_boundary_consumer_use_count` 仅保留为诊断。
2. `materialized_value_target_count` 与总 `boundary_activation_edges` 容易混淆；文中改为 `compute_materialized_value_target_count`，明确只对齐 `compute_compute_value_pairs`。
3. `regToMem.intent.version=1` 的字段列表不是完整接口。当前实现已消费 `storageGroup/storageElementCount/storageRowOffset/storageRow/storageRegSymbols` 等扩展字段，本文按兼容 attr 族描述。
4. 完整 XiangShan activity-schedule 输入按约 5M ops 量级规划；不再使用“50M 级 op”的旧估计。
5. `π` / weighted-boundary 不再作为合并接受的主目标。它可以保留为报告字段、tie-break 或 profile 校准输入，但不能覆盖真实边界指标。

---

## 2. 数学问题定义

### 2.1 基础对象

从 activity-schedule 的 compute 子图抽象出一个有向无环图：

```text
G = (V, E)
```

其中 `V` 是可进入 compute supernode 的 op / atom，`E` 是 value def-use 依赖。sink / commit op 不进入本文的 partition vertex 集；它们只可以作为静态语义标签来源，例如“这个 compute cone 最终服务哪个 state write family”。

为了准确表达 value 的 producer/consumer 关系，不直接在普通图 `E` 上做 partition，而是构造 directed value-use graph：

```text
H = (A, U)
```

- `A`：atom 集。atom 是若干 op 的不可拆或暂不拆单元。初版 atom 可以等于 computeNode / MFFC seed，后续可直接由语义 atom builder 产生，不要求继承 plain。
- `U`：value use group 集。每个 compute value `x` 形成一个 use group：

```text
use_group(x) = {
  producer_atom: atom that defines x,
  compute_consumer_atoms: compute atoms that use x,
  fixed_terminal_targets: sink/commit target supernodes that use x
}
```

同一个 value 被多个 consumer 或 terminal target 使用时，必须保留这个 use group，不应先压成普通二元边；否则高 fanout value 的跨边界成本会被错误估计。partition 顶点仍只包含 compute atom；sink / commit target 是 fixed terminal，不参与合并，只用于 evaluator 对齐 `boundary_activation_edges` 和 target-kind 拆分。

### 2.2 Partition 与精确边界指标

给定划分 `supernode_of(atom) -> compute_supernode`。`compute_supernode` 是本文唯一的划分单位。

对每个 value `x` 的 use group：

```text
producer_supernode = supernode_of(producer_atom(x))
external_compute_uses = [
  consumer_atom | supernode_of(consumer_atom) != producer_supernode
]
terminal_targets = fixed sink/commit supernodes that use x
target_supernodes = unique(
  supernode_of(consumer_atom) for consumer_atom in external_compute_uses
  plus terminal_targets
)
```

定义四个主指标和一个诊断指标：

```text
cross_boundary_target_count(supernode_of)
  = Σ_x |target_supernodes(x)|

supernode_dependency_edge_count(supernode_of)
  = |{ (producer_supernode(x), target_supernode) for every x and target_supernode in target_supernodes(x) }|

compute_materialized_value_target_count(supernode_of)
  = Σ_x |{ t in target_supernodes(x) | kind(t) == compute }|

cross_boundary_value_bytes(supernode_of)
  = Σ_x value_byte_cost(x) * |target_supernodes(x)|

cross_boundary_consumer_use_count(supernode_of)
  = Σ_x |external_compute_uses(x)| + |terminal consumer uses(x)|
```

含义：

- `cross_boundary_target_count`：跨 supernode 的去重 `(value, target supernode)` 数量，对齐当前 `boundary_activation_edges`。
- `supernode_dependency_edge_count`：最终 compute supernode DAG 的唯一有向边数，贴近 `dag_edges`。
- `compute_materialized_value_target_count`：target 为 compute supernode 的跨边界 value materialization 对数，对齐当前 `compute_compute_value_pairs`。
- `cross_boundary_value_bytes`：对 `cross_boundary_target_count` 乘以 value width / storage bucket 后的派生量。
- `cross_boundary_consumer_use_count`：原始 consumer use 数，适合解释高 fanout value 的内部压力，但当前 emit/stats 已经按 target supernode 去重，不能把它当作 `boundary_activation_edges`。

Evaluator 必须同时按 source kind 和 target kind 拆分：

- source kind：state read / memory read / constant / compute-like，沿用 `state_read_activation_edges`、`memory_read_activation_edges`、`constant_activation_edges`、`other_compute_activation_edges` 的口径；
- target kind：compute / commit，沿用 `compute_compute_value_pairs`、`compute_commit_value_pairs` 的口径；
- compute partition 可以直接改变 compute supernode 形状和 compute target 分布，但不应把 commit grouping / commit mask 的问题混入本文目标。验收仍看总 `boundary_activation_edges`，归因必须给出 compute/commit target 拆分。

实际验收时仍以现有 stats 字段为准；本文的数学指标用于算法内部保持目标一致。

### 2.3 目标函数

新算法不把概率作为主目标。主目标采用词典序而不是单一加权和：

```text
minimize  PartitionCost(P) =
  (
    cross_boundary_target_count(P),
    supernode_dependency_edge_count(P),
    compute_materialized_value_target_count(P),
    cross_boundary_value_bytes(P),
    supernode_resource_pressure(P),
    supernode_count_penalty(P),
    semantic_split_penalty(P)
  )
```

设计理由：

1. `cross_boundary_target_count / supernode_dependency_edge_count / compute_materialized_value_target_count` 是 runtime 失败中已经被验证的硬结构指标，必须排在概率、权重和 supernode 数之前。
2. `cross_boundary_value_bytes` 是 `cross_boundary_target_count` 的 width-aware 派生量，只在前三个主指标相同或近似持平时参与，不能作为独立硬目标重复计分。
3. `supernode_resource_pressure` 约束单个 supernode 的 emitted code、host cache、temporary footprint 和 helper/branch 压力，避免为了少量边界下降制造超大函数。
4. `supernode_count_penalty` 只在前面指标相同或近似持平时参与；不再允许“supernode 少一点但 cross-boundary activation work 多很多”的方案进入 runtime。
5. `semantic_split_penalty` 是最后的 tie-breaker 或 plateau mover，用语义帮助走出局部最优，但不能让 real cross-boundary activation work 大幅变差。

局部搜索的接受规则不能把词典序目标解释成“任何第一项微小增加都永久禁止”。为避免陷入过硬的局部最优，本文采用两层口径：

- **local accept**：默认要求前三个主指标词典序不变差；若 `cross_boundary_target_count` 只有极小增量，必须同时带来明显的 `supernode_dependency_edge_count / compute_materialized_value_target_count / resource_pressure` 改善，并且该增量不能让当前 partition 超过 plain gate 预算。
- **structure/runtime gate**：最终输出进入 build/runtime 前，仍必须相对 plain 满足硬门槛。局部搜索允许的微小临时回退不能成为最终结构回退。

第一版实现建议把“极小增量”写成显式参数并默认关闭；只有当 no-regression 版本卡在 plateau，且 evaluator 能解释收益来源时再打开。

### 2.4 约束

输出 partition 必须满足：

1. **Quotient DAG 无环**：contract 每个 compute supernode 后得到的 supernode 图仍是 DAG。
2. **Supernode resource budget**：每个 compute supernode 的归一化资源压力不超过上限。
3. **语义不可拆约束**：reg-to-mem intent、必须保持同一访问形态的 aggregate row / lane、source clone 的 canonical 语义不能被破坏。

resource budget 不再把 op count、footprint、code shape 当作三条互相独立的约束。它们大多共线，应先合并成一个资源向量，再用统一压力值做 hard cap：

```text
resource_pressure(S) = max(
  op_count(S) / op_count_cap,
  live_value_bytes(S) / live_value_bytes_cap,
  temporary_bytes(S) / temporary_bytes_cap,
  emitted_code_units(S) / emitted_code_units_cap,
  helper_call_count(S) / helper_call_cap,
  branch_count(S) / branch_count_cap
)

supernode_resource_pressure(P) = max_S resource_pressure(S)
```

其中 `op_count` 是便宜 surrogate，适合第一版保护调度和构建时间；`live_value_bytes / temporary_bytes` 才直接描述 cache / memory footprint；`emitted_code_units / helper_call_count / branch_count` 描述 host code shape。merge 接受时先检查统一的 `resource_pressure <= 1`；若候选都可行，`supernode_resource_pressure` 可以作为后段 tie-break，但不能再让这些共线分量分别进入 objective 或 accept gate。

首版 cap 不应拍脑袋给常量。建议先用 plain partition 的资源分布校准：

- 对每个资源分量统计 plain compute supernode 的 p50 / p90 / p99 / p99.5 / max；
- 默认 `resource_pressure=1` 参考 plain 的 p99 或 p99.5，再加一个绝对 max guard；
- 若某个资源分量 plain 本身已有极端 outlier，不用 outlier 定 cap，而是把它列入 baseline exception；
- 每次候选 merge 被 resource budget 拒绝时，记录触发的最大分量，避免只看到一个合成 `resource_pressure` 而无法调参。

### 2.5 共线性审计结论

本文的指标分成三层，避免把同一成本重复计分：

| 层级 | 保留指标 | 处理结论 |
| --- | --- | --- |
| 主目标 | `cross_boundary_target_count` | 去重后的 `(value, target supernode)` 数，直接对齐 `boundary_activation_edges` |
| 主目标 | `supernode_dependency_edge_count` | quotient DAG 调度边数，和 target count 相关但不是同一量，保留 |
| 主目标 | `compute_materialized_value_target_count` | target 为 compute supernode 的跨边界 value 数，直接对齐 `compute_compute_value_pairs` |
| 派生 tie-break | `cross_boundary_value_bytes` | `cross_boundary_target_count` 的 width-aware 版本，不再作为独立硬目标 |
| 诊断 | `cross_boundary_consumer_use_count` | 未按 target 去重的 consumer use 数，只用于解释 fanout/候选优先级，不进入主验收 |
| hard budget | `supernode_resource_pressure` | 合并 op count、footprint、temporary bytes、emitted code units、helper/branch count |
| tie-break | `supernode_count_penalty` | 只在主目标和 resource pressure 持平时使用 |
| tie-break | `semantic_split_penalty` | 只用于 plateau move，不允许压过真实 cross-boundary 指标 |

`op_count` 和 footprint 不再同时作为独立 cap；`code_shape_penalty` 也不再单列为 objective 项。它们都是 `resource_pressure` 的分量。实现时可以保留原始分量用于诊断和调参，但 merge gain / accept gate 只能看统一后的 resource budget，避免“同一资源压力被多次惩罚”。

这个问题包含 resource-bounded value-use partition、semantic integrity 和 acyclic contraction，理论上是 NP-hard。完整 XiangShan 上不能求精确最优，只能用有明确目标函数的近线性多级启发式。

### 2.6 firing-frequency 盲点与 trigger 模型（ATE 扩展）

§2.3 的词典序目标只含边界、materialization、resource，**不含 firing frequency**。但 [`NO0190`](./NO0190_grhsim_gsim_unified_cost_model_comp_src_sink_plan_20260612.md) 的统一成本模型是：

```text
T = Σ_i f(i) · (E(i) + A_succ(i)) + N · A_exam
```

主导项是 `f(i)·E(i)`。把 atom A、B 合并成 M 时：

```text
E(M) = E(A) + E(B)
trigger(M) = trigger(A) ∪ trigger(B)
f(M) = P(trigger(M) 中任一 value 变化) ≥ max(f(A), f(B))
```

因此“只看边界下降、不看 f”的合并会把低频块拖到高频块的 firing 率上空转，抬高 `f·E`。这正是 [`NO0067`](./NO0067_batch_coarsen_coremark_50k_failure_20260503.md)、[`NO0086`](./NO0086_grhsim_runtime_aware_coarsen_ordering_experiments_20260511.md)、[`NO0134`](./NO0134_commit_supernode_cap1024_build_positive_runtime_negative_20260521.md)、[`NO0085`](./NO0085_xs_no0076_fresh_rerun_20260510.md) 反复出现的 **over-eval 回退**：结构 / 粒度指标变好、runtime 反而变慢。§2.3 目标对这一项完全失明，是本路线最大的理论缺口。

不能用概率或 profile 去补：

- 静态 `π` 已被 [`NO0209`](./NO0209_prob_fm_runtime_failure_reflection_20260628.md) 否定为合并主目标（§5.1 也据此把概率降级为 tie-break）；
- runtime profile 在本路线**完全不可接受**，包括 §1.2 早先允许的“校准 / gate”用途。

所以 over-eval 必须用 **profile-free、且不依赖 `π` 绝对值** 的量表达。引入 **trigger 集合**：

```text
trigger(a) = { 跨边界进入 a 的 volatile source value }
```

只计 state-read / memory-read 等真正会变的 source；常量与纯 representation 透传不增加 trigger 基数。`trigger` 可在一次 reverse-topo 中用定宽签名（MinHash / Bloom）近线性传播，与 Phase A evaluator 同复杂度级。

据此把目标函数扩展为：在 §2.3 词典序之上叠加一个 **over-eval guard**，用全局 trigger 膨胀 `Σ_S |trigger(S)|` 作为 `f·E` 抬升的 profile-free 上界代理。具体合并准则、Pareto 定理与阶段接线见 §9；trigger 模型是**集合结构事实，不是概率**，因此与 §5.1“不以概率主导合并”一致。

---

## 3. 语义建模规则

cross-boundary activation work 是目标，但候选不能只来自裸图邻接。CrossBoundaryActivationWork 的语义建模要回答三个问题：

1. 哪些 op 应该先包成 atom seed，避免后续过度拆分；
2. 哪些 atom 之间应该生成 `MergeHintGroup` / merge candidate；
3. 哪些信息只能诊断，不能进入 gain。

### 3.1 统一产物

每条语义规则最多产生三类产物：

| 产物 | 含义 | 是否能压过 cross-boundary activation work |
| --- | --- | --- |
| `SeedGroup` | 初始不可拆分组；内部 op 必须先同属一个 atom seed | 是，但仍受 resource budget / DAG 无环约束 |
| `MergeHintGroup` | 合并提示分组；用于生成 merge candidate 或 tie-break | 否 |
| `DebugLabel` | 诊断标签；仅用于报告 top cross-boundary root 归因 | 否 |

规则输出格式：

```text
SemanticRuleResult {
  seed_groups:       [ {rule, members, reason, cap_policy} ],
  merge_hint_groups: [ {rule, key, members, max_candidates} ],
  debug_labels:      [ {op/value/atom, key, rule} ]
}
```

通用降级原则：

- 规则需要的 attr / def-use 形态不完整时，整条规则降级为 `DebugLabel` 或直接忽略；
- 任何 `MergeHintGroup` 都不能让 merge 接受一个 cross-boundary activation work 变差的动作；
- `SeedGroup` 若超过 resource budget，必须按 topo 连续段或 rule-specific frontier 拆成多个 atom，拆分出的 atom 之间生成 `MergeHintGroup`；
- 任何规则若会引入 quotient cycle 风险，只能生成 candidate，不能直接强行 contract；
- 所有 key 都必须来自 graph 内稳定 id / canonical value / pass attr，不从扁平化名字前缀猜层级。

### 3.2 ValueUseGroup Rule（硬目标）

这是唯一直接进入主目标的语义规则。

**输入**

- 每个 compute value `x`；
- `canonicalValue(x)`，用于把 source clone 回溯到原始 value；
- `producer_atom(x)`、所有 compute consumer atom、固定 sink/commit terminal target；
- value width / storage bucket。

**匹配**

所有有跨 supernode compute consumer 或 sink/commit terminal target 的 compute value 都匹配。若 value 没有外部 compute consumer 且没有 terminal target，则不建 compute value-use group。

**产物**

```text
ValueUseGroup(x) = {
  producer = atom(canonical def of x),
  compute_consumers = [atom(consumer_0), atom(consumer_1), ...],
  fixed_terminal_targets = [commit/sink supernode_0, ...],
  width_bucket = storage_bucket(width(x))
}
```

**计分**

`ValueUseGroup` 的 cut 精确贡献：

```text
cross_boundary_target_count,
supernode_dependency_edge_count,
compute_materialized_value_target_count,
cross_boundary_value_bytes
```

同时可统计 `cross_boundary_consumer_use_count`，用于诊断某个 value 在单个 target supernode 内仍有大量 consumer 的情况；它不作为主目标。

**candidate rules**

对每个已经跨 supernode 的 high-impact `ValueUseGroup`：

- producer supernode -> top-k consumer supernode；
- consumer supernode 之间的 top-k co-location pair；
- 若 fanout 很高，只保留按 target count / consumer use count / byte cost 排序的 top-k supernode，不展开 clique。

**降级**

不降级。Value use group 是算法的基础事实。

### 3.3 FanoutFreeCone Rule

MFFC 用来定义默认 atom seed，但不把现有 computeNode 作为永久边界。

**输入**

- compute/source op 的 def-use DAG；
- op class：source / compute / sink / unsupported；
- reg-to-mem intent protected group；
- supernode resource budget。

**匹配**

反向 topo 近似：

```text
if op is sink/unsupported/side-effect:
  rep[op] = NONE
else if op is protected by a SeedGroup rule:
  rep[op] = hard_atom_key
else:
  consumers = compute consumers of op result(s)
  if consumers is empty:
    rep[op] = op
  else if all consumers have same non-NONE rep:
    rep[op] = that rep
  else:
    rep[op] = op
```

这不是精确 dominator 算法，而是完整 XiangShan 可承受的线性 MFFC 近似。

**产物**

- `SeedGroup(rule=MFFC, members=same rep)`，受 resource budget 限制；
- 若一个 MFFC 因 resource budget 被拆成多个 topo-contiguous atom，生成：

```text
MergeHintGroup(rule=mffc_split, key=rep, members=[split_atom_0, split_atom_1, ...])
```

**candidate rules**

- 同一 `mffc_split` merge-hint group 内相邻 topo atom；
- MFFC root producer 与唯一重 consumer supernode；
- 被 resource budget 拆开的连续段优先于跨 MFFC candidate。

**拒绝 / 降级**

- 包含 sink / side-effect / unsupported op 时不建 MFFC seed group；
- 与 reg-to-mem intent seed group 冲突时，以 intent seed group 为准；
- 巨型 MFFC 超 resource budget 时必须拆，不允许为了 MFFC 完整性制造超大 supernode。

### 3.4 PlainStructuralHint Rule

这条规则复用当前 plain 路径已经证明稳定的低风险结构形状，但只作为 `MergeHintGroup` / candidate 来源，不作为算法目标，也不要求新算法复刻 plain partition。它不能被实现成“读取 plain partition 后再局部修补”的 bridge pass；CBAW 只能读取 out1 / in1 / sibling 这类局部结构事实，并在自己的 value-use evaluator 下重新裁决。

**输入**

- atom quotient DAG；
- 当前实现中的 out1 / in1 / sibling 关系；
- atom / supernode resource vector；
- quotient DAG topo interval。

**匹配**

- `out1`：某个 atom / supernode 只有一个 compute 后继；
- `in1`：某个 atom / supernode 只有一个 compute 前驱；
- `siblings`：多个 atom / supernode 有相同或高度重叠的前驱集合；
- 只在 compute-only 区域匹配，不跨 sink / commit / unsupported op。

**产物**

```text
MergeHintGroup(rule=plain_out1, key=(producer, sole_successor), members=[producer, successor])
MergeHintGroup(rule=plain_in1, key=(sole_predecessor, consumer), members=[predecessor, consumer])
MergeHintGroup(rule=plain_siblings, key=canonical_pred_set, members=[sibling_0, sibling_1, ...])
```

**candidate rules**

- `plain_out1 / plain_in1` 只生成 pair candidate；
- `plain_siblings` 不展开全 clique，只保留按真实 cross-boundary gain 排序后的 top-k sibling pair 或小批量 merge；
- plain candidate 与 semantic candidate 同队列竞争，接受时仍使用 `PartitionCost` 和 resource / acyclic gate；
- plain partition 本身不作为 CBAW 的初始解、fallback merge 序列或必须保持的骨架。

**拒绝 / 降级**

- 如果 plain shape merge 的真实 `cross_boundary_target_count / supernode_dependency_edge_count / compute_materialized_value_target_count` 变差，拒绝；
- 如果它只减少 supernode 数但增加 activation work，不允许作为 plateau merge；
- 如果无环检查不确定，首版保守拒绝并记录 `rejected_cycle_plain_hint`。

设计目的：避免新 atom / semantic candidate 体系漏掉 plain 已经能捕捉的大量局部结构合并，同时保持 NO0210 的真实目标函数为唯一裁决者。PlainStructuralHint 是第三条路径里的 hint adapter，不是 plain 到 CBAW 的补丁通道。

### 3.5 CanonicalValueInvariant Rule

这不是 merge hint，而是 evaluator 和 value-use graph 的硬 invariant。source clone、canonical value 和 terminal target 的处理若出错，所有 cross-boundary 指标都会偏移。

**规则**

- 每个 compute value 必须映射到稳定的 `canonicalValue(x)`；
- source clone 的 use group 归并到 canonical def，不允许同一个 canonical value 因多个 clone 被重复计入 `cross_boundary_target_count`；
- 如果多个 clone 有不同 compute consumer atom，consumer set 合并后再按 target supernode 去重；
- terminal sink / commit target 也按 canonical value 合并，并与 compute target 分开计数；
- value width / storage bucket 必须来自 canonical value；若 clone width 与 canonical width 不一致，记录 diagnostic 并降级为不可合并的独立 use group，不能静默合并；
- producer atom 选择必须稳定：优先 canonical def 所在 atom；若 canonical def 不在 compute partition vertex 集，则使用 source/fixed terminal 口径标记，不伪造成 compute producer。

**验收测试**

- evaluator 对 plain partition 的 `boundary_activation_edges / compute_compute_value_pairs` 复算必须对齐现有 stats 或列出差异来源；
- 构造 source clone 小图，验证多个 clone consumer 不重复增加同一 `(canonical value, target supernode)`；
- 构造 clone 同时流向 compute 和 commit 的小图，验证 target-kind 拆分稳定。

### 3.6 RegToMemIntentGroup Rule

这是当前已有、最可信的 aggregate 语义。它来自 `reg-to-mem` pass 的 attrs。

**输入 attr**

```text
regToMem.intent.version = 可选；存在时按兼容版本解释
regToMem.intent.group
regToMem.intent.role = "register" | "read" | "concat" | "slice"
regToMem.intent.mode = "array-index"
regToMem.intent.elementWidth
regToMem.intent.elementCount
regToMem.intent.regSymbols
regToMem.intent.storageRegSymbols
regToMem.intent.operandRows
regToMem.intent.row
regToMem.intent.storageGroup
regToMem.intent.storageElementCount
regToMem.intent.storageRowOffset
regToMem.intent.storageRow
regToMem.intent.sliceKind
```

其中 `storage*` attrs 是当前实现里已经被 activity-schedule / emitter 消费的扩展字段；没有这些字段时按本地 group 口径降级。本文不再把早期 v1 子集当作完整接口。

**匹配**

同一 `regToMem.intent.group` 内：

- `kRegisterReadPort` role=`read`；
- `kConcat` role=`concat`；
- `kSliceArray` / `kSliceDynamic` role=`slice`；
- `mode` 必须为 `array-index`；
- `elementWidth / elementCount / regSymbols / operandRows` 必须自洽；
- 若存在 `storageGroup/storageElementCount/storageRowOffset/storageRow/storageRegSymbols`，必须与本地 row 映射一致。

**产物**

```text
SeedGroup(rule=rtm_intent, key=group, members=read_ports + concat + slice_ops)
MergeHintGroup(rule=aggregate_array, key=("rtm", group), members=[hard_atom, direct consumers])
DebugLabel(key=("rtm", group, row/width/count))
```

**边界定义**

- seed group 的内部语义输出是 slice result；
- slice index / address 是 boundary input，不强行纳入 seed group；
- downstream consumers 不自动并入 seed group，只通过 `MergeHintGroup` 产生 cross-boundary-activation-work-aware candidate。

**拒绝 / 降级**

- attr 缺失或 group 不自洽：不建 seed group；
- group members 跨多个不兼容 storage family：不建 seed group；
- index/address 链不稳定：仍可保 seed group，但 index/address 不纳入 members；
- resource budget 超限：按 slice anchor 拆成多个 atom，并在拆分出的 atom 之间生成 `MergeHintGroup(rule=rtm_split)`。

### 3.7 AggregateAccessGroup Rule

这条规则覆盖没有 reg-to-mem intent 的 array-like / packed aggregate 读侧。

**输入形态**

完整 row 读取：

```text
r_i      = kRegisterReadPort / kLatchReadPort / kMemoryReadPort
packed   = kConcat(r_N-1, ..., r_0)
elem     = kSliceArray(packed, index)
```

可解析 dynamic slice：

```text
elem = kSliceDynamic(packed, start)
start = index * elementWidth + const_offset
sliceWidth = elementWidth
```

以及纯 bitfield 拆分 / 重建：

```text
part_i = kSliceStatic(base, offset_i, width_i)
repack = kConcat(part_k, ..., part_0)
```

**匹配规则**

- `kConcat` operands 宽度一致或能形成稳定 row layout；
- `kSliceArray.sliceWidth` 或 `kSliceDynamic.sliceWidth` 等于 row width；
- `kSliceDynamic` 的 start 必须可解析为 `index * rowWidth + constant lane offset`；
- concat result 的 consumer 主要是 slice / simple passthrough，若还有大量无关 consumer，则只建 merge-hint group；
- 对 static slice / concat 重建，必须覆盖同一 base 的不重叠区间，且 concat 顺序与 bit offset 一致。

**产物**

强形态：

```text
SeedGroup(rule=aggregate_read_anchor, members=concat + slice + single-user read/passthrough chain)
MergeHintGroup(rule=aggregate_family, key=(base/canonical packed value, rowWidth, elementCount))
```

弱形态：

```text
MergeHintGroup(rule=aggregate_family, key=(canonical packed value or base value))
DebugLabel(rule=aggregate_shape, key=...)
```

**candidate rules**

- producer of packed value -> slice supernode；
- 同一 aggregate family 的多个 slice supernode；
- slice result producer -> immediate compute consumers；
- static slice pieces -> repack supernode。

**拒绝 / 降级**

- shared concat / shared read 无法证明单一 aggregate view 时，不建 seed group；
- dynamic start 不可解析时，仅保留普通 `ValueUseGroup`；
- family fanout 过大时只保留 top-k row/lane candidate；
- 不从 symbol 名字猜 row / lane。

### 3.8 GuardContextGroup Rule

Guard 语义只作为 merge-hint group，不作为 seed group 的默认来源。原因是 flatten 后很难证明完整控制域，且 guard 相同不代表数据依赖适合合并。

**输入**

- `kMux(sel, a, b)`；
- `kAnd / kOr / kLogicAnd / kLogicOr / kNot / kLogicNot`；
- `kEq` with constant、`kNe` with constant、onehot-ish compare；
- canonical value id。

**Guard 表达式限制**

只维护小型 guard signature：

```text
GuardSig = AND of at most K literals
Literal  = canonical value id + polarity
```

建议 `K <= 4`。超过 K 或遇到复杂表达式，标记 `unknown`。

**传播规则**

- `kAssign / kSliceStatic / kSliceDynamic / kSliceArray / kReplicate`：继承输入 guard；
- `kMux(sel, a, b)`：
  - mux 输出只记录 `mux_select={sel}`，不把 `a/b` 两支强行归为同一 guard domain；
  - 若从 mux 输出反向给 operand 标注 sink-cone / guard context，则 `a` 分支附加 `sel`，`b` 分支附加 `!sel`；
  - 若 `sel` 过宽、不可 canonicalize 或 guard literal 数超过上限，降级为 `mux_guard_unknown`；
- `kAnd(valid, data)`：
  - 若一侧是 1-bit control-like value，输出 guard 加该 literal；
  - control-like 判定：width=1，fanout 高，或参与 mux select / write enable / memory enable；
- `kOr(masked_a, masked_b, ...)`：
  - 若 operands 分别来自互斥 guard，输出 guard 记为 `union_guard`，不生成 seed group；
- `kNot`：翻转 literal polarity；
- 算术 / compare / reduce：不传播强 guard，只保留 operands guard 的交集。

**产物**

```text
MergeHintGroup(rule=guard_domain, key=GuardSig, members=[atoms carrying GuardSig])
DebugLabel(rule=guard_unknown/guard_union, ...)
```

**candidate rules**

- 同一 `GuardSig` 下、已有 value-use 连接的 atom pair；
- 同一 `GuardSig` 下、共同服务同一 sink-cone 的 atom pair；
- 不生成无数据关系的全连接 candidate。

**拒绝 / 降级**

- guard member count超过阈值：只保留 top-k by current cross-boundary activation work contribution；
- `unknown` / `union_guard` 不参与 merge gain；
- guard 不能让 cross-boundary activation work 变差的 merge 被接受。

### 3.9 DownstreamSinkGroup Rule

Sink-cone 用 commit/sink 身份给 compute cone 打标签，但不把 sink 放入 compute partition。

**输入**

- compute value 的 downstream users；
- sink-class op：`kRegisterWritePort`、`kLatchWritePort`、`kMemoryWritePort`、`kMemoryFillPort`；
- sink symbol / state symbol / event key / memory symbol；
- bounded reverse/forward propagation。

**传播规则**

反向从 sink 的 data / mask / address / enable operand 标记：

```text
SinkLabel = {
  kind: reg_write | latch_write | mem_write | mem_fill,
  state_symbol or memory_symbol,
  operand_role: data | mask | addr | enable,
  event_key if available
}
```

沿 def-use 反向传播到 compute atoms：

- 每个 atom 保留 top-k sink labels，建议 `k <= 4`；
- 若 labels 超过 k 或熵过高，标记 `multi_sink`；
- data / mask / addr / enable 分开标记，避免把地址计算和数据通路误合并。

**产物**

```text
MergeHintGroup(rule=sink_cone, key=SinkLabel, members=[atoms with that label])
DebugLabel(rule=sink_cone_exact/multi_sink, ...)
```

**candidate rules**

- 同一 sink label 且存在 value-use 边的 producer-consumer；
- 同一 sink label 下的 high-cross-boundary activation work boundary atoms；
- data 与 mask/enable 只有在有直接 value 关系或同 guard 时才生成 candidate。

**拒绝 / 降级**

- `multi_sink` 只做诊断；
- sink label 不允许跨 operand role 强合并；
- 不把 commit supernode cap / grouping 引入本文目标。

### 3.10 PassthroughChain Rule

这条规则处理只改变表示、不改变语义信息量的链，防止边界落在纯搬运 op 上。

**匹配 op**

```text
kAssign
kSliceStatic
kSliceDynamic with constant/resolved static range
kSliceArray with resolved static row
kReplicate
single-operand kConcat
bitcast-like concat/slice pair
```

**产物**

- 小型 `SeedGroup(rule=passthrough_chain)`：仅当链单 consumer、无高 fanout、总 op 数很小；
- 否则 `MergeHintGroup(rule=passthrough_chain, key=canonical source value)`。

**candidate rules**

- passthrough producer 与唯一 consumer supernode；
- slice producer 与 repack concat supernode；
- source clone supernode 与其唯一 compute consumer。

**拒绝 / 降级**

- passthrough result 高 fanout 时不建 seed group，只靠 `ValueUseGroup`；
- dynamic slice 未解析时不建 seed group；
- wide concat 超 resource budget 时不强包。

### 3.11 SupernodeResourceBudget Rule

这不是功能语义，而是防止 CrossBoundaryActivationWork 为了降 cross-boundary activation work 生成超大或 host 不友好的 compute supernode。它把 op count、footprint、temporary storage、emitted code shape 视为同一资源压力的不同投影。

**输入**

- op kind；
- value width bucket；
- op cost bucket；
- live value / temporary storage 估计；
- emitted statement 估计；
- helper call 估计；
- branch / guard 估计；
- source / memory read / wide words 估计。

**产物**

```text
SupernodeMetric {
  op_count,
  est_statements,
  est_helper_calls,
  est_branches,
  est_wide_word_ops,
  est_source_reads,
  live_value_bytes,
  temporary_bytes,
  resource_pressure
}
```

**使用规则**

- 不生成 merge-hint group；
- 只作为 hard resource budget 和 PartitionCost 后段 penalty；
- 当 `Δcross-boundary activation work` 很小但 `resource_pressure` 明显变差时拒绝 merge；
- 防止单个 supernode 因 high-fanout absorption 变成巨大函数。

### 3.12 HierarchyInfo Rule（不可用于算法）

`activity-schedule` 的输入目标 graph 已经要求不含 hierarchical op；源码里也有 guard，遇到 hierarchical kind 会直接报错。因此不能把 module / instance hierarchy 当作可用语义信号，也不应设计 `hierarchy_net` 或按模块内外给 gain 加权。

`hier-flatten` 之后可能还残留一些扁平化 symbol、debug origin、名字前缀或 `xmrPath` 痕迹，但这些不是稳定的层级结构：

- 可以用于离线诊断 top cross-boundary-activation-work root 的名字族归因；
- 可以用于人工报告里解释某些 boundary 来自哪个扁平化名字前缀；
- 不进入 merge-hint group；
- 不参与 merge candidate 生成；
- 不参与 gain / tie-break。

若后续确实需要层级信息，必须在 flatten 前显式保留可靠的 origin metadata，并先证明它在完整 XiangShan 上覆盖稳定、不会被 `strip-debug` / `hier-flatten` / `instance-inline` 改写破坏。首版 CrossBoundaryActivationWork 不依赖这条路。

### 3.13 规则优先级

多条规则命中同一 op / atom 时按以下顺序处理：

1. `CanonicalValueInvariant` evaluator / use-group invariant；
2. `RegToMemIntentGroup` seed group；
3. `FanoutFreeCone` seed group；
4. `AggregateAccessGroup` seed group；
5. `PassthroughChain` small seed group；
6. `PlainStructuralHint` / `GuardContextGroup` / `DownstreamSinkGroup` merge-hint group；
7. `SupernodeResourceBudget` cap；
8. `ValueUseGroup` primary objective 始终生效。

若 seed group 互相重叠：

- 完全包含：取更强规则的 atom，另一个规则只生成 merge-hint group；
- 部分交叉：不建交叉 seed group，降级为 merge-hint group + diagnostic；
- 与 DAG 无环冲突：拆成 topo-contiguous atom，atom 间 merge-hint group 保留语义。

---

## 4. 算法框架

### Phase A：构建 directed value-use graph 与精确 evaluator

先实现一个与算法无关的 evaluator。给任意 partition，输出：

- `cross_boundary_target_count`
- `supernode_dependency_edge_count`
- `compute_materialized_value_target_count`
- `cross_boundary_value_bytes`
- `cross_boundary_consumer_use_count`（诊断，不进主验收）
- source-kind / target-kind matrix：compute / commit target 拆分，source / state_read / memory_read / constant / compute-like source 拆分
- per-supernode resource vector / `resource_pressure`
- quotient DAG 是否有环
- plain-vs-candidate diff report：总量 delta、按 kind delta、top worsening roots、top improvement roots

这是后续所有实验的硬尺子。没有 evaluator，不进入算法实现；没有 plain replay，不进入新 materialization。

复杂度要求：

```text
O(|V| + |value_use_count|)
```

数据结构：

- value use group CSR：`net_offsets`, `use_group_compute_consumers`, `use_group_fixed_terminal_targets`, `use_group_producer_atom`;
- atom-to-supernode array：`supernode_of[atom]`;
- 临时 hash 只用于每个 group 的 target supernode 去重，不能全局 all-pair。

### Phase B：语义 annotation pass

在线性拓扑 / 反向拓扑中按 §3 的规则计算：

- `ValueUseGroup Rule`：canonical value id、`ValueUseGroup(producer, consumers, width_bucket)`；
- `CanonicalValueInvariant Rule`：source clone 合并、canonical producer、target-kind 拆分的硬 invariant；
- `RegToMemIntentGroup Rule`：intent group 的完整性、row / elementWidth / elementCount；
- `FanoutFreeCone Rule`：MFFC / fanout-free cone rep 与 resource-budget split；
- `PlainStructuralHint Rule`：plain out1 / in1 / siblings 结构 hint，只进入 candidate；
- `AggregateAccessGroup Rule`：concat / slice aggregate family、row / field / lane；
- `GuardContextGroup Rule`：bounded guard signature 与 `unknown/union` 降级标签；
- `DownstreamSinkGroup Rule`：downstream sink label、operand role、`multi_sink` 降级标签；
- `PassthroughChain Rule`：passthrough / representation chain；
- `SupernodeResourceBudget Rule`：op kind / width bucket / helper / branch / footprint 估计；
- `HierarchyInfo Rule`：仅诊断用名字族 label，不进入 merge-hint group。

输出语义统计：

- value use group fanout 分布、top cross-boundary-activation-work value roots；
- seed group 规则命中数与 resource-budget split 数；
- plain out1 / in1 / siblings hint 命中数、top-k gain 估计、与 top boundary roots 的重叠；
- guard domain 数量、top guard fanout、unknown/union 比例；
- aggregate family 数量、top aggregate fanout、seed/hint 命中比例；
- sink-cone exact / multi_sink 比例、按 operand role 拆分；
- passthrough chain 命中数；
- resource-pressure 预估分布；
- MFFC coverage；
- merge-hint group member-count distribution。

这一步不改变 partition。

### Phase C：atom builder

atom builder 的目标是把完整 XiangShan 的约 5M 级 op 压到可 coarsen 的初始规模，同时不制造环和超大 compute supernode。

优先顺序：

1. semantic seed group：reg-to-mem intent、必须保持 atomic 的 source clone / aggregate access 形态；
2. MFFC / fanout-free cone atom：受 supernode resource budget 限制；
3. pure passthrough atom：assign / slice / concat / trivial cast 等只改变表示的链；
4. guard-local small atom：同一 guard 下的小型局部 cone。

若某个语义 atom 超过 resource budget，按拓扑连续段或 dominance frontier 拆分，不允许生成无上限的 compute supernode。

产物必须满足：

- atom 内部 op 有合法 topo order；
- atom quotient DAG 无环；
- 每个 atom 有 `resource_vector / resource_pressure / semantic signatures`。

### Phase D：cross-boundary-activation-work-first 多级 coarsening

在 atom quotient directed value-use graph 上做多轮 contraction。每次 merge 候选 `a,b` 的 gain 使用真实指标的局部增量：

```text
Gain(a,b) =
  PartitionCost(P) - PartitionCost(P with a,b contracted)
```

只需要检查 incident use groups：

```text
incident(a) ∪ incident(b)
```

候选来源以 value-use graph + merge hints 为主；plain out1 / in1 / siblings 只作为一种 structural hint 进入候选队列，不能绕过真实 gain：

1. **heavy value use group candidate**：同一个 high-fanout value 的 producer atom 与 top-k consumer supernode。
2. **consumer co-location candidate**：同一个 high-fanout value 的多个 consumer supernode，若合并能降低 `cross_boundary_target_count/supernode_dependency_edge_count/compute_materialized_value_target_count` 或为后续 producer merge 创造条件。
3. **plain structural candidate**：当前 plain 能稳定发现的 out1 / in1 / sibling pair，用 NO0210 的 evaluator 裁决。
4. **guard merge hint candidate**：同一 guard domain 下、且 real cross-boundary activation work 不变差的 atom pair。
5. **aggregate merge hint candidate**：同一 aggregate row/lane/family 下的 producer-consumer 或 sibling atoms。
6. **sink-cone candidate**：同一 downstream sink family 的局部 atoms。
7. **dominance candidate**：MFFC / post-dominator cone 中被 resource budget 拆开的相邻 atom。

注意：本阶段的初始 partition 来自 CBAW atom builder / ATE safe merge 的结果，不来自 plain partition。plain structural candidate 只是候选生成器之一，和 heavy value-use / aggregate / MFFC candidate 平级；接受与否只看 CBAW evaluator 和 gate。

候选不做 clique 展开。每个 group 只保留 top-k：

```text
k = small constant, e.g. 4 or 8
```

排序策略：

- 第一关键字：`Δcross_boundary_target_count`
- 第二关键字：`Δsupernode_dependency_edge_count`
- 第三关键字：`Δcompute_materialized_value_target_count`
- 后续才是 `Δcross_boundary_value_bytes / Δsupernode_resource_pressure / Δsemantic_split_penalty`

接受规则：

- 默认只接受词典序正 gain；
- 允许 semantic plateau merge：真实 `cross_boundary_target_count/supernode_dependency_edge_count/compute_materialized_value_target_count` 不变差，但 semantic split 降低且 supernode count / resource pressure 不恶化；
- 不接受“weighted 或 semantic 变好但 cross-boundary activation work 明显变差”的 merge。

首版 MVP 应限制 merge 形状，先降低无环检查和 materialize 风险：

- 允许 producer-consumer 直接相邻 merge；
- 允许 MFFC / dominance split 的 topo-contiguous 相邻段 merge；
- 允许 aggregate / passthrough 的 topo-convex 小范围 merge；
- 允许 plain out1 / in1 / sibling pair merge；
- 暂缓非局部 consumer co-location、跨 sink-cone 大范围合并、guard-domain 内无直接 value 关系的合并。

每类 candidate 必须单独统计：

```text
generated, evaluated, accepted,
rejected_no_gain, rejected_cycle, rejected_resource,
rejected_semantic, stale, elapsed_ms
```

若某类 candidate 的 `rejected_cycle` 或 `stale` 占比过高，应先调整 candidate 生成，而不是继续放宽 accept gate。

### Phase E：DAG 无环 contraction 检查

contract DAG 顶点可能制造 quotient cycle。例如 `a -> x -> b` 且 `a -> b` 时，直接合并 `a,b` 会产生 `M -> x -> M`。

每次 merge 必须过无环检查：

1. topo interval 快速剪枝：若两个 candidate supernode 的 topo 区间不重叠且不存在反向 reachability 风险，直接通过；
2. incident path check：检查是否存在从 `a` 到 `b` 的外部路径或从 `b` 到 `a` 的外部路径；
3. bounded BFS / dynamic reachability：只在候选 gain 足够高时做更贵检查；
4. batch 后全局 Kahn 校验作为 backstop，失败则回滚本 batch。

长期可以维护动态 topological order。第一版可采用“保守拒绝多、绝不放环”的策略。

### Phase F：cross-boundary-aware refinement

coarsening 到稳定后，做 k-way refinement。移动单位不是单 op，而是 boundary atom；必要时也可以移动一个已经形成的小型 compute supernode。

候选 move：

```text
atom c: current supernode A -> neighboring supernode B
```

只考虑 `c` 的 incident use groups，计算精确 `PartitionCost` delta，并检查：

- `B` 的 `resource_pressure` 不超过 budget；
- `A` 不变成非法空 supernode 或破坏 semantic seed group；
- quotient DAG 无环。

Refinement 类型：

1. **cross-boundary-activation-work FM**：FM / KL 风格边界移动，主 gain 仍是 `cross_boundary_target_count/supernode_dependency_edge_count/compute_materialized_value_target_count`。
2. **hyperedge absorption**：对高 fanout value，尝试把多数 consumer supernode 收敛到 producer supernode 或少数 target supernode。
3. **local exact cut**：对 top cross-boundary-activation-work 的局部 ROI，构造小型 min-cut / maxflow 问题，求局部最优后回填。ROI 必须小，例如 `<= 10k atoms`。

注意：refinement 不要求 supernode 是 topo 连续区间，但必须保证 quotient DAG 无环。

### Phase G：输出 materialization

输出是 arbitrary acyclic supernode partition：

- 每个 supernode 内按全局 topo 排序 emit；
- supernode 间按 quotient DAG topo order 调度；
- 不依赖 DP 连续分段；
- 不触碰 commit supernode / fixed-point 调度。

若现有 materialize 路径要求某些中间结构连续，应改 materialize 接口，而不是让算法退回 1-D DP。

---

## 5. 为什么这比 prob 路线更贴近问题

### 5.1 cross-boundary activation work 是目标，不是副作用

prob 路线的目标大致是：

```text
minimize Σ p(e) * W(succ)
```

这会出现两个问题：

- `p(e)` 不经过 runtime profile 不可靠；
- 即使 weighted cut 降了，真实 `cross_boundary_target_count/supernode_dependency_edge_count/compute_materialized_value_target_count` 可能上升。

CrossBoundaryActivationWork 的目标是：

```text
minimize cross_boundary_target_count / supernode_dependency_edge_count / compute_materialized_value_target_count directly
```

概率可以作为报告字段或 tie-breaker，但不能主导 merge 接受。

### 5.2 使用 value-use group，而不是普通 graph edge-cut

cross-boundary activation work 本质是 value producer/consumer 分布问题。普通二元边只看 `u -> v`，不能表达“一个 value 被 100 个 consumer 分散到多少个 supernode”。value-use group 可以精确表达：

- producer supernode；
- consumer supernode set；
- cross-boundary target count；
- target supernode count；
- compute materialized value target count。

这比 plain 的 edge count 或 prob 的 weighted pair 更接近最终 stats。

### 5.3 语义用于找对候选，而不是猜概率

transition-density `π` 仍是启发式；guard / aggregate / sink-cone / MFFC 是静态语义事实。它们不告诉我们 workload 中某条边多热，但能告诉我们哪些 op 属于同一个结构域、控制域或数据结构域。

这类信息更适合用于：

- 候选生成；
- tie-break；
- seed group / merge hint group；
- 防止 aggregate 被切碎；
- 防止同 guard 代码跨很多 supernode 重复。

---

## 6. 完整 XiangShan 规模策略

### 6.1 复杂度红线

允许：

- 一次或少数几次 topo / reverse topo；
- 按 value use group 的 CSR 遍历；
- 每个 group top-k candidate；
- lazy priority queue / bucket queue；
- 局部 incident-use-group gain 重算。

禁止：

- atom all-pair；
- 每个 root 做全图 DFS；
- 每轮全量重建所有 candidates；
- 对 high-fanout value use group 做完整 clique；
- 依赖 full runtime profiling 才能产出 partition。

### 6.2 数据结构

建议：

```text
atom_parent: union-find id for current supernode assignment
supernode_metrics: resource_vector, resource_pressure, topo_min, topo_max
use_group_producer: atom id
use_group_compute_consumers: CSR atom ids
use_group_fixed_terminal_targets: CSR supernode ids
use_group_width_bucket
supernode_incident_use_groups: compressed adjacency or rebuilt lazily
merge_hint_groups: same CSR representation, but only used for candidate hints
candidate_queue: bucketed by Δcross_boundary_target_count / Δsupernode_dependency_edge_count first, lazy validate
```

大数组优先用 32-bit id；只有计数和累计成本用 64-bit。

### 6.3 High-Fanout ValueUseGroup 处理

高 fanout value 是 cross-boundary activation work 爆炸的核心风险。对这类 value use group：

- 不展开 consumer clique；
- 统计 consumer supernode top-k；
- 优先尝试 producer-to-heavy-consumer 或 consumer-supernode co-location；
- 若 fanout 过大且无法合并，记录为不可消除 boundary root，供诊断报告定位。

### 6.4 局部 exact optimizer 的使用边界

可以对 top cross-boundary-activation-work 的局部 ROI 用 min-cut / maxflow 做精修，但必须满足：

- ROI 从一个或少数 high-cross-boundary-activation-work value use group 扩展 1-2 hop；
- ROI atom 数有硬上限；
- 求解结果仍要过 DAG 无环和 resource budget；
- 只作为 refinement，不作为全图主算法。

---

## 7. Kill Criteria

以下任一成立，应停止当前实现方向，而不是继续调参：

1. 完整 XiangShan 上 evaluator 无法在线性或近线性时间跑完。
2. evaluator plain replay 不能与现有 plain stats 对齐，且差异无法归因。
3. semantic annotation 的 top domains 与 top cross-boundary-activation-work roots 基本无关，说明语义信号没有打到边界问题。
4. plain structural hint 也无法覆盖 plain 已经消除的大量低风险 boundary，说明 atom/materialize 表达有缺陷。
5. cross-boundary-activation-work-first coarsening 后 `boundary_activation_edges / dag_edges / compute_compute_value_pairs` 任一显著高于 plain。
6. 无环检查导致大量高 gain candidate 被拒，说明 candidate 设计不适合 DAG contraction，需要改 atom / convexity 策略。
7. candidate accounting 显示某类候选长期 `stale/rejected_cycle/rejected_resource` 主导，继续调 gain 不会解决问题。
8. 为降低 cross-boundary activation work 制造少数超大 supernode，导致 `resource_pressure`、build time 或 emitted code size 明显失控。
9. structure gate 未过却想进入 50k runtime。禁止重复 NO0209 的流程错误。
10. 完整 XiangShan 上 trigger 签名高度饱和、等触发集等价桶覆盖率过低（§9.7 / P1 未过），说明 ATE 退化，应停止强推 trigger 合并、回到纯 net-cut 主线，而不是放宽签名阈值凑覆盖。
11. 为降低边界接受了使全局 `Σ_S |trigger(S)|` 显著上升的合并（over-eval 抬升），即使 `boundary_activation_edges / dag_edges` 更好也必须回滚——这是 NO0067 / NO0086 / NO0085 式的粒度 / 抬频回退，不能进 runtime。

---

## 8. 与现有路线的关系

- [`NO0207`](./NO0207_activity_schedule_prob_partition_upgrade_plan_20260625.md)：保留其中 `π/cost/hypergraph` 的工程经验，但不继承“概率主目标”。
- [`NO0208`](./NO0208_activity_schedule_prob_partition_rollout_progress_20260625.md)：可复用 canonical source clone、cost bucket、hypergraph aggregate、MFFC coverage 等基础设施；prob gain / mixed DP / FM weighted objective 不作为主线。
- [`NO0209`](./NO0209_prob_fm_runtime_failure_reflection_20260628.md)：其 plain-first gate 教训保留为验收纪律；新算法可以把 plain out1 / in1 / siblings 作为 structural hint 复用，但不由 plain 规则裁决 merge，最终仍以真实 cross-boundary 指标和 resource / acyclic gate 为准。
- [`NO0206`](./NO0206_commit_activation_mask_group_plan_20260624.md)：正交。本文只做 compute partition；commit mask group 仍是单独 runtime 大头方向。

---

## 9. 激活触发等价（ATE）合并：profile-free 的 over-eval 防护

§2.6 指出 §2.3 目标对 `f·E` 失明。ATE（Activation-Trigger Equivalence）是对 §4 算法的**合并接受准则**扩展，不替换 cross-boundary net-cut 主目标，只在其上加一层 profile-free 的 over-eval 防护。它不引入概率，也不使用任何 runtime profile。

### 9.1 trigger 集合与签名

定义见 §2.6。实现要点：

- 在 Phase C atom builder 之后、Phase D coarsening 之前，跑一次 trigger 签名 pass；
- 每个 atom / supernode 持有定宽签名（建议 16-32 路 MinHash，或 64-128 bit Bloom），reverse-topo 一次传播；
- 签名只用于快速判等 / 判子集；被签名命中的候选必须在小候选集上做一次**精确 trigger 集合复核**再接受，避免 MinHash 误判抬频；
- trigger 只计 volatile source（state-read / memory-read），与 §2.2 的 source-kind 口径一致；常量与纯 representation 透传不计入；
- **饱和风险**：深逻辑里 trigger 可能退化成近全集，使判别力归零。这是 ATE 的生死点，必须先验（§9.7 / §11.3 P1）。

### 9.2 Keystone 定理：等触发集合并是 profile-free 的 Pareto 改进

```text
若 trigger(A) = trigger(B) = τ：
  f(A) = f(B) = f(M) = P(τ 变化)          # 同触发集 ⇒ firing 率必然相等
  E(M) = E(A) + E(B)
  ⇒ f(M)·E(M) = f(A)·E(A) + f(B)·E(B)      # eval 项精确不变
同时：A↔B 间边界边内化、A_succ 对共同后继去重、N 减 1（A_exam 降）
  ⇒ T 严格下降（无共享边界时持平）
```

关键：`f` 在等式中被约掉，**全程不需要它的数值**。所以“穷尽所有等触发集合并”在 [`NO0190`](./NO0190_grhsim_gsim_unified_cost_model_comp_src_sink_plan_20260612.md) 成本模型下是 **profile-free、可证明不增加 runtime** 的粗化。这是纯 net-cut 主目标给不出的保证——后者会无差别接受抬频合并。

### 9.3 子集与 disjoint 情况

```text
trigger(A) ⊆ trigger(B) ⇒ f(M) = f(B)
  Δeval = E(A)·(f(B) − f(A)) ≥ 0          # A 被拖到 B 的 firing 率
```

无 profile 时 `(f(B)−f(A))` 的绝对值未知，但**符号已知（≥0）**，且随 `E(A)` 与 trigger 差 `|trigger(B)\trigger(A)|` 单调。接受规则：

- 子集合并只在 `E(A)` 很小（便宜 atom，没多少可空转）或 trigger 差很小（`f(B)≈f(A)`）时接受；
- **disjoint trigger 的合并一律拒绝**（`f(M) ≈ f(A)+f(B)`，两侧都空转，over-eval 最大），即使它能大幅降边界。这正是 §2.6 列举的历史回退动作，net-cut 主目标会接受、ATE 拒绝。

### 9.4 频率分层粒度（启发式层，需 gate）

用 `|trigger(a)|` 作 `f` 的**单调代理**（触发集大 ⇒ 多半高频）：

- 高 `|trigger|` 区域：高频、无稀疏性可保护 ⇒ 放心粗化到 resource budget；
- 低 `|trigger|` 且彼此 disjoint 区域：低频 ⇒ 保持细粒度，保护激活稀疏性。

这与“对全图一律往 cap 粗化”相反，是**热区粗、冷区细**。注意：`|trigger|` 作 f 代理是弱的（单个超热 trigger 会破坏单调性），所以本层仅为启发式，必须靠 §9.5 的 gate 兜底；**只有 §9.2 的等触发集合并是定理级安全的**。

### 9.5 与 §4 阶段接线

- **Phase C 后**：插入 trigger 签名 pass（§9.1）。
- **Phase D**：合并接受准则改为两段——先穷尽等触发集合并（§9.2，纯赚），再进入 cross-boundary net-cut 候选；net-cut 候选的 gain 在 §2.3 词典序之后追加 over-eval 惩罚项 `∝ E·Δ|trigger|`（§9.3），并对 disjoint-trigger 合并设硬否决。
- **Phase F**：FM 边界 move 带 trigger 约束，禁止把 atom 移进会显著抬升其 `|trigger|` 的 supernode。
- **§11.10 gate**：在 plain 结构地板之外，增加 **trigger 膨胀地板**——任何使全局 `Σ_S |trigger(S)|` 相对 plain 显著上升的方案不得进 runtime（over-eval 的 profile-free 上界代理）。

### 9.6 与 NO0200 的关系

[`NO0200`](./NO0200_commit_shared_guard_group_emit_plan_20260615.md) 在 commit 路径按 **event + guard** 分组，本质就是按 trigger 签名分组的特例，并已实测正向（two-level event supernode 把 50k 从 `408948ms` 提到 `318117ms`，capped 版 `321436ms`）。ATE 是把该成功从 commit 路径推广到 compute 路径的一般化：**“按共享激活条件合并 ⇒ runtime 改善” 在本代码库已有正向实测，而 “纯降边界 / 纯加粒度” 已有 NO0067 / NO0086 / NO0134 的负向实测。** 这是 ATE 相对纯 net-cut 主目标在本仓库证据上的不对称优势。

### 9.7 风险与首验实验

ATE 自身风险：

1. `|trigger|` 作 f 代理弱——只有等触发集合并是定理安全，分层是启发式；
2. MinHash 判等近似——须精确复核；
3. **trigger 饱和**——最大威胁，可能使全部 atom trigger 近全集、等价桶碎成单点。

因此 ATE **第一步不是写划分器**，而是 §11.3 P1 的纯静态前验（zero profile / zero build）：只跑 trigger 签名 pass，量 (a) atom trigger 基数分布是否“少数小触发集 + 长尾”而非整体饱和；(b) 等触发集等价桶能覆盖多少 atom、能内化掉 plain 多少 `boundary_activation_edges`。若饱和、覆盖率过低 ⇒ ATE 退化，回纯 net-cut 主线（§7 Kill 10/11）；若存在大量等触发集结构 ⇒ 优先落地 §9.2 的定理级安全合并。

---

## 10. 当前结论

下一条 compute partition 主线应从“概率驱动”切换到“cross-boundary-activation-work-first directed value-use partition”：

```text
真实 value-use graph
  + merge hint groups / plain structural hint / guard / aggregate / sink-cone / MFFC
  + 精确 cross_boundary_target_count / supernode_dependency_edge_count / compute_materialized_value_target_count 词典序目标
  + ATE 等触发集合并（profile-free over-eval 防护，§9）
  + acyclic contraction
  + cross-boundary-aware refinement
```

这条路线的关键不是复刻 plain，也不是继续修 prob，而是让数学目标直接对准 NO0209 暴露的失败指标：**跨边界 activation 和 quotient DAG 边不能爆炸**。语义信息的职责是帮助算法找到更好的合并候选和更稳定的 atom，而不是替代 real cross-boundary activation work 指标。

工程入口上也应保持同样边界：CBAW 是 plain、prob/FM 之外的第三条平行路径。plain gate 决定“能不能进 build/runtime”，plain replay 证明“新 materialize 接口没有引入统计偏差”，plain hint 只提供“局部候选”；三者都不能把 CBAW 降级为 plain 的修补 pass。

此外，net-cut 主目标对 firing-frequency × eval 的 over-eval 项失明（§2.6）；ATE 用 profile-free 的 trigger 等价（§9）补上这一项，并以等触发集合并的 Pareto 定理保证不抬升 runtime。整条路线全程不使用 runtime profile：firing 成本只通过静态 trigger 集合结构表达，绝对频率 `f` 在安全合并的代价计算中被约掉，从根上回避了 NO0207–NO0209 “静态 π 不可靠 / 需要 profile 才能定频率” 的死结。

---

## 11. 最终按阶段实施计划（覆盖全部 feat）

本节是落地时的唯一阶段顺序。§4 给算法流水线，§9 给 ATE 接线；本节把它们收敛成可执行的 feat 列表。每个阶段都必须保持 **compute-only、profile-free、plain-gated、近线性**。任何阶段未过结构 gate，不进入 build/runtime。

实现形态必须保持 **plain / prob/FM / CBAW 三入口并列**：P0/P3 的 plain replay 只用于 evaluator/materialize 校验，P5 之后的 CBAW coarsen/refine/output 不允许依赖 plain partition 作为初始解或后处理对象。

### 11.1 feat 覆盖清单

| feat | 内容 | 覆盖章节 | 阶段 |
| --- | --- | --- | --- |
| `feat-evaluator` | directed value-use graph、精确 evaluator、plain replay、source/target kind matrix、top worsening/improvement report | §2.2、§3.2、§3.5、§4 Phase A | P0 |
| `feat-resource-budget` | resource vector、plain p99/p99.5 cap 校准、`resource_pressure` hard gate、拒绝原因统计 | §2.4、§3.11、§4 Phase A/D | P0/P3 |
| `feat-trigger-ate-readonly` | trigger 签名传播、等触发桶统计、饱和度与 ATE go/no-go | §2.6、§9.1/9.7、§11.3 | P1 |
| `feat-semantic-annotation` | rtm intent、MFFC、plain hints、aggregate、guard、sink-cone、passthrough、hierarchy debug label 的只读统计 | §3、§4 Phase B | P2 |
| `feat-atom-builder` | semantic seed、MFFC/passthrough atom、resource split、atom quotient DAG 校验 | §3.3/3.6/3.7/3.10、§4 Phase C | P3 |
| `feat-plain-materialize-replay` | 用新 atom/partition/materialize 接口独立回放等价 plain，证明接口本身不改 stats；该 replay 不作为 CBAW 初始解 | §4 Phase G、§11.5 | P3 |
| `feat-ate-safe-merge` | 等触发集合并、精确 trigger 复核、`Σ|trigger|` 膨胀统计、disjoint-trigger hard reject | §9.2/9.3/9.5、§11.6 | P4 |
| `feat-cbaw-coarsen-mvp` | heavy value-use、plain out1/in1/siblings、aggregate、MFFC/dominance 四类候选；真实 gain；lazy candidate accounting | §4 Phase D、§6.2/6.3、§11.7 | P5 |
| `feat-acyclic-contraction` | topo interval、incident path check、bounded BFS、batch Kahn backstop、rollback | §2.4、§4 Phase E | P5 |
| `feat-guard-sink-candidates` | guard-domain 与 sink-cone 候选接入，只允许真实主指标不变差或改善 | §3.8/3.9、§11.8 | P6 |
| `feat-fm-refine` | boundary atom move、hyperedge absorption、trigger-aware move gate、resource/cycle 检查 | §4 Phase F、§9.5、§11.9 | P7 |
| `feat-local-exact-roi` | top cross-boundary roots 的小 ROI min-cut/maxflow 精修，受 size/time hard cap | §6.4、§11.9 | P7 |
| `feat-output-materialization` | arbitrary acyclic supernode partition 输出，supernode 内 topo emit，quotient DAG topo 调度 | §4 Phase G | P8 |
| `feat-structure-runtime-gate` | plain gate、trigger 膨胀 gate、candidate accounting、correctness smoke、build/runtime gate | §7、§9.5、§11.10 | P8 |
| `feat-reporting-doc` | 阶段报告、top root 归因、kill criteria 判定、后续是否拆文档 | §5、§7、§8 | 全阶段 |

### 11.2 阶段 P0：地基尺子

目标：先把“能不能量准”解决，不改 partition。

- 实现 `feat-evaluator`：从 compute 子图构建 `ValueUseGroup` CSR，按任意 partition 复算 `cross_boundary_target_count / supernode_dependency_edge_count / compute_materialized_value_target_count / cross_boundary_value_bytes / cross_boundary_consumer_use_count`。
- 实现 `CanonicalValueInvariant` 小图测试：source clone 合并、compute+commit target 拆分、clone width 不一致诊断。
- 实现 `feat-resource-budget` 的只读部分：统计 plain compute supernode 的 resource 分布，给出默认 cap 来源和 baseline exception。
- 输出 plain-vs-candidate diff report，但本阶段 candidate 只是现有 plain / prob / 旧路径的只读对照回放，不生成 CBAW 初始解。

出门槛：

- plain replay 的 `boundary_activation_edges / dag_edges / compute_compute_value_pairs` 对齐现有 stats，或差异有逐项归因；
- evaluator 在完整 XiangShan 上近线性跑完；
- resource cap 不使用拍脑袋常量，至少来自 plain p99 或 p99.5 分布。

### 11.3 阶段 P1：ATE 前验

目标：判断 trigger 路线是否有判别力，不写划分器。

- 实现 `feat-trigger-ate-readonly`：reverse-topo 传播 volatile source trigger 签名，统计 `|trigger|` 分布、等触发桶数量、桶覆盖 atom 比例、近全集饱和比例。
- 对 plain partition 估计“等触发桶若全合并”可内化的 `boundary_activation_edges` 上界；这只是 ATE 判别力评估，不把 plain partition 作为 P4/P5 输入。
- 输出 ATE go/no-go：只允许启用等触发集合并；子集/分层合并仍留到后续 gate。

出门槛：

- 若 trigger 大面积饱和或等触发桶覆盖过低，P4 的 ATE merge 默认关闭，只保留 trigger 膨胀 gate；
- 若存在足够等触发桶，P4 优先落地定理级安全合并。

### 11.4 阶段 P2：语义只读统计

目标：把所有语义规则先做成 annotation 和 report，禁止影响 partition。

- 实现 `feat-semantic-annotation`：`RegToMemIntentGroup / FanoutFreeCone / PlainStructuralHint / AggregateAccessGroup / GuardContextGroup / DownstreamSinkGroup / PassthroughChain / HierarchyInfo`。
- 每条规则只输出 `SeedGroup / MergeHintGroup / DebugLabel` 统计，不生成新 supernode。
- 给 top cross-boundary roots 归因：哪些来自 high-fanout value、rtm/aggregate、guard、sink-cone、passthrough、plain structural shape。

出门槛：

- 完整 XiangShan annotation 近线性；
- semantic domains 与 top cross-boundary roots 有可解释重叠；
- hierarchy/name prefix 只出现在 debug label，不进入 candidate 或 gain。

### 11.5 阶段 P3：atom 与接口闭环

目标：建立新算法的初始 atom 层，并证明 materialize 接口可承载非旧路径结构。

- 实现 `feat-atom-builder`：按 `RegToMemIntentGroup`、MFFC、aggregate/passthrough small seed、guard-local small atom 构建 atom。
- 对超 cap seed 做 topo-contiguous 或 rule-specific split，并产生对应 merge hint。
- 实现 atom quotient DAG 校验和每 atom resource vector。
- 实现 `feat-plain-materialize-replay`：用新接口表达等价 plain partition，先不启用新 coarsen；该 replay 与 CBAW atom 闭环并行校验，不作为后续 merge 起点。

出门槛：

- atom quotient DAG 无环；
- atom 数、resource 分布、split 统计可解释；
- 等价 plain materialization 不单独引入 stats 差异。

### 11.6 阶段 P4：ATE 安全合并

目标：只落地 profile-free 可证明安全的 trigger 合并，作为 net-cut 前的低风险粗化。

- 实现 `feat-ate-safe-merge`：仅对 `trigger(A) == trigger(B)` 的候选做合并，签名命中后必须精确集合复核。
- 合并仍过 resource budget 和 acyclic contraction。
- 对 `trigger(A) ∩ trigger(B) = empty` 的 candidate 加 hard reject 标记；子集合并默认不开，只输出 hypothetical gain。
- 统计 `Σ_S |trigger(S)|`，作为后续所有阶段的 over-eval gate。

出门槛：

- ATE merge 后三项主结构指标不高于 P3 CBAW atom baseline；
- `Σ_S |trigger(S)|` 不显著高于 P3 CBAW atom baseline；
- 若收益低或饱和，关闭 ATE merge，不阻塞 P5 纯 net-cut 主线。

### 11.7 阶段 P5：CBAW coarsen MVP

目标：实现主算法最小闭环。

- 实现 `feat-cbaw-coarsen-mvp` 四类 candidate：heavy value-use、plain structural hint、aggregate hint、MFFC/dominance hint。
- CBAW 初始解来自 P3 atom builder 与 P4 ATE safe merge；plain structural hint 只生成候选，不读取 plain partition 结果，不要求沿 plain 边界修补。
- gain 只用 incident use groups 精确计算，排序按 `cross_boundary_target_count`、`supernode_dependency_edge_count`、`compute_materialized_value_target_count` 词典序。
- 实现 `feat-acyclic-contraction`：topo interval 快速剪枝、incident path check、bounded BFS、batch Kahn 校验。
- 每类 candidate 输出 `generated/evaluated/accepted/rejected_no_gain/rejected_cycle/rejected_resource/rejected_semantic/stale/elapsed_ms`。

出门槛：

- 完整 XiangShan stop-after activity-schedule 通过；
- quotient DAG 无环；
- 进入 build/runtime 前，`boundary_activation_edges / dag_edges / compute_compute_value_pairs` 必须全部 `<= plain`；MVP smoke 可先接受 `<= plain * 1.02` 只用于定位下一步候选缺口，不进入 runtime。

### 11.8 阶段 P6：补齐 guard / sink-cone 候选

目标：接入剩余语义 candidate，但不放宽主目标。

- 实现 `feat-guard-sink-candidates`：同 guard 且有 value-use 关系、同 sink label 且 role compatible 的局部 candidate。
- `unknown / union_guard / multi_sink` 只做诊断。
- semantic split penalty 只能做 plateau tie-break；不允许主指标回退。

出门槛：

- top guard / sink-cone domain 的 cut 数下降或持平；
- candidate rejected_cycle/stale 不失控；
- 三项主结构指标和 `Σ|trigger|` 不回退。

### 11.9 阶段 P7：refinement 与局部 exact

目标：在已稳定的 coarsen 结果上做局部精修。

- 实现 `feat-fm-refine`：boundary atom move、producer/consumer hyperedge absorption、trigger-aware move gate、resource/cycle 检查。
- 实现 `feat-local-exact-roi`：只对 evaluator 报告的 top cross-boundary roots 扩 1-2 hop，ROI atom 数和求解时间有硬上限。
- 每轮 refinement 输出 before/after、move 数、三项主指标 delta、trigger delta、拒绝原因。

出门槛：

- refinement 后主指标相对 coarsen 后降低或持平；
- 不因少数巨大 ROI 卡死；
- 不接受降低边界但显著抬升 `Σ|trigger|` 的结果。

### 11.10 阶段 P8：输出、build 与 runtime gate

目标：把 arbitrary acyclic partition 接到最终输出，并只让结构合格结果进入 runtime。

- 实现 `feat-output-materialization`：supernode 内按全局 topo emit，supernode 间按 quotient DAG topo 调度，不依赖 1-D DP 连续分段。
- 实现 `feat-structure-runtime-gate`：plain gate、trigger 膨胀 gate、resource gate、candidate accounting gate、correctness smoke。
- 对通过结构 gate 的结果执行 build 和 smoke；再进入 CoreMark 50k runtime。
- 实现 `feat-reporting-doc`：记录本阶段结构数据、runtime 数据、top root 归因、kill criteria 是否触发。

出门槛：

| 指标 | 硬要求 |
| --- | --- |
| `boundary_activation_edges` | `<= plain`，目标 `<= plain * 0.95` |
| `dag_edges` | `<= plain` |
| `compute_compute_value_pairs` | `<= plain` |
| `Σ_S |trigger(S)|` | 不显著高于 plain；若高于 plain，禁止进入 runtime |
| `max_resource_pressure` | `<= 1.0` 或命中显式 baseline exception |
| quotient DAG | 无环 |
| correctness smoke | 通过 |
| candidate accounting | 每类 candidate 拒绝原因和耗时完整输出 |

### 11.11 推荐提交切分

建议按下面顺序提交，保证每个 commit 都有可单独验证的 feat：

1. `feat: add cbaw evaluator and plain replay metrics`
2. `feat: add compute supernode resource pressure calibration`
3. `feat: add trigger signature read-only analysis`
4. `feat: add cbaw semantic annotation reports`
5. `feat: build cbaw atom seeds and plain materialize replay`
6. `feat: add activation-trigger-equivalent safe merge`
7. `feat: add cbaw coarsening mvp`
8. `feat: add acyclic contraction checks for cbaw`
9. `feat: add guard and sink-cone cbaw candidates`
10. `feat: add cbaw boundary refinement and local roi exact cut`
11. `feat: materialize arbitrary acyclic cbaw partitions`
12. `feat: add cbaw structure and runtime gates`

任何阶段如果触发 §7 kill criteria，应先提交诊断报告或回滚该 feat 的默认启用开关；不要把未过 gate 的 partition 送入 runtime。
