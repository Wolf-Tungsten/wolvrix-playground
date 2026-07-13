# NO0261 Sched54 optimize-size negative probe

日期：2026-07-10

## 目的

[NO0260](./NO0260_phr_multi_write_scalarization_gap_20260710.md) 定位到 batch54 的 PHR
one-hot 网络。完整 multi-write recovery 改动较大，本轮先验证一个更小的问题：热点是否
主要由 `-O3` 生成的超大机器码造成，单独对 sched54 使用 `-Os` 能否提速。

## Variant

基线其它 167 个 state/eval/sched objects 不变，只把 `grhsim_SimTop_sched_54.cpp` 用独立
`-Os` PCH 重编译并替换 archive member：

```text
build/xs_grhsim_no0259_sched54_os_probe_20260710
```

静态结果：

| 指标 | `-O3` | `-Os` | 变化 |
| --- | ---: | ---: | ---: |
| object bytes | `3670400` | `3573456` | `-2.64%` |
| normal text | `1912482` | `1830837` | `-4.27%` |
| fullpass text | `1620519` | `1608056` | `-0.77%` |

10k difftest 通过，Guest cycle 为 `10001`，无 mismatch。

## 50k A/B

测试时系统 load 约 `76~86/384`，因此先跑原始 `-O3` baseline，再跑 `-Os` probe，并同时
采集四个硬件 counter。

| 指标 | `-O3` baseline | `-Os` probe | 变化 |
| --- | ---: | ---: | ---: |
| Host time | `122756ms` | `111599ms` | `-9.09%` |
| cycles | `446371594953` | `406745595240` | `-8.88%` |
| instructions | `231698776854` | `232267074857` | `+0.25%` |
| branches | `19745797319` | `19878286676` | `+0.67%` |
| branch misses | `7883405099` | `7932664902` | `+0.62%` |

两边功能结果均为 `50001` guest cycles、`73580` instructions、无 mismatch。

日志：

```text
build/logs/xs/no0259_simtop_sched54_os_probe_smoke_10k_20260710.log
build/logs/xs/no0259_simtop_sched54_o3_baseline_50k_perf_stat_20260710.txt
build/logs/xs/no0259_simtop_sched54_o3_baseline_50k_perf_stat_run_20260710.log
build/logs/xs/no0259_simtop_sched54_os_probe_50k_perf_stat_20260710.txt
build/logs/xs/no0259_simtop_sched54_os_probe_50k_perf_stat_run_20260710.log
```

## 结论

wall/cycles 的表面收益来自同窗 CPU 频率和 IPC 差异；`-Os` 实际执行了更多 instructions、
branches 和 branch misses。它只减少 `4.27%` 的单函数 text，没有消除 13k PHR LogicAnd
工作，不能作为工程优化保留。

variant 仅存在于 ignored build 目录，仓库源码未修改。下一步转向
[NO0262](./NO0262_multi_write_true_merge_plan_20260710.md) 的结构恢复。
