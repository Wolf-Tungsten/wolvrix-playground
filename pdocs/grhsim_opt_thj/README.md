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
| `TNO0021` | `2026-07-14` | [Current default baseline and Stage 1 refinement plan](./TNO0021_current_default_baseline_and_stage1_refinement_plan_20260714.md) | 固定当前 HEAD 默认 NO0300/fixed-ASLR 为唯一基线；规划 plain-seeded exact post-DP refinement，并将 BAE/DAG/compute pairs 改为软结构门槛、以 SimTop 50k 为最终裁决。 |
| `TNO0022` | `2026-07-14` | [Fresh current-default NO0300 baseline1](./TNO0022_fresh_current_default_no0300_baseline1_20260714.md) | Fresh 复现当前默认 NO0300 结构；CPU106/298 quiet fixed-ASLR 50k 功能与五事件 PMU 通过，固定为后续 activity-schedule A/B/A 的 `baseline1`。 |
| `TNO0023` | `2026-07-14` | [Stage 1 exact post-DP refinement and strict-r1 structure scan](./TNO0023_stage1_exact_post_dp_refinement_strict_r1_scan_20260714.md) | 实现 bounded exact BAE/DAG move/swap refinement；strict/r1 在 `4096` moves 下将 total BAE 降低 `1.1212%`、DAG 降低 `3.7821%`，已过结构 recount，尚待 SimTop runtime gate。 |
| `TNO0024` | `2026-07-14` | [Stage 1 mixed-policy structure scans](./TNO0024_stage1_mixed_policy_structure_scans_20260714.md) | 同一 current-default checkpoint 上完成 strict/balanced/bae-budget 扫描；三者 BAE 均下降约 `1.1%..1.2%`、DAG 均下降约 `3.5%..3.8%`，全部进入 runtime gate。 |
| `TNO0025` | `2026-07-14` | [Stage 1 candidate build and functional gates](./TNO0025_stage1_candidate_build_and_functional_gates_20260714.md) | 三种 policy 均完成 fresh O3 build 和 fixed-ASLR 100/10k/50k 功能门禁；generated C++ 与 `.text` 均下降，正式性能仍待 quiet A/B/A。 |
| `TNO0026` | `2026-07-14` | [Stage 1 generated-code static analysis](./TNO0026_stage1_generated_code_static_analysis_20260714.md) | 区分 batch relocation 与真实 work：候选 `.text` 下降约 `0.2%`、propagation entries 下降约 `1.4%`，但 commit/clock 表略退，仍须 50k 裁决。 |
| `TNO0027` | `2026-07-14` | [Stage 1 quiet-gate block and default decision](./TNO0027_stage1_quiet_gate_block_and_default_decision_20260714.md) | 外部负载使 formal quiet A/B/A 不成立；三候选功能/静态正向但不据此晋升，current-default 保持 `off`，保留后续安静重测入口。 |
| `TNO0028` | `2026-07-14` | [Stage 2 same-Kahn-level packing plan](./TNO0028_stage2_same_kahn_level_packing_plan_20260714.md) | 规划 coarsen 后、DP 前的 bounded same-level slot swap；保持拓扑、segment 数不增加、cap 与 1% moved-op 预算，并用 exact BAE/DAG 整候选裁决。已追加首轮门禁修正。 |
| `TNO0029` | `2026-07-14` | [Stage 2 Kahn packing implementation and structure gate](./TNO0029_stage2_kahn_packing_implementation_and_structure_gate_20260714.md) | 实现 bounded same-level swap；default-off identity 闭合，candidate SN `-75`、BAE `-0.014%`、DAG `+0.121%`，strict/balanced 回退，bae-budget 进入 50k。 |
| `TNO0030` | `2026-07-14` | [Stage 2 bae-budget build and functional gate](./TNO0030_stage2_bae_budget_build_and_functional_gate_20260714.md) | mixed candidate 完成 fresh O3 build 与 fixed-ASLR 100/10k/50k；功能 PASS，`.text -0.021%`，高负载 wall 不作性能结论。 |
| `TNO0031` | `2026-07-14` | [Stage 2 bae-budget quiet A/B/A](./TNO0031_stage2_bae_budget_quiet_aba_20260714.md) | CPU113/305、NUMA1 quiet A/B/A 有效；cycles `-0.324%` 低于 1% 门槛，standalone 接近中性且不晋升默认。 |
| `TNO0032` | `2026-07-14` | [Stage 2 bae-budget plus Stage 1 strict structure gate](./TNO0032_stage2_bae_plus_stage1_strict_structure_gate_20260714.md) | 组合保留 Stage 1 的 BAE/DAG 收益并减少 75 个 SN；相对 baseline BAE `-1.156%`、DAG `-3.748%`，进入完整 50k。 |
| `TNO0033` | `2026-07-14` | [Stage 2 combination runtime and default decision](./TNO0033_stage2_combination_runtime_and_default_decision_20260714.md) | 组合 fixed-ASLR quiet A/B/A 有效；instructions `-0.559%` 但 frontend empty `+11.461%`、cycles `+8.713%`，明确回退，Stage 1/2 均保持默认关闭。 |
| `TNO0034` | `2026-07-14` | [Stage 3 true local shared compute clone plan](./TNO0034_stage3_true_local_shared_compute_clone_plan_20260714.md) | 规划 bounded true graph clone，取代历史上会造 DAG 环的 ownership 吸收；限定 cheap pure/two-consumer/64-bit 与 0.5% clone 预算，最终仍由 fixed-ASLR 50k 裁决。 |
| `TNO0035` | `2026-07-14` | [Stage 3 true clone implementation and correctness](./TNO0035_stage3_true_clone_implementation_and_correctness_20260714.md) | 实现 mutation 前 snapshot、true op/value clone 与 full refreeze/rebuild；预算/owner/locality/commit/intent/cycle-split gates 和 focused/full tests 通过，默认关闭。 |
| `TNO0036` | `2026-07-14` | [Stage 3 explicit-off SimTop identity](./TNO0036_stage3_explicit_off_simtop_identity_20260714.md) | explicit false 的 SimTop stats 与 current-default 原始 JSON `cmp=0`，182 个叶子全同，确认 inactive path 不改变默认 NO0300 结构。 |
| `TNO0037` | `2026-07-14` | [Stage 3 standalone structure scan](./TNO0037_stage3_standalone_structure_scan_20260714.md) | conservative true clone 应用 108 个；BAE `-54`、DAG `-18`、boundary values `-64`，但 graph ops/values 各 `+108`、SN `+3`，继续 full 50k。 |
| `TNO0038` | `2026-07-14` | [Stage 3 full build and functional gate](./TNO0038_stage3_full_build_and_functional_gate_20260714.md) | full stats 复现；source/`.text` 分别 `-0.118%/-0.063%`，fixed-ASLR 100/10k/50k 功能全过，高负载 wall 不作性能结论。 |
| `TNO0039` | `2026-07-14` | [Stage 3 quiet A/B/A and default decision](./TNO0039_stage3_quiet_aba_and_default_decision_20260714.md) | atomic gate-to-run `6..7 ms` 的 quiet A/B/A 有效；cycles `+0.145%`、instructions `-0.078%`，低于 1% 线，判 neutral 并保持默认关闭。 |
| `TNO0040` | `2026-07-14` | [Stage 4 common-owner probe plan](./TNO0040_stage4_common_owner_probe_plan_20260714.md) | 规划 no-mutation 分桶，确认 third singleton common owner 的双边 operand locality/cap 机会；maxClones=0，未有证据前不放开 strict clone。 |
| `TNO0041` | `2026-07-14` | [Stage 4 common-owner probe implementation](./TNO0041_stage4_common_owner_probe_implementation_20260714.md) | 实现 off/probe 只读漏斗与全层参数绑定；focused identity/positive/reject 和独立 review 通过，exact eligible 明确为冲突选择前的上界。 |
| `TNO0042` | `2026-07-14` | [Stage 4 SimTop common-owner probe](./TNO0042_stage4_simtop_common_owner_probe_20260714.md) | raw stats identity；167,780 third-common 经 singleton/双边 locality/cap 后剩 691 exact upper-bound，projected pairs 1,382（总 BAE `0.0697%`）。 |
| `TNO0043` | `2026-07-14` | [Stage 5 common-owner strict plan](./TNO0043_stage5_common_owner_strict_plan_20260714.md) | 规划独立 common-owner clone/PPM budget、conflict-aware stable selection、transaction snapshot 与 full rebuild；local-owner maxClones=0 隔离变量。 |
| `TNO0044` | `2026-07-14` | [Stage 5 common-owner strict implementation](./TNO0044_stage5_common_owner_strict_implementation_20260714.md) | 实现独立budget、stable conflict/cap selection、snapshot/apply/full rebuild与graph/metadata/users/topo验证；focused和独立review通过。 |
| `TNO0045` | `2026-07-14` | [Stage 5 first strict commit-partition failure](./TNO0045_stage5_first_strict_commit_partition_failure_20260714.md) | 首次strict大图在candidate rewrite后触发commit partition equality硬失败；无final stats/50k，先增强set/order/partition差异诊断再取证。 |
| `TNO0046` | `2026-07-14` | [Stage 5 commit-order diagnostic and fix plan](./TNO0046_stage5_commit_order_diagnostic_and_fix_plan_20260714.md) | diagnostic2证实sink/input集合与normalized partition全等、仅node内顺序漂移；计划验证并复用baseline commit order，exact guard不放宽。 |
| `TNO0047` | `2026-07-14` | [Stage 5 fixed commit seed implementation](./TNO0047_stage5_fixed_commit_seed_implementation_20260714.md) | strict candidate rebuild 仅在 sink/input/grouping 验证全过后复用 baseline commit exact order；focused测试和binding重装通过，门禁未放宽。 |
| `TNO0048` | `2026-07-14` | [Stage 5 common-owner strict structure gate](./TNO0048_stage5_common_owner_strict_structure_gate_20260714.md) | fixed-seed SimTop scan应用555个clone；BAE `-0.0286%`、boundary `-279`、SN `-5`，DAG仅`+8`，结构温和并继续full 50k。 |
| `TNO0049` | `2026-07-14` | [Stage 5 full build and functional gate](./TNO0049_stage5_full_build_and_functional_gate_20260714.md) | full stats与scan完全一致；生成源码/`.text`无膨胀，fixed-ASLR 100/10k/50k功能全过，全量测试无新增失败。 |
| `TNO0050` | `2026-07-14` | [Stage 5 quiet A/B/A and default decision](./TNO0050_stage5_quiet_aba_and_default_decision_20260714.md) | atomic quiet A/B/A有效；cycles `+0.688%`、frontend/backend偏负，判neutral-to-mild-regression并保持common-owner strict默认关闭。 |

## 来源覆盖

- 初始整理范围：`NO0221..NO0526`。
- 原始记录数：`306`。
- 初始来源整理形成的 TNO 主题文档数：`20`。
- 当前记录类文档总数：`50`（`TNO0001..TNO0050`）。
- 各 TNO 的来源范围连续、互不重叠，合并后完整覆盖 306 个原编号。
- 详细原始记录继续保存在 [`../grhsim_opt`](../grhsim_opt/README.md)，本目录不复制或改写原文件。
