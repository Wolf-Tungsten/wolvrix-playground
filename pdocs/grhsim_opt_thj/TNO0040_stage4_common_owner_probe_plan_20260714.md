# TNO0040 Stage 4 common-owner probe plan

记录日期：2026-07-14

状态：启动 Stage 4；先实现 common-expression third-owner 的 no-mutation opportunity probe，拆分 Stage 3 的混合 reject，再决定是否实现双边本地化 strict true clone。

## 1. Baseline 与动机

基线为父仓 `33d8be6`、Wolvrix `3b13db9` 的 current-default NO0300/fixed-ASLR，所有可选 activity-schedule 策略默认关闭。

[TNO0037](./TNO0037_stage3_standalone_structure_scan_20260714.md) 的 conservative true clone 只应用 `108` 个，BAE 净减 `54`；[TNO0039](./TNO0039_stage3_quiet_aba_and_default_decision_20260714.md) 的有效 A/B/A 为 cycles `+0.145%`，没有可信收益。主要 reject 中 `rejected_consumer_nodes=194,009`，但该桶混合了 invalid user、consumer node 数不等于 2、source owner 无效、source owner 位于第三个 common/non-common node等多种原因，不能直接当成 common-owner 候选数。

本阶段先只统计，不 mutate graph。历史 [NO0086](../grhsim_opt/NO0086_grhsim_runtime_aware_coarsen_ordering_experiments_20260511.md) 的 ownership absorption 曾造出 DAG 环；没有双边 locality/cap 证据前，不允许直接放开 source-owner gate。

## 2. Probe option 与无 mutation 口径

计划新增：

```text
localSharedComputeCommonOwnerPolicy = off / probe
```

默认 `off`。SimTop probe 显式使用：

```text
enable_local_shared_compute=true
local_shared_compute_max_clones=0
local_shared_compute_common_owner_policy=probe
post_dp_refine_policy=off
kahn_level_pack_policy=off
```

`maxClones=0` 保证现有 conservative candidate 也不 apply；probe 只读 baseline `ActivityOpData/opClasses/ComputeRewriteBuild`，不得调用 `createOperation/createValue/replaceOperand`，不得 refreeze/rebuild。最终 graph/session/stats 应与 default baseline identity；probe 结果只写 info log，避免改变 default-off stats schema。

## 3. 分桶与 strict 资格投影

首先拆分：

- invalid/non-compute user；
- consumer node count `1 / 2 / >2`；
- source owner invalid；
- source owner 已是 consumer；
- source owner 是 third common / third non-common。

对 third common 继续检查：

- source node 是 singleton `{sourceOp}` 或 multi-op；
- source/common node 与两个 consumer node 是否 intent/indivisible；
- source result 是否是两个 consumer 的 exact boundary input；
- source 的每个 operand 对 consumer A/B 分别是 local 或既有 exact boundary；统计 `both / left-only / right-only / neither`；
- A/B 在累计增加一个 op 后分别是否满足 `maxOpInComputeNode`；统计 `both-pass / left-fail / right-fail / both-fail`；
- kind、result width、operand total bits、两个 target headroom 分布；
- exact projected result boundary pairs removed，严格候选首版按每项 2 条统计。

probe eligible 首版必须同时满足：cheap pure/single Logic result/exactly two distinct compute user 的 Stage 3 guard、third owner 为 non-intent/non-indivisible singleton common node、两个 consumer 非 intent/non-indivisible、双边 operand locality、双边 cap。

## 4. 后续 strict 算法边界

若机会量成立，后续 strict 实现应：

1. 较早 consumer 保留 original，较晚 consumer 改用 clone，排序依据为 user topo/op/operand stable key。
2. A/B 两侧都累计预留 `+1` cap；common source node 的预计删除不得抵扣容量。
3. selected source node 不得兼任其他 candidate target，直接相互依赖的 candidate 不同时选择。
4. mutation 前 snapshot；replace 前复核 operand index 仍指向 source value。
5. full refreeze/rebuild 后验证 original/clone 分别与两个 consumer local、graph op/value 增量、result users、metadata、commit/intent/cycle split/cap/topology。

改写一侧 uses 后，original 只剩另一侧 single consumer；full rebuild 才允许把 original/clone 分别自然吸收到 A/B。任何就地改 baseline owner/DAG 的实现都不接受。

## 5. Gate 与提交

focused tests 至少覆盖 default/explicit off/probe graph+schedule identity、singleton common positive count、multi-op/non-common/双边 locality/双边 cap reject、invalid policy。SimTop probe 必须复用 current-default checkpoint并确认 stats raw identity、probe timing/RSS 与详细桶计数。

如果 eligible 为零或极少，直接停止 common-owner 方向；如果达到可观量级，则在同一 activity-schedule目标下另开 strict 实现与 structure/50k 阶段。probe 阶段完成后按子模块、父仓顺序提交，不把后续 strict 结果回填覆盖本文。
