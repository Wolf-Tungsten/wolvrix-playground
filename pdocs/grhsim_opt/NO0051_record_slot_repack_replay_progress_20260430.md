# NO0051 Record Slot Repack Replay Progress

## 1. 本轮结果

在 [`wolvrix/lib/transform/record_slot_repack.cpp`](../../wolvrix/lib/transform/record_slot_repack.cpp) 上继续扩展后，`record-slot-repack` 对 XiangShan replay JSON 先到：

- `graphs=1`
- `candidates=153`
- `rewritten_families=153`

随后在同一轮排查里，又定位并修掉了一个真实 bug：

- `graph.getValue(...).users()` 被直接挂在临时 `Value` 对象后面使用
- `users()` 返回的是依附于该临时对象内部存储的 `span`
- 导致 `record-slot-repack` 在 replay 图上随机读到悬空 `ValueUser`，表现为 `OperationId out of range`

修掉这个生命周期问题后，replay 计数进一步提升到：

- `graphs=1`
- `candidates=176`
- `rewritten_families=176`

对应 replay 输入：

- [`build/xs/scalar_memory_pack_replay_from_json_20260430_v9_read_write_cone/after_flatten_simplify_plus_scalar_memory_pack.json`](../../build/xs/scalar_memory_pack_replay_from_json_20260430_v9_read_write_cone/after_flatten_simplify_plus_scalar_memory_pack.json)

对应新产物：

- [`build/xs/record_slot_repack_replay_from_scalar_pack_20260430_v1/after_record_slot_repack.json`](../../build/xs/record_slot_repack_replay_from_scalar_pack_20260430_v1/after_record_slot_repack.json)
- [`build/xs/record_slot_repack_replay_from_scalar_pack_20260430_v1/after_record_slot_repack_stats.json`](../../build/xs/record_slot_repack_replay_from_scalar_pack_20260430_v1/after_record_slot_repack_stats.json)

## 2. 本轮实现了什么

### 2.1 写侧支持一个寄存器写口承载多个 point-update family

之前 `record-slot-repack` 只支持：

- 每个 scalar reg 的写口直接是一个 point-write

现在支持：

- 写条件是 `OR(point0, point1, ...)`
- 写数据是 nested `mux(point_i, data_i, next)` 或 masked-or 等价树
- 一个 field memory 最终发出多个 `kMemoryWritePort`

这一步让 pass 不再卡死在“一个写口只能恢复一个 point-update family”的假设上。

### 2.2 写侧支持 priority point-chain 的 guard 抽象

真实图中常见形态不是简单：

- `base & Eq(addr, slot)`

而是：

- `!prev_hit_same_slot & base & Eq(addr, slot)`

本轮没有把 `!prev_hit_same_slot` 当作普通 `base term` 生吞，而是把它抽象成：

- “排斥更高优先级 source 在同一地址命中”的 guard

rewrite 时恢复成：

- `base`
- `AND !((prev_base) & (prev_addr == curr_addr))`

这样 family 级条件不再依赖 member-local 常数槽位，才能跨 slot 对齐。

### 2.3 mux-read 路径允许旧值流入 write cone

之前 mux-root 读侧还要求：

- register read 只能被 read tree 自己使用

现在和 concat 路径一致，允许：

- 旧值同时流入写侧 next-value cone

否则很多 `next = mux(point, new, old)` 风格会在读侧直接被拒绝。

## 3. replay 前后计数

下面这张表对应的是第一次落到 `153` family 时保存的 stats 快照；本轮继续修掉生命周期 bug 后，计数已经进一步前进到 `176`，但尚未重新落一份完整 stats JSON。

基于 stats JSON，主要变化如下：

| op kind | before | after | delta |
| --- | ---: | ---: | ---: |
| `kRegister` | `218768` | `217850` | `-918` |
| `kRegisterReadPort` | `218768` | `217850` | `-918` |
| `kRegisterWritePort` | `218767` | `217849` | `-918` |
| `kMemory` | `1438` | `1591` | `+153` |
| `kMemoryReadPort` | `1729` | `1882` | `+153` |
| `kMemoryWritePort` | `4792` | `4945` | `+153` |
| `kConcat` | `256711` | `256558` | `-153` |
| `kSliceDynamic` | `274614` | `274461` | `-153` |

整体：

- `operation_count`: `5082531 -> 5080695`，减少 `1836`
- `register_bitwidth_total`: `3822155 -> 3816149`，减少 `6006`
- `memory_capacity_total`: `185719480 -> 185725486`，增加 `6006`

这和“把 scalar register family 改写成 field memory”是对齐的。

## 4. 仍未拿下的目标样本

本轮最初是针对：

- `loadQueueReplay.uop_*_pc`
- `loadQueueReplay.uop_*_exceptionVec_0`

做的定向推进。

修掉 `Value::users()` 生命周期 bug 之后，再次核对：

- `uop_*_pc` 已经能被改写
- `uop_*_exceptionVec_0` 仍未拿下

也就是说：

- 新增的 `23` 个 family 里，包含了 `loadQueueReplay.uop_*_pc`
- `loadQueueReplay.uop_*_exceptionVec_0` 仍是剩余阻塞点

## 5. 为什么 `loadQueueReplay` 还没被吃掉

### 5.1 读侧 concat 的 leaf 序列有 padding / duplicate

以：

- `_op_9412952` (`uop_*_pc`)
- `_op_9413082` (`uop_*_exceptionVec_0`)

为例，concat 不是简单 `72` 个 distinct leaves，而是：

- 总 operand 数 `128`
- distinct reg 只有 `72`
- 前 `56` 个 operand 全是 `uop_0_*`
- 后 `72` 个才是 `uop_71 .. uop_0`

即它更像：

- 高位 padding
- 低位真实 packed rows

这类形态已经超出最初“concat leaves 全 distinct”的假设。

### 5.2 `uop_*_pc` 的真正阻塞不是 canonicalization，而是悬空 `users()` span

定向 trace `_op_9412952` 后，真正的 read-side 异常不是 IR 形态问题，而是 pass 自身 bug：

- `member.readValue` 的 user 遍历写成了 `graph.getValue(member.readValue).users()`
- 这里 `graph.getValue(...)` 先返回临时 `Value`
- `users()` 再返回指向该临时对象内部缓存的 `span`
- range-for 迭代时临时对象已经销毁，`ValueUser` 变成悬空引用

修掉以后：

- `_op_9412952` (`uop_*_pc`) 可以稳定走到 `parsed -> accept -> rewrite_done`
- replay 总命中 `153 -> 176`

因此：

- 之前 `_op_9412952` 的 `OperationId out of range` 是 pass bug
- 不是 `loadQueueReplay.uop_*_pc` 本身不可合并

### 5.3 `uop_*_exceptionVec_0` 剩下的是写侧 cond 形态

对 `_op_9413082` (`uop_*_exceptionVec_0`) 的最新 trace：

- 读侧已经通过
- 写侧卡在 `slot=71`，即 `uop_71_exceptionVec_0`
- 对应 write op `_op_9451113`
- `point_branches=0`
- `fill_branches=3`
- 这 3 个 branch 的顶层 kind 分别是 `kAnd,kLogicAnd,kLogicAnd`
- 展平后的 term 摘要是：
  - branch0: `kRegisterReadPort;kOr;kNot;kReduceOr`
  - branch1: `kLogicNot;kRegisterReadPort;kOr;kNot;kReduceOr`
  - branch2: `kLogicNot;kLogicNot;kRegisterReadPort;kOr;kNot;kReduceOr`

这说明当前阻塞已经不是“有没有 addr==slot 的 point compare”，而是：

- `parsePointCond` 目前只认识 `Eq(addr, const)` 主导的 point-cond
- `uop_71_exceptionVec_0` 这组写侧 cond 更像一类 one-hot / reduce-or / old-value guard 组合
- 需要单独扩展 point-cond 归一化，或者引入新的写侧形态识别

## 6. 当前代码状态

本轮代码改动已通过本地回归：

- `cmake --build wolvrix/build --target transform-record-slot-repack`
- `ctest --test-dir wolvrix/build --output-on-failure -R transform-record-slot-repack`

并且 replay 已验证从：

- `0 -> 153 -> 176`

不是空转。

## 7. 下一跳建议

后续最值得继续追的，不是再泛泛扩写侧，而是继续定向打 `loadQueueReplay`：

1. 保留这次修掉的 `Value::users()` 生命周期修复，不要回退
2. 继续只盯 `_op_9413082`，把 `kRegisterReadPort;kOr;kNot;kReduceOr` 这一类 cond 归一化成可识别 point/fill 形态
3. 若这一类 cond 实际表达的是“部分 slot 不可写”，则考虑把缺失 slot 约束显式并入 unified memory write 的 guard

也就是：

- 现在已经证明方向对了
- `uop_*_pc` 已经拿下
- `uop_*_exceptionVec_0` 是下一轮最值得继续打的剩余大头
