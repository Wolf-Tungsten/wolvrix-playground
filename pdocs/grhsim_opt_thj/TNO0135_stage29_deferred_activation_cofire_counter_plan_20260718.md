# TNO0135 Stage 29 deferred-activation cofire counter plan（2026-07-18）

## 1. 背景与当前结论

Stage 28 的 emitter-only forward probe 在 current-default（C++ native hybrid、commit cap `8192`、ASLR 关闭）上得到：

- raw value pairs `490,406`；exact/accounted/static-positive `3,864`；selected `128`；另输出 near-selected `64`，共 `192` 行；
- emitter work units `2,417,244 -> 2,409,068`，差值 `-8,176`；estimated source lines `549,155 -> 549,385`，差值 `+230`；
- selected fire-weighted work-proxy lower/upper 为 `-71,582,689/+60,496,519`，区间跨零；
- 因此 proxy 不是 runtime cost 的保守上界，不能直接生成 strict candidate 或改变默认配置。

Stage 29 只继续检查其中 13 对 proxy-positive、互不冲突的 source -> target pair。目标是测量真实 emu 中 source 普通 compute fire 时 target 是否仍处于待执行状态，并确认 forward 是否会减少原有 deferred activation，而不是用静态 proxy 代替动态证据。

## 2. 基线与范围

- 结构和性能基线：仓库当前默认生成配置，即 NO0300、ASLR 关闭、C++ native hybrid 默认、commit cap `8192`；XS 仅使用显式 sparse override。
- 本阶段首个实现必须是 default-off、no-product-mutation probe；不改变 graph、schedule、Kahn level、active ID、batch 划分、value slot、consumer/session map 或仿真逻辑。只有显式 `cofire-probe` 生成物会增加计数器和诊断 TSV；默认/off 生成物必须保持 identity。
- 13 对固定 pair（Stage 28 r2 profile）为：

```text
51194 -> 52335
51196 -> 52337
51195 -> 52336
51197 -> 52338
51193 -> 52334
57291 -> 57901
57289 -> 57899
57290 -> 57900
57294 -> 57904
57293 -> 57903
57292 -> 57902
10635 -> 27668
35026 -> 38043
```

所有 pair 在静态审查中均满足 source active ID 小于 target active ID，且跨 active byte；仍需在运行时按实际 active-mask 状态计数。

## 3. 动态计数定义

计数只插入普通 compute variant 的 source supernode fire 点，且由 `runtime_profile_enabled_` 门控。fullpass、commit、seed/initialization 路径不计入 cofire 证据。计数器只对固定的 13 对 pair 生效；profile 无效、pair 集合/active ID 不一致、same-word 或 source/target 含 commit/side effect 时，`cofire-probe` 必须 fail-closed，不得降级成普通 runtime profile。

对每个 pair 记录以下绝对值：

- `leader_fire`：source 普通 compute fire 次数；
- `before_pending`：source body 入口、任何 source operation 执行前 target active bit 已置位的次数；
- `after_pending`：source operations 和 baseline deferred-activation flush 完成后 target active bit 已置位的次数；
- `follower_pending`：`after_pending` 的兼容同义列，便于直接对照 Stage 28 计划中的命名；
- `leader_without_follower`：上述 after 采样时 target bit 未置位的次数；这是 strict forward 可能新增 activation 的动态风险计数；
- `follower_fire`：target 普通 compute fire 次数；
- `follower_already_pending`：`before_pending` 的同义解释列，保留以便和历史 profile 字段对账；
- `baseline_flush_added`：`before_pending=false` 且 after 采样变为 true 的次数，表示 baseline deferred flush 已经提供了 activation；
- `forward_would_add`：入口前 target 未 pending 的次数，表示 source fire 时 unconditional forward 会尝试提供 activation；它不是 walltime 收益保证。

对于跨 word pair，pending 判定只能读取 `supernode_active_curr_[targetWord]`；不能把 source 当前 word 的 `activeWordFlags` 与 target word 的 mask 做 OR。若未来允许同 word pair，必须读取当前局部 `activeWordFlags` 的后续 bit，并单独处理 split-helper 的局部保存状态。Stage 29 当前 13 对均跨 word，因此实现直接拒绝 same-word，避免 bit-position 混淆。

首要判据是 `leader_without_follower == 0` 且 `follower_pending == leader_fire`；同时记录 `before_pending` 与 `baseline_flush_added` 以区分原本已有的 activation 和 source 计算产生的 activation。这些条件只说明 activation 时序成立，不说明 forward 代码一定降低 walltime；任何 strict candidate 仍须经过功能和 SimTop walltime gate。

## 4. 实验阶梯与停止条件

1. 先完成 focused emitter/unit test，验证 default/off 产物 identity、profile-only 编译、pair metadata、counter reset/dump 和非法配置 fail-closed。
2. 在同一生成物上运行 100、10k、50k 功能/计数样本，记录每个 pair 的完整绝对计数、输入输出校验和、runtime profile 文件 SHA256。
3. 若 50k 中任一 pair `leader_without_follower > 0`，该 pair 停止 strict；若全部为零，再生成独立 strict overlay candidate。strict overlay 只在普通 compute source body 末尾向后续 target 写 activation，不改原始 model 的 materialization、fullpass 或 commit seed。
4. strict candidate 必须先通过 100/10k/50k 功能门禁和 generated CPP/ELF 对账，再做未插桩 SimTop 50k。插桩版本的 walltime 仅作诊断，不作性能结论。
5. 最终端到端判据统一使用 SimTop `Host time spent` walltime；cycles/instructions/BAE/bytes 只作解释性字段。双 NUMA 必须使用 fresh inode、目标 node first-touch、`numactl --physcpubind/--membind`、`setarch x86_64 -R`，并通过整 node idle/runtime gate 后才纳入 A/B/A。

若动态证据不足、输出不等价、walltime 合并结果不改善，保持默认关闭并记录停止原因；不得仅因 BAE 或 proxy 下降而晋升默认。

## 5. 文档与提交要求

- 运行期间在后续 TNO 文档记录原始 log 路径、SHA256、文件大小、每个 pair 的绝对计数和 walltime；找不到的原始值登记到 missing ledger，不用相对百分比替代。
- 本阶段完成一个可复现的 probe/strict gate 后，先提交 `wolvrix` 子模块，再提交父仓库，提交粒度按阶段整体控制。
