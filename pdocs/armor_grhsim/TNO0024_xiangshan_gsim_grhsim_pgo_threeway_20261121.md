# TNO0024　GSIM PGO、原 GrhSIM PGO 与新 GrhSIM PGO 的同轮复测

在 node030 的 CPU 96 上，每个版本均按相同周期上限运行。新 GrhSIM 相对原 GrhSIM 的同轮平均耗时变化为 CoreMark **−10.14%**、MicroBench **−10.87%**。相对原样 GSIM，新 GrhSIM 的耗时分别为 **+9.95%**、**+5.74%**。

## 实测耗时

表内单位为秒。每格是四次正式运行的外部 walltime 算术平均。[32 次原始计时](./data/TNO0024_pgo_threeway_times.csv)

| 负载 | 原样 GSIM PGO | 原 GrhSIM PGO | 新 GrhSIM PGO | GSIM PGO，两处统计 DPI 置零 |
| --- | ---: | ---: | ---: | ---: |
| CoreMark | 72.68 | 88.93 | 79.92 | 60.89 |
| MicroBench | 68.54 | 81.31 | 72.47 | 57.51 |

下表先对同轮的两个耗时求比值，减一后取四轮算术平均。分母写在斜线右侧，负值表示左侧版本用时更少。方括号为固定种子对四个配对比值重采样 10,000 次得到的 95% 区间。[配对统计](../../build/armor-xs-pgo-threeway-v1/summary.json)

| 同轮耗时比较 | CoreMark | MicroBench |
| --- | ---: | ---: |
| 新 GrhSIM / 原 GrhSIM | −10.14% [−10.35%, −9.99%] | −10.87% [−10.95%, −10.73%] |
| 原 GrhSIM / 原样 GSIM | +22.35% [+22.01%, +22.89%] | +18.63% [+17.58%, +19.69%] |
| 新 GrhSIM / 原样 GSIM | +9.95% [+9.73%, +10.17%] | +5.74% [+4.88%, +6.65%] |
| 原 GrhSIM / DPI 对齐 GSIM | +46.05% [+45.07%, +46.60%] | +41.38% [+40.29%, +42.61%] |
| 新 GrhSIM / DPI 对齐 GSIM | +31.24% [+30.47%, +31.95%] | +26.02% [+25.24%, +27.02%] |
| DPI 对齐 GSIM / 原样 GSIM | −16.22% [−16.71%, −15.73%] | −16.09% [−16.85%, −15.26%] |

以原样 GSIM 为基准，CoreMark 中原、新 GrhSIM 分别多用 16.25 s 和 7.23 s，收回原来差额的 55.5%。MicroBench 对应的差额为 12.77 s 和 3.93 s，收回 69.2%。这里用各版实测的平均秒数计算差额。

## 对照口径与历史基线

原样 GSIM 执行 XiangShan 的两处组合 top-down 统计 DPI，GrhSIM 在读入时忽略这两处调用。额外的 GSIM 对照取自 TNO0022，在这两处把输出置零，沿用其独立训练的 PGO ELF。两种 GSIM 在本轮两个负载的 99,999 条 DiffTest 活跃字段记录均逐条匹配。本次轨迹核对单独在 node029 上进行。[DPI 口径由来](./TNO0022_grhsim_gsim_gap_causes_20261121.md) · [CoreMark 核对](../../build/armor-xs-pgo-threeway-v1/verify/coremark/result.json) · [MicroBench 核对](../../build/armor-xs-pgo-threeway-v1/verify/microbench/result.json)

TNO0022 的原 GrhSIM 在 CoreMark 为 78.70 s，TNO0023 的新 GrhSIM 为 78.24 s，两者跨批次只差 0.46 s。同一份原 GrhSIM ELF 在 TNO0023 用了 86.11 s，本轮为 88.93 s。本次同轮比较缩短了 9.01 s。历史两组各四次的进程监控中，原 GrhSIM 在首末进程样本间的 CPU 时间占比均超过 99.9%，按用户态与内核态 tick 增量除以采样间隔计算。历史记录确认了绝对耗时漂移，单一宿主原因尚未定位。[TNO0022 逐次秒数](./data/TNO0022_times.csv) · [TNO0023 逐次秒数](./data/TNO0023_times.csv)

## 逐轮数据

| 负载 | 轮次 | 原样 GSIM | 原 GrhSIM | 新 GrhSIM | DPI 对齐 GSIM |
| --- | ---: | ---: | ---: | ---: | ---: |
| CoreMark | 1 | 72.48 | 88.43 | 79.55 | 60.30 |
| CoreMark | 2 | 73.37 | 89.66 | 80.74 | 61.18 |
| CoreMark | 3 | 73.14 | 90.09 | 80.67 | 61.53 |
| CoreMark | 4 | 71.75 | 87.55 | 78.71 | 60.56 |
| MicroBench | 1 | 69.21 | 81.30 | 72.42 | 57.52 |
| MicroBench | 2 | 69.41 | 82.61 | 73.59 | 57.74 |
| MicroBench | 3 | 67.70 | 81.48 | 72.55 | 57.72 |
| MicroBench | 4 | 67.85 | 79.84 | 71.32 | 57.05 |

## 运行与核验

沿用 TNO0021 的单核 XiangShan DefaultConfig、Clang 23.1.2、相同的 CoreMark 训练窗口和 NEMU 参考库。新 GrhSIM 是 TNO0023 的最终联合版，启用三组规则、计算超节点上限 160、最多 16 个寄存器的成块提交和 mux 门槛 16。MicroBench 未参与训练。本次直接使用归档的四份 profile-use ELF，测量前后均核验文件哈希。[输入与可执行文件清单](../../build/armor-xs-pgo-threeway-v1/policy.json) · [GrhSIM 新配置](./TNO0023_grhsim_commit_pgo_partition_mux_20261121.md)

| ELF | SHA-256 |
| --- | --- |
| 原样 GSIM PGO | `0f88df83fee136525d03addbec6ccd7d46c2b3c58603e244fe39a390eb90db57` |
| 原 GrhSIM PGO | `0707b81b7667325f2ec887a3189f6e7006efb65f2bbe52b7d1fdf178e4072837` |
| 新 GrhSIM PGO | `340edaeec5b053e3cd47280f0588c7c695e6fb05095c5d9e67c2606fcaf33fb0` |
| GSIM PGO，两处统计 DPI 置零 | `4d90afe83d56144ab96bf0b0504489f328f2cff02371d0f545846e6c20a93397` |

每个负载和版本各预热一次，随后四轮，每个版本在四个位置各出现一次。同一轮内的四次运行串行，CPU 96 的测量锁贯穿两种负载。固定 seed 0、NUMA 1、单线程、关闭 ASLR、开启 DiffTest。核查模拟器实际线程和 CPU 亲和性、代码与数据页位置、NEMU 映射及每次运行的固件输出、停止 PC、提交数和周期数。32 次正式样本中 SMT 兄弟 CPU 288 的最低空闲率为 99.98%。所有配对块均在首次运行时通过放置与空闲检查。[计时驱动](../../scripts/armor_xs_pgo_threeway.py) · [逐轮运行与位置记录](../../build/armor-xs-pgo-threeway-v1/rounds.json)

两后端都用 `-C 100000`，都报告 100,001 个 guest cycles。GSIM 的末端架构周期为 99,997，GrhSIM 为 99,995。CoreMark 分别提交 250,845 / 250,838 条，MicroBench 分别为 138,523 / 138,514 条，各自与同后端的冻结参考匹配。过去已对齐两个后端在共同区间的提交序列，时间比较覆盖两个固定窗口。[历史提交序列核对](../../build/armor-xs-pgo-v1/cross-engine-commit-prefix.json)

另建目录复测可在 node030 运行 `python3 scripts/armor_xs_pgo_threeway.py --output build/新的输出目录`。在 node029 另加 `--verify-matched` 可对照两份 GSIM 轨迹。计时完成后，`--export-csv 路径` 可从已接受的样本重新导出 CSV。
