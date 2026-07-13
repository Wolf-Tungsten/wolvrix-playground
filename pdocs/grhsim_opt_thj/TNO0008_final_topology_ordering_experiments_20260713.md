# TNO0008 Final-topology ordering experiments

记录日期：2026-07-13

来源范围：`NO0304..NO0308`，原始记录见 [NO0304](../grhsim_opt/NO0304_final_topo_stable_tiebreak_plan_20260712.md) 至 [NO0308](../grhsim_opt/NO0308_gsim_ready_stack_topo_overlap_negative_gate_20260712.md)。

状态：`level-op` 与 `ready-op` 两种默认关闭的排序实验均判负，production 继续使用 `level-id`。

## 1. 问题

final topo order 会继续决定 active ID、dispatch word、batch composition、slot layout 和最终函数地址。ordered-write 前后即使图结构接近，临时 supernode ID 的变化仍会引起大范围 batch 重排。

## 2. `level-op`

`level-op` 保留 Kahn layer barrier，只在同层按最小稳定 op ID 排序。严格关闭 decoded discovery/ordered lowering 后，SimTop graph、DAG、boundary 与 compute/commit pairs 全量一致，证明 probe 只改变布局。

但 strict/ordered batch correlation 仅从 `0.6181` 变为 `0.6237`，pair 共置率下降，平均位移基本不变。失败原因是完整 Kahn layer barrier 阻止跨层稳定化。

## 3. GSim-like `ready-op`

`ready-op` 使用稳定 op key、升序 roots/successors 和 LIFO ready stack，可跨 Kahn layer。结构仍精确复现 baseline，但结果更差：

```text
batch correlation  0.5587
average displacement 0.1639
pair colocation     15.54%
```

## 4. 决策

- 两个候选都不进入 emu/runtime gate；
- 不再通过盲试 topo tie-break 解释 ordered-write 性能；
- production 保持 `level-id`；
- 后续先比较动态 fire/work，再处理 code layout 与 ASLR。

## 5. 规则审计与关键数据

记录类型：单一 topology hypothesis 的负向结构 gate。议题边界是“仅改变 final-topo tie-break 能否提高 strict/ordered 两版的 batch 对齐度”。两个 policy 是同一假设的低风险和 GSim-like 两种实现；两者都在预声明的结构门槛失败，因此没有 emu、guest cycle、walltime 或 perf 样本。

| Policy | Strict/ordered batch correlation | Mean displacement | Pair co-location | Runtime status |
| --- | ---: | ---: | ---: | --- |
| production `level-id` | `0.6181` | 基线 | 基线 | 保留 |
| `level-op` | `0.6237` | 基本不变 | 下降 | 未进入 emu |
| `ready-op` | `0.5587` | `0.1639` | `15.54%` | 未进入 emu |

两项 probe 都精确保持 graph ops、supernodes、DAG、boundary 和 compute/commit pair 结构；失败仅说明 ordering overlap 没有改善，不能推导 runtime。数据见 [NO0306](../grhsim_opt/NO0306_final_topo_level_op_overlap_negative_gate_20260712.md) 与 [NO0308](../grhsim_opt/NO0308_gsim_ready_stack_topo_overlap_negative_gate_20260712.md)。
