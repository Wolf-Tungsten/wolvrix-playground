# compute-partition 专题索引

主题：GRHSIM AM Compute Graph 的分区算法研究——以 split-am-graph 阶段原生拆出的
compute 图为切入点（语义上与 gsim 打平图同构），对齐量化指标，改进
partition-am-compute-graph 的分区质量（主指标：同等超节点数下跨超节点 value 数，
沿用 supernode-align NO0012 的 compute_network 口径）。

管理规则见 [../RULES.md](../RULES.md)。

## 记录索引

| 编号 | 标题 | 日期 | 内容摘要 |
|---|---|---|---|
| [NO0001](NO0001_split后compute_AM图与gsim打平图量化基线_20260806.md) | split 后 compute AM 图与 gsim 打平图量化基线 | 2026-08-06 | split-am-graph 新增 compute/commit 图原生导出；节点规模两图基本相当（3.06M vs 3.04M）；生产划分 2.96x 差距主因是粒度与划分器截断行为而非图结构——同分区器同块数下 AM 图不差（28k 块 0.70x）；出度≥2 规模 2.37x 是主要结构差 |
| [NO0002](NO0002_细粒度截断归因与DP后局部移动精化_20260806.md) | 细粒度截断归因与 DP 后局部移动精化 | 2026-08-06 | 归因坐实：分区器细粒度失效 ~4.5x 为主因、图结构 ~1.42x；DP 后确定性局部移动精化（精确 incoming 增量 + 拓扑硬约束）落地，cap=128 cross_values −1.6%、生产模型 detector/激活边同步下降；结论：截断是切分算法族的结构性问题，需连通性导向分区算法才能根治 |
| [NO0003](NO0003_AM_fanout偏大微观归因_20260806.md) | AM fanout 偏大微观归因 | 2026-08-06 | AM fanout 大不是控制广播（两侧相当 +0.6%），而是出度 2-3 小扇出多 2.4 倍：守卫逻辑族（and/logic_and，excess 45%）+ mem.read 36x + slice 族 18%；~58% excess 属图形级 pass 可攻击面（守卫链合并/assign 消除/NOT 吸收）；同名对照 13/7/0 佐证 AM 结构性更散 |
| [NO0004](NO0004_gsim风格连通性分区算法移植_20260806.md) | gsim 风格连通性分区算法移植 | 2026-08-06 | 破除两误解：gsim 的 refine 与 rep 都不起作用，关键是激进 coarsen（宿主上限 7000 + 同前驱集兄弟合并）+ Kernighan 边割 DP；离线复刻验证后 C++ 移植替换旧 coarsen+segment DP（精化保留）：cap=128 cross_values 389,508（−24.9%，2.19x）、块数 −14.2%、detectors −19.5%、cap46 −31.2% |
| [NO0005](NO0005_图形级fanout收敛pass_20260806.md) | 图形级 fanout 收敛 pass | 2026-08-06 | 仿真证伪"守卫链=CSE 去重"（仅 4.5k 合并）；落地 stateReadAlias/logicUnify/muxNotAbsorb/sliceFuse 四 pass（重写表框架）：ge2 −25.2k（2.27x）、cross_values 434,458（−5.5%，2.44x）；difftest 抓到 identity-slice 缺 commit 保护（131 处）并已修复验证；剩余 excess 边界：when→mux 展开需 cond-form 裁决、mem.read 需 mem2reg |
