# NO0175 XS GrhSIM C2 Full Default

日期：2026-05-21

## 目的

补齐 `NO0174` 只修 emitter 代码形态默认值的问题：XiangShan grhsim 脚本的 activity-schedule 默认值也必须对齐到已经验证过的 C2 full 结构快档，否则后续 fresh emit 仍可能回到 `NO0154/NO0170` 的高 BAE 慢结构。

本次只修改 XS 脚本默认口径，仍保留所有环境变量显式覆盖。

## 改动

修改文件：

```text
scripts/wolvrix_xs_grhsim.py
```

默认值调整：

| 环境变量 | 旧默认 | 新默认 | 依据 |
| --- | ---: | ---: | --- |
| `WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD` | `0` | `1` | `NO0171/NO0172` |
| `WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN` | `0` | `1` | `NO0171/NO0172` |
| `WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_MAX_PREDS` | `1` | `0` | C2 full |
| `WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_CANDIDATE_BUDGET` | `250000` | `0` | C2 full |
| `WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE` | `1` | `0` | 当前主线关闭 |
| `WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE` | `1` | `0` | 当前主线关闭 |

`enable_essent_single_parent_merge` 和 `enable_essent_small_sibling_merge` 保持默认 `1`。

## 依据

`NO0171` 已证明当前代码中恢复旧快档结构需要：

```text
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_MAX_PREDS=0
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_CANDIDATE_BUDGET=0
```

对应结构：

| 指标 | 快档数值 |
| --- | ---: |
| `compute_supernodes` | `74430` |
| `dag_edges` | `485905` |
| `boundary_values` | `1151073` |
| `boundary_activation_edges` | `2216514` |
| `essent_small_sibling_merges` | `329802` |

`max_preds=1/2` 或 budgeted small-sibling 路线已被 `NO0166/NO0168/NO0169/NO0170` 证明不能恢复该结构。

## 验证

已完成轻量验证：

```sh
python3 -m py_compile scripts/wolvrix_xs_grhsim.py
```

结果：通过。

新增 dry-run 配置验证：

```sh
WOLVRIX_XS_GRHSIM_DUMP_CONFIG_ONLY=1 \
  python3 scripts/wolvrix_xs_grhsim.py dummy.f SimTop tmp/dummy_out /tmp/dummy.json '' info
```

结果：通过，脚本只打印配置并退出，没有读 SV、没有跑 pass、没有 emit，也没有创建 `cpp_out_dir`。

关键输出：

```text
enable_essent_mffc_build=True
enable_essent_coarsen=True
enable_essent_small_sibling_merge=True
enable_essent_small_overlap_merge=False
enable_essent_down_merge=False
essent_small_sibling_max_preds=0
essent_small_sibling_candidate_budget=0
storage_ref_aliases=0(xs_default)
dump_config_only=True
```

同时验证了用户显式覆盖仍生效：

```sh
WOLVRIX_XS_GRHSIM_DUMP_CONFIG_ONLY=1 \
WOLVRIX_GRHSIM_STORAGE_REF_ALIASES=1 \
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_MAX_PREDS=2 \
WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_CANDIDATE_BUDGET=250000 \
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE=1 \
WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE=1 \
  python3 scripts/wolvrix_xs_grhsim.py dummy.f SimTop tmp/dummy_override /tmp/dummy.json '' info
```

关键输出：

```text
enable_essent_small_overlap_merge=True
enable_essent_down_merge=True
essent_small_sibling_max_preds=2
essent_small_sibling_candidate_budget=250000
storage_ref_aliases=1
dump_config_only=True
```

两个 dry-run 均确认没有创建对应 `cpp_out_dir`。

## 待验收

本次没有 fresh emit/build/runtime。下一次必须 full emit 时，应同时验收：

- emit log 中默认打印：
  - `enable_essent_mffc_build=True`
  - `enable_essent_coarsen=True`
  - `essent_small_sibling_max_preds=0`
  - `essent_small_sibling_candidate_budget=0`
  - `enable_essent_small_overlap_merge=False`
  - `enable_essent_down_merge=False`
  - `storage_ref_aliases=0(xs_default)`
- 结构回到 `NO0171/NO0172` 档。
- sched 源码体积回到 `NO0151` alias-off 档。
- 20k gate 接近 `NO0151/NO0152` 的 `~99-101s` 档。

若上述任一项不成立，说明仍存在新的默认口径漂移或 emitter 代码形态漂移。
