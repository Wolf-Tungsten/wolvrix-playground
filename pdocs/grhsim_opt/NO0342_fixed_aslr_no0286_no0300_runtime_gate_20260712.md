# NO0342 Fixed-ASLR NO0286 / NO0300 runtime gate

日期：2026-07-12

## 1. 口径与有效性

按 [NO0341](./NO0341_fixed_aslr_no0286_no0300_recalibration_plan_20260712.md)，使用原始无插桩 emu，
以 `setarch -R`、CPU138、NUMA node 1 执行 NO0286 / NO0300 / NO0286 的 CoreMark 50k A/B/A。
三轮开始前全机 load 约为 `3.0~4.8/384`，CPU138/330 短时平均空闲均不低于约 `96%`。

三轮均完成 `50001` guest cycles，得到 `cycleCnt = 49996`、`instrCnt = 73580` 和 terminal PC
`0x80001312`；没有 mismatch/assertion/abort。cycles、instructions、frontend empty、cmask6 四项均为
`100.00%` 调度。两次 NO0286 的 fixed address 运行还得到完全相同的 difftest state pointer
`0x55555b82cd30`。

NO0286 Host time spread 为 `0.266%`，host cycles spread 为 `0.288%`，均通过计划中的 `1%` 门限。

## 2. 原始计数

| Run | Host time (ms) | Host cycles | Instructions | Frontend empty slots | cmask6 cycles |
| --- | ---: | ---: | ---: | ---: | ---: |
| NO0286 old1 | 81,085 | 296,693,879,641 | 188,838,091,961 | 1,349,962,728,377 | 174,219,440,165 |
| NO0300 new | 77,319 | 283,010,641,755 | 172,878,903,261 | 1,292,915,608,828 | 167,606,568,836 |
| NO0286 old2 | 81,301 | 297,549,973,489 | 188,838,092,054 | 1,354,174,795,493 | 174,965,085,611 |

以两次 NO0286 均值计算：

| Metric | NO0286 mean | NO0300 | Absolute delta | Per-cycle delta |
| --- | ---: | ---: | ---: | ---: |
| Host time | 81,193 ms | 77,319 ms | -4.771% | - |
| Host cycles | 297,121,926,565 | 283,010,641,755 | -4.749% | - |
| Instructions | 188,838,092,007.5 | 172,878,903,261 | -8.451% | -3.887% |
| Frontend empty slots | 1,352,068,761,935 | 1,292,915,608,828 | -4.375% | +0.393% |
| cmask6 cycles | 174,592,262,888 | 167,606,568,836 | -4.001% | +0.785% |

frontend 分解为：

| Metric | NO0286 mean | NO0300 | Absolute delta | Per-cycle delta |
| --- | ---: | ---: | ---: | ---: |
| Latency slots | 1,047,553,577,328 | 1,005,639,413,016 | -4.001% | +0.785% |
| Bandwidth slots | 304,515,184,607 | 287,276,195,812 | -5.661% | -0.957% |

NO0300 仍有很小的 full-empty frontend density 增量，但绝对 stall 和总 cycles 均下降；它不再抵消
ordered lowering 带来的动态工作缩减。

## 3. Dynamic work 归一化

复用 [NO0312](./NO0312_no0286_no0300_dynamic_work_gate_20260712.md) 的同 workload `work_total`：

```text
NO0286 = 87,495,065,123
NO0300 = 83,730,351,495 (-4.303%)
```

得到：

| Metric per work | NO0300 vs NO0286 |
| --- | ---: |
| Host cycles / work | -0.467% |
| Instructions / work | -4.335% |
| Frontend empty / work | -0.075% |
| cmask6 / work | +0.315% |

因此 [NO0312](./NO0312_no0286_no0300_dynamic_work_gate_20260712.md) 在随机 PIE 基址下得到的
cycles/work `+8.52%` 不是模型固有成本。fixed-ASLR 下单位工作成本约持平并略有改善，`4.30%` 的 work
缩减转化成了 `4.75%` 的 host-cycle 收益。

## 4. 与历史随机基址数据的关系

fixed NO0286 mean 相对历史 old mean 仅变化 `+0.47%`（NO0317）和 `+0.96%`（NO0328）；fixed NO0300
却分别变化 `-8.18%` 和 `-8.82%`。因此此前 old/new 约 `+4%~+5%` 的回退主要来自随机 load base
对两版不同 native layout 的非对称影响，而不是 ordered-affine 增加了动态工作或稳定的单位 work 成本。

NO0300 的 generated-code 缩减、功能、dynamic work 和本轮 fixed-ASLR 加速结论有效。NO0302、NO0312、
NO0315、NO0317、NO0319、NO0321、NO0323、NO0328 中依赖未固定 PIE 基址的相对 runtime 幅度与
root-cause 强度应视为被 ASLR 混淆；其中事件接线、功能结果和不依赖 wall time 的结构/动态计数仍可复用。

fixed-ASLR 只提供可复现的单一 native address layout，不代表随机 ASLR 分布的均值。因此本轮证明的是
NO0300 在受控地址下优于 NO0286，并揭示地址布局是一级性能变量；若实际运行仍启用 ASLR，还需单独评估
多基址分布或采用稳定的非 PIE/link layout。

## 5. 结论与下一步

ordered-affine NO0300 在受控地址下功能正确且相对 NO0286 加速 `4.75%`，应恢复为可保留候选。下一步对
GSim 使用同一 `setarch -R`、CPU138、NUMA1、CoreMark 50k 和配对基线，更新 GrhSIM/GSim 的绝对差距，
并检查 GSim 对固定基址是否也有同等级变化。完成直接对比后，再决定优先优化 GrhSIM 的 dynamic
instructions、frontend layout，还是先把稳定地址策略纳入正式运行方式。

## 6. 产物

```text
build/logs/xs_perf/no0341/fixed_old1_emu.log
build/logs/xs_perf/no0341/fixed_old1_perf.csv
build/logs/xs_perf/no0341/fixed_new_emu.log
build/logs/xs_perf/no0341/fixed_new_perf.csv
build/logs/xs_perf/no0341/fixed_old2_emu.log
build/logs/xs_perf/no0341/fixed_old2_perf.csv
```
