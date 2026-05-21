# NO0177 XS Default Structure Gate

日期：2026-05-21

## 目的

验证 `NO0174/NO0175` 之后，最新 `scripts/wolvrix_xs_grhsim.py` 的默认口径是否已经同时满足：

- activity-schedule 默认进入 C2 full 快档；
- XiangShan grhsim 默认关闭 per-supernode storage-ref alias；
- 不做 fresh emit/build/runtime，只用现有 `post_stats.json` 做 structure-only gate。

本次不是 fresh emit。目的只是避免在默认值还没确认时浪费一次完整 emit/build。

## 命令

输入 checkpoint：

```text
build/xs/grhsim/wolvrix_xs_post_stats.json
```

大小约 `2.9G`。

执行命令：

```sh
mkdir -p tmp/no0177_xs_default_structure_gate

WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1 \
WOLVRIX_XS_GRHSIM_POST_STATS_JSON=/home/gaoruihao/wksp/wolvrix-playground/build/xs/grhsim/wolvrix_xs_post_stats.json \
WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1 \
python3 scripts/wolvrix_xs_grhsim.py dummy.f SimTop tmp/no0177_xs_default_structure_gate/grhsim_emit '' '' info \
  > tmp/no0177_xs_default_structure_gate/structure.log 2>&1
```

产物：

```text
tmp/no0177_xs_default_structure_gate/structure.log
tmp/no0177_xs_default_structure_gate/grhsim_emit/activity_schedule_supernode_stats.json
```

## 默认口径

日志确认：

```text
enable_essent_mffc_build=True
enable_essent_coarsen=True
enable_essent_small_overlap_merge=False
enable_essent_down_merge=False
essent_small_sibling_max_preds=0
essent_small_sibling_candidate_budget=0
storage_ref_aliases=0(xs_default)
```

这说明脚本默认已经对齐到 `NO0171/NO0172` 的 C2 full 结构口径，并保留 `NO0174` 的 alias-off 代码形态默认值。

## Timing

| 阶段 | 时间 |
| --- | ---: |
| `read_json_file` | `21084 ms` |
| `pass activity-schedule` | `187083 ms` |
| `total` | `208167 ms` |

日志最后停在：

```text
stop after activity-schedule enabled
```

没有进入 C++ emit、build 或 runtime。

## 结构结果

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
| `memory_read_activation_edges` | `33` |
| `constant_activation_edges` | `4749` |
| `other_compute_activation_edges` | `2202365` |

关键 C2 指标：

| 指标 | 数值 |
| --- | ---: |
| `essent_single_parent_merges` | `305822` |
| `essent_small_sibling_merges` | `329802` |
| `essent_small_overlap_merges` | `0` |
| `essent_down_merges` | `0` |
| `essent_merge_rejected_size` | `0` |
| `essent_merge_rejected_cycle` | `25594` |
| `essent_merge_rejected_bounded` | `974070` |

结构已经恢复到 `NO0171/NO0172` 的快档：

```text
compute_supernodes=74430
dag_edges=485905
boundary_values=1151073
boundary_activation_edges=2216514
essent_small_sibling_merges=329802
```

## 结论

最新默认口径的 structure-only gate 通过：

1. 默认 activity-schedule 已回到 C2 full 快档。
2. 默认代码形态开关已保持 alias-off。
3. 本次只验证结构，不构成 runtime 闭环。

下一步需要在必须 fresh emit 时做完整闭环：

- fresh emit，确认默认日志仍一致；
- 检查 sched 源码体积和 alias 计数是否接近 `NO0151` alias-off；
- build difftest emu；
- 先跑 CoreMark 20k difftest gate；
- 20k 若接近 `~99-101s`，再跑 50k。

如果 20k 明显慢，不应直接跑 50k，应先诊断生成代码体积和 hot batch 代码形态。
