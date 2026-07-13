# NO0465 Exact Eq and LogicAnd residual audit plan

日期：2026-07-13

## 1. Objective

[NO0464](./NO0464_simple_logical_and_object_probe_negative_gate_20260713.md) 已停止 simple `&& -> &`。本阶段按
[NO0448](./NO0448_global_compute_scope_attribution_plan_20260713.md) 校正后的 exact-value body 继续审计 `kEq` 与
`kLogicAnd`，不再使用 nearest-comment operation 归属。

当前 exact counts 为：

| kind | all exact samples | payload | non-payload |
| --- | ---: | ---: | ---: |
| `kEq` | 195 | 90 | 105 |
| `kLogicAnd` | 197 | 69 | 128 |

non-payload 包含 operand/state read、changed compare/accumulate、slot writeback 与 activation propagation；这些作为必要框架
分开报告，不能和 payload 合并过 67-sample gate。

## 2. Inputs

只重放既有 artifacts：

```text
scope-corrected rows: build/logs/xs_perf/no0448/compute_sample_rows.tsv
generated source:     build/xs_grhsim_no0357_direct_state_read_20260712/grhsim/grhsim_emit
line-table objects:   build/logs/xs_perf/no0401/grhsim_SimTop_sched_*_debug_pch.o
same-FIR GSim source: build/xs_gsim_no0255_current_20260710/gsim/gsim-compile/model
GSim sample rows:     build/logs/xs_perf/no0403/gsim_all_sample_rows.tsv
```

不重新运行仿真、perf 或编译 candidate。

## 3. Audit method

对 159 个 payload samples 做互斥分类：

1. scalar state/local-to-constant equality；
2. scalar value-to-value equality；
3. vector/wide equality；
4. simple logical AND，按 NO0464 已停止类扣除；
5. complex/nested logical AND；
6. fused consumer 或无法证明的 machine payload。

每类按 width/storage、opcode、batch、stable value、source expression shape 与 basic-block def/use 汇总。`cmp/test/setcc` 只有在
同一 block 内能证明是重复 normalization 或重复 comparison 时才可列为候选；实现 FIR equality/AND 本身的 compare/logic 不算开销。

## 4. GSim crosscheck

对 stable result names 在 same-FIR GSim source 中查找 exact LHS，区分 equality/logic、alias/mux/other 与 missing。只有两侧实现
相同 FIR payload 后仍存在的 GrhSIM machine work 才算残余；anonymous 或 missing 不能当作 GSim 删除。

NO0464 的 same-TU simple logical-AND 负向结果对所有 exact simple forms 同样生效，不允许通过 operation ownership 重新开启。

## 5. Decision gate

只有单一可替代残余类在扣除共同 GSim payload与 NO0464 stopped class 后仍至少 67 samples/direct `1%`，才进入新的
generated-copy O3 probe。probe 还必须针对 whole representative objects 减少 instructions，且 jump/memory-form 不增。

如果 `kEq` 和 `kLogicAnd` 都不过门槛，则停止两类，转向 scope-corrected exact `kOr`/`kSliceStatic`，不把 framework
changed/activation 重新包装成 payload 优化。
