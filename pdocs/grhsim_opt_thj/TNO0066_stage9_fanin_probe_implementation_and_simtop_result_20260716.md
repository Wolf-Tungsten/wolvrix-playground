# TNO0066 Stage 9 fanin probe implementation and SimTop result

日期：2026-07-16

状态：完成 final-schedule common-source fanin pullback 的 off/probe 实现、focused correctness 与 current-default NO0300 production probe；识别 84 个 conflict-aware exact candidate、projected compute BAE `-254`，进入 strict move 阶段。

## 1. 实现边界

按 [TNO0065](./TNO0065_stage9_common_source_fanin_pullback_probe_plan_20260716.md) 新增默认关闭的：

```text
finalFaninPullbackPolicy = off/probe
finalFaninPullbackMaxNodeOps = 8
finalFaninPullbackMaxValueWidth = 64
finalFaninPullbackMinGain = 3
finalFaninPullbackMaxMoves = 4096
finalFaninPullbackMaxMovedOpPpm = 5000
```

native CLI、Python kwargs 与 XS 环境变量/配置日志均已接通。policy 首阶段只接受 `off/probe`；默认 `off` 不进入扫描，不修改 session value 或默认 stats schema。

probe 在完整 final schedule 构建后只读扫描完整 compute node。exact evaluator 覆盖：

- cheap pure kind、side effect、clone-forbidden、intent/indivisible、node size 与 value width；
- 全部 result 的 declared/input/output/inout/port anchor；
- 唯一 live-out 及反向 root cone 覆盖；
- boundary input 的 no-def、target predecessor、third source 与 source kind；
- 显式 `Value::users` 和 reg-to-mem intent 隐式 canonical index use；
- external/commit consumer、source capacity、target non-empty；
- distinct removable input value 与 exact `N - 1` gain。

projected selection 采用 gain 降序、node ops/width/ID 稳定排序，累计检查 source capacity、target 剩余 ops、move/moved-op PPM budget、node/value overlap。probe summary 输出全部原始 knob、eligible/selected/gain/moved ops、拒绝分类和分布。

## 2. Focused correctness

`transform-activity-schedule` focused build/CTest PASS，`0.03s`。覆盖：

- default、explicit off、probe 的全部 session schedule identity；
- 四输入/唯一 live-out 的 gain3 正例与重复运行 determinism；
- target 共享输入与 duplicate operand 的 distinct/removable exact 计数；
- reg-to-mem 隐式 index use；
- multi-liveout、root/non-root port/declared、commit external、capacity、no-def、target predecessor、side effect、forbidden attr、width 的具体 reject counter；
- 两候选累计 source capacity：`exact=2/selected=1/rejected_selection_capacity=1`；
- zero maxMoves/PPM selection gate；
- CLI 分离/等号语法、malformed/overflow、非法 policy/PPM；
- editable reinstall 后真实 Python import/kwargs 与负数拒绝 smoke PASS。

未单独形成稳定 fixture 的分支是 third-source、invalid read kind 与 disconnected cone；实现经人工和独立只读 review 检查为保守拒绝，记录为测试覆盖缺口。`target-empty` 在要求 live-out 被 target 剩余 op 消费的前置条件下基本不可达。

## 3. Production identity

off/probe 均从 Stage 8 由 canonical pre-reg checkpoint 生成并审计过的同一 post-reg JSON 恢复；其余配置显式锁定为仓库默认 NO0300、penalty `1000000 PPM`、ASLR off runtime 口径。

三份 stats 完全 byte-exact：

```text
canonical baseline  e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77
explicit off        e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77
probe               e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77
baseline/off cmp=0
off/probe cmp=0
```

结构保持 SN `63726`、compute/commit `63241/485`、DAG `528622`、boundary values `1000463`、total BAE `1983923`、compute/commit pairs `1721698/262225`。因此 probe 确认没有 mutation 或统计副作用。

## 4. Production probe

默认阈值下：

```text
scanned=1092530
pure=330400
common_source=10893
exact_eligible=84
selected=84
eligible_projected_bae_gain=254
projected_bae_gain=254
moved_ops=262
moved_op_limit=28125
selection rejects=0
elapsed_ms=3840
```

候选分布：

| 分桶 | eligible/selected |
| --- | --- |
| gain | `3:82, 4:2` |
| node ops | `3:82, 8:2` |
| max width | `1:84` |

projected gain 相当于 total BAE `-0.012802916%`、compute-compute pairs `-0.014752878%`；moved ops 仅占 compute-node ops `0.004657681%`。所有 84 个候选均通过累计 capacity/budget/overlap 选择，没有把互斥 eligible 简单相加。

主要漏斗 reject 为 kind `581663`、port/declared `128701`、third source `113586`、target predecessor `69034`、width `59463`；另有 capacity `2138`、external consumer `6137`、no removable input `1807`、min gain `727`。这些数据说明 strict 机会很集中，不需要放宽纯度、width 或 gain 门槛。

## 5. Strict 决策

`-254` BAE 的绝对收益温和，但候选 exact、全部 conflict-aware selected，移动量极小且理论上保持 SN/DAG/topo/active ID/commit 不变。按用户要求不以温和收益提前停止，下一阶段实现 strict：移动这 84 个完整 compute node，重建全部 final 派生数据，要求 actual compute BAE 精确 `-254` 且所有结构不变量逐项闭合；通过后继续 full emit 和 SimTop 50k。

默认继续保持 `finalFaninPullbackPolicy=off`，probe 结果本身不修改仓库生成行为。

## 6. 产物

```text
build/xs_activity_stage9_fanin_off_20260716/grhsim/grhsim_emit/activity_schedule_supernode_stats.json
build/xs_activity_stage9_fanin_probe_20260716/grhsim/grhsim_emit/activity_schedule_supernode_stats.json
build/logs/xs/xs_wolf_grhsim_build_activity_stage9_fanin_off_20260716.log
build/logs/xs/xs_wolf_grhsim_build_activity_stage9_fanin_probe_20260716.log
```
