---
id: NO00015
date: 2026-07-14
title: GSim event-clock liveness for register-generated clocks
kind: implementation
status: active
area: simulation
topic: gsim-grhsim-exchange
tags: [gsim, grhsim, grh-json, clock, liveness, register, memory, xiangshan]
parents: [NO00014]
related: [NO00010]
supersedes: []
---

# NO00015 GSim event-clock liveness for register-generated clocks (2026-07-14)

> 归档编号：`NO00015`。主题导航：
> `tree/simulation/gsim-grhsim-exchange/00/000-099.md`。

## Full run06 首诊断

```text
ptmp/gsim_full_exec_20260714/run06/strict-export.log
wall=9:36.45
maxRSS=98,036,680 KiB
exit=1
```

run06 越过 clock alias 首诊断，新的失败是：

```text
node id=7360915 name='cpu$rtcClock' type=NODE_REG_SRC line=8794373:
unsupported non-live status 1
```

FIR 中 `rtcClock` 是由顶层 `clock` 驱动的 1-bit toggle register，经 `asClock` 后作为整个 SoC 的
RTC event clock。它没有普通 value consumer，只有下游 register/memory 的 `Node::clock` semantic
pointer consumer。

## 根因与修复

`removeDeadNodes()` 只沿 assignment graph、reset tree 和少数 terminal ABI 反向标记。它在访问
live register source 时保留 destination/reset，却未保留 source 的 event clock；memory port、effect
和 external root 也存在同类缺口。因此 register-generated clock 及其 next-state cone 会被错误删除，
而 `graph.regsrc` 留下 non-live source。

liveness traversal 现在沿以下 event dependency 继续反向标记：

- live register source 的 `clock`；
- live reader/writer/readwriter 的 `clock`；
- live special effect 的 `effectClock` expression；
- live external root 的 captured `clock`。

这保留真实 event producer，不改变 `clockOptimize()` 已完成的 gated-clock condition lowering，也不
恢复没有 live event consumer 的普通 dead value。

## 局部回归

新增 `executable-grh-register-clock-liveness` fixture：顶层 toggle register 生成子模块时钟。修复前
第一轮 dead removal 删除 generated register/source/destination，exporter 稳定复现 non-live source；
修复后 checker 证明 generated register 存在，且 child register write port 的第四个 input 精确引用
generated register value。

同时复测 clock alias + split register：

```text
make -C reference/gsim \
  BUILD_DIR=$PWD/ptmp/gsim_external_integration_20260714/build \
  test-executable-grh-register-clock-liveness \
  test-executable-grh-split-register-clock -j32
executable GRH register-clock liveness PASS
executable GRH split-register clock inheritance PASS
```

## 后续

用 fresh binary 运行 full run07。最终 gate 仍是完整 v2 JSON 的 GrhSIM import/build 与 CoreMark
`-C 50000` NEMU difftest。

## 增量更新

后续 full result 使用新记录；本文保留 run06 与 event-clock liveness 根因。
