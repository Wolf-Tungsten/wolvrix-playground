# NO0315 NO0286 / NO0300 native stall PMU gate

日期：2026-07-12

## 1. 口径

按 [NO0314](./NO0314_native_stall_pmu_group_correction_20260712.md) 修正后的五事件组，对无 profile
NO0286 / NO0300 执行 old / new / old 固定 CPU138、NUMA node 1 配对：

```text
cycles:u
ic_tag_hit_miss.all_instruction_cache_accesses:u
ic_tag_hit_miss.instruction_cache_miss:u
de_no_dispatch_per_slot.no_ops_from_frontend:u
de_no_dispatch_per_slot.backend_stalls:u
```

三次五项均为 `100.00%` 调度。运行前 CPU138/330 四秒平均空闲 `98%/99%`；new 和 old2 前的
两秒检查分别为 `100%/98%`、`100%/98.5%`。全机 load 相对 384 个逻辑 CPU 保持很低。

## 2. 功能与稳定性

三次均得到：

```text
Guest cycle spent: 50001
cycleCnt = 49996
instrCnt = 73580
terminal PC = 0x80001312
```

无 assertion、abort 或 difftest mismatch。两次 old 的 Host time/cycles spread 为 `0.481%/0.485%`，
明显小于 new 的约 `4.4%` 差异。

## 3. 原生计数

下表 old 为两次均值：

| Metric | NO0286 old mean | NO0300 new | New vs old |
| --- | ---: | ---: | ---: |
| Host time (ms) | 81,096.5 | 84,658 | +4.392% |
| cycles | 296,800,963,277 | 309,798,834,300 | +4.379% |
| I-cache accesses | 113,296,682,004 | 109,594,014,758 | -3.268% |
| I-cache misses | 38,235,727,887 | 36,894,796,047 | -3.507% |
| frontend empty slots | 1,351,545,709,535 | 1,453,002,983,755 | +7.507% |
| backend stall slots | 98,665,708,724 | 94,384,036,881 | -4.340% |

按 host cycles 归一化：

| Metric / cycle | NO0286 | NO0300 | Delta |
| --- | ---: | ---: | ---: |
| I-cache accesses | 0.381726 | 0.353759 | -7.327% |
| I-cache misses | 0.128826 | 0.119093 | -7.555% |
| frontend empty slots | 4.553711 | 4.690150 | +2.996% |
| backend stall slots | 0.332431 | 0.304662 | -8.353% |

native I-cache miss/access 比率也从 `33.7483%` 小幅降至 `33.6650%`。因此唯一与 cycles 回退同方向的
stall density 是 frontend empty slots；backend 和 I-cache 事件均改善。

## 4. 与 dynamic work / 既有 PMU 合并

[NO0312](./NO0312_no0286_no0300_dynamic_work_gate_20260712.md) 已显示 total work `-4.30%`、compute
work `-4.98%`，但 compute samples/work `+9.33%`。本轮进一步证明该单位成本不是 data/backend stall
总量增加，也不是 I-cache miss 增加。

[NO0302](./NO0302_ordered_memory_write_affine_overall_50k_gate_20260712.md) 中 NO0300 的 branches
几乎不变（`+0.062%`），branch misses 下降 `2.032%`，但 work 已下降 `4.303%`；归一化后 branches/work
和 branch-misses/work 反而增加 `4.56%/2.37%`。结合 [NO0303](./NO0303_ordered_memory_write_affine_post_profile_20260712.md)
观察到的 compute batch 全局混排，当前更符合控制流密度、taken-branch/redirect 或 decode/fetch bandwidth
效率恶化，而不是 I-cache 容量或 backend 数据路径压力。

## 5. 结论与下一步

NO0300 的剩余回退明确归入 frontend supply，但需要保持以下边界：

- 已排除更多 I-cache access/miss；
- 已排除更高 backend stall density；
- 不能仅凭 empty slots 断言是 ITLB、branch redirect 还是 decode bandwidth。

下一步查看本机 AMD PMU 的 frontend-bound 子事件，选择可 100% 调度的 ITLB、branch redirect/taken
branch 和 decoder-op 事件组做 old/new/old。若 ITLB 同样不恶化，则 root cause 将进一步落到 graph 重排后的
控制流/函数内布局和解码供给，应优先改变 batch packing 或 generated hot-path branch shape，而不是继续减
supernode/activation 数量。

## 6. 产物

```text
build/logs/xs_perf/no0314/native5_old1_emu.log
build/logs/xs_perf/no0314/native5_old1_perf.csv
build/logs/xs_perf/no0314/native5_new_emu.log
build/logs/xs_perf/no0314/native5_new_perf.csv
build/logs/xs_perf/no0314/native5_old2_emu.log
build/logs/xs_perf/no0314/native5_old2_perf.csv
```

