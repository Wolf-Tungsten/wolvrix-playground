# NO0086 GrhSIM Runtime-Aware Coarsen / Ordering Experiments

> 2026-05-11 继续从 `NO0085` 的 fresh post-stats JSON 恢复，验证“更强合并 / 更低静态 activation”是否能转化为 XiangShan CoreMark 50k 的真实速度收益。结论是：当前简单调大 `MAX_COMPUTE_NODE_IN_COMPUTE_SUPERNODE` 没有可保留方案，后续优化必须用 runtime-aware 门禁筛选。

## 背景基线

本轮不重新从 SV 读取开始，统一使用 `NO0085` 产物：

```bash
WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1
WOLVRIX_XS_GRHSIM_POST_STATS_JSON=/home/gaoruihao/wksp/wolvrix-playground/build/xs/grhsim/wolvrix_xs_post_stats.json
```

baseline 结构来自 fresh original topo：

| 指标 | baseline |
| --- | ---: |
| `supernodes` | `85885` |
| `compute_supernodes` | `79801` |
| `commit_supernodes` | `6084` |
| `dag_edges` | `743311` |
| `boundary_activation_edges` | `2545743` |
| `other_compute_duplicate_ratio` | `71.81%` |
| `ops_p99` | `671` |
| `outdeg_p99` | `58` |
| `runtime_risk_score` | `1375089.3` |

baseline CoreMark 50k perf：

| 指标 | baseline |
| --- | ---: |
| `emu_host_time_ms` | `386385` |
| `perf_elapsed_s` | `386.396` |
| `instructions` | `276487037094` |
| `branches` | `29924233870` |
| `branch_misses` | `16068534840` |
| `cache_misses` | `48458293920` |

## DP 合并作用量化

不能简单说 DP 没起作用。当前数量合并是明显的：

| 阶段 | 数量 |
| --- | ---: |
| `compute_nodes` | `1380259` |
| `clusters_before` | `1380259` |
| `clusters_after` | `1066173` |
| `compute_supernodes` | `79801` |

即：

- coarsen 把 `1380259` 个初始 cluster 压到 `1066173`，减少 `22.75%`。
- DP / final packing 把 `1066173` 个 cluster 压到 `79801` 个 compute supernode，约 `13.36:1`。
- 但 `boundary_activation_edges` 仍为 `2545743`，`other_compute_duplicate_ratio` 仍为 `71.81%`。

因此问题不是“DP 完全没合并”，而是当前 DP 主要优化 supernode 数量和局部规模约束，没有直接优化 runtime 成本；activation multiplicity、函数体大小、分支/缓存压力之间也不是单调关系。

## 简单增大合并粒度实验

本轮只调整 `XS_WOLF_GRHSIM_MAX_COMPUTE_NODE_IN_COMPUTE_SUPERNODE`，全部从同一份 post-stats JSON 恢复。

| 方案 | `compute_supernodes` | `dag_edges` | `boundary_activation_edges` | `ops_p99` | `runtime_risk_score` | 结构判断 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| baseline | `79801` | `743311` | `2545743` | `671` | `1375089.3` | baseline |
| size16 | `89678` | `809848` | `2600582` | `590` | `1485618.2` | reject，risk `+8.04%` |
| size20 | `71695` | `702189` | `2521848` | `760` | `1299153.8` | 进入 perf |
| size24 | `60121` | `622291` | `2448421` | `768` | `1169617.1` | 进入 perf |
| size32 | `45199` | `535583` | `2367434` | `896` | `1017122.4` | 进入 perf |

结构上 size24/32 看起来更好，但它们同时显著增加 `ops_p99`、每个 compute supernode 的 value pair 数和 activation / DAG edge。

## CoreMark 50k 实测

perf 命令口径：

```bash
env -u EMU_RUNTIME_PROFILE EMU_PROGRESS_EVERY_CYCLES=0 \
  perf stat -e cycles,instructions,branches,branch-misses,cache-references,cache-misses,duration_time,user_time,system_time \
  build/xs/grhsim/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 50000
```

三轮 perf 的 guest 进度一致：`instrCnt=73580`、`cycleCnt=49996`、`IPC=1.471718`、结束 PC `0x80001312`。

| 方案 | `perf_elapsed_s` | vs baseline | `instructions` | vs baseline | `cache_misses` | vs baseline | 结论 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| baseline | `386.396` | baseline | `276487037094` | baseline | `48458293920` | baseline | 保留 |
| size20 | `391.942` | `+1.44%` | `279281676131` | `+1.01%` | `48539249282` | `+0.17%` | reject |
| size24 | `398.436` | `+3.12%` | `290034349640` | `+4.90%` | `49488804250` | `+2.13%` | reject |
| size32 | `423.188` | `+9.52%` | `313373134553` | `+13.34%` | `51800298019` | `+6.90%` | reject |

结论：简单加大 final compute supernode 粒度虽然减少 DAG edge 和部分 activation edge，但在 CoreMark 50k 上没有速度收益。主要负面信号是 retired instructions 随粒度增大而增加，size24/32 的 cache miss 也同步增加。

## 当前判断

1. 静态 `boundary_activation_edges` 不能单独作为默认优化目标。`NO0085` 的 activation-affinity ordering 降低静态 activation `12.82%`，但 wall time 回退 `18.49%`。
2. 简单增大 supernode 上限也不能作为默认优化目标。size32 结构 risk 下降 `26.03%`，但 wall time 回退 `9.52%`。
3. 当前 runtime 更敏感的是 generated code footprint、host instructions、branch/cache 压力和 supernode 内函数体规模。
4. 后续 ordering / coarsen 仍值得做，但必须局部化、受限化，并以 perf 结果作为保留条件。

## 后续推进计划

后续每个候选方案按四级门禁推进：

| 阶段 | 目标 | 保留条件 |
| --- | --- | --- |
| A. JSON resume 结构实验 | 不从 SV 重跑，快速生成 stats | `runtime_risk_score` 不上升，且 `ops_p99/outdeg_p99` 不显著恶化 |
| B. build / code footprint 检查 | 重建 emu，观察生成代码风险 | sched 数量、重尾函数体、编译失败/拖尾不能恶化 |
| C. CoreMark 50k perf | 同口径 `perf stat` 实测 | `perf_elapsed_s` 必须低于 baseline，且 instructions/cache 不显著恶化 |
| D. 复测确认 | 对有效候选再跑一次 | 仍稳定快于 baseline 才考虑默认启用 |

优先实验方向：

1. 局部 ordering：只在同一 parent / 同一近邻边界集合内改变 topo ready tie-break，避免 `NO0085` 那种全局 affinity 重排导致 DAG 和函数分布失控。
2. runtime-aware DP cost：cost 同时约束 `boundary_activation_edges`、`ops_p99`、`outdeg_p99`、segment 数，禁止为了 activation 降低而扩大函数体。
3. coarsen 阶段减少 boundary 泄出：优先吞掉单消费者/近邻共享 boundary value，而不是事后把更大的 compute cluster 强行打包。
4. activation 传播汇聚检查：确认同一 supernode pair 上重复 value 的传播是否能在 emitter/runtime 层做聚合，而不是只在图结构上减少边。

本轮没有产生应保留的默认代码方案；保留的是实验脚本和门禁规则。

## 产物

- `scripts/grhsim_opt_metrics.py`
- `build/logs/xs/grhsim_opt_baseline_original_topo_metrics.json`
- `build/logs/xs/grhsim_opt/size16_metrics.json`
- `build/logs/xs/grhsim_opt/size20_perf_metrics.json`
- `build/logs/xs/grhsim_opt/size24_perf_metrics.json`
- `build/logs/xs/grhsim_opt/size32_perf_metrics.json`
- `build/logs/xs/grhsim_opt/size20_coremark50k_perf.log`
- `build/logs/xs/grhsim_opt/size24_coremark50k_perf.log`
- `build/logs/xs/grhsim_opt/size32_coremark50k_perf.log`

## 追加实验 2026-05-11

继续尝试两个更保守的候选，仍然遵守“先结构、后 perf”的门禁。两个候选都没有进入 perf 阶段，代码改动已撤回。

### Segment Boundary Refinement

候选思路：不做全局 topo affinity reorder，不增大 `MAX_COMPUTE_NODE_IN_COMPUTE_SUPERNODE`，只在 greedy segment 之后对相邻 segment 边界做局部 cluster 移动，期望减少跨 segment cut。

执行口径：

```bash
WOLVRIX_XS_GRHSIM_ENABLE_SEGMENT_REFINE=1 \
WOLVRIX_XS_GRHSIM_SEGMENT_REFINE_MAX_ITER=4 \
make xs_wolf_grhsim_emit \
  RUN_ID=20260511_segment_refine_struct \
  XS_WOLF_GRHSIM_RESUME_FROM_STATS_JSON=1 \
  XS_WOLF_GRHSIM_MAX_COMPUTE_NODE_IN_COMPUTE_SUPERNODE=16
```

结果：

| 指标 | baseline | segment refine | 变化 |
| --- | ---: | ---: | ---: |
| `compute_supernodes` | `79801` | `89678` | `+12.38%` |
| `dag_edges` | `743311` | `809847` | `+8.95%` |
| `boundary_activation_edges` | `2545743` | `2600582` | `+2.15%` |
| `ops_p99` | `671` | `590` | `-12.07%` |
| `outdeg_p99` | `58` | `57` | `-1.72%` |
| `runtime_risk_score` | `1375089.3` | `1485617.2` | `+8.04%` |

这个结果与 size16 负例基本一致，说明该 refinement 没有改变最终结构，只额外引入了实验复杂度。结构门禁失败，不进入 emu build / perf。

产物：

- `build/logs/xs/grhsim_opt/segment_refine_size16_activity_schedule_supernode_stats.json`
- `build/logs/xs/grhsim_opt/segment_refine_size16_metrics.json`
- `build/logs/xs/xs_wolf_grhsim_build_20260511_segment_refine_struct.log`

### Local Shared Compute

候选思路：针对日志中的 `boundary_shared=990412`，启用已有但默认关闭的 `enable_local_shared_compute`，尝试把低 fanout / 低 width 的共享公共表达式吸收到本地 compute node，减少 boundary 泄出。

执行口径：

```bash
WOLVRIX_XS_GRHSIM_ENABLE_LOCAL_SHARED_COMPUTE=1 \
make xs_wolf_grhsim_emit \
  RUN_ID=20260511_local_shared_struct \
  XS_WOLF_GRHSIM_RESUME_FROM_STATS_JSON=1 \
  XS_WOLF_GRHSIM_MAX_COMPUTE_NODE_IN_COMPUTE_SUPERNODE=16
```

结果：`activity-schedule` 失败，没有 stats 产物。

```text
error [activity-schedule] activity-schedule compute-node topo failed: toposort failed: graph contains cycle (SimTop)
```

随后加过一个更保守 guard，只允许 local shared compute 吸收“不依赖其他 compute op”的表达式，仍然复现同样 cycle：

```text
error [activity-schedule] activity-schedule compute-node topo failed: toposort failed: graph contains cycle (SimTop)
```

判断：当前 `local_shared_compute` 的吸收模型会破坏 compute-node DAG 无环性，不能作为候选继续 perf。后续若重启这条线，必须先把“共享表达式复制”改成真正 clone 新 op/value 到 consumer，而不是把原 def op 重新归属到某个 consumer node。

产物：

- `build/logs/xs/xs_wolf_grhsim_build_20260511_local_shared_struct.log`
- `build/logs/xs/xs_wolf_grhsim_build_20260511_local_shared_guarded_struct.log`

### 追加结论

本轮新增两个候选也没有保留：

1. `segment_refine` 结构门禁失败，`runtime_risk_score +8.04%`。
2. `local_shared_compute` 语义/拓扑门禁失败，compute-node DAG 出环。
3. 当前没有任何默认代码方案应进入主路径；保留的是 JSON resume 测试流程、metrics 汇总脚本和负结果记录。

下一步更合理的方向是实现真正的 runtime-aware clone：对低 fanout shared compute 复制新 op/value 到 consumer node，并保证不改写原 def op ownership；同时在结构门禁里额外统计 cloned op 数和 generated code footprint 风险。
