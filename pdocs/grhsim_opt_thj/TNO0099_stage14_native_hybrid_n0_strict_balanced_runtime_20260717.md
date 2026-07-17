# TNO0099 Stage 14 native-hybrid N0 strict balanced runtime

记录日期：2026-07-17

状态：N0 strict P0 确认完成，N1 待测。current C++ native-hybrid default 相对显式 `0/0` rollback 在 N0 的 ABBA 与 BAAB 共 8 个有效 SimTop 50k 样本中，cycles 分别改善 `4.010465%/3.943042%`，合并改善 `3.976741%`；instructions、frontend empty、frontend `cmask>=6` 与 backend stalls 也分别改善 `4.835558%/4.022265%/4.047815%/3.409628%`。8/8 样本通过 node-local placement、whole-node runtime monitor、PMU、scheduler/migration、affinity/ASLR 与功能硬门禁，control/candidate cycles spread 仅 `0.090981%/0.256570%`。结果进一步确认 [TNO0092](./TNO0092_stage14_native_hybrid_default_adoption_decision_20260717.md) 的采用决定，但 current strict 双 node closure 尚未完成；N1 必须在同协议的安静窗口补齐后另立记录。

## 1. 对象、顺序与绑定

本轮执行 [TNO0098](./TNO0098_stage7_plus_strict_numa_window_recheck_and_retest_queue_20260717.md) 的 P0 队列，只比较：

```text
A/control: s14_off      (direct-state=0, pure-event-bypass=0)
B/candidate: s14_default (C++ native hybrid default)
```

这两份 ELF 已按 [TNO0087](./TNO0087_page_local_stage7_stage8_corrected_runtime_20260716.md) 的 page-local 方法 staging 到 N0 独立 `/dev/shm` inode。执行核为 N0 CPU43，SMT sibling 为 CPU235，gate/monitor helper 绑到对侧 node 的 CPU191；两组顺序分别为：

```text
ABBA: off / default / default / off
BAAB: default / off / off / default
```

workload 绑定层级与 [TNO0089](./TNO0089_page_local_stage12_stage13_interim_runtime_and_strict_numa_protocol_20260717.md) 一致：

```bash
taskset -c "$cpu" \
    numactl --physcpubind="$cpu" --membind="$node" \
    perf stat ... -- \
    setarch x86_64 -R "$node_local_emu" ... -C 50000
```

这同时固定 workload CPU、物理 CPU 与 memory policy；最终 file-backed locality 仍以运行中 `numa_maps` 的逐页审计为准，而不是仅根据命令行推断。

## 2. 两次 pre-gate rejection 没有进入 perf

每个样本启动前均对 N0 的 192 个 logical CPU 执行 30 秒 gate，要求 whole-node mean idle `>=99%`、minimum idle `>=95%`，目标 CPU43 与 sibling CPU235 各自 idle `>=98%`。ABBA 四次首轮 gate 全部通过；BAAB 中有两次首轮 attempt 被正确拒绝：

| sample | attempt | mean idle | min idle | CPU43 | CPU235 | 决定 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| BAAB B1/default | `1` | `99.770%` | `95.87%` | `99.63%` | `95.87%` | sibling `<98%`，REJECT |
| BAAB A1/off | `1` | `99.648%` | `92.63%` | `99.97%` | `99.87%` | whole-node min `<95%`，REJECT |

这两项是 admission attempt rejection，不是性能样本；runner 在 gate 内继续等待，未启动 emu 或 `perf stat`，也没有将任何 counter 纳入统计。对应第二次 attempt 随后通过。8 个最终 accepted gate 的 mean idle 为 `99.764%..99.844%`、minimum idle 为 `95.96%..97.67%`，CPU43 为 `99.83%..100.00%`，CPU235 为 `99.87%..100.00%`；gate-to-run gap 全部为 `7..8 ms`。

## 3. 八个有效样本的原始 PMU 计数

| order | sample | binary | cycles | instructions | frontend empty | frontend `cmask>=6` | backend stalls |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| ABBA | A1 | off | `284,396,544,386` | `172,881,401,690` | `1,301,635,357,710` | `168,932,288,258` | `94,350,709,946` |
| ABBA | B1 | default | `272,968,997,141` | `164,521,620,268` | `1,249,814,833,768` | `162,200,648,295` | `90,076,637,394` |
| ABBA | B2 | default | `273,112,556,193` | `164,521,621,433` | `1,249,322,962,092` | `162,134,584,857` | `91,215,679,991` |
| ABBA | A2 | off | `284,500,419,821` | `172,881,401,634` | `1,300,994,168,575` | `168,866,255,044` | `95,565,457,691` |
| BAAB | B1 | default | `273,186,734,480` | `164,521,621,206` | `1,249,826,469,231` | `162,216,089,311` | `91,233,670,989` |
| BAAB | A1 | off | `284,648,691,291` | `172,881,401,269` | `1,305,114,738,437` | `169,502,874,767` | `92,582,142,166` |
| BAAB | A2 | off | `284,655,291,620` | `172,881,402,147` | `1,303,165,771,596` | `169,259,532,211` | `94,368,072,481` |
| BAAB | B2 | default | `273,669,353,119` | `164,521,620,395` | `1,252,349,169,506` | `162,623,694,875` | `91,490,651,931` |

每个顺序内分别对两份 default 与两份 off 取均值，再计算 `default/off - 1`。cycles 得到：

| order | cycles delta |
| --- | ---: |
| ABBA | `-4.010465%` |
| BAAB | `-3.943042%` |

将四份 default 与四份 off 分别合并后的 headline 为：

| metric | default vs off |
| --- | ---: |
| cycles | `-3.976741%` |
| instructions | `-4.835558%` |
| frontend empty | `-4.022265%` |
| frontend `cmask>=6` | `-4.047815%` |
| backend stalls | `-3.409628%` |

cycles 在 ABBA/BAAB 两种相反顺序下方向、幅度一致；按组内 `max/min - 1` 计算，四份 off control 的 spread 为 `0.090981%`，四份 default candidate 的 spread 为 `0.256570%`，均远小于约 `3.98%` 的候选收益。instructions 几乎精确复现，前端两项和 backend 也与 cycles 同向，因此本轮不是单一包夹的时间顺序漂移。

## 4. 全部硬门禁

8/8 个正式样本全部满足：

- **node-local page placement PASS**：off `emu` 为 `21,494` 页、default `emu` 为 `21,264` 页，`nemu.so` 均为 `115` 页；全部位于 N0，N1 页数为 `0`。
- **whole-node runtime monitor PASS**：除 target 外的 191 个 logical CPU mean idle 为 `99.770%..99.832%`、minimum idle 为 `96.34%..97.90%`，均超过 `99%/95%` 门槛。
- **PMU PASS**：五项 headline event 的 scheduling 均为 `100.00%`；没有 multiplexing 污染。
- **scheduler PASS**：task-clock utilization 为 `0.998..0.999`，context-switch rate 为 `11.202..12.021/s`，低于 `20/s` 门槛；8/8 `cpu-migrations=0`。
- **affinity 与 ASLR PASS**：8/8 `Cpus_allowed_list=43`，personality probe 为 `00040000`；runner/helper 均保持 CPU191。
- **功能 PASS**：8/8 均到达 `Guest cycle spent=50001`、`cycleCnt=49996`、`instrCnt=73580`，且无 mismatch/assert/fatal/error。

此外，8/8 `run_status=0`，placement、monitor、perf、scheduler、function 与 affinity 六项 runner result flag 全为 `1`。这组数据满足 current strict protocol 的 N0 单边闭环。

## 5. 结论与剩余边界

本轮 N0 strict balanced 结果进一步确认 native hybrid 是当前默认的正确选择：约 `3.98%` cycles 收益明显高于 control/candidate spread，并与 instructions、frontend、backend 同向。[TNO0092](./TNO0092_stage14_native_hybrid_default_adoption_decision_20260717.md) 的采用决定无需回滚，也无需等待 N1 才继续作为默认；本记录提供的是更严格协议下的进一步确认。

## 增量更新 2026-07-17：walltime headline 绝对值补录

最终性能 headline 采用 host walltime；cycles/instructions/frontend/backend 仅作解释。注意按 binary header 映射样本，而不是按 `a/b` 文件名猜测：ABBA 是 `off / default / default / off`，BAAB 是 `default / off / off / default`。以下为 `Host time spent` 原值（milliseconds）：

| order | sample sequence | wall ms |
| --- | --- | --- |
| ABBA | off A1 / default B1 / default B2 / off A2 | `77,820 / 74,606 / 74,646 / 77,780` |
| BAAB | default B1 / off A1 / off A2 / default B2 | `74,652 / 77,797 / 77,806 / 74,795` |

原始来源为 `build/logs/xs_perf/page_local_retest_stage7plus_20260716/groups/n0/stage14_default_strict_p0_{abba,baab}_try1/{a1,b1,b2,a2}_emu.log`。按每组两份 control/candidate 均值计算，walltime default 相对 explicit-off 为 ABBA `-4.079692%`、BAAB `-3.956222%`、合并 `-4.017956%`；control/default candidate spreads 为 `0.051427%/0.253331%`。采用结论在 walltime headline 下不变。

但它仍不是 current strict 双 node closure。N1 在 [TNO0098](./TNO0098_stage7_plus_strict_numa_window_recheck_and_retest_queue_20260717.md) 记录的外部迁移负载消失并通过同一 30 秒 whole-node gate 后，必须使用镜像 CPU139/sibling331、N1 独立 inode、ABBA+BAAB 和相同全部硬门禁重测。N1 完成前，不把本轮单边数据写成“双 node strict 已通过”，也不据此批量晋升 Stage 8/10/12/13 的其它默认关闭选项。

原始产物：

```text
build/logs/xs_perf/page_local_retest_stage7plus_20260716/run_formal.sh
build/logs/xs_perf/page_local_retest_stage7plus_20260716/run_balanced_pair.sh
build/logs/xs_perf/page_local_retest_stage7plus_20260716/groups/n0/stage14_default_strict_p0_abba_try1/
build/logs/xs_perf/page_local_retest_stage7plus_20260716/groups/n0/stage14_default_strict_p0_baab_try1/
```
