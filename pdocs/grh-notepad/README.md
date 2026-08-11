# grh-notepad

GRH/grhsim 专题研究记录库：按专题分子目录，每个专题下是带索引的线性研究记录（`NOxxxx_主题_YYYYMMDD.md`）。管理规则见 [RULES.md](RULES.md)。

## 专题索引

| 专题 | 主题 | 开题日期 | 记录数 |
|---|---|---|---|
| [ir-scale/](ir-scale/README.md) | IR 规模优化：AM 图 vs gsim 打平图的 op 数对齐（归因 → 优化 pass → lane-aggregate → 剩余差距拆解 → 数组/when 语义扩展） | 2026-07-31 | 21 |
| [supernode-align/](supernode-align/README.md) | 超节点构造对齐：AM compute block vs gsim supernode（同等超节点数下跨超节点边数差距；NO0012 起 compute 网络口径；当前最佳 2.91x/可选 2.59x） | 2026-08-03 | 12 |
| [am-graph/](am-graph/README.md) | AM 执行模型升级与转换路径重构：GRH IR 与 program 之间引入 AmGraph 图层；含锥打包 def-after-use 修复与 t0 相位错位调查；compute/commit 分图与两路独立分区；转换方向修正（图为一等 IR） | 2026-08-04 | 3 |
| [compute-partition/](compute-partition/README.md) | GRHSIM AM Compute Graph 分区算法研究：以 split 后 compute 图（与 gsim 打平图同构）为切入点，对齐量化指标，改进 partition-am-compute-graph 分区质量 | 2026-08-06 | 4 |
| [emit-cost/](emit-cost/README.md) | 同图 emit 单位成本归因与修复：AM vs gsim 同图单位求值成本 ~21x 的因子瀑布分解与按序修复（源自 supernode-align NO0017 D 层判定：调度无罪、emit 不良）；阶段目标破 10x | 2026-08-10 | 1 |
