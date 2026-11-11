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
