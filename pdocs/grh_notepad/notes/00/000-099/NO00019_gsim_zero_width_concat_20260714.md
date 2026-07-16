---
id: NO00019
date: 2026-07-14
title: GSim zero-width FIRRTL concat identity lowering
kind: implementation
status: active
area: simulation
topic: gsim-grhsim-exchange
tags: [gsim, grhsim, grh-json, zero-width, concat, firrtl, xiangshan]
parents: [NO00018]
related: [NO00002]
supersedes: []
---

# NO00019 GSim zero-width FIRRTL concat identity lowering (2026-07-14)

> 归档编号：`NO00019`。主题导航：
> `tree/simulation/gsim-grhsim-exchange/00/000-099.md`。

## Full run10b 首诊断

第一次 run10 因交互中断停在第二次 dead removal，未形成 exporter 结果；保留日志：

```text
ptmp/gsim_full_exec_20260714/run10/strict-export.log
```

重新执行的 run10b 越过 NO00018 的 scalar reference coercion，在约 3.13 GB partial JSON 处得到：

```text
ptmp/gsim_full_exec_20260714/run10b/strict-export.log
wall=9:54.36
maxRSS=99,268,260 KiB
exit=1

...$_floatMap_T_5 line=6470130, expression ... op=OP_INT:
expression width must be positive
```

原 FIR 是：

```text
node _floatMap_T_5 = cat(floatMap_sign_1, UInt<0>(0h0))
```

GSim `ENode::compute()` 和 constant evaluator 均把 non-lvalue width-0 expression 当作零；在 concat
中 width-0 operand 是 identity。Wolvrix GRH 不允许创建零宽 value，因此不能原样物化 literal。

## 修复

`OP_CAT` 使用独立 lowering：若恰有一个 operand width 为 0，消去该 operand并将 surviving scalar
显式 coerce 到 concat result shape；两个 operand 均为零或 survivor 是 array 时继续 fail closed。
其他零宽运算仍由通用正宽检查拒绝，不作泛化猜测。

## 局部验证

fixture：

```text
ptmp/gsim_zero_width_concat_20260714/ZeroWidthConcat.fir
```

左右两种 `cat(UInt<0>, in)` / `cat(in, UInt<0>)` 均成功导出。JSON 所有 value width 均为正，
不存在 `kConcat`，两个 output 的 assignment cone 最终都引用同一 8-bit input；说明 identity 消除
没有创建零宽中间值。

## 后续

用 fresh binary 运行 full run11。最终 gate 仍是完整 v2 JSON 的 GrhSIM import/build 与 CoreMark
`-C 50000` NEMU difftest。

## 增量更新

后续 full result 使用新记录；本文保留 run10b 与 zero-width concat 根因。
