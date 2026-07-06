# NO0219 Declared Value Compute Node Boundary Plan

记录日期：2026-07-06

关联：[`NO0214`](./NO0214_cbaw_compute_node_builder_decision_20260703.md)、[`NO0218`](./NO0218_grhsim_compute_node_granularity_profile_20260706.md)、[`GrhSIM Scheduling`](../../wolvrix/docs/emit/grhsim-scheduling.md)

状态：已实现；full CBAW A/B 结果见 [`NO0220`](./NO0220_declared_value_boundary_cbaw_ab_final_perf_20260706.md)。

## 1. 背景

`NO0218` 量化了一个事实：当前 GrhSIM compute node / CBAW atom 数量约为 GSim partition Node 的 `0.5155x`，也就是 GrhSIM seed 粒度平均约 `1.94x` 更粗。最终 supernode 数和 DAG edge 已接近 GSim，但 BAE 仍高，说明仅继续减少 final supernode 数不是主线。

新的尝试方向是：在 compute node builder 建 seed compute node 时，把带 declared symbol 的 value 当成截断边界，不再从 consumer 反向跨过这个 value 吸收 producer。这样做的目的不是直接减少边，而是保留更多 RTL 语义切点，让后续 CBAW / DP / 诊断能看见这些原本被 builder 吞进同一 compute node 的 declared 中间值。

当前代码里已经有基础入口：

- `isDeclaredValue(graph, value)` 已存在，判断 `value.symbol()` 是否在 `graph.declaredSymbols()` 中。
- `compute_node_boundary_input_declared` 已在 summary JSON / log 字段中预留。

但当前 compute node builder 的主决策没有把 declared value 作为吸收截断条件；多数停止原因仍是 existing owner、shared、capacity、source spill、unsupported 等。

## 2. 目标和非目标

目标：

- 在初始 compute node 建立阶段显式保留 declared value 边界。
- 让 `compute_node_boundary_input_declared` 成为真实统计项。
- 保证 `plain`、`prob`、`cbaw` 三条 partition policy 都不会在 seed compute node 层无意跨过 declared value。
- 通过门控 A/B 测量它对 compute node 数、op 分布、DAG、BAE、runtime 的影响。

非目标：

- 不改变 GRH IR 的语义和 value 定义。
- 不强制最终 compute supernode 永远不能跨 declared value；第一阶段只把它作为 seed compute node 边界。后续 coarsen 是否合并，需要由 CBAW / DP 的成本模型决定。
- 不把“有普通 symbol 的内部临时值”都当边界。必须使用 `graph.isDeclaredSymbol(symbol)`，不能只看 `symbol.valid()`，否则 activity-schedule 自己补的内部 symbol 会造成边界爆炸。

## 3. 截断规则

在 `ComputeNodeBuilder::processOperands(...)` 处理某个 consumer op 的 operand value `v` 时增加优先规则：

```text
consumer op 读取 value v
if v 是 declared cut value:
    确保 v 的 producer 有自己的 owner compute node
    当前 consumer node 把 v 记录为 boundary input
    不把 producer op 吸收到当前 consumer node
```

`declared cut value` 定义为：

- `isDeclaredValue(graph, v)` 为 true；或
- `v` 是 source clone / canonical rewrite 后的内部 value，但 `canonicalValues[v]` 指向的原始 value 是 declared value。

不同 defining op 的处理：

| 情况 | 处理 |
| --- | --- |
| `v` 没有本 graph 内 def | 记录为 boundary input；如果 `v` 是 declared value，原因计入 `boundary_declared`，否则保持现有 `boundary_no_def`。 |
| `defClass == Source` 且 `v` 是 declared cut value | `ensureSourceOwnerNode(defOp)`，当前 node 记录 `v` 为 boundary，不再 `absorbSourceOp(...)`。 |
| `defClass == Compute` 且 `v` 是 declared cut value | `ensureComputeNodeForOp(defOp, common)`，当前 node 记录 `v` 为 boundary，不再 `absorbOp(...)`。 |
| `defClass == Sink` | 保持现有报错；compute 侧不应依赖 sink result。 |
| `defClass == Declaration/Unsupported` | 保持现有 unsupported/boundary 处理，避免把异常结构伪装成 declared cut。 |

Producer owner node 继续按现有规则处理自己的 operand。也就是说，边界只阻止从 consumer 跨过 `v` 向上吸收 producer；producer node 内部仍可在它自己的输入侧继续吸收，直到遇到另一个停止条件。

## 4. 必须维护的不变量

新增不变量：

```text
同一个 compute node 内，不允许同时包含 declared cut value 的 producer op 和 consumer op。
```

实现上需要在以下位置检查：

1. 初始 builder 完成后。
2. `prob` 路径的 `mergeComputeNodesToMffc(...)` 后。
3. cycle split / owner-boundary recompute 后。
4. materialize 前。

检查方法：

- 遍历每个 compute node 内 op 的 operand。
- 如果 operand 是 declared cut value，并且 operand 的 defining op 也属于同一个 compute node，则这是跨边界违规。

违规处理优先用 deterministic split，而不是直接失败：

- 对违规 node 按 op topo 顺序重新切分。
- 每遇到 declared cut edge，就在 consumer 前切开。
- 如果一个 op 有多个 declared cut operand，consumer 留在后段，所有 producer 留在前段或各自 owner node。
- split 后调用 `recomputeComputeNodeOwnersAndBoundaries(...)`，再重建 compute DAG。

如果 split 后仍违规，再报错，避免静默生成不符合方案语义的 schedule。

## 5. 与 `mergeComputeNodesToMffc` 的关系

这是本方案最容易漏掉的地方。`prob` 策略会在 builder 后调用 `mergeComputeNodesToMffc(...)`，把同一 MFFC rep 下的多个 compute node 再按 topo 连续分块合并。如果只修改初始递归吸收，`prob` 路径可能会把 declared boundary 重新合回一个 compute node。

修改要求：

- `mergeComputeNodesToMffc(...)` 在构造 chunk 时必须把 declared cut edge 当作 chunk hard break。
- 当准备把 node `N` 加入当前 chunk 时，检查 `N.boundaryInputs` 中是否有 declared cut value，且其 producer node 已在当前 chunk 内；如果有，就先结束当前 chunk，再开新 chunk。
- 合并后仍运行 §4 的 invariant checker，作为兜底。

`plain` 和 `cbaw` 当前不会调用这个 MFFC merge，但它们仍要通过同一 invariant checker，防止后续改动绕过边界。

## 6. 与 CBAW / final supernode 的关系

第一阶段只把 declared value 作为 seed compute node 边界，不把它提升为 final supernode 的硬边界。

原因：

- `NO0218` 显示 final DAG edge 已经接近 GSim，当前主要问题是 value-target multiplicity 和运行时激活工作，不应盲目禁止 final merge。
- 如果 declared boundary 在 CBAW 后仍被频繁合回，说明 CBAW 认为合并有收益；此时应该先看结构和 runtime 数据，而不是提前把规则写死。

但 CBAW 需要能看见这个语义：

- compute-node DAG edge 应能标记 `declared_boundary=true`。
- CBAW stats 增加 declared-boundary edge/value 计数，至少区分 initial / after coarsen / final。
- 后续可追加第二阶段：把 declared boundary 从 hard seed boundary 升级为 CBAW soft penalty 或 no-merge hint，但这不放入第一版。

## 7. 统计与诊断

复用并补实已有字段：

- `compute_node_boundary_input_declared`

建议新增字段：

- `compute_node_boundary_declared_values`：distinct declared boundary value 数。
- `compute_node_boundary_declared_edges`：producer compute node -> consumer compute node 的 declared boundary edge 数。
- `compute_node_declared_cut_violations_fixed`：invariant checker 自动拆开的违规数。
- `compute_node_declared_cut_violations_fatal`：拆分后仍违规的 fatal 数。

建议在 `activity_schedule_cbaw_stats.json` 增加：

- `declared_boundary_values_initial`
- `declared_boundary_edges_initial`
- `declared_boundary_values_after_coarsen`
- `declared_boundary_edges_after_coarsen`
- `declared_boundary_values_final`
- `declared_boundary_edges_final`

这些统计用于回答两个关键问题：

1. declared boundary 是否真的把 seed compute node 切细。
2. 这些语义边界在 CBAW / DP 后是被保留、被合并，还是造成了新的 activation multiplicity。

## 8. 实施步骤

### Step A：门控选项

新增 activity-schedule 选项：

```text
-declared-value-compute-node-boundary
```

`ActivityScheduleOptions` 增加：

```cpp
bool declaredValueComputeNodeBoundary = false;
```

XS GrhSIM wrapper 增加环境变量：

```text
WOLVRIX_XS_GRHSIM_DECLARED_VALUE_COMPUTE_NODE_BOUNDARY=1
```

默认保持关闭。只有 A/B 结构和 runtime gate 通过后，再讨论是否切默认值。

### Step B：统一 cut helper

新增 helper：

```cpp
bool isDeclaredCutValue(const Graph &graph,
                        const ValueCanonicalMap &canonicalValues,
                        ValueId value);
```

逻辑：

1. `isDeclaredValue(graph, value)` 为 true 则返回 true。
2. 查询 `canonicalValues[value]`，若存在且 canonical value 是 declared value，也返回 true。
3. 其他情况 false。

这个 helper 必须只看 declared symbol，不看普通 internal symbol。

### Step C：修改 builder 吸收规则

在 `ComputeNodeBuilder::processOperands(...)` 中，在进入 Source / Compute 吸收分支前判断 declared cut：

- Source cut：`ensureSourceOwnerNode(defOp)` + `addBoundary(nodeId, operand)` + `boundary_declared++`。
- Compute cut：`ensureComputeNodeForOp(defOp, common)` + `addBoundary(nodeId, operand)` + `boundary_declared++`。
- no-def declared：`addBoundary(...)` + `boundary_declared++`。

注意：`compute_node_boundary_inputs_total` 仍只对实际 boundary input 加一次，原因字段保持互斥，避免 summary 口径失真。

### Step D：修补后置合并与 invariant

- 给 `mergeComputeNodesToMffc(...)` 加 declared cut hard break。
- 增加 `splitDeclaredBoundaryComputeNodes(...)` 或同等 invariant fixer。
- 在 `buildComputeNodeRewrite(...)` 的 DAG/cycle loop 前后调用 invariant checker。
- 所有 split 后必须重新 `recomputeComputeNodeOwnersAndBoundaries(...)` 和 `buildComputeDag(...)`。

### Step E：测试

新增 `activity-schedule` 单测：

1. `declared wire` 中间值：开启选项后 producer/consumer 分属不同 compute node，`boundary_declared=1`。
2. 普通内部临时值：开启选项后仍可被吸收到同一 compute node。
3. source clone canonical declared：clone value 是 internal symbol，但 canonical 原 value declared 时仍截断。
4. `prob` policy MFFC merge：开启选项后 MFFC merge 不跨 declared cut。
5. 多 consumer declared value：只创建一个 producer owner node，多个 consumer node 通过 boundary 读取。

最小验证命令：

```text
cmake --build wolvrix/build --target transform-activity-schedule
ctest --test-dir wolvrix/build --output-on-failure -R activity-schedule
```

### Step F：XiangShan A/B

用 `NO0218` 的 stop-after 结构 profile 口径复跑：

```text
WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1
WOLVRIX_XS_GRHSIM_PARTITION_POLICY=cbaw
WOLVRIX_XS_GRHSIM_DECLARED_VALUE_COMPUTE_NODE_BOUNDARY=1
make xs_wolf_grhsim_emit ...
```

记录：

- `compute_nodes`
- `compute_node_ops_total`
- `ops / compute_node`
- `compute_node_boundary_input_declared`
- `initial_compute_supernode_dag_edges`
- `initial_boundary_activation_edges`
- final `dag_edges`
- final `boundary_activation_edges`
- final `compute_compute_value_pairs`
- CBAW declared-boundary initial/coarsen/final 统计

如果结构 gate 可接受，再继续 full emit / emu build / 2k smoke / CoreMark 50k。

## 9. Gate

第一阶段成功标准不是“compute_nodes 越多越好”，而是：

- declared boundary 统计显著非零，证明规则生效。
- compute node p99 / max op payload 下降，说明粗粒度尾部被切开。
- final `dag_edges`、`boundary_activation_edges`、`compute_compute_value_pairs` 不出现明显结构回退。
- 2k smoke 正确。
- 50k runtime 至少不显著慢于当前 CBAW baseline；若 runtime 变慢，需要 top declared-boundary ROI 解释变慢来自边界爆炸还是 codegen 成本。

建议硬门槛：

| 指标 | 门槛 |
| --- | --- |
| `compute_node_boundary_input_declared` | `> 0` |
| final `dag_edges` | 不超过 baseline `+3%` |
| final `boundary_activation_edges` | 不超过 baseline `+3%` |
| final `compute_compute_value_pairs` | 不超过 baseline `+3%` |
| 2k smoke | PASS |
| 50k runtime | 不超过 baseline `+5%`，除非结构数据明确支持进入第二阶段 |

## 10. 风险

1. declared symbol 过多会把 seed compute node 切得过碎，增加 compute-node DAG 和后续 partition 压力。
2. source clone 使用 internal value symbol，如果不追 canonical value，会漏掉 source 侧 declared 语义。
3. `prob` 后置 MFFC merge 会绕过初始 cut，必须同步处理。
4. final coarsen 可能把 declared boundary 再合回；这不是第一阶段 bug，但需要 stats 显示被合回的比例。
5. 更多 boundary value 可能增加 value storage / change detect / activation work，runtime 未必变好。

## 11. 预期结论形态

这次实验要回答的问题是：

```text
把 declared value 作为 compute node seed 截断边界，
是否能用可控的结构成本换回更有语义的 partition 输入？
```

如果答案是“seed 更细但 final BAE 明显变差”，则这条规则只能作为诊断或 CBAW soft hint。

如果答案是“seed p99 明显下降，final 结构不退或略好”，下一步应把 declared boundary 纳入 CBAW gain attribution，评估是否对特定 kind / width / fanout 的 declared value 提供 soft no-merge 权重。

## 12. 增量更新 2026-07-06：实现落地

已完成第一阶段实现：

- `ActivityScheduleOptions` 新增 `declaredValueComputeNodeBoundary`，pass 参数为 `-declared-value-compute-node-boundary`。
- Python binding 支持 `declared_value_compute_node_boundary=True`。
- XS GrhSIM wrapper 支持环境变量 `WOLVRIX_XS_GRHSIM_DECLARED_VALUE_COMPUTE_NODE_BOUNDARY=1`。
- compute node builder 在该开关开启时，把 declared cut value 作为 boundary：source / compute producer 会先建立 owner compute node，consumer node 不再跨 value 吸收 producer。
- source clone 通过 `canonicalValues` 追到原始 declared value，避免 clone 的 internal value symbol 丢失 declared 语义。
- `prob` 路径的 `mergeComputeNodesToMffc(...)` 增加 declared cut hard break，防止后置 MFFC 合并重新跨界。
- 增加 invariant fixer：若某个 compute node 内仍同时含 declared cut value 的 producer 和 consumer，会按 topo 在 consumer 前切开并重建 owner/boundary。
- summary JSON / log 增加 declared boundary 统计：`compute_node_boundary_declared_values`、`compute_node_boundary_declared_edges`、`compute_node_declared_cut_violations_fixed`、`compute_node_declared_cut_violations_fatal`。
- 新增单测覆盖默认关闭、显式开启、`prob` MFFC hard break、source clone canonical declared value。

已验证：

```text
cmake --build wolvrix/build --target transform-activity-schedule
ctest --test-dir wolvrix/build --output-on-failure -R activity-schedule
ctest --test-dir wolvrix/build --output-on-failure -R transform-pass-manager
```

XiangShan full emit / emu / CoreMark 50k A/B 已在 [`NO0220`](./NO0220_declared_value_boundary_cbaw_ab_final_perf_20260706.md) 完成。结论是：hard seed boundary 生效，但 CBAW final runtime 两次复测均慢于 baseline，因此不应作为当前 CBAW 默认配置；后续若继续利用 declared 语义，应改成 soft hint / attribution。
