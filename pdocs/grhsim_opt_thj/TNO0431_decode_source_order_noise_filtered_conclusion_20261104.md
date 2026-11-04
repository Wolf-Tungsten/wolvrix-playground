# TNO0431 source-order walltime 的干扰过滤与阶段结论

本轮继续使用 E 的合法 post-reg-to-mem 快照，对比内部 operation symbol 字典序（lexicographic）和按 RTL 文件/行/列排序（rtl-location）。所有候选都保持同一前端图、译码表语义、恒定折叠状态和生产编译选项；两组各 100,000 周期的 Difftest trace 均逐字节一致。

## 服务器干扰处理

node030 在本轮明显繁忙。原始样本全部保留，但不能把服务器排队或频率漂移当成代码收益。过滤规则固定为：若一对中任一版本的 `Host time` 超过 102 秒，则该对只进入“原始结果”，不进入敏感性均值；这是根据同一批次主体样本约 94–98 秒与 106/112 秒孤立峰值预先设定的宽松门限，不按候选快慢选择样本。CPU96、NUMA node1、单线程和 sibling 检查仍必须通过；过滤不替代这些门禁。

字典序 8 对原始 delta（负数代表候选更快）为：`+0.215%, +0.051%, +0.311%, -0.003%, +0.816%, -5.082%, -15.359%, -1.266%`。第 5、6 对的 E 基线分别为 `106.057s` 和 `112.387s`，明显脱离其它 E 样本，按规则排除。剩余 6 对的均值为 `+0.021%`、中位数 `+0.133%`，只有 2/6 对更快；因此原始 `-2.540%` 不能作为收益证据。

字典序第一轮独立 4 对的均值为 `-1.080%`，但区间 `[-3.163%, +1.378%]` 跨零。两轮合并后的过滤结果仍没有方向稳定性。

RTL 源位置序 4 对均未触发 102 秒过滤：delta 为 `+0.303%, -0.306%, -0.801%, +1.083%`，均值 `+0.070%`、中位数 `-0.001%`，bootstrap 区间 `[-0.554%, +0.736%]`，仅 2/4 对更快。

## 结构与性能对应关系

按 RTL 源位置排序的结构为 compute node `1,065,983`、supernode `63,148`、DAG edge `511,892`；原观察顺序为 `1,067,570 / 63,083 / 515,084`。它确实减少了节点和 DAG edge，但增加了 65 个 supernode，walltime 没有改善。字典序进一步把 compute node 降到 `1,065,897`，但过滤后也没有收益。这说明“节点数少”不能单独作为仿真成本代理，supernode 切分、批次调用、代码布局和服务器状态都必须同时测量。

产物：

- [字典序 8 对原始汇总](../../build/xs/decode_constant_investigation_20261104_v1/order-walltime-lex-v2/summary.json)
- [字典序 4 对第一轮](../../build/xs/decode_constant_investigation_20261104_v1/order-walltime-lex-v1/summary.json)
- [RTL 源位置序汇总](../../build/xs/decode_constant_investigation_20261104_v1/order-walltime-rtl-v1/summary.json)
- [顺序结构汇总](../../build/xs/decode_constant_investigation_20261104_v1/order-scan-E/structural-summary.json)

当前结论是：source order 已被证实会改变 activity-schedule 的后端结构，但在排除服务器明显干扰后，尚未显示稳定单线程 walltime 收益。后续若继续，应先使用更稳定的服务器窗口或增加交替重复，再研究按 RTL 来源排序是否能减少 supernode，而不是继续扩大随机顺序数量。
