# NO0173 Same-Structure Runtime Gap Alias Codegen Diagnosis

日期：2026-05-21

## 目的

解释 `NO0172` 的关键现象：activity-schedule 结构已经恢复到 `NO0162/NO0171` 快档画像，但 20k runtime 仍明显慢。

本次不 fresh emit、不 rebuild、不 rerun，只用现有产物做静态诊断。

## 产物

对比对象：

```text
tmp/no0151_xs_no_storage_ref_aliases/grhsim_emit
tmp/no0162_xs_assign_fullword_fastpath/grhsim_emit
tmp/no0172_xs_c2_full_valuefanout_fix_full/grhsim_emit
```

注意：`NO0163` 已记录 `tmp/no0162_xs_assign_fullword_fastpath/grhsim_emit` 源码树被一次 `cp -al` no-fresh probe 污染过，因此 `NO0162` 源码树不能作为 pristine 生成源码基线。`NO0162` 的历史 archive/runtime 结果仍有效。

本诊断中，真正用于 clean generated-code 对比的是 `NO0151` 与 `NO0172`：

- 二者结构 JSON 完全一致。
- `NO0151` 是 clean fresh alias-off 产物。
- `NO0172` 是 C2 full + valueFanout fix 后的 fresh runtime gate 产物。

## 结构对齐

`NO0151`、`NO0162`、`NO0172` 的核心结构指标一致：

| 指标 | 数值 |
| --- | ---: |
| `supernodes` | `74945` |
| `compute_supernodes` | `74430` |
| `commit_supernodes` | `515` |
| `dag_edges` | `485905` |
| `boundary_values` | `1151073` |
| `boundary_activation_edges` | `2216514` |
| `compute_compute_value_pairs` | `1858400` |
| `compute_commit_value_pairs` | `358114` |
| `state_read_activation_edges` | `9367` |
| `constant_activation_edges` | `4749` |
| `other_compute_activation_edges` | `2202365` |
| `essent_small_sibling_merges` | `329802` |

结论：`NO0172` 的 runtime 回退不是 C2/C4 supernode DAG 结构造成的。

## 生成代码差异

sched `.cpp` 文件均为 `994` 个，但生成源码体积明显不同：

| 实验 | sched bytes | 目录大小 | 20k gate |
| --- | ---: | ---: | ---: |
| `NO0151` | `1788406953` | `1.7G` | `101232 ms` |
| `NO0172` | `2696952102` | `3.0G` | `129095 ms` |

`NO0172` 比 `NO0151` 多约 `908 MB` sched 源码，20k 慢约 `27.5%`。

关键静态计数：

| 指标 | `NO0151` | `NO0172` |
| --- | ---: | ---: |
| `auto &grhsim_state_scalar` | `0` | `1318475` |
| `auto &grhsim_value_` | `0` | `3184814` |
| `grhsim_slice_u64_words` | `71059` | `71059` |
| `grhsim_value_storage_ref` | `1850751` | `1324984` |
| `value_u8_slots_` | `1233814` | `2712613` |
| `value_u16_slots_` | `283466` | `596997` |
| `value_u32_slots_` | `62464` | `179967` |
| `value_u64_slots_` | `461835` | `1047186` |

`grhsim_slice_u64_words` 次数一致，说明 `NO0172` 的主要代码膨胀不是 slice-u64 helper 引入的；主要差异来自 per-supernode storage-ref alias 重新打开。

## 机制解释

`wolvrix/lib/emit/grhsim_cpp.cpp` 当前默认：

```text
WOLVRIX_GRHSIM_STORAGE_REF_ALIASES unset => enabled
WOLVRIX_GRHSIM_STATE_STORAGE_REF_ALIASES unset => enabled
WOLVRIX_GRHSIM_STORAGE_REF_ALIAS_MIN_TOUCHES unset => 2
```

`NO0151` 明确设置：

```text
WOLVRIX_GRHSIM_STORAGE_REF_ALIASES=0
```

`NO0172` 没有设置该变量，因此同一张 activity-schedule 图生成了大量入口 alias 声明。典型膨胀表现是大量：

```text
auto &grhsim_value_..._slot = value_*_slots_[...];
auto &grhsim_state_scalar_... = grhsim_value_storage_ref(...);
```

这些声明在 active supernode 入口处集中生成，增加源码体积、热函数体大小和 frontend 压力；这与早期 perf 结论中 `eval_commit_batch_*` / hot batch body frontend pressure 的方向一致。

## 结论

`NO0172` 已经排除了 C2/C4 结构问题：静态图恢复后 runtime 仍慢，是 emitter 生成代码形态回退造成的。

当前更精确的根因表述：

```text
grhsim 与 gsim 的主要差距不只是 activity-schedule supernode 图过大；
在结构恢复后，grhsim 仍会因为生成的 batch body 过大、alias 声明过多、
typed slot / generic storage access 形态不稳定而产生严重 frontend/code-layout 压力。
```

对当前工作区而言，直接性能对齐动作应该先恢复 `NO0151` 的 alias-off 快档：

```text
WOLVRIX_GRHSIM_STORAGE_REF_ALIASES=0
```

后续再做更细的 alias 策略时，必须以 `NO0151` 作为 clean 代码形态基线，而不是使用已污染的 `NO0162` 源码树。

## 下一步

建议将 XiangShan grhsim emit 脚本的默认运行口径改为 alias-off，或至少在主线实验命令中显式设置：

```text
WOLVRIX_GRHSIM_STORAGE_REF_ALIASES=0
```

验收方式：

- 不必再次 fresh emit 只为证明结构；结构已由 `NO0172` 证明。
- 若修改默认口径，需要一次 fresh emit/build/20k gate 验证生成代码重新回到 `NO0151` 级别。
- 20k gate 应接近 `NO0151/NO0152` 的 `~99-101s`，否则继续查 emitter 形态差异。
