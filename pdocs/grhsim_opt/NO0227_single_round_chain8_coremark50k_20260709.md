# NO0227 Single-Round Chain8 CoreMark 50k Snapshot

## 1. 记录目的

本文记录 2026-07-09 在单轮 `activity-schedule` plain coarsen 基础上，
把 `out1` / `in1` chain merge 合并上限继续收紧到
`8 * maxOpInComputeSupernode` 后的 XiangShan `CoreMark 50k`
fresh emit/build/runtime 快照。

## 2. 代码改动

本轮修改：

- 保持 coarsen 只执行一轮 `out1 -> in1 -> siblings`。
- `out1` / `in1` 合并 op 上限改为 `8 * maxOpInComputeSupernode`。
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
20260709_single_round_chain8_50k
```

Fresh emit/build 命令：

```bash
source env.sh && /usr/bin/time -v make --no-print-directory xs_wolf_grhsim_emu \
  RUN_ID=20260709_single_round_chain8_50k \
  XS_SIM_MAX_CYCLE=50000 \
  XS_PROGRESS_EVERY_CYCLES=5000 \
  XS_COMMIT_TRACE=0 \
  XS_WAVEFORM=0 \
  WOLVRIX_GRHSIM_WAVEFORM=0
```

Runtime 命令：

```bash
source env.sh && /usr/bin/time -v make --no-print-directory run_xs_wolf_grhsim_emu \
  RUN_ID=20260709_single_round_chain8_50k \
  XS_SIM_MAX_CYCLE=50000 \
  XS_PROGRESS_EVERY_CYCLES=5000 \
  XS_COMMIT_TRACE=0 \
  XS_WAVEFORM=0 \
  WOLVRIX_GRHSIM_WAVEFORM=0
```

## 4. Activity-Schedule 结构数据

日志：

- build log: [`../../build/logs/xs/xs_wolf_grhsim_build_20260709_single_round_chain8_50k.log`](../../build/logs/xs/xs_wolf_grhsim_build_20260709_single_round_chain8_50k.log)

`activity-schedule` 总耗时：

```text
build_op_data=5282ms
compute_node_build=20559ms
freeze_after_compute_node=0ms
final_materialize=15714ms
export_session=106ms
total=59701ms
```

`materializeComputeNodeSchedule` 分解：

```text
init_clusters=43ms
topo_before_coarsen=315ms
coarsen=6664ms
topo_after_coarsen=157ms
build_cluster_view=102ms
dp_segment=1916ms
flatten_segments=16ms
build_final_supernodes=1202ms
build_final_dag=2313ms
build_state_read_sets=2479ms
final_topo=12ms
```

Compute-node coarsen detail：

```text
enabled=true
chain_merge=true
iterations=1
out1_merges=360243
in1_merges=248708
sibling_merges=300621
clusters_before=1396066
clusters_after=486494
tail_stopped=false
tail_iterations=0
segments=52669
compute_supernodes=52669
```

Coarsen shape：

```text
clusters=486494
isolated=15340
sources=113461
sinks=116013
linear=374
forks=285978
joins=353439
max_pred=2405
max_succ=52034
op_size_min=1
op_size_mean=13
op_size_p50=3
op_size_p90=21
op_size_max=1026
```

Final schedule summary：

```text
supernodes=53206
compute_supernodes=52709
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
initial_compute_supernodes=486494
initial_compute_supernode_ops_total=6429337
initial_compute_supernode_dag_edges=1915497
initial_boundary_values=1147106
initial_boundary_activation_edges=2653814
initial_compute_compute_value_pairs=2303291
initial_compute_commit_value_pairs=350523
compute_supernodes=52709
commit_supernodes=497
topo_edges=10184708
graph_ops=7249135
graph_values=6725504
```

## 5. Emit / Build 数据

Emit 阶段：

```text
write_grhsim_cpp=45327ms
total=142970ms
```

Fresh emit/build `/usr/bin/time -v`：

```text
Elapsed (wall clock) time: 8:04.57
User time: 5799.50s
System time: 55.28s
CPU: 1208%
Maximum resident set size: 28331172 KB
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
grhsim_SimTop_sched_*.cpp: 128
```

## 6. CoreMark 50k Runtime 数据

日志：

- runtime log: [`../../build/logs/xs/xs_wolf_grhsim_20260709_single_round_chain8_50k.log`](../../build/logs/xs/xs_wolf_grhsim_20260709_single_round_chain8_50k.log)

Runtime progress：

```text
host_cycles=5000  host_ms=8415
host_cycles=10000 host_ms=19436
host_cycles=15000 host_ms=49144
host_cycles=20000 host_ms=88473
host_cycles=25000 host_ms=124316
host_cycles=30000 host_ms=161808
host_cycles=35000 host_ms=199217
host_cycles=40000 host_ms=236690
host_cycles=45000 host_ms=275272
host_cycles=50000 host_ms=322814
```

Runtime final：

```text
Core 0: EXCEEDING CYCLE/INSTR LIMIT at pc = 0x80001312
Core-0 instrCnt = 73580
cycleCnt = 49996
IPC = 1.471718
Guest cycle spent = 50001
Host time spent = 322826ms
```

折算速度：

```text
50001 guest cycles / 322.826s = 154.89 cycles/s
```

Runtime `/usr/bin/time -v`：

```text
Elapsed (wall clock) time: 5:22.84
User time: 322.73s
System time: 0.02s
CPU: 99%
Maximum resident set size: 129240 KB
Exit status: 0
```

## 7. 结论记录

单轮 coarsen + chain8 可以完成完整 XiangShan `CoreMark 50k`
fresh emit/build/runtime 流程，并在 difftest 运行中跑满 `50000` cycle limit。

本轮相对 chain16 继续拆小后，`compute_supernodes` 从 `51745` 增至 `52709`，
`initial_boundary_activation_edges` 从 `2619863` 增至 `2653814`，
单次 runtime 从 `316459ms` 到 `322826ms`。

注意：这两个 runtime 只有单次样本，约 6.4s / 2.0% 的差距可能落在机器负载、
调度和温度等噪声范围内，不能仅凭该数值断言 chain8 稳定慢于 chain16。
可以确定的是，chain8 相对 chain16 进一步增加了 supernode 数和边界激活规模；
本次样本也没有显示出把 chain cap 从 `16x` 砍到 `8x` 带来的明确 runtime 收益。

本轮 runtime 数值为：

```text
Host time spent = 322826ms
cycles/s = 154.89
instrCnt / cycleCnt = 73580 / 49996
```
