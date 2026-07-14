# TNO0024 Stage 1 mixed-policy structure scans

记录日期：2026-07-14

状态：`strict / bae-budget / balanced` 的 SimTop `rounds=1` structure scan 全部 PASS；三者均进入 fresh emit/build 与 runtime gate。本文只记录结构结果，不把结构下降写成性能收益。

## 1. 对照与扫描口径

三组扫描都复用 [TNO0022](./TNO0022_fresh_current_default_no0300_baseline1_20260714.md) 的 fresh current-default pre-reg-to-mem checkpoint。除 policy 外，参数一致：

```text
post_dp_refine_max_rounds=1
post_dp_refine_max_moves=4096
post_dp_refine_max_moved_op_ppm=10000
post_dp_refine_max_regression_ppm=10000
```

基础 graph、plain partition 和结构锚点均相同：`7,204,108` graph ops、`63,726` supernodes、`1,983,923` total BAE、`528,622` DAG edges。原始产物为：

```text
build/logs/xs/xs_wolf_grhsim_build_activity_stage1_strict_r1_scan_20260714.log
build/logs/xs/xs_wolf_grhsim_build_activity_stage1_balanced_r1_scan_20260714.log
build/logs/xs/xs_wolf_grhsim_build_activity_stage1_bae_budget_r1_scan_20260714.log
build/xs_activity_stage1_strict_r1_20260714/grhsim/grhsim_emit/activity_schedule_supernode_stats.json
build/xs_activity_stage1_balanced_r1_20260714/grhsim/grhsim_emit/activity_schedule_supernode_stats.json
build/xs_activity_stage1_bae_budget_r1_20260714/grhsim/grhsim_emit/activity_schedule_supernode_stats.json
```

## 2. 搜索结果

| Metric | strict | balanced | bae-budget |
| --- | ---: | ---: | ---: |
| refinement time | `2,533 ms` | `2,486 ms` | `2,592 ms` |
| retained candidates | `49,676` | `57,312` | `105,307` |
| moves / swaps | `4,096 / 0` | `4,096 / 0` | `4,096 / 0` |
| moved ops | `51,569` | `51,930` | `52,363` |
| rejected capacity | `385,401` | `395,125` | `499,061` |
| rejected topology | `1,449,288` | `1,448,885` | `1,454,070` |
| rejected policy | `658,981` | `643,450` | `461,288` |

三组都先耗尽 `4096` moved-cluster 总上限，尚未触及 `56,251` moved-op 上限；一次 swap 计两个 moved cluster，因此本轮没有容量留给 swap。`postDpRefineMaxRounds` 是同一次 refinement 的总预算而不是逐轮重置预算。既然第一轮结束时 `movedClusters == postDpRefineMaxMoves`，外层循环在进入第二轮前即停止；在其余参数不变时，扫描 rounds `2/4` 会逐字复现 rounds `1`，故不重复执行无效的大图运行。

## 3. 最终结构

| Metric | baseline | strict | balanced | bae-budget |
| --- | ---: | ---: | ---: | ---: |
| total / compute / commit SN | `63726 / 63241 / 485` | same | same | same |
| compute BAE | `1,721,698` | `1,699,454` | `1,699,349` | `1,697,944` |
| compute-commit pairs | `262,225` | `262,225` | `262,225` | `262,225` |
| total BAE | `1,983,923` | `1,961,679` | `1,961,574` | `1,960,169` |
| total BAE delta | - | `-1.1212%` | `-1.1265%` | `-1.1973%` |
| DAG edges | `528,622` | `508,629` | `508,456` | `510,187` |
| DAG delta | - | `-3.7821%` | `-3.8141%` | `-3.4874%` |
| boundary values | `1,000,463` | `998,394` | `998,593` | `998,425` |
| boundary-value delta | - | `-2,069` | `-1,870` | `-2,038` |
| compute ops p99 / max | `108 / 108` | same | same | same |

三种 policy 的 modeled compute BAE/DAG 都由 final stats full recount 精确复现，且 `compute BAE + 262,225 = total BAE`。graph 大小、supernode 数、commit pairs 和 cap 均未变化。

`balanced` 相对 `strict` 只再减少 `105` 个 compute BAE 和 `173` 条 DAG edge，同时多 `199` 个 boundary value。`bae-budget` 相对 `strict` 再减少 `1,510` 个 compute BAE，但多 `1,558` 条 DAG edge。这些差异都远小于结构软门槛，不能据此提前淘汰任何一组。

## 4. 生成耗时说明

三次 scan 的 activity-schedule / total flow 时间分别为：

| Policy | activity-schedule | total flow |
| --- | ---: | ---: |
| strict | `179,815 ms` | `354,223 ms` |
| balanced | `178,029 ms` | `350,120 ms` |
| bae-budget | `188,274 ms` | `364,821 ms` |

跨运行的 reg-to-mem、coarsen 和主机负载噪声远大于约 `2.5 s` refinement 本体差异，因此这里不把 total-flow 排序解释成 policy 性能。三组 refinement 均远低于 current-default schedule 的 `2x` kill criterion。

## 5. 下一步

三组候选均属于正向结构结果。按 [TNO0021](./TNO0021_current_default_baseline_and_stage1_refinement_plan_20260714.md) 的软门槛，它们分别从同一 checkpoint fresh emit/build，执行 fixed-ASLR 100-cycle、10k 和 50k difftest。最终保留或停止只由 quiet fixed-ASLR SimTop 50k A/B/A 裁决；generated C++ 总量、sched batch 数、emu `.text` 和五事件 PMU 用于解释结构与 runtime 的一致或背离。
