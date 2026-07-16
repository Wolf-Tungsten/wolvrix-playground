---
id: NO00005
date: 2026-07-14
title: GSim XiangShan SimJTAG and PrintCommit wrapper contract
kind: decision
status: active
area: simulation
topic: gsim-grhsim-exchange
tags: [gsim, grhsim, grh-json, extmodule, simjtag, print-commit, coremark]
parents: [NO00003]
related: [NO00002, NO00004]
supersedes: []
---

# NO00005 GSim XiangShan SimJTAG and PrintCommit wrapper contract (2026-07-14)

> 归档编号：`NO00005`。主题导航：
> `tree/simulation/gsim-grhsim-exchange/00/000-099.md`。

## 背景

[`NO00003`](./NO00003_gsim_extmodule_dpi_abi_20260714.md) 对当前 XiangShan
`SimTop` 的 external module 做了 census，但 `SimJTAG` 与 `PrintCommitIDModule` 仍只给出
未审计拒绝。本记录固定这两个模块的真实 RTL、GSim graph/adapter 和 CoreMark stub 三层契约，
避免为了通过 full-graph export 而把有状态或一次性副作用误降成普通组合调用。

本记录不修改 `ExecutableGrhExporter.cpp`，也不宣称完整 CoreMark 已通过。

## 原始 RTL 契约

### SimJTAG

`testcase/xiangshan/difftest/src/test/vsrc/common/SimJTAG.v` 在 `posedge clock` 上维护：

- 一拍延迟的 `r_reset`，使 reset release 后仍执行一拍 reset 分支；
- `tickCounterReg`，当前 `SimTop` 参数 `TICK_DELAY = 3`；
- `init_done_sticky`；
- `__jtag_TCK/TMS/TDI/TRSTn` 与 `__exit`；
- 当 `enable && init_done_sticky && tickCounterReg == 0` 时调用 `jtag_tick`；
- TDO 未 driven 时使用一次初始化的 `$random` bit。

`testcase/xiangshan/difftest/src/test/csrc/common/SimJTAG.cpp` 的 `jtag_tick` 再根据运行时
`enable_simjtag` 决定是否建立 remote-bitbang server，并把完成状态编码为
`(exit_code << 1) | 1`。因此该模块不是 defname 到单个无状态 DPI call 的映射。

### PrintCommitIDModule

`testcase/xiangshan/src/main/scala/xiangshan/backend/fu/NewCSR/CommitIDModule.scala` 内联的 RTL
只有一个 simulation-only `initial $fwrite`：每个实例在初始阶段输出一次 hart ID、40-bit commit
SHA 和 dirty bit。它没有 clock 和输出端口，但一次性时序本身是可观察副作用。

## 当前 GSim graph 已丢失的语义

### 输出 Clock 被常量化

`AST2Graph.cpp::visitExtModule` 把第一个 Clock leaf 保存到 `Node::clock`，后续 Clock leaf 不加入
`Node::member`。对 `SimJTAG` 而言，第一个 Clock 是输入 `clock`，输出 `jtag.TCK` 被改成
`NODE_OTHERS`，没有 `OP_EXT_FUNC` producer。

最小探针位于：

```text
ptmp/gsim_xs_wrapper_contract_20260714/SimJtagClockProbe.fir
```

GSim 直接报告：

```text
Warning: An external clock signal is detected. It is not supported now and treated as a constant clock signal.
node jtag$jtag$$TCK[width 1 sign 0 status=valid type=others ...]
```

`clock_probe/SimJtagClockProbe_0Init.json` 证明 `TCK` 是无 assign tree 的 `NODE_OTHERS`；生成的
`clock_probe_model/SimJtagClockProbe.h` adapter 签名为：

```cpp
void SimJTAG(int, uint8_t reset,
             uint8_t& TRSTn, uint8_t& TMS, uint8_t& TDI,
             uint8_t TDO_data, uint8_t TDO_driven,
             uint8_t enable, uint8_t init_done, uint32_t& exit);
```

签名中没有 `TCK`。生成 getter `get_tck()` 无条件返回 `0`。完整 `SimTop.h` 使用相同签名。
所以仅从当前 GSim executable graph/JSON 无法恢复原始 JTAG clock waveform；任何声称完整映射的
方案都必须在 GSim 建图时保留 output Clock 或随 JSON 携带原 wrapper，而不能在 importer 中猜测。

### initial 被改成普通重复调用

GSim 把无输出的 `PrintCommitIDModule` 保留为始终执行的 external supernode。最小模型连续调用
两次 `step()`，adapter 被调用两次：

```text
GSim PrintCommit ordinary-call probe PASS (calls=2)
```

这不等于 RTL 的一次 `initial $fwrite`。把 defname 直接变成无 event 的 `kDpicCall` 会重复副作用；
直接忽略则丢副作用。当前 graph 没有实例级 one-shot 状态，不能自行区分两者。

## Registry 决策

`ExecutableGrhExtRegistry` 新增：

- `ExternalModulePlanStatus::RequiresWrapper`：ABI 已识别，但当前 graph 不足以无损执行；
- `ExternalModuleExecutionProfile::FullFidelity`：默认模式；
- `ExternalModuleExecutionProfile::XiangShanGsimCoremarkStub`：仅显式复现现有 GSim CoreMark
  link stub。

默认模式严格校验完整当前 ABI 后：

| defname | 状态 | requiredWrapper | 原因 |
| --- | --- | --- | --- |
| `SimJTAG` | `RequiresWrapper` | `SimJTAG.v` | output `jtag.TCK` 已从 graph 丢失，且内部有时序状态和 `jtag_tick` |
| `PrintCommitIDModule` | `RequiresWrapper` | `PrintCommitIDModule.v` | graph 没有 initial/实例级 one-shot 契约 |

ABI 不匹配仍返回 `Unsupported`，不会仅凭 defname 请求错误 wrapper。校验包括参数数量/类型、clock
存在性、member 数量、顺序、suffix、方向、位宽和 scalar shape。

### 显式 CoreMark stub profile

`testcase/xiangshan/difftest/src/test/csrc/gsim/unimpl-blackbox.cpp` 是当前 GSim CoreMark 的实际
link contract，而不是完整 RTL：

- `SimJTAG`: `TRSTn=1`、`TMS=0`、`TDI=0`、`exit=0`，忽略所有输入与 `TICK_DELAY`；GSim 自身
  已把 `TCK` 固定成 0；
- `PrintCommitIDModule`: 空函数，丢弃三个输入。

只有调用者显式选择 `XiangShanGsimCoremarkStub` 时，registry 才返回 `Supported` 并生成上述
constants/ignore plan。这个 profile 可用于复现当前 GSim CoreMark 行为、解除这两个 external
node 的导出 gate，但不能用于声称 remote JTAG 或 commit-SHA 日志完整等价。

## 完整执行路径

完整语义需要在 executable exchange 中选择并验证以下路径之一：

1. 在 GSim 建图时把 external output Clock 作为有方向的 member 保留，同时区分 module event
   clock；随 JSON 保存 wrapper identity、参数和实例 identity，再把 `SimJTAG.v` 交给能够执行其
   state machine 的 backend。
2. 把 `SimJTAG.v` 明确 lower 成 GRH registers、clock/reset events 和 `jtag_tick` DPI call；必须
   differential 验证 reset delay、tick cadence、sticky init、TDO fallback、所有 JTAG outputs 与
   exit code。缺任何一项均 fail closed。
3. 为 `PrintCommitIDModule` 增加真正的 per-instance initial/one-shot effect；普通无 event
   `kDpicCall` 不足以表示 initial。若 backend 新增 initial event，需验证多实例各执行一次且格式
   与 `$fwrite(32'h80000001, ...)` 一致。

当前 JSON 不包含完成路径 1 或 2 所需的 `TCK` producer，因而 importer 侧不存在无损补救。

## 验证

Registry 独立回归：

```bash
clang++ -std=c++17 -Wall -Wextra -Werror \
  -Ireference/gsim/include \
  reference/gsim/src/ExecutableGrhExtRegistry.cpp \
  reference/gsim/test/executable-grh-ext-registry.cpp \
  -o ptmp/gsim_xs_wrapper_contract_20260714/executable-grh-ext-registry-test

ptmp/gsim_xs_wrapper_contract_20260714/executable-grh-ext-registry-test
```

输出：

```text
executable GRH ext registry PASS
```

测试覆盖两个 wrapper requirement、精确原因、显式 CoreMark constants/ignore plan，以及 malformed
direction/clock 的严格拒绝。两组生成模型行为探针输出：

```text
GSim SimJTAG CoreMark stub probe PASS
GSim PrintCommit ordinary-call probe PASS (calls=2)
```

所有 fixture、生成模型、harness 和二进制均在
`ptmp/gsim_xs_wrapper_contract_20260714/`。

## 结论

当前 GSim 导出的图不能支持完整 SimJTAG 仿真，也不能无损保留 PrintCommit 的 initial 日志；这
不是 GrhSIM importer 可独立修复的问题。默认 registry 现在能区分“已识别但必须保留 wrapper”与
“未知/畸形 ABI”，避免静默丢语义。

当前 CoreMark GSim 本来就链接 disabled/no-op stub，因此显式 compatibility profile 能精确复现
该基线并让 exporter 继续前进；它只关闭 CoreMark 当前配置的这两个 external gate。完整目标仍需
接入 external plan、关闭 memory/effect/reset 等剩余缺口，并实际通过 GrhSIM CoreMark NEMU
difftest。

## 后续关联

- exporter 默认只接受 `Supported`；遇到 `RequiresWrapper` 必须报出 wrapper 与原因。
- CoreMark driver 若采用兼容 profile，必须在产物 metadata 和日志中明确标记，不得默认为完整模式。
- 修复 GSim external Clock member 表示后，新增 SimJTAG RTL-vs-GSim-vs-GrhSIM 逐周期 differential。
- 增加 per-instance initial effect 后，再把 `PrintCommitIDModule` 从 `RequiresWrapper` 改为可执行计划。

## 增量更新

后续 wrapper 实现或完整 CoreMark gate 使用新的 `NO` 记录；本记录保留 2026-07-14 契约基线。
