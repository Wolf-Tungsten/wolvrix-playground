# NO0063 Remove `record-slot-repack`

## 1. 背景

[`NO0061`](./NO0061_merge_reg_two_strategy_prune_20260503.md) 已将当前寄存器合并路径收敛到 `merge-reg` 的两个策略：

```text
scalar-to-memory
indexed-bundle-entry-to-wide-register
```

[`NO0062`](./NO0062_merge_reg_inline_scalar_to_memory_20260503.md) 又删除了独立 `scalar-memory-pack` pass，并把其实现内联到 `merge-reg`。

本轮继续清理旧实验性 pass：`record-slot-repack` 仍以独立 pass、独立源文件和独立测试目标存在，但当前 `merge-reg` 默认路径并不调用它，Python / grhsim 脚本也不再依赖它。

## 2. 调整

移除独立 `record-slot-repack` 组件：

- 从 `wolvrix/lib/core/transform.cpp` 删除 `record-slot-repack` include、`availableTransformPasses()` 条目和 `makePass()` factory 分支。
- 从 `wolvrix/CMakeLists.txt` 删除 `lib/transform/record_slot_repack.cpp` 源文件和 `transform-record-slot-repack` 测试目标。
- 删除：
  - `wolvrix/include/transform/record_slot_repack.hpp`
  - `wolvrix/lib/transform/record_slot_repack.cpp`
  - `wolvrix/tests/transform/test_record_slot_repack.cpp`

历史文档 [`NO0051`](./NO0051_record_slot_repack_replay_progress_20260430.md) 保留为当时实验记录，不回改历史结论。

## 3. 当前含义

从本记录之后，当前寄存器合并优化只通过 `merge-reg` 暴露；`record-slot-repack` 不再是可运行 pass，也不再构建独立测试。
