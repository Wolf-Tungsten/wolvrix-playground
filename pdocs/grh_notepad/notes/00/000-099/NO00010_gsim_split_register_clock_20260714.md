---
id: NO00010
date: 2026-07-14
title: GSim split-register clock inheritance for executable GRH
kind: diagnosis
status: active
area: simulation
topic: gsim-grhsim-exchange
tags: [gsim, grhsim, grh-json, register, clock, split-node, xiangshan]
parents: [NO00009]
related: [NO00002, NO00007]
supersedes: []
---

# NO00010 GSim split-register clock inheritance for executable GRH (2026-07-14)

> 归档编号：`NO00010`。主题导航：
> `tree/simulation/gsim-grhsim-exchange/00/000-099.md`。

## Full run02 首诊断

在 [NO00009](./NO00009_gsim_diffext_abi_variants_20260714.md) 的 DiffExt ABI 修复后，使用
fresh GSim binary 和显式 `xiangshan-gsim-coremark-stub` profile 再次导出完整
`build/xs/rtl/rtl/SimTop.fir`。日志：

```text
ptmp/gsim_full_exec_20260714/run02/strict-export.log
wall=9:34.35
maxRSS=97,994,012 KiB
exit=1
```

run02 越过了全部 external/DPI preparation，新的权威首诊断进入 register preparation：

```text
node id=9885634
name='cpu$l_soc$core_with_l2$core$frontend$inner$bpu$abtb$t1_train$$abtbMeta$$bankMask$3_3'
type=NODE_REG_SRC line=1100557: register has no clock node
```

目标 JSON 未安装。

## 根因与 census

FIR line 1100557 是合法的 aggregate `reg t1_train ..., clock`。其中 `abtbMeta.bankMask` 是
`UInt<4>` leaf；GSim `splitNodes()` 按 bit-use boundary 将它拆为多个 `$hi_lo` register pair。
`createSplittedNode()` 使用 `Node::dup()` 创建新的 source/destination，但 `Node::dup()` 有意只复制
值类型信息，不复制 caller-owned `clock` 指针，且该 split path 没有像 array split 一样显式补回
clock。因此 FIR clock 没有丢失，丢失的是优化后 split-register node 的事件元数据。

旧完整 pre-coarsen projection 的流式 census 显示 3,095 个 live `NODE_REG_SRC` 名称带
`$hi_lo`，覆盖 585 个 source line；这些 register fragment 都受同一问题影响，不能在 exporter
中猜测 top clock 或仅为首个节点放宽验证。

## 最小复现与修复

最小 fixture 位于：

```text
ptmp/gsim_split_reg_clock_20260714/SplitRegisterClock.fir
```

它使用一个 4-bit synchronous-reset register 和 18 个 bit-0 fanout，稳定触发：

```text
[splitNode] split 2 nodes
state$3_1 type=NODE_REG_SRC: register has no clock node
```

修复位于 `reference/gsim/src/splitNodes.cpp`：创建 split register pair 后，source fragment 继承
原 source clock，destination fragment 继承原 destination clock；不修改全局 `Node::dup()` 语义，
也不放宽 executable exporter 的 fail-closed clock validation。

## 局部端到端验证

修复后的 fresh binary：

```text
ptmp/gsim_external_integration_20260714/build/gsim/gsim
mtime=2026-07-14 10:19:03 +0800
sha256=a2f059231589f8b066c19183a3186c56637cd6d4cf7b894d0c7798eaeb56dc0d
```

同一 fixture 已完成 GSim PreCoarsen executable export、Wolvrix `LoadJson`、
`activity-schedule`、GrhSIM C++ emit、archive build 和 runtime。runtime 固定了：stable-low 不写、
posedge 同时更新两个 split fragment、stable-high/negedge 保持、下一 posedge 捕获，以及 synchronous
reset 只在下一 posedge 生效。输出：

```text
split register clock inheritance PASS
```

局部验证证明 clock inheritance 修复了 3,095 个同形 fragment 的共同结构缺陷；它不替代完整
SimTop export、完整 model build 或 CoreMark 50k difftest。

## 后续

使用上述 fresh binary 运行 full run03。若仍失败，保存 exporter 的下一条首诊断并继续建立最小
fixture；只有完整 JSON import/build 和 CoreMark `-C 50000` NEMU difftest 通过后才关闭总目标。

## 增量更新

后续 full run 结果使用新的记录，本文保留 run02 和 split-register clock 根因的证据。
