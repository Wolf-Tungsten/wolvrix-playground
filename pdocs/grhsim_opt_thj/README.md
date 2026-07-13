# grhsim_opt_thj 文档索引

本目录采用增量式文档管理，规则见 [`RULES.md`](./RULES.md)。

`TNO0001..TNO0020` 是对 `pdocs/grhsim_opt` 中 `NO0221..NO0526` 共 306 篇细粒度记录的主题化整理。原始 NO 文档保持不变并继续作为详细实验档案；后续 GrhSIM 优化文档只在本目录按 TNO 编号新增。

## 当前文档顺序

下表按“记录日期优先、同日按依赖关系与阅读顺序判定”的规则整理当前已有文档。

| 编号 | 记录日期 | 文档 | 说明 |
| --- | --- | --- | --- |
| `TNO0001` | `2026-07-13` | [Small-load baseline and analysis method](./TNO0001_small_load_baseline_and_analysis_method_20260713.md) | 整理 `NO0221..NO0223`：恢复 plain BAE 基线，建立 BigComb/xs-components 小负载 codegen、perf、profile 与汇编分析方法。 |
| `TNO0002` | `2026-07-13` | [VtypeBuffer codegen and active-framework diagnosis](./TNO0002_vtypebuffer_codegen_and_active_framework_diagnosis_20260713.md) | 整理 `NO0224..NO0239`：宽字 helper 优化、phase/edge 语义、动态 fire 与 active/change propagation 根因。 |
| `TNO0003` | `2026-07-13` | [Full-pass specialization and event settle](./TNO0003_fullpass_specialization_and_event_settle_20260713.md) | 整理 `NO0240..NO0254`：input/posedge full-pass、SimTop event 顺序修复与 adaptive post-commit settle。 |
| `TNO0004` | `2026-07-13` | [SimTop commit, state-read, and PHR optimization](./TNO0004_simtop_commit_state_read_and_phr_optimization_20260713.md) | 整理 `NO0255..NO0269`：同 FIR profile、全掩码 commit、state-read 复用、PHR true-merge、broadcast 与 active scan。 |
| `TNO0005` | `2026-07-13` | [Array true-merge expansion](./TNO0005_array_true_merge_expansion_20260713.md) | 整理 `NO0270..NO0280`：TAGE、ROB edge-padded 与 DCache/LLPTW OR-decoded true-merge 及其性能闭环。 |
| `TNO0006` | `2026-07-13` | [Same-FIR gap, state alias, and commit layout](./TNO0006_same_fir_gap_state_alias_and_commit_layout_20260713.md) | 整理 `NO0281..NO0290`：剩余 GSim gap、state-read alias、commit unlikely 和 RenameTable write-only merge 失败。 |
| `TNO0007` | `2026-07-13` | [Ordered memory write and affine loop](./TNO0007_ordered_memory_write_and_affine_loop_20260713.md) | 整理 `NO0291..NO0303`：ordered-write 契约、rank 修复、affine loop 与最终 runtime/profile 结论。 |
| `TNO0008` | `2026-07-13` | [Final-topology ordering experiments](./TNO0008_final_topology_ordering_experiments_20260713.md) | 整理 `NO0304..NO0308`：`level-op` 与 GSim-like `ready-op` 排序实验均未改善跨版本 batch 对齐。 |
| `TNO0009` | `2026-07-13` | [Ordered-write dynamic work and frontend PMU diagnosis](./TNO0009_ordered_write_dynamic_work_and_frontend_pmu_diagnosis_20260713.md) | 整理 `NO0309..NO0328`：排除动态 work、cache/TLB/redirect/op-cache 后，将随机基址下回退定位到前端供给与布局。 |
| `TNO0010` | `2026-07-13` | [Code layout, ASLR, and fixed profile](./TNO0010_code_layout_aslr_and_fixed_profile_20260713.md) | 整理 `NO0329..NO0349`：页对齐、object 顺序、PIE/ASLR 勘误、fixed-ASLR 重测与最新 GSim/GrhSIM instruction profile。 |
| `TNO0011` | `2026-07-13` | [Direct state-read implementation and native gate](./TNO0011_direct_state_read_implementation_and_native_gate_20260713.md) | 整理 `NO0350..NO0367`：single-writer direct forwarding 的诊断、实现、SimTop 功能闭环及 native layout 回退。 |
| `TNO0012` | `2026-07-13` | [Direct state-read layout control and final profile](./TNO0012_direct_state_read_layout_control_and_final_profile_20260713.md) | 整理 `NO0368..NO0388`：4 KiB/exact-entry 控制证明同址净收益约 `1.7%`，并闭合 compute8 state-read 指令收益。 |
| `TNO0013` | `2026-07-13` | [Scalar-read locality machine gate](./TNO0013_scalar_read_locality_machine_gate_20260713.md) | 整理 `NO0389..NO0402`：source 动态上界约 `32.8%`，但 O3 真实冗余只占 direct compute instructions `0.688%`，停止 typed-local。 |
| `TNO0014` | `2026-07-13` | [Compute machine attribution and active-word probe](./TNO0014_compute_machine_attribution_and_active_word_probe_20260713.md) | 整理 `NO0403..NO0414`：全局机器归因排除 mux/logic/deferred/helper 小项，full active-word consume 静态 probe 过 1% 门槛。 |
| `TNO0015` | `2026-07-13` | [Full active-word consume experiment](./TNO0015_full_active_word_consume_experiment_20260713.md) | 整理 `NO0415..NO0434`：实现与功能正确，但 native 和 exact-entry runtime 均回退约 2%，方案停止。 |
| `TNO0016` | `2026-07-13` | [Commit, true-merge, and boundary audits](./TNO0016_commit_true_merge_and_boundary_audits_20260713.md) | 整理 `NO0435..NO0447`：commit array gap 过门槛，但 reset-mux、剩余 read 与 assign forwarding 子类均不足 1%。 |
| `TNO0017` | `2026-07-13` | [Global compute residual closure](./TNO0017_global_compute_residual_closure_20260713.md) | 整理 `NO0448..NO0476`：scope-aware 归因后系统关闭 boolean、logic、concat、state/slot template 与 runtime-frame 候选。 |
| `TNO0018` | `2026-07-13` | [Event-pure word bypass development](./TNO0018_event_pure_word_bypass_development_20260713.md) | 整理 `NO0477..NO0494`：从 side-effect/event guard 负向探针收敛到 pure-event whole-word bypass 与动态 profile 实现。 |
| `TNO0019` | `2026-07-13` | [SimTop pure-event profile and plain bypass](./TNO0019_simtop_pure_event_profile_and_plain_bypass_20260713.md) | 整理 `NO0495..NO0509`：107 words 的动态 miss 机会闭合，plain bypass 功能正确但 batch27 codegen cliff 且正式 runtime 被负载阻断。 |
| `TNO0020` | `2026-07-13` | [Sparse pure-event codegen and legal packing](./TNO0020_sparse_pure_event_codegen_and_legal_packing_20260713.md) | 整理 `NO0510..NO0526`：threshold-2 修复 batch27，hybrid 功能正确；高负载性能无效，legal packing 静态候选新增 `119/6675` samples。 |

## 来源覆盖

- 初始整理范围：`NO0221..NO0526`。
- 原始记录数：`306`。
- TNO 主题文档数：`20`。
- 各 TNO 的来源范围连续、互不重叠，合并后完整覆盖 306 个原编号。
- 详细原始记录继续保存在 [`../grhsim_opt`](../grhsim_opt/README.md)，本目录不复制或改写原文件。
