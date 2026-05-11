# NO0090 GrhSIM Branchless Mux Select CoreMark 50k

> 2026-05-11 基于 [`NO0089`](./NO0089_current_gsim_grhsim_perf_static_dynamic_coremark50k_20260511.md) 的结论，针对 `kMux` 生成 `?:` 可能引入大量 host branch 的问题，把 scalar / words mux emit 改成 mask-select helper。结果显示该方向能显著降低静态与动态分支，并带来可测的 CoreMark 50k wall-time 收益；代价是动态 retired instructions 小幅上升。

## 1. 背景

`NO0089` 显示当前 GrhSIM 的分支压力明显高于总指令膨胀：

| 指标 | GSim | GrhSIM | GrhSIM / GSim |
| --- | ---: | ---: | ---: |
| static all instructions | `9,841,119` | `23,189,727` | `2.356x` |
| static branch/control-flow instructions | `454,356` | `1,553,168` | `3.418x` |
| dynamic branches | `4,518,767,074` | `34,333,402,633` | `7.598x` |
| dynamic branch misses | `1,857,682,250` | `16,137,579,459` | `8.687x` |
| branch miss rate | `41.11%` | `47.00%` | `1.143x` |

其中 `kMux` 在 XiangShan `activity-schedule` 中规模很大，重建日志显示 `kMux:197429`。旧 scalar mux emit 直接生成 C++ `?:`：

```cpp
((cond) ? (true_expr) : (false_expr))
```

这让后端编译器有机会在大量局部条件选择上生成 branch 或控制流形态。由于 RTL mux 本质上是数据选择，本轮尝试改为 mask-select。

## 2. 实现

源码改动：

- `wolvrix/lib/emit/grhsim_cpp.cpp`
  - scalar `OperationKind::kMux` 改为生成 `grhsim_mux_u64(...)`；
  - wide / words `OperationKind::kMux` 改为生成 `grhsim_mux_words<N>(...)`；
  - runtime helper 使用 `cond != 0` 生成全 0 / 全 1 mask，再做 `(true & mask) | (false & ~mask)`。
- `wolvrix/tests/emit/test_emit_grhsim_cpp.cpp`
  - 增加 scalar mux fixture；
  - 检查 runtime helper 存在；
  - 检查生成 schedule 使用 `grhsim_mux_u64` / `grhsim_mux_words`，不再使用 mux `?:`。

scalar helper 形态：

```cpp
inline std::uint64_t grhsim_mux_u64(std::uint64_t cond,
                                    std::uint64_t trueValue,
                                    std::uint64_t falseValue)
{
    const std::uint64_t trueMask =
        static_cast<std::uint64_t>(-static_cast<std::int64_t>(cond != 0));
    return (trueValue & trueMask) | (falseValue & ~trueMask);
}
```

words helper 形态：

```cpp
template <std::size_t N>
inline std::array<std::uint64_t, N> grhsim_mux_words(
    std::uint64_t cond,
    const std::array<std::uint64_t, N> &trueValue,
    const std::array<std::uint64_t, N> &falseValue,
    std::size_t width)
{
    const std::uint64_t trueMask =
        static_cast<std::uint64_t>(-static_cast<std::int64_t>(cond != 0));
    std::array<std::uint64_t, N> out{};
    for (std::size_t i = 0; i < N; ++i) {
        out[i] = (trueValue[i] & trueMask) | (falseValue[i] & ~trueMask);
    }
    grhsim_trunc_words(out, width);
    return out;
}
```

## 3. 生成代码覆盖

重新生成 XiangShan GrhSIM 后，`grhsim_SimTop_sched_*.cpp` 中 mux helper 覆盖如下：

| helper | occurrences |
| --- | ---: |
| `grhsim_mux_u64` | `776,861` |
| `grhsim_mux_words` | `5,279` |

检查 `grhsim_SimTop_sched_*.cpp` 未命中旧 mux 形态 `? (`。剩余 `?:` 主要来自 shift bound、runtime helper、task formatting 等非本轮 mux emit 路径。

小生成样例中：

- scalar mux 生成 `const std::uint8_t next_value = grhsim_mux_u64(...)`；
- wide mux 生成 `const auto next_words = grhsim_mux_words<3>(...)`。

对小样例 schedule 以 `clang++ -O3 -S` 检查，helper 被内联后主要落为 `test` + `cmov*` / bitwise select 形态，没有由 mux helper 引入条件跳转。

## 4. 构建与验证

单元测试：

```bash
ctest --test-dir wolvrix/build --output-on-failure \
  -R '^(emit-grhsim-cpp|emit-grhsim-cpp-memory-fill)$'
```

结果：

```text
2/2 tests passed
```

XiangShan GrhSIM 重建：

```bash
make xs_wolf_grhsim_emu \
  RUN_ID=20260511_mux_branchless \
  XS_COMMIT_TRACE=0 \
  XS_PROGRESS_EVERY_CYCLES=0
```

关键产物：

| path | value |
| --- | --- |
| build log | `build/logs/xs/xs_wolf_grhsim_build_20260511_mux_branchless.log` |
| emu | `build/xs/grhsim/grhsim-compile/emu` |
| emu mtime | `2026-05-11 22:41 +0800` |
| emu file size | `118,048,136 B` |

CoreMark 50k perf 命令：

```bash
env -u EMU_RUNTIME_PROFILE EMU_PROGRESS_EVERY_CYCLES=0 \
  perf stat -o build/logs/xs_perf_mux_branchless/grhsim_basic.stat \
  -e cycles,instructions,branches,branch-misses,cache-references,cache-misses,duration_time,user_time,system_time \
  build/xs/grhsim/grhsim-compile/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 50000
```

运行结果正常到达 cycle limit：

| 指标 | value |
| --- | ---: |
| guest cycle spent | `50,001` |
| core cycleCnt | `49,996` |
| guest instrCnt | `73,580` |
| guest IPC | `1.471718` |
| end PC | `0x80001312` |
| host time from emu | `376,883 ms` |

## 5. 静态二进制变化

对比对象为 `NO0089` 中同一 GrhSIM 口径。

| 静态计数 | NO0089 GrhSIM | branchless mux | change |
| --- | ---: | ---: | ---: |
| file size | `120,235,400 B` | `118,048,136 B` | `-1.82%` |
| `.text` | `119,902,985 B` | `111,926,335 B` | `-6.65%` |
| all instructions | `23,189,727` | `22,651,890` | `-2.32%` |
| memory-form instructions | `9,852,681` | `9,546,250` | `-3.11%` |
| branch/control-flow instructions | `1,553,168` | `968,670` | `-37.63%` |

Top mnemonic 变化：

| rank | NO0089 GrhSIM | count | branchless mux | count |
| ---: | --- | ---: | --- | ---: |
| 1 | `mov` | `4,257,231` | `mov` | `4,187,686` |
| 2 | `or` | `3,068,566` | `or` | `2,981,532` |
| 3 | `movzx` | `2,479,953` | `movzx` | `2,384,241` |
| 4 | `cmp` | `1,951,283` | `and` | `1,728,087` |
| 5 | `and` | `1,737,985` | `cmp` | `1,657,533` |
| 6 | `setne` | `1,417,742` | `setne` | `1,293,226` |
| 7 | `xor` | `1,231,425` | `xor` | `1,253,991` |
| 8 | `je` | `865,629` | `test` | `785,741` |
| 9 | `test` | `784,418` | `je` | `614,049` |
| 10 | `shl` | `582,162` | `shl` | `567,070` |

静态 `je` 从 `865,629` 降到 `614,049`，与 branch/control-flow 总量下降一致。

## 6. Perf 基础事件变化

对比对象为 `NO0089` 中 `build/logs/xs_perf_no0089/grhsim_basic.stat`。

| perf 指标 | NO0089 GrhSIM | branchless mux | change |
| --- | ---: | ---: | ---: |
| elapsed time | `388.740922 s` | `376.894818 s` | `-3.05%` |
| cycles | `2,230,633,160,497` | `2,164,479,349,428` | `-2.97%` |
| instructions | `288,645,501,546` | `300,934,575,320` | `+4.26%` |
| IPC | `0.129` | `0.139` | improved |
| branches | `34,333,402,633` | `29,023,470,352` | `-15.47%` |
| branch misses | `16,137,579,459` | `12,345,101,414` | `-23.50%` |
| branch miss rate | `47.00%` | `42.53%` | `-4.47pp` |
| cache references | `100,733,228,073` | `91,315,909,039` | `-9.35%` |
| cache misses | `48,326,827,011` | `46,712,466,312` | `-3.34%` |
| cache miss rate | `47.98%` | `51.15%` | `+3.17pp` |
| host time from emu | `388,730 ms` | `376,883 ms` | `-3.05%` |

归一到 guest cycle：

| 指标 | NO0089 GrhSIM | branchless mux | change |
| --- | ---: | ---: | ---: |
| host retired instructions / guest cycle | `5,772,795` | `6,018,570` | `+4.26%` |
| host branches / guest cycle | `686,655` | `580,458` | `-15.47%` |
| host branch misses / guest cycle | `322,745` | `246,902` | `-23.50%` |

相对 `NO0089` GSim：

| perf 指标 | GSim | branchless mux GrhSIM | GrhSIM / GSim |
| --- | ---: | ---: | ---: |
| elapsed time | `34.089382 s` | `376.894818 s` | `11.055x` |
| cycles | `193,974,522,338` | `2,164,479,349,428` | `11.159x` |
| instructions | `80,041,267,210` | `300,934,575,320` | `3.760x` |
| branches | `4,518,767,074` | `29,023,470,352` | `6.423x` |
| branch misses | `1,857,682,250` | `12,345,101,414` | `6.645x` |

## 7. 结论

本轮优化有效：

- `kMux` 从 C++ `?:` 改为 mask-select 后，静态 branch/control-flow 降低 `37.63%`；
- CoreMark 50k 动态 branches 降低 `15.47%`，branch misses 降低 `23.50%`；
- host time / elapsed time 均提升约 `3.05%`；
- `.text` 下降 `6.65%`，静态总指令下降 `2.32%`，没有出现二进制静态膨胀。

主要代价：

- dynamic retired instructions 增加 `4.26%`。原因是 mask-select 会让 true/false 两侧表达式都被求值，而旧 `?:` 可在部分点只走一侧。

当前判断：

- 对 GrhSIM 当前 branch-pressure 特征而言，mux branchless 是正收益优化；
- 该优化比 `NO0083` 的 changed-activation branchless 更适合保留，因为它没有显著增加静态 code footprint，也没有改变 fixed-point 激活轨迹；
- 后续若继续推进 branchless，应优先选择 mux 这类纯数据选择语义明确、无 side effect、不会改变 activation 收敛行为的点，而不是全量替换 changed-check / active-bitset 更新。

