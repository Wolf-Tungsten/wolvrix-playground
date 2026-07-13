# NO0302 Ordered memory-write affine overall 50k gate

日期：2026-07-12

## 1. 口径与负载检查

承接 [NO0301](./NO0301_ordered_memory_write_affine_loop_50k_gate_20260712.md)，用进入 ordered-write 路线前的 NO0286 重新做相邻双 baseline：

```text
old = build/xs_grhsim_no0286_commit_change_unlikely_20260711/grhsim/grhsim-compile/emu
new = build/xs_grhsim_no0300_ordered_affine_fresh_20260712/grhsim/grhsim-compile/emu
```

固定 CPU 138，SMT sibling 为 CPU 330，顺序执行 old / new / old。每次均使用 CoreMark 两迭代镜像、NEMU difftest、`-C 50000`，以 `perf stat` 采集 user-space cycles、instructions、branches 和 branch misses。

三次预检时整机 load average 在 `2.61~4.35`，机器有 384 个逻辑 CPU。CPU 138 的四秒平均空闲率分别为 `95.49%/99.00%/100.00%`，CPU 330 分别为 `97.51%/99.25%/97.25%`；两次 old 的 Host time/cycles spread 只有 `0.102%/0.086%`，局部环境足够稳定。

## 2. 功能端点

三次均得到完全一致的功能端点：

```text
Guest cycle spent: 50001
cycleCnt = 49996
instrCnt = 73580
terminal PC = 0x80001312
```

没有 assertion、abort 或 difftest mismatch。四个 perf 事件在三次运行中均为 `100%` 调度。

## 3. 结果

| Metric | NO0286 old 1 | NO0300 new | NO0286 old 2 | New vs old mean |
| --- | ---: | ---: | ---: | ---: |
| Host time (ms) | 81,230 | 84,405 | 81,313 | +3.856% |
| cycles | 297,422,782,679 | 309,005,122,520 | 297,678,058,907 | +3.850% |
| instructions | 188,838,676,209 | 172,879,300,971 | 188,838,478,375 | -8.451% |
| branches | 15,048,506,022 | 15,057,855,322 | 15,048,479,858 | +0.062% |
| branch misses | 5,504,731,365 | 5,392,050,096 | 5,503,022,578 | -2.032% |
| IPC | 0.63464 | 0.55947 | 0.63437 | -11.845% against aggregate old IPC |
| branch miss rate | 36.574% | 35.809% | 36.568% | -2.093% relative |

NO0300 仍执行少 `8.45%` 的 instructions，branch misses 也少 `2.03%`，但 IPC 从约 `0.635` 降到 `0.559`，使 Host time/cycles 反而增加约 `3.85%`。这与 NO0297 的总体结论一致，证明剩余回退不是机器负载假象。

NO0301 已证明 affine loop 相对 NO0296 可稳定降低约 `0.80%` cycles；本轮则证明该局部修复不足以让 ordered-write 整体通过 NO0286 baseline 保留门禁。两轮的比较口径不同，不能用 NO0301 的单项收益替代本轮整体结论。

## 4. 产物与下一步

```text
build/logs/xs_perf/no0302/old1_emu.log
build/logs/xs_perf/no0302/old1_perf.csv
build/logs/xs_perf/no0302/new_emu.log
build/logs/xs_perf/no0302/new_perf.csv
build/logs/xs_perf/no0302/old2_emu.log
build/logs/xs_perf/no0302/old2_perf.csv
```

affine emitter 优化本身保留，但当前 ordered-write 方案仍未通过整体 runtime gate。下一步对 NO0286 与 NO0300 采集相同 fixed-period `cycles:u` profile，重新定位 affine 后剩余的 sample 增量，区分三组 RAT commit path 的残余成本与 graph/code-layout 造成的其他热点。
