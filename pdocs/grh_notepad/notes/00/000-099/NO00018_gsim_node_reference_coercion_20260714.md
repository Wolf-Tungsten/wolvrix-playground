---
id: NO00018
date: 2026-07-14
title: GSim explicit scalar node-reference coercion after used-bits optimization
kind: implementation
status: active
area: simulation
topic: gsim-grhsim-exchange
tags: [gsim, grhsim, grh-json, used-bits, width, coercion, xiangshan]
parents: [NO00017]
related: [NO00002]
supersedes: []
---

# NO00018 GSim explicit scalar node-reference coercion after used-bits optimization (2026-07-14)

> 归档编号：`NO00018`。主题导航：
> `tree/simulation/gsim-grhsim-exchange/00/000-099.md`。

## Full run09 首诊断

```text
ptmp/gsim_full_exec_20260714/run09/strict-export.log
wall=9:46.75
maxRSS=98,673,028 KiB
exit=1
```

run09 越过 empty-assignment node，并继续写到约 2.87 GB 后失败：

```text
cpu$l_soc$core_with_l2$core$frontend$inner$itlb$_readResult_gpaddr_offset_T_1
expression id=71973403 op=OP_EMPTY:
implicit node-reference width/sign conversion is not supported
```

原 FIR 是对地址执行 `bits(readResult_crossPageVaddr, 63, 12)`。GSim usedBits、alias 和 split 优化
可以让 node storage 的物理宽度与引用 ENode 的逻辑宽度不同；原生 inst generator 按 ENode width
执行转换，旧 exporter 却要求二者完全相同。

## 修复

scalar node-reference 现在先按 canonical storage shape 完成 static/dynamic selection，再通过现有
`coerceToShape()` 显式发射 truncate、zero-extend 或 sign-extend，使转换在 GRH JSON 中可见且可
调度。array-valued reference 仍要求 element width/sign 完全一致，不允许隐式改变 array shape。

## 回归

fresh GSim binary 通过以下 exporter 回归：

```text
test-executable-grh-register-clock-liveness
test-executable-grh-split-register-clock
test-executable-grh-async-reset-constant-next
test-executable-grh-effects
```

输出分别为 PASS；effects unit 仍以 `-Wall -Wextra -Werror` 构建。三个相关 worktree 的
`diff --check` 均通过。

## 后续

用 fresh binary 运行 full run10。最终 gate 仍是完整 v2 JSON 的 GrhSIM import/build 与 CoreMark
`-C 50000` NEMU difftest。

## 增量更新

后续 full result 使用新记录；本文保留 run09 与 explicit scalar coercion 根因。
