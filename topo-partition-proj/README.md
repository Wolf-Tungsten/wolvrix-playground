# topo-partition-proj

专题研究：**为什么 grhsim（legacy / am 两条路线）的分区效果长期不如 gsim，以及能否用"学习 + 搜索"的方法做出更好的分区**。

## 目标

为 grhsim 的 compute DAG 找到一个容量受限、无环的划分，使模拟的期望执行成本最小，并在结构上（dag_edges / boundary_activation_edges / compute_compute_value_pairs / code footprint）与运行时（XiangShan CoreMark 50k host time）同时优于现有 plain 基线。

## 文档

| 文档 | 内容 |
|---|---|
| [docs/01-问题定义与现状.md](docs/01-问题定义与现状.md) | 问题形式化、现有算法、gsim 对照、历史教训、可用资产 |
| [docs/02-技术路线讨论.md](docs/02-技术路线讨论.md) | 对"语义固定性 / GNN / 搜索+RL / 无环建模"四条思路的讨论与提案 |
| [docs/03-atom层次与comb-loop-atom.md](docs/03-atom层次与comb-loop-atom.md) | atom = 指令依赖图 SCC，实践中恒为单指令；概念收缩为 comb-loop-atom，作为不可分割节点建模其边界 |
| [docs/04-实现计划.md](docs/04-实现计划.md) | 按阶段实施计划（自足版：背景一页纸 + 全术语白话解释）：Phase 0–4 任务/验收门、D1–D12 待定细节、风险登记 |
| [docs/05-图导出实现记录.md](docs/05-图导出实现记录.md) | Phase 0 任务 1 落地记录：AM 指令图 JSONL 导出器（as-built 格式、对 D1 的三处扩展、全香山验证证据） |
| [docs/06-基线解导出与对账.md](docs/06-基线解导出与对账.md) | Phase 0 任务 2 前半：plain 基线 block assignment 导出 + 三项指标生产/独立复算对账（cost 基线 6,468,546） |
| [docs/07-harness重建与M0验收.md](docs/07-harness重建与M0验收.md) | Phase 0 任务 2 后半–5：harness 四模块（scorer/采样器/搜索器骨架/CPU 摸底）as-built、512 区域数据集、M0 验收门核对 |
| [docs/08-Phase1搜索标签与M1验收.md](docs/08-Phase1搜索标签与M1验收.md) | Phase 1：C 段 DP 内核 + 完整 SA、512 区域标签、CP-SAT gap（中位 0%）、全图 no-coarsen 基线（cost −8.5% / footprint +21.6%）与段惩罚权衡、M1 核对 |
| [docs/09-全图排序油水实验.md](docs/09-全图排序油水实验.md) | R1 预案落地：c910 导出、全图 SA（规范序起点 +0.0016% / 随机起点爬不回）、随机线性扩张零假设（+32.5%）——排序无全局油水 |
| [docs/10-确定性基线方案.md](docs/10-确定性基线方案.md) | R2 预案固化为方案：去 coarsen + 规范 Kahn + 新段 DP + λ 段惩罚；与生产算法逐项差异、两设计收益证据、footprint 红线与落地路径 |
| [docs/11-生产侧落实与50k实测.md](docs/11-生产侧落实与50k实测.md) | 方案落到生产代码：段 DP 位宽折算改动 + 选项/CLI 打通；离线指标与 harness 一致；CoreMark 50k 实测 plain 575.5s → λ=4 564.1s（−2.0%） |
| [docs/12-gsim-node打平实验设计与实现.md](docs/12-gsim-node打平实验设计与实现.md) | gsim node 层次打平逆向实验的设计与实现：`--flatten-nodes` pass（每 node 至多一个计算 enode）、rocket 功能等价验证、本机 gsim 构建环境修复与 difftest-extmodule.cpp 机械重建方法 |
| [docs/13-gsim-node打平coremark50k对比.md](docs/13-gsim-node打平coremark50k对比.md) | 打平版对齐超节点数（84,754 vs 84,642）后 coremark 50k 仅慢 3.6%、超节点间边数 +0.68%——不支持"node 层次是 activity 划分优势根因"；含打平有效性核查（0 违规；86.7% 节点本来就单算子） |
| [docs/14-gsim打平图与两段assignment导出.md](docs/14-gsim打平图与两段assignment导出.md) | gsim `--export-topo-proj`：按本仓 JSONL 格式导出打平后节点图（304 万节点，DAG 0 违序边）与 coarsen/DP 两段 block assignment，全香山 reconcile 三项全等 |
| [docs/17-gsim屏蔽coarsen的coremark50k对比.md](docs/17-gsim屏蔽coarsen的coremark50k对比.md) | 消融实验：`--no-coarsen` 后超节点 2.57x、dag_edges 1.94x、激活源 3.07x，coremark 50k 慢 2.49x——coarsen 才是 gsim 划分优势的核心（与 13 的打平实验互证） |
| [docs/26-am-coarsen消融.md](docs/26-am-coarsen消融.md) | 第二步开局：AM coarsen 消融——coarsen 在 AM 图上是负资产（cost +8.3%、runtime +19%、体积 +40%），no-coarsen 生产调度已贴规范化 DP 地板（+0.1%）；50k host time 515.4→431.6 s（累计较 E0 −25%）；AM-gsim 划分差距是图不是算法；待决：生产默认翻转 |

> **IR 规模优化专题已迁出**：原 docs 15–16、18–25、27–31（AM vs gsim op 数对齐链：规模对比 → T1–T5 归因 → I1/I2 → 数组语义 → P0 → lane-aggregate → 剩余差距拆解）于 2026-08-01 迁移至 [`pdocs/grh-notepad/ir-scale/`](../pdocs/grh-notepad/ir-scale/README.md)，按 NO0001–NO0016 重新编号（映射见该专题索引）；后续 IR 规模方向的新记录也在该专题下递增。

## 工作方式

- 讨论驱动：思路先在 docs 里收敛，再动手写实验代码。
- 文档编号递增（03、04……），新主题开新文档，旧文档不大改，结论变化用新文档记录。
- 实验性代码 / 数据放 `exp/`（数据见 `exp/dataset/`，大规模导出文件本地保留、不入库），不进 wolvrix 生产路径。
