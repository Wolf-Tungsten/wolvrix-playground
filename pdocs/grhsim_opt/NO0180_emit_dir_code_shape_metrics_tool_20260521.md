# NO0180 Emit-Dir Code-Shape Metrics Tool

日期：2026-05-21

## 目的

为 latest default 的 full emit/build/runtime 闭环补一个可复用静态 gate：

- 读取 `activity_schedule_supernode_stats.json`；
- 扫描 `grhsim_emit` 目录中的 `grhsim_*_sched_*.cpp`；
- 输出 sched 源码体积、文件数、行数和 storage-ref alias 计数；
- 用于判断 fresh emit 后是否真的回到 `NO0151` alias-off 代码形态，而不是只看结构 stats。

本次不启动 XiangShan fresh emit/build/runtime，只扩展已有工具并用历史产物回归验证。

## 改动

修改文件：

```text
scripts/grhsim_opt_metrics.py
```

新增参数：

```sh
--emit-dir <grhsim_emit_dir>
```

新增输出字段：

| 字段 | 含义 |
| --- | --- |
| `sched_cpp_files` | `grhsim_*_sched_*.cpp` 数量 |
| `sched_cpp_bytes` | 所有 sched C++ 总字节数 |
| `sched_cpp_lines` | 所有 sched C++ 总行数 |
| `sched_cpp_largest_file` | 最大 sched 文件名 |
| `sched_cpp_largest_bytes` | 最大 sched 文件字节数 |
| `sched_cpp_largest_lines` | 最大 sched 文件行数 |
| `state_ref_alias_count` | `auto &grhsim_state_` 出现次数 |
| `state_scalar_ref_alias_count` | `auto &grhsim_state_scalar` 出现次数 |
| `value_ref_alias_count` | `auto &grhsim_value_` 出现次数 |
| `storage_ref_alias_count` | state/value alias 总数 |
| `value_storage_ref_count` | `grhsim_value_storage_ref` 出现次数 |
| `slice_u64_words_count` | `grhsim_slice_u64_words` 出现次数 |
| `assign_words_count` | `grhsim_assign_words` 出现次数 |

## 验证

语法检查：

```sh
python3 -m py_compile scripts/grhsim_opt_metrics.py
```

结果：通过。

### NO0151 alias-off 回归

命令：

```sh
python3 scripts/grhsim_opt_metrics.py \
  --emit-dir tmp/no0151_xs_no_storage_ref_aliases/grhsim_emit \
  --stats tmp/no0151_xs_no_storage_ref_aliases/grhsim_emit/activity_schedule_supernode_stats.json \
  --pretty
```

关键输出：

| 指标 | 数值 |
| --- | ---: |
| `compute_supernodes` | `74430` |
| `dag_edges` | `485905` |
| `boundary_activation_edges` | `2216514` |
| `sched_cpp_files` | `994` |
| `sched_cpp_bytes` | `1788406953` |
| `sched_cpp_lines` | `17638469` |
| `state_ref_alias_count` | `0` |
| `state_scalar_ref_alias_count` | `0` |
| `value_ref_alias_count` | `0` |
| `storage_ref_alias_count` | `0` |
| `value_storage_ref_count` | `1850751` |
| `slice_u64_words_count` | `71059` |

`sched_cpp_bytes=1788406953` 与 `NO0173` 记录一致。

### NO0172 alias-on 回归

命令：

```sh
python3 scripts/grhsim_opt_metrics.py \
  --emit-dir tmp/no0172_xs_c2_full_valuefanout_fix_full/grhsim_emit \
  --stats tmp/no0172_xs_c2_full_valuefanout_fix_full/grhsim_emit/activity_schedule_supernode_stats.json \
  --pretty
```

关键输出：

| 指标 | 数值 |
| --- | ---: |
| `compute_supernodes` | `74430` |
| `dag_edges` | `485905` |
| `boundary_activation_edges` | `2216514` |
| `sched_cpp_files` | `994` |
| `sched_cpp_bytes` | `2696952102` |
| `sched_cpp_lines` | `30053927` |
| `state_ref_alias_count` | `1324984` |
| `state_scalar_ref_alias_count` | `1318475` |
| `value_ref_alias_count` | `3184814` |
| `storage_ref_alias_count` | `4509798` |
| `value_storage_ref_count` | `1324984` |
| `slice_u64_words_count` | `71059` |

`sched_cpp_bytes=2696952102`、`state_scalar_ref_alias_count=1318475` 和 `value_ref_alias_count=3184814` 与 `NO0173` 记录一致。

## 用法

下次 latest default fresh emit 后，应先运行：

```sh
python3 scripts/grhsim_opt_metrics.py \
  --emit-dir <fresh>/grhsim_emit \
  --stats <fresh>/grhsim_emit/activity_schedule_supernode_stats.json \
  --out <fresh>/code_shape_metrics.json \
  --pretty
```

静态 gate：

| 指标 | 期望 |
| --- | --- |
| `compute_supernodes` | `74430` 附近 |
| `dag_edges` | `485905` 附近 |
| `boundary_activation_edges` | `2216514` 附近 |
| `sched_cpp_bytes` | 接近 `NO0151` 的 `1788406953`，不能接近 `NO0172` 的 `2696952102` |
| `storage_ref_alias_count` | 应保持 `0` 或接近 alias-off 口径 |
| `state_scalar_ref_alias_count` | 不应回到百万级 |
| `value_ref_alias_count` | 不应回到百万级 |

如果这个静态 gate 失败，不应继续跑 50k；应先诊断 generated-code 形态。

## 结论

现在 latest default full emit 后的代码形态检查可以一条命令完成。这个工具补上了 `NO0178` 中指出的缺口之一：不再需要手工 `find/rg/wc` 才能判断 fresh emit 是否回到 alias-off 快档。

该工具仍不能替代 runtime gate；它只判断结构和生成代码形态是否具备进入 20k/50k 的前提。
