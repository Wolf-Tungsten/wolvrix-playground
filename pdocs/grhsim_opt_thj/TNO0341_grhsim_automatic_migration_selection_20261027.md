# TNO0341：新初解 profile 驱动的自动迁移选择

日期：2026-10-27。规则固定于 [TNO0338](./TNO0338_grhsim_automatic_rtl_flow_20261027.md)，初解功能与性能见 [TNO0340](./TNO0340_grhsim_automatic_initial_runtime_20261027.md)。

## 数据与提案

对自动初解采集 4 次 C100000 逐步 trace，共 800008 个非 reset step。诊断 archive 只替换 4 个 RepCut wrapper 对象，保留模型对象和归档顺序，继承 `-fno-slp-vectorize`；功能及代码大页检查通过。诊断 walltime 不用于性能接受。

按 exclusive eval margin 自动选出的前 3 个来源为 p17、p16、p4；这是本轮新 assignment 的结果，不引用历史分区编号。每源 8 个 piece，每 piece 3 个按已有共享关系选择的目的地，得到 72 个候选。

精确 assignment 重建/记账完成 72/72，21 个满足预先固定的全局 send/receive calls/bytes 总量和峰值不增长约束。Pareto frontier 有 16 个，其中只有一个预测改善逐步最大 eval。

## 工具选择结果

- 候选：`piece_957948_p4_to_7`，完整迁移 1925 个 ASC；assignment diff 只含 `4 → 7`。
- 来源 work 比例：0.887273；目的地：1.105281。
- 预测平均 step 最大 eval：58.171229 → 57.807390 µs，变化 -0.625%。这是固定 trace 上的筛选估计，不是 walltime 收益。
- 静态发送总量：4743 → 4679 calls；459331 → 457687 bytes。
- 直接受包布局影响的非端点分区有 27 个；此字段参与 Pareto 排序，但预先没有把它定义成硬性拒绝阈值。不会在看到候选后人为改门槛。
- 候选 assignment SHA256：`4105835ee0c4acef761ce9dd36ec38f012478bdb78b3d277d1b4f1357b1a67f8`。

新分区图已从本轮 mem-to-reg 原始图重建通过；SHA256 为 `3b7a1c1a367aa68175a4347b2bcff58fda650dbbc98f02d64e65de337619ee75`。后续按完整 preset、相同编译兼容规则生成/编译，先功能检查，再与自动初解 fresh AB/BA。

[profile](../../build/grhsim_auto_flow_20261027_allcores/trace_initial/profile.json)、[全部提案](../../build/grhsim_auto_flow_20261027_allcores/automatic_migration/proposals/selection.json)、[精确评估](../../build/grhsim_auto_flow_20261027_allcores/automatic_migration/evaluation/report.json)、[排序](../../build/grhsim_auto_flow_20261027_allcores/automatic_migration/ranking.json)、[选择记录](../../build/grhsim_auto_flow_20261027_allcores/automatic_migration/selected.json)。
