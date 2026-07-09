# NO0224 VtypeBuffer Codegen Hot-Path Compare

记录日期：2026-07-09

关联：[`NO0222`](./NO0222_small_load_codegen_perf_runbook_20260709.md)、[`NO0223`](./NO0223_small_load_codegen_perf_findings_20260709.md)、[`NO0196`](./NO0196_two_eval_vs_xiangshan_sink_succ_inconsistency_20260614.md)、[`NO0199`](./NO0199_firrtl_packed_array_split_in_grhsim_cases_20260615.md)

## 1. 目的

承接 `NO0223`，本轮不再补长跑数据，而是继续直接对比 `XsReal075RobVtypebufferLarge` 的 GSIM / GrhSIM 生成 C++ 与汇编，回答“GrhSIM 为什么比 GSIM 慢”。

本轮使用已有产物：

```text
testcase/xs-components/build/no0222_small_load_codegen_perf_20260709/raw_bench/XsReal075RobVtypebufferLarge/
testcase/xs-components/build/no0222_small_load_codegen_perf_20260709/runtime_profile/XsReal075RobVtypebufferLarge/
tmp/no0222_small_load_codegen_perf_20260709/perf/XsReal075RobVtypebufferLarge.*
```

## 2. Perf 热点 recap

`XsReal075RobVtypebufferLarge` 的 no-profile raw timing 为：

| model | vectors | ms | 相对 GSIM |
| --- | ---: | ---: | ---: |
| GSIM | 200002 | 210.040 | 1.000 |
| GrhSIM | 200002 | 462.889 | 2.204 |

perf 放大到 `2,000,002` timed vectors 后仍一致：

| model | ms | 相对 GSIM |
| --- | ---: | ---: |
| GSIM | 2125.737 | 1.000 |
| GrhSIM | 4695.578 | 2.209 |

perf report 的主要 self 占比：

| symbol group | self% |
| --- | ---: |
| `SXsReal075RobVtypebufferLarge::subStep0/1` | 30.35 |
| `GrhSIM_XsReal075RobVtypebufferLarge::eval_compute_batch_{0..3}` | 45.47 |
| `GrhSIM_XsReal075RobVtypebufferLarge::eval_commit_batch_4` | 7.76 |
| `grhsim_and_words<16>` | 4.64 |
| `grhsim_assign_words<16>` | 4.56 |
| `grhsim_xor_words<16>` | 3.96 |

只看这个 case，GrhSIM 慢不是因为单一大函数，而是 `eval_compute_batch_*` + out-of-line 1024-bit helper + commit batch 合计压过 GSIM 的两个 `subStep`。

## 3. 二进制符号大小

从 `nm -C -S --size-sort` 可见：

| symbol | size(hex) | 备注 |
| --- | ---: | --- |
| `SXsReal075RobVtypebufferLarge::subStep0()` | `0x85e7` | GSIM 最大热点 |
| `SXsReal075RobVtypebufferLarge::subStep1()` | `0x2fa6` | GSIM 第二热点 |
| `GrhSIM_XsReal075RobVtypebufferLarge::eval_compute_batch_3()` | `0x5194` | GrhSIM 最大热点 |
| `GrhSIM_XsReal075RobVtypebufferLarge::eval_commit_batch_4()` | `0x1cef` | GrhSIM commit 热点 |
| `grhsim_xor_words<16>()` | `0x00fb` | out-of-line helper |
| `grhsim_and_words<16>()` | `0x00fb` | out-of-line helper |
| `grhsim_assign_words<16>()` | `0x00c7` | out-of-line helper |

注意：GrhSIM 的热点函数本身不比 GSIM `subStep0` 更大；问题更像“热路径形态 + helper 调用 + fixed-point 活动放大”的单位成本，而不是函数文本大小。

## 4. GrhSIM hot-path 形态

`grhsim_XsReal075RobVtypebufferLarge_sched_3.cpp` 是唯一含 1024-bit word helper 的 schedule 文件：

| file | lines | `grhsim_*_words` calls | `grhsim_assign_words` calls |
| --- | ---: | ---: | ---: |
| `sched_0.cpp` | 3212 | 0 | 0 |
| `sched_1.cpp` | 2099 | 0 | 0 |
| `sched_2.cpp` | 1406 | 0 | 0 |
| `sched_3.cpp` | 3249 | 46 | 6 |
| `sched_4.cpp` | 1499 | 0 | 0 |

源码中典型形态：

```cpp
const auto grhsim_v3316_0 =
    grhsim_xor_words((grhsim_v3314_0), (grhsim_v3315_0), 1024);

const auto next_words =
    grhsim_xor_words((grhsim_v3317_0), (grhsim_v3318_0), 1024);
if (grhsim_assign_words(grhsim_value_3319_0_slot, next_words, 1024)) {
    activeWordFlags |= UINT8_C(192);
}
```

最终汇编中，`eval_compute_batch_3()` 仍保留 21 个 out-of-line helper calls：

| helper target | call count in `eval_compute_batch_3` |
| --- | ---: |
| `grhsim_and_words<16>` | 8 |
| `grhsim_assign_words<16>` | 6 |
| `grhsim_xor_words<16>` | 5 |
| `grhsim_not_words<16>` | 2 |

即：源码里部分 helper 被优化/内联/消除，但热点函数仍然频繁调用 out-of-line 1024-bit helper。

## 5. Helper 汇编形态问题

以 `grhsim_xor_words<16>(..., width)` 为例，虽然所有调用点传入常量 `1024`，由于 helper 没有在 call site 完全内联，汇编仍保留通用逻辑：

- 使用 hidden sret 指针返回 `std::array<uint64_t,16>`；
- 函数 prologue 保存多个 callee-saved register；
- 先用 SSE 对 16 个 word 做 load/xor/store；
- 然后仍计算 `liveWords=(width+63)/64`；
- 对 `width < 1024` 的清零路径保留分支；
- 对最后一个 word 的 mask/truncation 路径保留分支与 mask 计算。

对本 case 来说，`width` 实际固定为 `1024`，最后的 truncation/mask 逻辑在语义上是 no-op，但 out-of-line helper 看不到这个常量，仍在热路径执行通用路径。

`grhsim_assign_words<16>` 的情况更糟：它需要比较 changed 并写回，汇编仍是按 `liveWords` 的 generic loop，而不是针对 16 个完整 64-bit word 的直线化 compare/store。

这解释了 perf 中 helper 自身就占约 `13.95%` self 的现象；更重要的是，`eval_compute_batch_3()` 内部还承担了为这些 helper 准备/保存 `std::array` 临时值、处理 active flags、传播 changed 的成本。

## 6. GSIM hot-path 形态

GSIM 的对应热点是 `XsReal075RobVtypebufferLarge0.cpp` / `1.cpp`，没有 `std::array` / word helper：

| file | lines | `uint64_t` occurrence | `std::array` | word helper |
| --- | ---: | ---: | ---: | ---: |
| `XsReal075RobVtypebufferLarge0.cpp` | 12459 | 4237 | 0 | 0 |
| `XsReal075RobVtypebufferLarge1.cpp` | 4662 | 1768 | 0 | 0 |

典型形态是按 lane / scalar 展开：

```cpp
_dataProbe_T_108 = (requestData ^ meta_27);
_dataProbe_x_T_108 = (_dataProbe_T_108 & 0x7ffffffffffffff);
_dataProbe_y_T_135 = (data_27 ^ _dataProbe_T_108);
_nextData_27_T = (dataProbe_27 ^ requestData);
_nextData_27_T_1 =
    ((-(uint64_t)_touchBits_27_T_1 & _nextData_27_T) |
     ((-(uint64_t)!_touchBits_27_T_1) & data_27));
data$NEXT_27 = _nextData_27_T_1;
```

GSIM 的 hot path 仍然有 active flags 和大量分支，但它在这个 case 中直接操作 `uint64_t` lane。GrhSIM 则先把若干 lane 重组成 `std::array<uint64_t,16>`，再通过 generic helper 做 1024-bit 逻辑，再拆 slice 回多个 64-bit slots。

## 7. Runtime fire 放大

runtime profile 对 `200002` component cycles 的 GrhSIM fire count：

| supernode | phase | fire count | fires / component cycle |
| ---: | --- | ---: | ---: |
| 3 | compute | 200002 | 1.00 |
| 33 | compute | 400003 | 2.00 |
| 34 | compute | 400003 | 2.00 |
| 35 | compute | 400003 | 2.00 |
| 36 | compute | 400003 | 2.00 |
| 38 | commit | 200002 | 1.00 |

`eval_compute_batch_3()` 覆盖多个 active-flag word / supernode block，并会把部分 `activeWordFlags` 回写给后续 batch。由于 `xs-components` 的 GrhSIM 每个 component cycle 本来就调用两次 `eval()`，再加 fixed-point round / active flag 传播，少量 1024-bit helper call site 能被动态放大到显著 perf 占比。

## 8. 诊断结论

本轮对比支持下面这个更具体的慢因假设：

> 对 `VtypeBuffer` 这类 workload，GrhSIM 慢的直接原因不是总 code size，也不是 supernode fire 数量更多；而是 GrhSIM 把一批本可按 64-bit lane/scalar 更新的逻辑组织成 1024-bit `std::array<uint64_t,16>` 临时值，再通过未完全内联且保留 runtime-width/truncation 的 generic helper 执行，并在 fixed-point active propagation 中反复触发。这导致单次 fire / 单次 batch 的单位成本显著高于 GSIM。

和 GSIM 的本质差异：

- GSIM：按 lane 标量直线化，`uint64_t` 局部变量 + changed flag。
- GrhSIM：宽值聚合，`std::array<uint64_t,16>` 临时 + generic words helper + `grhsim_assign_words` changed check + active flag propagation。

这也解释了 `NO0223` 中的现象：GrhSIM 的 fire rows / fires per vector 比 GSIM 少，但仍然更慢。

## 9. 下一步建议

下一步不应继续只盯全局 partition/topo，而应先做一个局部 codegen A/B：

1. 针对 `width == 1024 && N == 16` 的 `grhsim_and_words/xor_words/not_words/assign_words` 做专化：
   - 去掉 runtime `width` 参数或把 width 提升成模板常量；
   - full-width 时完全省掉 truncation/memset/mask；
   - `assign_words<16,1024>` 直线化 compare/store，避免 generic loop。
2. 或者更进一步：在 emitter 侧识别 `slice_words<1>(word16, k*64, 64)` 的后续使用，避免先重建 1024-bit array 再拆 lane。
3. 以 `XsReal075RobVtypebufferLarge` 为首个 A/B gate，验收：
   - `grhsim_*_words<16>` helper self% 明显下降；
   - `eval_compute_batch_3` self% 下降；
   - raw `GrhSIM/GSIM` 从 `2.20x` 明显回收；
   - `BigComb` / `NfmappedElemidxSmall` 不回退。

这条路线比继续调整全局 supernode 划分更直接，因为它命中当前 perf report 中已经坐实的 hot symbol。

## 10. 实现入口定位

本轮没有改源码，但后续 A/B 的源码入口已经明确：

- `wolvrix/lib/emit/grhsim_cpp.cpp:8890` 附近：`assignWordsInlineExpr()` 当前对 `logicWordCount(width) == 2` 有 `grhsim_assign_words_2<width>` 专化，但 `N == 16 / width == 1024` 仍落到 `grhsim_assign_words(dst, src, width)`。
- `wolvrix/lib/emit/grhsim_cpp.cpp:10450` 附近：宽 `kAnd/kOr/kXor/kNot` 通过 `binaryWordsBufferOpExpr()` / `unaryWordsBufferOpExpr()` 发出 `grhsim_*_words(..., width)`。
- `wolvrix/lib/emit/grhsim_cpp.cpp:15180` 附近：runtime header 生成 generic `grhsim_assign_words<N>(..., std::size_t width)`。
- `wolvrix/lib/emit/grhsim_cpp.cpp:16335` 附近：runtime header 生成 generic `std::array` 版本 `grhsim_and_words/or_words/xor_words<N>(..., std::size_t width)`。

也就是说，第一版 A/B 可以很小：沿用现有 `grhsim_assign_words_2<width>` 的模式，为 full-width words 增加 `grhsim_assign_words_full<N>()` / `grhsim_xor_words_full<N>()` / `grhsim_and_words_full<N>()`，并在 emit 时当 `width == N * 64` 直接选 full-width helper。这样可以先验证“去掉 runtime width/truncation + 提高 inline 机会”是否能回收 VtypeBuffer 的 perf 差距。
