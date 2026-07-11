# NO0298 Ordered memory-write frontend regression diagnosis

日期：2026-07-12

## 1. 目的与口径

承接 [NO0297](./NO0297_ordered_memory_write_simtop_50k_gate_20260711.md)，本轮解释 ordered memory-write 在减少 host instructions 的同时，为什么仍使 SimTop 50k runtime 回退约 `4.2%`。比较对象保持不变：

```text
old = build/xs_grhsim_no0286_commit_change_unlikely_20260711/grhsim/grhsim-compile/emu
new = build/xs_grhsim_no0296_ordered_rank_fix_fresh_20260711/grhsim/grhsim-compile/emu
```

cycles profile 与原生计数器均固定 CPU 138，SMT sibling 为 CPU 330，负载为 CoreMark 两迭代镜像、NEMU difftest、`-C 50000`。运行前检查目标物理核空闲，原生计数器再次采用 old / new / old 顺序，所有事件均为 `100%` 调度。

三次原生计数器运行的功能端点完全一致：

```text
Guest cycle spent: 50001
cycleCnt = 49996
instrCnt = 73580
terminal PC = 0x80001312
```

## 2. Cycles profile 分解

profile 使用 `cycles:u`、`25,000,000` period 与 DWARF call graph。old/new 的用户态 symbol samples 分别为 `11,878/12,412`，没有 lost samples。

| Phase | old samples | new samples | Delta | Share of total increase |
| --- | ---: | ---: | ---: | ---: |
| compute | 7,983 | 8,274 | +291 | 54.49% |
| commit | 3,695 | 3,923 | +228 | 42.70% |
| eval | 18 | 21 | +3 | 0.56% |
| other | 182 | 194 | +12 | 2.25% |
| total | 11,878 | 12,412 | +534 | 100.00% |

回退同时出现在 compute 与 commit，不能只按 phase aggregate 将问题归因到某一个 batch。继续把 ordered RAT writes 映射回 generated source 后，得到更直接的局部证据：

| Model | Ordered RAT write location | Symbol samples | Symbol text size |
| --- | --- | ---: | ---: |
| old | `eval_commit_batch_116()`，三组 scalar row writes | 41 | `0x28233` |
| new | `eval_commit_batch_90()`，fpRat + intRat 共 1,022 writes | 119 | `0x3f210` |
| new | `eval_commit_batch_104()`，vecRat 共 520 writes | 129 | `0x41620` |

两个新版目标 batch 合计 `248` samples，相对旧版目标位置增加 `207` samples，按固定 period 折合约 `5.175B` cycles，占整个 profile 事件增量约 `38.8%`。annotate 中 batch90/batch104 的 sampled instructions 分别有 `94.08%/92.03%` 落在 `je`；旧版 batch116 对应比例为 `82.96%`。这说明主要直接成本是每周期扫描大量未命中的写使能 guard，而不是执行实际 memory store。

## 3. 与 GSim 生成代码的差异

同 FIR 的 GSim `SimTop279.cpp` 先从当前 scalar rows 初始化紧凑的 `difftest_table_next[]`，再按优先级执行 guarded indexed assignments。也就是说，GSim 保留了数组与顺序写语义，writer 只更新动态地址对应的 next row。

当前 GrhSIM 虽然已经消除了 pairwise address-conflict 网络，但 C++ emitter 仍把每个 memory write 展开为独立 direct-commit 分支。三组 RAT 因此在每个相关周期顺序穿过 `511 + 511 + 520 = 1,542` 个稀疏 outer guards；每个命中项再完成 state compare、write 和 reader activation。ordered IR 解决了图规模问题，但 generated C++ 的控制流形态仍没有对齐 GSim。

## 4. 原生前后端计数器

两次 old 的 Host time spread 为 `0.3725%`，cycles spread 为 `0.4468%`，明显小于 new 的约 `4.2%` 回退。下表 old 使用两次均值：

| Metric | old mean | new | New vs old mean |
| --- | ---: | ---: | ---: |
| Host time (ms) | 81,348.5 | 84,754 | +4.1863% |
| cycles | 297,736,003,961 | 310,266,520,210 | +4.2086% |
| I-cache accesses | 113,448,122,293 | 110,807,150,211 | -2.3279% |
| I-cache misses | 38,223,715,864 | 37,044,362,337 | -3.0854% |
| frontend no-op slots | 1,356,196,478,918 | 1,452,709,574,751 | +7.1165% |
| backend stall slots | 99,812,914,634 | 95,725,190,569 | -4.0954% |

按 host cycles 归一化后：

| Metric / cycle | old mean | new | Delta |
| --- | ---: | ---: | ---: |
| I-cache accesses | 0.381040 | 0.357135 | -6.2734% |
| I-cache misses | 0.128382 | 0.119395 | -7.0000% |
| frontend no-op slots | 4.555031 | 4.682134 | +2.7904% |
| backend stall slots | 0.335238 | 0.308526 | -7.9681% |

I-cache miss 与 backend stall 都没有恶化，反而明显下降；frontend no-op slots/cycle 是唯一恶化的等待指标。结合 NO0297 中 branches/branch misses 均略降，以及本轮 annotate 中高度集中的 `je`，当前 root cause 是长串稀疏 guard 改变了前端取指、解码和控制流供给效率，而不是 branch predictor、cache miss 或 store backend 压力。

## 5. 下一步约束

下一步在 GrhSIM C++ emitter 中增加严格受限的 ordered scalar-memory table loop：

1. 只匹配同一 memory、同一 priority group、连续完整 rank、全掩码和已物化 scalar cond/address/data 的 ordered writes；其他情况继续走现有逐 op 路径。
2. descriptor table 按 low-to-high priority 保存 slot indices，运行时用一个紧凑循环扫描 guards。
3. 命中 writer 时立即更新 state，保持同地址后写覆盖前写的可观察语义；同时累计 changed rows，再复用现有 row-aware reader activation。
4. 先以 generated-model collision harness 和定向 CTest 证明语义，再做 fresh SimTop source/text、10k/50k 功能及固定 CPU runtime gate。

该方案直接针对已观察到的前端问题；是否优于现状仍必须由 fresh runtime gate 决定。

## 6. 产物

```text
build/logs/xs_perf/no0298/new_no0296_cpu138_50k_cycles.data
build/logs/xs_perf/no0298/new_no0296_cpu138_50k_cycles_exact_symbols_samples.report
build/logs/xs_perf/no0298/new_no0296_commit90_cycles_annotate.report
build/logs/xs_perf/no0298/new_no0296_commit104_cycles_annotate.report
build/logs/xs_perf/no0298/old_no0286_commit116_cycles_annotate.report
build/logs/xs_perf/no0298/native_old1_emu.log
build/logs/xs_perf/no0298/native_old1_perf.csv
build/logs/xs_perf/no0298/native_new_emu.log
build/logs/xs_perf/no0298/native_new_perf.csv
build/logs/xs_perf/no0298/native_old2_emu.log
build/logs/xs_perf/no0298/native_old2_perf.csv
```
