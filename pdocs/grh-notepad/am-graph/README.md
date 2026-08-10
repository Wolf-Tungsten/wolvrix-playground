# am-graph 专题索引

主题：grhsim AM 指令/执行模型升级与转换路径重构——在 GRH IR 与 grhsim am program 之间引入 grhsim am graph 层（instr 为 op、var 为 value；var 区分状态/非状态并补足声明语义；显式快照/破环），graph 上承载优化与调度 pass，定型后一次性生成 program 交付 emit/interpreter。硬约束：执行语义不变、香山 difftest 通过、性能不回退。

管理规则见 [../RULES.md](../RULES.md)。

## 记录索引

| 编号 | 标题 | 日期 | 内容摘要 |
|---|---|---|---|
| [NO0001](NO0001_AM执行模型升级与图重构_20260804.md) | AM 执行模型升级与图重构 | 2026-08-04 | 五条指令模型升级的落地；AmGraph 图层落地（容器/调度器过图）；锥打包两个 def-after-use 根因修复后，mem.write 回退 cond/mask（快照 vs 活读不对称），锥打包随之整体移除（保留事件签名门控 + def-before-use 硬校验 + 相位审计）；t0 错位根治，香山 difftest 73,580/49,996 通过，回退版取优 329.7s |
| [NO0002](NO0002_compute_commit分图与两路独立分区_20260806.md) | compute/commit 分图与两路独立分区 | 2026-08-06 | 分块单体式实现拆为「分图 + 两路分区 pass + 组合入口」：atom DAG 分图成 compute/commit 诱导子图，compute 按活动度 coarsen+DP、commit 按事件聚类，生产调用点显式三段；香山指令图/划分结果/发射产物全部字节级不变，AM 10/10 |
| [NO0003](NO0003_转换方向修正GRH到AmGraph到Program_20260806.md) | 转换方向修正：GRH IR → AM Graph → AM Program | 2026-08-06 | AmGraph 升为一等 IR：lowering 原生建图、optimize 移植到图、scheduler 直接消费图，线性程序只在 finalize 物化；artifact.hpp 拆型解循环依赖；香山三份产物字节级不变，AM 10/10 |
| [NO0004](NO0004_流程框架与术语统一_20260806.md) | 流程框架与术语统一 | 2026-08-06 | 用户裁定标准流程（lowering-to-am-graph → opt-am-graph → split-am-graph → opt-am-compute-graph → partition-am-compute-graph / partition-am-commit-graph → materialize → emit）已落到代码与文档：每阶段一个文件、总流程命名 GrhToGrhSimAMProgram、空阶段留钩子；香山三份产物字节级不变，AM 10/10 |
| [NO0005](NO0005_状态写指令cond-mask变体族_20260807.md) | 状态写指令 cond/mask 变体族 | 2026-08-07 | 对 NO0001 reg.write cond/mask 数据化决策的勘误性修正：写指令改显式 opcode 变体族（带/不带 cond × 带/不带 mask），lowering 按常量性选型，targetSnapshot 机制整体删除；difftest 73,580/49,996 逐位一致（双 trace 对差 35,920 条全同），host 308.8s（−4.5%），AM 指令 −79,330，ge2 2.248x，AM 12/12 |
| [NO0006](NO0006_同条件mux原子化与if-else发射_20260807.md) | 同条件 mux 原子化与 if-else 发射 | 2026-08-07 | gsim merge-when 对齐：mux-merge atom pass（归组+独占锥吸收+SCC 解合并）入驻 opt-am-compute-graph，emitter 模式融合 if-else；生产 35,109 融合结构/231,856 赋值；cap 扫描四点 difftest 全逐位一致、运行时中性；cross_values +22% 如实记录（用户裁定特性保留默认 512 开启）；AM 13/13 |
| [NO0007](NO0007_atom一等公民化与对齐口径重构_20260807.md) | atom 一等公民化与对齐口径重构 | 2026-08-07 | 证实 gsim flatten 不打平 when（粒度差异致统计/划分双重偏差）；用户三点判断落地：Program atom 层（block→atom→instruction + kind/签名）、emitter 直消费 atom（删 planMuxRuns 双机制，mux_atom_fused=227,925 精确等于归组数）、分区经济全换 atom 计权（compute 块 −12.6%）、指标 atom-as-node；P1 产物字节级不变，P2/P3 difftest 73,580/49,996 一致、host 309.7s（−1.0%）；新口径基线 2.8911x / nodes 0.8608x（supernode-align NO0013）；AM 14/14 |
| [NO0008](NO0008_atom单输出树化与mergeWhen降为coarsen_20260808.md) | atom 单输出树化与 mergeWhen 降为 coarsen | 2026-08-08 | 层级错误诊断落地为重构：atom 以单根输出折叠独占锥（when 树形态），同条件合并降为 coarsen 首 sweep（atom→cluster，带 gsim 三道门），if-else 融合回到块级 emit；确立 atom 冻结不变量公理与 atom/cluster/block ↔ node/coarsen-supernode/final-supernode 概念映射；difftest 73,580/49,996 两档一致，host 306.6s（−1.0%），默认 cap 改 48，主指标 2.89x→2.38x（cap128 2.16x）；AM 12/12 |
