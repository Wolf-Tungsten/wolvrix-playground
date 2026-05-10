# NO0077 XS GSim / GrhSIM Runtime Profile CoreMark 50k

> 归档编号：`NO0077`。目录顺序见 [`README.md`](./README.md)。
>
> 本文档记录 2026-05-09 重新构建 `gsim` / `grhsim` emu 后，开启 `EMU_RUNTIME_PROFILE=1` 跑 XiangShan `coremark` 50k 的动态插桩结果。

## 1. 实验口径

本次不是静态图统计，而是运行时激活加权后的求解量：

- `gsim`
  - 每个 activated supernode 触发该 supernode 内所有 `node` 求解；
  - `ref_enodes` / `non_ref_enodes` 由生成期 per-supernode 静态计数乘以运行期激活次数累计。
- `grhsim`
  - runtime 区分 `compute_supernode` 与 `commit_supernode` 激活；
  - 每个 activated compute supernode 触发内部所有 compute node 求解；
  - `source_ops` / `compute_ops` / `sink_ops` 由生成期 per-supernode 静态计数乘以运行期激活次数累计。

运行 workload 固定为：

```text
testcase/xiangshan/ready-to-run/coremark-2-iteration.bin
--diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so
-b 0 -e 0 -C 50000
```

构建命令：

```bash
make --no-print-directory xs_gsim_emu RUN_ID=20260509_runtime_profile XS_VM_BUILD_JOBS=32
make --no-print-directory xs_wolf_grhsim_emu RUN_ID=20260509_runtime_profile XS_VM_BUILD_JOBS=32
```

运行命令等价于：

```bash
cd build/xs/gsim
EMU_RUNTIME_PROFILE=1 EMU_PROGRESS_EVERY_CYCLES=0 ./gsim-compile/emu \
  -i ../../../testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff ../../../testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 50000

cd build/xs/grhsim
EMU_RUNTIME_PROFILE=1 EMU_PROGRESS_EVERY_CYCLES=0 ./grhsim-compile/emu \
  -i ../../../testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff ../../../testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 50000
```

说明：`gsim` 运行时第一次尝试用 `tee` 写 `build/logs/xs/xs_gsim_20260509_runtime_profile.log`，但该重定向在当前执行环境里报 `Read-only file system`；emu 仍完整跑完，本文保留 stdout 中的原始 profile 行。

## 2. 构建期结构基准

本次 `gsim` emit 输出：

```text
cppEmitter: define 488167 nodes 84714 superNodes
```

本次 `grhsim activity-schedule` 输出：

```text
supernodes=115257 compute_supernodes=109173 commit_supernodes=6084
compute_nodes=1654394 source_clones=1640163 eligible_ops=4996771
```

这组构建期数据只用于解释 runtime profile 的乘数来源。真正比较性能差异时，下面的动态激活加权计数更关键。

## 3. 原始运行结果

### 3.1 `gsim`

```text
Core-0 instrCnt = 73584, cycleCnt = 49998, IPC = 1.471739
Seed=0 Guest cycle spent: 50001
Host time spent: 51797ms
[GSIM_RUNTIME_PROFILE] active_supernodes=766585701 nodes=35102411637 ref_enodes=114465246904 non_ref_enodes=66558858856 total_enodes=181024105760
```

### 3.2 `grhsim`

```text
Core-0 instrCnt = 73580, cycleCnt = 49996, IPC = 1.471718
Seed=0 Guest cycle spent: 50001
Host time spent: 438566ms
[GRHSIM_RUNTIME_PROFILE] active_supernodes=1440786355 compute_supernodes=945845917 commit_supernodes=494940438 compute_nodes=14397531265 source_ops=27856193149 compute_ops=52569735713 sink_ops=32631359162 total_ops=113057288024
```

两边都跑到 50k cycle limit。`instrCnt` / `IPC` 基本一致，可以把本轮数据视为同 workload、同仿真进度下的 runtime profile 对比。

## 4. 动态 profile 对比

| 指标 | `gsim` | `grhsim` | `grhsim / gsim` |
| --- | ---: | ---: | ---: |
| guest cycles | `50001` | `50001` | `1.000x` |
| host time | `51797 ms` | `438566 ms` | `8.467x` |
| cycles/s | `965.33` | `114.01` | `0.118x` |
| active supernodes | `766585701` | `1440786355` | `1.879x` |
| node / compute-node solves | `35102411637` | `14397531265` | `0.410x` |
| enode / op solves | `181024105760` | `113057288024` | `0.625x` |

按 cycle 归一化：

| 指标 | `gsim` | `grhsim` | `grhsim / gsim` |
| --- | ---: | ---: | ---: |
| active supernodes / cycle | `15331.41` | `28815.15` | `1.879x` |
| node / compute-node solves / cycle | `702034.19` | `287944.87` | `0.410x` |
| enode / op solves / cycle | `3620409.71` | `2261100.54` | `0.625x` |

按 activated supernode 归一化：

| 指标 | `gsim` | `grhsim` |
| --- | ---: | ---: |
| node solves / active supernode | `45.79` | - |
| enode solves / active supernode | `236.14` | `78.47` |
| compute nodes / compute supernode | - | `15.22` |
| ops / compute node | - | `7.85` |

`grhsim` supernode 激活拆分：

| 指标 | 数值 | 占比 |
| --- | ---: | ---: |
| compute supernode activations | `945845917` | `65.65%` |
| commit supernode activations | `494940438` | `34.35%` |

`gsim` enode 拆分：

| 指标 | 数值 | 占比 |
| --- | ---: | ---: |
| ref enode solves | `114465246904` | `63.23%` |
| non-ref enode solves | `66558858856` | `36.77%` |

`grhsim` op 拆分：

| 指标 | 数值 | 占比 |
| --- | ---: | ---: |
| source op solves | `27856193149` | `24.64%` |
| compute op solves | `52569735713` | `46.50%` |
| sink op solves | `32631359162` | `28.86%` |

## 5. 直接结论

这组动态数据把性能差异收窄到两个事实：

1. `grhsim` 的 active supernode 次数是 `gsim` 的 `1.879x`。
   - 这和 [`NO0076`](./NO0076_xs_gsim_grhsim_supernode_activation_stats_20260508.md) 中 `boundary_activation_edges` 偏多的静态结论一致；
   - 即使最终 supernode 数接近，`grhsim` 运行时仍触发了明显更多 supernode。

2. 仅看求解对象数量，`grhsim` 并没有更多。
   - compute-node solves 只有 `gsim node solves` 的 `0.410x`；
   - total op solves 只有 `gsim total enode solves` 的 `0.625x`；
   - 所以 `8.467x` host time 差异不能解释为“grhsim 动态求解了更多 op”。

更关键的倍率是单位求解对象成本：

| 指标 | `gsim` | `grhsim` | `grhsim / gsim` |
| --- | ---: | ---: | ---: |
| host ns / enode-or-op solve | `0.286` | `3.879` | `13.557x` |

因此，当前性能差距主要不是动态工作量总数偏大，而是 `grhsim` 每个 runtime op solve 的成本远高于 `gsim` 每个 enode solve 的成本。`active_supernodes` 的 `1.879x` 会放大调度/激活开销，但它不能单独解释 `8.467x` 总时间差；单位求解成本才是更大的主因。

## 6. 后续定位方向

基于本轮 profile，下一步不应继续只盯静态 supernode 数或 total op 数，而应拆 `grhsim` 单位 op 成本：

- `compute_supernode` 调度开销：
  - active compute supernode 达 `945845917` 次；
  - 每次平均只求解 `15.22` 个 compute node，可能导致函数调度、active bit 检查、batch 入口成本摊薄不足。
- `commit_supernode` 成本：
  - commit 激活占 `34.35%`；
  - sink op solves 占 `28.86%`，需要继续拆 register/latch/memory write。
- value/state 访问成本：
  - total op solves 少于 `gsim`，但单位成本高 `13.557x`；
  - 优先看 grhsim 生成代码里的 value load/store helper、宽值访问、active queue/bitset 操作是否压过了算术本身。
- compute node 粒度：
  - runtime 平均 `7.85 ops / compute node`；
  - 如果每个 compute node 都有独立边界值搬运、函数/分支/activation 管理，当前粒度可能不足以摊平外围成本。

一句话结论：`NO0076` 解释了为什么 `grhsim` runtime 会激活更多 supernode；本轮 `NO0077` 进一步说明，真正造成接近数量级差距的不是 total op solve 数，而是 grhsim 单位 op solve 的执行成本约为 gsim 的 `13.6x`。
