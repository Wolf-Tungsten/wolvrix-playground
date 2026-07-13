# TNO0016 Commit, true-merge, and boundary audits

记录日期：2026-07-13

来源范围：`NO0435..NO0447`，原始记录见 [NO0435](../grhsim_opt/NO0435_current_commit_machine_source_attribution_plan_20260713.md) 至 [NO0447](../grhsim_opt/NO0447_assign_boundary_machine_source_gate_20260713.md)。

状态：commit flattened-array gap 是唯一过 1% 的主类；outer reset mux、剩余 register read 与 assign forwarding 均未达到实现门槛。

## 1. Commit machine/source attribution

42/42 sampled commit objects 保持 `.text` identity，868/868 samples 完成归因。commit 以 changed/guard 为主，但 GSim 也存在约 23.45B state-update work。

严格 crosswalk 找到 140 个 GrhSIM flattened states 对应 79 个 GSim arrays，覆盖：

```text
commit samples  143 / 16.47%
direct total          2.14%
```

这是唯一同时超过 commit 10% 与 direct 1% 的差异类，说明继续扩展 true-merge 有合理 ROI。

## 2. True-merge rejection closure

默认关闭的 full-group profile 精确复现 4,318 groups 与 `835/174/254` true/edge/intent counts。140 states/143 samples 中，124/127 已被 discovery 找到但被 matcher 拒绝。

`branch_not_in_update` 初看覆盖 78 samples/direct `1.169%`，但 shape audit 显示：

- 17 samples 的 outer guard 不是 event；
- 严格 outer reset mux 只剩 61/direct `0.914%`；
- kAnd/kOr/kMux 分别为 37/15/9。

因此不放宽 matcher，也不实现 reset-mux peeling。

## 3. Remaining register reads

920/920 `kRegisterReadPort` samples 连接后：

```text
inline                     629
fused/ambiguous            276
independent scalar slot     15 / direct 0.225%
wide independent slot        0
```

GSim 对 ROB timer 和 delayed writeback count 也直接读取状态参与 payload，停止扩展 direct-state forwarding。

## 4. Assign-boundary 勘误与结论

旧 nearest-op mapping 会把下一 supernode dispatch/prelude 和 shared tail 误归给前一 `kAssign`。scope-aware 重算后：

```text
exact body       291
shared tail       51
next preamble     53
```

唯一过门槛的 direct scalar changed-boundary 为 69 samples；扣除 GSim 同样保留的 17 个 logEndpoint values 后，上界仅 52/direct `0.779%`，不做 forwarding。

## 5. 阶段结论

commit 仍存在 array scalarization 差异，但当前可安全恢复的 reset-mux 子类不足门槛。read/assign 的表面大类在修正 ownership 后也快速收敛。后续转向对全部 compute samples 做 scope-aware residual closure，而不是继续按 operation kind 粗排热点。

## 6. 规则审计与关键数据

记录类型：latest direct commit/boundary 的候选关闭审计。单一议题边界是“剩余 commit/read/assign 差异中是否还有同一可安全机制超过 direct-total 1%”。本阶段没有实现候选，也没有 runtime A/B/A；所有数字是 fixed-period instruction profile 与 production-identical machine/source 映射。

Profile 总计 `6,675` 个 direct leaf samples，其中 commit `868`。关键筛选链如下：

| Candidate stage | Samples | Direct-total share | Decision |
| --- | ---: | ---: | --- |
| flattened array states, strict GSim crosswalk | 143 | `2.14%` | 进入 rejection 审计 |
| `branch_not_in_update` | 78 | `1.169%` | 进入 outer-reset shape 审计 |
| strict outer reset after event check | 61 | `0.914%` | 停止 |
| independent scalar read materialization | 15 | `0.225%` | 停止 |
| scalar changed-boundary after GSim subtraction | 52 | `0.779%` | 停止 |

42/42 sampled commit TUs 的 `.text` identity 通过；4,318 个 reg-to-mem groups 与 `835/174/254` true/edge/intent 结果复现。上述数据只证明各安全子类未过门槛，不能解读为 commit 没有性能差距。详见 [NO0436](../grhsim_opt/NO0436_current_commit_machine_source_attribution_gate_20260713.md)、[NO0442](../grhsim_opt/NO0442_outer_reset_mux_recovery_audit_gate_20260713.md)、[NO0444](../grhsim_opt/NO0444_remaining_register_read_machine_audit_gate_20260713.md) 与 [NO0447](../grhsim_opt/NO0447_assign_boundary_machine_source_gate_20260713.md)。
