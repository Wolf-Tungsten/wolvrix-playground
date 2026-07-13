# NO0323 NO0286 / NO0300 frontend full-empty profile

日期：2026-07-12

## 1. 采样有效性

按 [NO0322](./NO0322_frontend_full_empty_sampling_plan_20260712.md) 对无 profile NO0286 / NO0300
分别采集 frontend `cmask=6` full-empty 事件：fixed CPU138、NUMA node 1、period `10,000,000`、8 KiB
DWARF call graph、CoreMark 50k 和 NEMU difftest。

两边均得到 `Guest cycle spent = 50001`、`cycleCnt = 49996`、`instrCnt = 73580` 和 terminal PC
`0x80001312`；无 assertion、abort 或 difftest mismatch。运行前局部 CPU 检查通过；new 前发现 sibling CPU330
有连续两秒 `3%~5%` 占用后等待，正式启动前 CPU138/330 连续四秒均 `100%` 空闲。

| Metric | NO0286 | NO0300 | Delta |
| --- | ---: | ---: | ---: |
| samples | 17,434 | 19,558 | +12.183% |
| approximate event count | 174.34B | 195.58B | +12.183% |
| lost samples | 0 | 0 | - |
| `perf.data` size | 141 MB | 158 MB | - |

采样总量增幅比 [NO0317](./NO0317_no0286_no0300_frontend_latency_itlb_gate_20260712.md) 无 record
stat 的 cmask6 `+11.115%` 高约 `1.07` 个百分点；DWARF unwind/record 会扰动运行，但方向与量级一致。本轮只用
profile 分布做归因，不替代无 record A/B/A 性能结论。

## 2. Phase 分解

exact symbol 汇总：

| Phase | NO0286 samples | NO0300 samples | Delta | Share of total increase |
| --- | ---: | ---: | ---: | ---: |
| compute | 11,845 | 13,637 | +1,792 (+15.13%) | 84.37% |
| commit | 5,249 | 5,550 | +301 (+5.73%) | 14.17% |
| eval | 39 | 36 | -3 (-7.69%) | -0.14% |
| other | 301 | 335 | +34 (+11.30%) | 1.60% |
| total | 17,434 | 19,558 | +2,124 (+12.18%) | 100% |

结合 [NO0312](./NO0312_no0286_no0300_dynamic_work_gate_20260712.md) 的 compute work `-4.984%` 与
commit work `+0.691%`，full-empty samples/work 分别回退约 `21.2%/5.0%`。因此 frontend latency 回退比普通
cycles profile 更集中在 compute，后续应先分析 compute packing。

## 3. 热点分布

NO0300 最大 symbol 为 compute36 的 `456` samples，只占 total `2.33%`、compute `3.34%`。top-10 compute
合计 `3,393` samples，占 compute `24.88%`；NO0286 top-10 compute 占 `26.20%`。new 并未形成单一超大
frontend-latency hotspot，增量广泛分布在 compute functions，与 NO0303 的全局 batch 混排相符。

NO0300 top symbols 包括：

| Symbol | Samples |
| --- | ---: |
| `eval_compute_batch_36()` | 456 |
| `eval_commit_batch_115()` | 450 |
| `eval_compute_batch_21()` | 402 |
| `eval_compute_batch_8()` | 371 |
| `eval_compute_batch_61()` | 347 |
| `eval_compute_batch_4()` | 318 |
| `eval_compute_batch_58()` | 314 |
| `eval_compute_batch_62()` | 309 |
| `eval_compute_batch_63()` | 306 |

## 4. Annotate 边界

- compute36 的 456 samples 高度弥散，最大单指令仅 `0.88%`；主要落在 `cmpb/cmpw/setne/and/mov/test`，
  branch 合计很低，没有单个 guard 或 call hotspot；
- compute21 同样分布在 test/cmp/set/mov/branch；
- compute8 有 `15.39%` 落在整数 `div`，但 new compute8 总样本低于 old 同名 batch，且 NO0303 已证明两者
  逻辑不同，不能仅凭同名比较把 div 认定为总体增量；
- commit115 的样本以 changed-check `jne/cmp/movb` 为主，但 commit 只占总增量 `14.17%`，不是第一主线。

该事件不是 precise PMU，sample IP 可能有 skid；annotate 用于排除单一指令集中，不能把每个 IP 当作精确 stall
触发点。

## 5. 结论与下一步

full-empty frontend latency 的回退是 compute-wide、非单一函数/指令问题。下一步把 generated source 中的
batch→supernode 映射，与 NO0310/NO0311 的 static/fire TSV 连接，计算每个 batch 的 dynamic fire/work 和
full-empty samples/work；再结合 `_op_<id>` overlap 筛选“相对旧逻辑来源异常”的 new batches。只有完成该
归一化后，才判断 batch packing、supernode composition 或某类运算是否值得改动。

## 6. 产物

```text
build/logs/xs_perf/no0322/old_no0286_cmask6_50k.data
build/logs/xs_perf/no0322/old_no0286_cmask6_50k_symbols.report
build/logs/xs_perf/no0322/new_no0300_cmask6_50k.data
build/logs/xs_perf/no0322/new_no0300_cmask6_50k_symbols.report
build/logs/xs_perf/no0322/compute_batch_op_overlap.report
build/logs/xs_perf/no0322/new_compute36_cmask6_annotate.report
build/logs/xs_perf/no0322/new_compute21_cmask6_annotate.report
build/logs/xs_perf/no0322/new_compute8_cmask6_annotate.report
build/logs/xs_perf/no0322/new_commit115_cmask6_annotate.report
```

