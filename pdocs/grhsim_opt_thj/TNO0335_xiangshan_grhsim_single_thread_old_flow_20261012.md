# TNO0335 XiangShan GrhSIM 旧单线程流程性能复测

日期：2026-10-12

## 1. 目的与流程边界

本轮验证的是 XiangShan 原有的 GrhSIM 单模型流程，不是 RepCut 分区、多 worker、Host/worker 或 all-spin 框架。流程为：

```
RTL/FIR → scripts/wolvrix_xs_grhsim.py → activity-schedule → 一个 GrhSIM C++ 模型 → difftest emu
```

因此这里的“单线程”指一个模型实例由一个仿真执行线程推进；它不表示把 32 个 RepCut 分区串行运行。旧流程默认的图变换和生成选项保持不变。本轮另外隔离了两个可迁移候选：

1. **codegen**：打开通用的 `packed_array_late_index` 与带 `1048576 bit·operation / 25%` 门槛的 `local_compute_use_order`；不改变 RTL、调度图或模型分区。
2. **coalesce**：只在旧单模型脚本中显式打开 `memory-write-coalesce`，环境变量为 `WOLVRIX_XS_GRHSIM_MEMORY_WRITE_COALESCE=1`；脚本默认仍为关闭。

三组均从同一 XiangShan RTL 和同一 pre-reg-to-mem 检查点生成，避免把前端图变换差异混入后端候选。所有模型均用 Clang 23.1.2、`-std=c++20 -O3 -march=native` 编译；Wolvrix Python 扩展使用当前可用的 LLVM-21 主机构建产物，三组最终模型的编译器和参数一致。

## 2. 运行设置

- 运行节点：`node032`。
- 仿真进程 CPU 限制：`taskset -c 0-7 setarch x86_64 -R`；构建阶段不限制在 0--7。
- 输入：`coremark-2-iteration.bin`，NEMU Difftest，seed=0，`C=100000`。
- 不启用 waveform；保留既有 XSPerfPrint 输出，但只在仿真结束时统一重定向到日志。
- 每组均完成正向 `ABBA`（baseline、candidate、candidate、baseline）和反向 `BAAB`（candidate、baseline、baseline、candidate）。所有样本到达同一 cycle limit，Difftest 签名一致：`pc=0x80000c0c`、Guest cycle `100001`。

模型和日志位于：

```
build/old_single_20261012/{baseline,codegen,coalesce}/
build/old_single_20261012/perf_c100000/
```

## 3. Host 时间

日志中的 `Host time spent`（ms）原始样本如下。

| 候选 | 顺序 | baseline | candidate |
| --- | --- | ---: | ---: |
| codegen | ABBA | 115424, 118397 | 118892, 118368 |
| codegen | BAAB | 115821, 116770 | 116299, 116723 |
| coalesce | ABBA | 121819, 119163 | 119916, 120942 |
| coalesce | BAAB | 119515, 117584 | 119669, 118910 |

按每个 ABBA/BAAB 块中的 baseline 与 candidate 配对平均：

| 候选 | ABBA 配对均值（ms） | BAAB 配对均值（ms） | 四对总体均值（ms） | 相对 baseline |
| --- | ---: | ---: | ---: | ---: |
| codegen | 116910.5 → 118630.0 | 116295.5 → 116511.0 | 116603.0 → 117570.5 | **+0.8297%** |
| coalesce | 120491.0 → 120429.0 | 118549.5 → 119289.5 | 119520.25 → 119859.25 | **+0.2836%** |

codegen 在 ABBA 中回退约 1.47%，反向 BAAB 中接近中性；合并后没有收益。coalesce 的 ABBA 微小负差没有在 BAAB 复现，四对合并为轻微回退。两者都不能作为单线程默认优化。

## 4. 生成物对照与归因

codegen 虽然改变了各 `sched_*.cpp` 的操作遍历/注释文本，生成的 `libgrhsim_SimTop.a` 与 baseline **逐字节相同**（SHA256：`56b0df8c400eca19d527ff0bb707d7926074b35794070b8643652a5df97c3a34`）。因此该候选在本次 XiangShan 旧流程中没有进入不同的机器码，Host 时间的 +0.83% 只能视为运行噪声/顺序效应，不能解释为代码生成收益。

coalesce 使生成 C++ 总字节数约减少 `0.369%`，静态库从 `87285028` 降到 `86772668` 字节（约 `-0.587%`），但运行时间仍为中性到轻微回退。这说明单线程瓶颈不由这一小部分模型体积主导；仅缩减 memory-write staging 还不足以降低完整 Host 时间。

## 5. 结论与后续

- 旧单线程 GrhSIM 流程本身已在 node032 0--7 上完成可复现的 C=100000 ABBA/BAAB 测量。
- 本轮迁移的两个多线程优化候选均没有明确单线程收益：`codegen` 不改变最终静态库，`coalesce` 只减小模型尺寸但不改善 Host 时间。
- `memory-write-coalesce` 在旧流程中保留显式选项和默认关闭语义；不应因为 RepCut 上的静态缩减就直接打开旧单线程默认。
- 后续若要继续迁移，应先做单线程模型内部的 eval/update/初始化分解或机器码热点归因，再选择能实际改变执行指令和内存访问的通用规则；本轮结果不支持继续叠加这些候选。

## 6. 与历史速度口径对齐及回退归因（2026-10-12 增量）

### 6.1 历史记录

当前可找到的最近两组单线程 GrhSIM 记录如下：

| 记录 | 仿真长度 | 条件 | Host 时间 | 速度 |
| --- | ---: | --- | ---: | ---: |
| [TNO0299](TNO0299_simpletes_b_native_walltime_regression_20260909.md) | `C=50000` | 已落地主线，Clang 19.1.1，`-O3` | `41051.25 ms` | `1217.99 cycles/s` |
| [TNO0302](TNO0302_simpletes_astra_budget128_valid64_resume_20260914.md) | `C=50000` | 实验候选，Clang 19.1.1，`-O3` | `39490 ms` | `1266.14 cycles/s` |

更早的 [TNO0234](TNO0234_clean_plain_gsim_grhsim_walltime_comparison_20260814.md) 为 `1167.21 cycles/s`。因此“之前 1100+ cycles/s”的记忆是正确的；但这些记录都是 `C=50000`，不能直接与本轮 `C=100000` 的结果比较。

本轮 `C=100000` 的 baseline 配对平均约为 `116.6--118.1 s`，即约 `847--858 cycles/s`。`C=100000` 的当前模型在结束时达到 `240349` 条 guest 指令，而 `C=50000` 时只有 `73580` 条；后半段动态工作量明显更密集，所以 cycles/s 会随仿真窗口变长而下降。仅用 `C` 做线性换算会把这一差异误判成回退。

### 6.2 同一 C=50000 下的旧/新二进制诊断 AB

历史 TNO0299 的二进制仍然存在：

```
build/grhsim_b_landing_20260909/run_node032_v1/snapshots/base/emu
build/grhsim_b_landing_20260909/run_node032_v1/snapshots/base_B/emu
```

在 node032 的 CPU `0--7` 上用同一 `C=50000`、同一输入和 Difftest 目标进行了旧二进制与当前二进制的 AB/BA 诊断。两者都完成到相同的 `73580` 条指令、`cycle=49996`，说明比较的是同一仿真工作量。诊断样本受节点负载影响，不能作为正式 speedup，但暴露了明确差异：

| 二进制 | stderr 输出 | `sys` 时间 |
| --- | ---: | ---: |
| 历史 base | 31 bytes，几乎没有运行时输出 | `0.04--0.13 s` |
| 当前 baseline | `4,434,050 bytes`、约 `34,306` 条 `[PERF]` | `3.76--4.13 s` |

即使把 stdout/stderr 重定向到 `/dev/null`，当前二进制仍保留约 4 秒的系统时间，说明成本主要来自格式化和写出路径本身，而不是终端或文件系统吞吐。当前 C=50000 的输出是由 XiangShan `XSPerfPrint` 的 dump 路径产生的；`wolvrix_xs_grhsim.py --perf off` 只关闭 GrhSIM evaluator 自身的性能计数，不会关闭 RTL 侧的 `set_perf_dump(1)`。`emu.cpp` 在 `display_stats()` 的结束路径中无条件调用 `trigger_stat_dump()`，后者再执行一次 `set_perf_dump(1)` 和 `single_cycle()`。

这解释了当前速度下降中的一个已确认因素：每次 C=50000 仿真多出约 4 秒的固定计账/输出开销。当前 XiangShan utility 子模块相对历史快照包含 `next_counter → counter` 的实验性修改；它是 RTL 侧输出行为的主要版本差异，但仅凭现有 AB 还不能把全部 4 秒严格归因到这一行修改，因为当前生成器、编译器和启动协议也同时发生了变化。

### 6.3 仍需区分的次要因素

1. 当前 activity schedule 的 `graph_ops` 为 `7,204,108`，历史 TNO0298 为 `6,990,363`，增加约 `3.06%`；topo edges 基本不变。这表示当前生成模型确实有更多图操作，可能增加 eval 工作量。
2. 历史主线使用 Clang 19.1.1 的普通 `-O3`，本轮使用 Clang 23.1.2 的 `-O3 -march=native`；现有 AB 没有隔离编译器影响。
3. 历史正式记录使用专用 CPU/NUMA 页面局部性协议，本轮旧流程复测只使用 `taskset -c 0-7`，且 node032 当时存在较高外部负载；当前绝对 walltime 会因此更不稳定。
4. 当前最终 ELF 更小并不能说明更快：本轮 coalesce 已把静态库缩小约 `0.587%`，但 Host 时间没有改善。因此模型文件大小不是这次回退的主因。

结论是：历史 `1100+ cycles/s` 主要来自 `C=50000` 的较轻工作窗口和更干净的运行协议；当前低到 `~850 cycles/s` 不能直接视为单线程算法整体退化。当前二进制额外执行的 XSPerfPrint dump 是已用同一 C、同一终点和 AB 诊断确认的具体回退来源，优先应在性能测量/发布构建中显式关闭该 dump，再用相同的 `C=50000`、编译器和 CPU/NUMA 协议重做正式 AB。

## 7. 固定 C=50000、关闭 PERF dump 后的 ABBA/BAAB（2026-10-12 增量）

为隔离上一节确认的输出开销，保留当前 `grhsim_emit` 模型不变，只将 `emu.cpp` 的 `trigger_stat_dump()` 在测试链接中编译为空操作，生成临时 B 二进制：

```
build/old_single_20261012/baseline/grhsim-compile/emu_noperf_20261012
SHA256 19ea448c00b6a5047f588d5bbcffe1da859e22ca52351a7c9dbebbe2ec744d1b
```

A 使用历史二进制 `build/grhsim_b_landing_20260909/run_node032_v1/snapshots/base/emu`。两边均在 node032 CPU `0--7`、相同输入和 NEMU Difftest 下执行 `C=50000`，顺序为 `ABBA` 与 `BAAB`。所有样本均为 `73580` 条指令、`cycleCnt=49996`，stdout/stderr 中 `[PERF]` 数量均为 0。

| 顺序 | A（历史 base，ms） | B（当前模型、无 PERF，ms） | B 相对 A |
| --- | ---: | ---: | ---: |
| ABBA 配对均值 | `45562.5` | `42599.5` | **-6.50%** |
| BAAB 配对均值 | `46206.5` | `45190.0` | **-2.20%** |
| 四样本总体均值 | `45884.5` | `43894.75` | **-4.34%** |

对应平均速度为 `1089.7 → 1139.1 cycles/s`，即约 `4.53%` 的速度提升。因此，在固定 `C=50000` 且真正关闭 RTL 性能计数器 dump 后，当前生成模型相对历史 base 的 Host 时间下降约 `4.34%`；之前观察到的约 4 秒差距主要来自当前二进制额外执行的 XSPerfPrint dump。该轮运行目录为 `build/old_single_20261012/ab_c50000_noperf_20261012/`。

## 8. C=100000 的前后 50000 cycles 分段对照（2026-10-13 增量）

使用同一个关闭 PERF dump 的当前二进制，在 node030 CPU `0--7` 上交错执行两次 `C=50000` 和两次 `C=100000`。由于 `C=100000` 是从同一复位状态开始的完整前缀，使用 `T(100000)-T(50000)` 估算后 50000 个 cycles；初始化开销在差分中基本抵消。所有样本均无 `[PERF]` 输出。

| 样本 | `C=50000` 前缀 Host | `C=100000` Host | 后 50000 cycles 差分 |
| --- | ---: | ---: | ---: |
| 1 | `41.471 s` | `100.078 s` | `58.607 s` |
| 2 | `42.256 s` | `98.599 s` | `56.343 s` |
| 平均 | `41.864 s` | `99.339 s` | `57.475 s` |

因此，前 50000 cycles 的速度约为 `1194.4 cycles/s`，后 50000 cycles 约为 `869.9 cycles/s`：后半段每相同数量的模拟 cycles 多耗时约 **37.3%**，按 cycles/s 计算则下降约 **27.2%**。结果目录为 `build/old_single_20261012/prefix_split_c100000_noperf_node030_20261013/`。

差异与动态工作量变化直接相关：前 50000 cycles 退休 `73580` 条 guest 指令，后 50000 cycles 退休 `240349-73580=166769` 条，后半段是前半段的约 `2.27` 倍。相应的 guest IPC 从 `1.4716` 增至 `3.3354`；虽然每个模拟 cycle 更慢，但每秒退休指令数反而从约 `1758` 增至 `2902`。这说明后半段进入了更活跃的 CoreMark 执行阶段，更多流水线、寄存器和存储状态参与 eval/update，cycles/s 的下降主要反映每周期 RTL 工作量增加，而不是同样工作量的单纯退化。

## 9. CoreMark 自然结束前每 50000 cycles 的单次连续测量（2026-10-13）

本轮使用 `EMU_PROGRESS_EVERY_CYCLES=50000`，在同一次仿真内记录累计 Host 时间，避免多次从复位状态启动。运行固定 node030 CPU `0--7`、当前无 PERF dump 二进制和 `coremark-2-iteration.bin`，直到自然 good trap；没有设置 `-C` 上限。

| 区间 | cycles | 退休指令增量 | Host 时间 | 速度 |
| --- | ---: | ---: | ---: | ---: |
| 0--50000 | 50000 | 73580 | 42.776 s | 1168.9 cycles/s |
| 50000--100000 | 50000 | 166769 | 57.785 s | 865.3 cycles/s |
| 100000--150000 | 50000 | 93941 | 50.251 s | 995.0 cycles/s |
| 150000--200000 | 50000 | 170054 | 55.770 s | 896.5 cycles/s |
| 200000--250000 | 50000 | 127125 | 53.521 s | 934.2 cycles/s |
| 250000--297295 | 47295 | 32219 | 28.625 s | 1652.2 cycles/s |

CoreMark 在 `297295 guest cycles`、`663688` 条指令处命中 good trap，完整 Host 时间为 `288.728 s`；stderr 为空。最后一行不是完整的 50000-cycle 区间，且包含结束处理，速度不应与前五行直接比较。

这组连续数据说明速度不是随 cycle 单调下降，而是随着 CoreMark 所处阶段的动态 RTL 工作量变化：`50000--100000` 和 `150000--200000` 的退休指令增量较大，对应较低的 cycles/s；`100000--150000` 和 `200000--250000` 较轻。此前 C=100000 中“后 50000 比前 50000 慢”是真实的阶段差异，但不能外推为整个 CoreMark 后半程都会越来越慢。
