---
id: NO00007
date: 2026-07-14
title: GSim executable GRH async-reset exporter integration
kind: implementation
status: active
area: simulation
topic: gsim-grhsim-exchange
tags: [gsim, grhsim, grh-json, async-reset, register, xiangshan]
parents: [NO00004, NO00006]
related: [NO00002]
supersedes: []
---

# NO00007 GSim executable GRH async-reset exporter integration (2026-07-14)

> 归档编号：`NO00007`。主题导航：
> `tree/simulation/gsim-grhsim-exchange/00/000-099.md`。

## 背景

[`NO00004`](./NO00004_gsim_async_reset_contract_20260714.md) 已固定异步复位的单一多事件
`kRegisterWritePort` 契约，但当时没有接入 executable exporter。修复
[`NO00006`](./NO00006_gsim_executable_grh_recovery_20260714.md) 的 infer-mport 首诊断后，使用
fresh-before-async binary 的完整 `SimTop` strict export 在 9:36.70 后得到新的权威首诊断：

```text
[ExecutableGrhExport] ERROR: node id=31029
name='cpu$l_soc$socMisc$xbar$beatsLeft' type=NODE_REG_SRC line=824566:
asynchronous reset requires the executable-async-reset extension
```

日志位于 `ptmp/gsim_exec_recovery_20260714/full_after_infer/strict-export.log`，峰值 RSS
98,527,892 KiB。该结果证明完整图已越过 infer-mport memory gate，并把 async reset 确认为下一
阻塞项；该 full run 使用的 binary 尚不包含本文实现。

## 实现

`reference/gsim/src/ExecutableGrhExporter.cpp` 现把 register lowering 结果表示为 data 与可选
async reset condition：

- `normalData` 先由普通 next-value/hold mux 得到；
- `OP_RESET(cond, value)` 生成最外层 `mux(cond, resetValue, normalData)`，保证复位优先；
- 同步复位 write port 只监听 base clock；
- 异步复位仍只生成一个 write port，operands 为
  `[1, writeData, allOnesMask, baseClock, resetCond]`，event edges 为
  `['posedge', 'posedge']`；
- JSON 写入 `gsim.reset_kind = none|sync|async`，便于 census；
- base clock 和 reset condition 必须是 scalar one-bit，indexed reset lvalue 严格拒绝。

reset array shape 采用 fail-closed 规则：array-to-array 必须 dimensions 逐项相同，array 不能写入
scalar；唯一允许的 scalar-to-array 是 GSim 将 uniform `OP_GROUP` constant canonicalize 成
`OP_INT` 的形式，由 exporter 按 element shape 显式复制。该例外是完整 SimTop 1,469 个 zero
memset array reset 所需的真实 GSim canonical form，不允许普通 scalar expression 广播。

## 验证

fresh binary 为：

```text
ptmp/gsim_async_integration_20260714/build/gsim/gsim
mtime = 2026-07-14 09:12:29 +0800
sha256 = 3a382426d070c1aa08489159e5921af337d10cd6793084c164ac0747c3454312
```

下列 fixture 均完成 GSim PreCoarsen executable export、Wolvrix LoadJson、在
`activity-schedule` 前导入、GrhSIM C++ emit/build 和 runtime harness：

| fixture | 覆盖 | runtime 结果 |
| --- | --- | --- |
| `SyncHigh` | 同步复位只响应 clock | `exported GRH reset contract PASS` |
| `AsyncHigh` | 直接 async、assert/release、动态 value、first-eval、clock/reset 同时上升 | `exported GRH reset contract PASS` |
| `AsyncActiveLowExpr` | `not(reset_n)` 派生 event | `exported GRH reset contract PASS` |
| `AsyncOrDynamic` | OR reset 表达式与动态 reset value | `exported GRH reset contract PASS` |
| `AsyncArray` | split 后的两个 scalar array element | `exported GRH async-array reset PASS` |
| `AsyncPackedArray` | 保留的 16-bit packed array、非 uniform reset | `exported GRH packed async-array reset PASS` |
| `AsyncPackedArrayUniformReset` | uniform group 折成 scalar `OP_INT` 后复制为 packed zero | `exported GRH uniform packed async-array reset PASS` |

runtime 同时检查 release 不触发写、reset value 无事件变化不触发写、reset 高电平时 clock 重新采样、
复位优先以及 `had_register_write_conflict() == false`。所有产物位于
`ptmp/gsim_async_integration_20260714/`。C++17 `-Wall -Werror` syntax check、根仓库和 GSim
submodule 的 `git diff --check` 均通过。

## 结论

async-reset exporter 的局部执行 gate 已关闭，并且完整图在接入前的首诊断与实现目标一致。仍不能
宣称完整 `SimTop` executable graph 已导出：必须使用上述或更新后的 fresh binary 再跑完整图，
继续处理真实首诊断。external/DPI 尚未接入，最终仍需 GrhSIM model build 和 CoreMark 50k NEMU
difftest。

## 后续关联

- 接入 [`NO00003`](./NO00003_gsim_extmodule_dpi_abi_20260714.md) 和
  [`NO00005`](./NO00005_gsim_xiangshan_wrapper_contract_20260714.md) 的 external profile。
- 所有已知语义 gate 接入后，以 fresh binary 重跑完整 strict export。
- 最终 CoreMark 50k gate 另建记录。

## 增量更新

后续 full-graph census、勘误或回归结果只追加于此；新的 root cause 使用新记录。
