# NO0461 Fused and prelude machine audit plan

日期：2026-07-13

## 1. Objective

[NO0450](./NO0450_global_compute_scope_attribution_gate_20260713.md) 校正后仍有两类不能按最近 operation 解释的
source-backed compute samples：

| ownership | samples | direct share |
| --- | ---: | ---: |
| comment-only / compiler-fused | 1,210 | 18.127% |
| shared supernode prelude | 489 | 7.326% |
| total | 1,699 | 25.453% |

其中 payload 1,192、runtime helper 252、operand/read 221。one-bit byte emit 已在
[NO0460](./NO0460_storage_aware_bit_assumption_negative_gate_20260713.md) 停止；本阶段回到这 1,699 个样本，
按机器基本块和真实 source scope 找跨 operation 机制，不把它们重新归给 nearest comment。

## 2. Inputs

只重放既有 artifacts，不重新编译、运行仿真或采集 perf：

```text
sample rows:
  build/logs/xs_perf/no0448/compute_sample_rows.tsv
generated source:
  build/xs_grhsim_no0357_direct_state_read_20260712/grhsim/grhsim_emit
production-identical line-table objects:
  build/logs/xs_perf/no0401/grhsim_SimTop_sched_{0..65}_debug_pch.o
same-FIR GSim source:
  existing NO0404/NO0451 source tree
```

要求目标 1,699/1,699 offsets 均命中对应 function，debug object `.text` 与 production identity 继续沿用 NO0402 的
66/66 gate；不能用 candidate NO0457 objects。

## 3. Machine classification

对每个 sample 提取所在 basic block、前后 def/use 指令和 generated source scope，互斥拆分：

1. scalar/SIMD payload：bitwise、compare/setcc、arith、shift、select；
2. value/state load 与 spill/copy；
3. branch/control；
4. known runtime helper；
5. entry/prelude local expression；
6. unresolved fused instruction。

同时按 mnemonic、batch、supernode、source family、helper symbol 和 source expression shape 汇总。comment-only 行只能根据
同一基本块内可证明的 def/use 连接到后续 expression；跨 branch、跨 supernode 或只靠相邻注释的连接一律拒绝。

## 4. Historical exclusions and GSim crosscheck

先显式扣除已审计机制：

- NO0412 的 line-0 `grhsim_mux_u64` 80 samples 与 full OR 3 samples；
- NO0406 的 same-condition mux reuse；
- NO0407/NO0408 的 full-width logic helpers；
- NO0410 的 deferred activation；
- NO0414 的 active-word dispatch；
- NO0444/NO0447 的 register-read 与 assign boundary。

对剩余最大 source shape 才连接 same-FIR GSim。stable value/family 必须比较两侧是否实现相同 payload；anonymous 或无法
crosswalk 的样本作为保守上界，不能当作 GSim 删除。

## 5. Decision gate

只有同一个可替代的 GrhSIM-specific machine/source class 在扣除共同 GSim payload 后仍至少 67 samples/direct `1%`，
才进入局部 generated-copy O3 probe。probe 必须减少 whole representative object instructions，且 branch/memory-form 不增；
否则停止该类并转向 corrected exact `kEq`/`kLogicAnd`，不重复 mux、full-width logic 或 byte-result 实验。

本阶段只做审计，尚不修改 emitter。
