# grhsim_opt 文档索引

本目录采用增量式文档管理，规则见 [`RULES.md`](./RULES.md)。

## 当前文档顺序

下表按“记录日期优先、同日按依赖关系与阅读顺序判定”的规则整理当前已有文档。

| 编号 | 记录日期 | 文档 | 说明 |
| --- | --- | --- | --- |
| `NO0001` | `2026-04-18` | [GSim Default XiangShan CoreMark Baseline](./NO0001_gsim_default_xiangshan_coremark_baseline_20260418.md) | `gsim` baseline，后续 `grhsim` baseline 与性能对齐的基础输入 |
| `NO0002` | `2026-04-18` | [GrhSIM Default XiangShan CoreMark Baseline](./NO0002_grhsim_default_xiangshan_coremark_baseline_20260418.md) | `grhsim` baseline，对齐 `NO0001` 的 workload 与运行口径 |
| `NO0003` | `2026-04-18` | [GSim Default XiangShan Activation Instrumentation](./NO0003_gsim_default_xiangshan_activation_instrument_20260418.md) | `gsim` 机制级插桩记录 |
| `NO0004` | `2026-04-18` | [GrhSIM Default XiangShan 结构边与 Step 激活统计](./NO0004_grhsim_default_xiangshan_activation_instrument_20260418.md) | `grhsim` 机制级插桩记录 |
| `NO0005` | `2026-04-18` | [GSim vs GrhSIM CoreMark 性能特征对齐](./NO0005_gsim_grhsim_coremark_perf_alignment_20260418.md) | 基于 `NO0001` 与 `NO0002` 的性能对齐 |
| `NO0006` | `2026-04-18` | [GSim / GrhSIM Simulation Speed Tracking Snapshot](./NO0006_gsim_grhsim_sim_speed_tracking_20260418.md) | 基于 baseline 与性能对齐的速度快照 |
| `NO0007` | `2026-04-18` | [GSim / GrhSIM Supernode Edge-Step Tracking Snapshot](./NO0007_gsim_grhsim_supernode_edge_step_tracking_20260418.md) | 基于双边插桩结果的结构与 step/eval 跟踪 |

## 编号说明

- 现有 7 篇历史文档已在本次整理中统一重命名为 `NOxxxx_*.md`。
- 稳定编号以文件名、本文索引和各文档标题中的 `NOxxxx` 为准。
- 当前下一个可用记录编号为 `NO0008`。
