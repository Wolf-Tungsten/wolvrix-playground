# NO0228 Single-Round Chain4 CoreMark 50k Snapshot

## 1. 记录目的

本文记录 2026-07-09 在单轮 `activity-schedule` plain coarsen 基础上，
把 `out1` / `in1` chain merge 合并上限继续收紧到
`4 * maxOpInComputeSupernode` 后的 XiangShan `CoreMark 50k`
fresh emit/build/runtime 快照，并对 chain16 / chain8 / chain4 的趋势做归纳。

## 2. 代码改动

本轮修改：

- 保持 coarsen 只执行一轮 `out1 -> in1 -> siblings`。
- `out1` / `in1` 合并 op 上限改为 `4 * maxOpInComputeSupernode`。
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
20260709_single_round_chain4_50k
```

Fresh emit/build 命令：

```bash
source env.sh && /usr/bin/time -v make --no-print-directory xs_wolf_grhsim_emu \
  RUN_ID=20260709_single_round_chain4_50k \
  XS_SIM_MAX_CYCLE=50000 \
  XS_PROGRESS_EVERY_CYCLES=5000 \
  XS_COMMIT_TRACE=0 \
  XS_WAVEFORM=0 \
  WOLVRIX_GRHSIM_WAVEFORM=0
```

Runtime 命令：

```bash
source env.sh && /usr/bin/time -v make --no-print-directory run_xs_wolf_grhsim_emu \
  RUN_ID=20260709_single_round_chain4_50k \
  XS_SIM_MAX_CYCLE=50000 \
  XS_PROGRESS_EVERY_CYCLES=5000 \
  XS_COMMIT_TRACE=0 \
  XS_WAVEFORM=0 \
  WOLVRIX_GRHSIM_WAVEFORM=0
```

## 4. Activity-Schedule 结构数据

日志：

- build log: [`../../build/logs/xs/xs_wolf_grhsim_build_20260709_single_round_chain4_50k.log`](../../build/logs/xs/xs_wolf_grhsim_build_20260709_single_round_chain4_50k.log)

`activity-schedule` 总耗时：

```text
build_op_data=5225ms
compute_node_build=20205ms
freeze_after_compute_node=0ms
final_materialize=15757ms
export_session=104ms
total=59243ms
```

`materializeComputeNodeSchedule` 分解：

```text
init_clusters=49ms
topo_before_coarsen=314ms
coarsen=6726ms
topo_after_coarsen=162ms
build_cluster_view=106ms
dp_segment=1943ms
flatten_segments=16ms
build_final_supernodes=1191ms
build_final_dag=2305ms
build_state_read_sets=2430ms
final_topo=12ms
```

Compute-node coarsen detail：

```text
enabled=true
chain_merge=true
iterations=1
out1_merges=329670
in1_merges=240656
sibling_merges=306366
clusters_before=1396066
clusters_after=519374
tail_stopped=false
tail_iterations=0
segments=54161
compute_supernodes=54161
```

Coarsen shape：

```text
clusters=519374
isolated=15339
sources=141341
sinks=116141
linear=441
forks=288883
joins=358065
max_pred=2837
max_succ=52720
op_size_min=1
op_size_mean=12
op_size_p50=3
op_size_p90=20
op_size_max=1026
```

Final schedule summary：

```text
supernodes=54696
compute_supernodes=54199
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
initial_compute_supernodes=519374
initial_compute_supernode_ops_total=6429337
initial_compute_supernode_dag_edges=1955763
initial_boundary_values=1177418
initial_boundary_activation_edges=2687721
initial_compute_compute_value_pairs=2337198
initial_compute_commit_value_pairs=350523
compute_supernodes=54199
commit_supernodes=497
topo_edges=10184708
graph_ops=7249135
graph_values=6725504
```

## 5. Emit / Build 数据

Emit 阶段：

```text
write_grhsim_cpp=45024ms
total=142690ms
```

Fresh emit/build `/usr/bin/time -v`：

```text
Elapsed (wall clock) time: 8:02.41
User time: 5778.82s
System time: 54.98s
CPU: 1209%
Maximum resident set size: 28330980 KB
Exit status: 0
```

生成产物：

```text
build/xs/grhsim/grhsim-compile/emu: 102M
build/xs/grhsim/grhsim_emit/libgrhsim_SimTop.a: 109M
build/xs/grhsim/grhsim_emit/grhsim_static_stats.json: 13M
```

本轮生成的 schedule C++ translation unit 数：

```text
grhsim_SimTop_sched_*.cpp: 126
```

## 6. CoreMark 50k Runtime 数据

日志：

- runtime log: [`../../build/logs/xs/xs_wolf_grhsim_20260709_single_round_chain4_50k.log`](../../build/logs/xs/xs_wolf_grhsim_20260709_single_round_chain4_50k.log)

Runtime progress：

```text
host_cycles=5000  host_ms=8969
host_cycles=10000 host_ms=20439
host_cycles=15000 host_ms=50388
host_cycles=20000 host_ms=89886
host_cycles=25000 host_ms=125879
host_cycles=30000 host_ms=163450
host_cycles=35000 host_ms=200929
host_cycles=40000 host_ms=238471
host_cycles=45000 host_ms=277109
host_cycles=50000 host_ms=324663
```

Runtime final：

```text
Core 0: EXCEEDING CYCLE/INSTR LIMIT at pc = 0x80001312
Core-0 instrCnt = 73580
cycleCnt = 49996
IPC = 1.471718
Guest cycle spent = 50001
Host time spent = 324675ms
```

折算速度：

```text
50001 guest cycles / 324.675s = 154.00 cycles/s
```

Runtime `/usr/bin/time -v`：

```text
Elapsed (wall clock) time: 5:24.68
User time: 324.58s
System time: 0.02s
CPU: 99%
Maximum resident set size: 130844 KB
Exit status: 0
```

## 7. 16 / 8 / 4 趋势

| 实验 | chain cap | compute supernodes | BAE | compute-compute value pairs | op p90 | op max | host time | cycles/s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| [`NO0226`](./NO0226_single_round_chain16_coremark50k_20260709.md) | `16x` | `51745` | `2619863` | `2269340` | `22` | `1728` | `316459ms` | `158.00` |
| [`NO0227`](./NO0227_single_round_chain8_coremark50k_20260709.md) | `8x` | `52709` | `2653814` | `2303291` | `21` | `1026` | `322826ms` | `154.89` |
| `NO0228` | `4x` | `54199` | `2687721` | `2337198` | `20` | `1026` | `324675ms` | `154.00` |

从 chain16 继续砍到 chain8 / chain4 后，`op_size_p90` 和 `op_size_max`
确实继续下降；同时 `compute_supernodes`、BAE 和 compute-compute value pairs
持续上升：

- chain8 相对 chain16：`compute_supernodes +964`，BAE `+33951`，
  单次 runtime `316459ms -> 322826ms`，差约 `2.01%`。
- chain4 相对 chain8：`compute_supernodes +1490`，BAE `+33907`，
  单次 runtime `322826ms -> 324675ms`，差约 `0.57%`。

结论需要保守表述：这些 runtime 目前都只有单次样本，几秒到 8 秒左右的差异
可能是测量噪声，不能直接断言 chain16 稳定快于 chain8 / chain4。
但结构指标的趋势是确定的：继续降低 chain cap 会增加调度单元和跨边界激活，
而本轮单次样本没有显示出相应的明确 runtime 收益。因此当前只能说：
`16x` 以下继续收紧的收益不明显，且有过拆风险；若要定默认值，需要对
chain16 / chain8 / chain4 做多轮重复采样或固定更严格的 perf 环境后再判定。
