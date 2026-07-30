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

## 工作方式

- 讨论驱动：思路先在 docs 里收敛，再动手写实验代码。
- 文档编号递增（03、04……），新主题开新文档，旧文档不大改，结论变化用新文档记录。
- 实验性代码 / 数据放 `exp/`（数据见 `exp/dataset/`，大规模导出文件本地保留、不入库），不进 wolvrix 生产路径。
