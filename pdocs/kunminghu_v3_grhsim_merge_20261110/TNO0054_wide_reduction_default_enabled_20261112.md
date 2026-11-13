# TNO0054：宽归约默认开启与最终验证

日期：2026-11-12（America/Los_Angeles）。实现见 [TNO0050](./TNO0050_wide_concat_reduction_implementation_20261111.md)。按此前“确认其他配置不退化后默认启用”的要求，完成 after seed7、before seed2、after seed1 的独立检查后，开启宽局部 concat 归约融合。

## 默认策略

`wide_concat_reduction` 默认 true，但仍受 `scalar_concat_reduction` 父规则控制。父规则默认不变。显式设置 attribute 或环境变量 `WOLVRIX_GRHSIM_WIDE_CONCAT_REDUCTION=0` 可关闭宽扩展；attribute 优先于环境变量。

标准 [config/grhsim32.json](../../config/grhsim32.json) 显式记录宽归约为 `1`，[配置测试](../../scripts/test_grhsim32.py) 同步检查该设置。默认功能流程、performance 流程及其 CPU/NUMA/code-page 的选择策略保持原规则；此修改只影响生成模型中的局部计算表示，不自动增加运行时放置或性能测量。

最终源码还对静态 execution-plan 的 packed-lane concat 优先级补充了检查，使静态分类与实际 emitter 的先后顺序一致。这只修正诊断分类；实际 C++ lowering 条件与正式测量的显式开启版本相同。

## 默认启用依据

三组均固定各自 graph/assignment、Clang 23、CoreMark 100k、完整 DiffTest/NEMU；node030、CPU96–127、NUMA1 bind、ASLR off，每组 8 对 AB/BA。构建与计时分阶段串行执行，不做外部 CPU 空闲检查。

| 对照 | Host time 配对变化 | 95% CI | 结论 |
|---|---:|---:|---|
| after seed7 | −2.9829% | [−4.0868%, −1.9000%] | 8/8 更快；part_18 eval 中位数 −5.20% |
| before seed2 | −0.4137% | [−1.5717%, +0.5895%] | 未观察到稳定退化，区间跨零 |
| after seed1 | −4.1937% | [−4.6108%, −3.8623%] | 8/8 更快；保留原 Clang 修正对象 |

共 **66 次有效运行、24 对测量、0 次拒绝**，完整功能和 placement/locality 门通过。外部 walltime 同方向。独立结果分别见 [TNO0051](./TNO0051_wide_reduction_seed7_walltime_20261112.md)、[TNO0052](./TNO0052_wide_reduction_before_nonregression_20261112.md)、[TNO0053](./TNO0053_wide_reduction_after_seed1_nonregression_20261112.md)。before 的跨零区间不是绝对零退化证明，结论限于本轮图、编译器和负载。

## 最终检查

- 新增宽归约 focused 测试覆盖实际位宽、截断、极性、重复字段及保守回退；Clang 23/O0/O3、ASan/UBSan 通过。
- 默认切换后通过注册的 CTest `emit-grhsim-cpp-wide-concat-reduction`：default/on 一致，显式关闭、环境覆盖和 parent-off 隔离通过。
- default 切换前后的显式 on/off 各 12 个生成 source/header 的 SHA256 完全相同，测试中的 default 与 on 也相同，排除为默认切换另引入计算变化。
- 对 seed7 实际 296 个融合表达式的 440,372 组输入比较通过；保留旧 Words 实现作为参考。
- 旧标量归约、共享掩码及完整 emitter 回归通过；native replay/test 工具重新构建通过。
- 17 项 Python 测试、canonical 默认/performance Make dry-run、Python 编译、相对链接和父仓/Wolvrix `git diff --check` 通过，详情保存在最终检查 JSON。

本轮已降低 part_18 的宽打包/归约成本。它仍是较慢分区，未命中的短字段译码和条件复用留作下一独立优化；没有把本次收益外推为所有 workload、GSIM 或单核 GrhSIM 的速度结论。

## 归档

- [总报告](../../build/artifacts/repcut-wide-reduction-20261111/report.json)、[三组性能摘要](../../build/artifacts/repcut-wide-reduction-20261111/performance-summary.json)
- [检查记录](../../build/artifacts/repcut-wide-reduction-20261111/checks.json)、[最终验证](../../build/artifacts/repcut-wide-reduction-20261111/final-verification.json)
- [默认切换前的生成工具与动态库身份](../../build/artifacts/repcut-wide-reduction-20261111/emitter-provenance.json)、[最终源码身份](../../build/artifacts/repcut-wide-reduction-20261111/source-provenance.json)
- [增量补丁](../../build/artifacts/repcut-wide-reduction-20261111/implementation.patch)、[默认开关 CTest 日志](../../build/artifacts/repcut-wide-reduction-20261111/default-focused.log)
- [开关与语义文档](../../wolvrix/docs/emit/grhsim-wide-concat-reductions.md)
