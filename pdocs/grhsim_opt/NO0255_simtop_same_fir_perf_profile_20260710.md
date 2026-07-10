# NO0255 SimTop same-FIR GSIM / GrhSIM perf profile

日期：2026-07-10

## 背景

`NO0254` 已完成 event post-commit settle 的小负载 gate，并将后续任务指向完整
`SimTop` 的同场 GSIM / GrhSIM 对照。本轮不再继续调整分区参数，而是严格对齐
FIR，直接比较较长运行窗口、硬件计数器、perf 热点和 generated C++。

所有构建和运行命令均先执行：

```bash
source env.sh
```

## 同源构建口径

两边使用同一份当前 FIR：

```text
build/xs_grhsim_event_order_src_20260710/rtl/rtl/SimTop.fir
sha256 = 461755d7531724b6e26e1601f45db3344dc8c5c8e099b8f162d7e1b638eee877
```

此前已有 GSIM 产物的 FIR 与当前 GrhSIM 输入不完全一致，因此本轮 fresh 重建 GSIM，
不把旧 binary 当成严格基线：

```text
build/xs_gsim_no0255_current_20260710/gsim/gsim-compile/emu
build/logs/xs/no0255_fresh_current_fir_gsim_build_20260710.log
```

fresh GSIM 生成 `84713` 个 supernode。当前 GrhSIM activity schedule 为：

```text
compute supernodes       71871
commit supernodes          497
total supernodes          72368
DAG edges                703270
boundary activation edges 2446334
commit sink ops           268310
max commit ops             42937
```

这些数字用于确认比较的是当前 NO0253 hybrid event settle 结构，而不是更早的
full-graph post-commit fullpass 版本。

## 功能 smoke

fresh GSIM 10k：

```text
build/logs/xs/no0255_fresh_current_fir_gsim_smoke_10k_20260710.log
instrCnt = 458
cycleCnt = 9998
Host time spent = 3779ms
```

无 difftest mismatch、refill failure 或 ABORT。

## 相邻 50k runtime

日志：

```text
build/logs/xs/no0255_simtop_adjacent_50k_gsim_1_20260710.log
build/logs/xs/no0255_simtop_adjacent_50k_grhsim_20260710.log
build/logs/xs/no0255_simtop_adjacent_50k_gsim_2_20260710.log
```

| 顺序 | simulator | Host time | instrCnt / cycleCnt |
| --- | --- | ---: | --- |
| 1 | fresh same-FIR GSIM | `31526ms` | `73584 / 49998` |
| 2 | current hybrid GrhSIM | `133891ms` | `73580 / 49996` |
| 3 | fresh same-FIR GSIM | `30973ms` | `73584 / 49998` |

GSIM 两次均值为 `31249.5ms`，GrhSIM / GSIM 为：

```text
133891 / 31249.5 = 4.285x
```

三次均通过 50k difftest 功能门。机器未满载，且前后 GSIM 仅相差 `1.79%`，
说明该差距不是本轮机器负载波动造成的。

## perf stat

日志：

```text
build/logs/xs/no0255_simtop_gsim_50k_perf_stat_20260710.txt
build/logs/xs/no0255_simtop_grhsim_50k_perf_stat_20260710.txt
```

| metric | GSIM | GrhSIM | GrhSIM / GSIM |
| --- | ---: | ---: | ---: |
| duration | `31.306s` | `134.781s` | `4.305x` |
| cycles | `112638425978` | `485258907523` | `4.308x` |
| instructions | `80641770629` | `255312206310` | `3.166x` |
| branches | `4550525203` | `19838958877` | `4.360x` |
| branch misses | `2155491266` | `11168720905` | `5.182x` |
| cache references | `16161213712` | `54446895462` | `3.369x` |
| cache misses | `12742450215` | `38762681667` | `3.042x` |
| IPC | `0.716` | `0.526` | GSIM 高 `1.361x` |

事件组运行比例为 `83%`，因此 cache/branch miss 的绝对值只作近似参考；
instructions、cycles 和 duration 已足以说明 GrhSIM 同时存在更多动态工作和更低 IPC。

## perf record 热点

使用 `cycles:u`、99 Hz、DWARF call graph 采集 50k：

```text
build/logs/xs_perf/no0255/gsim_simtop_50k_cycles.data
build/logs/xs_perf/no0255/gsim_simtop_50k_cycles_self.report
build/logs/xs_perf/no0255/gsim_simtop_50k_cycles.perf-script
build/logs/xs_perf/no0255/grhsim_simtop_50k_cycles.data
build/logs/xs_perf/no0255/grhsim_simtop_50k_cycles_self.report
build/logs/xs_perf/no0255/grhsim_simtop_50k_cycles.perf-script
```

两边均无 lost sample。GSIM 的 `subStep*()` 合计占 `98.61%`，热点较分散，
最高的 `subStep20()` 仅 `2.48%`。

GrhSIM 聚合结果：

| 类别 | self cycles |
| --- | ---: |
| commit batches | `49.21%` |
| compute batches | `48.60%` |
| eval control | `0.83%` |
| GrhSIM helpers | `1.13%` |

最突出的两个符号为：

```text
eval_commit_batch_126()  11.19%
eval_commit_batch_112()   5.75%
```

## generated C++ 映射

两个 hot batch 都在一个共享 event guard 下顺序扫描大量 register write：

| batch | generated C++ lines | register writes |
| --- | ---: | ---: |
| 126 | `445017` | `42937` |
| 112 | `221085` | `18439` |

batch126 的写入目标包括 `28702` 个 cpu state、`10639` 个 log endpoint、
`3595` 个 endpoint 和 `1` 个 timer；batch112 的 `18439` 个写入全部属于 cpu state。
两者每个 posedge 共扫描 `61376` 个 write，50k 窗口约执行 `3.07B` 次 write body。

这些普通寄存器写入绝大多数带编译期全 1 mask，但旧 emitter 仍生成通用 merge：

```cpp
next = (state & ~mask) | (data & mask);
```

对应 slot 已确认是常量，例如 2-bit mask 为 `3`，64-bit mask 为
`UINT64_MAX`。GSIM 对同类寄存器则直接比较/写入 `$NEXT`，没有先执行全掩码 merge。

这不是说 changed check 本身只存在于 GrhSIM；GSIM 同样需要 old/NEXT 比较和后继激活。
本轮定位到的额外工作是：GrhSIM 在数十亿次全掩码 write scan 中仍执行了本可消除的
`not/and/and/or` 数据路径。

## 结论

1. strict same-FIR 50k 下，当前 hybrid GrhSIM 仍慢于 GSIM `4.285x`。
2. 差距同时包含 `3.166x` retired instructions 和约 `1.361x` IPC 劣势。
3. GrhSIM 基线时间几乎由 compute/commit 各占一半，但两个超大 commit batch 单独占
   `16.94%`，是比继续调 partition 更直接的优化入口。
4. 下一阶段实现全掩码 register commit 专门化；实现与 A/B 结果见
   [NO0256](./NO0256_full_mask_register_commit_specialization_20260710.md)。

