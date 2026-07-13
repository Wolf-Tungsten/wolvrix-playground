# NO0467 Exact OR and static slice residual plan

日期：2026-07-13

## 1. Objective

[NO0466](./NO0466_exact_eq_and_logicand_residual_audit_gate_20260713.md) 停止 exact `kEq/kLogicAnd` 后，继续审计
scope-corrected exact `kOr` 与 `kSliceStatic`。当前口径为：

| kind | all exact samples | payload | non-payload |
| --- | ---: | ---: | ---: |
| `kOr` | 222 | 102 | 120 |
| `kSliceStatic` | 136 | 30 | 106 |

non-payload 的 read/changed/writeback/activation/runtime helper 独立保留，不合入候选。

## 2. Historical exclusions

- NO0407/NO0408 已停止 full-width OR/AND helper copy/spill；本阶段不重复 wide helper probe。
- NO0456--NO0460 已停止 one-bit AND/OR byte-result/assumption 方向；本阶段不重新引入 assumed-byte helper。
- scalar/SIMD OR 或 slice 本身是 FIR payload；只有 GSim 不共有且机器块可证明冗余的部分才算残余。

## 3. Audit method

对 102 个 `kOr` payload 按 source shape 互斥拆分：simple bool-slot/local OR、nested masked OR、constant identity、wide/SIMD
fusion 与 unresolved consumer fusion。按 opcode、batch、stable/anonymous value 与 basic-block def/use 统计，区分必要 OR、operand
normalization 和独立 copy/spill。

`kSliceStatic` 的 30 个 payload 单独按 input width、offset/output width 与 machine shift/mask/load 分类；总量本身低于 67，
只用于确认没有和 `kOr` 共享同一可替代机制。

## 4. Same-FIR GSim crosscheck

`kOr` payload 当前为 52 stable-name 与 50 anonymous samples。对 stable canonical names 扫描 same-FIR GSim source，分类 exact
OR assignment、exact non-OR、read-only 与 missing。exact GSim OR 是共同 payload；missing/anonymous 全部保守保留。

## 5. Decision gate

只有同一 residual OR class 在扣除 GSim common payload 和历史 stopped classes 后仍至少 67 samples/direct `1%`，才进入
generated-copy O3 probe；probe 必须整对象 instructions 下降且 jump/memory-form 不增。

若最大保守残余低于 67，则同时停止 `kOr/kSliceStatic`，转向 corrected global source 中尚未审计的 scalar concat/add 或
commit/global runtime 差异，不做低覆盖 emitter 改写。
