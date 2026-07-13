# TNO0017 Global compute residual closure

记录日期：2026-07-13

来源范围：`NO0448..NO0476`，原始记录见 [NO0448](../grhsim_opt/NO0448_global_compute_scope_attribution_plan_20260713.md) 至 [NO0476](../grhsim_opt/NO0476_corrected_runtime_frame_closure_gate_20260713.md)。

状态：完成 latest direct compute profile 的 scope-aware 全局闭合；boolean、logic、concat、state/slot template 与 runtime-frame 候选均停止。

## 1. Ownership correction

5,590 compute samples 中 4,833 有 generated line，562 只有 runtime frame，195 unresolved。只对有 source 的行做 exact scope gate，同时保留完整分母。

校正后的互斥分布：

| Scope | Samples |
| --- | ---: |
| exact value/side-effect body | 2,473 |
| comment/fused | 1,210 |
| prelude | 489 |
| dispatch | 413 |
| shared tail | 118 |

旧的 operation-kind 排名包含跨 supernode 误归，不能继续直接使用。

## 2. Boolean/logic probes

scalar Boolean AND 的 source residual 一度达到 direct `2.547%`；O3 machine audit 只确认 57 operand + 12 result normalization，刚过 `1.034%`。

受限 width-1 AND/OR byte emit 在 fixture 中删指令，但 SimTop broad candidate 生成 2,080,384 helper calls：代表 objects 的 text/instructions 改善，memory/jumps 却 `+0.45%/+4.80%`。storage-aware refinement 后 jumps 更差 `+6.29%`，整个方向停止。

simple logical `&& -> &` probe aggregate 指标改善，但 batch21 text/memory-form 显著增加；短路分支被 slot load 替代，停止。其余 exact `kLogicAnd`、`kEq`、`kOr`、static slice 最大统一残余均低于 direct 1%。

## 3. Concat 与 template closure

wide concat 最初只计 accumulation 时低估覆盖；连续补齐 whole block 和 term-only seeds 后：

```text
all concat source rows/offsets  226 / 221
max unified concat-to-AND       66 samples
direct share                    0.989%
```

仍低于 67-sample 门槛，且 dynamic shift/slice 语义不可合并。

剩余 state-ref/slot payload 共 415 rows，归一化为 174 templates；最大 exact 41，pure popcount 54/direct `0.809%`，无新模板过门。

## 4. Runtime-frame closure

562 runtime-only rows 中的 138 empty keys 与旧 unknown audit 逐项闭合为 mux 80、full OR 3、unresolved 55。named helpers 均落入已分析的 mux/full-width 类或低于 67 samples，runtime-frame 域关闭。

## 5. 阶段结论

scope-aware 归因把多个看似超过 1% 的 operation family 拆成了共同 payload、已停止形态和小残余。到此，通用 boolean/logic/concat/template/helper 路线没有新的可实施候选。下一可见差异转为 side-effect event guard：negedge 时有一批 producer/side effects 理论上可整体跳过。

## 6. 规则审计与关键数据

记录类型：global compute residual 的 scope-correct root-cause closure。单一议题边界是“修正 sample ownership 后，通用 boolean/logic/concat/template/runtime-frame 中是否仍有超过 1% 的统一候选”。本篇没有 full emu runtime 样本；局部 object probe 只决定候选是否值得实现。

| Scope bucket | Samples | Share of 5,590 compute samples |
| --- | ---: | ---: |
| exact value/side-effect body | 2,473 | `44.24%` |
| comment/fused | 1,210 | `21.65%` |
| prelude | 489 | `8.75%` |
| dispatch | 413 | `7.39%` |
| shared tail | 118 | `2.11%` |

代表性候选的最终证据：

| Candidate | Upper bound / object result | Decision |
| --- | ---: | --- |
| one-bit AND/OR byte emit | 5 representative objects instructions `-5.30%`，jumps `+4.80%` | 停止 |
| storage-aware refinement | instructions `-4.89%`，jumps `+6.29%` | 停止 |
| simple `&& -> &` | aggregate instructions `-1.89%`，但 batch21 text `+9,186B` | 停止 |
| concat-to-AND 最大统一类 | 66 samples / direct `0.989%` | 停止 |
| pure popcount template | 54 samples / direct `0.809%` | 停止 |
| runtime unresolved | 55 samples / direct `<1%` | 停止 |

数据来自 production-identical 5,590-sample profile；没有 guest cycle 或 walltime，因为所有候选都在 source/object gate 前后被关闭。详见 [NO0450](../grhsim_opt/NO0450_global_compute_scope_attribution_gate_20260713.md)、[NO0460](../grhsim_opt/NO0460_storage_aware_bit_assumption_negative_gate_20260713.md)、[NO0464](../grhsim_opt/NO0464_simple_logical_and_object_probe_negative_gate_20260713.md)、[NO0472](../grhsim_opt/NO0472_all_concat_seed_coverage_gate_20260713.md) 与 [NO0476](../grhsim_opt/NO0476_corrected_runtime_frame_closure_gate_20260713.md)。
