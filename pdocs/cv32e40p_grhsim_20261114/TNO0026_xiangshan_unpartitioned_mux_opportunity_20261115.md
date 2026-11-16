# TNO0026：XiangShan 未分图全图的 mux 单侧计算潜力

本轮只做静态分析。复用合并后 kunminghu-v3、单核 DefaultConfig、完整 DiffTest、hardware simulation models 的冻结 `SimTop` 图，在 RepCut 分图和 activity schedule 之前统计。没有重新生成 RTL、运行仿真、修改 emitter 或生产默认值。

**517.47 万个活跃纯组合 op 中，194.85 万个（37.65%）属于可跳过的单侧封闭锥。考虑嵌套、同一 selector 的复用，并假设不同 selector 独立且两侧各 0.5，封闭锥模型期望少执行 130.38 万个 op（25.20%）。进一步合并跨消费者的条件需求，4096 组假设选择得到 28.27%。这些数字衡量一次全图组合求值的 IR 工作量，不是现有仿真器的 walltime 收益。**

## 输入身份和分母

输入：`wolvrix-playground-new-xiangshan/build/xs/kunminghu-v3-grhsim-merge-20261110/after/repcut/memory.json`，4,548,632,377 bytes，SHA256 `6a2510cac638cbefa9e432d6e7f3e4ade8158fbda05cef09e0ccdb06792c07fc`。JSON 中只有一个 `SimTop` graph，没有 partition/supernode 限制。阶段是 frontend lowering、comb-lane-pack 和指定 memory lowering 后、RepCut 前。

冻结生成记录使用 XiangShan merge `9d1f24cea2726642bfe04be545f7046f845735ed`，上游 parent 为 `41ab74e7d`；随后 harness 更新至 `defb18e13c2e3a0e272b43b2eaccd1d4b16de9c0`，记录明确 RTL 未变。完整配置、阶段日志和脚本身份见 [provenance](../../build/xiangshan-mux-opportunity-v1/provenance.json)。

| 统计对象 | 数量 |
| --- | ---: |
| 全部 IR op（含声明、常量、状态、effects） | 6,590,947 |
| 对输出或必执行边界有贡献的活跃 op | 6,385,406 |
| 活跃纯组合计算 op，本文主要分母 | **5,174,672** |
| 其中所有操作数及结果都为 ≤64 位、单结果的 op | 4,931,743 |
| 扣除 Assign / Concat / Replicate / SliceStatic 后的组合 op | 4,283,326 |
| 全图 mux / 活跃 mux | 978,175 / **939,916** |

不把 Constant、RegisterReadPort、MemoryReadPort、声明、提交和 effects 算作可省的纯组合运算。所有非纯操作及公开输出作为必需根，反向求活跃集合；寄存器状态依赖在读写之间切断。内存读取本身保持必需，其地址计算也因此不能被单侧 mux 偷偷跳过。完整 DiffTest、断言和打印相关数据流保留，未依据实际运行时 enable 剪枝。

原图有 1,616 个既无定义又非输入的值，其中 120 个有使用；分析显式记录它们并作为不可回溯的外部叶子，不假装它们是常量，也不添加不存在的生产者。见 [input.json](../../build/xiangshan-mux-opportunity-v1/input.json)。本轮假设不额外观察内部波形值。

## 单个 mux 的期望如何定义

对必须执行的 `mux(s, t, f)`，令 `T`、`F` 分别为只因该侧被选择才需要的纯组合 op；`C` 为其它必需工作，包括选择锥、两侧公共工作和仍被外部消费者使用的工作。每个 op 权重先取 1：

```text
eager cost       = C + |T| + |F| + 1
expected cost    = C + p|T| + (1-p)|F| + 1
expected saving  = (1-p)|T| + p|F|
p = 0.5         => 0.5 × (|T| + |F|)
```

末尾的 `1` 是 mux 自身。选择计算在这个 mux 被需要时始终执行；若整个 mux 已被外层未选分支跳过，其选择计算也可以跳过。

为求 `T/F`，在数据使用图中给 mux 的真、假数据边各插入一个虚拟 gate；选择输入直接连到 mux，不经过 gate。只有从某 op 到所有必需根的使用路径都经过同一个 gate，该 op 才属于这个单侧锥。实现用 DAG 的后支配树求集合，允许同一侧内部的多次使用，不要求每个中间值只有一个消费者。

这自动排除选择锥、跨侧共享和外部使用。逐 mux、两侧大小和原 JSON byte offset 全部保留在 [muxes.tsv](../../build/xiangshan-mux-opportunity-v1/muxes.tsv)，可定位全部 939,916 个活跃 mux。

## 全图结果：四个范围

以下百分比统一以 5,174,672 个活跃纯组合 op 为分母；各行是完整模型，**不能相加**。

| 结构模型 | 唯一条件覆盖 op | 0.5 下期望少执行 op | 减少比例 |
| --- | ---: | ---: | ---: |
| 单使用、标量、每臂 16–256，外层优先选不重叠锥 | 587,473 | 294,486 | **5.69%** |
| 单使用、标量，放开大小限制并允许逐层条件求值 | 1,680,250 | 1,095,118.79 | **21.16%** |
| 全图单侧封闭锥，允许锥内共享与宽值 | 1,948,503 | 1,303,841.69 | **25.20%** |
| 全图条件需求传播，进一步处理跨消费者共享 | 不用单侧覆盖率描述 | 1,462,925.53 | **28.27%** |

第一行是现有 conditional-mux 规则的**结构近似**，没有施加分组、持久存储、其它 lowering 排斥等 emitter 限制；也未生成 XiangShan 候选。它选中 13,625 个 mux、14,748 个分支。不能把它称为当前 emitter 已命中的数量，或已验证的净收益。第二行还允许外层分支内部继续进行条件求值，而现有 emitter 在吸收一个外层锥后会直接生成其内部普通运算。

### 为什么不能逐 mux 相加

所有单侧锥大小之和为 5,692,021；直接取一半会得到 **2,846,010.5 op，即 55.00%**。同一 op 会出现在外层和内层多个锥中，这个加法重复记账。

实际唯一覆盖只有 1,948,503 op，其中 911,770 op 处于至少两层 gate 之下。独立条件下，经过两层同向选择的 op 执行概率是 0.25，经过三层是 0.125。统计对每个 op 只计一次，并处理同一 selector 的重复约束和矛盾约束。存在 1,075 个已知常量 selector，按常量真实取值处理，不为常量抛硬币。

精确的封闭锥模型结果因此为 **25.20%**。另一个独立记账检查是：所有最外层、互不重叠的单侧区域包含 op 数之和，恰好等于唯一覆盖的 1,948,503。

### 更广的共享需求模型

对 4096 组假设 selector 赋值，从公开输出和状态/effect 边界反向传播需求：普通运算要求所有输入；mux 要求 selector 和选中侧；共享 op 的需求取所有消费者需求的 OR。每组赋值中，每个 op 最多计一次。同一个 selector SSA 值在所有 mux 中共用同一取值。

实现用 64-bit mask 同时处理 64 组赋值，共 64 个固定 seed block。期望执行 3,711,746.47 op，少执行 28.2709%；基于 64 个 block 均值的近似 95% 采样区间为 **[28.2004%, 28.3414%]**。这个区间仅描述随机采样误差，**不描述真实 workload 的误差或性能置信区间**。

不同 selector 之间的逻辑关系没有求解。例如，两个不同 SSA 值即便分别表达 `x==1`、`x==2`，本模型仍按独立事件抽样；这可能生成真实硬件不可能出现的组合。25.20% 与 28.27% 都是明确假设下的结构机会，不能当成 workload 无关的上下界。

统一把所有非恒定 selector 的 true 概率改为 0.1 / 0.9，封闭锥期望减少量分别为 **26.93% / 21.62%**，仅供模型敏感性参考。真实分析应使用逐 selector 的实际概率及联合关系。

## 机会的形状

939,916 个活跃 mux 中，578,756 个（**61.58%**）至少有一侧非空封闭锥。其中 487,634 个仅一侧有可跳过工作，91,122 个两侧都有。

| 单侧锥大小 | 分支数（含嵌套，不能加 op 量） | 最外层不重叠区域数 | 最外层区域包含的唯一 op |
| --- | ---: | ---: | ---: |
| 0 | 1,209,954 | — | — |
| 1–3 | 324,643 | 112,715 | 188,620 |
| 4–15 | 263,025 | 100,373 | 750,980 |
| 16–63 | 75,738 | 17,077 | 491,364 |
| 64–256 | 5,315 | 2,097 | 239,423 |
| ≥257 | 1,157 | 467 | 278,116 |

大量机会是小锥，但也存在被现有宽度和大小限制排除的大锥。自动按最外层不重叠区域排序，最大的几个为：

| 根的 RTL 来源 | 侧 | 单侧 op 数 | 根最大操作数/结果位宽 | selector / 语义线索 |
| --- | --- | ---: | ---: | --- |
| VFEX1.sv:3265 | true | 5,278 | 128 | `outFuUopEx_0_valid`，向量结果输出选择 |
| VFEX0.sv:4444 | true | 4,754 | 128 | `outFuUopEx_0_valid`，向量结果输出选择 |
| VFEX3.sv:1239 | true | 4,604 | 128 | `_Vialu_out_ex_0_valid` |
| VFEX2.sv:1239 | true | 4,604 | 128 | `_Vialu_out_ex_0_valid` |
| PtwCache.sv:26936 | true | 4,595 | 256 | `l0v` 状态更新选择 |
| Decoupled2LCredit_2.sv:137 | true | 4,149 | 422 | `io_in_valid` 对 `out_flit_r` 更新的选择 |

这些是根的 source location，整个跨模块计算锥不一定都源自同一个 RTL 文件。完整前 30 项及 selector 路径见 [largest-disjoint-regions.csv](../../build/xiangshan-mux-opportunity-v1/largest-disjoint-regions.csv)。前四项的有效信号选择在冻结 RTL 中直接核对过；未根据运行时热点挑选。

全图需求模型省下的 146.29 万 op 中，主要类别为：Mux 46.82 万、Or 27.06 万、And 25.99 万、Concat 8.93 万、Eq 8.56 万。这里很大一部分是选择/布尔网络，不等价于同样数量的 Host 指令。完整分类见 [op-kinds.csv](../../build/xiangshan-mux-opportunity-v1/op-kinds.csv)。

作为两个静态权重检查：

- 去掉 Assign、Concat、Replicate、SliceStatic 后，全图需求模型减少 **29.17%**，说明机会并非全部来自这些接线类 op。
- 每 op 权重取 `ceil(max(input_width, output_width)/64)` 时减少 **20.98%**。这个权重只是宽度代理，不等价于机器成本，不能把宽除法、拼接和位运算的同一权重解释为同一运行时间。

## 对下一步的含义

静态覆盖足够大，值得继续做条件求值；目前 16–256、单使用、标量的保守入口只覆盖其中一部分。下一轮更有信息量的验证，是在这些自动列出的结构类别上核对现有 generated C++：哪些已经由 priority-mux lowering、常量折叠或 Clang 消去，哪些仍提前执行；再测量 selector 的真实选择概率和区域执行频率。

真实收益还需计入新分支、预测失误、调度、存储和结果复用成本。已有事件驱动执行不会每周期扫完整图；本轮没有将这些全图一次求值的统计换算成每周期数据，也没有承诺 25–28% 的整机加速。后续如做 profile，应先冻结结构类别与选择规则，保留全部样本，避免按测量结果挑最有利的锥。

## 复现和验证

新增分析代码：[prepare](../../scripts/xiangshan_mux_opportunity.py)、[C++ analysis](../../scripts/xiangshan_mux_opportunity.cpp)、[summary](../../scripts/xiangshan_mux_opportunity_report.py)、[独立 oracle](../../scripts/test_xiangshan_mux_opportunity.py)。它们均不依赖 Wolvrix runtime library。

```bash
python3 scripts/xiangshan_mux_opportunity.py \
  --graph ../wolvrix-playground-new-xiangshan/build/xs/kunminghu-v3-grhsim-merge-20261110/after/repcut/memory.json \
  --output build/xiangshan-mux-opportunity-repro
g++ -std=c++20 -O3 -Wall -Wextra -Werror \
  scripts/xiangshan_mux_opportunity.cpp -o build/xiangshan-mux-opportunity-repro/analyze
build/xiangshan-mux-opportunity-repro/analyze build/xiangshan-mux-opportunity-repro 64
python3 scripts/xiangshan_mux_opportunity_report.py --output build/xiangshan-mux-opportunity-repro
PYTHONPATH=scripts XIANGSHAN_MUX_ANALYZER=build/xiangshan-mux-opportunity-repro/analyze \
  python3 -m unittest test_xiangshan_mux_opportunity
```

独立验证用“删除某个 mux 数据边后重新求必需集合”检查单侧区域，用逐赋值的递归需求遍历检查 bitset 全图结果。10 项测试覆盖锥内共享、外部使用、selector 重叠、嵌套、重复 selector、不可能路径、常量、宽值、状态边界、死节点、乱序定义、16/256 边界、外层优先及 24 个随机 DAG；O3 与 ASan/UBSan 结果均归档。全图还检查单一 SimTop、SSA 唯一定义、活跃 DAG 无环、单使用锥两种计数一致及最外层区域总量恒等式。

最终结果：[summary.json](../../build/xiangshan-mux-opportunity-v1/summary.json)、[provenance.json](../../build/xiangshan-mux-opportunity-v1/provenance.json)、[验证日志目录](../../build/xiangshan-mux-opportunity-v1/validation)。
