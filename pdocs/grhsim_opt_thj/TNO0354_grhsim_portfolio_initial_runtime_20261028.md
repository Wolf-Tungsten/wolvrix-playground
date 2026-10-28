# TNO0354：八份择优初解相对同编译恢复版的运行结果

日期：2026-10-28。承接 [TNO0353 构建检查](./TNO0353_grhsim_portfolio_selected_build_gate_20261028.md)。本篇比较自动选择的 seed 1 初解与相同 no-SLP 编译设置的恢复版；尚未施加后续自动迁移。

## 条件与检查

node030 CPU96–127，N=K=32，C=100000，all-spin、push、preferred NUMA1、ASLR disabled、完整代码 THP、64B compute 对齐。baseline/candidate 均在本轮交错重测，8 对 AB/BA；全部成功样本保留，未按外部负载或离群值过滤。

两个 C100 smoke 和 16 个 C100000 样本全部功能通过，18/18 次完整 THP 覆盖核验通过。运行时配置确认为 32 lanes / 31 background workers / Host 参与一个 lane。此阶段生成、计划及编译任务已经结束。

## 结果

百分比为逐对 candidate / baseline 变化的中位数，不等于两列独立中位数的比值。

| 指标 | 同编译恢复版 | seed 1 初解 | 配对变化 |
|---|---:|---:|---:|
| 进程 walltime | 9.785 s | 10.350 s | +5.518% |
| Host | 9.7185 s | 10.2675 s | +5.531% |
| 全局 eval | 38.514 µs | 41.374 µs | +7.457% |
| 全局 update | 6.6585 µs | 6.3865 µs | −4.085% |
| 最大分区平均 eval | 24.6895 µs | 29.4215 µs | +18.759% |
| 各分区 eval 之和 | 554.588 µs | 540.8325 µs | −2.496% |
| 各分区 update-push 之和 | 78.329 µs | 70.2095 µs | −10.262% |

新初解 walltime 0/8 获胜，所有配对变化为 +5.076% 至 +6.551%；AB/BA 分别 +5.496% / +5.635%。因此本轮不能替代恢复版。

择优后的 full km1=27,912,141 接近恢复版最终分配的 27,752,000，但 km1 接近不能保证 walltime 接近。新初解减少了一些总开销，最长分区平均 eval 却上升；这支持继续用其自身逐步 trace 选择修整候选，而非仅按 km1 判断运行收益。平均分区峰值也不能替代逐步关键路径。

## 后续与边界

自动流程继续对这份新初解采集四次 C100000 trace，由工具自动选择来源、piece 和目的分区，按原通信预算与预测改善排序；本轮不手工指定端点。自动迁移结果及与历史原始二进制的对照另记。

本篇 baseline 是控制 `-fno-slp-vectorize` 的恢复版，不能将本篇差值等同于相对历史原始恢复版的差值，也不能与旧窗口的秒数相减。

原始数据：[summary](../../build/grhsim_portfolio8_followup_20261028/reference_vs_initial/summary.json)、[逐对数据](../../build/grhsim_portfolio8_followup_20261028/reference_vs_initial/runs.csv)、[运行清单](../../build/grhsim_portfolio8_followup_20261028/reference_vs_initial/manifest.json)、[THP 核验](../../build/grhsim_portfolio8_followup_20261028/reference_vs_initial/thp_verification.json)。
