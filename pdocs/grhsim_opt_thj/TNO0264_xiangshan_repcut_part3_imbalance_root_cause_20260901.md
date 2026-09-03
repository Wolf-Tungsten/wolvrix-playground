# TNO0264: XiangShan RepCut part3 imbalance root cause

日期：2026-09-01

状态：`DIAGNOSIS HIGH CONFIDENCE; OPTIMIZATION A/B NOT RUN`。

## 1. 结论

本轮承接 [TNO0245](./TNO0245_xiangshan_repcut_partition_count_sweep_protocol_20260822.md)、
[TNO0246](./TNO0246_xiangshan_repcut_partition_count_sweep_results_20260822.md) 的 `k=32`
静态切分，以及 [TNO0250](./TNO0250_repcut_dpi_fix_v7_build_and_gate_20260825.md)、
[TNO0251](./TNO0251_repcut_v7_thread_scaling_results_and_gate_boundary_20260825.md) 的 v7
功能与 runtime snapshot，对 `part_3` 热点做只读归因。

结论需要区分“求解器调参”和“求解目标修正”：

1. **不应优先调 Mt-KaHyPar preset、seed、epsilon 或现有权重中的几个系数。**
   `k=32` 的 `hyper_partition_weight` 已满足约 `1.5%` 不平衡约束，求解器基本完成了
   当前目标；问题首先是目标与最终执行负载不一致。
2. **应优先修正生成 `hyper_partition_weight` 的负载口径。** 当前 HGR vertex load
   没有覆盖 shared/residual piece 的完整计算成本，也不能表达一个 shared piece 被某个
   partition 实际物化后的 assignment-dependent closure cost。
3. **修正权重只能消除 giant ASC 之外的可避免附加载荷，不能根治扩展性。** `aid=4`
   本身包含 `464,599` 个组合 op 和 `26,848` 个 sink，作为一个不可拆 HGR node 时就有
   至少 `491,447` 个原始 op；要突破这个硬下限，最终仍需改变 memory/state 边界语义或
   对 giant ASC 做经过功能证明的再切分。

因此近期优先级是：先建立 exact closure cost 观测，再做 closure-aware weight、
overweight-ASC isolate 和 max-load-aware post-refine A/B；memory 边界的语义重构作为更高风险、
但长期不可替代的主线。本文没有修改 Wolvrix 代码、默认参数或分区结果。

## 2. 证据身份与范围

本轮复用 TNO0246 的 deterministic `k=32` 产物：

| 项目 | 身份 |
| --- | --- |
| HGR | SHA-256 `830ca5c22823222f3204c132fd2f40b87a4a3bfbb8d2332f7573c0edcdb371c1` |
| `.part32` | SHA-256 `6857d47e3f36eaa3790bfdcdf2c128249fa3ef11866df19730419ec88c45e07e` |
| `k32.stats.json` | SHA-256 `ba95902f0601e10f828e931f878299fb76d845434bd48f344f06059475fde9b1` |
| `k32.stderr.log` | SHA-256 `766b199ab900319782b5aded26e6826a7aa0912cb0e46ee7d84bc4f9fc432400` |
| v7 N=1/C=10000 timing | SHA-256 `71e31fa2e395254b1f4056c6f410621d5b86659a9ddbbcaafd71cfd8ea46fff3` |

本轮没有重新运行 Mt-KaHyPar，没有生成新 RTL/ELF，也没有新增正式 C=30000 性能样本。
runtime 数据仍是 TNO0251 已限定证据边界的 C=10000 accepted canary snapshot；它可以用于
解释 part 内部热点，不能提升为正式跨 backend 性能 headline。

## 3. 三种 weight 不是同一个指标

### 3.1 `hyper_partition_weight`

这是 Mt-KaHyPar 实际接收并约束的 HGR vertex weight 之和。phase C 为每个 ASC 建一个
hypernode，phase E 再按 `.part32` 汇总每个 partition 的 vertex weight。它是“求解器
平衡了什么”的指标，不是最终 graph op 数，也不是实测时间。

### 3.2 `estimated_node_weight_sum`

分区归属已经展开为每个 part 的 `partitionOps` 后，重建 `SimTop_repcut_partN` 之前，
代码对该 part 实际拥有的 Phase-A 原始 op 再执行一次 `calculateNodeWeight()` 并求和：

```text
estimated_node_weight_sum[p]
  = sum(calculateNodeWeight(op) for op in partitionOps[p])
```

它包含 shared logic 实际进入该 part 后的 op membership，但仍是按 op kind、位宽和 fanout
构造的静态估计，不是微秒。统计点与权重实现见
[`repcut.cpp`](../../wolvrix/lib/transform/repcut.cpp)。

### 3.3 final graph ops 与 runtime

`partition_graph_stats.ops` 是重建后 graph 的实际 op 数，已经混入边界 bundle、slice、
adapter 和 propagation 结果。`eval_avg_us` 则来自 Verilator 运行时插桩。两者都不能与
`hyper_partition_weight` 互换。

## 4. `part_3` 的失配规模

| 层次 | `part_3` | 全部 32 part 均值 | `part_3 / mean` |
| --- | ---: | ---: | ---: |
| `hyper_partition_weight` | 228,155 | 224,825.094 | 1.015x |
| 重建前 `estimated_node_weight_sum` | 1,785,172 | 429,237.688 | 4.159x |
| 重建前 `op_count` | 823,809 | 184,045.094 | 4.476x |
| 重建后 final graph ops | 912,331 | 194,609.313 | 4.688x |
| N=1/C=10000 `eval_avg_us` | 505.359 us | 76.910 us | 6.571x |

求解器看到的最大 weight 只比均值高 `1.481%`；按展开后静态成本重新统计，最大值已经比
均值高 `315.894%`。N=1 中 `part_3` 的 eval 是第二名 `part_7` 的 `4.100x`，并占 32 个
part eval 求和的 `20.534%`。这说明 `hyper_partition_weight` 的平衡不能预测当前 emitted
model 的 critical part。

`part_3` 的 `estimated_node_weight_sum / hyper_partition_weight = 7.824x`。这个比值不是
运行时间倍率，但直接暴露了 solver load 与 realized static load 的口径错位。

把 32 个 part 的同一份静态 feature 与上述 accepted N=1 timing 按 `part_name` 对齐，
对 `eval_avg_us` 计算 Pearson 相关系数，得到：

| 静态指标 | 全部 32 part | 排除 `part_3` |
| --- | ---: | ---: |
| `hyper_partition_weight` | 0.202 | -0.041 |
| `estimated_node_weight_sum` | 0.953 | 0.722 |
| `op_count` | 0.958 | 0.778 |
| `operand_word_count` | 0.983 | 0.833 |
| `result_word_count` | 0.957 | 0.766 |

这不是正式预测模型，但说明弱相关并不只由 `part_3` 一个离群点造成：移除它以后，现有
solver weight 与 eval 已基本无正相关，而展开后的 op/word 指标仍保留明显相关性。

## 5. 为什么现有 HGR weight 会漏载荷

phase B 将 `329,692` 个 sink 先按 register/latch/memory symbol 和 cone 中触及的 memory
关系做 DSU 合并，再为每个 ASC 收集完整 predecessor combinational cone。phase C 的建模
随后采用：

1. 一个 ASC 对应一个不可拆 HGR vertex；
2. ASC 编号对应的首批 piece 进入 `hg.nodeWeights`；
3. shared/residual piece 变成 hyperedge；
4. hyperedge weight 使用压缩后的 signal、wide-word、fanout 和 state-boundary communication
   proxy，而不是该 piece 的完整 `pieceWeight`；
5. phase E 按最终 ASC 归属物化完整 op closure。

本次全图 `total_piece_weight=13,682,460`，而 HGR vertex balance weight 总和只有
`7,194,403`，只覆盖前者的 `52.581%`。其余 piece 仍可能通过 communication proxy 影响
cut/KM1，但其计算成本没有作为 per-part vertex load 进入平衡约束。

这也是为什么不能只把现有 `calculateNodeWeight()` 的 Mul/Div/width/fanout 系数调得更准：
主要误差不是单个 op 的系数偏一点，而是约 `47.419%` 的 piece compute weight 没有进入
vertex balance，且 shared closure 的每-part 成本依赖最终 assignment。

## 6. giant ASC 给出的硬下限

phase-B 日志中最大 ASC 为：

```text
aid=4 comb_ops=464599 sinks=26848
```

HGR 中 `aid=4` 的 vertex weight 只有 `22,577`，`.part32` 第 5 行把它分配给 `part_3`。
由于当前算法不能在 ASC 内继续切分，`464,599 + 26,848 = 491,447` 个原始 op 构成当前
语义下的原子下限。它已经是重建前每 part 平均 `184,045` op 的 `2.670x`，因此单靠任何
fixed vertex reweight 都不可能把 `k=32` 做到 raw-op 均衡。

`part_3` 重建前共有 `823,809` op，减去该 giant ASC 后还剩至多 `332,362` 个其他
membership。把 giant ASC isolate 并改善其他 ASC 的装箱，理论上最多只能处理这一部分；
其中仍包含必要 shared/storage closure，所以 `332,362` 是可优化空间的绝对上界，不是
可兑现收益或 runtime 承诺。

## 7. RTL 性质与算法责任边界

两方面共同造成了热点，但责任不同：

| 因素 | 已有证据支持的判断 |
| --- | --- |
| RTL 结构 | XiangShan flatten graph 中存在大型 memory/array、高 fanout 以及跨层共享控制与观测逻辑；这是大 cone 和高复制成本的客观触发条件。 |
| `mem_cone_union` | 当前实现会把触及同一 memory 的多个 sink 与 memory write sink 传递合并，可能把多个局部锥放大为 giant ASC。 |
| ASC 原子化 | `aid=4` 一旦形成，seed、preset、epsilon 和增加 `k` 都不能在求解阶段拆开它。 |
| weight proxy | 求解器只平衡 HGR vertex proxy，shared/residual piece 的 realized compute load 没有完整进入约束；这是 `part_3` 又承载大量附加工作并仍显示“weight 平衡”的直接原因。 |

因此不能把问题简单归因于某一个 RTL module，也不能说 Mt-KaHyPar 没有把收到的目标优化好。
更准确的结论是：RTL 提供了困难拓扑，当前保守 memory closure、ASC 粒度和负载模型共同
将其放大；算法侧存在明确且应优先验证的改进空间。

## 8. 调优优先级

| 优先级 | 工作 | 目的与边界 |
| --- | --- | --- |
| P0 | 补 per-ASC full/exclusive/shared closure cost，以及每个候选 partition 的 exact unique realized cost | 先让模型误差可量化；不改语义和 partition。 |
| P1a | closure-aware fixed weight + overweight ASC isolate | 低风险止血，避免继续向 giant ASC 所在 part 填入明显的正边际成本；不能突破 `491,447` op 下限。 |
| P1b | 将 compute replication 与 communication cost 分开，并做 max-load-aware exact marginal post-refine | 这是主要权重算法修复；固定 vertex weight 无法完整表示 assignment-dependent shared closure。 |
| P2 | 在经过证明的 memory/state 边界拆分 giant ASC，例如 shared state ownership 或两阶段 write/commit | 唯一能突破 giant ASC 原子下限的方向，但功能风险和验证成本最高。 |

不能直接把每个 ASC 的 full cone 全量重复加到 fixed vertex weight：shared cone 会被多个 ASC
重复计数，`aid=4` 还可能大于普通 epsilon 允许的 block capacity。第一轮 A/B 必须显式处理
overweight singleton，并将“最大 part load”和“总复制工作”作为两个目标，而不是塞入一个
无法解释的混合系数。

## 9. 下一轮验证指标

### 9.1 最小可执行 A/B

当前 `RepcutOptions` 和 Python binding 没有独立 weight mode，balance 公式直接编译在
`repcut.cpp` 中。第一轮实现应暴露离散的 `baseline/candidate` mode，并保持 baseline binary、
输入、`k=32`、epsilon、preset 和 seed 冻结，不用连续系数 sweep 混入多个变量。

静态筛选可以直接复用：

```text
build/repcut_partition_sweep_20260822/run_one.py
build/repcut_partition_sweep_20260822/summarize.py
```

现有 baseline 的一次 `k=32` transform-only wall 为 `6:36.92`，peak RSS 为约
`34.68 GiB`；它已经保存 stats、HGR、`.part32`、cut/KM1、复制与完整性 gate，不需要先做
全 K sweep。推荐执行漏斗为：

1. baseline/candidate 各跑一次同输入 `k=32` transform-only；
2. 静态指标胜出后只 emit/build candidate；
3. 先跑 C=100 功能门，再跑 C=10000 的 N=1 与 N=4；
4. 只有两档 runtime 都改善，才扩到 N=2/8、C=30000 和正式重复样本。

N=1 用于比较 `sum(part eval)`、`max(part eval)` 和 giant-ASC owner；N=4 还必须按当前
连续 part-to-worker 映射计算每个 worker 的 predicted load 与实际 barrier critical path，
避免单个 part 变小但 worker 分组仍然失衡。

### 9.2 判定指标

第一轮固定 `k=32` 和同一输入，只改变负载建模，至少记录：

- 输入覆盖：`sum(vertex_balance_weight) / sum(pieceWeight)`、最大 ASC full closure、
  overweight ASC 数量；
- 静态负载：每 part exact unique op weight、final ops、word count、最大值/均值和 P95/均值；
- 复制与通信：core replicated memberships、compute KM1、communication KM1、cross words 和
  boundary adapter ops；
- 预测有效性：新 cost 与 N=1 per-part `eval_avg_us` 的相关性、最大预测误差；
- runtime：N=1 的 `sum(eval)` 与 `max(part eval)`，以及 N=8 的 eval/update barrier critical
  path，避免只降低最大 part 却扩大总工作；
- 功能门：C=100/C=10000/C=30000 的端点签名、difftest 和 memory 同周期读写路径。

只有新权重同时降低 realized max load、没有不可接受地抬高总复制/通信，并通过功能门，才
进入 K/N sweep。不能再用 `hyper_partition_weight` 自身变得更平衡作为成功标准。

## 10. 证据限制

- 本轮只有 deterministic-quality、seed 0 的既有 `k=32` 切分，没有比较新权重或新 seed。
- `estimated_node_weight_sum` 仍是静态 heuristic，不是最终 Verilator 指令数或时间。
- `491,447` 是当前 ASC 原子粒度下的 op 下限，不证明其中所有逻辑都可安全拆开。
- C=10000 per-part timing 是 accepted canary snapshot，不是正式 C=30000 统计结果。
- 本文没有实施 A/B，不改变 TNO0246 与 TNO0251 的原始结果边界。

## 11. 持久证据

静态切分证据：

```text
build/repcut_partition_sweep_20260822/results/k32.stats.json
build/repcut_partition_sweep_20260822/logs/k32.stderr.log
build/repcut_partition_sweep_20260822/runs/k32/work/SimTop_repcut_k32.hgr
build/repcut_partition_sweep_20260822/runs/k32/work/SimTop_repcut_k32.hgr.part32
```

runtime 诊断证据：

```text
build/repcut_fix_20260825/logs/run/canary_v7_final2_ccd152/
  slot010_canary_partitioned_t1_c10000_s1_attempt01.timing.jsonl
```

实现入口：

```text
wolvrix/lib/transform/repcut.cpp
```

后续 weight protocol、实现、静态结果和 runtime 结果按目录规则分别新建 TNO，不向本文
回填成一篇跨阶段长记录。

## 12. 勘误：piece weight 覆盖率口径（2026-09-01）

第 5 节把 `1 - 7,194,403 / 13,682,460 = 47.419%` 直接表述为“没有进入 vertex
balance 的 piece compute weight”，这个说法过强。TNO0265/TNO0266 新增的 exact closure
instrumentation 将总量拆成：

- ASC 引用的 unique piece weight：`12,450,769`；
- 没有 ASC 引用的 piece weight：`1,231,690`；
- 一个 empty piece 的人工 weight：`1`。

同时 baseline vertex weight 还包含首批 piece 上的 communication uplift，不是纯 piece compute
之和。因此 `52.581%/47.419%` 只能表示“旧 HGR vertex balance 总量与全部 piece-weight 总量
的粗对比”，不能解释成 exact referenced-compute 覆盖率或遗漏率。第 5 节关于旧 solver load 与
realized closure load 失配的方向性结论不变；后续量化统一使用 TNO0265 定义的
`referenced_unique_weight`、exact partition load 与 compute KM1。
