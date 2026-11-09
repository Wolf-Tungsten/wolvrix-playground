# TNO0451：整数与位运算行为模型的完整 S3 验收（2026-11-08）

本轮把已通过局部功能和性能门的四类无状态行为模型带入完整 XiangShan S3：`int-alu`、`int-bku`、`vec-int-alu-lane` 和 `vec-int-pu-lane`。A 是全硬件模型；B 只启用这四类模型，并使用 `kBehaviorComputeGroup` grouped lowering。两组都保留完整 DiffTest/NEMU、断言、flush 和原有流水寄存器；未叠加 PopCount、commit-rat、乘法或 whole-unit 模型。

## 构建和功能配置

两组在同一源码和工具快照下串行生成 RTL，再分别经过相同的 Wolvrix import、reg-to-mem、activity schedule、C++ 发射和 Clang 23/O3 编译。A 的 simulation model manifest 为 `hardware` 且模型数为 0；B 的 manifest 为 `int-alu,int-bku,vec-int-alu-lane,vec-int-pu-lane`、`compute_lowering=grouped`，共 12 个实际 carrier 实例：6 个标量 ALU、1 个 BKU、4 个向量 ALU lane、1 个向量 PU lane。B 的生成 C++ 中对应出现 6、1、4、1 个行为 helper 调用点。

两组各完成 10,000 周期 smoke 和两个 100,000 周期 CoreMark trace。PC、提交指令数、周期数和所有生成的 DiffTest 字段逐记录一致；两组 trace 文件 SHA-256 完全相同。功能门记录在 `build/xs/integer_bit_20261107_v1/verification-v1/verification-complete.json`。

## GRH 和产物变化

| 指标 | A 硬件 | B grouped | B 相对 A |
|---|---:|---:|---:|
| graph ops | 7,203,931 | 7,176,031 | −0.387% |
| graph values | 6,832,832 | 6,805,236 | −0.404% |
| supernodes | 63,744 | 63,379 | −0.573% |
| compute supernodes | 63,276 | 62,911 | −0.577% |
| compute nodes | 1,081,888 | 1,076,412 | −0.506% |
| activity boundary edges | 1,977,256 | 1,971,607 | −0.286% |
| C++ 源码 | 1,264,544,349 B | 1,260,039,582 B | −0.356% |
| native binary | 79,093,256 B | 78,585,480 B | −0.642% |

结构规模只减少约千分之几，说明局部 carrier 的巨大 fixture 收益没有转化为全芯片图规模变化；本轮仍没有引入新的状态节点。

## CoreMark 性能

计时固定 node030、CPU96、单线程、NUMA 本地内存、100,000 周期、关闭 trace 和诊断计数，运行时 DiffTest 保持开启。按用户要求跳过外部 CPU 空闲 admission 检查，但每次仍检查 CPU 亲和、单线程和 NUMA locality。百分比定义为 `B/A−1`，负值表示 B 更快。

| pair | 顺序 | A (s) | B (s) | B−A |
|---:|:---:|---:|---:|---:|
| 0 | AB | 100.527 | 100.589 | +0.062% |
| 1 | BA | 100.123 | 100.376 | +0.253% |
| 2 | AB | 99.976 | 98.095 | −1.881% |
| 3 | BA | 98.279 | 97.911 | −0.374% |
| 4 | AB | 98.810 | 98.825 | +0.015% |
| 5 | BA | 98.805 | 98.978 | +0.175% |
| 6 | AB | 98.882 | 99.099 | +0.219% |
| 7 | BA | 98.562 | 98.642 | +0.081% |

A 均值为 **99.2455 s**，B 均值为 **99.0644 s**，配对均值为 **−0.181330%**；中位数变化为 **+0.071421%**，只有 **2/8** 对 B 更快。固定种子 paired bootstrap 95% CI 为 **[−0.701011%, +0.153807%]**，跨过零，因此不能宣称稳定整机加速。

原始结果和哈希集中在 [integer-bit-xs-20261107](../../wolvrix/build/artifacts/behavior-model/integer-bit-xs-20261107/)，机器可读汇总为 [`report.json`](../../wolvrix/build/artifacts/behavior-model/integer-bit-xs-20261107/report.json)，逐对数据为 [`pairs.csv`](../../build/xs/integer_bit_20261107_v1/comparison-v1/pairs.csv)。

## 结论

四类整数/位运算行为模型在完整 S3 中保持了 DiffTest 功能和逐周期轨迹一致，grouped 图和 binary 略小，但 CoreMark 只得到 −0.18% 的点估计且区间跨零。局部 carrier 的收益被完整处理器中其他组合逻辑、调度和状态更新成本稀释；本轮不把模型加入默认配置，继续保持 `--wolvrix-sim-models hardware` 和 ordinary lowering。
