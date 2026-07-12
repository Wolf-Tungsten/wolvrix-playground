# NO0390 Materialized scalar read-locality diagnostic implementation gate

日期：2026-07-12

## 1. 实现范围

按 [NO0389](./NO0389_materialized_scalar_read_locality_diagnostic_plan_20260712.md)，nested `wolvrix` commit
`87d67ee` 新增默认关闭的 emit-time 诊断：

```text
option: materialized_scalar_read_locality_stats=1
env:    WOLVRIX_GRHSIM_MATERIALIZED_SCALAR_READ_LOCALITY_STATS=1
output: grhsim_materialized_scalar_read_locality.tsv
```

writer 只遍历 compute batches 中实际属于 compute phase、且未被 reg-to-memory intent bypass 的 operations。operand
先按 canonical materialized slot 聚合；direct state-read、wide words、input/local/non-materialized value 均不进入
scalar 表。同一 canonical slot 在 supernode 内出现 result write 时仍记录该行，但标记 `candidate=0`。

## 2. TSV schema

输出共 17 列：

```text
supernode_id phase batch_id canonical_value_id canonical_value_generation value_name
width scalar_kind slot_index operand_touches distinct_operand_values use_ops result_writes
supernode_ops emitted_compute_ops candidate loads_saved_per_fire
```

所有 materialized scalar operand-read 行都保留，支持按 `(supernode_id, phase)` 与 runtime fire 连接。只有
`operand_touches >= 2 && result_writes == 0` 时 `candidate=1`，此时
`loads_saved_per_fire=operand_touches-1`；其他行的 saved 为 0。stderr 另给出 supernodes、read rows、全部 scalar
touches、direct-state skipped touches、candidate rows/touches 和静态 saved 总和。

该口径修正了原计划只输出候选行时的分母偏差：SimTop 可以计算
`weighted_saved / all_weighted_scalar_touches`，而不是候选集合内天然至少 50% 的比例。

## 3. Synthetic 结构门禁

新增同一张两级计算图，分别以 coarsened 和 `maxOpInComputeSupernode=1` 发射：

| Case | touches | writes | candidate | saved/fire |
| --- | ---: | ---: | ---: | ---: |
| coarsened repeated scalar | 2 | 1 | 0 | 0 |
| split repeated scalar | 2 | 0 | 1 | 1 |
| split single-read scalar | 1 | 0 | 0 | 0 |

同图中的 72-bit repeated value 不产生 scalar row。诊断关闭时不生成 TSV；对 split 图逐文件比较全部 generated
`.hpp/.cpp`，开关前后内容完全一致。

既有 repeated state-read 图在 baseline 下得到 4 个 canonical candidates：touches 为 `3/4/4/4`，合计 15，
`loads_saved_per_fire=11`。打开 direct single-writer state-read 后 TSV 只有表头，证明已直读 state storage 的 15 个
operand 不会被错误计为 scalar slot 候选。

## 4. 构建与回归

所有命令均先执行 `source env.sh`：

```text
cmake --build wolvrix/build --target wolvrix-lib -j$(nproc)          PASS
cmake --build wolvrix/build --target emit-grhsim-cpp -j$(nproc)     PASS
ctest --test-dir wolvrix/build -R '^emit-grhsim-cpp$' --output-on-failure
1/1 PASS, 170.00 s
```

本阶段没有运行 SimTop，也没有启用任何 codegen 优化。下一步先重建 editable Python emitter，再对 NO0357 direct
配置做 fresh emit；只有 schedule identity 和 generated model identity 门禁通过后，才把静态 TSV 与 50k fire
连接并评价覆盖率。
