# NO0100: Per-Entry Commit Scalar Activation 候选实现

Date: 2026-05-21

## 背景

`NO0099` 已把 hot commit batch 的反汇编形态映射到生成代码：大量 inline register write 形成重复的
`cond -> changed -> supernode_active_curr_ |= mask` 模式。以 `sched_990` 为例，源码热段对应：

- 外层 homogeneous event guard。
- 每个 `kRegisterWritePort` 单独判断 condition。
- 计算 masked `next_value`。
- 状态改变后直接写 state，并逐条 OR reader activation masks。

这解释了 hot commit batch 的 branch-dense / memory-dense 形态，也比“单个函数太大”更贴近当前 10x gap 的代码生成根因。

## 静态诊断

对 no0162 已生成 hot commit 文件做只读扫描：

| 文件 | inline write blocks | 长 run | 代表 run | avg activation entries | union entries | 结论 |
| --- | ---: | ---: | --- | ---: | ---: | --- |
| `sched_990` | 1354 | 10 | len=701 | 5.00 | 461 | union 会明显过激活 |
| `sched_951` | 4020 | 1 | len=4020 | 2.00 | 1169 | union 极不合适 |
| `sched_977` | 1085 | 17 | len=514 | 3.46 | 196 | union 仍偏大 |

因此本轮没有做 union activation table。新候选是 per-entry activation table：每个 table entry 保留自己的 activation slice，只有该 entry 对应 state 真的改变时才激活自己的 reader set。

## 实现口径

新增默认关闭开关：

- emitter option: `emit_per_entry_commit_scalar_activations`
- C++ env: `GRHSIM_EMIT_PER_ENTRY_COMMIT_SCALAR_ACTIVATIONS`
- XS 脚本 env: `WOLVRIX_XS_GRHSIM_EMIT_PER_ENTRY_COMMIT_SCALAR_ACTIVATIONS`

实现点：

- `DirectCommitScalarStateWriteDesc` 增加 `activationOffset` / `activationCount`。
- `canUseDirectCommitScalarTableRun` 增加 `allowDistinctActivationEntries`，新开关打开时允许同一 event run 中 activation set 不同的 scalar commit writes 进入 table。
- helper 使用 `activationMaskCount == SIZE_MAX` 作为 per-entry 模式标记。
- per-entry 模式下，每个 entry 状态改变后立即调用 `apply_commit_activation_masks(activationMasks + entry.activationOffset, entry.activationCount, ...)`。
- 旧 common activation table / specialized table / inline table 路径默认不变。
- `WOLVRIX_GRHSIM_DIAG_COMMIT_SCALAR_TABLE=1` 诊断新增 `table_runs`、`table_writes`、`per_entry_runs`、`per_entry_writes`、`per_entry_activation_entries`，用于 fresh emit 后先看结构命中。

## 验证

已执行：

```sh
cmake --build wolvrix/build --target core-toposort
cmake --build wolvrix/build --target emit-grhsim-cpp
ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'
```

结果：

- `core-toposort` 编译通过，覆盖 `wolvrix-lib` / `grhsim_cpp.cpp`。
- `emit-grhsim-cpp` 编译通过。
- `emit-grhsim-cpp` CTest 通过，最终复跑耗时 `57.70 sec`；新增小测试覆盖新开关下 descriptor 字段与 helper 生成可编译，但该小设计不保证命中真实 per-entry activation table。
- 当前 CMake build 未启用 Python package target，`wolvrix_python` 不存在；pybind 参数入口已做源码贯通检查，但未在本配置下编译。

## 未完成

本轮没有 fresh emit XiangShan，也没有做 runtime 复测。原因是该步骤目标是先把 root-cause 映射到最小生成器候选，并用小测试验证生成语义。

下一步应做 low-cost 结构验证优先：

- 先做 XS fresh emit 的结构统计，不急于 build/runtime：统计 `PerEntryActivations` 命中数、被 table 化的 commit scalar writes 数、hot `sched_990/951/977` 是否从 inline write 转为 table。
- 若结构命中充分，再做完整 build/runtime；因为这是 emitter 新开关，进入 XiangShan 时必须 fresh emit。
