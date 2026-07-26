# ST00011 commit 写槽脚手架瘦身

- 父节点：ST00009
- 状态：pruned-no-gain（2026-07-26，2k 门控 −0.64%/−0.74%，<2% 线；代码已回退）
- 代码状态：wolvrix @ `afcd5fd` + ST00002/ST00008/ST00009 本地改动 + 本节点改动（未提交）
- 创建日期：2026-07-26

## 假设

ST00005 归因：commit 阶段 38.6s/2k = 483,654 次 commit 巨块执行 × ~80 µs，每次执行对块内全部 state write 重算 event-hit 脚手架（每写 ~10 条指令：独立 `commit_event_hit_*` bool 计算 + `completedCommitWrites_` 测试）。2k profile：event 触发率 ~40%（429.8M/1.13B），但写槽按写序排列、event 槽位散乱，稀疏分组在 2k 无收益；**机械缩小每个写槽脚手架的指令数**是 2k 口径下的直接杠杆（脚手架 ≈ 每写 ~10 条 × 218,588 写槽 × 平均 ~975 次块执行）。

目标形态（每写从 3 行降到 1 行级）：

```cpp
// 现状：{ const bool hit = ((values_[X] != 0)); if (hit && !completed[slot]) { completed=true; if (cond) { body } } }
// 目标：if (!completedCommitWrites_[slot] && values_[X] != 0) { completedCommitWrites_[slot] = true; if (cond) { body } }
```

- `!completed` 短路在前：本 eval 已完成的写不再读 `values_[X]`；
- 消除独立 bool（编译器本可能优化，但文本/体积同样受益——.text 不增是硬约束）；
- 进一步：`completedCommitWrites_` 机制对"静态可证每 eval 至多执行一次"的写整组消除（保守分析，拿不准保留）。

## 改动

已实现（`wolvrix/lib/grhsim/am/cpp_emitter.cpp` 的 `emitEventfulStateWrite`，1096-1115 行）：

- 每写槽新形态：`if (!completedCommitWrites_[slot] && <eventHit>) { completedCommitWrites_[slot] = true; if (condition) { body } }`——completed 短路在前（eventHit 为纯 `values_[]` 读取、无副作用，`&&` 换序严格等价），`commit_event_hit_*` 独立 bool 与外层作用域去除（全树 437,176 → 0 处）；
- **`completedCommitWrites_` 消除分析：不成立，全部保留**——正面反证：commit 块写寄存器后经 `set_changed_result` → `activate_backward` 唤醒下游 compute，writer-frontier `ActForward(B)` 在写条件仍真时同 eval 重新置位 pending（`if (state != IDLE) state <= next_state` 是普遍形态），无 completed 跟踪会按新捕获操作数重复写入，语义改变；首 eval `activate_all_blocks()` forced 也使任何 commit 块可执行两次。实测 2k commit 块执行 483,654 次 ≈ 242/eval/block（>1），证实重入存在；
- 生成源码：1,509,963,635 → 1,491,664,427 字节（−1.21%，≈84B/写槽）；最大 commit 块（block 36972，4096 槽）逆变换归一化后与 baseline 逐字节一致（写序/槽分配/条件零漂移）；
- `ctest` 10/10。

## 测量

**2k 门控（2026-07-26，同会话交错，`setarch -R` + `taskset -c 7`，profile OFF，-C 2000）**：

| 配置 | run1 | run2 | .text |
| --- | --- | --- | --- |
| ST00009 | 139,488 | 139,369 | 334,390,470 B |
| ST00011 | 138,593 | −0.64% | 138,340 | −0.74% | 334,436,156 B（+0.01%，持平） |

功能 gate 通过（instrCnt=3 / cycleCnt=1,996 逐字一致）。

## 结论

**剪枝（pruned-no-gain）**。两组交错收益 −0.64%/−0.74%，低于 2% 线；.text 持平。代码已按 hunk 回退（保留 ST00009 局部化）。

**树级教训（与 ST00005 合并）**：commit 侧连续两个节点的机械减重（簿记链条、写槽脚手架）都只值 <1%——**commit 巨块的 ~80 µs/exec 主体是写体与条件的必要工作本身，而非脚手架开销**；且 2k boot 期 ~40% 写槽触发率下稀疏化无收益。commit 方向整体降级，不再投入机械类瘦身；剩余可能（写槽按 event 分组的稀疏调度）是 50k 稳态话题，2k 门控口径下不成立，park 到 2k 对齐之后。

## 子节点候选

- 无新候选。commit 机械瘦身方向关闭（ST00005/ST00011 双重否定）；steward 备注：若未来 50k 稳态重开，候选是"写槽按 event 分组 + 组级跳过"的稀疏调度（2k 口径无效，50k 稀疏期才可能成立）。
