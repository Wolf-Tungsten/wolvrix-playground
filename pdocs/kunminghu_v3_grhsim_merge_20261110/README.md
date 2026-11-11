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
