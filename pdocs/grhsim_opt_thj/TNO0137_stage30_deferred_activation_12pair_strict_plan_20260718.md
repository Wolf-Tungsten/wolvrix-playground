# TNO0137 Stage 30 deferred-activation 12-pair strict plan（2026-07-18）

## 1. 依据与目标

Stage 29 的 50k no-mutation cofire 计数显示，固定 13 对中前 12 对满足：

```text
leader_without_follower = 0
after_pending = follower_pending = leader_fire
```

第 13 对 `35026 -> 38043` 在 50k 有 `leader_without_follower=141`，已经从 strict 候选中排除。Stage 30 只研究前 12 对，不把动态计数直接当作性能收益保证。

Stage 28 的静态重新聚合给出 12 对的待验证上界：

- exclusive shared values `648`；
- deferred/activation work `3,262 -> 1,953`，静态差值 `-1,309`；
- target operation count `1,296`；
- work-proxy lower/upper `94,886 / 9,454,706`；
- estimated activation lines `423 -> 445`，差值 `+22`。

这些数值只是 overlay 前的 accounting 输入，必须由 strict emitter 重新生成并逐项对账。

## 2. Strict overlay 契约

- 新增显式、default-off policy（建议 `deferred_activation_forward_policy=cofire-strict`）；C++ 默认仍 `off`，XS 只转发显式环境变量。
- 固定 pair 集合为 TNO0136 的 pair `0..11`，要求 source/target、active ID、batch 顺序、跨 active word、普通 compute-only、无 side effect、无 commit part 全部 exact；profile 或 schedule 改变时 fail-closed。
- 固定 candidate value 集合必须在 emit 时从当前 model 重新计算并记录，不能只依赖旧 TSV 行数；每个 value 必须是 source 的 exclusive boundary fanout，target 是唯一普通 compute consumer，且不能是 output/inout/waveform/event/direct-state/memory head。
- baseline `EmitModel` 的 graph、schedule、Kahn level、active ID、batch、value slot、materialization、state/direct-read、fullpass/commit/seed 和 session data 必须保持不变。overlay 只能影响普通 compute 的 changed-value tracking、deferred-group construction 与 source body 末尾的 activation write。
- 对每个 source，删除选定 `value -> targetActiveId` 的 baseline deferred activation，并在 baseline deferred flush 之后用现有 activation emitter 无条件置位 target；不在 fullpass、commit、initial/seed 路径写入。
- 12 对必须互不共享 source/target，且 selected value 不得重叠；若 changed-group accounting、target purity 或 overlay reconstruction 不一致，停止并返回 emit error。

## 3. 验证阶梯

1. focused emitter tests：default/off byte identity；strict invalid profile/pair/active-mask policy fail-closed；strict generated source 只在普通 compute 出现 overlay，fullpass/commit/seed 无 overlay；session keys、activity stats、slots 和 schedule manifests identity。
2. fresh production emit、source diff 和 O3/archive/link；记录所有绝对结构值、CPP/ELF SHA256 与文件大小。
3. strict instrumented or diagnostic build 先做 100/10k/50k difftest，确认 `instrCnt/cycleCnt/guest` 终点和 output signature 与 baseline 相同。插桩 walltime 不作性能结论。
4. 通过功能门禁后生成未插桩 strict candidate，并按正确 NUMA 协议做 SimTop 50k：每个 node/variant 使用独立 fresh `/dev/shm` inode，复制时用目标 CPU 的 `taskset + numactl --physcpubind/--membind` first-touch，运行用 `setarch x86_64 -R`，审计 `/proc/<pid>/numa_maps`，整 node idle/runtime gate 和平衡 AB/BA 重复均通过后才采纳。
5. 最终只用 SimTop `Host time spent` walltime 作为端到端 headline；cycles、instructions、BAE、bytes 和 static work 仅作解释。若双 NUMA 合并 walltime 不改善或输出不等价，strict 保持显式关闭。

## 4. 提交与记录

- 先提交本计划文档，再提交 strict implementation/result 的整体阶段；子模块先提交，父仓库随后更新指针。
- 所有 raw log/TSV/manifest/placement 文件记录路径、SHA256、文件大小和绝对数值；找不到的字段进入 missing ledger，不以相对百分比替代。
