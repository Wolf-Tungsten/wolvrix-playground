# TNO0355：八份择优初解的自动迁移筛选

日期：2026-10-28。承接 [TNO0354 初解运行对照](./TNO0354_grhsim_portfolio_initial_runtime_20261028.md)；采用同一 seed 1 初解的新鲜 trace，不沿用恢复版分区排名。

## 动态来源与提案

仅替换诊断 wrapper，保留初解模型 archive，完成 4 次 C100000 trace 和 2 次 C100 smoke。6 次均功能及完整代码 THP 核验通过；trace walltime 不作为普通性能结论。

剔除 reset 后共 800,008 个 step。按成为 eval 瓶颈时领先第二名的累计时间贡献，工具自动选择 p8、p9、p0；各自的每 step 平均独占 margin 为 1.445581、1.196493、0.519627 µs。这里的分区号是本轮工具输出，不是候选策略中的常量。

每来源最多 8 个结构 piece、每 piece 最多 3 个自动目的地，实际生成 51 个提案：p8 来源 24 个，p9 来源 24 个，p0 来源 3 个。原始候选及其端点均由工具选择，没有人工提交来源/目的列表。

## 精确结构门槛

51 个 assignment 全部完成精确核算。保持原有 8 条结构预算：send/receive 的 calls/bytes，各自 peak/sum 均不得超过初解。结果 eligible=0、outside_budget=51；没有可进入 improving Pareto frontier 的候选。

| 检查 | 不满足的提案数 / 51 |
|---|---:|
| send calls peak | 26 |
| send calls sum | 47 |
| send bytes peak | 30 |
| send bytes sum | 44 |
| receive calls peak | 27 |
| receive calls sum | 47 |
| receive bytes peak | 24 |
| receive bytes sum | 44 |

同一提案可能违反多条规则，不能将上表相加。也不是所有提案的每项通信都增加：其中少数提案总量下降，但另一些峰值/调用限制仍未通过。

## 取舍与限制

selected=null，最终保留本轮初解，不做迁移，不为获得一个候选临时放宽预算。本次结果表示这 51 个自动提案均未通过既有结构约束，不能据此声称所有局部迁移都无益，也不能将未实测的预测值写成性能收益。

排序仍采用 source-envelope 活动估计，未观测每个 piece 的独立活动，不预测 update 时间；这些估计不是 walltime 上界。本轮没有候选进入完整 replay/发射/编译/两轮接受测试。最终版本与历史原始恢复版二进制的独立对照继续执行，结果另记。

原始记录：[四次 trace 的 profile](../../build/grhsim_portfolio8_followup_20261028/trace_initial/profile.json)、[自动提案](../../build/grhsim_portfolio8_followup_20261028/automatic_migration/proposals/selection.json)、[精确结构报告](../../build/grhsim_portfolio8_followup_20261028/automatic_migration/evaluation/report.json)、[预算与排序](../../build/grhsim_portfolio8_followup_20261028/automatic_migration/ranking.json)、[最终取舍](../../build/grhsim_portfolio8_followup_20261028/automatic_migration/result.json)。
