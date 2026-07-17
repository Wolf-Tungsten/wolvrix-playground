# TNO0114 Stage 19 table activation runtime probe result

记录日期：2026-07-17

状态：Stage 19 dynamic probe 完成。generic table activation 在真实 SimTop 窗口中持续高频执行，且 zero-hole chunk opportunity 随窗口增长；因此 table encoding 候选进入下一阶段（另立 Stage 20），本阶段不直接修改默认生成方式。

## 1. 版本、配置与 profile 边界

对象为当前仓库默认生成配置（NO0300、ASLR 关闭）对应的 current native-hybrid/cap4096 schedule。profile emit 显式设置：

```text
active_mask_gap_pack_policy = probe
emit_runtime_profile = true
```

探针字段只在这两个显式选项同时存在时编译；default、explicit-off、普通 probe 仍保持原 generated source。Stage 19 profile binary 只用于动态计数与功能闭环，插桩开销使其 walltime 不可用于 control/candidate 性能比较。最终性能仍必须由 Stage 20 未插桩 binary 的 SimTop 50k `Host time spent` 决定。

v1 曾在 editable Python extension 尚未重装时生成，虽然 emit-time probe 日志有效，但没有新 table counter；该目录和日志不作任何运行结论。重新安装 editable package 后生成的 v2 才是正式 profile：

```text
build/xs_activity_stage19_table_runtime_profile_v2_20260717/grhsim/grhsim_emit/
build/logs/xs/xs_wolf_grhsim_build_stage19_table_runtime_profile_v2_20260717.log
```

## 2. 静态 source gate

emit-time probe 和 generated source 机械对账如下：

| metric | exact value |
| --- | ---: |
| generic table counter insertion sites | `586` |
| current per-entry constants sum | `89,903` |
| contiguous chunk constants sum | `19,942` |
| zero-hole chunk constants sum | `17,530` |
| emit-time table gap-only delta | `2,412` |

对应 emit 日志的 table 行为 `groups=586 entries=89903 baseline_writes=89903 contiguous_writes=19942 candidate_writes=17530 invalid_groups=0`。从所有 `*.cpp` 的 `UINT64_C(...)` 常量重新求和得到同样的四项值；`++runtime_profile_active_mask_table_evaluations_` 插点恰为 `586` 个。O3 model archive 和 emu link 均通过：

```text
build/logs/xs/stage19_table_runtime_profile_o3_build_20260717.log
build/logs/xs/stage19_table_runtime_profile_emu_build_20260717.log
```

这里的 `586` 是 emit-time generic site/group 数，不是总 runtime evaluations 上界；同一 site 可跨多个 eval/round 多次命中。

## 3. SimTop dynamic profile

运行命令统一使用 `source env.sh` 后的 `setarch x86_64 -R numactl --physcpubind=43 --membind=0 taskset -c 43`，输入为：

```text
testcase/xiangshan/ready-to-run/coremark-2-iteration.bin
```

emu 设置 `EMU_RUNTIME_PROFILE=1`，每个 raw log 要求恰有一条正的 `GRHSIM_ACTIVE_MASK_TABLE_PROFILE` summary。绝对值如下：

| window | cycles/functional result | Host time (profile only) | evaluations | current entry writes | contiguous chunks | zero-hole chunks |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| `100` | `cycleCnt=96`, guest `101`, instr `0` | `401 ms` | `2,986` | `394,750` | `100,323` | `87,025` |
| `10,000` | `cycleCnt=9,996`, guest `10,001`, instr `458` | `9,736 ms` | `302,819` | `41,635,848` | `9,790,907` | `8,562,640` |
| `50,000` | `cycleCnt=49,996`, guest `50,001`, instr `73,580` | `76,500 ms` | `2,998,684` | `517,247,888` | `95,185,834` | `86,274,884` |

原始日志和 fire TSV：

```text
build/logs/xs_perf/activity_stage19_table_runtime_profile_20260717/profile_100.log
build/logs/xs_perf/activity_stage19_table_runtime_profile_20260717/profile_10000.log
build/logs/xs_perf/activity_stage19_table_runtime_profile_20260717/profile_50000.log
build/logs/xs_perf/activity_stage19_table_runtime_profile_20260717/fire_100.tsv
build/logs/xs_perf/activity_stage19_table_runtime_profile_20260717/fire_10000.tsv
build/logs/xs_perf/activity_stage19_table_runtime_profile_20260717/fire_50000.tsv
```

每个 log 中 summary 行只出现一次。三个窗口均满足：

```text
current entry writes >= contiguous chunks >= zero-hole chunks
```

从 `10,000` 到 `50,000` 的增量为：

```text
evaluations       +2,695,865
current           +475,612,040
contiguous        +85,394,927
zero-hole         +77,712,244
gap opportunity    +7,682,683 chunks  (contiguous - zero-hole)
```

这说明 table path 不是只存在于 reset/cold path；静态 `2,412` 的 gap-only opportunity 被真实 active-mask propagation 多次复用。该计数仍是 lowering-work proxy，不等价于 CPU instruction 或 walltime 收益。

共享指标工具 `scripts/grhsim_opt_metrics.py` 已增加唯一 summary 解析：输出 `active_mask_table_profile_count`；只有 count 为 `1` 时才输出四项绝对 counter，并用 `active_mask_table_profile_ok` 检查 `current >= contiguous >= zero_hole >= 0`。对正式 50k raw log 的机读结果精确为上述 `2,998,684 / 517,247,888 / 95,185,834 / 86,274,884`，同时保留唯一 walltime `76,500 ms` 作为插桩运行原值。

## 4. 决定与下一阶段边界

Stage 19 进入 Stage 20 table candidate，理由是动态 evaluations 和 gap opportunity 在 10k→50k 保持显著正增量，且 profile source/functional gates 全部闭合。Stage 20 必须拆开验证两层变化：

1. current per-entry table loop → contiguous chunk representation；
2. contiguous chunk → zero-hole chunk representation。

两层都必须冻结 schedule、active ID、batch、slot 和其它 emitter policy，并分别生成未插桩 control/candidate。任何 candidate 的最终结论只看严格 page-local、双 NUMA、ABBA+BAAB 的 SimTop 50k walltime；cycles、instructions、静态 writes 和本 profile 的插桩 walltime 仅作诊断。若 whole-node admission/runtime monitor 失败，不启动正式 run，也不降低门槛。
