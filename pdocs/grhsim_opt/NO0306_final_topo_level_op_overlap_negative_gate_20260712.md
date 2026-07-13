# NO0306 Final-topo level-op overlap negative gate

日期：2026-07-12

## 1. 实验对象

承接 [NO0305](./NO0305_final_topo_level_op_implementation_structure_gate_20260712.md)，从同一
pre-reg-to-mem checkpoint 生成两组 `level-op`：

| 产物 | decoded-write storage | ordered writes | 结构 |
| --- | --- | --- | --- |
| strict baseline | off | off | NO0286：`7,196,059` graph ops、`67,934` supernodes、`638,649` DAG edges |
| ordered candidate | on | on | NO0300：`7,204,108` graph ops、`63,726` supernodes、`528,622` DAG edges |

两组 final topo policy 均为 `level-op`。ordered 产物的 source clones `2,045,861`、eligible ops
`6,990,363`、compute/commit supernodes `63,241/485`，与 NO0300 完全一致，因此不存在 lowering 或
partition 配置漂移。

## 2. 可复用 overlap 工具

新增 `scripts/grhsim_compute_batch_overlap.py`，解析 generated compute C++ 中的
`// op _op_<id>` 注释，建立无歧义的 stable op-to-batch map，并报告：

- old/new coverage 与跨 batch 歧义数；
- 每个新 batch 的旧 batch 来源分布；
- dominant-source share、batch 位置相关性；
- 归一化 batch 位移均值、p50/p90、相邻 batch 覆盖率；
- 同一 old batch 的 op pair 在新布局中的共置率。

两组比较均有 `1,498,855` 个共同 op，old/new coverage 分别为 `72.288%/78.437%`，且两边
cross-batch ambiguous op 均为 `0`，比较集合完全一致。工具还修正了 NO0303 临时提取遗漏的末尾小
compute65；两版实际均为 66 个 compute batches，遗漏不影响 NO0303 的热点结论。

## 3. level-id 与 level-op 对比

| Metric | NO0286/NO0300 `level-id` | strict/ordered `level-op` | 变化 |
| --- | ---: | ---: | ---: |
| new dominant old share | `33.597%` | `33.709%` | `+0.112 pp` |
| old dominant new share | `32.053%` | `31.902%` | `-0.151 pp` |
| same-index share | `13.886%` | `13.920%` | `+0.034 pp` |
| batch-position correlation | `0.618145` | `0.623659` | `+0.005514` |
| normalized displacement mean | `0.144657` | `0.144559` | `-0.000098` |
| displacement p50 / p90 | `0.030769 / 0.492308` | `0.046154 / 0.492308` | p50 变差 |
| within one / two batches | `34.704% / 50.266%` | `33.850% / 49.042%` | `-0.854 / -1.224 pp` |
| old pairs colocated | `19.055%` | `17.702%` | `-1.353 pp` |

层内 stable key 只带来极小的 correlation 改善，位移均值基本不变，多项 locality 指标反而下降。
这不足以解释或修复 NO0302 的 `+3.85%` cycles 回退。

## 4. 同图 policy 对照

为区分实现问题和跨图问题，又在结构相同的产物间只比较 `level-id -> level-op`：

| Graph | common ops | correlation | mean displacement | within two batches |
| --- | ---: | ---: | ---: | ---: |
| strict / NO0286 shape | `2,073,444` | `0.995113` | `0.020202` | `80.004%` |
| ordered / NO0300 shape | `1,910,892` | `0.993807` | `0.022823` | `74.778%` |

两组均为 `100%` op coverage 且无 ambiguity。说明 `level-op` 实现是确定的，同图上只造成局部 batch
边界移动；它之所以不能稳定 strict/ordered 布局，不是 key 失效，而是局部 graph rewrite 改变依赖深度
后，大量 supernode 已经落入不同的完整 Kahn layer。层内排序无法跨越 layer barrier 恢复邻近关系。

## 5. 判定

`level-op` overlap gate 不通过，保持默认关闭，不编译 emu，也不进入 10k/50k 或 runtime gate。这样避免
把一个静态目标已经失败的候选拿去消耗长时间编译和性能测试。

下一步回到 [NO0304](./NO0304_final_topo_stable_tiebreak_plan_20260712.md) 的 GSim 对照：实现独立、默认
关闭的 ready-stack/ready-op probe，去掉完整 frontier layer barrier，同时保持每条 DAG 边和 deterministic
successor order。仍先做同图结构与 strict/ordered overlap gate，只有明显优于本轮才进入功能和 runtime。

## 6. 产物

```text
build/xs_grhsim_no0306_level_op_ordered_20260712/grhsim/grhsim_emit
build/logs/xs/xs_wolf_grhsim_build_no0306_level_op_ordered_emit_20260712.log
build/logs/xs_perf/no0306/level_id_compute_batch_overlap.report
build/logs/xs_perf/no0306/level_op_compute_batch_overlap.report
build/logs/xs_perf/no0306/strict_level_id_vs_level_op.report
build/logs/xs_perf/no0306/ordered_level_id_vs_level_op.report
```
