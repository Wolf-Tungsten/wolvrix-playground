# grhsim-ir-module-attribution

模块级仿真耗时归因：从 GRH IR flatten 起为每个 op 挂来源模块路径属性，经变换语义保持传递至 grhsim IR，导出 P_general 阶段每个超节点的 op 来源清单，配合超节点级运行时插桩，得到模块级耗时归因，用于与 SV/Chisel 语义对照的微观性能分析。

## 文档

- [20261022-implementation-plan.md](20261022-implementation-plan.md) — 总体实施规划（属性设计、传递规则、manifest 导出、运行时插桩、多来源耗时分摊模型、来源构成实证验证、里程碑）
- [20261022-m7-e2e-record.md](20261022-m7-e2e-record.md) — M7 端到端验证记录（编译耗时、H1/H2/H3 假设检验、带探针运行时、开销）

## 核心问题

超节点耗时 T 已知（插桩实测），但超节点内 op 可能来自多个模块，T 如何分摊到模块？见规划文档 §6。
