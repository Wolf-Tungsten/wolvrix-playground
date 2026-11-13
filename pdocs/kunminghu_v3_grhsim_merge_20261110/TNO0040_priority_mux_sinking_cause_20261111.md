# TNO0040 DiffTest RAT 长 mux 的公共下沉优化与因果验证

## 结论

[TNO0039](./TNO0039_compiler_hotspot_sampling_20261111.md) 的采样发现已通过双向对象替换、LLVM pass 控制和动态计数验证：**before 的 Clang 23 大幅收益主要来自 DiffTest RAT 的长 priority mux，经 SimplifyCFG 公共指令下沉后，未命中路径的代码形态显著改善。** after 已移除这类长链，主要热点转为向量译码，因此不复制该收益。

这不是新一轮正式性能对测。以下短系列用于定位因果；8 对性能结论仍引用 [TNO0028](./TNO0028_seed2_clang23_recompile_20261111.md) 和 [TNO0038](./TNO0038_after_seed7_compiler_sensitivity_20261111.md)。所有修改都在独立诊断模型中，默认编译选项、生产 emitter 和 retained binary 保持不变。

## 双向对象替换

before 生成模型包含 7,759 个 C++ 对象，其中 28 个对象含 96 条长 mux。建立两个组合：

- 保持 Clang 19 harness 和其余模型对象，仅替换这 28 个为原 Clang 23 对象。
- 保持 Clang 23 harness 和其余模型对象，仅替换这 28 个为原 Clang 19 对象。

归档成员逐项哈希核对，两个组合都仅有这 **28 个对象**变化。源码、图、assignment、workload 和 NEMU 固定。

首轮四份模型均通过 DiffTest，性能随这 28 个对象切换。第二轮首次重复因 libc/libm 共 13 个页位于 NUMA0 被 locality 门拒绝，未纳入后续汇总。原日志保留；后续每次运行重新构建独立 private runtime，继续严格检查 CPU96–127、NUMA1、ASLR disabled、codepage PASS 和完整功能签名，没有放宽门槛。

## LLVM pass 对照

从第一条 511 级 mux 提取标准 C++ 独立 fixture：

- Clang 19：每个候选有独立数据 load，最后用数据 PHI 合并。
- Clang 23：将选择合并为地址偏移 PHI，随后公共 load。
- Clang 23 加 `-mllvm -simplifycfg-sink-common=false`：恢复独立 load 形式。
- Clang 23 加 `-fno-slp-vectorize`：仍保留公共 load 形式。
- Clang 19 显式打开 `-simplifycfg-sink-common=true`：仍未形成相同合并。

独立 fixture 优化 IR 的 `load i8` 静态数量：原 Clang 19 为 1,022（511 个条件和 511 个数据读取）；原 Clang 23 为 512（511 个条件加一个公共数据读取）。Clang 23/no-sink 为 1,022；Clang 23/no-SLP 为 512。这是对**该结构的公共下沉行为**的定位，不宣称找到了具体 LLVM 上游提交，也不意味着一个全局 flag 能让 Clang 19 获得相同优化。

保持 Clang 23 编译器，仅将 28 个对象加 no-sink 参数重编，再与原 Clang 23 模型/harness 链接。28 个重编对象中 **19 个的实际对象内容变化**，其余对象与原件字节相同；归档没有超出选择范围的变化。

## 完整仿真控制结果

5 份模型按正序、逆序各运行一次 100k CoreMark，共 **10 次全部通过**严格功能和放置检查。Host time 中位数：

| 模型 | Host time | part_eval |
| --- | ---: | ---: |
| 全 Clang 19 | 15.6330 s | 13.3498 s |
| 全 Clang 23 | 10.9140 s | 8.6432 s |
| Clang 19 + 28 个 Clang 23 长 mux 对象 | 10.9260 s | 8.6681 s |
| Clang 23 + 28 个 Clang 19 长 mux 对象 | 15.6085 s | 13.2771 s |
| Clang 23，仅长 mux 对象关闭 common sinking | 15.6075 s | 13.3414 s |

该对照中，只交换 28 个对象就几乎交换了完整仿真的快慢；Clang 23 的 pass 控制也恢复了慢路径。收益不主要来自 harness、通用调度器的重编译或模型执行次数变化。上述归因针对本次冻结模型和 workload；没有据此修改默认编译参数。

## 实际调用次数和命中深度

在 part_6/batch_93 的 6 条长 mux 中加入独立计数，然后分别用 Clang 19/23 编译该对象，其余保持各自原件。两份完整模型均通过 100k DiffTest，六条 mux 的计数逐项相同：

| 每条 mux | 数量 |
| --- | ---: |
| 候选数 | 511 |
| 调用次数 | 67,238 |
| 有任一候选命中 | 1 |
| 全部不命中 | 67,237 |
| 条件检查总次数 | 34,358,108 |
| 每次平均检查 | 510.9924 |

约 **99.9985%** 的调用扫描完整长链后返回默认值。Clang 19 的这种路径几乎每一级都跳到下一段，Clang 23 则顺序继续直到末尾。数据和执行次数相同，代码形态决定了这部分效率。该动态统计来自单个代表 batch，不能未经测量外推为所有 96 条链的精确命中率。

独立单 mux fixture 在 CPU96/NUMA1/ASLR-disabled 条件下也支持这一方向：全不命中时，Clang 19 / 23 的调用中位数为 **171.17 / 103.87 ns**；末尾命中时为 **170.55 / 101.24 ns**。首项立即命中则是 1.47 / 2.36 ns，Clang 23 反而稍慢，说明收益与真实命中分布有关。

独立全不命中场景的 branch-misses 比例两侧都很低，不能将全部收益称为“预测失败减少”。不同分支方向、目标跳转、代码体积和前端吞吐共同改变执行成本；完整模型同时运行许多链，独立单 mux 的倍数也不能直接外推为整机倍数。因果证据由实际对象替换和 pass 控制提供。

## 为什么 after 不同，以及下一步

before 观察路径的大型选择链已被 after 的 `DiffRatStateBuffer` 结构替代，after 无 511/520 级链可供同样的优化。采样显示 after 的热点是 `VectorDecodeChannel` 展开后的大型布尔计算；主要函数同时具有较大代码体积和大量栈访问，见 TNO0039。因此，“Clang 23 对 before 快约 30%，对 after 没有类似改善”有具体的代码路径和控制实验解释。

下一步应直接针对 after part_8 的 batch 53、39、54、51 做译码逻辑的动态归因和等价变换：检查重复表达式、长生存期临时值、跨 supernode 内联与激活范围。保持所有输出、断言和完整 DiffTest 的语义，先用局部函数验证，再做完整模型验收。当前还没有把 after 的栈访问量等价为已证明的全部瓶颈，需以进一步 profile 和控制实验判断。

## 验证与产物

- 4 次硬件采样均通过完整 DiffTest；初始对象交换 4 次通过，1 次 locality 拒绝被单独保留；最终 10 次因果控制和 2 次动态计数均通过严格门。
- 全部通过运行的 before 签名一致：PC=`0x80000cde`、instrCnt=238,535、cycleCnt=99,996、Guest=100,001、cycle-limit、相同 CoreMark UART。
- 实验脚本编译、证据校验、归档成员哈希、计数相等、文档链接及 `git diff --check` 通过。本轮未修改生产代码，没有新增正式 walltime 结论。

证据入口：

- [综合报告](../../build/artifacts/repcut-compiler-hotspots-20261111/report.json)、[最终验证](../../build/artifacts/repcut-compiler-hotspots-20261111/verification.json)、[核验脚本](../../build/artifacts/repcut-compiler-hotspots-20261111/report.py)。
- [对象交换脚本](../../build/artifacts/repcut-compiler-hotspots-20261111/hybrid.py)、[pass 控制脚本](../../build/artifacts/repcut-compiler-hotspots-20261111/pass_control.py)、[10 次控制结果](../../build/xs/repcut-compiler-hotspots-20261111/causal-runs/summary.json)、[原始样本](../../build/xs/repcut-compiler-hotspots-20261111/causal-runs/results.json)。
- [动态计数脚本](../../build/artifacts/repcut-compiler-hotspots-20261111/mux_counts.py)、[两版计数](../../build/xs/repcut-compiler-hotspots-20261111/mux-counts/result.json)。
- [独立 mux 提取与实验脚本](../../build/artifacts/repcut-compiler-hotspots-20261111/mux_probe.py)、[独立结果](../../build/xs/repcut-compiler-hotspots-20261111/mux-probe/summary.json)、[fixture/IR/汇编/硬件计数](../../build/xs/repcut-compiler-hotspots-20261111/mux-probe/)、[pass IR 控制](../../build/xs/repcut-compiler-hotspots-20261111/mux-pass-controls/results.json)。
- [被拒绝的 locality 样本](../../build/xs/repcut-compiler-hotspots-20261111/hybrid/runs/c23_plus_mux19/run1.rejected.json)、[原始日志](../../build/xs/repcut-compiler-hotspots-20261111/hybrid/runs/c23_plus_mux19/run1.log)。
