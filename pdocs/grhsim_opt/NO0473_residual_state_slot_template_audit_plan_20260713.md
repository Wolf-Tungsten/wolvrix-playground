# NO0473 Residual state and slot template audit plan

日期：2026-07-13

## 1. Objective

[NO0472](./NO0472_all_concat_seed_coverage_gate_20260713.md) 全量关闭 concat source family 后，对 comment/fused +
shared-prelude 的 residual source 建互斥 ledger。扣除已审计 logical-AND、mux、concat、wide/other helpers、prologue 与小型 array
init 后，剩余主要为：

| source family | all samples | payload | non-payload |
| --- | ---: | ---: | ---: |
| state-ref expression | 287 | 197 | 90 operand/read |
| slot expression | 219 | 218 | 1 runtime helper |

90 个 operand/read 沿用 NO0444 的 inline/fused read 边界，不再作为独立 forwarding 候选。本阶段审计 415 个 payload，判断是否
还有被宽泛 state/slot 标签掩盖的统一 generated-code template。

## 2. Normalization

对 actual source 做结构保持的 token normalization：

- local/value/slot/state offset 与常量 ID 归一化；
- 保留 result C++ type、operator、cast、helper name、operand storage family 与 expression nesting；
- `&`、`|`、comparison、arithmetic、shift、plain load/copy 分开；
- 同一 machine offset 只计一次，重复 samples 另列。

同时按 opcode、batch、ownership 与 exact normalized template 汇总。只有相同 result type/operator/storage/nesting 的模板才允许合并；
不能把所有含 state ref 的 payload 当成一种机制。

## 3. Historical exclusions

- simple one-bit AND/OR 与 byte normalization 已由 NO0454--NO0460 停止；
- logical short-circuit 已由 NO0464 停止；
- register/state forwarding 已由 NO0444、assign boundary 已由 NO0447 停止；
- mux/full-width helper/concat 分别由 NO0406/NO0412、NO0408、NO0472 闭合。

归一化模板若落入这些 stopped classes，直接标记 historical，不进入新 probe。

## 4. Decision gate

只有同一未审计 template class 覆盖至少 67 samples/direct `1%`，且 machine opcode/context 表明存在可替代成本，才进入
same-FIR GSim crosscheck 或 generated-copy O3 probe。

若最大 exact template 和最大安全 coarse class 都低于 67，则关闭 comment/fused residual 的 source-template 路线，转回
runtime-frame-only/side-effect/commit 等全局域，不按相似源码外观继续细分低覆盖表达式。
