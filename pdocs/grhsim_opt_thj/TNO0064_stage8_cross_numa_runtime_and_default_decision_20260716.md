# TNO0064 Stage 8 cross-NUMA runtime and default decision

日期：2026-07-16

状态：p050/p200 均完成 current-default NO0300 fixed-ASLR 跨 NUMA SimTop 50k；两者在 NUMA0 明显回退、NUMA1 明显提升，方向反转，因此不修改默认 `1000000 PPM`，Stage 8 penalty family 停止。

## 1. Runtime 对象与方法

[TNO0063](./TNO0063_stage8_penalty_full_build_and_functional_gate_20260715.md) 形成两套 fresh O3 emu：

- p050：plain-DP segment penalty `500000 PPM`；
- p200：plain-DP segment penalty `2000000 PPM`。

控制组使用 Stage 7 fresh rollback emu，即仓库当前默认 NO0300、penalty `1000000 PPM`、所有可选 activity/emitter 优化关闭。三者均用 `setarch x86_64 -R` 关闭 ASLR。

每个候选在每个 NUMA node 都由相邻 NO0300 控制包夹，候选相对两侧控制算术均值计算百分比。正式样本满足：

```text
双 SMT sibling idle >= 99%
gate-to-run gap = 7..9 ms
CPU 与 memory 绑定到同一 NUMA node
cycles/instructions/frontend-empty/frontend-cmask6/backend-stalls 100% scheduled
control cycles spread < 1%
```

CPU topology：p050 NUMA0 使用 `73/265`，p200 NUMA0 使用 `84/276`；NUMA1 两候选共享 `125/317` 的 `A/p050/A/p200/A` 序列。每对均为同 core sibling 且位于对应 node。实际 invocation 对 NUMA0 显式传入 `FORMAL_NODE=0`，对 NUMA1 显式传入 `FORMAL_NODE=1`；runner 因而分别执行 local `numactl --physcpubind=... --membind=0/1`。timing artifact 本身不重复保存这些环境变量，本段保留调用配置作为审计边界。

## 2. 四组正式结果

负数表示候选更快或事件更少：

| 候选 | NUMA | cycles control spread | host | cycles | instructions | frontend empty | frontend cmask6 | backend stalls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| p050 | 0 | 0.036104% | +7.237691% | +7.205864% | -0.292708% | +9.292651% | +11.954701% | +1.896590% |
| p200 | 0 | 0.485714% | +11.701201% | +11.690451% | +0.072550% | +15.126309% | +18.989851% | +4.536309% |
| p050 | 1 | 0.038129% | -9.617739% | -9.584938% | -0.292715% | -12.170449% | -15.116548% | -1.375106% |
| p200 | 1 | 0.300966% | -10.009064% | -10.006916% | +0.072540% | -12.870608% | -16.241033% | +0.738345% |

所有正式样本的 guest 终点均为：

```text
guest=50001 cycle=49996 instr=73580 pc=0x80001312
```

exit 均为 `0`，mismatch/assert/fatal/error/fail/bad-trap/segmentation/aborted 负向扫描为 `0`。

formal perf、emu、quiet-gate 与 gate-to-run timing 产物统一位于：

```text
build/logs/xs_perf/activity_stage8_dp_penalty_20260715/
```

## 3. 失效样本处理

最初在 NUMA0 CPU84/276 上得到两个 p050 样本，但其控制 cycles spread 分别为 `1.820536%` 和 `1.582843%`，超过 `1%` 门槛；候选观测为 `+9.758185%/+6.759863%`，只作为同向负向旁证，不进入正式表。

随后 CPU11/203 与 CPU56/248 的尝试均因迁移型外部负载，在 20 轮 gate 内不能让双 sibling 同时达到 `99% idle`。这些尝试没有启动 candidate 或没有形成完整包夹，均不计算性能百分比。最终 CPU73/265 的 p050 控制 spread 仅 `0.036104%`，替代前述失效组。

## 4. 解释与默认决策

p050 在两个 node 上都稳定减少约 `0.2927%` retired instructions，p200 则稳定增加约 `0.0725%`；这说明 candidate 的动态指令变化可复现。但 cycles 完全由 frontend 方向主导：

- NUMA0 frontend empty/cmask6 分别回退约 `9.3%/12.0%` 和 `15.1%/19.0%`；
- NUMA1 frontend empty/cmask6 分别改善约 `12.2%/15.1%` 和 `12.9%/16.2%`。

这与 Stage 7 的跨 socket 反转一致。p050 只减少 `177` BAE 却增加 `177` compute SN 和一个 schedule CPP；p200 只减少 `143` compute SN、增加 `282` BAE，并少一个 schedule CPP。两者都足以重排 batch/native code layout，但结构与 retired instructions 不能解释跨 socket frontend 反转，不能把 NUMA1 的约 `10%` 收益推广到整机。

因此 Stage 8 不采用 p050 或 p200，仓库默认保持：

```text
WOLVRIX_XS_GRHSIM_DP_SEGMENT_PENALTY_PPM=1000000
```

保留参数化入口与测试，作为显式实验 knob；停止继续细扫固定 penalty。原因不是平均收益不足，而是受支持机器的一整个 NUMA node 上存在可复现的 `7.2%..11.7%` 回退。

## 5. 结构扫描耗时补充

[TNO0062](./TNO0062_stage8_plain_dp_penalty_structure_scan_20260715.md) 的四点日志时间如下：

| PPM | activity schedule | total | resume 路径 |
| ---: | ---: | ---: | --- |
| 500000 | 174082 ms | 451480 ms | canonical pre-reg，额外写 post-stats checkpoint |
| 1000000 | 174113 ms | 455516 ms | canonical pre-reg |
| 1500000 | 165292 ms | 194701 ms | p050 post-stats |
| 2000000 | 164972 ms | 192915 ms | p050 post-stats |

由于 resume 路径不同，`total` 不用于 penalty 性能比较；activity schedule 时间仅证明四点都完整执行。p100 identity 日志为：

```text
build/logs/xs/xs_wolf_grhsim_build_activity_stage8_dp_p100_20260715.log
```

## 6. 测试闭环

新增 option 后先只重建 focused target，首次全量 CTest 有三个旧测试可执行文件因 `ActivityScheduleOptions` 布局陈旧而读到非法 `final_topo_policy`。完整执行 `cmake --build wolvrix/build -j8` 后这些失败全部消失。

最终全量 CTest：`46/48 PASS`，其中：

- `transform-activity-schedule` PASS，`0.03s`；
- `emit-grhsim-cpp` PASS，`291.13s`；
- memory-fill 与 aggregate-port-slice 相关用例均 PASS；
- 仅既有 `transform-comb-lane-pack` 与 `transform-repcut` 两项保持相同失败签名，没有新增失败。

## 7. 后续方向

下一阶段不再调整全局固定 segment penalty。优先验证更定向的 common-source fanin root pullback：只把小型纯 compute cone 拉回共同 source 的 slack，以 exact `N` 个输入 BAE 换一个 live-out BAE，并保持 supernode 数、DAG、topo、active ID 和 commit partition 不变；仍须以跨 NUMA 50k 裁决。

## 增量更新 2026-07-17：绝对数值补录/勘误

原文四组正式结果只列相对变化。现从原始 `perf stat -x,` CSV 补录四个 A/B/A 的绝对计数；没有用百分比反推。事件与单位为 `cycles:u`（cycles count）、`instructions:u`（retired-instruction count）、`de_no_dispatch_per_slot.no_ops_from_frontend:u`（frontend-empty slots count）、`cpu/de_no_dispatch_per_slot.no_ops_from_frontend,cmask=0x6/u`（frontend-empty `cmask>=6` cycles count）和 `de_no_dispatch_per_slot.backend_stalls:u`（backend-stall slots count）。

四组共有 12 个 group positions、11 份不同 CSV：N1 的 `n1_a2_perf.csv` 同时是 p050 的 A2 和随后 p200 的 A1，属于原始 `A/p050/A/p200/A` 顺序中的共享 control。

| candidate / node | 顺序 | sample | cycles | instructions | frontend empty | frontend `cmask>=6` | backend stalls |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| p050 / N0 | 1 | control A1 | `282,581,972,127` | `172,881,261,641` | `1,289,488,149,681` | `167,065,100,144` | `94,732,049,992` |
| p050 / N0 | 2 | p050 B | `302,889,768,231` | `172,375,224,974` | `1,409,893,219,702` | `187,133,424,677` | `95,676,102,096` |
| p050 / N0 | 3 | control A2 | `282,479,968,358` | `172,881,262,133` | `1,290,544,823,389` | `167,236,939,632` | `93,058,537,509` |
| p200 / N0 | 1 | control A1 | `282,957,917,549` | `172,881,263,029` | `1,287,645,444,572` | `166,758,261,748` | `98,192,865,427` |
| p200 / N0 | 2 | p200 B | `315,271,316,901` | `173,006,688,028` | `1,479,722,923,552` | `198,017,497,904` | `101,006,771,224` |
| p200 / N0 | 3 | control A2 | `281,586,881,710` | `172,881,262,439` | `1,282,962,330,315` | `166,072,641,354` | `95,054,384,769` |
| p050 / N1 | 1 | control A1 | `309,939,961,442` | `172,881,268,571` | `1,456,416,536,879` | `194,761,404,672` | `92,979,666,812` |
| p050 / N1 | 2 | p050 B | `280,285,843,165` | `172,375,218,562` | `1,280,019,636,909` | `165,458,796,817` | `91,199,267,267` |
| p050 / N1 | 3 | control A2 | `310,058,161,549` | `172,881,268,891` | `1,458,364,710,643` | `195,087,952,988` | `91,962,012,182` |
| p200 / N1 | 1 | control A1（共享） | `310,058,161,549` | `172,881,268,891` | `1,458,364,710,643` | `195,087,952,988` | `91,962,012,182` |
| p200 / N1 | 2 | p200 B | `278,611,638,656` | `173,006,676,897` | `1,268,253,187,393` | `162,997,705,425` | `92,634,015,038` |
| p200 / N1 | 3 | control A2 | `309,126,393,355` | `172,881,269,003` | `1,452,830,145,295` | `194,118,627,209` | `91,948,127,368` |

原始路径前缀为 `build/logs/xs_perf/activity_stage8_dp_penalty_20260715/`；组内顺序与文件名为：

```text
n0d_a1_perf.csv / n0d_p050_b_perf.csv / n0d_a2_perf.csv
n0_a2_perf.csv / n0_p200_b_perf.csv / n0_a3_perf.csv
n1_a1_perf.csv / n1_p050_b_perf.csv / n1_a2_perf.csv
n1_a2_perf.csv / n1_p200_b_perf.csv / n1_a3_perf.csv
```

上述 11 份不同 CSV 的五个 headline events 均为 `100.00%` scheduled。两组被原文拒绝的 N0 p050 包夹不混入本表；本补录不改变原文默认决策。

原文 `host` 列也只给相对值；从对应 `*_emu.log` 的 `Host time spent` 行补录 wall milliseconds。N1 的 `n1_a2_emu.log` 与 PMU control 一样由相邻两组共享：

| candidate / node | 顺序 | sample | host ms |
| --- | ---: | --- | ---: |
| p050 / N0 | 1 | control A1 | `77,158` |
| p050 / N0 | 2 | p050 B | `82,669` |
| p050 / N0 | 3 | control A2 | `77,021` |
| p200 / N0 | 1 | control A1 | `78,467` |
| p200 / N0 | 2 | p200 B | `87,223` |
| p200 / N0 | 3 | control A2 | `77,705` |
| p050 / N1 | 1 | control A1 | `84,550` |
| p050 / N1 | 2 | p050 B | `76,406` |
| p050 / N1 | 3 | control A2 | `84,523` |
| p200 / N1 | 1 | control A1（共享） | `84,523` |
| p200 / N1 | 2 | p200 B | `75,951` |
| p200 / N1 | 3 | control A2 | `84,274` |

原始路径仍为 `build/logs/xs_perf/activity_stage8_dp_penalty_20260715/{stem}_emu.log`，stem 与上表 PMU CSV 一一对应。这些 wall 原值来自日志，不是百分比反推。
