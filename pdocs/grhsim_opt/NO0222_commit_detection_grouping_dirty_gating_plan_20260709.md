# NO0222 Commit Detection Grouping + Dirty Gating Plan

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

建议 schema：

```json
{
  "format": "wolvrix.grhsim-commit-detection-stats.v1",
  "sim": "grhsim",
  "top": "SimTop",
  "summary": {
    "commit_supernodes": 497,
    "detection_points": 268310,
    "reader_mask_groups": 0,
    "range_compressible_points": 0
  },
  "commit_supernodes": [
    {
      "sim": "grhsim",
      "top": "SimTop",
      "supernode_id": 71871,
      "detection_points": 42937,
      "commit_compute_edges": 11982,
      "input_values": 0,
      "reader_mask_unique_count": 0,
      "state_symbol_top": [],
      "range_candidates": []
    }
  ]
}
```

P0 需要至少统计：

- `detection_points`
- `commit_compute_edges`
- `input_values`
- `reader_mask_unique_count`
- `reader_mask_group_sizes`
- `state_symbol_top`
- `storage_kind_top`
- `scalar_width_top`
- `range_compressible_points`
- `shared_cond_groups`
- `shared_mask_groups`
- `multi_writer_state_count`
- `always_scan_reason_counts`

### 6.2 P0 验收

- 不改变 `grhsim_static_stats.json`。
- 不改变 `grhsim_runtime_stats.json`。
- XiangShan CoreMark 50k host time 只允许诊断开关打开时有可解释开销；默认关闭时必须无差异。
- top commit supernode `71871` / `72080` 必须能拆出 top state family 和 reader mask 分布。

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

### 8.1 基本思想

每个 commit detection group 维护一个 active flag。只有当该 group 的输入 value 发生变化时，才扫描该 group 的 state write detection points。

伪代码：

```cpp
if (!commit_group_active_[group_id]) {
    return;
}
commit_group_active_[group_id] = false;

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
- event/guard 相关 value；
- 对 memory / dynamic write 的保守依赖。

当 compute supernode 产生这些 value 且 value 实际变化时，置位对应 commit group active flag。

### 8.3 reset / 初始化规则

所有 commit group 在 reset 后必须 active 一次：

```cpp
std::fill(commit_group_active_.begin(), commit_group_active_.end(), true);
```

原因：

- state 初值和 input cache 必须建立一致性；
- 第一轮必须允许 state write detection 正常运行；
- 不能依赖未初始化的 dirty 状态。

### 8.4 正确性条件

P2 的核心正确性判断：

如果一个 commit group 的所有输入 value 相对上次该 group 执行时都没有变化，并且该 group 上次执行后已经完成 state update，那么再次执行该 group 不会产生新的 state change。

这对单 writer / 无跨 group state dependency 的 scalar state write 成立。

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
std::array<std::uint64_t, kCommitGroupActiveWords> commit_group_active_;
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
    commit_group_active_[entry.word_index] |= entry.mask;
}
```

### 8.7 统计更新

官方 `grhsim_runtime_stats.json` 的 `activation_count` 应继续表示实际执行的 supernode/group 次数。P2 开启后，如果 commit group 被跳过，则不增加 activation_count。

如果 P2 引入 commit group 但不改变 official supernode id，需要额外定义 group-level diagnostic。建议不要污染主 schema，新增：

```text
grhsim_commit_detection_runtime_stats.json
```

字段：

- `commit_group_id`
- `owner_supernode_id`
- `active_count`
- `skip_count`
- `detection_points`
- `executed_weighted_checks`
- `reader_mask_words`

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
6. 同 state 多 writer：fallback always-scan。
7. memory write / dynamic address：fallback always-scan。
8. range detector full mask：批量更新和逐项更新等价。
9. range detector masked：批量 masked update 和逐项更新等价。

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

正确的第一优先级是：

```text
让 commit detection 可跳过，再让可执行的 detection 更成组、更批量。
```

因此建议按 P0 -> P1 -> P2 -> P3 -> P4 推进。P2 dirty gating 是主收益路径；P1 是 P2 的必要结构准备；P3/P4 是进一步压低单次执行成本和控制 group 粒度的补充。
