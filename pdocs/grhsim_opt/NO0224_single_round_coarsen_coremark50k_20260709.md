# NO0224 Single-Round Coarsen CoreMark 50k Snapshot

## 1. 记录目的

本文记录 2026-07-09 对 `activity-schedule` plain coarsen 的单轮实验：
取消 fixed-point 迭代，只执行一轮 `out1 -> in1 -> siblings`，随后直接进入 DP。

## 2. 代码改动

本轮在 `materializeComputeNodeSchedule(...)` 中调整 coarsen 主循环：

- `enableCoarsen=true` 时只执行一轮 coarsen stage。
- `out1` / `in1` 仍受 `enableChainMerge` 控制。
- `out1` / `in1` 合并 op 上限仍为 `64 * maxOpInComputeSupernode`。
- `siblings` 合并 op 上限仍为 `4 * maxOpInComputeSupernode`。
- 单轮结束后直接重新 topo 并进入 DP 连续分段。

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
20260709_single_round_coarsen_50k
```

Fresh emit/build 命令：

```bash
source env.sh && /usr/bin/time -v make --no-print-directory xs_wolf_grhsim_emu \
  RUN_ID=20260709_single_round_coarsen_50k \
  XS_SIM_MAX_CYCLE=50000 \
  XS_PROGRESS_EVERY_CYCLES=5000 \
  XS_COMMIT_TRACE=0 \
  XS_WAVEFORM=0 \
  WOLVRIX_GRHSIM_WAVEFORM=0
```

Runtime 命令：

```bash
source env.sh && /usr/bin/time -v make --no-print-directory run_xs_wolf_grhsim_emu \
  RUN_ID=20260709_single_round_coarsen_50k \
  XS_SIM_MAX_CYCLE=50000 \
  XS_PROGRESS_EVERY_CYCLES=5000 \
  XS_COMMIT_TRACE=0 \
  XS_WAVEFORM=0 \
  WOLVRIX_GRHSIM_WAVEFORM=0
```

## 4. Activity-Schedule 结构数据

日志：

- build log: [`../../build/logs/xs/xs_wolf_grhsim_build_20260709_single_round_coarsen_50k.log`](../../build/logs/xs/xs_wolf_grhsim_build_20260709_single_round_coarsen_50k.log)

`activity-schedule` 总耗时：

```text
build_op_data=5271ms
compute_node_build=20401ms
freeze_after_compute_node=0ms
final_materialize=15528ms
export_session=106ms
total=59239ms
```

`materializeComputeNodeSchedule` 分解：

```text
init_clusters=41ms
topo_before_coarsen=309ms
coarsen=6576ms
topo_after_coarsen=153ms
build_cluster_view=97ms
dp_segment=1828ms
flatten_segments=17ms
build_final_supernodes=1302ms
build_final_dag=2276ms
build_state_read_sets=2435ms
final_topo=12ms
```

Compute-node coarsen detail：

```text
enabled=true
chain_merge=true
iterations=1
out1_merges=405231
in1_merges=252812
sibling_merges=292694
clusters_before=1396066
clusters_after=445329
tail_stopped=false
tail_iterations=0
segments=50461
compute_supernodes=50461
```

Coarsen shape：

```text
clusters=445329
isolated=15340
sources=78566
sinks=115782
linear=338
forks=283122
joins=347287
max_pred=1314
max_succ=51650
op_size_min=1
op_size_mean=14
op_size_p50=3
op_size_p90=22
op_size_max=6912
```

Final schedule summary：

```text
supernodes=51003
compute_supernodes=50506
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
initial_compute_supernodes=445329
initial_compute_supernode_ops_total=6429337
initial_compute_supernode_dag_edges=1858869
initial_boundary_values=1101723
initial_boundary_activation_edges=2601752
initial_compute_compute_value_pairs=2251229
initial_compute_commit_value_pairs=350523
compute_supernodes=50506
commit_supernodes=497
topo_edges=10184708
graph_ops=7249135
graph_values=6725504
```

## 5. Emit / Build 数据

Emit 阶段：

```text
write_grhsim_cpp=44092ms
total=141476ms
```

Fresh emit/build `/usr/bin/time -v`：

```text
Elapsed (wall clock) time: 8:30.20
User time: 5953.47s
System time: 56.31s
CPU: 1177%
Maximum resident set size: 28331016 KB
Exit status: 0
```

生成产物：

```text
build/xs/grhsim/grhsim-compile/emu: 101M
build/xs/grhsim/grhsim_emit/libgrhsim_SimTop.a: 107M
build/xs/grhsim/grhsim_emit/grhsim_static_stats.json: 12M
```

本轮生成的 schedule C++ translation unit 数：

```text
grhsim_SimTop_sched_*.cpp: 129
```

## 6. CoreMark 50k Runtime 数据

日志：

- runtime log: [`../../build/logs/xs/xs_wolf_grhsim_20260709_single_round_coarsen_50k.log`](../../build/logs/xs/xs_wolf_grhsim_20260709_single_round_coarsen_50k.log)

Runtime progress：

```text
host_cycles=5000  host_ms=7885
host_cycles=10000 host_ms=18339
host_cycles=15000 host_ms=47739
host_cycles=20000 host_ms=87270
host_cycles=25000 host_ms=123006
host_cycles=30000 host_ms=160304
host_cycles=35000 host_ms=197489
host_cycles=40000 host_ms=234843
host_cycles=45000 host_ms=273583
host_cycles=50000 host_ms=321700
```

Runtime final：

```text
Core 0: EXCEEDING CYCLE/INSTR LIMIT at pc = 0x80001312
Core-0 instrCnt = 73580
cycleCnt = 49996
IPC = 1.471718
Guest cycle spent = 50001
Host time spent = 321712ms
```

折算速度：

```text
50001 guest cycles / 321.712s = 155.42 cycles/s
```

Runtime `/usr/bin/time -v`：

```text
Elapsed (wall clock) time: 5:21.72
User time: 321.65s
System time: 0.01s
CPU: 99%
Maximum resident set size: 129008 KB
Exit status: 0
```

## 7. 结论记录

单轮 coarsen 实验可以完成完整 XiangShan `CoreMark 50k`
fresh emit/build/runtime 流程，并在 difftest 运行中跑满 `50000` cycle limit。

本轮产物的最终调度规模为：

```text
supernodes=51003
compute_supernodes=50506
commit_supernodes=497
```

本轮 runtime 数值为：

```text
Host time spent = 321712ms
cycles/s = 155.42
instrCnt / cycleCnt = 73580 / 49996
```
