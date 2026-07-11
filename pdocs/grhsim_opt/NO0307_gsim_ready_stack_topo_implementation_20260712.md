# NO0307 GSim ready-stack topo implementation

日期：2026-07-12

## 1. 依据

承接 [NO0306](./NO0306_final_topo_level_op_overlap_negative_gate_20260712.md)。`level-op` 失败的主要边界是
完整 Kahn layer barrier，因此本轮直接对照 GSim：

- `reference/gsim/src/topoSort.cpp::graph::topoSort()`；
- `reference/gsim/src/graphPartition.cpp::graph::resort()`；
- `reference/gsim/include/common.h` 中默认启用的 `ORDERED_TOPO_SORT`。

GSim 先按 `SuperNode::id` 升序排列 roots 并依次压栈；每次弹出一个节点后，将 successors 按 ID 升序
扫描，入度刚降到零的节点立即压栈。由于栈是 LIFO，同一轮最后释放的较大 ID successor 会先执行，且
新 ready 节点可以在尚未处理的旧 root 之前执行，不存在完整 frontier barrier。

## 2. ready-op policy

activity-schedule 新增默认关闭的 `ready-op` final topo policy：

1. key 使用 supernode 内最小 `OperationId.index`，替代 GrhSIM 中不稳定的临时 supernode ID；
2. roots 按 key、再按 supernode ID 升序压栈；
3. 每个节点的 successors 按相同 key 升序扫描，入度归零后立即压栈；
4. 栈后进先出，精确保留 GSim 的 traversal 方向；
5. successor 越界、重复边导致的入度下溢、cycle 和 key 数量错误均显式失败。

XiangShan probe 通过已有入口开启：

```text
WOLVRIX_XS_GRHSIM_FINAL_TOPO_POLICY=ready-op
```

默认仍为 `level-id`；NO0306 失败的 `level-op` 也保留为诊断 policy，不改变现有产物。

## 3. Synthetic gate

单测构造三个单-op supernodes：独立 `A`、依赖链 `B -> C`，且 op ID 顺序为 `A < B < C`。

- layered policy 必须先完成同层 roots，再进入 `C`；
- `ready-op` 将 roots 升序压栈后先弹出 `B`，`B` 释放 `C` 后立即弹出 `C`，最后才执行 `A`；
- 因此 `ready-op` 与 `level-op` topo 必须不同，明确证明跨越完整 Kahn layer；
- 两者的 supernode/op map、DAG、value fanout、supernode kind、compute-node map 和 summary stats 必须
  完全一致。

测试还独立重放 ready-stack 算法，逐节点检查导出的 final topo。

## 4. 回归

```text
cmake --build wolvrix/build -j32 \
  --target transform-activity-schedule transform-pass-manager
ctest --test-dir wolvrix/build \
  -R '^(transform-activity-schedule|transform-pass-manager)$' \
  --output-on-failure
```

构建通过，定向 CTest `2/2` 通过。

## 5. 下一步

从固定 pre-reg-to-mem checkpoint 分别生成 strict 与 ordered `ready-op`。先要求各自结构与
NO0286/NO0300 完全一致，再用 NO0306 工具比较共同 op 的 batch overlap。只有 correlation、位移和 pair
locality 明显优于 `level-id`，才进入 emu 编译、10k/50k 功能和 fixed-CPU runtime gate。
