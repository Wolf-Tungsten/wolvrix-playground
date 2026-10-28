# TNO0338：从 Verilog 开始的结构化 memory 筛选与自动迁移流程

日期：2026-10-27。此记录固定本轮策略和生成来源；性能验收单独记录。

## 目标与边界

从 Verilog 重新 ingest，自动选择 mem-to-reg 的 memory，重新求解 32 分区，并根据这份新初解的 profile 自动选择迁移源和目标。恢复版只提供完整后端 preset 和独立的性能锚点，不提供初始 assignment 或 memory 名单。

新入口为 [`scripts/repcut_grhsim_auto_flow.py`](../../scripts/repcut_grhsim_auto_flow.py)。完整命令及参数分别保存在 [run.sh](../../build/grhsim_auto_flow_20261027_allcores/run.sh) 和 [automatic_policy.json](../../build/grhsim_auto_flow_20261027_allcores/automatic_policy.json)。入口不接受用户指定的 memory 名单、迁移源或目标分区。

Verilog 文件列表来自 `build/asc_counter_print_20260915/candidate_ingest_v1/input.f`；这是现有 RTL 输入，不是旧分区图。所有选择和后续 partitioned JSON 均从本轮 raw 图重新产生。

## CPU 与构建约定

生成、分析和编译显式设置为 node030 全部在线 CPU（0–383），并行求解/编译使用 384 个线程/作业。SSH 继承的原始 affinity `8-95,128-191,200-287,320-383` 会遗漏 96–127 和 288–319，因此不能仅用 `nproc` 判断全部核心可用。驱动会覆盖并审计 affinity。串行阶段仍只有少量核忙碌。

正式运行固定 node030 CPU96–127、32 线程、C=100000、preferred NUMA1、all-spin、ASLR off、代码 THP；先检查全部 compute 入口 64B 对齐。每组 8 对 AB/BA，双方重新运行；功能失败的数据不能计作 walltime。归档成员顺序来自候选 Makefile 的 SRCS，不按文件名字典序重新排序。

继承恢复版 `emit.json` 全部 26 项环境选项。编译兼容检查和本轮发现的 Clang 23 问题见 [TNO0339](./TNO0339_grhsim_clang23_change_reduction_20261027.md)。

## 预先固定的自动选择规则

1. 结构探针重建实际 ASC 与 memory bridge 关系，筛选不超过 32 行的 memory；按结构选出最多 10 个单切和 10 个双切，再枚举两个切集的并集。
2. 精确计算拆分后的组合锥与复制量，要求额外复制不超过原锥的 5%；按最大锥、总工作、memory 数量和确定性编号排序。memory 名称只作为结果和 mem-to-reg 的输入标识，不参与优先级。
3. 用 MT-KaHyPar 从头求解 K=32、closure-aware GrhsimV1、deterministic-quality。分区后沿用 memory-write-coalesce、reg-to-mem（enableIntent=false、VerilatorV1 profitability）。这里的 profitability 名称是与保留线相同的图变换选项。
4. 完整发射、计划对账、构建、功能验证后，采集新初解的 4 次完整逐步 trace。按关键路径 margin 自动选前 3 个源，每源最多 8 个完整 piece，每 piece 自动提最多 3 个目的地。
5. 对所有提案进行精确 assignment 评估；发送/接收 calls、bytes 的全局总量和分区峰值均不得增长。以 source-envelope 动态模型的 improving Pareto frontier 排序，取预测 step 最大 eval 最小者，依次以非端点影响数量、局部通信增量、确定性编号解平局。
6. 最多完整 replay 一个候选。第一轮 8 对要求配对 walltime 中位变化为负且至少 6/8 更快，满足后独立复测；两轮均满足才接受。没有合格候选或没有稳定改善就保留自动初解，不手工改选分区。

这些规则不等于全局最优算法；本轮检验的是自动生成路径是否完整、结果是否正确，以及实际性能达到什么水平。

## 已完成的输入和结构对账

- fresh ingestion：1231.65 s，raw JSON 3,773,541,560 B，SHA256 `29459bd5c26e15e44da1ed7a7b97168279be0e032d3acbfacd8525e4cff3baeb`。
- 结构捕获：301182 个原始 ASC、329697 个 sink、5817258 个节点；最大 closure 为 883100。
- 206 个 memory 切集经过精确评估，167 个满足预算。工具选 `combined_102`，最大 closure 616076（−30.24%），合计 899993，额外复制 16893（1.91%），形成 3 个组。
- 选出的三个 memory 均为 2 行，宽度为 281、275、359；名单见 [selection.json](../../build/grhsim_auto_flow_20261027_allcores/memory/choice/selection.json)。与历史手工集合有一项不同，没有用历史名字替换自动结果。
- mem-to-reg 图 SHA256：`97765ab6f36dff43ab7ed97f01dc123dc31b6c4ed35b5526d1835ed2ade20319`。
- 新初解 301184 个 ASC；assignment SHA256：`b723e54268f04042d5b9405d8a480806bd851c8e06b3b57e186903b1acb2a1cd`。
- 32 分区 execution-plan、10 张静态特征表完成并通过身份检查；初次构建有 7538 个对象、6937 个 compute 入口，全部 64B 对齐。

初次 C100000 功能失败已定位为编译器错误，不能据此否定自动 memory 或初解，也没有有效的初解性能结论。完整兼容构建及正式验收继续进行。

## CPU 记录补充

本轮 ingest 启动时仍继承了 SSH 的 304-CPU mask；用户指出遗漏后，对仍在运行的 ingest 进程进行了实时更正，更新后为 0–383。原始 `ingest/run.json` 保留启动 mask，未覆盖历史。实际修改记录见 [generation_affinity_correction.json](../../build/grhsim_auto_flow_20261027_allcores/generation_affinity_correction.json)；后续自动驱动在启动阶段显式重置所有线程的 affinity，初解/候选构建记录均为 384 个 CPU。
