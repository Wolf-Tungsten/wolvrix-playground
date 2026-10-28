# TNO0333 RepCut 多线程 GrhSIM 后端

日期：2026-09-25

## 1. 目标与支持范围

为 RepCut 多线程仿真框架增加 GrhSIM 后端，保留原有 Verilator 功能和默认配置。同一个 package 内全部 partition 使用同一种后端，不支持混用。生成阶段选择后端，运行时没有 backend virtual dispatch。

本阶段保持一个主题文档，后续编译、运行验证在相关章节追加，不为每次动作新建记录。另一条 backend-lowered cost model 探索线保持独立，不纳入本次后端接入结论。

## 2. 实现

- 新增 C++ `EmitGrhSimRepCutPackage` 和 Python `Session.emit_grhsim_repcut_package(design=..., output=..., top=...)`。
- 共用原 RepCut 的边界复制和阶段调度：load → early eval → early update → normal eval → final update。N=K 时沿用 host 参与及默认 all-spin；N<K 时沿用条件变量路径。
- 每个 partition 实例拥有独立 GrhSIM 模型；即使多个实例引用同一 graph，也不共享状态。只在私有 design/graph clone 上执行 activity-schedule，不修改调用方设计。
- adapter 暴露 `init/eval` 和输入输出引用；每个 adapter 的实现文件单独包含对应模型头，避免多个模型 runtime 头在一个翻译单元内重复定义。
- GrhSIM 信号使用 bool/uint8/uint16/uint32/uint64 及更宽的 `std::array<uint64_t,N>`，不借用 Verilator 的宽值 ABI。
- 顶层生成 `grhsim_<Top>.hpp` facade、`wolvi_repcut_grhsim_sim.h`/分片 cpp 和 `libgrhsim_<Top>.a` Makefile，可由既有 XiangShan `grhsim.mk` 消费。
- Makefile 使用本次 emit 的显式源文件列表，并重新创建 archive，避免重生成后旧 partition 残留被编译/链接。
- 支持重新 `init()`；第一次 eval 建立时钟基准，初始高电平不凭空触发上升沿。

### 2.1 后端选择与默认值

`scripts/wolvrix_xs_repcut.py` 新增 `XS_REPCUT_BACKEND=verilator|grhsim`，默认仍为 Verilator。原显式 Verilator targets 强制 Verilator；新增 GrhSIM targets 和通用 dispatch targets。两个后端的构建产物隔离。

| 配置 | Verilator 默认 | GrhSIM 默认 |
| --- | --- | --- |
| RepCut cost model | verilator-v1 | legacy |
| reg-to-mem profitability filter | verilator-v1 | none |
| memory-write-coalesce / reg-to-mem | 保持现有默认 | 同样执行，允许显式覆盖 |

GrhSIM 尚未建立专属成本模型，因此不默认套用 Verilator 经验权重/门槛；显式覆盖仍然可用。库级 reg-to-mem 的默认筛选行为没有被本工作更改。

```bash
make build_xs_repcut_grhsim
make run_xs_repcut_grhsim XS_EMU_THREADS=32 XS_EMU_PREFIX='taskset -c 96-127'

# 通用入口，默认不传 backend 时仍为 Verilator
make build_xs_repcut_sim XS_REPCUT_BACKEND=grhsim
make run_xs_repcut_sim XS_REPCUT_BACKEND=grhsim XS_EMU_THREADS=32
```

上述运行命令应在 node030 上执行。生成/模型 API 说明见 [RepCut 文档](../../wolvrix/docs/transform/repcut.md)。

## 3. 已完成的验证

### 3.1 小模型真实编译运行

`emit-grhsim-repcut-package` 测试真实生成、编译静态库、链接 harness 并运行，不只检查输出文本。覆盖：

- 3 个 partition、同 graph 的两个独立实例；
- 8/65/130 位端口及宽常量、跨 partition 寄存器传递；
- 带结果的 early DPI、调用次数、同步 reset、reset 优先于 enable；
- 初始高电平、保持时钟期间修改输入/reset 不误触发；
- wrapper 与 native GrhSIM facade 两种入口、重新 init；
- N=1、N=2 条件变量、N=3 默认 all-spin、N=3 显式条件变量；
- 各模式预期输出与完整 transcript 一致，线程数/等待策略日志符合配置；
- source design 不变、非法顶层端口名拒绝、重生成忽略陈旧 cpp。

2026-09-25 最新测试结果：两个 package CTest 均通过，GrhSIM 测试约 42.87 秒，合计 43.52 秒（包含命名、宏名、wrapper 类名和六类 file-handle 负向 gate）。Python API 4/4、父仓库 flow 4/4、既有 Python options 回归 40/40 通过。

### 3.2 Verilator 不变性

独立编译 HEAD 的 emitter/原测试，与当前实现对同一 fixture 分别生成 7 个 package；70 个文件逐字节一致，两个测试均退出 0。审计产物位于 `wolvrix/build/artifacts/repcut-verilator-identity-KYIJCs`。

这证明该 fixture 的 Verilator 生成路径没有变化；不是新的 XiangShan walltime A/B 测量，不声称据此测得性能百分比。

### 3.3 XiangShan 32 partition 集成

为单独验证后端接入，本次输入采用现有冻结的 `build/default_line_ab_20260924/default_noenv/partitioned.json`，不是重新按 GrhSIM 的 legacy/none 默认划分。

- node030，CPU96–127。
- 产物目录：`build/repcut_grhsim_20260925/package`。
- 完整 read + emit 约 544.212 秒（读取约 33.744 秒）。
- 32 个独立模型；根目录共 7,454 个 cpp。package 总占用约 3.7 GiB，含嵌套模型原件与复制到根目录的源码，不是单份源码大小。
- 模型静态库已用 node030 CPU96–127、G++、O3 编译完成，`libgrhsim_SimTop.a` 约 135 MiB；现有 Difftest 的 41 个对象和最终 `emu` 链接均通过。
- 实际 NEMU Difftest 已完成 `-C 100`、`-C 10000`、`-C 30000`。N=1、N=8 与 N=32 的 C=10000 均提交 458 条指令并在 `0x800027c6` 结束；N=1 与 N=32 的 C=30000 均提交 27,809 条指令并在 `0x80000442` 结束。三档均通过 Difftest，timing JSONL 也正常生成。N=8 使用父仓库新 `run_xs_repcut_sim XS_REPCUT_BACKEND=grhsim` 入口，验证了 Make dispatch 与条件变量路径。
- 这些是后端接入的功能/链路检查，不是性能 A/B：例如 C=30000 的单线程 Host 约 86.5 s，32 线程 all-spin 约 6.25 s，短程序、首次生成包和当前机器状态都会显著影响绝对值，不能用来宣称 GrhSIM 相对 Verilator 的收益。

### 3.4 关于跨分区输出时序

用 64 个寄存器的独立小 RTL 做默认 `read_sv → RepCut 32 分区 → GrhSIM` 流程时，发现一个可重复的既有 RepCut 输出传播限制：例如 `state00` 在一个 partition、`q00` 在另一个 partition 时，normal eval 后的 final update 才把新 state 推到 q00 所在 partition，因此 q00 可能到下一次 eval 才观察到该值。N=1 也能复现，和线程数无关。

对同一份冻结 `repcut.json` 分别生成 GrhSIM 与 Verilator package，N=1/8/32 三档的逐 eval 记录均逐字节一致：每档 770 个输出快照加 1 行汇总，共 771 行，checksum 为 `ab0da7c068fc145d`。另按 RTL 算术参考和上述既有输出 phase 检查每个快照的 64 个 lane，三档均通过。单体、未 RepCut 的 GrhSIM 在同一 RTL 上会在 posedge 立即暴露新值，证实这个差异来自共享 RepCut 调度，不是 GrhSIM 后端新增的问题。

本次没有添加额外 eval 来掩盖此限制，也不将其描述为完整的 SV delta-cycle 语义支持。XiangShan 的实际 Difftest 链路已通过；后续若要修正这类跨分区同步输出，需要单独修改共享 RepCut phase/输出契约并同时重测 Verilator。复现产物及逐快照校验脚本位于 `build/repcut_grhsim_20260925/small_flow/`。

## 4. 当前边界

- 支持固定宽度 logic 端口，拒绝 inout、顶层 C++ 保留字/名称冲突。
- 当前 package 不支持 waveform 和 GrhSIM 模型内部 perf/runtime-profile；显式请求会报错，不用空计数冒充支持。RepCut 框架级 `WOLVI_REPCUT_TIMING_JSONL` 可用。
- 外部 DPI 的 ABI/线程安全仍由现有 GrhSIM/DPI 契约约束。该 XiangShan 输入的 34 个 imports 都是 ≤64 位标量或 string，27 个 `v_difftest_*` 的参数顺序/宽度与当前 C++ 实现对照一致。
- 文件句柄目前由每个 GrhSIM 模型独立保存，尚无 package 共享句柄上下文，因此生成前明确拒绝 `fopen/ferror/fdisplay/fwrite/fflush/fclose`，避免跨 partition 使用句柄时静默出错。`display/write/fatal` 可用，但并行 partition 之间的打印顺序不保证。
- 调用方不可并发调用同一仿真实例的 init/eval/析构；跨 partition 同时调用的 DPI 必须自身线程安全。
- 当前验证重点是功能和集成，尚未声称 GrhSIM 的速度优于 Verilator，也未据此调整 Verilator 默认。

## 5. 增量更新 2026-09-25：两后端 walltime 交错实测

本节是功能接入完成后的性能验证，补充第 3 节的单次功能数据。分别测了“相对之前实际使用的 Verilator 配置”以及“统一 GCC 编译器”两个口径；不把二者混为同一个收益数字。两批均为 8 对 AB/BA，各后端各 8 个 C=30000 正式样本，全部通过。

### 5.1 固定输入与构建配置

- node030，CPU96–127，NUMA memory bind=1，关闭 ASLR；N=K=32，Host CPU105/lane9，31 个后台 worker，默认 host/worker all-spin。每个样本核验完整 runtime-config。
- 两后端都来自 `build/default_line_ab_20260924/default_noenv/partitioned.json`，SHA256=`91fe701ad7e68df398d9f62f6c4584dfa78a72cc195789724dcf5f97923bf488`。没有重跑分区，不能将这次结果理解为 GrhSIM legacy/none 默认分区方案的测量。
- 同一个 `coremark-2-iteration.bin`、seed=0、NEMU reference，`-b 0 -e 0 -C 30000`。每个正式样本均开启 Difftest，提交 27,809 条指令，结束 PC=`0x80000442`，cycleCnt=29,996、guest cycles=30,001、RepCut steps=60,102。这是固定周期窗口，不是完整 CoreMark 跑分。
- A=Verilator，B=GrhSIM；顺序 AB/BA/AB/BA/AB/BA/AB/BA。每批先做两端 C=100 初始化检查，不计入正式中位数；保留全部功能通过样本，无空闲率门槛、无按速度过滤。编译结束后才开始正式采样。
- 框架 step/partition 计时在当前生成代码中固定开启，两端一致；仅设置 `XS_REPCUT_STEP_TIMING=0` 不能去除这些计时。GrhSIM 内部 perf/profile、波形与 EMU_PHASE_TIMING 均未启用。这不关闭香山 RTL 中的 XSPerf 逻辑。

| 项目 | 原使用的 Verilator | 统一 GCC 的 Verilator | 本次 GrhSIM |
| --- | --- | --- | --- |
| C++ 编译器 | Clang 21.1.5 | GCC 13.3.0 | GCC 13.3.0 |
| 模型 | Verilator 5.048，默认 fast=`-Os`、slow 无显式优化标志 | 同左 | GrhSIM 模型 `-O3` |
| RepCut wrapper | `-O3` | `-O3` | `-O3` |
| Difftest 外层 | 没有显式 `-O` 标志 | 同左 | 同左，使用同一组 generated-src |

统一 GCC 的实验消除了编译器差异，但仍保留各后端现有模型优化配置，不是统一所有 `-O` 标志的代码生成器微基准。GCC-Verilator 在独立目录重新生成/编译 32 个模型；GrhSIM 复用已验证的 GCC `-O3` 模型库，重新编译外层以匹配原 Verilator 的 Difftest 编译选项。原有 Verilator/GrhSIM 产物均未覆盖。

### 5.2 Walltime 与 Host 结果

以下“减少”按 `1 - median(GrhSIM) / median(Verilator)` 计算；“逐对减少中位数”先计算每一对 `1 - GrhSIM_i / Verilator_i` 再取中位数，两者不应混用。

| 比较口径 | 指标 | Verilator 中位数 | GrhSIM 中位数 | 中位数之比对应减少 | 逐对减少中位数 |
| --- | --- | ---: | ---: | ---: | ---: |
| 原使用配置：Clang-Verilator 对 GCC-GrhSIM | 进程 walltime | 6.925 s | 6.305 s | 8.95% | 8.89% |
| 同上 | Host | 6.8410 s | 6.2675 s | 8.38% | 8.34% |
| 统一 GCC 编译器 | 进程 walltime | 8.395 s | 6.380 s | 24.00% | 23.96% |
| 同上 | Host | 8.3015 s | 6.3445 s | 23.57% | 23.56% |

两批均为 GrhSIM 8/8 对更快。原使用配置对照的 walltime 范围是 Verilator 6.91–6.95 s、GrhSIM 6.24–6.44 s，逐对减少 6.95%–9.83%；AB、BA 的逐对减少中位数分别为 8.15%、9.31%。统一 GCC 的 walltime 范围为 8.35–8.48 s、6.11–6.50 s，逐对减少 22.53%–27.18%。两批 GrhSIM 样本是分别重跑的，不跨批次拼成一组收益。

| 对次 | 顺序 | 原配置对照 Verilator wall / s | GrhSIM wall / s | 统一 GCC 对照 Verilator wall / s | GrhSIM wall / s |
| ---: | --- | ---: | ---: | ---: | ---: |
| 1 | AB | 6.91 | 6.43 | 8.48 | 6.49 |
| 2 | BA | 6.92 | 6.29 | 8.39 | 6.50 |
| 3 | AB | 6.94 | 6.41 | 8.38 | 6.42 |
| 4 | BA | 6.95 | 6.44 | 8.43 | 6.39 |
| 5 | AB | 6.92 | 6.24 | 8.39 | 6.11 |
| 6 | BA | 6.93 | 6.25 | 8.40 | 6.13 |
| 7 | AB | 6.92 | 6.32 | 8.35 | 6.37 |
| 8 | BA | 6.93 | 6.27 | 8.41 | 6.28 |

进程 walltime 由 `/usr/bin/time -v` 获取，包含启动、模型构造/初始化、仿真及退出。Host 使用 Difftest 日志中的计时边界，不等于完整进程 walltime，也不是所有线程 CPU 时间之和。这里只统计运行时间，不含生成/编译。

### 5.3 阶段数据与结论边界

原使用配置对照的每 step 耗时中位数：

| 指标 | Clang-Verilator | GCC-GrhSIM | 中位数之比对应变化 |
| --- | ---: | ---: | ---: |
| Host 侧 input-load 阶段 | 3.865 µs | 3.6145 µs | -6.48% |
| Host 侧 eval 阶段（含阶段同步） | 81.240 µs | 71.232 µs | -12.32% |
| Host 侧 update 阶段（含阶段同步） | 25.841 µs | 26.1175 µs | +1.07% |
| 最大分区 eval：part_3 | 75.981 µs | 57.4015 µs | -24.45% |
| part_3 update-push | 9.162 µs | 14.453 µs | +57.75% |

可确认当前 GCC-GrhSIM 在相同冻结分区和该周期窗口上改善了最终 walltime，且收益主要出现在 eval；update 没有随之下降。最大分区仍为 part_3。分区自身 eval、Host 整个 eval 阶段、最终 walltime 是不同边界，因此 24.45% 的最大分区 eval 降幅不能直接换算成同等 walltime 收益。这里不进一步把 update 变化归因到特定缓存/ABI 机制。

对用户原有工作流，最直接的收益口径是约 8.95% 的 walltime 减少（1.098×），不是 24%。后者只对应 GCC 对 GCC 这批数据。这些结论限定于本次 GCC-GrhSIM 构建、N=K=32、C=30000 和冻结分区，不外推为所有编译器、workload 或分区权重下的收益，也不修改 Verilator 默认。

### 5.4 复现与数据位置

统一前缀 `build/repcut_grhsim_20260925/`：

- `ab_c30000_current/`：原使用配置对照；`ab_c30000_gcc/`：统一 GCC 对照。两目录均保留每次 `.log/.time/.timing.jsonl`、`manifest.json`、`runs.csv`、`pairs.csv`、`parts.csv`、`summary.json` 和 `backend_summary.json`。
- `compare_backends.py` 复用 `scripts/repcut_cost_model_compare.py` 的 AB/BA runner 及既有功能/runtime 验证，只跳过不适用 GrhSIM ABI 的 Verilator 存储字节解析，不改变性能或功能通过标准。`summarize_backends.py` 计算上述汇总。
- `gcc_verilator/build.json`、`gcc_verilator/build.log`、`build_gcc_verilator.py` 保存独立构建命令；`gcc_grhsim/build.json`、`gcc_grhsim/build.log`、`build_gcc_grhsim_harness.py` 保存 GrhSIM 外层对齐命令。
- 两批 manifest 均确认 ELF、程序镜像、NEMU SHA256 在测量前后不变。原 Clang-Verilator ELF：`210574baaf81dbc85ef3d1a27bbf9a5800a7ebbaa66b15d86ad00754940080e3`；GCC-Verilator：`64094d79edaf5f71ddf8cbaeded30c850ec691beb89a80cef8e28a5c79457822`；两批共用 GCC-GrhSIM：`8f3b1a7db341fedd0a2ee2808ed2e426b7944a4a77f9cd8f4596685686d5e3cb`。

## 6. 增量更新 2026-09-25：Clang 错误代码生成定位与兼容修复

用户要求定位并修复 Clang 构建的 Difftest 失败。本节沿用同一冻结分区、CoreMark 镜像、NEMU 与 node030 CPU96–127；不改变分区、RTL 或 all-spin 默认。先前 GCC 正确性结果仍成立。

### 6.1 根因与独立复现

定位链条为模型编译器 → part_23 → `eval_compute_batch_102()` → 一个条件 OR 归约。外层 harness 交叉链接、N=1 和 N=32 的结果排除了外层编译器与多线程竞争。原报错是 cycleCnt=8257、仅提交 32 条指令时 PC 不一致；对同一份真实函数输入做 GCC/Clang 双执行后，发现第一次初始化计算就已有一个 bool 值不同，Difftest 只是后来观察到后果。

根因已缩成不依赖香山、Difftest、生成模型头和线程的普通 C++ 测试：若干 uint8 加法、布尔条件选择和 19 项 OR 归约，输入为零时本应得到固定结果。生产回归 fixture 为 `wolvrix/tests/emit/data/grhsim_clang_sse2_reduction.cpp`；计算与 main 分别编译以防整程序常量折叠。Clang 21.1.5 默认 x86/SSE2 的 `-O3` 可稳定得到错误结果，GCC 13、Clang 19，以及 Clang 21 的 `-mssse3` 均正确；ASan/UBSan 未报告源程序错误。

LLVM IR 的 shuffle 只保留向量加法的第 7 个 lane，其余 lane 应取原值。然而 SSE2 汇编在应丢弃的 lane 上产生 `0xff + 0x0f = 0x0e`，随后将这些非零值直接 OR 入有效 lane，导致布尔归约翻转。独立复核确认 IR 与机器码在此不等价。这是已复现的编译器后端错误；不是根据“关闭优化就好了”推测，也不是 GrhSIM 缺少香山性能计数器。尚未确认其他 LLVM 21 补丁版本的修复状态。

### 6.2 通用兼容处理

新增共享 Makefile 生成片段，供单体 GrhSIM 和 RepCut-GrhSIM 使用。在 **Clang major=21、x86 目标、未启用 SSSE3** 时自动追加 `-fno-slp-vectorize`，保留 `-O3` 和循环向量化。采用保守的整项 SLP 规避，覆盖可能由其他 SLP 形状触发的同类 shuffle；没有按 part_23、模块或信号名称匹配。

检测使用调用方的 `CXX/CPPFLAGS/CXXFLAGS` 预定义宏。GCC、Clang 19、AArch64 目标和显式 `-mssse3` 的探针均不追加标志。单体 PCH 与对象采用一致选项。没有给 Verilator 添加兼容标志，也没有修改其调度或默认编译选项。支持其他生成/构建系统的调用方如果绕开生成 Makefile，需要自行应用对应规避或使用已验证的编译器/目标组合。

独立 `grhsim-compiler-compat` CTest 以 GCC 和 PATH 中的 Clang21 编译并运行真实回归 fixture，通过；去掉兼容标志时该 fixture 的原错误仍可复现。首次整库重编译使用冻结的 generated C++ 加生产兼容片段，约 281.49 s，`N=32/C=30000` 通过 NEMU Difftest：27,809 instructions、PC=`0x80000442`、cycleCnt=29,996。该结果先隔离验证编译器修复，不等同于新的最终 walltime 对比。

### 6.3 重新生成时发现的标准流边界修正

从冻结 JSON 重新生成时，第 4 节所述“拒绝所有文件操作”的后加检查拦截了香山断言的 `$fwrite(32'h80000002, ...)`。这是标准错误流，不依赖各模型的 fopen 表。不能删除断言或跳过检查来掩盖问题，因此补充了通用例外：仅允许 `$fwrite/$fdisplay` 的直接、已知、32 位常量标准流描述符 `1/0x80000001`（stdout）、`0x80000002`（stderr）。动态句柄和 fopen/ferror/fflush/fclose 仍明确拒绝。

同时修正 GrhSIM runtime 对带高位的标准输出/错误描述符的解析。原 runtime 只识别内部 1/2，可能使该标准错误描述符的文字输出丢失；DPI 断言仍独立存在。新增小模型真实输出检查，验证 stdout/stderr 分流，保留六类私有句柄负向测试。这是对第 4 节边界的增量修正，不声称已支持跨分区共享文件句柄。

复现产物统一在 `build/repcut_grhsim_20260925/`：`clang_diagnosis/` 为定位与单函数重放，`clang_fixed/` 为冻结 generated C++ 重编译，`clang_fresh/` 为修复后的重新生成/构建。后续完整链路与性能结果在本节继续补充。

### 6.4 最终生成、验证与 walltime

重新 read+emit 全部 32 个模型成功，耗时 526.464 s。所有 generated C++ 与头文件逐文件比对后，复用 7,426 个内容与依赖头均相同、已使用兼容标志编译的对象；其余源文件重新编译，再重新建立 archive/链接。生成包未修改函数计算或分区，标准流 runtime 修正进入新包。该过程不是只替换 part_23，也不是重用未加兼容标志的 Clang 对象。

- 新生成包 `clang_fresh/emu`：N=32/C=30000 的 NEMU Difftest 通过，27,809 instructions、PC=`0x80000442`；冻结源码兼容构建另通过 N=1/C=10000，458 instructions、PC=`0x800027c6`。
- `emit-grhsim-cpp`、`emit-verilator-repcut-package`、`emit-grhsim-repcut-package` 全部通过，最终一轮合计 329.79 s；其中包含标准流 stdout/stderr 实际输出与私有文件句柄拒绝测试。Python API 4/4、playground flow 4/4 通过。
- 独立编译器回归还覆盖 `CPPFLAGS=-include cstdint`：检测只接收唯一标记，避免把强制 include 的预处理文本误作编译参数。该检测修正不改变普通构建的最终编译标志。
- 与先前 HEAD 生成的 Verilator fixture 比较，除输出目录造成的 `.f` 绝对路径变化及新增 GrhSIM 子目录外，原 Verilator 产物一致；原模型与 ELF 均未重建/覆盖。

在编译任务结束后，node030 CPU96–127，N=K=32、NUMA1、fixed ASLR、all-spin、同一冻结分区和 C=30000 做 4 对 AB/BA/AB/BA。A 为原 Clang21-Verilator 配置，B 为 Clang21-GrhSIM `-O3` 加自动兼容处理；外层仍沿用无显式 `-O` 的 Clang harness。不要求严格空闲率门槛，保留全部通过样本。两端各 4 次均通过 Difftest 和完整 runtime-config 检查，ELF/镜像/NEMU 身份在测量前后不变。

| 对次 | 顺序 | Verilator wall / s | 修复后 Clang-GrhSIM wall / s |
| ---: | --- | ---: | ---: |
| 1 | AB | 6.72 | 5.44 |
| 2 | BA | 6.73 | 5.44 |
| 3 | AB | 6.73 | 5.43 |
| 4 | BA | 6.70 | 5.49 |

walltime 中位数 **6.725 → 5.440 s，减少 19.11%（1.236×）**；Host 中位数 **6.6430 → 5.4085 s，减少 18.58%**。四对均更快，walltime 逐对减少 18.06%–19.32%。最大 eval 仍为 part_3，eval 中位数约 75.3885 → 47.4085 µs/step；这不是 walltime 的同口径数字。

最终补验：新生成包也完成 N=1/C=10000，458 instructions、PC=`0x800027c6`；检测过滤修正后 `grhsim-compiler-compat`（0.82 s）及两种 package CTest（44.43 s）再次全部通过。

### 6.5 社区记录与新版本状态（2026-09-25）

检索 LLVM 官方 issue、pull request 和 release notes，暂未找到与本次“Clang 21.1.5、x86/SSE2、SLP shuffle 将无效 lane 混入有效结果”完全对应的公开条目或修复提交。

社区中存在相关但不能等同的 SLP/水平归约问题，例如 [LLVM issue #57078](https://github.com/llvm/llvm-project/issues/57078) 讨论 `slp-vectorize-hor-store` 引起的异常性能，[issue #58567](https://github.com/llvm/llvm-project/issues/58567) 涉及激进向量化导致的系统崩溃，[issue #107418](https://github.com/llvm/llvm-project/issues/107418) 涉及 Clang 20 开发版本在激进 SLP 配置下崩溃。这些条目证明该优化区域已有历史问题，但没有证明它们就是本次错误。

公开 release 信息显示 LLVM 21 系列有后续 `21.1.x` 补丁版本，LLVM 22/23 也有更新版本；但 [LLVM 21.1.8 发布说明](https://discourse.llvm.org/t/llvm-21-1-8-released/89144)、[LLVM 23.1.2 release](https://github.com/llvm/llvm-project/releases/tag/llvmorg-23.1.2) 和 [Clang Release Notes](https://clang.llvm.org/docs/ReleaseNotes.html) 中没有找到该 SSE2/SLP 错误的明确修复说明。因此目前不能声称 Clang 21.1.8、22 或 23 已修复。

本机当前只有 Clang 21.1.5。后续拿到新版本后，应直接编译同一份 `wolvrix/tests/emit/data/grhsim_clang_sse2_reduction.cpp`，分别运行默认 x86/SSE2、`-mssse3` 和兼容选项三组；只有 fixture 正确且完整香山 N=1/C=10000 通过，才能移除对应版本的规避。当前兼容处理继续保留。

计算方式为 `1 - median(B) / median(A)`。不能拿本批 Clang-GrhSIM 5.440 s 与第 5 节不同时段的 GCC-GrhSIM 6.305 s 直接算编译器收益；本批仅正式测量原 Clang-Verilator 对修复后 Clang-GrhSIM，也不声称关闭 SLP 本身带来性能提升（未修复版本功能错误）。数据见 `ab_c30000_clang_fixed/{manifest.json,runs.csv,pairs.csv,summary.json,backend_summary.json}`。新 ELF SHA256=`f78bdbdf114af3b7d2bd3cb0213e0fda021e9ce90e52d52dbf666da008d21ce2`。

### 6.6 增量验证：用户安装的 Clang 23.1.2（2026-09-25）

用户新增 `/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64` 后，在 node030 CPU96–127 实测。编译器报告 `clang version 23.1.2`，LLVM revision=`85ac560262434c9ccfc0c183ec22d4138ed647fb`。此结果更新 §6.5 中“只有 Clang21、未验证新版本”的当时状态。

独立 fixture 的计算函数与 main 分别编译、链接；默认 x86/SSE2 `-std=c++20 -O3`、额外 `-mssse3`、额外 `-fno-slp-vectorize` 三组均通过。默认组没有添加后两种标志，已无法复现 Clang21 的原错误。尚未定位使结果恢复正确的 LLVM 提交，不外推 Clang22 或其他 21.x 补丁版本。

完整模型使用 §6.4 新生成的同一份 C++，在独立 `clang23/package` 中清理后重编，共 7,454 个对象，模型构建耗时 277.86 s。编译日志与 archive 的 `.comment` 核查确认全部模型对象由 Clang23 编译，没有混用旧对象；无 `-fno-slp-vectorize`、`-mssse3` 或 `-march`。原故障函数源码保持相同。现有兼容条件只匹配 Clang major=21，Clang23 自动采用正常 `-O3`。

先共用原 Clang21 外围的 40 个对象，隔离模型编译器变化；随后通过 Difftest `make emu` 在独立 `clang23/full-build` 下将这 40 个外围对象也全部用 Clang23 重编（保持原无显式 `-O` 配置）。两种构建均通过以下检查：退出码 0、实际启用 NEMU Difftest、无 mismatch/ABORT，且完整功能签名相同。

| 配置 | 指令数 | cycleCnt | Guest cycles | PC | step 数 |
| --- | ---: | ---: | ---: | --- | ---: |
| N=1、C=10000 | 458 | 9996 | 10001 | `0x800027c6` | 20102 |
| N=32、C=30000 | 27809 | 29996 | 30001 | `0x80000442` | 60102 |

另外在编译结束后，以同一外围对象、NUMA1、fixed ASLR、all-spin、N=K=32、C=30000 做 4 对 AB/BA，A 为 Clang21 `-O3` 加兼容选项，B 为 Clang23 正常 `-O3`；保留全部通过样本，runtime-config 和输入身份检查均通过。

| 对次 | 顺序 | Clang21 兼容版 wall / s | Clang23 wall / s |
| ---: | --- | ---: | ---: |
| 1 | AB | 5.49 | 5.40 |
| 2 | BA | 5.58 | 5.58 |
| 3 | AB | 5.47 | 5.44 |
| 4 | BA | 5.48 | 5.43 |

walltime 中位数 **5.485 → 5.435 s，减少 0.91%**；Host 中位数 **5.4495 → 5.4010 s，减少 0.89%**。walltime 为三对更快、一对相同，逐对减少中位数 0.73%；最大分区 eval 中位数 **47.6620 → 44.7355 µs/step，减少 6.14%**。因此本次主要结论是 Clang23 正常优化下功能正确，walltime 仅有小幅改善；该差值同时包含编译器版本与 SLP 启用状态的变化，不能单独归因为 SLP。此批性能数据使用相同 Clang21 外围，不与全 Clang23 构建的单次功能运行混算，也不与前一批 Verilator 数字跨批计算收益。

数据统一在 `build/repcut_grhsim_20260925/`：`clang23/model-build.log`、`clang23/full-build.log` 为构建记录，`clang_diagnosis/clang23_{,full_}n{1_c10000,32_c30000}.log` 为功能记录，`ab_c30000_clang21_clang23/` 保存全部 AB/BA 日志、manifest、runs/pairs/parts 与 summary。模型隔离 ELF=`clang23/emu`，SHA256=`52979c0f2e9047baf6fb7ae4e1908d0d8146a65cc3bd155484529e15969abf66`；全 Clang23 ELF=`clang23/full-build/grhsim-compile/emu`，SHA256=`e1459eb575d6dcd700cd7079ae2fd5f0574afeb2bd8cce787364e9c8bd22f67c`。保留 Clang21 的兼容处理；本次没有修改编译器或后端默认选择。

## 7. 增量实验：Clang23 三组完整对比（2026-09-25）

用户要求比较 Verilator `-Os`、Verilator `-O3` 与 GrhSIM `-O3`，同时记录编译 walltime，并放入同一份 HTML 时空图。此节为同一后端接入主题的后续实验，不修改前述历史数据。

### 7.1 口径与执行计划

三组继续使用 §5.1 的冻结 32 分区、CoreMark 镜像、NEMU 和 node030 CPU96–127，N=K=32、NUMA1、fixed ASLR、all-spin。所有模型、框架和外围对象均使用 Clang23.1.2；Verilator 两组的 FAST/SLOW 模型分别统一 `-Os` 或 `-O3`，框架及外围均为 `-O3`；GrhSIM 三层均为 `-O3`。这与 §5 的 Verilator 默认 FAST=`-Os`、SLOW 未显式优化、外围未显式优化不同，不跨批拼接数据。

编译采用独立输出目录、删除对象缓存的效果由不复制 `.o/.a/.d/.gch/.pch` 保证，三组各自完整编译，固定 24 路共享编译并行、禁止对象缓存。单独统计已有 generated C++ 到最终 ELF 的编译/链接 walltime；代码生成另列，不把 GrhSIM 已有静态库的增量链接时间当作完整编译时间。文件系统页缓存不清空，称“无旧对象的全量构建”，不称磁盘冷缓存。实验脚本为 `build/repcut_grhsim_20260925/build_threeway.py`，记录到 `clang23_threeway/`。

运行测试设 C=10000 与 C=30000 两个窗口。每个窗口先对三组做 C100 初始化检查，再执行三组的六种排列各两次（ABC、ACB、BAC、BCA、CAB、CBA，循环两遍），每组共 12 个正式样本。这样每组在第一/第二/第三位置各出现 4 次，任意两组的先后顺序各 6 次。保留全部通过样本，无速度筛选；沿用原完整 Difftest 签名、runtime-config、32 分区 timing 与 ELF/输入身份核验。执行脚本为 `compare_clang23_three.py`。

HTML 采用各 run 的每 step 平均耗时再取跨 run 中位数，展示三组总时间、各轮原始数据、Host 全局阶段、32 个分区自身 eval/update，以及编译时间。时空图按阶段起点对齐重建；未采逐事件 trace，留白只能表示“阶段剩余跨度”，不能精确拆成忙等待或调度开销。`input_apply` 在当前源码中由 Host 串行加载，各分区的该项不能画成 worker 同时执行。结果待本轮构建/运行完成后在本节追加。

### 7.2 三组编译与运行结果

三组完整构建及全部对象编译器审计通过：两组 Verilator 各 1,307 个模型对象与 47 个外围/框架对象；GrhSIM 7,454 个模型/框架对象与 40 个外围对象，全部为 Clang23.1.2。每次构建均为 24 路，包含 PCH、编译、归档及最终链接，下面使用各命令 walltime 之和，排除脚本写 manifest 的毫秒级开销。构建仅各测一次，Os/O3 约 4 s 的差异不作为编译速度的稳定结论。

| 指标 | Verilator Os | Verilator O3 | GrhSIM O3 |
| --- | ---: | ---: | ---: |
| 完整 C++ 编译/链接 walltime | 170.899 s | 166.866 s | 288.500 s |
| C=10000 进程 walltime 中位数 | 2.480 s | 2.360 s | 1.670 s |
| C=10000 Host 中位数 | 2.4330 s | 2.2995 s | 1.6250 s |
| C=30000 进程 walltime 中位数 | 7.320 s | 6.945 s | 5.985 s |
| C=30000 Host 中位数 | 7.2680 s | 6.8845 s | 5.9415 s |

GrhSIM 完整编译为模型/框架 284.426 s，加外围与最终链接 4.074 s；不能只拿后者对比 Verilator 全量构建。以上运行不含编译时间。最后构建结束于 15:27:04 UTC，首批采样开始于 15:27:32 UTC，没有编译与运行重叠。两窗口三组共 72 个正式样本及 6 个 C100 启动检查均通过，完整 Difftest 签名见 §6.6；输入/ELF 哈希前后不变。

| walltime 减少口径：`1 - median(候选) / median(参照)` | C=10000 | C=30000 |
| --- | ---: | ---: |
| Verilator O3 相对 Verilator Os | 4.84% | 5.12% |
| GrhSIM O3 相对 Verilator Os | 32.66% | 18.24% |
| GrhSIM O3 相对 Verilator O3 | 29.24% | 13.82% |

每个窗口内，三种两两比较的候选均为 12/12 轮更快。C30000 的 GrhSIM 对 Verilator O3 逐轮减少范围 11.88%–14.86%，逐轮减少中位数 13.90%；后者与表中的中位数之比 13.82% 不是同一个统计量。C10000 尚主要覆盖启动阶段（只提交 458 条指令），C30000 提交 27,809 条指令，不能把较短窗口的 29.24% 外推为较长窗口收益；本实验仍是固定周期窗口，不是完整 CoreMark 跑分。

### 7.3 阶段与分区分析

C=30000，每项为 12 次运行各自每 step 均值的中位数，单位 µs/step：

| 指标 | Verilator Os | Verilator O3 | GrhSIM O3 |
| --- | ---: | ---: | ---: |
| Host input_load | 4.4250 | 4.5485 | 4.2985 |
| Host 全局 eval，含阶段同步 | 88.6380 | 83.7430 | 65.7225 |
| Host 全局 update，含阶段同步 | 26.4330 | 24.6665 | 27.7345 |
| 最大分区 eval，三组均为 part_3 | 82.5990 | 81.5945 | 47.7625 |
| 每次 run 的最大分区 update | 20.4780 | 20.0885 | 22.8445 |
| 所有分区 eval 累计跨度 | 1305.2825 | 1252.8870 | 611.4595 |

GrhSIM 相对 Verilator O3 的主要改善在 eval；update 反而更长。两组 Verilator 的 update 中位数最大者为 part_20，GrhSIM 为 part_5。part_3 自身 eval 下降不能等比例换算为全局 eval 或最终 walltime：阶段还包含调度、同步和其他分区，各 step 的最慢者也可能变化。当前数据不直接区分缓存/内存/忙等机制，不把这些差值单独归因于通信字节数。

三组均含生成框架现有的无条件 step/partition 计时代码；`XS_REPCUT_STEP_TIMING=0` 不能移除它们。当前冻结包 early eval/update 列表为空，因此三段对齐重建适用。分区 input_apply 由 Host 串行执行，按目标分区记录；并非每个 worker 同时加载输入。

计时边界补充：源码中 Host 从 `Emulator` 的 `elapsed_time(uptime())` 成员初始化起，到析构函数后段打印前截止；`dut_ptr` 的初始构造先于该起点，部分其他初始化与清理在区间内。因此 Host 不能精确称为“纯仿真循环时间”；进程 walltime 才完整覆盖进程启动和退出。此说明细化此前简略描述。

数据见 `build/repcut_grhsim_20260925/three_clang23_c{10000,30000}/` 的 manifest、runs/parts/pairs JSON/CSV、summary 和每次原始日志。交互图见 [Clang23 三组性能与平均 step 时空图](../../build/repcut_grhsim_20260925/clang23_backend_compare.html)：两窗口、三组共享时轴、walltime/Host、逐轮样本、分区指标筛选、参照与变化比例切换、CSV 导出、编译时间及 ELF/输入证据。图中灰色不表示 CPU 空闲，所有分区时间之和不是 walltime。

正式页面经 Chromium 离线验证：两个窗口各 96 条线程行的 eval/update 条长逐项核对原始数据，384 项全部一致；切换周期、参照、指标、排序、缩放、tooltip、CSV 和移动布局均通过，未发生 JS 错误或外网请求。原始 78 次记录另经独立 analyzer 重新解析，72 次正式样本及汇总数值全部一致。

### 7.4 编译计时与代码生成边界补充

§7.2 的三个编译 walltime 均从已生成 C++ 开始，到最终仿真 ELF 链接完成为止；不包括 RTL 导入、优化、分区以及后端 C++ 代码生成。GrhSIM 的 288.500 s 是完整编译，而不是复用已有模型库后的 4.074 s 外围构建。

另行测得 Verilator 从已有分区 SV 执行 32 个 `--cc`、最多 24 路并行的代码生成 walltime 为 **43.402 s**，生成 `.cpp/.h` 与用于本次编译的冻结包逐文件一致，记录见 `clang23_threeway/verilator_codegen/manifest.json`。两种后端的生成起始输入不同，GrhSIM 从分区 JSON 开始且需读入 JSON；本轮未取得可用的 GrhSIM 生成时间，因此不计算端到端生成加编译的后端加速比，也不把缺失项当作零。这不影响三组完整 C++ 编译与仿真 walltime 的对比。

### 7.5 增量归因：GrhSIM 全局 eval 与最大分区 eval 的差距（2026-09-29）

针对 C=30000 时 GrhSIM 全局 eval 中位数 `65.7225 us/step` 明显高于最大分区自身 eval `47.7625 us/step` 的现象，新增诊断包 `build/repcut_grhsim_20260925/eval_gap_v2_c30000/`。探针每 127 step 采样一次，复用生成代码中已有的分区 eval 起止时钟，不改变调度；每个采样 step 记录：

```text
T = normal_eval_phase_end - normal_eval_phase_begin
D = max_i(part_i_eval_end - part_i_eval_begin)
P = max_i(part_i_eval_end - normal_eval_phase_begin)
```

因此 `T - max_i(mean(part_i_eval))` 被分成三项：

- `switching = mean(D) - max_i(mean(part_i_eval))`：每 step 的实际最慢分区在不同分区间轮换；
- `start_skew = mean(P - D)`：worker 被唤起、取到任务以及开始执行的错位；
- `finish_scan = mean(T - P)`：最后一个 eval 完成后，主线程观察/收齐完成状态的尾部。

三次 GrhSIM 与三次 Verilator O3 交错运行的 C=30000 中位数如下，单位均为 `us/step`：

| 后端 | `T` 全局阶段 | 最大分区平均值 | 每步实际最大 eval `mean(D)` | switching | start skew | finish scan |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| GrhSIM O3 | 59.519 | 45.117 | 56.239 | **11.122** | 2.776 | 0.451 |
| Verilator O3 | 76.577 | 74.665 | 74.672 | 0.000 | 1.231 | 0.645 |

这组 probe 的绝对 `T` 低于此前 12 次正式样本的 `65.7225`，原因是 probe 使用采样窗口、交错批次及当前机器运行状态；不能把两组绝对值直接相减。但分解关系在同一 probe run 内闭合，且机制结论不依赖这个绝对偏移。GrhSIM 的当前 probe gap 为 `59.519 - 45.117 = 14.402 us`，其中约 `11.122 us`（约 77%）来自逐 step 最慢分区轮换，约 `2.776 us` 来自启动错位，收尾扫描仅 `0.451 us`。因此不能把旧正式样本约 `17.96 us` 的全部差值称为 scheduler overhead。

窗口对照进一步说明这是工作负载阶段效应，而不是固定的框架常数。GrhSIM 早期窗口的 `switching/start_skew/finish_scan` 为 `0.626/1.345/0.499`，后期窗口变为 `16.386/3.523/0.417`；Verilator 早晚窗口 switching 均约 `0`，start skew 约 `1.23`。C=10000 全窗口 GrhSIM 的 switching 仅 `0.810`，与其较小的全局-最大分区差一致。

关键分区胜出频次也发生了变化：GrhSIM 早期 158 个采样中 `part_3` 约胜出 148--151 次；C=30000 后期 315 个采样中，`part_3` 仅约 57--61 次，`part_6` 约 43--47 次，`part_10` 约 46--49 次，`part_15` 约 54--59 次，`part_29` 约 64--65 次，另有 `part_28` 等少量胜出。Verilator 则几乎每个采样 step 都由 `part_3` 胜出（471--473/473）。这直接解释了为什么“最大分区的平均 eval”会低估全局阶段真正等待的最慢 eval。

结论：GrhSIM 的差距主要由其后端生成代码在长窗口中呈现的动态工作量变化，以及固定 all-spin 调度下的 worker 开始时间错位共同造成；不是主线程重复执行了一遍分区 eval，也不是完成扫描本身占据了十几微秒。下一步应优先分析 `part_6/10/15/29` 在后期窗口的 activation、memory-write staging 和 update-push 工作，或做按实际 step tail 进行调度/分区的优化；单纯继续压低长期平均最大的 `part_3` 不一定能减少 walltime。

本轮只新增 build 目录下的诊断包，没有修改生产后端、调度默认或 Verilator 路径。

### 7.6 C=100000 最慢分区分布（2026-09-29）

为确认 §7.5 的长窗口现象，将 C 拉长到 100000。仍使用 node030 CPU96–127、N=K=32、all-spin、Clang23/O3；每个后端运行 3 次，每 127 step 采样一次。为避免把启动/稳定/收尾阶段混在一起，早、中、晚窗口按执行 step 三等分，每个窗口每次 525 个样本。这里的“最慢分区”定义为单个采样 step 中 `part_i_eval_end - part_i_eval_begin` 最大的分区；另有 completion-critical 统计，但不作为主结论。

三次运行的中位数（单位 `us/step`）为：

| 后端/窗口 | 全局 eval `T` | 最大分区平均值 | 每步实际最大 eval `mean(D)` | switching | start skew | finish scan |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Verilator O3 / all | 77.214 | 74.957 | 74.957 | 0.000 | 1.503 | 0.718 |
| Verilator O3 / early | 76.978 | 74.776 | 74.777 | 0.000 | 1.481 | 0.721 |
| Verilator O3 / middle | 77.080 | 74.827 | 74.827 | 0.000 | 1.512 | 0.735 |
| Verilator O3 / late | 77.371 | 75.200 | 75.200 | 0.000 | 1.472 | 0.699 |
| GrhSIM O3 / all | 71.325 | 45.832 | 67.388 | 21.696 | 3.635 | 0.400 |
| GrhSIM O3 / early | 62.176 | 45.391 | 58.803 | 13.413 | 2.815 | 0.459 |
| GrhSIM O3 / middle | 74.308 | 46.773 | 70.075 | 24.226 | 3.950 | 0.383 |
| GrhSIM O3 / late | 77.490 | 45.453 | 73.078 | 27.450 | 4.140 | 0.357 |

三次运行合并后的“单步实际最长 eval”分布如下；总样本数为 4725（3×1575），括号内为占比：

| 后端 | 分布（按次数降序，低于 0.1% 的分区仍保留在原始日志） |
| --- | --- |
| Verilator O3 | `part_3=4723 (99.96%)`，`part_6=1`，`part_21=1` |
| GrhSIM O3 | `part_29=1284 (27.18%)`，`part_15=968 (20.49%)`，`part_3=903 (19.11%)`，`part_10=724 (15.32%)`，`part_6=421 (8.91%)`，`part_28=152 (3.22%)`，`part_18=145 (3.07%)`，`part_25=47 (0.99%)`，`其余分区合计 81 次 (1.71%)` |

GrhSIM 分窗口的主分布更能说明变化：

| 后端/窗口 | 最慢分区分布 |
| --- | --- |
| GrhSIM / early | `part_3=677 (43.0%)`，`part_29=237 (15.0%)`，`part_15=201 (12.8%)`，`part_6=179 (11.4%)`，`part_10=161 (10.2%)` |
| GrhSIM / middle | `part_29=489 (31.0%)`，`part_15=364 (23.1%)`，`part_10=249 (15.8%)`，`part_3=162 (10.3%)`，`part_6=131 (8.3%)` |
| GrhSIM / late | `part_29=558 (35.4%)`，`part_15=403 (25.6%)`，`part_10=314 (19.9%)`，`part_6=111 (7.0%)`，`part_3=64 (4.1%)` |

因此，C=100000 下的结论比 C=30000 更清楚：Verilator 的 `part_3` 是稳定的静态瓶颈；GrhSIM 的长期平均最大分区仍是 `part_3`，但它不是大多数后期 step 的实际 tail。GrhSIM 在后半程主要由 `part_29/15/10` 轮换，导致 `mean(D)` 比最大分区平均值高约 21.7 us/step，并随阶段从 13.4 增至 27.5 us/step；`finish_scan` 只有约 0.4 us/step，不能解释差距。优化方向应继续针对后期多个实际 tail 分区及其动态工作量，而不是只压低 `part_3` 的平均 eval。

原始日志与 manifest：`build/repcut_grhsim_20260925/eval_gap_v5_c100000/`（Verilator）和 `build/repcut_grhsim_20260925/eval_gap_v6_c100000/`（GrhSIM）。本轮仍只新增诊断探针与 build 目录内容，没有修改生产后端或默认调度策略。

### 7.7 GrhSIM 瓶颈分区的条件 eval 均值（2026-09-29）

在同一批 C=100000 的 GrhSIM O3 采样上，诊断探针进一步记录 `part_i` 成为该采样 step 的最长 eval 分区时，该分区自身的 eval duration。下表把本轮新执行的 3 次运行、共 4725 个采样合并；`n` 是该分区胜出的采样数，`avg` 是条件均值 `mean(eval_i | i 是该 step 的最长分区)`，单位 `us/step`。这不是该分区在所有 step 上的无条件平均值；因此胜出次数与 §7.6 另一批独立运行的分布不完全相同。

| part | n | 条件 eval avg |
| --- | ---: | ---: |
| part_3 | 872 | 44.017 |
| part_6 | 443 | 55.943 |
| part_7 | 2 | 52.941 |
| part_8 | 1 | 45.951 |
| part_9 | 1 | 56.051 |
| part_10 | 751 | 58.434 |
| part_13 | 2 | 47.160 |
| part_14 | 15 | 55.352 |
| part_15 | 947 | 63.967 |
| part_17 | 4 | 47.517 |
| part_18 | 149 | 53.507 |
| part_20 | 6 | 52.815 |
| part_21 | 11 | 55.968 |
| part_22 | 2 | 54.275 |
| part_25 | 42 | 57.600 |
| part_26 | 19 | 58.942 |
| part_27 | 34 | 58.256 |
| part_28 | 140 | 61.066 |
| part_29 | 1284 | 96.958 |

稳定瓶颈主要是 `part_29`、`part_15`、`part_10`、`part_3` 和 `part_6`：它们合计 4297/4725（90.94%）次胜出。`part_29` 虽然在 all-window 的胜出次数最多，但其条件均值也最高，说明它不是仅靠偶然调度成为瓶颈，而是在成为 tail 时确实承担了约 97 us 的 eval 工作。按窗口观察，`part_29` 的条件均值从 early 的 99.790 降到 late 的 95.198，而胜出次数从 237 增至 558；`part_10` 则从 54.741 增至 60.787，`part_6` 从 54.155 增至 60.514。后期 tail 轮换因此既来自胜出频次变化，也来自各分区条件工作量随仿真阶段变化。

本节数据来自 `build/repcut_grhsim_20260925/eval_gap_v11_c100000/` 的三份原始日志；仅使用诊断探针新增的条件统计字段，没有修改生产后端、分区或调度默认值。

### 7.8 瓶颈分区的长尾形态与性能归因（2026-09-29）

为区分“每一步都重”和“只有少数 step 突然变重”，对同样的 C=100000、GrhSIM O3、3 次独立运行（共 4725 个采样）记录五个主要瓶颈分区的 eval duration 分位数。这里的分位数是该分区在所有采样 step 上的 duration，不是只筛选该分区成为全局最长者后的条件分布。

| part | P50 (us) | P90 (us) | P99 (us) | max (us) | 形态 |
| --- | ---: | ---: | ---: | ---: | --- |
| part_3 | 44.99 | 51.75 | 59.50 | 71.62 | 持续重负载，分布较窄 |
| part_6 | 44.51 | 59.08 | 70.93 | 78.03 | 稳定负载上叠加中等长尾 |
| part_10 | 39.01 | 59.28 | 75.59 | 91.50 | 缓存/选择网络导致的混合型长尾 |
| part_15 | 19.65 | 63.61 | 73.19 | 91.64 | 轻量多数 step，少数固定点尖峰 |
| part_29 | 3.94 | 99.60 | 107.08 | 123.27 | 极强双峰，少数激活波成为 tail |

这组分位数与 §7.7 的条件均值相互印证：`part_29` 的无条件中位数只有约 4 us，但它一旦成为最长分区，条件均值约 97 us；`part_15` 的中位数约 20 us，成为瓶颈时约 64 us。它们不是静态代码一直很慢，而是某些 step 触发了额外的激活传播或固定点重跑。相反，`part_3` 的 P50 已接近 45 us，P90 只升到约 52 us，成为瓶颈时约 44 us，说明它本身每一步都在稳定地消耗大量 eval 时间。

结合生成模型结构，目前可以把“成为瓶颈的原因”和“瓶颈时具体在做什么”分成以下五类：

| part | 成为瓶颈的主要原因 | 瓶颈时的主要工作形态 | 证据强度 |
| --- | --- | --- | --- |
| part_29 | 条件性激活波，少数 step 的工作量从约 4 us 跳到 100 us 量级 | 无显式 Memory reader；大组合 scheduler 中反复传播 `supernode_active_curr_[]`，并由 `pending_eval_round` 触发固定点重复执行 | 动态分布和代码结构已确认；具体额外轮数尚未直接计数 |
| part_15 | 条件性控制/预测状态传播，P90 远高于 P50 | 两个 512 项 MicroTageTable 及大量展开的 concat/compare/select；commit 后激活 reader 可能触发下一轮 | 结构和长尾已确认；reader 重激活占比仍是机制推断 |
| part_10 | 基础 I-cache 工作量较大，且部分 step 激活更多 cache reader | 多 bank、multi-way I-cache meta/data 读出，约 128 项展开 compare/select/mux；同时存在固定点重跑 | 生成代码热点明确；各子路径运行时占比尚未直接计数 |
| part_6 | ROB/DCache 的稳定工作叠加提交、写回和事件传播 | DCache tag/data、多 bank 状态和 ROB 阵列的 memory staging，随后进入较大的 commit scheduler；其 42 B event-edge storage 是五者最大 | 结构明确；cache、ROB、commit 三者的精确比例仍是机制推断 |
| part_3 | 不是偶发事件，而是自身成为长期重分区 | 341 个 compute batch + 5 个 commit batch，L2 directory/cache/queue 等大量 Memory 状态，形成最长的固定点调度链 | 持续时间分布与静态结构均已确认 |

五个分区的生成常量也说明了这一差异：`part_3` 有 346 个 batch、14450 个 write，属于深而稳定的逻辑锥；`part_29` 只有 149 个 batch、422 个 write，却能在少数 step 达到约 100 us，说明其问题不能用静态代码规模解释，而应优先检查激活传播和固定点轮数；`part_10` 的 write 数最高（24923），`part_6` 的 event-edge storage 最大（42 B），它们更像 memory/update 与组合逻辑混合的瓶颈。

因此当前优化优先级应分两条线：

1. 对 `part_29`、`part_15`，优先增加临时的 fixed-point round、compute/commit batch 激活次数计数，验证长尾是否确实由重复轮次造成；在没有该计数前，不应把某个具体 scheduler 函数直接认定为唯一热点。
2. 对 `part_10`、`part_6`、`part_3`，再做 batch/reader 级的累计耗时统计。`part_3` 适合做持续性大 ASC 的后端优化，`part_10/6` 则应分别观察 memory-reader staging、compare/select 和 commit/update 的实际比例。

本节新增探针原始日志位于 `build/repcut_grhsim_20260925/eval_gap_v13_c100000/`；强制重编了探针所依赖的 GrhSIM package，未修改生产后端代码、分区结果或默认调度策略。

### 7.9 整体硬件计数旁证（2026-09-29）

在同一 node030、CPU 96--127、all-spin、C=100000 条件下，对重新编译的 GrhSIM 探针运行一次 `perf stat`。这是整个仿真进程的 32 线程聚合计数，不是按 part 分摊的计数：

| counter | value |
| --- | ---: |
| cycles | 1.099e12 |
| instructions | 3.022e11 |
| instructions/cycle | 0.83 |
| cache-misses | 1.069e11 |
| branches | 4.824e10 |
| branch-misses | 7.499e9 (15.54%) |

低 IPC 和较高的 cache/branch miss 与前面看到的大量展开 scheduler、active-mask 判断、compare/select 网络相吻合，说明瓶颈不只是线程同步等待，也包含生成代码自身的前端和存储层次压力。但该计数不能回答“part_10 的 cache staging 占多少”或“part_29 的长尾由哪一个 scheduler 占多少”，因此只作为全局旁证；后续若要完成分区级归因，仍需在生成 eval 内做 fixed-point round、batch/reader 累计耗时的临时计数。

原始计数日志：`build/repcut_grhsim_20260925/eval_gap_perfstat_c100000.log`。

### 7.10 热点分区 compute/commit 阶段归因（2026-09-29）

为继续区分“固定点重复执行”和“单轮内部工作量突然变重”，在同一 node030、CPU 96--127、N=K=32、all-spin、GrhSIM O3、C=100000 条件下，对 `part_3/6/10/15/29` 增加了仅用于诊断构建的阶段计时：每个固定点 round 分别累计 compute batches 和 commit batches 的耗时。三次运行共 4725 个采样；下表为三次运行的均值，单位为 `us/step`。`critical` 只取该分区成为单步最长 eval 分区的样本。

| part | compute mean | compute P50/P90/P99 | commit mean | critical compute | critical commit | critical rounds |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| part_3 | 39.28 | 37.45 / 46.82 / 52.63 | 2.67 | 37.65 | 3.15 | 1.55 |
| part_6 | 32.74 | 33.94 / 52.82 / 64.34 | 2.74 | 49.01 | 1.24 | 1.85 |
| part_10 | 31.27 | 33.19 / 50.02 / 62.84 | 3.55 | 48.02 | 8.43 | 2.00 |
| part_15 | 24.24 | 20.32 / 61.63 / 71.13 | 0.64 | 61.46 | 1.33 | 2.00 |
| part_29 | 29.28 | 1.79 / 96.57 / 104.77 | 0.19 | 93.63 | 0.05 | 1.00 |

这组数据把前一节的机制推断进一步收紧：

1. `part_29` 的长尾几乎完全发生在 compute 阶段。它的无条件 P50 只有约 1.8 us，但 P90 已达约 96.6 us；成为瓶颈时 compute 平均约 93.6 us，而 commit 仅约 0.05 us，且瓶颈样本固定点平均只有 1 轮。因此它不是“commit 慢”或“多轮收敛”造成的，而是某些输入状态触发了 scheduler/active-mask 组合路径的大规模单轮传播。
2. `part_15` 的瓶颈样本 compute 约 61.5 us、commit 约 1.3 us，瓶颈时稳定为 2 轮，而全体样本平均约 1.29 轮；这说明 MicroTage 控制/预测逻辑的额外 fixed-point round 确实参与了其长尾，但主要耗时仍在 compute，不在 commit。
3. `part_10` 的瓶颈样本约为 48.0 us compute + 8.4 us commit。它既有 cache compare/select 的 compute 尾部，也有明显高于普通样本的 commit 尾部；瓶颈时为 2 轮，不能只看静态 batch 数量。
4. `part_6` 的瓶颈样本 compute 约 49.0 us，明显高于无条件均值 32.7 us，而 commit 仍很小；其主要问题是 DCache/ROB 相关 compute 激活量变化，固定点重复只是次要因素。
5. `part_3` 的 compute 分布最稳定，critical compute 甚至略低于无条件均值；其长期瓶颈来自持续的基础工作量，而不是长尾事件或 commit 阶段。

因此下一步不应继续只按“平均 eval 最大”优化：`part_29` 应检查通用的 active-mask/scheduler 批次在不同输入状态下的激活规模，`part_15` 应检查跨 round 的 reader 重激活，`part_10` 应拆分 memory-reader staging 与 commit/update。当前阶段计时还没有细到单个 batch，不能据此把某个具体生成函数认定为唯一热点；后续应增加按 batch 累计的通用计数，再评估可泛化的后端规则。

本节仅使用 `build/repcut_grhsim_20260925/eval_gap_v15_c100000/` 的三次有效诊断日志；阶段计时和轮数 probe 均只存在于 ignored 的临时构建目录，没有修改生产后端、分区结果或默认调度。

### 7.11 生成 batch 级热点定位（2026-09-29）

为把 §7.10 的 compute/commit 阶段继续细分，在临时诊断构建中给五个主要瓶颈分区的每个生成 batch 加了 RAII 计时。`bN` 表示 `eval_compute_batch_N()`，`cN` 表示 `eval_commit_batch_N()`；日志中的 `ordinary/critical` 分别是该 batch 在所有采样、以及该分区成为最长 eval 分区的采样中的平均时间，单位为 `us/step`。这项计时包含 batch 的 active-mask 检查和调度开销，因此用于相对定位，不把它当作无探针 walltime。

C=30000 的单次校验通过；C=100000 在 node030、CPU 96--127、all-spin、GrhSIM O3 下完成 3 次运行（每次 1575 个采样）。三次 all-window 结果中稳定出现的前 8 个 batch 如下，数值是三次运行的均值：

| part | 主要 batch（ordinary / critical, us） | 生成代码形态 |
| --- | --- | --- |
| part_29 | `b137=4.53/14.57`，`b138=3.69/13.49`，`b139=3.12/10.83`，`b140=3.06/9.11`，`b145=2.87/8.72` | 连续的 compute batch；注释中的 supernode 从 1095--1126，属于同一段 active-mask 调度链 |
| part_15 | `b130=3.42/15.74`，`b131=3.33/10.50`，`b132=3.82/9.13`，`b129=3.54/9.09`，`b135=3.18/8.43` | 连续 compute batch；supernode 1030--1085 一带的控制/预测状态传播 |
| part_10 | `b146=1.90/3.31`，`c174=1.73/3.05`，`b15=1.74/2.96`，`c173=1.51/2.53`，`b17=1.43/2.48`，`c175=1.20/2.09` | compute 与 commit 交错；既有 I-cache compare/select，也有事件驱动 commit batch |
| part_6 | `b184=7.45/10.00`，`b6=0.70/1.53`，`b7=0.62/1.38`，`b159=0.46/1.36`，`b158=0.45/1.35` | 以 compute 为主；b184 覆盖 ROB/DCache 相关的一组较大的 active supernode |
| part_3 | `b46=1.87/2.34`，`c344=1.27/1.64`，`c343=0.79/1.00`，`c345=0.69/0.89`，`b333=0.67/0.83` | 346 个 batch 分散承担工作；单个 batch 占比小，包含大量 L2 directory/cache/queue 状态更新 |

这组数据给出三个比单纯看分区平均时间更具体的结论：

1. `part_29` 的长尾不是由一个孤立函数造成，而是由 `b137--b140` 等相邻 compute batch 组成的连续激活簇。它们的 critical 时间约为 ordinary 的 3--4 倍，并且三次运行的 batch 排名、编号和数值都稳定。结合 §7.10 中“critical compute 约 93.6 us、critical commit 约 0.05 us、critical rounds 约 1”的结果，当前最合理的归因是：某些输入状态让这一段 active-mask scheduler 同时展开更多 supernode；不是 commit 慢，也不是固定点重复。
2. `part_15` 的热点同样集中在相邻 compute batch，但 `b130` 单独就贡献约 15.7 us 的 critical 平均，且其余相邻 batch 仍有 8--10 us。它与 §7.10 中 critical rounds=2 相吻合，说明控制/预测状态传播会在第二轮再次激活一组相邻 batch；不过主要成本仍是 compute，而不是 commit。
3. `part_10` 是唯一明显的混合型：`b146/b15/b17` 的 compute 尾部与 `c173--c175` 的 commit 尾部同时出现。因此对它只优化 memory reader 或只优化 fixed-point round 都可能遗漏另一半成本。

静态生成代码大小也支持“连续批次簇”这一判断，但不能单独预测运行时间：例如临时 package 中 `part_29/b137` 约 2.2 MiB、`part_15/b130` 约 2.4 MiB，`part_10/c173` 和 `c175` 各约 6.0 MiB；`part_3` 的 `c343/c344` 虽然分别约 4.5/4.9 MiB，运行时却没有形成 p29 那样的长尾。这说明代码规模是必要的静态压力指标，但实际 tail 还取决于 active-mask 在当前 step 是否覆盖该 batch 内的 supernode。

因此下一步应优先做一种不绑定分区编号或信号名的后端规则：在生成 scheduler 时识别“连续 active-mask batch 簇”，计算其静态规模和跨 batch 依赖，再评估是否能把簇内的重复 mask/状态访问合并或降低无效扫描。实现前仍需保留当前 batch 级探针，确认优化减少的是 `critical` 激活簇时间，而不是只改变普通样本的代码大小。当前探针和日志位于 `build/repcut_grhsim_20260925/eval_gap_v16_validate_c30000/`、`build/repcut_grhsim_20260925/eval_gap_v16_c100000/`，未修改生产后端、分区结果或默认调度策略。

### 7.12 完整 active-word 命中率诊断：不支持直接生成 all-on 快路径（2026-09-30）

为验证 §7.11 提出的通用候选，在 GrhSIM emitter 中启用了临时 `full_active_word_profile`。该选项只统计普通 compute word 中 `dispatchMask=0xff` 且包含 8 个真实 supernode 的 active word，不改变调度和执行语义；默认关闭。诊断包基于现有 XiangShan RTL/filelist，在 node030 CPU96--127、Clang23/O3 生成并编译。

| C | Host time | all-off | all-on | partial | all-on / total | (all-on+partial) / total |
|---:|---:|---:|---:|---:|---:|---:|
| 100 | 0.466 s | 3,850,655 | 66,120 | 224,929 | 1.596% | 7.027% |
| 30,000 | 45.332 s | 795,394,691 | 21,666,630 | 83,445,307 | 2.406% | 11.673% |
| 100,000 | 174.849 s | 2,567,106,081 | 97,219,163 | 334,694,584 | 3.242% | 14.402% |

三个长度的 all-on 命中率都很低，且绝大多数候选 word 调用是 all-off；即使把 partial 也算作非空，仍不到 15%。因此“完整 active word 时跳过逐 bit guard”的静态快路径只能覆盖约 3% 的调用，无法解释当前 GrhSIM 的主要 tail，也不足以抵消新增分支/代码体积/编译压力。该候选不应默认启用；后续若继续优化，应针对 all-off 扫描本身或动态热点 batch 的状态访问，而不是复制生成 all-on payload。

本轮正式结论：否决直接 all-on active-word 快路径。保留 `full_active_word_profile` 作为可关闭的诊断选项，后续仅在其他 workload 或仿真器显示明显更高命中率时再复用。

### 7.13 与 Verilator 生成代码的调度对照（2026-09-30）

为寻找不依赖具体模块或信号名的后端优化，对同一份 `part_29` 的 Verilator 生成代码和 GrhSIM 生成代码进行了结构对照。Verilator 的 `eval_step()` 进入 root scheduler 后，使用紧凑的 `__VicoTriggered`、`__VactTriggered`、`__VnbaTriggered` 位图选择 region；例如 `eval_ico()` 只有触发位非零时才调用相应的 `ico_sequent` 函数，active/NBA 阶段也采用同样的 region-level trigger。该 part 约有 15 个 region，`VL_UNLIKELY` 只有 61 处，主要用于初始化、调试和不收敛保护。

GrhSIM 当前 `eval()` 的固定点循环则每轮无条件调用 66 个 compute batch 和 30 个 commit batch（共 96 个 batch），再由 batch 内的 active word 和 bit guard 过滤。生成包静态统计约有 8,013 个 word-level guard、58,639 个 bit-level guard。已有 C=100000 profile 显示候选 full active word 中 all-off 约占 85.6%，说明目前主要开销形态是“进入所有 batch 后做大量无效活动检查”，而不是缺少 `unlikely`。

因此，从 Verilator 得到的可迁移机制是 **batch/region-level trigger bitmap**：为每个 schedule batch 建立活动位；当某个 supernode 被激活时，除设置现有 `supernode_active_curr_` 外，同步标记其所属 batch；固定点循环只 dispatch 被标记的 batch，batch 内现有 active-word/bit guard 保留作为第二级过滤。实现时不能把 active word 简单映射为唯一 batch，因为同一 word 可能跨多个 batch，且各 batch 的 `dispatchMask/clearMask` 不同，必须按静态 batch-word-mask 关系维护触发集合。

本次对照没有直接修改生产调度器，也没有把 Verilator 的模块名或变量名特判搬入 GrhSIM。当前结论是：分支预测标注不是主要差异；下一步应先做 batch-level trigger bitmap 的语义原型和计数验证，再决定是否值得进行性能实现。

### 7.14 compute batch 入口守卫的计数与 A/B（2026-09-30）

先校正两处口径：§7.12 的 full-active-word 数据来自单体 `profile_codegen/emit_profile2`，不能直接当作 RepCut32 的命中率；§7.13 的 `66 compute + 30 commit` 是当时所检查生成包的 `part_29` 批次数，不能代替本节冻结输入包的全局批次数。以下诊断和 A/B 均以 `build/default_line_ab_20260924/default_noenv/partitioned.json` 为同一分区输入，N=K=32，node030 CPU96--127，all-spin，Clang23/O3。

在冻结输入包上新增默认关闭的 `compute_batch_activity_profile`，直接统计每个生成 batch 被调用时是否有可执行的 active word。C=100000 时，compute batch 共调用 2,106,849,948 次，其中 1,453,794,074 次为空，空调用占 69.00%；`part_29` 的空调用占 80.54%。这证明入口过滤有明确机会，但只反映调用频次，不能直接推算关键路径时间。原始计数在 `build/repcut_grhsim_20260925/batch_dispatch_diagnostic/runs_v1/`。

据此实现默认关闭的 `compute_batch_dispatch_guard`：对每个普通 compute batch，在调用前检查该 batch 的静态 word/dispatch-mask 关系；没有任何对应 active bit 时跳过调用。batch 内原有检查保留，commit、fullpass 和 posedge 特化路径不变；不按分区、模块或信号名特判。A/B 的 6,994 个生成 scheduler `.cpp` 文件逐一比较，全部逐字节相同；新增守卫只在外层 `eval()` 的 batch 调用处。两边使用同一冻结输入、编译参数和仿真签名。emitter 单测（含纯事件/full-word 边界）通过，C=100、30000、100000 的功能签名均通过。

| C；每组 4 对 AB/BA | 指标 | baseline 中位 | guard 中位 | 配对变化中位 | guard 胜出 |
| --- | --- | ---: | ---: | ---: | ---: |
| 30000 | Host (s) | 5.4960 | 5.4965 | +0.055% | 2/4 |
| 30000 | 全局 eval (us/step) | 60.398 | 60.253 | -0.257% | 3/4 |
| 30000 | 最大分区平均 eval (us/step) | 45.229 | 44.870 | -0.837% | 4/4 |
| 30000 | 分区平均 eval 之和 (us/step) | 550.161 | 541.195 | -1.630% | 4/4 |
| 100000 | Host (s) | 20.3905 | 20.3290 | -0.452% | 3/4 |
| 100000 | 全局 eval (us/step) | 70.541 | 70.526 | -0.399% | 3/4 |
| 100000 | 最大分区平均 eval (us/step) | 45.408 | 44.998 | -1.038% | 4/4 |
| 100000 | 分区平均 eval 之和 (us/step) | 714.375 | 705.198 | -1.431% | 4/4 |

守卫确实稳定减少了分区内部工作，但没有证明 Host walltime 收益。C=100000 的单对 Host 变化横跨 -1.95% 至 +2.38%；AB 次序的变化中位为 -1.20%，BA 为 +0.96%，与约 -0.45% 的总中位变化同量级。`part_29` 后期平均 eval 约 30.5--30.8 us，守卫只减少约 0.2--0.3 us；持续最慢的 `part_3` 仍约 45 us。最大分区平均 eval 与全局 eval 的约 25 us 差距不能全部解释为同步开销：前者是“各分区均值的最大值”，后者逐 step 还受到瓶颈轮换、调度及等待影响，两个统计量不能直接相减归因。

结论：保留入口守卫为默认关闭的实验选项，不把它作为 walltime 优化默认开启。下一步若继续追求端到端收益，应测量活跃 batch 内部的实际耗时和逐 step 的关键路径，再评估更紧凑的 batch trigger 调度；不能仅凭空调用率推断跳过空 batch 会明显缩短全局 eval。A/B 原始结果分别在 `build/repcut_grhsim_20260925/batch_dispatch_guard_ab/c30000_4pairs/` 与 `c100000_4pairs/`。

### 7.15 活跃 batch 关键路径的通用表达式优化复测（2026-09-30）

§7.11 的 batch 级探针显示，`part_29`/`part_15` 的长尾来自连续 active-mask compute batch，而 `part_3`/`part_6`/`part_10` 还包含大量展开的标量拼接和选择表达式。先尝试了一个与分区编号、模块名和信号名无关的后端规则：对满足以下条件的 `kConcat` 生成结果宽度不超过 64 bit、至少 16 个标量逻辑操作数、且不包含 event 的拼接，改为逐项掩码、移位、OR 到唯一的 `uint64_t` accumulator，再复用原有的结果赋值、change detection 和 activation propagation。选项为 `staged_scalar_concat` / `WOLVRIX_GRHSIM_STAGED_SCALAR_CONCAT`，默认关闭。

在冻结输入 `build/default_line_ab_20260924/default_noenv/partitioned.json`、N=K=32、node030 CPU96--127、all-spin、Clang23/O3 上重新生成和编译。规则命中了 `part_3` 248 个、`part_6` 246 个、`part_10` 116 个长标量拼接；`part_15` 和 `part_29` 没有满足条件的拼接，因此没有对它们做分区特判。该候选模型静态库编译 walltime 为 4:24.56，外层 harness 为 6.67 s；同一轮先行生成的 helper-chunk 候选模型编译为 4:35.44，二者只作编译代价参考。生成包和运行结果位于 `build/repcut_grhsim_20260925/staged_concat_final/`。

| C；每组 4 对 AB/BA | Host | 全局 eval | 最大分区 eval | 分区 eval 之和 | 功能签名 |
| --- | ---: | ---: | ---: | ---: | --- |
| 30000 | 中位 -1.05% | -1.25% | -2.73% | -0.57% | 4/4 通过 |
| 100000，首轮 | 中位 -4.88% | -6.92% | -9.33% | -6.72% | 4/4 通过 |
| 100000，独立复测 | -0.08% | +0.43% | +1.87% | +0.30% | 4/4 通过 |

C=30000 的收益在四对中方向一致，但 C=100000 的独立复测回到统计噪声范围，且 `part_3`/`part_10` 的 eval 分别约增加 0.3--2.2%/1.6--4.8%。因此不能把首轮 C=100000 的改善归因于该规则；它更可能叠加了 node030 运行期时序波动。结论是：该表达式改写可以保留为默认关闭的实验选项和后端机制样例，但当前证据不足以作为 walltime 优化或默认策略。它没有改变分区、通信量、Verilator 路径或 GrhSIM 默认行为。

本节的意义是把“活跃 batch 内部关键路径”从静态大函数进一步收敛到可泛化的后端模式：长标量 concat 确实集中出现在 `part_3/6/10`，但把嵌套表达式改成 accumulator 并不会稳定减少运行时成本。下一步应回到 §7.11 的连续 batch 激活簇，增加不改变语义的 batch 内部状态访问/激活计数，再选择能减少无效扫描的通用调度变换。

增量复测：在相同 node030 CPU96--127、C=100000、4 对 AB/BA 条件下再次运行，功能签名仍为 4/4 通过，但 Host 配对中位为 `+0.58%`，全局 eval `+1.13%`，最大分区 eval `+2.00%`，分区 eval 之和 `+0.33%`。这组结果进一步确认该规则不应进入默认路径。

### 7.16 batch trigger bitmap：语义验证与维护成本（2026-09-30）

沿 §7.13--7.15 的方向实现了通用 batch trigger bitmap 原型：根据最终 schedule，把每个 active ID 映射到其所属 batch；输入、状态提交、memory reader 和 compute 中的激活传播在更新原活动位之外，同步置位 batch bitmap；外层仅调用被标记的 compute batch，并在调用前清除该 batch 的标记，使执行期间产生的新标记得以保留。commit 和已有 fullpass 路径仍沿用原调度。不匹配分区编号、模块名或信号名。

选项 `batch_trigger_bitmap` / `WOLVRIX_GRHSIM_BATCH_TRIGGER_BITMAP` 默认关闭。`batch_trigger_bitmap_validate` / `WOLVRIX_GRHSIM_BATCH_TRIGGER_BITMAP_VALIDATE` 是诊断模式：同时检查原有活动位，如果 bitmap 漏标则回退执行并计数；它隐含编译 runtime profile，运行时需 `EMU_RUNTIME_PROFILE=1` 才输出计数。另有默认关闭的 `batch_trigger_profile` 记录标记操作次数；这个计数不是“原本为零的 bitmap 位变成一”的去重次数，不能直接当作有效调用节省数。

功能验证覆盖普通、表驱动及 deferred aggregate 激活入口。XiangShan C=10000 和 C=100000 Difftest 通过；C=100000 的全部 32 个分区均为 `fallback_total=0`。独立回归测试 `emit-grhsim-cpp-batch-trigger-bitmap` 通过，包含变化输入、重复 `init()`、跨多个 activity word 的聚合激活、拆分 word helper、关闭/开启/校验模式；强制开启 bitmap 的完整 `emit-grhsim-cpp` 测试也通过（336.30 s）。专门检查旧入口守卫文本的 fixture 显式关闭 bitmap，避免两种方案的结构断言互相覆盖。默认关闭时不生成 bitmap 成员。

性能使用同一冻结输入 `build/default_line_ab_20260924/default_noenv/partitioned.json`，baseline 为 §7.14 的 `batch_dispatch_guard_ab/baseline`（guard 和 bitmap 均关闭）；node030 CPU96--127、N=K=32、all-spin、Clang23/O3、C=100000、Difftest 开启。所有正式 A/B 均关闭模型内部诊断 profile，仅保留双方一致的 RepCut 阶段计时。每个候选单独完成 4 对 AB/BA，8 次运行的功能签名一致：`pc=0x80000c0c`、instructions=240349、cycles=99996、guest_cycles=100001、steps=200102。

| 实现；每组 4 对 AB/BA | Host 中位，baseline→候选 (s) | Host 配对变化 | 全局 eval 配对变化 | 最大分区平均 eval 配对变化 | 分区平均 eval 之和配对变化 | Host 胜出 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 逐变化条件标记 | 20.0990→31.2220 | +55.185% | +77.996% | +73.853% | +43.863% | 0/4 |
| 新增标记改成无分支掩码 OR | 24.8835→25.8730 | +4.669% | +6.674% | +11.781% | +3.049% | 0/4 |

变化的计算口径为 `median((candidate_i / baseline_i - 1) × 100%)`，不是两列总体中位数直接相除。有分支版本的四对 Host 变化为 +54.90% 至 +56.39%；无分支版本为 +0.36% 至 +6.49%。两轮 baseline 绝对值有明显变化，因此不能用第一轮 31.222 s 与第二轮 25.873 s 直接计算无分支改写的收益。各自配对结果均不支持启用 bitmap；update 配对中位分别约 -0.75%/-0.43%，退化集中在 eval。

CPU 采样单独执行，分析时排除了 all-spin 等待函数，按实际 `GrhSIM_Gpart_i_model::*` 符号累计采样 period。有分支 bitmap 相对 baseline 的模型采样 cycles 在 p3/p6/p10/p15/p29 分别增加约 76.2%/17.7%/64.6%/49.2%/47.7%。这五个候选分区中 compute 占模型采样周期的约 87.7%--97.6%，外层 `eval()` dispatch 仅约 1.6%--3.9%。这说明增加的工作主要在模型内，不能把退化归因为 Host 等待或外层 bitmap 检查。该单次采样用于定位，不能代替交错 walltime 测量，也没有把整个进程的自旋周期计成有效模型工作。

对 p3 中的具体函数进一步比较 Clang23 机器码：

| 函数/实现 | 机器码字节数 | 静态指令数 | 条件跳转数 | 含栈地址的静态指令数 |
| --- | ---: | ---: | ---: | ---: |
| b19 / baseline | 28,698 | 5,977 | 54 | 1,414 |
| b19 / 条件标记 | 38,304 | 7,771 | 402 | 2,204 |
| b19 / 无分支标记 | 36,627 | 7,611 | 54 | 1,638 |
| b20 / baseline | 31,354 | 6,690 | 28 | 1,568 |
| b20 / 条件标记 | 42,823 | 8,898 | 456 | 2,721 |
| b20 / 无分支标记 | 41,045 | 8,708 | 28 | 1,919 |

这些是反汇编的静态计数，不是运行时指令或 cache-miss 计数。条件标记给每个变化检测增加分支，b19 的条件跳转从 54 增到 402；掩码 OR 把它恢复到 54，但仍保留 bitmap 的计算和读改写，静态指令数仍比 baseline 多 27.3%。b20 同样多约 30.2%。可执行文件 text 段分别为 106,960,672 / 119,924,086 / 116,973,566 B；无分支版仍比 baseline 大约 9.36%。作为对照，p3/b46 三版均为 132,613 B、22,566 条静态指令、23 个条件跳转；影响并非均匀施加到所有 batch。

机制结论：高空调用率不等于高可回收 walltime。当前细粒度调度已经逐值维护 supernode 活动位，再逐值维护一套 batch bitmap，会把“将来少做的空调用检查”换成“当前活跃逻辑上的额外标记计算、访存和代码”。无分支改写减少了新增控制流，却没有消除第二套活动元数据的维护成本。当前两种实现均不应进入默认路径；现有默认值及 Verilator 路径不变。若继续研究 bitmap，下一候选应在 supernode/batch 边界合并目标标记、减少每次信号变化的重复维护，并同时验证活动位覆盖和端到端 walltime，而非继续逐点添加更细的守卫。

可复查产物：`build/repcut_grhsim_20260925/batch_trigger_bitmap_validate_v5/run_c100000/` 是覆盖诊断；`batch_trigger_bitmap_v6/c100000_4pairs/` 和 `batch_trigger_bitmap_branchless/c100000_4pairs/` 是正式对照；`batch_trigger_bitmap_v6/perf_summary.json`、`codegen_summary.json` 保存采样和机器码归因。生成/编译 walltime：条件标记版本生成 554.804 s、模型编译 232.53 s、harness 4.53 s；无分支版生成 632.878 s、模型编译 265.25 s、harness 4.48 s。模型均使用 `make -j32`，harness 使用 `make -j24`；这些编译在不同时间执行，仅记录成本，不据此宣称编译速度差异。

补充直接消融：为隔离前两轮 baseline 绝对时间变化的影响，又将条件标记 bitmap 作为 A、无分支 bitmap 作为 B，按相同配置完成 C=100000 的 4 对 AB/BA。8 次功能签名全部通过；Host 中位为 `38.5350→25.9235 s`，配对变化中位 `-32.675%`，范围 `-32.994%` 至 `-32.616%`，4/4 胜出。进程 elapsed 配对中位 `-32.625%`，全局 eval `-40.063%`，最大分区平均 eval `-39.423%`，分区平均 eval 之和 `-27.925%`，update 为 `+0.507%`。结果位于 `batch_trigger_bitmap_branchless/conditional_vs_branchless_c100000_4pairs/`。这直接支持新增条件控制流及其编译后形态是大幅退化的重要来源，但不把收益全部归因于 branch misprediction：寄存器分配、代码规模和访存形态也随之改变。该消融只证明无分支实现优于条件标记实现；相对原始无 bitmap baseline，它仍未取得 walltime 收益。

### 7.17 在 supernode 边界合并 batch 标记（2026-10-01）

继续 §7.16 的结论，先实现默认关闭的 `batch_trigger_supernode_union` / `WOLVRIX_GRHSIM_BATCH_TRIGGER_SUPERNODE_UNION`。这个选项隐含开启 bitmap：emitter 收集普通 compute supernode 内所有可能传播的 batch 目标，在该 supernode 末尾按 bitmap word 合并 OR；原来的逐值 supernode activity 更新不变。也就是说，batch 标记允许保守地多标，但实际 supernode 执行仍由精确活动位决定。不按分区编号或信号名筛选；输入、commit、fullpass 和动态 memory reader helper 保持原来的标记方式。

这种改写降低了标记密度：冻结的 32 分区包中，compute 的静态 bitmap 成员更新由 387,203 处降到 57,426 处（-85.17%）；p3/p6/p10/p15/p29 分别减少 77.7%/70.1%/90.5%/91.4%/92.7%。6,859 个 compute batch 和 135 个 commit batch 的划分不变；外层 eval 和 commit scheduler 源文件与 §7.16 无分支 bitmap 版逐字节相同。可执行文件 text 从 116,973,566 降到 111,997,582 B，仍比原始无 bitmap baseline 的 106,960,672 B 大 4.71%。

机器码中，p3/b19 从无分支 bitmap 的 7,609 条静态指令降到 6,041，原始 baseline 为 5,975；条件跳转三者均为 54，栈引用从 1,638 恢复为 1,414（baseline 也是 1,414）。p10/b146 的静态指令由 11,738 降到 8,825，baseline 为 8,804。本节数的是 `.o` 反汇编；与 §7.16 的完整可执行文件统计有少量对齐指令差异，不能把二者的差额当作优化收益。

新增边界合并回归覆盖普通、deferred aggregate、拆分 word helper、输入变化及重复初始化；关闭/精确 bitmap/保守合并/validate 模式均通过，强制开启保守合并的完整 emitter 回归也通过（340.18 s）。香山另建临时诊断程序，仅替换 `eval.cpp`，复用生产模型其余编译对象：每次准备跳过 compute batch 时检查原始活动位，若发现漏标则立即报错退出；同时记录 skipped/useful/empty。这个诊断不启用改变 commit 策略的 runtime profile，也不作为性能样本。

| C=100000，32 个分区合计 | 精确 bitmap | 保守边界合并 |
| --- | ---: | ---: |
| 总 batch 调度机会 | 2,106,849,948 | 2,106,849,948 |
| 跳过的调用 | 1,452,735,224 | 967,781,823 |
| 实际进入的非空调用 | 653,055,874 | 653,055,874 |
| 实际进入的空调用 | 1,058,850 | 486,012,251 |
| 跳过率 | 68.953% | 45.935% |
| 漏标记 | 0 | 0 |

两组诊断的 Difftest 和完整执行签名均通过，逐个分区的非空调用次数与总调度机会完全相同。保守合并使总进入次数增加 74.14%，其中 42.67% 是空调用；p3 单独增加 32,742,830 次空调用。该结果同时说明语义覆盖没有丢失，以及无条件 union 的代价主要是丢掉了大量原本能跳过的空 batch。

无诊断生产程序在 node030 CPU96--127、N=K=32、all-spin、Clang23/O3、C=100000 上完成两轮各 4 对 AB/BA，baseline 仍为 `batch_dispatch_guard_ab/baseline`。所有样本均通过 Difftest；保留每个通过功能检查的样本，没有核空闲门槛或按性能筛样。

| 保守边界合并相对原 baseline | 第一轮 | 独立复测 |
| --- | ---: | ---: |
| Host 中位 baseline→候选 (s) | 23.7600→24.0105 | 25.5930→25.7425 |
| Host 配对变化中位 | +1.052% | +0.615% |
| 进程 elapsed 配对变化中位 | +1.069% | +0.604% |
| 全局 eval 配对变化中位 | +2.240% | +1.164% |
| 分区平均 eval 之和配对变化中位 | -0.794% | +0.423% |
| Host 胜出 | 1/4 | 1/4 |

结论：保守边界合并消除了大部分标记指令膨胀，但当前尚未带来 walltime 收益，不能默认开启。进一步检查静态形态发现，6,859 个 compute batch 中有 6,854 个（99.927%）只含一个 activity word，剩余 5 个只有两个。p3/p6/p10/p15/p29 的 compute batch 全部只含一个 word，原入口空检查实际上是一次活动字节检查。因而本工作负载中 batch bitmap 与已有 active-word 信息高度重合；“空调用占多数”并不能证明值得额外维护一套 batch 元数据。

本轮产物集中于 `build/repcut_grhsim_20260925/batch_trigger_supernode_union/`：`codegen_counts.json`、`object_counts.json`、`batch_shapes.json` 为静态证据；`precise_check/c100000/` 和 `union_check/c100000/` 为覆盖/调用计数；`c100000_4pairs/` 与 `c100000_repeat_4pairs/` 为无诊断正式计时。生成 626.515 s，Clang23/O3 `make -j32` 模型编译 253.18 s，`make -j24` harness 编译 3.64 s；仅记录本次成本。

下一次机制对照使用精确局部累积：在 supernode 内将真实变化累积到局部 bitmap，末尾再写回成员 bitmap，保留逐值条件但避免每处都读改写成员。该选项是默认关闭的 `batch_trigger_supernode_accumulate` / `WOLVRIX_GRHSIM_BATCH_TRIGGER_SUPERNODE_ACCUMULATE`；若两个边界选项同时开启，以精确局部累积为准。小模型回归已通过，仍需香山无诊断交错计时来判断收益。

增量结果（2026-10-01）：精确局部累积已完成完整验证。普通、validate、拆分 word helper 等共 10 种模式的独立回归通过（68.86 s）；强制开启精确累积的完整 emitter 回归通过（336.36 s）。香山 C=100000 另建无 runtime profile 的覆盖诊断程序，32 个分区逐一核对 skipped/useful/empty，三项计数全部与 §7.16 的无分支精确 bitmap 一致：合计分别为 1,452,735,224 / 653,055,874 / 1,058,850，漏标记为零，Difftest 和完整功能签名通过。因此这次确实保留了精确 bitmap 的调用选择，没有靠多进入空 batch 来减少成员更新。

无诊断性能程序继续使用本节同一 baseline、冻结分区输入和 node030 CPU96--127，在 C=100000 下完成 4 对 AB/BA。8 个正式样本全部通过功能检查，所有样本均纳入统计：

| 精确局部累积相对原 baseline | baseline 中位 | 候选中位 | 配对变化中位 |
| --- | ---: | ---: | ---: |
| Host (s) | 25.3695 | 26.4425 | +4.352% |
| 进程 elapsed (s) | 25.4100 | 26.4900 | +4.352% |
| 全局 eval (us/step) | 90.4785 | 96.0075 | +6.282% |
| 全局 update (us/step) | 29.8620 | 29.5175 | -1.141% |
| 最大分区平均 eval，即 p3 (us/step) | 57.5880 | 65.6520 | +14.582% |
| 分区平均 eval 之和 (us/step) | 933.5045 | 968.2780 | +3.962% |

这里配对变化仍为 `median((candidate_i / baseline_i - 1) × 100%)`；Host 四对全部退化，范围 +1.155% 至 +4.925%，没有端到端收益。p6/p10/p15/p29 的平均 eval 配对变化分别为 +1.08%/+3.32%/+1.36%/+0.21%。该组相对原始无 bitmap baseline 测量，不能把其绝对时间与前一轮保守 union 或 §7.16 的绝对时间直接相除。

精确累积也把 compute 中的成员 bitmap 更新从 387,203 处减至 57,426 处，但保留了逐值掩码计算并增加局部累积。外层 eval 和 commit scheduler 源文件仍与无分支精确 bitmap 逐字节相同。可执行文件 text 为 117,010,974 B，相比精确 bitmap 的 116,973,566 B 几乎没有减少，仍比原始 baseline 大 9.40%。代表性 `.o` 的机器码说明“成员写回减少”不等于“总工作减少”：

| 函数 | 逐值精确 bitmap：静态指令 / 栈引用 | 精确局部累积：静态指令 / 栈引用 |
| --- | ---: | ---: |
| p3/b19 | 7,609 / 1,638 | 7,629 / 1,984 |
| p3/b20 | 8,706 / 1,919 | 8,538 / 2,161 |
| p10/b146 | 11,738 / 512 | 12,247 / 1,645 |

这里“栈引用”是含栈地址的静态指令计数，不能解释为动态 spill 次数。计数和较大的栈访问形态支持局部累积增加寄存器压力这一机制解释；当前没有隔离实验把全部 Host 退化归因于 spill。可以确定的是，调用选择保持精确，额外激活元数据的计算成本依然存在，且该实现没有消除热点机器码膨胀。

还检查了原 baseline 的空入口机器码：p3/b19 和 p29/b137 都先执行活动字节 load/test，空时直接 `ret`，之后才保存寄存器和建立栈帧；p10/b146 则先建立栈帧再检查。前两例说明不少空调用本来就很便宜，后一例说明不能把这一形态泛化到全部 batch。结合 §7.14 原活动位入口 guard 也没有稳定 walltime 收益的结果，后续不应再仅凭 69% 的空调用率继续叠加 batch 元数据。

本轮结论：保守边界合并降低了标记代码密度，但引入大量空调用；精确局部累积保住了跳过率，但仍需逐值维护另一套状态，并加重部分热点的栈访问。两种边界方案均没有证明 walltime 收益，继续保持默认关闭，现有 GrhSIM 默认调度及 Verilator 路径不变。本轮到此收敛；后续优化优先回到实际活跃 payload 内的状态访问与激活传播，目标应是减少现有工作本身。若继续研究更粗粒度的 region 调度，需要先证明一次 region 判断可覆盖多个 batch，且不必为每次变化重复维护第二套元数据，不能直接套用本节已经证伪的细粒度实现。

精确累积产物位于 `build/repcut_grhsim_20260925/batch_trigger_supernode_accumulate/`：`c100000_4pairs/` 是无诊断计时，`union_check/c100000/` 是精确累积的覆盖诊断（目录名沿用通用 checker），`codegen_counts.json`、`object_counts.json` 是静态证据。生成 walltime 631.005 s，Clang23/O3 `make -j32` 模型编译 260.53 s，`make -j24` harness 4.15 s；不据此推断不同轮次的编译速度优劣。

### 7.18 活跃 payload 的索引存活期优化（2026-10-01）

沿 §7.17 的结论回到活跃逻辑，复查冻结 baseline 的生成代码与 `active_batch_perf/profile23.instructions.json`。p6/b184 的采样指令中约一半包含栈地址，但它没有 packed-array 索引快照，不能把它的栈压力归因于下面的模式。p29/b137 则发现了一个明确的 emitter 行为：先生成 521 个 `const std::size_t packed_array_idx_*`，其中最多 520 个尚未首次使用；后面的单用户局部 slice 被内联到消费表达式，使索引快照与使用点相距很远。Clang23 的该函数入口紧接着出现大量索引 load/store 到栈的指令。这里 520 是源码“已定义但尚未首次使用”的数量，不是机器寄存器活跃数。

实现默认关闭的 `packed_array_late_index` / `WOLVRIX_GRHSIM_PACKED_ARRAY_LATE_INDEX`：对纯组合 compute supernode 内的 packed-array 标量索引，如果索引来自输入或已保存的标量值，且整个 supernode 不写它的存储（包含规范化别名），则不再提前生成索引临时变量，在实际数组选择表达式中读取。保留原边界检查和越界返回零的语义；有副作用、当前 supernode 定义/改写的索引、直接状态读取、event 和宽索引均保留原路径。没有按 part、模块或变量名选取目标，也没有新增调度元数据或改变活动位传播。

简化示例：原来先执行 `i0 = saved_index0; i1 = saved_index1; ...`，再在若干计算后用 `lanes[i0]`、`lanes[i1]`。规则只在证明这些 `saved_index` 在当前块中不变时，将读取放回各自的实际使用点。目标是缩短临时值存活期，是否减少机器码和 walltime 仍需编译及测量验证。

独立回归已经通过（26.61 s），覆盖默认与显式关闭生成一致、输入/跨 supernode 保存索引、当前块定义索引与副作用排除、0..31 索引访问 10 项数组的越界行为、跨 supernode 激活、变化输入、两次初始化和拆分 helper。强制开启候选的完整 emitter 回归通过（348.53 s）。本轮产物统一位于 `build/repcut_grhsim_20260925/packed_array_late_index/`，`baseline_evidence.json` 保存静态模式及已有采样分类；完整香山生成、静态不变性检查和 C=100000 对比继续执行。

增量结果（2026-10-01）：完整生成和复测已完成。baseline 继续冻结为 `batch_dispatch_guard_ab/baseline`，输入仍是 `build/default_line_ab_20260924/default_noenv/partitioned.json`；候选只打开本节索引规则，§7.14--7.17 的入口 guard、concat 和 bitmap 实验均未叠加。7519 个生成源码/头文件中 7190 个逐字节相同，只有 329 个 compute 文件变化，合计移除 4495 个提前索引快照，自然覆盖 27 个分区；p15/p28/p29 分别移除 1040/1022/1048 个。所有头文件、外层运行时、eval、状态、commit 文件以及未命中 compute 文件均保持相同。

Clang23/O3 的代表性机器码如下。静态栈引用为含 `(%rsp` 操作数的指令数；栈帧一列是函数入口 `sub ..., %rsp` 分配的字节数，未包含保存通用寄存器的 push，不能解释成动态 spill 次数。

| 函数 | 代码字节 baseline→候选 | 静态指令 baseline→候选 | 静态栈引用 baseline→候选 | 栈帧分配 baseline→候选 (B) |
| --- | ---: | ---: | ---: | ---: |
| p15/b129 | 147373→133638 | 25032→24033 | 6757→5261 | 5224→2168 |
| p29/b137 | 215149→199229 | 36823→35800 | 8320→6780 | 5192→2008 |
| p3/b46 | 132613→132613 | 22565→22565 | 2710→2710 | 9848→9848 |
| p6/b184 | 296406→296406 | 52907→52907 | 20444→20444 | 17336→17336 |

p15/b129 和 p29/b137 的条件跳转数保持 1139/1391，不是靠去掉边界判断得到的变化。p29/b137 入口原先集中 load 索引并写栈，候选改为读取索引后就近选择、比较和写回；其代码字节减少 7.40%，静态栈引用减少 18.51%，栈帧分配减少 61.33%。p15/b130、p29/b138、p3/b19、p10/b146 的机器码计数也完全相同。整个 ELF 的 text 从 106960672 降到 106914808 B，仅减少约 0.043%；局部函数的收益不能按比例外推到全模型。

正式性能在 node030 CPU96--127、N=K=32、NUMA1、all-spin、Clang23/O3、C=100000、Difftest 开启、ASLR 关闭下进行两轮独立的四对 AB/BA。两边只有相同的阶段计时，没有模型内部诊断插桩；所有功能通过样本全部纳入，未做空闲门槛或按速度筛选。两轮共 16 个正式样本及 C100 smoke 均通过，功能签名仍为 `pc=0x80000c0c`、instructions=240349、cycles=99996、guest_cycles=100001、steps=200102，ELF/镜像/NEMU 的前后哈希一致。

| 指标 | 首轮配对中位变化 | 独立复测配对中位变化 | 合并 8 对配对中位变化 | 合并候选胜出 |
| --- | ---: | ---: | ---: | ---: |
| Host | -1.206% | -0.578% | -1.078% | 6/8 |
| 进程 elapsed | -1.196% | -0.559% | -1.069% | 5/8，另 1 对相同 |
| 全局 eval | -1.112% | -0.526% | -1.089% | 5/8 |
| 全局 update | -0.874% | -0.891% | -0.891% | 7/8 |
| 最大分区平均 eval，即 p3 | -0.659% | +3.065% | +0.787% | 4/8 |
| 分区平均 eval 之和 | -0.726% | -0.300% | -0.589% | 7/8 |
| p15 eval | -2.326% | -2.009% | -2.221% | 8/8 |
| p28 eval | -2.244% | -2.300% | -2.244% | 8/8 |
| p29 eval | -1.683% | -1.847% | -1.701% | 8/8 |

变化口径始终是 `median((candidate_i / baseline_i - 1) × 100%)`。首轮 Host 的独立中位为 25.4580→25.1535 s，复测为 25.5725→25.2810 s；不能直接用这些总体中位的比值代替配对变化。8 对 Host 变化范围为 -5.529% 至 +1.070%，p3 和未修改的 update 仍有明显运行期波动，因此只能报告“测得约 1% 的小幅总时间改善”，不能把这个幅度全部确定归因为索引规则。p15/p28/p29 在两轮每一对中均变快、且收益集中于大量命中索引规则的分区，是比总 Host 更稳定的局部证据。

另做 baseline/candidate/candidate/baseline 四次 `cycles:u`、499 Hz 的 perf 采样，每次同样 C=100000 并通过 Difftest；这些运行不混入上表。只累计 `GrhSIM_Gpart_*_model::*` 的采样 period，排除 all-spin 等待。命中规则的 compute 函数组 baseline 约占模型采样 cycles 的 7.80%，候选该组采样 cycles 减少 2.45%；未变化的 compute 组也减少 1.45%，说明采样和执行环境仍有共同波动。p15/b129 和 p29/b137 分别从 551→494、658→595 个样本，period 变化约 -10.27%/-9.61%；但未改动的 p29/b138 也约 -7.87%，p15/b130 则 +9.66%。这些单函数采样不能证明精确的 10% 加速率。

按采样 IP 对照机器码，p15/b129 的含栈地址样本为 118→82，p29/b137 为 82→68；这是与减少长寿命索引临时值一致的旁证，不是精确停顿计数，也不把 cycles 全部归为 cache miss 或 spill。采样分析使用 `perf script -F period,ip,sym`：本机 perf 省略 `ip` 时符号列为空，因此修正解析后直接重读四份原始数据，未重跑或替换正式时间样本。

本轮结论：索引延迟读取消除了一个有明确数据依赖依据的后端冗余，局部栈帧、代码体积和 p15/p28/p29 的 eval 均改善；对最终 walltime 的收益较小，最大的 p3 仍未改善。本选项继续默认关闭，作为通过功能验证的候选保留，暂不升级默认。下一步应优先分析 p3 中尚未变化的热点、以及 p6/b184 的长寿命中间值和激活累积；后者在新采样中仍是单个 compute 函数的最大采样热点，且本次没有索引快照可消除。不能用 p6 的总 cycles 排名替代逐 step 的关键路径判断，也不应把优化限定为这些分区名。

产物与复现：`c100000_4pairs/`、`c100000_repeat_4pairs/` 保存完整正式样本，`profile/` 保存四次诊断采样与 IP 分类；`static_summary.json`、`results.json` 为静态和运行汇总。`run_build.py`、`static_report.py`、`report.py`、`profile.py`、`profile_instructions.py` 保存生成、检查和汇总过程。本轮生成 walltime 691.221 s、模型 `make -j32` 编译 256.426 s、harness 编译 4.537 s，仅记录成本，不与跨轮 baseline 的编译耗时作加速比较。

残余热点检查补充：复用本轮两次 candidate 采样，p3 的最大单个 compute 函数 b46 只占该分区 compute 采样 cycles 的 3.94%，热点较分散；p6/b184 则占其分区的 22.65%，更加集中。对生成代码逐项区分引用别名与值复制后，p3/b46 的 4381 个 `auto &` 本身不复制状态，但其中另有 336 个 `const auto grhsim_v... = grhsim_state_words_...` 确实按值复制宽寄存器数组；335 个复制值的首次源码使用相距超过 50 行，最大距离 8282 行，主要用于后面的 RepCut 输出 bundle 拼接。这个 batch 没有逐值 changed predicate，不能把它的栈压力归因于 activation 累积。整个生成包有此类宽状态复制 13748 处、覆盖 23 个分区的 351 个 compute 文件；按声明大小累加约 2.31 MB，这是静态快照大小之和，不是动态流量或同时存活的栈空间。

p6/b184 的 2302 个局部值则由 119 个输入位快照、1 个宽状态复制和 2182 个其他中间值组成；2109 个首次使用相距超过 50 行，最大距离 2952 行。因此下一项可以优先验证“纯 compute 区间内不可变宽状态读取使用引用而非数组快照”的通用规则，再针对 p6 的依赖链评估表达式按使用顺序调度。前者必须证明从定义到所有使用期间对应状态不变，排除 latch 写入、DPI 和其他副作用，不能直接把所有 `const auto` 文本替换成引用；后者不能简单扩大内联导致重复计算。这里只完成模式和覆盖审计，尚未实现这两项，也没有声称它们会提升 walltime。可复现审计脚本及数据为 `residual_audit.py`、`residual_audit.json`。

### 7.19 纯 compute 块中的宽状态引用（2026-10-01）

沿 §7.18 的残余热点证据实现默认关闭的 `wide_state_read_refs` / `WOLVRIX_GRHSIM_WIDE_STATE_READ_REFS`。只在纯 compute supernode 内，对局部、非持久化、结果宽度等于状态宽度的宽寄存器/锁存器读取，将 `const auto value = state_array;` 改成 `const auto &value = state_array;`。引用限定在本次 supernode 调用内；消费者仍沿原顺序计算，不改变调度、状态布局或激活传播。模型中 compute 与 commit 不在块内交错，纯计算只写 value storage，故被引用状态在所有使用期间不变。含 DPI/系统任务/未知操作/显式副作用或 latch 写入的块保持快照；输出、跨 supernode、跨阶段等需要持久保存的值保持原路径。不按分区、模块或信号名选择目标。

小模型独立回归通过（33.60 s），覆盖默认与显式关闭的生成一致、128/130 bit 状态、多消费者、跨 supernode 和输出持久化排除、显式副作用与真实 DPI 调用排除、256 次变化/写使能循环、重复 eval、两次初始化和拆分 helper。强制同时开启本规则及 §7.18 索引规则的完整 emitter 回归通过（320.40 s）。先行编译 p3/b46 显示，336 个宽数组快照全部变成引用，该文件其他字节相同；Clang23/O3 静态指令从 22566 降至 21885、含栈地址的静态指令从 2710 降至 30，入口栈帧分配从 9848 降至 208 B。静态计数不等于动态 spill 或性能收益。

本次正式 A/B 的 baseline 是 §7.18 的 `packed_array_late_index`，候选为“索引规则 + 宽状态引用”，用于隔离新增规则的增量收益；不是 §7.18 所用的原始无索引 baseline。冻结输入仍为 `build/default_line_ab_20260924/default_noenv/partitioned.json`，实验产物在 `build/repcut_grhsim_20260925/wide_state_read_refs/`。

完整包检查已完成：7519 个源码/头文件中 7198 个逐字节相同，321 个 compute 文件仅将上述宽状态值声明改为引用，共替换 13295 个快照，覆盖 23 个分区；外层调度、commit、通信及所有头文件保持相同。321 个函数中 46 个反汇编相同。按 compute 函数自身的符号边界累计，静态指令总数 1237452→1233322（-0.334%），含栈地址指令 124655→116441（-6.589%），代码字节 6091782→6050148（-0.683%）。全 ELF text 为 106914808→106873216 B，仅减少 0.039%。源码快照数量不能直接当作编译后消除的数组拷贝数量。

| 函数 | 代码字节 baseline→候选 | 静态指令 baseline→候选 | 静态栈引用 baseline→候选 | 栈帧分配 baseline→候选 (B) |
| --- | ---: | ---: | ---: | ---: |
| p3/b46 | 132613→127389 | 22566→21885 | 2710→30 | 9848→208 |
| p6/b184 | 296406→296409 | 52842→52842 | 20444→20444 | 17336→17336 |

本节最终静态统计限定到目标 compute 函数的 `.text` 和符号地址范围，包含无操作数指令；不把同一 `.o` 中单独的 helper 算入函数。§7.18 的旧脚本按整个 object 计数，且正则对无操作数指令存在跨行匹配，因此部分绝对指令数与本节略有不同；这不改变两臂相对变化、栈帧或运行时间。已在本轮汇总脚本中修正口径。p6/b184 的 20444 处栈引用没有减少，说明仅消除宽状态快照没有解决它的大量普通中间值存活问题。

正式测量在 node030 CPU96--127、N=K=32、NUMA1、all-spin、Clang23/O3、C=100000、Difftest 开启、ASLR 关闭下完成两轮各四对 AB/BA。所有 16 个正式样本及 C100 smoke 均通过，功能签名一致：`pc=0x80000c0c`、instructions=240349、cycles=99996、guest_cycles=100001、steps=200102；二进制、镜像和 NEMU 身份前后不变。双方只有相同的阶段计时，未开启模型诊断 profile；未采用空闲门槛或按速度筛选。

| 指标 | 首轮配对中位变化 | 独立复测配对中位变化 | 合并 8 对配对中位变化 | 合并候选胜出 |
| --- | ---: | ---: | ---: | ---: |
| Host | +0.684% | +0.125% | +0.439% | 2/8 |
| 进程 elapsed | +0.695% | +0.124% | +0.420% | 2/8 |
| 全局 eval | +0.366% | -0.040% | +0.286% | 3/8 |
| 全局 update | +0.555% | +0.560% | +0.560% | 1/8 |
| 最大分区平均 eval，即 p3 | +1.834% | -0.313% | +0.578% | 3/8 |
| 分区平均 eval 之和 | +0.138% | -0.084% | +0.042% | 4/8 |
| p6 eval | +0.296% | +0.008% | +0.274% | 3/8 |

变化口径仍为 `median((candidate_i / baseline_i - 1) × 100%)`。首轮 Host 独立中位为 20.1180→20.2140 s，第二轮为 20.1975→20.1740 s，合并为 20.1745→20.2065 s；这些总体中位的比值不能替代配对变化。8 对 Host 变化范围 -0.341% 至 +0.864%。未修改的 update 也有约 +0.56% 的共同波动，因此不能把全部 +0.44% 都确定归因于引用改写；能够得出的结论是没有测到端到端收益，不适合默认开启。不要用本轮约 20 s 与 §7.18 另一时间窗口约 25 s 直接计算收益。

另完成 baseline/candidate/candidate/baseline 四次 `cycles:u`、499 Hz 的诊断采样，均为 C=100000 并通过 Difftest，不混入正式 walltime 样本。只累计模型符号的采样 period，排除 all-spin 等待：命中规则的 compute 组约占 baseline 全模型采样 cycles 的 7.87%，该组减少 0.77%；未变化 compute 组增加 0.72%，全模型增加 0.38%。p3 命中组减少 2.29%，但未命中组增加 3.21%，p3 模型合计增加 1.97%。这说明局部消除快照不足以抵消其他热点及执行波动。

| 代表函数 | 样本数 baseline→候选，两次运行合计 | 采样 period 变化 | 含栈地址样本 baseline→候选 |
| --- | ---: | ---: | ---: |
| p3/b46 | 285→245 | -14.07% | 42→0 |
| p6/b47 | 407→483 | +18.65% | 4→0 |
| p6/b184 | 1506→1491 | -1.02% | 757→768 |

p3/b46 的两次配对采样方向均改善，且含栈地址样本减少，与机器码证据一致。但它只占 baseline p3 compute 采样周期的 3.63%；即便把本次约 14% 局部变化完全视作收益，对 p3 compute 的贡献也仅约 0.51 个百分点，不能解释成全局 eval 或 Host 会下降 14%。p6/b184 占 p6 compute 的 23.18%，约一半样本仍落在含栈地址指令上，当前规则基本没有覆盖其主要成本。

p6/b47 提供了反方向的机制线索：40 个宽状态快照改为引用后，静态栈引用 180→24、指令数 33133→33068，但代码字节 164401→170298（+3.59%）。大量 `movzbl` 字节读取的地址基寄存器从 `%rdi` 转为 `%r14`，需要额外的 REX 编码字节；该类指令的编码体积 59752→66370 B，贡献 +6618 B，超过整个函数净增长的 +5897 B。这是寄存器分配改变导致代码变大的直接证据；两次配对采样也均变慢，但还不能证明全部约 18.65% 的采样变化都来自取指或代码 cache。未修改的 p3/b19、p15/b129 采样 period 也分别约 -13.06%/+17.59%，因此不把单函数采样当作精确加速率或 stall 分类。

本轮结论：宽状态引用的语义验证通过，确实消除了部分长寿命数组快照，p3/b46 有局部改善证据；但收益覆盖较小、不同函数的编译结果有得有失，C=100000 的最终 walltime 没有收益。保留为默认关闭的通用实验选项，不按分区或信号名挑选启用，也不叠加到下一轮性能 baseline。下一方向回到 §7.18 的索引版本，优先研究纯 compute 内按消费顺序安排普通中间值计算：遵守依赖和副作用边界，不重复计算多消费者表达式，先验证高栈压力的 p6/b184 及同类结构是否实际减少机器码访存，再做全图 A/B；不能继续用栈帧大小代替关键路径和 walltime。

复现产物：`c100000_4pairs/`、`c100000_repeat_4pairs/` 保存全部正式结果，`results.json` 为两轮和合并统计；`profile/summary.json`、`profile/results.json` 保存四次采样及指令操作数分类；`static_summary.json`、`changed_objects.json`、`encoding_audit.json` 保存生成不变性、321 个函数及编码变化。对应脚本为 `run_build.py`、`static_report.py`、`report.py`、`profile.py`、`profile_report.py`、`changed_objects.py`、`encoding_audit.py`。生成 walltime 557.547 s、模型 `make -j32` 编译 226.144 s、harness 驱动 4.304 s；仅记录成本，不据跨窗口耗时宣称编译加速。

### 7.20 局部 compute 按消费者顺序生成（2026-10-01）

沿 §7.19 的结论回到 §7.18 `packed_array_late_index` baseline，不叠加宽状态引用。p6/b184 源码中存在成批生成的宽移位中间数组，随后才逐项消费；本轮先验证通用的 `local_compute_use_order` / `WOLVRIX_GRHSIM_LOCAL_COMPUTE_USE_ORDER`，默认关闭。只重排纯 compute supernode 内的局部操作：持久化结果写回及其 change detection 保持原次序，在每个消费者之前按依赖顺序生成尚未计算的局部前驱，每个操作只生成一次；多消费者共用结果，未使用操作也保留。只调整 C++ 生成顺序，不改变 GRH、分区、supernode 调度或状态布局。

规则拒绝含 DPI、状态写入、未知操作、显式副作用、event、非 Logic 值、reg-to-mem 专用绕过操作的整个 supernode。依赖检查使用规范化存储别名；如果同一存储有多个定义，或存在先读旧值后覆盖的顺序，就保留原路径。局部值在持久化消费前尽量晚算；持久化前驱仍按原顺序先写回，不能越过它们读取尚未更新的值。没有按分区、模块、信号名或 profile 排名决定启用范围。

独立 focused 回归通过（24.55 s）：默认与显式关闭生成一致，128 bit 依赖链、每个局部值多个消费者、每个计算仅生成一次、输出写回次序、副作用块排除、512 次变化输入与越界移位、重复 eval、两次初始化、拆分 helper 全部通过。完整 emitter 回归和香山生成编译正在执行，当前尚无性能结论。候选产物统一位于 `build/repcut_grhsim_20260925/local_compute_use_order/`；正式计划仍为 node030 CPU96--127、N=K=32、all-spin、Clang23/O3、C=100000 的两轮四对 AB/BA。

增量验证：强制同时开启本规则与索引规则的完整 `emit-grhsim-cpp` 回归通过（321.58 s）。生成中的 p6/b184 已完成逐行多重集合相等检查：两版都是 1548148 字节、2302 个局部声明，只改变行序；首次使用超过 50 行的局部值从 2109 降到 510。完整 Clang23/O3 编译后，目标函数代码 296406→255170 B，静态指令 52842→50810，静态栈引用 20444→13444，入口栈帧 17336→2776 B；整个 ELF 的 `size` 工具 text 统计为 106914808→105956112 B（-0.897%，包含只读数据等，并非仅 `.text` section）。该结果证明热点代码形态确实改变，但静态代码缩小不等于全局 walltime 下降。全包源码检查覆盖 7519 个文件：5825 个 compute 文件只发生行序变化，其余 1694 个源码和头文件逐字节相同，规则自然覆盖全部 32 个分区。

正式 A/B 在 node030 CPU96--127、NUMA1、N=K=32、all-spin、Clang23/O3、C=100000、Difftest 开启、ASLR 关闭下完成两轮各四对 AB/BA。baseline 为 §7.18 `packed_array_late_index`，候选只打开本节规则；所有 16 个正式样本和两组 C100 smoke 功能签名通过，仍为 `pc=0x80000c0c`、instructions=240349、cycles=99996、guest_cycles=100001、steps=200102。所有通过功能检查的计时样本均纳入，没有按速度或核空闲筛选。

| 指标 | 首轮 4 对 | 独立复测 4 对 | 合并 8 对 |
| --- | ---: | ---: | ---: |
| Host 配对变化 | +1.164%（0/4 胜） | +0.838%（0/4 胜） | **+1.084%（0/8 胜）** |
| 进程 elapsed | +1.145% | +0.821% | +1.069% |
| 全局 eval | +1.091% | +1.107% | +1.091% |
| 全局 update | +0.961% | +0.348% | +0.767% |
| 最大分区平均 eval | -1.681% | -0.307% | -1.258% |
| 分区平均 eval 之和 | -1.618% | -1.465% | -1.511% |
| p6 eval | -8.228% | -8.410% | **-8.306%（8/8 胜）** |
| p15 eval | +1.423% | +1.159% | +1.200% |
| p28 eval | -2.250% | -1.704% | -1.704%（8/8 胜） |
| p29 eval | +3.644% | +3.788% | **+3.754%（0/8 胜）** |

变化口径为每一对 `100 × (candidate / baseline - 1)` 后取中位数。首轮 Host 独立中位为 20.0540→20.2410 s，复测为 20.0500→20.2305 s，合并为 20.0500→20.2370 s；总体中位的比值不能替代配对变化。8 对 Host 变化范围 +0.447% 至 +1.746%。候选虽然让分区 eval 总和下降 1.51%，但全局 eval 反而增加 1.09%，说明减少总模型工作并没有减少端到端关键路径。p29 的变慢是需要继续定位的线索；其主要代表函数 b137/b138/b140 的源文件和反汇编均未改变，不能把退化简单归因于这些函数的表达式重排。可执行文件尺寸和链接地址变化后，可能影响原本未修改代码的运行代价，但也可能涉及其他函数或同步时序；尚未通过逐 step 诊断区分这些解释，不能仅凭 walltime 证明 instruction-cache miss 或把全局退化全部归因于 p29。

为检查“全局布局”而不是规则语义本身，另把两边已编译静态库的每个 `.text` section 统一改为 64 B 对齐后重新链接。7454 个 archive member 的所有非对齐 section 元数据和 payload 完全相同，6859 个 compute 函数入口全部 64 B 对齐，功能检查通过；但四对 C=100000 的 Host 仍为 `+1.461%`（0/4 胜），全局 eval `+2.315%`。这排除了“仅由函数入口未对齐”这一简单解释，但不能排除更细的代码布局、页/缓存占用、寄存器压力及跨分区关键路径效应。

独立四次 `cycles:u` 采样（baseline/candidate/candidate/baseline）均通过功能检查，排除 all-spin 等待后只累计模型符号：候选模型总采样 period -1.665%，changed compute 组 -1.676%，p3 -4.098%，p6 -6.830%。p6/b184 单函数 period 下降 20.65%，含栈地址样本从 745 降至 323；这与静态栈引用 20444→13444 一致。p29 的 b137 period 约 -0.60%，但 b139/b140/b144 分别约 +13.27%/+7.27%/+21.02%，p29 模型合计约 +1.96%；这几个函数的源代码均未改。因此不能把 p29 看成一个统一变慢的函数，也不能只用 b137 代表整段长尾。采样是诊断证据，不是精确 stall 或 cache-miss 计数。

本轮结论：消费者顺序规则确实减少了 p6/b184 的长寿命中间值、栈访问和模型采样周期；但在当前 XiangShan/GrhSIM 组合上，端到端 Host 8 对全部退化约 1.08%，不能进入默认路径。统一函数入口对齐仍退化约 1.46%，因此继续做简单对齐修补没有依据。规则和 `wide_state_read_refs`、`packed_array_late_index` 一样保持默认关闭。下一步应先以两版的逐 step/batch 关键路径对照，区分 p29 长尾、其他计算和等待阶段的贡献，再决定是否需要受控的代码布局实验；如果研究 link-order/section 分组，也只能根据通用依赖或可重建 profile 生成，不能按分区编号或单一 workload 固定顺序硬编码。另一候选是仅对静态中间值存活量明确下降的纯计算区域重排，减少无收益区域的扰动；目前未验证，不据此默认启用。

产物：`local_compute_use_order/c100000_4pairs/`、`c100000_repeat_4pairs/`、`profile/` 保存正式结果和采样；`alignment64/` 保存统一对齐排除实验，`source_summary.json`、`static_summary.json`、`profile/results.json`、`alignment64/audit.json` 保存静态/动态汇总。生成 1194.438 s、源检查 28.605 s、模型 `make -j32` 编译 229.340 s、harness 3.775 s；仅作复现成本记录。规则实现位于 `wolvrix/lib/emit/grhsim_cpp.cpp`，focused CTest 为 `emit-grhsim-cpp-local-compute-use-order`。

增量更新（2026-10-01，静态收益筛选）：宽泛版本并非让所有局部存活期变短。按生成代码中局部声明到最后使用的行距求和，p6/b184 为 1631494→94207，p3/b46 为 935148→1133004，p6/b47 为 126591→304700。后两者反而增加，因此先试通用的 supernode 级收益筛选，不按分区或信号名单选择。

新增可选参数 `local_compute_use_order_min_saved_bit_ops` 与 `local_compute_use_order_min_reduction_percent`，对应环境变量为属性名大写并加 `WOLVRIX_GRHSIM_` 前缀；二者默认均为 0，保留上述宽泛实验的复现方式，主开关仍默认关闭。对于已满足语义约束的 supernode，构造新顺序后，分别计算 `Σ 位宽 × (最后使用的操作位置 − 定义位置)`，只计入 >64 bit 的普通局部值，排除常量、直接状态引用和 packed-array lane 表示；标量常被表达式内联，暂不把它们视为独立存储。候选须使总量下降，且同时超过绝对量和比例门槛，未达标则完全保留原顺序。这里是 IR 位宽与操作跨度的静态近似，单位为 bit·operation，不能解释为实际内存字节或寄存器分配结果。

本轮预先固定门槛 1048576 bit·operation、25%，不根据逐分区速度调整。新增正向、绝对门槛拒绝、比例门槛拒绝与非法参数回归；focused 43.10 s、强制打开本规则/两项门槛/late-index 的完整 emitter 回归 320.28 s 均通过。完整 XiangShan 产物为 `local_compute_use_order_selective/`，baseline 仍为 §7.18，后续按同一 C=100000 两轮四对 AB/BA 验证。

并行准备的低频关键路径诊断只改 `common` 与 `eval_0` 两份线程封装，复用已有 eval 时间戳，每 127 step 保存一次各 part 的开始/结束时间，全部数组在 barrier 后读取。两版静态库均校验 7452 个未改 member 的 payload hash 完全一致，只替换两份 wrapper object；诊断运行期间暂停本任务的生成进程，结束后恢复。宽泛版本四次 baseline/candidate/candidate/baseline C=100000 全通过 Difftest，每版共 3150 个有效 step。采样全局 eval 69.758→73.571 µs，最后完成线程的完成时间 69.335→73.147 µs，完成后的收尾 0.424→0.423 µs；p6 最后完成占比 8.76%→4.10%，p29 为 27.17%→27.46%、成为瓶颈时 eval 94.026→99.810 µs，p15 为 19.94%→20.63%、62.006→66.770 µs。它支持“p6 收益被其他关键路径覆盖”，不支持把主因归为线程已完成后的 Host 收尾等待。诊断版改变 wrapper 布局，Host 中位数 19.8525→20.6415 s、约 +3.97%，比正式 +1.084% 更大，故仅作机制证据，不用其百分比代替正式结果。原始 TSV、构建对象校验与窗口统计位于 `local_compute_use_order/critical_probe/`。

增量更新（2026-10-01，筛选版正式结果）：完整生成后选中 15 个分区中的 104 个 supernode，改变 42 个 compute 源文件，其余 7477 个 `.cpp/.hpp` 和 33 个 `.h` 均 byte-identical。逐 supernode 核对证明：选中块逐字节等于宽泛重排版本对应块，其他块等于 baseline；没有额外改变表达式、操作数量或激活逻辑。重新编译的 7454 个 object 中仅 40 个变化，均来自选中源文件，其他 7414 个 object 逐字节相同。全 ELF 的 `size` text 统计 106914808→106863136 B（-0.0483%），因此不能用总代码体积缩减来解释下面约 1.6% 的 Host 收益。

| 静态指标 | baseline | 筛选版 |
| --- | ---: | ---: |
| p6/b184 函数代码 B | 296406 | 255440 |
| p6/b184 指令数 | 52842 | 50861 |
| p6/b184 静态栈引用 | 20444 | 13506 |
| p6/b184 入口栈帧 B | 17336 | 2760 |
| p6/b184 局部值到最后使用的行距和 | 1631494 | 94555 |
| p3/b19、p3/b46、p6/b47、p10/b146、p15/b129、p29/b137 | — | 源码与 object 均不变 |

正式复测沿用 node030 CPU96--127、NUMA1、N=K=32、all-spin、Clang23/O3、C=100000、fixed-ASLR、Difftest；baseline 是 §7.18 `packed_array_late_index`，candidate 只增加局部重排和本节预先固定的两项筛选门槛。两轮各四对 AB/BA 的 16 个正式样本与四个 C100 smoke 全部通过功能检查，正式签名与上文一致；所有成功样本纳入统计，不筛选外部负载或计时离群值。输入 ELF、image 与 NEMU 在两轮前后分别校验不变。

| 指标（配对变化的中位数） | 首轮 4 对 | 复测 4 对 | 合并 8 对 |
| --- | ---: | ---: | ---: |
| Host | **-1.623%（4/4）** | **-1.609%（4/4）** | **-1.609%（8/8）** |
| elapsed | -1.610% | -1.621% | -1.621% |
| 全局 eval | -1.633% | -2.309% | -2.008% |
| 全局 update | -0.517% | -0.047% | -0.047% |
| 最大分区平均 eval（p3） | -1.177% | -1.510% | -1.320%（7/8） |
| 分区平均 eval 之和 | -1.728% | -2.091% | -1.851%（8/8） |
| p6 eval | -5.524% | -6.075% | **-5.682%（8/8）** |
| p10 eval | -0.592% | -1.120% | -0.996% |
| p15 eval | -0.636% | -0.904% | -0.841% |
| p28 eval | -2.499% | -3.229% | -2.868% |
| p29 eval | -1.302% | -1.835% | **-1.510%（8/8）** |

Host 独立中位数：首轮 20.0455→19.8175 s，复测 20.0155→19.7160 s，合并 20.0155→19.7505 s。合并配对变化范围 -1.918% 至 -0.711%，AB 与 BA 均同向。合并全局 eval 独立中位数 70.627→69.227 µs，p6 为 40.7815→38.3295 µs，p29 为 30.361→29.897 µs。注意“中位数之比”和“逐对变化的中位数”不是同一个统计量，表格使用后者，不能拿两组独立中位直接反算表中百分比。

这轮已把宽泛重排的 Host +1.084% 回退转为可重复的 -1.609% 收益：保留 p6/b184 的大幅静态改善，显著减少无收益/反向区域的改动；但不能把全部端到端收益归于 p6，或凭源码相同就认定未改热点运行代价必然相同。默认开关仍保持关闭，本轮是固定工作负载上的机制与性能验证，尚未完成第二 workload 的泛化验证。产物保存在 `local_compute_use_order_selective/`：`selection_audit.json`、`object_audit.json`、`static_summary.json`、两组 `c100000*_4pairs/` 与 `results.json`。模型编译 228.149 s、harness 3.753 s；生成驱动 1615.518 s 包含主动暂停时间，仅作实验过程记录，不与前轮宣称生成速度差异。

筛选版的独立关键路径诊断同样只替换 wrapper object，并校验两边各 7452 个未改 archive member 的 payload hash 相同；四次 baseline/candidate/candidate/baseline 全部通过 Difftest，每次 1575 个抽样 step、每版合并 3150 个。合并抽样的 eval phase 为 69.472→68.823 µs（-0.934%），最后完成线程的完成时间为 68.980→68.398 µs（-0.844%），最后完成后的收尾等待为 0.492→0.425 µs（减少 0.066 µs）。p6 在全部抽样 step 中的平均 eval 为 40.266→37.699 µs、成为最后完成线程的占比为 8.60%→5.05%；p29 平均 eval 为 29.987→30.039 µs，成为最后完成线程的占比为 27.30%→27.17%，成为瓶颈时的 eval 为 92.934→92.336 µs，没有再出现宽泛版的 p29 长尾增大。早/中/晚三个窗口的 phase 变化分别为 -1.210%/-0.603%/-1.027%，三个窗口均同向；这不是对每一个 step 都会加速的保证。诊断二进制仍增加了 wrapper 代码，数值用于解释关键路径，不替代正式 Host A/B。

### 7.21 当前优化线与 Verilator 的条件瓶颈对照（2026-10-01）

用户暂时没有第二 workload，本轮继续在香山上定位：某个 GrhSIM 分区成为最后完成者时，同一 guest step、同一分区的 Verilator 究竟快在哪里；同时重新审查旧尝试，不能把早期效果小直接解释为优化机制无效。本轮只增加构建目录内的诊断 wrapper 和分析脚本，没有改变生产代码、默认选项或 Verilator 模型。

比较的 GrhSIM 是 §7.20 的 `local_compute_use_order_selective`：§7.18 late-index 加局部重排及 1048576 bit·operation / 25% 门槛，不叠加 wide-state-read-refs、bool-eager、batch guard 或 bitmap。Verilator 为 §7 的冻结 `clang23_threeway/verilator_o3`。两者来自同一 `default_line_ab_20260924/default_noenv/partitioned.json`，保持同一分区和通信。运行在 node030 CPU96--127、NUMA1、N=K=32、all-spin、host lane 9/CPU105、Clang23/O3、fixed-ASLR、C=100000，Difftest 开启。

完成低频计时 4 对 AB/BA、eval 内 core PMU 4 对、memory PMU 2 对、相邻半周期 PMU 2 对、无 wrapper 插桩的 branch-miss 采样 2 对、旧 bool-eager 复查 2 对，共 32 次 C=100000 和 10 次 C100 smoke，功能均通过。正式长度的签名全部为 `pc=0x80000c0c`、instructions=240349、cycles=99996、guest_cycles=100001、steps=200102；纳入全部通过样本，不按核空闲或计时离群值筛选。这是归因诊断，不把插桩程序的 Host 变化当作生产版收益。

#### 条件计时与选择偏差

每 127 step 复用 wrapper 已有的 eval 开始/结束时间戳。定义瓶颈为 `argmax(start_ns + duration_ns)`，即最后完成的分区，不是单看 duration 最大者。四对中每次 1575 个采样 step、每后端共 6300 个；对每个 GrhSIM 瓶颈样本，取配对 Verilator 的相同 step 和相同 part，下面为这些样本的合并算术平均，不是全程分区平均，也不是配对中位数。

| GrhSIM 最后完成分区 | 次数 / 占比 | GrhSIM eval µs | 同 step Verilator eval µs | G/V |
| --- | ---: | ---: | ---: | ---: |
| p29 | 1719 / 27.29% | 92.980 | 27.539 | 3.376 |
| p15 | 1246 / 19.78% | 61.140 | 58.658 | 1.042 |
| p3 | 1246 / 19.78% | 44.391 | 75.319 | 0.589 |
| p10 | 915 / 14.52% | 56.650 | 51.586 | 1.098 |
| p18 | 351 / 5.57% | 60.533 | 44.697 | 1.354 |
| p6 | 316 / 5.02% | 53.969 | 35.596 | 1.516 |
| p28 | 256 / 4.06% | 56.954 | 19.898 | 2.862 |

为避免“因为当次偶然变慢而被选为瓶颈”的偏差，又用另外三次 GrhSIM 运行的完成时间中位数选择当前运行的条件样本。p29/p28/p6/p10/p15/p3 的 G/V 分别为 3.376/2.854/1.524/1.093/1.040/0.592，主要结论不变；但 p18 从 1.354 降至 1.118，因此不能把 p18 的自选样本 35.4% 差距当成稳定的后端劣势。p29 四对各自的比值为 3.408/3.362/3.369/3.367，稳定性明显更强。

GrhSIM 全局 eval phase 平均 69.163 µs，可分解为最后完成线程的开始偏移 3.799、实际 eval 64.949、完成后的收尾 0.415 µs；Verilator 对应 74.077 = 1.217 + 72.182 + 0.679 µs。p29 成为瓶颈时自身开始偏移约 6.559 µs，eval 92.980 µs，完成后收尾约 0.362 µs。启动偏移仍有优化空间，但这次 p29 对照的主要差距位于模型 eval 内，不是模型已完成后 Host 仍长时间等待。Verilator 有 6171/6300（97.95%）样本由 p3 最后完成；不能只凭 GrhSIM 的最大分区平均 eval 指定下一个优化对象，p3 相对 Verilator 已明显更快。

#### 独立选样的线程内 PMU

先用上述四次 GrhSIM 计时的完成时间中位数，为 1575 个 step 固定瓶颈标签，再用于另一组 PMU 运行，避免按 PMU 运行本身的偶发延迟选样。固定标签与逐次实际最后完成者一致率 93.56%；p29/p15/p3/p10/p6/p28/p18 的唯一步数分别为 430/325/320/237/81/68/57。

每线程用 `perf_event_open` 建立四事件 pinned group，在 eval 前后读组计数，只统计用户态 delta，排除 kernel/hypervisor 及 eval 外 all-spin。core 组是 cycles/instructions/branches/branch-misses，另一次 memory 组是 cycles/instructions/cache-references/cache-misses；所有采样的 running/enabled 均为 1.0，没有复用缩放。PMU delta 包含小量读计数封装和计时函数的用户态开销，诊断布局也改变，因此不把它当成零扰动 walltime。

| 固定瓶颈分区 | G/V 动态指令数 | G IPC | V IPC | G 分支预测失败/次 eval | V 分支预测失败/次 eval |
| --- | ---: | ---: | ---: | ---: | ---: |
| p29 | 1.524 | 1.278 | 2.635 | 4317.2 | 29.6 |
| p28 | 1.651 | 1.845 | 3.023 | 1293.6 | 9.5 |
| p6 | 1.237 | 1.736 | 2.234 | 588.5 | 45.9 |
| p10 | 0.814 | 1.595 | 2.152 | 1530.1 | 536.0 |
| p15 | 0.654 | 1.539 | 2.466 | 1906.5 | 195.8 |
| p18 | 0.729 | 1.454 | 2.221 | 1378.6 | 636.2 |
| p3 | 0.711 | 1.922 | 1.531 | 88.1 | 2274.7 |

IPC 是每 CPU cycle 退休的指令数，不是 CPU 使用率。p29 的单半周期 CPU cycles 比值为 3.142，可严格分解为指令数比值 1.524 × CPI 比值 2.061；但这个“指令更多”的结论仅限当前半周期，不能推广到相邻两次 eval。`cycles / eval_ns` 在两边约为 3.6 GHz，p29 为 3.587/3.614 GHz，不足以解释数倍差距。memory 组的 p29 generic cache misses 为约 33852/15898、MPKI 为 78.93/56.50，支持继续研究访存和局部性，但未做层级事件解码，不能直接宣称为 LLC miss、DRAM 瓶颈或确定的 stall 百分比。

#### 必须区分半周期关键路径与整周期工作

harness 每周期执行 `set_clock(1); step(); set_clock(0); step();`，本次 step 编号为奇数对应上升沿、偶数对应下降沿。固定 p29 瓶颈的 430 个 step 全部为偶数，p28 的 68 个也全部为偶数，p15 的 325 个全部为奇数。因此补测每个选定 step 的前一次、当前、后一次 eval，不能只比较工作分布不同的单个半周期。

| p29 固定瓶颈样本的相邻计时 | GrhSIM µs | Verilator µs |
| --- | ---: | ---: |
| 当前下降沿 eval | 94.573 | 28.716 |
| 后一个上升沿 eval | 3.719 | 35.466 |
| 当前 + 后一次 | 98.292 | 64.182 |
| 前一次 + 当前 | 98.077 | 63.981 |

同一次相邻采样中，当前加后一次的 p29 eval 比值为 1.531，前一次加当前为 1.533，均远小于单半周期约 3.4 倍。相邻两次的指令数反而是 431797 对 621435，GrhSIM 少 30.5%；IPC 是 1.227 对 2.691，分支预测失败约 4414 对 52，cycles 比值为 1.523。说明整周期尺度上的关键缺口主要是每条指令执行效率，而不是整体执行了数倍工作；分支行为是已明确观察到的差异，尚不能把全部 CPI 差距归给单一原因。

GrhSIM 在下降沿计算出部分候选数据，后续上升沿复用；Verilator 的工作分布更偏向上升沿。p6 当前加后一次为 93.723/96.021 µs，p15 为 83.758/87.861 µs，两个后端的总量已经相当；p28 为 62.615/49.689 µs，p10 为 96.844/72.949 µs，仍有明显差距。相邻求和是这些固定条件样本的分区工作量比较，不等于全程周期平均，更不等于 Host 加速上限。单半周期的长尾仍会阻塞该次全局 barrier，是真实瓶颈；但把计算简单挪到另一个半周期也可能拉长另一条关键路径，不能直接把 Verilator 的当前半周期时间替换进 GrhSIM 后预测最终收益。

#### 从分支样本追到长 mux 链

另外对两版无诊断 wrapper 的原始二进制做 branch-misses:u、period=20011 的 AB/BA 采样，排除 all-spin，只统计模型符号。GrhSIM p29 两次合计 26965 个分支预测失败样本，其中 b140/b141/b144/b145/b146 五个 compute batch 占 82.68%。单独 b140/b145/b146 占 52.56%，这三个函数没有 `&&`、`||` 或 `grhsim_changed_*` 条件，其主要内容是长 mux 链。mux 指“按条件在两个候选值中选择一个”，连续优先选择形成链。

| 当前 G 代表函数 | mux 调用数 | 条件跳转数 | 条件移动数 | 静态 `%rsp` 栈引用数 |
| --- | ---: | ---: | ---: | ---: |
| p29/b140 | 4088（8 × 511） | 1032 | 3072 | 4504 |
| p29/b145 | 4160（8 × 520） | 1056 | 3120 | 0 |
| p29/b146 | 2080（4 × 520） | 528 | 1560 | 0 |
| p15/b132 | 4088 | 1040 | 3064 | 4504 |
| p28/b145 | 4088 | 1040 | 3064 | 0 |

这些统计来自实际 Clang23/O3 ELF，不是 C++ 行数。p29/b140 源码只有少量活动字/节点 guard，千余条件跳转主要来自 payload；p29/b145 和 b146 已没有 `%rsp` 栈访问却仍有大量分支样本，因此继续只围绕 spill/栈帧优化无法覆盖主要残余成本。

生成器的 `kMux` 使用 `grhsim_mux_u64(cond, t, f)`，runtime 表达式为 `m = -int64_t(cond != 0); (t & m) | (f & ~m)`。虽然源码没有条件跳转，Clang 会识别为 select，并在最终机器码重新产生 `cmp/test + cmov + je/jne`；不能把“写成位掩码”等同于“机器码无分支”。当前 cheap-scalar-inline 路径还按 1024 字符等条件截断局部表达式，多个 mux 被分段到提前计算的临时值，外层选择不能自动避免所有内层候选求值。下一轮须以整条优先链和实际机器码验证，不能只改 helper 拼写。

Verilator 对同一类寄存器写数据采用另一个值得借鉴的组织：`VWolviRepCutUnit_part_29___024root__15.cpp` 的 `nba_sequent__TOP__2` 在写使能组合条件内生成候选数据和嵌套 `?:`。例如 `fpRat.difftest_table_6`，对应 GrhSIM b140 先生成 `_val_4012806` 并写入 `value_u8_slots_[118]`，b148 才在 posedge 及 `value_bool_slots_[391]` 写使能下消费这个候选值。这里只用信号名追踪同一语义，未来优化不得按它匹配。

这说明可以研究“只有特定事件/写使能消费者需要的纯组合锥，按需求值”的通用模式，但还没有统计候选数据最终被消费的比例。提前算出的值可能在下一沿被复用，不能仅因当前沿不提交就说计算浪费；若要延迟，必须正确维护 dirty/invalidation、消费者共享与事件前状态，不能简单跳过后遗失更新。源代码证据支持该候选方向，不等于已证明它比链级降低分支更有效。

采样边界：上述 IP profile 是全程样本，不是逐 step gated profile；独立 PMU 中 p29 的固定瓶颈组占该分区所有抽样 branch misses 的 83.68%，支持热点的相关性，但不能把 82.68% 当作瓶颈时间占比。普通 perf IP 有 skid，也不能凭单条采样落点认定某个具体跳转负责全部损失。数据依赖链、访存、取指等仍可能共同压低 IPC，分支失败数不能直接乘固定惩罚周期得到精确分解。

#### 重新评估旧 bool-eager 尝试

旧 `bool_eager_logic` 将满足条件的布尔 `&&/||` 改为对已求值 bool 的 `&/|`，目的是去掉短路分支。实现只接受位宽为 1、已经物化为简单 bool slot 或局部标识符的两个操作数；不覆盖复杂嵌套表达式，更不处理 `kMux` 链。旧候选与当前版本的 p29/b140、b141、b145、b146 源文件逐字节相同，所以不能用其 p29 无收益否定长 mux 分支优化。

本轮用旧 baseline `batch_dispatch_guard_ab/baseline`（目录名不表示开启 guard）和旧 `bool_eager`，仅替换同样的 PMU wrapper，重新做两对 AB/BA；仍用本轮独立固定的瓶颈 step 集合，下面是条件样本的合并均值变化，不与当前 selective 版本跨窗口相减。

| 分区 | baseline eval µs | bool-eager eval µs | eval 变化 | 指令数变化 | 分支预测失败变化 |
| --- | ---: | ---: | ---: | ---: | ---: |
| p10 | 58.611 | 50.545 | -13.76% | -1.53% | -46.26% |
| p28 | 59.837 | 54.612 | -8.73% | -8.51% | -3.28% |
| p29 | 95.487 | 95.599 | +0.12% | -0.42% | +0.53% |
| p15 | 63.762 | 64.427 | +1.04% | -0.67% | -0.50% |

p10 的 IPC 1.566→1.789，改善与分支失败减少一致；p28 更接近减少指令，而非消除错分支。p29 总分支数虽少 10.14%，错分支约 4368→4391，热点基本未覆盖，不能只看“少了多少 branch”。旧 C=100000 四对非 PMU 数据的 Host 配对中位本就有 -0.531%、p10 全程平均 eval -10.488%、p28 -6.607%，这次支持其局部机制，不应归为完全无效。旧 C30000 Host 近中性也不能替代现在的条件瓶颈判断。

因此旧方向保留重新组合的价值，但当前结果只证明旧 baseline 上的局部收益；尚未测试与 late-index + selective-use-order 叠加，不宣称当前 Host 也会按同样百分比改善，不因此改默认。后续可检查该规则依赖生成字符串形态的覆盖限制，改用 IR 的纯度、位宽与已求值性质决定是否适用，继续保留短路副作用语义。

#### 结论与下一轮优先级

1. 优先处理长优先 mux 链的通用生成方式。p29 的瓶颈频率、半周期长尾、两沿合计差距及机器码证据都支持它优先于继续缩减 p3 平均时间。分别比较链级保留优先级的按需选择、减少强制物化和必要的无分支形式；one-hot 化必须由 IR 证明互斥，不可假设。先确认动态错分支/指令效率改变，再检查相邻两次 eval 和最终 Host。
2. 将事件/写使能下的纯数据锥按需计算作为独立候选，不与 mux 变换同时推出，否则难以归因。必须证明没有输出、DPI 或其他独立消费者，或为这些消费者保留原行为，并验证跨沿缓存有效性和多消费者语义。
3. 重新组合旧 bool-eager 与当前有效规则，对 p10/p28 有明确机制依据；但须独立做全图 C=100000 AB/BA，不能手选 part 或信号启用。保留所有通过样本，以 Host 为采纳标准，不用局部 eval 或源代码看起来无分支作结论。
4. p6 的条件半周期差距主要受工作分布影响，两沿合计已接近 Verilator；p18 的自选长尾有明显选择偏差。它们暂不优先于 p29 的通用 mux 生成问题。没有第二 workload 不阻止当前归因和实验，但所有结论仍限定为这一输入的证据，未完成跨 workload 泛化验证。

复现产物统一位于 `build/repcut_grhsim_20260925/`：计时 `conditional_match_v1_c100000/`，core/memory PMU `conditional_pmu_core_v1_c100000/`、`conditional_pmu_memory_v1_c100000/`，相邻半周期 `conditional_adjacent_v1_c100000/`，旧规则复查 `conditional_old_bool_v1_c100000/`。`conditional_backend_compare/results.json` 保存条件计时、交叉选样及 PMU；`supplement.json` 保存相邻沿、静态 mux、分支热点与旧规则复查；`branch_profile/summary.json` 与 `.data/.samples.txt` 保存全程采样。构建脚本为 `build_probe.py`、`build_old_bool_probe.py`，探针为 `pmu_probe.hpp`，汇总为 `report.py`、`supplement_report.py`，均在同一 `conditional_backend_compare/` 下。

构建不变性检查：GrhSIM 每个诊断 archive 只替换 `common` 和 `eval_0` 两份线程 wrapper，其他 7452 个 member payload 与对应候选一致；Verilator 32 个模型 archive 共 1307 个 member 与冻结 O3 版本完全相同，仅重编 wrapper/harness。各轮 manifest 保存二进制身份，采样使用的原始二进制运行前后校验不变。数据中的理想化 fixed-other-threads replay 只是固定其他线程时间的计算练习，不包含计算跨沿迁移及编译布局变化，本节不将其作为可实现收益预测。

### 7.22 长优先 mux 链的按需选择（2026-10-01）

承接 §7.21 的机器码与条件瓶颈证据，本轮先单独验证长 mux 链的通用生成规则，不同时加入事件需求求值或 bool-eager，避免混淆归因。对照基线固定为 §7.20 的 `local_compute_use_order_selective`，即 late-index 加 1048576 bit·operation / 25% 门槛的局部重排；候选只增加 `priority_mux_chains` / `WOLVRIX_GRHSIM_PRIORITY_MUX_CHAINS=1`。开关默认关闭，不改 Verilator、分区结果、通信或 all-spin 框架，不按 part、模块、信号名或采样次数匹配。

实现把至少 8 级、1--64 bit 的同宽标量 mux 链转换为从外向内的优先选择：检查当前最高优先条件，命中则返回其数据，否则继续下一层；最后返回原来的默认值。允许沿 true 或 false 数据分支继续，也允许混合方向，不假设条件互斥。这里只延迟链内的 mux 选择，不移动任意有副作用的计算，也不改变事件与半周期调度。生成的结果仍经原来的写回、变化检测和下游激活路径。

第一版边界保守：只在同一纯 compute supernode 内吸收中间节点；被吸收结果必须未物化、不需独立变化跟踪且只有一个消费者。共享或跨 supernode 的中间值保留。整个块遇到副作用、状态写、未知操作、事件值、重复 canonical storage 写入或先读后写别名即不改写，避免延迟读破坏旧值语义。宽值、短链和异宽 mux 不在本轮范围。该筛选依据 IR 的数据依赖与存储性质，不依赖生成文本中的特定变量名。

专项 CTest `emit-grhsim-cpp-priority-mux-chains` 已在 node030 上通过，生成代码用 Clang23/O3 编译运行。六种模式覆盖默认、显式关闭、开启、拆 helper、叠加 late-index/use-order 和环境变量开启；包括 520 级链、1/7/8/64 bit 结果、64 bit 非零条件、重叠条件、true/false 混合延续、共享中间结果、跨节点边界、副作用拒绝和短链拒绝。每种模式执行两次 init、各 1100 组全零/全真/逐位命中/随机输入，每组两次 eval 并对照独立顺序计算；同时验证下游结果与默认/显式关闭源码逐字节一致。

实验产物统一置于 `build/repcut_grhsim_20260925/priority_mux_chains/`。`run_build.py` 固定当前有效选项、保存生成器身份并完整生成 32 个模型；`static_report.py` 检查变更只出现在 compute 源文件，且同时统计完整 object 的机器码（包括编译器可能拆出的 lambda），不把函数内代码移出误记为消除。完整香山生成、Difftest 和两轮 C=100000 AB/BA 正在继续，以上仅是实现与专项正确性检查，不是性能收益结论。

#### 第一版完整 A/B 与实现层回退定位

完整生成与构建完成：生成 1104.895 s，32 路模型编译 228.954 s，harness 构建驱动 3.916 s。通用规则匹配 30/32 个分区的 6617 条链、198185 个 mux，修改 707 份 compute 文件；其他 6846 份源码/头文件/Makefile 相同，7454 个 archive 对象中 6747 个 payload 完全相同。最长链 609 级；没有手选分区或信号。默认和选项开启的完整 `emit-grhsim-cpp`、GrhSIM/Verilator RepCut package 测试均通过，默认关闭时生成结果不变。

node030 CPU96--127、NUMA1、固定 ASLR、N=K=32、all-spin、Clang23/O3，完成两轮各 4 对 C=100000 AB/BA，另有各轮两次 C100。16 次正式运行全部通过 Difftest，签名均为 pc `0x80000c0c`、instructions 240349、cycles 99996、guest_cycles 100001、steps 200102。保留所有功能通过样本，不按负载或耗时删样。下面数值为 8 次运行各自的中位数；百分比单独按每对 `candidate / baseline - 1` 后取中位数，不是两个独立中位数相除。

| 指标 | selective baseline | 第一版 lambda | 配对变化 |
| --- | ---: | ---: | ---: |
| Host s | 19.8380 | 28.2195 | +42.118% |
| process wall s | 19.8750 | 28.2550 | +42.052% |
| 全局 eval µs/step | 69.2285 | 110.6590 | +59.692% |
| 全局 update µs/step | 24.4610 | 24.4980 | +0.200% |
| p29 eval µs/step | 29.8765 | 20.4330 | -31.540% |
| p15 eval µs/step | 24.9200 | 19.7710 | -20.855% |
| p28 eval µs/step | 21.0880 | 18.3820 | -12.820% |
| p25 eval µs/step | 19.8635 | 82.0310 | +312.903% |
| p27 eval µs/step | 20.0335 | 74.8825 | +273.806% |
| p14 eval µs/step | 18.6000 | 68.5985 | +268.796% |

因此不能把 p29 的改善作为整体采用依据，Host 为 0/8 对获胜。两轮 Host 配对中位分别为 +42.168%、+42.080%，不是单次异常。独立 timing wrapper 两对 AB/BA 每版合计 3150 个 step 的最后完成者，baseline p29 占 861/3150，候选 p25 占 1485/3150；phase 69.562→108.918 µs，winner start 4.149→4.005 µs，主要增加在模型计算而非启动延迟。

相邻 eval 的 core PMU 另做两对 AB/BA，所有 running/enabled=1.0。继续沿用 §7.21 的独立固定 p29 标签，每次 430 个 step，不按本轮耗时重新挑选；当前加下一次 eval 的均值如下。

| p29 固定样本两沿合计 | baseline | 第一版 lambda |
| --- | ---: | ---: |
| eval µs | 97.834 | 62.094 |
| instructions | 431796.5 | 429795.9 |
| cycles | 349965.8 | 222838.5 |
| branches | 18700.3 | 33108.3 |
| branch misses | 4418.4 | 69.9 |
| IPC | 1.234 | 1.929 |

动态指令仅少 0.463%，分支数反而多 77.05%，但错分支少 98.42%、时间少 36.53%，有效频率 3.577/3.589 GHz 相近。这支持长链优先选择改善 p29 的分支行为，而非减少数倍工作量；不把 miss 数直接换算成精确 stall 时间。普通 timing 的同一组 p29 当前 eval 93.159→60.961 µs，排除了仅 PMU 布局下有效的解释。

回退分区存在另一种生成形态。以 p25/b222 的 25 级链为例，原先是同一函数内的 select/cmov；第一版的捕获 lambda 被 Clang23 单独生成函数，调用前为条件槽逐个构造指针捕获对象。完整 object（含 lambda）的静态指令数 1133→3260、条件跳转 32→416、调用 0→16、`%rsp` 引用 0→848、text 6213→16539 B。p14/b215 同样发生；p27/b240 为调用 0→16、栈引用 0→832。不能只看主体函数变小就宣称降低了机器码开销。

以本轮 timing 的候选完成时间中位数独立选出 745 个 p25 瓶颈 step，再对另一轮 PMU 在相同步号比较：eval 33.988→151.904 µs，指令 +23.86%，IPC 1.839→0.511，错分支 380.4→14575.7。增加的捕获/调用/栈访问和分支预测失败同时存在，尚不把所有回退归因于某一个指令类别。相邻两沿合计仍为 40.042→163.274 µs，不能解释成工作转移到了另一沿。

据此修正的是实现形式而非按负收益分区关开关：仍用完全相同的纯度、单消费者、位宽、链长规则，把 lambda 提前返回改为函数内局部变量加 `do/break`。专项测试再次通过（45.31 s），同时断言链生成不含捕获 lambda；完整重新生成与独立 A/B 继续进行。第一版不改默认，也不能因修正已写入就提前宣称 Host 回退已消除。

第一版数据位于上述目录的 `c100000_4pairs/`、`c100000_repeat_4pairs/`、`critical_probe/`、`adjacent_probe/`；汇总 `results.json`、`probe_results.json`、静态检查 `static_summary.json`。每个 probe archive 只换两个 wrapper 对象，其他 7452 个对象与对应候选相同。baseline ELF SHA-256 为 `fc22ce303e98b7eeb6cb8d9286c36ad4fac4d801928ad4384b2ce5c02b1c9cb6`，第一版为 `f7767b33e6f2ca31ac1ede5fb3a13f6baab09f793b999babaf9634df6c2aa6b1`，运行前后身份不变。修正版使用同级 `priority_mux_inline/`，避免覆盖第一版的成功样本。

#### 函数内展开的复测与短链分支代价

`priority_mux_inline` 完整生成 1063.433 s、模型编译 226.469 s、harness 构建驱动 3.728 s。匹配范围与第一版相同，仍为 6617 条链、707 份 compute 文件；这里只改生成形式。专项测试 45.31 s、默认完整 emitter 测试 311.70 s、开启选项的完整 emitter 测试 315.71 s、GrhSIM/Verilator RepCut package 测试均通过。

完成三轮各 4 对 C=100000，24 次正式运行与 6 次 C100 全部通过。第二轮第一对的 baseline 与本代理启动的 timing wrapper 编译重叠，Host 为 32.424 s；该功能通过样本完整保留并标注，不把其候选获胜解释为优化收益。第三轮是发现重叠后预先决定补做的完整四对，未与自身编译重叠。`paired_results.json` 同时报告全部 12 对和排除这一已知重叠对的敏感性结果，不按事后耗时筛选其他样本。

| 无诊断 wrapper 指标 | 全部 12 对的配对变化 | 11 对无已知重叠的配对变化 |
| --- | ---: | ---: |
| Host | +3.606%（1/12 获胜） | +3.765%（0/11 获胜） |
| process wall | +3.597% | +3.778% |
| 全局 eval | +4.834% | +4.860% |
| 全局 update | -0.290% | -0.172% |
| p29 eval | -36.956% | -36.920% |
| p15 eval | -25.622% | -25.580% |
| p28 eval | -17.243% | -17.236% |
| p25 eval | +96.019% | +96.034% |
| p27 eval | +102.352% | +102.530% |
| p14 eval | +116.559% | +116.625% |

两轮完全未重叠的四对，Host 分别 +3.374%、+3.979%；因此 lambda 捕获/调用确实是第一版的一层问题，但去掉它不足以使无差别改写盈利。p25/b222 的静态调用和栈引用均归零，text 从第一版 16539 B 降至 7853 B；条件跳转仍为 392，对照原有 32，原有 376 条 cmov 则变成零。p14/b215、p27/b240 也不再有 lambda 调用和捕获帧，但大量连续分支仍在。

另做 timing 和相邻 PMU 各两对 AB/BA，均通过且无自身编译重叠，PMU running/enabled 全为 1.0。固定 §7.21 标签的 p29 当前 eval 计时为 92.786→58.011 µs；相邻两沿 PMU 计时 97.342→63.035 µs（-35.24%），指令 -1.19%、错分支 -97.34%、IPC +52.12%。说明长链收益不是 lambda 引起的偶然布局效应。

新瓶颈使用这次独立 timing 的候选完成时间中位数选样，再到另一轮 PMU 测量。p25 的 160 个固定 step，当前 eval 49.921→99.901 µs，指令 323100→316449，错分支 710.3→7891.8，IPC 1.804→0.885；有效频率 3.588/3.579 GHz。p27 的 248 个 step 为 47.189→98.814 µs、错分支 698.6→8222.5；p14 的 149 个为 41.835→92.949 µs、错分支 475.6→7945.8。相邻两沿合计仍退化，不是把工作搬到另一沿。短链原先的 cmov 更合适，不能以“分支允许提前结束”推导出任意链长都会更快。

下一版在相同语义证明上增加 `priority_mux_min_chain_length` / `WOLVRIX_GRHSIM_PRIORITY_MUX_MIN_CHAIN_LENGTH`，作为统一的 IR 链长门槛，先测 128。整项优化仍默认关闭；显式开启时门槛缺省 128，允许设置整数 >=2。128 是机制引导的首个保守实验点，并非已证实最优值。没有按 part、模块、变量或性能计数定名单，也不同时加入 bool-eager。本轮没有第二 workload，不据此宣称跨 workload 保证收益。

复现目录 `priority_mux_inline/` 保存全部三轮样本、`paired_results.json`、`probe_results.json` 和 `static_summary.json`。二进制 SHA-256 为 `199ac020e8188061a573b8a522bea55d017ae7012be31777d59f68af5942ffa4`。增量勘误：统一静态反汇编脚本计入两条对齐指令后，上一小节 p25/b222 的静态指令数为 1135→3262；调用、栈引用、text 字节和结论不变。

#### 128 级门槛的完整整机验证

`priority_mux_min128` 保持同一 selective baseline，只开启上述链改写且统一设置门槛 128。完整生成 1522.746 s，其中 JSON 读取 685.881 s；模型编译 225.721 s，harness 驱动 3.611 s。生成耗时仅作本次构建记录，不将跨窗口读入差异解释为优化本身的代价。该规则匹配 128 条链、57864 个 mux，长度分布为 130×8、162×8、164×8、511×64、520×32、609×8。改动 6 个分区的 34 份 compute 源码；其他 7519 份源码/头文件/Makefile、7420/7454 个 object payload 与 baseline 相同。

专项测试扩展至 11 种模式并通过（83.16 s），增加缺省门槛 128、16/520/521 边界、属性优先于环境变量及非法数值诊断；门槛 521 未匹配时输出逐字节等于默认。完整默认 emitter、开启门槛与既有有效选项的 emitter、两后端 RepCut package 测试分别通过，耗时 306.717/313.050/45.439 s。优化总开关仍默认关闭。

node030 CPU96--127、N=K=32、all-spin、Clang23/O3、固定 NUMA/ASLR/镜像不变。两轮各四对 C=100000 的 16 次正式运行及 4 次 C100 全部通过，功能签名与前文相同；全部样本保留，没有自身编译重叠。两轮 Host 配对中位分别为 -9.608%、-8.966%，合并如下；中位数与配对百分比的定义沿用前文。

| 普通运行指标 | selective baseline | min128 | 配对变化 |
| --- | ---: | ---: | ---: |
| Host s | 19.7930 | 17.9955 | -9.076%（8/8 获胜） |
| process wall s | 19.8300 | 18.0350 | -9.063% |
| 全局 eval µs/step | 69.1455 | 59.7075 | -13.535% |
| 全局 update µs/step | 24.4245 | 24.4495 | +0.247% |
| p29 eval µs/step | 29.8235 | 19.4695 | -34.690% |
| p15 eval µs/step | 24.8710 | 18.7780 | -24.409% |
| p28 eval µs/step | 21.0210 | 17.8360 | -15.205% |
| p3 eval µs/step | 45.1035 | 45.5665 | +1.142% |
| p10 eval µs/step | 36.4185 | 37.5840 | +2.914% |
| p21 eval µs/step | 18.8060 | 19.0145 | +1.164% |

p14/p25/p27 全程 eval 配对变化仅为 +1.816%/+2.653%/+2.653%，先前翻倍的退化消失。这三个分区所有源码和对象已恢复 baseline，因此不能将残余百分点差异归为这些分区被改写；布局、并行运行条件与缓存等影响尚未单独拆分。p3 的全程平均仍最大，但并非每一步都是它最后完成；整体收益仍需结合逐 step 瓶颈分布解释，不能用最大分区平均值不变否定。

长常量选择链仍是需要检查的边界。静态 p21/b93 的 609 级常量链原为 19 条条件跳转、1825 条 cmov，min128 为 1842/1；与 p29 的动态候选数据选择不同，常量链没有同样的候选数据加载可省。当前 p21 全程均值没有大幅退化，不能仅凭跳转条数决定继续收紧规则；后续独立条件计时/PMU 检查它是否形成新的瓶颈。128 不是已证明最优的通用阈值，也不宣称跨 workload 保证收益。

本轮 ELF SHA-256 为 `779b4a73856019f71cb6f50de07a4726806ba51c09e21d58a7978e69d25ef741`。复现目录为 `build/repcut_grhsim_20260925/priority_mux_min128/`，普通运行在 `c100000_4pairs/` 与 `c100000_repeat_4pairs/`，汇总 `paired_results.json`。同级 `priority_mux_chains/validate.py` 按普通运行、probe 编译、条件计时、相邻 PMU 的顺序执行，避免自身编译与性能测量重叠。每个 probe archive 只替换两个 wrapper，其他 7452 个 member payload 不变；探针结果和同窗口 Verilator 对照接续记录。

#### min128 的条件计时与机制核实

另行完成 timing 与 adjacent PMU 各两对 AB/BA，8 次正式 C=100000 及 4 次 C100 全部通过，期间不编译。每版计时 3150 个 step，PMU 每次 4726 个相邻沿样本；全部计数 running/enabled=1.0。固定 §7.21 的独立标签，不根据本轮 PMU 时间重新挑样。当前 eval 的普通探针计时 p29 为 92.406→57.378 µs（-37.907%），p15 为 61.697→45.060 µs（-26.966%），p28 为 56.468→45.466 µs（-19.484%）。

| 独立固定瓶颈组、当前加下一次 eval | baseline µs | min128 µs | 时间变化 | 指令数变化 | branch misses 变化 | IPC baseline→min128 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| p29，430 step/run | 96.641 | 62.699 | -35.122% | -1.165% | -97.806% | 1.245→1.893 |
| p15，325 step/run | 83.793 | 60.982 | -27.223% | -1.580% | -94.748% | 1.472→1.983 |
| p28，68 step/run | 60.154 | 50.929 | -15.334% | +0.056% | -96.934% | 1.783→2.104 |
| p10，237 step/run | 95.314 | 94.818 | -0.520% | <0.001% | +0.126% | 1.638→1.644 |

p29 两沿 branches 18700→33024，branch misses 4415→97，有效频率 3.589→3.596 GHz；不是靠降低分支总数、少执行数倍指令或频率变化取得收益。这里支持的是优先链生成改变了分支行为、提高执行效率，不把 miss 数乘某个固定惩罚当成精确周期归因。

低频计时的全局 eval phase 从 68.924 降到 57.331 µs，可以分解为最后完成线程的开始偏移 3.818→3.841、eval 64.703→53.039、收尾 0.403→0.451 µs。主要变化位于模型求值。该探针版本本身改变 wrapper 布局，因此不把其 16.8% phase 改善替换上表普通运行的 13.535%。

| 最后完成分区 | baseline 次数/3150 | min128 次数/3150 | min128 比例 |
| --- | ---: | ---: | ---: |
| p10 | 512 | 691 | 21.937% |
| p29 | 857 | 614 | 19.492% |
| p3 | 588 | 597 | 18.952% |
| p18 | 149 | 308 | 9.778% |
| p6 | 168 | 264 | 8.381% |
| p15 | 606 | 206 | 6.540% |
| p28 | 120 | 77 | 2.444% |
| p21 | 24 | 39 | 1.238% |

候选两次独立 timing 的完成时间中位数选出 1575 个新标签，与逐次 winner 一致率 90.413%。再用这些固定标签查另一轮 PMU，p21 的 19 个唯一步数当前 eval 为 42.488→46.367 µs（+9.132%），错分支 234.7→881.6、IPC 1.757→1.551；相邻两沿 56.336→60.712 µs（+7.767%）。用另一轮 timing 给当前轮选标签的交叉检查也为 +8.876%，支持长常量链存在局部退化。它在当前整机中只占少量瓶颈，故不因它否定已测的整体收益，也不因此把现有 128 门槛称为充分的收益模型。后续可以按 IR 数据是否常量细分，不应按 p21 名称排除。

`probe_results.json` 保留旧固定标签、新候选标签、相互交叉选样、phase 分解和每次运行均值。下一优先级须结合更新后的 Verilator 条件对照决定：p29 错分支已大幅收敛，不能继续假定同一热点仍占原来的瓶颈份额；p10/p18 的难预测分支与之前 bool-eager 尝试需在当前有效线重新评估。

#### min128 与 Verilator O3 的同窗口对照及本轮结论

保持相同 node030 CPU96--127、Clang23/O3、N=K=32、all-spin、C=100000 和输入，另做冻结 Verilator O3 与 min128 的两轮各四对普通 AB/BA。16 次正式运行及 4 次 C100 全部通过 Difftest，功能签名不变，二进制运行前后身份一致；无自身编译重叠，保留全部样本。Verilator ELF SHA-256 为 `12ff6327e7fa4a4866974bfe6727821bebe6f9e46e8b2c9407482251d136958d`，GrhSIM 仍为本节上述 min128 SHA。两轮 Host 配对中位变化分别为 -14.357%、-14.636%。

| 普通运行指标 | Verilator O3 | GrhSIM min128 | 配对变化 |
| --- | ---: | ---: | ---: |
| Host s | 21.1110 | 18.0015 | -14.636%（8/8 获胜） |
| process wall s | 21.1600 | 18.0400 | -14.644% |
| 全局 eval µs/step | 76.7745 | 59.8950 | -22.011% |
| 全局 update µs/step | 23.0845 | 24.4830 | +6.188% |

这是同窗口的八对结果，不用另一窗口的 GrhSIM 17.9955 s 与这里的 Verilator 中位数相除。相对原 selective GrhSIM 的 Host -9.076% 是本次单项优化收益；相对 Verilator 的 -14.636% 则包括当前 GrhSIM 整条有效线的差异，不能全部归于长 mux 链。百分比均先逐对求比值再取中位数。GrhSIM update 仍慢，但 eval 的减少足以降低最终 walltime。

随后 timing 与 adjacent PMU 各做两对 AB/BA，8 次正式运行及 4 次 C100 也全部通过；PMU running/enabled 最小值与均值均为 1.0。候选两次独立 timing 的完成时间中位数生成 1575 个固定标签，再到另一轮 PMU 查询相同步号，标签与各轮实际 winner 一致率 89.810%。下面“当前”是 GrhSIM 被选为瓶颈的半周期，“两次”是当前加下一次 eval；均为所选 step 的条件均值，不是全程分区均值。

| 分区 | 唯一步数/run | 当前 eval µs，V→G | 两次 eval µs，V→G | 两次时间变化 | 两次 IPC，V→G | 两次 branch misses，V→G |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| p3 | 312 | 80.830→44.390 | 150.740→88.752 | -41.122% | 1.548→1.950 | 4159.6→181.5 |
| p6 | 133 | 36.809→56.302 | 96.165→94.387 | -1.849% | 2.202→1.584 | 206.1→1146.4 |
| p10 | 350 | 54.759→56.809 | 73.420→93.869 | +27.851% | 2.127→1.663 | 627.9→2121.2 |
| p15 | 92 | 59.740→48.004 | 87.173→57.557 | -33.974% | 2.426→1.984 | 301.9→120.8 |
| p18 | 158 | 48.539→53.883 | 70.742→95.467 | +34.951% | 2.260→1.593 | 779.4→1999.8 |
| p28 | 33 | 21.391→48.802 | 50.215→50.986 | +1.535% | 2.855→2.096 | 101.9→41.6 |
| p29 | 321 | 28.622→62.445 | 63.983→64.917 | +1.461% | 2.690→1.884 | 53.8→98.3 |

继续沿用 §7.21 的旧固定 p29 标签（430 个 step/run）时，两次 eval 为 Verilator 63.975、GrhSIM 62.868 µs（-1.730%），指令 621441→426764、IPC 2.690→1.889。新旧标签都支持 p29 两沿合计已接近，而非仍慢约 50%；也不能声称所有条件样本都已更快。当前半周期仍明显更慢，下一次却约 2.5 µs 对 35.4 µs，说明工作集中在不同半周期。每步有全局同步，整周期总工作相近并不消除这一半周期的关键路径。

p10/p18 则不同：两次合计仍分别慢 27.851%/34.951%，指令仅为 Verilator 的 99.808%/94.912%；有效频率分别为 3.595/3.589 GHz、3.601/3.592 GHz。它们仍有低 IPC 与更多错分支的执行效率差距，不是生成指令明显更多或频率明显更低。用另一轮 timing 选标签的交叉检查，当前 eval 也分别慢 5.121%/9.709%，排除了仅由本轮自选极值造成全部差距的解释。PMU 尚不能把全部额外周期精确分摊给错分支，需结合剩余热点和代码对照继续定位。

本轮低频 timing 中，Verilator 的 p3 为 3142/3150 个 step 的最后完成者；GrhSIM 则为 p10 687（21.810%）、p3 645（20.476%）、p29 598（18.984%）、p18 315（10.000%），并非单一固定分区。两后端 phase 74.806→57.468 µs，winner start 1.248→3.449、winner eval 72.880→53.576、tail 0.678→0.443 µs。GrhSIM 开始偏移仍较大，但本轮整体改善来自求值减少；诊断 probe 的 phase 数值不替代普通运行的全局 eval 和 Host。

本轮结论与下一优先级：

1. 保留函数内优先选择加统一 min128 门槛作为当前有效实验候选。相对 selective GrhSIM 的八对 Host 全胜、配对中位 -9.076%，与 Verilator 的另外八对全胜、配对中位 -14.636%；默认总开关仍关闭，没有更改 Verilator 代码路径或默认行为。
2. 下一轮优先检查 p10/p18 当前瓶颈时的分支热点，独立复查 bool-eager 在当前 min128 线上的覆盖和作用；按纯布尔表达式、条件更新等通用 IR 模式处理，不按分区或变量名放行。旧尝试已有局部改善证据，但未证明与本轮叠加后的整机收益。
3. p29/p28 的下一层问题更偏向工作集中在单一半周期及剩余依赖链，不能只重复优化已下降约 98% 的 p29 错分支。若探索按事件需求求值，须证明消费者、脏值及跨沿复用语义，不可直接跳过非提交沿计算。
4. min128 尚会使长常量选择链局部退化；按候选数据是否常量改进收益筛选有机制依据，但本轮未实现或验证该修正。仍只有一个 workload，128 不代表最优阈值，也不承诺对其他输入或处理器普遍获益。

新增复现产物位于 `priority_mux_min128/verilator_c100000_4pairs/`、`verilator_c100000_repeat_4pairs/`、`verilator_critical_probe/`、`verilator_adjacent_probe/`，汇总为 `verilator_paired_results.json`、`verilator_probe_results.json`，各阶段顺序与时间为 `verilator_validation.json`。本版相对两种基线共完成 48 次正式 C=100000 与 16 次 C100，全部通过。原始成功样本、旧版退化证据及构建身份均保留。

#### 长常量选择链的收益筛选（2026-10-01，实现检查点）

本轮只修正 min128 对长常量链的误改写，不同时加入 bool-eager、事件需求求值或调整链长门槛。`kMux(cond, on_true, on_false)` 表示条件非零时选择 `on_true`，否则选择 `on_false`。例如 `c2 ? 7 : (c1 ? 3 : fallback)` 的候选数据是常数 7 和 3，即使兜底 `fallback` 随输入变化，连续分支也没有大量候选数据加载可省；保留原有 select 表达式，让后端编译器采用条件移动等生成方式。相反 `c2 ? data2 : (c1 ? data1 : fallback)` 仍按既有动态链规则处理。

实现从 IR 识别已知标量常量，并沿同一纯 compute supernode 内的等宽单输入 `kAssign` 追踪常量别名。除最内层兜底外，候选值全部为常量时拒绝优先分支展开；最内层任一输入都可作为兜底，因此支持 true/false 及混合方向。识别采用既有常量解析 API，不匹配 part、模块、信号名、常量值或生成源码字符串。混合常量/动态候选的链不在这次拒绝规则内。被拒绝链的中间 mux 不吸收，仍走原有生成、变化检测与下游激活；记住已拒绝的单消费者链，避免对每个后缀重复遍历。

扩展专项测试已通过（Clang23/O3，93.63 s）。11 种模式增加 609 级常量链、1/7/8/9/16/64 bit 数据、动态和常量兜底、两层赋值别名、true/false/混合方向、常量中夹有动态数据等场景。每种模式两次 init、每次 1300 组全零/全真/逐位命中/随机输入、每组两次 eval；仍逐项对照独立顺序计算。即使 609 级常量链超过 521 门槛，只要动态链未匹配，启用后的生成文件仍与默认逐字节一致。

完整香山实验使用 `build/repcut_grhsim_20260925/priority_mux_constant_filter/`。普通 A/B 基线固定为上一版 `priority_mux_min128`，不能把和更老 selective 线的差异全算成本次收益。条件 PMU 预先固定上一版独立 timing 的 `candidate_labels`，其中 p21 为 19 个唯一步数；同时报告全程均值和新标签，避免以重新挑选瓶颈步数制造收益。整机生成、全部源码/对象不变性检查及 C=100000 交错复测接续执行，当前仅确认专项正确性，不预先宣称 walltime 改善。

在本轮性能测量之前进一步固定覆盖检查：对全部 32 个分区均报告每次运行的全部 1575 个采样 step，以及由上一轮 min128 两次 timing 的分区 eval 均值独立选出的最慢 10%（158 个 step）。慢样本按历史耗时排序，相同耗时按步号排序；不根据本轮候选耗时重新选择。`constant_probe_report.py` 汇总普通计时、当前 eval 的 PMU 及当前加下一次 eval 的 PMU；原固定瓶颈标签的 19 个 p21 step 仍是独立的一组，不和全样本或慢样本混算。作用域审计则逐文件比较 selective、min128、常量筛选三版，并逐对象验证未改动的动态链保留 min128 机器码、撤销改写的常量链恢复 selective 机器码。

完整构建及作用域审计已通过。生成 1998.624 s，其中 JSON 读取 1100.369 s；Clang23/O3、32 路模型编译 225.827 s，harness 构建驱动 3.691 s。撤销 32 条常量链、8520 个 mux 的优先分支展开，长度为 130/162/164/609 各 8 条；保留 96 条动态链、49344 个 mux，长度为 511×64、520×32。相对 min128，只改变 p4/p21/p30 的 4/6/5 份 compute 源码，15 份源码及对象均逐字节恢复 selective；其余 7439/7454 个对象与 min128 一致，其中包含 p15/p28/p29 的全部 19 份动态链优化对象。全部头文件、状态、commit、eval、wrapper 和 Makefile 均未改变。分区名称仅用于报告匹配结果，不参与生成规则。

p21/b93 的静态 text 为 38632→33287 B、条件跳转 1842→19、条件移动 1→1825；p21/b136 为跳转 147→17、条件移动 52→181。p4/b66 的跳转 333→16，p30/b59 为 334→16。以上来自完整对象反汇编及三版 hash 审计，不能直接换算成动态执行时间；后续 PMU 核实这些条件移动在固定步号上的收益。产物为 `constant_scope.json`、`source_summary.json`、`static_summary.json` 和 `build_times.json`。

#### 常量筛选的完整运行结果与收益边界

node030 CPU96--127、NUMA1、关闭 ASLR、N=K=32、all-spin、Clang23/O3、CoreMark/NEMU 与前节相同。先完成两轮各四对 C=100000；因首轮 Host 仅改善约 0.46%，在余下测量完成前确定再追加两轮各四对，检查小幅收益的可重复性。32 次普通正式运行、8 次 timing/PMU 正式运行及 12 次 C100 均通过，正式签名为 pc `0x80000c0c`、instructions 240349、cycles 99996、guest_cycles 100001、steps 200102。保留全部成功样本，无自身编译重叠，不按事后耗时或负载删样。

普通对照的唯一基线是冻结的 min128。以下秒数/均值列分别取 16 次运行中位数；变化列先对每对计算 `100 * (candidate / baseline - 1)` 再取中位数，不用表中两个独立中位数相除。四轮 Host 配对中位按执行顺序为 -0.455%、-0.419%、-0.649%、-0.711%。

| 普通运行指标 | min128 | 常量筛选 | 配对变化 |
| --- | ---: | ---: | ---: |
| Host s | 17.7920 | 17.6990 | -0.486% |
| process wall s | 17.8300 | 17.7300 | -0.505% |
| 全局 eval µs/step | 58.7590 | 58.4330 | -0.498% |
| 全局 update µs/step | 24.3950 | 24.4100 | -0.076% |
| p21 eval µs/step | 18.8120 | 18.6295 | -0.818% |
| p4 eval µs/step | 3.5435 | 3.5220 | -0.495% |
| p30 eval µs/step | 5.9975 | 5.9425 | -1.027% |
| p15 eval µs/step | 18.6195 | 18.5300 | -0.521% |
| p28 eval µs/step | 17.5395 | 17.4530 | -0.479% |
| p29 eval µs/step | 19.1285 | 19.1485 | +0.107% |

Host 和 process wall 都是 13/16 对更快、1 对按记录精度持平、2 对略慢，不能称为全胜。p21 是 15/16 对更快。update 的对象未改变，表中独立中位数略增与配对中位略减并不矛盾，也没有证据认为本项优化了 update。p15/p28/p29 的全部优化对象与 min128 相同，残余计时差异不能归为这些分区被再次改写；最终链接布局、并行执行条件与缓存影响尚未分别隔离。本轮支持小幅整机改善，不将约 0.5% 宣称为跨 workload/处理器的普遍收益。

固定上一版独立 timing 的 19 个 p21 瓶颈步号，每版两次 PMU 运行。全部 32 个线程、全部计数样本的 running/enabled=1.0，没有 PMU 复用缩放。下表是这些相同步号的条件均值，不是全程平均，也不是重新从候选 PMU 耗时里选极值。

| p21 固定瓶颈组指标 | min128 | 常量筛选 | 变化 |
| --- | ---: | ---: | ---: |
| 普通 timing 当前 eval µs | 43.756 | 38.101 | -12.924% |
| PMU 当前 eval µs | 44.579 | 41.653 | -6.565% |
| PMU 当前 instructions | 258361.0 | 268873.3 | +4.069% |
| PMU 当前 branch misses | 881.0 | 215.4 | -75.550% |
| PMU 当前 IPC | 1.597 | 1.793 | +12.298% |
| PMU 当前加下一次 eval µs | 58.943 | 55.077 | -6.558% |
| 两次合计 instructions | 328439.0 | 338951.6 | +3.201% |
| 两次合计 branch misses | 1106.8 | 346.5 | -68.692% |
| 两次合计 IPC | 1.532 | 1.703 | +11.140% |

当前 eval 的有效频率为 3.630→3.600 GHz，两次合计为 3.637→3.614 GHz，新版没有靠更高频率获益。两次独立 PMU 运行的当前 eval 分别为 46.076→43.214、43.083→40.091 µs，两次都改善；相邻两沿合计也改善，不能解释为工作移到下一沿。核心机制是用少量额外指令换取更少错分支、更高执行效率，而不是减少了指令数量。普通 timing 和 PMU wrapper 的布局、计数边界及扰动不同，因此两种时间改善不强行合并，也不把错分支数乘固定惩罚当成精确周期归因。

扩大覆盖后收益明显小于这 19 个瓶颈样本。预先声明的 p21 全部 1575 step/run，普通 timing 当前 eval 18.695→18.356 µs（-1.816%），PMU 当前 19.340→19.283 µs（-0.293%）、两次合计 -0.300%；两次 instructions +2.707%、错分支 -33.378%。历史最慢 10% 的 158 step/run，普通 timing 当前 41.953→40.273 µs（-4.004%），PMU 当前仅 -0.405%、两次合计 57.334→56.681 µs（-1.139%）；两次 instructions +3.381%、错分支 -47.717%、IPC +4.861%。这些较弱结果同样保留，说明常量链回退修正主要帮助原先高错分支的一部分条件，未普遍消除 p21 的依赖链或其他执行开销。

p4/p30 也被通用规则命中，但在全部采样步中，PMU 当前 instructions 分别仅变 +0.000017%/+0.001123%、branches -0.000057%/+0.013234%。p4 当前约 -0.100%、两次约 +0.005%；p30 当前约 -0.350%、两次约 -0.569%。普通 timing 中 p30 反而 +0.898%，历史最慢组 +1.983%，因此不将它普通全程约 -1% 的变化解释成已被 PMU 证明的稳定局部收益。这些分区的静态跳转减少不能代替真实执行覆盖证据。

另用本轮独立 timing 产生新标签时，p21 选中 12 个唯一步号，在另一轮 PMU 当前 -5.639%、两次 -4.900%；但 timing 的留一轮交叉选样为 +0.389%，并非所有标签口径都同幅改善。当前采样中 p21 最后完成次数仅 27→24/3150（0.857%→0.762%），p4/p30 为零。新版主要 winner 仍是 p10 708、p29 649、p3 617、p18 296；这四者合计 2270/3150，未由常量链筛选消除。探针 phase 为 57.992→57.405 µs，不能替代普通版本的 Host/walltime 结果，也不能把其全部变化归为 p21。原固定 p29 两次 PMU 为 62.929→63.974 µs（+1.660%），指令/branches 几乎完全相同，而普通 timing 当前为 -1.112%，进一步提示链接布局及探针扰动对百分点级差异的影响。

默认完整 emitter 测试 308.34 s、开启选项及当前有效组合的完整测试 307.57 s 均通过；Verilator/GrhSIM RepCut package 测试分别为 0.63/43.94 s。三版作用域检查与生成器身份检查均通过。候选 ELF SHA-256 为 `70797802c5b9f898a5692e29b076414e2ad9b3737f2d32c9721789673c51cfe3`，min128 仍为 `779b4a73856019f71cb6f50de07a4726806ba51c09e21d58a7978e69d25ef741`，所有运行前后身份一致。每个诊断 archive 仅替换两个 wrapper 对象，其余 7452 个 member payload 与对应普通版相同。

本轮结论：保留“已知常量候选链不作优先分支展开”作为 min128 的通用修正；无需分区名单，也未牺牲此前动态链生成。它修复了已验证的局部错分支退化，16 对普通运行支持约 0.5% 的小幅 walltime 改善，但不是对长常量解码器本身的全新算法优化。总开关仍默认关闭，Verilator 路径和默认行为不变。进一步压缩常量选择逻辑需要另外证明条件互斥、优先级或相同常量分组的合法性，不能直接把优先 mux 改成 OR/table；当前主要剩余瓶颈仍应回到 p10/p18 的条件执行热点等证据驱动方向。

完整复现目录仍为 `priority_mux_constant_filter/`：四轮普通运行是 `c100000_4pairs/`、`c100000_repeat_4pairs/`、`c100000_confirm_4pairs/`、`c100000_confirm_repeat_4pairs/`；汇总 `paired_results.json`，诊断为 `critical_probe/`、`adjacent_probe/`、`probe_results.json` 与 `constant_probe_results.json`。顺序、耗时与命令保存在 `experiment_stages.json`、`validation.json`、`confirmation_stages.json`；同级 `priority_mux_chains/constant_experiment.py` 和 `constant_finalize.py` 执行完整流程，没有人工挑选分区或成功样本。

最终测试补充：性能测量全部结束后，仅重新编译专项测试程序，加入按具体结果 ValueId 检查的分类断言，确认每条常量链都不生成 `priority_mux` 局部变量、含动态候选的混合链在满足门槛时仍生成。11 模式完整专项再次通过（93.75 s），生成器和已测仿真二进制未改变；日志为 `test-rebuild-final.log`、`test-priority-mux-final.log`。本轮实现、完整生成、功能验证、16 对普通复测和条件归因均已完成。

### 7.23 长常量选择链的优先位图生成（2026-10-01）

#### 实现与正确性检查点

本轮基线固定为上一节已完成的 `priority_mux_constant_filter`，不再使用退化的 min128 作为收益基准。目标是在保持优先级的前提下缩短常量链的选择依赖，而不仅是避免逐候选分支。实验选项为 `priority_mux_constant_bitmaps` / `WOLVRIX_GRHSIM_PRIORITY_MUX_CONSTANT_BITMAPS`，默认关闭，只有 `priority_mux_chains` 总开关开启时生效；共用最小链长门槛，本次保持 128。规则仍从 IR 识别纯 compute supernode 内的等宽、单消费者、非物化中间 mux 和已知常量，不使用模块名、分区名、信号名或常量数值名单。

将链按从高到低的优先级分为最多 64 项一组。每个条件先归一化为 bool，原来取 false 分支的候选使用逻辑非，然后将第 i 个候选条件放在 uint64 位图的 bit i。顺序检查各组；第一个非零组用 `ctz`（从低位起数连续零的数量）定位该组优先级最高的命中项，再从编译期常量数组读取结果。只有非零位图才调用 `ctz`，尾组未使用的高位始终为零，全不命中时使用原兜底。最内层动态候选必要时通过交换两侧并取反条件变为兜底。多条件同时成立时仍选原链最高优先级项，不假设条件互斥。

例如 `c2 ? 7 : (c1 ? 3 : fallback)` 生成 `mask = bool(c2) | (uint64_t(bool(c1)) << 1)`；mask 非零时读取 `{7, 3}[ctz(mask)]`，否则取 fallback。c2/c1 同时为真时 mask=3、ctz=0，结果仍为 7。因此本方案不是直接把候选数据 OR 起来，也不是根据指令编码直接查表；它只压缩优先选择本身，不省略仍然被其他消费者需要的条件计算。

18 模式专项已在 node030 CPU96--127、Clang23/O3 下通过（156.56 s）。20 个测试链覆盖 609 级、63/64/65/128 项边界、1/7/8/9/16/32/64 bit 输出、64 bit 非零条件、全真/全假/逐位唯一命中/逐位唯一不命中/随机输入、两次 init 和重复 eval、true/false/混合方向、常量赋值别名、动态及常量兜底、动态候选混合链，以及拆分 helper、局部 use-order、环境变量与显式属性优先级。默认、总开关关闭和不匹配门槛的生成不变性检查通过。

整机实验目录预定为 `build/repcut_grhsim_20260925/priority_mux_constant_bitmaps/`，驱动是同级 `priority_mux_chains/bitmap_experiment.py`。保持原分区/框架/编译选项，先全量生成和编译、全包源码与对象审计、完整 emitter/package 测试，再执行两轮各四对 C=100000 AB/BA，之后构建 timing/PMU wrapper 并各跑两对，避免自身编译与正式性能测量重叠。条件标签固定使用常量筛选版既有独立 timing 的瓶颈步号及最慢 10% 步号，同时报告全部采样，不根据本轮候选耗时挑样。当前只确认上述实现和专项正确性，不预报整机收益。

专项覆盖补充：在不改变生成器和整机实验选项的情况下，进一步混用 1 bit/64 bit 条件，增加混合方向链的全不命中状态及每一优先级位置的唯一命中，每次 init 扩展为 2200 组输入。18 模式复测通过（184.629 s），日志和覆盖参数在 `test-priority-mux-exhaustive.log/json`。先前全 64 bit 条件版本通过 GCC/UBSan（18.101 s）；增强版本通过 GCC/ASan+UBSan（29.951 s），记录为 `test-bitmap-ubsan.json`、`test-bitmap-sanitized.json`，这些验证耗时不作为仿真性能数据。

冻结源码的常量分布检查：130 项链有 45 个不同输出，609 项链有 162 个不同输出，162/164 项链分别有 162/164 个不同输出，每类各 8 条；四类都没有相邻相同输出。因此只合并相邻同值不能进一步缩短本次的链，合并非相邻同值则仍需保留中间候选的优先级。位图方案不依赖重复常量，也不将静态链长缩短等同于动态指令数或 walltime 必然下降。

#### 完整生成与编译检查点

全量 IR 读取及生成 1614.911 s，Clang23/O3 `make -j32` 模型编译 224.881 s，复用既有 harness 对象后的驱动构建及链接 3.750 s。这些是本次实际 walltime，不与上轮生成时间直接作优化幅度比较。生成器源码、核心库和 Python binding 的 SHA-256 在全流程前后保持一致。候选 ELF SHA-256 为 `cbdbefe2c9dfdf45247dced2e85aa4578b6186b2a3ba6002d614cd5c5517faae`，对照继续使用常量筛选版 `70797802c5b9f898a5692e29b076414e2ad9b3737f2d32c9721789673c51cfe3`。

规则命中 32 条链、8520 个 mux，分别为 p21 的 16 条、p4 的 6 条、p30 的 10 条，仅 15 个 compute 源文件变化；其他 7538 个源码/头文件/Makefile 完全相同，7439 个未变更对象逐字节一致。命中源文件合计 4,135,647→3,459,307 bytes（-16.354%），但整机 `size` 的 text 合计 106,816,248→106,786,624 bytes（-0.028%），源码缩小不能代替机器码或运行时间收益。

| 对象 | 函数 text bytes | 静态指令条数 | 条件跳转 | cmov | 位扫描 |
| --- | ---: | ---: | ---: | ---: | ---: |
| p21/b93 | 33,287→32,094 | 6180→6723 | 19→48 | 1825→1 | 0→30 |
| p21/b136 | 10,265→10,548 | 1926→2062 | 17→20 | 181→51 | 0→3 |
| p4/b66 | 11,053→6826 | 2495→1551 | 16→22 | 667→343 | 0→6 |
| p30/b59 | 11,102→6800 | 2485→1549 | 16→22 | 739→415 | 0→6 |

表内是整个对象定义的函数 text 和反汇编静态计数，不含常量表，不是动态执行计数；整机 `size` text 口径则还包含只读常量等内容。p21/b93 的三条 609 级链已消除串联 cmov，但位图打包使静态指令数增加，是否缩短真实依赖路径要由后续 timing/PMU 和无探针 Host 运行判断。完整作用域证据见 `source_summary.json`、`static_summary.json`、`build_times.json` 与 `emitter_identity.json`。

构建口径勘误：上文“复用既有 harness 对象”表述不准确，驱动实际重新编译了 40 个 harness 对象再链接，3.750 s 是这一步的总耗时。与基线逐对象比较，39 个完全相同，`common.o` 仅四个字节不同，均位于 `__TIME__` 生成的启动提示字符串 `14:39:46`→`16:26:06`，函数机器码和重定位不变；仿真执行逻辑未额外改变。

#### C=100000 交错复测与条件归因

完整流程已完成。node030 CPU96--127、NUMA1、ASLR off、N=K=32、all-spin、Clang23/O3 保持不变；基线是上一节的常量筛选版，候选只增加常量优先位图。先执行两轮各 4 对 AB/BA，再构建并运行 timing/相邻步 PMU 各 2 对，最后补两轮各 4 对普通确认。没有本任务编译与正式测量重叠，没有外部负载门槛、异常值剔除或挑选获胜样本；32 次普通正式运行、8 次诊断正式运行及 12 次 C100 smoke 全部通过。所有 C100000 都启用 Difftest，签名一致：PC `0x80000c0c`、instructions=240349、cycles=99996、guest_cycles=100001、steps=200102。

| 普通版指标 | 基线中位 | 位图版中位 | 16 对配对变化中位 | 候选更快 |
| --- | ---: | ---: | ---: | ---: |
| Host | 17.7285 s | 17.6405 s | -0.546% | 14/16 |
| 最终 walltime | 17.7650 s | 17.6750 s | -0.508% | 14/16 |
| 全局 eval 阶段/step | 58.5530 us | 57.9650 us | -0.870% | 16/16 |
| 全局 update 阶段/step | 24.2750 us | 24.4065 us | +0.561% | 3/16 |
| p21 eval/step | 18.6405 us | 18.4695 us | -0.952% | 15/16 |
| p4 eval/step | 3.5305 us | 3.5685 us | +1.090% | 3/16 |
| p30 eval/step | 5.9055 us | 5.9170 us | +0.025% | 8/16 |

“配对变化中位”是先对每一对计算 `100*(candidate_i/baseline_i-1)` 再取中位，不是表内两列独立中位数之比。例如 Host 两列之比约 -0.496%，与配对值 -0.546% 不同。按执行时间顺序，四轮 Host 配对变化中位为 -0.479%、-0.575%、-0.584%、-0.413%；walltime 分别 -0.481%、-0.562%、-0.566%、-0.395%。支持这组固定二进制约 0.5% 的小幅收益，不支持宣称数量级或数个百分点的整机提升。

条件分析仍固定使用基线上一轮独立 timing 选出的标签。每次 timing 包含 1575 个采样步，最慢 10% 为 158 个唯一步号，p21 瓶颈标签为 12 个唯一步号；两个变体均在相同步号比较，不根据本轮候选速度挑样。每个诊断 archive 仅替换两个 wrapper 对象，其余 7452 个 member payload 与对应普通版一致。全部 PMU 事件组 running/enabled=1，没有事件复用；PMU 读计数在 eval 计时边界外，但系统调用、缓存和链接布局仍可能扰动后续执行，不能把探针时间当作无探针 walltime。

| p21 样本口径 | 轻量 timing eval | 相邻步 PMU 中的当前 eval | PMU 当前 instructions | PMU 当前 branch misses |
| --- | ---: | ---: | ---: | ---: |
| 全部 1575 步/次 | 18.975→18.574 us（-2.112%） | 19.084→19.194 us（+0.574%） | 121755→118895（-2.349%） | 121.34→134.74（+11.046%） |
| 历史最慢 158 步/次 | 42.112→40.227 us（-4.477%） | 41.684→41.393 us（-0.697%） | 297939→286795（-3.740%） | 191.90→203.82（+6.212%） |
| 历史瓶颈 12 步/次 | 44.621→41.464 us（-7.074%） | 41.345→42.685 us（+3.242%） | 270081→259954（-3.750%） | 249.29→284.67（+14.190%） |

因此应区分三个结论：常量选择链的机器码形态确实改变；动态指令减少也在独立 PMU 中得到验证；但局部耗时改善幅度对探针敏感，不能把 timing 的 -7.074% 作为稳定局部收益。全样本 PMU IPC 1.758→1.706（-2.942%），有效频率 3.629→3.630 GHz 基本不变；历史瓶颈组 IPC 1.811→1.679（-7.324%）。位图并非消除了所有成本：零散 bool 的加载、移位和 OR 打包仍存在，分组跳转和常量表读取还引入额外工作。反汇编中每组内部仍有串行 OR 累积，没有证据说明残余瓶颈已完全解决。PMU 当前加下一次 eval 的全样本 +0.486%、历史最慢组 +0.181%、历史瓶颈组 +3.024%，也不支持简单用“工作转移到相邻沿”解释差异。

p4/p30 全样本 PMU 当前 instructions 分别仅变化 -0.000011%/-0.000033%，缺乏命中优化在本次采样中省下动态工作的证据；不能从它们的静态代码缩小推断仿真收益。p4 普通 eval 的约 +1% 和 p30 的基本不变都保留在汇总，不按分区名单排除。另一方面，未改对象的 p3 普通 eval 也下降 -2.219%，而其全样本 PMU instructions 仅 +0.000011%；链接布局、缓存/预测状态、线程相位和运行波动可能贡献这些间接变化，本轮没有把它们分离。因此整机约 0.5% 是这组二进制的 A/B 结果，不能全部归因于 p21 的选择依赖改善。

当前 timing 中 p21 最后完成次数为 17→17/3150（均 0.540%），p4/p30 均为零；位图版 p3/p10/p18/p29 分别为 628/711/306/708，合计 2353/3150（74.698%）。全局采样 phase 为 58.275→58.704 us，与普通全程 eval 变化方向不同，进一步说明不能混用两个指标。本次解决了命中链“仍串联数百级 cmov”的代码生成问题，但没有使它成为新的主要 walltime 优化来源，也没有消除所有长 mux 或条件生产成本。

默认完整 emitter 测试 308.528 s、开启选项及当前组合完整测试 307.922 s；Verilator/GrhSIM RepCut package 测试 0.64/43.88 s，均通过。候选及基线二进制在所有运行前后身份一致。新增选项和优先链总开关均继续默认关闭，Verilator 生成路径不变，不在本轮擅自提交或提升为默认。

数据保存在 `priority_mux_constant_bitmaps/`：四轮普通结果为 `c100000_4pairs/`、`c100000_repeat_4pairs/`、`c100000_confirm_4pairs/`、`c100000_confirm_repeat_4pairs/`；最终汇总是 `paired_results.json`，条件归因为 `probe_results.json`、`constant_probe_results.json`，原始 TSV 位于 `critical_probe/`、`adjacent_probe/`。执行阶段为 `experiment_stages.json`、`validation.json`、`confirmation_stages.json`；复现驱动是同级 `priority_mux_chains/bitmap_experiment.py` 与 `bitmap_finalize.py`。后续若继续本方向，应优先验证位图组内打包依赖和分组命中分布；若以 walltime 为唯一目标，主要资源应转向仍占关键路径多数的 p3/p10/p18/p29，并继续用通用 IR 模式实现，而非增加手选分区名单。

### 7.24 在最新有效线上复查 bool-eager（2026-10-01）

#### 基线、问题与实验口径

本轮先复用既有 `bool_eager_logic`，不扩大识别规则、不修改生产默认值。基线固定为 §7.23 完整生成的 `priority_mux_constant_bitmaps`，候选 `priority_mux_bool_eager` 只额外设置 `WOLVRIX_GRHSIM_BOOL_EAGER_LOGIC=1`，其余 packed-array late-index、选择性 local compute use-order、priority mux 最小链长 128、常量位图选项保持相同。全图统一启用，不按 p10/p18 等分区名称选择是否优化。继续 node030 CPU96--127、NUMA1、N=K=32、all-spin、Clang23/O3、ASLR off、C=100000。

现有规则仅将两个已求值、无副作用的一位 bool 槽或局部临时量的 `&&/||` 改为 bool `&/|`。这使编译器有机会减少短路跳转，但不保证每处都生成无分支机器码；不处理 mux，也不处理 commit 的状态变化判断。此前老线上 p10 条件 eval 改善约 13.8%、错分支减少约 46.3%，p18 却未改善。长选择链优化已经改变全局关键路径，因此必须在最新版本重新测试，不能把旧局部收益直接叠加到最新 walltime。此前 p10/p18 两沿比 Verilator 慢约 28%/35% 的数据来自 min128 阶段，也不是最新位图版的重新测量。

本轮全量重新生成和编译，检查所有生成源码、头文件和对象。源码作用域审计对候选精确逆变换 bool 表达式后要求与基线逐字节相同，拒绝夹带调度、state、commit、wrapper 或其他变化。完整 emitter 测试新增环境隔离：只在检查 bool-eager 的默认/显式关闭/显式开启 fixture 时暂时清理外部 bool 开关，结束后恢复，其他 fixture 仍使用本次有效选项组合。此调整不改变生成器或仿真代码。

预先固定四轮各 4 对普通 AB/BA，不按胜负停止或剔除样本；中间单独运行 timing 和相邻步 PMU 各 2 对。瓶颈步号和各分区最慢 10% 步号使用上一轮位图版的独立 timing 选取，同时保留全样本与两沿合计。探针不用于替代最终 walltime。待确认 bool-eager 是否真正改善 p10 及全局关键路径后，再按实际残余证据分析 p18 commit/state-change 分支；p29 的单沿集中与按需求值属于另一项风险更高的改变，暂不混入本轮。驱动为 `build/repcut_grhsim_20260925/priority_mux_chains/bool_experiment.py`。当前处于完整生成阶段，尚无本轮性能结论。

作用域审计补充：既有 `isCheapScalarInlineExpr` 还使用 1024 字符门槛，bool 显式转换使表达式变长，可能改变单消费者 bool 临时量的拆分位置。对逆变换后不再逐字节一致的 compute 文件，使用隔离安装的 tree-sitter C++ 解析器核对表达式树：只允许纯 bool、恰有一个消费者且作用域不变的局部临时量替换，去除冗余 bool 转换后要求其余语法树相同。先在旧 bool-eager 产物验证了 1369 个直接逆变换文件和 83 个表达式树文件。此处是源码作用域检查，不代替功能回归，也不宣称 C++ 编译后的影响仅限分支指令。

诊断补充计划：16 对普通复测完成后，在同一独立历史标签下运行候选与冻结 Verilator/O3 的 timing、相邻步 PMU 各两对，更新两后端条件差距；再对位图基线、bool 候选、Verilator 按 ABC/CBA 顺序刷新全程 branch-misses 与 cycles 函数采样。全程热点不能当成瓶颈步的耗时比例，且所有诊断运行均与普通性能样本分开，见驱动 `bool_diagnostics.py`、`bool_profile.py`。

#### 完整生成与机器码检查点

全图读取及生成完成，实际 walltime 922.646 s，其中 IR 读取 308.048 s；Clang23/O3 模型 `make -j32` 227.775 s，40 个 harness 对象重新编译并链接 3.691 s。生成器源码、核心库及 Python binding 哈希与 §7.23 完全相同，候选 ELF 为 `ed490c3dbe795fd64df876de8e91685ff0868b2b6604059d263110efeee38e99`。构建耗时只报告本轮实测，不将 NFS/cache 窗口差异误认为 bool-eager 的生成加速。

全部 32 分区共 95,639 个 eager 表达式，1452 个 compute 源文件变化，6101 个其他源码/头文件/Makefile 一致；其中 1369 个文件直接逆变换后与基线逐字节一致，83 个文件通过单消费者 bool 临时量的语法树审计，共涉及 1542 个声明名的集合差异。编译后 6276 个模型及框架对象逐字节一致，1178 个变化对象全部来自上述 compute 文件；另有 274 个源码变化文件编译后对象未变。所有 commit、state、外层 eval 和通信对象不变。

| 对象 | 定义函数 text bytes | 静态指令 | 条件跳转 |
| --- | ---: | ---: | ---: |
| p10 compute b145 | 23801→18180 | 5150→3737 | 368→91 |
| p10 compute b146 | 38737→27868 | 8805→5640 | 719→36 |
| p10 compute b147 | 28090→24110 | 6095→4730 | 396→36 |
| p18 compute b197 | 8525→8525 | 1650→1650 | 148→148 |
| p18 commit c256 | 367595→367595 | 56312→56312 | 12768→12768 |

p10 命中 4865 个表达式、p18 命中 472 个，均无临时量拆分变化；p10 commit c173/c174/c175 和 p18 compute b197/b200、commit c255/c256 对象完全一致。整机 `size` text 106,786,624→106,257,000 bytes（约 -0.496%）。静态跳转数不等于运行时错分支数；源码覆盖广也不能直接推出动态收益。完整默认和有效组合回归、普通与诊断运行接续进行。

#### 16 对普通 AB/BA 的收益检查点

四轮各 4 对 C=100000 已全部完成，32 次正式运行全部启用 Difftest 并通过，功能签名均为 PC `0x80000c0c`、instructions=240349、cycles=99996、guest_cycles=100001、steps=200102。基线与候选仍为上文两个冻结二进制；所有成功样本纳入，无核空闲筛选、计时离群值剔除或自身编译重叠。默认完整 emitter 测试 308.241 s、有效选项组合完整测试 307.358 s、两后端 package 测试合计 44.475 s，均通过。

| 普通版指标 | 位图基线中位 | 叠加 bool-eager 中位 | 16 对配对变化中位 | 候选更快 |
| --- | ---: | ---: | ---: | ---: |
| Host | 17.6645 s | 17.3695 s | -1.489% | 16/16 |
| 最终 walltime | 17.7000 s | 17.4050 s | -1.494% | 16/16 |
| 全局 eval/step | 58.0025 us | 56.7140 us | -2.257% | 16/16 |
| 全局 update/step | 24.5025 us | 24.3910 us | -0.068% | 9/16 |
| p10 eval/step | 36.1310 us | 32.7835 us | -9.231% | 16/16 |
| p18 eval/step | 32.1710 us | 32.2135 us | +0.201% | 7/16 |
| p28 eval/step | 17.4150 us | 15.8115 us | -9.234% | 16/16 |
| p29 eval/step | 18.9705 us | 18.5590 us | -1.988% | 16/16 |
| p3 eval/step | 44.1085 us | 44.7625 us | +1.368% | 4/16 |

配对变化是先计算每对 `100*(candidate_i/baseline_i-1)` 再取中位，不是前两列中位数的比值。按执行先后，四轮 walltime 配对变化中位为 -2.193%、-1.022%、-1.499%、-1.688%，每轮均 4/4 更快。结果支持本次固定配置约 1.5% 的整机收益，不能将 p10 局部改善当作整机改善，也没有证据称 p18 已获益。p3 的退化同样保留在表内，不按分区筛选结果；最终以全图 walltime 判断。

独立历史瓶颈标签下，p10 轻量 timing 为 56.766→48.906 us（-13.847%），相邻步 PMU 的当前 eval 为 57.943→49.476 us（-14.612%）；动态指令仅 -1.486%，分支预测失败 1446.63→842.14（-41.787%），IPC 1.555→1.789，有效频率 3.587→3.598 GHz。当前加下一次 eval 为 95.929→81.427 us（-15.117%），支持主要来自短路分支效率改善，而非转移到下一沿。p28 对应当前 PMU eval -9.756%、指令 -8.517%，错分支仅约 28→27 次，其主要机制是动态工作减少，不能套用 p10 的错分支解释。

p18 则出现轻量 timing +1.412%、PMU timing -2.967% 的相反方向；指令 -0.040%、分支 -0.028%、错分支 -0.767%，结合普通版约 +0.2%，不认定为稳定局部收益。每次 timing 为 1575 个步号，固定 p10/p18/p28 标签分别为 354/151/39 个；两个变体比较相同历史步号，PMU 事件组 running/enabled 均为 1。下一段补充新 Verilator 对照、全程函数采样和 compute/commit 拆分，以定位 bool-eager 未覆盖的剩余成本。

#### 更新与 Verilator 的条件对照

普通复测结束后，冻结 Verilator/O3 与 bool-eager 候选在同一机器依次完成 timing、相邻步 PMU 各两对 AB/BA。继续使用上一轮位图版选定的历史瓶颈步号，以下不是各后端各自挑出的最差样本，也不是整机 walltime。两沿指选定 step 的 normal eval 加紧接着下一 step 的 normal eval；计数器 running/enabled 均为 1，无事件复用。

| 分区 | 轻量 timing：Verilator→GrhSIM | PMU 两沿 eval：Verilator→GrhSIM | 两沿耗时变化 | 两沿指令变化 | 两沿错分支变化 |
| --- | ---: | ---: | ---: | ---: | ---: |
| p3 | 76.053→44.225 us | 150.915→86.906 us | -42.414% | -25.750% | -95.374% |
| p6 | 34.998→56.168 us | 96.331→93.393 us | -3.050% | -29.196% | +471.798% |
| p10 | 52.841→48.867 us | 73.513→81.636 us | +11.050% | -1.903% | +86.492% |
| p18 | 46.942→52.053 us | 70.457→91.733 us | +30.198% | -5.200% | +146.833% |
| p28 | 20.748→42.510 us | 49.642→43.896 us | -11.575% | -31.371% | -45.072% |
| p29 | 27.855→61.640 us | 64.724→63.045 us | -2.595% | -29.699% | +86.918% |

p10 的所选瓶颈沿已经快于 Verilator，但下一沿为 32.060 us，对照为 18.689 us，因此两沿仍慢约 11%。不能沿用旧 min128 阶段“仍慢约 28%”来描述本轮。p18 两沿 IPC 为 2.273→1.659（-27.007%），有效频率 3.595→3.586 GHz；指令反而少 5.2%，耗时多 30.2%，支持继续检查分支、依赖及活动传播的执行效率，不支持归因于频率明显下降或代码工作量必然更多。

p29 的 PMU 两沿分别为 Verilator `28.834 + 35.890 us`、GrhSIM `60.548 + 2.497 us`。总量已略好，但 GrhSIM 的同步屏障仍要等待那个约 60 us 的半周期，另一沿空闲不能抵消它。其当前错分支约 87 次，不能与 p18 的约 1379 次等量看待；百分比增加不等于主要瓶颈。p29 后续方向更像事件需求、共享中间结果及依赖调度，不是继续把旧长选择链的错分支收益再算一遍。

#### p18 残余热点的机制边界

位图基线、bool 候选、Verilator 分别按 ABC/CBA 顺序运行全程 branch-misses 与 cycles 采样，各两次；branch-misses 采样间隔为 20011，cycles 为 399 Hz。按 sample period 加权统计函数，以下分母均为该分区已归属的模型函数样本，不包含 worker 自旋等框架函数，也不是条件瓶颈步的时间比例。

bool 候选 p18 的 `eval_commit_batch_256()` 占该分区错分支样本 25.387%，`c255` 占 3.410%，全部 compute 函数合计占 68.510%；cycles 样本则为 c256 8.026%、全部 commit 9.173%、全部 compute 88.118%。c256 是最大的单函数热点，但分散的 compute 成本合起来大得多。p10 的 commit 占错分支样本 34.747%、cycles 样本 10.850%，说明本轮组合布尔分支改善后，状态提交也成为它值得进一步检查的一部分。

另外制作低频阶段探针，统一对 32 个分区在每轮固定点求值中累计 compute/commit 时间；每 127 step 采样，沿用同一组历史标签，两对 AB/BA。每个 archive 仅改变 32 个外层 eval 对象和两个 wrapper 对象，其余 7420 个 member payload 完全一致，所有 compute/commit batch 机器码原样保留。

| 候选固定瓶颈步 | compute | commit | 其他 | 总 eval | 固定点轮数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| p10 | 39.557 us | 7.527 us | 2.064 us | 49.148 us | 1.994 |
| p18 | 41.057 us | 8.506 us | 1.550 us | 51.113 us | 1.993 |
| p29 | 60.112 us | 0.028 us | 1.523 us | 61.663 us | 1.000 |

这里 commit 是模型 `eval()` 内更新寄存器状态并标记 reader 的阶段，不是 RepCut 全局通信 `update`。p18 commit 占固定瓶颈步约 16.641%；全体采样平均 compute/commit/其他为 26.869/2.868/1.454 us，commit 占 9.195%，与全程 cycles 的约 9.2% 一致。计时边界会增加时间读取并改变外层函数布局，不能将阶段探针的基线/候选差值当作普通版收益；例如其 p29 总 eval 59.909→61.663 us，与轻量 timing 和普通版方向不同。本节用它判定阶段量级和轮数，不据此改写前面的 walltime 结论。

生成源码与机器码的具体证据：p18/c256 有 6383 个标量 `state != next_value` 判断，默认已经带 `unlikely`，并非缺少分支提示。典型路径是加载 next、比较 state、条件跳转、写 state、对 `supernode_active_curr_` 做掩码 OR。新采样的 `c256+0x29e07` 附近正是这种比较及两次标记更新；采样存在 skid，只作为代码形态证据，不把该地址的采样精确归到单条比较指令。例子见 `priority_mux_bool_eager/package/grhsim_Gpart_18_model_sched_256.cpp` 第 7525 行起。

冻结 Verilator 对同一 `iqWakeUpBundleDelayed_delayed_REG_7_bits_rfWen` 的 `nba_sequent` 代码直接执行赋值，本段没有逐寄存器变化判断和对应的逐值 reader 激活，见 `clang23_threeway/verilator_o3/package/build/verilated/part_18/VWolviRepCutUnit_part_18___024root__14.cpp` 第 550 行。名称只用于核对等价状态，不能成为优化规则；也不推论 Verilator 全局没有事件检测。GrhSIM 必须维护精确激活以避免漏算，照抄直接赋值但删除激活会破坏行为。

#### 本轮结论与下一步

1. bool-eager 与最新有效线叠加的收益已确认，本次整机 walltime 配对改善约 1.49%，可作为后续探索的固定候选基线。它不是只对手选分区启用；本轮不修改生产默认值、不额外提交，Verilator 路径保持原样。
2. 下一项较小范围的通用候选是标量寄存器提交的变化检测和 reader 标记生成：从 IR 的写者、掩码和实际激活写入数量判断，评估少量标记的精确无分支更新，或同一安全作用域内的标记合并。保留高扇出时的跳过收益、写入顺序、变化检测、固定点和性能计数语义；已有写使能分组及 lockstep 相同状态分组不能当作新方案重复实现。不得按模块、分区、信号或本次采样命中名单筛选。
3. p18 不能只优化 commit：条件 compute 仍约 41 us，占约 80%。下一次应将这部分继续按实际活跃 batch 内的值计算、变化比较和活动标记拆分；先确认通用重复成本，再决定是否减少物化或合并激活，不盲目扩大 bool-eager，也不增加第二套逐值活动元数据。
4. p29 是另一项潜在收益更大、语义风险也更高的工作。候选轻量 timing 的 3150 个采样中，p3/p29/p18/p10 最后完成次数分别为 701/699/468/399，占 22.254%/22.190%/14.857%/12.667%；对照为 619/695/296/723。p10 缓解后 p18 更常进入关键路径，但 p29 并未消失。固定其他线程开始和结束时间、假定某分区 eval 再降 10% 的简单敏感度计算，p29/p3/p18/p10 对平均关键完成时间的减量分别为 1.191/0.810/0.610/0.514 us；这是 `mean(min(0.1*winner_eval, winner_finish-runnerup_finish))`，不是实际加速预测。按需求值须先证明值不会被另一消费者、当前输出或下一轮事件提前使用，不能仅把计算机械挪到另一沿。

全流程完成：32 次普通 C=100000、20 次 wrapper 诊断 C=100000、12 次全程 PMU 采样 C=100000、18 次 C100 smoke 全部通过，正式签名完全一致，输入及二进制身份不变；完整默认/组合 emitter 回归与两后端 package 回归通过。普通汇总为 `priority_mux_bool_eager/paired_results.json`，跨后端为 `verilator_probe_results.json`，阶段为 `phase_results.json`，全量汇总为 `results.json`；全程 profile 原始数据及逐函数/地址计数在 `branch_profile/`、`cycles_profile/`。驱动依次为 `priority_mux_chains/bool_experiment.py`、`bool_diagnostics.py`、`bool_results.py`，本次补充诊断在普通驱动退出后单独启动；`experiment_stages.json` 和 `diagnostic_stages.json` 保留实际执行顺序及耗时。

### 7.25 少量激活写入的标量寄存器提交（2026-10-01）

#### 实现与专项验证检查点

本轮接续上一节提出的小范围 commit 候选，基线固定为已验证的 `priority_mux_bool_eager`，普通 ELF SHA-256 为 `ed490c3dbe795fd64df876de8e91685ff0868b2b6604059d263110efeee38e99`。不同时改动 compute、分区、通信或 p29 求值时机。新实验选项 `commit_scalar_eager_max_activation_writes` / `WOLVRIX_GRHSIM_COMMIT_SCALAR_EAGER_MAX_ACTIVATION_WRITES` 默认 0 关闭，允许 0..3；本次统一对所有 32 分区设为 2。规则不含分区、模块或信号名单，Verilator 路径不变。

在原 event/update guard 内，先按原来的全掩码或部分掩码表达式算出 `next_value`，再保留精确的 `state_changed = (state != next_value)`。符合条件时不再用该布尔值包围整个提交块，而是直接写回标量 state，用 `state_changed` 的全零/全一掩码 OR reader 的 active bit，并将它按位 OR 到 `commit_activated_readers_`。性能计数仍只累计实际变化，不因无效写回而增加。没有变化时，reader active bit 和 commit 累加标记的逻辑值都保持不变；多个写者和部分掩码仍按原顺序执行。这里 commit 是模型内部状态提交，不是 RepCut 的跨分区 update。

门槛复用现有 `estimateConditionalActivationEmitCost`，计算局部/全局目标拆分及连续 active 字节合并后实际需要生成的激活写入次数，不是直接按 reader 数量筛选。只有普通标量寄存器（最多 64 bit）且成本不超过 2 的提交匹配；宽状态、latch、memory、reg-to-mem intent storage、高成本激活及已有 lockstep 状态分组保留原路径。收益假设是用少量无效 store/OR 换取更少的变化分支；并不假定状态经常变化，也不预报会改善 walltime。

新增专项 CTest `emit-grhsim-cpp-commit-scalar-eager` 在 node030 CPU96--127、Clang23/O3 下通过，耗时 105.019 s。12 种模式覆盖默认/关闭、门槛 1/2/3、split-word helper、perf、full-pass、精确 batch bitmap、环境变量与 attribute 优先级，以及关闭旧 unlikely 提示。测试含 1/7/8/16/32/64 bit 标量、130 bit 回退、0/1/2/3/4 次激活写入、部分掩码、禁用及无变化写、同一寄存器多写者；每模式两次 init，各 300 组输入并重复 eval，逐阶段核对输出，perf 模式精确核对 `touchedWriteCount`。非法和溢出选项均要求报错。

全包审计将候选 C++ 用结构化解析器逆变换为旧的变化判断块，并要求与基线逐字节一致；只允许出现声明的状态写回、变化计数、commit 累加和条件掩码激活，不接受任意文本替换或忽略其他变化。专项生成文件上的正例及三个语义变异负例已验证，完整包将继续使用同一检查。模型头文件、compute、外层调度、wrapper 和 Makefile 必须保持一致，编译对象变化也须能追溯到允许改写的 commit 文件。

完整流程驱动为 `build/repcut_grhsim_20260925/priority_mux_chains/commit_experiment.py`，产物目录为同级 `commit_scalar_eager_2/`。先完成默认/开启选项完整回归、两后端 package 回归和全图生成编译，再按预定顺序完成 16 对 C=100000 普通 AB/BA、timing/相邻步 PMU/阶段探针各两对。保持 node030 CPU96--127、NUMA1、N=K=32、all-spin、ASLR off、Clang23/O3；所有功能通过样本纳入，不做核空闲筛选或按胜负提前终止。本轮条件标签使用上一节 bool-eager 的独立 timing 步号，同时报告全样本、历史最慢 10% 和两沿合计。源码、核心库和 binding 的哈希在每个阶段前后冻结核对，正式计时与本任务编译不重叠。当前仅完成实现和专项，不将其表述为已验证性能收益。

#### 完整生成与正确性闭环

本轮全流程已经完成。全图 IR 读取及生成 walltime 909.042 s（其中读取约 300.0 s），Clang23/O3 模型 `make -j32` 228.765 s，40 个 harness 对象重编译及链接 3.885 s。默认完整 emitter 回归 336.041 s、有效选项组合回归 318.497 s、两后端 package 回归合计 44.844 s，全部通过。专项另补 `activity-off/activity-two` 两个模式，总计 14 模式复测通过（117.11 s）：精确核对每个 reader 的动态执行次数、compute/commit batch 次数及固定点轮数，避免只检查最终输出而漏掉多余激活。此补充只改测试，不改冻结的生成器及模型。

规则共命中 239,585 次标量提交，其中实际激活写入成本 0/1/2 的数量分别为 7873/145519/86193，覆盖全部 32 个分区。132 个 commit 源文件通过结构化逆变换后与基线逐字节一致；其他 7421 个源码/头文件/Makefile 不变。编译对象中 132 个变化、7322 个一致，变化对象全部对应这些 commit 源文件。harness 的 39 个对象完全一致，`common.o` 仅 `__TIME__` 启动提示的 5 个字符不同，除此之外逐字节相同。

变化源码合计 245,167,240→287,528,209 bytes（+17.278%），整机 `size` text 则为 106,257,000→103,846,922 bytes（-2.268%）。p10/c173 条件跳转 15726→199，p10/c175 15387→3022，p18/c256 12768→4211；对应定义函数 text 分别为 423783→295843、469397→340758、367595→305387 bytes。源码展开量、机器码体积、静态跳转与动态执行成本不是同一指标，均不能单独替代运行测量。候选普通 ELF SHA-256 为 `ca14c4049a328dd5a6102e13575a500e5abb78d960fe4516743d66fb9d591c26`。

32 次普通 C=100000、12 次 wrapper 诊断 C=100000、8 次全程 PMU 采样 C=100000，以及 14 次 C100 smoke 均通过。所有正式运行启用 Difftest，签名均为 PC `0x80000c0c`、instructions=240349、cycles=99996、guest_cycles=100001、steps=200102。输入、基线/候选二进制及生成器身份前后不变；4 次阶段探针的全部 1575 个采样步、32 分区的固定点轮数向量逐项完全一致。该轮数检查加上专项动态 reader 计数支持精确激活语义，但不代替未覆盖 workload 的进一步验证。

#### 16 对普通运行：小幅正向但不足以确认稳定收益

| 普通版指标 | bool-eager 基线中位 | commit eager=2 中位 | 16 对配对变化中位 | 候选更快 |
| --- | ---: | ---: | ---: | ---: |
| Host | 17.4455 s | 17.3800 s | -0.395% | 10/16 |
| 最终 walltime | 17.4800 s | 17.4050 s | -0.428% | 10/16 |
| 全局 eval/step | 57.0310 us | 56.7665 us | -0.354% | 14/16 |
| 全局 update/step | 24.3920 us | 24.3925 us | +0.306% | 6/16 |
| p3 eval/step | 44.8515 us | 46.1470 us | +2.899% | 0/16 |
| p6 eval/step | 37.9780 us | 36.9930 us | -2.455% | 16/16 |
| p10 eval/step | 32.7035 us | 32.1830 us | -1.860% | 16/16 |
| p18 eval/step | 32.3700 us | 31.3840 us | -3.063% | 16/16 |
| p28 eval/step | 15.8390 us | 15.8865 us | +0.309% | 1/16 |
| p29 eval/step | 18.9785 us | 19.1395 us | +0.833% | 0/16 |

继续按每对 `100*(candidate_i/baseline_i-1)` 后取中位，不把两列独立中位数之比或局部 eval 改善当作最终收益。四轮按执行顺序的 walltime 配对变化中位为 -0.200%、-0.285%、-0.630%、+0.087%，分别 2/4、2/4、4/4、2/4 更快。全部 8 对 AB（先基线后候选）为 -0.771%、7/8 更快；8 对 BA 为 +0.143%、3/8 更快。Host 的对应两种顺序为 -0.773%/+0.172%，全局 update 为 -0.732%/+0.997%。没有删除任何成功样本，也没有为了凑出收益延长到某个获胜时刻。

因此本轮仅报告“观察到约 0.43% 的配对中位 walltime 改善，但对顺序敏感，不能确认稳定整机收益”。p10/p18 局部改善和 p3 退化更一致，值得用于指导通用规则修正；不能据此手选 p10/p18 开启、p3 关闭。生产默认保持 0，后续已验证探索基线仍使用上一节 bool-eager，不将该候选直接叠加为新的默认实验起点。

#### 为什么局部有效而整机收益很小

诊断固定采用上一轮 bool-eager 独立 timing 选出的步号，每次 1575 个采样步；p3/p10/p18 固定瓶颈集合分别为 350/199/237 步，不根据本轮候选速度重选。所有相邻步 PMU 的 running/enabled=1，未复用计数器。下表阶段时间来自独立阶段探针，错分支和指令来自相邻步 PMU，不能将不同探针的绝对时间混加。

| 固定历史瓶颈步 | 轻量 timing eval | compute 阶段 | commit 阶段 | PMU 当前指令 | PMU 当前错分支 |
| --- | ---: | ---: | ---: | ---: | ---: |
| p3 | 44.050→44.727 us（+1.537%） | 36.191→37.623 us | 3.229→4.409 us（+36.543%） | +4.298% | 96.60→79.93（-17.256%） |
| p10 | 53.348→52.759 us（-1.104%） | 41.577→41.884 us | 8.475→7.678 us（-9.406%） | +6.517% | 895.50→551.45（-38.420%） |
| p18 | 52.420→50.203 us（-4.229%） | 41.913→40.635 us | 8.616→7.025 us（-18.461%） | +4.267% | 1367.09→1016.82（-25.621%） |

p10/p18 PMU 当前 eval 为 53.842→52.061 us（-3.309%）、52.130→50.086 us（-3.922%）；当前加下一沿分别 -3.330%/-2.770%，没有证据说明收益只是移到另一沿。有效频率分别为 3.594→3.589 GHz、3.594→3.587 GHz，收益并非频率升高。少量 mask/store 换走变化分支后，动态指令虽多，但错分支减少，IPC 分别提高 10.310%/8.720%。p18 全样本 commit 则只从 2.898 降到 2.634 us；瓶颈步的 18.46% 不能用作全程 commit 或整机加速比例。

p3 的普通 eval 16/16 变慢，轻量 timing 全样本也变慢 1.279%。阶段探针全样本 commit 为 2.642→3.626 us（+37.262%），全程 cycles 采样中 commit 占该分区模型函数的比例为 6.179%→8.548%，支持新增提交工作确有代价。它在固定瓶颈步原来只有约 97 次错分支，新版省约 17 次；与 p10/p18 各省约 344/350 次的绝对量不同。仅凭“错分支减少 17%”不能推断会加速，也不能把全部 p3 退化都精确归因到 store：其未修改的 compute 机器码耗时也变化，代码布局、缓存/预测状态与线程相位的贡献尚未分离。

p3 的 PMU 计时反而为 -1.635%，与普通版、轻量 timing 和阶段探针方向相反；p29 也出现普通 +0.833%、轻量瓶颈 +0.392%、PMU 当前 -1.381%，而该瓶颈沿动态指令几乎完全不变。这些探针/布局敏感性全部保留，不选取有利探针替换普通 walltime。阶段 archive 仅改变 32 个外层 eval 和两个 wrapper 对象，其余 7420 个 member 不变；timing/PMU archive 仅改变两个 wrapper，但仍可能通过调用边界、系统调用和链接布局扰动性能。

全程函数采样按两种事件各 ABBA 运行，branch-misses 间隔 20011、cycles 399 Hz，按 period 加权。p18/c256 错分支占该分区模型函数的比例 25.182%→14.179%，全部 commit 28.737%→18.011%；cycles 中全部 commit 9.522%→8.889%。p10 commit 错分支占比 35.526%→20.947%，cycles 占比 11.161%→10.695%。这是全程模型函数样本内的占比，不是瓶颈步的时间或全机成本；它与条件 PMU 一起支持“变化检测分支有所缓解，compute 仍占主体”的判断。

轻量 timing 的 3150 个采样中，p18 最后完成次数 452→375，p3 则 696→776，p29 712→731。改善部分线程后，p3/p29 仍挡在关键路径上；N=K=32 的屏障不会把其他线程节省的时间直接相加。候选 p18 瓶颈步 compute 仍约 40.6 us、占该步模型 eval 约 82.6%，单靠提交分支无法解决其剩余差距。

#### 保留边界与下一步

本轮验证了通用生成方式、精确激活与局部机制，没有达到稳定整机收益的结论。选项和回归保留，默认关闭；不改 Verilator，不引入分区或信号名单，不提交未请求的默认提升。

若继续提交方向，优先考察同一合法 event/update guard、同一有序提交范围内，将多个状态的精确 changed 掩码在局部累积后合并写 active 字节；目标是同时减少跳转和重复 active read-modify-write，而非继续扩大逐寄存器 eager。需先审计现有 lockstep、guard 合并和 deferred activation 覆盖，避免重复实现；必须在任何消费者可读取前 flush，并保留多写者次序、无变化行为及计数语义。单纯把门槛从 2 改为 1 可以作为后续有依据的消融，但不会自动解决低变化率状态的无效 store 成本。

另一方面继续以 bool-eager 为基线拆解 p18 活跃 compute batch 的值计算、变化比较及激活成本。p29 的重半周期仍约 61 us、commit 约 0.027 us，本轮不解决它；按需/事件约束求值须另证消费者与跨沿依赖，不能机械搬运执行时机。上述均为后续方向，不宣称本轮已实现或验证。

复现入口为 `priority_mux_chains/commit_experiment.py`、`commit_finalize.py`、`commit_results.py`。数据集中在 `commit_scalar_eager_2/`：`paired_results.json` 为 16 对普通汇总，`probe_results.json`/`constant_probe_results.json` 为固定瓶颈、全样本与历史最慢 10%，`phase_results.json` 为阶段拆分，`branch_profile/`/`cycles_profile/` 为函数及地址采样，`results.json` 汇总源码作用域、harness 恒等性、AB/BA 顺序敏感性、关键路径和全部功能签名。`experiment_stages.json`、`validation.json`、`finalization_stages.json` 保留实际执行次序与耗时；原始 TSV/日志与成功样本均可追溯。

### 7.26 相同 reader 集合的标量提交合并（2026-10-01）

#### 通用规则与专项检查点

本轮仍以 §7.24 的冻结 `priority_mux_bool_eager` 为基线，不叠加上一节未确认稳定收益的逐寄存器 eager。新实验选项 `commit_scalar_same_reader_groups` / `WOLVRIX_GRHSIM_COMMIT_SCALAR_SAME_READER_GROUPS` 默认关闭，候选统一对全部 32 分区开启，`commit_scalar_eager_max_activation_writes=0`。Verilator 不变，不匹配分区、模块、信号或采样热点名单。

先审计已有实现：guard 合并只消除重复写使能判断；lockstep 要求 next 表达式等价及同步状态条件；compute deferred activation 不覆盖本轮提交。新规则在已经建立的同一 event/update guard 内，沿原发射顺序合并连续 2..8 个完整 reader active-ID 集合相同的普通标量写入。只接受单写者、全掩码、最多 64 bit、next 已物化为 compute 标量结果的寄存器；直接状态引用、部分掩码、多写者、宽状态、无 reader、latch、memory、reg-to-mem intent storage 和既有 lockstep 均不混入组内。不同 reader、不合格写入及作用域边界会断组。

对每个成员保留精确 `changed_i = (state_i != next_i)`，组内任一变化才进入写回分支，然后按原顺序写回组内全部状态并只激活一次共享 reader 集合。整组不变时没有 store 和激活。部分成员不变时会产生有限冗余 store，但共享 reader 的并集与旧路径完全相同；不会为了省分支激活本来不应执行的 reader。`touchedWriteCount` 和 batch-trigger profile 仍逐成员按 `changed_i` 累计，commit continuation 只在真实变化时置位。目标是同时减少跳转和重复标记读改写，不能仅凭静态数量断言性能提高。

生成前静态预扫描只统计全掩码提交块的相同激活表达式，尚未包含全部 IR eligibility，故仅为上界：267117 次标量写中，28116 组、111960 次写入、128249 条重复激活语句可合并。p3/p10/p18 上界分别为 6260/15065/2206 次写入；最终以新生成器实际命中和结构化逆变换审计为准。预扫描文件为 `priority_mux_chains/commit_group_scan.json`，不是动态执行次数或性能预测。

新增 CTest `emit-grhsim-cpp-commit-same-readers` 已在 node030 CPU96--127、Clang23/O3 下通过，127.15 s。15 模式覆盖默认/显式关闭、环境变量与 attribute 优先级、开启、helper 拆分、perf、full-pass、bitmap、动态 activity/trigger profile、关闭旧 unlikely 提示，以及与 eager 同时开启。测试含 1/7/8/16/32/64 bit、130 bit 回退、不同初值、组大小 8+2、全组不变、单个成员变化、不同 reader、多个写者、部分掩码、不同 guard 和空 reader；每模式两次 init、各 400 组输入，逐阶段核对输出和精确 touched-write 次数。开启/关闭的 reader 动态执行、batch 次数、固定点轮数及 batch-trigger 计数逐字节相同。

全包 scope checker 使用 C++ AST 校验 next/changed、按位 OR、写入目标和完整激活集合，将分组逐项逆变换后要求与冻结基线源码逐字节相同。专项正例及 OR、写入值、guard、激活位四类语义变异负例已验证；完整设计继续沿用该检查，不忽略任意其他差异。模型头文件、state、compute、外层 eval、wrapper、Makefile 均须不变，编译对象变化只能来自通过校验的 commit 源文件。

完整驱动为 `priority_mux_chains/commit_experiment.py --commit-groups`，产物集中于 `build/repcut_grhsim_20260925/commit_same_reader_groups/`。预定完成完整默认/开启 emitter、两后端 package 回归、全图生成和 Clang23/O3 编译，然后 16 对 C=100000 普通 AB/BA、timing/相邻步 PMU/阶段探针各两对及两种事件各 ABBA 的全程采样。使用 node030 CPU96--127、NUMA1、N=K=32、all-spin、ASLR off，不做额外核空闲筛选；本任务编译与正式计时不重叠。固定条件步号仍采用 §7.24 的独立 bool-eager timing，同时保留全样本、历史最慢 10% 和两沿合计。当前为实现/专项检查点，尚无本候选的 walltime 结论。

#### 完整生成、作用域与正确性结果

本轮完整流程已于 2026-10-01 完成。全图生成 walltime 583.461 s，其中 IR 读取 53.950 s；Clang23/O3 模型 `make -j32` 225.545 s，harness 重编译及链接 3.823 s。生成进程单独设置 `MIMALLOC_ALLOW_LARGE_OS_PAGES=0`；这不是仿真选项，未传入正式性能运行，也未更改系统 THP 配置。默认完整 emitter 回归最终复测 308.129 s、候选选项组合完整回归 307.445 s、两后端 package 回归 44.569 s 均通过；15 模式专项、既有 scalar-eager 专项、与 exact-event/lockstep 的组合回归（19.244 s）及增强 AST 正负例全部通过。AST checker 同时覆盖直接激活写入和激活表循环，不能因表式输出而漏审激活内容。

实际命中全部 32 个分区：28014 组、111473 次寄存器写入，组大小 2/3/4/5/6/7/8 的数量分别为 13182/3362/2950/917/761/664/6178。静态减少 127599 次激活写入；按顶层语句计为 127554，差额来自一个包含 46 个 entry 的激活表循环。两者均为生成代码静态量，不是每 step 的动态节省量。实际 eligibility 后的覆盖略小于前文预扫描上界。

130 个 commit 源文件通过结构化逆变换后与冻结基线逐字节相同，其他 7423 个源码/头文件/Makefile 不变；编译对象为 130 个变化、7324 个完全一致。harness 39 个对象相同，`common.o` 仅 `__TIME__` 提示中的 6 个字符不同。变化源码合计 240363522→216545604 bytes（-9.909%），最终 ELF 的 text 为 106257000→103117808 bytes（-2.954%），data/bss 不变。候选 ELF SHA-256 为 `14f47251b2268897d3c609011fa6a88cd51830acac3d954ff99883b1523a1583`。

代表性 commit 函数中，p3/c343 的 text 321411→223821 bytes、条件跳转 11011→7178；p10/c173 为 423783→274935 bytes、15726→9263；p18/c256 为 367595→309432 bytes、12768→10670。compute、外层调度和状态布局没有改动；静态跳转与代码体积减少本身仍不等于运行收益。

32 次普通、12 次 wrapper 诊断、8 次全程 PMU，合计 52 次 C=100000，以及 14 次 C100 smoke 全部通过。正式运行均启用 Difftest，签名一致：PC `0x80000c0c`、instructions=240349、cycles=99996、guest_cycles=100001、steps=200102。输入、二进制及 emitter 源码/核心库/binding 身份核对通过。4 次阶段探针中，每次 1575 个采样 step × 32 分区的固定点轮数向量逐项一致。

#### 16 对普通运行：约 0.54% 的小幅整机收益

| 普通版指标 | bool-eager 基线中位 | 相同 reader 分组中位 | 16 对配对变化中位 | 候选更快 |
| --- | ---: | ---: | ---: | ---: |
| Host | 17.5045 s | 17.4450 s | -0.549% | 14/16 |
| 最终 walltime | 17.5400 s | 17.4800 s | -0.541% | 14/16 |
| 全局 eval/step | 57.3900 us | 56.8630 us | -0.987% | 16/16 |
| 全局 update/step | 24.4940 us | 24.4790 us | -0.055% | 9/16 |
| p3 eval/step | 44.8760 us | 44.8385 us | +0.009% | 8/16 |
| p6 eval/step | 37.9790 us | 37.1495 us | -2.245% | 16/16 |
| p10 eval/step | 32.8320 us | 31.9320 us | -2.681% | 15/16 |
| p18 eval/step | 32.3075 us | 31.7090 us | -1.734% | 16/16 |
| p28 eval/step | 15.8480 us | 16.0900 us | +1.473% | 0/16 |
| p29 eval/step | 19.0215 us | 18.6755 us | -1.834% | 16/16 |

配对变化仍为先计算每对 `100*(candidate_i/baseline_i-1)` 再取中位，不是前两列独立中位数之比。四轮按实际顺序的 walltime 配对变化为 -0.341%、-1.198%、-0.257%、-0.653%，更快次数为 4/4、4/4、3/4、3/4。全部 AB 为 -0.540%（6/8 更快）、BA 为 -0.568%（8/8 更快）；Host 对应 -0.549%/-0.518%。全局 update 的 AB/BA 为 +0.414%/-0.175%，不能说通信本身获益；本轮没有修改通信实现。

本轮在该固定 workload/二进制/机器配置下支持小幅正向 walltime 收益，两种顺序方向一致；没有重现 §7.25 的 p3 明显退化。它不是新的大幅加速，也不能用本轮 -0.541% 与上一轮 -0.428% 的差值当作两个候选的直接 A/B 优势。全部成功样本保留，未按胜负或空闲率筛选。除表内 p28 外，p4/p14/p23 普通 eval 也分别为 +1.710%/+1.409%/+1.016%，不因它们暂非主瓶颈而隐藏。

#### 提交成本下降，但不能把所有计时变化归因到它

条件集合固定采用 §7.24 独立 bool-eager 标签：p3/p10/p18 每次分别为 350/199/237 个 step；本轮不重新选择候选较有利的步号。下表轻量 timing、阶段拆分、相邻步 PMU 是三种独立诊断，不能混加绝对时间或用阶段探针的加速替换普通版 walltime。

| 固定历史瓶颈步 | 轻量 timing eval | 阶段探针 commit | commit 变化 | PMU 当前指令变化 | PMU 当前错分支变化 |
| --- | ---: | ---: | ---: | ---: | ---: |
| p3 | 43.535→43.402 us | 3.346→2.855 us | -14.673% | -0.815% | 99.39→90.19（-9.251%） |
| p10 | 52.975→51.786 us | 8.592→7.052 us | -17.929% | -1.204% | 899.34→834.11（-7.253%） |
| p18 | 52.052→50.893 us | 8.717→7.572 us | -13.129% | -0.242% | 1365.74→1226.60（-10.188%） |

p10/p18 当前 PMU eval 为 -2.946%/-2.670%，当前加下一沿为 -2.132%/-1.798%，未见将节省的工作转移到下一沿；有效频率分别为 3.592→3.585 GHz、3.590→3.591 GHz，不支持频率提升解释。PMU running/enabled 全部为 1。与上一轮“减少很多错分支但增加指令”不同，本轮同时减少了一部分分支、重复激活与动态指令；精确 reader 集合和固定点轮数未改变。

p3/p10/p18 全体采样的 commit 时间分别为 2.713→2.298、3.351→2.716、2.921→2.561 us。全程 cycles 采样中 commit 占各分区模型函数样本的比例分别为 6.785%→5.513%、10.279%→8.490%、8.927%→8.150%；p18/c256 错分支占比 25.307%→20.356%。这些全程占比的分母是该分区模型函数的 period 加权样本，不含 worker 自旋，不是固定瓶颈步时间比例。

阶段探针中 p3 的 compute 也从 37.756 降到 36.625 us，但它的 compute 机器码未改，普通 p3 eval 更是基本持平。因此只能说提交成本下降、没有重现 eager 的额外成本，不能宣称 p3 普通运行得到阶段探针所示的大幅加速。timing/PMU archive 各只改变两个 wrapper 对象，7452 个 member 保持一致；阶段 archive 改变 32 个外层 eval 加两个 wrapper，其余 7420 个 member 保持一致。探针仍可能改变链接布局和线程相位。

p28/p29 尤其需要保留这一边界。固定瓶颈集合的轻量 eval 分别 +2.778%/+2.470%，而 PMU 当前 eval 为 -2.387%/-4.102%，方向相反；该沿动态指令和分支数几乎完全相同，commit 仅约 0.026/0.027 us。p28 固定集合仅 13 个 step，但即便使用全部 1575 个采样或历史最慢 10% 的 158 个 step，轻量与 PMU 方向仍相反；p29 同样如此。不能用有利的 PMU 时间解释普通版 p28 退化，或把普通 p29 的 -1.834% 宣称为重半周期计算已减少。布局、缓存/预测状态及线程相位尚未分离，本轮未完成这些间接影响的归因。

#### 收敛结论与下一步边界

1. 同 reader 提交合并实现了通用、精确的激活合并，本轮观察到约 0.54% 的 walltime 收益，证据比上一轮逐寄存器 eager 的顺序敏感结果一致。保留实验选项及测试，默认仍关闭；本轮不提交、不改生产默认，也不按 p28 等个别分区开关。后续做机制对照时保留冻结 bool-eager 基线，不能悄悄叠加候选。
2. 接下来不应继续盲目扩大 commit 分组。p10/p18 条件 compute 仍为 41.609/41.046 us，分别占候选该步总 eval 的 82.193%/81.838%；应优先拆分活跃 compute batch 内的实际值计算、变化检测和 active 标记，寻找可以消除的重复物化或重复激活，并先审计已有 deferred activation 覆盖。用通用依赖/副作用约束描述规则，不匹配热点名称，不添加第二套逐值运行时元数据。
3. p29 的重半周期仍约 61 us，commit 几乎为零，本次提交优化不能解决它。轻量探针的 3150 次采样中 p3/p29/p18/p10 最后完成次数从 691/673/451/437 变为 724/685/436/406；候选 p3+p29 仍占约 44.73%。这只是各变体实际最后完成分布，不能代替前面的固定标签条件 A/B。p29 后续应考察按需求值和跨沿中间结果复用，但必须先证明消费者与事件依赖，不能机械挪到另一半周期。

普通数据见 [paired_results.json](../../build/repcut_grhsim_20260925/commit_same_reader_groups/paired_results.json)，完整汇总见 [results.json](../../build/repcut_grhsim_20260925/commit_same_reader_groups/results.json)，固定条件及全样本/最慢 10% 分别见 [probe_results.json](../../build/repcut_grhsim_20260925/commit_same_reader_groups/probe_results.json)、[constant_probe_results.json](../../build/repcut_grhsim_20260925/commit_same_reader_groups/constant_probe_results.json)，阶段拆分见 [phase_results.json](../../build/repcut_grhsim_20260925/commit_same_reader_groups/phase_results.json)。全程原始 profile、函数和地址计数仍在该目录 `branch_profile/`、`cycles_profile/`；`experiment_stages.json`、`validation.json`、`finalization_stages.json` 记录实际运行次序和耗时。所有正式运行、最终回归与结果校验均已结束，没有遗留后台测试。

### 7.27 活跃 compute 残余归因与逐字宽拼接（2026-10-01）

#### 残余热点与实现检查点

仍使用 §7.24 冻结 `priority_mux_bool_eager`，没有叠加 §7.25/7.26 的提交候选。先在 p10/p18 外层 eval 调用处对各 compute batch 计时，不修改 batch 机器码；每 127 step 采一次，两次 C=100000，各 1575 个采样。archive 只有两个 wrapper 和两个外层 eval 共四个对象改变，另 7450 个保持相同。两次正式 Difftest 和 C100 smoke 通过，结果位于 `build/repcut_grhsim_20260925/compute_residual/`。条件步号仍固定为 §7.24 独立标签，每轮 p10/p18 分别 199/237 个 step。

| 分区/compute batch | 固定历史瓶颈步内累计 batch 时间 | 全采样平均 | 全程 cycles 样本归于 concat 的比例 |
| --- | ---: | ---: | ---: |
| p10/b15 | 4.276 us | 1.662 us | 87.785% |
| p10/b17 | 3.867 us | 1.367 us | 99.231% |
| p10/b16 | 1.815 us | 0.768 us | 100.000% |
| p10/b53 | 1.722 us | 0.836 us | 75.956% |
| p18/b18 | 1.486 us | 0.714 us | 89.470% |

时间为同一个 step 内所有固定点轮次对该 batch 的调用累计，不是单次调用；逐调用时钟有扰动，不能用它替换普通版 walltime 或直接算可加速上限。p18 后续 b195/b210 条件时间为 0.788/0.653 us，热点更分散。

源码归因复用 §7.26 的冻结基线 cycles/branch-misses 全程采样，在 node030 用完全相同的 Clang23/O3 编译选项加 `-gline-tables-only` 重编译九个 batch，逐个确认 `.text` 与冻结原对象逐字节相同，再将函数偏移映射到源码行。上述百分比分母是相应函数的 period 加权 cycles 样本；它不是固定瓶颈步专属 profile，也不排除采样 skid/优化后行号归属偏差。结果及 `.text` 身份见 `compute_residual/source_profile/results.json`。它支持优先检查宽拼接，但不能仅凭源码形态宣称机器代码有多少冗余 store。

这些 concat 主要在构造 RepCut 跨分区输出 bundle。旧生成方式先把整个结果数组清零，再按各输入片段对目标 64-bit word 反复 `|=`。已有 compute deferred activation 被保留，本轮不另建重复激活方案。实验实现 `wordwise_wide_concat` / `WOLVRIX_GRHSIM_WORDWISE_WIDE_CONCAT`：在局部组成一个完整 word 后只写回一次，逐字由高至低输出；跨 word 片段、输入尾位和结果尾位均保留掩码，宽操作数表达式只求值一次。只接受结果至少 96 bit、至少四个操作数的既有 direct-wide-concat，且宽度和正确、纯表达式、无结果存储依赖/别名及 event 值；不是按 RepCut、模块、分区或信号名字匹配。全部 32 分区统一开启实验选项，默认仍关闭，Verilator 不变。

最终实现的八模式专项已通过（51.864 s）：默认/显式关闭/开启、环境变量、attribute 优先级、perf、bitmap、helper split；覆盖 1/7/16/31/32/33/63/64/65/72/129/130/257-bit 输入、跨 word、多小操作数、非整 word 尾部、有符号输入及高位脏数据。每模式两次 init、各 300 组输入、两次 eval，与独立逐 bit 参考及跨 supernode 的切片输出核对；关闭和优先级回退的所有生成源码与默认逐字节相同。新 scope checker 用 AST 定位作用域，逐一比较输入表达式、分块、移位、每个输出 word 的 OR 片段多重集、掩码和唯一写回，再逆变换要求基线源码逐字节相同；八个正例和五类语义变异拒绝测试通过。

驱动 `priority_mux_chains/wordwise_experiment.py` 分 preflight/build/measure，产物集中在 `wordwise_wide_concat/`。计划顺序完成完整默认/开启及两后端 package 回归、全图生成、Clang23/O3 编译、16 对普通 C=100000 AB/BA，再做轻量 timing、相邻两沿 PMU 和阶段拆分。运行仍为 node030 CPU96--127、NUMA1、N=K=32、all-spin、ASLR off，无额外空闲率筛选；本任务编译与正式性能运行不重叠。当前是归因和专项实现检查点，尚无候选 walltime 结论。

#### 完整回归与全图源码审计检查点

完整默认回归 341.157 s、开启候选回归 359.717 s、Verilator/GrhSIM package 回归合计 52.563 s 均通过。八模式专项另以 Clang23/O1 加 UBSan 运行通过，未出现未定义行为报告。全图生成 644.091 s；完整源码审计确认 32 分区共 10437 个 concat、148312 个目标 word、433767 个片段按同一通用规则改写，1578 个 compute 文件变化、5975 个文件完全相同。全部头文件、状态、commit、外层 eval、wrapper 和 Makefile 不变，所有改写逐片段比较并逆变换恢复基线逐字节一致。

审计器同时支持有/无逐值注释的生成配置：改为以 AST 中 concat 的生成声明和作用域定位，不依赖可选的 `// value` 注释；八个正例分别在两种注释模式验证，五类语义变异仍被拒绝。结果见 [source_summary.json](../../build/repcut_grhsim_20260925/wordwise_wide_concat/source_summary.json)。本检查点已开始完整 Clang23/O3 编译，尚不以源码减少重复写回推断实际指令或 walltime 收益。

#### 完整构建、作用域与正确性

Clang23/O3 全模型编译 288.276 s，harness 重编译/链接 4.483 s。对实际链接的 7454 个 archive member 核验，6676 个逐字节相同，778 个变化且全部属于上述已审计的 compute 文件；基线/候选 archive SHA-256 分别为 `737e9588a9e0b977b2afb32a1344b2cc80b36f3eabea00fae35f4a17196af964` / `ef8a7671abc1239cc65f0cfcda7ac01af65211dcb867242872fa7ba925ef6337`。变化源码合计 413394266→443012706 bytes（+7.16%），最终 ELF text 106257000→105455872 bytes（-0.754%）；源码展开量不等于机器码或运行成本。候选 ELF SHA-256 为 `4086634f32cfd7a031787da6a20e552a80e64bb85b7e928720b31faf5064f489`。

代表性 batch 的静态指令数 p10/b15 为 38700→34437（-11.02%）、b16 为 11133→9635（-13.46%）、b17 为 36213→32271（-10.89%），p18/b18 为 7749→5869（-24.26%）。p10/b53 和 p18/b195、b210 的机器码完全不变：虽然其中部分源码命中规则，Clang/O3 原本已完成相应简化，不能把命中数直接视为额外运行收益。

本轮共有 56 次 C=100000 正式运行和 16 次 C100 smoke，全部通过；正式运行均开启 Difftest，签名均为 PC `0x80000c0c`、instructions=240349、cycles=99996、guest_cycles=100001、steps=200102。四次阶段探针的每步/每分区固定点轮数向量完全相同；batch 探针的调用次数、活跃调用及活跃位向量也逐项相同。输入、冻结基线、候选二进制和生成器源码/核心库/binding 身份在实验前后未变。专项 UBSan、完整默认/开启 emitter、两后端 package 回归及全图语义审计通过；Verilator 路径未修改。

#### 16 对普通运行与直接计算归因

每对先计算 `100*(candidate_i/baseline_i-1)` 再取中位；表内前两列是各臂独立中位，不能用其比值替代配对变化。所有成功样本保留，没有核空闲率筛选，也没有编译与正式测量重叠。

| C=100000 普通版指标 | bool-eager 基线中位 | 逐字拼接中位 | 配对变化中位 | 候选更快 |
| --- | ---: | ---: | ---: | ---: |
| Host | 21.3655 s | 21.3210 s | -0.476% | 10/16 |
| 最终 walltime | 21.4050 s | 21.3550 s | -0.515% | 10/16 |
| 全局 eval/step | 70.9335 us | 70.6930 us | -0.283% | 12/16 |
| 全局 update/step | 28.8850 us | 29.1220 us | -0.285% | 9/16 |
| 32 分区 eval 合计/step | 836.5950 us | 831.0735 us | -0.738% | 15/16 |
| p10 eval/step | 39.3580 us | 38.7645 us | -1.473% | 15/16 |
| p18 eval/step | 39.9535 us | 39.5520 us | -0.731% | 12/16 |
| p29 eval/step | 25.5835 us | 25.8690 us | +1.454% | 0/16 |

四轮 walltime 配对中位依次为 -0.929%、-0.115%、-0.237%、-0.458%，更快次数 3/4、2/4、2/4、3/4；AB 与 BA 分别 -0.279%/-0.627%，各 5/8 更快。方向上是小幅正向，但胜率和量级不足以称为稳定的大幅整机加速。和 §7.26 的独立运行相比，本轮冻结基线本身的 walltime 中位明显更高，固定瓶颈 p10 的 PMU 有效频率约 3.06 GHz，而 §7.26 约 3.59 GHz；因此不能跨实验直接比较两个候选的 walltime 百分比，只能使用本轮同期配对对照。

固定采用 §7.24 独立选择的瓶颈步号，p10/p18 每次各 199/237 步，不按候选重新挑步。p10 轻量 timing 的 eval 62.601→60.669 us（-3.086%）；相邻步 PMU 的当前沿 cycles -3.526%、动态指令 -2.604%、错分支 -4.803%，当前加下一沿时间 -3.141%，没有显示成本转移。阶段探针的 p10 compute 47.601→44.726 us（-6.039%），commit 9.834→9.744 us；独立逐 batch 计时中 b15/b16/b17 分别从 4.622/1.883/4.269 降至 3.929/1.631/3.565 us。逐调用计时有扰动，不能将这些绝对值与阶段探针或普通版直接相加，但源码、机器码、动态指令及计时方向一致，支持 p10 直接 compute 收益。

p18/b18 的固定瓶颈 batch 为 1.526→1.363 us（-10.710%），但 b195/b210 机器码不变，且固定步全部 batch 的逐调用计时合计未改善。其轻量 timing eval 为 61.240→61.521 us（+0.460%），PMU 当前沿 cycles -0.106%、指令 -0.798%、错分支 +1.704%，当前加下一沿时间仅 -0.252%；阶段探针 compute 46.691→46.344 us（-0.744%）。单个宽拼接热点改善被更分散的其余工作淹没，不能从 b18 的 -10.7% 推出 p18/整机同比例加速。候选全程源码归因中，p18/b195、b210 的 cycles 样本约 50%/53% 归于标量赋值，另有约 16%/19% 归于变化检测或激活，而 concat 只约 5.5%/不足主项；行号归因存在采样 skid 与优化映射误差。

p29 在普通运行 16/16 变慢，但固定瓶颈步轻量 timing 82.376→82.293 us，PMU 当前沿指令数约 433811→433811、cycles +0.021%，与普通平均方向不同。其全程主要热点 b137/b138/b139/b145/b141 的源码和对象均未被本规则改变；整个 p29 仅 12 个其他 compute 文件改变，已链接热点地址因整机代码变化而平移。现有证据不支持“p29 本身多执行了拼接指令”，也不能证明是哪一项布局、缓存、预测或线程相位效应造成普通版 +1.454%；该退化必须保留在最终评价中。

#### 结论与后续边界

通用逐字宽拼接确实减少了 p10 热 compute batch 的机器码和执行成本，整机 walltime 本轮观察到约 0.51% 的配对中位收益，但 10/16 胜率和 p29 的一致退化使其尚不适合作为默认。保留选项与专项测试，默认关闭；不手选分区/模块/信号，也不叠加未验证的提交候选。下一轮应优先拆解 p18/b195、b210 中高占比的标量赋值与变化检测，以及 p29 未修改重半周期的残余计算；若要归因 p29 间接退化，应先做等机器码的链接布局对照，而不能以不同探针方向挑选有利解释。

普通配对见 [paired_results.json](../../build/repcut_grhsim_20260925/wordwise_wide_concat/paired_results.json)，完整汇总见 [results.json](../../build/repcut_grhsim_20260925/wordwise_wide_concat/results.json)，静态作用域和实际 archive 审计见 [static_summary.json](../../build/repcut_grhsim_20260925/wordwise_wide_concat/static_summary.json)，固定条件 PMU、阶段及逐 batch 结果分别见 [probe_results.json](../../build/repcut_grhsim_20260925/wordwise_wide_concat/probe_results.json)、[phase_results.json](../../build/repcut_grhsim_20260925/wordwise_wide_concat/phase_results.json)、[compute_probe/results.json](../../build/repcut_grhsim_20260925/wordwise_wide_concat/compute_probe/results.json)。两种全程事件原始样本和源码映射在 `branch_profile/`、`cycles_profile/`、`source_profile/`；`experiment_stages.json` 保留各阶段顺序与耗时。实验已结束，没有遗留后台任务。

### 7.28 terminal priority mux 的 commit-demand 求值（2026-10-02）

#### 动机与通用规则

前一轮热点分析表明，p29 的长优先级选择链在 compute 半周期大量执行，但最终
只有寄存器写入真正需要它的结果。为验证“只在终端提交 guard 内求值”是否能减少
无效工作，实现了 `priority_mux_commit_demand` 试验选项（attribute 与
`WOLVRIX_GRHSIM_PRIORITY_MUX_COMMIT_DEMAND` 环境变量；默认关闭）。它要求已有的
`priority_mux_chains` 选项开启，并且不改变 Verilator 路径。

规则完全基于 IR 依赖和 emitter 可证明的存储性质，不匹配分区、模块、信号或
workload 名字。只接受纯 compute supernode 中的长标量 mux 链，并逐条证明：链根
已物化为稳定 value field、条件/候选/fallback 均为稳定输入/field/常量、链根只有
一个 user、该 user 是 commit 阶段寄存器写入 data，且没有 output/waveform/inout 或
第二消费者观察它。compute 阶段跳过通过证明的链，commit 的真实 event/update
guard 内重新计算；状态写入、mask、event edge 和 reader activation 保持原路径。
重新求值的 change-propagation 被显式抑制，避免把一个只服务于当前提交的数据值当
成新的跨 supernode 活动源。

为减小 commit dispatch 热函数的指令流，长链放进 `noinline` lambda。该布局优化
不是语义前提；关闭选项时生成源码逐字节保持默认恒等。当前实现仍是实验性功能，
不能跳过完整功能回归和 Difftest。

#### 生成、编译与语义回归

完整 XiangShan 图统一应用该规则，自动命中 96 条链：p15 为 27 条、p28 为 32
条、p29 为 37 条，链长为 511/520；没有使用分区名单。候选包目录为
[`p29_demand_generic_diag9/package`](../../build/repcut_grhsim_20260925/p29_demand_generic_diag9/package)，
Clang23/O3 模型编译用时 227.53 s，实际链接 harness 使用的 ELF 为
[`aligned_build/emu/grhsim-compile/emu`](../../build/repcut_grhsim_20260925/p29_demand_generic_diag9/aligned_build/emu/grhsim-compile/emu)。

新增 `emit-grhsim-cpp-priority-mux-commit-demand` 专项，覆盖默认/显式关闭恒等、
单消费者寄存器写入、时钟沿提交、保持时钟时不提前改变状态，以及输入变化后下一
时钟沿取新值；该专项和既有 `emit-grhsim-cpp-priority-mux-chains` 长链专项均通过。
完整模型 C=100000 Difftest 签名保持
`PC=0x80000c0c, instructions=240349, cycles=99996, guest_cycles=100001,
steps=200102`。

#### node030 C=100000 交错结果

运行配置保持 node030 CPU96--127、NUMA1、N=K=32、all-spin、ASLR off、Clang23/O3，
每次 4 对 AB/BA，保留全部成功样本。先将内联求值候选与冻结 baseline 对比，再将
无内联候选与内联候选直接对比；原始结果见
[`ab_aligned_c100000_4pairs`](../../build/repcut_grhsim_20260925/p29_demand_generic_diag8/ab_aligned_c100000_4pairs/summary.json)、
[`vs_diag8_c100000_4pairs`](../../build/repcut_grhsim_20260925/p29_demand_generic_diag9/vs_diag8_c100000_4pairs/summary.json)
和重复轮次
[`vs_diag8_repeat_c100000_4pairs`](../../build/repcut_grhsim_20260925/p29_demand_generic_diag9/vs_diag8_repeat_c100000_4pairs/summary.json)。

| 直接 A=内联、B=无内联 | 首轮配对中位变化 | 重复轮配对中位变化 |
| --- | ---: | ---: |
| Host | -1.435% | -0.460% |
| 全局 eval/step | -2.575% | -1.437% |
| 全局 update/step | +1.622% | +1.619% |
| 最大分区 eval/step | +0.672% | -0.666% |

与冻结 baseline 的独立 4 对交错中，内联候选 Host 为 `-0.696%`，无内联候选为
`-0.519%`；由于两轮的外部运行窗口不同，这两个数字不作为无内联相对内联的
直接差值，直接 A/B 表才用于候选选择。直接两轮合计 8 对中无内联 Host 胜 5 对，
方向支持保留无内联布局：它主要改善全局 eval/代码布局，同时引入约 1.6% 的
全局 update 代价；最长分区没有稳定缩短，因此不能把该规则描述成“消除了 p29
最大 ASC”。

本轮结论是保留该通用、默认关闭的实验选项和 noinline 实现，下一步仍应围绕最长
逻辑锥的实际关键路径，而不是按分区继续增加特例。实验产物和回归均已结束，没有
遗留后台任务。

### 7.29 commit-demand 后的逐步关键路径与残余热点（2026-10-02）

#### 冻结对照与条件计时

继续对比 §7.24 的 `priority_mux_bool_eager/package` 与 §7.28 已实测的
`p29_demand_generic_diag9/package`，普通程序沿用相同 harness 的
`p29_demand_audit/baseline_relink` 和 `diag9/aligned_build`。本轮明确冻结已有
diag9 的 `[&]` noinline lambda 产物，不把工作区随后 `[this]` 的源码细化视为
已经重新做过全图性能验证；不叠加提交合并或逐字拼接，不改变生产默认。

新增相邻半周期 timeline 探针：每 127 step 采当前及下一 step，同时记录真实 clock
输入、32 个线程的 eval/update 起止时间和 Host 阶段边界。每个模型 archive 只替换
common/eval/update 三个框架对象，其余 7451 个 member payload 完全相同；仍可能有
探针与链接布局扰动，因此探针 walltime 不当作普通程序的收益。固定配置仍为
node030 CPU96--127、NUMA1、N=K=32、all-spin、Clang23/O3、ASLR off、C=100000。
4 对 AB/BA、2 次 C100 smoke 全部通过，正式 Difftest 签名与 §7.28 相同，无核空闲
筛选，保留全部成功样本。每次 3150 个采样，每个变体合计 12600 个。

为避免按候选挑选有利 step，条件表继续使用 §7.24 独立的 baseline 历史瓶颈标签；
另做 leave-one-pair-out 标签交叉检查，用其他三对 baseline 选择当前对的相同步号。
历史 p29 标签每次 353 步，全部 clock=0；它们的相邻下一步 clock=1。

| p29 历史瓶颈步，4 次合并均值 | baseline | commit-demand |
| --- | ---: | ---: |
| p29 当前沿 eval | 61.279 us | 52.565 us |
| p29 下一沿 eval | 2.360 us | 2.389 us |
| p29 两沿 eval 合计 | 63.639 us | 54.954 us |
| 全局当前沿 eval 阶段 | 68.996 us | 62.097 us |
| 全局两沿 step 合计 | 179.878 us | 172.583 us |
| 当前步仍由 p29 最后完成 | 1298/1412 | 737/1412 |

当前沿 p29 -14.221%，两沿合计 -13.648%，没有显示主要成本搬到下一沿。当前步
全局 eval -9.999%，两沿完整 step -4.055%；局部收益确实落到关键路径上，但有其他
线程接替瓶颈。交叉选择 baseline 标签得到 p29 当前沿 -14.356%、全局当前 eval
-9.531%、两沿 step -3.804%，方向一致。上述是条件探针均值，不是普通版全程 walltime。

独立 compute/commit 探针完成两对 AB/BA 和两次 smoke；每个 archive 只改 32 个
外层 eval 和两个 wrapper，7420 个 batch 等对象保持原样。在同一历史 p29 标签下，
compute 从 59.262 降至 50.934 us，commit 为 0.0275→0.0265 us、固定点轮数均为 1。
它支持重半周期 compute 成本下降，但探针绝对时间不能与上表相加。

#### 瓶颈迁移与剩余收益排序

全部 12600 个采样中，各分区最后完成的次数如下；这张表描述实际瓶颈分布，不能
用各版本自选样本比较条件 eval。

| 分区 | baseline 次数（比例） | commit-demand 次数（比例） |
| --- | ---: | ---: |
| p3 | 2890（22.94%） | 3534（28.05%） |
| p18 | 1851（14.69%） | 2012（15.97%） |
| p10 | 1620（12.86%） | 1787（14.18%） |
| p29 | 2728（21.65%） | 1525（12.10%） |
| p15 | 963（7.64%） | 152（1.21%） |

在保持所有开始时刻和其他分区工作时间不变的假设下，单独把某分区 eval 再缩短
10%，平均最后完成时刻可减少的量为：p3 1.067 us、p18 0.698 us、p10 0.585 us、
p29 0.499 us。此前 baseline 的 p29 为 1.173 us、p3 为 0.902 us；优先级已改变。
这是静态时序敏感度，不是新优化的实际收益预测。

另一反事实计算仅把 baseline 的 p15/p28/p29 duration 换成同一步候选实测值，保持
其余 duration 和全部 start 不变：三分区局部 eval 合计每步少 8.237 us，而最后
完成时刻仅减少 1.885 us。真实探针的全局 eval 为 56.858→55.484 us（少 1.375 us）；
其他分区计时和开始相位也有变化，不能把这两种计算之差唯一归因于代码布局。

通信 update 在本探针中为 23.968→23.950 us，未复现必然增加；最后完成主要是
p20/p16，而最长纯复制 duration 经常是 p5，说明必须区分开始偏移和工作时间。
Host 等最后一个 update 完成后的尾部约 0.633→0.629 us。此前约 +0.85%/+1.6%
的 update 变化尚不能认定为 commit-demand 的固有成本；模型内部 commit 也不是
RepCut 的通信 update。

对 §7.28 的结论补充限定：`max(part_mean_eval)` 不是逐 step 的关键路径，不能因
前者未改善推断 p29 没有缩短长尾；无内联引起的代码布局变化确实存在，但其对计时
变化的因果贡献尚未分离。本检查点支持优先重新 profile 当前 p3，再比较 p18/p29
残余热点，而非继续无条件扩大 p29 的按需计算范围。

原始数据和可复现驱动集中在
[`demand_critical_path`](../../build/repcut_grhsim_20260925/demand_critical_path/)；
archive 身份见 `build.json`，全部逐步样本见 `runs/`，条件/交叉选择/敏感度汇总见
[`results.json`](../../build/repcut_grhsim_20260925/demand_critical_path/results.json)。
阶段结果见
[`phase_results.json`](../../build/repcut_grhsim_20260925/p29_demand_generic_diag9/phase_results.json)。

#### 普通程序复测与重新选择优化方向

在上述探针之外，原始普通 ELF 另做 4 对 C=100000 AB/BA，Host 配对中位 -1.829%、
walltime -1.808%，均 4/4 更快，eval -2.322%；update -0.566%，仅 2/4 更快。
§7.28 无内联对冻结 baseline 的旧窗口为 walltime -0.481%、3/4 更快。两个窗口
使用同一对普通 ELF，合并 8 个配对百分比的中位为 Host -1.391%、walltime -1.393%，
7/8 更快；eval -2.019%、8/8 更快；update +0.509%、仅 2/8 更快。不能只保留这次
较有利窗口，也不把两个窗口的绝对中位 walltime 相除。结果支持小幅收益和实际长尾
改善，但 update 的因果解释仍未闭合。见 `ordinary_4pairs/` 与 `residual_results.json`。

当前候选 p3/p18/p29 各 compute batch 的两次低频计时全部通过功能检查。每个
archive 只改三个外层 eval 和两个 wrapper，7449 个 member payload 不变。
固定历史瓶颈 step 的代表项为：

| 分区 | batch | 每 step 累计调用时间 | 作用/下一步线索 |
| --- | --- | ---: | --- |
| p3 | b46 / b333 / b322 | 2.032 / 0.773 / 0.731 us | 工作分散；前两者的全程 cycles 样本主要落在宽拼接 |
| p18 | b195 / b210 | 0.800 / 0.709 us | 标量赋值和变化传播仍值得分析 |
| p29 | b138 / b137 / b139 | 5.819 / 4.874 / 3.623 us | 选择条件的组合计算与变化传播，非移走的末端链 |

逐 batch 计时含调用处探针开销，不能把这些数和前面的阶段探针混加。另对原始普通
程序各做两次 cycles、branch-misses 采样（ABBA），对十个热点 batch 加 debug 行号
重编译，逐一验证 `.text` 与原对象完全一致后再映射源码。全程 p3/b46 仅占 p3
模型 cycles 样本约 3.40%；该函数内部约 80.6% 落在 concat、19.4% 在宽寄存器读取，
b333 的 concat 约 89.6%。p3/b19、b20 的变化检测/激活样本约 45.8%/50.0%；
p18/b195、b210 标量赋值约 38.7%/43.1%；p29/b137--139 的 kLogicAnd 与
变化传播合计约 94.5%--100%。这里是全程函数内的采样归属，不是条件瓶颈步的
精确 stall 占比；小样本、skid、优化行号映射和未映射部分均限制归因精度。

对应数据在 `compute_candidate/results.json`、`residual_results.json`，以及
[`source_profile/results.json`](../../build/repcut_grhsim_20260925/p29_demand_generic_diag9/source_profile/results.json)。
archive 审计确认 baseline 与 demand 候选的 p3 对象全部一致，不能把 p3 约 1%--3%
的间接变慢归因于新增的 p3 运算。下一轮模型内部工作仍应针对 p3 的宽结果组装与
分散的变化传播；已有逐字拼接/局部表达式/宽状态引用需检查覆盖和净收益，不能作为
全新优化重复提出。

#### 从启动偏移发现的通用 all-spin 派发优化

本轮 update 起止探针同时暴露了更直接的框架开销：Host 按 lane 顺序发布任务，
但即使 Host/worker 均永久轮询，仍逐 worker 获取 mutex，只为执行
`worker.error = nullptr`。这段逐个加锁不属于模型计算，也不属于实际通信复制。
当前正常启动/上阶段完成握手已同步异常槽；all-spin 下后续 `workFast` release
会把清理和任务发布给 worker，故此分支可以省略 mutex。CV/混合策略继续原锁路径，
初始化、停止、异常传播及 join 不变。

据此实现共享 emitter 的 all-spin 专用派发去锁，不匹配后端、分区或信号。仅在
`phase_host_spin_infinite_ && phase_worker_spin_infinite_` 时采用；不是删除同步屏障，
不改变模型、复制量、分区和线程映射，也不改变已有 all-spin/CV 默认策略。
生产实现位于 `wolvrix/lib/emit/verilator_repcut_package.cpp`，该代码也用于 GrhSIM。
本轮 GrhSIM 普通对照以已验证的 diag9 为 baseline，只替换 common wrapper 对象，
其余 7453 个对象完全不变。`commit-demand` 本身仍保持默认关闭。

去锁首轮 4 对 walltime -3.321%、Host -3.299%，复测 4 对 walltime -3.203%、
Host -3.205%，两轮均 4/4 更快。对应 `lock_elision_4pairs/` 和
`lock_elision_repeat_4pairs/`。两次独立构建的相邻沿 timeline AB/BA 中，关键 eval
线程平均启动偏移从 3.435 降到 0.922 us；p29 从 6.679 降到 1.384 us，p18 从
3.780 降到 1.023 us。全局 eval 55.215→53.156 us，而最后完成线程的工作时长
51.301→51.721 us，支持主要收益来自更早派发而非模型本身算得更快。

通信也要保留反方向证据：去锁后 update 的开始偏移更小，但线程复制重叠形态变化，
timeline 中 update 最后完成线程的 duration 19.048→22.442 us，update 阶段
23.750→24.137 us；普通复测则 update -1.963%，最大分区复制 duration +8.403%、
复制 duration 合计 +18.167%。不能把每个线程提前启动的微秒全部算作 walltime 收益，
也不能仅凭这些计时断定是哪种 cache/带宽竞争；本次以普通程序最终 walltime 采纳，
该通信现象保留为后续优化线索。

两后端 package 回归均通过（0.47 s / 43.95 s）。GrhSIM 回归新增 DPI 抛异常、
异常后的重新初始化与继续运行，分别覆盖 Host 和后台 worker，原有串行/N<K/N=K、
wrapper/facade、all-spin/CV、宽状态/early-phase 检查均保留。性能测量仍使用
Clang23/O3；CMake 专项测试使用其原配置 GCC13，不混淆两种编译口径。

#### 混合等待修正与最终代码验证

补充混合策略回归时发现原有完成握手的缺口：worker 永久轮询、Host 使用 CV 或
有限自旋后回退 CV 时，worker 会设置 mutex 保护的 `completed=true`，而旧派发
只清除 `completedFast`，没有清除 `completed`。Host 因而可能把上阶段的完成标志
当成本阶段完成，提前越过屏障。这不是 all-spin 去锁新引入的行为；全 all-spin
只等待原子完成标志，前述该策略下的成功性能样本仍保留。

最终实现保留 all-spin 快路径，并在混合策略的原 mutex 路径内复位 `completed`。
没有删除同步：首次启动通过 mutex/CV 握手，后续 Host 通过 acquire 完成标志确认
worker 已结束，清理异常槽后用 release `workFast` 发布下一阶段任务；worker acquire
该标志后才开始访问任务/异常槽。退出和异常恢复仍执行停止握手与 join。

最终两后端 package 回归均通过（Verilator 0.68 s、GrhSIM 44.26 s）。GrhSIM
运行回归增加四种混合配置，分别通过 wrapper/facade 执行：Host 无限自旋/worker CV、
Host CV/worker 无限自旋、Host 50 us/worker CV、Host 50 us/worker 无限自旋。
这些配置使用 Host lane 0，覆盖后台 early DPI 抛异常和重新初始化，要求完整输出
与串行参考一致；原有默认 Host lane 的异常、N<K/N=K 与 all-spin/CV 检查继续保留。
Verilator package 测试核对生成结构，真实香山 Verilator 功能和性能另由下面的
Clang23/O3 整机对照验证，不把生成检查称为完整 Verilator 运行回归。

最终实现重新编译 common wrapper 后，各后端再完成 4 对普通 C=100000 AB/BA
及各 2 次 C100 smoke，共 16 次正式运行、4 次 smoke 全部通过。整机仍使用
node030 CPU96--127、NUMA1、N=K=32、Host lane 9、all-spin、Clang23/O3、ASLR off；
正式运行启用 Difftest，签名为 `pc=0x80000c0c`、instructions=240349、cycles=99996、
guest_cycles=100001、steps=200102。无额外负载筛选，也不剔除成功样本。

| 最终框架代码，4 对/后端 | GrhSIM | Verilator O3 |
| --- | ---: | ---: |
| baseline Host 中位 | 16.8625 s | 20.8590 s |
| candidate Host 中位 | 16.3110 s | 20.5455 s |
| Host 配对变化中位 | -2.954% | -1.443% |
| baseline walltime 中位 | 16.900 s | 20.910 s |
| candidate walltime 中位 | 16.345 s | 20.590 s |
| walltime 配对变化中位 | -2.968% | -1.435% |
| walltime AB / BA 配对变化中位 | -3.191% / -2.968% | -1.553% / -1.435% |
| Host / walltime 更快对数 | 4/4 / 4/4 | 4/4 / 4/4 |
| 全局 eval 配对变化中位 | -3.427% | -1.145% |
| 全局 update 配对变化中位 | -2.816% | -3.666% |
| 最大分区复制 duration 配对变化中位 | +7.035% | +13.442% |
| 分区复制 duration 合计配对变化中位 | +17.076% | +25.066% |

百分比按每对 `(candidate / baseline - 1) * 100%` 后取中位，不是表中两个
绝对中位数相除。GrhSIM 的 baseline 是已启用 commit-demand 的冻结 diag9，
Verilator 的 baseline 是冻结 O3 模型的原派发框架；这不是 GrhSIM 与 Verilator
之间的交错 A/B，不能用跨后端绝对时间差代替本轮框架优化收益。通信复制的 duration
是线程内 elapsed time，不是复制字节量；所有模型与复制代码未变，复制量没有增加。
更早开始使工作重叠方式改变，虽然局部复制耗时增加，全局 update 和 walltime
仍缩短。具体 cache/带宽影响尚未单独验证，不把猜测写成确定归因。

初版去锁代码的 GrhSIM 两窗口共 8 对，Host/walltime 配对中位为
-3.205%/-3.203%，8/8 更快；初版 Verilator 4 对为 -2.925%/-2.930%，4/4 更快，
数据见 `verilator_lock_elision_4pairs/`。它们与最终版存在混合等待冷路径代码差异，
且测量窗口不同，分别保留，不混为同一个 ELF 的统计。上段启动延迟的 timeline
测量针对初版去锁实现，最终版性能结论使用本表的普通程序复测；不据两窗口收益差
认定混合等待修正导致性能倒退。

作用域核验：最终 GrhSIM archive 仅 common wrapper 一个对象变化，7453 个 member
payload 不变；Verilator 仅替换 common wrapper，另外 78 个链接对象/静态库哈希不变。
新生成的两个后端 fixture 与最终实测两个 wrapper 的 `run_phase_workers_` 在
去掉类名、注释和空白后完全一致。八个混合等待/API 组合又独立运行一遍，全部与
串行参考 transcript 一致。最终 GrhSIM ELF 为
`dcfb1ca02b4c5a770c9af5f5fb4655039d00634641855d46efc57d96f7846233`，
Verilator baseline/candidate ELF 分别为
`12ff6327e7fa4a4866974bfe6727821bebe6f9e46e8b2c9407482251d136958d` /
`9ab8112408aefc66ccb8fdcbfb18d23ad7baca3ab8a00aac77795a32e9f8fd63`。

最终原始结果位于
[`lock_elision_final_4pairs`](../../build/repcut_grhsim_20260925/demand_critical_path/lock_elision_final_4pairs/)
和
[`verilator_lock_elision_final_4pairs`](../../build/repcut_grhsim_20260925/demand_critical_path/verilator_lock_elision_final_4pairs/)；
身份与混合等待汇总见
[`final_validation.json`](../../build/repcut_grhsim_20260925/demand_critical_path/final_validation.json)。
构建脚本为 `demand_critical_path/build_lock_elision.py --final` 与
`build_verilator_lock_elision.py --final`，作用域/附加运行核验为同目录 `finalize.py`。

本轮结论：commit-demand 确实减少了 p29 重半周期计算，未主要转移到下一沿；
瓶颈因此更多转向 p3，但残余工作分散，不能只按最大 batch 决策。由逐步启动偏移
发现的 all-spin 去锁已落实到两后端共用生成器，默认 all-spin 自动使用，无分区、
信号或 workload 名单；混合等待修正同步纳入。模型内部实验选项（包括
commit-demand）默认值保持不变，本轮未提交。下一轮模型优化优先复核新派发方式下
p3 的宽结果组装及变化检测/活动传播，先检查已有逐字拼接等规则的覆盖与副作用；
派发提前后复制 duration 增加则作为独立框架线索，不直接推断应改变同步语义。

### 7.30 新派发框架下的 p3 残余与既有规则复查（2026-10-02）

本轮模型优化基线固定为 §7.29 最终去锁版，GrhSIM ELF 为
`dcfb1ca02b4c5a770c9af5f5fb4655039d00634641855d46efc57d96f7846233`，
即冻结 diag9 模型加最终共享框架；没有悄悄叠加提交分组、逐字拼接或宽状态引用。
实验集中于 `build/repcut_grhsim_20260925/p3_postdispatch_20261002/`，仍使用
node030 CPU96--127、NUMA1、N=K=32、Clang23/O3、all-spin、C=100000，保留全部
功能通过样本，不做额外空闲率筛选，编译与本任务正式测量不重叠。

先对最终派发代码重新做两对相邻沿 timeline AB/BA，各模型 archive 只改三个
wrapper 对象，其余 7451 个对象不变；4 次正式运行和 2 次 smoke 全部通过。
去锁版本共 6300 个样本，eval 最后完成次数为 p3 1927（30.59%）、p10 935
（14.84%）、p18 893（14.17%）、p6 878（13.94%）、p29 597（9.48%）。
p3 仍是第一优先级；把单一分区工作假设缩短 10% 的静态关键路径敏感度依次为
p3 1.078 us、p10 0.620 us、p18 0.599 us、p6 0.504 us、p29 0.391 us。
这些是敏感度而非可实现加速承诺，也不能把探针 Host 时间当作普通版 walltime。

用两次去锁 timeline 在每 127 step 的同一步号上平均实际完成时刻，预先冻结
1575 个瓶颈标签，p3/p10/p18/p6/p29 分别占 490/232/216/211/149 步；此标签
在测试新模型候选之前确定。另对这五个分区的外层 eval 加逐 batch 调用计时，
仅改变五个外层 eval 和两个 wrapper，7447 个 archive member 不变。
两次正式运行及一次 smoke 全部通过。固定 p3 标签下，b46/b333/b322/b19/b146/b20
每 step 累计调用时间分别为 1.996/0.780/0.776/0.687/0.684/0.680 us，仍较分散。
同一口径下 p10/b15、b17 为 4.361/3.890 us，p6/b184 为 7.953 us。
逐调用计时有额外开销，不与低频 timeline 的 eval 时间直接相加或计算精确占比。

源码复查确认 p3/b46 含大规模输出包拼接：先清零目标字数组，再逐源片段 OR，
已存在的 `wordwise_wide_concat` 正是针对这一结构，不能包装为新发明。
因此首先全图复测其与当前 demand/新框架的组合，不按分区/信号筛选。
通过对已有完整生成包的拼接改写做三方合并和逐块符号片段/尾掩码逆变换核验，
构建只增加该既有规则的对照；共享派发、头文件/状态布局、其他生成代码保持冻结。
这属于已生成产物的组合实验，不声称已从当前工作区生成器全量重新生成香山。
该检查点只记录已通过的诊断，不提前宣称新组合的 walltime 收益。

#### 残余 profile 与已有逐字拼接复测完成

重新采集 cycles/branch-misses，并将八个 compute 函数用 Clang23
`-gline-tables-only` 重编译映射源码；与**实际链接 archive** 提取的对象比较，
八个函数所属对象 `.text` 均逐字节相等，不依赖可能被诊断覆盖的松散 `.o`。
p3/b46、b333 的函数内 cycles 样本分别有 77.73%/86.41% 映射到 concat；
b19/b20/b146 则有 42.70%/41.37%/31.15% 映射到变化检测或激活代码。
这是全程函数内源码归类，**不是固定瓶颈步的 stall 因果比例**。
b322/b318 有大量未映射样本，不把剩余份额强行归到某种操作。

p3/b46 在整个 p3 模型函数 cycles 样本中仅占 3.60%，b333 占 1.50%；
其余分布在其他 compute、commit 及外层 eval。因而最大单个 batch 的加速
不能等比例推导到 p3，更不能等比例推导到 Host walltime。

已有规则在此冻结基线上完整组合了 10437 个 concat（全部 32 分区），
1578 个源文件通过逐片段/尾掩码和逆变换审计，无三方合并冲突或额外合并文件；
实际链接 archive 778 个对象变化、6676 个不变。
候选 ELF SHA256：`eaa007d5015439235fc7e1186dca77ee1f940d6d2fd7841eb69c9b7c489c089c`。
18.527 s 是复用已编译对象后的组合/链接时间，不是完整生成编译时间。

两个窗口各 4 对 AB/BA，C=100000，所有正式运行及 smoke 的 Difftest/终态一致。
按各对 `(candidate / baseline - 1)` 后取中位，未剔除较慢样本：

| 指标 | baseline 绝对中位 | 已有逐字拼接绝对中位 | 配对变化中位 | 更快对数 |
|---|---:|---:|---:|---:|
| Host（s） | 16.4280 | 16.4065 | -0.428% | 6/8 |
| walltime（s） | 16.4600 | 16.4400 | -0.424% | 6/8 |
| 全局 eval（us/step） | 53.4885 | 52.8410 | -1.351% | 8/8 |
| 全局 update（us/step） | 23.5910 | 23.7485 | +0.645% | 1/8 |
| p3 eval（us/step） | 46.2525 | 44.9690 | -2.405% | 7/8 |
| p6 eval（us/step） | 38.4095 | 37.4680 | -2.553% | 8/8 |
| p10 eval（us/step） | 32.4755 | 31.9220 | -1.758% | 7/8 |
| p18 eval（us/step） | 32.5200 | 33.0085 | +1.199% | 0/8 |
| p29 eval（us/step） | 16.4685 | 16.5390 | +0.610% | 3/8 |

walltime 两个窗口分别 -0.332%/-0.486%，按顺序分组 AB/BA 为
-0.486%/-0.242%。收益是小幅正向而非显著突破，update 和 p18 的反向结果保留。

独立逐 batch 2 对 AB/BA，沿用**事前冻结的 1575 个标签**，调用次数、活跃
调用次数及 active-bit popcount 总数向量全部相同；这些计数不等同于逐次 bitmask
序列。固定 p3 标签下，b46 每 step 累计调用时间 `1.875→1.442 us`（-23.10%），
实际对象静态指令 `22566→17184`、text `132613→100864 B`、call `4→0`。
p10/b15、b17 为 -14.00%/-15.76%，p18/b18 为 -21.56%。
然而 p3/b333 为 `0.741→0.785 us`（+5.82%），它的机器码其实完全未变；
b19/b20 及 p29 三个重 batch 也有类似间接变化，不能把这些变化直接归因于
该函数指令改写，更不能仅凭此确定 cache/布局就是唯一原因。

另做低频逐步 timeline 2 对 AB/BA：固定 p3 标签的自身 eval
`45.591→43.946 us`（-3.608%），对应全局 eval `46.900→45.264 us`
（-3.489%），两步合计时间只下降 1.117%。固定 p18 标签的当前沿 eval
仅下降 0.259%，两沿自身 eval 反而 +0.435%；单个 batch 变快不代表整个分区
或同步关键路径同比例变快。诊断插桩结果不混入普通 walltime 样本。

汇总与原始证据：
[`results_summary.json`](../../build/repcut_grhsim_20260925/p3_postdispatch_20261002/results_summary.json)、
[`static_residual.json`](../../build/repcut_grhsim_20260925/p3_postdispatch_20261002/static_residual.json)、
[`profile_text_identity.json`](../../build/repcut_grhsim_20260925/p3_postdispatch_20261002/profile_text_identity.json)、
[`wordwise/stages.json`](../../build/repcut_grhsim_20260925/p3_postdispatch_20261002/wordwise/stages.json)。

#### 通用覆盖缺口：内联异步内存读

p3/b333 的主要输出拼接仍保留旧式逐片段 OR。它构造 325 个 64-bit 目标字，
操作数树包含内联 `kMemoryReadPort`，现有逐字拼接规则调用的纯表达式白名单
不接纳该操作，导致整个大拼接退出优化；该文件虽有另一小拼接进入旧规则，
编译后整个对象仍与 baseline 恒等。

实现局部修正：只在 `emitWordwiseWideConcat` 的遍历中允许异步 memory read，
继续递归检查其地址操作数，保留目标存储别名及 event 排除；不改动其他优化
共用的纯操作判定。内存读只有地址 operand 0，无写入副作用，状态内存不与
concat 值存储重叠；原有边界检查和零值语义不变。不含分区/模块/信号匹配。

新增专项覆盖 31/65/130-bit 内存、3/4 行、双读取、地址 XOR 表达式、越界
读取为零、合法地址掩码写入、同沿写后读、重复 eval 和两次 init；窄读必须
确实内联到拼接。默认/关闭/开启/perf/bitmap/helper-split 六种模式均通过。
连同原有八模式拼接和 commit-demand 专项，Clang23 回归全部通过。
`wordwise_wide_concat` 仍默认关闭，Verilator 路径不变。
此处先记录通过的规则与回归，完整香山作用域和 walltime 待后续同节追加。

#### 内存读覆盖扩展：完整结果与本轮结论

使用独立冻结的当前生成器，在同一完整 partitioned.json 上分别关闭/开启
逐字拼接，32 分区均全量生成。读入 57.374 s，off/on 生成分别
569.710/552.476 s；生成期间有回归并行，因此这些时间只作构建追踪，不作
生成器性能比较。两份输出的 7552 个源码/头文件全部检查：on/off 的差异必须
仅由可逆且位片段等价的 concat 改写组成。随后将这些**生成器实际产出的全部
改写**按精确旧/新块匹配组合到冻结 diag9/最终 all-spin 模型上，避免混入
`[&]→[this]` 等其他源码细化。没有根据 profile 手工选择分区或信号。
这是“全量生成新规则并严格组合到冻结模型”的实验，不声称完整候选 ELF
由当前源树的所有默认改动共同生成。

覆盖由 10437 增至 **10555 个 concat**，1591 个文件完成符号逆变换核验。
新增 118 个，分布为 p0=31、p1=45、p3=13、p6=22、p10=3，
p11/p13/p15/p20 各 1；其他分区仍应用既有规则，没有人工排除。
相对上一组已开启逐字拼接的候选，50 个源文件变化，实际 archive
**41 个对象改变、7413 个不变**；状态/接口布局及 wrapper 保持冻结。
增量编译链接 8.800 s，不是全模型从零编译时间。
最终候选 ELF SHA256：`e7d431bdddf35a53beecd0fcdf5c9da1f781d4edcd37984179da2aa1e6dae2da`。

正式实验依次完成：新增覆盖相对已有规则的 4 对普通 AB/BA、2 对逐 batch
诊断、2 对低频 timeline、第二批 4 对普通 AB/BA，最后再与未开启逐字拼接
的本节原始冻结基线做 4 对普通 AB/BA。配置均为 node030 CPU96–127、
NUMA1、N=K=32、all-spin、Clang23/O3、C=100000；32 次正式 Difftest
及 10 次 smoke 全部通过。正式终态均为 PC `0x80000c0c`、指令
240349、cycles 99996、guest_cycles 100001、steps 200102。
全部正确性通过的样本均保留，不因性能回退删样。

| 对照与指标 | baseline 绝对中位 | candidate 绝对中位 | 配对变化中位 | 更快对数 |
|---|---:|---:|---:|---:|
| 新增覆盖 vs 已有规则：Host（s） | 16.2925 | 16.2385 | -0.598% | 6/8 |
| 同上：walltime（s） | 16.3250 | 16.2700 | -0.581% | 6/8 |
| 同上：全局 eval（us/step） | 52.2950 | 52.4595 | -0.129% | 5/8 |
| 同上：全局 update（us/step） | 23.9025 | 23.5525 | -0.904% | 7/8 |
| 完整候选 vs 未开启拼接：Host（s） | 16.3085 | 16.2030 | -0.594% | 4/4 |
| 同上：walltime（s） | 16.3450 | 16.2400 | -0.581% | 4/4 |
| 同上：全局 eval（us/step） | 52.8985 | 52.5245 | -0.682% | 4/4 |
| 同上：全局 update（us/step） | 23.4820 | 23.3760 | -0.451% | 3/4 |

“绝对中位数相除”不等于“每对求变化后取中位数”；例如新增覆盖的 eval
绝对中位略增、配对变化却略减，两者均原样列出。也**不能**把前一节
-0.424% 与本节新增覆盖 -0.581% 相加为总收益；不同窗口基线状态不同，
总收益以直接对原始基线的 4 对数据为准。新增覆盖两窗口 walltime 分别
-0.581%/-0.431%，AB/BA 分组分别 -0.974%/-0.153%，顺序敏感性仍明显。

新增覆盖相对已有规则的普通各分区 eval 配对变化：p3 **-0.009%（4/8）**、
p6 -0.679%（8/8）、p10 -0.071%（4/8）、p18 -2.135%（8/8）、
p29 **+1.596%（0/8）**。最终直接对未开启拼接的原始基线，p3 为
**+0.374%（1/4）**，p18 +1.011%（1/4）；不能声称解决了 p3 平均 eval
瓶颈。p18/p29 及 update 的有关函数机器码并未因本次扩展改变，测到的
间接变化不能冒充这些函数的局部代码收益，也尚未归因于某个确定的缓存/
频率/布局机制。

局部证据方面，实际 archive 的 p3/b333 静态指令 `10046→9650`
（-3.94%）、text `50848→46241 B`（-9.06%）、栈引用 `592→485`、
call `1→0`。固定 p3 标签的逐 batch 时间 `0.800→0.683 us`（-14.59%）；
调用/活跃调用/popcount 总数向量一致。与此同时，机器码不变的 p3/b46
也变化 -3.40%，p18/b18 变化 -19.37%，因此 14.59% 不是剥离了所有间接
影响后的纯因果收益，更不是 walltime 预测。

低频 timeline 同一固定 p3 标签下，p3 自身 eval `43.577→43.295 us`
（-0.648%），对应全局 eval `45.083→44.756 us`（-0.724%），两沿 p3
eval 合计 -0.601%，两步总时间 -0.450%。整个 timeline 的 p3 最后完成
次数仍为 `1928→1991 / 6300`，没有退出主要瓶颈位置。

默认/开启完整 GrhSIM 回归、两种后端 package 回归、扩展后的拼接专项、
commit-demand 专项均通过；独立 UBSan harness 通过。源码、测试和后端说明
已更新；模型实验选项默认值未改变，本轮不提交。完整数据见
[`wordwise_memory/results_summary.json`](../../build/repcut_grhsim_20260925/p3_postdispatch_20261002/wordwise_memory/results_summary.json)、
[`source_audit.json`](../../build/repcut_grhsim_20260925/p3_postdispatch_20261002/wordwise_memory/source_audit.json)、
[`static_residual.json`](../../build/repcut_grhsim_20260925/p3_postdispatch_20261002/wordwise_memory/static_residual.json)、
[`stages.json`](../../build/repcut_grhsim_20260925/p3_postdispatch_20261002/wordwise_memory/stages.json)。

**结论与下一优先级：**已补齐通用覆盖缺口，得到小幅 walltime 正向结果，
但不是 p3 的突破性优化，不据此将逐字拼接升为默认。下一步应转向 p3
广泛分布的**变化检测及激活传播**：一次值变化可能需要累积多个 group 的
changed 标志，再单独 OR 某些 active 字；b19/b20/b146 的源码采样已提供
具体证据。需先复查已有 deferred-activation 分组/字累积的覆盖和成本，
再考虑在同一 supernode 内把相同目标激活字的重复更新合并；保持精确激活、
事件语义和固定点轮数不变，不以扩大重算量换表面代码缩短。

收尾再次运行专项与 UBSan，全部通过，见
[`final_checks.json`](../../build/repcut_grhsim_20260925/p3_postdispatch_20261002/wordwise_memory/final_checks.json)。
生成器源码/动态库哈希仍与本次生成快照一致，根仓库与子模块 `git diff --check`
通过。本轮构建、诊断与正式测试均已结束，无遗留实验后台任务。

### 7.31 p3 分布式变化传播：精确 group 标志打包（2026-10-02）

本轮沿 §7.30 的下一步开展。**baseline 固定为该节最终的
`wordwise_memory` 候选**（ELF `e7d431bd…`），不是未开启宽拼接的原始版本。
配置保持 node030 CPU96–127、NUMA1、N=K=32、all-spin、Clang23/O3、
C=100000。普通 walltime 预定分两个窗口各做 4 对 AB/BA，期间另做逐 batch
与低频 timeline 诊断；诊断样本不并入普通时间。

#### 机制、候选及正确性检查

复查发现现有 deferred-activation 已按“完全相同的源值集合”合并下游目标，
且最多保留 16 组，因此不是完全没有分组。同一个源值却可能属于多个不同组，
变化后仍需逐一 OR 多个 Boolean 标志。源码普查中，p3 有 7814 个组、49193
条组标志更新；b19/b20 的若干 supernode 平均每个源变化更新约 2–3 个组。
这些是静态源码数量，不是每 step 的执行次数或 PMU 指令数。

实现通用 `packed_deferred_activation` / `WOLVRIX_GRHSIM_PACKED_DEFERRED_ACTIVATION`
实验选项，默认关闭，attribute 优先。满足“至少 4 组且平均每个源属于至少
2 组”的结构，改为每组占 `uint32_t` 的独立 bit，一次 OR 同时累计该源所
影响的多组标志；flush 时恢复每组原来的布尔判定。组成员、目标集合、直接
剩余目标、事件及固定点语义保持不变。不匹配分区/模块/信号名称，不扩大重算。
门槛只减少明显不利的低重叠情况，**不预设会提高性能**：单个掩码也可能引入
更长的依赖链或位提取成本。

新增专项已通过 default/off/on/environment/attribute-precedence/perf/bitmap/
supernode-union/helper-split 共 9 模式，包括第 15 bit、稀疏重叠不打包的对照、
打包组之外的直接目标、多 active 字的聚合 flush、随机输入、重复 eval 和
两次 init。默认、显式关闭及 attribute 覆盖环境变量的生成代码逐字节相同。
接下来全 32 分区生成 off/on，核对所有差异都属于逐 bit 等价的 OR 改写，再
组合到冻结 commit-demand/all-spin 模型，排除其他源码改动混入对照。

本节工作产物位于
[`p3_activation_packed_20261002`](../../build/repcut_grhsim_20260925/p3_activation_packed_20261002/)，
静态普查见 [`scan.json`](../../build/repcut_grhsim_20260925/p3_activation_packed_20261002/scan.json)。
此处只记录实现与通过的专项，性能结论待正式实验完成后在本节追加。

#### 完整验证与性能结论

同一冻结生成器全量生成 32 分区 off/on，读入 59.431 s，生成分别
572.941/548.470 s；期间存在并行回归，不用于比较生成器速度。7552 个源码/
头文件全部核验，**off 与修改前的全量生成结果逐字节相同**。on 的全部差异
都可由“独立 Boolean 对应独立 bit、同条件 OR 合并、读取还原为 bit 测试”
精确重现；变化条件只允许不可变 `grhsim_changed_*` 或 Boolean 常量。
这些受改写的原始行也与冻结 commit-demand/all-spin 基线一致，因而可以组合
全部改写而不混入其他 emitter 细化；并非手工挑分区开启。

实际覆盖全部 32 分区的 3851 个 supernode、40486 个组；受覆盖部分的
Boolean 更新 `378587→144526`（-61.82%），不代表全模型动态指令减少同样
比例。p3 覆盖 239 个 supernode、2648 个组，相关更新 `20756→8162`。
1651 个源文件及实际链接对象改变，其余 **5803 个 archive 对象逐字节不变**；
模型布局、通信和 wrapper 不变。增量编译链接 57.877 s，不是全模型从零编译。
候选 ELF SHA256：`ffe6aad6c02cfdedef585f63b144301e19bde705de5d0975f1de83c385f1217b`。

两窗口共 8 对普通 AB/BA、2 对逐 batch 诊断、2 对低频 timeline 全部完成。
**24 次 C=100000 正式 Difftest 和 8 次 smoke 全部通过**；正式终态统一为
PC `0x80000c0c`、instructions 240349、cycles 99996、guest_cycles 100001、
steps 200102。没有删除正确性通过但性能不利的样本。

| 普通测量指标 | baseline 绝对中位 | candidate 绝对中位 | 配对变化中位 | 更快对数 |
|---|---:|---:|---:|---:|
| Host（s） | 16.3860 | 16.4305 | +0.064% | 3/8 |
| walltime（s） | 16.4200 | 16.4650 | **+0.091%** | **3/8** |
| 全局 eval（us/step） | 52.9025 | 53.1405 | +0.453% | 2/8 |
| 全局 update（us/step） | 23.7655 | 23.8350 | -0.086% | 4/8 |
| p3 eval（us/step） | 45.0000 | 45.0065 | +0.072% | 3/8 |

变化列仍为每对 `candidate/baseline-1` 后取中位，不是绝对中位数相除。
两个窗口 walltime 分别 +0.213%/-0.061%，AB/BA 分别 +0.459%/-0.061%；
**没有稳定 walltime 收益**，也不能把 +0.091% 解读为精确而显著的退化量。
其他重点分区 eval：p6 +0.302%（2/8）、p10 -0.383%（5/8）、
p18 +0.833%（2/8）、p29 +0.638%（0/8）。

局部代码解释了“源码 OR 更少”为什么不等于更便宜。以下数字来自实际链接
archive 的反汇编，不使用早期预览对象替代最终对象：

| p3 热点 | 静态指令数 | text（B） | 栈引用 | 固定标签下 batch 时间（us/step） |
|---|---:|---:|---:|---:|
| b19 | 5977→6255（+4.65%） | 28698→30448 | 1414→1352 | 0.6662→0.6980（+4.76%） |
| b20 | 6690→7093（+6.02%） | 31354→34020 | 1568→1506 | 0.6668→0.6799（+1.96%） |

b19 的 OR 少 253 条，却新增 320 条 `mov`、201 条 `cmove`；b20 的 OR
少 336 条，却新增 456 条 `mov`、313 条 `cmove`，还增加掩码/移位处理。
栈引用各少 62 次，分支数不变。这里是**静态代码构成**，不是实际退休指令
或 PMU stall 占比；只能说明打包引入了实在的生成代价，不能把全部时间差
唯一归因于某一种指令。b146 未达到重叠门槛，实际对象保持不变。

逐 batch 诊断沿用事前冻结的 1575 个标签，调用/活跃调用/active-bit popcount
总数向量完全相同；不等于逐次完整 bitmask 序列证明。与此同时，未改机器码
的 p3/b322 也测到 -8.31%、p10/b15 -6.64%、p18/b18 +10.41% 等变化，
这些只能列作间接变化或测量波动，不能冒充这些函数的直接改写收益。

反方向证据同样保留：独立低频 timeline 的固定 p3 标签下，自身 eval
`43.738→42.613 us`（-2.574%），对应全局 eval `45.560→44.773 us`
（-1.727%），两沿 p3 eval 合计 -2.815%，但两步总时间仅 -0.716%，
update 阶段 +1.026%。整个 timeline 的 p3 最后完成次数为
`1874→1738 / 6300`。这些是抽样、插桩和独立窗口中的结果，与普通全程
walltime 的口径不同；不能用其中的 -2.574% 宣称普通仿真提速，现有数据
也不足以将差异确定归因于缓存、布局或频率中的某一个因素。

**结论：保留为默认关闭的实验选项，不进入默认验证线。**这轮证明了表示
变换正确，但没有证明性能收益。下一步不应继续以“减少中间 flag 数量”为
目标，而应检查能否直接按最终 active 字累计变化，在目标较集中时省掉
`Boolean → group mask → Boolean → active mask` 的中间转换，并减少真正的
重复读改写。已有 deferred flush 已做部分按字聚合，必须先复查其覆盖；新
方案需以最终更新数和同时存活的临时量设通用门槛，不能按 p3/b19 等名称
筛选，也不能扩大激活集合。这是后续候选方向，本轮尚未实现或证明收益。

默认/开启完整 GrhSIM 回归、两种后端 package 回归、9 模式专项及 UBSan
全部通过。源码及生成器动态库哈希保持与冻结快照一致；Verilator 路径不变，
本轮未提交。完整数据与构建、检查记录：
[`results_summary.json`](../../build/repcut_grhsim_20260925/p3_activation_packed_20261002/results_summary.json)、
[`source_audit.json`](../../build/repcut_grhsim_20260925/p3_activation_packed_20261002/source_audit.json)、
[`static_residual.json`](../../build/repcut_grhsim_20260925/p3_activation_packed_20261002/static_residual.json)、
[`instruction_mix.json`](../../build/repcut_grhsim_20260925/p3_activation_packed_20261002/instruction_mix.json)、
[`stages.json`](../../build/repcut_grhsim_20260925/p3_activation_packed_20261002/stages.json)、
[`final_checks.json`](../../build/repcut_grhsim_20260925/p3_activation_packed_20261002/final_checks.json)。

### 7.32 直接累计最终激活掩码（2026-10-02）

沿 §7.31 的结论继续，但**不以该节无收益的 packed 候选为 baseline**：仍使用
§7.30 最终 `wordwise_memory`，ELF `e7d431bd…`。本轮仅开启新增的
`direct_deferred_activation`，上一轮 `packed_deferred_activation` 保持关闭。
node030 CPU96–127、NUMA1、N=K=32、all-spin、Clang23/O3、C=100000
不变，预定两窗口共 8 对普通 AB/BA，中间独立逐 batch 和低频 timeline 诊断。

#### 规则和通过的专项检查

已有 deferred flush 会在静态代价门槛满足时按 active 字聚合，但此前仍先
累计每个组的 Boolean，最终才形成目标掩码。新候选在**目标集中、源值重叠**
时直接累计最终 bit，省掉“组编号编码→解码→目标编码”。并非完全新增一个
此前不存在的按字聚合机制，也不合并所有组或所有目标。

筛选以结构为准：完整组的目标必须都位于同一个对齐 8-byte 激活区间，或
都属于当前局部字的前向目标；同区间至少 3 组，源成员总数至少为源值并集
大小的 2 倍。每 supernode 最多 4 个直接累加器，宽度取覆盖目标所需的
1/2/4/8 byte，访问必须在真实活动数组边界内，空洞位为零。局部/全局分开，
未覆盖组及直接目标保留原路径；不按模块、分区、信号或热点名称挑选。
默认关闭，与旧 packed 同开时，存在直接累加器的 supernode 优先走本规则。

两种模式的专项共 20 个生成/Clang23 执行配置通过，其中新增候选覆盖
default/off/on/environment/attribute-precedence/perf/batch-profile/bitmap/
supernode-union/helper-split。检查局部前向与全局同时存在、剩余多区间组、
低重叠不匹配、空洞、bit63、恰好到数组末尾、随机变化、重复 eval 和两次
init。默认/显式关闭/attribute 优先的输出逐字节相同，独立 UBSan 也通过。

全量生成后使用 AST/位符号核验：将每个最终激活 bit 展开成“位于哪个原始
执行位置、满足哪个变化条件”的 OR 集合，要求新旧完全一致，并要求其他
计算和 guard 的源码骨架逐字节一致。与只比较活跃位总数不同，这能检查
目标位或条件被替换的问题。经核验的全部生成改写再组合到冻结模型，以避免
混入其他 emitter 细化。完整结果在本节追加；此处不预判性能收益。

产物目录：
[`p3_activation_direct_20261002`](../../build/repcut_grhsim_20260925/p3_activation_direct_20261002/)。

#### 第一轮完整结果：直接掩码未取得稳定 walltime 收益

全量 off/on 生成的 7552 个文件核验通过，关闭选项时逐字节等于原基线的
生成结果。命中 31 个分区（p28 不匹配）、980 个 supernode、5196 个原组，
构成 1036 个直接累加器；56037 条原 Boolean 更新变为 24052 条直接掩码
更新。645 个源文件改写，实际 archive 中 644 个对象变化、6810 个不变。
冻结模型上再次通过精确目标/条件 OR 核验，未改模型布局、分区、通信及 wrapper。
增量编译 26.717 s；候选 ELF `211288e8…`，archive `a10d64da…`。

两窗口共 8 对普通 AB/BA、2 对固定标签 batch 诊断、2 对 timeline 诊断全部
完成：24 次正式 C=100000 和 8 次 smoke 均通过 Difftest。默认/开启和两后端
package 回归、专项、UBSan、ASan+UBSan 通过；compute call、active call、
popcount 向量完全一致。下表百分比是每对 `(candidate / baseline - 1)` 的
中位数，并非两列绝对时间中位数之比；负数表示更快。

| 普通运行指标 | baseline 中位数 | 直接掩码中位数 | 配对变化 | 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| walltime | 16.425 s | 16.455 s | +0.061% | 4/8 |
| Host | 16.3885 s | 16.4215 s | +0.067% | 4/8 |
| 全局 eval/step | 52.812 µs | 52.995 µs | +0.300% | 2/8 |
| 全局 update/step | 23.8915 µs | 23.8830 µs | −0.615% | 5/8 |
| p3 eval/step | 45.2355 µs | 44.4135 µs | −1.870% | 8/8 |
| p18 eval/step | 31.9695 µs | 32.9870 µs | +3.193% | 0/8 |

两个普通窗口的 walltime 分别 −0.183%（3/4）和 +0.334%（1/4），因此不能
把 p3 的改善解释成整体加速。独立固定 p3 标签 timeline 中，p3 自身 eval
44.312→44.110 µs（−0.456%），对应全局阶段 −0.658%，两沿合计 step
−0.335%；这是诊断子集，不与普通运行混算。

**p18 的退步有明确的局部代码线索。** 固定原有瓶颈标签下，b195 从
0.79194→1.05964 µs（+33.80%），b210 从 0.69254→0.87375 µs（+26.17%）。
对实际链接 archive 的反汇编，二者静态指令分别 5623→6763（+20.27%）、
5017→6011（+19.81%）；涉及栈寻址的指令数分别 1418→2227、1125→1520。
b195 增加 264 条 `cmove`、263 条 `cmp`，而 `xor` 减少 262 条；这符合
原先 Boolean/XOR 归约变成逐源生成整数掩码后，条件选择和寄存器压力增加。
这里的静态数不是 retired instructions，也不能单凭它认定某类 stall。
p3/b19、b20 的静态指令 5977→5966、6690→6690，固定标签耗时却分别
+0.65%、+2.25%，亦未证实这两个预期热点得到局部加速。

其他未改写对象也存在正负变化，例如 p18/b179 +6.56%、p3/b46 −9.04%；
这些可能来自布局、缓存或运行波动，不能作为规则直接优化该函数的证据。
第一轮保持实验性关闭，不提升为默认。

证据：
[`results_summary.json`](../../build/repcut_grhsim_20260925/p3_activation_direct_20261002/results_summary.json)、
[`source_audit.json`](../../build/repcut_grhsim_20260925/p3_activation_direct_20261002/source_audit.json)、
[`instruction_mix.json`](../../build/repcut_grhsim_20260925/p3_activation_direct_20261002/instruction_mix.json)、
[`stages.json`](../../build/repcut_grhsim_20260925/p3_activation_direct_20261002/stages.json)。

#### 第二轮：相同最终掩码的源条件先合并

继续沿上述机器码线索改进同一通用规则，不按 p18 或 batch 名称排除。
在每个直接累加器内，先按源值的**完整最终目标掩码**归类；至少两个源值
共享同一掩码时，先把这些源的变化 OR 到一个 Boolean，再在原 flush 位置
只展开一次掩码。每个累加器最多选择 `min(4, 原组数−1)` 类，优先选择
重复源更多的类别、以掩码打破平局；其他源仍走第一轮直接路径。相同目标
集合之外不合并，保留原 guard 与每次变化检测的位置。

直观上，第一轮为 200 个变化条件各生成一次相同的目标掩码，第二轮先判断
这 200 个条件中是否有变化，再生成一次掩码。它尝试恢复便宜的 Boolean
归约，同时避免基线对同一源反复更新多个目标组。专项新增成对源值具有
相同目标集、64-bit 空洞和 bit63 的情况；完整 off/on 核验、两窗口 8 对
AB/BA 和固定标签诊断仍按原协议执行，不预判收益。产物：
[`p3_activation_cohort_20261002`](../../build/repcut_grhsim_20260925/p3_activation_cohort_20261002/)。

#### 第二轮完整结果：修复大部分局部退步，仍无整体加速

全量 off/on 的 7552 个文件及冻结模型组合再次通过核验，默认输出保持不变。
规则覆盖与第一轮相同，仍是 31 个分区、980 个 supernode、5196 个原组、
1036 个直接累加器。本轮加入 2661 个同目标源组，保留 5044 次逐源掩码更新，
将另 19008 次更新改为 Boolean 合并、最后展开 2661 次；合计掩码展开
**24052→7705**，约减少 68%。这只是生成代码的静态条数，不是执行频次或
机器指令数。p3 为 881→224，p18 为 2551→828。

645 个源文件改写，实际链接 archive 的 643 个对象变化、6811 个不变。
增量编译 26.759 s（不是完整 clean build）；候选 ELF `de2903f6…`，archive
`68172af6…`。生成器和核心源码身份已冻结核对。默认/开启、两个后端 package、
两套专项共 20 个模式、UBSan、ASan+UBSan 全部通过；位符号核验的正例及
8 种故意改错源条件、目标位、flush 或计算的反例也通过。运行协议完整执行：
8 对普通 AB/BA、2 对 batch、2 对 timeline，共 24 次正式 C=100000 和
8 次 smoke 均通过 Difftest，compute call/active call/popcount 向量相同。

下面各百分比仍为**同窗口、同一固定 baseline 版本的配对变化中位数**。
两轮的绝对时间受测试窗口影响，不能直接用第一轮与第二轮的绝对时间相除，
也不能将两轮相对 baseline 的百分比相加。

| 普通运行指标 | baseline 中位数 | 同目标源合并中位数 | 配对变化 | 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| walltime | 16.355 s | 16.385 s | +0.274% | 3/8 |
| Host | 16.3240 s | 16.3485 s | +0.284% | 3/8 |
| 全局 eval/step | 52.845 µs | 52.885 µs | +0.195% | 3/8 |
| 全局 update/step | 23.535 µs | 23.694 µs | +0.468% | 3/8 |
| p3 eval/step | 45.0375 µs | 44.5275 µs | −0.885% | 7/8 |
| p6 eval/step | 37.4645 µs | 37.2340 µs | −0.633% | 6/8 |
| p10 eval/step | 32.8755 µs | 32.9010 µs | +0.382% | 3/8 |
| p18 eval/step | 31.8990 µs | 32.4015 µs | +1.631% | 0/8 |
| p29 eval/step | 16.2655 µs | 16.2470 µs | −0.606% | 5/8 |

两个普通窗口 walltime 分别 +0.154%（2/4 更快）、+0.274%（1/4）；按顺序
分层 AB +0.277%、BA +0.274%，均没有显示整体获益。不能因为 p3 平均 eval
下降，或者某个诊断子集变快，就据此启用默认。

**p18 的主要机器码膨胀确实消除了，但并非所有代码形态都恢复。**
b195 的 540 条原组更新，第一轮变成 270 次掩码展开，第二轮变成 270 次
Boolean 合并、2 次展开；b210 相应为 576→288 次展开→288 次 Boolean
合并和 2 次展开。下面机器码计数取自实际链接 archive，而非预览对象。

| batch | 基线静态指令 | 第一轮直接展开 | 第二轮同目标合并 | 基线/第二轮栈寻址指令 | 第二轮固定标签耗时 |
| --- | ---: | ---: | ---: | ---: | ---: |
| p18/b195 | 5623 | 6763 | 5616 | 1418 / 1407 | 0.80533→0.76548 µs（−4.95%） |
| p18/b210 | 5017 | 6011 | 5020 | 1125 / 1138 | 0.67661→0.69894 µs（+3.30%） |
| p3/b19 | 5977 | 5966 | 5997 | 1414 / 1427 | 0.67897→0.68172 µs（+0.40%） |
| p3/b20 | 6690 | 6690 | 6673 | 1568 / 1549 | 0.65079→0.65952 µs（+1.34%） |

b210 的条件跳转仍是 22→38，增加 16 条 `cmp`、15 条 `jne`，而 `xor`
减少 15 条。总指令数接近并不意味着分支形态、依赖链或运行成本完全相同；
不能据此称 b210 已完全恢复，也尚不能把 +3.30% 全部归因为分支预测失败，
后者需要对应路径的动态证据。p3/b19、b20 也再次说明：源代码归约大幅简化，
并没有转化成这些 batch 的明显机器码压缩或耗时下降。

**独立固定标签诊断的方向不能替代普通 walltime。** p3 的 980 个历史固定
样本中，p3 自身 eval 44.019→43.210 µs（−1.839%），全局 eval 阶段
46.519→44.996 µs（−3.274%），两沿合计 step 149.865→147.170 µs
（−1.798%），最后完成次数 911→881。其他历史固定样本则不同：p18 自身
eval +0.277%、全局阶段 +0.068%；p29 自身 +3.358%、阶段 +3.291%，
即使普通运行的 p29 平均 eval 略降，其瓶颈样本仍可能变慢。
这只能说明获益分布不均，不能把所有普通 walltime 差异唯一归因于某个分区。
update 未被本规则直接改写，其 +0.468% 也不能解释为新增了 update 工作量。

本轮结论：**不将 `direct_deferred_activation` 提升为默认**，保留默认关闭的
通用实验选项；未改原有 Verilator 路径，也未采用模块、分区或信号名筛选。
已经验证了“相同最终掩码先合并”能避免第一轮的严重局部膨胀，但尚未验证
这条直接掩码路线能改善最终 walltime。后续优先级应从继续压缩源码更新条数，
转回实际瓶颈路径的机器码形态：尤其区分 Boolean 归约与条件分支选择、
状态读取/变化检测和剩余掩码处理。b210 保留的条件跳转变化可作为下一次
有针对性的诊断入口，而不是直接增加新的按分区筛选门槛。

证据：
[`results_summary.json`](../../build/repcut_grhsim_20260925/p3_activation_cohort_20261002/results_summary.json)、
[`source_audit.json`](../../build/repcut_grhsim_20260925/p3_activation_cohort_20261002/source_audit.json)、
[`instruction_mix.json`](../../build/repcut_grhsim_20260925/p3_activation_cohort_20261002/instruction_mix.json)、
[`stages.json`](../../build/repcut_grhsim_20260925/p3_activation_cohort_20261002/stages.json)、
[`audit_checks.json`](../../build/repcut_grhsim_20260925/p3_activation_cohort_20261002/audit_checks.json)、
[`final_checks.json`](../../build/repcut_grhsim_20260925/p3_activation_cohort_20261002/final_checks.json)、
[`asan_checks.json`](../../build/repcut_grhsim_20260925/p3_activation_cohort_20261002/asan_checks.json)。

### 7.33 b210 宽值变化检测分支归因与 XOR 归约（2026-10-02）

#### 新增跳转实际来自哪里

接续 §7.32，但性能候选仍从已验证的 §7.30 `wordwise_memory` 基线出发，
不叠加没有整体收益的直接掩码/同目标合并。先比较该基线与 §7.32 第二轮，
分别用 Clang23/O3 加 `-gline-tables-only` 重编译 p18/b195、b210 和 p3/b19，
六个对象的 `.text` 均与实际 archive 逐字节相同，再用函数偏移映射源码。

b210 增加的 16 条条件跳转集中在同一处：一个 1024-bit `kOr` 结果经
`grhsim_assign_words_full<16>` 写入物化槽，然后决定是否激活下游。
函数做的是 16 个 64-bit 字的赋值与变化检测，并不是 16 个新增逻辑条件或
额外的 RTL 工作。基线该处没有比较跳转链，第二轮则出现 15 个 `jne` 和
1 个 `je` 的逐字比较/提前退出形态。C++ helper 本来就用 Boolean bitwise
OR 而非 `||`；因此不能简单把问题说成 emitter 写了短路逻辑，或认为已有
bool-eager 开关必然能解决。其附近代码变化影响了 Clang 的最终指令选择。

随后仅在外层 eval 调用处对 p18/b96、b179、b195、b210 加线程本地 PMU，
不改这些 batch 的机器码。每 127 step 采样，C=100000 两对 AB/BA，历史
瓶颈标签固定使用 §7.30 的独立标签。每个变体固定 p18 样本共 432 个；
计数器 pinned、running/enabled 全为 1，Difftest 和调用/活跃计数一致。
另测空载 probe，不从结果中机械扣除；PMU 区间包含固定读数/时钟代码，
不能作为普通 walltime，也不能把 cycles 与不含系统调用的短区间计时直接
相除当作有效频率。

| b210 固定瓶颈样本，每 step 累计 | 基线 | 同目标合并候选 | 变化 |
| --- | ---: | ---: | ---: |
| batch 调用数 | 1.99537 | 1.99537 | 相同 |
| 动态指令（含 probe 固定开销） | 5230.74 | 5222.82 | −0.151% |
| 动态分支 | 147.46 | 159.24 | +11.78 次 / +7.987% |
| 分支预测失败 | 9.838 | 10.722 | +0.884 次 / +8.988% |
| cycles | 2862.98 | 2853.26 | −0.339% |
| 调用区间计时 | 0.68719 µs | 0.68750 µs | +0.046% |

空载 probe 每次约 269 instructions、57 branches、2 misses、24.5–24.9 ns；
其调用次数为每采样 step 一次，不能与上述近两次 batch 调用直接相减。
未修改机器码的 b179 在该诊断中计时也 +4.09%、cycles +3.35%，而动态指令
基本不变，提示布局、缓存、相位和 probe 扰动仍需留意。**新增跳转是实情，
但本轮动态结果不支持将 §7.32 的全部退步归因为这条链的错分支**。
这些是独立诊断样本，不与上一节逐 batch 的 +3.30% 混算。

#### 通用候选及验证范围

新增实验选项 `wide_assign_xor` / `WOLVRIX_GRHSIM_WIDE_ASSIGN_XOR`，默认关闭。
仅把完整字数组赋值 helper 的 Boolean 差异归约替换为 uint64 XOR/OR
归约：`difference |= dst[i] ^ next`，保留每字读取/写回次序，最终返回
`difference != 0`。不改变其他截断/补零 helper，不改变精确激活集合、
固定点、模型状态布局、RTL 或 Verilator；没有分区/信号/宽度名单筛选。

专项 default/off/on/environment/attribute-precedence 通过；覆盖 N=0、1、
2、3、4、8、16、17、33，随机稠密和稀疏变化、bit63、相同输入重复赋值、
同数组别名以及生成模型重复 eval。默认/关闭/优先级结果逐文件相同，
开启选项时模型计算源文件不变。还将执行默认/开启及两后端 package 回归、
UBSan、ASan+UBSan 和完整普通/诊断对比。

本次不重复读取巨大的 IR：从实际 emitter 专项 off/on 的 runtime 中提取
唯一 helper 差异，核对为上述三处等价替换，再应用到冻结模型的全部 32 个
runtime header。所有计算、布局和 wrapper 源码保持不变；扫描全部 header
确认不存在间接调用或其他 helper 使用，再重编译所有直接调用它的 397 个
翻译单元，共 1538 个调用点、30 个有调用的分区。非调用者使用冻结原对象，
实际 archive 377 个对象改变、7077 个保持不变。增量编译 23.130 s，ELF
`4b961e94…`，archive `58b4fa2f…`。这是受控 helper 替换/依赖重编译，
不是一次完整的 IR 重新生成或 clean build。

早期机器码检查：p18/b195 指令 5623→5555、栈寻址指令 1418→1362；
b179 4526→4460、1128→1068；但 b210 5017→5043、条件跳转 22→38，
Clang 再次生成了比较跳转链。**XOR 形式不保证机器级无分支**。完整性能
测试继续按两个窗口 8 对普通 AB/BA、两对固定标签 batch、两对 timeline
执行，基线仍为 `wordwise_memory`，不会用修复失败候选来放大收益。

诊断与候选产物集中于
[`p18_change_branches_20261002`](../../build/repcut_grhsim_20260925/p18_change_branches_20261002/)，
源码映射见 [`code_map.json`](../../build/repcut_grhsim_20260925/p18_change_branches_20261002/code_map.json)，
条件 PMU 见 [`pmu_results.json`](../../build/repcut_grhsim_20260925/p18_change_branches_20261002/pmu_results.json)。

范围数字更正：上述“30 个有调用的分区”应为 **29 个**；以
`source_audit.json.parts` 为准，p15、p28、p29 没有该 helper 的直接调用。
32 个 runtime header 仍全部统一修改，不按分区名筛选。

#### 完整结果与决策

两窗口 8 对普通 AB/BA、两对固定标签 batch、两对 timeline 均已完成，
24 次正式 C=100000、8 次 smoke 通过 Difftest；默认/开启 emitter、
GrhSIM/Verilator package 回归及 UBSan、ASan+UBSan 全部通过。
普通测试之后另做两对 XOR 候选的局部 PMU，对照仍使用同一冻结基线，
4 次正式 C=100000、2 次 smoke 均通过，所有 PMU running/enabled=1。
加上本节开头针对旧 cohort 候选的归因，本节合计 32 次正式运行、12 次
smoke；没有将插桩运行并入普通 walltime 样本。源码、二进制及输入身份
核对通过，调用/活跃次数与原基线相同。

配置保持 node030 CPU96–127、NUMA1、N=K=32、all-spin、Clang23/O3、
ASLR off。下表百分比为 8 个同窗口配对 `(candidate / baseline - 1)` 的
中位数，负数表示更快，不是绝对时间中位数之比。

| 普通运行指标 | wordwise_memory 基线中位数 | XOR 候选中位数 | 配对变化 | 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| walltime | 16.435 s | 16.510 s | +0.426% | 1/8 |
| Host | 16.403 s | 16.473 s | +0.436% | 1/8 |
| 全局 eval/step | 52.858 µs | 53.215 µs | +0.605% | 0/8 |
| 全局 update/step | 23.933 µs | 23.842 µs | −0.242% | 6/8 |
| p3 eval/step | 45.2005 µs | 44.8065 µs | −0.760% | 6/8 |
| p6 eval/step | 37.5095 µs | 37.7365 µs | +0.636% | 1/8 |
| p10 eval/step | 32.7920 µs | 33.1600 µs | +0.868% | 2/8 |
| p18 eval/step | 31.8730 µs | 32.1575 µs | +0.836% | 0/8 |
| p29 eval/step | 16.2490 µs | 16.4035 µs | +0.911% | 2/8 |

两个普通窗口 walltime 分别 +0.457%（1/4 更快）、+0.334%（0/4）；
AB 顺序 +0.426%、BA +0.396%，未显示整体收益。p29 没有该 helper 的
直接调用、相应模型对象未替换，因此不能将其退化解释为新增了 XOR 工作。
未直接改写的 update、输入应用等阶段也有波动，布局、缓存/预测状态和
线程相位的间接影响尚未完全分离。

固定历史标签的逐 batch 计时中，p18/b195 为 0.79938→0.78626 µs
（−1.640%）、b179 为 0.59513→0.58982 µs（−0.893%），b210 为
0.67584→0.69858 µs（+3.363%）。机器码未改的 b96 为 +0.164%。
这与静态代码显示的局部得失大体一致，但不能据此推导整体加速。

后续独立 PMU 采样仍使用 432 个固定 p18 瓶颈样本，以下为每 step 累计值
（平均约 1.995 次调用），包含固定 probe 开销，不作机械扣除：

| batch | 动态 instructions 基线→XOR | cycles 变化 | branch misses 基线→XOR | PMU 中的调用计时变化 |
| --- | ---: | ---: | ---: | ---: |
| b179 | 4634.32→4568.31（−1.424%） | +0.641% | 8.789→9.185 | +0.062% |
| b195 | 5609.92→5544.60（−1.164%） | +0.460% | 12.222→12.688 | +5.626% |
| b210 | 5230.85→5243.81（+0.248%） | +0.522% | 9.581→11.850 | −0.120% |

b210 动态分支 147.48→159.23（+7.964%），说明仅改为 XOR 未消除
动态分支增加；但 cycles 只 +0.52%，且短区间计时基本持平，不能用
错分支百分比直接解释普通版的全部退化。b195 的动态指令减少得到确认，
然而 PMU cycles 未下降，计时方向又与独立逐 batch 探针相反，因此不认定
其具有稳定局部加速。未改机器码的 b96 在该 PMU 运行里也出现 miss
14.611→17.206、cycles +4.224%，再次说明需要区分代码直接变化与运行
环境/布局/探针上下文，而不是把所有计数差异都归因于 helper。

独立 timeline 中，固定 p3 的 980 个历史样本自身 eval 为
43.666→42.303 µs（−3.122%），全局 eval 阶段 −2.610%，两沿 step
−1.042%；固定 p18 的自身 eval −0.805%、两沿 step −0.188%。这些
子集改善同样没有转化为普通 walltime 优势，完整保留，不混入最终收益。

本轮结论：**`wide_assign_xor` 保持默认关闭，不作为新的有效探索基线**，
原 `wordwise_memory` 和 Verilator 路径不变。已定位 b210 新增分支的
具体来源，并排除“改写为 XOR 就能确保无分支”的假设。下一项更有针对性
的机制验证应检查变化结果的**使用方式**：当前宽值 helper 返回值仍进入
`if (changed) { 激活少量下游位; }`。对于实际激活写入很少的情况，可考察
复用现有精确条件掩码写入，保持原位集合和 guard，不通过 compiler barrier、
信号名单或全局禁用分支来强制代码形态。这是下一候选方向，本轮尚未实现
或宣称其有性能收益；也不能把 b210 这一个小热点当作 p18 的全部瓶颈。

完整普通与诊断汇总：
[`results_summary.json`](../../build/repcut_grhsim_20260925/p18_change_branches_20261002/results_summary.json)、
[`pmu_xor_results.json`](../../build/repcut_grhsim_20260925/p18_change_branches_20261002/pmu_xor_results.json)、
[`instruction_mix.json`](../../build/repcut_grhsim_20260925/p18_change_branches_20261002/instruction_mix.json)、
[`source_audit.json`](../../build/repcut_grhsim_20260925/p18_change_branches_20261002/source_audit.json)、
[`stages.json`](../../build/repcut_grhsim_20260925/p18_change_branches_20261002/stages.json)、
[`diagnostic_stages.json`](../../build/repcut_grhsim_20260925/p18_change_branches_20261002/diagnostic_stages.json)。

### 7.34 宽值变化结果的低成本条件激活（2026-10-02）

接续 §7.33，仍以 §7.30 `wordwise_memory` 为有效基线，不叠加未取得整体
收益的 XOR、packed/direct/cohort 改写。代码检查发现，普通物化宽值赋值
一直将 helper 返回值放在 `if (changed)` 中，而 scalar 路径已能复用
精确的条件掩码激活。此轮验证的是返回值的**使用方式**，不是再次更改
宽值赋值 helper 的比较算法。

新增默认关闭的 `wide_assign_eager_max_activation_writes`，可选 `0..3`；
计数使用既有条件激活成本估算：局部活动字一次 OR 算一次，相邻全局活动
字合并为 1/2/4/8-byte chunk 后各算一次，激活表/超过三次写入回退。
选中后先 `const bool changed = assign_words(...)`，只调用 helper 一次，
再将精确目标 mask 与 `-unsigned(changed)` 相与后 OR 回原活动字。
不改目标集合、执行 guard、宽值运算、helper、存储布局、batch 边界或
commit；不引入新的 deferred group。事件值保持原路径，Verilator 不变。
profile/bitmap 仍按原条件更新，其额外成本不包括在上述活动字写入预算内。

本轮预设只评估预算 **1**，所有分区统一应用通用规则；没有模块/信号/
位宽或 profile 白名单。对全模型生成 off/on，对完整差异做结构核对，再
将唯一等价变化应用到冻结的有效基线（保留其 commit-demand 改写）。
计划为 node030 CPU96–127、NUMA1、N=K=32、all-spin、Clang23/O3、
ASLR off、C=100000，两个窗口共八对普通 AB/BA；独立固定标签 batch、
timeline 和 PMU 不混入普通 walltime。默认保持关闭，收益待完成后判定。

专项测试已通过：default/off/显式属性优先级逐文件相同；预算 1/2/3、
环境开关、perf、trigger profile、bitmap/union、拆分 helper 均执行生成
模型，覆盖 65..4096-bit、重复 eval、重新 init、稠密/稀疏变化、变化被
OR 掩盖、尾字截断、本地和全局目标、多个目标合并写入，以及大扇出和
激活表回退；非法参数拒绝。完整默认/开启回归及 sanitizer 正在执行。

初步静态检查的收益并不一致：p18/b195 条件跳转 67→51、指令 5623→5590、
栈寻址指令 1418→1367；b210 指令 5017→4996、跳转保持 22；但 b179
跳转 66→50 的同时，指令 4526→5346、栈寻址 1128→1725。后者提示
需要实测寄存器溢出/调度代价，不能从“少了 16 个跳转”直接推断加速。
这些只是预览，最终以实际链接对象核对及动态采样为准。

本轮产物集中于
[`wide_activation_20261002`](../../build/repcut_grhsim_20260925/wide_activation_20261002/)。

#### 完整生成核验与 b179 编译形态

专项、默认 emitter、开启 emitter、GrhSIM/Verilator package 回归均通过，
UBSan 与 ASan+UBSan 通过。默认关闭时，7552 个生成源码/头文件、共
1,745,388,665 bytes 与此前的实际生成结果逐字节相同。开启后，所有差异
均等于经过严格匹配的“单次赋值 helper + 原目标的条件掩码”替换；再核对
这些变换区间在冻结有效基线中也完全相同，保留其原有 commit-demand
改写。不是把新的全生成包直接当作基线的替代品，也没有修改批边界。

全分区统一规则共命中 2185 处、660 个源文件、30 个分区：2067 次全局
byte OR、96 次 16-bit chunk OR、2 次 32-bit chunk OR、20 次本地活动字
OR。没有改变 runtime helper 或任何头文件；未命中的源文件链接原冻结
文件，所有命中的翻译单元均重新编译。增量构建 27.340 s，候选 ELF
`3c7b9fa4…`、archive `173dda39…`；基线 archive 仍为 `bb641538…`。

b179 的进一步归因使用 `-gline-tables-only` 重编译，`.text` 与不加调试
信息的对象逐字节相同。其函数栈帧分配 0x2a8→0x498 bytes（680→1176），
但扩张并不始于寄存器分配：Clang 在 `finalize-isel` 后、寄存器分配前的
CMOV 已为 47→467；最终机器码 CMOV 为 45→465。优化后的 LLVM IR 中
`or i1` 都为 591 个、`icmp` 都为 400 个，条件 branch 只 36→35。
因此，根因方向是删掉控制流边界后，指令选择对同一批 Boolean 归约的
处理发生了变化，再带来更多指令和栈读写，而不是新增了相应数量的 RTL。

展开链实际设置的是原 deferred group 的 192 和 12 掩码（各包含两个
active bit），**不是**新宽值激活的 8 掩码。该 supernode 的三个组分别
累计 288、144、144 个源条件；其中两个多位掩码被展开为长 CMOV 链。
对照 b195 的组源数为 270/144/126，但目标掩码分别为 64/32/16；b210
为 288/144/144，掩码为 4/8/128，都是单 bit，并未出现同样的扩张。
这个差异说明后续筛选/改写可以研究“长 Boolean 归约 + 多位常量掩码”的
通用结构，而不需要分区/信号名单；当前还不能仅由这三个例子确定收益规则。
源码行号有时继承最后一个 slice 的注释，不能把这些 CMOV 误认为 slice
运算本身的开销。动态成本和普通 walltime 将另行列出。

证据：[`disabled_audit.json`](../../build/repcut_grhsim_20260925/wide_activation_20261002/disabled_audit.json)、
[`source_audit.json`](../../build/repcut_grhsim_20260925/wide_activation_20261002/source_audit.json)、
[`residual_code_map.json`](../../build/repcut_grhsim_20260925/wide_activation_20261002/residual_code_map.json)、
[`isel_results.json`](../../build/repcut_grhsim_20260925/wide_activation_20261002/isel_results.json)。

#### 完整性能结果与决策

两个窗口共八对普通 AB/BA、两对固定标签 batch、两对 timeline、两对局部
PMU 全部完成，合计 28 次正式 C=100000 和 10 次 smoke 均通过 Difftest。
调用/活跃计数向量一致，输入和二进制身份检查通过，生成器与源码身份在
结束时仍与冻结记录相同。2185 处改写实际改变 657 个 archive member，
6797 个 member 字节不变；p15、p28 没有命中，未手工排除任何分区。
普通运行与插桩运行分开执行，没有与本轮生成/编译任务重叠。

下表百分比为八个配对 `(candidate / baseline - 1)` 的中位数，不是两个
绝对中位数之比；负值表示更快。

| 普通运行指标 | 基线中位数 | 候选中位数 | 配对变化 | 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| walltime | 16.285 s | 16.310 s | +0.215% | 2/8 |
| Host | 16.252 s | 16.2755 s | +0.247% | 2/8 |
| 全局 eval/step | 52.399 µs | 52.223 µs | −0.314% | 6/8 |
| 全局 update/step | 23.7595 µs | 23.857 µs | +0.887% | 1/8 |
| p3 eval/step | 45.3125 µs | 44.9340 µs | −0.930% | 6/8 |
| p6 eval/step | 37.4100 µs | 36.9440 µs | −1.381% | 8/8 |
| p10 eval/step | 31.6655 µs | 32.0745 µs | +1.193% | 1/8 |
| p18 eval/step | 31.8500 µs | 32.2755 µs | +1.264% | 0/8 |
| p29 eval/step | 16.4020 µs | 16.3395 µs | −0.181% | 5/8 |

两个普通窗口 walltime 分别 +0.031%（2/4 更快）、+0.276%（0/4）；
AB 顺序 +0.307%、BA +0.153%。update 源码没有被此规则直接改写，不能
把其 +0.887% 简单解释为新增了 update 运算；布局、缓存/预测器状态和
跨阶段相位尚未独立分离。独立 timeline 甚至显示 update 阶段相反方向的
波动，因此以普通 walltime 判定整体收益，不借阶段指标替代。

固定历史瓶颈标签的逐 batch 计时显示 p18/b179 为
0.59536→0.76317 µs（+28.186%）；b195 为 +1.534%，b210 为 +1.683%。
与此同时，p6/b158 为 1.82323→1.05315 µs（−42.237%），b159 为
−2.301%，b184 为 −3.870%。因此在普通测试完成后，独立 PMU 同时测
p18 的 96/179/195/210 和 p6 的 158/159/184，不只诊断退化侧。

PMU 每 127 step 采样，固定 p6/p18 标签分别 422/432 个样本，每 step
平均调用约 1.872/1.995 次；所有 running/enabled=1。以下数据为每个
采样 step 的累计值，包含固定 probe 开销。每次调用区间计时不包含 PMU
读数的全部开销，不能用两者直接相除推算频率。另测每 step 一次的空载
probe，约 269 instructions、57 branches、2 misses、25 ns，不机械扣除。

| batch | instructions 基线→候选 | cycles 变化 | branch misses 基线→候选 | 调用计时变化 |
| --- | ---: | ---: | ---: | ---: |
| p6/b158 | 7514.33→7520.58（+0.083%） | −39.116% | 136.17→28.85（−78.810%） | −44.067% |
| p6/b159 | 10005.27→10010.17（+0.049%） | −1.993% | 76.52→73.45（−4.013%） | −1.935% |
| p6/b184 | 46135.54→46177.10（+0.090%） | −0.571% | 97.94→88.33（−9.809%） | −0.675% |
| p18/b179 | 4634.20→5467.23（+17.976%） | +21.223% | 8.51→7.28（−14.472%） | +24.032% |
| p18/b195 | 5609.81→5587.47（−0.398%） | +5.476% | 12.38→12.08（−2.430%） | +3.771% |
| p18/b210 | 5230.74→5209.74（−0.401%） | +2.582% | 9.82→9.93（+1.061%） | +2.950% |

p18/b96 的机器码完全未改，动态指令也相同，但此次 PMU cycles +5.303%、
计时 +3.889%；所以不把 b195/b210 的小幅周期变化全部归因于改写。
相比之下，b179 在两种独立插桩中都慢约 24%–28%，动态指令增加约 18%，
即使 miss 减少仍变慢，与前述 CMOV 链及栈访问膨胀相吻合。

p6/b158 的改善也不是“少算了很多逻辑”：实际链接对象指令
15971→15991，条件跳转 844→843，动态指令基本不变。该文件只有七处
227-bit 赋值的条件激活改写；不能将 −79% 的 miss 理解为删掉了相同
比例的分支。计时与周期的大幅减少伴随预测失败下降，支持分支预测是
重要机制，但分支历史、地址布局及其他上下文变化的贡献仍未独立分离，
不能将这个局部百分比当作可直接推广的规则收益。

独立 timeline 的固定历史样本中，p6 自身 eval −1.114%、两沿 step
−0.394%；p18 自身 eval +1.765%、两沿 step +0.010%；p3 自身 eval
+1.120%、两沿 step +0.043%。这与普通平均值不是同一统计对象，不混算。

结论：**只按最后的活动字写入数筛选，还不足以取得整体 walltime 收益**。
新选项保持默认 `0`，不替换有效 `wordwise_memory` 基线，不改变 Verilator。
此轮确实验证了少量条件激活可以改善部分热点，也定位了一个具体反例：
删掉宽值分支后，周边“长 Boolean OR 归约 → 多位常量掩码”被后端展开
成长条件移动链。下一步应优先对该通用结构做小型复现及受控改写，再验证
能否保留 p6 的收益、避免 b179 的退化；不以分区名单或单一静态指令数
硬筛选，也不假定所有多位掩码都一定退化。本节尚未实现该后续改写。

完整结果：[`results_summary.json`](../../build/repcut_grhsim_20260925/wide_activation_20261002/results_summary.json)、
[`pmu_results.json`](../../build/repcut_grhsim_20260925/wide_activation_20261002/pmu_results.json)、
[`instruction_mix.json`](../../build/repcut_grhsim_20260925/wide_activation_20261002/instruction_mix.json)、
[`stages.json`](../../build/repcut_grhsim_20260925/wide_activation_20261002/stages.json)、
[`diagnostic_stages.json`](../../build/repcut_grhsim_20260925/wide_activation_20261002/diagnostic_stages.json)。

### 7.35 长 Boolean 归约到多位掩码的物化实验（2026-10-02）

接续 §7.34，针对后端把长变化归约展开为 CMOV 链的已确认机制，先比较
等价表示，再进行完整模型验证。有效基线仍是 §7.30 `wordwise_memory`，
不是上一轮未取得 walltime 收益的宽值条件激活版本。没有按分区/信号名称
选择优化；代表性热点只用于编译结果诊断。

预览中，整数 XOR 差异归约和累加变化次数虽然可以阻断该 CMOV 展开，
却增加了总体指令及栈读写。局部 volatile 物化最终 Boolean 的表示更小：
不改逐源检测，在最终掩码生成前将归约结果固定一次，阻止多位掩码分配到
前面数百个条件。它不是线程同步，不含 CPU 内存栅栏；其局部 store/load
也有成本，不能单凭解决编译膨胀就宣布 walltime 改善。

新增默认关闭的 `deferred_activation_materialize_min_sources`，本轮预设
门槛 32：普通 deferred group 的源全部为 1..64-bit Logic，至少同一活动字
内有两个目标位，且源数达到门槛。packed/direct 接管的组及 fullpass 保持
原路径。实现保留原 Boolean 归约，用一次 volatile store/load 得到稳定
谓词，所有后续激活、profile、bitmap 使用同一普通 Boolean 读取结果。

计划生成 off、只开新规则、再叠加上一轮宽值激活预算 1 三套完整源码；
逐文件证明唯一生成差异，再组合到冻结有效基线中，保留其 commit-demand
代码。测试仍在 node030 CPU96–127、NUMA1、N=K=32、all-spin、Clang23/O3、
ASLR off、C=100000 上交错执行，普通 walltime 与 batch/PMU 诊断分开。
先验证单项和组合是否取得收益，不默认打开新规则，也不追认上一轮候选。

本轮产物集中于
[`deferred_reduce_20261002`](../../build/repcut_grhsim_20260925/deferred_reduce_20261002/)。

#### 完整源码核验、回归与实际机器码

专项覆盖 default/off/属性优先级、环境变量、16/32/33 的门槛边界、
1/8/32/64-bit 源、65-bit 回退、单目标位/跨字单目标位回退、本地/全局
目标、重叠组及直接目标、重复 eval/重新 init、稀疏/稠密/高位变化，
perf、trigger profile、bitmap/union、split、fullpass 及与 packed/direct
选项共同开启的生成模型均执行通过。默认和开启完整 emitter 回归、
GrhSIM/Verilator package 回归、UBSan、ASan+UBSan 全部通过。

关闭时 7552 个文件、1,745,388,665 bytes 与前一有效生成结果逐字节相同。
新规则共选中 **296 组、19723 个源、148 个文件、31 个分区**；所有组
均有对应的实际变化归约更新，不存在只初始化而没有实际更新的空组。
完整 off/on 差异严格等于“flush 前物化一次 + 最终使用 ready 谓词”，
其余源码相同；组合版本再严格等于 §7.34 的 2185 处条件激活改写。
所有修改区间与冻结的 commit-demand 基线也相同，未覆盖其额外改写。

只开新规则的 archive 中 148 个对象变化、7306 个保持相同；组合为
781 个变化、6673 个相同（783 个翻译单元重编译，其中两个对象相同）。
**增量**构建时间分别 15.579/35.035 s，非全量编译时间。三套源码生成
耗时 555.250/542.065/529.035 s；这是顺序生成记录，不据此声称生成加速。
候选 ELF 分别为 `2821f77a…`、`15bfc207…`，有效基线仍为 `e7d431bd…`。

实际链接的 p18/b179 对照如下，`single` 为只开新规则，`wide` 为
§7.34 旧候选，`combined` 为两项同时开启；这里统计的是静态函数对象。

| b179 指标 | 有效基线 | single | wide | combined |
| --- | ---: | ---: | ---: | ---: |
| 指令数 | 4526 | 4528 | 5346 | 4495 |
| CMOV | 47 | 46 | 467 | 46 |
| 条件跳转 | 66 | 66 | 50 | 50 |
| 栈寻址指令 | 1128 | 1132 | 1725 | 1079 |
| 栈帧 bytes | 680 | 680 | 1176 | 648 |
| text bytes | 24504 | 24524 | 30792 | 24202 |

四套 `-gline-tables-only` 重编译的 `.text` 均与实际 archive 对象完全相同。
LLVM IR 的 `or i1` 都为 591、`icmp` 都为 400；新规则只多两次 volatile
store/load。`finalize-isel` 后、寄存器分配前 CMOV 已为 47/46/467/46，
证明阻止展开的效果确实发生在指令选择处，并未靠删减原逻辑或改变激活
集合“省工作”。同时也看到基线本来没有此膨胀时，single 几乎不减少指令。

勘误：§7.34 文字中的“最终机器码 CMOV 45→465”少计两条；当时保存的
`instruction_mix.json` 和 `residual_code_map.json` 均为 **47→467**。
增加 420 条和指令选择阶段的归因不变，本节采用实际对象完整计数。

#### 普通 walltime 与独立 batch/PMU 结果

单项、组合各执行两个窗口、共八对普通 AB/BA。以下均为各自配对
`100 × (candidate / baseline − 1)` 的中位数，负值表示改善；不是
两个绝对中位数相除。两套测试是分开的实验序列，不能横比绝对时间。

| 普通指标 | single 配对变化（更快对数） | combined 配对变化（更快对数） |
| --- | ---: | ---: |
| walltime | −0.341%（5/8） | −0.600%（5/8） |
| Host | −0.350%（5/8） | −0.600%（5/8） |
| 全局 eval/step | −0.798%（6/8） | −0.588%（5/8） |
| 全局 update/step | −0.027%（5/8） | −0.270%（5/8） |
| p3 eval/step | −1.718%（7/8，另 1 对持平） | −0.546%（7/8） |
| p6 eval/step | −0.682%（7/8） | −1.149%（7/8） |
| p10 eval/step | −0.765%（6/8） | −0.062%（4/8） |
| p18 eval/step | −0.481%（6/8） | +0.709%（1/8） |
| p29 eval/step | −0.747%（5/8） | −0.096%（4/8） |

single 的 walltime 绝对中位数 18.000→17.925 s，两个窗口配对变化分别
−0.028%/−0.735%，AB +0.242%、BA −0.723%。combined 为 18.270→18.240 s，
两个窗口 −0.754%/+0.267%，AB −0.754%、BA +0.924%。顺序与窗口间波动
大于整体收益量级，因此 **不能把 −0.34%/−0.60% 当作已稳定验证的加速**。
本轮基线绝对时间也高于 §7.34；未把跨轮绝对差值计作任何候选收益。

独立固定历史瓶颈标签的 batch 计时中，combined 相对有效基线的
p6/b158 为 1.99273→1.07183 µs（−46.213%），p18/b179 为
0.63705→0.69683 µs（+9.384%）；另外直接对 `wide` 和 `combined` 做
同窗口 AB/BA，b179 为 0.79816→0.67565 µs（**−15.349%**），p6/b158
为 1.12282→1.09293 µs（−2.663%）。这说明上一轮 b179 的退化已显著
缓解，同时 p6 的收益仍在；不能说 b179 已明确快于有效基线。

独立 PMU 对有效基线的结果如下。每 127 step 采样，固定历史 p6/p18
分别 422/432 个样本，活动/调用计数完全一致，所有 running/enabled=1。
数值为每个采样 step 的累计值，包含固定 probe 成本；计时区间与 PMU
区间不同，不用 `cycles/ns` 计算频率。

| 固定标签 batch | single 指令变化 | single cycles 变化 | combined 指令变化 | combined cycles 变化 |
| --- | ---: | ---: | ---: | ---: |
| p6/b158 | −0.001% | −1.314% | +0.083% | −39.976% |
| p18/b179 | +0.044% | +2.005% | −0.388% | +2.268% |
| p18/b96（对象未改） | +0.002% | +4.351% | +0.00005% | +7.270% |

combined 的 b158 miss 为 135.924→27.810（−79.540%）；b179 为
8.310→7.516（−9.554%），动态指令为 4634.262→4616.287，已没有上一轮
约 18% 的指令膨胀。但未改的 b96 也有周期波动，不能把 b179 剩余约 2%
周期变化全部归因于新代码，或据此承诺进一步清理几条指令就能改善 walltime。

结论：这次**修复了一个有实证的编译膨胀机制**，但当前应用范围与方式
尚未证明稳定的整体收益。`deferred_activation_materialize_min_sources`
继续默认 `0`，宽值激活预算也继续默认 `0`；不替换有效 `wordwise_memory`
基线，不改 Verilator。后续值得检验的是能否用成本更低的值物化边界
避免落栈，以及其对更大残余热点的影响；不要继续仅按减少 CMOV 数量判优。

证据：[`disabled_audit.json`](../../build/repcut_grhsim_20260925/deferred_reduce_20261002/disabled_audit.json)、
[`source_audit.json`](../../build/repcut_grhsim_20260925/deferred_reduce_20261002/source_audit.json)、
[`combined/source_audit.json`](../../build/repcut_grhsim_20260925/deferred_reduce_20261002/combined/source_audit.json)、
[`lowering_results.json`](../../build/repcut_grhsim_20260925/deferred_reduce_20261002/lowering_results.json)、
[`instruction_mix.json`](../../build/repcut_grhsim_20260925/deferred_reduce_20261002/instruction_mix.json)、
[`results_summary.json`](../../build/repcut_grhsim_20260925/deferred_reduce_20261002/results_summary.json)。

#### 收尾：直接 wide→combined 的 PMU 对照

普通测试结束后另做两对直接 PMU AB/BA，不与编译或其他本轮仿真重叠。
p18/b179 的指令 5467.289→4616.292（**−15.565%**），cycles
3031.764→2596.037（**−14.372%**），区间计时 0.82330→0.69833 µs
（−15.179%）。分支总数基本相同，miss 7.102→7.417，改善不依赖减少
预测失败，与“去掉 CMOV 展开和额外栈操作”的静态证据一致。
p6/b158 指令 +0.001%、cycles −0.177%，确认叠加物化没有丢失它已有的
改善。空 probe 约 269 instructions、57 branches、2 misses、27 ns，
不机械扣除；未改 b96 的指令不变而 cycles +5.685%，也保留为环境/
布局上下文敏感性的对照，不假定所有周期差都是目标代码的直接成本。

至此本轮共 **56 次正式 C=100000、20 次 C=100 smoke** 均通过；普通
walltime 32 次、固定标签 batch 12 次、局部 PMU 12 次分开统计，未混算。
所有运行输入/二进制身份检查、工作量向量检查、最终生成器身份检查均
通过；不据局部 −15% 更改前面的整体 walltime 结论。

直接对照原始数据：
[`wide_vs_combined_pmu_results.json`](../../build/repcut_grhsim_20260925/deferred_reduce_20261002/wide_vs_combined_pmu_results.json)、
[`final_diagnosis.json`](../../build/repcut_grhsim_20260925/deferred_reduce_20261002/final_diagnosis.json)。

### 7.36 当前有效线与 Verilator 的瓶颈均值复核（2026-10-02）

按用户要求暂不开展编译后反馈，也不继续叠加未经采纳的候选。本轮只重新
测量当前有效 `wordwise_memory` 与 Verilator/O3 的条件瓶颈。GrhSIM 普通
ELF 为 `e7d431bd…`、模型 archive 为 `bb641538…`，与 §7.30 的最终验证线
相同；Verilator 采用 §7.29 最终共享派发版本 `9ab81124…`。两者均包含
all-spin 去锁框架，不将较旧框架或本轮之前的无收益候选混作“当前版本”。

两后端统一使用同一低频相邻沿 timeline：每 127 step 采当前及下一 step，
记录实际 clock、32 个线程的 eval/update 起止和 Host 阶段边界。GrhSIM
只替换 common/eval/update 三个 wrapper 对象，7451 个 archive member
不变；Verilator 同样只重建三个 wrapper，全部其余链接对象/模型 archive
身份不变。没有修改模型、分区、通信、编译优化或默认选项。

node030 CPU96–127、NUMA1、N=K=32、Host lane 9、all-spin、Clang23/O3、
ASLR off、C=100000。按 V/G、G/V、V/G、G/V 完成 **4 对交错**，8 次正式
Difftest 和 2 次 C100 smoke 全部通过；终态保持 PC `0x80000c0c`、
instructions=240349、cycles=99996、guest_cycles=100001、steps=200102。
每次 3150 个采样，每后端合计 **12600** 个；两后端 step/clock 逐项相同。
没有空闲率 gate 或时间离群值剔除，运行前后输入和二进制身份一致。

#### 口径与当前分布

“瓶颈”取该步 **启动偏移 + eval duration 最大** 的分区，即最后结束 eval
的线程，而非单纯 duration 最大者；GrhSIM 中两者有 227/12600 个样本不同。
下表 G 时间只在该分区实际成为 GrhSIM 瓶颈的样本上取自身 eval 算术均值，
不含启动等待、全局 update。V 时间取 **同一次配对、同一步、同一分区**，
不是 Verilator 自选瓶颈样本。变化为这两个匹配均值之比减一；不是普通
walltime 的收益，也不能相加。表列 GrhSIM 占比至少 0.1% 的所有分区。

| 分区 | G 瓶颈次数 / 12600 | G 占比 | G 瓶颈 eval（µs） | V 相同步 eval（µs） | G/V 变化 |
| --- | ---: | ---: | ---: | ---: | ---: |
| p3 | 3875 | 30.75% | 45.918 | 88.548 | −48.14% |
| p18 | 1984 | 15.75% | 55.224 | 51.441 | +7.35% |
| p10 | 1599 | 12.69% | 54.739 | 60.326 | −9.26% |
| p29 | 1517 | 12.04% | 65.214 | 35.586 | +83.26% |
| p6 | 1112 | 8.83% | 58.832 | 38.974 | +50.95% |
| p26 | 1064 | 8.44% | 63.899 | 33.091 | +93.10% |
| p27 | 586 | 4.65% | 67.803 | 27.756 | +144.28% |
| p25 | 540 | 4.29% | 67.411 | 26.673 | +152.73% |
| p13 | 155 | 1.23% | 64.323 | 38.445 | +67.31% |
| p17 | 65 | 0.52% | 47.485 | 44.135 | +7.59% |
| p15 | 52 | 0.41% | 47.256 | 63.451 | −25.52% |
| p14 | 20 | 0.16% | 60.469 | 22.584 | +167.75% |

前八项合计 97.44%；p25/p26/p27 合计 17.38%，不能只盯 p3/p10/p18/p29。
其余分区各自不足 0.1%，包括没有瓶颈样本者，均在完整 32 行表中保留；
没有瓶颈样本不表示计算耗时为零。条件均值也不保证大于全程均值：其他
分区较轻时，p3 即使自身不在最重状态也可能成为瓶颈。

Verilator 自身的瓶颈分布高度集中于 p3：12345 次（97.98%），这些样本内
p3 eval 平均 **80.039 µs**；p13 为 211 次（1.67%）、113.531 µs，p22
为 29 次（0.23%）、55.929 µs，其余合计 15 次。这是另一套条件集合，
不能将 p3 的 80.039 与上表匹配步的 88.548 混用。

全体采样的全局 eval 平均为 G **57.370 µs**、V **82.299 µs**。
G 最后完成线程的自身 eval 平均 55.706 µs、启动偏移 1.115 µs、结束后
Host 尾部 0.550 µs，三项之和解释了该阶段均值。V 对应为
80.742/0.780/0.778 µs。本轮均为探针计时，不当作新的普通 walltime 实验。

#### 相同步号的独立选择与两沿合计

为避免用某次运行的偶发慢样本挑选自身，另以其他三对 G 的同一步完成
时刻中位数选瓶颈标签，再测留出的一对。前八个分区的单沿差异方向均
保持；例如 p18 +7.41%、p29 +82.73%、p26 +93.39%、p27 +143.37%。
p13 的自选 64.323 µs 在此口径降到 36.129 µs（V 34.017 µs，+6.21%），
因此不能把其 +67% 当作稳定的固定步热点，也未将这种差异归因于外部负载。

下表进一步只使用每 127 step 的首个锚点及紧接着的 step+1，仍按其他
三对独立选标签。各行两后端使用同一组步号，两沿值是该组相邻 eval
的累计均值，不与上表不同样本集合的单沿值直接相减。

| 分区 | 独立标签样本数 | G 两沿 eval（µs） | V 两沿 eval（µs） | G/V 变化 |
| --- | ---: | ---: | ---: | ---: |
| p3 | 2037 | 92.989 | 161.241 | −42.33% |
| p18 | 951 | 99.289 | 75.123 | +32.17% |
| p10 | 788 | 90.248 | 78.547 | +14.90% |
| p29 | 747 | 68.725 | 77.206 | −10.98% |
| p6 | 527 | 98.412 | 102.192 | −3.70% |
| p26 | 548 | 83.725 | 95.561 | −12.39% |
| p27 | 302 | 78.878 | 72.356 | +9.01% |
| p25 | 311 | 77.006 | 68.363 | +12.64% |

p29 为 G **65.441 + 3.285**、V **35.535 + 41.672 µs**，两沿总量更少
但集中在一个半周期；p26 为 G **64.065 + 19.660**、V
**33.013 + 62.547 µs**，同样不能仅看瓶颈沿就断言总计算量更高。
p25/p27 的重半周期不均衡还叠加约 13%/9% 的两沿残余差距。
p18 的下一沿为 G 43.842、V 23.589 µs；p10 为 G 35.566、V
18.382 µs，因此只看当前瓶颈沿会低估它们的剩余总成本。

本轮仅更新性能定位：p3 仍最常卡住屏障，但相对 V 已明显更快；p18/p10
仍值得找额外计算/执行低效，p25/p26/p27 应加入残余分析范围；p29 等
必须区分两沿总量和单沿关键路径。不开展编译后反馈、不引入新优化或默认变化。

完整 32 分区表及相邻沿拆分：
[`REPORT.md`](../../build/repcut_grhsim_20260925/current_backend_bottleneck_20261002/REPORT.md)、
[`parts.csv`](../../build/repcut_grhsim_20260925/current_backend_bottleneck_20261002/parts.csv)。
完整分布、交叉选择和逐轮均值见
[`results.json`](../../build/repcut_grhsim_20260925/current_backend_bottleneck_20261002/results.json)；
版本身份、运行签名和原始数据见同目录 `build.json`、`runs/manifest.json`。

### 7.37 GrhSIM/Verilator 瓶颈分区的代码与 PMU 归因（2026-10-03）

本节沿用 §7.36 的当前有效线，只回答“为什么某个分区在成为 GrhSIM
瓶颈时比 Verilator 慢”，不引入新的模型或默认选项。GrhSIM 仍为
`wordwise_memory`（model archive `bb641538…`，普通 ELF `e7d431bd…`），
Verilator 为 Clang23/O3、最终 all-spin 派发 ELF `9ab81124…`；两边都在
node030 CPU96–127、NUMA1、N=K=32、C=100000 下运行。PMU 探针只重建三个
wrapper 对象，GrhSIM 的 7451 个模型 archive member 和 Verilator 的模型/
运行时对象保持不变；所有 AB/BA 正式运行与 Difftest 均通过。

#### PMU 口径

在 4 对交错运行中每 127 step 采样一次，比较同一步、同一分区。瓶颈标签
沿用 §7.36 的 GrhSIM 自选“最后结束 eval”分区；因此下表不是把 V 自选的
瓶颈强行配给 G，而是回答“G 卡住时，V 执行相同分区要多少工作”。PMU 事件
是每个 eval 线程自己的 `cycles/instructions/branches/branch-misses`，
`running/enabled=1`；每个运行的第一个采样点剔除，因为它包含首次创建
perf descriptor 的一次性开销。边界 `read()` 会带来相同的微小探针成本，故
只用计数的相对关系，不用 PMU duration 估算频率。

| G 瓶颈分区 | 样本数 | G cycles / V cycles | G instructions / V instructions | G IPC / V IPC | G branch-miss / V |
| --- | ---: | ---: | ---: | ---: | ---: |
| p3 | 1992 | 159k / 302k | 302k / 461k | 1.89 / 1.53 | 0.68% / 19.44% |
| p18 | 956 | 187k / 175k | 277k / 389k | 1.48 / 2.22 | 11.97% / 11.41% |
| p10 | 790 | 189k / 205k | 332k / 427k | 1.75 / 2.08 | 6.63% / 7.67% |
| p29 | 745 | 195k / 110k | 387k / 281k | 1.99 / 2.56 | 0.45% / 1.52% |
| p6 | 529 | 201k / 130k | 339k / 287k | 1.69 / 2.21 | 5.15% / 1.29% |
| p26 | 530 | 199k / 102k | 372k / 269k | 1.88 / 2.65 | 6.24% / 0.22% |
| p27 | 305 | 206k / 85k | 353k / 199k | 1.71 / 2.33 | 10.80% / 5.19% |
| p25 | 291 | 209k / 87k | 363k / 185k | 1.74 / 2.11 | 9.40% / 5.29% |

这张表把差异分成三类：

1. **p25/p26/p27：工作量和执行效率同时不利。** GrhSIM 指令约为 V 的
   1.38/1.39/1.77 倍，cycles 约为 2.39/1.96/2.42 倍，IPC 低
   18%–29%，且分支 miss 约为 V 的 1.8–28 倍。它们不是单纯屏障偏移，
   而是 GrhSIM 在同一 eval 内做了更多变化检测/激活传播，并且控制流更难预测。
2. **p29：不是分支预测问题，而是内存访问和间接状态表示。** 指令为
   1.38 倍、cycles 为 1.77 倍，分支 miss 反而更少；IPC 从 2.56 降到
   1.99。也就是说 p29 的主要差异是更多 load/store、依赖链和缓存层压力，
   不是长分支链本身。它的两沿合计在 §7.36 甚至略快，说明这个问题还会
   通过半周期工作集中改变屏障位置。
3. **p18：代码量不是原因，但 ILP/访存延迟明显更差。** GrhSIM 指令只有
   V 的约 71%，cache reference 总量接近，cycles 却略高，IPC 只有
   1.48 对 2.22，branch miss 基本相同；因此 p18 更像是通用 slot 数组的
   间接 load、变化检测依赖链和较少可并行的表达式，而非“生成了更多算术”。
4. **p10/p3 是反例。** p10 即使 IPC 较低，因总指令更少而 cycles 略低；
   p3 的 GrhSIM 指令和 cycles 都远低于 V，且 V 的 branch miss 约 19.4%，
   说明同一后端差异不会对每个 RTL 分区同向作用。

#### cache 事件复核

另做 2 对交错运行，事件为硬件 `cache-references/cache-misses`，同样保证
`running/enabled=1`。这些是体系结构的 aggregate cache 事件，不把它们解释
成某一级 cache 的精确 miss；用途是比较相对内存交通量。

| 分区 | G refs / V refs | G misses / V misses | G miss rate / V miss rate |
| --- | ---: | ---: | ---: |
| p18 | 39.7k / 37.9k | 26.6k / 23.8k | 67.0% / 62.8% |
| p25 | 36.7k / 16.5k | 31.1k / 10.8k | 84.7% / 65.4% |
| p26 | 41.6k / 19.0k | 30.3k / 13.5k | 72.8% / 70.8% |
| p27 | 35.9k / 17.8k | 30.1k / 11.6k | 83.7% / 64.8% |
| p29 | 53.7k / 21.4k | 28.9k / 15.1k | 53.7% / 70.7% |

p25/p26/p27 的 GrhSIM cache traffic 约为 V 的 2.0–2.2 倍，miss 数约为
2.2–2.9 倍，与上面的指令和 cycles 差异一致。p29 的 miss rate 反而较低，
但 reference 约 2.5 倍，符合“访问次数/状态数组遍历更多”的判断；p18 则是
总量接近但每条指令承受的 miss 更多，符合低 IPC 的依赖/间接访存解释。

#### 静态生成代码对照

对当前有效 archive 和 Clang23/O3 Verilator `__ALL.a` 做了分区汇总。`.text`
是链接前各模型对象的总和；两种后端的函数划分不同，不把函数数直接当作
等价的 RTL 运算数。

| 分区 | GrhSIM batch 数 / `.text` | Verilator 模型对象数 / `.text` | G `eval_compute_batch` 数 |
| --- | ---: | ---: | ---: |
| p18 | 270 / 2.69 MB | 43 / 3.84 MB | 260 |
| p25 | 272 / 3.40 MB | 34 / 3.94 MB | 261 |
| p26 | 258 / 3.00 MB | 37 / 3.97 MB | 244 |
| p27 | 275 / 3.36 MB | 38 / 4.09 MB | 264 |
| p29 | 161 / 3.46 MB | 38 / 4.22 MB | 149 |

GrhSIM 的源代码呈现出统一的通用模板：每个 batch 先读取
`supernode_active_curr_` 的 activity word，再访问大型
`value_*_slots_`/`state_logic_storage_`，逐项维护 `grhsim_any_changed_*`，
最后把 changed 转成下游 active mask。以 p25/p26/p27/p29 为例，源文件中
`any_changed`/`value_slots` 出现次数分别为 **55962/148021**、
**46573/131418**、**56381/148784**、**113988/243387**；p29 尤其突出。
相应的 Verilator 代码主要使用 `vlSelfRef` 直接字段和
`__VactTriggered/__VnbaTriggered` dirty-trigger bitmap，运行时只进入被
触发的 phase/region，而不是在每次 eval 中顺序调用全部 batch。

因此，“GrhSIM 比 V 慢”当前最可信的归因不是 RTL 本身存在某个 p25/p29
特殊算子，也不是单纯的 C++ 优化级别，而是 **GrhSIM 后端的通用调度/状态
表示方式**：

* 直接 dispatch 的固定 batch 序列带来大量 inactive activity-word 检查；
* 变化检测和激活传播通过大 slot 数组与 bool/掩码临时量完成，导致更多
  间接访存、cache traffic 和依赖链；
* p25/p26/p27 还叠加较多条件分支，p29 则主要叠加内存交通，p18 主要叠加
  load-use 依赖和 ILP 不足。

这也解释了为什么“最大 `.text`”不是充分指标：Verilator 的 p18/p29
`.text` 反而更大，但它的 dirty-trigger 调度和直接字段访问使动态指令/内存
访问更少；反过来 p10/p3 的动态工作量并未落入同一坏模式。

#### 下一步建议

下一步应优先做后端通用而非分区名/信号名匹配的实验：

1. 在不改变 batch 顺序和固定点语义的前提下，把 `activeWordFlags` 先压成
   active-batch list/bitmap，只调用实际 active 的 batch；用 batch-entry 计数
   验证是否消除了 inactive dispatch，而不是凭 `.text` 推测。
2. 对生成器评估“按 batch/类型分片的 slot storage”或只读值的局部指针缓存，
   降低 `value_*_slots_` 的间接寻址；先以 p25/p27 的 cache PMU 和 p18 的
   IPC 为验收指标。
3. 保留 p29 的两沿计时，避免把单沿下降误判为总工作下降；任何候选都必须
   同时看 G 自选瓶颈分布、两沿累计 eval、普通 walltime 和 Difftest。

本轮证据与原始数据：
[`PMU 探针脚本`](../../build/repcut_grhsim_20260925/current_backend_bottleneck_20261002/pmu_experiment.py)、
[`PMU core 运行目录`](../../build/repcut_grhsim_20260925/current_backend_bottleneck_20261002/pmu_runs_v2/)、
[`PMU memory 运行目录`](../../build/repcut_grhsim_20260925/current_backend_bottleneck_20261002/pmu_memory_runs/)、
[`PMU 构建身份`](../../build/repcut_grhsim_20260925/current_backend_bottleneck_20261002/pmu_build.json)、
[`静态代码汇总`](../../build/repcut_grhsim_20260925/current_backend_bottleneck_20261002/static_code_metrics.csv)、
[`生成模板 token 汇总`](../../build/repcut_grhsim_20260925/current_backend_bottleneck_20261002/static_token_counts.csv)。

### 7.38 瓶颈归因勘误：指令取码、活跃覆盖与 bool 别名（2026-10-03）

#### 对 §7.37 的勘误

上一节正确记录了动态指令、cycles 和 IPC 的差异，但对原因的解释超过了
计数本身能够证明的范围。本节保留历史记录，以下列核实结果为准：

1. node030 是 AMD EPYC 9684X（Family 19h、Model 11h），当前内核为
   `6.8.0-111-generic`。本机 `perf list --details` 明确给出
   `cache-references=event 0x60/umask 0xff`、
   `cache-misses=event 0x64/umask 0x09`。前者是包含指令、数据、预取等
   请求的 L2 事件，后者合并指令与数据的 L2 miss；不是纯数据访存计数。
   两者覆盖范围不同，其比值也不应表述成严格的同口径 cache miss rate。
   因而不能从上一节的总量直接推出“slot 数组的间接访存是主因”。
   事件映射和语义可分别核对
   [Linux AMD PMU 实现](https://github.com/torvalds/linux/blob/v6.8/arch/x86/events/amd/core.c) 与
   [Zen4 cache 事件定义](https://github.com/torvalds/linux/blob/v6.8/tools/perf/pmu-events/arch/x86/amdzen4/cache.json)。
2. 固定索引的 slot 访问不等于指针追逐；Verilator 的字段和 GrhSIM 的定长
   数组访问都可能降为基址加常量偏移。上一节“间接状态表示必然更慢”的说法
   缺乏汇编及消融证据，不据此推进 storage 分片。
3. p25 的 instructions 比值应为约 **1.97**，不是正文中的 1.38；表中
   branch-miss 列是 miss/branches 的比例，不是绝对 miss 次数。
4. 静态表首列的 270/272/258/275/161 是 archive 对象数，不是 batch 数；
   带克隆的符号统计也不能代替 scheduler 调用数。当前实际 compute 调用
   项 p18/p25/p26/p27/p29 分别为 **255/257/243/260/147**。
   上一节基于 `generated_off` 的源码 token 计数也不是动态工作量证明。
5. §7.14–7.17 已验证过单 batch guard 和多种额外 bitmap 维护方式。
   高全程空调用率不足以支持重新优先投入 bitmap，必须先看瓶颈步的覆盖。

#### 分离指令与数据的同一步 PMU

仍冻结 §7.36 的 wordwise_memory archive `bb641538…` 和 Verilator/O3
最终 all-spin 模型。在 node030 CPU96–127、NUMA1、N=K=32、Clang23/O3、
C=100000 下，miss、request、pipeline 三种事件组分别做两对 AB/BA。
12 次正式运行全部通过 Difftest 及完整功能签名，所有线程计数
`running/enabled=1`，模型对象不变。每个探针仅更换两个 wrapper 对象；
GrhSIM 其余 7452 个 archive member payload 恒等。构建、运行前后均检查
ELF/image/NEMU 身份。首个创建 perf descriptor 的 step 127 不参与统计。

瓶颈标签由上一轮四次独立 timeline 的各分区完成时刻中位数预先选定；
两后端使用相同步号、相同分区，不用本轮 PMU 耗时重新选样。下表为
选中 eval 内的事件平均次数，`k` 为千次，不是 KB。

| 分区 | 样本数 | 指令 L2 miss G / V (k) | 数据 L2 miss G / V (k) | G 的 miss 中指令占比 |
| --- | ---: | ---: | ---: | ---: |
| p3 | 1010 | 22.50 / 38.34 | 1.872 / 1.587 | 92.3% |
| p18 | 478 | 25.89 / 22.81 | 0.821 / 0.559 | 96.9% |
| p10 | 398 | 26.32 / 28.14 | 1.092 / 0.951 | 96.0% |
| p29 | 374 | 28.47 / 14.73 | 0.317 / 0.296 | 98.9% |
| p26 | 272 | 28.93 / 12.42 | 1.107 / 0.480 | 96.3% |
| p6 | 268 | 26.76 / 18.68 | 1.865 / 0.868 | 93.5% |
| p25 | 158 | 30.02 / 10.62 | 0.703 / 0.370 | 97.7% |
| p27 | 154 | 29.46 / 12.00 | 0.591 / 0.340 | 98.0% |

使用的 raw 事件分别是 `r0164`（指令 L2 miss）、`r0864`（数据 L2 miss）、
`r1060`（指令 L2 request）、`re860`（常见 L1D→L2 request，包含预取）。
request 组中 p25/p27 的 G 指令请求为 31.53k/30.68k，数据请求仅
2.63k/2.89k；p29 则有 30.34k 指令请求和 13.98k 数据请求，对照 V 的
18.16k/1.83k。**p29 的数据请求确实更多，但大多数在 L2 命中；不能把
“请求多”和“数据 cache miss 是主瓶颈”画等号。** 两种 raw request 的和
也不要求等于包含其他请求类别的旧 `0xff60`。

再按 [Zen4 pipeline 指标定义](https://github.com/torvalds/linux/blob/v6.8/tools/perf/pmu-events/arch/x86/amdzen4/pipeline.json)
测量 `de_no_dispatch_per_slot.no_ops_from_frontend` 和 `backend_stalls`，
分别除以 `6 × cycles`。这是未利用派发槽的比例，不是 walltime 占比；
frontend 还包含解码、取码、预测恢复等影响，不能全部归为 I-cache。

| 分区 | 前端供指不足 G / V | 后端阻塞 G / V |
| --- | ---: | ---: |
| p18 | 67.85% / 57.68% | 3.43% / 2.91% |
| p25 | 65.00% / 55.26% | 3.12% / 5.65% |
| p26 | 58.34% / 40.95% | 6.54% / 12.84% |
| p27 | 65.96% / 56.97% | 3.33% / 5.50% |
| p29 | 48.14% / 49.48% | 17.13% / 8.33% |

p18/p25/p26/p27 应优先检查活跃代码的动态展开、短路控制流和取码效率，
而不是先改数据数组布局。p29 不宜套同一个解释：它的工作量集中于单沿，
前端比例未高于 V，后端阻塞比例却更高，应保留两沿口径并另查活跃函数的
数据访问/依赖。上述事件支持优先级排序，尚未把全部 cycles 差额精确分摊。

#### 空调用是否落在关键路径

另建低频 batch 探针，仅在预先选定的瓶颈分区/step 逐调用计时；原有
compute/commit 机器码不动，计时及探针开销不用于评价普通 walltime。
每版两次 C100000 均通过，下面列出 baseline 的结果：

| 分区 | 瓶颈唯一步数 | 每步 compute 调用 | 非空调用 | 非空占比 | 空调用计时占 compute |
| --- | ---: | ---: | ---: | ---: | ---: |
| p18 | 239 | 510.00 | 259.54 | 50.9% | 15.90% |
| p25 | 79 | 257.00 | 243.06 | 94.6% | 0.71% |
| p26 | 136 | 243.00 | 226.40 | 93.2% | 0.87% |
| p27 | 77 | 260.00 | 247.47 | 95.2% | 0.60% |
| p29 | 187 | 147.00 | 93.81 | 63.8% | 3.29% |

空调用计时含每次读取时钟的固定成本，因此不能当作精确可回收耗时，尤其
不能把 p18 的 15.90% 当作无探针理论加速比。p25/p26/p27 的结论则很明确：
**它们成为瓶颈时几乎所有 batch 都在计算，全程空调用率掩盖了这个条件差异。**
前三者最热的 12 个 batch 也只占活跃 batch 时间约 16.7%/18.4%/15.9%，
热点分散，不是一个空派发函数吞掉了全部时间。

完成了不新增 bitmap、只读取既有活动字的通用整组跳过消融：保持原顺序，
在每组开始时读取活动字，组内仍使用原 guard，避免提前快照漏掉后续激活。
非空调用次数和 active-bit popcount 的逐步向量保持一致；这不宣称是完整
活动 mask 序列相同的证明。该方向未达到稳定 Host 收益，不进入默认。
按当前记录粒度，仅保留这一机制结论，不展开失败候选的逐次调参记录。

诊断复现入口：
[`PMU 构建/运行`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/pmu_split.py)、
[`cache 分离汇总`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cache_split.json)、
[`pipeline 汇总`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/pipeline.json)、
[`固定标签 batch 汇总`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dispatch_diagnostic.json)。

#### 活跃代码的下一候选：bool 引用的覆盖缺口

在 p27/b224 的活跃逻辑中，`auto &alias = value_bool_slots_[index]` 已经
明确是一个 bool 引用，但现有 `simpleBoolOperandRef` 仅接受直接 slot 或
已物化临时量，拒绝这个等价引用；因此即使 `bool_eager_logic=1`，仍输出
`alias && other_bool`。同一个 IR 值 `_val_2522326` 在 Verilator 的
`root__9.cpp` 中使用 `&`。这只是定位例子，候选选择不能使用该值名。

按“声明明确绑定 bool slot、两操作数都是纯读取、不含调用或复杂下标”
保守普查，当前全图仍有 **105620** 个二元 `next_value` 表达式落入此类，
涉及全部 32 个分区、1964 个 compute 源文件；p18/p25/p26/p27 分别为
1574/7435/3856/7248。计数不是动态命中数，也不预报收益。全图候选先只
补齐这一类覆盖，复用现有 bool-eager 语义；复杂表达式、commit、布局、
框架和 Verilator 均保持不动。审计见
[`bool 引用普查`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_alias_audit.json)。

#### bool 引用规则补齐：实际实现与验证范围

本轮在 `lib/emit/grhsim_cpp.cpp` 中补充 bool storage alias 的类型来源：
收集别名声明时记录 `ValueSlotScalarKind::kBool`，普通 compute 生成二元
逻辑表达式时再检查该集合及两操作数的 IR 位宽。规则不读取模块、信号、
分区名或性能采样；仍复用 `bool_eager_logic`，**默认关闭状态不变**。
未证明纯度的外层表达式不放宽，commit 和 Verilator 路径也不改。

前述 105620 是只数 `const bool next_value` 的保守原型，不是实际 emitter
的完整覆盖。实际实现也覆盖局部 bool 临时量及内联表达式内部的纯读取
叶子；其前后文本长度还可能触发现有表达式物化上限。完整 32 分区生成后，
7552 个 C++/header 文件中，2547 个 compute 文件变化，源文本中共有
171435 处符合纯 bool alias 规则的表达式（不是唯一 IR 节点数或动态次数）；
54 个文件还出现物化位置变化。逐文件核对确认，变化只发生在局部标量
表达式声明行，所有 header、layout、eval 调度、commit 和 wrapper 均恒等。
**不能用最初文本原型的性能直接代表此完整实现。**

最终被测 candidate 使用真实生成器的 compute 变化，而非扩大后的正则
原型。通过不相交三方合并保留冻结 package 的既有优化：旧完整生成与
被测基线有 22 个 compute 文件存在历史选择链差异，其中 8 个也受到本轮
规则影响，均无重叠冲突地保留；其余对象直接复用。候选最终替换 2240 个
archive member，5214 个 member payload 不变。基线仍是 §7.36 的
wordwise_memory / `bb641538…`，不是重新生成的裸 package。

实际候选 archive 为 `af8e72db295695fa…`，普通 ELF 为
`a3b5feaeddf68ecd…`；ELF 的 `.text` 从 98986658 降为 97833954 字节
（−1.165%）。这里只统计代码段，不把整个 GNU size 的 text 汇总误标为
`.text`，也不据此推导运行时间。

已完成 `emit-grhsim-cpp`、`emit-grhsim-repcut-package`、
`emit-verilator-repcut-package` 三项 CTest，全部通过；新增 fixture 覆盖
bool alias、原有临时量/直接读取、混合位宽、关闭开关及功能真值表。
开启版小模型另通过 Clang23/O3 的 UBSan 检查。
源码/生成器快照、生成审计、实际合并构建及串行复测入口分别见
[`generator identity`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitted_alias/identity.json)、
[`完整生成审计`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitted_alias/audit.json)、
[`候选 build manifest`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_alias_full/build.json)、
[`构建/测量入口`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/run_final.py)。

#### 实际实现的固定瓶颈步 PMU

两边都保留原有 `bool_eager_logic=1`；A 为旧覆盖范围，B 为上述类型来源
补全，不是 bool-eager 开/关对比。两对 C100000 AB/BA 共四次正式运行，
使用本节同一组预先选定的瓶颈分区/step 标签，不在优化后重新挑选有利
样本。所有功能签名一致，`running/enabled` 全部为 1。

| 固定瓶颈分区 | 样本数/版 | cycles 变化 | instructions 变化 | branches 变化 | branch miss 次数变化 |
| --- | ---: | ---: | ---: | ---: | ---: |
| p3 | 1010 | −2.84% | +0.06% | −0.77% | −3.29% |
| p18 | 478 | +1.06% | +0.19% | −0.77% | +1.05% |
| p10 | 398 | −1.02% | −0.43% | −5.24% | −12.00% |
| p29 | 374 | −2.50% | −2.41% | −0.26% | +9.58% |
| p26 | 272 | −1.94% | −0.24% | −14.29% | −19.29% |
| p6 | 268 | +0.10% | −0.01% | −0.40% | −0.94% |
| p25 | 158 | −6.91% | −2.16% | −24.82% | −35.34% |
| p27 | 154 | −7.40% | −1.04% | −24.04% | −36.66% |

p25 的 miss 从 813 降为 526 次/eval，p27 从 951 降为 603 次/eval；
相应 cycles 从 213.42k/215.26k 降为 198.68k/199.32k。
这提供了活跃布尔控制流存在可消除成本的实验证据，但不是把全部周期差额
归因于预测失败：取码、代码布局和编译器表达式选择也随候选改变。
p29 的 miss 仅约 50→55，不能只看 +9.58% 就断言其分支退化严重。
p18 仍有约 1350 次 miss/eval，且该候选没有减少，必须另查残余热点。

硬件 cycles 不是纳秒，也不是 Host 时间；不能用这里的 −7% 宣称整个
仿真加速 −7%。普通交错 walltime 与无 PMU 的相邻半周期 timeline 单独
统计。原始结果见
[`实际实现 PMU 汇总`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/alias_full_pmu/results.json)。

#### 实际实现的普通 walltime

沿用 node030 CPU96–127、NUMA1、N=K=32、all-spin、Clang23/O3 和
C=100000。两个独立窗口各四对 AB/BA；每次均通过 Difftest，全部成功
样本保留，不按空闲率、性能或离群程度筛除。普通版本保留原有框架计时，
没有本轮额外的 PMU、batch 或逐步 timeline 探针；构建与仿真串行进行。

| 指标 | A 中位数 | B 中位数 | 八对配对变化中位数 | B 更快 |
| --- | ---: | ---: | ---: | ---: |
| process walltime | 19.975 s | 19.705 s | **−1.493%** | 7/8 |
| Host | 19.9295 s | 19.6655 s | −1.481% | 7/8 |
| 全局 eval 阶段 | 64.728 µs/step | 63.758 µs/step | −2.353% | 6/8 |
| 全局 update 阶段 | 28.308 µs/step | 28.206 µs/step | −0.014% | 4/8 |
| 最大分区全程平均 eval | 53.031 µs/step | 52.420 µs/step | −1.622% | 6/8 |
| 各分区全程平均 eval 之和 | 820.567 µs/step | 812.016 µs/step | −1.137% | 7/8 |

“配对变化”计算为 `median_i(100 × (B_i/A_i − 1))`，不是上表 B、A
两个中位数再相除。两个窗口的 walltime 配对中位数分别为 −0.729%、
−2.303%；八对的完整范围是 −2.804% 到 +2.318%。因此当前可以说是
**有局部机制证据、约 1.5% 的整体改善趋势**，不能宣称每次必然更快，
更不能把 p25/p27 的约 −7% cycles 当作 Host 加速。本轮不修改默认开关，
也不据此改变 Verilator 配置或优先选择特定分区。

结果与功能身份检查见
[`窗口一`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/alias_full_4pairs/summary.json)、
[`窗口二`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/alias_full_repeat_4pairs/summary.json)、
[`八对及固定标签 timeline 汇总`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/full_results.json)。

#### 相邻半周期、关键路径与本轮结论

另做两对独立 timeline，每版 6300 个全线程 step 样本；固定标签仍来自
候选生成之前的独立测量。下表比较同一个分区、同一个锚点 step 及紧邻
下一步，而不是比较 A/B 各自重新选出的最慢样本。

| 分区 | 固定瓶颈步 A / B (µs) | 该步变化 | 两沿合计 A / B (µs) |
| --- | ---: | ---: | ---: |
| p3 | 51.319 / 51.710 | +0.76% | 103.793 / 104.340 |
| p18 | 61.637 / 63.151 | +2.46% | 112.428 / 114.407 |
| p10 | 61.302 / 61.034 | −0.44% | 103.247 / 101.904 |
| p29 | 74.087 / 71.988 | −2.83% | 77.666 / 75.421 |
| p26 | 72.702 / 72.506 | −0.27% | 94.640 / 94.563 |
| p6 | 64.651 / 66.658 | +3.10% | 108.269 / 110.761 |
| p25 | 74.700 / 69.993 | −6.30% | 86.181 / 81.333 |
| p27 | 76.692 / 71.461 | −6.82% | 89.511 / 83.789 |

按各分区实际完成时刻确定每个样本的瓶颈：p25+p27 占比从 9.30% 降到
4.27%，而 B 中 p3、p18 仍占 29.87%、17.27%。因此降低 p25/p27 的
延迟不可能按同样百分比缩短所有 step；其他分区与 update 仍限制总时间。
不过不能只呈现有利项：本组 timeline 的全局 eval 样本均值为
64.162→64.607 µs（+0.69%），没有重现普通八对中的整体 eval 改善；
p3/p6 的纳秒变化也未与独立 PMU 的 cycles 变化完全一致。保留全部样本，
不把不同运行的 cycles、纳秒或条件均值直接拼接为精确因果分解。

额外核实了 B 中 p28 的 4.17% 瓶颈占比。两次 B 各有 80/52 个锚点
step 由 p28 最晚完成，但交集为空。用这 132 个 step 的并集做独立 PMU
匹配复查，p28 的 instructions/cycles 分别为 −5.93%/−8.88%，而普通
两个窗口 p28 平均 eval 的配对变化为 +0.56%/−18.33%。所以目前只确认
时序采样存在不稳定长尾，**不能据此判定 bool 规则造成了稳定的 p28
代码退化，也没有证据把原因指定为某个外部进程**。该检查不用于筛掉原始
样本或美化 walltime，见
[`p28 独立交叉核对`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/p28_tail.json)。

本轮最终保留的判断：

- 纠正“通用 cache miss 主要是 slot 数据访存”的归因；当前 p18/p25/
  p26/p27 更应优先看活跃代码的供指和控制流，p29 则需要另外分析。
- 空 batch 调度不是 p25/p26/p27 瓶颈步的主要开销，不继续优先加 bitmap。
- 类型可证明的 bool alias 确有覆盖漏洞，通用补齐后 p25/p27 的分支计数、
  cycles、匹配步耗时均改善；原型覆盖与真实生成器覆盖已分别核实。
- 普通八对显示约 1.5% walltime 改善趋势，但跨窗口和诊断运行仍有波动。
  只保留现有实验开关下的实现，不改默认，不宣称所有分区或其他 workload
  一定加速。
- 下一优先项是 **p18 的剩余活跃控制流/供指开销**：本候选没有降低其约
  1350 次/eval 的分支预测失败。继续以相同步号对照 Verilator，定位剩余
  分支所对应的通用模式；不启用编译后反馈，也不按 p18 名字加特例。

实际实现共完成 24 次正式 C100000（普通 16、PMU 4、timeline 4）、
8 次 smoke，Difftest/功能签名与输入身份均通过；三项 CTest 及 UBSan
也通过。最终校验见
[`verification`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/verification.json)。

#### 7.39 纯 bool alias 之后的 eager 扩展复核（2026-10-03）

在上一节的纯 bool storage alias 补全之上，曾尝试把“无 helper、无三目/单目
否定、只有一位读取和比较”的表达式也统一改成非短路 `&`/`|`。这是语法上
通用的候选，不按分区或信号挑选；但“无副作用”不等于“无额外工作”，改成
eager 后会失去短路跳过右操作数的机会。

修正 `static_cast<T>` 误识别后，仍以 node030 CPU96--127、NUMA1、N=K=32、
all-spin、Clang23/O3、C=100000 做了多组交错 AB/BA 和功能签名检查；结果
没有形成稳定收益，因此不进入主线，也不把这些否决候选作为后续基线保留。
这说明仅凭生成表达式的语法纯度不足以决定 eager 是否划算，短路行为本身
也是成本模型的一部分。

当前保留的仍是 `simpleBoolOperandRef` 的纯 alias 覆盖补全，
`bool_eager_logic` 默认关闭状态不变。比较门控代码已从 emitter 和 fixture
移除；撤回后重新编译，受影响的 `emit-grhsim-cpp` 与
`emit-grhsim-cpp-memory-fill` 回归均通过。

### 7.40 纯 bool alias 基线上的 p18 定向归因与选择运算原型（2026-10-03）

本轮保持 §7.38 的完整纯 bool alias 补全为基线，不叠加 §7.39 的扩大
eager 候选。基线 ELF 为 `a3b5feaeddf68ecd…`，archive 为
`af8e72db295695fa…`；Verilator 仍为冻结的 Clang23/O3、最终 all-spin
版本 `9ab8112408aefc66…`。以下两个新候选**分别从该基线构建，没有互相
叠加**，均检查全部 32 分区，不按分区、RTL 模块或信号名单选择。

#### 相同步号的定向采样：compute 分散，commit 的错分支密度较高

继续使用候选产生前已经保存的独立瓶颈标签：每次 C100000 固定选中
239 个 p18 step。只在这些 step 的 p18 eval 内开启线程本地 PMU 采样，
不采 all-spin。cycles 和 branch-misses 各四对交错，每后端、每事件
956 个 eval；只替换外围 wrapper，模型对象保持冻结。采样间隔分别为
250003 cycles、2047 branch misses，所有正式采样均无丢失、无限流，
running/enabled=1。低密度 IP 样本只作函数/代码邻域归因，存在 skid，
不是逐条指令的精确归因，更不能用其百分比预测 walltime。

| 相同 p18 瓶颈步，每 eval 平均 | GrhSIM | Verilator | G 相对 V |
| --- | ---: | ---: | ---: |
| cycles | 190387.8 | 177345.8 | +7.35% |
| branch misses | 1370.10 | 730.92 | +87.45% |

这是**当前关键半周期**的计数，不含相邻半周期，也不替换 §7.36 的两沿
总量对照。cycles 与 branch misses 来自独立运行，不能相乘或相减推导
精确 stall 周期。

GrhSIM 的 727 个 cycles IP 样本中，compute 占 77.03%，commit 占
17.47%，模型 eval 调度占 2.20%，模型函数外占 3.30%。最大单函数
`commit_256` 为 15.54%；没有一个 compute 函数独占主体。638 个
branch-miss IP 样本中，compute/commit 分别占 54.23%/42.95%。所以
commit 是高密度错分支区域，但只处理它仍不能覆盖主要计算时间。
Verilator 的函数分类边界不同，不能把它的 `nba_sequent` 直接等同于
GrhSIM commit，再对两个分类比例做成本相减。

#### 候选 A：取消 compute 活动判断的统一 unlikely 提示

在所有 compute batch 中，仅去掉 `activeWordFlags` 判断上的 `unlikely`；
保留判断、激活内容、执行顺序、commit 的状态变化提示及其他代码。总共
6859 个源文件、59289 个 guard；6858 个 archive member 改变，596 个
不变。源代码来自完整 alias overlay 与冻结 package，而非缺少既有
commit-demand 改写的原始新生成目录；逆变换核对不夹带其他改动。

两个窗口共 12 对普通 C100000 AB/BA，另两对固定标签 PMU。普通版只
保留原有框架计时，不带本轮 IP/PMU 探针。

| 指标 | A 基线中位数 | 候选 A 中位数 | 配对变化中位数 | 更快次数 |
| --- | ---: | ---: | ---: | ---: |
| process walltime | 16.240 s | 16.110 s | −0.648% | 11/12 |
| Host | 16.2025 s | 16.0725 s | −0.619% | 11/12 |
| 全局 eval | 51.827 µs | 51.266 µs | −1.232% | 12/12 |
| 全局 update | 23.891 µs | 24.024 µs | +0.864% | 2/12 |

配对变化始终是 `median_i(100 × (candidate_i/baseline_i − 1))`，不是
两个独立中位数之比。walltime 两窗口分别为 −0.679%、−0.615%；全部
样本的 walltime 算术均值为 16.2308→16.1367 s。

这项小幅整体收益**不是 p18 改善**：固定瓶颈步 PMU 中，p6/p29 cycles
分别为 −3.54%/−2.48%，p18 则为 +2.81%，其 branch misses 只少 0.65%。
普通 p18 全程 eval 配对中位变化为 +0.19%。p29 的 branches 少 18.26%，
branch misses 却从 55.28 增到 89.38；再次说明“错分支百分比”不能脱离
绝对量和其他成本判断。保留此独立原型，不把它叠入 p18 分析基线。

#### 候选 B：便宜的零/标量选择项，避免再次变成条件跳转

定向样本的代码邻域包含如下通用模式：

```cpp
result = (c0 ? stored_value0 : 0) | (c1 ? stored_value1 : 0) | ...;
```

这里的条件是已存好的 bool，非零分支是已物化的标量读取，不是需要按需
执行的大表达式。现有 `grhsim_mux_u64` 本来就用掩码 AND/OR 表达选择，
但这**不能保证最终机器码不分支**。本轮进一步追到了具体编译阶段：

- 用同一 Clang23.1.2 重编 p18/b167，生成对象与冻结 archive 对应 member
  的 SHA-256 完全相同；排除用不同编译设置解释源码的情况。
- `X86 cmov Conversion` 前后 dump 中，JCC 数从 15 变为 40，CMOV 从
  38 变为 13，即该阶段增加了 25 个条件跳转。最终基线汇编为 47 JCC、
  13 CMOV；仅为诊断而关闭这个编译 pass 后为 22 JCC、38 CMOV。
- 对应 LLVM revision `85ac560262434c9ccfc0c183ec22d4138ed647fb`
  的实现默认允许把带访存的条件移动转成分支，并跳过带 unpredictable
  标记的候选。这是成本决策，不是仿真逻辑错误。见
  [对应版本的编译 pass](https://github.com/llvm/llvm-project/blob/85ac560262434c9ccfc0c183ec22d4138ed647fb/llvm/lib/Target/X86/X86CmovConversion.cpp)
  和 [Clang 提示说明](https://clang.llvm.org/docs/LanguageExtensions.html#builtin-unpredictable)。

候选 B 只对 OR 表达式中的“bool 叶子条件、一个零分支、一个声明可证明
的标量叶子分支”的 mux 使用 `__builtin_unpredictable` 选择提示；无该
builtin 时退回普通选择。保留所有参数表达式和求值语义，不处理复杂
helper、宽数组、长优先选择链或有副作用的调用，也不全局禁用编译 pass。
当前是生成物上的结构原型；正式 emitter 规则尚未落地，不能把字符串
原型当作已完成的 IR 结构化实现。

规则扫描全部 32 分区，31 个分区的 1802 个源文件中命中 175166 个项；
实际上只有 23 个分区的 363 个对象发生变化，其余 7091 个 member 不变。
p18 命中 13852 个项，20 个对象改变。说明多数位置原来就已经得到相同
机器码，静态匹配数量不能当作动态优化工作量。

| p18 代表性 batch | 基线 JCC | 候选 B JCC | 基线 CMOV | 候选 B CMOV |
| --- | ---: | ---: | ---: | ---: |
| b163 | 57 | 20 | 61 | 91 |
| b167 | 47 | 23 | 13 | 37 |
| b182 | 19 | 19 | 72 | 72 |
| b197 | 148 | 56 | 103 | 243 |

固定 239 步、两对独立 PMU 的 p18 平均值如下；两个运行窗口中的 cycles
变化分别约 −2.20%/−1.25%，方向一致。

| p18 固定瓶颈步 | 纯 alias 基线 | 候选 B | 变化 |
| --- | ---: | ---: | ---: |
| cycles | 190566.55 | 187266.99 | −1.731% |
| instructions | 278314.82 | 278327.01 | +0.004% |
| branches | 11143.54 | 10923.07 | −1.978% |
| branch misses | 1364.29 | 1283.12 | −5.950% |

这支持“部分选择项的控制流成本确实下降”，不是靠少计算 RTL 逻辑或删除
性能计数器。p25/p27 固定步 cycles 也约少 1.79%/1.97%；但 p3 的同一步
PMU cycles 反而多 1.62%，不能选择性只报告有利分区。

普通运行共 16 对，分成 8+4+4 三个窗口。最后四对是遇到长尾后追加的固定
交错确认，前面的样本全部保留，没有按速度或空闲率筛除。

| 普通运行指标 | 基线中位数 | 候选 B 中位数 | 配对变化中位数 | 更快次数 |
| --- | ---: | ---: | ---: | ---: |
| process walltime | 16.225 s | 16.170 s | −0.247% | 10/16（另 1 对持平） |
| Host | 16.1935 s | 16.1345 s | −0.293% | 10/16 |
| 全局 eval | 51.858 µs | 51.5265 µs | −0.395% | 13/16 |
| 全局 update | 23.963 µs | 23.8855 µs | −0.239% | 11/16 |

必须保留长尾边界：第二窗口 pair03 为 16.72→19.61 s（+17.28%），
eval/update 同时变长；功能签名正确、输入身份未变。该次进程 CPU 使用率
约 3193%，无 major fault，不能据此指定某个外部进程为原因。包含此样本的
walltime **算术均值反而是 16.2556→16.3875 s**，平均配对变化 +0.781%。
最后四对的配对中位数为 −0.247%，3/4 更快，但这不授权删除之前的长尾。
因此最终判断是：**局部机制收益已确认；约 0.25% 的中位数趋势不足以
宣称稳定整机加速或启用默认**。

#### 本轮结论、验证与后续边界

本轮新增 80 次正式 C100000、18 次 C100 smoke 均通过 Difftest/签名检查；
普通、采样、PMU 与本任务编译串行，固定 node030 CPU96--127、NUMA1、
N=K=32、all-spin、ASLR off、Clang23/O3。独立标量语义测试覆盖 1/7/8/
16/32/63/64 bit、零/非零条件和两种零分支方向，builtin 与 fallback
各 560 万个 select 在 UBSan 下通过。没有修改 Verilator、RTL 或默认配置。

两个实验的源文件与链接身份、固定标签、所有成功样本和汇总集中在
[`p18_followup_results.json`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/p18_followup_results.json)。
复现入口为同目录 `p18_ip_profile.py`、`activity_hint_candidate.py`、
`scalar_mux_candidate.py`、`activity_probe.py`；编译阶段证据见
[`leaf_mux_codegen/results.json`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/leaf_mux_codegen/results.json)。

当前正式探索基线仍保持纯 bool alias 补全，两个新原型都不进入默认，
也不把两个收益百分比相加。后续优先把零/标量 OR 选择项的判定落实到
IR 的类型、常量和使用关系，复核真实生成器覆盖后再做完整对照；活动
提示方向则应区分“空 batch 快速返回”和“已活跃 batch 内部执行”，不再
把统一取消提示当成 p18 优化。约 6% 的错分支减少只解释了残余的一部分，
尚不能据此宣布 p18 的供指或控制流问题已经解决。

最终校验口径补充：80 次正式运行均逐条核实了 `Difftest enabled` 和
C100000 功能签名；18 次 C100 只作启动/功能 smoke，不将尚未进入差分
执行阶段的 smoke 计入 Difftest 覆盖。上述计数不含调试采样器时的未验收
运行。文档新增的本地链接已核验，全部本轮构建和仿真进程已结束。

### 7.41 零标量 OR 选择项的 IR 实现与复测（2026-10-03）

承接 §7.40 的候选 B，现将选择项提示实现到 GrhSIM emitter；继续以纯
bool alias 补全为实验基线，不叠加候选 A 的活动提示修改。新选项
`scalar_leaf_mux_unpredictable` / `WOLVRIX_GRHSIM_SCALAR_LEAF_MUX_UNPREDICTABLE`
**默认关闭**，attribute 优先于环境变量，Verilator 路径不变。

不再用“生成 C++ 同一行存在 `|`”决定是否优化，而是检查 IR 与当前
生成上下文。`kMux` 的三个 operand 分别为条件、条件为真时的值、条件
为假时的值；例如 `MUX(c, x, 0)` 即 `c ? x : 0`。命中条件为：

- 结果为 1–64-bit 逻辑值，条件为已计算好的 1-bit 标量读取；
- 一条数据分支是 IR 中确定的零常量，另一条为已计算好的标量读取；
- 结果直接供给标量按位 `kOr`，例如 `OR(MUX(c,x,0), MUX(d,0,y))`；
- 只在普通 compute 生成路径启用，不改变 commit、活动传播和线程框架。

“已计算好”是生成层面的属性，并非保证硬件已把数据载入寄存器：包括
端口、存储引用和已声明的局部临时量；未物化的内联表达式不扩大覆盖。
类型和引用映射决定资格，不依赖用户信号名、模块名、分区名单或编译后
反馈。未知常量、宽值、仅供逻辑 OR 的选择与复杂内联条件/数据保持原路径。

命中时仅将 `grhsim_mux_u64` 换成等长的 `grhsim_sel_u64`，避免原型较长
的函数名扰动表达式长度/物化阈值。新 helper 支持时使用
`__builtin_unpredictable`，否则调用原 helper；保留原 operand 转换、
截断和符号扩展，两者仍先求值函数实参。提示不保证最终无分支或 walltime
收益。接口说明见
[`grhsim-scheduling.md`](../../wolvrix/docs/emit/grhsim-scheduling.md#实验性标量零选择项的编译器提示)。

修正后重新运行的五项 CTest 全部通过：完整 `emit-grhsim-cpp`、新增
`emit-grhsim-cpp-scalar-leaf-mux`、memory-fill、GrhSIM 和 Verilator
repcut package。专项覆盖默认/显式关闭逐文件一致、环境变量及 attribute
优先级、split helper、两种零分支方向、1/7/8/16/32/63/64 bit、符号扩展、
截断、负匹配，以及超过内联容量的多用户使用列表；Clang23 与 GCC 生成
代码均完成带 UBSan 的语义运行。完整日志见
[`leaf_mux_regressions.log`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/leaf_mux_regressions.log)。

下面的性能对照固定为 node030 CPU96--127、NUMA1、N=K=32、all-spin、
ASLR off、Clang23/O3、C100000，预先安排普通 8+4 对 AB/BA 与固定步号
两对 PMU；编译和性能运行串行，所有功能通过的样本均保留。

#### 实际生成器覆盖审计与状态读取补全

第一版 IR 规则保守地排除了所有未物化内联表达式，覆盖 140798 项。
但 p18/b163、b167 的条件跳转数仍为 57/47，未重现 §7.40 原型的
20/23。复核源代码发现，缺失项的数据分支只是展开为状态左值及标量
转换的 `kRegisterReadPort`，并不是尚待计算的算术表达式。

最终实现进一步识别 `kRegisterReadPort` / `kLatchReadPort`，并只沿
当前局部值映射中的同宽 `kAssign` 向前追溯；遇到算术、动态索引或
另一层 mux 即停止。专项新增寄存器/锁存器读取、八层同宽别名、状态
条件以及“别名后实际是加法”的负例，Clang23/GCC + UBSan 均通过。
补全版五项回归日志为 `leaf_mux_storage_focused.log` 和
`leaf_mux_storage_regressions.log`，仍在同一实验目录。

两轮都从冻结 partitioned IR 重新生成 on/off，逐一检查 7552 个 C++/
header 文件：关闭后与纯 alias 原始生成包逐字节相同；开启后只允许
runtime helper 新增和 compute 中等长 helper 名称替换，替换回去后
逐字节恢复。源文件覆盖如下（原型按同一行含 `|` 的旧条件重新审计）：

| 覆盖项 | 初版 IR | 补全状态读取的最终 IR |
|---|---:|---:|
| 命中选择项 | 140798 | 172997 |
| 变化 compute 文件 | 1450 | 1682 |
| 与旧原型共同命中 | 140748 | 172875 |
| 仅 IR 规则命中 | 50 | 122 |
| 仅旧原型命中 | 34418 | 2291 |
| 实际变化 archive object | 286 | 356 |
| 其余 object 字节一致 | 7168 | 7098 |

最终 p18 命中数与原型都是 13852，但共同项为 13851：删去了一个结果
先进入另一层 mux、仅因同一行有 OR 而误归类的项；补进了一个从输入
端口经同宽别名读取的真实 OR 选择项。全图剩余差异也说明两者并非同一
候选，不把“原型已经测过”当成实现版已获验证。

最终 p18 的静态指令特征恢复到原型方向：

| compute batch | 基线 JCC / CMOV | 初版 IR | 最终 IR |
|---|---:|---:|---:|
| b163 | 57 / 61 | 57 / 61 | 20 / 91 |
| b167 | 47 / 13 | 47 / 13 | 23 / 37 |
| b182 | 19 / 72 | 19 / 72 | 19 / 72 |
| b197 | 148 / 103 | 56 / 243 | 56 / 243 |

JCC 是静态条件跳转指令数，CMOV 是静态条件移动指令数，不是动态执行
次数。覆盖不完整的初版也按预定 12 对普通运行及两对 PMU 完成，所有功能
通过的数据保留：walltime 配对中位数 −0.497%，11/12 更快；p18 固定步
cycles −0.380%、branch misses −3.002%。这一初版的整机收益不能作为
补全版收益，也不能与补全版百分比叠加。

两版都基于冻结纯 alias archive 替换变化 compute object，未命中的
冻结 compute/commit、先前保留的 demand 优化、公共 wrapper 和调度均
保留；所有 object 名集合不变，变化集严格限制在审计过的 compute 内。
最终 1682 个源文件增量编译用时 40.408 s，非全量编译时间。

#### 最终实现：12 对 walltime 与固定瓶颈步 PMU

最终版本以纯 bool alias 为 A、状态读取补全后的 IR 提示为 B，完成
两个预定窗口（8 对、4 对），每个窗口内部 AB/BA 交错。未与 §7.40 的
活动提示叠加，也未将初版当成 A。全部 24 次正式普通运行功能通过，
Host 固定 CPU105/part9、worker-to-part 映射相同，未删除任何成功样本。

| 指标 | A 的中位数 | B 的中位数 | 配对变化中位数 | B 更快 |
|---|---:|---:|---:|---:|
| 进程 walltime | 16.165 s | 16.020 s | −0.928% | 12/12 |
| Host | 16.131 s | 15.9905 s | −0.905% | 12/12 |
| 全局 eval / step | 51.759 µs | 51.086 µs | −1.050% | 12/12 |
| 全局 update / step | 23.854 µs | 23.776 µs | −0.407% | 11/12 |

“配对变化中位数”先逐对计算 `100 × (B_i / A_i − 1)`，再对 12 个
百分比取中位数，**不是**把表中两个绝对中位数相除。walltime 算术均值
为 16.17167→16.03167 s，平均配对变化 −0.865%；两个窗口各自的配对
中位数 −0.928% / −0.713%，均无长尾样本删除。普通整段平均的 p18 eval
为 32.578→31.4645 µs，配对中位数 −3.229%；它与下表只挑独立固定瓶颈
步号的 PMU 口径不同，不能把二者当作同一比例。

固定步标签沿用此前独立观测的 `labels.json`，没有根据候选再挑更慢或
更快的步。两对 AB/BA 每侧采样相同事件组，所有 `running/enabled=1`：

| 分区 | 每侧样本数 | cycles A→B | cycles 变化 | instructions 变化 | branch misses 变化 |
|---|---:|---:|---:|---:|---:|
| p3 | 1010 | 160338.7→158370.4 | −1.228% | +0.0003% | +0.662% |
| p18 | 478 | 190123.5→188045.5 | −1.093% | +0.0044% | −5.160% |
| p10 | 398 | 185293.3→182756.5 | −1.369% | −0.0083% | −0.589% |
| p29 | 374 | 192647.8→191558.1 | −0.566% | −0.0001% | −3.439% |
| p26 | 272 | 190073.4→188404.3 | −0.878% | +0.0994% | −4.674% |
| p6 | 268 | 201225.1→201210.9 | −0.007% | −0.00002% | +1.501% |
| p25 | 158 | 187211.3→180545.4 | −3.561% | +0.0672% | −8.529% |
| p27 | 154 | 190369.7→188161.6 | −1.160% | +0.1977% | −5.944% |

p18 的平均错分支为 1364.613→1294.195 次/所选 eval，动态 branches
11143.533→10923.048（−1.979%），而 instructions 几乎不变，支持减少
不必要控制流的解释。p3/p10 的 cycles 也下降，但错分支没有同等变化，
因此不将全部 cycles/walltime 收益单因归结为该提示；代码布局、缓存和
多线程运行条件的间接变化仍混在整体测量中。

本轮结论：IR 实现已能复现主要局部机制，并在这批 XiangShan 数据上
取得约 0.9% 的小幅 walltime 收益；尚不是跨 workload/编译器普适收益的
证据，**保持实验选项默认关闭，正式探索基线仍为纯 bool alias**。
不继续为了贴近文本原型而放宽到嵌套 mux、任意内联运算或模块特例。
下一步更值得重新采样补全版的残余热点，优先检查此前 p18 的大 commit
函数及其状态变更/活动传播控制流；本轮没有改变 commit，不能宣称该部分
错分支或供指瓶颈已解决。候选更新后仍应与 Verilator 同步号对照，而不是
用这次 GrhSIM A/B 的百分比替代 GrhSIM/Verilator 差距。

#### 验证与复现入口

初版与补全版合计 56 次正式 C100000 均核实 `Difftest enabled`，终态
PC `0x80000c0c`、instructions 240349、cycles 99996、guest cycles 100001、
steps 200102；另有 12 次 C100 启动 smoke，不计入 Difftest 执行覆盖。
最终源码、冻结生成器、二进制和输入身份已校验，五项 CTest 及新增语义
测试均通过，所有本轮生成、编译和仿真进程已结束。没有修改 RTL、
Verilator 默认路径或开启新的默认优化。

- [最终完整结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_leaf_mux_storage/results.json)、
  [初版结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_leaf_mux/results.json)、
  [最终校验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_leaf_mux_storage/verification.json)。
- [覆盖审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_leaf_mux_storage/audit.json)、
  [编译及 object 身份](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_leaf_mux_storage/candidate/build.json)。
- 生成/审计/重建入口：`active_dispatch_20261003/emitter_leaf_mux.py`；固定
  测量入口 `run_emitter_leaf_mux.py`；完整验证入口 `validate_leaf_mux_storage.py`；
  参数 `LEAF_MUX_VARIANT=emitter_leaf_mux_storage` 指向补全版，不覆盖初版。
- 共同基线普通二进制 SHA256 为
  `a3b5feaeddf68ecd24700b4bebf4c42b6c0402c2dd0f0eec8fda114a63206ac6`；
  最终候选为
  `16b2fb9ff7f22127ffdbd8d5d5e130e4752ab3d93003d034bf893c791ea87916`。

### 7.42 补全版 p18 残余 commit 路径的固定指令采样（2026-10-03）

承接 §7.41 的最终 IR 版本，先不改变 emitter，重新对同一组预先固定的
239 个 p18 瓶颈步做 GrhSIM 内部 IP 采样。A 是纯 bool alias 补全基线，B
是状态读取别名补全后的 `scalar_leaf_mux_unpredictable` 候选；两边只替换
`common/eval_0` 探针包装，模型对象、分区、调度和输入身份冻结。node030
CPU96--127、NUMA1、C=100000、4 对 AB/BA；两种事件各 4 次正式运行，
每次均核实 239 个区间、`enabled=running` 和 Difftest。

每版共收集 956 个固定区间。cycles 的 IP 样本中，compute/commit/model
eval/框架外部分别为 A 的 559/119/15/13（79.178%/16.856%/2.125%/
1.841%），B 的 574/113/12/19（79.944%/15.738%/1.671%/2.646%）。
`eval_commit_batch_256()` 是两边最大的提交函数，样本占比 14.59%→13.37%；
`eval_commit_batch_255()` 为 2.27%→2.37%。这说明最终选择项规则继续改善
compute 后，剩余 commit 成本仍集中在大而重复的状态提交函数，但不是单个
RTL 信号或单个选择表达式。

branch-misses 采样更直接地支持控制流归因：固定区间总错分支事件
1,306,351→1,260,046（−3.545%）；错分支 IP 样本中 commit 占
45.283%→43.974%，其中 `eval_commit_batch_256()` 占 38.21%→37.79%，
`eval_commit_batch_255()` 占 7.08%→6.19%。静态源代码显示 c256 含约
6383 个逐标量 `state != next_value` 变化判断，另有大量活动字检查和
`supernode_active_curr_` 写入；采样地址分散在整个函数（不是一个可孤立
替换的长链）。

固定区间的原始 cycles 计数为 176,941,180→179,718,943（+1.570%），
与 §7.41 无探针生产 PMU 的 p18 cycles −1.093% 不同。探针同时增加了
perf 开关、读数和采样环形缓冲操作，且 AB/BA 的频率/线程相位会影响该
区间；因此这里只采用 branch-misses 的结构性线索，不把区间 cycles 当作
候选收益，也不替代无探针 walltime。报告见
[`cycles IP 归因`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/p18_final_ip/cycles/report.json)、
[`branch-misses IP 归因`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/p18_final_ip/branch-misses/report.json)，
复现入口为同目录 `p18_final_ip.py`。

本检查点的结论是：下一步应研究**同一合法 event/update guard 和有序提交
范围内的激活掩码累计/批量 flush**，减少重复的 active-byte read-modify-write
及相关分支；必须在后续消费者可能读取前 flush，保持多写者顺序、精确
`touchedWriteCount` 和无变化语义。仅凭本轮数据不能证明
`commit_state_change_unlikely` 方向错误，也不应盲目取消所有 `unlikely` 或
按 p18/c256 名称特判。该方向若实现，仍需先做 IR/依赖约束和小模型回归，
再进行全图 AB/BA；当前没有修改默认选项或提交新的 commit 优化。

#### 增量更新：在最终选择项候选上复测同 reader 分组（2026-10-03）

先勘误上面的运行次数：cycles、branch-misses **各 4 对 AB/BA，即每种事件
8 次正式运行**，两种事件合计 16 次；每种事件每版 4 次、956 个固定区间。
上面的样本量和事件总量不变。

本轮先复用 §7.26 已有、默认关闭的 `commit_scalar_same_reader_groups`，
验证当前残余热点是否仍能从精确激活合并受益，而不是直接引入更宽泛的累计器。
**A 为 §7.41 最终 leaf-mux 候选**（包含纯 bool alias 补全及冻结线既有的
按需计算）；B 仅叠加同 reader 分组。不是重新与纯 alias 或 Verilator 比较，
也不能将本轮收益与 §7.41 的 −0.928% 相加。

这里的 reader 指“某个状态变化后需要重新计算的消费者”，不是宿主线程。
如果连续几个寄存器的完整消费者集合相同，就可先分别比较新旧值，然后共用
一个变化分支和一次消费者通知。示意如下（省略精确计数器，`n0/n1` 已算好）：

```cpp
// 原来：两次变化判断、可能两次通知相同的消费者 R。
if (q0 != n0) { q0 = n0; activate(R); }
if (q1 != n1) { q1 = n1; activate(R); }

// 分组：保留每个 changed 值，任一成员变化才写回并通知一次。
const bool changed0 = q0 != n0, changed1 = q1 != n1;
if (changed0 || changed1) { q0 = n0; q1 = n1; activate(R); }
```

实际规则仍为同一 event/update guard、连续 2..8 个单写者、全掩码、最多
64 bit 普通寄存器，且完整 reader active-ID 集合相同。直接状态引用、部分
掩码、多写者、宽状态、latch、memory、reg-to-mem intent storage 等回退；
既有 lockstep 优先。保持写回顺序、逐成员 `touchedWriteCount`、无变化不写回
不激活及原有 profile 语义。代价是“组内有人变化时，未变化成员也会写回相同
值”，不能仅凭减少分支就认定所有分区都受益。

**生成与身份审计。** 全部 32 个分区统一启用，无分区/信号名单。对照 7552
个生成文件，只有 130 个 commit 源文件变化，compute 和头文件不变；将该
delta 合入冻结线后，逆变换审计逐组验证旧 next 表达式、状态对象、顺序及
精确 activation 集合，并还原到冻结源文件，确认没有丢失既有按需计算。
共 28014 组、111473 个标量写入；组大小 2..8 的数量依次为
13182/3362/2950/917/761/664/6178。p18 的 c255 为 12 组/35 个写入，
c256 为 494 组/2171 个写入。

最终 archive 共 7454 个对象，130 个变化、7324 个逐字节相同；A SHA256
为 `78e0639abb1688b3516b02eae690c0eec26bb06fcaa20b538ff050ee8c645587`，
B 为 `63299300ceebe09cffa35deeedcb739f58cfda2644a27113d1c21f8e08c23173`。
archive 大小 122688788→119563812 byte（−2.547%）。p18/c256 反汇编
静态指令数 56313→47746（−15.213%），条件跳转 12768→10670（−16.432%）；
静态减少量不能直接当作动态减少量或 walltime 收益。

**普通版 C=100000。** node030 CPU96--127、NUMA1、N=K=32、all-spin、
Clang23/O3、ASLR 关闭；Host CPU105、worker/part 映射及输入保持一致。
两轮各 8 对 AB/BA，共 16 对、32 次正式运行全部通过 Difftest，保留所有
成功运行，包括较慢样本和并列样本。两轮 walltime 配对变化中位数分别为
−0.409%/−0.715%；合并结果如下。

| 普通版指标 | A 中位数 | B 中位数 | 16 对变化中位数 | B 更快 |
| --- | ---: | ---: | ---: | ---: |
| walltime | 16.010 s | 15.910 s | −0.626% | 12/16 |
| Host | 15.9715 s | 15.8735 s | −0.640% | 13/16 |
| 全局 eval/step | 50.9855 us | 50.6020 us | −0.682% | 14/16 |
| 全局 update/step | 23.7620 us | 23.6505 us | −0.453% | 11/16 |

变化列为 `median(100*(B_i/A_i-1))`，不是左右两列中位数直接相除。
walltime 另有 2 对并列、2 对变慢；算术均值为 16.0175→15.9225 s。
各线程全程平均 eval 也并非普遍改善：

| 分区 | A eval/step 中位数（us） | B（us） | 配对变化中位数 | B 更快 |
| --- | ---: | ---: | ---: | ---: |
| p3 | 44.2955 | 44.1365 | −0.341% | 10/16 |
| p6 | 37.2110 | 36.4005 | −2.190% | 16/16 |
| p10 | 30.9680 | 30.5170 | −1.436% | 15/16 |
| p18 | 31.4160 | 31.0865 | −0.970% | 15/16 |
| p25 | 18.4300 | 18.8810 | +2.414% | 0/16 |
| p26 | 26.5825 | 26.8085 | +0.823% | 0/16 |
| p27 | 18.7345 | 19.2005 | +2.273% | 0/16 |
| p29 | 15.8325 | 15.8785 | +0.297% | 6/16 |

以上是各次运行“全 step 均值”的跨运行统计，不是成为瓶颈时的条件均值。
全 32 个分区的 eval/update 数据均保留在汇总 JSON，不能只摘收益分区。

**固定历史瓶颈步的 PMU。** 独立做 2 对 AB/BA，仍使用之前固定的
`labels.json`，不按本轮快慢重选样本。每版每个分区的区间数见表；全部
running/enabled=1，无事件复用。探针只替换 common/eval 包装对象，模型
对象保持对应 A/B 身份。事件变化是合并同一固定步集合后的均值比值。

| 分区 | 区间数/版 | cycles A→B | cycles 变化 | instructions 变化 | branches 变化 | branch-misses 变化 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| p3 | 1010 | 159809→156411 | −2.127% | −0.903% | −6.694% | −13.923% |
| p18 | 478 | 188777→182846 | −3.142% | −0.243% | −2.944% | −10.331% |
| p10 | 398 | 184259→178401 | −3.179% | −1.244% | −11.852% | −7.444% |
| p29 | 374 | 190396→187270 | −1.642% | 约 0 | 约 0 | +1.815% |
| p26 | 272 | 189728→186539 | −1.681% | 约 0 | 约 0 | −3.465% |
| p6 | 268 | 202522→194501 | −3.961% | −0.200% | −1.979% | −19.138% |
| p25 | 158 | 184843→186892 | +1.109% | 约 0 | 约 0 | +9.028% |
| p27 | 154 | 188115→190683 | +1.365% | 约 0 | 约 0 | −5.559% |

p18 固定步每区间错分支从 1289.88 降到 1156.62，结合 commit 静态跳转
缩减，支持“合并重复变化分支和 activation”确有机制收益。但固定步 PMU
与普通版全程平均是不同统计；尤其 p26 的 PMU 改善不能抹去普通版退化，
也不以探针版耗时替代普通版 walltime。

**半周期进一步核对。** harness 的 reset 和正常单周期均为先 clock=1 再
clock=0，框架 step_count 从 0 开始并在 eval 前递增，因此本实验奇数步为
上升沿、偶数步为下降沿。冻结标签中 p18 的 239 步、p10 的 199 步全部为
上升沿；p25/p26/p27 的 79/136/77 步全部为下降沿。其最大的 commit
函数受 `hot_event_posedge_` 守卫，分组主要减少上升沿提交工作，不直接减少
下降沿主要 compute 工作。

重新按边沿汇总已有周期采样（去掉首个 step127；每版每沿 1574 个区间，
这张表**不限于成为瓶颈的步**）：

| 分区 | 上升沿 instructions 变化 | 上升沿 cycles 变化 | 下降沿 instructions 变化 | 下降沿 cycles 变化 | 下降沿 branch-misses 变化 |
| --- | ---: | ---: | ---: | ---: | ---: |
| p18 | −0.318% | −3.186% | 约 0 | −1.067% | −2.172% |
| p25 | −2.076% | −0.796% | 约 0 | +1.524% | +11.812% |
| p26 | −0.331% | −4.362% | 约 0 | −1.672% | −2.467% |
| p27 | −2.400% | +0.263% | 约 0 | +1.364% | −5.591% |

这更支持“p25/p27 的长半周期没有直接少算，收益主要没打中该半周期”，
而不是“它们的退化必然来自新增计算”。p25 的下降沿错分支增加可作为后续
线索；p27 却在错分支减少时变慢，说明不能统一归因于 branch miss。
虽然 compute 对象逐字节相同，重新链接后的地址布局、取指/预测状态及
跨半周期/线程相位仍可能影响执行；本轮尚未把这些间接因素逐项分离，
不宣称已经证明某一个原因。

**验证与结论。** 32 次普通版、4 次固定步 PMU 的正式 C100000 均通过
Difftest，另有上述三组运行各两次 C100 smoke，以及最终整图 C1000 smoke
通过。功能签名统一为 PC `0x80000c0c`、instructions=240349、cycles=99996、
guest_cycles=100001、steps=200102。Clang23 下六项 CTest 全部通过
（529.54 s）：完整 `emit-grhsim-cpp`、scalar-leaf-mux、commit-same-readers、
memory-fill，以及 Verilator/GrhSIM repcut package 两项。

当前结论是小幅正向的增量收益，不能据此声称提交瓶颈已经解决或分组普遍
有利。p3 仍为最大平均 eval 分区且只改善约 0.34%，p25/p26/p27 的普通版
退化真实保留；不按分区名关掉规则，不盲目扩大 group 大小或改成无条件写回。
保留默认关闭的实验选项，纯 alias、leaf-mux 和本轮组合的身份继续分开，
不修改 Verilator 或主线默认。下一步应优先区分下降沿残余 compute 的取指/
布局/分支效应，并检查 p3 当前关键路径，再决定是否设计更一般的激活累计。
这些是诊断方向，不引入编译后反馈作为优化规则。

数据与复现入口：
[`完整汇总（含全部分区 eval/update、半周期 PMU 与身份）`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/same_reader_leaf_mux/results.json)、
[`逐组逆变换审计`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/same_reader_leaf_mux/audit.json)、
[`六项回归`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/same_reader_leaf_mux/regressions.log)。
同目录上一级的 `same_reader_leaf_mux.py` 负责生成及冻结 delta 构建，
`audit_same_reader.py` 负责语义/范围审计，`same_reader_probe.py` 负责 PMU，
`same_reader_results.py` 负责完整汇总及身份/运行签名核验。原始普通版窗口为
`same_reader_leaf_mux/8pairs_fixed` 和 `same_reader_leaf_mux/repeat_8pairs`；
PMU 为 `same_reader_leaf_mux/pmu/runs`。

#### 增量更新：下降沿退化的布局对照（2026-10-03）

继续以上一小节的最终 leaf-mux 为 A、leaf-mux + 同 reader 分组为 B，
本轮只诊断差异来源，不修改 emitter、默认选项或 Verilator。首先核实一个
容易遗漏的变量：**对象文件相同，不等于链接后的执行地址相同。** 正常布局
中，6859 个 compute 函数有 6625 个入口移动；每个分区内部的平移量一致，
来自前面分区 commit 代码的缩小。p25/p26/p27 分别前移
2915424/2957120/2980688 byte，其中 p25/p27 的 64-byte 内位置也改变了
32/16 byte。这不是它们的 compute 算法变了，而是链接布局发生了连带变化。

为做消融，建立 **padded 对照**：对全部 130 个变化的 commit 对象，仅在
原 `.text` 尾部增加不执行的 NOP，将该 section 大小补到 A 的大小，共
3143593 byte；不改原指令、控制流、状态写入或通知，也不按分区挑选。
A 重新链接后的 ELF 与原 A SHA256 完全一致（`16b2fb9f…87916`），B 的
compute 入口全部恢复到 A 的地址。正常布局和 padded 布局都独立做 A/B，
避免把“改算法”与“变更对照组”混在一起。

进一步逐字节核验：padded 两版仍有 3164 个 compute 函数的链接后字节
不同，共 34311 byte，但全部落在 PC-relative 重定位操作数内，目标为
`.rodata`、`.rodata.cst16` 或 `.rodata.cst32`；没有未解释的 opcode/指令
顺序/长度差异。96 个 commit 内部的 lambda 函数位置仍有变化。因此该
对照固定了 compute 入口和指令布局，**并未固定常量池地址、提交内部布局、
缓存/预测历史或所有运行态条件**，不能据此声称做到了全部微架构状态一致。
静态证据见
[`自然布局`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/same_reader_diagnostics/padded/natural_layout.json)、
[`补齐布局`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/same_reader_diagnostics/padded/padded_layout.json)、
[`重定位字段审计`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/same_reader_diagnostics/padded/relocation_audit.json)。

测量协议为 node030 CPU96--127、NUMA1、N=K=32、all-spin、Clang23/O3、
ASLR 关闭、C100000；沿用同一 image/NEMU 和固定历史瓶颈标签。普通版
分四个窗口，每个窗口每种布局各两对 AB/BA，窗口间交替布局顺序；两布局
各累计八对。branch、指令/数据 L2 miss、pipeline 三种独立 PMU 事件组，
每种布局每组各两对，穿插在普通版窗口之间；构建与测量不重叠，不筛成功
运行或慢样本。PMU 只替换两个 wrapper 对象，compute/commit 使用对应
冻结 archive。首个创建 perf descriptor 的 step127 不参与统计。

事件语义再次按 Linux v6.8 的 Zen4 定义核对：`r0164/r0864` 是指令/数据
请求在 L2 中 miss 的计数；`r1000001a0/r100001ea0` 对应前端未供给和后端
阻塞的派发槽，比例除以 `6 × cycles`，不等于 walltime 百分比，也不能将
前端未供给全部归于 I-cache。定义分别见
[cache 事件](https://github.com/torvalds/linux/blob/v6.8/tools/perf/pmu-events/arch/x86/amdzen4/cache.json) 和
[pipeline 指标](https://github.com/torvalds/linux/blob/v6.8/tools/perf/pmu-events/arch/x86/amdzen4/pipeline.json)。

**运行完成。** 32 次普通版 + 24 次 PMU 的 C100000 正式运行全部通过
Difftest，另有 28 次 C100 smoke 通过；所有正式运行功能签名一致，Host
CPU105、worker/part 映射和 all-spin 配置相同。所有 PMU 区间的
running/enabled=1；测前、测后和最终汇总时均复核 ELF、image、NEMU 与
探针身份。PMU padded 两版的 6859 个 compute 函数入口也逐一确认相同。
本轮没有生产代码变更，不重复运行上一小节已经通过的 emitter CTest。

普通版全局结果如下；每行布局都有自己在邻近时段运行的相同 A，百分比
仍为八对 `median(100*(B_i/A_i-1))`，不是两列中位数直接相除。

| 布局 | 指标 | A 中位数 | B 中位数 | 配对变化中位数 | B 更快 |
| --- | --- | ---: | ---: | ---: | ---: |
| natural | walltime | 16.195 s | 16.140 s | −0.463% | 7/8 |
| padded | walltime | 16.170 s | 16.105 s | −0.339% | 6/8 |
| natural | Host | 16.1635 s | 16.1055 s | −0.461% | 7/8 |
| padded | Host | 16.1375 s | 16.0685 s | −0.352% | 6/8 |
| natural | 全局 eval/step | 52.0260 us | 51.5615 us | −0.914% | 8/8 |
| padded | 全局 eval/step | 51.9145 us | 51.4045 us | −0.752% | 8/8 |
| natural | 全局 update/step | 23.9175 us | 23.7915 us | −0.746% | 5/8 |
| padded | 全局 update/step | 23.6925 us | 23.7975 us | +0.253% | 1/8 |

padded 的 walltime 另有一平一负。两布局的基线 ELF 相同，但测量时段
不同；不可仅看 B 的 16.140/16.105 s 就宣称 padding 进一步加速。按各自
A/B，**没有证明 padding 比自然布局有更好的整机 walltime**。

各线程全 step 平均 eval 的配对变化如下（不是瓶颈条件均值）：

| 分区 | natural 变化 | 更快次数 | padded 变化 | 更快次数 |
| --- | ---: | ---: | ---: | ---: |
| p3 | −0.702% | 5/8 | +0.221% | 3/8 |
| p6 | −2.123% | 8/8 | −2.823% | 8/8 |
| p10 | −1.956% | 8/8 | −0.219% | 5/8 |
| p18 | −0.996% | 7/8 | −1.324% | 8/8 |
| p25 | +2.302% | 0/8 | −1.171% | 8/8 |
| p26 | +0.544% | 0/8 | −0.069% | 5/8 |
| p27 | +0.274% | 2/8 | −0.116% | 4/8 |
| p29 | +0.189% | 2/8 | +0.730% | 0/8 |

p25 的稳定退化被反转，p26/p27 基本回到持平；但 p3/p10 的自然布局收益
也被削弱，p29 更慢，不能只保留 p25 的有利结果。p27 本轮 natural
退化幅度小于上一小节 16 对中的 +2.273%，表明幅度对运行窗口敏感，不能
把上一轮百分比视为固定的算法代价。全部分区和每一对数据均保留。

固定历史瓶颈步的 PMU 更直接：p25/p26/p27 每版分别为 158/272/154 个
区间，全在下降沿；三种事件组中的动态 instructions 均近乎不变，branch
组的 branches 也近乎不变。下表 cycles 和 FE 槽取自同一次 pipeline 组，IC miss 取自独立
miss 组，错分支取自独立 branch 组；不把不同组的计数相加做周期分摊。

| 分区 | natural cycles | padded cycles | natural FE 未供给槽计数 | padded FE 未供给槽计数 |
| --- | ---: | ---: | ---: | ---: |
| p25 | +3.724% | −3.524% | +6.193% | −6.142% |
| p26 | +1.429% | −2.239% | +2.549% | −4.065% |
| p27 | +2.908% | −2.634% | +3.785% | −4.958% |

| 分区 | natural 指令 L2 miss | padded 指令 L2 miss | natural 错分支 | padded 错分支 |
| --- | ---: | ---: | ---: | ---: |
| p25 | +0.088% | −0.643% | +10.663% | +1.648% |
| p26 | −0.365% | −0.820% | −2.467% | −2.832% |
| p27 | −0.324% | +0.351% | −7.773% | −0.920% |

branch 组中 p25/p26/p27 的 cycles 为 natural 的 +3.583%/+1.755%/
+2.760%，padded 的 −2.709%/−2.175%/−3.753%；miss 组中分别为
+4.578%/+1.408%/+2.569% 和 −3.422%/−2.061%/−1.853%。三种独立
事件组的方向一致，但这些插桩区间时间/周期不代替普通版 walltime。

以上支持“布局相关的前端执行效率”是退化的重要因素：恢复 compute
地址和指令布局后，分组算法、状态写入和通知仍相同，下降沿的周期退化与
FE 未供给槽增加同时反转。尤其 p27 在 natural 下错分支和 IC miss 都
减少却更慢，在 padded 下 IC miss 略增却更快，不能仅用 miss 次数解释。
数据 L2 miss 同样不能统一解释：p26 在两布局分别增加 8.59%/17.92%，
cycles 却一个增加、一个减少；p27 则为 −10.89%/+6.41%，方向也不相符。
仍未分离解码/op-cache 带宽、预测恢复、常量池/数据地址及跨沿历史的各自
份额，不将 FE 槽计数变化百分比写成 walltime 变化或某一硬件单元的精确
归因比例。

p18 的直接提交收益没有消失：branch 组两布局的固定步错分支分别下降
10.904%/10.650%，cycles 下降 1.797%/2.362%；普通版 eval 也均改善。
因此当前更准确的判断是：**同 reader 分组有真实的提交收益，但其自然
链接还带来了未修改 compute 的布局得失；不能把二者混成一个“分组好坏”
结论。** 补齐恢复 p25，不代表恢复整个工程最优布局。

下一步优先做不依赖 workload 名称或编译后性能反馈的统一布局规则，例如
预先固定的函数/分区起始对齐、compute/commit 代码分离组织；从小范围的
通用方案开始，全图验证 walltime 和局部得失。禁止把本轮按旧编译尺寸的
padding 作为默认优化，或只对 p25/p27 开关选项。当前维持自然布局和已有
默认设置，保留本对照作归因工具，尚未增加上述正式布局优化。

完整证据为
[`结果及全分区统计`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/same_reader_diagnostics/results.json)、
[`padded 构建身份`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/same_reader_diagnostics/padded/build.json)。
复现脚本为上一级的 `same_reader_diagnostics.py`、
`run_same_reader_diagnostics.py`、`audit_padded_relocations.py` 和
`report_same_reader_diagnostics.py --complete`。原始数据在对应目录
`natural/ordinary_1..4`、`padded/ordinary_1..4`，以及两布局各自的
`pmu/pmu_branches`、`pmu/pmu_misses`、`pmu/pmu_pipeline`。

#### 增量更新：仅试统一 64 字节对齐，收敛布局探索（2026-10-03）

按用户要求，布局方向只做一项小范围通用试验，不扫描对齐值、函数排列或
分区组合。**本轮 A 是上文的同 reader 分组自然布局候选**，B 是相同模型
加统一 64 字节代码段对齐；不是 leaf-mux 单项、纯 bool alias 或 Verilator
基线，也没有使用此前按旧对象尺寸补齐的 padded 版本。

规则预先固定：所有生成模型对象的非空可执行 ELF section，起始对齐提高到
`max(原对齐, 64)`；所有 32 个分区一致，未根据 profile、旧代码尺寸、模块
或信号名称选择对象。这是固定链接布局规则，不是编译后性能反馈。通过
Clang23 的 `llvm-objcopy --set-section-alignment` 修改对象元数据后重链接，
没有重编译模型、改源码或改计算/提交算法。本轮共处理 7418 个模型对象、
8544 个可执行 section，36 个框架/包装对象不变。逐 section 核对指令、
常量、符号及重定位 payload 完全相同，模型函数尺寸不变；最终 6859 个
compute batch 入口全部 64 字节对齐（原为 1715 个）。该结果不表示函数
内部每个 basic block 或 helper 都被重新对齐。

A/B 使用同一组冻结 harness 对象重新链接。A 与上一轮自然候选 ELF 仅
启动 banner 的编译时间有 4 bytes 不同，其余字节完全一致；两版模型和
框架并未混入重新编译的差异。ELF 文件大小由 102346672 增至
102535088 bytes，增加 188416 bytes（0.184%）。生成器、正式默认选项、
Verilator 路径均未改变。

node030 CPU96--127、NUMA1、N=K=32、all-spin、Host CPU105、Clang23/O3、
ASLR 关闭，C100000 共四对 AB/BA。8 次正式运行全部通过 Difftest、2 次
C100 初始化 smoke 通过，正式终态签名与前文相同；输入身份、线程映射及
运行配置核对通过。保留全部成功样本，不做空闲率 gate、挑样或慢值过滤。
这是普通计时版，不额外插入 PMU/timeline 探针；本轮不继续扩展事件采样。

| 指标 | A 中位数 | B 中位数 | 配对变化中位数 | B 更快 |
| --- | ---: | ---: | ---: | ---: |
| walltime | 16.330 s | 16.005 s | −2.020% | 4/4 |
| Host | 16.2920 s | 15.9685 s | −2.021% | 4/4 |
| 全局 eval/step | 52.2345 us | 50.8830 us | −2.506% | 4/4 |
| 全局 update/step | 23.9665 us | 23.6805 us | −1.193% | 3/4 |

百分比为四对 `median(100*(B_i/A_i-1))`，不是两列中位数直接相除。
walltime 四对依次为 −2.085%、−1.955%、−1.655%、−2.324%；AB/BA
两种顺序均改善。不能将这组百分比与此前 leaf-mux、同 reader 分组的不同
基线数据相加，或据此推算相对 Verilator 的差距。

下表是各线程**全 step 平均 eval**，不是“成为瓶颈时”的条件均值：

| 分区 | A 中位数/us | B 中位数/us | 配对变化中位数 | B 更快 |
| --- | ---: | ---: | ---: | ---: |
| p3 | 44.9980 | 43.7915 | −2.768% | 4/4 |
| p6 | 37.0125 | 36.1990 | −2.379% | 4/4 |
| p10 | 30.8800 | 30.6175 | −0.800% | 3/4 |
| p18 | 31.4165 | 31.1790 | −0.796% | 4/4 |
| p25 | 19.6235 | 18.5180 | −5.373% | 4/4 |
| p26 | 27.4080 | 26.3705 | −3.623% | 4/4 |
| p27 | 19.7365 | 19.0150 | −3.669% | 4/4 |
| p29 | 16.4555 | 16.2190 | −1.278% | 4/4 |

32 个分区中，31 个 eval 配对变化中位数降低，p12 小幅增加 0.142%；
并非所有阶段都受益，例如 p7/p11 的 update 分别增加 0.768%/3.195%，
且均为 4/4 更慢。全部分区的 eval/update 及每对结果保留在汇总 JSON 中。
这些是整机环境内的线程计时，不把 update 的变化归因于本轮没有修改的
通信算法，也不把对象指令不变等同于硬件执行周期不变。

结论：这个单一、通用、低复杂度的对齐候选在当前一轮测试中有约 2% 的
walltime 收益，值得保留；不是对 64 字节为最佳布局的证明，也尚未验证
其他 workload/编译器。本轮按约定在此收住布局探索，不继续扫参数、按分区
特调或研究更复杂的代码重排，**不改变正式默认或纯 bool alias 基线**。
后续回到真实残余 compute/commit 工作量、分支与活跃路径，对照 Verilator
寻找通用优化；这个对齐结果作为独立候选保留，不掩盖算法本身的得失。

证据与复现入口：

- [完整结果及 32 分区统计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/model_align64/results.json)、
  [原始运行与身份记录](../../build/repcut_grhsim_20260925/active_dispatch_20261003/model_align64/ordinary/manifest.json)。
- [对象/链接审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/model_align64/build.json)、
  [A 重链接一致性审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/model_align64/baseline_relink_audit.json)。
- [试验脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/model_align64.py)：
  在 node030 依次执行 `build`、`run`、`report`；复现时三步均传入相同且新建的
  `--output` 路径，不覆盖已有结果。原始数据在 `model_align64/ordinary/`。

#### 增量更新：按追加授权补测 32/128 字节相邻档位（2026-10-03）

随后用户允许在必要时补试其他对齐。考虑到 64 字节的初测收益方向一致，
仅增加两个相邻档位 32 和 128 字节，与同一个冻结的 64 字节 ELF 做同窗
比较；不扩展到函数排序、分区名单或更大的参数搜索。两版仍对全部生成
模型可执行段使用 `max(原对齐, 指定值)`，7418 个模型对象的 section
payload、符号和重定位内容均不变，36 个框架对象不变，全部 6859 个
compute batch 入口分别达到指定对齐。三个档位相对原始自然 ELF 的文件
增量为 61440/188416/438272 bytes，即 0.060%/0.184%/0.428%。

本轮参照是 **64 字节候选，不是原始自然布局**。沿用上一小节的机器、
绑核、NUMA、编译器和运行配置，三版各做 6 次 C100000。六轮顺序预先固定为
`32/64/128`、`64/128/32`、`128/32/64`、`128/64/32`、`64/32/128`、
`32/128/64`；每版在前、中、后各出现两次，每两版的先后关系各三次。
每轮三次构成一个匹配组，统计该轮相对 64 的百分比，再取六轮中位数。
没有与前一窗口的数据拼接，也没有挑选最快的一次作为代表。

18 次正式运行全部通过 Difftest，3 次 C100 初始化 smoke 通过；正式终态
签名、Host CPU105、worker/part 映射、all-spin 和测前测后的 ELF/archive/
image/NEMU 身份全部核对通过。连同上一小节，本轮布局探索累计完成 26 次
正式 C100000 和 5 次 smoke；所有运行均保留，无额外 PMU 插桩或负载 gate。

| 对齐 | walltime 中位数/s | Host 中位数/s | 全局 eval 中位数/us | 全局 update 中位数/us | walltime 相对 64 的配对变化 | 快于 64 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 32 bytes | 16.030 | 16.0000 | 51.0175 | 23.7685 | −0.156% | 4/6 |
| 64 bytes | 16.060 | 16.0265 | 50.9870 | 23.7715 | 参照 | — |
| 128 bytes | 16.075 | 16.0440 | 51.1720 | 23.7460 | +0.125% | 3/6 |

32 相对 64 的 walltime 单轮范围为 −0.621%..+0.436%，配对均值 −0.103%；
128 相对 64 的范围为 −0.560%..+0.438%，配对均值 +0.001%。本轮 64 的
16.060 s 与上一窗口的 16.005 s 不应直接比较，也不能把相对 64 的百分比
与上一窗口相对自然布局的 −2.020% 相加。32 的小幅中位趋势不足以证明它
稳定优于 64；128 同样未显示额外 walltime 收益。

局部结果继续体现取舍。以下仍为全 step 平均 eval 的配对变化，而非瓶颈
条件均值；百分比均相对本轮 64：

| 分区 | 32 的变化 | 32 更快次数 | 128 的变化 | 128 更快次数 |
| --- | ---: | ---: | ---: | ---: |
| p3 | +0.181% | 2/6 | +0.542% | 2/6 |
| p6 | +0.426% | 0/6 | +0.524% | 0/6 |
| p10 | −0.636% | 5/6 | −1.195% | 4/6 |
| p18 | −0.681% | 4/6 | +1.628% | 1/6 |
| p25 | +1.391% | 0/6 | +2.917% | 0/6 |
| p26 | +1.676% | 0/6 | +1.982% | 0/6 |
| p27 | +0.693% | 1/6 | +1.240% | 0/6 |
| p29 | −1.648% | 6/6 | −0.697% | 5/6 |

32/128 各有 10 个分区的 eval 配对中位趋势改善、22 个增加；不能据此
按“获益分区数量”选方案，最终仍看整机 walltime。32 对 p29/p18 较好，
64 对 p25/p26/p27 较好，128 对 p10 较好，说明不存在简单的“越大越快”。
本轮没有重新做 PMU，不能进一步将差异精确归于解码、op-cache 或预测器。

结论：**暂保留 64 字节作为独立候选，但不声称它是最优值；结束这轮布局
搜索，正式默认保持不变。** 依据是 64 对原始自然布局已有同窗约 2% 的
正向结果，而这两个相邻档位未提供足够稳定的额外 walltime 收益，不是为了
保住个别分区数字。后续优先回到实际计算/提交和活跃路径热点；不新增 256
字节等档位，也不按分区混用对齐规则。此次未修改生产源码、RTL 或 Verilator。

- [三档完整结果及全部分区统计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/model_alignment_compare/results.json)、
  [六轮原始运行/身份记录](../../build/repcut_grhsim_20260925/active_dispatch_20261003/model_alignment_compare/manifest.json)。
- [32 字节构建审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/model_align32/build.json)、
  [128 字节构建审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/model_align128/build.json)；
  64 字节直接复用上一小节，未重新构建或更换 ELF。
- 构建复用 `model_align64.py build --alignment 32/128`（两值分别执行，支持
  `--output` 新目录）；交错运行与汇总入口为
  [model_alignment_compare.py](../../build/repcut_grhsim_20260925/active_dispatch_20261003/model_alignment_compare.py)
  的 `run`/`report`。测量输出使用新目录，已有数据不覆盖。

### 7.43 相邻标量提交的精确激活掩码原型与残余归因（2026-10-03）

布局小范围比较结束后，回到实际提交与活跃路径成本。**本轮 A 是 §7.42 的
同 reader 分组自然布局版，B 只增加下述精确掩码分组原型**；两版均未加入
64 字节对齐。64 字节继续独立保留，不将其收益与本轮百分比相加，也未改变
正式默认或纯 bool alias 参照线。

#### 先复核当前线与 Verilator

复用固定 IP 探针，模型对象不重编译，只替换 GrhSIM 的 `common/eval_0`
两个包装对象。对照冻结的 Verilator/O3，在相同 239 个历史 p18 瓶颈 step
上，cycles 和 branch-misses 各做四对 C100000 AB/BA。每种事件每版共
956 个区间，running/enabled 全为 1，没有丢样或 throttle。

当前同 reader 自然候选相对 Verilator 的区间 cycles 为
175900175/167971538（+4.720%），错分支为 1118648/681484（+64.149%）。
这是固定标签下的单沿条件集合，不是全 step、两沿合计或整机 walltime。
GrhSIM 周期 IP 样本中，compute/commit/model eval 分别占 78.490%/
16.809%/1.852%；commit 占错分支 IP 样本 41.728%。大提交函数 c256
仍占周期样本 14.530%、错分支样本 34.007%，没有因同 reader 分组消失。

生成代码对照仍显示机制差异：Verilator 对某些等价寄存器直接赋值，而
GrhSIM 要逐值比较新旧状态并精确激活后续消费者。例子仍可核对
`clang23_threeway/verilator_o3/package/build/verilated/part_18/`
`VWolviRepCutUnit_part_18___024root__14.cpp:550` 和当前
`same_reader_leaf_mux/candidate/grhsim_Gpart_18_model_sched_256.cpp:7525`。
名称只用于等价代码定位，不是候选筛选条件；不能删除 GrhSIM 的必要激活，
也不能把全部 GrhSIM/Verilator 差距都归因于 commit。

#### 原型规则与验证范围

现有 same-reader 分组要求完整消费者集合相同。本原型只补充其余连续写入：
同一 guard/作用域内，3..8 个普通标量状态写入，next 是已物化 value slot
或其纯引用，目标状态互异，生成 commit 源中仅有一处显式状态写入；全掩码、
非宽值，且每个成员的激活位都落在同一个对齐 8-byte 区间。不同 guard、
其他语句、不可证明的表达式或活动更新均断组。已有 same-reader/lockstep
组不拆开，也不匹配分区、RTL 模块、寄存器名称或 profile 命中名单。

其核心是保留每个成员的精确变化条件，再合成最终掩码：

```cpp
bool ca = (a != na), cb = (b != nb), cc = (c != nc);
if (ca | cb | cc) {
    a = na; b = nb; c = nc;
    active_word |= (mask_a & -unsigned(ca))
                 | (mask_b & -unsigned(cb))
                 | (mask_c & -unsigned(cc));
}
```

真实代码使用明确的 8/16/32/64 bit 无符号类型，不依赖上面示意的默认整型
宽度；OR helper 的读写范围必须处于活动数组真实边界内，空洞位的掩码为零。
有人变化时，未变化成员会写回相同值，但其消费者不会被额外激活；全组不变
则不写状态或活动字。所有 next 均为纯存储读取，状态互异且中间没有其他
操作，避免移动快照或写入顺序改变语义。

这是**生成 C++ 上的结构化探索原型，尚未做成生产 IR/emitter 选项**。
当前只覆盖已冻结的普通计时配置，带额外 perf/触发计数语句的块会拒绝匹配，
不能宣称支持所有生成选项。若后续落地，写者、guard、掩码和纯读取资格应
由 IR 证明，并完整保留各项计数语义，不依赖扫描生成源码的显式赋值次数。

全量扫描由冻结 ELF 的 135 个 commit 方法枚举对应源文件，覆盖全部 32
分区；30 个分区命中，p15/p29 不匹配。共 3006 组、15035 次状态写入，
67 个 commit 对象变化，7387 个对象原样复用；compute、调度、框架对象及
已有按需计算不变。这些组的静态激活写语句从 15080 条降至 3006 条，
但不能将此比例当作动态指令或 walltime 降幅。p3/p10/p18 分别只覆盖
291/2030/441 次写入，后者覆盖面仍较小。

逐组逆变换要求恢复原始源码，保证组外计算和 guard 不变；对全部组枚举
252456 个 changed 组合核对精确目标位。另有 120 个标量/掩码配置，覆盖
bool、8/16/32/64 bit、组大小 3..8、空洞、重叠、bit63、已有活动位、重复
不变 eval，分别在 Clang23/O3 和 GCC/UBSan 下通过。解析器的 8 种负例
检查拒绝副作用、直接状态读取、部分掩码、多写者及额外计数/未知激活语句。
模型增量编译 9.608 s；ELF 比 A 小 45056 bytes，总模型函数字节少 51535。
源码变短并不预先等于运行更快。

#### 普通版收益与固定瓶颈步计数

沿用 node030 CPU96--127、NUMA1、N=K=32、Host CPU105、all-spin、Clang23/O3、
ASLR off、C100000。先四对普通 AB/BA，中间两对独立 core-PMU，再四对普通
复测；全部成功样本保留，不做空闲率 gate 或慢样本过滤，编译与测量不重叠。

| 指标 | A 中位数 | B 中位数 | 八对配对变化中位数 | B 更快 |
| --- | ---: | ---: | ---: | ---: |
| walltime | 16.225 s | 16.090 s | −0.892% | 8/8 |
| Host | 16.1915 s | 16.0555 s | −0.867% | 8/8 |
| 全局 eval/step | 52.1565 us | 51.1590 us | −1.687% | 8/8 |
| 全局 update/step | 23.6525 us | 23.7990 us | +0.779% | 3/8 |

两窗口 walltime 配对中位数分别为 −0.648%/−1.260%；合并仍按八个
`100*(B_i/A_i-1)` 取中位数，不是两列中位数相除。各线程全 step eval 的
配对变化为 p3 −1.807%、p10 −0.458%、p18 −0.557%、p25 −1.668%、
p26 −1.473%、p27 −1.689%、p29 −1.886%。p29 没有命中任何新组，
已经提示整机变化不能全解释成新增规则直接减少计算。

固定历史瓶颈步的 PMU 与普通平均值不是同一个统计量，不能混用：

| 分区 | cycles 变化 | instructions 变化 | branches 变化 | branch misses 变化 |
| --- | ---: | ---: | ---: | ---: |
| p3 | −2.450% | +0.015% | −0.011% | −21.400% |
| p10 | −0.081% | +0.054% | −0.105% | +2.039% |
| p18 | −1.133% | +0.114% | −0.193% | −1.967% |
| p25 | +0.790% | 约 0 | 约 0 | +0.925% |
| p26 | +0.419% | 约 0 | 约 0 | −3.051% |
| p27 | −1.328% | 约 0 | 约 0 | −0.433% |
| p29 | +1.428% | 约 0 | 约 0 | +5.462% |

两沿拆分也保留在 JSON：p18 上升沿指令 +0.103%、分支 −0.131%，下降沿
两者几乎不变；其 cycles 两沿都降低约 1.4%。p25/p26/p27 的历史瓶颈均在
下降沿，不能将当步现象解释成上升沿的提交工作大幅减少。p3 错分支下降
远大于动态分支减少，故补做下面的阶段拆分，不仅凭 walltime 宣称机制成立。

#### 分段计时：直接提交收益较小，主要残余仍在 compute

复用已有阶段探针，仅重建两个 wrapper 和 32 个外层 model eval 对象；
compute/commit batch 对象保持各自冻结版本，A/B 使用同一套探针对象。
独立两对 C100000，共每版 3150 个采样 step；所有运行在全部 1575 个步号、
32 个分区的固定点轮数向量逐项相同。此计数并非完整逐位活动序列的动态
证明，精确掩码仍由前面的结构/语义验证保障。阶段探针会改变外层代码及
执行环境，因此不使用其 walltime 代替普通版结论。

固定历史瓶颈步的阶段均值如下：

| 分区 | compute A→B/us | commit A→B/us | commit 变化 |
| --- | ---: | ---: | ---: |
| p3 | 36.0852→35.0025 | 2.9871→2.9296 | −1.925% |
| p10 | 39.7774→39.4859 | 7.0940→7.0263 | −0.954% |
| p18 | 40.6236→40.3130 | 7.9635→7.8370 | −1.589% |

p18 的 commit 两对分别 −1.224%/−1.947%，平均仅节省约 **0.127 us**；
p10 两对为 +0.134%/−2.037%，趋势较弱。p3 则主要省在未修改的 compute：
约 1.083 us，对比 commit 的 0.057 us。p25/p26/p27/p29 在这套探针中的
固定瓶颈步 compute 反而增加约 3.4%--5.0%，且 commit 只有数十 ns；
不能隐藏这与普通全 step 平均不一致的现象，也不能把探针数值直接外推为
原二进制每部分的时间分摊。

结论：原型在两个普通窗口都得到小幅 walltime 收益，但**不能把约 0.89%
全部归于精确掩码合并**。确有少量提交分支减少和 p18 commit 的小幅正向
信号，动态指令却未减少；未修改 compute 的附带变化占有重要份额，执行
布局/缓存预测历史/线程相位等尚未精确分离。本轮按约定不再做布局参数搜索，
也不为这点收益继续扩大提交分组或立即改生产默认。

保留这个通用原型和成功结果，下一步把优先级放回 **p18 约 40 us 的活跃
compute**，而不是继续挤当前只省约 0.13 us 的提交组。新 IP 样本中 b18、
b195、b210 是可优先调查的实际 batch，但只作为归因位置，最终规则仍应按
运算/依赖模式筛选，不按 batch 名单优化。正式默认、RTL 和 Verilator 均未修改。

本轮累计 40 次正式 C100000 Difftest、12 次 C100 初始化 smoke 全部通过，
正式签名仍为 PC `0x80000c0c`、instructions 240349、cycles 99996、guest
cycles 100001、steps 200102。普通、PMU、IP、阶段四类输入及 ELF 身份均
最终复核，PMU 不复用计数器，IP 无丢样，当前无遗留测试进程。未修改生产
代码，所以本轮不重复全套 emitter CTest，不将原型专项等同于正式 IR 回归。

- [普通八对及全部分区/两沿 PMU](../../build/repcut_grhsim_20260925/active_dispatch_20261003/commit_mask_groups/results.json)、
  [阶段拆分](../../build/repcut_grhsim_20260925/active_dispatch_20261003/commit_mask_groups/phase/results.json)、
  [最终核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/commit_mask_groups/verification.json)。
- [结构及精确掩码审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/commit_mask_groups/audit.json)、
  [语义测试](../../build/repcut_grhsim_20260925/active_dispatch_20261003/commit_mask_groups/semantics/results.json)、
  [冻结增量构建](../../build/repcut_grhsim_20260925/active_dispatch_20261003/commit_mask_groups/build.json)。
- [当前线/Verilator cycles IP](../../build/repcut_grhsim_20260925/active_dispatch_20261003/commit_mask_residual/cycles/report.json)、
  [branch-misses IP](../../build/repcut_grhsim_20260925/active_dispatch_20261003/commit_mask_residual/branch-misses/report.json)。
- 复现脚本均在 `active_dispatch_20261003/`：`commit_mask_residual.py`、
  `commit_mask_groups.py`、`test_commit_mask_groups.py`、`run_commit_mask_groups.py`、
  `commit_mask_phase.py`、`verify_commit_mask_groups.py`。原始普通窗口位于
  `commit_mask_groups/ordinary_1` 与 `ordinary_2`；PMU/阶段原始数据分别在
  `pmu/runs` 与 `phase/runs`。不覆盖已测量的模型或运行目录。

#### 增量更新：两边共同开启 64 字节对齐的组合验证（2026-10-03）

按用户要求补测组合。前文沿用自然布局有利于与旧提交实验衔接，但隔离
精确掩码这一变量并不要求关闭 64 字节对齐；**两边同时开启即可**。
本次 A 直接复用 §7.42 已测过的同 reader + align64 ELF，B 将相同的
统一对齐规则应用到本节精确掩码原型，不混用自然布局 A，也不将历史
−2.020% 与 −0.892% 相加作为组合收益。

构建复用各自冻结的 Clang23/O3 模型对象，仅提升所有模型非空可执行段的
对齐要求至至少 64 bytes，原有更大对齐保持不变。B 的 7418 个模型对象
逐段审计指令、常量、符号及重定位内容不变，全部 6859 个主要 compute
batch 入口均满足 64 字节对齐。共同对齐后的 A/B 仍然只有原来的 67 个
commit 对象不同，7387 个对象完全相同，链接复用相同 harness 对象。
B 的 ELF 为 102490032 bytes，比共同对齐的 A 少 45056 bytes。
对齐转换、两次链接及该构建步骤的审计合计 54.957 s；未重编译 C++，
此数不是完整编译 walltime。

64 字节规则只控制入口对齐，不保证 A/B 的全部绝对地址、缓存映射或
预测历史相同。因此本次普通版测量回答的是“在已有 align64 上是否仍有
增量 walltime 收益”，不是彻底排除布局效应的机制证明。保持 node030
CPU96--127、NUMA1、N=K=32、Host105、all-spin、ASLR off、C100000，
预定八对交替 AB/BA，全部功能成功样本保留，不做空闲门槛或慢样本过滤。

- [共同对齐构建与差异审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/commit_mask_groups/align64/comparison_build.json)、
  [B 的逐段对齐审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/commit_mask_groups/align64/build.json)。
- [复现入口](../../build/repcut_grhsim_20260925/active_dispatch_20261003/commit_mask_align64.py)：
  `build` / `run` / `report`；可用 `--output` 指定新的目录，不覆盖旧实验。
  当前运行数据目录为 `commit_mask_groups/align64/ordinary`。

八对现已完成，共 16 次正式 C100000 Difftest 与两次 C100 初始化 smoke
全部通过；功能签名、Host105、线程映射、all-spin 和测量前后 ELF/image/NEMU
身份均复核通过。构建与测量不重叠，当前无本轮遗留仿真任务。

| 指标 | 配对变化中位数 B/A−1 | B 更快 |
| --- | ---: | ---: |
| walltime | +0.241% | 4/8 |
| Host | +0.228% | 4/8 |
| 全局 eval/step | +0.490% | 4/8 |
| 全局 update/step | −0.484% | 5/8 |

walltime 八次运行的算术平均值为 A 18.52000 s、B 18.53125 s；配对百分比的
平均值为 +0.095%。这里表中仍使用八个 `100*(B_i/A_i-1)` 的中位数，
不是两列运行时间中位数相除。尤其本轮单独对 A、B 取中位数会得到
18.55/18.45 s，看似 B 更快；但排序后丢失了相邻配对关系，不能将这个
比值当成表中的 +0.241%。完整逐对数据如下，未剔除任何成功样本：

| 对次 | 顺序 | A wall/s | B wall/s | B/A−1 |
| --- | --- | ---: | ---: | ---: |
| 1 | AB | 18.66 | 18.76 | +0.536% |
| 2 | BA | 18.90 | 18.28 | −3.280% |
| 3 | AB | 18.83 | 18.04 | −4.195% |
| 4 | BA | 18.21 | 18.92 | +3.899% |
| 5 | AB | 18.44 | 18.43 | −0.054% |
| 6 | BA | 18.72 | 18.47 | −1.335% |
| 7 | AB | 18.42 | 19.14 | +3.909% |
| 8 | BA | 17.98 | 18.21 | +1.279% |

前四对/后四对分别为 −1.372%/+0.612%；按执行顺序拆分，AB/BA 分别为
+0.241%/−0.028%，各 2/4 更快。波动明显大于整体差异，不能将 +0.241%
解释成已经证实的新规则固定退化，也没有依据宣称组合有稳定增量收益。
本轮绝对时间与前文历史窗口不同，只比较本轮冻结 A/B，不跨窗口计算加速比。

各线程**全 step 平均 eval**仍有明确取舍，不能用它替代条件瓶颈步耗时：

| 分区 | 配对 eval 变化中位数 | B 更快 |
| --- | ---: | ---: |
| p3 | −1.889% | 8/8 |
| p6 | +0.798% | 0/8 |
| p10 | −1.080% | 7/8 |
| p18 | −1.165% | 6/8 |
| p25 | +1.507% | 3/8 |
| p26 | +0.573% | 4/8 |
| p27 | +2.874% | 2/8 |
| p29 | +0.173% | 4/8 |

p3 在全部运行中仍是“平均 eval 最大”的分区，八次均改善，但全局阶段
不只由这个平均值决定：每一步的瓶颈可换人，还涉及到达/调度/同步等时间。
特别是 p26 的配对 eval 变化范围为 −10.192%..+21.268%，与全局 eval
配对变化的 Pearson r≈0.982（仅八对）；这只是共同波动线索，不证明 p26
单独导致全局变化，更不能据此认定外部负载或某个特定硬件事件。当前普通
汇总不足以完成该归因，本轮未额外改探针、扩大布局搜索或过滤这些波动。
全部 32 分区的 eval/update 数据保留在下面的汇总中。

**本次结论：组合在功能上通过，但未验证出对 align64 的稳定额外 walltime
收益。** 自然布局下的 −0.892% 不能直接沿用到组合；它也不说明 64 字节
对齐失效，因为本次 A/B 两边都已经开启，未重测其相对自然布局的单独收益。
继续保留统一 64 字节候选，精确掩码原型暂不因前一轮自然布局结果而纳入
默认；本轮不修改生产生成器、正式默认、RTL 或 Verilator 路径。

- [八对汇总、顺序拆分及全部分区](../../build/repcut_grhsim_20260925/active_dispatch_20261003/commit_mask_groups/align64/results.json)。
- [运行清单与身份/功能核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/commit_mask_groups/align64/ordinary/manifest.json)、
  [逐次时间](../../build/repcut_grhsim_20260925/active_dispatch_20261003/commit_mask_groups/align64/ordinary/runs.csv)、
  [逐分区时间](../../build/repcut_grhsim_20260925/active_dispatch_20261003/commit_mask_groups/align64/ordinary/parts.csv)。

#### 增量更新：关键路径归因与尺寸中和控制（2026-10-04）

组合版普通数据表明 p3 的无条件平均 eval 虽然下降，但 walltime 没有稳定下降，
因此对同一 align64 A/B 线做了逐 step 诊断。诊断 wrapper 每 127 个 step 采集
一次 32 个分区的开始/结束时间；以 `start + duration` 最大者定义实际完成关键
分区，而不是只取该分区的无条件平均 eval。四对 AB/BA、每对 1575 个样本，
共 6300 个配对样本。该探针改变 wrapper/外层 eval 布局并增加计时开销，以下
只用于相对归因，不替代普通版 walltime。

实际完成关键分区的次数如下：

| 分区 | A 次数 | B 次数 | 变化 |
| --- | ---: | ---: | ---: |
| p3 | 1992 | 2154 | +162 |
| p6 | 1146 | 1101 | −45 |
| p18 | 998 | 911 | −87 |
| p10 | 759 | 734 | −25 |
| p29 | 458 | 445 | −13 |
| p26 | 450 | 389 | −61 |
| p27 | 138 | 138 | 0 |
| p25 | 118 | 130 | +12 |

最常见的同分区迁移为 p3→p3 1737 次、p18→p18 834 次、p6→p6 805 次、
p10→p10 619 次；但也有 p6→p3 148 次、p3→p6 88 次、p10→p3 71 次、
p26→p6 67 次。也就是说“平均最大分区”并不等于每一步的关键路径分区。

在 A 原本为关键分区的同一批 step 上，固定比较同一个分区的工作量与整段
normal-eval 阶段：

| A 关键分区 | 该分区 eval | compute | commit | 整段 normal-eval |
| --- | ---: | ---: | ---: | ---: |
| p3 | +0.946% | +0.987% | −1.145% | +3.024% |
| p6 | −4.526% | −4.709% | −7.630% | −1.665% |
| p10 | −1.453% | −1.093% | −1.394% | +0.455% |
| p18 | −2.979% | −3.044% | −0.735% | −1.256% |
| p25 | −9.943% | −10.204% | +2.030% | +1.269% |
| p26 | −3.307% | −3.496% | +6.170% | +3.560% |
| p27 | −12.948% | −13.235% | +32.969% | −3.021% |
| p29 | −4.725% | −4.159% | +6.175% | −1.038% |

反向按 B 关键分区取 cohort 时，p6/p25/p27/p29 的同分区 eval 分别为
+5.198%/+12.453%/+11.228%/+5.429%，p26 为 +3.624%；p3 为 +2.369%。
这解释了 p3 的平均改善为何没有直接兑现为 walltime：B 的关键路径会在不同
step 换成其他分区，且这些分区的慢化会覆盖 p3 的节省。

随后使用 core PMU wrapper 在相同 align64 A/B 上复核 cycles、instructions、
branches、branch-misses。四对 AB/BA、同样每 127 step 采样；所有分区的
`time_running/time_enabled` 均为 1，没有 multiplex 或丢失。PMU 探针的全体
分区平均变化为 cycles +0.690%、instructions +0.087%、branches −0.035%、
branch-misses −0.367%。在 B 成为关键分区的 cohort 中，p27/p29 cycles 分别
为 +6.433%/+5.599%，instructions 约不变，p29 branch-misses +11.204%。
这更像取指/布局/预测状态改变，而不是生成了更多有效指令；PMU 同样受探针
布局影响，只作机制证据。

最直接的布局证据是：A/B 的 67 个不同 commit 对象合计使 B 的 ELF 比 A 小
48544 bytes。p29 没有任何直接修改的 model object，但其链接后的函数地址
整体约前移 48640 bytes；因此 p29 的退化不能归因于 p29 的 RTL 或 commit
规则本身，而是前面对象尺寸变化造成的后续代码布局变化。64 字节对齐只保证
入口对齐，不能固定这些入口之间的累计偏移。

#### 尺寸中和：分离算法收益与全局布局扰动

为验证上述归因，构造仅用于诊断的 size-neutral align64 控制：A/B 仍使用
各自的 align64 模型，仍保留 67 个真实 commit 改写；对每个改变过的 object，
两边都把 `.text` 尺寸补到该 object 在 A/B 中的较大值，尾部填充不可达 NOP，
不改变有效函数前缀。这样 6859 个主要 compute 入口在两版间 **0 个地址变化**。
A/B 的 padding 分别为 713/52243 bytes；该 padding 不是生产规则，只是消融
控制。尺寸中和后的两个 ELF 分别为 102539184/102543280 bytes，链接和功能
签名均独立核验。

node030 CPU96--127、NUMA1、N=K=32、Host105、all-spin、ASLR off、Clang23/O3、
C100000 下，交错完成 8 对普通 AB/BA（16 次正式 Difftest、2 次 C100 smoke）：

| 指标 | A 中位数 | B 中位数 | 配对变化中位数 | B 更快 |
| --- | ---: | ---: | ---: | ---: |
| walltime | 16.100 s | 15.945 s | **−1.212%** | 8/8 |
| Host | 16.0685 s | 15.9125 s | **−1.199%** | 8/8 |
| 全局 eval/step | 51.2865 us | 50.3530 us | **−1.623%** | 8/8 |
| 全局 update/step | 23.8205 us | 23.7990 us | −0.280% | 6/8 |

代表性分区的 eval 变化为 p3 −3.904%、p6 −1.347%、p10 −2.806%、p18
−2.513%、p25 −3.128%、p26 −2.089%、p27 −0.488%（6/8 更快）；p29
+0.508%（0/8 更快）。p29 的有效函数在尺寸中和版中地址和代码 hash
均保持不变，剩余约半个百分点应视为线程相位/其他全局布局差异，而不是
精确掩码直接改坏 p29。全部逐对结果与 32 分区数据保留在结果 JSON。

这组控制给出比自然/普通 align64 组合更清晰的结论：**精确掩码分组本身
存在约 1.2% 的 walltime 潜力，但原始组合被跨 object 的代码尺寸变化和
关键路径迁移掩盖。** 不能把尺寸中和 padding 直接加入正式实现；它会额外
膨胀代码并不一定适合所有后端。下一步应保持 64 字节对齐，研究通用的
“降低有效提交成本、同时限制无关 object 布局扰动”的生成策略，并以真实
关键路径而非平均分区权重验收。仍不按 partition/信号名单做特调，正式默认、
RTL 和 Verilator 路径保持不变。

- [逐 step 关键路径结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/conditional_bottleneck_align64/results.json)、
  [关键路径运行清单](../../build/repcut_grhsim_20260925/active_dispatch_20261003/conditional_bottleneck_align64/runs/manifest.json)。
- [core PMU 关键 cohort](../../build/repcut_grhsim_20260925/active_dispatch_20261003/conditional_bottleneck_align64/pmu_core/results.json)、
  [PMU 运行清单](../../build/repcut_grhsim_20260925/active_dispatch_20261003/conditional_bottleneck_align64/pmu_core/runs/manifest.json)。
- [尺寸中和构建/入口地址审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/commit_mask_groups/align64_size_neutral/build.json)、
  [尺寸中和普通版汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/commit_mask_groups/align64_size_neutral/results.json)。
- 复现脚本为 `conditional_bottleneck_align64.py`、`conditional_bottleneck_pmu_align64.py`
  和 `mask_size_neutral_align64.py`；所有脚本均只生成诊断/实验产物，不修改生产
  emitter、默认选项、RTL 或 Verilator 路径。

#### 勘误与增量验证计划：固定样本、同窗四组对照（2026-10-04）

复核后，上述“这证明精确掩码本身有约 1.2% 潜力、被布局变化掩盖”的因果
表述过强，应以本说明为准。此前普通 align64 与尺寸中和实验相隔约五小时，
只能证明各自时间窗口和布局下的相对表现，不能将两次实验的差异全算成布局
效应或纯算法收益。尺寸中和虽固定了 compute 入口，但未固定所有数据布局：
两版 `.data.rel.ro/.data/.bss` 仍相差 4096 bytes。p29 的剩余退化也尚不能
排他地归因于线程相位。

另有两个统计/数值勘误：

- 先按本轮 A 或 B 成为瓶颈筛选，再比较 A/B，会分别偏向该版本的慢样本。
  双向 cohort 可以描述瓶颈分布，不能独立证明优化引起了关键路径迁移损失。
  将原 core PMU 的四对数据改用此前冻结的 `labels.json` 相同步号统计，排除
  首个初始化样本 step127，以每次完整 run 的均值计算配对变化中位数：p29
  cycles **+3.179%**、branch misses **+11.153%**、指令数基本不变；p27
  cycles +3.925%、misses −0.450%；p18 cycles +1.343%、misses −1.854%。
  这支持继续检查执行效率，不支持将全部分区的退化统一解释为分支预测。
- 前文 48544 bytes 是 archive 的大小差，不是最终 ELF。普通 align64 A/B
  ELF 分别为 102535088/102490032 bytes，差 **45056 bytes**；p29 有 208/209
  个函数地址前移 48640 bytes 的核查结果不变。

下一组实验保持 node030 CPU96--127、NUMA1、N=K=32、Host105、all-spin、
ASLR off、Clang23/O3、共同 64 字节对齐和 C100000；四组分别为普通 A/B、
尺寸中和 A/B，复用已验证 ELF。按四组位置与先后顺序平衡的八个 block 交错，
每个 block 四次正式仿真，共 32 次，外加四次 C100 初始化检查。不按负载、
胜负或离群程度删成功样本。

独立诊断只替换共享的两个 wrapper object，不改模型。各 PMU 组固定 cycles
和 instructions，分别增加 branches/branch-misses、前端未供给/后端阻塞槽、
L1 指令缓存/Op Cache misses、L1 ITLB miss 且 L2 hit/两级 ITLB miss。每组四个
硬件事件，避免 node030 已开启 NMI watchdog 时占满计数器；逐样本验证 running
等于 enabled。固定历史标签与全部上升/下降沿均保留，统计重复单位是完整 run，
不是将重复测量的同一步号视为独立实验。PMU wrapper 改变布局且有开销，仍不
以诊断版 walltime 替代普通版结果。频率只记开跑前后快照，不当作单步精确频率。

实验脚本：`build/repcut_grhsim_20260925/active_dispatch_20261003/layout_rootcause.py`；
产物目录：`layout_rootcause_20261004/`。本轮不尝试新的对齐档位、不引入 padding
生产策略、不改正式默认或 Verilator 路径。

#### 同窗普通版四组结果（2026-10-04）

八个完整 block、32 次 C100000 与四次 C100 已全部通过功能、运行配置和输入
身份核验。四组均为既有未加新探针的二进制：plain A/B 为原 align64，neutral
A/B 为此前逐 object 尺寸中和版本。每组在四个运行位置各出现两次，block
内部的每一种有向相邻组合也各出现两次，编译与测量未重叠。

| 组别 | walltime 中位数/s | Host 中位数/s | 全局 eval/us | 全局 update/us |
| --- | ---: | ---: | ---: | ---: |
| plain A | 16.280 | 16.2425 | 51.7000 | 23.9050 |
| plain B | 16.195 | 16.1640 | 51.5870 | 23.8855 |
| neutral A | 16.215 | 16.1805 | 51.8735 | 23.7045 |
| neutral B | 16.020 | 15.9845 | 50.8640 | 23.7870 |

在每个 block 内计算 B/A 比例，再取八个配对比例的中位数：

| 对照 | walltime 变化 | Host 变化 | eval 变化 | update 变化 | walltime 更快 |
| --- | ---: | ---: | ---: | ---: | ---: |
| plain B/A | −0.461% | −0.447% | −0.215% | −0.082% | 8/8 |
| neutral B/A | −1.142% | −1.144% | −1.936% | +0.479% | 8/8 |
| neutral A/plain A | −0.399% | −0.400% | +0.300% | −0.868% | 5 胜、1 平、2 负 |
| neutral B/plain B | −1.048% | −1.056% | −1.314% | −0.178% | 8/8 |

每个 block 分别计算 `100*(neutral_B/neutral_A-1) -
100*(plain_B/plain_A-1)`，walltime 差异的中位数为 **−0.616 个百分点**，
均值 −0.695 个百分点，八轮均为负。注意 −0.616 不等于两个中位数直接相减。
这次同窗对照支持“规则收益随布局改变”的交互，但仍不是纯算法贡献分解。
原布局这次有小幅稳定收益，不能继续引用旧窗口的 +0.241% 当作固定表现。

普通版全 step 的分区 eval 变化（仍非条件瓶颈步）：

| 分区 | plain B/A | neutral B/A |
| --- | ---: | ---: |
| p3 | −0.078% | −4.395% |
| p6 | +0.409% | −1.653% |
| p10 | −0.753% | −2.872% |
| p18 | −0.998% | −2.528% |
| p25 | +0.220% | −3.474% |
| p26 | −1.021% | −2.319% |
| p27 | −1.106% | −1.219% |
| p29 | −4.254% | +0.199% |

p29 原布局的全 step 均值这次并未退化，不能预设旧 PMU 的 p29 慢化必然
复现。新共享 wrapper 探针的首组 core PMU 又出现 neutral walltime 与普通版
方向不一致的情况，因此除了固定步号 PMU，还追加不改上述四个 ELF 的低频
`perf record` 指令地址采样作交叉检查。后者是全运行期采样、不是固定步号，
也受采样中断影响；其 walltime 不代替上表。所有正式性能结论仍以上表无探针
对照为准。

- [同窗普通版结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/layout_rootcause_20261004/ordinary/results.json)
  与 [运行清单](../../build/repcut_grhsim_20260925/active_dispatch_20261003/layout_rootcause_20261004/ordinary/manifest.json)。
- [旧 PMU 固定步号重算与四组 ELF 地址审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/layout_rootcause_20261004/audit.json)。

#### 固定步号 PMU 与无改码采样交叉核验（2026-10-04）

四个事件模式（core/pipeline/cache/tlb）各完成四个位置平衡的四组 block，
合计 64 次正式 C100000 和 16 次 C100，均通过 Difftest、输入身份、运行
配置、样本步号与计数器 running/enabled 核验。每个 run 有 1575 个采样
step，排除首次计数器初始化的 step127 后保留 1574 个；统计按完整 run
配对，不将四次重复的同一步当作四个独立 workload。

这次发现的关键方法问题是 **探针改变了被测布局**：共享两个 wrapper 后，
四个版本的全部 6859 个主要 compute 入口都相对各自普通版后移 13568
bytes。它们仍然 64 字节对齐；neutral A/B 之间的 compute 入口和机器码
仍完全相同，但这不等于保持了普通版的完整地址和时序环境。neutral B/A
普通版 walltime 为 −1.142%，而四个探针事件模式的配对中位数分别为
+0.435%/+0.404%/+0.560%/+0.093%。这是探针改变布局和执行时序后观测
方向发生反转的证据，不是仅凭地址变化就排他证明地址导致了反转。

因此，固定步号 PMU 只解释这一探针版本：

- pipeline 组中，历史 p3 瓶颈步的前端未供给槽约占可用槽的 54%，p18
  约 67%--68%。这里是 `frontend_slots/(6*cycles)`，不是“54%/68% 的
  walltime 可以直接消掉”，也不是单独的指令缓存 miss 延迟。
- p18 的 plain B/A 在 core/pipeline/cache/tlb 四组的 cycles 中位变化
  分别为 −0.989%/−1.492%/−1.181%/−1.269%；对应 branch misses
  −1.646%、前端未供给槽 −2.473%、IC miss −3.374%、ITLB 两级 miss
  触发的页表遍历请求 −4.853%。各事件模式独立测量，不能拼成一次同时
  发生的计数器快照。
- p29 原布局的 ITLB 遍历请求 −9.782%，但不能据此解释旧探针里的
  branch misses +11.153%；新 probe 的 core 组错分支方向已变为
  −1.533%。旧版本、当前 probe 和普通版不能互换。

事件编码同时核对 node030 的 `perf list --details` 和 Linux perf 的
[Zen 4 cache 事件定义](https://raw.githubusercontent.com/torvalds/linux/master/tools/perf/pmu-events/arch/x86/amdzen4/cache.json)、
[memory 事件定义](https://raw.githubusercontent.com/torvalds/linux/master/tools/perf/pmu-events/arch/x86/amdzen4/memory.json)、
[pipeline 指标定义](https://raw.githubusercontent.com/torvalds/linux/master/tools/perf/pmu-events/arch/x86/amdzen4/pipeline.json)。
IC/Op Cache miss 是事件计数，不是已退休指令数、唯一 cache line 数或实际
内存字节流量，不能简单乘 64 当作读取量。

为避免重新链接这一干扰，随后对四个 **原普通版 ELF** 做低频用户态
`perf record`，不替换模型或 wrapper；四个完整 block 共 16 次 C100000、
四次 C100 全部通过。只采集所启动进程及线程，不作系统级/其他用户采样。
cycles/branch-misses/前端未供给槽/IC miss 的固定采样周期分别为
10000019/100003/60000011/1000003；按符号累计 sample period 估计事件总量，
不比较不同运行中某函数占全部样本的百分比。全部原始事件记录没有 LOST、
LOST_SAMPLES、THROTTLE/UNTHROTTLE。采样仍有中断/skid 和收集器开销，
它是全运行期而非历史瓶颈步诊断，不用其外层 perf walltime 代替普通版。

这组无改码采样中，neutral B/A 的 Host 四轮均更短（−1.627%、−1.248%、
−1.129%、−1.565%），保留了普通版主要方向。下表为 **compute 方法** 的
事件估计量配对中位变化：

| 分区 | cycles | 前端未供给槽 | IC miss |
| --- | ---: | ---: | ---: |
| p3 | **−3.881%** | **−6.507%** | **−11.743%** |
| p6 | −2.221% | −2.841% | −6.190% |
| p10 | −5.921% | −6.503% | −9.418% |
| p18 | −0.841% | −3.255% | −6.904% |
| p25 | −0.917% | −5.219% | −10.123% |
| p26 | −3.510% | −5.581% | −8.754% |
| p27 | +0.610% | −2.844% | −3.937% |
| p29 | +0.333% | −2.281% | +0.350% |

p3 的三项在四轮均为负；compute cycles 四轮为 −5.00%、−3.85%、−3.91%、
−3.79%，IC miss 为 −12.03%、−11.81%、−10.00%、−11.67%。而 p3 commit
cycles 为 −2.89%、+1.33%、−8.43%、+13.42%，未出现相同的稳定周期改善。
在此全运行期采样口径下，neutral A 的 p3 模型 eval 周期估计中 compute
占 91.92%、commit 5.36%、外层 eval 2.72%；不等同于历史单沿瓶颈 cohort。
p18/p25/p27 的周期估计有正有负，即使 miss 同向减少也不应宣称全部分区
都得到稳定周期收益。

这比只看包装层 PMU 更支持“原有 compute 的供指/指令缓存行为发生间接改善”
这一解释，而不支持把 walltime 改善全算作直接提交成本下降。但目前还没有
将具体缓存组冲突、预取、分支预测状态、物理页布局及线程阶段关系分别隔离。
尤其少量事件的 IP 样本较稀疏（如 p29 错分支只有每轮几十个），不将其大幅
百分比变化当作确定机制。未命中规则的 p15 compute IC miss 也约 −5.15%，
故不能将上述所有变化都解释为该分区自身 commit 代码缩小；另补一项仅平移
堆起点的边界控制，检查此前 4 KiB 数据区差异能否单独解释结果。

- [共享探针布局/对象身份审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/layout_rootcause_20261004/probe/build.json)。
- 固定步号结果：[core](../../build/repcut_grhsim_20260925/active_dispatch_20261003/layout_rootcause_20261004/core/results.json)、
  [pipeline](../../build/repcut_grhsim_20260925/active_dispatch_20261003/layout_rootcause_20261004/pipeline/results.json)、
  [cache](../../build/repcut_grhsim_20260925/active_dispatch_20261003/layout_rootcause_20261004/cache/results.json)、
  [tlb](../../build/repcut_grhsim_20260925/active_dispatch_20261003/layout_rootcause_20261004/tlb/results.json)。
- 无改码采样：[结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/layout_rootcause_20261004/ordinary_perf/results.json)
  与 [运行清单](../../build/repcut_grhsim_20260925/active_dispatch_20261003/layout_rootcause_20261004/ordinary_perf/manifest.json)。

#### 堆起点边界控制与本轮结论（2026-10-04）

最后只增加一个诊断控制，不搜索其他地址/对齐档位：复制 neutral A 的 ELF，
将最后一个可写 PT_LOAD 的 `p_memsz` 和 `.bss` 的 `sh_size` 各增加 4096。
文件中实际只有两个元数据字节不同；所有已有 section 的地址和 payload、
所有已有函数地址/机器码与 A 完全相同，不新增实际执行的指令，也不移动已有
全局变量。只扩展末尾尚未使用的零填充区域，以调整内核设置的初始 brk。
生产 ELF、原 archive 和源代码未修改，该副本不作为生产候选。

旧 A / 旧 A+heap4k / 新 B 三组按六种排列平衡交错，18 次 C100000 和三次
C100 均通过。每次正式运行读取自己启动的子进程映射，实际 heap 起点稳定为：
旧 A `0x55555b5eb000`，A+heap4k 和新 B 均为 `0x55555b5ec000`。因此控制
确实平移了堆起点，并非只改 ELF 描述却未影响运行地址。

| 同窗配对对照 | walltime | Host | 全局 eval | p3 全 step eval | walltime 更快 |
| --- | ---: | ---: | ---: | ---: | ---: |
| A+heap4k / A | −0.553% | −0.563% | −0.567% | −1.729% | 4/6 |
| B / A+heap4k | −0.834% | −0.827% | −1.273% | −3.045% | 6/6 |
| B / A | −1.352% | −1.380% | −2.018% | −4.580% | 6/6 |

A+heap4k 的六个 walltime 比例为 −0.490%、+0.062%、−1.046%、−0.615%、
−0.861%、+0.493%；保留两次变慢样本。该控制提示非算法的布局变化可以出现
同量级的收益趋势，但 **4/6 不能宣称稳定确认了固定的 −0.55% 堆贡献**。
它也没有固定全部全局数据区或物理页映射，不能将其称为完整的数据布局中和。
新 B 相对堆起点已经一致的旧版仍六轮更快，故“只是堆起点差 4 KiB”不足以
解释全部收益。各行的配对中位数也不能相加、相减来进行贡献分摊。

本轮结论与后续边界：

1. **保留 64 字节对齐。** 原布局的当前同窗 walltime 增益约 0.46%，尺寸
   中和约 1.14%，两组均 8/8 更快；后续三组窗口 B/A 约 1.35%，不能把不同
   窗口的百分比叠加。布局会改变这项规则的表现，但并未证明固定的“纯算法
   收益”是多少。
2. **主要收益表现在未改 compute 的供指/指令缓存行为上。** 无改码采样的
   p3 compute cycles、前端未供给槽和 IC miss 分别约 −3.88%、−6.51%、
   −11.74%，四轮同向；p3 commit 周期没有同样稳定的改善。更支持前端执行
   效率这一层解释，而不是“提交指令直接减少，所以总时间相应减少”。这仍
   不是已定位某个具体 I-cache set、BTB 冲突或某次预取的排他因果证明。
3. **测量方法是此前归因不稳的重要因素。** 按本轮瓶颈选样本存在选择偏差，
   插 wrapper 又使全部 compute 入口移动 13568 bytes 并改变时序，足以让
   观测的收益方向与原版不同；后续必须继续区分无探针 walltime、冻结步号
   probe、原二进制全程 IP 采样三种口径。
4. 本轮到此收住布局消融，不将 tail padding 或 heap4k 加入默认，不改
   Verilator。精确掩码仍是实验原型；下一步更值得降低活跃 compute 的重复
   代码/控制流密度和供指压力，再用原二进制采样与普通 walltime 验证，而不是
   扩大提交分组后直接按其静态语句减少量估算收益。

本轮共 **130 次正式 C100000 Difftest、27 次 C100 初始化检查**，均通过；
全部成功样本保留，未采用 CPU 空闲率淘汰、挑选快样本或按分区/信号名单调优。
所有仿真及诊断构建均在 node030 CPU96--127，代码生成器、生产默认、RTL 和
Verilator 路径没有变更。记录仅扩展本节，不另开细粒度文档。

- [heap 控制构建审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/layout_rootcause_20261004/heap_control/build.json)、
  [三组完整结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/layout_rootcause_20261004/heap_control/results.json)、
  [含逐次映射的运行清单](../../build/repcut_grhsim_20260925/active_dispatch_20261003/layout_rootcause_20261004/heap_control/manifest.json)。
- 追加脚本：`layout_rootcause_audit.py`、`layout_rootcause_perf.py`、
  `layout_rootcause_perf_report.py`、`layout_heap_control.py`，均位于同一实验目录。

### 7.44 活跃 compute 的重复位搬运压缩（2026-10-04）

接续 §7.43 的供指归因，保留 uniform64，不继续搜索 padding/对齐档位。
本轮固定基线为该节 **plain B**：精确掩码提交原型、same-reader、完整纯 bool
别名及 leaf-mux 等此前有效线，加统一 64-byte 对齐；不带尺寸中和或 heap4k。
ELF SHA-256 为 `75329bfe1c87a1a06c52bf51a135a53369682aac0d7f8177dd801d7ee386a3d3`。
两个独立原型均从该基线出发，不互相叠加，不修改 RTL 或 Verilator。

重新汇总原二进制四轮全程 IP 样本后，p3 compute 中最热的 b46 也只占其
compute cycles 估计的 3.56%，而 p6/b184 约 18.97%，p10/b15 约 5.00%，
p18/b195 约 1.72%。这是全运行期口径，并非“成为瓶颈的条件平均”。p3/p18
热点较分散，不能把一个大函数的局部改善直接换算为分区或 walltime 收益。

本轮测试同一类机制的两个方向，规则只看生成操作的结构：

1. **packed-bit scatter（拆位）**：连续至少八个纯 `kSliceStatic` bool
   写回，读取同一 64-bit 源字中连续的位，目的槽互不重复，精确 deferred
   reader 组相同，中间无计算/副作用。将逐项展开改为共享紧凑循环和常量
   目的索引表；仍逐项比较旧值、写回，以完全相同的 OR 结果更新原 reader
   组。不扩大激活集合，也不增加状态缓存。
2. **bool gather（拼位）**：宽拼接中连续至少八个纯 bool 子对象读取，
   填入同一目标字的连续位，源临时量没有其他使用。将重复 load/shift/OR
   收成共享循环和常量字节偏移表。仅接受 bool 数组槽或标准布局状态结构
   的真实 bool 字段，不包含 memory/DPI/表达式求值，不改变更新时序。

二者的示意分别是 `out[index[i]] = (word >> i) & 1` 和
`word |= uint64_t(bool_source[i]) << i`；它们压缩的是 C++ 展开方式，不是
删减仿真逻辑。索引表的读取、循环分支与函数调用可能抵消供指收益，因此
仍以普通 C100000 AB/BA 的最终 walltime 决定是否接受，不按静态 bytes 判定。

生成改写只存于实验目录。每个将替换的对象先用正确的冻结源文件和头文件
重编译基线，逐 section 核验已分配代码/常量及 relocation payload 与原
archive 相同，再编译候选并保持 64-byte 对齐；未修改对象逐字节保留。
性能测量继续使用 node030 CPU96--127、NUMA1、N=K=32、Host105、all-spin、
Clang23/O3、ASLR off；无空闲率淘汰，成功运行全保留。

拆位首轮已完成八对正式运行与两次 C100：功能签名全部一致，walltime 配对
中位数 **+0.031%（4/8 更快）**，没有整体收益。虽然分区 eval 合计约
−1.010%（8/8），p3 约 +0.549%，仍是主要限制；后续仅做原 ELF 采样用于
解释这一结果，不据此接受候选。详细结果及拼位独立对照将在本节继续补充。

- [拆位构建与源身份审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/compute_bit_scatter_20261004/build.json)、
  [普通 AB/BA](../../build/repcut_grhsim_20260925/active_dispatch_20261003/compute_bit_scatter_20261004/ordinary/manifest.json)。
- [拼位结构覆盖](../../build/repcut_grhsim_20260925/active_dispatch_20261003/compute_bool_gather_20261004/prepare.json)。

#### 循环对照与无循环修正

两种循环都通过功能检查，但没有达到 walltime 目标。拆位命中 25 分区、
87 个 compute 对象、329 组/6796 个写回站点；拼位命中 29 分区、98 个
对象、1691 组/49204 个读取站点。其余 archive 成员完全相同，commit、
框架和接口不变。最终 ELF `.text` 分别减少 220992 / 560448 bytes。

拆位另做四对原 ELF 低频 IP 采样。以**全部被修改的 compute 函数加共享
helper**为一个整体，避免把转移到 helper 的工作漏掉，结果为：cycles
+3.272%、retired instructions +13.054%、frontend slots +3.421%、IC miss
−19.890%。四对 cycles 分别 +3.715/+7.085/+2.828/+2.073%，指令也均增加，
IC miss 均减少。它说明“代码更紧凑”确实可以改善缓存计数，却增加实际
循环/索引/调用工作，不能只优化静态代码体积。这里是全运行期加权事件估计，
不等同于瓶颈 step 延迟；前端 slots 四轮有正有负，不声称其稳定增加。

据此增加第三个独立候选 **loop-free bool pack（无循环 bool 打包）**，
仍从同一个 plain B 基线出发，不叠加上面两个循环候选：

- 使用宽拼接的纯 bool 读取模式；以 `constexpr offsetof`/数组偏移检查
  八个真实 bool 子对象是否正向或反向连续，不依赖 RTL/分区/信号名字。
- 当目标 ABI 为 little-endian、`sizeof(bool)==1` 且 false/true 的字节
  表示为 0/1 时，`memcpy` 精确读取这八个字节，再用固定掩码和乘法压成
  八个 bit。正向乘数 `0x0102040810204080`，反向
  `0x8040201008040201`；运算均为 unsigned 64-bit，移位范围受目标字限制。
  例如八个字节 `[1,0,1,0,0,0,0,1]` 按前者得到低八位 `0x85`。
- 字段不相邻、ABI 不符合或剩余不足八项时，保留纯标量展开；不引入
  逐位循环、运行时索引表、新的共享调用或状态缓存。布局资格是生成 C++
  内的编译期常量表达式，**不是编译后反馈**。后续读取上一候选的常量表
  仅作覆盖审计，不作为生成规则输入，也没有根据 profile 选择站点。

在上述 49204 个读取站点中，27312 个进入 3414 个八字节块（正向 412、
反向 3002），21892 个走标量回退；这些是生成站点数，不是动态执行次数
或唯一寄存器数。覆盖不等于每个分区都受益：p3 进入块读取的为 1368 位，
p6 6472、p10 3104、p18 40，p29 未命中。

构建核验为 98 个 compute 对象变化、7356 个成员保持逐字节相同，6859 个
compute 入口仍全部 64-byte 对齐。所有被替换对象均先完成基线代码/常量/
relocation 重编译核对。最终 `.text` 94755186→94516978 bytes（−238208，
−0.251%），`.rodata` 只增加 48 bytes；最终 ELF 中没有新打包 helper 的
独立函数符号。被重编译对象的静态反汇编统计如下，**不是动态执行计数**：

| 指标 | 基线 | 循环拼位 | 无循环打包 |
| --- | ---: | ---: | ---: |
| 指令数 | 747724 | 614814 | 686694 |
| 条件跳转 | 2526 | 2867 | 2527 |
| call 指令 | 86 | 1777 | 86 |
| 栈寻址指令 | 25219 | 23896 | 24112 |

无循环版本的静态指令减少 8.16%，但没有循环版本的 1691 个额外 call。
这里不靠相同绝对地址证明纯算法贡献，链接位置仍可能变化；保留统一 64-byte
规则，不重新展开 padding/地址搜索。

三套候选各做八对普通 C100000；均使用每对 `100×(候选/基线−1)` 的中位数，
不由两组绝对中位数相除，也不跨窗口相减。p3/p6/p10/p18/p29 是各分区的
全 step 平均 eval，**不是按该分区当次是否最慢筛出的条件平均**。

| 普通指标 | 拆位循环 | 拼位循环 | 无循环打包 |
| --- | ---: | ---: | ---: |
| walltime | +0.031%（4/8 更快） | +0.903%（0/8） | **−0.904%（8/8）** |
| Host | +0.056% | +0.877% | −0.914% |
| 全局 eval | +0.049% | +1.818% | −1.485% |
| 全局 update | +0.305% | −0.183% | −0.226% |
| 分区 eval 合计 | −1.010% | +0.879% | −1.042% |
| p3 eval | +0.549% | +1.806% | −1.851%（6/8） |
| p6 eval | −1.997% | −0.367% | −3.708%（8/8） |
| p10 eval | −1.973% | +4.147% | −2.097%（8/8） |
| p18 eval | −1.202% | +0.815% | −0.188%（6/8） |
| p29 eval | +2.017% | +3.857% | −1.374%（8/8） |

无循环版首窗 walltime 绝对中位数 16.080→15.895 s；AB / BA 配对变化
−0.902% / −0.997%，八对范围 −1.552%..−0.125%。p29 没有命中新规则，
不能把其局部时间变化算作该分区新增打包的直接收益。

三套均通过专门结构边界测试与 Clang23/O3、ASan+UBSan 等价性测试。
拆位/拼位各 133120 例/编译模式；无循环版 65536 例/模式，包含八位全部
256 种取值、正/反向连续、不规则/混合偏移、1..64 位及合法移位范围。
正式模型 Difftest 的 PC、提交指令、guest cycles、step 数与基线一致。
三个原型均不修改正式 emitter 或生产默认，继续保留 64 字节对齐。

- [三套普通数据汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/compute_compact_results_20261004.json)、
  [静态反汇编](../../build/repcut_grhsim_20260925/active_dispatch_20261003/compute_compact_static_20261004.json)。
- [拆位原 ELF 采样](../../build/repcut_grhsim_20260925/active_dispatch_20261003/compute_bit_scatter_20261004/ordinary_perf/results.json)。
- 无循环版：[构建](../../build/repcut_grhsim_20260925/active_dispatch_20261003/compute_bool_pack_20261004/build.json)、
  [结构/布局覆盖](../../build/repcut_grhsim_20260925/active_dispatch_20261003/compute_bool_pack_20261004/coverage.json)、
  [等价性测试](../../build/repcut_grhsim_20260925/active_dispatch_20261003/compute_bool_pack_20261004/unit_tests.json)、
  [完整逐分区与逐对结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/compute_bool_pack_20261004/results.json)。

#### 原 ELF 采样、独立确认窗口与结论

无循环版再做四对原 ELF 采样，按同样的完整函数集合统计：

| 事件 | 全部改动 compute | 四对变化范围 | 全模型 |
| --- | ---: | ---: | ---: |
| cycles | −4.865% | −9.436%..−2.452% | −1.060% |
| retired instructions | −7.480% | −8.660%..−7.133% | −0.429% |
| frontend slots | −11.126% | −12.532%..−3.819% | −2.023% |
| IC miss | −12.715% | −13.547%..−10.841% | −4.661% |

未增加 wrapper，也没有新 helper 承接漏计的工作；四个事件在改动函数集合
均四轮同向下降，未检测到丢样/节流。这支持“既减少实际指令工作，又缓解
供指压力”，比仅看代码尺寸更有依据。但采样仍会扰动时序，perf 的外层
walltime 含采样器退出成本，不能与普通结果混算；例如 p29 compute 的
cycles 估计 +0.701%，并未重现普通 p29 eval 的改善。未改 compute 的
IC miss 也 −4.347%，说明间接布局/时序因素仍在，不能把整体 walltime
的全部收益归为新打包指令本身，更没有分解出某个特定缓存冲突的贡献。

随后关掉 perf，另外完成四对普通 AB/BA：walltime 配对中位数
**−1.029%（4/4 更快）**，Host −1.009%、全局 eval −1.763%，全局 update
+0.304%。该窗口 walltime 绝对中位数 16.035→15.880 s，配对范围
−1.735%..−0.126%，AB/BA 分别 −1.029%/−0.930%。

合并两个普通窗口的 **12 个实际配对比例**（不平均两个窗口的中位数）：

| 指标 | 配对中位变化 | 更快对数 |
| --- | ---: | ---: |
| walltime | **−0.965%** | **12/12** |
| Host | −0.973% | 12/12 |
| 全局 eval | −1.541% | 12/12 |
| 全局 update | +0.099% | 6/12 |
| 分区 eval 合计 | −1.187% | 12/12 |
| p3 全 step eval | −2.177% | 10/12 |
| p6 全 step eval | −3.759% | 12/12 |
| p10 全 step eval | −2.058% | 12/12 |
| p18 全 step eval | −0.087% | 8/12 |
| p29 全 step eval | −1.435% | 12/12 |

本轮三套普通对照、两套原 ELF 采样及无循环版确认窗口，合计 **72 次正式
C100000、12 次 C100** 全部通过；所有成功样本保留，没有用空闲率、运行
先后或耗时筛选。新增脚本为本目录的 `compute_bit_scatter*.py`、
`compute_bool_gather*.py`、`compute_bool_pack*.py`、相应 `test_*.py` 和
`compute_compact_*.py`；冻结 ELF、archive、输入身份及 runtime 配置均核验。

结论：**保留无循环 bool 打包作为下一轮实验候选，不保留两个循环方案作为
后续基线。** 对当前 workload，约 1% 的 walltime 收益得到第二个窗口支持；
不能承诺其他 workload 同幅获益。64 字节对齐继续保留，不新增布局调参。
目前完成的是经过完整模型验证的生成 C++ 原型，正式 emitter/生产默认、
Verilator 与 RTL 均未改变。后续应将此模式移入 GrhSIM 的正式宽拼接生成
路径，保持非连续/不适用 ABI 的原路径，并用完整重新生成及 IR 回归验证，
不继续扩大解释器式索引循环，也不转向按名字特调。

- [无改码采样与逐对事件](../../build/repcut_grhsim_20260925/active_dispatch_20261003/compute_bool_pack_20261004/ordinary_perf/results.json)、
  [确认窗口运行清单](../../build/repcut_grhsim_20260925/active_dispatch_20261003/compute_bool_pack_20261004/confirm_4pairs/manifest.json)、
  [12 对汇总、身份核验与保留决策](../../build/repcut_grhsim_20260925/active_dispatch_20261003/compute_bool_pack_20261004/confirmation.json)。

#### 增量更新：迁入正式 IR emitter（2026-10-04）

将上述无循环方案接入 `emitWordwiseWideConcat`，新增独立选项
`wordwise_wide_concat_bool_pack` / `WOLVRIX_GRHSIM_WORDWISE_WIDE_CONCAT_BOOL_PACK`。
默认关闭，仅与 `wordwise_wide_concat` 同开时生效；不修改 Verilator 或 RTL。
这一步是正式生成路径的实现和验证，并非将所有探索线选项改成生产默认。

识别依据改为 IR 和存储元数据，而非原型的 C++ 正则：允许真实 bool 值槽、
register/latch 字段及已内联的同宽纯别名；按表达式解析优先级保留物化快照，
不得绕过原值槽改读当前状态。仅合并同一目标字、同一存储基址、连续目标位
上的读取；不内联动态 memory/DPI/任意计算，不变更调度、激活集合或物理布局。
目标 C++ 编译时用 constexpr 判断八字节连续性及 bool ABI，适用则 load/mask/
multiply，不适用及尾部继续逐位展开。没有运行期索引表循环，也没有编译后反馈。

已通过第一轮专项回归：默认/off/attribute 优先级、7/8/9/63/64/65/127/128/129
位边界、正逆序及重复/间隔槽、跨字、纯别名与表达式/输入排除、物化读取、
拆分生成、bitmap/profile；独立黄金模型覆盖两次 init、256 个随机/全零/全一
周期、两沿及重复 eval，helper 穷举 256 个字节模式。Clang 23 和 GCC 的
ASan/UBSan 检查通过。旧 wordwise-concat、leaf-mux、wide-assign-xor、
same-reader、batch-bitmap 及 GrhSIM/Verilator RepCut package 回归均通过。

完整 XiangShan off/on 重新生成与原型对照入口为
`active_dispatch_20261003/emitter_bool_pack.py`。继续固定 node030 CPU96–127、
Clang 23/O3、N=K=32、all-spin 和 uniform64。旧的 commit-demand、same-reader、
exact-mask 等冻结差异须完整保留：全量生成后审计关闭开关的输出，再将不相交
的既有探索线差异合入，增量重编译受影响对象；不能把此流程称为“纯生产默认
从头构建”，也不能把遗漏旧优化产生的差异记到 bool pack 名下。

全量生成审计结果：off/on 各 7,552 个源码/头文件，off 与此前 leaf-mux 正式
生成输出逐字相同；on 只改变 134 个 compute 源文件和 32 个 runtime 头文件，
后者只有 helper/include 增量。原型 1,691 个状态 bool 拼接组全部保留，另覆盖
1,202 个真实 bool 值槽拼接组（原型正则遗漏了直接槽读取和不同标量 cast
拼写）。总计 2,893 组；扩展部分 31,658 次读取，其中 15,896 次可按连续八
字节打包，其余逐位展开。独立的纯存储文本 oracle 扩展拼写后与正式生成
输出逐文件相同；oracle 仅作审计，不参与生产代码的筛选。

回归夹具进一步固定真实 producer/consumer 边界，并断言确实生成值槽打包
和 direct-single-writer 读取，避免调度器复制 read root 后“开了配置却没有
测到目标路径”。含 latch 的最终专项回归通过；新开关打开时原 wordwise/
memory-concat 回归也通过。未改 RTL 或任何 Verilator 生成逻辑。

构建审计：134 个目标先重编译旧源，allocated code/constants/relocations
均与冻结基线一致，再编译正式候选；133 个 archive 成员实际变化，7,321 个
成员逐字节保留。受影响对象 `.text` 合计 4,656,298 → 4,241,778 bytes；
最终 ELF `.text` 为 94,341,042 bytes，原型为 94,516,978 bytes，原基线为
94,755,186 bytes。6,859 个主要 compute 入口全部仍为 64-byte 对齐。
上述体积变化不是性能收益，性能以接下来的 C100000 普通 AB/BA 为准。

最终实现范围补充：采用**仅 register/latch 状态 bool 字段**的版本，与已验证
原型的范围对齐；不将上述开发阶段的值槽扩展纳入保留方案。物化值槽完整保留
原宽拼接路径（不是绕过快照改读状态），仍支持已内联的同宽状态别名和已有
direct-single-writer 状态引用。这是统一的存储类别条件，不按分区/信号选择。
最终产物使用独立目录 `active_dispatch_20261003/emitter_bool_pack_state_20261004/`，
重新进行全量 off/on 生成、代码身份核验和专项回归；上面的 2,893 组及体积数据
仅描述开发中间范围，不代表最终保留代码的覆盖与性能。

最终全量生成/构建验证：

- off 的 7,552 个源码/头文件仍与旧正式输出逐字相同；on 改动 98 个 compute
  源文件、32 个 runtime 头文件，恰好覆盖原型的 1,691 组，无额外组、无遗漏组。
  移除原型在源文件内的 helper 后，98 个正式源文件与原型输出逐字相同。
- 保留所有冻结旧优化，重编译旧源的 allocated sections/relocations 核对通过。
  98 个对象相对未打包基线变化，7,356 个对象不变；6,859 个主要 compute 入口
  全部仍为 64-byte 对齐。受影响对象代码合计 3,527,484 → 3,288,915 bytes。
- **最终 archive 和 ELF 与原型各自逐字节相同**：archive SHA-256
  `a3ec0cd64c68846a53efd1ec4554e8a39e210a7f9cff349b3ebe52a2d0022bc6`；
  ELF SHA-256 `1cbbeeedd546fbb46357ef53d20dd4dcd5261ccbdb0672f6549e2b5faed6cc27`。
  因而正式化没有增加布局或机器代码扰动；对原型的 AB/BA 是同代码噪声检查，
  不能把其微小时间差解释为新优化收益。
- 最终九项 CTest 全通过：核心 `emit-grhsim-cpp`、wordwise-bool-pack、
  wordwise-concat、leaf-mux、wide-assign-xor、same-reader、batch-bitmap 及两种
 后端的 RepCut package。专项包含 Clang 23/GCC、ASan/UBSan、标量回退、
  物化快照不优化、direct-state 和 latch；核心全套测试单项约 307 s，九项
  并行运行总约 408 s。
- full off/on 各自 JSON 载入约 51.2 s、生成约 525.4/526.4 s；旧源重编译身份
  核对加候选增量编译合计 30.5 s（不含链接）。这是生成/增量编译审计口径，
  不是 7,454 个对象从零编译耗时。

复现与证据：[最终源码审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_bool_pack_state_20261004/audit.json)、
[构建身份](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_bool_pack_state_20261004/build.json)、
[九项回归日志](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_bool_pack_state_20261004/regression.log)。

最终普通版复测完成。固定 node030 CPU96–127、Host105、N=K=32、all-spin、
Clang23/O3、uniform64、NUMA1、ASLR off，CoreMark C100000；所有成功样本
保留。四对原型/正式版和八对原基线/正式版，共 **24 次 C100000、4 次 C100**
全部通过；正式运行开启 Difftest，终态均为 PC `0x80000c0c`、240349 条指令、
99996 cycles、100001 guest cycles、200102 steps。输入和 ELF 身份前后不变。

收益对照的 baseline 是本节开头的 **plain B 精确掩码 + same-reader + 纯 bool
别名 + leaf-mux 等旧有效线 +64**，不含 bool pack；不是 Verilator，也不是
已打包的原型。四对原型对照的 walltime 配对中位数为 −0.125%，区间
−0.189%..0%，由于两个 ELF 完全相同，仅用作同代码波动检查，不计入收益。

八对正式收益窗口：

| 指标 | 未打包基线运行中位数 | 正式版运行中位数 | 逐对变化的中位数 | 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| walltime | 16.165 s | 15.970 s | **−0.960%** | **8/8** |
| Host | 16.132 s | 15.9425 s | **−0.962%** | 8/8 |
| 全局 eval / step | 51.4585 µs | 50.6710 µs | **−1.466%** | 8/8 |
| 全局 update / step | 23.7755 µs | 23.8035 µs | +0.071% | 4/8 |
| 分区 eval 合计 / step | 638.5335 µs | 629.1280 µs | −1.493% | 8/8 |

变化列始终是 `median_i(100 × (candidate_i / baseline_i − 1))`；两列运行
中位数只是绝对耗时概括，不是用它们相除计算变化。walltime 八个配对变化为
−0.684%、−1.606%、−0.926%、−1.787%、−0.929%、−0.992%、−0.744%、−1.298%；
AB 四对中位数 −0.835%，BA 四对 −1.452%，两个顺序均为四对全胜。

本窗 p3/p6/p10/p18/p29 的全 step 分区 eval 配对变化分别为 −2.248%、
−2.743%、−3.074%、−1.371%、−1.624%，均 8/8 同向。这不是“成为瓶颈时”的
条件平均；p29 没有规则命中，其变化仍属整体代码/布局/时序的间接效果，不能
记为该分区直接少做了计算。

正式版与原型 ELF 相同，基线 ELF 也相同，故可合并先前 8+4 对与本次 8 对
（不包含四对同二进制检查）：**20 对 walltime −0.960%（20/20）**、Host
−0.962%（20/20）、全局 eval −1.487%（20/20）、update +0.099%（10/20 更快）。
这是保留原型收益的独立复测，不是新规则叠加出另一份约 1% 收益，也不外推到
尚未测试的 workload。

结论：**无循环状态 bool 打包已完成正式 emitter 实现与验证，保留此范围和
64 字节对齐。** 选项仍默认关闭；在当前探索线通过
`WOLVRIX_GRHSIM_WORDWISE_WIDE_CONCAT=1` 与
`WOLVRIX_GRHSIM_WORDWISE_WIDE_CONCAT_BOOL_PACK=1` 开启。未修改 Verilator、
RTL 或其他生产默认，也未进行代码布局搜索或编译后反馈。无需再手动改写
生成 C++ 来获得这项优化；既有提交路径原型的冻结保留范围见前面的构建说明。

- [四对原型对照](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_bool_pack_state_20261004/vs_prototype/manifest.json)、
  [八对基线复测](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_bool_pack_state_20261004/vs_baseline/manifest.json)、
  [最终逐对/分区汇总、20 对合并及身份核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_bool_pack_state_20261004/results.json)。
- 生产入口：`wolvrix/lib/emit/grhsim_cpp.cpp`；选项说明：
  `wolvrix/docs/emit/grhsim-scheduling.md`；回归入口：
  `emit-grhsim-cpp-wordwise-bool-pack`，实现于 `tests/emit/test_emit_grhsim_cpp.cpp`。

### 7.45 当前瓶颈复核与按需求计算局部位（2026-10-04）

接续 §7.44，冻结正式状态 bool pack 验证产物 `1cbbeeedd546…` 为新的
GrhSIM baseline，保留所有旧有效优化及 uniform64；不是回到未打包版。
Verilator/O3 继续采用共享派发/all-spin 普通 ELF `9ab8112408ae…`。
本轮不做编译后反馈或布局搜索，不按分区/模块/变量名称选择优化。

#### 最新相邻沿瓶颈分布

两后端从当前普通源码重新编译相同的低频相邻沿 timeline 封装。GrhSIM
只替换 common/eval/update 三个 wrapper，7451 个其他 archive member
与最新基线逐字节一致；Verilator 的三个 wrapper 以外，76 个链接输入
的身份与 §7.36 已记录构建完全相同。诊断程序不是普通性能二进制，不能
将其 walltime 用于新优化收益；模型与工作负载均未改变。

node030 CPU96–127、NUMA1、N=K=32、Host105、all-spin、Clang23/O3、ASLR off、
C100000，四对 V/G、G/V 交错与两次 C100 全部通过 Difftest；PC、退休指令、
cycle/guest cycle 和 steps 与既有签名完全一致。每 127 step 采当前及下一沿，
每次 3150 个样本，每后端合计 12600；相同步号与 clock 逐项一致。所有成功
运行保留，无空闲率 gate 或耗时筛选。

瓶颈仍定义为启动偏移加 eval duration 最大、即最后完成的分区。下表 G
只取它自身成为瓶颈时的 duration；V 使用同一配对、同一步、同一分区，
不混用 V 自选瓶颈样本，也不含启动等待和全局 update。

| 分区 | G 瓶颈次数 / 12600 | 占比 | G 条件 eval/µs | V 相同步 eval/µs | G/V 变化 |
| --- | ---: | ---: | ---: | ---: | ---: |
| p3 | 3993 | 31.69% | 41.940 | 79.349 | −47.14% |
| p18 | 2112 | 16.76% | 48.807 | 45.533 | +7.19% |
| p6 | 2108 | 16.73% | 57.877 | 35.248 | +64.20% |
| p10 | 1414 | 11.22% | 48.387 | 54.109 | −10.58% |
| p26 | 1065 | 8.45% | 52.794 | 26.103 | +102.25% |
| p29 | 947 | 7.52% | 52.901 | 28.205 | +87.56% |
| p27 | 239 | 1.90% | 54.547 | 20.599 | +164.80% |
| p25 | 224 | 1.78% | 55.575 | 19.379 | +186.78% |

完整 32 行（包括零样本项）见产物。另用其他三对 G 的完成时刻中位数
为留出一对独立选择标签，只选每 127 step 的首个锚点及紧接下一沿：

| 分区 | 独立标签样本数 | G 两沿 eval/µs | V 两沿 eval/µs | G/V 变化 |
| --- | ---: | ---: | ---: | ---: |
| p3 | 2075 | 84.173 | 147.856 | −43.07% |
| p18 | 1039 | 87.957 | 66.549 | +32.17% |
| p6 | 1034 | 88.196 | 97.056 | −9.13% |
| p10 | 701 | 79.349 | 70.457 | +12.62% |
| p26 | 604 | 69.665 | 79.372 | −12.23% |
| p29 | 451 | 53.213 | 62.782 | −15.24% |
| p27 | 102 | 61.945 | 58.703 | +5.52% |
| p25 | 80 | 59.813 | 54.484 | +9.78% |

p18/p10 的额外总计算仍值得优先调查；p6/p26/p29 的单沿慢不能直接解释
成两沿工作总量更大，但缩短其重半周期仍可能改善全局 walltime。不能只
盯 p3 的全程均值，也不能把旧瓶颈标签视为当前版本的实际分布。G 采样
全局 eval 50.270 µs = 最后完成者 duration 48.873 + 启动 0.865 + 收尾
0.532；V 对应 76.249 = 74.829 + 0.720 + 0.700 µs，均为探针口径。

- [构建与身份](../../build/repcut_grhsim_20260925/active_dispatch_20261003/packed_compute_followup_20261004/build.json)、
  [四对运行](../../build/repcut_grhsim_20260925/active_dispatch_20261003/packed_compute_followup_20261004/runs/manifest.json)、
  [条件统计及两沿](../../build/repcut_grhsim_20260925/active_dispatch_20261003/packed_compute_followup_20261004/results.json)、
  [完整分区表](../../build/repcut_grhsim_20260925/active_dispatch_20261003/packed_compute_followup_20261004/parts.csv)。

#### 通用候选：局部宽右移只计算实际读取的位

代码检查在 p18/b195 等位置发现 `tmp = lshr_words(source, shift, 224)` 后
只读取 `tmp[0]` 的 bit0。候选不限定这个函数或宽度：只要局部 const 宽值
临时量的完整消费者集合都是同一个常量 bit，就在**原定义点**计算该 bit，
替换所有相应读取；其他消费者、不同 bit、非局部写回均拒绝。保留原索引
越界行为和源值快照时刻，不把取值推迟到可能已更新状态的消费者处。

这里 `source` 是宽源值，`shift` 是逻辑右移量，`width` 是结果有效位宽，
`bit` 是被消费的结果位；新路径等价于读取 `source[shift + bit]`，并保留
原 helper 的移位越界、结果位宽和数组边界判断。例：只需 224-bit 右移
结果最低位时，不再构造四个 word 的中间数组；这是按消费者需求简化计算，
不是重新排列状态字段或取消观察者的变化通知。

全图统一规则命中 7 个分区、17 个 compute 源文件、2218 个局部宽右移：
p0/p6/p7/p17/p18/p23/p29 分别 2/2048/64/24/16/48/16 个，宽度为
67/128/224/256。该首个候选主要覆盖 p6，不能宣称已覆盖 p18/p10 的主热点。
重编译17个旧源并核验 allocated code/constants/relocations 与冻结基线
一致，再生成候选；16 个实际对象变化、7438 个不变，所有主要 compute
入口仍 64-byte 对齐。目标对象 text 609524→536125 bytes，静态缩减不是
性能结论。12 个结构正负例、9 种宽度/8 种取位位置、完整边界索引、宽/负
索引及非零 padding 由原 helper 与独立位参考共同核对；Clang23/O3、GCC/O3、
Clang ASan/UBSan 均通过。后续按普通 C100000 八对 AB/BA 判断 walltime。

#### 普通 walltime、代码对照与独立确认

两轮各八对普通 AB/BA，中间分开做四对原 ELF 的低频 user-only IP 采样。
所有运行使用相同已冻结输入；没有把 perf 的 walltime 混入普通结果。
首轮 walltime 配对中位数 −0.250%（7/8 更快、1 对持平），第二轮
−0.747%（8/8 更快）。合并16个逐对比例后如下；不能平均两轮百分比，
也不能从两列独立中位数直接反算变化列。

| 普通指标 | baseline 中位数 | candidate 中位数 | 配对变化中位数 | 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| walltime | 16.055 s | 15.955 s | **−0.530%** | **15/16，另1对持平** |
| Host | 16.0235 s | 15.9255 s | −0.521% | 15/16 |
| 全局 eval/step | 51.1070 µs | 50.5405 µs | −1.089% | 16/16 |
| 全局 update/step | 23.8530 µs | 23.9105 µs | +0.740% | 5/16 |
| 分区 eval 合计/step | 634.5360 µs | 630.5615 µs | −0.607% | 16/16 |

AB/BA 的 walltime 分别 −0.685%/−0.436%，两个顺序均同向。p6 的全程
平均 eval 36.7520→35.9135 µs，配对 −2.300%（16/16）；p3/p10/p18
分别 −1.042%/−0.732%/−0.328%，p29 为 **+2.084%（16/16 变慢）**。
不隐去 p29/update 的退化，也不把这些无条件平均值写成瓶颈条件均值。

与 Verilator 对应路径的源码核对：p6 的 128-bit 数据动态取位已经输出
`source[(index >> 5) & 3] >> (index & 31)`，外层保留有效位判断，而不是
先形成完整宽右移结果。GrhSIM 新路径使用其自身64-bit word，做同类
按需读取；没有复用 Verilator 实现或改变两后端 RTL。对应 Verilator
位置是 `VWolviRepCutUnit_part_6___024root__26.cpp` 第295行附近，原
GrhSIM p6/b184 第3703行附近；位置仅用于解释机制，不参与筛选。

17 个重编译对象的静态指令126952→107018、条件跳转5594→3599、
CMOV 5352→4136、含 `%rsp` 的静态栈引用28672→26717；调用23→23。
其中 p6/b184 指令49796→42848、条件跳转2304→1510，p6/b158
指令15969→10750、CMOV 1045→149。说明 Clang23/O3 没有完全消除原
全宽表示带来的多余操作；静态栈引用不是动态访存计数。

原 ELF 四对 IP 采样按 sample period 汇总，无丢样/节流。改动 compute
集合 cycles −9.723%、retired instructions −2.266%、前端未供给槽
−5.955%、IC miss −4.767%，四项均四对同向；全模型对应
−1.114%/−0.010%/−1.115%/−3.735%。改动函数在原模型采样周期中仅占
**1.421%**，因此不能把局部 −9.7% 换作整体收益。p6 全 compute 指令
约 −1.001%（4/4），但 cycles −0.663%（2/4）；p6/b184 cycles 约
−7.335%（3/4），稀疏单函数样本只作方向性证据。未改 compute 的周期
和 IC miss 也约 −0.859%/−4.025%，整体收益不能全部归于删减的指令，
仍有代码布局/执行上下文的间接影响；本轮未据此搜索布局参数。

- [结构覆盖](../../build/repcut_grhsim_20260925/active_dispatch_20261003/compute_shift_bit_20261004/prepare.json)、
  [对象与入口对齐审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/compute_shift_bit_20261004/build.json)、
  [专项测试](../../build/repcut_grhsim_20260925/active_dispatch_20261003/compute_shift_bit_20261004/unit_tests.json)。
- [首轮八对](../../build/repcut_grhsim_20260925/active_dispatch_20261003/compute_shift_bit_20261004/ordinary/manifest.json)、
  [独立八对](../../build/repcut_grhsim_20260925/active_dispatch_20261003/compute_shift_bit_20261004/confirm_8pairs/manifest.json)、
  [原 ELF 采样](../../build/repcut_grhsim_20260925/active_dispatch_20261003/compute_shift_bit_20261004/ordinary_perf/results.json)、
  [16对及静态汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/compute_shift_bit_20261004/results.json)。

#### 固定关键步闭环与保留决定

最后另做四对相邻沿 A/B 诊断。标签来自本节最初四次 GrhSIM 运行的同一步
完成时刻中位数，与这八次被评估运行完全独立；不以候选的新慢步回选样本。
每一对先对固定步集合取算术均值，再计算比例，最后取四对比例中位数。
仍只替换三个 wrapper，7451 个其他成员保持各自普通版身份，探针 walltime
不参与前述16对结果。

| 分区 | 每次固定样本数 | A 条件 eval 中位/µs | B 条件 eval 中位/µs | 四对配对变化 | 更快 |
| --- | ---: | ---: | ---: | ---: | ---: |
| p3 | 1003 | 41.271 | 41.326 | +0.124% | 2/4 |
| p6 | 563 | 54.321 | 53.108 | **−2.849%** | **4/4** |
| p10 | 355 | 48.130 | 47.915 | +0.116% | 2/4 |
| p18 | 538 | 49.403 | 48.270 | −1.785% | 4/4 |
| p25 | 43 | 51.295 | 52.344 | +2.662% | 0/4 |
| p26 | 291 | 52.558 | 51.571 | −1.878% | 3/4 |
| p27 | 46 | 52.146 | 52.582 | +1.188% | 1/4 |
| p29 | 223 | 51.071 | 51.124 | −0.019% | 2/4 |

p6 在固定瓶颈步确实改善，不只是全程平均降低；实际最后完成次数从
2104/12600 降至1954/12600。p29 从952增加到1144，但同一固定步的自身
耗时接近不变，说明“成为瓶颈更多”不能直接当作“这些关键步计算更慢”。
也不能因此抹去普通版 p29 全程平均 +2.084%：两者是不同二进制执行上下文
和样本条件。p3/p10 普通均值的改善在固定步中未稳定重现，p25/p27 条件
耗时有反向变化；覆盖较小的 p18 改善也不能全部归因于16处直接取位。

结论：**保留局部宽右移单 bit 需求原型作为下一轮实验候选**，其普通
walltime 在两个窗口、两种执行顺序均有小幅收益；当前幅度约0.53%，不
宣称大幅加速或已经解决 p18/p10 的残余差距。本轮没有扩大到其他消费
模式，也没有按照分区挑选启用。64-byte 对齐和上一轮状态 bool pack
保持开启，生产 emitter/默认、RTL 和 Verilator 均未修改。

候选普通 ELF SHA-256：
`613e4b83ec3d5e306b57f14f8115a5c1bbb3f83ea7820fd60bb2de79af32c182`。
完整流程共56次正式C100000、10次C100通过Difftest；所有成功样本、输入
身份和均值/比例口径已复核，17个改写源重新执行规则并逐字节比对一致。
未修改生产生成器，因此没有把原型的C++专项冒充新的全套IR emitter回归。

后续应先将已验证的“局部值完整use集合→按需求计算”条件落入IR生成路径，
保留原定义点快照与越界语义并验证off/on产物；继续调查p18时，需关注本轮
未覆盖的混合窄字段拼接与跨计算块中间值，不靠扩大当前单bit规则的名单。

- [固定关键步构建](../../build/repcut_grhsim_20260925/active_dispatch_20261003/compute_shift_bit_20261004/critical/build.json)、
  [四对诊断运行](../../build/repcut_grhsim_20260925/active_dispatch_20261003/compute_shift_bit_20261004/critical/runs/manifest.json)、
  [固定标签、两沿和迁移统计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/compute_shift_bit_20261004/critical/results.json)。

#### 2026-10-04 增量：局部宽右移需求规则迁入正式生成器

本轮只迁移上一增量已验证的局部单 bit 需求规则，不扩大消费模式、不增加
分区名单，也不改变前述瓶颈标签。正式入口为 GrhSIM emitter attribute
`local_shift_demanded_bit` / 环境变量
`WOLVRIX_GRHSIM_LOCAL_SHIFT_DEMANDED_BIT`，**默认关闭、显式 attribute 优先**；
验证线开启，64-byte 对齐与此前状态 bool pack、纯 bool alias、same-reader、
exact-mask 等已验证改动均保留。那些尚在生成后原型层的旧改动，本轮仍通过
冻结差量重放；不能因此宣称整条实验线已全部成为生产默认。

实现直接检查 IR 宽逻辑右移结果的完整使用集合：结果必须是无变化跟踪的
compute 局部值，所有消费者均为同一 supernode 后续读取同一常量位的
单比特静态切片。宽值端口输出、跨块/commit 使用、不同位、动态切片、event、
算术右移等走原路径。bool 在原移位定义处求值一次，不延后源读取，不将
bool 混入宽数组表达式映射；消费端仍使用原单比特赋值、变化传播和激活路径。
helper 沿用原移位量归一化及源 padding 语义。

正式说明与开关见 [GrhSIM 调度文档](../../wolvrix/docs/emit/grhsim-scheduling.md#实验性局部宽右移的单比特需求计算)。
专项 IR fixture 覆盖默认/关闭/attribute 优先/环境变量、普通/分 helper/
bitmap 校验/perf 生成，包含同位多消费者、完整宽输出、跨块、不同位、
宽切片、事件、动态切片、算术/窄移位，以及状态读写后的两沿、重复 eval
和重复 init；helper 另与旧实现及独立位运算 golden 对照，检查宽度边界、
脏 padding、负移位量及高字非零的宽移位量。Clang/GCC 与 ASan/UBSan
用于候选运行期检查，不把单独 helper 测试当作全模型正确性的替代。

完整 32 分区重新生成及审计通过：

- off 的全部 **7552 个 C++/头文件与上一轮正式状态 bool pack 的 on 产物
  逐字节一致**；on 仅 17 个 compute 文件改动、32 份 runtime 头增加 helper。
  2218 处命中和上一轮原型完全相同，每个改动 C++ 文件均与独立文本规则
  逐字核对一致；不是仅抽查 p6，也没有将原型输出直接当作 IR 生成结果。
- 冻结旧实验差量重放后，17 个原基线源重新编译的分配节、常量及重定位
  与原 archive 对应成员一致；候选仍保留 **6859 个 compute 入口的 64-byte
  对齐**。实际相对优化前仅16个对象变化，p7/b238仍被编译成相同机器码，
  其余7438个成员保持原身份。
- 正式版候选 archive SHA-256
  `825a202bc233c0a7e2a16177194a80d1c806126039ec0277e4e78ebacb44fe30`，
  最终 ELF SHA-256
  `613e4b83ec3d5e306b57f14f8115a5c1bbb3f83ea7820fd60bb2de79af32c182`，
  与上一轮原型一致；本轮迁移本身不是一次新的叠加优化。
- **10项相关CTest通过**：新需求位专项、原GrhSIM综合、bool pack、leaf mux、
  wide-assign XOR、wordwise concat、same-reader、bitmap校验，以及
  GrhSIM/Verilator repcut package。新专项包含Clang23/GCC和ASan/UBSan。
  这里只称相关回归，不声称运行了仓库全部测试。

产物：[冻结生成身份](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_shift_bit_20261004/identity.json)、
[全量off/on审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_shift_bit_20261004/audit.json)、
[编译与机器码审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_shift_bit_20261004/build.json)、
[相关回归日志](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_shift_bit_20261004/regression.log)。

性能仍使用 node030 CPU96–127、NUMA1、N=K32、Host105、all-spin、
Clang23/O3、关闭 ASLR、CoreMark C100000。A 基线是**正式状态 bool pack＋
64-byte 对齐，但没有单 bit 需求优化**，不是最初 GrhSIM 默认或 Verilator。
比值均先在每对内计算，再取中位数；独立 walltime 中位数仅供查看绝对量级。

| 对照 | 对数 | 基线 wall 中位/s | 候选 wall 中位/s | 配对 wall 变化 | 候选更快/持平 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 已优化原型→正式生成版（ELF完全相同） | 4 | 15.975 | 16.055 | +0.533% | 1/4、0持平 |
| 未启用需求位优化→正式生成版，本轮普通复测 | 8 | 16.005 | 16.055 | **+0.188%** | 1/8、2持平 |
| 前两窗口16对＋本轮8对，按相同ELF身份合并 | 24 | 16.045 | 15.975 | −0.250% | 16/24、3持平 |

本轮八对 Host +0.175%、global eval +0.189%、update +0.423%，不能写成
“本窗口保住了此前 −0.53% 收益”。p6全程 eval −0.305%，p3/p10/p18/p29
分别 +0.641%/+1.616%/+0.280%/+3.826%。24对合并 Host −0.222%、eval
−0.941%、update +0.585%；合并仅作跨窗口描述，**不覆盖本轮未复现的事实**。

原型/正式版四对的 wall 变化范围为 −0.437%..+0.942%，且7454个对象、
ELF所有分配节、模型函数地址图和完整ELF均一致。因此这里的差值不能归因
于迁移删除/增加了机器指令；但也不能据此认定具体是频率、缓存、文件页
落点或外部负载。没有测量证据就不指定其中某一个原因，更不能将这组
+0.533%直接从另一组结果中相减，造出“校正后收益”。

[原型/正式版校验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_shift_bit_20261004/vs_prototype/manifest.json)、
[本轮普通八对](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_shift_bit_20261004/vs_baseline/manifest.json)、
[身份、全部样本及24对汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_shift_bit_20261004/results.json)。

为检查上述同ELF差异，又增加六轮三方普通对照：A为未启用需求位优化的
基线，B为原型文件，C为正式生成文件。用硬链接将三者的可执行文件路径
长度对齐，保留各自原文件/inode；计时输出路径也等长。运行顺序采用全部
六种排列 `ABC/CBA/BAC/CAB/BCA/ACB`，不修改二进制、CPU映射或代码布局。
这不是寻找某一种最快布局；六轮18次均保留，不能把共享同一轮A的两种
比较当成12对独立A/B样本。

| 六轮三方对照 | wall配对变化 | Host配对变化 | global eval配对变化 | wall更快 |
| --- | ---: | ---: | ---: | ---: |
| 原型B / 未优化A | −0.930% | −0.904% | −1.339% | 5/6 |
| 正式C / 未优化A | −0.341% | −0.332% | −0.242% | 5/6 |
| 正式C / 原型B（同ELF） | **+0.564%** | +0.571% | +0.565% | 0/6 |

绝对wall中位数A/B/C为16.100/15.960/16.070 s。C/B六轮同向，说明不能
简单将所有差异叫作一次偶然计时离群；等长路径和顺序轮换也没有消除它。
但当前对照仍没有隔离文件页物理落点、缓存状态、执行上下文等因素，不能
指定根因。C/A的p6全程eval −1.254%，而p3/p10/p18/p29为
+0.133%/+0.267%/+0.720%/+2.790%；不能用其中某个局部均值解释全部wall变化。

最后单独增加B/C各一次C100000只读诊断，在运行中读取`maps`与`numa_maps`，
不把这两次计时加入普通wall统计。两者主程序虚拟映射起点相同，执行段均为
`55555555d000-55555af70000`；采样时均驻留22963个4 KiB代码页，**全部在NUMA1**。
主程序其余文件映射的页数/NUMA归属也相同。此快照不支持“某份代码放在
远端NUMA”这一解释，但不等于物理页号/缓存组或整个运行期状态相同。

关于 ASLR：这个 ELF 是 PIE（`ET_DYN`），所以如果启用 ASLR，代码/库/堆
地址变化确实可能影响 i-cache/BTB/TLB，理论上会造成小幅运行差异。因此
正式 runner 的实际命令链固定为
`taskset → numactl → setarch x86_64 -R → emu`，不是只在 manifest 中写一个
标签；`setarch -R` 设置的 Linux personality 为 `0x00040000`
（`ADDR_NO_RANDOMIZE`）。两次只读诊断的完整 `/proc/<pid>/maps` 都有123行，
去掉候选文件 inode 和路径名后逐行相同；主程序基址、共享库/匿名映射的
地址布局也一致。因此当前同 ELF 的约 `+0.56%` 差异**不是由 ASLR 未关闭
造成的**，无需再改成全局 `kernel.randomize_va_space=0`。全局关闭会影响
节点上其他进程，反而不适合这个实验；以后只要沿用 runner 的 `setarch -R`
即可。剩余差异应继续从频率/缓存与 TLB 状态、页缓存冷热、线程启动和
内核调度等方面排查，不能再用 ASLR 解释。

本增量共 **42次普通C100000、2次只读诊断C100000、7次C100初始化检查**
通过；C100000均通过Difftest，所有成功样本、冻结输入身份和运行配置保留。
**结论分开表述：正式生成迁移已完成且与原型机器码完全相同；最终wall收益
仍是小幅、对运行上下文敏感的趋势，本轮不能宣称稳定保住0.53%。** 保留
`local_shift_demanded_bit` 默认关闭的实验开关，验证线可以开启；不升级生产
默认，不修改RTL/Verilator，也不通过挑选分区或丢弃不利样本来“恢复”收益。
同ELF运行差异的根因尚未定位，不影响本轮代码等价与功能验证结论。

[三方控制脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/shift_bit_threeway_control.py)、
[六轮运行记录](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_shift_bit_20261004/threeway_control/manifest.json)、
[三方统计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_shift_bit_20261004/threeway_control/results.json)、
[代码页NUMA快照](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_shift_bit_20261004/numa_diagnostic/results.json)。

### 7.46 同文件重复性与固定瓶颈步的后端归因（2026-10-04）

接续 §7.45，先校准重复性，再回到 p10/p18 的代码机制。保留所有现有验证
优化和 uniform64；冻结正式 demanded-bit ELF `613e4b83ec3d…`，不继续搜索
布局、不做编译后反馈、不改生产默认。node030 CPU96–127、NUMA1、N=K=32、
Host105、all-spin、Clang23/O3、每进程 `setarch -R`、CoreMark C100000。

#### 相同 ELF、inode、路径、目标 argv 与环境的 24 次普通复跑

24 次执行同一实际文件，A/B 只是统计标签，按 12 对 AB/BA 交替。目标进程
的 timing 输出也固定为同一路径，每次退出后再归档；环境散列固定。另做
8 次独立 `perf stat`，不与普通 walltime 混算。不设空闲率门槛，不剔除任何
成功样本；32 次正式运行及一次 C100 均通过，正式运行 Difftest、固定签名、
绑核/派发配置和前后输入身份全部核验通过。

| 普通指标 | 24 次中位数 | 最小–最大 | 变异系数（标准差/均值） |
| --- | ---: | ---: | ---: |
| walltime/s | 16.060 | 15.960–16.120 | 0.244% |
| Host/s | 16.024 | 15.922–16.085 | 0.244% |
| 全局 eval/step/µs | 51.1555 | 50.936–51.483 | 0.247% |
| 全局 update/step/µs | 23.7265 | 23.378–24.230 | 0.715% |

伪 B/A 的 12 个 walltime 比例中位数为 **+0.0625%**，5 快、6 慢、1 平；
按 run pair 重采样的中位数 bootstrap 95% 区间为 **[−0.3729%, +0.2494%]**。
单对绝对差异中位数 0.3422%、经验 P95 0.7284%、最大 0.9311%。这不是
普适“噪声上限”，也不是要求收益必须超过某固定百分比；它表明单对约
0.5% 的差异不足以单独确立收益，应依靠多窗口配对、机制计数和局部热点
共同验证。§7.45 同字节、不同 inode 两文件连续 6/6 同方向的现象，仍不能
据此归结为随机噪声，根因仍未被排他确定。

普通版无 major page fault；非自愿切换 397–488 次，与 walltime 的 Pearson
r=0.184；自愿切换 r=−0.196，minor fault r=−0.062，未形成单一明显解释。
8 次独立 PMU 诊断 walltime 中位数 16.13 s，所有事件 100% running。
cycles/task-clock 得到的全进程运行态平均频率为 3.6015–3.6048 GHz，跨度
约 0.091%，不支持“整进程大幅降频”作为主要解释；它不是关键分区单次
eval 的频率，不能排除局部短时变化。全进程计数含大量 all-spin，不用于
推断模型指令工作量。开跑前后 cpufreq 快照、cycles/instructions/
branch-misses/cache-misses/context-switches 原始数据均保留。

[复跑脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/repeatability_fixed_path.py)、
[32 次运行清单](../../build/repcut_grhsim_20260925/active_dispatch_20261003/repeatability_fixed_path_20261004/runs/manifest.json)、
[完整统计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/repeatability_fixed_path_20261004/runs/results.json)。

#### 独立固定标签：p10/p18 的两沿 PMU 对照

使用 §7.45 四次旧 GrhSIM timeline 的完成时刻中位数选标签，与本轮被测
运行完全独立。每127 step采样该步及下一步，事先排除首个127/128初始化
采样对，留下3148步/运行。历史 p10/p18 标签各355/538步；只取首步为该
分区瓶颈的相邻沿，则各175/260对，首步 clock 全为1（上升沿），下一步
为下降沿。两后端使用完全相同的 guest step，不从新测量中挑慢样本。

GrhSIM 为 `613e4b83ec3d…` 的全部原模型对象，Verilator/O3 为
`9ab8112408ae…` 的原模型/共享派发实现。每后端只换 common/eval 两个
诊断 wrapper；GrhSIM 其余7452个 archive member逐字节不变。只在 p10/
p18 的采样 eval 前后读取线程本地四事件 pinned group；eval时钟不包含
前置/后置 perf 系统调用，计数差值仍含两个时钟读取等固定探针开销。
每种 core/pipeline/cache/memory 模式各四对 AB/BA，共32次C100000与8次
C100，全部功能、身份、绑定与3148步计数运行率核验通过，没有multiplex。
每个模式独立测量，不能把不同模式的事件拼成同一次硬件快照。

下表取 core 模式四个**run 内条件均值**的中位数；变化列为四个 G/V
配对比例的中位数，不是左右两个中位数直接相除。

| 分区/范围 | V eval/µs | G eval/µs | G/V 变化 | V 指令数 | G 指令数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| p10 上升沿 | 56.833 | 49.650 | −12.60% | 426592 | 324256 |
| p10 紧接下降沿 | 16.844 | 33.452 | +99.19% | 137903 | 243337 |
| p10 两沿合计 | 73.620 | 83.102 | **+12.77%** | 564495 | 567592 |
| p18 上升沿 | 47.892 | 49.412 | +3.12% | 388608 | 274360 |
| p18 紧接下降沿 | 21.794 | 39.942 | +84.07% | 186936 | 266248 |
| p18 两沿合计 | 69.665 | 89.354 | **+28.35%** | 575544 | 540608 |

p10 的上升沿实际更快，两沿差额来自下降沿；p18 差额也主要在下降沿。
但不能只把下降沿指令增加解释为“做了更多总计算”：合计指令分别仅
**+0.55%/−6.07%**，cycles却 **+12.61%/+27.94%**，IPC由
2.129→1.902、2.290→1.682。两沿合计的四种事件模式耗时变化分别处于
p10 +11.67%～+12.77%、p18 +28.35%～+29.32%，方向可重复。

| 两沿指标 | p10 V→G | p18 V→G |
| --- | ---: | ---: |
| 动态分支数 | 8953→15731（+75.71%） | 7144→15047（+110.64%） |
| 错分支次数 | 591→996（+68.55%） | 768→1693（+120.60%） |
| 错分支率 | 6.60%→6.33% | 10.75%→11.25% |
| 前端未供给槽 | 846827→1084928（+28.07%） | 855785→1278004（+49.27%） |
| 前端未供给槽 / 6 cycles | 53.3%→60.8% | 56.8%→65.9% |
| 后端阻塞槽 / 6 cycles | 9.7%→4.8% | 3.4%→3.1% |
| 指令缓存 miss | 58042→62117（+7.05%） | 56020→66391（+18.51%） |
| Op Cache miss | 49790→55051（+10.60%） | 48282→56943（+17.93%） |

不能称为“预测器准确率整体差一倍”：p10的错分支率还略低，重要差异是
分支总量增加。前端计数与IC/Op Cache事件共同支持检查供指和控制流成本；
不能将前端未供给槽比例直接当作可删除的walltime，也没有把每个多出的
cycles都归因到branch miss。四模式的cycles/测量ns频率差仅约0～−0.36%，
不支持降频解释12%/28%的分区差距。generic cache-references/misses也完整
保留，但不将其称作纯数据cache或DRAM流量。

另核对了生成的调度代码：GrhSIM 在同一次 `eval()` 的固定点循环中执行
compute、commit，commit激活reader时继续迭代；并非统一拖至下一次eval。
Verilator则在其ICO、ACT、NBA区域循环中调度。当前p10/p18的eval对象与
原可查源码对应对象的allocated data及relocations完全一致，只将text对齐
从16提高到64。因此两沿差异不能未经路径计数就命名为重复计算或延迟提交。

探针仍改变地址：PMU/IP版的6859个compute入口均保持64对齐，但相对普通
版分别整体平移；精确位移记录在audit.json中。此处是**诊断版本的分区
归因**，不是新的普通walltime结论，不用它衡量此前约0.5%的优化收益。

[实验脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fixed_step_backend_diagnostics.py)、
[构建与输入](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fixed_step_backend_20261004/build.json)、
[独立标签](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fixed_step_backend_20261004/labels.json)、
[PMU完整统计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fixed_step_backend_20261004/pmu_results.json)、
[代码/布局审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fixed_step_backend_20261004/audit.json)。
槽指标口径沿用 Linux perf 的
[Zen4 pipeline定义](https://raw.githubusercontent.com/torvalds/linux/master/tools/perf/pmu-events/arch/x86/amdzen4/pipeline.json)，
IC/Op Cache事件核对其[cache定义](https://raw.githubusercontent.com/torvalds/linux/master/tools/perf/pmu-events/arch/x86/amdzen4/cache.json)。

#### 固定区间地址采样、代码对照与本轮结论

继续对相同175/260对历史上升沿锚点及紧接下降沿做按线程启停的 user-only
采样。cycles周期1000003、branch-misses周期8191；只分析该分区选中区间，
不采其他进程、不改系统采样参数。每个分区/事件四对G/V交错，共32次
C100000与8次C100，均通过；全部区间enabled=running，lost=throttled=0。
IP探针仍仅替换两个wrapper，7452个模型/框架对象不变。普通/PMU/IP的
compute入口差值为0/+4032/+5952 bytes，全部6859个入口64对齐。

| GrhSIM 周期 IP 样本 | p10（201个） | p18（336个） |
| --- | ---: | ---: |
| compute | 169，84.1% | 302，89.9% |
| commit | 14，7.0% | 20，6.0% |
| 模型eval顶层派发 | 5，2.5% | 8，2.4% |
| 其余/主ELF之外 | 13，6.5% | 6，1.8% |
| 仅下降沿：compute/全部 | 73/80，91.3% | 159/163，97.5% |

G的最热单个compute分别为p10/b15的9个、p18/b210的10个样本，只占全部
4.5%/3.0%；更适合寻找多个batch共有的代码模式。V对应184/254个周期
样本，下降沿主要落在ICO函数，上升沿还包括NBA提交/组合区域。函数
边界不一一对应，不用“一个G函数/一个V函数”的大小比例解释整分区速度。
这是低频、非precise采样，样本有限且可能skid，足以作阶段粗分布，不适合
给相近小函数排精确名次或把落点指令当成唯一阻塞源。

错分支IP中，G p10的88个样本有48个compute、35个commit；p18的216个
有143个compute、65个commit。也就是说commit错分支密度高，但其周期
份额较小；按错分支数量排序不能直接等价于按可节省walltime排序。两组
均未发现顶层调度独占残余成本，不能将本轮结果重新解释为线程唤醒问题。

按实际周期落点反查未变的源码与汇编，发现应进一步检查的通用模式：

| 示例compute | 静态指令 | 静态条件跳转 | 含栈寄存器引用的指令 | SIMD重排类指令 |
| --- | ---: | ---: | ---: | ---: |
| p10/b78 | 8242 | 79 | 991 | 1671 |
| p18/b210 | 5017 | 22 | 1129 | 21 |
| p18/b196 | 4021 | 44 | 563 | 202 |
| p18/b179 | 4526 | 66 | 1132 | 47 |

p10/b78的采样邻域实际包含 `packuswb/punpck*/pshuf*` 链和栈向量读写，
不是所有热点都表现为条件跳转。该源文件264个显式窄局部值中，有110个
定义到最后使用相隔超过50行，最长144行；p18/b210的60个中有17个超过
50行，p18/b179的73个中有29个。这里的行距是**词法诊断**，不是机器
寄存器活跃区间；静态栈引用也包含局部对象，不能全称为动态spill。
V热点同样可见栈读写，因此尚不能声称这些计数已排他证明G慢的原因。

**下一项优先级收敛为：真正物化的窄局部值就近计算，以及窄字段拼拆的
中间表示。** 现有 `local_compute_use_order` 的收益门槛只统计>64-bit
普通局部值（源码 `grhsim_cpp.cpp` 中LiveRange收集处），原理由是标量
通常内联；本次源码/汇编提示，不能将实际声明并长期存活的u8/u16/bool
也一概忽略。后续应区分真正物化的标量与纯内联表达式，先统计全图结构
覆盖，再在已有依赖、状态快照及副作用边界内尝试缩短存活区间或按消费者
就近组装。禁止把所有窄值强行物化，也不把所有SIMD、所有分支禁掉。

这是待验证的机制假设，不是已经实现的新优化。筛选必须只看局部值/使用
关系与纯度，不匹配p10/p18、模块或信号名，也不使用编译后热点名单。
保留64对齐；候选需证明Difftest/功能等价、相关栈/重排/前端计数改善，
并由全part普通C100000多窗口AB/BA给出最终walltime，不能只看诊断版。
旧的全word all-on复制路径已有低覆盖证据，当前也没有重开的依据。

本轮总计 **96次有效C100000、17次C100**：24次普通同文件复跑、8次
全进程计数、32次固定步PMU、32次固定步IP。全部有效样本与身份保留，
不改RTL、Verilator、生产默认或现有验证线模型；没有新增walltime收益
声明。已校准重复性并定位到compute/供指方向，但**同字节不同inode的
旧6/6差异根因仍未排他定位，局部窄值假设也还需要受控修改来证实**。

[周期地址采样](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fixed_step_backend_20261004/ip_results.json)、
[错分支采样](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fixed_step_backend_20261004/ip_branch-misses_results.json)、
[汇编邻域及源码审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fixed_step_backend_20261004/code_audit.json)、
[统计脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/report_fixed_step_backend.py)、
[总核验记录](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fixed_step_backend_20261004/verification.json)。

### 7.47 显式窄局部值的消费者顺序实验（2026-10-04）

承接 §7.46，这次实际修改已经声明为 `const bool/u8/u16/u32/u64`
的局部值，不把所有标量 IR 值都算成需要存储的临时量。冻结基线是
`emitter_shift_bit_20261004/candidate/emu`（SHA256 前缀 `613e4b83ec3d`），
保留全部既有验证线变换及统一 64 B 对齐。当前为生成 C++ 的受控原型，
不改生产默认、RTL、Verilator、分区和通信；若有稳定收益再迁入 IR。

#### 通用规则与首轮检查点

只在连续的纯标量常量声明区间内重排。允许的辅助函数经 runtime 源码
核实为纯计算；状态写入、未知调用、控制流、引用声明和宽临时量均截断
区间。依赖关系决定先后，区间外仍有消费者的值作为根；每个计算保留一次，
声明及表达式逐字不改，不跨写入移动读取。范围只由声明类型、纯度和
依赖决定，没有 part/模块/RTL 信号名单，也没有编译后反馈筛选。

预先固定门槛为 `Σ C++标量存储字节数 × 声明距离` 至少减少 256，且
至少减少 25%；单位是 byte·declaration，不是动态 spill 字节或真实
寄存器分配。第一版按消费者深度优先顺序生成；全图 6859 个 compute
文件中命中 24 个 part、130 个文件、235 个区间、27062 个声明，近似成本
3205189→310542。5 种类型×20000 组输入的 O0/O3、ASan/UBSan 及
写入/未知调用边界检查通过；重编译所有受影响基线对象的分配区段与重定位
payload 均匹配冻结 archive，全部 compute 入口仍为 64 B 对齐。

受影响对象 text 3065850→2921989 B（约 −4.69%），但并非每处都改善：
p10/b78 的静态指令 8242→10715、栈引用 991→3752，SIMD 重排则
1671→483。这提示“少做重排”可能伴随丢失有益向量化；这些仍是静态
数量，不能直接解释为动态 spill 次数。首轮 4 对普通 C100000 均通过
Difftest，配对 walltime 中位 +0.312%，全局 eval −0.002%，不能宣称
加速。正在用 §7.46 的独立固定步标签复核 PMU，并验证每组 8 个相邻
依赖保留组内原拓扑顺序的版本，避免直接将长串计算全标量化。

本轮继续 node030 CPU96–127、NUMA1、N=K=32、Host105、all-spin、
Clang23/O3、进程级 ASLR off、C100000，保留所有有效性能样本。
先普通版后诊断版分开统计；生成、编译和仿真不重叠占用保留核。

[原型及专项测试](../../build/repcut_grhsim_20260925/active_dispatch_20261003/narrow_local_use_order.py)、
[全图覆盖](../../build/repcut_grhsim_20260925/active_dispatch_20261003/narrow_local_use_order_20261004/prepare.json)、
[构建与身份核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/narrow_local_use_order_20261004/build.json)、
[静态机器码](../../build/repcut_grhsim_20260925/active_dispatch_20261003/narrow_local_use_order_20261004/static.json)、
[普通结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/narrow_local_use_order_20261004/results.json)。

#### 两种候选完成：缩短源码距离没有换成更少的真实溢出

第二版将相邻消费者/输入依赖按固定 8 项分组，组内依赖闭包保留原拓扑
顺序，组间仍靠近消费者；高扇入的单个标量根也分组处理其直接输入。
沿用同一 256 byte·declaration/25% 门槛，全图扫描命中 8 个 part、15 个
文件、19 个区间、4143 个声明，近似成本 469496→228783；没有为了
保住某个 part 而人工增删名单。专项另外覆盖高扇入单根及共享依赖，
O0/O3、ASan/UBSan 均通过。第一/二版实际改变 116/14 个 archive
member，其余 7338/7440 个 member 完全不变；所有 6859 个 compute
入口保持 64 B 对齐。

p10/b78 是两种通用规则自然命中的同一例子。以下是整个函数的静态
机器码/Clang 寄存器分配统计，不是每个 step 实际执行次数：

| 指标 | 冻结基线 | 逐消费者 | 8 项分组 |
| --- | ---: | ---: | ---: |
| 函数 text / B | 43394 | 59796 | 60175 |
| 静态指令 | 8242 | 10715 | 10481 |
| 向量指令 | 5350 | 1499 | 902 |
| SIMD 重排指令 | 1671 | 483 | 363 |
| 栈引用指令 | 991 | 3752 | 4078 |
| Clang `NumSpills` | 394 | 1450 | 1584 |
| Clang `NumFoldedSpills` | 8 | 333 | 357 |
| Clang `NumReloads` | 339 | 781 | 1066 |
| Clang `NumFoldedReloads` | 240 | 1178 | 1055 |
| Clang 栈帧 / B | 1608 | 2072 | 2392 |

这里 spill/reload 是寄存器分配阶段生成的“存回栈/从栈读回”指令；
folded 表示这类访问折叠进另一条指令。四项合计 981→3742/4062，
与汇编栈引用数量接近，因而这次不再只是“栈访问也可能是局部数组”的
线索：确实存在**编译器生成的溢出/重载大幅增加**。仍不能把该静态
数量当动态内存事务，也不把 Clang 的内部 cost 当作真实周期。

Clang 优化报告中的 SLP（把多条相似标量运算组合为向量运算）选择也
改变了，不能仅用“成功向量化次数”或拒绝 remark 数量推断速度。
原先 SIMD 搬运并非全是浪费；这种源码重排削弱了一些批量计算形态，
寄存器分配结果反而更差。报告伴随的非分配调试元数据会重编号符号，
已核验三版分配区段字节及解析后的重定位 offset/type/目标/addend
与正式实测对象一致；报告没有替换实测模型。编译后信息**仅用于归因**，
没有反馈到优化选择规则。

#### 两窗口普通 walltime 与独立固定步验证

每版两个窗口、各 4 对 AB/BA，即每版 8 对 C100000。下表统一计算
`median(100 × (candidate_i / baseline_i − 1))`，正数表示变慢；不是
两个独立中位数相除，也不把诊断版 walltime 混入正式统计。

| 普通版配对指标 | 逐消费者 | 8 项分组 |
| --- | ---: | ---: |
| 窗口 1 walltime | +0.312% | +0.844% |
| 窗口 2 walltime | −0.001% | +0.657% |
| 合并 8 对 walltime | +0.279% | +0.719% |
| walltime 配对变化的均值（辅助口径） | +0.001% | +0.791% |
| candidate 更快的对数 | 3/8 | 2/8 |
| Host | +0.296% | +0.730% |
| 全局 eval | +0.174% | +1.229% |
| 各 part eval 之和 | −0.491% | +0.517% |

逐消费者版本两组 walltime 算术均值均为 **16.0875 s**，应理解为
“基本持平、没有稳定收益”，不把 +0.279% 的配对中位数夸大成明确的
整体退化。8 项分组两个窗口均偏慢。普通结果中 p3/p18 的整体 eval
均值有时下降，但没有变成更低的全局 eval；例如逐消费者的 p3/p18
分别 −0.972%/−0.768%，p10 则 +0.560%。分组版 p10 为 +2.267%。
不能只选择改善的分区来保留一个全图无收益方案。

固定步 PMU 继续采用 §7.46 四次旧运行生成的独立标签，p10/p18 的
两沿 anchor 各 175/260 个，非本轮候选挑选的“恰好最快/最慢”步。
每个候选的 core/pipeline 模式各 4 对 AB/BA。只替换两份已验证的
线程 wrapper 对象，7452 个模型/其余对象保持其对应普通候选的字节；
counter 的 enabled=running，所有窗口一致。两沿合计的结果如下：

| 配对固定步指标 | 逐消费者 p10 | 逐消费者 p18 | 8 项分组 p10 | 8 项分组 p18 |
| --- | ---: | ---: | ---: | ---: |
| eval（core） | +1.351% | +2.188% | +0.797% | +0.437% |
| eval（pipeline 独立窗口） | +0.915% | +2.077% | +0.990% | +0.343% |
| 指令数 | +0.922% | +0.130% | +0.786% | +0.282% |
| 周期数（core） | +1.267% | +1.798% | +0.708% | +0.259% |
| 前端未供给槽（pipeline） | +1.245% | +2.451% | −0.272% | −1.063% |
| 后端未供给槽（pipeline） | −1.413% | +13.187% | +19.566% | +37.582% |

分组版略减前端未供给槽，却增加后端槽和指令数，依然没有减少 eval；
后端槽的相对增幅不能解读成同等 walltime 损失。频率变化不超过约
0.22%，不是该轮的主要证据。两沿诊断、普通全步均值、条件瓶颈均值
属于不同口径，不能互相替代。

因重链接会改变函数地址，统一 64 B 对齐并不代表所有地址相同；未改
对象所在 part 的时间也会变化。因此不能把所有 p18 或其他 part 的
涨跌都排他归为本分区的重排，更不能将调试 wrapper 的耗时当正式收益。
本轮足以证明该候选未解决关键路径，并以 p10/b78 的等机器码编译报告
确认真实 spill 反作用，但没有分离所有全图布局/执行相位的伴随影响。

#### 本轮决定与复现边界

**两种候选都不并入当前有效线，不修改生产默认，保留原有 64 B 对齐。**
否定的是“仅凭窄值的源码存活距离缩短即可判断重排有益”的启发式，
不是否定降低机器级寄存器压力本身。下一步应保留有益批量计算形式，
从通用的窄字段拼装/拆分表示中减少真实冗余运算，而非继续盲调声明
分组大小；规则仍不能依赖 part、模块、信号名称或编译后热点反馈。

总核验已通过：**32 次普通 C100000、32 次诊断 C100000、16 次 C100**，
所有正式运行均开启并通过 Difftest，PC/退休指令/guest cycles/step
签名一致，100736 行 PMU 数据计账完整。输入 ELF/archive/image/NEMU
身份、全图规则覆盖和对齐检查通过；全部有效样本保留，不过滤偏慢值。
没有改变 RTL、Verilator、旧验证线的冻结产物，未引入新的默认选项。

[分组版覆盖与构建](../../build/repcut_grhsim_20260925/active_dispatch_20261003/narrow_local_use_order_20261004/tiled8/build.json)、
[分组版普通结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/narrow_local_use_order_20261004/tiled8/results.json)、
[逐消费者固定步 PMU](../../build/repcut_grhsim_20260925/active_dispatch_20261003/narrow_local_use_order_20261004/diagnostics/results.json)、
[分组版固定步 PMU](../../build/repcut_grhsim_20260925/active_dispatch_20261003/narrow_local_use_order_20261004/tiled8/diagnostics/results.json)、
[等机器码编译报告与寄存器分配](../../build/repcut_grhsim_20260925/active_dispatch_20261003/narrow_local_use_order_20261004/compiler_remarks/results.json)、
[总核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/narrow_local_use_order_20261004/verification.json)。

### 7.48 标量拼接的按需归约（2026-10-04）

承接 §7.47，不再重排窄局部声明；本轮直接消除“先拼装一个整数，随后
只检查这些位是否全为 1 / 是否有 1”的中间表示。基线仍为
`emitter_shift_bit_20261004/candidate/emu`（SHA256 前缀 `613e4b83ec3d`），
**没有叠加上一节未保留的声明重排**。当前是生成 C++ 的通用受控原型，
不是按热点 part/信号挑选的修改，也尚未修改生产 emitter 或默认值。

#### 规则、语义与首个检查点

只处理已显式声明的 u8/u16/u32/u64 局部值，其定义是完全覆盖有效位、
互不重叠的常量移位字段拼接，且所有消费者均为同一族的 AND/OR/XOR
归约或其取反。普通数值消费者、不同归约混用、位宽不符、缺口/重叠、
动态移位、未知或有副作用调用均拒绝。字段仍在**原定义位置**各求值一次，
改存最终 Boolean；不延迟到消费者、不跨状态写入、不改变声明顺序。
用 eager 的 Boolean 位运算，保留所有原字段求值，不新增短路控制流。

例如 `packed = (a&1)<<3 | (b&1)<<2 | (c&1)<<1 | (d&1)`，若所有用途
只要求 `reduce_and(packed,4)`，原位置直接存 `a[0] & b[0] & c[0] & d[0]`
即可；多位字段则先求字段本身的归约。规则按结构与完整使用集选择，
没有模块名、part 编号、RTL 变量名或编译后反馈门槛。

36 种拼接/归约组合 × 12000 组输入，在 O0/O3、ASan/UBSan 下通过；
专项包含定义后修改输入以检查快照、多消费者及互补归约、1/64 位边界
和拒绝模式。全图扫描 6859 个 compute 文件，覆盖 **28 个 part、393 个
文件、2460 个局部值、25690 个字段**；1326 个 AND、1134 个 OR，实际
workload 没有命中 XOR（专项已覆盖）。其中 25685 个字段为单 bit。

重编译受影响基线对象的分配区段与重定位 payload 匹配冻结 archive；
候选实际改变 385 个 member，其余 7069 个字节不变。受影响对象 text
4604710→4463456 B（−3.07%），静态指令 962966→932266；全部 6859 个
compute 入口保持 64 B 对齐。但 p10/b78 的向量指令 5350→710、栈引用
991→4267，仍提示有益批量计算可能被削弱，不能据总代码变小直接保留。

首窗口 4 对普通 C100000 AB/BA 全部通过 Difftest；walltime 配对中位
−0.594%，Host −0.621%，全局 eval −0.736%。这是初步结果，尚不作为
稳定收益结论；后续窗口及独立固定 step PMU 会在本节追加。沿用 node030
CPU96–127、NUMA1、N=K=32、Host105、all-spin、Clang23/O3、进程级
ASLR off；普通计时与诊断分开，保留全部有效样本，不按快慢筛选。

[规则与专项测试](../../build/repcut_grhsim_20260925/active_dispatch_20261003/scalar_concat_reduce.py)、
[全图覆盖](../../build/repcut_grhsim_20260925/active_dispatch_20261003/scalar_concat_reduce_20261004/prepare.json)、
[构建及身份](../../build/repcut_grhsim_20260925/active_dispatch_20261003/scalar_concat_reduce_20261004/build.json)、
[静态统计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/scalar_concat_reduce_20261004/static.json)、
[首窗口普通计时](../../build/repcut_grhsim_20260925/active_dispatch_20261003/scalar_concat_reduce_20261004/ordinary_1/summary.json)。

#### 固定瓶颈步与 p10 的编译器反作用

沿用 §7.46 的独立标签，p10/p18 各 175/260 组上升沿 anchor＋随后
下降沿。core/pipeline 分别 4 对 AB/BA；每次采样 3148 个 step，counter
enabled=running。只替换两份既有 PMU wrapper，7452 个其余 member
与对应普通版一致；这 16 次 C100000 的耗时不进入普通 walltime 统计。

| 两沿合计的配对中位变化 | p10 | p18 |
| --- | ---: | ---: |
| eval，core 窗口 | +0.218% | −0.387% |
| eval，pipeline 独立窗口 | +0.216% | +0.577% |
| 动态指令数（两种窗口一致） | +0.582% | −0.788% |
| 周期数，core 窗口 | −0.247% | −0.351% |
| 周期数，pipeline 窗口 | +0.451% | +0.634% |
| 前端未供给槽，pipeline | −0.583% | +1.039% |
| 后端未供给槽，pipeline | +17.509% | +13.079% |

p10 的关键标签两沿略慢；p18 虽少执行指令，但两个独立窗口的 eval
方向不一致，不能声称这组瓶颈 step 已有稳定提升。pipeline 的后端槽
占总槽比例约 p10 4.4%→5.1%、p18 2.5%→2.9%；相对增幅不能当成
同等 walltime 损失，也不能单凭这些计数排他认定所有差异的根因。

p10/b78 再次做了**与实测对象分配区段和解析后重定位一致**的 Clang
编译报告检查，确认不是只凭静态栈引用猜测：

| p10/b78 静态机器码/寄存器分配 | 冻结基线 | 拼接按需归约 |
| --- | ---: | ---: |
| 函数 text / B | 43394 | 58963 |
| 指令数 | 8242 | 9897 |
| 向量指令 | 5350 | 710 |
| SIMD 重排指令 | 1671 | 277 |
| 栈引用指令 | 991 | 4267 |
| `NumSpills` | 394 | 1709 |
| `NumFoldedSpills` | 8 | 322 |
| `NumReloads` | 339 | 961 |
| `NumFoldedReloads` | 240 | 1265 |
| 上述四项合计 | 981 | 4257 |
| 栈帧 / B | 1608 | 3736 |

该处删掉拼接的同时，SLP（把相似标量计算组合成向量）的选择改变，
真实编译器 spill/reload 大增。报告中的成功向量化 remark 反而更多，
再次说明 remark 次数不等于向量覆盖或运行收益。这里仍是静态生成量，
不是每 step 动态栈事务；不能把 b78 单函数的变化等同整个 p10 的代价。
这些编译结果只用于解释，**没有回馈为 part/信号筛选或机器码门槛**。

普通全步平均、独立固定瓶颈标签、最大分区平均与全局 eval 是不同统计
口径；比如前两窗口普通 p18 eval 平均下降约 2%，并不推翻上述固定
标签“尚无稳定收益”的结果。完整重链接仍改变函数地址及执行相位，
64 B 对齐不代表地址完全不变，不能把未改对象的时间变化排他归为规则。

[固定步 PMU](../../build/repcut_grhsim_20260925/active_dispatch_20261003/scalar_concat_reduce_20261004/diagnostics/results.json)、
[等机器码编译报告及寄存器分配](../../build/repcut_grhsim_20260925/active_dispatch_20261003/scalar_concat_reduce_20261004/compiler_remarks/results.json)。

#### 四窗口完整结果与保留决定

普通版已完成 **4 个窗口 × 4 对 AB/BA＝16 对 C100000**，共 32 次正式
运行。每个窗口 walltime 配对中位变化分别为 **−0.594%、−0.752%、
−0.656%、−0.532%**。保留全部样本，包括候选慢的一对及 walltime 相同
的两对；没有依据空闲率或快慢剔除。最终统计如下：

| 普通版指标 | baseline 算术均值 | candidate 算术均值 | 配对变化中位 |
| --- | ---: | ---: | ---: |
| walltime / s | 15.98625 | 15.89500 | −0.752% |
| Host / s | 15.95231 | 15.86144 | −0.747% |
| 全局 eval / µs | 50.75281 | 50.39269 | −0.639% |
| 全局 update / µs | 23.79038 | 23.78544 | −0.065% |
| 各 part eval 平均之和 / µs | 636.52013 | 634.04244 | −0.446% |
| p3 全步 eval 平均 / µs | 44.22463 | 43.40288 | −1.830% |
| p10 全步 eval 平均 / µs | 30.42256 | 30.82800 | +1.240% |
| p18 全步 eval 平均 / µs | 31.18213 | 30.58313 | −1.961% |

配对变化统一为 `median(100 × (candidate_i / baseline_i − 1))`，不是
表中两组算术均值相除。walltime 配对变化的**均值为 −0.570%**，实际
组均值相差 **91.25 ms**；“约 0.6% 小幅改善”是更保守的整体概括，
不把配对中位数与均值混用。16 对中候选 13 胜、2 平、1 负；Host 则
14 胜、2 负。AB/BA 各 8 对，walltime 配对中位分别 −0.533%/−0.782%，
两种执行先后均偏向候选。

按窗口内成对重采样 20000 次、固定随机种子，walltime 配对中位变化的
描述性 95% percentile 区间为 [−0.872%, −0.313%]。这仅反映当前二进制、
窗口及成对样本的重复性，不能据此保证另一种编译、workload 或机器也
有同等收益；本轮没有第二个 workload，不作跨 workload 泛化声明。

全图规则对不同计算形态确实有不同反作用。下表只统计**受影响对象**，
不是整个 part 的静态规模，更不是动态执行次数：

| 受影响对象静态汇总 | p3（42 个） | p10（14 个） | p18（11 个） |
| --- | ---: | ---: | ---: |
| text | −3.475% | +7.359% | −9.732% |
| 指令数 | −3.404% | +3.708% | −8.483% |
| 栈引用指令 | −5.483% | +125.104% | −40.459% |
| 向量指令 | −3.664% | −62.877% | +17.842% |

p3/p18 的普通全步平均在 16 对中均更低，p10 则多数偏慢，与这些编译
取舍相符；但不能据此称为排他因果证明。完全没有改对象的 p29 仍有
约 −0.424% 的全步 eval 配对变化，提醒重链接布局、整体执行相位和
缓存交互仍在影响分区计时。现有 64 B 对齐及 ASLR off 并未隔离这些。

**本轮保留该全图候选用于后续对照，收益是整体 walltime 的小幅下降，
不是已解决 p10/p18 的固定瓶颈步。** 不因 p10 变慢就人工撤销该 part，
不以编译后 spill 数建立选择名单。原冻结基线不覆盖，RTL、Verilator、
生产 emitter 和默认选项均未改变。当前仍是生成源码原型，尚不能声称
仅通过正式生成选项就能复现；迁入 IR 及 fresh 生成对照是独立后续工作。

下一步应围绕**保留批量向量计算的归约表示**处理这项明确的 p10 反作用，
而非继续调声明顺序、对齐尺寸或以少几个移位为充分收益判据。是否采用
后续形式，仍由全图语义覆盖、完整 Difftest 和普通 AB/BA walltime 判断。

总核验通过：**32 次普通＋16 次诊断 C100000、12 次 C100、50368 行 PMU**。
全部 C100000 开启并通过 Difftest，PC/退休指令/guest cycles/step 一致；
ELF/archive/image/NEMU 身份、源规则复现、385 个改变/7069 个未变 member、
6859 个 compute 的 64 B 对齐均验证通过。候选 ELF SHA256 为
`47c82e8555ab24beae0bdd5d3fd23f042712c3272c55abf72b7dd7b931e2cc40`，
位于 `scalar_concat_reduce_20261004/candidate/emu`。

[普通 16 对与全部分区统计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/scalar_concat_reduce_20261004/results.json)、
[顺序/重采样/静态汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/scalar_concat_reduce_20261004/assessment.json)、
[诊断与复核脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/scalar_concat_diagnostics.py)、
[总核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/scalar_concat_reduce_20261004/verification.json)。

### 7.49 按归约扇入选择整数聚合并迁入正式 emitter（2026-10-05）

承接 §7.48，先把“直接保存最终 Boolean”改成更适合 Clang 保留批量代码的
表示：仍只匹配完整、静态、标量 concat，且所有**存活消费者**必须属于同一
归约族。AND/NAND 将每个字段的坏位（`~field & mask`）做整数 OR，最后得到
全零/全一的原 concat 宽度；OR/NOR 将字段做整数 OR，得到 0/1。XOR/XNOR、
混合归约、普通数值消费者、状态/事件/需变化传播的值都 fail closed。OR 另加
结构性扇入门槛：少于 16 个字段保持原路径，避免短链为聚合引入额外转换；该
数字是表示成本的保护阈值，不是 part、模块、信号或编译后热点名单。字段按
原顺序、原位置各求值一次，64 B 函数对齐不变。

#### 阈值候选的完整 workload 结果

`scalar_concat_reduce_threshold_20261004` 通过 36 组语义专项（每组 12000
输入，O0/O3、ASan/UBSan）、全图 2460 组/393 文件/28 part/25690 字段覆盖，
以及 393 个受影响对象的构建与 archive/ELF 身份检查；6859 个 compute 入口
保持 64 B 对齐。16 对普通 C100000 AB/BA 全部通过 Difftest，14 胜、2 负：

| 指标 | baseline 均值 | threshold 均值 | 配对变化中位 | 配对变化均值 |
| --- | ---: | ---: | ---: | ---: |
| walltime / s | 16.655000 | 16.531875 | **−0.596%** | **−0.736%** |
| Host / s | 16.620313 | 16.496938 | −0.628% | −0.739% |
| 全局 eval / µs | 52.102813 | 51.783250 | −0.762% | −0.608% |
| 各 part eval 和 / µs | 657.073688 | 653.975438 | −0.322% | −0.459% |

p3/p10/p18 的全步 eval 配对中位分别 −0.429%/−0.316%/−2.491%；这不是把
最大 ASC 或所有瓶颈都同比缩短的证明，而是先减少中间拼装表示的一个小幅全图
收益。四窗口中位分别 −0.893%/−0.406%/−1.293%/−0.596%，AB/BA 分别
−0.596%/−0.824%；完整结果保留全部样本，不按快慢筛选。固定标签 PMU 的
p10/p18 只作解释：p10 两沿 core/pipeline 分别约 +0.53%/+2.59%，p18 约
−0.54%/−0.42%，因此不能声称这条规则解决固定瓶颈步。

阈值敏感性只做静态检查：8、24、32 的全图覆盖和 p10/b78 编译报告均成功，
但没有为它们运行完整 walltime 线；16 是当前默认实验阈值，不能据静态尺寸
直接宣称最优或跨 workload 泛化。p10/b78 的等机器码分配报告中，阈值版
`NumSpills` 394→403、`NumReloads` 339→332、栈帧 1608→1656 B，未复现
§7.48 直接 Boolean 候选的严重 spill/向量化回退；这只是安全性检查，不作为
运行时筛选条件。

#### 正式 emitter 的 opt-in 迁移与语义 fixture

规则已迁入 `wolvrix/lib/emit/grhsim_cpp.cpp`，新增两个 emitter 属性：
`scalar_concat_reduction`（默认 `false`）和
`scalar_concat_reduction_min_fields`（默认 `16`，要求至少 2）。匹配器按
IR 结构扫描所有存活用户；activity-schedule 的 use-list 可能带有已擦除操作
的 tombstone，因此只忽略无效 OperationId，仍对每个存活用户执行同族检查。
这避免了 fixture 中“规则永远不触发”的假拒绝，同时不放宽混合活跃消费者的
安全边界。生产默认仍关闭，未改变原有 Verilator/GrhSIM 默认路径。

新 fixture 覆盖长 AND/NAND、长 OR/NOR、低扇入 OR 回退及默认/显式关闭一致性。
全量 CMake 目标 `emit-grhsim-cpp` 已编译通过；生成结果中默认与 `scalar_concat_reduction=0`
逐字一致，开启版出现整数坏位/任意置位聚合，12 组输入的 Clang harness 返回
0（真值等价）。这是 emitter 迁移的语义检查点，尚未用 fresh XiangShan
全量生成替换当前正式默认，也未把阈值候选自动打开。

[threshold 完整普通结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/scalar_concat_reduce_threshold_20261004/results.json)、
[threshold 顺序/重采样/静态汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/scalar_concat_reduce_threshold_20261004/assessment.json)、
[threshold 总核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/scalar_concat_reduce_threshold_20261004/verification.json)、
[规则与专项脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/scalar_concat_reduce.py)、
[emitter 语义 fixture 生成物](../../wolvrix/build/grhsim_concat_reduction/artifacts/emit/grhsim_cpp_scalar_concat_reduction/enabled/)。

#### 勘误与 fresh 验证准备（2026-10-05）

上文关于 use-list tombstone 的解释不成立，现予纠正：`Graph::getValue()`
返回拥有使用者缓存的 `Value` 对象，`Value::users()` 返回该缓存的 span。
C++20 中直接遍历 `graph.getValue(result).users()` 会使用已析构临时对象的
存储；不能把异常 OperationId 当成已删除消费者并跳过。现已用具名 `Value`
保活，遇无效用户一律拒绝优化；同时要求全部消费者在当前 compute scope
内且晚于定义，公开端口、状态/事件、普通数值用途及混合归约均不改变表示。

初版 emitter 与 threshold 源码原型也不完全等价：初版保留原宽度的 0/全一
整数，且短 OR 完全回退；已测原型则在原定义处保存 `bool`，AND 保存“存在
坏位”，OR 保存“存在置位”，短 OR 用逐字段比较后按位 OR（不短路）。本次
迁移修正为后一种表示，消费者按极性读取该快照，不在原宽度表达式表里注册
这个 bool、不把求值推迟到后面的消费者。生产默认仍关闭。

上文“393 个受影响对象”应区分为 393 个重新编译源文件与实际发生变化的
385 个 archive 成员；其余 7069 个成员未变。原型的 16 对收益不直接归给
修订 emitter。新实验从同一份 partitioned IR 分别关闭/开启规则完整生成
32 个 part，先检查关闭输出与上一轮 fresh 输出的一致性，再合入原验证线
中被冻结的无关改动，重新编译、Difftest 和普通 C100000 AB/BA。所有选择仍
只由 IR 结构决定，没有 part/信号名单或编译后反馈筛选。

#### Fresh 全图与构建核验（2026-10-05）

补充保守边界：已有 emitter 会直接内联的低成本 concat 不新增快照；仅改变
原先需要显式局部临时值的表示，不人为延长其存活期。新增 focused CTest
覆盖 9 种字段形状 × 5 类用途（同族 AND、同族 OR、混合族、数值输出、XOR），
各 12000 组输入；默认/关闭/开启及阈值 2、64 五种设置均用 Clang 23 的
O0/O3、ASan/UBSan 验证。修订后的全量 `emit-grhsim-cpp` 回归通过（335.58 s），
focused 通过（102.46 s）；移位 demanded-bit、wordwise bool-pack 回归亦通过。

从相同 partitioned IR 完整生成开关两组后，**关闭组全部 7552 个源码/头文件
与上一轮 fresh 输出逐字相同**。开启组改变 416 个 compute 源文件、29 个 part，
将 2584 个显式标量 concat 改成布尔快照；原型的 2460 个匹配全部覆盖，额外
124 个由 IR 的完整类型/使用者信息证明可转换（例如包含模板化 wide slice 的
字段表达式，原正则原型不能识别）。328 个文件与独立源码原型逐字相同。
接口、头文件、commit 代码不变；调度/副作用骨架检查对归约结果内联进入 DPI
条件的情形，仅允许已证明的归约替换及该布尔值周围的冗余转换/括号归一化。

416 个文件均先重编译 baseline 并核对已冻结 archive 的代码、常量与重定位，
再编译 candidate；编译加核验 wall 24.00 s。实际变动 404 个 archive 成员，
7050 个成员逐字未变，受影响对象 text 合计 4905925→4744693 B（−3.29%）；
6859 个 compute 入口仍全部 64 B 对齐。相对先前 threshold 源码原型，只有
35 个成员的分配段/重定位有差异，因此后续必须以本次新二进制的 AB 为准，
不能沿用原型的 −0.596%。

基线仍为 `emitter_shift_bit_20261004/candidate/emu`（SHA256 `613e4b83…32c182`），
新候选为 `emitter_concat_reduction_20261005/candidate/emu`
（SHA256 `5709ab5d…554486`）。node030 CPU96–127、NUMA1、N=K32、all-spin、
Host105、Clang23/O3、进程级 ASLR 关闭；开始 4 窗口 × 4 对 C100000 AB/BA，
保留所有功能正确的样本，不设置额外空闲率门槛。

#### Fresh emitter 的 16 对结果与判断（2026-10-05）

四窗口全部完成，32 次 C100000 均开启 Difftest 并通过同一功能签名：
PC `0x80000c0c`、240349 instructions、99996 cycles、100001 guest cycles、
200102 steps；另有 8 次 C100 初始化检查。ELF、输入镜像、NEMU，以及生成所用
IR/动态库/binding 身份复核均通过。未剔除任何成功样本，walltime 共 13 胜、
1 平、2 负。

下表的“变化中位”是先对每对计算 `100 × (candidate_i / baseline_i − 1)`，
再取 16 个比例的中位数；**不是**用表内两列组均值相除，也不是与 §7.49 前半段
不同时间窗口的绝对耗时相除。

| 指标 | baseline 均值 | fresh emitter 均值 | 配对变化中位 | 配对变化均值 |
| --- | ---: | ---: | ---: | ---: |
| walltime / s | 16.071250 | 15.996250 | **−0.437%** | −0.465% |
| Host / s | 16.035688 | 15.963625 | −0.437% | −0.448% |
| 全局 eval / µs | 51.087750 | 50.958938 | −0.233% | −0.252% |
| 全局 update / µs | 23.944125 | 23.740188 | −1.135% | −0.846% |
| 各 part eval 和 / µs | 637.464000 | 632.926625 | −0.643% | −0.712% |

四窗口 walltime 配对中位为 −0.591% / −0.344% / −0.713% / −0.093%；
AB 与 BA 各 8 对，分别 −0.312% / −0.652%。固定种子、窗口内按配对重采样
20000 次的描述性 95% 区间为 [−0.652%, −0.312%]；该区间仅描述本次二进制
与采样窗口，不是换 workload、编译器或链接布局后的收益保证。第四窗口接近
零，不能表述为“每次都能加速 0.44%”。

| part | baseline 全步平均 eval / µs | candidate 全步平均 eval / µs | 配对变化中位 |
| --- | ---: | ---: | ---: |
| p3 | 43.776313 | 43.808313 | +0.042% |
| p10 | 30.270125 | 30.298125 | −0.046% |
| p18 | 31.394000 | 30.713813 | **−2.290%** |
| p29 | 15.966000 | 15.935500 | −0.270% |

这些是**全步平均**，不是“成为瓶颈时”的条件平均。p18 的全步 eval 在 16 对中
全部更短，各 part eval 总和亦 16 对全部下降；但 p3/p10 基本不动，全局 eval
仅小幅改善，不能据此宣称主要关键路径已经解决。update 阶段为原框架的分区间
拷贝，通信接口、拷贝逻辑及对应 archive 成员未改；其计时改善不能归因于通信量
减少。执行前状态、缓存/地址布局或等待关系等间接机制仍待固定步诊断，不能只凭
本表给出某一个机制的确定归因。

阶段判断：**正式 emitter 已正确复现并扩展通用结构规则，本次得到约 0.44%
的 walltime 小收益；保留为 opt-in，不扩大为解决瓶颈的主要方案。**
`scalar_concat_reduction` 仍默认关闭，阈值默认 16；环境变量为
`WOLVRIX_GRHSIM_SCALAR_CONCAT_REDUCTION` 与
`WOLVRIX_GRHSIM_SCALAR_CONCAT_REDUCTION_MIN_FIELDS`。64 B 对齐保持不变。
下一步更有价值的是固定同一批瓶颈 step，复查 p3/p10 的残余计算路径，并区分
此次 update 的间接收益；不继续只靠扩大 concat 覆盖率、布局试探或编译后反馈
挑选优化对象。目前仍只有 XiangShan 的性能验证，结构与语义检查不等于第二个
workload 的泛化收益。

[fresh 生成、结构核验与运行脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_concat_reduction.py)、
[全图覆盖核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_concat_reduction_20261005/audit.json)、
[构建与机器码身份核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_concat_reduction_20261005/build.json)、
[16 对及全部分区数据](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_concat_reduction_20261005/results.json)、
[顺序与重采样汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_concat_reduction_20261005/assessment.json)、
[最终核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_concat_reduction_20261005/verification.json)、
[全量回归](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_concat_reduction_20261005/full_final.log)、
[语义专项回归](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_concat_reduction_20261005/focused_final.log)。

### 7.50 Fresh emitter 固定瓶颈步与代码布局归因（2026-10-05）

为解释 §7.49 fresh 版本中 p3/p10 全步平均几乎不变、但总 walltime 仍有小幅下降，
本节在同一 GrhSIM 框架内只替换模型 archive：baseline 为
`emitter_shift_bit_20261004/candidate`，candidate 为
`emitter_concat_reduction_20261005/candidate`。两侧均使用 Clang 23/O3、N=K=32、
CPU96--127、NUMA1、all-spin、Host105；每次启动命令都带
`setarch x86_64 -R`，因此本实验的 ASLR 已在进程级关闭，不是地址随机化造成的差异。

瓶颈标签来自此前独立的四次 candidate 运行（没有用本次 PMU 结果挑选 step）：
p3 标签 1001 个 step，p10 标签 355 个 step；4 对 AB/BA 采样后分别得到 4004
和 1420 个固定标签样本。探针只在这些标签对应的 p3/p10 eval 周围读取 cycles、
instructions、pipeline/cache 计数，Difftest 全部通过。

#### 固定瓶颈步的机器特征

以下均为 candidate 相对 baseline 的逐样本百分比，先按每对 step 配对，再汇总中位数；
`instructions` 下降说明归约确实减少了执行工作，但 cycles/eval 未必同步下降。

| 固定标签 | eval 时长 | cycles | instructions | pipeline/cache 迹象 |
| --- | ---: | ---: | ---: | --- |
| p3（selected） | +1.600% | +1.478% | **−0.198%** | frontend-slots +4.528%；ic-misses +7.208% |
| p10（selected） | +0.729% | +0.716% | **−0.045%** | backend-slots +8.743%；ic-misses −0.848% |

均值方向一致：p3 的 eval/cycles/instructions 为 +1.428%/+1.212%/−0.199%，
p10 为 +0.820%/+0.468%/−0.045%。p3 更符合“指令变少但取指/前端供给恶化”的
形态；p10 的 frontend 基本不变、backend-slots 上升，说明它还混有执行端依赖/资源
占用变化。pipeline raw event 只作为方向性证据，不能把 slot 数直接当作时间比例；
低计数的 branch-misses 也不作归因依据。

#### 布局控制实验

fresh candidate 中 404 个 archive 成员发生变化，compute `.text` 总量从
4,905,925 B 降到 4,744,693 B（−161,232 B）；p3/p10 compute 函数体积分别
变化 −19,528 B/−818 B。尽管每个 compute entry 仍保持 64 B 对齐，链接后的
入口地址相对旧 binary 的中位位移仍为 p3 −27,264 B、p10 −60,480 B；64 B
对齐只能保持低 6 位，不能保持 I-cache/BTB/cache-set 所依赖的更高地址位。

为了隔离这一变量，另建了一个**诊断控制**：对 320 个缩短的 `.text` 段在尾部
补回共 172,365 B NOP，不改变新 emitter 的有效指令；变长对象不强行缩短。控制版
的 p3/p10 入口中位位移变为 +1,984 B/+9,280 B。独立 4 对 core PMU 的固定标签
结果为：

| 固定标签 | fresh eval / cycles 中位 | 补 NOP 后 eval / cycles 中位 | instructions |
| --- | ---: | ---: | ---: |
| p3 | +1.600% / +1.478% | +1.112% / +1.125% | 两版均 −0.198% |
| p10 | +0.729% / +0.716% | **−0.178% / −0.255%** | 两版均 −0.045% |

控制版不是生产候选（它只是证明布局因果的 post-link 试验），且 p3 的 ic-miss
计数仍约 +7%，所以结论不是“单一 L1I miss 数量解释一切”。更准确的结论是：
代码缩短改变了大段 hot code 的绝对位置，进而同时影响 cache-set、取指队列/预取、
分支目标布局等微结构状态；补回 footprint 后性能退化显著减轻，足以证明代码布局
是主要因素之一，而不是 ASLR 或 concat 计算本身。

因此当前归因闭合为：**scalar-concat reduction 减少了少量真实指令，但全图 text
收缩和后续代码搬移抵消了 p3/p10 的关键步收益；§7.49 的 walltime 小收益主要来自
其他分区/阶段，不能宣称已解决最大瓶颈。** 后续若继续，应做不依赖手选 part/信号、
不使用编译后反馈的通用 backend layout 方案（例如保持 hot compute 区域的稳定布局、
按结构元数据做统一的 section/cache-set 对齐），并以全 32 part 的 Host walltime 裁决；
NOP 补齐控制本身不晋升默认，也不改变 `scalar_concat_reduction` 仍默认关闭的决定。

[固定瓶颈 PMU 脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fresh_concat_bottleneck_diagnostics.py)、
[布局控制脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/preserve_concat_layout.py)、
[统计脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/report_concat_bottleneck.py)、
[fresh PMU/布局汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_concat_bottleneck_20261005/bottleneck_report.json)、
[fresh core 运行](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_concat_bottleneck_20261005/runs/pmu/core/manifest.json)、
[fresh pipeline 运行](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_concat_bottleneck_20261005/runs/pmu/pipeline/manifest.json)、
[fresh cache 运行](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_concat_bottleneck_20261005/runs/pmu/cache/manifest.json)、
[布局控制构建](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_concat_layout_control_20261005/build.json)、
[布局控制 4 对 core 运行](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_concat_layout_control_20261005_r2/runs/pmu/core/manifest.json)。

#### 通用布局策略与归约表示的后续探针（2026-10-05 增量）

继续做了三类**不依赖分区/信号名单**的 post-link 控制。第一类把每个 archive
member 的主 `.text` 独立向上取整到 2 KiB 或 512 B；第二类把每个 executable
section 独立取整到 512 B。2 KiB 版本使 GrhSIM ELF 达到 109,684,184 B（约比
普通 fresh binary 多 8 MB），4 对固定瓶颈 core 中 p3/p10 eval 仍分别为
约 +0.215%/+−0.310%，但普通 wall 已落在 18.14--19.31 s，故不接受；512 B
版本的 p3/p10 entry 位移仍约 −27.6 KiB/−61.4 KiB，没有解决地址高位漂移。
executable-section bucket 版本额外填充 2,357,351 B（GrhSIM ELF
103,855,576 B），entry 漂移同样未消失；它只作静态否定证据，不晋升默认。

第二类是因果控制：对 baseline/candidate 的每个匹配 executable section 都补到
两者的共同最大长度，使 6859 个 compute entry 地址逐一完全相同。该版本不是可部署
策略（需要知道两边的共同 max），但能把“地址布局”从实验变量中拿掉。4 对 core
固定标签相对 fresh baseline 的结果为 p3 eval/cycles −0.338%/+0.597%，p10
−1.107%/−0.400%；2 对 pipeline 中 p3 frontend/backend slots 约 −0.731%/−1.621%，
p10 backend 仍有约 +11.1% 的噪声；2 对 cache 中 p3 ic-miss 约 +1.36%、p10
约 +0.42%。因此 p10 的 fresh 退化有很大一部分来自跨函数布局，但 p3 即使 entry
完全相同仍残留计算内部/依赖代价。

第三类回到源表达式。把所有完整 OR/AND 归约都写成整数掩码聚合后，固定同一批
p3/p10 标签的 4 对 core 结果是：p3 eval 中位 −1.12%、cycles −1.76%、branch
misses −10.7%，p10 eval +1.62%、cycles +1.92%、branch misses +2.0%。pipeline
中 p3 backend slots 约 −13.0%，p10 backend slots 约 +9.9%；cache 中两者 ic
miss 均无明显下降（p3 +0.29%、p10 −0.62%）。这说明收益/退化主要是编译器形成的
指令依赖和执行端资源形态，不是简单的 I-cache miss 数量。

随后做了一个结构门槛对照：只对字段数小于 16 的 OR 使用整数掩码，长 OR 保持
原候选表达式。它在相同标签上反而使 p3/p10 eval 中位分别 +0.72%/+3.63%，说明
“按扇入数单调筛选”并不足够；同一 compute batch 内多组表达式是否能被编译器一起
向量化/调度，比单个 concat 的字段数更关键。当前结论收敛为：不再继续堆叠对齐粒度或
简单扇入阈值；应优先研究**保持 batch 内统一整数/向量表达形态，同时限制跨函数
布局漂移**的通用 emitter 规则。所有这些候选仍是诊断线，生产默认与 64 B 对齐
保持不变。

[通用 2 KiB 对齐构建](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_concat_uniform_text_align_20261005/build.json)、
[通用 512 B 对齐构建](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_concat_uniform_text_align_512_20261005/build.json)、
[executable-section 512 B bucket 构建](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_concat_exec_bucket_512_20261005/build.json)、
[共同 executable-section 控制构建](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_concat_exact_exec_control_20261005_r2/build.json)、
[共同布局 core 运行](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_concat_exact_exec_control_20261005_r2/runs/pmu/core/manifest.json)、
[共同布局 pipeline 运行](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_concat_exact_exec_control_20261005_r2/runs/pmu/pipeline/manifest.json)、
[共同布局 cache 运行](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_concat_exact_exec_control_20261005_r2/runs/pmu/cache/manifest.json)、
[整数聚合固定瓶颈脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/aggregate_concat_bottleneck_diagnostics.py)、
[整数聚合固定瓶颈构建](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_concat_aggregate_bottleneck_20261005/build.json)、
[整数聚合 core 运行](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_concat_aggregate_bottleneck_20261005/runs/pmu/core/manifest.json)、
[整数聚合 pipeline 运行](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_concat_aggregate_bottleneck_20261005/runs/pmu/pipeline/manifest.json)、
[整数聚合 cache 运行](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_concat_aggregate_bottleneck_20261005/runs/pmu/cache/manifest.json)、
[短 OR 门槛构建](../../build/repcut_grhsim_20260925/active_dispatch_20261003/scalar_concat_reduce_small_or_aggregate_20261005/build.json)、
[短 OR 门槛固定瓶颈运行](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_concat_small_or_aggregate_bottleneck_20261005/runs/pmu/core/manifest.json)。

#### 勘误：统计口径、候选身份与因果边界（2026-10-05）

本次逐项回查原始 TSV、构建 archive 与全部运行清单后，发现上述增量记录混用了
不同统计量，并对候选之间的变量控制作了过强解释。保留原记录供追溯，但相关结论
以本勘误及后面的单变量实验为准。

1. **采样范围与标签筛选不同。** PMU 实际在 `step > 128 && step % 127 <= 1`
   的所有 3148 个采样步读取 p3/p10，而不是只在各自标签步读取。分析时才使用此前
   独立运行得到的 p3 1001 步、p10 355 步。它们是固定的历史瓶颈标签，不保证
   在本轮每次运行中仍是实际最慢分区。
2. §7.50 前半的 +1.600%/+0.729% 等数值是**逐 step 百分比的中位数**，计算本身
   没有被本次推翻，但不能称作“瓶颈 eval 平均值的变化”。上段整数聚合的
   −1.12%/+1.62%、短 OR 的 +0.72%/+3.63% 则来自**整段运行的分区 eval 均值**；
   部分 PMU 数值还来自所有采样步或未完成时的前两对，不能冒充完整固定标签统计。
3. 旧整数聚合、旧混合表达式均是此前的 source prototype，不是 fresh emitter 的
   单变量派生。尤其 `scalar_concat_reduce_small_or_aggregate_20261005` 除了短 OR，
   还改变了 AND、长 OR 的表示；据它断言“短 OR 门槛失败”“batch 向量化被破坏”
   均不成立。后面的新实验才只改变 fresh 版本中的短 OR。
4. 共同 executable-section 长度控制已重新核验：**全部 6859 个 compute entry
   地址确实一致**。但函数内部基本块/指令位置没有因此一致，`.rodata` 虽起始地址
   相同，内容与长度仍不同（4,947,744→4,947,408 B）。因此不能说所有布局因素均
   被消除，也不能据 p3 的小幅剩余差异认定存在确定的“计算内部依赖退化”。这些
   控制支持“对代码布局敏感”，尚未定量分离布局、内部指令与运行波动的贡献。
5. 2 KiB 版本的 18.14–19.31 s 是**带探针诊断 binary 的 walltime**，不是普通
   binary 的同窗口 64 B/2 KiB 对照，不能据跨窗口绝对值断言其普通 walltime
   退化多少。512 B executable-section bucket 实际已完成 **2 对 core**，并非
   “只做静态核验”。两者都没有获得足以晋升生产默认的普通 walltime 证据。

统一后的固定标签口径为：每次运行先算同一集合 `S_p` 上的
`mean_p = sum(eval_ns[step] for step in S_p) / len(S_p)`，每对再算
`delta_r = 100 * (candidate_mean_p / baseline_mean_p - 1)`，最后汇总
`median(delta_r)`。旧逐 step 百分比口径另存于统计 JSON 的 `legacy_step_pct_*`，
不与这个统计量混用。按此口径重算全部已完成 core 对照如下：

| 实验线 | AB/BA 对数 | p3 固定标签平均 eval：配对变化中位 | p10 同指标 |
| --- | ---: | ---: | ---: |
| fresh concat / 旧 shift-bit | 4 | +1.479% | +0.765% |
| fresh，缩短段补尾 NOP / 对应旧线 | 4 | +0.585% | −0.170% |
| fresh / 旧线，共同 executable-section 长度 | 4 | −0.033% | −1.554% |
| fresh / 旧线，双方 2 KiB text 对齐 | 4 | +0.152% | −0.638% |
| fresh / 旧线，双方 512 B executable bucket | 2 | −1.877% | +1.045% |
| 旧整数聚合 prototype / 旧 shift-bit | 4 | −1.070% | +1.891% |
| 旧混合表达式 prototype / 旧 shift-bit | 4 | +0.662% | +2.373% |

每行只比较该行同窗口的两个 binary，**不能把不同实验窗口的绝对时间相减当作
某项改动的独立贡献**。所有行的两个后端均为 GrhSIM；目录中的
`pmu/verilator`、`pmu/grhsim` 是沿用的 runner 别名，不表示本表在比较 Verilator。
上述旧 prototype 的整体性能数据仍有效，但不足以独立归因某一种 OR/AND 写法。

[统一统计与复核脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/audit_concat_cohorts.py)、
[完整口径核验与各对原始均值](../../build/repcut_grhsim_20260925/active_dispatch_20261003/concat_cohort_audit_20261005.json)、
[512 B bucket 的两对实际运行](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_concat_exec_bucket_512_20261005/runs/pmu/core/manifest.json)。

#### Fresh 基线上只改短 OR 的单变量复测（2026-10-05）

本轮 baseline 是 §7.49 的 **fresh concat emitter 候选**，不是生产默认，也不是
旧 shift-bit：普通 ELF SHA256 为 `5709ab5d7745ca7ac987d9eb2277419b7685ec3e33b180549fe69156ed554486`。
candidate 为 `fresh_concat_short_integer_20261005/candidate/emu`，SHA256 为
`d2e8e51440b65b10851767feadf16b3f2d6f2c23f23c96a9a289b78157994df9`。
只在原快照位置把 eager（不短路）OR 的写法从
`const bool b = (x != 0) | (y != 0);` 改为
`const bool b = uint64_t(x) | uint64_t(y);`。实际规则要求各整数操作数为纯表达式，
保留取值时刻、求值次数及 eager 语义；不改 AND、长 OR、调度、持久化状态或
通信。匹配条件没有 part/信号名单，也没有运行后或编译后挑选。

在 fresh 已改写的全图 compute 源码中匹配 810 组、186 个文件，字段数均为 2–15。
O0/O3 的 ASan/UBSan 语义测试覆盖 9 种长度、12000 组输入及快照后输入变化，均通过。
186 个原始源文件重编译后先与冻结 archive 做有效段/重定位等价核验，再编译候选；
最终仅 **79 个对象改变，另 107 个重编译对象逐字节相同**。所编译对象的 `.text`
总量 2,046,830→2,067,438 B，增加 20,608 B；全部 6859 个 compute entry 仍为 64 B 对齐。

机器码检查提供了比源码直觉更直接的限制：

- p3 的 360 个 archive 对象中仅 sched_108/147/158 三个改变，其 compute 总字节
  减少 706 B。包含多组 6-field OR 的 sched_88 在两版中对象逐字节相同，`.text`
  都是 7362 B；因此不能声称这些短链因 bool 表示而失去向量化。
- p10 的 191 个 archive 对象全部相同，170 个 compute entry 地址也全部相同；
  sched_78 的 `.text` 两边都是 42442 B。此候选没有给 p10 引入新的直接计算优化。
- p3 的 entry 中位位移仍有 −320 B；源码/对象相同也不保证整机共享资源和运行
  状态相同。不能只凭时间变化反推某条源表达式的硬件原因。

node030 CPU96–127、NUMA1、Clang23/O3、N=K=32、Host105、all-spin、进程级
ASLR 关闭；两个普通窗口各 4 对 AB/BA，中间插入 4 对固定标签 core PMU。
**24 次 C100000 Difftest 及 6 次 C100 均通过**，运行前后输入身份一致；
PMU 每次 3148 行、enabled=running，无 multiplex。没有剔除成功样本。

| 普通 binary，8 对 AB/BA | baseline 各次均值 | candidate 各次均值 | 配对变化中位 |
| --- | ---: | ---: | ---: |
| walltime / s | 16.20125 | 16.26375 | **+0.370%** |
| Host / s | 16.16300 | 16.22750 | +0.374% |
| 全局 eval / µs per step | 51.85950 | 52.23325 | +0.755% |
| 全局 update / µs per step | 23.79875 | 23.80438 | −0.006% |
| p3 全步 eval / µs | 44.38788 | 44.76013 | +0.803% |
| p10 全步 eval / µs | 30.62250 | 30.52813 | −0.253% |

walltime 两个窗口的配对中位分别 +0.371%/+0.370%，合计 7/8 对更慢；全局 eval
8/8 对更慢。表中的绝对数值是各次运行均值，百分比是前述配对百分比的中位数，
不是直接用表中两个绝对数值相除。

| 固定历史标签，4 对 PMU | baseline eval 平均 / µs | candidate eval 平均 / µs | eval 配对变化中位 | cycles 配对变化中位 | instructions |
| --- | ---: | ---: | ---: | ---: | ---: |
| p3，1001 步/次 | 43.54969 | 44.15972 | **+1.614%** | +1.809% | 约 0% |
| p10，355 步/次 | 50.04815 | 49.97968 | −0.115% | −0.040% | 约 0% |

**本轮结论：不晋升“短 OR 全部整数化”。** 它没有减少所测瓶颈步的动态指令工作，
也没有普通 walltime 收益；多数源码改写被 Clang 归一到同样的机器码。动态计数
几乎不变不能单独证明那三个变化 batch 没有执行，更不能证明全部短 OR 规则在所有
workload 上无效。本轮只否定这个具体候选，撤回“已证实 bool 破坏 batch 向量化”的
归因。后续优先检查固定瓶颈步中实际执行且仍占较多周期的 batch，建立指令/访存
层面的差额后再选通用规则；不继续无目标扫描 OR 写法或对齐粒度。生产默认、
`scalar_concat_reduction` 默认关闭及现有 64 B 对齐均不变，Verilator 未改动。

[单变量构建、测试及运行脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/concat_short_integer_probe.py)、
[源代码匹配范围](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fresh_concat_short_integer_20261005/prepare.json)、
[构建与对象核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fresh_concat_short_integer_20261005/build.json)、
[第一窗口普通 AB/BA](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fresh_concat_short_integer_20261005/ordinary_1/manifest.json)、
[第二窗口普通 AB/BA](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fresh_concat_short_integer_20261005/ordinary_2/manifest.json)、
[固定标签 core PMU](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fresh_concat_short_integer_20261005/diagnostics/runs/pmu/core/manifest.json)、
[最终核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fresh_concat_short_integer_20261005/verification.json)。

### 7.51 固定瓶颈活跃批次复核与宽快照延迟物化（2026-10-05）

延续 §7.50 的最终结论，本轮先重新定位实际执行的 batch，再从真实热点中选择
通用规则；不继续扫描短 OR 写法或对齐粒度。所有实际测量仍使用 node030
CPU96–127、NUMA1、Host105、N=K=32、all-spin、Clang23/O3、进程级 ASLR 关闭，
保留全部成功样本，不以空闲率或运行速度筛选。

**实验身份需要区分两组。** 残余归因的 A/B 是真实 Verilator/O3 与 §7.49 的
fresh concat GrhSIM；后面的优化 A/B 则两边都是 GrhSIM。优化 baseline 的普通
ELF 为 `emitter_concat_reduction_20261005/candidate/emu`，SHA256
`5709ab5d7745ca7ac987d9eb2277419b7685ec3e33b180549fe69156ed554486`；它是探索线，
**不是仓库生产默认**，也没有叠加上一节未获益的短 OR 整数化。新候选位于
`late_pack_snapshots_20261005/candidate/emu`，SHA256
`b42045cf9cf9fb9f4a3fc2da163fe0caf61f330d1e4857bb8424f36ffc264ee6`。
两者均在 `build/repcut_grhsim_20260925/active_dispatch_20261003/` 下。

#### 固定步对照：p3 已更快，p10/p18 的两沿成本仍偏高

沿用独立历史运行得到的固定标签：p3 1001 步、p10 355 步、p18 538 步；不根据
本次哪个后端更慢重新挑选。PMU 每次读取 3148 个采样步，再筛选这些标签，完成
4 对 AB/BA。这里的“瓶颈步”是历史标签，不保证在当前每次运行中仍是最慢分区。
另取同一历史标签中的 anchor 及其紧随一步，两沿合计各有 517/175/260 对。
两沿集合与单步标签集合并不完全相同，不能把下表右半边简单解释为左半边乘二。

表中绝对时间是“每次运行先在固定集合求均值，再取各次均值的中位数”；百分比是
`median(100 * (G_run_mean / V_run_mean - 1))`，不是表中两个中位数直接相除。

| part | 固定标签 V / µs | 固定标签 G / µs | G/V 配对变化 | 两沿 V / µs | 两沿 G / µs | 两沿配对变化 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| p3 | 82.00 | 43.25 | −47.21% | 152.20 | 87.44 | −42.44% |
| p10 | 56.43 | 49.44 | −12.49% | 72.65 | 81.86 | +12.59% |
| p18 | 47.76 | 49.21 | +3.18% | 69.80 | 88.58 | +27.18% |

两沿 PMU 的关键差额：p10 动态指令约 +0.50%，分支 +75.71%，branch misses
+65.38%，IPC 从 2.156 降到 1.924；p18 指令反而 −6.96%，分支 +110.61%，
branch misses +113.29%，IPC 从 2.287 降到 1.679。有效频率差均不足 0.3%。
因此“指令很多”或“降频”不足以解释这两个分区的两沿差距，控制流/执行效率仍是
后续重点；仅凭这些计数不能把全部差额都归因于 branch miss。

按上述 anchor 的两沿窗口另做 cycles IP 采样，每个 part 各 4 对 A/B。
GrhSIM 的 p3/p10/p18 分别得到 652/208/335 个 IP 样本，其中 compute 占
85.28%/87.02%/83.58%，commit 占 5.98%/7.69%/12.84%，dispatch 占比均不足 2%。
这里 commit 指模型 `eval()` 内的状态提交，不是 Host 框架的 update 阶段。
采样量较小且可能存在 skid，不能把 IP 百分比当作精确 walltime 构成，或据此
认定某一条汇编就是全部 stall 的根因。

#### 活跃 batch：宽输出打包比短 OR 更值得检查，但热点较分散

只在固定标签步统计 p3/p10/p18 的 compute 调用：空调用只计数、不计时；活跃调用
在调用边界计时，并记录 active/all-on/活动位数。只重编译三个 eval 派发对象与
两个框架探针对象，compute archive 成员不变。2 次 C100000 的热点结果为：

| part | 活跃 compute 时间之和 / µs per selected step | 最大 batch 及时间 / µs | 最大项占活跃计算 | 前 10 项占比 |
| --- | ---: | --- | ---: | ---: |
| p3 | 40.979 | b46：1.512 | 3.69% | 16.94% |
| p10 | 45.246 | b15：3.141；b17：2.953 | 6.94%；6.53% | 30.40% |
| p18 | 45.205 | b18：1.301 | 2.88% | 13.53% |

这些是**带探针的活跃调用时间**，含计时扰动，不能与上表无 batch 探针的 eval
绝对值拼接，也不能直接推算普通 walltime。特别是 p3/b46 并没有占据大部分 p3
计算时间。上一节短 OR 真正改变的 p3/b108、b147、b158 合计只有约 **0.484%**
活跃 compute 时间；它们确实执行了，并非“动态指令不变就说明没有执行”。

p3/b46 主要由 4381 个寄存器读取和 20 个 concat 操作组成，包含 RepCut 跨分区
输出 bundle 的打包。p10/b15/b17 也包含大量寄存器读取与宽输出打包，但 b15
还混有输入切片，b17 中不同 supernode 还包含比较/DPI，不能将整个文件一概当作
纯打包块。p18/b18 同样是混合结构。

对照真实 Verilator 生成代码，part_3 的 `out_40` 在包装 SV 中连接
`out_bundle_to_p2`；`__024root__33.cpp` 约 22443 行起，对同一 release buffer
宽寄存器的各字直接做移位、OR 并写输出。GrhSIM 的对应输出也已是逐字拼接，但
部分宽寄存器先生成 `const auto snapshot = state_array;`，很久以后才逐字消费。
这提示应检查**临时数组副本的存活期**，不能据源码存在副本就直接断定编译后一定
产生了全部复制，更不能据局部代码推断整个后端孰优孰劣。

[残余归因脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/residual_batch_profile.py)、
[活跃调用探针](../../build/repcut_grhsim_20260925/active_dispatch_20261003/residual_batch_probe.hpp)、
[G/V 固定步 PMU](../../build/repcut_grhsim_20260925/active_dispatch_20261003/residual_batch_20261005/pmu_results.json)、
[活跃 batch 汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/residual_batch_20261005/batch_results.json)、
[IP 汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/residual_batch_20261005/ip_results.json)、
[归因运行核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/residual_batch_20261005/verification.json)。

#### 新候选：保留值复制，延迟到第一次逐字消费

§7.19 的 `wide_state_read_refs` 已验证过：将副本改成引用能够减少部分栈访问，
但当时 8 对普通 walltime 没有收益。本轮不原样重跑，而是在更窄的纯打包块中
**保留原值复制表达式和类型，只移动声明位置**：

```cpp
// 原来：先复制许多宽数组，随后才开始打包。
const auto a = state_a;
const auto b = state_b;
// ...
const auto &pack_a = (a);  // 逐字消费 a
// ...
const auto &pack_b = (b);

// 候选：在第一次需要该数组时才复制；仍不是引用状态。
const auto a = state_a;
const auto &pack_a = (a);
// ...
const auto b = state_b;
const auto &pack_b = (b);
```

原型要求整个 supernode 只有 `kRegisterReadPort` 与 `kConcat`，源是不可变宽
状态数组，本地副本与首次使用处具有相同词法作用域，首次使用必须为逐字 concat
的操作数绑定；拒绝状态写入、DPI/未知调用等情况。每个副本只复制一次，不复制
计算、不改变后续消费者顺序。逐字拼接内部的消费顺序比 GRH 操作级的
`local_compute_use_order` 更细，因此不是简单重启该旧选项。

规则在全图扫描，没有 part、模块、信号名单，没有 profile 或编译反馈筛选。
共命中 **21 个分区、49 个 compute 文件、1140 个宽副本**，声明大小静态合计
30264 B（不是动态流量，也不是同时存活的栈空间）。p3/b46 命中 336 个副本，
p10/b15 命中 36 个；p10/b17 与整个 p18 没有命中。

这是 generated-C++ **source oracle**，尚未迁入正式 IR emitter。专项 O0/O3
ASan/UBSan 测试覆盖 12000 组输入、inactive、重复 eval 及副作用拒绝；全部通过。
49 份原始源码先重编译并与冻结 archive 核验有效段/重定位一致，再编译候选。
最终 48 个 archive 成员改变，其余成员保持不变；全部 6859 个 compute entry
仍为 64 B 对齐。所编译对象 `.text` 总量 1,981,711→1,932,619 B。

| 对象 | `.text` 字节 baseline→candidate | 含栈地址的静态指令 | 入口 `sub rsp` 分配 / B |
| --- | ---: | ---: | ---: |
| p3/b46 | 100151→78955 | 2674→34 | 9592→72 |
| p10/b15 | 142711→141839 | 138→7 | 376→0 |
| p6/b47 | 70710→69252 | 172→32 | 584→184 |

静态计数覆盖对象内指令，包含 helper，不是动态 spill 次数；入口分配不包含
push 等其他栈操作。与旧引用实验不同，本轮 p6/b47 的代码也缩短，没有重现当时
该函数变大的现象。但两轮 baseline 不同，不能将它们跨窗口相减作独立收益。

#### 普通 walltime 与固定步结果：小收益，不是瓶颈突破

普通 binary 完成两窗口各 4 对 AB/BA；中间插入 4 对 core PMU 及 2 对活跃
batch A/B。候选诊断使用与 baseline **同一份探针对象**，不重编译 compute
正文；batch 的每步调用次数/活动标志逐项一致。优化实验共 **28 次 C100000、
8 次 C100** 通过 Difftest/签名与身份核验；前面的残余归因另有 34 次 C100000、
9 次 C100，合计 62 次正式长运行及 17 次短运行。PMU enabled=running，IP
无 lost/throttle；没有把诊断 binary 的 walltime 混入普通结果。

以下绝对值为 8 次普通运行的算术均值，百分比仍为配对百分比的中位数，两种统计量
不同。两个窗口 walltime 配对中位分别 −0.495%/−0.526%。

| 普通 binary，8 对 | baseline | candidate | 配对变化中位 |
| --- | ---: | ---: | ---: |
| walltime / s | 16.17250 | 16.10875 | **−0.495%**，7/8 对更快 |
| Host / s | 16.13513 | 16.07425 | −0.480% |
| 全局 eval / µs per step | 51.68250 | 51.21138 | −0.914% |
| 全局 update / µs per step | 23.76950 | 23.83838 | +0.399% |
| p3 全步 eval / µs | 43.95888 | 44.16950 | +0.351% |
| p10 全步 eval / µs | 30.67000 | 30.30025 | −1.757% |
| p18 全步 eval / µs | 31.09825 | 31.08938 | −0.253% |

walltime 均值的比值为 −0.394%，配对中位 −0.495%；不要混用。p3 全步均值
并未改善，不能把全局 eval/walltime 的小收益都归因于 p3/b46。全局阶段受各步
关键路径影响，与“某分区全步均值的最大值”不是同一统计量。

| 固定历史标签，4 对 PMU | eval 配对变化 | cycles | instructions |
| --- | ---: | ---: | ---: |
| p3 | −0.140% | −0.264% | −0.535% |
| p10 | +0.211% | +0.070% | −0.075% |
| p18 | −0.881% | −0.812% | 约 0% |

p3/b46 的活跃调用 A/B 探针均值为 1.708→1.503 µs/selected step，但仅两对，
配对变化分别 −22.74%/+1.23%，不能称作稳定的“局部加速 12%”。p3 全部活跃
compute 时间之和配对中位约 −0.64%，与其覆盖有限相符。整个 p18 对象未改变，
但 compute entry 中位位移 −45248 B；其时间变化不能算成直接优化了 p18。
两边虽然均关闭 ASLR 且保留 64 B 对齐，代码缩短仍会改变链接布局。

**结论与保留范围：** 宽快照延迟到首次逐字消费具有明确的静态机制证据，当前
探索线上两窗口普通 walltime 得到约半个百分点的小收益，保留为待迁移验证的
通用候选；尚不能称为稳定的关键瓶颈突破，不晋升生产默认。本轮没有修改
Wolvrix 正式 emitter、Verilator 路径、all-spin 或 64 B 对齐。后续不应继续
只追求栈帧/代码体积下降：应优先围绕 p10/p18 两沿差额，检查实际活跃路径上的
分支及跨半周期重复工作，再用同集合 PMU 与普通 walltime 裁决。若迁移本候选，
必须在 IR 层证明状态不变、存储不别名和副作用边界，并做 fresh 生成/完整回归，
不能把本轮文本匹配脚本直接作为生产流程。

[通用原型与专项测试](../../build/repcut_grhsim_20260925/active_dispatch_20261003/late_pack_snapshots.py)、
[覆盖记录](../../build/repcut_grhsim_20260925/active_dispatch_20261003/late_pack_snapshots_20261005/prepare.json)、
[构建核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/late_pack_snapshots_20261005/build.json)、
[静态机器码统计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/late_pack_snapshots_20261005/static.json)、
[同探针对照脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/late_pack_diagnostics.py)、
[第一窗口普通运行](../../build/repcut_grhsim_20260925/active_dispatch_20261003/late_pack_snapshots_20261005/ordinary_1/manifest.json)、
[第二窗口普通运行](../../build/repcut_grhsim_20260925/active_dispatch_20261003/late_pack_snapshots_20261005/ordinary_2/manifest.json)、
[固定步 PMU](../../build/repcut_grhsim_20260925/active_dispatch_20261003/late_pack_snapshots_20261005/diagnostics/pmu_results.json)、
[活跃 batch 对照](../../build/repcut_grhsim_20260925/active_dispatch_20261003/late_pack_snapshots_20261005/diagnostics/batch_results.json)、
[最终统计脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/late_pack_results.py)、
[全部核验与配对原始均值](../../build/repcut_grhsim_20260925/active_dispatch_20261003/late_pack_snapshots_20261005/verification.json)。

### 7.52 两沿实际路径与共同布尔使能试验（2026-10-05）

本轮继续 §7.51 的 p10/p18 两沿归因，不开展编译后反馈或新的布局扫描。
测量仍为 node030 CPU96–127、NUMA1、Host105、N=K=32、all-spin、Clang23/O3、
进程级 ASLR off；保留 64 B compute entry 对齐与全部成功样本，不设空闲率 gate。
本节没有修改正式 emitter、生产默认、RTL 或 Verilator 路径。

**baseline 已前移，不能与上一节的 baseline 混用。** 本轮 GrhSIM baseline
是 §7.51 的 `late_pack_snapshots_20261005/candidate/emu`，SHA256
`b42045cf9cf9fb9f4a3fc2da163fe0caf61f330d1e4857bb8424f36ffc264ee6`，即已含
宽快照延迟物化的探索线，不是仓库生产默认。G/V 归因仍使用真实 Verilator/O3
最终去锁版；后面两项优化 A/B 则双方都是 GrhSIM，且两个候选各自直接对照上述
同一个冻结 baseline，第二项不是在第一项 ELF 上叠加。

#### 两沿差距仍主要在下降沿，不是频率差

沿用独立历史标签中的 p10 175 个、p18 260 个上升沿 anchor，以及各自紧随的
下降沿，不按本轮性能重新选步。core PMU 完成 4 对 AB/BA，每次读取 3148 个
采样步后再取固定集合。绝对值为各次运行的集合均值之中位数；百分比为各对
`100 * (G_run_mean / V_run_mean - 1)` 的中位数，不是两个绝对中位数相除。

| part / 集合 | V eval / µs | G eval / µs | eval 配对变化 | 动态指令变化 | 分支变化 |
| --- | ---: | ---: | ---: | ---: | ---: |
| p10 上升沿 | 56.846 | 49.334 | −13.23% | −24.08% | +40.11% |
| p10 紧接下降沿 | 16.794 | 32.942 | +96.79% | +76.35% | +311.09% |
| p10 两沿合计 | 73.641 | 82.228 | **+11.77%** | +0.45% | +75.71% |
| p18 上升沿 | 48.288 | 48.873 | +1.05% | −30.00% | +85.66% |
| p18 紧接下降沿 | 21.784 | 39.179 | +79.91% | +40.92% | +206.80% |
| p18 两沿合计 | 70.200 | 88.065 | **+25.55%** | −6.96% | +110.64% |

两沿合计 p10/p18 的 branch misses 分别 +70.04%/+118.18%，IPC 分别从
2.126→1.912、2.274→1.687；有效频率差 +0.10%/−0.16%。因此剩余差距不支持
以降频解释。下降沿确实执行了更多指令，但两沿总指令接近或更少，不能将整体
差额全部解释成额外算术；控制流、数据依赖和执行效率仍需区分。

对同一集合另做每 part 4 对 branch-misses IP 采样。G 的 p10 共 88 个样本，
compute/模型内部 commit/dispatch/其他为 49/34/1/4；p18 共 216 个，为
146/62/7/1。下降沿 p10 的 21 个中 20 个落在 compute，p18 的 61 个中 58 个
落在 compute，均没有 commit 样本；上升沿则有较多 commit 样本。V 的 p10/p18
共 60/104 个样本，均落在 Verilated 模型函数。样本较稀疏且有 skid，不能用这些
比例代替时间占比、归咎某一条指令，或把模型 commit 与 Host update 混为一谈。

#### 实际 supernode 入口计数：排除大规模重复迭代猜测

这次不只观察 batch 的入口活动位，而是在 p10/p18 的 **3383 个 supernode**
实际 guard 内计数，并记录 eval 内第几轮执行；共重编译 425 个 compute 和
2 个 eval 对象，原始源码先与冻结 archive 核验，再添加两个框架探针对象。
2 次 C100000 的逐步、逐 supernode 调用/轮次记录完全相同。

| 固定集合 | eval 轮数分布 | 每步 supernode 调用数 | 同一 eval 内重复调用数 |
| --- | --- | ---: | ---: |
| p10 上升沿 | 175/175 为 2 轮 | 698.68 | 63.25 |
| p10 下降沿 | 123 次 2 轮，52 次 1 轮 | 638.07 | 0.70 |
| p18 上升沿 | 260/260 为 2 轮 | 1033.30 | 23.01 |
| p18 下降沿 | **260/260 为 1 轮** | 986.10 | **0** |

第二轮存在不等于全部逻辑重跑。p10 下降沿的重复量很小，p18 下降沿完全没有
重复迭代；这不是下降沿慢约 80%–97% 的主要解释。纯状态读取/输出 concat 的
supernode 也没有在同一 eval 内重复执行。某块在相邻两沿都执行，并不证明其
输入或结果相同，更不能据此直接删掉第二次计算。

同步的块内计时仅用于热点排序，含大量计时探针扰动，**不是自然 eval 时间**：
p10 的纯输出打包主要在上升沿（合计约 7.182 µs，下降沿仅 0.0006 µs）；下降沿
靠前的是 b78/SN669、b47/SN337，探针均值约 0.783/0.750 µs。SN669 含大量
状态读取和断言谓词，虽然 system task 受 posedge guard 控制，不能在未审清其他
消费者前把整块也套上该 guard。p18 下降沿前三项是 b210/SN1719、b179/SN1485、
b195/SN1635，约 0.495/0.470/0.443 µs，且每步各执行一次。

这些 p18 块含数百项状态读取和布尔物化：例如 `source & valid_state` 的结果
写入 bool slot，和旧值比较，再累计下游 reader 的活动标志。其中有 issue queue
唤醒统计的中间量和计数器路径。对照实际 V 的
`part_18/VWolviRepCutUnit_part_18___024root__6.cpp` 约 17855 行与 `__11.cpp`
约 15029 行，同一个 `othersEntry_all_wakeup_iq_from_exu4_src1_cntCounter_4`
也有求和与状态写入，不是 Verilator 省掉了 perf 功能；该状态赋值处没有逐值的
GrhSIM reader 通知。这只是具体实现差异，不代表已将全部性能差额归因到这个
计数器。分类中的“纯输入切片”还排除了混合 supernode，不能由该分类的低占比
断言所有输入切片都不重要。

[路径探针与构建脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/two_edge_path_profile.py)、
[实际 supernode 记录](../../build/repcut_grhsim_20260925/active_dispatch_20261003/two_edge_path_20261005/trace_results.json)、
[G/V core PMU](../../build/repcut_grhsim_20260925/active_dispatch_20261003/two_edge_path_20261005/pmu_results.json)、
[branch-miss IP](../../build/repcut_grhsim_20260925/active_dispatch_20261003/two_edge_path_20261005/ip_branch-misses_results.json)、
[归因核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/two_edge_path_20261005/verification.json)。

#### 通用候选：共同使能提到组外，但仍精确保留输出和通知

试验规则只按结构匹配：至少 8 项相邻的纯 bool 赋值，共用同一个不可变 state-bool
使能；源/目标 slot 集合不相交，目标不重复，赋值之间只能有注释/空白。
保留每项输出比较、原有 reader 标志的 OR 累积及写回顺序；不匹配 part、模块、
信号或 workload 名称，不使用 profile/编译反馈筛选。

```cpp
// 原来每项都计算 source_i & gate，然后比较、通知、写回。
if (gate) {
    // 每项 next = source_i；其余比较/通知/写回保留。
} else {
    // 每项 next = false；其余比较/通知/写回仍保留。
}
```

使能为 0 不能直接跳过：上次保存的输出可能为 1，必须清零并通知。
第一版额外要求组内 reader 集合相同；第二版去掉这个非必要限制，因为变换没有
合并通知，始终逐项保留原 reader 集合。两版都只是 generated-C++ source oracle，
不是生产文本替换 pass。

| 候选 | 匹配范围 | 输出赋值数 | 重编译对象 `.text` / B |
| --- | --- | ---: | ---: |
| 相同 reader 集合 | 5 part、6 文件、84 组 | 728 | 143061→129844 |
| 保留各自 reader 集合 | 5 part、14 文件、216 组 | 2594 | 353702→346495 |

两个候选普通 ELF SHA256 分别为
`3190249fe00ee49ebf30c31f5143c03957cf75f7716d5aafe9a95515ef24ad50`、
`1f9c5acdfdb7a9048c2e58e54d05717a6714b4ee6e8d3d2dcc20925d6e35f10b`。
O0/O3 的 ASan/UBSan 语义测试均通过，每版 16000 组输入、各重复 3 次，覆盖
旧值为 1 后清零、使能翻转、预置活动标志、重复 eval、源目标别名及副作用拒绝；
第二版还逐位检查不同 reader 集合。全部 6/14 个原始对象重编译与冻结 archive
匹配，候选也恰好只改变这些成员；6859 个 compute entry 保留 64 B 对齐。

#### 普通 walltime 与固定步 PMU：未确认瓶颈收益

每版完成两窗口各 4 对普通 AB/BA，中间独立运行 4 对 core PMU。普通结果不混入
探针 walltime。下表绝对值为 8 次普通运行的算术均值，百分比为配对变化中位数。

| 指标 | 相同 reader：A→B | 配对变化 | 各自 reader：A→B | 配对变化 |
| --- | ---: | ---: | ---: | ---: |
| walltime / s | 15.96375→15.92375 | −0.313%，5/8 更快 | 15.92750→15.92000 | −0.125%，4/8 更快 |
| Host / s | 15.92963→15.89050 | −0.314% | 15.89213→15.88550 | −0.144% |
| 全局 eval / µs | 50.39975→50.39863 | −0.061% | 50.35913→50.31588 | −0.320% |
| 全局 update / µs | 23.88075→23.81375 | −0.395% | 23.77425→23.74388 | −0.023% |
| p18 全步 eval / µs | 30.99525→31.06638 | +0.473% | 31.09438→30.61588 | **−1.483%，8/8 更快** |

第一版 walltime 的均值比为 −0.251%，第二版为 −0.047%，不能写成第二版有
1.48% 的整机收益。第二版两个普通窗口的 walltime 配对中位数分别 −0.500%/
+0.188%，没有一致改善。其 p18 全步平均确实下降，但固定历史瓶颈集合不是全步
集合，PMU binary 也不是普通 binary，以下结果同样必须保留：

| p18 两沿固定集合，4 对 PMU | eval | cycles | instructions | branches | branch misses |
| --- | ---: | ---: | ---: | ---: | ---: |
| 相同 reader | −0.050% | −0.390% | −0.189% | +0.316% | +0.096% |
| 各自 reader | **+1.701%** | +1.278% | −0.896% | +0.897% | +0.256% |

第二版下降沿单独为 eval +3.244%、cycles +2.472%、instructions −0.911%。
这不是“完全没命中执行路径”，但节省约 0.9% 的指令仍不足以得到目标区间加速。
其 14 个对象含栈地址的静态指令 16020→8079，却增加了 SIMD 重排
1900→3263、条件跳转 511→642；静态指令总数 66683→67605。p18/b179/b210
的 `.text` 还分别略增。静态数量不是动态 spill/执行次数，不能只按栈引用减半
认定收益，也不能仅凭分支增加就把全部 cycles 退化归因于 branch miss。

两版都没有改动 p10 的模型对象，但第二版固定两沿 p10 eval 为 −1.107%，指令/
分支基本不变。这种变化不能算成优化直接减少了 p10 工作；ASLR off 和 64 B
对齐不固定完整链接布局，探针、布局与执行上下文也可能影响时间。本轮没有继续
对齐搜索，也没有用普通/探针之间方向不同的数字挑选有利结论。

#### 动态值计数：下一步应评估无变化输出，而非只省源读取

最后在冻结 baseline 上另做纯值计数，针对第二版命中的 p18 四个文件、57 组、
711 项输出，不施加优化、不使用其时间作性能数据。2 次 C100000 的原始计数逐字
相同，仍用前面的 260 对历史 anchor/next：

| 每个选中 step 的均值 | 上升沿 | 下降沿 |
| --- | ---: | ---: |
| 进入的赋值组 | 56.381 | 57.000 |
| 共同使能为 0 的组占比 | 53.60% | 54.02% |
| 使能为 0 路径上的输出项 | 376.727 | 383.781 |
| 其中旧值为 1、需要清零的项 | 0.0615 | **0** |
| 使能为 1 路径上的输出项 | 326.688 | 327.219 |
| 其中实际变化的项 | 1.981 | 2.488 |

因此这些组确实有较多关闭使能的路径，不是“运行时始终开启”导致改写无用。
但第二版仍对关闭路径逐项读取旧输出、比较、累积通知和写零；而下降沿 711 个
输出中平均只有约 2.49 个真正变化。**下一项值得验证的是能否安全证明整组输出
仍为零/不变并跳过，而不是再给表达式增加分支。** 这只是后续方向，不是本轮
已实现的缓存优化；必须在 IR 层证明唯一写者、别名/副作用边界、首次执行和
使能翻转时的失效语义。不能仅凭本次 0 次清零观测假定以后永远为 0，也不能关闭
perf/assert 功能或改成模块/变量名单。

**本轮裁决：** 两项共同使能候选均暂不叠加到有效探索线、不晋升默认。第一版
仅有小幅 walltime 变化且未改善目标 p18，第二版 p18 全步均值有益但整机基本持平、
固定两沿未改善。继续保留 §7.51 的冻结探索线、现有 all-spin 和 64 B 对齐。
本节完成 **76 次 C100000、20 次 C100**：归因 26/7，两候选各 24/6，动态值
计数 2/1；Difftest/终态签名、输入身份与配置核验均通过。正式 core PMU 无
multiplex，IP 无 lost/throttle；探针结果与普通 walltime 分开，无遗留测量任务。

[共同使能原型与语义测试](../../build/repcut_grhsim_20260925/active_dispatch_20261003/shared_bool_guard.py)、
[两窗口及同对象探针对照脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/shared_bool_guard_diagnostics.py)、
[第一版最终核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/shared_bool_guard_20261005/verification.json)、
[第一版固定步 PMU](../../build/repcut_grhsim_20260925/active_dispatch_20261003/shared_bool_guard_20261005/diagnostics/pmu_results.json)、
[第二版匹配范围](../../build/repcut_grhsim_20260925/active_dispatch_20261003/shared_bool_guard_mixed_20261005/prepare.json)、
[第二版静态统计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/shared_bool_guard_mixed_20261005/static.json)、
[第二版最终核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/shared_bool_guard_mixed_20261005/verification.json)、
[第二版固定步 PMU](../../build/repcut_grhsim_20260925/active_dispatch_20261003/shared_bool_guard_mixed_20261005/diagnostics/pmu_results.json)、
[值计数脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/shared_guard_activity.py)、
[值计数结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/shared_guard_activity_20261005/results.json)。

本轮普通/诊断运行分账及冻结候选的最终交叉核验见
[shared_guard_final_verification_20261005.json](../../build/repcut_grhsim_20260925/active_dispatch_20261003/shared_guard_final_verification_20261005.json)。

### 7.53 当前值证明的整组不变跳过（2026-10-05）

继续 §7.52 的动态值线索，但不叠加该节未保留的共同使能外提原型。两版新候选
均直接对照冻结 `late_pack_snapshots_20261005/candidate/emu`，SHA256
`b42045cf9cf9fb9f4a3fc2da163fe0caf61f330d1e4857bb8424f36ffc264ee6`。
保持 node030 CPU96–127、NUMA1、Host105、N=K=32、all-spin、Clang23/O3、
进程级 ASLR off 和 64 B compute entry 对齐；所有成功样本均计入，不设空闲率 gate。
本节仍为 generated-C++ source oracle 验证，不是正式 emitter 或生产默认修改。

#### 不需要持久缓存：每次根据当前输出判定

原计划考虑缓存“这组输出已清零”，但最小可验证实现可以直接读取当前输出。
这样无需新增模型状态或失效标志，也不依赖跨 eval 的唯一写者历史假设。
选取至少 8 项连续、纯 bool 赋值 `out_i = source_i & state_gate`：共同使能必须
是不可变 state-bool 字段，目标互异且与组内源 slot 集合不相交，项间只有注释/
空白。不能夹带 DPI、状态写入、独立统计语句或其他副作用。全图按结构匹配，
没有 part、模块、信号、profile 或编译反馈名单。

**Zero：关闭使能且输出已全零时跳过。**

```cpp
if (gate || any_current_output_is_one) {
    // 完整保留原来的逐项 next、比较、reader 标志 OR、写回。
}
```

`any_current_output_is_one` 是 bool 输出的 eager 位 OR；只有 `gate == false`
才需要检查它。若此时旧输出全为零，原 next 必然也全零，所有 changed 都是
false，写回和通知均为无效工作，可以跳过。若任一旧输出为 1，原代码照常清零并
通知；若使能变成 1，直接执行原代码。首次执行、inactive eval、源值变化以及
其他写者在两次 eval 之间改写输出，都不需要重置缓存，因为根本没有历史缓存。
这不等于允许同一模型存在数据竞争；沿用原有单线程求值语义。

**Exact：整组新旧值完全相同时跳过。** 使用相同结构匹配集合，先按原顺序
求出每项 `next_i` 和 `changed_i`，只求值一次；若所有 changed 都为 false，
跳过写回和通知，否则复用这些局部值执行原来的逐项 reader 标志更新和写回。
源/目标不相交确保把这些纯读取提前到组首不会改变结果。即便 reader 集合不同，
仍各用各的 changed，不把整组变化广播给所有下游。这与已有 commit 阶段分组
相似，但本轮对象是 compute 的布尔中间值，不修改 commit 路径。

两版均命中 **5 个分区、14 个文件、216 组、2594 项输出**，组大小 8–14；
p18 为 4 文件、57 组、711 项。头文件、C++ 模型成员布局、init 和框架不变。
Zero 的普通 ELF SHA256 为
`012d587d339324fc87b1ba496e0042e5fd3acad6fc76799e18e461108232abe2`，Exact 为
`2a09e573f24c1bc6b2665c1e6d4ab885ab6617d107c520b45fdea48b89db86a0`。

两版专项均通过 Clang23/O0、O3 的 ASan/UBSan：24000 组输入、每组 6 次连续
调用，另有逐输出旧值为 1 的清零检查；覆盖不同 reader 集合、预置活动标志、
使能翻转、inactive、两次 eval 间改写输出。拒绝源目标别名、重复目标、未知
状态来源和项间副作用。14 份原始源码均先重编译并与冻结 archive 核验，再生成
候选；各自恰好只改变这 14 个成员，其余 7440 个成员不变，6859 个主要 compute
entry 仍全部 64 B 对齐。这些测试不代替将来正式 IR 规则的 fresh 生成回归。

#### 动态机会与编译代价不能混为一谈

复用 §7.52 的两次完全相同的 baseline 值计数；没有增加仿真次数，也没有据此
筛选匹配组。先核对新旧规则的 p18 57 组在 gate、源、目标和 reader 集合上逐项
相同；每个被记录的组在该 eval 内恰好调用一次，因此可以精确重算跳过条件。

| p18 固定历史集合 | Zero 可跳过的组 | Exact 可跳过的组 | Zero / Exact 可省写回项数，per step |
| --- | ---: | ---: | ---: |
| 上升沿 | 53.49% | 96.45% | 376.012 / 678.081 |
| 紧接下降沿 | 54.02% | 95.80% | 383.781 / 680.869 |

这是条件命中量，不是时间占比或加速预测。Exact 即使跳过更多写回，仍须先算
各项 next 和变化条件；Zero 在关闭路径不需要读取源值。

| 所有重编译对象的静态计数 | baseline | Zero | Exact |
| --- | ---: | ---: | ---: |
| 可执行段大小 / B | 353702 | 313915 | 347026 |
| 指令条数 | 66683 | 64448 | 70528 |
| 含栈地址的指令 | 16020 | 8309 | 14818 |
| 条件跳转 | 511 | 851 | 825 |

静态计数包含 helper，不是执行次数或动态 spill。两版都增加了分支，并非
“去掉了 54%/96% 的全部计算”。

#### 两窗口普通复测与两候选直接对照

每版先后各 4 对普通 AB/BA，中间单独跑 4 对 core PMU。以下绝对值为 8 次
普通运行的算术均值，百分比为各对相对变化的中位数，探针 walltime 不计入。

| 普通指标 | baseline→Zero | 配对变化 | baseline→Exact | 配对变化 |
| --- | ---: | ---: | ---: | ---: |
| walltime / s | 15.94625→15.81250 | **−0.784%，8/8 更快** | 15.95500→15.83750 | **−0.564%，8/8 更快** |
| Host / s | 15.91300→15.78125 | −0.767% | 15.91963→15.80425 | −0.533% |
| 全局 eval / µs | 50.41800→49.98313 | −0.875% | 50.40913→49.92025 | −1.007% |
| 全局 update / µs | 23.79000→23.71075 | −0.326% | 23.83725→23.71713 | −0.427% |
| p18 全步 eval / µs | 31.09163→30.03188 | −3.048% | 31.10488→30.22738 | −2.775% |

Zero 两个普通窗口的 walltime 配对中位数 −0.813%/−0.627%，Exact 为
−0.658%/−0.564%。walltime 均值之比分别为 −0.839%/−0.736%，不要和配对中位数
混用。两版都比各自的冻结 baseline 更快，但不能将不同窗口的两个改进百分比
直接相减，作为候选间收益。

随后新增 **4 对 Zero/Exact 直接交错**。Zero / Exact walltime 均值为
15.8850 / 15.9525 s；Exact 相对 Zero 的配对中位数 **+0.284%**，4/4 对更慢，
Host +0.322%，全局 eval +0.293%。p18 全步 eval 仅 +0.059%，因此这约 0.28%
的整机差额也不能全部归为 p18 的直接计算差异。本轮候选选择优先 Zero。

#### 固定步 PMU：指令确实减少，目标区间时间尚未同比改善

标签仍是历史 p10 175 对、p18 260 对上升沿及紧接下降沿；不是在本次运行里
重新挑选瓶颈。两边使用相同探针对象，模型对象不额外重编译。

| p18 固定两沿，4 对 PMU | eval | cycles | instructions | branches | branch misses |
| --- | ---: | ---: | ---: | ---: | ---: |
| Zero | +0.312% | +0.162% | **−0.942%** | +0.996% | +1.739% |
| Exact | −0.101% | −0.392% | **−0.488%** | +0.549% | +0.312% |

下降沿单独的 eval 变化分别约 +0.001%/−0.088%，同样接近持平。更多组跳过写回
没有自动带来更大的指令节省或瓶颈时间收益，不能把全步 p18 的 −3% 当作固定
历史瓶颈步也缩短 −3%。PMU 与普通 binary 不同，后续轻量计时另行核验。

Zero 的 p10 全步 eval 也下降 2.714%，但 p10 模型 archive 对象未改变，其固定
两沿动态指令基本不变，不能算作规则直接减少了 p10 工作。只读布局核验显示
p3/p10 的 341/170 个 compute entry 地址及尺寸全部相同；不过 `.rodata` 起址
94273536→94236672，链接后的函数体分别仅 49/51 个完全逐字节相同。入口 64 B
对齐、ASLR off 或 archive 对象不变都不等于完整代码/常量布局不变；本轮没有
进一步调布局，也没有将这个观察排他地当作 p10 时间变化的原因。

[两版通用原型及专项测试](../../build/repcut_grhsim_20260925/active_dispatch_20261003/zero_guard_groups.py)、
[Exact 配置](../../build/repcut_grhsim_20260925/active_dispatch_20261003/exact_change_groups.py)、
[Zero 普通/PMU 最终核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/zero_guard_groups_20261005/verification.json)、
[Exact 普通/PMU 最终核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/exact_change_groups_20261005/verification.json)、
[两候选直接普通对照](../../build/repcut_grhsim_20260925/active_dispatch_20261003/zero_vs_exact_20261005/results.json)、
[同集合动态机会计数](../../build/repcut_grhsim_20260925/active_dispatch_20261003/zero_guard_opportunity_20261005.json)。

#### 轻量计时补充：固定集合不是完全无收益，探针也会影响对照

针对普通 p18 全步改善而 PMU 固定两沿近乎持平的差异，另完成两版各 **4 对**
仅计时 AB/BA。复用框架已有的 eval 起止时间戳，在 eval 结束后保存选中步的
时间差，不增加 PMU 读取、clock 读取或模型内部插桩；两边复用同一组 wrapper
对象，全部模型 archive 成员保持各自普通版本不变。未改写 wrapper 的源文件
重编译先与冻结对象的 alloc section/relocation 内容匹配，独立采样器专项通过
ASan/UBSan。每次长运行每个被测 part 恰好 3148 条记录，无重复；历史标签仍为
p10/p18 的 355/538 步、其中上升沿 anchor 175/260 对，没有重选瓶颈标签。

下表为 **轻量计时 binary 内部**的配对变化中位数，不与普通/PMU 的绝对值拼接。

| p18 eval 集合，4 对轻量计时 | Zero | Exact |
| --- | ---: | ---: |
| 历史瓶颈步 selected | −0.946%，4/4 更快 | −0.530%，2/4 更快 |
| 上升沿 anchor | −0.877% | −0.703% |
| 紧接下降沿 next | **−2.266%** | −0.867% |
| 两沿合计 | **−1.498%，4/4 更快** | −0.777%，3/4 更快 |
| 全部 3148 个采样步 | −1.774% | −0.886% |
| 同一 binary 的全步 eval 统计 | −1.770% | −1.119% |

Zero 的 p18 两沿合计均值为 88.93289→87.59484 µs，下降沿为
39.77071→38.86645 µs；Exact 两沿合计为 89.38041→88.67887 µs。
轻量计时中两沿/全步方向接近，说明“普通运行只改善了非瓶颈步”不足以解释
全部差异，也不能继续把 PMU 的 +0.312% 解释成规则对固定集合完全无效。
不过本实验同时改变了探针调用和链接后的 binary；**尚不能排他地区分 PMU
读取扰动、链接布局与运行上下文的贡献**，更不能从三个不同 binary 的百分比
相减，计算所谓探针开销或直接优化贡献。

p10 模型未改，但轻量固定两沿仍为 Zero −2.857%、Exact −1.603%，全步为
−2.765%/−1.295%。这是另一项不能把所有计时改善直接归于新增跳过路径的证据。
这些轻量 binary 的 walltime 配对中位数分别 −0.126%（2/4 更快）和 +0.346%
（1/4 更快），与普通对照不同；诊断 walltime 不加入前面的普通收益统计。

#### 本轮裁决与后续边界

**优先保留 Zero 作为下一阶段的探索候选，不叠加 Exact，也不立即晋升生产默认。**
理由是普通对照在两个窗口均有小幅收益、直接对照 4/4 胜过 Exact，同时实现
更简单、静态代码更小；轻量固定集合也提供了方向一致的 p18 改善证据。不能把
约 54% 的组可跳过说成接近 54% 的 eval 加速，当前普通整机收益仍仅约 0.78%。

下一步应将这个无持久状态的条件表达为正式 IR/emitter 层的结构规则，在 compute
赋值组发射处证明共同使能、纯读取、源目标不相交及逐输出 reader 通知语义，
再做开关对照的 fresh 生成与普通 AB/BA；不按 p18、信号名或采样命中率决定资格。
本轮只验证了源码原型，尚未完成这一步，不能用原型替代正式生成回归。现有
Verilator、all-spin、64 B 对齐及生产默认均未改变，也未继续进行对齐搜索。

本轮累计 **72 次 C100000、18 次 C100** 全部通过终态/Difftest 与输入身份核验：
40 次普通长运行（两个候选各 16 次、直接互比 8 次），16 次 PMU、16 次轻量
计时。普通/诊断分账，所有成功样本均计入；复用上一节值计数不重复计算次数。
完整核验已结束，无遗留本轮测量任务。

[轻量计时实现](../../build/repcut_grhsim_20260925/active_dispatch_20261003/zero_guard_cohort_timing.hpp)、
[轻量计时专项](../../build/repcut_grhsim_20260925/active_dispatch_20261003/zero_guard_cohort_test.cpp)、
[轻量构建及运行脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/zero_guard_cohort_timing.py)、
[轻量结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/zero_guard_cohort_timing_20261005/results.json)、
[全部运行最终核验脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/zero_guard_results.py)、
[本轮最终汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/zero_guard_summary_20261005.json)。

### 7.54 当前全零组保护的正式 emitter 实现与 fresh 验证（2026-10-05）

承接 §7.53 的 Zero 原型，现已在 `grhsim_cpp.cpp` 中加入通用 IR/emitter 规则。
新选项为 `bool_zero_group_guard`，对应环境变量
`WOLVRIX_GRHSIM_BOOL_ZERO_GROUP_GUARD`，**默认关闭**，显式 attribute 优先。
不引入持久状态、缓存标志、profiling/编译后反馈或模块/信号/part 名单，也不改
Verilator、多线程框架、all-spin 或既有 64 B 对齐。

#### 匹配真实 IR，而不是匹配生成代码文本

输出赋值既可能是直接 `kAnd`，也可能是 `kAssign` 消费已经内联的 AND；后者是
前一节原型的主要形态。只沿 emitter 已确认内联的同宽纯 bool alias 追溯，拒绝
已物化的中间快照。共同使能的身份通过已有 bool 状态读取解析器证明：可以是
direct-state-read，也可以是已内联的纯 register/latch read；**持久 value-slot
中的状态快照不能替换成当前状态字段**。

在同一普通 compute supernode 内寻找至少 8 项连续赋值，比较物理 bool-slot
编号以覆盖别名，要求目标互异、全部源和目标不相交。其他 op、不同使能、
concat-prefix 声明和 supernode 边界终止组；DPI、副作用、输入 port、事件值、
宽值和任意表达式均不作为组成员。仅在原来的逐项代码外增加
`if (gate || any_current_output_is_one)`，其内部计算、顺序、各自 reader 通知和
写回均不改；普通 fullpass 版本沿用原实现。

专项 `emit-grhsim-cpp-bool-zero-group-guard` 已通过首轮 12 配置测试：默认/
显式关闭恒等性、环境选项优先级、正反 AND operand、内联 AND/Assign/源 alias、
状态快照/短组/源目标重叠/副作用拒绝、DPI 次数、使能翻转、重复 eval、重复 init、
不同 reader 集合、packed/direct deferred、helper 拆分与 fullpass。执行型配置
分别编译 O0/O3 并运行 ASan/UBSan；后续最终验证还将显式开启 runtime profile。

#### 实验口径

对同一份冻结 `partitioned.json`，从全部 32 个 GRH graph 分别 fresh 生成开关
关闭/开启两份 package，不手选图或文件。关闭输出须与上轮 fresh 输出逐文件一致，
开启输出须在去掉新增保护条件后逐字恢复关闭输出。为保持 §7.53 对照口径，两边
同样保留此前尚未全部迁入 emitter 的冻结探索变更；只接受与本规则不冲突的
增量合并，并再次检查去保护后与冻结源码一致。完全相同的对象允许复用，受影响
源码先重编译 baseline、核对机器码/常量/重定位，再编译候选。

性能对照 baseline 仍为 `late_pack_snapshots_20261005/candidate/emu`（SHA256
`b42045cf9cf9fb9f4a3fc2da163fe0caf61f330d1e4857bb8424f36ffc264ee6`）；不是退回
生产默认，也不是拿未开启其他探索优化的 fresh 程序当 baseline。node030
CPU96–127、NUMA1、Host105、N=K=32、all-spin、Clang23/O3、ASLR off、64 B 对齐
均不变。正式 fresh 开关审计和普通 AB/BA 结果在完成后继续补充于本节。

[正式实现](../../wolvrix/lib/emit/grhsim_cpp.cpp)、
[生成器语义回归](../../wolvrix/tests/emit/test_emit_grhsim_cpp.cpp)、
[选项与证明边界](../../wolvrix/docs/emit/grhsim-scheduling.md)、
[完整生成、审计与 AB 脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_zero_group.py)。

#### 完整生成与最终语义回归结果

32 图开关两份 fresh 生成完成，全部 **7552 个 C++/头文件**通过比较：关闭版与
此前冻结 fresh 输出逐字节相同；开启版只增加保护条件，去掉条件后逐字节恢复
关闭版。模型头文件、接口、commit 和 runtime 不变。生成用库另行复制冻结，并
记录输入 JSON、绑定、源文件和库的身份；最终核验再次检查其未被并行工作改动。

正式规则自动覆盖 **234 组、2908 项输出、9 个 part 的 24 个源文件**。逐 part
组数为 p4/5/6/13/16/17/18/19/23 = 6/3/2/1/18/30/57/38/79；这些编号仅用于
报告结果，不参与选择。旧文本原型的 **216 组全部保留，遗漏为 0**，新增 18 组、
314 项输出来自操作数顺序、内联 AND/Assign 和 bool alias 的结构覆盖。

全部受影响源码先重编译关闭版，其可装载 section 与 relocation 与冻结基线对象
一致，再编译开启版；复用 7430 个未改变对象，替换 24 个对象并重新链接。
不是全对象重编译，也不是移除既有探索增量后从生产默认重新开始。24 个对象的
`.text` 总计 508441→474224 B（约 −6.73%，不是整个程序的体积变化）。与旧 Zero
原型比较，原来涉及的 14 个对象机器码/常量/重定位一致，仅新增覆盖涉及的
10 个对象不同；p18 的 57 组、711 项输出未扩大。最终 6859 个主要 compute
入口保持 64 B 对齐，未做布局搜索。

5 项最终 CTest 均通过：`emit-grhsim-cpp-bool-zero-group-guard`、
`emit-grhsim-cpp-wordwise-bool-pack`、`emit-grhsim-cpp-scalar-concat-reduction`、
`emit-grhsim-repcut-package`、`emit-verilator-repcut-package`。其中零组专项的
12 配置含真正开启 runtime profile 的执行路径，执行型配置分别运行 O0/O3 与
ASan/UBSan，逐输出检查随机输入、使能切换、旧非零值清除、重复 eval/init 和
DPI 次数；不是仅做生成文本匹配。这是定向回归，不声称跑完仓库全部 CTest。

[全源码审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_zero_group_v2_20261005/audit.json)、
[旧原型覆盖对照](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_zero_group_v2_20261005/prepare.json)、
[对象与链接审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_zero_group_v2_20261005/build.json)、
[5 项回归凭证](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_zero_group_v2_20261005/tests.json)。

#### 普通 AB/BA 完成：正式实现保留了小幅整机收益

冻结基线与正式候选分两个窗口各跑 4 对，共 **8 对 C100000 普通 AB/BA**；没有
增加 PMU/模型内探针。下表绝对值为各版本 8 次运行的算术均值，变化列为先逐对
计算 `(candidate / baseline - 1) × 100%` 后取中位数，**不是两个均值之比**。

| 指标 | 冻结 baseline 均值 | 正式 IR 候选均值 | 配对变化中位数 | 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| walltime / s | 15.888750 | 15.790000 | **−0.723%** | 7/8 |
| Host / s | 15.852625 | 15.757375 | −0.675% | 7/8 |
| 全局 eval / µs | 50.099750 | 49.826875 | −0.579% | 7/8 |
| 全局 update / µs | 23.867125 | 23.704125 | −0.400% | 7/8 |
| p3 全步 eval / µs | 43.734625 | 43.699750 | −0.034% | 4/8 |
| p10 全步 eval / µs | 29.898250 | 29.500375 | −1.190% | 8/8 |
| p18 全步 eval / µs | 31.016625 | 30.300875 | **−2.155%** | 8/8 |

两个窗口 walltime 的配对变化中位数分别为 −0.630%/−0.723%。合并 walltime
均值减少 98.750 ms，**均值之比为 −0.622%**；p18 均值之比为 −2.308%。本轮
没有固定瓶颈步探针，不能把 p18 全步均值变化解释为“成为瓶颈时也改善 2.3%”。
p3 仍基本不变，说明本规则没有解决当前最长 eval 分区；p10 模型对象未改，
其计时变化同样不能算作本规则直接减少了 p10 工作。

#### 与旧 Zero 原型直接对照及裁决

另外完成 **4 对旧 Zero→正式 IR 候选普通交错对照**，不使用不同窗口的两个
baseline 收益相减。旧 Zero ELF SHA256 为
`012d587d339324fc87b1ba496e0042e5fd3acad6fc76799e18e461108232abe2`；正式候选为
`0fe15b5b48283f6d1a6542daac5d32c9791b553e2604f2589dc5f60ce8e5eb59`。

| 直接对照指标 | 旧 Zero 均值 | 正式 IR 均值 | 配对变化中位数 | 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| walltime / s | 15.890000 | 15.835000 | −0.534% | 3/4 |
| Host / s | 15.857000 | 15.797500 | −0.542% | 3/4 |
| 全局 eval / µs | 50.088500 | 49.838500 | −0.506% | 4/4 |
| p18 全步 eval / µs | 30.533000 | 30.344750 | −0.644% | 4/4 |

直接对照 walltime 均值之比 −0.346%；但 AB/BA 顺序分组的配对变化中位数为
**+0.065% / −0.752%**，有顺序差异，不据此宣称新增 18 组独立贡献了 0.53%。
新增覆盖的 p4/5/6/13/23 的全步 eval 配对变化分别为
−1.178% / **+0.590%** / −0.021% / −0.136% / −0.422%；覆盖增加不意味着每个
part 都变快。尤其 p10 archive 对象两边相同，计时却 −3.439%；p18 原有对象
也一致，因此不能排除重新链接后的布局及运行上下文贡献，也不据此再做布局
调参或按 part 排除规则。

**保留正式 IR 规则作为后续探索实现，替代手工生成代码原型；生产默认仍关闭。**
结构证明、源码恒等性、语义回归和普通 walltime 对照已闭合，当前证据支持它
保留小幅整机收益，但不支持宣布已解决 p3 瓶颈、证明跨 workload 泛化，或把
所有计时改善归给跳过的赋值。已有源码探索增量尚未全部迁入 emitter，本轮
fresh 生成加增量保留的口径也不能称为“全部生产默认的独立全新构建”。

本轮总计 **24 次 C100000、6 次 C100**，全部通过终态/Difftest、运行配置及
输入身份核验；包括 16 次基线对照长运行和 8 次原型直比长运行，无诊断 walltime
混入，无成功样本剔除，且不重复统计 §7.53 的运行。5 项测试及全部生成输入
身份最终复核通过；本轮生成、编译和测量均已结束，无遗留本轮任务。

验证口径补充：24 次长运行均记录 `Difftest enabled` 并通过终态核验；6 次
C100 虽传入同一差分模型，但指令数为 0、尚未进入实际指令差分阶段，只作为
初始化/终态签名短测，不计作额外 6 次已执行指令的 Difftest 验证。

[普通两窗口及原型直比最终汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_zero_group_v2_20261005/results.json)、
[第一窗口原始记录](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_zero_group_v2_20261005/ordinary_1/manifest.json)、
[第二窗口原始记录](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_zero_group_v2_20261005/ordinary_2/manifest.json)、
[旧原型直接对照](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_zero_group_v2_20261005/prototype_direct/manifest.json)。

### 7.55 当前正式线 p3 关键路径复核与状态字段共访问布局试验（2026-10-05）

本节承接 §7.54 的正式 IR 候选，固定被测 ELF 为
`0fe15b5b48283f6d1a6542daac5d32c9791b553e2604f2589dc5f60ce8e5eb59`；不改变
生成输入、生产默认、Verilator、all-spin、64 B 对齐或线程框架。先用候选本身的
4 对普通 timing 运行冻结瓶颈标签，再进行 batch/PMU/IP 诊断；标签在诊断前冻结，
不以诊断结果重新选择样本。

#### p3 确实是当前候选的关键路径，但热点不是单一 batch

4 对运行共 3148 个 step；按 p3 的 eval 完成时间最后者定义，p3 在 **3064/3148**
个 step 最后完成，领先第二名的完成时间平均约 **13.93 µs**。这说明 p3 仍是
当前同步关键路径，但不能把“最大源码文件”直接等同于“最大动态代价”。

固定标签下的低扰动 batch 计时只作为排序证据（计时 probe 会改变局部代码和
调度，不能换算成自然 walltime）：p3 活跃 compute probe 总和约 41.63 µs，
b46 约 1.194 µs、仅 **2.87%**；b322 0.726 µs、b19 0.718 µs，前 10/20 个
batch 也只占约 **15.76%/25.55%**。按生成 IR 的结构分类，活跃时间为：

| 结构类别 | batch 数 | 活跃时间占比 |
| --- | ---: | ---: |
| slice/mixed（静态/动态切片及其混合） | 141 | **48.71%** |
| memory/mixed（含 memory read/write） | 55 | **30.34%** |
| control/compare（比较、归约、mux 等） | 126 | 15.47% |
| pure_pack（仅 register read/concat） | 2 | 2.88% |
| other | 17 | 2.60% |

b46 的 2.57 MB 源码主要是纯 register-read/concat 输出打包，但它只占 p3 活跃
时间 2.87%，因此单独改 b46 或继续做宽快照延迟物化不构成合理的下一步。
全 p3 源码静态计数约 40158 个 register-read、7760 个静态切片、361 个
memory-read 和 89483 个 `grhsim_changed_*` 文本引用；代码行数/字节数与
probe 时间的相关性高于任一种单独 op 计数，支持“分散的状态读取 + 变化通知”
而非单一选择链是主因。

另外对 b19 的 O3 反汇编做了一个排除性检查：多个同源
`grhsim_get_bit_words(repcut_port_15, bit)` 已被 Clang 合并为一次 64-bit
源加载，再用多次移位/比较消费；因此把生成文本中的 bit helper 手工缓存，并
不能自动减少真实 load。下一候选应优先观察 `old-slot compare → 多个
changed group → active byte` 的依赖链和 memory-read staging，而不是重复实现
编译器已经完成的位提取公共子表达式。

#### GrhSIM 与 Verilator 的 p3 PMU 对照：p3 不是 GrhSIM 相对 V 的后端慢点

这是**插桩诊断 binary** 的 p3 标签均值，不是普通 walltime，也不用于宣称
某条指令的排他因果。GrhSIM 候选相对 Verilator/O3 baseline 的 4 对选定样本为：

| p3 指标 | Verilator/O3 | GrhSIM | 配对变化中位数 |
| --- | ---: | ---: | ---: |
| eval duration / ns | 76603.98 | 43753.65 | **−43.09%** |
| cycles | 275113.37 | 157446.88 | **−43.00%** |
| instructions | 423090.64 | 308731.04 | **−27.03%** |
| branches | 11558.14 | 12418.77 | **+7.45%** |
| branch misses | 2140.11 | 68.47 | **−96.79%** |

pipeline/cache/memory PMU 也分别显示 cycles 约 −42.4%、I-cache/op-cache
misses 约 −39%/−49%、cache refs/misses 约 −27.6%/−33.2%。所以当前 p3
之所以在 GrhSIM 内部成为最后完成者，不是因为它比 Verilator 的同一 p3 后端
更慢；优化目标应是减少 GrhSIM 自身的总工作量/关键路径，而不是继续追 branch
miss 或照搬 Verilator 分支布局。cycles-IP 是稀疏整步采样，step 标签不能把
异步 sample 解释成 p3 函数独占时间；报告保留这一范围限制。

#### 状态字段共访问布局：有局部信号，但不足以进入默认线

为验证“p3 的状态字段按生成顺序散落，是否造成 cache-line 跨度”这一机制，做了
一个**只改 p3 头文件字段顺序**的测量候选：按静态 compute-batch 共访问签名
（同一状态字段在哪些 batch 被读）重排 `state_logic_storage_t`，不按 part/信号名
选择，不使用编译后 profile。正确的第二版把源文件放在实验目录以确保引号包含
真的使用重排头文件；321 个 archive member 改变，其余 7444 个逐字节不变，
8 对 C100000 均通过统一 Difftest 终态。

两组各 4 对 AB/BA 的结果方向不一致但可解释：8 对合并 walltime 配对中位约
**−0.158%**（均值约 −0.069%，5/8 更快），全局 eval 中位约 −0.392%，p3
eval 中位约 **−0.552%**；但 update 中位约 **+0.504%**，且第一组/重复组的
walltime 中位分别 −0.599%/−0.063%。因此它说明状态布局会同时影响 eval 与
update 的 cache/访问上下文，静态“cache-line 数减少约 2.6%”不能直接转成
稳定 Host 收益。该候选不迁入 emitter 默认，也不作为新的正式验证线；保留为
后续数据布局研究的证据。

**裁决与下一步：**停止以 b46 单点或单纯代码尺寸为目标。当前最通用、最有证据
的候选模式是“同一 supernode 内大量窄切片/寄存器读取，随后写回标量 slot 并传播
多个 reader activation”，应先在 IR 层做跨 workload 可证明的标量物化/变化通知
合并（保持旧值比较、事件和精确 active 集合），再用无 probe 的普通 walltime
裁决；不要把 p3 的状态布局试验或插桩 PMU 的局部改善直接升为默认。所有诊断
构建、4 对标签 timing、4 类 PMU、cycles-IP 和两组布局对照均已完成。

[p3 关键路径汇总报告](../../build/repcut_grhsim_20260925/active_dispatch_20261003/p3_critical_current_20261005/report.json)、
[p3 关键路径复现脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/p3_critical_path_profile.py)、
[p3 状态布局候选脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/p3_state_layout_probe.py)、
[状态布局构建与 4 对结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/p3_state_layout_coaccess_probe_v2_20261005/ordinary_p4/summary.json)、
[独立重复 4 对结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/p3_state_layout_coaccess_probe_v2_20261005/ordinary_p4_repeat/summary.json)。

#### 增量勘误 2026-10-06：§7.55 的瓶颈标签混入参考版本

复核 `p3_critical_path_profile.py::freeze_labels()` 发现，旧代码仅按 `pair` 保存
最后一条运行，未过滤 `variant == candidate`。AB/BA 因而使 4 组标签输入实际成为
**2 次 GrhSIM + 2 次 Verilator**，不是上述文字所称的 4 次当前 GrhSIM。原始
运行、历史标签和诊断数据保留不变；选择器已加版本过滤和每对唯一性断言。

只用原始的 4 次 GrhSIM 运行重新计算，3148 个采样 step 的最后完成者中，p3 为
**1098/3148（34.88%）**，而非 3064/3148（97.33%）；p18/p6/p29/p10/p26 分别为
510/423/372/368/198 个。共有 1968 个标签与旧结果不同。因此 §7.55 的“p3 几乎
始终处于关键路径”及 13.93 µs 领先值不能再作为 GrhSIM 独立瓶颈结论。

§7.55 的 batch/PMU/IP 数字仍是原固定步集合上的诊断结果，但该集合是混合版本
定义的，**不能称为 GrhSIM 瓶颈条件统计**，也不外推到修正后的标签。状态布局的
普通 AB/BA，以及 §7.54/§7.56 的普通 walltime 与全步均值，不依赖这个选择器，
不受此错误影响。后续改用版本独立标签，并将发现标签与验证计时分开运行。

[原始数据重算与选择器身份核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/state_view_critical_20261006/legacy_label_audit.json)。

### 7.56 仅复用已有 reader 的布尔状态视图（2026-10-06）

承接 §7.55 的标量物化/变化通知方向，本轮实现一个受限的通用 IR 规则：
**只有不增加任何 register→consumer 激活边时，才消除反相 bool 中间值。**
不使用模块/分区/信号名单，也不使用编译后反馈。冻结 baseline 仍为 §7.54 的
`0fe15b5b48283f6d1a6542daac5d32c9791b553e2604f2589dc5f60ce8e5eb59`；本轮候选为
`d17f0ab8fa2bcb6bf5e6e8c70b5560843b1c7493bfc3dd8bc939dce5543f8c33`。

#### 规则及结构核验

普通单写者 1-bit 寄存器 `q` 在 compute 内被局部读取，随后产生 `t = !q`，
其他 compute supernode 使用 `t`。原来需要保存 `t`、比较其新旧值，再通知
读者；若 **每一个使用者原本就是 `q` 的直接 reader**，就可让使用者直接求
`!q`：commit 改变 `q` 时，原有通知已经覆盖这些使用者，无需另加通知。

仅沿同 supernode 内未物化的纯 read/assign 路径追溯；拒绝快照、可见输出、
波形/事件、commit 使用者、多写者和有副作用的路径。资格检查只读既有 reader
集合，候选之间不扩展资格。保留 eager bool lowering，且禁止 bool-pack 把
反相视图误当成原始状态字段。实现为 `direct_bool_state_views=1` / 环境变量
`WOLVRIX_GRHSIM_DIRECT_BOOL_STATE_VIEWS=1`，attribute 优先，**生产默认关闭**。
完整契约见 [GrhSIM 调度文档](../../wolvrix/docs/emit/grhsim-scheduling.md)。

全 32 个分区自动筛选后保留 **464 处**，排除 **1709 处**需要新 reader 的情况，
新增激活边为 **0**。其中 p3 保留 84、排除 199；p10 保留 49、排除 69。
这些分区编号仅是结果统计，不参与优化选择。

关闭版 fresh 生成的 **7552 个源码/头文件**与冻结基线的生成对照逐字一致。
候选重放既有 same-reader / exact-mask 等探索增量后，**commit 源码全部不变**，
3006 个 exact-mask 分组也完全相同；没有把新增通知工作搬到 update。
不过 direct 引用会影响既有状态字段排序，11 个私有模型头文件发生重排，所以
不能据此声称 commit 的机器码、cache 行为或计时也必然不变。

受头文件/源码影响的 2829 个编译单元均先重编译关闭版，核验可装载 section
和 relocation 与冻结 archive 一致，再编译候选。最终 1504 个 archive member
字节改变、5950 个原样保留；所有 6859 个主要 compute 入口仍为 64 B 对齐。
受重编译对象的 `.text` 合计 42718030→42686378 B，减少 31652 B，**不是整个
程序的体积降幅**。本轮没有搜索代码布局。沿用的是既有累积探索线，不宣称这是
移除全部源码增量后的生产默认独立构建。

#### 三窗口 C100000 普通 AB/BA

固定 node030、CPU96–127、N=K=32、all-spin、Clang23/O3、64 B 对齐、ASLR 关闭。
先完成两窗口各 4 对；因整机收益较小，追加第三窗口 4 对验证重复性。共 **12 对、
24 次 C100000**，另有每窗口两次 C100 初始化短测。所有成功样本纳入，无 PMU、
batch probe 或诊断 walltime 混入。24 次长运行均通过 Difftest/终态、输入身份
及运行配置核验；C100 尚未执行指令差分，仅计初始化短测。

绝对值列是各版本 12 次运行的算术均值；变化列先逐对计算
`(candidate / baseline - 1) × 100%`，再取中位数，**不是两个均值之比**。

| 指标 | baseline 均值 | 本轮候选均值 | 配对变化中位数 | 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| walltime / s | 15.935000 | 15.849167 | **−0.597%** | 10/12，另 1 对持平 |
| Host / s | 15.900583 | 15.813167 | −0.617% | 11/12 |
| 全局 eval / µs | 50.361417 | 50.035833 | −0.675% | 11/12 |
| 全局 update / µs | 23.814417 | 23.811917 | −0.010% | 6/12 |
| p3 全步 eval / µs | 44.470417 | 42.988500 | **−3.087%** | 12/12 |
| p10 全步 eval / µs | 30.211750 | 30.386417 | **+0.664%** | 2/12 |
| p18 全步 eval / µs | 30.660083 | 30.596000 | −0.312% | 8/12 |

三个窗口的 walltime 配对中位数分别为 **−0.219% / −0.658% / −0.941%**；合并
AB / BA 顺序分组分别为 −0.408% / −0.752%，方向一致但幅度仍有波动。walltime
均值减少 85.833 ms，均值之比为 **−0.539%**，不要与表中的 −0.597% 混用。

本轮支持保留小幅整机收益，但不能把所有效果归给被删除的 slot 操作：状态字段
排序和重链接的访问上下文也发生变化，未做排他归因。p10 仍有小幅退化，不能说
“没有新增通知就保证每个分区都更快”；也不按 p10 名单禁用规则。

#### 回归、裁决与下一步

新增 `emit-grhsim-cpp-direct-bool-state-view` 专项：8 配置 × O0/O3，共 16 种
执行变体，每种运行 64000 个随机/边沿/使能步骤并检查输出；开启/packed 变体
运行 ASan/UBSan。覆盖完整/部分/缺失 reader、局部 alias、多写者优先级、旧状态
commit、重复初始化、128-bit concat、fullpass、选项优先级，以及真正开启
runtime profile 的路径。默认/关闭/开启/env/precedence 的 commit 函数文本
必须完全一致，默认与显式关闭生成结果也必须完全一致。

最终 **7 项 CTest 全部通过**：新增专项、bool-zero-group、scalar-concat-reduction、
local-shift-demanded-bit、wordwise-bool-pack，以及 GrhSIM/Verilator 两个 Repcut
package 测试。这是定向回归，不声称跑过仓库全部测试。

**保留本轮候选作为后续探索基线，生产默认仍不启用新选项。** p3 全步平均节省约
1.482 µs，但全局 eval 只节省约 0.326 µs；两者不是同一统计量，不能直接把差额
解释成某一种同步开销。本轮没有冻结新候选的瓶颈步标签，不能宣称“成为瓶颈时
也加速 3.09%”。下一步应在这个候选上重新定位真正最后完成的步及活跃 batch，
区分关键路径收益、非关键步收益和其他分区变化，再选择更广泛的标量物化/通知
合并模式；不继续扩大通知集合，不转向按分区筛选或布局搜索，也不外推到第二个
workload。生成、编译、普通性能测量及回归均已结束。

[复现脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/state_view_existing_readers_20261006.py)、
[结构与增量重放核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/state_view_existing_readers_20261006/prepare.json)、
[对象与二进制构建](../../build/repcut_grhsim_20260925/active_dispatch_20261003/state_view_existing_readers_20261006/build.json)、
[12 对完整汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/state_view_existing_readers_20261006/results.json)、
[7 项回归](../../build/repcut_grhsim_20260925/active_dispatch_20261003/state_view_existing_readers_20261006/regressions.json)、
[最终身份与样本核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/state_view_existing_readers_20261006/final_audit.json)。

### 7.57 布尔状态视图后的真实关键路径与活跃热点复核（2026-10-06）

本轮完成 §7.56 的后续诊断，**没有再增加生产优化，也没有改变生产默认值**。
普通 A/B 沿用上一节的同一对冻结 ELF：A 为正式 zero-group 探索线，B 再加
existing-reader bool-state-view；不是 GrhSIM/Verilator 对照。继续 node030
CPU96–127、NUMA1、Host105、N=K=32、all-spin、Clang23/O3、64 B compute
入口对齐、进程级 ASLR off、C100000，不设核空闲率门槛，不开展布局搜索。

首先发现并修正 §7.55 的标签选择错误，详见该节后的增量勘误：AB/BA 每对末次
运行混入了 Verilator。旧原始记录不改写；此前“p3 占 97.33% 瓶颈步”的结论
撤回。只用原始 GrhSIM 数据重算为 34.88%。这个错误不影响普通 walltime A/B。

#### 独立发现与验证：瓶颈按半周期轮换

对 A/B 各做 4 次发现运行、4 次独立验证运行，均按 AB/BA 交错。每次采样
`step > 128 && step % 127 <= 1`，得到 3148 个不同 step，实际 clock=0/1 各
1574 个。worker 探针复用原有 eval 起止时间戳；按**同一版本四次运行的各分区
完成时刻中位数**确定每个 step 的最后完成者，A/B 分别选标签，绝不混用。
下面条件 eval 均值来自之后的验证运行，不用验证时间重新挑选集合。

| B 发现集合的分区 | 唯一步数 | 占采样步 | clock=0 / 1 | 独立验证中该分区的条件 eval 均值 / µs |
| --- | ---: | ---: | ---: | ---: |
| p3 | 1124 | 35.71% | 472 / 652 | 42.881 |
| p18 | 503 | 15.98% | 2 / 501 | 49.626 |
| p10 | 379 | 12.04% | 0 / 379 | 49.337 |
| p6 | 377 | 11.98% | 372 / 5 | 55.102 |
| p29 | 332 | 10.55% | 332 / 0 | 52.993 |
| p26 | 240 | 7.62% | 240 / 0 | 53.579 |
| p25 | 74 | 2.35% | 74 / 0 | 53.971 |
| p27 | 60 | 1.91% | 60 / 0 | 52.714 |

其余分区合计 59 步。以上是稀疏诊断、固定集合上的均值，不是全程平均，
也不表示该分区在四次验证的每一步都最后完成。独立验证重新计算标签仅用于
稳定性检查：p3 为 1116/3148（35.45%），与发现标签逐步相同的比例为 94.12%；
没有用这些新标签回选上表。旧数据修正、新发现和独立验证都支持 p3 约占三分之一，
而非几乎全部。p18/p10 主要在 clock=1 拖住整步，p6/p29/p26 主要在 clock=0。

因此，`max(part 的全步平均 eval)` 与每步 `max(part 完成时刻)` 不是同一指标。
p3 全步均值最大，并不意味着减少它的每一微秒都能减少 Host 等待；当 p6 或 p29
更慢时，p3 提前结束只会增加其等待时间。最后完成者还取决于启动偏移，不能仅按
eval duration 最大者代替。

#### 探针代表性检查：不能用诊断版硬分摊普通收益

第一版逐线程时间戳采样只替换 common/eval wrapper 两个对象，模型 compute
对象不变、6859 个入口仍 64 B 对齐，但重链接改变了函数绝对位置。它**没有复现**
普通二进制中的 p3 改善：独立验证的全部采样步 p3 为 43.945→43.970 µs，正常
eval 阶段为 50.038→50.175 µs。因此，其起步偏移/其他分区/收尾的数学分解虽然
可以加和，不能作为普通约 3% p3 收益的因果分摊。

为减少 worker 执行路径干扰，另做 4 对 AB/BA：只改 common 对象，由 Host 在
step 前后读取已有各分区累计 `eval_ns` 并取差值；worker wrapper 和全部模型对象
字节不变，不增加 worker 内时钟调用。标签仍固定使用前面的 B 发现集合。

| Host-only 诊断集合 | 步数 | A 的 p3 eval / µs | B 的 p3 eval / µs | 对全部采样步均值变化的加权贡献 / µs |
| --- | ---: | ---: | ---: | ---: |
| p3 被标为最后完成者 | 1124 | 42.590 | 41.728 | −0.307 |
| 其他分区被标为最后完成者 | 2024 | 44.126 | 43.177 | −0.610 |
| 全部 | 3148 | 43.577 | 42.660 | −0.917 |

加权贡献严格按 `集合步数 / 3148 × (B集合均值 − A集合均值)` 计算；两行相加
等于全部均值变化。**该诊断中约 66.48% 的 p3 均值减少，落在标签为其他分区
瓶颈的步骤**。这与“p3 平均明显下降，但全局下降较小”的机制相符。

但它仍不是普通程序的精确收益分解：Host-only 探针也使 p6/p10/p18 等出现与
普通运行不同的相对变化，且未测 worker 启动偏移；其标签来自另一种探针。
不能把 66.48% 当作普通 walltime 的浪费比例，不能据此声称唯一根因已闭合，
也不能声称普通关键步已被证实加速 3.09%。目前可靠结论是**瓶颈轮换限制局部
收益传递**；准确贡献仍对测量方式敏感。

#### 当前候选的活跃 batch：热点从大分区收敛到具体模式

按 B 发现集合中的瓶颈次数自动选前五分区 p3/p18/p10/p6/p29，覆盖 2715/3148
步（86.25%）。只对当前 step 标签所指分区记录非空 compute 调用时间，两次
C100000 均通过 Difftest。只替换框架/模型 eval-dispatch wrapper，compute
函数体对象不变；空调用不计时，全部主要 compute 入口继续 64 B 对齐。
下面的 µs 是**带 batch 探针、每个固定集合 step 累计的活跃调用时间**，分母是
该分区同集合的全部活跃 batch 时间，不是普通 eval 或 Host 时间。

| 分区 | 热点 batch | 活跃调用时间 / µs | 占该分区活跃 batch 时间 | 源码核对后的模式 |
| --- | --- | ---: | ---: | --- |
| p3 | b46 | 1.330 | 3.23% | 宽状态读取与跨分区结果拼接，热点整体分散 |
| p6 | b184 | 7.243 | 13.05% | 动态取位、宽中间结果与超宽输出组装 |
| p10 | b15 / b17 | 3.149 / 2.921 | 合计 13.36% | 大量状态字段读取和跨分区输出拼接，混有少量其他逻辑 |
| p18 | b18 / b195 | 1.089 / 0.763 | 合计 4.07% | 混合标量计算、读取与变化传播，单块占比较低 |
| p29 | b138 / b137 / b139 | 6.085 / 4.885 / 3.809 | 合计 27.47% | 布尔结果物化、变化检测/合并通知，以及长布尔 OR 归约 |

源码分类脚本的 `slice/mixed`、`control/mixed` 只是“文件中出现了哪类 op”的
粗分类，不能当成耗时归因。例如 p6/b184 仅含一项显式 slice 就被分入前者，
p10/b17 因少量 DPI/op 被分入 control，但主体源码是结果打包。本轮继续核对了
真实片段，而非按分类名字选优化：

- p6/b184 的最大源码块 SN1455 包含 **794 个** `grhsim_lshr_bit<128u,0u>` 调用，
  最终组装 `endpoint$in` 的 1239-word 数组。此前 demanded-bit 优化已在生效，
  不是重新发现“完整 128-bit 右移只读一位”。这里仍有许多取位及中间拼接；代码
  大小和调用计数本身不能证明究竟是算术、访存还是寄存器压力占主导。
- p10/b15 的 SN131、b17 的 SN146 分别读取 6759/6027 项显式寄存器 read op，
  组装 558/502-word 跨分区 bundle。这些是 **eval 内打包**，不能混称 Host
  update 的复制耗时。两个 batch 的活跃调用数约为 2，不代表每个 supernode
  都执行两次；§7.52 已证明纯打包块不能凭 batch 次数判为无效重复。
- p29/b138 含 4088 项显式 `kLogicAnd`。典型块有 511 项 AND、512 次逐值变化
  比较，再合并通知；当前 exact-mask 优化已将共同 reader 的通知集中到块末。
  它同时保留长的 bool OR 归约，代表块仍有 **482 个 `||`**。eager bool 规则
  只接受已经求值的简单 bool 操作数/别名，内联后的嵌套表达式不在其范围内。
  这不是此前已移走/改成位图的长常量 mux 末端链，不能把旧 mux 收益重复计算。

三个方向的热点 batch 都没有 §7.56 新增的 direct-bool-state-view 标记。
这只说明新规则未直接改写这些热点块，不表示它们绝不受状态排序或其他函数
变化的间接影响，也不表示整个 part 未被修改。

进一步检查**当前冻结候选的最终 ELF**，按函数 symbol 的地址/大小截取反汇编，
排除符号外对齐 NOP，得到下面的静态数量：

| 函数 | 指令数 | 条件跳转 | 含 `%rsp` 操作数的指令 |
| --- | ---: | ---: | ---: |
| p6/b184 | 42783 | 1496 | 13176 |
| p10/b15 | 29997 | 14 | 0 |
| p10/b17 | 30103 | 17 | 90 |
| p29/b137 | 28418 | 540 | 8226 |
| p29/b138 | 36951 | **16** | **15557** |
| p29/b139 | 23252 | **15** | **9762** |

p29/b138 的 16 个跳转均围绕 batch/supernode 活动位控制；源码长 `||` 链没有
留下对应的逐项短路跳转。因此，**不能把 p29 热点重新归因于这些源码短路符号，
也没有依据仅为它扩大 bool-eager**。反而 b138/b139 仍有大量栈寻址，是后续
检查中间结果存活期与归约组织的具体线索。静态 `%rsp` 引用包含多种栈访问，
不等于动态 spill 次数、cache miss 或已证明的停顿占比；p10 也不能套用相同解释。

下一项优先尝试**多输出 bool 的生成与后续纯 OR 归约融合**：在依赖、别名和
快照时刻允许时，随各结果生成逐步累计归约，避免大量结果长时间存活后再归约；
原可见输出写回、旧值比较和 reader 通知继续保留。它不是只把 `||` 换成 `|`，
也不是 §7.47 已试过的“仅重排现有局部声明”。先以通用 IR 结构约束候选，再
用当前固定集合与普通 AB/BA 判断是否真的减少运行成本，不以编译结果或分区
编号筛选。p6 的拼接中间量及 p10 的打包作为后续备选；不重新无条件打开旧的
宽泛 use-order，不取消 Difftest/debug 语义。**新融合方案本轮尚未实现，不能
宣称已有收益。**

#### 无诊断探针的普通复测与汇总

最后用原始 A/B ELF 另做 4 对普通 C100000 AB/BA，不带上述新探针。该窗口
walltime 15.9550→15.7625 s（均值），配对中位数 **−1.252%，4/4 更快**；p3
全步 eval 44.7685→42.8455 µs，配对 **−4.646%，4/4**。幅度大于上一节，不能
用新窗口替换旧窗口。将旧 12 对和本次 4 对的逐对比例合并后：

| 普通指标 | A 的 16 次均值 | B 的 16 次均值 | 配对变化中位数 | 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| walltime / s | 15.940000 | 15.827500 | **−0.784%** | 14/16，另 1 对持平 |
| Host / s | 15.905188 | 15.792625 | −0.779% | 15/16 |
| 全局 eval / µs | 50.363813 | 49.972750 | −0.759% | 15/16 |
| 全局 update / µs | 23.844313 | 23.790250 | −0.179% | 10/16 |
| p3 全步 eval / µs | 44.544938 | 42.952750 | **−3.626%** | 16/16 |
| p10 全步 eval / µs | 30.200813 | 30.331125 | +0.619% | 3/16 |

变化仍为逐对 `(B/A − 1) × 100%` 的中位数，不能由两列均值直接相除得到。
合并 walltime 均值减少 112.5 ms，其均值比为 −0.706%，与 −0.784% 是不同
统计量。所有功能通过的普通样本均保留，未将 PMU/稀疏探针的 walltime 混入。

本轮共 **34 次 C100000、9 次 C100**：发现 8、独立验证 8、Host-only 8、活跃
batch 2、普通复测 8 次长运行。长运行全部通过 Difftest、终态/配置/输入身份
检查；C100 仅验证初始化。另完成两种探针的 ASan/UBSan 小测试与标签版本选择
检查。生产 emitter SHA256 仍为
`340737dc1e46bbcafad0d30c3f31419bf6ddb86a3a5b9654f72aed819b156cda`，本轮没有
修改它；普通二进制也与 §7.56 完全相同。§7.56 的 7 项 CTest 本轮未重复执行，
不将其计入新增测试。

[诊断复现脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/state_view_critical_path.py)、
[批次探针脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/state_view_critical_batches.py)、
[独立标签](../../build/repcut_grhsim_20260925/active_dispatch_20261003/state_view_critical_20261006/labels.json)、
[逐线程验证数据](../../build/repcut_grhsim_20260925/active_dispatch_20261003/state_view_critical_20261006/timing_results.json)、
[Host-only 复核](../../build/repcut_grhsim_20260925/active_dispatch_20261003/state_view_critical_20261006/host_results.json)、
[活跃热点及源码身份](../../build/repcut_grhsim_20260925/active_dispatch_20261003/state_view_critical_20261006/critical_batches/hotspots.json)、
[新增 4 对普通结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/state_view_critical_20261006/ordinary_recheck/summary.json)、
[完整汇总、16 对普通数据与最终核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/state_view_critical_20261006/final_report.json)。

### 7.58 布尔结果生成与 OR 归约的紧凑循环原型（2026-10-06）

完成上一节提出的融合实验。保留的方案把结构相同的布尔 AND 输出、逐值变化
检测和后续 OR 汇总放进一个有序短循环。全工程按统一结构规则选择，**没有按
part、模块、信号或编译后 profile 选择启用范围**。两轮共 8 对普通 C100000
AB/BA 的 walltime 全部改善，配对中位数 **−0.631%**；p29 全步 eval 为
**−7.126%**。当前仍是生成 C++ 上的通用规则原型，**尚未迁入正式 emitter，
也未改变生产默认**。

本轮 A 是 §7.56/§7.57 的 existing-reader bool-state-view 候选，即
`state_view_existing_readers_20261006/candidate/emu`，SHA256：
`d17f0ab8fa2bcb6bf5e6e8c70b5560843b1c7493bfc3dd8bc939dce5543f8c33`。
B 只叠加本规则，SHA256：
`d374b78b405f3ced763f625c6abd32afbc809fc982c84ab625e3bda92fa23a7b`。
二者都是 GrhSIM；本轮没有重新测 Verilator，也不把前几节收益合并到本增量。
继续 node030 CPU96–127、NUMA1、Host105、N=K=32、all-spin、Clang23/O3、
全部 compute 入口 64 B 对齐、`setarch -R`，不设核空闲率门槛。

#### 规则与语义边界

候选区域必须由连续、无外部副作用的布尔输出写回及其后的纯 OR 汇总组成。
先检查布尔类型、存储别名、输出地址唯一性和 OR 局部变量的完整使用范围；
被删除的局部归约值不得被其他输出或后续语句使用，也不得跨越影响快照的写入。
再从区域内提取连续不少于 32 项的简单 `bool AND bool` 输出，且每项的
deferred-reader 通知集合完全相同。其他表达式保留原代码，仍在原位置参与计算。

每组生成一个只读的输入/输出索引表，交给共享的 `grhsim_bool_and_reduce`。
循环依次完成以下工作：

```text
next = slots[left] AND slots[right]
changed |= (slots[target] != next)
slots[target] = next
reduced |= next
```

循环返回 `changed` 和 `reduced`：前者 OR 到原来的 reader 累计标志，后者与
未融合的叶子在原归约位置合并。所有可见输出写回、旧值比较和通知对象均保留；
只合并具有完全相同 reader 集合的通知。循环保留生产者次序，允许后项读取前项
已经写出的值；组内输出地址不重复，因此先累计的输出不会在原汇总点前被覆盖。
未融合叶子仍在原位置读取，未引入提前读取其旧值的快照问题。

共享函数使用 `noinline`，并禁止循环展开、向量化和交错展开，以保持中间值
数量有界。这是本原型的固定生成策略，不根据某个已编译函数的表现决定是否使用。
全工程扫描 **6859 个 compute 源文件**，改写 **16 个文件、90 组、46161 个
输出**：p15/p28/p29 分别有 25/30/35 组。其余区域因结构不满足而保持原样。
修改 archive 的 16 个 compute 成员，**7438 个成员保持原字节**；6859 个
compute 入口仍全部 64 B 对齐。输入来自冻结的完整来源映射，并非只扫描热点。

#### 普通 walltime：两轮结果都保留

普通测试不带本轮新增的 batch/PMU 探针，保留现有阶段与分区计时。两轮之间
完成独立的条件 batch 和 PMU 诊断，没有把诊断程序 walltime 混入下表。

| 普通窗口 | A walltime 均值 / s | B walltime 均值 / s | 配对变化中位数 | 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| 第一轮 | 15.8175 | 15.6600 | −1.136% | 4/4 |
| 第二轮 | 15.8125 | 15.7425 | −0.411% | 4/4 |
| 合并 | 15.8150 | 15.70125 | **−0.631%** | **8/8** |

| 合并普通指标 | A 的 8 次均值 | B 的 8 次均值 | 配对变化中位数 | 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| Host / s | 15.781500 | 15.667625 | −0.610% | 8/8 |
| 全局 eval / µs | 49.834875 | 49.117125 | **−1.386%** | 8/8 |
| 全局 update / µs | 23.877375 | 23.905375 | −0.077% | 4/8 |
| p3 全步 eval / µs | 42.598875 | 42.937375 | +0.901% | 0/8 |
| p15 全步 eval / µs | 13.905125 | 12.946500 | **−6.826%** | 8/8 |
| p28 全步 eval / µs | 12.514250 | 12.879125 | **+2.820%** | 0/8 |
| p29 全步 eval / µs | 16.106125 | 14.944375 | **−7.126%** | 8/8 |

百分比仍为每对 `(B/A − 1) × 100%` 的中位数。walltime 均值减少 **113.75 ms**，
均值比为 −0.719%，与 −0.631% 是不同统计量；update 的均值略升与配对中位略降
也不矛盾，不能把接近零的后者当成通信优化。p28 明确回退，p3 也未改善；没有
按 part 手动禁用规则来掩盖它们。当前保留依据是最终 walltime 的小幅一致收益，
不是所有分区都变快，也不是最大分区均值下降。

#### 固定瓶颈步骤：改善确实落到 p29 的活跃热点

沿用 §7.57 **独立发现运行**中布尔状态视图版本的标签，不用本轮时间重新选择。
对原先 332 个 p29 最后完成的采样 step 做 4 对 AB/BA，均在 clock=0。
两版复用完全相同的 batch 探针对象，compute 对象与各自普通程序一致。
逐 step、逐 batch 核验调用次数、活跃调用数、all-on 数及活动位数量完全相同。

| 同一固定集合上的诊断指标 | A 均值 / µs | B 均值 / µs | 配对变化中位数 |
| --- | ---: | ---: | ---: |
| p29 条件 eval | 57.445512 | 54.377167 | **−5.379%** |
| p29/b137 活跃调用累计 | 4.828067 | 4.144111 | −13.813% |
| p29/b138 活跃调用累计 | 6.039586 | 4.662762 | −23.332% |
| p29/b139 活跃调用累计 | 3.779146 | 2.902123 | −23.088% |

三个 batch 每个集合 step 合计减少 **2.9378 µs**，p29 条件 eval 减少
**3.0683 µs**，前者为后者的 **95.75%**。这只是同一探针内的时间差核算，
支持热点与改写目标对应；不能把 95.75% 当成普通 walltime 的因果归因。
batch 计时会扰动执行，未据此宣称普通程序的 p29 瓶颈占比已下降到某个数值。
探针下 p3 条件 eval 略降，而普通版 p3 略升，也说明不能把探针的全部分区变化
直接推广到普通运行。完整前五分区条件结果保留在汇总 JSON 中。

#### 机器码与 PMU：减少展开代码，代价是更多循环指令

改写的 16 个对象可执行节总量由 **2167542→244650 B**。最终 ELF 的 `.text`
由 **94165746→92241842 B**，`.rodata` 由 **4945632→5500400 B**；新增只读
索引表有实际空间/读取代价，不能只报告代码缩短。

以 p29/b138 为例，调用方从 219726 B/36951 条静态指令变为 1542 B/362 条，
显式含 `%rsp` 的指令从 15557 降到 2；但主要工作移入了共享循环，不能据此
声称动态指令减少 99%。最终共享函数为 **78 B、26 条静态指令、无显式栈寻址**，
循环仍逐项读取、比较、写回和归约。p29/b137 还包含未融合逻辑，改善幅度较小。

另对原始普通 ELF 做 4 对低频、仅本进程及其线程的用户态 IP 采样；无丢样或
throttle。每项按事件 period 累加，而非直接比较不等长运行的样本百分比。
**改写调用方与共享 helper 合并计账**，未把搬到 helper 的工作当成消失。

| 采样归属范围 | cycles 配对中位变化 | instructions | frontend 事件 | icmiss 事件 |
| --- | ---: | ---: | ---: | ---: |
| 16 个改写 compute + 共享 helper | **+3.181%** | **+61.296%** | −76.255% | −77.632% |
| 全部模型函数（含 helper） | −1.648% | +1.040% | −4.725% | −7.255% |

因此，本规则不是减少全部动态工作量：索引加载、循环控制引入额外指令，改写
区域合计 cycles 没有下降；同时，大段展开代码变成可复用的短循环，前端压力
显著降低。结合固定集合上的 batch 改善和普通 walltime，支持保留该折衷。
共享 helper 服务 p15/p28/p29，当前 IP 记录不能把其成本逐 part 分摊，也不能
将上述合计 cycles 当成 p29 的条件 cycles。重链接仍会搬移其他函数，即使全部
入口保留 64 B 对齐；未改写函数的变化可能含布局/缓存等间接影响，本轮未作
新的布局搜索，也没有把普通总收益全部归给栈访问或某一种 cache miss。

#### 验证与保留范围

8 类独立参考测试各做 12000 组输入、3 次重复 eval，分别用 Clang23 O0/O3
及 ASan/UBSan 通过。比较完整输出数组和原通知标志，覆盖旧输出非零、预置
通知、未激活 eval、外部叶子变化、部分输出参与 OR、生产者顺序依赖，以及
两段循环之间夹一个不融合操作。负向检查覆盖小组、不同 reader、重复目标、
副作用边界、快照写入和局部值逃逸。

保留候选及其基线共 **32 次 C100000、8 次 C100**：普通 16、固定集合 batch 8、
PMU 8 次长运行；长运行全部通过 Difftest、终态签名、线程配置、ASLR 与输入身份检查。
C100 只作初始化检查。编译前逐个重编译冻结基线对象，核对可分配节及 relocation
内容；修改后核对仅目标成员变化，改写涉及的全部源文件身份在最后再次校验。

生产 `grhsim_cpp.cpp` 仍为
`340737dc1e46bbcafad0d30c3f31419bf6ddb86a3a5b9654f72aed819b156cda`。
本节记录通用生成代码原型及其通过的数据，未新增正式选项、未启用生产默认。
下一步适合把该结构识别迁到带类型/依赖信息的 emitter 中，再做 fresh 全量生成
对照；若继续减少循环索引成本或处理 p28 的回退，也应采用通用结构规则，不能
通过手动分区白名单决定启用范围。当前只有 XiangShan 的性能证据，不宣称其他
workload 已获益。

[原型与全图扫描](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_producer_reduce_compact.py)、
[纯 OR/别名合法性检查](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_producer_reduce.py)、
[独立语义测试](../../build/repcut_grhsim_20260925/active_dispatch_20261003/test_bool_producer_reduce_compact.py)、
[条件计时与核验脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_producer_reduce_report.py)、
[原始 ELF 采样脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_producer_reduce_perf.py)、
[第一轮普通结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_producer_reduce_compact_20261006/ordinary_1/summary.json)、
[第二轮普通结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_producer_reduce_compact_20261006/ordinary_2/summary.json)、
[固定集合数据](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_producer_reduce_compact_20261006/critical_batches/results.json)、
[PMU 汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_producer_reduce_compact_20261006/ordinary_perf/results.json)、
[完整汇总与最终核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_producer_reduce_compact_20261006/final_report.json)。

### 7.59 短循环索引压缩、逐 worker 归因与正式 emitter（2026-10-06）

继续 §7.58 的通用布尔生产者/OR 归约融合。先补齐共享 helper 的线程归属，
再验证连续目标地址与窄输入偏移，最后迁入正式 IR emitter。环境沿用 node030
CPU96–127、NUMA1、Host105、N=K=32、all-spin、Clang23/O3、compute 入口
64 B 对齐、ASLR 关闭；不增加核空闲率门槛。本节各阶段的 A/B 单独标明，
不把不同窗口的收益相加。

#### 补充上一节的 helper 归属

§7.58 的原始 `perf.data` 实际保存了线程 ID。重新解码后，以同一 worker 的
compute 符号确定所属分区，并要求每个 helper 线程只能映射到一个分区。
四对记录中 helper 全部唯一归属于 p15/p28/p29，没有丢弃无法归属的 helper。
此处复用原始采样，没有增加一轮负载；更正上一节“当前 IP 记录不能逐 part
分摊”的限制。统计仍是按事件 period 累加的低频采样估计，不是瓶颈条件 PMU。

| 改写 compute 与本 worker 的 helper 合计 | cycles 配对中位变化 | instructions | frontend | icmiss |
| --- | ---: | ---: | ---: | ---: |
| p15 | −13.501% | +36.178% | −72.110% | −64.075% |
| p28 | **+29.614%** | **+93.371%** | −85.216% | −86.817% |
| p29 | −18.425% | +34.041% | −68.756% | −77.618% |

这解释了为什么上一节的合计 cycles 略增，而 p29 的活跃热点仍变快：三个
worker 的变化方向不同。原展开代码也不等价：p28/b142 的 26999 条静态指令中，
显式含 `%rsp` 的仅 160 条；p29/b138 为 36951 条中 15557 条。p28 原先的栈访问
已少，改成索引循环时可抵消新增索引/循环指令的收益更小。三者典型组的两列
输入均逐项唯一，没有发现可归因于“重复输入值复用”的证据。栈指令数是静态
线索，不能直接换算动态耗时；采样下 p28 全模型 cycles 的变化也不能替代普通
运行的 eval 百分比。

#### 保留的地址压缩规则与原型直接复测

保持原生产顺序，把每组目标地址划为连续区段：长度至少 32 的区段以基址加
循环下标寻址，较短区段保留原顺序的标量写回。两个输入列分别减去自己的
最小索引，只有各自跨度均不超过 65535 时才用 `uint16_t`，否则回退到
`uint32_t`；无长连续段的组仍能使用完整三索引表。没有 `restrict` 假设，
前项输出被后项读取时仍按原次序执行。

原 90 组、46161 项中，**46101 项使用连续目标寻址，60 项保留标量形式**；
连续部分 **42987 项使用 16 位输入偏移，3114 项使用 32 位输入索引**。
表中索引的有效字节数从 **553932→196860 B**，下降 64.46%；这不包括对齐。
对应原型 ELF `.rodata` 从 **5500400→5142880 B**，`.text` 从
**92241842→92246578 B**。代码没有随表缩短，性能结论取自实际运行。

这里 A 是 §7.58 的短循环原型 `d374b78b…`，B 只叠加上述地址压缩。
两轮各 4 对普通 C100000，全部纳入，包括第一轮的一对 walltime 回退：

| 指标 | A 的 8 次均值 | B 的 8 次均值 | 配对变化中位数 | B 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| walltime / s | 15.883750 | 15.808750 | **−0.786%** | **7/8** |
| Host / s | 15.848375 | 15.773875 | −0.776% | 7/8 |
| 全局 eval / µs | 50.207875 | 49.662875 | **−1.074%** | **8/8** |
| 全局 update / µs | 23.804750 | 23.978250 | +0.032% | 4/8 |
| p3 全步 eval / µs | 43.879125 | 43.550750 | −0.598% | 7/8 |
| p15 全步 eval / µs | 12.917500 | 12.829625 | −1.077% | 7/8 |
| p28 全步 eval / µs | 12.827250 | 12.116500 | **−5.527%** | **8/8** |
| p29 全步 eval / µs | 15.620750 | 14.812500 | **−5.142%** | **8/8** |

第一轮与第二轮 walltime 配对中位分别为 −0.630%/−0.786%。合并均值减少
75 ms，均值比 −0.472%，与配对中位 −0.786% 不是同一统计量；不能省略首轮
较慢样本来使两者靠近。update 没有可确认的收益，未改写 p3 的变化仍可能包含
重链接、缓存及并行运行的间接影响，本轮不作布局参数搜索。

地址规则的 22 种配置已在 Clang23 O0/O3、ASan/UBSan 下通过，比较完整状态、
归约结果及 changed 返回值，覆盖连续段边界、小间隙、别名与顺序依赖、65535
可压缩边界、65536 回退、高输入基址、短组与非连续组。

正式实现增加默认关闭的 `bool_producer_reduce` attribute / 环境变量
`WOLVRIX_GRHSIM_BOOL_PRODUCER_REDUCE`，使用类型、完整 use-list、存储别名、
快照与 deferred-reader 证明，不使用生成 C++ 的正则选择。未融合的事件叶子
保留在原 OR 位置读取，不能因 reset 同时承担事件用途而把整条合法锥排除；
被合并的输出本身仍不得是事件值。以下分别记录正式生成与实测，不用原型
数据代替正式版本数据。

#### 正式 emitter、fresh 生成与兼容性

实现位于 `wolvrix/lib/emit/grhsim_cpp.cpp`，新增聚合测试注册到 CTest，选项及
约束写入 `wolvrix/docs/emit/grhsim-scheduling.md`。显式 attribute 优先于环境
变量；默认关闭。纯布尔 AND 的有序计算、逐输出写回、旧值比较和完整 reader
通知均保留，只有私有 OR 中间锥被吸收；存在外部使用、副作用或快照覆盖时
回退。普通、packed、direct-reader 和 profile 路径都经过验证，fullpass 保留
原实现。没有按 part、模块、变量或编译结果选择启用位置。

以同一冻结的 `partitioned.json` 对全部 32 个分区分别 fresh 生成 on/off：
off 的 **7552 个生成源文件/头文件与上一条 fresh 基线逐字节一致**，因此关闭
选项不引入新的运行代码。on 自动覆盖 **17 个文件、96 组、49239 个输出**；
p15/p28/p29 分别为 27/32/37 组。相比文本原型多 6 组：IR 能证明其中夹杂
其他未融合操作的 OR 锥仍合法，不需要文本区域全部连续。这里是覆盖范围扩展，
不能把正式版当作原 90 组原型的逐字节搬迁。

正式版 46044 项用 16 位输入偏移，3114 项用 32 位索引，81 项保留标量，
索引有效载荷 **209088 B**。headers、commit、wrapper 保持不变；旧探索线中
尚未进入 emitter 的通用改写按冻结差异原样重放，并核对重放到旧 fresh 源码
能完全还原旧候选。因此此处完成的是本规则的正式化，尚不代表所有历史探索
优化都已成为无后处理的生产默认。

构建采用 fresh 全量生成、对象增量重编译：17 个改写对象更新，另 **7437 个
archive 成员不变**。改写前先重编译相应基线源码，核对可分配节和 relocation
内容与冻结对象一致；改写对象可执行节总量 **2201630→168263 B**，最终
6859 个 compute 入口仍全部 64 B 对齐。这不是重新编译全工程全部对象，
也不把静态代码缩小当作动态工作量同比下降。

新增 emitter 检查覆盖 10 种配置；其中 7 种实际运行模式各用 O0/O3、ASan/UBSan
执行，共 **14 次 sanitizer 运行**。每次两种初始化、2048 步、每步三次 eval，
以独立参考逐项比较输出、reader 状态和归约；覆盖交错 OR、事件残余叶子、
顺序依赖、不同 reader，以及短组、OR 中间值逃逸和副作用的拒绝路径。
默认/off 与环境变量优先级检查通过。另 5 项既有 CTest 回归全部通过，包括
布尔状态视图、零值组保护、concat reduction、GrhSIM/Verilator repcut package。

本轮 emitter SHA256 为
`d6962e0ba4673e483398386304c798e8fa075e0e4db38592de2e55b79843d57b`；
正式候选 ELF 为
`4dc96b1adc84b3f095b0b43c472d6f95e0432d321c72ea59cb5b947fe775463f`。

#### 正式版与融合前基线：8 对普通 C100000

A 为 §7.57 的布尔状态视图候选 `d17f0ab8…`，尚无生产者/OR 融合；B 为上述
96 组正式版。两个窗口各 4 对 AB/BA，中间进行独立瓶颈诊断；下表只统计普通
程序，不混入诊断程序 walltime。两个回退样本完整保留。

| 普通指标 | A 的 8 次均值 | B 的 8 次均值 | 配对变化中位数 | B 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| walltime / s | 15.856250 | 15.821250 | **−0.312%** | **6/8** |
| Host / s | 15.823250 | 15.786625 | −0.335% | 6/8 |
| 全局 eval / µs | 50.071125 | 49.789500 | **−0.525%** | **8/8** |
| 全局 update / µs | 23.734875 | 23.851375 | +0.082% | 3/8 |
| p3 全步 eval / µs | 43.500625 | 43.919500 | **+1.005%** | 1/8 |
| p15 全步 eval / µs | 13.951250 | 12.539250 | **−10.082%** | **8/8** |
| p28 全步 eval / µs | 12.446750 | 11.560625 | **−7.072%** | **8/8** |
| p29 全步 eval / µs | 16.006750 | 13.996625 | **−12.667%** | **8/8** |

第一/第二窗口 walltime 配对中位为 −0.312%/−0.126%，分别 4/4、2/4 更快。
合并均值减少 **35 ms**，均值比 −0.221%；百分比列是各对 `(B/A−1)×100%`
的中位数，不是均值比。三个直接改写分区一致变快，旧 p28 回退已被修复；
全局收益仍小，不能据此宣称最终 walltime 大幅改善。p3 对象和 update 实现
没有改变，其耗时增加可能涉及重链接或并行运行的间接效应，本轮没有独立
隔离原因，也没有增加布局参数搜索。

#### 正式版与地址压缩原型直接对照

为检查迁移是否保住原型收益，另做 4 对普通 C100000，A 为本节 90 组地址
压缩原型，B 仍为同一正式 ELF。不能通过相加不同时间窗口的百分比代替本表。

| 普通指标 | A 的 4 次均值 | B 的 4 次均值 | 配对变化中位数 | B 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| walltime / s | 15.800000 | 15.755000 | **−0.253%** | **4/4** |
| Host / s | 15.761500 | 15.719500 | −0.232% | 4/4 |
| 全局 eval / µs | 49.694250 | 49.503250 | −0.379% | 4/4 |
| 全局 update / µs | 23.813000 | 23.908000 | +0.381% | 1/4 |
| p3 全步 eval / µs | 43.767250 | 43.232250 | −1.267% | 4/4 |
| p15 全步 eval / µs | 12.745500 | 12.555500 | −1.337% | 4/4 |
| p28 全步 eval / µs | 11.903000 | 11.592000 | −2.497% | 4/4 |
| p29 全步 eval / µs | 14.713750 | 14.058500 | −4.383% | 4/4 |

这轮支持保留正式版作为后续探索基线：新覆盖和 emitter 生成没有使总时间
回退。它仍只是一轮 4 对的迁移检查，不把 −0.253% 当作跨环境保证；p3 在
不同 A/B 间方向不同，也进一步说明不能仅凭对象是否改写来推断最终耗时。

#### 刷新瓶颈分布：p29 已明显退出，p3/p18/p6/p10 接替

对融合前基线与正式版分别做 4 对发现运行，按每个采样 step 的 **worker
完成偏移＝开始偏移＋eval 时长** 的跨运行中位数选最后完成者。每版固定
3148 个采样步骤，两个半周期各 1574 个；随后用另外 4 对运行验证，标签
冻结后不再用验证时间选择。探针只加在 wrapper，模型对象与普通版一致。

| 分区 | A 发现标签数 | B 发现标签数 | A 发现占比 | B 发现占比 | A 验证实际占比 | B 验证实际占比 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| p3 | 1019 | 1227 | 32.37% | 38.98% | 31.25% | 35.68% |
| p18 | 523 | 504 | 16.61% | 16.01% | 16.58% | 17.60% |
| p6 | 482 | 489 | 15.31% | 15.53% | 14.83% | 15.34% |
| p10 | 362 | 388 | 11.50% | 12.33% | 11.81% | 11.71% |
| p26 | 318 | 283 | 10.10% | 8.99% | 9.49% | 11.16% |
| p29 | 290 | 104 | **9.21%** | **3.30%** | **9.51%** | **3.12%** |

验证实际占比是四次验证各自最后完成者计数的均值除以 3148，与发现阶段的
跨运行中位标签不同，故两列不要求相等。p28 没有发现标签，不给它编造一组
“瓶颈时平均 eval”。以下固定 **A 的发现标签集合**，只在独立验证中计时，
两版使用完全相同的步骤：

| 分区 | 固定步骤数 | A 条件 eval 均值 / µs | B 条件 eval 均值 / µs | 配对变化中位数 |
| --- | ---: | ---: | ---: | ---: |
| p3 | 1019 | 41.435178 | 41.906422 | +1.276% |
| p18 | 523 | 48.759940 | 49.788183 | +2.308% |
| p6 | 482 | 54.692623 | 54.035694 | −1.213% |
| p10 | 362 | 48.178801 | 48.730131 | +1.130% |
| p26 | 318 | 53.436639 | 52.336274 | −1.980% |
| p29 | 290 | **52.836941** | **45.496922** | **−13.881%** |

p29 改善既体现为同一步骤上的条件 eval 缩短，也体现为独立验证中更少最后
完成；不是只缩短了不影响全局的空闲阶段。但 p3/p18 等接过了关键路径，
局部改善不能线性换算成总 walltime。以上时间均为探针诊断，不当作普通
程序的精确条件耗时，也不与 Verilator 的其他窗口直接比较。

本阶段普通对照 24 次、发现/验证 16 次，合计 **40 次 C100000**，全部通过
Difftest、终态签名、绑核/线程、ASLR、输入身份与阶段计时一致性检查。
汇总时再次核对 emitter、生成库、输入图、改写源码、基线/候选 ELF 和 archive
身份，均未改变。下一步不宜继续围绕 p29 增加变体；先在正式候选重新确认
p6/b184 的活跃 batch 占比，再针对动态位提取和宽位拼接寻找通用规则。
p3 仍占最多最后完成步骤，须持续跟踪；当前尚未有证据把它的主要成本归到
同一种可统一改写的操作。

[索引规则与原型测试驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_reduce_addressing.py)、
[独立地址语义测试](../../build/repcut_grhsim_20260925/active_dispatch_20261003/test_bool_reduce_addressing.py)、
[逐 worker PMU 归属脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_reduce_worker_pmu.py)、
[逐 worker PMU 数据](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_reduce_addressing_20261006/prior_loop_worker_pmu/results.json)、
[地址压缩的直接 8 对结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_reduce_addressing_20261006/offset16/direct_results.json)、
[正式生成与核验驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_bool_reduce.py)、
[正式覆盖与计数](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_bool_reduce_v2_20261006/scope.json)、
[fresh 与关闭选项核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_bool_reduce_v2_20261006/prepare.json)、
[构建核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_bool_reduce_v2_20261006/build.json)、
[独立语义检查](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_bool_reduce_v2_20261006/tests.json)、
[既有回归](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_bool_reduce_v2_20261006/regressions.json)、
[普通窗口一](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_bool_reduce_v2_20261006/ordinary_1/manifest.json)、
[普通窗口二](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_bool_reduce_v2_20261006/ordinary_2/manifest.json)、
[原型与正式版直接对照](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_bool_reduce_v2_20261006/vs_compact_prototype/manifest.json)、
[瓶颈标签](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_bool_reduce_v2_20261006/critical_path/labels.json)、
[独立瓶颈验证](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_bool_reduce_v2_20261006/critical_path/timing_results.json)、
[最终汇总与身份检查](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_bool_reduce_v2_20261006/results.json)。

### 7.60 宽动态位提取的同源快照缓存（2026-10-06）

接续 §7.59 的瓶颈刷新，重新检查正式版 p6/b184 的动态位提取。该函数在
一个 compute supernode 内对同一个已物化宽值执行 794 次
`grhsim_lshr_bit<128,0>`，每次移位量不同；原路径反复从同一 128-bit storage
读取。候选在 emitter 内增加 `demanded_bit_source_cache` attribute / 环境变量，
默认关闭。规则只使用 typed IR 的完整 use-list、物化值和 canonical storage：
同一 compute supernode 内同一源的 demanded-bit 使用次数至少 128 次，且首次
使用之后没有同一物理槽的后续写入，才在首次读取处复制一次源值；事件值、输入
值和不满足证明的源回退原路径。缓存只存活于当前 supernode 的 C++ 词法作用域，
不改变状态布局、写入、通知、调度、通信或 Verilator 路径，也不按 part、信号、
模块或 profile 选择。

#### 形式化生成与静态审计

固定同一 `partitioned.json` 重新生成关闭/开启包。关闭路径的 7552 个生成源/头
文件与既有正式基线逐字节一致；开启路径只命中 **1 个文件、1 个 IR 组、794 次
读取**，即 `p6/b184`。对象编译采用 Clang23/O3，先重编译关闭版基线并核对
可分配节和 relocation，再替换候选对象；最终仅
`grhsim_Gpart_6_model_sched_184.o` 改变，archive 其余 **7453** 个成员保持不变。
该函数 `.text` 为 **228104→224544 B**，全部 6859 个 compute 入口仍满足
64-byte 对齐。生成代码形态为：

```cpp
const auto grhsim_demanded_bit_source_0 = grhsim_value_12645_0_slot;
const bool bit = grhsim_lshr_bit<128u, 0u>(
    grhsim_demanded_bit_source_0, dynamic_shift);
```

本轮 emitter 源文件 SHA256 为
`09de8eb456c6c8d8a868f3161d6c2965d0b0762c4183a265ca0ce7f1214e675a`；开启版
候选 ELF SHA256 为 `9025c86382833a072ef0d46de0be0b67c7a9e9f6b9ef296f223ba3a9a787a7a8`。

独立的 `emit-grhsim-cpp-local-shift-demanded-bit` CTest 通过；正式候选的 C100
初始化检查和两轮共 16 对 C100000 AB/BA 均通过 Difftest，签名保持
`pc=0x80000c0c`、instructions=240349、cycles=99996、guest_cycles=100001、
steps=200102。

#### 两轮正式性能结果

运行条件保持 node030 CPU96–127、NUMA1、Host105、N=K=32、all-spin、Clang23/O3、
ASLR off、C=100000；所有成功样本保留，不设空闲门槛或事后离群剔除。每轮 8 对
AB/BA，百分比按每对 `candidate/baseline-1` 后取中位数。

| 指标 | 第一轮配对中位 | 第二轮配对中位 | 两轮 16 对合并中位 |
| --- | ---: | ---: | ---: |
| Host | −0.328%（6/8） | +0.321%（1/8） | **+0.089%（7/16）** |
| walltime | −0.350%（6/8） | +0.317%（1/8） | **+0.063%（7/16）** |
| 全局 eval | **−0.779%（8/8）** | −0.283%（7/8） | **−0.482%（15/16）** |
| 全局 update | −0.652%（6/8） | −0.464%（5/8） | **−0.652%（11/16）** |
| 最大分区 eval | −0.230%（5/8） | +1.010%（1/8） | +0.647%（6/16） |
| 分区 eval 总和 | −0.840%（8/8） | −0.291%（7/8） | **−0.604%（15/16）** |

候选稳定减少了分区计算总量，但 walltime 没有形成可确认的下降；两轮合并的
wall 中位略为 **+0.063%**。全局 eval 的改善没有等比例传递到 Host/wall，且
`input_load` 阶段在两轮均增加约 10%（绝对量约 0.36 µs/step），最大分区尾部
也有方向不一致。这说明当前收益被主线程输入装载、线程同步和运行中代码/缓存
布局变化抵消，不能把 p6 的静态缩短直接当作最终 walltime 收益。

#### 固定后续代码布局的诊断

为区分计算规则与重链接布局，另将候选对象 `.text` 尾部补回基线长度
`227910−224350=3560 B`，只填充不可达 NOP，不改变候选函数前缀；重新链接后
所有 compute 函数入口地址与基线相同（`shifted_functions=0`）。这不是生产构建，
只用于布局归因。8 对 padded AB/BA 的合并配对中位为：wall **+0.126%**、Host
`+0.124%`、全局 eval `+0.014%`、全局 update `+0.368%`，分区 eval 总和
`−0.013%`。自然布局下的 eval −0.482% 在固定布局后消失，而 p6 本身只剩约
0.1% 量级的波动；这支持“自然版的部分 eval 变化来自链接后代码/缓存布局”这一
解释，但不能把布局因素进一步归结为某一个 cache 或 TLB 事件。

因此本规则保留为 **default-off 的正式 emitter 探索选项**，不进入默认 pipeline，
也不把这轮结果表述为 walltime 优化。后续若继续，应先用固定瓶颈步和 PMU 检查
输入装载/同步的抵消项，再决定是否为更窄的后端成本模型增加额外证明；不要把
小于 128 次的组无条件缓存。

[正式生成与构建脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/generate_demanded_bit_cache_formal_20261006.py)、
[对象构建审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/build_demanded_bit_cache_formal_20261006.py)、
[形式覆盖](../../build/repcut_grhsim_20260925/active_dispatch_20261003/probe_demanded_bit_cache_formal_20261006/formal_prepare.json)、
[构建结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/probe_demanded_bit_cache_formal_20261006/formal_build.json)、
[第一轮 AB/BA](../../build/repcut_grhsim_20260925/active_dispatch_20261003/probe_demanded_bit_cache_formal_20261006/formal128_ordinary/summary.json)、
[第二轮 AB/BA](../../build/repcut_grhsim_20260925/active_dispatch_20261003/probe_demanded_bit_cache_formal_20261006/formal128_ordinary2/summary.json)、
[固定布局构建](../../build/repcut_grhsim_20260925/active_dispatch_20261003/probe_demanded_bit_cache_formal_20261006/padded_build.json)、
[固定布局第一轮](../../build/repcut_grhsim_20260925/active_dispatch_20261003/probe_demanded_bit_cache_formal_20261006/padded_ordinary/summary.json)、
[固定布局第二轮](../../build/repcut_grhsim_20260925/active_dispatch_20261003/probe_demanded_bit_cache_formal_20261006/padded_ordinary2/summary.json)。

### 7.61 GrhSIM 输入装载 fanout 并行化（2026-10-06）

重新检查前面的 `input_load` 阶段后，确认它原本是主线程逐个调用
`load_step_fns_`：每个 `run_load_part_X_` 只把稳定的 Host 输入成员写入自己分区
的 top-input 字段，分区之间没有读写交叉。因此这段 fanout 不需要等待前一个分区
完成，适合复用已经用于 eval/update 的 all-spin worker pool。

正式改动位于 `verilator_repcut_package.cpp` 生成的 `step()`：`grhSim=true` 时
发射 `run_phase_workers_(load_step_fns_)`，让每个 load method 由一个 worker 执行；
`grhSim=false` 仍发射原来的 `run_host_phase_(load_step_fns_)`，所以 Verilator 的
Host-only 输入路径、API 和生成内容保持不变。该规则只依赖生成器已知的“一个 load
method 对应一个分区输入字段”的结构，不匹配分区名、信号名、模块名或运行时 profile，
也不依赖 7.60 的 demanded-bit cache；不改变模型代码、通信值、eval/update 顺序或
状态提交语义。

#### 实验和功能结果

基线为 §7.59 的 bool producer/reduce 正式候选，§7.60 的 demanded-bit cache 关闭；
候选只在这个基线上并行化输入装载。先用只替换生成的 common object 的独立实验
核对行为，模型对象保持不变。node030 CPU96–127、NUMA1、Host105、N=K=32、all-spin、Clang23/O3、
ASLR off、C=100000；保留所有成功样本，不设外部负载门槛或离群剔除。8 对 AB/BA
结果如下：两列绝对值分别取 8 次运行的中位数；变化列先逐对计算
`(candidate/baseline−1)×100%`，再取中位数，因此不是前两列直接相除：

| 指标 | 原串行 load | GrhSIM 并行 load | 变化 | 候选更快 |
| --- | ---: | ---: | ---: | ---: |
| Host / s | 15.7870 | 15.3970 | **−2.426%** | **8/8** |
| walltime / s | 15.8300 | 15.4400 | **−2.439%** | **8/8** |
| `input_load` / µs | 3.6455 | 1.8630 | **−48.490%** | **8/8** |
| 全局 eval / µs | 49.8285 | 49.8185 | −0.586% | 6/8 |
| 全局 update / µs | 23.7515 | 23.7675 | +0.034% | 4/8 |
| 最大分区 eval / µs | 43.7730 | 43.5015 | −0.161% | 4/8 |
| 分区 eval 总和 / µs | 630.4355 | 629.3715 | −0.134% | 6/8 |

C100 初始化检查通过；所有 C100000 运行通过 Difftest，终态签名一致：
`pc=0x80000c0c`、`instructions=240349`、`cycles=99996`、`guest_cycles=100001`、
`steps=200102`。8 对中 wall/Host/input_load 全部逐对下降，收益主要来自消除主线程
逐分区 fanout 的串行时间；eval/update 的变化较小且方向不完全一致，不能把这项结果
解释成模型计算本身变快。按两列阶段中位数粗算，输入装载每 step 减少约 1.783 µs，
乘以 200102 step 约为 0.357 s，与 walltime 中位数减少 0.390 s 的量级吻合。
这只是阶段量级核对，不替代逐对统计。

4 对并行 load 基线与“并行 load + demanded-bit cache”直接对照时，wall 仅再变为
−0.519%、Host −0.527%（均 4/4 更快），分区 eval 总和 +0.129%。这个新组合值得
保留为后续复核线索，但只有单窗口 4 对，尚不足以推翻 §7.60 的两轮不稳定结果；
demanded-bit cache 仍保持 default-off。本节 8 对收益不包含该缓存规则。

#### 生成器验证和边界

新构建树中的 `emit-grhsim-repcut-package` 已通过真实发射、包装代码编译和运行检查，
覆盖 N=1/2/3、标量/宽状态、常量、模型复用、early DPI、重初始化以及串行/并行 API；
同一构建树中的 `emit-verilator-repcut-package` 也返回 0。该功能目前作为 GrhSIM
生成器默认行为落地，Verilator 分支保持原实现。N=1 沿用 `run_phase_workers_` 的
串行回退；多线程时增加了一次与其他 phase 相同的 worker barrier，极小模型或
worker 数很少时可能抵消收益；后续应在
第二个 workload 或不同分区规模上复测，但无需为单个分区或信号增加特判。

[独立并行 load 探针](../../build/repcut_grhsim_20260925/active_dispatch_20261003/probe_parallel_input_load_20261006.py)、
[8 对串行/并行结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/parallel_input_load_20261006/baseline_parallel_ordinary2/summary.json)、
[并行 load 与 source-cache 对照](../../build/repcut_grhsim_20260925/active_dispatch_20261003/parallel_input_load_20261006/cache_vs_parallel_baseline/summary.json)、
[并行 load 基线构建审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/parallel_input_load_20261006/baseline_parallel/build.json)、
[并行 load 候选构建审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/parallel_input_load_20261006/cache_parallel/build.json)。

### 7.62 宽端口通信跳过未变化块：update 归因与正式规则（2026-10-07）

继续 §7.61 的并行 load 基线，保留 bool producer/reduce 正式候选、64 字节 compute
入口对齐，关闭 §7.60 的 demanded-bit cache。本轮把注意力移到 `global_update`：
该阶段不仅包含等待，还包括从各分区输出向其他分区输入发布结果的真实复制。
最终保留的方案是**发送方按 64 字节分块比较当前源/目标，仅复制发生变化的块**，
已作为 GrhSIM RepCut 生成器默认行为实现；不改变 Verilator 生成路径。

#### 实际瓶颈：复制正文，而非派发/收尾

冻结包装代码包含 5291 条发布语句：1129 条宽端口复制、4157 条分区间标量赋值、
5 条顶层输出赋值，合计每 step 逻辑写入 463262 B。其中宽端口占 454488 B。
每个目标端口只有一个写者，适配器引用独立模型成员；存储审计确认 5286 个分区间
目标均唯一，源/目标没有重叠。发送方分组最大每步发布 41244 B；接收分布却很不均匀，
p24 接收 197283 B，约占全部发布量的 42.6%。因此，简单把“发送方复制”改成
“接收方复制”，并不能自然消除串行尾部，还会改变下一阶段读取数据时的缓存状态。

独立基线时序发现集为 4 次 C100000，每次在 `step % 127 ∈ {0,1}`、step≥127
采样 3150 步，共 12600 步。update 最后完成者几乎都为 p5/p16/p20。
后续同窗 2 对时序对照中，基线的全局 update 平均 27.508 µs，分解为：

| 关键路径组成 | 基线 / µs | 按块比较候选 / µs |
| --- | ---: | ---: |
| 最后完成任务开始前 | 1.204 | 1.198 |
| 该任务复制正文 | 25.513 | 18.160 |
| 该任务完成到全局阶段结束 | 0.792 | 0.641 |
| 全局 update 合计 | 27.508 | 20.000 |

两侧各 6300 个采样点，最后完成者逐步重新判定。候选中 p16/p20 分别最后完成
3149/3025 次，p5 只有 8 次；剩余瓶颈已经改变。这些是**带探针的时序诊断**，
不能拿来替代下文普通可执行文件的 walltime，也不能将“逐步最后完成任务的平均
正文”与“各分区平均正文的最大值”混为一谈。

针对上述固定基线瓶颈步的 PMU 诊断也表明，复制的成本不能只用指令条数解释；
显著减少复制指令未必降低其 cycles。当前证据支持优先减少不必要的目标写入，
但普通 `cache-misses` 事件不能单独证明 HITM、某一级缓存或具体一致性事务是唯一原因。

#### 通用规则与写入量

`verilator_repcut_package.cpp` 在 GrhSIM 的 `unit_to_unit` 宽端口赋值处生成
`copy_changed_wide_words_`。helper 按 8 个 `uint64_t`、即 64 B 分块执行：

```cpp
if (std::memcmp(dst.data() + offset, src.data() + offset, bytes) != 0)
    std::memcpy(dst.data() + offset, src.data() + offset, bytes);
```

最后不足 64 B 的部分按实际剩余 word 数处理；64 B 是分块长度，不是对端口地址
的对齐要求。Clang 下保留紧凑循环，避免把大端口展开成很大的比较/复制正文。
范围只由端口类型和 `unit_to_unit` 连接确定，不匹配分区、模块、信号名或运行时
profile。标量、Host load、顶层输出继续沿用原实现。

发送方、early/final phase、复制顺序和已有 barrier 均保留。目标是普通数组存储，
写入本身没有回调或通知副作用；下一个 eval 看到的输入值与无条件复制相同。直接
比较**当前目标值**，不保留历史源快照、dirty bit 或版本号，因此不会因初始化/
重初始化、源值保持不变而漏掉必要的恢复写入。

独立计数版完成一次 C100000 Difftest，累计 200102 step；逐任务计数与静态宽端口
大小 × step 数完全吻合。计数版仅用来统计字节，不进入普通性能统计：

| 每 step 逻辑写入 | 无条件复制 / B | 跳过未变化块 / B |
| --- | ---: | ---: |
| 宽端口 | 454488 | 44856.27 |
| 标量及顶层输出 | 8774 | 8774 |
| 合计 | 463262 | 53630.27 |

宽端口写入减少 **90.130%**。这表示没有执行相应目标写入的逻辑字节数，**不等于
总内存流量减少 90.130%**：比较依然读取源和目标，缓存行获取、回写与实际硬件
总线流量需要其他硬件事件才能量化。

#### 普通 AB/BA：原型复现后，再验证正式 helper

统一 node030 CPU96–127、NUMA1、Host105、N=K=32、all-spin、Clang23/O3、ASLR off、
C=100000。保留全部成功样本，包括较慢样本，不使用空闲门槛或离群剔除。
当日基线绝对时间与 §7.61 不同，所有收益都来自本节同窗配对，不跨日期相减。

原型两窗口合计 8 对：Host −8.983%、walltime −8.988%、全局 update −26.665%、
全局 eval −1.257%，均 8/8 逐对变快。随后从新构建的正式 emitter 实际生成的
header 提取 helper，应用到同一冻结 XiangShan 包装代码，再做 4 对 AB/BA：

| 指标 | 本轮基线中位数 | 正式 helper 中位数 | 逐对变化中位数 | 更快次数 |
| --- | ---: | ---: | ---: | ---: |
| Host / s | 17.7305 | 16.1290 | **−9.039%** | 4/4 |
| walltime / s | 17.7650 | 16.1650 | **−8.999%** | 4/4 |
| `input_load` / µs | 2.1310 | 2.1325 | +0.409% | 2/4 |
| 全局 eval / µs | 56.9635 | 56.2880 | −1.019% | 4/4 |
| 全局 update / µs | 27.7800 | 20.4360 | **−26.382%** | 4/4 |
| 最大分区平均 update / µs | 25.2760 | 16.1175 | −35.789% | 4/4 |
| 各分区平均 update 总和 / µs | 376.9310 | 216.8825 | −42.515% | 4/4 |

变化先逐对计算 `(candidate/baseline−1)×100%` 再取中位数，不能直接由前两列
相除得到。正式 helper 的 4 对 walltime 降幅为 8.622%～9.312%。按阶段中位数
作量级核对，update 每步减少 7.344 µs，乘以 200102 step 约 1.470 s；eval 每步
减少约 0.676 µs，约 0.135 s，合计接近 walltime 中位数减少的 1.600 s。
主要收益因此来自通信，不能解释成模型逻辑本身得到约 9% 的加速。

性能构建没有重新划分或重新生成 32 份计算模型：普通候选只替换
`wolvi_repcut_grhsim_sim_update_0.o`，归档中其余对象逐字节不变，链接复用原 harness
对象。正式 helper 使用新生成器的真实生成内容，但大包仍是受控的增量构建，
不是一次全量 fresh XiangShan 生成。链接地址会移动；6859 个主 compute 入口
全部保留 64 字节对齐。本节没有把约 1% 的 eval 变化单独归因于某一种缓存机制。

C100 初始化检查和全部 24 次普通 C100000 均通过 Difftest，签名一致：
`pc=0x80000c0c`、`instructions=240349`、`cycles=99996`、`guest_cycles=100001`、
`steps=200102`。诊断版也各自通过功能检查，未混入上述 12 对性能结果。

#### 功能回归、保留范围与后续

`emit-grhsim-repcut-package` 在新构建树实际发射、编译并运行，扩展原 fixture，
新增 1025-bit 两级寄存器通信，覆盖两个完整 64 B 块及尾块；原有 65/130-bit
短尾块、标量、常量、保持不变、逐 word 修改、清零、重初始化、DPI/异常恢复、
N=1/2/3、wrapper/facade、all-spin/condition-variable 等检查全部通过。
同一 fixture 再用 Clang23/O3 + ASan/UBSan 编译，N=1/2/3 × 两种 API 共 6 次通过。
`emit-verilator-repcut-package` 的生成结构回归也通过；这里未声称重新运行完整
Verilator XiangShan 性能测试。代码审查确认新增 helper/include/调用均受 `grhSim`
分支约束，Verilator 输出仍为原复制方式。

保留此通用通信规则为 GrhSIM RepCut 默认行为。当前只有一个真实 workload，若
其他设计每步绝大部分块均改变，额外比较可能抵消收益，需后续再评估。接下来的
通信分析可聚焦仍经常最后完成的 p16/p20，区分残余比较读取与实际变化块写入；
不能因为 p5 退出就继续沿用旧的瓶颈标签。eval 则继续按新的关键路径独立分析。

[实验与构建脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/update_ownership_20261007.py)、
[汇总及写入量审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/update_ownership_20261007/results.json)、
[正式 helper 的 4 对结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/update_ownership_20261007/formal_ordinary/summary.json)、
[正式增量构建身份](../../build/repcut_grhsim_20260925/active_dispatch_20261003/update_ownership_20261007/formal/build.json)、
[独立时序对照](../../build/repcut_grhsim_20260925/active_dispatch_20261003/update_ownership_20261007/changed_chunks_timing/results.json)、
[端口存储审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/update_ownership_20261007/storage_audit.json)、
[sanitizer 结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/update_ownership_20261007/sanitizer/results.json)。

#### 增量核查：为何前一轮约 15 s，本轮 baseline 却约 17.8 s（2026-10-07）

核对 §7.61 的 `baseline_parallel_ordinary2` 与本节 `formal_ordinary` 原始 manifest：
前者 candidate 与后者 baseline 是**同一路径、同一 SHA-256 的可执行文件**
（`9e4673800ea065ab7c586fede8da1f54541d62c4829ef2242c7ff6a87b8c2f66`）。
两次记录的 runner/analyzer 脚本、CoreMark/NEMU 文件哈希、CPU96–127、NUMA1、
ASLR off、N=K=32、Host105、all-spin、功能签名也全部相同，且两侧都通过运行前后
输入身份检查。并非拿回了较旧的代码或关闭了前面的优化。

| 同一个并行 load 二进制 | 10 月 6 日 21:41–21:45 | 10 月 7 日 08:04 起 | 跨窗口变化 |
| --- | ---: | ---: | ---: |
| walltime 中位数 / s | 15.440 | 17.765 | +15.058% |
| input_load / µs | 1.863 | 2.131 | +14.385% |
| eval / µs | 49.8185 | 56.9635 | +14.342% |
| update / µs | 23.7675 | 27.7800 | +16.882% |

时间均为北京时间。首对原始 `/usr/bin/time` 都报告约 3194% CPU 使用率、0 次重大
缺页和 0 文件输入，不能把额外 2.325 s 解释为启动读盘，也没有证据说明线程少用了
15% 的 CPU 配额。绝对时间变化发生在旧程序本身的整个运行过程。

08:42 起补做只读 perf/procfs 诊断，保留原二进制和系统设置。两次旧并行 load
程序 wall 为 17.27/17.25 s，平均执行频率为 3.3047/3.3031 GHz；中间一次新通信
程序为 15.64 s、3.3058 GHz。它们仍使用约 31.9 个 CPU，代码驻留页和主要匿名
数据页均在 NUMA1；SMT 兄弟 CPU288–319 平均活跃率约 0.2%–0.3%。这一复测再次
说明绝对值会随窗口变化，而同窗通信优化仍有收益；诊断运行不并入普通 AB/BA 表。

前一晚 21:13 附近、同一计算模型的串行 load 线有历史 PMU：从 cycles、event
running time 和约 83% multiplex 比例估计，4 次 baseline 运行频率中位约 3.565 GHz。
本次两次旧并行 load 的约 3.304 GHz 比它低约 7.3%；仅按频率比例，耗时会增加约
7.9%。这是降频因素的证据，**不是对全部 +15.058% 的精确分摊**：历史 PMU 属于
邻近时段的串行 load 线，普通 8 对运行没有逐次保存频率数据，剩余差额也没有被
独立定位为某一种缓存/内存原因。

当前同 socket 的 CPU128–191 平均活跃率约 88%，并发现多组清晨启动的其他仿真
任务绑定在这些核上。它们与预留核不直接重叠，但共享 socket 资源；这支持
“socket 总负载变化降低 boost 余量”的解释，尚不足以区分功耗、温度及其他共享
资源的具体贡献。因此保留的严格结论是：**存在已验证的跨窗口运行速度漂移，
其中降频是明确因素；新通信优化约 9% 的收益来自同窗配对，不能直接拿 16.165 s
与前一晚 15.440 s 判定优化倒退，也不能假定旧环境下一定能达到某个推算秒数。**

[只读诊断脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/walltime_drift_20261007.py)、
[频率、页面位置与功能结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/walltime_drift_20261007/results.json)。

### 7.63 标量通信保护原型与 p16/p20 残余开销（2026-10-07）

按用户约定，正式 walltime AB/BA 留到服务器负载降低后。本轮完成不依赖性能
裁决的原型、功能验证和机制归因。基线是 §7.62 已保留的 **wide-chunk guard**，
即宽端口按 64 B 比较、只写变化块的版本，另含并行 input load、既有模型优化、
64 B compute 入口对齐；不是 §7.62 表中的无条件宽复制 baseline。
冻结基线 SHA-256 为 `8a5dc8eb490f0801d27738cbf1cb9d325ed65391a775f377665412590c6af6f6`。

#### p16/p20 剩余 update 时间花在哪里

给冻结基线的 update 翻译单元补充调试行号，核实其所有已分配 ELF section 的内容
与原对象相同；链接后 compute 地址及机器码不变。使用 node030 CPU96–127、
NUMA1、Host105、N=K=32、all-spin、Clang23/O3、ASLR off，运行 C100000，启动约
2 s 后仅对 CPU112/p16、CPU116/p20 对应线程采样 `cycles:u`，period=2000003，
以调用栈和源代码行区分 update、eval 内部的比较/复制。运行通过 Difftest。

共解码 38227 个线程样本，与 perf 记录总数一致；其中 p16/p20 的 update 样本
分别为 4427/4111 个。统计包含 perf 展开的内联帧；eval 内部的 303/456 个
内存库函数样本单独排除，没有把它们算进跨分区通信。update 内样本占比如下：

| update 内 cycles 样本归属 | p16 | p20 |
| --- | ---: | ---: |
| 宽端口比较 | 56.13% | 68.38% |
| 宽端口变化块复制 | 22.39% | 4.69% |
| 标量赋值及其取址/读写 | 18.00% | 22.50% |
| 宽复制循环及参数准备 | 1.67% | 2.75% |
| 任务准备及计时收尾 | 1.81% | 1.68% |

这是一轮热点定位，不是正式 walltime 对照，也不是“该分区成为最后完成者时”
的条件采样。源码行归因和 PMU 采样存在边界误差，不能将表中的占比直接换算为
可消除的全局耗时，但已足以确定：**剩余通信开销以宽数据比较为主，标量发布也
并非可以按字节占比忽略的小项。**

p16 的 173 条标量连接每步仅 418 B，却涉及 28 个目标分区；p20 的 422 条每步
736 B、涉及 31 个目标分区。零散赋值需要取址和跨核访问，逻辑字节少不代表成本低；
本次尚未用一致性硬件事件把其中开销进一步分成具体 cache 层级或事务。
p16 最大宽端口为 21976 B，单条发布对应约 56.72% 的 update 样本；p20 热点更
分散，最大 6704 B 端口只对应约 5.91%。因此不能仅按最大端口大小安排优化。
这些端口位置仅用于归因，不用于下面的优化适用条件。

#### 标量“值变化才写”的通用原型

对全部分区间标量连接统一应用：

```cpp
const T value = src;
if (dst != value) dst = value;
```

覆盖 bool、8/16/32/64 位整数，不匹配分区、模块或信号，也不按运行 profile
决定适用性。仍比较**当前目标值**，没有源历史快照、版本号或 dirty bit；目标
在重初始化后被清零而源保持不变时，仍会恢复正确输入。发送方、early/final
phase 和同步边界保持原有语义，宽端口继续使用基线 helper。

冻结 XiangShan 包装代码的全部 4157 条标量连接均应用该规则，计数版独立完成
C100000、200102 step；每条连接的尝试次数都精确等于 step 数。

| 范围 | 原标量写入 / B·step⁻¹ | 原型实际标量写入 / B·step⁻¹ | 省去赋值次数 | 省去逻辑写入字节 |
| --- | ---: | ---: | ---: | ---: |
| 全部 32 分区 | 8755 | 634.25 | 95.399% | 92.756% |
| p16 | 418 | 26.04 | 94.948% | 93.770% |
| p20 | 736 | 52.59 | 95.389% | 92.854% |

全体每步原有 4157 次标量发布，实际约 191.25 次需要写入。以上分母只包含标量
分区间连接，不含宽端口及 5 条顶层输出；也不表示实际硬件内存流量下降相同比例。
新增比较仍读取源和目标，且会增加分支和代码体积，必须通过后续 walltime 验证净收益。

#### 机器码、功能验证与保留范围

Clang23/O3 的五种标量类型独立汇编均保留跳过 store 的相等分支；冻结大包的
优化 LLVM IR 逐一核对全部 4157 个调用点：store 仅从不相等分支进入，相等路径
直接到汇合点。大包汇编也存在相应 compare/branch/store；LLVM 会复制部分冷路径，
所以没有把汇编中的分支个数误当成源码连接个数。

普通原型只替换 `wolvi_repcut_grhsim_sim_update_0.o`，其余模型对象与 harness
对象保持不变，6859 个主 compute 入口继续 64 B 对齐。update 对象 `.text` 从
224747 B 增至 308107 B（+83360 B），这是后续性能验证需要观察的代价。

普通版和独立计数版各自通过 C100、C100000 Difftest；C100000 均为
`pc=0x80000c0c`、`instructions=240349`、`cycles=99996`、`guest_cycles=100001`、
`steps=200102`。小模型同时覆盖 early/final 标量通信，在 Clang23/O3 + ASan/UBSan
下通过 N=1/2/3、wrapper/facade、all-spin 以及 N=3 condition-variable 共 8 次
运行。独立五类型测试又在 Clang23 sanitizer 和 GCC/O3 下通过，覆盖保持、变化、
随机值、扇出、源/目标别名及目标重置。

**当前保留为实验原型，尚未加入正式 emitter 默认行为。** 现行默认仍为 §7.62
的宽端口规则；本轮没有修改 Verilator 路径，也没有将功能/计数/采样运行的时间
当成普通性能结果。服务器空闲后先比较冻结 wide-only 与 wide+scalar 两个普通
二进制，重点看 walltime、global_update、p16/p20 尾部及 eval 是否因布局改变而
抵消收益。若标量版没有收益，不能仅凭省去 95% 写入就采用。

更大的后续方向是减少宽数据的重复比较，例如利用输出物化时已有的精确变化信息，
在源侧生成可供通信使用的变化标志。它需要证明初始化/重初始化、多个目标及
early/final phase 下的有效性，并将标志维护成本纳入评估；本轮只明确了这个
方向的优先级，尚未实现或声称它有净收益。

[原型、构建与验证脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/scalar_communication_20261007.py)、
[汇总与二进制身份](../../build/repcut_grhsim_20260925/active_dispatch_20261003/scalar_communication_20261007/results.json)、
[逐连接计数](../../build/repcut_grhsim_20260925/active_dispatch_20261003/scalar_communication_20261007/counts_functional/counts.json)、
[机器码与逐调用点 IR 核查](../../build/repcut_grhsim_20260925/active_dispatch_20261003/scalar_communication_20261007/machine_code.json)、
[功能回归](../../build/repcut_grhsim_20260925/active_dispatch_20261003/scalar_communication_20261007/semantic/results.json)、
[采样与归因脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/scalar_update_profile_20261007.py)、
[完整采样归因](../../build/repcut_grhsim_20260925/active_dispatch_20261003/scalar_communication_20261007/profile_runs/complete/attribution.json)。

#### 增量更新：完成 8 对普通 walltime AB/BA（2026-10-07）

同日按用户要求补做正式性能对照，不再等待服务器负载降低。仍用 node030
CPU96–127、NUMA1、Host105、N=K=32、all-spin、Clang23/O3、ASLR off、C=100000。
A 为上文的 wide-only 基线，B 为同一基线叠加全部标量连接保护的普通原型；
两者都没有逐连接计数或 perf 采样。先各做 C100 初始化检查，再做 8 对交错
AB/BA，共 16 次 C100000，保留全部功能成功样本，不设负载门槛或剔除慢样本。

| 指标 | wide-only 中位数 | wide+scalar 中位数 | 逐对变化中位数 | 更快次数 |
| --- | ---: | ---: | ---: | ---: |
| walltime / s | 15.015 | 13.695 | **−8.821%** | 8/8 |
| Host / s | 14.9820 | 13.6615 | **−8.850%** | 8/8 |
| input_load / µs | 2.2115 | 2.0820 | −6.696% | 7/8 |
| 全局 eval / µs | 51.4555 | 51.2860 | −0.481% | 6/8 |
| 全局 update / µs | 19.5790 | 13.3720 | **−31.876%** | 8/8 |
| 最大分区平均 update / µs | 15.3985 | 11.2660 | −26.711% | 8/8 |
| 各分区平均 update 总和 / µs | 209.2305 | 115.4535 | −44.794% | 8/8 |

变化逐对按 `(B/A−1)×100%` 计算，再取 8 对中位数；不能直接用表中两组中位数
相除代替。walltime 的 8 对降幅为 8.027%～10.138%；AB 顺序的中位变化为
−8.821%，BA 为 −8.791%，顺序差仅约 0.030 个百分点。本轮支持当前 workload
下有明确净收益，不能把上文“尚待普通性能验证”继续当作最新状态。

| 分区平均 update / µs | wide-only 中位数 | wide+scalar 中位数 | 逐对变化中位数 |
| --- | ---: | ---: | ---: |
| p16 | 15.3985 | 11.2660 | −26.711% |
| p20 | 13.8160 | 6.1395 | −55.724% |

两侧全部 8 次运行中，分区平均 update 最大者均为 p16。此处仍是每个分区的
全程平均值；本轮未添加逐步时空探针，因此不把它解释为最后完成次数或条件瓶颈
耗时。p20 的平均通信耗时已经明显低于 p16，后续残余分析应以新版本重新采样。

按同一批运行的**均值差**乘以 200102 step 核算阶段贡献：update 减少
1.24028 s，eval 减少 0.05308 s，input_load 减少 0.02551 s；Host 共减少
1.34325 s，其余约 0.02438 s。update 约占 Host 减少量的 **92.33%**，与这次
修改作用于通信路径相符，eval 没有抵消主要收益。不能仅由这张表进一步断言
具体 cache 一致性事务减少了多少，亦不能将省去的写入次数比例当成耗时降幅。

16 次 C100000 均通过 Difftest、配置及功能签名检查，签名与上文一致。运行前后
两份 ELF、CoreMark image 和 NEMU 的 SHA-256 均保持不变；两个普通二进制身份
就是上文已经审计的基线和候选。采用同窗比较，不与 §7.62 或前一天的绝对秒数
直接相减。正式 emitter 默认尚未改动；现已补齐原型的性能证据，可据此进入
生成器实现与生成一致性验证。

[普通对照 manifest](../../build/repcut_grhsim_20260925/active_dispatch_20261003/scalar_communication_20261007/ordinary/manifest.json)、
[8 对统计汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/scalar_communication_20261007/ordinary/summary.json)、
[逐对原始结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/scalar_communication_20261007/ordinary/pairs.csv)、
[逐分区结果及阶段核算](../../build/repcut_grhsim_20260925/active_dispatch_20261003/scalar_communication_20261007/ordinary/performance.json)。

#### 增量更新：标量规则迁入正式生成器（2026-10-07）

`verilator_repcut_package.cpp` 现对 GrhSIM 的全部 `unit_to_unit` 标量连接生成
`copy_changed_scalar_`，比较当前目标与源，仅在不相等时写入；early/final 共用
同一规则。宽端口继续沿用此前 helper。Verilator、Host 输入及顶层输出的生成
分支保持原实现，无模块/信号名单或 profile 条件。

重新构建 emitter，并扩展已有寄存器链 fixture，使 bool、8/16/32/64 位标量均
通过真实分区间连接验证。`emit-grhsim-repcut-package` 与
`emit-verilator-repcut-package` 两项回归通过；前者包含生成、编译、运行、
early DPI、复位/保持/重初始化、N=1/2/3、两种 API 及等待策略检查。新生成的
fixture 又在 Clang23/O3 + ASan/UBSan 下通过 8 次运行。

香山使用正式 emitter 实际生成的 helper，应用到冻结包装代码的全部 4157 条
标量连接。只重编 update 对象，其余计算模型对象和 harness 对象不变，6859 个
compute 主入口仍为 64 B 对齐。这里是受控增量构建，不是重新全量生成香山。
对照仍为原 wide-only 基线，配置与上文一致，完成 4 对 C100000 AB/BA：

| 指标 | wide-only 中位数 | 正式标量规则中位数 | 逐对变化中位数 | 更快次数 |
| --- | ---: | ---: | ---: | ---: |
| walltime / s | 15.040 | 13.780 | **−8.469%** | 4/4 |
| Host / s | 15.0015 | 13.7430 | −8.486% | 4/4 |
| 全局 eval / µs | 51.4345 | 51.4605 | +0.178% | 1/4 |
| 全局 update / µs | 19.6770 | 13.5005 | **−31.510%** | 4/4 |

C100 与全部 8 次 C100000 的功能签名/运行配置通过，运行前后输入身份相同。
正式 helper 复现原型的主要通信收益，现保留为 GrhSIM RepCut 默认生成行为。
后续宽端口优化以此正式标量版本为新基线，重新采样其关键路径。

[正式构建与实验脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_communication_20261007.py)、
[正式标量版本构建身份](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_communication_20261007/scalar_formal/build.json)、
[正式规则 4 对对照](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_communication_20261007/scalar_formal_ordinary/summary.json)、
[扩展 fixture 的 sanitizer 结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_communication_20261007/scalar_sanitizer/results.json)。

### 7.64 宽通信块复用源值：新基线关键路径与正式默认（2026-10-07）

以 §7.63 的**正式标量保护版本**为 A，重新定位其剩余 update 开销，再对全部
GrhSIM 分区间宽连接采用同一条通用规则。仍使用 node030 CPU96–127、NUMA1、
Host105、N=K=32、all-spin、Clang23/O3、ASLR off、CoreMark、C100000；所有功能
成功的普通性能样本均保留，不设置空闲门槛，不剔除慢样本。

#### 新基线的残余热点

独立时空探针各取 2 次 C100000，每次均匀抽取 3150 step，共 6300 个样本。
最后完成者按每个 step 的 `start + duration` 重新计算，不能直接用最大平均值
代替。基线 p16 是 3401/6300 个 update 的最后完成者，其中高电平半周期占
3149/3150；它在最后完成时的平均自身 update 为 16.9268 µs。低电平半周期则
主要由 p5/p20 决定，不能把 p16 当作所有 step 的唯一瓶颈。

另用仅补充行号、保持可装载 section 与 compute 地址/字节不变的采样二进制，
重新捕获 p5/p16/p20。下面的分母为各线程**全部 update** 的 cycles 样本，
不是只在成为最后完成者时采样；它与上述条件时空数据是互补证据。

| 分区 | update 样本数 | 宽比较 | 宽复制 | 标量保护/赋值 |
| --- | ---: | ---: | ---: | ---: |
| p5 | 1520 | 67.17% | 3.88% | 21.97% |
| p16 | 2896 | 56.60% | 28.73% | 11.36% |
| p20 | 1685 | 45.04% | 4.33% | 45.04% |

p16 的 21976 B 发布调用占其 update 样本的 79.14%，宽比较与复制合计占
85.32%。标量保护已有效压低此前开销，当前应减少完整宽块的比较/复制实现成本。
这些分区和调用位置仅用于诊断，未作为优化名单。

#### 通用改写及实际机器码

原完整块执行 `memcmp(dst, src, 64)`，若不同再 `memcpy(dst, src, 64)`。
新规则先取 8 个 `uint64_t` 源值，比较当前目标；若不同，直接写回这些已取出的
源值。外层仍每次推进 64 B，禁止 Clang 展开整个大端口；尾块继续按实际长度
比较和复制，不读写有效 word 以外的地址。

源码以逐 word XOR 后 OR 归约表达“是否不同”，但 **Clang23/O3 实际生成的是
8 次源加载与 compare/branch 链，不是 SIMD XOR**。正式大包的 2747-word
helper 汇编确认：完整块循环内不再调用 `bcmp/memcpy`，改变时直接存储已经
加载到寄存器的 8 个源值；不足 64 B 的尾部仍可调用库函数。这给出了收益的
代码层依据，但没有单独分离“省库函数调用”与“复用源值”的各自贡献。

规则不增加历史值、版本号或 dirty bit，不匹配模块/分区/信号，不依赖编译后
profile；所有分区间宽连接统一应用。标量保护、early/final 发布时机、发送方
职责及 barrier 语义保持不变。Verilator 的生成分支继续使用原实现。

#### 普通性能：原型与正式 helper 分别交错验证

先做原型 4 对 AB/BA：walltime 13.815→13.170 s，逐对变化中位数 −4.593%，
4/4 更快；global_update 13.3480→10.7595 µs，逐对 −19.042%。随后将规则迁入
正式 emitter，真实重新生成小模型包，取实际生成的 helper 应用到冻结香山包。
正式 helper 与通过验证的原型逐字节相同。仍只重编 update 对象，其他模型和
harness 对象不变，6859 个主 compute 入口保留 64 B 对齐。这里是**受控增量
构建，不是重新全量生成香山**。

正式版本另做 4 对 C100000 AB/BA，A 同样为正式标量基线：

| 指标 | A 中位数 | 正式宽块规则中位数 | 逐对变化中位数 | 更快次数 |
| --- | ---: | ---: | ---: | ---: |
| walltime / s | 13.730 | 13.160 | **−4.375%** | 4/4 |
| Host / s | 13.6930 | 13.1245 | −4.382% | 4/4 |
| 全局 eval / µs | 51.3395 | 51.2845 | −0.344% | 3/4 |
| 全局 update / µs | 13.3485 | 10.6040 | **−20.560%** | 4/4 |
| p16 平均 update / µs | 11.1710 | 8.3890 | **−25.144%** | 4/4 |
| p5 平均 update / µs | 5.9660 | 5.6355 | −5.427% | 4/4 |
| p20 平均 update / µs | 6.1525 | 6.7080 | **+9.905%** | 0/4 |
| 最大分区平均 eval / µs | 43.9640 | 44.7760 | +1.199% | 0/4 |

逐对百分比先按 `(B/A−1)×100%` 计算，再取中位数，不能用两个组中位数直接
相除替代。正式版本每对 walltime 降幅为 3.275%～4.417%，AB/BA 两种顺序都
更快。p20 局部 update 和最大分区平均 eval 的退化一并保留；这不是所有局部
计时均下降的优化，采用依据是整体 walltime。不能因模型对象未变就认为其
实际 eval 时间必须相同，包装代码变化仍可能影响缓存、布局和进入下一阶段的状态。

按本轮 4 对的**均值差**核算，Host 减少 0.56350 s，其中 update 减少
0.55693 s，eval 减少 0.01276 s，input_load 增加 0.00200 s，其余增加约
0.00419 s。主要收益来自通信阶段。§7.63 的 −8.469% 与本节 −4.375% 使用
不同对照窗口，不能相加，也没有在本轮直接测得相对 wide-only 的合计降幅。

#### 时空探针确认改善发生在哪个半周期

候选同样单独跑 2 次 C100000、采样 6300 step，与前述新基线诊断比较：

| 时空样本指标 | 正式标量基线 / µs | 新宽块原型 / µs |
| --- | ---: | ---: |
| 全部采样 step 的全局 update | 13.3254 | 10.6591 |
| p16 最后完成时的自身 update | 16.9268 | 12.1059 |
| 高电平半周期的全局 update | 19.8636 | 14.1301 |
| 高电平半周期的 p16 自身 update | 17.8846 | 12.2077 |
| 低电平半周期的全局 update | 6.7872 | 7.1880 |
| 低电平半周期的 p16 自身 update | 4.7067 | 4.8278 |

高电平半周期 p16 平均自身 update 下降约 31.74%；低电平全局 update 则
增加约 5.91%。候选高电平中 p16 仍有 3106/3150 次最后完成，低电平则主要
是 p5（2075 次）、p20（794 次）、p2（216 次）。这里两个版本分别采样，
不是交错普通性能结果；且“最后完成时”条件集合会变化，所以主要用于定位
改善方向。walltime 净收益以此前无逐步探针的 AB/BA 为准。

#### 验证与保留结果

两项 package CTest 均通过。正式生成的 108 个源文件/头文件/构建文件与已通过
Clang23/O3 + ASan/UBSan 的原型 fixture 逐字节相同，后者完成 wrapper/facade、
N=1/2/3 默认及 N=3 condition-variable 共 8 次运行。独立 helper 在
Clang23 sanitizer 与 GCC/O3 下验证零长度、前缀长度、尾块、逐 word 变化、
保持、清零、源目标相同及不同容量数组。

原型及正式两批各自的 C100 初始化检查、全部 16 次普通 C100000 均通过
Difftest；两侧诊断共 4 次 C100000 亦通过。功能签名保持
`pc=0x80000c0c/instructions=240349/cycles=99996/guest_cycles=100001/steps=200102`。
普通运行前后 ELF/image/NEMU 的身份一致。Verilator fixture 的 167 个产物中，
其附带 GrhSIM 包只有预期的宽 helper 变化，其余 166 个文件逐字节不变。

**正式 GrhSIM RepCut 默认保留新宽块规则和 §7.63 标量保护。** 当前普通全局
eval 约 51.28 µs、update 约 10.60 µs，后续优先回到新基线的 eval 关键路径。
最新诊断中 p3/p18/p6/p10 分别最后完成 2171/1194/933/840 次，可先针对这些
分区的实际瓶颈步与 Verilator 对照。源侧变化标志仍可作为更长期的通信方向，
但需要同时解决重初始化、多个目标、early/final 语义与维护成本，本轮未实现。

[完整汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_communication_20261007/results.json)、
[实验与分析脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_communication_20261007.py)、
[新基线 perf 归因](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_communication_20261007/scalar_profile/attribution.json)、
[正式构建身份](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_communication_20261007/wide_formal/build.json)、
[正式宽 helper 汇编](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_communication_20261007/wide_formal/wide_2747.asm)、
[原型 4 对普通对照](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_communication_20261007/xor64_ordinary/summary.json)、
[正式 4 对普通对照与阶段核算](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_communication_20261007/wide_formal_ordinary/performance.json)、
[基线按半周期统计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_communication_20261007/scalar_discovery/clock_phases.json)、
[候选按半周期统计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_communication_20261007/wide_discovery/clock_phases.json)、
[正式生成与 sanitizer 源码一致性](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_communication_20261007/final_sanitizer_identity.json)、
[Verilator 产物一致性](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_communication_20261007/verilator_identity.json)。

### 7.65 通信优化后的 eval 关键路径与动态取位实验（2026-10-07）

本节以 §7.64 的正式宽通信版本为当前 GrhSIM 基线，包含并行输入装载、标量
变化保护和完整 64 B 块源值复用。普通 ELF SHA-256 为
`2ca12a413bdacfb86733f075ae8584b5f94ab445ed1561653f1984a6d65e6ade`。
Verilator 使用冻结的 Clang23/O3 `verilator_lock_elision_final/candidate/emu`。
仍在 node030 CPU96–127、NUMA1、Host105、N=K=32、all-spin、ASLR off、CoreMark、
C100000 下测试，保留全部功能成功的普通性能样本，不设空闲门槛。

#### 重新确定瓶颈步骤，并在相同步骤比较后端

先对当前 GrhSIM 运行 4 次独立时空发现采样；均匀取相邻两个 step，剔除最初
一对初始化样本后，每次保留 3148 个 step。对每个 step，以各分区 4 次运行的
`start + duration` 中位数确定最后完成者，冻结标签。再做独立 4 对 GrhSIM /
Verilator AB/BA，在这些相同 step 上比较自身 eval；验证数据不参与选标签。

因此下面“标签次数”是 **3148 个稀疏步骤的固定标签数**，不是所有 200102 step
的完整最后完成频数。自身 eval 不包含启动偏差或 barrier 等待。相邻两步合计
针对该分区标签所覆盖的采样对，分别计算两步自身 eval 后相加；采样对不一定
从某个特定时钟沿开始，不能解释为完整电路工作量的严格重分配。

| 分区 | 标签数 / 占比 | 标签 clock=0/1 | Verilator 瓶颈步自身 eval / µs | GrhSIM / µs | 逐对变化中位数 | V 相邻两步合计 / µs | G 相邻两步合计 / µs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| p3 | 1136 / 36.09% | 541 / 595 | 81.0913 | 43.2261 | −46.63% | 159.3361 | 87.0457 |
| p6 | 431 / 13.69% | 429 / 2 | 36.0627 | 56.3030 | **+56.13%** | 104.9704 | 87.5109 |
| p10 | 437 / 13.88% | 5 / 432 | 59.6937 | 49.7552 | −16.69% | 81.4050 | 85.3899 |
| p18 | 518 / 16.45% | 10 / 508 | 55.3679 | 51.4644 | −7.03% | 81.9136 | 95.1767 |

四者合计占固定标签的 80.11%。表中绝对值为每次运行在固定集合上的均值，再对
4 次运行取均值；变化率先逐对计算再取中位数。p3 虽最常成为 GrhSIM 的最后
完成者，但同一步已显著快于 Verilator。p6 是当前最明确的局部后端劣势：
瓶颈几乎都在 clock=0，自身 eval 慢约 56%，但相邻两步合计仍快约 16.61%。
p10/p18 的瓶颈步本身较快，相邻两步合计却分别慢约 4.79%/16.14%，说明另一个
半周期仍有可优化工作；不能只看其中一个半周期就宣布整个分区更快。

另做 4 对条件 PMU 对照，仅在同一批固定步骤统计 p3/p6/p10/p18。每个样本均
核验 `time_enabled == time_running > 0`，没有 PMU 多路复用；读取计数器在
eval 计时边界外，事件计数包含两次时钟读取，不计内核态。它是独立诊断窗口，
不能把其耗时与上一张时空表混用。p6 瓶颈步的结果为：

| 指标 | Verilator 均值 | GrhSIM 均值 | 逐对变化中位数 |
| --- | ---: | ---: | ---: |
| 自身 eval / µs | 35.652 | 59.074 | +66.33% |
| instructions | 258599 | 351971 | +36.11% |
| branches | 3671.8 | 11098.1 | +202.25% |
| branch misses | 58.27 | 521.99 | +793.45% |
| cycles | 117161 | 193662 | +65.75% |
| IPC | 2.207 | 1.817 | 下降 |
| cycles / duration_ns | 3.286 | 3.278 | 接近 |

这次 p6 差距不能主要归因于频率；多余指令和分支失误都是明确线索，但上述计数
本身不等于各自导致的 stall cycles。p10/p18 相邻两步的 instructions 分别
约少 1.79%/7.99%，branches 却多 72.87%/112.59%，IPC 低 8.45%/23.66%；后续
仍应检查控制流和执行效率，而不是只按静态运算数判断。

#### 活跃 batch 与 Verilator 代码对照

仅重编诊断包装/派发对象，保留实际 compute 对象，采样固定标签中的活跃调用。
p6 的 b184 平均约 7.991 µs，占该探针活跃 compute 总时间 13.21%；b159/b158
分别约 2.202/2.112 µs。p3 和 p18 热点较分散，最大 batch 分别仅占约
2.97%/2.17%；p10 的 b15/b17 约占 6.99%/6.39%。这些数字含探针开销，不能
直接从普通 walltime 中相减。

p6 b184 对同一个 128 位存储数据执行 794 次不同偏移的单 bit 提取；b158/b159
另有 448/512 次。原 helper 先判断移位量范围，再读源 word 并移位，展开后有
大量分支与跨后续拼接存活的 bool 临时值。Verilator 对应的 store-buffer
拆分数据代码使用受限 word 索引并与有效条件按位相与。这提供了两个通用方向：
安全索引后合并有效位，以及将连续纯取位组压缩为短循环。源侧快照缓存已在
§7.60 尝试且没有普通 walltime 收益，本轮没有将其重复作为新候选。

[发现标签与分析脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/eval_after_communication_20261007.py)、
[固定标签](../../build/repcut_grhsim_20260925/active_dispatch_20261003/eval_after_communication_20261007/labels.json)、
[独立时空验证](../../build/repcut_grhsim_20260925/active_dispatch_20261003/eval_after_communication_20261007/timing_results.json)、
[PMU 分时钟结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/eval_after_communication_20261007/pmu_core_results.json)、
[活跃 batch 结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/eval_after_communication_20261007/batch_results.json)。

#### 普通二进制的 GrhSIM / Verilator 对照

独立运行没有逐步或 PMU 探针的普通二进制，完成 4 对 C100000 AB/BA：

| 指标 | Verilator 中位数 | 当前 GrhSIM 中位数 | 逐对变化中位数 | G 更快次数 |
| --- | ---: | ---: | ---: | ---: |
| walltime / s | 23.075 | 13.720 | **−40.542%** | 4/4 |
| Host / s | 23.022 | 13.685 | −40.560% | 4/4 |
| 全局 eval / µs | 83.1140 | 53.5975 | −35.600% | 4/4 |
| 全局 update / µs | 25.4915 | 10.8250 | −57.471% | 4/4 |

这是两条当前实现线的**整机对比**：GrhSIM 已包含此前输入/通信专用优化，
Verilator 保持原路径，不能把 −40.54% 全部归为模拟器计算代码的差距。所有
C100/C100000 均通过配置、功能签名和 Difftest 检查，ELF/image/NEMU 的运行
前后身份一致。绝对时间与 §7.64 属于不同窗口，不直接比较其秒数变化。

[4 对普通结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/eval_after_communication_20261007/ordinary/summary.json)、
[原始运行身份与配置](../../build/repcut_grhsim_20260925/active_dispatch_20261003/eval_after_communication_20261007/ordinary/manifest.json)。

#### 候选一：安全索引后合并有效位

对所有分区的 `grhsim_lshr_bit` 调用使用同一个模板规则：源存储 word 数是 2
的幂且移位量为标量时，先用掩码把地址限制在实际数组容量内，提取 bit 后与
原有效范围相与；其他情况走原 helper。范围同时考虑逻辑 Width、目标 Bit 与
实际数组容量，保留脏 padding、超大/负移位和窄容量时的原有结果。它只读取
普通初始化存储，不涉及 volatile 或跨模型操作移动快照。

全包扫描 17 个计算文件、2218 个调用，实际改变 16 个对象；p6 b184/b158/b159
均覆盖。代表性的 128 位 helper 从条件跳转变为安全索引、移位和 `setb/and`。
但这 17 个对象的可执行 section 总计从 534154 增到 545606 B，并未缩小代码。

4 对普通 AB/BA 的 walltime 中位数为 **13.650→13.760 s**，逐对中位
**+0.585%**，0/4 更快；全局 eval +0.972%，update −0.603%。另 2 对条件 PMU
显示 p6 瓶颈步自身 eval 59.242→57.258 µs（逐对 −3.346%）、branches
−17.979%、branch misses −44.956%，但 instructions +0.762%；p3/p10/p18
的固定瓶颈步均值约增加 1.8%～2.0%。普通运行 p6 全程均值仅约 −0.189%，
p3/p10 全程均值分别 +2.741%/+3.035%。说明目标范围分支有真实成本，但单独
消去它不足以改善整机。本候选不迁入正式默认。

[模板与实验脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bounded_bit_extract_20261007.py)、
[普通结果及分区均值](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bounded_bit_extract_20261007/ordinary_results.json)、
[同一步 PMU 结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bounded_bit_extract_20261007/pmu_results.json)。

#### 候选二：连续动态取位的紧凑循环

本候选独立叠加在当前基线上，**不包含候选一**。识别同一个纯计算块内连续至少
8 次、相同源值/Width/Bit/标量存储类型的单 bit 提取；中间出现其他计算、写入
或副作用则终止分组。将该组改为常量偏移表与禁止展开的循环，结果存入局部
bool 数组，在原消费者位置读取。循环每次仍调用原有 helper，保持原范围语义
与结果快照时点。原型按结构遍历全包，无分区/模块/信号名单，也不使用 profile
决定是否启用。

共识别 **12 个文件、41 组、2135 次取位**；这些对象的可执行 section 总计
480624→335018 B（约 −30.29%，按对象统计，包含可能被链接器合并的模板实例）。
p6 b184 为 228104→167208 B，b158 为 51915→21012 B，b159 为
60895→24917 B。代表性 64 项 helper 是 81 B 标量循环，仍含范围分支、循环
分支、偏移表加载和 bool 数组写入；不是将计算消除，也不是自动获得 SIMD。

两对活跃 batch AB/BA 和另两对条件 PMU 都通过；下表来自各自独立的诊断窗口：

| 诊断指标 | 当前基线 | 紧凑循环 | 逐对变化中位数 |
| --- | ---: | ---: | ---: |
| p6 固定瓶颈步自身 eval / µs（PMU） | 59.2178 | 55.3235 | **−6.577%** |
| 上述步骤全局 eval / µs（PMU） | 66.8514 | 63.3332 | −5.262% |
| p6 瓶颈步 instructions（PMU） | 351971 | 352432 | +0.131% |
| p6 瓶颈步 branches（PMU） | 11098.1 | 12245.6 | +10.340% |
| p6 瓶颈步 branch misses（PMU） | 523.386 | 303.803 | **−41.954%** |
| p6 b184 活跃耗时 / µs（batch） | 8.0546 | 6.1973 | **−23.060%** |
| p6 b159 活跃耗时 / µs（batch） | 2.2183 | 1.0242 | **−53.816%** |
| p6 b158 活跃耗时 / µs（batch） | 2.1349 | 0.9300 | **−56.440%** |

局部改善成立，而且覆盖 p6 两个半周期；其相邻两步合计 PMU 耗时下降约
5.768%。循环增加了动态分支数量，却减少分支失误，不能用“分支条数变少”
解释这个候选；紧凑代码、预测行为和临时值实现共同变化，本轮未精确拆分贡献。

普通 walltime 另完成两个窗口、合计 **8 对 AB/BA**，全部成功样本均保留：

| 窗口 | A walltime 中位数 / s | B 中位数 / s | 逐对变化中位数 | B 更快次数 |
| --- | ---: | ---: | ---: | ---: |
| 首轮 4 对 | 13.685 | 13.680 | −0.037% | 2/4 |
| 复核 4 对 | 13.690 | 13.760 | +0.292% | 2/4 |
| 全部 8 对 | 13.685 | 13.715 | −0.037% | 4/8 |

合并行同时保留组中位数和逐对变化中位数：两者的运算顺序不同，符号也可能
不同，不能相除替代。这里无论看哪种统计，都没有可重复的整机收益。8 对
普通运行中 p6 全程平均 eval 逐对下降 **3.828%（8/8）**，但 p3 上升
**3.099%（8/8）**、p10 上升 **1.377%（8/8）**；全局 eval 反而约 +0.277%。
这些是全程均值，不能与条件瓶颈均值直接相加核算。p3/p10 模型对象未改，
因此其变慢不是新增 RTL 运算导致；链接后的地址、缓存及运行阶段状态仍会变化，
本轮没有进一步区分这些因素，不将其中某一个宣称为已证明的唯一原因。

p6 仅占发现标签的约 13.69%，局部改善也不会等比例传递到所有 step；其他
关键分区的代价足以抵消这一级别的收益。**候选二也不迁入正式默认。** 代码
仍保留 §7.64 的有效默认；两项实验仅作为可复现的通用原型，未按信号名单
选用，也没有修改 Verilator 路径或尝试编译后反馈。

#### 验证边界与后续判断

两项 helper 均通过 Clang23/O3、GCC/O3 和 Clang23 ASan/UBSan 的独立语义
检查，覆盖越界/负移位、非 64 整数宽度及 padding；循环还验证结果快照和
短组/副作用/换源的拒绝边界。原型重编前，原源码重编对象的可装载 section
及重定位与冻结 archive 一致；其余模型对象未变，6859 个 compute 主入口
均保留 64 B 对齐。普通 C100/C100000、两项条件 PMU 以及循环活跃 batch
运行的配置与功能签名均通过，运行前后 ELF/image/NEMU 身份一致。当前结论
限于此 CoreMark 工作负载，没有第二个 workload 的泛化性能证据。

下一轮不再只压缩取位 helper 的单条表达式：如继续此方向，应检查通用的
**动态取位结果直接拼接/归约**模式，争取同时省掉中间 bool 数组和再次装载。
不过采用仍需普通 walltime 收益；p3 的分散关键路径和 p10/p18 另一半周期的
额外执行成本也应一起考虑，不能仅凭 p6 的局部改善决定默认。

[紧凑循环脚本及匹配规则](../../build/repcut_grhsim_20260925/active_dispatch_20261003/grouped_bit_extract_20261007.py)、
[语义检查](../../build/repcut_grhsim_20260925/active_dispatch_20261003/grouped_bit_extract_20261007/semantics/results.json)、
[构建、覆盖与对象身份](../../build/repcut_grhsim_20260925/active_dispatch_20261003/grouped_bit_extract_20261007/build.json)、
[8 对普通结果与逐分区均值](../../build/repcut_grhsim_20260925/active_dispatch_20261003/grouped_bit_extract_20261007/ordinary_results.json)、
[条件 PMU](../../build/repcut_grhsim_20260925/active_dispatch_20261003/grouped_bit_extract_20261007/pmu_results.json)、
[活跃 batch 对照](../../build/repcut_grhsim_20260925/active_dispatch_20261003/grouped_bit_extract_20261007/batch_results.json)、
[统计脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bit_extract_results_20261007.py)。

### 7.66 动态取位与标量拼接融合（2026-10-07）

继续 §7.65 的建议，以 §7.64 的正式默认为 A，普通 ELF SHA-256 仍为
`2ca12a413bdacfb86733f075ae8584b5f94ab445ed1561653f1984a6d65e6ade`。
本节候选没有叠加上一节未采用的全包安全索引或 bool 数组循环；只对完整满足
融合条件的生产者/消费者区域做变换。配置仍为 node030 CPU96–127、NUMA1、
Host105、N=K=32、all-spin、Clang23/O3、ASLR off、CoreMark、C100000，全部
普通成功样本保留，没有空闲门槛或慢样本剔除。

#### 通用结构与语义边界

“生产者”指连续执行的单 bit 动态提取；“消费者”指紧接其后的整数拼接。
原型扫描全包，要求 8～64 个连续纯取位有相同源、位宽、目标 bit 和移位量
存储类型，且所有结果仅由紧接着的这一处拼接使用；每个拼接位具有相同的纯
变换表达式，只允许当前取位结果与当前移位量随 lane 改变。遇到写入/副作用、
额外消费者、不连续的输出位或不同表达式即拒绝，不跨 supernode 移动快照。

例如原先先得到 `b0=data[s0]`、`b1=data[s1]` 等，再计算
`((b0 & gate(s0)) << 63) | ((b1 & gate(s1)) << 62) | ...`。
这里 `data[s]` 是原 GrhSIM helper 定义的动态 bit 提取，越界仍按原语义处理；
`gate(s)` 是已有的纯整数条件。新循环每次直接取一位、计算其条件，然后令
`result = (result << 1) | next_bit`，最终返回拼接整数。它省掉上一节循环的
bool 数组存储和消费者的再次装载，并保留每个 lane 原有的整数 cast 与末位
掩码。这里只验证了**标量拼接**，未声称已经覆盖任意 OR 归约或宽拼接。

全包匹配 **5 个计算文件、29 组、1856 次取位**，当前命中恰好都在 p6，分别为
b158/b159/b174/b175/b184；这是结构匹配结果，没有用这些编号筛选。其他可疑
区域未满足完整融合条件时保留原实现。两种实现分别为：

- F：循环内继续使用原动态取位 helper。
- FB：仅在上述融合循环内部采用 §7.65 已验证的安全索引 helper；其余调用
  不变。安全索引先把地址限制在实际数组容量内，再与原有效条件相与，不做
  越界读；不符合模板形状时回退原 helper。

| 修改对象的可执行 section 合计 / B | 当前基线 | F | FB |
| --- | ---: | ---: | ---: |
| 5 个对象合计 | 365140 | 178223 | 177742 |
| p6 b158 | 51915 | 9641 | 9526 |
| p6 b159 | 60895 | 10466 | 10334 |
| p6 b184 | 228104 | 145243 | 145048 |

F/FB 的总量分别约缩小 51.19%/51.32%；此处按对象中的可执行 section 统计，
不是整个程序体积。F 的代表性 helper 仍有范围跳转；FB 的实际 Clang23 汇编
用受限地址、`setb/setbe/and` 和寄存器内移位累积，循环体只保留回边条件跳转，
没有中间 bool 数组。均未依赖 profile 或编译后反馈选择区域。

#### F 的普通性能与局部归因

F 先完成 4 对普通 AB/BA，C100 初始化及全部 C100000 均通过 Difftest：

| 指标 | A 中位数 | F 中位数 | 逐对变化中位数 |
| --- | ---: | ---: | ---: |
| walltime / s | 14.140 | 14.170 | **+0.319%** |
| Host / s | 14.0990 | 14.1285 | +0.338% |
| 全局 eval / µs | 55.5440 | 55.7345 | +0.436% |
| p6 全程平均 eval / µs | 36.9370 | 35.1835 | **−4.846%** |
| p3 全程平均 eval / µs | 46.9700 | 48.2665 | +2.603% |

walltime 0/4 严格更快，其中一对按 0.01 s 精度持平；Host 则四对均略慢。
p6 四对均改善，但 p10/p18 全程平均 eval 也分别上升约 1.809%/1.788%。
这些结果只使用本窗口的 A/B，不与上一节的绝对秒数相减。

条件诊断继续使用 §7.65 独立冻结的 3148-step 标签，其中 p6 有 431 个瓶颈步。
另 2 对 PMU（无多路复用）显示 p6 在这些步骤中的自身 eval
60.9632→56.2298 µs，逐对 **−7.764%**；instructions −0.403%、cycles
−7.534%、branch misses −37.420%，branches 则 +13.611%。相邻两步合计
95.3426→88.4082 µs，逐对 −7.273%。这些带探针的耗时不是普通运行时间。

再做独立 2 对活跃 batch 对照：b184 为 8.2498→6.0607 µs（−26.536%），
b159 为 2.2890→1.0434 µs（−54.406%），b158 为 2.1901→0.9303 µs
（−57.523%）。局部路径确有改善，但仍未形成普通 walltime 收益。

[结构规则、构建与运行脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fused_bit_extract_20261007.py)、
[F 构建与覆盖](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fused_bit_extract_20261007/build.json)、
[FB 构建与覆盖](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fused_bounded_bit_extract_20261007/build.json)、
[F 普通结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fused_bit_extract_20261007/ordinary_results.json)、
[F 条件 PMU](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fused_bit_extract_20261007/pmu_results.json)、
[F 活跃 batch](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fused_bit_extract_20261007/batch_results.json)、
[F 代表性汇编](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fused_bit_extract_20261007/representative.asm)、
[FB 代表性汇编](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fused_bounded_bit_extract_20261007/representative.asm)。

#### FB 的普通性能及最终判断

FB 另完成 4 对普通 AB/BA；它与 F 分别对照同一个冻结 A，不将两个窗口的
候选绝对时间直接相减：

| 指标 | A 中位数 | FB 中位数 | 逐对变化中位数 |
| --- | ---: | ---: | ---: |
| walltime / s | 14.150 | 14.245 | **+0.707%** |
| Host / s | 14.1165 | 14.2045 | +0.623% |
| 全局 eval / µs | 55.5415 | 55.8290 | +0.547% |
| 全局 update / µs | 10.9670 | 11.0595 | +0.950% |
| p6 全程平均 eval / µs | 37.0455 | 35.6235 | **−4.218%** |
| p3 全程平均 eval / µs | 46.6185 | 47.5425 | +1.937% |
| p18 全程平均 eval / µs | 35.9250 | 36.5635 | +1.965% |

walltime 与 Host 均 0/4 更快，p6 全程均值则 4/4 改善。另 2 对条件 PMU
显示 p6 固定瓶颈步自身 eval 60.7924→56.2594 µs，逐对 **−7.456%**；
相邻两步合计 95.1328→88.7170 µs（−6.744%）。其 branches
11098.1→10692.7（−3.653%），branch misses 523.921→313.871
（−40.091%），但 instructions 351971→353369（**+0.397%**）。安全地址
计算、无条件读取和掩码仍需要执行；去掉范围跳转没有同时减少动态指令数量。
本轮未单独测量这些额外操作分别贡献了多少 cycles。

**F 与 FB 均不迁入正式 emitter 或默认流程。** 原型证明了“动态取位与最终
拼接融合”在目标计算块上有效，但两组普通 walltime 都没有净收益。全局阶段
由每步最后完成者决定，p6 只占原发现标签的约 13.69%；不能把 p6 自身约
7%～8% 的条件改善当作整机改善，也不能把各分区的全程平均值相加解释 barrier
时间。其他关键分区/阶段的退化与局部收益同时存在，采用仍以普通 walltime
为准。

做了一次静态身份核验以限制归因：p3 的 **341 个 compute 入口地址与函数长度
全部不变**，原模型对象也未修改；其中 292 个函数链接后字节有变化，涉及
引用地址的重定位。p10/p18 的入口则发生移动，但全部仍满足 64 B 对齐。
因此本轮 p3 退化不能简单归因为入口移动或失去 64 B 对齐；也不能因源对象
没改就假设实际运行必须同速。数据/调用目标布局、缓存及进入阶段时的运行
状态尚未分离，本轮没有做布局或对齐扫参。

条件 PMU 与普通运行有不同插桩对象，p3 在 F 的条件 PMU 中反而约 −4.01%，
而普通运行全程平均为 +2.60%；两者不仅二进制不同，统计集合也不同。这再次
说明不能用插桩窗口中未改分区的变化，直接解释普通整机性能。后续应优先核对
**普通 ELF 上这些关键分区的退化来源**，再决定是否进一步推进此融合模式；
在此之前继续微调 p6 的这一个 helper，整机收益空间已较有限。

#### 验证与产物

F/FB 各通过 Clang23/O3、GCC/O3 与 Clang23 ASan/UBSan 的 helper 检查，以及
由实际源改写器生成的 before/after 差分程序（8/26/64 项，随机输入并校验输入
不被改变）。helper 覆盖零宽、非整 word 宽度、目标 bit 越界、负/大移位、
脏 padding 和不同 lane 变换；结构检查拒绝短组、副作用、额外消费者和错误
位序。两侧构建均先重编原源码并核对可装载 section/重定位，再替换仅 5 个
计算对象；6859 个 compute 主入口均保持 64 B 对齐，Verilator 路径未改。

两组普通测试合计 16 次 C100000、两组 PMU 合计 8 次、F 活跃 batch 4 次，
**28 次 C100000 均通过 Difftest**；各组的 C100 初始化检查亦通过。功能签名
仍为 `pc=0x80000c0c/instructions=240349/cycles=99996/guest_cycles=100001/steps=200102`，
每组运行前后的 ELF/image/NEMU 身份一致。未对无整机收益的原型执行正式
emitter 迁移；本节结果限于当前单 workload。

[FB 普通结果与分区均值](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fused_bounded_bit_extract_20261007/ordinary_results.json)、
[FB 条件 PMU](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fused_bounded_bit_extract_20261007/pmu_results.json)、
[F 语义验证](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fused_bit_extract_20261007/semantics/results.json)、
[FB 语义验证](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fused_bounded_bit_extract_20261007/semantics/results.json)、
[F 链接身份核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fused_bit_extract_20261007/audit.json)、
[FB 链接身份核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fused_bounded_bit_extract_20261007/audit.json)。

### 7.67 融合实验中未改分区的普通二进制退化归因（2026-10-07）

接续 §7.66，只诊断原 helper 的融合候选 F，不继续增加取位优化变体。A 是
§7.64 的 `wide_communication_20261007/wide_formal/emu`，F 是
`fused_bit_extract_20261007/candidate/emu`，SHA256 分别为
`2ca12a413bdacfb86733f075ae8584b5f94ab445ed1561653f1984a6d65e6ade` 与
`c721f179a2dc77fd57b94471ef8cbbd5782148c96f22544241ee563847cddad0`。
两者沿用同一 CoreMark/NEMU、Clang23/O3、N=K=32、all-spin、Host105、
node030 CPU96–127、NUMA1、ASLR off、C100000；正式默认与 Verilator 路径未改。

#### 普通复测与链接审计

新增 4 对普通 AB/BA，F 相对 A 的逐对变化中位为：walltime **+0.459%**，
Host +0.449%，p3 eval **+2.606%**（4/4 更慢）。此处和下表的分区 eval
均为完整 200102 steps 的平均，不是“该分区成为瓶颈时”的条件均值。

Archive 仍然只有 p6 的 5 个计算对象改变。进一步逐指令比较 p3 的全部
341 个 compute、5 个 commit 及 1 个 eval 调度函数：函数入口、长度、
指令次序、运算及分支形态一致，变化的 **6076 处指令全部只是 RIP 相对寻址
位移**；引用的 `.rodata` 地址统一前移 **184320 B**，每个目标前 16 B
内容相同。RIP 相对寻址即“从当前指令位置加一个距离找到常量”；距离变了
并不等于新增了一次 RTL 计算。不能把这一静态差异直接解释为全部性能原因。

#### 原 ELF 上的硬件采样

直接对 A/F 的普通 ELF 做两组各 4 对、user-only、继承到 worker 的低频
`perf record`；不重新编译模型、不加入 eval/batch 探针。按每个完整运行累加
落在分区 compute/commit/eval 符号内的 sample period，再做逐对比值；不比较
所有线程混在一起的样本百分比。下列为统计估计，存在采样误差和 skid，且未含
无分区符号的共享 helper。采样运行的 walltime 不混入普通性能结果。

| F / A，配对中位变化 | p3 | p6 | p10 | p18 |
| --- | ---: | ---: | ---: | ---: |
| cycles（第一组） | +2.120% | −4.869% | +3.683% | −0.022% |
| retired instructions | +0.155% | +0.551% | +1.480% | +0.884% |
| 每条指令 cycles，先逐次计算再配对 | +2.524% | −5.256% | +1.540% | −1.254% |
| 前端未供给指令的 dispatch 空槽 | +3.736% | −9.905% | +5.466% | +3.320% |
| cycles（第二组） | +2.465% | −4.829% | +2.480% | +0.635% |
| 指令缓存 miss | **+10.395%** | −2.226% | **+8.723%** | +2.180% |
| demand 数据缓存补充 | +0.348% | −2.037% | +5.873% | +1.832% |
| L1 DTLB miss | −1.960% | +3.942% | −2.433% | +9.968% |

p3 指令缓存 miss 的四对增幅为 **10.188%、10.014%、10.898%、10.601%**，
每次约 5600→6200 个样本，方向一致；p10 的四对亦都增加约 8%～9%。相反，
p3 数据缓存补充只在约 ±1.4% 内波动，DTLB 样本较少且正负混合。后端阻塞
空槽虽有 +16.69% 中位数，但四对为 −0.75%、−15.67%、+50.43%、+34.13%，
不能据此认定统一的数据访问瓶颈。

因此目前更明确的机制线索是：**相同计算在 CPU 中的执行效率下降，尤其是
取指/指令缓存行为变化**，而非 p3 新增计算量。cycles 的增长也说明不能只用
降频解释这次退化；sysfs 频率瞬时快照不代表 eval 内有效频率，本轮不据此
宣称完全排除频率因素。运行时页面快照显示两侧模型代码页和匿名页均位于
NUMA1，没有观察到跨 NUMA 落点差异；这不等于证明物理页面/缓存状态相同。

#### 一次布局对照与堆起点单因素检查

构建 P：保留 F 的融合计算，在 5 个改写对象 `.text` 的不可达尾部填充，
恢复基线代码布局。所有基线 compute 符号入口均恢复，p3 的 341 个 compute、
5 个 commit 及 eval 函数的**地址、长度、全部机器码逐字节与 A 一致**。
这是诊断控制，不是建议生产构建保留填充。

A/F/P 按三组的全部 6 种排列交错执行，共 18 次 C100000：

| 配对中位变化 | F / A | P / A | P / F |
| --- | ---: | ---: | ---: |
| walltime | +0.927% | +0.432% | −0.705% |
| Host | +0.865% | +0.419% | −0.686% |
| 全局 eval | +1.234% | +0.257% | −0.739% |
| p3 eval | **+4.267%** | **+2.023%** | **−1.167%** |
| p6 eval | −4.526% | −4.049% | +1.034% |
| p10 eval | +2.098% | +1.396% | −0.382% |
| p18 eval | +1.725% | +0.026% | −1.573% |

P 相对 F 的 p3 在 6/6 轮变快，但相对 A 仍 6/6 变慢。因此“只是 p3 的入口
地址/指令字节变了”不足以解释现象，布局对其他函数、数据、阶段间执行状态的
连带影响仍须考虑。各列先按各轮算比值再取中位，不能把三列百分比相减当作
严格的贡献分解。该窗口 walltime 中途有整体变化，全部成功样本仍保留，未作
空闲门槛、重试选样或离群剔除。

另外构建 H：只把 F 最后一个可写 LOAD 段的零填充尾部扩展 **180224 B**，
恢复 A 的初始堆起点，所有已有 section 地址/字节及全部函数均保持 F 原样。
运行 maps 确认堆起点由 `0x55555b36a000` 恢复为 A 的 `0x55555b396000`。
F/H 4 对普通 AB/BA：p3 **−0.516%**（3/4）、walltime **−0.071%**（2/4）、
Host −0.097%；量级小且整机方向混合，堆起点变化不足以解释主要退化。

[普通复测](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fusion_regression_20261007/ordinary_results.json)、
[链接后逐指令核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fusion_regression_20261007/linked_audit.json)、
[普通 ELF cycles/指令/前端采样](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fusion_regression_20261007/perf_lowrate/results.json)、
[普通 ELF 缓存/TLB 采样](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fusion_regression_20261007/memory/perf_lowrate/results.json)、
[P 构建核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fusion_regression_20261007/padded_build.json)、
[A/F/P 三组交错数据](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fusion_regression_20261007/layout_ordinary/results.json)、
[H 构建核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fusion_regression_20261007/heap_restored/build.json)、
[F/H 普通对照](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fusion_regression_20261007/heap_ordinary/summary.json)、
[堆地址及页面快照](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fusion_regression_20261007/heap_ordinary/placement/snapshots.json)。

#### 恢复布局后的缓存复核与阶段结论

继续对已经构建的 P 与 A 做 4 对原 ELF 缓存采样，不增加新的布局变体：

| P / A，配对中位变化 | p3 | p6 | p10 | p18 |
| --- | ---: | ---: | ---: | ---: |
| cycles | +3.690% | −4.494% | +0.748% | +0.326% |
| 指令缓存 miss | **+10.100%** | −3.334% | +5.701% | +1.004% |
| demand 数据缓存补充 | +1.442% | −2.963% | −0.955% | −1.357% |
| L1 DTLB miss | −0.086% | +5.502% | −10.310% | +9.302% |

p3 指令缓存 miss 的四对增幅为 8.914%、10.637%、10.661%、9.563%；
在 p3 函数已与 A 逐字节相同的情况下，这一退化仍存在。因此本轮**没有证明
“p3 常量地址移动导致全部退化”**，也不能用“恢复了 p3 自身机器码”推导
它会恢复相同的缓存命中率。三组普通对照证明布局影响性能，但 P 的剩余退化
说明，仍要区分其他函数/物理页面的缓存行为、同步等待与进入 eval 时的状态。
这些具体触发因素尚未单独控制，不写成已经确认的唯一根因。

截至本节，§7.66 的 4 对、当前复测 4 对、三组对照中的 6 轮合计 **14 对同一
A/F 普通 ELF**：p6 eval **−4.873%（14/14 更快）**，p3 eval
**+3.577%（14/14 更慢）**，walltime **+0.534%（仅 1/14 更快）**。
这是各窗口内部形成比值后合并的中位数，不把不同时段的绝对秒数直接比较。
融合的局部收益成立，整机净收益仍不成立；**F/P/H 均不进入默认**。

本轮到此收住布局控制。后续优先在当前默认 A 上寻找 p3 跨多个 batch 共有的
重复拼接/加载模式，减少需要执行和取入指令缓存的代码；按通用结构匹配，
同时检查指令缓存指标及普通 walltime。不要继续只调 p6 的单个 helper，或
将手工填充、指定分区/符号的地址安排做成生产优化。普通样本中 p3 的热点
较分散，第一组 cycles 采样里最大单函数 commit/b344 约占 p3 eval 归属样本的
2.80%，最大 compute/b46 约 2.46%；单函数低频采样的涨跌不足以当作精准的
贡献排序，后续应以结构覆盖率及独立验证决定取舍。

用于本节结论的 **34 次普通 + 24 次低频采样 = 58 次 C100000** 全部通过
Difftest 和相同终态签名；另 13 次 C100 初始化检查通过。三组计数采样均核对
无 lost/throttle 记录，运行前后 ELF/image/NEMU 身份不变。A/F/P/H 的
6859 个 compute 主入口均保留 64 B 对齐，P 的 347 个 p3 eval 相关函数身份
与 A 相同，H 的所有已有函数与 F 相同。没有新增正式 emitter 修改。

[P 缓存/TLB 复核](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fusion_regression_20261007/memory_padded/perf_lowrate/results.json)、
[14 对同一 A/F 的普通结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fusion_regression_20261007/all_natural_windows.json)、
[最终结果与身份核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fusion_regression_20261007/summary.json)、
[诊断采样脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fusion_regression_20261007.py)、
[布局审计与控制脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fusion_layout_audit_20261007.py)、
[三组普通对照脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fusion_layout_compare_20261007.py)、
[堆起点控制脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fusion_heap_control_20261007.py)、
[缓存采样脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fusion_memory_profile_20261007.py)、
[最终汇总脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/fusion_regression_summary_20261007.py)。

### 7.68 静态取位写回的通用紧凑循环：代码缩减与执行成本（2026-10-07）

承接 §7.67，在当前已保留的 GrhSIM 线 A 上寻找跨 batch 重复模式。本轮完成
两个通用原型、各两窗口普通 AB/BA，以及条件 PMU/原 ELF 采样；**两版均无
walltime 净收益，不进入默认，没有修改正式 emitter 或 Verilator 路径。**

基线仍为 `wide_communication_20261007/wide_formal/emu`，SHA-256
`2ca12a413bdacfb86733f075ae8584b5f94ab445ed1561653f1984a6d65e6ade`，
保留已有计算优化、并行 input-load、标量跳过未变化写入及宽通信源复用，
不叠加 §7.66 的 p6 融合候选。运行固定 node030 CPU96–127、NUMA1、
N=K=32、all-spin、ASLR off、Clang23/O3、CoreMark、C100000；保留全部
功能通过的样本，不设空闲门槛，不按耗时重试或剔除。

#### 结构、覆盖与构建核验

匹配“同一宽值的常量单 bit slice → 独立 bool 槽写回 → 精确变化通知”的
连续纯计算区域：至少 16 项、目标存储不重复、区域内没有其他语句或副作用，
最多 64 个不同通知目标。循环仍读取每个目标旧值、写入新值，并只通知实际
发生变化的输出原有的消费者；不扩大活动范围、不跳过应有写回。陌生通知写法、
有副作用的输入表达式、歧义 alias 等保守拒绝。全包按上述结构选择，未按
分区、模块、信号名或 profile 白名单筛选。

- **M：通知掩码版**。每项保存目标相对索引、源 bit 索引及 64 位消费者掩码；
  循环合并变化通知，末尾应用通知结果。本 workload 的表项为 16 B。
- **B：输出位图版**。循环每批至多 64 项，仅返回哪些输出发生变化，循环外
  用常量掩码合并消费者通知。本 workload 两种索引均可用 16 位，表项降为
  4 B，并省去循环内的消费者掩码加载；更大索引保留 32 位表示。

两版均扫描完整的 6994 个 sched 源文件，匹配 **27 个分区、160 个文件、
429 组、19444 次写入**；p3 为 10 个文件、1354 次写入，p6 为 13 个文件、
2266 次写入。使用基线实际源文件映射保留之前的源级改写；160 个文件逐一
重编译原版，核对其已分配 section 和 relocation 与 A 归档对应成员逐字节
一致，再替换候选对象。不能把未包含旧改写的重新生成快照直接当作 A 的源码。
两版的 6859 个 compute 主入口均保持 64 B 对齐。

| 静态变化，相对 A | M 通知掩码版 | B 输出位图版 |
| --- | ---: | ---: |
| 整个 ELF `.text` | −634432 B | −621440 B |
| 整个 ELF `.rodata` | +311384 B | +79776 B |
| p3 涉及的 10 个对象可执行节合计 | 219864→174695 B（−20.544%） | 219864→174381 B（−20.687%） |

最后一行只描述被改写对象，包含各对象中的 helper，**不是整个 p3 的代码
缩减比例**。M ELF 为 `aaf9ce3e8c6e02cd61dff12f394e815ddcfa4b4de01014f5f16b306f32500447`，
B ELF 为 `8de49263547d6205fe1798849f28f821aa794740dcc67b5783cf32369436376d`。

#### 普通 walltime 与固定瓶颈步计数

每版各 8 对普通 AB/BA，分两个窗口各 4 对。百分比统一为各窗口内部先配对
计算 `(candidate / baseline − 1) × 100%`，再对 8 个比值取中位；绝对秒数
单独列中位数，不能用它们的比值替代配对统计，也不能把 M/B 不同时段的
绝对耗时直接相减解释收益。

| 普通运行指标 | M / A，8 对 | B / A，8 对 |
| --- | ---: | ---: |
| walltime 中位数 | 13.590→13.740 s | 13.630→13.750 s |
| walltime 配对变化 | **+1.105%**，3/8 更快 | **+0.801%**，2/8 更快 |
| Host 配对变化 | +1.096% | +0.803% |
| 全局 eval | +1.539% | +1.195% |
| p3 全程平均 eval | **+2.021%** | **+2.128%** |
| p6 全程平均 eval | +1.030% | +1.874% |
| p10 全程平均 eval | +1.523% | −0.561% |
| p18 全程平均 eval | +1.786% | +1.652% |

两版另各做 4 对条件 PMU，沿用 §7.65 独立发现并冻结的瓶颈步标签，p3/p6/
p10/p18 分别为 1136/431/437/518 步。以下是**同一标签步上的配对计数变化**，
不是重新挑选候选自己的最慢步，也不是上表的全程平均 eval：

| 分区 | M 指令数 | B 指令数 | M cycles | B cycles |
| --- | ---: | ---: | ---: | ---: |
| p3 | +2.372% | +2.444% | +0.375% | +2.204% |
| p6 | +6.484% | +7.030% | +0.772% | +2.077% |
| p10 | +0.834% | +0.920% | +0.663% | +0.073% |
| p18 | +0.875% | +0.952% | +1.110% | +0.949% |

反汇编确认 M 的 `(0 − changed) & mask` 被 Clang 变成了按 changed 判断的
条件分支；B 确实消除了这个数据相关分支。p6 的分支总数增量由 M 的
**+54.461%** 降为 B 的 **+19.133%**，p3 则由 +14.236% 降为 +5.135%。
但 B 还需要为每项定位变化位图中的 bit；动态索引、动态移位、循环控制及
helper 调用的成本仍在，实际指令数没有随表项缩小或分支减少而下降。

#### 缓存收益为何没有转化为 walltime 收益

对 A/M 的**普通 ELF**再做 4 对低频采样。共享 helper 的样本按原始 TID
归属：只有 compute 样本能唯一确定该线程所属分区时才计入，避免因 helper
符号不含 `Gpart_3` 而漏算候选工作。以下为整次运行的采样估计，不与条件
PMU 或普通 walltime 混算：

| p3 采样范围，M / A | cycles | 指令数 | 指令缓存 miss |
| --- | ---: | ---: | ---: |
| 模型函数及共享 GrhSIM helper | +2.122% | +2.177% | **−0.816%** |
| 被改写 compute 块及新 slice helper | **+9.738%** | **+30.876%** | −5.429% |

p3 整体指令缓存 miss 的 4 对变化均为负，分别 −0.728%、−0.632%、−0.904%、
−1.304%；因此缩减代码的缓存收益存在，但幅度有限。原来的常量 bit/目标索引
变成表项读取与运行时地址/移位计算，增加了真实执行工作。被改写区域的 cycles
上升，整个 p3 的 cycles 也上升；不能只用频率降低解释，更不能从静态代码
缩小约 20% 推导 eval 应改善约 20%。具体 walltime 差额还包含频率、同步和
其他分区的变化，本轮没有把这些因素强行分解为可相加的贡献。

本轮阶段结论：**“将重复静态取位收进通用索引循环”暂不成立为默认优化。**
若继续这一类模式，应先验证能同时保留常量索引、源字读取复用并减少实际
操作的改写；代码体积和分支总数只作为辅助证据。两个原型停留在 build 实验
目录，不引入指定分区启用规则，也不继续做地址/对齐扫描。

两版均通过 Clang23/O3、GCC/O3、Clang23 ASan+UBSan 的实际生成语句前后
差分检查：每种构建 6 个 fixture、3072 次状态转换，覆盖跨 word、越界、空
源数组、重复输入、64 个通知目标及较大目标偏移，并验证不合格结构拒绝改写。
共 **32 次普通 + 16 次条件 PMU + 8 次原 ELF 采样 = 56 次 C100000**，
另 14 次 C100 初始化检查，均通过；完整运行全部启用 Difftest、终态签名相同，
测量前后 ELF/image/NEMU 身份保持不变。

[最终汇总与身份核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/static_slice_groups_20261007/summary.json)、
[M 普通结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/static_slice_groups_20261007/ordinary_results.json)、
[B 普通结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/static_slice_bitmap_20261007/ordinary_results.json)、
[M 条件 PMU](../../build/repcut_grhsim_20260925/active_dispatch_20261003/static_slice_groups_20261007/pmu_results.json)、
[B 条件 PMU](../../build/repcut_grhsim_20260925/active_dispatch_20261003/static_slice_bitmap_20261007/pmu_results.json)、
[原 ELF 按线程归属的采样](../../build/repcut_grhsim_20260925/active_dispatch_20261003/static_slice_groups_20261007/original_elf/perf_lowrate/worker_results.json)、
[M 改写与构建脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/static_slice_groups_20261007.py)、
[B 改写脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/static_slice_bitmap_20261007.py)、
[生成语句差分验证](../../build/repcut_grhsim_20260925/active_dispatch_20261003/static_slice_groups_verify_20261007.py)、
[汇总核验脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/static_slice_summary_20261007.py)。

### 7.69 按宽输入实际读取位过滤初始激活：通用原型与两窗口验证（2026-10-07）

承接 §7.68，本轮改为减少无效计算块激活。**通用生成代码原型在两窗口合计
8 对普通 C100000 AB/BA 中全部更快，walltime 配对中位改善 4.593%。**
已完成静态覆盖、语义差分、整机 Difftest、初始激活/dispatch 入口计数及固定
瓶颈步 PMU。原型保留在 build 目录；尚未移入正式 emitter，也未改变仓库
默认选项或 Verilator 路径。本节基线不包含 §7.66–7.68 的未采纳候选。

基线 A 为 `wide_communication_20261007/wide_formal/emu`，SHA-256
`2ca12a413bdacfb86733f075ae8584b5f94ab445ed1561653f1984a6d65e6ade`；
候选 B 为 `input_bit_demand_20261007/candidate/emu`，SHA-256
`b49e63bddec078df9dc7e56570d903696c6b3db80535102662e6688cf0828779`。
固定 node030 CPU96–127、NUMA1、Host105/lane9、N=K=32、all-spin、
ASLR off、Clang23/O3、CoreMark、C100000。保留全部功能通过的普通样本，
不设空闲门槛，不按耗时筛选或重跑。

#### 原因、规则与边界

`grhsim_cpp.cpp` 的 `inputSeedGroups` 按输入对应的计算块集合合并触发：
只要整个输入与 `prev_in_*` 不等，就激活所有对应的 head。head 指由输入
直接触发、拥有活动位的计算块（supernode），不是线程或整个 batch。
例如 p3 的一个 22×64 位输入，任意位变化都会触发 42 个 head；其中 36 个
可证明只读取固定的部分位。该例仅用于解释，**不参与候选选择**。

原型扫描基线实际源文件映射中的全部 **6994 个 sched 文件**，按如下通用
条件推导每个“输入→head”的依赖掩码：

- 计算块必须由已知纯计算/寄存器读取操作构成；DPI、系统任务、写操作、
  memory read 及未知种类保持原判定。
- 对这个输入的每一次可执行代码引用，都必须是可解析的常量 bit 提取。
  收集全部读取位并合并为每个 64 位 word 的掩码；整值读取、动态索引、
  alias、越界及无法证明的引用保守回退。没有直接读取证据的隐含依赖不删除。
- 保留原来的整输入变化外层判断；在其内部共享必要 word 的新旧值 XOR，
  只有 `XOR & 依赖掩码` 非零才 OR 入对应活动位，相同条件的 head 继续合并
  写入活动掩码。普通候选不新增持久状态、前值副本或第二套活动位图。
- 只过滤该输入贡献的激活，其他输入仍按各自条件 OR 入；状态/事件通知、
  首次全激活、后续固定点传播和 `pending_eval_round` 的原有处理均保留。
  不通过清除现有活动位来实现过滤。

例如一个块只读取总线 bit3、bit140，则仅比较 word0 的 bit3 和 word2 的
bit12；总线其他位变化时不因该输入触发这个块。如果状态或另一输入同时
触发它，它仍会执行。因此本轮无需拆分原来的计算块，也没有按分区、模块、
信号名、profile 或编译结果设置白名单。

覆盖 **32 个分区、3926 个 head、6219 条输入→head 依赖**；p3/p6 分别涉及
509/275 个 head。只替换 32 个 `model_eval.o`；全部 compute 对象与 A 逐字节
相同。32 个原 eval 文件逐一重编译，已分配 section 和 relocation 均与 A
归档对应成员一致，6859 个 compute 主入口仍全部 64 B 对齐。

#### 普通性能与条件 PMU

两窗口各 4 对，窗口内部先计算 `(B/A−1)×100%`，再合并 8 个配对比值取
中位数；绝对值列分别取 8 次运行的中位数，不能用两列中位数相除替代配对
结果。第一/第二窗口 walltime 配对变化分别为 −4.593%/−3.733%。

| 普通指标 | A 中位数 | B 中位数 | 8 对配对变化 |
| --- | ---: | ---: | ---: |
| walltime | 13.375 s | 12.735 s | **−4.593%，8/8 更快** |
| Host | 13.3335 s | 12.6980 s | −4.591% |
| 全局 eval | 52.154 µs/step | 48.850 µs/step | **−6.280%** |
| p3 全程平均 eval | 45.5595 µs/step | 37.3695 µs/step | **−16.148%** |
| p6 全程平均 eval | 35.1260 µs/step | 31.2695 µs/step | **−10.657%** |
| p10 全程平均 eval | 31.2810 µs/step | 30.5620 µs/step | −2.207% |
| p18 全程平均 eval | 33.3915 µs/step | 31.9610 µs/step | −4.545% |
| 全局 input-load | 2.0825 µs/step | 2.2195 µs/step | +6.149% |
| 全局 update | 10.8045 µs/step | 10.7180 µs/step | −0.690% |

另做 4 对条件 PMU，仍用 §7.65 的独立基线发现标签，p3/p6/p10/p18 分别
1136/431/437/518 步。**这是原基线瓶颈步上的同一步比较，不是候选重新挑出
的瓶颈步分布，也不是上表全程平均。** 探针与普通 walltime 分开运行。

| 固定原基线瓶颈步 | 指令数变化 | cycles 变化 | eval 时间变化 | 有效频率变化 |
| --- | ---: | ---: | ---: | ---: |
| p3 | **−20.346%** | **−17.326%** | −18.210% | +0.349% |
| p6 | **−16.680%** | **−12.571%** | −13.023% | +0.784% |
| p10 | −0.008% | −0.953% | −1.912% | +1.178% |
| p18 | −0.046% | −1.873% | −4.258% | +1.772% |

p3/p6 的收益有实际指令和 cycles 减少支持，不以频率变化解释。其分支 miss
反而分别增加 3.813%/6.230%，IPC 分别降低 3.626%/4.698%；整体仍更快，
因为省掉的执行工作超过新增位比较及分支的成本。不能把 p10/p18 的时间
改善解释为同等幅度的工作量减少：它们在这些瓶颈步上的指令数基本没变。

#### 多少触发确实没有必要

另做 2 对 AB/BA 激活诊断。每个分区固定采样 3148 步，分别构造原始输入
seed 与过滤后的 seed，再与保留的其他活动位 OR 合并，避免把其他输入同时
触发同一 head 的情况误算成可过滤。诊断数组只存在于诊断 ELF。

| 范围：全部固定采样步 | p3 | p6 | p10 | p18 |
| --- | ---: | ---: | ---: | ---: |
| 可过滤 head 的初始激活数，A→B，个/步 | 291.224→67.420 | 89.596→26.772 | 11.131→5.699 | 53.622→22.591 |
| 该计数变化 | −76.849% | −70.120% | −48.794% | −57.869% |
| batch 入口处对应活动位的计数变化 | **−62.372%** | **−57.003%** | −25.405% | −22.200% |

初始激活被过滤后，前面的计算仍可能再次通知这个 head。第二种计数在实际
batch 调用前读取活动位，包含各固定点轮次，可见降幅小于初始过滤量。
**它仍不是精确的 supernode 执行次数**：同一 batch 内的传播也可能继续
触发计算；因此这些计数不能直接换算成省下的 eval 时间。

只看冻结的原基线瓶颈步时，p3 的相应 batch 入口计数为
319.590→118.148（−63.031%），p6 为 211.735→80.619（−61.924%）。
p10/p18 则只下降 0.657%/1.498%，与其条件指令数几乎不变相符。各重复
运行的计数完全一致，A/B 的原始与过滤后初始联合计数也逐项一致。

#### 验证、限制与后续落点

Clang23/O3、GCC/O3、Clang23 ASan+UBSan 三种构建分别通过 150000 次
状态转换差分：覆盖跨 word 位、多个输入 OR、状态/事件已置位、首次 eval、
重复输入和完整读取/动态引用保守回退。另核验活动掩码打包与语法拒绝规则。
共 **16 次普通 + 4 次激活诊断 + 8 次条件 PMU = 28 次 C100000** 全部通过
Difftest 与相同终态签名；另 8 次 C100 初始化检查通过。最终核对 2425 个
源码、头文件、链接输入及运行输入身份，均未变化。

代价是 32 个 eval 对象的可执行节合计从 367028 增为 895359 B（+528331 B），
且普通 input-load 增加约 0.137 µs/step；净 walltime 已包含这些代价。
p29 的全程平均 eval 配对增加 2.331%，p12 增加 0.088%，本轮没有用分区
白名单屏蔽退化。p29 在固定采样步中可过滤 head 的初始激活为零，不能把
其时间变化直接归因于过滤了大量计算；尚未对该小幅变化单独归因。

本轮结论是：**按输入实际读取位过滤 head 激活值得保留，收益主要来自
p3/p6 的无效执行减少。** 下一步优先把完整依赖证明和保守回退移入 GrhSIM
emitter，按正式生成流程重新验证等价性与收益；不要把本次源码改写脚本作为
最终按名字匹配的实现。正式化时还需覆盖 input/inout、隐含 memory intent
依赖及可选调度模式，无法证明时保留整输入判定。随后再测新的瓶颈分布；
当前证据不支持继续用同一过滤规则解释或解决 p10/p18 的主要瓶颈工作。

[最终汇总与身份核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/input_bit_demand_20261007/summary.json)、
[8 对普通结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/input_bit_demand_20261007/ordinary_results.json)、
[静态覆盖](../../build/repcut_grhsim_20260925/active_dispatch_20261003/input_bit_demand_20261007/scan.json)、
[激活计数](../../build/repcut_grhsim_20260925/active_dispatch_20261003/input_bit_demand_20261007/activation_results.json)、
[条件 PMU](../../build/repcut_grhsim_20260925/active_dispatch_20261003/input_bit_demand_20261007/pmu_results.json)、
[原型与构建脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/input_bit_demand_20261007.py)、
[语义验证](../../build/repcut_grhsim_20260925/active_dispatch_20261003/input_bit_demand_verify_20261007.py)、
[诊断脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/input_bit_demand_profile_20261007.py)、
[汇总脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/input_bit_demand_summary_20261007.py)。

### 7.70 宽输入按读取位激活移入正式 emitter（2026-10-07）

接续 §7.69，本轮把输入依赖证明移入 `grhsim_cpp.cpp`，直接分析 GRH 的
操作与调度关系，不再扫描或改写生成 C++ 来决定适用对象。新选项
`input_bit_activation` / `WOLVRIX_GRHSIM_INPUT_BIT_ACTIVATION` **默认关闭**，
显式 attribute 优先；本轮探索线对所有分区统一开启，保留 64 B compute
入口对齐，不使用模块、信号、分区或性能白名单。

规则分析同一 compute supernode 内全部操作，包括最终被内联的操作。
对于某个宽输入，只有其全部直接读取都是界内固定单 bit 切片，才收集所读
位的掩码；常量索引的动态切片也能证明。整值/多位读取、未知动态索引、
越界及无法证明的输入依赖继续使用整输入比较；含副作用标记、DPI、system
task、commit、memory/latch 读取或 reg-to-mem intent 的块整体回退。
fullpass 两种可选模式暂时保持原判定。

普通输入与 inout 输入侧使用同一规则。首次 eval、其他输入、状态/事件与
后续固定点传播仍按原逻辑激活，规则只决定当前输入是否额外 OR 入活动位，
绝不清除已有活动位。沿用现有 previous-input 快照及 bitmap/profile 生成
接口，不增加持久状态，也不修改 compute/commit 函数和通信框架。
接口与小例子见 [调度说明](../../wolvrix/docs/emit/grhsim-scheduling.md#实验性宽输入按读取位激活)。

本轮 A 仍为 §7.69 的 `wide_communication_20261007/wide_formal/emu`
（SHA-256 `2ca12a413bdacfb86733f075ae8584b5f94ab445ed1561653f1984a6d65e6ade`）。
为保留当前探索线此前的 compute 优化，B 从完整 IR 重新生成开/关两份
模型，直接编译生成的 eval 源码与头文件，再与 A 的不变 compute 对象链接。
这不是从原始包重新编译全部 compute，也不把历史源码 overlay 当作已经
全部合入默认的实现。关闭选项的源文件、eval 对象的已分配节与 relocation、
其余归档成员和对齐均纳入核验。最终功能与普通性能结果在本节继续追加。

[正式化构建与测试脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_input_bit_activation_20261007.py)、
[生成器与输入身份](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_input_bit_activation_20261007/identity.json)、
[专项测试源码](../../wolvrix/tests/emit/test_emit_grhsim_input_bit_activation.cpp)。

#### 正式覆盖与兼容性核验

开/关两包均从冻结的 `partitioned.json` 完整生成。关闭时 **7482 个模型文件
逐字节一致**；开启后只有 **31 个 eval.cpp** 不同，头文件、状态与 compute
源码保持一致。31 个关闭版 eval 重编译后的已分配节及 relocation 与 A 对应
对象一致；B 只替换这 31 个归档成员，全部 compute 对象不变，**6859 个
compute 入口仍全部 64 B 对齐**。B 的 SHA-256 为
`28920ebdb581cd62643164cd1d4e766a2f65fdc8ff5c2d95e126f47cef4ffe0e`。

正式版覆盖 **31 个分区、3924 个 head、6217 条输入→head 依赖**。
p3/p6 分别为 510/275 个 head、745/437 条依赖。与原型逐项核对：

- 6200 条依赖及其位掩码完全相同，没有共同依赖的掩码变化。
- 新增 17 条：它们所在块使用 `GRHSIM_LIKELY` guard，原型只解析了
  `unlikely` 的代码形态；正式 IR 分析不受该拼写限制。已从实际 compute
  源码独立核对新增依赖的全部取位及掩码。
- 移除 19 条：这些块读取了输入的全部有效位，已按原分区 wrapper 位宽
  逐项核实。原型按 64 位存储字的总容量判断，把末字填充位当成了“未读取
  的部分”；正式版按逻辑位宽判断，不为这种情况增加掩码检查。因此 p28
  没有适用依赖，保持原 eval，而不是按分区名单排除。

新增专项覆盖 11 种模式：未配置、显式关/开、环境开、attribute 覆盖环境、
bitmap 校验、helper 拆分、dispatch guard、perf 计数及两种 fullpass。
其中 8 种各以 Clang23/O0、O3 编译运行，共 **16 个构建，每个校验 32768 次
eval（合计 524288 次）**；开启版 O3 加 ASan/UBSan，日志无 sanitizer 报错。
随机状态序列覆盖多个输入 OR、跨 word 位、inout、末字填充位、首次与重复
eval、重新 init、寄存器更新、DPI 调用次数、整值/动态读取、保守 fanout、
memory intent 和显式副作用标记；全部输出与统一 oracle、最终 checksum
一致。默认关闭与显式关闭、attribute=false 覆盖环境=true 的输出逐字节相同。

带新开关的六项现有 CTest 全部通过：Boolean producer 归约、direct bool
state view、编译器兼容、memory fill，以及 Verilator/GrhSIM 分区包生成。
新增专项已注册 CMake/CTest 目标 `emit-grhsim-cpp-input-bit-activation`；本轮
使用隔离生成库编译并执行同一测试源码，避免覆盖共享构建的库。

[覆盖与原型差异核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_input_bit_activation_20261007/coverage.json)、
[构建与对象核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_input_bit_activation_20261007/build.json)、
[专项结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_input_bit_activation_20261007/tests/results.json)、
[现有回归](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_input_bit_activation_20261007/regression/results.json)。

#### 两窗口普通性能与结论

在 node030 CPU96–127 上，使用 Clang23/O3、N=K=32、all-spin、Host105/lane9、
NUMA1、ASLR 关闭及 CoreMark C100000。两个窗口各 4 对 AB/BA，保留全部
功能通过的普通样本，不增加空闲门槛或剔除离群值。运行时仅开既有 step
计时，没有 PMU、激活诊断或额外 profile。16 次 C100000 均通过 Difftest
和统一终态签名，另 4 次 C100 初始化检查通过；最终 152 个输入身份核验通过。

下表绝对值分别取 8 次运行的中位数；百分比为各对 `(B/A−1)×100%` 的
中位数，不能用两列绝对值直接相除代替。两个窗口 walltime 的配对中位变化
分别为 **−4.499%/−4.069%**；合并 8 对得到 **−4.215%，8/8 更快**。

| 普通指标 | A 中位数 | 正式 IR 版 B 中位数 | 8 对配对变化 |
| --- | ---: | ---: | ---: |
| walltime | 13.410 s | 12.835 s | **−4.215%** |
| Host | 13.3770 s | 12.7965 s | −4.236% |
| 全局 eval | 52.2235 µs/step | 49.5420 µs/step | **−4.932%** |
| p3 全程平均 eval | 45.1340 µs/step | 37.8100 µs/step | **−15.565%** |
| p6 全程平均 eval | 35.8385 µs/step | 32.4875 µs/step | **−9.392%** |
| p10 全程平均 eval | 31.9610 µs/step | 31.5650 µs/step | −1.221% |
| p18 全程平均 eval | 32.5660 µs/step | 31.7230 µs/step | −2.795% |
| 全局 input-load | 2.1340 µs/step | 2.1420 µs/step | +0.648% |
| 全局 update | 10.7820 µs/step | 10.8555 µs/step | −0.201% |

p3/p6 的全程平均 eval 都是 8/8 更快。p10/p18 的小幅时间改善仍不能解释为
同幅度的实际工作量减少；本轮没有重新采集条件 PMU，原型的条件指令证据
仍见 §7.69。input-load 在两窗口的变化方向相反（+6.778%/−4.719%），
不视作稳定的额外收益或损失。全程平均 eval 配对上升的分区为 p9/p11/p15/
p19/p25/p29，分别 +0.129%/+0.311%/+1.137%/+0.469%/+1.272%/+0.780%；
没有据此加入分区白名单。各分区完整数据保留在汇总 JSON。

代价是这 31 个 eval 对象的可执行节从 364164 增至 897339 B，增加
533175 B；普通 walltime 已包含新增比较和代码规模的影响。**正式实现保住
了约 4.2% 的 walltime 收益，值得作为下一轮探索基线保留。** 本节是 B
相对同一冻结 A 的复测；与 §7.69 属于不同测量窗口，未直接测量正式版与
原型之间的性能差异。仓库新增开关仍默认关闭，当前验证线统一在生成阶段
设置 `WOLVRIX_GRHSIM_INPUT_BIT_ACTIVATION=1`。

下一步应在此正式候选上重新采集各分区的瓶颈分布和同一步条件耗时。
p3 的全程平均仍最大，但它下降约 15.6% 而全局 eval 只下降约 4.9%，需要
检查剩余关键步由哪些分区接替；不要直接沿用旧标签推断新候选的瓶颈占比。

[最终汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_input_bit_activation_20261007/summary.json)、
[8 对普通结果及全部分区](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_input_bit_activation_20261007/ordinary_results.json)、
[第一窗口原始运行](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_input_bit_activation_20261007/ordinary/manifest.json)、
[第二窗口原始运行](../../build/repcut_grhsim_20260925/active_dispatch_20261003/emitter_input_bit_activation_20261007/ordinary_verify/manifest.json)。

### 7.71 输入位激活正式版的剩余关键路径（2026-10-07）

接续 §7.70，以正式候选 `emitter_input_bit_activation_20261007/candidate/emu`
为新基线，SHA-256
`28920ebdb581cd62643164cd1d4e766a2f65fdc8ff5c2d95e126f47cef4ffe0e`。
先刷新瓶颈标签，再比较同一步的 Verilator/Clang23/O3，最后由真实剩余热点
选择通用候选。继续 node030 CPU96–127、Host105/lane9、NUMA1、N=K=32、
all-spin、64 B compute 对齐、ASLR 关闭和 C100000；普通样本不设空闲门槛，
不按耗时筛选。不开展编译后反馈或分区/信号白名单优化。

四次独立 GrhSIM 发现运行已通过 Difftest。使用既有相邻两步稀疏时空探针，
每次去掉预先约定的第一个初始化采样对后保留 3148 步；按各分区四次运行的
完成时刻中位数确定最后完成者，再冻结标签供独立对照使用。额外记录第一、
第二完成时刻之间的差值：这里的“第一”是最晚完成者，第二是次晚完成者。
该差值表示其他线程耗时固定时，单独加速该分区可消除的当前尾部；不是
全程可实现的收益，也不能把多个分区的差值直接当成可相加的 walltime 收益。

| 分区 | 最后完成标签数 / 占比 | clock=0 / 1 | 超过次晚者的平均时间 |
| --- | ---: | ---: | ---: |
| p3 | 663 / 21.061% | 293 / 370 | 8.039 µs |
| p18 | 587 / 18.647% | 9 / 578 | 8.132 µs |
| p10 | 510 / 16.201% | 6 / 504 | 7.298 µs |
| p26 | 407 / 12.929% | 407 / 0 | 3.409 µs |
| p6 | 346 / 10.991% | 301 / 45 | 4.300 µs |
| p29 | 258 / 8.196% | 258 / 0 | 5.927 µs |

六者合计 88.02% 的稀疏标签。p3 仍有较多长尾，p10/p18 主要占 clock=1，
p26/p29 全部占 clock=0；后续不能只用全程平均时间决定优先级。按标签占比
选出的这六个分区只用于诊断采样，任何优化仍需按通用 IR/代码模式选择。
独立同一步后端对照、条件 PMU、活跃 batch 和候选验证接续记录在本节。

[实验脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/eval_after_input_bits_20261007.py)、
[新标签及尾部差值](../../build/repcut_grhsim_20260925/active_dispatch_20261003/eval_after_input_bits_20261007/labels.json)、
[发现运行](../../build/repcut_grhsim_20260925/active_dispatch_20261003/eval_after_input_bits_20261007/discovery/manifest.json)、
[时空探针构建核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/eval_after_input_bits_20261007/timing_build.json)。

#### 独立同一步对照与活跃计算归因

冻结上述标签后，另外完成四对 Verilator/GrhSIM 交错时空运行、四对条件
PMU 运行，以及两次 GrhSIM 活跃 batch 运行。以下均为 **GrhSIM 被标记为
瓶颈的同一批步骤**，不是两个后端分别挑自己最慢的步骤。两沿合计则对
这些步骤所属的相邻两步求和。绝对时间为每次运行的条件平均再跨运行平均；
百分比是每对条件平均之比的中位数，不能直接用表内绝对值相除替代。

| 分区 | 同一步 V / G eval | G 相对 V | 相邻两步 V / G eval | G 相对 V |
| --- | ---: | ---: | ---: | ---: |
| p3 | 86.255 / 37.631 µs | −56.31% | 165.211 / 76.600 µs | −53.52% |
| p18 | 51.871 / 51.878 µs | +0.40% | 76.089 / 93.305 µs | **+23.04%** |
| p10 | 59.956 / 49.667 µs | −16.86% | 78.401 / 83.005 µs | +6.33% |
| p26 | 30.271 / 54.417 µs | +79.26% | 90.816 / 71.554 µs | −21.21% |
| p6 | 41.158 / 49.780 µs | +21.49% | 106.676 / 82.703 µs | −22.13% |
| p29 | 33.343 / 49.800 µs | +49.30% | 73.216 / 51.836 µs | −29.20% |

p26/p6/p29 的主要矛盾仍包含半周期间工作集中；p18 是明显的两步总计算
时间劣势，p10 较轻。p3 比 Verilator 快不等于已无需优化：它在 GrhSIM
自己的同步尾部仍占 21.06%，有约 8 µs 的条件平均领先差。

独立 PMU 运行的两步合计变化如下。六个采样线程全部核验
`time_enabled == time_running > 0`；不使用计数器复用推算。PMU 探针自身
也有开销，所以它的时间百分比和前一表不是同一测量，不能混作普通性能。

| 分区 | PMU eval 时间 | 指令数 | 分支数 | 分支预测失败数 | IPC | 有效 GHz |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| p3 | −52.51% | −41.94% | +4.14% | −95.42% | +20.01% | +1.95% |
| p18 | +29.79% | −10.74% | **+113.51%** | **+132.23%** | **−30.86%** | −0.57% |
| p10 | +6.32% | −5.13% | +70.26% | +70.01% | −10.56% | −0.34% |
| p26 | −19.02% | −43.59% | −65.81% | +98.99% | −31.45% | +1.53% |
| p6 | −16.38% | −41.29% | +97.69% | +452.67% | −29.61% | −0.12% |
| p29 | −27.75% | −34.97% | +295.54% | +76.86% | −11.64% | +2.14% |

p18/p10 的证据指向分支与执行效率，而非更多指令或频率下降。计数器仍不能
单独证明每个额外周期都由预测失败造成，后续需结合具体热分支。p26/p6/p29
即使 IPC 较低，两步仍因指令更少而更快，不能只按 IPC 排优化优先级。

活跃 batch 探针只给非空调用计时，空调用仍计数。p6/b184 占其条件活跃时间
16.47%，是集中热点；p10/b15、b17 合计 13.38%；p29/b138、b137、b139
合计 20.40%。p3 最重的 b46 仅占 4.03%，p18 最重的 b18 仅占 2.31%，
p26 最重的 b5 仅占 3.53%，后几者需要覆盖更广的通用规则。探针内时间
不能代替未插桩 walltime。

对实际归档对应的 compute 源码做静态检查：p3/b322、b146，p10/b15、b17、
b53，p26/b5、b0 均有固定多 bit 的外部宽输入切片。当前输入位规则只覆盖
单 bit，剩余范围读取仍可能被无关输入变化触发。由此选择下一候选：在 IR
中把同一 input→supernode 的全部固定读取范围并集转成掩码，仍保留整值读取、
动态未知索引、副作用和隐式状态依赖的回退。该选择不使用上述分区名单；
p18 内部计算热点也不假定能由此解决。收益待普通 AB/BA 决定。

[独立时空对照](../../build/repcut_grhsim_20260925/active_dispatch_20261003/eval_after_input_bits_20261007/timing_results.json)、
[条件 PMU](../../build/repcut_grhsim_20260925/active_dispatch_20261003/eval_after_input_bits_20261007/pmu_core_results.json)、
[活跃 batch](../../build/repcut_grhsim_20260925/active_dispatch_20261003/eval_after_input_bits_20261007/batch_results.json)、
[实际源码热点检查](../../build/repcut_grhsim_20260925/active_dispatch_20261003/input_range_activation_20261007/hotspot_source_survey.json)。

#### 固定多位输入范围的正式候选

直接扩展 `buildInputBitActivationMasks()` 的 IR 分析，不增加源码匹配或
人工选择。沿用 `input_bit_activation` 开关，仍默认关闭；本验证线对所有
分区开启。读取的起始位必须为界内常量，结果位宽必须为正且整个范围不越界。
把 `[start, start + width)` 按 64-bit 字拆分，再合并同一输入、同一 head
的掩码；每次移位都严格小于 64。原先的纯度、hidden intent、完整输入
读取和 fullpass 回退均保留。没有沿纯别名继续推断，也没有改变内部值传播。

新候选 SHA-256：
`bae8032b637b888a7267fa1f097de8c2cc2c0282f8fcdd4c0430c1236e81dbcd`。
重新生成 on/off 包；关闭版 7482 个模型文件与 §7.70 关闭版逐字节一致。
开启版相对 §7.70 正式候选只改变 32 个 `model_eval.cpp`，其他源码和头文件
不变。重新编译旧 eval 并核对可分配节及重定位，再只替换新 eval 对象；
所有 compute 对象保留，6859 个 compute 主入口仍全部 64 B 对齐。
这不是把旧探索线的全部 compute 从当前原始包重新编译，旧覆盖层仍冻结。

覆盖从 3924 个 head、6217 条 input→head 依赖，扩大为 **7943 个 head、
15218 条依赖**，新增 9001 条；原先 6217 条掩码逐项不变。32 个分区均有
自动命中的新增依赖，包括原先没有单 bit 命中的 p28（新增 4 条）。

| 分区 | 可收窄依赖：原单 bit / 固定范围 | 可收窄 head：原单 bit / 固定范围 |
| --- | ---: | ---: |
| p3 | 745 / 1562 | 510 / 875 |
| p6 | 437 / 1043 | 275 / 503 |
| p10 | 51 / 182 | 30 / 98 |
| p18 | 209 / 469 | 147 / 277 |
| p26 | 173 / 698 | 71 / 179 |
| p29 | 27 / 99 | 23 / 68 |

代价是 32 个 eval 对象的可执行节从 900203 B 增至 2227192 B，增加
1326989 B；是否划算必须包含在普通测量内，不能只按覆盖数量判断。

扩展专项覆盖 2/64/65/67/96/512 bit 切片、跨字与整字、重叠范围和单 bit
并集、常量动态切片、inout、完整逻辑位宽、越界回退，以及原有状态/DPI/
intent/位图/fullpass 等场景。11 种生成模式，16 个 O0/O3 运行构建，每个
32768 次 eval，合计 524288 次；输出校验全部通过，其中开启版 O3 使用
ASan/UBSan 并遇错终止。六项现有回归全部通过，包含 Verilator 和 GrhSIM
分区包。接下来在同一基线下完成两窗口普通 AB/BA 和固定标签条件 PMU。

[范围候选脚本](../../build/repcut_grhsim_20260925/active_dispatch_20261003/input_range_activation_20261007.py)、
[覆盖核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/input_range_activation_20261007/coverage.json)、
[对象构建核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/input_range_activation_20261007/build.json)、
[专项验证](../../build/repcut_grhsim_20260925/active_dispatch_20261003/input_range_activation_20261007/tests/results.json)、
[现有回归](../../build/repcut_grhsim_20260925/active_dispatch_20261003/input_range_activation_20261007/regression/results.json)。

#### 两窗口普通 walltime 与同一步 PMU 验证

以 §7.70 正式单 bit 候选为 A，上述固定范围候选为 B。在 node030 CPU96–127
完成两个窗口各 4 对普通 AB/BA，中间穿插独立的四对条件 PMU，三组运行
依次执行。16 次普通 C100000 全部 Difftest/终态签名通过，4 次 C100 通过；
PMU 另有 8 次 C100000 和 2 次 C100 通过。普通运行不含 PMU、时空或 batch
探针。所有功能通过的普通样本均保留，不设置空闲门槛或按时间剔除。

第一/第二窗口 walltime 的配对中位变化分别 **−4.576% / −3.906%**，
合并 8 对为 **−4.176%，8/8 更快**。表中绝对值是各版本 8 次运行的中位数，
百分比是每对 `(B/A−1)×100%` 的中位数；百分比不由两列绝对值相除计算。
分区 eval 是全程每 step 平均，不是只看它成为瓶颈的步骤。

| 普通指标 | A 中位数 | B 中位数 | 配对中位变化 |
| --- | ---: | ---: | ---: |
| walltime | 12.920 s | 12.340 s | **−4.176%** |
| Host | 12.8805 s | 12.3055 s | −4.211% |
| 全局 eval | 50.9405 µs/step | 48.1550 µs/step | **−5.385%** |
| p3 全程平均 eval | 39.3995 µs/step | 20.6490 µs/step | **−47.409%** |
| p6 全程平均 eval | 33.6370 µs/step | 29.0930 µs/step | −13.693% |
| p10 全程平均 eval | 32.6840 µs/step | 32.2325 µs/step | −1.461% |
| p18 全程平均 eval | 32.9300 µs/step | 31.9245 µs/step | −3.082% |
| p26 全程平均 eval | 27.7020 µs/step | 26.3880 µs/step | −4.611% |
| p29 全程平均 eval | 15.0280 µs/step | 14.6310 µs/step | −2.404% |
| 全局 input-load | 2.0265 µs/step | 2.0830 µs/step | +3.348% |
| 全局 update | 9.6930 µs/step | 9.6245 µs/step | −0.110% |

32 个分区的全程 eval 配对中位数均下降；但这不代表每个分区的瓶颈步骤都
少做了相同比例的工作。input-load 两窗口为 −0.181%/+5.765%，update 为
−0.414%/+0.328%，不主张这些小变化是额外收益；它们已包含在最终 walltime。

用候选实施前冻结的 3148 步标签，在四对 PMU 运行中比较同一批关键步骤。
仅复用完全相同的两个 PMU framework 对象，模型对象不另行插桩；计数器
全部满足 `time_enabled == time_running > 0`。下表时间是条件平均再跨
运行平均，变化仍取配对比值中位数，不与前面的普通时间混用。

| 原瓶颈分区 | 条件 eval A / B | eval 变化 | 指令变化 | 分支失败变化 | 有效 GHz 变化 |
| --- | ---: | ---: | ---: | ---: | ---: |
| p3 | 37.721 / 20.294 µs | **−46.279%** | **−51.758%** | −23.583% | −0.342% |
| p6 | 51.306 / 43.337 µs | **−15.862%** | **−20.814%** | +7.726% | +0.075% |
| p10 | 51.167 / 51.238 µs | −0.817% | −0.024% | −1.764% | −0.243% |
| p18 | 52.761 / 53.054 µs | +1.013% | −0.100% | +1.914% | −0.184% |
| p26 | 55.794 / 54.791 µs | −1.841% | −6.123% | +27.948% | +0.048% |
| p29 | 49.518 / 48.524 µs | −2.968% | −0.005% | +8.497% | −0.016% |

因此 p3/p6 的收益有明确的指令数证据，并非靠升频。p26 也减少了实际工作，
但新增分支失败和较低 IPC 抵消部分收益。p10/p18/p29 的原瓶颈步骤指令数
基本未变，不能把其全程平均改善直接解释成关键计算优化。p3 两沿合计
eval/指令还分别减少 46.635%/52.175%，排除了仅把工作移到另一个半周期
的解释。p3 原标签步骤的全局 eval 阶段下降约 23.22%，小于 p3 自身的
46.28%；其他分区接替等待尾部，因此最终 walltime 只下降约 4.18% 并不矛盾。

**保留固定范围扩展作为当前验证线的新候选。** 开关默认状态不变；下一步
需以新瓶颈分布决定 p18/p10 的内部执行优化，而不是继续按旧 p3 标签排序。
这些收益是相对 §7.70 正式候选的本轮实测，不与前轮 4.215% 直接相加。

[8 对普通结果及全部分区](../../build/repcut_grhsim_20260925/active_dispatch_20261003/input_range_activation_20261007/ordinary_results.json)、
[第一窗口](../../build/repcut_grhsim_20260925/active_dispatch_20261003/input_range_activation_20261007/ordinary/manifest.json)、
[第二窗口](../../build/repcut_grhsim_20260925/active_dispatch_20261003/input_range_activation_20261007/ordinary_verify/manifest.json)、
[条件 PMU 结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/input_range_activation_20261007/pmu_results.json)、
[PMU 原始运行](../../build/repcut_grhsim_20260925/active_dispatch_20261003/input_range_activation_20261007/pmu_runs/manifest.json)。

#### 候选实施后的瓶颈重采与后续优先级

普通和 PMU 对照结束后，再对 B 独立运行四次 C100000 时空采样及一次
C100，全部通过 Difftest/签名和输入身份核验。仅复用同一组时空 framework
对象，候选模型对象及 64 B 对齐不变。按与本节开头相同的方法，在 3148 个
固定采样步骤上用四次完成时刻中位数重新选最后完成者。

| 分区 | A 发现占比 | B 新发现占比 | B 超过次晚者的条件平均时间 |
| --- | ---: | ---: | ---: |
| p10 | 16.201% | **20.108%** | 8.312 µs |
| p26 | 12.929% | **20.076%** | 5.316 µs |
| p18 | 18.647% | **19.377%** | 8.666 µs |
| p29 | 8.196% | 8.767% | 8.086 µs |
| p6 | 10.991% | 5.813% | 4.477 µs |
| p24 | 见完整标签 | 5.718% | 10.088 µs |
| p3 | 21.061% | **5.559%** | 3.200 µs |

这是不同发现窗口的描述性分布，不把占比变化当作精确的配对因果估计。
候选实施前后 PMU 的严格同一步对照仍使用旧冻结标签；前面的条件 eval
不能冒充这一批新标签的条件平均。p3 的无效触发明显缓解后，等待尾部由
p10/p18/p26 等接替；不能因为 p3 全程平均接近减半，就期待 walltime 同比
减半。

下一轮优先在这组新标签上定位 **p10/p18 的内部热分支与高频调度判断**。
两者合计约 39.49% 的最后完成标签，超过次晚者的条件平均均约 8–9 µs；
且本轮范围过滤几乎没改变其原关键步骤的指令数。应把同一步的 branch-miss
位置映射回活动标志判断、值变化通知和实际逻辑选择，再与 Verilator 的
对应代码对照，选一个有语义依据的通用模式。p26 则作为下一优先项：其
632 个新标签全部 clock=0，仍需拆清半周期集中计算的来源。p24 也进入
后续诊断名单，但目前没有其新标签上的后端/PMU 对照，不预先归因。

[B 的新瓶颈标签](../../build/repcut_grhsim_20260925/active_dispatch_20261003/input_range_activation_20261007/post_range/labels.json)、
[B 的四次发现运行](../../build/repcut_grhsim_20260925/active_dispatch_20261003/input_range_activation_20261007/post_range/discovery/manifest.json)、
[时空构建身份核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/input_range_activation_20261007/post_range/timing_build.json)、
[候选最终核验汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/input_range_activation_20261007/summary.json)。

### 7.72 固定范围触发之后的 p10/p18 热分支（2026-10-07）

以 §7.71 保留的固定范围候选为基线，SHA-256
`bae8032b637b888a7267fa1f097de8c2cc2c0282f8fcdd4c0430c1236e81dbcd`。
诊断标签冻结为该节末尾四次独立发现运行的结果：p10/p18 分别有 633/610
个最后完成步骤。沿用 node030 CPU96–127、Host105/lane9、NUMA1、N=K=32、
Clang23/O3、all-spin、64 B compute 对齐、ASLR 关闭和 C100000。

本轮先把同一步 G/V 计数器差异及 branch-miss 地址分布更新到这条基线，
再按模式选择通用候选。地址采样覆盖每个标签所属的相邻两步，分析时分别
统计真正的 critical 步骤、配对的其他步骤及两步合计，避免只选中 clock=0
或把工作集中在不同半周期误归因为总工作量。每个分区单独采样，不采其他
线程/进程。PMU 沿用已核验的 wrapper-only 二进制；IP 只替换 common/eval
两个 wrapper，全部模型对象不变，6859 个 compute 主入口仍保持 64 B 对齐。
诊断时间不混入最终普通 walltime。

已有共同使能外提、整组不变跳过、布尔归约等实验见 §7.52–7.59；本轮不把
这些已尝试方案当作新发现，也不依赖 part/信号名单、编译后反馈或地址搜索
选择生产优化。硬件 IP 为非 precise 采样，可能 skid，只作热区域线索，
不把落点指令直接当成产生预测失败的分支。

[本轮驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/range_branch_path_20261007.py)、
[冻结标签](../../build/repcut_grhsim_20260925/active_dispatch_20261003/range_branch_path_20261007/labels.json)、
[构建身份核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/range_branch_path_20261007/build.json)。

#### 同一步的 G/V 差距与代码归因

PMU 四对 AB/BA 完成。下表绝对时间为四次运行条件均值的平均，变化为
`median(100*(G_i/V_i-1))`；两沿取标签所在的去重相邻步对，不能将标签步
直接乘二，也不能把两个分区的条件集合混在一起。

| 分区/集合 | Verilator eval | GrhSIM eval | 配对变化 |
| --- | ---: | ---: | ---: |
| p10，633 个 critical 步 | 59.311 µs | 47.901 µs | −19.125% |
| p10，611 对相邻两步合计 | 79.713 µs | 80.766 µs | +1.705% |
| p18，610 个 critical 步 | 51.111 µs | 52.040 µs | +1.833% |
| p18，591 对相邻两步合计 | 75.752 µs | 92.340 µs | +21.882% |

p18 两沿指令数 **−14.532%**，branches **+114.258%**，branch misses
**+147.008%**，IPC **−29.529%**；有效 GHz 仅 −0.582%。p10 对应为
−9.361%、+67.937%、+66.173%、−10.810%，GHz +0.185%。因此 p18 仍有
实际执行效率差距；p10 的两沿总成本已接近 V，不能因为它频繁成为 G 的最后
完成分区，就称它在同一步或总工作量上一定比 V 慢。上述探针 eval 不替代
普通整机 walltime，也不足以把全部差距归因于预测失败。

进一步按这 591 对的实际 clock 拆开，p18 的差额几乎都在下降沿：

| p18，同一组 591 对 | Verilator eval | GrhSIM eval | 配对变化 |
| --- | ---: | ---: | ---: |
| clock=1，上升沿 | 52.216 µs | 52.251 µs | +0.097% |
| clock=0，下降沿 | 23.537 µs | 40.089 µs | +70.269% |

但 610 个 critical 标签中 **586 个为上升沿、24 个为下降沿**。这不是说
下降沿成本不值得改善，而是本轮 p18 拖住全局阶段的主要情形在上升沿；
只围绕“两沿比 V 慢 21.9%”优化，可能大量减少非关键步骤工作而收不到
相称的 walltime 收益。后续诊断与候选验证应同时报告 critical、分沿和两沿，
保持原标签，避免把三种指标互相替代。

cycles 和 branch-misses 地址采样分别对每个 part 做四对 AB/BA。GrhSIM
critical 周期样本 p10/p18 共 388/403 个，compute 为 321/326，commit 为
48/56；错分支样本共 235/317 个，compute 为 117/191，commit 为 105/114。
换算后，commit 占 critical 周期样本 **12.37%/13.90%**，占错分支样本
**44.68%/35.96%**；两沿周期样本中 commit 仅 **7.62%/7.99%**。提交是
错分支密集区，但不是全部执行时间的主导部分。周期主成本仍是分散的 compute，
不能用错分支占比替代时间占比。

对 27 个 GrhSIM 热函数重编译仅加行号信息，逐一核实所有原 allocated
section 字节及重定位目标/加数不变，再按函数内偏移映射采样地址；调试符号
表索引变化不当作指令变化。使用冻结候选的真实 source overlay，未用 raw
package 覆盖已有优化。p10/b15、b17 的主要周期落点是大状态快照的窄字段
拼接；p18 则分散于状态拼接、布尔生成/变化通知、标量选择与提交比较。
采样存在 skid，映射到一条语句不证明该语句就是前一个错分支的来源。

与当前 V 代码对照，提交成本差异仍有明确的结构来源：例如同一个
`iqWakeUpBundleDelayed_delayed_REG_7_bits_rfWen`，V 的
`part_18/VWolviRepCutUnit_part_18___024root__14.cpp:550` 在相应阶段直接
赋值；G 的冻结 `grhsim_Gpart_18_model_sched_256.cpp:7526` 还需在合法
event/enable 下比较新旧值，并对多个 consumer 活动字通知变化。名字只用于
对应等价 RTL，不用于优化筛选。其激活语义不可删除，已有 same-reader 和
精确 mask 合并也已经在基线中；后续应量化被激活后实际产生多少有效变化，
而不是再次重复已有合并或关闭性能计数器。

本轮选择先验证一项严格受限的选择规则：`cond ? a : b` 的三个参数都已经
是布尔存储读取或已物化布尔临时量时，复用现有 `grhsim_sel_u64` 的
unpredictable 提示。区别于 §7.39 的复杂 eager 扩展，也区别于已有零值/标量
OR 项规则；不扩展到条件或两分支含运算、动态读取、函数调用的情况。全量
扫描 6994 个冻结 sched 源文件，命中 1602 个 compute 文件、43395 个选择项；
p10/p18 为 750/308 个。按类型/存储结构统一筛选，未按 part 或 profile
挑选应用位置。

完成编译后，1602 个命中文件中 **1595 个对象逐字节不变**，只有 7 个对象
发生变化；p18 的 52 个命中文件全部不变，p10 仅 b120 改变，且其静态条件
跳转从 111 增至 112。这项提示扩展不能减少本轮主要热点的机器指令，不能
把源码选择项数量当成尚待优化的分支数量。两窗口八对普通 C100000 的配对
walltime 变化中位数 **−0.283%**，5/8 次更快；窗口分别为 +0.001%/
−0.599%，不足以确认稳定收益，继续采用 §7.71 固定范围版本作为基线。
按用户记录粒度，只保留这一机制结论和验证入口，不逐次展开未采纳候选。

本轮共 16 次普通版、40 次 G/V 诊断正式 C100000，全部通过 Difftest、终态
签名一致；另有 14 次 C100 启动 smoke。最终复核 11 项 ELF/输入/探针身份，
计数器区间无复用，IP 采样无丢失或 throttle。普通版保持 6859 个 compute
入口 64 B 对齐，所有功能成功样本均纳入。本轮未增加主线默认优化。

下一步应以瓶颈上升沿为目标，量化**大状态拼接中实际变化的 word 比例，以及
状态通知唤醒后输出仍不变的比例**。前者可判断按 word 增量更新快照是否值得
设计，后者用于定位可证明的冗余激活；应先取得动态工作量证据，再设计纯
IR/依赖结构规则，不依赖分区名单、编译后反馈或删除 debug/perf 逻辑。

数据与复现：
[同一步 PMU](../../build/repcut_grhsim_20260925/active_dispatch_20261003/range_branch_path_20261007/pmu_core_results.json)、
[周期落点](../../build/repcut_grhsim_20260925/active_dispatch_20261003/range_branch_path_20261007/ip_cycles_results.json)、
[错分支落点](../../build/repcut_grhsim_20260925/active_dispatch_20261003/range_branch_path_20261007/ip_branch-misses_results.json)、
[机器码及源码映射审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/range_branch_path_20261007/code_audit.json)。

[本轮完整核验与结论](../../build/repcut_grhsim_20260925/active_dispatch_20261003/range_branch_path_20261007/summary.json)、
[普通版八对统计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_leaf_select_20261007/ordinary_results.json)。

### 7.73 瓶颈上升沿的有效变化量与快照增量计算（2026-10-07）

沿用 §7.71 的固定范围输入激活基线和 §7.72 的冻结标签，先测量活跃计算的
结果究竟变化多少，再选择通用规则。诊断限定 p10/p18，但优化的结构筛选
遍历全部分区，不使用分区、模块、信号名单或编译后性能反馈。继续使用
node030 CPU96–127、NUMA1、host105/lane9、N=K=32、all-spin、Clang23/O3、
64 B 计算入口对齐、ASLR 关闭；不增加核空闲门槛，不筛掉功能成功样本。

#### 两次独立 C100000 的工作量计数

探针覆盖 p10/p18 的 424 个 compute 文件、3233 个纯计算 supernode 和
31 个直接按 word 拼接的宽结果。纯节点入口/出口比较其引用的全部持久化
value 存储范围；只读范围也包括在内，但不会制造错误的“不变”结果。
DPI、SystemTask、状态写入和无持久化结果的节点不计入。宽拼接则紧贴该次
拼接的首条计算和最后一次存储，逐一比较 64 bit word，避免后续槽复用影响。

两次正式运行的所有计数逐行完全相同，均通过 Difftest、终态签名一致；另有
C100 smoke。424 个原始 compute 对象重编译后，allocated section 和重定位
与冻结基线相同，确认使用了当前保留的源码 overlay，而非原始 package。

| 瓶颈上升沿条件集合 | p10 | p18 |
| --- | ---: | ---: |
| eval 步数 | 606 | 586 |
| 活跃纯节点执行次数 | 298680 | 540283 |
| 执行后持久化结果全不变 | 56.383% | 50.041% |
| 被重新拼接的 word 次数 | 1692735 | 1254827 |
| 最终数值确实变化的 word 比例 | 4.440% | 14.558% |

p10 的两个主要密集拼接为 b15 的 558 word 结果（变化 **1.838%**）和 b17
的 502 word 结果（**1.149%**）；它们分别包含约 5151/4803 个显式标量片段，
另有紧凑 bool 打包。p10/b16 的 1369 word 结果变化 3.763%，p18/b18 的
1902 word 结果变化 13.023%，但这两组主要是整字复制，不能与大量窄字段
移位/掩码/拼接视为相同计算成本。p18 其余几个较大的拼接变化约 7%–26%。

相邻下降沿中，p10 的非 critical 步纯节点结果全不变比例为 71.535%，
p18 为 58.300%；这提供了冗余计算线索，但不能直接推出该比例的 walltime
可被消除。**输出不变不是允许跳过计算的条件**：必须证明所有输入不变，
还要保留槽复用、变化通知、事件和副作用语义。本轮只测覆盖范围内的纯节点
和直接 wordwise concat，既不覆盖所有执行，也不以诊断版时间替代普通版性能。

[计数驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/snapshot_changes_20261007.py)、
[分沿与逐拼接数据](../../build/repcut_grhsim_20260925/active_dispatch_20261003/snapshot_changes_20261007/results.json)、
[源文件/节点覆盖](../../build/repcut_grhsim_20260925/active_dispatch_20261003/snapshot_changes_20261007/prepare.json)、
[构建核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/snapshot_changes_20261007/build.json)、
[运行及输入身份](../../build/repcut_grhsim_20260925/active_dispatch_20261003/snapshot_changes_20261007/runs/manifest.json)。

#### 通用原型的边界

据此验证按 word 的纯状态拼接缓存：证明该 word 只依赖普通标量状态字段，
且至少读取 8 个不同字段时，比较覆盖全部输入字段的字节区间。区间超过
128 B 的情况在编译期回退原计算；简单整字复制也保持原样。这两个结构门槛
在普通性能测试前确定，不按各 part 的表现挑选应用位置。

缓存同时核对**当前目标 word 与上次缓存结果相等**，因此即使临时槽被其他
值复用、模型重新初始化、多个模型交替执行或模型顺序切换线程，也不会仅凭
旧输入副本错误跳过。缓存为函数局部 thread-local，不改变模型 ABI 或活动
标记；跨 word 使用的纯标量临时值保留在 guard 外。无法闭合输入依赖或
无法证明纯度的语句回退。Clang23、GCC 以及 Clang ASan/UBSan 下，独立模型、
重初始化、目标被覆盖、旧线程缓存复用和 128/129 B 边界用例均已通过。
普通 C100000 AB/BA 的结果在本节接续记录。

#### 完成验证：有冗余，但逐 word 比较缓存没有整机收益

全量扫描 6994 个 sched 文件，在全部 32 个分区的 97 个 compute 文件中
找到 6520 个满足依赖/复杂度条件的 word；编译期跨度检查后，实际留下
**2893 个缓存**。p10 为 433 个，p18 仅 4 个；所有被替换源的基线重建均
通过 allocated section 和重定位一致性核验，6859 个计算入口仍 64 B 对齐，
模型 ABI、提交/激活规则及 Verilator 路径不变。

两次独立缓存计数完全相同，且检查次数与此前“逐拼接调用次数 × 该拼接中
实际缓存 word 数”的预测完全一致。瓶颈上升沿的具体覆盖为：

| 指标 | p10 | p18 |
| --- | ---: | ---: |
| 检查次数 | 225239 | 2336 |
| 占全部被重新拼接 word 的比例 | 13.306% | 0.186% |
| 检查命中，跳过拼接 | 218673 | 1065 |
| 缓存命中率 | 97.085% | 45.591% |

所测步骤中没有冷缓存或目标槽失配，未命中均来自输入字节区间变化。p10
的高命中率说明该子集确有可省的重复计算，但只覆盖 b15/558 word 中的
157 个、b17/502 word 中的 93 个；不能把“全部拼接约 95.6% 不变”理解为
这版已经跳过 95.6% 的拼接计算。p18 的主要大结果是便宜的整字复制，剩余
密集拼接的输入分散，当前安全跨度规则覆盖极少。

普通版两窗口共八对 C100000 AB/BA：walltime 的逐对比值变化中位数
**+1.045%**，仅 2/8 对更快；两个窗口分别为 +0.121%/+1.416%。全局 eval
阶段 +0.660%，p10/p18 全程平均 eval 为 +0.837%/+0.923%。这些是逐对
百分比的中位数，不用不同运行集合的绝对时间中位数相除代替。

随后复用冻结基线的同一套 wrapper-only PMU，保持原 critical 标签，做四对
AB/BA，计数区间无复用。下表是固定瓶颈步骤的配对变化，**不是普通 walltime**：

| 指标 | p10 | p18 |
| --- | ---: | ---: |
| eval 时间 | +3.139% | +2.006% |
| cycles | +2.983% | +1.751% |
| instructions | −5.020% | +0.005% |
| branches | +11.558% | +0.112% |
| branch misses | +16.615% | +0.911% |
| IPC | −7.766% | −1.716% |
| 有效 GHz | +0.145% | +0.074% |

p10 两个主要拼接所在对象的代码分别增加约 21.4%/26.7%，p10 所有涉及对象
合计增加 17.93%；全部改写对象合计 3.505→3.929 MB。缓存自身的 TLS
存储为每线程 125552 B，其中 p10 的条目共 16624 B。结合 p10 指令减少、
分支/预测失败增加、频率近似不变而周期上升，可以确认**减少拼接指令并未
提高执行效率**。新增输入/输出比较、缓存访问和分支，以及代码增大，都属于
该方案的成本；当前 PMU 不能将它们与代码位置、缓存层级等影响精确分摊，
不能宣称全部回退都由某一种 miss 造成。p18 几乎没有减少实际工作，也不能
把其时间波动全部归因于四个缓存条目。

结论：保留 §7.71 固定范围基线，**本轮比较缓存不进入默认，也不叠加到后续
验证线**。动态冗余的结论仍成立；失败的是“在消费端重新读取/比较输入来
发现不变”这一具体实现。下一步更值得验证生产端记录变化：复用状态提交时
已有的新旧值比较，根据 IR 依赖给受影响的拼接 word 标记 dirty（需要重算），
消费端遍历真正受影响的 word。设计前要证明跨 word 字段依赖、持久化结果
所有权、初始化全量计算和精确通知；复用槽或未证明的依赖应保守回退。需要
同时计入提交端新增通知成本，不能只测拼接函数，也不能用 part/信号名单。

本轮累计 **28 次正式 C100000、8 次 C100 smoke**，全部 Difftest/终态签名
检查通过，所有功能成功样本纳入；两次有效变化计数和两次缓存计数各自
逐行一致。最终复核 ELF、输入、标签、探针及生成源码身份，保留原基线。
按约定仅保留机制结论和复现入口，不逐次展开未采用原型的测试日志。

[缓存原型驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/state_word_cache_20261007.py)、
[构建及覆盖](../../build/repcut_grhsim_20260925/active_dispatch_20261003/state_word_cache_20261007/build.json)、
[普通版八对汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/state_word_cache_20261007/ordinary_results.json)、
[缓存命中计数](../../build/repcut_grhsim_20260925/active_dispatch_20261003/state_word_cache_20261007/counts_results.json)、
[固定瓶颈步骤 PMU](../../build/repcut_grhsim_20260925/active_dispatch_20261003/state_word_cache_20261007/pmu_results.json)、
[最终核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/state_word_cache_20261007/summary.json)。

### 7.74 在状态写回时记录受影响的拼接 word（2026-10-07）

接续 §7.73 的结论，仍以 §7.71 固定范围候选为基线，不叠加未采用的消费端
比较缓存。本轮改为在状态写回时记录 dirty 位（表示相应 word 需要重算），
计算端通过位图枚举实际需要更新的 word。沿用 node030 CPU96–127、NUMA1、
host105/lane9、N=K=32、all-spin、Clang23/O3、ASLR 关闭、计算入口 64 B 对齐；
普通版 AB/BA 是最终性能判断，诊断版只用于归因。

首先复用上一节在冻结源码上得到的纯状态依赖证明，并增加两项检查：目标
value 存储只有一个 SSA 所有者，且全部输入状态的运行期写入都能识别和
发出通知。扫描完整 6994 个 sched 文件，32 个分区共 5176 个 word 通过；
另有 1344 个因存在尚未覆盖的写入形式而回退。不存在按 part、模块、信号
名称或 profile 选择的应用名单。输入字段没有上一版的 128 B 距离限制。

原型保留现有 enable/event、状态赋值和 reader 激活。在独立写回的已变化
分支内增加 dirty 掩码；同 reader 的成组提交复用现有 `changed_i`，将同一
位图字上的通知合并。消费端每 64 个候选 word 使用一个位图字，取出后清零，
通过最低置位和 switch 枚举需要计算的 word。跨 word 字段连接到所有实际
读取它的目标，初始化标记全 dirty，未被执行的组保留标记。跨 word 共享的
纯标量表达式保持原声明的整数类型后展开，避免窄整数提升改变移位语义。

为先验证执行成本，原型将位图放在按模型实例管理的附属存储中，经线程局部
指针缓存访问；模型 ABI 不变，init 重置，析构释放，顺序切换执行线程仍访问
同一份位图。所有模型遵循原有不并发操作同一实例的生命周期；本实验不使用
模型按值复制或恢复裸内存快照。若后续进入正式 emitter，应将位图作为模型
成员，并在正式存储规划和 IR 写入依赖上表达规则。

候选共 339 个 64 bit dirty 字（2712 B，全部 32 个模型合计），涉及 227 个
compute/commit/生命周期对象。Clang23、GCC、Clang ASan/UBSan 均通过跨
word、写入使能、多次写入、初始化、实例隔离、线程交接和地址复用测试；
另有由真实重写器生成的三种局部/完整改写，以 65536 种 16 bit 输入差分验证
跨 word 临时值、整数提升及未置 dirty 时的持久化结果。后续整机测试会计入
提交端增加的通知、间接分支和可能变化的成组比较优化，不以少算的 word
比例推算 walltime 收益。

[结构与写入覆盖核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/producer_dirty_words_20261007/audit.json)、
[原型驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/producer_dirty_words_20261007.py)、
[依赖与通知映射](../../build/repcut_grhsim_20260925/active_dispatch_20261003/producer_dirty_words_20261007/prepare.json)。

#### 两窗口普通版与固定瓶颈步骤归因

227 个替换对象全部完成基线重建核验，原 allocated section 和重定位一致；
模型头文件与 ABI 未修改，全部 6859 个计算入口仍保持 64 B 对齐。对 305 个
涉及的持久化结果槽再次扫描运行期直接写入，21768 次 word 存储均来自其
唯一拼接生产者；未知写入形式仍保守回退。另构建全分区检查版：每次增量
更新后都执行原始完整拼接，逐 word 对照全部 5176 个候选。C100 和完整
C100000 均通过，未发现 dirty 遗漏。检查版只用于正确性，不用于性能统计。

两个独立窗口各四对普通 C100000 AB/BA，所有成功样本均纳入：

| 普通版指标，逐对变化中位数 | 结果 |
| --- | ---: |
| walltime | **−0.694%，8/8 对更快** |
| 两窗口各自 walltime | −0.691% / −0.694% |
| Host | −0.666% |
| 全局 eval 阶段 | −0.753% |
| p10 全程平均 eval | **−4.110%，8/8 对更快** |
| p18 全程平均 eval | +0.176% |

本轮八次基线 walltime 中位数 11.495 s，候选为 11.445 s；前述 −0.694%
来自 `median(100*(candidate_i/baseline_i-1))`，不等于这两个中位数之比。
不把本轮绝对秒数与上一节不同时间窗口的 12 s 级数据直接相除宣称额外收益。

同一套 wrapper-only PMU、原固定标签、四对 AB/BA 的结果如下。探针只替换
common/eval wrapper，不改变已构建的 compute/commit 对象，计数区间无复用：

| 固定 critical 步指标，逐对变化中位数 | p10 | p18 |
| --- | ---: | ---: |
| eval 时间 | **−3.335%** | +1.428% |
| cycles | −3.442% | +1.240% |
| instructions | **−10.828%** | −0.234% |
| branches | +1.288% | +0.588% |
| branch misses | +4.845% | +3.271% |
| 有效 GHz | −0.159% | −0.136% |

p10 上升沿指令 −11.252%、eval −3.505%；下降沿指令 +0.098%、eval
+1.925%，两沿合计 eval −1.320%。因此收益确实来自上升沿少做拼接，而不是
频率提升；下降沿不执行这些候选拼接，仍有附属状态访问等新增成本。不能
将某一个下降沿时间变化全部归因于某条指令或缓存事件。

再用独立的 batch 计时/word 计数版各跑四次基线和候选，始终保留同一批
critical 标签。每侧四次的调用和执行计数完全一致，结果为：

| 瓶颈上升沿中的候选 word | p10 | p18 |
| --- | ---: | ---: |
| 基线重复计算次数 | 385903 | 20575 |
| 占全部直接拼接 word 次数 | 22.798% | 1.640% |
| 候选实际计算次数 | 9740 | 7336 |
| 候选范围内跳过比例 | **97.476%** | **64.345%** |

p10 所有涉及 compute 批次在 critical 集合上的计时合计变化为 **−37.451%**，
对应 commit 批次为 **+1.305%**；两个主要 compute 批次 b15/b17 分别为
−56.06%/−38.96%。其证据支持“计算端省下的工作超过写回端增加的通知成本”，
但这些批次包括拼接以外的计算，不能把整段时间都叫拼接时间。独立 batch
探针还会改变代码布局与执行成本，不能用其整个 eval 的 −9.795% 替代普通版
或 wrapper-only PMU 的收益，也不能将不同二进制的分项时间直接相减。
p18 的涉及 compute 批次合计基本不变（−0.076%），与其覆盖范围很小一致。

代码成本也更小：p10 涉及的 compute 对象 404271→428151 B（+5.91%），
commit 对象 952026→1023244 B（+7.48%）。提交端并非免费；后续正式实现仍
需要保留 enable/event 与原 reader 激活，并避免为每个 word 引入新的独立
分支或重复比较。当前 PMU 说明 p10 指令节省超过新增执行成本，但仍有 IPC
下降，不能简单按少算比例预期 walltime 收益。

本轮共 **33 次正式 C100000、9 次 C100 smoke**，全部通过 Difftest、终态签名
一致；另有两类语义差分各三种编译配置，及全分区每次拼接的逐 word 校验。
保留该原型作为后续候选，**仓库默认与正式 emitter 尚未修改**。下一步可将
规则移入 IR/存储规划和正式 emitter，使用模型内的 dirty 成员替代临时附属
存储，并验证关闭选项时生成结果不变、开启时与本原型等价，再以普通 AB/BA
确认收益。p18 的覆盖和下降沿开销另行评估，不以热点名单扩大应用范围。

[普通版八对汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/producer_dirty_words_20261007/ordinary_results.json)、
[固定标签 PMU](../../build/repcut_grhsim_20260925/active_dispatch_20261003/producer_dirty_words_20261007/pmu_results.json)、
[批次与 dirty 执行计数](../../build/repcut_grhsim_20260925/active_dispatch_20261003/producer_dirty_words_20261007/profile_results.json)、
[全分区逐 word 校验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/producer_dirty_words_20261007/validation_runs/manifest.json)、
[最终输入/源码身份核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/producer_dirty_words_20261007/summary.json)。

### 7.75 producer dirty-word 正式 emitter 验证（2026-10-08）

增量勘误（2026-10-08）：本节 `off_v2/on_v2` 的生成配置没有继承已保留的
input-range activation，并误开了未保留的 demanded-bit source cache。
本节同配置 off/on 对照仍成立，但不能解释为叠加全部已保留优化后的增量。
配置证据、修复后的 `off_v3/on_v3` 对照和关键路径重采见 §7.76。

接续 §7.74，本轮把原型迁入正式 `grhsim_cpp` emitter。规则保持结构化、
与分区和信号名称无关：结果宽度至少 96 bit、至少四个操作数；逐个目标
64-bit word 检查其完整依赖树，只有依赖至少八个不同的标量 register/latch
状态字段和常量、且目标持久化槽由该 SSA value 独占时才启用。输入、event、
memory、宽状态、带副作用、reg-to-mem intent、物化中间快照和无法证明为
状态根的依赖回到普通路径；同一 concat 中符合条件的 word 可以单独启用。
这个八字段门槛沿用 §7.74 原型，用于让通知和位图遍历成本有足够摊销。

正式实现将位图作为模型实例成员，初始化时全置脏；所有普通寄存器/锁存器
写回、成组标量提交和同 reader 提交均复用已有变化判断发出通知，并合并同一
位图字的 mask。consumer 取出对应 bank 后清零，用 `countr_zero` 和 `switch`
遍历置位 word，未置位的 word 不再重建。关闭选项时不生成模型成员，关闭版
7,519 个模型源码文件与重新生成的 off 源逐字节一致；Verilator 路径不受影响。
选项 `producer_dirty_words` / `WOLVRIX_GRHSIM_PRODUCER_DIRTY_WORDS` 默认关闭，
正式生成或脚本流程可显式开启。

正式生成的 32 个分区共覆盖 6,623 个 word、453 个 64-bit bank（3,624 B 位图），
其中原型的 5,176 个 word 全部保留，正式 IR 规则另外识别 1,447 个 word；246
个调度源文件包含 dirty consumer。off/on 两侧各完整编译 7,454 个对象，
6,859 个 compute 入口保持 64 B 对齐。C=100000 的全分区逐 word 重算校验、
小模型跨 word/混合输入/部分写入/latch/多实例测试，以及 Clang、GCC、
ASan/UBSan 配置均通过；检查版 Difftest 和终态签名一致。
正式 emitter 回归中的 `emit-grhsim-cpp`、`emit-grhsim-cpp-wordwise-concat` 和
`emit-grhsim-cpp-commit-same-readers` 三组测试也全部通过（3/3）。

严格同源的两个独立窗口、共 8 对普通 AB/BA 均通过 Difftest。变化定义为
逐对 `100*(on_i/off_i-1)` 的中位数：

| 指标 | off 中位数 | on 中位数 | 变化 |
| --- | ---: | ---: | ---: |
| Host | 12.7495 s | 12.4765 s | **−2.216%** |
| walltime | 12.785 s | 12.510 s | **−2.229%（8/8 更快）** |
| 全局 eval | 50.678 µs | 49.3825 µs | **−2.544%（8/8 更快）** |
| 最大分区 eval | 42.8195 µs | 41.5185 µs | **−3.026%（8/8 更快）** |
| update push 总和 | 90.419 µs | 90.4695 µs | +0.051% |

p10 的分区 eval 平均下降 5.754%，p18 下降 3.815%；update 总量基本不变，
说明收益来自消费端少重建，而不是减少通信或改变调度。模型 on 二进制约
101.4 MB，off 约 100.2 MB；新增成员会改变 C++ 对象布局，因此开启版必须
完整重编译，不能复用关闭版对象。该结果支持将选项作为正式可选机制保留，
但默认关闭状态不变，后续若要默认开启仍需在更多 workload/仿真器上复测。

[正式生成器与 AB/BA 驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/producer_dirty_formal_20261008.py)、
[生成及编译产物](../../build/repcut_grhsim_20260925/active_dispatch_20261003/producer_dirty_words_20261007/formal/)、
[结构覆盖核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/producer_dirty_words_20261007/formal/audit_v2.json)、
[全分区逐词校验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/producer_dirty_words_20261007/formal/check_v2/build.json)、
[严格窗口汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/producer_dirty_words_20261007/formal/strict_v2_results.json)、
[第一窗口原始结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/producer_dirty_words_20261007/formal/strict_v2_a/summary.json)、
[第二窗口原始结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/producer_dirty_words_20261007/formal/strict_v2_b/summary.json)。

#### 增量：bank 动态密度与继续优化的范围（2026-10-08）

在上述正式 `on_v2` 上增加逐分区、逐 bank 计数，沿用 node030 CPU96–127、
Clang 23/O3、N=K=32、all-spin、C100000。两次完整候选运行均通过 Difftest，
每个 bank 的调用、非空、候选 word 和实际执行 word 计数逐项一致。计数版只
用于解释行为，其 Host/eval 不作为普通版性能结果。

下面的分母是“对应拼接被调度时，候选 word 若走完整重算所需的执行次数”，
分子是实际 dirty word 执行次数；统计覆盖完整运行，不是固定瓶颈步骤集合，
也不是全部分区计算的跳过比例。

| 分区 | 静态候选 word | bank 数 | 候选 word 实际重算比例 | 候选范围内跳过比例 |
| --- | ---: | ---: | ---: | ---: |
| p3 | 190 | 12 | 3.332% | 96.668% |
| p10 | 923 | 24 | 3.013% | 96.987% |
| p18 | 68 | 13 | 39.351% | 60.649% |
| p24 | 91 | 12 | 13.731% | 86.269% |
| p29 | 14 | 3 | 0.179% | 99.821% |

bank 是一组候选目标 word 对应的 64-bit 脏位图，并不要求使用满 64 bit。
同样很小的 bank 也有完全不同的活动特征：p24 的 bank 0 仅四个候选 word，
两次运行共 1,381,008 次全量重算机会中只执行了八次；bank 1 只有两个 word，
399,996 次机会却全部执行。因此，单凭 bank 中 word 的个数，无法判断保留
dirty 路径是否划算。生成源码里的 OR/拼接片段数量也不等于机器执行成本，
例如一个 bool-pack 调用可能承载多个字段的读取和拼位。

本轮还完成了按 bank 大小/表达式片段筛选，以及小 bank 直接位判断的验证；
没有获得足以替换现有路径的稳定 walltime 收益，不纳入正式实现。按当前记录
约定，不展开未采纳候选的逐轮数据。正式 emitter 已恢复为上述通过验证的
无 bank 数量门槛版本，并与 `generator_v2/grhsim_cpp.cpp` 快照逐字节核对一致；
`producer_dirty_words` 默认仍关闭，验证线的 `on_v2` 保持原实现。

这些计数支持保留 producer 通知、consumer 仅处理 dirty word 的方向，但不能
据此把 eval 收益推算成 97%。下一步应优先对正式版本的固定瓶颈步骤拆分
状态提交通知成本与残余 compute 成本，尤其是 p18；p3/p10 已覆盖拼接范围内
的冗余重算大多被去除，继续只调整 bank 遍历形态的空间暂未得到证实。后续
规则仍从 IR/依赖结构推导，运行时 profile 仅作归因和验证，不用热点名单或
编译后反馈选择分区、信号。

[逐 bank 动态计数及汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/producer_dirty_dynamic_profile_20261008_bank2/profile_results.json)、
[完整 Difftest 及两次计数记录](../../build/repcut_grhsim_20260925/active_dispatch_20261003/producer_dirty_dynamic_profile_20261008_bank2/runs/manifest.json)、
[计数工具](../../build/repcut_grhsim_20260925/active_dispatch_20261003/producer_dirty_dynamic_profile_20261008.py)。

#### 增量：p18 的提交通知成本与剩余计算（2026-10-08）

接续上述计划，基线和候选分别为本节冻结的 `formal/off_v2` 与 `on_v2`，
仅对比正式 producer dirty-word 机制的开关；此前已经保留的优化两侧一致。
本轮没有新增正式优化，也没有重新做 Verilator 对照。继续使用 node030
CPU96–127、Host105、NUMA1、N=K=32、all-spin、Clang 23/O3、64 B 计算入口
对齐与原 ASLR 设置，C=100000；不按耗时或核空闲程度筛除样本。

沿用 §7.72 的独立固定瓶颈标签，不根据本轮候选计时重新挑选步骤：p10 为
633 步（606 上升沿、27 下降沿），p18 为 610 步（586 上升沿、24 下降沿）。
PMU 版只替换 wrapper；阶段计时版另外替换 p10/p18 的 eval 调度函数，
仅在 prepare、compute、commit、tail 边界计时。每侧原有 6994 个计算/提交
批次对象保持逐字节一致，6859 个 compute 入口仍对齐；PMU 无事件复用。
另做两次独立 word 计数，计数与计时不混用。

这里的 commit 是 **eval 内部的状态写回、原 reader 激活和新增 dirty 通知**，
不是框架的 update 或分区间通信。compute 包括本阶段的批次调度和实际计算，
不能全部叫做拼接时间。开启版 p18 在固定 critical 集合上的阶段均值如下，
占比使用各次均值的平均值相除：

| 阶段 | 每个 critical eval 的平均时间 | 占 eval |
| --- | ---: | ---: |
| compute：调度与组合计算 | 41.849 µs | 81.278% |
| commit：状态提交及激活/通知 | 7.909 µs | 15.361% |
| prepare：求值前准备 | 0.468 µs | 0.909% |
| tail：刷新/收尾 | 0.967 µs | 1.878% |
| 未归入上述区间的调度与计时开销 | 0.295 µs | 0.574% |
| eval 合计 | 51.488 µs | 100% |

off/on 的平均迭代轮数均为 1.961，逐次、逐集合的轮数完全一致。阶段探针中
off 的 compute/commit 为 41.246/7.437 µs，但 **不能将两侧 commit 差额
0.472 µs 全部归因于 dirty 通知**：off/on 的模型成员和生成代码布局不同。

为隔离这一成本，再构造三个使用相同 `on_v2` 模型数据布局的诊断版本：

| 诊断版本 | p18 消费端 | p18 提交端 |
| --- | --- | --- |
| full_notify | 13 个 bank 的 68 个 word 全量计算 | 保留原 dirty 通知 |
| full_no_notify | 与 full_notify 使用相同计算对象 | 去掉 752 处 dirty 标记语句 |
| normal_on | 正式的 dirty-word 增量计算 | 与 full_notify 保持相同通知 |

`full_notify` 仍清除对应位图；全量计算保证去掉通知不影响语义。这里只在 p18
做消融以隔离因果，并非按分区筛选的生产优化。非目标对象保持不变，但最终
链接地址仍可能变化，不能把不同对照的计时差直接相加。

每项阶段/PMU 对照各做四对 AB/BA，得到以下机制证据：

- **通知成本较小。** full_notify → full_no_notify 的 commit 平均为
  7.928→7.832 µs，约省 0.096 µs；逐对变化中位数 −1.101%，四对都下降。
  PMU 显示每个 critical eval 少约 257 条指令，只占约 26.3 万条总指令的
  0.097%。整个 eval 的时间没有呈现一致的同等收益，不能按提交差额直接
  预测 walltime。
- **p18 消费端省下的净工作也很少。** full_notify → normal_on 保持通知
  不变，每个 critical eval 净少约 388 条指令（−0.147%，已经计入位图遍历
  的新增指令），分支 +1.026%、预测失败 +1.475%。本诊断的 cycles +0.872%、
  eval +0.596%，未显示局部加速。通知和消费端是独立实验，不把两个指令差
  当作严格守恒分解，更不将这些时间差用作普通版收益。

计数进一步解释了 p10/p18 的区别。下表分母仍仅为符合规则的 word 被调度后
所对应的全量重算机会，不是全部计算量；每步均值包含固定集合中的两种沿。
两次完整运行的每个 bank、每类步骤计数完全一致：

| 固定 critical 集合 | p10 | p18 |
| --- | ---: | ---: |
| 全量 word 重算机会合计 | 481359 | 38284 |
| 实际 dirty word 重算合计 | 14832 | 20334 |
| 每步全量重算机会 | 760.441 | 62.761 |
| 每步实际重算 | 23.431 | 33.334 |
| 候选范围内实际重算比例 | **3.081%** | **53.114%** |

p18 在全程的重算比例为 39.351%，到了瓶颈集合却升到 53.114%；p10 则仍仅
约 3%。p18 多个 bank 的重算比例达到 95%–98%，例如 bank 3 的两个 word
来自 121 个分散 bool 状态字段，任一相关字段变化就需要重建整个 word，
其重算比例达到 97.867%。这不是“这些拼接一定便宜”，而是“瓶颈时经常
必须计算，当前整 word 跳过机制省不了多少”。静态片段个数不能替代成本判断。

正式 off/on 的固定步骤 PMU 也符合这一工作量差异：p10 指令 −13.732%、
eval −5.892%，p18 指令仅 −0.043%、eval +3.337%。但本轮确认 **探针会影响
p18 的时间变化，不能将 +3.337% 宣称为普通版的瓶颈步骤退化**：PMU 版连
p18 的全程平均 eval 都变为 +2.410%，阶段计时版为 +0.923%，而下面的普通版
结果为 −4.035%。因此差异不能只用“固定瓶颈步骤与全程平均的口径不同”
解释；探针插入、重新链接和运行状态的影响尚未逐项分离。保持批次对象不变
并不保证计时无扰动，未修改的 p10 在两类消融中也存在约 1%–2% 的时间变化。
阶段占比用于近似定位，重复一致的工作量和 PMU 指令数用于判断机制成本，
最终性能仍以原普通二进制为准。

最后重新使用冻结的原普通二进制做四对 AB/BA，结果如下。百分比仍为逐对
`100*(on_i/off_i-1)` 的中位数，而不是两列中位数之比：

| 普通版指标 | off 中位数 | on 中位数 | 逐对变化中位数 |
| --- | ---: | ---: | ---: |
| walltime | 13.620 s | 13.240 s | **−2.575%（4/4 更快）** |
| Host | 13.5845 s | 13.2030 s | **−2.592%** |
| 全局 eval 阶段 | 53.238 µs | 51.427 µs | −3.276% |
| 最大分区全程平均 eval | 44.9815 µs | 42.7280 µs | −4.218% |
| p10 全程平均 eval | 33.0675 µs | 30.4915 µs | −7.523% |
| p18 全程平均 eval | 32.0225 µs | 30.7715 µs | **−4.035%** |

walltime 四对变化为 −3.448% 至 −1.910%。这是对本节既有优化的复测，不能
与前述 −2.229% 再相加；不同时间窗口的绝对秒数也不能直接比较为新的收益。

本轮共 **58 次完整 C100000、15 次 C100 smoke**，均通过；完整运行 Difftest
与终态签名一致，输入与冻结产物身份检查通过。正式 emitter 与选项默认状态
未改。结论是保留现有 producer dirty-word 验证线，后续优先看 p18 剩余
compute 中经常执行的 bool/拼接生成、变化传播与热分支，并结合 Verilator
代码对照寻找通用 IR 模式；现有证据不支持把下一轮重点继续放在通知 bookkeeping
或 bank 遍历微调上。尚不能从本轮确定某一个剩余计算模式就是主要可消除成本。

[本轮完整汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/producer_dirty_attribution_20261008/summary.json)、
[固定步骤阶段拆分](../../build/repcut_grhsim_20260925/active_dispatch_20261003/producer_dirty_attribution_20261008/phase_a/results.json)、
[固定步骤 word 计数](../../build/repcut_grhsim_20260925/active_dispatch_20261003/producer_dirty_attribution_20261008/words/results.json)、
[同布局通知对照](../../build/repcut_grhsim_20260925/active_dispatch_20261003/producer_dirty_attribution_20261008/notifications/pmu_a/results.json)、
[同布局消费端对照](../../build/repcut_grhsim_20260925/active_dispatch_20261003/producer_dirty_attribution_20261008/compute/pmu_a/results.json)、
[普通版复测](../../build/repcut_grhsim_20260925/active_dispatch_20261003/producer_dirty_words_20261007/formal/attribution_ordinary_a/summary.json)、
[诊断与消融驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/producer_dirty_attribution_20261008.py)、
[独立计数驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/producer_dirty_critical_words_20261008.py)。

#### 增量：当前 p18 与 Verilator 的同一步代码热点对照（2026-10-08）

接续剩余 compute 的分析，对 GrhSIM `formal/on_v2` 和既有 Clang 23/O3
Verilator 版本重新做硬件周期、分支预测失败地址采样。环境仍为 node030
CPU96–127、Host105、NUMA1、N=K=32、all-spin、64 B compute 入口对齐及
原 ASLR 设置，C=100000。每个事件四对交错运行，共 16 次完整 Difftest、
4 次 C100 smoke，全部通过，终态签名一致，运行前后输入身份不变。

本轮固定标签仍来自独立的 post-range 发现运行：610 个 p18 critical eval，
其中 586 个上升沿、24 个下降沿；这些步骤所在的 591 对相邻半周期共有
1182 次 eval。下表“其余半周期”是其中不在 critical 集合的 572 次 eval，
不能直接称为“全部下降沿”。这也不是对 on_v2 当前瓶颈频率的重新统计。
GrhSIM 的 IP 探针仅替换两个 wrapper 对象，原 7452 个其他对象保持一致；
6859 个 compute 入口仍为 64 B 对齐。Verilator 复用相同标签及探针实现。

表中两侧值为四次运行均值的平均，变化为逐对 `100*(GrhSIM/Verilator-1)`
的中位数。周期是硬件计数，不是微秒或整机 walltime；“两沿合计”的单位
是每对两次 eval 的事件数，其余行是每次 eval 的事件数。

| p18 固定集合与指标 | Verilator | GrhSIM on_v2 | 逐对变化中位数 |
| --- | ---: | ---: | ---: |
| critical 周期/eval | 172625 | 173023 | **+0.006%** |
| 其余半周期的周期/eval | 80201 | 138596 | **+73.013%** |
| 两沿合计周期/对 | 255797 | 312725 | **+22.125%** |
| critical 分支预测失败/eval | 642.650 | 1156.597 | +79.790% |
| 其余半周期的分支预测失败/eval | 138.844 | 585.595 | +322.416% |
| 两沿合计分支预测失败/对 | 797.690 | 1760.549 | +120.622% |

这再次确认了 §7.72 的主要区别：固定瓶颈步骤上的周期已接近 Verilator，
两沿总量的差额主要来自相邻半周期。不能把“p18 两沿多约 22% 周期”直接
说成“当前关键步骤可缩短 22%”，也不能把更多分支预测失败简单乘以一个
固定罚时来解释总差额，流水线停顿可能重叠，其他执行成本也不同。

GrhSIM critical 的 420 个周期地址样本中，337 个落在 compute（80.238%），
73 个落在 commit（17.381%），其余为调度或其他位置；330 个预测失败地址
样本中，compute/commit 分别为 195/128 个（59.091%/38.788%）。这里
commit 仍是 eval 内部的状态写回、激活和通知，不是分区间 update。
硬件地址采样有 skid，这些数是**样本位置占比**，不是精确耗时占比或精确
致错分支归属。每个事件的完整计数用于上表，样本个数不能代替完整计数。

剩余 compute 热点分散：最多的 batch_18 只有 10/420 个周期样本（2.381%）；
batch_210、195、101 各 8 个，batch_80 为 7 个。不能根据这么少的样本把
其中某一条 C++ 语句判定为主因。对应生成代码中仍可见以下通用结构：

- 大快照的连续标量状态复制，不能仅因源码长就认定全部属于昂贵拼接。
- 多个 bool 或 bool 与表达式先移位拼接，再只判断拼接结果是否非零；部分
  编译后代码仍保留移位、打包及 SIMD 重排。既有 scalar concat reduction
  对单用户内联值保守跳过，因此这种消费端内联形态仍可能出现。
- 结果逐项计算、与旧值比较、持久化并汇总 reader 激活；计算、变化判断与
  传播的成本混在同一批次，不能把整个批次时间都算给某个表达式。

针对 12 个 GrhSIM 函数增加行号信息后，已核对原有可分配 section 和重定位
与被测对象一致，再将热点映射回源码；另外对 9 个 Verilator 函数反汇编。
此轮确认的是上述生成模式仍存在，尚未建立每段 GrhSIM 与 Verilator 代码的
严格一一对应，也未证明某个模式主导了剩余差距。函数/分区编号仅用于诊断，
不用于生产规则筛选。

本轮通用表达式候选的普通性能验证未形成可保留收益，正式 emitter、选项默认
及 `on_v2` 验证线保持不变；按用户要求不在本文展开未保留候选的数据记录。
下一步选择优化对象前，应先用 on_v2 重采最后完成者和尾部差值，再把活跃
批次及变化传播成本对应到当前关键步骤；相邻半周期的额外计算是明确线索，
但是否缩短 walltime 仍须普通版交错实测，不能只看局部指令或两沿总量。

[本轮同一步对照汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/residual_compute_20261008/profile_summary.json)、
[周期完整计数与地址分布](../../build/repcut_grhsim_20260925/active_dispatch_20261003/residual_compute_20261008/ip_cycles_results.json)、
[预测失败完整计数与地址分布](../../build/repcut_grhsim_20260925/active_dispatch_20261003/residual_compute_20261008/ip_branch-misses_results.json)、
[源码及机器码核查](../../build/repcut_grhsim_20260925/active_dispatch_20261003/residual_compute_20261008/code_audit.json)、
[复现驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/residual_compute_20261008.py)。

### 7.76 验证线配置勘误、修复与关键路径重采（2026-10-08）

本轮先重采最后完成者，再检查活跃 batch。结果发现此前所谓的“当前累计
验证线”存在配置回退，先修复再选择后续优化，避免继续围绕旧关键路径调优。
仍使用 node030 CPU96–127、NUMA1、Host105、N=K=32、all-spin、Clang23/O3、
compute 入口 64 B 对齐、进程 ASLR 关闭、C100000；不加空闲率门槛，不剔除
慢样本，编译与性能运行串行执行。

#### 配置来源及修复边界

`producer_dirty_formal_20261008.py` 原先取
`probe_demanded_bit_cache_formal_20261006/identity.json` 为生成配置来源，
而不是最后保留的 `input_range_activation_20261007/on.identity.json`。
逐项比较发现只有下面两项偏离，其他已记录配置一致：

| 生成选项 | 原 on_v2 | 应继承的保留值 |
| --- | --- | --- |
| `WOLVRIX_GRHSIM_INPUT_BIT_ACTIVATION` | 未设置，实际关闭 | `1` |
| `WOLVRIX_GRHSIM_DEMANDED_BIT_SOURCE_CACHE` | `1` | `0` |

这不只是 manifest 推断：on_v2 的全部 32 个模型 eval 源文件与 input-range
实验的 **off** 版本逐字节一致。以 p3 为例，旧 eval 中没有
`grhsim_input_delta_`，保留版有 3572 处。Host/worker 框架的并行 input-load、
标量/宽通信过滤、all-spin 和 64 B 对齐仍在，并未一并丢失。

现已修正生成驱动，从最后保留配置继承并检查这两项，再分别设置
`PRODUCER_DIRTY_WORDS=0/1`，以同一冻结 `partitioned.json` fresh 生成
`off_v3/on_v3`。正式 emitter 源码与 `generator_v2/grhsim_cpp.cpp` 快照一致，
本次修复没有改变生成算法及生产默认。

两边均有 33 个生成源文件变化：32 个 eval 恢复输入位/范围激活，另一个
p6 compute 源文件关闭 source cache；其余 7519 个生成文件、全部头文件和
框架源文件保持一致。新的 32 个 eval 又与先前保留的 input-range on 版本
逐字节一致。33 个对象各自重新编译，并先重编旧源码核对可分配 section 和
重定位与原 archive 一致，再替换新对象；全部 6859 个 compute 入口保持
64 B 对齐。这是 fresh 全量生成、经核验的对象增量构建，不是全对象重编译。

全分区 6623 个 dirty word 的强制全量重算校验在新 on_v3 上通过 C100/C100000。
校验复用的 109 个 compute 对象逐个证明源码和当前头文件未变，且与上述
33 个更新对象不重叠；没有跨模型布局复用对象。

#### 普通性能：两种问题分别配对

每种对照两个窗口各 4 对 AB/BA。百分比统一为每对 `(B/A−1)×100%` 的中位数；
时间列是各侧 8 次普通运行中位数，不用两列中位数之比代替配对统计。

| 对照 | A walltime / s | B walltime / s | 配对变化 | B 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| 配置修复：on_v2 → on_v3 | 12.720 | 11.940 | **−6.226%** | **8/8** |
| 修正配置内 dirty 开关：off_v3 → on_v3 | 11.970 | 11.865 | **−1.390%** | **8/8** |

配置修复两个窗口分别 −5.027%/−7.215%；对应全局 eval 49.417→45.684 µs，
配对 −7.443%；p3 全程平均 eval 41.8215→18.047 µs，配对 −56.855%。
这是**恢复已保留配置的收益**，不能称为本轮发明的新优化，也不能把全部收益
单独归给其中一个开关。普通 update 对象未改，其波动不代表通信算法改变。

修正配置内 dirty 开关两个窗口分别 −1.109%/−1.390%；全局 eval 配对
−1.330%，所有分区 eval 总和 −1.675%，p3/p10 分别 −6.749%/−6.252%。
因此 producer dirty-word 在正确累计配置上仍有收益，但应引用本轮约 1.39%
结果，不能直接沿用旧配置的 2.229%，更不能与配置恢复的 6.226% 相加。

#### 独立重采：当前等待的是哪些线程

旧 on_v2、新 on_v3 各做 4 次发现运行；每 127 step 采相邻两步，以四次
完成时刻的中位数选最后完成者，按既定规则不纳入最初 127/128 步，共 3148
个唯一步标签。on_v2 的 p3 最后完成占比为 27.764%，新 on_v3 降为 5.337%。
新标签随后冻结，在另外 4 对 GrhSIM/Verilator 运行中验证，不在验证样本上
重新选择 winner。下表 eval 是该分区在自身固定瓶颈步骤集合中的平均耗时；
Verilator 使用同一集合，单位均为 µs。

| 分区 | 发现占比 | GrhSIM eval | Verilator eval | 配对 eval 差 | 验证仍最后完成 | 正尾差 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| p29 | 21.410% | 54.746 | 29.195 | +87.849% | 95.326% | 8.388 |
| p18 | 20.966% | 47.602 | 47.210 | +1.134% | 97.652% | 8.155 |
| p10 | 13.755% | 41.515 | 54.335 | −23.613% | 94.169% | 6.583 |
| p26 | 9.911% | 50.408 | 27.194 | +85.892% | 88.301% | 3.581 |
| p15 | 7.529% | 40.397 | 59.304 | −31.900% | 96.308% | 6.960 |
| p24 | 6.671% | 24.889 | 20.735 | +20.415% | 93.095% | 9.077 |

“正尾差”是每步 `max(本线程完成时刻−其余线程最晚完成时刻,0)`，再取平均。
它表示该线程在当前调度下单独拖出的尾部，不能把不同集合的均值相加当作
可获得的 walltime 收益。开始 eval 的平均延迟仅约 0.7–1.4 µs，当前多数
尾部有实际计算耗时支撑，不能只归因于 worker 启动延迟。

p29/p26 的相邻两沿总 eval 分别比 Verilator 少约 12.643%/21.012%，却在
自身瓶颈半周期慢约 88%/86%；“总工作量较少”和“单步尾部较长”仍同时存在。
p18 瓶颈半周期已接近 Verilator，相邻两沿仍多约 21.094%；p10/p15 在
上述瓶颈步已快于 Verilator。后续不再笼统地把这些分区都描述成“比 V 慢”。

另 4 对条件 PMU 不复用发现样本选标签，所有硬件计数均验证没有 multiplex。
p29 瓶颈步平均指令为 V 281387、G 450593（+60.13%），分支约 2653→39167，
预测失败约 43→91；两侧有效频率均约 3.59 GHz。大量循环分支本身大多预测
正确，应先看执行/寻址/循环控制成本，而不能只凭分支总量称为预测失败瓶颈。
p18 则指令少 31.48%，周期基本持平、IPC 约 2.245→1.537、预测失败约
586→1161；它更接近执行效率问题，仍需细分分散热点。

两次活跃 batch 计时只对实际执行的 batch 读时钟，compute 对象不变。p29
活跃 batch 合计约 53.967 µs，其中 b137/b138/b139 分别 4.217/3.301/2.482 µs；
p15 的 b130/b129/b131 分别 3.288/2.926/2.180 µs。p18 最大的 b18 只有
1.466 µs，占活跃 batch 合计约 3.20%，依旧分散。batch 探针包含测量开销，
其合计不能从普通 eval 中直接相减得到调度或 commit 时间。

以上配置修复、配对和诊断共 59 次完整 C100000 Difftest、16 次 C100 smoke
通过；其中普通性能为 32 次完整运行，其余用于校验或归因。后续优化以 on_v3
为基线，沿用这批独立标签；不采用按分区/信号手工启用的生产规则。

[配置核查与全部汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_profile_restore_20261008/summary.json)、
[恢复配置及构建驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_profile_restore_20261008.py)、
[修复后的生成驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/producer_dirty_formal_20261008.py)、
[固定标签与尾差](../../build/repcut_grhsim_20260925/active_dispatch_20261003/eval_after_dirty_v3_20261008/validation_tail.json)、
[同一步 G/V timing](../../build/repcut_grhsim_20260925/active_dispatch_20261003/eval_after_dirty_v3_20261008/timing_results.json)、
[活跃 batch](../../build/repcut_grhsim_20260925/active_dispatch_20261003/eval_after_dirty_v3_20261008/batch_results.json)、
[条件 PMU](../../build/repcut_grhsim_20260925/active_dispatch_20261003/eval_after_dirty_v3_20261008/pmu_core_results.json)。

交互展示见 [当前关键路径 HTML](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_profile_restore_20261008/critical_path.html)：
包含两个普通性能对照、全部 32 分区修复前后最后完成占比、六个主要瓶颈的
G/V eval 对照、验证尾差、条件 PMU，并可切换单步/相邻两沿和导出 CSV。
数据全部内嵌，无外部网络依赖；完成脚本语法及交互切换检查，未做浏览器截图
验收。此页只收录配置修复和关键路径重采，不混入下面的循环候选数据。

#### 增量：有序布尔循环四项展开候选

依据新关键路径，对已有 producer/OR 归约 helper 尝试每次顺序处理四项。
通用规则只把 helper 的 Clang 提示从 `unroll(disable)` 改为
`unroll_count(4)`，仍禁止 vectorize/interleave，不加 `restrict`、不改变
输入读取、旧值比较、写回或归约次序。扫描全部生成 compute 源文件后，实际
命中 17 个文件中的 34 个 helper 定义，分布在 p15/p28/p29；这些编号是自动
覆盖结果，不是白名单。头文件、框架及其余对象保持一致，6859 个 compute
入口继续保持 64 B 对齐。17 个对象可执行节合计 351390→356038 B，增加
4648 B，仍保留紧凑循环而没有重新展开成数百项表达式。

普通对照 A=修复配置的 on_v3，B=on_v3 加上述全局 helper 改写。先做两个
窗口，再因第二窗口接近持平追加一个确认窗口，共 12 对，全部纳入：

| 指标 | A 中位数 | B 中位数 | 配对变化中位数 | B 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| walltime / s | 11.730 | 11.700 | **−0.255%** | **10/12** |
| Host / s | 11.6975 | 11.6645 | −0.248% | 10/12 |
| 全局 eval / µs | 45.526 | 45.4175 | −0.241% | 8/12 |
| 所有分区 eval 总和 / µs | 523.406 | 523.024 | −0.035% | 7/12 |

三个窗口的 walltime 配对中位依次为 −0.895%/−0.128%/−0.086%；因此不沿用
首窗口“约 0.9%”作为最终结论。合并均值 11.74417→11.68750 s，相差约
56.7 ms；均值比、两列中位数之比和配对中位是不同统计量。两次回退及首窗口
12.00 s 的慢基线均保留，没有按性能筛除样本。

p29 全程平均 eval 配对 −1.370%，12/12 更快；p15 −0.665%（11/12），
p28 −0.381%（10/12）。未改写的 p26 则 +0.255%（仅 1/12 更快），说明
重链接和并行执行的间接效应不可忽略，不把各分区变化全部归为直接代码收益。

另 4 对固定 on_v3 标签 PMU：p29 瓶颈 eval 54.726→54.158 µs，配对
−1.167%，cycles −0.910%、指令 −3.820%、分支 −16.620%、预测失败
−16.162%，频率基本一致。p15 指令 −4.398%、分支 −17.989%，但瓶颈
eval +0.105%、cycles +0.025%，基本持平。省掉部分控制指令确有机制证据，
但不能据此推算等比例时间收益，也没有解决 p29 计算集中在一个半周期的问题。

结论：保留为小幅收益的原型候选，**尚未迁入正式 emitter、没有改变生产
默认，当前参考基线仍明确标为 on_v3**。窗口后半段收益很小，不再扩大循环
展开参数搜索。后续重点应是 p29 剩余实际计算/间接寻址，以及 p18 分散
compute 中的执行效率，而非继续减少已经预测良好的循环跳转。

候选专项验证使用精确 helper，覆盖 23 种长度（含 0、4 项尾部和 508/513）、
16/32 位索引、前项依赖、原地写回、读取后项旧值、重复目标等 5 类别名形态，
每项 128 组输入、重复 3 次，Clang23/O0/O3 的 ASan/UBSan 比较全部存储和
两个返回标志均通过。候选测量另有 32 次完整 Difftest、8 次 smoke 通过；
与本节此前合计 91 次完整、24 次 smoke，未计作新的 workload 泛化验证。

[候选汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_reduce_unroll4_20261008/summary.json)、
[通用候选与专项检查](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_reduce_unroll_20261008.py)、
[固定标签 PMU](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_reduce_unroll4_20261008/diagnostics/pmu_a/results.json)。

### 7.77 p29 布尔循环归因与静态步长寻址（2026-10-08）

本轮参考线仍为 §7.76 修复后的 **on_v3**，不叠加上一轮四项展开原型。
继续使用 node030 CPU96–127、NUMA1、Host105、N=K=32、all-spin、Clang23/O3、
compute 入口 64 B 对齐、进程 ASLR 关闭、C100000；编译与性能运行串行，
不使用空闲率门槛、不筛除慢样本。先对原始循环采样，再独立统计实际变化量，
最后只用静态地址规律选择候选，不以测试程序中的取值或分区名称筛选生产规则。

#### 原始代码采样与实际变化量

沿用 on_v3 的独立发现标签，冻结 p29 的瓶颈步骤，不按本轮结果重选。
4 对 GrhSIM/Verilator 周期 IP 采样只在 p29 worker 的 eval 内计数，模型
compute 对象保持原样；硬件事件无 multiplex，采样无丢失或 throttle。
GrhSIM critical 共 529 个地址样本，其中 88 个在共享的布尔归约 helper，
占 **16.635%**；其余 compute 428 个、eval dispatch 6 个、commit 2 个、
其他 5 个。这是稀疏周期样本分布，存在采样偏移，不等价于精确耗时占比。
共享 helper 的归属由采样线程确定，不按符号名猜测所属分区。

另一份独立计数版在 p29 的每次真实 helper 调用中记录输入历史，保留原有
按序读取、旧值比较、写回及两个返回标志；只用固定步骤标签划分统计集合。
两次 C100000 的逐组计数完全一致：

| 集合 | helper 调用 | 处理项数 | 相对上次调用输入变化项 | 输出变化项 |
| --- | ---: | ---: | ---: | ---: |
| 固定 p29 瓶颈步 | 11574 | 5885971 | **0** | **0** |
| 配对的相邻另一沿 | 0 | 0 | 0 | 0 |
| 其余步骤 | 889844 | 452582364 | 37980 | 0 |

其余步骤含首次初始化的 18990 项，输入变化的可比较分母为 452563374。
瓶颈步所有已观察项的左输入为真、右输入为假；全程右输入均为假。
这说明本 workload 中有大量重复计算，却**不能据此把输入当作编译期常量**，
也不能只凭本次输出没变就在下一次跳过。安全跳过需要证明所有相关输入
自上次计算后未变，并处理首次执行、输入/输出重叠及顺序依赖。本轮不实施
动态缓存或跳过，计数版的运行耗时不纳入普通性能结果。

#### 通用候选：从索引表改为可证明的地址递推

原 helper 对每一项先读取左右两个索引，再按索引读两个 bool，执行 AND、
比较目标旧值、写回，并累计 OR 结果和 changed 标志。静态扫描发现多数
索引序列具有重复步长：例如一组每 3 项重复，左右基址每组各增加 222，
组内偏移分别为左侧 `0/37/111`、右侧 `0/1/112`。
因此可直接生成 `base + block*222 + lane_offset`，不再逐项查索引表。

规则只接受周期 1–8、两列均为非负恒定步长、至少 32 个完整条目的连续区域；
对区域内**每个原索引**验证等式。按原次序串联区域，不规则前缀/尾部仍走旧
helper。每个周期最多展开 8 项，外层保持循环；不加 restrict，不改计算或
写回次数，不做跨项重排。有限周期展开也减少循环控制，因此本轮收益不能
完全归因于索引读取这一种指令。

| 自动覆盖分区 | 组数 | 原连续目标条目 | 直接寻址条目 |
| --- | ---: | ---: | ---: |
| p15 | 27 | 13853 | 13608 |
| p28 | 32 | 16315 | 16252 |
| p29 | 37 | 18990 | 17982 |
| 合计 | **96** | **49158** | **47842（97.323%）** |

扫描全部生成 compute 文件后实际改写 17 个文件；上述分区是自动命中结果，
不是白名单。原有非连续目标项保持原状。新旧头文件、框架及其他模型对象
一致；先重编旧源码验证可分配 section 和重定位与冻结 archive 相同，再
替换候选对象，全部 6859 个 compute 入口继续 64 B 对齐。
17 个对象可执行节合计 351390→369884 B，增加 18494 B。

汇编核查确认原 16 位 helper 每项有两条索引 `movzwl`，随后才读取输入；
候选周期 helper 改用固定偏移，循环末尾递增地址。例如上述 3 项模式使用
`add $222` 推进输入、`add $3` 推进目标，原先的每项两次索引表读取消失。
最终 ELF 保留 2 个旧 helper 供不规则区域调用，新增 39 个步长模板实例。
专项语义验证覆盖 42 类模式：周期 1–8、独立输入、前项依赖、原地更新、
读取后项旧值、常量地址，以及不规则前后缀和多区域；各 128 组输入、重复
3 次，在 Clang23/O0/O3 的 ASan/UBSan 下比较全部存储及两个标志，均通过。

#### 两窗口普通性能与固定瓶颈步 PMU

A=on_v3，B=on_v3 加上述通用静态步长规则。两个窗口各 4 对 AB/BA，
全部 8 对纳入；时间列为各侧运行中位数，百分比为每对 `(B/A−1)×100%`
的中位数，不用两列中位数之比替代配对结果。

| 指标 | A | B | 配对变化 | B 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| walltime / s | 11.935 | 11.690 | **−2.410%** | **8/8** |
| Host / s | 11.8975 | 11.6525 | −2.409% | 8/8 |
| 全局 eval / µs | 45.9695 | 45.1005 | −2.082% | 8/8 |
| p29 全程平均 eval / µs | 16.8755 | 16.1495 | **−4.898%** | **8/8** |
| p28 全程平均 eval / µs | 14.3140 | 13.3855 | −6.643% | 8/8 |
| p15 全程平均 eval / µs | 15.7260 | 15.3975 | −2.044% | 8/8 |

两个窗口 walltime 配对中位分别 −2.167%/−2.931%；合并算术均值
11.96375→11.69875 s，差 265 ms。普通 update 配对 −2.330%，但两个窗口
分别 +1.044%/−3.926%，且 update 对象未改，不能宣称通信规则获得新收益。
未改写的 p18 全程平均 eval 配对 −0.749%，说明并行执行和重链接的间接
效应仍存在，不把全部分区变化算作直接代码收益。

另外 4 对固定标签 PMU 使用独立诊断 binary；下表时间与计数列为各轮样本
均值的平均，变化列仍为配对中位，不能与上一轮不同运行的绝对时间拼接。

| p29 固定瓶颈步指标 | A | B | 配对变化 |
| --- | ---: | ---: | ---: |
| eval / µs | 53.535 | 51.405 | **−4.005%** |
| CPU cycles | 191816 | 184333 | −3.817% |
| instructions | 450593 | 429260 | −4.734% |
| branches | 39167 | 33709 | −13.936% |
| branch misses | 99.16 | 81.78 | −17.411% |
| 有效频率 / GHz | 3.5830 | 3.5859 | −0.008% |

p15 固定瓶颈步 eval 40.649→39.716 µs，配对 −2.137%，指令 −3.069%。
p18 没有改写，固定瓶颈步 eval 47.563→48.889 µs，配对 +2.315%，指令
和分支基本不变；与其全程平均略改善并不矛盾，采样集合和测量 binary 不同。
当前 PMU 结果支持 p29/p15 的局部执行成本下降，但不证明 p18 获益，也没有
解决 p29 工作集中在单个半周期的现象。

本轮共 **34 次完整 C100000 Difftest、9 次 C100 smoke** 通过：原代码
IP/变化计数 10/3 次，普通对照 16/4 次，条件 PMU 8/2 次；同长度功能签名
一致，输入文件身份不变。普通 walltime 不混入任何诊断运行。

结论：保留静态步长寻址原型，收益比上一轮单纯四项展开更明确；两者没有
叠加测量，不能相加百分比。**尚未迁入正式 emitter、尚未修改生产默认**。
后续迁入应在 IR/生成阶段识别索引模式、fresh 生成验证等价，保持上述通用
条件；另一条剩余线索是证明输入未变化后再减少重复执行，不能用本次动态
全零观察替代静态或运行时依赖证明。

[归因驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/p29_loop_attribution_20261008.py)、
[原代码周期 IP](../../build/repcut_grhsim_20260925/active_dispatch_20261003/p29_loop_attribution_20261008/ip_cycles_results.json)、
[逐组变化计数](../../build/repcut_grhsim_20260925/active_dispatch_20261003/p29_loop_attribution_20261008/density_results.json)、
[静态模式覆盖](../../build/repcut_grhsim_20260925/active_dispatch_20261003/p29_loop_attribution_20261008/access_patterns.json)、
[通用原型与语义检查](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_loop_strided_20261008.py)、
[普通性能及 PMU 汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_loop_strided_20261008/summary.json)、
[汇编核查](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_loop_strided_20261008/static.json)。

### 7.78 布尔归约的分组失效与无分支缓存跳过（2026-10-08）

本轮只记录最终保留原型。**A 为 §7.77 的 on_v3 加静态步长寻址，B 在 A 上
增加下述运行时缓存**，不是直接与未加步长的 on_v3 比较。继续使用 node030
CPU96–127、NUMA1、Host105、N=K=32、all-spin、Clang23/O3、64 B compute
入口对齐、ASLR 关闭、C100000；编译和性能测量串行，不设空闲率门槛，不筛样本。
普通性能、逐次语义校验、固定标签 PMU 使用各自独立二进制。

#### 安全条件与最终实现

对全图扫描自动命中的 96 组连续目标归约，补查其所属模型的 **475 个 C++
源文件**，包括 eval、compute、commit、state 和 init；分区号不参与资格筛选。
98316 条组内输入引用对应 **98259 个不同输入槽**，每个输入槽都有唯一的本地
普通写入点。49158 个 helper 目标槽互不重叠，不是任何 helper 的输入，也没有
额外的普通写入点。三个 init 中的整数组清零单独处理，必须同时令所有缓存失效。

每组设置一个 dirty 位，含义是“自上次归约以来，至少一个相关输入可能变化”。
首次计算或重新 init 后全置 dirty；dirty 时照原顺序读输入、比较旧目标、写回，
保存 reduced 位后清 dirty。非 dirty 时复用 reduced，changed 返回 false。
因此缓存既不假定输入为零，也不只依赖“上次输出没变”；其依据是完整的输入
失效传播，以及目标槽只由这一组归约写入。

失效传播复用现有 supernode 中的 `grhsim_any_changed` 汇总。supernode 是
一起调度执行的一组逻辑操作；汇总标志已经记录其中若干输出是否变化。
89621 个输入写入可复用现有汇总，8638 个补充到局部 OR 标志，最终在 **1912
个 supernode 边界**汇总通知。覆盖条件允许多包含无关变化，最多导致多算一次；
不得漏掉任何相关输入。若生产者与消费 helper 在同一 supernode，生成器保留
立即通知，避免通知晚于使用；本 workload 没有命中这一回退，但专项测试覆盖它。

最终通知使用无分支位掩码，典型形式为：

```cpp
const uint64_t changed_mask = uint64_t{0} - uint64_t(any_changed);
helper_dirty[word] |= changed_mask & dependent_helpers_mask;
```

当 any_changed 为 false/true，changed_mask 分别为全零/全一；这一写法避免
为每个通知增加条件跳转。消费端仍保留每组的 dirty 判断。已有的静态步长
helper 作为需要重算时的计算路径，原有通知和输出顺序保持不变。

由于模型增加成员，三个模型及包装层 **478 个编译单元全部重编**，包括构造、
分配、初始化和销毁，避免混用类布局。另将相同 478 个原源码重编后，与冻结
archive 的全部可分配节及重定位节逐字节/对齐核对一致；其余 6976 个 archive
成员保持原样。所有 6859 个 compute 入口仍为 64 B 对齐。对应对象可执行节
相对 A 为 6875243→7117877 B，增加 242634 B（约 3.53%），这也是缓存的成本。

#### 语义检查与实际跳过量

专项直接测试真实源代码改写器，包含 dirty 位跨 64 位边界、共享输入、同
supernode 立即失效、跨 supernode 延迟消费、保守额外依赖、重新 init、全真/
全假/随机输入及不变写入。在 Clang23/O0/O3 的 ASan/UBSan 下各执行 12000
步，逐槽比对全部结果和 reduced/changed 两个标志，通过。

另用独立检查版在**每一次实际跳过时完整重算**，核验所有目标均无需变化，且
reduced 与缓存相等；C100000 Difftest 通过，无缓存误判。以下为该运行的
实际次数；检查版开销不纳入普通性能。

| 自动覆盖分区 | helper 调用 | 跳过调用 | 跳过比例 | 跳过的条目计算 |
| --- | ---: | ---: | ---: | ---: |
| p15 | 794046 | 712268 | 89.701% | 362115527 |
| p28 | 1764201 | 455740 | 25.833% | 232308245 |
| p29 | 901418 | 892750 | 99.038% | 453970282 |

91/96 组出现实际跳过；其余五组仅有少量调用，没有虚报覆盖。p29 跳过率高，
只说明本次输入历史适合缓存；不将这一动态现象用于编译期常量折叠。

#### 两窗口普通性能与固定瓶颈步

两个窗口各 4 对 AB/BA，共 8 对全部纳入。时间列是各侧运行中位数，配对变化
是每对 `(B/A−1)×100%` 的中位数；不以时间列中位数之比替代。

| 指标 | A：静态步长 | B：增加无分支缓存 | 配对变化 | B 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| walltime / s | 12.035 | 11.970 | **−0.582%** | **6/8，另 1 对持平** |
| Host / s | 11.9960 | 11.9335 | −0.584% | 7/8 |
| 全局 eval / µs | 45.6065 | 45.0240 | **−1.152%** | 8/8 |
| p29 全程平均 eval / µs | 16.4645 | 14.8750 | **−9.947%** | 8/8 |
| p15 全程平均 eval / µs | 15.7395 | 14.5355 | −7.771% | 8/8 |
| p28 全程平均 eval / µs | 13.6520 | 13.0110 | −4.753% | 8/8 |

两窗口 walltime 配对中位分别 −0.656%/−0.582%；合并算术均值
12.0675→11.9825 s，差 85 ms。walltime 最小/最大配对变化为
−2.385%/+0.251%。全局 update 配对 +0.231%，只有 4/8 更快；本轮没有
通信规则收益。未改写的 p3/p24 全程 eval 分别 +3.137%/+3.708%，p18
−0.461%；不能把重链接、内存布局和并行执行的间接变化都归因于归约本身。

另 4 对 PMU 沿用 on_v3 独立发现的固定步骤标签，不因候选结果改变采样集合。
只改框架探针对象，模型 compute/commit 对象保持各自普通版本原样；事件无
multiplex。下表为 p29 固定瓶颈步，各侧列为四轮样本均值的平均，变化仍为
逐对变化中位数，因此不与普通运行的绝对时间混用。

| p29 固定瓶颈步 | A | B | 配对变化 |
| --- | ---: | ---: | ---: |
| eval / µs | 54.696 | 48.699 | **−10.464%** |
| CPU cycles | 187354 | 167195 | −10.690% |
| instructions | 429260 | 350783 | −18.282% |
| branches | 33709 | 30458 | −9.644% |
| branch misses | 81.15 | 78.07 | −3.421% |
| 有效频率 / GHz | 3.4263 | 3.4350 | −0.033% |

p15 固定瓶颈步 eval 40.162→35.846 µs，配对 −10.820%；指令 −21.666%。
p18/p10 的固定瓶颈步 eval 配对 +0.419%/−0.868%，指令数不变。以上支持
p29/p15 的局部计算收益，频率不是 p29 改善的主要来源。但这些是不同固定
步骤集合，不能把 48.699 和 p18 的 49.797 µs 直接当作同一步的快慢排名，
也不能据此宣布新的瓶颈分布。

最终候选共 **26 次完整 C100000 Difftest、8 次 C100 smoke** 通过：普通
16/4 次、逐次校验 2/2 次、条件 PMU 8/2 次；同长度功能签名一致，运行前后
输入身份不变。原型有局部明确收益，最终 walltime 的增益仍小；**保留实验
原型，未迁入正式 emitter、未改生产默认**。本轮增量百分比不能与 §7.77
的独立窗口结果相加。下一步应对这一累计版本重新采样最后完成线程及关键
步骤，判断 p29 缩短后还有哪些分区在限制全局时间，再选择通用生成规则。

[全源依赖审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_loop_dependency_20261008.py)、
[最终原型](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_loop_dirty_branchless_20261008.py)、
[分组通知规则](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_loop_dirty_grouped_20261008.py)、
[构建与依赖核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_loop_dirty_branchless_20261008/audit.json)、
[专项语义检查](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_loop_dirty_branchless_20261008/semantics/summary.json)、
[逐次重算与跳过统计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_loop_dirty_branchless_20261008/validate/summary.json)、
[普通性能与固定标签 PMU 汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_loop_dirty_branchless_20261008/summary.json)。

### 7.79 静态步长与归约缓存后的瓶颈重采（2026-10-08）

本轮累计版本是 **on_v3 + §7.77 静态步长 + §7.78 无分支布尔归约缓存**，
没有叠加未保留的四项展开或其他候选。普通 ELF SHA-256 为
`67073e05bc4700642284995c0e151e0f70bb95b2e32ffb1958dda0706b58b7f7`。
本轮只完成重采与归因，未新增生产优化、未修改正式 emitter/默认选项。
继续 node030 CPU96–127、NUMA1、Host105、N=K=32、all-spin、Clang23/O3、
compute 64 B 对齐、ASLR 关闭、C100000；编译与测量串行，不设空闲率门槛，
不按速度筛除样本。

#### 重新发现与独立验证

先做四次当前 GrhSIM 发现运行，每 127 step 取相邻两步，按既定规则排除
127/128 两个探针预热步，共 3148 个唯一步。每步按四轮完成时刻中位数选择
最后完成分区，再冻结标签；另做四对 G/V AB/BA 验证。下表耗时是各侧四轮
条件均值的平均，差值为逐对 `(G/V−1)` 中位数。不同分区对应不同固定步骤
集合，不能用这些条件均值对全程线程工作量直接排名。

| 分区 | 最后完成标签数/占比 | G eval / µs | V eval / µs | 配对差 | 验证仍最后完成 | 正尾差 / µs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| p18 | 675 / 21.442% | 50.975 | 51.050 | −0.472% | 98.000% | 9.367 |
| p26 | 590 / 18.742% | 56.841 | 33.348 | +70.438% | 92.415% | 4.868 |
| p10 | 504 / 16.010% | 44.233 | 57.359 | −23.043% | 89.683% | 6.530 |
| p29 | 379 / 12.039% | 51.138 | 36.066 | +41.109% | 94.129% | 7.238 |
| p24 | 252 / 8.005% | 25.628 | 31.631 | −18.940% | 90.675% | 9.092 |
| p6 | 135 / 4.288% | 40.517 | 49.162 | −17.325% | 88.519% | 4.565 |

正尾差仍为 `max(本分区完成时刻−其余分区最晚完成时刻,0)`，先逐步算再求均值。
六者占发现标签的 80.527%；独立验证全部步骤的实际 winner 占比中，p18/p26
为 21.641%/17.972%，支持它们是当前主要瓶颈。六者平均开始延迟约
0.741–1.477 µs，不能把这些尾部笼统归因于线程启动。

历史 on_v3 的 p29/p15 标签占比为 21.410%/7.529%，本轮为
12.039%/3.653%；p26 从历史 9.911% 变成 18.742%。这只是不同窗口的描述性
分布变化，不能把它当作配对收益或纯因果估计。尤其 p24 本轮在自身标签上
比 V 快，和历史标签上较慢不矛盾；采样集合已变，不能拼接两次条件均值。

p26/p29 的标签全部 clock=0；对应相邻两沿合计，G/V 分别为
72.771/96.101 µs（配对 −24.291%）、53.186/78.264 µs（−32.261%）。
这两个分区仍是**单个半周期集中计算**，并非两沿总工作量都比 V 更多。
p18 的 675 个标签中 658 个 clock=1，两沿合计为 G 90.562、V 75.671 µs
（+19.545%）；其瓶颈沿已接近 V，总量差额主要在另一沿。后续仍需同时报告
瓶颈沿与两沿，不能只减少非关键步骤后期待 walltime 等比例下降。

#### 硬件计数与实际代码位置

另四对固定标签 PMU，只重编 common/eval 两个框架对象，全部模型对象不变，
事件无 multiplex。下表为瓶颈步骤，数值列为四轮均值，IPC 为 instructions/
cycles。计数探针与上述 timing 探针独立，不混用绝对耗时。

| 分区 | V/G 指令数 | 指令配对差 | V/G IPC | V/G branch misses | cycles 配对差 |
| --- | ---: | ---: | ---: | ---: | ---: |
| p18 | 382543 / 260301 | −31.955% | 2.249 / 1.528 | 584 / 1155 | +0.231% |
| p26 | 268992 / 339454 | +26.195% | 2.692 / 1.860 | 23 / 458 | +82.747% |
| p29 | 281392 / 349697 | +24.274% | 2.547 / 2.123 | 42 / 79 | +48.965% |

p18 是指令较少而执行效率较低；p26 同时包含更多指令与较低 IPC。p26 两侧
有效 GHz 为 V 3.164、G 3.356，G 反而较高，因此其更长 eval 不能解释为
GrhSIM 频率较低。分支失败较多是线索，不据此把全部时间差归因于预测失败。

两次活跃 batch 计时中，p18 的最大 b18 为 1.395 µs，仅占活跃 batch 合计
2.994%；p26 最大 b5 为 2.080 µs，占 4.039%；p29 最大 b137 为 2.249 µs，
占 4.861%。compute 已较分散，继续只盯单个最大函数的空间有限。batch 计时
包含探针影响，不能用它从普通 eval 中相减推导调度成本。

p18/p26 各四对周期 IP 采样，事件仅在指定 worker 的冻结步对内启用；没有
丢失、throttle 或 multiplex。critical 样本分布如下，样本比例不是精确时间
比例；硬件 IP 可发生 skid。

| 分区 | 总样本 | compute | commit | eval 准备/调度 | 其他 |
| --- | ---: | ---: | ---: | ---: | ---: |
| p18 | 467 | 374（80.086%） | 71（15.203%） | 6（1.285%） | 16 |
| p26 | 435 | 364（83.678%） | 0 | 55（12.644%） | 16 |

对 16 个热模型函数重编译仅加行号，逐个证明全部 allocated section 字节及
解析后的原有重定位一致，再按函数内偏移映射原测量地址。p18 仍分散在状态
拼接、标量选择、值变化通知与提交比较；p26 的 b5 在构建 512 项 packed-array
lane 表，其他热函数包含布尔更新/活动位传播、65–71 bit 的选择与加法。
这些是通用结构线索，名称仅用于对应源代码，不能成为生产筛选条件。

新的明确线索在 p26 eval：55 个样本中 32 个映射到输入 delta 的掩码范围
判断，19 个无可用源码行，其余 4 个分散在输入比较、快照、batch 调用等。
与 V 对照，p26 此沿的样本主要在 `ico_sequent` 输入组合处理及宽字插入，
没有 GrhSIM 这种逐 consumer 掩码判断结构。仍不能以落点断言精确开销，
因此追加独立阶段探针核实。

#### p26 输入准备的成本已得到独立计时支持

阶段探针对 p18/p26 仅重编 eval 和两个框架对象，全部 compute/commit 对象
保持原样。两次完整运行对固定标签分别累计 prepare、compute、commit、tail，
下表为每个瓶颈 eval 的平均 µs。prepare 包括输入变化检查及激活准备；compute
包括空 batch 调用；tail 包括末尾快照。各列来自同一探针，不与前面的 timing
或 batch 绝对数值混用。

| 分区 | prepare | compute | commit | tail | 其余 | eval 合计 | 固定点轮数 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| p18 | 0.575 | 40.385 | 7.443 | 0.903 | 0.334 | 49.640 | 1.975 |
| p26 | **7.976** | 44.040 | 0.034 | 1.170 | 0.219 | 53.439 | 1.000 |

p26 的 prepare 约占 14.925%，两轮分别 7.933/8.018 µs；此沿没有第二轮
固定点重算，commit 也极小。故 p26 此处不能套用 p18 的提交/重激活解释。
全源静态核对进一步显示：

| eval 输入激活结构 | p18 | p26 |
| --- | ---: | ---: |
| delta 定义数 | 429 | 2903 |
| 含 delta 的范围判断 | 469 | 511 |
| 判断内掩码项出现次数 | 1447 | **9644** |
| 最长一条判断的项数 | 46 | **510** |
| 至少 64 项的判断数 | 0 | **17** |

这些是 C++ 静态出现次数，不是动态执行次数。当前精确输入范围规则有效地
避免了无关 compute，但对一条宽输入，只要某处变化，就可能生成/检查大量
delta 和 consumer 范围。下一项通用候选应优先研究**输入激活检查的共享与
分组**：复用 word delta，在静态覆盖关系允许时共享范围归约，或按变化 word
枚举精确受影响 consumer，保留首次 eval 和原有激活语义。先记录关键步的
实际变化 word 密度，决定是否适合稀疏遍历；不能预设稀疏，也不按 p26 名称
启用规则。p18 则继续作为分散 compute/提交效率的后续方向。

#### walltime 与剩余空间

普通程序另做四对 AB/BA，所有样本纳入：V/G walltime 中位数
**21.865/11.845 s**，配对 −45.827%，G 四对全快；Host 为
21.8165/11.8095 s，全局 eval 为 77.8815/44.7805 µs。这个对照是当前累计
GrhSIM 与 Verilator O3 的后端比较，**不是本轮新增优化收益**，也不和
§7.77/§7.78 的不同窗口增量相加。

为解释局部收益为何不等比例转成 walltime，另基于验证的全部采样步骤计算
“其余线程时刻不变，只缩短一个分区”的情景。p18 eval 减少 20% 时，全局
eval 平均仅减少约 1.680 µs；p26 对应约 0.910 µs。即使完全移除 p26 的
eval，固定其他线程时的上界也只有约 0.919 µs/step，因为次晚线程会接替。
这不是实测预测，也不能把各分区上界相加；它说明新规则应尽量覆盖多个
实际瓶颈，且最终仍以普通 walltime 验证收益。

本轮共 **48 次完整 C100000 Difftest、13 次 C100 smoke** 通过，包括
发现 4/1、独立 timing 8/2、PMU 8/2、活跃 batch 2/1、普通性能 8/2、
IP 16/4、阶段 2/1。所有运行输入身份不变；模型 compute 仍全部 64 B 对齐。
这不是第二个 workload 的泛化验证。已生成继承原主题的交互 HTML，包含
32 分区分布、同一步/两沿 G/V 对照、尾差、PMU、活跃 batch、阶段拆解与
固定其余线程的情景表，可切换和导出 CSV。Chromium 已验证全部排序、
历史系列开关、单步/两沿、PMU/batch 分区切换及表格有限数值，并完成截图检查。

[交互 HTML](../../build/repcut_grhsim_20260925/active_dispatch_20261003/eval_after_bool_cache_20261008/critical_path.html)、
[完整汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/eval_after_bool_cache_20261008/summary.json)、
[发现/对照驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/eval_after_bool_cache_20261008.py)、
[源码与机器码审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/eval_after_bool_cache_20261008/code_audit.json)、
[阶段计时](../../build/repcut_grhsim_20260925/active_dispatch_20261003/eval_after_bool_cache_20261008/phase_results.json)。

### 7.80 宽输入激活的分块稀疏检查（2026-10-08）

本轮沿 §7.79 的输入准备热点继续实现并验证，保留一个**按静态结构选择的
8 字分块原型**。基线仍为 on_v3 + 静态步长 + 无分支布尔归约缓存，普通
ELF SHA-256 为 `67073e05bc4700642284995c0e151e0f70bb95b2e32ffb1958dda0706b58b7f7`；
候选为 `d4b513b629f3459c4ad869317ff69d83fe4f94ac5f99fb0615ff21caaf62600a`。
这次 A/B 两侧都是 GrhSIM，只差输入激活检查规则，不是和历史 Verilator
数据相减。保持 node030 CPU96–127、NUMA1、Host105、N=K=32、all-spin、
Clang23/O3、compute 64 B 对齐、ASLR 关闭、C100000；编译与性能测量串行，
不设空闲率门槛，不剔除功能正确的慢样本。

#### 先测稀疏度，再选择实现

复用 §7.79 独立发现后冻结的步骤标签，加探针统计已进入外层输入变化判断的
各组。在 p26 的 590 个固定瓶颈步骤中，累计检查 1,449,841 个 64 位差分字，
其中 66,593 个非零，占 **4.593%**。非零字关联的掩码项出现次数，占原本
这些输入组全部掩码项的 **5.321%**。最终规则命中的 p26 两个输入组更稀疏：
非零字占 **2.475%**，关联掩码项占 **2.662%**。p18 对应的全组非零字占
17.558%，且其瓶颈主要在另一时钟沿，不能预期它有相同收益。

这里统计的是字及其静态消费者关系；“关联掩码项”不意味着对应 mask 一定
命中，也不是编译后指令数。最终按 8 字一块跳过，块内只要一字变化仍需检查
其他相关掩码，因此不能把 95% 的零字直接解释为 95% 的准备时间可消除。

旧代码按消费者分别归约大量 `(delta & mask)`。新代码把一组输入差分划为
每块最多 8 个字，先做一次共享的“本块是否全零”判断；全零就跳过整个块，
否则仅检查消费者在这一块上的掩码，并 OR 对应激活位。目标位置和掩码仍是
编译期常量，不需要运行时查找消费者表。不同块对同一激活位重复 OR 是幂等的；
所有块合并后与原来的长归约完全等价。

规则扫描全部 32 个分区，对满足下列条件的输入组统一启用：

- 至少 32 个差分字，掩码项总数至少是差分字数的两倍；
- 至少三条消费者判断，且至少一条包含 64 个掩码项；
- 消费者判断具有可精确分解的输入位掩码，不混合整端口 fallback 条件。

这些都是生成结构条件，没有模块、变量或分区白名单，也不使用编译后反馈。
首次 eval、外层输入变化判断、原有粗粒度激活及 `pending_eval_round` 保持原样。
共命中 **9 个分区、16 个输入组**（分布为 p0/p3/p6/p7/p8/p9/p11/p13/p26），
覆盖 5,886 个差分字、33,061 个掩码项，生成 743 个块。分区编号仅用于报告
匹配结果。原型入口为 `input_activation_share_20261008.py`，保留配置是
`--scheme blocks --long-only`；当前仍未迁入正式 emitter 或更改仓库默认选项。

#### 等价性和构建检查

对最终 16 组穷举 **376,704 个输入位**的单位置变，检查每个输入位会 OR 到
哪些输出激活位。旧、新表达式都对输入位集合满足 OR 分配律，因此单位置变
映射相同也覆盖任意多位同时变化。另构建运行时对照程序：每次命中输入组时，
分别从同一份初始激活状态执行旧、新代码，逐字比较所有激活位及 pending 状态；
完整 C100000 Difftest 通过。

普通候选只替换 **9 个 model_eval 对象**，其余 **7,445 个 archive 成员**
字节不变；全部 6,859 个 compute 入口仍为 64 B 对齐。九个变更对象的可执行
代码合计从 1,255,841 B 降至 1,141,373 B；这是可执行 section 总量，不是 SV
大小或整个 ELF 大小。p18 的模型对象未改，Verilator 路径未改。

#### 普通 walltime：八对 AB/BA

分两个窗口各做四对，第二窗口位于独立诊断之后。两窗口配对 walltime 中位
变化分别为 −1.007% / −0.336%，全部八对合并如下。前两列是各侧运行中位数；
最后一列先逐对计算 `100 × (candidate / baseline − 1)` 再取中位数，
不是两侧中位数直接相除。

| 指标 | 基线 | 候选 | 配对变化中位数 |
| --- | ---: | ---: | ---: |
| walltime / s | 11.950 | **11.855** | **−0.879%** |
| Host / s | 11.917 | **11.819** | **−0.898%** |
| 全局 eval / µs | 45.101 | **44.702** | **−0.875%** |
| 全局 update / µs | 10.6735 | 10.6995 | −0.029% |

walltime **7/8 对更快**，配对范围 −1.664% 至 +0.167%；两侧平均值为
11.96125 / 11.86625 s，平均节省约 95 ms。全程各分区 eval 的配对变化为
p26 −4.483%、p6 −1.830%、p18 +0.953%、p29 +0.335%。保留真实的整体收益和
局部波动，不将输入准备的百分比当成整个仿真的百分比，也不与此前优化增量相加。

#### 固定瓶颈步骤归因

阶段计时另做四对，继续使用冻结的旧版本瓶颈步骤，避免重新挑样。下表的
耗时列是四轮条件均值的平均；配对列仍采用逐对变化中位数。它们来自带探针
程序，不与普通程序的绝对耗时拼接。

| p26 固定瓶颈步 / µs | 基线 | 候选 | 配对变化 |
| --- | ---: | ---: | ---: |
| 输入检查和激活准备 | **8.145** | **6.075** | **−25.294%** |
| compute | 44.226 | 44.564 | +0.616% |
| commit | 0.0335 | 0.0358 | +5.329% |
| tail（含输入快照） | 1.143 | 1.326 | +18.979% |
| eval 合计 | **53.763** | **52.237** | **−2.976%** |

准备阶段平均节省约 2.071 µs；compute/tail 等有反向变化，所以整个 eval
平均仅减少 1.526 µs。固定点轮数两侧都为 1；相邻两沿合计为 70.039 /
68.505 µs，配对 −2.247%，没有把工作简单挪到另一沿。阶段探针两侧 p18、
compute/commit 对象相同；wrapper 可执行代码和重定位相同，额外字符串差异
只有 assert 的源码路径及依赖该字符串位置的局部符号偏移。

再做四对固定标签 PMU，所有事件均无 multiplex：

| p26 固定瓶颈步 PMU | 基线均值 | 候选均值 | 配对变化 |
| --- | ---: | ---: | ---: |
| 指令数 | 339,454 | 323,225 | **−4.781%** |
| 周期数 | 185,674 | 177,623 | **−4.344%** |
| 分支数 | 5,792.7 | 6,017.1 | +3.874% |
| 分支误预测 | 464.9 | 583.7 | +25.685% |
| 有效频率 / GHz | 3.4635 | 3.4479 | −0.281% |

同一 PMU 探针内 p26 eval 配对 −4.130%；收益伴随指令/周期减少，不能解释
成频率上升。分块也确实增加了分支和误预测，说明新检查并非没有代价。
p6 瓶颈步指令减少 1.365%、周期减少 1.624%，也命中通用收益；p18 的指令及
分支数不变，eval +0.990%、周期 +0.427%、频率 −0.829%。这些变化已计入普通
walltime，不能因为对象未改就剔除，也不把全部波动都归因于频率。

最终保留线相关验证合计 **34 次完整 C100000 Difftest、10 次 C100 smoke**：
普通性能 16/4、阶段 8/2、PMU 8/2、逐次掩码对照 1/1、前置稀疏度探针 1/1。
全部 44 次 runtime 配置相同，ELF/image/NEMU 等运行输入身份保持不变。
本轮未验证第二个 workload，结构阈值也不能称为普适最优。结论是保留该通用
原型，整体收益约 0.9%，尚未解决 p26 的主要 compute 成本；后续应进一步
检查宽拼接后只读取少量元素的通用模式，并继续观察 p18 的计算/提交成本。

[完整汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/input_activation_blocks8_long_20261008/summary.json)、
[通用变换与等价校验驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/input_activation_share_20261008.py)、
[诊断与汇总驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/input_activation_diagnostics_20261008.py)、
[匹配结构与构建清单](../../build/repcut_grhsim_20260925/active_dispatch_20261003/input_activation_blocks8_long_20261008/candidate/prepare.json)、
[逐次掩码对照](../../build/repcut_grhsim_20260925/active_dispatch_20261003/input_activation_blocks8_long_20261008/validate/runs/manifest.json)。

### 7.81 稀疏读取的 packed-array 按需取值（2026-10-08）

沿 §7.80 提出的宽拼接热点，完成并保留一个**带静态成本门槛的按需取值原型**。
基线是上一节已经保留的累计 GrhSIM 版本，包含输入激活分块优化，普通 ELF
SHA-256 为 `d4b513b629f3459c4ad869317ff69d83fe4f94ac5f99fb0615ff21caaf62600a`；
本轮候选为 `590a948a4cc4d9d53f50c93f49430a96bed4ca9781dcde81bc64133dbcb9cc15`。
两侧只差本节规则，均为 GrhSIM。配置继续使用 node030 CPU96–127、NUMA1、
Host105、N=K=32、all-spin、Clang23/O3、compute 64 B 对齐、ASLR 关闭、C100000。
编译与性能测量串行，不设空闲率门槛，不剔除功能正确的慢样本。

#### 从完整填表改为直接读取所需位置

p26/b5 会构造六张各 512 项的 64 位表，内容来自输入切片和寄存器状态。
其中五张表在 b22 各读取 8 个索引，另一张在 b37 读取 8 个索引。原代码
每次先填好整表，之后消费者再读元素；新代码通过编译期只读的“索引→源位置”
表，直接从对应输入或状态中取得所需值。索引边界检查、位宽截断与越界返回零
保持原语义。没有新增每个模型实例的指针表或运行时缓存。

规则统一扫描全部 32 个分区，接受的结构必须同时满足：

- 成员数组至少 64 项，只有一个完整构造点；其余使用全部是可识别的索引读取
  或初始化，读取在生产者之后，静态读取点数不超过项数的 1/8。
- 构造表达式能够追溯到当前 compute 扫描期间稳定的输入、标量寄存器状态或
  常量；检查 compute 无相关写入/未知可变地址使用，且 compute 在 commit 前。
- `数组项数 × sizeof(存储类型) / 静态读取点数 >= 64 B`。
  这是生成结构上的成本启发式，不是实际通信量、内存流量或编译后反馈。

最后一个条件同时考虑“表有多大”和“读多少次”。窄表可能很便宜，且表内容
未变化时消费者仍可能因索引变化而多次读取，直接取值会反复支付动态寻址成本。
因此仅判断数组项数或读取比例不足以判断收益。此门槛不是普适最优参数。
分区、RTL 模块和信号名称不参与选择；以下编号只是扫描得到的匹配结果。

| 分区 | 表数 | 合计元素数 | 原表存储字节 | 静态读取点 |
| --- | ---: | ---: | ---: | ---: |
| p6 | 2 | 576 | 4,608 | 10 |
| p13 | 1 | 256 | 256 | 2 |
| p20 | 1 | 512 | 512 | 8 |
| p26 | 6 | 3,072 | 24,576 | 48 |
| 合计 | **10** | **4,416** | **29,952** | **68** |

原有激活通知和调度关系保持不变，避免删除填表时漏掉下游激活。成员数组字段
和初始化仍保留，模型布局没有变化。普通候选只替换 **13 个 compute 对象**，
其余 **7,441 个 archive 成员**字节相同；全部 **6,859 个 compute 入口**仍
为 64 B 对齐。变更对象的可执行 section 合计 258,642→191,256 B（−26.054%），
仅作为代码规模信息；性能结论来自实际仿真。p18 模型对象未修改。

#### 等价性验证

独立构造带填充字节的状态结构，使用原始 C++ 右值及其别名展开作为参考，
不从新位置表反推期望值。覆盖全零、全一、交替位、64 种单位置位及 64 轮
固定种子随机输入，逐一比较所有元素，并检查 N、N+1、SIZE_MAX 三种越界索引。
**586,872 次比较**在 Clang23/O3、AddressSanitizer/UndefinedBehaviorSanitizer
下通过。

另构建真实模型校验版：保留旧的完整填表，在构造后比较全部元素，并在消费者
真正读取时再次比较旧表与新取值器，检查延后读取的时序等价性。C100 smoke
及完整 C100000 Difftest 均通过。正常性能程序不包含这些对照检查。

#### 普通性能：两个窗口、八对 AB/BA

两个窗口各四对，第二窗口放在独立 PMU/batch 诊断之后。两窗口的配对 walltime
变化中位数分别为 **−0.655% / −0.812%**。下表前两列为八次运行的**平均值**；
最后一列先逐对计算 `100 × (candidate / baseline − 1)` 再取中位数，
不能用前两列相除得到该列。

| 指标 | 基线均值 | 候选均值 | 配对变化中位数 |
| --- | ---: | ---: | ---: |
| walltime / s | 12.21375 | **12.14875** | **−0.783%** |
| Host / s | 12.17625 | **12.113125** | **−0.778%** |
| 全局 eval / µs | 46.1565 | **45.876125** | **−0.775%** |
| 全局 update / µs | 10.831625 | 10.835875 | +0.136% |

walltime **7/8 对更快**，配对范围 −1.399% 至 +1.480%，慢的一对完整保留。
按均值计算，节省 **65 ms，即 0.532%**；按逐对变化中位数统计则是 0.783%，
两者统计方法不同。各侧 walltime 中位数另为 12.175/12.130 s，也不用于计算
上述配对百分比。全程 p26 eval 均值为 24.936/24.18225 µs，配对 −3.088%，
八对全部下降；p6/p13/p20 分别为 −0.409%/−0.976%/−0.354%。未改动的 p18
也有 −0.585% 的时间变化，因此不能把所有分区的时间变化都归为直接代码收益。

#### 固定瓶颈步：生产者与消费者合并计算

继续使用 §7.79 独立发现后冻结的标签，避免按本轮结果重新挑选有利步骤。
batch 探针另做四对，直接调用各侧普通程序的原 compute 对象；探针只改 wrapper
和 dispatcher，双方探针机器码/重定位一致。所有所测 batch 的调用次数、
活跃次数、all-on 次数及激活位数均一致。p26 的 590 个固定步骤中，下面三批
均每步活跃一次。表内为四轮条件均值的平均，包含 batch 计时探针开销。

| p26 活跃 batch / µs | 基线 | 候选 | 均值差 |
| --- | ---: | ---: | ---: |
| b5：生产者 | 2.16072 | **0.06418** | −2.09654 |
| b22：五张表的消费者 | 0.57106 | 0.78694 | +0.21588 |
| b37：另一张表的消费者 | 0.36493 | 0.44065 | +0.07572 |
| 三批合计 | **3.09672** | **1.29178** | **−1.80494** |

消费者确实增加了约 0.292 µs，但生产者减少约 2.097 µs，合计净省约
**1.805 µs/固定瓶颈步**，合计配对变化中位数 −58.028%。p6 对应的五个变更
batch 合计为 1.09309/0.97204 µs，配对 −11.255%。这些数字用于拆解局部机制，
不能把 batch 探针的绝对时间与普通 walltime 或其他探针直接拼接。

四对固定标签 PMU 也全部通过，事件无 multiplex：

| p26 固定瓶颈步 PMU | 基线均值 | 候选均值 | 配对变化 |
| --- | ---: | ---: | ---: |
| eval / µs | 52.584 | **50.376** | **−3.985%** |
| 指令数 | 323,225 | **316,128** | **−2.196%** |
| CPU 周期数 | 177,187 | **170,899** | **−3.518%** |
| 分支数 | 6,017.1 | 6,214.9 | +3.287% |
| 分支误预测 | 583.73 | 592.16 | +1.566% |
| 有效频率 / GHz | 3.3698 | 3.3928 | +0.560% |

p26 相邻两沿合计为 68.328/65.619 µs，配对 −3.867%，指令 −2.380%，周期
−3.355%；没有通过单纯挪到另一沿获得当前步收益。频率略有上升，但同时存在
明确的指令和周期减少。p18 的指令/分支基本不变，而 eval 配对 −1.351%、
周期 −0.825%、频率 +0.403%，说明本轮也有频率和执行波动，不能把时间降幅
全部算作静态工作减少。

最终候选相关验证共 **33 次完整 C100000 Difftest、9 次 C100 smoke**：
普通性能 16/4、PMU 8/2、batch 8/2、逐次新旧值对照 1/1；全部 42 次运行
配置相同，输入身份保持不变。保留该通用生成代码原型，入口为
`packed_lane_demand_20261008.py --min-bytes-per-read 64`，尚未迁入正式 emitter
或改变默认选项，Verilator 路径未改。这仍是同一个 workload 的验证。

本轮解决了 p26 一处具体的重复工作，全局收益约为配对 walltime 的 0.78%；
每步仍由最晚线程决定，局部 1.8 µs 不会全部转化成 Host 时间。后续应优先
继续检查 p18/p10 的剩余计算与提交热点。累计收益需单独重新对照，不能把
本节百分比与前几轮百分比直接相加。

[完整汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/packed_lane_demand_bytes64_20261008/summary.json)、
[通用扫描与变换](../../build/repcut_grhsim_20260925/active_dispatch_20261003/packed_lane_demand_20261008.py)、
[匹配结构与稳定性审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/packed_lane_demand_bytes64_20261008/scan.json)、
[语义校验驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/packed_lane_semantics_20261008.py)、
[诊断与汇总驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/packed_lane_diagnostics_20261008.py)、
[真实模型逐次对照](../../build/repcut_grhsim_20260925/active_dispatch_20261003/packed_lane_demand_bytes64_20261008/validate/runs/manifest.json)。

### 7.82 Commit 激活字节的局部累加：先修正基线来源，再完成 C100000 验证（2026-10-09）

沿 §7.81 的 p18/p10 残余热点，尝试了一个通用的 generated-commit lowering：在
同一个 commit supernode 函数中，对满足结构条件的 `supernode_active_curr_[word] |=
UINT8_C(mask)` 先累加到局部 `uint8_t`，在该 supernode 退出前统一写回。规则只看
生成代码结构，不使用 part、信号或 workload 名称：函数内所有该 active byte 的直接
访问必须是常量掩码 OR，函数至少有 4,000 个 active-byte 写入，且被选 byte 至少
重复 128 次。直接读、非常量写和未识别 wide helper 的对象不进入自动选择。扫描共
选择 36 个对象、156,376 个直接写、267 个局部 pending byte，涉及 24 个分区；编译
只替换这 36 个 archive member，其余 7,418 个 member 保持字节不变。

#### 基线来源勘误

首次二分使用了较早的 packed-lane archive，却用当前 `on_v3` 的源文件和头文件重编译
对象。即使对 p15 做空改写（源文本不变）也会功能失败，因此这些混合 archive 的失败
结果全部作废，不作为候选结论。随后改用当前 `on_v3` 自带的完整
`libgrhsim_SimTop.a` 和同目录头文件重建 source-consistent baseline；baseline archive
SHA-256 为
`57cbfa920fb038a353b7f58c77f3221782b940e6fbad6b1673f85860301a4877`，baseline ELF 为
`178a6430d7ec5355e8293db78afbf2ccc3a421884e840a36d733a795013adc70`。候选 archive 和
ELF 分别为
`5a189a63f5a9a41fff482f2ec61c832231827461ecd435043071f5e65fcd95d6` 和
`069e2b15b55320b59d8dcb653bd6310ff4a6484c1f3443b9fc2949c9582572d7`；运行期间两份
baseline 输入身份均未变化。这个校正使后面的功能和性能比较具有同一生成版本的口径。

配置仍为 node030 CPU96–127、NUMA1、Host105、N=K=32、all-spin、Clang23/O3、ASLR
关闭、C100000；不设置外部负载门槛，也不剔除慢样本。source-consistent baseline
上的 C100 smoke 和 4 组 C100000 AB/BA 均通过 Difftest。

#### 结果

| 指标 | baseline 中位数 | candidate 中位数 | 配对变化中位数 | candidate 胜出 |
| --- | ---: | ---: | ---: | ---: |
| walltime / s | 11.925 | **11.820** | **−0.965%** | 4/4 |
| Host / s | 11.887 | **11.7835** | **−0.955%** | 4/4 |
| 全局 eval / µs | 46.521 | **46.117** | **−0.917%** | 4/4 |
| 全局 update / µs | 9.4735 | **9.2770** | **−2.409%** | 3/4 |
| 最大分区 eval / µs | 29.666 | 29.660 | −0.078% | 2/4 |
| 各分区 eval 合计 / µs | 532.6545 | **527.454** | **−1.008%** | 4/4 |
| 各分区 update 合计 / µs | 89.7125 | 89.429 | −0.355% | 3/4 |

walltime 四个配对均改善，范围为 −0.673% 至 −1.088%；AB 中位数 −1.046%，BA
中位数 −0.799%。最大分区 eval 几乎不动，说明这次变换减少的是各分区内部重复的
激活字节写入和 update 路径工作，尚未解决单个最慢分区的主 compute 锥。分区明细中
p3 eval 下降约 2.38%、p8 下降约 2.82%、p25 下降约 2.56%，而 p18 基本不变；因此
全局收益来自多分区累计工作量，不能宣称最大 ASC 已被拆小。

该候选仍是生成后原型，尚未迁入正式 emitter 或修改默认选项；更换仿真器和第二个
workload 尚未验证。下一步应在保持 source-consistent 基线的前提下，检查 active-byte
累加规则对 wide helper、跨 batch 可见性和不同生成版本的约束，再决定是否值得实现
为正式可选 lowering。

[结构扫描与构建清单](../../build/repcut_grhsim_20260925/active_dispatch_20261003/commit_active_accumulator_consistent2_20261009/candidate/build.json)、
[C100000 AB/BA 汇总](../../build/repcut_grhsim_20260925/active_dispatch_20261003/commit_active_accumulator_consistent2_20261009/ordinary_c100000/summary.json)、
[变换驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/commit_active_accumulator_20261009.py)。

### 7.83 连续 u64 状态布局与纯宽拼接复制：通用原型和消融（2026-10-09）

完成全部分区的统一结构扫描、功能对照、两个窗口的普通性能验证，以及布局/复制
消融。保留通用生成代码原型：**完整方案八对 walltime 全部更快，配对变化中位数
−1.611%**。收益主要与连续状态布局有关；在相同布局上单独加入复制循环仅为
−0.210%。p18 全程平均 eval 基本不动，不能据此宣布其主要 compute 瓶颈已解决。

#### 基线与变换范围

本节采用 §7.82 确认的 `producer_dirty_words_20261007/formal/on_v3` 完整包及其
source-consistent harness。baseline archive SHA-256 为
`57cbfa920fb038a353b7f58c77f3221782b940e6fbad6b1673f85860301a4877`，ELF 为
`178a6430d7ec5355e8293db78afbf2ccc3a421884e840a36d733a795013adc70`。
本节未叠加 §7.82 的 commit active-byte 累加原型；也不是对 §7.81 的另一份累计
ELF 直接继续叠加，因此不能把这些章节的百分比相加。最终完整候选 archive/ELF 为
`e035142fbe72030675b4e651fbff3fe11392f6f487022ed2958a8cae3cc0c032` /
`2b7070736f082081b10188288b1cd0d9b9c488a7d46a5f31723f4a271d4de369`。

变换包含两部分，统一扫描全部 32 个分区，不使用 RTL 模块、信号名称或 profile
白名单决定是否开启：

1. 将状态结构中分别命名的 64 位标量字段，改为按逻辑槽号排列的
   `std::array<std::uint64_t, N>`；对应字段引用改为数组索引。非 u64 字段保留相对
   顺序。31 个模型具有这类槽，p28 没有；最终 p28 的 164 个模型/包装对象，其
   机器码及重定位与 baseline 相同。
2. 对纯宽拼接，只接受每个目标 word 都完整来自一个 u64 状态槽、目标 word
   恰好覆盖一次、源槽号步长统一为 +1 或 −1、区域内没有其他操作的结构。
   将逐 word 展开的赋值改为普通 C++ 循环。共匹配 **18 个分区、19 处拼接、
   16,307 个 64 位 word**；选择条件不依赖具体 part 编号。

例如 p18/b18 的 1902-word 拼接，原来是 1902 组独立的 load/OR/store 表达式；
连续存储后可写为以下形式，其中目标数组是该拼接的临时值：

```cpp
for (std::size_t i = 0; i < 1902; ++i) {
    destination[i] = state_u64[2720 - i];
}
```

这些数字仅是实际匹配到的一例。Clang23 的真实对象中出现了 `pshufd` 与 `movdqu`
组成的反向向量复制循环，没有跨独立 C++ 字段进行指针运算。p18 原来这 1902 个
逻辑槽虽然占据连续的 15,216 B 区域，但逻辑槽顺序对应 **285 段**物理连续序列；
新布局将它们恢复成一段。按所测 x86-64 POD ABI 静态计算，全部状态结构合计仅
730,700→730,580 B，p18 为 27,080→27,072 B，因此不是明显缩小状态容量的优化。
访问顺序、地址和生成机器码一起改变；本轮没有用 PMU 进一步分离这些因素。

| compute 对象可执行字节 | baseline | 仅连续布局 | 布局＋复制循环 |
| --- | ---: | ---: | ---: |
| p10/b16 | 49,130 | 46,277 | 34,734 |
| p16/b17 | 37,381 | 34,734 | 11,506 |
| p18/b18 | 34,942 | 33,570 | 17,522 |
| 匹配的 18 个对象合计 | 627,701 | 629,696 | 476,617 |
| 整个模型 archive 合计 | 95,464,627 | 95,499,098 | 95,346,019 |

以上为可执行 section 字节数，不等于动态指令数或耗时。所有源文件统一暂存并全量
重编 7,454 个对象，编译器依赖文件检查确认没有混入 baseline 的旧模型头文件。
沿用既有 object section 对齐处理；下文所有普通、消融及诊断 ELF 的 **6,859 个
compute 入口均验证为 64 B 对齐**。只统计这一一致口径下的结果。

#### 普通 walltime：两个窗口、八对 AB/BA

配置为 node030 CPU96–127、NUMA1、Host105、N=K=32、all-spin、Clang23/O3、
ASLR 关闭、C100000。编译与运行串行；不设置空闲率门槛，不剔除功能正确的慢样本。
两个窗口各四对，配对 walltime 中位变化为 **−2.071% / −0.952%**。

下表前两列是各侧八次运行的**平均值**；末列先逐对计算
`100 × (candidate / baseline − 1)` 再取中位数，不能由前两列相除复算。

| 指标 | baseline 均值 | 完整候选均值 | 配对变化中位数 |
| --- | ---: | ---: | ---: |
| walltime / s | 12.06000 | **11.89625** | **−1.611%** |
| Host / s | 12.02050 | **11.85875** | **−1.604%** |
| 全局 eval / µs | 47.213375 | **46.559750** | **−1.560%** |
| 全局 update / µs | 9.322000 | 9.321125 | −0.042% |
| 最大分区 eval / µs | 30.436625 | 30.478125 | −0.079% |
| 各分区 eval 合计 / µs | 538.942250 | **532.405375** | **−1.389%** |

walltime **8/8 对更快**，范围 −2.312% 至 −0.249%。按均值计算节省
163.75 ms，即 1.358%；这是另一种统计量，与配对变化中位数 1.611% 区分使用。
p18 始终是全程平均 eval 最大的分区，时间均值略升 0.0415 µs，配对中位数接近
零；p6/p10/p16/p26 的全程平均 eval 配对变化分别为 −1.432%/−1.496%/−1.613%/
−1.705%。因此完整方案有整体收益，但不是把最大 ASC 或最大平均 eval 大幅压低。

#### 消融：主要收益在哪里

三个独立消融各四对 AB/BA，全部保持相同运行配置及 64 B 对齐：

| 比较 | baseline walltime 中位数 / s | candidate 中位数 / s | 配对变化中位数 | 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| 原 baseline → 仅 p18 布局＋循环（诊断） | 12.030 | 11.905 | −1.039% | 4/4 |
| 原 baseline → 全部分区仅连续布局 | 12.105 | 11.950 | **−1.322%** | 4/4 |
| 全部分区仅连续布局 → 布局＋循环 | 11.900 | 11.865 | **−0.210%** | 3/4，另 1 对持平 |

最后一组两侧只相差 18 个 compute archive member，其余 **7,436 个 member 完全
相同**。它表明“循环带来的大幅代码缩减”只贡献了较小的增量 walltime 改善；主要
收益与状态布局变更有关。这些比较位于不同窗口，不能把 −1.322% 和 −0.210%
相加，或将两者与完整方案相减来精确分摊时间。p18-only 仅用于诊断，保留的候选
采用全分区统一规则。

进一步用 §7.79 已冻结的独立步骤标签，对“仅布局 / 布局＋循环”做四对 batch
计时。两侧共用完全相同的六个探针对象，compute/commit 对象保留各自普通版本；
各批调用数、活跃次数、all-on 次数及活跃位数完全一致。以下是**活跃批耗时合计
除以全部固定标签 eval 数**的四轮均值，非活跃调用以零计，包含计时探针扰动。
这些标签来自此前独立发现，不声称每个标签步在本轮仍然是该分区决定全局结束。

| batch / µs 每固定标签 eval | 仅布局 | 布局＋循环 | 配对变化中位数 |
| --- | ---: | ---: | ---: |
| p6/b46 | 0.222052 | 0.185487 | −15.964% |
| p10/b16 | 0.796722 | 0.691119 | −13.260% |
| p18/b18 | 1.115157 | 1.061591 | −4.896% |
| p26/b19 | 0.163973 | 0.173704 | +6.942% |

p18/b18 每个固定标签 eval 实际净省约 **0.0536 µs**，p10/b16 约 **0.1056 µs**。
这解释了对象体积减半并不意味着 p18 eval 减半；其余批次和提交仍占大头。
p26 的小幅局部变慢完整保留，不按分区手动排除。带探针的整个 p18 eval 均值
69.006→69.526 µs，配对 +0.852%，也不能用单个改善 batch 代替整个 eval 的结论。
普通最终性能以上面的无 batch 探针 walltime 为准。

#### 验证与保留状态

真实模型校验版在新循环旁保留原始逐 word C++ 表达式，写入独立参考数组后逐次
比较；参考代码不从新循环的槽号公式反推。C100 和完整 C100000 Difftest 均通过。
完整运行中 **19/19 处都执行到**，合计 1,716,989 次拼接检查、1,592,548,306 个
逻辑 word 比较，无不一致。普通性能程序不含这些检查。

最终一致口径的全部验证合计 **50 次完整 C100000 Difftest、14 次 C100 smoke**：
普通性能/消融 40/10，batch 8/2，逐次参考对照 2/2；运行输入身份保持不变。
保留全分区结构原型及复现驱动，尚未迁入正式 emitter 或修改默认选项。
本轮没有修改 Verilator 路径，也没有第二个 workload 的泛化证据。下一步应把注意力
回到 p18 剩余活跃 compute/commit，而不是继续扩大对这条纯复制循环的收益预期；
正式迁入前还需在明确重建的累计源版本上验证叠加效果。

[完整汇总与逐分区数据](../../build/repcut_grhsim_20260925/active_dispatch_20261003/u64_array_concat_all_20261009_v2/summary.json)、
[全分区变换和构建](../../build/repcut_grhsim_20260925/active_dispatch_20261003/u64_array_concat_all_20261009.py)、
[64 B 对齐及最终二进制核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/u64_array_finalize_20261009.py)、
[消融与真实模型逐次校验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/u64_array_ablation_20261009.py)、
[普通交错复测驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/u64_array_trials_20261009.py)、
[固定标签 batch 诊断](../../build/repcut_grhsim_20260925/active_dispatch_20261003/u64_array_batch_20261009.py)、
[汇总与身份审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/u64_array_report_20261009.py)。

### 7.84 p18 动态路径重采与宽输出存储复用（2026-10-09）

在 §7.83 的最终全分区 u64/64 B 对齐版本上，完成独立瓶颈发现、全部 p18 batch
排序、阶段拆解，并保留一个新的通用生成代码原型：**宽输出直接使用输出端口的
存储，省去 eval 末尾从内部数组到端口的整块复制**。两窗口八对 C100000 AB/BA
的 walltime 全部更快，配对变化中位数 **−0.851%**；p18 全程平均 eval 为
**−1.860%**。本节没有叠加其他新候选，也没有改变正式 emitter 或默认选项。

#### 重新定位：compute 占大头，但最大 batch 只占 2.88%

基线 ELF SHA-256 为
`2b7070736f082081b10188288b1cd0d9b9c488a7d46a5f31723f4a271d4de369`，即上一节
最终完整候选。配置继续使用 node030 CPU96–127、NUMA1、Host105、N=K=32、
all-spin、Clang23/O3、进程级 ASLR 关闭和 compute 64 B 对齐。不设置空闲率门槛，
不剔除功能正确的慢样本，编译与性能运行串行。

先独立执行四次 C100000 timeline 发现，按每个采样步骤的四轮完成时刻中位数
选择最后完成的分区；排除预先约定的探针初始 127/128 两步，留下 3,148 步。
p18/p29/p10/p26 分别最后完成 **666/637/431/364 步**。p18 被选步骤中，与
次晚线程的完成时间差均值约 **7.992 µs**。随后冻结这些标签再做诊断，没有按
新候选是否更快重新选步；标签也不保证在以后每次运行中仍由 p18 最晚完成。

两次独立阶段探针对 p18 的 666 个固定标签得到：eval **48.9418 µs**，其中
prepare 0.6055、compute **39.7686**、commit **7.1428**、tail **1.1316 µs**，
平均固定点轮数 1.96847。compute 包含空 batch 调用，commit 是模型 eval 内部
状态提交，tail 包括公开输出刷新与上一轮输入快照；不是框架的 update/通信阶段。

另一个探针对全部 255 个 compute batch 记录调用数、活跃次数与活跃耗时。
两次运行的活动计数一致，以下时间为活跃调用耗时总和除以全部 666 个固定步骤，
再对两轮求平均；非活跃调用不计时，数字包含 batch 探针扰动。

| batch | µs / 固定标签 eval | 活跃调用数 / 每轮 | 占活跃 batch 总时间 |
| --- | ---: | ---: | ---: |
| b18 | 1.327670 | 659 | 2.881% |
| b96 | 0.751719 | 666 | 1.631% |
| b195 | 0.724452 | 1310 | 1.572% |
| b210 | 0.651026 | 1311 | 1.413% |
| b17 | 0.549609 | 656 | 1.193% |

前五项合计仅 **8.689%**，前十项为 **13.726%**。部分 batch 在一个 eval 的
两个固定点轮次都活跃，所以活跃次数可以大于标签步骤数。batch 探针的活跃时间
合计为 46.0856 µs，不能与另一个阶段探针的 compute 39.7686 µs 相减。

源码对应的主要结构是：b18 的状态输出拼接，b96 的布尔结果存储、变化检测及
reader 通知，以及 b195/b210 的布尔谓词、归约、状态增量与通知。b18 中最大的
1,902-word 拼接是完整的分区输出，并非只被读取少量位置的内部表，不能直接
套用 §7.81 的稀疏按需读取规则。但它存在另一份冗余拷贝：先填
`value_words_1902_slots_[0]`，再由 `refresh_outputs()` 整块复制到公开端口。

#### 保留规则：让值直接使用最终输出存储

规则统一扫描全部分区，只按生成结构选择至少 8 个 64 位 word 的数组输出：

- 最终发布是 `output_port = internal_value_slot`，且该 slot 只对应一个输出。
- 端口是独立拥有的数组字段；模型 C++ 中没有既有的端口读取或其他写入，仅有
  这一次最终发布和可识别的初始化；头文件中也只存在该字段的声明。
- 对内部数组 bank 的使用都能识别为具体 slot 或整体初始化，没有未知地址逃逸
  或整 bank 操作。将该 slot 的全部内部使用统一改为输出字段，保持计算顺序。
- 当前 RepCut 框架在所有 eval 完成后，才进入读取这些输出的 update 阶段。
  因此端口在所属 worker 的 eval 内较早写入，不会向其他分区提前传播。

例如大拼接原来是“状态 → 内部数组 → 输出端口”，现在直接“状态 → 输出端口”。
数组类型、值计算、固定点迭代、变化通知和跨分区复制关系保持原样。保留旧内部
bank 的字段和初始化以维持类布局，并在对应 bank 初始化处补齐输出清零，覆盖
重复 init 的生成语义。本轮没有合并多个输出，也没有按 part、RTL 模块或信号名称
选择规则；公开端口在 eval 返回前不可被外部并发观察，是这一 RepCut 原型的使用边界。

匹配 **32 个分区、328 个输出、46,837 个 word**。原有一轮全分区输出发布中，
这些复制的静态 payload 合计 **374,696 B**；这不是实测内存总线流量，也不表示
跨分区通信量下降。p18 匹配 9 个输出、2,129 word，其中大输出为 1,902 word。
仅替换 **159 个 archive member**，其余 7,295 个保持字节相同；所有 6,859 个
compute 入口仍验证为 64 B 对齐。匹配对象可执行 section 合计
4,678,757→4,680,252 B，说明本轮收益不是来自明显缩小机器码。

#### 普通性能：两窗口、八对 AB/BA

最终候选 ELF SHA-256 为
`d6e196d8a27448f384dac83148241bddb1acfe2bc3f5be516cc21901a1e9e28c`。两个窗口
各四对，中间插入独立功能摘要和阶段诊断；窗口内的配对 walltime 中位变化分别为
**−0.709% / −1.032%**。下表前两列为各侧八次运行的平均值，最后一列为
`median(100 × (candidate_run / baseline_run − 1))`，不能由前两列直接相除复算。

| 指标 | baseline 均值 | candidate 均值 | 配对变化中位数 |
| --- | ---: | ---: | ---: |
| walltime / s | 11.831250 | **11.731250** | **−0.851%** |
| Host / s | 11.794750 | **11.695875** | **−0.823%** |
| 全局 eval / µs | 45.496250 | **44.984750** | **−1.181%** |
| 全局 update / µs | 9.976875 | 9.931500 | +0.192% |
| p18 / 最大平均分区 eval / µs | 29.402625 | **28.832875** | **−1.860%** |
| 各分区 eval 合计 / µs | 526.280625 | **509.921625** | **−3.072%** |

walltime **8/8 对更快**，范围 −1.206% 至 −0.417%；按均值计算节省 100 ms，
约 0.845%，与配对百分比是两种统计量。p18 也为 8/8 对更快。其他分区全程
eval 的配对变化包括 p3 −10.797%、p10 −4.402%、p6 −1.797%、p26 −1.027%；
p29 为 +0.189%，没有因局部退化而手动排除该分区。全局 update 没有稳定下降，
也没有修改通信路径，因此不把收益解释为通信压缩。

#### 机制复核与功能覆盖

基线与候选共用完全相同的两个输出摘要探针对象，在每个 worker 的 eval 返回后，
把全部匹配输出加入两种独立的 64 位滚动摘要，并纳入 step 序号和访问次序。
C100 与完整 C100000 的 32 个分区摘要、调用数、word 数及结束 step 全部一致。
完整运行每侧累计处理 **9,372,177,374 个 word**，覆盖每一个仿真 step，Difftest
同时通过。这里是完整输出流的双摘要一致，并非逐 word 双模型直接比较或形式证明。
普通性能 ELF 不含该探针。

另用完全相同的三个阶段探针对象，保留各侧普通 compute/commit/state 对象，
完成两对 C100000 AB/BA。p18 固定 666 步的阶段结果如下，时间为每轮条件均值
再跨轮平均；固定点轮数两侧均为 1.96847。

| p18 固定标签阶段 / µs | baseline | candidate | 均值差 |
| --- | ---: | ---: | ---: |
| eval 合计 | 49.122981 | **47.295758** | −1.827223 |
| compute | 39.938512 | 39.269342 | −0.669170 |
| commit | 7.150138 | 6.986666 | −0.163472 |
| tail：输出刷新与输入快照 | **1.138387** | **0.206258** | **−0.932129** |

tail 的配对变化为 **−81.876%**，支持“省去内部数组到端口的重复复制”这一机制。
eval 合计的配对变化为 −3.720%；额外的 compute/commit 变化还可能包含访问地址、
缓存、频率和运行波动，本轮没有通过 PMU 分离这些因素，不能把全部 1.827 µs
都算作直接删除复制的成本。相邻两沿合计 eval 86.9501→84.0979 µs，配对
−3.280%，没有把整个收益简单移到另一沿。固定标签诊断与无探针全程平均 eval
的统计集合不同，二者百分比不应混用。

本节保留结果共 **30 次完整 C100000 Difftest、11 次 C100 smoke**：独立发现/
batch/阶段重采为 8/3，普通性能为 16/4，输出摘要与候选阶段对照为 6/4。
全部运行输入身份不变。当前仍是 XiangShan 的生成代码原型，正式迁入应以 IR 的
输出方向、存储使用关系及 RepCut 发布屏障表达约束，不能依赖具体生成名称。

这次真正减少了一段可验证的重复工作，但最终 p18 的固定瓶颈步仍有约
**39.27 µs compute、6.99 µs commit**。下一步的主线仍应是分散的布尔结果计算、
变化检测与通知效率，不能因宽输出复制已改善而声称主要 compute 瓶颈已经解决。

[完整数据与身份审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/output_storage_forward_20261009/summary.json)、
[独立发现与 p18 路径剖析](../../build/repcut_grhsim_20260925/active_dispatch_20261003/p18_current_profile_20261009/summary.json)、
[剖析复现驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/p18_current_profile_20261009.py)、
[全分区规则及构建](../../build/repcut_grhsim_20260925/active_dispatch_20261003/output_storage_forward_20261009.py)、
[静态使用关系清单](../../build/repcut_grhsim_20260925/active_dispatch_20261003/output_storage_forward_20261009/scan.json)、
[输出摘要与共享阶段探针](../../build/repcut_grhsim_20260925/active_dispatch_20261003/output_forward_diagnostics_20261009.py)、
[汇总驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/output_forward_report_20261009.py)。

### 7.85 保留优化的统一累计验证与瓶颈重采（2026-10-09）

本轮先解决实验分支未累计的问题。§7.84 的输出存储复用版本并未包含 §7.77–7.81
的另一条累计线，也没有包含 §7.82 的 commit 激活累加。以 §7.84 的最终 ELF
`d6e196d8a27448f384dac83148241bddb1acfe2bc3f5be516cc21901a1e9e28c` 为本轮起点，
将其完整 7,454 个 C++ 源文件、98 个头文件冻结到独立快照；每层从上一层继承，
改写源码后重新编译所需对象，不导入历史候选对象。改变模型成员布局时重编该
模型的全部实现及包装层，编译依赖检查只允许引用这一层的模型源码和头文件。

配置继续为 node030 CPU96–127、NUMA1、Host105、N=K=32、all-spin、Clang23/O3、
compute 入口 64 B 对齐、进程 ASLR 关闭、C100000。不设核空闲率门槛，不剔除功能
正确的慢样本，编译和性能运行串行。每层先做 C100 smoke，再做四对 AB/BA；
最终累计收益另与起点直接对照，并加入同窗口 Verilator O3 参考。

#### 首两层增量验证

静态步长规则重新扫描全部当前 compute 源码，命中原有的 96 组归约、17 个文件。
缓存层重新审计这些组所属模型的全部写入点，确认 98,316 条组内输入引用均有本地
写入点、49,158 个目标没有其他普通写入点，再应用唯一写者和输入/目标不重叠检查。
为缓存新增成员后，完整重编 478 个相关编译单元。两个阶段均保持 6,859 个 compute
入口的 64 B 对齐。以下百分比是四对逐对变化的中位数，不能相加作为累计收益。

| 增量 | A walltime 均值 / s | B walltime 均值 / s | 配对变化中位数 | 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| 本轮起点 → 加静态步长 | 11.5625 | 11.4350 | −1.123% | 4/4 |
| 上一层 → 加布尔归约缓存 | 11.4525 | 11.2450 | −1.790% | 4/4 |

两层的 p29 全程平均 eval 配对变化分别为 −3.358% 和 −10.539%，与此前寻址简化、
输入未变化时跳过重复归约的机制相符；这不是 p29 瓶颈步骤的条件均值。两层合计
16 次完整 C100000 Difftest 和 4 次 C100 smoke 通过。这里先记录已完成的阶段，
后续组合及最终直接对照结果在本节继续追加。当前仍为通用生成代码原型，未改生产默认。

[累计构建与增量驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cumulative_retained_20261009.py)、
[完整初始源码快照](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cumulative_retained_20261009/s0_current/snapshot.json)、
[静态步长增量结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cumulative_retained_20261009/increment_1/paired_report.json)、
[归约缓存增量结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cumulative_retained_20261009/increment_2/paired_report.json)。

#### 后续保留规则与组合语义验证

在上述两层之后，继续叠加宽输入 8 字分块检查和稀疏表按需读取。前者统一扫描
32 个分区，命中 16 个输入组/9 个模型，并重新验证 376,704 个输入位的激活映射。
后者仍命中 10 张表/13 个 compute 源文件，使用原有至少 64 B/静态读点的成本
门槛；适配连续 u64 存储时，位置表记录数组下标，通过 `u64_slots_[index]` 读取，
不把 `std::array` 对象的起始地址当作其首元素地址。其余标量字段仍用编译器
计算的 `offsetof` 和 `memcpy` 取值，完整输入/状态稳定性审计重新执行。

本轮最终保留的 commit 累加规则采用更窄的通用资格条件：单个 commit supernode
内，激活数组的全部访问必须是直接常量掩码 OR；至少 4,000 次直接写入，选中字节
至少重复 128 次。统一扫描得到 3 个函数、14,891 次可合并写入和 11 个局部累加
字节。它不是 §7.82 的完整 36 函数覆盖。实际命中的 p2/p10/p24 只是结果，资格
判断没有分区、模块或信号名称条件。

| 增量 | A walltime 均值 / s | B walltime 均值 / s | 配对变化中位数 | 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| 缓存后 → 加输入分块 | 11.2425 | 11.2125 | −0.267% | 3/4 |
| 上一层 → 加按需取值 | 11.1725 | 11.0600 | −1.029% | 4/4 |
| 上一层 → 加直接 OR 的 commit 累加，首窗口 | 11.1075 | 11.0700 | −0.360% | 4/4 |
| 同一 commit 对照，第二窗口 | 11.0500 | 11.0225 | −0.407% | 3/4 |

commit 两窗口合并的配对中位变化为 **−0.361%，7/8 对更快**；全部成功样本保留。
以上仍是不同窗口的增量，最终整体收益以起点/累计版本的直接比较为准。
最终保留包为 `cumulative_retained_20261009/s5_commit`，ELF SHA-256 为
`15aecc3089d05280c4c2f4feb625f80fd42ee7abd7dffcce80c9ace308d06860`，archive 为
`b7b5a0dbd62347b39eab7ebf9ecf16566b25aeece511eadedc8cda762d719fea`。

独立组合校验版只重编 42 个模型对象，在同一次完整 C100000 中同时执行：

- 每一次缓存跳过都重新计算全部目标和 reduced/changed 标志：96 组均有执行，
  合计 **2,060,758 次跳过**检查通过。
- 每个改写的输入组，从相同初始激活位分别计算旧表达式和新分块表达式，再比较
  完整激活数组及 pending 状态。
- 保留旧表构造，逐元素比较新取值器，并在实际读取时再次对照；**10/10 张表**
  实际执行，累计 **606,005 次构造**检查通过。
- 对保留的 commit 函数，在完全相同的状态变化分支下，另行立即 OR 到影子激活
  数组，在 supernode 退出前与延迟合并的数组比较；**3/3 函数**实际执行，累计
  **300,150 次边界比较**通过。

该校验版的 C100 smoke 与完整 Difftest 均通过，耗时不混入普通性能数据。
五层实际 C++ 编译 walltime 分别为 1.702、9.899、3.923、0.986、6.043 s，
含 archive 审计及独立 harness 构建的各层总耗时为 7.294、15.639、9.440、6.541、
11.580 s。这是冻结模型上的增量构建成本，不是从 RTL 完整生成/编译的成本。

[最终保留构建](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cumulative_retained_20261009/s5_commit/build.json)、
[组合语义校验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cumulative_retained_20261009/semantic_composition/summary.json)、
[校验驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cumulative_semantics_20261009.py)。

#### 最终直接对照：两个窗口、八组正反序三方运行

每组按“起点 GrhSIM → 累计 GrhSIM → Verilator”或相反顺序运行，两个窗口各四组；
第二窗口在独立 timeline 和输出摘要诊断之后。三者的 runtime_config 完全相同：
32 lane、31 个后台 worker、Host 在 CPU105 承担 lane9、逐 lane atomic spin、
push update、Host/worker 均永久轮询。Verilator 复用冻结的 Clang23/O3
`verilator_lock_elision_final/candidate/emu`，不是本轮重新优化的 Verilator。

| 普通性能指标 | 本轮起点均值 | 累计版本均值 | 配对变化中位数 | 累计更快对数 |
| --- | ---: | ---: | ---: | ---: |
| walltime / s | 11.537500 | **11.065000** | **−3.863%** | **8/8** |
| Host / s | 11.504375 | **11.032000** | −3.886% | 8/8 |
| 全局 eval / µs | 44.833000 | **42.551375** | −5.065% | 8/8 |
| 全局 update / µs | 9.251750 | 9.262500 | +0.431% | 2/8 |
| 最大分区平均 eval（p18）/ µs | 28.834875 | **28.523500** | −1.084% | 8/8 |
| 各分区平均 eval 合计 / µs | 510.606875 | **500.429125** | −2.019% | 8/8 |

walltime 两窗口配对中位变化分别为 −4.038% / −3.859%，八对范围 −5.086% 至
−3.652%。按均值计算节省 **472.5 ms，即 4.095%**；配对中位数为 **3.863%**。
两种统计方法明确区分，不用均值之比复算配对中位数，也不把各层增量相加。

同窗口 Verilator O3 的 walltime 均值为 **20.856250 s**，累计 GrhSIM 相对它的
配对中位变化为 **−46.849%**。起点 GrhSIM 相对它已经为 −44.607%，因此
46.849% 是包含此前全部成果的后端对照，不能算成本轮新获得的收益。

p29/p26/p15 的全程平均 eval 配对变化分别为 **−12.142% / −7.807% / −9.252%**；
p10/p24 为 +0.642% / +3.209%，没有排除这些分区或相应样本。全局 update 未稳定
下降。最大平均分区仅改善约 1%，而全局 eval 改善约 5%，说明减少其他步骤的
最晚完成线程也能降低 walltime，不能仅用全程平均最大的分区估算收益。

同一套输出探针对象分别链接两侧普通模型，在每个 worker 的 eval 返回后，比较
328 个宽输出的两种独立滚动摘要。C100 和 C100000 的全部 32 个分区摘要、调用
次数、word 数与结束 step 完全一致；完整运行每侧处理 **9,372,177,374 个 word**。
这是全输出流的双摘要一致，不是逐 word 双模型比较或形式证明。

#### 新累计版本的冻结瓶颈步骤

先用累计版本独立运行四次 timeline，按每步各线程完成时刻的跨轮中位数选择
最后完成者，预先排除最初 127/128 两个探针样本，得到 3,148 个步骤。再冻结
标签，用三者各四次独立运行比较相同仿真步骤。下表是各运行条件均值的跨轮平均，
来自 timeline 诊断程序，不能与普通程序的全程平均 eval 混用。

| 分区 | 标签步数 | 本轮起点瓶颈步 / µs | 累计瓶颈步 / µs | Verilator 同步 / µs | 累计相邻两沿合计 / µs | Verilator 两沿合计 / µs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| p18 | **719** | 48.302 | **47.786** | 50.063 | **85.156** | 75.211 |
| p29 | **450** | 54.955 | **47.564** | 29.595 | **49.367** | 65.691 |
| p10 | 440 | 41.205 | **40.953** | 56.220 | **69.991** | 78.157 |
| p24 | 361 | 21.720 | **21.583** | 29.856 | **41.716** | 63.776 |
| p26 | **357** | 55.098 | **50.843** | 27.822 | **65.439** | 84.122 |
| p6 | 196 | 40.687 | **40.243** | 43.849 | **70.696** | 97.675 |

“Verilator 同步”指同一批 step 上该分区的耗时，不要求它在 Verilator 中也为
最后完成者。两沿合计对去重后的相邻步对取平均，不能由单沿条件均值简单乘二。
p29 的 450 步和 p26 的 357 步均为 clock=0；p18 的 719 步中，688 步为 clock=1。

p18 最晚完成占比 **22.840%**，发现样本中比次晚线程晚 **8.763 µs**；p29 为
14.295% / 7.516 µs，p26 为 11.341% / 3.745 µs。这是发现样本的完成时间差，
不是已实现的节省，也不保证在另一次运行中仍由同一分区最晚完成。

p29/p26 的瓶颈沿仍明显慢于 Verilator，但两沿合计已经更少，说明计算集中在
一个半周期仍会拉长对应步骤。p18 则是瓶颈沿相近、两沿合计仍偏慢。二者需要
分开处理，不能从某一沿或全程平均的单个数字判断剩余问题。

#### 冻结步骤的 PMU：工作量与执行效率

再用四对 Verilator/累计 GrhSIM AB/BA，测量 p29/p26 以及 p18/p10 对照组。
生产模型对象保持各自普通版本不变，只替换两个框架探针对象；事件组为 cycles、
instructions、branches、branch misses。全部样本 enabled/running 时间一致，
没有事件复用。eval 计时排除 perf 读取，计数差额包含两个时钟读取；普通 walltime
不混入这些诊断运行。

下表前两列均为四轮条件均值的平均，百分比仍为配对变化中位数。IPC 是每个 CPU
周期完成的指令数；它用于区分“执行更多指令”和“每条指令花更多周期”。

| 固定瓶颈步指标 | Verilator | 累计 GrhSIM | GrhSIM 配对变化 |
| --- | ---: | ---: | ---: |
| p29 指令数 | 281,393 | 349,871 | +24.336% |
| p29 CPU 周期 | 104,094 | 166,042 | +59.403% |
| p29 IPC | 2.703 | 2.107 | −21.999% |
| p29 分支数 / 误预测数 | 2,654 / 36.57 | 30,428 / 80.13 | +1046.703% / +119.642% |
| p26 指令数 | 268,996 | 331,708 | +23.313% |
| p26 CPU 周期 | 95,855 | 179,592 | +87.421% |
| p26 IPC | 2.806 | 1.847 | −34.205% |
| p26 分支数 / 误预测数 | 10,992 / 23.94 | 6,251 / 616.55 | −43.128% / +2471.115% |
| p18 指令数 | 378,848 | 260,424 | −31.259% |
| p18 CPU 周期 | 169,077 | 169,418 | +0.234% |
| p18 IPC | 2.241 | 1.537 | −31.419% |
| p18 分支数 / 误预测数 | 5,466 / 566.21 | 10,760 / 1129.34 | +96.875% / +99.508% |

p29/p26 有效频率配对变化仅 −0.344% / −0.457%，不能解释约 59% / 87% 的
周期差；p18 有效频率反而高约 1.506%。p10 的指令/周期分别少 37.433% /
25.762%，当前不是最明显的 GrhSIM 对 Verilator 回退点。

PMU 中两沿合计也重复了 timeline 的方向：p29 指令/周期分别少 **43.226% /
26.105%**，p26 少 **49.315% / 20.259%**；p18 则指令少 **14.854%**、周期多
**19.918%**，分支误预测 712.42→1824.04。不同探针/窗口的绝对耗时不互相拼接。

这些数据支持下一步保留两条明确线索：优先在 p18 新冻结步骤上采样周期和分支
误预测地址，查明较低 IPC 对应的布尔结果存储、变化检测或通知路径；同时把
p29 的约三万次分支映射回模型逻辑、循环和调度，分析 p29/p26 在 clock=0 的
工作集中及可安全跳过的重复计算。p29 误预测绝对次数较小，不应仅凭其倍数
优先做误预测优化；p18/p26 的误预测是值得定位的线索，但计数器尚未证明它能
解释全部周期差。任何进一步消除或移动计算都要保持输出在每个 eval 返回时的
可见语义，不能直接把工作挪到另一沿，也不按分区/信号白名单生成优化。

最终保留线相关验证共 **99 次完整 C100000 Difftest、27 次 C100 smoke**，全部
通过；7,552 个最终源码/头文件按逐层清单重建 SHA-256 并核对一致，最终 archive
相对起点有 **497 个成员变化、6,957 个成员不变**。所有运行配置一致，输入及
各 ELF/archive 身份核验通过，compute 保持 64 B 对齐。当前保留为一套完整、可
复现的累计生成代码原型；正式 emitter/生产默认保持原状态，泛化验证仍限本 workload。

[三方普通性能、冻结步骤与摘要结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cumulative_retained_20261009/summary.json)、
[独立发现标签](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cumulative_retained_20261009/diagnostics/labels.json)、
[PMU 完整结果](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cumulative_retained_20261009/pmu/summary.json)、
[最终运行与源码审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cumulative_retained_20261009/final_audit.json)、
[三方与 timeline 驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cumulative_diagnostics_20261009.py)、
[PMU 驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cumulative_pmu_20261009.py)。

### 7.86 累计版本 p18 的周期与误预测地址归因（2026-10-09）

继续以 §7.85 最终 `s5_commit` 为基线，普通 ELF SHA-256 为
`15aecc3089d05280c4c2f4feb625f80fd42ee7abd7dffcce80c9ace308d06860`。
固定该节独立发现的 **719 个 p18 瓶颈步骤、694 对去重相邻步**，不根据新探针
的耗时重新挑选。仍使用 node030 CPU96–127、Host105、NUMA1、N=K=32、
all-spin、Clang23/O3、64 B compute 对齐、进程 ASLR off、C100000。

cycles 和 branch-misses 各完成四对 Verilator/GrhSIM AB/BA，共 16 次完整
Difftest 和 4 次 C100，通过全部功能签名及输入身份检查。两个后端各自仅替换
common/eval 两个框架对象，模型对象不变。事件仅在 p18 worker 的固定步骤对
内启用，全部区间 enabled/running 相同，样本无丢失或 throttle。周期采样间隔
1,000,003，误预测间隔 8,191；不将诊断程序 walltime 当成普通性能收益。

#### 周期主成本与分支密集区域不同

下表仅统计真正的 719 个瓶颈步骤，数字是四次 GrhSIM 运行的 IP 样本数。
IP 指采样时的机器指令地址；这类非 precise 事件存在 skid，落点可能晚于实际
产生事件的指令，因此只能定位热区域，不能把单条落点直接认作出错分支。

| 区域 | 周期样本 | 周期样本占比 | 误预测样本 | 误预测样本占比 |
| --- | ---: | ---: | ---: | ---: |
| compute | 418 | **83.94%** | 253 | 60.10% |
| 模型内部 commit | 68 | **13.65%** | 158 | **37.53%** |
| eval 外层派发 | 7 | 1.41% | 7 | 1.66% |
| 其他 | 5 | 1.00% | 3 | 0.71% |

单个大提交函数 c256 占 62 个周期样本、143 个误预测样本，即全部瓶颈步骤
样本的 12.45% / 33.97%。最大的单个 compute 函数 b18 仅 13 个周期样本，
占 2.61%；其余分散在 b195、b80、b17、b209 等。这些是样本比例，不能直接
换算成可回收 walltime。只优化 c256 或最大 compute 块，都不足以消除 p18
剩余计算成本；模型 commit 也不是 RepCut 全局通信 update。

独立采样窗口内，固定瓶颈步骤的累计 CPU 周期 G/V 为
490,580,241 / 485,343,483（**+1.079%**），相邻但未被选为瓶颈的步骤为
351,765,468 / 209,886,975（**+67.598%**），去重两沿合计 **+21.161%**。
对应的误预测事件总数分别多 88.941% / 420.353% / 145.238%。这些百分比取
两侧全部区间事件数之比，不是 §7.85 的配对时间中位数。

这再次限定了优化目标：两沿整体差距很大，但主要拖住全局阶段的 p18 步骤与
Verilator 周期接近。减少非关键沿的工作仍有价值，却不能按“两沿节省多少”
直接预报 walltime。误预测明显更多，但尚不能把全部额外周期都归因于误预测。

#### 对应到真实代码

对 14 个 GrhSIM 热函数仅增加行号信息重编译，逐一检查原有 allocated section
字节和重定位目标/加数完全一致，再按函数内偏移映射采样地址。基于完整累计
源码视图核验，没有用较老生成源码覆盖已保留的优化。

compute 落点仍包括输出拼接、布尔结果生成/新旧值比较、分组变化归约、活动
掩码通知以及标量选择。b18 最热落点是已有的连续 u64 输出复制循环；不能因
它源码短就认为不耗时，也不能把已有循环优化重新作为新方案。

c256 的 143 个误预测样本按源代码落点分类：45 个在状态比较，28 个在外层
写使能判断，28 个在活动或 dirty 通知，11 个在状态写回，31 个在 next 值
读取/已有分组等附近。该分类保留 skid 限制，并非精确的分支来源分摊。
生成代码仍存在“写使能判断 → 新旧状态比较 → 写回并通知”的双层控制流。
同一等价状态在 Verilator 的对应 `nba_sequent` 路径直接赋值；GrhSIM 必须
保留精确激活，不能照搬赋值并删除通知。既有 same-reader 分组、布尔别名补全
和 producer dirty-word 已在本轮基线中，后续候选需要处理其覆盖之外的通用结构。

[冻结模型构建核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cumulative_p18_path_20261009/build.json)、
[周期地址分布](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cumulative_p18_path_20261009/ip_cycles_results.json)、
[误预测地址分布](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cumulative_p18_path_20261009/ip_branch-misses_results.json)、
[机器码与源码映射](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cumulative_p18_path_20261009/code_audit.json)、
[复现驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cumulative_p18_path_20261009.py)。

#### 同一步的前端供指与执行后端阻塞

继续复用 §7.85 原有的两个 PMU 二进制，不重编任何对象。另完成四对 G/V
C100000 AB/BA，事件组为 cycles、instructions，以及 §7.38 已核验的 Zen4
`de_no_dispatch_per_slot` 的 `no_ops_from_frontend`（event 0x1a0、mask 0x01）
和 `backend_stalls`（mask 0x1e）。全部区间计数器 enabled/running 相等，
没有复用缩放。

“前端”在这里指 CPU 取指、解码及供给待执行操作的路径，不是 RepCut Host；
“执行后端”也不是 GrhSIM/Verilator 后端选项。两类事件分别除以
`6 × cycles`，得到未利用派发槽的比例，**不是 walltime 占比**。表中均为
四次运行的固定瓶颈步骤条件均值之平均。

| 分区 | 前端供指不足 V / G | 执行后端阻塞 V / G | IPC V / G |
| --- | ---: | ---: | ---: |
| p18 | **57.23% / 69.33%** | **3.42% / 1.74%** | **2.265 / 1.538** |
| p10 | 56.54% / 65.54% | 8.19% / 3.03% | 1.996 / 1.686 |
| p26 | 37.71% / 62.48% | 12.97% / 4.09% | 2.809 / 1.843 |
| p29 | 46.27% / 60.81% | 8.31% / 2.73% | 2.701 / 2.103 |

p18 的前端事件绝对次数也增加：574,217→704,612 槽/固定瓶颈步；执行后端
阻塞事件为 34,275→17,670。该窗口 p18 指令数仍少 **31.259%**，CPU 周期
配对多 **1.179%**；去重两沿指令少 **14.853%**，周期多 **21.442%**，前端
比例 56.20%→67.96%，执行后端比例 3.86%→1.91%。因此较低 IPC 的主要
差异线索在 CPU 前端供给，当前证据不支持先把重点放在 ALU 吞吐或执行后端
阻塞。这里没有把这些比例乘 walltime，或拿不同探针绝对时间拼接。

前端供给不足仍可能包含指令缓存/操作缓存、解码吞吐、控制流和分支恢复等
影响；本组事件**不能把它们进一步分离，也没有证明 I-cache miss 独占主因**。
这与 IP 样本的“分散 compute 占主成本、commit 更集中地出现误预测”一致。
下一步宜对真实活跃 compute 路径分离供指来源与预测恢复，再选择能减少实际
展开工作或控制流的通用 IR 规则；不能只因源码更新条数减少、函数变小或静态
分支数变化，就把它计作整机收益。p29/p26 的单沿集中问题仍需单独保持两沿口径。

本节成功诊断合计 **24 次完整 Difftest、6 次 C100 smoke**。最终复核所有输入、
普通累计 ELF/archive 和 14 个映射源码身份不变。保留的性能基线仍为 §7.85
`s5_commit`，未改正式 emitter、生产默认、RTL 或 Verilator 路径。

[前端/执行后端完整计数](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cumulative_p18_path_20261009/pipeline/summary.json)、
[计数复现驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cumulative_pipeline_20261009.py)、
[本轮最终身份与运行审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cumulative_p18_path_20261009/final_audit.json)。

### 7.87 累计版本的前端断供与地址翻译分离（2026-10-09）

继续使用 §7.85 的 `s5_commit` 完整累计基线、冻结瓶颈标签与 §7.86 的运行
配置。p18 仍为 719 个瓶颈步、694 对去重相邻步；另外观察 p10/p26/p29，
不按新测量结果重新选择步骤。六种 PMU 事件组各四对 G/V AB/BA，共完成
**48 次 C100000 Difftest、12 次 C100 smoke**，全部功能签名、运行配置、
输入身份核验通过，所有采样区间 enabled/running 相等。

cache/sources/tlb 三组直接复用 §7.85 的 PMU binary；latency/speculation/
redirects 三组只替换两个框架探针对象，两边模型对象均不变，GrhSIM 的
6859 个 compute 入口仍为 64 B 对齐。普通累计 ELF 与 archive 的 SHA-256
仍与 §7.86 相同。本小节中的计时仅作诊断，不混入普通 walltime 收益。

#### 区分完全断供、带宽不足和无效推测操作

事件及公式依据 Linux 的 [Zen4 pipeline 指标](https://github.com/torvalds/linux/blob/v6.8/tools/perf/pmu-events/arch/x86/amdzen4/pipeline.json)、
[派发事件](https://github.com/torvalds/linux/blob/v6.8/tools/perf/pmu-events/arch/x86/amdzen4/other.json)
和 [退休操作事件](https://github.com/torvalds/linux/blob/v6.8/tools/perf/pmu-events/arch/x86/amdzen4/core.json)。

- **完全断供**：`0x1a0/0x01` 加 `cmask=6`，统计六个派发槽都因前端无操作
  而空置的 CPU 周期，再除以 cycles。这是 frontend latency 指标，不只包含
  缓存 miss，也可能包含分支重定向后的供给空泡。
- **供给带宽不足**：原前端空槽比例减去上述完全断供比例，即有供给但没有填满
  派发宽度的部分；不是源代码中的算术运算占比。
- **无效推测操作**：`(dispatched_ops - retired_ops) / (6 × cycles)`。
  派发操作用 `0xaa/0x07`，退休操作用 `0xc1`。它只数被派发后没有退休的
  操作，**不包含预测恢复期间没有派发操作的空周期**，不能用它代表分支错误
  的全部时间代价。

下表绝对值均为四次运行的固定瓶颈集合条件均值之算术平均，V/G 表示
Verilator/GrhSIM。后两类槽比例不是 walltime 占比；不同事件组分开运行，
不把这些百分比拼成严格的整机时间分解。

| part | 完全断供 V/G | 供给带宽不足 V/G | 无效推测操作 V/G |
| --- | ---: | ---: | ---: |
| p18 | **29.32% / 45.88%** | **27.11% / 23.30%** | 1.35% / 2.36% |
| p10 | 34.36% / 40.56% | 21.96% / 24.75% | 0.99% / 2.02% |
| p26 | 17.84% / 35.59% | 20.84% / 27.21% | 0.94% / 1.93% |
| p29 | 21.25% / 33.60% | 25.27% / 27.67% | 0.18% / 0.19% |

p18 的完全断供绝对周期为 **47,910→77,467/瓶颈步**。其未被选为瓶颈的
相邻步，完全断供为 26.29%→41.63%；去重两沿为 28.40%→44.10%。因此，
相比继续增加算术吞吐或只调整普通解码带宽，**优先减少供给中断更有依据**。
这仍不是把多出的 29,557 个断供周期全部判成某一种 miss。

#### 指令缓存 miss 总量不是 p18 瓶颈步的简单解释

缓存与地址翻译事件采用 [Zen4 cache 定义](https://github.com/torvalds/linux/blob/v6.8/tools/perf/pmu-events/arch/x86/amdzen4/cache.json)。
指令缓存 miss 为 `0x18e/0x18`，操作缓存 miss 为 `0x28f/0x04`；L1 指令
TLB miss/L2 hit 为 `0x84`，两级都 miss、请求页表遍历为 `0x85/0x0f`。
TLB 是缓存虚拟地址到物理地址翻译的结构；页表遍历请求并不等同于缺页或磁盘 I/O。

| p18 每固定瓶颈步 | V | G |
| --- | ---: | ---: |
| 退休指令 | 378,848 | 260,424 |
| 指令缓存 miss | 37,572 | 34,381 |
| 操作缓存 miss | 32,992 | 30,223 |
| 普通解码器供给占比 | 99.53% | 97.69% |
| L1 指令 TLB miss、L2 hit | 339.88 | 526.34 |
| 两级指令 TLB 都 miss，请求页表遍历 | **210.79** | **369.29** |
| 退休分支误预测 | 568.67 | 1,130.06 |
| 非分支误预测导致的流水线重启 | 39.55 | 19.84 |

普通解码器供给占比是 `decoder_ops / (decoder_ops + op_cache_ops)`，不是
cache hit rate；这里没有将 loop-buffer 供给混入分母。两侧绝大多数操作都来自
解码器，不能解释成只有 GrhSIM 没有利用操作缓存。p18 指令缓存 miss 总数
配对少 **8.485%**，而指令少 **31.259%**，每千指令 miss 仍从 99.17 增至
132.02。非关键相邻步的 miss 则多 58.546%，去重两沿合计多 11.621%。必须
区分这些集合，不能把单沿缓存总量结论推广到两沿。

分支事件依据 [Zen4 branch 定义](https://github.com/torvalds/linux/blob/v6.8/tools/perf/pmu-events/arch/x86/amdzen4/branch.json)：
误预测用 `0xc3`，非分支重启用 `0x96`。p18 瓶颈步误预测约翻倍，但非分支
重启减少，暂不支持将主要差异归为后者。无效推测槽只多约 1 个百分点，也不能
反过来声称分支影响很小，因为预测恢复的空泡可能落在完全断供指标中。

当前最明确、可独立干预的线索是地址翻译：p18 瓶颈步页表遍历请求配对多
**75.208%**，两沿合计多 **60.474%**。下一项消融固定机器码和虚拟地址，
只改变代码页的映射方式，另设匿名 4 KB 页对照，分离匿名复制/物理放置与
2 MB 大页本身的效果。不会仅凭请求数乘一个假定延迟来宣称 walltime 收益。

[六组完整数据与最终身份审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cumulative_frontend_20261009/summary.json)、
[新增探针的模型对象不变性核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cumulative_frontend_20261009/extended/build.json)、
[复现驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cumulative_frontend_20261009.py)。

#### 代码页消融：相同机器码、相同虚拟地址

完成进程内代码大页原型。通过 ELF 程序头枚举主程序的只读可执行段，对完整
2 MB 对齐区间作处理；**不按 part、模块、信号、profile 或编译后反馈筛选**。
本例覆盖 `0x555555600000–0x55555b000000`，共 **90 MiB**，边缘不足一页的
部分保持原映射。所有模式都使用同一个 §7.85 ELF；不重新编译模型或移动函数，
64 B 入口对齐自然保持。

三种模式都加载相同的实验辅助库，只有代码页处理不同：

| 模式 | 代码承载方式 | 用途 |
| --- | --- | --- |
| file | 原有文件映射 | 控制辅助库加载本身的影响 |
| small | 匿名 4 KB 页，明确禁用大页 | 控制复制、匿名物理放置和初始化的影响 |
| thp | 匿名 2 MB 透明大页 | 检验代码地址翻译成本 |

匿名模式先复制完整区间并逐字节比较，再设成只读可执行，通过 `mremap`
替换到原地址。操作在 worker 创建前进行，辅助库自身位于被替换区间之外。
每次运行都读取 `/proc/self/smaps`：file/small 的匿名大页为 0，thp 为完整
94,371,840 B；成功标志不只依赖 `madvise` 返回值。使用 Linux 的
`MADV_HUGEPAGE`/`MADV_COLLAPSE`，未修改系统 THP 设置；机制参见
[内核透明大页说明](https://docs.kernel.org/admin-guide/mm/transhuge.html)。
本轮 thp 普通三方运行的准备耗时平均 **37.657 ms**，small 为 **69.431 ms**，
它们全部包含在最终进程 walltime 中。

#### 相同 p18 步骤：翻译请求消失，分支形态不变

file/thp 的 tlb、latency、core 三组各四对 C100000 AB/BA，继续使用冻结的
719 个 p18 瓶颈步骤。下表绝对值为运行均值的算术平均，变化为逐对百分比的
中位数。各行保留所属事件组，不能跨组把周期差相加。

| 事件组 / p18 指标 | file | thp | 配对变化中位 |
| --- | ---: | ---: | ---: |
| tlb：eval / µs | 47.1893 | 44.7983 | **−4.979%** |
| tlb：CPU 周期 | 168,836.70 | 160,644.71 | −4.839% |
| tlb：L1 miss、L2 hit | 526.288 | 0.0066 | −99.999% |
| tlb：页表遍历请求 | **370.050** | **2.663** | **−99.281%** |
| latency：完全断供周期 | 76,998.84 | 69,008.30 | −10.136% |
| latency：eval / µs | 46.9793 | 44.7699 | −4.620% |
| core：退休分支 | 10,760.345 | 10,760.339 | 约 0% |
| core：误预测 | 1,129.011 | 1,129.976 | +0.075% |
| core：eval / µs | 47.2003 | 45.2675 | −4.438% |

三组的 p18 退休指令都保持约 260,424/步，相对差不足 0.001%。tlb 组两沿
合计 eval 为 84.102→79.858 µs，配对 −4.958%。同组 p10/p26/p29 的固定
瓶颈步 eval 配对分别 −3.445%/−1.959%/−4.955%，页表遍历也均减少约 99%。
所有 PMU 区间无复用，Difftest 与功能签名通过。

这给出了比“代码大、IPC 低”更直接的干预证据：**代码地址翻译贡献了可回收
的开销**，本次改善不依赖减少执行指令、改变分支路径或降低误预测次数。
它仍不是全部根因：p18 完全断供比例只从 45.73% 降至 **42.96%**，远未消失。
带宽不足比例从 23.36% 升至 24.52%，对应的空槽绝对数却基本相同
（约 236,028→236,354）；主要是总周期分母缩短，不能直接判成带宽退化。

#### 最终 walltime：三方重复与原始程序直接对照

普通二进制完成三个窗口，每窗口四组正反序三方对照；全程 node030 CPU96–127、
C100000、N=K=32、all-spin、Host105、NUMA1、ASLR off。下表每种模式均值
基于该窗口四次运行，配对变化按同一组 `100 × (thp / file - 1)` 取中位数。

| 窗口 | file walltime / s | small / s | thp / s | thp 相对 file 配对变化 |
| --- | ---: | ---: | ---: | ---: |
| A | 11.7250 | 11.2675 | 11.0025 | −2.003% |
| B | 11.1850 | 11.2875 | 11.0350 | −1.163% |
| C | 11.1175 | 11.2025 | 10.9700 | −1.482% |

窗口 A 的第二次 file 运行是 **13.29 s**，与本任务自己的前一轮结果身份审计
重叠；审计完成时间位于该运行区间内。该成功样本**完整保留、未修正或剔除**，
也不把它的异常偏慢认作大页收益。之后停止测量期间在这些核上运行审计，B/C
均为独立复测。三窗口合计 file→thp **12/12 更快，配对中位 −1.525%**；
small→thp 也 **12/12 更快，配对中位 −2.266%**。包含上述偏慢样本的
file/thp 总均值为 11.3425/11.0025 s，均值比约 −2.998%，不能与配对中位
混用，更不能把它当成无干扰的稳定加速率。

最后另做四对 AB/BA，A 是**完全不加载辅助库的原始累计 GrhSIM 程序**，
B 加载代码大页原型；不是以装载实验库后的 file 模式代替真实原始程序。
产物 `native_ab` 中的 `native` 仅指这个“未加载辅助库”的模式，仍然是
N=K=32 的 RepCut GrhSIM。

| 原始累计程序 → 代码大页，四对 | A 均值 | B 均值 | 配对变化中位 |
| --- | ---: | ---: | ---: |
| 最终 walltime / s | **11.2175** | **10.9200** | **−2.620%，4/4 更快** |
| Host / s | 11.1825 | 10.84725 | −2.945% |
| 全局 eval / µs per step | 43.14625 | 41.32650 | −4.437% |
| 全局 update / µs per step | 9.38750 | 9.51175 | +0.423% |
| 最大分区全步平均 eval / µs | 28.42050 | 27.05525 | −4.876% |

四对 walltime 变化范围 −4.085% 至 −1.257%，均值比为 −2.652%。结合三个
三方窗口，结论是当前 workload 下存在约 **1%–3% 量级的可重复最终时间收益**，
不把单窗口最有利结果外推成固定提升。代码大页准备的成本已计入这些 walltime。
update 没有稳定改善；较明显的变化在 eval，符合本次代码页干预的目标。

保留这一通用 Linux/x86 运行候选及复现工具；目前仍是进程内实验实现，没有
晋升正式运行默认。它不依赖修改 RTL 或指定某个分区，也不代表 GrhSIM 独占
的大页收益。本轮未用它重新计算 G/V 加速比。后续可以先将其整理成可选运行
支持，同时在固定代码页条件下继续分析剩余的取码/控制流中断；仍不能将原先
全部前端断供归为 TLB，也不能将无效推测槽比例当作分支恢复的完整代价。

代码页实验共 **68 次完整 Difftest、17 次 C100**；与本节前半的六组 G/V
归因合计 **116 次 C100000、29 次 smoke**，全部通过。普通与诊断数据分账，
最终再次核验全部输入身份及原始累计 ELF/archive。

[代码页原型](../../build/repcut_grhsim_20260925/active_dispatch_20261003/codepage_probe_20261009.cpp)、
[三方及直接 AB/BA 驱动](../../build/repcut_grhsim_20260925/active_dispatch_20261003/codepage_probe_20261009.py)、
[全部普通窗口、诊断、准备耗时与最终审计](../../build/repcut_grhsim_20260925/active_dispatch_20261003/codepage_probe_20261009/summary.json)、
[原始程序直接对照](../../build/repcut_grhsim_20260925/active_dispatch_20261003/codepage_probe_20261009/native_ab/manifest.json)。

### 7.88 代码页大页默认接入与缓存对照（2026-10-09）

根据 §7.87 的重复 walltime、TLB 和功能结果，代码页大页不再只停留在
`LD_PRELOAD` 原型。生成器现在仅在 GrhSIM 的 RepCut wrapper 中插入一次性启动
阶段处理：构造第一个 `WolviRepCutGrhSimSim` 对象时，在创建 phase workers 之前，
通过 `dl_iterate_phdr` 找到主程序完整的 2 MiB 对齐 RX 段，复制到匿名内存，执行
`MADV_HUGEPAGE`/`MADV_COLLAPSE`，设为 RX 后用 `mremap(MREMAP_FIXED)` 放回原
虚拟地址。没有按分区、模块、信号或 workload 选择，也没有移动任何函数；Verilator
生成路径不包含这段代码。

默认行为是尝试启用 THP。若平台没有完整对齐段或内核/内存不允许 collapse，运行时
打印 `fallback=native` 并继续使用原始映射，不改变仿真语义；设置
`WOLVI_GRHSIM_CODE_HUGEPAGE=0`、`off`、`false`、`disable` 或 `native` 可显式关闭。
成功和回退都会输出一条 `[WOLVI][codepage]` 记录，处理用 `std::once_flag` 保证同一
进程只执行一次。因此这项能力是 GrhSIM 默认优化，同时保留可诊断、可回退开关。

#### 生成器与真实代码路径验证

使用当前 Wolvrix 源码重新编译 `wolvrix-lib`，随后运行
`emit-grhsim-repcut-package` 的完整 CTest；生成、编译、wrapper/facade 行为检查均
通过（1/1，44.84 s）。测试 fixture 的普通小 ELF 没有完整 2 MiB RX 段，正确打印
`fallback=native`；再给同一个已生成 GrhSIM package 链接一个 6 MiB 的 `.text` 填充
段，运行 wrapper 得到 `enabled=thp bytes=6291456`，Difftest harness 仍输出
`grhsim-repcut-harness-ok`。同一二进制设置关闭变量后输出
`disabled by WOLVI_GRHSIM_CODE_HUGEPAGE`，标准输出逐字节相同且 harness 仍通过。
这同时验证了默认启用、显式关闭、没有完整段时回退以及代码地址不变四条路径。

#### 缓存事件对照

在 node030 CPU96–127 的累计 PMU binary 上又完成两对有效的 file/thp cache
AB/BA（C100000）；由于节点随后出现明显外部负载，后续一对不纳入统计。固定 p18
瓶颈集合中，代码大页反而使 I-cache miss 增加约 **2.23%**，op-cache miss 增加约
**0.81%**，而两对全局 step walltime 仍分别下降 **2.22%/0.65%**。这与 §7.87
中 ITLB L2 hit 近乎清零、页表遍历减少约 99% 的结果相互印证：收益来自地址翻译
覆盖范围变大，而不是 I-cache/op-cache miss 变少。缓存计数只用于归因，不与普通
walltime 样本混合。

因此，代码页大页现已作为 GrhSIM RepCut 生成运行时的默认选项落入主线；原有
Verilator 支持、GrhSIM 的线程/ all-spin 行为和模型代码均保持不变。后续优化重点
转回剩余完全断供中的取码布局与控制流恢复，不能把大页收益外推为消除全部前端
瓶颈。

[默认代码页实现](../../wolvrix/lib/emit/verilator_repcut_package.cpp)、
[生成器 CTest 输出](../../wolvrix/build-direct-hot-principled-landing-20260801/artifacts/emit/grhsim_repcut_package/)、
[代码页 cache 对照原始数据](../../build/repcut_grhsim_20260925/active_dispatch_20261003/codepage_probe_20261009/cache/)。

### 7.89 通用 hot/cold 文本分裂消融（2026-10-09）

代码页大页默认接入后，先检查一个不依赖分区、信号或模块名单的编译器级取码布局方案：
对累计版本 **part 18 的全部 257 个 schedule 文件**统一加入 Clang23 的
`-mllvm -hot-cold-split=true -mllvm -enable-cold-section=true`，其余归档成员、
编译器、O3、64 B 对齐和 wrapper 均保持不变。该试验只用于识别机制，没有进入默认线。

结果显示当前生成代码的 `unlikely(activeWordFlags != 0)` 外层守卫把真正执行的大主体
误标为 cold。以最大提交函数为例，`eval_commit_batch_256` 的热入口只有 **21 B**，
约 **270 KiB** 主体被放入对象的 `__llvm_cold` 段；活跃时每次都要跳到该段。这个
形态与当前“活跃路径供指不足”的症状相反，不能用“把所有 cold 块移走”来解决。

在 node030 CPU96--127、NUMA1、ASLR 关闭、N=K=32、all-spin、Clang23/O3、
C=100000 下做两对 AB/BA，4/4 次功能签名通过，但候选全部变慢：

| 指标 | 基线中位数 | hot/cold 分裂中位数 | 配对变化中位数 |
| --- | ---: | ---: | ---: |
| walltime / s | 13.145 | 13.690 | **+4.149%** |
| Host / s | 13.106 | 13.653 | **+4.176%** |
| 全局 eval / µs | 50.363 | 53.046 | **+5.330%** |
| 最大分区 eval / µs | 32.982 | 37.144 | **+12.628%** |
| 全局 update / µs | 11.193 | 11.118 | −0.670% |

因此不接入该编译器选项，也不把它作为默认或实验基线。当前文本布局的下一步应
保持高频 batch 的主体在热文本段，只对有独立依赖证明且实际低频的内层分支做局部
布局；不能由源码中的单个 `unlikely` 标签直接推出整个函数是 cold。原始消融的
构建、对象和普通对照保存在
[`text_layout_probe_20261009`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/text_layout_probe_20261009/)。

#### 外层活动提示的分层复核（2026-10-09）

继续用完整累计 `s6_commit_complete` 冻结源码作基线，仅把外层
`if (unlikely(activeWordFlags != UINT8_C(0)))` 改成不带概率提示的普通判断。
内部各 bit 的 `unlikely`、状态变化判断、执行顺序和激活语义全部保留。先统一
覆盖全部 32 分区的 6994 个 schedule 文件、7437 处外层判断，再补一个按调度
阶段选择的对照：仅覆盖所有分区的 135 个 event-driven commit 文件、573 处
外层判断。两条规则均不使用分区、模块、信号名单，也不以 profile 或机器码大小
选择优化对象。两版分别改变 6945/87 个 archive member；第二版的 compute
对象完全沿用基线。

配置仍为 node030 CPU96–127、NUMA1、N=K=32、all-spin、Clang23/O3、ASLR off、
64 B compute 对齐、C100000。冻结 package 早于大页 wrapper 接入，因此双方均
用 §7.87 同一个进程内辅助库启用 THP，逐次核实实际大页覆盖；walltime 包含
启动映射时间。普通运行分两个窗口，各四对 AB/BA，成功样本全部保留。下表的
百分比是 `median_i(100 × (candidate_i / baseline_i − 1))`，不是表内均值之比；
两行来自各自交错窗口，不直接比较两行的绝对时间。

| 规则 | 基线 / 候选 walltime 均值 / s | walltime 配对中位变化 | 两窗口各自的变化 | 更快对数 | 全局 eval 变化 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 所有外层判断取消提示 | 13.06625 / 13.06875 | **+0.116%** | −0.039% / +0.422% | 3/8 | −0.330% |
| 仅 commit 外层取消提示 | 13.29250 / 13.26625 | **−0.115%** | −0.751% / +0.335% | 4/8 | −0.189% |

这也补充了“活跃主体不应被整体移入 cold”结论的适用范围：它并不意味着统一
取消外层提示一定能加速。以 p10/c175 为诊断例，取消提示使对象 `.text` 从
415398 B 降到 331850 B（−20.11%），但限定版在固定 p10 瓶颈步骤的实际指令数
只减少约 0.18%。p18/c256 则从“空路径就地返回、活跃路径跳入主体”变成“活跃
路径顺序执行、空路径跳到较远返回点”；栈上显式预留也由 56 B 增为 72 B。这些都是编译
布局和生成代码的变化，不能直接折算为运行时收益。

另复用此前独立冻结的 p10/p18/p26/p29 步骤，分开测 core 和 pipeline 事件。
完整外层版各四对，commit 限定版各两对，全部区间 `enabled == running`，没有
计数器复用。限定版 p26 的固定步骤 cycles 在两窗口分别下降 2.10%/2.15%，
但 p18 为 +2.42%/−1.98%，p29 为 +6.44%/−1.72%；局部周期方向并不一致，
也没有形成一致的误预测减少。探针版 walltime 不计入上表，槽位事件不当作
walltime 占比。两种候选都没有证实稳定的端到端收益，**不接入正式 emitter 或
默认配置**；本轮停止继续扩展提示/布局变体，保留已有大页与 64 B 对齐。

两版共完成 **56 次 C100000 Difftest、16 次 C100**，全部功能签名通过；分别核实
7552 个源码/头文件、归档成员变更范围、输入及 ELF 身份和 6859 个 compute
函数的 64 B 对齐。复现与汇总集中在
[`outer_activity_hint_20261009.py`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/outer_activity_hint_20261009.py)、
[`完整外层版汇总`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/outer_activity_hint_20261009/summary.json)、
[`commit 限定版汇总`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/commit_outer_activity_hint_20261009/summary.json)。

### 7.90 p26 残余 compute 归因与纯宽位运算融合（2026-10-09）

结束提示/布局消融后，回到实际计算。基线仍为完整累计
`s6_commit_complete`，保留代码 THP 和 64 B compute 对齐；没有叠加 §7.89
的两个外层提示候选。沿用 §7.85 独立发现的 **357 个 p26 瓶颈步骤**及其
相邻半周期，标签全部位于 clock=0。本轮不根据新测量重新挑选步骤，也不把
“固定历史瓶颈集合”当作重新发现的全局瓶颈分布。运行固定 node030 CPU96–127、
NUMA1、N=K=32、all-spin、Clang23/O3、ASLR off、C100000；成功样本全部保留。

#### 与 Verilator 的固定步骤对照

cycles 和 branch-misses 分开采样，各四对 Verilator/O3 与 GrhSIM AB/BA。
仅在指定 worker 的选定 eval 区间启用事件，模型对象保持原样；全部有效数据
无丢失、无节流、无计数器复用。GrhSIM 用与 §7.87 相同的进程内辅助库为冻结
ELF 启用 THP，并逐次核验覆盖；Verilator 使用原有映射。

| p26 固定瓶颈步骤指标 | Verilator | GrhSIM | 口径 |
| --- | ---: | ---: | --- |
| CPU cycles / eval | 98,595 | 176,219 | 周期采样轮配套计数；配对中位差 +79.130% |
| branch misses / eval | 25.63 | 707.10 | 独立误预测采样轮配套计数 |
| cycles IP 样本 | 129 | 244 | 不是普通 walltime 或精确耗时占比 |

GrhSIM 的 244 个周期样本中，**217 个在 compute（88.934%）**，21 个在
eval 输入处理/调度（8.607%），其余 6 个在其他位置；没有 commit 样本。
217 个 compute 样本分布到 **130 个函数**，最多的单函数只有 5 个样本。
127 个误预测样本中，compute 为 84 个、eval 为 39 个。eval 的映射仍主要
指向宽输入 delta 与掩码检查；compute 的落点包括布尔生成/新旧值比较、
活动通知、选择结果与宽数组赋值。样本有 skid，不能把落在一条 `cmov` 或
load 上的误预测样本直接说成该指令产生误预测。

另做四次独立活跃 batch 计时，只替换 p26 dispatcher 和框架探针对象，所有
compute/commit 机器码不变，243 个 batch 的调用/活跃计数逐次一致：

| batch | 每固定 eval 的活跃耗时 / µs | 主要代码形态 |
| --- | ---: | --- |
| b22 | 1.0342 | 已按需读取的 packed-array 消费及后续逻辑 |
| b222 | 0.9582 | 宽掩码选择链、结果物化及其他组合逻辑 |
| b209 | 0.9430 | 包含性能统计的宽数值运算与输出构造 |
| b71 | 0.7315 | 布尔结果、选择与变化通知 |
| b208 | 0.7017 | 拼接、宽数值运算、宽结果赋值与变化检测 |

活跃 batch 探针合计 58.5529 µs，最大 batch 占 **1.766%**、前十合计
**12.933%**。该合计包含每个 batch 的计时扰动，不与普通 eval 或之前阶段
探针的绝对时间相减。它与 IP 分布共同支持：此前整表预先填充等热点已被
处理，当前剩余成本较分散，不能再把某一个大函数当作 p26 的主要全部瓶颈。
例如 b209 所用 65–128 bit 加法 helper 已经使用 `unsigned __int128`，再次
提出简单的 native-128 替换并不是新的优化。

[`IP 采样驱动与源码映射`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cumulative_p26_path_20261009/)、
[`固定步骤 batch 汇总`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cumulative_p26_batches_20261009/summary.json)。

#### 通用候选：按字融合纯位运算区域

对照相同 `_val_10544009` 的 Verilator 生成代码，可见其按 32 bit 字组织
嵌套掩码表达式；GrhSIM 对应区域则由多级完整 1024 bit 数组 helper 组成。
这提示可以尝试改变纯计算区域的组织方式，但源码差异本身不证明 Verilator
在这一区域快多少。所检查的 Verilator 片段位于
[`part 26 生成源文件`](../../build/repcut_grhsim_20260925/clang23_threeway/verilator_o3/package/build/verilated/part_26/VWolviRepCutUnit_part_26___024root__8.cpp)。

原型统一扫描全部分区：选择连续、同位宽、至少 4 个 64 bit 字且至少 8 个
纯 AND/OR/XOR/NOT 操作的局部数组区域，按原依赖顺序逐字计算。只接受简单
数组读取与字面量数组；调用未知函数、算术进位、移位、混合位宽、状态写回、
事件或其他语句都截断区域。规则不读取 profile、机器码大小、分区或信号名单。
自然覆盖 **24 个分区、102 个文件、288 个区域、6768 个位运算**；其中 p26
只命中 b37/b221/b222，不能将其他 batch 的间接变化解释为直接改写收益。

初版的完整功能对照通过，但反汇编发现它在每次循环中构造常量数组再按动态
下标取字，Clang 保留了重复清零与栈读取。修正版直接使用均匀字面量；非均匀
字面量数组在循环外构造。只有区域外仍被使用的结果保留完整数组，内部结果
只保留当前字；7118 个数组结果中，保守检出 1462 个区域外使用者。每个保留
结果的所有字均在任何数组读取前写好，因此不额外初始化输出数组。变化检测、
活动传播、执行条件和区域外存储顺序保持原样。

修正版已完成 **72,000 组 Clang23/O3 + ASan/UBSan 差分检查**，覆盖
3/4/5/7/8/11/16/17/64 字、全部四类位运算、非均匀常量、内部共享、多输出、
输入别名、全零/全一/最高位/随机数据，以及短组、窄值、未知调用和跨字算术
拒绝。另在完整 C100000 中逐次执行原表达式并比较每个中间字，Difftest 与
全部比较通过。普通候选实际改变 97 个 archive member，其余保持逐字节一致，
6859 个 compute 入口仍为 64 B 对齐。修正版普通性能与固定步骤归因在本节
后续结果中统一记录；校验版耗时不进入性能结论。

[`通用原型驱动`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_bitwise_fusion_20261009.py)、
[`修正版构建`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_bitwise_fusion_compact2_20261009/build.json)、
[`专项语义检查`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_bitwise_fusion_compact2_20261009/semantics/summary.json)。

#### 完整性能结果与归因

修正版普通运行分两个窗口，各四对 AB/BA。下表时间列为各侧运行的算术均值，
变化列为 **`median_i(100 × (candidate_i / baseline_i − 1))`**；不能用两列
均值之比代替配对中位数。全部八对成功样本纳入，没有按快慢剔除。

| 普通 C100000 指标 | 基线均值 | 修正版均值 | 配对变化中位数 | 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| walltime / s | 13.54375 | 13.48125 | **−0.033%** | **4/8** |
| Host / s | 13.446625 | 13.387750 | −0.024% | 4/8 |
| 全局 eval / µs | 51.6020 | 51.3806 | −0.054% | 4/8 |
| 全局 update / µs | 11.5194 | 11.4689 | −0.313% | 7/8 |
| 最大分区全程 eval / µs | 33.4711 | 33.5601 | +0.188% | 2/8 |
| p26 全程 eval / µs | 27.5546 | 27.6445 | **+0.978%** | 3/8 |

两个窗口的 walltime 配对变化分别 **+0.299% / −0.801%**，合并范围
−2.322% 至 +1.558%。均值之比约为 −0.461%，但它不能替代上表的配对
中位数，也不改变四快四慢、两窗口方向相反的事实。update 未被直接改写，
不把其小幅变化认作新增通信优化。当前没有证实稳定的端到端收益。

固定步骤 core PMU 另做四对，仍无复用。p26 的条件 eval 64.7509→61.9378 µs，
配对 −4.985%；cycles 182706→174723，配对 −5.298%。但同时，动态指令
**331708→332185（+0.144%）**、分支 **6251.14→6300.08（+0.783%）**、
branch misses **621.88→630.64（+1.423%）**。该局部探针下降没有出现在
普通全程 p26 均值或普通 walltime 中，不能把它单独报告成候选收益。

为核实直接被改写计算的成本，另做两对 batch AB/BA：双方使用完全相同的
三个探针对象，所有 compute/commit 对象保持对应普通版本原样。全部 243 个
batch 在 357 个步骤上的调用数、活跃数、all-on 数和激活 bit 数完全一致。

| p26 被改写 batch | 基线 / µs | 修正版 / µs | 配对变化 |
| --- | ---: | ---: | ---: |
| b37 | 0.56878 | 0.62987 | **+10.832%** |
| b221 | 0.56699 | 0.57259 | +0.987% |
| b222 | 0.95402 | 0.95540 | +0.133% |

b221/b222 没有显示稳定局部加速，b37 两对均变慢。这些结果也不支持把 PMU
版整个 p26 的约 5% 下降归因于被融合的区域；重链接后的代码地址、其他 batch
执行状态与探针上下文的间接影响尚未独立分离，不据此选择有利的统计口径。

静态机器码同样说明“源码按字组织”并不自动减少实际工作。b221 的静态指令
4905→3762，但引入循环后不能把静态条数差当作动态执行条数差；b222 为
8574→8093，仍有大量栈引用；b37 的指令 3392→3398、栈地址引用
286→420，与局部退化方向一致。修正版改变对象的可执行节总计
1382845→1351246 B（−2.285%），这是相关对象的统计，不是全 ELF 缩小比例。
102 个源文件的增量编译 walltime 为 3.192 s；包含全源码扫描、归档审计和
harness 链接的构建总耗时为 39.473 s，不是完整 RTL 生成/clean build 成本。

修正版累计 **30 次完整 C100000 Difftest、10 次 C100** 全部通过，其中普通
16/4、core 8/2、batch 4/2、逐次 oracle 2/2；原始热点采样和首版试验不混入
这个计数。最终源码、archive、ELF、输入身份和 64 B 对齐审计均通过。候选
archive SHA-256 为 `c7362f7d139755929eefb042eede06c81c8f3554e9a786a2c9a79e6bad593d50`，
普通 ELF 为 `b5306e4765fd9bad1ff3689b8ffce119c8d0eae6ad8450e5c0ad16e9ac21d0d5`。

结论：**纯宽位运算的通用逐字融合本轮不保留为有效性能基线，不迁入正式
emitter 或默认配置**。保留 `s6_commit_complete + THP + 64 B`，Verilator
生成和执行路径不变。下一项更有价值的检查是记录高频活跃区域的输入/输出
实际变化比例，再评估已有 producer-dirty 机制能否精确跳过稳定子图的重复
计算；这需要依赖及可见性证明，不能只根据本次“经常不变”就省略计算。

[`修正版完整汇总`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_bitwise_fusion_compact2_20261009/summary.json)、
[`固定步骤 PMU`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_bitwise_fusion_compact2_20261009/core/summary.json)、
[`直接 batch 对照`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_bitwise_fusion_compact2_20261009/batch_runs/summary.json)、
[`源码和机器码审计`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_bitwise_fusion_compact2_20261009/audit.json)。

### 7.91 宽位区域的真实变化比例与按掩码按需计算（2026-10-09）

继续使用 `s6_commit_complete + THP + 64 B`，不叠加 §7.90 未证实收益的
融合候选。node030 CPU96–127、NUMA1、N=K=32、all-spin、Clang23/O3、关闭
ASLR、C100000 和 Difftest 保持不变。先检查实际变化，再决定是否增加缓存；
本轮不以机器码或 profile 选择优化对象。

#### 实际变化：结果不变不等于输入不变

统一扫描全部分区中连续、同宽、至少 4 个 64 bit 字、至少 8 个 AND/OR/XOR/NOT
的纯计算区域，覆盖 **24 分区、102 个源文件、288 个区域**。保留原计算，
在每次调用前后记录完整外部输入和所有区域外仍被使用的结果，与该区域上一次
调用比较；第一次调用视为必须计算。另记录所有输入共同保持不变的字位置，
用于区分整段稳定和部分字稳定。所有“输入未变但输出改变”均会触发断言，
不能由输出变化率反推缓存正确性。

两次 C100000（另加一次 C100）全部功能通过，**每个区域的全部计数逐项一致**。
每次完整运行共观察 **6,620,657 次区域调用**；31.889% 的调用输入完全相同，
77.373% 的调用结果相同。按静态 `操作数 × 字数 × 调用数` 加权，整段输入
稳定对应 21.651% 的字运算；这是结构机会量，不是动态指令或 walltime 比例。
快照复制和比较只用于诊断，不能将这个探针的耗时混入普通性能。

继续使用 §7.85 冻结的瓶颈步骤，未因新候选或新测量重选样本。p26 的 357 个
步骤共执行下列区域 1647 次；不同区域属于不同 supernode，调用次数可以不同。

| p26 区域（基线源码行） | 位运算数 | 输入数组数 / 输出数组数 | 调用数 | 输入完全未变 | 结果完全未变 | 所有输入共同未变的字比例 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| b221:1653 | 15 | 15 / 21 | 322 | 70.50% | 70.50% | 95.90% |
| b221:2508 | 43 | 42 / 1 | 322 | **1.55%** | **73.91%** | 2.58% |
| b221:3383 | 61 | 27 / 1 | 323 | **2.17%** | **80.19%** | 4.04% |
| b222:240 | 61 | 27 / 1 | 323 | **3.41%** | **77.71%** | 4.14% |
| b37:2249 | 21 | 17 / 2 | 357 | 16.81% | 17.09% | 21.73% |

p26 全部被观测区域按上述静态字运算加权，冻结瓶颈步骤中整段稳定仅
**9.116%**，精确到字也仅 **12.551%**。最稳定的第一段主要是逐字 NOT 与
常量数组，输出数量还多于输入；后续三段更长的选择计算，其输入几乎每次
都变。故现有 producer-dirty 即便拥有完整依赖，也只能跳过少量调用，
增加全输入快照或持久输出缓存并不是当前 p26 的优先方案。这不否定其他
结构上的缓存：例如 p24 同口径整段稳定为 76.561%，但不能据此推断 p26
或全局临界路径也能得到同样收益。p18 的这类区域在其 719 个冻结瓶颈步骤中
合计仅执行 183 次，也不能把宽位区域的统计推广成整个 p18 的剩余瓶颈。

源码追踪说明较大差异来自**被选择条件屏蔽的输入变化**。例如 p26/b212 把
16 个不同的 Boolean 各复制为一个全零或全一的 64 bit 字，形成 1024 bit
选择掩码；b221/b222 通过多级 `(t & m) | (f & ~m)` 组合候选数据。不是整个
1024 bit 掩码都相同，而是每个字分别表示一个选择条件。候选数据变化会进入
该区域，但当对应掩码未选中它时，最后结果仍可完全不变。纯粹把这些数据
登记为 dirty 依赖，不能消除这种重复计算。

[`变化比例探针与完整逐区域数据`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_region_activity_20261009/summary.json)、
[`探针驱动`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_region_activity_20261009.py)。

#### 通用候选与验证边界

据上述机制改试**当前调用内按掩码按需计算**，不添加跨调用缓存。仅接受
单一外部结果、无重复复杂子树的纯位运算树，且树中至少四个可证明等价的
`(t & m) | (f & ~m)` 节点。每个 64 bit 字独立处理：`m=0` 只计算 `f`，
`m=全一` 只计算 `t`；其他任意部分位掩码仍计算两侧并执行原 AND/OR。
因此**不假设运行时掩码一定是 Boolean 扩展**，也不需要绕过存储别名或
跨 supernode 的可见性检查。未知调用、跨字算术、多个外部结果、共享复杂
子树继续拒绝，选择只由静态纯计算结构决定。

候选先完成 112,000 组 Clang23/O3 + ASan/UBSan 差分检查，覆盖
3/4/5/8/16/17/64 字、3/4/8/16 层选择、全零/全一/混合 Boolean/任意部分位
掩码、输入别名及短树/窄值/多输出拒绝。完整 XiangShan 校验版还会在每次
命中时执行原表达式并比较最终结果。普通 AB/BA、固定步骤 PMU 和直接 batch
对照完成后，在本节追加性能结论；当前不改变正式 emitter 或默认配置。

[`按掩码需求求值原型`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_mask_demand_20261009.py)、
[`专项语义检查`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_mask_demand_20261009/semantics/summary.json)。

#### 完成结果：逐字按需路径退化，维持原基线

结构规则最终自然命中 **p14/p20/p25/p26/p27 五个分区、7 个文件、16 个
区域、224 个选择节点**；每个区域包含 14 个匹配的掩码选择。p26 直接改写
b221:3383 和 b222:240，b37 和其他两段保持原样。七个归档成员以外全部
逐字节相同，7552 个源码/头文件身份核对通过，6859 个 compute 入口保留
64 B 对齐。改变对象的可执行节总量 244670→241397 B（−1.338%）；这是
相关对象大小，不是全 ELF 大小。增量编译 1.231 s，含扫描、归档审计和
harness 链接的构建 36.701 s，均不是完整 clean build 的成本。

普通 C100000 分两个窗口、各四对 AB/BA。下表时间列为各侧算术均值，变化
仍为 `median_i(100 × (candidate_i / baseline_i − 1))`，全部通过样本纳入。

| 普通运行指标 | 基线均值 | 按需候选均值 | 配对变化中位数 | 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| walltime / s | 13.22125 | 13.28250 | **+0.501%** | **2/8** |
| Host / s | 13.125625 | 13.191375 | +0.567% | 2/8 |
| 全局 eval / µs | 50.2564 | 50.5619 | +0.674% | 2/8 |
| 全局 update / µs | 11.3569 | 11.3610 | −0.085% | 4/8 |
| 最大分区全程 eval / µs | 32.4259 | 32.3955 | −0.028% | 4/8 |
| p26 全程 eval / µs | 27.2039 | 27.4346 | **+1.596%** | 2/8 |

两个窗口 walltime 配对变化分别 +0.559%/+0.501%；八对中两快、五慢、一对
在 walltime 的 0.01 s 输出精度下相等，范围 −1.574% 至 +2.613%。直接命中
的其他分区 p14/p20/p25/p27 的全程 eval 配对变化分别
+4.730%/+2.375%/+5.114%/+3.631%，不支持用全局最大分区的微小负变化
解释成收益。

固定 p26 瓶颈步骤另做四对 core PMU，无计数器复用。动态指令
331707.95→338478.67（配对 **+2.041%**），分支
6251.14→7301.13（**+16.797%**），branch misses
622.72→635.71（+2.043%），cycles 176060→180368（+1.791%），条件
eval 61.9458→63.0405 µs（+1.347%）。p10/p18 未改写，动态指令与分支
基本精确相同，说明新增指令集中于候选影响的路径。

两对直接 batch 对照复用同一组探针对象，所有 243 个 batch 的调用/活跃/
all-on/激活 bit 计数相同。直接命中的 b221 从 0.61363→1.12256 µs，配对
**+83.045%**；b222 从 0.97048→1.48128 µs，**+52.627%**；两批在两对中
均变慢。未改写的 b37 为 +0.642%，两对方向相反。此处是带局部计时开销
的 batch 结果，不与普通全程 eval 相减，但能确认直接计算区域的退化方向。

#### 退化原因：几乎没有提前退出，破坏了原有向量处理

为确认实际源级路径，另建独立计数版，记录每个选择节点被访问的次数以及
掩码是零、全一或部分位掩码。它只用于路径计数，不参与普通性能。再次完成
两次 C100000、一次 C100，计数逐项一致；全部 16 个区域在各冻结步骤和全程
的调用数都与前面的原始计算探针一致。

| p26 固定瓶颈步骤 | 全部节点逐字求值时的数量 | 按需访问数量 | 零掩码 / 全一 / 部分位 | 省略节点字比例 |
| --- | ---: | ---: | ---: | ---: |
| b221:3383 | 72352 | 71740 | 71667 / 73 / 0 | **0.846%** |
| b222:240 | 72352 | 71647 | 71562 / 85 / 0 | **0.974%** |

分母为 `323 次区域调用 × 16 个字 × 14 个选择节点`。合计实际访问中
**99.8898% 的掩码字为零**，只省略 **0.9101%** 的节点字；全程合并口径
也只有 0.5699% 被省略。这些是 C++ 源级需求求值计数，不是机器指令数；
带副作用的计数探针会影响编译器的投机求值，故机器成本仍以上面的独立 PMU
和普通运行判断。

原因是这些链通常沿“条件未选中”的路径继续访问更早的选择节点，很少遇到
可直接返回数据的全一掩码。结果虽然长期稳定，逐级询问选择条件却仍几乎
遍历完整条链。原代码的数组 AND/OR/NOT 能以 SIMD（单条指令处理多个字）
执行；加入逐字控制流后，相关 batch 的静态向量逻辑指令数 b221
695→303、b222 633→310，而动态总指令和分支却增加。静态向量指令减少
本身不是收益证据，与局部时间、动态指令一起看，支持“向量化工作被更昂贵
的逐字路径替代”的归因。

候选的功能验证共 **30 次 C100000、10 次 C100**：普通 16/4、core 8/2、
batch 4/2、完整原表达式 oracle 2/2。加上两组路径/变化探针，本节共
**34 次 C100000、12 次 C100**，全部通过。112,000 组专项差分中，72,000
组实际改写，40,000 组覆盖短树/窄值拒绝；另检查八种交换操作数顺序，以及
共享复杂子树、未知调用边界、跨字算术边界的拒绝。候选普通 archive
SHA-256 为 `c91db21436ae2439fc4ac5b0fc5abb48a769d4bed4922e5c1867e031ae94c043`，
ELF 为 `b2b8b1ff1b5b9cda24999dbb5f9e906015a85670617a624a492b567cd195fa2c`。

**本轮不保留逐字按需候选为有效性能基线，不迁入正式 emitter 或默认配置**；
继续使用 `s6_commit_complete + THP + 64 B`。已明确排除在这些区域直接增加
全输入 dirty 缓存，以及用逐字选择分支替代向量化位运算这两条当前做法。
后续若继续这条结构方向，值得验证的是一次可向量化的“整组掩码全零”检查，
在证明全部选择都不生效时直接求默认结果，而非逐字逐层检查；这只是由
本轮零掩码分布导出的下一项候选，**尚未实现或测得收益**。它也应采用全分区
通用结构匹配及完整非零回退，不按本次 profile 选定某个分区。

[`普通与 PMU 完整汇总`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_mask_demand_20261009/summary.json)、
[`直接 batch 对照`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_mask_demand_20261009/batch_runs/summary.json)、
[`实际需求求值路径计数`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_mask_demand_counts_20261009/summary.json)、
[`变化探针源码审计`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_region_activity_20261009/audit.json)、
[`候选源码和机器码审计`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_mask_demand_20261009/audit.json)。

#### 补充归因：排除 lambda 未内联造成的实现开销

继续核查完整机器码后发现，上一小节的候选还有实现质量因素，不能把其退化
全部归因于选择策略：Clang 将部分 lambda 保留为独立函数，共新增 **112 个
helper**。p26/b221 和 b222 各包含一个主函数与七个 helper；合并后静态
调用点各为 18 个。每个字的循环中还会构造捕获对象并沿多层 helper 访问
指针。只检查主 batch 函数大小会漏掉这些代码，前面的静态主函数统计不能
替代含 helper 的完整机器码统计。

因此补做内联修正版：对本规则生成的局部 lambda 明确 `always_inline`，
同时把每个子树在源代码中合并为一个调用点：非零掩码时求 `t`，非全一时求
`f`，最后保持 `(t & m) | (f & ~m)`。这样避免早返回与部分位回退重复出现
同一子树，并保持零/全一/部分位情况下的按需语义。结构资格和 16 个目标区域
完全相同，仍不使用 profile 或分区名单。

机器码已确认修正版**没有新增 helper 函数**，p26 两个相关 batch 的调用
指令均为零，排除了上述调用与捕获对象开销。另一次 112,000 组 sanitizer
差分通过；其普通、PMU、直接 batch 对照按相同协议另跑，结果继续追加于此。
首版的路径计数说明源级树几乎走到底，但不能预先替代修正版的实际性能结果。

[`完整 helper 与主函数审计`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_mask_demand_inline_20261009/helper_audit.json)。

内联修正版已完成相同的两窗口、八对普通 AB/BA。各列仍采用前面的算术
均值和配对变化中位数定义，未排除任何通过的运行。

| 内联修正版普通指标 | 基线均值 | 修正版均值 | 配对变化中位数 | 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| walltime / s | 13.54000 | 13.52000 | **−0.297%** | **4/8** |
| Host / s | 13.449125 | 13.431000 | −0.287% | 4/8 |
| 全局 eval / µs | 51.7435 | 51.7643 | −0.115% | 4/8 |
| 全局 update / µs | 11.4071 | 11.3521 | −0.534% | 5/8 |
| 最大分区全程 eval / µs | 33.2050 | 33.0815 | −0.538% | 5/8 |
| p26 全程 eval / µs | 28.1054 | 27.7140 | −1.616% | 5/8 |

两个窗口 walltime 分别 **−0.297% / +0.643%**，方向相反，八对范围
−2.937% 至 +2.539%。update 没有直接改写；p26 全程均值的下降也与下面
直接计算及固定瓶颈步骤的变化方向不同，尚不能归因于候选计算本身。
p14/p25/p27 的全程 eval 配对变化仍为 +1.183%/+0.504%/+1.738%，p20
为 −0.184%。这组结果不支持稳定端到端收益。

固定 p26 瓶颈步骤四对 PMU 中，动态指令 331707.95→333932.74，配对
**+0.671%**；分支 6251.13→6725.22，**+7.584%**；branch misses
621.81→624.23（+0.499%），cycles 配对 +0.495%，eval 配对 +0.688%。
额外指令和分支比首版明显收敛，但仍未低于基线。此处 cycles/eval 的算术
均值受首对较慢的 baseline 影响，其方向与配对中位数不同；继续使用预先
约定的配对口径，不选择更有利的均值之比。

直接 batch 的两对结果如下；与首版比较时，应看各自同期 baseline 的配对
变化，不能跨窗口直接相减绝对时间来声称内联收益。

| p26 batch | 同期基线 / µs | 内联修正版 / µs | 配对变化 |
| --- | ---: | ---: | ---: |
| b221 | 0.62878 | 0.72251 | **+14.922%** |
| b222 | 1.02412 | 1.16012 | **+13.286%** |
| b37（未改写） | 0.57048 | 0.55790 | −2.038%，两对方向相反 |

b221/b222 在两对中仍全部变慢。原型中的调用开销确实是需要修正的因素，
但排除它后，逐字判断、标量控制流和额外栈引用仍未胜过原来的向量化位运算。
完整主函数及 helper 审计中，修正版两个 batch 都只有一个函数和零调用点；
主函数静态条件跳转 b221 为 32→71、b222 为 26→50，栈地址引用
716→881、2450→2524。结合动态指令、直接耗时和原有的几乎全零掩码分布，
可以把“不保留”的结论收窄到**已修正内联问题的当前逐字需求求值方案**，
而不是笼统排除一切按需计算。

修正版另完成 **30 次 C100000、10 次 C100**，全部功能通过。本节两种候选
及两组诊断合计 **64 次 C100000、22 次 C100**，专项差分合计 224,000 组。
修正版改变对象的可执行节为 244670→209538 B（−14.359%），增量编译
1.251 s、完整本次构建 43.330 s；代码缩小同样不能替代性能结果。其 archive
SHA-256 为 `35a603bc2a250034d9f1456c935deed3b67cda3406b08762b694ba195ba38189`，
普通 ELF 为 `3581b797d697f85637e95cc84901439e008bf3cec9934f63a2499bcb43271939`。

最终保留决策不变：**首版和内联修正版都不迁入默认，性能基线仍为
`s6_commit_complete + THP + 64 B`**。下一步若继续研究这些链，应测试整组
零掩码检查，保留原向量化非零路径；不再以单纯增加逐字条件分支作为下一轮
候选。本节结束时没有遗留正在运行的基准测试。

[`内联修正版完整结果`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_mask_demand_inline_20261009/summary.json)、
[`内联修正版 batch 结果`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_mask_demand_inline_20261009/batch_runs/summary.json)。

### 7.92 整组零掩码快速路径（2026-10-10）

承接 §7.91，新的候选先对一个纯选择区域涉及的全部掩码、全部字做按位 OR
归约。归约结果为零，才能证明该区域的所有选择条件都不生效，此时仅计算
默认表达式；任何一位非零，则执行原来的全部数组位运算语句，语句顺序和
任意部分位掩码的语义保持不变。检查与原非零路径都可由编译器向量化，不再
给每个字的每一级选择增加控制流。没有跨调用缓存或新增仿真状态。

适用资格仍由生成代码的通用结构确定：连续、等宽、纯 AND/OR/XOR/NOT
表达式，至少四字、至少四个可辨认的掩码选择节点、单一活跃输出，且没有
共享的非常量子树。新增限制是所有被检查的掩码必须在区域入口已可用；
区域内计算出的掩码不能提前读取，因而拒绝这类结构。没有分区、信号名、
实测命中率或编译后 profile 筛选。全分区扫描自然命中 p14/p20/p25/p26/p27
的七个文件、16 个区域，每个区域含 14 个选择节点，与前一候选范围相同。

采用内联 lambda 封装零路径和原表达式回退，并显式 `always_inline`；
普通候选仅替换这七个模型对象。测试基线继续为未经前两项失败候选修改的
`s6_commit_complete + THP + 64 B`，Clang 23/O3、N=K=32、all-spin，
node030 CPU96–127/NUMA1、关闭 ASLR。普通候选及基线都显式确认代码页
大页映射，计数与局部计时探针单独构建，不使用其 walltime 代替普通运行。

功能校验已完成 112,000 组原有 sanitizer 差分，另补 **16,970** 组整组检查
边界测试：在 4/5/16/17/64 字和 4/16 级选择树中，遍历每一个掩码、每一个
字，只令该位置的 bit 0/31/32/63 非零，并测试相应补码及全零情形。
这组测试同时对照完整原表达式并检查预期输出，防止归约漏字、漏掩码；
ASan/UBSan 均通过。区域内产生掩码的拒绝测试也通过。完整 XiangShan
oracle 在两次 C100000、两次 C100 中逐次比较新旧结果，全部通过。

普通性能安排为两个窗口共八对 C100000 AB/BA；另有四对固定步骤 PMU、
两对直接 batch 计时及两次独立零路径计数。结果和保留决定在本节继续追加。

[`通用原型及评估脚本`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_zero_mask_20261010.py)、
[`整组边界差分`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_zero_mask_20261010/guard_edges/summary.json)、
[`入口掩码资格检查`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_zero_mask_20261010/extra_shapes.json)。

#### 完整性能结果：局部有小幅改善，未形成 walltime 收益

两个普通窗口的八对 AB/BA 已完成，所有通过的运行均保留。下表的均值是
八次运行的算术均值；配对变化是各对 `100 × (candidate / baseline − 1)`
的中位数，**不是两列均值之比**。诊断版、oracle 版和计数版不混入这些数据。

| 普通指标 | 基线均值 | 整组零掩码均值 | 配对变化中位数 | 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| walltime / s | 12.48875 | 12.50000 | **+0.450%** | **3/8** |
| Host / s | 12.403375 | 12.411250 | +0.387% | 3/8 |
| 全局 eval / µs | 47.0695 | 47.2000 | +0.590% | 3/8 |
| 全局 update / µs | 10.95325 | 10.953375 | −0.007% | 4/8 |
| p26 全程 eval / µs | 25.0970 | 25.3365 | +1.198% | 1/8 |

两个窗口 walltime 的配对变化分别为 **+0.746% / +0.042%**，八对范围
−2.780% 至 +1.874%。p14/p20/p25/p27 全程 eval 的配对变化分别为
+2.592%/−0.451%/−0.013%/+1.337%。这些结果不支持把候选视为可靠的
端到端提升，也不以某一对较快样本作保留依据。

固定的 357 个历史 p26 瓶颈步骤，另做四对 PMU，无计数器复用：

| 固定步骤指标 | 基线均值 | 候选均值 | 配对变化中位数 |
| --- | ---: | ---: | ---: |
| 动态指令 / step | 331707.96 | 331225.64 | **−0.145%** |
| 分支 / step | 6251.13 | 6252.94 | +0.029% |
| branch misses / step | 620.01 | 616.86 | −0.650% |
| cycles / step | 173680.12 | 174216.36 | +0.039% |
| 条件 eval / µs | 52.57154 | 53.55254 | +1.742% |

相比上一节逐字分支方案，这次确实没有再大量增加动态分支，指令也略有下降，
但总节省只有约 482 条指令/固定步骤。时间和 cycles 尚未给出一致收益。

两对直接 batch 计时的调用、活跃、all-on 和激活 bit 数在全部 243 批上相同：

| p26 batch | 同期基线 / µs | 候选 / µs | 配对变化 |
| --- | ---: | ---: | ---: |
| b221 | 0.56035 | 0.53754 | **−4.076%**，2/2 更快 |
| b222 | 0.90211 | 0.88970 | **−1.372%**，2/2 更快 |
| b37（未改写） | 0.45800 | 0.52832 | +15.442%，0/2 更快 |

直接改写的两个 batch 有小幅一致改善，但不能据此解释整个 p26 或 walltime。
未改写的 b37 指令序列统计与基线相同，局部耗时仍显著变化，表明执行环境及
整体二进制改变后的间接效应仍在；本轮没有进一步把它唯一归因到某一种缓存
或布局因素，也没有剔除该对照。

#### 高命中率为什么没有带来明显收益

独立计数版完成两次 C100000，16 个区域的计数逐项一致，调用数也与 §7.91
原始变化探针完全一致。全程各区域零路径命中率为 88.967%–89.459%。p26
固定瓶颈步骤下的数据如下，分母为该区域实际执行的 323 次，不是 357 个
步骤；没有执行该区域的步骤不计入命中率。

| 区域 | 固定步骤零路径 / 调用 | 固定步骤命中率 | 全程零路径 / 调用 | 全程命中率 |
| --- | ---: | ---: | ---: | ---: |
| b221:3383 | 271 / 323 | **83.901%** | 56356 / 63196 | 89.177% |
| b222:240 | 266 / 323 | **82.353%** | 56338 / 63157 | 89.203% |

这里的限制有两层。首先，命中前仍要读取并归约 **14 个掩码 × 16 字 = 224
个字**，已有的上游掩码生成和默认表达式也没有整体跳过。机器码可见成串的
SIMD `por` 及最终零比较；回退仍保留向量位运算，且没有新增独立 helper。
b221/b222 的条件跳转仅各增一条（32→33、26→27），两者均无函数调用，
因此这次不是上一节 lambda 未内联或逐字分支爆炸的问题。检查本身有实际
成本，命中率不能直接当成节省的工作比例。

其次，当前规则覆盖的计算很少。在**同一组直接 batch 探针、同一批固定步骤**
内，baseline 全部活跃 batch 时间之和为 52.96187 µs，其中整个 b221+b222
仅 1.46245 µs，占 **2.761%**；实际被改写的选择区域还只是这两个 batch
的一部分。两批实测合计降到 1.42724 µs，节省 0.03521 µs，仅相当于该探针
全部活跃计算的 **0.0665%**。这不是无探针 eval 或 walltime 的精确预测，
但足以说明此次覆盖范围很难带来可观的总加速。不能把“82%–84% 命中”
理解为“瓶颈分区省掉了82%–84%的计算”。

七个改写对象的可执行节从 244670→263878 B（+7.851%），没有新增模型函数；
增量编译 1.603 s，本次完整构建 46.709 s。普通 archive SHA-256 为
`32ab00bee353f3b86f81480ef9466ffbbe7a45ee50a4fd1f31551f5dd95b324c`，
ELF 为 `2e6468c138632c528cf4d47805a5b77e6248c08ebe1a256900245db252b86f94`。
源码审计检查全部 7552 个文件及冻结 archive，只有预期的七个模型对象改变。

本轮总计 **32 次 C100000、11 次 C100、128970 组 sanitizer 差分**全部通过。
完整运行分为普通 16 次、core 8 次、batch 4 次、oracle 2 次、独立计数 2 次。
**整组零掩码候选不迁入正式 emitter 或默认配置**，保留
`s6_commit_complete + THP + 64 B`；评估任务已结束，没有遗留基准进程。
下一步应转向覆盖更多活跃计算的通用模式，优先核查 bool 扩展、拼接为宽掩码
再参与选择的中间表示成本，先估计其覆盖和可省工作，再决定是否实现；不再
围绕这 16 段低占比区域继续搜索检查或布局变体。

[`完整普通与 PMU 结果`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_zero_mask_20261010/summary.json)、
[`batch 对照`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_zero_mask_20261010/batch_runs/summary.json)、
[`实际命中计数`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_zero_mask_20261010/counts/summary.json)、
[`总验证计数、覆盖比例与保留结论`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_zero_mask_20261010/conclusion.json)、
[`b221 候选机器码`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_zero_mask_20261010/machine_audit/candidate_p26_b221.asm)、
[`b222 候选机器码`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_zero_mask_20261010/machine_audit/candidate_p26_b222.asm)。

### 7.93 布尔宽掩码的连续扩展与覆盖评估（2026-10-10）

承接 §7.92，先扫描保留基线 `s6_commit_complete` 的掩码生产端。生成代码
中的一种模式是把单个 bool 扩展为 64 位全零/全一，再按字拼成宽数组。
扫描得到 **21521 个**符合纯四语句赋值模式的扩展字；这只是静态站点数，
不代表动态耗时，也不声称覆盖所有 bool 扩展形式。

其中 **4664 个字**来自连续 bool 槽，并写入连续目标字，源、目标具有相同
的单位步长；组成 **323 段、31 个 compute 文件、9 个分区**。一个常见例子是
15 个相邻 bool 原来从高地址向低地址逐条生成宽字；改写后按低地址到高地址
的顺序表达为 `out[first_word+i] = uint64_t(0) - uint64_t(bool_slots[first+i])`。
无符号减法使 false 对应全零、true 对应全一，不增加逐字选择分支。

这次并未把持久化宽掩码压缩成另一种存储格式；仍保留原数组布局、每个字
的值、原有写回和激活，仅把纯连续扩展写成便于编译器向量化的顺序循环。
也不叠加 §7.92 的零掩码检查。匹配不读取分区或信号名单、实测热点或
编译后反馈；源必须为真实 bool 数组槽，目标为已知 uint64 数组或其直接
引用，临时变量不得有其他使用，中间不得穿过副作用或非连续项。

| 分区 | 连续段数 | 扩展字数 | 改写文件数 |
| --- | ---: | ---: | ---: |
| p5 | 31 | 388 | 3 |
| p14 | 49 | 735 | 3 |
| p17 | 1 | 14 | 1 |
| p20 | 26 | 390 | 3 |
| p24 | 7 | 105 | 1 |
| p25 | 71 | 1029 | 7 |
| p26 | 35 | 525 | 3 |
| p27 | 64 | 960 | 6 |
| p31 | 39 | 518 | 4 |

最短段长为八字。段长分布为 8/9/11/12/13/14/15/16 字各
4/15/5/14/5/5/261/14 段。p10/p18 有原始扩展站点，但没有命中这项连续
资格；p26 命中 b212/b213/b216。此前固定 357 步的 batch 探针中，这三批
合计 0.71259 µs，占全部活跃 batch 的约 **1.217%**，且扩展只是批内部分
计算。因此这是一个成本低、可明确验证的生产端候选，不能仅凭站点数增加
就预期明显的端到端收益；尚有 16857 个原始站点未进入本规则。

专项 Clang23/O3 + ASan/UBSan 差分 **511488 组**通过：包含 7/8/9/14/15/
16/17/31/64 字，正反向原赋值顺序、局部数组/持久化数组，16 个 bool 以内
穷举全部组合，更长序列随机取值，并校验偏移与目标两端未改写的哨兵字。
非连续源/目标、共享临时变量、不明指针目标、插入副作用和不同位掩码均有
拒绝检查。完整评估继续采用 node030 CPU96–127、NUMA1、N=K=32、all-spin、
Clang23/O3、THP、64 B 计算入口对齐、ASLR off，按两个窗口八对普通 AB/BA
及独立 PMU、batch 和原表达式校验判断保留与否。

[`通用扫描和试验脚本`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_mask_expand_20261010.py)、
[`全图覆盖清单`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_mask_expand_20261010/inventory.json)、
[`专项差分结果`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_mask_expand_20261010/semantics/summary.json)。

#### 首版对照与局部数组匹配补全

首版完成 30 次 C100000、10 次 C100，全部通过。八对普通 walltime 均值
13.28875→13.21875 s，配对变化中位数 **−0.526%，5/8 更快、1/8 持平**；
两个窗口分别 −0.564%/−0.339%。Host 配对 −0.526%、全局 eval −0.537%，
update +0.621%。这是小幅正向结果，不是确定的默认接受结论。

固定 p26 瓶颈步骤的指令 331707.95→331640.43（**−0.0204%**，每步仅少
约 68 条），动态分支近乎不变，cycles 配对 −0.144%、条件 eval +0.843%。
直接 b212/b213/b216 配对分别 +0.842%/+4.204%/+1.880%，每批两对都是
一快一慢，没有一致局部时间收益。全部 31 个改写函数的静态指令
111193→106668，独立调用点仍为 15 个；改变对象的可执行节
573512→550786 B（−3.963%），静态缩小明显大于动态指令下降。

随后进行生成形式覆盖审计，发现首版资格识别存在不必要的语法限制：只认
带 `{}` 初始化的局部 `std::array`，而真实 emitter 的纯局部数组通常声明为
`std::array<uint64_t, N> tmp;`，随后逐字赋值。首版实际命中的 323 段全是
持久化槽引用；表中的“p10/p18 无命中”仅适用于这个首版匹配器，不能解释为
这两个分区不存在连续 bool 扩展。无初始化本身不影响本变换的合法性：
改写只写入原本将赋值的字，不读取目标旧内容，其他字继续按原程序处理。

因此补全两种局部声明的识别，仍要求已知数组类型、非别名来源、纯连续
赋值与临时量无其他用途，**不根据首轮时间选择范围**。补全版覆盖
**25 分区、275 文件、949 段、12307 个字**，相对首版增加 626 段/7643 字。
p10/p18 分别进入 40/53 段、552/692 字，p26 为 39 段/589 字。新增无初始化
数组的专项测试会先明确赋值边界哨兵，再比较全部结果，避免测试自身读取
未定义的字。补全版独立从同一冻结基线构建，按同样两个窗口八对协议重测，
不与首版混成一组结果。

[`首版完整对照`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_mask_expand_20261010/summary.json)、
[`首版覆盖、局部耗时及机器码汇总`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_mask_expand_20261010/assessment.json)、
[`补全版结构覆盖`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_mask_expand_full_20261010/inventory.json)。

#### 补全版终态及字节掩码表示修正

补全版也完成 30 次 C100000、10 次 C100 和 **767232 组**专项差分，全部
功能通过。普通八对 walltime 均值 13.55875→13.62250 s，配对中位
**+0.442%，3/8 更快**，两个窗口分别 +0.855%/+0.073%；Host +0.505%、
全局 eval +0.349%。覆盖增加后没有延续首版的小幅正向结果，因此此版
不进入默认。

固定瓶颈步骤中，p10/p18 的指令分别 **+0.155%/+0.215%**，动态分支
**+0.329%/+0.570%**，四对中的指令增量一致。p26 指令 −0.067%，但条件
eval +1.009%；两个直接 batch 对照中新增覆盖的 b37 为 −5.260%，其他
三个生产 batch 没有一致局部收益。只看局部正向指标仍不能推出总收益。

机器码进一步指出一个具体的表示问题，而不只是循环或代码布局猜测。
例如 p10/b141、p18/b243 都命中八段循环：

| 函数 | 原静态指令 → 补全版 | 原条件跳转 → 补全版 | 条件回跳数 | 函数调用 |
| --- | ---: | ---: | ---: | ---: |
| p10/b141 | 1140 → 1314 | 32 → 40 | 均为 7 | 均为 0 |
| p18/b243 | 1178 → 1323 | 25 → 33 | 均为 7 | 均为 0 |

这些短循环已被展开，没有新增循环回跳或 helper 调用。原代码在字节内做
`psubb` 形成 0/−1，随后符号扩展；同一扩展掩码参与 `pand` 和 `pandn`，
后者直接完成补掩码选择。新代码的 `uint64_t(0) - uint64_t(bool)` 则先
零扩展，再做 `psubq`；在这些片段中，另一选择臂还单独通过 `pcmpeqb`
及重排生成补掩码，重复了部分宽化工作。标量尾部也出现了额外条件分支。
这是这些函数的直接机器码证据，不将全部 walltime 变化唯一归因于它。

据此增加表示修正版，保持补全版的 949 段资格、赋值顺序和循环边界完全
相同，仅改成先在有符号字节内得到 0/−1，再扩成 uint64：
`uint64_t(int8_t(-int(bool_value)))`。bool 只能是 0/1，负值只会是 0/−1，
都在 int8_t 范围内；转换成 uint64 时 −1 按模转换成全一。这不依赖 SIMD
指令集扩展，不新增缓存，不按实测函数名单启用，也不是给循环强制加展开
或对齐选项。修正版独立从冻结基线构建、验证和计时，结果在本节追加。

[`补全版完整结果`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_mask_expand_full_20261010/summary.json)、
[`补全版汇总`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_mask_expand_full_20261010/assessment.json)、
[`p10/b141 原代码`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_mask_expand_full_20261010/machine_audit/baseline_p10_b141.asm)、
[`p10/b141 补全版`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_mask_expand_full_20261010/machine_audit/candidate_p10_b141.asm)。

#### 三版终态与保留结论

字节掩码修正版也完成全部验证：30 次 C100000、10 次 C100、767232 组
Clang23/O3 + ASan/UBSan 差分通过。三个版本合计 **90 次 C100000、30 次
C100、2045952 组专项差分**；其中普通 walltime 对照为每版两个窗口、
八对 AB/BA，其余为独立原表达式校验、固定步骤 PMU 和 batch 探针运行，
不将插桩时间混入普通 walltime。

| 候选 | 覆盖段数 / 文件数 | 同期基线 → 候选 walltime 均值（s） | 八对变化中位数 | 两窗口变化中位数 | 更快对数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 首版连续扩展 | 323 / 31 | 13.28875 → 13.21875 | −0.526% | −0.564% / −0.339% | 5/8，另 1 对持平 |
| 补全局部数组，先宽化再取负 | 949 / 275 | 13.55875 → 13.62250 | +0.442% | +0.855% / +0.073% | 3/8 |
| 同样覆盖，先形成字节掩码再宽化 | 949 / 275 | 13.81625 → 13.81000 | +0.111% | +0.111% / +0.109% | 3/8，另 1 对持平 |

百分比统一为每对 `100 × (candidate / baseline − 1)` 的中位数，负值表示
更快，并非表中两个均值相除。修正版均值略降、配对中位略升并不矛盾：
八对变化依次为 0、+0.222%、−0.441%、+0.886%、−0.354%、−2.177%、
+1.004%、+0.573%，单对 −2.177% 对均值影响较大。三个版本均从同一
`s6_commit_complete` 归档独立构建，SHA-256 保持
`55d5d55b45806a6633ba71160e8b88ee4f0094b552353c5e49bac2dd5d21ddf2`。
各轮发生在不同时间窗口，只用各自同期 AB/BA 判断收益，不把 13.29 s 和
13.82 s 的跨窗口差异当作版本退化。

修正版消除了补全版中观察到的重复宽化，但没有减少足够的实际工作。
275 个源文件都重新编译，其中 **203 个对象文件与冻结基线逐字节相同**，
只有 72 个归档成员发生变化。p10/b141、p18/b243 两个示例对象也与基线
完全相同，静态指令/条件跳转分别恢复为 1140/32、1178/25。全体 275 个
被审计的主计算函数指令 551888→552099、条件跳转 7710→7712、调用点
343→343；函数集合未增删。实际改变的 72 个对象可执行节
915316→916541 B，仅增加 1225 B。两种完整覆盖版本的源文件、原始哈希
和匹配段清单逐项一致，因此这些差异来自表达方式，不是缩小优化范围。

| 固定瓶颈步骤 | 每步指令均值：基线 → 修正版 | 指令配对变化 | cycles 配对变化 | eval 配对变化 |
| --- | ---: | ---: | ---: | ---: |
| p10，440 步 | 255857.125 → 255853.952 | −0.00124% | −0.282% | −0.196% |
| p18，719 步 | 260825.731 → 260825.704 | −0.000008% | −1.693% | −1.165% |
| p26，357 步 | 331707.917 → 331714.595 | +0.00201% | −1.665% | −1.189% |

动态分支数也几乎不变。局部 cycles/eval 的小幅改善没有伴随指令工作量
下降，也没有变成普通 walltime 收益；不能据此声称掩码扩展明显加速。
p26 的 b37/b212/b213/b216 直接计时均为两对一快一慢，四批合计只占同期
全部活跃 batch 时间的 2.190%，且每批包含掩码以外的工作。普通 Host 配对
+0.089%、全局 eval +0.256%、update −0.651%，最终仍以 walltime 判断。

**本轮三版均不晋升默认，继续保留累计基线、THP 和 64 B 对齐。** 首版
小幅正向结果没有一致局部证据，扩大合法覆盖后也未复现；修正版确认大部分
原展开式本已被 Clang 优化。这个结论仅关闭本次“连续扩展改写”的候选，
不等于证明所有宽掩码都没有成本，也不等于证明源代码更短就必然更快。

下一步应检查掩码的使用端，寻找能同时消除掩码生成和后续选择的通用
代数模式，例如同宽无符号的 `select(cond, x + 1, x) → x + uint64_t(cond)`。
这要求两臂的 `x` 可证明来自同一个值、同一求值时刻；当前例子中的状态槽
和宽数组缓存不能仅凭内容看似相同就合并。应先证明这种关系并统计覆盖，
再做差分和 walltime 验证；该方向在本轮尚未实现，也不预先承诺收益。

[`三版对照、构建身份及总验证计数`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_mask_expand_signed_20261010/comparison.json)、
[`修正版完整结果`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_mask_expand_signed_20261010/summary.json)、
[`修正版覆盖、局部耗时与机器码汇总`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_mask_expand_signed_20261010/assessment.json)、
[`修正版 p10/b141 机器码`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_mask_expand_signed_20261010/machine_audit/candidate_p10_b141.asm)、
[`修正版 p18/b243 机器码`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/bool_mask_expand_signed_20261010/machine_audit/candidate_p18_b243.asm)。

### 7.94 掩码选择的恒零分支与跨 batch 常量传播（2026-10-10）

承接 §7.93，先核实 `select(cond, x+1, x)` 的值同一性条件。p10/b141
的另一选择臂实际读取 `value_words_16_slots_[0]`，其唯一写者 p10/b38
计算的是 `(zeros & mask) | (zeros & ~mask)`，恒为零；它不是旧计数器的
缓存。因此这个例子不能改成 `x+cond`，可以继续研究的是
`(incremented & mask) | (zero_slot & ~mask) → incremented & mask`。
识别资格仍只依赖结构与值证明，不依赖这些分区号、变量名或 profile。

本轮原型扫描全部 32 个模型的头文件、compute/commit、初始化、状态和
eval 源文件，建立每个私有宽数组槽的完整访问清单。候选必须有真实的
`std::array<...>{}` 零初始化；初始化整组清零被显式识别；每次写入都要
通过纯局部常量及 AND/OR/XOR/NOT 表达式独立证明为零。推导写者时不假定
任何持久化槽为常量，因而不能靠“先假设它为零”形成循环证明。

不明写入、逐字写入、动态索引、别名逃逸、无法解析的使用和非零初始化
均拒绝。局部常量按 C++ 作用域跟踪，写入要求紧邻的 `next_words` 定义；
没有借用其他作用域的同名临时量。所有已知 helper 在 32 个模型中逐一
核对为相同实现，其输入为只读数组。原型只替换纯 helper 的常量槽读取，
保留槽本身、原写入、变化检测、激活与调度，避免把代数简化和调度变化
混成一个实验。

静态资格命中 **22 个分区、72 个槽、614 个 compute 文件、2067 处读取**。
每个入选槽恰有一个独立证明为零的正常写者；宽度为 4/8/10/12/16 个
uint64 字的槽分别为 4/5/1/2/60 个。p10 为 5 槽/115 处读取，p18 为
3 槽/168 处读取，p26 为 2 槽/38 处读取。这里是静态覆盖，不是动态节省
时间的估计，也不声称穷尽全部可传播常量。

专项测试已通过 Clang23/O3 + ASan/UBSan **73728 组**：包含 1/2/3/4/8/
16/17/31/64 字，零、全一、单比特及随机部分掩码，第一次激活写者之前
读取、跳过写者、重复初始化及原变化检测。另有 **108 项**拒绝检查，
覆盖不明/非零写入、逐字写入、动态索引、别名与整组逃逸、缺少初始化及
自引用写者。完整 XiangShan oracle 将在每个替换点同时检查槽确为零、
新旧表达式相同，再进行普通性能对照。

这次机会的来源是跨 C++ 文件的信息丢失：写者所在文件可把计算折成零，
其他文件却仍把持久化数组当作未知值读取。当前 `const_fold.cpp` 中
`foldOperation` 的常规入口在遇到任一非常量操作数时即返回，单靠这条
完整常量求值路径不能推出 `0 & dynamic == 0`。是否在生产 IR 或后端值
分析中补这种吸收律，应在验证收益后决定；当前只做冻结生成包上的通用
原型，没有更改共享工作区中的正式 emitter 或 Verilator 路径。

性能仍从 `s6_commit_complete + THP + 64 B` 独立构建，不叠加 §7.93 的
候选。配置为 node030 CPU96–127、NUMA1、N=K=32、all-spin、Clang23/O3、
ASLR off；普通运行分两个窗口共八对 C100000 AB/BA，另外独立运行原
表达式校验、固定瓶颈步骤 PMU 和 p26 batch 探针。终态结果在本节追加。

[`通用证明、改写及评估脚本`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_slot_constant_20261010.py)、
[`完整访问证明与覆盖清单`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_slot_constant_20261010/inventory.json)、
[`运行库 helper 一致性`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_slot_constant_20261010/runtime_proof.json)、
[`专项差分及拒绝检查`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_slot_constant_20261010/semantics/summary.json)。

#### 实际计时配置补充

本轮实际计时改为**双方统一的匿名 4 KiB 代码页**。node030 NUMA1 当前
不能完整分配代码大页，因此不将部分大页覆盖或两边页大小不同的样本纳入
对照。沿用原进程内代码页工具的 `small` 模式：复制前后逐字节核对，保持
原虚拟地址，并逐次检查 `AnonHugePages == 0`；不修改系统 THP 设置。
原型构建、CPU96–127、NUMA1、all-spin、Clang23/O3、64 B 对齐和 ASLR off
均保持前述条件。所有成功运行在 manifest 中记录 `codepage=small`，本轮
数据与既有 THP 数据分开解释；主线默认 THP 仍保留，不能用这组普通页
结果直接宣称默认大页配置上的收益。

普通候选增量编译 18.487 s，构建合计 55.230 s。614 个改写文件中 595 个
对象有实际变化，改变对象的可执行节 6439641→6232134 B（约 −3.22%）。
两个之前检查过的函数，p10/b141 静态指令/条件跳转 1140/32→995/24，
p18/b243 为 1178/25→980/17，均仍无函数调用。这证明使用端确实删除了
机器指令；动态瓶颈步骤与 walltime 仍需独立验证。

#### 读取传播版终态及冗余写入消除

读取传播版在统一 4 KiB 页下完成 30 次 C100000、10 次 C100，功能全部
通过。八对普通 walltime 均值 **14.50375→14.57000 s**，配对变化中位数
**+0.0703%，2/8 更快、2/8 持平**；两个窗口分别 +0.6997%/−0.0337%。
Host +0.0532%、全局 eval +0.0221%、update +0.2055%，没有形成总时间
收益。每对百分比均为 `100 × (candidate / baseline − 1)`，表述中的
配对中位数并非两组均值之比。

四对固定瓶颈步骤 PMU 无计数器复用，指令下降在各对中一致：

| 分区 / 固定步骤数 | 每步指令均值：基线 → 读取传播 | 指令配对变化 | cycles 配对变化 | eval 配对变化 |
| --- | ---: | ---: | ---: | ---: |
| p10 / 440 | 255857.05 → 254636.23 | −0.4771% | −0.4384% | −1.2628% |
| p18 / 719 | 260825.72 → 258788.45 | −0.7811% | −0.0966% | −1.8222% |
| p26 / 357 | 331707.94 → 331029.97 | −0.2044% | +0.6277% | +0.6635% |
| p29 / 450 | 349870.93 → 349870.84 | 约 0% | +2.2059% | +1.7564% |

示例函数静态指令下降约 13%/17%，但全分区实际执行的指令只少不到 1%，
两者分母及动态覆盖不同。p26 分支数 +0.3850%、分支失误 +3.8688%；未
命中改写的 p29 指令/分支数不变，分支失误约 78.02→91.74、cycles 四对
均上升。代码地址、并行运行和系统状态等仍可能影响执行，不能把全部差异
唯一归因于十余次额外分支失误，也不能只看 p10/p18 局部时间推导 walltime。

p26 七个命中 batch 在同期探针中合计 3.82359→3.73277 µs，原合计占
全部活跃 batch 的 **5.6823%**，节省仅相当于活跃计算的约 **0.1350%**。
它们不是全部都变快：b207/b208/b209 的两对均改善，b205/b210 的两对
均退化。所有调用/活跃次数和活跃位计数保持一致；这组插桩数据只解释
动态覆盖，不混入普通 walltime。

进一步补齐同一恒零证明的直接推论：若槽的旧值和每次写入值都恒为零，
`grhsim_assign_words_full` 的返回值就恒为 false。完整候选在读取传播外，
消除全部合法恒零槽的冗余写入及其永不执行的变化激活分支；其他写入、
初始化和调度保持原逻辑。不按首版的分区收益或编译结果挑选写者。oracle
逐次检查写入前槽值和 `next_words` 都为零，并实际调用原赋值 helper 确认
其返回 false；普通候选才删除冗余调用。补全版从同一冻结基线独立构建，
仍使用双方统一的 4 KiB 页与两个窗口八对 AB/BA。

[`读取传播完整结果`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_slot_constant_20261010/summary.json)、
[`读取传播汇总`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_slot_constant_20261010/assessment.json)、
[`预处理分支与非零写入边界核对`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_slot_constant_20261010/proof_checks.json)。

#### 完整候选终态：普通页下有小幅正向信号，默认大页收益尚未验证

读取传播加写入消除版覆盖同一组 72 个槽，改写 2067 处读取和 72 处
恒零写入，共 **615 个文件、2139 处改写**。新旧初始化仍相同，没有按
首版快慢缩减资格。原表达式 oracle、73728 组 sanitizer 差分、108 项
拒绝检查，以及预处理分支/非零字面量写入的边界核对全部通过；所有相关
615 个访问文件均无条件预处理分支，避免把未编译的定义误当作常量依据。

| 方案，均为双方 4 KiB 代码页 | 同期基线 → 候选 walltime 均值（s） | 八对变化中位数 | 两窗口变化中位数 | 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| 仅传播恒零读取 | 14.50375 → 14.57000 | +0.0703% | +0.6997% / −0.0337% | 2/8，另 2 对持平 |
| 同时消除恒零写入和无效变化检查 | 14.54375 → 14.47625 | **−0.7934%** | −0.0638% / −1.2025% | 5/8 |

完整候选普通 Host 配对 **−0.8174%**、全局 eval **−1.3304%**、update
+0.0922%。八对 walltime 变化依次为 +0.7676%、+2.0000%、−2.4210%、
−0.8953%、+1.7241%、−0.6916%、−2.4005%、−1.7135%，波动仍跨过零。
两个版本各自与同期基线比较，不能直接相减百分比，声称写入消除独自带来
约 0.86 个百分点。普通代码页初始化均值为基线 0.08582 s、候选 0.08156 s；
Host 也有小幅正向变化，所以不能把全部差异解释为页面初始化时间。

完整候选四对固定步骤的结果为：

| 分区 | 每步指令均值：基线 → 完整候选 | 指令配对变化 | cycles 配对变化 | eval 配对变化 |
| --- | ---: | ---: | ---: | ---: |
| p10 | 255857.06 → 254571.36 | −0.5025% | +4.1762% | +4.5851% |
| p18 | 260825.69 → 258722.56 | −0.8063% | −1.0428% | −0.8250% |
| p26 | 331707.97 → 330962.23 | −0.2248% | +0.0230% | −0.0810% |
| p29 | 349870.91 → 349871.03 | 约 0% | +0.4499% | +0.4100% |

每步指令节省相对读取传播版只进一步增加约 **65/66/68 条**（p10/p18/
p26），这些增量只有分区总指令的约 0.02%–0.03%。p26 七个命中 batch
合计 3.78310→3.67413 µs，占同期全部活跃 batch 的 5.6747%，实测节省
相当于活跃计算的 **0.1635%**；调用、活跃次数和活跃位计数保持一致。
两轮都确认 p29 的所有模型对象未改写，但重新链接后其 147 个 compute
函数的入口地址全部移动，且仍满足 64 B 对齐。由此只能说明未改写分区
也存在地址布局变化，尚未单独证明它或其他因素造成了多少时间差异。

615 个对象的可执行节 6702884→6478663 B（−3.3451%），审计的主计算
函数静态指令 1363016→1327244（−2.6245%）、条件跳转 20661→20091，
调用点仍为 1440，函数集合没有增删。这里的对象集合比首版多 20 个实际
改变对象，不应直接拿两版各自“改变对象集合”的字节总量判断谁更大。
增量编译 18.934 s，构建合计 55.293 s；普通 archive SHA-256 为
`0e2c59664cbd264b7f7eceed975ee441dc519bf7836ef99d1db908f58e3a0ef2`，ELF 为
`3e93c438f4167a4b54bc20341f8bda96f33bb54c978d2389ed7e5695f99a2d77`。

两版总计 **60 次 C100000、20 次 C100、147456 组专项差分全部通过**。
保留判断：**读取传播版不晋升；完整候选保留为待复核方案，暂不迁入默认。**
完整候选在普通页下有约 0.8% 的正向信号，但第一窗口近乎持平，默认 THP
配置上的收益也尚未测得。主线的累计优化、THP 和 64 B 对齐继续保留。
下一次应在 THP 可用时先复测同一个完整候选，而不是继续扩大源代码匹配
或根据这轮偶然快慢选择分区；若需要正式实现，应把值证明落在 IR/后端
常量分析中，生成 C++ 改写脚本只作为本次实验工具。

[`两版汇总、输入身份、页大小及总验证计数`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_slot_constant_elide_20261010/comparison.json)、
[`完整候选全部结果`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_slot_constant_elide_20261010/summary.json)、
[`完整候选汇总`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_slot_constant_elide_20261010/assessment.json)、
[`完整候选逐文件改写清单`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_slot_constant_elide_20261010/sources.json)。

#### THP 复核终态：同一完整候选的约 1% walltime 收益得到复现

2026-10-10 继续前述计划，只复核完整恒零候选，没有叠加新优化。node030
NUMA1 的空闲内存已恢复到约 119 GiB，buddy 高阶空闲块也恢复；基线和
候选首次启动均成功取得完整大页覆盖，无需修改系统 THP 设置、压实内存
或借用其他 CPU。仍固定 node030 CPU96–127、NUMA1、N=K=32、all-spin、
Clang23/O3、64 B compute 入口对齐及关闭 ASLR，不增加空闲率筛选。

复用上轮 **完全相同的普通、oracle、PMU 和 batch ELF**，没有重新编译
或链接。普通基线仍是累计 `s6_commit_complete`，不是“只传播读取”版；
其 ELF SHA-256 为 `001299fcf0fd0d32f024de53fae3340f8927cf84dfa339a9cb65fd695e89ae39`，
完整候选为 `3e93c438f4167a4b54bc20341f8bda96f33bb54c978d2389ed7e5695f99a2d77`。
双方使用同一原始进程内代码大页 preload，所有运行均核对可重映射代码区
的 `anon_huge == bytes`：普通基线 **90 MiB**、候选 **88 MiB**。这里的
“完整”指 2 MiB 对齐的可重映射 RX 区间，不包含未重映射的区间边缘。
候选代码较小，覆盖字节数不同是实际二进制的属性；未混入 4 KiB 或部分
大页运行。输入镜像、NEMU、固定步骤标签、archive 和 ELF 的身份前后不变。

顺序为 oracle 一对、普通窗口 A 四对、固定步骤 PMU 四对、p26 batch
两对、普通窗口 B 四对。每阶段先做两次 C100，再以 AB/BA 交错执行
C100000；**30 次 C100000、10 次 C100 全部通过**，没有筛除任何成功样本。
C100000 均通过 Difftest/终态签名检查，oracle 逐次校验原表达式及恒零
写入；PMU 无 multiplex，batch 调用次数、活跃次数、活跃位计数完全一致。
上轮 sanitizer/拒绝检查的产物作为同一候选的既有证据复用，不重复计作
本轮新测试。仅 16 次普通 C100000 用于以下 walltime 比较。

| THP 普通运行 | 同期基线 → 候选均值 | 八对变化中位数 | 候选更快对数 |
| --- | ---: | ---: | ---: |
| walltime | 14.42625 → 14.24625 s | **−1.0188%** | **8/8** |
| Host | 14.327875 → 14.148500 s | **−0.9838%** | **8/8** |
| 全局 eval 阶段 | 56.136875 → 55.374000 µs/step | −1.2205% | 6/8 |
| 全局 update 阶段 | 11.271625 → 11.155000 µs/step | −1.1657% | 7/8 |

百分比统一为 `median(100 * (candidate_i / baseline_i - 1))`，不是两列
均值相除。八对 walltime 变化依次为 −0.9880%、−3.9402%、−1.5048%、
−0.3413%、−1.0497%、−0.1388%、−1.2649%、−0.6983%。窗口 A 的均值
14.5400→14.2925 s、变化中位数 **−1.2464%**；窗口 B 为
14.3125→14.2000 s、**−0.8740%**。两窗口均四对更快。页面初始化均值
0.057649→0.055771 s，仅相差约 1.88 ms；普通 walltime/Host 均值分别
少 180.0/179.4 ms，因此收益并非只来自启动时的大页设置。

固定步骤探针的四对结果如下。“瓶颈步骤”沿用候选构造前冻结的标签，
两边测量相同步骤，不是各自事后挑选的最大值；它们也不同于全程平均。

| 分区 / 固定步骤数 | 瓶颈步骤 eval 均值：基线 → 候选（µs） | eval 配对变化 | 指令配对变化 | cycles 配对变化 |
| --- | ---: | ---: | ---: | ---: |
| p10 / 440 | 51.06644 → 50.51987 | −0.9582% | −0.5025% | −0.5602% |
| p18 / 719 | 59.41899 → 58.18984 | −2.0655% | −0.8064% | −0.9414% |
| p26 / 357 | 70.06931 → 69.26560 | −1.0663% | −0.2248% | −1.5884% |
| p29 / 450 | 62.22792 → 62.44948 | +0.3046% | 约 0% | +0.1931% |

p10/p18/p26 的指令减少量与上轮普通页测量一致，说明同一计算工作确实
被消除。p18 的四对固定步骤 eval 全部改善；p10/p26 各为两对改善、
两对退化，局部时间仍有波动。p26 分支数 +0.3532%、分支失误 +2.0872%，
并非所有硬件指标都单调改善。p29 的对象代码没有改写，但本候选原有的
重新链接已改变其函数地址；其固定步骤分支失误 78.94→83.61，配对
+6.3992%，而普通全程平均 eval 配对 +1.9979%。这项局部退化不能忽略，
也尚不能唯一归因于地址或分支失误；最终普通 walltime 八对均有净收益。

p26 命中的 b46/b62/b205/b207/b208/b209/b210 合计均值
**3.90350→3.66152 µs**，原先只占全部活跃 batch 的 **5.8238%**；
节省的 0.24198 µs 相当于原活跃计算的 **0.3610%**。这进一步确认这条
规则可以减小冗余，但覆盖面不足以单独解决 p26 的大部分剩余瓶颈。
插桩测量不参与普通 walltime 汇总，也不据其快慢筛选分区或槽。

阶段判断：**完整恒零候选的约 1% 净收益在 THP 下得到复现，值得进入
正式实现；本轮尚未修改主线默认。** 上轮普通页 −0.7934%、本轮 THP
−1.0188% 都是各自同期 AB/BA 的结果，不能把两者差额说成 THP 的额外
收益，因为两种页模式未在同一窗口交错比较。下一步将恒量证明与传播
落到正式 IR/后端分析，保留初始化、全部写者、逃逸和变化激活语义的
约束；不把生成 C++ 的实验改写器或分区/变量白名单直接做成默认。
正式生成路径仍需单独验证与本候选一致及其 walltime，再决定开启默认。
累计主线、THP、64 B 对齐和原有 Verilator 路径均未改动。

[`THP 完整汇总`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_slot_constant_elide_thp_20261010/summary.json)、
[`冻结输入及执行记录`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_slot_constant_elide_thp_20261010/run.json)、
[`复用二进制的复测驱动`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_slot_thp_20261010.py)、
[`固定步骤 PMU`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_slot_constant_elide_thp_20261010/core/summary.json)、
[`p26 活跃 batch`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_slot_constant_elide_thp_20261010/batch_runs/summary.json)。

#### THP 同 ELF 复测：绝对 walltime 回落，但仍高于更早窗口

为确认上一轮 14.426 s 是否是暂态机器状态，立即复用完全相同的 baseline
和完整候选 ELF，在 node030 CPU96–127、NUMA1、THP、C=100000、all-spin
下重新执行两个窗口、八对 AB/BA；不重新编译、不改变输入、不混入 PMU 或
batch 计时。两边每次均再次确认完整匿名大页覆盖，代码页分别为 90 MiB
和 88 MiB；16 次普通运行全部 Difftest 通过。

| THP 同 ELF 复测 | baseline | candidate | 配对变化中位数 | 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| walltime 均值 / s | 13.95875 | 13.86125 | **−0.5731%** | **8/8** |
| Host 均值 / s | 13.86975 | 13.76800 | −0.5769% | 8/8 |
| 全局 eval / µs | 53.42975 | 53.11938 | −0.4789% | 7/8 |
| 全局 update / µs | 11.61975 | 11.53600 | −0.8561% | 7/8 |

两个四对窗口的 walltime 配对中位数分别为 **−0.6816%** 和 **−0.4658%**；
变化范围 −0.2882% 至 −1.4245%。因此候选相对同期 baseline 的小幅收益仍
存在，但低于上一轮 THP 复测的 −1.0188%，说明这一级别的收益会受运行窗口
扰动。绝对 baseline 从上一轮 14.42625 s 回落到 13.95875 s，下降约
3.24%；相对更早 `wide_zero_mask` 窗口的 12.48875 s 仍高约 **11.77%**。
候选也同步回落，故这不是候选代码突然恢复或 baseline 工作量变化。

本次复测进一步支持：之前 walltime 变大的主因是机器运行状态（有效频率、
调度/共享资源等）变化，而不是仿真 step 数或生成代码工作量增加；优化的
相对收益应只用同一窗口内的 AB/BA 配对结果评价，不能比较不同日期的绝对
秒数。现阶段仍不把约 0.6%–1.0% 的端到端收益写成固定提升，后续正式实现
验证需要至少继续采用同窗口交错对照。

[`THP 同 ELF 复测汇总`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_slot_constant_elide_thp_rerun_20261010/summary.json)、
[`THP 同 ELF 复测驱动`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_slot_thp_rerun_20261010.py)。

### 7.95 恒零证明正式接入 GrhSIM 后端（2026-10-10）

前面的恒零候选已经证明值得进入正式生成路径，但生成 C++ 的实验改写器
不能作为主线实现。本轮把规则接入 `wolvrix/lib/emit/grhsim_cpp.cpp`：在
`rebuildMaterializedValueStorage` 完成、宽值槽布局冻结后，后端对 IR 的
`ValueId` 定义做递归的 `zero/ones/unknown` 三值证明，再按
`(word_count, slot_index)` 对所有槽占用者取交集。只有同一槽的全部占用者
都证明为恒零时才获得资格。输入、事件、持久状态、memory、带副作用操作、
循环证明和不支持的操作均 fail-closed；因此不会把“C++ 数组默认初始化为零”
误当作证明，也不会按分区或手工信号白名单选择。

对获得资格的值，后端只做两件事：

1. 操作数表达式用正确宽度的零 word-array 替代；
2. 写入恒零槽的 `grhsim_assign_words*` 及其变化激活分支整体消除。

槽声明仍由原路径生成并保持零初始化，非恒零值、初始化、调度和其他存储
写者不变。证明只影响 GrhSIM；Verilator 路径没有调用该分析。新增选项为
`proved_zero_value_elision`，Python/pybind 和 XiangShan 脚本均已透传，环境
入口为 `WOLVRIX_XS_GRHSIM_PROVED_ZERO_VALUE_ELISION=1`（或
`WOLVRIX_GRHSIM_PROVED_ZERO_VALUE_ELISION=1`），默认关闭。

#### XiangShan 正式生成结果

使用已有 post-stats 中间结果恢复生成，baseline 与 candidate 的调度参数、
输入和输出文件集合完全一致。正式后端报告 **92 个恒零宽槽、92 个宽值、
9935 个宽值映射项**。关闭/开启选项分别生成 148 个文件；两者调度统计
相同，54 个调度源只包含恒零读替换或写/激活消除，共出现 40 个
`proved-zero wide value` 写消除标记。生成包总源码字节数
`1500063416 → 1500051574`（减少 11842 B，约 0.00079%），这只是代码
规模证据，不能替代 walltime 结论。

正式包用 Clang 23、`-O0` 完整编译归档通过。随后接入 XiangShan GrhSIM
fixture，baseline 和 candidate 均在 `C=1000` 下通过 Difftest；默认 8 MiB
栈会使两种包都在 `init_chunk_28` 初始化时栈溢出，烟测统一使用
`ulimit -s unlimited`，这属于当前生成模型/fixture 的运行配置问题，不是
恒零选项特有的失败。该短测只作语义烟测，不作性能比较；模型初始化已占据
主要时间，尚未进行正式 C=100000 AB/BA walltime 复测。

保留判断：**正式 IR/后端接入和功能烟测通过，但选项继续默认关闭，暂不
宣称性能收益或晋升默认**。下一步应在与当前主线完全匹配的构建/运行 fixture
上复用 node030 CPU96–127、NUMA1、N=K=32、all-spin、THP、Clang23/O3、
64 B 对齐配置，先做同窗口 baseline/candidate 的 C=100000 AB/BA，再决定
是否开启默认。

[`正式后端汇总`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/formal_zero_backend_20261010/summary.json)、
[`candidate 发射日志`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/formal_zero_backend_20261010/candidate.log)、
[`baseline 发射日志`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/formal_zero_backend_20261010/baseline.log)、
[`candidate Clang23 编译日志`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/formal_zero_backend_20261010/candidate_compile.log)、
[`candidate C=1000 烟测日志`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/formal_zero_backend_20261010/candidate-emu-smoke-c1000.log)。

#### 恒量证明边界收紧后的复核

随后对证明器做了一次 fail-closed 收紧：宽度可能变化的 `assign`/`mux` 不再传播
all-ones，逻辑与归约结果只有在结果宽度为 1 bit 时才传播 all-ones。这样不会把
零扩展后的值误判为全一；恒零传播本身和 `concat` 等宽度安全规则不变。重新用同一
post-stats 输入生成 candidate，调度统计、源文件字节数和 40 处写消除标记均与收紧前
候选完全一致，仍报告 92 个恒零宽槽、92 个宽值和 9935 个映射项。Clang 23 `-O0`
完整编译、完整 GrhSIM emitter 回归 29/29，以及放宽栈限制后的 C=1000 Difftest 均通过。因此这次修正没有改变当前
XiangShan workload 的候选代码，但让证明器对宽度转换更保守；选项仍默认关闭，尚未
据此宣称 walltime 收益。

[`收紧后正式汇总`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/formal_zero_backend_20261010_tightened/summary.json)、
[`收紧后 candidate 发射日志`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/formal_zero_backend_20261010_tightened/candidate.log)、
[`收紧后 Clang23 编译日志`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/formal_zero_backend_20261010_tightened/candidate_compile.log)、
[`收紧后 C=1000 烟测日志`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/formal_zero_backend_20261010_tightened/candidate-emu-smoke-c1000.log)。

#### 32 分区 RepCut 包的 C=100000 AB/BA 复测（2026-10-10）

为确认这条规则在实际多线程框架中的收益，本轮没有把单体 `SimTop` 包当作
多线程结果，而是复用已经通过功能验证的 32 分区 RepCut 包：baseline 为
`s6_commit_complete/package`，candidate 为恒零规则在分区后模型源上的保守
落地 `wide_slot_constant_elide_20261010/package`。candidate 的分区后证明清单
为 **72 个槽、2067 次读取传播**，重新编译了 615 个模型对象；单体正式后端
之前报告的 92 个槽、9935 个映射项属于另一种 storage/layout，不能直接套到
这个分区包上。两者的候选包路径、证明清单和构建摘要分别见
[`candidate build`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_slot_constant_elide_20261010/build.json)、
[`分区后证明清单`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_slot_constant_elide_20261010/inventory.json)。

测试严格固定在 **node030 CPU96–127、NUMA1、32 线程/32 分区、N=K=32、
all-spin、ASLR 关闭、Clang 23.1.2/O3**。每个进程都通过同一个一次性 THP
代码页探针，baseline 覆盖 94,371,840 B、candidate 覆盖 92,274,688 B，且
18 次运行均满足 `anon_huge == bytes`。先做 C100 初始化/功能检查，再做 8
对 C=100000 的交错 AB/BA；两次 C100 和 16 次计时运行全部通过 Difftest，
输入 ELF、镜像和 NEMU 的身份前后保持不变。

| 指标（8 对配对中位数） | baseline | candidate | candidate 相对变化 | 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| walltime | 12.830 s | 12.725 s | **−0.6227%** | 6/8 |
| Host | 12.7425 s | 12.6380 s | **−0.6504%** | 6/8 |
| 全局 eval | 48.5595 µs/step | 48.0445 µs/step | **−0.8346%** | 6/8 |
| 全局 update | 11.0375 µs/step | 11.0455 µs/step | +0.0003% | 4/8 |
| 最大分区 eval | 32.289 µs/step | 32.0745 µs/step | **−1.1723%** | 7/8 |
| 全部分区 eval 求和 | 549.3595 µs/step | 544.4160 µs/step | **−0.6950%** | 6/8 |

AB 顺序的 walltime 配对中位数为 −1.5091%，BA 顺序为 +0.1615%，说明这个
级别的收益仍受运行窗口扰动；应以同一窗口的配对结果为准，不能与其他日期的
绝对秒数比较。变化集中在 eval，update 基本不变，和“消除恒零宽值的计算及
对应变化激活”这一机制一致；输入加载仅 +0.087%，不是主要代价。重新编译
Difftest 外壳的 walltime 为 baseline 4.50 s、candidate 4.00 s，模型静态库
沿用各自已验证的 Clang23/O3 归档。

本轮结论是：**恒零规则在真实 32 分区 GrhSIM 框架中仍有约 0.6% 的同期
walltime 收益，且最大分区 eval 下降约 1.2%，但收益小于单体布局的理论覆盖**。
因此 `proved_zero_value_elision` 继续保持默认关闭；下一步应让正式
`emit_grhsim_repcut_package` 在 32 个分区图上直接完成同一证明，并核对它与
分区后 72 槽清单一致，再用同样的 node030 CPU96–127 AB/BA 复测后决定是否
开启默认。

[`本轮 AB/BA 汇总`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/formal_zero_backend_perf_20261010/ab_ba_8pairs_thp_repcut/summary.json)、
[`运行清单及固定资源`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/formal_zero_backend_perf_20261010/ab_ba_8pairs_thp_repcut/manifest.json)、
[`THP 覆盖核验`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/formal_zero_backend_perf_20261010/ab_ba_8pairs_thp_repcut/thp_verification.json)、
[`candidate 源改写清单`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_slot_constant_elide_20261010/sources.json)。

#### 旧 `s5_commit` binary 与当前 candidate 的普通页 AB/BA（2026-10-10）

为直接比较二进制版本，复用旧的 `s5_commit/emu`（历史约 11 s 记录）作为
baseline，使用当前恒零候选的 fresh candidate ELF；两侧都不加载代码页探针，
避免把 THP 映射差异混入版本对照。测试固定在 node030 CPU96–127、NUMA1、
32 线程/32 分区、N=K=32、all-spin、Host105、ASLR 关闭、C=100000，执行
8 对交错 AB/BA。16 次正式运行全部通过 Difftest，guest 输入和两侧 ELF 身份
在运行前后保持不变。

| 指标（8 对配对中位数） | 旧 `s5_commit` | 当前 candidate | candidate 相对变化 | 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| walltime | 11.965 s | **11.770 s** | **−1.772%** | **8/8** |
| Host | 11.923 s | **11.734 s** | **−1.786%** | **8/8** |
| step 总时间 | 11.6134 s | **11.4161 s** | **−1.914%** | **8/8** |
| 全局 eval | 45.0175 µs/step | **44.4400 µs/step** | **−1.682%** | **8/8** |
| 全局 update | 10.7890 µs/step | **10.6300 µs/step** | **−1.333%** | **8/8** |
| 最大分区 eval | 30.4645 µs/step | 30.4745 µs/step | −0.809%（配对） | 6/8 |
| 全部分区 eval 求和 | 517.347 µs/step | **509.096 µs/step** | **−2.030%** | **8/8** |

旧 binary 与当前 candidate 的大小和身份分别为 `15aecc…d06860` 和
`b1c45f…827bc0`；完整运行清单和逐对数据见
[`普通页 AB/BA 汇总`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/old_s5_vs_current_candidate_native_20261010/summary.json)、
[`固定资源与输入身份`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/old_s5_vs_current_candidate_native_20261010/manifest.json)、
[`逐对结果`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/old_s5_vs_current_candidate_native_20261010/pairs.json)。

这次对照说明当前 candidate 在同一普通页运行路径下确实比历史 `s5_commit`
更快约 1.8%，因此最新 THP 窗口中的 12.7 s 不能解释为 candidate 本身变慢。
它与上一节 12.7 s 的 THP 运行不是同一种页映射条件；同时仍存在运行窗口差异，
所以不能仅凭 11.77→12.725 s 的绝对差值把全部差距归因于 THP。若要单独量化
代码页映射的影响，还需要让这两个 binary 在同一 THP preload 条件下再做一次
交错对照。

#### 旧 `s5_commit` binary 与当前 candidate 的同 THP AB/BA（2026-10-10）

上一节普通页对照的目的，是隔离 binary 版本；它不能直接回答“上一轮约
12.7 s 的 THP 运行是否由大页造成”。因此继续复用同一旧 `s5_commit` ELF
和当前 candidate ELF，在两侧同时注入同一个 `codepage.so`，设置
`REPCUT_CODEPAGE_MODE=thp`，仍固定 node030 CPU96–127、NUMA1、32 线程/32
分区、N=K=32、all-spin、ASLR 关闭、C=100000，执行 8 对交错 AB/BA。
两次 C100 和 16 次正式运行全部通过 Difftest；每次代码匿名映射都满足
`anon_huge == bytes`，旧 binary 为 90 MiB，candidate 为 88 MiB。

| 指标（8 对配对中位数） | 旧 `s5_commit` | 当前 candidate | candidate 相对变化 | 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| walltime | 11.020 s | 11.025 s | 0.000%（配对中位数） | 4/8 |
| Host | 10.953 s | 10.958 s | +0.041% | 4/8 |
| step 总时间 | 10.6491 s | 10.6425 s | −0.064% | 4/8 |
| 全局 eval | 41.830 µs/step | 41.8095 µs/step | −0.079% | 4/8 |
| 全局 update | 9.4205 µs/step | 9.4845 µs/step | +0.197% | 4/8 |
| 全部分区 eval 求和 | 474.1835 µs/step | 471.2935 µs/step | −0.452% | 8/8 |

同 THP 条件下两个 ELF 的端到端 walltime 基本相同，说明普通页 AB/BA 中的约
1.8% 优势并不是一个稳定的“candidate 必然更快”结论；它和运行窗口/频率
扰动同量级。更关键的是，这次 THP 运行的绝对 walltime 约 11.02 s，而前一
轮 THP 运行约 12.7 s，二者使用相同 96–127 核和大页方式，故 1.7 s 的差异
不能归因于“之前没开大页”，而应归因于不同时间窗口的机器状态（例如有效
频率或内核调度状态）。THP 映射初始化只需约 0.03–0.04 s，也不足以解释
秒级差距。

因此，刚才没有开大页是为了做版本隔离，并非遗漏配置；现在的同 THP 对照已
补齐。后续比较绝对 walltime 时，必须同时写明页映射模式和运行窗口；评估
优化收益则继续采用同一窗口内的 AB/BA 配对。

[`同 THP AB/BA 汇总`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/old_s5_vs_current_candidate_thp_20261010/summary.json)、
[`THP 完整覆盖核验`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/old_s5_vs_current_candidate_thp_20261010/thp_verification.json)、
[`运行清单与输入身份`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/old_s5_vs_current_candidate_thp_20261010/manifest.json)。

#### 同一 current candidate 的同 THP AB/BA 锚定复测（2026-10-10）

为了测量当前运行窗口自身的配对噪声，又用**同一个 ELF**同时作为 A/B 两侧，
在 node030 CPU96–127、NUMA1、32 线程/32 分区、N=K=32、all-spin、Host105、
ASLR 关闭和同一 `codepage.so` THP preload 条件下执行 8 对交错 AB/BA。A、B
均为 SHA256 `b1c45f507188c31a602b0e61311b6ada4e3d5f594a30379ef293c75f08237bc0`；
两次 C100 smoke 和 16 次 C100000 正式运行全部通过 Difftest，代码匿名映射
均满足 `anon_huge == bytes`。

| 指标（8 对配对中位数） | A/B 同一 ELF | 配对差异中位数 | 配对差异范围 |
| --- | ---: | ---: | ---: |
| walltime | 10.930 / 10.905 s | −0.183% | −1.091% … +1.372% |
| Host | 10.865 / 10.834 s | −0.124% | −1.097% … +1.352% |
| step 总时间 | 10.555482 / 10.526285 s | −0.102% | −1.172% … +1.429% |
| 全局 eval | 41.6265 / 41.494 µs/step | −0.093% | −1.250% … +1.977% |
| 全局 update | 9.244 / 9.224 µs/step | −0.227% | −1.604% … +2.498% |
| 最大分区 eval | 28.0965 / 28.0345 µs/step | −0.138% | −2.745% … +1.598% |
| 全部分区 eval 求和 | 469.220 / 469.331 µs/step | +0.080% | −0.215% … +0.445% |

这组结果不是优化对照，而是当前窗口的噪声锚点：端到端 walltime 的自然配对
波动约为 1.3%，因此后续小于约 0.5% 的单轮收益不能视为可靠改进，必须增加
配对次数或在另一窗口复核。`parts.json` 中 16 次正式运行的最大 eval 分区均
为 `p18`，`p10` 稳定排第二；`p29` 约 13.75 µs/step，已不是当前端到端
关键路径。后续代码优化应针对跨分区共有的生成模式，并以新的 current
production candidate 为 A 做同一轮 THP AB/BA；不能把本轮任一侧的绝对值直接
当作下一轮 baseline。

[`同 ELF 锚定汇总`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/anchor_same_candidate_thp_20261010/summary.json)、
[`运行清单与输入身份`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/anchor_same_candidate_thp_20261010/manifest.json)、
[`逐分区数据`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/anchor_same_candidate_thp_20261010/parts.json)。

#### Verilator 与当前 GrhSIM 的同轮 AB/BA 对照及 PMU 归因（2026-10-10）

针对“最近只在看 GrhSIM、是否把 Verilator 搁置了”的疑问，补做了一组可正常
运行的 Verilator/O3 生产 ELF 对照。此前找到的若干 Verilator ELF 属于带
`critical_probe`/`demand_timeline` 诊断断言的实验 binary，缺少相应环境变量会在
析构阶段 abort，已删除其失败实验目录，没有把它们当性能结果。本节使用的
Verilator ELF SHA256 为
`12ff6327e7fa4a4866974bfe6727821bebe6f9e46e8b2c9407482251d136958d`，没有这些
诊断依赖；GrhSIM ELF SHA256 为
`b1c45f507188c31a602b0e61311b6ada4e3d5f594a30379ef293c75f08237bc0`。

两侧均固定在 **node030 CPU96–127、NUMA1、32 线程/32 分区、N=K=32、all-spin、
ASLR 关闭、同一代码页 THP preload、C=100000、Clang 23/O3**，执行 8 对交错
AB/BA；C100 smoke 和 16 次正式运行均通过 Difftest。这里的 V 包来自
2026-09-25 的 `clang23_threeway/verilator_o3`，G 包是当前累积优化后的
`wide_slot_constant_elide_20261010`，所以这是“当前 Verilator 线与当前
GrhSIM 线的端点差距”，不是只替换仿真器而保持所有后端代码完全相同的反事实
实验。后续如果要量化纯仿真器差异，应从同一份当前 partitioned SV 重新生成
两种 backend，再做同轮 AB/BA；本节不会把任意一侧绝对值直接用作下一轮
baseline。

| 指标（8 对配对中位数） | Verilator/O3 | 当前 GrhSIM | G 相对 V | G 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| walltime | 25.410 s | 13.670 s | **−45.84%** | 8/8 |
| Host | 25.3195 s | 13.5980 s | **−45.93%** | 8/8 |
| step 总时间 | 24.8968 s | 13.2219 s | **−46.52%** | 8/8 |
| 全局 eval | 91.7165 µs/step | 52.5445 µs/step | **−42.40%** | 8/8 |
| 全局 update | 28.2265 µs/step | 11.2940 µs/step | **−60.00%** | 8/8 |
| 最大分区 eval | 89.2240 µs/step（p3） | 33.3005 µs/step（p18） | **−62.16%** | 8/8 |
| 全部分区 eval 求和 | 1389.6025 µs/step | 608.1875 µs/step | **−56.15%** | 8/8 |

这说明 Verilator 的问题没有被忽略，而且差距不是 Host 睡眠/唤醒策略造成的：
两侧运行时配置相同，V 的 p3 是瓶颈，G 的 p18 才是瓶颈，说明关键路径随
backend 的代码布局和调度方式发生了变化。逐分区数据见
[`V/G AB/BA 汇总`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/verilator_o3_vs_current_grhsim_thp_20261010/summary.json)、
[`运行清单`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/verilator_o3_vs_current_grhsim_thp_20261010/manifest.json)、
[`逐分区结果`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/verilator_o3_vs_current_grhsim_thp_20261010/parts.json)。

随后对相同 4 对 AB/BA（V→G、G→V 交替）做全进程 `perf stat`，计数不含诊断
代码，所有运行仍通过 Difftest 和 THP 核验。计数中位数如下：

| PMU 计数（全进程） | Verilator/O3 | 当前 GrhSIM | V/G |
| --- | ---: | ---: | ---: |
| cycles | 2.3271e12 | 1.2791e12 | **1.82×** |
| instructions | 1.9408e12 | 8.1121e11 | **2.39×** |
| branches | 7.7108e10 | 8.5451e10 | 0.90× |
| branch-misses | 2.3923e9 | 1.3713e9 | **1.74×** |
| cache-references | 1.8464e11 | 9.6133e10 | **1.92×** |
| cache-misses | 1.0297e11 | 3.8161e10 | **2.70×** |
| instructions/cycle | 0.834 | 0.634 | — |

因此 V 的端到端落后主要来自**做了更多工作和搬运了更多数据**，不是因为它的
单条指令吞吐率更差：V 的 IPC 反而较高，但指令数约为 G 的 2.39 倍，cache
reference 约 1.92 倍、cache miss 约 2.70 倍，branch miss 约 1.74 倍。结合
生成代码可见，V 的 p3 目录有 60 个 `.cpp`、约 134.1 MB/115.1 万行；G 的
p3 调度源有 360 个 `.cpp`、约 76.4 MB/83.6 万行。V 的 `eval_step()` 进入
Verilator 的 ico/act/NBA 迭代器，按触发向量分派几十个大型 `*_nba_sequent`/
`*_nba_comb` 函数；G 则把同一逻辑拆成按 supernode activity mask 选择的
compute/commit batch，并以窄槽和激活字节驱动跳过本步不活跃节点。也就是说，
V 当前的主要问题是**RTL 级事件触发仍被编译成大块顺序求值，无法获得 GrhSIM
的按活跃 supernode 跳过效果**，而非 all-spin 或 32 核绑定没有生效。

当前 V 包的 p3 生成代码最大瓶颈不是某一条手写规则：它是通用的 Verilator
组合/NBA 调度形态。下一步应先用同一份当前 partitioned SV 生成 V/G 两个新包
做纯 backend AB/BA，再评估两条通用路径：一是让 RepCut/Verilator wrapper
利用跨分区输入变更集合跳过确定不受影响的 `eval_step` 阶段；二是检查
Verilator 输出切分和编译目标（包括 `-march=native`）是否能在不改变语义的前提
下减少大函数中的内存流量。任何候选都必须和当前 V 线同轮交错 AB/BA，不能把本
轮 V 的 25.41 s 直接当作下一轮 baseline。

[`PMU 原始计数目录`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/verilator_o3_vs_current_grhsim_pmu_20261010/)、
[`V pair01 PMU`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/verilator_o3_vs_current_grhsim_pmu_20261010/pair01-a-verilator.perf)、
[`G pair01 PMU`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/verilator_o3_vs_current_grhsim_pmu_20261010/pair01-b-grhsim.perf)。

#### 归因口径勘误与工作范围更新（2026-10-11）

上节的全进程 PMU 包含 all-spin 等待，而且总量随运行时长增长，不能据此把
2.39 倍 instructions、1.92 倍 cache references 直接解释成模型求值工作量之比。
“主要来自做了更多工作和搬运了更多数据”的因果判断应收紧为待验证的代码层面
假设；两条线使用不同年代的包，也不能据此量化纯后端差异。后续归因只统计
指定线程的 eval 区间，并用同一步骤集合对照。

按用户明确的目标，后续优化对象是 **GrhSIM 多线程性能**，Verilator 仅作
参照。不继续实施上节提出的 Verilator wrapper 或调度优化。所有性能试验仍
只在 node030 CPU96–127 上运行，每轮重新交错测量 baseline/candidate。

### 7.96 GrhSIM 按 CPU 指令集编译：同源验证、区间 PMU 与默认接入（2026-10-11）

#### 方案与产物隔离

在当前 `wide_slot_constant_elide_20261010/package` 累计恒零探索线上，保持
7552 个源码/头文件、32 分区及调度规则相同，只增加 Clang 23 的
`-march=native`。编译机器和测试机器均为 AMD EPYC 9684X，Clang 将该选项
解析为 `znver4` 及本机可用指令集。它允许编译器为通用的移位、拼接、选择、
宽值搬运等表达式选择更合适的指令，不包含模块、分区或变量白名单，也没有
使用编译后反馈来选择优化对象。

先只重编 7418 个模型对象，复用原来的 36 个 RepCut 适配/框架对象与全部
Difftest 外壳对象；再验证实际构建方式，将该选项用于整个 7454 对象生成包。
两种候选都保持原始 archive 成员顺序和全部 **6859 个 compute 入口的 64 B
对齐**。基线 archive 重新链接得到原 ELF；进一步从相同源码完整重编通用
指令集模型，所得 archive 和 ELF 的 SHA256 仍与原基线完全一致，排除了旧
对象、编译历史、外壳重编和链接顺序差异。

- 通用基线 ELF：`b1c45f507188c31a602b0e61311b6ada4e3d5f594a30379ef293c75f08237bc0`。
- 仅模型 native ELF：`2abd2790dae809270095073769de472029a2bb2a985998cbd9b7ab82e6063294`。
- 完整包 native ELF：`92f13186afe65b688ed747cd04d70644bb0f96b036e92bf5d3258ad92cdf0afe`。

这里的 baseline 是当前累计恒零探索线，不能称作“不含此前优化的仓库默认线”。
恒零证明正式后端选项的默认状态仍遵循 §7.95，本次只采用 CPU 编译目标选项。

#### 普通 walltime：每个窗口都重测 baseline

统一使用 **node030 CPU96–127、NUMA1、Clang23/O3、N=K=32、all-spin、
Host105、ASLR off、C=100000、64 B 对齐和代码 THP**。仅模型候选完成 8 对
AB/BA；完整包候选分两个窗口各完成 4 对 AB/BA。每个窗口都重新运行两侧，
没有沿用前一轮 baseline 时间，也没有按负载或时间结果剔除成功样本。

| 候选与窗口 | baseline walltime 中位数 | candidate walltime 中位数 | 配对变化中位数 | 更快对数 |
| --- | ---: | ---: | ---: | ---: |
| 仅模型 native，8 对 | 14.235 s | 13.550 s | **−4.8045%** | 8/8 |
| 完整包 native，窗口 1 | 14.050 s | 13.500 s | **−3.9140%** | 4/4 |
| 完整包 native，窗口 2 | 14.040 s | 13.445 s | **−4.2375%** | 4/4 |
| 完整包 native，两窗口合并 | 14.040 s | 13.475 s | **−4.0553%** | 8/8 |

变化先逐对计算 `(candidate / baseline - 1) * 100`，再取中位数；不是用表中
两个时间中位数直接相除。完整包八对全部改善，单对范围为 −6.4201% 至
−3.3571%。仅模型与完整包来自不同窗口，不能把 −4.80% 与 −4.06% 的差额
解释成框架对象 native 编译的独立损益。

| 完整包两窗口合并指标 | baseline 中位数 | candidate 中位数 | 配对变化中位数 |
| --- | ---: | ---: | ---: |
| Host | 13.9615 s | 13.4005 s | −4.0557% |
| 全局 eval | 54.0565 µs/step | 51.7205 µs/step | −4.4140% |
| 全局 update | 11.4365 µs/step | 10.9190 µs/step | −4.4424% |
| 全局 input load | 2.3205 µs/step | 2.4475 µs/step | **+5.2268%** |
| 最大分区全程平均 eval | 34.4120 µs/step | 33.3005 µs/step | −3.1190% |
| 全部分区 eval 求和 | 630.7975 µs/step | 602.8200 µs/step | −4.4018% |

input load 存在约 0.127 µs/step 的回退，因此并非所有阶段均获益；eval 和
update 的节省覆盖了它，最终采用依据仍是 walltime。p10/p18/p26/p29 的全程
平均 eval 配对变化分别为 **−7.3157% / −3.1190% / −9.5007% / −5.8194%**。
这些是全程平均值，不是“该分区成为瓶颈时”的条件平均值。

三组普通性能试验共 32 次 C100000 Difftest、6 次 C100 初始化烟测通过。
每次都核实完整匿名代码大页覆盖；基线为 88 MiB，两种 native 候选为 80 MiB。
运行前后 ELF、镜像、NEMU 身份均不变。

#### 机制：eval 内的实际指令减少

7418 个模型对象的可执行节从 **94,739,076 B → 85,600,227 B（−9.646%）**。
例如 p18 `compute_batch_14` 的机器码从 27,570 B 降到 14,999 B，静态指令条数
从 6349 降到 2368；原先大量逐元素移位、截位和存储，变为 `vpsrlvq`、
`vpmovqb` 等向量操作。该函数只是解释编译器行为的例子，优化应用于所有分区。
静态体积或条数不能直接作为动态耗时占比。

另对仅模型候选做 4 对 PMU AB/BA：只替换相同的两个测量 wrapper，模型对象
保持普通性能版本原样；每 127 步采样一次，双方采用相同 **1575 步**集合。
计数取各线程 eval 前后差值，排除区间外的 all-spin 等待。四个硬件事件均有
`enabled == running`，没有复用。以下百分比为四对变化中位数：

| 分区 | instructions/eval | cycles/eval | branches/eval | branch misses/eval |
| --- | ---: | ---: | ---: | ---: |
| p10 | **−19.058%** | −9.592% | −6.458% | −8.579% |
| p18 | **−14.397%** | −5.200% | −11.247% | −7.758% |
| p26 | **−17.437%** | −10.312% | −9.097% | −6.159% |
| p29 | −8.170% | −5.340% | −0.388% | −5.296% |

PMU 测试额外 8 次 C100000 Difftest、2 次 C100 烟测全部通过。探针调用会扰动
采样步骤的时间，尤其不能将带探针的 duration 或 walltime 混入普通性能表。
这里证明的是相同步骤中 eval 执行的指令与周期下降，不是通过减少忙等指令
得出的结论，也没有据此声称每一条向量指令的独立贡献。

#### 接入与使用边界

收益在完整生成包的两个窗口均复现，故将本选项接入顶层
`build_xs_repcut_grhsim`（及选用 GrhSIM 的统一构建入口）的默认构建参数：

```make
XS_REPCUT_GRHSIM_MARCH ?= native
XS_REPCUT_GRHSIM_MODEL_CXXFLAGS ?= -std=c++20 -O3 -march=native
```

实际 Makefile 根据 `MARCH` 组装参数，并保留原有显式
`GRHSIM_MODEL_CXXFLAGS` 及新的专用参数覆盖能力。需要可跨不同 CPU 使用的
通用包时传 `XS_REPCUT_GRHSIM_MARCH=`；也可显式选择 `znver4` 等编译目标。
`native` 指编译机器的 CPU，实测收益边界为当前 Clang23/Zen4/XiangShan，
不是对其他 CPU/编译器作同幅度收益承诺。

该接入不改通用 emitter 发射的可移植 C++，不修改 Verilator 构建命令或模型，
也不把实验源码中的分区/信号名称写成生产资格规则。配置展开的默认、portable、
显式架构、旧/新 flags 覆盖检查及现有 backend 路由测试 4/4 通过。
下一步以 native 的累计 GrhSIM 候选为基础重新检查 p18 的残余活跃路径；
仍需每轮重新运行 baseline/candidate，不能直接复用这里的 13.475 s。

[`统一数据与 32 分区结果`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_slot_constant_elide_native_20261011/summary.json)、
[`构建与同源核验驱动`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/native_model_20261011.py)、
[`完整包窗口 1`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_slot_constant_elide_native_20261011/full_ab_ba_thp_r1/summary.json)、
[`完整包窗口 2`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_slot_constant_elide_native_20261011/full_ab_ba_thp_r2/summary.json)、
[`eval 区间 PMU`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_slot_constant_elide_native_20261011/pmu/summary.json)、
[`数据汇总驱动`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/native_model_report_20261011.py)。

### 7.97 Native 版本的残余关键路径重采（2026-10-11）

以 §7.96 完整生成包 native ELF `92f13186afe65b688ed747cd04d70644bb0f96b036e92bf5d3258ad92cdf0afe`
为冻结基线，继续使用 node030 CPU96–127、Host105、NUMA1、N=K=32、all-spin、
Clang23/O3/native、64 B compute 对齐、代码 THP、ASLR off 和 C100000。
本节先重新发现 GrhSIM 的关键步骤，没有沿用旧通用指令集版本的瓶颈名单；
Verilator 保持对照定位，本轮不修改或优化其代码。

四次独立 timing 运行，每 127 步采相邻两步，预先排除首对探针预热步，得到
共同的 3148 个采样步骤。每步对各分区的结束时刻取四次运行中位数，选择
最后结束者为该步瓶颈；下表 eval 是每步四次 duration 中位数在该条件集合内
的平均值。“领先次慢者”是结束时刻差，不是该分区全部 eval 都可转化为全局
加速。这些比例来自稀疏采样，不能称作对全部 200102 步的精确计数。

| 分区 | 瓶颈采样步数 | 占比 | 瓶颈时 eval | 结束时刻领先次慢者 |
| --- | ---: | ---: | ---: | ---: |
| p18 | 694 | 22.046% | 52.506 µs | 9.427 µs |
| p29 | 434 | 13.787% | 57.062 µs | 5.819 µs |
| p10 | 425 | 13.501% | 45.032 µs | 7.200 µs |
| p24 | 375 | 11.912% | 25.390 µs | 8.723 µs |
| p26 | 311 | 9.879% | 61.466 µs | 3.857 µs |
| p15 | 189 | 6.004% | 41.017 µs | 6.838 µs |
| p27 | 175 | 5.559% | 60.490 µs | 3.614 µs |

随后固定 p18 的 694 个瓶颈步及其 675 对去重相邻步，分别再做四次 cycles
和四次 branch-misses 地址采样。计数器仅在该 worker 的选定 eval 区间启用，
排除 all-spin 等待；全部区间 `enabled == running`，没有丢样或 throttle。
下表仅包含真正的瓶颈步，不包含为了观察工作转移而同时采集的相邻沿。

| 区域 | 周期样本 / 占比 | 误预测样本 / 占比 |
| --- | ---: | ---: |
| compute | 341 / **83.374%** | 232 / 59.033% |
| 模型内部 commit | 51 / **12.469%** | 151 / **38.422%** |
| eval 派发 | 11 / 2.689% | 6 / 1.527% |
| 其他 | 6 / 1.467% | 4 / 1.018% |

单个 c256 提交函数占 48/409 周期样本、127/393 误预测样本，即
**11.736% / 32.316%**。最大的单个 compute 函数 b17 只有 10/409 周期样本
（2.445%），其后是 b143/b210/b234 各 7 个。compute 的总成本明显更大，
但没有新的单个巨型热函数；只减少一小类 commit 分支不能预报较大的 walltime
收益。这里的 commit 是模型内部状态提交，不是 RepCut 跨分区 update 通信。

对 13 个热函数增加行号信息重编译，逐个核验原有 allocated section 字节和
重定位完全相同，再将测得的函数内地址映射回源码。compute 落点包括输入拆位、
布尔值读取和更新、变化条件归约、active mask 通知以及宽输出比较；c256 仍包含
写使能、状态变化比较、已有 same-reader 分组和 active/producer-dirty 通知。
因此后续规则应处理这些可复用结构，不能把采样命中的分区、模块或信号名作为
优化资格。地址事件存在 skid，源码落点是热区域线索，不能当作精确的出错分支
归属；这些样本占比也不能直接乘全机 walltime 来算收益。

本组发现与地址归因共 **12 次 C100000 Difftest、3 次 C100 烟测**，全部通过。
timing/IP 仅替换各自的 wrapper 对象，模型对象保持冻结版本；普通 ELF、输入、
映射源码身份前后不变。后续候选需分别重测 baseline/candidate 的普通 AB/BA，
并在这组独立冻结步骤上检查实际周期、指令和误预测变化；探针时间不进入普通
性能收益表。

本轮结束时继续使用 §7.96 的完整包 native 基线。后续优先复查 compute 中
值槽读写、变化检测和激活传播的实际重复工作，先审计已有分组规则的覆盖，
再选择通用消冗余模式；采用依据仍是新一轮普通 walltime AB/BA 与固定关键
步骤的实际执行成本，不以源码判断层数或分支条数代替收益。

[`32 分区瓶颈与采样汇总`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/native_residual_20261011/summary.json)、
[`冻结步骤标签`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/native_residual_20261011/labels.json)、
[`周期地址采样`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/native_residual_20261011/ip_cycles_summary.json)、
[`误预测地址采样`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/native_residual_20261011/ip_branch-misses_summary.json)、
[`机器码与源码一致性核验`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/native_residual_20261011/code_audit.json)、
[`复现驱动`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/native_residual_20261011.py)。

### 7.98 Compute 共享变化条件：通用原型与 native 双窗口验证（2026-10-11）

继续使用 §7.96/§7.97 的完整包 native 基线，未叠加其他候选。性能运行均在
node030 CPU96–127、NUMA1、Host105、N=K=32、all-spin 下进行，保持
Clang23/O3/native、64 B compute 对齐、代码 THP、ASLR off、C100000。
本轮完成一个通用消冗余原型，确认实际执行指令减少及小幅整机收益；暂不改默认。

#### 改写什么，以及覆盖多少

已有 deferred group 会汇总多个值的“是否变化”，再精确激活对应消费者。
但同一批变化标志可能同时属于多个组，导致相同归约分别执行。新原型按
**完全相同的组成员关系**聚合来源：例如两组都需要 `d0 | … | d5`，先计算
一次共同结果，再分别并入两组各自的其余条件。仍使用普通 Boolean 归约，
不把结果扩成整数掩码，也不增加任何消费者激活。

资格只看结构：至少三个来源、至少两个组，改写前后的源码 OR 更新数至少
相差四次；每个来源必须是唯一的不可变 Boolean 变化标志，相关更新连续，
所有组均在贡献收集结束后才消费。原值计算、比较、存储与条件执行留在原位，
共同结果在原 flush 所在作用域合并；中途读取、未知副作用等结构保守回退。
没有按分区、RTL 模块、信号或本轮性能反馈筛选。

统一扫描命中 **32 个分区、2405 个文件、16899 个共享组**。这些位置的
归约更新从 **394499 降至 209812**，源码操作数少约 46.8%；这不是整个
compute 的指令下降比例。重编后 2362 个 archive 成员改变，其余成员保持
原字节；模型可执行段合计 **85954809 → 85231310 B（−0.842%）**。
全部 6859 个 compute 入口仍为 64 B 对齐，模型成员布局、RTL、分区、框架
通信代码及 Verilator 均未修改。候选 ELF 为
`c7e0d7aab5a3cefc002ce0e24da79391117234dda93c53d57c772e7e56f42878`。

#### 同轮普通 AB/BA

两个独立窗口各八对，每个窗口均重新运行 baseline/candidate，未引用历史
baseline 时间。下表百分比是 **16 对逐对变化的中位数**，所有成功样本保留。

| 指标 | 配对变化中位数 | 候选更快对数 |
| --- | ---: | ---: |
| walltime | **−0.641%** | 10/16 |
| Host | −0.605% | 10/16 |
| 全局 eval | −0.799% | 11/16 |
| 全局 update | **+1.490%** | 2/16 |
| p18 全程平均 eval | −1.446% | 14/16 |
| 各分区平均 eval 合计 | −0.397% | 10/16 |

按所有普通运行的均值计算，walltime 为 **12.532500 → 12.483750 s**，
少 **48.75 ms，即 0.389%**；这与配对中位数 0.641% 是不同统计量。
两个窗口的 walltime 配对中位数分别为 −0.641% / −0.475%。AB、BA 顺序
仍有明显差异，因此同时保留八个完整 ABBA 块的统计：六块改善；以块为单位
做 50000 次固定种子的 bootstrap，均值比变化的探索性 95% 区间为
约 **[−0.701%, −0.055%]**。块数仍少，不把这个区间当作泛化保证。

#### 固定瓶颈步骤上的实际成本

另做四对 PMU AB/BA，使用 §7.97 独立发现并冻结的瓶颈步骤，不按候选耗时
重新选择。计数器只覆盖每个 worker 的 eval 区间，全部 `enabled == running`；
探针时间不计入普通 walltime 表。以下为四对变化中位数。

| 分区 | 固定瓶颈步骤数 | 动态指令 | CPU 周期 | 区间 eval 时间 |
| --- | ---: | ---: | ---: | ---: |
| p10 | 425 | −0.401% | −0.858% | +0.008% |
| p18 | 694 | **−1.232%** | **−0.860%** | −1.026% |
| p24 | 375 | −0.309% | +0.068% | +2.151% |
| p26 | 311 | −0.879% | −0.900% | −0.577% |
| p27 | 175 | −1.121% | −1.441% | −1.431% |
| p29 | 434 | −0.025% | −2.070% | −1.881% |

p18 的条件指令均值在四次运行取中位数后为 222176.32 → 219438.12，
每个选定步骤约省 2738 条指令；四对指令与周期均下降，支持确实消除了工作。
p29 指令几乎没有变化，不能把其约 2% 的周期下降都归因于本规则。
源码局部操作数下降 46.8% 后，整个瓶颈 eval 只少约 1.2% 指令，说明本次
选中的重复归约仅占实际工作的一小部分。

本轮 **40 次 C100000 Difftest、6 次 C100 初始化检查**全部通过。独立
Clang23/O0、O3 的 ASan/UBSan 对照共 **1048576 次有序状态转换**，覆盖
条件执行、输入不变、预置活动位、重复 eval 和混合共享/独有贡献；另检查
可变标志、中途读取和更新间副作用的拒绝路径。源文件、ELF 和输入身份复核通过。

**决策：保留为通用候选，生产默认与后续控制基线仍维持 §7.96。** 本轮有
小幅正向收益，但 update 增长部分抵消了 eval 改善，且尚未解释其来源。
通信量、通信对象代码未改，不能据此称通信量增加；后续应定位哪些 update
路径增长、区别实际工作量与进入阶段时的缓存/线程状态，再决定是否正式接入。

[`最终核验与完整数据`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/compute_change_cohort_native_20261011/verification.json)、
[`普通窗口一`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/compute_change_cohort_native_20261011/ordinary_a/summary.json)、
[`普通窗口二`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/compute_change_cohort_native_20261011/ordinary_b/summary.json)、
[`固定步骤 PMU`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/compute_change_cohort_native_20261011/pmu/summary.json)、
[`通用改写器`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/compute_change_cohort_native_20261011.py)、
[`独立语义检查`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/compute_change_cohort_checks_20261011.py)。

#### 增量：update 抵消项的归因与同堆地址对照（2026-10-11）

本轮继续比较上文的两个冻结 ELF：A 为完整包 native 基线
`wide_slot_constant_elide_native_20261011/full_native/emu`，B 为只增加共享变化
归约的 `compute_change_cohort_native_20261011/candidate/emu`。未更换 RTL、
分区、输入或编译选项。性能仍只在 node030 CPU96–127、NUMA1、Host105、
N=K=32、all-spin、Clang23/O3/native、64 B compute 对齐、代码 THP、ASLR off
下运行。每组比较重新执行双方的 C100000 AB/BA，没有借用上一窗口的基线时间。

**结论：没有发现 update 工作量增加；此前 +1.490% 不能当作固定代价。**
新窗口仍能看到小幅 update 抵消，但幅度随窗口及地址条件变化。普通版本和
恢复相同堆地址后的版本都保留小幅整机收益。现有证据尚不能把余下差异确定归因
到某一种缓存、频率或一致性机制，不把“没有更多指令”直接等同于“纯噪声”。

**先确认比较的是同一条 update 路径。** 两个 archive 的 common/load/eval/
update 四个 wrapper 对象逐字节相同；链接后全部 32 个 update 函数的入口地址
和大小也相同。238948 B 正常路径机器码完全一致。每个函数仅有末尾断言失败
路径的三个字符串 RIP 相对位移不同，三个字符串内容不变，正常运行不经过这些
指令。因此没有 update 算法变复杂或其正常代码直接重排的解释。

逐步时序及 PMU 只重编 common 对象，在原 update 函数调用外侧包探针，原来的
update/eval/load 及模型对象不动。每次正式运行采样 3148 个相同步号；时序先做
四对，再冻结每步四次基线完成时刻的中位数所对应的最后完成者，独立用于 PMU。
这批代表步骤中 p16 占 1845 步、p20 占 1233 步，合计 97.776%；按各次实际
最后完成者直接计数，基线两者合计 94.838%，两种口径不混用。

全局 update 按每个采样步精确拆成“最后完成线程的进入时间、该线程执行时间、
完成后的 Host 收尾”三项之和，四次运行及全部采样步的算术均值如下。这里是诊断时间，
不是普通 ELF 的性能成绩。

| update 组成 / µs | A | B | B−A / ns |
| --- | ---: | ---: | ---: |
| 最后完成线程的进入时间 | 1.204091 | 1.144286 | −59.805 |
| 该线程的执行区间 | 8.753456 | 8.792246 | +38.790 |
| Host 收尾 | 0.730310 | 0.746674 | +16.364 |
| 全局阶段 | 10.687858 | 10.683207 | −4.651 |

全部线程进入时刻的最大差距也从 1.080724 降到 0.908695 µs，四对均减少。
故这一组没有支持“进入 update 更晚、更分散”是退化原因。执行与收尾有小幅
增长，但被更早进入抵消；探针会影响短阶段的执行状态，不能据此替代普通复测。

**实际执行成本。** core 和 data 两组各四对 PMU，均只覆盖 update 调用区间，
包含两侧相同的固定探针开销，所有样本 `enabled == running`。以下为所有采样
步骤的四对变化中位数；指令来自 core 组，数据填充来自独立的 data 组。

| 分区 | update 动态指令 | 数据缓存填充数 | 跨 CCX 缓存填充数 |
| --- | ---: | ---: | ---: |
| p16 | +0.00038% | +0.00336% | −0.12351% |
| p19 | +0.00043% | −0.24408% | −0.83002% |
| p20 | −0.00339% | −0.23697% | +0.95784% |
| p23 | −0.00053% | −0.18623% | +1.63509% |

数据填充指 load 需要从缓存层次获取的 cache line，跨 CCX 表示来自其他缓存簇，
不能把它们直接解释为 RTL 通信字节。事件分别为本机 perf 元数据中的
`ls_any_fills_from_sys.all`（event `0x44` / mask `0xff`）及 `remote_cache`
（`0x44` / `0x14`）。未见 p16/p20 的填充总数系统性增加。

固定瓶颈步骤上，p16 的指令约 6811.7 条，p20 约 6784.2 条，两侧基本一致。
core 组 p16 误预测约 45.23→42.66 次，p20 约 13.76→14.82 次；并非两者
一起出现大量新增误预测。周期的小幅增加与区间耗时变化也不完全同向，例如
p16 瓶颈步 core 周期配对 +1.240%，区间时间 −0.350%。这些数据排除了明显
新增工作，尚不足以证明某个具体微架构原因。

**新跑八对普通 AB/BA。** 下表同时给出均值比与配对变化中位数，避免把两者混为
一个指标；所有成功样本均保留。

| 指标 | A 均值 | B 均值 | 均值比变化 | 配对变化中位数 |
| --- | ---: | ---: | ---: | ---: |
| walltime / s | 12.862500 | 12.757500 | **−0.816%** | **−0.625%** |
| Host / s | 12.786125 | 12.682625 | −0.809% | −0.625% |
| 全局 eval / µs | 48.922000 | 48.477750 | −0.908% | −0.812% |
| 全局 update / µs | 10.796125 | 10.835375 | +0.364% | −0.134% |

walltime 为 7/8 对更快、1 对在 0.01 s 的时间记录分辨率下持平，四个完整
ABBA 块均改善；Host 为 8/8 对更快。p18 全程平均 eval 均值少 1.180%，
配对中位数 −1.262%，7/8 对更快。update 的四个 ABBA 块依次为
+1.585%/−0.562%/+0.417%/+0.023%，未稳定复现此前 +1.490% 的幅度；
这也不等于否定前一窗口确实观察到的增长。

**一次有界的堆地址因果对照。** B 代码较小，ELF 末端页边界提前了
733184 B（`0xb3000`）。ASLR off 并不固定不同 ELF 的堆起点：普通运行的
`/proc/<owned-child>/maps` 确认 A 为 `0x55555b189000`、B 为
`0x55555b0d6000`。诊断版 32 个 adapter 地址同样整体前移，12 个从堆分配
的模型随之移动，其余 20 个 mmap 模型的采样地址相同。

因此构造 H：只在 B 的最后一个可写 PT_LOAD 与 `.bss` 中增加未使用的零填充
尾部，使堆起点恢复到 A。仅修改两个 ELF 大小字段，所有已有函数/节的地址及
内容保持 B 原样；不移动代码，不修改生成器，不把填充当作优化。普通运行验证
堆起点符合预期；诊断初始化验证全部 32 个 adapter、`in_0`、`out_0` 地址与
A 一致。然后做两组相互独立的新 AB/BA，各四对：

| 对照 | walltime 均值 / s | walltime 均值比 / 配对中位数 | update 均值比 / 配对中位数 |
| --- | --- | ---: | ---: |
| B → H，只改变堆起点 | 12.732500 → 12.780000 | +0.373% / +0.871% | −0.625% / −0.715% |
| A → H，堆起点相同 | 12.677500 → 12.605000 | **−0.572% / −0.670%** | +0.678% / +0.924% |

B→H 的两个完整 ABBA 块 walltime 方向相反（+1.580%/−0.820%），不据四对
中的局部 update 下降宣称找到了稳定修复。A→H 的两个 ABBA 块 walltime 均
改善（−0.669%/−0.474%），eval 均值少 0.923%，但 update 仍略增；所以堆
地址变化不是 update 抵消的充分解释，归约候选的小幅净收益也并非只靠该地址位移。
这只控制了堆起点及模型采样地址，没有宣称全部虚拟/物理缓存布局都已相同。

本轮新增 **56 次 C100000 Difftest、14 次 C100 初始化检查**全部通过，其中
普通性能 32 次、时序/PMU 诊断 24 次。代码 THP 完整覆盖、固定输入/ELF 身份、
32 路映射及 all-spin 设置复核通过；没有按性能筛除样本。

**决策：共享归约继续保留为通用候选，不增加堆填充，不改生产默认。** 可以继续
推进它在正式生成器中的结构化接入，并对默认生成产物做独立 AB/BA；目前不把
update 抵消归咎于通信量增加，也不为解释不到 1% 的整机差异展开地址参数搜索。
尚未证明的具体硬件机制保留为限制；本轮没有修改 Verilator 或生产通信逻辑。

[`本轮最终核验与全部汇总`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cohort_update_path_20261011/verification.json)、
[`原普通 ELF 八对`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cohort_update_path_20261011/ordinary_original/summary.json)、
[`逐步时序分解`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cohort_update_path_20261011/timing/summary.json)、
[`update 正常路径一致性`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cohort_update_path_20261011/static_audit.json)、
[`core PMU`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cohort_update_path_20261011/pmu/core_summary.json)、
[`data PMU`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cohort_update_path_20261011/pmu/data_summary.json)、
[`相同堆起点 A/H 对照`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cohort_update_path_20261011/ordinary_heap_baseline/summary.json)、
[`单独 B/H 地址对照`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cohort_update_path_20261011/ordinary_heap_candidate/summary.json)、
[`探针驱动`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cohort_update_path_20261011.py)、
[`地址对照驱动`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cohort_heap_control_20261011.py)、
[`汇总驱动`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/cohort_update_report_20261011.py)。

### 7.99 共享变化归约接入正式 GrhSIM emitter（2026-10-11）

#### 接入范围与功能检查

延续 §7.98 的候选，将选择规则放入 `grhsim_cpp.cpp` 的结构化代码生成路径。
新 attribute 为 `shared_deferred_activation`，环境变量为
`WOLVRIX_GRHSIM_SHARED_DEFERRED_ACTIVATION`，初始默认关闭，attribute 优先。
按同一 compute supernode 内源值所属的**完整 deferred 组集合**进行分组；只选择
1..64 bit Logic 源值，要求共同来源数 `S >= 3`、目标组数 `G >= 2`，且
`S*(G-1)-G >= 4`。不匹配分区、模块、信号名称或 profile。

来源变化时只累计一次共同 Boolean 条件，在原通知阶段之前合回各组；各组独有
来源和未被组覆盖的直接目标保持原处理。局部变量不进入模型布局，不增加通信。
packed/direct 表示优先保留其路径；未匹配这些表示的 supernode 可回退到共享
归约。合并先于 predicate materialization、profile/bitmap 观察和最终激活，
避免只优化普通模式却破坏诊断模式。Verilator emitter 和通信实现未改。

四项 focused 测试通过：新增 shared 测试，以及已有 packed/direct/materialized
回归。新增测试包含 14 个生成/执行配置、共 57344 次 eval，覆盖显式开关及环境
变量优先级、门槛正反例、共享与独有贡献、直接残余目标、随机输入、重复 init/eval、
fullpass、拆分 helper、perf/profile、bitmap/union 和 packed/direct 组合；开启
模式另经 Clang23/O3 ASan/UBSan 检查。测试已注册到 CTest。

使用私有构建的 emitter 从同一 `partitioned.json` 完整生成关闭/开启两套代码。
关闭版本已核对 **7549 个源码/头文件**与 `formal/on_v3` 快照逐字节相同。
另 3 个 `wolvi_repcut_grhsim_sim*` wrapper 文件在旧快照中带有既有的 worker
输入加载及 conditional-copy 改写，不能把这部分配置差异混入本轮性能对照。
因此本轮继续冻结 §7.96 的完整 native 基线及 wrapper，只将正式 emitter 的
开启/关闭差量与已有全部保留改写合并，并要求反向应用该差量能逐字节恢复基线。
这是一条保留既有优化的受控接入验证线，**不等同于无环境选项的全默认包**。

性能阶段继续只在 node030 CPU96–127、NUMA1、Host105、N=K=32、all-spin、
Clang23/O3/native、64 B compute 对齐、代码 THP、ASLR off 下进行新跑双方
C100000 AB/BA；接入阶段尚未改变生产默认，结果在本节继续追加。

[`实现说明`](../../wolvrix/docs/emit/grhsim-scheduling.md#实验性共享-deferred-变化归约)、
[`接入与复核驱动`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/shared_deferred_formal_20261011.py)、
[`focused 测试结果`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/shared_deferred_formal_20261011/generator/tests.json)、
[`关闭版本一致性`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/shared_deferred_formal_20261011/disabled_audit.json)。

#### 完整接入验证与新跑 AB/BA 结论

最终选择规则进一步依据已有 lowering 信息，只计入仍会独立生成标量变化通知
的来源：排除初始化常量、存储别名、直接状态视图、被已有规则吸收的操作/循环
和特殊赋值路径。新增“常量参与 IR 依赖但不应帮助通过收益门槛”的回归；四项
focused 测试再次全部通过。该判断来自 IR 与生成器自身的 lowering 计划，
不使用编译后反馈或分区/变量白名单。

完整生成及合并后的 **7552 个源码/头文件**核对通过；本次差量修改 **2437 个
compute 源文件**，覆盖全部 **32 个分区、17101 个共享组**。每组实际生成的
贡献数均复核满足门槛。选中来源相关的源码 OR 累计由 **399759 → 212573**，
减少 187186 次、约 **46.825%**；它描述该局部模式的静态语句数，不是整机
动态指令数。原型为 16899 组，正式实现也能覆盖原型文本识别未纳入的组，
因此两者并非逐文件相同。

既有优化全部保留：三方合并时只组合互不重叠的改写，包括一处紧邻输出存储
转发的新增归约语句；反向应用正式差量后，每个修改文件都逐字节恢复为原基线。
头文件、wrapper 和其对象代码保持控制版本，未改变模型布局或通信算法。
2437 个文件以 Clang23/O3/native 增量重编并重新链接，用时 **128.131 s**，
其中 2386 个 archive member 变化；此时间不是整个工程从零编译时间。
模型 archive 的可执行节合计 **85954809 → 85228346 B（−0.845%）**，
全部 6859 个 compute 入口的 64 B 对齐检查通过。

以下记 A 为 §7.96 完整保留优化 native 基线，B 为 §7.98 生成后改写的共享
归约原型，F 为本节正式 emitter 接入版。三者分别对应冻结 ELF：

| 版本 | ELF 路径（相对 `active_dispatch_20261003/`） | SHA256 |
| --- | --- | --- |
| A | `wide_slot_constant_elide_native_20261011/full_native/emu` | `92f13186afe65b688ed747cd04d70644bb0f96b036e92bf5d3258ad92cdf0afe` |
| B | `compute_change_cohort_native_20261011/candidate/emu` | `c7e0d7aab5a3cefc002ce0e24da79391117234dda93c53d57c772e7e56f42878` |
| F | `shared_deferred_formal_20261011/candidate/emu` | `5dbdc2943adc32f27f0f00a9282b3a5d6701302d8ff1ef67525cb6b355c568e3` |

**A/F 新跑八对 C100000 AB/BA。** 全部使用本节所列固定运行条件，双方均重新
运行，不借用历史基线时间。均值比为 `(F 均值 / A 均值 − 1) × 100%`；最后
一列则先逐对计算百分比、再取中位数，二者是不同统计量。

| 指标 | A 均值 | F 均值 | 均值比变化 | 配对变化中位数 |
| --- | ---: | ---: | ---: | ---: |
| walltime / s | 12.142500 | 12.077500 | **−0.535%** | **−0.413%** |
| Host / s | 12.070875 | 12.010375 | −0.501% | −0.420% |
| 全局 eval / µs | 46.965875 | 46.625125 | −0.726% | −0.668% |
| 全局 update / µs | 9.438375 | 9.469875 | +0.334% | −0.021% |
| 各分区全程平均 eval 合计 / µs | 536.967625 | 533.660500 | −0.616% | −0.667% |

walltime 为 6/8 对改善，四个完整 ABBA 块的均值比依次为
**−0.777% / −0.451% / −0.660% / −0.249%**，均为正向收益。AB、BA 单独看
仍有明显顺序效应：walltime 配对中位数分别 −0.041% / −1.237%；因此保留
全部成功样本和完整块统计，结论按小幅探索性收益表述。update 均值有轻微抵消，
不能把它解释为新增通信工作；本轮沿用同一套通信对象代码。

**B/F 另新跑四对 C100000 AB/BA。** 用于检查正式接入是否丢失原型收益。
以下百分比分别使用该独立窗口自己的基线，不能与上一表跨窗口拼接或相加。

| 指标 | B 均值 | F 均值 | 均值比变化 | 配对变化中位数 |
| --- | ---: | ---: | ---: | ---: |
| walltime / s | 12.032500 | 11.955000 | **−0.644%** | −0.661% |
| Host / s | 11.958250 | 11.885250 | −0.610% | −0.591% |
| 全局 eval / µs | 46.419500 | 46.031500 | −0.836% | −0.778% |
| 全局 update / µs | 9.489250 | 9.551000 | +0.651% | +0.773% |

walltime 3/4 对改善，两个完整 ABBA 块分别 −0.666% / −0.622%。该窗口没有
观察到正式接入的净退化；样本较少且有顺序效应，不能将全部额外差异确定归因
于多出的 202 个共享组。源码 OR 大幅减少、整机只改善约半个百分点，仍说明
这部分重复归约只占实际总工作的较小部分。

本轮 **24 次 C100000 Difftest、4 次 C100 初始化检查全部通过**；所有正式运行
的 golden 签名、代码 THP 完整覆盖、输入/ELF 身份及头文件/生成源码身份检查
通过，未按性能筛除样本。功能、结构与两组性能对照均已完成。

**决策：接受 F 为后续同一完整保留优化验证线的控制基线；生产 emitter 的
`shared_deferred_activation` 默认仍为 false。** 该验证线后续生成应显式启用
`WOLVRIX_GRHSIM_SHARED_DEFERRED_ACTIVATION=1`，继续携带已保留的其他改写；
后续比较仍要重新运行双方 AB/BA。当前证明的是这一完整组合上的小幅收益，
尚未将“无环境选项、无既有生成后改写”的纯生产默认组合做性能对照，因此
不把本轮结论扩大为全局默认组合已经验证。Verilator 路径未改。

[`最终核验、完整 32 分区数据与决策`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/shared_deferred_formal_20261011/verification.json)、
[`A/F 八对完整数据`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/shared_deferred_formal_20261011/ordinary_a/summary.json)、
[`B/F 四对完整数据`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/shared_deferred_formal_20261011/ordinary_prototype/summary.json)、
[`源码与反向合并核验`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/shared_deferred_formal_20261011/candidate/scan.json)、
[`构建记录`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/shared_deferred_formal_20261011/candidate/build.json)。

### 7.100 宽输入 previous snapshot 的安全审计（2026-10-12）

#### 先前候选为何不能直接接入

上一轮热点分析看到 p24 的宽输入比较和 `prev_in_*` 快照复制都调用了 libc 的
整段比较/复制。一个初步实验只解析 `model_eval.cpp` 的输入变化 guard，把 guard
中出现的少数 word 同时用于比较和快照；它在短测中明显变快，但这个判据没有覆盖
后续调度源文件中的输入读取，因此不能作为通用优化。

对正式生成的 p24 代码复核后，`repcut_port_31` 的数组长度是 **3153 个
uint64 word**。eval guard 的激活增量只列出 **116 个 word（3.68%）**，但
`grhsim_Gpart_24_model_sched_*.cpp` 的实际读取覆盖 **3152/3153 个 word**；
加上 eval 中的边界 word 后，整个生成模型的依赖并没有稀疏性。只改 eval guard
会在未列出的 word 变化时错误地跳过调度计算，故该实验候选已删除，不保留其
二进制或性能结果。

#### emitter 中保留的通用规则

在 `grhsim_cpp.cpp` 中加入了一个严格的结构化判据，用已有的 input-bit
dependency mask 推导是否可以安全地同时缩减“变化比较”和“previous snapshot”
复制。只有满足以下条件才生成 `always_inline` 的 word compare/copy helper：

* 输入是至少 128 word 的 Logic 数组；
* 所有 input consumer head 都有完整的已证明 mask，不能存在未覆盖的 head；
* 排除 event/commit 输入以及 fullpass 特殊路径；
* 所有 head 的 demanded word 并集不超过数组的 5%。

不满足条件时完全保留原来的数组比较和复制。规则只依据 lowering 依赖，不匹配
分区、模块、信号名或 profile；即使 input-bit activation 选项关闭，也可以独立
进行这项安全判定，而原有 activation 行为仍只在显式开启时使用 mask。

#### 验证与结论

修改后的私有 emitter/library 构建通过；shared、packed、direct、materialized
四项 focused emitter 回归全部通过。对同一 `partitioned.json` 的真实生成检查
确认 XiangShan 当前没有满足上述全部条件的宽输入，因此本 workload 的默认生成
代码没有新增 helper，运行时路径保持不变。此前“只根据 eval guard 缩减快照”的
短测收益不再作为性能结论。

下一步应从 Host 输入边界是否能提供可信的 dirty-word 信息入手；在没有这种信息
之前，不能把 eval guard 的局部稀疏性当成整个调度模型的依赖范围。

[`本轮 emitter focused 回归`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/shared_deferred_formal_20261011/generator/tests.json)。

### 7.101 复用通信变化信息并精简输入旧快照（2026-10-12）

#### 机制与适用边界

沿 §7.100 的方向完成了一个完整的 generated-package 原型。RepCut 的 GrhSIM
通信 helper 本来就逐 8-word 块比较目的输入与新输出，再复制变化块；现在复用
这次完整比较的结果，为对应输入设置一个 `changed` 标记。下次 eval 使用该
标记替代整数组比较，保留原有的逐位增量激活表达式、未掩码激活以及全部计算。
每个标记独占一个 64 B 缓存行，避免不同生产线程写同一行；eval 完成后清零。
沿用现有 phase barrier 交接数据，不增加线程、锁或独立同步阶段。

选择规则统一作用于所有分区：输入至少 128 个 uint64 word、有且仅有一个
完整宽度的内部通信发布点、没有 top/constant 输入加载写入。原型覆盖 **22 个
分区、78 个输入、40,331 个 word**，没有分区/模块/信号白名单。受控 package
的发布和 eval 顺序保证每个目标输入在相邻两次 eval 之间只发布一次；另用带
断言的版本在真实 C10000/C100000 上逐次核对标记与原整数组比较完全相等。

有了完整变化标记后，才进一步分析 `prev_in_*` 的实际读取。扫描同一模型全部
生成源文件，排除初始化写入，并剔除已替代的整数组比较；只有剩余读取均为
静态下标、所需 word 不超过完整数组的四分之一时，才缩减该输入的旧快照。
相邻下标合并为固定长度复制。共有 **27 个输入**满足条件，每次 eval 的逻辑
快照复制量从 **25,531 → 1,163 word（−95.445%）**。这是这些选中快照的复制量，
不是整个模型的存储量，也不代表实测 DRAM 流量下降相同比例。

这解决了 §7.100 的安全问题，而没有假设计算只读取少数输入位。例如 p24 的
3153-word 输入，即使变化发生在增量 guard 未列出的 word，通信仍会发现变化，
原来的未掩码激活仍执行；后续 schedule 读取的**当前输入仍是完整数组**。只有
用来判断逐位变化的旧值缩到 116 word。旧快照的读取范围与当前输入的读取范围
必须分开判断。

原型在 adapter 增加了仅供受控 package 调用的 `eval_tracked()`，模型保留普通
`eval()` 路径。精简快照后的跟踪路径要求持续使用上述发布协议；不能在没有
重新初始化的情况下任意混用直接输入写入、普通 eval 与跟踪 eval。正式接入时
应将该契约封装为固定的内部模式，并覆盖初始化、重复发布和输入别名等边界。
上述数据采集时仍是隔离原型，尚未接入生产 emitter 或改变默认配置；正式接入的
验证见本节后续记录。Verilator 的生成行为未改变。

#### 新跑的性能与功能验证

控制版本为 §7.99 的完整保留优化线 **F**，不是历史 Verilator 或早期 GrhSIM。
全部性能测试仍在 **node030 CPU96–127、NUMA1、N=K=32、all-spin、Clang23
O3/native、64 B compute 对齐、代码 THP、关闭 ASLR、C100000** 下运行。
两轮分别新跑四对、八对 AB/BA，每一轮都重新运行双方，没有借用上一轮 baseline。

首轮四对 walltime 均值 **10.280000 → 10.117500 s（−1.581%）**，4/4 对改善。
以下是随后独立八对复测的均值；变化按 `(候选均值 / F 均值 − 1) × 100%` 计算，
不能与首轮百分比相加。

| 指标 | F 均值 | 候选均值 | 均值比变化 |
| --- | ---: | ---: | ---: |
| walltime / s | 10.346250 | 10.093750 | **−2.440%** |
| Host / s | 10.274125 | 10.025375 | −2.421% |
| 全局 input-load / µs | 1.902750 | 2.027250 | +6.543% |
| 全局 eval / µs | 38.718125 | 38.119625 | −1.546% |
| 全局 update / µs | 9.166625 | 8.450000 | −7.818% |
| 各分区平均 eval 合计 / µs | 443.502250 | 433.927625 | −2.159% |
| p24 全程平均 eval / µs | 21.519000 | 15.509500 | **−27.926%** |
| p18 全程平均 eval / µs | 25.494625 | 25.463750 | −0.121% |

八对 walltime 全部改善，逐对变化中位数 **−2.300%**；四个完整 ABBA 块的均值比
依次为 **−1.948% / −2.675% / −2.845% / −2.292%**。两轮合计 12/12 对改善，
按当前 workload 上约 **1.6%–2.4%** 的探索性收益保留原型，不把单轮幅度解释为
固定不变的收益。

p24 的局部收益很明显，但 p18 基本未变，说明最大耗时部分尚未被整体解决。
在八对窗口中，eval/update 合计每 step 少约 1.315 µs，input-load 增加约
0.125 µs，净阶段节省约 1.191 µs；这与约 200102 step 的 Host 改善量级一致。
update 的下降是观测结果：逻辑通信载荷没有减少，但输入比较接口及快照访问
发生了变化。尚未用 PMU 分离缓存影响与代码/数据布局影响，不能全部归因于某项
具体微架构机制。

两轮性能窗口的 **24 次 C100000 Difftest、4 次 C100 检查全部通过**；额外的
C10000/C100000 一致性验证也通过。THP 完整覆盖、ELF/输入身份、所有保留样本的
golden 签名核验通过，没有按性能过滤样本。候选只替换 47 个 archive member，
compute/commit schedule 对象保持原样，6859 个 compute 入口仍满足 64 B 对齐。
候选增量编译和链接用时 27.649 s，此数不是全工程从零编译时间。

冻结候选为 `active_dispatch_20261003/dirty_input_bridge_20261012/sparse/emu`，
SHA256：`2eaaf0b14cf31f0e0d5844f1abd6e8d0b01fb7fd60a94cef325befa1d9ef1e78`。
这两轮数据仅对应生成后原型；正式 package/emitter 接入后另行重新生成、重编
并进行独立 AB/BA，结果分开列在下文，不能把原型数据当作默认配置的验证。

[`统一核验、结构统计与完整分区数据`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_input_bridge_20261012/verification.json)、
[`四对首轮数据`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_input_bridge_20261012/sparse/ordinary_c100000_4pairs/summary.json)、
[`八对复测数据`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_input_bridge_20261012/sparse/ordinary_c100000_8pairs/summary.json)、
[`原型与复测脚本`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_input_bridge_20261012.py)。

#### 正式 package/emitter 接入与重新生成

已实现 `input_dirty_tracking` / `WOLVRIX_GRHSIM_INPUT_DIRTY_TRACKING`，当前默认关闭，
本次完整保留线显式开启。package 根据完整宽度内部发布关系选择输入，排除同一
ValueId 绑定多个输入端口的情形，并把有序的端口映射传给 adapter 和模型。
快照判据直接使用 emitter 的输入激活掩码与事件分类信息，统一作用于所有分区。
adapter 负责设置/消费标记，模型固定首次 eval 的跟踪模式；普通/跟踪模式之间
切换须先 `init()`，否则抛出 `logic_error`。未跟踪输入保留原有比较路径。

使用同一个 `partitioned.json` 及同一组既有选项，分别关闭/开启新选项重新生成。
关闭时，全部模型和 adapter 源文件与 §7.99 正式生成版本逐字节一致。开启时仍
选择 **22 个分区、78 个输入**，27 份稀疏快照的每一个 word 下标与原型一致，
复制量仍为 **25,531 → 1,163 word**。既有完整保留线 F 的其余改动保留在双方；
新 emitter 增量应用和反向撤回都经过逐文件核对。本轮衡量的是对 F 的增量，
不代表所有出厂默认选项组合都已经完成性能验证。

为避免混用类定义不同的旧对象，重编受影响模型、全部 adapter 和 wrapper，共
**5,396 个 C++ 源文件**；编译和链接用时 **221.855 s**。最终 69 个 archive
member 改变，compute/commit 调度源码与对象的已分配代码/数据 section 均未改变，
6,859 个 compute 入口保持 64 B 对齐。正式候选 SHA256 为
`203e9fb21f633ddc8f74115ebd9e9ac55438a9b07ec5e5d8bd7964fc4a6fe6e4`。

三个正式 CTest 全部通过：`emit-grhsim-repcut-package`、
`emit-grhsim-cpp-input-bit-activation`、`emit-verilator-repcut-package`。
新增 fixture 覆盖 8200-bit 跨分区输入、完整计算和稀疏切片、未跟踪的顶层输入、
输入别名、末尾非整 word、重复值、N=1/N=2、重新初始化和调用模式切换保护；
并验证默认/显式关闭代码一致、显式关闭覆盖环境变量，以及输入按位激活开/关和
fullpass 选项组合。额外以新环境变量开启运行 Verilator package 回归也通过。

正式候选首轮四对新跑的 C100000 AB/BA：walltime 均值
**11.420000 → 11.205000 s（−1.883%）**，3/4 对改善，逐对变化中位数 −2.697%。
其中第一对为 +1.323%，保留该通过样本，没有按性能筛选。8 次 C100000 Difftest
及 2 次 C100 检查全部通过，代码 THP 完整覆盖。随后独立八对窗口再次新跑双方，
条件仍为 node030 CPU96–127、NUMA1、N=K=32、all-spin、Clang23 O3/native、
64 B compute 对齐、完整代码 THP、关闭 ASLR、C100000。

| 正式八对窗口指标 | F 均值 | 正式候选 G 均值 | 均值比变化 |
| --- | ---: | ---: | ---: |
| walltime / s | 11.477500 | 11.071250 | **−3.540%** |
| Host / s | 11.401500 | 10.988125 | −3.626% |
| 全局 input-load / µs | 2.117500 | 2.242875 | +5.921% |
| 全局 eval / µs | 42.736250 | 41.334500 | −3.280% |
| 全局 update / µs | 10.463625 | 9.715625 | −7.149% |
| 各分区平均 eval 合计 / µs | 485.528375 | 474.113750 | −2.351% |
| p24 全程平均 eval / µs | 24.070750 | 17.140625 | **−28.791%** |
| p18 全程平均 eval / µs | 27.129750 | 27.170750 | +0.151% |

八对 walltime **8/8 改善**，逐对变化中位数 **−2.864%**；四个完整 ABBA 块分别
为 **−4.372% / −1.543% / −1.458% / −6.667%**。正式版本两轮合计 11/12 对、
6/6 个 ABBA 块改善，按当前 workload 上约 **1.9%–3.5% 的窗口均值收益**保留，
不把单对 −9.144% 或八对均值视为固定加速比。正式两轮共 24 次 C100000 Difftest、
4 次 C100 检查以及全部签名/ELF 身份/THP 核验通过，没有按性能删除样本。
原型与正式版本各窗口绝对时间不能直接相减，百分比也不能累加。

本窗口 eval/update 合计每 step 减少 2.14975 µs，扣除 input-load 增加的
0.125375 µs 后净少 2.024375 µs，与 Host 均值减少 0.413375 s 的量级一致。
p24 的局部收益在正式版本复现，但 p18 平均 eval 仍为所有分区最高且基本未变。
下一轮应在 **G** 上重新采集瓶颈事件，继续研究剩余计算开销；本轮未重新统计
各分区成为瓶颈的次数，不能把平均耗时排序直接当作新的逐 step 瓶颈分布。

正式候选 **G** 保留为这条完整优化验证线的后续控制版本，路径为
`active_dispatch_20261003/dirty_input_bridge_20261012/formal/candidate/emu`。
源码开关仍默认关闭，后续沿 G 的实验显式开启，并且每次重新运行控制与候选
AB/BA；不能复用本节的任何一轮控制时间。

[`正式生成记录`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_input_bridge_20261012/formal/generation.json)、
[`结构与快照一致性`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_input_bridge_20261012/formal/candidate/scan.json)、
[`正式重编记录`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_input_bridge_20261012/formal/candidate/build.json)、
[`正式 CTest`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_input_bridge_20261012/formal_tests.log)、
[`正式首轮四对核验`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_input_bridge_20261012/formal/verification_4pairs.json)、
[`正式八对复测核验与全部分区数据`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_input_bridge_20261012/formal/verification_8pairs.json)、
[`正式生成与验证脚本`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_input_formal_20261012.py)。

#### 源码提交归档（2026-10-12）

本轮将累积源码按功能提交：Wolvrix `05f2a1d` 为可选 mem-to-reg 内存选择，
`6799586` 为非默认 `verilator-lowered-v1` 成本模型，`7c05d67` 为 GrhSIM RepCut
后端及后续 codegen/调度优化、接口、测试和文档。Difftest `5b7a09635` 提交
partition wrapper 编译优化，保存在 `thj/grhsim-repcut-integration` 分支；
XiangShan `c35b27d77` 同步其子模块引用，原有实验分支继续保留。

提交前使用当前源码重建 Python 绑定，29 项 GrhSIM Python 测试、6 项 RepCut
选项测试和 4 项 playground 后端流程测试全部通过；补跑的 mem-to-reg selection、
RepCut、RepCut cost model 和 GrhSIM compiler compatibility 四项 CTest 全部通过。
本节前述三项正式 emitter CTest 与 C100000 AB/BA 仍为对应功能和性能证据。
输入变化跟踪开关保持默认关闭，完整验证线的后续控制版本仍为 **G**。

#### 最新 F/G 平均 step 时空图（2026-10-13）

复用本节 **2026-10-12 正式八对窗口**的 16 次 C100000 运行、512 条分区计时，
生成最新 GrhSIM F/G 对照图。本次只读取已有成功样本，没有启动新的性能测试；
不混合原型、首轮四对、旧 Verilator 或其他后续对照窗口。

- [交互 HTML](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_input_bridge_20261012/formal/timeline_8pairs/grhsim_f_g_timeline.html)
- [时空图 PNG](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_input_bridge_20261012/formal/timeline_8pairs/grhsim_f_g_timeline.png) / [SVG](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_input_bridge_20261012/formal/timeline_8pairs/grhsim_f_g_timeline.svg)
- [数据 JSON](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_input_bridge_20261012/formal/timeline_8pairs/data.json) / [分区统计 CSV](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_input_bridge_20261012/formal/timeline_8pairs/part_summary.csv)
- [生成器](../../scripts/repcut_grhsim_timeline.py) / [HTML 模板](../../scripts/repcut_grhsim_timeline.html) / [浏览器检查](../../scripts/test_repcut_grhsim_timeline.mjs)

HTML 沿用此前浅色主题，支持完整单步/各阶段、F/G 显隐、共用分区排序与横轴、
缩放、均值/中位数、单独一对样本、逐对原始数据、分区指标选择、相对变化，以及
CSV/SVG 导出。默认使用跨运行均值，与本节正式八对表一致：walltime
**11.477500 → 11.071250 s（均值比 −3.540%）**，逐对变化中位数另列为
**−2.864%**，不混用两种计算。p24 全程平均 eval 为
**24.070750 → 17.140625 µs**。

图中 input/apply、eval、update/push 都画在对应分区线程上；当前 GrhSIM
input-load 已并行，不能沿用早期图的 Host 串行 input 画法。生成器核对两侧
wrapper 的并行 load 调用和空 early phase 列表。顶部为全局阶段跨度，各线程
callback 起点人为对齐于阶段边界；**灰色不是实测等待或 CPU 空闲时间**。
本批只有累计计时，不能恢复逐 step 进入/完成时刻或最后完成者。200102 个 step
包含两种时钟沿及初始化，图中单位为每次半周期求值调用，不是每完整周期。

生成器逐项核对全部原始 timing JSONL、运行配置、功能签名、步骤数和既有
verification 统计；浏览器通过 83 组交互检查、CSV 下载、SVG 导出、窄屏布局
及截图检查。内嵌字体覆盖本页所需全部 343 个汉字，离线显示无缺字。
证据见 [数据核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_input_bridge_20261012/formal/timeline_8pairs/validation.json)
和 [浏览器核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_input_bridge_20261012/formal/timeline_8pairs/browser_validation.json)。

#### 逐 cycle 分区直方图（2026-10-13）

新增 [可选择任意 cycle 的交互 HTML](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_input_bridge_20261012/formal/cycle_trace_20261013/viewer/grhsim_cycle_histogram.html)，
并附 [PNG 示例](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_input_bridge_20261012/formal/cycle_trace_20261013/viewer/grhsim_cycle_histogram.png)。
前一张平均图的累计计时无法恢复单周期，因此本次另行采集了完整逐步数据，
没有把全程均值或旧版本抽样冒充某一个 cycle。

采集仍仅在 **node030 CPU96–127、NUMA1、N=K=32、all-spin、ASLR off** 上进行；
F/G 各构建独立诊断二进制，只在 common/load/eval/update 四个外围目标文件加入
记录，其余各 **7450 个 archive member 字节不变**，原正式性能 ELF/archive 不改。
记录复用已有时钟读数，callback 计时结束后将原始 ns 写入独占分区缓冲，退出时
统一落盘。本次新跑 **F→G、G→F 两对 C100000**，另有两次 C100 检查，全部通过。
本批统一使用经核验的匿名 **4 KiB 代码页**；它不是上一节的 THP 窗口，且诊断
记录本身可能影响缓存和同步，**不能把绝对耗时与上一张 THP 平均图直接相减，
也不作为新一轮 ordinary walltime 收益证据**。默认配置未改变。

每次保留 **200102 个 step**：先是 50 个复位周期，再是 100001 个正常周期。
页面选择范围 **1–100001**，从复位后的第一个完整周期编号；cycle `c` 的原始
上升沿 step 为 `100 + 2*(c-1) + 1`，下降沿再加 1。此编号不是 RTL perf 或
退休指令计数。可选上升沿、下降沿、两沿合计，以及 input/eval/update 显隐、
F/G、两次独立运行、排序、滑条、前后跳转、CSV/SVG 导出；**不跨运行求平均**。
两沿相加时每个分区分别求和，最大柱不等于整周期关键路径；未采 callback
绝对时间戳，不将全局阶段减最大 callback 的差解释成精确线程等待。

四次采集共核对 **76839168 个 callback 阶段记录**，校验时钟沿/复位边界、
缺失值、callback 不超出对应全局阶段，并完成 **396 项累计值核对**，误差均在
原 JSON 的 500 ns 舍入范围内。HTML 内嵌全部周期、字体和数据，无外部网络请求；
以 391 个 gzip 区块按需解压，ns 数据无损，完整文件约 **158 MB（151 MiB）**。
浏览器通过 **129 组检查**，其中 84 项将解码/两沿合计结果直接与原 trace 对照，
另验证周期边界、切换竞态、指标开关、CSV/SVG 下载和窄屏布局。

入口与复现材料：

- [采集器](../../scripts/repcut_cycle_trace.py) / [计时记录头文件](../../scripts/repcut_cycle_trace.hpp)
- [HTML 生成器](../../scripts/repcut_grhsim_cycle_view.py) / [模板](../../scripts/repcut_grhsim_cycle_view.html) / [浏览器测试](../../scripts/test_repcut_grhsim_cycle_view.mjs)
- [成功采集窗口](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_input_bridge_20261012/formal/cycle_trace_20261013/runs_small/manifest.json) / [代码页核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_input_bridge_20261012/formal/cycle_trace_20261013/runs_small/codepage_verification.json)
- [完整性和累计计时核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_input_bridge_20261012/formal/cycle_trace_20261013/viewer/validation.json) / [浏览器核验](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_input_bridge_20261012/formal/cycle_trace_20261013/viewer/browser_validation.json)

重生成时以 `scripts/repcut_grhsim_cycle_view.py --source <上述 runs_small 目录>`
读取本批数据；可用 `--font` 指向前一平均图 assets 内的完整 Noto Sans CJK 字体，
并通过前一平均图目录的 `fonttools` 设置 `PYTHONPATH`。生成器不再执行仿真。
