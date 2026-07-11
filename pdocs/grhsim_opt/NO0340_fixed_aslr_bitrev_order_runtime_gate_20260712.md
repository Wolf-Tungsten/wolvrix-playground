# NO0340 Fixed-ASLR bit-reversal order runtime gate

日期：2026-07-12

## 1. 口径与有效性

按 [NO0339](./NO0339_fixed_aslr_mapping_probe_20260712.md)，三轮均使用 `setarch -R` 固定 emu text base，
并固定 CPU138、NUMA node 1，执行 numeric NO0300 / bit-reversal NO0300 / numeric NO0300 的 CoreMark
50k。NO0338 标记无效的旧 numeric1 不进入统计。

三轮都完成 `50001` guest cycles，得到 `cycleCnt = 49996`、`instrCnt = 73580` 和 terminal PC
`0x80001312`；无 mismatch/assertion/abort。cycles、instructions、frontend empty、cmask6 四项全部为
`100.00%` 调度。

运行前全机 load 约 `2.7~3.4/384`；CPU138 与 sibling 330 基本空闲。两次 numeric Host time spread
为 `0.349%`，cycles spread 为 `0.351%`，A/B/A 稳定性通过。

## 2. 原始计数

| Run | Host time (ms) | Host cycles | Instructions | Frontend empty slots | cmask6 cycles |
| --- | ---: | ---: | ---: | ---: | ---: |
| numeric1 | 77,199 | 282,580,179,927 | 172,879,702,674 | 1,289,854,940,501 | 167,092,976,571 |
| bit-reversal | 76,763 | 280,975,963,662 | 172,879,701,836 | 1,279,678,660,819 | 165,591,159,292 |
| numeric2 | 77,469 | 283,573,009,608 | 172,879,702,269 | 1,294,421,463,601 | 167,862,061,252 |

以两次 numeric 均值计算：

| Metric | Numeric mean | Bit-reversal | Absolute delta | Per-cycle delta |
| --- | ---: | ---: | ---: | ---: |
| Host time | 77,334 ms | 76,763 ms | -0.738% | - |
| Host cycles | 283,076,594,767.5 | 280,975,963,662 | -0.742% | - |
| Instructions | 172,879,702,471.5 | 172,879,701,836 | -0.0000004% | +0.748% |
| Frontend empty slots | 1,292,138,202,051 | 1,279,678,660,819 | -0.964% | -0.224% |
| cmask6 cycles | 167,477,518,911.5 | 165,591,159,292 | -1.126% | -0.387% |

frontend 分解为：

| Metric | Numeric mean | Bit-reversal | Absolute delta | Per-cycle delta |
| --- | ---: | ---: | ---: | ---: |
| Latency slots | 1,004,865,113,469 | 993,546,955,752 | -1.126% | -0.387% |
| Bandwidth slots | 287,273,088,582 | 286,131,705,067 | -0.397% | +0.347% |

input objects、batch bodies 和 dynamic instructions 不变时，物理顺序带来 `0.74%` cycles 收益，并伴随
cmask6 density `-0.39%`。方向自洽，但收益只约为 numeric spread 的 2.1 倍；单次 bit-reversal 尚不足以
作为默认布局。即使复现，该幅度也只能解释历史约 4% 回退的一小部分。

## 3. Fixed ASLR 的影响

本轮 numeric mean 与同一 NO0300 binary 的历史随机基址数据比较：

```text
vs NO0317 cycles: -8.157%
vs NO0328 cycles: -8.797%
```

该变化远大于 bit-reversal 顺序收益，也大于此前 NO0286/NO0300 相对回退。它确认 NO0338 不是纯理论风险：
PIE load base 是 SimTop frontend 性能的一级变量。后续任何 old/new/GSim 比较都必须 fixed-ASLR 重跑，不能继续
引用随机基址下约 4% 的方向作为当前事实。

## 4. 结论与下一步

无 padding sched 重排产生小幅正向信号，证明 archive order 是可操作的 layout knob，但 bit-reversal 不是主要
解法。下一步优先使用 fixed-ASLR 重跑 NO0286/NO0300 old/new/old，重新判断 ordered affine 变更的净性能；
随后固定同一口径复测 GSim，更新 GrhSIM/GSim 差距。bit-reversal 可再补一轮确认，但不阻塞更高优先级的
fixed-ASLR 基线校准。

## 5. 产物

```text
build/logs/xs_perf/no0334/fixed_numeric1_emu.log
build/logs/xs_perf/no0334/fixed_numeric1_perf.csv
build/logs/xs_perf/no0334/fixed_bitrev_emu.log
build/logs/xs_perf/no0334/fixed_bitrev_perf.csv
build/logs/xs_perf/no0334/fixed_numeric2_emu.log
build/logs/xs_perf/no0334/fixed_numeric2_perf.csv
```
