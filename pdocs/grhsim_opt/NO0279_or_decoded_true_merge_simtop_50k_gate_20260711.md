# NO0279 OR-decoded true-merge SimTop 50k gate

日期：2026-07-11

## 1. 目标与口径

对 [NO0278](./NO0278_or_decoded_priority_true_merge_20260711.md) 的 fresh emu 做固定 CPU
old/new/old 50k gate：

- old: 已提交的 NO0274 edge-padded true-merge；
- new: NO0278 OR-decoded priority true-merge；
- workload: CoreMark 2 iterations，NEMU difftest，`-C 50000`；
- events: `cycles:u,instructions:u,branches:u,branch-misses:u`；
- 三次 perf events 均为 `100%` scheduled。

全机 load average 为 `64.52/56.38/57.12`，但存在多组 8-thread Verilator 任务，局部物理核
竞争明显。全 CPU 扫描后选择 CPU138，SMT sibling 为 CPU330。紧邻 old1 的三秒预检 idle
为 `98.99%/99.33%`；各 run 后复检也保持约 `97.67%~100%`。

所有 run 前均执行 `source env.sh`，并用 `taskset -c 138` 固定。

## 2. Functional status

三个 paired run 的功能终点完全一致：

```text
Guest cycles: 50001
instrCnt: 73580
cycleCnt: 49996
terminal PC: 0x80001312
mismatch / ABORT: 0 / 0
```

## 3. CPU138 old/new/old

| run | Host time | host cycles | instructions | branches | branch misses |
| --- | ---: | ---: | ---: | ---: | ---: |
| NO0274 old 1 | `95034ms` | `342331007112` | `190862597156` | `15156552465` | `5510029191` |
| NO0278 new | `84257ms` | `303535719660` | `190436135371` | `15004655417` | `5548806240` |
| NO0274 old 2 | `94903ms` | `341913094626` | `190864109920` | `15156690887` | `5513385768` |

old 两次 Host time spread 为 `0.1379%`，host cycles spread 为 `0.1222%`。以 old 均值为
baseline：

| metric | old mean | new | delta |
| --- | ---: | ---: | ---: |
| Host time | `94968.5ms` | `84257ms` | `-11.2790%` |
| host cycles | `342122050869.0` | `303535719660` | `-11.2785%` |
| instructions | `190863353538.0` | `190436135371` | `-0.2238%` |
| branches | `15156621676.0` | `15004655417` | `-1.0026%` |
| branch misses | `5511707479.5` | `5548806240` | `+0.6731%` |
| branch-miss rate | `36.3650%` | `36.9806%` | `+0.6156pp` |
| IPC | `0.557881` | `0.627393` | `+12.4600%` |
| guest cycles/s | `526.501` | `593.434` | `+12.7129%` |

Host time 与 host cycles 一致下降，且两次 old 稳定包住 new，因此性能收益有效。CPU138 的
绝对时间不能与此前 CPU65/CPU140 横向比较，本结论只使用同核相邻 paired runs。

## 4. 初步归因

动态 instructions 仅下降 `0.22%`，但 cycles 下降 `11.28%`；branch misses 还增加 `0.67%`。
因此本轮收益不能解释为简单的指令数或 branch-miss 数减少，更可能来自以下结构变化共同影响：

- 1024 个 DCache scalar rows 和 18 个 LLPTW scalar rows 被 indexed memory state 替代；
- generated C++ 减少 4.88 MB，emu `.text` 减少约 217 KB；
- compute supernodes 减少 303，compute-commit pairs 减少 1911；
- commit/compute 函数重新布局后，前端 cache、分支位置和依赖链发生变化。

这是基于 counters 与生成结构的推断，不把 `11.28%` 全部归因到 DCache 单项。下一步应对
NO0274/NO0278 做 `cycles:u` post-profile，并在需要时隔离 4 个 DCache group 与 3 个 LLPTW group，
确认收益落在哪些 commit/compute batches。

## 5. 日志

```text
build/logs/xs_perf/no0278/cpu_all_preflight_20260711.log
build/logs/xs_perf/no0278/cpu138_330_preflight_before_old1_20260711.log
build/logs/xs_perf/no0278/cpu138_330_after_old1_20260711.log
build/logs/xs_perf/no0278/cpu138_330_after_new_20260711.log
build/logs/xs_perf/no0278/cpu138_330_after_old2_20260711.log
build/logs/xs_perf/no0278/paired_old_no0274_cpu138_50k_run1.log
build/logs/xs_perf/no0278/paired_old_no0274_cpu138_50k_run1_perf_stat.csv
build/logs/xs_perf/no0278/paired_new_no0278_cpu138_50k.log
build/logs/xs_perf/no0278/paired_new_no0278_cpu138_50k_perf_stat.csv
build/logs/xs_perf/no0278/paired_old_no0274_cpu138_50k_run2.log
build/logs/xs_perf/no0278/paired_old_no0274_cpu138_50k_run2_perf_stat.csv
```

## 6. 结论

NO0278 应保留：fresh 10k/50k difftest 和稳定 old/new/old 性能 gate 均通过，SimTop 50k
host cycles 下降 `11.28%`，吞吐提高 `12.71%`。下一阶段转向 cycles post-profile，直接确认
新旧 batch 的执行代价变化，并继续与 GSim 的数组状态结构对照。
