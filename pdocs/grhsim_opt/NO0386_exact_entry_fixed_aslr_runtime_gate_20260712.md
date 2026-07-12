# NO0386 Exact-entry fixed-ASLR runtime gate

日期：2026-07-12

## 1. 有效性门禁

按 [NO0382](./NO0382_exact_entry_fixed_aslr_runtime_plan_20260712.md)、
[NO0384](./NO0384_exact_entry_runtime_cpu_reselection_20260712.md) 和
[NO0385](./NO0385_exact_entry_pmu_preflight_gate_20260712.md)，在 CPU188、NUMA1、`setarch -R` 下串行执行
exact-entry baseline/direct/baseline 的 CoreMark 50k 五事件 A/B/A。

共享机噪声由每轮 quiet gate 现场过滤：

| Run | Rejected attempts | Accepted attempt | CPU188/380 idle |
| --- | ---: | ---: | --- |
| baseline1 | 5 | 6 | 99.67% / 100.00% |
| direct | 5 | 6 | 99.33% / 100.00% |
| baseline2 | 0 | 1 | 99.67% / 99.33% |

通过 gate 时全机 load average 分别为 `2.87/3.26/6.56`，相对 384 个逻辑 CPU 很低；所有 rejected attempts 均
保留且未产生 perf 数据。三轮都以 exit 0 到达 guest cycles `50001`、`cycleCnt=49996`、`instrCnt=73580`、terminal
PC `0x80001312`，无 mismatch、assertion、abort、fatal/error 或 `input_fullpass_blocked`。五项 PMU 均为
`100.00%` 调度。

两版以及两次 baseline 的 difftest state pointer 都为 `0x55555b079d30`，117 个入口严格同址后 fixed mapping 也完全
一致。baseline host-time/cycles spread 为 `0.598%/0.641%`，通过 `<=1%` 门限，A/B/A 比例有效。

## 2. 原始计数

| Run | Host time (ms) | Host cycles | Instructions | Frontend empty | cmask6 cycles | Backend stalls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| exact baseline1 | 83,678 | 306,232,601,819 | 172,879,276,228 | 1,431,357,551,798 | 190,702,141,085 | 95,436,417,806 |
| exact direct | 82,455 | 301,892,311,894 | 166,888,327,986 | 1,415,611,260,214 | 189,216,131,292 | 92,003,200,653 |
| exact baseline2 | 84,180 | 308,201,931,010 | 172,879,276,383 | 1,443,241,286,642 | 192,623,377,741 | 95,503,240,222 |

以两次 baseline 均值计算：

| Metric | Baseline mean | Direct | Delta |
| --- | ---: | ---: | ---: |
| Host time | 83,929.0 ms | 82,455 ms | -1.756% |
| Host cycles | 307,217,266,414.5 | 301,892,311,894 | -1.733% |
| Instructions | 172,879,276,305.5 | 166,888,327,986 | -3.465% |
| Frontend empty | 1,437,299,419,220 | 1,415,611,260,214 | -1.509% |
| cmask6 cycles | 191,662,759,413 | 189,216,131,292 | -1.277% |
| Backend stalls | 95,469,829,014 | 92,003,200,653 | -3.631% |

入口严格同址后 direct 有稳定的净加速，而不是 NO0365 原生布局下的回退。

## 3. CPI 与 stall density

| Metric per host cycle | Baseline | Direct | Delta |
| --- | ---: | ---: | ---: |
| Host IPC | 0.562726 | 0.552807 | -1.763% |
| Frontend empty slots | 4.678446 | 4.689127 | +0.228% |
| cmask6 cycles | 0.623867 | 0.626767 | +0.465% |
| Backend stall slots | 0.310757 | 0.304755 | -1.931% |
| Remaining bandwidth slots | 0.935243 | 0.928525 | -0.718% |

direct 的 backend 和 frontend bandwidth density 都改善；仅 full-empty frontend latency density 仍小幅恶化。绝对
cmask6 仍下降 `1.277%`，但下降慢于总 cycles，形成 `+0.465%` density 回退。

## 4. 删指令收益实现度

direct 少执行 `5,990,948,319.5` host instructions。baseline CPI 为 `1.777062`，若 CPI 不变，理论应节省
`10,646,289,164 cycles`；实际节省 `5,324,954,521 cycles`，实现理论删指令收益的 `50.017%`。剩余
`5,321,334,643 cycles` 被 direct 的 CPI 回退抵消。

因此 direct-forward 删除 state-read compare/store/changed/alias-OR 的工作是真实收益，但仍有约一半潜力被小幅前端
full-empty latency 放大吞掉。

## 5. 三种布局的因果对照

| Relative direct effect | Native NO0365 | Exact-entry NO0386 | 4 KiB NO0373 |
| --- | ---: | ---: | ---: |
| Host cycles | +6.263% | -1.733% | -9.084% |
| Instructions | -3.466% | -3.465% | -3.465% |
| cmask6 density | +5.839% | +0.465% | -4.503% |

instructions 收益对布局不敏感，但 cycles 在三种布局间摆动 `15.347 pp`。exact-entry 相对 native 改善 `7.996 pp`，
并把 cmask6 density 回退压低 `5.374 pp`；相对 4 KiB 又少 `7.351 pp` 的表观收益。这同时说明：

1. NO0365 的 `+6.263%` 主要是入口地址漂移造成的前端布局惩罚，不是 direct activation 的固有成本；
2. NO0373 的 `-9.084%` 也主要包含 4 KiB 对两版方向相反的有利/不利扰动；
3. 在对应完整入口同址时，direct 机制的当前净收益约为 `1.7%`，但仍存在函数内部/helper/rodata 布局或动态访问造成的
   小幅前端残差。

## 6. 结论与下一步

direct state-read 功能正确且在 strict exact-entry 控制下有净性能收益，但 production native binary 仍是 NO0365 的
回退，所以开关继续默认关闭；不能把 padding probe 当作实现，也不能直接采用统一 4 KiB alignment。

本轮因 CPU138 持续受共享任务干扰而改用 CPU188，按 NO0383/NO0384 的修正规则不把本轮 absolute cycles 直接除以
历史 CPU138 GSim cycles。下一步应在 exact-entry baseline/direct 上采集同核 fixed-ASLR cmask6 profile，定位剩余
`+0.465%` full-empty density 到具体函数和 body offset；同时对照 GSim 生成代码，寻找不依赖偶然地址的 layout/代码组织
方式。若要更新 absolute GrhSIM/GSim gap，则另行在 CPU188 现场重跑 GSim。

## 7. 产物

```text
build/logs/xs_perf/no0386/{baseline1,direct,baseline2}_{emu.log,perf.csv}
build/logs/xs_perf/no0386/{baseline1,direct,baseline2}_quiet_gate_attempt_*.log
build/logs/xs_perf/no0386/raw_counts.tsv
build/logs/xs_perf/no0386/runtime_summary.report
```
