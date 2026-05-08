# NO0076 XS GSim / GrhSIM Supernode Activation Stats Snapshot

> 归档编号：`NO0076`。目录顺序见 [`README.md`](./README.md)。
>
> 本文档只保留本轮复核后的最终结论：
>
> - `supernode` 总数
> - `supernode` 间 `boundary_activation_edges`
> - `grhsim cloned source / compute op` 与 `gsim ref / non-ref enode` 的对比

## 1. 复核口径

本次以 2026-05-08 重跑产物为准。

数据来源：

- `gsim`
  - [`../../build/xs/gsim/gsim-compile/model/SimTop_supernode_stats.json`](../../build/xs/gsim/gsim-compile/model/SimTop_supernode_stats.json)
- `grhsim`
  - [`../../build/xs/grhsim/grhsim_emit/activity_schedule_supernode_stats.json`](../../build/xs/grhsim/grhsim_emit/activity_schedule_supernode_stats.json)
  - [`../../build/logs/xs/xs_wolf_grhsim_build_20260508_no0076_recheck.log`](../../build/logs/xs/xs_wolf_grhsim_build_20260508_no0076_recheck.log)
  - [`../../build/xs/grhsim/wolvrix_xs_post_stats.json`](../../build/xs/grhsim/wolvrix_xs_post_stats.json)

对齐关系固定为：

- `grhsim cloned source op` 对应 `gsim ref enode`
- `grhsim compute op` 对应 `gsim non-ref enode`

其中：

- `grhsim cloned source op`
  - 取 `activity-schedule timing detail` 中的 `source_clones_in_compute_nodes`
- `grhsim compute op`
  - 按 [`../../wolvrix/lib/transform/activity_schedule.cpp`](../../wolvrix/lib/transform/activity_schedule.cpp) 中 `classifyActivityOp(...)` 口径重算
  - `Source = {kConstant, kRegisterReadPort, kLatchReadPort}`
  - `Sink = {kRegisterWritePort, kLatchWritePort, kMemoryWritePort, kMemoryFillPort}`
  - `Declaration = {kRegister, kMemory, kLatch, kDpicImport}`
  - `Compute = total - Source - Sink - Declaration - HierLike`
- `gsim ref enode`
  - 取 `enode_node_ref_count`
- `gsim non-ref enode`
  - 取 `enode_unique_count - enode_node_ref_count`

## 2. 最终结论

### 2.1 `supernode` 数量

| 指标 | `gsim` | `grhsim` | 差异 |
| --- | ---: | ---: | ---: |
| `supernodes` | `84714` | `84257` | `-457` (`-0.54%`) |

### 2.2 `supernode` 间激活边

| 指标 | `gsim` | `grhsim` | 差异 |
| --- | ---: | ---: | ---: |
| `boundary_activation_edges` | `1378665` | `2346640` | `+967975` (`+70.21%`) |

### 2.3 `ref/non-ref enode` vs `cloned source/compute op`

本次复核后的准确数值：

| 指标 | 数值 |
| --- | ---: |
| `grhsim cloned source ops` | `2234939` |
| `grhsim compute ops` | `4390655` |
| `gsim ref enodes` | `8793011` |
| `gsim non-ref enodes` | `5018941` |

对应比值：

| 对齐项 | `gsim` | `grhsim` | 比值 |
| --- | ---: | ---: | ---: |
| `ref/cloned-source` | `8793011` | `2234939` | `3.93x` |
| `non-ref/compute` | `5018941` | `4390655` | `1.14x` |

## 3. 结论摘要

本轮重跑复核后，最终只保留以下事实：

1. `supernode` 数量已经基本对齐：
   - `gsim = 84714`
   - `grhsim = 84257`

2. `boundary_activation_edges` 仍然显著偏大：
   - `gsim = 1378665`
   - `grhsim = 2346640`

3. 在指定对齐关系下：
   - `grhsim cloned source ops = 2234939`
   - `gsim ref enodes = 8793011`
   - `ref / cloned-source = 3.93x`
   - `grhsim compute ops = 4390655`
   - `gsim non-ref enodes = 5018941`
   - `non-ref / compute = 1.14x`
