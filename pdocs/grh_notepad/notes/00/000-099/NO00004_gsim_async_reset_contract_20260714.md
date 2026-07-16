---
id: NO00004
date: 2026-07-14
title: GSim asynchronous-reset contract for executable GRH
kind: decision
status: active
area: simulation
topic: gsim-grhsim-exchange
tags: [gsim, grhsim, grh-json, async-reset, register, coremark]
parents: [NO00002]
related: [NO00001, NO00003]
supersedes: []
---

# NO00004 GSim asynchronous-reset contract for executable GRH (2026-07-14)

> 归档编号：`NO00004`。主题导航：
> `tree/simulation/gsim-grhsim-exchange/00/000-099.md`。

## 背景

[`NO00002`](./NO00002_gsim_executable_grh_exchange_20260713.md) 的 executable GRH
原型只覆盖单时钟寄存器。XiangShan `SimTop` 大量使用异步复位；若 exporter 只把
`OP_RESET` 降成时钟沿上的 data mux，复位在无时钟沿时不会生效，行为不等价。

本记录定义 GSim `resetTree` 到 GrhSIM `kRegisterWritePort` 的严格映射，并用独立原生 GRH
fixture 验证事件语义。它不修改 `ExecutableGrhExporter.cpp`，也不代表完整 CoreMark gate 已经
通过。

## GSim 语义来源

GSim 在 `reference/gsim/src/resetAnalysis.cpp` 中区分 `UNCERTAIN`、`ASYRESET`、
`UINTRESET` 和 `ZERO_RESET`。`Node::addUpdateTree()` 在
`reference/gsim/src/Node.cpp` 中把 reset 表示成 `OP_RESET(cond, value)`；
`clockOptimize.cpp` 将 gated-clock 条件并入寄存器 next-value，而 event clock 保留基础时钟；
`mergeNodes.cpp` 再按 reset condition 构造 `SUPER_ASYNC_RESET` 或
`SUPER_UINT_RESET`。

因此 executable GRH 必须分别保存：基础时钟事件、普通更新 data/enable、reset condition、
reset value 和 reset 类型。不能从 GSim C++ 的 `step()` 调度方式反推 RTL 事件语义；
`step()` 表示一个完整仿真周期，并不按输入 clock 的真实边沿提交寄存器。

## 映射决策

### 普通 next-value

先把已有条件赋值 lower 成 reset 之外的普通 data mux 链，fallback 为寄存器 read：

```text
normalData = mux(updateCondN, valueN,
             ... mux(updateCond0, value0, regRead))
writeData  = mux(resetCond, resetValue, normalData)
```

reset mux 必须位于最外层，使 clock 与 reset 同时上升时 reset 具有确定优先级。

### 异步复位

一个逻辑寄存器只生成一个多事件 `kRegisterWritePort`：

```text
kRegisterWritePort(
    updateCond = 1,
    nextValue  = writeData,
    mask       = all_ones,
    events     = [baseClock, resetCond],
    eventEdge  = ["posedge", "posedge"]
)
```

这与 `always @(posedge baseClock or posedge resetCond)` 一致：

- reset assertion 立即提交 reset value；release 不触发写；
- reset 高电平期间，每个 clock posedge 重新采样 reset value；
- reset value 自身变化而 clock/reset 均无边沿时，不得改写状态；
- clock 与 reset 同时上升时，外层 reset mux 保证 reset 优先；
- 派生的 1-bit reset 表达式也可直接作为 event operand，其组合值变化由 GrhSIM 分类边沿。

不得把 clock 更新和 async-reset 更新拆成两个写端口。那会为同一寄存器制造并发多写，而当前
GRH/GrhSIM 没有用端口顺序定义 reset 优先级的契约。

### 同步复位

同步复位继续只监听基础时钟：

```text
events    = [baseClock]
eventEdge = ["posedge"]
writeData = mux(resetCond, resetValue, normalData)
```

`wolvrix/lib/emit/grhsim_cpp.cpp` 已验证一个 `kRegisterWritePort` 可带多个 event operand，
`eventEdge` 数量必须等于 `operands[3:]` 数量，多个事件 guard 按 OR 触发。事件 operand 可以是
派生组合表达式。

## 严格拒绝条件

exporter 仅在以下条件全部成立时 lower reset，否则必须报错，不能退化为同步复位、普通 assign
或常量初始化：

- `resetTree` 的根必须是完整寄存器 lvalue 的 `OP_RESET(cond, value)`；
- condition lower 后必须是 1-bit logic；
- reset value 必须能按位宽、符号和 shape 精确 coerce 到寄存器类型；
- base clock、condition、value 及其全部表达式闭包必须被导出；
- 数组寄存器仅在完整 packed update/reset 已受支持时允许；
- 无法精确 lower 的 clock、condition 或 value 必须 fail closed。

这些检查要在产生部分写端口之前完成，避免失败 JSON 中残留半个寄存器实现。

## 首次 eval 的事件边界

当前 GrhSIM 第一次 `eval()` 只记录 event baseline，不凭当前高电平合成 posedge。因此模型第一次
求值时 reset 已为高，async reset 不会在该次求值立即提交；后续真实 clock posedge 仍会在
reset mux 下提交 reset value。

CoreMark 驱动包含时钟复位周期，首个真实 clock posedge 可使状态进入 reset，因而该边界不是
当前 CoreMark 链路的独立阻塞项。纯异步调用者应先以 inactive reset 做一次 baseline eval，再
assert reset；若需要“初始即高也触发”的契约，应另行修改并验证 GrhSIM runtime 初始事件策略，
不能在 exporter 中隐式特判。

## 最小行为验证

fixture、原生 JSON、harness 和生成模型位于：

```text
ptmp/gsim_async_reset_contract_20260714/
```

原生 GRH harness 覆盖：同步 active-high、直接异步 active-high、active-low `not` 表达式、
`or` reset 表达式、动态 reset value、assert/release、无事件时 reset value 变化、reset 高电平
时 clock 重新采样、clock/reset 同时上升、单写端口冲突检查以及 first-eval baseline。

复测命令：

```bash
ptmp/gsim_async_reset_contract_20260714/grh/harness
```

输出：

```text
native GRH async-reset contract PASS
```

## GSim C++ 参考实现的已知缺陷

最小 FIRRTL fixture 同时暴露出三项 GSim C++ emitter/调度缺陷；它们只作为差异证据，不是
executable GRH 应复制的行为：

1. 直接 `AsyncReset` 输入 assertion 后，`AsyncHigh` 的 q/output 仍为 `0x11`；手工
   `activateAll()` 后才变成 `0xa5`。
2. `not(reset_n)` 派生 reset assertion 会在同一 `step()` 改变内部 q，但 output 要下一次
   `step()` 才 settle 到 `0xa5`。
3. 组合 reset value 的 `AsyncOrDynamic0.cpp` 不能编译；`subReset0()` 引用了作用域外局部变量
   `reset_value`。

同步复位参考 fixture 的 `load_step2=11`、`sync_assert=a5` 正常。上述问题说明 GSim 生成 C++
并非 async-reset 交换格式的行为 oracle；映射应遵循 FIRRTL 事件语义和 GrhSIM 已验证的事件
契约。

## SimTop 影响范围

对当前生成模型 `build/xs/gsim/gsim-compile/model/SimTop1.cpp` 的 reset body census 得到三个
async-reset condition group：

| condition | reset body 中的逻辑寄存器数 |
| --- | ---: |
| `reset` | 17 |
| `cpu...reset_sync_resetSync..._raw_reset_T` | 37,527 |
| `cpu...ref_reset_sync_resetSync..._raw_reset_T` | 12 |
| 合计 | 37,556 |

主 group 包含 36,058 个 scalar 和 1,469 个 array reset。三个 group 的 reset value 合计全为
常量：31,801 个 scalar 为零、4,286 个 scalar 为非零常量，1,469 个 array 均为 zero memset；
当前 SimTop 未见动态 async-reset value。两个 `_raw_reset_T` 均来自 `pipe_reset[2]` 的
`asAsyncReset(...)`。

作为全图基线，`build/xs/gsim/gsim-compile/model/SimTop_0Final_Stats.json` 记录
`NODE_REG_SRC = 148954`、`resetTree = OP_RESET = 74142`。37,556 是最终 GSim reset body 的
实际逻辑寄存器 census，不等同于 PreCoarsen 容器级绝对计数；若需要后者，应给 GraphStats
增加 `ResetType` census 后重新生成完整 SimTop。

## 结论

当前 GSim 导出的 executable GRH JSON 不能直接运行 XiangShan CoreMark，async reset 是明确的
硬阻塞项：现有 exporter 尚未实现上述多事件寄存器写端口契约，而 SimTop 的主要 reset group
覆盖 37,527 个逻辑寄存器。将 async reset 映射为单一多事件写端口后，GrhSIM 本身具备所需的
事件能力，最小契约已经通过原生 GRH 验证。

这只关闭 reset 语义缺口，不能单独宣称 CoreMark 链路可运行。仍需合入 external/DPI、memory、
effect、array/index 等完整 exporter 支持，并完成 SimTop export、GrhSIM emit/build 与 CoreMark
NEMU difftest gate。

## 后续关联

- 在 `ExecutableGrhExporter.cpp` 中实现本记录的单多事件写端口映射和严格诊断。
- 增加 exporter 级 sync/async reset JSON fixture，随后在完整 SimTop 上核对 reset port census。
- 完成所有 executable GRH 缺口后执行 CoreMark NEMU difftest，另建 gate 记录。

## 增量更新

后续 exporter 实现或完整 CoreMark gate 使用新的 `NO` 记录；本记录保留 2026-07-14 语义基线。
