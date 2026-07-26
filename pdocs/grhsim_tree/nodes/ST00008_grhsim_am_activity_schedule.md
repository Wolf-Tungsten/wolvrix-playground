# ST00008 grhsim-am-activity-schedule（coarsen+dp transform）

- 父节点：ST00001
- 状态：pruned-regression（2026-07-25，2k 门控 cap512 +17.5% / cap128 +5.7%）
- 代码状态：wolvrix @ `afcd5fd` + ST00002 CLI 参数化 + 本节点本地改动（未提交）
- 创建日期：2026-07-25

## 假设

IN-20260725-03（强制任务）：AM 生成后、emit cpp 之前必须有 coarsen+dp transform，与 legacy 路线的 `activity-schedule`（`ComputeNodeBuilder` 迭代 coarsen + supernode topo + DP 分段）对齐。

ST00002 证明 naive 放大块上限会回归（activation 次数不降，块内冗余求值线性放大）。legacy DP 的目标函数不同：**最小化跨段边界值（incoming activation cost）+ 段数惩罚**，直接压低 activation 次数与 detector 密度——正是 ST00002 缺失的机制。无环性由"topo 序列上连续分段"天然保证。

## 改动

新 transform：`grhsim-am-activity-schedule`（`wolvrix/lib/grhsim/am/grhsim_am_activity_schedule.cpp` + 对应头文件），在 `ProductionActivityScheduleStage::schedule()` 的块形成点作为可选路径（`ActivityScheduleOptions::blockFormation`，默认 greedy 不变）：

1. **coarsen**（compute 类 atom DAG，4.95M 节点）：迭代合并 out-degree-1 / in-degree-1 链（沿唯一边收缩，定理保证无环）+ 同 top-level 兄弟合并（同层无路径，必无环），簇重上限 budget；
2. **topo**：簇 DAG Kahn 拓扑成线性序列；
3. **DP 分段**（移植 `wolvrix/lib/transform/activity_schedule.cpp:4719-4839` 的 `buildComputeSupernodeSegments`）：`dp[end] = min(dp[begin] + 段内消费但定义在段前的去重变量数 + segmentPenalty)`，段指令数 ≤ cap，超大 atom 单例成段；
4. commit 类 atom 不参与 coarsen/DP，沿用现有 event/guard rank 贪心成块，编号接在 compute 块之后；
5. 输出对接到既有 model 构建（`atomBlock`/`atomTopo`/块计数），后续 detector/activation 物化零改动。

CLI：`grhsim-am-lower-json --block-formation coarsen-dp [--dp-segment-penalty x] [--dp-coarsen-budget n]`，脚本与 Makefile 透传。

参数：segmentPenalty 初值 ~64（以 AN00002 分解 F≈1.56 µs vs 单边界值 detector+activation 成本估算），coarsen budget = cap/8。

## 测量

**schedule 统计（2026-07-25，XiangShan 4.95M atom，cap 512，dpSegmentPenalty=64，coarsen budget=64 自动）**：

| 指标 | greedy cap512（ST00002） | coarsen-dp | 变化 |
| --- | --- | --- | --- |
| compute blocks | 9,241 | 9,620 | +4.1% |
| detectors | 1,651,951 | 1,445,053 | **-12.5%** |
| activation 边 | 2,623,813 | 2,394,588 | **-8.7%** |
| scheduled 指令 | 8,544,079 | 8,130,283 | -4.8% |

coarsen：4,950,236 → 1,992,995 簇（317 ms）；DP 分段 9,620 段（2,053 ms）；schedule 总耗时 ~6.1s，峰值 RSS 28.0GB。compute blocks 略升符合预期（DP 目标是 activation 成本 + 段惩罚，不是块数）。XS 图偏宽、链少，out1/in1 合并收益有限（簇均 ~2.5 指令），调大 budget/penalty 是后续调优空间。

实现要点与调试记录：初版单轮内混合 out1/in1/sibling 合并会在"间接路径旁路"情形成环（沿边收缩定理要求被收缩边是唯一路径）；修复为"单轮单规则 + 轮间重建簇图 + 轮内邮票标记"，三种规则在此约束下均可严格证明无环。

coarsen-dp cap128 的 2k 门控已在下方 round 2 补齐。

**2k 门控 round 1（2026-07-25，solo，`setarch -R` + `taskset -c 7`，profile OFF，-C 2000）**：

| 配置 | 2k 时间 | vs baseline（140,573 ms） | 判定 |
| --- | --- | --- | --- |
| coarsen-dp cap512 | 165,095 ms | +17.5% | 未过门控（功能 gate 通过：instrCnt=3 / cycleCnt=1,996 一致） |

解读：静态指标（detectors -12.5% / activation -8.7%）的改善不足以抵消粒度回归——ST00002 已证明 runtime activation 次数对块数不敏感（激活由边界值变化驱动，边数 -8.7% 太少），cap512 下块内冗余求值仍主导。因此下一轮在 **cap128（与 baseline 同粒度）** 下测 coarsen-dp，隔离"块形成质量"这一个变量。

**2k 门控 round 2（coarsen-dp cap128，同口径）**：

静态（vs greedy cap128 baseline）：compute blocks 37,667（+1.9%）、detectors 1,675,451（-10.7%）、activation 边 2,973,867（-7.6%）、scheduled 指令 8.59M（-4.4%）。

| 配置 | 2k 时间 | vs baseline | 判定 |
| --- | --- | --- | --- |
| coarsen-dp cap128 | 148,567 ms | **+5.7%** | 未过门控（功能 gate 通过，数值一致） |

**归因（2k profile ON 三方对比）**：

| 指标 | baseline（greedy cap128） | codp128 | greedy cap512（ST00002） |
| --- | --- | --- | --- |
| block execs（compute） | 35.5M | **38.96M（+11%）** | 11.82M |
| activation forward | 505M | 507.9M（持平） | 482.7M |
| 每次 block exec 成本 | ~2.81 µs | ~2.75 µs（持平） | ~9.86 µs |
| compute 阶段时间 | 99.8s | 107.3s | 121.2s |

决定性事实：**静态边界边 -7.6% 没有转化为 runtime 收益，block exec 反而 +11%**。activation 次数持平而 exec 上升 = 激活去重变差（同 epoch 内多次激活同一块才去重，块被激活的时间分布更散）。结论：greedy 的 Kahn ready 相邻性恰好携带了"同时 ready ≈ 同时被激活"的共生信号，把同 epoch 会一起触发的 atom 聚到同一块；DP 的静态 cut 目标捕捉不到这个 runtime 共生性，边界值更少但触发更分散。静态 edge cut 在固定粒度下是 runtime activation 的弱代理。

## 结论

**剪枝（pruned-regression，2k 门控）**。强制 transform 已实现并合入工具链（`--block-formation coarsen-dp`，默认仍为 greedy），功能正确（两档 cap 均过 difftest），但 cap512（+17.5%）与 cap128（+5.7%）均未过 2k 门控，按策略不投入 50k。

教训（与 ST00002 合并成两条树级结论）：

1. **粒度增大必然回归**（ST00002 greedy 与 ST00008 cap512 双重确认）：runtime activation 次数不随块数下降，块内冗余求值线性放大。
2. **静态 edge cut ≠ runtime activation**：同粒度下 DP 边界优化 -7.6% 边，block exec 反而 +11%——Kahn ready 相邻性隐含 runtime 共生激活信号，静态 cut 捕捉不到。任何新的块形成目标必须直接优化"runtime 每 epoch 触发块数"，而不是静态边界。

工具价值保留：coarsen-dp 路径、`--max-instructions-per-block`、`--dp-segment-penalty`/`--dp-coarsen-budget` 全部参数化留存在工具链中，若后续出现 co-activation 感知的目标函数可直接复用该框架重开 A/B。

## 子节点候选

- **co-activation 感知的块形成**（parked）：把 DP 的 cost 从静态边界值换成"跨段 activation 触发概率"（需要 profile 反馈或静态活动率估计），在 ST00003/04 降低原语成本后重估价值。
- 本节点再次确认 per-exec 成本（~2.8 µs）在所有块形成方案下不变——原语成本（ST00003 激活位图化 / ST00004 分派扁平化）是唯一未被证伪的杠杆，优先级进一步上调。

---

## 更新 2026-07-25（coarsen 截断 bug 修复与复测）

**发现（[AN00003](../analysis/AN00003_am_coarsen_failure_root_cause_20260725.md)）**：本节点此前评估的 coarsen 被 tail-stop bug 截断在 3 轮（`clusterDelta` 恒为 0——`graph.count` 只在下一轮轮初更新）。修复后 coarsen 收敛正常（25 轮，簇 4.73M → 739k），AM atom 图链状度（66% out-1）与 legacy（79%）同量级，"AM 化后图太宽"的先验猜测不成立。

**复测（修复版 codp128，深 coarsen）**：静态指标反而变差（detectors 1,889,778，高于 greedy 的 1,875,970；activation 边 3,108,536）——深 coarsen 压缩了 DP 在每段内的放置自由度，边界切得更粗。2k 门控 **154,976 ms（+10.2%）**，比浅 coarsen 版（+5.7%）更差，功能 gate 通过。

**结论维持 pruned-regression**，三个变体（cap512 +17.5%、浅 codp128 +5.7%、深 codp128 +10.2%）全部回归且方向自洽：粒度/块形成不是 runtime 一阶杠杆。coarsen 修复与诊断计数器（rounds/per-rule merges/度数直方图，随 stats 输出）保留在工具链中。
