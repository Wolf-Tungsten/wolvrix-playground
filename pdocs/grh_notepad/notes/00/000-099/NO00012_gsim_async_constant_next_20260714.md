---
id: NO00012
date: 2026-07-14
title: GSim async-reset constant-next register export
kind: implementation
status: active
area: simulation
topic: gsim-grhsim-exchange
tags: [gsim, grhsim, grh-json, register, async-reset, constant-folding, xiangshan]
parents: [NO00011]
related: [NO00007, NO00010]
supersedes: []
---

# NO00012 GSim async-reset constant-next register export (2026-07-14)

> 归档编号：`NO00012`。主题导航：
> `tree/simulation/gsim-grhsim-exchange/00/000-099.md`。

## 预审发现

在 full run04 前，对旧完整 PreCoarsen projection 与原生 GSim model 做流式交叉检查，发现
148,954 个 live `NODE_REG_SRC` 只有 148,874 个 live `NODE_REG_DST`。差值 80 不是丢失绑定，
而是 async-reset register 的 normal next value 被 constant analysis 折叠：

```text
70  DCache missQueue entries_2..15 last_REG{,_1.._4}
8   L2 slice tag/data ren_vec_1
1   syscnt.time_en
1   pll_lock
```

这些寄存器均为 unsigned one-bit，async reset 值为 0，normal update 恒为 1。
`constantNode.cpp` 对“next constant 与 reset value 不同”的 async-reset register 只恢复 source 为
`VALID_NODE`，destination 保持 `CONSTANT_NODE`，并将其 assignment 改写为 canonical `OP_INT`。

此前 exporter 会在 `prepareRegisters()` 找到正确的 src/dst binding，随后却在通用 node validation
把 status 2 的 destination 当作任意 non-live node 拒绝。若直接跳过 destination，又会丢失正常
posedge 写 1 的语义。

## Narrow support

exporter 现在只接受同时满足下列条件的 non-live register destination：

- status 精确为 `CONSTANT_NODE`；
- 与 live `ASYRESET` source 双向绑定；
- scalar shape 与 source 完全一致；
- 恰好一棵 assignment tree；
- lvalue 精确为该 destination；
- root 是 width/sign 精确匹配、无 child 的 canonical `OP_INT` literal。

其余 non-live destination 继续 fail closed。accepted destination 仍通过普通 assignment lowering，
因此 normal data 来自保存的 literal；register reset mux 与 async reset event 继续复用既有路径。
write op 写入：

```text
gsim.constant_normal_update = true
```

## 局部端到端验证

最小 fixture：

```text
ptmp/gsim_constant_reg_dst_20260714/AsyncConstantNext.fir
```

修复前稳定报告：

```text
state$NEXT type=NODE_REG_DST: unsupported non-live status 2
```

修复后完成 GSim executable export、LoadJson、activity-schedule、GrhSIM emit/build 和 runtime。
runtime 验证：stable-clock async reset 立即写 0、reset release 不写、下一 posedge 写常量 1、再次
async reset 写 0、negedge 保持、再下一 posedge 恢复 1。输出：

```text
async reset constant-next register PASS
```

fresh binary：

```text
ptmp/gsim_external_integration_20260714/build/gsim/gsim
mtime=2026-07-14 10:58:57 +0800
sha256=87d3754c898b1aae5b6078e79bd4ba1d42362e240c29daaa9fa27234f66ca61d
```

## 后续

该修复来自完整图 census，但仍需 full run04 证明 80 个实例及后续 emitModel 全部通过。最终 gate
仍是完整 GrhSIM model build 与 CoreMark `-C 50000` NEMU difftest。

## 增量更新

后续 full result 使用新记录；本文保留 constant-next register 的根因与 narrow whitelist。
