# NO0281 Same-FIR GSim / GrhSIM frontend counter compare

日期：2026-07-11

## 1. 目标与输入

[NO0280](./NO0280_or_decoded_true_merge_cycles_post_profile_20260711.md) 证明 NO0278 相对
NO0274 的局部收益主要来自 frontend stall 下降。本轮用完全相同的 counters 对照 same-FIR
GSim，判断当前 GrhSIM 相对 GSim 的剩余差距是否仍由 frontend 主导。

- GSim：`build/xs_gsim_no0255_current_20260710/gsim/gsim-compile/emu`；
- GrhSIM：NO0278 fresh emu；
- source FIR：`build/xs_grhsim_event_order_src_20260710/rtl/rtl/SimTop.fir`；
- FIR SHA256：`461755d7531724b6e26e1601f45db3344dc8c5c8e099b8f162d7e1b638eee877`；
- GrhSIM 从该 source build 的 `wolvrix_xs_pre_reg_to_mem.json` 恢复后执行最新 transform；
- workload：CoreMark 2 iterations、NEMU difftest、`-C 50000`；
- CPU：CPU138，SMT sibling CPU330；
- 所有运行前执行 `source env.sh`，所有事件均为 `100% scheduled`。

运行窗口内全机 load average 约 `2.74~10.71 / 5.16~7.31 / 7.98~8.52`。GSim 两次
preflight 中 CPU138/330 平均 idle 均不低于 `97.67%`；对应 GrhSIM 数据来自紧邻的
[NO0280](./NO0280_or_decoded_true_merge_cycles_post_profile_20260711.md) paired run。

## 2. 功能终点

两边均完成 50001 guest cycles 且 difftest 无 mismatch/abort。GSim 与 GrhSIM 的少量 guest
计数/PC 差异是已有 same-FIR 基线行为：

| simulator | Guest cycle spent | instrCnt / cycleCnt | terminal PC |
| --- | ---: | ---: | --- |
| GSim | `50001` | `73584 / 49998` | `0x8000131e` |
| GrhSIM | `50001` | `73580 / 49996` | `0x80001312` |

## 3. Generic frontend counters

事件为 `cycles:u`、`instructions:u`、`stalled-cycles-frontend:u`、`L1-icache-loads:u` 和
`L1-icache-load-misses:u`：

| metric | GSim | GrhSIM | GrhSIM / GSim |
| --- | ---: | ---: | ---: |
| Host time | `31137ms` | `83237ms` | `2.673x` |
| host cycles | `113989494480` | `304592107755` | `2.672x` |
| host instructions | `80071216791` | `190436311216` | `2.378x` |
| frontend stalled cycles | `68763967145` | `175878092260` | `2.558x` |
| L1I loads | `45736855887` | `117349090326` | `2.566x` |
| L1I misses | `424248796` | `1281983951` | `3.022x` |
| IPC | `0.702444` | `0.625217` | GSim `1.124x` higher |

frontend stalled cycles 的绝对值随总 runtime 增长，但占比并未在 GrhSIM 中恶化：

```text
GSim frontend stalled share   = 60.3248%
GrhSIM frontend stalled share = 57.7422%
```

GrhSIM 的 L1I miss rate 为 `1.0925%`，GSim 为 `0.9276%`，相差 `0.1649pp`；该差异存在，
但不足以把总 cycles `2.672x` 主要归因到 frontend。

## 4. Cycles 差距分解

用 GSim CPI 将 GrhSIM 的额外 host instructions 折算为 cycles：

```text
total excess cycles                         = 190602613275
extra-instruction component at GSim CPI     = 157115900394  (82.43%)
remaining CPI component                     =  33486712881  (17.57%)
```

这是算术分解，不是假设两边每条指令语义或 cache 行为相同。它说明优化优先级：当前剩余差距的
主体是 GrhSIM 执行了 `2.378x` host instructions；较低 IPC 仍重要，但只解释约六分之一的
excess cycles。

## 5. AMD native dispatch counters

事件为 `cycles:u`、两个 `ic_tag_hit_miss.*` 和两个 `de_no_dispatch_per_slot.*`：

| metric | GSim | GrhSIM | GrhSIM / GSim |
| --- | ---: | ---: | ---: |
| Host time | `31018ms` | `83354ms` | `2.687x` |
| host cycles | `113554065467` | `305064270476` | `2.687x` |
| ICache accesses | `44500669340` | `115881057471` | `2.604x` |
| ICache misses | `15246127936` | `40422336906` | `2.651x` |
| no ops from frontend | `530191697678` | `1367227268875` | `2.579x` |
| backend stalls | `23923902191` | `105362319512` | `4.404x` |

两个 dispatch 事件是 slot count。按 host cycle 归一化：

| normalized metric | GSim | GrhSIM | GrhSIM / GSim |
| --- | ---: | ---: | ---: |
| frontend empty slots / cycle | `4.6691` | `4.4818` | `0.960x` |
| backend stall slots / cycle | `0.2107` | `0.3454` | `1.639x` |

因此当前 GrhSIM 并不是每 cycle 得到更少的 frontend operations；相反，backend stall density
明显更高。这与 generic stalled-cycle share 一起排除了“剩余差距主要是 GrhSIM frontend
供给更差”的假设。

## 6. 结论与下一步

1. NO0278 相对 NO0274 的 `~10%` 局部收益来自前端布局改善，但不能外推为当前 GSim/GrhSIM
   总差距的主因。
2. 当前 NO0278 GrhSIM 在同 FIR、同 50k workload 下仍为 GSim 的约 `2.67x` cycles；其中
   host instructions 为 `2.38x`，算术上解释约 `82.43%` excess cycles。
3. frontend stall share 和 frontend empty slots/cycle 都不比 GSim 更差；剩余 IPC 劣势更偏向
   backend stall、数据依赖、访存或更复杂指令形态。
4. 下一步使用 `instructions:u` 固定 period profile 对照 GSim `subStep*` 与 GrhSIM
   compute/commit，先定位额外 `110.37B` host instructions 分布，再回到 generated C++ 做具体差异分析。

## 7. 产物

```text
build/logs/xs_perf/no0281/cpu138_330_preflight_gsim_generic_20260711.log
build/logs/xs_perf/no0281/gsim_cpu138_50k_generic_frontend.log
build/logs/xs_perf/no0281/gsim_cpu138_50k_generic_frontend_perf_stat.csv
build/logs/xs_perf/no0281/cpu138_330_preflight_gsim_native_20260711.log
build/logs/xs_perf/no0281/gsim_cpu138_50k_native_frontend.log
build/logs/xs_perf/no0281/gsim_cpu138_50k_native_frontend_perf_stat.csv
```
