# NO0287 Commit state-change unlikely 50k gate

日期：2026-07-11

## 1. Paired runtime gate

候选为 [NO0286](./NO0286_commit_state_change_unlikely_codegen_20260711.md)，基线为保留的 NO0283 emu。
测试前整机 load average `11.61/15.08/16.93`，机器有 384 logical CPUs；CPU138 三秒平均
`96% idle`。old/new/old 固定 CPU138，四个 perf events 均 `100%` 调度，三次均执行到完全相同的
50k 功能终点。

| run | Host time | cycles:u | instructions:u | branches:u | branch-misses:u |
| --- | ---: | ---: | ---: | ---: | ---: |
| NO0283 old 1 | `82325ms` | `301908112795` | `188789212958` | `14996941085` | `5542846056` |
| NO0286 unlikely | `80934ms` | `296899700806` | `188838118195` | `15048377817` | `5500645848` |
| NO0283 old 2 | `82290ms` | `301557505956` | `188788991396` | `14996901419` | `5539011709` |

两次 old Host time 仅差 `35ms`（`0.043%`）。相对 old 均值：

- Host time `-1.6687%`；
- cycles `-1.6018%`；
- instructions `+0.0260%`，基本不变；
- branches `+0.3431%`；
- branch-misses `-0.7270%`。

hint 没有删除动态工作，甚至略增 branch 指令；收益来自相同 instructions 的平均周期下降，符合热路径
fall-through/code layout 改善，而不是 branchless 或激活语义变化。

## 2. Fixed-period cycles post-profile

NO0286 使用 `cycles:u`、period `25000000`、DWARF stack `8192`，完成相同 50k 终点：

```text
Host time spent: 81385ms
samples = 11882
lost samples = 0
```

与 [NO0285](./NO0285_state_read_alias_post_profile_commit_layout_diagnosis_20260711.md) 的 NO0283
cycles profile 对比：

| phase | NO0283 samples | NO0286 samples | delta |
| --- | ---: | ---: | ---: |
| compute batches | `8042` | `7983` | `-59` (`-0.73%`) |
| commit batches | `3866` | `3695` | `-171` (`-4.42%`) |
| all user symbols | `12117` | `11878` | `-239` (`-1.97%`) |

commit 占 user-symbol sample 减量的 `71.55%`，说明优化命中了目标 phase。单个 batch 仅约 100 到
300 samples，波动较大：commit79 `148 -> 130`、commit82 `173 -> 163`，但 commit94
`196 -> 213`、commit113 `344 -> 351`。因此只采信 commit aggregate，不把单个函数变化解释为稳定收益。

## 3. 结论

1. register/latch commit changed-path cold hint 保持功能正确，并在干净 old/new/old 窗口得到约 `1.6%`
   host cycles 收益。
2. instructions 基本不变、commit cycles samples 降 `4.42%`，证实 GrhSIM 相比 GSim 的一部分额外
   成本来自逐 scalar changed branch 的代码布局，而不只是动态指令数量。
3. 全局 `.text +0.97%` 是明确代价，但当前 runtime 收益足以覆盖，因此默认启用并保留环境回退开关。
4. 该优化不能消除 GrhSIM/GSim 的主要差距。下一步应回到 compute instruction 大头，优先分析
   compute39 的 dynamic slice/one-hot decode 与 GSim 对应实现。

## 4. 产物

```text
build/logs/xs_perf/no0286/paired_old_no0283_cpu138_50k_run1.log
build/logs/xs_perf/no0286/paired_new_commit_change_unlikely_cpu138_50k.log
build/logs/xs_perf/no0286/paired_old_no0283_cpu138_50k_run2.log
build/logs/xs_perf/no0286/paired_*_perf_stat.csv
build/logs/xs_perf/no0286/commit_change_unlikely_cpu138_50k_cycles.data
build/logs/xs_perf/no0286/commit_change_unlikely_cpu138_50k_cycles_exact_symbols_samples.report
build/logs/xs_perf/no0286/old_new_cycles_batch_delta.tsv
```
