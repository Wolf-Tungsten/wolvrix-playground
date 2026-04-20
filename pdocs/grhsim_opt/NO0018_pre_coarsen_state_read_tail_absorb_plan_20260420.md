# NO0018 Pre-Coarsen State-Read Tail-Absorb Plan

## 背景

观察 `grhsim` 当前生成代码后，可以看到一类额外 fixed-point 传播：

1. `commit_state_updates()` 在状态变化后先激活包含 `RegisterReadPort` / `LatchReadPort` 的 read-head supernode
2. read-head supernode 执行，把 read result 更新出来
3. read result 再经 `value_fanout` 激活真正的 consumer supernode

对 `register read` / `latch read` 来说，这里的读取语义是幂等的，因为调度阶段只写 next-state shadow，真正的 state 更新发生在所有 scheduled supernode 执行完成后的 commit 阶段。因此，同一轮内把同一个 state read 复制进多个 consumer supernode，不会改变语义，但有机会去掉“中间 read-head supernode”这一跳。

## 目标

把 `RegisterReadPort` / `LatchReadPort` 的“吸收并复制”前移到 `activity-schedule` 的早期 special partition 阶段。

具体落点：

- 在 `initialPartition` 完成之后
- 在 coarsen / DP 之前
- 只处理 `kRegisterReadPort` / `kLatchReadPort`
- 第一版不处理 `kMemoryReadPort`

## 为什么不直接塞进当前 tail merge reverse topo 扫描

当前 `buildTailPartition()` 的数据结构默认：

- 一个 topo op 只属于一个 cluster
- reverse topo 扫描期间不会改 graph 结构

而“read 吸收并复制”需要：

- 同一个 read op 可被复制到多个 target cluster
- 在 graph 上创建 clone op / clone result
- 重写 target user operand
- 可能删除原 read op

这已经不是纯 partition merge，而是 graph rewrite。若直接嵌进 `buildTailPartition()`，当前 `ActivityOpData`、topoPos 和 user 关系会在扫描过程中失效，复杂度会明显上升。

因此，更稳的实现方式是：

1. 先完成 `sinkPartition + tailPartition + initialPartition`
2. 基于 `initialPartition` 的 cluster 形状执行一次 state-read-tail-absorb graph rewrite
3. rewrite 完成后重新 freeze / rebuild `ActivityOpData`
4. 继续 coarsen / DP

## 范围约束

第一版只处理：

- `kRegisterReadPort`
- `kLatchReadPort`

第一版明确不处理：

- `kMemoryReadPort`

原因是 `memory read` 当前不仅是幂等读取，还承担“按地址过滤状态变化传播”的作用。若简单复制到所有 consumer supernode，会把“某一 row 改变但当前读取地址结果未变”的场景也提前放大成 consumer supernode 激活，容易引入过度激活。

## 拟议流程

新增一个早期阶段，暂定名为 `state-read-tail-absorb`。

输入：

- 当前 graph
- `initialPartition`
- 基于 `initialPartition` 生成的 symbol cluster 映射
- `ActivityOpData`

处理逻辑：

1. 扫描所有 `RegisterReadPort` / `LatchReadPort`
2. 读取其唯一 result 的 users
3. 按 user 所属 cluster 分桶
4. 对每个 foreign cluster clone 一份 read op
5. 将该 cluster 内对应 users 的 operand 改接到 clone result
6. 若原 read 在 owner cluster 内已无本地 user，且其 result 不是 observable boundary value，则删除原 read
7. 将 clone symbol 追加到 target cluster；若原 read 被删，则从 owner cluster 中移除原 symbol
8. 阶段结束后重新 freeze，重新构建 `ActivityOpData`，并把 symbol cluster 重新 materialize 成 `WorkingPartition`

## 删除原 read 的判定

原 read 可以删除，当且仅当：

- 没有 owner cluster 内本地 user
- read result 不在 observable boundary set 中

其中 observable boundary set 至少包括：

- graph output port values
- graph inout port 的 `out` / `oe`

如果 read result 直接对外可见，则必须保留原 read。

## 预期收益

### 调度结构侧

- 减少独立 read-head supernode 数量
- 让 `state_read_supernodes` 更接近真实 consumer supernode 集合
- 减少由 read result 引入的跨-supernode `value_fanout`

### emit/runtime 侧

- commit 后可直接激活 consumer supernode，而不是先激活中间 read-head supernode
- 减少一轮 fixed-point 传播
- 减少只承担读状态和转发 fanout 的 supernode 执行

## 代价

- 某些 consumer supernode 的 member 数会增加
- 某个 state 对应的 `state_read_supernodes[state]` 激活目标可能变多
- 但这批 consumer supernode 原本就会被 read-head 间接激活，属于把中间层折叠掉而不是新增最终工作量

## 实施项

1. 在 `ActivityScheduleOptions` 增加开关和阈值：
   - `enableStateReadTailAbsorb`
   - `stateReadTailAbsorbMaxTargets`
2. 在 pass 参数解析中加入对应 CLI 选项
3. 在 `activity_schedule.cpp` 新增早期 absorb 阶段与相关 helper
4. 在 coarsen 前插入该阶段，并在阶段后 rebuild `ActivityOpData` / partition
5. 补 `activity-schedule` 单测：
   - register read 跨两个 consumer cluster 的 clone/吸收
   - latch read 跨 cluster 的 clone/吸收
   - read 直接连 output 时原 read 保留
   - memory read 行为不变

## 验收标准

- `RegisterReadPort` / `LatchReadPort` 跨 cluster 扇出时，不再形成中间 read-only supernode
- 最终 `state_read_supernodes` 直接指向 consumer 所在 supernode
- 相关 `value_fanout` 边减少
- 现有 `activity-schedule` / `grhsim-cpp` 行为保持正确

## 增量更新 2026-04-20：实现后 XiangShan CoreMark 50k 对齐复测

### 本次运行

- 命令：

```bash
make -j2 run_xs_wolf_grhsim_emu \
  RUN_ID=20260420_codex_state_read_tail_absorb_50k \
  XS_SIM_MAX_CYCLE=50000 \
  XS_COMMIT_TRACE=0 \
  XS_PROGRESS_EVERY_CYCLES=5000
```

- 日志：
  - [`../../build/logs/xs/xs_wolf_grhsim_20260420_codex_state_read_tail_absorb_50k.log`](../../build/logs/xs/xs_wolf_grhsim_20260420_codex_state_read_tail_absorb_50k.log)

### 结果摘要

- 本次实现后的 `grhsim` 仍可稳定推进到 `50000-cycle` 上限
- 最终统计与最近几轮 `50k` 对齐复测保持相同功能口径：
  - `instrCnt = 73580`
  - `cycleCnt = 49996`
  - `Host time spent = 740997 ms`
- 这说明“pre-coarsen state-read tail absorb”没有破坏当前 `XiangShan coremark` 的 `50k` 功能对齐

### 与最近几轮 50k 结果对比

对比对象统一选用同口径的 `50000-cycle` XiangShan `grhsim` 运行：

- [`NO0011 当前 GrhSIM XiangShan CoreMark 50k Runtime Snapshot`](./NO0011_current_grhsim_xiangshan_coremark_50k_runtime_snapshot_20260420.md)：`560738 ms`
- [`NO0013 当前 GrhSIM XiangShan CoreMark 50k Aligned Rerun`](./NO0013_current_grhsim_xiangshan_coremark_50k_aligned_rerun_20260420.md)：`781443 ms`
- [`NO0014 Persistent Wide BitInt Storage 50k Alignment`](./NO0014_persistent_wide_bitint_storage_50k_alignment_20260420.md)：`748748 ms`
- [`NO0015 Remove BitInt Words-Only 50k Alignment`](./NO0015_remove_bitint_words_only_50k_alignment_20260420.md)：`730523 ms`
- [`NO0016 Disable Single-User Inline 50k Alignment`](./NO0016_disable_single_user_inline_50k_alignment_20260420.md)：`767220 ms`
- [`NO0017 Current Words-Only Selective-Inline 59k Snapshot`](./NO0017_current_words_selective_inline_59k_snapshot_20260420.md) 的 `50k checkpoint`：`734869 ms`

本次结果：

| 对比对象 | `50k host time` | 相对本次差值 |
| --- | ---: | ---: |
| `NO0011` | `560738 ms` | 本次慢 `180259 ms`，约 `+32.14%` |
| `NO0013` | `781443 ms` | 本次快 `40446 ms`，约 `-5.18%` |
| `NO0014` | `748748 ms` | 本次快 `7751 ms`，约 `-1.04%` |
| `NO0015` | `730523 ms` | 本次慢 `10474 ms`，约 `+1.43%` |
| `NO0016` | `767220 ms` | 本次快 `26223 ms`，约 `-3.42%` |
| `NO0017` `50k checkpoint` | `734869 ms` | 本次慢 `6128 ms`，约 `+0.83%` |

### 当前判断

- 从结构量化上看，这次改动并没有把 supernode 图进一步压小，反而让最终 supernode 数和 supernode 间 DAG 边数都出现了小幅上升，见下节。
- 从功能上看，这次“把 `register/latch read` 吸收到 consumer supernode，并前移到 coarsen / DP 之前”的实现是安全的；`50k` 结果仍与最近几轮对齐在同一 `instrCnt / cycleCnt`。
- 从性能上看，这个改动没有带来可见收益，当前结果反而略慢于 `NO0015` 与 `NO0017`：
  - 相对 `NO0015` 慢约 `1.43%`
  - 相对 `NO0017` 的 `50k checkpoint` 慢约 `0.83%`
- 但它仍优于 `NO0013 / NO0014 / NO0016` 这些更慢的 emitter 变体，因此可以判断：
  - 该优化本身没有造成灾难性性能回退
  - 但“减少 read-head supernode 一跳 fixed-point 传播”这一收益，在当前 XiangShan `50k` 窗口里不足以抵消它引入的其他代价

### 超节点数量与超节点间边数量量化

为避免把旧的 `activity_schedule_supernode_stats.json` 误当成新结果，这里额外补了一次 emit：

```bash
make xs_wolf_grhsim_emit RUN_ID=20260420_codex_state_read_tail_absorb_stats
```

对比口径：

- 改动前基线：[`../../build/logs/xs/xs_wolf_grhsim_build_20260419_152314.log`](../../build/logs/xs/xs_wolf_grhsim_build_20260419_152314.log)
- 改动后统计：[`../../build/logs/xs/xs_wolf_grhsim_build_20260420_codex_state_read_tail_absorb_stats.log`](../../build/logs/xs/xs_wolf_grhsim_build_20260420_codex_state_read_tail_absorb_stats.log)
- 当前 stats 文件：[`../../build/xs/grhsim/grhsim_emit/activity_schedule_supernode_stats.json`](../../build/xs/grhsim/grhsim_emit/activity_schedule_supernode_stats.json)

量化结果如下：

| 指标 | 改动前 | 改动后 | 变化量 |
| --- | ---: | ---: | ---: |
| `supernodes` | `77272` | `80343` | `+3071`，约 `+3.97%` |
| `dag_edges` | `1252417` | `1289958` | `+37541`，约 `+3.00%` |

同一次对比里还能看到几个相关侧证：

- `state_read_tail_absorb_cloned = 549615`
- `state_read_tail_absorb_erased = 300568`
- `eligible_ops` 从 `5463193` 增加到 `5712240`
- `ops_p99` 从 `72` 增加到 `92`
- `ops_max` 从 `4096` 增加到 `25574`

这些数字说明当前实现虽然消掉了一批原始 read-head，但没有把最终 supernode 图压扁，反而引入了更多 cluster/supernode 分裂与更多跨 supernode 连接：

1. supernode 数增加 `3071`，说明“把 read 合进去”没有转化为更少的最终调度单元，coarsen / DP 后反而保留了更多 supernode。
2. supernode 间边数增加 `37541`，说明 read clone 后并没有减少最终 DAG 连边总量；至少在 XiangShan 这个实例上，跨 supernode 传播关系整体更稠密了。
3. `ops_p99` 和 `ops_max` 同时抬升，说明一部分 consumer supernode 确实被“喂胖”了，但这并没有换来全局 supernode 数下降。

因此，当前 `50k` runtime 没有收益，和结构量化是相互印证的：这次改动减少的是一部分“中间 read-head 跳转”，但在最终图上换来的却是“更多 supernode + 更多 supernode 间边 + 更胖的局部 supernode”。在这个 workload 上，后者显然没有被前者抵消。

### 可能原因

结合实现方式，当前更可能的解释是：

1. `state_read_supernodes[state]` 在 commit 后会直接激活更多 consumer supernode，减少了中间 read-head，但也放大了 commit 时的激活目标集合。
2. read clone 进入 consumer supernode 后，consumer supernode member 数变大，局部执行体更重。
3. 当前窗口内，原先 read-head supernode 的运行成本并没有高到足以覆盖以上新增代价。

也就是说，这次改动更像是把一部分“中间调度成本”换成了“更早、更宽的直接激活 + 更胖的 consumer supernode”，在这个 workload 上净收益暂时没有体现出来。

### 结论

- 功能结论：通过。`50k-cycle` XiangShan `grhsim` 运行正常完成，功能口径未变。
- 性能结论：暂未验证出正收益。当前版本 `740997 ms`，略慢于当前最优附近的 `NO0015 / NO0017`。
- 后续方向：
  - 若继续保留这条路线，需要补更细的 activity / fixed-point / commit 激活统计，确认慢点究竟落在 commit 激活放大，还是 supernode 体积膨胀。
  - 如果只是追求当前 `50k` runtime 最优，这个改动不应直接视为性能正向优化完成态。

## 增量更新 2026-04-20：定位 over-cloning 根因并彻底修复

上面这一版实现随后被证明有明显缺陷：`state-read-tail-absorb` 是按 `initialPartition` 的 seed cluster 做 target 分桶的，而不是按接近最终 supernode 的粒度分桶。

在 XiangShan `SimTop` 上，这意味着 absorb 发生时面对的是：

- `seed_supernodes = 4538037`
- 而最终只有 `~8e4` 级别 supernode

也就是说，clone target 的粒度比最终 supernode 细了约两个数量级，导致同一批原本会在后续 `coarsen / DP` 中重新合并的 consumer，也会被提前拆成多个 clone target，形成过度复制。

### 修复思路

修复后的实现不再直接把 `initialPartition` 当作 absorb target，而是先基于当前图对 partition 做一次“预测最终分区”的 dry-run：

1. 从 `initialPartition` 出发
2. 先跑一轮不改图的 `coarsen` 合并
3. 再跑一轮不改图的 `DP/refine` 分段
4. 用这份更接近最终 supernode 的 target partition 去做 `state-read-tail-absorb`

这样 absorb 时的 target 粒度就从 `4538037` 个 seed cluster，收敛到与旧版最终 supernode 数接近的 `77272` 个 target supernode，避免了在 seed 粒度上的系统性 over-cloning。

### 修复后结构量化

本次修复对应的 emit 统计：

```bash
make xs_wolf_grhsim_emit RUN_ID=20260420_codex_state_read_tail_absorb_fix_stats
```

日志：

- 修复后 build log：[`../../build/logs/xs/xs_wolf_grhsim_build_20260420_codex_state_read_tail_absorb_fix_stats.log`](../../build/logs/xs/xs_wolf_grhsim_build_20260420_codex_state_read_tail_absorb_fix_stats.log)
- 当前 stats 文件：[`../../build/xs/grhsim/grhsim_emit/activity_schedule_supernode_stats.json`](../../build/xs/grhsim/grhsim_emit/activity_schedule_supernode_stats.json)

对比三组口径：

- 旧基线：[`../../build/logs/xs/xs_wolf_grhsim_build_20260419_152314.log`](../../build/logs/xs/xs_wolf_grhsim_build_20260419_152314.log)
- 第一次错误实现：[`../../build/logs/xs/xs_wolf_grhsim_build_20260420_codex_state_read_tail_absorb_stats.log`](../../build/logs/xs/xs_wolf_grhsim_build_20260420_codex_state_read_tail_absorb_stats.log)
- 修复后实现：[`../../build/logs/xs/xs_wolf_grhsim_build_20260420_codex_state_read_tail_absorb_fix_stats.log`](../../build/logs/xs/xs_wolf_grhsim_build_20260420_codex_state_read_tail_absorb_fix_stats.log)

| 指标 | 旧基线 | 第一次错误实现 | 修复后实现 |
| --- | ---: | ---: | ---: |
| `supernodes` | `77272` | `80343` | `75620` |
| `dag_edges` | `1252417` | `1289958` | `1186097` |
| `eligible_ops` | `5463193` | `5712240` | `5666859` |
| `state_read_tail_absorb_cloned` | `0` | `549615` | `371697` |
| `state_read_tail_absorb_erased` | `0` | `300568` | `168031` |

相对旧基线，修复后实现的最终图反而更小：

- `supernodes`: `77272 -> 75620`，减少 `1652`，约 `-2.14%`
- `dag_edges`: `1252417 -> 1186097`，减少 `66320`，约 `-5.30%`

同时，相对第一次错误实现，修复后：

- `state_read_tail_absorb_cloned` 从 `549615` 降到 `371697`
- `supernodes` 从 `80343` 降到 `75620`
- `dag_edges` 从 `1289958` 降到 `1186097`

这基本可以确认：之前 supernode 反而变多，确实不是方案本身必然失败，而是 target 粒度选错导致的 over-cloning。

### 修复后 XiangShan CoreMark 50k 复测

命令：

```bash
make -j2 run_xs_wolf_grhsim_emu \
  RUN_ID=20260420_codex_state_read_tail_absorb_fix_50k \
  XS_SIM_MAX_CYCLE=50000 \
  XS_COMMIT_TRACE=0 \
  XS_PROGRESS_EVERY_CYCLES=5000
```

日志：

- [`../../build/logs/xs/xs_wolf_grhsim_20260420_codex_state_read_tail_absorb_fix_50k.log`](../../build/logs/xs/xs_wolf_grhsim_20260420_codex_state_read_tail_absorb_fix_50k.log)

结果：

- `instrCnt = 73580`
- `cycleCnt = 49996`
- `Host time spent = 593873 ms`

功能口径与前几轮保持一致，但 runtime 明显好于第一次错误实现：

- 相对第一次错误实现 `740997 ms`，本次快 `147124 ms`，约 `-19.85%`
- 相对 `NO0011` 的 `560738 ms`，本次仍慢 `33135 ms`，约 `+5.91%`

### 修复后结论

- 严格说，之前“supernode 变多”的现象来自实现缺陷，而不是方案方向错误。
- 在把 absorb target 从 seed cluster 改成“预测最终 supernode”之后，这条路线重新符合原始预期：
  - 最终 supernode 数下降
  - supernode 间边数下降
  - `50k` runtime 从 `740997 ms` 回落到 `593873 ms`
- 当前版本虽然还没有超过 `NO0011` 的 `560738 ms`，但已经从“负优化”回到“明确正向”的区间，可以继续沿这条路线做后续细化。
