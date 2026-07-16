---
id: NO00021
date: 2026-07-14
title: GSim element-wise packed array assignment coercion
kind: implementation
status: active
area: simulation
topic: gsim-grhsim-exchange
tags: [gsim, grhsim, grh-json, array, coercion, register, xiangshan]
parents: [NO00020]
related: [NO00002]
supersedes: []
---

# NO00021 GSim element-wise packed array assignment coercion (2026-07-14)

> 归档编号：`NO00021`。主题导航：
> `tree/simulation/gsim-grhsim-exchange/00/000-099.md`。

## Full run12 首诊断

```text
ptmp/gsim_full_exec_20260714/run12/strict-export.log
wall=10:07.93
maxRSS=99,751,996 KiB
exit=1
```

run12 越过完整 width-0 corpus，在约 6.0 GB partial JSON 处进入 array register lowering：

```text
...$dispatch$intBusyTable$loadDependency$NEXT type=NODE_REG_DST line=3141540,
expression ... op=OP_WHEN: incompatible packed array assignment shape
```

原 FIR register 是 `UInt<2>[3][224]`。每个 outer entry 的第一条 conditional write 使用
`UInt<2>[3]`，另一条 write 使用 `UInt<3>[3]`，合法 FIRRTL connect 要求把后者逐元素截为 2 bit。
整包从 9 bit 截为 6 bit 会错误移动 element boundary，因此不能复用 scalar truncate。

## 修复

array-to-array coercion 现在：

- 首先要求 flat element count 完全相同；
- element width/sign 相同则保留原 packed symbol，可允许等元素数 reshape；
- element width/sign 不同则按 flat index 对每个 source element 发射 static slice，逐元素调用 scalar
  `coerceToShape()`，再按原 array packing 顺序 concat 为 target shape；
- element count 不同继续 fail closed。

这使 array update 的 SSA temporary 明确保留逐元素 FIRRTL connect 语义。

## 局部验证

fixture：

```text
ptmp/gsim_array_element_coercion_20260714/ArrayElementCoercion.fir
```

`UInt<2>[3]` register 在条件分支接收 `UInt<3>[3]`。fresh JSON 包含至少三个 element slice、逐元素
truncate、repack concat 和 register write port，且所有 value width 为正：

```text
executable GRH element-wise array coercion PASS
```

## 后续

用 fresh binary 运行 full run13。最终 gate 仍是完整 v2 JSON 的 GrhSIM import/build 与 CoreMark
`-C 50000` NEMU difftest。

## 增量更新

后续 full result 使用新记录；本文保留 run12 与 element-wise array coercion 根因。
