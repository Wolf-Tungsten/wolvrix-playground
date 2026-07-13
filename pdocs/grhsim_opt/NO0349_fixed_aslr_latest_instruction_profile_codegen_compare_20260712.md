# NO0349 Fixed-ASLR latest instruction profile and codegen compare

日期：2026-07-12

## 1. 数据有效性

按 [NO0345](./NO0345_fixed_aslr_latest_instruction_profile_plan_20260712.md) 与
[NO0346](./NO0346_fixed_period_event_count_gate_correction_20260712.md)，使用 same-FIR GSim 和 latest NO0300
GrhSIM，在 CPU138、NUMA node 1、`setarch -R` 下采集 CoreMark 50k `instructions:u` fixed-period profile：

```text
period     = 25,000,000
call graph = dwarf,8192
GSim       = 3,201 samples / 80.025B approximate instructions
GrhSIM     = 6,914 samples / 172.850B approximate instructions
```

两边 `Total Lost Samples = 0`，分别耗时 `31,081/77,685 ms`，并都完成 `50,001` guest cycles：

| Simulator | `instrCnt / cycleCnt` | Terminal PC |
| --- | ---: | --- |
| GSim | `73584 / 49998` | `0x8000131e` |
| GrhSIM | `73580 / 49996` | `0x80001312` |

sample ratio 为 `2.159950x`，与 [NO0344](./NO0344_fixed_aslr_gsim_grhsim_direct_compare_gate_20260712.md)
的精确 perf-stat instruction ratio `2.159080x` 只差 `0.0403%`，通过修正后的 `0.5%` 门禁。本文的类别
share 使用精确 sample 数；由 `sample * period` 推导的 instruction 数只作近似归因，不替代 perf stat。

## 2. 最新指令分类

leaf-symbol 分类结果：

| Simulator / class | Samples | Share |
| --- | ---: | ---: |
| GSim `subStep*` | 3,170 | 99.0316% |
| GSim `step()` | 1 | 0.0312% |
| GSim other / unresolved | 30 | 0.9372% |
| GrhSIM compute batch | 5,822 | 84.2060% |
| GrhSIM commit batch | 874 | 12.6410% |
| GrhSIM `eval()` control | 24 | 0.3471% |
| GrhSIM generated helpers | 155 | 2.2418% |
| GrhSIM other / unresolved | 39 | 0.5641% |

GSim 的 top leaf 为 `subStep315/272/18/17/255/294/19`，samples 分别为
`100/66/56/54/48/42/40`。GrhSIM 的 top leaf 为：

| Symbol | Samples | Share |
| --- | ---: | ---: |
| `eval_commit_batch_115` | 287 | 4.15% |
| `eval_compute_batch_8` | 255 | 3.69% |
| `eval_compute_batch_1` | 218 | 3.15% |
| `eval_compute_batch_62` | 179 | 2.59% |
| `eval_compute_batch_61` | 177 | 2.56% |
| `eval_compute_batch_0` | 172 | 2.49% |
| `eval_commit_batch_105` | 162 | 2.34% |

热点分散在多个 batch；compute8 的 `255` samples 覆盖 `248` 条不同的非零采样指令，最大单指令只有
`1.18%`。因此没有一个 helper 或一条汇编能解释主要 gap，后续候选必须成批减少生成工作。

## 3. Approximate excess-instruction 归因

按相同 period 将类别折算为 approximate instructions：

```text
GSim all subSteps              =  79.250B
GrhSIM compute                 = 145.550B  (1.8366x GSim subSteps)
GrhSIM commit                  =  21.850B
GrhSIM compute + commit        = 167.400B  (2.1123x GSim subSteps)
```

以两边 profile 总量差 `92.825B` 为分母，算术拆分为：

| Component | Approximate instructions | Share of profile excess |
| --- | ---: | ---: |
| compute 超出全部 GSim subSteps 的部分 | 66.300B | 71.425% |
| GrhSIM commit | 21.850B | 23.539% |
| control/helper/other residual | 4.675B | 5.036% |

这不是逐条语义配对，但足以确定优化优先级：compute 是第一目标，commit 是明确的第二目标。结合 NO0344，
frontend empty/cmask6 density 并不差于 GSim，而 backend-stall density 为 `1.565x`；因此当前主线应先删动态
instructions，再观察剩余 backend CPI。

## 4. 相对 NO0278 的变化

用同一个 leaf parser 重算历史 NO0278 profile：

| Version | Total samples | Compute | Commit | Compute share | Commit share |
| --- | ---: | ---: | ---: | ---: | ---: |
| NO0278 | 7,617 | 6,651 | 754 | 87.3178% | 9.8989% |
| NO0300 | 6,914 | 5,822 | 874 | 84.2060% | 12.6410% |

NO0300 total/compute samples 分别下降 `9.229%/12.464%`，compute share 下降 `3.112 pp`；commit samples
增加 `15.915%`，share 增加 `2.742 pp`。由于这是不同 binary layout 的 fixed-period sampling，commit 的增量只作
近似趋势，不能声称为精确动态指令回退。NO0283 state-read slot alias 已明显降低 compute，但 commit 因而成为更大的
相对占比。

## 5. Generated C++ 直接对照

GrhSIM top batch 的函数 text 和 generated source 都很大：

| GrhSIM symbol | Text size | Source lines | Source bytes | Op comments |
| --- | ---: | ---: | ---: | ---: |
| compute0 | `0x15a8a0` | 295,158 | 27,547,100 | 56,738 |
| compute1 | `0x1bf21c` | 366,530 | 33,199,262 | 56,185 |
| compute8 | `0x1157a8` | 350,724 | 32,064,015 | 68,490 |
| compute61 | `0xf9954` | 123,338 | 14,352,273 | 26,141 |
| compute62 | `0xd0056` | 104,069 | 15,045,376 | 30,731 |
| commit105 | `0x140806` | 239,495 | 17,847,304 | 18,439 |
| commit115 | `0x26fab9` | 487,573 | 36,041,985 | 42,937 |

GSim top `subStep` 的 text size 范围为 `0x2bf39~0x8c53e`；对应源文件为 `32,937~69,474` 行、
`8.73~11.48 MB`。GSim 源码单行更长，因此 source bytes 不能直接当动态成本，但热点函数 text 明显小于
GrhSIM 最大 batch。

直接阅读 GSim `subStep272/315` 可见它同样生成函数局部 `$old` snapshot 并比较更新；因此不能把差异简化成
“GSim 不做 value materialization”。更准确的差异是：GSim 在一个 `subStep` 中大量使用函数局部旧值和对象成员
直访，GrhSIM 则为跨 supernode/batch 的增量调度维护持久 typed value slots、changed predicate 和 activation。
这些状态带有跨 fire 语义，不能在没有 producer/consumer activation 证明时直接改为局部变量。

## 6. Compute8 state-read 物化

对 compute8 中每个 scalar `kRegisterReadPort`，按其后对应的 typed-slot storage assignment 分类：

| Version | Total | timer | logEndpoint | cpu | endpoint |
| --- | ---: | ---: | ---: | ---: | ---: |
| NO0278 | 48,551 | 29,686 | 17,789 | 1,074 | 2 |
| NO0300 | 21,069 | 431 | 19,565 | 1,073 | 0 |

NO0283 将 timer 物化减少 `98.55%`，与 compute8 samples 从历史 `403` 降到当前 `255` 的方向一致。当前剩余
scalar state-read 物化中，`logEndpoint` 占 `92.86%`，cpu 占 `5.09%`，timer 只占 `2.05%`。compute8 源码也从
`34.15 MB` 降到 `32.06 MB`，函数 text 从 `0x14ccff` 降到 `0x1157a8`。

这把下一候选从 timer alias 收窄到 logEndpoint 跨边界值，但不能把不同 logEndpoint states 按 NO0283 的
same-state 规则合并。下一阶段先做 state-read producer/consumer boundary-locality 诊断，量化哪些物化值只服务于
同 batch、哪些跨 batch 或可被 consumer 独立激活，再定义可证明安全的窄优化；在诊断前不做全局 direct-ref 重写。

## 7. 产物

```text
build/logs/xs_perf/no0345/fixed_gsim_50k_instructions.{data,report,perf-script,folded,svg,png}
build/logs/xs_perf/no0345/fixed_grhsim_50k_instructions.{data,report,perf-script,folded,svg,png}
build/logs/xs_perf/no0345/fixed_gsim_50k_instructions_leaf_symbols.tsv
build/logs/xs_perf/no0345/fixed_grhsim_50k_instructions_leaf_symbols.tsv
build/logs/xs_perf/no0345/historical_no0278_50k_instructions_leaf_symbols.tsv
build/logs/xs_perf/no0345/fixed_grhsim_compute8_instructions_annotate.report
```
