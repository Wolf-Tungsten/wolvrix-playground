# TNO0068 Stage 10 fanin pullback strict plan

日期：2026-07-16

状态：基于 Stage 9 production probe 的 84 个 exact candidate，规划 strict final-schedule compute-node move、全派生数据重建与 SimTop 结构/runtime gate。

## 1. 输入证据

[TNO0066](./TNO0066_stage9_fanin_probe_implementation_and_simtop_result_20260716.md) 在 current-default NO0300 上得到：

```text
exact_eligible=84
selected=84
projected_bae_gain=254
moved_ops=262
gain distribution=3:82,4:2
node ops=3:82,8:2
max width=1:84
```

所有 candidate 均通过 capacity/budget/overlap selection，且 off/probe stats 与 canonical baseline byte-exact。Stage 10 不放宽 pure kind、width、min gain 或预算，只把同一 selected set 从 no-mutation 预测变成真实 schedule move。

## 2. Policy 与应用

将既有 policy 扩展为：

```text
finalFaninPullbackPolicy = off / probe / strict
```

`strict` 仍只允许 `level-id`，并要求本轮没有 oversize compute-node split。selection 必须与 probe 共用同一 evaluator/排序/预算，不复制一套可能漂移的候选逻辑。

对每个 selected candidate `C: T -> S`：

- 从 `T.supernodeToOps` 删除 `C.ops`，加入 `S`；
- 从 `T.computeNodesBySupernode` 删除 compute-node ID，加入 `S`；
- 不改 `rewrite.computeNodeOfOp`，因为完整 compute node 未拆分；
- 多 candidate 应用后，对所有 touched `S/T` 重新执行 local op topo sort；
- 拒绝任何 op/node 缺失、重复、target 变空或 source 超 cap，不做 best-effort 部分采用。

## 3. 全派生数据重建

strict 应从修改后的 `supernodeToOps` 重新构建，而不是只手工删改 254 个 value-fanout entry：

```text
opToSupernode / supernodeOfOp
dag
valueFanout
valueSourceKind / valueSourceSupernode
stateReadSupernodes
topoOrder
```

重建必须包含 reg-to-mem intent 隐式 index dependency，且复用与 baseline final materialization 相同的 unique edge/value-target 口径。首版因 strict 禁止 split，可使用明确的 no-split rebuild helper；不要引入未验证的 split owner 特例。

## 4. Exact adoption gate

应用前保存 baseline build，应用/重建后必须全部满足：

```text
supernode count unchanged
supernode kinds byte-exact
all scheduled ops appear exactly once
all compute supernodes non-empty and within cap
commit supernode ops byte-exact
compute-node partition exact, each node exactly once
dag byte-exact
topoOrder byte-exact
stateReadSupernodes byte-exact
compute-commit pairs unchanged
before compute BAE - after compute BAE == selected projected gain
```

任何不一致使 pass 失败并输出 predicted/actual/invariant diagnostic，不静默回滚为 baseline。成功日志记录 eligible/selected/applied/moved ops、projected/actual gain、before/after BAE/DAG 和 validator flags。

## 5. 测试与 SimTop

Focused tests：

- gain3 正例 strict 后 op/node owner 从 `T` 变为 `S`；
- compute BAE 精确 `-3`，SN/kinds/DAG/topo/state-read/commit 全同；
- probe 与 strict selected/projected set 一致；
- zero move/PPM budget 的 strict schedule 与 off 相同；
- 多 candidate cumulative capacity 只应用 selected candidate；
- strict + non-level-id 或实际 split 明确失败；
- 重复 strict deterministic，default/off identity 保持。

Production structure gate 从同一 post-reg checkpoint 跑 strict，目标为：

```text
compute pairs 1721698 -> 1721444
total BAE      1983923 -> 1983669
SN             63726 unchanged
DAG            528622 unchanged
commit pairs   262225 unchanged
```

若 exact recount 闭合，则继续 full emit/O3、fixed-ASLR 100/10k/50k 和正式 A/B/A。鉴于 Stage 7/8 均出现跨 socket frontend 反转，最终至少覆盖 NUMA0/NUMA1，各自报告最坏组，不用跨 node 平均值决定默认。

## 6. 提交边界

strict 实现/tests/结构 gate 先提交 `wolvrix` 子模块；父仓库随后提交 pointer、strict 文档和 README。full build/runtime 结果形成后续独立 TNO；只有跨 NUMA 最坏组无明显回退时才考虑修改 XS 默认，当前默认继续 `off`。
