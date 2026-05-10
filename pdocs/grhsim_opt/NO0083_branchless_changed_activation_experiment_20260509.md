# NO0083 Branchless Changed Activation Experiment

> 2026-05-09 在 [`NO0082`](./NO0082_grhsim_helper_fastpath_perf_rerun_20260509.md) 之后，尝试把 scalar tracked value 的 `if (old != next) { activate; old = next; }` 改成 branchless mask activation。结果显示该方向能显著降低 branch / branch-miss，但当前粗粒度实现会增加太多 host instructions，最终 wall time 变慢。因此该实验已从源码回退，仅保留数据和结论。

## 实验改动

临时实现过的生成形态：

```cpp
const bool changed = old_value != next_value;
const std::uint8_t changed_mask =
    static_cast<std::uint8_t>(UINT8_C(0) - static_cast<std::uint8_t>(changed));
supernode_active_curr_[word] =
    static_cast<std::uint8_t>(supernode_active_curr_[word] | (mask & changed_mask));
old_value = next_value;
```

覆盖范围：

- 只覆盖非 event 的 scalar tracked value；
- event edge 仍走原 `grhsim_classify_edge(old, next)` 路径；
- wide words 和 commit state write 路径没有纳入这次实验。

验证：

- `cmake --build wolvrix/build --target emit-grhsim-cpp`: pass
- `ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'`: pass
- `xs_wolf_grhsim_emu` 重新构建成功
- `coremark 50k` 能跑到 cycle limit，没有 difftest 报错

## 产物

临时 branchless emu：

| path | timestamp | size |
| --- | --- | ---: |
| `build/xs/grhsim/grhsim-compile/emu` | `2026-05-09 20:32:52 +0800` | `146,060,256` |

运行日志：

- `build/logs/xs/xs_wolf_grhsim_branchless_20260509_2025_speed.log`
- `build/logs/xs_perf/grhsim_branchless_20260509_2025_basic.perf`
- `build/logs/xs_perf/grhsim_branchless_20260509_2025_basic.stdout`

## Speed

裸跑命令：

```bash
/usr/bin/time -v make --no-print-directory run_xs_wolf_grhsim_emu \
  XS_SIM_MAX_CYCLE=50000 \
  WOLVRIX_GRHSIM_PERF=0 \
  WOLVRIX_GRHSIM_WAVEFORM=0 \
  XS_WAVEFORM=0 \
  XS_COMMIT_TRACE=0 \
  XS_PROGRESS_EVERY_CYCLES=0 \
  RUN_ID=branchless_20260509_2025_speed
```

结果：

| metric | value |
| --- | ---: |
| host time from emu | `424,215 ms` |
| wall time | `7:04.23` |
| guest instrCnt | `73,628` |
| guest cycleCnt | `49,996` |
| guest IPC | `1.472678` |
| final PC | `0x800012f8` |

对比 `NO0082` 的 helper-fastpath baseline：

| metric | baseline | branchless experiment | change |
| --- | ---: | ---: | ---: |
| host time from emu | `414,257 ms` | `424,215 ms` | `+2.40%` |
| guest instrCnt | `73,087` | `73,628` | `+0.74%` |
| final PC | `0x800010ce` | `0x800012f8` | changed |

final PC / guest instrCnt 变化说明该实验改变了 fixed-point 激活/收敛行为的动态轨迹。它没有触发 difftest 错误，但不应在没有更细功能对齐分析前作为默认优化保留。

## Perf Stat

命令：

```bash
env -u EMU_RUNTIME_PROFILE EMU_PROGRESS_EVERY_CYCLES=0 \
  perf stat \
  -o build/logs/xs_perf/grhsim_branchless_20260509_2025_basic.perf \
  -e cycles,instructions,branches,branch-misses,cache-references,cache-misses,duration_time,user_time,system_time \
  -- build/xs/grhsim/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 50000
```

对比 `NO0082` baseline：

| metric | baseline | branchless experiment | change |
| --- | ---: | ---: | ---: |
| elapsed time | `414.315s` | `423.372s` | `+2.19%` |
| host cycles | `2,377,730,276,539` | `2,429,519,384,524` | `+2.18%` |
| host instructions | `254,317,990,363` | `301,927,326,128` | `+18.72%` |
| host IPC | `0.107` | `0.124` | improved |
| branches | `45,102,933,735` | `35,764,703,877` | `-20.70%` |
| branch misses | `23,219,880,268` | `17,440,876,067` | `-24.89%` |
| branch miss rate | `51.48%` | `48.77%` | `-2.71pp` |
| cache references | `115,331,074,887` | `106,902,419,713` | `-7.31%` |
| cache misses | `53,072,891,887` | `52,908,419,896` | `-0.31%` |
| cache miss rate | `46.02%` | `49.49%` | `+3.47pp` |

## 解释

这个实验验证了两个事实：

1. `changed-check` 分支确实是 branch / branch-miss 的重要来源

粗粒度 branchless 之后：

- branches 降低 `20.70%`
- branch misses 降低 `24.89%`

这比 helper fast path 更接近 `NO0082` 里定位的主瓶颈。

2. 当前实现方式代价过高

host instructions 增加 `18.72%`，最终 elapsed time 变慢 `2.19%`。原因主要是：

- 对大量单 fanout value 也生成 `changed_mask`；
- 每个 value update 都无条件写回 `old_value = next_value`；
- 每个 activation word 都无条件执行 `load/or/store`；
- 许多原本预测正确或低成本的分支也被替换成更多算术和 store。

对 `grhsim_SimTop_sched_859/860/861.cpp` 的简单统计显示，`changed_mask` 片段绝大多数只有 1 个 active-word OR，粗粒度 branchless 对这些点收益不足。

## 当前源码状态

本实验已从 `wolvrix/lib/emit/grhsim_cpp.cpp` 回退；源码保留的是 `NO0082` 的 helper fast path 版本。

回退后验证：

- `cmake --build wolvrix/build --target emit-grhsim-cpp`: pass
- `ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'`: pass

注意：`build/xs/grhsim/emu` 当前仍是临时 branchless 版本产物，若继续正式测速，需要重新构建 emu。

## 下一步

不要恢复这个逐 value branchless 版本。更合理的下一步是：

1. Batch-local active word 聚合

不要每个 changed 立即写 `supernode_active_curr_[word]`。应在 batch/word/chunk 局部维护 accumulator：

```cpp
std::uint8_t active_acc_word_14406 = 0;
if (changed_a) active_acc_word_14406 |= UINT8_C(1);
if (changed_b) active_acc_word_14406 |= UINT8_C(32);
...
supernode_active_curr_[14406] |= active_acc_word_14406;
```

这样仍保留 changed 分支，但减少全局 active bitset 的 load/or/store 密度，并为后续 selective branchless 提供聚合点。

2. Selective branchless

只对 fanout 较大、或同一 active word 内多次激活的 value 使用 branchless mask。单 fanout value 默认保留原 `if changed`。

3. Per active-word deferred OR

对同一个 active word 的多个 changed source，先聚合到局部变量，最后一次写回全局 active word。这个方向比当前实验更可能同时降低 branch miss 和 store traffic。

