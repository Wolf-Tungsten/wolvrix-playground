# TNO0379：CRC 共同调用循环复核——撤回通用查表收益判断

日期：2026-10-29。承接 [扩展实验](./TNO0377_chisel_pattern_expanded_evidence_20261029.md)。

## 为什么追加这次实验

原 `crc16` 和 `crc16_table` 使用同一个 Rocket Chip CRC 参数：多项式 0x11021、32-bit
输入、16-bit 余数。复核发现两例 `research_compute.cpp` 完全相同，计算体反汇编都为
20 条指令，但原二进制里的随机输入基线分别约 2.23 ns 和 6.96 ns。

所以原实验可以保留为各自调用上下文中的测量，却不能据其中最大的百分比推荐通用
LUT 替换。这也是本轮主动保留失败与反证的一个例子。

## 共同调用实验

新增 [crc_variants.cpp](../../testcase/chisel-pattern-study/crc_variants.cpp) 和
[复现驱动](../../scripts/chisel_pattern_crc_control.py)，复制并校验原生成模型，不改算式。
三种实现放进同一 binary，通过同一个非内联函数指针循环调用：生成计算体、位串行
多项式除法、同多项式 LUT。三者都保留一个尾跳转 adapter，机器码已核对；没有为某个
候选生成专门的计时循环。

在 node030 CPU96，以相同 Clang 和 `-std=c++20 -O3 -march=native` 构建、计时。
验证两组种子 × 五种分布 × 100,000 输入，同时比较正常 eval、生成计算体和两个软件
实现。每个候选五种分布各完成 8 对 AB/BA，候选之间的先后顺序也交替。

最终产物：[crc-common-loop-v2](../../wolvrix/build/artifacts/chisel-pattern-study/crc-common-loop-v2/)。
早期只有生成体包含 adapter 的版本另存为 `crc-common-loop`，未覆盖；最终结果以
各候选 adapter 对齐的 v2 为准。

## 结果

| 输入 | 候选 | 生成体 ns | 候选 ns | 配对变化中位数 | 8 对变化范围 |
|---|---|---:|---:|---:|---:|
| random | 位串行 | 2.240 | 5.631 | +151.8% | +146.4% ～ +156.0% |
| random | LUT | 2.226 | 2.480 | +11.6% | -4.2% ～ +12.7% |
| sparse | LUT | 2.220 | 2.481 | +11.7% | +2.3% ～ +12.5% |
| dense | LUT | 2.210 | 2.483 | +12.3% | -0.8% ～ +12.9% |
| toggle1 | LUT | 2.291 | 2.481 | +8.5% | -7.0% ～ +12.3% |
| hold99 | LUT | 2.210 | 2.480 | +12.1% | +7.9% ～ +13.2% |

这里没有测出 LUT 的稳定优势。原基线在新的共同调用循环中接近较快的原 `crc16`
测量；位串行实现仍明显退化。不同程序布局/调用循环改变纳秒级结果的原因尚未细分，
不能直接归因为某种 cache miss、分支预测或 CPU 频率。

反汇编确认，生成体已经使用 `vpbroadcastq`、`vpandq`、两个 `vpopcntq` 及向量归约。
因此“CRC 在 RTL 是大量 parity，仿真也必然逐 bit 计算”的推断不成立。Clang 在本机
目标 ISA 下已经恢复了相当紧凑的字/向量实现。

## 更新后的处置

- 撤回“本轮已证明 CRC LUT 可通用提速”的判断；原表保留作为历史测量。
- CRC 归入“已有编译器优化、调用上下文敏感，需要真实使用锥复核”。
- 接入真实设计前保留准确的多项式、位序、反射、输出宽度和调用语义。
- 对其他纳秒级、小指令数差异同样避免过度解读；较大局部收益仍需真实布局和整机验证。

证据：[输入/二进制身份](../../wolvrix/build/artifacts/chisel-pattern-study/crc-common-loop-v2/manifest.json)、
[原始计时](../../wolvrix/build/artifacts/chisel-pattern-study/crc-common-loop-v2/measurement.json)、
[共同调用循环与各实现机器码](../../wolvrix/build/artifacts/chisel-pattern-study/crc-common-loop-v2/assembly.txt)。
