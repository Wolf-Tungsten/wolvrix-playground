---
id: NO00002
date: 2026-07-13
title: GSim executable GRH exchange for complete GrhSIM simulation
kind: plan
status: active
area: simulation
topic: gsim-grhsim-exchange
tags: [gsim, grhsim, grh-json, executable-semantics, coremark]
parents: [NO00001]
related: []
supersedes: []
---

# NO00002 GSim executable GRH exchange for complete GrhSIM simulation (2026-07-13)

> 归档编号：`NO00002`。主题导航：
> `tree/simulation/gsim-grhsim-exchange/00/000-099.md`。

## 背景

[`NO00001`](./NO00001_gsim_precoarsen_exchange_20260713.md) 建立了
`gsim.precoarsen-graph.v1`，证明完整 XiangShan PreCoarsen 图可以从 GSim 导出并由
GrhSIM 读入、完成 activity scheduling。该格式明确是 `analysisOnly` 投影：非源节点被
降为只表达依赖关系的 `kAssign`，不保留表达式、寄存器、复位、存储器、系统任务和
外部调用语义，因此不能生成语义正确的 CoreMark 仿真模型。

## 问题或目标

建立 GSim 到 GrhSIM 的可执行交换链路。GSim 导出的产物必须包含完整执行语义，能够由
Wolvrix GRH loader 直接加载，经过 GrhSIM 调度和 C++ emitter 后构建模型，并最终通过
XiangShan CoreMark difftest。

不能把成功条件缩减为图可解析、调度成功或模型可编译。任何活跃节点或表达式操作没有
精确映射时，导出必须失败并报告节点、树槽和操作类型，禁止退化为依赖占位 `kAssign`。

## 证据与方法

### 当前语义边界

GSim `PreCoarsen` 时仍保存可执行信息：

- `Node::assignTree` 保存普通连接和条件更新；
- `NODE_REG_SRC` / `NODE_REG_DST` 通过 `regNext` 配对，并保存 `clock`、`resetTree`、
  `resetCond` 和 `resetVal`；
- memory declaration/reader/writer/readwriter 保存 shape、成员端口和 `memTree`；
- `NODE_SPECIAL` 和 external node 保存 printf/assert/exit 与外部调用信息；
- `ENode::opType` 覆盖组合运算、常量、切片、动态索引、条件语句、memory 和系统操作。

最小 `ReproUsefulReset` 的 PreCoarsen dump 位于
`ptmp/gsim_exec_v2_probe_20260713/ReproUsefulReset_PreCoarsen.json`。它证明优化后仍存在
`OP_ADD`、`OP_EQ`、`OP_AND`、`OP_INT`、嵌套 `OP_WHEN`，以及三组配对寄存器；因此
翻译器应读取当前 Node/ExpTree，而不是重新解释原始 FIRRTL 文本。

GrhSIM 原生 GRH 已提供对应执行模型：组合 Operation、`kRegister` + read/write ports、
`kMemory` + read/write/fill ports、`kSystemTask` 和 `kDpicCall`。可执行交换产物采用原生
Design JSON，避免在 GrhSIM 中引入第二套解释器。

### 交换契约

新格式暂定 `gsim.executable-grh.v2`，外层继续兼容原生 GRH Design JSON：

- `graphs`、`declaredSymbols`、`tops` 使用现有 loader schema；
- 根 `format` 和 `gsim` metadata 标识 GSim 版本、输入指纹、导出 stage 与完整性统计；
- graph ports 只绑定真实 `NODE_INP` / `NODE_OUT`，寄存器读值不再伪装为 input；
- 每个可执行 op/value 保存稳定的 GSim node/ENode provenance 属性；
- 调度依赖由真实 operand/result 和状态读写端口产生，不用依赖占位操作伪造；
- 所有 symbol 在 graph 内唯一，宽度至少为 1，常量使用 GRH `constValue` 字面量。

### 分阶段语义映射

1. 组合闭环：node reference、constant、assign、arithmetic/compare/bitwise、cast、
   reduction、shift、concat、static/dynamic slice、mux/when。
2. 状态闭环：register declaration/read/write、时钟边沿、同步/异步 reset、条件写和 mask。
3. Memory 闭环：declaration、异步 read、同步 write、readwriter、mask 和写优先级。
4. Effect 闭环：printf/assert/exit、external/DPI 调用及其事件条件。
5. 全量 gate：Xi​​angShan 导出无 unsupported semantic entries，GrhSIM emit/build 成功，
   CoreMark 与 NEMU difftest 通过。

每阶段都需要正向行为测试和至少一个严格拒绝测试。小型测试的所有生成文件、构建目录和
日志均放在仓库 `ptmp/` 下。

## 结论

实现主线是从 GSim PreCoarsen `Node`/`ExpTree` 直接生成原生可执行 GRH，而不是扩展 v1
依赖投影。v1 保留为分析接口；v2 使用独立 CLI 参数和 schema，避免旧调用者误把分析
产物用于仿真。

## 后续关联

- 组合语义导出实现与最小 end-to-end gate。
- register/reset、memory、system/external 各自的增量实现和回归记录。
- XiangShan CoreMark 最终 gate 记录。

## 增量更新

后续在此追加同一实现议题的小步进展；新的实验或 gate 使用新的 `NO` 记录。

### 2026-07-13 scalar/register 严格子集

新增 `reference/gsim/src/ExecutableGrhExporter.cpp`，从 PreCoarsen `Node`/`ExpTree`
流式生成原生 GRH Design JSON。当前格式标识为 `gsim.executable-grh.v2`，支持标量组合
表达式、常量、mux/when、寄存器 read/write、posedge、同步 UInt reset、条件更新和寄存器
hold。真实顶层 port 名称和顺序保持不变；value/op symbol 使用稳定 GSim node id，并附带
provenance 属性。array/index、memory、effect、external/DPI、async reset 等未实现语义会严格
失败，不生成依赖占位操作。

构建和正式导入链路验证命令如下，所有产物均在仓库 `ptmp/` 内：

```bash
make -C reference/gsim \
  BUILD_DIR=../../ptmp/gsim_exec_exporter_build \
  build-gsim -j4

ptmp/gsim_exec_exporter_build/gsim/gsim \
  --export-executable-grh=ptmp/gsim_exec_exporter_probe/counter_gsim/Counter.exec.json \
  --dir=ptmp/gsim_exec_exporter_probe/counter_gsim \
  ptmp/gsim_exec_exporter_probe/Counter.fir

python3 scripts/wolvrix_xs_grhsim.py \
  ptmp/gsim_exec_exporter_probe/unused.f Counter \
  ptmp/gsim_exec_exporter_probe/counter_script_emit \
  ptmp/gsim_exec_exporter_probe/unused.json '' info \
  --import-gsim-executable-grh \
  ptmp/gsim_exec_exporter_probe/counter_gsim/Counter.exec.json

make -C ptmp/gsim_exec_exporter_probe/counter_script_emit CXX=clang++ -j4
ptmp/gsim_exec_exporter_probe/counter_script_emit/counter_harness
```

以上步骤全部通过。正式 driver 已验证 v2 envelope、native loader、activity-schedule 和
GrhSIM C++ emit；生成模型随后成功编译为静态库。runtime harness 输出
`counter executable-GRH semantics PASS`，覆盖同步 reset、连续 increment、enable hold、
hold 后恢复更新，以及 `had_register_write_conflict() == false`。主要 artifact：

- `ptmp/gsim_exec_exporter_probe/counter_gsim/Counter.exec.json`
- `ptmp/gsim_exec_exporter_probe/counter_script_emit/libgrhsim_Counter.a`
- `ptmp/gsim_exec_exporter_probe/counter_script_emit/counter_harness`
- `ptmp/gsim_exec_exporter_probe/counter_script_emit/activity_schedule_supernode_stats.json`

`ReproUsefulReset.exec.json` 也重新导出为 v2，并通过同一正式 import 路径和 `clang++`
生成库构建；回归产物位于 `ptmp/gsim_exec_exporter_probe/repro_script_emit_v2/`。

严格拒绝验证也通过。Memory 用例命令：

```bash
ptmp/gsim_exec_exporter_build/gsim/gsim \
  --export-executable-grh=ptmp/gsim_exec_exporter_probe/negative_memory/MemoryUnsupported.exec.json \
  --dir=ptmp/gsim_exec_exporter_probe/negative_memory \
  ptmp/gsim_exec_exporter_probe/MemoryUnsupported.fir
```

该命令 exit 1，并报告
`node id=5 name='storage' type=NODE_MEMORY line=10: backing memories require the executable-memory extension`。
Effect 用例命令：

```bash
ptmp/gsim_exec_exporter_build/gsim/gsim \
  --export-executable-grh=ptmp/gsim_exec_exporter_probe/negative_effect/EffectUnsupported.exec.json \
  --dir=ptmp/gsim_exec_exporter_probe/negative_effect \
  ptmp/gsim_exec_exporter_probe/EffectUnsupported.fir
```

该命令 exit 1，并报告
`node id=4 name='' type=NODE_SPECIAL line=10: printf/assert/exit effects require the executable-effects extension`。
两次失败均未生成目标 JSON，也未留下 `*.tmp.*`、value spool 或 op spool。

该里程碑只证明 scalar/register 子集端到端可执行，尚不代表 XiangShan CoreMark 可运行。
完整 CoreMark 仍依赖 array/dynamic index、memory/RUW、printf/assert/exit、external/DPI、
async reset，以及仿真 harness/program-memory ABI 的后续闭环。
