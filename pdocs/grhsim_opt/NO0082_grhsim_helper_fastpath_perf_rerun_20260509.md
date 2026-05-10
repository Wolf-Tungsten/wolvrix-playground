# NO0082 GrhSIM Helper Fastpath Perf Rerun

> 2026-05-09 记录 `2-word` wide helper fast path 优化后，重新构建 `xs_wolf_grhsim_emu` 并对 XiangShan `coremark 50k` 做 host 侧 `perf` 复测。本文和 [`NO0081`](./NO0081_xs_gsim_grhsim_perf_coremark_50k_20260509.md) 的无 runtime profile 数据对齐。

## 结论

- 新 `grhsim` emu 已重新构建，产物为 `2026-05-09 19:18` 的 `build/xs/grhsim/grhsim-compile/emu`，大小 `144,346,856 bytes`。
- 裸跑和 perf 跑的 host time 稳定在 `414-417s`，和 `NO0081` 旧 `grhsim` `412.646s` 基本同档，未形成可见速度收益。
- 优化有效降低了 retired host instructions 和 retired branches：
  - instructions: `293.224B -> 254.318B`，下降 `13.27%`
  - branches: `50.961B -> 45.103B`，下降 `11.50%`
- 但 branch misses 几乎没有下降：
  - branch misses: `23.243B -> 23.220B`，仅下降 `0.10%`
  - branch miss rate: `45.61% -> 51.48%`
- 这说明前一轮锁定的 `2-word` helper 确实是 retired branch 来源之一，但不是当前 wall time 的主限制；主限制仍是 batch 内 changed-check / activation propagation 产生的难预测分支。

## 构建与运行口径

重建命令：

```bash
make --no-print-directory xs_wolf_grhsim_emu \
  XS_SIM_MAX_CYCLE=50000 \
  WOLVRIX_GRHSIM_PERF=0 \
  WOLVRIX_GRHSIM_WAVEFORM=0 \
  XS_WAVEFORM=0 \
  XS_COMMIT_TRACE=0 \
  XS_PROGRESS_EVERY_CYCLES=0 \
  RUN_ID=opt_20260509_1912
```

产物核查：

| path | timestamp | size |
| --- | --- | ---: |
| `build/xs/grhsim/emu` | `2026-05-09 19:18:55 +0800` | symlink |
| `build/xs/grhsim/grhsim-compile/emu` | `2026-05-09 19:18:55 +0800` | `144,346,856` |

运行口径：

- workload: `testcase/xiangshan/ready-to-run/coremark-2-iteration.bin`
- reference: `testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`
- emulator args: `-b 0 -e 0 -C 50000`
- env: `env -u EMU_RUNTIME_PROFILE EMU_PROGRESS_EVERY_CYCLES=0`
- waveform / commit trace / runtime profile: off

功能进度保持一致：

| metric | value |
| --- | ---: |
| `instrCnt` | `73,087` |
| `cycleCnt` | `49,996` |
| guest IPC | `1.461857` |
| final PC | `0x800010ce` |

## 速度复测

裸跑：

| run | host time |
| --- | ---: |
| `run_xs_wolf_grhsim_emu` | `414,257 ms` |

perf 各轮运行时间：

| run | host time from emu | perf elapsed |
| --- | ---: | ---: |
| basic stat | `414,304 ms` | `414.315s` |
| L1/TLB stat | 未单独列出 stdout 差异 | `416.223s` |
| cycles record | `417,421 ms` | - |
| branch-misses record | `414,984 ms` | - |

5 次同口径运行均值约 `415.438s`，范围 `414.257s - 417.421s`。相对 `NO0081` 旧 `grhsim` `412.646s`，basic stat 轮慢 `0.40%`，可以视为噪声级别。

## Perf Stat 基础事件

命令：

```bash
env -u EMU_RUNTIME_PROFILE EMU_PROGRESS_EVERY_CYCLES=0 \
  perf stat \
  -o build/logs/xs_perf/grhsim_opt_20260509_1918_basic.perf \
  -e cycles,instructions,branches,branch-misses,cache-references,cache-misses,duration_time,user_time,system_time \
  -- build/xs/grhsim/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 50000
```

| metric | old grhsim (`NO0081`) | new grhsim | change |
| --- | ---: | ---: | ---: |
| elapsed time | `412.656s` | `414.315s` | `+0.40%` |
| host cycles | `2,367,819,835,745` | `2,377,730,276,539` | `+0.42%` |
| host instructions | `293,224,359,350` | `254,317,990,363` | `-13.27%` |
| host IPC | `0.124` | `0.107` | `-13.31%` |
| branches | `50,961,221,682` | `45,102,933,735` | `-11.50%` |
| branch misses | `23,242,526,001` | `23,219,880,268` | `-0.10%` |
| branch miss rate | `45.61%` | `51.48%` | `+5.87pp` |
| cache references | `116,632,267,565` | `115,331,074,887` | `-1.12%` |
| cache misses | `52,640,359,658` | `53,072,891,887` | `+0.82%` |
| cache miss rate | `45.13%` | `46.02%` | `+0.89pp` |

相对 `NO0081` 的 `gsim` 基线，新 `grhsim` 仍然是：

| metric | new grhsim / old gsim |
| --- | ---: |
| elapsed time | `13.59x` |
| host cycles | `13.72x` |
| host instructions | `3.18x` |
| branches | `10.00x` |
| branch misses | `12.50x` |
| cache references | `5.08x` |
| cache misses | `4.33x` |

## Perf Stat L1/TLB

命令：

```bash
env -u EMU_RUNTIME_PROFILE EMU_PROGRESS_EVERY_CYCLES=0 \
  perf stat \
  -o build/logs/xs_perf/grhsim_opt_20260509_1918_l1tlb.perf \
  -e L1-dcache-loads,L1-dcache-load-misses,L1-icache-load-misses,dTLB-loads,dTLB-load-misses,iTLB-loads,iTLB-load-misses \
  -- build/xs/grhsim/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 50000
```

本组 perf 显示 multiplex coverage 约 `85.71%`。

| metric | old grhsim (`NO0081`) | new grhsim | change |
| --- | ---: | ---: | ---: |
| L1D loads | `260,391,544,746` | `253,585,871,128` | `-2.61%` |
| L1D load misses | `10,568,930,111` | `10,495,577,947` | `-0.69%` |
| L1D miss rate | `4.06%` | `4.14%` | `+0.08pp` |
| L1I load misses | `22,275,296,433` | `22,770,005,992` | `+2.22%` |
| dTLB loads | `1,936,376,406` | `1,944,336,307` | `+0.41%` |
| dTLB load misses | `1,252,643` | `1,334,667` | `+6.55%` |
| iTLB loads | `4,118,243,735` | `4,066,496,736` | `-1.26%` |
| iTLB load misses | `1,663,717,689` | `1,671,232,136` | `+0.45%` |

data-side loads 有小幅下降，但 L1D misses 几乎没动；instruction-side miss 和 TLB miss 也没有改善。这与 wall time 不变一致。

## Perf Record Cycles

命令：

```bash
env -u EMU_RUNTIME_PROFILE EMU_PROGRESS_EVERY_CYCLES=0 \
  perf record -F 99 -e cycles \
  -o build/logs/xs_perf/grhsim_opt_20260509_1918_cycles.data -- \
  build/xs/grhsim/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 50000
```

样本规模：

- cycles samples: `41K`
- lost samples: `0`

top symbols：

| overhead | symbol |
| ---: | --- |
| `1.12%` | `GrhSIM_SimTop::eval_compute_batch_11()` |
| `1.11%` | `GrhSIM_SimTop::eval_compute_batch_860()` |
| `0.97%` | `GrhSIM_SimTop::eval_compute_batch_861()` |
| `0.95%` | `GrhSIM_SimTop::eval_compute_batch_859()` |
| `0.49%` | `GrhSIM_SimTop::eval_compute_batch_819()` |
| `0.44%` | `GrhSIM_SimTop::eval_compute_batch_822()` |
| `0.42%` | `GrhSIM_SimTop::eval()` |
| `0.41%` | `GrhSIM_SimTop::eval_compute_batch_821()` |
| `0.40%` | `GrhSIM_SimTop::eval_compute_batch_826()` |
| `0.39%` | `GrhSIM_SimTop::eval_compute_batch_161()` |
| `0.38%` | `grhsim_assign_words<16ul>(...)` |

和 `NO0081` 的 cycles top 相比，`batch_11/859/860/861` 仍在最前面；原来 retired-branch top 中的 `grhsim_replicate_words<2,1>()`、`grhsim_add_words<2>()`、`grhsim_concat_words<2,1,1>()`、`grhsim_concat_words<2,1,2>()` 没有进入 cycles top 前列。

## Perf Record Branch Misses

命令：

```bash
env -u EMU_RUNTIME_PROFILE EMU_PROGRESS_EVERY_CYCLES=0 \
  perf record -e branch-misses -c 500000 \
  -o build/logs/xs_perf/grhsim_opt_20260509_1918_branch_misses.data -- \
  build/xs/grhsim/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 50000
```

样本规模：

- branch-misses samples: `46,440`
- event count approx: `23,220,000,000`
- lost samples: `0`

top symbols：

| overhead | symbol |
| ---: | --- |
| `1.80%` | `GrhSIM_SimTop::eval_compute_batch_860()` |
| `1.76%` | `GrhSIM_SimTop::eval_compute_batch_859()` |
| `1.75%` | `GrhSIM_SimTop::eval_compute_batch_861()` |
| `0.88%` | `GrhSIM_SimTop::eval_compute_batch_819()` |
| `0.85%` | `GrhSIM_SimTop::eval_compute_batch_821()` |
| `0.85%` | `GrhSIM_SimTop::eval_compute_batch_822()` |
| `0.83%` | `GrhSIM_SimTop::eval_compute_batch_820()` |
| `0.80%` | `GrhSIM_SimTop::eval_compute_batch_823()` |
| `0.79%` | `GrhSIM_SimTop::eval_compute_batch_826()` |
| `0.67%` | `GrhSIM_SimTop::eval_compute_batch_202()` |
| `0.47%` | `GrhSIM_SimTop::eval_compute_batch_824()` |
| `0.44%` | `GrhSIM_SimTop::eval()` |

这和 `NO0081` 的 branch-misses top 保持同一结构：miss 不在 helper，而在大 compute batch。helper fast path 降低了 retired branch 总量，但没有改变 batch 内难预测分支的数量级。

## 解释

这次优化的效果可以拆开看：

1. `2-word` helper fast path 是有效的

`NO0081` 的 retired-branches top4 分别是：

- `grhsim_replicate_words<2,1>()`
- `grhsim_add_words<2>()`
- `grhsim_concat_words<2,1,1>()`
- `grhsim_concat_words<2,1,2>()`

新版本把 `2-word` add / concat / replicate / assign 的常见路径转成更直线化 helper 后，retired instructions 和 retired branches 分别下降 `13.27%` / `11.50%`。这说明优化确实打中了 retired branch 数量来源。

2. wall time 没动是因为 branch misses 没动

新版本 branch miss 绝对数仍是 `23.220B`，相对旧版本只少 `0.10%`。因为 retired branches 降了而 misses 不降，branch miss rate 被动升到 `51.48%`。

结合 `perf record -e branch-misses`，剩余 miss 仍集中在：

- `eval_compute_batch_859/860/861`
- `eval_compute_batch_819-826`
- `eval_compute_batch_202`

这些 batch 内的 `old/new changed-check -> conditional branch -> mark active -> writeback` 仍是更核心的瓶颈。

3. cache/TLB 没有明显改善

L1D loads 只降 `2.61%`，L1D misses 只降 `0.69%`，L1I misses 反而上升 `2.22%`。因此本轮 helper 优化减少了执行指令和 retired branch，但没有减少足够多的 cache/TLB 压力。

## 下一步

优先方向应从 generic helper 转向 batch 内控制流：

- 对 `eval_compute_batch_860/859/861` 做源码窗口和反汇编窗口分析，统计 `cmp/jcc/orb/store` 密度。
- 尝试把常见 changed-check 改成 branchless active propagation，例如计算 changed mask 后无条件 OR active word，或按 word 聚合 changed bit 再分发。
- 检查 active propagation 是否可以做 per-word batching，减少每个 value update 后立即 `if changed` 的分支链。
- 继续保留本轮 helper fast path，因为它降低了 retired instructions / branches；但下一轮速度收益更可能来自降低 branch misses，而不是继续压 retired branch 数。

## 产物

- `build/logs/xs/xs_wolf_grhsim_opt_20260509_1912_speed.log`
- `build/logs/xs_perf/grhsim_opt_20260509_1918_basic.perf`
- `build/logs/xs_perf/grhsim_opt_20260509_1918_basic.stdout`
- `build/logs/xs_perf/grhsim_opt_20260509_1918_l1tlb.perf`
- `build/logs/xs_perf/grhsim_opt_20260509_1918_l1tlb.stdout`
- `build/logs/xs_perf/grhsim_opt_20260509_1918_cycles.data`
- `build/logs/xs_perf/grhsim_opt_20260509_1918_cycles.report`
- `build/logs/xs_perf/grhsim_opt_20260509_1918_cycles.stdout`
- `build/logs/xs_perf/grhsim_opt_20260509_1918_branch_misses.data`
- `build/logs/xs_perf/grhsim_opt_20260509_1918_branch_misses.report`
- `build/logs/xs_perf/grhsim_opt_20260509_1918_branch_misses.stdout`

