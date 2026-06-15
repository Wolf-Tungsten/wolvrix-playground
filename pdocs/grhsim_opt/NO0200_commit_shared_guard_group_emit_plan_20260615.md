# NO0200 Commit Shared Guard Group Emit Plan

记录日期：2026-06-15

## 背景

`XsRealFtqMetaQueueResolve` 暴露出一个独立于 preserve-aggregate 的 commit codegen 问题：
SV 已经把 `Vec[64] of Bundle` scalarize 成大量 `kRegisterWritePort` 后，GRH IR 仍能复用同一个
`updateCond` value，但 GrhSIM commit C++ 没有利用这个共享性。

以 slot `17` 为例，GRH JSON 中 `metaQueueResolve_17_*` 共有 `104` 个
`kRegisterWritePort`，它们的 `oper[0]` 全部是同一个 value：

```text
updateCond = _val_62621
_val_62621 = reset || (!reset && io_ctrl[0] && io_in0[5:0] == 6'd17)
```

生成 C++ 中 `_val_62621` 被物化为同一个 bool slot：

```text
_val_62621 -> value_bool_slots_[18]
auto &grhsim_value_8937_0_slot = value_bool_slots_[18];
```

但 commit 写回形态仍是每个 scalar write 各自一层判断：

```cpp
if ((grhsim_value_8937_0_slot) != 0) {
    // op _op_30594 [kRegisterWritePort] reg=metaQueueResolve_17_mbtb_entries_1_2_position
    ...
}
if ((grhsim_value_8937_0_slot) != 0) {
    // op _op_30603 [kRegisterWritePort] reg=metaQueueResolve_17_mbtb_entries_1_2_attribute_branchType
    ...
}
```

同一个 guard 在 `sched_17.cpp` 到 `sched_25.cpp` 中重复出现；`slot 17` 对应 `104` 次
`if ((grhsim_value_8937_0_slot) != 0)`。这会放大 commit 代码体积、分支数量和编译器 CFG 压力。

## 目标

在 `emit_grhsim_cpp` 的 commit 写回阶段识别共享 `updateCond` 的连续写操作，并生成一个外层
guard block：

```cpp
if ((shared_guard) != 0) {
    // write A
    // write B
    // write C
}
```

而不是：

```cpp
if ((shared_guard) != 0) { write A; }
if ((shared_guard) != 0) { write B; }
if ((shared_guard) != 0) { write C; }
```

这个优化只改变 C++ 代码形态，不改变 GRH IR，不改变 scheduling 语义，不要求先解决
`Vec-of-Bundle` scalarization。

## 适用范围

第一阶段只处理 commit sink 中的本地状态写：

- `kRegisterWritePort`
- `kLatchWritePort`
- 后续可评估 `kMemoryWritePort`

分组 key 至少包含：

- 同一个 commit batch / same emitted function
- 同一个 event guard 上下文，例如同一个 posedge scan block
- 同一个 `updateCond` value

不把不同 batch、不同 event edge、不同调度活动块之间的写强行合并。第一版以保守的
“相邻 runs 合并”为主，避免改变原有写顺序。

## 语义约束

1. 写顺序必须保持。
   同一组内部按原 `SinkWrite` / op emission 顺序输出，不做重排。

2. change detection 仍逐写执行。
   每条写内部的 `next_value`、mask merge、`if (state != next_value)`、reader reactivation 和
   `supernode_active_curr_` 标记保持原逻辑。

3. 不跨越可能改变 guard 或写入依赖的语句。
   如果中间存在非写操作、不同 guard、不同事件块、runtime profile 计数、trace 语句或其它 side effect，
   结束当前 group。

4. alias/ref declaration 可以提前，但必须维持 C++ lifetime 合理。
   当前生成代码通常先声明一组 `auto &...`，再逐写 commit；分组只包写动作主体，不要求把所有引用声明搬进
   guard 内。若后续发现声明本身也显著增加编译成本，再单独规划 lazy alias emission。

5. 分组只基于已经 materialized 的 guard expression 或 guard slot。
   不在 commit emitter 内重新构造 guard 表达式，避免引入求值顺序差异。

## 实现计划

### Phase 1：代码形态最小改动

在 `wolvrix/lib/emit/grhsim_cpp.cpp` 的 commit write emission 路径中，把当前逐条写输出改成
run-based 输出：

```text
for writes in commit_supernode:
  collect consecutive writes with same updateCond operand
  if run size >= 2:
    emit one outer if(updateCond)
    emit each write body with per-write guard omitted
  else:
    keep existing single-write shape
```

需要把“写回主体”和“guard 包裹”拆开：

- `emitCommitWriteWithGuard(write)`：当前形态，兼容旧路径。
- `emitCommitWriteBody(write)`：只输出 masked next-value、state update、activation。
- `emitCommitWriteGuardValue(write)`：返回该 write 的 updateCond emitted expression / slot。

### Phase 2：跨 run 的同 guard 合并评估

如果第一版效果明确，再评估更激进的 per-supernode guard buckets：

```text
guard -> ordered list of writes
```

这一步只有在能证明不破坏原写顺序时才做。存在同一 state 多写、不同 write conflict 处理、
profile/trace side effect 时，不做跨 run 分组。

### Phase 3：memory write 形态

`kMemoryWritePort` 除 `updateCond` 外还有 address/data/mask、touched slot 和 memory shadow 逻辑。
可以复用外层 guard，但要先确认：

- guard 为 false 时不会改变 pending write bookkeeping；
- address/data expression 已经在 compute 阶段完成，不依赖 commit side effect；
- multi-write conflict 语义保持不变。

## 验收

### 结构检查

对 `XsRealFtqMetaQueueResolve` 重跑：

```bash
PYTHONPATH=$PWD/wolvrix/build/skbuild/python \
LD_LIBRARY_PATH=$PWD/wolvrix/build/skbuild:$PWD/wolvrix/build \
make -C testcase/xs-components CASE=XsRealFtqMetaQueueResolve grhsim
```

检查 `slot 17`：

```bash
rg -c 'if \(\(grhsim_value_8937_0_slot\) != 0\)' \
  testcase/xs-components/build/XsRealFtqMetaQueueResolve/grhsim/model/grhsim_XsRealFtqMetaQueueResolve_sched_*.cpp
```

当前基线为 `104` 次。Phase 1 期望明显下降；由于当前写分布跨多个 `sched_*.cpp`，不会下降到 `1`，
但每个 contiguous run 应只剩一个外层 `if`。

### 编译检查

```bash
make -C testcase/xs-components CASE=XsRealFtqMetaQueueResolve grhsim
```

### 功能检查

优先跑 xs-component bench：

```bash
make -C testcase/xs-components CASE=XsRealFtqMetaQueueResolve bench
```

如果改动推广到全 XiangShan，再跑对应 `grhsim` smoke / coremark gate。

### 指标检查

记录：

- generated `sched_*.cpp` 总字节数
- `if ((same_guard) != 0)` 计数
- GrhSIM model build time
- xs-component bench runtime
- full XiangShan 20k/50k runtime gate（推广后）

## 风险

- 如果 group 跨越了同一 state 的多写冲突处理，可能改变最后写胜出的顺序。第一版只合并相邻 run，
  并保留原输出顺序，规避该风险。
- 如果原路径在每条写前后插入 trace/profile side effect，外层合并可能改变统计粒度。第一版遇到这些
  side effect 应结束 group。
- 该优化不减少 scalarized state 数量，也不恢复 indexed memory/write 结构；它只是降低共享 guard 下的
  重复 commit 分支开销。根因仍由 NO0197/NO0199 记录的 SV scalarization / aggregate preservation 问题覆盖。

## 与既有文档关系

- [NO0196](./NO0196_two_eval_vs_xiangshan_sink_succ_inconsistency_20260614.md)：指出 FTQ 类
  array-register 展平导致 per-field scalar commit 真开销暴涨。
- [NO0197](./NO0197_ftq_vec_of_bundle_sv_scalarization_rootcause_20260614.md)：定位 preserve-aggregate
  对 FTQ 不起效的输入侧根因。
- [NO0199](./NO0199_firrtl_packed_array_split_in_grhsim_cases_20260615.md)：给出当前 HEAD 可复现的
  Vec-of-Bundle scalarization 事实对比。

本文只规划 emit 侧的共享 guard 分组合并，是上述问题的局部 codegen 缓解，不替代 aggregate 恢复方案。

## 实施记录 2026-06-15

已在 `wolvrix/lib/emit/grhsim_cpp.cpp` 落地：

- commit batch 写回先按同 event run 收集 `WritePortGuardKey`；
- 默认合并相邻同 guard 写口；
- 同一 event run 内按 `condExpr` 做非相邻分桶，把被其它 guard 插开的同 guard 写口合到一个外层 `if`。

这里不额外保护 memory write 或同 target 多写。GRH/硬件语义不应依赖 emitter 的 op 输出顺序；如果同一批写的最终结果受到输出次序影响，问题应由前面的 guard/多驱动语义处理，而不是由 C++ emit 保序兜底。

新增 `emit-grhsim-cpp` 单测覆盖非相邻分桶：`batch_reg0_write` 与 `batch_reg2_write` 共享 guard，中间夹 `batch_reg1_write`，生成代码应把 `reg0/reg2` 放在同一 guard block 内，同时 harness 校验可见状态结果。

验证结果：

```bash
cmake --build wolvrix/build --target emit-grhsim-cpp
ctest --test-dir wolvrix/build --output-on-failure -R emit-grhsim-cpp
cmake --build wolvrix/build/skbuild --target wolvrix-lib
PYTHONPATH=$PWD/wolvrix/build/skbuild/python \
LD_LIBRARY_PATH=$PWD/wolvrix/build/skbuild:$PWD/wolvrix/build \
python3 testcase/xs-components/scripts/emit_grhsim.py ... XsRealFtqMetaQueueResolve ...
PYTHONPATH=$PWD/wolvrix/build/skbuild/python \
LD_LIBRARY_PATH=$PWD/wolvrix/build/skbuild:$PWD/wolvrix/build \
make -C testcase/xs-components CASE=XsRealFtqMetaQueueResolve grhsim
```

`XsRealFtqMetaQueueResolve` 中 `grhsim_value_8937_0_slot` 对应的写 guard 计数：

```text
before: 104
after : 9
```

剩余 `9` 次来自该 case 目前被切成 `sched_17.cpp` 到 `sched_25.cpp` 共 9 个 emitted sched 文件；每个文件内只剩一个共享 guard block。

## XiangShan 50k 复测 2026-06-15

按完整 XiangShan no-preserve-aggregate GrhSIM flow 重新 emit、重新编译 emu，并运行 CoreMark 50k：

```bash
source /home/gaoruihao/wksp/wolvrix-playground/env.sh
make xs_wolf_grhsim_emu \
  RUN_ID=no0200_guardbucket50k_20260615 \
  XS_WOLF_GRHSIM_RESUME_FROM_STATS_JSON=0 \
  XS_SIM_MAX_CYCLE=50000 \
  XS_COMMIT_TRACE=0 \
  XS_PROGRESS_EVERY_CYCLES=5000 \
  WOLVRIX_GRHSIM_WAVEFORM=0 \
  WOLVRIX_GRHSIM_PERF=0

make run_xs_wolf_grhsim_emu \
  RUN_ID=no0200_guardbucket50k_20260615 \
  XS_SIM_MAX_CYCLE=50000 \
  XS_COMMIT_TRACE=0 \
  XS_PROGRESS_EVERY_CYCLES=5000 \
  WOLVRIX_GRHSIM_WAVEFORM=0 \
  WOLVRIX_GRHSIM_PERF=0
```

产物日志：

- build log: `build/logs/xs/xs_wolf_grhsim_build_no0200_guardbucket50k_20260615.log`
- run log: `build/logs/xs/xs_wolf_grhsim_no0200_guardbucket50k_20260615.log`

本轮重新生成，不复用旧 post-stats：

```text
[wolvrix-xs-grhsim] post-stats summary top_total_ops=5268574 top_compute_ops=4376838 top_declaration_ops=287282 top_hierarchy_ops=0 top_values=4677017
[wolvrix-xs-grhsim] activity-schedule supernode stats supernodes=72653 compute_supernodes=72138 commit_supernodes=515 dag_edges=705150 boundary_values=1320493 boundary_activation_edges=2440779 compute_commit_value_pairs=358484 state_read_activation_edges=131628 memory_read_activation_edges=788 ops_max=4096 compute_ops_max=108 commit_ops_max=4096
[wolvrix-xs-grhsim] write_grhsim_cpp done 49950ms
[wolvrix-xs-grhsim] total done 1062242ms
[EXIT] xs_wolf_grhsim_emit 0
```

CoreMark 50k 结果：

```text
[EMU_PROGRESS] host_cycles=50000 model_cycles=50000 instr=73580 commit_pc=0x800012f8 trap_pc=0x80001312 core=0 host_ms=333003
[CYCLE_LIMIT] cycles=50000 max_cycles=50000
Core-0 instrCnt = 73580, cycleCnt = 49996, IPC = 1.471718
Host time spent: 333015ms
```

`EXCEEDING CYCLE/INSTR LIMIT` 是 `-C 50000` 的预期停止条件；本轮退出码为 `0`，日志中未出现
`mismatch` / `abort` / `error`。

与最近同 workload 结果对比：

| run | log | host time | throughput |
| --- | --- | ---: | ---: |
| NO0200 shared guard bucket | `xs_wolf_grhsim_no0200_guardbucket50k_20260615.log` | `333015ms` | `150.14 cycles/s` |
| NO0198 runtime-profile no-preserve | `xs_wolf_grhsim_rtprofile50k_grhsim_run_20260615.log` | `351592ms` | `142.21 cycles/s` |
| no-preserve commit fixed | `xs_wolf_grhsim_no_preserve_commit_fixed_grhsim_run_20260614.log` | `358557ms` | `139.45 cycles/s` |
| 2026-06-10 clean50k | `xs_wolf_grhsim_clean50k_grhsim_20260610.log` | `483944ms` | `103.32 cycles/s` |

相对 `no_preserve_commit_fixed`，本轮 `333015ms` 少 `25542ms`，约 `7.1%` wall-time 收益；
相对 NO0198 的 `351592ms` 少 `18577ms`，约 `5.3%`。这说明共享 guard 合并不是只改善 xs-component
局部 code shape，在完整 XiangShan CoreMark 50k 上也能转化为可测的 runtime 正收益。

## 下一阶段规划：commit supernode 按 event+guard 原子聚合

### 当前结构判断

完整 XiangShan 生成代码中，`eval()` 在 compute batch 之后顺序调用 commit batch：

```cpp
commit_activated_readers_ = false;
this->eval_commit_batch_66();
...
this->eval_commit_batch_141();
pending_eval_round = commit_activated_readers_ || grhsim_any_active_flags(supernode_active_curr_);
```

每个 `eval_commit_batch_N()` 内部再扫描固定 event-driven commit supernode。当前 emit batch 基本以
supernode 为原子；`buildScheduleBatches()` 在 commit phase 下会把每个 commit supernode 作为单独
`Word`，然后把多个 word 合成一个 `eval_commit_batch_N()`。因此 `XsRealFtqMetaQueueResolve` 里
同一个 `grhsim_value_8937_0_slot` 被拆到 `sched_17.cpp` 到 `sched_25.cpp`，主要不是 emit 把一个
commit supernode 拆开，而是 activity schedule 构造 commit supernode 时已经切成了多个 cluster。

当前 `activity_schedule.cpp` 的关键路径是：

```cpp
WorkingPartition sinkPartition =
    buildEventClusteredSinkPartition(graph, opData, sinkTopoPositions, maxCommitOps, &canonicalValues);
```

而 `buildEventClusteredSinkPartition()` 现在只按 `normalizedSinkEventKey(...)` 分桶，再按
`maxOpInCommitSupernode` 做 chunk：

```cpp
key = normalizedSinkEventKey(...)
positionsByKey[key].push_back(topoPos)
...
for (offset += chunkSize)
  partition.clusters.emplace_back(positions[offset:end])
```

也就是说，当前 commit supernode key 只包含 event，不包含 write `updateCond`；同一个 event 下不同
guard 会混在一起，同一个 guard 也可能被 `max_op_in_commit_supernode=4096` 或 emit code-size 间接切成
多个函数。

### 方案

把 commit supernode 的构造从“按 event key + size cap”改成“按 event key + canonical update guard
value”优先聚合：

```text
for each sink op in topo order:
  if op is register/latch/memory/memory-fill write:
    key = normalized event key + canonical updateCond value
  else if op has opaque side effect:
    key = singleton side-effect key
  append topoPos to key bucket

for key in first-seen order:
  emit one CommitNode for the full bucket
  do not split this CommitNode by maxOpInCommitSupernode
```

实现点：

1. 在 `wolvrix/lib/transform/activity_schedule.cpp` 增加 `normalizedSinkGuardKey()` 或扩展
   `normalizedSinkEventKey()` 的调用侧，识别：
   - `kRegisterWritePort` / `kLatchWritePort`: `oper[0]` 为 `updateCond`，event operands 从 `oper[3...]` 开始；
   - `kMemoryWritePort`: `oper[0]` 为 `updateCond`，event operands 从 `oper[4...]` 开始；
   - `kMemoryFillPort` 若有同样 operand 约定则纳入，否则先保守 singleton；
   - `kSystemTask` / `kDpicCall` 等 opaque side effect 不参与 guard bucket，保持独立或只按现有 event key。

2. 新增可选开关，例如：
   - `ActivityScheduleOptions::commitGuardEventBuckets`
   - 环境变量 `WOLVRIX_XS_GRHSIM_COMMIT_GUARD_EVENT_BUCKETS=1`
   - 默认先打开在 xs-components / XiangShan gate 中验证，最终是否默认开启由 50k 和 compile gate 决定。

3. 对 guard-event bucket 不使用 `maxOpInCommitSupernode` 切分。`max_op_in_commit_supernode` 仍可保留给
   opaque side-effect bucket 或 fallback event-only bucket。

4. emit 侧保持 commit supernode 原子：
   - `buildScheduleBatches()` 当前 commit phase 已经以单个 commit supernode 为 `Word`；
   - 加断言/统计，确保一个 commit supernode 不会被 helper chunk 或 sched batch 切开；
   - NO0200 已实现的 per-function guard grouping 继续保留，用于同一 commit supernode 内最终生成单个外层 `if`。

### 预期收益

这条路线大概率正向，理由是：

- NO0200 已证明同 guard 合并在完整 XiangShan 50k 上从 `358557ms` 改到 `333015ms`，约 `7.1%` 正收益；
- 现有剩余 `9` 个相同 guard block 来自 commit supernode / emitted function 切分，而不是 guard 无法识别；
- 如果在 activity schedule 阶段把同 event+guard 写口先合成一个 commit supernode，emit 侧自然只会生成一个外层
  `if`，同时减少 commit batch 函数调用、event scan 片段和重复 guard branch；
- 这比在 emit 末端做跨函数合并更干净，因为 commit supernode 本身就是调度和 emit 的原子单位。

但收益不是无条件保证。主要风险是少数 guard bucket 可能非常大，导致：

- 单个 `eval_commit_batch_N()` / helper 函数源码和 LLVM IR 变大；
- `clang++ -O3` 编译时间回升；
- runtime i-cache / branch locality 可能在极大 bucket 上变差。

因此该方向应以运行性能为主指标，同时把编译时间和 code shape 作为硬 gate，而不是只追求
`if` 数量最小。

### 验收指标

xs-component gate：

```bash
make -C testcase/xs-components CASE=XsRealFtqMetaQueueResolve grhsim
```

期望：

- `grhsim_value_8937_0_slot` guard count 从当前 `9` 继续降到 `1`；
- 该 `if` 内包含 `metaQueueResolve_17_*` 的全部同 event+guard write；
- 功能保持通过。

完整 XiangShan gate：

```bash
make xs_wolf_grhsim_emu \
  RUN_ID=no0200_guard_event_bucket50k_20260615 \
  XS_WOLF_GRHSIM_RESUME_FROM_STATS_JSON=0 \
  XS_SIM_MAX_CYCLE=50000 \
  XS_COMMIT_TRACE=0 \
  XS_PROGRESS_EVERY_CYCLES=5000 \
  WOLVRIX_GRHSIM_WAVEFORM=0 \
  WOLVRIX_GRHSIM_PERF=0

make run_xs_wolf_grhsim_emu \
  RUN_ID=no0200_guard_event_bucket50k_20260615 \
  XS_SIM_MAX_CYCLE=50000 \
  XS_COMMIT_TRACE=0 \
  XS_PROGRESS_EVERY_CYCLES=5000 \
  WOLVRIX_GRHSIM_WAVEFORM=0 \
  WOLVRIX_GRHSIM_PERF=0
```

记录并比较：

- `commit_supernodes` 数量；
- `commit_ops_max`、commit op size p90/p99/max；
- generated `sched_*.cpp` 最大文件大小和最大函数估计行数；
- GrhSIM model build time，尤其最慢 `sched_*.cpp`；
- CoreMark 50k `Host time spent`。

判定线：

- correctness：50k 跑满 `-C 50000`，无 difftest mismatch / abort；
- runtime：优先要求好于 NO0200 当前 `333015ms`；
- compile：若 runtime 小幅收益但 model build 明显恶化，需要进一步做 guard bucket 的可配置上限或 helper split；
- fallback：若极大 bucket 负向，保留当前 NO0200 emit-only grouping 作为默认路径。

## 2026-06-15 落地记录：activity-schedule event+guard commit bucket

已实现下一阶段规划：

- `ActivityScheduleOptions::commitGuardEventBuckets` 默认开启；
- CLI / Python 入口增加 `-commit-guard-event-buckets true|false` 与
  `commit_guard_event_buckets`；
- XiangShan GrhSIM 脚本增加 `WOLVRIX_XS_GRHSIM_COMMIT_GUARD_EVENT_BUCKETS`，默认 `1`；
- `activity_schedule` 在构造 commit supernode 时按 normalized event key + canonical updateCond
  分桶；
- `kRegisterWritePort` / `kLatchWritePort` / `kMemoryWritePort` 纳入 guard bucket；
- `kMemoryFillPort` 等没有明确 updateCond operand 约定的 sink 保持 singleton fallback；
- guard-event bucket 不再受 `maxOpInCommitSupernode` 切分，commit supernode 继续作为 emit 侧原子单元。

局部验证：

```bash
cmake --build wolvrix/build --target wolvrix-lib
cmake --build wolvrix/build --target transform-activity-schedule
ctest --test-dir wolvrix/build --output-on-failure -R "transform-activity-schedule"
ctest --test-dir wolvrix/build --output-on-failure -R "emit-grhsim-cpp"
```

结果：

- `transform-activity-schedule` 通过；
- `emit-grhsim-cpp` / `emit-grhsim-cpp-memory-fill` 通过。

`XsRealFtqMetaQueueResolve` 结构验证：

```bash
PYTHONPATH=$PWD/wolvrix/build/skbuild/python \
LD_LIBRARY_PATH=$PWD/wolvrix/build/skbuild:$PWD/wolvrix/build \
python3 testcase/xs-components/scripts/emit_grhsim.py \
  --sv testcase/xs-components/build/XsRealFtqMetaQueueResolve/chisel-sv/XsRealFtqMetaQueueResolve.sv \
  --top XsRealFtqMetaQueueResolve \
  --out testcase/xs-components/build/XsRealFtqMetaQueueResolve/grhsim/model \
  --json testcase/xs-components/build/XsRealFtqMetaQueueResolve/grhsim/XsRealFtqMetaQueueResolve.json \
  --max-op-in-compute-supernode 128 \
  --max-op-in-commit-supernode 768 \
  --sched-batch-max-ops 2048 \
  --sched-batch-max-estimated-lines 8192 \
  --sched-batch-target-count 64 \
  --emit-parallelism 4

make -B -C testcase/xs-components/build/XsRealFtqMetaQueueResolve/grhsim/model \
  CXX=clang++ CXXFLAGS="-O3 -std=c++20"
```

结果：

- `activity_schedule_stats.json` 中 `commit_supernodes=64`、`commit_event_key_runs=64`、
  `commit_event_keys=64`；
- `grhsim_value_8937_0_slot` 的外层 `if` 从原先分布在 `sched_17.cpp` 到
  `sched_25.cpp` 的 `9` 处，收敛到 `grhsim_XsRealFtqMetaQueueResolve_sched_21.cpp`
  的 `1` 处；
- `metaQueueResolve_17_mbtb_entries_1_2_position` 与
  `metaQueueResolve_17_tage_entries_0_useProvider` 等同 event+guard 写动作已位于同一个
  guard block；
- 生成的 GrhSIM 静态库 `libgrhsim_XsRealFtqMetaQueueResolve.a` 编译通过。

## 2026-06-15 完整 XiangShan 50k gate：无上限 event+guard bucket 负向

执行命令：

```bash
source env.sh

WOLVRIX_XS_GRHSIM_COMMIT_GUARD_EVENT_BUCKETS=1 \
make xs_wolf_grhsim_emu \
  RUN_ID=no0200_guard_event_bucket50k_20260615 \
  XS_WOLF_GRHSIM_RESUME_FROM_STATS_JSON=0 \
  XS_SIM_MAX_CYCLE=50000 \
  XS_COMMIT_TRACE=0 \
  XS_PROGRESS_EVERY_CYCLES=5000 \
  WOLVRIX_GRHSIM_WAVEFORM=0 \
  WOLVRIX_GRHSIM_PERF=0

make run_xs_wolf_grhsim_emu \
  RUN_ID=no0200_guard_event_bucket50k_20260615 \
  XS_SIM_MAX_CYCLE=50000 \
  XS_COMMIT_TRACE=0 \
  XS_PROGRESS_EVERY_CYCLES=5000 \
  WOLVRIX_GRHSIM_WAVEFORM=0 \
  WOLVRIX_GRHSIM_PERF=0
```

日志：

- `build/logs/xs/xs_wolf_grhsim_build_no0200_guard_event_bucket50k_20260615.log`
- `build/logs/xs/xs_wolf_grhsim_no0200_guard_event_bucket50k_20260615.log`

结构结果：

- `commit_supernodes=105093`
- `commit_event_key_runs=105093`
- `commit_event_keys=105093`
- `commit_sink_ops=290531`
- `commit_ops_per_supernode.p99=24`
- `commit_ops_max=42937`
- `out_degree_per_supernode.max=95916`
- fresh emit/build pipeline 中 `write_grhsim_cpp done 51351ms`
- Python emit 总耗时 `total done 1405513ms`

运行结果：

- 退出码：`0`
- `instrCnt = 73580`
- `cycleCnt = 49996`
- `IPC = 1.471718`
- `Host time spent: 408948ms`
- 速度约 `122.26 cycles/s`

对比：

| 版本 | Host time | cycles/s |
| --- | ---: | ---: |
| NO0200 emit-only shared guard bucket | `333015ms` | `150.14` |
| event+guard commit supernode，无上限 | `408948ms` | `122.26` |

结论：

- correctness 通过：50k 跑满，无 difftest mismatch；
- runtime 负向：相对 emit-only 版本慢 `75833ms`，约 `22.8%` host time regression；
- 当时怀疑点：无上限 event+guard bucket 同时改变了两个变量：
  - `commit_supernodes` 从原先约 `515` 增到 `105093`；
  - 最大 commit bucket 也增到 `42937` op；
- 因此不能直接把 runtime regression 归因到“大 bucket 破坏局部性”，需要单独验证 supernode 数量爆炸。
- 不应把“无上限 event+guard commit supernode”作为默认性能路径；
- 下一步实验：先聚合相同 `event+guard` 的 commit node，再把 commit node 聚合回 event-level commit supernode；
  即最终 `commit_supernodes` 回到 event key 量级，但 event 内仍保持 guard bucket 连续。

## 2026-06-15 两级 commit node 聚合实验：runtime 正向，compile-time 暴露大 TU 问题

实现调整：

- `buildEventClusteredSinkPartition(..., groupByGuard=true)` 不再直接以 `event+guard` 作为最终 cluster key；
- 第一层按 `(eventKey, guardKey)` 聚合 sink topo positions，保持 guard bucket first-seen order；
- 第二层按 `eventKey` 生成最终 commit cluster，把该 event 下的 guard buckets 顺序拼回一个 cluster；
- `commit_event_keys` 重新统计 event key，而不是 event+guard key；
- `maxOpInCommitSupernode` 仍不切这个实验路径中的 event-level commit cluster，以验证超大 bucket 保留时的 runtime。

局部验证：

```bash
cmake --build wolvrix/build --target transform-activity-schedule
ctest --test-dir wolvrix/build --output-on-failure -R transform-activity-schedule
ctest --test-dir wolvrix/build --output-on-failure -R emit-grhsim-cpp
cmake --build wolvrix/build/skbuild --target wolvrix-lib wolvrix-python-sources wolvrix_python
```

结果：

- `transform-activity-schedule` 通过；
- `emit-grhsim-cpp` / `emit-grhsim-cpp-memory-fill` 通过；
- `XsRealFtqMetaQueueResolve` 重新 emit 后：
  - `commit_supernodes=1`
  - `commit_event_key_runs=1`
  - `commit_event_keys=1`
  - `ops_per_supernode.max=6656`
  - 目标 `grhsim_value_8937_0_slot` guard 仍只生成 `1` 个 `if`。

完整 XiangShan 50k：

```bash
source env.sh

WOLVRIX_XS_GRHSIM_COMMIT_GUARD_EVENT_BUCKETS=1 \
WOLVRIX_GRHSIM_WAVEFORM=0 \
WOLVRIX_GRHSIM_PERF=0 \
make xs_wolf_grhsim_emu \
  RUN_ID=no0200_guard_event_nodes_in_event_supernode50k_20260615 \
  XS_WOLF_GRHSIM_RESUME_FROM_STATS_JSON=0 \
  XS_SIM_MAX_CYCLE=50000 \
  XS_COMMIT_TRACE=0 \
  XS_PROGRESS_EVERY_CYCLES=5000

WOLVRIX_GRHSIM_WAVEFORM=0 \
WOLVRIX_GRHSIM_PERF=0 \
make run_xs_wolf_grhsim_emu \
  RUN_ID=no0200_guard_event_nodes_in_event_supernode50k_20260615 \
  XS_SIM_MAX_CYCLE=50000 \
  XS_COMMIT_TRACE=0 \
  XS_PROGRESS_EVERY_CYCLES=5000
```

日志：

- `build/logs/xs/xs_wolf_grhsim_build_no0200_guard_event_nodes_in_event_supernode50k_20260615.log`
- `build/logs/xs/xs_wolf_grhsim_no0200_guard_event_nodes_in_event_supernode50k_20260615.log`

结构结果：

- `commit_nodes=449`
- `commit_supernodes=449`
- `commit_event_key_runs=449`
- `commit_event_keys=449`
- `commit_sink_ops=290531`
- `commit_ops_max=176719`
- `supernodes=72648`
- `compute_supernodes=72199`
- `dag_edges=699081`
- `boundary_activation_edges=2447820`
- `outdeg_max=10627`
- `write_grhsim_cpp done 54780ms`
- Python emit 总耗时 `total done 1093614ms`

运行结果：

- 退出码：`0`
- `instrCnt = 73580`
- `cycleCnt = 49996`
- `IPC = 1.471718`
- `Host time spent: 318117ms`
- 速度约 `157.17 cycles/s`

对比：

| 版本 | commit supernodes | commit ops max | Host time | cycles/s |
| --- | ---: | ---: | ---: | ---: |
| NO0200 emit-only shared guard bucket | `515` | `4096` | `333015ms` | `150.14` |
| event+guard commit supernode，无上限 | `105093` | `42937` | `408948ms` | `122.26` |
| event supernode + 内部 guard commit node | `449` | `176719` | `318117ms` | `157.17` |

结论：

- 运行期验证了用户提出的猜想：前一版明显变慢的主因是 `commit_supernodes=105093`
  带来的 commit supernode 数量爆炸，而不是“最大 bucket 过大必然破坏 runtime locality”；
- 当最终 commit supernode 数回到 event key 量级后，即使 `commit_ops_max` 增到 `176719`，50k runtime
  仍比 emit-only 基线快约 `4.47%`，比 event+guard-supernode 爆炸版本快约 `22.21%`；
- 但 compile-time 暴露了新的硬问题：
  - `grhsim_SimTop_sched_70.cpp` 约 `1995316` 行 / `160MB`；
  - `grhsim_SimTop_sched_71.cpp` 约 `1118010` 行 / `86MB`；
  - `sched_71.o` 于 `20:48:45` 生成，`sched_70.o` 到 `21:12:28` 才生成；
  - 单个超大 commit batch/TU 明显拖慢 build tail。

后续方向：

- schedule 层继续保留“两级 commit node”语义：event 内先形成 guard commit node，再聚合成最终 commit supernode；
- 最终 commit supernode 不应无条件吞掉整个 event；应按 commit node 的 op 数做 capped packing；
- 单个 commit node 若超过 cap，应保持原子单独成为 commit supernode，不拆分、不与其他 commit node 合并。

## 2026-06-15 capped commit-node packing 落地

用户建议：

- 聚合单位仍是 commit node（相同 event + guard 的 sink op bucket）；
- 最终 commit supernode 按 commit node 的 op 数累计聚合；
- 最大合并阈值不超过 `4096`；
- 如果单个 commit node 已经超过阈值，则该 commit node 单独成为一个 commit supernode，不拆分，也不与其他
  commit node 合并。

实现状态：

- `buildEventClusteredSinkPartition(..., groupByGuard=true)` 的第二层聚合改为 capped packing：
  - `mergeLimit = min(maxOpInCommitSupernode, 4096)`；
  - `maxOpInCommitSupernode == 0` 时仍使用硬上限 `4096`；
  - event 内按 guard bucket first-seen order 逐个装箱；
  - 当前箱加上下一个 commit node 超过 `mergeLimit` 时先 flush 当前箱；
  - 下一个 commit node 若自身 `size > mergeLimit`，直接单独输出为 commit supernode；
  - commit node 内部不再被 `maxOpInCommitSupernode` 拆开。
- `commit_event_key_runs` 现在表示最终 commit cluster 数；`commit_event_keys` 仍表示唯一 event key 数。

局部测试：

```bash
cmake --build wolvrix/build --target transform-activity-schedule
ctest --test-dir wolvrix/build --output-on-failure -R transform-activity-schedule
ctest --test-dir wolvrix/build --output-on-failure -R emit-grhsim-cpp
cmake --build wolvrix/build/skbuild --target wolvrix-lib wolvrix-python-sources wolvrix_python
```

结果：

- `transform-activity-schedule` 通过；
- `emit-grhsim-cpp` / `emit-grhsim-cpp-memory-fill` 通过；
- 新增 transform 测试覆盖：
  - `maxOpInCommitSupernode=3` 时，2-op same-guard commit node 可与 1-op commit node 合并，但再遇到
    一个 1-op commit node 会切到下一个 commit supernode；
  - `maxOpInCommitSupernode=1` 时，2-op same-guard commit node 作为 oversized bucket 单独成为一个
    commit supernode，不拆分、不与其他 guard bucket 合并。

`XsRealFtqMetaQueueResolve` 快速结构验证：

- 命令：重新运行 `testcase/xs-components/scripts/emit_grhsim.py`，`--max-op-in-commit-supernode 768`；
- `commit_supernodes=10`
- `commit_event_key_runs=10`
- `commit_event_keys=1`
- `commit_sink_ops=6656`
- `ops_per_supernode.max=3237`
- 目标 guard `grhsim_value_8937_0_slot` 仍只生成 `1` 个 `if`，目标写动作仍位于同一 guard block。

## 2026-06-15 完整 XiangShan 50k gate：capped commit-node packing

执行命令：

```bash
source /home/gaoruihao/wksp/wolvrix-playground/env.sh

WOLVRIX_XS_GRHSIM_COMMIT_GUARD_EVENT_BUCKETS=1 \
WOLVRIX_GRHSIM_WAVEFORM=0 \
WOLVRIX_GRHSIM_PERF=0 \
make xs_wolf_grhsim_emu \
  RUN_ID=no0200_guard_event_capped4096_50k_20260615 \
  XS_WOLF_GRHSIM_RESUME_FROM_STATS_JSON=0 \
  XS_SIM_MAX_CYCLE=50000 \
  XS_COMMIT_TRACE=0 \
  XS_PROGRESS_EVERY_CYCLES=5000

WOLVRIX_GRHSIM_WAVEFORM=0 \
WOLVRIX_GRHSIM_PERF=0 \
make run_xs_wolf_grhsim_emu \
  RUN_ID=no0200_guard_event_capped4096_50k_20260615 \
  XS_SIM_MAX_CYCLE=50000 \
  XS_COMMIT_TRACE=0 \
  XS_PROGRESS_EVERY_CYCLES=5000
```

日志：

- `build/logs/xs/xs_wolf_grhsim_build_no0200_guard_event_capped4096_50k_20260615.log`
- `build/logs/xs/xs_wolf_grhsim_no0200_guard_event_capped4096_50k_20260615.log`

结构结果：

- `commit_nodes=502`
- `commit_supernodes=502`
- `commit_event_key_runs=502`
- `commit_event_keys=449`
- `commit_sink_ops=290531`
- `commit_ops_per_supernode.p90=3876`
- `commit_ops_per_supernode.p99=4096`
- `commit_ops_max=42937`
- `supernodes=72701`
- `compute_supernodes=72199`
- `dag_edges=702244`
- `boundary_activation_edges=2451459`
- `outdeg_max=10647`
- `write_grhsim_cpp done 51758ms`
- Python emit 总耗时 `total done 1084038ms`

生成源码规模：

- `grhsim_SimTop_sched_*.cpp` 共 `132` 个文件；
- 总行数 `16470845`；
- 最大行数文件：`grhsim_SimTop_sched_128.cpp`，`445114` 行；
- 最大体积文件：`grhsim_SimTop_sched_7.cpp`，`39M`；
- 相比两级无 cap 版本的 `sched_70.cpp` `1995316` 行 / `160MB`，compile-time tail 明显收敛。

CoreMark 50k 结果：

```text
[EMU_PROGRESS] host_cycles=50000 model_cycles=50000 instr=73580 commit_pc=0x800012f8 trap_pc=0x80001312 core=0 host_ms=321424
[CYCLE_LIMIT] cycles=50000 max_cycles=50000
Core-0 instrCnt = 73580, cycleCnt = 49996, IPC = 1.471718
Host time spent: 321436ms
```

速度约 `155.55 cycles/s`。`EXCEEDING CYCLE/INSTR LIMIT` 是 `-C 50000` 的预期停止条件；本轮退出码为
`0`，日志中未出现 difftest mismatch / abort。

对比：

| 版本 | commit supernodes | commit ops max | 最大 sched cpp | Host time | cycles/s |
| --- | ---: | ---: | ---: | ---: | ---: |
| emit-only shared guard bucket | `515` | `4096` | 未显著重尾 | `333015ms` | `150.14` |
| event+guard commit supernode，无上限 | `105093` | `42937` | 未记录为主问题 | `408948ms` | `122.26` |
| event supernode + 内部 guard commit node，无 cap | `449` | `176719` | `1995316` 行 / `160MB` | `318117ms` | `157.17` |
| capped commit-node packing | `502` | `42937` | `445114` 行 / `39M` | `321436ms` | `155.55` |

结论：

- capped packing 保留了 event 内 guard commit node 的主要 runtime 收益：相对 emit-only shared guard bucket
  仍快 `11579ms`，约 `3.48%` host time improvement；
- 相对无 cap 两级版本慢 `3319ms`，约 `1.04%`，但最大生成文件从百万行/百 MB 级降到 `445k` 行 / `39M`；
- `commit_ops_max=42937` 来自单个 oversized commit node，符合“不拆分单个同 event+guard bucket”的规则；
- `commit_supernodes=502` 回到原始 event-level 量级，避免了 `105093` supernode 爆炸；
- 这版更适合作为当前默认路径：runtime 接近无 cap 最快点，同时显著降低 compile-time 重尾风险。
