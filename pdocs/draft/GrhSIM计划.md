# GrhSIM 计划

本文先不讨论零散优化点，先把当前 `grhsim-cpp` 的执行模型讲清楚。后续重构、语义修正、体积压缩，都应围绕这个模型逐层拆开，而不是继续在局部打补丁。

## 0. 本轮重构边界

当前共识：

- `activity-schedule` 本身已经足够清晰
- 本轮不修改 `activity-schedule` 的建模、切分、coarsen、replication 和 session 导出逻辑
- 计划文档里保留 `activity-schedule` 的字段语义，只把它作为 `grhsim-cpp` 的既定输入前提

因此，后续这里讨论的“重构”默认只指：

- `grhsim-cpp emit` 的代码生成结构
- 生成后运行时的 fixed-point 执行模型
- event / staged write / materialized value 的语义分层与体积优化

不包括：

- 改 `activity-schedule` 算法
- 改 supernode 划分策略
- 改 session 数据格式

## 1. 当前核心模型

当前 GrhSIM 生成出来的 C++，本质上是一个：

- 基于 `activity-schedule` 的
- supernode 粒度的
- fixed-point 迭代执行器

它不是传统“按 always block 直接翻译”的执行器，也不是事件队列驱动仿真器。它更像一个：

1. 先把图切成 supernode
2. 用位图表示哪些 supernode 当前活跃
3. 反复执行活跃 supernode
4. 当组合值变化或状态提交后，再激活依赖它们的 supernode
5. 直到没有活跃 supernode 为止

因此，当前实现的本体语义不是“事件驱动”，而是“固定点求解”。

## 2. 当前执行流

### 2.1 emit 依赖的前提

`grhsim-cpp` emit 不直接从裸 GRH 发代码，而是依赖 `activity-schedule` 先准备好 session 数据：

- `supernode_to_ops`
- `value_fanout`
- `topo_order`
- `state_read_supernodes`

这些数据定义了当前执行器的拓扑结构。

### 2.1.1 这四个字段各自是什么意思

下面这四个字段不要混成“普通图信息”。它们都已经是 `activity-schedule` 产出的“执行结构信息”。

#### `supernode_to_ops`

类型：

- `std::vector<std::vector<OperationId>>`

含义：

- 下标是 `supernodeId`
- 值是这个 supernode 内按局部 topo 顺序排列的 op 列表

运行时用途：

- `eval_batch_*()` 真正执行 supernode 时，就是顺序遍历 `supernode_to_ops[supernodeId]`
- 这是“一个 supernode 里到底要跑哪些 op”的直接定义

要点：

- 它定义的是执行簇内部内容
- 不是原始 GRH 的 block/进程边界
- 同一个 supernode 内部的值，可以被当作局部临时量处理

#### `value_fanout`

类型：

- `std::vector<std::vector<uint32_t>>`

含义：

- 下标对应 `ValueId.index - 1`
- 值是“使用这个 value 的后继 supernodeId 列表”
- 这里只记录跨 supernode 边界的 fanout

构建规则：

- 若某个 operand 的定义 op 在 `fromNode`
- 使用它的 op 在 `toNode`
- 且 `fromNode != toNode`
- 则把 `toNode` 放进该 value 的 `value_fanout`

运行时用途：

- 当某个被物化的组合值发生变化时
- emitter 会查它的 `value_fanout`
- 并重新激活这些后继 supernode

要点：

- 这不是“原始图上所有 user”
- 它只关心跨 supernode 的传播边界
- 当前 emit 里“哪些 value 必须物化”为成员字段，和它强相关

#### `topo_order`

类型：

- `std::vector<uint32_t>`

含义：

- 一个全局的 supernode 拓扑序列
- 元素本身就是 `supernodeId`

构建规则：

- 先根据 supernode 之间的 DAG 建图
- 再对 supernode DAG 做 topo sort
- 最终把 topo layer 摊平成一条线性顺序

运行时用途：

- batch 划分是基于这条顺序做的
- `eval_batch_*()` 的发射顺序也服从这个顺序
- fixed-point 每一轮传播时，supernode 都按这个顺序被扫描

要点：

- 它定义的是“跨 supernode 的合法执行顺序”
- 不涉及 supernode 内部 op 的顺序

#### `state_read_supernodes`

类型：

- `std::unordered_map<std::string, std::vector<uint32_t>>`

含义：

- key 是状态对象符号名，例如某个 reg / latch / memory 的 symbol
- value 是“读取该状态的 supernodeId 列表”

构建规则：

- 遍历所有 state read op
- 找到它读的是哪个状态符号
- 再找到这个 read op 属于哪个 supernode
- 把该 supernode 记到这个状态的 reader 集合里

运行时用途：

- `commit_state_updates()` 提交 touched shadow 后
- 如果某个状态真的发生变化
- 就查 `state_read_supernodes[stateSymbol]`
- 并重新激活所有读这个状态的 supernode

要点：

- 它定义的是“状态变化之后，要重新算谁”
- 是 fixed-point 里时序反馈链的关键索引

### 2.2 目标运行时结构

这一节开始不再沿用当前实现的命名和拆法，而是记录本轮重构希望收敛到的运行时结构。

先给出本轮 event 重构的总前提：

1. event value 本身仍然是正常的 value，继续参与 fixed-point 传播
2. activity 传播按 supernode 拓扑序进行，因此 event value 的新值一定先于依赖它的带 event 输入 op 可见
3. 本轮不引入独立事件队列，只在 fixed-point 求解过程中附带维护共享 `evt_edge_*`
4. emitter 只识别“直接连接到 event 操作数的 value”作为 event value 集合
5. 这些 event value 在真实电路里预期主要是 `clk` / `rst` 或它们的简单派生，数量应远小于 op 数量

目标生成物里应有几类关键状态：

- `supernode_active_bitmap`
  当前活跃 supernode 位图。

- `active_word_count_`
  当前仍有多少活跃 word，用来快速判空。这个字段语义没问题，暂不要求改名。

- `val_*`
  只物化那些需要跨 supernode 传播的组合值。
  换句话说，`val_*` 不再是“通用组合中间值槽位”，而是“supernode 边界传播接口”。
  supernode 内部纯局部中间值应优先落成局部临时量。
  但有一个例外：
  内部传播的 event value 也必须有稳定的当前值槽位，便于和新结果比较并生成 `evt_edge_*`。
  由于这类 value 总量预期很小，当前计划默认也落在 `val_*` 中。

- `state_*`
  持久状态对象，包含 reg / latch / memory。

- `state_shadow_*`
  next-state shadow 槽位。
  这里不是“整份 `state_next` 全量双缓冲”，而是“只给被写状态保留 shadow”。
  写口命中时直接生成最终 next 值写入 shadow，commit 时只提交 touched shadow。

- `state_shadow_touched_*`
  shadow 命中标记。
  用来记录哪些状态对象或 memory row 在本轮被写过，避免全量复制和全量提交。

- `prev_input_*`
  输入变化检测基线。

- `evt_edge_*`
  事件边沿记录。
  这是本轮修改的重点。

`evt_edge_*` 的目标语义是：

- 粒度按“连接到 event 操作数的 value”建，而不是按 op 建
- 每个 event value 在运行时只对应一个共享 `evt_edge_*`
- 对外部输入 event value，在迭代开始前用 `prev_input_*` 和当前输入先计算一次 `evt_edge_*`
- 对内部传播的 event value，在本轮求解中一旦发生变化，就立即更新对应的 `evt_edge_*`
- 所有带 event 操作数的 op 后续都不再自己维护 `prev_evt_*` / `seen_evt_*`
- 这类 op 在执行点统一消费其依赖的 event value 对应的 `evt_edge_*`
- 当前轮产生的 `evt_edge_*` 在 commit 之后统一清为 `none`，下一轮再重新播种

因此，当前的：

- `prev_evt_*`
- `seen_evt_*`

都应从目标结构中移除。

#### `evt_edge_*` 的枚举值

`evt_edge_*` 使用 3 态枚举：

- `none`
- `posedge`
- `negedge`

这里不需要 `bothedge` / `dualedge` 一类状态。

目标约束是：

- 对单个 event value，在当前模型里，一轮求解只保留一个明确的边沿结果
- 也就是 `none / posedge / negedge` 三选一

因此，`evt_edge_*` 记录的是“当前轮里，这个 event value 的当前边沿结果”，不是长期基线，不是累计历史，也不是 per-op 私有状态。

### 2.3 `eval()` 主循环

这一节后续讨论要使用固定分段名，避免混淆“哪一段在执行 supernode topo”“哪一段在做 commit”“哪一段在更新 baseline”。

#### `eval()` 完整伪代码

下面给出一版完整伪代码，作为后续交流的统一骨架。

```cpp
void eval() {
    // Phase A: Input Stimulus Capture
    // 读取当前输入，但此时不更新 prev_input_*。
    const bool initial_eval = first_eval_;

    // Phase B: Activity Seed
    // 依赖不变量：
    // 1) 正常退出上一轮 eval() 时，supernode_active_bitmap 必为空
    // 2) 初次 eval() 不依赖旧 bitmap，直接走全量激活
    if (initial_eval) {
        activate_all_supernodes(supernode_active_bitmap, active_word_count_);
    } else {
        for (InputValue in : input_values) {
            if (current_input_value[in] != prev_input_slot[in]) {
                activate_supernodes_of_input(in, supernode_active_bitmap, active_word_count_);
            }
        }
    }

    // Phase C: Input Event Edge Seed
    // 只处理“直接来自输入端口”的 event value。
    for (EventValue ev : input_event_values) {
        event_edge_slot[ev] = classify_edge(prev_input_slot[ev], current_input_value[ev]);  // none / posedge / negedge
    }

    while (active_word_count_ != 0) {
        // Phase D: Supernode Topo Execute
        for (SupernodeId sid : topo_order) {
            // 当前未激活的 supernode，本轮直接跳过。
            if (!supernode_active_bitmap.test(sid)) {
                continue;
            }

            // 进入执行前，先消费掉这个 supernode 的 active bit。
            // 若执行过程中又被重新激活，会留给后续 fixed-point 轮次处理。
            clear_supernode_active(sid, supernode_active_bitmap, active_word_count_);

            for (Op op : supernode_to_ops[sid]) {
                // 1) 执行到这个 op 时，按它自身语义尝试执行。
                //    如果该 op 带 event 操作数，则在 try_execute_op(...)
                //    内部读取 event_edge_slot 判断这次是否触发。
                //    若触发，则它在内部完成该 op 应有的副作用，
                //    包括更新 touched shadow、dpi/system task 执行等。
                auto result = try_execute_op(op, event_edge_slot, state_shadow_slots);
                if (!result.executed) {
                    continue;
                }

                // 2) 若 op 这次真的执行了，并产出了结果值，
                //    就处理结果传播。
                if (result.has_result_value) {
                    ValueId value = result.result_value;
                    auto new_result = result.result_data;

                    // 3) 只有“跨 supernode 传播值”或“event value”
                    //    才需要稳定的边界传播槽位。
                    const bool has_boundary_slot =
                        is_materialized_boundary_value(value) || is_event_value(value);

                    // 4) 对需要稳定槽位的 value，顺序必须是：
                    //    先读旧槽位，再算 edge，最后写回新槽位。
                    if (has_boundary_slot) {
                        auto old_result = boundary_value_slot[value];
                        if (old_result != new_result) {
                            if (is_event_value(value)) {
                                event_edge_slot[value] = classify_edge(old_result, new_result);
                            }
                            boundary_value_slot[value] = new_result;
                            if (is_materialized_boundary_value(value)) {
                                activate_value_fanout(value, supernode_active_bitmap, active_word_count_);
                            }
                        }
                    }
                }
            }
        }

        // Phase E: Commit Phase
        auto changed_states = commit_state_updates(state_shadow_slots);
        for (StateSymbol state_symbol : changed_states) {
            activate_state_readers(state_symbol, supernode_active_bitmap, active_word_count_);
        }

        // Phase F: Event Edge Clear
        // 清理本轮 Phase D / E 中消费过的边沿结果。
        for (EventValue ev : all_event_values) {
            event_edge_slot[ev] = EdgeKind::none;
        }
    }

    // Phase G: Output Publish
    refresh_outputs();

    // Phase H: Input Baseline Commit
    for (InputValue in : input_values) {
        prev_input_slot[in] = current_input_value[in];
    }
    first_eval_ = false;
}
```

这段伪代码故意保留了几个抽象 helper，后续我们讨论时可以直接落成具体生成策略：

- `classify_edge(old, new)`
- `is_materialized_boundary_value(value)`
- `is_event_value(value)`
- `try_execute_op(...)`
- `clear_supernode_active(...)`
- `commit_state_updates(...)`
- `activate_value_fanout(...)`
- `activate_state_readers(...)`

其中最关键的是：

- `classify_edge(old, new)` 只产出 `none / posedge / negedge`
- event value 的边沿计算发生在 value 更新点
- 所有带 event 操作数的 op 都是在“执行到该 op 时”读取 `event_edge_slot[...]` 并决定这次是否触发
- side effect / shadow 写入 / dpi / system task 都属于 op 自身执行的一部分，不单独拆成尾部阶段
- `prev_input_*` 只在整个 `eval()` 结束时更新
- 对内部 event value，旧值来源就是更新前的 `boundary_value_slot[...]`
- 因此顺序必须是“先读旧边界传播槽位，再算 `event_edge_slot[...]`，最后写回新边界传播槽位”

建议把一次 `eval()` 形式化拆成下面几个阶段。

#### Phase A: 输入刺激采样（Input Stimulus Capture）

这一段只做外部可见输入的读取，不做任何传播：

- 读取当前 input / inout 输入值
- 保持 `prev_input_*` 不变

这里的关键约束是：

- `prev_input_*` 代表“上一次 `eval()` 收敛后的输入基线”
- 在本次 `eval()` 完全结束前，不更新 `prev_input_*`

#### Phase B: 活动度播种（Activity Seed）

这一段只负责决定 fixed-point 从哪里开始算：

- 若是第一次 `eval()`，则全量激活全部 supernode
- 否则比较当前输入与 `prev_input_*`
- 如果某个输入变化，则激活引用该输入的 supernode

这一步只播种 `supernode_active_bitmap`，不执行 op。

这里依赖一个运行时不变量：

- 正常退出上一轮 `eval()` 时，`supernode_active_bitmap` 必为空
- 因此热路径里不需要先无条件 `clear(supernode_active_bitmap)`
- 初始 `eval()` 则直接走“全量激活”路径，不依赖旧 bitmap 内容

#### Phase C: 输入事件边沿播种（Input Event Edge Seed）

这一段只处理“直接来自输入端口的 event value”：

- 对每个输入类 event value
- 用 `prev_input_*` 和当前输入值计算其初始 `evt_edge_*`

这一段只在进入 fixed-point 之前做一次。

这里必须明确：

- 不能在这里更新 `prev_input_*`
- 否则后续本轮 `eval()` 内就失去“旧输入基线”

#### Phase D: supernode 拓扑执行段（Supernode Topo Execute）

这是 fixed-point 的主执行段，也是后续交流时默认说的“执行段”。

形式上：

- `while (active_word_count_ != 0)` 进入一轮迭代
- 在这一轮里按 `topo_order` 顺序扫描 supernode
- 若某个 supernode 当前不在 `supernode_active_bitmap` 中，则本轮直接跳过
- 若某个 supernode 当前处于 active，则先消费掉它的 active bit，再执行它内部的 op
- 每个 supernode 内按 `supernode_to_ops[supernodeId]` 的局部 topo 顺序执行 op

这一段里发生的事情包括：

- 执行到某个带 event 操作数的 op 时，在它自身语义里读取 `evt_edge_*` 决定这次是否触发
- 组合局部临时值求值
- 被物化的 `val_*` 更新
- 若 `val_*` 变化，则通过 `value_fanout` 激活后继 supernode
- 若某个内部传播的 event value 变化，则立刻更新它对应的 `evt_edge_*`
- 带 event 操作数的 `dpicall` / `system task` / 写口 / 普通结果 op 都直接消费 `evt_edge_*`
- 写口只写 `state_shadow_*`，不直接改 `state_*`

所以：

- “supernode topo 执行”只发生在 Phase D
- “未激活 supernode 直接跳过”也只发生在 Phase D 的扫描逻辑里
- 事件边沿的实时产生也发生在 Phase D

#### Phase E: 提交段（Commit Phase）

这一段只负责把 touched shadow 统一提交到状态：

- 执行 `commit_state_updates()`
- 把 `state_shadow_*` 写入 `state_*`
- 如果状态真的变化，则通过 `state_read_supernodes` 激活读该状态的 supernode

所以：

- “状态真正改变”只发生在 Phase E
- 由状态变化触发的新一轮活动度，也是在 Phase E 产生

#### Phase F: 事件边沿清理段（Event Edge Clear）

这一段放在每轮迭代的 commit 之后。

规则是：

- 当前轮 Phase D 中产生的 `evt_edge_*`
- 必须允许同轮里所有带 event 输入的 op 消费完
- 一旦进入下一轮迭代前，就统一清成 `none`

因此，`evt_edge_*` 的生命周期应是：

- 先在 Phase C 为输入类 event value 播种一次
- 在 Phase D 中被内部传播增量更新
- 在 Phase E 完成 commit 后
- 再由 Phase F 统一清零

这样做的原因是：

- 如果把清零放在每轮迭代开始前
- 那么输入类 event value 在第一轮播种出来的 edge，后续迭代可能被过早抹掉或被重复播种
- 把清零放在 commit 之后，边沿结果刚好覆盖“本轮执行段”，不会泄漏到下一轮

#### Phase G: 输出发布段（Output Publish）

当 fixed-point 收敛，也就是 `active_word_count_ == 0` 后：

- 刷新输出端口
- 刷新 inout 输出/oe

这一步只做外部可见结果发布。

#### Phase H: 输入基线提交段（Input Baseline Commit）

这是 `prev_input_*` 的唯一更新时间点。

规则是：

- 必须等整个 `eval()` 完全收敛
- 输出已经刷新完毕
- 本轮不再继续 fixed-point 迭代
- 然后才把当前输入写回 `prev_input_*`

所以：

- `prev_input_*` 不是“迭代级基线”
- 它是“eval 级基线”

所以当前语义的中心应明确成：

- 组合传播靠 `value_fanout`
- 状态反馈靠 Phase E 的 `commit_state_updates()`
- 事件传播靠共享 `evt_edge_*`
- 输入旧值基线只在 Phase H 更新
- 整体靠 `Phase D -> Phase E -> Phase F` 的 fixed-point 循环收敛

## 3. supernode 语义

当前 supernode 不是语义上的 always block，而是 `activity-schedule` 算出来的一个执行簇。

它的作用是：

- 把组合逻辑打包成较大的执行单元
- 减少运行时调度粒度
- 把组合传播从“逐 op 调度”降到“逐 supernode 调度”

因此，一个 supernode 内部当前默认假设：

- 在单次执行时，可以按 topo 顺序直接顺推
- supernode 内中间值可以局部化
- supernode 边界值才需要稳定可见的传播接口

这也是当前为什么要区分：

- supernode 内部 value
- 跨 supernode 边界 value

## 4. 当前固定点模型里三条传播链

### 4.1 输入变化传播

输入端口不直接触发全图重算，而是：

- 把输入与 `prev_input_*` 比较
- 若变化，则激活引用该输入的 supernode

这是外部刺激进入 fixed-point 的入口。

### 4.2 组合值变化传播

当某个被物化的组合值在 supernode 内被更新后：

- 如果它在 `value_fanout` 中有跨 supernode 后继
- 则激活这些后继 supernode

这是组合传播链。

### 4.3 状态提交传播

写口不直接写 `state_*`，而是先写对应的 touched shadow。

`commit_state_updates()` 统一提交后：

- 如果状态确实变化
- 则激活读取该状态的 supernode

这是时序反馈链。

### 4.4 事件边沿传播

event 不再建模为“op 级私有基线 + 去重标记”，而是：

- 先识别所有直接接到 event 操作数上的 value
- 给这些 value 各自分配一个共享 `evt_edge_*`

传播规则分两类：

- 外部输入 event value：
  在进入 fixed-point 前的 Phase C，由 `prev_input_*` 和当前输入直接计算 `evt_edge_*`

- 内部传播 event value：
  在 Phase D 的 supernode 执行过程中，一旦该 value 的新值与旧值不同，立即计算并写入 `evt_edge_*`

所有带 event 操作数的 op 的判断规则是：

- `posedge` 触发条件：`evt_edge_* == posedge`
- `negedge` 触发条件：`evt_edge_* == negedge`
- 无 edge 限定的变化触发：`evt_edge_* != none`

这条链的关键点不是“保存旧值”，而是：

- 在当前轮求解里实时产出边沿结果
- 让所有带 event 输入的 op 在同轮执行里直接消费
- 并在 commit 后统一清空，避免把上一轮边沿带入下一轮

## 5. 写口重构方向：touched next-shadow

当前实现里，寄存器/存储器/锁存器写口都被建模为：

- 在组合阶段计算“是否写”“写什么”
- 先写入 `pending_commit_*` 槽位
- 在统一提交阶段修改状态

这样做的好处是：

- 避免同一轮 fixed-point 中状态被提前污染
- 把时序边界统一到 `commit_state_updates()`

但代价也很明显：

- `pending_commit_*` 数量巨大
- `init()` 中 staged write 初始化极重
- `state.cpp` 体积容易爆炸

这已经成为当前 XS 下的主瓶颈。

本轮决定把写口模型重构成：

- `state_*`
  当前可见状态，只读不在 Phase D 里原地改写。

- `state_shadow_*`
  next-state shadow。
  对 `register / latch`，按状态对象各保留一个 shadow 值槽位。
  写口命中时，不再记录 `valid/data/mask/addr` 这类分裂中间态，而是直接形成“本轮最终 next 值”写入 shadow。

- `state_shadow_touched_*`
  shadow 命中标记。
  对 `register / latch`，按状态对象各保留一个 touched 标记，commit 时只提交 touched 项。

- `memory_shadow_*`
  memory 写口 shadow。
  当前阶段按“每个 memory 写口一个 shadow”落地，字段形态是：
  `memory_shadow_addr_*`、`memory_shadow_data_*`、可选的 `memory_shadow_mask_*`。
  若该写口是全写口，则不生成 `mask` 字段。

- `memory_shadow_touched_*`
  memory 写口命中标记。
  当前阶段按“每个 memory 写口一个 touched 位”落地。

这里要明确否定一种容易想到但代价很高的方案：

- 不做“`state_*` + `state_next_*` 全量双缓冲”

原因是：

- 对 memory 来说，全量双份状态会明显抬高运行时内存
- 每轮 commit 后如果要整份复制或重新对齐 `state_next_*`，代价会从“按 touched 提交”退化成“按全状态规模复制”
- XS 场景下，体积问题可能缓解，但运行时成本会变得不可接受

因此，目标模型是“保留 shadow，但只保留 touched shadow”，不是“全量双缓冲”。

这个模型下，写口语义应改成：

- Phase D 中，读口始终只读 `state_*`
- 写口命中时，立即把最终 next 值写入 `state_shadow_*`
- 如果该写口是 masked write，则在写口处当场完成 merge，shadow 里存放的就是最终 next 值，不再额外保存 `mask`
- `register / latch` 的具体字段形态定为“每个状态对象一个 shadow 值 + 一个 touched 位”
- `memory` 的具体字段形态定为“每个写口一个 addr/data[/mask] shadow + 一个 touched 位”
- 如果该写口写 memory，则 emit 阶段先保留“每写口一个 shadow”的简单模型，不在 emitter 内保证多写口冲突语义
- 多个 memory 写口若在同轮命中，则 Phase E 直接按 emitter 当前最简单实现方式覆盖提交；该覆盖顺序视为未规定行为（UB），文档和实现都不对其作保证
- memory 多写口冲突的静态检查与报警后移到独立 pass，不放在本轮 emitter 重构里解决
- Phase E 中，只提交 `state_shadow_touched_*` 对应的 shadow 项

这个方向的直接收益是：

- `pending_valid / pending_data / pending_mask / pending_addr` 这套写口模板可以大幅收缩
- `mask` 可以在写口处被折叠掉，不必长期物化成成员字段
- `init()` 不再需要为每个写口逐字段清零 staged write 槽位
- `commit_state_updates()` 的语义从“解释 pending 载荷”变成“提交 touched next-shadow”

当前建议的具体落地顺序是：

1. 先把 `mask` 从长期字段改成写口处即时 merge，优先消灭 `pending_mask_*`
2. 再把 `pending_valid_*` / `pending_data_*` / `pending_addr_*` 收口成 shadow 结构
3. register / latch 落地成“按状态对象一个 shadow 值 + 一个 touched 位”
4. memory 落地成“每写口一个 addr/data[/mask] shadow + 一个 touched 位”
5. 后续再补 memory 多写口冲突检查 pass，并决定是否收敛到更细的 row shadow

## 6. 当前模型对带 event 输入 op 的定义

这是当前最需要重新梳理的部分。

当前实现不是完整事件队列模型，而是把“带 event 输入的 op”整体塞进 fixed-point 模型中。

本轮决定不再修补旧结构，而是直接切到下面这个模型：

1. event value 继续按普通 value 参与 fixed-point 传播
2. emitter 识别“直接连接到 event 操作数的 value”集合
3. 每个 event value 只有一个共享 `evt_edge_*`
4. 输入类 event value 先由 `prev_input_*` 和当前输入计算出本轮初值
5. 内部 event value 在传播过程中一旦变化，立刻更新 `evt_edge_*`
6. 所有带 event 输入的 op 都是在执行到该 op 时读取 `evt_edge_*`，并把它作为自身触发条件的一部分
7. 当前轮结束 commit 后，把全部 `evt_edge_*` 统一清为 `none`

这套模型成立的关键原因是：

- activity 传播按 supernode 拓扑序前进
- event value 的计算一定先于其依赖 op 可见
- 因此不需要为每个带 event 输入的 op 单独保存一份 previous sample
- 只要在执行到该 op 时把 `evt_edge_*` 作为它自身触发条件的一部分，就能同时覆盖有返回值的 `dpicall`、写口、system task 和普通结果 op

这个重构方向下：

- `prev_evt_*` 删除
- `seen_evt_*` 删除
- 事件相关状态统一收口到共享 `evt_edge_*`

这就是本轮语义重构的中心。

## 7. 当前代码生成结构

当前主要文件职责如下：

### 7.1 `grhsim_<top>.hpp`

定义类和成员字段：

- public ports
- `val_*`
- `state_*`
- `state_shadow_*`
- `state_shadow_touched_*`
- `evt_edge_*`
- batch 函数声明

### 7.2 `grhsim_<top>_state.cpp`

主要包含：

- 构造/析构
- `init()`
- `commit_state_updates()`
- `refresh_outputs()`
- system task runtime 支撑代码

它通常是当前最大的文件，因为：

- 各类字段初始化集中在这里
- shadow 初始化和提交集中在这里
- 事件相关运行时状态初始化也在这里

### 7.3 `grhsim_<top>_eval.cpp`

主要包含：

- fixed-point 主循环
- 首轮激活逻辑
- 输入变化激活逻辑
- eval 末尾刷新逻辑

### 7.4 `grhsim_<top>_sched_*.cpp`

每个 batch 一个文件，负责：

- 按 supernode 执行 op
- 计算局部临时值
- 更新物化组合值
- 更新写口对应的 touched shadow
- 执行 system task / dpi 等 side effect op

## 8. 当前 XS 下已知现实

截至目前，当前模型已经发生过一轮重要收缩：

- `prev_evt_*` 爆炸已基本解决
- “所有 value 都物化成 `val_*` 字段”的老问题已大幅缓解

但当前 XS 现场仍然说明：

 - `pending_commit_*` 对应的 staged write 结构是新的主瓶颈
- `state.cpp:init()` 过重
- 当前带 event 输入 op 的语义分层仍不干净，需要切到 `evt_edge_*` 模型

也就是说，下一阶段不该再围绕“某个局部 helper 怎么写”展开，而是应该正面重构模型边界。

## 9. 后续重构必须先回答的几个问题

我们后续要逐步梳理的新架构，至少要先回答这些问题：

### 9.1 fixed-point 的边界是什么

- fixed-point 只负责组合传播吗
- 还是要把带 event 输入的执行语义也塞进 fixed-point
- 哪些语义应该从 fixed-point 核中拿出去

### 9.2 next-shadow 的粒度是什么

这一项当前已经有明确决策：

- `register / latch`：按状态对象保留一个 shadow 值和一个 touched 位
- `memory`：按写口保留一个 `addr/data[/mask]` shadow 和一个 touched 位
- `mask`：只在确实需要掩码写的写口上保留；能在写口处即时 merge 的就不长期物化
- memory 多写口同轮覆盖顺序：视为 UB，不在 emitter 阶段规定，也不保证行为
- memory 多写口冲突检查：后续由独立 pass 负责报警

### 9.3 event 的抽象层次是什么

- event 应明确建模为“共享事件源”
- `evt_edge_*` 只按直接 event value 维护，不按 op 扩张
- 输入类 event value 的 `evt_edge_*` 何时计算
- 内部传播 event value 的 `evt_edge_*` 在 value 更新点如何立即计算
- 所有带 event 输入的 op 如何仅凭 `evt_edge_*` 判断 `posedge / negedge / anyedge`
- 是否完全不再需要任何 per-op 事件状态

### 9.4 materialized value 的边界是什么

- 哪些 value 必须是成员字段
- 哪些只能是局部临时量
- 哪些应该转成表或延迟求值

## 10. 建议的重构顺序

后续建议严格按下面顺序推进，不要乱跳：

1. 先把“当前 fixed-point 模型”彻底说清楚
2. 明确 event 重构采用“共享 `evt_edge_*`”模式
3. 先落地 event value 识别与 `evt_edge_*` 更新规则
4. 再把写口模型从 `pending_commit_*` 切到 touched next-shadow
5. 最后再做体积和性能优化

否则会不断出现：

- 一边为了体积共享状态
- 一边又因为语义不清补 guard
- 最终越补越乱

## 11. 当前这份文档的用途

从现在开始，这份文档只承担两件事：

1. 作为“当前模型说明书”
2. 作为“新架构梳理入口”

后续我们继续改它时，优先做的是：

- 补清楚当前真实语义
- 明确哪些地方是实现妥协
- 逐步提出替代结构

而不是继续往里面堆零散 patch 点。
