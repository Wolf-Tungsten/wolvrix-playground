# NO0324 Batch dynamic-work profile tool plan

日期：2026-07-12

## 1. 目的

[NO0323](./NO0323_no0286_no0300_frontend_full_empty_profile_20260712.md) 已将 frontend full-empty
增量定位到 compute-wide 分布，但 old/new batch 内容广泛混排，直接比较同名函数无效。本阶段新增：

```text
scripts/grhsim_batch_profile_compare.py
```

将 generated batch、runtime dynamic work 和 perf exact-symbol samples 严格连接，按 samples/work 排序。

## 2. 输入与连接契约

每个 `--variant` 接收：

```text
NAME SOURCE_DIR STATIC_TSV FIRE_TSV PERF_REPORT
```

工具执行以下检查：

- 每个 `*_sched_*.cpp` 只能包含一个 compute/commit batch function；
- 从 `// Supernode N: run ...` 提取 batch→supernode 映射，禁止重复归属；
- static/fire TSV 继续复用 NO0311 的 schema、key-set、phase 和非负整数校验；
- generated supernode key 集合必须与 TSV 完全相等；
- perf report 中的 exact batch symbol 不得指向未知 generated batch；
- report 未出现的 generated batch按零 samples 处理，而不是误删该 batch。

## 3. 输出

每个 variant 输出 compute/commit phase 的 samples、period、fire、work 和 samples-per-billion-work，以及：

- top by samples；
- 设置最小样本阈值并按 compute/commit 分 phase 的 top by sample density；
- 全 batch 表；
- machine-readable JSON；
- candidate 与 baseline 的 phase sample/work density delta。

batch ID 仍只表示各自版本的 layout。工具不会把 old/new 同编号 batch 自动认作相同逻辑；跨版本逻辑映射继续
使用 `grhsim_compute_batch_overlap.py` 的稳定 op ID overlap。

## 4. 验证计划

1. `py_compile`；
2. 全量连接 NO0286 的 `67,934` 和 NO0300 的 `63,726` 个 supernodes；
3. phase work 必须精确复现 NO0312；
4. phase samples 必须精确复现 NO0323；
5. 检查 JSON、top density 和全 batch 行数。
