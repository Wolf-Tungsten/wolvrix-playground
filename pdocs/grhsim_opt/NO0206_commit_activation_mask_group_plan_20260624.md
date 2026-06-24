# NO0206 Commit Activation Mask Group Plan

记录日期：2026-06-24
状态：已尝试，负收益；代码已回退，文档保留
关联：[`NO0189`](./NO0189_grhsim_gsim_supernode_cost_tsv_instrument_plan_20260611.md)、[`NO0190`](./NO0190_grhsim_gsim_unified_cost_model_comp_src_sink_plan_20260612.md)、[`NO0198`](./NO0198_xiangshan_coremark50k_runtime_profile_no_preserve_20260615.md)、[`NO0200`](./NO0200_commit_shared_guard_group_emit_plan_20260615.md)

## 结论

2026-06-24 已实现第一版 exact-mask grouping 并在完整 XiangShan CoreMark 50k 上验证。结果功能等价，
但仿真速度明显下降。相关代码修改已回退，回退后在 xrdp 高 CPU 负载解除后复测恢复到历史 baseline
同档，因此本特性不启用，仅保留本文档作为尝试记录。

初始对比结果：

| 版本 | RUN_ID / log | Host time | Guest cycle | 速度 | instrCnt / cycleCnt / IPC |
| --- | --- | ---: | ---: | ---: | --- |
| baseline | `20260623_grhsim_coremark50k_rebuild` | 320285ms | 50001 | 156.1 cycle/s | `73580 / 49996 / 1.471718` |
| NO0206 exact-mask grouping | `no0206_commit_activation_group_coremark50k_20260624_152005` | 603451ms | 50001 | 82.9 cycle/s | `73580 / 49996 / 1.471718` |

NO0206 版本相对 2026-06-23 baseline 慢约 1.88x。由于 guest 指令数、cycle 数和 IPC 一致，这次问题不是
功能错误，而是 host 执行成本上升。

回退后复测：

| 版本 | RUN_ID / log | Host time | Guest cycle | 速度 | instrCnt / cycleCnt / IPC |
| --- | --- | ---: | ---: | ---: | --- |
| NO0206 code reverted, xrdp load cleared | `no0206_reverted_rerun_coremark50k_20260624_171347` | 319248ms | 50001 | 156.6 cycle/s | `73580 / 49996 / 1.471718` |
| NO0206 code reverted | `no0206_reverted_coremark50k_20260624_162359` | 597649ms | 50001 | 83.7 cycle/s | `73580 / 49996 / 1.471718` |
| 2026-06-23 saved binary, current env | `rtprofile_20260623_current_env_50k_20260624_165617` | 651058ms | 50001 | 76.8 cycle/s | `73580 / 49996 / 1.471718` |

回退版源码确认 `wolvrix` 子模块无代码改动，生成代码中没有 `grhsim_commit_changed_*` / `group_changed`
标记，编译文件列表与 2026-06-23 baseline 一致。`597649ms` / `651058ms` 两次结果受当时 xrdp 高 CPU
负载污染；负载解除后复跑 `319248ms`，与 2026-06-23 baseline `320285ms` 等价，确认回退后性能恢复。

静态检查显示，当前 exact-mask grouping 过于碎片化：

- 生成 `20749` 个 `grhsim_commit_changed_*` group / flush `if`。
- 生成 `105064` 次 group flag set。
- group size 均值 `5.06`，p50 `3`，p90 `10`，p99 `32`，max `108`。
- `9490` 个 group size 为 `2`，`14219` 个 group size 不超过 `4`，`18225` 个 group size 不超过 `8`。
- mask entries 均值 `1.89`，p50 `2`，p90 `3`，p99 `8`，max `23`。

负收益的主要原因是多数 group 太小：每条 write 仍要执行 changed 判断和 state update，还额外引入
`bool` 初始化、flag store、group flush branch。被删除的重复 OR active mask 成本不足以覆盖这些新增成本。

阈值控制可能让少数大 group 留下正收益，但不能直接按 group size 判断。更合理的结构收益过滤应同时考虑
write 数和 mask entry 数，例如：

```text
(n_writes - 1) * mask_entries >= n_writes + 2 + margin
```

按静态数据粗估，`margin=8` 只保留约 `760` 个 group / `7569` 条 write，`margin=16` 只保留约
`194` 个 group / `2131` 条 write，`margin=32` 只保留约 `32` 个 group / `341` 条 write。这个方向
即使可能有局部正收益，也必须先做 dry-run/runtime changed-count profile，再做 A/B 实测，不能默认启用。

以下为原始方案记录，保留用于后续重新评估。

当前 GrhSIM 的 `a_succ` 高值主要来自 commit 阶段的 state write reader activation。下一步优化应优先做
**commit activation mask grouping**：把同一 commit 作用域内、reader activation mask 完全相同的 state writes
合并成一个 activation group。组内每条 write 仍按原顺序执行 change detection 和 state update，但只累计
`group_changed`；组尾若任意 state changed，再统一 OR 一次 shared reader mask。

这个方向的第一版应只做“相同 activation mask 精确合并”，不先做按 state family / memory bank 的粗粒度合并。
相同 mask 合并不改变被激活的 reader 集合，只删除重复 OR active bits，是低风险的 codegen 优化。

## Profile 依据

本轮 profile 产物：

```text
build/logs/xs/runtime_profile_20260623/
```

核心对比：

| 指标 | GSIM | GrhSIM | 比例 |
| --- | ---: | ---: | ---: |
| static `a_succ_total` | 434,702 | 1,275,142 | 2.93x |
| runtime `sum(f*a_succ)` | 3,762,489,186 | 25,491,064,157 | 6.78x |
| `a_succ` work / fire | 4.91 | 27.93 | 5.69x |

GrhSIM 分 phase：

| phase | rows | static `a_succ` | fire | runtime `sum(f*a_succ)` | max `a_succ` |
| --- | ---: | ---: | ---: | ---: | ---: |
| compute | 72,180 | 984,611 | 903,887,033 | 11,335,969,937 | 108 |
| commit | 502 | 290,531 | 8,942,500 | 14,155,094,220 | 42,937 |

虽然 commit 行数很少，但 runtime activation work 已超过 compute，是本轮最明确的优化入口。

典型热点：

| supernode | phase | fire | `a_succ` | `f*a_succ` |
| ---: | --- | ---: | ---: | ---: |
| 72180 | commit | 50,050 | 42,937 | 2,148,996,850 |
| 72393 | commit | 50,050 | 18,439 | 922,871,950 |
| 72217 | commit | 50,050 | 5,130 | 256,756,500 |
| 多个 commit supernode | commit | 50,050 | 4,096 | 205,004,800 / row |

这类热点说明 GrhSIM 当前存在大量 per-write reader activation 重复工作。

## 当前 `a_succ` 口径

GrhSIM 侧 `a_succ` 当前在 `wolvrix/lib/emit/grhsim_cpp.cpp` 的 `buildRuntimeProfileWeights()` 中静态统计：

- 每个 op result 如果命中 `model.boundaryFanoutByValue[result]` 且 fanout 非空，`a_succ += 1`。
- 每个 write port op 如果 `model.stateHeadSupernodesBySymbol[write.symbol]` 非空，`a_succ += 1`。

因此 `a_succ` 不是 fanout length，也不是真实 OR 的 mask entry 数。对 commit 而言，`a_succ=42937` 表示
该 commit supernode 中有 42,937 个 write-port activation points，而不是某一个 write 有 42,937 个 reader。

这个定义对定位“重复 activation 检查点”有用，但优化后需要补充新的统计列，否则 TSV 仍会显示旧静态上界。

## 问题形态

当前 commit write 的基本形态是每条 state write 独立判断 changed，并立即激活 readers：

```cpp
if (state_changed) {
    emitActivationStatements(stateHeadSupernodesBySymbol[write.symbol]);
}
```

当很多 scalar state writes 的 reader set 相同或高度重复时，会形成：

```cpp
if (write0_changed) { OR same_reader_mask; }
if (write1_changed) { OR same_reader_mask; }
if (write2_changed) { OR same_reader_mask; }
...
```

这些 OR 操作的目标 active bits 相同，重复执行没有额外语义，只增加 commit runtime、分支和 generated code 压力。

## 方案

### 1. 构造 ActivationKey

对每个 commit write，根据写入 symbol 找到 reader heads：

```text
stateHeadSupernodesBySymbol[write.symbol]
```

再用现有 active mask 表达能力生成稳定 key，例如：

```text
ActivationKey = vector<ActiveMaskEntry>
```

同一 key 表示最终会 OR 到完全相同的一组 `supernode_active_curr_` word/mask。

### 2. 同一 commit 作用域内按 key 分组

第一版作用域保持保守：

- 不跨 commit supernode。
- 不跨 event edge / event guard 作用域。
- 不跨 runtime trace、profile side effect 或其它非 write side effect。
- 组内 write update 顺序保持原始顺序。

生成代码目标形态：

```cpp
bool group_changed_0 = false;

// write A
if (state_A_changed) {
    group_changed_0 = true;
}

// write B
if (state_B_changed) {
    group_changed_0 = true;
}

if (group_changed_0) {
    commit_activated_readers_ = true;
    OR shared_reader_mask_0;
}
```

对不同 activation mask 的 writes 使用不同 `group_changed_N`。没有 readers 的 writes 不进组，保持现状。

### 3. 先复用/扩展 direct commit scalar helper

当前代码已有 `DirectCommitScalarStateWriteDesc::activationEntries`，并存在
`apply_commit_scalar_state_write_*_range` 一类 helper 名称。这个路径适合作为第一批落地点：

- 对 direct scalar commit writes 按 `activationEntries` 分段或分组。
- helper 内循环执行每条 write 的 changed/update。
- helper 局部累计 `anyStateChanged`。
- 组尾统一 OR `activationEntries`。

需要先检查并修正 helper 使用条件；当前 `modelUsesCommitScalarStateWriteKind(...)` 直接返回 `false`，意味着相关
helper declaration / fast path 可能未真正启用。

### 4. generalized emitter path

在 scalar helper 外，再给普通 commit write path 增加通用 grouping：

```text
collect writes in current commit scope
for each write:
  compute ActivationKey
  assign group id
emit writes in original order:
  on changed: group_changed[group_id] = true
after scope:
  for each group_changed:
    emitActivationStatements(shared mask)
```

如果 group 数过多、存在难以证明安全的 side effect、或 write kind 暂不支持 grouping，则局部 fallback 到旧路径。

## 正确性约束

该优化依赖以下事实：

- active bit OR 是幂等的，同一个 reader mask 被 OR 多次与 OR 一次在最终 active set 上等价。
- commit write 的 state update 顺序必须保持，不能因为 grouping 重排 writes。
- activation 可以延迟到同一 commit scope 末尾，但必须发生在下一轮 pending/active 检查之前。
- `commit_activated_readers_` 的语义应从“某条 write 激活了 reader”变成“某个 activation group 在本 scope 末尾激活了 reader”，不能漏置。

第一版只合并 identical reader mask，因此不会引入 over-activation。后续如果做 state family / memory bank 粗粒度合并，
会产生 over-activation；这可能仍然语义正确，但需要独立 profile 验证，不能混入第一版结论。

## Instrumentation 更新

建议先把 profile 列拆开，避免继续用单个 `a_succ` 混淆不同来源：

| 新列 | 含义 |
| --- | --- |
| `a_succ_value` | compute result 命中 `boundaryFanoutByValue` 的 activation points |
| `a_succ_state_write` | write port 命中 `stateHeadSupernodesBySymbol` 的 activation points |
| `a_succ_group` | grouping 后实际发射的 activation groups |
| `a_succ_mask_entries` | 可选，实际 OR 的 word/mask entry 数，用于评估 helper 成本 |

在实现前可以先做 emit-time dry-run report：

```text
supernode_id, phase, state_write_activation_points, unique_activation_masks, largest_mask_group
```

这能直接估算 `42937 -> unique_masks` 的上限收益，避免先写完整 runtime path。

## 实施阶段

### Phase 0：dry-run 画像

- 对 commit supernode 统计 `state_write_activation_points` 与 `unique_activation_masks`。
- 输出 top commit supernode 的 group 分布。
- 验证热点 `72180` / `72393` 是否主要由少数 activation masks 构成。

### Phase 1：direct scalar exact-mask grouping

- 启用或修正 direct commit scalar write helper 的使用条件。
- 只处理 direct scalar state writes。
- 按 identical `activationEntries` 精确分组。
- 保持 fallback 到旧 per-write activation。

### Phase 2：普通 commit write path grouping

- 抽象 `ActivationKey` 与 group id 分配。
- 对 register/latch scalar writes 扩展 grouping。
- 确认 memory write、wide state write、shadow write 有无额外 side effect；不能证明安全时继续旧路径。

### Phase 3：memory / reg-to-mem 方向

- 对 `reg-to-mem` intent/real merge 产物评估按 memory row/bank 的 activation grouping。
- 仅在 exact-mask grouping 收益不够时，再评估更粗粒度的 state family grouping。
- 粗粒度 grouping 必须单独记录 over-activation 比例和 runtime 结果。

## 验收

### 单元和结构

- 新增 emit 单测：两条 state writes 共享 reader mask 时，只生成一个 activation group。
- 新增 emit 单测：两条 state writes reader mask 不同时，生成两个 activation groups。
- 新增 emit 单测：无 reader write 不产生 group。
- `ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp'` 通过。

### XiangShan profile

用同一 CoreMark 50k workload 复测：

- `static a_succ_state_write` 保持可解释。
- `a_succ_group` 在 commit 热点上显著小于旧 `a_succ`。
- `sum(f*a_succ_group)` 的 commit 部分相对 `14.16B` 明显下降。
- 50k runtime 不应相对当前 no-profile 快档回退。

### 正确性

- XiangShan CoreMark 20k difftest 先通过。
- 50k 跑到 cycle limit，不出现 `ABORT` / `MISMATCH` / `FAIL`。
- 如涉及 memory/write shadow path，再补对应 xs-components case。

## 风险

- 如果 activation 被延迟到 scope 末尾后，某些当前代码在同一 scope 内读取 active bits，会改变行为。实施前必须确认
  `supernode_active_curr_` 只在 scope 结束后的调度检查中被观察。
- 如果 group 穿过 trace/profile side effect，统计粒度可能变化。第一版遇到 side effect 应断组。
- 如果 unique activation masks 数量接近 write 数，收益有限，还会增加 local bool 压力。应设置结构阈值，超过阈值 fallback。
- 旧 `a_succ` 统计不随 codegen grouping 自动下降；必须同步更新 profile schema，否则后续分析会误判。

## 与 NO0200 的关系

`NO0200` 合并的是共享 write guard，减少重复 `if (cond)` 和 commit code shape 压力。本文合并的是共享 reader
activation mask，减少 changed 后重复 OR active bits。二者正交，可以叠加：

```text
shared guard grouping:        many writes share updateCond
activation mask grouping:     many writes share reader activation mask
```

后续实施时应保持两者的作用域一致性：guard group 可以作为 activation grouping 的外层 scope，但 activation grouping
仍以 identical reader mask 为 correctness boundary。
