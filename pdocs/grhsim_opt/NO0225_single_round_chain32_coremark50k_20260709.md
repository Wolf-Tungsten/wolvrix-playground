# NO0225 Single-Round Chain32 CoreMark 50k Snapshot

## 1. 记录目的

本文记录 2026-07-09 在单轮 `activity-schedule` plain coarsen 基础上，
把 `out1` / `in1` chain merge 合并上限从 `64 * maxOpInComputeSupernode`
收紧到 `32 * maxOpInComputeSupernode` 后的 XiangShan `CoreMark 50k`
fresh emit/build/runtime 快照。

## 2. 代码改动

本轮修改：

- 保持 coarsen 只执行一轮 `out1 -> in1 -> siblings`。
- `out1` / `in1` 合并 op 上限改为 `32 * maxOpInComputeSupernode`。
- `siblings` 合并 op 上限保持 `4 * maxOpInComputeSupernode`。
- `maxOpInComputeSupernode == 0` 时，上述 coarsen 上限仍视为无限制。

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
20260709_single_round_chain32_50k
```

Fresh emit/build 命令：

```bash
source env.sh && /usr/bin/time -v make --no-print-directory xs_wolf_grhsim_emu \
  RUN_ID=20260709_single_round_chain32_50k \
  XS_SIM_MAX_CYCLE=50000 \
  XS_PROGRESS_EVERY_CYCLES=5000 \
  XS_COMMIT_TRACE=0 \
  XS_WAVEFORM=0 \
  WOLVRIX_GRHSIM_WAVEFORM=0
```

Runtime 命令：

```bash
source env.sh && /usr/bin/time -v make --no-print-directory run_xs_wolf_grhsim_emu \
  RUN_ID=20260709_single_round_chain32_50k \
  XS_SIM_MAX_CYCLE=50000 \
  XS_PROGRESS_EVERY_CYCLES=5000 \
  XS_COMMIT_TRACE=0 \
  XS_WAVEFORM=0 \
  WOLVRIX_GRHSIM_WAVEFORM=0
```

## 4. Activity-Schedule 结构数据

日志：

- build log: [`../../build/logs/xs/xs_wolf_grhsim_build_20260709_single_round_chain32_50k.log`](../../build/logs/xs/xs_wolf_grhsim_build_20260709_single_round_chain32_50k.log)

`activity-schedule` 总耗时：

```text
build_op_data=5259ms
compute_node_build=20469ms
freeze_after_compute_node=0ms
final_materialize=15529ms
export_session=108ms
total=59409ms
```

`materializeComputeNodeSchedule` 分解：

```text
init_clusters=43ms
topo_before_coarsen=309ms
coarsen=6593ms
topo_after_coarsen=154ms
build_cluster_view=99ms
dp_segment=1853ms
flatten_segments=17ms
build_final_supernodes=1289ms
build_final_dag=2273ms
build_state_read_sets=2402ms
final_topo=12ms
```

Compute-node coarsen detail：

```text
enabled=true
chain_merge=true
iterations=1
out1_merges=405019
in1_merges=252080
sibling_merges=291967
clusters_before=1396066
clusters_after=447000
tail_stopped=false
tail_iterations=0
segments=50973
compute_supernodes=50973
```

Coarsen shape：

```text
clusters=447000
isolated=15340
sources=78566
sinks=115839
linear=342
forks=283487
joins=348930
max_pred=705
max_succ=51659
op_size_min=1
op_size_mean=14
op_size_p50=3
op_size_p90=23
op_size_max=3456
```

Final schedule summary：

```text
supernodes=51515
compute_supernodes=51018
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
initial_compute_supernodes=447000
initial_compute_supernode_ops_total=6429337
initial_compute_supernode_dag_edges=1865235
initial_boundary_values=1102149
initial_boundary_activation_edges=2605608
initial_compute_compute_value_pairs=2255085
initial_compute_commit_value_pairs=350523
compute_supernodes=51018
commit_supernodes=497
topo_edges=10184708
graph_ops=7249135
graph_values=6725504
```

## 5. Emit / Build 数据

Emit 阶段：

```text
write_grhsim_cpp=44331ms
total=141239ms
```

Fresh emit/build `/usr/bin/time -v`：

```text
Elapsed (wall clock) time: 8:00.55
User time: 5919.54s
System time: 54.75s
CPU: 1243%
Maximum resident set size: 28331384 KB
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
grhsim_SimTop_sched_*.cpp: 127
```

## 6. CoreMark 50k Runtime 数据

日志：

- runtime log: [`../../build/logs/xs/xs_wolf_grhsim_20260709_single_round_chain32_50k.log`](../../build/logs/xs/xs_wolf_grhsim_20260709_single_round_chain32_50k.log)

Runtime progress：

```text
host_cycles=5000  host_ms=7354
host_cycles=10000 host_ms=17228
host_cycles=15000 host_ms=46084
host_cycles=20000 host_ms=84968
host_cycles=25000 host_ms=120210
host_cycles=30000 host_ms=157053
host_cycles=35000 host_ms=193711
host_cycles=40000 host_ms=230466
host_cycles=45000 host_ms=268638
host_cycles=50000 host_ms=316271
```

Runtime final：

```text
Core 0: EXCEEDING CYCLE/INSTR LIMIT at pc = 0x80001312
Core-0 instrCnt = 73580
cycleCnt = 49996
IPC = 1.471718
Guest cycle spent = 50001
Host time spent = 316283ms
```

折算速度：

```text
50001 guest cycles / 316.283s = 158.09 cycles/s
```

Runtime `/usr/bin/time -v`：

```text
Elapsed (wall clock) time: 5:16.29
User time: 316.18s
System time: 0.02s
CPU: 99%
Maximum resident set size: 129264 KB
Exit status: 0
```

## 7. 结论记录

单轮 coarsen + chain32 可以完成完整 XiangShan `CoreMark 50k`
fresh emit/build/runtime 流程，并在 difftest 运行中跑满 `50000` cycle limit。

本轮产物的最终调度规模为：

```text
supernodes=51515
compute_supernodes=51018
commit_supernodes=497
```

本轮 runtime 数值为：

```text
Host time spent = 316283ms
cycles/s = 158.09
instrCnt / cycleCnt = 73580 / 49996
```
