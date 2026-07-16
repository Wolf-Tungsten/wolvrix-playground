---
id: NO00013
date: 2026-07-14
title: GSim optimizer-folded constant top-output export
kind: implementation
status: active
area: simulation
topic: gsim-grhsim-exchange
tags: [gsim, grhsim, grh-json, constant-folding, output-port, xiangshan]
parents: [NO00012]
related: [NO00006]
supersedes: []
---

# NO00013 GSim optimizer-folded constant top-output export (2026-07-14)

> 归档编号：`NO00013`。主题导航：
> `tree/simulation/gsim-grhsim-exchange/00/000-099.md`。

## Full run04 首诊断

使用 NO00012 的 constant-next register 修复运行完整 strict export。日志：

```text
ptmp/gsim_full_exec_20260714/run04/strict-export.log
wall=9:35.19
maxRSS=98,037,572 KiB
exit=1
```

run04 越过此前所有 register 和 effect validation，新的首诊断是：

```text
node id=3 name='difftest$$exit' type=NODE_OUT line=9374745:
unsupported non-live status 2
```

这是 constant analysis 折叠后的顶层输出端口。端口仍属于 graph ABI，不能像 dead internal node
一样跳过；必须保留端口 symbol 并发射其常量 driver。

## Narrow support

exporter 现在只接受同时满足下列条件的 non-live output：

- node 位于 graph 的正式 output port list；
- status 精确为 `CONSTANT_NODE`；
- scalar、正宽；
- 恰好一棵 assignment tree，lvalue 精确指向该 output；
- root 是 width/sign 精确匹配、无 child 的 canonical `OP_INT` literal。

accepted output 仍作为公开 output symbol 发射，并由普通 constant op 驱动；op 标记：

```text
gsim.constant_output = true
```

其他 non-live output、array constant 或 malformed assignment 继续 fail closed。

## 局部验证

最小 fixture：

```text
ptmp/gsim_constant_output_20260714/ConstantOutput.fir
```

修复后成功生成：

```text
ptmp/gsim_constant_output_20260714/fixed/gsim/ConstantOutput.exec.json
```

JSON 保留 output port，并包含精确常量 driver 与 `gsim.constant_output=true`。fresh GSim binary：

```text
ptmp/gsim_external_integration_20260714/build/gsim/gsim
mtime=2026-07-14 11:22:21 +0800
```

三个相关 worktree 的 `diff --check` 均通过。

## 后续

使用该 binary 运行 full run05，继续取得下一条真实首诊断或完整 v2 JSON。最终 gate 仍是完整
GrhSIM import/build 与 CoreMark `-C 50000` NEMU difftest。

## 增量更新

后续 full result 使用新记录；本文保留 run04 与 constant top-output 的窄兼容规则。
