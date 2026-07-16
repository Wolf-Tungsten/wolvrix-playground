---
id: NO00022
date: 2026-07-14
title: GSim optimizer-elided memory writer export
kind: implementation
status: active
area: simulation
topic: gsim-grhsim-exchange
tags: [gsim, grhsim, grh-json, memory, writer, constant-analysis, xiangshan]
parents: [NO00021]
related: [NO00002, NO00011, NO00017]
supersedes: []
---

# NO00022 GSim optimizer-elided memory writer export (2026-07-14)

> 归档编号：`NO00022`。主题导航：
> `tree/simulation/gsim-grhsim-exchange/00/000-099.md`。

## Full run13 首诊断

```text
ptmp/gsim_full_exec_20260714/run13/strict-export.log
wall=10:12.32
maxRSS=99,881,264 KiB
exit=1
```

run13 越过 run12 的 packed array element coercion，首次停在 aggregate memory 字段 writer：

```text
cpu$l_soc$socMisc$axi4buf_8$nodeOut_aw_deq_q$MPORT$$id
type=NODE_WRITER line=998068: live writer has no executable write action
```

对应 FIRRTL 是 `cmem ram` 的 infer mport，且整个 write 位于 `when do_enq` 内。优化后该实例的
write guard 为常量 false；ConstantAnalysis 删除完整 writer `assignTree`，但存活 reader 使 backing
memory 及其 writer port 继续通过 memory liveness 保留。

## 最小复现与证据

最小 fixture：

```text
ptmp/gsim_empty_memory_writer_20260714/EmptyMemoryWriter.fir
```

它包含一个存活 combinational memory read 和一个 `when UInt<1>(0)` 下的 infer mport write。
PreCoarsen assign-tree dump 明确显示：

```text
writer type=NODE_WRITER status=VALID_NODE assignTrees=[]
reader type=NODE_READER status=VALID_NODE assignTrees=[OP_READ_MEM]
memory type=NODE_MEMORY status=VALID_NODE members=[writer, reader]
```

因此这是合法的 optimizer-elided side-effect port，而不是 exporter 遗失 data/address lowering。

## 修复

memory write lowering 现在先检查每棵 write expression 是否仍含潜在动作：

- null、`OP_INVALID` 和 `OP_READ_MEM` 不算 write；
- `OP_WHEN` 递归检查两个 action branch；
- 其余 expression 保持原有 write lowering；
- 只有声称含 write action、lowering 后却没有产生 write 时才继续 fail closed。

由常量分析清空的 writer 不再强制生成虚假写操作。backing memory 和 live read 保留，writer 不生成
`kMemoryWritePort`。

## 回归

新增：

```text
reference/gsim/test/executable-grh-empty-memory-writer.fir
reference/gsim/test/check-executable-grh-empty-memory-writer.py
make test-executable-grh-empty-memory-writer
```

checker 验证恰有一个 `kMemory`、一个 `kMemoryReadPort`、零个 `kMemoryWritePort`。同时通过：

```text
test-executable-grh-split-register-clock
test-executable-grh-register-clock-liveness
test-executable-grh-async-reset-constant-next
test-executable-grh-effects
```

## 后续

用 fresh binary 运行 full run14。最终 gate 仍是完整 v2 JSON 的 Wolvrix direct LoadJson、
activity-schedule、GrhSIM emit/build 和 CoreMark `-C 50000` NEMU difftest。

## 增量更新

后续 full result 使用新记录；本文保留 run13 与 optimizer-elided memory writer 的根因和修复。
