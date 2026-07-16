---
id: NO00020
date: 2026-07-14
title: GSim contextual zero-width literal materialization
kind: implementation
status: active
area: simulation
topic: gsim-grhsim-exchange
tags: [gsim, grhsim, grh-json, zero-width, literal, array-split, sram, xiangshan]
parents: [NO00019]
related: [NO00016]
supersedes: []
---

# NO00020 GSim contextual zero-width literal materialization (2026-07-14)

> 归档编号：`NO00020`。主题导航：
> `tree/simulation/gsim-grhsim-exchange/00/000-099.md`。

## Full run11 首诊断

```text
ptmp/gsim_full_exec_20260714/run11/strict-export.log
wall=9:55.02
maxRSS=99,048,636 KiB
exit=1
```

run11 越过 zero-width concat，在约 4.04 GB partial JSON 处得到：

```text
cpu$l_soc$l3cacheOpt$tpmeta$tpDataTable$array$RW0$$wdata$8159_7905
type=NODE_OTHERS line=8468773, expression ... op=OP_INT:
expression width must be positive
```

这是 8160-bit SRAM `RW0.wdata` 被 split 成 255-bit leaf 后的 assignment。优化 tree 保存了
width-0 literal rvalue；GSim 对任何 non-lvalue width-0 expression 直接计算为常量零。它不位于 concat，
因此 NO00019 的 identity 规则不适用，但 assignment fallback 已提供精确的 255-bit scalar shape。

## 修复

当且仅当同时满足以下条件时，width-0 `OP_INT` 被物化为正宽零：

- expression 没有 node reference、没有 child；
- lowering caller 提供正宽 scalar fallback；
- zero 使用 fallback 的 width/sign。

没有 fallback、fallback 是 array 或宽度非正时继续 fail closed。这样不会根据 owner 或相邻 operand
猜测宽度，也不会生成 GRH 零宽 value。

## 局部验证

fixture：

```text
ptmp/gsim_zero_width_context_20260714/ZeroWidthContext.fir
```

8-bit output 先由 data 驱动，再在条件分支写 `UInt<0>(0)`。fresh exporter 生成一个 8-bit zero、
一个 priority mux，所有 JSON value width 均为正：

```text
executable GRH contextual zero-width literal PASS
```

## 后续

用 fresh binary 运行 full run12。最终 gate 仍是完整 v2 JSON 的 GrhSIM import/build 与 CoreMark
`-C 50000` NEMU difftest。

## 增量更新

后续 full result 使用新记录；本文保留 run11 与 contextual zero-width literal 根因。
