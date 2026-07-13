# NO0301 Ordered memory-write affine-loop 50k gate

日期：2026-07-12

## 1. 口径与负载检查

承接 [NO0300](./NO0300_ordered_memory_write_affine_loop_fresh_gate_20260712.md)，直接隔离 C++ emitter 表达的变化：

```text
old = build/xs_grhsim_no0296_ordered_rank_fix_fresh_20260711/grhsim/grhsim-compile/emu
new = build/xs_grhsim_no0300_ordered_affine_fresh_20260712/grhsim/grhsim-compile/emu
```

两者来自相同 checkpoint，graph、supernode、DAG、boundary 和 activation 统计完全一致；区别仅为 fp/int/vec RAT 的 1,542 个展开 guard 在 new 中改成 4 个仿射循环。

固定 CPU 138，SMT sibling 为 CPU 330，顺序执行 old / new / old。每次均使用 CoreMark 两迭代镜像、NEMU difftest、`-C 50000`，以 `perf stat` 采集 user-space cycles、instructions、branches 和 branch misses。

运行前整机 load average 为 `4.83/4.81/5.49`，机器有 384 个逻辑 CPU；五秒总预检中 CPU 138/330 平均空闲率为 `99.8%/99.2%`。三个样本各自四秒预检的目标核空闲率分别为 `98.0%/99.75%/100.0%`，sibling 空闲率为 `99.0%/99.0%/98.0%`。

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

| Metric | NO0296 old 1 | NO0300 new | NO0296 old 2 | New vs old mean |
| --- | ---: | ---: | ---: | ---: |
| Host time (ms) | 84,809 | 84,297 | 85,119 | -0.785% |
| cycles | 310,510,395,601 | 308,588,918,402 | 311,627,426,114 | -0.797% |
| instructions | 172,597,037,733 | 172,879,438,667 | 172,597,030,169 | +0.164% |
| branches | 14,980,748,902 | 15,057,832,914 | 14,980,744,633 | +0.515% |
| branch misses | 5,466,942,056 | 5,389,216,348 | 5,467,024,672 | -1.422% |
| IPC | 0.55485 | 0.56023 | 0.55386 | +0.969% against aggregate old IPC |
| branch miss rate | 36.493% | 35.790% | 36.494% | -1.927% relative |

两次 old 的 Host time spread 为 `0.366%`，cycles spread 为 `0.360%`；instructions、branches 和 branch misses 则高度稳定。new 的 Host time/cycles 降幅约为 baseline spread 的 2.2 倍，并同时出现 IPC 和 miss rate 改善，因此 affine loop 的小幅收益可信。

循环并非免费：instructions 增加 `0.164%`、branches 增加 `0.515%`。收益来自 branch misses 降低和 IPC 恢复，方向与 NO0298 的 frontend/control-flow 诊断一致，但幅度有限。

## 4. Ordered-write 回退恢复量

NO0297 中 NO0296 相对 NO0286 的 cycles 回退为 `+4.240%`。本轮 NO0296 baseline 均值相对 NO0297 的 NO0296 样本只漂移约 `+0.11%`，两轮机器条件接近。用 NO0297 的相邻 NO0286 双 baseline 估算，NO0300 相对 NO0286 仍为：

| Metric | NO0300 vs NO0286 prior mean |
| --- | ---: |
| Host time | +3.499% |
| cycles | +3.527% |

按 cycles 的原始 excess gap 计算，affine loop 约收回 NO0296 ordered-write 回退的 `16.81%`。该数字跨两次相邻实验推导，下一步仍需用 fresh NO0286 / NO0300 / NO0286 配对确认；不能把 `-0.797%` 局部收益误报成 ordered-write 已恢复到基线。

## 5. 产物与结论

```text
build/logs/xs_perf/no0301/old1_emu.log
build/logs/xs_perf/no0301/old1_perf.csv
build/logs/xs_perf/no0301/new_emu.log
build/logs/xs_perf/no0301/new_perf.csv
build/logs/xs_perf/no0301/old2_emu.log
build/logs/xs_perf/no0301/old2_perf.csv
```

affine loop 通过功能与 runtime gate，作为对 NO0296 的确定性小幅修复保留。但它只解释并修复了 ordered-write 回退的一部分；下一步用 fresh NO0286 双 baseline 确认整体差距，然后重新 profile 剩余热点，而不是继续假设三个 RAT guard 已经是全部原因。
