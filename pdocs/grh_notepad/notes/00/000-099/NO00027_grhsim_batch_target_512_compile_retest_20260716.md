---
id: NO00027
date: 2026-07-16
title: GrhSIM batch target 512 compile-time diagnosis and XiangShan retest
kind: experiment
status: active
area: simulation
topic: gsim-grhsim-exchange
tags: [gsim, grhsim, activity-schedule, codegen, clang, gvn, compile-time, batching, xiangshan]
parents: [NO00026]
related: [NO00023, NO00025]
supersedes: []
---

# NO00027 GrhSIM batch target 512 compile-time diagnosis and XiangShan retest (2026-07-16)

> 归档编号：`NO00027`。主题导航：
> `tree/simulation/gsim-grhsim-exchange/00/000-099.md`。

## 结论先行

在完全复用 NO00026 的 GSim executable GRH、108-op activity schedule 参数和
`clang++ -std=c++20 -O3 -j32` 条件下，只把 `sched_batch_target_count` 从 64 提到 512，
model archive 从 30 分钟仍不能完成变为 **4:57.20 完整编译成功**。583/583 个 schedule
objects 全部生成，最终 `libgrhsim_SimTop.a` 为 173 MiB。

该结果证明 NO00026 的主要编译阻塞不是总 C++ 规模，而是过少的 batch 把约 1200 个
supernode 聚合进单个 `eval_compute_batch_N()`，触发 LLVM GVN 在一个巨大函数上的灾难性长尾。
target 512 基本不改变总 schedule C++ bytes，却把平均每函数 supernode 从 797.0 降到 144.9，
足以消除 30 分钟 gate。

## Clang 阶段定位

对 target 64 gate 中未完成的 17 个 TU 做了逐个串行隔离编译，命令包含：

```text
-ftime-report=per-pass
-ftime-trace=<tu>.trace.json
```

结果为 16 个成功，`sched_63` 单独运行 60 分钟仍超时。成功 TU 的累计分布：

| 阶段 | 累计耗时 | 占总编译 |
| --- | ---: | ---: |
| total | 10,967.4 s | 100% |
| Optimizer | 10,656.5 s | 97.16% |
| GVNPass | 9,378.3 s | 85.51% |
| CodeGen | 286.8 s | 2.62% |
| Frontend | 23.9 s | 0.22% |

每个成功 TU 中最慢的一次 GVN 都落在唯一的
`GrhSIM_SimTop::eval_compute_batch_N()`，而且最慢 invocation 平均占该 TU 全部 GVN 时间的
99.95%。典型长尾为：

| target 64 TU | 隔离 wall | GVN |
| --- | ---: | ---: |
| `sched_56` | 53:42 | 51:35 |
| `sched_63` | >60:00 | 未正常退出 |
| `sched_64` | 33:48 | 28:47 |
| `sched_62` | 22:34 | 21:29 |
| `sched_60` | 17:34 | 14:46 |

因此预处理、AST/Sema 和 backend code generation 都不是主因；问题集中在单个巨大 CFG/SSA
函数进入 GVN 后的非线性开销。

## target 64 为什么产生约 1200-supernode 函数

activity-schedule 仍产生 84,439 个 compute supernode；batch grouping 是 emitter 的后续步骤，
并没有把这些 supernode 在 GRH 中合并。target 64 的理论平均值为：

```text
84,439 / 64 = 1,319.4 supernodes per target batch
```

`sched_56` 实际包含 1,206 个 supernode 和 152 个连续 active words，因而是正常的 target-64
产物而非偶发异常。`buildScheduleBatches()` 还会计算：

```cpp
effectiveMaxOps = std::max(batchMaxOps, totalOps / targetBatchCount);
effectiveMaxLines = std::max(batchMaxEstimatedLines, totalLines / targetBatchCount);
```

本图有 7,572,108 个 compute ops，所以配置的 2,048-op 上限被抬高到 118,314。换言之，
`sched_batch_target_count=64` 会把看似是 max 的阈值变成软约束，主动形成少量大函数。

## sched_56 的结构归因

target-64 `sched_56` 是 flattened SimTop 的全局拓扑切片，不对应单一 RTL module：

- 1,206 supernodes；
- 13,994 emitted op markers；
- 9,342 `kRegisterReadPort`，占 66.8%；
- 1,647 mux、701 and、694 concat；
- 273 system tasks、95 DPI calls；
- register reads 主要来自 backend `ctrlBlock`、frontend IFU/ITLB 和 MemBlock。

最大的单个 supernode 是 70162，对应：

```text
gsim.effect.7822919
gsim.node_name = logEndpoint$PRINTF_9368977
source = utility/LogUtils.scala:203
```

这是合并后的 PERF `fwrite`，有 2,001 个 GSim value inputs 和 2,000 个 `%d`；生成的一条 C++
调用长 281,108 bytes，整个 supernode 为 400,155 bytes。但是它只占 `sched_56` 的 2.83%，
说明 GVN 长尾来自整个 batch CFG，而不是仅由这一条打印造成。

当前成本模型对任意 `kSystemTask` / `kDpicCall` 都固定估 10 行，不随参数数、格式串长度或表达式
长度变化。这仍会造成 target 512 中少数 TU 比平均值大很多，但本轮没有阻止完整编译。

## target 512 A/B

输入 JSON、activity-schedule 参数和编译参数不变，唯一变量：

```text
WOLVRIX_XS_GRHSIM_SCHED_BATCH_TARGET_COUNT=64  ->  512
```

activity-schedule 的 graph/supernode/DAG 统计逐项一致，证明 target 只改变 emitter grouping，
不改变调度语义与 supernode 形成结果。

| 指标 | target 64 | target 512 | 差异 |
| --- | ---: | ---: | ---: |
| compute functions | 66 | 542 | +476 |
| commit functions | 40 | 41 | +1 |
| all schedule TUs | 106 | 583 | +477 |
| total schedule bytes | 1,196,041,092 | 1,200,575,465 | +0.38% |
| mean schedule TU bytes | 11,283,407 | 2,059,306 | -81.75% |
| largest schedule TU | 36,157,553 | 12,079,508 | -66.59% |
| mean supernodes/TU | 797.0 | 144.9 | -81.82% |
| max supernodes/TU | 1,544 | 232 | -84.97% |
| compile gate | >30:00, timeout | 4:57.20, success | fixed |
| schedule objects | incomplete | 583/583 | complete |
| archive | absent | 173 MiB | complete |

target 512 emit 本身为 51.670 s，与 target 64 的 53.130 s 相当；import + schedule + emit 总 wall
为 2:56.28。因此增加 TU 数没有显著增加代码生成阶段开销。

## Emulator build 与 CoreMark 50k gate

target 512 model archive 随后接入独立 XiangShan difftest build：

```text
BUILD_DIR=ptmp/gsim_assign_elide_20260716/target512/difftest
GRHSIM_MODEL_DIR=ptmp/gsim_assign_elide_20260716/target512/grhsim_emit
GEN_CSRC_DIR=testcase/xiangshan/build/generated-src
WOLVRIX_GRHSIM_WAVEFORM=0
```

wrapper compile 和链接成功，wall 为 7.61 s，生成 132 MiB `grhsim-compile/emu`。随后执行：

```text
./emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 50000
```

50k **未正常结束**。进程在启动后 0.05 s 以 exit 1 退出，首个错误为：

```text
[fatal] Assertion failed at MSHR.scala:1472
```

该 assertion 来自 `huancun/noninclusive/MSHR.scala`：

```scala
assert(RegNext(!req_valid || !io.alloc.valid, true.B)) // TODO: support fully-pipelined
```

含义是已有 request 有效时又收到新的 MSHR allocation。失败不是 timeout、链接错误或 NEMU
mismatch；运行尚未到达 50k 正常终点。生成的 fatal 路径位于 target 512
`grhsim_SimTop_sched_106.cpp`。batch target 只改变保持顺序的函数边界，activity-schedule 结构也
逐项相同，因此本轮证据不足以把该功能错误归因于 target 512；它更像 executable GRH 导入/调度
语义中尚未解决的时序或状态更新问题。

## 判断与后续

1. target 512 是当前输入规模下有效的编译 unblock，可作为近期默认 A/B 值。
2. `sched_batch_max_ops` 和 `sched_batch_max_estimated_lines` 应成为真正硬上限；target count 只能在
   不突破硬上限时作为软目标，无法满足时应允许产生更多 batch。
3. cost model 应至少计入 SystemTask/DPI operand count、format bytes、estimated expression bytes、
   active-word 数和 branch 数；只计 op/estimated lines 无法预测 GVN。
4. emulator 已成功链接，但 CoreMark 50k 在 `MSHR.scala:1472` assertion 处立即失败。下一步功能
   调试应围绕 `req_valid`、`io.alloc.valid` 和对应 MSHR 实例的上一周期状态更新展开；编译优化本身
   可以保留。

## 证据路径

```text
ptmp/gsim_assign_elide_20260715/full/clang_profile_incomplete/summary.tsv
ptmp/gsim_assign_elide_20260715/full/clang_profile_incomplete/status.tsv
ptmp/gsim_assign_elide_20260715/full/clang_profile_incomplete/*.trace.json
ptmp/gsim_assign_elide_20260716/target512/run_import_emit.sh
ptmp/gsim_assign_elide_20260716/target512/run_compile.sh
ptmp/gsim_assign_elide_20260716/target512/run_build_emu.sh
ptmp/gsim_assign_elide_20260716/target512/run_coremark_50k.sh
ptmp/gsim_assign_elide_20260716/target512/logs/import_emit.log
ptmp/gsim_assign_elide_20260716/target512/logs/model_compile.log
ptmp/gsim_assign_elide_20260716/target512/logs/emu_build.log
ptmp/gsim_assign_elide_20260716/target512/logs/coremark_50k.log
ptmp/gsim_assign_elide_20260716/target512/grhsim_emit/libgrhsim_SimTop.a
ptmp/gsim_assign_elide_20260716/target512/difftest/grhsim-compile/emu
```
