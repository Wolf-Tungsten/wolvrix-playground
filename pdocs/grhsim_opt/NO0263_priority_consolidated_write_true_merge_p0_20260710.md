# NO0263 Priority consolidated-write true-merge P0

日期：2026-07-10

## 目的

落实 [NO0262](./NO0262_multi_write_true_merge_plan_20260710.md) 的 P0：在小型 4-row
design 上证明 scalar register array 的 `updateCond=OR(branches)` 与
`nextValue=nested mux(branches)` 可以安全转置为多个动态 `kMemoryWritePort`。

本阶段只完成 write-side synthetic matcher 和 collision/reset gate，尚未让 PHR 进入 true
candidate discovery，也没有完整 SimTop 性能数据。

## 首次实现失败

第一版直接把每行的两个独立 `kRegisterWritePort` 聚合为两个 `kMemoryWritePort`，并按原
operation 创建顺序生成端口。IR shape test 通过，但执行级 harness 失败：activity-schedule
生成的 commit batch 先执行第二端口、再执行第一端口，同地址 collision 最终得到低优先级
数据。

该结果说明：

- operation 创建顺序不是 memory write priority contract；
- `kRegisterWritePort`/`kMemoryWritePort` 的优先级应由外部 mux/guard 显式表达；
- 不能通过调整端口生成顺序掩盖问题。

因此最终实现不再从多个独立 register write port 推断 priority。此类输入仍走原有保守失败
路径，不发生 true merge。

## 最终实现

新增 strict consolidated-write matcher，要求每行只有一个 scalar write port，并同时证明：

1. `nextValue` 是至少两层的 nested `kMux`；
2. mux 的每个 branch guard 都恰好出现在 `updateCond` 的 OR 叶子中；
3. 每个 branch guard 包含一个 `addr == row` 正等式；
4. priority exclusion 只允许形如 `!(higher_addr == row)` 的行相关负等式；
5. 去掉行常数后，同一 branch 的 addr、data、mask、event、common terms 与 conflict addr
   集合在所有行完全一致；
6. OR 中至多剩一个 reset guard，且所有 regular branch 都包含该 reset 的否定；
7. reset fallback 在各行一致或可打包为 per-row fill data。

rewrite 将 `!(higher_addr == row)` 转置为：

```text
!(higher_addr == current_addr)
```

并加入对应 memory write guard。这样高低优先级端口同地址时只有高优先级端口可写，最终
结果不依赖 activity-schedule 的端口排列。1-bit 非常量 reset mask 会并入 fill guard；更宽
的非全掩码 reset 继续保守拒绝。

## Synthetic gate

新增/扩展测试覆盖：

- 两个动态地址、nested mux 明确优先级；
- 同地址 collision 时高优先级数据覆盖；
- 不同地址时两个端口可在同一边沿分别更新；
- consolidated reset OR leaf；
- per-row 不同 reset fallback 生成 packed `kMemoryFillPort`；
- 旧 single-write、multi-anchor、独立 reset 与 compound reset 用例不回退。

验证命令均先执行 `source env.sh`：

```text
cmake --build wolvrix/build --target transform-reg-to-mem emit-grhsim-cpp -j8
ctest --test-dir wolvrix/build --output-on-failure -R '^transform-reg-to-mem$'
ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'
```

结果：

- `transform-reg-to-mem`：PASS；
- `emit-grhsim-cpp`：PASS，完整测试 `157.80s`；
- 新 generated-model collision harness：PASS。

## PHR 结构补充

解析当前 pre-reg-to-mem JSON 中 `phr_0/phr_1` 后确认，每行 write 的结构为：

- update OR：`reset + 41` 个 regular branch；
- next mux chain：`41` 个 branch，fallback 为 reset value；
- branch guard 中的 row equality 与 priority exclusion 符合本阶段 matcher 的目标形态；
- PHR 读侧不是简单单元素 slice，而是多个 `{phr, phr}` circular-window concat，且 register
  read 有共享用户。

因此下一步需要独立的 true-only shared-read/storage discovery；默认 intent discovery 继续
保持 [NO0205](./NO0205_reg_to_mem_single_user_correct_mode_20260623.md) 的 single-user 规则，
失败 candidate 不写任何 intent attrs。
