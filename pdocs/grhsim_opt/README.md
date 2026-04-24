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
| `NO0008` | `2026-04-19` | [Activity-Schedule Topo 延后与 Supernode-DP 重构计划](./NO0008_activity_schedule_topo_refactor_plan_20260419.md) | 评估 `sink/tail` 对 topo 的真实依赖，并制定“DP 前只对 coarse supernode topo”的重构计划 |
| `NO0009` | `2026-04-19` | [Activity-Schedule Topo 重构后性能与 Supernode 结构画像](./NO0009_activity_schedule_topo_refactor_perf_and_supernode_profile_20260419.md) | 基于本轮实现后的 XiangShan `grhsim` 构建与运行日志，固化 `tail/coarsen` 热点、special partition 占比和 final supernode 重尾结构 |
| `NO0010` | `2026-04-19` | [当前 GrhSIM Supernode 图结构相对 GSim 的差异](./NO0010_current_grhsim_supernode_graph_vs_gsim_20260419.md) | 只看静态 supernode 图结构，聚焦“少点多边、接近 gsim 宽口径依赖图、hub 更重”的当前差异 |
| `NO0011` | `2026-04-20` | [当前 GrhSIM XiangShan CoreMark 50k Runtime Snapshot](./NO0011_current_grhsim_xiangshan_coremark_50k_runtime_snapshot_20260420.md) | 固化当前版本 `grhsim` 在 `XiangShan coremark` 上的 `50000-cycle` 运行结果、分段推进情况和 runtime 侧基线速度 |
| `NO0012` | `2026-04-20` | [当前 GrhSIM XiangShan CoreMark 30k Smoke Runtime Snapshot](./NO0012_current_grhsim_xiangshan_coremark_30k_smoke_runtime_snapshot_20260420.md) | 固化最近 emitter 调整之后的 `30000-cycle` bounded smoke run，记录稳定性、分段推进和当前 runtime 速度特征 |
| `NO0013` | `2026-04-20` | [当前 GrhSIM XiangShan CoreMark 50k Aligned Rerun](./NO0013_current_grhsim_xiangshan_coremark_50k_aligned_rerun_20260420.md) | 严格按 `NO0011` 的 `50000-cycle` 口径复测最近 emitter 修改后的版本，确认功能仍对齐，但 runtime 性能相对旧基线明显回退 |
| `NO0014` | `2026-04-20` | [Persistent Wide BitInt Storage 50k Alignment](./NO0014_persistent_wide_bitint_storage_50k_alignment_20260420.md) | 记录把宽 `persistent value/state` 切到 `_BitInt` 存储后的 `50k-cycle` 对齐复测，确认功能仍对齐，并回收了相对 `NO0013` 的部分性能回退 |
| `NO0015` | `2026-04-20` | [Remove BitInt Words-Only 50k Alignment](./NO0015_remove_bitint_words_only_50k_alignment_20260420.md) | 记录把宽值 `_BitInt` 路线完全移除、统一回到 pure words helper 后的 `50k-cycle` 对齐复测，确认功能仍对齐，并进一步优于 `NO0014` |
| `NO0016` | `2026-04-20` | [Disable Single-User Inline 50k Alignment](./NO0016_disable_single_user_inline_50k_alignment_20260420.md) | 记录在保持 words-only 路线不变时，仅关闭 single-user supernode local 内联并恢复显式 `local_value_` 后的 `50k-cycle` 对齐复测，确认功能仍对齐，但 runtime 相对 `NO0015` 再次回退 |
| `NO0017` | `2026-04-20` | [Current Words-Only Selective-Inline 59k Snapshot](./NO0017_current_words_selective_inline_59k_snapshot_20260420.md) | 固化当前“去掉 `_BitInt`、宽值保留必要 local value、只内联 cheap scalar”的语义状态，并记录对应的 XiangShan `59000-cycle` 运行快照 |
| `NO0018` | `2026-04-20` | [Pre-Coarsen State-Read Tail-Absorb Plan](./NO0018_pre_coarsen_state_read_tail_absorb_plan_20260420.md) | 记录把 `register/latch read` 的吸收复制前移到 `initialPartition` 之后、coarsen / DP 之前的实现计划，目标是消掉中间 read-head supernode |
| `NO0019` | `2026-04-20` | [GrhSIM Value/State Slot Static-Array Plan](./NO0019_grhsim_value_state_slot_static_array_plan_20260420.md) | 规划把生成头文件中的 `value` / `state` slot 从 `std::vector` 改为 `std::array`，并为 memory state 引入 row-aware 静态分桶 |
| `NO0020` | `2026-04-21` | [Batch Merge Precise Dispatch 50k Alignment](./NO0020_batch_merge_precise_dispatch_50k_alignment_20260421.md) | 记录 XiangShan batching 合并后的两轮 `50k` 复测，确认“全扫 batch”会导致回退，而“按 active word 即时派发”能在保持合批的同时把 `50k` 速度提升到 `100.94 cycles/s` |
| `NO0021` | `2026-04-21` | [Batch Merge Precise Dispatch 400 Target](./NO0021_batch_merge_precise_dispatch_400_target_20260421.md) | 延续 `NO0020` 将 `targetBatchCount` 降到 `400`（实际 432 batches）的实验，确认运行性能回退到 `92.83 cycles/s`，当前最优配置仍为 `800` |
| `NO0022` | `2026-04-21` | [GrhSIM Goto → `if (unlikely)` 分支提示优化](./NO0022_grhsim_goto_to_unlikely_branch_hint_20260421.md) | 将 grhsim 生成的活性跳过从 `goto` 改写为 `if (unlikely(...))` 包裹风格，50k 性能从 `109.15 cycles/s` 提升到 `115.42 cycles/s`（+5.74%） |
| `NO0023` | `2026-04-23` | [GrhSIM Compute-Commit Two-Phase Eval Plan](./NO0023_grhsim_compute_commit_two_phase_eval_plan_20260423.md) | 细化 `sink supernode` 覆盖核对与新的 `compute/commit` 双阶段 `eval` 方案，目标是移除不必要的 `commit shadow` 并保留单次 `eval` 内的 fixed-point 收敛语义 |
| `NO0024` | `2026-04-23` | [GrhSIM XiangShan Fresh Re-emit / Rebuild 50k Snapshot](./NO0024_grhsim_xiangshan_fresh_reemit_rebuild_50k_snapshot_20260423.md) | 记录一次从空 `grhsim` 产物开始的 fresh `emit -> build -> 50k` 复测，确认新 `emu` 可运行且功能正确，但本轮 runtime 含意外调试打印，速度值先视为污染下快照 |
| `NO0025` | `2026-04-23` | [GrhSIM Packed Value Storage Plan](./NO0025_grhsim_packed_value_storage_plan_20260423.md) | 规划把 `grhsim` emitter 中按类型/宽度分桶展开的 logic value storage 收敛为 packed arena，并用 `constexpr layout metadata + inline accessor` 取代分散字段与裸宏强转 |
| `NO0026` | `2026-04-24` | [GrhSIM Emit `.o` MTime Compile Tail Snapshot](./NO0026_grhsim_emit_o_mtime_compile_tail_snapshot_20260424.md) | 只用 `build/xs/grhsim/grhsim_emit` 下 `.o` 文件的 `mtime` 做一次拖尾排序快照，确认当前总墙钟时间主要被少量尾部 `sched_9xx` 和 `state_init_2.o` 拖长 |
| `NO0027` | `2026-04-24` | [GrhSIM Emit Real Compile Time Snapshot](./NO0027_grhsim_emit_real_compile_time_snapshot_20260424.md) | 在 `max_sink_supernode_op=768` 的 fresh re-emit 基础上，用 `clang + PCH + compile wrapper` 记录每个编译单元的真实编译耗时，确认当前最慢文件已扩散到一整段 `sched_9xx~13xx` 重尾，而不是只剩 `sched_945.cpp` |
| `NO0028` | `2026-04-24` | [GrhSIM Emit Tail Compile Root Cause](./NO0028_grhsim_emit_tail_compile_root_cause_20260424.md) | 继续剖析“长度相近但后段 `sched` 文件异常慢”的根因，确认主瓶颈是 `event guard + side effect + masked commit write` 叠加后触发 LLVM `GVNPass` / MemorySSA 退化，而不是头文件解析或纯文本长度 |
| `NO0029` | `2026-04-24` | [Sink Supernode Event Cluster Plan](./NO0029_sink_supernode_event_cluster_plan_20260424.md) | 细化“在 sink supernode 生成阶段按 event guard 聚类”的设计，目标是把 event guard 提升为外层统一分组条件，降低 guard 类型数、重复判断和 CFG 分裂，并为后续 guard-aware chunking 提供实施规则 |
| `NO0030` | `2026-04-24` | [Sched 124 LLVM IR / `GVN` + `MemoryDependence` Root Cause 与优化计划](./NO0030_sched124_llvm_ir_gvn_memdep_root_cause_20260424.md) | 针对 `grhsim_SimTop_sched_124.cpp` 做单文件 `clang++`、`gdb attach` 与 raw LLVM IR 分析，确认当前拖尾根因已经下沉到 `eval_batch_124` 的超大 IR、lambda thunk、`std::array::operator[]` 调用和 `GVN + MemoryDependence + TBAA alias` 组合爆炸 |

## 编号说明

- 现有 7 篇历史文档已在本次整理中统一重命名为 `NOxxxx_*.md`。
- 稳定编号以文件名、本文索引和各文档标题中的 `NOxxxx` 为准。
- 当前下一个可用记录编号为 `NO0031`。
