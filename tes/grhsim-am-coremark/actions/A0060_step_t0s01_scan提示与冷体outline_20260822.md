# A0060 step r003/t0/s01：scan 分支提示与 system-task 冷体 outline（2026-08-22）

- action：step（t0 第 1 步，K=2）
- proposal：[r003-t0-s01](../proposals/r003-t0-s01.md)（Φ 选中 e00051）
- TES eval 计数：2 -> 4
- r003 基线：AM e00051 = 363.995s；gsim e00052 = 45.864s；起跑 7.936x

## 候选设计（假设先于实施固定）

两个候选都从 e00051 的同一代码、输入图和 10 开关表型出发；跨 run 学习只使用
restart 时已落入 insights 的 r002 证据。候选分别作用于 dispatch 扫描布局和
system-task 冷代码体，命中池与变换机制不同。

- **c1 / e00053 / scan-branch-hints**：同输入 recon 显示每轮约 93,199 个 Block
  的稀疏活动测试与约 945B 块体交错，跳过链约占 Host 22-24%。给 byte 序言和
  Block 活动测试加 `__builtin_expect(..., 0)`，让 clang 把冷块体移出
  fall-through 检查链。预期 Host 至少下降 4%；低于 2% 证伪。
- **c2 / e00054 / sys-task-body-outline**：b90656/b90657 守卫池约占 9.3% 块周期，
  7,235 个 `fwrite` 冷体在热块内形成前端流式成本。把非 final system-task body
  抽为 `noinline` 成员，热路径只留 fire 求值、实参物化与一次调用。预期 Host
  至少下降 4%；低于 2% 证伪。

## 实施

- c1 commit `2829fb7b9f8746cec7c02b2a5d2e5bcba580c52c`：将 r002 的 scan hint
  规则移植到 e00051 基座。历史补丁位于后续机制链上，四文件冲突按 scan 单机制
  解决；审计确认未带入 `sysTaskBodyOutline` 或 `wideMuxChainFuse`。同步 CLI、
  pipeline 文档和 emitter 等价性/oracle 测试。
- c2 commit `b1f2c8dcd21f17fc654c3838869efd3180acfb5b`：将 system-task body outline
  规则直接移植到 e00051 基座；同步 CLI、pipeline 文档和完整 emitter 行为测试，
  未带入 scan 或 wide-mux 机制。
- 两个候选都显式携带 manifest 冻结的 10 个基座开关，再分别追加自己的单一开关；
  评估严格串行，只走任务 evaluator。

## 量化结果

| cand | eval / commit | Host reps（ms） | 中位 | vs e00051 | vs gsim | CV | compile_s | 功能门 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| c1 scan hints | e00053 / `2829fb7` | 334690 / 334687 / 334686 | **334.687s** | **-8.05%** | 7.297x | 0.00% | 1978.0s（wolvrix 62.6 / emit 70.9 / emu 1591.8s） | 17/17 ctest；3 rep difftest 73580/49996 全过 |
| c2 task outline | e00054 / `b1f2c8d` | 247579 / 247560 / 247559 | **247.560s** | **-31.99%** | 5.398x | 0.00% | 1067.7s（wolvrix 62.5 / emit 70.9 / emu 673.6s） | 17/17 ctest；3 rep difftest 73580/49996 全过 |

两者均 `status=ok`、`noisy=false`，且在 2400s 编译预算内。`finish-step` 按分数
机械选择 **c2 / e00054**，已将 `b1f2c8d` 快移到 `tes/r003/t0/main`；t0 完成 1/8。

## 裁决与机制分析

- **状态机 winner 明确，因果量级不明确**：c2 比 c1 快 26.03%，但
  `334.687 / 247.560 = 1.352x`，正落在 r002 已直接检出的 per-process 快慢态
  `1.3-1.4x` 混杂带内。三个并行 rep 各自 CV=0 不能排除整批同态抽签；两候选
  又不在同一计时窗口。因此 c2 的 31.99% 与 c1 的 8.05% 都是合法 ledger 分数，
  但不能全部解释为本次机制收益，也不能据此可靠排序两种机制的真实效应。
- **两种方向都有独立先验证据，不是空命中**：同输入 r002 的同窗裁决曾确认
  scan hints -11.41%、sys-task outline -5.91%。本次 c1 的 -8.05% 与 scan 池
  预期一致；c2 极低绝对时间更像 outline 正收益叠加快态抽签。故可确认两项实现
  和功能门均迁移成功，不能确认 c2 机制本身比 c1 强 26.03%。
- **构建时间同样受状态混杂**：c2 emu_build 673.6s vs c1 1591.8s，与 outline
  缩小冷代码体的方向一致，但历史上构建墙钟也有约 4.4x 双态分裂；本次 2.36x
  差值只作辅助证据，不作纯机制量化。
- **变更面合规**：两项均为默认关闭、显式可定位的 emit 规则，不改变 GRH IR；
  文档、CLI 和 oracle/等价性测试随候选提交，功能门全部通过。

## 对 Φ 下一步的建议

- t0 主线的有效解为 `b1f2c8d` + 基座 10 开关 + `--sys-task-body-outline`。
  scan hints 留在未中选节点 e00053；若未来 Φ 在 t0 再选到 e00054/e00053 邻域，
  可用“outline 基座上叠加 scan hints”作为实质组合候选，检验两个前端机制是否正交，
  但不得用原样重测占席。
- c2 的 247.560s 暂只作为 ledger/机械 winner 分数。后续量级解释必须依赖同轨迹
  新机制的局部对照、静态 engagement 或新的同窗证据，不能把跨窗 -31.99% 直接
  写成 outline 的单因子收益。
- 状态机下一 action 是 t1/s01。按 `cross_trajectory=false` 纪律，t1 proposal
  不引用本 step 结果；跨轨迹比较只留给 round-summary。
