# NO0093 GrhSIM Activity-Schedule 迁移 ESSENT MFFC Coarsen 方案

> 2026-05-18 规划在 `grhsim` 的 `activity-schedule` 中复刻 ESSENT 的 acyclic partition / coarsen 思路，替换当前弱 coarsen 主路径。目标是先把 compute 入口图改成接近 FIRRTL/ESSENT 语义的 MFFC 初始 compute supernode DAG，再在该 DAG 上用面向 XiangShan 大规模图的高性能数据结构和 merge 策略降低 boundary value / BAE，最终推动 XiangShan `grhsim` 从当前约 `120 cycles/s` 继续提速。

## 1. 背景与目标

参考材料：

- 论文：`tmp/Beamer和Donofrio - 2020 - Efficiently Exploiting Low Activity Factors to Accelerate RTL Simulation.pdf`
- 参考实现：`tmp/essent/src/main/scala/{MFFC.scala,MergeGraph.scala,AcyclicPart.scala,Graph.scala}`
- 当前 GrhSIM compute-node 重构基础：[`NO0070`](./NO0070_grhsim_activity_schedule_computenode_rewrite_plan_20260505.md)
- 当前结构差距画像：[`NO0076`](./NO0076_xs_gsim_grhsim_supernode_activation_stats_20260508.md)、[`NO0087`](./NO0087_current_gsim_grhsim_quant_profile_perf_20260511.md)、[`NO0092`](./NO0092_activity_schedule_op_granularity_commit_bucket_snapshot_20260514.md)

ESSENT 的核心流程是：

1. 从 sink 节点向上做 MFFC 分解，得到天然 acyclic 的初始 partition。
2. 在 partition DAG 上按拓扑特征做 greedy merge：
   - single-parent partition 合并到 parent；
   - small siblings 合并；
   - small partition 按 common-input fraction 合并；
   - 可选向下 merge。
3. 每次 merge 必须保持 partition graph acyclic；论文中的判定条件是两个 partition 间任一方向都不存在 external path。

当前 `grhsim` 的问题不是最终 supernode 数量单独偏大。既有记录显示：

- `NO0076` 中最终 supernode 数已基本对齐，但 `boundary_activation_edges` 仍高约 `70%`。
- `NO0087` 中当前 compute coarsen 可把 `clusters_before=1,380,259` 降到 `clusters_after=1,066,173`，但合并幅度远弱于 GSim / ESSENT 风格 coarsen。
- `NO0092` 的 op 粒度路径在 `max-op=108` 下能对齐 GSim supernode 数，但 `boundary_activation_edges=2,600,941` 仍明显偏大，50k 速度只有 `106.29 cycles/s`。

因此本计划的目标不是简单调大/调小 `max-op-in-compute-supernode`，而是替换 compute 侧 coarsen 的入口图与 merge 机制，优先降低：

- compute 入口 DAG 的无效密度；
- coarsen 后 cluster 数；
- final `boundary_values`；
- final `boundary_activation_edges`，特别是同一 supernode pair 上的 duplicate activation values；
- 生成代码的 active supernode 数、动态分支与 value slot 访问次数。

## 2. 命名约定

为避免和当前代码里的 `computeSupernode` 混淆，本计划固定使用三层概念：

| 名称 | 含义 | 是否最终 emit 单元 |
| --- | --- | --- |
| initial compute supernode | 从 sink/output root 反推得到的 MFFC 风格 op 集合；对应 ESSENT 初始 partition | 否 |
| ESSENT compute supernode | initial compute supernode DAG 经 ESSENT merge 后得到的 coarsened partition | 否 |
| final compute supernode | DP / segment 之后给 `grhsim_cpp` emitter 使用的 compute supernode | 是 |

用户建议中的 “compute supernode 是 op 的集合，从 sink op 的输入 value 的 def op 开始反推” 对应本文的 initial compute supernode。

## 3. 初始 Compute Supernode 构建语义

### 3.1 Root 集合

root value 来自：

- commit/sink op 的直接输入；
- graph output port；
- graph inout port 的 `out` / `oe`；
- 必要时保留当前 test/diagnostic 需要的 observable value。

不从 declaration op 建 root。`kRegister` / `kMemory` / `kLatch` 仍是 storage declaration，不参与 compute MFFC。

### 3.2 反向建树规则

从 root value 的 defining op 反推：

1. 外部 input value：停止，作为 boundary input。
2. source op：
   - `kConstant` / `kRegisterReadPort` / `kLatchReadPort` 可复制到当前 initial compute supernode；
   - 若 source value 直接服务 commit supernode，不能复制进 commit，只保留 direct source input 依赖。
3. `kMemoryReadPort` 按普通 compute op 处理，因为地址 operand 是真实 compute dependency。
4. sink op 不允许出现在 compute 反推路径；出现则报错。
5. 普通 compute op：
   - 如果该 op 的 result 只服务当前 consumer 链，则吸收到当前 initial compute supernode；
   - 如果该 op 的输出影响超过一个 op / 一个 root consumer，则该 op 成为新的 root，建立自己的 initial compute supernode，当前节点通过 boundary value 依赖它。

这里的 “只服务当前 consumer 链” 不能直接等价于 `Value::users().size()==1`，需要按 schedule 语义归一：

- 同一 initial compute supernode 内的多次使用算一个 consumer；
- source clone 不形成跨节点 consumer；
- commit direct source input 不把 source value 变成 common expr；
- observable output 和 commit root 都算作 fanout endpoint。

### 3.3 与当前代码的差异

当前 `wolvrix/lib/transform/activity_schedule.cpp` 的 op 粒度路径先为每个 Source/Compute op 建单节点，再依赖后续 coarsen 合并；这会让 coarsen 面对过多低价值 singleton，并且合并规则不足时很难接近 ESSENT。

新路径改为：

```text
root values
  -> reverse MFFC builder
  -> initial compute supernode DAG
  -> ESSENT merge on DAG
  -> final compute supernode DP / segment
  -> existing grhsim_cpp emitter model
```

## 4. 大规模图数据结构

XiangShan 规模显著大于 ESSENT 原始 Scala 实现的典型目标，不能直接移植 `ArrayBuffer[ArrayBuffer[Int]] + distinct + recursive merge`。需要新增 C++ 高性能结构，建议命名为 `ComputeSupernodeDag` 或 `ActivityPartitionDag`，先放在 `activity_schedule.cpp` 私有命名空间，稳定后再考虑拆文件。

### 4.1 基础存储

核心字段：

| 字段 | 用途 |
| --- | --- |
| `nodeMembers` / `memberOffsets` | CSR 形式保存 node -> compute op 列表 |
| `opToNode` | op index -> initial compute supernode id |
| `valueOwnerNode` | value index -> producing node id |
| `nodeTopoPos` | node id -> topo position |
| `succOffsets/succs`、`predOffsets/preds` | node DAG CSR 邻接表 |
| `edgeValueOffsets/edgeValues` | 每条 cluster edge 对应的 boundary value 列表或 value count |
| `nodeInputValueOffsets/nodeInputValues` | node 的 external / cross-node input values |
| `nodeOutputValueOffsets/nodeOutputValues` | node 输出到其他 node / commit/output 的 boundary values |
| `activeNode` / `nodeParent` | merge 用 live 标记和 DSU parent |
| `scratchStamp` | 替代反复清空 `unordered_set` / `vector<bool>` 的 stamp 数组 |

### 4.2 构建原则

- ID 全部使用 `uint32_t`，value/op index 转换只在边界检查处做。
- 邻接表以 CSR 为主，局部候选才临时 materialize 小 vector。
- 去重使用排序 + unique 或 stamp，不在热路径使用大量 `std::unordered_set`。
- coarsen 每一 phase 后允许 rebuild CSR；单次 merge 不做复杂动态邻接维护，避免维护成本高于 rebuild。
- 所有统计先从同一套 CSR 派生，避免 `dag_edges`、`boundary_values`、`BAE` 多处口径漂移。

### 4.3 必须导出的结构统计

在 `activity_schedule_supernode_stats.json` 和 build log 中新增或保留：

- `initial_compute_supernodes`
- `initial_compute_supernode_ops_total`
- `initial_compute_supernode_dag_edges`
- `initial_boundary_values`
- `initial_boundary_activation_edges`
- `essent_clusters_before_coarsen`
- `essent_clusters_after_mffc`
- `essent_clusters_after_single_parent`
- `essent_clusters_after_small_siblings`
- `essent_clusters_after_small_overlap`
- `essent_clusters_after_down`
- 每个 phase 的 `merge_candidates / accepted / rejected_cycle / rejected_size / rejected_kind`
- `clusters_after_essent_coarsen`
- final `boundary_values` / `boundary_activation_edges`
- duplicate activation:
  - `other_compute_unique_supernode_pairs`
  - `other_compute_duplicate_activation_edges`
  - `boundary_activation_edges_per_unique_pair_mean/p90/p99/max`

## 5. ESSENT Merge 迁移策略

### 5.1 Phase M：MFFC 初始分解

目标：实现用户建议中的初始 compute supernode 构建。

验收：

- 小单测覆盖 diamond、chain、two sinks、output root、direct source -> commit。
- initial compute supernode 覆盖所有应该参与 compute 的 op，且无重复所有权。
- initial DAG topo 成功，无 cycle。
- source clone / direct source commit 语义不变。
- `ctest -R '^(transform-activity-schedule|emit-grhsim-cpp|emit-grhsim-cpp-memory-fill)$'` 通过。

### 5.2 Phase D：DAG 数据结构落地

目标：把 initial compute supernode DAG materialize 到 CSR 结构，并用该结构替换当前 coarsen 输入。

验收：

- 对同一输入，CSR 统计与慢速 debug recompute 统计一致。
- XiangShan emit 能产出 `activity_schedule_supernode_stats.json`。
- DAG 构建时间不超过当前 `activity-schedule total` 的 `20%`；若超过，先停下优化数据结构。
- 内存峰值可接受，不能因 boundary value 全量复制导致 OOM。

### 5.3 Phase C1：single-parent merge

ESSENT `mergeSingleInputPartsIntoParents` 的迁移版。

规则：

- 小 cluster 且入度为 1；
- parent 非 hard boundary；
- 合并后 op 数 / compute node 数不超过阈值；
- 合并必须保持 acyclic。

大图实现建议：

- 初版只接受 “parent -> child 直接相邻且 child 无回向 external path” 的保守候选；
- 用 topo interval + bounded BFS 做 cycle guard；
- 对高 fanout hub 设置访问上限，超限 reject 并统计。

验收：

- phase 独立开关：`enableEssentSingleParentMerge`。
- XiangShan 上 phase 时间、候选数、accepted 数有日志。
- `clusters_after_single_parent < clusters_after_mffc`。
- final 50k 功能正确；性能不作为单独硬门，但不能出现明显灾难性回退。

### 5.4 Phase C2：small siblings merge

ESSENT `mergeSmallSiblings` 的迁移版。

规则：

- cluster size `< Cp`；
- siblings 的 input cluster set 完全相同，或在 debug 参数下允许 canonical input set hash 相同后再精确校验；
- 同组 siblings 只合并非 hard boundary、非 commit 的 compute cluster；
- 优先消除 cut edge 数最多的 sibling group。

验收：

- 小图覆盖 siblings merge 后仍 acyclic。
- XiangShan 上 `same_input_sibling_groups`、`accepted_sibling_merges` 非零。
- final duplicate activation edge 比 Phase C1 不上升；若上升，默认关闭该 phase。

### 5.5 Phase C3：small overlap merge

ESSENT `mergeSmallParts` 的迁移版。

规则：

- cluster size `< Cp`；
- 候选 sibling 来自 `pred(cluster)` 的其他 successors；
- score = common input count / cluster input count；
- 初始阈值 `0.5`，第二轮可试 `0.25`；
- 候选按 score、edge removed、cluster id 稳定排序。

验收：

- 可通过参数单独开启 `threshold=0.5` 和 `threshold=0.25`。
- XiangShan 上必须记录 rejected reason，尤其是 cycle guard reject。
- 只有当 final `boundary_activation_edges` 或 CoreMark 50k wall time 有收益时才默认开启。

### 5.6 Phase C4：down merge

ESSENT `mergeSmallPartsDown` 的迁移版。

规则：

- 小 cluster 向 child 合并；
- 候选 child 按 removed edge count 排序；
- 必须通过 acyclic guard；
- 默认实验开关关闭，作为可选后段。

验收：

- 单独 AB：C1+C2+C3 vs C1+C2+C3+C4。
- 若 `.text`、branch、CoreMark wall time 任一显著回退，则保持默认关闭。

## 6. Acyclic Guard 设计

论文判定条件：合并 A/B 当且仅当任一方向都不存在 external path。Scala 参考实现用图遍历实现 `extPathExists`，但 XiangShan 规模下不能对每个候选做无界 DFS。

建议分三档实现：

1. Fast accept：
   - 直接 chain out1/in1；
   - identical-input siblings 且 cluster 间无直接 reachability；
   - topo interval 不重叠且无跨越回边风险。
2. Bounded exact：
   - 在 topo interval `[min(A,B), max(A,B)]` 内做 bounded BFS；
   - 跳过 A/B 内部节点；
   - 访问数超过阈值则 reject，不冒险 accept。
3. Debug exact：
   - 小测试或抽样启用完整 external path 检查；
   - 用于验证 fast/bounded guard 是否过保守或漏判。

验收硬门：

- 任意 phase 后 `orderNodeClustersTopologically` 必须成功。
- final schedule topo 必须成功。
- 任何 cycle 失败都要输出最小 phase、候选、cluster size、topo interval 和 edge reason。

## 7. 参数与默认策略

新增参数建议：

| 参数 | 默认值 | 含义 |
| --- | ---: | --- |
| `enableEssentMffcBuild` | `false` | 启用新的 initial compute supernode builder |
| `enableEssentCoarsen` | `false` | 启用 ESSENT merge 主路径 |
| `essentSmallPartCutoff` | `20` | 对应论文 / 参考实现的 `Cp` |
| `essentMaxClusterOps` | `0` | 0 表示沿用 `max-op-in-compute-supernode` 或单独推导 |
| `essentOverlapThreshold1` | `0.5` | small overlap 第一轮阈值 |
| `essentOverlapThreshold2` | `0.25` | small overlap 第二轮阈值 |
| `essentCycleGuardMaxVisits` | `4096` | bounded external path 检查访问上限 |
| `dumpEssentDagStats` | `true` | 输出阶段结构统计 |

默认落地顺序：

1. 先 hidden/off-by-default 合入 MFFC builder 和统计。
2. 再逐个 phase 开关 AB。
3. 只有 XiangShan 50k 功能正确且至少一个结构指标或 wall time 有稳定收益，才考虑默认开启。

## 8. 分阶段验收计划

### Stage 0：基线固化

输入：当前主线，记录 50k 与结构指标。

验收产物：

- `activity_schedule_supernode_stats.json`
- build log 中 `activity-schedule compute-node coarsen detail`
- CoreMark 50k 运行日志
- 可选 `perf stat`：instructions、branches、branch-misses、iTLB/dTLB、IPC

硬门：

- 50k 跑满 `-C 50000`，无 difftest mismatch / assert。
- 记录当前 speed，本文目标基线按用户提供的约 `120 cycles/s` 处理；若复测不同，以复测日志为准。

### Stage 1：MFFC Builder 单独启用

目标：替换初始 compute supernode 构建，不启用 ESSENT merge。

验收：

- 单测通过。
- XiangShan emit 成功。
- initial DAG 统计可解释：
  - node 数不应爆炸超过当前 op 粒度 compute node；
  - avg out-degree、boundary value、BAE 必须记录。
- CoreMark 20k smoke 通过，再跑 50k。

通过标准：

- 功能正确是硬门。
- 若 50k 速度回退超过 `5%`，必须判断是 node 过粗、boundary 增加还是 emit 代码形态变坏；默认不进入 Stage 2。

### Stage 2：高性能 DAG 与统计口径稳定

目标：让新 DAG 成为后续 coarsen 的唯一输入结构。

验收：

- stats 慢速校验一致。
- XiangShan `activity-schedule` 时间没有明显劣化；目标是新增 DAG 阶段 `< 60s`，理想 `< 30s`。
- JSON 中包含 initial/coarsen/final 三层指标。

### Stage 3：ESSENT C1/C2 合并

目标：先迁移低风险 merge。

启用：

- MFFC builder
- single-parent merge
- small siblings merge

验收：

- `clusters_after_essent_coarsen` 明显低于 `initial_compute_supernodes`。
- final `boundary_values` 和 `boundary_activation_edges` 至少一个下降。
- CoreMark 50k 功能正确。
- wall time 不低于基线 `120 cycles/s` 的 `95%`；若结构改善但 wall time 未改善，保留 off-by-default 并进入 profiling。

### Stage 4：ESSENT C3/C4 合并

目标：迁移更激进 merge，并找出收益边界。

矩阵：

- C1+C2
- C1+C2+C3(threshold=0.5)
- C1+C2+C3(0.5)+C3(0.25)
- C1+C2+C3+C4

验收：

- 每个点都要记录 structure + 50k。
- 只接受功能正确且 wall time 改善的组合。
- 如果 `BAE` 降但 runtime 回退，需要补充 active supernode、branch、`.text` 与 perf 解释，不直接默认开启。

### Stage 5：XiangShan 提速验收

最终验收以 XiangShan `coremark-2-iteration.bin` 为主。

硬门：

- fresh emit + build 成功。
- CoreMark 50k 跑满，`instrCnt/cycleCnt/end PC` 与当前正确基线一致。
- `ctest -R '^(transform-activity-schedule|emit-grhsim-cpp|emit-grhsim-cpp-memory-fill)$'` 通过。

结构目标：

| 指标 | 目标 |
| --- | --- |
| `boundary_activation_edges` | 相对当前基线下降，第一阶段目标 `-10%` |
| duplicate activation edges | 相对当前基线下降，第一阶段目标 `-15%` |
| `clusters_after_essent_coarsen / initial_compute_supernodes` | 明显低于当前 coarsen 收缩比 |
| activity-schedule total time | 不显著高于当前主线；若更慢，需要 runtime 收益抵消 |

性能目标：

| 阶段 | 目标 |
| --- | --- |
| smoke | 20k 功能正确 |
| first useful win | 50k speed 超过当前约 `120 cycles/s` |
| near-term | 50k speed `>= 135 cycles/s` |
| stretch | 50k speed `>= 150 cycles/s`，并解释相对 GSim 的剩余差距 |

## 9. 风险与处理

| 风险 | 处理 |
| --- | --- |
| MFFC 初始节点过粗，导致 boundary multiplicity 更坏 | 输出 per-node output value / fanout 分布，必要时对 high-fanout op 强制 root |
| external path 检查过慢 | bounded guard 超限 reject，先保正确性和构建时间 |
| BAE 降但 runtime 回退 | 用 perf / runtime profile 判断是否 `.text`、branch、cache/frontend 变坏 |
| merge 后 local op topo 失败 | phase 级开关 + candidate dump，禁止 silent fallback |
| source clone 语义影响 commit | direct source -> commit 保留原值依赖，单测覆盖 |
| memory read 被错误复制 | `kMemoryReadPort` 始终 compute op，不作为 source clone |

## 10. 实施顺序建议

1. 在现有 `activity_schedule.cpp` 中新增 MFFC builder 的慢速清晰版和单测，默认关闭。
2. 增加 initial DAG / final DAG 的统一 stats dump，先不改 runtime 行为。
3. 把慢速 MFFC builder 改为 CSR + stamp 结构，跑 XiangShan emit。
4. 迁移 C1/C2 merge，做 20k/50k AB。
5. 迁移 C3/C4 merge，做矩阵实验。
6. 选出一个默认关闭的 best config，写新 NO 文档记录结构与 50k。
7. 若 best config 稳定超过当前约 `120 cycles/s`，再考虑默认开启或接入主流程参数。

## 11. 增量更新 2026-05-18：Stage 1 与 C1/C2 原型落地状态

本轮已把 ESSENT/MFFC 路径以默认关闭方式接入 `activity-schedule`，用于后续 XiangShan 结构实验。

已落地内容：

- 新增参数：`enableEssentMffcBuild`、`enableEssentCoarsen`、`essentSmallPartCutoff`、`essentMaxClusterOps`、`essentOverlapThreshold1`、`essentOverlapThreshold2`、`essentCycleGuardMaxVisits`、`dumpEssentDagStats`；CLI 与 Python wrapper 均可传入。
- 新增 MFFC 风格初始 compute node builder：从 output/commit root 反推，单用户链吸收到同一 initial compute supernode，共享 producer 保持为独立 root；当前仍是清晰优先的 vector/hash 版本，尚未 CSR 化。
- 新增 summary/log 字段：`initial_compute_supernodes`、`initial_compute_supernode_ops_total`、`initial_compute_supernode_dag_edges`、`initial_boundary_values`、`initial_boundary_activation_edges`、`essent_clusters_*`、`clusters_after_essent_coarsen`、`essent_single_parent_merges`、`essent_small_sibling_merges`。
- 新增 ESSENT coarsen 原型：C1 single-parent merge 与 C2 small-sibling merge。C3 small overlap、C4 down merge、bounded external path guard 还未实现。
- `essentMaxClusterOps != 0` 时作为 ESSENT coarsen 阶段的 cluster size cap；否则沿用 `maxOpInComputeSupernode`。

已增加单测：

- `essent_mffc_chain_and_shared`：验证单用户链被 MFFC 吸收，共享表达式保留为独立 root，并检查 initial 统计。
- `essent_coarsen_single_parent`：验证 C1 能把共享 parent 与两个 single-parent child 合并，并导出 merge 计数。
- `essent_coarsen_small_siblings`：验证 C2 能合并具有相同输入集合的小 sibling cluster，并导出 merge 计数。

已执行验证：

```text
cmake --build wolvrix/build --target transform-activity-schedule -j$(nproc)
ctest --test-dir wolvrix/build --output-on-failure -R '^transform-activity-schedule$'
cmake --build wolvrix/build --target emit-grhsim-cpp emit-grhsim-cpp-memory-fill -j$(nproc)
ctest --test-dir wolvrix/build --output-on-failure -R '^(transform-activity-schedule|emit-grhsim-cpp|emit-grhsim-cpp-memory-fill)$'
```

结果：上述三项 CTest 通过。`emit-grhsim-cpp` 本轮耗时约 `56.05s`。

当前限制：

- 默认行为未改变；未验证前不能默认开启 `enableEssentMffcBuild` 或 `enableEssentCoarsen`。
- 还没有 XiangShan emit/20k/50k 数据，不能声称已经带来 `120 cycles/s` 以上提速。
- DAG 仍未迁移到本文第 4 节的 CSR/stamp 高性能结构；大规模图上的构建时间、内存与 candidate reject 分布仍待测。
- C1/C2 当前依赖每轮 rebuild/toposort 保证 acyclic，尚未实现 ESSENT 论文中的 external path 判定与 bounded guard 统计。

## 12. 增量更新 2026-05-18：C3/C4 原型与 phase 开关

在上一轮 C1/C2 基础上，继续补齐 ESSENT merge phase 的默认关闭原型。

已落地内容：

- 新增 phase 独立开关：
  - `enableEssentSingleParentMerge`
  - `enableEssentSmallSiblingMerge`
  - `enableEssentSmallOverlapMerge`
  - `enableEssentDownMerge`
- CLI 与 Python wrapper 均支持上述开关；默认值为 `true`，但只有 `enableEssentCoarsen=true` 时才生效。
- 新增 C3 small-overlap merge：从小 cluster 的 predecessor successors 中找候选 sibling，按 `common input count / max input count` 与 `essentOverlapThreshold1/2` 筛选并合并。
- 新增 C4 down merge：小 cluster 优先按与 child 的 boundary value weight 向下合并。
- 新增 summary/log 字段：`essent_small_overlap_merges`、`essent_down_merges`。

已增加单测：

- `essent_coarsen_small_overlap`：关闭 C1/C2/C4，只验证 C3 small-overlap merge 计数和最终 cluster 数。
- `essent_coarsen_down`：关闭 C1/C2/C3，只验证 C4 down merge 至少接受一个候选。
- 原有 C1/C2 用例改为关闭后续 phase，保证每个 phase 的验收互不污染。

已执行验证：

```text
cmake --build wolvrix/build --target transform-activity-schedule -j$(nproc)
ctest --test-dir wolvrix/build --output-on-failure -R '^transform-activity-schedule$'
cmake --build wolvrix/build --target emit-grhsim-cpp emit-grhsim-cpp-memory-fill -j$(nproc)
ctest --test-dir wolvrix/build --output-on-failure -R '^(transform-activity-schedule|emit-grhsim-cpp|emit-grhsim-cpp-memory-fill)$'
```

结果：上述三项 CTest 通过。`emit-grhsim-cpp` 本轮耗时约 `56.07s`。

当前限制：

- C3/C4 仍是 vector/hash 原型，尚未迁移到 CSR/stamp 结构。
- C3/C4 仍依赖 merge 后 topo 成功作为保守 acyclic gate，没有实现 external path guard、candidate reject reason、bounded visit 统计。
- 还未在 XiangShan 上跑 emit/20k/50k AB；不能默认开启，也不能声称有 runtime 收益。

## 13. 增量更新 2026-05-18：XiangShan flow 参数透传

为进入 Stage 5 的 XiangShan emit/20k/50k AB，`scripts/wolvrix_xs_grhsim.py` 已支持通过环境变量透传 ESSENT 参数到 `activity-schedule`：

- `WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD`
- `WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN`
- `WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SINGLE_PARENT_MERGE`
- `WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_SIBLING_MERGE`
- `WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE`
- `WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE`
- `WOLVRIX_XS_GRHSIM_ESSENT_SMALL_PART_CUTOFF`
- `WOLVRIX_XS_GRHSIM_ESSENT_MAX_CLUSTER_OPS`
- `WOLVRIX_XS_GRHSIM_ESSENT_OVERLAP_THRESHOLD1`
- `WOLVRIX_XS_GRHSIM_ESSENT_OVERLAP_THRESHOLD2`
- `WOLVRIX_XS_GRHSIM_ESSENT_CYCLE_GUARD_MAX_VISITS`
- `WOLVRIX_XS_GRHSIM_DUMP_ESSENT_DAG_STATS`

已执行验证：

```text
python3 -m py_compile scripts/wolvrix_xs_grhsim.py wolvrix/app/pybind/wolvrix/__init__.py
cmake --build wolvrix/build --target transform-activity-schedule -j$(nproc)
```

下一步建议使用同一份 `WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1` checkpoint 做结构 AB，先只生成 `activity_schedule_supernode_stats.json`，再决定是否进入 fresh emit/build/20k/50k。

## 14. 增量更新 2026-05-18：bounded external path guard

为补齐第 6 节的 acyclic guard，C1/C2/C3/C4 merge 原型已加入候选级 bounded external path 检查。

已落地内容：

- 对每个候选 `(A, B)`，分别检查 `A -> B` 和 `B -> A` 是否存在经过第三方 cluster 的 external path。
- 直接边 `A -> B` / `B -> A` 视为合并后的内部边，不作为 external path 拒绝。
- 当 DFS 访问数超过 `essentCycleGuardMaxVisits` 时保守 reject，不冒险 accept。
- 所有 phase 共享 reject 统计：
  - `essent_merge_candidates`
  - `essent_merge_rejected_size`
  - `essent_merge_rejected_cycle`
  - `essent_merge_rejected_bounded`
  - `essent_merge_rejected_topo`
- summary JSON、build log 和 `activity_schedule_supernode_stats.json` 均能导出上述字段。

已增加单测：

- `essent_cycle_guard_bounded_reject`：把 `essentCycleGuardMaxVisits` 设为 `0`，确认候选被 bounded guard 拒绝，`essent_single_parent_merges=0` 且 `essent_merge_rejected_bounded` 非零。

已执行验证：

```text
cmake --build wolvrix/build --target transform-activity-schedule -j$(nproc)
ctest --test-dir wolvrix/build --output-on-failure -R '^transform-activity-schedule$'
cmake --build wolvrix/build --target emit-grhsim-cpp emit-grhsim-cpp-memory-fill -j$(nproc)
ctest --test-dir wolvrix/build --output-on-failure -R '^(transform-activity-schedule|emit-grhsim-cpp|emit-grhsim-cpp-memory-fill)$'
```

结果：上述三项 CTest 通过。`emit-grhsim-cpp` 本轮耗时约 `55.94s`。

当前限制：

- guard 仍运行在 vector adjacency 上，尚未使用 CSR/stamp 数据结构。
- reject reason 是 phase 汇总口径，尚未输出候选级 cluster id、topo interval、edge reason 的详细 dump。
- 尚未在 XiangShan 大图上验证 bounded reject 数量、guard 时间占比和结构收益。

## 15. 增量更新 2026-05-18：phase-level reject stats 与结构 AB 阻塞

为满足第 4.3 节“每个 phase 的 candidate / accepted / rejected reason”统计要求，本轮把 ESSENT reject stats 从总量扩展到 phase 级别。

新增 summary JSON 字段：

- C1 single-parent：
  - `essent_single_parent_candidates`
  - `essent_single_parent_rejected_size`
  - `essent_single_parent_rejected_cycle`
  - `essent_single_parent_rejected_bounded`
  - `essent_single_parent_rejected_topo`
- C2 small-sibling：
  - `essent_small_sibling_candidates`
  - `essent_small_sibling_rejected_size`
  - `essent_small_sibling_rejected_cycle`
  - `essent_small_sibling_rejected_bounded`
  - `essent_small_sibling_rejected_topo`
- C3 small-overlap：
  - `essent_small_overlap_candidates`
  - `essent_small_overlap_rejected_size`
  - `essent_small_overlap_rejected_cycle`
  - `essent_small_overlap_rejected_bounded`
  - `essent_small_overlap_rejected_topo`
- C4 down:
  - `essent_down_candidates`
  - `essent_down_rejected_size`
  - `essent_down_rejected_cycle`
  - `essent_down_rejected_bounded`
  - `essent_down_rejected_topo`

新增 build log 行：

```text
activity-schedule essent phase detail: ...
```

已执行验证：

```text
cmake --build wolvrix/build --target transform-activity-schedule -j$(nproc)
ctest --test-dir wolvrix/build --output-on-failure -R '^transform-activity-schedule$'
python3 -m py_compile scripts/wolvrix_xs_grhsim.py wolvrix/app/pybind/wolvrix/__init__.py
```

XiangShan 结构 AB 尝试：

```text
WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1
WOLVRIX_XS_GRHSIM_POST_STATS_JSON=/home/gaoruihao/wksp/wolvrix-playground/build/xs/grhsim/wolvrix_xs_post_stats.json
WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1
python3 scripts/wolvrix_xs_grhsim.py dummy.f SimTop tmp/no0093_default_stats/grhsim_emit '' '' info
```

结果：修复 Python wrapper / native library 不匹配后，默认路径结构-only activity-schedule 成功完成并写出：

- stats: `tmp/no0093_default_stats/grhsim_emit/activity_schedule_supernode_stats.json`
- log: `tmp/no0093_default_stats/run.log`

本轮默认路径结构基线：

| 指标 | 值 |
| --- | ---: |
| `compute_nodes` | `6,635,278` |
| `compute_supernodes` | `63,392` |
| `commit_supernodes` | `515` |
| `supernodes` | `63,907` |
| `dag_edges` | `975,745` |
| `boundary_values` | `1,349,093` |
| `boundary_activation_edges` | `2,460,976` |
| `other_compute_activation_edges` | `2,330,523` |
| `ops_mean` | `108.373` |
| `ops_p99` | `128` |
| `outdeg_p99` | `186` |
| `activity-schedule` time | `615,252 ms` |
| total resume + schedule time | `637,401 ms` |

后续处理：

- 默认路径单次 activity-schedule 已接近 `10.3 min`，ESSENT vector/hash 原型直接跑 XiangShan 可能更慢；下一步优先做 CSR/stamp，或者先用更小 `xs-bugcase` / `xs-components` 做结构 AB。
- structure-only runner 仍应补超时、周期性 heartbeat 和阶段进度，避免长时间无日志时难以判断是否卡死。

## 16. 增量更新 2026-05-19：CASE_007 ESSENT structure-only 通过

修复内容：

- `topoSortLocalOps` 入口现在先对 op 列表做保持顺序的唯一化，避免同一 local op 被重复加入时误报 `missing ops`。
- MFFC builder 吸收 `Source` op 时同步设置 `computeNodeOfOp`，避免同一 initial compute supernode 内的 source result 在边界重建阶段被当成外部输入。

已执行验证：

```text
cmake --build wolvrix/build --target transform-activity-schedule -j$(nproc)
ctest --test-dir wolvrix/build --output-on-failure -R '^transform-activity-schedule$'
```

结果：`transform-activity-schedule` 通过。

CASE_007 structure-only 对比：

| 指标 | 默认路径 | ESSENT MFFC + C1/C2/C3/C4 |
| --- | ---: | ---: |
| `compute_nodes` | `164` | `107` |
| `initial_compute_supernodes` | `0` | `107` |
| `initial_compute_supernode_dag_edges` | `0` | `55` |
| `initial_boundary_values` | `0` | `20` |
| `initial_boundary_activation_edges` | `0` | `55` |
| `essent_clusters_after_mffc` | `0` | `107` |
| `essent_clusters_after_single_parent` | `0` | `92` |
| `essent_clusters_after_small_siblings` | `0` | `90` |
| `essent_clusters_after_small_overlap` | `0` | `82` |
| `essent_clusters_after_down` | `0` | `74` |
| `clusters_after_essent_coarsen` | `0` | `74` |
| `compute_supernodes` | `3` | `1` |
| `commit_supernodes` | `2` | `2` |
| `supernodes` | `5` | `3` |
| `dag_edges` | `5` | `2` |
| `boundary_values` | `19` | `18` |
| `boundary_activation_edges` | `21` | `20` |
| `other_compute_activation_edges` | `11` | `10` |

ESSENT phase 计数：

- C1 single-parent：`15 / 15` accepted。
- C2 small-sibling：`2 / 2` accepted。
- C3 small-overlap：`8 / 16` accepted，`7` cycle rejects。
- C4 down：`8 / 11` accepted，`3` cycle rejects。
- 总候选：`44`，总 cycle rejects：`10`，bounded rejects：`0`。

产物：

- 默认 stats：`tmp/no0093_case007_default/grhsim/activity_schedule_supernode_stats.json`
- ESSENT stats：`tmp/no0093_case007_essent/grhsim/activity_schedule_supernode_stats.json`

当前限制：

- 这只是小规模 `xs-bugcase` structure-only 验收，不能推导 XiangShan runtime 收益。
- CSR/stamp 高性能 DAG 仍未完成。
- XiangShan ESSENT structure AB、fresh emit/build、CoreMark 20k/50k 正确性和 `120 cycles/s` 以上提速仍未验收。

## 17. 增量更新 2026-05-19：ESSENT guard CSR/stamp 切片

为推进第 4 节“大规模图数据结构”，本轮先把 C1/C2/C3/C4 共用的 external-path cycle guard 从每候选 `vector<uint8_t> seen` 改为阶段内复用的 CSR + stamp scratch。

已落地内容：

- 新增 `ClusterDagCsr`：
  - `succOffsets/succs` 保存 cluster DAG successor CSR；
  - `seen` + `stamp` 复用 visited 标记；
  - `stack` 复用 DFS 栈。
- `hasExternalPathBetweenClusters` 现在基于 CSR 遍历，不再为每个候选分配 visited 数组。
- C1 single-parent、C2 small-sibling、C3 small-overlap、C4 down merge 均在 phase 开始时从 `NodeClusterView::succs` 构建一次 CSR guard，并复用于该 phase 内所有候选。

已执行验证：

```text
cmake --build wolvrix/build --target transform-activity-schedule -j$(nproc)
ctest --test-dir wolvrix/build --output-on-failure -R '^transform-activity-schedule$'
```

CASE_007 ESSENT structure-only 复测：

```text
WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1
WOLVRIX_XS_GRHSIM_POST_STATS_JSON=/home/gaoruihao/wksp/wolvrix-playground/build/xs_bugcase/CASE_007/grhsim/wolvrix_xs_post_stats.json
WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN=1
python3 scripts/wolvrix_xs_grhsim.py testcase/xs-bugcase/CASE_007/filelist.f xs_bugcase_tb tmp/no0093_case007_essent_csr_guard/grhsim '' testcase/xs-bugcase/CASE_007/tb.v info
```

结果：通过，且结构计数与上一轮一致：

- `initial_compute_supernodes=107`
- `essent_clusters_after_single_parent=92`
- `essent_clusters_after_small_siblings=90`
- `essent_clusters_after_small_overlap=82`
- `essent_clusters_after_down=74`
- `clusters_after_essent_coarsen=74`
- `boundary_values=18`
- `boundary_activation_edges=20`

产物：

- `tmp/no0093_case007_essent_csr_guard/grhsim/activity_schedule_supernode_stats.json`

当前限制：

- 这只是 guard 热路径的 CSR/stamp 切片；`NodeClusterView`、`ClusterValueEdges`、MFFC builder 与 final segment 仍含 vector/hash 重建路径。
- 还未在 XiangShan 大图上测 guard 时间占比和 ESSENT structure AB。

## 18. 增量更新 2026-05-19：XiangShan ESSENT structure-only 超时

在 guard CSR/stamp 切片后，尝试用 XiangShan checkpoint 做 ESSENT structure-only AB。

命令：

```text
timeout 1800 env \
  WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1 \
  WOLVRIX_XS_GRHSIM_POST_STATS_JSON=/home/gaoruihao/wksp/wolvrix-playground/build/xs/grhsim/wolvrix_xs_post_stats.json \
  WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1 \
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD=1 \
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN=1 \
  python3 scripts/wolvrix_xs_grhsim.py dummy.f SimTop tmp/no0093_xs_essent_csr_guard/grhsim_emit '' '' info
```

结果：

- checkpoint JSON 读取完成，用时约 `20.858s`。
- 进入 `pass activity-schedule start` 后 30 分钟内没有返回。
- `timeout` 以退出码 `124` 终止命令。
- `tmp/no0093_xs_essent_csr_guard/grhsim_emit/` 未产生 `activity_schedule_supernode_stats.json`。
- 事后 `ps -efww` 未发现残留 `wolvrix_xs_grhsim.py` 进程。

结论：

- 当前 ESSENT 大图路径未通过 Stage 2 构建成本门槛，不能进入 fresh emit/build 或 CoreMark 20k/50k。
- 仅将 external-path guard 改成 CSR/stamp 不足以支撑 XiangShan；下一个优化点应优先覆盖仍在大图热路径中的 `NodeClusterView` / `ClusterValueEdges` 构建和 MFFC builder，而不是继续尝试 runtime AB。
- 需要补 activity-schedule 阶段 heartbeat 或 phase-level 进度日志，否则长时间无输出时无法区分 MFFC build、phase merge、final materialize 哪一段耗时。

## 19. 增量更新 2026-05-19：activity-schedule 粗粒度进度日志

为解决第 18 节 XiangShan ESSENT 超时时无法定位阶段的问题，本轮增加粗粒度 progress log 和 ESSENT phase timing。

新增日志：

- `activity-schedule progress: build_op_data start/done`
- `activity-schedule progress: source_clone start/done`
- `activity-schedule progress: source_clone_refreeze start/done`
- `activity-schedule progress: compute_node_build start/done`
- `activity-schedule progress: freeze_after_compute_node start/done`
- `activity-schedule progress: final_materialize start/done`
- `activity-schedule progress: export_session start/done`
- `activity-schedule essent progress: single_parent/small_sibling/small_overlap/down start/done`

新增 timing 字段：

- `essent_single_parent`
- `essent_small_sibling`
- `essent_small_overlap`
- `essent_down`

已执行验证：

```text
cmake --build wolvrix/build --target transform-activity-schedule -j$(nproc)
ctest --test-dir wolvrix/build --output-on-failure -R '^transform-activity-schedule$'
```

CASE_007 ESSENT structure-only 复测确认日志可见，并成功写出：

- `tmp/no0093_case007_essent_progress/grhsim/activity_schedule_supernode_stats.json`

观察到的阶段日志示例：

```text
activity-schedule progress: compute_node_build start mode=essent_mffc
activity-schedule progress: compute_node_build done compute_nodes=107 commit_nodes=2 elapsed_ms=0
activity-schedule progress: final_materialize start
activity-schedule essent progress: single_parent start clusters=107
activity-schedule essent progress: single_parent done clusters=92 merges=15 candidates=15 elapsed_ms=0
...
```

下一次 XiangShan ESSENT structure-only 超时时，可以据此判断卡在 MFFC build 还是 C1-C4 / final materialize。

## 20. 增量更新 2026-05-19：XiangShan progress-run 定位到 C2 small-sibling

使用第 19 节新增进度日志，重新运行 XiangShan ESSENT structure-only，并用 `timeout 900` 限制总时长。

关键日志：

```text
activity-schedule progress: build_op_data done ops=4996771 topo_edges=10383484 elapsed_ms=5280
activity-schedule progress: source_clone done clones=2234946 graph_changed=true elapsed_ms=12070
activity-schedule progress: source_clone_refreeze done ops=7231717 topo_edges=10458727 elapsed_ms=7812
activity-schedule progress: compute_node_build done compute_nodes=3720195 commit_nodes=515 elapsed_ms=34335
activity-schedule progress: final_materialize start
activity-schedule essent progress: single_parent start clusters=3720195
activity-schedule essent progress: single_parent done clusters=3423020 merges=297175 candidates=1689503 elapsed_ms=117308
activity-schedule essent progress: small_sibling start clusters=3423020
```

结果：

- 命令在 C2 small-sibling 阶段超时，退出码 `124`。
- `tmp/no0093_xs_essent_progress/grhsim_emit/` 未产生 stats。
- 无残留 `wolvrix_xs_grhsim.py` 进程。

结论：

- MFFC builder 本身不是当前 30 分钟超时主因：XiangShan 上耗时约 `34.3s`，并把 compute nodes 降到 `3,720,195`。
- C1 single-parent 可完成，耗时约 `117.3s`，合并 `297,175` 个 cluster。
- C2 small-sibling 是当前明确瓶颈。现实现使用 `std::unordered_map<std::string, vector<uint32_t>>` 和 `ostringstream` 构造 predecessor-set key，在 `3.4M` cluster 规模下不可接受。

下一步：

- 将 C2 grouping 从 string key 改为排序 predecessor vector 的 hash/exact key，去掉 `ostringstream` 热点。
- 或先做 C1-only structure AB，验证后续 final materialize 是否能完成；但 C2 若要纳入默认候选，必须先完成上述数据结构替换。

## 21. 增量更新 2026-05-19：C2 vector-hash grouping 仍未通过 XiangShan

本轮将 C2 small-sibling 的 grouping key 从 `ostringstream` 生成的 string 改为 `std::vector<uint32_t>` exact key + 自定义 hash，消除字符串构造热点。

已验证：

```text
cmake --build wolvrix/build --target transform-activity-schedule -j$(nproc)
ctest --test-dir wolvrix/build --output-on-failure -R '^transform-activity-schedule$'
```

CASE_007 ESSENT structure-only 通过，C2 计数保持：

- `essent_small_sibling_merges=2`
- `essent_small_sibling_candidates=2`
- final `boundary_activation_edges=20`

XiangShan 定位运行：

- 前段耗时稳定：
  - `build_op_data` 约 `5.265s`
  - `source_clone` 约 `12.131s`
  - `source_clone_refreeze` 约 `7.823s`
  - `compute_node_build` 约 `34.445s`
  - C1 single-parent 约 `118.442s`
- 仍在 `small_sibling start clusters=3423020` 后超时，退出码 `124`。
- 未产生 `tmp/no0093_xs_essent_c2_hash/grhsim_emit/activity_schedule_supernode_stats.json`。

结论：

- C2 的瓶颈不只是 string key；`buildNodeClusterView` 重建、百万级 group map、候选收集/排序和后续 topo reorder 都仍是大图不可接受路径。
- 在 C2 重写前，应先做 C1-only structure AB，确认 MFFC + C1 + final materialize 是否能跑通，并取得第一份 XiangShan ESSENT 部分结构指标。

## 22. 增量更新 2026-05-19：XiangShan MFFC+C1 structure-only 成功

在 C1-only 尝试中，final topo 最初报 cycle。错误中出现 `def/use` 都属于同一 `computeNode` 的边，例如：

```text
edge 20295 -> 1787 via ... def=...(computeNode=561965) use=...(computeNode=561965)
```

修复：

- final DAG 构建时，如果 operand 的 def op 与 use op 映射到同一个 `rewrite.computeNodeOfOp`，直接视为 compute node 内部依赖并跳过，不生成跨 final supernode edge。

已验证：

```text
cmake --build wolvrix/build --target transform-activity-schedule -j$(nproc)
ctest --test-dir wolvrix/build --output-on-failure -R '^transform-activity-schedule$'
```

XiangShan C1-only structure-only 命令：

```text
timeout 1200 env \
  WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1 \
  WOLVRIX_XS_GRHSIM_POST_STATS_JSON=/home/gaoruihao/wksp/wolvrix-playground/build/xs/grhsim/wolvrix_xs_post_stats.json \
  WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1 \
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD=1 \
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN=1 \
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_SIBLING_MERGE=0 \
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE=0 \
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE=0 \
  python3 scripts/wolvrix_xs_grhsim.py dummy.f SimTop tmp/no0093_xs_essent_c1_only_fixed/grhsim_emit '' '' info
```

结果：成功，写出 `tmp/no0093_xs_essent_c1_only_fixed/grhsim_emit/activity_schedule_supernode_stats.json`。

与默认 structure-only 基线对比：

| 指标 | 默认 | MFFC+C1 only |
| --- | ---: | ---: |
| activity-schedule time | `615,252 ms` | `198,285 ms` |
| total resume + schedule time | `637,401 ms` | `219,222 ms` |
| `compute_nodes` | `6,635,278` | `3,720,195` |
| `compute_supernodes` | `63,392` | `30,452` |
| `commit_supernodes` | `515` | `515` |
| `supernodes` | `63,907` | `30,967` |
| `dag_edges` | `975,745` | `218,378` |
| `boundary_values` | `1,349,093` | `1,245,433` |
| `boundary_activation_edges` | `2,460,976` | `1,983,819` |
| `other_compute_activation_edges` | `2,330,523` | `1,969,674` |
| `outdeg_p99` | `186` | `129` |

MFFC / C1 结构细节：

- `initial_compute_supernodes=3,720,195`
- `initial_compute_supernode_ops_total=8,870,220`
- `initial_compute_supernode_dag_edges=4,221,447`
- `initial_boundary_values=1,320,082`
- `initial_boundary_activation_edges=4,221,447`
- C1 single-parent:
  - candidates: `1,689,503`
  - merges: `297,175`
  - rejected size: `217,914`
  - rejected cycle: `27,736`
  - rejected bounded: `1,146,678`
  - elapsed: `118,403 ms`
- `clusters_after_essent_coarsen=3,423,020`

结论：

- MFFC+C1 已经给出第一份正向 XiangShan structure AB：结构指标和 activity-schedule 构建时间均优于默认 structure-only 基线。
- 这仍不是最终 runtime 验收：还没有 fresh emit/build，也没有 CoreMark 20k/50k 正确性和 `cycles/s` 数据。
- 下一步可优先尝试 MFFC+C1 fresh emit/build smoke；C2/C3/C4 仍需重写大图数据结构后再纳入 XiangShan。

## 23. 增量更新 2026-05-19：final segment 改为按 op 数计量

第 22 节的 MFFC+C1 structure stats 虽然 BAE 降幅明显，但 `ops_max=84654`，不适合直接进入 fresh emit/build。原因是 ESSENT final segment 的 size cap 按 compute node 数计量，而 MFFC compute node 可能包含多个 op。

修复内容：

- 新增 `computeNodeOpSizes` / `clusterOpSize`，为每个 compute node 记录真实 op 数。
- C1/C2/C3/C4 的 merge size cap 改为按 cluster 内 op 数判断。
- `buildComputeSupernodeSegments` 的 DP segment size 改为按 op 数前缀和计量。
- final DAG 构建保留第 22 节修复：同一 `rewrite.computeNodeOfOp` 内部依赖不生成跨 supernode edge。

已验证：

```text
cmake --build wolvrix/build --target transform-activity-schedule -j$(nproc)
ctest --test-dir wolvrix/build --output-on-failure -R '^transform-activity-schedule$'
ctest --test-dir wolvrix/build --output-on-failure -R '^(transform-activity-schedule|emit-grhsim-cpp|emit-grhsim-cpp-memory-fill)$'
```

CASE_007 ESSENT structure-only 结果变化：

- final `compute_supernodes` 从 `1` 变为 `3`。
- final `ops_max=96`，符合 `max_op_in_compute_supernode=128` 约束。
- `boundary_activation_edges=27`，比按 compute-node 数分段时的 `20` 高，但避免了过粗 final supernode。

XiangShan MFFC+C1 op-size structure-only 结果：

| 指标 | 默认 | MFFC+C1 op-size |
| --- | ---: | ---: |
| activity-schedule time | `615,252 ms` | `123,605 ms` |
| total resume + schedule time | `637,401 ms` | `145,053 ms` |
| `compute_nodes` | `6,635,278` | `3,720,195` |
| `compute_supernodes` | `63,392` | `71,893` |
| `commit_supernodes` | `515` | `515` |
| `supernodes` | `63,907` | `72,408` |
| `dag_edges` | `975,745` | `640,636` |
| `boundary_values` | `1,349,093` | `1,270,895` |
| `boundary_activation_edges` | `2,460,976` | `2,457,899` |
| `other_compute_activation_edges` | `2,330,523` | `2,443,754` |
| `ops_p99` | `128` | `510` |
| `ops_max` | `4096` | `8192` |

MFFC / C1 details:

- C1 candidates: `964,704`
- C1 merges: `276,403`
- C1 elapsed: `43,302 ms`
- `clusters_after_essent_coarsen=3,443,792`
- `segments=71,893`

结论：

- 按 op 数 segment 后，构建时间进一步下降，但 BAE 收益基本消失，且 `ops_max=8192` 仍由单个 MFFC compute node 的 `maxOpInComputeNode=8192` 决定。
- 要进入 fresh emit/build，应先把 `WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMPUTE_NODE` 降到 `128` 做一次 structure AB，或实现 MFFC compute node 内部 split；否则仍可能生成过大函数。

## 24. 增量更新 2026-05-19：maxOpInComputeNode=128 不适合当前 MFFC+C1

为限制单个 MFFC compute node 的最大 op 数，本轮给 `scripts/wolvrix_xs_grhsim.py` 增加：

- `WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMPUTE_NODE`

该环境变量透传到 `activity-schedule` 的 `max_op_in_compute_node`。

XiangShan MFFC+C1 node128 structure-only 命令要点：

```text
WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMPUTE_NODE=128
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_SIBLING_MERGE=0
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE=0
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE=0
```

结果：成功，写出 `tmp/no0093_xs_essent_c1_node128/grhsim_emit/activity_schedule_supernode_stats.json`。

对比：

| 指标 | 默认 | MFFC+C1 op-size | MFFC+C1 node128 |
| --- | ---: | ---: | ---: |
| activity-schedule time | `615,252 ms` | `123,605 ms` | `139,045 ms` |
| total resume + schedule time | `637,401 ms` | `145,053 ms` | `159,932 ms` |
| `compute_nodes` | `6,635,278` | `3,720,195` | `4,183,680` |
| `compute_supernodes` | `63,392` | `71,893` | `77,978` |
| `supernodes` | `63,907` | `72,408` | `78,493` |
| `dag_edges` | `975,745` | `640,636` | `699,652` |
| `boundary_values` | `1,349,093` | `1,270,895` | `1,588,616` |
| `boundary_activation_edges` | `2,460,976` | `2,457,899` | `2,645,610` |
| `other_compute_activation_edges` | `2,330,523` | `2,443,754` | `2,512,478` |
| `ops_p99` | `128` | `510` | `128` |
| `ops_max` | `4096` | `8192` | `4096` |

结论：

- `maxOpInComputeNode=128` 控制了 compute supernode 的 `ops_p99`，但显著增加 boundary 和 BAE，不适合作为当前提速配置。
- 当前更有前景的结构点仍是第 22 节 MFFC+C1 粗 MFFC 版本：BAE 明显下降，但需要解决超大 final supernode / emit 函数过大问题。
- 后续方向应是对粗 MFFC compute node 做内部 split 或 emit-level function splitting，而不是简单把 MFFC build cap 降到 128。

## 25. 增量更新 2026-05-19：final oversize compute-node split 原型

为避免第 22 节粗 MFFC+C1 方案生成 `ops_max=84654` 的超大 final compute supernode，本轮新增 final materialize 阶段的可选后置切分：

- `ActivityScheduleOptions::splitOversizeComputeNodes`，默认 `false`，保持既有测试和默认 schedule 语义。
- `ActivityScheduleOptions::splitOversizeComputeNodeMaxOps`，默认 `0` 表示沿用 `maxOpInComputeSupernode`；非零时只控制 oversized MFFC compute node 的内部 chunk 大小。
- Python flow 环境变量：
  - `WOLVRIX_XS_GRHSIM_SPLIT_OVERSIZE_COMPUTE_NODES`
  - `WOLVRIX_XS_GRHSIM_SPLIT_OVERSIZE_COMPUTE_NODE_MAX_OPS`

实现要点：

- C1 merge 和 DP segment 仍在 compute-node DAG 上执行，不在 MFFC build 阶段把 `maxOpInComputeNode` 降到 128。
- final supernode 生成时，如果单个 MFFC compute node 的 op 数超过 split cap，则按该 compute node 的局部 topo op 顺序切成多个 final compute supernode。
- final DAG 构建只保留同一个 oversized compute node 的 forward split chunk 依赖；普通同 compute node 内部依赖仍跳过，避免把局部 MFFC 内部环错误暴露到 final DAG。

新增验证：

```text
cmake --build wolvrix/build --target transform-activity-schedule -j$(nproc)
ctest --test-dir wolvrix/build --output-on-failure -R '^transform-activity-schedule$'
ctest --test-dir wolvrix/build --output-on-failure -R '^(transform-activity-schedule|emit-grhsim-cpp|emit-grhsim-cpp-memory-fill)$'
python3 -m py_compile scripts/wolvrix_xs_grhsim.py wolvrix/app/pybind/wolvrix/__init__.py
```

单测新增 `essent_split_oversize_compute_node`：构造 5-op 单用户 MFFC chain，`maxOpInComputeSupernode=2` 且开启 split 后，应拆成多个 final compute supernode，并保持首尾 chunk 在 DAG 中可达。

### split cap = 128

命令要点：

```text
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_SIBLING_MERGE=0
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE=0
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE=0
WOLVRIX_XS_GRHSIM_SPLIT_OVERSIZE_COMPUTE_NODES=1
```

结果：成功，写出 `tmp/no0093_xs_essent_c1_final_split/grhsim_emit/activity_schedule_supernode_stats.json`。

| 指标 | 默认 | C1 op-size | C1 final split128 |
| --- | ---: | ---: | ---: |
| activity-schedule time | `615,252 ms` | `123,605 ms` | `126,580 ms` |
| `compute_supernodes` | `63,392` | `71,893` | `79,501` |
| `supernodes` | `63,907` | `72,408` | `80,016` |
| `dag_edges` | `975,745` | `640,636` | `671,236` |
| `boundary_values` | `1,349,093` | `1,270,895` | `1,810,281` |
| `boundary_activation_edges` | `2,460,976` | `2,457,899` | `3,012,745` |
| `other_compute_activation_edges` | `2,330,523` | `2,443,754` | `2,686,501` |
| `ops_p99` | `128` | `510` | `128` |
| `ops_max` | `4096` | `8192` | `4096` |

split detail:

- `oversize_compute_nodes=2437`
- `split_supernodes=10045`

结论：切到 128 虽然控制了函数大小，但大量 MFFC 内部值变成 final boundary，BAE 比默认更差，不能作为提速候选。

### split cap = 1024

命令要点：

```text
WOLVRIX_XS_GRHSIM_SPLIT_OVERSIZE_COMPUTE_NODES=1
WOLVRIX_XS_GRHSIM_SPLIT_OVERSIZE_COMPUTE_NODE_MAX_OPS=1024
```

结果：成功，写出 `tmp/no0093_xs_essent_c1_final_split1024/grhsim_emit/activity_schedule_supernode_stats.json`。

| 指标 | 默认 | C1 op-size | C1 final split1024 |
| --- | ---: | ---: | ---: |
| activity-schedule time | `615,252 ms` | `123,605 ms` | `126,580 ms` |
| `compute_supernodes` | `63,392` | `71,893` | `72,247` |
| `supernodes` | `63,907` | `72,408` | `72,762` |
| `dag_edges` | `975,745` | `640,636` | `642,742` |
| `boundary_values` | `1,349,093` | `1,270,895` | `1,497,792` |
| `boundary_activation_edges` | `2,460,976` | `2,457,899` | `2,687,215` |
| `other_compute_activation_edges` | `2,330,523` | `2,443,754` | `2,526,965` |
| `ops_p99` | `128` | `510` | `513` |
| `ops_max` | `4096` | `8192` | `4096` |

split detail:

- `oversize_compute_nodes=183`
- `split_supernodes=537`

结论：

- split1024 比 split128 明显少制造 boundary，但 `BAE=2.69M` 仍高于默认 `2.46M`，不是当前最佳结构点。
- 当前所有“把 MFFC 内部按 final op chunk 切开”的方案都会提高 BAE；它们解决代码尺寸风险，但牺牲了 C1 粗 MFFC 的主要收益。
- 下一步更合理的方向是：试 split cap 4096 / 8192 的 emit smoke，或做 emit-level function splitting，让单个 final supernode 保持 schedule 边界不变、只拆 C++ 函数体。
- fresh XiangShan emit/build、CoreMark 20k/50k 正确性和 cycles/s 提速仍未验收。

## 26. 增量更新 2026-05-19：MFFC+C1 op-size fresh XiangShan emit/build

本轮对当前最佳候选 `MFFC+C1 op-size` 重新做完整 `emit_grhsim_cpp` 和生成模型库构建，验证它不是只停在结构统计阶段。

emit 命令要点：

```text
timeout 2400 env
  WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1
  WOLVRIX_XS_GRHSIM_POST_STATS_JSON=/home/gaoruihao/wksp/wolvrix-playground/build/xs/grhsim/wolvrix_xs_post_stats.json
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD=1
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN=1
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_SIBLING_MERGE=0
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE=0
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE=0
  python3 scripts/wolvrix_xs_grhsim.py dummy.f SimTop tmp/no0093_xs_essent_c1_op_size_emit/grhsim_emit '' '' info
```

emit 结果：

- `activity-schedule`：`126,559 ms`
- `emit_grhsim_cpp`：`41,345 ms`
- 脚本总耗时：`188,795 ms`
- 输出目录：`tmp/no0093_xs_essent_c1_op_size_emit/grhsim_emit`
- 输出规模：约 `2.3G`，顶层文件 `2108` 个

结构统计：

| 指标 | 默认 | MFFC+C1 op-size fresh |
| --- | ---: | ---: |
| `compute_nodes` | `6,635,278` | `3,720,195` |
| `compute_supernodes` | `63,392` | `71,893` |
| `commit_supernodes` | `515` | `515` |
| `supernodes` | `63,907` | `72,408` |
| `dag_edges` | `975,745` | `640,636` |
| `boundary_values` | `1,349,093` | `1,270,895` |
| `boundary_activation_edges` | `2,460,976` | `2,457,899` |
| `other_compute_activation_edges` | `2,330,523` | `2,443,754` |
| `ops_p99` | `128` | `510` |
| `ops_max` | `4096` | `8192` |

生成模型库构建命令：

```text
timeout 3600 make -B -C tmp/no0093_xs_essent_c1_op_size_emit/grhsim_emit -j$(nproc) CXX=clang++
```

构建结果：

- 成功生成 `tmp/no0093_xs_essent_c1_op_size_emit/grhsim_emit/libgrhsim_SimTop.a`
- 静态库大小：`128M`
- 构建过程中存在 `logical '&&' with constant operand` 警告，但没有阻断生成。
- 需要显式使用 `CXX=clang++`；默认 `g++` 对当前生成的 `-include-pch` 路径不稳定。

当前结论：

- `MFFC+C1 op-size` 已通过 XiangShan grhsim C++ emit 和模型库 build smoke。
- 结构上主要收益是大幅降低 final DAG 边数；`BAE` 基本持平默认，`other_compute_activation_edges` 略升，因此真实 runtime 是否提速必须以 CoreMark 实测为准。
- 尚未完成验收项：接入 XiangShan difftest emu、CoreMark `20k` / `50k` 正确性、host 侧 `cycles/s` 与当前 `120 cycles/s` 基线对比。

## 27. 增量更新 2026-05-19：MFFC+C1 op-size XiangShan CoreMark 验收

为避免顶层 `xs_wolf_grhsim_emu` 重新 emit 并覆盖候选目录，本轮直接用 XiangShan difftest 的 grhsim 后端，把 `GRHSIM_MODEL_DIR` 指向第 26 节已生成的模型库目录。

emu 构建命令：

```text
timeout 3600 make -C testcase/xiangshan/difftest emu
  BUILD_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/no0093_xs_essent_c1_op_size_emu
  GEN_CSRC_DIR=/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/build/generated-src
  GEN_VSRC_DIR=/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/build/generated-src
  NUM_CORES=1
  WITH_CHISELDB=0
  WITH_CONSTANTIN=0
  GRHSIM=1
  GRHSIM_MODEL_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/no0093_xs_essent_c1_op_size_emit/grhsim_emit
  WOLVRIX_GRHSIM_WAVEFORM=0
  VM_BUILD_JOBS=$(nproc)
  CXX=clang++
  CC=clang
```

结果：成功生成 `tmp/no0093_xs_essent_c1_op_size_emu/grhsim-compile/emu`。

### CoreMark 20k bounded run

命令：

```text
timeout 600 env EMU_PROGRESS_EVERY_CYCLES=5000 stdbuf -oL -eL
  tmp/no0093_xs_essent_c1_op_size_emu/grhsim-compile/emu
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so
  -b 0 -e 0 -C 20000
```

结果：

- 退出码：`0`
- 未出现 difftest mismatch。
- `Guest cycle spent: 20001`
- `Host time spent: 116318ms`
- 折算 host 侧仿真速度：约 `172 cycles/s`

### CoreMark 50k bounded run

命令：

```text
timeout 900 env EMU_PROGRESS_EVERY_CYCLES=10000 stdbuf -oL -eL
  tmp/no0093_xs_essent_c1_op_size_emu/grhsim-compile/emu
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so
  -b 0 -e 0 -C 50000
```

结果：

- 退出码：`0`
- 未出现 difftest mismatch。
- `Guest cycle spent: 50001`
- `Host time spent: 403361ms`
- 折算 host 侧仿真速度：约 `124 cycles/s`

50k 进度点：

| model cycles | host ms | cumulative cycles/s |
| ---: | ---: | ---: |
| `10000` | `29180` | `343` |
| `20000` | `115690` | `173` |
| `30000` | `205971` | `146` |
| `40000` | `298495` | `134` |
| `50000` | `403347` | `124` |

验收结论：

- 正确性：`20k` 和 `50k` bounded CoreMark 均通过 difftest bounded smoke。
- 性能：相对当前约 `120 cycles/s` 的基线，`50k` 实测约 `124 cycles/s`，只有约 `3.3%` 提升。
- 当前 MFFC+C1 op-size 方案可以作为正确性通过的第一版 ESSENT/MFFC schedule，但提速幅度没有达到“显著优化”的目标。
- 结构原因与第 26 节一致：该方案降低了 `dag_edges`，但 `BAE` 基本持平，且 `other_compute_activation_edges` 增加；真实 runtime 只出现小幅收益。
- 后续若要继续拉大 XiangShan 提速，应优先做不增加 schedule boundary 的 emit-level function splitting，或重写 C2/C3/C4 的大图 merge 数据结构，而不是继续用 final chunk split 把 MFFC 内部值暴露成 boundary。

## 28. 增量更新 2026-05-19：C2 small-sibling bounded 快速路径

目标：让 C2 small-sibling merge 在 XiangShan 规模上不超时，并且带来结构正向收益。

实现调整：

- 新增 `ActivityScheduleOptions::essentSmallSiblingMaxPreds`，默认 `1`。
- Python flow 环境变量：`WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_MAX_PREDS`。
- C2 对 `maxPreds == 1` 使用 parent-bucket 快速路径：只扫描每个 parent 的 succ 列表，把“唯一 predecessor 就是该 parent”的 small sibling 放入同组。
- C2 从多轮 `while changed` 改成单轮 bounded merge，避免一次成功后反复全图重扫。
- 对完全相同 predecessor set 的 sibling 组，跳过 per-candidate 双向 path guard；在 DAG 中这些 sibling 互不可达，合并不会引入环。
- C2 输出仍做 topo 验证，但不再使用 value-local 重排，避免为 C2 额外构造完整 value-edge 视图。

验证：

```text
cmake --build wolvrix/build --target transform-activity-schedule -j$(nproc)
ctest --test-dir wolvrix/build --output-on-failure -R '^transform-activity-schedule$'
python3 -m py_compile scripts/wolvrix_xs_grhsim.py wolvrix/app/pybind/wolvrix/__init__.py
```

XiangShan structure-only 命令要点：

```text
timeout 900 env
  WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1
  WOLVRIX_XS_GRHSIM_POST_STATS_JSON=/home/gaoruihao/wksp/wolvrix-playground/build/xs/grhsim/wolvrix_xs_post_stats.json
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD=1
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN=1
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_SIBLING_MERGE=1
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE=0
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE=0
  WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1
  .venv/bin/python scripts/wolvrix_xs_grhsim.py dummy.f SimTop tmp/no0094_xs_essent_c1_c2_pred1/grhsim_emit '' '' info
```

结果：成功，写出 `tmp/no0094_xs_essent_c1_c2_pred1/grhsim_emit/activity_schedule_supernode_stats.json`。

关键耗时：

- `small_sibling elapsed_ms=1443`
- `activity-schedule total=127040 ms`
- 脚本总耗时：`149326 ms`

C2 phase stats：

- `essent_small_sibling_candidates=69057`
- `essent_small_sibling_merges=34222`
- `essent_small_sibling_rejected_size=34835`
- `essent_small_sibling_rejected_cycle=0`
- `essent_small_sibling_rejected_bounded=0`
- `essent_clusters_after_small_siblings=3409570`

结构对比：

| 指标 | C1 op-size | C1+C2 pred1 |
| --- | ---: | ---: |
| `activity-schedule total` | `126,559 ms` | `127,040 ms` |
| `compute_supernodes` | `71,893` | `72,099` |
| `supernodes` | `72,408` | `72,614` |
| `dag_edges` | `640,636` | `688,179` |
| `boundary_values` | `1,270,895` | `1,272,060` |
| `boundary_activation_edges` | `2,457,899` | `2,445,980` |
| `other_compute_activation_edges` | `2,443,754` | `2,431,835` |
| `ops_p99` | `510` | `508` |
| `ops_max` | `8192` | `8192` |

结论：

- C2 pred1 在 XiangShan 规模上不再超时，C2 自身耗时约 `1.4s`。
- 结构收益为正：`BAE` 降低 `11,919`，`other_compute_activation_edges` 降低 `11,919`。
- 代价是 `dag_edges` 和 `boundary_values` 略升，后续仍需 runtime 验证判断是否转化为 CoreMark 提速。
- 曾试 `essentSmallSiblingMaxPreds=8`，在 XiangShan 上仍长时间无阶段完成输出；因此当前默认采用低风险 `maxPreds=1`，先作为可用的 C2 大图路径。
- 下一步可以做两条线：
  - 为 C2 增加“收益预算/候选预算”后逐步放宽到 `maxPreds=2/4`。
  - 直接基于 C2 pred1 结果做 emit/build + `20k/50k` runtime 对比，确认 `BAE` 小幅下降是否能抵消 `dag_edges` 增长。

## 29. 增量更新 2026-05-19：C1+C2 pred1 emit/build/runtime 实测

本轮对第 28 节的 C1+C2 pred1 候选做完整 `emit_grhsim_cpp`、生成模型库构建、XiangShan difftest emu 链接和 CoreMark bounded runtime。

emit 命令要点：

```text
timeout 2400 env
  WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1
  WOLVRIX_XS_GRHSIM_POST_STATS_JSON=/home/gaoruihao/wksp/wolvrix-playground/build/xs/grhsim/wolvrix_xs_post_stats.json
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD=1
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN=1
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_SIBLING_MERGE=1
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE=0
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE=0
  WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_MAX_PREDS=1
  .venv/bin/python scripts/wolvrix_xs_grhsim.py dummy.f SimTop tmp/no0094_xs_essent_c1_c2_pred1_emit/grhsim_emit '' '' info
```

emit 结果：

- `activity-schedule`：`128069 ms`
- `write_grhsim_cpp`：`40426 ms`
- 脚本总耗时：`189738 ms`
- stats：`tmp/no0094_xs_essent_c1_c2_pred1_emit/grhsim_emit/activity_schedule_supernode_stats.json`

模型库构建：

```text
timeout 3600 /usr/bin/time -p make -B -C tmp/no0094_xs_essent_c1_c2_pred1_emit/grhsim_emit -j$(nproc) CXX=clang++
```

结果：

- 退出码：`0`
- `real 312.76`
- `user 7002.26`
- `sys 62.88`
- `libgrhsim_SimTop.a`：`129M`

XiangShan emu build 使用同一份 emit 产物作为 `GRHSIM_MODEL_DIR`，未触发重新 emit：

```text
timeout 3600 make -C testcase/xiangshan/difftest emu
  BUILD_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/no0094_xs_essent_c1_c2_pred1_emu
  GEN_CSRC_DIR=/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/build/generated-src
  GEN_VSRC_DIR=/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/build/generated-src
  NUM_CORES=1 WITH_CHISELDB=0 WITH_CONSTANTIN=0 GRHSIM=1
  GRHSIM_MODEL_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/no0094_xs_essent_c1_c2_pred1_emit/grhsim_emit
  WOLVRIX_GRHSIM_WAVEFORM=0 VM_BUILD_JOBS=$(nproc) CXX=clang++ CC=clang
```

结果：退出码 `0`，生成 `tmp/no0094_xs_essent_c1_c2_pred1_emu/grhsim-compile/emu`。

CoreMark 20k bounded run：

- 退出码：`0`
- 未出现 difftest mismatch。
- `Guest cycle spent: 20001`
- `Host time spent: 116559ms`
- 折算 host 侧仿真速度：约 `172 cycles/s`

CoreMark 50k bounded run：

- 退出码：`0`
- 未出现 difftest mismatch。
- `Guest cycle spent: 50001`
- `Host time spent: 406215ms`
- 折算 host 侧仿真速度：约 `123 cycles/s`

50k 进度点：

| model cycles | host ms | cumulative cycles/s |
| ---: | ---: | ---: |
| `10000` | `28289` | `354` |
| `20000` | `115840` | `173` |
| `30000` | `206909` | `145` |
| `40000` | `300235` | `133` |
| `50000` | `406201` | `123` |

与 C1 op-size 对比：

| 指标 | C1 op-size | C1+C2 pred1 |
| --- | ---: | ---: |
| `activity-schedule` | `126559 ms` | `128069 ms` |
| `write_grhsim_cpp` | `40477 ms` | `40426 ms` |
| `libgrhsim build real` | `310.94s` | `312.76s` |
| `20k Host time` | `116318ms` | `116559ms` |
| `20k speed` | `172 cycles/s` | `172 cycles/s` |
| `50k Host time` | `403361ms` | `406215ms` |
| `50k speed` | `124 cycles/s` | `123 cycles/s` |
| `boundary_activation_edges` | `2457899` | `2445980` |
| `other_compute_activation_edges` | `2443754` | `2431835` |
| `dag_edges` | `640636` | `688179` |

结论：

- C1+C2 pred1 的正确性 smoke 通过，emit/build 也稳定。
- C2 pred1 的结构收益没有转化为 runtime 收益；`BAE` 降低 `11919`，但 `dag_edges` 增加 `47543`，50k 速度从约 `124 cycles/s` 变为约 `123 cycles/s`。
- 当前数据支持“编译不慢，主要瓶颈仍在 runtime schedule 质量”的判断。
- 下一步应继续优化 C2/C3/C4 的 merge 策略和收益函数，优先让 merge 同时降低 `BAE` 与 `dag_edges`，再进入新的 emit/build/runtime AB。

## 30. 增量更新 2026-05-19：C2 bounded generalized grouping

本轮继续推进 C2 small-sibling merge，使 `maxPreds>1` 不再回到大图超时路径。

实现调整：

- 新增 `ActivityScheduleOptions::essentSmallSiblingCandidateBudget`，默认 `250000`。
- 新增 CLI 参数：`-essent-small-sibling-candidate-budget`。
- 新增 Python kwarg：`essent_small_sibling_candidate_budget`。
- 新增 XiangShan 环境变量：`WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_CANDIDATE_BUDGET`。
- C2 `maxPreds>1` 路径从 `unordered_map<vector<uint32_t>, vector<uint32_t>>` 改为：
  - 收集候选 entry：`signature, predCount, clusterId`。
  - 先按 predecessor count 从小到大收集，保证预算优先覆盖 pred1/pred2 低阶候选。
  - 按 `signature/predCount` 排序分桶。
  - 在桶内按真实 `preds` vector 排序并做 exact grouping，避免 hash collision 误合并。
- `maxPreds==1` 的 parent-bucket 快速路径保持不变。
- progress/detail log 增加 `max_preds` 和 `candidate_budget`，便于 XiangShan 大图调参。

验证：

```text
cmake --build wolvrix/build --target transform-activity-schedule -j$(nproc)
ctest --test-dir wolvrix/build --output-on-failure -R '^transform-activity-schedule$'
python3 -m py_compile scripts/wolvrix_xs_grhsim.py wolvrix/app/pybind/wolvrix/__init__.py
```

补充测试：

- 新增 `essent_coarsen_small_siblings_budgeted`，验证 candidate budget 可以限制 C2 候选收集，并保持 schedule 正确。

XiangShan structure-only AB 使用同一份 `wolvrix_xs_post_stats.json` checkpoint，关闭 C3/C4，只比较 C1+C2。

| 指标 | C1 op-size | C1+C2 pred1 | C1+C2 pred2 budget250k | C1+C2 pred4 layered budget250k |
| --- | ---: | ---: | ---: | ---: |
| `activity-schedule` | `126559 ms` | `128069 ms` | `127831 ms` | `127388 ms` |
| `small_sibling elapsed` | `0 ms` | `1456 ms` | `1425 ms` | `1432 ms` |
| `small_sibling candidates` | `0` | `69057` | `88811` | `105778` |
| `small_sibling merges` | `0` | `34222` | `57705` | `60673` |
| `compute_supernodes` | `71893` | `72099` | `72285` | `72233` |
| `supernodes` | `72408` | `72614` | `72800` | `72748` |
| `dag_edges` | `640636` | `688179` | `678663` | `684279` |
| `boundary_values` | `1270895` | `1272060` | `1266250` | `1267434` |
| `boundary_activation_edges` | `2457899` | `2445980` | `2437321` | `2440529` |
| `other_compute_activation_edges` | `2443754` | `2431835` | `2423176` | `2426384` |

观察：

- generalized C2 已经能在 XiangShan 大图上稳定跑完；pred2/pred4 的 C2 阶段仍约 `1.4s`。
- pred2 是当前最好的 C2 结构候选：相比 C1-only，`BAE` 降低 `20578`，`other_compute_activation_edges` 降低 `20578`；相比 pred1，又进一步降低 `8659`。
- pred4 虽然 merge 数更多，但结构不优于 pred2：`BAE` 与 `dag_edges` 都更高。原因是更宽的 sibling merge 会改变后续 final segmentation 和 DAG 形态，单纯增加 merge 数并不等于 runtime 收益。
- 当前 C2 下一步应以 pred2 为 runtime 候选做完整 emit/build/20k/50k；同时继续补收益函数，避免 pred4 这类“merge 更多但结构更差”的候选进入。

## 31. 增量更新 2026-05-19：C2 pred2 budget250k emit/build/runtime 实测

本轮对第 30 节 C2 generalized grouping 的 `maxPreds=2`、`candidateBudget=250000` 做完整 emit/build/runtime 验收。

命令要点：

```text
timeout 2400 env
  WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1
  WOLVRIX_XS_GRHSIM_POST_STATS_JSON=/home/gaoruihao/wksp/wolvrix-playground/build/xs/grhsim/wolvrix_xs_post_stats.json
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD=1
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN=1
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_SIBLING_MERGE=1
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE=0
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE=0
  WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_MAX_PREDS=2
  WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_CANDIDATE_BUDGET=250000
  .venv/bin/python scripts/wolvrix_xs_grhsim.py dummy.f SimTop tmp/no0095_xs_essent_c1_c2_pred2_budget250k_emit/grhsim_emit '' '' info
```

注意：这次完整 emit 使用的是“分层预算收集”后的实现，因此结构指标与第 30 节早先未分层 pred2 run 不同；实际 emit 产物的结构与 `pred4 layered budget250k` 一致。

emit 结果：

- `activity-schedule`：`128075 ms`
- `small_sibling elapsed`：`1464 ms`
- `small_sibling candidates`：`105778`
- `small_sibling merges`：`60673`
- `write_grhsim_cpp`：`41220 ms`
- 脚本总耗时：`190572 ms`
- stats：`tmp/no0095_xs_essent_c1_c2_pred2_budget250k_emit/grhsim_emit/activity_schedule_supernode_stats.json`

结构指标：

- `supernodes=72748`
- `compute_supernodes=72233`
- `commit_supernodes=515`
- `dag_edges=684279`
- `boundary_values=1267434`
- `boundary_activation_edges=2440529`
- `other_compute_activation_edges=2426384`
- `ops_p99=507`
- `ops_max=8192`

模型库构建：

```text
timeout 3600 /usr/bin/time -p make -B -C tmp/no0095_xs_essent_c1_c2_pred2_budget250k_emit/grhsim_emit -j$(nproc) CXX=clang++
```

结果：

- 退出码：`0`
- `real 311.51`
- `user 6920.24`
- `sys 64.23`
- `libgrhsim_SimTop.a`：`128M`

XiangShan emu build 使用同一份 emit 产物作为 `GRHSIM_MODEL_DIR`，未触发重新 emit：

```text
timeout 3600 make -C testcase/xiangshan/difftest emu
  BUILD_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/no0095_xs_essent_c1_c2_pred2_budget250k_emu
  GEN_CSRC_DIR=/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/build/generated-src
  GEN_VSRC_DIR=/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/build/generated-src
  NUM_CORES=1 WITH_CHISELDB=0 WITH_CONSTANTIN=0 GRHSIM=1
  GRHSIM_MODEL_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/no0095_xs_essent_c1_c2_pred2_budget250k_emit/grhsim_emit
  WOLVRIX_GRHSIM_WAVEFORM=0 VM_BUILD_JOBS=$(nproc) CXX=clang++ CC=clang
```

结果：退出码 `0`，生成 `tmp/no0095_xs_essent_c1_c2_pred2_budget250k_emu/grhsim-compile/emu`。

CoreMark 20k bounded run：

- 退出码：`0`
- 未出现 difftest mismatch。
- `Guest cycle spent: 20001`
- `Host time spent: 116330ms`
- 折算 host 侧仿真速度：约 `172 cycles/s`

CoreMark 50k bounded run：

- 退出码：`0`
- 未出现 difftest mismatch。
- `Guest cycle spent: 50001`
- `Host time spent: 400276ms`
- 折算 host 侧仿真速度：约 `125 cycles/s`

50k 进度点：

| model cycles | host ms | cumulative cycles/s |
| ---: | ---: | ---: |
| `10000` | `29409` | `340` |
| `20000` | `115107` | `174` |
| `30000` | `204453` | `147` |
| `40000` | `295676` | `135` |
| `50000` | `400262` | `125` |

与 C1 op-size / pred1 对比：

| 指标 | C1 op-size | C1+C2 pred1 | C1+C2 pred2 budget250k |
| --- | ---: | ---: | ---: |
| `activity-schedule` | `126559 ms` | `128069 ms` | `128075 ms` |
| `write_grhsim_cpp` | `40477 ms` | `40426 ms` | `41220 ms` |
| `libgrhsim build real` | `310.94s` | `312.76s` | `311.51s` |
| `20k Host time` | `116318ms` | `116559ms` | `116330ms` |
| `20k speed` | `172 cycles/s` | `172 cycles/s` | `172 cycles/s` |
| `50k Host time` | `403361ms` | `406215ms` | `400276ms` |
| `50k speed` | `124 cycles/s` | `123 cycles/s` | `125 cycles/s` |
| `boundary_activation_edges` | `2457899` | `2445980` | `2440529` |
| `other_compute_activation_edges` | `2443754` | `2431835` | `2426384` |
| `dag_edges` | `640636` | `688179` | `684279` |

结论：

- C2 pred2 budget250k 正确性通过，emit/build 稳定。
- 50k runtime 相比 C1-only 从 `403361ms` 降到 `400276ms`，约 `0.8%` 提升；相比 pred1 从 `406215ms` 降到 `400276ms`，约 `1.5%` 提升。
- C2 pred2 的结构收益可以转化为小幅 runtime 收益，但仍很弱；`dag_edges` 仍高于 C1-only `43643`，抵消了部分 `BAE` 下降。
- 下一步应继续做 C2 收益函数：以降低 `BAE/other_compute_activation_edges` 且不显著增加 `dag_edges` 为筛选条件，再决定是否继续放宽 pred 数或进入 C3/C4。

## 32. 增量更新 2026-05-19：C2 对齐 ESSENT edge-removed score

复查 `tmp/essent/src/main/scala/AcyclicPart.scala` 后确认：

- ESSENT 的 `mergeSmallSiblings` 本身按 exact input set 分组，输入完全相同的 small siblings 不需要额外 safety check。
- 参考实现中的收益语义来自 `numEdgesRemovedByMerge`：
  - `totalInDegree + totalOutDegree - (mergedInDegree + mergedOutDegree)`
  - 对 exact siblings 来说，主要等价于删除重复 input checks，并合并重复 output checks。
- 因此 C2 不应只按 group size 或预算扫描顺序合并；候选应按 edge-removed score 排序，并过滤 `score == 0`。

实现调整：

- 新增 C2 group score：`essentEdgesRemovedByMergeReq`。
- C2 group 构造时只保留 `edgesRemoved > 0` 的 exact sibling group。
- group 排序从 `group size desc` 改为：
  - `edgesRemoved desc`
  - `group size desc`
  - `ids lexicographic`
- 为避免 XiangShan 大图额外开销，score 计算针对 exact sibling 做局部计算：
  - predecessor set 必须相同；
  - `before = sum(inDegree + outDegree)`；
  - `after = commonPredCount + union(externalSuccs).size`；
  - 不为每个 group 分配全图 membership bitset。

验证：

```text
cmake --build wolvrix/build --target transform-activity-schedule -j$(nproc)
ctest --test-dir wolvrix/build --output-on-failure -R '^transform-activity-schedule$'
python3 -m py_compile scripts/wolvrix_xs_grhsim.py wolvrix/app/pybind/wolvrix/__init__.py
```

structure-only：`maxPreds=2, candidateBudget=250000`

- 结果与第 31 节一致。
- 说明在该预算截断下，候选基本都是正 edge-removed group，score 排序没有改变最终结构。

structure-only：full C2，`maxPreds=0, candidateBudget=0`

```text
timeout 900 env
  WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1
  WOLVRIX_XS_GRHSIM_POST_STATS_JSON=/home/gaoruihao/wksp/wolvrix-playground/build/xs/grhsim/wolvrix_xs_post_stats.json
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD=1
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN=1
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_SIBLING_MERGE=1
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE=0
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE=0
  WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_MAX_PREDS=0
  WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_CANDIDATE_BUDGET=0
  WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1
  .venv/bin/python scripts/wolvrix_xs_grhsim.py dummy.f SimTop tmp/no0096_xs_essent_c2_score_full/grhsim_emit '' '' info
```

结果：

- `activity-schedule`：`127313 ms`
- `small_sibling elapsed`：`1541 ms`
- `small_sibling candidates`：`347616`
- `small_sibling merges`：`248859`
- `supernodes=73368`
- `compute_supernodes=72853`
- `dag_edges=487673`
- `boundary_values=1128380`
- `boundary_activation_edges=2184186`
- `other_compute_activation_edges=2170041`

full C2 完整 emit/build/runtime：

```text
timeout 2400 env
  WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1
  WOLVRIX_XS_GRHSIM_POST_STATS_JSON=/home/gaoruihao/wksp/wolvrix-playground/build/xs/grhsim/wolvrix_xs_post_stats.json
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD=1
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN=1
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_SIBLING_MERGE=1
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE=0
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE=0
  WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_MAX_PREDS=0
  WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_CANDIDATE_BUDGET=0
  .venv/bin/python scripts/wolvrix_xs_grhsim.py dummy.f SimTop tmp/no0096_xs_essent_c2_score_full_emit/grhsim_emit '' '' info
```

emit/build 结果：

- `activity-schedule`：`128098 ms`
- `small_sibling elapsed`：`1558 ms`
- `small_sibling candidates`：`347616`
- `small_sibling merges`：`248859`
- `write_grhsim_cpp`：`41058 ms`
- 脚本总耗时：`190501 ms`
- `libgrhsim_SimTop.a` build：`real 302.35`
- `libgrhsim_SimTop.a` 大小：`120M`
- XiangShan emu build：成功

CoreMark 20k bounded run：

- 退出码：`0`
- 未出现 difftest mismatch。
- `Host time spent: 106820ms`
- 折算 host 侧仿真速度：约 `187 cycles/s`

CoreMark 50k bounded run：

- 退出码：`0`
- 未出现 difftest mismatch。
- `Host time spent: 378558ms`
- 折算 host 侧仿真速度：约 `132 cycles/s`

50k 进度点：

| model cycles | host ms | cumulative cycles/s |
| ---: | ---: | ---: |
| `10000` | `27089` | `369` |
| `20000` | `108648` | `184` |
| `30000` | `193188` | `155` |
| `40000` | `279432` | `143` |
| `50000` | `378545` | `132` |

与前序候选对比：

| 指标 | C1 op-size | C2 pred2 budget250k | C2 full edge-score |
| --- | ---: | ---: | ---: |
| `activity-schedule` | `126559 ms` | `128075 ms` | `128098 ms` |
| `small_sibling elapsed` | `0 ms` | `1464 ms` | `1558 ms` |
| `small_sibling merges` | `0` | `60673` | `248859` |
| `write_grhsim_cpp` | `40477 ms` | `41220 ms` | `41058 ms` |
| `libgrhsim build real` | `310.94s` | `311.51s` | `302.35s` |
| `libgrhsim size` | `129M` | `128M` | `120M` |
| `boundary_activation_edges` | `2457899` | `2440529` | `2184186` |
| `other_compute_activation_edges` | `2443754` | `2426384` | `2170041` |
| `dag_edges` | `640636` | `684279` | `487673` |
| `20k Host time` | `116318ms` | `116330ms` | `106820ms` |
| `50k Host time` | `403361ms` | `400276ms` | `378558ms` |
| `50k speed` | `124 cycles/s` | `125 cycles/s` | `132 cycles/s` |

结论：

- 用户关于“当前 C2 和 ESSENT 收益函数未对齐”的判断是对的；真正对齐后，关键不是保守 pred2，而是允许 full exact-sibling merge 并按 edge-removed score 筛选/排序。
- full C2 的结构指标同时改善 `BAE` 与 `dag_edges`，这与 runtime 提速一致。
- 相比 C1-only，50k host time 从 `403361ms` 降到 `378558ms`，提升约 `6.2%`。
- 相比当前目标口径 `120 cycles/s`，full C2 达到约 `132 cycles/s`，提升约 `10%`。
- 下一步可以基于 full C2 继续对齐 C3/C4，但需要保持同一个原则：以 ESSENT 的 edge-removed / input-check-saved 语义筛候选，不能只看 merge 数。

## 33. 增量更新 2026-05-19：C3 small-overlap 对齐 ESSENT 并复测

本轮开始实施 C3。对照 `tmp/essent/src/main/scala/AcyclicPart.scala` 的 `mergeSmallParts`，修正 C++ 原型与 ESSENT 的偏差：

- C3 overlap score 改为 `common_inputs / in_degree(id)`，不再用两个候选输入数的 max 作为分母。
- 保留 ESSENT order constraint：只考虑 `sibling < id`。
- 每个 small part `id` 只选择一个 top choice，再进入全局候选排序。
- C3 候选 sibling 不再要求也是 small part；ESSENT 只限制当前 `id` 来自 `findSmallParts`。合并时仍用总 op 数 cap 控制代码尺寸。
- 新增 `essent_small_overlap_candidate_budget`，并透传到 CLI、pybind 与 `scripts/wolvrix_xs_grhsim.py` 的 `WOLVRIX_XS_GRHSIM_ESSENT_SMALL_OVERLAP_CANDIDATE_BUDGET`。
- 新增回归用例，覆盖 small-overlap 可以选择非 small sibling 的行为。

本地验证：

- `cmake --build wolvrix/build --target transform-activity-schedule -j$(nproc)`：通过。
- `ctest --test-dir wolvrix/build --output-on-failure -R '^transform-activity-schedule$'`：通过。
- `python3 -m py_compile scripts/wolvrix_xs_grhsim.py wolvrix/app/pybind/wolvrix/__init__.py`：通过。

XiangShan structure-only 复测使用同一份 `wolvrix_xs_post_stats.json` checkpoint，配置为 full C2 后接 C3，关闭 C4：

```bash
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_SIBLING_MERGE=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE=0
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_MAX_PREDS=0
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_CANDIDATE_BUDGET=0
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_OVERLAP_CANDIDATE_BUDGET=250000
```

结构结果：

| 指标 | C2 full edge-score | C2 full + C3 `0.5` | C2 full + C3 `0.5/0.25` |
| --- | ---: | ---: | ---: |
| `activity-schedule` | `128098 ms` | `127302 ms` | `126870 ms` |
| `small_overlap elapsed` | `0 ms` | `244 ms` | `471 ms` |
| `small_overlap candidates` | `0` | `121` | `242` |
| `small_overlap merges` | `0` | `0` | `0` |
| `small_overlap rejected_size` | `0` | `121` | `242` |
| `compute_supernodes` | `72853` | `72853` | `72853` |
| `boundary_values` | `1128380` | `1128380` | `1128380` |
| `boundary_activation_edges` | `2184186` | `2184186` | `2184186` |
| `other_compute_activation_edges` | `2170041` | `2170041` | `2170041` |
| `dag_edges` | `487673` | `487673` | `487673` |

结论：

- C3 已按 ESSENT 语义完成可运行实现，并通过小图回归。
- 在 XiangShan full C2 后，C3 的可见候选全部被 `maxOpInComputeSupernode=128` 的 op-size cap 拒绝，`0.5` 与 `0.25` 两档都没有形成新的结构收益。
- 因为 `BAE`、`other_compute_activation_edges`、`dag_edges` 与 C2 full 完全一致，本轮不继续做 C3 的 fresh emit/build/20k/50k runtime；当前 runtime 候选仍是第 32 节的 C2 full edge-score。
- 下一步若要让 C3 产生收益，需要先解决 size-cap 约束下的候选选择问题，例如为 C3 top choice 增加 cap-aware 选择，或研究 `essentMaxClusterOps > 128` 配合后续 split 是否能降低整体 runtime。

## 34. 增量更新 2026-05-19：放宽 ESSENT cluster cap 到 256

为验证 C3 候选被 `maxOpInComputeSupernode=128` 拒绝后是否能通过放宽 cap 获得收益，本轮使用 `WOLVRIX_XS_GRHSIM_ESSENT_MAX_CLUSTER_OPS=256` 做 structure-only AB。注意该参数会放宽整个 ESSENT coarsen 的 merge cap，不只作用于 C3，因此分别测试 C2-only 与 C2+C3。

配置差异：

```bash
WOLVRIX_XS_GRHSIM_ESSENT_MAX_CLUSTER_OPS=256
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_MAX_PREDS=0
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_CANDIDATE_BUDGET=0
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_OVERLAP_CANDIDATE_BUDGET=250000
```

结构结果：

| 指标 | C2 full cap128 | C2 full cap256 | C2 full + C3 cap256 |
| --- | ---: | ---: | ---: |
| `activity-schedule` | `128098 ms` | `188524 ms` | `189122 ms` |
| `single_parent elapsed` | `46308 ms` | `107857 ms` | `107510 ms` |
| `small_sibling elapsed` | `1558 ms` | `1573 ms` | `1570 ms` |
| `small_overlap elapsed` | `0 ms` | `0 ms` | `472 ms` |
| `small_overlap candidates` | `0` | `0` | `252` |
| `small_overlap merges` | `0` | `0` | `0` |
| `small_overlap rejected_size` | `0` | `0` | `252` |
| `compute_supernodes` | `72853` | `37118` | `37118` |
| `boundary_values` | `1128380` | `1119715` | `1119715` |
| `boundary_activation_edges` | `2184186` | `2008051` | `2008051` |
| `other_compute_activation_edges` | `2170041` | `1993906` | `1993906` |
| `dag_edges` | `487673` | `277167` | `277167` |
| `ops_mean` | `124.559` | `242.830` | `242.830` |
| `ops_p90` | `128` | `256` | `256` |
| `ops_p99` | `499` | `559` | `559` |

结论：

- 放宽 cap 到 256 有明显结构收益：相比 cap128，`BAE` 下降约 `176135`，`dag_edges` 下降约 `210506`，compute supernodes 从 `72853` 降到 `37118`。
- 该收益来自 C1/C2 在更大 op-size cap 下继续合并；C3 仍然 `0` merge，且 cap256 下的 C3 候选仍全部被 size cap 拒绝。
- 成本也明显上升：`activity-schedule` 从约 `128s` 增到约 `189s`，主要来自 C1 single-parent 的候选和 bounded guard 增加。
- cap256 已经是新的 runtime 候选，但不应标记为 C3 收益；下一步应对 `C2 full cap256` 做 fresh emit/build/20k/50k，验证结构收益能否抵消更大 compute supernode 带来的 C++ 编译与执行成本。

## 35. 增量更新 2026-05-19：C2 full cap256 emit/build/runtime

本轮对第 34 节的 `C2 full cap256` 候选做完整 fresh emit、`libgrhsim_SimTop.a` build、XiangShan difftest emu build、CoreMark 20k/50k runtime。

fresh emit 命令要点：

```text
timeout 2400 env
  WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1
  WOLVRIX_XS_GRHSIM_POST_STATS_JSON=/home/gaoruihao/wksp/wolvrix-playground/build/xs/grhsim/wolvrix_xs_post_stats.json
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD=1
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN=1
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_SIBLING_MERGE=1
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE=0
  WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE=0
  WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_MAX_PREDS=0
  WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_CANDIDATE_BUDGET=0
  WOLVRIX_XS_GRHSIM_ESSENT_MAX_CLUSTER_OPS=256
  .venv/bin/python scripts/wolvrix_xs_grhsim.py dummy.f SimTop tmp/no0099_xs_essent_c2_full_cap256_emit/grhsim_emit '' '' info
```

emit 结果：

- `activity-schedule`：`189382 ms`
- `single_parent elapsed`：`108360 ms`
- `small_sibling elapsed`：`1558 ms`
- `small_sibling candidates`：`339927`
- `small_sibling merges`：`263186`
- `write_grhsim_cpp`：`41239 ms`
- 脚本总耗时：`251943 ms`
- stats：`tmp/no0099_xs_essent_c2_full_cap256_emit/grhsim_emit/activity_schedule_supernode_stats.json`

结构指标：

- `supernodes=37633`
- `compute_supernodes=37118`
- `commit_supernodes=515`
- `dag_edges=277167`
- `boundary_values=1119715`
- `boundary_activation_edges=2008051`
- `other_compute_activation_edges=1993906`
- `ops_mean=242.830`
- `ops_p90=256`
- `ops_p99=559`
- `ops_max=8192`

模型库构建：

```text
timeout 3600 /usr/bin/time -p make -B -C tmp/no0099_xs_essent_c2_full_cap256_emit/grhsim_emit -j$(nproc) CXX=clang++
```

结果：

- 退出码：`0`
- `real 302.15`
- `user 6631.02`
- `sys 61.02`
- `libgrhsim_SimTop.a`：`119M`
- sched `.cpp` 数量：`1028`

XiangShan emu build 使用同一份 emit 产物作为 `GRHSIM_MODEL_DIR`，未触发重新 emit：

```text
timeout 3600 make -C testcase/xiangshan/difftest emu
  BUILD_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/no0099_xs_essent_c2_full_cap256_emu
  GEN_CSRC_DIR=/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/build/generated-src
  GEN_VSRC_DIR=/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/build/generated-src
  NUM_CORES=1 WITH_CHISELDB=0 WITH_CONSTANTIN=0 GRHSIM=1
  GRHSIM_MODEL_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/no0099_xs_essent_c2_full_cap256_emit/grhsim_emit
  WOLVRIX_GRHSIM_WAVEFORM=0 VM_BUILD_JOBS=$(nproc) CXX=clang++ CC=clang
```

结果：退出码 `0`，生成 `tmp/no0099_xs_essent_c2_full_cap256_emu/grhsim-compile/emu`。

CoreMark 20k bounded run：

- 退出码：`0`
- 未出现 difftest mismatch。
- `Guest cycle spent: 20001`
- `Host time spent: 156446ms`
- 折算 host 侧仿真速度：约 `128 cycles/s`

CoreMark 50k bounded run：

- 退出码：`0`
- 未出现 difftest mismatch。
- `Guest cycle spent: 50001`
- `Host time spent: 508018ms`
- 折算 host 侧仿真速度：约 `98 cycles/s`

50k 进度点：

| model cycles | host ms | cumulative cycles/s |
| ---: | ---: | ---: |
| `10000` | `45398` | `220` |
| `20000` | `153340` | `130` |
| `30000` | `265810` | `113` |
| `40000` | `380592` | `105` |
| `50000` | `508001` | `98` |

与 cap128 full C2 对比：

| 指标 | C2 full cap128 | C2 full cap256 |
| --- | ---: | ---: |
| `activity-schedule` | `128098 ms` | `189382 ms` |
| `write_grhsim_cpp` | `41058 ms` | `41239 ms` |
| `libgrhsim build real` | `302.35s` | `302.15s` |
| `libgrhsim size` | `120M` | `119M` |
| `compute_supernodes` | `72853` | `37118` |
| `boundary_activation_edges` | `2184186` | `2008051` |
| `other_compute_activation_edges` | `2170041` | `1993906` |
| `dag_edges` | `487673` | `277167` |
| `20k Host time` | `106820ms` | `156446ms` |
| `50k Host time` | `378558ms` | `508018ms` |
| `50k speed` | `132 cycles/s` | `98 cycles/s` |

结论：

- cap256 的结构收益没有转成 runtime 收益；CoreMark 50k 从 cap128 full C2 的 `378558ms` 回退到 `508018ms`。
- 虽然 `BAE` 和 `dag_edges` 继续下降，但 compute supernode 变大后单次 eval 的局部代码体/缓存行为变差，抵消并超过 activation 边减少带来的收益。
- cap256 不应作为当前默认候选；当前最佳仍是第 32 节的 `C2 full cap128 edge-score`。
- 后续如果继续探索 cap，应优先做 `essentMaxClusterOps=160/192` 的结构与 20k 快速筛选，或引入 runtime-aware cap，而不是直接放到 256。

## 36. 增量更新 2026-05-19：coarsen cap256 + final cap128

第 35 节说明 `cap256` runtime 回退的核心原因不是 build，而是最终 compute supernode 从约 `72k` 降到 `37k`，单个 supernode 过大。为验证是否能“允许 C1/C2 在内部用 256 合并，但最终 emit 仍保持 70-80k compute supernodes”，本轮曾把实现拆成两个 cap：

- `essentMaxClusterOps`：只控制 ESSENT C1/C2/C3/C4 merge 的 cluster op-size cap。
- `maxOpInComputeSupernode`：继续控制 final DP segmentation 和 emit compute supernode op-size cap。

实现位置：

- `wolvrix/lib/transform/activity_schedule.cpp`
  - 新增局部 `maxOpsPerEssentCluster`。
  - C1/C2/C3/C4 merge 使用 `maxOpsPerEssentCluster`。
  - `buildComputeSupernodeSegments` 与 final flush 仍使用 `maxOpsPerComputeSupernode`。

验证：

- `cmake --build wolvrix/build --target transform-activity-schedule -j$(nproc)`：通过。
- `ctest --test-dir wolvrix/build --output-on-failure -R '^transform-activity-schedule$'`：通过。
- `python3 -m py_compile scripts/wolvrix_xs_grhsim.py wolvrix/app/pybind/wolvrix/__init__.py`：通过。

structure-only 命令要点：

```text
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_SIBLING_MERGE=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE=0
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE=0
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_MAX_PREDS=0
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_CANDIDATE_BUDGET=0
WOLVRIX_XS_GRHSIM_ESSENT_MAX_CLUSTER_OPS=256
WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1
```

结果：

- `activity-schedule`：`194553 ms`
- `single_parent elapsed`：`108016 ms`
- `small_sibling elapsed`：`1585 ms`
- `small_sibling candidates`：`339927`
- `small_sibling merges`：`263186`
- `segments=71541`
- `compute_supernodes=74261`
- `commit_supernodes=515`
- `dag_edges=487477`
- `boundary_values=1136101`
- `boundary_activation_edges=2200500`
- `other_compute_activation_edges=2186355`
- `ops_mean=122.212`
- `ops_median=123`
- `ops_p90=128`
- `ops_p99=469`

对比：

| 指标 | C2 full cap128 | coarsen cap256 + final cap128 | full cap256 |
| --- | ---: | ---: | ---: |
| `compute_supernodes` | `72853` | `74261` | `37118` |
| `boundary_activation_edges` | `2184186` | `2200500` | `2008051` |
| `other_compute_activation_edges` | `2170041` | `2186355` | `1993906` |
| `dag_edges` | `487673` | `487477` | `277167` |
| `ops_median` | `123` | `123` | `247` |
| `ops_p90` | `128` | `128` | `256` |

结论：

- “coarsen cap256 + final cap128”能把 compute supernodes 保持在 `70-80k`，避免第 35 节的 `37k` 大 supernode 问题。
- 但该结构不优于 cap128 full C2：`BAE` 与 `other_compute_activation_edges` 反而升高约 `16k`，只有 `dag_edges` 微降 `196`。
- 更重要的是，该实验破坏了 ESSENT partition 语义：final emit cap 小于 coarsen cap 时，final build 会把已经 merge 的 ESSENT cluster 按 op cap flush 成多个 compute supernode。ESSENT merge 后的 cluster 不应再被 final 阶段拆开。
- 因此该实验作废，不进入 fresh emit/build/runtime。
- 已修正实现：当 `essentMaxClusterOps > maxOpInComputeSupernode` 时，effective final compute-supernode cap 自动提升到 ESSENT coarsen cap，保证 `final cap >= coarsen cap`。
- 日志新增 `requested_max_ops_per_compute_supernode`、`effective_max_ops_per_compute_supernode`、`max_ops_per_essent_cluster`，用于确认是否触发该语义保护。

## 37. 增量更新 2026-05-19：移除 `essentMaxClusterOps`

复核 ESSENT 原始实现后确认，参考算法没有 `essentMaxClusterOps` 这类 cluster op-size cap。该参数是 grhsim 为 XiangShan 大图临时增加的保护，但实验阶段会遮蔽算法本身行为。因此本轮移除该参数，并把 ESSENT merge 阶段恢复为“不按 op-size cap 拒绝候选”的语义。

实现调整：

- 删除 `ActivityScheduleOptions::essentMaxClusterOps`。
- 删除 CLI 参数 `-essent-max-cluster-ops`。
- 删除 pybind kwarg `essent_max_cluster_ops`。
- 删除 XiangShan 脚本环境变量 `WOLVRIX_XS_GRHSIM_ESSENT_MAX_CLUSTER_OPS` 的读取、透传和日志。
- ESSENT C1/C2/C3/C4 merge 函数中，`maxNodes == 0` 表示不做 size reject；当前 ESSENT 路径统一传 `0`。
- 删除上一节新增的 effective/final/coarsen cap 保护日志；该保护随参数一起撤销。

验证：

- `cmake --build wolvrix/build --target transform-activity-schedule -j$(nproc)`：通过。
- `ctest --test-dir wolvrix/build --output-on-failure -R '^transform-activity-schedule$'`：通过。
- `python3 -m py_compile scripts/wolvrix_xs_grhsim.py wolvrix/app/pybind/wolvrix/__init__.py`：通过。

XiangShan structure-only：无 size cap、C1+C2 full、C3/C4 关闭。

```text
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_SIBLING_MERGE=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE=0
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE=0
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_MAX_PREDS=0
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_CANDIDATE_BUDGET=0
WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1
```

结果：

- `activity-schedule`：`190789 ms`
- `single_parent elapsed`：`107353 ms`
- `small_sibling elapsed`：`1536 ms`
- `single_parent merges`：`305822`
- `small_sibling merges`：`329802`
- `essent_merge_rejected_size=0`
- `clusters_after_essent_coarsen=3084571`
- `segments=68857`
- `compute_supernodes=74430`
- `dag_edges=485905`
- `boundary_values=1151073`
- `boundary_activation_edges=2216514`
- `other_compute_activation_edges=2202365`
- `ops_mean=121.938`
- `ops_median=123`
- `ops_p90=128`
- `ops_p99=465`

对比：

| 指标 | C2 full cap128 | C2 full no-size-cap |
| --- | ---: | ---: |
| `single_parent merges` | `276403` | `305822` |
| `small_sibling merges` | `248859` | `329802` |
| `essent_merge_rejected_size` | `319165` | `0` |
| `compute_supernodes` | `72853` | `74430` |
| `boundary_activation_edges` | `2184186` | `2216514` |
| `other_compute_activation_edges` | `2170041` | `2202365` |
| `dag_edges` | `487673` | `485905` |

结论：

- 去掉 size cap 后，ESSENT C1/C2 算法本身确实接受了更多 merge，且 size reject 归零。
- 但在 grhsim 当前 final segmentation / emit 图上，更多 merge 没有转化为更好的 final BAE；`BAE` 比 cap128 full C2 高约 `32328`，`other_compute_activation_edges` 高约 `32324`，只有 `dag_edges` 小幅下降。
- 因此后续重点应转到“ESSENT partition 与 grhsim final compute supernode 图的对应关系”，而不是继续加 size cap 保护。

## 38. 增量更新 2026-05-19：C4 small-parts-down 对齐 ESSENT

复查 `tmp/essent/src/main/scala/AcyclicPart.scala` 的 `mergeSmallPartsDown` 后，确认 C4 原型仍未完全对齐：

- ESSENT 对每个 small part `id` 只从 `mg.outNeigh(id)` 里选择一个 `topChoice`。
- `topChoice` 按 `numEdgesRemovedByMerge(Seq(id, childID))` 最大选择。
- 当前 C++ 原型之前按 `clusterEdgeWeight(valueEdges, parent, child)` 做全局排序，不是 ESSENT 的 edge-removed score，也不是 per-parent top choice。

实现调整：

- C4 score 改为复用 `essentEdgesRemovedByPair(view, parent, child)`。
- 每个 small parent 只保留一个 `removedEdges` 最大 child。
- 再把这些 per-parent top choices 按：
  - `removedEdges desc`
  - `parent asc`
  - `child asc`
  排序后执行 merge。
- 保持无 size cap；`maxNodes=0` 不触发 size reject。

验证：

- `cmake --build wolvrix/build --target transform-activity-schedule -j$(nproc)`：通过。
- `ctest --test-dir wolvrix/build --output-on-failure -R '^transform-activity-schedule$'`：通过。
- `python3 -m py_compile scripts/wolvrix_xs_grhsim.py wolvrix/app/pybind/wolvrix/__init__.py`：通过。

XiangShan structure-only：无 size cap、C1+C2+C4，关闭 C3。

```text
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_SIBLING_MERGE=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE=0
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE=1
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_MAX_PREDS=0
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_CANDIDATE_BUDGET=0
WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1
```

结果：

- `activity-schedule`：`225438 ms`
- `essent_down elapsed`：`36874 ms`
- `essent_down_candidates=751418`
- `essent_down_merges=0`
- `essent_down_rejected_cycle=152886`
- `essent_down_rejected_bounded=13914`
- `essent_merge_rejected_topo=1`
- 最终结构与第 37 节 C1+C2 无 cap 相同：
  - `compute_supernodes=74430`
  - `dag_edges=485905`
  - `boundary_values=1151073`
  - `boundary_activation_edges=2216514`
  - `other_compute_activation_edges=2202365`

结论：

- C4 当前已按 ESSENT 的 per-parent top-choice / edge-removed score 对齐。
- 在 XiangShan C1+C2 full 后，C4 产生大量候选，但没有接受任何 merge；候选主要被 external path cycle guard 拒绝。
- C4 在当前顺序下没有结构收益，只增加约 `36.9s` activity-schedule 时间。
- 下一步若继续验证 ESSENT 完整 partition，应跑 `C1+C2+C3+C4`，以及 ESSENT 原始顺序中的 `small2`：`mergeSmallParts(2*smallPartCutoff, 0.25)`；但需要先接受 C3/C4 会显著增加 schedule 时间。

## 39. 增量更新 2026-05-19：C1/C2/C3/C4 全流程 no-size-cap 结构检查

目标：按当前已实现的 ESSENT C1/C2/C3/C4 顺序做一次完整 structure-only，确认收益为什么没有继续转化到 grhsim final 指标。

配置：

```text
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_SIBLING_MERGE=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE=1
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_MAX_PREDS=0
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_CANDIDATE_BUDGET=0
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_OVERLAP_CANDIDATE_BUDGET=250000
WOLVRIX_XS_GRHSIM_ESSENT_OVERLAP_THRESHOLD1=0.5
WOLVRIX_XS_GRHSIM_ESSENT_OVERLAP_THRESHOLD2=0.25
WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1
```

结果：

- `activity-schedule`：`307971 ms`
- `single_parent elapsed`：`108090 ms`
- `small_sibling elapsed`：`1558 ms`
- `small_overlap elapsed`：`81076 ms`
- `essent_down elapsed`：`38655 ms`
- `essent_single_parent_merges=305822`
- `essent_small_sibling_merges=329802`
- `essent_small_overlap_candidates=4480`
- `essent_small_overlap_merges=4048`
- `essent_small_overlap_rejected_cycle=51`
- `essent_small_overlap_rejected_bounded=381`
- `essent_down_candidates=747501`
- `essent_down_merges=0`
- `essent_down_rejected_cycle=154910`
- `essent_down_rejected_bounded=13927`
- `essent_merge_rejected_size=0`

结构对比：

| 指标 | C2 full cap128 | C1+C2 no-size-cap | C1+C2+C3+C4 no-size-cap |
| --- | ---: | ---: | ---: |
| `clusters_after_essent_coarsen` | `3194933` | `3084571` | `3080523` |
| `compute_supernodes` | `72853` | `74430` | `74448` |
| `dag_edges` | `487673` | `485905` | `484400` |
| `boundary_values` | `1128380` | `1151073` | `1151083` |
| `boundary_activation_edges` | `2184186` | `2216514` | `2221157` |
| `other_compute_activation_edges` | `2170041` | `2202365` | `2207008` |
| `other_compute_duplicate_activation_edges` | `1684306` | `1718318` | `1724463` |
| `other_compute_multi_target_activation_edges` | `1455997` | `1493663` | `1500879` |
| `other_compute_unique_supernode_pairs` | `485735` | `484047` | `482545` |
| `ops_mean` | `124.559` | `121.938` | `121.909` |
| `ops_p99` | `499` | `465` | `465` |
| `ops_max` | `8192` | `8192` | `8192` |

判断：

- C3 确实发生了算法合并：cluster 数从 `3084571` 降到 `3080523`，接受 `4048` 个 small-overlap merge。
- 但 C3 后 final `compute_supernodes` 反而从 `74430` 增到 `74448`；说明 coarsen cluster 的局部合并改变了后续 final materialization / segmentation 的切分边界，最终 supernode 数没有下降。
- `dag_edges` 从 `485905` 降到 `484400`，但 `boundary_values` 基本持平，`boundary_activation_edges` 增加 `4643`，`other_compute_duplicate_activation_edges` 增加 `6145`。所以没收益的直接原因是：C3 降低了少量唯一 pair/DAG 边，却制造了更多 duplicate activation。
- C4 在完整流里仍然没有接受 merge：`747501` 个 down 候选最终 `0` merge，主要被 external path cycle guard 拒绝。因此 C4 当前只增加 schedule 时间，不改变结构。
- 这组结构不适合继续 fresh emit/build/runtime；与当前最好的第 32 节 `C2 full cap128` 相比，`BAE` 高 `36971`，`other_compute_activation_edges` 高 `36967`。

下一步：

- 不再盲目跑完整 runtime；先加 C3/C4 诊断，把 ESSENT 局部 score 与 grhsim final activation 指标接起来。
- C3 需要记录 accepted merge 的 `commonInputs/inputCount`、`removedEdges`、合并双方 op size/fanout，以及 materialize 后对应 final supernode 的 boundary/duplicate activation 变化。
- C4 需要拆分 cycle guard 统计：区分存在真实 alternate path、visit bound 不足、以及 DSU 批量合并后候选失效；否则无法判断是 ESSENT 原图确实不可合并，还是当前 guard 太保守。
- `small2` 仍未实现；但在 C3 第一轮已使 final BAE 变差的前提下，应先完成上述诊断，再决定是否补 ESSENT 原始 `mergeSmallParts(2*smallPartCutoff, 0.25)`。

## 40. 增量更新 2026-05-19：C3/C4 ESSENT 对齐诊断

本轮目标：把 C3/C4 的候选选择阶段继续向 `tmp/essent/src/main/scala/AcyclicPart.scala` 对齐，并补充能解释“为什么没收益”的诊断字段。

ESSENT 对齐点：

- C3 `mergeSmallParts`：
  - 对每个 small part `id` 找 siblings；
  - 只保留 `sibID < id`；
  - overlap score 为 `|in(sibID) intersect in(id)| / |in(id)|`；
  - 先过滤 `score >= threshold`；
  - 在该 small part 内按 score 从高到低找第一个 `mergeIsAcyclic(sibID, id)` 的 topChoice。
- C4 `mergeSmallPartsDown`：
  - 对每个 small part `id` 找 children；
  - 先过滤 `mergeIsAcyclic(id, childID)`；
  - 在合法 children 中按 `numEdgesRemovedByMerge(Seq(id, childID))` 选 topChoice。

实现调整：

- C3/C4 候选选择阶段改成先做 acyclic 过滤，再确定 topChoice。
- 补充 summary/log 诊断字段：
  - `*_small_parts`
  - `*_raw_candidates`
  - `*_threshold_candidates`（C3）
  - `*_acyclic_candidates`
  - `*_acyclic_rejected`
  - `*_inactive_rejected`
  - `*_candidate_removed_edges`
  - `*_accepted_removed_edges`

验证：

- `cmake --build wolvrix/build --target transform-activity-schedule -j$(nproc)`：通过。
- `ctest --test-dir wolvrix/build --output-on-failure -R '^transform-activity-schedule$'`：通过。
- `python3 -m py_compile scripts/wolvrix_xs_grhsim.py wolvrix/app/pybind/wolvrix/__init__.py`：通过。

XiangShan structure-only：C1+C2+C3+C4 no-size-cap，C3/C4 acyclic-first 诊断版。

结果：

- `activity-schedule`：`595742 ms`
- `small_overlap elapsed`：`385773 ms`
- `down elapsed`：`15843 ms`
- `essent_small_overlap_merges=4542`
- `essent_down_merges=0`
- `clusters_after_essent_coarsen=3080029`
- `compute_supernodes=74430`
- `dag_edges=484429`
- `boundary_values=1151224`
- `boundary_activation_edges=2221617`
- `other_compute_activation_edges=2207468`

C3 诊断：

| 指标 | 值 |
| --- | ---: |
| `essent_small_overlap_small_parts` | `101430` |
| `essent_small_overlap_raw_candidates` | `189423` |
| `essent_small_overlap_threshold_candidates` | `64510` |
| `essent_small_overlap_acyclic_candidates` | `63266` |
| `essent_small_overlap_acyclic_rejected` | `1244` |
| `essent_small_overlap_candidates` | `4773` |
| `essent_small_overlap_merges` | `4542` |
| `essent_small_overlap_candidate_removed_edges` | `11968` |
| `essent_small_overlap_accepted_removed_edges` | `11910` |

C4 诊断：

| 指标 | 值 |
| --- | ---: |
| `essent_down_small_parts` | `3023517` |
| `essent_down_raw_candidates` | `2295051` |
| `essent_down_acyclic_candidates` | `1697797` |
| `essent_down_acyclic_rejected` | `597254` |
| `essent_down_candidates` | `733308` |
| `essent_down_rejected_cycle` | `534817` |
| `essent_down_rejected_bounded` | `205362` |
| `essent_down_candidate_removed_edges` | `1857410` |
| `essent_down_accepted_removed_edges` | `1428777` |
| `essent_down_merges` | `0` |

判断：

- C3 的 acyclic-first 对齐有效：merge 数从第 39 节 `4048` 增到 `4542`。之前“先选 topChoice、再做 acyclic guard”的实现会漏掉部分 ESSENT 合法候选。
- 但 C3 对齐后结构更差：`BAE=2221617`，比第 39 节 `2221157` 又高 `460`，比当前最好 C2 cap128 `2184186` 高 `37431`。
- C3 的主要代价来自候选阶段 reachability：`64510` 个 threshold candidate 中有 `63266` 个 individually acyclic，schedule 时间从第 39 节约 `308s` 增到约 `596s`。
- C4 并不是没有合法候选：有 `1697797` 个 individually acyclic child candidate，候选 topChoice 的 edge-removed 总和也很大。
- 但 C4 当前批处理执行仍不等价于 ESSENT 的 `perfomMergesIfPossible`。日志里 `accepted_removed_edges=1428777` 表示批内 DSU 接受过 merge；最终 `essent_down_merges=0` 是因为整批合并后的 `orderNodeClustersTopologically` 失败，函数返回 false，外层丢弃了整个 C4 结果。ESSENT 原版是逐个 merge request 尝试，失败只跳过单个 request，不会因为批末 topo 失败清空整批。

补充验证：尝试了更接近 ESSENT 的动态逐请求执行原型，即每个 candidate 用当前 DSU 聚合图做可达性检查后立即合并。该原型在 C3 阶段跑到 `20+ min` 仍未完成，CPU 100%，已中止；原因是朴素动态 reachability 会反复扫描 root members，不适合 XiangShan 规模。

下一步：

- 保留当前 acyclic-first 候选诊断字段。
- 若继续对齐 C4，不能用朴素动态 rootMembers 扫描；需要专门实现高性能动态 cluster DAG：
  - merge 后维护 root-level succ/pred adjacency；
  - 支持跳过 inactive roots；
  - cycle check 在当前 compressed DAG 上做 bounded DFS；
  - 单个 merge 失败只跳过该 request，不回滚整轮。
- 在这个动态 DAG 可用前，不应跑 C4 runtime；当前可实测候选仍是第 32 节 C2 full cap128。

## 41. 增量更新 2026-05-19：C4 高性能动态 cluster DAG

本轮目标：继续 C4，实现一个可在 XiangShan 规模上运行的动态 cluster DAG，使 `mergeSmallPartsDown` 不再因为批末 topo 失败清空整轮结果。

实现：

- 新增 C4 专用 `DynamicEssentClusterDag`。
- 维护：
  - `DisjointSet` 当前 root；
  - root-level `succs` adjacency；
  - DFS `seen/stack/stamp` 工作区。
- 每次 C4 candidate 执行时：
  - 先用当前 DSU root 压缩 `lhs/rhs`；
  - 在动态 root DAG 上做 bounded DFS；
  - 跳过 self edge、direct `lhs -> rhs` edge 和当前 merge 两端；
  - 失败只拒绝当前 candidate；
  - 成功后立即合并 DSU root，并把被合并 root 的 succ row 合到新 root。
- 只把动态 DAG 用在 C4 执行阶段；C1/C2/C3 执行语义保持不变。

验证：

- `cmake --build wolvrix/build --target transform-activity-schedule -j$(nproc)`：通过。
- `ctest --test-dir wolvrix/build --output-on-failure -R '^transform-activity-schedule$'`：通过。
- `python3 -m py_compile scripts/wolvrix_xs_grhsim.py wolvrix/app/pybind/wolvrix/__init__.py`：通过。
- 已同步 `.venv` 的 `libwolvrix-lib.so`。

### 41.1 C4-only：C1+C2+C4 dynamic，关闭 C3

配置：

```text
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_SIBLING_MERGE=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE=0
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE=1
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_MAX_PREDS=0
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_CANDIDATE_BUDGET=0
WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1
```

结果：

- `activity-schedule`：`351873 ms`
- `essent_down elapsed`：`164991 ms`
- `essent_down_merges=766863`
- `essent_down_candidates=807730`
- `essent_down_small_parts=45527976`
- `essent_down_raw_candidates=6859568`
- `essent_down_acyclic_candidates=2783566`
- `essent_down_acyclic_rejected=4076002`
- `essent_down_rejected_cycle=1154924`
- `essent_down_rejected_bounded=2961945`
- `essent_down_candidate_removed_edges=2172339`
- `essent_down_accepted_removed_edges=2050792`
- `clusters_after_essent_coarsen=2317708`
- `compute_supernodes=76592`
- `dag_edges=475522`
- `boundary_values=1113044`
- `boundary_activation_edges=2146343`
- `other_compute_activation_edges=2132195`
- `ops_mean=117.818`
- `ops_p99=450`
- `ops_max=8192`

### 41.2 Full：C1+C2+C3+C4 dynamic

配置：

```text
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_SIBLING_MERGE=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE=1
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_MAX_PREDS=0
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_CANDIDATE_BUDGET=0
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_OVERLAP_CANDIDATE_BUDGET=250000
WOLVRIX_XS_GRHSIM_ESSENT_OVERLAP_THRESHOLD1=0.5
WOLVRIX_XS_GRHSIM_ESSENT_OVERLAP_THRESHOLD2=0.25
WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1
```

结果：

- `activity-schedule`：`731237 ms`
- `small_overlap elapsed`：`384025 ms`
- `essent_small_overlap_merges=4542`
- `essent_down elapsed`：`162818 ms`
- `essent_down_merges=765253`
- `essent_down_candidates=809842`
- `essent_down_small_parts=45498686`
- `essent_down_raw_candidates=6810710`
- `essent_down_acyclic_candidates=2769706`
- `essent_down_acyclic_rejected=4041004`
- `essent_down_rejected_cycle=1248513`
- `essent_down_rejected_bounded=2837080`
- `essent_down_candidate_removed_edges=2208781`
- `essent_down_accepted_removed_edges=2086067`
- `clusters_after_essent_coarsen=2314776`
- `compute_supernodes=76947`
- `dag_edges=474243`
- `boundary_values=1105512`
- `boundary_activation_edges=2139243`
- `other_compute_activation_edges=2125095`
- `ops_mean=117.204`
- `ops_p99=443`
- `ops_max=8192`

结构对比：

| 指标 | C2 full cap128 | C1+C2 no-cap | C1+C2+C4 dynamic | C1+C2+C3+C4 dynamic |
| --- | ---: | ---: | ---: | ---: |
| `clusters_after_essent_coarsen` | `3194933` | `3084571` | `2317708` | `2314776` |
| `compute_supernodes` | `72853` | `74430` | `76592` | `76947` |
| `dag_edges` | `487673` | `485905` | `475522` | `474243` |
| `boundary_values` | `1128380` | `1151073` | `1113044` | `1105512` |
| `boundary_activation_edges` | `2184186` | `2216514` | `2146343` | `2139243` |
| `other_compute_activation_edges` | `2170041` | `2202365` | `2132195` | `2125095` |
| `ops_mean` | `124.559` | `121.938` | `117.818` | `117.204` |
| `ops_p99` | `499` | `465` | `450` | `443` |

判断：

- C4 dynamic 是目前第一组明确优于 C2 cap128 的 ESSENT 结构收益。
- C4-only 相比 C2 cap128：
  - `BAE` 降低 `37843`
  - `other_compute_activation_edges` 降低 `37846`
  - `dag_edges` 降低 `12151`
- Full C1+C2+C3+C4 dynamic 相比 C2 cap128：
  - `BAE` 降低 `44943`
  - `other_compute_activation_edges` 降低 `44946`
  - `dag_edges` 降低 `13430`
- C3 在 dynamic C4 后不再是纯负贡献：full 比 C4-only 的 `BAE` 又低 `7100`，`dag_edges` 低 `1279`。
- 但 C3 的 schedule 成本仍很高：full `activity-schedule=731237 ms`，C4-only `351873 ms`。

下一步：

- 先拿 `C1+C2+C4 dynamic` 做 fresh emit/build/20k/50k runtime，因为它结构收益明显且 schedule 成本较低。
- 若 runtime 能转化，再跑 `C1+C2+C3+C4 dynamic` fresh emit/build/20k/50k，判断多 `7100` BAE 收益是否抵得过更长 emit 前处理和可能改变的代码布局。

## 42. 增量更新 2026-05-19：C1+C2+C4 dynamic emit/build/runtime

本轮按第 41 节结论，把 `C1+C2+C4 dynamic` 作为主体候选，做完整 fresh emit、`libgrhsim_SimTop.a` build、XiangShan difftest emu build、CoreMark 20k/50k runtime。C3 保持关闭。

配置：

```text
WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1
WOLVRIX_XS_GRHSIM_POST_STATS_JSON=/home/gaoruihao/wksp/wolvrix-playground/build/xs/grhsim/wolvrix_xs_post_stats.json
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_SIBLING_MERGE=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE=0
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE=1
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_MAX_PREDS=0
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_CANDIDATE_BUDGET=0
```

fresh emit 结果：

- 输出目录：`tmp/no0108_xs_essent_c4_dynamic_emit/grhsim_emit`
- `activity-schedule`：`350219 ms`
- `essent_down elapsed`：`165921 ms`
- `write_grhsim_cpp`：`39757 ms`
- 脚本总耗时：`411513 ms`
- `essent_small_sibling_merges=329802`
- `essent_down_merges=766863`
- `essent_down_candidates=807730`
- `essent_down_small_parts=45527976`
- `essent_down_raw_candidates=6859568`
- `essent_down_acyclic_candidates=2783566`
- `essent_down_acyclic_rejected=4076002`
- `essent_down_rejected_cycle=1154924`
- `essent_down_rejected_bounded=2961945`
- `essent_down_candidate_removed_edges=2172339`
- `essent_down_accepted_removed_edges=2050792`
- `clusters_after_essent_coarsen=2317708`
- `compute_supernodes=76592`
- `dag_edges=475522`
- `boundary_values=1113044`
- `boundary_activation_edges=2146343`
- `other_compute_activation_edges=2132195`
- `ops_mean=117.818`
- `ops_median=118`
- `ops_p90=128`
- `ops_p99=450`
- `ops_max=8192`

model library build：

```text
timeout 3600 /usr/bin/time -p make -B -C tmp/no0108_xs_essent_c4_dynamic_emit/grhsim_emit -j$(nproc) CXX=clang++
```

结果：

- 退出码：`0`
- `real 301.13`
- `user 6728.07`
- `sys 62.27`
- `libgrhsim_SimTop.a` 大小：`119M`
- `grhsim_SimTop_sched_*.cpp` 数量：`996`

XiangShan emu build：

```text
timeout 3600 make -C testcase/xiangshan/difftest emu
  BUILD_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/no0108_xs_essent_c4_dynamic_emu
  GEN_CSRC_DIR=/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/build/generated-src
  GEN_VSRC_DIR=/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/build/generated-src
  NUM_CORES=1
  WITH_CHISELDB=0
  WITH_CONSTANTIN=0
  GRHSIM=1
  GRHSIM_MODEL_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/no0108_xs_essent_c4_dynamic_emit/grhsim_emit
  WOLVRIX_GRHSIM_WAVEFORM=0
  VM_BUILD_JOBS=$(nproc)
  CXX=clang++
  CC=clang
```

结果：成功生成 `tmp/no0108_xs_essent_c4_dynamic_emu/grhsim-compile/emu`，大小 `110M`。

CoreMark 20k bounded run：

```text
timeout 1200 env EMU_PROGRESS_EVERY_CYCLES=5000 stdbuf -oL -eL
  tmp/no0108_xs_essent_c4_dynamic_emu/grhsim-compile/emu
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so
  -b 0 -e 0 -C 20000
```

结果：

- 退出码：`0`
- 未出现 difftest mismatch。
- `Guest cycle spent: 20001`
- `Host time spent: 116360ms`
- 折算 host 侧仿真速度：约 `171.9 cycles/s`

CoreMark 50k bounded run：

```text
timeout 1800 env EMU_PROGRESS_EVERY_CYCLES=10000 stdbuf -oL -eL
  tmp/no0108_xs_essent_c4_dynamic_emu/grhsim-compile/emu
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so
  -b 0 -e 0 -C 50000
```

结果：

- 退出码：`0`
- 未出现 difftest mismatch。
- `Guest cycle spent: 50001`
- `Host time spent: 386258ms`
- 折算 host 侧仿真速度：约 `129.4 cycles/s`

50k 进度点：

| model cycles | host ms | cumulative cycles/s |
| ---: | ---: | ---: |
| `10000` | `34709` | `288` |
| `20000` | `116805` | `171` |
| `30000` | `201713` | `149` |
| `40000` | `288255` | `139` |
| `50000` | `386245` | `129` |

与当前关键基线对比：

| 指标 | C1-only | C2 full cap128 | C1+C2+C4 dynamic |
| --- | ---: | ---: | ---: |
| `compute_supernodes` | `73289` | `72853` | `76592` |
| `dag_edges` | `545207` | `487673` | `475522` |
| `boundary_activation_edges` | `2399091` | `2184186` | `2146343` |
| `other_compute_activation_edges` | `2384942` | `2170041` | `2132195` |
| 20k `Host time spent` | `116318ms` | `106820ms` | `116360ms` |
| 50k `Host time spent` | `403361ms` | `378558ms` | `386258ms` |
| 50k throughput | `124.0 cycles/s` | `132.1 cycles/s` | `129.4 cycles/s` |

判断：

- 结构收益成立：相比 C2 full cap128，C4 dynamic 的 `BAE` 低 `37843`，约 `1.73%`；`dag_edges` 低 `12151`，约 `2.49%`；`other_compute_activation_edges` 低 `37846`，约 `1.74%`。
- 结构收益没有完全转成 runtime：50k `386258ms` 比 C2 full cap128 的 `378558ms` 慢 `7700ms`，约 `2.03%`。
- 但它仍优于 C1-only：50k 比 `403361ms` 快 `17103ms`，约 `4.24%`。
- 因此当前 runtime 最佳仍是 `C2 full cap128`；`C1+C2+C4 dynamic` 说明 C4 dynamic 能改善图结构，但需要进一步解释为什么更低 BAE/dag_edges 反而拖慢执行。

下一步诊断重点：

- 对比 C2 cap128 与 C4 dynamic 的 emitted C++ 形态：`compute_supernodes` 从 `72853` 增到 `76592`，可能导致更多调度函数/activation bookkeeping，即使 BAE 降低也抵消收益。
- 对 50k 跑 `perf stat` 或轻量 profile，区分时间落在 activation 队列、compute 调用、boundary value load/store，还是 generated code 指令缓存/分支行为。
- 暂不把 C4 dynamic 设为默认主体；保留 C2 full cap128 作为 runtime 基线，C4 dynamic 作为结构优化分支继续诊断。

## 43. NO0109: C2 full cap128 + emitted activation merge 的 CoreMark 50k 复测

目的：在第 32 节 runtime 最佳配置 `C2 full cap128` 上，只叠加 GrhSIM C++ emit 的 successor activation 合并优化，观察重复 activation 写出减少能否转成 CoreMark 50k runtime 收益。

配置：

```text
WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1
WOLVRIX_XS_GRHSIM_POST_STATS_JSON=build/xs/grhsim/wolvrix_xs_post_stats.json
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_SIBLING_MERGE=1
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE=0
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE=0
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_MAX_PREDS=0
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_CANDIDATE_BUDGET=0
```

fresh emit 输出目录：

```text
tmp/no0109_xs_emit_activation_merge_c2_full_emit/grhsim_emit
```

emit 结果：

- `activity-schedule done`: `187654ms`
- `write_grhsim_cpp done`: `40499ms`
- script total: `249345ms`
- `supernodes`: `74945`
- `compute_supernodes`: `74430`
- `commit_supernodes`: `515`
- `dag_edges`: `485905`
- `boundary_values`: `1151073`
- `boundary_activation_edges`: `2216514`

model build：

```text
timeout 3600 /usr/bin/time -p make -B -C tmp/no0109_xs_emit_activation_merge_c2_full_emit/grhsim_emit -j$(nproc) CXX=clang++
```

结果：

- `real`: `303.60s`
- `user`: `6737.02s`
- `sys`: `59.72s`
- `libgrhsim_SimTop.a`: `122M`
- `grhsim_SimTop_sched_*.cpp`: `994`

XiangShan difftest emu build：

```text
timeout 3600 make -C testcase/xiangshan/difftest emu
  BUILD_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/no0109_xs_emit_activation_merge_c2_full_emu
  GEN_CSRC_DIR=/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/build/generated-src
  GEN_VSRC_DIR=/home/gaoruihao/wksp/wolvrix-playground/testcase/xiangshan/build/generated-src
  NUM_CORES=1
  WITH_CHISELDB=0
  WITH_CONSTANTIN=0
  GRHSIM=1
  GRHSIM_MODEL_DIR=/home/gaoruihao/wksp/wolvrix-playground/tmp/no0109_xs_emit_activation_merge_c2_full_emit/grhsim_emit
  WOLVRIX_GRHSIM_WAVEFORM=0
  VM_BUILD_JOBS=$(nproc)
  CXX=clang++
  CC=clang
```

结果：成功生成 `tmp/no0109_xs_emit_activation_merge_c2_full_emu/grhsim-compile/emu`，大小 `111M`。

CoreMark 50k bounded run：

```text
timeout 1800 env EMU_PROGRESS_EVERY_CYCLES=10000 stdbuf -oL -eL
  tmp/no0109_xs_emit_activation_merge_c2_full_emu/grhsim-compile/emu
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so
  -b 0 -e 0 -C 50000
```

结果：

- 退出码：`0`
- 未出现 difftest mismatch。
- `Guest cycle spent: 50001`
- `Host time spent: 369976ms`
- 折算 host 侧仿真速度：约 `135.1 cycles/s`

50k 进度点：

| model cycles | host ms | cumulative cycles/s |
| ---: | ---: | ---: |
| `10000` | `26249` | `381` |
| `20000` | `105701` | `189` |
| `30000` | `188617` | `159` |
| `40000` | `273452` | `146` |
| `50000` | `369963` | `135` |

与旧 C2 full cap128 基线对比：

| 指标 | C2 full cap128 | C2 full cap128 + activation merge |
| --- | ---: | ---: |
| `activity-schedule` | `128098ms` | `187654ms` |
| `write_grhsim_cpp` | `41058ms` | `40499ms` |
| `libgrhsim_SimTop.a` build real | `302.35s` | `303.60s` |
| 10k progress | `27089ms` | `26249ms` |
| 20k progress | `108648ms` | `105701ms` |
| 30k progress | `193188ms` | `188617ms` |
| 40k progress | `279432ms` | `273452ms` |
| 50k `Host time spent` | `378558ms` | `369976ms` |
| 50k throughput | `132.1 cycles/s` | `135.1 cycles/s` |

判断：

- runtime 有可测收益：50k 从 `378558ms` 降到 `369976ms`，减少 `8582ms`，约 `2.27%`。
- build 基本不变：model archive build 从 `302.35s` 到 `303.60s`，差异约 `0.4%`，说明 activation merge 没有明显增加 C++ 编译成本。
- 当前已测组合中，`C2 full cap128 + activation merge` 暂时成为新的 runtime 最佳点；它比 `C1+C2+C4 dynamic` 的 `386258ms` 快 `16282ms`，约 `4.22%`。
- 这次收益来自 emit 代码形态，而不是调度结构变化。后续 C4 仍需继续解释结构收益没有转化为 runtime 的原因。
