# NO0254 Event settle density FTQ/Tage gate

日期：2026-07-10

## 背景

`NO0253` 将 event fast path 的 post-commit settle 改为按本次 commit reader density 自适应选择：

```text
post_commit_active_count * 4 <= compute_supernode_count
    -> sparse normal active closure
otherwise
    -> dense no-propagation fullpass
```

该规则已在两个分布相距很远的 case 上验证：

- `SimTop` 平均 reader density 为 `4.12%`，选择 sparse；
- `VtypeBuffer` direct reader density 为 `68.42%`，选择 dense。

本轮按计划补充 `XsReal053FtqFtqLarge` 和 `XsReal043TageTageLarge`，验证 `25%` 阈值是否仍位于自然间隔内，并给默认关闭的 `perf=eval` 模型增加可读取的 event settle counters。

## 机器负载与构建口径

所有命令均先执行：

```bash
source env.sh
```

第一次 FTQ `make bench` 时，Mill 停在 `Retrieving latest mill version`，同时机器 load 升至约 `211/384`。该运行尚未进入模型生成或 benchmark，已中止，不作为结果。

后续复用以下已有 Chisel FIR/SV：

```text
testcase/xs-components/build/no0231_compute_skip_20260709/raw_bench/
```

两组 FIR/SV 的时间戳均晚于对应 Scala 源码与 `build.mill`，本轮 Scala case 未变化。只复用前端输入，GSIM、当前 GrhSIM emitter、generated C++、对象文件和 bench 均在独立目录 fresh 生成：

```text
build/no0254_hybrid_post_commit_ftq_20260710
build/no0254_hybrid_post_commit_tage_20260710
```

性能执行时 1 分钟 load 约为 `22-33/384`；每个 raw bench 同场运行 GSIM/GrhSIM，并使用相邻 hybrid/forced-active/hybrid 顺序控制机器波动。

## Fresh hybrid 功能与性能 gate

配置：

```text
GRHSIM_INPUT_FULLPASS_SPECIALIZATION=1
GRHSIM_POSEDGE_FULLPASS_SPECIALIZATION=1
BENCH_VECTORS=200000
BENCH_VERIFY=200000
BENCH_REPEAT=3
```

日志：

```text
build/logs/xs/no0254_ftq_hybrid_post_commit_build_20260710.log
build/logs/xs/no0254_tage_hybrid_post_commit_build_20260710.log
build/logs/xs/no0254_ftq_hybrid_post_commit_bench_20260710.log
build/logs/xs/no0254_tage_hybrid_post_commit_bench_20260710.log
```

结果：

| case | verify | compute supernodes | GSIM min | GrhSIM hybrid min | GrhSIM/GSIM | checksum |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| FTQ | pass 200k | `47` | `385.088ms` | `441.251ms` | `1.146x` | `0xbaee70347535d277` |
| Tage | pass 200k | `41` | `303.459ms` | `365.978ms` | `1.206x` | `0x3c264532fbc1f4d3` |

绝对时间与 `NO0245` 的旧 P0 fullpass 结果接近，且功能 checksum 与 GSIM 一致。

## Generated C++ density probe

先在 fresh generated eval 中临时加入 event hit、state-changed、sparse/dense 和 active-count histogram。该插桩只存在于 build 产物，完成后已 fresh 恢复 hybrid 模型。

日志：

```text
build/logs/xs/no0254_ftq_post_commit_density_profile_20260710.log
build/logs/xs/no0254_tage_post_commit_density_profile_20260710.log
```

### FTQ

```text
event_hits=600006 unchanged=2 sparse=1 dense=600003
active_sum=18612213 active_min=1 active_max=34
histogram=1:1,24:15,25:480,26:17799,27:94528,28:132903,
          30:20,31:284,32:23482,33:134018,34:196474
```

排除两个 unchanged event 后：

- state-changed samples：`600004`；
- 平均 active：`31.020 / 47 = 66.00%`；
- `600003` 次 dense，仅 `1` 次 sparse。

### Tage

```text
event_hits=600006 unchanged=2 sparse=1 dense=600003
active_sum=15102506 active_min=1 active_max=28
histogram=1:1,17:4,18:38,19:399,20:17156,21:94471,22:133244,
          24:11,25:214,26:1086,27:92697,28:260683
```

排除 unchanged event 后：

- state-changed samples：`600004`；
- 平均 active：`25.171 / 41 = 61.39%`；
- `600003` 次 dense，仅 `1` 次 sparse。

两组典型 reader density 均远高于 `25%`，不存在大量样本落在阈值附近的问题。

## Hybrid dense 与强制 active 相邻 A/B

为了验证 dense 判定确实选择了更快实现，而不只是与阈值自洽，将 generated 条件临时改成恒 true，强制所有 state-changed event 走 active closure。两组 `--verify 200000` 均通过。

日志：

```text
build/logs/xs/no0254_ftq_hybrid_vs_forced_active_adjacent_20260710.log
build/logs/xs/no0254_tage_hybrid_vs_forced_active_adjacent_20260710.log
```

结果使用相邻 `hybrid -> forced active -> hybrid` 的三组 min：

| case | hybrid run 1 | forced active | hybrid run 2 | hybrid mean | forced-active delta |
| --- | ---: | ---: | ---: | ---: | ---: |
| FTQ | `437.106ms` | `469.730ms` | `436.267ms` | `436.687ms` | `+7.57%` |
| Tage | `369.659ms` | `390.365ms` | `369.712ms` | `369.686ms` | `+5.59%` |

因此 FTQ/Tage 的 dense fullpass 选择有明确性能收益，当前 `25%` 阈值无需调整。

## 可选 perf counters

修改：

```text
wolvrix/lib/emit/grhsim_cpp.cpp
wolvrix/tests/emit/test_emit_grhsim_cpp.cpp
```

仅当生成选项为 `perf=eval` 时，`PerfCounters` 新增：

```text
eventFastPathCount
eventStateChangedCount
eventSparseSettleCount
eventDenseSettleCount
eventPostCommitActiveSum
eventPostCommitActiveMin
eventPostCommitActiveMax
```

默认 `perf=off` 模型不生成这些字段和计数语句，因此不增加默认仿真热路径开销。`reset_perf_counters()` 继续通过重置整个 `PerfCounters` 生效；当没有 state-changed sample 时，`eventPostCommitActiveMin` 保持 `UINT64_MAX`。

Emitter 单测中的 commit-cond-batch case 现在同时开启 posedge specialization 与 `perf=eval`，检查：

1. generated event branch 包含 fast/state/sparse/dense counter 更新；
2. generated header 暴露 active sum/min/max；
3. 运行 harness 后 `eventFastPathCount == 2`；
4. sparse + dense 等于 state-changed，active min/max/sum 合法。

## 源码级 profile 复现

临时 probe：

```text
tmp/no0254_event_settle_perf_counter_probe.cpp
```

使用当前 emitter fresh 生成 `perf=eval` 模型，通过公开 `perf_counters()` 读取结果：

```text
build/logs/xs/no0254_ftq_source_perf_counter_probe_20260710.log
build/logs/xs/no0254_tage_source_perf_counter_probe_20260710.log
```

| case | event fast | state changed | sparse | dense | active min/max | active avg | density |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| FTQ | `200002` | `200001` | `0` | `200001` | `24 / 34` | `31.020` | `66.00%` |
| Tage | `200002` | `200001` | `0` | `200001` | `17 / 28` | `25.171` | `61.39%` |

源码级 counters 与 generated 临时直方图的均值和范围一致。

## 测试

```text
build/logs/xs/no0254_wolvrix_build_event_settle_perf_counters_20260710.log
build/logs/xs/no0254_ctest_event_settle_perf_counters_20260710.log
```

结果：

- `emit-grhsim-cpp`: pass；
- `emit-grhsim-cpp-memory-fill`: pass；
- 2/2 passed。

强制 active 实验后已恢复两个 build 目录的 clean hybrid eval/lib/bench，并各自通过 4096 vector verify：

```text
build/logs/xs/no0254_ftq_restored_hybrid_verify_20260710.log
build/logs/xs/no0254_tage_restored_hybrid_verify_20260710.log
```

## 结论

1. FTQ/Tage 的 post-commit reader density 分别约 `66.00%` 和 `61.39%`，几乎所有 state-changed event 都稳定选择 dense fullpass。
2. 强制 active closure 分别慢 `7.57%` 和 `5.59%`，证明 hybrid 的 dense 判定是正确的成本选择。
3. SimTop `4.12%`、FTQ `66.00%`、Tage `61.39%`、VtypeBuffer `68.42%` 在当前 workload 下形成明显的 sparse/dense 两簇；`25%` 位于宽间隔中，暂不需要调整。
4. 新增的 `perf=eval` counters 可以在后续 SimTop 或其他 workload 上直接观测分支命中与 active density，而不影响默认模型性能。

## 下一步

下一步回到最终目标，使用 NO0253 hybrid 作为 SimTop correctness/performance baseline，与同场 GSIM 做相邻较长窗口对比，并采集 perf report / flamegraph。重点转向 hybrid 后仍剩余的差距，而不是继续调已经通过四组 case 验证的 `25%` 阈值。
