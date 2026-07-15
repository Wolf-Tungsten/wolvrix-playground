# TNO0047 Stage 5 fixed commit seed implementation

记录日期：2026-07-14

状态：Stage 5 strict candidate rebuild 已实现 verified baseline commit-partition seed；focused build/test 与 binding 重装通过，正在第三次运行 SimTop structure gate。

## 1. 修复边界

[TNO0046](./TNO0046_stage5_commit_order_diagnostic_and_fix_plan_20260714.md) 已证明首次 strict 失败只有同一 commit node 内的 vector order 漂移。修复没有把 exact validator 降为 set equality，也没有改变 default/probe/Stage 3 local-owner 路径。

`buildComputeNodeRewrite` 新增可选的 `fixedCommitPartition`，仅 Stage 5 strict 在 clone 后的 candidate rebuild 传入 baseline rewrite。fixed 路径在复用前验证：

- copied op 全部 valid、属于当前 graph 且仍分类为 Sink；
- copied sink 全集无重复、无缺失，精确覆盖 candidate topo 中全部 Sink；
- 按 copied op order 从当前 graph operands 重建每个 node 的 unique input vector，与 baseline `inputValues` exact 相同；
- candidate 仍按当前 topo/event/cap 正常构建 sink partition，其 normalized op partition 与 baseline 完全一致。

只有上述条件全部成立，才复制 baseline `commitNodes` 和 commit 统计。后续 compute root/build、cycle split、schedule 生成照常执行，最终既有 validator 仍逐 node exact 比较 commit ops 和 inputs。因此真实 sink、operand 或 grouping 改变仍会硬失败。

## 2. Focused fixture

新增同 event 的两个 tied commit sink fixture，分别运行 probe baseline 与 strict candidate。测试要求：

```text
baseline commit op partition == strict commit op partition (exact vector equality)
fixed_commit_partition_seed_adopted=true
strict clone applied=1
```

结果：focused target build PASS，`ctest -R '^transform-activity-schedule$'` 为 `1/1 PASS`（`0.06 s`），两仓 `git diff --check` PASS。独立 review 尚在进行，不在本篇提前给出结论。

## 3. Binding 与下一步

固定 seed C++ 变更后已重新执行 editable install；Python kwargs smoke 确认以下参数编译完整：

```text
-local-shared-compute-common-owner-policy strict
-local-shared-compute-common-owner-max-clones 4096
-local-shared-compute-common-owner-max-cloned-op-ppm 5000
```

第三次 SimTop strict scan 使用独立目录：

```text
build/xs_activity_stage5_common_owner_strict_fixed_20260714
```

本篇不记录尚未完成的 scan 结果；structure gate 将另建后续 TNO。

## 4. 增量更新：独立 review 与测试加固

独立 review 未发现 P0/P1，并确认 fixed seed 在复制前先独立生成 candidate partition，最终 exact commit validator 也没有移除。按 review 建议，focused fixture 进一步比较 probe/strict 的 `commit_sink_ops`、`commit_input_root_values`、`commit_event_key_runs` 和 `commit_event_keys` 四项 summary stats。

加固后的 focused target 重编 PASS，CTest `1/1 PASS`（`0.03 s`）。

保留一项防御性 P2：seed 当前保存 commit node 的 ordered op/aggregate input vectors，没有额外复制每个 sink 的 baseline operand vector。理论上，如果未来 mutation 同时重分配不同 sink 的 operands 而 aggregate vector 不变，现有 gate 不能单独证明逐 sink operand 不变；本阶段 strict eligibility 和 apply 都硬限制被改 use 的 user class 为 Compute，Sink operand 不在 mutation 集合中，因此该状态在当前路径不可达。若未来放宽 user class，必须同时扩展 per-sink snapshot 校验。
