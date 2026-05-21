# NO0176 Root-Cause Alignment Audit

日期：2026-05-21

## 目标复述

主目标是：

```text
找到 gsim 和 grhsim 性能差 10 倍的根本原因，并以这个原因为导向实施性能对齐。
```

当前不应标记为完成。原因是：已经定位并修复了多层 grhsim 侧退化来源，但还没有在最新默认口径下完成 fresh emit/build/20k/50k runtime 闭环。

## 已有证据链

### 1. 结构层根因

`NO0166` 到 `NO0171` 证明：近期结构回退来自两个问题。

| 问题 | 证据 | 修复/口径 |
| --- | --- | --- |
| budgeted small-sibling 不能恢复旧快档 | `NO0166/NO0168/NO0169/NO0170` | 使用 C2 full |
| skipped DAG edge 仍记录 `valueFanout` 导致 source-edge 爆炸 | `NO0170` | `skipDagEdge` 时同步跳过 `valueFanout` |

已恢复的结构快档：

| 指标 | 快档数值 |
| --- | ---: |
| `compute_supernodes` | `74430` |
| `dag_edges` | `485905` |
| `boundary_values` | `1151073` |
| `boundary_activation_edges` | `2216514` |
| `essent_small_sibling_merges` | `329802` |

### 2. 代码形态层根因

`NO0172` 证明：结构恢复后，runtime 仍未恢复。

| 实验 | 20k 时间 | 约速度 | 备注 |
| --- | ---: | ---: | --- |
| `NO0162` | `98988 ms` | `202.0 cycles/s` | 快档参考 |
| `NO0172` | `129095 ms` | `154.9 cycles/s` | 结构恢复但 alias-on |

`NO0173` 进一步证明：`NO0172` 与 clean `NO0151` 的结构一致，但生成代码体积和 alias 形态不同。

| 实验 | sched bytes | 20k gate |
| --- | ---: | ---: |
| `NO0151` alias-off | `1788406953` | `101232 ms` |
| `NO0172` alias-on | `2696952102` | `129095 ms` |

关键差异：

| 指标 | `NO0151` | `NO0172` |
| --- | ---: | ---: |
| `auto &grhsim_state_scalar` | `0` | `1318475` |
| `auto &grhsim_value_` | `0` | `3184814` |

结论：同结构下 runtime 回退主要来自 emitter 生成的 batch body 过大、alias 声明过多、frontend/code-layout 压力增加。

### 3. 默认口径对齐

已实施：

| 文档 | 改动 |
| --- | --- |
| `NO0174` | XS grhsim 脚本默认 `WOLVRIX_GRHSIM_STORAGE_REF_ALIASES=0`，保留显式覆盖 |
| `NO0175` | XS grhsim 脚本默认 C2 full：MFFC/coarsen 开启、small-sibling unbounded、overlap/down 关闭 |

`NO0175` dry-run 验证了默认和显式覆盖：

```text
enable_essent_mffc_build=True
enable_essent_coarsen=True
enable_essent_small_overlap_merge=False
enable_essent_down_merge=False
essent_small_sibling_max_preds=0
essent_small_sibling_candidate_budget=0
storage_ref_aliases=0(xs_default)
```

显式覆盖也保留：

```text
enable_essent_small_overlap_merge=True
enable_essent_down_merge=True
essent_small_sibling_max_preds=2
essent_small_sibling_candidate_budget=250000
storage_ref_aliases=1
```

## 当前根因表述

当前最精确的根因不是单一“activity-schedule 图过大”，而是两层叠加：

1. activity-schedule 结构必须保持 C2 full + valueFanout 修复后的低 BAE / 低 DAG 档。
2. 在同结构下，grhsim 生成的 batch body 仍可能因为 per-supernode storage-ref alias 和 typed slot 访问形态导致巨大源码/机器码与 frontend pressure，进而拉低 runtime。

换句话说：

```text
结构收益是必要条件，但不是充分条件；代码形态必须同时保持 alias-off 快档。
```

## 未完成项

还缺最新默认口径的完整验收：

| 验收项 | 状态 |
| --- | --- |
| latest script dry-run 默认值 | 已通过 |
| fresh emit 是否默认打印目标配置 | 未跑 |
| fresh emit 结构是否回到 `NO0171/NO0172` 档 | 未跑 |
| sched 源码体积是否回到 `NO0151` alias-off 档 | 未跑 |
| model build 是否成功 | 未跑 |
| 20k difftest runtime 是否回到 `~99-101s` | 未跑 |
| 50k difftest runtime 是否回到 `~347-349s` | 未跑 |

因此主目标不能标记为完成。

## 下一次最小闭环

下一次需要 fresh emit 时，最小闭环应该是：

1. full emit，确认日志默认值：
   - `enable_essent_mffc_build=True`
   - `enable_essent_coarsen=True`
   - `essent_small_sibling_max_preds=0`
   - `essent_small_sibling_candidate_budget=0`
   - `enable_essent_small_overlap_merge=False`
   - `enable_essent_down_merge=False`
   - `storage_ref_aliases=0(xs_default)`
2. 结构 gate：
   - `compute_supernodes=74430`
   - `dag_edges=485905`
   - `boundary_values=1151073`
   - `boundary_activation_edges=2216514`
3. 代码形态 gate：
   - sched bytes 接近 `NO0151`，不能接近 `NO0172` 的 `2696952102`。
   - `auto &grhsim_state_scalar` / `auto &grhsim_value_` 不应回到百万级。
4. build difftest emu。
5. CoreMark 20k with difftest：
   - 目标接近 `~99-101s`。
   - 若明显慢，不跑 50k，先诊断代码形态。
6. 20k 通过后再跑 50k：
   - 目标接近 `~347-349s`。

## 风险

- 当前 `NO0162` generated source tree 曾被 hardlink probe 污染，不能继续作为 pristine 源码对照；runtime/archive 历史数据仍可引用。
- `NO0172` 的 model build 曾误触发单个 `state_init_9.cpp` 重编并被终止，因此其 model build wall-clock 不能作为有效对比。
- nested `wolvrix` 仍包含大量前序 emitter/transform 改动；最终验收必须以实际 fresh emit/build/runtime 为准。
