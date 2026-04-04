# XiangShan RepCut 性能回退成因分析（2026-03-24）

## 范围

本文分析以下两次 XiangShan repcut emu 运行的性能差异，并回答“当前回退是否主要由超边权重不合理导致”：

- [build/logs/xs-repcut/xs_verilator_repcut_20260324_194327.log](/workspace/wolvrix-playground/build/logs/xs-repcut/xs_verilator_repcut_20260324_194327.log)
- [build/logs/xs-repcut/xs_verilator_repcut_20260324_210610.log](/workspace/wolvrix-playground/build/logs/xs-repcut/xs_verilator_repcut_20260324_210610.log)
- [build/logs/xs-repcut/xs_verilator_repcut_20260324_194327.timing.jsonl](/workspace/wolvrix-playground/build/logs/xs-repcut/xs_verilator_repcut_20260324_194327.timing.jsonl)
- [build/logs/xs-repcut/xs_verilator_repcut_20260324_210610.timing.jsonl](/workspace/wolvrix-playground/build/logs/xs-repcut/xs_verilator_repcut_20260324_210610.timing.jsonl)

辅助材料：

- [docs/draft/xs-repcut-timing-compare-20260324.md](/workspace/wolvrix-playground/docs/draft/xs-repcut-timing-compare-20260324.md)
- [build/xs/repcut/work/SimTop_logic_part_repcut_k128.partition_features.jsonl](/workspace/wolvrix-playground/build/xs/repcut/work/SimTop_logic_part_repcut_k128.partition_features.jsonl)

## 结论摘要

结论分两层：

1. 对这一次 `20260324_194327 -> 20260324_210610` 的突发性性能回退，主因不是超边权重不合理。
2. 但从长期看，当前 repcut 的代价模型仍然和真实 runtime 成本不一致，确实需要继续修正。

更具体地说：

- 本次 step 平均耗时从 `3601.299 us` 回退到 `5887.360 us`，增幅 `63.48%`。
- 最大增量来自 `debug_scatter`，其次是 `part_eval` 和 `writeback`。
- `debug_part` 的输入装载路径不受 hypergraph partition 直接支配，但它本身就增加了 `+1174.927 us/step`，这已经足以说明“本次回退不能主要归因于超边权重”。
- 非 debug 分区的回退也主要集中在 `scatter/gather`，不是集中在纯 `eval()`。
- 当前分区的 `estimated_node_weight_sum / hyper_partition_weight` 被切得很平，但 runtime 的 `scatter/gather` 与 `cross_in/cross_out word` 强相关，说明当前 partition 目标函数仍然没有把真实通信成本建模完整。

因此，正确判断应当是：

- 这次回退的直接触发项，更像是运行时 wrapper / 数据搬运 / 写回路径的变化。
- 超边权重不合理，是当前总体性能上限和负载不均的结构性问题，但不是这次突然回退的第一责任项。

## 本次回退的直接证据

两次运行对应的是两次不同时间编译出来的 `emu`：

- `194327` 日志中 `emu compiled at Mar 24 2026, 19:42:28`
- `210610` 日志中 `emu compiled at Mar 24 2026, 21:02:47`

从 timing 看，回退特征非常明确：

| phase | before avg_us | after avg_us | delta avg_us |
| --- | ---: | ---: | ---: |
| `debug_scatter` | `788.300` | `1954.372` | `+1166.072` |
| `debug_eval` | `6.126` | `14.219` | `+8.093` |
| `debug_publish` | `0.493` | `1.257` | `+0.764` |
| `part_eval` | `1966.821` | `2616.635` | `+649.814` |
| `writeback` | `838.666` | `1299.327` | `+460.661` |

这组数据说明：

- `debug_scatter` 是最大单项回退来源，占总回退的一半以上。
- `debug_part->eval()` 本身只增加了约 `8 us/step`，不是主因。
- 非 debug worker 之后的统一 `writeback` 也明显变慢，说明慢的不只是局部 `eval()`，而是跨分区数据交换路径。

再看 non-debug part 的局部画像：

- 128 个 non-debug part 中，`85` 个回退，`43` 个改善。
- 回退分区中，主导增量来源为：
  - `scatter`: `58`
  - `gather`: `17`
  - `eval`: `10`

这意味着本次退化主要不是“算得更慢了”，而是“搬得更慢了”。

最典型的异常是：

- `part_23`: `298.713 us -> 2141.922 us`
  - `scatter +95.721 us`
  - `eval +58.392 us`
  - `gather +1689.096 us`

而最大回退来源 `debug_part` 根本不是 repcut 被切出来的普通 worker part，它的 `scatter` 暴涨更加说明本次回退首先发生在运行时数据装载/发布路径。

## 当前 repcut 权重到底怎么计算

### 1. 节点权重

`calculateNodeWeight()` 按 op kind 和位宽给 phase-A node 赋静态 compute 权重，见：

- [repcut.cpp](/workspace/wolvrix-playground/wolvrix/lib/transform/repcut.cpp#L1809)

典型规则包括：

- `add/sub = 2`
- `mul = 4`
- `div/mod = 6`
- 位运算按结果位宽折算成 64-bit word 数
- `mux` 按结果位宽乘以系数
- `memory/register write port` 按写数据/使能宽度折算

### 2. piece 权重

`calculatePieceWeight()` 会把一个 piece 内部可达 cone 的节点权重累加，得到该 piece 的静态 compute weight，见：

- [repcut.cpp](/workspace/wolvrix-playground/wolvrix/lib/transform/repcut.cpp#L1928)

### 3. duplication hyperedge 权重

当前代码已经不是简单“所有超边都用 pieceWeight”。

在 `buildHyperGraph()` 里：

- duplication edge 权重来自 `calculatePieceDuplicationWeight()`，近似表示该 piece 若被多个 ASC 共享时的复制代价
- 对应代码见：
  - [repcut.cpp](/workspace/wolvrix-playground/wolvrix/lib/transform/repcut.cpp#L2423)
  - [repcut.cpp](/workspace/wolvrix-playground/wolvrix/lib/transform/repcut.cpp#L2502)

### 4. communication hyperedge 权重

当前代码还额外建立了 `Communication` 类型 hyperedge：

- 遍历 piece 内 result value
- 找到跨 piece 的 user
- 以跨分区 value 的 64-bit word 数累加为超边权重

对应代码见：

- [repcut.cpp](/workspace/wolvrix-playground/wolvrix/lib/transform/repcut.cpp#L2520)
- [repcut.cpp](/workspace/wolvrix-playground/wolvrix/lib/transform/repcut.cpp#L2595)

因此，严格说，当前实现已经开始建模跨分区通信成本了，不是“完全没有建模”。

但要注意：

- `partition_features.jsonl` 里的 `hyper_partition_weight` 不是“超边总成本”
- 它仍然是 partition/node 侧的静态 compute weight 指标
- 真正的 communication edge 权重并没有直接以“每个 part 一个汇总字段”的形式导出出来

## 为什么说这次回退不是超边权重主导

### 1. `debug_part` 的退化无法由 hypergraph 切分解释

当前 step 流程里，`debug_part` 是主线程先 scatter、再 `eval()`、再 publish，然后才启动 non-debug worker：

- [verilator_repcut_package.cpp](/workspace/wolvrix-playground/wolvrix/lib/emit/verilator_repcut_package.cpp#L1658)

也就是说：

- `debug_scatter` 变慢，不是“某个 worker 分区被切坏了”
- 它首先是 wrapper 生成出来的输入装载代码、数据布局、cache 行为或复制量变化的问题

而这次回退里，`debug_scatter` 恰恰是最大的全局增量来源。

### 2. 回退主导项是 scatter/gather/writeback，不是 eval

如果主要问题是 hypergraph 切分把“算子算力负载”切坏了，最直接的信号应当更偏向：

- `eval()` 明显恶化
- 重分区后 worker 之间纯计算负载极不均衡

但当前日志里：

- 大部分回退由 `scatter/gather` 主导
- `part_eval` 是总 phase 时间，内部还包含 worker 等待慢分区的影响
- 真正 per-part 的 `eval_avg_us` 不是主导回退项

这说明瓶颈更靠近数据交换，而不是本地组合逻辑执行。

### 3. 这是一次突发性 build-to-build 回退，不像单纯 partition quality 问题

超边权重不合理通常体现为：

- 长期稳定的分区质量差
- 某些 part 一直通信重、一直不均衡
- 同一套 emit/runtime 代码下，性能上限上不去

但这次是：

- 同一 workload
- 同一天两次重新构建出来的 `emu`
- 性能突然从 `3.6 ms/step` 恶化到 `5.9 ms/step`

这种画像更像是：

- 运行时 wrapper 生成代码发生变化
- 数据交换/写回路径的访问模式变差
- 或同步等待被放大

而不是“仅仅因为超边权重本来就不合理”。

## 但为什么仍然说当前权重模型不够好

这部分是结构性问题，与“本次直接回退原因”要区分开。

### 1. compute weight 被切得很平，但 runtime 差异很大

当前 `k=128` 的静态特征分布如下：

| 指标 | min | median | mean | max |
| --- | ---: | ---: | ---: | ---: |
| `estimated_node_weight_sum` | `87989` | `89366` | `89993.4` | `173418` |
| `op_count` | `28285` | `52439` | `53119.8` | `100282` |
| `cross_in_word_count` | `97` | `4028` | `4575.6` | `36641` |
| `cross_out_word_count` | `14` | `1711` | `2082.2` | `22488` |

可以看到：

- 大多数分区的静态 compute weight 已经被压得很平
- 但 `cross_in/cross_out` 的跨度仍然非常大

这就意味着：

- 仅靠 compute balance 不能解释 runtime
- 真正影响散发/回收成本的边界数据量仍然不平衡

### 2. runtime 与 boundary word 强相关，与 compute weight 弱相关

把当前 `partition_features.jsonl` 和 `210610.timing.jsonl` 对齐后，得到以下相关性：

| 静态特征 -> 运行时指标 | Pearson | 线性回归 R² |
| --- | ---: | ---: |
| `estimated_node_weight_sum -> eval_avg_us` | `-0.0696` | `0.0048` |
| `estimated_node_weight_sum -> avg_us` | `-0.1079` | `0.0116` |
| `hyper_partition_weight -> avg_us` | `-0.1079` | `0.0116` |
| `cross_in_word_count -> scatter_avg_us` | `0.8150` | `0.6642` |
| `cross_out_word_count -> gather_avg_us` | `0.9390` | `0.8817` |

这组数据非常关键：

- 当前导出的 compute weight 几乎不能解释 runtime
- `cross_in_word_count` 对 `scatter` 有强解释力
- `cross_out_word_count` 对 `gather` 的解释力更强

因此，当前代价模型即便已经加入 communication hyperedge，也仍然没有把 runtime 热点完全表达出来。

### 3. 当前 communication hyperedge 仍然缺少几类真实成本

当前 communication hyperedge 权重，本质上只是：

- “跨 piece 的 value 宽度总和”

而真实 runtime 成本还包括：

- snapshot slot 数量
- writeback slot 数量
- 同一 value 被多少个 part 读取/写回
- debug_part 的中心化输入装载成本
- writeback 汇总成本
- 实际生成代码的访问顺序和 cache locality
- worker 之间的尾部不均衡和 barrier wait

这些成本并没有完整进入 partition 目标函数。

## 当前热路径是否引入了 hash/map

本次静态检查结果是：

- `wolvrix/lib/emit/verilator_repcut_package.cpp` 在“代码生成阶段”使用了 `unordered_map` 组织元数据
- 但对生成出来的运行时代码目录 `build/xs/repcut/partitioned-emu` 搜索，没有发现 hot path 使用 `map/unordered_map/hash` 做动态查表

因此，当前运行时热路径更像是：

- 生成后的静态 scatter / eval / gather / writeback 代码

而不是：

- 每 step 通过 hash map 做端口或信号映射

这意味着本次退化更可能来自：

- 拷贝量变化
- 内存布局变化
- 访问顺序变化
- 同步等待变化

而不是动态容器查表开销。

## 修改建议

### 一、先处理“本次直接回退”

优先级最高的不是先改超边权重，而是先定位这次 build-to-build 回退的直接触发项。

建议马上补的静态/运行时导出：

1. 导出 `debug_part` 的输入 word 数、输出 word 数、scatter 赋值条目数。
2. 导出全局 writeback 的 slot 数、word 数、赋值条目数。
3. 对每个 `part_*` 导出本地 `scatter/gather` 的条目数和 word 数。
4. 对 worker 额外统计“忙碌时间”和“等待 barrier/收尾时间”。

这样可以直接回答：

- `debug_scatter` 为什么突然翻倍
- `writeback` 为什么明显变慢
- `part_23` 这类分区为什么会出现 gather 爆炸

### 二、再修正 partition cost model

当前更合理的方向不是先上机器学习，而是先做可解释的线性代价模型。

建议将分区代价近似为：

`cost(part) = a * local_eval_weight + b * scatter_in_words + c * gather_out_words + d * fanout_penalty + e * writeback_penalty`

其中：

- `local_eval_weight` 来自当前 node/piece compute weight
- `scatter_in_words` / `gather_out_words` 来自静态边界数据量
- `fanout_penalty` 用于惩罚高复制/高共享片段
- `writeback_penalty` 用于惩罚会放大全局写回成本的边界

参数 `a/b/c/d/e` 可以先通过现有静态特征和 runtime timing 做线性回归得到，而不需要先上 ML。

### 三、把优化目标从“总 cut”扩展到“并行 step 尾部时间”

当前真正影响吞吐的是每个 step 的尾部：

- 最慢 worker 的本地 scatter/eval/gather
- 全局 writeback
- debug_part 前置装载

因此 partition/refinement 的目标不应只看：

- 总 compute weight 是否平衡
- 总 communication cut 是否小

还应显式压制：

- `max per-part runtime`
- `max per-thread assigned runtime`
- `debug/writeback hub` 的集中热点

换句话说，需要从“cut quality”转到“step makespan quality”。

### 四、建议的实施顺序

建议按下面顺序推进：

1. 保持当前分区数不变，先把 `debug_scatter` / `writeback` / 每 part 本地搬运量导出齐全。
2. 用现有 timing 数据做一次线性拟合，先验证 `scatter/gather` 的主要解释变量。
3. 把 `cross_in/out word`、fanout、writeback hub cost 纳入超图或后处理 refinement 代价。
4. 再做一次 `k=128` 的重分区验证，观察 `max per-part time` 和 `step avg_us` 是否同时下降。

在这之前，直接把锅扣给“超边权重不合理”是不准确的。

## 最终判断

最终判断如下：

- 对这一次 `20260324_194327 -> 20260324_210610` 的性能回退，主因不是超边权重不合理。
- 更直接的原因是运行时数据交换路径变重，尤其是 `debug_scatter`、全局 `writeback`，以及部分分区的本地 `scatter/gather`。
- 但从更长周期看，当前 partition 目标函数与真实 runtime 成本确实仍然不匹配，特别是没有把 `scatter/gather/writeback/debug hub/barrier tail` 这些成本完整建模进去。

所以更准确的表述应当是：

- “本次回退不是主要由超边权重引起的。”
- “但如果想把 repcut 的长期性能做好，超边/分区代价模型确实还要继续修。”
