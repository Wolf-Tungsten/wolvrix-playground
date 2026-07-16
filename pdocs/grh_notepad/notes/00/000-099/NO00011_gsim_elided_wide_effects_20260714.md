---
id: NO00011
date: 2026-07-14
title: GSim optimizer-elided and wide/formatted executable effects
kind: implementation
status: active
area: simulation
topic: gsim-grhsim-exchange
tags: [gsim, grhsim, grh-json, printf, assert, system-task, xiangshan]
parents: [NO00010]
related: [NO00007, NO00008]
supersedes: []
---

# NO00011 GSim optimizer-elided and wide/formatted executable effects (2026-07-14)

> 归档编号：`NO00011`。主题导航：
> `tree/simulation/gsim-grhsim-exchange/00/000-099.md`。

## Full run03 首诊断

使用 [NO00010](./NO00010_gsim_split_register_clock_20260714.md) 的 split-register clock 修复运行
完整 strict export。日志：

```text
ptmp/gsim_full_exec_20260714/run03/strict-export.log
wall=9:34.64
maxRSS=97,994,832 KiB
exit=1
```

run03 越过完整 external、memory 和全部 3,095 个 split-register clock validation，新的首诊断是：

```text
node id=7826987 name='logEndpoint$PRINTF_9374683' type=NODE_SPECIAL line=9374683:
unsupported executable effect: NODE_SPECIAL must have exactly one assignment tree
```

目标 JSON 未安装。

## Optimizer-elided effect 根因

该诊断实际是零棵 assignment tree，不是多棵。FIR 中这个 printf 位于常量化后的 false guard；
`constantNode.cpp` 把 effect tree 算为 `VAL_EMPTY` 并删除，GSim runtime 对它不执行任何动作，但
live `NODE_SPECIAL` terminal 容器保留到 PreCoarsen。

完整图有 7,159 个 special node：6,243 assert、915 printf、1 stop；剩余 executable effect leaf
只有 7,052 个。差值恰为 107 个 optimizer-elided printf，其中 43 个来自 `logEndpoint`，64 个来自
L3 MSHR `BUG_REPRODUCE`。因此 exporter 现在显式区分：

- 零 tree：`OptimizerElided`，不发射 `kSystemTask`；
- 一棵合法 tree：继续严格解析和 lowering；
- 多 tree、null tree 或其他 malformed shape：仍 fail closed。

GraphDumper stats 新增 `plan_optimizer_elided_count`，exporter 只跳过经过该分类的 node。

最小 fixture `ptmp/gsim_inactive_effect_20260714/InactiveEffect.fir` 在修复前稳定复现
`dead_print ... exactly one assignment tree`。修复后 JSON 只有 live system tasks，完全不含
`dead=%d`。

## Wide printf

完整 GSim gprintf ABI census 发现四个 active scalar argument 超过 64 bit：128、256、256 和
512 bit。GrhSIM `grhsim_task_arg` 与 formatter 原生支持任意宽 word vector，因此此前 resolver 和
lowering 的 64-bit 上限是 exporter 人为限制。两处上限已移除；array-valued 或非正宽 argument
仍拒绝。

同一 fixture 的 128-bit `%d` runtime 使用 `bit127 + 5`，得到精确十进制：

```text
170141183460469231731687303715884105733
```

stable clock 不重复触发，dead printf 不出现，最终输出：

```text
optimizer-elided and wide printf effects PASS
```

## Assert 未绑定 format conversion

6,243 个 active assert 中有 402 个 message 含 `%d`、`%x` 或 `%b`。GSim parser 对
`circt_chisel_ifelsefatal` 丢弃 trailing format operands，`OP_ASSERT` 只保留 predicate 与 enable；
旧 `gAssert(cond, strVal)` 又直接把该字符串交给 `fprintf`，触发时存在 varargs UB。当前阶段不能
伪造已丢失的 argument。

兼容策略是把 assert 中未绑定的已知 conversion 转成 literal `%%d`、`%%x`、`%%b`、`%%c`，
并在 op 写入：

```text
gsim.unbound_format_conversions_literalized = true
```

未知 conversion 仍拒绝。该策略保留确定、无 UB 的 diagnostic 文本，但明确不是完整参数格式化
fidelity；真正恢复参数需同时修改 parser AST、`OP_ASSERT` child ABI、optimizer 和原 GSim codegen。

`AssertFormat.fir` 已完成 export、LoadJson、activity-schedule、GrhSIM emit/build 和失败 runtime；
process exit 1，文本稳定为：

```text
[fatal] fatal d=%d x=%x b=%b c=%c percent=%
```

## 验证与 fresh binary

`executable-grh-effects` unit 覆盖 optimizer-elided、multi-tree negative、wide scalar printf、assert
literalization 和 unknown-conversion negative，并通过 `-Wall -Wextra -Werror` 构建。两个局部
fixture 均完成 executable export 到 GrhSIM runtime。fresh binary：

```text
ptmp/gsim_external_integration_20260714/build/gsim/gsim
mtime=2026-07-14 10:47:38 +0800
sha256=45f20f7bca2850d5efde4280c3822377ac31562a8e0ee4a953ccd769a11ddacd
```

三个 worktree 当前相关 diff 均通过 `diff --check`。

## 后续

用该 binary 运行 full run04，继续取得下一条真实首诊断或完整 v2 JSON。局部 effect gate 不替代
完整 import/build 与 CoreMark `-C 50000` NEMU difftest。

## 增量更新

后续 full run 使用新的记录；本文保留 run03 及 effect ABI 兼容决策。
