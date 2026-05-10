# NO0084 Active Word Accumulator Negative Result

> 2026-05-09 记录在 [`NO0083`](./NO0083_branchless_changed_activation_experiment_20260509.md) 之后尝试的 batch/word-local active word accumulator。实验目标是减少同一 batch 内对 `supernode_active_curr_[]` 的重复 load/or/store，但实测显示代码规模、分支和 cache 压力明显增加，因此该方向不保留。

## 实验目标

`NO0082` / `NO0083` 显示当前 `grhsim` 的主要 runtime 压力来自 compute batch 内 changed-check 与 activation propagation。此次实验尝试：

- 在每个 active word body 内为跨 word 激活生成局部 `activeWordAccum_<word>`；
- changed 分支内先 OR 到局部 accumulator；
- word body 结束时再把 accumulator flush 回 `supernode_active_curr_[word]`；
- 保留同 word 后续 bit 的 `activeWordFlags` local propagation。

预期收益是降低全局 active bitset 写入密度，尤其减少多次激活同一目标 active word 时的 store traffic。

## 构建与验证

单测：

```bash
cmake --build wolvrix/build --target emit-grhsim-cpp
ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'
```

XS `grhsim` emu 重建：

```bash
make --no-print-directory xs_wolf_grhsim_emu \
  XS_SIM_MAX_CYCLE=50000 \
  WOLVRIX_GRHSIM_PERF=0 \
  WOLVRIX_GRHSIM_WAVEFORM=0 \
  XS_WAVEFORM=0 \
  XS_COMMIT_TRACE=0 \
  XS_PROGRESS_EVERY_CYCLES=0 \
  RUN_ID=active_accum_20260509
```

产物：

| path | timestamp | size |
| --- | --- | ---: |
| `build/xs/grhsim/emu` | `2026-05-09 21:24:33 +0800` | symlink |
| `build/xs/grhsim/grhsim-compile/emu` | compiled `May 9 2026, 21:20:11` | `151,973,136` |

## 静态代码规模

| metric | value |
| --- | ---: |
| schedule `.cpp` files | `1,471` |
| total schedule lines | `24,613,282` |
| `activeWordAccum_` occurrences | `3,513,684` |
| `build/xs/grhsim/grhsim_emit` size | `2.2G` |
| emu size | `151,973,136 bytes` |

这是本实验最直接的负面信号：accumulator 被大规模展开，远超过它想节省的全局 OR 写入。

## CoreMark 50k Speed

裸跑命令：

```bash
/usr/bin/time -v make --no-print-directory run_xs_wolf_grhsim_emu \
  XS_SIM_MAX_CYCLE=50000 \
  WOLVRIX_GRHSIM_PERF=0 \
  WOLVRIX_GRHSIM_WAVEFORM=0 \
  XS_WAVEFORM=0 \
  XS_COMMIT_TRACE=0 \
  XS_PROGRESS_EVERY_CYCLES=0 \
  RUN_ID=active_accum_20260509
```

结果：

| metric | value |
| --- | ---: |
| host time from emu | `484,613 ms` |
| wall time | `8:04.63` |
| guest instrCnt | `73,087` |
| guest cycleCnt | `49,996` |
| final PC | `0x800010ce` |

guest 进度与 `NO0082` 对齐，但 host time 从 `414,257 ms` 退化到 `484,613 ms`，约 `+17.0%`。

## Perf Stat

命令：

```bash
env -u EMU_RUNTIME_PROFILE EMU_PROGRESS_EVERY_CYCLES=0 \
  perf stat \
  -o build/logs/xs_perf/grhsim_active_accum_20260509.perf \
  -e cycles,instructions,branches,branch-misses,cache-references,cache-misses,duration_time,user_time,system_time \
  -- build/xs/grhsim/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 50000
```

对比 `NO0082` helper-fastpath baseline：

| metric | NO0082 baseline | active accumulator | change |
| --- | ---: | ---: | ---: |
| elapsed time | `414.315s` | `485.755s` | `+17.25%` |
| host cycles | `2,377,730,276,539` | `2,787,933,836,904` | `+17.25%` |
| host instructions | `254,317,990,363` | `290,219,595,641` | `+14.12%` |
| host IPC | `0.107` | `0.104` | worse |
| branches | `45,102,933,735` | `53,898,453,881` | `+19.50%` |
| branch misses | `23,219,880,268` | `28,550,432,856` | `+22.96%` |
| branch miss rate | `51.48%` | `52.97%` | `+1.49pp` |
| cache references | `115,331,074,887` | `139,269,980,456` | `+20.75%` |
| cache misses | `53,072,891,887` | `58,558,413,033` | `+10.34%` |
| cache miss rate | `46.02%` | `42.05%` | lower rate, higher count |

perf 轮 stdout 中 emu 自报 host time 为 `485,744 ms`，和 perf elapsed 一致。

## 结论

该 accumulator 方向不应保留。它没有降低 branch pressure，反而因为每个 word body 展开大量局部 accumulator 声明、更新和 flush 判断，导致：

- retired instructions 增加 `14.12%`；
- retired branches 增加 `19.50%`；
- branch misses 增加 `22.96%`；
- cache references 增加 `20.75%`；
- 最终 elapsed time 退化 `17.25%`。

本轮有一个可单独保留的发现：部分 op emit 路径没有传递 `ActivationEmitContext`，导致同 word 后续激活绕过 `activeWordFlags` local propagation。这是低风险修正，和 accumulator 本身无关，应在回退 accumulator 后保留并单独复测。

## 后续方向

不要继续做无界跨 word accumulator。下一步应更收窄：

1. 保留并评估 `ActivationEmitContext` 传递修正本身，确认同 word local propagation 是否有稳定收益。
2. 如果继续做延迟 OR，只允许静态阈值很小的局部合并，例如同一 active word 在同一短代码段内出现多次时才合并。
3. 优先用代码规模 guard 约束实验，避免再次把 `sched` 源码和 host text footprint 放大。
