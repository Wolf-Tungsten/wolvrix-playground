# TNO0395：优先编码原语的输入布局门控

日期：2026-11-02。本文记录在完整香山 walltime 出结果前，对“输入布局不适合原语”
这一回退原因的独立处理。它接续 [TNO0394](./TNO0394_priority_intrinsic_width_matrix_results_20261102.md)，
不把位宽阈值当作默认选择规则。

## 动机

TNO0394 的局部矩阵显示，`UInt` packed 输入在大宽度上适合 CTZ intrinsic，而
分散的 `Vec[Bool]` lanes 在宽度 65 时明显回退：完整 eval 中位变化约 `+334%`，
compute body 约 `+547%`。这不是“65 位永远不适合”，而是 intrinsic 需要先把分散
lane gather 成一个 packed 值；原有硬件树的逐 lane 访问在当前 GrhSIM 活动和局部
表达式模型中更便宜。因此本轮先固定一个可解释的布局契约：无法证明输入已 packed
时，保留原 utility 的硬件表达。

## 实现

`testcase/xiangshan/utility` 的同名 utility 现在按 Scala 输入类型记录布局：

| 输入形态 | 记录的布局 | `priority-encode` 模式 |
| --- | --- | --- |
| `UInt`/`Bits` | `packed` | 允许 CTZ intrinsic |
| `Seq[Bool]` | `distributed` | 保留原 `chisel3.util`/原 utility 硬件实现 |
| `Vec[Bool]` | `distributed` | 保留原硬件实现 |

新增 `Vec[Bool]` 重载覆盖 `PriorityEncoder`、`ParallelPriorityEncoder`、
`PriorityEncoderWithFlag` 和 `PriorityEncoderDefault`。香山调用方仍使用原来的
utility 名称和参数，不需要添加临时别名。调用 manifest 增加 `layout` 和 `decision`，
例如 `distributed-keeps-hardware` 与 `packed-intrinsic`。

这里的边界是有意明确的：调用方一旦显式写 `vec.asUInt`，就已经声明完成了 gather，
utility 只能把它视为 packed；若希望保留分散布局，应直接把 `Vec[Bool]` 传给 utility。
这避免在 utility 中猜测 Chisel 数据流的历史来源。

## 小型生成核验

`EncoderStudy` 使用同一语义同时生成 packed 和 `Vec[Bool]` lanes 两个输入。当前
`layout-policy-v3` 的调用清单已经证明：

```text
w65-lanes/B: 2×PriorityEncoder.Vec、ParallelPriorityEncoder.Vec、
             PriorityEncoderWithFlag.Vec、PriorityEncoderDefault.Vec
             全部 distributed-keeps-hardware，intrinsic=0
w65-packed/B: PriorityEncoder.Bits、ParallelPriorityEncoder.Bits、
              PriorityEncoderWithFlag.Bits 使用 packed-intrinsic
```

对应生成 RTL 位于 `wolvrix/build/artifacts/priority-intrinsic/layout-policy-v3/`。
packed 版本包含 `wolvrix_ctz_v1_w65`，lanes 版本的 `EncoderB.sv` 不包含该 DPI 调用。
本机 Verilator 5.048 与 fixture wrapper 的抽象 `VReference` 链接存在版本不匹配，
所以该目录只作为 Chisel、调用 manifest 和 RTL 结构证据；最终小基准 link 使用
node030 的 Verilator 5.052。

## 香山全量进展

曾启动的 v5 在 B elaboration 过程中发现上述 `Vec[Bool]` 重载需要补入，已保留其
部分日志但停止，不把新旧策略混入一个结果。v6 已从同一源码快照重新生成 A/B，
并由 `xs_finish_v6.py` 等待两个 RTL 完成后使用冻结的 Wolvrix tools 做 native
emit/compile。路径为：

```text
build/xs/priority_intrinsic_20261102_v6/
```

A/B 完成后将检查：调用布局分布、CTZ 调用数、GRH 图和活动调度差异、两组固定种子
各 100,000 周期 Difftest，以及 CPU96、node030 NUMA 本地的 8 对 AB/BA 单线程
walltime。若布局门控仍回退，下一步再拆分 gather、结果物化和活动传播，暂不引入
宽度拟合规则。

## 当前状态

- utility 的布局重载、manifest 字段和 fixture 断言已实现。
- Python/native 回归 `11` 项通过；Chisel fixture 已验证 packed/Vec 分流。
- v6 完整香山 A/B 仍在 node030 生成；walltime 结论待其完成后追加。

## 65 位布局复测增量（2026-11-02）

node030 的 Verilator 5.052 已完成 packed/lanes 两个 case 的新构建和测量；两组各
`1,000,133` 个功能向量通过，两个 case 均完成 8 对 AB/BA，NUMA node1、CPU96、
SMT sibling 空闲门禁通过。结果位于
`wolvrix/build/artifacts/priority-intrinsic/layout-policy-v7/`。

| 输入布局 | eval 中位变化 | compute 中位变化 | 解释 |
| --- | ---: | ---: | --- |
| 65 位 packed | `-77.900%` | `-64.502%` | 使用 CTZ intrinsic |
| 65 位 `Vec[Bool]` lanes | `-1.723%` | `-2.062%` | 保留原硬件树，变化落在测量噪声/代码布局范围附近 |

旧的全 intrinsic lanes case（TNO0394 的 `matrix-v3`）为 eval 中位 `+334.135%`、
compute 中位 `+547.395%`。新的 lanes 结果没有复现这类回退；这支持“先按输入布局
拒绝 gather”这一局部修正，但不能把约 `-2%` 视为稳定优化。第一次复测因 sibling
idle `97.783%` 被门禁拒绝，原始目录保留；第二次在新目录、安静 CPU96 上通过。

## v6 香山结构增量（2026-11-02）

两种完整 RTL 均已生成，A native emit/compile 已通过，B 正在完成同一套 native
编译；生成目录为 `build/xs/priority_intrinsic_20261102_v6/`。调用 manifest 的
实际分流是：B 中 `133` 个 packed 调用使用 intrinsic，`333` 个 distributed 调用
明确保留原硬件；实际宽度仍覆盖
`1,2,4,5,6,7,8,9,10,14,16,32,36,38,64`，没有加入宽度阈值。

布局门控改变了最终 activity 形态：

| 指标 | A：none | B：布局门控 | B-A |
| --- | ---: | ---: | ---: |
| graph ops | 7,204,108 | 7,200,444 | -3,664 |
| graph values | 6,833,009 | 6,829,345 | -3,664 |
| compute nodes | 1,081,648 | 1,081,361 | -287 |
| compute supernodes | 63,191 | 63,196 | +5 |
| commit supernodes | 468 | 468 | 0 |
| compute node ops | 5,625,117 | 5,621,443 | -3,674 |
| DAG edges | 519,040 | 520,354 | +1,314 |
| topo edges | 10,141,598 | 10,137,295 | -4,303 |
| boundary values | 996,222 | 996,238 | +16 |

相比 TNO0393 的“所有调用都替换”结果（compute nodes `+354`、supernodes `+62`、
DAG edges `+3,002`），布局门控没有消除所有后端形态变化，但把变化方向和规模
明显收回。B 的完整单线程 walltime、Difftest 和 8 对 AB/BA 仍待编译完成后记录，
不能从上述结构数字推断整机收益。

## v6 单线程整机结果（2026-11-02）

完整 A/B 已在 node030 专用单线程流程完成：CPU96、NUMA node1、默认 SLP、C100000，
两组 100,000-cycle Difftest trace 和逐字段比较通过，8 对 AB/BA 及 v4 A 历史
anchor 均通过。结果目录为
`build/xs/priority_intrinsic_20261102_v6/comparison-v1/`。

| 指标 | 结果 |
| --- | ---: |
| A 均值 | `111.957875 s` |
| B 均值 | `112.385625 s` |
| 配对均值变化 | `+0.383271%` |
| 配对中位变化 | `+0.427641%` |
| 固定种子 paired bootstrap 95% CI | `[-0.291121%, +1.054788%]` |
| B 更快的 pair | `3/8` |
| Difftest trace | `2 × 100,000`，均 PASS |
| 功能签名 | PC `0x80000c0c`、instr `240349`、cycle `99996` |

与 TNO0393 的全调用替换结果 `+0.439982%` 相比，布局门控把回退略微收窄，且区间
跨过零；当前证据应判为**接近中性、没有稳定整机收益**。它验证了“分散布局不应
强行 gather 到原语”的方向，不能证明 packed intrinsic 已适合每个调用。微基准中
65 位 packed 仍有显著局部收益，而完整整机的主要剩余成本仍可能来自活动传播、
结果物化和少量 DAG 边变化。

## 交付与后续边界

- Chisel/RTL 调用 manifest：`wolvrix/build/artifacts/priority-intrinsic/coverage-v6-b.json`。
- 65 位布局复测：`wolvrix/build/artifacts/priority-intrinsic/layout-policy-v7/`。
- 完整 A/B 结构和二进制：`build/xs/priority_intrinsic_20261102_v6/`。
- 汇总报告：`wolvrix/build/artifacts/priority-intrinsic/priority-intrinsic-layout-policy-report.json`。

默认关闭开关仍保持不变。下一阶段若继续，应针对 packed 输入的 gather/物化、结果
跨组边界和活动边，而不是重新按位宽拟合门槛；任何新规则仍需独立的单线程 A/B、
功能 trace、NUMA 门禁和失败样本归档。

### 状态勘误（2026-11-02）

文档前面的“v6 仍在生成”是生成阶段的现场记录；v6 A/B、编译、Difftest、NUMA
门禁和 8 对 AB/BA 已全部完成，最终判定以本节和 `comparison-v1/summary.json` 为准。
