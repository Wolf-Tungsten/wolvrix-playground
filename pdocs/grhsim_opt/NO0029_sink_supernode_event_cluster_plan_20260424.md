# NO0029 Sink Supernode Event Cluster Plan 20260424

## 目标

- 基于 [`NO0028`](./NO0028_grhsim_emit_tail_compile_root_cause_20260424.md) 的结论，细化一种新的 sink supernode 组织方式：
  - 在生成 sink supernode 时优先按 `event guard` 聚类
  - 尽量降低单个 supernode 内 event guard 类型数
  - 把 `event guard` 提升为外层统一判断
  - 在 event guard 内管理一组实际写入，减少重复分支和 CFG 分裂

## 背景判断

`NO0028` 已经确认：

- 目前 compile tail 的主因不是文件长度，而是巨 `eval_batch_xxx` 中混入了过多：
  - `event_edge_slots_[...]`
  - `execute_system_task(...)`
  - masked commit write
  - 写后 `supernode_active_curr_[...]` reactivation
- 这些结构会明显放大 LLVM `GVNPass` / MemorySSA 的成本。

当前 sink supernode 的问题不是单纯 “op 太多”，而是：

- 一个 supernode 内经常混了多种 event guard
- 相同 event guard 在代码里被多次重复展开
- event guard 与具体写入操作交错，导致 CFG 被重复切碎

因此，仅靠 `max_sink_supernode_op` 不足以解决 compile tail。需要让 sink supernode 的组织方式本身更接近编译器友好的形态。

## 核心思路

### 一句话版本

把 sink supernode 从“按拓扑/大小堆 op”的模式，改成“先按 event guard 聚类，再在 guard 内安排写入”的模式。

### 想要的代码形态

当前更像这样：

```cpp
if (event_a) { write_0(); }
if (event_b) { write_1(); }
if (event_a) { write_2(); }
if (event_c || event_d) { write_3(); }
if (event_a) { write_4(); }
```

目标是更接近这样：

```cpp
if (event_a) {
    write_0();
    write_2();
    write_4();
}
if (event_b) {
    write_1();
}
if (event_c || event_d) {
    write_3();
}
```

这类改写的直接收益：

- 减少重复 event 判断
- 降低 basic block 数量
- 降低同一函数中 event guard 的交错程度
- 让大量纯写入在一个更稳定的控制上下文里连续出现

## 设计原则

### 1. event guard 类型数优先于 op 数

对 sink supernode 来说，真正应该优先控制的是：

- guard 类型数
- guard block 数
- `||` 多事件 guard 数
- guard 切换次数

而不是只看：

- op 数
- 估计行数

原因是 compile tail 的关键成本来自 CFG / MemorySSA，而不是 token 数本身。

### 2. event guard 作为外层分组条件

如果一批 sink write 共享相同 guard，就应该：

- 先发射一层统一 `if (guard)` 
- 再在 guard 内连续发射 write

而不是给每个 write 单独套一层同样的 `if (guard)`。

### 3. guard key 应该是“规范化”的

不能直接按原始 AST 字符串做 key，而应该先规范化：

- 单事件 `posedge(slot_0)`
- 单事件 `negedge(slot_7)`
- 双事件 `posedge(slot_0) || posedge(slot_8)`
- 无 event guard

同语义但书写顺序不同的 guard 应归并到同一个 key。

### 4. 只在 sink supernode 做，不影响普通 compute supernode

这个策略主要针对 sink / commit-heavy 区域。

因为问题最严重的部分是：

- memory-visible write
- event-driven side effect
- 写后 reactivation

普通纯组合 compute supernode 不一定值得引入这套复杂度。

## event key 设计

建议给每个 sink op 计算一个 `EventGuardKey`：

```text
EventGuardKey {
  kind:
    none
    single_edge
    disjunction_of_edges

  edges: sorted list of {
    slot_id,
    edge_kind   // posedge / negedge / any-change if future exists
  }
}
```

### 规范化规则

1. `none` 单独作为一个 key。
2. `a || b` 与 `b || a` 归并。
3. 重复 edge 去重。
4. 当前只接受 emitter 已知的简单事件模式：
   - 单 edge
   - 多个 edge 的 OR
5. 如果 guard 不是这一类简单模式，就回退到 `opaque`，不做激进合并。

这样做的原因：

- 设计里 event 类型总量通常有限
- 规范化后 key 集合会比 op 集合小很多
- 这正是可以拿来压 CFG 的结构信息

## sink supernode 的新组织方式

### 现有模式

可以抽象成：

```text
sink supernode
  = [op0, op1, op2, op3, ...]
```

### 新模式

改成二层结构：

```text
sink supernode
  = [guard group 0, guard group 1, guard group 2, ...]

guard group
  = {
      event_guard_key,
      writes[],
      side_effects[],
      local_stats
    }
```

每个 guard group 内部再保留原始拓扑顺序。

### 关键点

- 不是打乱语义顺序地全局排序。
- 只是在 **不破坏 sink 可见语义** 的前提下，把可共享 guard 的写入尽量聚在一起。
- group 内仍按原始依赖与稳定顺序发射。

## 建议的构造流程

### Step 1. 为每个 sink op 提取 guard key

对每个 sink write / system task / side effect op：

- 提取 event guard
- 规范化成 `EventGuardKey`
- 顺便统计：
  - 是否有 side effect
  - 是否 masked commit write
  - reactivation fanout

### Step 2. 先按 guard key 分桶

形成：

```text
guard_key -> [sink op...]
```

### Step 3. 桶内保持相对顺序

每个桶里的 op 维持原始稳定顺序。

如果存在真实顺序依赖，仍然在桶内保序，不做重排。

### Step 4. 对过大的 guard 桶再二次切分

即使 guard 相同，也不能无限堆大。

建议在 guard 桶内部继续按以下指标切 chunk：

- masked write 数
- reactivation fanout 总数
- side effect 数
- 估计 IR basic block 成本

### Step 5. 最终生成 “guard-group supernode”

代码形态应变成：

```cpp
void GrhSIM_SimTop::eval_batch_xxx() {
    if (guard_a) {
        // group a writes
    }
    if (guard_b) {
        // group b writes
    }
    if (guard_c) {
        // group c writes
    }
}
```

而不是把这些 guard 交错散落在整个函数中。

## emit 侧建议形态

### 目标形态

```cpp
if (event_edge_slots_[0] == grhsim_event_edge_kind::posedge) {
    // write cluster A
    ...
    ...
}

if (event_edge_slots_[0] == grhsim_event_edge_kind::posedge ||
    event_edge_slots_[8] == grhsim_event_edge_kind::posedge) {
    // write cluster B
    ...
}
```

### 不希望继续出现的形态

```cpp
if (event0) { write_a(); }
if (event0) { write_b(); }
if (event0 || event8) { write_c(); }
if (event0) { write_d(); }
if (event0 || event8) { write_e(); }
```

这个形态的问题是：

- 守卫条件重复
- block 数变多
- 同类条件被穿插
- GVN / MemorySSA 的支配关系和可见性分析变复杂

## side effect 的单独约束

system task / extern side effect 不能简单与普通 masked write 混编。

建议：

1. `system task` 单独作为更高优先级的 group 类型。
2. 即使 guard key 相同，也不要和大量普通 commit write 放进同一大 group。
3. 可以拆成：

```text
guard_a:
  - write group
  - side-effect group
```

对应代码：

```cpp
if (guard_a) {
    // pure writes
}
if (guard_a) {
    // system tasks / extern calls
}
```

这样虽然 guard 会重复一次，但可以避免把 side effect 传播到整坨纯写入的 MemorySSA 区域里。

这点很重要，因为 compile 成本最怕的是：

- 一个巨大函数里既有大量 store，又有大量 side effect call。

## reactivation 的处理建议

除了 event guard，另一个需要一起纳入 cost 的是 reactivation fanout。

因为：

- 一个 write 后面如果要打很多 `supernode_active_curr_[...] |= ...`
- 它带来的 IR/CFG 压力并不比写本体小很多

建议在 group 内继续限制：

- `sum(reactivation_edges)`
- `max_reactivation_fanout_per_write`

如果某个 guard 桶虽然 event 类型单一，但 fanout 特别大，也要继续拆。

## 新的切块 cost model

建议把 sink supernode 的 cost 从单轴改成多轴：

```text
sink_group_risk =
  op_count * A +
  masked_write_count * B +
  reactivation_count * C +
  side_effect_count * D +
  event_guard_type_count * E +
  event_guard_block_count * F +
  multi_event_guard_count * G +
  guard_switch_count * H
```

其中最关键的是后三项：

- `event_guard_type_count`
- `multi_event_guard_count`
- `guard_switch_count`

这三项直接反映一个函数的 CFG 会不会被 event guard 打碎。

## 语义约束

这个方案必须满足几个前提。

### 1. 不改变同一 guard 内的依赖顺序

group 内只能做稳定聚类，不能把真实有顺序依赖的 sink write 重排。

### 2. 不跨越不同可见性边界乱合并

如果两个 op 虽然 guard 一样，但中间有必须保留的可见性/顺序边界，就不能硬并。

### 3. side effect 不能被纯写入吞并

对 compiler 来说，side effect 是污染源；对语义来说，它也经常是严格有序的。

### 4. 允许保守回退

如果 guard key 提取失败，或者遇到复杂 guard：

- 直接回退到原有模式
- 不为了聚类牺牲正确性

## 为什么这个方向值得做

这个方案比单纯继续调 `max_sink_supernode_op` 更有针对性，因为它直接瞄准了 `NO0028` 识别出的病灶：

1. 设计里的 event 类型通常有限。
   这意味着 guard key 的基数天然小，适合作为更高层的分组维度。
2. compile tail 本质上是 CFG / MemorySSA 问题。
   按 event 聚类，正是在减少 CFG 的切换频率。
3. event guard 统一外提以后，重复条件判断会减少。
4. 一个 guard 内连续发写入，比 guard 与写入交错展开更适合优化器处理。

## 实施建议

### 第一阶段

- 只对 sink supernode 启用 event clustering
- 只处理简单 guard：
  - `none`
  - `single edge`
  - `OR of edges`
- system task 单独分组

### 第二阶段

- 给 sink chunking 增加新的风险预算
- 把 `guard_type_count` / `guard_switch_count` 纳入 split 条件

### 第三阶段

- 对 compile tail 文件做 A/B 验证：
  - `sched_945`
  - `sched_964`
  - `sched_1230`
  - `sched_1304`

看这些文件的：

- `event_guard_block_count`
- `GVNPass` 时间
- 单文件隔离编译时间

是否明显下降。

## 预期收益

如果实现正确，预期收益主要有三类：

1. 编译期：
   - 减少重复 guard
   - 减少 CFG 分裂
   - 降低 GVN / MemorySSA 长尾
2. 代码形态：
   - sink batch 更规整
   - event-heavy 文件更容易读和分析
3. 后续优化空间：
   - 更容易继续做 guard-aware chunking
   - 更容易把 side effect / pure write 进一步分层

## 风险

### 1. 过度聚类导致单 group 反而过大

所以 event clustering 不是“只按 event 合并”，而是：

- 先按 event 聚类
- 再按风险预算切小

### 2. guard 一样但 side effect 类型不同

这类不能简单放一起，需要 side-effect-aware 二次拆分。

### 3. 过度依赖字符串相等做 key

必须使用规范化 key，不能直接拿 emit 字符串做聚类依据。

## 结论

- 你的方向是对的，而且和 `NO0028` 的根因分析是正对齐的。
- sink supernode 下一步不该只是继续调大小，而应该引入 **event-aware clustering**。
- 更具体地说，应该把：
  - `event guard` 变成 supernode 内的第一层组织维度
  - `write cluster` 变成第二层
  - `side effect` / `reactivation` 作为进一步切块约束
- 这样才能真正减少 event guard 重复展开，把 compile tail 从“文本大小问题”转成“结构受控问题”。
