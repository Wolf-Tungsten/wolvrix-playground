# NO0291 Ordered memory-write contract plan

日期：2026-07-11

## 1. 问题收敛

[NO0290](./NO0290_rename_table_write_only_fresh_regression_20260711.md) 证明 write-only discovery 与 memory state 功能正确，但当前 consolidated lowering 用显式 conflict guard 保证端口优先级。对 `N` 个 priority writers，第 `i` 个低优先级端口需要排除所有更高优先级同地址 writer，冲突项总数接近：

```text
intRat: 511 * 510 / 2 = 130,305
fpRat : 511 * 510 / 2 = 130,305
vecRat: 520 * 519 / 2 = 134,940
total                     395,550
```

每个冲突项至少重建地址 equality、enable conjunction、negation，并参与最终 guard AND chain。该近二次网络与 fresh 相对 baseline 新增约 `1.99 M` graph ops、`198 MB` generated C++ 的量级一致。

## 2. GSim 对照

同 FIR GSim 的 `SimTop278.cpp/SimTop279.cpp` 不生成 pairwise conflict：

```cpp
if (write_0_enable) next[write_0_addr] = write_0_data;
if (write_1_enable) next[write_1_addr] = write_1_data;
// ...
if (write_519_enable) next[write_519_addr] = write_519_data;
```

write port 按低编号到高编号执行，后写覆盖前写。scalar RTL 的 priority chain 则从高编号端口向低编号端口排列，二者在同地址 collision 时语义一致；不同地址 writer 仍可在同一 cycle 全部生效。

## 3. 不能依赖普通 operation 顺序

[NO0263](./NO0263_priority_consolidated_write_true_merge_p0_20260710.md) 的执行 harness 已证明 activity-schedule 可能改变普通 memory write operation 的执行顺序。仅反转 `createOperation()` 顺序会再次掩盖问题，不能作为修复。

因此本阶段定义显式 ordered-write contract：

- 同一 `kMemory`、同一 event family 的 `kMemoryWritePort` 可带 `memoryWrite.priorityGroup` 与 `memoryWrite.priority` attrs。
- 同组 priority 必须唯一且连续，`0` 表示最高优先级。
- commit 时按 priority 从大到小执行，使 priority `0` 最后写入；同地址时最高优先级获胜，不同地址时所有 enabled writes 均生效。
- activity-schedule 必须把同组端口放入同一 commit cluster，并显式排序。
- SystemVerilog emitter 必须把同组语句放在同一 event block 中并按相同顺序输出。
- reg-to-mem 只有在完整 consolidated matcher 已证明 addr/data/mask/event/common terms/conflicts/reset 后，才能用该 contract 替代显式 conflict guard。

## 4. 实施与门禁

1. 为 reg-to-mem 增加默认关闭的 ordered-write 选项；仅 GrhSIM SimTop flow 默认启用，并保留环境回退。
2. ordered lowering 保留 own enable/common terms 与 storage domain guard，不物化 pairwise conflicts；write op 写入 group/priority attrs。
3. activity-schedule 校验 group 完整性、memory/event 一致性和 priority 连续性，并按低到高优先级 commit。
4. SystemVerilog emitter 同样按 attrs 排序，避免该 IR 只在 GrhSIM 下有正确语义。
5. synthetic shape gate 要求 conflict network 消失；generated-model harness 同时覆盖同地址 collision 与不同地址并行写。
6. SimTop 先跑 pre-sched 静态 gate，目标是 graph ops、generated C++、text 和 supernodes 至少不再高于 NO0286；静态门禁通过后再做 10k/50k 与固定 CPU old/new/old。
