# NO0373 Direct state-read 4 KiB alignment runtime gate

日期：2026-07-12

## 1. 有效性门禁

按 [NO0368](./NO0368_direct_state_read_align4k_probe_plan_20260712.md)，使用 CPU138、NUMA1、`setarch -R`
串行执行 aligned NO0300 / aligned direct / aligned NO0300 的 CoreMark 50k 五事件 A/B/A。

quiet gate 记录如下：

| Run | Attempt | CPU138 idle | CPU330 idle | Decision |
| --- | ---: | ---: | ---: | --- |
| baseline1 | 1 | 97.33% | 100.00% | reject |
| baseline1 | 2 | 99.33% | 100.00% | run |
| direct | 1 | 98.33% | 100.00% | reject |
| direct | 2 | 99.67% | 99.67% | run |
| baseline2 | 1 | 99.67% | 99.00% | run |

全机 load 约 `8~13/384`，没有其他 emu/perf；低于门限的样本均保留后等待重测。三轮均以 exit 0 到达 guest
cycles `50001`、`cycleCnt=49996`、`instrCnt=73580`、terminal PC `0x80001312`，无 mismatch、assertion、
abort、fatal/error 或 `input_fullpass_blocked`。五项 PMU 均为 `100.00%` 调度。

两次 baseline difftest state pointer 都是 `0x55555b13dd30`，direct 为 `0x55555b039d30`，同一 binary 的
fixed mapping 可重复。baseline Host time/cycles spread 为 `0.203%/0.291%`，通过 `<=1%` 门限。

## 2. 原始计数

| Run | Host time (ms) | Host cycles | Instructions | Frontend empty | cmask6 cycles | Backend stalls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| aligned baseline1 | 83,462 | 305,917,175,775 | 172,879,599,298 | 1,430,768,989,084 | 190,647,885,245 | 93,858,635,757 |
| aligned direct | 75,919 | 278,534,096,737 | 166,888,633,421 | 1,274,893,307,005 | 165,893,426,894 | 91,339,829,396 |
| aligned baseline2 | 83,632 | 306,809,196,466 | 172,879,599,043 | 1,435,699,925,860 | 191,497,900,868 | 93,914,562,221 |

以两次 baseline 均值计算：

| Metric | Aligned baseline mean | Aligned direct | Delta |
| --- | ---: | ---: | ---: |
| Host time | 83,547.0 ms | 75,919 ms | -9.130% |
| Host cycles | 306,363,186,120.5 | 278,534,096,737 | -9.084% |
| Instructions | 172,879,599,170.5 | 166,888,633,421 | -3.465% |
| Frontend empty | 1,433,234,457,472.0 | 1,274,893,307,005 | -11.048% |
| cmask6 cycles | 191,072,893,056.5 | 165,893,426,894 | -13.178% |
| Backend stalls | 93,886,598,989.0 | 91,339,829,396 | -2.713% |

direct 少执行约 5.991B host instructions，同时少消耗约 27.829B cycles。按 aligned baseline CPI 折算，删指令只
解释约 10.617B cycles，另外约 17.212B 来自更有利的 CPI/native layout。

## 3. stall density

| Metric per host cycle | Aligned baseline | Aligned direct | Delta |
| --- | ---: | ---: | ---: |
| Host IPC | 0.564296 | 0.599168 | +6.180% |
| Frontend empty slots | 4.678220 | 4.577153 | -2.160% |
| cmask6 cycles | 0.623681 | 0.595595 | -4.503% |
| Backend stall slots | 0.306455 | 0.327931 | +7.008% |
| Remaining bandwidth slots | 0.936134 | 1.003585 | +7.205% |

alignment 后 NO0365 的 full-empty 前端回退消失并反转；direct 的绝对 frontend/backend stalls 都下降，但 cycles
下降更快，使 backend/bandwidth density 上升。当前剩余 CPI 约束重新偏向 backend，而不是 full-empty frontend。

## 4. 与未对齐结果的因果对照

| Relative direct effect | Unaligned NO0365 | Aligned NO0368 | Swing |
| --- | ---: | ---: | ---: |
| Host cycles | +6.263% | -9.084% | -15.347 pp |
| Instructions | -3.466% | -3.465% | +0.001 pp |
| cmask6 density | +5.839% | -4.503% | -10.342 pp |

动态指令收益不随 alignment 改变，但 cycles 和 cmask6 方向完全反转，直接证明 NO0365 回退不是 direct-read 语义
或 activation 工作的固有成本，而是 native address layout 压过了删指令收益。

不过 4 KiB alignment 不是中性控制。相对各自 unaligned fixed-ASLR 数据：

| Alignment effect | NO0300 baseline | Direct |
| --- | ---: | ---: |
| Host cycles | +7.843% | -7.732% |
| Instructions | -0.000292% | -0.000185% |
| cmask6 absolute | +13.472% | -12.403% |
| cmask6 density | +5.219% | -5.062% |

alignment 对两版产生方向相反的大扰动。两边 117 个 entry 的 low-12 offset 虽都归零，但只有 2 个对应 batch 的
完整入口地址相同，另外 115 个仍因前序函数跨页数量不同而漂移。因此 `-9.084%` 不能直接解释为 direct 机制固有
收益，也不能把统一 4 KiB alignment 作为默认优化。

## 5. 与 GSim gap

复用 [NO0344](./NO0344_fixed_aslr_gsim_grhsim_direct_compare_gate_20260712.md) 的 GSim mean：

| Metric | Aligned direct / GSim | Canonical NO0300 / GSim |
| --- | ---: | ---: |
| Host cycles | 2.460x | 2.489x |
| Instructions | 2.084x | 2.159x |
| Backend density | 1.547x | 1.565x |

aligned direct 比 NO0344 canonical NO0300 少 `1.198%` cycles，只关闭原 excess-cycle gap 的 `2.003%`。这比 aligned
pair 内的 `-9.084%` 小得多，再次说明 pair 收益主要来自 alignment 同时伤害 baseline、改善 direct。direct 确实缩小
了 instruction gap，但距离 GSim 仍有 `2.084x` instructions 和 `2.460x` cycles。

## 6. 结论与下一步

本轮已把 NO0365 的回退定位为 code layout 敏感性，而非 direct state-read 的功能或固有动态成本。下一步不立即
fresh runtime-profile，也不保留 4 KiB alignment；应构造更严格的 exact-entry probe：复用 baseline/direct O3
objects，把每对同名 model object 的 `.text` section 尾部 padding 到共同最大尺寸，保持函数 body、symbol size、
archive order 和动态 instructions 不变，使 117 个对应 batch 的完整入口地址逐项相同。

若 exact-entry A/B/A 中 direct 仍加速，才能量化删 state-read 扫描的布局隔离收益；若再次回退，则问题来自函数内部
basic-block layout 或动态访问序列。该 probe 需先单独记录计划和 object/relocation/function-size 门禁。

## 7. 产物

```text
build/logs/xs_perf/no0368/fixed_align4k_{baseline1,direct,baseline2}_emu.log
build/logs/xs_perf/no0368/fixed_align4k_{baseline1,direct,baseline2}_perf.csv
build/logs/xs_perf/no0368/fixed_align4k_*_quiet_gate_attempt_*.log
build/logs/xs_perf/no0368/fixed_align4k_summary.report
```
