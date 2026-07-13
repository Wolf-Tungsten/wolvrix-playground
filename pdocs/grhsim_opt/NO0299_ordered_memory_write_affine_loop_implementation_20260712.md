# NO0299 Ordered memory-write affine-loop implementation

日期：2026-07-12

## 1. 目标

承接 [NO0298](./NO0298_ordered_memory_write_frontend_regression_diagnosis_20260712.md)，本阶段只改变 GrhSIM generated C++ 中大型 ordered scalar-memory write group 的控制流形态。ordered IR、priority rank、activity-schedule 原子组、SystemVerilog 顺序以及 reg-to-mem lowering 均不改变。

旧 emitter 即使已经收到完整 ordered group，仍为每个 writer 输出一个独立 outer guard。三组 RenameTable shadow memory 因此每周期依次穿过 `511 + 511 + 520 = 1,542` 个静态分支块。本实现把可证明安全且 slot 编号规则的子段改为少量 affine loops。

## 2. 严格匹配条件

首版 fast path 仅在以下条件全部满足时启用：

1. group 至少包含 `16` 个连续 memory write，所有操作具有相同 `priorityGroup`、memory symbol 和 exact event。
2. activity-schedule 中的顺序必须严格对应 priority `N-1, N-2, ..., 0`；即 low-to-high priority，最高优先级最后执行。
3. 每个 writer 在现有 `CommitWriteGuardGroup` 中仍是 singleton，且这些 singleton 连续；这保证折叠前后的相对位置与普通 write guard grouping 完全相同。
4. memory row width 为 `1..8` bits、row count 为不超过 `64` 的二次幂；condition/address/data 均存在已物化 scalar slot，condition 为 bool slot，address/data 为 u8 slot。
5. mask 必须是 constant all-ones，group 不含 fill；任一条件不满足都完整回退到现有逐 op emitter。
6. cond/address/data 三个 slot index 序列被切分为 affine ranges，并且 range 数不超过 writer 数的四分之一；不可有效压缩的组也回退。

该约束不从 symbol 名或 XiangShan 层次路径推断语义，fast path 由通用 ordered-write contract 和 generated-model 物化布局共同驱动。

## 3. 生成代码语义

每个 affine range 输出一个运行时循环，slot index 由 `base + step * index` 计算。循环仍按原 priority 顺序逐 writer 执行：

```text
if condition slot is false: continue
row = address slot & row_mask
next = truncated data slot
if state[row] changed:
    state[row] = next
    record changed row
```

state 在每个命中 writer 内立即更新，因此同地址的后续高优先级 writer 仍能观察并覆盖前一个值。reader activation 延迟到 group 末尾：用 64-bit bitmap 保存“本 group 中曾发生过变化”的 rows，再调用现有 row-aware activation。即使某 row 先改变后恢复初值，bitmap 仍保留该 row，与旧路径已经触发 reader 的行为一致。`touchedWriteCount` 继续按实际发生 state change 的 writer 递增。

普通 register/latch/memory writes、短 ordered groups、重复 guard groups、动态 mask、wide memory 和非二次幂 memory 的生成代码不变。

## 4. Synthetic 结构与执行 gate

新增 16-writer、4-row、8-bit ordered memory generated-model case。测试先用 compute assignments 物化每个 writer 的 condition/address/data，以覆盖 SimTop 使用的 slot-driven 路径。当前 allocator 在常量附近形成一个 slot 断点，因此 16 writers 被合法压成 `2 + 14` 两个 ranges；测试不假定具体断点数量，只要求进入 affine-loop 路径且不保留逐 writer commit bodies。

执行 harness 覆盖：

- 同地址：priority 15 的低优先级写入 `0x11`，priority 0 的高优先级写入 `0x22`，最终读回 `0x22`。
- 异地址：低/高优先级分别写 row 0/2，读回 `0x33/0x44`。
- 每次写入均通过动态 memory read 输出观察，覆盖 changed-row reader activation。

最终定向回归命令均先执行 `source env.sh`：

```text
cmake --build wolvrix/build --target emit-grhsim-cpp -j32
ctest --test-dir wolvrix/build -R '^emit-grhsim-cpp$' --output-on-failure
```

结果：

```text
emit-grhsim-cpp PASS 150.34 s
```

测试过程中，新 affine generated model 以 `clang++ -std=c++20 -O0` 完成 archive 与 harness 编译并执行通过；既有 reg-to-mem collision harness 等 emitter 回归也保持通过。

## 5. 下一步

本阶段只证明局部生成语义与结构，尚不宣称 SimTop 提速。下一 gate 从 NO0296 使用的同一 pre-reg-to-mem checkpoint fresh 生成并编译，检查三组 RAT 是否压成预期的四个主循环，随后执行 10k/50k difftest。功能通过后才进入固定 CPU old/new/old runtime gate。
