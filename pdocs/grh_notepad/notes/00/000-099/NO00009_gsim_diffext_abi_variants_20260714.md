---
id: NO00009
date: 2026-07-14
title: GSim executable GRH DiffExt ABI variants from full SimTop
kind: diagnosis
status: active
area: simulation
topic: gsim-grhsim-exchange
tags: [gsim, grhsim, grh-json, difftest, dpi, xiangshan]
parents: [NO00008]
related: [NO00003, NO00006]
supersedes: []
---

# NO00009 GSim executable GRH DiffExt ABI variants from full SimTop (2026-07-14)

> 归档编号：`NO00009`。主题导航：
> `tree/simulation/gsim-grhsim-exchange/00/000-099.md`。

## Full run01 首诊断

使用已通过 external 局部 gate 的 fresh binary、显式
`xiangshan-gsim-coremark-stub` profile 对完整 `build/xs/rtl/rtl/SimTop.fir` 运行 strict export。
日志：

```text
ptmp/gsim_full_exec_20260714/run01/strict-export.log
wall=9:39.05
maxRSS=97,994,016 KiB
exit=1
```

运行越过 infer-mport、effect、async reset、captured external clock 和 SimJTAG/PrintCommit profile
gate，新的权威首诊断是：

```text
node id=7384679 name='DiffExtArchIntRegState' type=NODE_EXT line=8822528:
unsupported external defname 'DiffExtArchIntRegState':
member[1] 'endpoint$xrf$dpic$io$$value' does not end in 'io.valid'
```

目标 JSON 未安装，temporary spool 由 exporter 清理。

## 根因与全量 census

registry 错把 `io.valid` 当成所有 `DiffExt*` 的固定 member。完整 FIR 有 103 个 DiffExt instance、
27 个唯一 defname；93 个 instance/17 个 defname 含 `member[1] = io.valid`，但另 10 个已审计
defname 没有该 leaf，`member[1]` 就是真实 payload：

```text
TrapEvent, CSRState, DebugMode, TriggerCSRState, VecCSRState,
FpCSRState, HCSRState, ArchIntRegState, ArchFpRegState, ArchVecRegState
```

`DPIC.scala` 的 `HasValid` bundle 才生成 inner `io.valid`；所有 wrapper 的 outer valid、control enable
和 reset 已折入共同的 ext `enable`。生成的 `difftest-extmodule.cpp` 只丢弃真正存在的
`io_valid`，否则从 member 1 开始按序传 payload。对 27 个 adapter 的自动比对证明 FIR flatten 后
argument count/order 与生成 C++ 完全一致。

## 修复

`ExecutableGrhExtRegistry.cpp` 现在：

- 只接受 census 中 27 个已审计 DiffExt defname，未知 `DiffExt*` fail closed；
- 固定 member 0 为 scalar one-bit `enable`，call condition 仍只使用 enable，event 仍为 captured
  clock posedge；
- 10 个明确的 no-`io.valid` ABI 从 member 1 传 payload，其他 17 个仍严格要求并忽略 member 1
  的 exact `io.valid`；
- 其余 member 保持顺序，array 按 element 0 到 N-1 flatten；
- ArchInt/Fp/Vec register snapshot 进一步严格检查三成员结构、`UInt<64>[32/32/64] value` 与
  scalar `UInt<8> coreid`。

focused registry 增加三个 Arch sibling 的 argument count/order、错误 array count、unexpected/missing
valid 和 unaudited defname 拒绝。真实 no-valid `DiffExtTrapEvent` fixture 完成 export、LoadJson、
activity-schedule、GrhSIM emit/build/runtime，输出：

```text
no-valid DiffExt executable GRH PASS
```

它验证 first eval/falling edge 不调用、enable=false 不调用、enabled posedge 恰好一次，以及 payload
位序和 signed DPI bucket 的 bit-preserving conversion。更新后的 fresh binary：

```text
ptmp/gsim_external_integration_20260714/build/gsim/gsim
mtime=2026-07-14 10:02:09 +0800
sha256=7418958bc670ae19ebea1ca30368f71d2e1b63cc27473105905be42f147db49e
```

## 后续

用该 binary 重跑完整 strict export，取得下一条真实首诊断或完整 executable JSON。局部修复不改变
最终 CoreMark 50k gate。

## 增量更新

后续 full run 结果追加于本文或另建新的 root-cause 记录。
