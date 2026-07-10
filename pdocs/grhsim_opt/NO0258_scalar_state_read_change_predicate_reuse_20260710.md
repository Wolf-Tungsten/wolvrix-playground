# NO0258 Scalar state-read change-predicate reuse

日期：2026-07-10

## 目标

承接 [NO0257](./NO0257_simtop_duplicate_scalar_state_read_diagnosis_20260710.md)，消除
同一 compute supernode 内对同一 scalar register/latch state 的重复 changed comparison，
但不合并 value slot、不删除 result effects，也不改变 event phase。

## 实现

修改：

```text
wolvrix/lib/emit/grhsim_cpp.cpp
wolvrix/tests/emit/test_emit_grhsim_cpp.cpp
```

`SupernodeLocalExprContext` 新增按 state symbol 索引的 changed-predicate cache。对于 compute
phase、非 event、需要 changed detection 的 scalar register/latch read：

- 第一次读取照旧生成 `old_slot != state`，并缓存 `grhsim_changed_<value-id>`；
- 后续同 state 读取复用该 bool；
- 每个 result 仍调用自己的 `emitChangedValueEffectsForCondition()`；
- 每个 result slot 仍分别执行 `slot = state`；
- wide read、event value、commit phase 和不需要 changed detection 的路径保持旧逻辑。

生成代码由：

```cpp
const bool changed_a = (slot_a != state);
effects_a(changed_a);
slot_a = state;
const bool changed_b = (slot_b != state);
effects_b(changed_b);
slot_b = state;
```

收敛为：

```cpp
const bool changed_a = (slot_a != state);
effects_a(changed_a);
slot_a = state;
effects_b(changed_a);
slot_b = state;
```

## emitter 测试

新增 synthetic register/system-task fixture，让同一 scalar read 被重复使用 16 次，并强制
oversize split 触发 source clone。测试同时检查生成代码出现 predicate reuse，并编译运行
harness 验证寄存器初值、posedge 写入及后续稳定值。

日志：

```text
build/logs/xs/no0257_wolvrix_build_state_read_change_reuse_v2_20260710.log
build/logs/xs/no0257_ctest_state_read_change_reuse_v2_20260710.log
build/logs/xs/no0257_py_install_state_read_change_reuse_20260710.log
```

结果：

```text
emit-grhsim-cpp             pass (132.20s)
emit-grhsim-cpp-memory-fill pass (4.77s)
2/2 passed
```

## VtypeBuffer gate

fresh candidate：

```text
build/no0257_state_read_change_vtype_20260710/XsReal075RobVtypebufferLarge
build/logs/xs/no0257_vtype_state_read_change_reuse_source_gate_20260710.log
```

该 case 静态上没有同 supernode duplicate scalar state read，因此本优化命中 0 次，主要用于
no-regression gate。`--verify 200000` 通过，三次 GSIM/GrhSIM checksum 均对应一致：

| simulator | 200002 vectors min |
| --- | ---: |
| GSIM | `217.959ms` |
| GrhSIM | `329.794ms` |

由于本轮与旧 VtypeBuffer 测量不在同一机器窗口，不用跨窗口 raw time 宣称性能变化。

## Fresh SimTop 静态 gate

输入与 NO0256 使用同一份 pre-reg-to-mem checkpoint，调度参数保持
`compute=108, commit=4096, target_batches=64`，并开启当前 best 的 input/posedge
full-pass specialization。

产物：

```text
build/xs_grhsim_no0257_state_read_change_20260710/grhsim
build/logs/xs/no0257_simtop_state_read_change_emit_20260710.log
build/logs/xs/no0257_simtop_state_read_change_model_build_clang_20260710.log
build/logs/xs/no0257_simtop_state_read_change_emu_build_20260710.log
```

静态结果：

| 指标 | old | candidate |
| --- | ---: | ---: |
| activity schedule JSON SHA256 | `e143f0d...f149b` | `e143f0d...f149b` |
| sched C++ files | `130` | `130` |
| generated reuse comments | `0` | `73142` |
| normal/fullpass logical hits | `0/0` | `36571/36571` |
| files containing hits | `0` | `9` |

`sched_7` 集中了 `63956/73142` 个 generated hits。normal function 与 object 缩小：

| 指标 | old | candidate | 变化 |
| --- | ---: | ---: | ---: |
| `sched_7.cpp` bytes | `73414474` | `69046704` | `-5.95%` |
| `eval_compute_batch_7()` text | `1857872` | `1435341` | `-22.74%` |
| `sched_7.o` bytes | `2860328` | `2435600` | `-14.85%` |
| final `emu` bytes | `173232600` | `172745176` | `-0.28%` |

fullpass 函数 text 保持 `961989` bytes；本轮实际机器码收益主要在 normal active compute。

## SimTop correctness

10k smoke：

```text
build/logs/xs/no0257_simtop_state_read_change_smoke_10k_20260710.log
```

结果：

```text
Guest cycles = 10001
instrCnt = 458
cycleCnt = 9996
difftest mismatch = 0
```

后续所有 50k old/candidate 运行也都得到：

```text
Guest cycles = 50001
instrCnt = 73580
cycleCnt = 49996
IPC = 1.471718
difftest mismatch = 0
```

## SimTop performance

### 机器负载说明

测试期间机器共有约 43 到 74 个登录用户，系统 load 大多为 `26~57/384`，总体 CPU idle
约 `89%~91%`，但单线程频率波动很大。同一 NO0256 old binary 在不同运行中出现
`106079ms`、`116206ms`、`123498ms`、`319449ms`，因此不能简单平均所有 raw wall time。

固定 CPU 132 的 old/new/old 进一步证明低频下优化会被放大：

| 版本 | Host time | user time |
| --- | ---: | ---: |
| old 1 | `255635ms` | `247.68s` |
| candidate | `164108ms` | `159.07s` |
| old 2 | `249654ms` | `242.00s` |

old Host mean `252644.5ms`，candidate 为 `-35.05%`。该结果说明 candidate 确实减少 hot
work，但它不是正常高频下的通用加速比例。

### 正常频率与 perf-stat 对照

已有 NO0256 稳定高频 raw baseline 为 `106076ms`，本轮 candidate raw 为 `105556ms`，即
`-0.49%`。独立 perf-stat baseline/candidate 为 `108862/107557ms`，即 `-1.20%`。

同窗 `candidate -> old` perf-stat 因 old 运行中频率较低，wall time 为
`107557/123498ms`（candidate `-12.91%`）。硬件工作量是更稳定的判断依据：

| counter | same-window old | candidate | 变化 |
| --- | ---: | ---: | ---: |
| cycles | `446958467099` | `389838581958` | `-12.78%` |
| instructions | `236691509255` | `231737294279` | `-2.09%` |
| branches | `19771984100` | `19740525072` | `-0.16%` |
| branch misses | `7881886586` | `7878341628` | `-0.04%` |
| cache references | `50270935969` | `50030795708` | `-0.48%` |
| cache misses | `34839590015` | `34557143387` | `-0.81%` |

日志：

```text
build/logs/xs/no0257_simtop_state_read_change_50k_perf_stat_20260710.txt
build/logs/xs/no0257_simtop_state_read_change_50k_perf_stat_run_20260710.log
build/logs/xs/no0257_simtop_state_read_change_adjacent_old_50k_perf_stat_20260710.txt
build/logs/xs/no0257_simtop_state_read_change_adjacent_old_50k_perf_stat_run_20260710.log
```

## 结论

本优化通过功能、结构和 runtime gate，并把 50k host instructions 稳定降低约 `2.1%`。
正常高频 wall time 收益约 `0.5%~1.2%`；低频/频率受限窗口可能放大到更高比例，但不把
该值作为默认承诺。

它直接消除了 [NO0257](./NO0257_simtop_duplicate_scalar_state_read_diagnosis_20260710.md)
定位的 GrhSIM 额外工作，同时保留各 read result 的独立存储和激活语义，可以保留。下一步
应重新 profile candidate，确认 `eval_compute_batch_7()` 的占比变化并选择新的最大热点。
