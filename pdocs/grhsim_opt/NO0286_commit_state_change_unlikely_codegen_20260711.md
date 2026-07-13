# NO0286 Commit state-change unlikely codegen

日期：2026-07-11

## 1. 依据与范围

[NO0285](./NO0285_state_read_alias_post_profile_commit_layout_diagnosis_20260711.md) 发现高 CPI commit
batches 的 scalar state changed-check 常被 Clang 布局为“相等时 taken branch 跳过更新”，而低 CPI 的
commit113 已经是未变化路径 fall-through。本轮只给 register/latch commit state-change 条件增加静态
cold hint，不改 compute、memory write、state update 或 reader activation 语义。

## 2. 实现

新增 emit option/environment：

```text
commit_state_change_unlikely
WOLVRIX_GRHSIM_COMMIT_STATE_CHANGE_UNLIKELY
```

默认启用，设为 `0/false/off/no` 可恢复旧生成形态。开启后 scalar 和 wide、full-mask 和 dynamic-mask
register/latch commit 分别生成：

```cpp
if (unlikely(state != next_value)) { ... }
if (unlikely(grhsim_assign_words(state, next_words, width))) { ... }
```

memory write/fill 不在本轮范围内。`unlikely` 只向编译器提供分支概率，不重复求值条件。

## 3. Emitter gate

`emit-grhsim-cpp` 主 harness 默认检查四种 register write 均含 `if (unlikely(...))`，并编译运行完整
generated C++。同一设计额外用 option `0` 重新 emit，确认 scalar register write 恢复无 hint 条件。

```text
cmake --build wolvrix/build -j8 --target emit-grhsim-cpp
ctest --test-dir wolvrix/build -R '^emit-grhsim-cpp$' --output-on-failure
```

实现阶段 CTest 用时 `145.47s`，通过。

## 4. SimTop fresh structure gate

从 NO0283 相同 pre-reg-to-mem checkpoint fresh 恢复；第一次手工 emit 因 editable Python package 未
重装而没有加载新 emitter，结构检查及时拦截，产物未编译。执行仓库标准命令：

```text
python3 -m pip install --no-build-isolation -e wolvrix
```

并确认 `.venv` 中 `libwolvrix-lib.so` 含新环境变量后重新 fresh emit。关键统计与 NO0283 完全一致：

| metric | value |
| --- | ---: |
| supernodes | `67934` |
| compute / commit supernodes | `67449 / 485` |
| DAG edges | `638649` |
| source clones | `2044602` |
| commit ops max | `42937` |

fresh emit 总耗时约 `307s`，C++ emit `61.2s`。sched94 的每条目标 write 均生成 hinted condition。

## 5. O3 layout and size

O3 emu 中 sched94 changed-check 从旧形态：

```asm
cmp state,next
je  skip_update
```

变为：

```asm
cmp state,next
jne cold_update
; next comparison falls through
```

目标函数和全局 text 有膨胀：

| symbol/metric | NO0283 | NO0286 | change |
| --- | ---: | ---: | ---: |
| commit79 text | `0x3b567` | `0x4522d` | `+16.2%` |
| commit82 text | `0x35ea2` | `0x43a55` | `+24.9%` |
| commit94 text | `0x358cf` | `0x430be` | `+25.1%` |
| commit113 text | `0x26f2ed` | `0x26fde7` | `+0.11%` |
| full emu `.text` | `96112687` | `97049715` | `+937028` (`+0.97%`) |

因此是否保留必须由 runtime gate 决定，不能只看分支方向。

## 6. Functional gate

10k 与后续 50k 均通过 NEMU difftest：

| gate | guest cycles | instrCnt | cycleCnt | terminal PC |
| --- | ---: | ---: | ---: | --- |
| 10k | `10001` | `458` | `9996` | `0x800027c6` |
| 50k | `50001` | `73580` | `49996` | `0x80001312` |

## 7. 产物

```text
build/xs_grhsim_no0286_commit_change_unlikely_20260711/grhsim
build/logs/xs/xs_wolf_grhsim_build_no0286_commit_change_unlikely_emit_20260711.log
build/logs/xs_perf/no0286/commit_change_unlikely_build_20260711.log
build/logs/xs_perf/no0286/commit_change_unlikely_functional_10k_20260711.log
```
