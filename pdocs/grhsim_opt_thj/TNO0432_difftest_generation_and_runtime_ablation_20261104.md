# TNO0432：DiffTest 模型采集路径与运行时检查的分层消融

日期：2026-11-04。

本轮把 DiffTest 的成本拆成两部分分别测量。A/B 比较 GrhSIM/C++ 模型是否包含采集与检查支持；A′/B
比较在相同采集模型上，运行时是否加载 NEMU 并执行 DiffTest 检查。

## 配置

| 配置 | RTL 生成 | GrhSIM/C++ 模型 | harness | 运行时 |
| --- | --- | --- | --- | --- |
| A | DiffTest 开启，106 个接口 | 采集路径关闭 | `NO_DIFF=1` | `--no-diff` |
| A′ | 与 B 相同 | 采集路径开启 | `NO_DIFF=0` | `--no-diff` |
| B | 与 A/A′ 相同 | 采集路径开启 | `NO_DIFF=0` | `--diff`，加载 NEMU |

A 和 B 使用同一份已生成的 DiffTest RTL；A 的区别在于 Wolvrix 读入时不定义 `DIFFTEST`，
并以 `NO_DIFF=1` 编译 harness。A′ 直接复用 B 的模型目录和相同的采集支持，仅以
`NO_DIFF=1` 编译并用 `--no-diff` 运行。因此 A′/B 只改变运行时检查开关。

三组均使用 `coremark-2-iteration.bin`、100,000 guest cycles、seed 0、CPU96、NUMA node 1、
固定 ASLR 和单线程 native GrhSIM。正式运行关闭 trace、footprints 和额外诊断；每组先 warmup，
再做 8 对 AB/BA。node030 上仍有其他任务，但它们没有覆盖 CPU96 或 SMT sibling 288；每个样本
都通过 CPU affinity、SMT sibling、NUMA locality、周期数和 UART 检查。诊断阶段的访存指纹使用
1 GiB RAM，仅用于一致性检查，不计入 walltime。

## A/B：模型采集路径的影响

百分比为 `100 × (B_host / A_host − 1)`，正数表示 B 更慢。

| pair | 顺序 | A / s | B / s | B/A−1 |
| ---: | :---: | ---: | ---: | ---: |
| 0 | AB | 81.257 | 98.060 | +20.679% |
| 1 | BA | 80.903 | 98.381 | +21.604% |
| 2 | AB | 85.059 | 97.341 | +14.439% |
| 3 | BA | 81.751 | 98.167 | +20.080% |
| 4 | AB | 81.540 | 98.146 | +20.365% |
| 5 | BA | 80.898 | 97.283 | +20.254% |
| 6 | AB | 86.252 | 98.164 | +13.811% |
| 7 | BA | 80.874 | 98.123 | +21.328% |

| 指标 | 数值 |
| --- | ---: |
| A 平均 / 中位数 | 82.316750 / 81.398500 s |
| B 平均 / 中位数 | 97.958125 / 98.134500 s |
| 配对变化均值 / 中位数 | +19.070082% / +20.309682% |
| paired bootstrap 95% CI | [+16.777212%, +20.848009%] |
| B 更快 | 0/8 |

两端 100,000 周期的首次访存 footprint 均为 14,656 字节，SHA256 均为
`10a8932701c8fb78f3128f554f7f00c6be5802d8dcc63c3c5c77d29c4b710f7f`，UART 均为
`Running CoreMark for 2 iterations`。B 的 PC 为 `0x80000c0c`、提交指令数为 240349、
DiffTest cycleCnt 为 99996；A 没有这些采集字段，但 guest cycles 均为 100001。

## A′/B：运行时检查本身的影响

A′ 和 B 都保留采集路径，且每一对的 PC、提交指令数和 cycleCnt 完全相同。百分比为
`100 × (B_host / A′_host − 1)`。

| pair | 顺序 | A′ / s | B / s | B/A′−1 |
| ---: | :---: | ---: | ---: | ---: |
| 0 | A′B | 97.150 | 97.685 | +0.551% |
| 1 | BA′ | 97.260 | 97.861 | +0.618% |
| 2 | A′B | 97.116 | 97.630 | +0.529% |
| 3 | BA′ | 97.021 | 98.471 | +1.495% |
| 4 | A′B | 97.620 | 97.788 | +0.172% |
| 5 | BA′ | 97.804 | 97.889 | +0.087% |
| 6 | A′B | 97.842 | 98.460 | +0.632% |
| 7 | BA′ | 100.451 | 98.340 | −2.102% |

| 指标 | 数值 |
| --- | ---: |
| A′ 平均 / 中位数 | 97.783000 / 97.440000 s |
| B 平均 / 中位数 | 98.015500 / 97.875000 s |
| 配对变化均值 / 中位数 | +0.247691% / +0.539979% |
| paired bootstrap 95% CI | [−0.520546%, +0.807736%] |
| B 更快 | 1/8 |

区间跨零，且 pair07 有一次 A′ 的约 100.5 秒异常样本。因此本轮不能把约 0.25% 的均值
解释成稳定的运行时检查开销；在该负载和测量噪声下，A′ 与 B 的差异不可辨识。

## 结构与二进制对照

| 指标 | A | A′ | B |
| --- | ---: | ---: | ---: |
| DiffTest RTL 接口 | 106 | 106 | 106 |
| model 文件数 | 265 | 271 | 271 |
| model 目录字节数 | 1,401,183,547 | 1,492,714,510 | 1,492,714,510 |
| C++/header 源字节数 | 1,193,528,652 | 1,272,538,177 | 1,272,538,177 |
| native binary 字节数 | 73,454,048 | 79,101,024 | 79,101,024 |

A′ 和 B 的 model C++ 内容相同，binary 大小相同但 SHA256 不同，差异来自 harness 的
`NO_DIFF=1`/`NO_DIFF=0` 编译。A/B 的模型目录增加约 6.6%，binary 增加约 7.7%，与其
约 19.1% 的运行时间差方向一致。A′/B 没有模型规模差异，所以只剩运行时路径可归因。

## 结论

在本次 CoreMark、CPU96 和 native 单线程口径下，主要差异来自**模型生成/编译时移除 DiffTest
采集支持**：A 相对 B 平均快约 19.07%，8/8 对更快。仅关闭运行时 NEMU 检查而保留采集
模型（A′）没有测出稳定收益：B 相对 A′ 平均慢 0.248%，但 95% 区间跨零。

因此，若只在运行命令中关闭 DiffTest，预期收益很小；要获得本轮可重复的差异，需要在模型生成
和模型编译阶段同时移除采集路径。这里的 A/B 使用相同的 106 接口 DiffTest RTL，并没有重新测量
Chisel 硬件生成阶段关闭 DiffTest 的效果；该效果记录在 TNO0401。这个结论限定于当前负载、模型和“运行时完全停用”的
实验口径，不延伸到其他 workload 或多线程流程。

## 产物与验证

- [A/B summary](../../build/xs/difftest_runtime_20261104_v1/A-vs-B/summary.json)
- [A/B pairs](../../build/xs/difftest_runtime_20261104_v1/A-vs-B/pairs.csv)
- [A′/B summary](../../build/xs/difftest_runtime_20261104_v1/Aprime-vs-B/summary.json)
- [A′/B pairs](../../build/xs/difftest_runtime_20261104_v1/Aprime-vs-B/pairs.csv)
- [A/B manifest](../../build/xs/difftest_runtime_20261104_v1/A-vs-B/manifest.json)
- [A′/B manifest](../../build/xs/difftest_runtime_20261104_v1/Aprime-vs-B/manifest.json)
- 中断且未计入测量的旧目录：[ABORTED.md](../../build/xs/difftest_runtime_20261103_v4/A-vs-B/ABORTED.md)

本轮 focused tests 共 22 项通过；未运行全量回归。
