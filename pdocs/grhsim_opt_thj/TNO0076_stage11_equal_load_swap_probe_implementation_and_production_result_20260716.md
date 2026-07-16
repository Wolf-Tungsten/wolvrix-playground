# TNO0076 Stage 11 equal-load swap probe implementation and production result

日期：2026-07-16

状态：完成 plain-DP 后 equal-load swap-only no-mutation probe、focused correctness、资源上界审查与 current-default NO0300 production 扫描；完整候选漏斗的 exact eligible 为 `0`，不进入 strict/CPP/SimTop 50k。

## 1. 实现范围

按 [TNO0075](./TNO0075_stage11_equal_load_swap_probe_plan_20260716.md)，在既有 `postDpRefinePolicy` 增加默认关闭的：

```text
swap-probe
```

probe 复用 `postDpRefineMaxRounds/MaxMoves/MaxMovedOpPpm`，但不修改真实 `segments`、owner、DAG 或导出的 schedule。它从 affinity destination 中收集因目标容量或 source singleton 约束而不能直接移动的 seed，再枚举目标 segment 中的交换 cluster。单候选依次要求：

- lhs/rhs 均未锁定且不属于 split-sensitive segment；
- `clusterOps(lhs) == clusterOps(rhs)`；
- 完整 pair swap topo-valid，不使用单移动 topo 结果提前过滤；
- quotient DAG edge support key exact，不只比较 edge count；
- exact compute BAE gain 为正。

候选按 BAE gain、affinity、cluster ops 和 ID 稳定排序。selection 禁止 cluster 或 segment 重用，并检查 moved-cluster/moved-op 预算。selected set 只应用到内部 `candidateSegments` 副本，随后完整复算 compute BAE、compute-only boundary values、DAG support、segment op count/shape 与 topo；真实 schedule 直接保持原值。

## 2. 硬资源上界

终审发现首版 `32768/65536` cap 在全量收集和排序后才生效，只限制最终 vector，不能限制峰值内存。提交版改为：

```text
capacity-blocked seed: streaming deterministic top 32768
RHS pair scan: hard cap 4194304
eligible candidate: streaming deterministic top 65536
```

seed/eligible 的 ordered set 始终只保留当前 top-K；pair scan 上限与 `maxOps` 配置无关，未扫描 RHS 和被 top-K 淘汰的项计入 `rejected_scan_limit`。终审确认 comparator 方向、tie-break、替换 worst 和饱和计数正确。

## 3. Focused correctness

`transform-activity-schedule` focused build/CTest PASS，`0.03s`。覆盖：

- equal-op、capacity-blocked、BAE 正收益正例；
- off/probe/repeat 的 schedule 与 summary JSON identity；
- pair topo rejection 与 unequal-load rejection；
- DAG edge count 改变的拒绝；
- 三 segment、DAG edge `2 -> 2` 但 support key 改变的专用拒绝；
- conflict、maxMoves、moved-op PPM=0 和 maxRounds=0；
- projected/actual BAE、segment count/op/shape、DAG support 和 topo validators；
- invalid policy 明确失败。

独立只读终审未发现 correctness blocker。资源修复后的 focused CTest 与 `git diff --check` 再次通过。

## 4. Production 配置与 identity

production 从 Stage 10 corrected control 使用的同一 post-stats 恢复：

```text
input: build/xs_activity_stage8_dp_p050_20260715/grhsim/wolvrix_xs_post_stats.json
input SHA256: 165f5c58e06d0d8a483c49d80733f5a7a211bc27772dac5b1608b0c177a0b573
dp_segment_penalty_ppm=1000000
post_dp_refine_policy=swap-probe
kahn_level_pack_policy=off
final_fanin_pullback_policy=off
all clone/direct/bypass/packing experiments=off
final_topo_policy=level-id
```

目录名中的 `p050` 只是 pre-activity checkpoint 的历史 provenance；本次 activity schedule 显式使用仓库默认 `1000000 PPM`，性能口径仍为 current-default NO0300、ASLR off。

bounded 最终产物与 same-poststats explicit-off byte-exact：

```text
explicit off SHA256  e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77
swap-probe SHA256    e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77
cmp=0
```

结构保持 SN `63726`、compute/commit `63241/485`、DAG `528622`、boundary values `1000463`、total BAE `1983923`、compute/commit pairs `1721698/262225`。

## 5. Production 漏斗

首轮完整扫描和资源修复后的 bounded 复跑逐字段一致；最终结果为：

```text
capacity_blocked_seeds=1775369
retained seed top-K=32768
enumerated_rhs=3417492
rejected_equal_load=884463
swap_rejected_topo=54518
rejected_dag_support=296919
  rejected_dag_edge_count=289481
  rejected_dag_support_key=7438
rejected_nonpositive_bae=2181592
raw_eligible_swaps=0
selected_swaps=0
projected_bae_gain=0
actual_bae_gain=0
elapsed_ms=1060
```

`3,417,492` 个 RHS 全部在 `4,194,304` 硬上限内；四个主要 rejection 桶之和精确等于枚举总数。combined recount 的 segment count/op/shape、DAG support、topo、projected/actual validators 全为 `true`，compute-only boundary values 保持 `751973`。

## 6. 阶段结论

Stage 1 的 `swaps=0` 确实受到普通 move 执行顺序和预算遮蔽，但单独恢复 swap 搜索后，当前 production 图在 equal-load、pair-topo、DAG-support exact、BAE 正收益四项约束的交集中没有任何候选。这里不是“收益偏小”，而是 strict 可应用集合为空，因此不生成 candidate CPP，也不跑无候选可比较的 SimTop 50k。

`swap-probe` 保持默认关闭；Stage 11 到此停止，不实现 swap strict。后续 activity-schedule 优化应换到 boundary materialization/changed predicates 或 commit partition 等不同方向，不能通过放宽 DAG support/topo 约束来制造候选。

## 7. 产物

```text
build/xs_activity_stage11_equal_swap_probe_bounded_20260716/grhsim/grhsim_emit/activity_schedule_supernode_stats.json
build/logs/xs/xs_wolf_grhsim_build_activity_stage11_equal_swap_probe_bounded_20260716.log
```
