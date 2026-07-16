---
id: NO00017
date: 2026-07-14
title: GSim optimized-empty live node two-state zero driver
kind: implementation
status: active
area: simulation
topic: gsim-grhsim-exchange
tags: [gsim, grhsim, grh-json, invalid, empty-assignment, two-state, xiangshan]
parents: [NO00016]
related: [NO00011]
supersedes: []
---

# NO00017 GSim optimized-empty live node two-state zero driver (2026-07-14)

> 归档编号：`NO00017`。主题导航：
> `tree/simulation/gsim-grhsim-exchange/00/000-099.md`。

## Full run08 首诊断

```text
ptmp/gsim_full_exec_20260714/run08/strict-export.log
wall=9:42.13
maxRSS=98,623,180 KiB
exit=1
```

run08 越过 run07 的 null branch。新的首诊断：

```text
cpu$l_soc$core_with_l2$core$memBlock$inner$prefetcher$strideOpt$pf_queue_filter$
tlb_req_arb$io$$in$$bits$$pmp_addr type=NODE_OTHERS line=8068548:
live assigned node has no assignment tree
```

该 leaf 在优化后仍是 live ABI/dataflow value，但其 source 只有 invalid/unconnected 语义，GSim 两态
runtime 不为它生成计算语句，初始 storage 值为零。它与 NO00016 的 null branch 属于同一两态边界，
区别是全部 assignment tree 都已被 optimizer 删除。

## 修复

非寄存器 node 即使 assignment tree 为空，也创建 shape-preserving zero base 并发射 `kAssign`；该
assign 标记：

```text
gsim.empty_assignment_zero = true
```

register destination 仍必须存在 next-state assignment，并继续从 source hold value开始；本修复不
掩盖缺失 register update。常量 output 的既有 canonical literal path也保持不变。

## 局部验证

`ptmp/gsim_empty_assignment_zero_20260714/EmptyAssignment.fir` 验证 invalid-only output 在 optimizer
折叠后仍导出精确 8-bit zero。fresh exporter 构建成功；下一项权威验证为 full run09，确认实际
`pmp_addr` node 走 `gsim.empty_assignment_zero` path。

## 后续

用 fresh binary 运行 full run09。最终 gate 仍是完整 v2 JSON 的 GrhSIM import/build 与 CoreMark
`-C 50000` NEMU difftest。

## 增量更新

后续 full result 使用新记录；本文保留 run08 与 optimized-empty live node 根因。
