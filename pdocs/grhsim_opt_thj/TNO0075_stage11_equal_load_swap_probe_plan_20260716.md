# TNO0075 Stage 11 equal-load swap-only probe plan

记录日期：2026-07-16

状态：规划 plain-DP 后的 equal-load、DAG-support-exact swap-only no-mutation probe；目标是在不改变 segment 数、每 segment op 数、final DAG/topo/active-ID 的条件下，量化历史 Stage 1 被普通 move 预算遮蔽的 BAE 机会。

## 1. 为什么重新检查 swap

Stage 1 post-DP refinement 的正式 SimTop 日志为：

```text
moves=4096
swaps=0
rejected_capacity=385401
```

现有实现先应用普通 move，4096 moved-cluster 预算被全部耗尽后才枚举 capacity-blocked move 的 swap 补偿。因此 `swaps=0` 只说明 swap 被执行顺序/预算饿死，不能视为 swap 机制已被性能否决。

同 checkpoint 的 Stage 1 off/strict 静态复盘显示 broad move 改变 `63,283/63,726` 个 active-ID position，最大位移 `20,701`，并使大量 batch 重新切分；历史约 `+8%` frontend 回退主要对应这个布局爆炸。Stage 11 只测能保持布局骨架的 swap 子集。

## 2. Policy 与范围

在既有 `postDpRefinePolicy` 增加独立值：

```text
swap-probe
```

`swap-probe` 复用 `postDpRefineMaxRounds/MaxMoves/MaxMovedOpPpm` 作为扫描和 conflict-free selection 预算，但不修改 `segments`、owner、DAG 或最终 schedule。默认仍为 `off`，既有 `strict/bae-budget/balanced` 语义不变。

probe 从现有 affinity/top-destination 与 capacity-blocked move seed 出发，为 `lhs: A -> B` 枚举 `rhs: B -> A`，首轮只接受：

```text
clusterOps(lhs) == clusterOps(rhs)
lhs/rhs 均 unlocked、未 split-sensitive
pair move topo-valid
pair 后 quotient DAG edge support byte-exact
exact compute BAE gain > 0
```

equal op count 使 A/B 两个 segment 的 op 数逐项不变；DAG support exact 使 final `level-id` topo/active-ID 可保持不变。`dagGain==0` 但边集合变化的候选必须拒绝。

## 3. Probe 统计

日志至少记录：

- capacity-blocked seeds、枚举 RHS 数；
- rejected locked/equal-load/topo/DAG-support/nonpositive-BAE；
- raw eligible swaps、BAE gain 与 cluster-op 分布；
- conflict-free selected swaps、moved clusters/ops 与预算 rejection；
- projected gain，以及把 selected set 应用到内部副本后的 actual BAE/DAG recount；
- combined DAG support、segment count、segment op-count validators。

selection 至少禁止 cluster 或 segment 重用；内部副本 recount 若发现交互导致 projected/actual gain 或 DAG support 不一致，只报告 invalid，不导出候选 schedule。

## 4. Focused tests

- equal-op swap 正例：single moves 因 cap blocked，pair swap BAE 正收益且 DAG support 不变；
- unequal-op、topo-invalid、DAG edge-count 同但 support 不同分别进入拒绝桶；
- conflict/预算选择确定性；
- probe 前后 schedule/session byte-exact；
- invalid policy 明确失败，既有 off/strict policies 不漂移。

## 5. Production gate

从 current-default NO0300 canonical post-stats checkpoint 跑 `swap-probe`，其它 Stage 1/2、clone、fanin、packing 开关全部关闭。probe stats JSON 必须与 explicit-off byte-exact。

机会量判定不设硬退场线，但以 Stage 10 的 `254` 为参照：如果 combined exact gain 达到约 `2,500` 或以上，优先实现 strict；若更小，也记录分布并结合 boundary-value/materialization 方向决定。进入 strict 后仍须 full emit 检查 batch membership/estimated lines，因为 equal segment op count 不保证 emit-line cost 完全相同。

## 6. 后续指标修正

Stage 10 证明 raw BAE `-254` 同时造成 boundary values/`grhsim_changed` `+74`。因此 swap probe 的首轮机会量仍用 exact BAE 便于复用 evaluator，但 strict 决策必须追加 boundary-value delta 与 activation-update-site delta；不能只按 BAE gain 排序。
