# NO0246 Best GrhSIM vs GSIM remaining gap on VtypeBuffer

日期：2026-07-09

## 背景

`NO0245` 已经把 `input_fullpass_specialization + posedge_fullpass_specialization` 收敛为默认关闭的 GrhSIM codegen 开关。本轮继续主线任务：在当前 best GrhSIM 上重新对照 GSIM，确认剩余慢点具体来自哪里。

本轮只跑 `XsReal075RobVtypebufferLarge`，因为它是前面所有 small-load 诊断证据最完整的 case。

## 负载与口径

所有命令均在 `source env.sh` 后执行。

fresh build / paired bench 目录：

```text
tmp/no0246_best_vs_gsim_20260709/
```

GrhSIM 开关：

```text
GRHSIM_INPUT_FULLPASS_SPECIALIZATION=1
GRHSIM_POSEDGE_FULLPASS_SPECIALIZATION=1
```

机器负载：`nproc=384`。

- paired raw bench 开始/结束：1min load `5.58 -> 4.20`。
- phase/perf stat：1min load `10.95 -> 9.49`。
- perf record：1min load `6.12 -> 6.14`。

相对 384 硬件线程不高；并且 raw bench 在同一个 bench binary 内相邻运行 GSIM 与 GrhSIM，因此本轮相对结果不依赖绝对 host 负载。

## Paired raw bench

命令口径：`200000` vectors，`repeat=3`，`--verify 200000`。

```text
[VERIFY] top=XsReal075RobVtypebufferLarge vectors=200000 status=pass
[BENCH] model=gsim   vectors=200002 repeat=3 min_ms=203.787 median_ms=203.990 checksum=0xa6ff99241ea2cc48
[BENCH] model=grhsim vectors=200002 repeat=3 min_ms=309.800 median_ms=310.038 checksum=0xa6ff99241ea2cc48
```

当前 best GrhSIM 仍慢于 GSIM：

```text
309.800 / 203.787 = 1.52x
```

这已经明显优于早先 `~2x` 左右的 gap，说明 input/posedge full-pass 两步优化确实把 active/change propagation 的一大块成本消掉了。

## Phase profile

GrhSIM 单边 phase profile：`200000` vectors，`repeat=1`。

```text
[BENCH] model=grhsim vectors=200002 ms=348.390
[GRHSIM_PHASE] measured_ms=328.191 drive_ms=4.962 low_eval_ms=135.851 high_eval_ms=182.421 sample_ms=4.957 low_eval_pct_of_eval=42.68 high_eval_pct_of_eval=57.32 low_eval_ns_per_vector=679.2 high_eval_ns_per_vector=912.1
```

注意 phase profile 本身带计时扰动，不能和 raw min 直接相减；但比例很清楚：当前 best 下 high eval 仍比 low eval 更重，且二者都仍是实质工作。

## Perf stat：剩余 gap 是 retired work，不是 IPC/cache

命令口径：`2000000` vectors，`--verify 0`，`repeat=1`，分别 `--model gsim` / `--model grhsim`。

| metric | GSIM | GrhSIM best | ratio |
| --- | ---: | ---: | ---: |
| bench ms | `2052.685` | `3128.210` | `1.52x` |
| cycles | `15,398,572,728` | `23,265,814,578` | `1.51x` |
| instructions | `40,363,194,214` | `68,450,111,873` | `1.70x` |
| IPC | `2.62` | `2.94` | `1.12x` |
| branches | `2,116,191,489` | `1,133,467,011` | `0.54x` |
| branch misses | `113,663,384` | `120,901,467` | `1.06x` |
| cache misses / refs | `0.06%` | `0.06%` | roughly same |

结论：当前 best GrhSIM 的剩余 `1.52x` runtime gap 基本对应 `1.70x` retired instructions；IPC 不差，cache miss 也不是主因。branch miss 绝对数接近但不是主导解释。

产物：

```text
tmp/no0246_best_vs_gsim_20260709/perf_stat_gsim_2m.csv
tmp/no0246_best_vs_gsim_20260709/perf_stat_grhsim_2m.csv
```

## Perf report：hot symbols

产物：

```text
tmp/no0246_best_vs_gsim_20260709/perf_gsim_2m.data
tmp/no0246_best_vs_gsim_20260709/perf_grhsim_2m.data
tmp/no0246_best_vs_gsim_20260709/perf_report_gsim_2m.txt
tmp/no0246_best_vs_gsim_20260709/perf_report_grhsim_2m.txt
```

GSIM flat top：

| symbol | cycles overhead |
| --- | ---: |
| `SXsReal075RobVtypebufferLarge::subStep0()` | `70.09%` |
| `SXsReal075RobVtypebufferLarge::subStep1()` | `24.45%` |

GrhSIM best flat top：

| symbol | cycles overhead |
| --- | ---: |
| `eval_compute_batch_3_fullpass()` | `42.17%` |
| `eval_compute_batch_2_fullpass()` | `19.71%` |
| `eval_compute_batch_0_fullpass()` | `11.89%` |
| `eval_commit_batch_4()` | `11.50%` |
| `eval_compute_batch_1_fullpass()` | `10.56%` |
| `eval()` | `1.53%` |

当前已经没有大量 non-fullpass `eval_compute_batch_*()` 或 active propagation 符号出现在 top；热点集中在 full-pass compute 与 commit。

## 静态 objdump 对照

整体对象统计：

| model | static instructions | text bytes |
| --- | ---: | ---: |
| GSIM | `11047` | `50133` |
| GrhSIM best | `20922` | `98563` |

hot function 级拆解：

| function | insn | stack ops | mem ops | cmp/test/set | calls | branches |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `GSIM::subStep0()` | `7939` | `245` | `3088` | `1305` | `0` | `571` |
| `GSIM::subStep1()` | `2817` | `8` | `989` | `352` | `0` | `189` |
| `GrhSIM::eval_compute_batch_0_fullpass()` | `1178` | `41` | `433` | `0` | `0` | `1` |
| `GrhSIM::eval_compute_batch_1_fullpass()` | `984` | `117` | `436` | `14` | `0` | `1` |
| `GrhSIM::eval_compute_batch_2_fullpass()` | `1912` | `532` | `896` | `918` | `0` | `1` |
| `GrhSIM::eval_compute_batch_3_fullpass()` | `3861` | `905` | `1960` | `112` | `0` | `53` |
| `GrhSIM::eval_commit_batch_4()` | `1483` | `0` | `923` | `146` | `0` | `165` |
| `GrhSIM::eval()` | `239` | `3` | `155` | `41` | `15` | `55` |

聚合：

```text
GSIM subStep0+subStep1:          10756 insn,  253 stack ops, 4077 mem ops
GrhSIM fullpass compute once:     7935 insn, 1595 stack ops, 3725 mem ops
GrhSIM posedge commit once:       1483 insn,    0 stack ops,  923 mem ops
```

关键解释：单次 GrhSIM fullpass compute 的静态指令数并不比 GSIM `subStep0+subStep1` 多；但 GrhSIM 当前 vector 流程会在 low eval 和 high eval 各执行一次 fullpass compute。

## Fast-path hit count probe

只在 tmp generated C++ 中临时加计数器，不修改仓库源码。口径：`200000` vectors，`repeat=1`，bench 自带一次 warmup，因此总输入规模约 `2 * 200002` 次 vector eval。

输出：

```text
[GRHSIM_FASTPATH_COUNTS] input_fullpass=400003 posedge_fullpass=400005 posedge_state_changed=400003 fallback_round_entries=2
```

这确认正常路径基本是：

1. input-low eval：命中 `input_fullpass`，跑 `eval_compute_batch_0..3_fullpass()`；
2. posedge-high eval：命中 `posedge_fullpass`，先跑 `eval_commit_batch_4()`；
3. commit 后 state 几乎每次都 changed，因此再次跑 `eval_compute_batch_0..3_fullpass()`；
4. fallback fixed-point round 只在初始化/边角出现。

因此每个 vector 的近似静态执行 footprint 为：

```text
2 * fullpass_compute(7935) + commit(1483) + eval overhead
≈ 17353 + eval overhead
```

相对 GSIM：

```text
GSIM step = resetAll() + subStep0(7939) + subStep1(2817)
≈ 10756 + small reset/step overhead
```

`17353 / 10756 = 1.61x`，与 perf stat 的 instructions ratio `1.70x` 很接近。剩余差距的主因因此不是“fullpass compute 单次比 GSIM 大很多”，而是 GrhSIM 在 low/high 两个 eval 中重复跑了几乎同一套 fullpass compute；同时 GrhSIM fullpass compute 的 stack ops 很重（单次 `1595`，每 vector 约 `3190`，远高于 GSIM subStep 合计 `253`）。

## 结论

1. 当前 best GrhSIM 的 VtypeBuffer 剩余 gap 为 `1.52x`，主要由 `1.70x` retired instructions 驱动。
2. `input_fullpass + posedge_fullpass` 已经把 active/change propagation 从 top hotspot 中拿掉；新的 top hotspot 是 fullpass compute 本体和 posedge commit。
3. GSIM 的 `step()` 是 `resetAll(); subStep0(); subStep1();`，其中 `subStep1()` 静态只有 `2817` 指令；GrhSIM high eval 当前则是 `commit + 全 compute fullpass`，第二遍 compute 静态 `7935` 指令，明显比 GSIM 的第二阶段重。
4. 下一步不应继续只调 active propagation；更有希望的是做 phase-specific / post-commit compute specialization：让 posedge 后只跑真正受 state update 影响且需要对外可见/供下一拍使用的 compute 子集，目标是把 GrhSIM high phase 从“全量 fullpass”压向 GSIM `subStep1()` 的规模。
5. 另一条仍有价值的子线是降低 fullpass batch 内 stack spill / slot-ref 形态；当前单次 GrhSIM fullpass compute 的 stack ops 是 `1595`，即使只跑一遍也比 GSIM subStep 合计 `253` 高很多。

## 下一步候选

- 生成 post-commit fullpass subset 的静态候选：从 commit 写入 state 的 reader closure 出发，构造 high-phase 专用 compute batch，而不是复用 input fullpass 全量 batch。
- 对照 GSIM `subStep1()` 源码/汇编，抽样找它比 GrhSIM high fullpass 少掉的 value 家族，确认是否主要是 input-only / pre-edge-only cone。
- 若 subset 静态规模明显下降，再做 generated C++ probe；不要先大规模改 emitter。
