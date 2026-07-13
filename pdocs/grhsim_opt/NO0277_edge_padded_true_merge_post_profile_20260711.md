# NO0277 Edge-padded true-merge post profile

## 1. 目的

`NO0276` 已证明 ROB `debug_VecOtherPdest` edge-padded true-merge 能稳定降低 SimTop
50k host time/cycles 约 `16.97%`。本记录用新的 `branch-misses:u` profile 回答两个问题：

1. 原先占全 profile `2.40%` 的 ROB 状态族是否真的消失，而不是迁移到另一个 batch；
2. commit 仍占主要 branch-miss work 时，下一组应优先对照 GSim 的状态是什么。

## 2. 采样口径

新版本使用 `NO0275/NO0276` 的 fresh build：

```text
build/xs_grhsim_no0274_rob_true_merge_20260711/grhsim/emu
```

运行前 `source env.sh`，固定到 `CPU65`；该 CPU 及 SMT sibling `CPU257` 在运行前后均保持约
`97%~99%` idle。全机 load average 约 `95~101/384`，因此 `NO0276` 的 runtime gate 使用了
old/new/old 配对；本次 profile 只比较事件组成，不使用 profile wall time 代替配对性能结论。

```text
perf record -e branch-misses:u -c 500000 --call-graph dwarf,8192 \
  -o build/logs/xs_perf/no0277/edge_padded_true_merge_50k_branch_misses.data \
  -- ./emu ... -C 50000
```

功能终点仍为 `50001` guest cycles，无 mismatch/abort。profile 共 `11024` samples、lost `0`，
估算事件数 `5.512B`，与 `NO0276` perf-stat 的 `5.510B` branch misses 一致。

## 3. NO0271 old 与当前 new 的事件分布

用 `perf report --no-children -g none -F sample,period,symbol` 重新按精确 sample 数统计：

| 类别 | NO0271 old | 当前 new | sample 变化 | 估算事件变化 |
| --- | ---: | ---: | ---: | ---: |
| total | `11763` | `11024` | `-6.28%` | `5.8815B -> 5.5120B` |
| commit batches | `6837` | `6398` | `-6.42%` | `3.4185B -> 3.1990B` |
| compute batches | `4832` | `4551` | `-5.82%` | `2.4160B -> 2.2755B` |

commit/compute 在新 profile 中仍分别占 `58.04%/41.28%`。这说明本轮收益同时降低了 commit
和相关 compute work，但 commit 仍是更大的下一轮入口。

## 4. ROB 目标热点已经消除

新的 16 个 indexed write 位于 `eval_commit_batch_104()`，两组各 8 个 write，分别调用
`activate_memory_row_readers_77..84()`。逐指令 annotate 显示：

| 目标 | NO0271 old | 当前 new |
| --- | ---: | ---: |
| ROB `debug_VecOtherPdest` branch-miss samples | `282` | `0` |
| 占全 profile | `2.40%` | `0% observed` |

两个目标区间中的 outer guard、range check、state comparison 和 reader activation call 均为
`0 sample`。采样周期为 500k，因此不能把结果解释为绝对零 miss；但可以确认旧的 2816 个
scalar write guard 热点没有迁移成等量 indexed-write 热点。

## 5. commit sample 到状态族的映射

当前对象中 `value_bool_slots_` 基址为 `0x22b18`。将 annotate 中的对象位移换算为 slot 后：

- `6305/6398` commit samples 可映射到 guard slot，覆盖 `98.55%`；
- `6160/6398` 可继续映射到生成 C++ 的具体 state op，覆盖 `96.28%`；
- 其余主要来自编译器拆出的远端 changed-handler 和 sampling skid，不作为状态族排名依据。

去掉数组下标数字后的主要非 `logEndpoint` 状态族如下：

| GrhSIM 状态族 | mapped samples | GSim 形态 |
| --- | ---: | --- |
| DCache `prefetchArray.meta_array[row][lane]` | `123` | `uint8_t [256][4]` |
| SSIT `valid_array.dataBanks[*].data[*]` | `120` | scalarized |
| ABTB `takenCounter.value[bank][row][lane]` | `105` | `uint8_t [4][32][8]` |
| StoreQueue `data16[*].data[*].valid` | `98` | scalarized |
| SSIT `data_array...strict` | `91` | scalarized |
| StoreQueue `data16[*].data[*].data` | `89` | scalarized |
| SBuffer `dataModule.data[*][*][*]` | `80` | scalarized |
| mBTB replacer `states[*]` | `56` | scalarized |
| uTAGE useful entries（两表合计） | `90` | mixed/array-like |

`logEndpoint` histogram 占比很高，但它不是 GSim/GrhSIM 的明确结构差异，暂不作为
reg-to-mem matcher 的第一目标。

## 6. 下一目标：DCache prefetch meta array

同一 FIR 的 GSim header 明确保留：

```cpp
uint8_t ...prefetchArray__DOT__meta_array[256][4];
```

当前 GrhSIM 则仍生成 `4 x 256` 个 scalar register writes。`reg-to-mem` 已经发现四个
256-row candidate；以 lane 2 为例，group 900 为：

```text
members=256 element_width=3
first_reg=...prefetchArray$meta_array_0_2
last_reg=...prefetchArray$meta_array_255_2
consolidated_write_reject reason=priority_guard row=0 branch=0 unmatched=1
```

因此问题不是 discovery 缺失，而是现有 priority guard matcher 还不认识该写入 guard。
ABTB 也在同一 reject 原因失败，但当前 discovery 只形成 256 个 4-row 组；DCache 的四个
256-row 组更接近 GSim 形态，并能用更少的 memory write ports 替换相同数量的 scalar state，
所以先处理 DCache。

## 7. 下一步 gate

1. 只为 verbose candidate 输出 guard term/op 形态，确认 unmatched 的精确语义；
2. 用 synthetic case 固化该 guard，保守扩展 matcher，不按模块名做特判；
3. stop-after 要求四个 256-row 组 true-merge，其他已合并组数量不回退；
4. fresh C++ 检查目标 scalar writes 消失，并执行 SimTop 10k/50k difftest；
5. 在机器负载稳定的 CPU 上做 old/new/old 50k gate，再决定是否提交实现。

## 8. 产物

```text
build/logs/xs_perf/no0277/edge_padded_true_merge_50k_branch_misses.data
build/logs/xs_perf/no0277/edge_padded_true_merge_50k_branch_misses_exact_symbols.report
build/logs/xs_perf/no0277/tage_true_merge_50k_branch_misses_exact_symbols.report
build/logs/xs_perf/no0277/commit*_branch_misses_annotate_samples.report
build/logs/xs_perf/no0277/commit*_slot_sample_counts.tsv
build/logs/xs_perf/no0277/commit*_sampled_slot_summary.tsv
```
