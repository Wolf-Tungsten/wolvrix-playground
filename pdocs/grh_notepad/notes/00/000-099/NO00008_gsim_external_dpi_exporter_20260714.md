---
id: NO00008
date: 2026-07-14
title: GSim executable GRH external and DPI exporter integration
kind: implementation
status: active
area: simulation
topic: gsim-grhsim-exchange
tags: [gsim, grhsim, grh-json, extmodule, dpi, activity-schedule, coremark]
parents: [NO00003, NO00005, NO00007]
related: [NO00002, NO00006]
supersedes: []
---

# NO00008 GSim executable GRH external and DPI exporter integration (2026-07-14)

> 归档编号：`NO00008`。主题导航：
> `tree/simulation/gsim-grhsim-exchange/00/000-099.md`。

## 背景

[`NO00003`](./NO00003_gsim_extmodule_dpi_abi_20260714.md) 已固定 XiangShan helper 的
严格 ABI registry，[`NO00005`](./NO00005_gsim_xiangshan_wrapper_contract_20260714.md) 已把
CoreMark compatibility stub 与 full-fidelity wrapper requirement 分离。此前 registry 尚未接入
PreCoarsen executable exporter，也没有证明 external call 在 GrhSIM activity schedule 中保持
实例内时序。

## 实现

`reference/gsim/src/ExecutableGrhExporter.cpp` 现完成 external lowering：

- 从 live `NODE_EXT` 及有序 member 构造 ABI，clock 作为 GSim 单独捕获、无 parent 的
  `NODE_EXT_IN` 验证和 lowering；
- `NODE_EXT_IN` 按普通 assignment 计算，`NODE_EXT` 不创建无意义 value，`NODE_EXT_OUT`
  只由 DPI return/output argument 或显式 stub constant 定义；
- 接受 GSim 在宽 external output marker 外包裹的 canonical unary cast，再严格确认最终
  `OP_EXT_FUNC` 指向所属 root；
- 生成完整 `kDpicImport` signature、去重并拒绝同 symbol 冲突 signature；
- 生成 condition-first、input-args、event-last 的 `kDpicCall`，result 顺序为 return-first、
  output-args，保留 element-0-LSB array flatten、ABI width/sign conversion 和 inactive-return mux；
- 每个 parameter/member 必须恰好由 call、constant 或 ignore plan 消费，所有 output 恰好一个
  writer；unknown/malformed external fail closed；
- call 写入共同的 `gsim.external_instance_group` 和连续 ordinal，并标记 side effect；
- CLI 显示 profile；v2 root、`gsim` metadata 和 graph attrs 保存 stage/boundary、GSim version、
  build date、输入路径/字节数、execution profile 以及 node/value/op/external/import 统计。

`wolvrix/lib/transform/activity_schedule.cpp` 现验证 external group/ordinal 成对存在、类型正确、
非空、非负且从 0 连续无重复；同一 instance 的 calls 构成一个 ordered、indivisible compute
node。所有 call operands（包括 event clock）都能激活该 node；DPI call 无论 result 是否被使用
均按固有 side effect materialize。declared-cut、cycle repair 和 oversize split 均不能拆开该 node。

`scripts/wolvrix_xs_grhsim.py` 的 v2 import guard 现在要求：第一 graph symbol 等于请求 top；root
和 `gsim` metadata 的 format/stage/boundary/analysisOnly/profile 一致；profile 只能是
`full-fidelity` 或 `xiangshan-gsim-coremark-stub`。选择 stub 时日志明确警告 SimJTAG 与
PrintCommitIDModule 使用 compatibility stub。

## External RAM 时序契约

真实 GSim adapter 对 `Mem1R1WHelper` 的单次 step 顺序是 read 后 write。GrhSIM 因此不在 write
成功后立即重跑同轮 read；那会错误地产生 write-through。分组 node 的 write clock operand 使
每次 clock transition 都激活整个 instance：posedge 时先观察旧数据再写，下一次外层 eval（正常
为 falling edge）以稳定地址重新读取新数据。这一 read-before-write、next-eval refresh 行为已由
runtime fixture 固定。

## 验证

fresh GSim binary：

```text
ptmp/gsim_external_integration_20260714/build/gsim/gsim
sha256=7418958bc670ae19ebea1ca30368f71d2e1b63cc27473105905be42f147db49e
```

组合 fixture `ExternalProbe.fir` 覆盖 DiffExt scalar/array、Mem1R1W、Flash、SDCard、SimJTAG 与
PrintCommit。默认 profile exit 1，准确报告 SimJTAG 需要 `SimJTAG.v`，且没有安装目标 JSON；
显式 `--executable-grh-profile=xiangshan-gsim-coremark-stub` 成功导出：

```text
externalInstanceCount=6
externalCallCount=6
dpiImportCount=6
executionProfile=xiangshan-gsim-coremark-stub
```

正向 artifact：

```text
ptmp/gsim_external_integration_20260714/stub_export/ExternalProbe.exec.json
sha256=d90a15194c9ce2c4d09f052ceac98481e5629ce49717357cdeaa97dcb3e76673
```

该 JSON 已完成严格 import guard、LoadJson、`activity-schedule`、GrhSIM C++ emit 和 archive build。
runtime harness 检查：

- DiffExt 12-bit scalar coercion、array element 0/1 的 LSB-first 顺序及 posedge gating；
- RAM disabled read 为 0、write 只在 posedge、同 eval read-before-write、下一 eval stable-address
  refresh；
- Flash posedge output argument、SD setaddr posedge/read negedge；
- SimJTAG stub constants与 PrintCommit no-op；
- ignored `io.valid` 单独变化不触发 DPI，stable clock 不重复 edge call。

输出：

```text
exported GRH external/DPI semantics PASS
```

此外 `transform-activity-schedule` focused regression、external registry regression、import guard
suite、C++17 `-Wall -Wextra -Werror` exporter syntax check、三个 worktree 的 `diff --check` 均通过。
所有局部产物位于 `ptmp/gsim_external_integration_20260714/` 与
`ptmp/gsim_import_guard_test_20260714/`。

## 结论与后续

External/DPI 局部 executable gate 已闭环，但完整 XiangShan 尚未重新导出。下一步必须使用上述
fresh binary 和显式 CoreMark stub profile 跑完整 `SimTop` strict export，按新的真实首诊断继续
修复；最终仍以完整 GrhSIM model build 和 CoreMark `-C 50000` NEMU difftest 为唯一完成 gate。

## 增量更新

后续完整图诊断和最终 gate 使用新的 `NO` 记录；本文保留 external/DPI 局部闭环证据。
