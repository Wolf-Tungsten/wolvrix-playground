# TNO0446：标量与向量乘法行为模型的完整 S3 验收（2026-11-06）

## 覆盖检查修复

完整 A/B RTL、GRH 和 native binary 已在 TNO0445 修复后的同一工具冻结目录中完成。
定向负载的静态覆盖检查最初把 `andi t0,a1,127` 后的 `mulw t0,t0,a2` 当成必须独立退休的指令。
XiangShan 的 `FusedMulw7` 将这两个指令提交为 leader `andi`，并在提交记录中设置 `nFused=1`，
因此不会产生 `0x80000084` 的独立提交。

`scripts/multiply_workload_coverage.py` 现在识别该融合对，检查 leader 的 PC、编码和 `nFused`，
并将 follower 记录为 `mulw7` 覆盖。其他静态乘法指令仍要求 PC 和指令编码逐项匹配。
A/B 两个 seed 的覆盖检查均通过：89 个静态乘法/FMA 站点全部覆盖，融合 `mulw7` 各提交 414 次。
原始失败日志和修复后四份 JSON 位于 `build/xs/multiply_behavior_20261105_v2/` 与
`wolvrix/build/artifacts/multiply-behavior/`。

## 完整功能验收

A 为全硬件乘法，B 开启 `int-mul,vec-int-mul,fp-mul,vec-fp-mul`；两者均保留完整 DiffTest/NEMU，
未启用 intrinsic、commit-rat 或 grouped lowering。两组生成的 DiffTest schema 哈希相同，A 有 106 个
DiffTest bundle，B 也有 106 个；B 实际 manifest 记录 12 个乘法行为模型实例。

两组 100,000 周期定向 trace 的全部字段逐周期一致，CoreMark 和定向负载的功能签名、guest cycles、
PC、提交指令数和输出均一致。定向负载的 89 个乘法/FMA 静态站点包括标量 MUL/MULH/MULHSU/MULHU/MULW、
MULW7、标量 FP32/64 FMA、SEW8/16/32/64 向量整数、加宽整数、向量 FP16/32/64 和加宽 FP。

## 结构变化

| 指标 | A 硬件 | B 行为模型 |
|---|---:|---:|
| GRH graph operations | 7,203,931 | 7,140,001 |
| compute supernodes | 63,744 | 63,038 |
| C++ 源码字节数 | 1,264,626,115 | 1,248,311,184 |
| native binary 字节数 | 79,097,352 | 78,230,992 |
| register state slots | 208,964 | 208,872 |
| scalar register storage | 590,608 | 589,520 |
| event-edge slots | 412 | 412 |
| commit write count | 218,994 | 218,902 |
| state shadow | 0 | 0 |

B 的结构规模约小 0.9%，但完整模型的固定点调度、DiffTest、访存和其他功能逻辑仍占主要运行时间。
因此不能把局部乘法 helper 的收益直接外推到完整 SimTop。

## 性能结果

测量固定在 node030、CPU96、NUMA node1、本地内存、ASLR 关闭、单线程、无 trace/诊断计数。
每组先预热，再进行 8 对交替 AB/BA；保留全部有效样本。

| 负载 | A 均值 | B 均值 | B/A−1 均值 | 95% 配对 bootstrap CI | B 更快 |
|---|---:|---:|---:|---|---:|
| CoreMark 100,000 周期 | 103.603 s | 104.332 s | +0.706974% | [+0.353768%, +1.056130%] | 2/8 |
| 定向乘法 100,000 周期 | 68.698 s | 69.225 s | +0.776006% | [−0.057124%, +1.530780%] | 1/8 |

CoreMark 的区间完全位于零以上，行为模型稳定回退。定向乘法负载虽然有一对明显加速，整体区间跨零，
仍不能宣称稳定收益。两组都没有满足追加同 binary A/A 的条件（bootstrap 区间上界均未低于零）。

局部 fixture 的四类模型仍分别通过 active/sparse/idle 门槛，说明直接乘法确实能显著降低纯乘法模型的
计算体；完整 S3 的结果说明其收益被整个处理器模型的调度和外围开销淹没。

## 结论与默认配置

本轮完成了四类乘法行为模型的功能链路、真实 FU wrapper、SoftFloat/乘积边界、完整 DiffTest/NEMU、
指令覆盖和两类整机负载验证。当前没有可信的完整 S3 仿真加速，默认配置继续为硬件实现；行为模型仅在
显式指定 `--wolvrix-sim-models int-mul,vec-int-mul,fp-mul,vec-fp-mul` 时启用。

机器可读汇总见 `wolvrix/build/artifacts/multiply-behavior/multiply-final-report-v2.json`，
完整 A/B 产物见 `build/xs/multiply_behavior_20261105_v2/`。
