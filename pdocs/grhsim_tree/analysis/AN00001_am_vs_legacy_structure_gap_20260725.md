# AN00001 GRHSIM-AM vs legacy 结构差距分析（树搜索首批候选依据）

- 记录日期：2026-07-25
- 关联：ST00000 baseline、IN-20260725-01/02
- 代码状态：wolvrix @ `e7d0828`

## 1. 管线流程对比

- AM 的 GRH normalize 与 legacy **完全相同**（`scripts/wolvrix_xs_grhsim_am.py` 子进程调 legacy 脚本，`WOLVRIX_XS_GRHSIM_STOP_AFTER_PRE_SCHED=1`），transform pass 列表一致（含 `simplify` ×2、`reg-to-mem` 等），**AM 没有跳过任何 GRH pass**。
- 分歧点在 post-stats 之后：legacy 走 `activity-schedule` pass（`wolvrix/lib/transform/activity_schedule.cpp`）+ `emit_grhsim_cpp`；AM 走 `grhsim-am-lower-json`：`GrhToAmLowering::lower()`（`wolvrix/lib/grhsim/am/lowering.cpp`）→ `ProductionActivityScheduleStage::schedule()`（`wolvrix/lib/grhsim/am/production_activity_schedule.cpp`）→ `GrhSimAmCppEmitter::emit()`（`wolvrix/lib/grhsim/am/cpp_emitter.cpp`）。

## 2. 调度结构差距（IN-20260725-01 的依据）

| 维度 | legacy | AM production |
| --- | --- | --- |
| 调度原子 | SCC + 多轮 coarsening（`ComputeNodeBuilder`） | 仅 SCC（4.95M singleton atom），无 supernode 粗化 |
| 装桶 | supernode mean 178 / p99 2658 / max 3456 op，再打包 sched batch（max 2048 op） | Kahn ready 队列相邻贪心合并，compute 硬上限 128 指令，commit 4096 |
| 执行单元数 | 32,034 supernode + ~256 batch | 36,963 compute Block + 497 commit Block（~132 指令/块） |
| 跨块边界值 / detector | 704,437 boundary value / 1,459,664 activation 边 | **1,875,970 detector / 3,218,269 activation target** |
| scheduled 指令膨胀 | - | 4.95M → 8.99M（1.82x） |

`wolvrix/docs/grhsim/grhsim-am-pipeline.md` §3.2 明确承认"当前 production scheduler 不使用任何 SCC 之外的 atom contraction"。

## 3. 生成代码运行时开销（按嫌疑排序）

1. **per-block 动态分派**：`execute_block` 三级跨 TU 函数调用 + switch + 边界 throw；legacy 为固定序直接调用 + 内联 8-bit flag 测试。
2. **per-activation 跨 TU 调用**：3.22M 处 `activate_forward/backward`（不可内联，含分支与 throw）；legacy 为 `word |= const mask` 一条 OR。
3. **detector 密度**：2.17M 个 `set_changed_result` 调用点，每个 = 比较 + old 回写 + dirty 标记 + act 扇出。
4. **commit 阶段全量扫描**：`execute_next_commit_group` 每 commit 阶段无条件测试全部 ~497 个 commit Block 的 pending/captured 位 + 256k capture 表。
5. **epoch 边界固定成本**：每 epoch 位图整体拷贝/清零 + dirty list 清理；AM epoch 切换比 legacy round 更频繁。

## 4. 工具缺口（已被 ST00001 补齐）

AM emitter 不支持 waveform/perf 计数（`dump_runtime_profile` 原为空 stub），运行时归因能力缺失。ST00001 已实现计数器并产出 50k 稳态 profile。

## 5. 2026-07-23/24 功能调试迭代结论

此前的 v1–v8 迭代（commit event 稀疏化、batch capture、commit guard、consume-on-event、shift 宽度修复）全部为功能 gate 调试，**已全部合入主线（squash 进 `39c2ef2`），无一以性能为目标**。性能树搜索从空候选池开始。
