# NO0021 Batch Merge Precise Dispatch 400 Target（2026-04-21）

> 归档编号：`NO0021`。目录顺序见 [`README.md`](./README.md)。

这份记录延续 [`NO0020`](./NO0020_batch_merge_precise_dispatch_50k_alignment_20260421.md) 的路线，将 `sched_batch_target_count` 进一步下调到 `400`，以验证在 384 核机器上是否能在编译并行度和运行性能之间取得更优平衡。

本轮结论可以先直接写在前面：

- 实际生成 batch 数 `432`，非常接近 400 目标，也与 384 核数量基本匹配
- 但 50k 运行速度从 `target=800` 时的 `109.15 cycles/s` 回退到 `92.83 cycles/s`
- 编译时间并未因 batch 减少而显著缩短（约 8m52s）
- **继续压低 batch 数到 400 附近对运行性能是负收益**，当前最优配置仍为 `target=800`（实际 887 batches）

## 数据来源

- 本轮 `50k` 运行日志：
  - `build/logs/xs/xs_wolf_grhsim_20260421_codex_targetbatch_400.log`
- 本轮 emitter / emu 构建日志：
  - `build/logs/xs/xs_wolf_grhsim_build_20260421_codex_targetbatch_400.log`
  - `build/logs/xs/experiment_20260421_codex_targetbatch_400.log`
- 当前生成产物中的 batch 规模：
  - `build/xs/grhsim/grhsim_emit/grhsim_SimTop.hpp`
- 对齐基线：
  - [`NO0011 当前 GrhSIM XiangShan CoreMark 50k Runtime Snapshot`](./NO0011_current_grhsim_xiangshan_coremark_50k_runtime_snapshot_20260420.md)
  - [`NO0020 Batch Merge Precise Dispatch 50k Alignment`](./NO0020_batch_merge_precise_dispatch_50k_alignment_20260421.md)

## 1. 本轮修改目标

用户提出：

- 测试机器只有 384 核
- `target=800` 时生成 887 个 batch，编译并行度可能无法完全利用（因为 `make -j 64` 限制）
- 希望降到 400 左右，观察是否能在保持运行性能的前提下，缩短编译时间或提升整体吞吐

本轮采取的实现策略与 `NO0020` 完全一致，仅修改环境变量：

```bash
export WOLVRIX_XS_GRHSIM_SCHED_BATCH_TARGET_COUNT=400
```

## 2. 当前 batch 规模

重新 emit 后，XiangShan 生成产物里可直接看到：

- `kActiveFlagWordCount = 9453`
- `kBatchCount = 432`
- schedule cpp 文件总数：`432`
- schedule cpp 总大小：`1.97 GB`
- schedule cpp 平均大小：`4.56 MB`

也就是说：

- batch 数已经压到了和 CPU 核数（384）同一量级
- 但单个 batch 函数的代码量显著膨胀（从 `target=800` 时的约 2.2MB 增长到 4.56MB）
- emit 耗时：约 `342s`（与之前 4662/1120/887 batches 版本基本持平）

## 3. 50k 结果：targetBatchCount = 400

复测命令：

```bash
make xs_wolf_grhsim_emu run_xs_wolf_grhsim_emu \
  RUN_ID=20260421_codex_targetbatch_400 \
  XS_SIM_MAX_CYCLE=50000 XS_COMMIT_TRACE=0 XS_PROGRESS_EVERY_CYCLES=5000
```

最终结果：

| 指标 | 数值 |
| --- | ---: |
| batch count | `432` |
| guest cycle spent | `50001` |
| host time spent | `538650 ms` |
| host simulation speed | `92.83 cycles/s` |
| guest instructions | `73580` |
| IPC | `1.471718` |
| build time (real) | `531.6 s` |

功能验证：

- 正常跑到 `50000-cycle` 上限
- 没有 diff mismatch
- 没有 assertion
- 没有 crash

## 4. 与历史版本对比

| 版本 | batch count | build time | host time | cycles/s | 相对 `NO0011` |
| --- | ---: | ---: | ---: | ---: | ---: |
| `NO0011` baseline | 未单独记录 | — | `560.738 s` | `89.17` | `baseline` |
| 4662 + immediate dispatch | `4662` | — | `495.347 s` | `100.94` | `+13.20%` |
| targetBatchCount=1000 | `1120` | — | `466.205 s` | `107.25` | `+20.28%` |
| targetBatchCount=800 | `887` | — | `458.089 s` | `109.15` | `+22.41%` |
| **targetBatchCount=400** | **`432`** | **`531.6 s`** | **`538.650 s`** | **`92.83`** | **`+4.1%`** |

从对比中可以清晰看到：

- `800 -> 400` 的过程中，batch 数继续减半，但**运行速度下跌了约 `15%`**（`109.15 -> 92.83 cycles/s`）
- 相比 `NO0011` baseline 仍有些许提升（`+4.1%`），但已远不如 `target=800/1000` 的收益
- 编译时间（约 8m52s）也没有因为 batch 减少而明显缩短

## 5. 为什么 target=400 反而变慢

本轮没有改动任何代码逻辑，唯一的变量是 `sched_batch_target_count`。性能回退的核心原因可以从以下角度解释：

### 5.1 单个 batch 函数体过大，编译器优化下降

| target | batches | avg cpp size | 函数体规模 |
| --- | ---: | ---: | --- |
| 800 | 887 | ~2.2 MB | 中等 |
| 400 | 432 | ~4.56 MB | 接近翻倍 |

当单个函数体超过一定规模后：

- Clang `-O3` 的寄存器分配、指令调度、内联启发式可能进入次优区间
- 基本块数量膨胀后，CFG 分析和优化 passes 的复杂度上升
- 代码生成质量下降，导致运行时 IPC 或 cache 效率降低

### 5.2 I-cache / I-TLB 压力增加

- 更少的 batch 意味着每个 batch 覆盖更多的 supernode
- 单次进入 batch 函数后执行的指令路径更长
- 但 supernode 激活是稀疏的，**一个 batch 内可能只有部分 supernode 真正活跃**
- 过长的函数体导致更多冷指令被加载到 I-cache，增加 cache miss 和 TLB miss

### 5.3 编译并行度的瓶颈不在 batch 数量

用户最初的假设是：384 核机器上，887 个 batch 可能无法充分利用并行编译。但实际观察：

- `make -j 64` 的编译限制已经远小于 384 核
- 即使 batch 数降到 432，编译时间并未缩短
- 说明编译瓶颈不在 batch 数量，而在 difftest/verilator 的串行部分、链接时间、或 `make -j 64` 本身

## 6. 结论与推荐配置

本轮实验证明：

1. **继续压低 batch 数到 400 附近对运行性能是负收益**
2. **编译时间并未因 batch 减少而显著改善**
3. 当前最优配置仍为 `WOLVRIX_XS_GRHSIM_SCHED_BATCH_TARGET_COUNT=800`（实际 887 batches，`109.15 cycles/s`）

**推荐配置（不变）：**

```bash
export WOLVRIX_XS_GRHSIM_SCHED_BATCH_TARGET_COUNT=800
```

如果追求编译速度与运行性能的平衡，可保留 `1000`（实际 1120 batches，`107.25 cycles/s`）。

**后续方向：**

- 如需进一步提升运行性能，不应再在 batch 合并上做文章（收益递减且已出现回退）
- 可考虑其他优化方向，例如：
  - 减少 `active flag word` 的扫描开销（目前 9453 words 每轮仍需顺序扫描）
  - 优化 batch 内部的数据局部性（按访问模式重排 supernode）
  - 探索更激进的 supernode coarsen 策略（而非仅仅合并 batch）
