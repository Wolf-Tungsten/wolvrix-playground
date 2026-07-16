---
id: NO00006
date: 2026-07-14
title: GSim executable GRH recovery state and remaining semantic gates
kind: diagnosis
status: active
area: simulation
topic: gsim-grhsim-exchange
tags: [gsim, grhsim, grh-json, recovery, xiangshan, coremark]
parents: [NO00002]
related: [NO00003, NO00004, NO00005]
supersedes: []
---

# NO00006 GSim executable GRH recovery state and remaining semantic gates (2026-07-14)

> 归档编号：`NO00006`。主题导航：
> `tree/simulation/gsim-grhsim-exchange/00/000-099.md`。

## 背景

上一轮 Codex 会话在完整 XiangShan `SimTop` 严格导出期间异常终止。本记录从工作区、生成
产物和日志恢复权威现场，避免把未完成运行当作 exporter 失败，并固定继续推进的验证边界。

## 恢复证据

`gsim.precoarsen-graph.v1` 的完整静态交换证据仍由
[`NO00001`](./NO00001_gsim_precoarsen_exchange_20260713.md) 保存；它已完成全规模
LoadJson 和 `activity-schedule`，但明确没有运行 workload。

`gsim.executable-grh.v2` 在 [`NO00002`](./NO00002_gsim_executable_grh_exchange_20260713.md)
记录的 scalar/register 基础上，当前源码已经增加：

- packed array、静态/动态 index 与 `OP_BITS_NOSHIFT` lowering；
- 原生 memory declaration/read/write，read latency 0/1，`old`/`new` RUW 和 aggregate mask；
- effect event clock 在 AST 建图、clock optimize 和 graph census 中的保留；
- effect 严格解析器与 XiangShan external-module ABI registry。

已恢复并复核的行为产物包括：

- `ptmp/gsim_exec_array_stage_20260714/` 的 array/index 与 bits-no-shift harness；
- `ptmp/gsim_exec_integrated_20260714/memory/{new,old,array}/` 的三个 memory harness；
- `ptmp/gsim_effects_contract_20260714/executable-grh-effects-test` 和 native GrhSIM effect model；
- `ptmp/gsim_xs_wrapper_contract_20260714/executable-grh-ext-registry-test`；
- `ptmp/gsim_async_reset_contract_20260714/grh/harness`。

这些产物分别证明局部契约，不能替代完整 executable exporter、emit/build 或 CoreMark gate。

## 中断运行判定

两个完整 `SimTop` 日志分别是：

```text
ptmp/gsim_exec_integrated_20260714/full/strict-export.log
ptmp/gsim_effects_contract_20260714/simtop_census/run.log
```

前者止于 `PatternDetect`，后者止于 `CommonExpr = 83032 ms`。恢复时没有对应存活进程，日志
没有 `ERROR`、exit status、PreCoarsen 或 executable-export 记录，也没有生成目标 JSON。因此
结论是运行随会话中断而终止，尚未进入 exporter；当前没有可引用的完整图首个拒绝诊断。

## 剩余语义 gate

当前 `ExecutableGrhExporter.cpp` 尚未消费已经存在的三个契约：

1. `ASYRESET` 仍在 prepare 阶段严格拒绝；完整 SimTop census 有 37,556 个异步复位寄存器。
2. `NODE_SPECIAL` 仍未调用 `resolveExecutableGrhEffect` 并生成 `kSystemTask`。
3. `NODE_EXT*` 仍未调用 `resolveKnownXiangShanExternalModule` 并生成
   `kDpicImport`/`kDpicCall`。`SimJTAG` 与 `PrintCommitIDModule` 只有显式
   `XiangShanGsimCoremarkStub` profile 才能精确复现当前 GSim CoreMark link stub。

继续推进必须逐项完成小 fixture 的 JSON load、activity schedule、GrhSIM emit/build 和 runtime
行为验证，然后完成一次不中断的 full strict export，以真实首个 diagnostic 驱动剩余修复。

## 验收边界

最终成功条件保持不变：完整 XiangShan executable GRH 在 GSim 优化后、coarsen 前导出，
由 GrhSIM 在 `activity-schedule` 前导入，生成模型可构建，并通过 CoreMark 50k NEMU difftest。
图可解析、局部 harness 通过或 activity schedule 成功都不是最终替代条件。

## 增量更新

后续每完成一个语义 gate 或得到新的 full-graph 首诊断，在本记录追加时间、命令、产物和结论；
最终 CoreMark gate 另建独立记录。

## 增量更新 2026-07-14 08:53：effect gate 接入及 full-graph 首诊断

恢复后确认上一轮会话在崩溃前已经把 `ExecutableGrhEffects` 接入
`ExecutableGrhExporter.cpp`：prepare 阶段严格调用 `resolveExecutableGrhEffect`，lowering
阶段把 printf/assert/exit 分别生成带 `posedge` event 的 `kSystemTask` `fwrite`、`fatal` 和
`finish`。权威局部产物位于 `ptmp/gsim_effects_integration_20260714/`：

- `EffectProbe.exec.json` 已由 Wolvrix LoadJson、`activity-schedule` 和 GrhSIM C++ emit 消费；
- `grhsim_model/libgrhsim_EffectProbe.a` 与 `effect_probe` 构建成功；
- 2026-07-14 08:53 复跑 harness 得到 `print_rc=0`，stderr 精确输出两次
  `print d=65 x=41 c=A`；`exit_rc=7`；`assert_rc=1` 且 stderr 为
  `[fatal] assert failed`。这关闭的是局部 effect 行为 gate，不是完整 CoreMark gate。

随后已有一次完整 `SimTop` strict export 运行完成到 exporter。命令和日志为：

```bash
/usr/bin/time -v ptmp/gsim_exec_integrated_20260714/build/gsim/gsim \
  --export-executable-grh=ptmp/gsim_exec_recovery_20260714/full/gsim/SimTop.exec.json \
  --stop-after-stage=PreCoarsen \
  --dir=ptmp/gsim_exec_recovery_20260714/full/gsim \
  build/xs/rtl/rtl/SimTop.fir \
  >ptmp/gsim_exec_recovery_20260714/full/strict-export.log 2>&1
```

运行耗时 9:34.97、峰值 RSS 98,527,688 KiB，并得到当前权威首诊断：

```text
[ExecutableGrhExport] ERROR: node id=37219
name='cpu$l_soc$socMisc$buffers$nodeOut_a_q$MPORT$$opcode'
type=NODE_WRITER line=831984: malformed memory port memTree
```

因此下一步不是直接等待 async-reset/external 拒绝，而是先审计 GSim 在 PreCoarsen 上该
`NODE_WRITER` 的真实 `memTree` 形状，修正 exporter 对完整图 memory port 的过窄假设；修正后再跑
full strict export 取得下一个真实诊断。async reset 和 external/DPI 仍保持未关闭状态。

### 勘误：08:13 full run 的 binary provenance

上节“随后”只表示日志生成时间晚于 effect 局部产物，不能推断该 full run 已包含 effect 接入。
08:13 日志中的命令实际使用
`ptmp/gsim_exec_integrated_20260714/build/gsim/gsim`（mtime 00:55:31），早于
08:07 的 effect exporter 修改；因此该运行只证明 memory 首诊断，不证明包含 effect 的完整图已经
运行。后续 full gate 必须使用 fresh rebuild，并记录 binary 路径和 mtime。

### infer-mport writer root cause、修复和局部执行 gate

失败节点对应 FIR `Queue2_TLBundleA` 中：

```firrtl
when do_enq :
  infer mport MPORT = ram[enq_ptr_value], clock
  connect MPORT, io.enq.bits
```

源码审计确认这不是损坏的图：`visitChirrtlPort` 为 infer port 建立地址描述
`OP_INFER_MEM(addr)`；`whenConnect` 仅把 duplicate 改成 `OP_WRITE_MEM(addr, data)` 放入
assign tree，并把 port 重标成 `NODE_WRITER`，原 `memTree` 按设计仍是 `OP_INFER_MEM`。
exporter 误要求所有 `NODE_WRITER.memTree` 都是 `OP_WRITE_MEM`，所以在任何只写 infer mport
上都会误拒绝。

最小复现保存在 `ptmp/gsim_exec_infer_mport_20260714/InferWriter.fir`。修复前 9-node 图稳定得到：

```text
[ExecutableGrhExport] ERROR: node id=9 name='writePort'
type=NODE_WRITER line=14: malformed memory port memTree
```

`ExecutableGrhExporter.cpp` 现允许 `NODE_WRITER` 的地址描述 root 为 `OP_WRITE_MEM` 或
`OP_INFER_MEM`；实际写 action 仍在 `appendMemoryWrite` 中严格要求
`OP_WRITE_MEM(addr, data)`，没有放宽写语义。fresh incremental build 为
`ptmp/gsim_effects_contract_20260714/build/gsim/gsim`。

修复后的同一最小图完成以下完整局部链路：

1. executable export 生成 `after/InferWriter.exec.json`；
2. Wolvrix LoadJson 后在 activity-schedule 前导入，统计为 7 个初始 op，最终 2 个 supernode；
3. GrhSIM emit/build 生成 `grhsim/libgrhsim_InferWriter.a`；
4. `infer_writer_harness` 验证两个地址的写入/组合读回，输出
   `infer mport writer semantics PASS`，exit 0。

这关闭了当前首诊断的局部语义 gate；仍须用 fresh binary 重跑完整 strict export 取得下一条
真实诊断。
