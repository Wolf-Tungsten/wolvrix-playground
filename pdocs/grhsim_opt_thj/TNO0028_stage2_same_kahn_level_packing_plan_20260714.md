# TNO0028 Stage 2 same-Kahn-level packing plan

记录日期：2026-07-14

状态：启动 Stage 2；在 coarsen 后、plain DP 前试验 bounded same-Kahn-level slot packing。本文只定义设计、门禁和停止条件，不预写实现或性能结果。

## 1. 动机与独立变量

Stage 1 在现有 DP partition 之后移动 cluster，已经证明 exact BAE/DAG 可下降，但可见的静态 work 收益只有约 `0.2%` `.text` 与 `1.4%` propagation entries，且正式 runtime 被外部负载阻断。Stage 2 改变 plain DP 看到的 cluster 相邻关系：只在依赖深度相同的 cluster 中，把共享 value 的 cluster 放近，让原有 DP 有机会直接形成更好的 contiguous segment。

首轮必须作为独立变量：

```text
kahn_level_pack_policy = strict / bae-budget / balanced
post_dp_refine_policy  = off
```

基线仍是当前仓库默认 NO0300、fixed-ASLR，两个新策略都为 `off`。只有 Stage 2 standalone 有明确结构或 50k 价值时，才允许额外测试与 Stage 1 的组合；不能用组合结果掩盖单项退化。

历史 [NO0085](../grhsim_opt/NO0085_xs_no0076_fresh_rerun_20260510.md) 的全局 affinity reorder 曾让 BAE 下降 `12.82%`、runtime 却回退 `18.49%`。因此本轮不恢复全局 reorder，只做小预算、同 Kahn level、保留位置槽的局部交换。

## 2. 插入点与 baseline identity

插入点固定在：

```text
compute-node coarsen
  -> current value-local topological order
  -> [Stage 2 optional same-level packing]
  -> build final cluster view/value edges
  -> unchanged plain DP
  -> Stage 1 optional post-DP refinement
  -> flatten/final schedule
```

关闭 Stage 2 时不得无条件重建、重排或 renumber cluster；default 与显式 `off` 的完整 session/stats/generated source identity 仍是第一门禁。

Kahn level 只用于候选发现，不直接替换当前 value-local topological order。完整 frontier 中属于同一 level 的两个 cluster，交换它们在当前序列中的槽仍可能跨过第三个 cluster 的依赖边；每个 swap 必须检查双方 proposed position 下的全部 pred/succ，结束后还要 full edge scan 验证整个顺序。

## 3. Bounded packing

建议公共参数：

| Option | Default | 含义 |
| --- | ---: | --- |
| `kahnLevelPackPolicy` | `off` | `off / strict / bae-budget / balanced` |
| `kahnLevelPackMaxMoves` | `4096` | 最多移动 cluster 数；swap 计两个 |
| `kahnLevelPackMaxMovedOpPpm` | `10000` | moved-op 总预算，默认 compute ops 的 `1%` |
| `kahnLevelPackMaxRegressionPpm` | `10000` | mixed policy 单项回退预算，默认 `1%` |

算法边界：

1. 先从 current coarsened view 建 baseline value edges、plain DP segments 和 exact BAE/DAG。
2. 用完整 Kahn frontier 记录每个 cluster 的 level，但保留当前 position slot。
3. 对每个 value 的 target clusters 按 `(level, position)` 排序；同 level 内只连接相邻 target 并累加 shared-value affinity，避免 high-fanout clique。
4. 每个 cluster 最多保留稳定排序后的 top-32 affinity peer；pair 用有序 packed ID 排序归并，不能依赖 hash iteration。
5. 尝试把 pair 一端换入另一端附近的同-level位置；每个 cluster 最多移动一次，双方 op 均计入预算。
6. swap 前检查双方全部 pred/succ 在 proposed position 下仍满足 topology；完成后 full scan 全部 cluster DAG edge。
7. 用候选顺序重建 view/value edges，重跑完全相同的 plain DP。
8. 要求 candidate segment 数与 baseline 相同、每段非空且不超过 108-op cap；再用 exact full recount 比较 BAE/DAG，由 policy 整体采用或整体回退。

首版遇到 oversize/split-sensitive compute node 时整项跳过，避免 pre-split exact metric 与 final split schedule 不闭合。Stage 2 不改变 graph op/value、compute node membership、commit、intent 或 emitter contract。

## 4. Tests 与 SimTop gate

focused tests 至少覆盖：

- default 与显式 `off` 完整 session identity；
- strict 小图在 segment 数不变时确定性地降低 BAE/DAG；
- `maxMovedOpPpm=0` 保持 baseline；
- 同 Kahn level 但跨中间依赖的 naive swap 被 topology guard 拒绝；
- invalid policy / ppm 超界诊断；
- 与 `postDpRefinePolicy=strict` 同时启用时 cap、DAG、intent、full recount 仍成立。

SimTop 继续复用 [TNO0022](./TNO0022_fresh_current_default_no0300_baseline1_20260714.md) 的 fresh checkpoint，先 stop-after-activity-schedule 扫描 strict；mixed policy 即使单项轻微退化也按 [TNO0021](./TNO0021_current_default_baseline_and_stage1_refinement_plan_20260714.md) 的软门槛决定是否 build/50k。

每个非明显失败候选执行 fresh emit/O3 build、fixed-ASLR 100-cycle、10k、50k difftest。正式性能仍采用同 CPU/NUMA 的 `control / candidate / control`、双 sibling idle `>=99%`、五事件 `100% scheduled`；主机不安静时允许完成功能 50k，但不能写成性能结论。

## 5. Kill criteria 与提交

满足任一条件停止当前策略：

- default-off identity、topology、segment count、cap、intent 或 exact recount 不闭合；
- 搜索或候选 DP 使 activity-schedule 超过 baseline `2x`，且无已验证 runtime 收益；
- moved-op `1%` 内没有被整候选 policy 接受的合法 swap；
- structure/code 明显恶化超过 `10%` 且没有可解释反向收益；
- quiet A/B/A 稳定回退超过裁决线。

阶段完成后先提交 Wolvrix 子模块，再由父仓提交子模块指针、XS 参数与增量文档。若策略 runtime 未证实，core 与 XS 默认必须继续为 `off`。

## 6. 增量更新：segment-count 门禁修正

首轮 SimTop strict scan 在 `420` 次 swap、`840` 个 moved clusters、`56,251` moved ops 下，将 plain DP compute segments 从 `63,241` 降到 `63,166`。初版实现按本文原计划的“segment 数必须完全相同”在 exact candidate recount 前回退，因此没有取得候选 BAE/DAG。

这个现象证明“完全相同”过严：候选仍由相同 108-op cap、相同 DP 和完整 topology 产生，减少 `75` 个 compute supernode 本身不是不变量破坏，也可能直接减少调度开销。代码与后续 gate 修正为：

- candidate segment 数**不得增加**，减少允许；
- 非空、全覆盖、108-op cap 继续逐段验证；
- candidate 使用自己的 segment count 重映射 compute-to-commit endpoint，并执行 exact BAE/DAG 与 final actual recount；
- strict/mixed policy、1% moved-op、intent/split 和 topology 门禁不变；
- 若与 Stage 1 组合，post-DP evaluator 从采用后的 view/value edges/segments 重新建立 owner 与 baseline。

独立 review 已确认 commit base、final supernode ID、Stage 1 组合和 final recount 都按实际 segment count 重建，不依赖 count 恒等。后续结构文档使用“不增加”作为正式口径；本文前述“必须相同”保留为首版计划上下文，不再作为执行门禁。

## 7. 勘误：实际插入点

§2 的流程图将 Stage 2 简写成 plain DP 之前。实际实现为：先在 post-coarsen baseline view 上运行一次 unchanged plain DP，以取得 baseline segments 和 exact metrics；可选 packing 采用后，再重建 candidate view/value edges 并运行第二次同一 plain DP。packing 的独立变量仍是“改变 candidate DP 看到的 cluster 相邻关系”，但 baseline DP 并未被跳过。

因此更精确的执行顺序是：

```text
coarsen/topological order
  -> baseline view/value edges/plain DP
  -> [optional same-level packing]
  -> candidate view/value edges/plain DP
  -> whole-candidate exact policy gate
  -> optional post-DP refinement
```
