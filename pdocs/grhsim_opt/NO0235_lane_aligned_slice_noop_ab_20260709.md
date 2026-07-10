# NO0235 Lane-aligned slice 专门化 no-op A/B（2026-07-09）

## 1. 背景

`NO0234` 指出 `VtypeBuffer` 的 GrhSIM input-low 热点集中在 `eval_compute_batch_3()`，其中有大量宽字 helper、宽字临时和 `grhsim_slice_words<1>(..., 64*k, 64)[0]` 形态。

本轮尝试一个很小的 codegen 专门化：对静态、64-bit 对齐、结果宽度不超过 64 bit 的宽字 slice，直接生成 lane 读取，而不是走通用 `grhsim_slice_words` helper。

执行环境口径修正：本轮中途经用户提醒，后续生成/构建/测试命令均改为先执行：

```bash
source env.sh
```

并在 `.venv` 中刷新 editable `wolvrix`：

```bash
python -m pip install --no-build-isolation -e wolvrix
```

这样 `testcase/xs-components/scripts/emit_grhsim.py` 加载的是当前源码对应的 native extension，而不是旧 build 目录中的 `_wolvrix.so` / `libwolvrix-lib.so`。

## 2. 实验改动

临时修改位置：

```text
wolvrix/lib/emit/grhsim_cpp.cpp
```

实验内容：

1. 增加 `parseNonNegativeSizeLiteral()` 与 `alignedLaneSliceIndex()`；
2. 在 `sliceWordsExpr()` 中把 full-lane slice 生成成 `std::array<uint64_t,1>{src[lane]}`；
3. 进一步在 scalar result 的 `kSliceStatic` / const `kSliceDynamic` 路径中直接生成 `src[lane]`，避免 array 包装。

覆盖的典型热点形态：

```cpp
const std::uint64_t next_value =
    (grhsim_slice_words<1>(((grhsim_v3341_0)), static_cast<std::size_t>(0), 64))[0];
```

实验后生成形态：

```cpp
const std::uint64_t next_value = ((grhsim_v3341_0))[0];
```

该实验源码改动最终已撤回；本文只记录结果。

## 3. 生成源码变化

使用 `env.sh` + `.venv` 重新生成 `XsReal075RobVtypebufferLarge` GrhSIM model：

```text
tmp/no0235_lane_slice_ab_20260709/xs_env2/XsReal075RobVtypebufferLarge/grhsim/model/
```

关键源码统计：

| metric | baseline | lane-slice experiment |
|---|---:|---:|
| `sched_3.cpp` bytes | `252029` | `245372` |
| `sched_3.cpp` `grhsim_slice_words<1>` refs | `112` | `0` |
| `sched_3.cpp` direct scalar lane reads | `0` | `112` |
| `sched_3.o` bytes | `24336` | `24336` |
| `eval_compute_batch_3()` symbol size | `0x54db` | `0x54db` |

源码确实变短，且热点中 112 个 `slice_words<1>` 被替换为直接 lane 读取。

## 4. 机器码对比

进一步比较 baseline 与实验版的 GrhSIM object：

```text
643272af97c08644190a7f019eb6949eeb272f810cff00a1da40d1e0c64dc2a4  baseline sched_3.o
643272af97c08644190a7f019eb6949eeb272f810cff00a1da40d1e0c64dc2a4  experiment sched_3.o
```

并逐个比较 GrhSIM objects：

```text
state identical
eval identical
sched_0 identical
sched_1 identical
sched_2 identical
sched_3 identical
sched_4 identical
```

最终 bench binary 也完全一致：

```text
718697778fe5899c83788164ede5502a0be2d3ccbd731f24b33c12150e1e70b9  baseline bench
718697778fe5899c83788164ede5502a0be2d3ccbd731f24b33c12150e1e70b9  experiment bench
```

因此，在当前 `clang++ -O3` 口径下，编译器已经把原始 `grhsim_slice_words<1>(..., 64*k, 64)[0]` 优化为等价 lane load。这个 codegen 专门化虽然改变了源码形态，但没有改变机器码。

## 5. runtime 观测与解释

曾用 1M vectors、`--model grhsim` 做交错运行：

| run | min ms | median ms |
|---|---:|---:|
| experiment A | `2067.569` | `2069.278` |
| baseline A | `1998.721` | `2001.333` |
| baseline B | `2000.393` | `2001.691` |
| experiment B | `2070.536` | `2071.247` |

如果只看 wall time，似乎 experiment 慢 `~3.5%`。但 object 与最终 bench binary 已确认完全一致，所以这组 wall time 不能归因于源码改动，只能视为运行环境/频率/调度噪声。

这个结果也提醒：后续 A/B 必须先确认二进制是否真的不同；如果 binary identical，runtime 差异不应被解释为优化效果。

## 6. 结论

本实验结论是 **runtime no-op，源码改动已撤回**：

1. full-lane scalar slice 专门化能让生成源码更短；
2. 但当前 Clang already canonicalizes 该形态，GrhSIM `.o` 与最终 bench binary 完全一致；
3. 因此它不能解释 `NO0234` 看到的 input-low 指令数差距，也不是优先优化方向；
4. 后续不应继续追 `slice_words<1>(..., 64*k, 64)[0]` 这类表层语法，除非目标切换到编译时间或非 Clang 编译器。

## 7. 下一步

下一步应转向能实际改变机器码/指令数的方向：

1. `eval_compute_batch_3()` 中的宽字 producer-consumer 融合，目标是减少 16-lane `std::array<uint64_t,16>` 临时；
2. batch 内 value/state 的 typed local / lane local 化，目标是减少 `value_u64_slots_` / `state_logic_storage_` 重复搬运；
3. 每次 codegen A/B 后优先比较 `.o` / bench binary hash 与 hot symbol size，再解释 runtime。
