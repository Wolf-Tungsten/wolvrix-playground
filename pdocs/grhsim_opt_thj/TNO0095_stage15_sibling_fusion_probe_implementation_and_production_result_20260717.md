# TNO0095 Stage 15 sibling fusion probe implementation and production result

记录日期：2026-07-17

状态：default-off/no-mutation probe 实现、focused/plumbing tests、独立 review 与 production scan 完成；停止，不进入 strict、CPP/O3 或 SimTop。production 从 `7,234` 个 raw exact pair 经 compute cap 后只剩 `7` 个，且七个 projected raw BAE gain 均低于默认 `4`，最终 `exact_eligible=selected=projected_bae_gain=0`。即使忽略 min-gain，七个 pair 的总收益上界也小于 `21` BAE，即 current raw BAE 的 `<0.0011%`；这是明显不足以承担 canonical active-ID/batch/layout strict 成本的候选，符合“不明显可行时才继续 50k”的提前停止边界。

## 1. 实现范围与默认层级

本轮实现 [TNO0093](./TNO0093_stage15_activation_equivalent_sibling_fusion_probe_plan_20260717.md) 收敛后的 `off/probe` 路径，不实现 graph/schedule mutation。C++ 是四项配置的唯一默认源：

```text
finalSiblingFusionPolicy        = off
finalSiblingFusionMinGain       = 4
finalSiblingFusionMaxPairs      = 256
finalSiblingFusionMaxFusedOpPpm = 5000
```

CLI、Python 与 XS 使用对应的 `final-sibling-fusion-*`、`final_sibling_fusion_*` 和 `WOLVRIX_XS_GRHSIM_FINAL_SIBLING_FUSION_*` 命名。Python/XS 未显式设置时不注入 option，XS 日志显示 `cpp-default`；只有显式环境变量才形成 sparse override。combined raw-op cap 不新增配置，直接复用 current `maxOpInComputeSupernode`，production 为 `108`。

probe 在 final `level-id` schedule 上执行，先保守拒绝 state/event/unclassified activation，再以带类别的完整 signature 建桶：

```text
(final level, schedule incoming ValueIds, graph input/inout ValueIds)
```

graph input/inout 只用于 activation equivalence，projected raw BAE gain 只计算共同 schedule incoming `Vin`。这一边界避开 native direct-state frontier 重写、memory-row reader 细化和 pure-event posedge/negedge 差异；仅有相同 predecessor、symbol 或无类别 value union 不足以进入候选。

signature bucket 内按 topo/storage distance 与 stable SN ID 做 conflict-free selection。日志导出结构 count maps；若有 selected pair，则逐行输出 lhs/rhs supernode、lhs/rhs active ID、gain、fused ops 与两种 distance，供 rtprof 和后续 packing/layout 分析。summary 含实际 `elapsed_ms`，所以只要求结构字段/count maps 和 pair 行稳定，不要求整行 byte identity。

## 2. Focused、plumbing 与 review

已完成的测试为：

| gate | 结果 | 覆盖 |
| --- | --- | --- |
| `transform-activity-schedule` focused CTest | `1/1 PASS` | default/off/probe identity、正例、signature/state/event/cap/gain/adjacent/预算/非法参数与 deterministic pair selection |
| Python option tests | `3/3 PASS` | C++ default 省略、显式值透传、类型/范围入口 |
| XS option tests | `6/6 PASS` | sparse `cpp-default`、四项独立显式 override 与不写回环境 |

独立代码 review 未发现阻塞问题，并确认：

- graph input/inout、state/direct-state、memory-row、pure-event/side-effect 和 no-def operand 均已覆盖或保守拒绝；
- `off/probe` 不修改 graph、schedule、session 或 raw summary stats；
- oversize fixture 确实触发 split 并覆盖 safe skip；
- parser/default/Python/XS plumbing 一致，C++ 保持唯一默认源。

review 记录的低风险残余是：测试未覆盖不同 op 插入顺序，也没有用 varied op sizes 对 lazy stale-edge 路径做独立参考算法对照。静态审查确认当前 greedy heap 等价，production 的 `max_signature_group_nodes=67`、`stale_pair_refreshes=0` 且最终无 selected pair，因此这些残余不阻塞本轮 no-mutation 结论。完整 build/CTest 尚未写入本文，等待主线程完成后另立增量记录。

## 3. Production 配置与 raw identity

production 使用 current native hybrid default：

```text
direct_single_writer_state_reads = cpp-default/native true
pure_event_compute_word_bypass   = cpp-default/native true
commit cap                       = 4096
all other experimental schedule policies = off
```

fresh default 与 probe 目录为：

```text
build/xs_activity_stage15_sibling_default_20260717
build/xs_activity_stage15_sibling_probe_20260717
```

三份 raw activity stats 的 SHA256 完全相同：

| 对象 | policy | stats SHA256 |
| --- | --- | --- |
| Stage 15 native default | `cpp-default -> off` | `e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77` |
| Stage 15 explicit probe | `probe` | 同上 |
| Stage 14 native hybrid baseline | default | 同上 |

Stage15 default 对 probe、probe 对 Stage14 baseline 的 raw JSON `cmp` 均为 `0`。这证明 probe 日志没有污染 schedule/session 结果，也确认本次 scan 的结构 control 就是当前 native hybrid canonical cap4096。

## 4. Production signature 漏斗

production summary 为：

| 指标 | 数量 |
| --- | ---: |
| compute supernodes | `63,241` |
| signature groups | `413` |
| nodes in signature groups | `1,640` |
| max signature-group nodes | `67` |
| empty incoming nodes | `12` |
| input activation nodes | `2,354` |
| state activation nodes | `44,851` |
| event activation nodes | `991` |
| unclassified activation nodes | `0` |
| singleton signature nodes | `15,747` |

上述 node counters 是诊断 count maps，不是互斥漏斗，不能相加后与 `63,241` 对账。特别是 state/event/input counter 用来说明 conservative rejection 的覆盖面；production exact bucket 最终只包含 state-free、event-free、unclassified-free 节点。

pair 与预算结果为：

| 指标 | 数量 |
| --- | ---: |
| raw exact pairs | `7,234` |
| rejected by combined compute cap | `7,227` |
| cap-eligible pairs | `7` |
| rejected by `minGain=4` | `7` |
| exact eligible | `0` |
| selected | `0` |
| eligible projected BAE gain | `0` |
| selected projected BAE gain | `0` |
| fused ops | `0` |
| stale pair refreshes | `0` |
| elapsed | `2,017 ms` |

`elapsed_ms` 仅作本次资源记录，不属于 deterministic identity 字段。七个 cap-eligible pair 每个 gain 都是整数且 `<4`；没有进入 eligible/selected distribution，也没有输出 selected-pair 行。

## 5. Adjacent DP 性质验证

独立于 `finalSiblingFusionMinGain` 的 final-order adjacency scan 得到：

```text
adjacent_pairs_scanned = 63,240
adjacent_cap_eligible  = 0
```

这与 TNO0093 的预期一致：safe exact-signature、cap-legal 且 topo/storage 相邻的 sibling 已被 baseline DP/coarsen 吸收，不会成为 Stage 15 的新机会。`adjacent_cap_eligible` 在 min-gain 前计算，因此这里的 `0` 不是被 `minGain=4` 过滤出来的假零。

production 同时得到 `stale_pair_refreshes=0`，说明当前最大 67-node signature group 的 lazy nearest-pair heap 没有触发 stale refresh；本轮约 `2.0s` probe 成本可控。

## 6. 收益上界与停止决定

七个 cap-eligible pair 全部低于 min gain `4`。即使为了估算而暂时忽略 policy 门槛，其合计 projected raw BAE gain 上界仍 `<21`：

```text
< 21 / 1,983,923 BAE = < 0.0011%
```

这个上界还没有扣除 pair conflict/PPM selection，也没有承担 non-adjacent fusion 所需的 canonical active-ID、batch、value-slot 和 source-layout 稳定成本。结合 [TNO0094](./TNO0094_stage14_native_hybrid_commit_cap_fresh_gate_20260717.md) 已证明 raw BAE 与完整 active lowering 并不单调，低于万分之一的 raw BAE 机会没有合理证据支持继续生成 strict candidate。

因此本阶段明确停止：

- 不实现 `strict` mutation；
- 不生成 fusion candidate CPP 或 O3 ELF；
- 不运行 100/10k/50k candidate 功能和 SimTop 性能；
- `finalSiblingFusionPolicy` 保持 C++ native `off`。

这不是因结构指标轻微退化而提前放弃，而是 production exact selection 为 `0`、放宽 min-gain 后的理论上界仍 `<0.0011%`。它属于用户允许的“明显不行”例外，继续一次高成本 runtime 不会提供可归因的实现收益。

## 7. 当前边界

Stage 15 probe 的实现、focused/plumbing tests、independent review、production raw identity 与机会量结论均已闭合。尚待的完整 build/CTest 仅用于提交前回归确认，不会重新打开 strict/CPP/SimTop；其结果应单独记录，避免把后续 full regression 追加进本文。
