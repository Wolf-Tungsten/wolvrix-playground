# NO0259 State-read reuse post profile

日期：2026-07-10

## 目标

在 [NO0258](./NO0258_scalar_state_read_change_predicate_reuse_20260710.md) 提交后，使用与
NO0256 相同的 SimTop CoreMark 50k `cycles:u` 采样参数重新 profile，确认 batch7 是否退热，
并选择下一项主线热点。

## 运行

模型：

```text
build/xs_grhsim_no0257_state_read_change_20260710/grhsim
```

命令参数：

```text
perf record -F 99 -e cycles:u --call-graph dwarf,8192
--max-cycles=50000
```

产物：

```text
build/logs/xs_perf/no0258/grhsim_state_read_change_simtop_50k_cycles.data
build/logs/xs_perf/no0258/grhsim_state_read_change_simtop_50k_cycles_run.log
build/logs/xs_perf/no0258/grhsim_state_read_change_simtop_50k_cycles_self.report
build/logs/xs_perf/no0258/grhsim_state_read_change_simtop_50k_cycles.perf-script
```

结果跑满 `50001` guest cycles，`instrCnt=73580`、`cycleCnt=49996`，未出现 difftest
mismatch。Host time 为 `107769ms`，与 NO0256 profile 的 `108862ms` 属于同一正常频率区间。

## Profile 对照

| 指标 | NO0256 | NO0258 candidate | 变化 |
| --- | ---: | ---: | ---: |
| sampled total cycles | `390645501766` | `386516584740` | `-1.06%` |
| compute aggregate | `60.15%` | `58.94%` | `-1.21pp` |
| commit aggregate | `37.40%` | `38.53%` | `+1.13pp` |
| other | `2.51%` | `2.60%` | `+0.09pp` |

按 sampled cycles 近似换算，compute 从 `234.97B` 降到 `227.81B`，约 `-3.05%`；commit
绝对值的小幅上升属于 99 Hz sample 和运行窗口波动，commit object 并未改变。

头部热点：

| symbol | NO0256 | candidate |
| --- | ---: | ---: |
| `eval_commit_batch_126()` | `2.31%` | `2.37%` |
| `eval_compute_batch_7()` | `3.00%` | `2.31%` |
| `eval_compute_batch_54()` | `1.82%` | `2.30%` |
| `eval_compute_batch_33()` | `1.90%` | `1.80%` |

batch7 的近似绝对 sampled cycles 从 `11.72B` 降到 `8.93B`，即 `-23.81%`，与其 normal
text 缩小 `22.74%` 一致。NO0258 确实命中了预期热点。

## 新热点是否由本轮引入

NO0256/NO0258 的以下 object SHA256 完全相同：

```text
compute sched54: 5dbad3ab2d89a64abc887f3525f733d91e620a9ce5cd488111412fc0bb68c5a1
commit  sched126: db0b1a554562de28ce7346e1b1a77795d46fbbd983581c3396fe1ecabf6674e2
```

因此 batch54/126 的占比变化不是 NO0258 生成了更慢代码，而是 batch7 退热、采样噪声及
最终链接布局共同改变了相对排序。

## 精确源码映射

为 batch54/126 分别生成 `-O3 -gline-tables-only` object，并校验与实际运行 object 的
`.text` SHA256 完全一致：

```text
sched54 : da7ce705fb8ecc2f6ffd008c1802f3cdc5d07198d2c6cf5bb7e86954d3d7b5de
sched126: 446dd7cf8f699e52022f654edaa914ef16982bd6595ff2244d235af71076136c
```

映射产物：

```text
build/logs/xs_perf/no0258/grhsim_state_read_change_compute_batch_54_sample_lines.tsv
build/logs/xs_perf/no0258/grhsim_state_read_change_compute_batch_54_sample_ops.tsv
build/logs/xs_perf/no0258/grhsim_state_read_change_commit_batch_126_sample_lines.tsv
build/logs/xs_perf/no0258/grhsim_state_read_change_commit_batch_126_sample_ops.tsv
```

结果：

- commit126：`248/253` sample 映射到 `kRegisterWritePort`；该 batch 是单个 commit
  supernode，包含 `42937` 个 register write。
- compute54：`154/245` sample 映射到 `kLogicAnd`；normal 函数包含 `28495` 个 ops，
  其中 `14079` 个 `kLogicAnd`、`7282` 个 `kRegisterReadPort`。

## 结论

NO0258 将预期热点 batch7 的绝对 sampled cycles 降低约 `23.8%`，可以保留。新的调查重点
不是继续修改 batch7，而是：

1. commit126 剩余的 42937 个 changed comparisons；
2. compute54 中占主导的 LogicAnd 网络。

compute54 的 RTL 来源反查见
[NO0260](./NO0260_phr_multi_write_scalarization_gap_20260710.md)。
