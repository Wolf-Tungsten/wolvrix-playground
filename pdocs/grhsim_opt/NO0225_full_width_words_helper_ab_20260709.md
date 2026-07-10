# NO0225 Full-Width Words Helper A/B

记录日期：2026-07-09

关联：[`NO0222`](./NO0222_small_load_codegen_perf_runbook_20260709.md)、[`NO0223`](./NO0223_small_load_codegen_perf_findings_20260709.md)、[`NO0224`](./NO0224_vtypebuffer_codegen_hotpath_compare_20260709.md)

## 1. 背景与假设

`NO0224` 在 `XsReal075RobVtypebufferLarge` 上直接对比生成 C++ / perf 后，定位到一个很具体的差异：GrhSIM 热路径大量使用 1024-bit `std::array<uint64_t, 16>` 临时值，并调用 generic `grhsim_*_words<16>(..., width)` helper；这些 helper 即使实际宽度固定为 `1024`，仍保留 runtime `width` 参数、尾部截断逻辑和 generic changed-check 形态。

本轮做一个小范围 codegen A/B：当结果宽度是完整 64-bit word 的整数倍，且 word 数 `>= 3` 时，把部分宽字 helper 改成无 `width` 参数的 full-width helper，验证“runtime width/truncation/generic helper”是不是 GrhSIM 慢点中的真实组成部分。

## 2. 本轮代码改动

修改文件：`wolvrix/lib/emit/grhsim_cpp.cpp`

新增/调整要点：

- 新增 `canUseFullWidthWordsHelper(width)`：仅在 `width > 0 && width % 64 == 0 && logicWordCount(width) >= 3` 时启用。
- `assignWordsInlineExpr()` 对 full-width 宽字赋值改发：
  - `grhsim_assign_words_full<N>(lhs, rhs)`
- `unaryWordsBufferOpExpr()` 对 `not` 改发：
  - `grhsim_not_words_full<N>(value)`
- `binaryWordsBufferOpExpr()` 对 `and/or/xor/xnor` 改发：
  - `grhsim_{and,or,xor,xnor}_words_full<N>(lhs, rhs)`
- runtime header 新增对应 full-width helper，去掉 `width` 参数与尾 word mask/truncation。

保守点：

- `logicWordCount(width) == 2` 仍走原先已有的 `grhsim_assign_words_2<width>` 专化。
- 非 64-bit 整 word 宽度仍走原 generic helper，避免改变 tail mask 语义。
- 目前只验证 `not/and/or/xor/xnor/assign`，没有触碰 slice、concat、mux、比较等其它宽字路径。

## 3. 产物与执行命令

主要产物：

```text
tmp/no0225_full_width_words_ab_20260709/
tmp/no0225_full_width_words_ab_20260709/summary/summary.json
tmp/no0225_full_width_words_ab_20260709/summary/raw_ab.tsv
tmp/no0225_full_width_words_ab_20260709/summary/code_shape_ab.tsv
tmp/no0225_full_width_words_ab_20260709/summary/perf_vtypebuffer.tsv
testcase/xs-components/build/no0225_full_width_words_ab_20260709/raw_bench/
testcase/big-comb/build/no0225_full_width_words_ab_20260709/
```

关键命令：

```bash
# 安装修改后的 wolvrix Python binding / emitter
make py_install

# VtypeBuffer 第一 ROI
make -C testcase/xs-components one CASE=XsReal075RobVtypebufferLarge \
  BUILD_DIR=build/no0225_full_width_words_ab_20260709/raw_bench \
  BENCH_VECTORS=200000 BENCH_VERIFY=2048 BENCH_REPEAT=3

# 其它 xs-components guard / 对照
for case in XsReal100BackendNfmappedelemidxSmall XsReal053FtqFtqLarge XsReal043TageTageLarge; do
  make -C testcase/xs-components one CASE="$case" \
    BUILD_DIR=build/no0225_full_width_words_ab_20260709/raw_bench \
    BENCH_VECTORS=200000 BENCH_VERIFY=2048 BENCH_REPEAT=3
done

# Tage 首次 make bench 中 GSIM 明显异常偏慢，复用同一 executable 补 repeat=5
./testcase/xs-components/build/no0225_full_width_words_ab_20260709/raw_bench/XsReal043TageTageLarge/tb/XsReal043TageTageLarge_bench \
  --vectors 200000 --verify 2048 --repeat 5

# BigComb guard
make -C testcase/big-comb bench \
  BUILD_DIR=build/no0225_full_width_words_ab_20260709 \
  BENCH_VECTORS=1000000 BENCH_VERIFY=4096

# VtypeBuffer 长窗口 perf
perf stat -e cycles,instructions,branches,branch-misses,duration_time,user_time,system_time -- \
  testcase/xs-components/build/no0225_full_width_words_ab_20260709/raw_bench/XsReal075RobVtypebufferLarge/tb/XsReal075RobVtypebufferLarge_bench \
  --vectors 2000000 --verify 0 --repeat 1
perf record -F 999 -e cycles:u -g -- \
  testcase/xs-components/build/no0225_full_width_words_ab_20260709/raw_bench/XsReal075RobVtypebufferLarge/tb/XsReal075RobVtypebufferLarge_bench \
  --vectors 2000000 --verify 0 --repeat 1
perf report --stdio --demangle
```

验证补充：

```bash
ctest --test-dir wolvrix/build/skbuild --output-on-failure -R '^emit-grhsim-cpp($|-)'
# 2/2 passed: emit-grhsim-cpp, emit-grhsim-cpp-memory-fill
```

另外曾跑过较宽的 `ctest -R 'emit|grh|load|store|transform'`，其中 `transform-comb-lane-pack` 与 `transform-repcut` 失败；本轮修改只在 GrhSIM C++ emit，且 targeted emit tests 通过，暂按非本 patch 引入的问题记录。

## 4. Raw A/B 结果

基线取 `NO0223` raw no-profile timing；本轮 A/B 使用同一 vectors 口径。`xs-components` 的 `--vectors 200000` 日志会显示 `200002`，含 testbench 额外 seed vector。

| case | vectors | baseline GSIM ms | baseline GrhSIM ms | baseline ratio | A/B GSIM ms | A/B GrhSIM ms | A/B ratio | ratio 变化 | GrhSIM ms 变化 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `BigComb` | 1000000 | 18412.182 | 18423.966 | 1.001 | 19070.365 | 18990.588 | 0.996 | -0.48% | +3.08% |
| `XsReal100BackendNfmappedelemidxSmall` | 200002 | 8.851 | 7.937 | 0.897 | 8.828 | 8.033 | 0.910 | +1.47% | +1.21% |
| `XsReal053FtqFtqLarge` | 200002 | 382.939 | 621.988 | 1.624 | 388.279 | 588.933 | 1.517 | -6.62% | -5.31% |
| `XsReal043TageTageLarge` | 200002 | 311.882 | 519.662 | 1.666 | 306.040 | 497.542 | 1.626 | -2.43% | -4.26% |
| `XsReal075RobVtypebufferLarge` | 200002 | 210.040 | 462.889 | 2.204 | 205.514 | 414.712 | 2.018 | -8.43% | -10.41% |

说明：

- `VtypeBuffer` 是预期最大受益者：GrhSIM raw time 降 `10.41%`，slowdown ratio 从 `2.204x` 降到 `2.018x`。
- `FTQ` 也有可见收益：GrhSIM raw time 降 `5.31%`，ratio 从 `1.624x` 降到 `1.517x`。
- `Tage` 首次 make bench 中 GSIM 约 `509ms`，明显偏离 `NO0223` 与补跑结果；表中采用同一 executable 的 repeat=5 补跑值，ratio 从 `1.666x` 小幅降到 `1.626x`。
- `BigComb` 的 GrhSIM 绝对时间比 `NO0223` 慢 `3.08%`，但 GSIM 同时也慢，且 GrhSIM 代码形态完全不变；这里更适合作为“没有明显功能/比例回退”的 guard，而不是衡量本 patch 收益。
- `NfmappedElemidxSmall` 太小，`~0.1ms` 级差异不宜过度解读。

## 5. Static code shape

| case | A/B GSIM instr | A/B GrhSIM instr | instr ratio | A/B GSIM .text | A/B GrhSIM .text | text ratio | GrhSIM instr vs baseline | GrhSIM .text vs baseline |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `BigComb` | 232800 | 186389 | 0.801 | 952103 | 891807 | 0.937 | 0 | 0 |
| `XsReal100BackendNfmappedelemidxSmall` | 473 | 590 | 1.247 | 2078 | 2449 | 1.179 | 0 | 0 |
| `XsReal053FtqFtqLarge` | 17094 | 17476 | 1.022 | 80826 | 83350 | 1.031 | -236 | -638 |
| `XsReal043TageTageLarge` | 14582 | 15099 | 1.035 | 67212 | 71483 | 1.064 | -140 | -416 |
| `XsReal075RobVtypebufferLarge` | 11047 | 12714 | 1.151 | 50133 | 60945 | 1.216 | -124 | -408 |

`VtypeBuffer` 的生成 C++ 变化更直接：

| helper kind in `grhsim_*_sched_*.cpp` | baseline generic calls | A/B generic calls | A/B full-width calls |
| --- | ---: | ---: | ---: |
| `and` | 14 | 0 | 14 |
| `or` | 7 | 0 | 7 |
| `xor` | 14 | 0 | 14 |
| `not` | 5 | 0 | 5 |
| `assign` | 6 | 0 | 6 |

热点 `eval_compute_batch_3()` 仍有 out-of-line helper call，但目标从 generic helper 变成 full-width helper；函数大小也只小幅下降：

| symbol | baseline size | A/B size |
| --- | ---: | ---: |
| `GrhSIM_XsReal075RobVtypebufferLarge::eval_compute_batch_3()` | `0x5194` | `0x512b` |
| `grhsim_and_words<16>` / `grhsim_and_words_full<16>` | `0x00fb` | `0x0079` |
| `grhsim_xor_words<16>` / `grhsim_xor_words_full<16>` | `0x00fb` | `0x0079` |
| `grhsim_not_words<16>` / `grhsim_not_words_full<16>` | `0x00f8` | `0x0076` |
| `grhsim_assign_words<16>` / `grhsim_assign_words_full<16>` | `0x00c7` | `0x011e` |

`assign_words_full<16>` 的 symbol 变大，但 raw time 仍下降；这说明不能只看 helper symbol size，关键是去掉 generic width/tail 分支后，调用点与其它 helper 的总执行形态变轻。

## 6. VtypeBuffer perf 对照

`perf` 长窗口使用 `--vectors 2000000 --verify 0 --repeat 1`，日志显示 `2000002` timed vectors。基线取 `NO0223` 的同口径 perf。

| metric | baseline | A/B | 变化 |
| --- | ---: | ---: | ---: |
| GSIM ms | 2125.737 | 2061.935 | -3.00% |
| GrhSIM ms | 4695.578 | 4135.227 | -11.93% |
| GrhSIM/GSIM | 2.209 | 2.006 | -9.21% |
| GrhSIM words-helper self% | 13.95% | 9.11% | -4.84 pp |

A/B perf top 中 full-width helper 仍然可见：

| symbol | self% |
| --- | ---: |
| `grhsim_xor_words_full<16>` | 3.90% |
| `grhsim_and_words_full<16>` | 3.28% |
| `grhsim_assign_words_full<16>` | 1.73% |
| `grhsim_not_words_full<16>` | 0.20% |

这说明本 patch 只吃掉了 generic width/tail 的一部分成本；`std::array<uint64_t,16>` 返回值、临时数组 materialize、out-of-line call 边界、宽字 changed-check/fixed-point 触发仍是剩余 `~2.0x` slowdown 的主要候选。

## 7. 结论

本轮 A/B 支持 `NO0224` 的直接判断：GrhSIM 在这些 state/aggregate 小负载上的慢点，确实有一部分来自宽字 generic helper 的运行时宽度/尾部处理形态。

但收益幅度也给出边界：

- `VtypeBuffer` 最多只从 `2.204x` 降到 `2.018x`，长窗口 perf 从 `2.209x` 降到 `2.006x`。
- full-width helper self% 仍有 `9.11%`，同时 `eval_compute_batch_*` 本体仍占大头。
- 因此“helper full-width 化”是有效小优化和强验证信号，但不是最终解。

下一步主线建议：

1. 继续以 `VtypeBuffer` 为 ROI，把 1024-bit `and/or/xor/not` 从 helper call 进一步降成调用点内联 lane 代码，避免 `std::array` 返回值与 out-of-line call。
2. 尝试把 `assign_words_full` 与 producer 融合：producer 直接写目标 storage 并累积 changed bit，减少中间 `std::array` 临时。
3. 给 `xs_component_bench` 增加 `--model gsim|grhsim|both`，让 perf stat/report 可以单独采样 GrhSIM，避免当前同进程合并采样带来的比例解释误差。
4. 保留 `BigComb`、`NfmappedElemidxSmall` 作为 guard；后续任何更激进的宽字 inline/lane lowering 都不能让这些 case 明显回退。
