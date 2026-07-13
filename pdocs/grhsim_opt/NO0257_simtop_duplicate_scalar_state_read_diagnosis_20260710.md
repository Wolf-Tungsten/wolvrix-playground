# NO0257 SimTop duplicate scalar state-read diagnosis

日期：2026-07-10

## 背景

[NO0256](./NO0256_full_mask_register_commit_specialization_20260710.md) 把 SimTop 50k
的 commit 绝对时间从约 `66.33s` 降到 `40.72s`，compute 绝对时间则基本保持在
`65.50s`。优化后的 profile 中，`eval_compute_batch_7()` 以 `3.00%` 成为最大单一
热点。本轮从该 batch 的生成 C++、机器码和 perf sample 反查 compute 侧的额外工作。

基线模型：

```text
build/xs_grhsim_no0255_full_mask_commit_20260710/grhsim
```

## batch 7 静态结构

文件：

```text
build/xs_grhsim_no0255_full_mask_commit_20260710/grhsim/grhsim_emit/grhsim_SimTop_sched_7.cpp
```

normal compute 函数的主要规模为：

| 指标 | 数值 |
| --- | ---: |
| 源码行数 | `414303` |
| operation comments | `83158` |
| `kRegisterReadPort` | `69706` |
| supernodes | `984` |
| `eval_compute_batch_7()` text size | `0x1c5950` |

该文件不是被单个除法或单个宽运算主导，而是包含大量标量寄存器读取及其
`old_slot != state` changed check。

## perf sample 到源码的映射

原始 profile：

```text
build/logs/xs_perf/no0255/grhsim_full_mask_commit_simtop_50k_cycles.data
build/logs/xs_perf/no0255/grhsim_full_mask_commit_compute_batch_7.annotate
```

为避免用优化后二进制地址近似匹配源码，本轮以完全相同的 `-O3` 参数额外生成
line-table object：

```text
build/xs_grhsim_no0255_full_mask_commit_20260710/grhsim/grhsim_emit/grhsim_SimTop_sched_7.debug.o
build/logs/xs/no0257_simtop_sched7_debug_compile_20260710.log
```

原 object 与 debug object 的 `.text` SHA256 均为：

```text
865ac0bf76197f25be0cfe6698a35489555ea4d0c2a5a19014213deaa2672076
```

映射产物：

```text
build/logs/xs_perf/no0255/grhsim_full_mask_commit_compute_batch_7_sample_lines.tsv
build/logs/xs_perf/no0255/grhsim_full_mask_commit_compute_batch_7_sample_ops.tsv
```

batch 7 只有约 `320` 个 99 Hz sample，不能把小比例差异当成精确统计，但大类分布
足够明确：

| sample 分类 | 占比 |
| --- | ---: |
| 映射到 `kRegisterReadPort` | `82.81%` |
| 映射到顶层 `timer` read | `40.61%` |
| runtime inline unsigned-divide 行 | `10.23%` |
| 直接映射到 `kDiv` | `2.79%` |

因此 division 不是唯一根因；重复 state-read changed check 才是该热点最集中的代码形态。

## 重复读取计数

计数口径只包含 compute phase 中需要 materialize 和 changed detection 的 scalar
register/latch read，并以 `(supernode, state symbol)` 去重。event value 和宽值不纳入。

batch 7 中：

| 指标 | 数值 |
| --- | ---: |
| scalar read comments | `69706` |
| unique `(supernode, state)` | `29927` |
| duplicate reads | `39779` |
| materialized `timer` reads | `32523` |
| `timer` unique groups | `547` |
| `timer` duplicate checks | `31976` |

扩展到 66 个 normal compute batch：

| 指标 | 数值 |
| --- | ---: |
| tracked scalar reads | `121088` |
| unique `(supernode, state)` | `84517` |
| duplicate changed checks | `36571` (`30.20%`) |

明细：

```text
build/logs/xs/no0257_compute_scalar_state_read_duplicate_counts_20260710.txt
```

## 与 GSIM 的语义区别

这不是 FIR 中凭空多出 `36571` 次语义读取。GSIM/GrhSIM 都需要这些使用点，但 GrhSIM
把跨边界读取 materialize 到多个独立 value slot；旧 emitter 对同一 supernode 内同一
state 的每个 slot 都重新计算 changed predicate。

不能直接合并 slot：不同 read result 可能拥有不同 consumer/fanout，跨 supernode 的消费
也要求各 slot 保持可见。可以复用的只有 changed predicate，依据如下：

1. 同一 supernode 的 operations 总是一起执行；
2. 同 state 的 scalar read slots 在初始化后一起从同一 state 赋值，因此保持同步；
3. 所以它们的 `(old_slot != state)` 结果相同；
4. 每个 slot 的赋值和 changed effects 仍必须分别保留。

## 结论

下一步不调整分区和拓扑，也不重新启用已证明不利的 global storage alias。只在单个 compute
supernode 内缓存同一 state 的 scalar changed predicate，同时保留每个 read result 的独立
slot 写回及 fanout effects。该变换的实现和 runtime gate 见
[NO0258](./NO0258_scalar_state_read_change_predicate_reuse_20260710.md)。
