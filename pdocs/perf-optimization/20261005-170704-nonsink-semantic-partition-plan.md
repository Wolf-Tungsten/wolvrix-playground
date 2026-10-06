# 20261005-170704 非 sink 划分方法改进规划（语义节点 + 合并放松 + merge 调优）

> 规划记录，非优化项；落地后每项改动另写一条优化记录。本文是后续实验的
> 唯一入口：方案、度量、门槛、风险都在这里，实验结果回链本文。

## 元信息

- 日期：2026-10-05 / 作者：kimi（三条基础建议由作者给出，本文综合展开）
- wolvrix commit：`66000f6` + 未提交工作树（同 `20261005-002919-pmem-act-cluster-dead-compare.md`）
- 上游记录：`20261005-111210-compare-count-census.md`（比较次数普查）、
  `20261005-002919-pmem-act-cluster-dead-compare.md`（178.9s 基线模型）

## 背景与现状数据

当前基线（XS CoreMark 100k，定核，标准口径）：**178.9s**；P_general 占 92.4%，
其中非 sink 本体 76.3%。变化检测普查（100k 精确插桩）：非 sink publish 比较
**22.79e9 次**、sink 比较 9.74e9 次，gsim 对照 6.77e9（组合侧差 14.8×）。

非 sink 划分现状（`wolvrix/lib/grhsim/backend/cpu_partition.cpp`，已逐行核实）：

| 阶段 | 机制 | 尺寸约束 |
|---|---|---|
| C1 `formNodes`（:231-273） | 逆拓扑单 consumer 锥吸收；任一扇出到多个节点即断 | 128 op/节点 |
| C2 `coarsenGeneral`（:287-350） | out1/in1 链 + 同前驱兄弟，三模式贪心到不动点，商图须为 DAG | 合并后 ≤128 op（:302） |
| C2 `segmentGeneral`（:357-425） | 拓扑序一维 DP，代价 = distinct 入边界值数 + 段罚 1 | 窗口 ≤128 op 硬帽（:396） |

产出：34,289 个非 sink 超节点、**2,017,144 条边界值**、真实平均 ~105 op/超节点
（3.6M op / 34.3k——128 帽几乎一直贴着）。

已淘汰的方向（筛查实测，勿再走）：

- DP 代价率加权（PGO）：动态 publish 比较仅 **-1.1%**，运行 179.3s ≈ 基线。
  热值高扇出，小窗口装不下；且 gsim 不需要 profile 也能做好——问题在结构不在代价权重。
- 单纯放大 maxOps：m256/m512/m1024 边界 -15%/-25%/-36%、静态 publish 站点
  -17%/-23%/-27%，但 CPP→二进制编译爆炸（m256p1 ~4.8s/TU vs 基线 0.8，
  60 min 只编 52%；TU 总行数反降 10%，慢因是大函数活跃范围超线性）。

## 问题诊断

边界多的根源不是某个参数，而是**划分判据里没有任何语义/激活成分**：

1. 节点层靠"单输出逻辑锥"无脑吸收，扇出即断——把源信号的实现锥沿 fanout
   点切碎，边界落在数据流形状上而非语义断层上；
2. 128 op 帽贯穿 C1→coarsen→DP 三个阶段，合并被尺寸主导；
3. 激活信息（`event_acts`）只记录（`attrs.eventActs` 并集，:550-554）不参与
   划分；激活等价合并只发生在 sink 侧（按事件签名，:562-637），非 sink 侧
   "随便合并"——混合激活集的超节点点火率取成员并集，体内 guard 白算。

对照 gsim 默认路径 `graphPartition()`（`reference/gsim/main.cpp:350`，已核实）：
`mergeWhenNodes` 按 when 激活条件整组合并（mergeNodes.cpp:78）；
`mergeOut1/In1` 链吸收上限 7000 近乎无；尺寸只在最后
`graphInitPartition` 作为打包约束切一刀（SuperNodeMaxSize=35）。
（`MFFCPartition` 属于未被 main 调用的 `essentPartition` 备选路径，不计入对照。）
**gsim 是先按语义/激活结构无上限合并、最后才按编译需要切段；我们正好相反。**

## 目标与约束

- 目标：以边界为导向降低非 sink 比较次数与 P_general 时间；验收 = 标准口径
  运行时间 < 178.9s（越多越好），动态比较次数显著下降。
- 硬约束（作者给定，验收标准）：**SV→CPP 生成 ≤ 30 min**（现基线 15.7 min）、
  **CPP→二进制 ≤ 30 min**（现基线 ~10 min 量级；m256 教训说明这是首要风险）。
- 语义保守：划分只改分组不改 op 语义；点火只会变大不会变小（正确性零风险面）。

## 方案

三条主线对应作者的三条建议，统一为一句话：**把 gsim"语义结构先行、尺寸兜底"
的划分哲学搬进非 sink 框架，语义锚点用 declaredSymbol，尺寸降级为最后的打包
约束。**

### S0（前置测量）：声明溯源覆盖普查

在动划分之前先量化语义信息够不够用。`GrhSimModel` 携带
`DeclProvenance`（`include/grhsim/ir/model.hpp:669-717`）：每个 declaredSymbol
→ Value/State/Function 切片（Direct/Alias/Merged，带位区间），GRH lowering
填充、pass 有维护契约、compact() 重映射；生产流强制 `keep_declared_symbols`
（`scripts/wolvrix_xs_grhsim_ir.py:341`，`docs/grhsim_ir/flows/cpu-st.md:55`
明确禁止关闭）。测量项（对 XS checkpoint）：

- General 非 sink 值中被 DeclProvenance 覆盖的比例（值数 / op 数）；
- 每声明对应的值数分布（Direct 全量 vs Merged 打包 vs Alias 重定向）；
- 以声明值为根、沿未声明中间值单链回吸收的"语义锥"大小分布（验证"理论上
  不会很大"的假设；若出现巨型锥，记录其构成）；
- event_acts 等价类的大小分布，**特别是空签名（纯组合）op 的占比**——
  它直接决定 S3a 保护性合并的实际权重。

实现：向 `cpu.st.build-general-nodes` 加一组 `diagnostics.info` 计数（或用
checkpoint JSON + 脚本，复用 `ptmp/grhsim-cmpcount/census_and_instrument.py`
的模型解析）。产出一张分布表贴回本档。

### S1（建议 1）：语义级节点层——declaredSymbol 锚定的 node

替代 `formNodes` 的"单输出逻辑锥 + 128 帽"：

- **节点锚点**：每个解析到 Value 的 DeclProvenance 切片目标值 = 一个语义节点
  的根（同一目标值被多个声明锚定则并为一个节点；State 目标不涉及非 sink
  框架，Function 同理）。
- **锥吸收**：从锚点沿数据流逆向吸收**未被任何声明锚定**的中间 op；单
  consumer 在锥内则吸收，多 consumer 的中间 op 成为共享边界（自带一个无名
  节点）。吸收不停在扇出点——扇出的若是另一声明信号，恰是应该保留的节点
  边界（语义断层），若是无名中间值则按共享边界处理。
- **不设大小限制**：源信号的单轮实现锥理论上不会很大（S0 验证）；异常大锥
  由打包阶段处理（S3c），不在语义层设帽。
- **回退**：未被溯源覆盖的值沿用现 cone 规则，保证 S0 发现的覆盖缺口不阻塞。
- 落点：改写 `formNodes`（cpu_partition.cpp:231）为 `formSemanticNodes`，
  接口（ops → nodes + 边）不变，下游 coarsen/segment 无需感知。

### S2（建议 2）：启发式合并放松大小限制

`coarsenGeneral` 三模式保留（结构判据本身是对的，gsim 同款），但：

- out1/in1 链吸收的合并权重上限从 maxOps=128 提到**软上限**（初值 4096 op，
  对齐 gsim 7000 node 的"近乎无"），或提供 0 = 无上限；
- **不需要单独的 MFFC 算法**（2026-10-05 作者指正后核实）：gsim 的
  `MFFCPartition` 只挂在 `essentPartition()` 下，而 main 实际走的是
  `graphPartition()`（`main.cpp:350`），essent 路径在 main 里无调用点，
  是未启用的备选；且 MFFC 的"全部后继在锥内则吸入"规则与我们 out1 模式
  迭代到不动点在数学上等价（fanout-free region 分解）——尺寸帽放松后，
  out1/in1 迭代自然把被切碎的锥合拢；
- DAG 守卫（`orderClusters` 商图校验）必须保留，批量收缩的安全网不动。

### S3（建议 3）：最终边界的裁切规则——merge/segment 调优

**白话版（2026-10-05 应作者要求补）**：组内传值是 C++ 局部变量，零开销；
只有组间传值才要"变没变？变了就存+叫醒下游"——100k 拍共 228 亿次，这是
P_general 最大开销，所以**切在哪直接决定快慢**。今天的切法是"凑够 128 op
必须切一刀"的装箱程序（平均 105 op/组贴着帽，说明切点由帽决定而不是由
逻辑决定；一条 300 op 的信号链也被剁成 3 段，段间每次必变的值白比较）。
S3 换切规矩：先把"反正一起醒"的运算焊死不许切中间（S3a）；切刀改成"能不
切就不切、太大了才挑最便宜处切"（S3b）；函数太大编不动时用"拆函数体"
（helper chunks）兜住编译 30 min 硬闸，尺寸从此只服务编译时间、不再有权
决定哪些运算不许在一起（S3c）。买来什么：边界值 ↓ → 比较次数 ↓（gsim 总共
才 68 亿次）→ 运行时间 ↓，且函数不被两种唤醒条件反复白叫醒。

S1/S2 回答"结构允许哪些 op 在一起"，S3 回答**最终超节点边界切在哪**。三个
子项各管一件事：S3a 定"不许切的位置"，S3b 定"可以切时切哪"，S3c 定"编不过
时怎么收"。

- **S3a 事件携带者的保护性合并（哪里不许切）**：先明确非 sink op 的
  event_acts 是什么——B2 `lower-edge-detect` 把事件锥消费者的
  `event_edges` 降为 `event_acts`（overview.md:335-336），带非空 acts 的
  非 sink op 是事件锥里的值生产 op（典型：带返回值的 event-gated DPI/
  系统调用、事件采样值）；运行时它是**正确性机制**而非性能装饰：C4
  eventActivation 让携带者超节点边沿轮次无数据变化也点火（must-run，
  verifier 强制），体内 per-op eventActStore guard 让它非边沿轮次跳过
  （must-not-run）。非 sink 超节点的点火条件 = 数据变化 ∪ 事件激活。
  S3a 的判据：相同 acts 的 cluster 合并零代价（点火条件不变、guard 对齐），
  不同 acts 合并点火取并集、guard 白算——所以 DP 之前先把同 acts 的
  cluster 合并，不许把事件携带者从其自然邻居切开。
  **定位限定（2026-10-05 作者追问后修正）**：event_acts 只覆盖时钟/事件
  一个维度——① 非 sink 图里大多数 op 是空 acts（纯组合），"同 acts"对
  它们是空判据，S3a 在空签名海洋里没有区分度（空 acts 占比由 S0 实测，
  直接决定 S3a 的权重）；② 空 acts 内部的数据冷热（热边界 vs 冷边界）
  event_acts 完全看不见，gsim `mergeWhenNodes` 的 when 条件是**数据使能**
  覆盖全图，我们只对应其时钟维度那一半。因此 S3a 是保护性合并、不是
  主力；数据维度的"同生同死"信息长在语义节点的 en 锥结构上（S1 的地盘），
  gsim mergeWhenNodes 的完整对应物 = S1 + S3a 拼起来。与 S2 的分工：S2 按
  数据流形状合锥（不看激活），S3a 按事件激活焊块（不看形状），互补。
- **S3b DP 从硬帽装箱改成软罚裁切（可以切时切哪）**：今天窗口 ≤128 是硬
  约束——S3a 焊出的大块一旦超过 128，DP 连"整块为一段"的选项都不存在，
  等于 S3a 白做。改为段可以任意大、超过软阈值后线性加罚：DP 行为变为"能
  整段则整段；段大到编译预算吃不消时，才在块内选代价最小处切"。权重保持
  均匀（PGO 率加权已淘汰），`--segment-penalty` 保留，软罚系数做成旋钮。
- **S3c 编译时间由打包层兜底（编不过怎么收）**：与 merge 无关但决定方案
  可行性——超节点变大 → C++ 函数变大 → -O3 编译爆炸（m256 实测 ~4.8s/TU
  vs 基线 0.8）。手段：helper chunks 按估计行数把大函数体切小（已有，
  `--helper-max-estimated-lines`）+ C6 emit-function 批装控制 TU 数。
  CPP→二进制 ≤30 min 是硬闸；若 chunk 化救不回（m256p1h512 的教训是
  chunk 不一定救得回大函数活跃范围，裁决中），就收紧 S3b 软罚系数或按
  激活类内 DP 重切。**尺寸只是编译时间的控制变量，不再是结构合并的禁令**。

### 实验矩阵（每点都要五项度量）

度量五件套：① 非 sink 超节点数 / ② 边界值数 / ③ 静态 publish 站点数 /
④ SV→CPP 与 CPP→二进制时长 / ⑤ 定核 100k 运行时间（须命中终点
instrCnt=240,349 / cycleCnt=99,996）。通过筛查的点再补动态比较次数普查。

| 实验 | 内容 | 预期 |
|---|---|---|
| E0 | S0 覆盖普查 | 分布表；覆盖率 <90% 则先补溯源维护再往下走 |
| E1 | S1 单独（coarsen/DP 不动） | 节点/超节点结构对比、边界变化方向 |
| E2 | E1+S2 | 边界值数显著下降（对标 m512 的 -25% 但不动 DP） |
| E3 | E2+S3a | 动态比较次数下降（主目标） |
| E4 | E3+S3b/S3c 打包变体 | CPP→二进制 ≤30 min 内收敛 |

任一实验违反 30+30 min 约束即停，记录数据后回退到上一可行点收紧打包。

## 正确性验证（每个落地改动全绿才可提交）

按 README 门槛：`make test_wolvrix`（恰基线三项）、
`make run_all_hdlbits_grhsim_ir_tests` 162/162、`make run_xs_bugcase_grhsim`
25/25、`make check_sim_refactor_baseline` 161/161、XS 完整 CoreMark + NEMU
difftest 轨迹 663,688/297,291。划分改动不改调度语义，轨迹必须同迹。

## 风险与回退

- **溯源覆盖缺口**：pass 维护契约若有漏洞，S0 会发现；回退规则（未覆盖值
  走旧 cone）保证语义节点层始终可形成。
- **编译时间爆炸**（最大风险，m256 已实证）：所有放松都以打包层兜底 +
  30 min 硬闸；每实验必测 CPP→二进制时长。
- **剖面过拟合**：不以 CoreMark profile 做判据（PGO 已否决）；激活等价是
  静态结构，天然免于过拟合。跨设计验证靠 hdlbits/xs-bugcase/openc910。
- **DP 软罚引入新病态**（超大段吃光编译预算）：软罚系数作为旋钮，配合
  S3c 反馈；最坏情况退回硬帽但帽值放大（即 m512 形态，已知编译不可行，
  故打包层必须先于结构放松就绪——**实施顺序：S3c 打包验证 → S1 → S2 → S3a**）。

## 后续

- ~~m256p1h512（helper chunk 拆函数）编译裁决~~ 已裁决：3h37m 编 55%，违反
  约束——chunk 不救大函数（详见探索记录）；
- **E1/E2 已执行**（2026-10-05）：S1/S2 结构收益成立（s1c 边界 -16%、
  publish 站点 -21.8%），全形态违反编译闸；瓶颈定位为编译器后端
  SLPVectorizer（62%）+inliner，非划分本身。数据与基线见
  `20261006-061729-nonsink-partition-s1s2-exploration.md`。规划修订点：
  S3c 从"打包"精确化为"编译器后端成本控制"（`-fno-slp-vectorize` 运行时
  中性已证 + inliner 控制）；
- E0 分布表回填 S0 节（已顺测 anchored_values=464,858，锥大小分布仍欠）；
- 每个落地改动按模板另写优化记录并回链。
