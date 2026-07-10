# NO0256 Full-mask register commit specialization

日期：2026-07-10

## 背景

[NO0255](./NO0255_simtop_same_fir_perf_profile_20260710.md) 发现当前 SimTop GrhSIM
的 commit batch 占 50k perf self cycles 的 `49.21%`。其中 batch112/126 每个 posedge
扫描 `61376` 个寄存器写入，而绝大多数写入的 mask 是编译期全 1，旧代码仍执行通用
masked merge。

本轮目标是只消除已证明冗余的 merge，不改变 event guard、changed check、state write
或 reader activation 语义。

## 实现

修改：

```text
wolvrix/lib/emit/grhsim_cpp.cpp
wolvrix/tests/emit/test_emit_grhsim_cpp.cpp
```

`emitWritePortBody()` 对非 memory 的 register/latch write 复用已有
`isConstLogicAllOnes()` 判定：

- scalar 全掩码：直接把 data 转成 state 类型；
- wide 全掩码：直接用 `assignWordsInlineExpr()` 比较并写入 data words；
- dynamic/partial scalar mask：保留 `(state & ~mask) | (data & mask)`；
- dynamic/partial wide mask：保留 `grhsim_merge_words_masked()`。

生成代码仍只在值变化时写 state 并激活 readers。该专门化没有把 changed check 或
activation 隐藏掉，也没有改动 memory write 的 mask 语义。

单测新增 scalar/wide 两组动态 mask fixture，并分别断言：

1. scalar/wide 编译期全掩码选择 direct update；
2. scalar 动态 mask 保留按位 merge；
3. wide 动态 mask 保留 words masked merge。

## emitter 测试

日志：

```text
build/logs/xs/no0255_wolvrix_build_full_mask_commit_v2_20260710.log
build/logs/xs/no0255_ctest_full_mask_commit_v2_20260710.log
build/logs/xs/no0255_py_install_full_mask_commit_20260710.log
```

结果：

```text
emit-grhsim-cpp             pass (126.34s)
emit-grhsim-cpp-memory-fill pass (4.92s)
2/2 passed
```

## VtypeBuffer source A/B

fresh 优化模型：

```text
build/no0255_full_mask_commit_vtype_20260710/XsReal075RobVtypebufferLarge
```

复用 NO0253 的同一份 SV、GSIM 对象和 benchmark harness，只 fresh 生成/编译 GrhSIM。
生成代码中有 `113` 个 register write 命中专门化。200k verify 重复运行均与 GSIM
checksum 一致。

日志：

```text
build/logs/xs/no0255_vtype_full_mask_commit_adjacent_old_1_20260710.log
build/logs/xs/no0255_vtype_full_mask_commit_adjacent_new_20260710.log
build/logs/xs/no0255_vtype_full_mask_commit_adjacent_old_2_20260710.log
```

| 版本 | GrhSIM 200k |
| --- | ---: |
| old run 1 | `327.136ms` |
| specialized | `325.486ms` |
| old run 2 | `326.869ms` |

old mean 为 `327.003ms`，specialized 为 `-0.46%`。收益较小但方向为正；commit 符号
机器码从 `0x1cef` 降到 `0x1bb6`，减少 `4.23%`。

## Fresh SimTop 生成与构建

产物：

```text
build/xs_grhsim_no0255_full_mask_commit_20260710/grhsim/grhsim_emit
build/xs_grhsim_no0255_full_mask_commit_20260710/grhsim/grhsim-compile/emu
```

日志：

```text
build/logs/xs/no0255_simtop_full_mask_commit_emit_20260710.log
build/logs/xs/no0255_simtop_full_mask_commit_model_build_20260710.log
build/logs/xs/no0255_simtop_full_mask_commit_emu_build_20260710.log
```

重新执行 reg-to-mem、activity-schedule 和 emitter；复用的是同一份 pre-reg-to-mem JSON，
不是旧 generated C++。结构指标与 NO0255 基线精确一致：

```text
compute/commit/total = 71871 / 497 / 72368
DAG edges            = 703270
BAE                  = 2446334
max commit ops       = 42937
```

`263767 / 268310 = 98.31%` 的 commit sink 命中全掩码 direct update；batch112 的
`18439` 个和 batch126 的 `42937` 个 register write 全部命中。

值得注意的是，batch112/126 的总符号尺寸分别从 `0x11b9c6/0x225ae6` 增至
`0x140a91/0x26f1ee`。反汇编显示 Clang 把 changed 分支的冷写入/activation block
外提到函数后部，未变化热路径则变成密集的 `cmp; jne cold` 链。总函数尺寸因此不是
本优化的可靠性能指标，热路径动态指令才是关键。

反汇编：

```text
build/logs/xs_perf/no0255/grhsim_full_mask_commit_batch_126_old.objdump
build/logs/xs_perf/no0255/grhsim_full_mask_commit_batch_126_new.objdump
```

## SimTop 功能 gate

10k smoke：

```text
build/logs/xs/no0255_simtop_full_mask_commit_smoke_10k_20260710.log
instrCnt = 458
cycleCnt = 9996
Host time spent = 14324ms
```

50k 相邻 old/new/old 三次均无 difftest mismatch、refill failure 或 ABORT，且进度一致：

```text
instrCnt = 73580
cycleCnt = 49996
```

## SimTop 相邻 50k A/B

机器 load 约 `16-23/384`。日志：

```text
build/logs/xs/no0255_simtop_full_mask_commit_adjacent_old_1_50k_20260710.log
build/logs/xs/no0255_simtop_full_mask_commit_adjacent_new_50k_20260710.log
build/logs/xs/no0255_simtop_full_mask_commit_adjacent_old_2_50k_20260710.log
```

| 顺序 | 版本 | Host time |
| --- | --- | ---: |
| 1 | old hybrid GrhSIM | `151320ms` |
| 2 | full-mask specialized | `106076ms` |
| 3 | old hybrid GrhSIM | `141582ms` |

old mean 为 `146451ms`：

```text
wall time reduction = 27.57%
speedup             = 1.381x
```

随后在 load `10/384` 下重跑同 FIR fresh GSIM 50k，得到 `31197ms`，与 NO0255 的
`31526ms/30973ms` 一致：

```text
build/logs/xs/no0255_simtop_full_mask_commit_bracket_gsim_50k_20260710.log
optimized GrhSIM / GSIM = 106076 / 31197 = 3.400x
```

因此优化显著缩小了差距，但 SimTop 最终目标尚未完成。

## 优化后 perf stat

日志：

```text
build/logs/xs/no0255_simtop_full_mask_commit_50k_perf_stat_20260710.txt
```

| metric | old GrhSIM | specialized | delta |
| --- | ---: | ---: | ---: |
| duration | `134.781s` | `108.887s` | `-19.21%` |
| cycles | `485258907523` | `397489404173` | `-18.09%` |
| instructions | `255312206310` | `236724507391` | `-7.28%` |
| branches | `19838958877` | `19791144286` | `-0.24%` |
| branch misses | `11168720905` | `7882458813` | `-29.42%` |
| cache references | `54446895462` | `50368847027` | `-7.49%` |
| cache misses | `38762681667` | `34863059164` | `-10.06%` |
| IPC | `0.526` | `0.596` | `+13.19%` |

相邻 wall A/B 的 `-27.57%` 与独立 perf-stat 的 `-19.21%` 受运行时段影响，不能把
两者混成一个精确数字；两种口径都显示大幅正收益，且功能进度一致。

## 优化后 perf record

产物：

```text
build/logs/xs_perf/no0255/grhsim_full_mask_commit_simtop_50k_cycles.data
build/logs/xs_perf/no0255/grhsim_full_mask_commit_simtop_50k_cycles_self.report
build/logs/xs_perf/no0255/grhsim_full_mask_commit_simtop_50k_cycles.perf-script
```

共约 10k samples，lost sample 为 0。聚合变化：

| 类别 | old | specialized |
| --- | ---: | ---: |
| commit batches | `49.21%` | `37.40%` |
| compute batches | `48.60%` | `60.15%` |
| eval control | `0.83%` | `0.92%` |
| helpers | `1.13%` | `1.06%` |

最初的两个 hot commit batch 明显下降：

```text
batch126  11.19% -> 2.31%
batch112   5.75% -> 0.81%
```

用各自 perf-stat duration 乘 self 占比作近似绝对时间分解：

```text
compute  65.50s -> 65.50s
commit   66.33s -> 40.72s
```

这说明收益确实来自 commit 路径，而不是 workload 进度或 compute 工作偶然减少。
优化后最大热点已变为 `eval_compute_batch_7()` 的 `3.00%`，compute 总体占 `60.15%`，
下一阶段应对照 GSIM 分析 compute generated code 和动态工作，不再继续围绕已消除的
全掩码 merge 调参。

## 结论

1. 全掩码 register commit direct update 保留完整 changed/activation 语义，局部 emitter
   测试、VtypeBuffer 200k checksum 和 SimTop 10k/50k difftest 均通过。
2. SimTop 相邻 50k 提速 `1.381x`，perf-stat duration 下降 `19.21%`；这是当前阶段明确的
   端到端正收益。
3. 同 FIR GSIM 校准后剩余差距为 `3.400x`，尚不能宣称 SimTop 性能问题已解决。
4. 优化后 compute 的近似绝对时间不变并成为 `60.15%` 主热点；下一步从
   `eval_compute_batch_7()` 等热点出发，与 GSIM `subStep*()` 的代码形态和动态工作对照。

