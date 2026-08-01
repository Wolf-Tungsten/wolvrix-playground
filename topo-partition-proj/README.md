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
| [docs/15-am与gsim打平dag规模对比.md](docs/15-am与gsim打平dag规模对比.md) | AM 图 vs gsim 打平图同口径规模对比：gsim 节点 0.65x / def_use 0.54x；AM incoming_copy_cost 是 gsim DP 的 4.95 倍 |
| [docs/16-同一规范化dp下am与gsim打平cost对比.md](docs/16-同一规范化dp下am与gsim打平cost对比.md) | 同一规范化 DP（canonical Kahn + 段 DP capacity=128 penalty=0）：AM 图 cost 5,921,453 vs gsim 打平图 1,300,813（4.55x）——差距来自图本身性质 |
| [docs/17-gsim屏蔽coarsen的coremark50k对比.md](docs/17-gsim屏蔽coarsen的coremark50k对比.md) | 消融实验：`--no-coarsen` 后超节点 2.57x、dag_edges 1.94x、激活源 3.07x，coremark 50k 慢 2.49x——coarsen 才是 gsim 划分优势的核心（与 13 的打平实验互证） |
| [docs/18-am多出op的归因与验证计划.md](docs/18-am多出op的归因与验证计划.md) | 两步分析之第一步（图结构优势归因）：op 直方图第一刀——节点差 84% 是 logic 族（2.50x），剔除后两边 compute op 几乎相等；H1 优化流水差异（AM 未接 CSE）等假设与 T1–T6 验证计划 |
| [docs/19-gsim逐pass算子贡献与am死代码验证.md](docs/19-gsim逐pass算子贡献与am死代码验证.md) | T1 执行：gsim 逐阶段 dump 量化——logic 精简主力是 DCE（−70 万）+ 常量分析（−39 万）而非 commonExpr（−14 万）；AM 图实测 72.9 万死指令（48.7 万 logic，占 logic 差 36%）；T2 调整为 DCE/常量/CSE 三件套 |
| [docs/20-t2两级优化实施文档.md](docs/20-t2两级优化实施文档.md) | T2 执行：GRH 层（reg-to-mem 后 simplify）+ AM 层（grhsim/am/optimize DCE/fold/CSE）两级优化——指令数 −15.9%、logic 差 +1.37M→+871,433、死锥 0.3%、规范 DP −7.5%、50k difftest 全过且 host time −10%；两级终态收敛，剩余 logic 差确认非优化可消化 |
| [docs/21-t3模块级归因.md](docs/21-t3模块级归因.md) | T3 执行：模块 × 桶差表（AM loc.file × gsim fir 实例树，勾稽全等）——87.7 万 logic 差的分布：Rob 一族 31%、阵列/entry 类 26%、验证逻辑 5%；top-20 模块覆盖 77.3% |
| [docs/22-t4惯用法采样比对.md](docs/22-t4惯用法采样比对.md) | T4 执行：四种惯用法带计数实锤——I1 读选通译码树 vs mux 链、I2 SV 布尔表示层（35.2 万 AM-only）、I3 decode or-of-eq 展开（63x）、I4 entry×条件 guard 复制；doc 19 分解表修正（常量/CSE 下修、余量上修 ~87 万） |
| [docs/23-t5口径清算表.md](docs/23-t5口径清算表.md) | T5 执行、第一步收口：节点/边/cost 三层清算——可比 compute-op 口径 AM 仅为 gsim 的 1.21x（+602,060），logic 差 98% 是惯用法；净 cost 差 4.21x 的乘数链分解（1.21x 节点 → 1.91x ccvp → 4.21x cost） |
| [docs/24-i2布尔归一化与i1译码树重写.md](docs/24-i2布尔归一化与i1译码树重写.md) | I2/I1 执行：logic-normalize + onehot-to-mux 两 pass 落地（含 kAnd resize 语义护栏），探针合计 −31,256（0.71%）——便宜重写路线耗尽，剩余 logic 差是阵列形态，非局部模式可消；含 L2 生产路径接入 |
| [docs/25-数组语义路线终局.md](docs/25-数组语义路线终局.md) | 数组/向量语义路线终局：R2 独立恢复哑弹（40 族全 reset_attr）、R1 写侧匹配扩展 outcome 零变化——consolidated matcher 对香山 guard 语言证伪；诊断资产固化（reg-to-mem 组级报告、全图索引方法）；三层不可消互证 doc 23 归因 |
| [docs/26-am-coarsen消融.md](docs/26-am-coarsen消融.md) | 第二步开局：AM coarsen 消融——coarsen 在 AM 图上是负资产（cost +8.3%、runtime +19%、体积 +40%），no-coarsen 生产调度已贴规范化 DP 地板（+0.1%）；50k host time 515.4→431.6 s（累计较 E0 −25%）；AM-gsim 划分差距是图不是算法；待决：生产默认翻转 |
| [docs/27-p0数组盘点.md](docs/27-p0数组盘点.md) | P0 数组盘点（ingest 直建 memory 语义路线）：reg-to-mem 组账×log join 总账、E1 簇存量（MSHR_64 等路径索引数组零合并）、Rob.robEntries guard 形态实测分类（主流是 8 口单等式 A 类，doc 25 的 uopNum D 形态是个别字段）、reset 形态（valid 独有异步复位口）、~12.8 万寄存器从未进组；决策门 GO（v4 901,408 ops），Rob 一族实测 ~49.5 万 ops 独立佐证 |
| [docs/28-logperf核查与memory-op语义备忘.md](docs/28-logperf核查与memory-op语义备忘.md) | LogPerf "快赢"证伪：gsim 完整保留 LogPerfEndpoint（18.5 万 ops，guard 由 when 区域承载），非配置可关项；删模块是行为变更型可选项（默认不做）；备忘：kMemoryWritePort 已有逐位 mask + priority 有序写语义 |
| [docs/29-路线重锚-爆炸发生在firtool.md](docs/29-路线重锚-爆炸发生在firtool.md) | 路线重锚：逐 entry 爆炸发生在 firtool（SV 输入无数组可认），gsim 优势源于吃 FIR 聚合形态；原 P1 落空，替代路线 R-A（重生成 RTL，环境链断）/ R-B（图级重向量化，推荐）/ R-C（FIR frontend，否决）；wflags 351/352 lane 同构实证 |
| [docs/30-rb-lane重向量化pass设计草案.md](docs/30-rb-lane重向量化pass设计草案.md) | R-B lane-aggregate pass 设计：名字分组 + 同构签名 + 常量 lane 参数化（c_i==i 实证）+ masked 宽写；决策门通过——v4 全图精确汇总 1,811 组可省 901,408 ops（≥40 万门槛 2.25 倍，只低估不高估） |
| [docs/31-lane-aggregate实施与验收.md](docs/31-lane-aggregate实施与验收.md) | lane-aggregate 落地与验收：211 组/19,039 lane 合并，compute −121,785（1.21x→1.1758x），50k difftest 通过、ctest 干净；robEntries 32 族+renameBuffer 满编全收；剩余池逐项核查——≤1.10x 判据在本路线不可达（硬形态需分段算术/比较 IR 语义或 LogPerf 跳过），收尾建议与资产清单 |

## 工作方式

- 讨论驱动：思路先在 docs 里收敛，再动手写实验代码。
- 文档编号递增（03、04……），新主题开新文档，旧文档不大改，结论变化用新文档记录。
- 实验性代码 / 数据放 `exp/`（数据见 `exp/dataset/`，大规模导出文件本地保留、不入库），不进 wolvrix 生产路径。
