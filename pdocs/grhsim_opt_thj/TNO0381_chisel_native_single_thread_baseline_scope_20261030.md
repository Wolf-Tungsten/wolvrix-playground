# TNO0381：Chisel 仿真表达研究的专用单线程基线口径

日期：2026-10-30。状态：执行路线已明确，本文记录基线口径与测量建议；尚未产生新的
单线程性能数字。承接 [广泛模式调查](./TNO0380_chisel_pattern_delivery_and_ir_design_20261029.md)。

## 用户明确的路线

进一步实现语义操作或双实现之前，先固定性能基线。主比较采用 **Wolvrix 专门的单线程
GrhSIM 流程**，不使用 Repcut 多线程流程的 `N=K=1`，也不把 32 个分区串行执行当作本基线。
这里的单线程指宿主机执行模型的线程；不因此改变 XiangShan 的 guest 核数或硬件配置。

当前代码入口已核对：

- [Makefile](../../Makefile:549)：`xs_wolf_grhsim_emit` 调用专用脚本。
- [wolvrix_xs_grhsim.py](../../scripts/wolvrix_xs_grhsim.py:930)：正常前端/归一化后对完整
  top 做 activity-schedule，然后直接 `emit_grhsim_cpp`；该流程不运行 Repcut。
- [Makefile](../../Makefile:991)：`xs_wolf_grhsim_emu` 以 `GRHSIM=1` 构建 Difftest harness。
- [grhsim.cpp](../../testcase/xiangshan/difftest/src/test/csrc/grhsim/grhsim.cpp:80)：普通
  `GrhSIMDiffTestSim::step()` 直接调用 `dut->eval()`。
- [Makefile](../../Makefile:1137)：`run_xs_wolf_grhsim_emu` 运行专用构建产物。

发射/编译过程仍可并行；`emit_parallelism`、编译 `-j` 与模型运行时单线程是不同维度。
构建产物必须审计为普通 `GrhSIM_SimTop`，不能仅通过设置线程数宣称使用了专用流程。
当前 `xs_grhsim` / `grhsim32.py` 是另外的 32 分区入口，不用于本轮主基线。

## 为什么适合这条探索线

当前要回答的是“语义保留或不同软件表示是否减少仿真执行成本”。专用单线程完整模型
可以避免分区器变化、跨分区复制/通信、线程同步与负载均衡掩盖局部实现的总效果。
后续 candidate 的正常活动分组、代码布局变化仍是它实际执行效果的一部分，不应为了
保持旧图而阻止合法优化；应固定生成策略和参数，而非要求优化后仍有同一 batch ID。

单线程不意味着无噪声。缓存/指令布局、ASLR、代码页大小、CPU 调度/频率、SMT 邻居
和其他负载仍会影响 walltime。此前 CRC 复核已经展示调用上下文的影响，因此应先
测 baseline 对自身的 A/A 波动，而不是预先假设低于某个百分比。

## 建议的固定与测量口径

1. **输入身份**：冻结当前 Chisel/RTL/filelist、硬件配置、Wolvrix 与依赖源码（包含 dirty
   diff）、编译器、pass/emitter 参数、harness、工作负载、NEMU 和随机种子。将普通
   单线程 pipeline 的实际参数存档，不直接套用分区后 pipeline 的默认值。
2. **产物身份**：使用新的独立输出目录，保留生成 C++、实际编译命令、ELF 和哈希。
   后续固定的是 baseline 产物及方法；每轮候选比较仍重新运行同一 baseline binary，
   不长期用某一次历史秒数作分母。
3. **环境**：同一机器/物理核绑定、明确 SMT sibling、NUMA 和页面模式；避免编译或
   其他性能实验同时占用测量资源。两侧采用相同编译优化与 PGO/BOLT 状态。
4. **功能和负载**：两侧用同一输入、复位规则、周期数及结束检查，并保留 Difftest。
   100,000 cycles 可作为首个固定窗口；是否足够长、是否覆盖代表性活动由运行结果
   判断。先做功能/签名验证，再做性能采样，增加窗口时显式建立新的 benchmark 身份。
5. **重复性**：先重复 A/A，记录分布/漂移，必要时检查同源码 clean rebuild 的可复现性；
   候选至少 8 对交替 AB/BA，保存全部样本、配对变化和离散程度，不选最快一次。
6. **计时范围**：关闭波形、逐 batch/每拍诊断。主 walltime 使用相同 harness 的固定
   计时边界，并另记外部进程 walltime。现有 `Host time spent` 从 Emulator 初始化阶段
   到收尾计算，包含部分初始化、Difftest 和清理，不是纯 eval；若增加稳态模拟窗口
   计时，两侧统一实现、独立命名，不能与已有指标混报。

计时实现依据：[emu.cpp](../../testcase/xiangshan/difftest/src/test/csrc/emu/emu.cpp:80)
保存起点，[收尾处](../../testcase/xiangshan/difftest/src/test/csrc/emu/emu.cpp:329) 输出 Host
时间。现有 `EMU_PHASE_TIMING` 每次 step 读时钟，适合另行诊断，不默认启用为正式性能指标。

## 与微基准和多线程结果的关系

- 微基准用于解释算式、布局和组件机制，无法代替完整单线程 walltime。
- 专用单线程是本研究的主要收益判断依据，但其收益不能自动外推到 32 线程。
- 已有多线程产物和诊断保留；待单线程候选有可靠收益后，再检验生产并行场景。

本次只核对入口、记录研究口径，没有构建新的基线或宣称测得 baseline walltime。
