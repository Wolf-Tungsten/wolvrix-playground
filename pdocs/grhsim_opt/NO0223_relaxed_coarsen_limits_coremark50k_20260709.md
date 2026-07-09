# NO0223 Relaxed Coarsen Limits CoreMark 50k Snapshot

## 1. 记录目的

本文记录 2026-07-09 对 `activity-schedule` plain coarsen 合并上限放宽后的
XiangShan `CoreMark 50k` fresh emit/build/runtime 快照。

本文只记录本轮改动和本轮性能数值，不做历史结果对比。

## 2. 代码改动

本轮修改位于：

- [`activity_schedule.cpp`](../../wolvrix/lib/transform/activity_schedule.cpp)
- [`test_activity_schedule_pass.cpp`](../../wolvrix/tests/transform/test_activity_schedule_pass.cpp)
- [`activity-schedule.md`](../../wolvrix/docs/transform/activity-schedule.md)
- [`grhsim-scheduling.md`](../../wolvrix/docs/emit/grhsim-scheduling.md)

核心行为：

- `out1` / `in1` chain merge 的合并 op 上限改为
  `64 * maxOpInComputeSupernode`。
- `siblings` merge 的合并 op 上限改为
  `4 * maxOpInComputeSupernode`。
- `maxOpInComputeSupernode == 0` 时，上述 coarsen 上限视为无限制。
- 乘法使用 saturating helper，避免极大 cap 下 `std::size_t` 溢出。
- DP 连续分段仍使用 `maxOpInComputeSupernode` 作为 segment 上限。
- 如果单个 coarsen cluster 已经超过 DP 上限，DP 不拆开该 oversize cluster。
- 追加 compute-node 出度分布统计，日志输出
  `activity-schedule compute-node out-degree detail`，并写入 Session key
  `<target>.activity_schedule.compute_node_out_degree`。

本轮本地验证：

```bash
cmake --build wolvrix/build --target transform-activity-schedule
ctest --test-dir wolvrix/build --output-on-failure -R transform-activity-schedule
```

结果：

```text
transform-activity-schedule: Passed
```

## 3. 构建与运行命令

Run ID：

```text
20260709_relaxed_coarsen_50k
```

Fresh emit/build 命令：

```bash
source env.sh && /usr/bin/time -v make --no-print-directory xs_wolf_grhsim_emu \
  RUN_ID=20260709_relaxed_coarsen_50k \
  XS_SIM_MAX_CYCLE=50000 \
  XS_PROGRESS_EVERY_CYCLES=5000 \
  XS_COMMIT_TRACE=0 \
  XS_WAVEFORM=0 \
  WOLVRIX_GRHSIM_WAVEFORM=0
```

Runtime 命令：

```bash
source env.sh && /usr/bin/time -v make --no-print-directory run_xs_wolf_grhsim_emu \
  RUN_ID=20260709_relaxed_coarsen_50k \
  XS_SIM_MAX_CYCLE=50000 \
  XS_PROGRESS_EVERY_CYCLES=5000 \
  XS_COMMIT_TRACE=0 \
  XS_WAVEFORM=0 \
  WOLVRIX_GRHSIM_WAVEFORM=0
```

本轮 `activity-schedule` 关键参数：

```text
max_op_in_compute_supernode=108
max_op_in_compute_node=108
split_oversize_compute_nodes=True
split_oversize_compute_node_max_ops=108
max_op_in_commit_supernode=4096
commit_guard_event_buckets=True
sched_batch_max_ops=2048
sched_batch_max_estimated_lines=8192
sched_batch_target_count=64
sched_batches_per_cpp=1
emit_parallelism=4
emit_runtime_stats=False
waveform=off
perf=off
reg_to_mem_intent=True
declared_value_compute_node_boundary=False
```

## 4. Activity-Schedule 结构数据

日志：

- build log: [`../../build/logs/xs/xs_wolf_grhsim_build_20260709_relaxed_coarsen_50k.log`](../../build/logs/xs/xs_wolf_grhsim_build_20260709_relaxed_coarsen_50k.log)

`activity-schedule` 总耗时：

```text
build_op_data=5622ms
compute_node_build=22499ms
freeze_after_compute_node=0ms
final_materialize=62516ms
export_session=108ms
total=109442ms
```

`materializeComputeNodeSchedule` 分解：

```text
init_clusters=40ms
topo_before_coarsen=336ms
coarsen=53925ms
topo_after_coarsen=127ms
build_cluster_view=91ms
dp_segment=1433ms
flatten_segments=15ms
build_final_supernodes=1392ms
build_final_dag=2270ms
build_state_read_sets=2457ms
final_topo=9ms
```

Compute-node coarsen detail：

```text
enabled=true
chain_merge=true
iterations=16
out1_merges=465862
in1_merges=259469
sibling_merges=413767
clusters_before=1396066
clusters_after=256968
tail_stopped=true
tail_iterations=3
segments=39005
compute_supernodes=39005
```

Coarsen shape：

```text
clusters=256968
isolated=15410
sources=59348
sinks=47794
linear=2
forks=193575
joins=181850
max_pred=1320
max_succ=27426
op_size_min=1
op_size_mean=25
op_size_p50=3
op_size_p90=39
op_size_max=6912
```

Final schedule summary：

```text
supernodes=39547
compute_supernodes=39050
commit_supernodes=497
compute_nodes=1396066
source_clones=2047021
local_shared_compute_clones=0
eligible_ops=6984092
state_read_sets=265009
graph_changed=true
```

Initial/final activity timing detail：

```text
initial_compute_supernodes=256968
initial_compute_supernode_ops_total=6429337
initial_compute_supernode_dag_edges=1111814
initial_boundary_values=1004765
initial_boundary_activation_edges=2096236
initial_compute_compute_value_pairs=1745713
initial_compute_commit_value_pairs=350523
compute_supernodes=39050
commit_supernodes=497
topo_edges=10184708
graph_ops=7249135
graph_values=6725504
```

Oversize split detail：

```text
oversize_compute_nodes=8
split_supernodes=38
```

新增 compute-node 出度分布统计（2026-07-09 追加捕获）：

统计口径为 `value_target_dedup`：

- 节点是 `buildComputeNodeRewrite(...)` 生成并完成 cycle split 后的 compute node。
- 若 `cn1` 产生的一个或多个 value 被 `cn2` 作为 boundary input 读取，则
  `(cn1, cn2)` 只计 1 条 compute->compute 出边。
- 同一对 `(cn1, cn2)` 由多个 value 连接时不重复计数。
- 不包含 compute->commit 边，也不包含同 compute node 内部依赖。

捕获命令：

```bash
source env.sh && WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1 /usr/bin/time -v \
  make --no-print-directory xs_wolf_grhsim_emit \
  RUN_ID=20260709_compute_node_outdegree_stats \
  XS_GRHSIM_BUILD=tmp/no0223_compute_node_outdegree/grhsim \
  XS_WOLF_GRHSIM_PRE_REG_TO_MEM_JSON=build/xs/grhsim/wolvrix_xs_pre_reg_to_mem.json \
  XS_WOLF_GRHSIM_RESUME_FROM_PRE_REG_TO_MEM_JSON=1 \
  XS_WOLF_GRHSIM_RESUME_FROM_POST_REG_TO_MEM_JSON=0 \
  XS_COMMIT_TRACE=0 \
  XS_WAVEFORM=0 \
  WOLVRIX_GRHSIM_WAVEFORM=0
```

捕获日志：

- build log: [`../../build/logs/xs/xs_wolf_grhsim_build_20260709_compute_node_outdegree_stats.log`](../../build/logs/xs/xs_wolf_grhsim_build_20260709_compute_node_outdegree_stats.log)

结构统计原始输出：

```text
semantics=value_target_dedup
nodes=1396066
edges=3679128
mean_milli=2635
p50=2
p90=4
p99=27
max=45688
buckets=0:261496,1:405258,2:527033,3-4:92583,5-8:67722,9-16:21356,17-32:12618,33-64:5853,65-128:1155,129-256:390,257-512:379,513-1024:167,>1024:56
```

本次 stop-after 捕获耗时：

```text
activity-schedule total=100852ms
pass activity-schedule done 101077ms
total done 141811ms
```

## 5. Emit / Build 数据

Emit 阶段：

```text
write_grhsim_cpp=45860ms
total=194212ms
```

Fresh emit/build `/usr/bin/time -v`：

```text
Elapsed (wall clock) time: 8:39.67
User time: 5163.33s
System time: 48.21s
CPU: 1002%
Maximum resident set size: 28331052 KB
Exit status: 0
```

生成产物：

```text
build/xs/grhsim/grhsim-compile/emu: 97M
build/xs/grhsim/grhsim_emit/libgrhsim_SimTop.a: 103M
build/xs/grhsim/grhsim_emit/grhsim_static_stats.json: 8.9M
```

本轮生成的 schedule C++ translation unit 数：

```text
grhsim_SimTop_sched_*.cpp: 131
```

## 6. CoreMark 50k Runtime 数据

日志：

- runtime log: [`../../build/logs/xs/xs_wolf_grhsim_20260709_relaxed_coarsen_50k.log`](../../build/logs/xs/xs_wolf_grhsim_20260709_relaxed_coarsen_50k.log)

Runtime progress：

```text
host_cycles=5000  host_ms=9487
host_cycles=10000 host_ms=21926
host_cycles=15000 host_ms=56355
host_cycles=20000 host_ms=100462
host_cycles=25000 host_ms=141650
host_cycles=30000 host_ms=185148
host_cycles=35000 host_ms=224944
host_cycles=40000 host_ms=261814
host_cycles=45000 host_ms=300189
host_cycles=50000 host_ms=347536
```

Runtime final：

```text
Core 0: EXCEEDING CYCLE/INSTR LIMIT at pc = 0x80001312
Core-0 instrCnt = 73580
cycleCnt = 49996
IPC = 1.471718
Guest cycle spent = 50001
Host time spent = 347547ms
```

折算速度：

```text
50001 guest cycles / 347.547s = 143.87 cycles/s
```

Runtime `/usr/bin/time -v`：

```text
Elapsed (wall clock) time: 5:47.56
User time: 347.47s
System time: 0.02s
CPU: 99%
Maximum resident set size: 124808 KB
Exit status: 0
```

## 7. 结论记录

本轮 relaxed coarsen limits 版本可以完成完整 XiangShan `CoreMark 50k`
fresh emit/build/runtime 流程，并在 difftest 运行中跑满 `50000` cycle limit。

本轮产物的最终调度规模为：

```text
supernodes=39547
compute_supernodes=39050
commit_supernodes=497
```

本轮 runtime 数值为：

```text
Host time spent = 347547ms
cycles/s = 143.87
instrCnt / cycleCnt = 73580 / 49996
```
