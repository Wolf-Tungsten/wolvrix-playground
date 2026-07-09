# NO0222 Commit Detection Grouping + Dirty Gating Plan

## 0. 决策记录

2026-07-09 决策：不继续推进本文的 dirty gating 优化方案。

原因：

- runtime shadow 证明 dirty gating 的收益高度依赖 runtime 行为，而不是纯静态结构。
- CoreMark 50k 数据中，按 dirty mark cost = 1 个 static check unit 估算，整体有 `13.58%` commit detection weighted checks 收益，但 row 级别有 `261` 个负收益 row。
- 如果不能依赖 profiling / runtime hint，静态 gate 无法可靠区分高收益 group 和负收益 group。
- 过于保守的静态 gate 虽可降低负优化风险，但覆盖率和收益不确定，复杂度不值得作为当前方向继续投入。

因此本文后续仅作为 commit detection hotspot 和 runtime shadow 诊断记录保留，不作为待实现计划。P0 诊断数据可继续用于理解问题；P1 reader-mask grouping、P2 dirty gating、P3 range-level detector、P4 commit packing cost model 不再按本文方案推进。

## 1. 背景

`NO0221` 的新 JSON 口径显示，GrhSIM 的 `runtime_weighted_checks` 明显异常：

| 指标 | GSim | GrhSIM | GrhSIM / GSim |
| --- | ---: | ---: | ---: |
| static activation checks | `442,047` | `1,251,744` | `2.832x` |
| runtime activation_count | `766,596,798` | `907,159,590` | `1.183x` |
| runtime_weighted_checks | `3,832,780,896` | `24,440,291,074` | `6.377x` |

相关记录见 [`NO0221`](./NO0221_xs_gsim_grhsim_unified_stats_coremark50k_20260709.md)。

进一步拆分后，commit supernode 是主要来源：

| kind | supernodes | runtime activation_count | runtime_weighted_checks | weighted checks share |
| --- | ---: | ---: | ---: | ---: |
| compute | `71,871` | `898,467,340` | `11,397,357,904` | `46.63%` |
| commit | `497` | `8,692,250` | `13,042,933,170` | `53.37%` |

commit 只占 `0.69%` supernode、`0.96%` runtime activation_count，却贡献 `53.37%` weighted checks。按 top-N 看：

| top N by `runtime_weighted_checks` | 累计 weighted checks | 占 GrhSIM total |
| ---: | ---: | ---: |
| 1 | `2,148,996,850` | `8.79%` |
| 2 | `3,071,868,800` | `12.57%` |
| 10 | `4,763,658,900` | `19.49%` |
| 20 | `6,813,706,900` | `27.88%` |
| 50 | `12,800,187,400` | `52.37%` |

前 20 个热点全部是 commit supernode。典型热点：

| supernode | kind | activation_count | checks | runtime_weighted_checks |
| ---: | --- | ---: | ---: | ---: |
| `71871` | `commit` | `50,050` | `42,937` | `2,148,996,850` |
| `72080` | `commit` | `50,050` | `18,439` | `922,871,950` |

## 2. 当前机制判断

当前 activity-schedule 中，commit node 不参与 compute-node coarsen 和 DP。参见 [`grhsim-scheduling.md`](../../wolvrix/docs/emit/grhsim-scheduling.md)：

- commit node 是 sink-class op 的中间分组。
- commit node 不参与 compute-node coarsen 和 DP。
- compute DP 的目标函数是：

```text
cost(segment) = incoming_boundary_activation_edges + 1
```

因此，`runtime_weighted_checks = 6.377x` 不能简单归因于 “compute DP 权重选得不好”。更准确的说法是：当前调度/划分成本模型没有覆盖 commit detection cost。

当前 GrhSIM static stats 中，commit `activation_checks` 的定义是：

- 对 commit supernode 中的每个 state write detection point 计数；
- 该 write 的目标 state 必须存在 reader supernode；
- 同一 write 即使激活多个 reader supernode，`activation_checks` 只加一次；
- 多目标 fanout 体现在 `activation_edges.commit_compute` 中。

实现位置见 [`grhsim_cpp.cpp`](../../wolvrix/lib/emit/grhsim_cpp.cpp) 的 static stats 生成逻辑。官方口径见 [`grhsim-gsim-statistics.md`](../../wolvrix/docs/emit/grhsim-gsim-statistics.md)。

当前 commit apply helper 的形态是：

- 遍历 group/table/range 内的 state write entry；
- 检查 cond / mask；
- 计算 merged value；
- 比较 state old value 与 next/merged value；
- 若有任一 state changed，则 OR 对应 reader activation mask。

这个机制保证正确，但当一个 commit supernode 包含数千到数万 write detection points 且几乎每周期都执行时，`runtime_weighted_checks` 会被少数 commit supernode 主导。

## 3. 为什么“只拆 commit supernode”不够

单纯把一个大 commit supernode 拆成多个更小 chunk，不能保证降低总检查量。

如果拆分前：

```text
1 group * 50,000 activation * 40,000 checks = 2,000,000,000 weighted checks
```

拆分后如果所有 chunk 仍然每周期扫描：

```text
10 groups * 50,000 activation * 4,000 checks = 2,000,000,000 weighted checks
```

总量基本不变。拆分只能改善局部性、代码形态和激活 mask 粒度。真正减少 checks 必须满足至少一个条件：

1. 大部分 commit group 在多数周期可以跳过；
2. 多个 detection point 可以合并成更少的批量检测；
3. 激活 reader mask 的粒度更精确，减少不必要的 compute reader 激活，间接减少后续 work。

因此本文提案的主线不是“拆小”，而是：

```text
commit detection grouping + dirty gating + range-level detector
```

## 4. 目标与非目标

目标：

- 降低 GrhSIM commit 贡献的 `runtime_weighted_checks`。
- 降低 commit->compute 动态激活压力。
- 保持当前静态/运行期 JSON 主 schema 可 join。
- 保守保证 functional correctness，任何不确定 case 默认回退到 always-scan。
- 先以 XiangShan CoreMark 50k 为 gate，再扩展到 xs-components。

非目标：

- 本文不重写 compute DP。
- 本文不改变 GSim 口径。
- 本文不把 commit state write 语义重新建模成 compute supernode。
- 本文不把所有 state array re-aggregation 一次性解决；array/register 展开是上游问题，但本方案先降低展开后的 commit detection runtime cost。

## 5. 方案总览

分阶段推进：

| 阶段 | 名称 | 行为变化 | 目的 |
| --- | --- | --- | --- |
| P0 | commit detection diagnostics | 无 | 找出 top commit 的 state family / reader mask / range 形态 |
| P1 | reader-mask grouping | 默认无语义变化 | 把 commit writes 按 reader mask / event / guard / storage kind 分组 |
| P2 | commit detection dirty gating | 有，默认关 | input 没变的 commit group 直接跳过 detection scan |
| P3 | range-level detector | 有，默认关 | 对连续 state slots 做批量 compare/update |
| P4 | commit packing cost model | 有，默认关 | 用 detection cost 约束 commit packing，而不是只用 op count |

建议开关名：

- pass / emitter option：`commit_detection_dirty_gating`
- XiangShan env：`WOLVRIX_XS_GRHSIM_COMMIT_DETECTION_DIRTY_GATING`
- 诊断 JSON：`grhsim_commit_detection_stats.json`

开关名必须表达机制本身，避免使用含糊的 profile/tsv/experimental 名称。

## 6. P0：Commit Detection Diagnostics

P0 只新增诊断，不改变 schedule 或 runtime 行为。

### 6.1 新增诊断 JSON

输出：

```text
grhsim_commit_detection_stats.json
```

2026-07-09 已落地首版静态诊断，生成位置在 GrhSIM emit 输出目录，文件会被 `EmitResult.artifacts` 返回。该 JSON 不改变 schedule/runtime 行为，不改变 `grhsim_static_stats.json` / `grhsim_runtime_stats.json` 主 schema。

首版 schema 摘要：

```json
{
  "format": "wolvrix.grhsim-commit-detection-stats.v1",
  "sim": "grhsim",
  "top": "SimTop",
  "summary": {
    "commit_supernodes": 497,
    "detection_points": 268310,
    "activation_edges": {
      "total": 0,
      "commit_compute": 0,
      "commit_commit": 0
    },
    "reader_mask_groups": 0,
    "values": {
      "dependency": 0,
      "external_input": 0,
      "event": 0
    },
    "dirty_gating": {
      "candidate_points": 0,
      "always_scan_points": 0,
      "dependency_fanout_entries": 0
    },
    "range_detection": {
      "compressible_points": 0,
      "range_runs": 0,
      "largest_run": 0
    },
    "cost_model": {
      "unit": "static_detection_cost_unit",
      "baseline_scan_units_per_event": 0,
      "clean_event_units_with_dirty_gating": 0,
      "dirty_event_units_with_dirty_gating": 0,
      "break_even_skip_ratio_by_dependency_change_ratio": []
    }
  },
  "commit_supernodes": [
    {
      "sim": "grhsim",
      "top": "SimTop",
      "supernode_id": 71871,
      "detection_points": 42937,
      "activation_edges": {
        "total": 0,
        "commit_compute": 11982,
        "commit_commit": 0
      },
      "values": {
        "dependency": 0,
        "external_input": 0,
        "event": 0
      },
      "dirty_gating": {
        "candidate_points": 0,
        "always_scan_points": 0,
        "dependency_fanout_entries": 0
      },
      "reader_mask_unique_count": 0,
      "shared_cond_groups": {},
      "shared_mask_groups": {},
      "storage_kind_top": [],
      "scalar_width_top": [],
      "always_scan_reason_top": [],
      "state_symbol_top": [],
      "reader_mask_groups_top": [],
      "range_candidates_top": [],
      "cost_model": {}
    }
  ]
}
```

P0 需要至少统计：

- `detection_points`
- `activation_edges.commit_compute`
- `values.dependency` / `values.external_input` / `values.event`
- `reader_mask_unique_count`
- `reader_mask_groups_top`
- `state_symbol_top`
- `storage_kind_top`
- `scalar_width_top`
- `range_detection.compressible_points`
- `shared_cond_groups`
- `shared_mask_groups`
- `multi_writer_state`
- `always_scan_reason_top`
- `dirty_gating.candidate_points`
- `dirty_gating.always_scan_points`
- `dirty_gating.dependency_fanout_entries`
- `cost_model.break_even_skip_ratio_by_dependency_change_ratio`

注意：`values.event` 只描述 clock/event 触发输入，不进入 dirty fanout 的收益估算；`values.dependency` 才是 sticky dirty 依赖集合。成本模型是静态模型，只给 break-even 阈值，不代表实际 runtime skip 率。

### 6.2 P0 验收

- 不改变 `grhsim_static_stats.json`。
- 不改变 `grhsim_runtime_stats.json`。
- `grhsim_commit_detection_stats.json` 必须是可解析 JSON，并包含 `sim/top/supernode_id` join key。
- top commit supernode `71871` / `72080` 必须能拆出 top state family 和 reader mask 分布。

### 6.3 P0 落地验证

实现位置：

- [`grhsim_cpp.cpp`](../../wolvrix/lib/emit/grhsim_cpp.cpp)：emit `grhsim_commit_detection_stats.json`，并加入 artifacts / stale artifact cleanup。
- [`test_emit_grhsim_cpp.cpp`](../../wolvrix/tests/emit/test_emit_grhsim_cpp.cpp)：检查文件存在、artifact 登记、schema 关键字段。

验证命令：

```text
cmake --build wolvrix/build -j32
ctest --test-dir wolvrix/build --output-on-failure -R emit-grhsim-cpp
source env.sh
make xs_wolf_grhsim_emit
```

完整 XiangShan emit 产物：

```text
build/xs/grhsim/grhsim_emit/grhsim_commit_detection_stats.json
```

本次完整 XiangShan P0 摘要：

| field | value |
| --- | ---: |
| commit_supernodes | `497` |
| detection_points | `268,310` |
| activation_edges.commit_compute | `99,659` |
| reader_mask_groups | `59,566` |
| values.dependency | `345,493` |
| values.external_input | `1` |
| values.event | `412` |
| dirty_gating.candidate_points | `254,608` |
| dirty_gating.always_scan_points | `13,702` |
| dirty_gating.dependency_fanout_entries | `323,681` |
| range_detection.compressible_points | `0` |

Top commit supernode 诊断：

| supernode | detection_points | commit_compute_edges | dependency_values | event_values | candidate_points | always_scan_points | clean_event_units |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `71871` | `42,937` | `11,982` | `35,812` | `1` | `42,760` | `177` | `178` |
| `72080` | `18,439` | `13,903` | `17,629` | `2` | `18,433` | `6` | `7` |
| `71905` | `5,130` | `1,845` | `4,947` | `2` | `5,130` | `0` | `1` |

这里的 `clean_event_units` 是静态模型中的 `always_scan_points + dirty_test_units`，只表示 event 到达但 group clean 时的检查成本，不代表真实 runtime skip 率。实际收益需要 runtime shadow diagnostic 记录 event 到达时 dirty 是否命中后才能确认。

### 6.4 P0 Runtime Shadow Diagnosis

2026-07-09 已追加 runtime shadow 诊断。该诊断只记账，不改变 commit detection 行为，也不跳过任何已有 scan。

新增输出：

```text
build/xs/grhsim/grhsim_emit/grhsim_commit_detection_runtime_stats.json
```

schema 摘要：

```json
{
  "format": "wolvrix.grhsim-commit-detection-runtime-stats.v1",
  "sim": "grhsim",
  "top": "SimTop",
  "summary": {
    "event_trigger_count": 0,
    "dirty_mark_count": 0,
    "dirty_hit_count": 0,
    "clean_skip_count": 0,
    "candidate_checks_skipped": 0,
    "baseline_weighted_checks": 0,
    "estimated_gated_weighted_checks": 0,
    "estimated_saved_weighted_checks": 0,
    "estimated_extra_weighted_checks": 0
  },
  "commit_supernodes": [
    {
      "sim": "grhsim",
      "top": "SimTop",
      "supernode_id": 0,
      "event_trigger_count": 0,
      "dirty_mark_count": 0,
      "dirty_hit_count": 0,
      "clean_skip_count": 0,
      "clean_skip_ratio": 0.0,
      "detection_points": 0,
      "dirty_gating": {
        "candidate_points": 0,
        "always_scan_points": 0,
        "dirty_test_units": 0,
        "candidate_dependency_fanout_entries": 0
      },
      "candidate_checks_skipped": 0,
      "baseline_weighted_checks": 0,
      "estimated_gated_weighted_checks": 0,
      "estimated_saved_weighted_checks": 0,
      "estimated_extra_weighted_checks": 0
    }
  ]
}
```

字段定义：

- `event_trigger_count`：commit supernode 对应 event 实际到达次数。
- `dirty_mark_count`：dependency value 实际变化后，对 fanout commit supernode 执行 dirty mark 的次数。
- `dirty_hit_count`：event 到达且 sticky dirty 为 true 的次数，等价于 dirty gating 下会执行 detection 的次数。
- `clean_skip_count`：event 到达但 sticky dirty 为 false 的次数，等价于 dirty gating 下可跳过 candidate detection 的次数。
- `candidate_checks_skipped`：clean event 可跳过的 candidate detection points。
- `baseline_weighted_checks`：现有总检测成本，即 `event_trigger_count * detection_points`。
- `estimated_gated_weighted_checks`：shadow 模型估算的 dirty gating 成本，dirty mark 按 1 个 static check unit 计。
- `estimated_saved_weighted_checks` / `estimated_extra_weighted_checks`：相对 baseline 的净收益/净额外成本。

完整 XiangShan CoreMark 50k 诊断命令：

```text
source env.sh
make xs_wolf_grhsim_emu RUN_ID=runtime_dirty_diag_20260709 XS_WOLF_GRHSIM_EMIT_RUNTIME_STATS=1 XS_SIM_MAX_CYCLE=50000 XS_PROGRESS_EVERY_CYCLES=10000 XS_EMU_THREADS=1 XS_VM_BUILD_JOBS=32
make run_xs_wolf_grhsim_emu RUN_ID=runtime_dirty_diag_20260709 XS_WOLF_GRHSIM_EMIT_RUNTIME_STATS=1 XS_SIM_MAX_CYCLE=50000 XS_PROGRESS_EVERY_CYCLES=10000 XS_EMU_THREADS=1
```

运行结果：

| field | value |
| --- | ---: |
| host_cycles | `50,000` |
| cycleCnt | `49,996` |
| instr | `73,580` |
| host time | `386,948 ms` |

runtime shadow summary：

| field | value |
| --- | ---: |
| event_trigger_count | `8,692,250` |
| dirty_mark_count | `309,139,489` |
| dirty_hit_count | `3,189,687` |
| clean_skip_count | `5,502,563` |
| clean_skip_ratio | `63.304%` |
| candidate_checks_skipped | `2,088,856,907` |
| baseline_weighted_checks | `13,042,933,170` |
| estimated_gated_weighted_checks | `11,271,857,952` |
| estimated_saved_weighted_checks | `1,771,075,218` |
| estimated_gated / baseline | `86.421%` |
| estimated_saved / baseline | `13.579%` |

按当前 shadow 模型，commit detection weighted checks 从 `13.043B` 降到 `11.272B`，净省 `1.771B`。折到 GrhSIM total `runtime_weighted_checks=24.440B`，总量约降到 `22.669B`，约省 `7.25%`。这说明 dirty gating 有收益，但它不是单独达成 `<16B` 目标的完整方案。

dirty mark 成本敏感性：

| dirty mark cost / check unit | estimated net saving | saving ratio vs baseline |
| ---: | ---: | ---: |
| `0` | `2,080,214,707` | `15.949%` |
| `1` | `1,771,075,218` | `13.579%` |
| `2` | `1,461,935,729` | `11.209%` |
| `4` | `843,656,751` | `6.468%` |
| `8` | `-392,901,205` | `-3.012%` |
| `16` | `-2,866,017,117` | `-21.974%` |

break-even dirty mark cost 约为 `6.729` 个 static check unit。若 dirty mark 的真实成本超过这个值，全局 dirty gating 会变成负优化。

收益分布：

| class | rows | weighted checks |
| --- | ---: | ---: |
| positive rows | `217` | `+2,036,509,313` gross saved |
| negative rows | `261` | `-265,434,095` gross extra |
| zero rows | `19` | `0` |
| net | - | `+1,771,075,218` |

Top negative rows：

| supernode | event | dirty_mark | dirty_hit | clean_skip | skip_ratio | detection_points | candidate_points | always_scan_points | fanout_entries | baseline | gated | extra |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `71871` | `50,050` | `69,475,274` | `50,008` | `42` | `0.084%` | `42,937` | `42,760` | `177` | `35,626` | `2,148,996,850` | `2,216,726,254` | `67,729,404` |
| `71895` | `50,050` | `26,045,847` | `50,002` | `48` | `0.096%` | `4,091` | `4,032` | `59` | `5,679` | `204,754,550` | `230,656,911` | `25,902,361` |
| `72080` | `50,050` | `21,722,910` | `49,999` | `51` | `0.102%` | `18,439` | `18,433` | `6` | `17,599` | `922,871,950` | `943,704,827` | `20,832,877` |
| `71883` | `50,050` | `20,549,119` | `50,002` | `48` | `0.096%` | `4,095` | `4,002` | `93` | `5,859` | `204,954,750` | `225,361,823` | `20,407,073` |
| `71887` | `50,050` | `19,107,653` | `49,999` | `51` | `0.102%` | `4,096` | `4,032` | `64` | `4,426` | `205,004,800` | `223,956,871` | `18,952,071` |

Top positive rows：

| supernode | event | dirty_mark | dirty_hit | clean_skip | skip_ratio | detection_points | candidate_points | fanout_entries | baseline | gated | saved |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `72096` | `50,050` | `8,192` | `2` | `50,048` | `99.996%` | `4,096` | `4,096` | `8,192` | `205,004,800` | `66,434` | `204,938,366` |
| `72095` | `50,050` | `8,220` | `20` | `50,030` | `99.960%` | `4,096` | `4,096` | `8,192` | `205,004,800` | `140,190` | `204,864,610` |
| `72094` | `50,050` | `8,492` | `278` | `49,772` | `99.445%` | `4,096` | `4,096` | `8,192` | `205,004,800` | `1,197,230` | `203,807,570` |
| `72093` | `50,050` | `9,726` | `1,031` | `49,019` | `97.940%` | `4,096` | `4,096` | `8,192` | `205,004,800` | `4,282,752` | `200,722,048` |
| `72091` | `50,050` | `11,824` | `3,348` | `46,702` | `93.311%` | `4,096` | `4,096` | `8,192` | `205,004,800` | `13,775,282` | `191,229,518` |

结论：

- 当前数据支持继续做 dirty gating，但只能按 supernode / group 选择性启用。
- 不能全局无条件开启。`71871` / `72080` 这类几乎每次 event 都 dirty 的大 commit supernode 会因为 dirty mark 开销变慢。
- P1 reader-mask / subgroup grouping 仍然必要，因为正负收益混在同一 commit 区域时，需要更细粒度地只 gate 稳定输入 group。
- P2 首版应加入 profitability gate：只有静态 fanout、runtime clean skip ratio、估算 mark cost 同时满足收益条件的 group 才生成 dirty gating；其余保持 always-scan。

## 7. P1：Reader-Mask Grouping

P1 为每个 commit write 计算 reader activation mask signature，并按 signature 分组。

### 7.1 分组 key

建议分组 key：

```text
event_key
guard_key
reader_mask_signature
storage_kind
scalar_width
state_slot_layout
```

其中：

- `event_key` 保持原来的时序事件边界；
- `guard_key` 保持原来的 guard/event bucket 语义；
- `reader_mask_signature` 是目标 reader compute supernode 集合的 bitset/hash；
- `storage_kind` 区分 scalar storage、wide storage、reg-to-mem intent storage、memory；
- `state_slot_layout` 用于识别可 range-compress 的连续 slot。

### 7.2 生成代码形态

P1 后，commit helper 应从“一个 supernode 一个 union activation mask”变成“一个 group 一个 activation mask”。

伪代码：

```cpp
bool group_changed = false;
for (entry in group_entries) {
    if (!entry.cond()) continue;
    if (!entry.mask_nonzero()) continue;
    if (state != merged_next) {
        state = merged_next;
        group_changed = true;
    }
}
if (group_changed) {
    activate(group_reader_mask);
}
```

注意：P1 即使不减少 checks，也能让后续 P2/P3 的粒度正确，并减少“任一 state 变化激活过大 union reader mask”的问题。

### 7.3 保守限制

以下 case P1 可以分组，但不得改变原始 commit op 顺序：

- 同一 state symbol 在同一 event 内有多个 writer；
- writer 之间存在顺序覆盖关系；
- write cond/mask/next value 依赖其他 commit write 的结果；
- memory write 或动态地址写。

如果无法证明安全，保持原顺序并标记 `always_scan_reason`。

## 8. P2：Commit Detection Dirty Gating

P2 是主要收益来源。

基于 §6.4 的 runtime shadow 结果，P2 不应做全局无条件启用。首版必须按 commit supernode / commit group 做 profitability gate：

```text
enable_dirty_gating(group) =
    estimated_saved_weighted_checks(group, mark_cost_hint) > 0
```

其中 `mark_cost_hint` 首版用保守常量，并在诊断 JSON 中继续输出真实 `dirty_mark_count` / `clean_skip_count`，用于后续校准。若没有 runtime hint，默认策略应是：

- 高 fanout 且 dirty hit ratio 接近 100% 的 group 保持 always-scan；
- clean skip ratio 高、candidate detection points 大、dirty mark fanout 小的 group 才启用 dirty gating；
- 不确定 case always-scan。

### 8.1 基本思想

每个 commit detection group 维护一个 sticky dirty flag。dirty 不能定义成“当前 eval 内输入有没有变化”，而必须定义成：

```text
从该 commit group 上一次 event-triggered detection 执行之后，
它依赖的输入 value 是否发生过变化。
```

也就是说，dirty 是跨 eval 保持的粘滞状态，只能被该 group 对应 event 消费后清除。

典型反例：

```text
eval #1:
  data / next value 变化
  clock event 尚未到来

eval #2:
  data / next value 没有再次变化
  clock event 到来
```

正确行为是 `eval #1` 把 commit group dirty 置位，并一直保持到 `eval #2` 的 clock event 到来；`eval #2` 虽然 data 在本次 eval 内没有变化，也必须执行 commit detection。否则会漏掉 state update / reader activation。

所以每个 commit group 只在以下条件同时满足时扫描：

- 该 group 的 event 到来；
- 该 group 的 sticky dirty flag 为 true。

伪代码：

```cpp
if (!event_triggered_for_group(group_id)) {
    return;
}
if (!commit_group_dirty_[group_id]) {
    return;
}
commit_group_dirty_[group_id] = false;

bool group_changed = false;
for (entry in group_entries) {
    ...
}
if (group_changed) {
    activate(group_reader_mask);
}
```

### 8.2 输入依赖集合

每个 commit group 的 input dependency 至少包括：

- write cond value；
- write mask value；
- write next value；
- dynamic address/index value；
- event/guard 选择相关 value；
- 对 memory / dynamic write 的保守依赖。

当 compute supernode 产生这些 value 且 value 实际变化时，置位对应 commit group dirty flag：

```cpp
if (value_changed(v)) {
    for (group in commit_group_fanout_by_value[v]) {
        commit_group_dirty_[group] = true;
    }
}
```

注意：这里不要求对应 event 在同一个 eval 内到来。dirty bit 必须跨 eval 保留，直到该 group 的 event-triggered detection 消费它。

### 8.3 reset / 初始化规则

所有 commit group 在 reset 后必须 dirty 一次：

```cpp
std::fill(commit_group_dirty_.begin(), commit_group_dirty_.end(), true);
```

原因：

- state 初值和 input cache 必须建立一致性；
- 第一轮必须允许 state write detection 正常运行；
- 不能依赖未初始化的 dirty 状态。
- reset / event guard 变化如果会改变 write 是否生效，也必须作为对应 group 的 dirty 输入或直接触发该 group always-scan。

### 8.4 正确性条件

P2 的核心正确性判断：

如果一个 commit group 的所有输入 value 相对该 group 上一次 event-triggered detection 执行时都没有变化，并且该 group 上次执行后已经完成 state update，那么下一次同 event 到来时再次执行该 group 不会产生新的 state change。

这对单 writer / 无跨 group state dependency 的 scalar state write 成立。

禁止的错误实现：

```cpp
// 错误：dirty 不能在每个 eval 开头清零
commit_group_dirty_[group] = false;
```

```cpp
// 错误：event 未到来时不能消费 dirty
if (commit_group_dirty_[group]) {
    commit_group_dirty_[group] = false;
}
```

可选实现模型：

- 简单实现：sticky bitset，value change 置位，event-triggered detection 后清位。
- 调试实现：epoch 校验。记录 `value_change_epoch[v]` 与 `group_checked_epoch[group]`，断言 sticky dirty 不会在 `max(dep epochs) > group_checked_epoch` 时被清掉。

### 8.5 必须回退 always-scan 的 case

以下 case 首版直接 always-scan：

- 同一 target state 在多个 commit group 中被写；
- 同一 state 的多个 writer 顺序可能影响最终值；
- memory write；
- dynamic address write；
- DPI/system task 影响的 write；
- commit group 的 input dependency 无法完整枚举；
- write 的 next/mask/cond 读取了本轮 commit phase 中可能被更早 writer 更新的 state。

这些回退必须在 P0/P2 诊断 JSON 中计数，不允许静默回退。

### 8.6 Runtime 数据结构

建议新增：

```cpp
std::array<std::uint64_t, kCommitGroupDirtyWords> commit_group_dirty_;
```

或沿用现有 active bitset helper，避免新增散乱 bool array。

还需要 value -> commit group fanout：

```cpp
struct grhsim_commit_group_fanout_entry {
    std::uint32_t word_index;
    std::uint64_t mask;
};
```

当 compute value changed 时：

```cpp
for (entry in commit_group_fanout_by_value[value]) {
    commit_group_dirty_[entry.word_index] |= entry.mask;
}
```

### 8.7 统计更新

官方 `grhsim_runtime_stats.json` 的 `activation_count` 应继续表示实际执行的 supernode/group 次数。P2 开启后，如果 commit group 被跳过，则不增加 activation_count。

如果 P2 引入 commit group 但不改变 official supernode id，需要额外定义 group-level diagnostic。建议不要污染主 schema，新增：

```text
grhsim_commit_detection_runtime_stats.json
```

group-level 字段：

- `commit_group_id`
- `owner_supernode_id`
- `active_count`
- `skip_count`
- `dirty_set_count`
- `event_trigger_count`
- `detection_points`
- `executed_weighted_checks`
- `reader_mask_words`

其中：

- `dirty_set_count`：dependency value 变化导致该 group dirty 被置位的次数。
- `event_trigger_count`：该 group 对应 event 到来的次数。
- `active_count`：event 到来且 dirty 为 true，因此实际执行 detection 的次数。
- `skip_count`：event 到来但 dirty 为 false，因此跳过 detection 的次数。

当前已落地的 shadow 诊断是 supernode-level，不改变 official runtime 行为；后续真正 group 化后，应保留 `sim/top/supernode_id` join key，并额外增加 `commit_group_id`。

## 9. P3：Range-Level Detector

P3 降低单次执行成本，不负责减少执行次数。

### 9.1 适用条件

可 range-detect 的 group 需要满足：

- state slots 连续；
- next slots 连续；
- mask slots 连续或为常量 full mask；
- cond 相同，或 cond slots 连续且可批量读取；
- storage kind / scalar width 相同；
- reader mask signature 相同；
- writer 顺序不影响语义。

### 9.2 生成代码形态

full mask contiguous range：

```cpp
changed = compare_and_copy_range(state_base, next_base, count);
if (changed) activate(reader_mask);
```

masked range：

```cpp
changed = compare_masked_and_update_range(state_base, next_base, mask_base, count);
if (changed) activate(reader_mask);
```

bool / u8 / u16 / u32 / u64 分别保留专用 helper，避免模板膨胀。

### 9.3 和现有 range helper 的关系

现有 emitter 已经有 commit scalar state write range helper。P3 不是重新发明 helper，而是让 grouping 阶段更积极地产生 range descriptor，并让 descriptor 的 activation mask 粒度从大 supernode union 缩小到 group reader mask。

## 10. P4：Commit Packing Cost Model

当前 `maxOpInCommitSupernode=4096` 只限制 sink-class op 数。这个约束无法直接限制 detection cost。

新增 commit packing 约束：

- `maxCommitDetectionPointsPerGroup`
- `maxCommitReaderMaskWordsPerGroup`
- `maxCommitInputValuesPerGroup`
- `maxCommitRangeEntriesPerGroup`
- `maxCommitAlwaysScanPointsPerGroup`

packing 目标：

```text
minimize estimated_runtime_detection_cost
```

首版估算：

```text
estimated_runtime_detection_cost =
    always_scan_points
  + dirty_probability_hint * gated_detection_points
  + reader_mask_words * reader_mask_cost
```

如果没有 profile，`dirty_probability_hint` 先用保守常量：

- external/input/DPI group：`1.0`
- normal compute-driven scalar group：`0.1`
- shared clock/reset guard group：`1.0`

这些只是启发式，不进入 correctness 逻辑。

## 11. 实现切点

主要改动点：

- [`activity_schedule.cpp`](../../wolvrix/lib/transform/activity_schedule.cpp)
  - commit write metadata collection；
  - reader mask signature；
  - commit group construction；
  - always-scan reason classification；
  - session export：commit group map / value fanout。
- [`activity_schedule.hpp`](../../wolvrix/include/transform/activity_schedule.hpp)
  - 新增 options；
  - 新增 commit group 相关 session data 类型。
- [`grhsim_cpp.cpp`](../../wolvrix/lib/emit/grhsim_cpp.cpp)
  - emit commit group active bitset；
  - emit value -> commit group fanout；
  - emit grouped commit detection helper；
  - emit diagnostic JSON；
  - runtime stats 记录 active/skip。
- [`scripts/wolvrix_xs_grhsim.py`](../../scripts/wolvrix_xs_grhsim.py)
  - 接入 `WOLVRIX_XS_GRHSIM_COMMIT_DETECTION_DIRTY_GATING`；
  - 输出路径和日志。
- [`wolvrix/docs/emit/grhsim-gsim-statistics.md`](../../wolvrix/docs/emit/grhsim-gsim-statistics.md)
  - 若主 JSON schema 有变化，必须同步更新；
  - 若只新增 diagnostic JSON，主 schema 不变。

## 12. 验证计划

### 12.1 单元测试

新增最小 testcase：

1. cond 不变、mask 不变、next 不变：第二轮 commit group skip。
2. cond 变化：commit group active，state update 正确。
3. mask 变化：commit group active，masked update 正确。
4. next 变化：commit group active，state update 正确。
5. reset 后所有 commit group active。
6. data / next value 在 `eval #1` 变化，clock/event 在 `eval #2` 到来：dirty 必须跨 eval 保持，`eval #2` 执行 commit detection。
7. data / next value 在 `eval #1` 变化，`eval #2` event 未到来：dirty 不得被清除。
8. event 到来但 dirty 为 false：跳过 detection，state 不变。
9. 同 state 多 writer：fallback always-scan。
10. memory write / dynamic address：fallback always-scan。
11. range detector full mask：批量更新和逐项更新等价。
12. range detector masked：批量 masked update 和逐项更新等价。

### 12.2 xs-components gate

先跑小组件：

- scalar register write；
- array-like register write；
- shared guard writes；
- multi-writer state；
- dynamic index write；
- memory write。

要求：

- 和 Verilator / existing GrhSIM 行为一致；
- P2 开启时，skip_count > 0；
- fallback reason 可解释。

### 12.3 XiangShan gate

阶段 gate：

1. emit-only：生成 `grhsim_commit_detection_stats.json`。
2. build-only：确认不引入 compile-time 爆炸。
3. 2k smoke：difftest 通过。
4. 50k CoreMark：difftest/cycle-limit 正常。
5. JSON 校验：
   - `grhsim_static_stats.json` 可解析；
   - `grhsim_runtime_stats.json` 可解析；
   - static/runtime join key 完整；
   - diagnostic JSON 可解析；
   - 无 TSV。

## 13. 成功标准

第一阶段目标：

| 指标 | 当前 | 目标 |
| --- | ---: | ---: |
| GrhSIM total `runtime_weighted_checks` | `24.44B` | `< 16B` |
| commit share of weighted checks | `53.37%` | `< 35%` |
| top1 commit weighted checks | `2.149B` | `< 1.0B` |
| CoreMark 50k correctness | pass | pass |
| host time | `325,783 ms` | no regression, ideally improve |

结构目标：

- top commit `71871` / `72080` 有明确 group breakdown；
- dirty-gated commit group 的 `skip_count / (active_count + skip_count)` 可观测；
- always-scan fallback 占比不超过总 commit detection points 的 `50%`，否则 P2 收益会受限，需要回到上游 state aggregation / writer grouping。

## 14. 风险与处理

### 风险 A：dirty dependency 不完整导致漏 commit

处理：

- 首版只支持可完整枚举 input values 的 scalar state write；
- 不确定 case always-scan；
- 增加 assertion/debug mode，对 skip group 随机抽样执行 shadow check。
- 明确 dirty 是 sticky state，禁止 eval-local dirty；新增 data 先变、clock/event 后到的单测。

### 风险 B：多 writer state 破坏 skip 条件

处理：

- P0 标记 multi-writer；
- P2 首版 multi-writer always-scan；
- 后续若要支持，必须引入 target-state dirty dependency 或同 state writer chain grouping。

### 风险 C：group 数过多导致 active bitset / fanout 开销抵消收益

处理：

- P4 加 `maxCommitReaderMaskWordsPerGroup` 和 `maxCommitInputValuesPerGroup`；
- 统计 `commit_group_fanout_entries`；
- gate 中同时看 host time 和 generated code size。

### 风险 D：range helper 降低 checks 但增加 branch/cache 压力

处理：

- P3 单独开关；
- 对比 P2-only 和 P2+P3；
- 不把 range detector 和 dirty gating 绑死。

## 15. 结论

本轮异常的 `runtime_weighted_checks` 主要是 commit detection hotspot，不是 compute DP 权重单点问题。

runtime shadow 结论是：按 dirty mark cost = 1 个 static check unit 估算，selective dirty gating 有 `13.58%` commit detection weighted checks 收益；但收益高度不均匀，统一启用会让 `261` 个 row 变慢。没有 profiling / runtime hint 时，静态规则无法可靠判断哪些 group 真正收益为正。

因此本文方案不继续推进。保留结论如下：

- commit detection 是真实 hotspot，后续优化仍应优先关注 commit 侧。
- dirty gating 只有在有 profiling / runtime hint、并能按 supernode/group 做 profitability gate 时才有明确收益依据。
- 当前不做 dirty gating 默认实现，不做静态猜测式 enable，不继续按 P1 -> P2 -> P3 -> P4 落地本文方案。
- 本文产出的静态/runtime JSON 诊断结果只作为问题分析依据保留。
