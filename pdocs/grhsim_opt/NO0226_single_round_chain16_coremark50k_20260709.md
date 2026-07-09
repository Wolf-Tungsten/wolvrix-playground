# NO0226 Single-Round Chain16 CoreMark 50k Snapshot

## 1. 记录目的

本文记录 2026-07-09 在单轮 `activity-schedule` plain coarsen 基础上，
把 `out1` / `in1` chain merge 合并上限收紧到
`16 * maxOpInComputeSupernode` 后的 XiangShan `CoreMark 50k`
fresh emit/build/runtime 快照。

## 2. 代码改动

本轮修改：

- 保持 coarsen 只执行一轮 `out1 -> in1 -> siblings`。
- `out1` / `in1` 合并 op 上限改为 `16 * maxOpInComputeSupernode`。
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
20260709_single_round_chain16_50k
```

Fresh emit/build 命令：

```bash
source env.sh && /usr/bin/time -v make --no-print-directory xs_wolf_grhsim_emu \
  RUN_ID=20260709_single_round_chain16_50k \
  XS_SIM_MAX_CYCLE=50000 \
  XS_PROGRESS_EVERY_CYCLES=5000 \
  XS_COMMIT_TRACE=0 \
  XS_WAVEFORM=0 \
  WOLVRIX_GRHSIM_WAVEFORM=0
```

Runtime 命令：

```bash
source env.sh && /usr/bin/time -v make --no-print-directory run_xs_wolf_grhsim_emu \
  RUN_ID=20260709_single_round_chain16_50k \
  XS_SIM_MAX_CYCLE=50000 \
  XS_PROGRESS_EVERY_CYCLES=5000 \
  XS_COMMIT_TRACE=0 \
  XS_WAVEFORM=0 \
  WOLVRIX_GRHSIM_WAVEFORM=0
```

## 4. Activity-Schedule 结构数据

日志：

- build log: [`../../build/logs/xs/xs_wolf_grhsim_build_20260709_single_round_chain16_50k.log`](../../build/logs/xs/xs_wolf_grhsim_build_20260709_single_round_chain16_50k.log)

`activity-schedule` 总耗时：

```text
build_op_data=5268ms
compute_node_build=20551ms
freeze_after_compute_node=0ms
final_materialize=15776ms
export_session=109ms
total=59663ms
```

`materializeComputeNodeSchedule` 分解：

```text
init_clusters=41ms
topo_before_coarsen=314ms
coarsen=6721ms
topo_after_coarsen=155ms
build_cluster_view=99ms
dp_segment=1883ms
flatten_segments=17ms
build_final_supernodes=1276ms
build_final_dag=2301ms
build_state_read_sets=2470ms
final_topo=11ms
```

Compute-node coarsen detail：

```text
enabled=true
chain_merge=true
iterations=1
out1_merges=391726
in1_merges=253360
sibling_merges=292438
clusters_before=1396066
clusters_after=458542
tail_stopped=false
tail_iterations=0
segments=51701
compute_supernodes=51701
```

Coarsen shape：

```text
clusters=458542
isolated=15340
sources=88764
sinks=115916
linear=347
forks=283785
joins=350271
max_pred=1541
max_succ=51668
op_size_min=1
op_size_mean=14
op_size_p50=3
op_size_p90=22
op_size_max=1728
```

Final schedule summary：

```text
supernodes=52242
compute_supernodes=51745
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
initial_compute_supernodes=458542
initial_compute_supernode_ops_total=6429337
initial_compute_supernode_dag_edges=1881311
initial_boundary_values=1115605
initial_boundary_activation_edges=2619863
initial_compute_compute_value_pairs=2269340
initial_compute_commit_value_pairs=350523
compute_supernodes=51745
commit_supernodes=497
topo_edges=10184708
graph_ops=7249135
graph_values=6725504
```

## 5. Emit / Build 数据

Emit 阶段：

```text
write_grhsim_cpp=45443ms
total=143059ms
```

Fresh emit/build `/usr/bin/time -v`：

```text
Elapsed (wall clock) time: 8:01.18
User time: 5734.40s
System time: 54.79s
CPU: 1203%
Maximum resident set size: 28330320 KB
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
grhsim_SimTop_sched_*.cpp: 130
```

## 6. CoreMark 50k Runtime 数据

日志：

- runtime log: [`../../build/logs/xs/xs_wolf_grhsim_20260709_single_round_chain16_50k.log`](../../build/logs/xs/xs_wolf_grhsim_20260709_single_round_chain16_50k.log)

Runtime progress：

```text
host_cycles=5000  host_ms=8338
host_cycles=10000 host_ms=19144
host_cycles=15000 host_ms=48247
host_cycles=20000 host_ms=87022
host_cycles=25000 host_ms=122088
host_cycles=30000 host_ms=158567
host_cycles=35000 host_ms=195133
host_cycles=40000 host_ms=231764
host_cycles=45000 host_ms=269522
host_cycles=50000 host_ms=316448
```

Runtime final：

```text
Core 0: EXCEEDING CYCLE/INSTR LIMIT at pc = 0x80001312
Core-0 instrCnt = 73580
cycleCnt = 49996
IPC = 1.471718
Guest cycle spent = 50001
Host time spent = 316459ms
```

折算速度：

```text
50001 guest cycles / 316.459s = 158.00 cycles/s
```

Runtime `/usr/bin/time -v`：

```text
Elapsed (wall clock) time: 5:16.47
User time: 316.35s
System time: 0.02s
CPU: 99%
Maximum resident set size: 129364 KB
Exit status: 0
```
