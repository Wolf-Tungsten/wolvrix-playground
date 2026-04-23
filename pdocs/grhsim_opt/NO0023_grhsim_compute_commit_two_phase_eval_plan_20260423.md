# NO0023 GrhSIM Compute-Commit Two-Phase Eval Plan

## 背景

当前 `grhsim-cpp` 已经具备两层关键机制：

- `activity-schedule` 先把 `sink supernode` 从普通 supernode 中拆出来
- `eval()` 在运行时做 fixed-point 迭代，并在每轮末尾调用 `commit_state_updates()`

但当前实现里，`sink supernode` 仍然不是“直接 commit 状态”的阶段，而是：

1. 在 `sched` 中执行写端口 / side-effect op
2. 先把寄存器 / 锁存器写入记到 `state shadow`
3. 先把 memory 写入记到 `memory write shadow`
4. 本轮所有 supernode 跑完后，再由 `commit_state_updates()` 把 shadow 回写到真正的 state
5. 如果 state 变化，再激活 reader supernode，进入下一轮 fixed-point

这套模型是正确的，但有两个明显问题：

- `sink supernode` 已经在调度上单独存在，运行时却还保留一层“shadow -> commit”的中转，结构重复
- `state_shadow_*` / `memory_write_*` / `touched_*` / `commit_*_chunk_*` 这整套运行时状态和分发逻辑，本质上是在补偿“sink supernode 仍然运行在普通 compute 流水里”

本文档定义一个更直接的模型：把 `eval` 明确拆成 `compute` 与 `commit` 两阶段，`sink supernode` 只在 `commit` 阶段执行，并且不再写 shadow，而是直接更新真正的 state。

## 目标

- 去掉不必要的 `commit shadow`
- 保留当前 fixed-point 语义：一次 `eval()` 内允许 state 变化反复激活 reader，直到收敛
- 让 `sink supernode` 真正成为 `commit` 阶段，而不是“写 shadow 的普通 supernode”
- 让 activation 语义在阶段间清晰可描述、可验证、可插桩

非目标：

- 不在这轮设计里改变 `activity-schedule` 的 partition / coarsen / replication 策略
- 不在这轮设计里引入跨 graph / XMR / blackbox 的新时序语义
- 不在这轮设计里改变 `SystemTask` / `DPIC` 的外部可观察顺序，只是把它们纳入更明确的 phase 模型

## 1. sink supernode 覆盖核对

### 1.1 当前实现的 sink 判定

`activity-schedule` 当前通过 `isTailSinkOp(...)` / `isTailSinkKind(...)` 判定 sink，纳入 sink supernode 的 op 是：

- `kRegisterWritePort`
- `kLatchWritePort`
- `kMemoryWritePort`
- `kSystemTask`（仅无返回值）
- `kDpicCall`（仅无返回值）

对应代码在：

- [activity_schedule.cpp](../../wolvrix/lib/transform/activity_schedule.cpp)

### 1.2 “所有可能读写 state 的 op”需要怎样理解

如果按字面把“读写寄存器、锁存器、memory 状态的 op”全部列出来，那么 GRH 里与本地 state 相关的 op 可分为四类：

| 类别 | OperationKind | 是否应进入 sink supernode | 原因 |
| --- | --- | --- | --- |
| 状态声明 | `kRegister` / `kLatch` / `kMemory` | 否 | 它们只声明持久 state，本身不是运行时可执行 op |
| 状态读 | `kRegisterReadPort` / `kLatchReadPort` / `kMemoryReadPort` | 否 | 它们属于 compute 根节点，读取当前可见 state，并驱动组合逻辑 |
| 状态写 | `kRegisterWritePort` / `kLatchWritePort` / `kMemoryWritePort` | 是 | 它们真正修改 state，应在 commit 阶段执行 |
| 跨层次访问 | `kXMRRead` / `kXMRWrite` | 当前不在本模型内 | `activity-schedule` 已把它们归入 hier-like op，当前不参与本地 supernode 调度 |

### 1.3 结论

结论需要分两层说：

1. 如果问题是“当前 sink supernode 是否已经覆盖了所有本地 state 写入 op”，答案是：**是**。  
   对寄存器、锁存器、memory 的本地写入，当前没有遗漏，三类 write port 都已经被纳入 sink。

2. 如果问题是“当前 sink supernode 是否覆盖了所有接触本地 state 的 op（含读）”，答案是：**否，但这是正确的**。  
   `RegisterReadPort` / `LatchReadPort` / `MemoryReadPort` 不应进入 sink；它们应该保留在 non-sink / compute 阶段，作为“从当前可见 state 出发”的求值根。

因此，新的 compute/commit 模型下，建议把 sink supernode 的职责定义为：

- `commit` 阶段执行的所有本地 state 写入 op
- 以及不应与普通 compute 混排的无返回值外部 side-effect op

而不是“所有碰到 state 的 op”。

### 1.4 对 `SystemTask` / `DpicCall` 的位置判断

它们不读写本地寄存器/锁存器/memory，但它们具有外部可观察副作用，所以仍建议保留在 sink supernode：

- `无返回值 SystemTask / DpicCall`：进入 `commit`
- `有返回值 SystemTask / DpicCall`：保持在 `compute`

原因很直接：

- 无返回值版本不需要给组合逻辑提供结果值，放在 `commit` 更干净
- 有返回值版本的结果会被下游组合逻辑消费，必须仍然参与 `compute` 数据流

## 2. 新的两阶段语义

### 2.1 总体模型

对单次 `eval()`，执行模型改为：

1. 准备本次 `eval` 的输入激活
2. 执行 `compute` 阶段  
   只运行 non-sink supernode，按 topo order 传播组合变化
3. 执行 `commit` 阶段  
   只运行 sink supernode，按激活信息执行状态写入和外部副作用
4. 如果 `commit` 真的更新了任何 state，并因此激活了任何 non-sink supernode，则继续本次 `eval` 的 fixed-point 迭代
5. 直到 `commit` 不再激活任何 non-sink supernode，结束本次 `eval`

也就是说，固定点单位不再是：

- `所有 supernode`
- 然后 `commit_state_updates()`

而是：

- `compute(non-sink)`
- 然后 `commit(sink)`

### 2.2 阶段职责

#### compute 阶段

`compute` 阶段只负责：

- 求解组合逻辑
- 读取当前可见 state
- 传播 value change 导致的 downstream activation
- 生成 `commit` 阶段需要的 sink 激活

`compute` 阶段不负责：

- 修改寄存器、锁存器、memory 的持久 state
- 在本阶段执行 `sink supernode`
- 通过 shadow 延迟写入 state

#### commit 阶段

`commit` 阶段只负责：

- 执行 `sink supernode`
- 直接修改持久 state
- 当 state 的最终值真的变化时，跨过 declaration 节点，直接激活对应 reader supernode
- 执行无返回值 `SystemTask` / `DpicCall`

`commit` 阶段不负责：

- 再去激活别的 sink supernode
- 在阶段内自传播 fixed-point
- 写 `state shadow` / `memory write shadow`

### 2.3 激活来源

#### compute 激活来源

`compute` 阶段的激活来自三部分：

- 输入变化带来的初始激活
- `compute` 阶段自身求值过程中，由 value change 传播得到的激活
- 上一轮 fixed-point 的 `commit` 阶段由于 state 真变化而激活的 reader supernode

#### commit 激活来源

`commit` 阶段的激活来自两部分：

- 本轮 `compute` 阶段传播到 sink supernode 的激活
- 输入变化直接命中的 sink supernode 激活

约束：

- `commit` 阶段内部不再互相激活
- `commit` 阶段只向“下一轮 compute”反馈激活，不在本阶段内形成新的 commit 传播

这正是你提出的核心约束，文档里将其作为正式语义保留。

## 3. 运行时数据流

### 3.1 supernode 划分

运行时需要显式区分两类 supernode：

- `compute supernode`：所有 non-sink supernode
- `commit supernode`：所有 sink supernode

建议在 emit 时直接导出两套 topo 序：

- `compute_topo_order`
- `commit_topo_order`

或者在统一 `topo_order` 基础上，再附带：

- `supernode_is_sink`

两种做法都可以，但从生成代码和运行时扫描效率上看，直接拆成两套列表更直接。

这里还需要一个比“导出两套列表”更强的约束：

- `activity-schedule` 必须把 sink cluster 视为 phase hard-boundary
- 后续 coarsen / chain merge / sibling merge / forward merge 不允许跨过这条边界
- 因而最终 supernode 必须是纯 `compute` 或纯 `commit`，不允许 mixed supernode

否则 emitter 仍然需要处理“同一 supernode 先 compute、后 commit”的混合情况，compute/commit 两阶段就退化成运行时补救，而不是调度层面的明确契约。

### 3.2 输入激活索引

当前 emitter 已经构建了“输入变化激活哪些 supernode”的映射，但在新模型里建议拆成按 phase 分组的两个索引：

- `input_compute_head_supernodes_by_value`
- `input_commit_head_supernodes_by_value`

原因：

- 某些输入变化只需要激活 compute 根
- 某些 sink op 可能直接吃输入，不经过任何 compute supernode
- 这样可以避免先粗暴激活所有相关 supernode，再在阶段执行时判断是否属于本阶段

### 3.3 state reader 索引

当前 `activity-schedule` 已经导出：

- `state_read_supernodes`

它的语义正好可以复用，而且已经满足“跨过声明节点”的需求：

- key 是 `state symbol`
- value 是直接读取该 state 的 supernode 集合

在新模型里，`commit` 阶段一旦确认某个 state 真变化，就直接查这个表，把对应 non-sink supernode 标记为 active。

这部分不需要引入新的图结构，只需要保证：

- 这里记录的 supernode 必须都是 `compute supernode`
- 如果未来有 sink 中出现 state read，则必须单独报错或重新定义语义

## 4. 新的 eval 算法

下面给出目标形态的伪代码。

```cpp
void eval() {
    seed_compute_active_from_initial_eval_and_changed_inputs();
    seed_commit_active_from_initial_eval_and_changed_inputs();
    update_input_event_edges();

    while (compute_active_any() || commit_active_any()) {
        run_compute_phase();
        bool activated_compute = run_commit_phase();
        clear_round_local_event_edges();
        if (!activated_compute) {
            break;
        }
    }

    flush_deferred_system_task_texts_if_needed();
    refresh_outputs();
    publish_prev_inputs();
}
```

其中：

```cpp
void run_compute_phase() {
    for (supernode in compute_topo_order) {
        if (!compute_active(supernode)) continue;
        clear_compute_active(supernode);
        eval_compute_supernode(supernode);
        // value change:
        // 1. 激活后继 compute supernode
        // 2. 激活依赖这些值的 commit supernode
    }
}

bool run_commit_phase() {
    bool activated_compute = false;
    for (supernode in commit_topo_order) {
        if (!commit_active(supernode)) continue;
        clear_commit_active(supernode);
        activated_compute |= eval_commit_supernode(supernode);
    }
    return activated_compute;
}
```

而单个 `commit supernode` 的行为应是：

```cpp
bool eval_commit_supernode(supernode) {
    bool activated_compute = false;
    for (op in supernode) {
        switch (op.kind) {
        case RegisterWritePort:
        case LatchWritePort:
        case MemoryWritePort:
            if (direct_state_update_changes_visible_state(op)) {
                activate_reader_compute_supernodes(op.target_state);
                activated_compute = true;
            }
            break;
        case SystemTask:
        case DpicCall:
            execute_side_effect(op);
            break;
        }
    }
    return activated_compute;
}
```

## 5. 为何可以去掉 shadow

### 5.1 当前 shadow 的真实职责

当前 `state shadow` / `memory write shadow` 的职责不是“描述硬件状态”，而是“避免在普通 schedule 还没跑完时过早修改 state”。

换句话说，shadow 只是因为当前模型仍把 write port 放在普通 schedule 流水里，才必须存在：

- schedule 中先记录 next-state
- 全部 schedule 完成后再统一提交

一旦 write port 真正被移动到 `commit` 阶段，这层中转就不再是语义必需品。

### 5.2 新模型下的替代关系

旧模型：

- `compute + write-to-shadow`
- `commit_state_updates(shadow -> state)`

新模型：

- `compute`
- `commit(direct state update)`

语义等价点在于：

- `compute` 看见的始终是“本轮开始时可见的 state”
- `commit` 只在 `compute` 全部完成后才更新 state
- 更新后只通过 reader reactivation 进入下一轮 `compute`

因此，shadow 并不是必需语义对象，而只是旧执行模型下的实现技巧。

## 6. 关键语义约束

### 6.1 state read 必须留在 compute

`RegisterReadPort` / `LatchReadPort` / `MemoryReadPort` 必须继续属于 compute，相当于“从当前可见 state 出发的组合根节点”。

如果把 read port 也挪进 sink，会破坏两阶段模型：

- compute 就拿不到 state 根值
- commit 会同时承担“读状态 + 写状态 + 再次传播”的职责
- 阶段边界会重新变模糊

### 6.2 commit 阶段不自激活

这条约束非常关键，必须写死：

- `commit` 可以激活下一轮 `compute`
- `commit` 不能激活本轮或下一轮 `commit`

原因：

- sink op 之间不应通过 state 变化形成阶段内反馈
- 这样 `commit` 仍是一个简单的“收尾提交阶段”
- fixed-point 只围绕 `compute <- commit` 这一条回边展开

### 6.3 sink supernode 仍按 topo order 执行

即使 commit 内部不互相激活，也仍建议按 topo order 执行 sink supernode，原因有三点：

- 保持与现有 supernode 全序一致，减少行为漂移
- 保持 `SystemTask` / `DpicCall` 的可观察顺序稳定
- 便于插桩和对照当前实现

### 6.4 “state changed” 必须按可见 state 判断

commit 阶段激活下一轮 compute 的条件，不是“执行了 write”，而是：

- 对目标 state 做完直接更新后
- 新 state 与更新前可见 state 确实不同

只有这样才能避免无效 fixed-point 轮次。

对于不同 state 类型，判断规则应分别明确：

- register / latch：最终写入值与旧值不同
- memory：最终写入行号合法，且更新后的 row 内容与旧 row 不同
- masked write：比较 merge 后结果，不是比较原始写数据

### 6.5 event edge 仍按 fixed-point round 清零

当前实现会在每轮 fixed-point 末尾清理 event edge。新模型建议保留同样规则：

- 输入 event edge 在进入本次 `eval()` 时更新
- 一轮 `compute + commit` 结束后清零 round-local event edge
- 下一轮 fixed-point 若由 state 更新触发，则重新只依赖当前轮允许看到的 event 语义

这部分不应和 shadow 删除绑在一起改语义。

## 7. 对 emitter / runtime 的结构影响

### 7.1 可以删除的运行时对象

如果完全采用本文模型，以下结构应可整体删除或大幅收缩：

- `state_shadow_touched_slots_`
- `state_shadow_*_slots_`
- `memory_write_touched_slots_`
- `memory_write_addr_slots_`
- `memory_write_data_*_slots_`
- `memory_write_mask_*_slots_`
- `touched_state_shadow_indices_`
- `touched_state_shadow_flags_`
- `touched_state_shadow_count_`
- `touched_write_indices_`
- `touched_write_flags_`
- `touched_write_count_`
- `commit_state_updates()`
- `commit_state_shadow_chunk_*`
- `commit_write_chunk_*`

### 7.2 需要新增或显式化的运行时对象

建议新增或显式化：

- `compute_active_curr_`
- `commit_active_curr_`
- `compute_topo_order`
- `commit_topo_order`
- 输入到 compute / commit 的两套 head supernode 映射
- `supernode_is_sink` 或更直接的 phase 分表

### 7.3 schedule 生成形态

建议把 schedule emission 显式拆成两类函数：

- `eval_compute_batch_*`
- `eval_commit_batch_*`

或至少在 batch 元数据中记录 phase。

这样可以避免：

- 在 batch 内再判断哪些 op 属于 sink
- 继续沿用“统一 supernode bitset + 统一 dispatch”的旧结构

## 8. 对 activity-schedule 的要求

这次优化不要求重写 partition pass，但需要明确以下契约：

1. sink supernode 内只能包含：
   - state write op
   - 无返回值 `SystemTask`
   - 无返回值 `DpicCall`

2. non-sink supernode 内不能包含 state write op

3. `state_read_supernodes` 对应的 supernode 必须都是 non-sink

4. sink supernode 的 topo 顺序必须稳定可复现

5. 若未来引入新的本地 state 写 op，需要同步扩展 sink 判定，不允许悄悄落回 compute

建议在 pass 或 emit 前增加一个一致性校验：

- 遍历所有 supernode
- 检查 sink / non-sink 与 op kind 是否匹配
- 检查 `state_read_supernodes` 是否误指向 sink

## 9. 边界与风险

### 9.1 多写同一 state

如果同一轮 `commit` 中多个 sink op 写同一 state，必须继续沿用当前既有语义：

- 顺序以 topo / supernode order 为准
- 是否视为冲突、是否设置 `register_write_conflict_`，保持与当前实现一致

这部分不应该因为去掉 shadow 而改变，只是“冲突发生在直接写 state 时”，不再发生在 shadow 合并时。

### 9.2 memory 写与 reader 激活粒度

当前 `state_read_supernodes` 是按 state symbol 聚合，不区分 memory row。  
新模型默认沿用这一语义：

- 任意 row 变化，激活该 memory 的所有 reader supernode

这不是最细粒度，但和当前模型一致，且足够正确。

### 9.3 有返回值 side-effect op

带返回值的 `DpicCall` / `SystemTask` 仍应留在 compute。  
否则它们的结果值无法在同轮组合传播中被消费。

这类 op 如果同时具有副作用，仍需接受“副作用发生在 compute 阶段”的现状；这不是本轮优化要解决的问题。

### 9.4 XMR / hierarchy

`kXMRRead` / `kXMRWrite` 当前不在本地 activity-schedule 模型内。  
本文档不把它们纳入 sink coverage 范围。

如果未来要支持它们参与本地 fixed-point，需要单独定义跨 graph state 可见性和 phase 语义。

## 10. 建议的落地顺序

建议分三步实施，避免一次性大改：

### 第一步：先把 phase 语义显式化

- 保留现有 shadow 机制
- 但先把 `eval` 写成显式 `compute -> commit` 框架
- `compute` 只跑 non-sink
- `commit` 只跑 sink，再内部调用旧的 shadow commit

这一步的价值是先把控制流形状稳定下来。

### 第二步：把 sink 从“写 shadow”改为“直接写 state”

- register / latch write 去掉 `state shadow`
- memory write 去掉 `memory write shadow`
- `commit` 直接更新 state，并直接统计 `state_changed`

这一步完成后，`commit_state_updates()` 将自然退化为空壳。

### 第三步：删除旧 shadow 基础设施

- 删除 shadow pools
- 删除 touched 索引
- 删除 chunked commit dispatcher
- 收缩头文件和状态初始化逻辑

这样更容易做行为对照，也更容易定位回归。

## 11. 验证要点

至少需要覆盖以下场景：

- 纯组合 + register write：确认 write 仅在 commit 生效
- register 写后同次 `eval` 激活 reader：确认 fixed-point 收敛
- latch write / latch read：确认与 register 同样遵守 phase 语义
- memory write / memory read：确认 row 更新后 reader 被重新激活
- masked memory write：确认只有 merge 后真变化才激活 reader
- sink 直接依赖输入：确认输入变化可直接触发 commit
- 无返回值 `SystemTask` / `DpicCall`：确认仍按 sink topo 顺序执行
- 带返回值 `DpicCall`：确认仍留在 compute，不被误放入 sink
- 多写同一 register：确认冲突语义和当前实现一致
- gated clock / event edge：确认 round-local event 清理规则不变

## 12. 最终结论

这次优化的核心不是“再做一层 commit 优化”，而是把已有的 `sink supernode` 调度语义真正兑现到运行时：

- `compute` 只做组合求值
- `commit` 只做 sink 执行
- state 写入不再经过 shadow
- state 真变化时，直接跨 declaration 激活 reader compute supernode
- fixed-point 以 `compute -> commit -> compute` 的方式在单次 `eval()` 内收敛

关于第 1 点的最终结论也可以浓缩为一句：

- 当前 sink supernode 已经覆盖了所有本地 state 写 op，没有遗漏；state read op 不在 sink 中，这不是缺陷，而是新两阶段模型必须保留的边界。

## 增量更新 2026-04-23

- 首版归档到 `pdocs/grhsim_opt`
- 固化“sink coverage 核对 + compute/commit 双阶段 eval 方案”
- 明确本文是设计文档，不代表实现已落地
