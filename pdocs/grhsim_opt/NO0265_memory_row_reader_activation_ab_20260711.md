# NO0265 Memory row-reader activation A/B

日期：2026-07-11

## 问题

[NO0264](./NO0264_phr_true_only_shared_read_true_merge_p1_20260711.md) 把 PHR 恢复为 memory 后，
普通 memory write 仍会激活该 memory 的全部 reader supernode。PHR 的 532 行 constant-address
read 被 source clone 到 67 个 active ID；任何一行变化都全量激活 67 个 ID，会抵消 true merge
带来的部分收益。

## 实现

GrhSIM emitter 为满足以下条件的 memory 建立 row -> packed active-mask table：

1. 至少有 32 个 constant-address row，且覆盖至少一半 memory rows；
2. 从 schedule 扫描到的 `kMemoryReadPort` active-ID 集与 `stateReadSupernodes` 完全相等；
3. dynamic-address reader 单独保留为每次 write 都激活的保守集合；
4. constant 与 dynamic read 落在同一 supernode 时按 dynamic reader 处理；
5. memory fill 仍激活全部 readers，只有已确认 changed 的单行 write 使用 row table。

helper 同时保留当前 active word 中 later-bit 的立即调度语义。任何覆盖不完整或规模不达阈值的
memory 自动回退到原来的 full-reader activation。

## Synthetic gate

新增 64-row memory fixture，每行放两个独立 constant reader，并保留一个 dynamic reader。测试
明确要求生成：

```text
std::array<std::size_t, 65> kRowOffsets
std::array<grhsim_active_mask_entry, 128> kRowReaders
```

随后编译并执行 harness，验证 row 0/33 的两个 constant outputs 与 dynamic output 都在写后更新。
完整 `emit-grhsim-cpp` 回归通过，见 NO0264 的最终 CTest 日志。

## SimTop 结构

当前 SimTop 有 8 个 memory 满足 specialization 条件。PHR 主 storage 使用
`activate_memory_row_readers_3()`：

| metric | value |
| --- | ---: |
| rows / offset entries | `532 / 533` |
| packed mask entries | `1011` |
| represented reader bits total | `1117` |
| reader bits per row min / mean / max | `1 / 2.100 / 7` |
| generic full-reader active IDs | `67` |
| PHR write call sites | `41` |

因此静态上每次 PHR row change 从固定激活 67 个 reader ID 收窄到平均 2.1 个，约 `31.9x`。
这不是 31.9x 的整机收益，因为不少 reader supernode 在同一轮已被其他 value fanout 激活。

full-reader 与 row-aware 两个 P1 模型的 activity-schedule JSON SHA256 完全相同：

```text
3b2b756238a82fafd862df09e75e454f3f6586b1df5da2d38b641d8f313e6400
```

只有 emitter activation code 不同；executable text 从 `106802121` 增至 `106839279` bytes，
增加 `37158` bytes。

## 50k CPU8 perf-stat A/B

两边都绑定 CPU 8，运行相同 50k workload；四个 perf events 均为 `100%` scheduled。两边均得到
`Guest cycles=50001, instrCnt=73580, cycleCnt=49996`，difftest 无 mismatch。

| counter | full-reader | row-aware | delta |
| --- | ---: | ---: | ---: |
| cycles | `371565232945` | `370995860337` | `-0.1532%` |
| instructions | `228538915713` | `228124774135` | `-0.1812%` |
| branches | `21778941128` | `21610529133` | `-0.7733%` |
| branch misses | `7778159523` | `7762682592` | `-0.1990%` |
| perf time-enabled | `102.321s` | `102.143s` | `-0.1739%` |

日志：

```text
build/logs/xs/no0264_phr_full_reader_baseline_50k_cpu8_perf_stat.csv
build/logs/xs/no0264_phr_row_activation_50k_cpu8_perf_stat.csv
build/logs/xs/xs_wolf_grhsim_no0264_phr_full_reader_baseline_50k_cpu8_20260711.log
build/logs/xs/xs_wolf_grhsim_no0264_phr_multi_reader_row_activation_50k_cpu8_20260711.log
```

## 结论

row-aware activation 的方向与硬件计数都为正，但整机收益只有约 `0.18%`，远小于静态 reader
缩减倍数。当前实现保留，因为语义门槛严格、功能已回归且动态工作量稳定下降；它不是 P1 的
主要性能来源。下一轮应 profile true merge 后新增的 write/guard branches，而不是继续围绕
row table 做微调。
