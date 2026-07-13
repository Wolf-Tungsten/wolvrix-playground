# NO0297 Ordered memory-write SimTop 50k gate

日期：2026-07-11

## 1. 口径与负载检查

承接 [NO0296](./NO0296_ordered_memory_write_rank_fix_fresh_gate_20260711.md)，比较：

```text
old = build/xs_grhsim_no0286_commit_change_unlikely_20260711/grhsim/grhsim-compile/emu
new = build/xs_grhsim_no0296_ordered_rank_fix_fresh_20260711/grhsim/grhsim-compile/emu
```

固定 CPU 138，SMT sibling 为 CPU 330，顺序执行 old / new / old。每次均使用 CoreMark 两迭代镜像、NEMU difftest、`-C 50000`，并以 `perf stat` 采集 user-space counters。

运行前整机 load average 为 `10.90/8.67/7.25`，机器有 384 个逻辑 CPU；四秒预检中 CPU 138/330 平均空闲率为 `98.25%/98.75%`，未发现固定占用这两个逻辑核的用户进程。每个样本间再次检查，空闲率保持 `99%~100%`。因此整机存在其他任务，但目标物理核局部干净；相邻双 baseline 用于直接约束剩余漂移。

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

| Metric | NO0286 old 1 | NO0296 new | NO0286 old 2 | New vs old mean |
| --- | ---: | ---: | ---: | ---: |
| Host time (ms) | 81,492 | 84,874 | 81,403 | +4.207% |
| cycles | 298,115,248,219 | 310,713,254,780 | 298,037,335,452 | +4.240% |
| instructions | 188,838,062,855 | 172,596,601,508 | 188,838,080,957 | -8.601% |
| branches | 15,048,384,909 | 14,980,641,991 | 15,048,402,306 | -0.450% |
| branch misses | 5,501,502,208 | 5,469,339,196 | 5,506,350,110 | -0.628% |
| IPC | 0.63344 | 0.55549 | 0.63360 | -12.31% |

两次 old 的 Host time spread 为 `0.109%`，cycles spread 为 `0.026%`，instructions/branches 几乎完全重合。新版 `+4.24%` cycles 远大于 baseline 漂移，因此是可信回退。

## 4. 解释边界

ordered-write 结构确实省掉了大量工作：instructions 降低 `8.60%`，source/text 也已在 NO0296 中分别缩小 `7.32%/9.04%`。但 IPC 从约 `0.6335` 降至 `0.5555`，抵消并反转了 instruction 收益。branches 与 branch misses 都没有增加，当前证据不支持“分支数量或预测变差”是主因。

因此该实现通过功能门禁，但未通过 SimTop runtime 保留门禁。不能仅凭静态规模或 instruction 数将其视为最终优化；下一步需要比较 frontend/backend stall、cache/TLB counters，并做 cycles profile，定位 ordered memory-write 路径引入的等待来源。

## 5. 产物

```text
build/logs/xs_perf/no0297/old1_emu.log
build/logs/xs_perf/no0297/old1_perf.csv
build/logs/xs_perf/no0297/new_emu.log
build/logs/xs_perf/no0297/new_perf.csv
build/logs/xs_perf/no0297/old2_emu.log
build/logs/xs_perf/no0297/old2_perf.csv
```
