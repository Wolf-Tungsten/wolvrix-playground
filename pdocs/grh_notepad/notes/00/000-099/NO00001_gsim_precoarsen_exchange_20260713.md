---
id: NO00001
date: 2026-07-13
title: GSim pre-coarsen graph exchange for GrhSIM scheduling analysis
kind: implementation
status: active
area: simulation
topic: gsim-grhsim-exchange
tags: [gsim, grhsim, activity-schedule, graph-exchange, xiangshan]
parents: []
related: []
supersedes: []
---

# NO00001 GSim pre-coarsen graph exchange for GrhSIM scheduling analysis (2026-07-13)

> 归档编号：`NO00001`。主题导航：[simulation / gsim-grhsim-exchange](../../../tree/simulation/gsim-grhsim-exchange/00/000-099.md)。

## 背景

在同一台 AMD Ryzen 9950X 上运行 XiangShan CoreMark 50k 时，GSim 与 GrhSIM
仍有明显性能差距。两条链路各自完成优化和粗化，现有静态统计只能在粗粒度
supernode 指标上对照，无法将 GSim 的粗化输入直接交给 GrhSIM 的
`activity-schedule` 复算。

GSim 的准确边界是 `graphPartition()` 内的 `orderAllNodes()` 之后、
`graphCoarsen()` 之前。GrhSIM 的生产驱动边界是 `reg-to-mem` 后、
`activity-schedule` 前；该处已经支持通过 `Session.read_json_file` 装载完整
GRH JSON。

## 目标

建立一个可重放的交换链路：

1. GSim 在 pre-coarsen 边界导出优化后的 Node 依赖图。
2. 产物使用版本化的 `gsim.precoarsen-graph.v1` 格式，并兼容 Wolvrix GRH JSON
   loader。
3. GrhSIM 驱动在 `activity-schedule` 前装载该图，并在同一调度器上生成
   compute-node、coarsen、DP 和最终 supernode 统计。

## 设计边界

首版是 **结构投影**，不是可执行设计交换：

- 每个仍有效的 GSim Node 保留稳定 node id、name、type、width、signed、topo position
  和依赖关系。
- 无前驱 Node 投影为 GRH 输入 value；内部 Node 投影为带 GSim provenance attribute
  的 `kAssign` dependency operation；终端 Node 投影为输出 port。
- 投影图允许 `activity-schedule` 的 compute/coarsen/DP 路径复算 GSim 的优化后依赖
  图，但不携带 GSim 的寄存器、存储器、表达式、事件和外部调用的完整可执行语义。
- 根 metadata 必须含 `format = gsim.precoarsen-graph.v1`、`stage = pre-coarsen` 和
  `analysisOnly = true`。导入驱动强制在 `activity-schedule` 后停止，禁止把该投影交给
  GrhSIM C++ emitter。

这一区分是必要的：将 debug JSON 或 dependency projection 冒充可执行 GRH 设计会在
状态边界、memory 端口和 event 语义上产生无效对齐。

## 实现记录

### 2026-07-13 初始接入

`scripts/wolvrix_xs_grhsim.py` 新增 `--import-gsim-precoarsen` 与环境变量
`WOLVRIX_XS_GRHSIM_IMPORT_GSIM_PRECOARSEN`。

启用导入时，驱动会：

1. 校验 artifact 的 format、stage、analysis-only 标识、目标 graph 和 top。
2. 跳过 `read_sv`、pre-schedule transforms、`reg-to-mem` 和 checkpoint resume。
3. 用既有 `Session.read_json_file(..., out_design="design.main")` 装载投影。
4. 运行原有 `activity-schedule` 和 supernode 统计输出。
5. 要求 `WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1`，避免进入 emitter。

这使导入发生在 `activity-schedule` 之前，而不引入第二套 JSON parser 或依赖不稳定的
numeric `OperationId` 作为外部 ABI。

## 验证

用一个四 value、两 `kAssign` 的 `gsim.precoarsen-graph.v1` 最小投影验证：

```bash
WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1 \
python3 scripts/wolvrix_xs_grhsim.py /dev/null projection_smoke ptmp/gsim_precoarsen_exchange/smoke_out '' /dev/null info \
  --import-gsim-precoarsen ptmp/gsim_precoarsen_exchange/gsim_precoarsen_projection_smoke.json
```

结果：GRH JSON 加载、`activity-schedule`、session export 和
`activity_schedule_supernode_stats.json` 均成功；两条 projected `kAssign` 被归入一个
compute supernode。该验证只证明交换投影可被调度，不证明 XiangShan 语义或性能。

## 后续关联

- GSim 导出端仍需在 `orderAllNodes()` 后、`graphCoarsen()` 前实现 artifact 写出，并由
  小 FIR fixture 覆盖 schema 与边界。
- 顶层 Makefile 需要提供 GSim 导出和 GrhSIM analysis-only 导入的可复现 XiangShan
  target。
- 后续若要让导入图成为真正的 schedule seed，必须在 GrhSIM
  `buildComputeNodeRewrite()` 后、`materializeComputeNodeSchedule()` 前建立 provenance
  mapping，并显式处理 source clone、sink/commit、state 和 memory 语义；不能复用本投影
  直接发射。

## 增量更新 2026-07-13：导出端和分析闭环落地

上节“后续关联”记录的是初始导入探针完成时的状态。本次增量已经完成其中的 GSim
导出端和顶层可复现入口；schedule-seed 与可执行语义仍不在首版范围内。

### GSim 导出边界与命令

GSim 新增：

```text
--export-precoarsen-grh <path>
```

导出调用位于 `graph::graphPartition()` 的 `orderAllNodes()` 之后、
`graphCoarsen()` 之前。`--stop-after-stage=PreCoarsen` 会在 artifact 写完后立即退出，
不会进入 GSim coarsen、partition 或 C++ emission。未设置导出参数和 stop stage 时，原有
GSim 路径不变。

投影仅收集 `sortedSuper` 中仍为 `VALID_NODE` 的节点，按 GSim topo order 和 node id
稳定排序。为了适配 XiangShan 约数百万节点的规模，导出器只保留节点指针集合，并复用
一份边 scratch；它不会为全部节点同时保留 `prev` / `depPrev` 的复制向量。

### `gsim.precoarsen-graph.v1` 映射

artifact 同时是版本化交换格式和 Wolvrix LoadJson 可装载的 GRH JSON：

- 根字段固定为 `format = gsim.precoarsen-graph.v1`、`stage = pre-coarsen`、
  `analysisOnly = true`；`gsim.boundary = PreCoarsen` 记录源码中的精确 stage 名。
- 每个 GSim 节点对应 `gsim.v.<node-id>` value。没有有效 `depPrev` 的节点成为 input
  port；其余节点对应一个 `gsim.assign.<node-id>` `kAssign` operation。
- `kAssign` operands 使用完整 `depPrev`，因此 GrhSIM 看到的是 GSim 调度所依赖的 DAG；
  原始数据边 `prev` 和完整依赖边分别保存在 `gsim.data_input_ids`、
  `gsim.dependency_input_ids` attributes 中。
- operation attributes 还保留 node name/type/status/width/signed/used-bit、全局 topo order、
  supernode id/order 和源码行，可由 LoadJson 后的 session/store 路径继续读取。
- 终端节点成为 output port。一个节点若同时是 source 和 terminal，则增加带
  `projection.role = terminal_proxy_*` 的 value/assign proxy，以满足 GRH 不允许同一 value
  同时作为 input 和 output 的 invariant。

这是调度结构投影，不是表达式等价翻译。每个非 source GSim 节点用一个 `kAssign`
承载依赖，不能据此比较指令语义，也不能交给 GrhSIM emitter。

### GrhSIM 导入与规模约束

`scripts/wolvrix_xs_grhsim.py` 在导入路径中执行以下顺序：

```text
bounded envelope validation
  -> Session.read_json_file
  -> activity-schedule
  -> compute DAG / supernode stats
  -> mandatory stop
```

它不会执行 `read_sv`、pre-schedule transforms、`reg-to-mem` 或 `stats`。导入与两个
checkpoint resume 模式互斥，并强制
`WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1`。

schema guard 只读取 artifact 的前 4 MiB 和末尾 1 MiB，解析根 metadata、首个 graph
symbol 和 `tops`；完整图只由原生 LoadJson 解析一次。这样避免在 XiangShan 大图上先
构造一份 Python JSON object，再由 C++ 重复解析造成的峰值内存和时间开销。

### 顶层入口与产物位置

在已有 XiangShan FIR、GSim binary 和可导入的 Wolvrix Python binding 基础上：

```bash
make xs_gsim_precoarsen_export
make xs_gsim_grhsim_alignment
```

第二个 target 串联导出和 analysis-only 导入。它不自动重装 Python binding，也不隐式
生成 FIR 或重建 GSim；缺少前置产物时会直接报错。新 target 的 JSON、日志、compute DAG、
supernode stats 和 `TMPDIR` 默认全部位于：

```text
ptmp/gsim_precoarsen_exchange/
```

### 小 FIR 端到端证据

使用 `reference/gsim/test/repro-usefulreset.fir` 实际运行 GSim 到 `PreCoarsen`：

- 18 个有效 GSim nodes；20 条 data edges；22 条 dependency edges；8 个 terminals。
- artifact 含 20 个 values（其中 2 个 source-terminal proxies）和 13 个 `kAssign` ops。
- `Session.read_json_file` 成功；导入日志明确显示跳过 `reg-to-mem` 和 `stats`。
- `activity-schedule` 成功，并导出 13-node / 7-edge compute-op DAG 和 supernode stats。
- 未设置 mandatory stop 的负例在创建输出目录和进入 emitter 前失败。
- 当前 GSim 源码在 `ptmp/gsim_precoarsen_build_20260713/` fresh build 成功；不带新参数的
  原有 `fir-tests` 仍完成 graph partition 和 C++ emission。
- LoadJson 后再 StoreJson 保留全部 13 个 ops，并保留 11 个真实节点 op 上的
  `gsim.node_id`、data-input 和 dependency-input attributes。

复测产物位于 `ptmp/gsim_precoarsen_e2e_20260713/`。这些数据证明交换边界、schema、
LoadJson 和调度闭环成立；XiangShan 规模结果单独记录，不能由小 fixture 外推。

### XiangShan 全规模证据

使用现有 `build/xs/rtl/rtl/SimTop.fir`（1,671,325,062 bytes）完成了真实
PreCoarsen 导出和 GrhSIM analysis-only 导入。结果如下：

- GSim 导出 2,708,070 valid nodes、4,902,060 data edges、5,351,922 dependency
  edges、158,895 terminals，其中 109 个 source-terminal proxies。
- `SimTop_precoarsen_grh.json` 为 6,625,854,819 bytes。bounded envelope 校验约
  4.4 ms，没有解析完整图。
- 原生 LoadJson 得到 2,708,179 values、2,557,740 ops、150,439 input ports、
  158,895 output ports；JSON parse 为 18.1 s，LoadJson 内部总计 66.1 s，驱动观测
  77.6 s。
- `activity-schedule` 的 op DAG 有 2,557,740 nodes 和 4,263,523 edges；随后建立
  453,321 compute nodes，coarsen 后得到 113,444 clusters，并 materialize 为 28,863
  compute supernodes。
- 最终 supernode DAG 有 175,779 edges；每个 supernode 最多 108 ops，median 96，
  p99 108。`activity-schedule` 为 63.7 s，导入到 mandatory stop 的驱动总计
  141.3 s。
- `/usr/bin/time -v` 记录 wall time 2:21.99、maximum RSS 61,470,640 KiB、swap 0、
  exit status 0。
- 输出的 `wolvrix.compute-op-dag.v1` 为 678,924,601 bytes，连同 supernode stats、
  import log 和 time report 位于
  `ptmp/gsim_precoarsen_xs_20260713/grhsim/`；GSim 原图和导出日志位于相邻的
  `gsim/`。

这次验证使用的是 CoreMark 50k 对比所对应的同一 XiangShan 静态设计，但没有运行
CoreMark workload：首版投影被刻意限制为 analysis-only。它现在提供的是可供两侧
coarsen 输入、compute DAG 和 supernode 形状做微观比较的共同静态边界，而不是第三条
可执行仿真链路。
