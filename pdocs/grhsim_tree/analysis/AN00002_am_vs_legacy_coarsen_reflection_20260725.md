# AN00002 反省：AM 是否用了 legacy 的 coarsen 方法？（ST00002 后复盘）

- 记录日期：2026-07-25
- 关联：ST00002（粗化剪枝）、AN00001、IN-20260725-01
- 代码状态：wolvrix @ `afcd5fd`（+ ST00002 CLI 参数化本地改动）

## 1. 直接回答：没有

AM 管线在 normalize 之后**完全没有经过 legacy 的 coarsen**：

- AM 的 normalize 子进程以 `WOLVRIX_XS_GRHSIM_STOP_AFTER_PRE_SCHED=1` 调用 legacy 脚本（见 AN00001 §1），即 AM **从不运行** `activity-schedule` pass；legacy 的 coarsen 发生在该 pass 内（`wolvrix/lib/transform/activity_schedule.cpp` 的 `ComputeNodeBuilder`）。
- AM 自己的 `ProductionActivityScheduleStage`（`wolvrix/lib/grhsim/am/production_activity_schedule.cpp:1248-1315`）唯一的"合并"是 Kahn ready 队列相邻贪心合并（`enableCoarsening` 开关控制的就是它），配指令/state-writes 硬上限。没有任何多轮合并、没有 cost model、没有 tail-stop 启发式。

## 2. 纠正一个措辞：legacy 的 coarsen 不是 DP

`ComputeNodeBuilder` 是**多轮迭代贪心合并**（`activity_schedule.cpp:5557-5661`）：每轮依次尝试 out-degree-1 合并（`tryMergeNodeOut1`）、in-degree-1 合并（`tryMergeNodeIn1`）、兄弟合并（`tryMergeNodeSiblings`），受 budget（`maxOps × 32` 缩放上限）约束，带 tail-stop 启发式（大簇数下连续 3 轮收益 <1024 簇即停）。两条路线都没有 DP；DP 类划分只出现在 `reference/gsim` 的实验里，wolvrix legacy grhsim 路线未使用。

## 3. 更深的反省：移植 legacy coarsen 到 AM 不会赢

ST00002 已经实测：把块做大（512/1024）在 AM 的成本结构下回归 +15%/+23%。而 legacy 与 AM 粒度其实相近（supernode mean 178 op vs AM ~132 instr/块），执行语义也相同（激活后整块重算——legacy 生成代码同样有 `supernode_active_curr_` 位图 + flag 测试 + changed 驱动激活，见 `grhsim_cpp.cpp`）。**同粒度、同语义，legacy 166s vs AM 4,191s（25x）——差距不在划分算法，在运行时原语成本**：

| 原语 | legacy | AM |
| --- | --- | --- |
| 激活 | 内联 `grhsim_or_active_u64`（一条 OR + 常量掩码） | 跨 TU `activate_forward/backward` 函数调用（15.5B 次/50k） |
| 分派 | 固定序直接调用 + 内联 flag 测试 | 三级跨 TU switch + 边界检查（1.12B 次/50k） |
| changed 检测 | 按需、内联 | 2.17M 个物化 detector 调用点 |

## 4. 定量分解（2k 两点线性拟合，粗略但有指导意义）

用 ST00002 的 cap128/cap512 两次 2k profile 拟合 `每次 block exec 成本 = F + m × 块内指令数`：

- F ≈ 1.56 µs（per-exec 固定开销：分派 + 块边界 detector/activation 扇出）
- m ≈ 9.5 ns/指令（边际执行成本，约为 legacy 推算值 ~0.7-1 ns 的 10-20 倍）

代回 baseline 2k compute 阶段（99.8s）：固定开销 ≈ 55.4s（**55%**），线性指令成本 ≈ 44.4s（其中大量是冗余求值——activation:changed ≈ 10:1）。

结论修正（推翻 ST00002 节点里"固定开销非主导、ST00003/04 下调"的初步判断）：

1. **固定开销与冗余求值都是一阶项**。ST00002 回归不是因为固定开销小，而是冗余求值随块内指令数线性放大、恰好吃掉了固定开销的节省。
2. **ST00003（activation 位图化内联）/ ST00004（分派扁平化）恢复高优先级**：它们直接对齐 legacy 已验证的便宜原语，攻击 55% 的固定项，且不改变激活粒度（无 ST00002 的副作用）。
3. **ST00007（冗余求值消除）仍然成立**，攻击线性项；在原语变便宜之后，粗化方向（ST00002 遗留的 `--max-instructions-per-block` 参数化）可重新激活 A/B。
4. legacy 快不是因为划分聪明，而是因为"原语便宜所以敢于全块重算"。AM 应先把原语成本对齐 legacy，再谈划分策略。

## 5. 对候选池的影响（已反映到 TREE.md，2026-07-25）

- ST00003 → P1（expected_gain 恢复"高"：固定项占 compute 55%，且 activation 调用本身也计入 m）
- ST00004 → P2（分派是 F 的主要组成之一）
- ST00005 → P3（commit 占 25.7% 时间，独立于本次复盘的论据仍然成立）
- ST00007 → P4（攻击线性冗余项，实现成本中高；在原语变便宜之后重估，且届时粗化 A/B 可随 ST00002 遗留参数化重开）
- ST00002 保持 pruned-regression，遗留 `--max-instructions-per-block` 参数化工具
