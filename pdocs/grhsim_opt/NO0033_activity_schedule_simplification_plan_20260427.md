# NO0033 Activity-Schedule Simplification Plan

> 归档编号：`NO0033`。目录顺序见 [`README.md`](./README.md)。

这份文档用于固化一轮新的 `activity-schedule` 简化方向。目标不是继续给当前 `tail + coarsen` 叠加局部补丁，而是把 schedule 主路径收敛成更少的阶段、更清晰的 phase 语义，以及更统一的 cluster merge 模型。

本轮计划对应三个明确决策：

1. 所有 `DpicCall` 和 `SystemTask` 都不再放入 `sink supernode`。
2. 去掉当前“全覆盖 residual 图”的 `tail-supernode` 主路径，把 residual 聚合全部交给 `coarsen`。
3. 重新审视并升级 `coarsen` 规则，减少“多条局部 heuristic 反复 fixed-point”的结构成本。

## 1. 背景

当前 `activity-schedule` 主路径大致为：

1. 构造 `sink-supernode`
2. 构造 `tail-supernode`
3. 构造 seed partition
4. `coarsen`
5. `DP/refine`
6. replication / final materialize

当前行为说明可参考：

- [`../../wolvrix/docs/transform/activity-schedule.md`](../../wolvrix/docs/transform/activity-schedule.md)
- [`NO0008 Activity-Schedule Topo 延后与 Supernode-DP 重构计划`](./NO0008_activity_schedule_topo_refactor_plan_20260419.md)
- [`NO0009 Activity-Schedule Topo 重构后性能与 Supernode 结构画像`](./NO0009_activity_schedule_topo_refactor_perf_and_supernode_profile_20260419.md)

结合现有代码和最近的 XiangShan 画像，当前版本有三个明显问题：

- `sink supernode` 里混入了“本地 state write”与“外部 side effect call”两类语义不同的 op。
- `tail-supernode` 已经不是小特例，而是在主导 seed 形状；`NO0009` 里 `tail_ops / eligible_ops = 93.97%`，`residual_ops = 0`。
- 真正的大尺度压缩发生在 `coarsen`，但 `coarsen` 本身又是 `out1 / in1 / sibling / forwarder` 四条局部规则反复迭代，规则之间顺序敏感，且和最终目标之间缺少统一的 gain 度量。

因此，当前结构更像：

- 先用 `tail` 对 residual 图做一轮强启发式塑形
- 再让 `coarsen` 用另一套启发式继续重写

这不是一个从单一目标推导出来的干净设计。

## 2. 新方向

### 2.1 收窄 `sink supernode`

新的目标是让 `sink` 只表达“本地可见 state commit 边界”，不再承载“所有无返回值外部副作用”。

在这轮计划里：

- `kRegisterWritePort` 保留在 `sink`
- `kLatchWritePort` 保留在 `sink`
- `kMemoryWritePort` 保留在 `sink`
- `kSystemTask` 不再进入 `sink`
- `kDpicCall` 不再进入 `sink`

也就是说，`commit phase` 的定义收窄为：

- 只负责本地 state write

而 `SystemTask` / `DpicCall` 统一留在 non-sink / compute 路径中调度。

这样改的收益是：

- `sink` 语义更单一，直接对应“状态更新阶段”
- `commit` 与“外部 side effect”解耦
- 后续对 `sink` 做 event clustering / chunking 时，不必再混合处理 call 类 op

这一步的主要风险是：

- `SystemTask` / `DpicCall` 的外部可观察顺序会相对当前 `commit` 路径发生变化
- 尤其要核对各类 call 与 state write 的相对顺序是否仍满足现有运行语义

因此，这一改动必须带着顺序核对和回归测试一起做，不能只改分类函数。

### 2.2 去掉 `tail-supernode` 主路径

新的 seed 构造原则是：

- `sink partition` 继续保留
- `sink` 之外的 residual op 不再先构造成 `tail-supernode`
- residual 区域直接以更朴素的 seed 形式进入后续 `coarsen`

建议的新初始 partition 形态是：

- `sink`：按现有 `sink` 规则先切出 special partition
- `non-sink residual`：默认单 op seed，或最多只保留极轻量的同类 seed 预聚合

也就是说，主路径从：

- `sink -> tail -> seed -> coarsen`

收敛为：

- `sink -> seed -> coarsen`

这样做的理由很直接：

- `tail` 当前已经吃掉几乎全部 eligible op，但它本身并不提供统一的最优化目标
- 如果后面真正负责压缩的是 `coarsen`，那么 residual 图的主聚合逻辑应当集中在 `coarsen`，而不是先做一轮全覆盖 `tail` 再交给 `coarsen` 改写
- 这能减少一整段“先塑形、后重塑”的阶段成本，也让 seed 语义更直接

这一步的主要风险是：

- 如果直接删除 `tail` 而不提升 `coarsen`，seed 数量可能上升，甚至让 `coarsen` 增压
- 因此这一步不应孤立落地，而应与 `coarsen` 升级一起评估

### 2.3 把 `coarsen` 升级为主聚合器

当前 `coarsen` 的实现是四条规则反复 fixed-point：

- `out1 merge`
- `in1 merge`
- `sibling merge`
- `forwarder merge`

它们都受 `fixedBoundary`、`sinkOnly` 和 `supernodeMaxSize` 约束，但本质仍是多条局部 heuristic 的迭代。

新的目标不是立刻删光所有局部规则，而是把 `coarsen` 从“规则集合”升级成“带显式 gain 的主聚合器”。

建议把这件事拆成两层：

1. 先把现有规则做完整体检和插桩。
2. 再决定保留哪些规则作为 compatibility filter，哪些要收敛进统一 merge engine。

建议重点检查的问题：

- `out1` 和 `in1` 是否只是同一种 chain merge 的两个扫描方向
- `sibling` merge 的收益是否稳定，还是容易引入顺序敏感的大团簇
- `forwarder` merge 是否值得保留为特判，还是可以并入统一 gain 模型
- 当前 fixed-point 扫描顺序是否在无意中主导了最终 partition 形状
- `coarsen_tail_stop` 这类提前停止启发式是否只是性能止血，而不是结构上合理

建议的新 `coarsen` 目标应至少显式考虑：

- phase purity：不允许跨 `sink/non-sink`
- hard boundary：不允许跨 `fixedBoundary`
- size limit：不超过 `supernodeMaxSize`
- event compatibility：若后续需要，可把 event 相容性纳入 merge 约束
- gain：合并后对 cut、局部 fill ratio、热点局部性的净收益

实现上，优先推荐的方向是：

- 把当前 cluster DAG 上所有“可合并边/候选组”先转成候选集合
- 为每个候选计算统一的 merge gain
- 用 greedy / priority-queue 驱动合并，而不是整图多轮全扫

如果这一步做成，`coarsen` 才真正像一个主聚合器，而不是若干局部 rewrite pass 的炖锅。

本轮已经先落下第一步收敛：

- `tail-supernode` 主路径删除后，residual 区域直接以 singleton seed 进入 `coarsen`
- `forwarder merge` 开始升级为“guaranteed-change singleton merge”
- 当前已显式覆盖：
  - `kNot`
  - 非截断 `kAssign`
  - `kConcat`
  - `kReplicate(data)`
  - `kAdd` / `kSub` / `kXor` / `kXnor` 的“唯一动态前驱 + 常量其余项”情形

也就是说，这一轮的方向已经从“看到局部链就并”转成“优先合并那些一定会同步变动的节点”，后续再继续把它统一进显式 candidate/gain 框架。

## 3. 范围

本轮计划聚焦 `activity-schedule` 本体，不主动扩展到：

- replication 策略重写
- final materialize / emitter 数据结构大改
- runtime `eval` 主循环重写

但需要注意：

- `sink` 语义收窄后，`grhsim_cpp` emitter 和测试必须一起对齐
- `SystemTask` / `DpicCall` 的 phase 归属变化，可能影响 runtime 可观察顺序

## 4. 实施步骤

### Phase A：语义收敛与基线插桩

目标：

- 把当前 `sink` / `tail` / `coarsen` 的结构和收益量化清楚，作为新方案对照基线

工作项：

- 继续保留并增强当前 special-partition / coarsen 日志
- 为 `coarsen` 增加更细的 rule hit / accepted / rejected / gain 统计
- 记录：
  - seed 数
  - coarse supernode 数
  - coarsen 迭代数
  - 每条规则的命中与实际合并数
  - final supernode 尺寸分布
  - XiangShan emit/build/runtime 基线

验收点：

- 得到可和 `NO0009` 同口径对照的一组最新基线

当前基线补充（`2026-04-27`）：

- XiangShan `grhsim` coremark 50k 口径已重跑，先执行 `xs_wolf_grhsim_emu` 重建，再执行 `run_xs_wolf_grhsim_emu`
- 运行命令：
  - `make --no-print-directory run_xs_wolf_grhsim_emu RUN_ID=20260427_coarsen_syncchange_50k XS_SIM_MAX_CYCLE=50000 XS_PROGRESS_EVERY_CYCLES=5000`
- 运行日志：
  - `build/logs/xs/xs_wolf_grhsim_20260427_coarsen_syncchange_50k.log`
- 构建日志：
  - `build/logs/xs/xs_wolf_grhsim_build_20260427_coarsen_syncchange_50k.log`
- 结果：
  - 跑到 `50000` cycle 上限，无 difftest mismatch
  - `host_ms=635297`
  - `guest_cycles=50000`
  - `cycles/s = 78.703347`
  - `instrCnt=73580`
  - `IPC=1.471718`

这个 `cycles/s` 目前可作为本轮 `sink` 收窄、`tail` 删除、`coarsen` 升级之后的最新 runtime 基线；后续若继续调整 `coarsen` candidate/gain 模型，应继续用同一 50k 口径对照。

### Phase B：收窄 `sink`

目标：

- `sink` 只保留本地 state write

工作项：

- 调整 `isTailSinkOp(...)` / 相关 phase 分类逻辑
- 更新 `activity-schedule` 测试与 `grhsim_cpp` emitter 测试
- 新增覆盖：
  - `SystemTask`
  - `DpicCall`
  - call 与 state write 同周期共存
  - event guard 下的 call 调度顺序

验收点：

- 不再因为 `SystemTask` / `DpicCall` 把 supernode 归入 commit phase
- `compute/commit` supernode purity 仍成立
- 相关 emit / runtime 用例行为稳定

### Phase C：移除 `tail-supernode`

目标：

- 从主路径删除 `tailPartition`

工作项：

- 删除 `buildTailPartition(...)` 在主流程中的接入
- 让 `initial partition` 直接由 `sink partition + residual seeds` 构成
- 清理 tail 相关统计、文档和测试假设

验收点：

- 主路径不再出现 `tail_supernodes` / `tail_absorbed_ops` 这类结构性依赖
- 功能正确
- 即使 seed 数增加，后续 `coarsen + DP` 仍能稳定完成

### Phase D：升级 `coarsen`

目标：

- 让 `coarsen` 成为 residual 主聚合器

建议分两步：

1. 先保留现有四条规则，但统一到显式候选/统计框架里。
2. 再评估是否替换为 gain-driven merge engine。

工作项：

- 抽象统一的 merge candidate / compatibility / gain 接口
- 审视是否保留：
  - chain merge
  - sibling merge
  - forwarder merge
- 评估是否引入：
  - 按 edge-cut gain 的 greedy merge
  - 按局部 fill ratio 的 tie-break
  - 事件相容性约束
  - 更稳定的停止条件

验收点：

- `coarsen` 总时间下降，或至少迭代次数显著下降
- 最终 supernode 数、fill ratio、runtime 指标不回退，或回退有明确结构性解释

## 5. 文档与代码变更边界

为避免把“现状”和“计划”混写，建议采用以下口径：

- [`../../wolvrix/docs/transform/activity-schedule.md`](../../wolvrix/docs/transform/activity-schedule.md) 继续描述“当前已实现行为”
- 本文档负责描述“下一轮简化方案”
- 当 Phase B/C/D 真正落地后，再回写 `activity-schedule.md` 的当前行为说明

## 6. 风险与关注点

本轮最重要的风险不是算法本身，而是语义回归：

1. `SystemTask` / `DpicCall` 从 `sink` 移出后，外部可观察顺序可能变化。
2. 直接删掉 `tail` 可能把压力全部推给尚未升级的 `coarsen`。
3. 如果同时改 `sink`、删 `tail`、重写 `coarsen`，回归定位会很困难。

因此建议的推进顺序是：

1. 先插桩和量化
2. 再收窄 `sink`
3. 再移除 `tail`
4. 最后升级 `coarsen`

## 7. 最终建议

这轮 `activity-schedule` 简化，核心不是“再加一条更聪明的 `tail` 规则”，而是反过来做三件事：

1. 让 `sink` 回到“state commit boundary”的单一语义。
2. 让 residual 图不再经过 `tail-supernode` 这层全覆盖 special partition。
3. 让 `coarsen` 真正承担主聚合职责，并逐步收敛为可度量、可解释的统一 merge 模型。

如果后续实现按这条路线推进，那么 `activity-schedule` 的主干应当从现在的：

- `sink -> tail -> seed -> coarsen -> DP`

收敛为：

- `sink -> seed -> coarsen -> DP`

而且这里的 `coarsen` 不再是“若干局部规则的 fixed-point 炖锅”，而是 residual 主路径上唯一、明确、可度量的 cluster 合并器。
