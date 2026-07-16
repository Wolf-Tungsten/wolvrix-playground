---
id: NO00014
date: 2026-07-14
title: GSim canonical clock event pointers across dead-wire removal
kind: implementation
status: active
area: simulation
topic: gsim-grhsim-exchange
tags: [gsim, grhsim, grh-json, clock, alias-analysis, register, memory, xiangshan]
parents: [NO00013]
related: [NO00010]
supersedes: []
---

# NO00014 GSim canonical clock event pointers across dead-wire removal (2026-07-14)

> 归档编号：`NO00014`。主题导航：
> `tree/simulation/gsim-grhsim-exchange/00/000-099.md`。

## Full run05 首诊断

完整 strict export 日志：

```text
ptmp/gsim_full_exec_20260714/run05/strict-export.log
wall=9:35.20
maxRSS=98,036,620 KiB
exit=1
```

run05 越过 constant top-output validation，新的首诊断是：

```text
node id=37170 name='cpu$l_soc$socMisc$buffers$nodeOut_a_q$clock'
type=NODE_OTHERS line=831965: unsupported non-live status 1
```

## 根因

该 node 是 instance clock connection 形成的普通 wire alias。`clockOptimize()` 已正确求出其真正
event source，却只把 alias assignment root 改写成 canonical clock，register/memory port 的
`Node::clock` 指针仍指向 alias。第一次 dead-node removal 不把该 C++ semantic pointer 当作图边，
因此删除 alias；PreCoarsen exporter 随后沿 event pointer 重新看到 `DEAD_NODE`。

这不是可忽略的 dead value：它决定 register 和同步 memory 的触发边沿。

## 修复

`clockOptimize()` 在完成 gated-clock condition lowering 后，将 register source/destination 和 memory
port 的 `clock` event pointer 都改为已经求得的 canonical `clockVal::node`。这发生在 dead removal
与 `splitNodes()` 前，因此 split register fragment 也继承 canonical event source。gated clock 的
enable 仍留在既有 update condition 中，不改变 GSim 的时钟简化策略。

## 局部验证

扩展 `test/executable-grh-split-register-clock.fir`，在 split register 前加入会被删除的
`clock_alias` wire。修复前稳定复现 `clock_alias ... unsupported non-live status 1`；修复后：

```text
make -C reference/gsim \
  BUILD_DIR=$PWD/ptmp/gsim_external_integration_20260714/build \
  test-executable-grh-split-register-clock -j32
executable GRH split-register clock inheritance PASS
```

checker 证明两个 split register write port 都直接使用顶层 clock symbol，而不是已删除 alias。

## 后续

用 fresh binary 运行 full run06。最终 gate 仍是完整 v2 JSON 的 GrhSIM import/build 与 CoreMark
`-C 50000` NEMU difftest。

## 增量更新

后续 full result 使用新记录；本文保留 run05 与 event pointer canonicalization 根因。
