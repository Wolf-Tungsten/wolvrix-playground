# NO0214 CBAW Compute Node Builder Decision

记录日期：2026-07-03

主关联：[`NO0210`](./NO0210_cross_boundary_activation_work_partition_plan_20260629.md)、[`NO0211`](./NO0211_cbaw_p0_evaluator_rollout_progress_20260701.md)、[`NO0212`](./NO0212_gsim_dp_stage_structure_gain_20260702.md)、[`NO0213`](./NO0213_cbaw_coarsen_improvement_plan_20260702.md)

历史对照：[`NO0076`](./NO0076_xs_gsim_grhsim_supernode_activation_stats_20260508.md)、[`NO0077`](./NO0077_xs_gsim_grhsim_runtime_profile_coremark_50k_20260509.md)、[`NO0087`](./NO0087_current_gsim_grhsim_quant_profile_perf_20260511.md)、[`NO0198`](./NO0198_xiangshan_coremark50k_runtime_profile_no_preserve_20260615.md)

状态：决策文档，已按 2026-07-03 fresh GSim / CBAW GrhSIM 数据重写。本文回答一个问题：下一步 CBAW 是否需要单独改进 compute node 建立，还是继续使用当前 compute-node/MFFC chunk atom 路径。

## 1. 结论

**不把独立 compute-node builder 作为下一步默认主线。继续使用当前 CBAW atom/materialization/evaluator 路径，优先推进 NO0213 的 exact-delta coarsen、DP 后 gap 收敛、P7 refinement 和 top multiplicity 诊断。**

2026-07-03 fresh 数据给出的核心事实是：

1. 当前 GrhSIM CBAW 的 compute node / atom 数不是比 GSim `graphPartition Node` 多，而是更少：`1396066` compute nodes / `1396096` atoms，对比 GSim `2708070` Nodes，约 `0.516x`。
2. 当前 CBAW final DAG 已低于 GSim：`609375 / 645831 = 0.944x`。但 boundary activation edges 仍明显更高：`2359493 / 1367270 = 1.726x`。这说明主问题不是“node 数量太多”，而是跨边界 value-target multiplicity 和单位执行成本。
3. `gsim ENode` 仍不能当作 `gsim Node`。fresh GSim unique ENode 是 `13811952`，其中 ref ENode `8793011`；更接近表达式计算层的 non-ref ENode 是 `5018941`，只比 GrhSIM compute-like ops `4382316` 多 `1.145x`。
4. 最新 CoreMark 50k host runtime gap 仍存在：no-profile 口径 GrhSIM `321007ms` vs GSim `46237ms`，约 `6.94x`；`EMU_RUNTIME_PROFILE=1` 口径 GrhSIM `331344ms` vs GSim `44777ms`，约 `7.40x`。当前 GrhSIM emu 未用 `GRHSIM_EMIT_RUNTIME_PROFILE=1` 构建，因此没有最新 aggregate solve counters；不能再把旧 NO0077 动态 solve 表当本文主证据。

因此，下一步应先把 CBAW 现有路径上的 BAE / compute-compute multiplicity 继续打穿，而不是 fork 一条新的 compute-node builder。builder 相关工作只能作为诊断和 gated refinement，触发条件见第 7 节。

## 2. Fresh 数据来源

本次重新取数如下：

| 路径 | 数据 | 时间 |
| --- | --- | --- |
| `tmp/no0214_gsim_rtprof_20260703/gsim-compile/model/SimTop_supernode_stats.json` | fresh GSim final supernode / ENode stats | `2026-07-03 12:04:12 +0800` |
| `build/logs/xs/xs_gsim_no0214_rtprof50k_20260703.log` | fresh GSim CoreMark 50k no-profile run | `2026-07-03 12:29:12 +0800` |
| `build/logs/xs/xs_gsim_no0214_rtprof50k_profile_20260703.log` | fresh GSim CoreMark 50k `EMU_RUNTIME_PROFILE=1` run | `2026-07-03 12:30:32 +0800` |
| `build/xs/grhsim/grhsim_emit/activity_schedule_supernode_stats.json` | current CBAW GrhSIM structure stats | `2026-07-03 10:40:28 +0800` |
| `build/logs/xs/xs_wolf_grhsim_build_ate_retired_cbaw_exact_fm8_full_20260703.log` | current CBAW full emit/build structure log | `2026-07-03 10:47:02 +0800` |
| `build/logs/xs/xs_wolf_grhsim_ate_retired_cbaw_exact_fm8_coremark50k_20260703.log` | current CBAW CoreMark 50k no-profile run | `2026-07-03 10:52:37 +0800` |
| `build/logs/xs/xs_wolf_grhsim_no0214_cbaw_fm8_rtprofile50k_20260703.log` | current CBAW CoreMark 50k `EMU_RUNTIME_PROFILE=1` host-time run | `2026-07-03 12:36:36 +0800` |
| `tmp/no0212_gsim_dp_boundary_profile_20260702/SimTop_DpProfileAfter*.json` | fresh GSim graphPartition entry / DP stage stats | `2026-07-02` |

数据限制：当前 `build/xs/grhsim/grhsim-compile/emu` 没有用 `GRHSIM_EMIT_RUNTIME_PROFILE=1` 生成，`EMU_RUNTIME_PROFILE=1` 只确认 harness 开关开启并给出 host time，没有输出 GrhSIM supernode fire TSV 或 aggregate work counters。本文因此只把最新 GrhSIM runtime 用作 host-time gate，不用旧动态 solve ratio 直接支撑当前决策。

## 3. 术语边界

- `gsim Node`：GSim `graphPartition()` 的划分顶点，也是和 `grhsim compute node` 最接近的结构口径。
- `gsim ENode`：GSim 表达式树节点，分为 ref / non-ref。它是表达式层口径，不是 partition Node。
- `grhsim compute node`：GrhSIM activity-schedule 在 compute supernode coarsen/DP 之前建立的 compute DAG 节点。
- `CBAW atom`：NO0211 P3 的 CBAW 划分原子；当前由 compute-node/MFFC chunk 路径建立。
- `compute supernode`：最终 runtime compute 调度单位，CBAW gate 使用其 `boundary_activation_edges`、`dag_edges`、`compute_compute_value_pairs`。

比较 builder 是否需要改，主口径必须是 `gsim Node` vs `grhsim compute node` / `CBAW atom`。`ENode` 只能作为表达式层补充，不能替代 `Node`。

## 4. 静态规模对比

### 4.1 入口划分图

| 指标 | GSim `graphPartition Node` | GrhSIM CBAW compute/atom | GrhSIM / GSim |
| --- | ---: | ---: | ---: |
| partition nodes / compute nodes | `2708070` | `1396066` | `0.516x` |
| CBAW atoms | - | `1396096` | `0.516x` vs GSim Nodes |
| direct edges / quotient edges | `4902060` | `3679158` | `0.750x` |
| avg direct/quotient out-degree | `1.810` | `2.635` | `1.456x` |

`quotient_edges` 和 GSim direct edges 不是完全同一层语义，但都是 builder/coarsen 入口附近的 DAG 密度 proxy。结论很稳定：GrhSIM 的节点数量更少，但边没有等比例下降，所以图更粗、更密。这个形态可能解释后续 multiplicity，但不能推出“必须先减少 compute node 数”。

### 4.2 Final partition

| 指标 | fresh GSim final | current CBAW GrhSIM final | GrhSIM / GSim |
| --- | ---: | ---: | ---: |
| supernodes | `84714` | `72369` | `0.854x` |
| `dag_edges` | `645831` | `609375` | `0.944x` |
| `boundary_activation_edges` | `1367270` | `2359493` | `1.726x` |
| BAE / supernode | `16.14` | `32.60` | `2.020x` |
| `compute_compute_value_pairs` | - | `2008970` | - |

这张表比旧数据更关键：CBAW final 的 DAG 已经低于 GSim，但 BAE 仍接近 `1.73x`。所以接下来最直接的目标不是换 builder，而是把跨边界 value-target 的重复激活和 materialized value 对数继续压下来。

### 4.3 ENode 层级

| 指标 | fresh GSim | current CBAW GrhSIM |
| --- | ---: | ---: |
| unique ENode | `13811952` | - |
| ref ENode | `8793011` | - |
| non-ref ENode | `5018941` | - |
| compute node ops total | - | `6429337` |
| source clones in compute nodes | - | `2047021` |
| compute-like ops | - | `4382316` |
| GSim non-ref ENode / GrhSIM compute-like ops | `1.145x` | - |

`unique ENode` 大是因为包含大量 ref ENode。把 `13811952` 直接拿来和 `1396066` compute nodes 比，会把表达式树层和 partition 层混在一起。正确读法是：表达式计算层两边量级接近，GSim non-ref ENode 约为 GrhSIM compute-like ops 的 `1.145x`；它不能说明 CBAW 需要单独重建 compute node。

## 5. 运行时数据

### 5.1 最新 host-time gate

| 运行 | GSim | GrhSIM CBAW | GrhSIM / GSim |
| --- | ---: | ---: | ---: |
| no-profile CoreMark 50k | `46237ms` | `321007ms` | `6.94x` |
| `EMU_RUNTIME_PROFILE=1` CoreMark 50k | `44777ms` | `331344ms` | `7.40x` |
| guest cycle | `50001` | `50001` | aligned |
| retired instr | `73584` | `73580` | aligned |

no-profile 和 profile run 都能跑满 50k bounded workload，说明 current CBAW 仍通过功能和 runtime gate，但相对 GSim 的 host gap 仍是 7x 左右。

### 5.2 fresh GSim dynamic counters

fresh GSim profile run 输出：

```text
[GSIM_RUNTIME_PROFILE] active_supernodes=766629270 nodes=35103020807 ref_enodes=114467111515 non_ref_enodes=66559770864 total_enodes=181026882379
```

折算：

| 指标 | 数值 |
| --- | ---: |
| nodes / active supernode | `45.79` |
| total enodes / active supernode | `236.13` |
| non-ref enodes / active supernode | `86.82` |

当前 GrhSIM CBAW 缺少同日 aggregate work counters，不能严格给出 fresh `compute-node solves` / `op solves` ratio。要补齐这一项，需要重新 emit/build 一份 `GRHSIM_EMIT_RUNTIME_PROFILE=1` 的 CBAW emu，并设置 `WOLVRIX_GRHSIM_SUPERNODE_TSV` 跑同一 workload。

### 5.3 本次 runtime 能支持什么结论

这次 fresh runtime 能支持的结论是：

- 当前 CBAW 的 host gap 仍真实存在：`6.94x` 到 `7.40x`。
- 这个 gap 出现在 GrhSIM compute node 数只有 GSim Node `0.516x`、final DAG 只有 GSim `0.944x` 的情况下。因此，单纯“另建更少 compute nodes”不是被数据直接支持的下一步。
- GrhSIM final BAE 是 GSim `1.726x`，且 BAE / supernode 是 `2.020x`。这和 runtime gap 的方向一致，说明 multiplicity / activation / materialization 仍是更直接的优化对象。
- 旧 NO0077 / NO0198 的动态 profile 可作为机制背景，但不作为本文对 current CBAW 的主证据；current CBAW 必须另跑 `GRHSIM_EMIT_RUNTIME_PROFILE=1` 才能更新动态 work ratio。

## 6. 与 NO0210/NO0211/NO0212/NO0213 的关系

### 6.1 NO0210 的目标仍正确

NO0210 定下的三个主指标仍是本问题的验收口径：

- `cross_boundary_target_count` -> `boundary_activation_edges`
- `supernode_dependency_edge_count` -> `dag_edges`
- `compute_materialized_value_target_count` -> `compute_compute_value_pairs`

fresh 数据显示，DAG 已不是当前最突出的差距；BAE / value-target multiplicity 才是。

### 6.2 NO0211 P3 atom 接口仍成立

当前 2026-07-03 CBAW build 仍给出无偏 replay：

```text
atom_count=1396096
quotient_edges=3679158
quotient_cycle=0
plain_replay_supernodes=71872
plain_replay_boundary_delta=0
plain_replay_dag_delta=0
plain_replay_compute_compute_delta=0
```

这说明当前 atom 接口本身可承载 CBAW evaluator / coarsen / refine。替换 builder 前，必须先证明问题集中在 atom 形成方式，而不是 P5/DP/P7 的选择策略或 value-target multiplicity accounting。

### 6.3 NO0212 的 DP 结论仍适用

GSim fresh DP profile：

| stage | supernodes | DAG / edge | BAE |
| --- | ---: | ---: | ---: |
| after coarsen / before DP | `294107` | `1168392` | `1548518` |
| after init partition / DP | `84863` | `646204` | `1367521` |

DP 让 edge 下降 `44.69%`，但 BAE 只下降 `11.69%`。这和 CBAW 当前 after-DP 仍有 BAE gap 的现象一致：只靠更强 DAG packing 不足以解决 value-target activation work。

### 6.4 NO0213 的当前路径已经有效

current CBAW exact-delta FM8 的最新结构数据：

| stage | boundary | dag | compute-compute |
| --- | ---: | ---: | ---: |
| plain baseline | `2446334` | `703270` | `2095811` |
| after P5 coarsen | `3160612` | `2520174` | `2810089` |
| after DP before FM | `2621811` | `650955` | `2271288` |
| after FM | `2356253` | `609345` | `2005730` |
| final P8 replay | `2359493` | `609375` | `2008970` |

P8 gate：

```text
runtime_allowed=1 reason=pass
plain_boundary=2446334 cbaw_boundary=2359493
plain_dag=703270 cbaw_dag=609375
plain_compute_compute=2095811 cbaw_compute_compute=2008970
```

这说明同一 atom 路径已经能把三项结构指标压到 plain 以下。当前最大的下一步缺口是 after-DP boundary 仍比 plain 高 `175477`，需要减少对 P7 FM 的兜底依赖。

## 7. 决策边界

默认路线保持：

```text
current graph
  -> compute-node/MFFC chunk atom
  -> CBAW candidate generation
  -> incident exact-delta P5 coarsen
  -> DP segment packing
  -> P7 boundary FM/swap
  -> P8 structure/runtime gate
```

不新增默认启用的独立 compute-node builder，不把 builder 替换作为 NO0213 后续优化的前置依赖。

允许的 builder 相关工作：

1. 加 top high-fanout / high-multiplicity root report，至少包含 root value、defining op、producer atom、external target supernode count、compute target count，以及 before/after P5、after-DP、after-FM 的 target count。
2. 加 compute-node shape report，回答 top roots 是否集中在少数不良 compute node / atom 形态上。
3. 做默认关闭的 atom-level local refinement，但必须复用 P0/P3 replay 校验，并输出三项主指标 before/after exact delta。
4. 补 current CBAW 的 `GRHSIM_EMIT_RUNTIME_PROFILE=1` 数据，再讨论 dynamic work ratio；没有这份数据时，不应以旧 solve ratio 决定 builder 主线。

只有同时满足以下条件，才把独立 compute-node builder 升级为主线：

1. top-root 诊断证明主要 BAE / compute-compute regression 稳定集中在 builder 形成的少数不良 atom 形态上。
2. 最小原型在 stop-after 上同时改善 `boundary_activation_edges`、`dag_edges`、`compute_compute_value_pairs`，并且 resource p99/p99.5 或 code-shape proxy 不回退。
3. full emit/build 不引入新的编译重尾或代码体积爆炸。
4. CoreMark 50k runtime 相对当前 CBAW FM8 不回退。

## 8. 回答

对“下一步对 CBAW 路径的 compute node 建立是否需要单独改进，是否还是用同一个路径”的回答是：

**继续用同一个 CBAW atom/materialization/evaluator 路径；不把独立 compute-node builder 作为下一步默认改进。**

最新数据反而把理由变得更清楚：GrhSIM compute node / CBAW atom 数只有 GSim Node 的约一半，final DAG 也低于 GSim；真正突出的结构差距是 BAE / supernode 和 value-target multiplicity。下一步应该把这些 multiplicity 根因做成诊断和受控 refinement，而不是先分叉 builder。
