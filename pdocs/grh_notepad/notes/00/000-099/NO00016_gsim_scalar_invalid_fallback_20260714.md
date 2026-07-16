---
id: NO00016
date: 2026-07-14
title: GSim two-state invalid fallback for split scalar leaves
kind: implementation
status: active
area: simulation
topic: gsim-grhsim-exchange
tags: [gsim, grhsim, grh-json, invalid, when, array-split, xiangshan]
parents: [NO00015]
related: [NO00002]
supersedes: []
---

# NO00016 GSim two-state invalid fallback for split scalar leaves (2026-07-14)

> 归档编号：`NO00016`。主题导航：
> `tree/simulation/gsim-grhsim-exchange/00/000-099.md`。

## Full run07 首诊断

```text
ptmp/gsim_full_exec_20260714/run07/strict-export.log
wall=9:45.29
maxRSS=98,612,984 KiB
exit=1
```

run07 证明 event liveness 修复生效：第一次 dead removal 比旧图多保留 39 nodes，最终 PreCoarsen
图为 2,708,079 nodes。新的首诊断进入 expression lowering：

```text
cpu$l_soc$core_with_l2$core$memBlock$inner$sbuffer$io$$forward$$forwardData_2_0
expression id=35420118 op=OP_WHEN: null branch 2 has no prior lvalue value to preserve
```

对应 FIR 是 Sbuffer `forwardData`：先 `invalidate` 每个 array element，再由两个条件分支覆盖。
GSim 是两态 runtime，`OP_INVALID` 不生成 C++ assignment；array lowering 原先已经用 zero 作为确定
base，但 `splitOptionalArray()` 将该实例拆成 scalar leaf 后，exporter 的 scalar path 没有同一 base。

## 修复

所有含 assignment tree 的非寄存器 node 现在从 shape-preserving zero base 开始，随后按 GSim 保存的
tree 顺序应用 indexed/conditional overrides。这样 null `OP_WHEN` branch 和 `OP_INVALID` 都保留当前
两态 base。register destination 不变，仍从 register source 取得 hold value，绝不以 zero 替代 hold。

该规则统一 array container 与 split scalar leaf，不引入四态 X，也不把 invalid 当成可观察数据。

## 局部验证

fixture：

```text
ptmp/gsim_invalid_scalar_fallback_20260714/InvalidScalar.fir
```

包含 invalidate 加两个有优先级的条件覆盖；fresh exporter 成功生成 executable v2 JSON，并发射
priority mux 与 output assignment。三个相关 worktree 的 `diff --check` 均通过。

## 后续

用 fresh binary 运行 full run08。最终 gate 仍是完整 v2 JSON 的 GrhSIM import/build 与 CoreMark
`-C 50000` NEMU difftest。

## 增量更新

后续 full result 使用新记录；本文保留 run07 与 split-scalar invalid fallback 根因。
