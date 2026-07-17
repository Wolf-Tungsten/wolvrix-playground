# TNO0120 Stage 7+ P1 cap8192 try8 survey rejection

记录日期：2026-07-17

状态：P1 cap4096/default 对 cap8192 的 N0 BAAB try8 在启动 emu 前被 whole-node admission 拒绝。完整 `mpstat` raw 已保存；minimum idle `94.690000%` 低于 `95%`，没有创建 try8 group 或产生 walltime/PMU 样本。

## 1. Absolute survey

继续使用 [TNO0118](./TNO0118_stage7_plus_p1_cap8192_corrected_runtime_attempt4_to6_20260717.md) 的 fresh N0 staging、CPU43/sibling235/helper191 与相同硬门槛。raw：

```text
build/logs/xs_perf/page_local_retest_stage7plus_20260716/stage14_cap8192_strict_p1_try8_survey_20260717/n0.log
```

| metric | absolute value |
| --- | ---: |
| logical CPU count | `192` |
| whole-node mean idle | `99.573437%` |
| whole-node minimum idle | `94.690000%` |
| minimum CPU | `22` |
| target CPU43 idle | `99.630000%` |
| sibling CPU235 idle | `99.570000%` |

count、mean、target 和 sibling 均通过，只有 minimum 失败。与 [TNO0119](./TNO0119_stage7_plus_p0_n1_native_hybrid_closure_and_p1_try7_20260717.md) 的 try7 不同，本轮在 standalone survey 阶段即停止，没有调用 `run_balanced_pair.sh`，也没有 `Host time spent`、perf CSV、placement 或 runtime monitor。

## 2. Decision boundary

P1 现有三个有效组仍全部小幅正向，但 N0 BAAB 仍未形成完整组；try8 的机器 rejection 不构成 cap8192 性能证据。C++ commit cap default 保持 `4096`，不降低 `95%` minimum gate、不拼接 try4..7 的孤立样本，也不在 P1 balanced closure 前进入 cap16384。N0 后续重新通过 raw survey 时从 BAAB try9 完整开始。
