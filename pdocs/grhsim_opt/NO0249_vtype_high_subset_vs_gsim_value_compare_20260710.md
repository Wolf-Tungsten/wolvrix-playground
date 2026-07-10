# VtypeBuffer high fullpass vs GSIM subStep1 value-family compare

## 背景

`NO0247` 判断：`XsReal075RobVtypebufferLarge` 的 GrhSIM high phase 若只做 whole-supernode 级 post-commit subset，静态闭包仍覆盖 `30/38` 个 compute supernode，源码行数约 `76%`，预计收益有限。本文继续按用户建议“对照 GSIM 看 GrhSIM 具体多了什么”，直接比较：

- GSIM `subStep1()`；
- GrhSIM `posedge_fullpass` 中 `eval_commit_batch_4()` 后调用的 `eval_compute_batch_0..3_fullpass()`。

本文只做临时生成物静态分析和 generated C++ probe，不修改仓库源码。

主要产物：

```text
tmp/no0249_value_name_compare_20260710/
tmp/no0249_high_subset_probe_20260710/
tmp/no0249_baseline_rebuild_20260710/
```

所有命令均先执行：

```bash
source env.sh
```

## 静态代码规模对照

使用 `tmp/no0246_best_vs_gsim_20260709/build/XsReal075RobVtypebufferLarge` 中的成对生成物解析：

- GSIM: `gsim/model/XsReal075RobVtypebufferLarge1.cpp`
- GrhSIM: `grhsim/model/grhsim_XsReal075RobVtypebufferLarge_sched_*.cpp`

关键统计：

| scope | nonempty lines | assign-like | helper calls | slot/ref | changed checks |
| --- | ---: | ---: | ---: | ---: | ---: |
| GSIM `subStep1()` | `4654` | `1320` | `0` | `0` | `0` |
| GrhSIM high commit batch | `1491` | `768` | `113` | `165` | `0` |
| GrhSIM high fullpass compute | `8476` | `5156` | `421` | `2859` | `612` |

直观看，GrhSIM high compute 的源码工作量和赋值数量远高于 GSIM `subStep1()`；即便已经走 fullpass 跳过 compute-to-compute active propagation，仍保留大量：

- `value_*_slots_` / `state_logic_storage_` 间接访问；
- `grhsim_*` helper 调用；
- `grhsim_changed_*` changed check；
- wide words 的 slice/assign/helper 形态。

## value-family / entry-index 对照

按 `data_N` / `meta_N` / `tags_N` 家族粗略比较 GSIM `subStep1()` 与 GrhSIM high fullpass 中出现的 entry index。

GSIM `subStep1()`：

```text
data: refs=182 unique_indices=22
meta: refs=159 unique_indices=23
tags: refs=168 unique_indices=28
```

GrhSIM high fullpass：

```text
data: refs=112 unique_indices=32
meta: refs=112 unique_indices=32
tags: refs=144 unique_indices=48
io_in: refs=78 unique_indices=6
io_ctrl: refs=67
touchBits: refs=48 unique_indices=48
```

GrhSIM high fullpass 中出现、但 GSIM `subStep1()` 中没有出现的 index：

```text
data: [2, 5, 8, 29, 32, 35, 38, 41, 44, 47]
meta: [3, 6, 9, 30, 33, 36, 39, 42, 45]
tags: [2, 3, 5, 6, 8, 9, 27, 29, 30, 32, 33, 35, 36, 38, 39, 41, 42, 44, 45, 47]
```

另外，GSIM `subStep1()` 中基本没有 `io_in*`，而 GrhSIM high fullpass 的大 supernode 仍会读取 `io_in0/io_in4/io_in5` 并重算 `requestTag` / input-derived probe 值。这说明 GrhSIM high fullpass 不只是 post-commit settle，还复跑了大量 pre-edge/input cone。

## GrhSIM high fullpass supernode 分类

把 GrhSIM high fullpass 的 `38` 个 compute supernode 按其 register-read comment 与 GSIM `subStep1()` index 集合粗分：

| class | supernodes | lines | assigns | helpers | changed checks | 说明 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `only_indices_seen_in_gsim_subStep1` | `5` | `1452` | `989` | `115` | `66` | 寄存器读 index 完全出现在 GSIM `subStep1()` 中 |
| `mixed_absent_and_overlap_indices` | `17` | `3429` | `2177` | `222` | `247` | 同一 supernode 内混合 post-commit index 与 GSIM `subStep1()` 未出现 index |
| `no_regread_or_input_cone` | `16` | `3563` | `1978` | `84` | `299` | 无 register-read comment 或偏 input/precompute cone |

比例：

```text
only_indices_seen_in_gsim_subStep1: 17.20% lines
mixed_absent_and_overlap_indices:   40.61% lines
no_regread_or_input_cone:           42.20% lines
```

几个代表 supernode：

- `SN3`：`931` 行，`463` 个 assign，`117` 次 `io_*` 引用；主要从 `io_in0/io_in4/io_in5` 生成大量 bool slice、`requestTag`、`_tagProbe_T_*` 等 input-derived 值。
- `SN1`：`545` 行，`271` 个 assign；同样从 `io_in0/io_in1` 生成 `requestTag` 和 tag probe 常量/派生值。
- `SN33`：`335` 行，宽 `std::array<uint64_t,16>` concat/slice 形态，虽然无直接 register-read comment，但依赖前面 value slots。

这解释了为什么 `NO0247` 的 whole-supernode closure 不够好：GrhSIM 的 supernode 内部已经把 pre-edge/input cone、post-commit cone、以及不同 entry-index 家族混在一起。要接近 GSIM `subStep1()` 的规模，必须进一步做 value/phase 级裁剪，而不是只裁 supernode。

## generated C++ whole-supernode high subset probe

为了验证 `NO0247` 的静态上限，本轮做一个临时 generated C++ patch：

1. 复制 4 个 `eval_compute_batch_N_fullpass()`，新增 `eval_compute_batch_N_highsubset()`。
2. 只在 posedge fast path 中把 high compute 调用改为 `_highsubset()`；input-low fastpath 仍调用原 `_fullpass()`，避免破坏 low/input settle。
3. 按 `NO0247` 的 static closure `[4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,21,22,24,25,26,27,28,29,30,31,32,33,34,35,36]` 生成 mask：

```text
batch0 mask = 240  # keep 4..7, skip 0..3
batch1 mask = 255  # keep all 8..15
batch2 mask = 87   # keep 16,17,18,22,21; skip 19,20,23
batch3 masks = 255,31  # keep 24..36, skip 37
```

patch 后 200k verify：

- log: `build/logs/xs/no0249_vtype_high_subset_bench_20260710.log`

结果：

```text
[VERIFY] top=XsReal075RobVtypebufferLarge vectors=200000 status=pass
[BENCH] model=grhsim ... ms=329.836 checksum=0x7d62abe96844fe00
```

同源 baseline copy 相邻重建/运行：

- log: `build/logs/xs/no0249_vtype_baseline_rebuild_bench_20260710.log`

```text
[VERIFY] top=XsReal075RobVtypebufferLarge vectors=200000 status=pass
[BENCH] model=grhsim ... ms=334.123 checksum=0x7d62abe96844fe00
```

单次 200k 约 `-1.28%`。

## grhsim-only 长窗口 repeat

为了降低噪声，跑 `--model grhsim --vectors 1000000 --verify 0 --repeat 5`，并交替重跑 baseline / highsubset：

- log: `build/logs/xs/no0249_vtype_high_subset_grhsim_only_repeat_20260710.log`

结果：

| run | min_ms | median_ms |
| --- | ---: | ---: |
| baseline | `1672.942` | `1677.034` |
| highsubset | `1661.972` | `1663.453` |
| baseline rerun | `1667.950` | `1670.007` |
| highsubset rerun | `1643.011` | `1644.694` |

收益大约 `0.7%~1.5%`，存在一定机器噪声，但量级明显很小。

运行时 load 约 `19~23 / 384`，不算高。

## phase profile

再用 `--grhsim-phase-profile` 跑 200k：

- log: `build/logs/xs/no0249_vtype_high_subset_phase_profile_20260710.log`

结果：

| variant | bench ms | measured_ms | low_eval_ms | high_eval_ms | high ns/vector |
| --- | ---: | ---: | ---: | ---: | ---: |
| baseline | `370.993` | `350.619` | `146.408` | `194.178` | `970.9` |
| highsubset | `361.190` | `340.785` | `152.673` | `178.168` | `890.8` |

high phase 自身约 `-8.24%`，但 low phase 略升，整体 measured 只约 `-2.80%`。这进一步说明 whole-supernode high subset 的收益被以下因素稀释：

- low/input fullpass 仍占大量时间；
- batch1 全保留，batch3 几乎全保留；
- 新增 highsubset 函数使 binary 中 fullpass/highsubset 符号总尺寸增大，可能带来代码布局/I-cache 副作用；
- 被跳过的 supernode 虽源码行多，但不一定是最高动态成本部分。

符号大小也印证这一点：

```text
baseline fullpass total symbols: 36926 bytes
highsubset fullpass+highsubset symbols: 68760 bytes
batch0: 5056 -> 2322 bytes
batch2: 8010 -> 4757 bytes
batch3: 19296 -> 20191 bytes  # 只少跳过 SN37，且复制/布局后略大
```

## 结论

1. GrhSIM high fullpass 相比 GSIM `subStep1()` 的额外工作不是单纯“多跑几个 supernode”，而是 supernode 内部混入大量 input/pre-edge value、额外 entry-index 家族、slot/ref 间接、changed check 和 wide helper 形态。
2. Whole-supernode high subset 功能可行，200k verify 通过；但即使按 `NO0247` closure 跳过 `0,1,2,3,19,20,23,37`，长窗口收益也只有约 `1%` 量级，phase profile 中 high phase 约 `-8%`。
3. 这条结果支持 `NO0247` 的判断：后续若要继续缩小 `1.5x` gap，应做 value/phase 级裁剪，而不是工程化 whole-supernode high subset。

## 下一步

推荐继续沿两个方向之一推进：

1. **value/phase 级 post-commit 裁剪**：在 compute node / value dependency 层标记哪些 value 是 input-low 已稳定且 high phase 不必重算，生成 high-only value subset，而不是复制整 supernode。
2. **slot/ref 和 changed-check 形态优化**：即便 fullpass 下仍有 `value_*_slots_` 间接和 `grhsim_changed_*` 检查；如果 high/low 都必须 fullpass，则减少每个 value 的固定开销可能比裁掉少量 supernode 更有效。

当前不建议把 whole-supernode high subset 作为默认实现或正式 emitter 特性。
