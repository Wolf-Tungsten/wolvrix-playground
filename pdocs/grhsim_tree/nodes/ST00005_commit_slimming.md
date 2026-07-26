# ST00005 commit 阶段瘦身（commit event 生命周期 sticky 化）

- 父节点：ST00009
- 状态：pruned-no-gain（2026-07-26，2k 同会话约 -1.06%，未达到 2% 门槛）
- 代码状态：实验改动已从工作区回退，当前主干保持 ST00009；本页保留完整实验结果
- 创建日期：2026-07-25
- 完成日期：2026-07-26

## 假设

AN00005 因子 3：commit 阶段占 2k ~27% 时间。构成分析（2k profile + 生成代码/runtime 代码走读，见下）显示大头不是全量扫描（已 summary 制，可忽略），而是 **commit event 变量的 mark→capture→restore→clear 生命周期链条**：

- `set_commit_changed_result` 276k 站点、2k 动态 **1.29B** 次（≈ 每站点每 eval 都触发；50k 31.59B，17 倍于普通 changed）；
- 2k 中经 `clear_changed_results` 清理的变量累计 912.7M 次，其中 ~95% 是 commit event 变量（普通 changed 仅 11k/eval）；
- 链条语义：把 commit 相关 changed 事件从 compute epoch 边界保存到 commit 阶段（capture 快照 → restore 重标记 → 免于 epoch clear）。

**eval 作用域 sticky bitmap** 可在受限场景下严格等价地消除该链条：写入时同时更新块内 pulse 与 eval 内 sticky 位（不再进 dirty 列表、不参与 per-epoch clear），commit 读取方改读 sticky 位；sticky bitmap 仅在每次 `eval()` 开始时清零。

## 改动

实验分支曾实现（`wolvrix/lib/grhsim/am/cpp_emitter.cpp`，验证完成后因收益不足回退）：

- 新表示：每个 commit event 变量双轨——`values_[v]` 退化为 pulse 槽（每次写 `= event`，不再进 dirty 列表、不参与 per-epoch clear）供 compute 块内 reader；新增 `commitEventBits_[slot]` sticky 位（`event=true` 时置位，仅 eval 开始 `fill(0)` 清一次）供 commit 块 reader。
- 写入：`set_commit_changed_result` 不再调用 `mark_commit_changed_result`，改为 values_ 写 + sticky 置位；`profileCommitChangedMarks_` 计数点保持 `event==true` 原语义。
- 读取：commit 块内（eventHit guard、Act 条件）经 `valueExpr` 按 `activeBlockIsCommit` 上下文改写为 sticky 位判读 `((commitEventBits_[w] >> b) & 1)`；compute 块 reader（Act guard）仍读 values_ pulse。
- 删除：slim 全覆盖时 `capture_commit_events`/`restore_commit_events`/`clear_pending_commit_events`/`mark_commit_changed_result` 及 `dirtyCommitEventSlots_`/`pendingCommitEventSlots_`/`pendingCommitEventBits_` 成员整条不生成；eval 主循环对应调用点移除。
- 等价性门槛（eligibility sweep，逐变量）：def 在 compute 块；所有 compute 读都在 def 块内 def 之后（同次执行新鲜 pulse）；def 块内有指向 commit 块的 Act（fire ⟹ commit pending ⟹ 旧机制必然 capture，故 sticky ≡ captured）；commit 块内读取仅限状态写 event 操作数/Act 条件；无块外 reader（snapshot/capture/port/declared/Final task）。不满足的变量回退旧链条（`set_commit_changed_result_tracked` + 原 capture/restore，仅在存在回退变量时生成）。
- XiangShan 实测 276,182/276,182 全部 slim、0 回退（生成代码核对：写点 276,182 处全在 compute 块、guard 同块同执行、且均指向 commit 块）。
- 测试：实验时新增 `testSlimCommitEventRuntime`（slim 模型功能 harness：跨 eval 清零、同 eval sticky 可见、文本断言旧链条消失）；`testPhasedCommitRuntime` 的 `posedge` 因 block0 跨块读回退旧路径。实验态 `ctest -R "grhsim|am"` 10/10；回退到 ST00009 后 emitter 专项测试再次通过。
- capture operand 拷贝与扫描保持原样（实测为次要项）。

## 测量

**2k profile（机制画像；ST00001 profile baseline vs ST00009 + ST00005 v1，同 -C 2000）**：

| 指标 | ST00001 profile baseline | ST00005 v1 | 变化 |
| --- | --- | --- | --- |
| commit event marks | 1,293,738,006 | 429,777,742 | **-67%** |
| clears | 912,679,213 | 48,718,949 | **-95%** |
| commit operand capture words | 978,537,955 | 978,537,955 | 不变 |
| commit 阶段时间 | 39,871.9 ms（28.2%） | 38,614.0 ms（27.9%） | -3.2%（含 ST00009 差异，不能单独归因） |
| 总时间（profile ON） | 141,203 ms | 138,394 ms | -2.0%（含 ST00009 差异，非节点判定口径） |
| emu `.text`（父节点 ST00009 对照） | 334,390,470 B | 337,357,456 B | **+0.887%（+2,966,986 B）** |

**关键发现（v1 的真正产出）**：硬计数确认 mark 与 clear 各减少 863,960,264 次，合计至少 **1.728B** 次动态簿记；event capture/restore 链也移除，但 commit operand capture 的 978.5M words 完全未动。节点相对 ST00009 却只快约 1%，说明 mark/clear 是 L1 热数组上的便宜操作，不是 commit 主成本；sticky 位在 218,588 个 commit state-write 槽的 event-hit 表达式中引入位移/掩码，还使 `.text` 增长 0.887%，抵消了部分动态收益。

**commit 主体是巨块执行本身**：2k 有 483,654 次 commit block exec，总计 38.6s，即每次约 80 us（vs compute 块约 2.84 us；commit 块上限 4096 指令，约为 132 指令 compute 块的 31 倍）。每次 commit 块执行时，块内 state write 都要重算 `emitEventfulStateWrite` 的 event-hit 脚手架，无论对应写是否触发；276,182 个 commit event producer 调用点并不等于 state-write 槽数。

**2k 功能 gate**：rc=0，instrCnt=3 / cycleCnt=1,996 逐字一致。

**2k 性能门控（2026-07-26，profile OFF，`setarch -R` + `taskset -c 7`，-C 2000，同会话交错）**：

| 样本 | ST00009 | ST00005 v1 | 差值 |
| --- | --- | --- | --- |
| pair 1 | 139,623 ms | 138,319 ms | -0.93% |
| pair 2 | 139,478 ms | 137,974 ms | -1.08% |
| 预热后 bracket | 139,390 / 139,619 ms | 137,887 ms | -1.16%（父节点取两侧均值 139,505 ms） |

三组有效成对差值落在 **-0.93% 至 -1.16%**，代表值约 **-1.06%**。另有一次切换前 ST00009 冷样本 145,374 ms；同二进制立即复跑恢复至 139,390 ms，故按预热复跑与 bracket 口径排除该离群点。所有样本功能结果均为 `instrCnt=3 / cycleCnt=1,996`。

## 结论

**剪枝（pruned-no-gain）**。v1 功能正确且动态 mark/clear 计数显著下降，但三组同会话 2k 收益仅约 1.06%，低于 README 规定的 2% 接受线；`.text` 反而 +0.887%。按 L1 门控不运行 50k，实验代码与专用测试回退，主干头保持 ST00009。

假设只证对了一半：commit 阶段确实是约 27% 的一阶热点，但热点主体不是 event 生命周期簿记，而是巨型 commit block 内的大量 state-write/event-hit 脚手架。后续动作必须减少 commit 块实际执行的发射指令数，同时把 `.text` 不增长作为硬约束。

## 子节点候选

- **ST00011：commit write guard/dispatch 稀疏化**。按实际触发 event 选择写槽，避免每次 commit block exec 扫描并重算整块 state-write 脚手架；从 ST00009 分支，保持单边归因。
- **commit state-write 融合/分组**。把同一 event/guard 的写合并成紧凑 helper 或表驱动循环，目标同时降低 218,588 写槽的 `.text` 与每次 commit exec 工作量；需先做静态 guard 重用率画像。
- sticky 生命周期方案只有在读表达式更紧凑（例如字节槽或共享 guard）且 `.text` 不增长时才值得重开；单独继续削 mark/clear 不再列为候选。
