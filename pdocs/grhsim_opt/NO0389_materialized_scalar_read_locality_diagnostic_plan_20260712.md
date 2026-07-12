# NO0389 Materialized scalar read-locality diagnostic plan

日期：2026-07-12

## 1. 背景与目标

[NO0388](./NO0388_direct_state_read_instruction_profile_gate_20260712.md) 已确认 direct state-read 把 compute8 的
state-read 扫描基本清空，但 direct GrhSIM 仍执行约 `2.084x` GSim instructions。剩余第一热点为
`compute1=243`、`compute62=204` samples；两者的 generated C++ 中仍分别有 `107,121/73,469` 个 scalar
value-slot 文本引用，annotate 以分散的 `mov/or/cmp/setcc` 和 `lea/test/cmov/and` 为主。

本轮不重新打开 NO0151/NO0164 已证明负收益的全局 per-supernode `auto&` storage aliases，也不先修改生成代码。
先新增默认关闭的 emit-time 诊断，回答一个更窄的问题：active compute supernode 中，同一 materialized scalar slot
是否被多次只读，因而可能用一个 typed local copy 替代重复 slot load。

## 2. 候选定义

对每个 compute supernode，按实际会在 compute phase 发射的 operation 扫描 operands/results。value 先经
`canonicalMaterializedStorageValue` 归一，候选必须同时满足：

1. canonical value 是 materialized logic，且使用 scalar slot；wide words、real/string 和 state storage 不计；
2. operand touch 至少为 `2`，同一个 operation 中重复出现也按实际 operand 次数计；
3. 该 compute supernode 不产生同一 canonical value，避免 local copy 跨过写回；
4. direct state-read value 不计，因为其实际表达式已直接读取 state storage；
5. 被 phase 过滤或 reg-to-memory intent bypass 跳过的 operation 不计。

诊断按 canonical slot 聚合 alias operands，但同时保留 distinct operand value 数和 distinct use-op 数。这里的
`loads_saved_per_fire = operand_touches - 1` 只是源级理论上界；编译器可能已经 CSE/寄存器化部分 slot load，不能把它
直接解释为动态指令收益。

## 3. 输出与开关

新增 emit option/environment，均默认关闭：

```text
materialized_scalar_read_locality_stats=1
WOLVRIX_GRHSIM_MATERIALIZED_SCALAR_READ_LOCALITY_STATS=1
```

输出 `grhsim_materialized_scalar_read_locality.tsv`。每个重复只读 canonical slot 一行，至少包含：

```text
supernode_id, phase, batch_id, canonical_value_id, value_name, width, scalar_kind,
operand_touches, distinct_operand_values, use_ops, result_writes,
supernode_ops, loads_saved_per_fire
```

stderr 摘要同时给出 scanned compute supernodes、scalar operand touches、candidate rows、candidate touches 和
静态 `loads_saved_per_fire` 总和。开关关闭时不得生成 TSV，也不得改变任何 generated model C++。

## 4. Synthetic gate

单元测试至少覆盖以下四类：

1. 同一 materialized scalar 被同一 supernode 只读多次，产生一行候选且 `loads_saved_per_fire=touches-1`；
2. 只读取一次的 scalar 不产生候选；
3. 同一 supernode 内既读又写同一 canonical slot，不产生候选；
4. wide materialized value 和 direct state-read value 不产生候选。

还需验证 TSV schema/row width、默认关闭不产出文件，并运行 `emit-grhsim-cpp` CTest。诊断实现不得改变 synthetic
generated C++ 的内容。

## 5. SimTop 动态连接

在 editable Python emitter rebuild 后，对 NO0357 direct-state-read 配置做 fresh SimTop emit，并要求 schedule/IR
输入与该版本一致。静态 TSV 与已验证的 50k `grhsim_supernode_fire.tsv` 按 `(supernode_id, phase=compute)` 连接：

```text
weighted_touches = operand_touches * fire_count
weighted_saved_upper_bound = (operand_touches - 1) * fire_count
coverage = weighted_saved_upper_bound / weighted_touches
```

分别汇总全模型、touch threshold `2/3/4/8`、compute1、compute62，并列出 weighted-saved top supernodes/values。
如果旧 fire 文件的 schedule identity 不能逐项证明一致，则重建同配置 runtime-profile model 并做 50k 功能运行；性能
测试仍遵循机器负载门禁，诊断运行本身不作 wall-time 结论。

## 6. 决策门禁

只有同时满足以下条件，才进入默认关闭的 typed-local cache 实现：

1. compute1/62 确实有高动态权重候选，而不是静态大文件造成的文本计数假象；
2. 全模型 weighted saved upper bound 至少覆盖 candidate scalar operand touches 的 `10%`；
3. top 候选反汇编中仍能看到同一 slot 的重复 memory load，证明编译器没有已经完成等价 CSE；
4. 候选可在不改变写回、change detection 和 activation 顺序的前提下仅限于只读 supernode。

若任一项不满足，本方向以诊断否定结论收尾，不实现 codegen 优化，转向 NO0388 已量化的 commit 或其他 compute
结构差异。本篇只声明计划，尚未修改 emitter 或运行 SimTop 诊断。

## 7. 实施前口径修正

实现时发现，如果 TSV 只输出候选行，则 `(touches - 1) / touches` 对任意 `touches >= 2` 的候选天然不低于
`50%`，不能作为全模型覆盖率门禁。最终实现保留所有 materialized scalar operand-read 行，并增加
`candidate` 列：single-read 和同 supernode 写回分别以 `candidate=0` 留在表中，wide/direct-state 仍不进入
scalar-slot 行。这样动态连接可以使用全部 weighted scalar operand touches 作分母，原候选定义和
`loads_saved_per_fire` 公式不变。
