# NO0067 Batch 粗化实验：CoreMark 50k 性能未提升（2026-05-03）

> 归档编号：`NO0067`。目录顺序见 [`README.md`](./README.md)。

## 1. 目的

验证"调度粒度过碎"（1175 个 batch vs gsim 166 个 subStep）是否是当前 grhsim 比 gsim 慢约 30 倍的主因。

## 2. 实验方法

### 2.1 改动内容

通过环境变量抬高 `sched_batch_max_ops` / `sched_batch_max_estimated_lines`，压低 `sched_batch_target_count`，强制让 activity-schedule 生成更大、更少的 batch。

执行命令：

```bash
make xs_diff_clean RUN_ID=batch_coarsen_400

WOLVRIX_XS_GRHSIM_SCHED_BATCH_MAX_OPS=50000 \
WOLVRIX_XS_GRHSIM_SCHED_BATCH_MAX_ESTIMATED_LINES=100000 \
WOLVRIX_XS_GRHSIM_SCHED_BATCH_TARGET_COUNT=400 \
make xs_wolf_grhsim_emu RUN_ID=batch_coarsen_400

make run_xs_wolf_grhsim_emu RUN_ID=batch_coarsen_400 XS_SIM_MAX_CYCLE=50000
```

### 2.2 口径

- XiangShan `grhsim`
- `coremark-2-iteration.bin`
- `XS_SIM_MAX_CYCLE=50000`
- DiffTest 启用（与 nemu 对比）
- 直接读取 emu 日志中的 `Host time spent`

## 3. 实验结果

### 3.1 Batch 数量变化

| 指标 | 基线（NO0065） | 粗化实验 | 变化 |
|---|---|---|---|
| `sched_batch_max_ops` | 2048 | 50000 | **24.4×** |
| `sched_batch_max_estimated_lines` | 8192 | 100000 | **12.2×** |
| `sched_batch_target_count` | 800 | 400 | **0.5×** |
| `kBatchCount` | 1175 | **306** | **-74.0%** |
| `kSupernodeCount` | 76621 | 76621 | 不变 |
| 调度文件数（sched_*.cpp） | 1175 | **306** | **-74.0%** |

Batch 数量确实被成功压缩到了原来的约 **1/4**。

### 3.2 生成代码体量变化

| 指标 | 基线（NO0065） | 粗化实验 | 变化 |
|---|---|---|---|
| sched_*.cpp 总数 | 1175 | 306 | -74.0% |
| sched_*.cpp 总大小 | ~2.24 GiB | ~2.24 GiB | ~0% |
| 单个 sched 平均大小 | ~1.9 MiB | ~7.3 MiB | **+3.8×** |
| 最大单个 sched 文件 | ~5.0 MiB | **12.8 MiB** | **+2.6×** |
| sched_*.o 总大小 | — | ~178 MiB | — |

Batch 粗化后，总代码量几乎不变，但**文件集中度显著提高**。最大单个 cpp 从 5MB 膨胀到 12.8MB。

### 3.3 Emit 与编译耗时

| 指标 | 基线（NO0065） | 粗化实验 | 变化 |
|---|---|---|---|
| `write_grhsim_cpp` | 34811 ms | 27312 ms | **-21.5%**（emit 更快） |
| `emu` 二进制大小 | ~165 MiB | ~172 MiB | +4.2% |
| 用户体感编译速度 | — | **显著下降** | — |

注：用户反馈编译速度显著下降，与 emit 时间缩短形成反差，说明**编译期瓶颈从 emit 转移到了编译器前端**（大文件解析/优化）。

### 3.4 仿真性能（核心结论）

| 指标 | 基线（NO0065） | 粗化实验 | 变化 |
|---|---|---|---|
| `Host time spent` | **379910 ms** | **397823 ms** | **+17913 ms / +4.7%** |
| `Guest cycle spent` | 50001 | 50001 | 不变 |
| 仿真速度 | 131.61 cycles/s | 125.68 cycles/s | **-4.5%** |
| `Core-0 instrCnt` | 22484 | 22484 | 不变 |
| `cycleCnt` | 49996 | 49996 | 不变 |

**结果：batch 从 1175 粗化到 306 后，CoreMark 50k 的 host time 反而增加了约 4.7%。**

功能正确性：无 assertion、无 DiffTest mismatch、无 crash，正常结束。

## 4. 为什么粗化 batch 没有带来收益

### 4.1 框架开销不是主瓶颈

Batch 数量减少了 74%，但整机速度反而慢了。这说明：

- **空 batch 的 call/ret + active-word 检查不是当前热路径的主导成本**。
- 即使完全消除所有空 batch 的框架开销，也不足以抵消 batch 正文内部的其它成本。

### 4.2 大文件导致编译器优化退化

单个 sched 文件从 1.9MB 膨胀到 7.3MB（最大 12.8MB），带来了编译侧问题：

- 编译器前端解析时间增加。
- 大函数体内的寄存器分配和指令调度压力增大。
- 可能触发编译器的优化阈值（如内联预算、GVN 预算），导致生成代码质量下降。

从 `emu` 二进制大小从 165M 涨到 172M（+4.2%）也能侧面印证：代码生成形态发生了变化，但未必是更优的变化。

### 4.3 对反汇编假设的修正

此前基于反汇编推测"调度太碎 + 单条 op 太肥"是主因。本实验直接否定了"调度太碎"这一半：

- **batch 数量从 1175 压到 306，仿真速度没有回升，反而轻微下降。**
- 这意味着剩余的性能差距（仍然比 gsim 慢约 30 倍）**不能主要归因于 batch 调用密度**。

## 5. 已排除的结论

基于本轮实验，以下结论现在可以**正式排除**：

| 假设 | 结论 | 证据 |
|---|---|---|
| "1175 个 batch 的调度框架开销是 grhsim 慢 30 倍的主因" | ❌ 否 | batch 压缩 74% 后速度反而下降 4.7% |
| "只要 batch 数接近 gsim 的 166 个 subStep，就能追回数量级差距" | ❌ 否 | 306 个 batch（已接近 166 的 2 倍）仍未带来收益 |
| "空 batch 的 call/ret + active-word 扫描是 eval 热路径主导成本" | ❌ 否 | 空 batch 比例大幅下降，eval 整体未加速 |

## 6. 当前不能下的结论

以下结论目前仍**不能成立**，需继续验证：

- "主要瓶颈就是 op 级 `if (old!=new)` 分支膨胀"
- "主要瓶颈就是 commit phase 全局扫描框架"
- "主要瓶颈就是 value_storage_ref 的 reinterpret_cast"

## 7. 对后续工作的约束

1. **batch 粗化不应再作为有效优化主线。**
   - 方向是对的（减少调度碎片），但收益窗口已经关闭。
   - 继续扩大 batch 只会恶化编译时间和代码生成质量。

2. **后续若继续调 batch 参数，应以 1175 为参考基线，不应再大幅偏离。**
   - 当前默认的 `sched_batch_target_count=800` / `max_ops=2048` / `max_lines=8192` 已经是一个相对合理的局部最优。

3. **下一阶段的验证应转向 op 级代码生成形态。**
   - 既然 batch 框架不是主因，真正的差距应该在 batch 正文内部。
   - 建议优先验证：将 `if (old != new) { orb; orb; mov }` 改为 branchless 的 `-(uint8_t)cond & mask` 后，是否能带来可见收益。

4. **commit phase 的 touched-set 驱动改造仍需保留。**
   - 本实验未涉及 commit，NO0035 的采样数据仍然有效。
   - commit 框架（全局扫描 + tiny batch 派发）仍然是候选瓶颈之一。

## 8. 最终结论

截至 2026-05-03，batch 粗化实验的结论如下：

- **batch 数量从 1175 压缩到 306，功能正确，但 CoreMark 50k host time 回退约 4.7%。**
- **"调度粒度过碎"不能视为当前 grhsim 比 gsim 慢 30 倍的主因。**
- **优化重心应从"粗化 batch"移回"batch 正文降本"和"commit 框架重写"。**
