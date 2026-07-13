# NO0466 Exact Eq and LogicAnd residual audit gate

日期：2026-07-13

## 1. Scope closure

按 [NO0465](./NO0465_exact_eq_and_logicand_residual_audit_plan_20260713.md) 只重放既有 scope-corrected rows、
production-identical line-table objects 与 same-FIR GSim source。exact-value counts 精确闭合为：

| kind | all exact | payload | read/changed/writeback/activation |
| --- | ---: | ---: | ---: |
| `kEq` | 195 | 90 | 105 |
| `kLogicAnd` | 197 | 69 | 128 |

non-payload 没有并入候选；本阶段没有重新运行仿真、perf 或编译 candidate。

## 2. LogicAnd residual

69 个 `kLogicAnd` payload 中，30 个是如下 simple local/bool-slot form：

```cpp
const bool next_value = (operand_a) && (operand_b);
```

该 generated-code 类已由 [NO0464](./NO0464_simple_logical_and_object_probe_negative_gate_20260713.md) 的跨 TU object gate
停止，不能因 operation ownership 改为 exact body 而重新开启。剩余 complex/nested logical AND 为 39 samples/direct
`0.584%`，低于 67/direct `1%`，停止 `kLogicAnd`。

## 3. Equality source and machine classes

90 个 equality payload 的 source shape 为：

| shape | samples |
| --- | ---: |
| state u16 to constant | 31 |
| slot u16 to constant | 18 |
| slot u32 to constant | 10 |
| state u8 to constant | 10 |
| local to constant | 8 |
| slot u8 to constant | 7 |
| other scalar equality | 5 |
| state u8 to value | 1 |

机器 opcode 为 `cmp=51`、`sete=20`、`cmpw=4`、`pcmpeqw=4`、`test=2`；这 81 个直接实现 scalar/SIMD
equality。其余 9 个 `pack/shuffle/and/shr/mov` samples 位于 equality 与相邻 SIMD consumer 的融合实现中，没有独立
compare-normalization block。所有 90 条 source line 都是 equality 本体，没有形成可单独删除的 67-sample machine class。

## 4. Same-FIR GSim crosscheck

90 个 `kEq` payload 分为 65 个 stable-name samples/values 与 25 个 anonymous samples。对 65 个 canonical stable names
扫描 3.7 GiB GSim source，结果为：

| classification | samples | direct share |
| --- | ---: | ---: |
| exact GSim equality assignment | 26 | 0.390% |
| stable name not found | 39 | 0.584% |
| anonymous | 25 | 0.375% |

26 个 exact assignments 是两侧共同 FIR equality payload，从候选中扣除；39 个 missing 与 25 个 anonymous 全部保守留下，
不推断 GSim 删除。由此 equality 的最大保守残余为 `90 - 26 = 64` samples/direct `0.959%`，仍低于门槛。

## 5. Decision

`kLogicAnd` 与 `kEq` 的保守残余分别为 39/direct `0.584%` 和 64/direct `0.959%`，均未达到预声明的
67/direct `1%`：

- 不做 generated-copy probe；
- 不修改 emitter 或新增开关；
- 不把 missing/anonymous 当作 GSim 删除，也不把 framework samples 合入 payload；
- 后续转向 scope-corrected exact `kOr`/`kSliceStatic`。
