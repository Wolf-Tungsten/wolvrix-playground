# NO0280 OR-decoded true-merge cycles post-profile

日期：2026-07-11

## 1. 目标与口径

[NO0279](./NO0279_or_decoded_true_merge_simtop_50k_gate_20260711.md) 已确认 NO0278 在
SimTop 50k 上将 host cycles 降低 `11.28%`，但 instructions 只降低 `0.22%`。本轮继续比较：

- old：NO0274 edge-padded true-merge；
- new：NO0278 OR-decoded priority true-merge；
- workload：CoreMark 2 iterations、NEMU difftest、`-C 50000`；
- CPU：CPU138，SMT sibling 为 CPU330；
- 所有运行前均执行 `source env.sh`。

分析分为三层：固定周期 `perf record`、目标状态 operation 映射，以及两组固定 CPU 的
old/new/old 硬件计数器。三个 counter paired run 的事件均为 `100% scheduled`。

## 2. Cycles post-profile

两边使用 `cycles:u`、period `25000000`、DWARF stack `8192`。两次均执行到相同功能终点，
且 lost sample 为 0：

| metric | old | new | delta |
| --- | ---: | ---: | ---: |
| samples | `13749` | `12204` | `-1545` (`-11.24%`) |
| approximate event count | `343725000000` | `305100000000` | `-11.24%` |
| Guest cycle spent | `50001` | `50001` | `0` |
| instrCnt / cycleCnt | `73580 / 49996` | `73580 / 49996` | identical |
| terminal PC | `0x80001312` | `0x80001312` | identical |

按精确 symbol sample 聚合：

| category | old samples | new samples | delta | share old -> new |
| --- | ---: | ---: | ---: | ---: |
| compute batches | `9418` | `8033` | `-1385` (`-14.71%`) | `68.50% -> 65.82%` |
| commit batches | `4111` | `3941` | `-170` (`-4.14%`) | `29.90% -> 32.29%` |
| eval | `31` | `27` | `-4` | `0.23% -> 0.22%` |
| row-reader helpers | `2` | `1` | `-1` | negligible |
| other | `187` | `202` | `+15` | `1.36% -> 1.66%` |

compute 的 `-1385` samples 占总 sample 减量的 `89.64%`，commit 为 `11.00%`，其他类别的
小幅增加抵消约 `0.65%`。因此收益的主要落点是 compute，而不是新 memory write 所在的
commit batch。

## 3. 目标 operation 的直接成本

将 old `value_bool_slots_` 的 outer write guard 映射回 generated source：

- commit104 的 DCache `prefetchArray.meta_array` 映射到 `38` samples，约 `0.95B` cycles；
- commit106 的三个目标 LLPTW family 只观察到 `1` sample，约 `0.025B` cycles；
- 两者即使在 new 中全部消失，也只占 profile 总下降 `38.625B` cycles 的约 `2.52%`。

DCache read 所在 compute2/compute10 合计从 `190` samples 降为 `138`，差值 `52` samples，
约占总下降的 `3.37%`。按 `value_u8_slots_` output access 做近邻归因时，DCache read 本身在
old/new 都只观察到 `1` sample；该归因只用于确认没有直接热点，不用于精确核算单个 operation。

这说明 7 个新增 memory group 的直接读写 body 不是 `11%` 收益的主体。NO0278 同时改变了
303 个 compute supernode、1911 个 compute-commit value pair、约 4.88 MB generated C++ 和
217 KB 最终 `.text`，更大范围的 compute code placement 随之变化。

## 4. Generic frontend counter paired run

第一组事件为：

```text
cycles:u
instructions:u
stalled-cycles-frontend:u
L1-icache-loads:u
L1-icache-load-misses:u
```

| metric | old 1 | new | old 2 | new vs old mean |
| --- | ---: | ---: | ---: | ---: |
| Host time | `92077ms` | `83237ms` | `91623ms` | `-9.38%` |
| cycles | `336885295124` | `304592107755` | `335336539783` | `-9.38%` |
| instructions | `190864283302` | `190436311216` | `190863038503` | `-0.22%` |
| frontend stalled cycles | `207700059003` | `175878092260` | `206250864409` | `-15.02%` |
| L1I loads | `116781218662` | `117349090326` | `117249616734` | `+0.29%` |
| L1I misses | `1246514322` | `1281983951` | `1244921733` | `+2.91%` |

old 两次 Host time spread 为 `0.49%`，cycles spread 为 `0.46%`。frontend stalled cycles
占比从 old 均值的 `61.58%` 降到 new 的 `57.74%`。绝对减少 `31.10B` frontend stalled
cycles，而总 cycles 减少 `31.52B`；两者数值比为 `98.66%`。

因此本组 counter 将几乎全部 cycles 收益定位到 frontend stall 下降。L1I load/miss 没有下降，
不能用“执行了更少指令”或“generic L1I miss 更少”解释该收益。

## 5. AMD native frontend counter paired run

第二组使用 CPU 原生事件：

```text
cycles:u
ic_tag_hit_miss.all_instruction_cache_accesses:u
ic_tag_hit_miss.instruction_cache_miss:u
de_no_dispatch_per_slot.no_ops_from_frontend:u
de_no_dispatch_per_slot.backend_stalls:u
```

`de_no_dispatch_per_slot.*` 统计空 dispatch slots，不是 cycle 数。结果为：

| metric | old 1 | new | old 2 | new vs old mean |
| --- | ---: | ---: | ---: | ---: |
| Host time | `92210ms` | `83354ms` | `92944ms` | `-9.96%` |
| cycles | `337453350582` | `305064270476` | `340157387946` | `-9.96%` |
| ICache accesses | `116223556851` | `115881057471` | `115949387570` | `-0.18%` |
| ICache misses | `40941089175` | `40422336906` | `40938098492` | `-1.26%` |
| no ops from frontend | `1557637556783` | `1367227268875` | `1574196908840` | `-12.69%` |
| backend stalls | `108634363041` | `105362319512` | `107705822764` | `-2.60%` |

old 两次 Host time spread 为 `0.79%`，cycles spread 为 `0.80%`。前端未供给造成的空 slot
下降 `12.69%`，明显大于 ICache access、ICache miss 和 backend stall 的变化。按 cycles
归一化后，frontend empty slots 从 `4.622/cycle` 降为 `4.482/cycle`，而 backend stalls
从 `0.319/cycle` 升为 `0.345/cycle`。

这与 generic counter 一致：NO0278 的 IPC 收益主要来自 frontend 更连续地向 dispatch 提供
operation，而不是 backend stall 或 ICache miss 数量本身。

## 6. 结论与下一步

本轮得到的是性能机制结论，而不是把全部收益归因到某一条 DCache statement：

1. `11%` 左右的收益主要分布在 compute，目标 DCache/LLPTW 读写的直接 sampled cost 很小；
2. 两组成对 counter 都把 cycles 下降定位到 frontend supply/stall；
3. instructions 基本不变，ICache access/miss 变化也远小于 frontend empty slots；
4. 最合理的当前解释是：删除 scalar state/read 并重排 schedule 后，超大 generated code 的布局、
   取指连续性、分支位置或前端队列行为改善；现有数据不能再细分其中哪一项；
5. 因为 `.text` 只缩小 `0.21%` 却带来约 `10%~11%` cycles 变化，该收益包含明显的全局布局
   放大效应，不能假设后续每恢复一组 array 都会线性获得同样收益。

下一步先在同一 CPU、同一 50k workload 上采集 same-FIR GSim 的相同 frontend counters，确认
GSim 与当前 GrhSIM 的剩余 IPC 差是否同样由 frontend supply 主导；随后再决定是继续恢复 GSim
保留的 array，还是直接处理 GrhSIM 超大 compute function 的 code layout。

## 7. 产物

```text
build/logs/xs_perf/no0280/old_no0274_cpu138_50k_cycles.data
build/logs/xs_perf/no0280/new_no0278_cpu138_50k_cycles.data
build/logs/xs_perf/no0280/old_no0274_cpu138_50k_cycles_exact_symbols.report
build/logs/xs_perf/no0280/new_no0278_cpu138_50k_cycles_exact_symbols.report
build/logs/xs_perf/no0280/compute_dcache_read_sample_summary.tsv
build/logs/xs_perf/no0280/frontend_old_no0274_cpu138_50k_run1_perf_stat.csv
build/logs/xs_perf/no0280/frontend_new_no0278_cpu138_50k_perf_stat.csv
build/logs/xs_perf/no0280/frontend_old_no0274_cpu138_50k_run2_perf_stat.csv
build/logs/xs_perf/no0280/native_old_no0274_cpu138_50k_run1_perf_stat.csv
build/logs/xs_perf/no0280/native_new_no0278_cpu138_50k_perf_stat.csv
build/logs/xs_perf/no0280/native_old_no0274_cpu138_50k_run2_perf_stat.csv
```
