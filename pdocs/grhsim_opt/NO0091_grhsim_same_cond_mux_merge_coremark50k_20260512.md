# NO0091 GrhSIM Same-Cond Mux Merge CoreMark 50k

> 2026-05-12 继续基于 [`NO0090`](./NO0090_grhsim_branchless_mux_select_coremark50k_20260511.md) 的 branchless mux select，尝试把同一条件的 mux 选择进一步合并，减少重复 `cond != 0` 判断开销。最终保留 GrhSIM C++ emit 对相邻同条件 scalar mux run 复用一个 mask，且仅在 run 长度 `>= 8` 时启用；activity-schedule compute-node build 阶段合并已实测失败并移除。

## 1. 背景

`NO0090` 已将 scalar / words mux 从 C++ `?:` 改成 mask-select helper，明显降低静态控制流和动态 branch miss。但每个 scalar mux 仍会独立执行：

```cpp
cond != 0
```

XiangShan 生成代码中存在连续同条件 mux 串，适合参考 gsim when merge 思路，把一次条件判断结果复用到多个 mux 选择。

## 2. 实现

### 2.1 emit 层 mask 复用

在 `wolvrix/lib/emit/grhsim_cpp.cpp` 中新增：

- `scalarMuxSelectExpr(...)`：接受已生成的 `trueMask` 表达式，直接发出 `(true & mask) | (false & ~mask)` helper；
- runtime helper `grhsim_select_u64(mask, trueValue, falseValue)`；
- scalar op emit loop 中识别相邻同条件 `kMux` run，run 长度 `>= 8` 时只生成一次：

```cpp
const std::uint64_t mux_mask_X_Y = static_cast<std::uint64_t>(
    -static_cast<std::int64_t>(static_cast<std::uint64_t>(cond) != 0));
```

随后该 run 内每个 mux 使用：

```cpp
grhsim_select_u64(mux_mask_X_Y, trueValue, falseValue)
```

短 run 保持原 `grhsim_mux_u64(cond, trueValue, falseValue)`，避免为了少量 mux 引入额外局部变量和更大的 `.text`。

新增 emit 单测构造 8 个相邻同条件 scalar mux，检查生成代码中：

- 只有 1 个 `const std::uint64_t mux_mask_...`；
- 有 8 个 `grhsim_select_u64(...)`；
- 不再有该 run 的 `grhsim_mux_u64(...)` 或 mux `?:`。

## 3. 失败尝试与反思

| 尝试 | 结果 | 反思 |
| --- | ---: | --- |
| supernode-wide lazy mask reuse | `394.817824 s`, `309.075B` instructions | 复用范围过大，局部 mask 声明和 select 铺开导致 `.text` 与动态指令都上涨，吞掉条件复用收益。 |
| materialize 后同 cond mux computeNode merge + helper | `384.765926 s`, `299.781B` instructions | 只命中 `667` 组 / `2730` node，覆盖太小；run 形态没有充分转化成 emit 热点收益。 |
| compute-node build 全局同 cond owner 复用 | schedule 失败：`compute-node topo failed: graph contains cycle` | 同一 cond group 跨越已有依赖区间，后续递归 owner 分配会在 compute DAG 中制造回边。 |
| compute-node build root-only + 依赖检查 | `453.570252 s`, `339.045B` instructions | 虽避免 cycle，但把 mux root 从原局部计算链里拆出来，`compute_supernodes=88364`，`.text=120.322MB`，动态指令显著增加。 |
| schedule merge 默认关闭 + helper split | `382.876604 s` / `404.046749 s` 两次波动 | 默认路径没有稳定收益，说明单纯拆 helper 不是可靠优化点。 |
| emit run threshold `>= 4` | `373.303807 s`, `303.390B` instructions | wall time 有收益，但 `grhsim_select_u64` 达 `159,841` 次，`.text` 到 `118.482MB`，动态 retired instructions 上涨偏多。 |

最终选择 threshold `>= 8`：覆盖长 run，减少重复判断，同时显著收敛代码膨胀和动态指令增量。

## 4. 生成代码覆盖

最终 `RUN_ID=20260512_mux_run_emit8` 生成代码统计：

| 项 | value |
| --- | ---: |
| `mux_mask_*` occurrences | `55,803` |
| `grhsim_select_u64` occurrences | `51,563` |
| `grhsim_mux_u64` occurrences | `725,298` |
| `grhsim_mux_words` occurrences | `5,279` |

## 5. 静态二进制变化

对比 `NO0090` branchless mux 当前基线。

| 静态计数 | NO0090 branchless | same-cond mux run `>=8` | change |
| --- | ---: | ---: | ---: |
| file size | `118,048,136 B` | `118,162,824 B` | `+0.10%` |
| `.text` | `111,926,335 B` | `117,832,681 B` | `+5.28%` |
| all instructions | `22,651,890` | `22,677,379` | `+0.11%` |
| memory-form instructions | `9,546,250` | `9,554,419` | `+0.09%` |
| branch/control-flow instructions | `968,670` | `968,823` | `+0.02%` |

静态指令数基本持平，但 `.text` 增大。主要原因是长 run 中独立 select 表达式展开后增加了局部代码体积。threshold `>= 4` 的 `.text` 为 `118,482,289 B`、静态指令 `22,805,889`，因此 threshold `>= 8` 明显更可控。

## 6. CoreMark 50k Perf

命令：

```bash
env -u EMU_RUNTIME_PROFILE EMU_PROGRESS_EVERY_CYCLES=0 \
  perf stat -o build/logs/xs_perf_mux_run_emit8/grhsim_basic.stat \
  -e cycles,instructions,branches,branch-misses,cache-references,cache-misses,duration_time,user_time,system_time \
  build/xs/grhsim/grhsim-compile/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 50000
```

Guest 结果：

| 指标 | value |
| --- | ---: |
| guest cycle spent | `50,001` |
| core cycleCnt | `49,996` |
| guest instrCnt | `73,580` |
| guest IPC | `1.471718` |
| end PC | `0x80001312` |
| host time from emu | `369,931 ms` |

Perf 对比：

| perf 指标 | NO0090 branchless | same-cond mux run `>=8` | change |
| --- | ---: | ---: | ---: |
| elapsed time | `376.894818 s` | `369.943408 s` | `-1.84%` |
| cycles | `2,164,479,349,428` | `2,122,900,045,714` | `-1.92%` |
| instructions | `300,934,575,320` | `301,526,185,271` | `+0.20%` |
| IPC | `0.139` | `0.142` | improved |
| branches | `29,023,470,352` | `28,969,061,577` | `-0.19%` |
| branch misses | `12,345,101,414` | `12,314,042,576` | `-0.25%` |
| branch miss rate | `42.53%` | `42.51%` | `-0.02pp` |
| cache references | `91,315,909,039` | `92,430,326,916` | `+1.22%` |
| cache misses | `46,712,466,312` | `46,954,708,295` | `+0.52%` |
| host time from emu | `376,883 ms` | `369,931 ms` | `-1.84%` |

## 7. 验证

本地构建与单测：

```bash
cmake --build wolvrix/build --target emit-grhsim-cpp transform-activity-schedule -j$(nproc)
ctest --test-dir wolvrix/build --output-on-failure \
  -R '^(transform-activity-schedule|emit-grhsim-cpp|emit-grhsim-cpp-memory-fill)$'
```

结果：

```text
3/3 tests passed
```

XS 生成与编译：

```bash
make xs_wolf_grhsim_emu \
  RUN_ID=20260512_mux_run_emit8 \
  XS_COMMIT_TRACE=0 \
  XS_PROGRESS_EVERY_CYCLES=0
```

关键产物：

| path | value |
| --- | --- |
| build log | `build/logs/xs/xs_wolf_grhsim_build_20260512_mux_run_emit8.log` |
| perf log | `build/logs/xs_perf_mux_run_emit8/grhsim_basic.stat` |
| emu | `build/xs/grhsim/grhsim-compile/emu` |
| emu mtime | `2026-05-12 01:19:26 +0800` |

## 8. 结论

本轮最终优化有效，但不是 schedule 合并本身直接带来收益，而是 emit 层对长相邻同条件 scalar mux run 复用 mask 带来收益：

- CoreMark 50k host time 从 `376,883 ms` 降到 `369,931 ms`，提升 `1.84%`；
- dynamic retired instructions 只增加 `0.20%`，满足“不引入过多指令”的约束；
- branches / branch misses 小幅下降；
- 静态总指令基本持平，但 `.text` 增大 `5.28%`，这是后续需要继续压缩的主要代价。

保留策略：

- 不保留 activity-schedule 同条件 mux computeNode build 合并代码。本轮重做后实测 `453.57s`，比 branchless 基线和 emit-run 最优都明显回退；
- 默认性能路径启用 emit run threshold `>= 8` 的 mask 复用，因为它在当前 XS CoreMark 50k 上有稳定可测收益，且动态指令增量受控。
