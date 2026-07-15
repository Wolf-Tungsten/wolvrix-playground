# TNO0065 Stage 9 common-source fanin pullback probe plan

日期：2026-07-16

状态：规划 current-default NO0300 final-schedule common-source fanin pullback 的 no-mutation probe；先量化 exact BAE 机会、容量和冲突，再决定是否实现 strict move。

## 1. Stage 8 之后的问题

[TNO0064](./TNO0064_stage8_cross_numa_runtime_and_default_decision_20260716.md) 证明全局调整 DP 固定 segment penalty 会触发 batch/native layout 重分组，并在 NUMA0/NUMA1 上方向反转；默认保持 `1000000 PPM`。下一阶段不再改变全局分段权重，而是只处理一种局部、可精确计数的 BAE 形状：

```text
source supernode S
  v0 v1 v2 v3
    \ |  | /
   [small pure cone C]   currently in target T
          |
          r
          |
   remaining ops in T
```

若 `C` 的多个输入都由同一 `S` 提供、唯一 live-out `r` 只被 `T` 的剩余逻辑消费，并且 `S` 有 slack，则把完整 compute node/cone `C` 从 `T` 拉回 `S`：`N` 个 `S -> T` 输入 value-pairs 变为一个 `r` value-pair，exact gain 为 `N - 1`。`S -> T` DAG edge 仍存在，supernode 数、topo、active ID 和 commit partition 理论上可保持不变。

## 2. Probe 接口

新增默认关闭的 activity-schedule option：

```text
ActivityScheduleOptions::finalFaninPullbackPolicy = off/probe
-final-fanin-pullback-policy
WOLVRIX_XS_GRHSIM_FINAL_FANIN_PULLBACK_POLICY

finalFaninPullbackMaxNodeOps           = 8
finalFaninPullbackMaxValueWidth        = 64
finalFaninPullbackMinGain              = 3
finalFaninPullbackMaxMoves             = 4096
finalFaninPullbackMaxMovedOpPpm        = 5000
```

对应 CLI/Python/XS 名称统一使用 `final-fanin-pullback-*` / `final_fanin_pullback_*` / `WOLVRIX_XS_GRHSIM_FINAL_FANIN_PULLBACK_*`。首阶段只接受 `off/probe`，不暴露尚未实现的 strict 行为。

默认 `off` 不进入扫描，不新增默认 stats JSON 字段。`probe` 只记录 native/XS config 与 probe summary，不修改 `supernodeToOps`、`computeNodesBySupernode` 或任何派生 schedule 数据；因此 raw activity stats 必须与 NO0300 byte-exact。

## 3. Exact 候选条件

probe 在完整 baseline final schedule 和 value-fanout 构建后扫描 compute node `C`：

- 当前 source `S`、target `T` 均为 compute supernode，`S != T`；
- 无 oversize compute-node split；当前 final topo 为 `level-id`；
- `C` 非 indivisible、无 intent group，op 数 `<= maxNodeOps`；
- `C` 内每个 op 都在既有 cheap pure allowlist，拒绝 side effect、read/state/memory、clone-forbidden attr；
- 所有逻辑 value 宽度 `<= maxValueWidth`；
- `C` 是由唯一 live-out root 反向覆盖全部 node op 的连通 cone；
- 所有有效 boundary input 的 def 都位于同一 `S`，不接受 no-def、第三 source 或 `T` 内 predecessor；
- node 外恰有一个 distinct live-out，且其全部外部 consumer 都在原 `T`；拒绝 commit、其他 compute SN、port/声明或未调度 consumer；
- `T` 移除 `C` 后非空，`S` 加入 `C` 后不超过 compute cap；
- 对每个输入 value 精确检查 `T` 的剩余显式 operand 和 reg-to-mem 隐式 index use；只有移动后真正不再被 `T` 使用的输入才计入 removable inputs；
- `exactGain = removableInputs - 1 >= minGain`。

probe 的 projected selection 按 `gain` 降序、node op 数/宽度升序、compute-node ID 升序稳定排序；跟踪 source slack、target 剩余 op、value/node overlap、`maxMoves` 和 moved-op PPM 预算。输出 scanned/pure/common-source/exact-eligible/selected、projected BAE gain、moved ops 及各类 reject 计数。selected 是 conflict-aware 上界，不把所有 eligible 简单相加。

## 4. Correctness 门禁

Focused tests 至少覆盖：

- 默认与显式 `off` schedule 全字段相同；
- `probe` 正例识别四输入/一 live-out、projected gain `3`，同时 schedule 全字段不变；
- target 其他 node 共享输入时只计算真正 removable 的输入；
- 多 live-out、外部/commit consumer、no-def/第三 source、side effect/read、intent/indivisible、超宽、source 无 slack、target 变空均拒绝；
- 多候选容量/预算冲突与重复运行 deterministic；
- CLI 两种语法、Python binding、非法 policy 与 PPM 上限检查。

production probe 使用 [TNO0062](./TNO0062_stage8_plain_dp_penalty_structure_scan_20260715.md) 的 canonical checkpoint 和 current-default NO0300 其余配置。先闭合 explicit-off/probe raw identity，再依据 selected candidate/gain 分桶决定 strict 设计。即使 projected BAE 收益温和，只要存在 exact candidate，也允许进入一次 strict 结构扫描；是否 full emit/50k 继续遵循用户要求，以明显不可行为唯一提前停止理由。

## 5. Strict 预期边界

若 probe 成立，strict 阶段移动完整 compute node，不改写 GRH、不 clone op。应用后必须重建 op owner、DAG、value fanout、state-read sets 和 topo，并精确验证：

```text
supernode count/kinds unchanged
commit supernodes byte-exact
all supernodes non-empty and within cap
compute-node partition exact
DAG byte-exact
topo byte-exact
state-read sets byte-exact
actual compute BAE gain == selected projected gain
```

DAG/topo 不变可保证 active ID 不变，但 emitter batch 仍可能因 changed-value estimated lines 改变；strict full emit 后必须另行对比 batch 和 `.text`，不能在 scheduler probe 中预设 batch identity。

## 6. 提交边界

probe 实现、focused tests 与 production 结果作为一个阶段：先提交 `wolvrix` 子模块，再提交父仓库 pointer、XS 接线、TNO/README。strict 若进入实现，单独作为下一阶段提交，不与 probe 混成一个超大 commit。
