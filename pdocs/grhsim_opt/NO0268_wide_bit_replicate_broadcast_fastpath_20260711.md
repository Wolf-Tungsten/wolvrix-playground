# NO0268 Wide bit-replicate broadcast fast path

日期：2026-07-11

## 目标

承接 [NO0267](./NO0267_post_p1_same_fir_branch_diagnosis_20260711.md)，消除
`1 bit -> multi-word` replication 的通用 bit-copy 循环。该改动只处理
`operandWidth == 1 && rep == resultWidth` 的完整复制，不改变其他 replication 路径。

## 实现

runtime 新增 `grhsim_replicate_bit_words<DestN, TotalWidth>`：

1. 用 `0 - (value[0] & 1)` 生成全零或全一 word；
2. 用 `std::index_sequence` 参数包在编译期展开全部 destination words；
3. `TotalWidth` 不是 64 的整数倍时，只对最后一个 word 应用 compile-time tail mask；
4. 用 static assertions 约束 `DestN == ceil(TotalWidth / 64)`。

因此 hot path 没有运行时 replication loop，也不依赖跨 translation unit 的常量传播。

## Synthetic gate

`buildTwoWordHelperDesign` 新增独立 1-bit input，并同时生成 65-bit 与 256-bit outputs。执行
harness 覆盖：

- input `1` 时，65-bit 结果为 `{UINT64_MAX, 1}`；
- input `1` 时，256-bit 结果为 4 个 `UINT64_MAX`；
- input `0` 时，两种结果均清零；
- 原 8-bit -> 96-bit replication 和 96-bit register 行为保持不变。

验证均先执行 `source env.sh`：

```text
cmake --build wolvrix/build --target emit-grhsim-cpp -j8
ctest --test-dir wolvrix/build -R '^emit-grhsim-cpp$' --output-on-failure
```

结果 `PASS`，用时 `150.90s`。日志：

```text
build/logs/xs_perf/no0268/wolvrix_build_emit_grhsim_cpp_20260711.log
build/logs/xs_perf/no0268/ctest_emit_grhsim_cpp_20260711.log
```

## Fresh SimTop static gate

fresh emit 复用 NO0264/NO0267 的同一 pre-reg-to-mem checkpoint，调度参数保持
`compute=108, commit=4096, target_batches=64`。activity-schedule JSON 与 P1 baseline 的 SHA256
完全相同：

```text
3b2b756238a82fafd862df09e75e454f3f6586b1df5da2d38b641d8f313e6400
```

新 fast path 共命中 `609` 个 call sites：两字宽 `506`、三字宽 `56`、四字宽 `39`、五字宽
`8`。其中目标 `39` 个 `<4, 256>` call sites 全部替换完成，旧
`grhsim_replicate_words<4>(..., 1, 256, 256)` 数量从 `39` 降为 `0`。

O3 executable 中不再存在 `<3/4/5, SrcN=1>` 通用 helper，也不再存在 1-bit 两字递归模板实例：

| artifact | P1 baseline | broadcast | delta |
| --- | ---: | ---: | ---: |
| executable text | `106839279` | `106787143` | `-52136` (`-0.0488%`) |
| `libgrhsim_SimTop.a` | `113316922` | `113100270` | `-216652` (`-0.1912%`) |

fresh 产物与 build log：

```text
build/xs_grhsim_no0268_replicate_bit_fastpath_20260711/grhsim
build/logs/xs/xs_wolf_grhsim_build_no0268_replicate_bit_fastpath_20260711.log
```

## SimTop functional gate

| run | Guest cycles | instrCnt | cycleCnt | mismatch / ABORT |
| --- | ---: | ---: | ---: | ---: |
| 10k | `10001` | `458` | `9996` | `0 / 0` |
| 50k | `50001` | `73580` | `49996` | `0 / 0` |

日志：

```text
build/logs/xs/xs_wolf_grhsim_no0268_replicate_bit_fastpath_10k_20260711.log
build/logs/xs/xs_wolf_grhsim_no0268_replicate_bit_fastpath_50k_20260711.log
```

最初绑定 CPU 8 的 50k 功能运行结束后，CPU 8 连续采样为 `0% idle`，说明有其他任务竞争；其
`107274ms` Host time 不进入性能结论。

## CPU140 old/new/old

重新筛选 CPU 140；其 SMT sibling CPU 332 在测试前 5 秒采样均接近 `100% idle`，系统 load 约
`88~98/384`。三次都跑完整 50k，四个 perf events 均为 `100%` scheduled，且功能结果一致。

| run | Host time | cycles | instructions | branches | branch misses |
| --- | ---: | ---: | ---: | ---: | ---: |
| P1 old 1 | `121774ms` | `439939361179` | `227088033549` | `21404992956` | `7724764963` |
| broadcast | `120181ms` | `434979922745` | `204892394829` | `18857716638` | `7728798653` |
| P1 old 2 | `121595ms` | `439073219876` | `227087922011` | `21404880846` | `7725492773` |

以两次 old 均值为 baseline：

| metric | old mean | broadcast | delta |
| --- | ---: | ---: | ---: |
| Host time | `121684.5ms` | `120181ms` | `-1.2356%` |
| cycles | `439506290527.5` | `434979922745` | `-1.0299%` |
| instructions | `227087977780` | `204892394829` | `-9.7740%` |
| branches | `21404936901` | `18857716638` | `-11.9002%` |
| branch misses | `7725128868` | `7728798653` | `+0.0475%` |

旧 helper sampled 约 `2.433B` branches，本轮 retired branches 实际减少 `2.547B`，可解释
`95.53%`。根因与修复效果直接对应。被删除的循环分支高度可预测，绝对 branch misses 基本不变，
因此 IPC 从 `0.5167` 降为 `0.4710`，最终 cycles/Host 只兑现约 `1.0%~1.2%` 收益。

性能日志：

```text
build/logs/xs_perf/no0268/old_p1_cpu140_50k_run1.log
build/logs/xs_perf/no0268/old_p1_cpu140_50k_run1_perf_stat.csv
build/logs/xs_perf/no0268/bit_broadcast_cpu140_50k.log
build/logs/xs_perf/no0268/bit_broadcast_cpu140_50k_perf_stat.csv
build/logs/xs_perf/no0268/old_p1_cpu140_50k_run2.log
build/logs/xs_perf/no0268/old_p1_cpu140_50k_run2_perf_stat.csv
```

## Post-profile

新版本 branch profile 使用 `branches:u, period=1500000, dwarf 8192`，得到 `12570` samples、
lost `0`、近似事件数 `18.855B`。报告中已无任何 `grhsim_replicate*` symbol。按 symbol 聚合：

| class | branch share |
| --- | ---: |
| compute batches | `36.93%` |
| commit batches | `49.90%` |
| eval control | `10.53%` |
| other listed symbols | `2.39%` |

新的前三个热点为：

| symbol | share | approximate branches |
| --- | ---: | ---: |
| `eval_commit_batch_122()` | `11.58%` | `2.18B` |
| `GrhSIM_SimTop::eval()` | `10.53%` | `1.99B` |
| `eval_commit_batch_108()` | `5.62%` | `1.06B` |

三项合计约 `5.23B` branches，仍超过 NO0267 中 GSIM 整个 50k 的 `4.434B`。产物：

```text
build/logs/xs_perf/no0268/bit_broadcast_simtop_50k_branches.data
build/logs/xs_perf/no0268/bit_broadcast_simtop_50k_branches_run.log
build/logs/xs_perf/no0268/bit_broadcast_simtop_50k_branches_symbols.report
```

## 结论

1-bit wide broadcast fast path 通过 synthetic 与完整 SimTop 功能 gate，稳定减少约 `9.77%`
instructions 和 `11.90%` branches，并带来约 `1%` SimTop cycles 收益，应保留。下一步不再优化
replication，而应直接拆解 `commit_batch_122`、`eval()` 与 `commit_batch_108` 相对 GSIM 多出的
循环/派发工作，并优先寻找能降低 branch misses 或 memory traffic 的结构性差异。
