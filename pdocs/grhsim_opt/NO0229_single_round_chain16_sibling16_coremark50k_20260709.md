# NO0229 Single-Round Chain16 Sibling16 CoreMark 50k Snapshot

## 1. 记录目的

本文记录 2026-07-09 在单轮 `activity-schedule` plain coarsen 基础上，
固定 `out1` / `in1` chain merge 上限为
`16 * maxOpInComputeSupernode`，并把 `siblings` merge 上限从
`4 * maxOpInComputeSupernode` 放宽到
`16 * maxOpInComputeSupernode` 后的 XiangShan `CoreMark 50k`
fresh emit/build/runtime 快照。

## 2. 代码改动

本轮修改：

- 保持 coarsen 只执行一轮 `out1 -> in1 -> siblings`。
- `out1` / `in1` 合并 op 上限为 `16 * maxOpInComputeSupernode`。
- `siblings` 合并 op 上限改为 `16 * maxOpInComputeSupernode`。
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
20260709_single_round_chain16_sibling16_50k
```

Fresh emit/build 命令：

```bash
source env.sh && /usr/bin/time -v make --no-print-directory xs_wolf_grhsim_emu \
  RUN_ID=20260709_single_round_chain16_sibling16_50k \
  XS_SIM_MAX_CYCLE=50000 \
  XS_PROGRESS_EVERY_CYCLES=5000 \
  XS_COMMIT_TRACE=0 \
  XS_WAVEFORM=0 \
  WOLVRIX_GRHSIM_WAVEFORM=0
```

Runtime 命令：

```bash
source env.sh && /usr/bin/time -v make --no-print-directory run_xs_wolf_grhsim_emu \
  RUN_ID=20260709_single_round_chain16_sibling16_50k \
  XS_SIM_MAX_CYCLE=50000 \
  XS_PROGRESS_EVERY_CYCLES=5000 \
  XS_COMMIT_TRACE=0 \
  XS_WAVEFORM=0 \
  WOLVRIX_GRHSIM_WAVEFORM=0
```

## 4. Activity-Schedule 结构数据

日志：

- build log: [`../../build/logs/xs/xs_wolf_grhsim_build_20260709_single_round_chain16_sibling16_50k.log`](../../build/logs/xs/xs_wolf_grhsim_build_20260709_single_round_chain16_sibling16_50k.log)

`activity-schedule` 总耗时：

```text
build_op_data=5313ms
compute_node_build=20289ms
freeze_after_compute_node=0ms
final_materialize=15751ms
export_session=106ms
total=59375ms
```

`materializeComputeNodeSchedule` 分解：

```text
init_clusters=47ms
topo_before_coarsen=312ms
coarsen=6649ms
topo_after_coarsen=156ms
build_cluster_view=102ms
dp_segment=1833ms
flatten_segments=18ms
build_final_supernodes=1383ms
build_final_dag=2360ms
build_state_read_sets=2399ms
final_topo=11ms
```

Compute-node coarsen detail：

```text
enabled=true
chain_merge=true
iterations=1
out1_merges=391726
in1_merges=253360
sibling_merges=294347
clusters_before=1396066
clusters_after=456633
tail_stopped=false
tail_iterations=0
segments=49565
compute_supernodes=49565
```

Coarsen shape：

```text
clusters=456633
isolated=15340
sources=88764
sinks=114564
linear=354
forks=283046
joins=348581
max_pred=1541
max_succ=51368
op_size_min=1
op_size_mean=14
op_size_p50=3
op_size_p90=21
op_size_max=1728
```

Final schedule summary：

```text
supernodes=50107
compute_supernodes=49610
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
initial_compute_supernodes=456633
initial_compute_supernode_ops_total=6429337
initial_compute_supernode_dag_edges=1855260
initial_boundary_values=1115605
initial_boundary_activation_edges=2594965
initial_compute_compute_value_pairs=2244442
initial_compute_commit_value_pairs=350523
compute_supernodes=49610
commit_supernodes=497
topo_edges=10184708
graph_ops=7249135
graph_values=6725504
```

## 5. Emit / Build 数据

Emit 阶段：

```text
write_grhsim_cpp=44509ms
total=141574ms
```

Fresh emit/build `/usr/bin/time -v`：

```text
Elapsed (wall clock) time: 8:01.45
User time: 5927.13s
System time: 56.88s
CPU: 1242%
Maximum resident set size: 28331448 KB
Exit status: 0
```

生成产物：

```text
build/xs/grhsim/grhsim-compile/emu: 102M
build/xs/grhsim/grhsim_emit/libgrhsim_SimTop.a: 108M
build/xs/grhsim/grhsim_emit/grhsim_static_stats.json: 12M
```

本轮生成的 schedule C++ translation unit 数：

```text
grhsim_SimTop_sched_*.cpp: 129
```

## 6. CoreMark 50k Runtime 数据

日志：

- runtime log: [`../../build/logs/xs/xs_wolf_grhsim_20260709_single_round_chain16_sibling16_50k.log`](../../build/logs/xs/xs_wolf_grhsim_20260709_single_round_chain16_sibling16_50k.log)

Runtime progress：

```text
host_cycles=5000  host_ms=8088
host_cycles=10000 host_ms=18785
host_cycles=15000 host_ms=48827
host_cycles=20000 host_ms=88994
host_cycles=25000 host_ms=125070
host_cycles=30000 host_ms=162662
host_cycles=35000 host_ms=200251
host_cycles=40000 host_ms=237940
host_cycles=45000 host_ms=276958
host_cycles=50000 host_ms=325073
```

Runtime final：

```text
Core 0: EXCEEDING CYCLE/INSTR LIMIT at pc = 0x80001312
Core-0 instrCnt = 73580
cycleCnt = 49996
IPC = 1.471718
Guest cycle spent = 50001
Host time spent = 325085ms
```

折算速度：

```text
50001 guest cycles / 325.085s = 153.81 cycles/s
```

Runtime `/usr/bin/time -v`：

```text
Elapsed (wall clock) time: 5:25.09
User time: 324.99s
System time: 0.02s
CPU: 99%
Maximum resident set size: 129332 KB
Exit status: 0
```

## 7. 与 chain16 / sibling4 对比

| 实验 | chain cap | sibling cap | compute supernodes | BAE | compute-compute value pairs | op p90 | op max | host time | cycles/s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| [`NO0226`](./NO0226_single_round_chain16_coremark50k_20260709.md) | `16x` | `4x` | `51745` | `2619863` | `2269340` | `22` | `1728` | `316459ms` | `158.00` |
| `NO0229` | `16x` | `16x` | `49610` | `2594965` | `2244442` | `21` | `1728` | `325085ms` | `153.81` |

相对 `chain16/sibling4`：

- `compute_supernodes -2135`，即 `-4.13%`。
- BAE `-24898`，即 `-0.95%`。
- compute-compute value pairs `-24898`，即 `-1.10%`。
- `op_size_p90 22 -> 21`，即 `-4.55%`。
- `op_size_max` 保持 `1728`，没有继续降低。
- 单次 runtime `316459ms -> 325085ms`，差约 `+2.73%`。
- 单次 cycles/s `158.00 -> 153.81`，差约 `-2.65%`。

结论需要保守：`sibling16` 的结构指标确实比 `sibling4` 更紧，尤其 final
compute supernode、BAE、compute-compute value pairs 都下降；但本轮单次 runtime
没有显示出收益，反而更慢。考虑到目前仍是单次样本，不能据此断言稳定性能退化。
更合理的解释是：放宽 sibling merge 降低了跨边界激活数量，但可能把共享前驱、
实际动态相关性不足的 sibling 合到同一 compute supernode 内，增加了局部 over-eval；
是否真实抵消边界收益，需要多轮 runtime 或 runtime activation/weighted-checks 统计确认。

