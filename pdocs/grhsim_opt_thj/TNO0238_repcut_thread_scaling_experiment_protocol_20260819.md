# RepCut 1/2/4/8 线程缩放对照实验协议

日期：2026-08-19

## 目标与边界

本实验比较同一份 XiangShan RepCut 设计在以下两个运行路径、四档线程参数下的仿真性能：

| 文档简称 | 对应入口 | 线程参数 |
| --- | --- | --- |
| native | `run_xs_repcut` | `XS_EMU_THREADS=1,2,4,8`，分别编译为 Verilator `--threads N` 二进制 |
| partitioned | `run_xs_repcut_verilator` | 同一个 partitioned 二进制，运行时设置 `XS_EMU_THREADS=1,2,4,8` |

比较只统计仿真运行阶段，不把 Wolvrix/RepCut、Verilator 或 C++ 编译时间并入性能结果。波形、coverage、随机初始化均关闭。

## 冻结输入

实验根目录为：

```text
build/repcut_thread_scaling_20260819
```

它是本轮新增目录；已有 `build/xs/repcut`、`build/logs/xs-repcut` 和其他工作区产物不清理、不覆盖。初始输入如下：

| 项目 | 值 |
| --- | --- |
| 主仓库 commit | `e088bdbbddecdc8998e82d4ac5410d977768d5ce` |
| Wolvrix commit | `79ec2037b00f2d4894d72785277ebe3f5d37782d` |
| XiangShan commit | `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6` |
| 输入 GRH JSON | `build/xs/wolf/wolf_emit/xs_wolf.json`，`3427740706` B，SHA-256 `82a29e6e2f715c18ffd61ab0106ed5abb6d0fbb6843eea58d8782eb3d30994ba` |
| CoreMark image | `testcase/xiangshan/ready-to-run/coremark-2-iteration.bin`，`16712` B，SHA-256 `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e` |
| NEMU SO | `testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`，`567504` B，SHA-256 `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9` |
| RepCut 脚本 | `scripts/wolvrix_xs_repcut.py`，SHA-256 `efd9a53d0df57352af1b9b36290a9bcb4a2cb1c3254fb11513b0dfe0c0a636ef` |
| partitioned emitter | `wolvrix/lib/emit/verilator_repcut_package.cpp`，SHA-256 `519797337a143a2ed2270e9484af6b65c2d1dd4666e8c0236d19101018758404` |

工作树在实验开始前已非 clean：父仓库显示 Wolvrix 子模块 modified；Wolvrix 内已有 `.gitignore` 修改及 `external/mt-kahypar` 未跟踪项。本实验不还原这些状态，因此除 commit 外同时冻结上述直接参与生成的文件与最终产物 SHA。

RepCut 仅运行一次，固定 `SimTop`、`32` 个 partition、imbalance `0.015`、Mt-KaHyPar `quality` preset。该次调用同时生成 split SV 和 partitioned package。四个 native 构建与 partitioned 构建必须复用这份结果，避免多次 Mt-KaHyPar 运行产生不同切分而污染线程缩放比较。

## 线程语义

相同的 `N` 表示相同的 CPU 并行预算，不表示相同的 OS 线程组成：

- native 的 `N` 是 Verilator `--threads N` 的总模型线程预算，通常由主线程加 `N-1` 个 worker 构成；
- partitioned 在 `N=1` 时走主线程串行路径，在 `N>=2` 时创建 `N` 个 phase worker，另有一个主要等待 barrier 的协调线程；
- 两条路径都只允许在同一组 `N` 个物理核上运行，排除 SMT sibling，因此不会因为 partitioned 的协调线程额外获得一个计算核。

partitioned 当前生成代码中计时插桩始终存在；`XS_REPCUT_STEP_TIMING` 已不控制这段代码。其 JSONL 分阶段统计只用于解释 partitioned 内部开销，不与 native 伪装成共同指标。

## 构建协议

1. Wolvrix Python 扩展使用本轮独立的 `python/skbuild`，不清理已有的 `wolvrix/build/skbuild`。
2. 一次性生成结果冻结后，分别在 `build/native-t1`、`native-t2`、`native-t4`、`native-t8` 中构建 native 二进制。
3. partitioned 只在 `build/partitioned-emu` 中构建一次，四档运行复用同一 ELF。
4. 不调用带清理动作的根目标并发构建；只调用 XiangShan difftest 内层 `make emu`，每一路使用独占 `BUILD_DIR`。
5. 编译可以分波并行；所有编译进程完全退出后，才允许采集正式仿真样本。

构建成功、ELF/生成物 SHA、命令和功能 canary 单独记录于 [TNO0239](./TNO0239_repcut_thread_scaling_build_and_functional_gates_20260819.md)。

## 运行协议

工作负载统一为 CoreMark 2-iteration，正式运行统一加 `-C 30000`。每个配置先运行不计分的 100-cycle smoke 和 10k-cycle canary；只有八个配置均满足功能门禁才进入正式测量。

主机固定为 `node030`：Linux `6.8.0-111-generic`、双路 AMD EPYC 9684X、每路 96 个物理核并开启 SMT、2 个 NUMA node、约 1 TiB 内存。工具链冻结为 Verilator `5.048`、Clang `21.1.5`、GCC `13.3.0`、CMake `4.1.0`；CPU governor 为 `schedutil`，boost 开启。

正式运行遵循以下约束：

- 从一个满足静默门禁的 8-physical-core CCD 中选核，四档使用嵌套集合 `1/2/4/8`，所有配置固定同一 CCD 与 NUMA node；
- 使用 `taskset`/`numactl` 固定 CPU 与内存，使用 `setarch x86_64 -R` 关闭 ASLR；
- 每次只运行一个仿真，不与编译或另一个正式样本并发；辅助采集进程放在目标 CCD 外；
- admission 检查整个 CCD 的物理核及 SMT sibling，连续运行期间继续监测，外部负载越过门限的样本作废并重跑，不择优保留；
- 功能硬门禁包括退出状态、同一终止原因、guest cycle/instruction/terminal PC 一致、无 difftest mismatch/assert/fatal/error，且日志恰有一个正数 `Host time spent`；
- partitioned 额外要求 timing JSONL 正常收尾，记录数与 step 数自洽。

## 样本顺序与统计

`A=native`，`B=partitioned`。每个线程数执行完整 `ABBA + BAAB`，即每条路径各 4 个正式样本；四档合计 32 个有效样本。全局先按 `N=1,2,4,8` 执行 ABBA，再按 `N=8,4,2,1` 执行 BAAB，以降低时间漂移与线程数顺序的耦合。按时间顺序接收首个通过门禁的完整 pair，不挑选最快轮次。

共同 headline 为仿真日志中的 `Host time spent`。每个后端/线程数报告 4 样本算术均值、median、min、max、spread，并计算：

- 后端内部 speedup：`T1 / TN`；
- 并行效率：`speedup / N`；
- 同线程数跨后端比值：`partitioned / native`，以及时间差和百分比；
- ABBA、BAAB 各自的跨后端差异及两种顺序的 gap。

外部 wall、task-clock、有效使用核数、PMU、context switches、CPU migrations、RSS 和 partitioned 分阶段 timing 作为诊断字段；它们不替代 `Host time spent` headline。正式结果与证据边界单独记录于 [TNO0240](./TNO0240_repcut_thread_scaling_performance_results_20260819.md)。

## 7. 参数职责勘误（2026-08-19）

Makefile 中两个参数的职责不同：native 构建把 `EMU_THREADS=N` 传给 XiangShan difftest，最终进入 Verilator 的 `--threads N`；partitioned 构建固定 `EMU_THREADS=0`，由生成的 package 在运行时读取 `XS_EMU_THREADS=N`，决定 phase worker 数。实验 runner 为保持命令审计一致，会对所有 slot 注入 `XS_EMU_THREADS=N`，但 native 的线程数已经在 ELF 构建时冻结，运行时该环境变量不会改变 native 二进制的 Verilator 线程数。

## 8. generated-src 身份勘误（2026-08-19）

冻结 `SimTop.sv` 的 `GatewayEndpoint.sv` 输入宽度为 `79263`，因此矩阵必须使用 XiangShan generated-src（`CPU_XIANGSHAN`、width `79263`）。通用 `difftest.DifftestMain` 配合 `CONFIG=G` 会生成 `CPU_DEMO`/`45871` 的独立 Demo profile，不能替代 XiangShan generated-src；该误用的构建只保留在 [TNO0239](./TNO0239_repcut_thread_scaling_build_and_functional_gates_20260819.md) 的诊断章节。正式矩阵若恢复，应从 `build` 目录下的匹配 profile ELF 开始，runner 默认 build root 已对应调整。

## 9. 执行状态增量（2026-08-19）

协议本身已冻结，但本轮没有进入 ABBA/BAAB 正式采样：匹配 profile 的 native `t1` 与 partitioned `N=1/2/4/8` 在 cycle 605 触发 `csr_dbltrp_inMN`，native `t2/t4/t8` 只能作为 10k cycle-limit 诊断。构建、日志和 profile 身份见 [TNO0239](./TNO0239_repcut_thread_scaling_build_and_functional_gates_20260819.md)，正式性能表见 [TNO0240](./TNO0240_repcut_thread_scaling_performance_results_20260819.md)；当前正式样本计数为 `0/32`，不得从诊断耗时计算 speedup。
