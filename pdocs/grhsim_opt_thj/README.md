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
| `TNO0051` | `2026-07-14` | [Stage 1 standalone quiet runtime closure](./TNO0051_stage1_standalone_quiet_runtime_closure_20260714.md) | 补齐此前被负载阻断的三policy正式包夹；cycles均回退`8.22%..8.87%`且frontend显著恶化，Stage1 family明确停止。 |
| `TNO0052` | `2026-07-15` | [Stage 6 targeted pure-event active-word pack plan](./TNO0052_stage6_targeted_pure_event_active_word_pack_plan_20260715.md) | 规划 emitter two-pass targeted packing：冻结 baseline batch/word slots，采用后完整重建 active-ID 派生结构；默认关闭，最终由 current-default NO0300 fixed-ASLR 50k 裁决。 |
| `TNO0053` | `2026-07-15` | [Stage 6 targeted pure-event pack implementation](./TNO0053_stage6_targeted_pure_event_pack_implementation_20260715.md) | 实现 off/probe/targeted two-pass emitter packing、strict validators/stats 与三层配置透传；余数/确定性/功能/error focused gates 全过，默认仍关闭。 |
| `TNO0054` | `2026-07-15` | [Stage 6 production probe and first targeted gate](./TNO0054_stage6_production_probe_and_first_targeted_gate_20260715.md) | 正确 source 环境下 production probe 精确复现 `107 -> 171` pure words、moved `256`；首次 targeted 被 batch 74 metadata gate 拦截，先增强 estimated-lines 差异诊断。 |
| `TNO0055` | `2026-07-15` | [Stage 6 frozen-batch cost-proxy fix](./TNO0055_stage6_frozen_batch_cost_proxy_fix_20260715.md) | 精确定位 batch 74 仅 `estimatedLines +6`；保留全部结构门禁，将 rebuilt line proxy 改为可观测统计，并新增稳定漂移 regression fixture。 |
| `TNO0056` | `2026-07-15` | [Stage 6 targeted build and functional gate](./TNO0056_stage6_targeted_build_and_functional_gate_20260715.md) | production targeted 通过并形成 171 pure words；schedule identity、O3 静态和 fixed-ASLR 100/10k/50k 功能门禁全部闭合。 |
| `TNO0057` | `2026-07-15` | [Stage 6 quiet runtime and default decision](./TNO0057_stage6_quiet_runtime_and_default_decision_20260715.md) | 两组独立 packing-only quiet A/B/A 均回退（cycles `+1.23%/+5.16%`），保持 pack 默认关闭；current-default 对 probe 的有效组合结果为 cycles `-11.41%`，另立采用阶段。 |
| `TNO0058` | `2026-07-15` | [Stage 7 hybrid XS-default adoption plan](./TNO0058_stage7_hybrid_xs_default_adoption_plan_20260715.md) | 规划仅在 XS 脚本默认开启 existing direct-state + threshold-2 bypass，保持全局 emitter 与 packing 默认关闭，并以 fresh identity/function/quiet 50k 决定是否采用。 |
| `TNO0059` | `2026-07-15` | [Stage 7 hybrid default implementation and fresh gates](./TNO0059_stage7_hybrid_default_implementation_and_fresh_gates_20260715.md) | XS 默认与显式回滚均完成 canonical fresh emit/O3；hybrid 精确复现 probe、rollback 去注释后精确回到 NO0300，100/10k/50k 功能全过，进入 quiet A/B/A。 |
| `TNO0060` | `2026-07-15` | [Stage 7 cross-socket runtime and default decision](./TNO0060_stage7_cross_socket_runtime_and_default_decision_20260715.md) | 四组 fresh A/B/A 显示 hybrid 在 NUMA0 cycles `+4.36%/+4.96%`、NUMA1 `-12.48%/-12.23%`；跨 socket 方向反转，不采用默认并恢复 NO0300，保留显式 XS direct 控制。 |
| `TNO0061` | `2026-07-15` | [Stage 8 plain-DP segment-penalty sweep plan](./TNO0061_stage8_plain_dp_penalty_sweep_plan_20260715.md) | 规划 current NO0300 plain DP 固定 penalty 的 `0.5/1.0/1.5/2.0` 双向扫描；默认 PPM 入口保持 `1.0` identity，允许温和结构退化并以 fixed-ASLR 50k 最终裁决。 |
| `TNO0062` | `2026-07-15` | [Stage 8 plain-DP segment-penalty structure scan](./TNO0062_stage8_plain_dp_penalty_structure_scan_20260715.md) | 四点结构扫描闭合 p100 raw identity；p050 以 compute SN `+177` 换 BAE `-177`，p200 以 BAE `+282` 换 compute SN `-143`，两端均继续 full emit/50k。 |
| `TNO0063` | `2026-07-15` | [Stage 8 penalty full build and functional gate](./TNO0063_stage8_penalty_full_build_and_functional_gate_20260715.md) | p050/p200 full stats 复现、fresh O3 build 与 fixed-ASLR 100/10k 均通过；`.text` 分别 `-0.080%/-0.042%`，两者继续跨 NUMA 50k。 |
| `TNO0064` | `2026-07-16` | [Stage 8 cross-NUMA runtime and default decision](./TNO0064_stage8_cross_numa_runtime_and_default_decision_20260716.md) | p050/p200 在 NUMA0 cycles 分别 `+7.21%/+11.69%`，NUMA1 分别 `-9.58%/-10.01%`；跨 socket 方向反转，不修改 `1000000 PPM` 默认并停止固定 penalty 细扫。 |
| `TNO0065` | `2026-07-16` | [Stage 9 common-source fanin pullback probe plan](./TNO0065_stage9_common_source_fanin_pullback_probe_plan_20260716.md) | 规划 final schedule no-mutation probe：识别小型纯 cone 的同源多输入，以 exact `N -> 1` value-pair gain、容量/冲突预算决定是否进入 strict pullback。 |
| `TNO0066` | `2026-07-16` | [Stage 9 fanin probe implementation and SimTop result](./TNO0066_stage9_fanin_probe_implementation_and_simtop_result_20260716.md) | off/probe raw identity 闭合；production probe 选中 84 个 1-bit pure cone，projected compute BAE `-254`、moved ops `262`，进入 strict move。 |
| `TNO0067` | `2026-07-16` | [Stage 9 fanin probe full regression gate](./TNO0067_stage9_fanin_probe_full_regression_gate_20260716.md) | 完整 rebuild 后全量 CTest `46/48`；activity/emitter/ingest 均通过，仅保留两个既有失败，probe 阶段可提交。 |
| `TNO0068` | `2026-07-16` | [Stage 10 fanin pullback strict plan](./TNO0068_stage10_fanin_pullback_strict_plan_20260716.md) | 基于 84 个 exact candidate 规划完整 compute-node move、final 派生数据重建与强不变量 gate；目标 compute/total BAE 精确 `-254` 且 SN/DAG/topo/commit 全同。 |
| `TNO0069` | `2026-07-16` | [Stage 10 fanin pullback strict implementation and structure gate](./TNO0069_stage10_fanin_pullback_strict_implementation_and_structure_gate_20260716.md) | strict 应用 84 个完整 compute-node move；11 项 validator 全过，compute/total BAE 精确 `-254`，SN/DAG/topo/compute-commit 不变，进入 full 50k。 |
| `TNO0070` | `2026-07-16` | [Stage 10 fanin pullback strict full regression gate](./TNO0070_stage10_fanin_pullback_strict_full_regression_gate_20260716.md) | 完整 build 通过，CTest `46/48` 且无新增失败；activity-schedule 与 292.89 秒 emitter 长测均通过，仅保留两个既有失败。 |
| `TNO0071` | `2026-07-16` | [Stage 10 fanin pullback strict full build and functional gate](./TNO0071_stage10_fanin_pullback_strict_full_build_and_functional_gate_20260716.md) | full emit 精确复现 BAE `-254`；O3/link 与 fixed-ASLR 100/10k 功能通过，`.text +0.0055%`，进入跨 NUMA 50k。 |
| `TNO0072` | `2026-07-16` | [Stage 10 fanin pullback strict cross-NUMA runtime](./TNO0072_stage10_fanin_pullback_strict_cross_numa_runtime_20260716.md) | quiet A/B/A：NUMA0 cycles `-0.0903%`，NUMA1 `+0.7464%` 且 frontend 约 `+0.94%`；判 neutral-to-mild-regression，默认保持 off。 |
| `TNO0073` | `2026-07-16` | [Stage 10 same-poststats control correction plan](./TNO0073_stage10_same_poststats_control_correction_plan_20260716.md) | 发现 Stage7 config-equivalent control 与 strict 的 source-clone op ID/layout provenance 漂移；规划同 post-stats/current-code explicit-off 控制重测，TNO0072 因果结论暂降级。 |
| `TNO0074` | `2026-07-16` | [Stage 10 same-poststats corrected runtime](./TNO0074_stage10_same_poststats_corrected_runtime_20260716.md) | corrected quiet A/B/A：NUMA0 cycles `-8.7636%`、NUMA1 `+9.4387%`，instructions 均 `-0.02675%`；确认 layout socket 反转，strict 默认保持 off。 |
| `TNO0075` | `2026-07-16` | [Stage 11 equal-load swap-only probe plan](./TNO0075_stage11_equal_load_swap_probe_plan_20260716.md) | 规划 plain-DP 后 `swap-probe`：只量化 equal-op、DAG-support/topo/active-ID exact 的 capacity-blocked swap，补测 Stage1 被 4096 普通 move 预算饿死的路径。 |
| `TNO0076` | `2026-07-16` | [Stage 11 equal-load swap probe implementation and production result](./TNO0076_stage11_equal_load_swap_probe_implementation_and_production_result_20260716.md) | 实现 no-mutation、资源有界的 swap probe；production 完整枚举 `3,417,492` 个 RHS 后 exact eligible 为 `0`，不进入 strict/CPP/50k。 |
| `TNO0077` | `2026-07-16` | [Stage 11 equal-load swap probe full regression gate](./TNO0077_stage11_equal_load_swap_probe_full_regression_gate_20260716.md) | 完整 rebuild 与 CTest `46/48`；activity/emitter/ingest 通过，仅保留两个既有失败，Stage 11 可提交。 |
| `TNO0078` | `2026-07-16` | [Stage 12 commit guard merge-cap sweep plan](./TNO0078_stage12_commit_guard_merge_cap_sweep_plan_20260716.md) | 规划以 default 4096 commit partition 为有序基础，只合并同 event 相邻完整节点，补扫历史未覆盖的 `8192/16384/32768` cap 与 current 50k。 |
| `TNO0079` | `2026-07-16` | [Stage 12 commit guard merge-cap implementation and structure scan](./TNO0079_stage12_commit_guard_merge_cap_implementation_and_structure_scan_20260716.md) | default SHA identity；高 cap runs `485→468/459/455`、compute-commit pairs 最多 `-2243`，三点均进入 full CPP/O3/50k。 |
| `TNO0080` | `2026-07-16` | [Stage 12 commit guard merge-cap full build and functional gate](./TNO0080_stage12_commit_guard_merge_cap_full_build_and_functional_gate_20260716.md) | 三档 full emit/O3 与 100/10k 功能全过；最大 CPP 不膨胀、`.text` 均下降，全部进入 fixed-ASLR 跨 NUMA 50k。 |
| `TNO0081` | `2026-07-16` | [Stage 12 commit guard merge-cap cross-NUMA runtime](./TNO0081_stage12_commit_guard_merge_cap_cross_numa_runtime_20260716.md) | 8192/32768 出现 socket 方向反转，16384 双 socket 回退；instructions 也不随 BAE 单调改善，默认保持 4096 并停止全局 cap 粗扫。 |
| `TNO0082` | `2026-07-16` | [Stage 12 commit guard merge-cap full regression gate](./TNO0082_stage12_commit_guard_merge_cap_full_regression_gate_20260716.md) | 完整 rebuild/CTest `46/48`；activity 与 emitter 长测通过，失败集合与 Stage 11 完全相同，无新增回归。 |
| `TNO0083` | `2026-07-16` | [Stage 13 partition-stable commit locality plan](./TNO0083_stage13_partition_stable_commit_locality_plan_20260716.md) | 定位 high-cap 引起 63.56% value-slot 改号的 supernode-anchor 根因；规划导出 4096 canonical locality group，保持 default layout 并隔离 commit coarsening。 |
| `TNO0084` | `2026-07-16` | [Stage 13 anchor-only production gate and order correction](./TNO0084_stage13_anchor_only_production_gate_and_order_correction_20260716.md) | default 全源码 identity；high-cap slot 漂移降至 1.26%..1.54% 但未清零，定位 actual commit first-read 顺序并转入 canonical group topo 修正。 |
| `TNO0085` | `2026-07-16` | [NUMA file-page locality diagnosis and controlled runtime protocol](./TNO0085_numa_file_page_locality_diagnosis_and_protocol_20260716.md) | 正式绑定语法正确，但 NFS file-backed text 不随 `membind` 迁移；双 inode 矩阵测得远端 file set 慢 `2.79%/3.48%`，后续 50k 增加 placement 与全 CCD gate。 |
| `TNO0086` | `2026-07-16` | [Stage 13 canonical commit order full gate](./TNO0086_stage13_canonical_commit_order_full_gate_20260716.md) | canonical group topo 与 groupCount 防御闭合；default 154 源文件 identity，三档 high-cap typed-slot changed/missing/extra/type-changed 全 `0`，O3/功能通过并进入 page-local 50k。 |
| `TNO0087` | `2026-07-16` | [Correct page-local Stage 7/8 runtime](./TNO0087_page_local_stage7_stage8_corrected_runtime_20260716.md) | 双 node 独立 inode、镜像核和全 CCD monitor 下重测：hybrid 两边提升约 `4.3%`，p050 中性、p200 轻退，旧 socket 反转结论失效；same-post 尚在运行。 |
| `TNO0088` | `2026-07-16` | [Stage 13 full regression gate](./TNO0088_stage13_full_regression_gate_20260716.md) | 完整 build PASS、串行 CTest `46/48`；activity/emitter 长测通过，仅保留与 Stage 11/12 相同的 comb-lane-pack/repcut 既有失败，无新增回归。 |
| `TNO0089` | `2026-07-17` | [Page-local Stage 12/13 interim runtime and strict NUMA protocol](./TNO0089_page_local_stage12_stage13_interim_runtime_and_strict_numa_protocol_20260717.md) | 归档 cap32768/cap8192 的有效 raw A/B/A 与 control 漂移；确认只监控 CCD 不足，协议升级为整 node 30 秒 gate、运行期 monitor 和平衡 AB/BA 重复，Stage 13 最终结论待补。 |
| `TNO0090` | `2026-07-17` | [Stage 14 native hybrid default adoption plan](./TNO0090_stage14_native_hybrid_default_adoption_plan_20260717.md) | 基于 corrected page-local 双 node 约 `4.3%` cycles 收益，规划将 direct-state 与 pure-event bypass 成对迁为 C++ native defaults；XS 改为 tri-state 显式覆盖，identity、回滚、build/tests 与 fresh NO0300 50k 待补。 |
| `TNO0091` | `2026-07-17` | [Stage 14 native hybrid default implementation and fresh gates](./TNO0091_stage14_native_hybrid_default_implementation_and_fresh_gates_20260717.md) | C++ native `true/true`、Python/XS tri-state 与显式回滚闭合；fresh default/off source、O3、100/10k/50k 和完整回归通过，严格整 node gate 因负载拒绝，性能待补。 |
| `TNO0092` | `2026-07-17` | [Stage 14 native hybrid default adoption decision](./TNO0092_stage14_native_hybrid_default_adoption_decision_20260717.md) | 基于 corrected page-local 双 node `-4.237%/-4.353%` 与 fresh `.text/.data/.eh_frame` 历史 identity，采用 C++ native hybrid default；strict ABBA/BAAB 待负载恢复后确认，显式 `0/0` 保留回滚。 |
| `TNO0093` | `2026-07-17` | [Stage 15 activation-equivalent sibling fusion probe plan](./TNO0093_stage15_activation_equivalent_sibling_fusion_probe_plan_20260717.md) | 规划 state/event/unclassified-free、`(level,schedule Vin,graph Vio)` exact-signature no-mutation probe，按距离稳定配对并导出 SN/active-ID；`adjacent_cap_eligible` 在 min-gain 前预期为 `0`，strict 须先闭合 canonical active-ID/batch/layout。 |
| `TNO0094` | `2026-07-17` | [Stage 14 native-hybrid commit-cap fresh gate](./TNO0094_stage14_native_hybrid_commit_cap_fresh_gate_20260717.md) | current native hybrid 下四档 cap 的 typed slots、O3/功能闭合；已补充完整 active lowering 勘误：one-byte OR 仅为子项，static/runtime-write proxy 与 raw BAE 非单调，严格 whole-node 窗口因外部负载未形成，默认保持 `4096`。 |
| `TNO0095` | `2026-07-17` | [Stage 15 sibling fusion probe implementation and production result](./TNO0095_stage15_sibling_fusion_probe_implementation_and_production_result_20260717.md) | default/probe/Stage14 raw stats byte-exact；`7,234` raw pairs 经 cap/min-gain 后 `exact=selected=0`，放宽门槛的 BAE 上界仍 `<0.0011%`，故不进入 strict/CPP/SimTop；完整回归见 [TNO0096](./TNO0096_stage15_full_regression_gate_20260717.md)。 |
| `TNO0096` | `2026-07-17` | [Stage 15 full regression gate](./TNO0096_stage15_full_regression_gate_20260717.md) | 完整 build PASS、串行 CTest `46/48`（`389.20s`）；activity/emitter/memory-fill 通过，仅保留 Stage11..14 相同的 comb-lane-pack/repcut 既有失败，无新增回归。 |
| `TNO0097` | `2026-07-17` | [Stage 16 emitter-local zero-hole active-mask pack probe plan](./TNO0097_stage16_emitter_local_zero_hole_active_mask_pack_probe_plan_20260717.md) | Stage15 exact=0 后转向真实 emitter lowering；规划 default-off/no-mutation zero-hole mask probe，冻结 schedule/topo/active-ID/batch/slot/layout，direct 静态 write proxy `-4.057%`、table gap 相对 contiguous `-11.374%`，strict 与双 NUMA 50k 另立阶段。已追加 gap-DP start 与 conditional logical-lane 勘误。 |
| `TNO0098` | `2026-07-17` | [Stage 7+ strict NUMA window recheck and retest queue](./TNO0098_stage7_plus_strict_numa_window_recheck_and_retest_queue_20260717.md) | 两轮 30 秒 whole-node gate 中 N0 均 PASS，N1 因可迁移外部 PID 导致 min idle `65.82%/78.79%` 均 FAIL；未启动 perf、不降 gate，17 组双 node 独立 inode staging 已闭合，按 Stage14、current caps、Stage10、Stage13/12、Stage8 排队重测。已追加 N1 retry：mean `99.652%` PASS，但 CPU104 min `81.49%` 仍 FAIL。 |
| `TNO0099` | `2026-07-17` | [Stage 14 native-hybrid N0 strict balanced runtime](./TNO0099_stage14_native_hybrid_n0_strict_balanced_runtime_20260717.md) | N0 P0 ABBA+BAAB 8/8 全硬门禁通过；native default cycles `-3.976741%`、instructions `-4.835558%`，两种顺序均约 `-4%`，进一步确认默认采用；N1 strict balanced 待安静窗口补齐。 |
| `TNO0100` | `2026-07-17` | [Stage 16 active-mask gap-pack probe implementation and production result](./TNO0100_stage16_active_mask_gap_probe_implementation_and_production_result_20260717.md) | default/off/probe 的 157-file 与 155-source manifest byte-exact；non-table zero-hole proxy `653,299→623,294`（`-4.593%`），table gap-only `19,942→17,530`（`-12.095%`），validator/自测全过；probe 不改产物，Stage17 先做 direct-only，table 先补 runtime counter。 |
| `TNO0101` | `2026-07-17` | [Stage 16 full regression gate](./TNO0101_stage16_full_regression_gate_20260717.md) | full build PASS、串行 CTest `46/48`（`387.10s`）；emitter 长测 `293.06s`、memory-fill、activity-schedule 与全部 ingest 通过，仅保留 Stage11..15 相同的 comb-lane-pack/repcut 既有失败，无新增回归；已追加 test-only low-env probe focused gate 与实际 `build -j4`/`ctest -j1` 命令勘误。 |
| `TNO0102` | `2026-07-17` | [Stage 17 targeted-direct active-mask gap-pack plan](./TNO0102_stage17_targeted_direct_active_mask_gap_pack_plan_20260717.md) | 规划只发 non-table direct zero-hole chunks；冻结 schedule/active-ID/batch/slot/table 与 excluded paths，native default 保持 `off`、XS sparse override；source diff、O3/功能及 strict 双 NUMA 50k 闭环后再决定 C++ default，N1 gate 阻塞期间不降门槛。 |
| `TNO0103` | `2026-07-17` | [Stage 17 targeted-direct implementation, static, and functional gate](./TNO0103_stage17_targeted_direct_implementation_static_and_functional_gate_20260717.md) | production 选中 `15,913` groups、writes `86,350→56,345`；仅 107 个 sched source 的 active writes 改变，总 source `-1,494,059` bytes，O3 `.text -101,551` bytes，fixed-ASLR 100/10k/50k 功能全过；full regression 待独立归档。 |
| `TNO0104` | `2026-07-17` | [Stage 17 targeted-direct N0 strict runtime and default decision](./TNO0104_stage17_targeted_direct_n0_strict_runtime_and_default_decision_20260717.md) | N0 ABBA/BAAB cycles `+0.253568%/-0.316547%`、合并 `-0.031601%`，低于 spread，判中性并保持 C++ default `off`；N1 因 CPU104 外部 `htop` 阻塞，未跑且未干预，XS 继续 sparse override。 |
| `TNO0105` | `2026-07-17` | [Stage 17 full regression gate](./TNO0105_stage17_full_regression_gate_20260717.md) | full build PASS、串行 CTest `46/48`（`387.77s`）；focused emitter/memory-fill、activity、pybind 与 XS 全过，仅保留 Stage11..16 相同的 comb-lane-pack/repcut 既有失败，无新增回归。 |
| `TNO0106` | `2026-07-17` | [Stage 7+ P1 cap8192 strict window rejection](./TNO0106_stage7_plus_p1_cap8192_strict_window_rejection_20260717.md) | P1 初始 N0 survey PASS、N1 CPU104 min idle `62.15%` FAIL；N0 首个 control pre-gate 通过但 runtime min `94.71%`，整组作废，retry survey 再失败；无 PMU 结论，下次从 attempt2 完整 ABBA+BAAB。 |
| `TNO0107` | `2026-07-17` | [Stage 18 C++ native default single-source cleanup plan](./TNO0107_stage18_cpp_native_default_single_source_cleanup_plan_20260717.md) | 规划仅将与 C++ 完全同值的 activity-schedule XS 默认迁为 sparse，并让 Makefile commit cap 只在显式设置时导出；保留 XS compute/split、batch、parallelism 与 storage-alias 配置，以 JSON/source byte identity 和 override spot tests 裁决。 |
| `TNO0108` | `2026-07-17` | [Absolute raw-value audit and missing ledger](./TNO0108_absolute_raw_value_audit_and_missing_ledger_20260717.md) | 全审计 TNO0001..TNO0107；补录可恢复的 PMU/结构/wall 原值，登记 rejected/incomplete/unrecoverable 边界，并交接 walltime 重评估。 |
| `TNO0109` | `2026-07-17` | [Stage 18 C++ native default single-source implementation and identity gate](./TNO0109_stage18_cpp_native_default_single_source_implementation_and_identity_gate_20260717.md) | 完成 28 项 sparse default/Makefile 单一默认来源迁移；clean/cap8192 fresh production identity、绝对结构值和 byte-exact gate 通过，schedule/端到端程序不变。 |
| `TNO0110` | `2026-07-17` | [Walltime headline criterion and historical re-evaluation](./TNO0110_walltime_headline_criterion_and_re_evaluation_20260717.md) | 将 `walltime_ms/walltime_ok` 设为 SimTop 50k 最终 headline；逐篇复核历史 runtime，唯一实质变化是 cap8192/N0 cycles 近中性但 wall 回退，默认决定保持不变。 |
| `TNO0111` | `2026-07-17` | [Stage 7+ P1 cap8192 attempt2 survey rejection](./TNO0111_stage7_plus_p1_cap8192_attempt2_survey_rejection_20260717.md) | attempt2 N0/N1 whole-node survey 均因 mean/min idle 失败；四项正式 run 均未启动，无 walltime/PMU 样本和 group 目录，不降低新 walltime protocol 的硬门槛。 |
| `TNO0112` | `2026-07-17` | [Stage 7+ P1 cap8192 attempt3 survey rejection](./TNO0112_stage7_plus_p1_cap8192_attempt3_survey_rejection_20260717.md) | attempt3 N0 survey PASS，N1 因 CPU112 minimum idle `60.02%` FAIL；外部可迁移 `htop`/Java 负载仍在，未启动正式 run，无 walltime/PMU 或 group 目录。 |
| `TNO0113` | `2026-07-17` | [Stage 19 table activation runtime probe plan](./TNO0113_stage19_table_activation_runtime_probe_plan_20260717.md) | 先用仅在显式 runtime-profile emit 中编译的动态 counter 量化 generic table activation 热度；profile walltime 不做 A/B，后续未插桩 candidate 仍由 strict 50k `Host time spent` 裁决。 |
| `TNO0114` | `2026-07-17` | [Stage 19 table activation runtime probe result](./TNO0114_stage19_table_activation_runtime_probe_result_20260717.md) | profile source 插点 `586` 个、静态和 `89,903/19,942/17,530` 闭合；100/10k/50k 动态 summary 均唯一且持续增长，50k `evaluations=2,998,684`，决定进入未插桩 Stage20 table candidate。 |
| `TNO0115` | `2026-07-17` | [Stage 20 table encoding candidate plan](./TNO0115_stage20_table_encoding_candidate_plan_20260717.md) | 将 table loop rewrite 与 zero-hole gap candidate 拆成两个显式 policy；冻结 schedule/active-ID/batch/slot，native default 继续 `off`，最终只由未插桩 50k `Host time spent` 裁决。 |
| `TNO0116` | `2026-07-17` | [Stage 20 table encoding implementation and full gate](./TNO0116_stage20_table_encoding_implementation_and_full_gate_20260717.md) | 两个未插桩 table candidate 完成实现、production emit、绝对 source/ELF 对账、功能与完整回归；586 个 generic loops 整体替换且 schedule/slot identity 闭合。 |
| `TNO0117` | `2026-07-17` | [Stage 20 table encoding strict walltime and default decision](./TNO0117_stage20_table_encoding_strict_walltime_and_default_decision_20260717.md) | 正确 page-local 双 NUMA walltime 显示 contiguous 合并仅 `-0.010753%` 且 node 方向反转，gap N1 为 `-0.074125%`、小于 spread；C++ default 保持 `off`。 |
| `TNO0118` | `2026-07-17` | [Stage 7+ P1 cap8192 corrected runtime attempt4 to6](./TNO0118_stage7_plus_p1_cap8192_corrected_runtime_attempt4_to6_20260717.md) | fresh page-local 下 N0 ABBA、N1 ABBA/BAAB wall 均小幅正向，N1 平衡 `-0.408054%` 但小于 spread；N0 BAAB 三次被 runtime minimum 拒绝，default 暂留 `4096`。 |
| `TNO0119` | `2026-07-17` | [Stage 7+ P0 N1 native hybrid closure and P1 try7](./TNO0119_stage7_plus_p0_n1_native_hybrid_closure_and_p1_try7_20260717.md) | N1 strict ABBA+BAAB wall `77,707.00→74,571.75 ms`（`-4.034707%`），完整确认 native hybrid C++ default；P1 N0 try7 runtime min `94.820%` 作废，cap 仍留 `4096`。 |
| `TNO0120` | `2026-07-17` | [Stage 7+ P1 cap8192 try8 survey rejection](./TNO0120_stage7_plus_p1_cap8192_try8_survey_rejection_20260717.md) | N0 raw survey count/mean 通过，但 minimum `94.690%` on CPU22 低于硬门槛；未启动 emu、无 wall/PMU，P1 N0 BAAB 继续待安静窗口。 |
| `TNO0121` | `2026-07-18` | [Stage 21 terminal common-target pushforward probe plan](./TNO0121_stage21_terminal_common_target_pushforward_probe_plan_20260718.md) | GSIM/GrhSIM 直比定位到 per-pair boundary-value multiplicity；规划最多128个小型纯 compute node 的 common-target pushforward no-mutation probe，同时要求 BAE 与 materialization 净下降并补动态额外执行 gate。 |
| `TNO0122` | `2026-07-18` | [Stage 21 terminal pushforward probe implementation and production result](./TNO0122_stage21_terminal_pushforward_probe_implementation_and_production_result_20260718.md) | production exact eligible `1,054`、默认选择 `128`，投影净减 `128` BAE/边界值；probe 与 current-default emitter 产物 byte-exact，继续实现 strict 并由 50k walltime 裁决。 |
| `TNO0123` | `2026-07-18` | [Stage 22 terminal pushforward strict implementation and static gate](./TNO0123_stage22_terminal_pushforward_strict_implementation_and_static_gate_20260718.md) | strict stable-splice 实际移动 `128` 个 1-op node，BAE/边界值精确 `-128`、logical-byte proxy `-183`，DAG/commit/batch 不变；O3/50k 功能通过，walltime 待 current-default cap 重裁后复测。 |
| `TNO0124` | `2026-07-18` | [Stage 7+ P1 cap8192 balanced closure and default adoption](./TNO0124_stage7_plus_p1_cap8192_balanced_closure_and_default_adoption_20260718.md) | fresh page-local N0 BAAB 补齐后，四个独立组 wall 全部正向；双 NUMA 等权 `74,604.75→74,280.00 ms`（`-0.435294%`），采用 C++ native cap8192，显式4096保留回滚。 |
| `TNO0125` | `2026-07-18` | [Stage 22 terminal pushforward cap8192 re-evaluation and default decision](./TNO0125_stage22_terminal_pushforward_cap8192_re_evaluation_and_default_decision_20260718.md) | cap8192 默认上 strict 结构收益 `-128` BAE/边界值、`-183` logical-byte proxy，但四组 fresh page-local wall 全部无正向合并收益；双 NUMA `74,384.00→74,461.50 ms`（`+0.104189073%`），strict 保持 off。 |
| `TNO0126` | `2026-07-18` | [Stage 25 commit-cap re-evaluation plan on the cap8192 baseline](./TNO0126_stage25_commit_cap_re_evaluation_plan_20260718.md) | 规划在 current cap8192/C++ native-hybrid 基线上重扫 `12288/16384/32768` commit guard cap；先结构筛选，再按 fresh page-local 双 NUMA walltime 裁决。 |
| `TNO0127` | `2026-07-18` | [Stage 25 commit-cap re-evaluation walltime and default decision](./TNO0127_stage25_commit_cap_re_evaluation_walltime_and_default_decision_20260718.md) | cap16384 结构 `-1,464` BAE/`-659` DAG，首次四组 dual wall `74,437.875→74,302.125ms`，但 N1 BAAB fresh try2 回退 `+0.570131%`；不改 cap8192 默认，32768 停止 full 测试。 |
| `TNO0128` | `2026-07-18` | [Stage 26 fire-aware terminal pushforward plan](./TNO0128_stage26_fire_aware_terminal_pushforward_plan_20260718.md) | 规划用 Stage19 50k fire profile 在 terminal pushforward strict 候选入列前加入 `source_fire`/`target_fire` gate，默认 off，按双 NUMA walltime 裁决。 |
| `TNO0129` | `2026-07-18` | [Stage 26 fire-aware terminal pushforward runtime and decision](./TNO0129_stage26_fire_aware_terminal_pushforward_runtime_and_decision_20260718.md) | min1000/min10000 strict 分别选 `80/54` 个 move；双 NUMA 四组 wall 分别 `74,248.375→74,258.500ms`、`74,259.375→74,344.500ms`，均未改善，profile strict 保持显式关闭。 |
| `TNO0130` | `2026-07-18` | [NUMA first-touch and tmpfs page-cache root cause](./TNO0130_numa_first_touch_and_tmpfs_page_cache_root_cause_20260718.md) | 证明 fresh inode 不等于目标 NUMA page placement；unbound `cp` 可把 NEMU tmpfs page cache 留在 N0，后续 `membind=1` 不迁移，固化复制时 first-touch 和 `numa_maps` 门禁。 |
| `TNO0131` | `2026-07-18` | [Stage 27 shared-input peer peel probe plan](./TNO0131_stage27_shared_input_peer_peel_probe_plan_20260718.md) | 规划在不放宽 108-op cap、不改变 graph 的前提下，将 source 超节点内小型 compute node 只读剥离到共同输入 fanout peer；先做 exact/active-byte/profile probe，再决定是否 strict。 |
| `TNO0132` | `2026-07-18` | [Stage 27 shared-input peer probe production result](./TNO0132_stage27_shared_input_peer_probe_production_result_20260718.md) | fresh extension 双次 production probe 均 `exact=80/selected=14`，selected TSV byte-identical；严格 fire 子集仅 `9` 行、`11` BAE/active-byte/chunk 上界（`0.000638904%`），无 slot/batch 证据，按停止条件不进入 strict/CPP/50k，默认保持 off。 |
| `TNO0133` | `2026-07-18` | [Stage 28 deferred-activation forward probe plan](./TNO0133_stage28_deferred_activation_forward_probe_plan_20260718.md) | 基于 emitter 实际 deferred activation lowering，规划对纯 compute source→target 的无条件 forward activation 只读 probe；冻结 consumer fanout、direct-state、batch 与 active ID，先按真实 entry/chunk/table 和 50k fire 加权净收益筛选。 |
| `TNO0134` | `2026-07-18` | [Stage 28 deferred-activation forward probe production result](./TNO0134_stage28_deferred_activation_forward_probe_production_result_20260718.md) | r2 production `raw_pairs=490406`、exact/accounted/static-positive `3864`、selected `128`、逐项输出 `192`；emitter work `2,417,244→2,409,068`、estimated lines `549,155→549,385`，work-proxy lower/upper `-71,582,689/+60,496,519` 跨零；13 个 proxy-positive pair 仅进入动态 cofire counter，未直接 strict。 |
| `TNO0135` | `2026-07-18` | [Stage 29 deferred-activation cofire counter plan](./TNO0135_stage29_deferred_activation_cofire_counter_plan_20260718.md) | 只对 13 个 proxy-positive source→target pair 做 default-off、no-mutation 动态计数；记录入口前/flush 后 pending、baseline flush added、leader miss 等绝对值，先过 100/10k/50k 功能与计数，再决定是否生成 strict overlay，最终以 SimTop `Host time spent` walltime 裁决。 |
| `TNO0136` | `2026-07-18` | [Stage 29 deferred-activation cofire probe production result](./TNO0136_stage29_deferred_activation_cofire_probe_production_result_20260718.md) | 显式 cofire probe 的 O3/link 与 100/10k/50k 功能通过；50k 中 pair 0..11 均 `leader_without_follower=0`，进入 Stage30 12-pair strict 计划；`35026→38043` 有 `141` 次 miss，停止该 pair，插桩 walltime 仅作诊断且默认保持 off。 |
| `TNO0137` | `2026-07-18` | [Stage 30 deferred-activation 12-pair strict plan](./TNO0137_stage30_deferred_activation_12pair_strict_plan_20260718.md) | 仅对 Stage29 前 12 对设计显式 default-off strict overlay；固定 `648` exclusive values，目标 static work `3,262→1,953`，先做 product-map/schedule/slot identity 与 100/10k/50k 功能，再以双 NUMA SimTop `Host time spent` walltime 裁决。 |
| `TNO0138` | `2026-07-18` | [Stage 30 deferred-activation 12-pair strict implementation, static, and function gate](./TNO0138_stage30_deferred_activation_12pair_strict_implementation_static_function_gate_20260718.md) | production strict 通过 `12` pairs/`648` values；勘误后的实际 12-pair work 为 `2,417,244→2,415,935`，8 个 schedule CPP 改变、`.text -15,632`，O3/link 与 100/10k/50k 功能通过；formal 双 NUMA 被外部负载阻断，尚无 walltime 采用结论。 |
| `TNO0139` | `2026-07-19` | [Stage 30 formal walltime gate block and default decision](./TNO0139_stage30_formal_walltime_gate_block_and_default_decision_20260719.md) | 唯一有效 N0 ABBA wall 为 `74,429.5→74,266.0 ms`（`-0.219671%`）；N0 BAAB/N1 在最多 60 次 whole-node admission 中被持续外部 CI 负载阻断，无法形成双 NUMA balanced 结论，strict 保持显式 off。 |
| `TNO0140` | `2026-07-19` | [Stage 31 miss-tolerant 13-pair deferred-activation strict plan](./TNO0140_stage31_miss_tolerant_13pair_strict_plan_20260719.md) | 保留 Stage30 12-pair policy，新增独立 extended strict 只加入 `35026→38043`；141 次额外纯 bool target fire 修正后 proxy 仍为 `268,014`，规划按 `3,525→2,129` local work 和双 NUMA walltime裁决。 |
| `TNO0141` | `2026-07-19` | [Stage 31 13-pair strict implementation, static, and function gate](./TNO0141_stage31_13pair_strict_implementation_static_function_gate_20260719.md) | 新增独立 extended policy，production 验证 `13` pairs/`691` values，实际 global work `2,417,244→2,415,848`、9 个 schedule CPP 合计 `-143,088` bytes、`.text -16,576`；三版本 100/10k/50k 功能全过。 |
| `TNO0142` | `2026-07-19` | [Stage 31 13-pair strict formal walltime block and default decision](./TNO0142_stage31_13pair_strict_formal_walltime_block_and_default_decision_20260719.md) | N0 ABBA 前三样本各自有效但 a2 三次 whole-node admission 失败，N1 三窗 mean 仅 `96.26%..96.98%`；没有完整 order/双 NUMA walltime，12/13-pair strict 都保持 C++ default-off。 |
| `TNO0143` | `2026-07-19` | [Walltime absolute-value and Stage 7+ NUMA retest audit](./TNO0143_walltime_absolute_value_and_stage7plus_numa_retest_audit_20260719.md) | 审计确认 accepted runtime 均可恢复绝对 `Host time spent` 且默认结论不变；补录 TNO0087/旧 samepost 绝对值和缺失路径，同时明确 Stage10、Stage8 仍缺 whole-node balanced 复核。 |
| `TNO0144` | `2026-07-19` | [Stage 32 same-batch activation cohort probe plan](./TNO0144_stage32_same_batch_activation_cohort_probe_plan_20260719.md) | 规划 final-emitter exact-source cohort probe；pinned batch12 的 51 个连续 pure-compute body 只有一个普通 activation source，投影 BAE `51→1`、50k guard tests `-958,750`，先用入口/出口 pending counter 证明全等再做 strict。 |
| `TNO0145` | `2026-07-19` | [Stage 32 cohort probe implementation and static gate](./TNO0145_stage32_cohort_probe_implementation_and_static_gate_20260719.md) | 实现 C++ default-off exact-source probe并收紧 SimTop production contract；current-default 找到 `252` cohorts/`902` members，投影 BAE `3,619→1,450`，activity/emitter stats 与基线 byte-identical。 |
| `TNO0146` | `2026-07-19` | [Stage 32 cohort probe 50k equivalence gate](./TNO0146_stage32_cohort_probe_50k_equivalence_gate_20260719.md) | page-local fixed-ASLR 100/10k/50k 功能全过；50k `252/252` cohorts partial/mismatch/exit-pending 全零，绝对 body fire `9,270,152`、guard tests saved `6,854,019`，进入 default-off strict。 |
| `TNO0147` | `2026-07-19` | [Stage 32 current-profile replay and log audit](./TNO0147_stage32_current_profile_replay_and_log_audit_20260719.md) | 审计发现 legacy/current 全量 fire 有 `1,553` 行差异但与 selected member 交集为 0；current-profile fresh replay 完整复现 `252/902/2,169`，并记录 raw stdout/stderr 插断、TSV 为权威计数源。 |
| `TNO0148` | `2026-07-19` | [Stage 33 same-batch activation cohort strict plan](./TNO0148_stage33_same_batch_activation_cohort_strict_plan_20260719.md) | 规划 default-off strict lowering；以完整 252-cohort manifest fingerprint、跨 word accumulator、deferred fanout overlay 和 ordinary/fullpass 边界为硬 gate，最终只由 fresh 双 NUMA 50k `Host time spent` 决定默认。 |
| `TNO0149` | `2026-07-19` | [Stage 33 NUMA symmetry and quiet-window recheck](./TNO0149_stage33_numa_symmetry_and_quiet_window_recheck_20260719.md) | 两轮 30 秒 whole-node survey 从 N0 PASS/N1 FAIL 反转为 N0 FAIL/N1 PASS；第一轮仅保留绝对汇总，第二轮 raw/SHA 完整，结合镜像 target/sibling 与 binding probe，支持差异来自迁移外部负载窗口，而非拓扑或 `taskset+numactl` 绑反。 |
| `TNO0150` | `2026-07-19` | [Stage 33 strict implementation, manifest, and focused gate](./TNO0150_stage33_strict_implementation_manifest_and_focused_gate_20260719.md) | 实现 default-off strict overlay；v2 完整 source tuple manifest 固定 FNV `2221bbc3ffd74a71`，两 cohort 跨 word/downstream harness、2/2 focused、Python17/17、XS28/28 通过，production/50k 另行归档。 |
| `TNO0151` | `2026-07-19` | [Stage 33 strict production static gate](./TNO0151_stage33_strict_production_static_gate_20260719.md) | fresh SimTop strict emit 通过完整 FNV与 `252/902/88,334` contract，实际 ordinary BAE `3,619→1,450`；activity/emitter stats identity，134 个源码/header 共 `-34,609 B`，O3/功能另行归档。 |
| `TNO0152` | `2026-07-19` | [Stage 33 strict O3, link, and function gate](./TNO0152_stage33_strict_o3_link_and_function_gate_20260719.md) | O3/archive、独立 link 与 page-local fixed-ASLR 100/10k/50k 全过；strict `.text -11,360 B`，50k 功能 wall `74,459 ms`、placement `21,257/0`，正式 A/B 仍待 fresh same-commit control。 |
| `TNO0153` | `2026-07-19` | [Stage 33 strict full regression gate](./TNO0153_stage33_strict_full_regression_gate_20260719.md) | 完整 build/install 与 CTest `48/50`（`403.44 s`）；full emitter、cohort/deferred、memory-fill、activity/ingest 全过，仅保留既有 comb-lane-pack/repcut 两项失败。 |
| `TNO0154` | `2026-07-19` | [Stage 33 fresh same-commit current-default control](./TNO0154_stage33_fresh_same_commit_default_control_20260719.md) | 在父 `4857a5b`/子模块 `f17e90e` 上 fresh 重建 current C++ default A；stats 与 strict `cmp=0`，control archive/emu 绝对 SHA、ELF sections 和后续 walltime protocol 固定。 |
| `TNO0155` | `2026-07-19` | [Stage 7+ current-baseline rebuild and formal gate interruption](./TNO0155_stage7_plus_current_baseline_rebuild_and_formal_gate_interruption_20260719.md) | fresh 重建四个既有候选；四者均完成 N0 ABBA（strict `-0.357478203%`、fanin `-0.322120752%`、p050 `-0.089137909%`、p200 `+0.170114912%`），BAAB 被外部 workload 的 hard runtime gate 阻断，按 single-NUMA 代表记录，默认保持不变。 |
| `TNO0156` | `2026-07-20` | [SimpleTES auto-research bench and launch gate](./TNO0156_simpletes_auto_research_bench_and_launch_gate_20260720.md) | 固定 parent `b90d204`/wolvrix `f17e90e`，实现安全 Codex structured candidate、fresh build/default-off/attribution gate 与动态 CCD fixed-ASLR 50k ABBA→BAAB runtime；SimpleTES `98 passed`，真实 MJY `gpt-5.6-sol/ultra` preflight PASS；当前 survey 无 quiet CCD，尚无 accepted walltime。 |
| `TNO0157` | `2026-07-20` | [SimpleTES isolated-clone startup fix](./TNO0157_simpletes_isolated_clone_startup_fix_20260720.md) | 正式 instance `91f6580e` 定位并修复 env stderr 污染 Git SHA、空 gitlink 继承 parent worktree 两个 deterministic clone bug；SimpleTES `100 passed`，control ready marker 已写并进入 isolated env/build，仍无 50k walltime。 |
| `TNO0158` | `2026-07-20` | [SimpleTES formal runtime contract hardening](./TNO0158_simpletes_formal_runtime_contract_hardening_20260720.md) | paired runtime 仅接受 `ABBA/BAAB` 并记录绝对 order，清理继承 trace/profile/TSV 环境；SimpleTES `104 passed`，正式 control 已进入 fresh SimTop emit，尚无 accepted 50k walltime。 |
| `TNO0159` | `2026-07-20` | [SimpleTES current-default baseline and worker launch](./TNO0159_simpletes_current_default_baseline_and_worker_launch_20260720.md) | dynamic CCD66 上 current-default ABBA 四个有效 wall 为 `74,900/74,933/74,956/74,441 ms`，全组均值 `74,807.5 ms`；ASLR/NUMA/monitor/PMU/功能全过，初始节点 accepted 后真实 `gpt-5.6-sol/ultra` worker 已启动。 |
| `TNO0160` | `2026-07-20` | [SimpleTES first formal search results and default decision](./TNO0160_simpletes_first_formal_search_results_and_default_decision_20260720.md) | 正式 run 用满 `16` 次 generation，`2` 个候选完成 ABBA+BAAB；最佳 wall 为 `74,237.50→73,998.25 ms`（改善 `239.25 ms/0.322276478%`），低于 `1%` 可信线且独立复测被 fresh-fingerprint 假拒绝阻断，不保留代码、不改默认。 |
| `TNO0161` | `2026-07-20` | [SimpleTES fingerprint input stabilization and best-seed continuation](./TNO0161_simpletes_fingerprint_input_stabilization_and_best_seed_continuation_20260720.md) | SimpleTES `c7f0cef` 固定并私有复制 `2,103` 个 generation inputs，在三个阶段复核 manifest；`110 passed`，best digest `842fb6de...` 的 fresh `16 proposals/8 valid` continuation 契约已闭合，本记录截止点尚未启动。 |
| `TNO0162` | `2026-07-20` | [SimpleTES best-seed continuation launch and attribution gate](./TNO0162_simpletes_best_seed_continuation_launch_20260720.md) | fresh instance `4269c986` 已从 best digest `842fb6de...` 启动；control/candidate 均为 `2,103` 个 generation inputs、fingerprint `e9ca0efd...`，disabled `24` 项 focused 与 `100/10k` gate 通过，enabled build 和新 50k 复评进行中，尚无新性能结论。 |
| `TNO0163` | `2026-07-20` | [SimpleTES quiet-CCD retry and rebuild audit](./TNO0163_simpletes_quiet_ccd_retry_and_rebuild_audit_20260720.md) | 首次 50k admission 因 24 个 CCD 均未满足 `3s whole-CCD` 严格空闲 gate 而 retryable，`eval_time=4,986.4233756661415 s`、无 walltime 样本；engine 已重新 clone/build 同一 seed，尚无性能或默认结论。 |
| `TNO0164` | `2026-07-20` | [SimpleTES best-seed initial runtime result](./TNO0164_simpletes_best_seed_initial_runtime_result_20260720.md) | 初始 seed 完成 ABBA/BAAB；control `72,793.25 ms`、candidate `73,378.75 ms`，回退 `585.50 ms/0.804333%`，`Initial score=0.992021`，保持默认关闭；scheduler 已进入新 generation。 |
| `TNO0165` | `2026-07-21` | [SimpleTES best-seed continuation final results and default decision](./TNO0165_simpletes_best_seed_continuation_final_results_and_default_decision_20260721.md) | instance `4269c986` 在 `14/16` generation attempts 后达到 `8/8` valid；8 个新候选 wall 均正向，最佳 targeted-direct 为 `73,828.00→73,458.50 ms`（改善 `369.50 ms/0.500488%`），低于 `1%` 可信线，不改默认；best program 只作为后续 seed。 |
| `TNO0166` | `2026-07-21` | [SimpleTES long best-seed continuation launch](./TNO0166_simpletes_long_best_seed_continuation_launch_20260721.md) | fresh instance `25411edd` 从 digest `4ce54fe6...` 启动；预算扩为 `32 proposals/16 valid`、LLM timeout `5,400s`、runtime infra retries `4`，所有 quiet-CCD/fixed-ASLR/双 NUMA 50k gate 不变；初始归因构建进行中，尚无本轮新 walltime。 |
| `TNO0167` | `2026-07-23` | [SimpleTES long continuation final results, semantic audit, and default hold](./TNO0167_simpletes_long_continuation_final_results_semantic_audit_and_default_hold_20260723.md) | instance `25411edd` 正常达到 `16/16` valid；最佳 gen27 pooled wall 为 `74,327.00→60,685.75 ms`（改善 `13,641.25 ms/18.353021%`），正式 gate 全过；因复合机制仍需 fresh 复现、消融和更广语义回归，暂不合入或改默认。 |
| `TNO0168` | `2026-07-23` | [SimpleTES best-candidate fresh replication launch](./TNO0168_simpletes_best_candidate_fresh_replication_launch_20260723.md) | 用 gen27 best program fresh 启动 instance `50c610a6`，预算仍为 `32 proposals/16 valid`；initial seed attribution build 正在进行，尚无新 50k walltime 或 score。 |
| `TNO0169` | `2026-07-24` | [SimpleTES fresh replication interim checkpoint and new best](./TNO0169_simpletes_fresh_replication_interim_checkpoint_and_new_best_20260724.md) | instance `50c610a6` 仍在运行，checkpoint 已有 `6/16` generated valid；initial fresh 复现 `18.420313%`，当前 gen9 新最佳为 `73,883.00→59,940.00 ms`（改善 `13,943.00 ms/18.871730%`），正式双 order gate 全过，尚不改默认。 |
| `TNO0170` | `2026-07-24` | [SimpleTES continuation abnormal termination and orphan result](./TNO0170_simpletes_continuation_abnormal_termination_and_orphan_result_20260724.md) | instance `50c610a6` 的 scheduler 在 `6/16` 时无正常 footer 消失；最后 evaluator 脱离 scheduler 完成 digest `1051b1e8...`，正式 wall 为 `74,400.00→60,617.50 ms`（改善 `13,782.50 ms/18.524866%`）但未被 checkpoint ingest，当前没有运行进程，也未自动恢复。 |
| `TNO0171` | `2026-07-24` | [SimpleTES 18% ablation design and static attribution](./TNO0171_simpletes_18pct_ablation_design_and_static_attribution_20260724.md) | 机械 diff 将 gen20→gen24 的 `17.386666` 个百分点跃升缩小到唯一变量：`44,976` 个 cold singleton guard 的 `unlikely`；历史 instructions 仅 `-0.003936%`、cycles `-17.644466%`，fresh gen20/gen24 单变量 50k 已开始串行复测。 |
| `TNO0172` | `2026-07-24` | [gen20 quiet-gate retries and proof-backed runtime reuse](./TNO0172_gen20_quiet_gate_retries_and_proof_backed_runtime_reuse_20260724.md) | gen20 两次 full gate 分别在临运行复核和 24-CCD survey 被外部负载阻断，accepted samples 均为 `0`；SimpleTES `fc17b90` 加入完整 artifact proof 与 immutable runtime attempts，第三轮 full 已启动，之后可安全跳过重复构建。 |
| `TNO0173` | `2026-07-24` | [gen20/gen24 fresh cold-guard hint ablation result](./TNO0173_gen20_gen24_fresh_cold_guard_hint_ablation_result_20260724.md) | Fresh gen20 为 `73,928.00→73,237.50 ms`（`0.934017%`，低于 spread），gen24 为 `74,055.00→60,648.25 ms`（`18.103774%`，可信）；唯一变量 `>=1024` cold guard `unlikely` 贡献 `17.169757 pp`，确认其为约 18% 主来源。 |
| `TNO0174` | `2026-07-25` | [gen24 targeted-direct dependency audit and landing plan](./TNO0174_gen24_targeted_direct_dependency_audit_and_landing_plan_20260725.md) | 确认 gen24 只借用 `targeted-direct` gate、无 gap-pack correctness/data dependency；原 gap packing 独立 pooled wall `74,691.75→74,649.50 ms`（`0.056566%`，双 order 反向）保持 off，规划独立 exact-event policy 与 A/B/C/D 四臂落地门禁。 |
| `TNO0175` | `2026-07-25` | [gen24 independent policy implementation and static gate](./TNO0175_gen24_independent_policy_implementation_and_static_gate_20260725.md) | 新增独立 `commit_exact_event_policy`，C++ 为唯一默认源，Python/XS 稀疏继承；focused、pybind `22/22`、XS `32/32` 与主 emitter 全过，fresh full build PASS、CTest `49/51`，仅保留两个历史 transform 失败。 |
| `TNO0176` | `2026-07-25` | [gen24 four-arm function, formal walltime, and default decision](./TNO0176_gen24_four_arm_function_formal_walltime_and_default_decision_20260725.md) | A/B/C/D 独立产物与 100/10k 功能全过；正式 A/C pooled wall `74,773.25→61,284.00 ms`（减少 `13,489.25 ms/18.040208%`）确认 exact-event 独立默认开启，C/D 仅 `60,759.50→60,665.25 ms`（`94.25 ms/0.155120%`）故 targeted-direct 保持 off；native no-policy identity 仍 pending。 |
| `TNO0177` | `2026-07-25` | [SimpleTES GrhSIM bench contract v2 migration and continuation readiness](./TNO0177_simpletes_grhsim_bench_contract_v2_migration_and_continuation_readiness_20260725.md) | bench 新增 `control/default-path/explicit-options` 三模式，绑定完整 control artifact/proof 与 exact resume state；全量 `138/138`、focused `66/66`、validate-only/dry-run 均 PASS，最终 pins 与 direct native-control canary 待提交后完成。 |
| `TNO0178` | `2026-07-25` | [native no-override default path and same-session identity](./TNO0178_native_no_override_default_path_and_same_session_identity_20260725.md) | independent fresh 审计发现三份 RTL 输入漂移，未误报 identity；最终同 Session/同已调度 design 双 emit 的 `134` files、`1,340,129,434 B`、fingerprint `3bffd9df...` 逐字节相同，证明通用 C++ 默认等价于显式 C 臂且 gap-pack 仍 off。 |
| `TNO0179` | `2026-07-25` | [SimpleTES v2 pinned native-control canary and continuation readiness](./TNO0179_simpletes_v2_pinned_native_control_canary_and_continuation_ready_20260725.md) | 最终 pins 与 schema-v2 control canary 闭合；accepted ABBA 为 `61,310/61,318/61,010/61,073 ms`，control/candidate 均值 `61,191.50/61,164.00 ms`、仅差 `0.044941%`，生成/产物身份相同且所有 CCD/ASLR/NUMA/perf/功能门禁通过；未启动 research 或调用模型。 |
| `TNO0180` | `2026-07-25` | [SimpleTES v2 provider schema fix and long research launch](./TNO0180_simpletes_v2_provider_schema_fix_and_long_research_launch_20260725.md) | 首次启动因 provider 禁止顶层 `oneOf` 在 preflight 确定性退出；SimpleTES `3decc51` 改为 flat schema 并补强 evaluator evidence gate，真实 `gpt-5.6-sol/ultra` preflight、focused `77/77`、full `139/139` 通过；fresh v2 `continuation_v2_20260725_090855` 已按 `64 proposals/32 valid` 启动 initial control。 |
| `TNO0181` | `2026-07-27` | [SimpleTES v2 cumulative ablation design and launch](./TNO0181_simpletes_v2_cumulative_ablation_design_and_launch_20260727.md) | 机械恢复 gen7/gen16/gen22/gen40 为 `R/RW/RWF/RWFA` 四个 default-path、零 option 累计 arm；固定 current-default paired baseline、fresh build、quiet-CCD fixed-ASLR ABBA→BAAB 协议，已串行启动，尚无 fresh 性能或默认结论。 |
| `TNO0182` | `2026-07-27` | [SimpleTES v2 R result and RW quiet-gate exhaustion](./TNO0182_simpletes_v2_r_result_and_rw_quiet_gate_exhaustion_20260727.md) | R 正式 pooled wall 为 `61505.75→57466.50 ms`，减少 `4039.25 ms/6.567272%`，双 order、fixed-ASLR、CCD/NUMA/PMU/功能门禁全过；RW build/proof/功能通过但 9 次 infra 调用耗尽，最终 attempt 报 strict quiet-gate failure，accepted 50k samples 为 0（walltime=`null`），不能裁决 W。 |
| `TNO0183` | `2026-07-27` | [SimpleTES v2 direct ablation final attribution and retention decision](./TNO0183_simpletes_v2_direct_ablation_final_attribution_and_retention_decision_20260727.md) | 顶层 direct 消融确认 R `6.567272%`、W `1.869589%`、A `2.585383%` 正向，F pooled 仅 `0.159522%` 且双 order 反向；B→RW endpoint 为 `60513.50→55394.00 ms`（`5119.50 ms/8.460096%`）。保留 R/W，停止 F；A 待 no-F 的 RWA direct/endpoint 后再决定默认。 |
| `TNO0184` | `2026-07-27` | [SimpleTES v2 RWA materialization and fresh gate](./TNO0184_simpletes_v2_rwa_materialization_and_fresh_gate_20260727.md) | 从 RW/RWF/RWFA full patch 机械构造无 F 的 RWA；`RW+A == RWFA-F`、`RWA+F == RWFA` 逐字节闭合。新 default-path/零 option arm 完成 fresh build、focused `29/29`、100/10k、proof 与 11-file manifest，SimpleTES `140 passed`。 |
| `TNO0185` | `2026-07-27` | [SimpleTES v2 F repeat and RWA endpoint decision](./TNO0185_simpletes_v2_f_repeat_and_rwa_endpoint_decision_20260727.md) | F 复测 pooled 仅 `55381.75→55248.75 ms`（`133.00 ms/0.240151%`），确认无可靠保留收益；无 F 的 B→RWA fresh endpoint 为 `60583.50→53992.75 ms`（`6590.75 ms/10.878787%`），双 order 和全门禁通过，最终组合收敛为 R/W/A，排除 F。 |
| `TNO0186` | `2026-07-27` | [RWA Wolvrix landing implementation and provenance](./TNO0186_rwa_wolvrix_landing_implementation_and_provenance_20260727.md) | R/W/A 已落入 Wolvrix `16a9f493`，parent executable snapshot 为 `d31118be`；fresh Ninja `94` steps、focused、CTest `50/52`（仅两项历史 expected failures）、pybind `22/22`、XS `32/32` 通过，F 排除；SimpleTES production/canary 与正式性能仍为 PENDING。 |
| `TNO0187` | `2026-07-27` | [RWA landing SimpleTES repin and native control canary](./TNO0187_rwa_landing_simpletes_repin_and_native_control_canary_20260727.md) | SimpleTES `b0c7754` 已 pin parent `d31118b` / Wolvrix `16a9f49` 并改为 post-RWA 空 control；旧 checkpoint fail-close，bench `69/69`、全量 `141/141`、production focused/100/10k 与同 ELF 50k canary 全过，未启动 auto research。 |
| `TNO0188` | `2026-07-27` | [RWA landing native 50k performance and default decision](./TNO0188_rwa_landing_native_50k_performance_and_default_decision_20260727.md) | 实际 B→native-RWA final pooled wall 为 `60,881.50→54,088.00 ms`，减少 `6,793.50 ms/11.158562%`；ABBA/BAAB 双 order 与全部 ASLR/CCD/NUMA/PMU/功能门禁通过，最终保留通用默认 R/W/A，F 排除、targeted-direct 保持 off；已追加 attempt 1 失败时点勘误，不改性能结论。 |
| `TNO0189` | `2026-07-28` | [SimpleTES K3 Codex provider default and preflight](./TNO0189_simpletes_k3_codex_provider_default_and_preflight_20260728.md) | SimpleTES `b73f399` 通用化 Codex custom-provider credential override，并把 GrhSIM launcher 默认切到 `k3/ultra` 与 Kimi config/auth；focused `83/83`、full `145/145`、真实 production-schema preflight 通过，checkpoint 快照不变，未启动下一轮 research。 |
| `TNO0190` | `2026-07-28` | [SimpleTES K3 post-RWA long research launch](./TNO0190_simpletes_k3_post_rwa_long_research_launch_20260728.md) | 旧 6 个 instance 均因无 checkpoint 或 pre-RWA/schema-v1 pin 不兼容而 fail-close；fresh instance `583068cb` 已用 Kimi `k3/ultra` 按 `64 proposals/32 valid` 启动，initial control evaluator 正在运行，尚无本轮 walltime 或性能结论。 |
| `TNO0191` | `2026-07-28` | [SimpleTES K3 broken run diagnosis and graceful stop](./TNO0191_simpletes_k3_broken_run_diagnosis_and_graceful_stop_20260728.md) | instance `583068cb` 在确认 K3 持续输出 placeholder 后 graceful stop；initial control `53,794.5 ms`，27 个持久化 output 全部无效、`0/32` valid，无 candidate build/50k 性能结果，旧 preflight 被勘误为只证明 transport/schema。 |
| `TNO0192` | `2026-07-28` | [SimpleTES K3 grounded generation fix and capability gate](./TNO0192_simpletes_k3_grounded_generation_fix_and_capability_gate_20260728.md) | SimpleTES `88abf71` 加入 JSON-only/local validation/repair、required-first loopback、bounded trace 与 grounded gate；全量 `210 passed`，真实 K3 deterministic preflight 约 `36 s`、`1` repo tool、`632 chars` PASS，未启动正式 research。 |
| `TNO0193` | `2026-07-28` | [SimpleTES K3 grounded fresh research launch](./TNO0193_simpletes_k3_grounded_fresh_research_launch_20260728.md) | fresh instance `7291c6c2` 已以 Kimi `k3/ultra`、`64 proposals/32 valid` 启动；deterministic capability/TOCTOU gate 通过，initial control 正按空闲 CCD、fixed-ASLR SimTop 50k 协议运行，尚无 candidate 或性能结论。 |
| `TNO0194` | `2026-07-28` | [SimpleTES K3 grounded initial control result](./TNO0194_simpletes_k3_grounded_initial_control_result_20260728.md) | 前 3 次 runtime invocation 因 strict CCD gate 作废；第 4 次正式同码 ABBA 为 control `54,512.5 ms`、candidate-control `54,584.0 ms`，仅 `0.131163%` 噪声，四样本 fixed-ASLR/CCD/NUMA/PMU/功能门禁全过，随后进入首条 K3 generation。 |
| `TNO0195` | `2026-07-28` | [SimpleTES K3 context window correction and resume](./TNO0195_simpletes_k3_context_window_correction_and_resume_20260728.md) | 旧首条 generation 在错误 `272000` context 下运行 `4,053 s` 后按指示优雅取消，无 final JSON/build/eval；`1,284,303 B` trace 与 `db_state_045321` 已保留。配置更正为 `1000000` 后从同一 control checkpoint 恢复，实际 private config 二次核验通过，剩余 `63` proposals 已继续运行。 |
| `TNO0196` | `2026-07-28` | [SimpleTES K3 parallel generation, subagents, and 1M catalog](./TNO0196_simpletes_k3_parallel_generation_subagents_and_context_catalog_20260728.md) | 根因确认 unknown-K3 metadata 将 `1000000` 钳为 `272000`；SimpleTES `50de044` 加入 private 1M catalog、K3-only 自由 3-subagent、4 路 generation 与 `10800s` timeout，全量 `213 passed`。旧实例由 `db_state_124118` 正常恢复，连续 `4 active/0 queued`、无 fallback；已追加两个 root 各自主 spawn `3` 个 subagent 的运行证据，尚无新 50k 结果。 |
| `TNO0197` | `2026-07-28` | [SimpleTES repair raw-response persistence and JSON diagnostics](./TNO0197_simpletes_repair_raw_response_persistence_and_json_diagnostics_20260728.md) | SimpleTES `c4e4a05` 修复 repair 仅见压平末尾 `2000` 字与 InvalidJSON 无定位：完整结构保持 response 在 retry 前写入 private `llm_attempts`，精确记录 line/column/character/byte；4 请求/12 artifacts 并发隔离，全量 `225 passed`。运行中旧实例未重启，修复从下次启动生效。 |
| `TNO0198` | `2026-07-28` | [SimpleTES GPT-5.6 Sol THJ switch and resume preflight](./TNO0198_simpletes_gpt56sol_thj_switch_and_resume_preflight_20260728.md) | K3 continuation 停止后固定 `db_state_153501`；launcher 保持 K3 默认并新增显式 model/effort，GPT 分支使用原生 structured/auto 且不接收 K3 agent/catalog；新 THJ config/auth 的真实 GPT preflight `1` repo tool、`632 chars` PASS，准备按 `64/32` 从既有 `3/32` valid 继续。 |
| `TNO0199` | `2026-07-29` | [SimpleTES K3/GPT post-RWA research completion](./TNO0199_simpletes_k3_gpt_post_rwa_research_completion_20260729.md) | post-RWA 连续搜索在 `64 attempts/15 valid` 自然停止；15 个 valid 均为正收益，最终 best 为 `53,742.50→51,534.50 ms`（减少 `2,208.00 ms/4.108480%`），并归档 K3/GPT 阶段、主要方向与失败审计。 |
| `TNO0200` | `2026-07-29` | [SimpleTES monotonic resume budget extension and GPT max launch](./TNO0200_simpletes_monotonic_resume_budget_extension_and_gpt_max_launch_20260729.md) | SimpleTES 以显式单调契约同时扩展全局/逐 chain resume budget，加入 `xhigh/max` CLI 兼容并通过全量 `231/231`；现已从 `64 attempts/15 valid` exact state 以 `gpt-5.6-sol/max`、`192 proposals/32 valid`、`4 gen` 正式续跑。 |
| `TNO0201` | `2026-07-30` | [SimpleTES GPT CodexExecError diagnosis](./TNO0201_simpletes_gpt_codexexecerror_diagnosis_20260730.md) | continuation 当前有 `15` 次 Codex status-1 failure；排除 effort、持续 auth、evaluator 和资源上限等系统性原因，确认 PATH warning 非根因证明，并定位 non-zero 分支删除 stdout JSONL、只留 stderr 的诊断缺口；运行仍在推进，修复应先持久化完整失败事件。 |
| `TNO0202` | `2026-07-30` | [SimpleTES Codex failure persistence, retry, and budget-256 restart](./TNO0202_simpletes_codex_failure_persistence_retry_and_budget256_restart_20260730.md) | SimpleTES 完整保存并脱敏 non-zero JSONL/stderr/final output，真实定位 provider capacity；加入分类退避 retry、稳定非 `/tmp` HOME、bounded repo inspection 和 exact extended-resume，full `239/239`。旧运行停于 `143 attempts/21 valid`，扩容后正式从 `150 attempts/21 valid` 以 `256/32`、GPT max、4 gen 续跑。 |
| `TNO0203` | `2026-07-30` | [SimpleTES Codex capacity session continuation](./TNO0203_simpletes_codex_capacity_session_continuation_20260730.md) | Stop hook 不覆盖 provider sampling error；SimpleTES 改用 exact thread ID 的 `codex exec resume ... continue`，默认每会话 `3` 次独立续跑且不消耗普通 retry，四 worker 不用 `--last`。focused `151/151`、full `245/245`、真实 GPT preflight 通过；运行中旧进程未重启，新机制下次启动生效。 |
| `TNO0204` | `2026-07-31` | [SimpleTES extended best-path ablation materialization and launch](./TNO0204_simpletes_extended_bestpath_ablation_materialization_and_launch_20260731.md) | 从 `db_state_235014` 恢复六段语义并构造 final gen150 加六个严格 final-minus-one arm，全部 remove/re-add 闭包且 validate-only PASS；已追加首版 runner 未保证跨 order 同 CCD 的勘误，正式结果见 TNO0205。 |
| `TNO0205` | `2026-07-31` | [SimpleTES extended best-path direct ablation result](./TNO0205_simpletes_extended_bestpath_direct_ablation_result_20260731.md) | 六项初轮 direct ablation 中 cold `+1.282339%` 可信，inline/constant/shift 为弱正向；已追加 residual/physical 同 binary 复测勘误：分别由旧 `−0.115054%/−0.247575%` 变为 `+0.023230%/−0.049291%`，新双 order 均跨零，故“稳定回退”不再成立，两项改判中性、未证明默认开启收益。 |
| `TNO0206` | `2026-07-31` | [SimpleTES RWA to gen150 endpoint replication](./TNO0206_simpletes_rwa_to_gen150_endpoint_replication_20260731.md) | 当前默认 RWA→四项 gen29 为 `+4.117704%`、RWA→完整六项为 `+4.135115%`；四项→六项 direct 为六项数值快 `0.181305%`，residual/physical 单项复测为 `+0.023230%/−0.049291%` 且双 order 都跨零。所有额外两项相关变化均低于 `1%`，统一判中性；四项默认子集不变，额外两项保持关闭。 |
| `TNO0207` | `2026-07-31` | [Four-positive Wolvrix landing and regression](./TNO0207_four_positive_wolvrix_landing_and_regression_20260731.md) | 四项已作为 Wolvrix 通用默认落入 `fd12d83`，parent executable snapshot 为 `de37459`；fresh Ninja `407/407`、focused、CTest `50/52`（仅两项历史失败）、pybind `29/29` 与 XS `32/32` 通过，不依赖或开启 targeted-direct。 |
| `TNO0208` | `2026-07-31` | [Four-positive SimpleTES repin and native 50k](./TNO0208_four_positive_simpletes_repin_and_native_50k_20260731.md) | SimpleTES `de12067` 已 repin 到 landed four-positive 空 control；production/功能/canary 通过，正式同 CCD 第二轮 RWA→native-four wall 为 `53,749.25→51,575.00 ms`，减少 `2,174.25 ms/4.045173%`，ABBA/BAAB gap `0.043458 pp`，四项最终 KEEP；未启动 research。 |
| `TNO0209` | `2026-07-31` | [SimpleTES post-four GPT max fresh launch](./TNO0209_simpletes_post_four_gpt_max_fresh_launch_20260731.md) | 新 fresh instance `73ee9786` 已用 `gpt-5.6-sol/max`、THJ config/auth、`64 proposals/32 valid`、`4 gen/1 eval` 启动并进入 initial control；首次错误 cwd 启动在 capacity continuation 时 fail-fast、未创建 checkpoint，失败日志已保留。 |
| `TNO0210` | `2026-07-31` | [SimpleTES Codex remote-compact/reconnect session continuation](./TNO0210_simpletes_codex_remote_compact_and_reconnect_session_continuation_20260731.md) | 当前实例四次长 trace 终止被定位为 remote compact，其中最新一次先出现 reconnect/stream disconnect；SimpleTES `6517bfc` 新增独立 exact-thread transient continuation，默认 `3` 次且不占 capacity/ordinary retry，full `251/251`。运行中旧进程未重启，新机制下次启动生效。 |
| `TNO0211` | `2026-08-01` | [SimpleTES post-four GPT max research completion](./TNO0211_simpletes_post_four_gpt_max_research_completion_20260801.md) | instance `73ee9786` 正常达到 `32/32` valid；最佳 gen28 pooled wall 为 `51,376.50→47,473.50 ms`（减少 `3,903.00 ms/7.596858%`），双 order gap `0.008800 pp` 且全门禁通过；优势来自 dominant event typed storage、decoded bool 与 batch-local snapshot，尚未落地或改默认。 |
| `TNO0212` | `2026-08-01` | [Hot-event best-path ablation design and materialization](./TNO0212_hot_event_bestpath_ablation_design_and_materialization_20260801.md) | 固定 `de37459/fd12d83` current-default，物化 exact search-path 与 final mechanical-decomposition 共六个 zero-option arm；全部 apply/schema gate 通过，预注册八组同 CCD ABBA+BAAB direct pair，parallel build 正在运行。 |
| `TNO0213` | `2026-08-01` | [Hot-event best-path direct ablation result](./TNO0213_hot_event_bestpath_direct_ablation_result_20260801.md) | 八组同 CCD direct pair 全部收敛；`B→TRBS` 为 `51,562.00→47,632.25 ms`（减少 `3,929.75 ms/7.621407%`，order gap `0.045683 pp`）。机械分解确认 typed storage `+2.748192%`、bool decode `+3.098466%`、bool snapshot `+1.969566%`，remap 单独中性；进入原则化门禁落地。 |
| `TNO0214` | `2026-08-01` | [Principled hot-event landing and native gate](./TNO0214_principled_hot_event_landing_and_native_gate_20260801.md) | TRBS 以 Wolvrix 通用 C++ 默认落地，并用 final-schedule exact-posedge reuse 替代 `event slots>=256`；fresh `407/407`、CTest `51/53`（仅两项历史失败）与功能 gate 通过。旧门禁→原则化门禁为 `47,567.25→47,597.00 ms`（`−0.062543%`，gap `0.072499 pp`），generated fingerprint 相同，判性能等价并保留。 |
| `TNO0215` | `2026-08-01` | [Principled hot-event SimpleTES repin and continuation readiness](./TNO0215_principled_hot_event_simpletes_repin_and_continuation_readiness_20260801.md) | SimpleTES `6a169d4` 已 repin 到 parent `52ba7d9` / Wolvrix `d3ed9de` 空 control；旧 four-positive checkpoint fail-close，bench `80/80`、full `251/251`、validate-only 与 GPT max dry-run 全过，未启动 research 或调用模型。 |
| `TNO0216` | `2026-08-01` | [SimpleTES principled-TRBS GPT max fresh research launch](./TNO0216_simpletes_principled_trbs_gpt_max_fresh_launch_20260801.md) | fresh instance `efb346a8` 已用 `gpt-5.6-sol/max`、THJ config/auth、`64 proposals/32 valid`、`4 gen/1 eval` 启动并进入原则化 TRBS empty-control evaluator；真实 preflight 通过，尚无 candidate 或本轮 50k 结果。 |
| `TNO0217` | `2026-08-03` | [SimpleTES principled-TRBS GPT max second fresh launch](./TNO0217_simpletes_principled_trbs_gpt_max_second_fresh_launch_20260803.md) | 上轮 `efb346a8` 达到 `32/32 valid` 后已退出；新 `instance-44cd457d` 明确不 resume、不 seed old best，以同一原则化 TRBS 空 control、`gpt-5.6-sol/max`、THJ config/auth 和 `64/32` 预算 fresh 启动，现处 initial evaluator。 |
| `TNO0218` | `2026-08-04` | [SimpleTES principled-TRBS second fresh completion](./TNO0218_simpletes_principled_trbs_second_fresh_completion_20260804.md) | `instance-44cd457d` 达到 `32/32 valid`；typed persistent-state storage best 为 `47,620.25→44,582.25 ms`（`3,038.00 ms/6.379639%`），同 digest 复测为 `47,692.00→44,669.00 ms`（`3,023.00 ms/6.338589%`），两轮 order gap 均 `<0.25 pp`。候选通用、零 option、功能/attribution gate 通过，尚待消融与 landing regression；已追加 alias、依赖链、数据/代码布局的机制解释与证据边界。 |
| `TNO0219` | `2026-08-04` | [SimpleTES typed-storage search budget-128/valid-64 resume launch](./TNO0219_simpletes_typed_storage_budget128_valid64_resume_launch_20260804.md) | `instance-44cd457d/db_state_000359` 已按 exact monotonic contract 原地续跑：保留 `40 attempts/32 valid/38 nodes`、四条 chain history 和 `6.379639%` best，将绝对预算 `64→128 generations`、累计目标 `32→64 valid`；GPT 5.6 Sol max、THJ config/auth、`4 gen/1 eval` 已实查运行，尚无扩容后的新性能结果。 |
| `TNO0220` | `2026-08-06` | [SimpleTES 64-valid node029-to-node032 migration](./TNO0220_simpletes_64valid_node029_to_node032_migration_20260806.md) | node029 因 whole-CCD evaluator retry 卡在 `34/64 valid` 后已 SIGINT 干净退出，final `db_state_020746` 为 `46 attempts/34 valid/40 nodes`；node032 同 NFS/commit/topology 接管，首次默认 Codex `0.145.0` 启动在零结果时撤销，最终固定与原机一致的 NVM `0.146.0` exact restart，GPT max `4 gen/1 eval` 已运行，尚无远端新性能结果。 |
| `TNO0221` | `2026-08-06` | [SimpleTES node032 post-reboot exact restart](./TNO0221_simpletes_node032_postreboot_exact_restart_20260806.md) | node032 于 `17:03:46` 重启，中断前 1 active/3 queued evaluations 未持久化且无新 checkpoint；重新排除 `db_state_021244` 审计状态，从 `db_state_020746` 精确恢复 `46 attempts/34 valid/40 nodes` 和绝对 `128/64` 预算，显式 NVM Codex `0.146.0` 的 GPT max 四个 gen workers 已运行。 |
| `TNO0222` | `2026-08-06` | [SimpleTES node032 scanner recovery and retry diagnostics](./TNO0222_simpletes_node032_scanner_recovery_and_retry_diagnostics_20260806.md) | post-reboot `36` 次 retry 确认为 fresh control build 缺 `clang-scan-deps-19`，非 CCD；不停止现有实例完成 package/cache 在线恢复，evaluator 已越过失败点进入 SimTop emit。SimpleTES `a32116d` 新增 matching-scanner launch gate 与脱敏限长 retry root cause，full `254/254` 通过；暂无新 50k walltime。 |
| `TNO0223` | `2026-08-07` | [SimpleTES c333 NUMA fixed-page gate retry diagnosis](./TNO0223_simpletes_c333_numa_page_gate_retry_diagnosis_20260807.md) | scanner 恢复后已推进至 `54/64` valid；当前 c333 候选把 ELF 缩小 `3,874,816 B/4.243101%`，其 `19,877` 个 file pages 全部位于目标 NUMA node，却因固定 `20,000` 页门槛被误判并持续 retry。八轮 immutable attempts 与跨 CPU/NUMA node 复现已闭合根因；本阶段未停运行、未改代码，待改为候选规模相对 coverage gate。 |
| `TNO0224` | `2026-08-07` | [SimpleTES relative NUMA page gate hot recovery](./TNO0224_simpletes_relative_numa_gate_hot_recovery_20260807.md) | SimpleTES `414ad80` 以 control/candidate ELF `PT_LOAD` footprint 保持相同最低 coverage，live c333 门槛由固定 `20,000` 原则化缩放为 `19,151`，`19,877/19,877` 本地页严格通过；`108/108` focused、`256/256` full 通过，原 launcher/main 未重启。正式 pooled wall 为 `48,120.25→44,186.75 ms`，减少 `3,933.50 ms/8.174313%`，成为 `55/64` valid 新 best。 |
| `TNO0225` | `2026-08-12` | [SimpleTES fixed NUMA coverage across baseline repins](./TNO0225_simpletes_fixed_numa_coverage_across_baseline_repins_20260812.md) | SimpleTES `869a11a` 将 NUMA 门槛固定为协议 coverage `20,000/22,260=89.847260%`，不再从当前 control ELF 漂移；`21,314→19,151` 与最终 best `20,401→18,330` 回归、repin invariance、非法配置和 `115` focused/`263` full tests 全通过。 |
| `TNO0226` | `2026-08-12` | [SimpleTES principled TRBS 64-valid completion](./TNO0226_simpletes_principled_trbs_64valid_completion_20260812.md) | node032 实例 `44cd457d` 最终 `83` generation attempts、`74` completed evaluations、`64/64 valid`；最佳 `297a7032` 的 SimTop 50k wall 为 `48,074.00→43,300.00 ms`，减少 `4,774.00 ms/9.930524%`，ABBA/BAAB gap `0.094283 pp`，尚未 landing/default。 |
| `TNO0227` | `2026-08-12` | [Typed-state best-path ablation design and materialization](./TNO0227_typed_state_bestpath_ablation_design_and_materialization_20260812.md) | 在 node032 固定原则化 TRBS pin，预注册 `B→S8→SB→SBV` 三个累计阶段和 `B→SBV` endpoint；gen60/gen68/gen72 三个 zero-option emitter arm 已物化并通过 validate-only，fresh parallel build/runtime 结果待补。 |
| `TNO0228` | `2026-08-12` | [Typed-state ablation paused for node032 load](./TNO0228_typed_state_ablation_node032_infrastructure_pause_20260812.md) | 三个 arm 与共享 control 均完成并行构建及功能/身份门禁；`B→S8` 已落盘 `72` 次 wrapper attempt，但完整 ABBA+BAAB 为 `0`，均因外部负载或 strict quiet-CCD gate 作废，按指示暂停，未改默认。 |
| `TNO0229` | `2026-08-13` | [Typed-state best-path ablation node032 runtime completion](./TNO0229_typed_state_bestpath_ablation_node032_runtime_completion_20260813.md) | 四组同 CCD ABBA/BAAB 全部完成且 gap `<0.25 pp`：`B→S8` `48,023.50→44,595.25 ms`（`7.138693%`），`S8→SB` `44,760.25→44,195.25 ms`（`1.262281%`），`SB→SBV` `44,198.00→43,373.50 ms`（`1.865469%`），endpoint `B→SBV` `48,054.25→43,335.50 ms`（`9.819631%`）；所有功能/ASLR/NUMA/PMU 门禁通过，未改默认。 |
| `TNO0230` | `2026-08-13` | [Typed-state Wolvrix landing and regression](./TNO0230_typed_state_wolvrix_landing_and_regression_20260813.md) | 明确为三项增量机制、四个实验 arm；完整 `SBV` 已在 Wolvrix 通用 emitter 默认启用，node032 同 CCD SimTop 50k 为 `48,162.50→43,434.50 ms`，减少 `4,728.00 ms/9.816766%`，gap `0.048671 pp`；功能/构建 gate 通过，SimpleTES 已以 `40baf93` repin 到新 parent/Wolvrix。 |
| `TNO0231` | `2026-08-13` | [GSIM/GrhSIM PGO SimTop walltime comparison](./TNO0231_pgo_gsim_grhsim_simtop_walltime_comparison_20260813.md) | node030 完成 GSIM/GrhSIM LLVM PGO 构建，node032 同一 `node1:152-159,344-351` CCD/CPU 152 上完成 fixed-ASLR ABBA+BAAB；GSIM-PGO `17,097.50 ms` 对 GrhSIM-PGO `32,141.25 ms`，GrhSIM 慢 `15,043.75 ms/87.988010%`。跨引擎临时 runner 仅旁路不适用的绝对 ELF 页数下限，NUMA local ratio、PMU、功能和连续 CCD 门禁均保留。 |
| `TNO0232` | `2026-08-13` | [PGO toolchain and plain cross-check](./TNO0232_pgo_toolchain_and_plain_crosscheck_20260813.md) | 审计确认本轮实际是 `PGO_BOLT=0` 的 LLVM instrumentation PGO、没有使用 BOLT；已追加勘误：旧 GSIM plain 复用了 PGO model objects，原 plain 性能与 plain/PGO 收益结论撤销，详见 TNO0233。 |
| `TNO0233` | `2026-08-13` | [Clean RTL-to-GSIM plain rebuild and correction](./TNO0233_clean_rtl_gsim_plain_rebuild_and_correction_20260813.md) | 从 Scala/Chisel RTL 全新生成 SV/FIR 和 `332` 个 GSIM C++，全量重编且无 PGO/BOLT；node032 正式 clean plain pooled wall 为 `30,907.75 ms`。旧 `17,032.25 ms` plain 被证实是 PGO model objects + plain harness 的混合产物；与历史 PGO 的 `45.144017%` 差值因 fresh C++ manifest 不同只能作跨构建观察。 |
| `TNO0234` | `2026-08-14` | [Clean plain GSIM/GrhSIM walltime comparison](./TNO0234_clean_plain_gsim_grhsim_walltime_comparison_20260814.md) | 基于同一 fresh RTL 全量发射/编译当前默认 GrhSIM，GSIM/GrhSIM 均为无 PGO/BOLT 的普通 `-O3`；node032 同 CCD fixed-ASLR 正式 pooled wall 为 `30,643.00→42,837.25 ms`，GrhSIM 慢 `12,194.25 ms/39.794570%`，ABBA/BAAB gap `0.179811 pp`，八个样本的功能/NUMA/PMU/连续负载门禁均通过。 |
| `TNO0235` | `2026-08-18` | [SimpleTES typed-state budget-128/valid-64 resume launch](./TNO0235_simpletes_typed_state_budget128_valid64_resume_launch_20260818.md) | 从 `instance-5f0c84e9/db_state_012346` 精确续跑；上一轮 `43 attempts/41 evals/32 valid` 已按单调契约扩展到 `128 generations/64 valid`，gpt-5.6-sol/max、`4 gen/1 eval` 在 node032 已进入调度，尚无本轮新性能结果。 |
| `TNO0236` | `2026-08-19` | [SimpleTES typed-state budget-256/valid-64 resume launch](./TNO0236_simpletes_typed_state_budget256_valid64_resume_launch_20260819.md) | 从 `db_state_211121` 精确续跑；上一轮 `128 attempts/51 evals/38 valid` 因 provider `429` 有 `74` 次 generation failure，现按单调契约扩展到 `256 attempts`、累计 valid 目标保持 `64`，gpt-5.6-sol/max、`4 gen/1 eval` 已在 node032 进入调度。 |
| `TNO0237` | `2026-08-19` | [SimpleTES rate-limit and transport-timeout continuation](./TNO0237_simpletes_rate_limit_and_timeout_continuation_20260819.md) | 活跃 run.log 顶层快照为 `74` 次 429、`6` 次 remote compact、`1` 次 transport-backed timeout；SimpleTES `25d6b7a` 将显式 429 和带 reconnect/有效 thread ID 的 timeout 纳入有界 exact-thread `continue`，focused `79/79`、full `265/265` 通过。现有 node032 任务未重启，新规则下次启动或恢复生效。 |
| `TNO0238` | `2026-08-19` | [RepCut 1/2/4/8 thread-scaling experiment protocol](./TNO0238_repcut_thread_scaling_experiment_protocol_20260819.md) | 预注册同一 RepCut 冻结结果下 native 与 partitioned 两条路径的 1/2/4/8 线程矩阵；固定同 CCD 嵌套物理核、每档 ABBA+BAAB、共 32 个正式样本，并明确相同 `N` 是相同 CPU 预算而非相同 OS 线程组成。 |
| `TNO0239` | `2026-08-19` | [RepCut thread-scaling build and functional gates](./TNO0239_repcut_thread_scaling_build_and_functional_gates_20260819.md) | 最终口径见第 8 节：冻结 RTL 匹配 `CPU_XIANGSHAN`/79263 generated-src，通用 `CPU_DEMO`/45871 fresh-G 构建排除；匹配 profile 的 native t1 与 partitioned N=1/2/4/8 在 cycle 605 触发 `csr_dbltrp_inMN`，正式矩阵被功能门阻断。 |
| `TNO0240` | `2026-08-19` | [RepCut thread-scaling performance results and evidence boundary](./TNO0240_repcut_thread_scaling_performance_results_20260819.md) | 最终执行口径见第 7 节：匹配 XiangShan profile 下 `run_xs_repcut` 与 `run_xs_repcut_verilator` 的 N=1/2/4/8 正式矩阵尚未启动，headline 均为 `N/A`；fresh-G 错误 profile 与历史 timing 均不冒充当前矩阵。 |
| `TNO0241` | `2026-08-20` | [RepCut DPI output schedule root cause](./TNO0241_repcut_dpi_output_schedule_root_cause_20260820.md) | native t1 的 cycle 605 assertion 已由严格单点调度 A/B 完成因果闭环：`void DPI(output)` 被误判为无返回 effect，emitter 拆散 producer/commit，t1 与 partitioned part3 形成 `reader→commit→producer`；仅复刻 t2 顺序即可跑满 C10000。早期 `debug_part` early-publish 被移除且替代 phase 未实现，partitioned 判定为高置信度，代码修复尚未实施。 |
| `TNO0242` | `2026-08-21` | [XiangShan direct Verilator single-core/single-thread CoreMark 2-iteration walltime](./TNO0242_xiangshan_direct_verilator_single_core_single_thread_coremark2_walltime_20260821.md) | 直接 Verilator 的 guest 单核/host 单线程 plain `-O3`、无 PGO/BOLT、编译含 FST 且运行不落波形；CoreMark 2 iter 功能 PASS，唯一 host walltime `738499 ms`。入场 quiet gate PASS，但运行期 CCD 被外部负载污染（other-15 mean/min `94.209%/82.210%`），故仅作为 node029 单次 raw snapshot，不作正式跨版本比较。 |
| `TNO0243` | `2026-08-21` | [XiangShan node032 direct Verilator 50k-cycle diagnostic run](./TNO0243_xiangshan_node032_direct_verilator_50k_cycle_diagnostic_20260821.md) | SSH 到 node032 复用 TNO0242 emu，单核/`EMU_THREADS=1`、运行无波形并加 `-C 50000`；在 `cycles=50000` 以 `EXCEEDING CYCLE/INSTR LIMIT` 停止，`Host time spent=181090 ms`、外层 `3:01.24`，不是完整 CoreMark PASS。 |
| `TNO0244` | `2026-08-21` | [XiangShan direct Verilator 2/4/8/16-thread scaling on node032 (50k-cycle serial runs)](./TNO0244_xiangshan_verilator_thread_scaling_node032_50k_20260821.md) | 按用户要求无 NUMA 绑定并行编译 `EMU_THREADS=2/4/8/16`（`-j96`、FST on、无 PGO/BOLT），随后在 node032 串行测 50k；external wall 为 `89.18/47.93/28.94/22.46 s`，四次均按 cycle limit 正常 `rc=0`，受 node032 外部负载影响，仅作 raw scaling snapshot。 |
| `TNO0245` | `2026-08-22` | [XiangShan RepCut partition-count sweep protocol](./TNO0245_xiangshan_repcut_partition_count_sweep_protocol_20260822.md) | 预注册同一 `SimTop` GRH、同一 Wolvrix binary、固定 deterministic-quality/seed 0/epsilon 0.015，仅改变 `k=2/4/8/16/32/64` 的 transform-only 串行 sweep；分离核心复制率、source/final 净变化、权重/op/通信不平衡和 cut/KM1，并在首档后追加保留错误复制率口径的勘误。 |
| `TNO0246` | `2026-08-22` | [XiangShan RepCut partition-count sweep results](./TNO0246_xiangshan_repcut_partition_count_sweep_results_20260822.md) | 六档 RepCut 与全部结构门禁均 PASS，`k=32` 逐字节复现旧 `.part32`；核心复制率 `0.2771%→9.0366%`、final op 不平衡 `20.307%→657.243%`、KM1 `895,474→23,455,797`，weight 不平衡仍约束在 1.5% 内。仅为静态 transform 结果，不宣称 runtime 最优或仿真正确。 |
| `TNO0247` | `2026-08-24` | [SimpleTES typed-state budget-512/valid-128 node030 resume launch](./TNO0247_simpletes_typed_state_budget512_valid128_node030_resume_launch_20260824.md) | 上段在 `185 attempts/98 evals/64 valid` 正常结束，best SimTop 50k 为 `43,564.25→41,575.00 ms`（提升 `4.566244%`）；SimpleTES `c8f1da8` 将受控 resume ceiling 扩至 `512`，node030 补齐 `clang-scan-deps-19` 后从最终 checkpoint 精确续跑到累计 `128 valid`，GPT max `4 gen/1 eval` 已运行。 |
| `TNO0248` | `2026-08-25` | [SimpleTES g158 node030 fresh same-CCD retest](./TNO0248_simpletes_g158_node030_fresh_sameccd_retest_20260825.md) | g158 fresh 同 CCD ABBA+BAAB 正式 pooled wall 为 `43,223.00→42,491.25 ms`，减少 `731.75 ms/1.692964%`，order gap `0.084992 pp`；确认方向为正但历史 `4.566244%` 幅度被异常 order 高估，尚未 landing/default。 |
| `TNO0249` | `2026-08-25` | [RepCut DPI effect and atomic emit fix](./TNO0249_repcut_dpi_effect_and_atomic_emit_fix_20260825.md) | 实现 TNO0241 的三层修复：`void DPI(output/inout)` 纳入 effect result/ASC 共置，SV 在同一事件块显式保证 producer 先于状态提交，partitioned runtime 支持 early-effect phase 并严格校验线程数；focused 3/3、CTest 52/53，仅余既有 `transform-comb-lane-pack` 失败，完整 SoC gate 另行归档。 |
| `TNO0250` | `2026-08-25` | [RepCut v7 DPI fix build and gate](./TNO0250_repcut_dpi_fix_v7_build_and_gate_20260825.md) | post-fix v7 manifest/source/generated identity、partitioned v7 build、C=100/C=10000 八配置 functional gate 与 C=30000 golden 全部闭合；focused 3/3、CTest `52/53`，正式 quiet-CCD 32 样本被共享主机 `hapi/GC/HeapHelper` 外部负载门禁阻断，raw 保留。 |
| `TNO0251` | `2026-08-25` | [RepCut v7 thread-scaling results and gate boundary](./TNO0251_repcut_v7_thread_scaling_results_and_gate_boundary_20260825.md) | 给出同 manifest canary 的 `run_xs_repcut`/`run_xs_repcut_verilator` C=100/C=10000 1/2/4/8 单样本 snapshot；正式 C=30000 32 样本均值/ABBA/BAAB headline 记为 `N/A — host quiet/foreign gate blocked`，未用污染样本冒充性能结论。 |
| `TNO0252` | `2026-08-26` | [g158 ranking-policy sensitivity ablation on node031](./TNO0252_g158_policy_sensitivity_ablation_node031_20260826.md) | 优雅停止 node030 的 SimpleTES（151 eval、108/128 valid）；g158 的三个内部排序策略敏感性候选在 node031 共享 control 后并行 fresh build，`29/29` 与 100/10k 功能门禁全部通过，但 24 个 CCD 被外部 gem5/IDE 等负载击穿 strict quiet gate，27 次同 CCD 配对预尝试无 workload 样本，未改默认或生产代码。 |
| `TNO0253` | `2026-08-27` | [g158 ranking-policy sensitivity runtime completion on node032](./TNO0253_g158_policy_sensitivity_runtime_node032_20260827.md) | node029-node032 同款门禁选出 `24/24` CCD 通过的 node032；三臂串行同 CCD ABBA+BAAB 均首轮收敛：demand-only `43,576.75->43,066.00 ms`（`1.172070%`）、signature-only `43,350.25->42,714.75 ms`（`1.465966%`）、full `43,374.75->42,809.00 ms`（`1.304330%`），gap 均 `<0.25 pp`，24 个样本全门禁通过，未 landing/default。 |
| `TNO0254` | `2026-08-27` | [g158 Wolvrix landing implementation checkpoint](./TNO0254_g158_wolvrix_landing_implementation_checkpoint_20260827.md) | 冻结 g158 的完整排序策略已提交到 Wolvrix 通用 GrhSIM C++ emitter，默认路径无新增选项、无 SimTop/变量名特判；源码 focused 构建与 emitter/调度测试通过。当前 parent executable snapshot 已建立，50k 前后性能回归与 SimpleTES repin 在后续增量记录中闭合。 |
| `TNO0255` | `2026-08-27` | [g158 fresh build and function regression](./TNO0255_g158_fresh_build_and_function_regression_20260827.md) | 基于同一冻结输入分别构建 baseline/landed immutable 快照；两边 fresh `187/187`、focused `29/29`、C=100/10000 功能门禁全过，生成差异仅为 `state_logic_storage_t` 物理声明顺序。50k walltime 仍待空闲 CCD 的正式增量记录。 |
| `TNO0256` | `2026-08-27` | [g158 landing native 50k walltime regression](./TNO0256_g158_landing_native_50k_walltime_regression_20260827.md) | node030 同 CCD fixed-ASLR ABBA+BAAB 正式 pooled wall 为 `43,702.00→42,959.00 ms`，减少 `743.00 ms/1.700151%`，order gap `0.232711 pp`；八个样本的功能/NUMA/PMU/连续负载门禁全过，g158 KEEP/default。 |
| `TNO0257` | `2026-08-27` | [SimpleTES post-g158 GPT max fresh research launch](./TNO0257_simpletes_post_g158_gpt_max_fresh_launch_20260827.md) | node030 在连续 strict whole-CCD 扫描中最空闲；post-g158 空 control 已以 `gpt-5.6-sol/max`、THJ config/auth、`64 proposals/32 valid`、`4 gen/1 eval` fresh 启动为 instance `0c4c9416`，真实 preflight 通过，initial control 正在评估。 |
| `TNO0258` | `2026-08-27` | [SimpleTES control bias invalidation and mirrored protocol fix](./TNO0258_simpletes_control_bias_invalidation_and_mirrored_protocol_fix_20260827.md) | TNO0257 实例同 ELF initial control 测出 `-1.565726%`，唯一候选双 order gap `0.513323 pp` 且跨 CPU，故整树冻结作废；SimpleTES `e107401` 改为同 CPU 原子 `ABBABAAB`、control self-bias/order-gap `<0.25` 严格门禁、通过后 score 精确归一为 `1.0`，schema-v3 拒绝旧树，full `277/277`。 |
| `TNO0259` | `2026-08-27` | [SimpleTES corrected fresh restart initial control](./TNO0259_simpletes_corrected_fresh_restart_initial_control_20260827.md) | node032 fresh RTL-to-GrhSIM rebuild 后，前两次八样本组因 order gap `0.431217/0.965376 pp` 作废；第三次同 CCD/CPU 组 raw self-bias `0.012264%`、gap `0.181031 pp` 通过，schema-v3 initial score 精确 `1.000000`，已启动 `4 gen/1 eval`，尚无 candidate 性能结论。 |
| `TNO0260` | `2026-08-30` | [SimpleTES g158 mirrored budget-128/valid-64 resume launch](./TNO0260_simpletes_g158_mirrored_budget128_valid64_resume_launch_20260830.md) | 原树以 `44 attempts/35 evals/32 valid` 正常结束，best `44,252.50->43,268.75 ms`（`2.223038%`）；从 final `db_state_223640` 精确恢复，累计预算单调扩到 `128/64`，node031 因缺 clang-scan-deps-19 未创建状态，正式 node030 `4 gen/1 eval` 已运行。 |
| `TNO0261` | `2026-08-30` | [SimpleTES post-g158 gen38 best node030 可靠性复测](./TNO0261_simpletes_post_g158_gen38_best_node030_retest_20260830.md) | node030 同 CCD schema-v3 正式复测为 `43,504.00->42,959.00 ms`（减少 `545.00 ms/1.252758%`），ABBA/BAAB gap `0.045690 pp`；正收益复现，但历史 `2.223038%` 幅度判为高估。运行中的 `128/64` auto research 未停止或重启。 |
| `TNO0262` | `2026-08-31` | [SimpleTES schema-v4 single-group stability gates](./TNO0262_simpletes_schema_v4_single_group_stability_gates_20260831.md) | node030 auto research 已优雅停止于 `49/64 valid` 并保存 `db_state_014436`；SimpleTES `48bb78c` 的 schema-v4 在单个同 CPU `ABBABAAB` 组增加 role block shift `<1%`、spread `<2%`、cycles/wall coherence 与 `cycles:u/task-clock` proxy 门禁，历史 `+4.566244%/+2.223038%` 异常组被拒、fresh g158 `+1.692964%` 组全过；full `299/299`，未加入第二独立确认组或重启研究。 |
| `TNO0263` | `2026-08-31` | [SimpleTES gen38 schema-v4 replay rebase and continuation](./TNO0263_simpletes_gen38_schema_v4_replay_rebase_launch_20260831.md) | 旧 schema-v3 树只读保留；gen38 精确 seed 以 node030 fresh 复测原始 perf 通过 schema-v4 replay，active root 改为 `43,504.00->42,959.00 ms`（`545.00 ms/1.252758%`，score `1.012686515`）。SimpleTES `e79733f` 全套 `303/303` 后在 node030 以剩余 `89 attempts/34 valid`、GPT max、`4 gen/1 eval` 启动 instance `47e6f5d9`。 |
| `TNO0264` | `2026-09-01` | [XiangShan RepCut part3 imbalance root cause](./TNO0264_xiangshan_repcut_part3_imbalance_root_cause_20260901.md) | `k=32` 的 `part_3` final ops 为 `912,331`（均值 `4.688x`），但 solver weight 仅为均值 `1.015x`；`aid=4` giant ASC 自身含 `464,599` comb 和 `26,848` sink，却只以 `22,577` vertex weight 参与平衡。确认应先修 closure/shared-piece 负载口径；已追加 `47.419%` 仅为粗总量对比、不是 exact omitted compute 比例的勘误。 |
| `TNO0265` | `2026-09-01` | [RepCut closure-aware weight implementation](./TNO0265_repcut_closure_aware_weight_implementation_20260901.md) | 新增默认关闭的 `baseline/closure-aware` 离散模式：守恒 fair-share vertex、compute+communication KM1 edge、exact closure stats 与 bounded whole-ASC refine；baseline 仍默认，focused `5/5`、Python `10/10`、full CTest `52/53`（仅历史 comb-lane-pack）通过，未拆 ASC 或改 state 语义。 |
| `TNO0266` | `2026-09-01` | [XiangShan RepCut closure-weight K32 static A/B](./TNO0266_xiangshan_repcut_closure_weight_k32_static_ab_20260901.md) | 同 binary K32 A/B 的十项身份 gate 全过；exact/final-op max 分别 `-34.421%/-33.274%` 并达到 giant closure 下界，但 exact/final-op total `+3.012%/+4.480%`、compute/communication KM1 `+60.414%/+56.822%`。保留实验模式、不改默认，进入独立 runtime gate。 |
| `TNO0267` | `2026-09-01` | [SimpleTES quiet-CCD retry default expansion](./TNO0267_simpletes_quiet_ccd_retry_default_20260901.md) | `GRHSIM_INFRA_RETRIES` 默认由 `2` 提高到 `99`，使一次已构建 evaluator 最多执行 `100` 次严格 runtime 尝试；显式环境值仍覆盖默认。focused `3/3`、full `304/304` 通过；node030 活跃实例显式为 `8`，未热变更或重启。 |
| `TNO0268` | `2026-09-02` | [XiangShan RepCut closure-weight runtime build and function gate](./TNO0268_xiangshan_repcut_closure_weight_runtime_build_and_function_gate_20260902.md) | 已追加重要勘误：attempt-2 baseline/candidate 混用 Clang21/19 package object，旧 runtime A/B 全部 INVALID；clean-v4 排除 package cache 后统一 Clang21 fresh build，1,386/1,422 个 partition object 与外层对象身份通过，两个 ELF 的 C=100 AB/BA 功能门闭合。 |
| `TNO0269` | `2026-09-02` | [XiangShan RepCut closure-weight N=1 per-partition runtime diagnostic](./TNO0269_xiangshan_repcut_closure_weight_n1_partition_runtime_diagnostic_20260902.md) | node033 同 CPU AB/BA diagnostic 中 eval max `-19.796%`、CV `-41.918%`，但 eval sum `+27.335%`、Host mean `+23.631%`；node038 单序同方向但幅度为 max `-33.331%`、sum/Host `+6.942%/+6.199%`。方向为削峰但增加串行工作量，所有 runtime audit 因 foreign ticks 未过 strict，只保留诊断结论；默认不变。 |
| `TNO0270` | `2026-09-02` | [SimpleTES automatic proof-backed runtime reuse](./TNO0270_simpletes_automatic_proof_backed_runtime_reuse_20260902.md) | retryable runtime infrastructure outcome 在完整 immutable attempt 提交后自动切到 runtime-only evaluator，复用已验证 ELF/image/NEMU，不再重复 clone/build；focused `138/138`、full `322/322`，本阶段未跑 50k，性能结论 N/A。 |
| `TNO0271` | `2026-09-03` | [SimpleTES gen38 cumulative budget-256/valid-128 resume and prompt bound](./TNO0271_simpletes_gen38_budget256_valid128_resume_and_prompt_bound_20260903.md) | 上段正常达到物理 `34/34 valid`，累计目标现由 `128/64` 翻倍为 `256/128`，对应迁移实例单调扩容 `89/34→217/98`；修复 chain3 将完整 nested metrics 塞入 prompt 导致 `1,093,102>1,048,576` 字符的确定性失败，同组请求降至 `126,088` 字符，full `324/324`。已从未污染的 `db_state_211206` 在 node030 以 GPT max、`4 gen/1 eval` 正式续跑。 |
| `TNO0272` | `2026-09-04` | [XiangShan RepCut closure-weight N=1 node030 CCD80 runtime diagnostic](./TNO0272_xiangshan_repcut_closure_weight_n1_node030_ccd80_runtime_diagnostic_20260904.md) | 原始 AB/BA diagnostic 观察到 Host `+47.367%`、eval sum `+56.329%`、max `-0.671%`；已追加重要勘误：TNO0273 证实两臂 executable page-cache NUMA 驻留不对称，这些数值不得再解释为算法固有代价。 |
| `TNO0273` | `2026-09-04` | [XiangShan RepCut N=1 frontend NUMA page root cause](./TNO0273_xiangshan_repcut_n1_frontend_numa_page_root_cause_20260904.md) | 运行中 `numa_maps` 确认原始 baseline text 约 `98.95%` 本地、candidate 约 `99.27%` 远端；PMU 将额外 cycles 定位到 frontend latency。两侧逐字节相同 ELF 在 NUMA0 tmpfs 本地化后，total/cycles 只回退 `4.068%/3.956%`，eval sum `+4.428%`、max `-33.810%`；撤销“并行加速无效”判断，正式 page-local AB/BA 与 N>1 gate 待补。 |
| `TNO0274` | `2026-09-04` | [XiangShan RepCut N=1 page-local runtime protocol fix](./TNO0274_xiangshan_repcut_n1_page_local_runtime_protocol_fix_20260904.md) | 新 v2 runner 为每个 order/arm 在目标 NUMA tmpfs 建立独占 ELF/image/NEMU inode，目标核 copy/SHA；以 maps dev+inode 的 RX VMA 关联 numa_maps，C=10000 至少 3 个有效采样并硬门 resident coverage/local ratio。汇总器隔离 legacy/v2，9 个聚焦测试通过；正式复测见 TNO0275。 |
| `TNO0275` | `2026-09-04` | [XiangShan RepCut N=1 page-local AB/BA on node033](./TNO0275_xiangshan_repcut_n1_page_local_ab_ba_node033_20260904.md) | node030 CI 风暴后按允许节点轮询，在 node033 CPU64 完成同机 page-local AB/BA；四个 C=10000 ELF/NEMU 均 `remote=0`。pooled Host/instructions/cycles 为 `+5.283%/+5.377%/+5.280%`，IPC/频率不变；eval sum `+5.887%`、max `-32.009%`、CV `-40.245%`，确认真实 trade-off 是增加串行总 work 换削峰。diagnostic 非 strict，N=8/32 未运行；已记录 v2 elapsed 混入 audit 尾巴，N>1 前须修。 |
| `TNO0276` | `2026-09-05` | [SimpleTES Gen61 best rebuilt-binary formal retest](./TNO0276_simpletes_gen61_best_rebuilt_binary_formal_retest_20260905.md) | 复用同一 Gen61 patch 的独立重建 control/candidate ELF，在 node031 完成 schema-v4 formal `ABBA+BAAB`；pooled wall `43,580.00→41,599.75 ms`，减少 `1,980.25 ms/4.543942%`，score `1.0476024495`，order gap `0.092101 pp`，全部门禁通过。历史 `5.520446%` 保留但 exact ELF 已不可恢复；未改源码或默认。 |
| `TNO0277` | `2026-09-07` | [XiangShan RepCut N=8/N=32 page-local comparison protocol](./TNO0277_xiangshan_repcut_n8_n32_page_local_protocol_20260907.md) | 固定 clean-v4/K32/C10000，计划同 NUMA 新旧 AB/BA；修正 workload/audit 计时边界，明确 global_update 含拷贝与同步、per-part sum 不等于并行 wall。N32 审计更新见 TNO0278，已追加完成状态，结果见 TNO0279。 |
| `TNO0278` | `2026-09-07` | [XiangShan RepCut parallel CPU audit and balanced capture protocol](./TNO0278_xiangshan_repcut_parallel_cpu_audit_capture_protocol_20260907.md) | N32 首轮 proc-stat total 与 wall 不闭合，target busy 门有方向性筛选风险；保留拒绝记录，v5 增加十字段/读取窗口证据并修正 worker 采样错位。新增固定 AB/BA capture，性能每臂只启动一次、不按残差重抽，结果明确非正式 clean。 |
| `TNO0279` | `2026-09-07` | [XiangShan RepCut N=8/N=32 communication runtime diagnostic](./TNO0279_xiangshan_repcut_n8_n32_communication_runtime_diagnostic_20260907.md) | node030 page-local 新旧 AB/BA：N8 Host `16.8625->15.5945 s`，update 基本持平；N32 balanced capture Host `14.0425->10.5835 s`（-24.632%），eval/update phase `-30.440%/-13.315%`，update 占比升到 34.219%。页面/worker 通过，保留 CPU accounting 失败与 diagnostic 限制，不改默认。 |
| `TNO0280` | `2026-09-07` | [XiangShan RepCut N=K=32 four-stage experiment plan](./TNO0280_xiangshan_repcut_nk32_four_stage_experiment_plan_20260907.md) | 用户授权依次实测调度/host、CCD 映射、接收方更新、通信后处理；固定 N=K=32，以 clean-v4 closure-aware 为起点，事前固定阶段选择规则，不拆 ASC、不改默认。已追加状态：准备/完整模型复现通过，40 次 admission 全拒绝、0 launch，四项实测未完成，见 TNO0286..0288。 |
| `TNO0281` | `2026-09-07` | [XiangShan RepCut N=K=32 scheduler build gate](./TNO0281_xiangshan_repcut_nk32_scheduler_build_gate_20260907.md) | common-only no-op 重建逐字节复现 frozen ELF；保留 1422 模型对象、ABI 与原编译选项，实验 legacy/pipeline-workers/pipeline-host 构建与 mock 通过，等待真实功能/性能 gate。 |
| `TNO0282` | `2026-09-07` | [XiangShan RepCut N=K=32 measurement protocol gate](./TNO0282_xiangshan_repcut_nk32_measurement_protocol_gate_20260907.md) | 显式 A/B 与实际编译源身份、Host lane/辅助线程分类，保留固定 balanced capture/页面门；新 runner 冻结、35 项测试通过。 |
| `TNO0283` | `2026-09-07` | [XiangShan RepCut N=K=32 CCD mapping structural gate](./TNO0283_xiangshan_repcut_nk32_ccd_mapping_structural_gate_20260907.md) | 由已校验生成代码重建 5137 个实际拷贝端点；固定四 CCD 容量，跨 CCD payload 286194->192598 bytes/update，-32.704%，仅静态候选，等待运行。 |
| `TNO0284` | `2026-09-07` | [XiangShan RepCut N=K=32 pull update build gate](./TNO0284_xiangshan_repcut_nk32_pull_update_build_gate_20260907.md) | 保持全部拷贝语句/顶层输出，接收方重分组 exact-once/宽度门与 14 tests 通过；独立 common/update 重建通过，静态单 owner 最大负载上升，待实测。 |
| `TNO0285` | `2026-09-07` | [XiangShan RepCut N=K=32 communication refinement tool gate](./TNO0285_xiangshan_repcut_nk32_communication_refinement_tool_gate_20260907.md) | 隔离单 TU 库支持 frozen assignment 导入/CSR导出，7 集成测试通过；通信校准 12 tests、whole-ASC 后处理 14 tests，明确 words64/packing 转移限制。完整 control 导出进行中，尚无校准候选或收益结论。 |
| `TNO0286` | `2026-09-07` | [XiangShan RepCut N=K=32 resource blocker](./TNO0286_xiangshan_repcut_nk32_resource_blocker_20260907.md) | 全部允许节点双 NUMA 轮询；4 次 pair 尝试共 40 次 admission 拒绝、实际 launch=0。短扫曾通过但启动门未通过，没有 BA/性能 summary，不放宽门槛或改默认。 |
| `TNO0287` | `2026-09-07` | [XiangShan RepCut N=K=32 full control reproduction](./TNO0287_xiangshan_repcut_nk32_full_control_reproduction_20260907.md) | 完整冻结 assignment 导入/重建成功；70 package 源文件、33 flat-SV逐字节复现，38 独立审计通过，双实现重算 exact load/KM1 一致；不是新划分性能结果。 |
| `TNO0288` | `2026-09-07` | [XiangShan RepCut N=K=32 full build entry gate](./TNO0288_xiangshan_repcut_nk32_full_build_entry_gate_20260907.md) | 新 assignment 全 32 模型独立构建入口 13 tests 与真实 package dry-run 通过；toolchain 字典/源身份/原wrapper flags 对齐。未执行新模型 make，四项实测仍被资源阻断。 |
| `TNO0289` | `2026-09-08` | [SimpleTES gen38 budget-256/valid-128 completion](./TNO0289_simpletes_gen38_budget256_valid128_completion_20260908.md) | node030 正常达到 `98/98 valid` 后收尾（`136/217` generation attempts，22 generation failures，0 evaluation failures）；最佳节点 pooled wall `43,950.25→41,524.00 ms`，减少 `2,426.25 ms/5.520446%`，ABBA/BAAB gap `0.234880 pp`，全部稳定性/功能/NUMA/PMU 门禁通过，尚未 landing/default。 |
| `TNO0290` | `2026-09-09` | [SimpleTES gen38 best-path factorial ablation](./TNO0290_simpletes_gen38_bestpath_factorial_ablation_20260909.md) | A/B/C 三机制 factorial 的八个 arm 均有同源 build 和 fixed-ASLR 同 CCD ABBA+BAAB；B `42,531.25→40,531.50 ms`（`+4.701837%`，gap `0.126339 pp`），BC exact `42,493.00→40,461.25 ms`（`+4.781376%`，gap `0.016084 pp`），ABC `42,102.50→40,200.00 ms`（`+4.518734%`），C 仍轻微回退。首份 BC 身份不一致已废弃。 |
| `TNO0291` | `2026-09-09` | [SimpleTES C independent retest](./TNO0291_simpletes_c_independent_retest_20260909.md) | 同一 B0/C binary 在 node031 独立复测：`42,592.75→42,816.75 ms`，慢 `224.00 ms/0.525911%`；ABBA/BAAB 都回退，gap `0.034567 pp`，离线复核当前全部 8 项稳定性门禁通过；旧 C_repeat4 的 spread 超限另作说明，不改生产默认。 |
| `TNO0292` | `2026-09-09` | [SimpleTES B to AB direct comparison](./TNO0292_simpletes_b_to_ab_direct_comparison_20260909.md) | 直接 B→AB 三组完整值为 `40,401.50→40,250.00 / 40,438.75→40,488.00 / 40,881.00→40,889.00 ms`，gap `0.525755/0.261007/0.445236 pp` 均不达标；继续三轮因外部污染无完整组。最终四节点 30 秒调查均 0/24 空闲 CCD，正式复测被负载阻断；全部原始记录保留，无默认或研究状态变更。 |
| `TNO0293` | `2026-09-09` | [XiangShan RepCut N=K=32 resource retry](./TNO0293_xiangshan_repcut_nk32_resource_retry_20260909.md) | 重新轮询允许节点；node041/node032 等候选在实际 admission 前失效，资源尝试保留为启动前阻断。node031 随后进入独立 runtime 记录，不能将本篇零 launch 外推到全部重试。 |
| `TNO0294` | `2026-09-09` | [XiangShan RepCut N=K=32 stage-1 scheduler AB/BA](./TNO0294_xiangshan_repcut_nk32_stage1_scheduler_ab_ba_20260909.md) | node031 完成 AB/BA 四条 C=10000 launch；legacy→pipeline-workers pooled Host `10.6135→11.7415 s`，pipeline 慢 `10.628%`。legacy 长样本运行期 busy/page/worker 门失败，证据保留且不正式选用。 |
| `TNO0295` | `2026-09-09` | [SimpleTES B to AB valid retest](./TNO0295_simpletes_b_to_ab_valid_retest_20260909.md) | node032 同 CCD fixed-ASLR 八样本与完整稳定性审计通过：B `40,633.00→AB 40,826.75 ms`，AB 慢 `193.75 ms/0.476829%`；两个顺序均回退，gap `0.099027 pp`。建议只保留 B、不默认叠加 A；尚未落地或改变研究基线。 |
| `TNO0296` | `2026-09-09` | [SimpleTES B native landing](./TNO0296_simpletes_b_native_landing_20260909.md) | Wolvrix `94109bc` 将 selected hot-input compute dispatch branch weighting 放入通用 C++/Python 默认路径；仅 B、不叠加 A/C，8 项 CTest 通过；fresh 构建/功能与正式 walltime 验证见 TNO0298..0299。 |
| `TNO0297` | `2026-09-09` | [SimpleTES B native baseline handoff](./TNO0297_simpletes_b_native_baseline_handoff_20260909.md) | SimpleTES 最终 `4ca31aa` 固定实际 parent `fd54f8d` / Wolvrix `94109bc`，新空 control 原生包含 B；161 项 bench/runtime 测试、GPT sol max/thj 离线启动和实际 pin/source/patch 核验通过，已追加逐 word 门槛措辞校正，未启动研究。 |
| `TNO0298` | `2026-09-09` | [SimpleTES B native fresh build regression](./TNO0298_simpletes_b_native_fresh_build_regression_20260909.md) | node032 当前 pre-B/base+B 独立 fresh RTL 构建成功；CPP 仅 2,074 处分支提示及 3 行宏定义差异，普通 O3 无 PGO/BOLT；双方各 32 项 pybind、100/10k 功能通过，ELF `83,521,600→83,624,000 bytes`，身份/配置一致。 |
| `TNO0299` | `2026-09-09` | [SimpleTES B native walltime regression](./TNO0299_simpletes_b_native_walltime_regression_20260909.md) | 正式 node032 CPU184 同 CCD fixed-ASLR 50k：base `43,048.50→B 41,051.25 ms`，减少 `1,997.25 ms/4.639534%`；order gap `0.166151 pp`，完整 8 项稳定性门禁通过。前三组 gap 不合格均保留并拒绝，不混合平均；B 保留原生默认。 |
| `TNO0300` | `2026-09-09` | [SimpleTES native-B Astra fresh research launch](./TNO0300_simpletes_native_b_astra_fresh_launch_20260909.md) | node030 以 native-B 默认基线新建 instance `ed572ae5`；隔离安装当前稳定 Codex `0.153.4`，THJ 派生私有配置的 `gpt-6-astra/max` 真实工具调用预检通过，`64 attempts/32 valid`、`4 gen/1 eval` 已启动，首次 control 构建中，尚无新性能结论。 |
| `TNO0301` | `2026-09-10` | [SimpleTES function-gate locale fix](./TNO0301_simpletes_function_gate_locale_fix_20260910.md) | SimpleTES `9d19a65` 为 evaluator 子进程及 source 后统一固定 `LC_ALL=C`，修复千位逗号导致的 10k 假失败；focused `165/165`、full `330/330`、node030 同 ELF 旧环境复现及修复后 100/10k gate 通过。引擎未重启，修复将在下一次自然 evaluator retry 加载，尚无新 50k 结果。 |
| `TNO0302` | `2026-09-14` | [SimpleTES Astra budget-128/valid-64 resume](./TNO0302_simpletes_astra_budget128_valid64_resume_20260914.md) | 原 Astra 树正常完成 `42 attempts/32 valid`，best g34 为 `40,469→39,490 ms`（减少 `2.419136%`）；node030 从最终 checkpoint 单调扩容至累计 `128/64`，原 instance `ed572ae5`、Astra/max、`4 gen/1 eval` 已续跑。首次模型 attestation 预检拒绝未启动引擎，第二次严格预检通过，历史分数/基线不变。 |
| `TNO0303` | `2026-09-14` | [XiangShan RepCut N=K=32 stage-1 fresh retest plan](./TNO0303_xiangshan_repcut_nk32_stage1_fresh_retest_plan_20260914.md) | 冻结 A=legacy/B=pipeline-workers、同 ELF 与 N=K=32，计划重新扫描允许节点并完成完整 C100/C10000 AB/BA；核对原协议选择条件，不放宽门槛、不单臂重抽、不从无效证据选择新 control。 |
| `TNO0304` | `2026-09-14` | [XiangShan RepCut N=K=32 stage-1 fresh resource result](./TNO0304_xiangshan_repcut_nk32_stage1_fresh_resource_result_20260914.md) | 59 份扫描、node033 三组入口共 14 attempts：13 次 admission 拒绝，仅 legacy C100 一次通过，C10000/BA 零 launch。47 项本地测试通过；保留 legacy，尚无新性能数据，需持续资源窗口。 |
| `TNO0305` | `2026-09-14` | [XiangShan RepCut giant ASC semantics and growth](./TNO0305_xiangshan_repcut_giant_asc_semantics_and_growth_20260914.md) | 只读定位 ASC4→part8：429 个 memory 写目标横跨缓存/访存、总线和观测逻辑；确认 AXI pending_count 至少连接 65 个 memory，以及四个 L3 回填缓冲展开 2,056 个逐 bit 写端点。区分 RTL 真实依赖、memory 传递共置与表示膨胀，未拆 ASC 或新增性能结论。 |
| `TNO0306` | `2026-09-14` | [XiangShan RepCut N=K=32 node031 reserved96 run plan](./TNO0306_xiangshan_repcut_nk32_node031_reserved96_run_plan_20260914.md) | 用户指定 node031 CPU96-127；核验四 CCD 与 SMT288-319 初扫全空闲，monitor35，固定同 ELF legacy/pipeline-workers 的 C100/C10000 AB/BA，不改变原判定门槛。 |
| `TNO0307` | `2026-09-14` | [XiangShan RepCut N=K=32 node031 reserved96 AB/BA result](./TNO0307_xiangshan_repcut_nk32_node031_reserved96_ab_ba_result_20260914.md) | 8 次首次 admission/launch，四长样本功能/身份/page/worker 全通过、guard100%；唯一 BA/A CPU residual 门保留。完整 balanced diagnostic：Host 10.2660→11.5355 s，pipeline-workers 慢12.366%，不采用、保留 legacy；非全 strict 或生产结论。 |
| `TNO0308` | `2026-09-14` | [XiangShan RepCut N=K=32 sync diagnosis plan](./TNO0308_xiangshan_repcut_nk32_sync_diagnosis_plan_20260914.md) | 固定每16 step对称采样 callback/host事件，拆分 eval→update 放行、本体和完成尾部；独立诊断 AB/BA，依据结果只做一个最小同步候选，无 probe 复测，不改分区/映射/默认。 |
| `TNO0309` | `2026-09-14` | [XiangShan RepCut sync probe build gate](./TNO0309_xiangshan_repcut_sync_probe_build_gate_20260914.md) | 独立common-only probe构建通过，原ABI/模型/优化级别不变；64B lane私有事件缓冲、每16步采样、退出后输出。生成器5项及分析器5项测试通过，node031诊断AB/BA启动，不用于Host选型。 |
| `TNO0310` | `2026-09-14` | [XiangShan RepCut sync probe result](./TNO0310_xiangshan_repcut_sync_probe_result_20260914.md) | probe四长样本各1257条记录。全lane平均放行 −9.646 us，critical放行 +14.707 us、完成尾部 +12.151 us；已追加两侧legacy CPU residual拒绝与critical身份改变的解释边界勘误，不能归因某把mutex的份额。 |
| `TNO0311` | `2026-09-14` | [XiangShan RepCut ASC split ablation plan](./TNO0311_xiangshan_repcut_asc_split_ablation_plan_20260914.md) | 隔离 O/A/B/AB：选择条件精化、非冲突细写聚合及叠加；先局部正确性再重算 ASC/memory 分量，区分操作数量压缩与真实拆分，不改默认、不移除共置检查。 |
| `TNO0312` | `2026-09-14` | [XiangShan RepCut completion-v1 invalidation](./TNO0312_xiangshan_repcut_completion_v1_invalidation_20260914.md) | 首版原子完成计数存在漏唤醒风险，已运行AB/BA保留但正确性否决；纠正旧mock误用与跨pair约0.19%因果收益表述，TNO0310追加CPU/critical条件统计勘误。 |
| `TNO0313` | `2026-09-14` | [XiangShan RepCut completion-v2 build gate](./TNO0313_xiangshan_repcut_completion_v2_build_gate_20260914.md) | 最后完成者持Host等待mutex通知，completion锁32→1；实际v2 C++17 mock、3项生成器、47项measurement测试及common-only身份构建通过。已追加独立漏唤醒回归和完成状态，AB/BA结果见TNO0314。 |
| `TNO0314` | `2026-09-14` | [XiangShan RepCut completion-v2 AB/BA result](./TNO0314_xiangshan_repcut_completion_v2_ab_ba_result_20260914.md) | 修正版node031完整AB/BA，Host 10.5475→11.5135 s，慢9.159%；四长样本功能/page/worker通过，两侧legacy CPU residual拒绝保留，balanced diagnostic，保留legacy。 |
| `TNO0315` | `2026-09-14` | [XiangShan RepCut ASC split ablation result](./TNO0315_xiangshan_repcut_asc_split_ablation_result_20260914.md) | O/A/B/AB 全图结构 gate：B 聚合 2,040 个写端点并降低 closure weight，但四臂 ASC 均 301,172，原 giant 的 429 个 memory 仍为单一组件；A/AB 未实现拆分，实验代码保持隔离。已追加主机与429/844计数口径勘误。 |
| `TNO0316` | `2026-09-14` | [XiangShan RepCut debug grouping and memory bridges](./TNO0316_xiangshan_repcut_debug_grouping_memory_bridges_20260914.md) | 只读核验不是全部debug共置：30,936个logEndpoint寄存器写分属28,538个ASC。批量printf观察next_counter，五条实际打印分别回溯21/10/4/21/31个memory，去重85；确认共置约束，未量化拆除收益。 |
| `TNO0317` | `2026-09-15` | [XiangShan perf print current-counter experiment](./TNO0317_xiangshan_perf_print_current_counter_experiment_20260915.md) | 用户授权单行实验：XSPerfAccumulate打印next_counter→counter，更新/触发/分组不变；打印不含本拍事件，精确源码差异检查通过，尚未重新生成RTL/GRH/ASC或复测。 |
| `TNO0318` | `2026-09-15` | [XiangShan counter-print regeneration plan](./TNO0318_xiangshan_counter_print_regeneration_plan_20260915.md) | 单行counter打印实验的独立RTL/GRH再生成与ASC结构gate；固定原TLConfig/1core/difftest G，先核对产物差异再比较429个memory归属，不叠加其他改写。 |
| `TNO0319` | `2026-09-15` | [XiangShan counter-print isolated-build runbook correction](./TNO0319_xiangshan_counter_print_isolated_build_runbook_correction_20260915.md) | 记录 Git 缓存路径失败、FileRegisters cwd 隔离导致的主动中止、可选 classpath 目录误判；Scala 编译通过，改为独立 cwd 启动 JVM，尚无结构结论。 |
| `TNO0320` | `2026-09-15` | [XiangShan counter-print RTL build result](./TNO0320_xiangshan_counter_print_rtl_build_result_20260915.md) | node039 独立 JVM 生成成功，2,097个RTL、7个helper，保留原产物；2,091个RTL字节一致，6个差异转入独立审计。 |
| `TNO0321` | `2026-09-15` | [XiangShan counter-print RTL semantic audit](./TNO0321_xiangshan_counter_print_rtl_semantic_audit_20260915.md) | 全量核验9,311个打印参数改current及更新表达式不变；788个条件组重排单独记录。其余差异为枚举重排、Git元数据与注释，不新增memory依赖，不声称日志全序/Host等价。 |
| `TNO0322` | `2026-09-15` | [XiangShan counter-print fresh-ingest control gate](./TNO0322_xiangshan_counter_print_fresh_ingest_control_gate_20260915.md) | 原RTL重新导入后ASC全部指标复现；完整ASC表、端点表和844个memory归属表字节相同，冻结基线gate通过。 |
| `TNO0323` | `2026-09-15` | [XiangShan counter-print ASC split result](./TNO0323_xiangshan_counter_print_asc_split_result_20260915.md) | 结构正向：原giant429个memory分成392/18/8/10/1五个ASC，最大comb降26.58%、full closure降20.83%；全图工作量仅略降，未测Host。 |
| `TNO0324` | `2026-09-15` | [XiangShan counter-print residual perf dependency audit](./TNO0324_xiangshan_counter_print_residual_perf_dependency_audit_20260915.md) | 全图核验35条PERF打印memory依赖全为0，各自独立单sink ASC；822条日志中仅1条ERROR条件仍读1块memory，残余giant不能再归因于集中perf打印。 |
| `TNO0325` | `2026-09-15` | [XiangShan counter-print Host AB/BA plan](./TNO0325_xiangshan_counter_print_host_ab_ba_plan_20260915.md) | 固定N=K=32、legacy/push、两臂同参数重新分区及全模型重建，C100→C10000 AB/BA；沿用原资源/page/worker/PMU gate，不以静态收益替代Host。 |
| `TNO0326` | `2026-09-15` | [XiangShan counter-print build provenance supplement](./TNO0326_xiangshan_counter_print_build_provenance_supplement_20260915.md) | 补齐旧builder漏记的实际difftest/native/generated C++与Verilator include身份，编译前冻结117+64份文件，要求编译后复核；记录测量候选不等于预约。 |
| `TNO0327` | `2026-09-15` | [XiangShan counter-print build resource diagnosis](./TNO0327_xiangshan_counter_print_build_resource_diagnosis_20260915.md) | A构建受资源影响、回读采样确认大页分配触发直接内存整理；仅调整本次构建affinity，未改系统设置，不作为Host证据。 |
| `TNO0328` | `2026-09-15` | [XiangShan counter-print partition build gate](./TNO0328_xiangshan_counter_print_partition_build_gate_20260915.md) | 两臂全量32模型编译和源码gate通过；最终最大partition ops降26.50%，每update复制449729→441866字节（−1.75%），不等同Host收益。 |
| `TNO0329` | `2026-09-15` | [XiangShan counter-print Host admission blocked](./TNO0329_xiangshan_counter_print_host_admission_blocked_20260915.md) | 全部允许节点扫描后两次node030 mask各4次admission全失败，0次仿真launch；无新Host数据，保留构建与原始失败记录，等待安静四CCD。 |
| `TNO0330` | `2026-09-15` | [XiangShan counter-print node030 reserved96 plan](./TNO0330_xiangshan_counter_print_node030_reserved96_plan_20260915.md) | counter-print 探索性 Host −2.21%；第8节固定Host＋同核最后通知相对冻结B Host −10.17%；8.4方案一前后时空图；8.5–8.11定位 Host 参与回退、CPU105 降频及自旋因果，并补充未固定 Host vs all-spin 单步时空图。以最终 walltime 为目标后，当前 N=K=32 专用 runtime 已将 all-spin 改为默认；相对 Host-only 50 µs 的 Host −26.49%，代价为 task-clock +73.59%。8.12–8.13 完成通用实现及 XiangShan K=32 端到端验证；8.14 六对生产/旧 v6 交错 C=10000 全部通过，生产 Host 配对中位数 `−2.65%`、`6/6` 胜出。 |
| `TNO0331` | `2026-09-20` | [XiangShan residual giant separator audit](./TNO0331_xiangshan_residual_giant_separator_audit_20260920.md) | 残余392-memory ASC 与选择性 mem-to-reg；§7.10 三方案 wrapper -O3：single Host −32.17%、pair −33.69%。追加2026-09-21 §7.11：single+pair 组合、四方案各八次，功能全过；组合最大ASC仍642,580，相对pair复制字节 −0.94%、Host −5.03%、wall −4.84%，7/8轮胜出，eval瓶颈转至part_3。本批波动较大，保留全部成功样本；未改变默认分区管线。§7.12追加同批四方案32线程时空重建图、CSV及离线交互HTML，明确非事件trace。§7.13追加128分区权重/eval/update可选条形图，含三种权重口径与归一化/双轴视图。 |
| `TNO0332` | `2026-09-22` | [RepCut backend cost models](./TNO0332_repcut_backend_cost_models_20260922.md) | 汇总预估边界、过拟合风险、后端可扩展架构；§5记录可选verilator-v1与测试；§6追加固定四组相关性及combined重新分区，C10000/C30000各8对AB/BA全部获胜，walltime约降2.50%/2.39%，尾部预测仍不足；§7定位part_6宽移位热点，生成器改写后C30000再测8对全部获胜，Host/wall约降10.66%/10.59%，legacy分区与权重不变。§9–10追加part_3热点定位及常量左移memory-write改写：消除2360次宽左移，C30000八对AB/BA全胜，walltime再降5.41%、part_3 eval降6.69%；§11追加连续 memory staging 合并，C30000八对全胜，walltime再降0.66%、eval降0.83%；编译/功能审计通过，分区及通信不变。§12追加当前v3的PMU/机器码/RTL对照，定位refillBuffer逐bit提交和BusPMU逐entry条件更新；区分静态归约数量与动态成本，并补充§11边界勘误。§12.4–12.5追加通用 memory-write-coalesce 结构变换：part_3 移除2040个写端口，C30000八对全胜，Host/wall分别下降7.34%/7.27%，最大分区 eval 下降11.28%；功能、编译和通信审计通过，默认 pipeline 仍未开启。§13.6 新增 `shift_low_bit_v1→const_shift_part3_v2→memory_slice_part3_v3→memory_coalesce_v5` 四阶段 PNG/SVG/交互 HTML 及时间明细，三次优化后 walltime 相对 baseline 下降15.74%、eval下降19.87%。 |
| `TNO0333` | `2026-09-25` | [RepCut 多线程 GrhSIM 后端](./TNO0333_repcut_grhsim_backend_20260925.md) | 增加同质 GrhSIM 后端，复用阶段调度/all-spin；小模型真实编译运行、Python/flow 验证、Verilator 生成不变性和 32 分区香山 Difftest 链路通过。两批各 8 对 C=30000 AB/BA：GCC-GrhSIM 相对原 Clang-Verilator walltime 中位数减少 8.95%，统一 GCC 对照减少 24.00%。已追加 Clang21/SSE2 错误代码生成根因、独立回归与兼容修复，以及标准流文件描述符边界修正；Clang23.1.2 正常 O3 的最小复现与全量香山验证通过，4 对 AB/BA 相对 Clang21 兼容版 walltime 中位数减少 0.91%。§7 新增 Clang23 三组 Os/O3/GrhSIM 完整编译计时、两个窗口各 12 轮均衡交错与 HTML 时空图；C30000 GrhSIM 相对 Verilator Os/O3 walltime 减少 18.24%/13.82%。 |
| `TNO0334` | `2026-10-12` | [XiangShan 原生 Verilator 线程扩展](./TNO0334_xiangshan_native_verilator_thread_scaling_20261012.md) | 原生未分区 RTL，标准 XiangShan Makefile、Clang23、无波形/PGO，六档线程模型分布于 node030–node032 编译；性能固定在 node030 CPU96 起连续核，C100000 正反交错窗口。已追加六轮八版本 48 次测量及 HTML：Native 1/2/4/8/16/32 中位数 `213.105/143.075/77.830/45.815/53.360/44.965 s`，RepCut V/G32 为 `22.615/10.995 s`，保留原生高线程档明显波动及端点比较限制。 |
| `TNO0335` | `2026-10-12` | [XiangShan GrhSIM 旧单线程流程复测](./TNO0335_xiangshan_grhsim_single_thread_old_flow_20261012.md) | 旧单模型流程在 node032 CPU0--7 完成 C=100000 ABBA/BAAB。通用 codegen 候选最终静态库与 baseline 逐字节相同，四对 Host `116603.0→117570.5 ms`（`+0.8297%`）；memory-write-coalesce 使静态库约 `-0.587%`，但 Host `119520.25→119859.25 ms`（`+0.2836%`）。两项均不进入旧单线程默认。 |
| `TNO0336` | `2026-10-13` | [GrhSIM 现有 ASC 的成本建模与均衡](./TNO0336_grhsim_existing_asc_balance_20261013.md) | 独立 opt-in `grhsim-v1`，不拆 ASC、不改 Verilator；追加阶段成本及 32 次整 ASC 迁移试验。两轮各 8 对 fresh AB/BA：eval 全胜、约 `-2.1%/-2.4%`，但 update `+7.5%/+6.9%`，Host 仅 `-0.29%/-0.55%`。p9 下沿瓶颈减少，p5 update 尾部加重；实际写回字节反而略降，下一步诊断 update 执行效率，实验候选暂不默认。 |
| `TNO0337` | `2026-10-13` | [GrhSIM 执行成本与划分体系重设计](./TNO0337_grhsim_partition_system_redesign_20261013.md) | 记录文献依据与完整规划；集合/通信评价器、execution-plan、事件/守卫及条件切片完成三份划分对账。已追加第 15 节：带条件的准备/比较/store/activation 特征和首批 compute lowering；第 16 节按实际后端 lowering 补齐 scalar/wide/state/memory/DPIC 形态、operand/word/helper 机制单位、helper 家族展开上界及两沿聚合诊断，producer-dirty concat 与普通 wordwise 分开，96 分区 source audit、20 文件 byte identity、成员守恒通过，unmodeled compute groups 为 0。新增 16.6：实现 mask 保留、互斥 family 和显式 unbucketed 的 GrhSIM backend cost adapter，old/scalar/stage 三份 `backend_cost.csv` 逐 feature 守恒均通过；16.7 新增 mechanism-unit 投影、raw attribution 守恒和 whole/range 相关性诊断，机制单位均无 unmapped；16.8 完成六记录跨变体稳定性筛选，确认 materialization/change-check 需与 commit 发布和 phase 分开；第 18 节完成 phase-specific 三轴 Pareto 表示和 old/scalar/stage 重放守恒；第 19 节新增显式 candidate atom、Pareto dominance 和确定性 lexicographic proposal 原型，通用 fixture/CMake/ASan 通过；19.1 明确当前 partition-level mechanism report 不能回填 ASC phase 权重，新增显式 piece feature adapter，尚未扫描完整 XiangShan 或接入 walltime。约 97.75% 计算操作仍为 generic 待计价，未形成新时间模型或 walltime 收益；Verilator 和默认划分未动。 |
| `TNO0338` | `2026-10-27` | [从 Verilog 开始的自动 memory 与迁移流程](./TNO0338_grhsim_automatic_rtl_flow_20261027.md) | 固定全核生成、结构 memory 筛选、从头 32 分区及自动迁移策略和来源。 |
| `TNO0339` | `2026-10-27` | [Clang 23 变化归约错误与兼容处理](./TNO0339_grhsim_clang23_change_reduction_20261027.md) | 独立 fixture 复现丢失 activation，添加通用 no-SLP 保护并完整重建。 |
| `TNO0340` | `2026-10-27` | [自动初解的完整构建与正式验收](./TNO0340_grhsim_automatic_initial_runtime_20261027.md) | 16 次 C100000 与 THP/对齐通过；walltime 11.015→14.725 s，继续自动 profile 迁移。 |
| `TNO0341` | `2026-10-27` | [新初解 profile 的自动迁移选择](./TNO0341_grhsim_automatic_migration_selection_20261027.md) | 自动选择来源和目标，72 个提案中唯一预测改善且满足预算者为 p4→p7，1925 个 ASC。 |
| `TNO0342` | `2026-10-27` | [自动流程完成与迁移验收](./TNO0342_grhsim_automatic_flow_acceptance_20261027.md) | Verilog→emu 全程完成；自动迁移 −0.136%、5/8 胜未接受，保留自动初解，尚未追平恢复版。 |

| `TNO0343` | `2026-10-28` | [固定恢复版 memory 的受控实验](./TNO0343_grhsim_restored_memory_control_20261028.md) | 固定三个 memory 与转换参数，重新分配并自动迁移，统一编译兼容选项。 |
| `TNO0344` | `2026-10-28` | [固定 memory 初解的正式性能对照](./TNO0344_grhsim_fixed_memory_initial_runtime_20261028.md) | 相同编译设置下13.790→13.190s，配对−4.455%、7/8更快，继续自动迁移。 |
| `TNO0345` | `2026-10-28` | [恢复版 no-SLP 编译对照](./TNO0345_grhsim_restored_no_slp_control_20261028.md) | 同源码/同归档顺序重编，walltime配对+8.987%、0/8更快。 |
| `TNO0346` | `2026-10-28` | [固定 memory 自动流程最终验收](./TNO0346_grhsim_fixed_memory_acceptance_20261028.md) | 自动72提案无满足预算的预测改善；同编译恢复版11.190→新初解13.040s，配对+16.325%。 |
| `TNO0347` | `2026-10-28` | [固定 memory 初始方法对齐](./TNO0347_grhsim_fixed_memory_initial_method_alignment_20261028.md) | 核实 ASC 模型逐字节一致，复用历史六维超图、自动隔离超大节点并重新 31-way 求解；固定完整 preset 和 no-SLP 编译后做新的 AB/BA。 |
| `TNO0348` | `2026-10-28` | [对齐初解构建与门禁](./TNO0348_grhsim_aligned_initial_build_gate_20261028.md) | 新六维初解的精确复制/通信账本，7857对象完整编译及7249入口64B对齐通过；执行计划检查与生成并行。 |
| `TNO0349` | `2026-10-28` | [对齐初解walltime验收](./TNO0349_grhsim_aligned_initial_walltime_20261028.md) | 两组各8对fresh AB/BA：相对普通初解−3.595%/8胜，相对同no-SLP恢复版+12.465%/0胜；固定memory及完整preset，36次运行全部通过。 |
| `TNO0350` | `2026-10-28` | [新旧初解不一致的求解器归因](./TNO0350_grhsim_initial_solver_reproducibility_20261028.md) | 同输入/seed/preset的32及384线程各重复两次均不复现；社区和粗化图已分歧，新初解切边与通信质量劣于历史初解，固定线程不足以复现。 |
| `TNO0351` | `2026-10-28` | [八份并行初解与km1择优](./TNO0351_grhsim_parallel_eight_initial_selection_20261028.md) | seed0–7各48线程并行，8份独立容量/目标审计通过，自动选seed1/full km1=27,912,141；优于历史初解1.283%，尚未测walltime。 |
| `TNO0352` | `2026-10-28` | [八份择优初解的后续流程](./TNO0352_grhsim_portfolio_selected_followup_runbook_20261028.md) | 固定seed1标签及完整preset，重建/生成/编译，自动动态迁移，最终与同编译恢复版及历史原binary做独立fresh AB/BA。 |
| `TNO0353` | `2026-10-28` | [八份择优初解的完整生成与构建检查](./TNO0353_grhsim_portfolio_selected_build_gate_20261028.md) | seed1标签保持不变，32分区计划通过；7,719个对象完成Clang23/O3/native/no-SLP构建，7,116个compute入口全部64B对齐。 |
| `TNO0354` | `2026-10-28` | [八份择优初解的同编译运行对照](./TNO0354_grhsim_portfolio_initial_runtime_20261028.md) | 8对fresh AB/BA，walltime 9.785→10.350s，配对+5.518%，0/8胜；总eval下降但拖尾上升，继续自动迁移筛选。 |
| `TNO0355` | `2026-10-28` | [八份择优初解的自动迁移筛选](./TNO0355_grhsim_portfolio_automatic_migration_gate_20261028.md) | 新trace自动选p8/p9/p0，51提案全部完成精确核算，但均不满足原8条通信零增长预算；无迁移，不放宽门槛。 |
| `TNO0356` | `2026-10-28` | [八份择优后续流程及恢复版最终对照](./TNO0356_grhsim_portfolio_followup_final_comparison_20261028.md) | 流程完成；同编译恢复版9.785→10.350s（+5.518%），原始恢复版8.920→10.360s（+16.002%），均0/8胜，恢复版仍为锚点。 |
| `TNO0357` | `2026-10-28` | [seed 1 原始编译选项对照计划](./TNO0357_grhsim_seed1_original_flags_runbook_20261028.md) | 同一生成源码全量去掉no-SLP，保留归档顺序和对齐，先功能检查，再对原始恢复版和同seed no-SLP做fresh AB/BA。 |
| `TNO0358` | `2026-10-28` | [seed 1 原始编译选项构建检查](./TNO0358_grhsim_seed1_original_flags_build_20261028.md) | 原始O3/native、无no-SLP，7719对象全量重编及链接141.92s；7116个compute入口全64B对齐，归档顺序相同。 |
| `TNO0359` | `2026-10-28` | [seed 1 原始选项与恢复版直接对照](./TNO0359_grhsim_seed1_original_flags_restored_runtime_20261028.md) | 同为原始编译选项，8对fresh AB/BA：walltime 8.925→9.480s，配对+6.352%、0/8胜；功能/THP/对齐均通过。 |
| `TNO0360` | `2026-10-28` | [同一 seed 1 的 SLP 编译选项对照](./TNO0360_grhsim_seed1_slp_control_runtime_20261028.md) | 同源8对fresh AB/BA，去掉no-SLP后walltime 10.390→9.430s、配对−9.007%、8/8胜；仍慢于恢复版，32次长测和4次smoke全部核验通过。 |
| `TNO0361` | `2026-10-28` | [可从新 clone 干净重跑的默认流程计划](./TNO0361_grhsim_clean_default_flow_plan_20261028.md) | 从Verilog重新生成六维图和8份初解，自动迁移，去掉中间历史身份/plan gate，构建工具与默认配置进入仓库。 |
| `TNO0362` | `2026-10-28` | [干净默认生成入口的实现与小型回归](./TNO0362_grhsim_clean_default_implementation_20261028.md) | 一键源码构建、完整preset、自动择优/迁移与本机32核运行；零权重维度fallback修正，实际Verilog八份求解和40项测试通过，全量香山试跑进行中。 |
| `TNO0363` | `2026-10-28` | [默认运行入口的代码页初始化](./TNO0363_grhsim_portable_startup_20261028.md) | preload移至emu入口，exec与dlmopen的一次性标记分离；实际ELF大页启动及编排回归通过，相关测试增至42项。 |
| `TNO0364` | `2026-10-28` | [独立目录的纯源码构建](./TNO0364_grhsim_source_only_bootstrap_20261028.md) | 排除旧构建与设计产物后独立构建全部原生工具成功；香山8份求解全可行，自动选seed6/km1=39,450,970，完整发射进行中。 |
| `TNO0365` | `2026-10-28` | [干净初解的完整构建与最终运行](./TNO0365_grhsim_clean_initial_runtime_20261028.md) | Verilog至32分区emu完成，8259对象原始O3/native；8次C100000功能通过，walltime中位13.394977s，自动迁移评估继续。 |
| `TNO0366` | `2026-10-28` | [干净默认流程的端到端完成与公开入口复测](./TNO0366_grhsim_clean_default_completion_20261028.md) | 51提案自动选p6→p31，fresh8对+2.277%/0胜后自动保留seed6初解；公开入口8次复测13.102951s，launcher通过，44项测试通过。 |
| `TNO0367` | `2026-10-28` | [默认路线初解km1增大与旧RTL复用问题](./TNO0367_grhsim_initial_km1_input_drift_20261028.md) | 同一计分器复现旧27,912,141；默认入口复用旧RTL漏掉counter-print改动，超图已变；修正默认重新生成，46项测试通过，尚未全量重测。 |
| `TNO0368` | `2026-10-28` | [重新生成RTL后的完整32线程流程结果](./TNO0368_grhsim_fresh_rtl_full_flow_result_20261028.md) | 新RTL全流程通过，8份初解自动选seed7/km1=26,547,623；walltime两窗口12.228/12.533s，51迁移提案均不满足通信预算，保留初解，默认入口指向新产物。 |
| `TNO0369` | `2026-10-28` | [新RTL seed7与恢复版的直接AB/BA](./TNO0369_grhsim_fresh_seed7_vs_restored_20261028.md) | 同为Clang23.1.2原始O3/native、SLP，fresh两轮16对walltime退化9.538%/0胜；eval+10.391%，36次功能、THP和对齐检查通过，恢复版继续为性能锚点。 |
| `TNO0370` | `2026-10-28` | [RTL 关键路径首版实现与香山诊断](./TNO0370_grhsim_rtl_critical_path_first_report_20261028.md) | 独立一键报告；7,412 batches、98.16% 操作来源覆盖；8 次完整 THP 诊断；37 项测试与两组 100,000-cycle Verilator 差分通过。 |
| `TNO0371` | `2026-10-28` | [关键路径中文 RTL 视图](./TNO0371_grhsim_rtl_critical_path_chinese_view_20261028.md) | 报告首页改为中文 RTL-first 路径清单，直接列出 module、信号/表达式、源码行、batch 和运行时证据；新增 Markdown/CSV/JSON 路径输出。 |
| `TNO0372` | `2026-10-28` | [RTL 关键路径到 Chisel 模块映射](./TNO0372_grhsim_rtl_to_chisel_path_mapping_20261028.md) | 按模块名和信号证据映射 Chisel package/class；唯一、最佳、歧义和未解析结果均显式记录。 |
| `TNO0373` | `2026-10-29` | [32 分区动态关键路径第一名](./TNO0373_grhsim_dynamic_top1_all_partitions_20261029.md) | 66 次完整 THP 诊断；64 个分区/clock 全部采样，58 项重复第一名一致；独立展示稳定拖尾与分区全部采样，附 RTL/Chisel 来源和重复证据。 |
| `TNO0374` | `2026-10-29` | [p0/clock=1/commit batch 345 详细分析](./TNO0374_grhsim_p0_commit_batch345_detail_20261029.md) | 拆解 5,986 个提交操作、4.53 MB C++ 函数、102 个 RTL 文件、Chisel 候选和动态计时；确认它是大规模状态提交 supernode，而非单一 RTL 组合路径。 |
| `TNO0375` | `2026-10-29` | [Chisel／Verilog 仿真表达广泛调查：范围与进度](./TNO0375_chisel_simulation_pattern_survey_progress_20261029.md) | 持续记录库与设计扫描、新模式、基准约束及未决问题；实验结果另篇归档。 |
| `TNO0376` | `2026-10-29` | [首轮微基准、校准与反例](./TNO0376_chisel_pattern_first_microbench_20261029.md) | 30 个真实发射实例；区分 eval 与计算体，记录排序/CRC 退化、已优化算子及失败修正。 |
| `TNO0377` | `2026-10-29` | [参数扩展、生产末端规则与广泛调查结果](./TNO0377_chisel_pattern_expanded_evidence_20261029.md) | 51 项候选、47 个实例、五种分布；记录归一化规则、参数差异、反例及明确语义限制。 |
| `TNO0378` | `2026-10-29` | [真实 MSHRCtl 计数：打包成本改变结论](./TNO0378_chisel_pattern_frozen_mshr_count_20261029.md) | 原样抽取 group 928 的分散槽位计数，穷举 2^18 输入；区分 gather+popcount 与预打包下界。 |
| `TNO0379` | `2026-10-29` | [CRC 共同调用复核](./TNO0379_chisel_crc_call_context_control_20261029.md) | 保留调用上下文反证；同 binary 复核后撤回通用 LUT 收益判断。 |
| `TNO0380` | `2026-10-29` | [广泛调查交付与双实现设计](./TNO0380_chisel_pattern_delivery_and_ir_design_20261029.md) | 1,583 文件、51 项逐项处置、47 个实验；记录接口工作边界、验证和后续优先级。 |
| `TNO0381` | `2026-10-30` | [专用单线程基线口径](./TNO0381_chisel_native_single_thread_baseline_scope_20261030.md) | 明确使用 Wolvrix 专用完整模型流程；记录 A/A、配对测量、身份冻结和计时边界，未产生新性能数字。 |
| `TNO0382` | `2026-10-30` | [Chisel 新生成专用单线程基线](./TNO0382_chisel_native_single_thread_fresh_build_20261030.md) | node030 新生成 RTL/绑定/完整模型；CPU96 固定测量，持续记录构建与产物身份。 |
| `TNO0383` | `2026-10-30` | [CPU96 专用单线程 walltime 基线](./TNO0383_native_single_thread_cpu96_walltime_baseline_20261030.md) | 新 Chisel→RTL→完整 GrhSIM→emu；100k cycles × 8，均值 118.525 秒、CV 1.59%；已追加 no-SLP/远端代码页勘误，不能直接作为统一局部性分母。 |
| `TNO0384` | `2026-10-30` | [专用单线程历史对照](./TNO0384_native_single_thread_historical_comparison_20261030.md) | CPU96 4 对复测 96.055→114.298 秒、慢 19.0%；确认 no-SLP 和远端代码页两个混杂因素。 |
| `TNO0385` | `2026-10-30` | [同一 emu 代码页局部性控制](./TNO0385_native_single_thread_code_page_locality_control_20261030.md) | 相同 SHA 的原文件/本地代码页副本，2 对 114.869→109.738 秒、减少 4.47%；不作为新正式基线。 |
| `TNO0386` | `2026-10-30` | [从 Makefile 生成器移除默认 no-SLP](./TNO0386_grhsim_generated_makefile_default_slp_20261030.md) | 生成器源头删除 no-SLP，脚本原样；131 对象重编译、C100k 与 22 项测试通过，保留 Clang23 已知失败复现。 |
| `TNO0387` | `2026-10-30` | [默认 SLP 单线程本地 NUMA 重测](./TNO0387_native_single_thread_slp_local_numa_measurement_20261030.md) | CPU96；emu/NEMU/库预先本地化，运行中严格检查匿名及文件页；已完成，结果见 TNO0388。 |
| `TNO0388` | `2026-10-30` | [默认 SLP、本地 NUMA 单线程基线结果](./TNO0388_native_single_thread_slp_local_baseline_results_20261030.md) | CPU96 100k × 8，均值 98.579 秒、CV 1.04%；161 次 NUMA 快照和 1575 次线程快照全部通过。 |
| `TNO0389` | `2026-10-30` | [IntrinsicExpr PriorityEncoder64 Verilog 实验](./TNO0389_intrinsic_expr_priority_encoder_verilog_20261030.md) | Scala 开关：常规链 / 组合 DPI 均成功生成；自定义 intrinsic 名称被拒绝；停在 Verilog。 |
| `TNO0390` | `2026-10-30` | [明确原语的仿真实现归属讨论](./TNO0390_intrinsic_simulation_implementation_ownership_20261030.md) | 建议标准原语由库表达语义、后端提供实现，专用功能保留用户扩展；仅记录讨论，未推进后端。 |
| `TNO0391` | `2026-11-02` | [优先编码原语接入进度](./TNO0391_priority_intrinsic_integration_progress_20261102.md) | 同名 utility、全位宽纯组合 IR 与单线程 A/B 实施中。 |
| `TNO0392` | `2026-11-02` | [条件调用与原语契约回归](./TNO0392_priority_intrinsic_when_and_validation_20261102.md) | Uncache when 作用域隔离、严格纯组合契约、完整动态库冻结及验证记录。 |
| `TNO0393` | `2026-11-02` | [完整香山 A/B 功能与单线程门禁](./TNO0393_priority_intrinsic_full_xs_ab_gate_20261102.md) | 466 调用、两组逐字段轨迹、8 对 CPU96 AB/BA；当前整机 +0.439982%。 |
| `TNO0394` | `2026-11-02` | [全位宽微基准结果](./TNO0394_priority_intrinsic_width_matrix_results_20261102.md) | 31 位宽×两布局、62248366 个功能向量；packed 大宽度受益，65 位 lanes 明显退化。 |
| `TNO0395` | `2026-11-02` | [优先编码原语输入布局门控](./TNO0395_priority_intrinsic_input_layout_policy_20261102.md) | `Vec[Bool]`/`Seq[Bool]` 保留原硬件；65 位 lanes 回退消失，完整香山 +0.383271% 且 CI 跨零。 |
| `TNO0396` | `2026-11-02` | [移除显式 Vec.asUInt](./TNO0396_priority_intrinsic_explicit_vec_asUInt_removal_20261102.md) | 三个调用改为分布式输入；v7 完成功能校验和 8 对 CPU96 AB/BA，B 平均 +0.482634%，CI 跨零。 |
| `TNO0397` | `2026-11-03` | [PopCount 紧凑布局替换与单线程实测](./TNO0397_popcount_intrinsic_packed_layout_walltime_20261103.md) | 1,095 个 packed 调用进入 `kCountOnes`，7,140 个分布式调用保留硬件；8 对 CPU96 walltime B 平均 +0.665717%，0/8 胜。 |
| `TNO0429` | `2026-11-04` | [译码表优化重新启用与顺序探索起点](./TNO0429_decode_table_reenable_and_order_exploration_start_20261104.md) | `decode-table` 默认同时启用 CSR 译码表接入和恒定 `kDecodeTable` 折叠；历史消融可显式关闭，相关 native/Python 测试通过。 |
| `TNO0430` | `2026-11-04` | [译码表恒定折叠后的 source-order 顺序扫描](./TNO0430_decode_source_order_scan_20261104.md) | E 快照四种顺序完成结构扫描；字典序 compute node `−1,673`，4 对 CPU96 初测 X 相对 E `−1.080%`、3/4 胜，但区间跨零。 |
| `TNO0431` | `2026-11-04` | [source-order walltime 的干扰过滤与阶段结论](./TNO0431_decode_source_order_noise_filtered_conclusion_20261104.md) | 字典序 8 对原始均值受 106/112 秒服务器峰值影响；按预设门限过滤后 6 对均值 `+0.021%`。RTL 源位置序 4 对均值 `+0.070%`，暂未见稳定收益。 |
| `TNO0432` | `2026-11-04` | [DiffTest 模型采集路径与运行时检查的分层消融](./TNO0432_difftest_generation_and_runtime_ablation_20261104.md) | 相同 106 接口 RTL 下，模型采集路径关闭使 B 相对 A 平均慢 `+19.070082%`；同一模型上仅运行时 `--diff` 相对 A′ 平均慢 `+0.247691%`，区间跨零。 |
| `TNO0433` | `2026-11-04` | [DiffTest 四种配置的复核与性能归因](./TNO0433_difftest_four_state_review_20261104.md) | 统一 RTL、模型采集和运行时检查三层开关；S0→S1 为 `+11.62%`、S1→S2 为 `+19.07%`，S2→S3 仅 `+0.2477%` 且区间跨零，优化重点应放在主模型结构隔离。 |
| `TNO0398` | `2026-11-03` | [仅替换四位及以上 PopCount](./TNO0398_popcount_ge4_intrinsic_walltime_20261103.md) | 405 个 packed 调用进入 intrinsic，1–3 位的 690 个调用保留硬件；8 对 CPU96 walltime B 平均 +1.136902%，3/8 胜，CI 跨零。 |
| `TNO0399` | `2026-11-03` | [PopCount 同 binary A/A 控制](./TNO0399_popcount_walltime_aa_control_20261103.md) | 同一 binary 的 8 对控制均值差 -1.342466%，单对波动超过 7%；当前约 1% 的 PopCount 差异不足以作稳定收益结论。 |
| `TNO0400` | `2026-11-03` | [Gray-to-binary intrinsic 接入与 GrhSIM lowering](./TNO0400_gray_decode_intrinsic_20261103.md) | 新增 packed `utility.GrayToBinary`、`gray-decode` 模式和 `kGrayDecode`；32/65 位 Verilog、GRH、C++ lowering 与 16 位穷举/10 万向量检查通过，尚未发现可直接替换的真实 XiangShan 调用。 |
| `TNO0401` | `2026-11-03` | [生成阶段关闭 DiffTest 的单线程实测](./TNO0401_difftest_generation_off_walltime_20261103.md) | 两端运行时采集与检查均完全关闭；生成阶段关闭 DiffTest 后，CPU96 的 8 对平均配对耗时下降 10.410040%，8/8 更快，95% CI [-10.777662%, -10.063447%]；访存/UART 与运行环境检查通过。 |
| `TNO0402` | `2026-11-03` | [译码表 intrinsic 契约与实施](./TNO0402_decode_table_intrinsic_contract_20261103.md) | 真实香山译码表、NEMU 分层匹配调研、DontCare 约束验证；实施中。 |
| `TNO0403` | `2026-11-03` | [译码表完整覆盖与功能验证](./TNO0403_decode_table_full_coverage_20261103.md) | 106 次调用、70 次替换、24 张真实表；整机生成中，未作性能结论。 |
| `TNO0404` | `2026-11-03` | [译码表原生构建与整机等价](./TNO0404_decode_table_native_build_and_equivalence_20261103.md) | 两组 100,000 周期逐条 DiffTest 一致；CPU96 NUMA 核验通过，正式配对进行中。 |
| `TNO0405` | `2026-11-03` | [译码表配对脚本修复与续测](./TNO0405_decode_table_pair_runner_resume_20261103.md) | 保留中断样本；复用已验证轨迹和相同输入，v2 重新采集完整 8 对。 |
| `TNO0406` | `2026-11-03` | [译码表单线程整机 walltime](./TNO0406_decode_table_whole_walltime_20261103.md) | A 99.255 s → B 97.229 s；8 对均快，配对均值 −2.041%，全部 NUMA/DiffTest 通过。 |
| `TNO0407` | `2026-11-03` | [译码表局部实证与最终交付](./TNO0407_decode_table_local_results_and_delivery_20261103.md) | 24 表、1,968 对局部样本；保留两类退化，中文逐表报告及 JSON/CSV 完整落盘。 |
| `TNO0408` | `2026-11-03` | [退化译码表机制与 CSR 字节读取对照](./TNO0408_decode_table_regression_mechanisms_20261103.md) | 恒零表残留活动依赖；CSR LUT 已化位测试，字节读取对照 80 对确认宽读取代价。 |
| `TNO0409` | `2026-11-03` | [译码表 lowering 调整](./TNO0409_decode_table_lowering_adjustments_20261103.md) | 常量表在调度前消除依赖；布尔位图保留窄读取，开始新旧版本同场复测。 |
| `TNO0410` | `2026-11-03` | [调整后 24 张表的局部复验](./TNO0410_decode_table_adjusted_local_verification_20261103.md) | 全部原始向量通过；恒零表依赖消除，CSR 确认窄读，22 张表机器码相同。 |
| `TNO0411` | `2026-11-03` | [调整版整机构建与周期轨迹验证](./TNO0411_decode_table_tuned_whole_build_and_equivalence_20261103.md) | 61 个表操作，恒零实例消除；两组 C100000 分别对照原硬件和旧 intrinsic 全部通过。 |
| `TNO0412` | `2026-11-03` | [CSR 局部与整机布局差异](./TNO0412_decode_table_local_vs_whole_codegen_20261103.md) | 整机输入原已寄存器打包；新约束产生额外掩码，局部改善不能直接推断整机收益。 |
| `TNO0413` | `2026-11-03` | [调整后八组整机 walltime](./TNO0413_decode_table_tuned_whole_walltime_20261103.md) | C 比旧 intrinsic 慢 0.617%，8/8；仍比原 RTL 快 1.428%，保留全部样本与局部环境拒绝证据。 |
| `TNO0414` | `2026-11-03` | [两处调整的局部复测与最终结论](./TNO0414_decode_table_tuned_local_results_and_conclusion_20261103.md) | 24张表1,968对；局部退化修复，但整机慢0.617%，不更新性能基线。 |
| `TNO0415` | `2026-11-03` | [CSR lowering 单项消融](./TNO0415_decode_table_csr_ablation_setup_20261103.md) | 只移除布尔位图／读取约束，保留常量折叠，开始 B/C/D 同场对照。 |
| `TNO0416` | `2026-11-03` | [CSR 消融结构一致性](./TNO0416_decode_table_csr_ablation_structure_20261103.md) | GRH、全部C++、布局和调度与C完全一致，仅CSR helper恢复B；smoke通过。 |
| `TNO0417` | `2026-11-04` | [CSR lowering 消融结果](./TNO0417_decode_table_csr_ablation_results_20261104.md) | D/C四胜四负、区间跨零；D仍8/8慢于旧B，撤回CSR未追回整机收益。 |
| `TNO0418` | `2026-11-04` | [恢复CSR并关闭恒定表折叠](./TNO0418_decode_table_csr_only_setup_20261104.md) | E只保留CSR优化，普通常量传播不变；启动B/C/E同场对照。 |
| `TNO0419` | `2026-11-04` | [CSR-only结构恢复与验证](./TNO0419_decode_table_csr_only_structure_20261104.md) | E/B图、129个C++及布局相同；仅CSR对象.text增加4字节，针对性验证通过。 |
| `TNO0420` | `2026-11-04` | [仅CSR优化的整机结果](./TNO0420_decode_table_csr_only_results_20261104.md) | E/C快0.558%、8/8；E/B四胜四负、区间跨零，恢复旧版水平；保留末轮时间漂移。 |
| `TNO0421` | `2026-11-04` | [恒零译码表回退：冻结对照与调查启动](./TNO0421_decode_constant_investigation_start_20261104.md) | C/E 同场八对复测、频率观察及阶段诊断启动。 |
| `TNO0422` | `2026-11-04` | [恒零译码表前端差分与频率观察](./TNO0422_decode_constant_frontend_diff_20261104.md) | 净删除 49 个操作、17 个 Mux 改写均局限于译码锥；捕获 APERF/MPERF 档位变化。 |
| `TNO0423` | `2026-11-04` | [恒零表回退同场复现与频率证据](./TNO0423_decode_constant_reproduced_walltime_20261104.md) | E/C −0.628%、8/8，同场完整保留降频配对；回退再次成立。 |
| `TNO0424` | `2026-11-04` | [恒零表消除后的调度扩散证据](./TNO0424_decode_constant_schedule_divergence_20261104.md) | 完整导出字节一致；source 顺序、4,835 次共享归属差异；额外节点在初次创建时出现。 |
| `TNO0425` | `2026-11-04` | [恒零表回退的动态执行计数](./TNO0425_decode_constant_dynamic_execution_counts_20261104.md) | 相同窗口逐项稳定；C 多 0.584% fire、1.026% 活动写入，PMU 指令少 0.571%。 |
| `TNO0426` | `2026-11-04` | [恒零表调查的 source-order 重放门禁](./TNO0426_decode_constant_source_order_replay_rejected_20261104.md) | 重放严格拒绝：pre-reg-to-mem 快照与后阶段 source 集合不兼容；没有把失败运行当作因果变体。 |
| `TNO0427` | `2026-11-04` | [恒零表回退的 PMU、IP 采样与调查结论](./TNO0427_decode_constant_pmu_and_ip_sampling_conclusion_20261104.md) | E walltime −0.628%、C 后端活动写入 +1.026%；IP 采样按语义组对齐，结构链仍待合法单变量重放确认。 |
| `TNO0428` | `2026-11-04` | [恒零表 post-reg-to-mem 顺序干预与 walltime](./TNO0428_decode_constant_post_reg_to_mem_order_intervention_20261104.md) | 合法快照下 C 使用 E 顺序后 compute node 1,069,057→1,067,572；动态活动写入降 1.080%，但 X/E walltime −0.270%、区间跨零。 |

增量更新（2026-10-14）：[TNO0337 第 20 节](./TNO0337_grhsim_partition_system_redesign_20261013.md)
完成未划分图的操作/融合区域归因，739.8 万条条件记录守恒。223.1 万条 compute 来源是
scheduler 复制，21,430 个写回体跨不同 ASC membership；old/scalar/stage 中分别有
2,751/1,288/1,288 个被分散。下一步明确为消费者侧读取与共享 lowering 的 assignment
派生计账；不是固定六列 piece 权重已可投入搜索。小图、ASan/UBSan、20 文件生成一致性及
三项回归通过，尚无新 assignment 或 walltime。

增量更新（2026-10-14）：[TNO0337 第 21 节](./TNO0337_grhsim_partition_system_redesign_20261013.md#21-完整-asc-移动后的读取共享写回与边界重建2026-10-14)
新增显式 ASC assignment 重放及 GrhSIM 消费者/共享正文视图。真实小图重建确认：一个
ASC 移动可改变共享组、使读取者的调度组从上沿活跃变为两沿活跃，并改变第三分区的输入
打包和生成代码。CMake/CTest、汇总器及 fixture 的 ASan/UBSan、四组生成模型功能检查
通过；普通默认路径的 35 份 HGR/assignment 与冻结 reference 一致。下一步是有限
XiangShan 候选的整图重算对照，尚无新性能数据。

增量更新（2026-10-14）：[TNO0337 第 22 节](./TNO0337_grhsim_partition_system_redesign_20261013.md#22-xiangshan-有限-asc-迁移的完整重建对照2026-10-14)
完成 scalar 对照及两次独立单 ASC 迁移的全量重建/planner 对账。对照 GRH 与四份工作量
报告逐字节复现；96 分区的真实通信接口与评价器一致。两次迁移分别改变 6/14 个分区，
后者仅增加 137 字节却增加 61 个 transfer，并改变 11 个分区的共享写回成员。
新增通用 `repcutAssignmentDirectImpact`，准确复现直接重建范围；CMake/CTest 和
ASan/UBSan 通过。下一步区分图/plan 缓存与 activity 固定点传播，尚无新 walltime。

增量更新（2026-10-14）：[TNO0337 第 23 节](./TNO0337_grhsim_partition_system_redesign_20261013.md#23-首个成组-asc-候选先完成搜索到性能的闭环2026-10-14)
完成首个成组 ASC 搜索到实际性能的闭环：缓存版与完整重算逐项一致，候选将 416 个完整
ASC 从 p27 搬到 p8，重建 10 个分区。node030 CPU96–127、C100000 共 8 对 fresh AB/BA
全部通过功能检查；p27 eval −1.335%，但 Host +1.799%、walltime +1.786%、update +10.818%，
仅 2/8 对胜出，因此不替换性能基线或默认。最大平均 eval 仍是 p2；最大 update-push
所在 p5 的分区源码未变，说明静态最大分区和通信容量约束仍不足以预测最终关键路径。
后续转向有限的 update 尾部定位及候选覆盖面调整，不继续扩大缓存/守恒审计。

增量更新（2026-10-14）：[TNO0337 第 24 节](./TNO0337_grhsim_partition_system_redesign_20261013.md#24-从原始-asc-重新分配的首个完整闭环2026-10-14)
首次从原始未划分 GRH 重新给全部 301,184 个 ASC 分配 32 个新分区，使用
`closure-aware + grhsim-v1`，不读取旧 assignment 标签。精确重算显示 recurring 最大值不变，
通信 calls/bytes 分别下降 15.27%/15.04%，falling compute-core 最大值下降 7.07%，
wide-helper 最大值下降约 49%。同配置真实生成、编译和 node030 CPU96–127 的 8 对
fresh C=100000 AB/BA 全部通过功能检查；Host 中位数 `11.072→10.9075 s`（逐对 −1.468%，
5/8 胜出），update −17.647%，但全局 eval +2.418%，最大平均 eval 从旧 p2 转到新 p11，
因此候选暂不默认。后续定位新 eval 瓶颈的 activation/阶段/同步机制，再做联合目标的少量
从头候选。

增量更新（2026-10-15）：[TNO0337 第 25 节](./TNO0337_grhsim_partition_system_redesign_20261013.md#25-将从头分配设为首道筛选2026-10-15)
将流程固化为“原始 GRH 从头分配 → 廉价结构/后端 gate → 少量局部调整 → 生成/编译/运行”。
新 gate 对 recurring、raw operation、通信峰值和 backend 机制峰值做筛选；当前 from-scratch
候选通过，head-gate JSON 已生成。随后在 candidate 自身上做的局部成组调整只令 falling
compute-core 最大值下降 0.021%，没有达到约 0.5% 的继续编译阈值，因此停止在静态层，
不新增 runtime 候选。后续优先改变从头分配的成本/目标组合，并把局部调整限制为通过 gate
且有明确后端收益的少数结果。

增量更新（2026-10-15）：[TNO0337 第 26 节](./TNO0337_grhsim_partition_system_redesign_20261013.md#26-通信标量强调的边界总量下降仍可能放大接收端尾部2026-10-15)
新增通用可选的 `communication_weight_scale`，默认值为 `1`，用于验证通信权重整体放大
是否能改善从头划分。因子 `2` 的候选总 send calls/bytes 降至 `0.9250/0.8711`，但
最大 receive calls 升至 `1.0623`，在首道结构 gate 被停止，未进入 backend、编译或
runtime，也未改变默认行为。后续转向显式建模接收端 incident/call 尾部，而不是继续
调整单一通信标量。

第 26 节后续探针表明，直接把 receiver exposure 加入 node weight 会造成计算分区严重倾斜；
改为 closure refine 的接收端二级目标虽能降低最大 receive calls，却使 recurring/raw 总和
增加约 `1.45%/1.89%`，receive bytes 峰值升至 `1.254` 倍，仍在首道 gate 被停止。当前
不再继续扫 receiver scale，下一步转向保留 owner/reader 方向的全局多目标 proposal，
显式约束接收 bytes/calls tail 与复制总量。

增量更新（2026-09-23）：TNO0332 §12.6–12.7 记录冻结 `memory_coalesce_v5` 的
残余热点复核和后续实验。decoded register table 的 packed 候选数据/逐项提交约占
`part_3` 模型采样 2.22% / 3.63%；据此选用已有通用 `reg-to-mem` pass 恢复 indexed
storage。只变更 part_3，C=30000 八对交错 AB/BA 全胜：Host −6.284%、wall −6.254%、
全局 eval −8.552%、最大 part eval −18.335%；update 近中性、通信完全不变。候选仍为
显式实验，未加入默认 pipeline；profile 显示剩余热点已分散到多个组合求值函数，继续
按生成结构找通用模式。backend-lowered cost manifest 的并行工作保持独立。

增量更新（2026-09-23）：TNO0332 §12.8 修正 part_28 Verilator `.cpp` 统计口径，完整
构建显示该分区源码由 56.9 MB 增至 108.8 MB。§12.9 按用户建议直接验证全图
`reg-to-mem` 的 walltime：冻结 V5 分区上自动转换 375 组、影响 12 个 part SV，未按
分区/信号名称筛选；C=30000 八对 AB/BA 全胜，Host −12.14%、wall −11.96%、eval
-15.22%、最大分区 eval −18.42%，update +0.36%，通信不变。完整 Difftest/build 审计通过；
结果尚未加入默认 pipeline，需其他 workload 复测。§12.10 加入 baseline / V5 / 全图
reg-to-mem 三组共享横轴时空图及离线交互 HTML，并标明 baseline 跨批次、V5/all-part
同批 AB/BA 的比较边界。

增量更新（2026-09-24）：TNO0332 §12.10 的三组 HTML 对齐既有四组主题，补齐
指标卡、关键线程/Host 标记、详情、分区明细与 CSV 导出；浏览器交互与数据不变性
检查通过，原链接不变。

同日增量：TNO0332 §12.11 在同一 node030 窗口完成 12 轮三臂交错复测（36 个样本），
并生成以新批次数据为源的三组 HTML；全图相对 V5 的 wall 中位数改善为 -12.23%。
同节已追加 HTML 配对字段不匹配的修正及严格浏览器回归结果：三组/96 分区、切换、
排序筛选、CSV、桌面/手机均通过；原始实验数据未变。

同日增量：TNO0332 §12.12 增加默认关闭的 Verilator reg-to-mem 逐组收益筛选；
冻结输入下只拒绝高冲突的 p28 表，保留 p3 转换。两批各 8 对 AB/BA 均确认
p28 eval 约降 35%--36%，但整体 Host/wall 尚无收益，需继续分析关键路径与全局影响。

同日增量：TNO0332 §12.13 将该验证线收为 XiangShan RepCut 默认入口：默认使用
`closure-aware + verilator-v1`，并在 RepCut 后执行全图 `memory-write-coalesce`、
带 `verilator-v1` 逐组门槛的 `reg-to-mem(intent=false)`；库级 profitability 默认
仍为 `None`。完全不传 `XS_REPCUT_*` 覆盖的默认生成与显式验证线 package inventory
完全一致；node030 C=30000 交错 8 对 AB/BA 全部通过功能校验，默认/验证线的
Host/wall 配对中位变化分别为 +0.37%/+0.33%，处于测量噪声范围内。

2026-09-30 增量：[TNO0333 §7.16](./TNO0333_repcut_grhsim_backend_20260925.md#716-batch-trigger-bitmap语义验证与维护成本2026-09-30)
记录 batch trigger bitmap 的完整功能验证与 C=100000 交错对照。逐值条件标记
使 Host 增加 55.19%；改为无分支标记后仍增加 4.67%，均为各自四对 AB/BA
的配对中位数。采样和机器码表明新增激活元数据的维护成本落在 compute
路径上；该实验保持默认关闭，现有默认调度和 Verilator 路径不变。

2026-10-01 增量：[TNO0333 §7.17](./TNO0333_repcut_grhsim_backend_20260925.md#717-在-supernode-边界合并-batch-标记2026-10-01)
记录 supernode 边界合并 bitmap 的验证：compute 标记减少 85.17%，但保守合并
新增约 4.85 亿次空调用，两轮各四对 C=100000 的 Host 配对中位为 +1.05%/+0.62%。
精确覆盖诊断通过，32 分区非空调用数相同；99.927% 的 compute batch 仅有一个
活动字节，新增 bitmap 与已有调度信息高度重复。继续验证精确局部累积版本。

2026-10-01 后续：[TNO0333 §7.17](./TNO0333_repcut_grhsim_backend_20260925.md#717-在-supernode-边界合并-batch-标记2026-10-01)
补齐精确局部累积的结果：32 分区 skipped/useful/empty 与精确 bitmap 全部一致，
但 C=100000 四对 AB/BA 的 Host 配对中位增加 4.35%，四对均退化，p3 eval 增加
14.58%。局部累积没有缩小机器码，代表性热点栈引用增加。两种边界方案均保持
默认关闭；本轮收敛，后续优先减少活跃 payload 本身的状态访问与激活传播成本。

2026-10-01 增量：[TNO0333 §7.18](./TNO0333_repcut_grhsim_backend_20260925.md#718-活跃-payload-的索引存活期优化2026-10-01)
记录通用 packed-array 索引延迟读取：27 个分区消除 4495 个提前快照，p29/b137
栈帧分配从 5192 降至 2008 B。node030 C=100000 两轮共 8 对全部通过 Difftest，
p15/p28/p29 eval 分别约降 2.22%/2.24%/1.70%，均 8/8 对变快；Host 配对中位
下降 1.08%，6/8 对变快，但 p3 未改善，未修改阶段仍有波动。保持候选默认关闭，
下一步聚焦 p3/p6 残余热点中的中间值存活期与激活累积。

2026-10-01 增量：[TNO0333 §7.19](./TNO0333_repcut_grhsim_backend_20260925.md#719-纯-compute-块中的宽状态引用2026-10-01)
记录纯 compute 宽状态引用的实现与验证：23 个分区替换 13295 个快照，p3/b46
栈帧 9848→208 B，但 C=100000 两轮共 8 对的 Host/elapsed 配对中位为
+0.44%/+0.42%，仅 2/8 变快。全部功能通过；采样支持 p3/b46 局部改善，
同时发现 p6/b47 寄存器分配改变使代码增大，p6/b184 的主要栈压力未消除。
保持默认关闭，后续回到索引版本研究普通中间值的依赖调度。

2026-10-01 后续：[TNO0333 §7.20](./TNO0333_repcut_grhsim_backend_20260925.md#720-局部-compute-按消费者顺序生成2026-10-01)
记录纯 compute 局部值按消费者顺序生成：p6/b184 代码 296406→255170 B、
静态栈引用 20444→13444，p6 eval 稳定下降 8.31%；但 p15/p29 eval 增加，
C=100000 两轮共 8 对 Host 全部退化，配对中位 +1.084%。统一 64 B 函数入口
对齐仍为 +1.461%，候选保持默认关闭。p29 的主要热点源代码未改，需逐 step
关键路径诊断区分其长尾与同步/布局影响，暂不下完整因果结论。

筛选版更新：以 `Σ 位宽×操作跨度` 至少减少 1048576 且减少至少 25% 为通用门槛，
只保留 104 个 supernode/42 个 compute 文件，C=100000 两轮 8 对 Host 配对中位
`-1.609%`（8/8），全局 eval `-2.008%`，p6 `-5.682%`；关键路径抽样 phase
`-0.934%`，默认仍关闭，待第二 workload 泛化验证。

2026-10-01 增量：[TNO0333 §7.21](./TNO0333_repcut_grhsim_backend_20260925.md#721-当前优化线与-verilator-的条件瓶颈对照2026-10-01)
记录当前 selective GrhSIM 与冻结 Verilator O3 的同 step 条件瓶颈对照及旧规则复查，
32 次 C=100000 均通过 Difftest。p29 成为瓶颈时 eval 92.98/27.54 µs，但两沿合计
98.29/64.18 µs，不能把半周期约 3.4 倍解释为整周期工作量。PMU 与机器码将长 mux
链列为优先候选；旧 bool-eager 在固定瓶颈样本中使 p10 eval 减少 13.76%，但未覆盖
p29 主要热点，值得独立验证与当前线叠加。未改变生产代码或默认选项。

2026-10-01 后续：[TNO0333 §7.22](./TNO0333_repcut_grhsim_backend_20260925.md#722-长优先-mux-链的按需选择2026-10-01)
记录长优先 mux 链按需选择的通用实现。专项测试已通过，覆盖重叠条件、共享结果、
跨节点边界和 520 级链；默认关闭，未改变 Verilator。完整香山生成与 C=100000
交错对照继续进行，当前尚不宣称性能收益。

2026-10-01 增量：[TNO0333 §7.22](./TNO0333_repcut_grhsim_backend_20260925.md#722-长优先-mux-链的按需选择2026-10-01)
已补充两版完整整机结果和条件 PMU。捕获 lambda 版 Host +42.118%；修正为函数内展开后，
11 对无已知编译重叠样本仍为 +3.765%，不能采用。p29 两沿 eval 约 -35%，但短链的
cmov 被大量难预测分支替代，造成其他分区退化；全部通过样本及一次已知重叠均保留并披露。
统一 128 级 IR 链长门槛的整机验证正在进行，优化总开关仍默认关闭。

2026-10-01 完整验证：[TNO0333 §7.22](./TNO0333_repcut_grhsim_backend_20260925.md#722-长优先-mux-链的按需选择2026-10-01)
已补充 min128 的两组各八对普通运行及条件 PMU，48 次正式 C=100000 全部通过。
相对 selective GrhSIM 的 Host 配对中位 `-9.076%`，相对 Verilator O3 为 `-14.636%`，
两组均 8/8 获胜。p29 错分支约减少 98%，两沿 eval 合计已接近 Verilator，
但单沿工作不均仍影响关键路径；p10/p18 两沿仍慢约 28%/35%，列为下一优先级。
长常量链的局部退化仍保留为规则边界，128 并非已证明最优值，优化总开关保持默认关闭。

2026-10-01 常量优先位图：[TNO0333 §7.23](./TNO0333_repcut_grhsim_backend_20260925.md#723-长常量选择链的优先位图生成2026-10-01)
在常量筛选版之上实验每 64 条件分组的位图、首命中定位和常量查表，保持原优先级，不依赖条件互斥；默认关闭。
18 模式专项通过，整机基线与独立条件选样口径已固定；完整生成及 C=100000 验证接续进行。

2026-10-01 位图完整结果：[TNO0333 §7.23](./TNO0333_repcut_grhsim_backend_20260925.md#723-长常量选择链的优先位图生成2026-10-01)
32 条常量链、8520 个 mux 转为优先位图，仅 15 个 compute 文件变化，其他 7439 个对象不变。
相对常量筛选版，16 对 C=100000 Host/walltime 配对中位 `-0.546%/-0.508%`，14 对更快；
p21 全程平均 eval `-0.952%`。40 次正式运行、12 次 smoke、完整回归及专项均通过。
PMU 确认 p21 动态指令下降，但错分支增加，局部耗时与轻量 timing 不完全一致；不把局部 -7% 宣称为稳定收益。
主要关键路径未改变，开关仍默认关闭；完整作用域、收益与归因边界已补入原节。

2026-10-01 常量链修正：[TNO0333 §7.22](./TNO0333_repcut_grhsim_backend_20260925.md#722-长优先-mux-链的按需选择2026-10-01)
新增通用已知常量候选筛选，撤销 32 条常量链的分支展开，保留 96 条动态链及其对象不变。
相对上一版 min128，16 对 C=100000 的 Host/walltime 配对中位分别为 `-0.486%/-0.505%`，
13 对更快、1 对持平、2 对略慢；40 次正式运行全部通过。原固定 p21 瓶颈步号的 eval
减少 6.565%、错分支减少 75.550%，但全样本收益较小，主要瓶颈仍未消除。
默认/开启选项完整回归、两后端 package 测试、补强专项均通过；总开关仍默认关闭。

2026-10-01 bool-eager 复查启动：[TNO0333 §7.24](./TNO0333_repcut_grhsim_backend_20260925.md#724-在最新有效线上复查-bool-eager2026-10-01)
以最新常量位图版为固定基线，全图只叠加既有一位布尔非短路规则，不改默认值。
完整生成、全包作用域审计、回归和 16 对 C=100000 AB/BA 口径已固定；瓶颈条件沿用独立历史标签。

2026-10-01 bool-eager 复查完成：[TNO0333 §7.24](./TNO0333_repcut_grhsim_backend_20260925.md#724-在最新有效线上复查-bool-eager2026-10-01)
16 对普通运行全部更快，Host/walltime 配对中位 `-1.489%/-1.494%`，全局 eval `-2.257%`。
p10 固定瓶颈步 eval `-13.847%`、PMU 错分支 `-41.787%`，p18 普通 eval 基本不变。
新 Verilator 对照下两沿合计 p10/p18 仍慢 `11.050%/30.198%`，p29 略快 `2.595%` 但单沿集中仍在。
p18 条件 compute/commit 为 `41.057/8.506 us`；提交值得优化但不是全部瓶颈。
64 次 C=100000、18 次 smoke 及完整回归均通过；不改生产默认值，通用提交/激活候选及 p29 语义边界已追加原节。

2026-10-01 小集合 commit 实验：[TNO0333 §7.25](./TNO0333_repcut_grhsim_backend_20260925.md#725-少量激活写入的标量寄存器提交2026-10-01)
以 bool-eager 为固定基线，仅对实际激活写入不超过 2 次的普通标量提交实验条件掩码更新，
保留精确变化检测、reader 激活、计数与多写者顺序；通用选项默认关闭，Verilator 不变。
12 模式专项通过；完整回归、全包逆变换审计、16 对 C=100000 及条件归因接续进行，尚无性能结论。

2026-10-01 小集合 commit 实验完成：[TNO0333 §7.25](./TNO0333_repcut_grhsim_backend_20260925.md#725-少量激活写入的标量寄存器提交2026-10-01)
239585 次通用标量提交改写，132 个 commit 文件变化，其余源码和对象的作用域审计通过。
16 对普通 walltime 配对中位 `-0.428%`，但仅 10/16 更快，AB/BA 为 `-0.771%/+0.143%`，不能认定稳定整机收益。
p10/p18 普通 eval `-1.860%/-3.063%`；固定瓶颈 commit `-9.406%/-18.461%`、错分支 `-38.420%/-25.621%`，同时指令增加。
p3 普通 eval `+2.899%`，固定瓶颈 commit `+36.543%`，说明小激活集合门槛不保证收益；候选默认保持关闭，继续以 bool-eager 为探索基线。
52 次 C=100000、14 次 smoke、完整回归与增强 14 模式专项全部通过；精确 reader 激活与采样步固定点轮数检查闭合。

2026-10-01 相同 reader 提交合并：[TNO0333 §7.26](./TNO0333_repcut_grhsim_backend_20260925.md#726-相同-reader-集合的标量提交合并2026-10-01)
仍以 bool-eager 为基线，统一尝试同一 guard 内最多 8 个单写者、全掩码标量的共享变化分支与 reader 激活。
15 模式功能/精确计数专项及结构化逆变换正负例通过；默认关闭，不按模块或分区筛选。
完整生成、作用域审计、16 对 C=100000 与条件归因接续进行，暂不报告性能收益。

2026-10-01 相同 reader 提交合并完成：[TNO0333 §7.26](./TNO0333_repcut_grhsim_backend_20260925.md#726-相同-reader-集合的标量提交合并2026-10-01)
通用规则实际覆盖 28014 组、111473 次提交，130 个 commit 文件变化，其他源码/对象作用域审计通过。
16 对普通 walltime 配对中位 `-0.541%`，14/16 更快，AB/BA 均改善（`-0.540%/-0.568%`）；全局 eval `-0.987%`。
p10/p18 普通 eval `-2.681%/-1.734%`、固定瓶颈 commit `-17.929%/-13.129%`，动态指令没有增加；p3 普通 eval 基本持平。
p28 普通 eval `+1.473%`，p28/p29 的不同探针计时方向相反，未把它们归因为直接计算收益；p29 重半周期问题仍在。
52 次 C=100000、14 次 smoke、完整默认/开启回归及 lockstep 组合验证全部通过。选项默认关闭，后续优先拆解活跃 compute 的重复成本。

2026-10-01 活跃 compute 残余与逐字宽拼接：[TNO0333 §7.27](./TNO0333_repcut_grhsim_backend_20260925.md#727-活跃-compute-残余归因与逐字宽拼接2026-10-01)
冻结 bool-eager 的逐 batch 计时和 `.text` 恒等源码 profile 将 p10/b15、b17 与 p18/b18 的主要 cycles 样本定位到宽拼接。
实现默认关闭、纯表达式及无别名约束的通用逐字拼接；八模式功能专项和源码语义变异拒绝检查通过。
继续完整回归、全包作用域审计及 16 对 C=100000 验证；此检查点不宣称 walltime 收益。

2026-10-01 逐字宽拼接完整验证：[TNO0333 §7.27](./TNO0333_repcut_grhsim_backend_20260925.md#727-活跃-compute-残余归因与逐字宽拼接2026-10-01)
全图 10437 个 concat 改写覆盖 32 分区，1578 个 compute 文件通过语义逆变换审计；实际 archive 778 个对象变化、6676 个相同，默认/开启及两后端回归通过。
16 对 C=100000 的 walltime 配对中位 `-0.515%`、10/16 更快，AB/BA 均为小幅正向；p10 普通 eval `-1.473%`，固定瓶颈 compute `-6.039%`，主要热 batch 的指令与时间同步下降。
p18 单个拼接 batch 有收益但其余计算分散，p29 普通 eval 16/16 退化 `+1.454%` 且重半周期热点机器码未变，间接原因未定。候选仍默认关闭，不以局部收益替代整机结论。
56 次 C=100000、16 次 smoke、UBSan、完整源码/对象审计及动态轮数和 batch 激活向量核验均通过。

2026-10-02 关键路径与 all-spin 派发：[TNO0333 §7.29](./TNO0333_repcut_grhsim_backend_20260925.md#729-commit-demand-后的逐步关键路径与残余热点2026-10-02)
固定历史瓶颈步证实 commit-demand 的 p29 当前沿 eval `61.279→52.565 us`，两沿合计 `-13.648%`，并非主要把计算搬到下一沿；残余关键路径转向 p3 的分散计算。
框架逐步计时发现 Host 在 all-spin 派发时仍逐 worker 加锁清理异常槽，已利用既有完成/任务发布握手消除该冗余锁，两个后端共用，并修正原有 worker 自旋/Host CV 的残留完成标志。
最终代码各 4 对 C=100000，GrhSIM / Verilator walltime 配对中位 `-2.968%/-1.435%`，分别 4/4 更快；模型和通信复制代码保持不变，局部复制耗时上升的反方向证据一并记录。
两后端 package 回归、混合等待/异常恢复、16 次最终正式 Difftest、生成与实测派发函数恒等核验均通过。原有模型实验选项默认值不变，未提交；初版和最终版分开统计，不合并不同 ELF/窗口的收益。

2026-10-02 新派发下的 p3 残余与拼接覆盖：[TNO0333 §7.30](./TNO0333_repcut_grhsim_backend_20260925.md#730-新派发框架下的-p3-残余与既有规则复查2026-10-02)
重新冻结关键路径标签并复查 cycles/源码热点；已有逐字拼接在最新框架上 8 对 C100000 walltime 配对中位 -0.424%，但 p3 热点分散，局部 batch 改善未等比例传递到整机。
补齐内联异步 memory read 的通用纯读取判定，全图新增 118 个 concat（总 10555），50 源文件/41 链接对象变化；源码逆变换、默认/开启和两后端回归、UBSan 及香山 Difftest 全部通过。
新增覆盖相对已有规则 8 对 walltime -0.581%（6/8）；完整候选直接对原始未开启拼接基线 4 对 -0.581%（4/4），不与不同窗口增益相加。p3 普通 eval 未改善，选项仍默认关闭；下一优先级转向分散的变化检测/激活传播，并复查已有分组实现。

2026-10-02 p3 变化传播与精确标志打包：[TNO0333 §7.31](./TNO0333_repcut_grhsim_backend_20260925.md#731-p3-分布式变化传播精确-group-标志打包2026-10-02)
复查已有 deferred-activation 分组，针对同一源反复更新多个组标志的模式，实现不扩大激活集合的通用 bitmask 候选，默认关闭；9 模式专项已通过。
本轮固定上一节最终 wordwise_memory 为 baseline，预定两个窗口共 8 对普通 AB/BA 及独立固定标签诊断；完整收益在同节追加，不混用不同基线。
已完成：32 分区全量 off/on 与 7552 文件核验，3851 个 supernode 的更新 378587→144526；24 次正式 Difftest、8 次 smoke 及全部回归通过。
8 对普通 walltime 配对中位 +0.091%（仅 3/8 更快），p3 eval +0.072%，未验证稳定收益，保持默认关闭。p3/b19、b20 因增加条件选择/掩码处理而静态指令增加；固定标签 timeline 的反方向改善也完整保留，不混入普通 walltime。
下一候选先检查已有 active 字聚合覆盖，考虑直接累计最终激活掩码以避免 group 标志的打包/解码往返，不按分区或信号名筛选。

2026-10-02 直接累计最终激活掩码：[TNO0333 §7.32](./TNO0333_repcut_grhsim_backend_20260925.md#732-直接累计最终激活掩码2026-10-02)
针对目标集中且源值重叠的完整 deferred 组，直接累计最终 active bit，保留局部/全局和未覆盖路径，新增选项默认关闭；专项及 UBSan 已通过。
baseline 仍为 §7.30 的 wordwise_memory，不叠加上一轮 packed 候选；全量位符号核验与两个窗口共 8 对普通 AB/BA 在同节记录。
第一轮完成：8 对 walltime +0.061%（4/8 更快），p3 eval −1.870%，但 p18 +3.193%，未验证整体收益。实际机器码定位到 p18/b195、b210 逐源掩码展开导致约 20% 静态指令增加；第二轮尝试按相同最终目标集归并源条件后只展开一次，仍是通用结构规则、默认关闭，结果继续追加同节。
第二轮也已完成：全量展开条数 24052→7705，p18/b195、b210 的静态指令基本恢复至基线规模，但 8 对普通 walltime +0.274%（3/8 更快），p3 eval −0.885%、p18 +1.631%，仍无整体加速。24 次正式 Difftest、8 次 smoke、完整回归及两类 sanitizer 通过；不启用默认。b210 仍有 22→38 条条件跳转，可作为后续动态诊断入口，不按分区名称修补。

2026-10-02 b210 宽值变化检测归因：[TNO0333 §7.33](./TNO0333_repcut_grhsim_backend_20260925.md#733-b210-宽值变化检测分支归因与-xor-归约2026-10-02)
等机器码源码映射将新增 16 条跳转定位到 1024-bit 赋值比较；固定瓶颈 PMU 每步约多 11.78 次分支、0.884 次 miss，但计时基本持平，不能据此解释全部退步。新增通用 `wide_assign_xor` 实验选项（默认关闭），在有效 wordwise_memory 基线上单独测量；已核验 32 个 runtime header、1538 调用点，专项通过。Clang 在 b210 仍产生比较分支链，因此不将 XOR 写法等同于机器级无分支；完整结果在同节追加。
完整复测已完成：8 对普通 walltime +0.426%（仅 1/8 更快）、全局 eval +0.605%，p18 eval +0.836%，不作为新基线。b195/b179 的动态指令减少约 1.2%/1.4%，但局部 PMU cycles 未改善；b210 分支链仍在。全部回归、Difftest 和 sanitizer 通过，选项保持关闭；下一候选优先考察少量下游激活时如何消费 `changed`，不再仅改变差异归约写法。

2026-10-02 宽值条件激活：[TNO0333 §7.34](./TNO0333_repcut_grhsim_backend_20260925.md#734-宽值变化结果的低成本条件激活2026-10-02)
复用精确条件掩码处理普通宽值赋值的返回值，按实际活动字写入数筛选，新增预算选项默认关闭；本轮预设全分区预算 1，不叠加 XOR 或直接累加器。专项通过，完整生成、回归及八对普通/独立诊断继续在同节记录；预览显示 b195 分支与栈访问减少，但 b179 分支减少伴随栈访问增加，必须以动态开销和 walltime 判定。
完整验证已完成：默认关闭的 7552 个生成文件逐字节相同；候选统一命中 30 分区、660 文件、2185 处，28 次正式 C100000、10 次 smoke、回归及 sanitizer 均通过。8 对普通 walltime +0.215%（2/8 更快），p6 eval −1.381%，p18 +1.264%，不启用默认。p18/b179 的长 Boolean 归约在指令选择阶段展开为多位掩码 CMOV 链，动态指令 +17.976%、cycles +21.223%；p6/b158 则指令基本不变、miss −78.810%、cycles −39.116%。局部得失均记录，下一步优先验证长 Boolean 归约到多位掩码的通用改写，尚未实现。

2026-10-02 长 Boolean 归约物化：[TNO0333 §7.35](./TNO0333_repcut_grhsim_backend_20260925.md#735-长-boolean-归约到多位掩码的物化实验2026-10-02)
针对 §7.34 的 CMOV 链膨胀，新增默认关闭的结构筛选选项；保留原 Boolean 归约，在多位掩码生成前物化一次最终谓词。预设门槛 32，分别验证单项与叠加宽值条件激活；基线仍为有效 wordwise_memory，进展与最终数据在同节追加。
完整验证已完成：新规则命中 31 分区、296 组、148 文件；默认 7552 文件逐字节相同，回归及 sanitizer、56 次正式 C100000 和 20 次 smoke 均通过。单项/组合各 8 对 walltime 配对中位数 −0.341%/−0.600%（均 5/8 更快），窗口/顺序波动明显，均不启用默认。组合将 b179 CMOV 467→46、栈帧 1176→648 bytes；相对上一轮 wide 候选的直接 PMU 指令 −15.565%、cycles −14.372%，p6/b158 的已有收益保留，但不能外推为整体 −15% 加速。

2026-10-02 当前瓶颈与 Verilator 复核：[TNO0333 §7.36](./TNO0333_repcut_grhsim_backend_20260925.md#736-当前有效线与-verilator-的瓶颈均值复核2026-10-02)
当前 wordwise_memory 与最终 all-spin 框架的 Verilator/O3 完成 C100000 四对交错，同一步号/clock 对齐，每后端 12600 个 timeline 样本。G 瓶颈以 p3（30.75%）为首，p25/p26/p27 合计 17.38%；V 97.98% 的瓶颈是 p3。独立标签的两沿 eval 显示 p18/p10 仍比 V 慢约 32%/15%，p29/p26 两沿总量反而少约 11%/12%，应区分计算总量与半周期集中；完整 32 分区条件均值和匹配对照已记录，不开展编译后反馈或更改默认。

2026-10-03 GrhSIM/Verilator 瓶颈 PMU 与代码归因：[TNO0333 §7.37](./TNO0333_repcut_grhsim_backend_20260925.md#737-grhsimverilator-瓶颈分区的代码与-pmu-归因2026-10-03)
当前有效线的 4 对 core-PMU 与 2 对 cache-PMU 交错采样显示：p25/p26/p27 的 GrhSIM 指令约为 Verilator 的 1.38–1.97 倍、cache traffic 约 2.0–2.2 倍，IPC 更低；p29 主要是约 2.5 倍 cache reference 和 1.38 倍指令，而不是分支 miss；p18 指令更少但 IPC 1.48 对 2.22，属于间接访存/依赖链问题。静态代码对照显示 GrhSIM 的直接 batch 调度、activity-word、slot 数组和 any_changed 传播模板，和 Verilator 的 dirty-trigger phase/直接字段访问不同；初步结论是后端通用调度与状态表示开销，而非某个 RTL 信号的特例。下一步优先验证 active-batch list/bitmap 和 slot 访问局部化，保持默认与 Verilator 不变。

2026-10-03 上节归因勘误及瓶颈步复核：[TNO0333 §7.38](./TNO0333_repcut_grhsim_backend_20260925.md#738-瓶颈归因勘误指令取码活跃覆盖与-bool-别名2026-10-03)
node030 的通用 cache 事件混合指令/数据请求，不能证明 slot 间接访存主因。分离事件后三个事件组共六对 C100000 显示，p18/p25/p26/p27 的 miss 约 96%–98% 来自指令，前端供指不足高于 Verilator；p29 同时存在较高数据请求和后端阻塞，需要单独看待。
p25/p26/p27 的瓶颈步有 93%–95% 的 batch 非空，空调用探针计时不足 1%，不再优先追加调度元数据。全图发现 105620 处声明可证明的纯 bool 引用未命中已有 eager 规则，正据此验证通用覆盖补全；默认及 Verilator 路径保持不变。此前 §7.37 的间接访存归因、对象数/batch 数混称及 p25 指令比值以上述勘误为准。

本轮补全与验证已完成：真实生成器覆盖还包含局部临时量和内联叶子，核对 7552 文件后仅 2547 个 compute 文件变化；保留冻结线的既有选择链优化。实际实现完成 24 次正式 C100000、8 次 smoke、三项 CTest 和 UBSan，全部通过。固定瓶颈步 p25/p27 的 branch miss −35.34%/−36.66%、cycles −6.91%/−7.40%、独立 timeline 耗时 −6.30%/−6.82%；普通八对 walltime 配对中位数 −1.493%，7/8 更快。额外 timeline 的全局均值未同步改善，p28 存在未能在同一步重复的长尾，因此保留波动和不确定性，不改默认。下一步优先分析 p18 未改善的活跃控制流/供指热点，不走编译后反馈或分区名特例。

2026-10-03 p18 定向归因与选择运算验证：[TNO0333 §7.40](./TNO0333_repcut_grhsim_backend_20260925.md#740-纯-bool-alias-基线上的-p18-定向归因与选择运算原型2026-10-03)
以纯 bool alias 补全为共同基线，固定 239 个 p18 瓶颈步对照 Verilator；关键沿 cycles 高 7.35%、branch misses 高 87.45%，compute/commit 的周期样本占约 77%/17%。取消 compute 活动冷提示的独立原型，12 对 walltime 配对中位数 −0.648%，但 p18 未改善。另一原型验证零/标量 OR 选择项提示：定位到 Clang 的 CMOV→branch 编译阶段，p18 固定步 misses −5.95%、cycles −1.73%；16 对 walltime 中位趋势仅 −0.247%，保留一次长尾后算术均值反而增加，不启用默认。80 次正式 C100000、18 次 smoke、两组 UBSan 标量语义验证通过；未叠加候选或采用按分区名单优化。

2026-10-03 零标量 OR 选择项的 IR 实现与复测：[TNO0333 §7.41](./TNO0333_repcut_grhsim_backend_20260925.md#741-零标量-or-选择项的-ir-实现与复测2026-10-03)
已实现默认关闭的 `scalar_leaf_mux_unpredictable`，按 IR 类型、零常量、纯读取与直接 OR 使用关系筛选，不匹配模块/信号名。核对 7552 文件，关闭与纯 alias 基线逐字节一致；补全寄存器/锁存器读取别名后覆盖 172997 项，变化 356 个 compute object。最终 12 对 C100000 walltime 配对中位数 −0.928%，12/12 更快；固定 p18 瓶颈步 branch misses −5.160%、cycles −1.093%，尚属小幅收益，未改变默认。初版与补全版合计 56 次正式 Difftest、12 次 smoke 和最终五项 CTest/Clang23、GCC+UBSan 语义测试通过。下一步转向补全版真实残余热点与 p18 commit 控制流，不叠加百分比或扩大到任意内联选择。

2026-10-03 p18 残余 commit 固定 IP 归因：[TNO0333 §7.42](./TNO0333_repcut_grhsim_backend_20260925.md#742-补全版-p18-残余-commit-路径的固定指令采样2026-10-03)
最终 IR 候选与纯 alias 基线在相同 239 个 p18 瓶颈步上各完成 4 对 cycles/branch-misses 采样。commit 在 cycles IP 样本中约 16.86%→15.74%，在 branch-misses 样本中约 45.28%→43.97%；`eval_commit_batch_256()` 仍是最大提交函数。branch-misses 区间总量 −3.545%，但插桩 cycles +1.570%，与无探针生产 PMU 方向不同，不用探针 cycles 替代 walltime。下一步优先研究合法提交 guard 内的激活掩码累计与批量 flush，保持默认和 Verilator 路径不变。

同节已追加同 reader 分组复测：以最终 leaf-mux 为 A，仅叠加已有通用分组为 B，全部 32 个分区统一启用，覆盖 28014 组/111473 个标量写入；130 个 commit 对象变化、7324 个对象相同，冻结线的按需计算完整保留。16 对 C100000 walltime 配对中位数 −0.626%（12 胜、2 平、2 负），Host −0.640%；固定 p18 瓶颈步 cycles −3.142%、错分支 −10.331%。普通版 p25/p26/p27 的 eval 则稳定退化 +2.414%/+0.823%/+2.273%，不隐藏局部损失。标签及 harness 核对显示其瓶颈均在下降沿，而本规则主要减少上升沿提交；p25/p27 下降沿动态指令近乎不变但 cycles 增加，布局/取指/预测状态仍待分离，不能直接归因于算得更多。36 次正式 Difftest、6 次 C100 smoke、最终 C1000 smoke 与六项 CTest 通过，默认保持关闭，不改 Verilator，也不把不同基线的收益百分比相加。

同节进一步完成布局消融：仅给 130 个 commit 对象补齐不执行的尾部字节，将全部 6859 个 compute 入口恢复到相同基线地址。两布局各八对新测中，p25 的 eval 由 natural +2.302% 变为 padded −1.171%，p26/p27 由 +0.544%/+0.274% 回到约持平；固定下降沿的 cycles 和前端未供给槽也同步反转，支持布局相关的前端效应，不支持简单归因于更多计算、IC miss 或错分支。p3/p10/p29 仍有得失，整机 walltime 为 natural −0.463%、padded −0.339%，未证明 padding 更好，因此不启用。56 次正式 C100000、28 次 smoke 及重定位/身份审计通过；下一步考虑统一、预先确定的函数/分区布局规则，不使用按旧编译尺寸补齐或分区名单作为生产优化。

同节按用户要求只追加一项小范围布局试验：在同 reader 自然候选上，将全部模型可执行段统一提高到至少 64 字节对齐，不改指令/常量/重定位内容，不按分区或编译后反馈特调。四对 C100000 walltime 配对中位数 −2.020%（4/4 更快）、全局 eval −2.506%；p3 −2.768%，p25/p26/p27 −5.373%/−3.623%/−3.669%。31/32 个分区 eval 中位趋势改善，p12 +0.142%，个别 update 仍退化；ELF 仅增大 0.184%。8 次正式 Difftest、2 次初始化 smoke 及身份审计通过。保留这个简单候选，不改默认，并在此收住布局搜索，后续回到真实计算与活跃路径热点。

随后按用户追加授权，仅补测 32/128 两个相邻档位：三版同窗各六次 C100000、位置/先后顺序平衡。相对 64，32 的 walltime 配对中位数 −0.156%（4/6 更快），128 +0.125%（3/6 更快），未显示足够稳定的额外收益；p10/p18/p29 与 p25/p26/p27 仍有局部取舍。18 次正式 Difftest、3 次 smoke 及身份审计通过。暂保留 64 为独立候选，不宣称最优，不改默认，并结束本轮布局搜索；完整三档结果继续记于同节。

2026-10-03 相邻提交精确掩码原型与残余归因：[TNO0333 §7.43](./TNO0333_repcut_grhsim_backend_20260925.md#743-相邻标量提交的精确激活掩码原型与残余归因2026-10-03)
以同 reader 自然布局为 A，不叠加 64 字节对齐。通用原型将同 guard、同小块内不同 reader 的连续标量写入合成精确掩码，命中 30 分区、3006 组/15035 次写入，仅 67 个 commit 对象变化。八对普通 C100000 walltime 配对中位数 −0.892%（8/8 更快），全局 eval −1.687%、update +0.779%；但分段计时显示 p18 commit 仅约 7.9635→7.8370 us，p3 的主要改善来自未修改 compute，不能把全部收益归于新规则。40 次正式 Difftest、12 次 smoke、Clang23/GCC+UBSan 语义验证及输入/固定点轮数核验通过。保留生成 C++ 原型、不改默认，下一步优先 p18 的活跃 compute，而非继续扩大提交或布局搜索。

同节按用户要求追加共同 align64 的组合验证：A 复用同 reader +64，B 为精确掩码 +64；统一对齐后仍仅 67 个 commit 对象变化、7387 个对象相同。八对 C100000 walltime 配对中位数 +0.241%（4 胜 4 负），Host +0.228%，全局 eval +0.490%；AB/BA 各自也均为 2/4 更快，未显示稳定增量收益。p3 的平均 eval 虽 −1.889%（8/8），p6/p27 却 +0.798%/+2.874%，局部均值改善未兑现为 walltime。16 次正式 Difftest、两次初始化 smoke 及身份/对齐审计通过。保留所有成功样本与全部分区数据；不叠加历史收益、不宣称固定退化，也不据此改变正式默认。

随后按同节完成 align64 关键路径与尺寸中和控制：逐 step 诊断显示瓶颈在 p3/p6/p18/p10/p29/p26 之间迁移，p29 本身无改动但因前序 object 缩短而整体前移约 48.6 KB。core PMU 中 candidate 关键 cohort 的 p27/p29 cycles +6.4%/+5.6%，instructions 基本不变，支持布局/预测效应。将 67 个改动 object 的 `.text` 补至两版逐 object 最大尺寸后，6859 个 compute 入口地址完全不变；8 对 C100000 walltime 配对中位数 **−1.212%（8/8 更快）**，Host −1.199%、全局 eval −1.623%。这证明精确掩码本身有约 1.2% 潜力，但 padding 只作因果控制，不直接作为生产规则。64 字节对齐保留；下一步研究通用的提交成本/布局扰动约束，不按分区或信号名单特调。

2026-10-04 同节追加归因勘误：上段“证明约 1.2% 纯算法潜力”的表述过强。
两个布局窗口相隔约五小时，且尺寸中和未固定数据区；按当前版本成为瓶颈选样本
还存在选择偏差。固定历史步号重算后，p29 cycles +3.179%、branch misses
+11.153%，p27/p18 的 cycles 增加但 misses 减少，不能统一归因于分支预测。
已启动同一窗口、四组位置平衡的普通/尺寸中和 A/B 对照，并计划使用固定步号
检查前端供给、指令缓存和 ITLB；64 字节对齐继续保留，不改生产默认。

同节现已完成上述归因：同窗八轮普通四组中，原布局 walltime −0.461%、尺寸
中和 −1.142%，均 8/8 更快。共享探针令全部 compute 入口再移动 13568 bytes，
且观测方向与普通版反转，因此补了不改 ELF 的 perf 采样：neutral B/A 的 p3
compute cycles −3.881%、前端未供给槽 −6.507%、IC miss −11.743%，四轮同向，
主要支持未改 compute 的前端效率改善，不是直接提交成本同比减少。额外只移
堆起点 4 KiB 的控制为 −0.553%（4/6），不据此认定固定堆收益；新 B 相对堆
起点一致的旧版仍 −0.834%（6/6）。合计 130 次正式 C100000、27 次初始化
检查全部通过，所有成功样本保留。64 字节保留，padding/heap4k 不进入默认；
结束本轮布局消融，优先回到活跃 compute 的代码体积与供指压力。

2026-10-04 活跃 compute 位搬运压缩：[TNO0333 §7.44](./TNO0333_repcut_grhsim_backend_20260925.md#744-活跃-compute-的重复位搬运压缩2026-10-04)
固定精确掩码 +64 原布局基线，分别测试拆位循环、拼位循环和相邻八 bool 的
无循环打包。前两者未取得 walltime 收益；无循环版使用编译期布局资格与
单次读取/掩码乘法，非连续字段保留标量展开，不使用编译后反馈或名字名单。
首窗八对 −0.904%、确认四对 −1.029%，合计 12 对 walltime 配对中位数
**−0.965%（12/12 更快）**，全局 eval −1.541%；原 ELF 采样的改动函数
动态指令 −7.480%、cycles −4.865%、IC miss −12.715%，四轮同向。72 次
正式 C100000、12 次 C100 与专项等价性/ASan+UBSan 检查通过。保留无循环
生成 C++ 原型和 64 字节对齐，正式 emitter/默认、RTL、Verilator 不变；
下一步是落入通用宽拼接生成路径并做完整重新生成验证，不继续索引循环调参。

2026-10-04 已追加正式 emitter 验证：[TNO0333 §7.44 增量更新](./TNO0333_repcut_grhsim_backend_20260925.md#增量更新迁入正式-ir-emitter2026-10-04)
新增默认关闭的 `wordwise_wide_concat_bool_pack`，最终范围为 register/latch
状态 bool 字段及同宽纯别名，物化值槽保留原路径，无名字/分区名单。
完整 off/on 7,552 文件审计通过，98 个 compute 文件、1,691 组恰好复现原型；
最终 archive/ELF 与原型逐字节相同，64 字节对齐保留。九项 CTest 与 24 次
正式 C100000、4 次初始化检查通过；新八对相对未打包固定基线 walltime
**−0.960%（8/8）**、Host −0.962%、eval −1.466%。与此前相同 ELF 窗口合计
20 对 walltime −0.960%（20/20）；这是保留收益，不是再叠加约 1% 的优化。
生产默认、RTL 和 Verilator 不变。

2026-10-04 当前瓶颈复核与局部位需求：[TNO0333 §7.45](./TNO0333_repcut_grhsim_backend_20260925.md#745-当前瓶颈复核与按需求计算局部位2026-10-04)
以正式状态 bool pack＋64 对齐为当前线，完成与 Verilator/O3 的四对相邻沿
采样；p18/p10 独立标签两沿仍慢约 32.17%/12.62%，p6/p26/p29 主要是重半周期
集中。新增局部宽右移单 bit 需求原型，统一结构规则覆盖 2218 处，保持快照、
边界与观察者语义；专项及静态身份审计通过，普通 walltime 验证接续记录。

同节已完成闭环：普通两轮共16对，walltime **−0.530%（15/16更快，1对持平）**、
Host −0.521%、eval −1.089%；p6全程平均 −2.300%，独立固定瓶颈步 −2.849%
（4/4）。p29全程平均 +2.084%、update +0.740% 的反向变化完整保留。
原ELF采样改动compute周期 −9.723%、指令 −2.266%，但原周期覆盖仅1.421%；
不能将局部改善外推为整体加速。56次C100000、10次C100及专项通过，保留
通用原型候选与64字节对齐，尚未修改生产emitter/默认、RTL或Verilator。

同节追加正式生成器迁移：新增默认关闭的 `local_shift_demanded_bit`，完整IR
off/on审计7552个文件、17个compute文件2218处替换，与原型archive/ELF逐字节
一致；10项相关CTest通过，64字节对齐保留。普通新8对wall **+0.188%**，
没有复现此前收益；等长路径六轮三方对照，正式版/未优化基线 −0.341%，
但相同ELF的正式文件/原型文件仍 **+0.564%（6/6变慢）**。只读快照显示两份
代码的虚拟映射与NUMA1驻留页数一致，未定位运行差异根因。42次普通、2次
诊断C100000及7次C100通过；保留默认关闭实验选项，不宣称稳定保住0.53%，
不以24对合并趋势覆盖本轮不利窗口，RTL与Verilator不变。

补充同文件重复性校准（TNO0333 §7.46）：同 ELF/inode/路径/目标环境连续
24 次普通 C100000，walltime 中位16.06 s、范围15.96–16.12 s；12对伪AB
中位+0.0625%，单对绝对差异中位0.342%、最大0.931%。独立8次PMU记录
运行态全进程频率3.6015–3.6048 GHz。成功样本全部保留；未将原先6/6
同字节不同文件的方向差异草率归为噪声，继续做固定瓶颈步的后端归因。

同节已完成固定标签两沿归因：p10/p18的G/V eval为+12.77%/+28.35%，
指令仅+0.55%/−6.07%，主要差额在下降沿；前端未供给槽+28%/+49%。
固定区间IP的compute占84%/90%，顶层派发约2.5%/2.4%；下一项收敛到
实际物化窄局部值的生命周期/拼拆，尚未实现或宣称收益。全轮96次有效
C100000、17次C100通过；64对齐与生产默认保持不变，统计、汇编邻域和
身份核验均可由TNO0333 §7.46的链接回查。

2026-10-05 布局与归约表示后续探针：[TNO0333 §7.50](./TNO0333_repcut_grhsim_backend_20260925.md#750-fresh-emitter-固定瓶颈步与代码布局归因2026-10-05)
已完成通用 2 KiB/512 B text 对齐、executable-section bucket 和共同 section
长度控制。统一对齐/bucket 不能消除 p3/p10 的高位入口漂移；共同长度控制把 entry
地址完全对齐后，p3/p10 eval 约为 −0.338%/−1.107%，证明布局是主要退化来源之一，
但 p3 仍有函数内部残余。全量整数掩码归约在固定标签上使 p3 eval/cycles
−1.12%/−1.76%，却使 p10 +1.62%/+1.92%；只改短 OR 链则 p3/p10 +0.72%/+3.63%。
因此不再把简单扇入阈值或对齐粒度作为默认优化，下一步研究保持 batch 内统一向量化
表达形态且限制跨函数布局漂移的通用 emitter 规则；生产默认与 64 B 对齐保持不变。

同日勘误及单变量复测（仍在 TNO0333 §7.50）：上段 −1.12%/+1.62% 等混用了
整段分区均值与固定标签均值，旧“短 OR”候选还改变了 AND/长 OR，不能用于单独
归因；“已证实 p3 内部依赖退化/bool 破坏向量化”的解释撤回。共同长度控制确实
使 6859 个 compute entry 一致，但不固定内部指令和常量布局。2 KiB 的绝对时间
是带探针结果，不能当作同窗口普通 walltime 对照；512 B bucket 实际完成了两对。
完整口径、历史重算及候选身份已追加勘误，不覆盖旧记录。

真正从 fresh 候选只改短 OR 的 8 对普通 C100000，walltime 配对中位 **+0.370%**
（7/8 对更慢），全局 eval +0.755%；4 对固定标签中 p3 eval +1.614%、p10 −0.115%，
动态指令均约不变。186 个重编译对象仅 79 个改变，p3/sched_88 及 p10 全部对象
机器码未变，不支持先前的向量化猜测。本轮 24 次 C100000、6 次 C100 通过，
不晋升该候选；后续回到瓶颈步的实际活跃 batch/指令路径，默认和 64 B 对齐不变。

2026-10-05 活跃批次复核：[TNO0333 §7.51](./TNO0333_repcut_grhsim_backend_20260925.md#751-固定瓶颈活跃批次复核与宽快照延迟物化2026-10-05)
fresh concat 与真实 Verilator/O3 的固定步对照中，p3 已更快；p10/p18 两沿合计
仍慢 12.59%/27.18%，分支更多、IPC 更低，不能只从动态指令数解释。p3 最大活跃
batch 是宽输出打包，但仅占其活跃 compute 约 3.69%；此前短 OR 改写的三项合计
仅约 0.484%。新通用 source oracle 保留宽数组值复制、延迟到首次逐字消费，
命中 21 part/49 文件；8 对普通 C100000 的 walltime 配对中位 −0.495%，7/8 对
更快，全局 eval −0.914%，但 p3 固定标签 eval 仅 −0.140%，并非瓶颈突破。
本轮归因及优化验证合计 62 次 C100000、17 次 C100 通过；保留实验候选，正式
emitter/生产默认/Verilator/64 B 对齐不变，后续聚焦 p10/p18 活跃控制流和两沿成本。

2026-10-05 两沿路径与共同使能：[TNO0333 §7.52](./TNO0333_repcut_grhsim_backend_20260925.md#752-两沿实际路径与共同布尔使能试验2026-10-05)
冻结 late-pack 线的 p10/p18 两沿仍比 V 慢 11.77%/25.55%，差距主要在下降沿；
实际入口计数确认 p18 下降沿全部只有一轮，p10 下降沿重复量也很小，不支持大规模
固定点重跑解释。两版通用共同 bool 使能原型各完成 8 对普通与 4 对 PMU；第一版
walltime 配对中位 −0.313%，第二版 −0.125%（均值比仅 −0.047%）。第二版 p18
全步 eval −1.483%，但固定两沿 +1.701%，没有明确的目标瓶颈/整机收益，均不晋升。
动态值计数发现第二版覆盖的 p18 下降沿每步 711 项输出仅约 2.49 项变化，使能关闭
路径约占 54%、对应旧输出均已为零；后续评估具有严格失效语义的整组不变跳过，
不能凭采样直接删计算。本轮 76 次 C100000、20 次 C100 通过，默认及 64 B 对齐不变。

2026-10-05 当前输出证明的整组跳过：[TNO0333 §7.53](./TNO0333_repcut_grhsim_backend_20260925.md#753-当前值证明的整组不变跳过2026-10-05)
无持久缓存的通用 Zero/Exact 原型均命中 5 part、216 组、2594 项 bool 输出。
各 8 对普通 C100000 的 walltime 配对中位数分别 −0.784%/−0.564%，均 8/8 更快；
4 对直接互比中 Exact 比 Zero 慢 0.284%，4/4 更慢，优先保留较简单的 Zero。
其 p18 普通全步 eval −3.048%，固定两沿 PMU +0.312%；另做无 PMU、复用已有
时间戳的轻量对照，两沿 −1.498%、下降沿 −2.266%、同 binary 全步 −1.770%，
不能仅用瓶颈集合不同解释全部差异，也不能把变化排他归因于 PMU。累计 72 次
C100000、18 次 C100 核验通过；仍是源码原型，下一步正式 IR 规则与 fresh 生成
回归。Verilator、生产默认和 64 B 对齐不变，没有按分区或信号名选择优化对象。

同日正式实现推进：[TNO0333 §7.54](./TNO0333_repcut_grhsim_backend_20260925.md#754-当前全零组保护的正式-emitter-实现与-fresh-验证2026-10-05)
新增默认关闭的 `bool_zero_group_guard`，按 IR 和已确认的内联表达式识别共同状态
使能，不匹配生成代码文本。覆盖直接 AND 与内联 AND 后 Assign，并拒绝把状态
快照当成当前字段。12 配置专项首轮通过，保持 64 B 对齐及其他默认；完整 32 图
fresh 开关审计和普通 AB/BA 正在进行，最终结果继续记录于同节。

同日完成更新：§7.54 的 32 图、7552 源文件 fresh 开关审计及 5 项最终 CTest
通过，正式规则覆盖 234 组/2908 项输出，包含全部旧 216 组。8 对普通 AB/BA 的
walltime 均值 15.88875→15.79000 s（均值之比 −0.622%，配对中位数 −0.723%，
7/8 更快），p18 全步 eval 配对 −2.155%，p3 基本不变。另 4 对与旧 Zero 直比
walltime 配对 −0.534%（3/4 更快），但顺序分组不一致，不能全归因于新增覆盖。
累计 24 次 C100000、6 次 C100 核验通过；正式 IR 规则替代文本原型继续探索，
生产默认保持关闭，未改变 Verilator、all-spin 或 64 B 对齐，全部本轮任务已结束。

2026-10-04 窄局部值实验：[TNO0333 §7.47](./TNO0333_repcut_grhsim_backend_20260925.md#747-显式窄局部值的消费者顺序实验2026-10-04)
已实现纯标量声明区间的通用消费者顺序原型，专项语义/完整构建及首轮
4 对 C100000 Difftest 通过；尚无 walltime 收益结论。正在结合固定步
PMU 检查向量化/栈访问取舍，并试验保留组内原拓扑顺序的小组版本。

同节已完成两版验证：各 8 对普通 AB/BA，逐消费者 wall 配对中位
+0.279%（两组算术均值相同，基本持平），8 项分组 +0.719%，均不保留。
p10/b78 的等机器码 Clang 报告确认 spill/reload 合计 981→3742/4062，
并非单凭源码跨度推断；原有向量化形态被扰动，固定瓶颈步也未改善。
64 次 C100000（32 普通＋32 诊断）、16 次 C100 及 100736 行 PMU
总核验通过；保留原验证线和 64 B 对齐，不改 RTL、Verilator 或生产默认。

2026-10-04 标量拼接按需归约：[TNO0333 §7.48](./TNO0333_repcut_grhsim_backend_20260925.md#748-标量拼接的按需归约2026-10-04)
通用原型在原定义快照直接存归约结果，避免先拼整数再归约；全图命中
28 个 part、2460 个局部值，不重排声明、不叠加上一节候选。专项及完整
构建通过，首窗口 4 对普通 C100000 wall 配对中位 −0.594%；固定步 PMU
与后续普通窗口仍在进行，尚不宣称稳定收益、不改生产默认，保留 64 B 对齐。

同节已完成 4 窗口、16 对普通 C100000：wall 配对中位 −0.752%、配对
变化均值 −0.570%，组均值 15.98625→15.89500 s，13 胜/2 平/1 负，
四窗口及 AB/BA 两种顺序均偏快，保留全图候选供后续对照。p3/p18 的
普通 eval 分别 −1.830%/−1.961%，p10 +1.240%；固定瓶颈标签未显示
p10/p18 稳定改善，p10/b78 spill/reload 981→4257。48 次 C100000、
12 次 C100 及 50368 行 PMU 总核验通过；仍为生成源码原型，尚未迁入
正式 emitter，不改生产默认。下一步聚焦保留向量批量计算的归约表示。

2026-10-05 标量拼接按归约扇入选择整数聚合：[TNO0333 §7.49](./TNO0333_repcut_grhsim_backend_20260925.md#749-按归约扇入选择整数聚合并迁入正式-emitter2026-10-05)
在 §7.48 的全图结构规则上，AND/NAND 改为整数坏位 OR，OR/NOR 改为整数任意置位 OR；混合消费者、XOR、状态/事件值均拒绝，低于 16 字段的 OR 保留原路径。阈值 16 版完成 36 组语义专项、全图 2460 组/393 文件/28 part 覆盖和 16 对 C100000 AB/BA，walltime **−0.596% 中位、−0.736% 均值**（14 胜/2 负），Host −0.628%，全局 eval −0.762%；p10/p18 固定标签未显示稳定改善。p10/b78 的 spills 394→403、reloads 339→332，未复现直接 Boolean 版的严重编译器回退；8/24/32 只作静态敏感性检查。
规则已迁入 `grhsim_cpp.cpp` 的默认关闭 opt-in：`scalar_concat_reduction` 与 `scalar_concat_reduction_min_fields`。补充处理 activity-schedule use-list 的无效 tombstone，只忽略死操作并继续检查所有存活消费者。`emit-grhsim-cpp` CMake 构建通过；fixture 验证默认/显式关闭逐字一致、开启版出现整数聚合，12 组真值 harness 返回 0。尚未打开生产默认或替换 XiangShan 全量生成。

同节追加 **勘误与 fresh 验证**：此前 tombstone 解释不成立，实为临时
`Value` 析构后的 use-list span 生命周期问题；已保活并恢复无效用户拒绝。
也已补齐原型的定义点 bool 快照与短 OR 路径，原型收益不直接归给 emitter；
正在对修订实现做完整 IR 重新生成、回归及 AB/BA，生产默认仍关闭。

该项 fresh 验证现已完成（同节后续增量）：关闭规则的全部 7552 个生成文件与
旧输出逐字一致；开启后覆盖 2584 个快照/416 文件/29 part，包含原型全部
2460 个匹配。全量与 O0/O3 sanitizer 专项通过，404 个 archive 成员变化、
7050 个不变，6859 个 compute 入口保留 64 B 对齐。32 次 C100000 Difftest
及 8 次 C100 检查全部通过。16 对 walltime **−0.437% 配对中位、−0.465%
配对均值**（13 胜/1 平/2 负），全局 eval −0.233%、update −1.135%；p18
全步 eval −2.290%，p3/p10 基本未变。保留通用 opt-in 小优化，不宣称关键路径
已解决、不将 update 计时下降解释为通信量减少；默认仍关闭。下一步回到固定
瓶颈步的 p3/p10 残余计算及 update 间接效应诊断。

同节已完成固定瓶颈步归因：ASLR 已由每次命令的 `setarch -R` 关闭；p3 的
instructions −0.198% 但 cycles/eval 中位 +1.478%/+1.600%，p10 为
−0.045% instructions、+0.716%/+0.729%。fresh text 缩短使 p3/p10 compute
入口中位搬移 −27,264/−60,480 B，虽保留 64B 对齐仍改变更高 cache-set/BTB
位。对 320 个缩短对象补回 172,365 B NOP 的布局控制，在独立 4 对 core PMU
中将 p3/p10 eval 中位变为 +1.112%/−0.178%、cycles +1.125%/−0.255%，
确认代码布局是主要退化来源之一；该 NOP 版本仅作诊断，不晋升默认。下一步
转向不依赖手选分区或编译反馈的通用 backend layout 方案，并以全 32 part
Host walltime 裁决。

2026-10-05 p3 关键路径复核：[TNO0333 §7.55](./TNO0333_repcut_grhsim_backend_20260925.md#755-当前正式线-p3-关键路径复核与状态字段共访问布局试验2026-10-05)
确认 p3 在 3148 个 step 中有 3064 次最后完成，但活跃时间由 141 个 slice/mixed
和 55 个 memory/mixed batch 分散贡献，最大 b46 仅占 2.87%。插桩 PMU 中 GrhSIM
p3 比 Verilator/O3 快约 43%，所以当前方向不是追 branch miss；按静态 batch 共访问
签名重排 p3 状态字段的两组 4 对对照，p3 eval 约 −0.55%，但 8 对 walltime
中位仅 −0.16%、update 约 +0.50%，不进入默认。下一步转向通用窄切片/状态读取后的
变化通知与 activation 物化模式，保持精确语义并用普通 walltime 裁决。

2026-10-06 增量勘误与复核：[TNO0333 §7.57](./TNO0333_repcut_grhsim_backend_20260925.md#757-布尔状态视图后的真实关键路径与活跃热点复核2026-10-06)。
上条“3064/3148 次 p3 最后完成”存在标签选择错误：AB/BA 每对末次运行混入了
Verilator，旧 GrhSIM 原始数据独立重算应为 **1098/3148（34.88%）**；原混合集合
的 batch/PMU 不能作为 GrhSIM 独立瓶颈条件统计。普通 AB/BA 不依赖这些标签，
仍有效。布尔状态视图候选的新发现/独立验证中 p3 分别为 35.71%/35.45%，瓶颈
主要在 p3/p18/p10/p6/p29 轮换。旧 12 对加新 4 对普通 C100000 合计 walltime
配对中位 **−0.784%**，p3 全步 eval **−3.626%**；探针未完全复现普通版收益
分布，条件时间只作诊断。已补充活跃 batch、源码/机器码和测量局限；生产默认
未改变，保留 all-spin 与 64 B 对齐。

2026-10-06 布尔生成/OR 归约融合：[TNO0333 §7.58](./TNO0333_repcut_grhsim_backend_20260925.md#758-布尔结果生成与-or-归约的紧凑循环原型2026-10-06)。
全工程统一识别相同 reader 的连续布尔 AND 输出，将写回、变化检测和后续 OR
汇总放入有序短循环；覆盖 16 文件、90 组、46161 个输出，不按 part/信号或
编译后反馈选择。相对布尔状态视图探索线，8 对普通 C100000 walltime
**−0.631% 配对中位，8/8 更快**，全局 eval −1.386%；p29 全步 eval −7.126%，
原固定瓶颈集合的诊断 eval −5.379%，三个热点 batch 快约 14%/23%/23%。
p28 回退 2.820%，保留为总 walltime 的小幅收益，未手动禁用某个分区。
PMU 合计调用方和共享 helper 后，改写区域指令增加约 61%、cycles 未降，
前端/取指未命中事件减少约 76%/78%；不能把静态代码缩短当成动态工作消失。
32 次长运行及独立 O0/O3 sanitizer 语义检查通过。当前仍是通用 C++ 原型，
正式 emitter 和生产默认未改变。

2026-10-06 短循环索引压缩及正式 emitter：[TNO0333 §7.59](./TNO0333_repcut_grhsim_backend_20260925.md#759-短循环索引压缩逐-worker-归因与正式-emitter2026-10-06)。
先按 worker 补齐共享 helper 的 PMU 归属，确认 p28 的额外循环/索引成本；
连续目标寻址与窄输入偏移使 90 组原型索引载荷下降 64.46%，直接 8 对普通
walltime 配对中位 −0.786%。正式 IR 规则覆盖 17 文件、96 组、49239 输出，
默认关闭，不按 part/信号或编译反馈选择。相对融合前基线，8 对普通 C100000
walltime **−0.312%，6/8 更快**，eval −0.525%；p15/p28/p29 分别改善
10.082%/7.072%/12.667%，p3 回退 1.005%。另与地址压缩原型直接比较，4 对
walltime −0.253%、4/4 更快，保留正式版为探索基线。独立验证中 p29 最后完成
占比约 9.51%→3.12%，同一固定瓶颈集合 eval −13.881%，主要瓶颈转到
p3/p18/p6/p10。关闭选项 7552 个生成文件与原 fresh 基线逐字节一致，14 次
sanitizer 运行、5 项既有回归及 40 次 C100000 均通过；所有慢样本完整纳入。
下一步先复核 p6 活跃 batch 的动态位提取/宽位拼接，继续跟踪 p3。

2026-10-06 宽动态位提取同源缓存：[TNO0333 §7.60](./TNO0333_repcut_grhsim_backend_20260925.md#760-宽动态位提取的同源快照缓存2026-10-06)。
正式 emitter 只在 IR 证明同一物化源于一个 compute supernode 内被读取至少 128 次、
且其物理槽之后没有写入时复制一次；本 workload 仅命中 p6/b184 的 794 次读取，
`.text` 减少 228104→224544 B。两轮共 16 对 C100000 功能全部通过，全局 eval
中位下降 0.482%、分区 eval 总和下降 0.604%，但 walltime 合并中位为 +0.063%，
固定后续代码布局的 8 对诊断中 eval 约 +0.014%、walltime +0.126%，支持自然版
部分 eval 变化来自链接/缓存布局，因此保持 default-off，继续检查输入装载和同步抵消项。

2026-10-06 GrhSIM 输入装载 fanout 并行化：[TNO0333 §7.61](./TNO0333_repcut_grhsim_backend_20260925.md#761-grhsim-输入装载-fanout-并行化2026-10-06)。
生成的 GrhSIM `step()` 现在把互相独立的 `load_step_fns_` 投递到 all-spin worker
pool；Verilator 继续使用原来的 Host-only load 路径。node030 C100000 的 8 对
AB/BA 中，Host −2.426%、walltime −2.439%、`input_load` −48.490%，三项均 8/8
逐对变快，功能签名全部一致；详细构建、边界和 source-cache 对照见 TNO0333 §7.61。

2026-10-07 GrhSIM 宽端口通信跳过未变化块：[TNO0333 §7.62](./TNO0333_repcut_grhsim_backend_20260925.md#762-宽端口通信跳过未变化块update-归因与正式规则2026-10-07)。
定位 global_update 的尾部主要来自复制正文后，默认对全部 GrhSIM 分区间宽端口
按 64 B 比较，只写变化块，保留发送方分组与同步语义。逻辑宽端口写入减少 90.130%；
原型 8 对 walltime −8.988%，正式 helper 4 对 walltime −8.999%、Host −9.039%、
update −26.382%，全部逐对更快。Difftest、扩展宽端口回归和 6 次 ASan/UBSan 通过，
Verilator 生成路径不变，6859 个主 compute 入口保留 64 B 对齐；大包验证为冻结模型的
增量构建，具体口径和局限见正文。

2026-10-07 标量通信原型与残余归因：[TNO0333 §7.63](./TNO0333_repcut_grhsim_backend_20260925.md#763-标量通信保护原型与-p16p20-残余开销2026-10-07)。
以已保留的宽端口规则为基线，p16/p20 的 update cycles 样本中宽比较占约
56%/68%，标量赋值占约 18%/23%。全部 4157 条标量连接统一应用“相等则不写”，
独立计数显示省去 95.399% 赋值、92.756% 逻辑标量写入字节；C100000 Difftest、
8 次小模型 sanitizer 运行与 4157 调用点的优化 IR 检查通过。原型尚未加入默认，
按约定等服务器空闲后做正式 walltime AB/BA，不把本轮诊断时间当作性能收益。

同日已补齐普通性能对照，见 [§7.63 增量更新](./TNO0333_repcut_grhsim_backend_20260925.md#增量更新完成-8-对普通-walltime-abba2026-10-07)：
node030 C100000 共 8 对 AB/BA 全部通过，walltime 15.015→13.695 s，逐对中位
−8.821%、8/8 更快；Host −8.850%、global_update −31.876%，eval −0.481%。
update 占 Host 减少量约 92.33%；p16/p20 平均 update 分别 −26.711%/−55.724%，
p16 仍是平均 update 最长分区。性能证据已补齐，正式 emitter 默认尚未改动。

同日完成[正式生成器落地](./TNO0333_repcut_grhsim_backend_20260925.md#增量更新标量规则迁入正式生成器2026-10-07)：
GrhSIM 分区间标量现默认只写变化值，Verilator 路径保持原实现。扩展五种标量类型
的真实生成回归、两项后端包测试及 8 次 sanitizer 通过；正式 helper 的 4 对
C100000 walltime 15.040→13.780 s、逐对 −8.469%，update −31.510%，均 4/4 更快。

同日完成[宽通信块复用源值](./TNO0333_repcut_grhsim_backend_20260925.md#764-宽通信块复用源值新基线关键路径与正式默认2026-10-07)：
标量新基线 p16 update 的宽比较/复制占 cycles 样本 85.32%；通用规则复用每块
8 个源 word，完整块不再调用比较库函数。原型 4 对 walltime −4.593%，正式
helper 另 4 对 13.730→13.160 s、逐对 −4.375%，均 4/4 更快；正式 update
−20.560%，p16 −25.144%，同时保留 p20 update +9.905% 的局部退化。时空探针
显示 p16 高电平自身 update 17.8846→12.2077 µs，低电平阶段略变慢。规则已纳入
GrhSIM 默认；Difftest、两项 package 回归、sanitizer 与 Verilator 产物一致性
通过。与上一轮使用不同对照窗口，不能相加收益；后续重点回到 eval 关键路径。

2026-10-07 通信优化后的 [eval 关键路径与动态取位实验（§7.65）](./TNO0333_repcut_grhsim_backend_20260925.md#765-通信优化后的-eval-关键路径与动态取位实验2026-10-07)：
独立固定标签与 4 对后端验证确认 p6 瓶颈步 56.303/36.063 µs（G/V），主要在
clock=0；同一步 PMU 显示其分支失误约为 V 的 9 倍。当前两条普通实现线的
4 对 walltime 为 V 23.075 s / G 13.720 s、逐对 −40.542%，其中包含 GrhSIM
专用输入/通信优化，不能解释为纯计算后端差距。安全索引原型 4 对 walltime
+0.585%；紧凑取位循环使 p6 条件 eval −6.577%、b184 −23.060%，但两窗口
8 对 walltime 无稳定收益（4/8 更快），p3/p10 全程均值有退化；两者均未改
正式默认。普通 Difftest、条件 PMU/batch、语义及 sanitizer 检查通过，所有
compute 主入口保留 64 B 对齐。后续候选可考虑取位与最终拼接/归约融合。

2026-10-07 [动态取位与标量拼接融合（§7.66）](./TNO0333_repcut_grhsim_backend_20260925.md#766-动态取位与标量拼接融合2026-10-07)：
全包按纯连续生产者/唯一立即消费者规则匹配 29 组、1856 次取位，省去 bool
数组及再次装载；5 个计算对象的机器码约减半。原 helper 的融合版本及循环内
安全索引版本各完成 4 对 C100000，p6 条件 eval 分别 −7.764%/−7.456%，但
普通 walltime 分别 +0.319%/+0.707%，均不改默认。普通运行 p3/p18 等仍有
退化；p3 的 341 个 compute 入口地址及长度全部不变，不能简单归因于入口
移动或失去对齐。28 次 C100000 Difftest、两种编译器及 sanitizer 差分验证
通过；下一步优先核对普通 ELF 上未改关键分区的退化来源。

2026-10-07 [融合实验中未改分区的普通二进制退化归因（§7.67）](./TNO0333_repcut_grhsim_backend_20260925.md#767-融合实验中未改分区的普通二进制退化归因2026-10-07)：
原 ELF 采样确认 p3 指令数基本持平、cycles 增加约 2%～3%，指令缓存 miss
稳定增加约 10.39%；p10 同项约 +8.72%。恢复布局使普通 p3 相对自然融合版
改善约 1.17%，但 p3 的函数已与基线逐字节相同时，指令缓存 miss 仍约 +10.10%；
单独恢复堆起点也不足以解释主要退化，具体的阶段间缓存触发因素尚未分离。
同一基线/融合 ELF 的三窗口合计 14 对：p6 eval −4.873%、p3 +3.577%、
walltime +0.534%，维持原默认。58 次有效诊断/普通 C100000 Difftest 与输入
身份检查通过；布局控制到此收住，后续优先探索 p3 中跨 batch 的通用代码缩减模式。

2026-10-07 [静态取位写回的通用紧凑循环（§7.68）](./TNO0333_repcut_grhsim_backend_20260925.md#768-静态取位写回的通用紧凑循环代码缩减与执行成本2026-10-07)：
全包按纯连续取位/独立写回/精确通知结构匹配 27 个分区、429 组、19444 次
写入，测试通知掩码和输出位图两版，p3 涉及的 10 个计算对象代码均缩小约 20%。
但两版各 8 对 C100000 普通 AB/BA 的 walltime 分别 +1.105%/+0.801%，
p3 全程平均 eval +2.021%/+2.128%，均不进入默认。条件 PMU 确认实际指令
增加；原 ELF 采样中第一版 p3 指令缓存 miss 仅 −0.816%，被改写块及新 helper
指令约 +30.876%、cycles +9.738%，缓存收益未抵消执行成本。位图版缩小
索引表并消除数据相关分支仍不足以改善 walltime。56 次完整运行全部通过
Difftest，另 14 次初始化检查及两种编译器/sanitizer 语义检查通过，64 B 对齐保留。

2026-10-07 [按宽输入实际读取位过滤初始激活（§7.69）](./TNO0333_repcut_grhsim_backend_20260925.md#769-按宽输入实际读取位过滤初始激活通用原型与两窗口验证2026-10-07)：
通用原型扫描完整计算包，在 32 个分区的 3926 个 head 上缩小 6219 条输入
依赖，保留其他输入/状态/事件激活；全部 compute 对象不变，64 B 对齐保留。
两窗口 8 对 C100000 普通 AB/BA 的 walltime −4.593%（8/8 更快），全局
eval −6.280%，p3/p6 全程平均 eval −16.148%/−10.657%。固定原基线瓶颈步
PMU 中 p3/p6 指令 −20.346%/−16.680%、cycles −17.326%/−12.571%，确认
减少真实执行工作；p10/p18 的条件指令数基本不变。28 次完整 Difftest、8 次
初始化检查及两种编译器/sanitizer 差分通过。原型暂留 build，下一步移入
GrhSIM emitter 并验证正式生成流程；当前仓库默认与 Verilator 路径未改。

2026-10-07 [宽输入按读取位激活移入正式 emitter（§7.70）](./TNO0333_repcut_grhsim_backend_20260925.md#770-宽输入按读取位激活移入正式-emitter2026-10-07)：
新增默认关闭的 `input_bit_activation`，在完整 IR 操作集合上证明固定取位依赖，
覆盖 input/inout，并对副作用、隐含 memory intent 与未证明依赖保守回退。
生成代码不再依赖源码匹配。正式生成、兼容性测试及普通 AB/BA 接续记录于本节。

同节最终结果：7482 个关闭版模型文件逐字节一致，开启版只替换 31 个 eval
对象；覆盖 3924 个 head、6217 条输入依赖，全部 compute 对象与 64 B 对齐
保留。专项 16 个运行构建/524288 次 eval、六项现有回归及 16 次完整
C100000 Difftest 均通过。两窗口 8 对普通 walltime **−4.215%（8/8 更快）**，
全局 eval −4.932%，p3/p6 全程平均 eval −15.565%/−9.392%；约 4.2% 收益
保留。新选项默认关闭，验证线统一开启，后续重采当前候选的瓶颈分布。

2026-10-07 [输入位激活正式版的剩余关键路径（§7.71）](./TNO0333_repcut_grhsim_backend_20260925.md#771-输入位激活正式版的剩余关键路径2026-10-07)：
以 §7.70 正式候选重新做四次独立发现采样；3148 个固定步骤中 p3/p18/p10/
p26/p6/p29 最后完成占比约 21.1%/18.6%/16.2%/12.9%/11.0%/8.2%。增加
最晚与次晚完成者的差值，区分瓶颈频率和可缩短的当前尾部；独立后端对照、
PMU、活跃 batch 与通用候选验证在同节继续追加。

同节已完成独立后端对照：p18/p10 两步合计相对 Verilator 慢 23.04%/6.33%，
p26/p6/p29 两步总时间更短但工作集中在一个半周期。条件 PMU 中 p18 指令少
10.74%，分支/预测失败却多 113.51%/132.23%，应继续看执行效率。活跃源码
确认还有固定多位输入切片，正在以通用 IR 位范围触发规则做候选验证。

同节候选验证完成：固定多位范围扩展覆盖 32 个分区、7943 个 head、15218 条
输入依赖；关闭版 7482 个模型文件一致。两窗口 8 对普通 C100000 walltime
**12.920→12.340 s，配对 −4.176%，8/8 更快**，全局 eval −5.385%；
p3/p6 全程平均 eval −47.409%/−13.693%。固定关键步骤 PMU 指令减少
51.758%/20.814%，证明少做了实际计算。专项、六项回归和普通/PMU Difftest
均通过，保留候选，开关默认状态不变。重采后 p3 最后完成占比降至 5.56%，
p10/p26/p18 约 20.11%/20.08%/19.38%，下一轮优先看 p10/p18 内部热分支。

2026-10-07 [固定范围触发之后的 p10/p18 热分支（§7.72）](./TNO0333_repcut_grhsim_backend_20260925.md#772-固定范围触发之后的-p10p18-热分支2026-10-07)：
以上述固定范围候选和新标签完成 G/V 同一步 PMU、周期/错分支地址对照。
p10 两沿差 +1.71%；p18 两沿 +21.88%，但差额几乎全在下降沿，上升沿约
52.2 µs 两者相当，而 p18 的 610 个瓶颈步中 586 个是上升沿。commit 占
p18 critical 周期样本 13.90%、错分支样本 35.96%，主要周期仍在 compute。
简单布尔选择的通用提示扩展未改变 p18 机器码，八对普通版未确认稳定收益；
保留固定范围基线。56 次正式 C100000 均通过 Difftest。后续优先量化瓶颈
上升沿的大快照实际变化 word 和冗余激活，再评估增量计算规则。

2026-10-07 [瓶颈上升沿的有效变化量与快照增量计算（§7.73）](./TNO0333_repcut_grhsim_backend_20260925.md#773-瓶颈上升沿的有效变化量与快照增量计算2026-10-07)：
两次 C100000 的全部工作量计数完全一致；p10/p18 在瓶颈上升沿重算的拼接
word 仅 4.440%/14.558% 变化，56.383%/50.041% 的活跃纯节点最终持久化
结果不变。p10 两个密集大拼接分别仅 1.838%/1.149% 的 word 变化。正在
验证按输入依赖和当前输出共同核验的通用 word 缓存；简单整字复制不套用。
计数不是可直接跳过的证明，也不是预期 walltime 收益，普通版结果在同节接续。

同节验证完成：实际启用 2893 个 word 缓存；p10 命中率 97.085%，但仅覆盖
13.306% 的拼接 word 检查，p18 覆盖仅 0.186%。八对普通 walltime +1.045%，
仅 2/8 更快，不保留。固定瓶颈步骤中 p10 指令 −5.020%，分支/预测失败却
+11.558%/+16.615%，eval +3.139%，有效频率基本不变，说明省下计算仍被
执行效率损失抵消。28 次正式 Difftest 均通过；继续保留固定范围基线，后续
优先考虑由状态提交沿依赖记录受影响 word，避免消费端反复比较输入。

2026-10-07 [在状态写回时记录受影响的拼接 word（§7.74）](./TNO0333_repcut_grhsim_backend_20260925.md#774-在状态写回时记录受影响的拼接-word2026-10-07)：
全分区按纯状态依赖、持久化槽所有权和写入覆盖筛选 5176 个 word，复用已有
状态变化判断记录 dirty 位图，计算端枚举置位项。两个窗口八对普通 C100000
walltime **−0.694%（8/8 更快）**，p10 全程平均 eval −4.110%，p18 基本不变。
固定 critical 步 p10 指令 −10.828%、cycles −3.442%，有效频率基本不变；
候选范围内 97.476% 的拼接被跳过，涉及 compute/commit 批次计时分别
−37.451%/+1.305%。保留为原型候选，尚未改正式 emitter/默认；33 次完整
Difftest、全分区逐 word 重算校验及两类专项语义检查通过。

2026-10-08 [producer dirty-word 正式 emitter 验证（§7.75）](./TNO0333_repcut_grhsim_backend_20260925.md#775-producer-dirty-word-正式-emitter-验证2026-10-08)：
将规则迁入正式 `grhsim_cpp` emitter，按至少八个独立标量状态字段和持久化槽
所有权逐 word 筛选；模型成员位图、所有状态写回通知和 bank 内
`countr_zero/switch` 消费路径均已实现，选项默认关闭。32 分区覆盖 6623 个
word、453 个 bank；原型 5176 个 word 全部保留，新增 1447 个。全分区逐词
重算、跨 word/部分写入/latch/多实例专项及 Clang/GCC/ASan/UBSan 均通过。
同源 off/on 两窗口共 8 对 C100000 AB/BA 全部 Difftest 通过，walltime 中位数
**−2.229%**，全局 eval −2.544%，最大分区 eval −3.026%；保留正式可选机制，
默认状态不变。

同节追加 bank 动态核查：两次 C100000 的逐 bank 计数完全一致，候选范围内
p3/p10/p18/p24 分别跳过 96.668%/96.987%/60.649%/86.269% 的重算；这不是
全部 eval 工作的跳过比例。bank 数量门槛和简化遍历尚未证明更优，保留已经
验证的无门槛实现，后续优先拆分正式版本的通知成本与剩余计算。

同节完成提交通知与剩余计算归因：固定瓶颈步骤中的 p18 阶段探针约 81.3%
耗时在 compute、15.4% 在 commit；同模型布局消融去掉通知仅减少约 0.10 µs
提交时间、257 条指令。p18 候选 word 在瓶颈步骤仍重算 53.1%，p10 仅 3.1%，
应优先看剩余计算。原普通二进制四对复测 walltime **−2.575%（4/4 更快）**、
p18 全程 eval −4.035%；探针会改变局部时间趋势，其 p18 +3.337% 不能当作
普通版退化。58 次完整 Difftest 与 15 次 smoke 通过，正式实现及默认未改。

同节追加当前 on_v2 与 Verilator 的 p18 同一步地址采样：固定 critical 周期
逐对差 **+0.006%**，相邻集合其余半周期 **+73.013%**，两沿合计 **+22.125%**；
不能将两沿差额当成关键步骤的可缩短比例。critical 的周期地址样本约 80.2%
在 compute、17.4% 在 commit，单个 compute 最多只占 2.4%，热点较分散。
完成 16 次完整 Difftest、4 次 smoke 和源码/机器码一致性核查；未新增可保留
优化，现有验证线与默认不变。后续先重采 on_v2 当前关键路径再选择生成规则。

2026-10-08 [验证线配置勘误与关键路径重采（§7.76）](./TNO0333_repcut_grhsim_backend_20260925.md#776-验证线配置勘误修复与关键路径重采2026-10-08)：
发现正式 dirty-word 的 off_v2/on_v2 错用较早生成配置，漏开已保留的 input-range
activation，并误开未保留的 demanded-bit source cache。已修正驱动、fresh
生成 off_v3/on_v3 并核验增量构建。配置恢复普通 8 对 walltime **−6.226%**，
这是恢复旧优化的收益；正确累计配置内 dirty off/on 另 8 对 **−1.390%**，
两组均 8/8 更快，不与旧配置收益相加。p3 最后完成占比 27.764%→5.337%，
现主要是 p29/p18/p10；独立验证其瓶颈步 eval 为 54.746/47.602/41.515 µs。
59 次完整 Difftest、16 次 smoke 通过，正式生成算法及默认未改。

同节追加通用布尔 helper 四项有序展开候选：全部符合模式的 17 个文件生效，
12 对普通 walltime **−0.255%（10/12）**，三个窗口分别
−0.895%/−0.128%/−0.086%；p29 全程 eval −1.370%（12/12），瓶颈步指令
−3.820%、eval −1.167%。收益小，保留原型，未改正式 emitter/默认。
专项别名/尾部/sanitizer 校验及另 32 次完整 Difftest、8 次 smoke 通过。
[交互 HTML](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_profile_restore_20261008/critical_path.html)
展示修复前后 32 分区占比、固定瓶颈步/两沿 G/V eval、尾差及 PMU，可导出 CSV。

2026-10-08 [p29 布尔循环归因与静态步长寻址（§7.77）](./TNO0333_repcut_grhsim_backend_20260925.md#777-p29-布尔循环归因与静态步长寻址2026-10-08)：
以修复后的 on_v3 为基线，不叠加四项展开。p29 布尔归约 helper 占瓶颈步
周期地址样本约 16.6%；两次独立变化计数一致，瓶颈步约 589 万项输入/输出
均未变，此动态现象不作常量折叠依据。通用静态周期/步长规则把 97.3% 的
连续目标索引项改为直接寻址，自动覆盖 17 个文件、96 组循环，无分区白名单。
两窗口 8 对 C100000 普通 walltime **−2.410%（8/8）**，p29/p28/p15 全程
eval −4.898%/−6.643%/−2.044%；p29 固定瓶颈步 eval −4.005%、指令 −4.734%，
频率基本不变。42 类别名/顺序/尾部 sanitizer 检查和本轮 34 次完整 Difftest、
9 次 smoke 通过。保留原型，未迁入正式 emitter、未改生产默认。

2026-10-08 [布尔归约的分组失效与无分支缓存跳过（§7.78）](./TNO0333_repcut_grhsim_backend_20260925.md#778-布尔归约的分组失效与无分支缓存跳过2026-10-08)：
在 §7.77 静态步长版上，对 96 组循环证明完整输入写入覆盖和独占输出，
复用已有变化汇总，在 1912 个 supernode 边界无分支更新 dirty 位，输入未变
时安全跳过归约。p29 实际跳过 99.038% 调用，逐次重算校验和 sanitizer 通过。
两窗口 8 对普通 walltime **−0.582%（6 对更快、1 对持平）**、全局 eval
−1.152%；p29/p15/p28 全程 eval −9.947%/−7.771%/−4.753%。p29 固定瓶颈步
eval −10.464%、指令 −18.282%，频率基本不变。最终候选 26 次完整 Difftest、
8 次 smoke 通过。保留原型，未改正式 emitter/默认；后续重新采样累计版本
瓶颈分布，不能把本轮增量与上一轮百分比直接相加。

2026-10-08 [静态步长与归约缓存后的瓶颈重采（§7.79）](./TNO0333_repcut_grhsim_backend_20260925.md#779-静态步长与归约缓存后的瓶颈重采2026-10-08)：
当前累计版四次独立发现＋四对 G/V 验证，p18/p26/p10/p29 最后完成占比
21.442%/18.742%/16.010%/12.039%；p26 同一步仍比 V 慢 70.438%，两沿却快
24.291%。周期 IP 与独立阶段计时确认 p26 输入激活准备约 **7.976 µs**、
占该探针 eval 14.925%；生成代码含 9644 个输入掩码项，最长判断 510 项。
下一方向是通用输入激活检查的共享/分组；p18 仍为分散 compute/提交效率。
普通四对 V/G walltime 中位数 21.865/11.845 s，此为累计后端比较，非本轮新
收益。48 次完整 Difftest、13 次 smoke 通过；附同主题交互 HTML，未改生产默认。

2026-10-08 [宽输入激活的分块稀疏检查（§7.80）](./TNO0333_repcut_grhsim_backend_20260925.md#780-宽输入激活的分块稀疏检查2026-10-08)：
根据输入字稀疏度，实现按结构选择的 8 字共享零检查，命中 9 分区/16 输入组，
无模块或信号白名单。八对普通 AB/BA walltime 中位数 11.950→11.855 s，配对
−0.879%，7/8 对更快；固定 p26 瓶颈步准备 8.145→6.075 µs（−25.294%），
整个 eval −2.976%，PMU 指令/周期 −4.781%/−4.344%，频率未升高。
376,704 输入位等价检查及逐次掩码对照通过；相关完整 Difftest 34 次、smoke
10 次通过。保留通用原型，未改正式 emitter/默认；下一方向是剩余 compute。

2026-10-08 [稀疏读取的 packed-array 按需取值（§7.81）](./TNO0333_repcut_grhsim_backend_20260925.md#781-稀疏读取的-packed-array-按需取值2026-10-08)：
根据稳定叶子、完整构造和静态字节/读取成本筛选，4 分区/10 张表改为从源位置
直接取值，无分区或信号白名单。八对 AB/BA 的 walltime **7/8 对更快、配对
中位变化 −0.783%**；两侧平均 12.21375/12.14875 s，平均节省 65 ms（0.532%）。
p26 生产者与消费者合计 3.09672→1.29178 µs，净省 1.805 µs/固定瓶颈步；
瓶颈步 eval −3.985%、指令 −2.196%、周期 −3.518%，两沿合计也下降。
586,872 次 O3/sanitizer 比较及真实模型逐次对照通过；最终候选完整 Difftest
33 次、smoke 9 次通过。保留通用原型，未改正式 emitter/默认及 Verilator 路径。

2026-10-09 [连续 u64 状态布局与纯宽拼接复制（§7.83）](./TNO0333_repcut_grhsim_backend_20260925.md#783-连续-u64-状态布局与纯宽拼接复制通用原型和消融2026-10-09)：
全部分区统一扫描，31 个模型改用连续 u64 槽，18 个分区的 19 处纯拼接改为循环。
保留 64 B 对齐；两窗口八对 C100000 的 walltime **8/8 更快、配对中位变化 −1.611%**，
均值 12.06000→11.89625 s。仅布局消融 −1.322%，其上加循环 −0.210%；p18 最大
平均 eval 基本不变。逐次新旧代码对照 19/19 处执行，约 15.93 亿 word 检查通过；
最终 50 次完整 Difftest、14 次 smoke 通过。保留通用原型，未改默认；基线及非累计
比较范围、局部 batch 收益和退化均见正文。

2026-10-09 [p18 动态路径重采与宽输出存储复用（§7.84）](./TNO0333_repcut_grhsim_backend_20260925.md#784-p18-动态路径重采与宽输出存储复用2026-10-09)：
独立发现后冻结 666 个 p18 瓶颈步，确认 compute 占大头、最大 batch 仅占活跃计算
2.88%。保留通用输出存储复用原型：32 分区/328 个宽输出直接写入最终端口，
消除内部数组到输出的重复复制。两窗口八对 C100000 walltime **8/8 更快，配对
中位变化 −0.851%**，均值 11.83125→11.73125 s；p18 全程 eval −1.860%。
固定标签 tail 1.138→0.206 µs，减少约 0.93 µs；每步输出流双摘要一致。
30 次完整 Difftest、11 次 smoke 通过，保持 64 B 对齐，未改正式 emitter/默认。

2026-10-09 [保留优化的统一累计验证与瓶颈重采（§7.85）](./TNO0333_repcut_grhsim_backend_20260925.md#785-保留优化的统一累计验证与瓶颈重采2026-10-09)：
从 §7.84 最终版本冻结完整源码/头文件，重新叠加此前保留的通用规则。首两层各四对
C100000 均通过，静态步长和归约缓存的增量 walltime 配对中位变化分别 −1.123% /
−1.790%，均 4/4 更快；累计结果另行直接对照，不能相加历史百分比。后续在同节追加。

§7.85 最终更新：保留静态步长、归约缓存、输入分块、按需取值和直接 OR 的 commit
累加子集。两个窗口八组正反序三方测试，累计 walltime **8/8 更快，配对中位
−3.863%**，均值 **11.5375→11.0650 s（−4.095%）**；同窗口 Verilator O3 均值
20.85625 s。全局 eval −5.065%，最大平均分区仅 −1.084%。新冻结步骤显示
p29/p26 单沿仍慢、两沿合计已优于 Verilator；p18 两沿指令较少而周期更多。
追加四对 PMU、逐次组合语义检查和宽输出双摘要；99 次完整 Difftest、27 次 smoke
通过，最终 7,552 个源码/头文件身份核验通过。仍为累计原型，未改生产默认。

2026-10-09 [累计版本 p18 的周期与误预测地址归因（§7.86）](./TNO0333_repcut_grhsim_backend_20260925.md#786-累计版本-p18-的周期与误预测地址归因2026-10-09)：
冻结累计版本的 719 个瓶颈步骤，两种事件各四对 G/V AB/BA。compute 占周期
样本 83.94%，commit 占 13.65% 却占误预测样本 37.53%；最大单个 compute
仅占 2.61%。14 个热函数完成机器码不变的源码映射，确认状态比较、写使能和
变化通知等分散成本。追加四对 pipeline 计数：p18 前端供指不足槽比例
V/G 为 **57.23%/69.33%**，执行后端阻塞为 **3.42%/1.74%**；支持优先查
活跃 compute 的供指/控制流，但尚未分离 I-cache、解码和预测恢复。
共 24 次诊断完整 Difftest、6 次 smoke 通过；保留基线仍为 §7.85 `s5_commit`。

2026-10-09 [累计版本的前端断供与地址翻译分离（§7.87）](./TNO0333_repcut_grhsim_backend_20260925.md#787-累计版本的前端断供与地址翻译分离2026-10-09)：
六组 G/V PMU 确认 p18 差异主要在完全断供，V/G 为 29.32%/45.88%；瓶颈步
指令缓存 miss 总量反而较少，但页表遍历请求 210.79→369.29。完成相同 ELF、
相同虚拟地址的代码大页消融：p18 页表遍历 **370.05→2.66/步**，指令/分支
基本不变，eval 降低约 **4.4%–5.0%**。三个三方窗口大页相对文件页 **12/12
更快、walltime 配对中位 −1.525%**；另四对与不加载辅助库的原始累计程序直接
比较，均值 **11.2175→10.9200 s**，配对中位 **−2.620%**。首窗口一次与自身
审计重叠的偏慢样本完整保留，后两窗口独立复核。共 116 次完整 Difftest、29 次
smoke 通过；保留通用运行候选，未晋升默认，剩余完全断供仍约 43%。

2026-10-09 [代码页大页默认接入与缓存对照（§7.88）](./TNO0333_repcut_grhsim_backend_20260925.md#788-代码页大页默认接入与缓存对照2026-10-09)：
根据 §7.87 的 TLB、walltime 和功能证据，代码页大页已接入 GrhSIM RepCut
wrapper 的启动阶段并默认启用；失败时自动回退原映射，`WOLVI_GRHSIM_CODE_HUGEPAGE=0`
等值可关闭，Verilator 路径不受影响。生成器 CTest、默认启用/显式关闭/回退和
6 MiB 文本段实际映射检查均通过。两对有效 cache AB/BA 显示大页并未减少
I-cache/op-cache miss（p18 约 +2.23%/+0.81%），但 walltime 仍下降，进一步支持
收益来自 ITLB/页表遍历覆盖；节点外部负载导致的后续无效样本不计入统计。

2026-10-09 [通用 hot/cold 文本分裂消融（§7.89）](./TNO0333_repcut_grhsim_backend_20260925.md#789-通用-hotcold-文本分裂消融2026-10-09)：
对 part 18 的全部 schedule 文件统一开启 Clang hot/cold splitting 后，`unlikely`
外层守卫使大部分活跃主体落入 `__llvm_cold`；两对 C100000 的 walltime **+4.149%**、
最大分区 eval **+12.628%**，4/4 功能通过但全部变慢。因此该选项不进入默认，后续
只研究保留活跃主体的细粒度内层布局。

2026-10-09 已在 [§7.89 外层活动提示复核](./TNO0333_repcut_grhsim_backend_20260925.md#外层活动提示的分层复核2026-10-09)
补充两种通用范围的对照：所有外层取消 `unlikely`、仅 event-driven commit 外层
取消提示，各八对 C100000 AB/BA 的 walltime 配对中位变化为 **+0.116%/−0.115%**，
第二窗口的 walltime 变化均为正值。56 次完整 Difftest、16 次 C100 通过，但没有
稳定端到端收益，因此保持现有默认；本轮结束提示/布局变体扩展。

2026-10-09 [p26 残余 compute 与宽位运算融合（§7.90）](./TNO0333_repcut_grhsim_backend_20260925.md#790-p26-残余-compute-归因与纯宽位运算融合2026-10-09)：
固定 357 个历史瓶颈步骤，GrhSIM 88.934% 的周期样本在 compute，热点分散；
独立 batch 探针中最大单批仅占活跃耗时 1.766%。对照 Verilator 按字表达式后，
试验了覆盖 24 分区、288 区域的通用纯宽位运算融合，并修正临时常量数组的
重复构造。72,000 组 sanitizer 差分检查与修正版 30 次 C100000/10 次 C100
通过，但八对普通 walltime 配对中位仅 **−0.033%，4/8 更快**；直接被改写的
b221/b222 持平、b37 退化，局部 PMU 的约 5% 下降不能替代端到端结果。
该规则不晋升默认，保留累计基线与 THP/64 B；下一项转向实际变化比例及精确跳过。

2026-10-09 [宽位区域真实变化与按掩码按需计算（§7.91）](./TNO0333_repcut_grhsim_backend_20260925.md#791-宽位区域的真实变化比例与按掩码按需计算2026-10-09)：
288 个区域两次完整运行的变化计数一致。p26 三段较长选择计算仅 1.55%–3.41%
的调用输入完全未变，结果却有 73.91%–80.19% 未变，原因是选择掩码屏蔽了
候选数据变化；单纯 producer-dirty 缓存机会有限。转测通用的纯掩码选择树
按需计算，任意部分位掩码保留完整语义；专项 112,000 组 sanitizer 差分通过。
完整性能对照与保留决策在同节追加。

同节已补充完整终态：五分区 16 段选择树的八对普通 walltime 配对中位
**+0.501%，仅 2/8 更快**；直接 b221/b222 分别退化 83.045%/52.627%。
p26 动态指令 +2.041%、分支 +16.797%；路径计数显示 99.8898% 的已检查
掩码字为零，沿默认路径几乎走完整条链，只省掉 0.9101% 的节点字，还损失
原有向量处理优势。34 次 C100000/12 次 C100 全部功能通过，但该候选不晋升
默认；维持累计基线，下一候选是保留向量化的整组零掩码检查，尚未验证收益。

补充完成内联修正对照：首版存在 112 个未内联 helper，修正版已全部消除，
额外指令/分支收敛到 +0.671%/+7.584%。但 b221/b222 仍退化
14.922%/13.286%；八对普通 walltime 中位 −0.297%，4/8 更快、两个窗口
方向相反，仍不晋升默认。本节累计 64 次 C100000、22 次 C100 全部功能通过；
结论及“原型实现开销”和“选择策略开销”的区分均已补入同节。

2026-10-10 [整组零掩码快速路径（§7.92）](./TNO0333_repcut_grhsim_backend_20260925.md#792-整组零掩码快速路径2026-10-10)：
通用结构扫描五分区的 16 个纯选择区域，对所有掩码字做一次 OR 归约；仅在
全零时直接求默认结果，非零时保留原数组位运算。128,970 组 sanitizer
差分及两次 C100000 的逐次原表达式校验通过；普通、PMU、batch 和实际
零路径命中率对照在同节继续追加。

同节完整结果已补齐：八对普通 walltime 配对中位 **+0.450%，3/8 更快**，
不晋升默认。p26 两段选择的固定步骤零路径命中 83.901%/82.353%，直接
batch 时间下降 4.076%/1.372%，但整个两批仅占同期活跃 batch 时间 2.761%；
实测节省仅相当于活跃计算的 0.0665%，p26 动态指令仅 −0.145%。32 次
C100000、11 次 C100 和 128970 组差分全部通过；保持累计基线与 THP/64 B。

2026-10-10 [布尔宽掩码的连续扩展（§7.93）](./TNO0333_repcut_grhsim_backend_20260925.md#793-布尔宽掩码的连续扩展与覆盖评估2026-10-10)：
生产端扫描得到 21521 个逐字扩展，4664 个字满足连续 bool/连续目标资格，
形成九分区 323 段；通用改写保留宽数组布局和原激活。511488 组 sanitizer
差分通过。p26 命中三个 batch 此前只占活跃耗时约 1.217%，p10/p18 没有
命中，故不能由静态覆盖推断总收益；完整性能和保留决定在同节追加。

同节已补充首版八对 walltime **−0.526%（5/8 更快、1/8 持平）**，但 p26
动态指令仅少 0.0204%、局部耗时未一致改善。覆盖审计发现首版遗漏无初始化
局部数组声明，已按同一语义资格补全到 25 分区 949 段/12307 字，包含
p10/p18；补全版独立对照继续记录于同节，不混用两版结果。

补全版八对 walltime **+0.442%，3/8 更快**，功能全部通过但不晋升默认。
p10/p18 动态指令 +0.155%/+0.215%。机器码确认短循环已经展开，问题之一
是先扩成 64 位再取负，导致正反掩码重复生成；已开始同资格的“先生成
有符号字节掩码，再宽化”修正验证，详见同节。

三版现已全部完成。修正版八对 walltime 配对中位 **+0.111%，3/8 更快、
1/8 持平**，两个窗口均约 +0.11%；275 个改写文件中 203 个编译对象与
基线逐字节相同，p10/p18/p26 的固定步骤动态指令几乎不变。三版合计
90 次 C100000、30 次 C100 和 2045952 组 sanitizer 差分全部通过，但均
不晋升默认，继续保留累计基线、THP 与 64 B 对齐。后续转向证明并消除
“掩码生成＋选择”的整体代数冗余，同节保留适用条件和结果链接。

2026-10-10 [掩码选择的恒零分支与跨 batch 常量传播（§7.94）](./TNO0333_repcut_grhsim_backend_20260925.md#794-掩码选择的恒零分支与跨-batch-常量传播2026-10-10)：
核实 p10 示例的另一选择臂实际恒零，不满足 `x+cond` 条件。按私有零初始化、
全部写入独立恒零、完整使用分类的通用资格，识别 22 分区/72 槽/614 文件/
2067 处读取；只传播常量读取，保留存储与调度。73728 组 sanitizer 差分及
108 项拒绝检查通过，完整 XiangShan oracle 和两个窗口 AB/BA 在同节追加。

读取传播版已完成 30 次 C100000、10 次 C100，统一匿名 4 KiB 代码页，
八对普通 walltime 配对中位 **+0.0703%**。p10/p18/p26 动态指令仅
−0.4771%/−0.7811%/−0.2044%，尚无总时间收益。继续按同一恒零证明
补齐冗余写入及恒 false 变化检查的消除；与默认 THP 数据分开验证。

同节已补齐完整候选：同一组 72 槽，2067 处读取＋72 处写入消除；八对
walltime 配对中位 **−0.7934%，5/8 更快**，两窗口 −0.0638%/−1.2025%。
两版合计 60 次 C100000、20 次 C100、147456 组差分全通过。完整候选
保留待 THP 可用时复核，暂不加入默认；普通页数据尚不能证明默认大页
配置收益，累计基线与 THP/64 B 保持。

同节已完成同一完整候选的 THP 复核：不重新编译或链接，双方可重映射
代码区均完整大页覆盖。30 次 C100000、10 次 C100 全通过；普通八对
walltime **14.42625→14.24625 s，配对中位 −1.0188%，8/8 更快**，
Host −0.9838%、8/8 更快，两窗口 −1.2464%/−0.8740%。收益在 THP
下复现，完整候选值得进入正式 IR/后端恒量分析；本轮尚未改主线默认，
正式生成后仍需核对一致性与收益，不把生成 C++ 改写或变量白名单直接
作为默认实现。p26 命中 batch 的节省仍仅约占活跃计算的 0.3610%。

随后用完全相同 ELF 做即时 THP 复测：八对普通 walltime
**13.95875→13.86125 s，配对中位 −0.5731%，8/8 更快**，两个窗口
−0.6816%/−0.4658%。绝对 baseline 比上一轮下降约 3.24%，但仍比更早
12.48875 s 高约 11.77%，说明绝对秒数受机器运行状态影响；候选相对收益
只能采用同窗口交错 AB/BA。详见 TNO0333 同节及
[`复测汇总`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/wide_slot_constant_elide_thp_rerun_20261010/summary.json)。

2026-10-10 [恒零证明正式接入 GrhSIM 后端（§7.95）](./TNO0333_repcut_grhsim_backend_20260925.md#795-恒零证明正式接入-grhsim-后端2026-10-10)：将恒零分析放入最终
materialized wide-slot 布局之后，按 IR `ValueId` 递归证明并按槽占用者
收敛，默认关闭、无分区/信号白名单。XiangShan 正式生成识别 92 个恒零宽槽、
9935 个映射项；baseline/candidate 调度统计一致，candidate 用 Clang 23
完整编译，且两者 C=1000 Difftest 烟测通过（8 MiB 栈限制需统一放宽）。
当前只确认正式路径和功能，尚未宣称 walltime 收益；下一步在匹配主线 fixture
上做 THP/Clang23/O3 的 C=100000 AB/BA 后再决定是否默认开启。详见
[`正式后端汇总`](../../build/repcut_grhsim_20260925/active_dispatch_20261003/formal_zero_backend_20261010/summary.json)。

同日又收紧了证明器的 all-ones 宽度传播边界，并用同一 XiangShan post-stats 重新生成：
候选仍为 92 个恒零宽槽/9935 个映射项，调度统计、源文件和 40 处写消除标记与之前
候选完全一致；Clang 23 编译和 C=1000 Difftest 烟测通过。该复核只确认语义边界更保守，
选项继续默认关闭，尚未替代正式 walltime AB/BA。

2026-10-11 [GrhSIM 按 CPU 指令集编译（§7.96）](./TNO0333_repcut_grhsim_backend_20260925.md#796-grhsim-按-cpu-指令集编译同源验证区间-pmu-与默认接入2026-10-11)：
当前累计恒零探索线增加 Clang23 `-march=native`，完整重编通用基线得到与原
archive/ELF 完全相同的结果。完整包两窗口各 4 对 C100000 AB/BA 的 walltime
分别下降 **3.914% / 4.238%**，合并 **14.040→13.475 s，配对 −4.055%，8/8 更快**。
固定 node030 CPU96–127、THP、64 B 对齐；eval 内 PMU 显示 p10/p18/p26 指令数
减少约 19.1%/14.4%/17.4%。已将该参数接入 GrhSIM RepCut 构建默认，可通过
`XS_REPCUT_GRHSIM_MARCH=` 回退通用目标；Verilator 仅作对照。前节追加勘误，
不再将含 all-spin 的全进程 PMU 比值直接解释为模型工作量比值。

2026-10-11 [Native 残余关键路径重采（§7.97）](./TNO0333_repcut_grhsim_backend_20260925.md#797-native-版本的残余关键路径重采2026-10-11)：
在当前完整包 native 基线上重新冻结瓶颈步骤。p18 占 3148 个采样步的 22.046%，
瓶颈时 eval 平均 52.506 µs；固定这些步骤的周期样本中 compute 占 83.374%，
模型内部 commit 占 12.469%，后者占误预测样本 38.422%。13 个热函数通过
机器码不变的行号映射核验，12 次 C100000 Difftest 和 3 次 C100 烟测通过；
完整 32 分区条件数据及采样驱动已链接，后续收益继续采用新一轮 AB/BA。

2026-10-11 [Compute 共享变化条件（§7.98）](./TNO0333_repcut_grhsim_backend_20260925.md#798-compute-共享变化条件通用原型与-native-双窗口验证2026-10-11)：
按共同通知组复用 Boolean 变化归约，统一覆盖全部 32 个分区。两窗口共 16 对
新跑 AB/BA 的 walltime 均值 12.5325→12.4838 s（−0.389%），配对中位数
−0.641%；p18 固定瓶颈步骤指令/周期分别 −1.232%/−0.860%。全局 update
约 +1.490%，暂保留为候选、默认不变。40 次 C100000、6 次 C100 及
1048576 次 sanitizer 对照检查通过，原始数据及复现脚本已链接。

同节已追加 update 归因与堆地址对照：全部 32 个 update 正常路径机器码和入口
相同，动态指令基本不变，未见数据填充系统性增加。新八对普通 AB/BA 的
walltime 均值 **12.8625→12.7575 s（−0.816%）**，四个 ABBA 块均改善；
update 均值 +0.364%，未稳定复现此前 +1.490%。单独恢复候选堆起点后，
新四对 A/H 的 walltime 仍改善 **0.572%**，update 均值仍 +0.678%，不能
将全部抵消归因于堆地址。新增 56 次 C100000、14 次 C100 均通过；候选保留，
不加入地址填充、不改默认，具体微架构原因尚未确定。

2026-10-11 [共享变化归约正式接入（§7.99）](./TNO0333_repcut_grhsim_backend_20260925.md#799-共享变化归约接入正式-grhsim-emitter2026-10-11)：
已增加结构化 emitter 选项与 CTest，四项 focused 测试通过；新增测试覆盖
14 个执行配置、57344 次 eval 及 sanitizer。关闭版本 7549 个源码/头文件与
原快照一致；本轮冻结既有 wrapper/保留优化，单独验证正式 emitter 差量，
不混入旧 wrapper 的配置差异，生产默认暂不改变。

同节已完成完整接入与新跑对照：32 分区共 17101 个共享组，选中来源的源码
OR 累计 399759→212573，模型可执行节 −0.845%；增量重编/链接 128.131 s。
A/F 八对的 walltime 均值 **12.1425→12.0775 s（−0.535%）**，四个 ABBA
块均改善；eval −0.726%、update +0.334%。另对原型 B/F 新跑四对，walltime
**12.0325→11.9550 s（−0.644%）**，两块均改善。24 次 C100000、4 次 C100
均通过；仍有顺序效应，按小幅收益表述。接受正式版 F 为同一保留优化验证线
的后续控制基线，生产默认仍关闭；所有后续比较继续重新运行双方 AB/BA。

2026-10-12 [通信变化复用与旧快照精简（§7.100–7.101）](./TNO0333_repcut_grhsim_backend_20260925.md#7101-复用通信变化信息并精简输入旧快照2026-10-12)：
先纠正仅按 eval guard 缩减输入依赖的安全问题，再用通信层完整变化标记驱动
eval。统一规则覆盖 22 个分区、78 个宽输入，其中 27 个旧快照由 25531 缩到
1163 word；当前输入和 schedule 计算保持完整。两轮各自新跑四对、八对
C100000 AB/BA，walltime 均值分别改善 **1.581% / 2.440%**，合计 12/12 对
改善，不能相加。八对窗口 p24 eval **21.519→15.5095 µs（−27.926%）**，
p18 基本不变；24 次 C100000 Difftest 及额外逐输入一致性检查通过。
已接入正式 emitter 的 `input_dirty_tracking` 开关（默认关闭），完成输入别名、
普通/跟踪模式切换、重新初始化等保护和三项 CTest。正式生成关闭时模型/adapter
与既有版本逐字节一致，开启后选择范围和快照下标与原型一致；重编 5396 个源文件，
compute/commit 调度对象代码未改变。正式候选 **G** 另行新跑四对、八对 AB/BA，
walltime 均值分别改善 **1.883% / 3.540%**，正式两轮 11/12 对、6/6 个 ABBA 块
改善。正式八对窗口 p24 eval **24.07075→17.140625 µs（−28.791%）**，p18
基本不变；另 24 次 C100000 Difftest、4 次 C100 通过。保留 G 为后续完整优化
验证线的控制版本，每轮仍重新运行双方，不能复用历史控制时间或累加窗口收益。

源码提交归档（2026-10-12）：Wolvrix `7c05d67` 保存累计 GrhSIM RepCut 实现，
前置的内存选择和成本模型分别提交；XiangShan `c35b27d77`、Difftest `5b7a09635`
同步编译适配。当前源码的 39 项 Python/流程测试与补跑的 4 项 CTest 全部通过，
具体提交范围见 TNO0333 §7.101 末尾。

2026-10-13 [最新 GrhSIM F/G 交互时空图](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_input_bridge_20261012/formal/timeline_8pairs/grhsim_f_g_timeline.html)：
复用 TNO0333 §7.101 正式八对窗口，不新增或混入其他性能样本。支持 32 线程的
阶段重建、均值/中位数、逐对样本、分区指标选择和 CSV/SVG 导出，附 PNG。
当前 input-load 按实际并行实现绘制；灰色不表示实测等待。数据与 83 组浏览器
交互检查通过，细节追加于该节末尾。

2026-10-13 [逐 cycle 分区耗时 HTML](../../build/repcut_grhsim_20260925/active_dispatch_20261003/dirty_input_bridge_20261012/formal/cycle_trace_20261013/viewer/grhsim_cycle_histogram.html)：
另采 F/G 两对 C100000 AB/BA，支持 cycle 1–100001、两种时钟沿或两沿合计、
指标选择、独立运行切换和 CSV/SVG 导出。仅用 node030 CPU96–127；本批为
**4 KiB 代码页诊断数据，不能与此前 THP 平均图直接比较绝对耗时**。完整 HTML
约 158 MB，离线分块解压；396 项累计值核对和 129 组浏览器检查通过，见
TNO0333 §7.101 末尾的增量说明。

2026-10-12 [GrhSIM 旧单线程流程复测（TNO0335）](./TNO0335_xiangshan_grhsim_single_thread_old_flow_20261012.md)：
在 node032 CPU0--7 上对旧单模型流程完成 C=100000 的 ABBA/BAAB。通用
`packed_array_late_index + local_compute_use_order` 候选的最终静态库与 baseline
逐字节相同，四对 Host 均值 `116603.0→117570.5 ms`（`+0.8297%`）；
`memory-write-coalesce` 使静态库约 `-0.587%`，但 Host `119520.25→119859.25 ms`
（`+0.2836%`）。两项均不进入旧单线程默认。

2026-10-15 [有向 sender/receiver proposal 探针（TNO0337 §27）](./TNO0337_grhsim_partition_system_redesign_20261013.md#27-有向-senderreceiver-proposal-的首个闭环2026-10-15)：
在 raw assignment 通过首道 gate 后，按真实 writer/reader 集合做受硬约束的宽值消费者
proposal。首个单 ASC proposal 完成 partition rebuild 和 backend 对账，receiver bytes
峰值约降 `0.15%`，低于进入编译/runtime 的 `0.5%` 停止线，暂不生成代码；sender 和
receiver 方向已经独立于无向超图权重，后续继续做成组/交换搜索。

同节已追加 §27.1：接收热点约 98.91% 的成员位宽来自不超过 64 bit 的值，旧探针遗漏了
这些值拼成的大包。修正后确认多个独立 ASC 可以重新放置；其中本轮选中的两个是受 dump
条件控制的性能日志输出。因此计算成本与边界通信必须分开评价，接收峰值降低仍需真实
walltime 验证。

§27.2 另已校正旧静态报告的生成选项差异，并补充同配置机制对照；第 24 节原有 fresh
AB/BA 的两边生成配置一致，运行时间数据仍有效。

§27.3 已完成全位宽 reader 分组候选的 8 对 fresh AB/BA：相对同配置从头划分参考，
Host 逐对中位数 −0.952%（7/8 胜出），全局 eval −0.629%，update −1.451%；功能和 THP
检查通过。收益小且仍有顺序差异，暂不改默认，下一步回到初始分配的联合目标。

2026-10-15 [两阶段从头分配与 fresh AB/BA（TNO0337 §28）](./TNO0337_grhsim_partition_system_redesign_20261013.md#28-从初始分配处理终端-reader2026-10-15)：
核心 ASC 从原始图重新求解，34 个通信需求占主导的终端消费者随后按精确 writer/reader
成本做初始放置，未复用旧 assignment 标签。相对上一轮候选，接收容量峰值 −74.55%、
通信总容量 −10.23%；node030 CPU96–127、C100000 的 8 对 fresh AB/BA 中，Host 配对
中位数 −5.55%、elapsed −5.53%、eval −2.65%、update −22.32%，均为 8/8 更快。
最大平均 eval 未改善，input-apply 总和增加，保留局部代价。另确认旧静态 gate 会因
operand bits 和派生事件条件上界拒绝实际有益候选；本轮保留原判定，并明确以有界诊断
完成性能核验。保留新实验候选，生产默认与 Verilator 不变，后续优先构造器接口化和
核心初始计算/写回均衡；完整证据与规划集中在同节。

2026-10-15 同主题已追加 [生产入口接入与回归（TNO0337 §28.4）](./TNO0337_grhsim_partition_system_redesign_20261013.md#284-生产入口接入配置边界与回归2026-10-15)：
两阶段从头分配已成为独立 GrhSIM 构造器，支持 CLI、Python、脚本和 Make，预算由当前
输入的参考方案推导，失败时回退。完整香山最终标签及优化后图与已测候选逐字节一致；
小图生产入口、精确核算及参数/后端路由回归通过，并修正最终权重统计仍指向参考分配的
问题。通用构建默认保留，当前优化线显式使用新构造器；文档说明了 reg-to-mem 等生成
配置与普通默认入口的差异，以及后续核心计算/写回均衡的节奏。

2026-10-15 补充新初解的两次完整 cycle trace、低频采样及划分前结构代理诊断：p24 两沿
均重，p14 偏上升沿，p4 的计算集中于下降沿，最长时长累加在两次运行中均排第一。
原始 GRH 的标量计算及潜在存储 site 数与平均 eval 的相关系数在两份分法中为
0.632/0.595，高于原 closure 的 0.318/0.221；同时明确 may 上界与实际半周期工作之间的
差别。证据、限制及后续初始核心分配节奏见 TNO0337 第 28.5 节。

2026-10-15 同主题追加 [场景/标量驱动的核心初解（TNO0337 §28.6）](./TNO0337_grhsim_partition_system_redesign_20261013.md#286-划分前场景与标量特征驱动的核心初解2026-10-15)：
实现调用方声明的划分前事件/commit 可见性分析，以显式 unknown 保留派生事件边界；
独立核心初解增加标量投影和 writer/reader value 超边。与当前最佳 binary 的 8 对
fresh AB/BA 中，Host 12.8465→12.2575 s，配对中位数 −4.59%，8/8 更快；全局
eval/update 分别 −5.09%/−10.10%，通信调用条目 −32.44%、存储 byte −10.07%。
功能、THP、身份及单元/ASan/UBSan 核验通过。相关性尚未全面提高，组合收益仍需
机制消融；保留为实验候选，生产默认和 Verilator 路线未切换。

2026-10-15 同主题追加 [两项机制消融（TNO0337 §28.7）](./TNO0337_grhsim_partition_system_redesign_20261013.md#287-标量投影与-value-超边的移除消融2026-10-15)：
各做 8 对 fresh AB/BA，移除 value 超边/标量投影分别使 Host 配对中位数退化
1.88%/4.63%，完整方案均 8/8 更快，继续保留组合。两种移除的主要退化都在框架
update 推送：分别 +41.87%/+44.79%，eval 则 −2.67%/+0.58%。96 个发送函数的
实际复制调用与精确模型逐项一致；明确 update-push 不含模型 commit，静态 byte
总量仍不能解释动态推送成本。36 次功能/THP 核验通过；仅投影为原端点预算之外的
诊断对照，预算和放置规则未放宽。补充原始库存审计、相关性边界和有限后续节奏。

2026-10-15 同主题追加 [动态通信与缓存域对照（TNO0337 §28.8）](./TNO0337_grhsim_partition_system_redesign_20261013.md#288-动态推送缓存域与一次固定模型的映射对照2026-10-15)：
完成三组 12 次 wrapper-only C100000 诊断与原始 ELF 的四次 PMU 核查；仅超边组
复制 payload 总量 +8.40%，发往不同 L3 域的实际复制 payload 却 +144.09%，逐步
最慢 sender 增量占 trace 全局 update 增量约 89.52%。进一步只按静态通信矩阵改变
冻结消融模型的核映射，同一个 ELF 的 4 对 fresh AB/BA 中 Host 配对 −2.191%、
update −15.238%，均 4/4 更快，确认物理映射的实际影响；不将其混为新的划分收益。
补充共享行/采样边界、64 B 复制生成热点及下一阶段库存投影与拓扑分层计划。

2026-10-15 同主题追加 [纯标量库存投影对照（TNO0337 §28.9）](./TNO0337_grhsim_partition_system_redesign_20261013.md#289-用纯标量库存替换场景投影的单变量对照2026-10-15)：
完整方案的 assignment/特征/精确 parts 与 transfers 四份重放逐字节一致；只将求解器
投影由两沿/unknown 组合换为 scalar-site 库存，保留相同场景验收。4,061 个核心节点
权重改变（1.35%），候选通过原预算并完成重建，通信存储量 −4.44%、条目 +3.23%。
记录同原绑核下的静态跨 L3 payload 及实验边界，后续以 8 对 fresh AB/BA 验证。

同轮运行验收已完成：Host 11.3420→10.9935 s，八对配对中位数 **−3.032%**，
eval/update 分别 −2.879%/−8.119%，均 8/8 改善；18 次功能/THP/配置及身份核验通过。
纯库存作为下一轮实验对照保留，生产默认未切换。补充实际核心投影与精确并集的
不同口径：投影/eval 的 Pearson 0.407→0.354，改善 walltime 尚不等于成本预测更准。
记录后续接口化及显式拓扑分层计划，场景验收仍保留，不开展比例或 seed 扫描。

2026-10-15 同主题追加 [资源层接口化与缓存域映射反例（TNO0337 §28.10）](./TNO0337_grhsim_partition_system_redesign_20261013.md#2810-将资源层接口化并验证缓存域映射约束2026-10-15)：
将结构特征、求解器投影、精确通信、场景约束和 CPU/L3/NUMA 资源拆成独立只读接口。
静态跨 L3 payload 由 81,150 降到 79,438 byte，但只改启动绑核映射的 8 对 fresh
AB/BA 中，Host 仅 −0.456%（5/8），最大分区 update-push **+3.401%（0/8）**，
update 总和 **+2.651%（0/8）**，不作为下一轮 baseline。定位到 `PhaseWorker` 的
64 B lane 元数据和连续 lane block 被拆跨 L3；后续资源目标必须先满足框架同步元数据
局部性，再优化 RTL 通信，生产默认与 Verilator 路线均不变。

2026-10-16 同主题追加 [动态 K/L3 层次化初始分配契约（TNO0337 §28.11）](./TNO0337_grhsim_partition_system_redesign_20261013.md#2811-按运行时-k-与实际-l3-域生成层次化初始分配契约2026-10-16)：
用实际 `lscpu` 拓扑和输入 assignment 推导域数与每域容量，当前 node030 自然得到
`[8,8,8,8]`；K=1/2/3/6/8/12/31/32/40 的容量推导验算通过。完整超图 K 路求解后
再按域容量编号 L3 槽位，动态结构门槛、精确 assignment 重放和 `partitioned.json` 生成均通过；
send bytes 相对场景初始候选 −2.38%，尚未进行运行时 AB/BA，不宣称 walltime 收益。

2026-10-16 同主题追加 [同一 ELF 的 CPU 映射复测与勘误（TNO0337 §28.12）](./TNO0337_grhsim_partition_system_redesign_20261013.md#2812-勘误固定同一-elf-单独验证-cpu-映射2026-10-16)：
两边使用同一 ELF、同一分区与 Host p9/CPU105，只在启动时切换 CPU 映射；
node030 CPU96–127 上 8 对 fresh C100000 AB/BA，18 次功能/配置/THP 核验通过。
Host 逐对变化中位数 +0.004%，双方各快 4 次，未发现稳定收益。撤回此前由
`alignas(64)` 推导八 lane 必须同 L3 的硬约束；核实层次化候选另有 11 个 terminal
ASC 放置变化，不能将其性能变化归因为纯线程映射或代码/缓存布局被破坏。

2026-10-16 同主题追加 [层次化初始分配修正与最佳候选重放（TNO0337 §28.13）](./TNO0337_grhsim_partition_system_redesign_20261013.md#2813-层次化初始分配的修正与最佳候选重放2026-10-16)：
修正等价线程容量、terminal reader 排序和严格路径投影差异，两边统一最佳纯库存
投影与求解选项。通用小图核验通过；关闭层次化时，节点权重、核心与完整 assignment、
特征、精确 parts/transfers 六份输出逐字节重放最佳候选，随后开始独立递归候选闭环。

同节已追加最终闭环：进一步修正超重大 ASC 抬高所有线程上限及两级 imbalance
叠加的问题，普通投影上限统一为 830,442；原 recurring 总量门槛仍超出 0.57%，
明确标为诊断候选，不改变原 gate。node030 CPU96–127 上 8 对 fresh C100000
AB/BA 的 elapsed 中位数 11.925→13.050 s，逐对变化中位数 +9.22%，8/8 对更慢；
eval +7.72%、update +36.91%。独立逐步诊断将主要尾部定位到 clock=0 eval 与
clock=1 的 p21 update-push，常见启动偏移低于 1 µs；不能归因为纯线程映射。
保留最佳纯库存候选，下一阶段优先考虑半周期计算负载、共享复制和定向传输成本，
L3 拓扑作为通信软目标；未改变生产默认或 Verilator 路线。

2026-10-16 同主题追加 [全局小组划分与集合成本装箱（TNO0337 §28.14）](./TNO0337_grhsim_partition_system_redesign_20261013.md#2814-全局小组划分与集合成本装箱2026-10-16进行中)：
计划从头生成 `4*K` 个逻辑小组，再按分阶段计算、共享并集和定向 bundle 代价装入
K 个线程；L3 是通信软目标。通用小图及互补半周期装箱测试通过，完整设计闭环进行中。

同节已追加首个完整闭环：128 个逻辑小组装入 32 线程，集合/通信完整对账及 ASan/UBSan
通过；原成本 gate 保留拒绝，候选明确按诊断版本验证。node030 CPU96–127 上
8 对 fresh C100000 AB/BA，elapsed 中位数 11.740→12.540 s，逐对变化中位数
+6.56%，8/8 对更慢；eval +2.92%、update +49.25%。独立两对诊断表明 clock=1
eval 的改善被 clock=0 抵消，约 64% 的 step 时间增量来自 update；候选 p0 的
clock=1 收尾 callback 达 9.30 µs，启动时差约 0.013 µs。静态 helper 条目
2397→6491，新增条目约 81.3% 是窄包，符合推送碎片化的退化方向。
另确认 28,186 个值在 writer 放置前已有多个 reader 线程，当前部分 assignment
忽略了非零通信下界；下一步修正这一通用前瞻成本。保留最佳纯库存版本，默认与
Verilator 路线不变。候选总构建 300.21 s，正式与诊断共 24 次功能/配置/THP 检查通过。

2026-10-16 同主题追加 [writer 未放置时的远端需求前瞻（TNO0337 §28.15）](./TNO0337_grhsim_partition_system_redesign_20261013.md#2815-writer-未放置时的远端需求前瞻2026-10-16进行中)：
实现 reader 已分散时的远端 bit 下界和合包后 helper 预测；逐次部分 assignment
重建、小图及完整精确核验通过。仅加前瞻仍因“复制绝对优先”退化成原分区的线程
编号置换，现继续以有限归一化势能联合考虑复制、阶段负载和通信，开展完整 fresh
AB/BA 闭环；原成本 gate 独立保留，生产默认及 Verilator 路线不变。

同节已追加完整结果：有限联合成本＋前瞻将旧装箱静态 helper 从 6,491 降至 4,504，
payload 从 422,319 降至 381,179 byte；但在 node030 CPU96–127 上 8 对 fresh
C100000 AB/BA，elapsed 中位数 11.580→12.935 s，逐对中位数 +11.66%，8/8 对
更慢，eval +9.79%、update +38.72%。独立两对诊断定位到 clock=0 p31 eval
（收尾时 62.98 µs）及 clock=1 p26 update（7.50 µs）；约 69% 的 step 增量来自
eval。正式与诊断共 24 次功能/配置/身份/完整代码 THP 核验通过。保留最佳纯库存；
下一步先建模后端活动组、分阶段成本和共激活，再贯穿初始分组与装箱，不再只调
当前原始计数势能。静态消融、计量边界与全部可复核数据已记录到同节。

2026-10-16 同主题追加 [后端活动上下文贯穿初始构造（TNO0337 §28.16）](./TNO0337_grhsim_partition_system_redesign_20261013.md#2816-后端活动上下文贯穿初始构造2026-10-16进行中)：
用后端 compute context、共享提交体与成员活动来源重新构造初始小组，再用于最终
装箱；不复用旧库存小组、不用时间拟合或编译后反馈。已记录六类原语、消费者归属、
共享体计数、共激活片段及预测边界，按小图/守恒→完整生成→fresh AB/BA 推进。

2026-10-16 同主题追加 [后端活动上下文完整闭环（TNO0337 §28.16）](./TNO0337_grhsim_partition_system_redesign_20261013.md#2816-后端活动上下文贯穿初始构造2026-10-16进行中)：
全量提取守恒并通过覆盖审计，后端上下文同时用于初始超图和最终装箱；但候选在
node030 CPU96–127 的 8 对 fresh C100000 AB/BA 中 Host 11.952→14.5945 s、
elapsed 12.025→14.665 s（+21.95%），最大 eval +58.01%、update-push +36.04%。
主要问题是新小组造成跨 L3/接收 payload 膨胀并把工作集中到新的尾部，原 gate 拒绝，
保留基线；下一步先补分区边界到达与 fixed-point 语义。

2026-10-16 同主题追加 [边界到达与本地提交后执行波（TNO0337 §28.17）](./TNO0337_grhsim_partition_system_redesign_20261013.md#2817-将边界到达与本地提交后执行波纳入初始构造2026-10-16)：
在来源中保留 writer ASC，随分配区分远端下一半步输入与本地提交后的再次计算，
并用于重新构造初始小组与装箱。小图和独立增量 oracle 已通过，开始全量提取及
fresh AB/BA；同时补充上一轮预算分母、跨划分 part 编号和通信净增口径的勘误。

2026-10-16 同主题追加 [到达阶段候选完整闭环（TNO0337 §28.17）](./TNO0337_grhsim_partition_system_redesign_20261013.md#2817-将边界到达与本地提交后执行波纳入初始构造2026-10-16)：
完成新图、119 小组、完整生成及 node030 CPU96–127 的 8 对 fresh C100000 AB/BA。
elapsed 12.245→17.895 s，逐对中位 +46.32%，8/8 退化；额外 step 时间 90.28%
来自 eval。两对独立诊断定位上升沿 p10 尾部（82.78%，96.29 µs）。同 assignment
消融验证标量阶段相关性改善，但宽字成本仍严重失真，综合投影相关性仅 0.109；
全部 24 次运行/配置/完整代码 THP 检查通过。保留最佳基线，下一步先对账原始预测、
通用变换后图和实际后端执行计划的成本差异，再形成新候选。

2026-10-16 同主题追加 [全分区计量修正及新划分验证（TNO0337 §28.18）](./TNO0337_grhsim_partition_system_redesign_20261013.md#2818-全分区成本对账先修正原语计量再评价划分目标)：
完成两套划分共 64 分区的通用 pass/最终 execution-plan 对账，修复窄切片按宽输入
收费、`grhsim_` 变量被误判为 helper 导致普通表达式漏计两项问题；回归与生成包
20 文件 byte identity 通过。使用相同 allocator、修正库存重新从头分配 120 小组，
node030 CPU96–127 上完成 8 对 fresh C100000 AB/BA 和两对独立诊断：elapsed
11.175→14.650 s，逐对中位 +32.12%，0/8 获胜；额外 step 时间 92.07% 来自 eval。
新候选上升沿 p20 尾部占 85.69%，模型也预测其标量峰值比基线高 9.99%，暴露
阶段峰值目标/初始小组放置及“可能活动→真实工作”的剩余缺口。保留计量修复和
最佳基线，不采用新划分；下一步优先核对上述缺口，不按分区调系数。

2026-10-16 同主题追加 [放置目标与真实活动量归因（TNO0337 §28.19）](./TNO0337_grhsim_partition_system_redesign_20261013.md#2819-放置目标与真实活动量分开归因再验证峰值优先初解)：
重放全部 120 次放置，确认旧目标会为复制/通信取舍接受更高的阶段峰值；旧候选
p20 来自四个可移动小组。全分区真实逻辑组计数复现一致，进入库存与未插桩 eval
的相关性为 0.867～0.967，明显高于静态可能库存。峰值优先方案从头重建并完成
node030 CPU96–127 的完整验证：相对旧目标 fresh 4 对 walltime −6.91%，4/4
获胜；相对最佳基线 fresh 8 对 +22.48%，0/8 获胜，保留最佳基线。新候选的
上升沿 eval 尾部仍为 p20，update 尾部集中到 p27；40 次仿真运行通过功能和完整
代码 THP 检查。下一步优先核对静态触发/到达沿/条件体，并配套约束通信端峰值。

2026-10-16 同主题追加 [静态触发来源审计与通信预算保护（TNO0337 §28.20）](./TNO0337_grhsim_partition_system_redesign_20261013.md#2820-静态触发来源审计与通信预算保护2026-10-16)：
对账全部 32 分区计划与 41 个活动过估反例，追到附加异步 reset、门控时钟及远端
到达阶段；通用事件极性原型收紧 918 个 compute group，下降沿已知库存/eval
相关性 0.296→0.353，但含 unknown 的可能库存相关性不变。通信超限优先候选从头
构造并完成 node030 CPU96–127 上 34 次功能/完整 THP 验证：相对最佳基线 fresh
八对 walltime +31.64%；相对上轮峰值优先 fresh 四对 update −11.59%、eval
+10.46%、walltime +7.23%。保留最佳基线和静态分析原型，下一步将触发原因与到达
阶段接入原始成本表示，继续避免按观测频率、模块名或分区编号调权。

2026-10-17 同主题追加 [原始图触发原因分解与新划分验证（TNO0337 §28.21）](./TNO0337_grhsim_partition_system_redesign_20261013.md#2821-原始图触发原因分解与从头构造验证2026-10-17)：
将事件极性和正常时钟/控制风险分解接入原始提取，438,676 个原因及来源归属通过
对账，ASC 模型与原语库存逐字节不变。新划分完成 node030 CPU96–127 上 34 次
功能/完整 THP 验证：相对最佳版本 fresh 八对 walltime 12.255→14.775 s，逐对
+20.56%；相对上轮峰值优先 fresh 四对 −1.86%，eval −3.58%、update +10.70%。
同划分同采样的相关性呈混合结果：最佳基线下降沿 0.369→0.531，候选上升沿
0.716→0.803，另外两项未改善。继续保留最佳版本；下一步优先检查初始微分组/
放置造成的通信集中与可行性，保持模型误差的独立检查，不继续只换目标排序。

2026-10-17 同主题追加 [通信集中与初始构造可行性（TNO0337 §28.22）](./TNO0337_grhsim_partition_system_redesign_20261013.md#2822-通信集中与初始构造可行性2026-10-17)：
确认上轮 p4 的通信集中主要来自一个含 4,439 ASC 的微分组；对该组整体搬迁，
满足投影容量时最大发送调用只能从 1,038 降到 1,019，不能解决问题。
完成“冻结后端负载投影＋原始复制/连接切边目标”的直接 K 路候选，最大发送调用
降为 237，通信/复制预算通过，旧两项场景上限仍未通过。node030 CPU96–127 上
34 次功能/完整 THP 验证通过：相对最佳 fresh 八对 walltime 11.85→13.98 s
（逐对 +17.68%）；相对上轮微分组候选 fresh 四对 14.61→14.07 s（−3.49%），
update −33.56%、各分区 eval 之和 −14.09%，但全局 eval +0.55%。
继续保留最佳版本；本轮确认了切边目标的结构作用，残余差距主要在计算集中，
下一步核对 p12 过估与 p11/p15 热点，再完善两沿负载的初始构造。

2026-10-17 同主题追加 [原始成本与实际调度误差分解（TNO0337 §28.23）](./TNO0337_grhsim_partition_system_redesign_20261013.md#2823-原始成本与实际调度的误差分解及两沿初始构造2026-10-17)：
全分区组进入计数定位了 §28.22 p12 的主要过估：上升沿 60.98% 的生成后库存
所在组从未进入，预测 291,882 个 scalar 单位、实际进入折算 26,718；后端重建
只使其库存减少 8.03%。实现了保守的无条件/条件来源分类与六维初始构造原型，
但有界种子回平衡未满足自身容量，且扩大复制/通信。node030 CPU96–127 上
40 次功能/完整 THP 验证通过：对最佳 fresh 八对 walltime 11.97→13.91 s
（逐对 +16.60%）；对上轮候选 fresh 四对 14.165→13.67 s（−3.36%）。
后者最大分区平均 eval −19.50%，全局 eval 仅 −4.79%，update +10.99%。
继续保留最佳版本；下一步细化写入与值变化条件，并把多维/复制集合约束前移到
初始构造，不再增加单权重种子后的修补轮数。

2026-10-17 同主题追加 [细化状态来源与直接计量复制集合（TNO0337 §28.24）](./TNO0337_grhsim_partition_system_redesign_20261013.md#2824-细化状态来源与直接计量复制集合的初始分配2026-10-17)：
完成独立状态/写者来源、自保持分类及从空分配开始的多维粗化/需求集合计量。
315,932 个写端口仅新增识别 12 个原使能恒真的简单自保持条件，分类相关性
未改善。新构造缩小了容量偏差，但仍超限，发送调用 2,397→42,116、recurring
总量增加 27.62%。node030 CPU96–127 上双方 fresh 八对 walltime
12.115→18.695 s，逐对 +53.98%、0/8 获胜；eval +42.37%、update +187.89%。
正式测量的额外单步时间约 68.32% 来自 eval、31.53% 来自 update；独立两对
诊断确认 eval 退化主要在下降沿。24 次功能/完整 THP 验证通过。归档改用响应
文件并复用全部 9,849 个编译对象。
继续保留最佳版本；下一步以独立的多约束 Mt-KaHyPar 研究实现检验完整多级
求解质量，保留真实复制/通信审计，不继续扩展本轮简化贪心构造或拟合活跃概率。

2026-10-17 同主题追加 [独立多约束 Mt-KaHyPar 静态验证（TNO0337 §28.25）](./TNO0337_grhsim_partition_system_redesign_20261013.md#2825-独立多约束-mt-kahypar-静态验证2026-10-17)：
在官方多约束研究分支上复用同一六维来源向量和 source/value 图，默认多级求解能够
结束，但 hard capacity 会显著切开复制关系：最佳静态折中 value-edge×16 相对最佳
基线 recurring +11.34%、发送调用 +289.48%、发送字节 +23.68%，因此未生成 C++
或做 walltime AB/BA。确认 atom 5 在四个维度本身超过 5% 分区上限，且图中有
44,776 个全零节点；在隔离副本修复了 fallback 空目标、负进度和零权重 NaN 边界。
下一步改研究不可拆超大节点隔离与“容量软约束＋复制/连接目标”的分层求解，生产
默认、Verilator 路径和当前最佳划分保持冻结。

2026-10-17 同主题追加 [不可拆大节点隔离与完整 GrhSIM 验证（TNO0337 §28.26）](./TNO0337_grhsim_partition_system_redesign_20261013.md#2826-不可拆大节点隔离与完整-grhsim-验证2026-10-17)：
将最大不可拆 ASC 作为 isolated lane，其余节点做 31-way 容量软约束求解。相对本轮
control，静态 recurring +5.84%、piece copies +6.93%，但 send bytes −24.51%；
execution-plan 结构和 transfer 账本完整闭合。补齐通用 `packed_fill_slice_words`
机制记账后，node030 CPU96–127 上同 library 的 8 对 fresh AB/BA、C=100000
全部通过功能和完整 THP：Host −6.55%、walltime −6.46%、global eval −5.62%、
update −11.57%，8/8 获胜。分区 eval 总和 +8.83% 而最大分区 eval −3.28%，说明
收益来自 barrier 关键路径和 update/通信阶段，不能用总 eval 求和解释。该方法暂不
设为默认；下一步用 wide-helper 峰值、最大 eval、update push 与通信峰值做联合静态
门槛，并验证跨 workload/仿真器的泛化。

同节追加的四个次大不可拆节点扫描显示，任意隔离大节点都会使 recurring 和 send calls
明显恶化，且最大 closure/recurring 仍由原始 atom 5 路径决定；因此后续候选必须按后端
机制峰值和六维权重联合排序，不能按节点大小单独选择。扫描结果和未进入运行时的静态
账本见同一文档 §28.26.1。
进一步实现的 `backend_shape_proxy.py` 保留跨 context 的共享度、fanout 和最大单项，
但对 `wide_helper` 的全 phase 最大相关性仍只有 0.176；它适合作为候选筛选输入，不能
替代 lowering 结构回放。

同一条验证线进一步按后端 feature 做了静态归因：whole/rising 中
`compute.wide.helper.kMux`、`compute.constant.wide_temporary`、
`compute.wide.helper.kOr` 与 `wide_helper` 的相关性分别为 +0.779、+0.732、+0.554，
明显强于六维容量轴。新增 raw extractor 的 ASC 级通用 feature 导出正在独立目录
`activity_context_shape_v1` 中生成；该结果仅用于后续候选排序和结构 gate，不改变默认
入口或 Verilator 路径。明细见 TNO0337 §28.26 及其
[`mechanism_feature_correlations.txt`](../../build/repcut_grhsim_balance_20261013/redesign/indivisible_sweep_20261017/mechanism_feature_correlations.txt)。

提取完成后用与 `phase_pareto` 一致的 control 标签复核了公平 ASC 回摊：whole/rising
的 kMux、wide temporary、kOr 相关性为 +0.783、+0.705、+0.654，峰值都落在 part 30；
但 source proxy 的量级与 generated mechanism ledger 仍不同，说明后端的
assignment-dependent cloning、跨分区 demand 和 context coactivation 需要第二阶段
结构回放。该 proxy 先作为 generic ASC 权重候选，不直接替代完整 cost；下一步是
candidate assignment 之后、C++ 生成之前的 backend structural replay 与 gate。见
[`backend_feature_proxy_analysis.txt`](../../build/repcut_grhsim_balance_20261013/redesign/indivisible_sweep_20261017/backend_feature_proxy_analysis.txt)。

2026-10-18 同主题追加 [分析口径勘误、候选工具与直接对照（TNO0337 §28.26.4）](./TNO0337_grhsim_partition_system_redesign_20261013.md#28264-分析口径勘误候选工具与直接对照2026-10-18)：
补正两组旧静态 probe 的配置与输出目录问题；实际 AB/BA 结果有效，但不能据旧静态
表归因 batch/input-target 成本，也不能将模型 commit 与框架 update_push 混淆。
新增配置/完整性校验及有界 whole-ASC 候选工具，预算/Pareto 筛选也已接入，14 项测试通过。node030 CPU96–127
上的 8 对直接 fresh AB/BA 显示 p12→p21 相对 p12→p15 walltime 配对中位数 −0.76%，
6/8 对获胜、1 对持平；优势较小，暂沿用 p12→p21 继续验证，保留另一候选。

同节后续的 [共享 piece 合并验证（TNO0337 §28.26.5）](./TNO0337_grhsim_partition_system_redesign_20261013.md#28265-共享-piece-合并的完整-walltime-验证2026-10-18)
在 p12→p21 起点上将 2,343 个完整 ASC 从 p30 合并到 p29。node030 CPU96–127、
C=100000、8 对 fresh AB/BA 全部通过：Host −2.05%、walltime −2.02%，8/8 获胜；
p30 eval 32.70→10.15 µs，p29 22.99→34.90 µs。最大分区平均 eval 反而上升 6.45%，
但全局 eval 下降 2.73%，因此保留此候选，并按逐 step/分沿关键路径继续评估。
新的验证线入口与完整身份信息见
[`retained_candidate_20261018.json`](../../build/repcut_grhsim_balance_20261013/redesign/indivisible_sweep_20261017/retained_candidate_20261018.json)；
后续比较仍必须重新运行双方，生产默认与 Verilator 路径未改。

2026-10-18 追加 [逐步、分沿瓶颈归因（TNO0337 §28.26.6）](./TNO0337_grhsim_partition_system_redesign_20261013.md#28266-共享集合合并后的逐步分沿瓶颈归因2026-10-18)：
同一对 binary 的 2 对 C100000 诊断 AB/BA 显示，p30→p29 使全局下降沿 eval
减少 7.174 µs、上升沿增加 5.121 µs，净减少 1.026 µs/step；约 97% 对应逐步
最长回调的缩短，框架窗口外时间基本不变。候选 p29 上升沿/p8 下降沿最后完成比例
为 36.47%/41.01%，下一步优先查 p29 上升沿激活，再查 p8 下降沿。
[交互 HTML](../../build/repcut_grhsim_balance_20261013/redesign/indivisible_sweep_20261017/p30_phase_trace_20261018/grhsim_edge_bottlenecks.html)
可切换时钟沿、阶段、AB/BA 和各分区瓶颈指标。诊断时间与此前 8 对普通 walltime
测量分开，不将运行时间写入划分权重。

2026-10-18 追加 [p29 提交后活动增长与生产者归属（TNO0337 §28.26.7）](./TNO0337_grhsim_partition_system_redesign_20261013.md#28267-p29-提交后活动增长同周期对照与生产者归属2026-10-18)：
两组各 2 对 C100000 计数 AB/BA 通过，结果逐字节可重放。p29 上升沿始终两轮，
96.585% 的进入库存增量发生在提交后；同一步重复部分仅 1.558%。同一批 34,921 个
瓶颈周期中，p29 进入操作库存 42,740.73→102,695.71，独立 trace 均值
22.40→52.99 µs。精确表达式及依赖路径确认：生产者从远端移到本地，会使原有
消费者也提前在上升沿激活；p8 下降沿进入工作量未变。保留当前最佳候选，下一步
据此复核 entry/settle 增量和生产者—消费者成组，计数版耗时不作性能收益证据。

2026-10-19 同主题追加 [entry/settle 账本驱动的部分完整集合回迁验证（TNO0337 §28.26.8）](./TNO0337_grhsim_partition_system_redesign_20261013.md#28268-entrysettle-账本驱动的部分完整集合回迁验证2026-10-19)：从当前 p30→p29 候选回迁一个 1,697-ASC 完整集合到 p30；node030 CPU96–127 上 8 对 fresh AB/BA 的 walltime 配对中位数下降 0.215%，最大分区 eval 下降 4.831%，分区 eval 总和上升 1.713%。结果支持同时约束 phase 关键路径和目标 lane 代码规模的通用方向，候选暂不改生产默认。

2026-10-19 同主题追加 [回迁候选的独立重复验证（TNO0337 §28.26.9）](./TNO0337_grhsim_partition_system_redesign_20261013.md#28269-回迁候选的独立重复验证与结论收束2026-10-19)：第二轮 8 对 fresh AB/BA 中 walltime 配对中位数为 +0.0517%，最大分区 eval 仍下降 3.5594% 而分区 eval 总和上升 1.8775%；候选不晋级默认，后续转向生成前的后端结构 gate。

2026-10-19 同主题追加 [生成前 backend-shape gate 与 629-ASC 候选验证（TNO0337 §28.26.10）](./TNO0337_grhsim_partition_system_redesign_20261013.md#282610-生成前-backend-shape-gate-与-629-asc-候选验证2026-10-19)：静态 v2 gate 在 9 个完整 piece 候选中仅放行 n629；两轮小页 8 对 AB/BA 的 walltime 分别下降 3.596%/3.362%，THP 因 node030 当前 MADV_COLLAPSE 内核资源不足待恢复后复测，候选暂不改默认。

2026-10-20 同主题追加 [从头多约束划分与 warm-start proxy 反例（TNO0337 §28.26.11）](./TNO0337_grhsim_partition_system_redesign_20261013.md#282611-从头多约束划分与-warm-start-proxy-反例2026-10-20)：将 GrhSIM lowering 特征作为硬多约束、value-edge 加权或 scalar 软偏置都会破坏当前最佳共享关系；基于 ASC proxy 自动选择源 lane 还会选中 part 8，而真实生成瓶颈是 p29，24 个局部候选全部被静态通信门槛挡住。后续转向 assignment-dependent backend structural replay 驱动的局部搜索，Verilator 和生产默认入口保持不变。

2026-10-20 同主题追加 [assignment-dependent structural replay 局部搜索的第二步验证（TNO0337 §28.26.12）](./TNO0337_grhsim_partition_system_redesign_20261013.md#282612-assignment-dependent-structural-replay-局部搜索的第二步验证2026-10-20)：n629 的全局结构峰值下降 1.859%，但简单地把回放后最大 lane p0 的唯一 ASC 搬到 p25 会把结构峰值推高 47.325%；这说明 source 选择必须先判断可搬迁的本地 payload，不能每轮直接搬当前最大分区。空分区校验器也已修正，n629 仍等待 THP 复测。

2026-10-20 同主题追加 [p29 第二个局部 piece 的结构与小页复测（TNO0337 §28.26.13）](./TNO0337_grhsim_partition_system_redesign_20261013.md#282613-p29-第二个局部-piece-的结构与小页复测2026-10-20)：stage3 将一个 12-ASC 完整 piece 从 p29 移到 p30，p29 `graph_ops` 再降 5.192%、边界峰值再降 9.087%，并完成 Clang 23/O3 package 编译；两轮小页 AB/BA walltime 分别下降 0.197%/0.541%，但最大分区 eval 轻微上升、update-push 上升，仍保留为 THP-pending 候选。

2026-10-20 同主题追加 [stage3 小页收益的阶段归因与 perf 交叉检查（TNO0337 §28.26.14）](./TNO0337_grhsim_partition_system_redesign_20261013.md#282614-stage3-小页收益的阶段归因与-perf-交叉检查2026-10-20)：逐步计时确认 walltime 变化完全由 input-load、part-eval 和 global-update 三个窗口组成；小页收益主要来自 all-spin 的阶段等待窗口，不是最大 eval 下降。4 对 perf stat 仅用于诊断，显示指令/缓存量几乎不变而代码从 p29 移向 p30；THP 复测前不晋级默认。

2026-10-20 同主题追加 [phase synchronization 窗口的直接拆分（TNO0337 §28.26.15）](./TNO0337_grhsim_partition_system_redesign_20261013.md#282615-phase-synchronization-窗口的直接拆分2026-10-20)：新增仅替换 common wrapper object 的诊断 binary，8 对 node030 CPU96–127 交错样本显示 stage3 的 normal-eval phase 总窗口约 +1.14%，load/update 的小幅改善主要来自 completion wait 尾部变化；p8 仍是最大 eval body，stage3 不晋级默认。

2026-10-22 同主题追加 [p29→p4 完整 piece 迁移与 THP fresh AB/BA（TNO0337 §28.26.20）](./TNO0337_grhsim_partition_system_redesign_20261013.md#282620-p29p4-完整-piece-迁移的后端-gate-与-thp-fresh-abba2026-10-22)：完整源码总量仅增加 `0.033%`，p29 源码下降 `6.33%`、p4 增加 `9.54%`；普通页 8 对 AB/BA walltime `−0.601%`，`--preferred=1` 的 THP 8 对 AB/BA walltime `−0.667%` 且 8/8 获胜，功能和 huge-page audit 全通过。候选保留为 GrhSIM 探索线，不改默认划分。

2026-10-22 同主题追加 [自动来源选择与 p12→p2 复测（TNO0337 §28.26.21）](./TNO0337_grhsim_partition_system_redesign_20261013.md#282621-当前-candidate-起点的自动来源选择与-p12p2-复测2026-10-22)：profile 自动选出当前热点并复现 72 个候选；p12→p2 的最大 eval 下降约 `4%..5%`，但两轮 THP fresh AB/BA 的 walltime 分别为 `−0.517%` 和 `+0.715%`，合并仅 `−0.209%`，update 两轮均增加，候选淘汰。候选入口改为参数化 profile 选择，不绑定分区编号。

2026-10-22 同主题追加 [逐步关键路径与全分区通信筛选（TNO0337 §28.26.22）](./TNO0337_grhsim_partition_system_redesign_20261013.md#282622-以逐步关键路径和全分区通信账本修正候选筛选2026-10-22)：12 次 wrapper-only 诊断确认最大平均 eval 与每步关键路径不同；p12 只占 eval 瓶颈 `2.586%`，却占 update 瓶颈 `54.735%`。迁移还会拆开未移动 sender 的 reader-set 包，p18 调用 `133→158` 而字节减少。工具补齐全分区调用账本与逐步重叠排序，22 项测试通过；自动来源改为 p14/p29/p18，10-ASC p14→p11 进入完整验证。

2026-10-23 同主题追加 [10-ASC p14→p11 完整验证（TNO0337 §28.26.22 增量）](./TNO0337_grhsim_partition_system_redesign_20261013.md#282622-以逐步关键路径和全分区通信账本修正候选筛选2026-10-22)：两轮各 8 对 node030 CPU96–127、C100000、THP fresh AB/BA 的 walltime 分别为 `−2.401%/−1.750%`，合并 `−2.167%` 且 16/16 对获胜，保留为新探索起点。正式 global eval 改善、update 基本持平；诊断 trace 显示 p14 尾部转移到 p11，但插桩版未复现收益，半周期活动投影仍需改进。不改生产默认或 Verilator。

2026-10-23 同主题追加 [来源活动与包布局影响（TNO0337 §28.26.23）](./TNO0337_grhsim_partition_system_redesign_20261013.md#282623-用来源活动补充目的地负载估计2026-10-23进行中)：新增可选来源活动包络与精确包成员/位偏移影响账本，29 项测试通过。自动首位 p11→p10 的两轮 fresh AB/BA walltime `−0.450%/+0.056%`，未获得稳定收益，保留 p14→p11 起点。确认通信总调用/字节不变仍可通过包重排影响其它接收分区；下一步补实际 piece 活动和接收端激活成本。

2026-10-23 同节追加 [动态包活动与分沿共同激活归因](./TNO0337_grhsim_partition_system_redesign_20261013.md#增量更新动态包活动接收端计数与迁移后的分沿共同激活2026-10-23)：14 次 node030 CPU96–127 功能/THP 检查通过，正反序通信及组计数完全重复。实际 copy 调用仅 +0.000820%、字节 −0.0000496%，四个第三方接收者全部组进入计数相同；p11 clock=1 进入 work 只减 0.416%，p10 却增 41.755%，主要在 commit 后。11 组中的 1210 个完全相同表达式由原来 clock=1 不执行变为每组 45038 次；现有生成前 plan 已显示对应相位扩展。下一步接入分沿减量/增量与共同激活风险，保留 p14→p11，不把诊断耗时当作新收益；34 项相关测试通过。

2026-10-24 同主题追加 [phase-risk 门禁与 p11→p5 修正配置复测](./TNO0337_grhsim_partition_system_redesign_20261013.md#增量更新phase-risk-门禁测量配置校验与-p11p5-复测2026-10-24)：修正测量入口，统一使用 preferred NUMA、代码页 THP 和 64-byte compute 对齐，并在运行前后审计；p11→p5 两轮各 8 对 fresh AB/BA 的 walltime 配对中位数为 `−0.816%`、12/16 胜，Host `−0.850%`，global eval `−0.283%`，global update `−1.021%`。phase-risk 保留 rise/fall/unknown 和 range/whole 账本，不拟合时间系数；p11→p5 作为新的 GrhSIM 探索基线，生产默认和 Verilator 不变。

2026-10-26 同主题追加 [输入比较与位级激活的归档顺序勘误及复测](./TNO0337_grhsim_partition_system_redesign_20261013.md#勘误与增量更新统一归档顺序分离输入比较和位级激活2026-10-26)：统一 7851 个 archive member 的顺序，修正此前 dirty tracking 的布局混杂归因。48 对 fresh AB/BA、功能/THP/64-byte 对齐检查通过；现有通用 bit activation 在当前 assignment 上单独改善 Host 8.032%，叠加 dirty tracking 后相对 fresh baseline 改善 Host 8.895%、process elapsed 8.863%。dirty tracking 叠加的两轮 16 对净 Host 增量为 0.403%。逐步 trace 确认 p0 最长占比从 28.883% 降到 5.962%，后续按分沿余量关注 p18/p29/p11/p30；组合版作为探索起点，生产默认和 Verilator 不变。

2026-10-26 重要勘误 [历史二进制直接复测与完整生成配置恢复](./TNO0337_grhsim_partition_system_redesign_20261013.md#增量更新历史二进制直接复测与完整生成配置恢复2026-10-26)：两组 fresh 8 对 AB/BA 确认 combined 比历史最低候选慢 11.828%、比相同 p11→p5 assignment 的旧保留 ELF 慢 11.283%。新生成入口未继承完整历史 preset；旧线原已开启 bit/dirty，并启用布尔归约等其它选项。撤回“combined 超越完整历史最佳”的推断，恢复旧 p11→p5 为性能锚点，正在用当前 emitter 重放完整配置验收；此前 8.895% 仅是新建对照之间的有效消融结果。

同次恢复验证已完成：继承完整历史 preset 后，以当前 emitter 重生成、Clang23/O3 编译；7851 个模型归档成员中 7848 个 payload 与旧线相同。恢复版对旧保留 ELF 的 fresh 8 对 walltime 为 10.355→10.280 s（配对 −0.766%，仅视为恢复到旧线水平）；对遗漏选项 combined 的另 8 对为 11.420→10.195 s（−11.047%，8/8 胜）。本轮共 32 对、64 次正式运行和 8 次 smoke 全部通过。后续继承恢复版完整 `emit.json`，并保留旧 ELF 作为直接回归锚点；不将此次找回已有优化记为新增算法收益。

2026-10-26 同主题追加 [完整 preset 的批次与 ASC 归因](./TNO0337_grhsim_partition_system_redesign_20261013.md#增量更新完整-preset-上的批次与-asc-归因2026-10-26)：重新采集四次 C100000 追踪，完成 p29/p11/p18 的批次计时及独立组计数。p29 上升沿瓶颈样本的进入库存为非瓶颈的 3.54 倍，同一步重复进入仅占 1.15%；主要增量来自提交后多组共同活跃。严格原始 ASC 归因确认热点跨多个逻辑锥，继续关注初始分配及归属改变造成的激活集中；插桩耗时不作新的 walltime 收益。

同次归因已完成 16 次 C100000 与 10 次初始化核验；另将 p11 最集中的三个热批次追到 8 个带状态的末端观测 ASC。后续先按状态依赖与反馈关系扩展 GrhSIM 的终端分类，再验证一个完整初解；保持 ASC、effect 约束和完整 preset，不按分区/信号名选择，不用诊断次数拟合权重。

2026-10-27 同主题追加 [末端状态分类与完整初解验收](./TNO0337_grhsim_partition_system_redesign_20261013.md#增量更新末端状态分类与初始构造2026-10-27)：通用 SCC 分类及从端点向上游的初始放置识别 21457 个状态 ASC，结构预算与 17 次 C100000、2 次初始化检查通过。完整 preset、THP、64-byte 对齐下的 fresh 8 对 AB/BA walltime 为 11.215→12.410 s（配对 +10.656%，0/8 胜）；update −18.169%、分区 eval 之和 −15.383%，全局 eval 却 +16.979%，因此不替换最佳线、不改默认。独立依赖路径确认含 1673 个 sink 的大 ASC 把观测链与功能反馈链连在同一投影环；下一步需在原始状态粒度判断反馈，再映射回完整 ASC。

2026-10-27 同节追加 [值级状态回溯复核](./TNO0337_grhsim_partition_system_redesign_20261013.md#增量更新值级状态回溯复核2026-10-27)：从每个完整 ASC 的 sink 沿 value definition 反向回溯真实 storage read 后，依赖边为 188859989 条、环 SCC 为 7712 个、最大 SCC 为 217542 个 ASC；8 个热点 ASC 仍全部位于该 SCC，末端候选为 18316 个。与旧 ASC 直接投影相比只减少 56 条边，说明大环主要是真实状态依赖和完整 ASC 的耦合，不能靠粗粒度修正释放这些热点；本轮不再继续生成/编译无明确收益的性能候选，保留最佳恢复版作为后续起点。

2026-10-27 同节追加 [最大 SCC 的 sink 锥重叠探针](./TNO0337_grhsim_partition_system_redesign_20261013.md#增量更新最大-scc-的完整-asc-规模与拆分切入点2026-10-27)：最大 SCC 的 217542 个 ASC 合计约 2.67 亿个组合操作，最大 ASC 为 249876 操作/20371 sinks，另一个大 ASC 为 68816 操作/1673 sinks。寄存器/effect sink 之间高度共享，而 memory sink 样本大多独立；下一步将按通用 sink-cone overlap graph 评估可拆分连通块，保持 storage/effect 约束，不按信号名或分区编号特判。

2026-10-27 同节追加 [最大 ASC 的 hard-union 归因与 memory bridge 扫描](./TNO0337_grhsim_partition_system_redesign_20261013.md#增量更新最大-asc-的-hard-union-归因与-memory-bridge-扫描2026-10-27)：ASC 5/89887 的大原子主要由 memory-cone union 的传递闭包形成；只保留 storage/effect hard rule 后分别变为 17,927/1,645 个组件，但 memory fanout 中位数分别为 16/743，直接去掉 bridge 会产生 41,006/5,584 个 component-memory 归属并触发 phase-E 的 memory-read cross 检查。阈值扫描表明这是需要 memory-read forwarding/clone 语义的通用后端问题，暂不改默认 `buildAscs`。

2026-10-27 同节追加 [最小 memory bridge 语义 fixture](./TNO0337_grhsim_partition_system_redesign_20261013.md#增量更新最小-memory-bridge-语义-fixture2026-10-27)：最小图证明加入同 memory 写口后，两个独立 read consumer 会由 2 个 ASC 合并为 1 个；activity-schedule 已能 clone memory read，但 phase-E 仍禁止跨分区 memory-read value。下一步先定义 owner snapshot/forwarding 或合法 read clone 协议，再接入通用 sink-cone overlap 分拆。

## 来源覆盖

- 初始整理范围：`NO0221..NO0526`。
- 原始记录数：`306`。
- 初始来源整理形成的 TNO 主题文档数：`20`。
- 当前记录类文档总数：`452`（`TNO0001..TNO0452`）。
- 2026-11-03 新增 [TNO0397：PopCount 的紧凑布局替换与香山单线程实测](./TNO0397_popcount_intrinsic_packed_layout_walltime_20261103.md)：完整香山生成中识别到 1,095 个 packed `PopCount.Bits`、7,140 个分布式 `Vec/Seq` 调用保留硬件；B 的 `kCountOnes` native 模型功能和两组 100,000 周期 trace 全部通过，但 node030 CPU96 的 8 对单线程 walltime 为 `+0.665717%`（0/8 胜，95% CI `[+0.421713%, +0.925537%]`）。静态模型略小而运行略慢，下一步优先消融 1–3 位高频调用和后端活动形态，不启用默认 PopCount。
- 2026-11-05 新增 [TNO0434：DiffTest RTL 结构审计与候选改写](./TNO0434_difftest_rtl_audit_20261105.md)：检查了中间 `dontTouch`、packed source、整包延迟寄存器和无效 payload 置零。前三项没有缩小 GRH 调度结构，最后一项反而增加 RTL 组合逻辑；当前主要成本集中在物理寄存器观察器、Preprocess 动态映射和完整接口集合，下一步应转向 observer-side GRH 组织，保留 S3 功能。
- 2026-11-05 新增 [TNO0435：Chisel 行为模型 API 与普通 GRH 状态基线](./TNO0435_behavior_model_generic_grh_20261105.md)：新增 elaboration 阶段 `hardware/commit-rat` 模式和 `simulation_models.json`，fixture 以两个长度为 32 的数组描述 commit/RAT 更新，A/B 均为 591 个 GRH operation，普通 lowering 后有 64 个 register/read/write port，1,002 个含 reset 的随机 commit/RAT 采样轨迹完全一致。当前不新增专用 GRH OperationKind，先把真实 DiffTest 字段裁剪和检查适配器接上后再做整机性能判断。
- 2026-11-05 新增 [TNO0436：DiffTest 语义级 commit/RAT adapter](./TNO0436_behavior_difftest_semantic_adapter_20261105.md)：恢复完整 ROB 微操作时序，按每个架构索引最后写入合并；先 gather 后延迟代替整张物理 RF 延迟。30,000 周期对原 Preprocess 的整数/FP/vector/RAT/commit_data 对照通过，整机同源码 A/B 构建与功能检查进行中；不新增专用 GRH 节点。
- 2026-11-05 新增 [TNO0437：语义级 commit/RAT 模型的完整 S3 验证与性能](./TNO0437_behavior_commit_rat_s3_measurement_20261105.md)：同源码 A/B 的两组 100,000 周期 NEMU 与原始 trace 完全一致；完整 S3 的 8 对 AB/BA 平均回退 5.2677%（95% CI +2.9748%..+7.1048%，1/8 更快）；A/A 完成一对后按用户要求停止。默认 hardware，不增加专用状态节点。
- 2026-11-05 新增 [TNO0438：数组语义到 kBehaviorStateGroup 的局部实现与契约验证](./TNO0438_behavior_state_group_contract_20261105.md)：v2 typed binding 与完整 SV carrier，普通/分组使用同一语义；组拥有有序数组更新，只有最终净变化激活 reader。小数组与 520 路 RAT、拒绝检查、SV 回退及多实例旧状态验证通过；补齐 TNO0437 的两项生成检查，保持默认 ordinary。
- 2026-11-05 新增 [TNO0439：kBehaviorStateGroup 的生产优化流程局部性能](./TNO0439_behavior_state_group_local_performance_20261105.md)：与完整 S3 相同优化配置下，RAT 分组相对普通模型在稀疏/密集更新快 24.10%/21.19%，相对原写法快 16.56%/17.10%，均 8/8 更快；小型双数组未通过相对普通模型门槛。仅完成局部验收，未重启整机或 A/A，默认 hardware/ordinary 不变。
- 2026-11-05 新增 [TNO0440：分组 RAT 接入完整 S3 的实现与局部验收](./TNO0440_grouped_rat_s3_integration_20261105.md)：原始 520 路更新绕过逐行合并，显式 observer domain 支持 debug delay/Gateway，功能反馈继续拒绝；真实 adapter O/G 各 30,000 周期及 DPI 时序检查通过。已修正 native 动态库冻结遗漏，完整同源码 S3 A/B 构建启动。
- 2026-11-05 新增 [TNO0441：分组 RAT 的完整 S3 构建与 NEMU/trace 验收](./TNO0441_grouped_rat_s3_functional_gate_20261105.md)：完整 A/B 编译通过，B 保留 2,080 条更新；两组各 seed 0/1、100,000 周期通过 NEMU，四份原始 trace 哈希完全一致。已勘误：最终 GRH 操作数少 4.63%，compute supernode/激活边仍略多；性能见 TNO0442。
- 2026-11-05 新增 [TNO0442：分组 RAT 的完整 S3 性能测量](./TNO0442_grouped_rat_s3_performance_20261105.md)：8 对 AB/BA 配对均值 +0.170705%，95% CI [-0.182087%, +0.461222%]，2/8 更快，未测出稳定整机加速。所有 S3 检查与运行环境审计通过，保留全部样本；不追加 A/A，不把历史普通模型的回退相减作为收益，默认 hardware/ordinary。
- 各 TNO 的来源范围连续、互不重叠，合并后完整覆盖 306 个原编号。
- 详细原始记录继续保存在 [`../grhsim_opt`](../grhsim_opt/README.md)，本目录不复制或改写原文件。

- 2026-11-05 新增 [TNO0443：乘法行为模型实现及局部功能验收](./TNO0443_multiply_behavior_implementation_20261105.md)：四类真实乘法通路使用直接乘法并保持流水；八个 core 模型和四个真实 FU wrapper 各通过 30,000 周期，FP 使用 SoftFloat 参考；修正 SV 自定宽乘法导入，默认硬件 RTL 与原源码一致。

- 2026-11-05 新增 [TNO0444：乘法行为模型局部性能](./TNO0444_multiply_behavior_local_performance_20261105.md)：四类 active/sparse/idle 均加速，持续输入分别快约 86.6%/80.5%/63.9%/45.6%，全部通过局部门槛；保留两次区域干扰记录，只补未完成场景，进入新完整 S3 A/B。

- 2026-11-05 新增 [TNO0445：乘法定向负载与布尔操作数位宽修复](./TNO0445_multiply_vector_baseline_width_fix_20261105.md)：旧硬件 S3 的向量程序暴露声明初始化比较中的错误截断；最小模型 4,224 组输入、12 种谓词通过，四类模型与 wrapper/有效数边界在修复后重新验收，RTL 冻结复用并重新做 native 构建。

- 2026-11-06 新增 [TNO0446：标量与向量乘法行为模型的完整 S3 验收](./TNO0446_multiply_behavior_full_s3_20261106.md)：修复 `andi+mulw`→`MULW7` 覆盖识别后，89 个乘法/FMA 站点和两组 100,000 周期 trace 全部通过；CoreMark B 回退 +0.706974%（95% CI [+0.353768%, +1.056130%]），定向乘法 B 回退 +0.776006%（CI 跨零），保持默认 hardware。
- 2026-11-07 新增 [TNO0447：`kBehaviorComputeGroup` 与乘法行为模型](./TNO0447_behavior_compute_group_multiply_20261107.md)：四类 carrier 的普通/分组逐拍功能与绑定拒绝检查通过；局部结果显示只有标量整数分组相对 ordinary 达到门槛，向量整数明显回退，浮点两类不足 5%。完整 S3 仅带入 grouped `int-mul`，8 对 CoreMark walltime 最终回退 `+0.486457%`（95% CI `[+0.348429%, +0.622474%]`），默认仍保持 hardware。
- 2026-11-07 新增 [TNO0448：整数与位运算行为模型 carrier 闭环](./TNO0448_integer_bit_behavior_models_20261107.md)：新增显式 `HostOpSpec`、`int-alu`/`int-bku` 的 ordinary/grouped carrier 和宿主 helper，接入 `VIAluFix` 与单 uop `VIPU` mask/scalar carrier，并为 VIMac 注册 lane/whole boundary 选择；标量、VIAlu 和 VIPU fixture 的 Verilog→GRH→C++ 闭环与固定向量通过，未进行整机 walltime，默认仍保持 hardware。
- 2026-11-07 新增 [TNO0449：整数与位运算行为模型统一功能矩阵](./TNO0449_integer_bit_functional_matrix_20261107.md)：`int-alu`、`int-bku`、`vec-int-alu-lane` 和 `vec-int-pu-lane` 在三个固定种子、每种子 10,000 周期的 ordinary/grouped 摘要完全一致；补齐 ALU 高位控制、XPERM.B、VIAlu 窄化结果和比较 sideband 语义。node030 CPU96–127 当时有外部任务占用，未启动局部 walltime，默认仍保持 hardware。
- 2026-11-07 新增 [TNO0450：整数与位运算行为模型局部性能比较](./TNO0450_integer_bit_local_performance_20261107.md)：四类 lane/scalar 模型在 active/sparse fixture 场景均显示 grouped 稳定加速（`-48.146%..-92.121%`，8/8 对更快）；idle 场景仅 VIPU lane 的区间稳定为负，其余区间跨零。输出哈希逐对一致；未把局部结果外推到整机，默认仍保持 hardware。
- 2026-11-08 新增 [TNO0451：整数与位运算行为模型的完整 S3 验收](./TNO0451_integer_bit_full_s3_20261108.md)：`int-alu`、`int-bku`、`vec-int-alu-lane` 和 `vec-int-pu-lane` 的 grouped 行为模型完成完整 XiangShan 构建；两组 100,000 周期 CoreMark DiffTest trace 完全一致，B 的 8 对 walltime 均值为 `−0.181330%`，但 95% CI 为 `[−0.701011%, +0.153807%]` 且只有 2/8 对更快，未测出稳定整机收益，默认仍保持 hardware。
- 2026-11-09 新增 [TNO0452：整数行为模型的运行时归因](./TNO0452_integer_behavior_runtime_attribution_20261109.md)：profile 版本在 CoreMark 和 `microbench.bin` 上显示四类行为 helper 分别只占 compute batch 的 `0.9405%` 和 `0.7654%`，向量 helper 各仅执行 5 次；B 与 A 的 compute batch 数相同，commit batch 反而增加 3.33%，model-step phase 仅变化 `−0.31%/−0.22%`。行为 carrier 不是完整 eval 热点，后续转向 DiffTest observer、state-read activation 和通用 batch/activation 成本，默认仍保持 hardware。
