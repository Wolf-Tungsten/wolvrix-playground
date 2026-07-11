# NO0308 GSim ready-stack topo overlap negative gate

日期：2026-07-12

## 1. 结构门禁

承接 [NO0307](./NO0307_gsim_ready_stack_topo_implementation_20260712.md)，从固定
pre-reg-to-mem checkpoint 生成 strict/ordered 两组 `ready-op`。两边均通过严格结构门禁：

| Metric | strict / NO0286 shape | ordered / NO0300 shape |
| --- | ---: | ---: |
| graph ops | `7,196,059` | `7,204,108` |
| eligible ops | `6,982,222` | `6,990,363` |
| source clones | `2,044,602` | `2,045,861` |
| compute / commit supernodes | `67,449 / 485` | `63,241 / 485` |
| DAG edges | `638,649` | `528,622` |
| boundary activation edges | `2,261,833` | `1,983,923` |
| compute-compute / compute-commit pairs | `2,003,556 / 258,277` | `1,721,698 / 262,225` |

这些计数分别与 NO0286/NO0300 完全一致，证明 `ready-op` 仍只改变 final topo 与派生布局。final topo
耗时约 `23-25 ms`，不是 build-time 问题。

## 2. Overlap 结果

比较集合与 [NO0306](./NO0306_final_topo_level_op_overlap_negative_gate_20260712.md) 完全相同：
`1,498,855` 个共同 stable ops，old/new coverage 为 `72.288%/78.437%`，两边无 cross-batch ambiguity。

| Metric | `level-id` | `level-op` | GSim-like `ready-op` |
| --- | ---: | ---: | ---: |
| new dominant old share | `33.597%` | `33.709%` | `30.614%` |
| old dominant new share | `32.053%` | `31.902%` | `29.935%` |
| same-index share | `13.886%` | `13.920%` | `12.754%` |
| batch-position correlation | `0.618145` | `0.623659` | `0.558657` |
| displacement mean | `0.144657` | `0.144559` | `0.163902` |
| displacement p50 / p90 | `0.030769 / 0.492308` | `0.046154 / 0.492308` | `0.061538 / 0.523077` |
| within one / two batches | `34.704% / 50.266%` | `33.850% / 49.042%` | `30.530% / 40.724%` |
| old pairs colocated | `19.055%` | `17.702%` | `15.536%` |

GSim-style traversal 在所有整体指标上都比当前 layered `level-id` 更差。它确实移除了 layer barrier，但 LIFO
会把 release timing 的局部差异继续放大；单独移植 traversal 没有移植 GSim 的 graph、partition 和稳定
SuperNode allocation，不能获得 GSim 的布局特性。

## 3. 判定

`ready-op` overlap gate 不通过，保持默认关闭，不编译 emu，也不进入功能/runtime gate。连续两种 ordering
probe 均失败后，停止无动态证据的 topo policy 搜索。当前不能再把 NO0300 的 `+3.85%` cycles 简单归因为
“最终排序 key 不稳定”。

下一步补 NO0286/NO0300 的同 workload runtime profile，直接比较：

- compute/commit supernode fire；
- compute-node 与 source/compute/sink op work；
- 如需要，再补 eval round、batch execution 与 touched state/write counters。

该对照用于区分 ordered 图是否每 guest cycle 实际执行了更多工作，还是动态工作下降但单位工作成本/IPC
恶化。前者回到 activation/settle 路径，后者再回到 generated code 与 GSim 单位求解成本差异。

## 4. 产物

```text
build/xs_grhsim_no0308_ready_op_strict_no0286_20260712/grhsim/grhsim_emit
build/xs_grhsim_no0308_ready_op_ordered_20260712/grhsim/grhsim_emit
build/logs/xs/xs_wolf_grhsim_build_no0308_ready_op_strict_emit_20260712.log
build/logs/xs/xs_wolf_grhsim_build_no0308_ready_op_ordered_emit_20260712.log
build/logs/xs_perf/no0308/ready_op_compute_batch_overlap.report
```
