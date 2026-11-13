# TNO0044：默认启用前的收益边界与重复谓词回退

日期：2026-11-11（America/Los_Angeles）。用户要求验证其他配置不退化后默认开启 [TNO0043](./TNO0043_vector_decode_masks_walltime_20261111.md) 的新规则。本阶段先检查收益边界，并准备 before seed2、after seed1 两份独立分区的完整开关对照。

## 边界测试发现的问题

生成 18 类合成归约函数：连续/分散 Boolean 输入布局、完全重复/滑动窗口/随机谓词，以及 16/32/64/128/512 个谓词规模。两侧使用原表达式与共享 pack/mask 表达式，Clang 23 `-O3 -march=znver4`，node030 CPU96、NUMA1 bind、ASLR off，每类预热后 8 对 AB/BA。该实验是局部诊断，不是完整 emulator walltime。

重要构造约束：两侧均先计算所有局部结果，再写输出，和正式 emitter 一致。首次草稿交错输入读取与输出写入，C++ 指针 alias 限制了旧表达式的公共子表达式合并，因此弃用其性能解释；产物保留在 `boundary/`。有效结果是 [boundary-v2](../../build/xs/reduction-mask-default-20261111/boundary-v2/)。

有效测试发现完全重复的谓词会退化：

| 布局/谓词数 | 旧表达式均值 | 原掩码表达式均值 | 逐对 delta 中位数 |
|---|---:|---:|---:|
| 连续 / 16 | 约 2.0 ns | 约 8.8 ns | +344% |
| 连续 / 128 | 约 2.3 ns | 约 9.1 ns | +306% |
| 分散 / 16 | 约 14.6 ns | 约 20.2 ns | +38% |
| 分散 / 128 | 约 14.6 ns | 约 20.8 ns | +42% |

原因是原编译器能把重复归约合为一个谓词，pack 的固定成本无法摊销。仅统计 concat operation 数量会高估有效复用。其余 14 类的中位数均改善，范围约 −21% 至 −97%；这只说明这些局部样本没有退化，整图仍需独立验证。

## 收紧触发条件

新增收益门：按 `(mask, AND/NAND 或 OR/NOR 族)` 去重，要求至少 **16 个不同谓词**。原有语义、安全与位宽条件继续保留。重复字段和不同 concat 排列可能得到相同 mask，不能重复计入收益门。

未满足条件时保留原发射路径。新增 fixture 明确检查“24 个 concat 仅形成两个谓词”的情况不生成 pack。after seed7 上次命中的 119 个节点最少已有 35 个不同 mask，因此不会因本次收益门丢失已验证的命中范围。

## 其他配置的控制方式

- before：冻结 before seed2 的图、Clang 23 和 harness，只改变掩码规则。
- after：冻结独立 after seed1 图，并在开关两侧复用此前验证的同一 Clang 掩码修正对象。该对象不属于新规则的允许改写范围；构建时检查其源码不变和 archive 中对象逐字节一致。
- 已有单核 native 流程没有打开父选项 `scalar_concat_reduction`。新掩码开关仍依赖该父选项，补充父选项关闭时的源码一致性回归，不把未受影响的 native/GSIM 路径计为加速结果。

所有完整性能样本继续使用 node030 CPU96–127、NUMA1、ASLR off、完整 DiffTest、8 对 AB/BA，无外部 CPU 空闲准入检查。默认值将在这些门完成后处理。

## 产物

- [边界测试生成器](../../build/artifacts/reduction-mask-default-20261111/boundary_bench.py)
- [有效局部结果](../../build/xs/reduction-mask-default-20261111/boundary-v2/summary.json)
- [跨图构建驱动](../../build/artifacts/reduction-mask-default-20261111/build.py)
- [完整配对驱动](../../build/artifacts/reduction-mask-default-20261111/measure.py)
