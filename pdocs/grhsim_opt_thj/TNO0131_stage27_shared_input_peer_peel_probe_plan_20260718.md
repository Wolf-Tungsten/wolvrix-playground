# TNO0131 Stage 27 shared-input peer peel probe plan

记录日期：2026-07-18

状态：在 Stage26 fire profile 两档均未改善后，转向一个不放宽 108-op cap、也不改变 graph 的局部 schedule probe。首选候选是把 source supernode 中一个完整的小 compute node `C` 剥离到共同输入 fanout peer `P`；本阶段先实现 `off/probe` 和 exact opportunity 统计，不直接实现 strict mutation 或改变默认。

## 1. 当前基线和动机

当前唯一性能基线仍是 cap8192、C++ native-hybrid、NO0300、ASLR 关闭：

```text
supernodes=63,709; compute=63,241; commit=468
compute BAE=1,721,698; total BAE=1,983,326
boundary values=1,000,463; DAG=527,990
```

边界集中度提供了比 Stage26 单边 terminal move 更大的候选池：other-compute 的 multi-target value 为 `338,710` 个、产生 `1,287,900` 条边；它们只占该类 value 的 `39.568648%`，却占 other-compute BAE 的 `71.344053%`，平均 `3.802368` edge/value。compute supernode ops 的 `median/p90/p99=98/108/108`，说明不少小 node 被 108-op cap 包在已有 supernode 中，不能由整 supernode move 触及。

Stage19 fire/static join 的 `a_succ_work` 总量为 `5,310,304,400`；按 supernode 排名 top `100/1000/3162/6324` 分别占 `4.598628%/27.397733%/59.959325%/83.255365%`。因此 probe 同时记录 source/peer fire 和 `ops * (source_fire-peer_fire)` work proxy，但 fire 只用于排序和诊断，不能替代 50k `Host time spent`。

## 2. 候选定义

对每个完整 compute node `C`（owner 为 source supernode `S`）只读枚举：

1. `C` 非空、未 split/indivisible/intent/side-effect/clone-forbidden，cheap-pure allowlist，`ops(C)<=8`，width `<=64`，从 `S` 移除后 `S` 仍非空。
2. 收集 `C` 的全部显式和 implicit external inputs `I`；每个 value 都有合法 scheduled definition。
3. peer `P` 必须同时出现在每个 `v in I` 的 fanout，且 `P` 不是 `S`、commit、任一 `v` 的 owner，也不定义这些 inputs。这样 move 不会新增 input BAE，也排除 fanin pullback。
4. `C` 的每个 external result 必须有 compute consumer，consumer 不在 `S/P`，无 port/declared/hidden/commit use；结果 fanout 集合保持不变，排除 terminal pushforward。
5. 精确模拟受影响 quotient pair：删除 input support `(owner(v),S)`，把 output support `(S,U)` 换成 `(P,U)`；DAG support key 必须与 baseline 完全相同（包括删除项仍有其它 support、添加项已存在）。
6. 只接受至少一个 input value 的最后一个 `S` user 位于 `C` 的 candidate；`projected_gain` 是这些被删除的 `(value,S)` target 对数。分别统计 gain `>=1/2/4`，并报告 raw BAE、active-byte/chunk 可能收益。

该定义不合并 `S/P`，不移动 graph operation，不改变 value 数、output fanout、compute-commit 集合或 108 cap。未来 strict 才需要定义 source segment 内的 stable anchor；probe 阶段不得 mutation。

## 3. Probe 开关和日志

新增选项必须默认 off，建议命名为 `shared-input-peer-probe`（或等价的 `final_shared_input_peer_policy`），并复用 Stage26 的严格 profile parser，仅在显式 path 非空时启用 fire 过滤：

```text
profile_valid: compute 0..63240 exactly once; commit rows ignored
source_fire >= min_source_fire
peer_fire <= source_fire
```

probe 漏斗按互斥顺序记录：扫描、owner/ambiguity、split/size/source-empty、restricted/intent、kind/side-effect/clone、width/declared/port、input/no-def、无共同 fanout peer、peer 非 compute/owner overlap、output consumer overlap、capacity、无 removable source target、fanout-set mismatch、DAG-support mismatch、profile reject、exact eligible、selection conflict/budget。

每个 exact candidate 至少记录：`S/P/C` id、source/peer fire、node ops、input/output 数、raw BAE gain、added BAE（必须 0）、boundary-value/logical-byte delta、DAG delta、active-byte/chunk proxy、same/cross emitter batch、topo/storage distance，以及 `ops*(source_fire-peer_fire)`。默认和 probe 的 session/schedule/stats 必须 byte-exact。

首轮只读 probe 的停止条件：

- exact eligible 为 0，或 active-byte/chunk 有效 gain 为 0：停止，不生成 CPP；
- 只有在 exact、slot-stable、active-byte 有效且 profile `peer_fire < source_fire` 的无冲突子集仍有可观 gain 时，另开 strict 实现阶段；
- 不因 raw BAE 的上界直接放宽 cap、融合超 108-op supernode 或运行 50k。

## 4. 正确性和 runtime 边界

probe 必须维持 off identity，不能调用 graph create/replace/freeze、不能重建 schedule。未来 strict 需要复用 `rebuildFinalScheduleDerivedNoSplit` 与 terminal 的 exact validators，额外验证 stable splice、full fanout、result source、compute-commit、actual BAE、boundary/logical bytes 和 active-ID/slot 集合。

即使 strict 后 `peer_fire < source_fire`，`P` 的其它 activation、batch/function 重切分、I-cache/layout 和 NUMA page placement 仍可能抵消收益。任何 strict candidate 都必须使用正确 first-touch staging、`taskset+numactl`、whole-node gate、`setarch -R`、ABBA/BAAB 和 `Host time spent` 作为最终判据；cycles/instructions/fire 仅作诊断。

over-cap cofire fusion（当前发现单对最高 `71` 条同 fire 边、但组合约 `216` ops）暂列后续，不与本 probe 混合，必须先有 activation bitmap/cofire 证据再考虑放宽 cap。
