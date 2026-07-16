---
id: NO00003
date: 2026-07-14
title: GSim external-module DPI ABI mapping for executable GRH
kind: implementation
status: active
area: simulation
topic: gsim-grhsim-exchange
tags: [gsim, grhsim, grh-json, extmodule, dpi, coremark]
parents: [NO00002]
related: [NO00001]
supersedes: []
---

# NO00003 GSim external-module DPI ABI mapping for executable GRH (2026-07-14)

> 归档编号：`NO00003`。主题导航：
> `tree/simulation/gsim-grhsim-exchange/00/000-099.md`。

## 背景

[`NO00002`](./NO00002_gsim_executable_grh_exchange_20260713.md) 的 scalar/register
子集能够端到端执行，但当前 `ExecutableGrhExporter.cpp` 仍在 `NODE_EXT`、
`NODE_EXT_IN`、`NODE_EXT_OUT` 和 `OP_EXT_FUNC` 上严格失败。XiangShan CoreMark 依赖
program memory 和 difftest DPI，因此不能把 GSim 的 external node 降成普通 assign，也不能
直接把 FIRRTL `defname` 当作任意 C 符号调用。

## 问题或目标

审计当前 XiangShan `SimTop` 中 GSim external module 的真实 ABI，建立一个严格注册表：

- 已审计 helper 映射为 GrhSIM `kDpicImport` / `kDpicCall` 计划；
- 顺序、方向、宽度、数组 shape、参数和 clock 不匹配时拒绝；
- 未审计 helper fail closed；
- 明确区分可直接映射的 DPI、应保留 RTL wrapper 的模块和已由 GSim 内联的逻辑。

## 证据与方法

### GSim external ABI

实现证据位于 `reference/gsim/src/AST2Graph.cpp`、`instsGenerator.cpp` 和
`cppEmitter.cpp`：

- link name 使用 extmodule `defname`，缺失时才回退到模块名；
- integer/string parameter 排在所有 port 参数之前；
- clock leaf 不进入有序 member 列表，仅第一个 clock 保存在 `Node::clock`；
- aggregate leaf 保持 FIRRTL field 顺序，flip 决定 `NODE_EXT_IN` / `NODE_EXT_OUT`；
- input array 按线性元素序号展开，output array 当前会触发 `TODO()`；
- external supernode 始终 active，GSim 每轮调用 defname adapter。

生成模型 `build/xs/gsim/gsim-compile/model/SimTop.h` 和 `SimTop296.cpp` 进一步证明
`DiffExtRefillEvent.io.data[8]` 的 C++ ABI 顺序为 `data[0]` 到 `data[7]`。注册表因此在
`DpiValueSource` 中同时保存 member index 和 element index，不能只接受标量 payload。

### 当前 XiangShan census

对 `build/xs/rtl/rtl/SimTop.fir` 的全部 521 个 `defname` 统计如下：

| defname 类别 | 数量 | 处理 |
| --- | ---: | --- |
| `ClockGate` | 410 | GSim 在 AST2Graph 中降为组合 `Q = CK & (E | TE)`，不是 DPI |
| `DiffExt*` | 103 | 已审计通用 wrapper ABI |
| `Mem1R1WHelper` | 4 | 已审计 RAM DPI ABI |
| `FlashHelper` | 1 | 已审计 flash DPI ABI |
| `SDCardHelper` | 1 | 已审计 SD DPI ABI |
| `SimJTAG` | 1 | 不可直接映射，必须保留 wrapper state machine |
| `PrintCommitIDModule` | 1 | side-effect ABI 未审计，严格拒绝 |

当前 `SimTop` 不含 `imsic_csr_top` extmodule；IMSIC 是可综合 RTL。注册表仍对该历史 GSim
stub 给出明确拒绝原因。

### 已审计映射

| GSim defname | GrhSIM 计划 | 条件与事件 |
| --- | --- | --- |
| `Mem1R1WHelper` | `difftest_ram_read` 返回 `r.data`；`difftest_ram_write(index,data,mask)`；`r.async = 1`；忽略 `RAM_SIZE` | read 为异步组合调用；write 为 `posedge clock`；分别受 `r.enable` / `w.enable` 控制 |
| `DiffExtFoo` | `v_difftest_Foo(payload...)`；input array 按 GSim 线性顺序展开 | `posedge clock` 且仅受 `enable` 控制；`io.valid` 不传入 |
| `FlashHelper` | `flash_read(addr, &data)` | `posedge clock && r.en` |
| `SDCardHelper` | `sd_setaddr(addr)`；`sd_read(&data)` | setaddr 为 `posedge clock && io.setAddr`；read 为 `negedge clock && io.ren` |

`build/xs/rtl/rtl/DiffExtInstrCommit.v` 明确写成 `if (enable)
v_difftest_InstrCommit(...)`，其 payload 不含 `io.valid`。生成的 GSim adapter 目标代码也只检查
第一参数，因此把条件写成 `enable && io.valid` 会改变 difftest 行为。

`Mem1R1WHelper` 的 GSim 分支是异步 read：禁用时 `r.data = 0`，启用时调用
`difftest_ram_read`。注册表用 `inactiveReturnLiteral = 64'b0` 显式保存该默认值，防止 GrhSIM
在条件为假时错误保留上次读值。

### 实现与回归

新增：

- `reference/gsim/include/ExecutableGrhExtRegistry.h`
- `reference/gsim/src/ExecutableGrhExtRegistry.cpp`
- `reference/gsim/test/executable-grh-ext-registry.cpp`

独立回归命令和产物均位于仓库内：

```bash
clang++ -std=c++17 -Wall -Wextra -Werror \
  -Ireference/gsim/include \
  reference/gsim/src/ExecutableGrhExtRegistry.cpp \
  reference/gsim/test/executable-grh-ext-registry.cpp \
  -o ptmp/gsim_ext_registry_test_20260714/executable-grh-ext-registry-test

ptmp/gsim_ext_registry_test_20260714/executable-grh-ext-registry-test
```

输出：

```text
executable GRH ext registry PASS
```

测试覆盖四类正向映射、DPI width bucket、DiffExt array 展平顺序、RAM disabled-read 默认值，
以及 unknown helper、`SimJTAG`、错误 member direction、空 clock 名和非法 array shape 的
严格拒绝。`git -C reference/gsim diff --check` 通过。

## 结论

目前 GSim 导出的 executable GRH JSON 仍不能直接运行 XiangShan CoreMark：external/DPI
注册表已经准备好，但尚未接入 exporter；当前 exporter 会在 external node 上明确报错。即使
完成接入，仍需关闭 memory、effect、其余 array/index 与 reset 等全量导出缺口，并实际完成
GrhSIM emit/build 和 CoreMark NEMU difftest，才能宣称链路可运行。

exporter 的接入契约是：从 `NODE_EXT` 构造 `ExternalModuleAbi`，调用
`resolveKnownXiangShanExternalModule`，按 plan 生成去重的 `kDpicImport`、带 condition/event
的 `kDpicCall`、输出常量和 inactive return mux；所有 parameter/member 必须被 call、constant
或 ignore 集合消费。unsupported plan 或未消费 ABI 项均使导出失败。

## 后续关联

- 将注册表接入 `ExecutableGrhExporter.cpp`，增加最小 extmodule JSON/load/emit/runtime 测试。
- 为 `SimJTAG` 保留原 RTL wrapper 或实现经过行为对照的等价 state machine。
- 审计 `PrintCommitIDModule` 是否可安全忽略，未证明前保持 fail closed。
- 在完整 `SimTop` 上执行 export、GrhSIM emit/build 和 CoreMark difftest gate。

## 增量更新

后续行为变化或完整 gate 使用新的 `NO` 记录；本记录保留 2026-07-14 ABI 审计基线。
