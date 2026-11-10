# kunminghu-v3 merge 与 GrhSIM 对测

本目录按阶段记录从 XiangShan `77ed568fc` 合并上游 `kunminghu-v3`，并比较合并前后的单核 native GrhSIM 与 32 线程 RepCut GrhSIM。记录遵循追加式规则：独立阶段独立成文，原始日志和机器可读结果保留在 `build/artifacts/kunminghu-v3-grhsim-merge-20261110/`。

规则参考：[GrhSIM 文档管理规则](../grhsim_opt_thj/RULES.md)。

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
| 独立配置与配对入口 | [TNO0009](./TNO0009_reproduction_and_paired_runbook_20261110.md) | native 完成；正式 RepCut 对测中 |
| 合并 checkout 与子模块 | [TNO0010](./TNO0010_merge_checkout_completion_20261110.md) | 主 checkout 已更新；递归子模块干净 |
| harness 验证 checkpoint | [TNO0011](./TNO0011_harness_validation_checkpoint_20261110.md) | 83 项测试通过，before RepCut 48 次 100k 签名一致 |
| RepCut 无驱动信号兼容 | [TNO0012](./TNO0012_repcut_undriven_wrapper_compatibility_20261110.md) | focused emitter 测试通过；验证结果见 TNO0013 |
| Backend 一致性与 after 功能门 | [TNO0013](./TNO0013_backend_compatibility_equivalence_gate_20261110.md) | before 15,754 个 source/header 字节一致；after 8 次 100k 通过 |
| RepCut retained 构建门 | [TNO0014](./TNO0014_repcut_retained_build_gates_20261110.md) | before=candidate、after=initial；正式对测开始 |
| native 8 对 AB/BA walltime | [TNO0015](./TNO0015_native_paired_walltime_20261110.md) | after 慢 30.766%，95% CI [29.968%, 31.781%] |
| RepCut 严格 NUMA 运行 | [TNO0016](./TNO0016_repcut_strict_numa_runtime_20261110.md) | 首次 verify 因远端页拒绝；统一 membind=0 后重新对测，84 项测试通过 |
| RepCut 退出阶段监控勘误 | [TNO0017](./TNO0017_repcut_teardown_affinity_verifier_20261110.md) | 退出后 host affinity 恢复不计作运行期失败；最终系列重新采集 |
