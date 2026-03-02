# XS Stats 数据分析

数据来源：`build/logs/xs/xs_wolf_build_20260302_210205.log` 中的 `info [stats]` JSON。以下结论基于该统计（单一 graph）。

## 概览
- Graph 数：1
- Operation 数：5,778,793
- Value 数：5,134,133
- Operation / Value 比：1.13
- Value 总位宽：87,974,960，比均位宽：17.14 bit
- 有状态元素总数：316,208（寄存器 310,989 + 锁存器 410 + 存储体 4,809）

## 宽度分布（Value / Register / Memory）
**Value 宽度**
- 中位数 1，P90=32，P95=64，P99=68，最大 1,438,184
- 1-bit 占 63.22%，2-bit 占 8.49%，64-bit 占 6.63%
- 结论：以控制/标志类信号为主，但存在极宽向量（可能是聚合总线/数组展平）。

**Register 宽度**
- 中位数 2，P90=64，P99=64，最大 4096
- 1-bit 占 39.79%，2-bit 占 17.32%，64-bit 占 15.02%
- 结论：寄存器宽度分布更“控制化”，但 64-bit 寄存器仍是显著主力。

**Memory 宽度**
- 中位数 32，P90=64，P99=345，最大 8160
- 32-bit 占 83.16%，64-bit 仅 2.66%
- 结论：内存以 32-bit 字宽为绝对主流，呈现明显的 word-oriented 设计风格。

**Memory 容量（bit）**
- 中位数 160，P95=26,560，P99=1,048,576，最大 8,355,840
- 32-bit 占 31.94%，64-bit 占 8.86%，1,048,576-bit 仍占 2.66%
- 结论：容量呈长尾分布，既有大量小容量 RAM，也存在少量超大容量阵列。

## 运算种类（Top 10）
- kMux 17.51%，kAnd 14.52%，kOr 11.57%
- kLogicAnd 6.63%，kRegister / kRegisterWritePort / kRegisterReadPort 各 5.38%
- kAssign 5.13%，kSliceDynamic 4.92%，kEq 4.77%
- Top3 占 43.60%，Top10 占 81.19%
- 有状态 op（kRegister + kRegisterWritePort + kRegisterReadPort）占 16.14%
- 结论：逻辑与多路选择占据绝对主导，操作类型高度集中。

## 连接复杂度（Fanout / Cone）
**组合逻辑 fanout（comb_op_fanout_sinks）**
- 中位数 2，P95=380，P99=5,227，最大 512,803
- fanout ≤2 的比例 52.02%，≤4 的比例 63.76%
- 结论：多数节点 fanout 很低，但存在极端高扇出的“广播”信号。

**读端口 fanout（readport_fanout_sinks）**
- 中位数 9，P95=5,409，P99=37,963，最大 126,931
- fanout ≤2 的比例仅 13.52%，≤8 的比例 48.84%
- 结论：读端口 fanout 普遍高于组合节点，读路径共享更显著。

**写端口 cone（writeport_cone_*)**
- 深度：中位数 17，P90=65，P99=97，最大 654
- 规模：中位数 120，P90=2,744，P99=7,243，最大 54,905
- 扇入：中位数 34，P90=3,681，P99=3,685，最大 21,868
- 结论：写端口 cone 明显长尾；出现 3,681/3,685 的高频峰值，可能是结构化宏或重复模块导致的固定规模网络。

## 组合视角（跨指标）
- **控制 vs 数据对比**：value 宽度 ≤2 的占比 71.71%，但 memory 宽度 ≥32 的占比高达 96.65%，register 宽度 ≥32 也有 18.85%。提示大量信号数量来自控制位，而“宽数据”主要沉在寄存器/存储中。
- **寄存器建模结构**：kRegister / kRegisterWritePort / kRegisterReadPort 计数几乎 1:1:1（310,989 / 310,989 / 310,923），对应“每个寄存器一个读端口+一个写端口”的主流模式；寄存器相关操作占全部操作的 16.14%。
- **寄存器远多于存储体**：寄存器数量 310,989，而 memory 实例仅 4,809，约 65:1，表明设计更依赖寄存器级存储而非大量 SRAM 宏。
- **逻辑/选择/切片高度主导**：逻辑类（and/or/logic/not/eq）占 45.35%，mux 占 17.51%，assign+slice 占 10.05%，三者合计 72.90%。结合 value 中位宽 1，推测大量操作围绕控制信号与选择路径展开。
- **读路径共享强于组合逻辑共享**：readport fanout 中位数 9（显著高于组合 fanout 中位数 2），与 memory 以 32-bit 为主相结合，说明读数据被多处消费、跨模块共享更明显。

## 最大值与代码符号（max_symbols）
以下条目来自 `max_symbols`，用于定位“最大值”在设计中的具体符号；对符号数量过大的条目，仅列出代表性样本（前 8 个）。

- value_widths：max=1,438,184，符号数=1  
  例：`SimTop::_val_10048790`
- register_widths：max=4,096，符号数=1  
  例：`SimTop::cpu$l_soc$core_with_l2$core$memBlock$inner_dcache$dcache$bloomFilter$data`
- latch_widths：max=1，符号数=410（几乎所有 latch 均为 1-bit）  
  例：`SimTop::cpu$l_soc$core_with_l2$core$frontend$inner_icache$metaArray$banks_0$tagArray$array_0_0_0$rcg$CG$EN` 等
- memory_widths：max=8,160，符号数=1  
  例：`SimTop::cpu$l_soc$l3cacheOpt$tpmeta$tpDataTable$array$array_ext$Memory`
- memory_capacity_bits：max=8,355,840，符号数=1  
  例：`SimTop::cpu$l_soc$l3cacheOpt$tpmeta$tpDataTable$array$array_ext$Memory`
- writeport_cone_depths：max=654，符号数=11  
  例：`SimTop::_val_3808979`, `SimTop::_val_3808972`, `SimTop::_val_3644265` 等
- writeport_cone_sizes：max=54,905，符号数=1,686  
  例：`SimTop::_val_9989430`, `SimTop::_val_9997565`, `SimTop::_val_10000592` 等
- writeport_cone_fanins：max=21,868，符号数=1,686  
  例：`SimTop::_val_9989430`, `SimTop::_val_9997565`, `SimTop::_val_10000592` 等
- comb_op_fanout_sinks：max=512,803，符号数=1  
  例：`SimTop::_op_12640`
- readport_fanout_sinks：max=126,931，符号数=1  
  例：`SimTop::_op_10844741`

## RTL 语义与分布判断
定位依据：`max_symbols` + `build/xs/wolf/wolf_emit/xs_wolf.json` 的 `loc` 记录，再结合对应 RTL 文件。

- value_widths：最大值来自超长性能日志字符串（`build/xs/wolf/wolf_emit/wolf_emit.sv:5432425`，对应 `LogPerfEndpoint` 的 `$fwrite` 格式串，语义是性能计数打印）。分布上是极端特例（max 仅 1 个，且远高于 P99=68）。
- register_widths：最大 4096-bit 来自 DCache 的 BloomFilter 位图寄存器（`build/xs/rtl/rtl/BloomFilter.sv:85` 中 `reg [4095:0] data`）。分布上是极端特例（max 仅 1 个，P99=64）。
- latch_widths：全部 latch 都是 1-bit（典型为 `rcg$CG$EN` 这类门控使能）。分布不是长尾而是“单点退化”（max=1 且覆盖全部 410 个）。
- memory_widths / memory_capacity_bits：最大宽度与容量来自 `sram_array_1p1024x8160m255s1h0l1_pftch`（`build/xs/rtl/rtl/sram_array_1p1024x8160m255s1h0l1_pftch.sv:2` 与 `build/xs/rtl/rtl/sram_array_1p1024x8160m255s1h0l1_pftch.sv:8`，1024×8160 位，容量 8,355,840 bit）。语义上对应 L3 tpmeta 的大表结构；分布上是极端特例（max 各 1 个，P99=345）。
- writeport_cone_depths：最深 654 的根节点示例位于 FusionDecoder 的控制路径（`build/xs/rtl/rtl/FusionDecoder.sv:1409`），max 出现 11 次，说明存在少量但非孤立的深控制链。分布上是长尾（median=17，P99=97，max=654）。
- writeport_cone_sizes / writeport_cone_fanins：最大规模 54,905 / 21,868 的根节点大量来自 DelayReg 等流水寄存路径（如 `build/xs/rtl/rtl/DelayReg.sv:360`），max 各出现 1,686 次，体现结构性重复的大锥体。分布上是明显长尾（median=120，P99=7,243，max=54,905）。
- comb_op_fanout_sinks：最大值对应常量 1’b0 的组合节点（`build/xs/rtl/rtl/XiangShanSim.sv:334`，`_GEN` 附近常量），被大量模块复用导致超大扇出。分布上是极端特例（max 仅 1 个，P99=5,227）。
- readport_fanout_sinks：最大值来自 reset 同步寄存器读端口（`build/xs/rtl/rtl/ResetGen.sv:52`，`pipe_reset`），作为全局复位分发点产生高扇出。分布上偏极端（max 仅 1 个，P99=37,963）。

## 有趣结论（总结）
1) **控制信号占主导**：1-bit value 超过 63%，寄存器也以 1~2 bit 为主，说明大量控制/状态位主导设计。
2) **逻辑操作高度集中**：kMux/kAnd/kOr 三类就占 43.6%，Top10 占 81.2%，结构上很“规律”。
3) **“小而多”与“极端大”并存**：内存宽度/容量、fanout、cone 规模都呈现明显长尾，提示存在少数大型聚合结构。
4) **读路径更易形成高扇出**：readport fanout 的均值/极值远高于组合 fanout，读数据被多处消费。
5) **写端口 cone 存在固定规模模式**：cone fanin 在 3,681/3,685 附近集中，暗示某类模块或结构重复。
