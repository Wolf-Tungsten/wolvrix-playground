# kunminghu-v3 merge 与 GrhSIM 对测

本目录按阶段记录从 XiangShan `77ed568fc` 合并上游 `kunminghu-v3`，并比较合并前后的单核 native GrhSIM 与 32 线程 RepCut GrhSIM。记录遵循追加式规则：独立阶段独立成文，原始日志和机器可读结果保留在 `build/artifacts/kunminghu-v3-grhsim-merge-20261110/`。

规则参考：[GrhSIM 文档管理规则](../grhsim_opt_thj/RULES.md)。

## 当前结果

XiangShan 已完成真实 merge：`9d1f24c` 的两个 parent 是 `77ed568fc` 和上游 `41ab74e7d`；当前 `defb18e13` 固定本地 difftest 适配 `b17a43a`。XiangShan 相对该上游 commit 仅保留 difftest gitlink 差异。父仓继续使用 `thj/gsim-calibrate-2`，默认功能/性能流程的区分保持不变。

CoreMark、100,000 周期、完整 DiffTest/NEMU，每组 8 对 AB/BA，正数表示合并后更慢：

| 测量 | before / after 平均 Host time | 配对 delta 均值 | 95% CI |
| --- | ---: | ---: | ---: |
| 单核 CPU96 | 101.289 / 132.449 s | +30.766% | [+29.968%, +31.781%] |
| 32 线程主实验 | 38.241 / 48.159 s | +32.179% | [+15.007%, +60.360%] |
| 32 线程同 binary 复测 | 17.004 / 17.507 s | +2.904% | [−1.458%, +8.379%] |

单核 8/8 合并后更慢。32 线程主实验存在明显的跨时段变化，同配置复测没有复现其幅度，因此不能确定稳定的 32 线程版本差异。两轮独立归档，不合并、不丢弃慢样本。结果包含上游 DefaultConfig、微架构和缓存容量变化。

### 2026-11-11 固定 CPU 补测

在 node030、单核 CPU96、RepCut CPU96–127、NUMA1、ASLR disabled 条件下，使用同一冻结 CoreMark/NEMU、100,000 周期、完整 DiffTest/NEMU、8 对 AB/BA 重新测量。共同终止条件和 workload 输出通过；跨版本 PC/提交进度按 revision-specific 规则单独保留。正数表示 after 更慢：

| 测量 | after Host time delta | 95% CI | after 更快 |
| --- | ---: | ---: | ---: |
| 单核 GSIM | +34.774% | [+33.872%, +35.624%] | 0/8 |
| 单核 GrhSIM CPU96 | +31.459% | [+28.719%, +35.527%] | 0/8 |
| 32 线程 RepCut CPU96–127 | −5.460% | [−5.841%, −5.011%] | 8/8 |

这是整版 XiangShan revision、DefaultConfig 和所跟踪 DiffTest 的比较，不能分离解释为 GSIM/GrhSIM 后端优化收益。完整机器可读汇总见 [follow-up report](../../build/artifacts/kunminghu-v3-gsim-followup-20261111/report.json)，分组结果和 placement 证据见 [TNO0021](./TNO0021_gsim_paired_walltime_20261111.md)、[TNO0022](./TNO0022_grhsim_cpu96_followup_20261111.md)、[TNO0023](./TNO0023_repcut_cpu96_127_followup_20261111.md)。

[总报告](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/report.json) 保留 Host time、外部 walltime、功能签名、输入身份和配对数据链接。

## 记录

| 阶段 | 文档 | 状态 |
| --- | --- | --- |
| 身份与基线 | [TNO0001](./TNO0001_identity_and_baseline_20261110.md) | 身份已冻结，before 功能门见 TNO0003 |
| difftest 适配设计与进度 | [TNO0002](./TNO0002_difftest_merge_port_20261110.md) | merge 已形成；后续 flash 兼容见 TNO0006 |
| before 功能门与配对 runner | [TNO0003](./TNO0003_before_functional_and_pair_runner_20261110.md) | before 两种 simulator 的 100k 功能签名一致 |
| 上游 RTL/schema/memory | [TNO0004](./TNO0004_upstream_rtl_schema_memory_20261110.md) | after RTL/model 完成；memory 配置按新层级独立归档 |
| RepCut 分阶段执行 | [TNO0005](./TNO0005_staged_repcut_execution_20261110.md) | before 完成；after wrapper 兼容修复与续跑见 TNO0012 |
| BootROM 兼容与 after native 功能门 | [TNO0006](./TNO0006_bootrom_compatibility_native_gate_20261110.md) | 默认 ROM、冻结 REF 的 10k/100k 完整 DiffTest 通过 |
| trace 覆盖验证器 | [TNO0007](./TNO0007_trace_cycle_coverage_20261110.md) | 11 项 focused 测试通过；真实运行见 TNO0008 |
| native trace 与结构门 | [TNO0008](./TNO0008_native_trace_and_structure_gate_20261110.md) | 两侧各两组 100k trace、CPU96/NUMA1 门通过 |
| 独立配置与配对入口 | [TNO0009](./TNO0009_reproduction_and_paired_runbook_20261110.md) | 两种对测均完成；后续 NUMA/监控修正见 TNO0016–0017 |
| 合并 checkout 与子模块 | [TNO0010](./TNO0010_merge_checkout_completion_20261110.md) | 主 checkout 已更新；递归子模块干净 |
| harness 验证 checkpoint | [TNO0011](./TNO0011_harness_validation_checkpoint_20261110.md) | 83 项测试通过，before RepCut 48 次 100k 签名一致 |
| RepCut 无驱动信号兼容 | [TNO0012](./TNO0012_repcut_undriven_wrapper_compatibility_20261110.md) | focused emitter 测试通过；验证结果见 TNO0013 |
| Backend 一致性与 after 功能门 | [TNO0013](./TNO0013_backend_compatibility_equivalence_gate_20261110.md) | before 15,754 个 source/header 字节一致；after 8 次 100k 通过 |
| RepCut retained 构建门 | [TNO0014](./TNO0014_repcut_retained_build_gates_20261110.md) | before=candidate、after=initial；正式对测开始 |
| native 8 对 AB/BA walltime | [TNO0015](./TNO0015_native_paired_walltime_20261110.md) | after 慢 30.766%，95% CI [29.968%, 31.781%] |
| RepCut 严格 NUMA 运行 | [TNO0016](./TNO0016_repcut_strict_numa_runtime_20261110.md) | 首次 verify 因远端页拒绝；统一 membind=0 后重新对测，84 项测试通过 |
| RepCut 退出阶段监控勘误 | [TNO0017](./TNO0017_repcut_teardown_affinity_verifier_20261110.md) | 退出后 host affinity 恢复不计作运行期失败；最终系列重新采集 |
| RepCut 8 对主实验 | [TNO0018](./TNO0018_repcut_primary_paired_walltime_20261110.md) | 平均 +32.179%，中位数 +18.341%；中途明显时间漂移 |
| RepCut 同 binary 复测 | [TNO0019](./TNO0019_repcut_confirmation_20261110.md) | 平均 +2.904%，CI 跨零；没有复现主实验幅度 |
| 最终源码、验证与归档 | [TNO0020](./TNO0020_completion_and_artifact_manifest_20261110.md) | 合并与对测完成；四种模型 manifest、原始数据和验证索引齐备 |
| GSIM 合并前后补测 | [TNO0021](./TNO0021_gsim_paired_walltime_20261111.md) | 8 对通过；after Host time +34.774%，CI [+33.872%, +35.624%]；文末已追加 BA 列与外部 walltime 勘误 |
| 单核 GrhSIM CPU96 补测 | [TNO0022](./TNO0022_grhsim_cpu96_followup_20261111.md) | 8 对通过；after Host time +31.459%，CI [+28.719%, +35.527%] |
| RepCut CPU96–127 补测 | [TNO0023](./TNO0023_repcut_cpu96_127_followup_20261111.md) | 8 对通过；after Host time −5.460%，CI [−5.841%, −5.011%] |
| RepCut 历史 10 秒 anchor 复核 | [TNO0024](./TNO0024_repcut_historical_anchor_audit_20261111.md) | 同一当前 runner 复测历史 anchor 10.552 s、merge-before 17.770 s；主要差距在分区 eval |
| 历史标准 RepCut pipeline 复核 | [TNO0025](./TNO0025_repcut_historical_standard_pipeline_audit_20261111.md) | seed7 标准 pipeline 当前 runner 11.0525 s；merge-before 17.039 s，Host delta +53.881% |
| 历史与 before 的源 Verilog 内容 | [TNO0026](./TNO0026_historical_before_verilog_content_20261111.md) | 2,097 个生成 RTL 中 44 个内容不同，含表达式变化；追加 TNO0025 因果判断与 HGR 描述勘误 |
| before 独立 8-seed 重试 | [TNO0027](./TNO0027_before_partition_retry_20261111.md) | 选中 seed2，km1 比原选择低 0.15249%；功能和性能结果在文末追加 |
| 新 seed2 的 Clang 23 重编译 | [TNO0028](./TNO0028_seed2_clang23_recompile_20261111.md) | 固定生成 C++，Clang 19 / 23 配对；完成结果在文末追加 |
| 三组统一 Clang 23 重编译口径 | [TNO0029](./TNO0029_all_clang23_rebuild_protocol_20261111.md) | GSIM、native GrhSIM、RepCut 前后六份 emulator 重编译；分组结果后续独立归档 |
| Clang 23 RepCut 前后对测 | [TNO0030](./TNO0030_clang23_repcut_merge_comparison_20261111.md) | before seed2 / after seed7，11.702 → 17.883 s，after +52.845%，8/8 更慢 |
| Clang 23 单核 GSIM 前后对测 | [TNO0031](./TNO0031_clang23_gsim_merge_comparison_20261111.md) | 78.974 → 106.913 s，after +35.378%，8/8 更慢 |
| Clang 23 单核 GrhSIM 与总核对 | [TNO0032](./TNO0032_clang23_native_merge_comparison_20261111.md) | native 110.015 → 140.255 s，after +27.489%；六份构建、三组各 8 对、70 次运行全部通过 |
| after 独立 8-seed 分区重试 | [TNO0033](./TNO0033_after_partition_retry_protocol_20261111.md) | 选中新 seed1，km1 比原 seed7 低 3.66045%；运行结果另文追加 |
| after seed1 功能拒绝与诊断 | [TNO0034](./TNO0034_after_retry_difftest_rejection_20261111.md) | 95,577 guest cycles 的 a4 mismatch；32 线程重复及单线程均重现，无有效性能对测 |
| after seed1 的 Clang 23 根因 | [TNO0035](./TNO0035_after_seed1_clang23_mask_codegen_20261111.md) | 定位至单对象的 8/16 位向量掩码错误；单字节机器码修正通过独立测试与 100k DiffTest，默认编译选项保持不变 |
| 补丁 after seed1 与旧 seed7 | [TNO0036](./TNO0036_patched_after_seed1_walltime_20261111.md) | 8 对全部通过；Host 17.527 → 23.552 s，补丁 seed1 慢 34.366%，CI [+33.066%, +35.717%] |
| before 与补丁 after 及最终核验 | [TNO0037](./TNO0037_before_vs_patched_after_walltime_20261111.md) | Host 11.221 → 23.174 s，after 慢 106.545%；两组共 41 次运行全部通过 |
| after seed7 编译器同窗口对测 | [TNO0038](./TNO0038_after_seed7_compiler_sensitivity_20261111.md) | Clang 19 → 23：17.024 → 17.347 s，+1.899%；与 before 的 −30.324% 不同，慢分区未获得类似收益 |
| 编译器差异的热点采样 | [TNO0039](./TNO0039_compiler_hotspot_sampling_20261111.md) | before 热点为 DiffTest RAT 长 mux，after 转为向量译码；四份 binary 硬件采样通过 |
| 公共下沉优化的因果定位 | [TNO0040](./TNO0040_priority_mux_sinking_cause_20261111.md) | 28 个对象双向交换几乎交换整机快慢；Clang 23/no-sink 恢复慢路径，实际 mux 调用与深度一致 |
| 向量译码共享输入掩码 | [TNO0041](./TNO0041_vector_decode_reduction_masks_20261111.md) | 通用 emitter 规则与 sanitizer 功能门；冻结 seed7 源码原型 2 对诊断约 −19%，正式验收另记 |
| 向量译码正式生成与功能门 | [TNO0042](./TNO0042_vector_decode_generated_functional_gate_20261111.md) | 仅 46 个 C++ 文件变化；49,143 个实际谓词的 6.64 亿次比较与完整 DiffTest 通过 |
| 向量译码正式 walltime | [TNO0043](./TNO0043_vector_decode_masks_walltime_20261111.md) | 8/8 更快；Host 16.275 → 13.655 s（−16.10%），外部 walltime −16.00%，CI 均低于零 |
| 默认启用前的收益边界 | [TNO0044](./TNO0044_reduction_mask_default_profitability_guard_20261111.md) | 发现重复谓词的 pack 成本退化，增加至少 16 个不同谓词的收益门，再做跨图验证 |
| before seed2 无变化门 | [TNO0045](./TNO0045_before_seed2_mask_nonregression_20261111.md) | 7,857 个源码/头文件和最终 binary 均逐字节相同，新规则未改变 before 的运行代码 |
| after seed1 跨分区验证 | [TNO0046](./TNO0046_after_seed1_mask_nonregression_20261111.md) | 同一 Clang 修正对象；8 对 Host −32.50%、外部 walltime −32.37%，22 次运行通过 |
| 默认开启与最终回归 | [TNO0047](./TNO0047_reduction_masks_default_enabled_20261111.md) | 增加不同谓词收益门后默认开启；默认/on、显式关闭、父规则隔离和 23 项 Python 测试通过 |
| part_18 剩余热点归因 | [TNO0048](./TNO0048_part18_remaining_hotspots_20261111.md) | 两次硬件采样与源码映射确认宽 concat→OR、短字段译码仍有成本；入口空 batch 占 59.26% |
| part_18 调用前检查对照 | [TNO0049](./TNO0049_part18_dispatch_guard_control_20261111.md) | 仅一个 eval 对象变化；22 次运行通过，8 对 Host −0.03%、CI 跨零，不更改默认配置 |
| 宽局部 concat 与归约融合 | [TNO0050](./TNO0050_wide_concat_reduction_implementation_20261111.md) | 通用 emitter 扩展；宽字段、极性、用途回退及开关边界的 Clang 23 ASan/UBSan 测试通过 |
| 宽归约 after seed7 验收 | [TNO0051](./TNO0051_wide_reduction_seed7_walltime_20261112.md) | 296 处融合、440,372 组实际表达式比较通过；8 对 Host −2.98%，part_18 eval 中位数 −5.20% |
| 宽归约 before seed2 回归 | [TNO0052](./TNO0052_wide_reduction_before_nonregression_20261112.md) | 65 处融合；22 次运行通过，Host −0.41%、CI 跨零，未观察到稳定退化 |
| 宽归约 after seed1 回归 | [TNO0053](./TNO0053_wide_reduction_after_seed1_nonregression_20261112.md) | 同一 Clang 修正对象；285 处融合，22 次运行通过，8 对 Host −4.19%、CI 全低于零 |
| 宽归约默认开启与最终验证 | [TNO0054](./TNO0054_wide_reduction_default_enabled_20261112.md) | 三组共 66 次运行通过；默认/on、显式关闭、父规则隔离及源码身份检查通过，标准 preset 已开启 |
| 当前 after 热点复核 | [TNO0055](./TNO0055_after_current_hotspots_20261112.md) | 新采样与等机器码源码映射：seed7 仍以 part_18 为先，part_19 输入变化/激活、part_23 宽 copy/update 为后续重点 |
| 短字段条件共享输入词 | [TNO0056](./TNO0056_short_predicate_masks_implementation_20261112.md) | 通用 emitter 实现；独立字段、谓词数量和复用收益门，功能与性能验收另行记录 |
| 短条件 after seed7 验收 | [TNO0057](./TNO0057_short_predicates_seed7_walltime_20261112.md) | 456 个范围、1.25 亿次表达式比较通过；8 对 Host −6.93%，part_18 eval −10.67%，开始接近 part_19 |
| 短条件收益门修正 | [TNO0058](./TNO0058_short_predicate_profitability_revision_20261112.md) | 初始 before +0.78%，不默认采用；最小不同谓词数收紧到 128，重新做无变化/功能/性能验收 |
| 短条件 before 回退验收 | [TNO0059](./TNO0059_short_predicates_before_identity_20261112.md) | 128 谓词门命中 0 范围；7,857 个 source/header 与 binary 均和基线完全一致 |
| 收紧短条件 seed7 验收 | [TNO0060](./TNO0060_short_predicates_strict_seed7_walltime_20261112.md) | 51 个范围；22 次功能/放置门通过；8 对 Host −2.20%，CI [−2.80%, −1.49%]，part_18 仍最慢 |
| 收紧短条件 seed1 验收 | [TNO0061](./TNO0061_short_predicates_strict_seed1_walltime_20261112.md) | 43 个范围；保持同一 Clang 修正；22 次功能/放置门通过，8 对 Host −2.53%，CI [−3.03%, −2.05%] |
| 短条件收紧版默认开启 | [TNO0062](./TNO0062_short_predicates_default_enabled_20261112.md) | 采用 128 不同谓词门；before 内容不变、两个 after 稳定收益；112 个默认/显式模式生成文件一致，保留关闭选项 |
| 短条件收益门动态复查 | [TNO0063](./TNO0063_short_predicate_cost_diagnosis_20261112.md) | before 原 binary 复测 +0.04%，CI 跨零；多数范围实际计算改善，改用公共因子后的成本筛选候选 |
| 短条件成本门实现 | [TNO0064](./TNO0064_short_predicate_factored_cost_implementation_20261112.md) | 为 16–127 谓词集合估计公共因子复用后成本；196 范围候选两对改善约 3.18%，正式验收另记 |
| 短条件成本门正式验收 | [TNO0065](./TNO0065_short_predicate_factored_cost_walltime_20261113.md) | seed7 相对 128 门再快 3.21%，相对未启用短条件总改善 5.21%；seed1 相对 128 门再快 2.10%；before 完全回退 |
| 当前 RepCut 瓶颈与下一步方向 | [TNO0066](./TNO0066_current_repcut_bottleneck_and_next_direction_20261113.md) | 最慢路径转为 part_19 输入变化/激活、part_23 更新和三阶段 worker barrier；下一步先隔离 GrhSIM load barrier |
| RepCut load phase Host-only 对照 | [TNO0067](./TNO0067_repcut_load_barrier_ablation_20261113.md) | Host-only load 变慢 3.41%，input_load 增加 91.7%；拒绝该方案，下一步诊断 phase barrier tail |
| RepCut phase tail 诊断 | [TNO0068](./TNO0068_repcut_phase_tail_diagnosis_20261113.md) | normal eval/update 约 75% 为最长 lane 等待；下一步做 part_18/19/23 局部 partition rebalance |
| RepCut 局部分区重平衡候选 | [TNO0069](./TNO0069_repcut_local_partition_rebalance_20261113.md) | part18 -> part17 通过完整 gate，8 对 Host −1.739%、外部 wall −1.734%，CI 全部低于零；新的 critical lane 为 part_19 |
| RepCut part18 -> part22 候选复测 | [TNO0070](./TNO0070_repcut_part18_to_22_candidate_20261113.md) | 两组 8 对平均更快但 Host/wall CI 跨零；part_22 变重，未采纳，part18 -> part17 仍为最佳候选 |
| 代码整理与新分支检查点 | [TNO0071](./TNO0071_cleanup_and_branch_checkpoint_20261113.md) | 四个代码仓库统一切新分支；保存通用优化和回归测试，停止手动 swap/运行后选优，历史候选不进入默认配置 |

### 2026-11-11 源内容审计与 before 分区重试完成

历史标准 pipeline 与当前 before 的 2,097 个生成 Verilog 中，44 个内容不同；除断言行号、Git 常量和命名变化外，还有表达式与连接/日志顺序变化，详见 [TNO0026](./TNO0026_historical_before_verilog_content_20261111.md)。因此两者不能视为同一份 RTL。

复用当前 before 冻结图重跑 seeds 0–7，选中新 seed2。node030、CPU96–127、NUMA1、ASLR disabled、完整 DiffTest 下，两组各 8 对 AB/BA 均通过：相对原 initial 快 **8.479%**；相对原 retained 快 **8.548%**，95% CI **[−9.433%, −7.658%]**，Host 均值 17.881 → 16.351 s。全部 41 次运行通过功能与 placement 门。重试找到更快方案，但没有恢复历史 10–12 秒水平；详细结果见 [TNO0027](./TNO0027_before_partition_retry_20261111.md)，原基线保持归档。

### 2026-11-11 同一 seed2 使用 Clang 23 完成对测

固定 seed2 的全部生成 C++，模型及 DiffTest harness 改用 Clang 23.1.2 重编译，在相同 CPU96–127/NUMA1/ASLR-disabled 条件下完成 8 对 AB/BA。Host 均值 **16.370 → 11.405 s**，配对变化 **−30.324%**，95% CI **[−30.698%, −29.884%]**，8/8 更快；外部 walltime **16.460 → 11.496 s**，下降 **30.154%**。22 次运行全部通过完整 DiffTest、功能签名和 placement 门。结果回到历史标准 pipeline 的 11 秒量级，说明编译器版本是重要变量，详见 [TNO0028](./TNO0028_seed2_clang23_recompile_20261111.md)。

### 2026-11-11 三组前后版本统一 Clang 23 完成复测

六份 emulator 的冻结生成模型和对应 DiffTest harness 均重新使用 Clang 23.1.2 编译，node030、CPU96 / CPU96–127、NUMA1、ASLR disabled、完整 DiffTest，各 8 对 AB/BA。

| 模拟器 | before / after Host 均值 | after 配对 delta | 95% CI |
| --- | ---: | ---: | ---: |
| GSIM 单核 | 78.974 / 106.913 s | +35.378% | [+35.129%, +35.615%] |
| GrhSIM 单核 | 110.015 / 140.255 s | +27.489% | [+27.066%, +27.963%] |
| RepCut GrhSIM 32 线程 | 11.702 / 17.883 s | +52.845% | [+51.392%, +54.038%] |

三组均 after 8/8 更慢。全部 70 次功能、验证、预热及计时运行通过，没有拒绝样本。RepCut before 使用新 seed2，after 沿用原 retained seed7，因此包含既有分区选择差异。详细口径及产物见 [TNO0029](./TNO0029_all_clang23_rebuild_protocol_20261111.md)、[TNO0030](./TNO0030_clang23_repcut_merge_comparison_20261111.md)、[TNO0031](./TNO0031_clang23_gsim_merge_comparison_20261111.md)、[TNO0032](./TNO0032_clang23_native_merge_comparison_20261111.md)，[综合 JSON](../../build/artifacts/kunminghu-v3-clang23-retest-20261111/report.json)。

### 2026-11-11 after 重分区未通过功能门

after 也复用冻结图重跑 seeds 0–7，选中新 seed1，`km1` 降低 3.66045%。Clang 23 构建完成，但在 95,577 guest cycles、PC `0x800010de` 出现 `a4` 的 NEMU mismatch；两次 32 线程复跑及同一 32 分区 binary 的单线程执行均在相同位置重现。新方案被功能门拒绝，两个计划的 8 对测量未启动，原 seed7 retained 保持不变。[TNO0033](./TNO0033_after_partition_retry_protocol_20261111.md) 记录求解，[TNO0034](./TNO0034_after_retry_difftest_rejection_20261111.md) 记录可复现失败及证据。

### 2026-11-11 after seed1 编译器根因确认

故障定位到 Clang 23.1.2 编译的 `grhsim_Gpart_2_model_sched_77.o`。固定全部源与 harness，单独重编该对象为 Clang 19 O3、Clang 23 O0 或 no-SLP 均通过。独立 C++ 进一步证实 8 位有效谓词被按 16 位右移，逻辑向量之外的位污染了最后一个 select；只修正一条指令、改变 `.text` 一个字节，完整 100k DiffTest 即通过。该机制与历史变化归约的 store/load 错序不同。详细证据见 [TNO0035](./TNO0035_after_seed1_clang23_mask_codegen_20261111.md)。原失败产物、旧 retained 和默认编译选项均保留，本轮没有正式性能结果。

### 2026-11-11 用户授权补丁 binary 的正式性能对照

采用单字节修正的 seed1 binary，重新完成严格功能与放置门，两组各 8 对 AB/BA；共 41 次运行通过，拒绝 0 次。node030、CPU96–127、NUMA1、ASLR disabled、CoreMark 100k、完整 DiffTest。

| 对照 | 基线 / 补丁 after Host 均值 | 配对 delta | 95% CI |
| --- | ---: | ---: | ---: |
| old after seed7 → patched seed1 | 17.527 / 23.552 s | +34.366% | [+33.066%, +35.717%] |
| before seed2 → patched after seed1 | 11.221 / 23.174 s | +106.545% | [+104.923%, +107.990%] |

两组补丁 after 均 8/8 更慢；外部 walltime 同方向。主要差距在 `part_eval`。静态 `km1` 更低的新分区没有带来收益，继续保留原 after seed7；默认编译选项未修改。详见 [TNO0036](./TNO0036_patched_after_seed1_walltime_20261111.md)、[TNO0037](./TNO0037_before_vs_patched_after_walltime_20261111.md) 和 [综合报告](../../build/artifacts/repcut-after-seed1-patched-perf-20261111/report.json)。

### 2026-11-11 after seed7 的 Clang 19/23 直接配对

固定原 after seed7 的相同生成 C++，直接使用两份现有 binary 完成同窗口 8 对 AB/BA，22 次运行全部通过。Clang 19 / 23 的 Host 均值为 **17.024 / 17.347 s**，Clang 23 **慢 1.899%**，95% CI **[+1.225%, +2.458%]**，8/8 更慢。它没有复现 before seed2 的 30.324% 加速：before 的几个较慢分区提速超过 60%，after 的主要慢分区 part_8 / part_18 则未改善。该响应差异已由分区计时确认，具体 LLVM pass 尚未定位。详见 [TNO0038](./TNO0038_after_seed7_compiler_sensitivity_20261111.md)。

### 2026-11-11 编译器差异的进一步因果定位

硬件采样将 before 收益集中到 28 个含 DiffTest RAT 长 mux 的对象。Clang 23 的 SimplifyCFG 公共下沉将独立数据读取合并，并使常见未命中路径顺序执行；双向交换这 28 个对象几乎交换完整仿真的快慢，单独关闭这些对象的 common sinking 也恢复慢路径。代表 batch 每条链调用 67,238 次，仅 1 次命中，两版计数一致。after 已没有 511/520 级链，热点转向大型向量译码布尔逻辑。控制实验完整 DiffTest 通过；1 次 locality 拒绝样本独立保留，默认配置未修改。详见 [TNO0039](./TNO0039_compiler_hotspot_sampling_20261111.md)、[TNO0040](./TNO0040_priority_mux_sinking_cause_20261111.md)。

### 2026-11-11 向量译码归约优化

[TNO0041](./TNO0041_vector_decode_reduction_masks_20261111.md) 记录共享 Boolean 输入掩码的通用 emitter 规则、Clang 23 sanitizer 功能测试和冻结 seed7 的源码原型。原型 2 对诊断显示方向有效，正式生成和 8 对验收另行记录。

正式生成已完成：[TNO0042](./TNO0042_vector_decode_generated_functional_gate_20261111.md) 的源内容审计、实际表达式等价检查和完整 DiffTest 全部通过。[TNO0043](./TNO0043_vector_decode_masks_walltime_20261111.md) 的 8 对结果为 Host **−16.0962%**，95% CI **[−16.8202%, −15.3548%]**；外部 walltime **−16.0028%**。原热点 `part_8` eval 中位数下降 59.52%，瓶颈转到 `part_18`。规则作为显式选项保留，默认配置未修改。

### 2026-11-11 默认策略的后续变更

完成边界和跨图验证后，掩码规则已默认开启，并保留显式关闭选项。验证中发现重复谓词可能退化，已增加至少 16 个不同谓词的收益门；before seed2 源码和 binary 完全不变，after seed1 的 8 对 Host time 降低 32.50%，功能与放置门全部通过。详见 [TNO0044](./TNO0044_reduction_mask_default_profitability_guard_20261111.md) 至 [TNO0047](./TNO0047_reduction_masks_default_enabled_20261111.md)。

### 2026-11-11 part_18 剩余瓶颈

对已优化 after seed7 的两次硬件采样与等机器码源码映射表明，compute 成本分散，仍有宽 concat→OR 和短字段条件反复展开。活动计数发现 59.26% compute 调用入口为空，但只改 part_18 调用前检查的 8 对对照没有稳定收益（Host −0.03%，CI [−1.96%, +1.58%]），22 次运行全部通过。下一入口优先为宽局部归约融合；本轮不修改默认配置。详见 [TNO0048](./TNO0048_part18_remaining_hotspots_20261111.md)、[TNO0049](./TNO0049_part18_dispatch_guard_control_20261111.md)。

### 2026-11-12 宽归约融合完成并默认开启

对局部宽 concat 的归约用途进行融合后，after seed7 的 8 对 Host time 下降 **2.98%**，part_18 eval 中位数下降 **5.20%**；独立 after seed1 下降 **4.19%**。before seed2 未观察到稳定退化（−0.41%，CI 跨零）。三组共 66 次运行通过完整 DiffTest 与放置门，默认/on、显式关闭和 parent-off 源码检查通过。现已随父规则默认开启，标准 preset 显式记录 `WOLVRIX_GRHSIM_WIDE_CONCAT_REDUCTION=1`。详见 [TNO0050](./TNO0050_wide_concat_reduction_implementation_20261111.md) 至 [TNO0054](./TNO0054_wide_reduction_default_enabled_20261112.md)。

### 2026-11-12 短条件共享掩码收紧版默认开启

初始 16 谓词门在 before 上观察到约 0.78% 退化，因此收紧为至少 128 个不同谓词。最终 before 的 7,857 个 source/header 与 binary 完全不变；after seed7 和 seed1 的 8 对 Host time 分别改善 **2.20% / 2.53%**，置信区间均低于零，44 次功能与放置检查全部通过。默认/显式模式的 112 个生成文件内容核对通过，现已默认开启并保留关闭选项。part_18 仍是 seed7 最慢累计 eval 分区。详见 [TNO0058](./TNO0058_short_predicate_profitability_revision_20261112.md) 至 [TNO0062](./TNO0062_short_predicates_default_enabled_20261112.md)。

### 2026-11-13 代码整理与分支切换

父仓、Wolvrix、XiangShan、difftest 均已切换到 `thj/kunminghu-v3-grhsim-cleanup-20261113`；此前记录中的分支名保留为历史状态。按最新要求，手动 swap 和根据运行结果选择候选的工作已停止；TNO0069/70 的候选只作历史归档，不进入默认 assignment。代码整理、parser 回归修复和提交检查点见 [TNO0071](./TNO0071_cleanup_and_branch_checkpoint_20261113.md)。

### 2026-11-14 标量 concat 归约父规则默认开启

直接调用 emitter 时，父规则默认开启相对显式关闭，在同一份 after `DefaultConfig` 图上进行 node030 CPU96 单核 GrhSIM 对测。8 对 AB/BA 的 Host time 从关闭版 143.065 s 降至开启版 128.792 s，默认开启相对关闭 **−9.977%**，95% CI **[−10.230%, −9.735%]**；外部 walltime 同方向。两组 100k trace 逐字节相同，placement/locality gate 全通过。详见 [TNO0072](./TNO0072_scalar_concat_reduction_parent_default_20261114.md)。
