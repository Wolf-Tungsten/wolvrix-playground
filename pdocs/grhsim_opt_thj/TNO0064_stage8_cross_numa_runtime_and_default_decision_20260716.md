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
