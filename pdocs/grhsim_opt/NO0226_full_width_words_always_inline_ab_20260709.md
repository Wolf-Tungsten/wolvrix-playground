# NO0226 Full-Width Words Always-Inline A/B

记录日期：2026-07-09

关联：[`NO0224`](./NO0224_vtypebuffer_codegen_hotpath_compare_20260709.md)、[`NO0225`](./NO0225_full_width_words_helper_ab_20260709.md)

## 1. 背景

`NO0225` 已经把完整 64-bit word 宽度的 `grhsim_*_words<16>(..., 1024)` 改成无 runtime `width` 参数的 `grhsim_*_words_full<16>`，证明 generic width/tail 开销是真实慢点。但 `VtypeBuffer` perf 中 full-width helper 仍有约 `9.11%` self：

- `grhsim_xor_words_full<16>`：`3.90%`
- `grhsim_and_words_full<16>`：`3.28%`
- `grhsim_assign_words_full<16>`：`1.73%`
- `grhsim_not_words_full<16>`：`0.20%`

因此本轮做一个更小的 A/B：不改 helper 选择逻辑，只给 `_full` helper 加 `always_inline`，观察 out-of-line call boundary / `std::array` 返回值 materialize 是否还能解释一部分剩余差距。

## 2. 本轮代码改动

修改文件：`wolvrix/lib/emit/grhsim_cpp.cpp`

新增生成 runtime 宏：

```cpp
#ifndef GRHSIM_ALWAYS_INLINE
#if defined(__GNUC__) || defined(__clang__)
#define GRHSIM_ALWAYS_INLINE inline __attribute__((always_inline))
#else
#define GRHSIM_ALWAYS_INLINE inline
#endif
#endif
```

仅把以下 full-width helper 从 `inline` 改为 `GRHSIM_ALWAYS_INLINE`：

- `grhsim_assign_words_full<N>`
- `grhsim_not_words_full<N>`
- `grhsim_and_words_full<N>`
- `grhsim_or_words_full<N>`
- `grhsim_xor_words_full<N>`
- `grhsim_xnor_words_full<N>`

没有修改 generic helper，也没有修改非整 word 宽度路径。

## 3. 产物与验证

主要产物：

```text
tmp/no0226_full_width_always_inline_20260709/
tmp/no0226_full_width_always_inline_20260709/summary/summary.json
tmp/no0226_full_width_always_inline_20260709/summary/raw_inline_ab.tsv
tmp/no0226_full_width_always_inline_20260709/summary/perf_vtypebuffer_inline.tsv
testcase/xs-components/build/no0226_full_width_always_inline_20260709/raw_bench/
```

执行/验证：

```bash
make py_install

make -C testcase/xs-components one CASE=XsReal075RobVtypebufferLarge \
  BUILD_DIR=build/no0226_full_width_always_inline_20260709/raw_bench \
  BENCH_VECTORS=200000 BENCH_VERIFY=2048 BENCH_REPEAT=3

for case in XsReal100BackendNfmappedelemidxSmall XsReal053FtqFtqLarge XsReal043TageTageLarge; do
  make -C testcase/xs-components one CASE="$case" \
    BUILD_DIR=build/no0226_full_width_always_inline_20260709/raw_bench \
    BENCH_VECTORS=200000 BENCH_VERIFY=2048 BENCH_REPEAT=3
done

perf stat -e cycles,instructions,branches,branch-misses,duration_time,user_time,system_time -- \
  testcase/xs-components/build/no0226_full_width_always_inline_20260709/raw_bench/XsReal075RobVtypebufferLarge/tb/XsReal075RobVtypebufferLarge_bench \
  --vectors 2000000 --verify 0 --repeat 1
perf record -F 999 -e cycles:u -g -- \
  testcase/xs-components/build/no0226_full_width_always_inline_20260709/raw_bench/XsReal075RobVtypebufferLarge/tb/XsReal075RobVtypebufferLarge_bench \
  --vectors 2000000 --verify 0 --repeat 1

ctest --test-dir wolvrix/build/skbuild --output-on-failure -R '^emit-grhsim-cpp($|-)'
# 2/2 passed: emit-grhsim-cpp, emit-grhsim-cpp-memory-fill
```

`BigComb` 未重跑：检查 `NO0225` BigComb 生成模型没有 `grhsim_*_words_full<...>` 调用点，因此本轮 always-inline 改动对它没有触发路径。

## 4. Raw A/B 结果

对照三组：

- baseline：`NO0223` 原始 generic helper。
- full-width：`NO0225` 无 runtime width/tail 的 `_full` helper。
- inline：本轮 `_full` helper 强制内联。

| case | baseline ratio | full-width ratio | inline ratio | inline GrhSIM vs full-width | inline GrhSIM vs baseline | inline GrhSIM instr | inline GrhSIM .text |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `XsReal100BackendNfmappedelemidxSmall` | 0.897 | 0.910 | 0.890 | -2.28% | -1.10% | 590 | 2449 |
| `XsReal053FtqFtqLarge` | 1.624 | 1.517 | 1.342 | -12.36% | -17.02% | 16965 | 80056 |
| `XsReal043TageTageLarge` | 1.666 | 1.626 | 1.453 | -10.56% | -14.37% | 14784 | 69471 |
| `XsReal075RobVtypebufferLarge` | 2.204 | 2.018 | 1.912 | -3.55% | -13.59% | 12922 | 61243 |

关键观察：

- `FTQ` / `Tage` 收益比 `VtypeBuffer` 更大，说明 out-of-line full helper call boundary 是多个 packed 1024-bit case 的共同慢点。
- `VtypeBuffer` 的 inline 版 `.text` 比 `NO0225` full-width 版略增（`60945 -> 61243`），但 runtime 仍下降，符合“用少量代码体积换掉 call/return 与 array materialize”的预期。
- `FTQ` / `Tage` 的 `.text` 反而下降，说明 `always_inline` 让编译器进一步 SROA/常量传播，消除了原本独立 helper 符号和部分搬运代码。
- `NfmappedElemidxSmall` 无宽字 full helper，结果只体现噪声级变化。

## 5. VtypeBuffer code shape 证据

`VtypeBuffer` 生成源码中仍有 `_full` 调用表达式：

| helper kind in `grhsim_*_sched_*.cpp` | textual full calls | textual generic calls |
| --- | ---: | ---: |
| `and` | 14 | 0 |
| `or` | 7 | 0 |
| `xor` | 14 | 0 |
| `not` | 5 | 0 |
| `assign` | 6 | 0 |

但编译后：

- `nm -S --size-sort -C *.o | grep 'grhsim_.*words_full<16'` 无输出。
- `objdump -drwC grhsim_XsReal075RobVtypebufferLarge_sched_3.o` 中 `eval_compute_batch_3()` 无 `_words_full<16>` call site。

热点 batch size：

| symbol | NO0225 full-width size | NO0226 always-inline size |
| --- | ---: | ---: |
| `eval_compute_batch_3()` | `0x512b` | `0x54db` |

也就是说，本轮确实把 helper 成本合并进 batch 本体，而不是仅仅重命名 perf 符号。

## 6. VtypeBuffer perf 对照

长窗口仍使用 `--vectors 2000000 --verify 0 --repeat 1`，日志显示 `2000002` timed vectors。

| metric | baseline NO0223 | full-width NO0225 | always-inline NO0226 |
| --- | ---: | ---: | ---: |
| GSIM ms | 2125.737 | 2061.935 | 2090.017 |
| GrhSIM ms | 4695.578 | 4135.227 | 4008.740 |
| GrhSIM/GSIM | 2.209 | 2.006 | 1.918 |
| words-helper self% | 13.95% | 9.11% | 0.00% |

相对变化：

- always-inline vs full-width：GrhSIM `-3.06%`，ratio `-4.36%`。
- always-inline vs baseline：GrhSIM `-14.63%`，ratio `-13.17%`。

perf top 也随之变化：

- `grhsim_*_words_full<16>` 不再出现在 top symbol。
- GrhSIM 时间集中到 `eval_compute_batch_3/1/2/0` 与 `eval_commit_batch_4` 本体：`26.29% + 9.49% + 9.12% + 7.97% + 7.42%`。

这说明 full helper 的独立开销已经基本消除，剩余慢点已不是“helper 函数调用本身”，而是 batch 内被内联后的宽字 lane 运算、临时值生命周期、写回/changed-check 与 fixed-point active 工作量。

## 7. 当前结论与下一步

本轮结论：

- `always_inline` 是有效优化，尤其对 `FTQ` / `Tage`，说明编译器默认没有稳定地内联这些 16-word helper。
- 它进一步支持 `NO0224` 的判断：GrhSIM 与 GSIM 的差距很大一部分在宽字 codegen 形态，而不是单纯分区/拓扑排序。
- 但 `VtypeBuffer` 仍有 `~1.9x` slowdown，说明下一步不能只继续调 helper 属性。

建议下一步：

1. 做 producer/assign 融合：对形如 `assign_words_full(dst, grhsim_xor/and/or_words_full(...))` 的模式，直接生成写 `dst[i]` 的 lane loop，并累积 changed bit，避免中间 `std::array`。
2. 对同一 batch 内只被消费一次的 1024-bit 临时值做 local scalarization：按 `word0..word15` 生成局部标量，减少 `std::array` 对象生命周期。
3. 给 bench 增加 `--model gsim|grhsim|both`，把 perf stat/report 从同进程合并采样改成单模型采样，方便继续看 IPC/branch/miss 差异。
