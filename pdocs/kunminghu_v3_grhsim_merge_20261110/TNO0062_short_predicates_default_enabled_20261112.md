# TNO0062：短条件共享掩码收紧版默认开启

日期：2026-11-12（America/Los_Angeles）。本阶段完成默认策略核对，采用至少 **128 个不同谓词**的收紧版。初始 16 谓词门的 before 退化保留在 [TNO0058](./TNO0058_short_predicate_profitability_revision_20261112.md)，没有删除或重新解释旧结果。

## 最终依据

| 冻结图 | 结果 | 验证记录 |
|---|---|---|
| before seed2 | 7,857 个 source/header、重新链接 binary 全部与原基线一致 | [TNO0059](./TNO0059_short_predicates_before_identity_20261112.md) |
| after seed7 | 8 对 Host **−2.2009%**，95% CI **[−2.8019%, −1.4895%]** | [TNO0060](./TNO0060_short_predicates_strict_seed7_walltime_20261112.md) |
| after seed1 | 8 对 Host **−2.5281%**，95% CI **[−3.0329%, −2.0491%]** | [TNO0061](./TNO0061_short_predicates_strict_seed1_walltime_20261112.md) |

两个 after 各 8/8 对更快，外部 walltime 置信区间也低于零；44 次 smoke/验证/预热/正式运行全部通过完整 DiffTest、功能签名、CPU96–127 singleton affinity、NUMA1 bind、ASLR 和 code-page 检查，无拒绝样本。保持 node030、Clang 23、CoreMark 100k，不做外部 CPU 空闲准入检查。

## 默认行为与回退

emitter 的 `short_concat_reduction_masks` 默认值改为 true；仍须父规则 `scalar_concat_reduction` 开启。标准 preset 在 `config/grhsim32.json` 显式记录 `WOLVRIX_GRHSIM_SHORT_CONCAT_REDUCTION_MASKS=1`。默认功能流程与 performance 流程的运行职责不变。

规则要求局部 concat 含 4–15 个一位字段，同一安全活动范围内至少 128 个不同 mask/family 谓词，最多 64 个稳定输入，distinct input uses 至少为输入数的四倍。重复或重排字段不能虚增不同谓词数。输入写入、未知副作用、数值用途、跨范围用途、混合 AND/OR family 和跟踪边界均保留保守回退。

显式属性 `short_concat_reduction_masks=0` 或有效生成环境中的 `WOLVRIX_GRHSIM_SHORT_CONCAT_REDUCTION_MASKS=0` 可关闭。标准流程从 preset 注入生成环境，因此使用该流程时应把对应 preset option 设为 `0`。关闭父规则也会关闭本规则。属性优先于环境变量。实现说明见 [feature 文档](../../wolvrix/docs/emit/grhsim-short-reduction-masks.md)。

## 最终检查

- native tools 与 focused test target 构建通过。
- 收紧版显式开启/关闭/父规则关闭分别在 O0/O3、ASan/UBSan 下通过全部 12,000 组输入及重复 eval；启用短规则的完整 emitter 回归通过。
- 默认策略修改后，对八种开关组合重新发射，比较 **112 个生成 C++/header**：default 等于已经测试过的 on，其余显式模式与原测试文件完全一致。由内容一致性复用既有 runtime/sanitizer 结果，没有无理由重复编译相同模型。
- Python 17 项测试、Python 编译检查、两个 canonical Make target 的 dry-run、主仓与 Wolvrix 的 `git diff --check` 通过。
- 新文档使用相对链接，README 索引同步；最终生成器、动态库、源文件、变更 patch 和所有中间实验均独立归档。

最终默认版只改变开关默认值，性能模型使用的显式开启 lowering 已冻结且不变；新行为不修改 graph、assignment、状态布局或活动传播。

## 当前剩余热点与边界

seed7 的本轮累计 eval 中位数仍为 part_18 **8.9985 s**、part_19 **8.0428 s**、part_23 **7.3336 s**。part_18 仍最慢，较小的短条件集合继续走原 lowering；不因初始广覆盖版更快就取消保护 before 的收益门。后续可以对 part_19 的输入变化检测/激活传播、part_23 的宽更新做独立实验，沿用 [TNO0055](./TNO0055_after_current_hotspots_20261112.md) 的归因边界。

本轮对三个冻结图及 CoreMark 100k 的验证不构成任意电路、任意负载都获益的保证。初始规则的 −6.93% 与最终收紧规则的 −2.20% 必须明确区分。

## 归档

- [最终机器可读报告](../../build/artifacts/repcut-short-reduction-20261112/final-report.json)
- [默认资格 gate](../../build/artifacts/repcut-short-reduction-20261112/strict-promotion-gate.json)、[默认/显式模式内容检查](../../build/artifacts/repcut-short-reduction-20261112/default-source-check.json)
- [最终变更 patch](../../build/artifacts/repcut-short-reduction-20261112/final-implementation.patch)、[冻结最终 emitter](../../build/artifacts/repcut-short-reduction-20261112/final-emitter/)、[冻结最终源文件](../../build/artifacts/repcut-short-reduction-20261112/final-source/)
- [全部原始模型和运行](../../build/xs/repcut-short-reduction-20261112/)、[工具、日志与报告](../../build/artifacts/repcut-short-reduction-20261112/)

## 增量勘误：2026-11-13

本篇原结论中的“至少 128 个不同谓词”是 2026-11-12 阶段的保守规则，不再是当前默认规则。后续 [TNO0063](./TNO0063_short_predicate_cost_diagnosis_20261112.md) 和 [TNO0064](./TNO0064_short_predicate_factored_cost_implementation_20261112.md) 增加了公共因子成本门；正式结果见 [TNO0065](./TNO0065_short_predicate_factored_cost_walltime_20261113.md)。before 仍完全回退，两个 after 仍通过完整功能和性能门。
