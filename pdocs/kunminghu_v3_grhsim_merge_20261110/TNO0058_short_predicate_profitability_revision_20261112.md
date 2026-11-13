# TNO0058：短条件规则的 before 退化与收益门收紧

日期：2026-11-12（America/Los_Angeles）。初始规则见 [TNO0056](./TNO0056_short_predicate_masks_implementation_20261112.md)，seed7 的收益见 [TNO0057](./TNO0057_short_predicates_seed7_walltime_20261112.md)。本篇保留跨图发现的问题，不用后续候选覆盖旧结果。

## 初始门的 before 对照

初始短规则要求至少 16 个不同谓词和足够输入复用。before seed2 命中 39 个范围、17 个 C++ 文件；全部 header/layout、活动范围顺序和原长字段 pack 均不变。

在 node030、CPU96–127、NUMA1 bind、ASLR off、相同 performance 配置、Clang 23、CoreMark 100k、完整 DiffTest 下，双方各完成 smoke、验证、预热和 8 对 AB/BA。22 次全部通过功能与放置门，没有拒绝样本。

| 指标 | A 均值 | B 均值 | 配对变化 | bootstrap 95% CI | B 更快 |
|---|---:|---:|---:|---:|---:|
| Host time | 11.373375 s | 11.460750 s | **+0.7752%** | **[+0.0037%, +1.4702%]** | 2/8 |
| 外部 walltime | 11.454473 s | 11.541945 s | **+0.7705%** | **[+0.0031%, +1.4649%]** | 2/8 |

区间下沿接近零，但该结果不满足“不观察到退化后默认开启”的要求。因此不默认启用初始门，也不丢弃这些样本。详情见 [before-report.json](../../build/artifacts/repcut-short-reduction-20261112/before-report.json) 和 [逐对数据](../../build/xs/repcut-short-reduction-20261112/measure-before/pairs.json)。

## 通用收益门修正

审计实际匹配集合后，before 的 39 个集合为 19–116 个不同谓词。after seed7 的 456 个集合为 16–374 个；其最明显的 part_18 译码热点含 337 个不同谓词。

将短条件最小不同谓词数提高到 **128**，其他安全边界不变，原长字段门仍为 16。这个修正选择更密集的短条件族，明确接受覆盖减少的代价，不引入模块名、opcode、revision 或分区编号条件。

按已生成集合预审：

| 图 | 初始范围数 | 128 门保留范围 | 保留不同谓词数 |
|---|---:|---:|---:|
| before seed2 | 39 | 0 | 0 |
| after seed7 | 456 | 51 | 13,496 |
| after seed1 | 455 | 43 | 11,600 |

这些只是静态候选数量，尚不是性能结论。重新发射后需要确认 before 的全部 source/header 和 binary 与基线相同，after 两个分区需要重新做完整功能门与 8 对计时。不能沿用初始门的 −6.93% 作为最终门的收益。

focused 测试同步增加 127/128 个不同谓词边界，重复同一谓词不能通过该门；继续覆盖 4/15 字段和重复字段、写入/副作用/跨用途回退、64/65 输入、父规则隔离。新旧实验分别归档到 `strict-generated`、`before-strict`、`after1-strict`。

- [匹配集合规模审计](../../build/artifacts/repcut-short-reduction-20261112/profitability-scopes.json)
- [严格门生成脚本](../../build/artifacts/repcut-short-reduction-20261112/strict_build.py)、[跨图脚本](../../build/artifacts/repcut-short-reduction-20261112/strict_cross_build.py)

## 验收边界

收紧门并不能保证任意电路获益。本次要求在已知旧图上取消所有新改写，并在两个 after 分区上实际复测；只有结果通过才更改默认策略。初始版 after seed1 的完整对照仍继续收尾，其结果保留为初始门的记录。

## 增量记录：初始门 after seed1 对照完成

初始门在 after seed1 改写 144 个 C++ 文件、455 个范围。保留同一 Clang 修正对象，双方各完成 smoke、100k 验证、预热和 8 对 AB/BA；22 次运行全部通过完整 DiffTest、固定功能签名和放置门，没有拒绝样本。

Host time 从 15.009500 s 降到 14.297375 s，配对变化 **−4.7397%**，95% CI **[−5.2692%, −4.1424%]**，8/8 对更快。外部 walltime 从 15.112315 s 降到 14.398594 s，配对变化 **−4.7179%**，95% CI **[−5.2563%, −4.1204%]**。

这是初始 16 谓词门的结果，不能代替 128 门的验收，也不能抵消 before 已观察到的退化。原始记录见 [after1-report.json](../../build/artifacts/repcut-short-reduction-20261112/after1-report.json) 和 [逐对数据](../../build/xs/repcut-short-reduction-20261112/measure-after1/pairs.json)。
