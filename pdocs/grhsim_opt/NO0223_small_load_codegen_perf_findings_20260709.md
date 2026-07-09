# NO0223 Small-Load Codegen / Perf Findings

记录日期：2026-07-09

关联：[`NO0222`](./NO0222_small_load_codegen_perf_runbook_20260709.md)、[`NO0196`](./NO0196_two_eval_vs_xiangshan_sink_succ_inconsistency_20260614.md)、[`NO0199`](./NO0199_firrtl_packed_array_split_in_grhsim_cases_20260615.md)、[`NO0221`](./NO0221_no0217_plain_bae_artifact_rebuild_20260707.md)

## 1. 本轮产物

本轮按 `NO0222` 的小负载口径执行，未改 simulator/codegen 源码。主要产物：

```text
tmp/no0222_small_load_codegen_perf_20260709/raw_bench/
tmp/no0222_small_load_codegen_perf_20260709/code_shape/
tmp/no0222_small_load_codegen_perf_20260709/perf/
tmp/no0222_small_load_codegen_perf_20260709/summary/
testcase/big-comb/build/no0222_small_load_codegen_perf_20260709/
testcase/xs-components/build/no0222_small_load_codegen_perf_20260709/
```

其中 `tmp/no0222_small_load_codegen_perf_20260709/summary/summary.json` 是本轮表格的机器可读汇总；同目录还导出了 `raw_timing.tsv`、`code_shape.tsv`、`runtime_profile.tsv`、`perf_summary.tsv`。

执行备注：

- `make py_install` 之前删除了旧 checkout 路径遗留的 ignored `wolvrix/build/skbuild`，否则 CMake cache 会拒绝复用。
- `perf stat` 探测时 `cache-misses` 受 NMI watchdog 影响可能不计数，本轮正式 perf 只保留 `cycles/instructions/branches/branch-misses/duration_time/user_time/system_time`。
- 本机未找到 `flamegraph.pl` / `stackcollapse-perf.pl` / Inferno，因此未生成 SVG flamegraph；已保留每个 case 的 `perf script`，后续装好工具后可直接生成。
- benchmark 可执行文件当前没有“只跑 GSIM”或“只跑 GrhSIM”的开关，perf report 是同一进程内先 GSIM、后 GrhSIM 的合并采样，本文用符号名前缀区分。

## 2. Raw no-profile timing

| case | vectors | GSIM ms | GrhSIM ms | GrhSIM/GSIM | checksum |
| --- | ---: | ---: | ---: | ---: | --- |
| `BigComb` | 1000000 | 18412.182 | 18423.966 | 1.001 | match |
| `XsReal100BackendNfmappedelemidxSmall` | 200002 | 8.851 | 7.937 | 0.897 | match |
| `XsReal053FtqFtqLarge` | 200002 | 382.939 | 621.988 | 1.624 | match |
| `XsReal043TageTageLarge` | 200002 | 311.882 | 519.662 | 1.666 | match |
| `XsReal075RobVtypebufferLarge` | 200002 | 210.040 | 462.889 | 2.204 | match |

直接结论：

- 当前版本在纯组合 `BigComb` 上已经基本不慢，perf rerun 中甚至因噪声/频率差异表现为 GrhSIM 略快。
- 很小的 `NfmappedElemidxSmall` 也不是问题 case。
- 三个含状态/aggregate 更新的大 case 仍然慢 `1.62x` 到 `2.20x`，`VtypebufferLarge` 是本轮最强 ROI。

## 3. Static code shape

| case | GSIM instr | GrhSIM instr | instr ratio | GSIM .text | GrhSIM .text | text ratio | GrhSIM supernodes | commit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `BigComb` | 232800 | 186389 | 0.801 | 952103 | 891807 | 0.937 | 1602 | 0 |
| `XsReal100BackendNfmappedelemidxSmall` | 473 | 590 | 1.247 | 2078 | 2449 | 1.179 | 2 | 0 |
| `XsReal053FtqFtqLarge` | 17094 | 17712 | 1.036 | 80826 | 83988 | 1.039 | 48 | 1 |
| `XsReal043TageTageLarge` | 14582 | 15239 | 1.045 | 67212 | 71899 | 1.070 | 42 | 1 |
| `XsReal075RobVtypebufferLarge` | 11047 | 12838 | 1.162 | 50133 | 61353 | 1.224 | 39 | 1 |

这个表不支持“GrhSIM 慢只是因为生成代码总量大”的解释。三个慢 case 中，GrhSIM `.text` 只比 GSIM 大 `3.9% / 7.0% / 22.4%`，但 raw runtime 慢 `62.4% / 66.6% / 120.4%`。

## 4. Runtime profile TSV

runtime profile 需要重新 emit/profile build，会改变绝对时间；这里主要看 static/fire 行数与每向量 fire 量，不用它替代 no-profile timing。

| case | vectors | GSIM ms | GrhSIM ms | GrhSIM/GSIM | GSIM rows | GSIM fires/vector | GrhSIM rows | GrhSIM fires/vector |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `XsReal100BackendNfmappedelemidxSmall` | 200002 | 9.072 | 7.963 | 0.878 | 1 | 1.00 | 2 | 2.00 |
| `XsReal053FtqFtqLarge` | 200002 | 581.417 | 650.191 | 1.118 | 432 | 430.10 | 48 | 86.93 |
| `XsReal043TageTageLarge` | 200002 | 465.485 | 520.521 | 1.118 | 405 | 403.84 | 42 | 74.94 |
| `XsReal075RobVtypebufferLarge` | 200002 | 308.280 | 461.032 | 1.495 | 274 | 271.86 | 39 | 68.99 |

一个反直觉但重要的现象：在三个慢 case 上，GrhSIM 的 fire rows 和 fires/vector 都显著少于 GSIM，但仍然更慢。也就是说，这批小负载上的主问题不像是“活动 supernode 数量更多”，而是 GrhSIM 单次 batch/fire 的每次工作更重。

## 5. Perf report 摘要

| case | perf vectors | perf GrhSIM/GSIM | GSIM self% | GrhSIM model self% | GrhSIM helper self% | top symbol |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `BigComb` | 1000000 | 0.943 | 51.16 | 47.21 | 1.09 | `SBigComb::subStep4()` |
| `XsReal100BackendNfmappedelemidxSmall` | 20000000 | 0.882 | 47.09 | 40.28 | 0.00 | `SXsReal100BackendNfmappedelemidxSmall::subStep0()` |
| `XsReal053FtqFtqLarge` | 2000000 | 1.629 | 37.70 | 48.27 | 13.52 | `SXsReal053FtqFtqLarge::subStep0()` |
| `XsReal043TageTageLarge` | 2000000 | 1.670 | 37.20 | 51.95 | 10.47 | `SXsReal043TageTageLarge::subStep0()` |
| `XsReal075RobVtypebufferLarge` | 2000000 | 2.209 | 30.74 | 54.59 | 13.95 | `SXsReal075RobVtypebufferLarge::subStep0()` |

大 case 的 top GrhSIM 热点集中在：

- FTQ: `eval_compute_batch_{0..5}`、`eval_commit_batch_6`、`grhsim_xor_words<16>`。
- Tage: `eval_compute_batch_{0..4}`、`eval_commit_batch_5`、`grhsim_xor_words<16>` / `grhsim_and_words<16>`。
- VtypeBuffer: `eval_compute_batch_{0..3}`、`eval_commit_batch_4`、`grhsim_and_words<16>` / `grhsim_assign_words<16>` / `grhsim_xor_words<16>`。

`VtypebufferLarge` 的 perf record stdout 为 `gsim=2125.737ms`、`grhsim=4695.578ms`，与 raw slowdown 一致；report 中 GrhSIM model+helper self 约 `68.5%`，GSIM self 约 `30.7%`。

## 6. 生成 C++ 直接观察

以 `XsReal075RobVtypebufferLarge` 为例：

- GrhSIM `eval()` 在 `grhsim_XsReal075RobVtypebufferLarge_eval.cpp` 中顺序调用 4 个 compute batch 和 1 个 commit batch。
- GrhSIM 最大热点文件是 `grhsim_XsReal075RobVtypebufferLarge_sched_3.cpp`，约 `3248` 行，perf top 最高的 `eval_compute_batch_3()` 就在这个文件。
- 该文件中大量 1024-bit helper 调用集中出现，例如 `grhsim_xor_words(..., 1024)`、`grhsim_and_words(..., 1024)`、`grhsim_assign_words(..., 1024)`；对应 helper 定义在 `grhsim_XsReal075RobVtypebufferLarge_runtime.hpp`。
- GSIM 对应热点主要是 `SXsReal075RobVtypebufferLarge::subStep0()` / `subStep1()`，生成文件 `XsReal075RobVtypebufferLarge0.cpp` / `1.cpp` 中大量使用 `uint64_t` 局部变量和按 lane 展开的 scalar 表达式。

这和 `NO0196` / `NO0199` 的方向一致：aggregate/packed-array 在 GrhSIM 侧容易走“宽 word 重建 + helper + changed check”的路径，而 GSIM 的生成代码更像按 64-bit lane/scalar 直接更新。

## 7. 当前结论

本轮最可信的结论是：

- GrhSIM 当前对纯组合或极小 case 已经可以接近或超过 GSIM，小负载并不支持“GrhSIM 全局固定慢”的说法。
- 三个状态/aggregate case 的慢，不主要由总 `.text` 或静态指令数解释。
- 慢 case 的 perf 热点显示，GrhSIM 时间集中在少数 `eval_compute_batch_*` / `eval_commit_batch_*` 和宽字 helper；runtime profile 同时显示 GrhSIM 的 fire 次数更少，说明每次 GrhSIM batch/fire 的单位成本过高。
- 下一步应优先攻 `VtypebufferLarge` 这类宽 word helper/codegen 形态，而不是继续只调整全局分区/拓扑排序指标。

暂不能由本轮数据支持的结论：

- 不能证明完整 XiangShan `SimTop` 的主因已经完全等同于 `VtypebufferLarge`；这里只说明小负载上存在一个可直接观察、可复现的强候选。
- 不能从合并 perf report 精确得到 GSIM 和 GrhSIM 各自的硬件计数；当前 bench 没有 model-select 开关，`perf stat` 是两者合并。
- 不能确认 helper 慢是因为未内联、数组返回、mask tail、changed check，还是宽 word 生命周期/寄存器压力；需要下一步单点 A/B。

## 8. 后续建议

优先级建议：

1. 给 `testcase/xs-components` bench 增加 `--model gsim|grhsim|both`，让 perf stat/report 能按模型单独采样。
2. 以 `XsReal075RobVtypebufferLarge` 为第一 ROI，对 `grhsim_*_words<16>` 做 codegen A/B：专化 16-word helper、避免返回 `std::array` 临时、把 assign changed check 融进 producer、或对 1024-bit lane 生成直线化 scalar 更新。
3. 对 FTQ/Tage/VtypeBuffer 做同一批 A/B，验收先看 raw no-profile slowdown，再看 perf helper self% 是否下降。
4. 保留 `BigComb` 和 `NfmappedElemidxSmall` 作为 guard：宽 word 优化不能让 compute-only/小 case 明显回退。

## 9. 仿真 cycle / eval 数量说明（2026-07-09）

补充精确口径：这些 microbench 当然可以数出跑了多少“仿真周期”，只是这里的周期不是完整 XiangShan/CoreMark guest cycle，而是 testbench 定义的 component-level cycle / input vector。

`xs-components` 的 testbench 口径：

- `make_vectors(N)` 会额外插入 2 个 seed vector，所以命令 `--vectors 200000` 在日志中显示为 `vectors=200002`。
- 1 个日志 vector 对应 1 个 component-level cycle / input transaction。
- GSIM：每个 vector 调 1 次 `step()`。
- GrhSIM：每个 vector 调 2 次 `eval()`，先 `clock=false; eval()`，再 `clock=true; eval()`。
- 每个 `[BENCH]` 计时前都会先跑 1 轮 warmup；raw bench 的 `repeat=3` 表示正式计时跑 3 个等长窗口，日志中的 `ms` 取最小值。

本轮 `xs-components` 的精确执行长度：

| 阶段 | 命令 vectors | 日志 vectors / window | repeat | `[BENCH]` 代表的 timed cycles | 每个 model 实际 benchmark loop cycles（含 warmup） | GrhSIM eval calls（含 warmup） |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| raw no-profile | 200000 | 200002 | 3 | 200002 | 800008 | 1600016 |
| runtime profile | 200000 | 200002 | 1 | 200002 | 400004 | 800008 |
| perf small case | 20000000 | 20000002 | 1 | 20000002 | 40000004 | 80000008 |
| perf FTQ/Tage/VtypeBuffer | 2000000 | 2000002 | 1 | 2000002 | 4000004 | 8000008 |

说明：

- 上表“每个 model 实际 benchmark loop cycles”不含 verify/reset；raw correctness 另用 `verify=2048`，perf 用 `verify=0`。
- runtime profile counter 在 warmup 后打开，因此 profile TSV 只统计正式 timed window，即 `200002` component cycles。
- perf 采样覆盖整个进程，所以包含 warmup + timed run；因此大 case 的 perf 实际每个 model 采样约 `4,000,004` component cycles，其中 GrhSIM 约 `8,000,008` 次 `eval()`。

`BigComb` 是组合逻辑 microbench，本身没有 clocked hardware cycle；可数的是 input-vector eval 次数：

| 阶段 | vectors / timed window | GSIM calls | GrhSIM calls | 备注 |
| --- | ---: | ---: | ---: | --- |
| raw no-profile | 1000000 | 1000000 次 `step()` | 1000000 次 `eval()` | 另有 `verify=4096` |
| perf | 1000000 | 1000000 次 `step()` | 1000000 次 `eval()` | `verify=0` |

所以更准确的判断是：raw no-profile 的 xs-components 结果每个计时窗口是 `200002` component cycles，作为初筛能看出 `1.6x-2.2x` 的大差距，但确实不算长；perf 采样已经放大到 `2,000,002` component cycles / timed window，且 perf 进程实际包含 warmup + timed run，慢的三个大 case 每个 model 约跑 `4,000,004` component cycles。若要把 no-profile timing 也做成更强证据，下一轮应补 `2M` 或 `5M` component cycles、`repeat=3/5` 的 raw rerun。
