# TNO0336 GrhSIM 现有 ASC 的成本建模与均衡（2026-10-13）

## 1. 范围与对照口径

用户要求：针对当前 GrhSIM 多线程负载不均衡，重新分配现有 ASC；不改变原有
Verilator 划分算法。当前主题的后续实现、数据和结论集中追加到本文，不按每次
动作新建文档。背景参见 [TNO0333](./TNO0333_repcut_grhsim_backend_20260925.md)
的当前 GrhSIM 线及逐 cycle 可视化。

本轮固定原始 GRH：

```text
build/asc_separator_combined_20260921/targeted/xs_wolf_mem_to_reg.json
sha256=c7b8b36adaf98f8bd794593f0d2f5c18e418f6566dae48edc5fabfb5f8d56e8e
```

旧分配来自 `build/default_line_ab_20260924/default_noenv`，包含 **301184 个 ASC**，
使用 `closure-aware + verilator-v1`；这不是 GrhSIM 流程省略选项时的 legacy 默认。
保持 ASC 边界、K=32、划分后的 memory-write-coalesce 和
`reg-to-mem(intent=false, profitability_filter=verilator-v1)` 相同。
这项后处理固定只用于本轮公平对照，不改变 GrhSIM 的 reg-to-mem 默认值。

此前完整保留 G binary 包含部分生成后原型叠加，不能将新划分直接和其历史耗时
相减并归因于划分。本轮对旧分配与新分配使用**同一 emitter、同组选项、同一编译器**
重新生成模型，保留旧 G 产物不动。新对照不能称作与旧 G 字节相同的完整保留线。
性能阶段只在 node030 CPU96–127/NUMA1，Clang23/O3/native、64B 对齐、all-spin、
N=K=32、ASLR off 条件下重新跑 AB/BA；优先使用并核验代码 THP。

## 2. 独立 GrhSIM 成本模型

新增显式 `grhsim-v1`，沿用已有 cost-model 扩展接口：

- GrhSIM 原生标量及 64-bit word 表示，不使用 Verilator 的 32-bit WData 估算。
- 宽归约计输入字数；窄动态切片计输出字数；bool 输入不另计 truth conversion。
- state/memory 写入按暂存、变更比较、提交、掩码合并和激活记账估算，不使用
  SV 的逐 bit memory staging 公式。
- 未知/外部 effects 显式 fallback；无模块、变量、partition 白名单，无运行耗时拟合。

完整规则和限制见 [RepCut 模型文档](../../wolvrix/docs/transform/repcut.md)。
这是每次激活的相对工作量近似，尚不预测各操作的活跃频率和上/下沿分布，不能
把静态均衡直接表述为动态 eval 均衡或 walltime 收益。

没有修改 `repcut.cpp` 的 ASC、solver 或 closure refinement 算法；没有改变
`legacy`、`verilator-v1`、`verilator-lowered-v1` 的计算公式和任何默认模型。
当前通过 `XS_REPCUT_COST_MODEL=grhsim-v1` 选择候选。

## 3. 实现检查（2026-10-13）

已通过独立构建中的四项检查：

1. `transform-repcut-cost-model`：含原有 legacy/Verilator golden、新 GrhSIM 的
   1/32/64/65/128/256/1024 位、write operand 下标、mask、fallback、溢出保护。
2. `transform-repcut`：新模型在 baseline/closure-aware 两种分摊模式下完成
   小设计分区/重建，同时保留默认与显式 legacy 的确定性 HGR 核验。
3. Python `test_repcut_options.py`：新 token、严格错误检查及 weight-mode 正交。
4. `test_wolvrix_xs_repcut_backend.py`：Verilator 默认路径不变；GrhSIM 显式新模型
   不改变其他后处理选项。

实验驱动与独立构建位于
[`build/repcut_grhsim_balance_20261013`](../../build/repcut_grhsim_balance_20261013/)。
完整设计正在分区和重新生成；完成后追加 ASC incidence 一致性、实际复制/通信、
功能验证以及 fresh AB/BA 数据。此处不预先宣称性能提升。

## 4. 完整设计的结构核验（2026-10-13）

候选完整分区及后处理通过。新旧 HGR 都包含 301184 个 ASC、296526 条超边；
去掉边权后的完整 incidence 列表 SHA256 均为
`2913bc53516a808b37de4710ee1220cbff73ab370979e0579966b87718c370ce`，
piece 数也同为 1320667。没有通过更换输入、拆锥或改变连接关系获得不同分区。

旧算法兼容性另通过实际文件核验：新测试生成的 30 份 HGR、solver 原始分配和
closure refinement 分配，与修改前保留的测试产物逐字节一致，覆盖原有三个
cost model、两种 weight mode 和 storage/effect/path fixtures。
见 [兼容性检查清单](../../build/repcut_grhsim_balance_20261013/legacy_compatibility.json)。

| RepCut 重建阶段指标（后续 memory passes 之前） | 旧分配 | `grhsim-v1` 新分配 |
| --- | ---: | ---: |
| 原图操作数 | 5817306 | 5817306 |
| 分区操作数总和 | 6184616 | 6178318 |
| 相比原图的操作数增量（含复制及重建） | 367310 | 361012 |
| 最大分区操作数 | 321936 | 321947 |
| 跨分区原始 values | 1123289 | 1108876 |
| cross links | 562 | 291 |

总操作数仅少约 0.10%。cross links 不是通信字节数，更不能直接当运行时通信
节省比例；生成包中的传输宽度、实际 update 时间另行核对。

原来的巨型 ASC 仍是 `ASC 5`，由旧 `p3` 迁到新 `p0`，因此后续不能把同名
partition 当成相同逻辑。新模型仍将它估成超过平均预算的 ASC；本轮没有绕过
已有的 overweight 保护或尝试拆开它。

旧划分重新生成的 GrhSIM 包已完成 Clang23/O3/native 构建，7454 个对象、
6859 个 compute 入口全部核验 64B 对齐。C100 初始化检查通过，80 MiB 完整
代码 THP 覆盖核验通过。该次仅为功能/环境准备，不进入性能统计；正式 AB/BA
会等待两侧构建全部结束后单独运行。

## 5. def-use 边界成本修订与完整 AB/BA（2026-10-13）

首版 `grhsim-v1` 只按算子和位宽估计 GrhSIM 的 word work。结构检查发现，新的
p20 主要吸收了旧 p15/p29 的布尔选择链；这些中间值在生成器的 compute/commit
边界上需要保留、比较旧值并设置 dirty 标记，首版没有计入这类持久化工作。于是
在同一个 `grhsim-v1` 模型中补充了通用 def-use 代理：

- 一个组合结果被两个不同 operation 使用时增加 `2*G(width)+1`，表示旧值比较、
  持久存储和变化标记；同一 operation 的两个 operand 使用只算一次；
- 一个结果只有一个 consumer、但 consumer 是 register/latch/memory write 时增加
  `G(width)`，表示 compute 到 commit 的暂存；
- 常量、assign 别名和直接 state read 不增加该项；没有模块、信号、partition 或
  workload 名称匹配，也没有读取 profile 来拟合系数。

测试特别覆盖了宽值、同一 consumer 的重复 operand 和 12 个以上 consumer 的
heap-backed use list，避免 `Graph::getValue()` 临时对象失效。旧模型的 golden
结果不变。重新链接时，旧 generator 的 emitter/scheduler 对象与第一轮逐字节
相同，说明此轮只改变成本模型和 ASC assignment。

### 5.1 结构与构建 gate

候选仍保持 301184 个 ASC、296526 条超边和同一 incidence SHA256
`2913bc53516a808b37de4710ee1220cbff73ab370979e0579966b87718c370ce`。完整候选
使用 Clang 23.1.2/O3/native 编译 7504 个对象，6905 个 compute 入口 64B 对齐；
C100 初始化、C100000 功能签名、difftest、代码 THP 覆盖和 8 对 C100000 AB/BA
均通过。基线和候选使用同一 emitter 选项、同一 runtime、同一 node030 CPU96--127
/NUMA1/all-spin 配置，基线计时也在本轮重新采集。

候选把原来 p3 上的 ASC 5 移到 p16；ASC 仍完整保留，没有拆分。候选静态 closure
负载的最大值仍由这个不可拆 ASC 决定（812163），其余较重分区为 p2/p22；这说明
模型可以重排 ASC，但无法消除单个不可拆逻辑锥。

### 5.2 实测结果

`build/repcut_grhsim_balance_20261013/boundary/ab_ba_thp/summary.json` 保存原始
数据，`runtime_report.json` 保存按分区聚合结果。8 对 fresh AB/BA 的中位数如下：

| 指标 | 冻结旧 assignment | `grhsim-v1` 新 assignment | 配对变化 |
| --- | ---: | ---: | ---: |
| Host walltime | 15.593 s | 15.112 s | **-2.069%** |
| elapsed walltime | 15.680 s | 15.190 s | **-2.065%** |
| 全局 eval | 62.628 us | 61.504 us | **-1.526%** |
| 全局 update | 10.382 us | 9.768 us | **-6.967%** |
| 分区 eval 总和 | 646.030 us | 620.973 us | **-3.866%** |
| 最大分区 eval | 38.786 us | 41.212 us | **+7.286%** |
| 分区 update 总和 | 95.527 us | 92.949 us | **-2.984%** |

候选在 8 对中的 walltime 胜出 4 对；update 胜出 7 对。静态生成的跨分区
update 检查次数由 5286 降至 3987（`-24.57%`），但检查的 full-width storage
字节由 463243 增至 501927（`+8.35%`），因此不能把通信次数下降等同于字节下降。

运行时瓶颈分布也发生了迁移：旧 assignment 的瓶颈是 p16/p17/p18，分别出现
3/3/2 次；新 assignment 的瓶颈是 p2/p27，各出现 4 次。新 p2 的平均 eval 为
44.676 us，p27 为 37.127 us，而旧最慢 p27/p18 为 35.319/35.117 us。候选的
平均分区 eval 变小，但尾部变长，正是全局 eval 小幅改善而最大分区 eval 退化的
原因。

### 5.3 结论与后续边界

这次修订证明 GrhSIM 专用的 whole-ASC 重新分配可以在不触碰 Verilator 公式、
默认值或划分实现的前提下，减少 update 复制与总体 walltime；它还没有证明能
稳定降低关键路径。候选静态 node-weight 与实测 eval 的 Pearson/Spearman 为
`0.221/0.309`，closure weight 为 `0.249/0.365`，仍属于中弱相关；因此当前
模型不设为 GrhSIM 默认，Verilator 路径完全不变。

下一步应加入与 operation 名称无关的结构性关键路径代理（例如 ASC 内依赖深度、
批次边界和 compute/commit 阶段的最长链），再评估是否能在保持 whole-ASC 约束的
同时压低最大分区 eval。不要直接用本轮实测时间拟合权重，也不要只为 p2/p27 或
某个信号添加特判。

## 6. node030 空闲窗口复测（2026-10-13）

上一节的 8 对窗口期间专用核有外部任务占用。按用户要求保留原 binary、原
baseline/candidate package 和所有运行参数，只重采性能阶段；本次仍是 node030
CPU96--127、NUMA1、all-spin、ASLR off、THP、C=100000、8 对 AB/BA。上一轮目录
保存在 `ab_ba_thp_round1/`，本节的 `ab_ba_thp/` 是复测结果。

复测的所有 16 个正式运行和两侧 C100 smoke 都通过，候选 8/8 次 walltime 胜出：

| 指标 | 基线中位数 | `grhsim-v1` 中位数 | 配对变化 |
| --- | ---: | ---: | ---: |
| Host walltime | 12.5905 s | 12.3055 s | **-2.323%** |
| elapsed walltime | 12.6750 s | 12.3900 s | **-2.304%** |
| 全局 eval | 48.909 us | 48.6715 us | **-0.785%** |
| 全局 update | 9.9835 us | 9.1230 us | **-8.257%** |
| 分区 eval 总和 | 541.044 us | 528.202 us | **-2.717%** |
| 最大分区 eval | 29.745 us | 31.0525 us | **+4.483%** |
| 分区 update 总和 | 90.5185 us | 86.848 us | **-3.771%** |

这轮的绝对 walltime 低于上一轮，不能跨轮比较绝对值；配对百分比方向一致，且
候选在 Host、elapsed、update 及分区 eval 总和上均稳定改善。瓶颈分区也稳定迁移：
基线 8 次均由 p18 最慢，候选 8 次均由 p2 最慢。候选仍降低整体工作量，却把关键
路径集中到 p2，说明当前静态成本可以减少平均负载和 update 开销，但还不能作为
“均衡最大 ASC 工作量”的完成结论。

因此本轮仍保持 `grhsim-v1` 显式 opt-in；Verilator 的 cost model、默认值、
solver 和分区算法没有修改。下一步应针对通用依赖深度/批次边界建立静态关键路径
代理，再做新的 whole-ASC AB/BA；不使用本轮运行时间反向拟合 p2 或 p18 的权重。

## 7. 静态依赖链与半周期负载诊断（2026-10-13）

本轮先检验上一节提出的“依赖深度/最长链”方向，未直接把它加入 solver。完整
扫描两份经过相同 memory 后处理的 partitioned GRH，在生成 scheduler/C++ 之前
计算各叶模型的算子工作量、最长 def-use 链、链上潜在暂存边界数和工作量加权深度。
两侧都使用同一个 `grhsim-v1` 计价函数；constant、storage 声明、直接 state read
和 assign 不当作 compute 指令计价。这里的“最长链”是 **GRH 依赖链的静态代价**，
不是 CPU 周期，也不是实际每一步最慢线程的耗时。

探针使用拓扑排序，去重同一 producer 的重复 operand 边，遇到叶模型环会拒绝；
顺序子模型之间有反馈的顶层 wiring graph 不属于组合 DAG，不参与统计。菱形
依赖/重复 operand 自检和新旧共 64 个叶模型扫描完成。探针、汇总及复现入口集中在
`build/repcut_grhsim_balance_20261013/critical_probe.cpp`、`critical_report.py`。

### 7.1 最长链不足以解释当前瓶颈

以下相关性均使用 §7.4 **新采的未插桩 8 对 AB/BA** 中各分区 eval 均值，未用耗时
拟合任何权重系数。Pearson 衡量线性关系；这里每侧有 32 个分区样本。

| 静态指标与 eval 的 Pearson | 旧 assignment | `grhsim-v1` assignment |
| --- | ---: | ---: |
| 后处理 GRH 的总工作量代理 | 0.218 | 0.329 |
| 最长加权依赖链 | 0.394 | **0.052** |
| 最大依赖深度 | -0.168 | **0.074** |
| 链上潜在暂存边界数 | 0.027 | **0.179** |

新 assignment 的 p2 平均 eval 为 **27.872 us**，最长链代价 **3882**、深度 **80**；
p12 最长链代价 **14291**，eval 却只有 **12.336 us**；p19 为 **12768 / 9.912 us**。
这些数据不支持直接给长链加罚权。上一轮计时上也得到相同方向：新 assignment
最长链 Pearson 为 0.015；重新采样后仍很弱，并非依赖某一轮计时才出现。

同一 fresh window 下，新 assignment 的原始 repcut node/closure/hyper 权重
Pearson 为 **0.201 / 0.227 / 0.123**。后处理后的工作量代理略有改善，但仍远不足以
预测动态瓶颈；不能把这一诊断结果直接当作新 cost model 已验证成功。

原始数据见
[静态特征与 fresh eval 汇总](../../build/repcut_grhsim_balance_20261013/boundary/critical_static_fresh_report.json)。

### 7.2 Fresh 逐半周期 AB/BA：热点随边沿和 cycle 改变

只重编译四个包装层对象以记录已有的计时结果，baseline/candidate 分别保留
**7450 / 7500 个其余 archive 对象逐字节不变**。在 node030 CPU96--127 上重新跑
C100000 AB/BA（共 4 次正式运行），固定 N=K=32、all-spin、Host CPU105/lane9、
NUMA1、ASLR off、64B 对齐及代码 THP。功能签名与 THP 检查通过；每份 trace
有 200102 个 step，99 项累计计时对账全部通过，误差不超过原 JSON 的 500 ns
舍入范围。下表剔除了前 50 个 reset cycle，按时钟 1/0 的相邻两步区分上/下沿。
**插桩结果只用于阶段归因，不用于宣称 walltime 收益。**

“瓶颈占比”指该边沿中 eval callback 用时最长的 step 比例；不是最晚到达屏障的
线程比例。“瓶颈时 eval”只对该分区成为最长 callback 的样本求均值。

| assignment | 边沿 | 分区 | 该边沿平均 eval | 瓶颈占比 | 瓶颈时 eval |
| --- | --- | --- | ---: | ---: | ---: |
| 旧 | 上沿 | p18 | 28.169 us | 37.568% | 43.865 us |
| 旧 | 上沿 | p10 | 28.837 us | 24.870% | 37.535 us |
| 旧 | 下沿 | p29 | 29.958 us | 37.308% | 51.382 us |
| 旧 | 下沿 | p26 | 35.046 us | 29.032% | 48.775 us |
| 新 | 上沿 | p2 | 30.183 us | **42.137%** | 45.406 us |
| 新 | 下沿 | p9 | 33.454 us | **47.378%** | **56.978 us** |
| 新 | 下沿 | p11 | 35.546 us | 15.815% | 49.470 us |
| 新 | 下沿 | p30 | 33.419 us | 17.543% | 25.720 us |

新 p9 的上沿平均 eval 只有 **0.738 us**，下沿为 **33.454 us**。两沿合并后只有
**17.096 us**，会在“各分区平均 eval 排名”中被掩盖，但它实际上是约一半下沿的
瓶颈。这不是通过 RTL 的 `eventEdge=negedge` 数量就能推出的结论：输入传播、
跨分区 update 和模型内部的 active/change 调度都会影响工作落在哪个半周期。

| 逐 step 归因指标 | 旧 assignment | 新 assignment |
| --- | ---: | ---: |
| 全局上沿 eval | 39.020 us | 39.603 us |
| 全局下沿 eval | 44.901 us | 47.700 us |
| 上沿各分区 eval 总和 | 385.949 us | 392.558 us |
| 下沿各分区 eval 总和 | 565.092 us | 552.584 us |
| 两沿平均的全局 eval | 41.961 us | 43.651 us |
| 先取每 step 最慢 callback，再求均值 | 40.479 us | 42.270 us |
| 先求每分区均值，再取最大值 | 26.635 us | 28.469 us |

可见新 assignment 下沿的**总工作量下降，但最长 callback 上升**。新 assignment
全局 eval 与每 step 最慢 callback 的平均差仅 **1.381 us**，这组数据中主体仍是
模型 eval，而不是只由 Host 屏障等待开销解释。两个“最大值/平均值”的运算次序
不可互换；下一轮均衡应针对逐 step 的尾部，而不只针对各分区的长期均值。

实现也与此一致：`grhsim_cpp.cpp` 生成的 compute batch 按 activity flag 选择
supernode，值改变后再激活后继；静态长链存在不代表该链在每个 step 都完整运行。
这些证据支持继续研究活跃阶段/触发源分布，但还不能据此声称已排除所有算子计价、
编译 lowering 或 CPU 执行效率误差。

完整 32 分区的逐沿均值、瓶颈比例、条件均值和 trace 对账见
[半周期诊断报告](../../build/repcut_grhsim_balance_20261013/critical_trace/report.json)。

### 7.3 是否仍有 whole-ASC 调整空间

新 assignment 的 HGR 和实际 assignment 对账如下。表中的占比是 solver 使用的
**fair-share 权重**：共享 piece 按引用 ASC 分摊后的估算，不是完整 closure，也不是
实际运行时间份额。

| 新分区 | ASC 数 | 最大单个 ASC 的 fair-share 占比 | 前 10 ASC 占比 |
| --- | ---: | ---: | ---: |
| p2 | 9867 | 0.405% | 2.462% |
| p9 | 46 | 2.465% | 24.645% |
| p11 | 368 | 2.587% | 25.871% |
| p30 | 5853 | 0.225% | 2.014% |
| p16 | 1 | 100% | 100% |

唯一占满 p16 的仍是 ASC5，它在本轮上/下沿的平均 eval 为 **18.060 / 17.395 us**，
成为瓶颈的比例为 **11.482% / 0.767%**。当前主要尾部并不全被这个单 ASC 决定。
p2/p9 等仍包含多个完整 ASC，因此 whole-ASC 重新分配有结构上的选择空间；但
不能由 fair-share 占比就断言每次移动都便宜，必须同时核算共享 closure 的额外
复制与跨分区通信。没有针对表中的 part 或 ASC ID 加入优化特判。

见 [ASC 构成与迁移来源](../../build/repcut_grhsim_balance_20261013/boundary/critical_asc_report.json)。

### 7.4 同窗口未插桩 8 对 AB/BA 与采用结论

trace 完成后，另外用 §6 同一对保留 binary 重新采集未插桩性能；没有复用任何旧
baseline 计时。仍使用 node030 CPU96--127、C100000、THP 及相同运行参数，所有
16 个正式 run 和两侧 C100 检查通过。每对百分比先按 `100*(B/A-1)` 计算，再取
8 对中位数；它与左右两列中位数直接相除不是同一指标。全部有效样本均纳入。

| 指标 | 旧 assignment 中位数 | 新 assignment 中位数 | 配对变化 |
| --- | ---: | ---: | ---: |
| Host walltime | 11.093 s | 11.220 s | **+0.920%** |
| elapsed walltime | 11.170 s | 11.305 s | **+0.936%** |
| 全局 eval | 41.924 us | 43.6165 us | **+3.559%** |
| 全局 update | 9.7025 us | 8.833 us | **-9.245%** |
| 分区 eval 总和 | 475.269 us | 463.816 us | **-2.425%** |
| 最大分区 eval | 26.3065 us | 27.6985 us | **+5.484%** |

候选 Host 只赢 **1/8** 对，全局 eval **0/8** 对，分区 eval 总和 **8/8** 对改善。
update 大多数样本改善，但本轮存在明显慢样本；此处保留它们，不筛选成更好看的
walltime 结论。原始结果位于
[未插桩 AB/BA 汇总](../../build/repcut_grhsim_balance_20261013/critical_trace/ordinary_ab_ba/summary.json)。

因此 §6 的约 2.3% walltime 收益没有在本次窗口稳定复现，不能升级为“已确认稳定
收益”。当前证据更一致地支持的是：新权重减少了总体 eval/update 工作，但没有
均衡每一步的最慢工作，性能采用依据仍不充分。

本轮不新增 `grhsim-critical-v1`，不把未经支持的最长链惩罚加入 solver；
`grhsim-v1` 继续 opt-in，Verilator 路径与默认不变。下一项应是从 GRH 的输入、
state read、event 和 def-use 关系建立通用的**触发来源/执行阶段成本向量**，区分
输入激活、state commit、提交后传播，而非只给每个 ASC 一个总分；先验证该静态
分类与上/下沿负载的关系，再尝试 GrhSIM 专用的 whole-ASC refinement。profile
仅用于验证解释能力，不把 p2/p9 的实测耗时或 ID 写进权重，也不做编译后反馈拟合。

## 8. 静态执行阶段向量与 whole-ASC refinement（2026-10-13 增量）

### 8.1 从触发来源预测阶段负载

本轮先实现 GRH 只读探针，分析输入、寄存器/存储器读写、事件和 def-use 关系。
沿用同一份 `grhsim-v1` 算子成本，分别累计上沿、下沿和未知触发源可以激活的工作，
不使用调度结果、生成 C++、编译结果或实测耗时作为成本输入。

阶段不能只看写操作的 `eventEdge`：本地 posedge 提交的状态在本地后续传播，跨分区
输入则在本步全局 update 后送达，通常在下一步 eval 处理，因此消费端对应下沿。
探针显式表示这一次跨分区传递。状态存在多个写者时合并其事件来源；无法解析的事件、
其他输入和 latch 保留为未知，不按变量名推断。

完整图中解析出两个顶层事件根。按引用次数选择主要事件根作为阶段坐标，旧/新划分中
该根的引用数分别为 294102 / 299328，事后核对名称均为 `clock`；另一个根 `reset`
只有 1 次事件引用，仍保留为未知。名称只用于核对，未用于选择。该坐标不能自动等同于
任意多时钟设计的全局阶段；多时钟泛化仍需独立表示各事件域。

两种划分的 64 个 leaf 均完成静态分类，在 3 轮跨图传播内收敛。用 §7.2 已采集的
逐半周期 trace 验证解释力，**这里只复用诊断数据，不是新一轮性能收益对比**：

| assignment | 验证边沿 | 总权重 Pearson | 对应阶段权重 Pearson | 对应阶段权重 Spearman |
| --- | --- | ---: | ---: | ---: |
| 旧 | 上沿 | 0.3061 | **0.6615** | 0.5495 |
| 旧 | 下沿 | 0.0657 | **0.6185** | 0.6452 |
| GrhSIM-v1 新划分 | 上沿 | 0.4083 | **0.6761** | 0.6804 |
| GrhSIM-v1 新划分 | 下沿 | 0.1612 | **0.7067** | 0.7364 |

新 p9 的静态上/下沿成本为 **281 / 406529**，对应实测 **0.738 / 33.454 us**，
成功区分了其主要在下沿执行的特点。新 p2 的静态成本为 **350514 / 332929**，
实测为 **30.183 / 26.755 us**。权重是相对工作量，不是纳秒预测。

这些结果支持保留阶段这一维度，但尚未充分解释每个分区：约 82% 的新划分工作还可能
被未知来源触发，仅有未知来源的工作约占各分区均值的 3.8%；静态“可能激活”也不等于
该 cycle 确实发生了值变化。分支、enable、变化频率和 lowering 差异均未通过拟合掩盖。

原始数据与实现见
[阶段分类报告](../../build/repcut_grhsim_balance_20261013/boundary/stage_report.json)、
[GRH 探针](../../build/repcut_grhsim_balance_20261013/stage_probe.cpp)。

### 8.2 阶段均衡候选的边界与验证

候选在原 `grhsim-v1` scalar closure refinement 之后，进一步移动完整 ASC。
目标是改善“上沿、下沿、未知触发源”三列成本的降序负载向量；不把未知来源忽略为零。
接受移动同时要求实际 referenced closure 总量和 communication proxy km1 相对本轮
起点的增幅均不超过 1%，保留超大不可分 ASC 的隔离约束，不清空分区。

移动写状态的 ASC 会改变其消费者的阶段归属。因此候选筛选可以先使用当前向量，但
接受前必须按新 assignment 重新计算源和目标分区的完整激活传播；其他分区对该状态
仍然是远端消费，阶段不变。最终再重算全部分区的向量，并独立核算复制/通信量，检查
增量计算与完整计算一致。第一版每次最多 32 个整 ASC 移动，属于有界局部搜索。

小型 fixture 包含正/负沿、反相时钟别名、本地与远端消费者，以及真正的状态写入 ASC
迁移。24 个 ASC 中成功移动 20 个；scalar closure 总量保持 96，阶段最大负载从 52
降至 18；全量阶段与复制/通信对账通过。原 cost-model 和 RepCut 测试也通过。

本实现暂在独立实验 generator 内，生产 `repcut.cpp` 未修改。用原对象重新链接的
对照库与前一轮保留 generator 逐字节一致，确保 emitter/scheduler 未混入其他修改。
完整模型性能将以 `grhsim-v1` 标量候选为 A、阶段 refinement 为 B，重新采集 AB/BA；
不将 §6/§7 的旧 timing 当成本轮 baseline。

### 8.3 完整候选的结构与通信量

完整候选的起点 assignment 与 §6 的 `boundary/candidate` 逐字节一致；HGR 的权重、
pin 内容及 ASC 顺序也完全一致。阶段 refinement 接受 32 次移动、恰好改变 32 个
ASC 的归属；32 次源/目标阶段重算均通过，最终全部列重算和 closure 对账一致。
重建、memory-write-coalesce、带原筛选规则的 reg-to-mem 以及 C++ 生成均完成。

| 指标 | A：标量 GrhSIM-v1 | B：追加阶段 refinement | 变化 |
| --- | ---: | ---: | ---: |
| 完整 referenced closure 总成本 | 13276069 | 13307659 | +0.238% |
| 其中重复计算的成本（compute km1） | 698131 | 729721 | +31590 |
| 重建后所有分区的操作总数 | 6154134 | 6169160 | +15026（+0.244%） |
| 其中复制出来的操作数 | 336828 | 351854 | +15026 |
| communication proxy km1 | 14026424 | 14166682 | +1.000% |
| 生成 update 的跨分区检查调用数 | 3987 | 4094 | +2.684% |
| 生成 update 每步检查的存储范围 | 501927 B | 502379 B | +452 B（+0.090%） |

最后一行逐目标计 fanout，表示生成代码对输入存储执行变化检查的完整范围；不是实际
变化字节数，也不是硬件缓存/内存流量。代理成本、调用次数、字节范围不可混为一谈。

搜索自动从 p9 移出 3 个 ASC，主要目的地为 p6；其余移动发生在其他分区，没有指定
这些分区的 ID 作为选择条件。后处理后的独立阶段探针显示：p9 的下沿成本从 406529
降到 379320（约 -6.7%），p6 的下沿成本从 286415 升至 338152，上沿从 261384 升至
301999。p2 和隔离的大 ASC 所在 p16 基本不变。因此这版候选主要检验下沿减负是否
能抵消接收方成本和额外复制，并不代表已解决全部瓶颈。

见 [结构、迁移与通信对账](../../build/repcut_grhsim_balance_20261013/stage/structural_report.json)、
[候选 post-pass 阶段成本](../../build/repcut_grhsim_balance_20261013/stage/stage_candidate.csv)、
[独立实验实现](../../build/repcut_grhsim_balance_20261013/stage_refine_impl.hpp)。

### 8.4 两轮 fresh AB/BA：eval 确有改善，wall 收益被 update 抵消大半

两轮均在 node030 CPU96--127 上使用未插桩 binary，C100000、N=K=32、all-spin、
Host CPU105/lane9、NUMA1、ASLR off、Clang23 O3/native、64B 对齐及代码 THP。
每轮 8 对、两侧均重新采样；第二轮从 BA 起始，交替 BA/AB，不复用第一轮任何计时。
共 32 次正式运行、4 次 C100 检查全部通过功能签名和 THP 检查；每次均有 80 MiB
代码完成大页映射。全部有效样本保留，没有按外部负载或好坏筛选。

下表百分比均为“先求每对 B/A-1，再取中位数”，不是左右中位数直接相除。

| 指标 | 第一轮 A / B 中位数 | 第一轮配对变化 | 第二轮 A / B 中位数 | 第二轮配对变化 |
| --- | ---: | ---: | ---: | ---: |
| Host walltime | 11.1545 / 11.0845 s | **-0.292%** | 11.1135 / 11.0135 s | **-0.547%** |
| elapsed walltime | 11.235 / 11.160 s | -0.356% | 11.195 / 11.090 s | -0.537% |
| 全局 eval | 43.460 / 42.196 us | **-2.061%** | 43.171 / 41.906 us | **-2.397%** |
| 全局 update | 8.7385 / 9.3290 us | **+7.472%** | 8.8500 / 9.4555 us | **+6.943%** |
| 分区 eval 总和 | 455.7655 / 469.1840 us | +1.941% | 453.9050 / 459.3915 us | +1.153% |

Host 分别赢 5/8、7/8 对；全局 eval **16/16 对改善**；update 只有 2/16 对改善。
16 对合并后，Host/elapsed 的配对中位变化约 **-0.401% / -0.402%**，eval 为
**-2.397%**，update 为 **+6.943%**。第一轮有明显顺序差异：AB 的 Host 中位变化
为 -2.285%，BA 为 +0.221%；反向起始的第二轮二者为 -0.241% / -1.914%。因此不能
只取有利顺序或单个快 run 宣称更大的 wall 收益。

这与优化目标相符但也暴露其不足：阶段均衡允许少量复制，分区 eval 总工作略增，
每一步等最慢 eval 的时间下降；然而总通信量的约束没有控制住最慢 update 的时间。
不能由“字节范围只增 0.09%”推导“update 开销也只能增 0.09%”。

原始结果：
[第一轮 8 对](../../build/repcut_grhsim_balance_20261013/stage/ab_ba_thp/summary.json)、
[反向起始的第二轮 8 对](../../build/repcut_grhsim_balance_20261013/stage/ab_ba_thp_reverse/summary.json)。

### 8.5 Fresh trace：eval 尾部改善和 update 退化分别发生在哪里

另用只替换四个包装层对象的 trace binary 采集 C100000 AB/BA，共 4 次正式运行；
A/B 分别保留 **7500 / 7523** 个其他 archive 对象逐字节不变。功能、THP 和计时对账
均通过；每份 trace 200102 步，剔除前 50 个 reset cycle。以下“瓶颈”仍指同一步
最长 callback，不是最晚到达屏障。插桩 walltime 不混入 §8.4。

| eval 指标 | A | B |
| --- | ---: | ---: |
| 全局上沿 eval | 39.593 us | 39.982 us |
| 全局下沿 eval | **47.049 us** | **44.624 us** |
| p9 下沿平均 eval | 32.601 us | 29.544 us |
| p9 下沿瓶颈占比 | **47.129%** | **23.833%** |
| p9 成为下沿瓶颈时的 eval | 55.960 us | 50.752 us |
| p11 下沿瓶颈占比 | 15.446% | 37.087% |
| p2 上沿瓶颈占比 | 41.551% | 41.382% |

p9 的减负真正降低了下沿尾部；p11 接过更多下沿瓶颈，p2 的上沿问题仍在。
新 trace 也验证了分区前的成本向量：A/B 的上沿 Pearson 分别为 0.6330 / 0.6346，
下沿为 0.6941 / 0.6939。post-pass 探针的 A/B 下沿 Pearson 为 0.7047 / 0.6887，
同图总权重仅为 0.1454 / 0.1244。该解释力在新采集数据上仍成立，但未达到精确排序
瓶颈或预测每个 cycle 的程度。

| update 指标 | A | B |
| --- | ---: | ---: |
| 全局 update，所有有效 step 平均 | 8.716 us | 9.470 us |
| 每步最慢 update callback，再取平均 | 6.962 us | 7.698 us |
| 二者差额 | 1.754 us | 1.772 us |
| p5 平均 update | 6.848 us | 7.680 us |
| p5 上沿平均 update | **9.901 us** | **11.419 us** |
| p5 下沿平均 update | 3.795 us | 3.941 us |
| p5 成为 update 瓶颈的比例 | **76.364%** | **96.564%** |

全局 update 增加约 0.753 us，其中每步最慢 callback 增加约 0.736 us，差额只增加
约 0.018 us。因此本轮退化主要已定位到实际 update callback，尤其是 p5 的上沿，
不能主要归因于 Host 屏障等待。

p5 的检查调用数只有 225→229，检查范围甚至从 **27305 B 降为 26920 B**。生成代码
仍是逐标量比较后写入，以及按 8 个 uint64_t 比较、有变化才 memcpy 64 字节的宽值
路径。仅凭这些静态数量，还不能区分变化块数、访问布局和并发缓存争用的影响；因此
另外采集实际变化写回计数，避免把“检查范围”误当作“实际发生的写流量”。

见 [逐半周期 eval](../../build/repcut_grhsim_balance_20261013/stage/critical_trace/report.json)、
[逐半周期 update](../../build/repcut_grhsim_balance_20261013/stage/update_trace_report.json)、
[新 trace 的阶段成本验证](../../build/repcut_grhsim_balance_20261013/stage/trace_validation.json)。

### 8.6 实际变化写回计数与本轮采用结论

为进一步区分数据量和执行效率，又制作了独立的 copy 计数版本：只替换 update 包装层
的 1 个对象，保留原标量“比较后写”和宽值“8 words 比较后按 64 B 写回”的语义，
统计调用、检查字节、实际标量写、64 B 写回块、尾部写和实际写出字节。计数器按发送
分区分开并对齐缓存行；不改模型计算对象，也不把计数版本的耗时当性能结果。

在相同 node030 核上另跑 C100000 AB/BA，两种 assignment 各重复 2 次。功能和 THP
通过，**每个分区的全部计数在两次重复中逐项完全一致**；32 个分区的调用数、检查
字节数均精确等于“生成代码静态数量 × 200102 step”。此处包括 reset，口径不同于
§8.5 去掉 reset 的 trace，但两侧完全一致。

| 每步平均的实际行为 | A | B |
| --- | ---: | ---: |
| 全部发送方写出的字节 | 43841.439 B | 43678.797 B |
| p5 写出的字节 | **5900.517 B** | **5865.455 B** |
| p5 写出的完整 64 B 块 | **87.547** | **86.809** |
| p5 标量写次数 | 8.917 | 8.204 |
| p5 尾部写次数（不足 64 B） | 9.294 | 10.875 |

p5 的实际写出字节约 **-0.594%**，完整 64 B 块约 **-0.844%**；全局实际写出字节也
略降。尾部碎片写有所增加，但没有出现能直接解释约 7% 全局 update 退化的数据量
增长。因此“总搬运数据增加”不是本轮 p5 退化的充分解释。访问位置、读写缓存行竞争、
分支及生成复制代码的执行效率仍需区分；**本轮尚未通过 PMU 或隔离实验确认其中哪一项
是主因，不能直接把缓存争用写成已证实根因**。

原始计数与复核见
[实际 copy 行为报告](../../build/repcut_grhsim_balance_20261013/stage/copy_counter/report.json)、
[通用计数器](../../build/repcut_grhsim_balance_20261013/copy_counter.hpp)。

本轮结论：

- **阶段维度有用。** 它在原、新 assignment 及新采集 trace 上都显著改善了负载解释力；
  整 ASC 候选也确实减轻 p9 下沿尾部，全局 eval 在 16/16 个未插桩配对中改善。
- **当前 wall 收益有限，暂不成为默认。** 两轮 Host 的配对中位收益只有约 0.3%–0.5%，
  被 update 的约 7% 退化抵消大半。保留该私有实验候选及数据，生产 RepCut、Verilator
  分配算法和现有默认选择均不改动。
- **下一步先补 update 约束及其成本依据。** 优先对照 A/B 的 p5 update 路径做有针对性的
  指令/缓存和访问布局诊断，然后将每个发送方的 update 尾部纳入 ASC 迁移评估；仅限制
  全局 communication km1 或总字节数不足。p2 的上沿成本误差仍保留为另一项明确问题，
  不将它误判成“现有 ASC 已经没有再均衡空间”。
