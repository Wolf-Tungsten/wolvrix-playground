---
id: NO00025
date: 2026-07-15
title: Direct SV versus GSim executable GRH shape, schedule, and C++ comparison
kind: diagnosis
status: active
area: simulation
topic: gsim-grhsim-exchange
tags: [gsim, grhsim, grh-json, activity-schedule, codegen, compile-time, xiangshan]
parents: [NO00024]
related: [NO00001, NO00002, NO00023]
supersedes: []
---

# NO00025 Direct SV versus GSim executable GRH shape, schedule, and C++ comparison (2026-07-15)

> 归档编号：`NO00025`。主题导航：
> `tree/simulation/gsim-grhsim-exchange/00/000-099.md`。

## 结论先行

在现有最接近的全量 XiangShan 产物中，GSim executable JSON 路线的主要问题不是 C++
总字节数更大，而是输入 GRH 更显式、`kAssign`/coercion 更密集，事件 key 又高度收敛，最终
形成了不同的调度形状和更高的单行表达式复杂度：

1. 原参数下，GSim 在 `activity-schedule` 前有 7,757,160 个 eligible ops，比 fresh direct
   SV 的 4,944,502 多 56.9%；source clone 后为 10,419,369 对 6,990,363，多 49.1%。
2. GSim 的 compute node 反而少 21.1%，但最终 compute supernode 多 78.4%。这说明差异不是
   简单的“节点更多”，而是 GSim 图中更大的初始 compute cone 被 108-op hard cap 切成了更多
   final segments。
3. GSim 只有 6 个 commit event keys，direct SV 有 450 个。旧实现因此把 111,852 个同
   event/guard sinks 放进一个 commit node；NO00024 修复后虽降到 4,096，事件结构仍没有恢复
   为 direct SV 的形状。
4. 修复 commit bucket 后，GSim C++ 为 1.321 GB、10.682 M 行，实际上比 direct SV 的
   1.379 GB、13.905 M 行更小；但 GSim schedule code 中 `static_cast` 出现 14.515 M 次，
   direct SV 为 9.070 M 次。GSim 每行平均 1.359 次，对 direct 的 0.652 次，是 2.08 倍。
5. 因而“半小时编不完”不能归因于 C++ 总量。证据指向少数表达式密度高的 compute TU
   形成 clang `-O3` 长尾；拆 commit bucket 和增加 TU 数量只能改善切分，不能消除这种单 TU
   编译复杂度。

## 比较边界与限制

### 主样本

direct SV 使用 2026-07-13 fresh `read_sv` 全流程：

```text
build/logs/xs_perf/grhsim_retest_20260713/fresh_read_sv_emit.log
build/xs_perf/grhsim_retest_20260713/grhsim/model/
```

GSim 使用 NO00023/NO00024 的同一份 executable artifact：

```text
ptmp/gsim_full_exec_20260714/run14/gsim/SimTop.exec.json
ptmp/gsim_full_exec_20260714/run14/logs/xs_gsim_executable_grh_import_run14_import_fresh.log
ptmp/gsim_full_exec_20260714/run15_schedule_commit_cap/
ptmp/gsim_full_exec_20260714/run15_grhsim_emit_commit_cap/
```

两者都使用：

```text
max_op_in_compute_supernode=108
max_op_in_compute_node=108
split_oversize_compute_nodes=True
split_oversize_compute_node_max_ops=108
max_op_in_commit_supernode=4096
commit_guard_event_buckets=True
declared_value_compute_node_boundary=False
final_topo_policy=level-id
sched_batch_max_ops=2048
sched_batch_max_estimated_lines=8192
sched_batch_target_count=64
sched_batches_per_cpp=1
```

这是现存产物中最接近“原先参数”的可比组。它们来自连续两天的同一 `build/xs/rtl/rtl`
设计族，但没有保存输入 SV/FIR 的统一内容 hash，也没有固定到完全相同的 Wolvrix binary
commit，因此本文报告的是现有产物诊断，不声称严格 controlled A/B。

当前 `scripts/wolvrix_xs_grhsim.py` 默认值已经变成 `split_oversize_compute_nodes=False` 和
`sched_batch_target_count=256`。复现实验时必须显式设置上述原参数，不能依赖当前默认值。

### 不可混入主对照的产物

`gsim.precoarsen-graph.v1` 是 analysis-only 依赖投影，非 source node 被投影成 `kAssign`，
不包含完整状态、memory、effect 和 external 语义，并强制禁止 emitter。NO00001 的 28,863
compute supernodes 只能用于 GSim pre-coarsen 结构分析，不能当作本次 executable JSON 结果。

run16/run17 修改了参数：run16 关闭 final 108-op split，内部 coarsen 上限变成 3,456；run17
又把 emitter target count 从 64 改为 256。它们只用于后文定位编译长尾，不进入原参数主表。

## 输入流水线为什么不同

direct SV 路线为：

```text
read_sv
  -> xmr-resolve
  -> memory-read-retime / multidriven-guard / blackbox-guard
  -> latch-transparent-read / hier-flatten / comb-lane-pack
  -> comb-loop-elim / simplify x2 / memory-init-check
  -> reg-to-mem
  -> activity-schedule
```

executable JSON 路线为：

```text
GSim PreCoarsen Node/ExpTree
  -> executable GRH exporter
  -> read_json_file
  -> activity-schedule
```

导入分支明确跳过全部 pre-schedule normalization 和 `reg-to-mem`。因此“调度器参数相同”
不等于“调度器输入等价”：direct 路线消费的是 Wolvrix 已规范化、flatten、simplify 并重新
识别 memory 后的图；JSON 路线消费的是 GSim 优化后语义的逐 node/ExpTree 显式翻译。

GSim exporter 为保持可执行语义还会显式生成 node assignment、宽度/符号 coercion、packed
array element coercion、invalid/empty assignment 的 zero driver，以及 GSim 已消除 memory
writer 时的对应省略。这些结构在 direct SV 的规范化图中没有一一对应关系。

### Pre-schedule operation census

对 direct 的 `pre_reg_to_mem.json`（已完成上述 normalization、尚未执行 `reg-to-mem`）和
run14 GSim executable JSON 做逐 operation kind census：

| operation / value | direct pre-reg-to-mem | GSim executable JSON | GSim / direct |
| --- | ---: | ---: | ---: |
| values | 4,677,017 | 7,597,096 | 1.62x |
| operations | 5,268,574 | 7,908,902 | 1.50x |
| `kAssign` | 220,168 | 2,939,224 | 13.35x |
| `kMux` | 781,521 | 1,336,782 | 1.71x |
| `kSliceStatic` | 215,530 | 912,996 | 4.24x |
| `kMul` | 71 | 67,791 | 954.80x |
| `kRegister` / read / write | 286,014 / 286,014 / 286,013 | 149,436 / 149,436 / 149,436 | about 0.52x |
| `kMemory` / read / write | 832 / 1,939 / 4,116 | 2,274 / 3,394 / 3,476 | different shape |
| `kLatch` / read / write | 402 / 402 / 402 | 0 / 0 / 0 | removed |
| `kDpicImport` / call | 34 / 6,527 | 32 / 114 | calls 0.017x |

这不是同 stage 的 IR diff，不能把每一项差异都归因给 exporter：direct 已经过 Wolvrix
normalization，GSim 则已走自己的 PreCoarsen 优化。不过它准确描述了两条实际流水线交出的
图形。尤其是 293 万个 `kAssign`、91 万个 static slice 和 6.8 万个 multiply，会直接进入
后续 source clone、调度和 C++ expression emission。

GSim artifact 还显式使用 `xiangshan-gsim-coremark-stub` profile，external instances/calls 为
111/114；direct SV 的 6,527 个 DPI calls 来自另一套 native/DPI 表示。DPI 数量差异既是图
颗粒度差异，也提醒当前比较不能被解释为完整 external 行为等价证明。

## GRH 与 schedule 结构对比

主表使用 NO00024 修复前的 direct fresh 与 GSim run14。两边都保留旧版“单个 oversized
guard bucket 不切分”的行为，因此 commit shape 是同一实现口径；后续再单列 run15 修复结果。

| 指标 | direct SV | GSim executable JSON | 差异 |
| --- | ---: | ---: | ---: |
| scheduler input eligible ops | 4,944,502 | 7,757,160 | +56.9% |
| input topo edges | 9,980,269 | 12,832,384 | +28.6% |
| source clones | 2,045,861 | 2,662,209 | +30.1% |
| post-clone eligible ops | 6,990,363 | 10,419,369 | +49.1% |
| post-clone graph values | 6,833,009 | 10,259,305 | +50.1% |
| post-clone topo edges | 10,150,909 | 12,957,530 | +27.6% |
| compute nodes | 1,092,530 | 861,970 | -21.1% |
| initial compute clusters | 398,569 | 392,968 | -1.4% |
| compute supernodes | 63,241 | 112,840 | +78.4% |
| compute ops max / p99 | 108 / 108 | 108 / 108 | same cap |
| commit sink ops | 218,994 | 152,912 | -30.2% |
| commit event keys | 450 | 6 | -98.7% |
| commit supernodes | 485 | 7 | -98.6% |
| commit ops max | 42,937 | 111,852 | +160.5% |
| final supernodes | 63,726 | 112,847 | +77.1% |
| final DAG edges | 528,622 | 636,801 | +20.5% |
| boundary values | 1,000,463 | 690,268 | -31.0% |
| boundary activation edges | 1,983,923 | 1,606,402 | -19.0% |
| state-read activation edges | 84,972 | 63,578 | -25.2% |
| memory-read activation edges | 47,830 | 921 | -98.1% |
| constant activation edges | 45,686 | 74,554 | +63.2% |

几个指标组合起来比单看 op 数更有解释力：

- GSim post-clone compute ops 为 10,056,416，direct 为 5,625,117，接近 1.79 倍；initial
  cluster 数却几乎相同。这表示 GSim compute cluster 平均承载更多显式 ops。
- 两边 final compute p99 都被 108 cap 固定，但 GSim 因总 compute ops 更多而需要 112,840
  个 compute supernodes；direct 只需 63,241 个。
- schedule 的 boundary kind 日志中，GSim 最主要的 definition 是 `kAssign:1,936,093`；
  direct 的 `kAssign` 只有 332,092，主导项改为 `kAnd:644,905`。这与 exporter 的逐 node
  assignment/coercion 形态一致。
- direct 的 450 个 event keys 保留了较细的 clock/guard 身份；GSim 的 6 个 keys 把大量
  register writes 聚在同一 event bucket。run14 的 111,852-op commit node 是这种结构加上旧
  bucket 不切分 bug 的共同结果，不是 `max_op_in_commit_supernode=4096` 参数本身不同。
- direct 的 commit max 也达到 42,937，说明旧 bug 并非 GSim 专属；但 GSim event keys 从
  450 收敛到 6 后，单 bucket 集中度进一步放大。NO00024 修复后，同一 GSim 图变为 43 个
  commit supernodes、max 4,096、final DAG 639,803 edges。direct 尚无同一修复版本的 fresh
  重跑，所以不能把 run15 的 43 与 direct 的 485 当成严格 post-fix A/B。

## 生成 C++ 对比

run15 已包含 NO00024 的 commit bucket 修复：

| 指标 | direct SV | GSim run15 | GSim 相对 direct |
| --- | ---: | ---: | ---: |
| schedule TUs | 117 | 106 | -9.4% |
| state-init TUs | 33 | 33 | same |
| all C++ files | 152 | 141 | -7.2% |
| C++ bytes | 1,378,578,889 | 1,320,746,311 | -4.2% |
| C++ lines | 13,904,899 | 10,681,780 | -23.2% |
| largest TU | 36,041,985 B | 33,983,694 B | -5.7% |
| bytes per line | 99.14 | 123.64 | +24.7% |
| schedule `static_cast` count | 9,069,765 | 14,515,110 | +60.0% |
| `static_cast` per line | 0.652 | 1.359 | +108.4% |

所以 JSON 路线不是“emit 出更多总字节”。它生成的行更少但更长，cast/coercion 表达式明显
更密。原始 GSim node 的宽度和符号转换被保留到 GRH，再逐项展开进 C++；这会增加 clang
前端 AST 和 `-O3` 优化负担，而单纯的文件字节数和行数无法反映这部分成本。

run14 修复前确实有一个独立的代码形状问题：最大 commit TU 为 99,233,042 bytes。
NO00024 将 commit nodes 从 7 个切成 43 个后，最大 commit TU 降到 4,920,546 bytes；run15
剩余最大文件均为 compute schedule TU。

## 30 分钟编译现象

direct fresh 模型从 emit 完成到 archive/emu 生成的 artifact 时间跨度约 5 分 25 秒。GSim
run15 使用 `clang++ -O3`、`VM_BUILD_JOBS=32`，30 分钟后完成 128/141 个 model objects，
剩余 13 个全部是 16.0--23.6 MB compute TUs；日志没有 compiler error、fatal error 或 OOM。

该对比的并行度和 binary 版本没有完全控制，不能把 5 分 25 秒与 30 分钟直接当成严格
speedup 数值。但即使考虑 direct 可能使用更多并行 job，以下证据仍排除了“总源码更大”这一
解释：GSim 的 C++ bytes、lines、TU 数和最大 TU 都更小，而编译仍出现显著长尾。

run16/run17 进一步验证长尾性质：

| 实验 | compute SN | schedule TUs | C++ bytes | 最大 TU | 30 分钟结果 |
| --- | ---: | ---: | ---: | ---: | --- |
| run15, original 108 split / target 64 | 112,840 | 106 | 1.321 GB | 34.0 MB | 剩 13/141 |
| run16, coarsen 3,456 / target 64 | 31,048 | 103 | 1.132 GB | 21.4 MB | 剩 22/138 |
| run17, same schedule / target 256 | 31,048 | 335 | 1.134 GB | 11.4 MB | 剩 6/366 |

run17 的 schedule stats 与 run16 逐字段相同，只改变 emitter 分批；30 分钟后未完成的 6 个
TU 已缩小到 2.15--4.97 MB，但仍在编译。它们只有约 9k--60k 行，却分别含约 22k--56k
个 `static_cast`，再次说明真正的长尾与表达式复杂度相关，而不是文件大小阈值本身。

## 诊断判断与下一步

当前证据支持以下优先级：

1. **先修输入图冗余。** 在 executable JSON import 后增加语义安全的 normalization，至少
   对 `kAssign` chain、冗余 width/sign coercion、常量转换和重复 expression 做 census 与
   定向消除；不能直接照搬 direct SV 全部 pass，因为 JSON 已携带 GSim 优化后的 state、
   memory、ordered external-call 契约。
2. **单独审计 event identity。** 6 对 450 个 event keys 是结构性差异。需要区分“确实共享
   clock/guard”与“exporter 丢失 identity 后被错误合并”，并检查 register-write guard/event
   的 provenance；仅依赖 commit cap 会隐藏结构问题而不修复它。
3. **给 emitter/编译器增加复杂度指标。** 除 bytes/lines 外，记录每 TU 的 op kinds、cast
   数、最大表达式深度、wide operation 数和 clang wall/RSS；用 run17 剩余 6 个 TU 作为
   首批 ROI。
4. **最后再调 TU batching。** target 64 -> 256 已将未完成 TU 从 22 降到 6，但不是根治。
   在表达式简化之前继续机械切小，会增加调度函数和 build bookkeeping，且不能保证消除
   单个复杂 supernode/表达式的优化长尾。

最终 gate 应在同一 Wolvrix/gsim commit、同一 SimTop 输入 hash、同一 `-j`、同一 clang 和
同一显式参数下重新跑 direct SV 与 executable JSON，并同时保存：pre-schedule operation
histogram、activity stats、per-TU code complexity 和 per-TU compile time。本文的数据已经足以
确定优化方向，但还不足以给出严格的编译倍数。

## 可复核命令

```bash
# 两条原参数路线的 scheduler 配置与关键阶段
rg -n 'activity-schedule max_op|build_op_data done|source_clone_refreeze done|timing detail' \
  build/logs/xs_perf/grhsim_retest_20260713/fresh_read_sv_emit.log \
  ptmp/gsim_full_exec_20260714/run14/logs/xs_gsim_executable_grh_import_run14_import_fresh.log

# 主 schedule stats
jq . build/xs_perf/grhsim_retest_20260713/grhsim/model/activity_schedule_supernode_stats.json
jq . ptmp/gsim_full_exec_20260714/run14/grhsim_emit/activity_schedule_supernode_stats.json

# NO00024 commit bucket 修复后的 GSim stats
jq . ptmp/gsim_full_exec_20260714/run15_schedule_commit_cap/activity_schedule_supernode_stats.json

# C++ 文件数、字节数和最大文件
find <model-dir> -maxdepth 1 -type f -name '*.cpp' -printf '%f %s\n' | \
  awk '{n++; b+=$2; if($2>m){m=$2; f=$1}} END{print n,b,m,f}'

# 表达式密度近似
rg -o 'static_cast' <model-dir>/grhsim_SimTop_sched_*.cpp | wc -l
```
