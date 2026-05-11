# NO0087 当前 GSim / GrhSIM 量化分析、Profile 与 Perf 复测

## 1. 本次口径

本记录只使用 `2026-05-11` 重新运行的数据，不沿用 `NO0076` / `NO0077` / `NO0081` 的旧数字。

关键产物：

- fresh stats run: `make xs_no0076_stats RUN_ID=20260511_no0087_fresh_stats`
- GSim stats: `build/xs/gsim/gsim-compile/model/SimTop_supernode_stats.json`
- GrhSIM stats: `build/xs/grhsim/grhsim_emit/activity_schedule_supernode_stats.json`
- GrhSIM post-stats: `build/xs/grhsim/wolvrix_xs_post_stats.json`
- 汇总 JSON: `build/xs/grhsim/no0087_current_quant_metrics.json`
- GSim emu build: `make xs_gsim_emu RUN_ID=20260511_no0087_profile XS_VM_BUILD_JOBS=32`
- GrhSIM emu build: `make xs_wolf_grhsim_emu RUN_ID=20260511_no0087_profile XS_VM_BUILD_JOBS=32 XS_WOLF_GRHSIM_RESUME_FROM_STATS_JSON=1 XS_WOLF_GRHSIM_MAX_COMPUTE_NODE_IN_COMPUTE_SUPERNODE=18`
- runtime profile logs:
  - `build/logs/xs/no0087_gsim_runtime_profile.log`
  - `build/logs/xs/no0087_grhsim_runtime_profile.log`
- perf logs:
  - `build/logs/xs/no0087_gsim_perf_basic.log`
  - `build/logs/xs/no0087_grhsim_perf_basic.log`

GrhSIM 本次口径：`max_compute_node_in_compute_supernode=18`，`max_op_in_compute_node=8192`，`max_op_in_commit_supernode=768`。GSim stats 为本次扩展后的 stats emitter，额外记录了 `enode_out_degree` / `ref_enode_out_degree` / `non_ref_enode_out_degree`。

## 2. 图规模对比

| 指标 | GSim | GrhSIM | GrhSIM / GSim |
| --- | ---: | ---: | ---: |
| supernodes | 84,714 | 85,885 | 1.014x |
| DAG edges | 645,829 | 743,311 | 1.151x |
| boundary activation edges | 1,378,665 | 2,545,743 | 1.847x |

GrhSIM 当前最终 supernode 数量只比 GSim 多 `1,171` 个，但 supernode DAG edges 多 `97,482` 条，boundary activation edges 多 `1,167,078` 条。这说明当前主要差距仍不是点数，而是跨 supernode 传播边更密。

## 3. compute op 与 enode 规模 / 出度

| 指标 | 数值 |
| --- | ---: |
| GrhSIM top total ops | 5,284,053 |
| GrhSIM top compute ops | 4,390,655 |
| GrhSIM top source ops | 315,585 |
| GrhSIM top sink ops | 290,531 |
| GrhSIM top declaration ops | 287,282 |
| GSim unique enodes | 13,811,952 |
| GSim ref enodes | 8,793,011 |
| GSim non-ref enodes | 5,018,941 |
| GSim non-ref enodes / GrhSIM compute ops | 1.143x |

出度定义：

- GSim `enode_out_degree`: 本次在 `cppEmitter` stats 中记录的 unique ENode child count。
- GrhSIM `compute_op_out_degree_all_users`: 对每个 top graph compute op，统计其所有输出 value 的 unique user op 数。
- GrhSIM `compute_op_out_degree_compute_users`: 同上，但只保留 user 也属于 compute op 的边。

| 出度分布 | count | sum | zero | mean | median | p90 | p99 | max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| GSim all enodes | 13,811,952 | 8,144,532 | 10,028,404 | 0.590 | 0 | 2 | 3 | 2,000 |
| GSim ref enodes | 8,793,011 | 474,442 | 8,453,414 | 0.054 | 0 | 0 | 2 | 3 |
| GSim non-ref enodes | 5,018,941 | 7,670,090 | 1,574,990 | 1.528 | 2 | 3 | 3 | 2,000 |
| GrhSIM compute op all users | 4,390,655 | 7,889,814 | 13,761 | 1.797 | 1 | 2 | 10 | 120,557 |
| GrhSIM compute op compute users | 4,390,655 | 7,275,799 | 336,992 | 1.657 | 1 | 2 | 9 | 47,693 |

这个对比里最突出的不是平均值，而是尾部：GSim non-ref ENode p99 只有 `3`，GrhSIM compute-op compute-user p99 是 `9`，max 到 `47,693`。这和 supernode 级 activation edges 偏多是一致的：GrhSIM 的原始 compute graph 里存在更重的高 fanout compute op，后续粗化/ordering 很容易把这些 fanout 转成跨 supernode activation。

## 4. GrhSIM 合并与 activation 构成

GrhSIM activity-schedule 本次统计：

| 指标 | 数值 |
| --- | ---: |
| compute nodes before coarsen | 1,380,259 |
| clusters before coarsen | 1,380,259 |
| clusters after coarsen | 1,066,173 |
| coarsen out1 merges | 114,217 |
| coarsen in1 merges | 199,869 |
| compute supernodes | 79,801 |
| commit supernodes | 6,084 |
| compute node ops total | 6,071,280 |
| compute node boundary inputs total | 4,840,091 |

activation edges 构成：

| 类别 | edges |
| --- | ---: |
| compute -> compute value pairs | 2,163,497 |
| compute -> commit value pairs | 382,246 |
| state read activation edges | 153,369 |
| constant activation edges | 41,516 |
| other compute activation edges | 2,350,858 |

合并确实在起作用：`clusters_before=1,380,259` 降到 `clusters_after=1,066,173`，直接合并 `314,086` 个 cluster。但是最终 `boundary_activation_edges=2,545,743` 仍显著高于 GSim 的 `1,378,665`，说明当前问题不是“完全没有合并”，而是合并没有有效压住高 fanout / 多目标 activation 的尾部。

## 5. 生成二进制静态对比

本次二进制 mtime：

| 项 | GSim | GrhSIM |
| --- | ---: | ---: |
| emu path | `build/xs/gsim/gsim-compile/emu` | `build/xs/grhsim/grhsim-compile/emu` |
| mtime | `2026-05-11 10:45:33 +0800` | `2026-05-11 10:53:09 +0800` |
| file size | 56,020,248 B | 120,081,200 B |
| `.text` | 55,892,978 B | 119,751,017 B |
| static disasm instructions | 9,841,136 | 23,151,907 |

比例：

| 指标 | GrhSIM / GSim |
| --- | ---: |
| file size | 2.144x |
| `.text` | 2.143x |
| static disasm instructions | 2.353x |

静态二进制层面，GrhSIM 仍然是明显更大的 code footprint；这会直接放大 i-cache / frontend / branch predictor 压力。

## 6. Runtime Profile 复测

命令口径：

```bash
EMU_RUNTIME_PROFILE=1 EMU_PROGRESS_EVERY_CYCLES=0 build/xs/{gsim,grhsim}/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 50000
```

结果：

| 指标 | GSim | GrhSIM | GrhSIM / GSim |
| --- | ---: | ---: | ---: |
| guest cycle spent | 50,001 | 50,001 | 1.000x |
| core cycleCnt | 49,998 | 49,996 | 1.000x |
| instrCnt | 73,584 | 73,580 | 1.000x |
| IPC | 1.471739 | 1.471718 | 1.000x |
| host time | 33,216 ms | 385,800 ms | 11.615x |
| sim speed | 1,505.30 cycles/s | 129.60 cycles/s | 0.086x |

注意：本次 `EMU_RUNTIME_PROFILE=1` 日志只输出了 enabled 标记和总运行结果，没有输出旧 profile 文档里的 GSim/GrhSIM 内部分项 counter。因此本记录不复用旧的 runtime breakdown，只记录本次可实际复现的总 profile 结果。

## 7. Perf Stat 复测

命令口径：

```bash
env -u EMU_RUNTIME_PROFILE EMU_PROGRESS_EVERY_CYCLES=0 perf stat \
  -e cycles,instructions,branches,branch-misses,cache-references,cache-misses,duration_time,user_time,system_time \
  build/xs/{gsim,grhsim}/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 50000
```

结果：

| perf 指标 | GSim | GrhSIM | GrhSIM / GSim |
| --- | ---: | ---: | ---: |
| duration | 33.330555 s | 385.858488 s | 11.577x |
| cycles | 189,554,283,332 | 2,213,706,232,198 | 11.678x |
| instructions | 80,037,357,697 | 276,380,640,551 | 3.453x |
| IPC | 0.42 | 0.12 | 0.297x |
| branches | 4,518,030,900 | 29,918,858,540 | 6.622x |
| branch misses | 1,856,683,441 | 16,080,124,309 | 8.661x |
| branch miss rate | 41.09% | 53.75% | 1.308x |
| cache references | 22,655,381,558 | 100,938,459,512 | 4.455x |
| cache misses | 12,244,444,134 | 48,274,882,810 | 3.943x |
| cache miss rate | 54.05% | 47.83% | 0.885x |

Perf 与静态数据的方向一致：GrhSIM host retired instructions 是 GSim 的 `3.45x`，但 host cycles / wall time 是 `11.6x`，说明不是单纯“指令数变多”能解释全部差距；更大的 code footprint、更多分支、明显更差 IPC 和更高 branch miss rate 共同放大了耗时。

## 8. 当前结论

1. 图规模上，GrhSIM supernode 数已经接近 GSim，但跨 supernode activation 仍是 `1.847x`。
2. compute-op 出度尾部比 GSim non-ref ENode 重得多；这比平均出度更值得关注。
3. 当前 DP / coarsen 并非没有作用，cluster 从 `1.38M` 降到 `1.066M`，但没有有效压住高 fanout activation。
4. 静态二进制 GrhSIM `.text` 是 GSim 的 `2.14x`，静态指令数是 `2.35x`。
5. runtime/perf 实测 GrhSIM 50k 约慢 `11.6x`；host instructions 只多 `3.45x`，剩余差距主要体现在低 IPC、branch pressure 和 cache/frontend footprint。

下一步如果要继续优化，优先级应放在“fanout-aware 的 compute-op / compute-node 汇聚”和“减少生成代码分支/footprint”上，而不是单纯继续放大 supernode size。
