# TNO0001：ARMOR 的节点压缩值得在 GrhSIM 上试在哪里

**建议在单核 XiangShan 上验证“同一活动条件内，多级窄位逻辑共用一种布局”，用 CV32 做回归对照。** GrhSIM 已有组合树打包、共享归约掩码和等值译码。本次评估找到的增量机会，是让一个机器字承载多路不同的布尔值，并让下游继续使用这些位，省掉逐值物化、拆包和重复访存。首轮试验的价值取决于这种链在现有优化和 Clang 编译之后还剩多少。

论文为 Jiaping Tang 等发表于 MICRO 2026 的 *ARMOR: Accelerating RTL Simulation by Mitigating the Front-End Bottleneck Using Node Compression*。下文图号、算法和数字取自所给的 16 页会议版，DOI 为 `10.1109/MICRO67795.2026.00168`。本地评估对应父仓 `8f5bbdc`、Wolvrix `59e0f1e`。会议版 PDF（本机路径 `/nfs/home/tanghaojin/.paseo/uploads/upload_3a677eea-c04d-44ab-ad1f-16346bd9c283/476701c452.pdf`） · [MICRO 议程](https://microarch.org/micro59/program/) · [作者实现](https://github.com/jptang99-star/ARMOR)

## 论文如何把多路 RTL 计算变成一条指令序列

编译型仿真器展开 RTL 后，信号地址和依赖在编译时可知，但每个窄节点都可能生成自己的指令。作者在 Conv2D 和 BOOM 上观察到，每个仿真周期访问的指令工作集可达数百 KB 至数 MB，超过实验机的 32 KB L1I。这里的前端是**运行仿真器的宿主 CPU 的取指、译码和微操作供给**。ARMOR 保留展开和静态寻址，利用一个宿主整数中的空余位，同时计算多个独立节点。论文 §I–III，图 1–6

例如，8 个队列项各自计算 `eligible[i] = valid[i] & ready[i] & ~kill[i]`。若三个输入字的 bit `i` 始终代表队列项 `i`，几个标量位运算就能同时得到 8 个不同的答案。若下一级仲裁或归约也接收这个字，才有机会把中间的 8 次独立物化一起省掉。若输入要逐项收集、输出要立刻逐项拆回，转换成本就可能吃掉收益。这也是它与公共子表达式消除、抽共享函数和编译器 SIMD 向量化的区别。

| 环节 | ARMOR 的具体做法 | 为什么重要 |
| --- | --- | --- |
| 找到对应关系，算法 1 | 同时保留模块实例层次图、扁平数据流图和节点到实例的映射。先按模块类型分组，再按模块定义内的局部节点名，把不同实例中处于相同位置的节点汇入同一压缩域。 | 利用已有模块结构做近线性分组，避开在整图搜索任意同构子图。一次确定多级生产者和消费者的对应关系。 |
| 决定谁占哪些位，算法 2 | 压缩域再按拓扑层拆开，确保同包成员相互独立。设宿主字宽为 `W`，节点所有输入和结果的最大位宽为 `w`，初始包最多容纳 `floor(W/w)` 个成员。沿真实生产者到消费者的边扩展，让同一实例沿链占据相应位置，最后贪心合并同域、总宽度装得下的余包。 | 先复用布局，再提高填充率。图 6 中仅改变种子或下游配对，就能让同一计算从 3 次位重排增加到 7 次。 |
| 生成可正确执行的机器字运算，§IV-D | AND、OR、XOR、NOT 可逐位直接算。可并读写的寄存器值按包内次序存入一个字。常量位提取、某些移位使用 BMI2 的 `PEXT`／`PDEP`。窄字段相等可用 XOR、逐位抽取、OR 归约求每个字段的结果，作者指出通常只对约 4 bit 及以下划算。 | 普通机器字比较只返回一个结果，普通加法还可能向相邻字段进位。每类跨字段运算都需要独立语义和成本证明。 |

对 CPU 中常见的“一份源值与多个不同常量比较”，ARMOR 还有单独处理。它用至多 512 项、64 B 的位表表示互斥结果，源值更新时清旧位、置新位。论文主要用标量机器字承载压缩，SIMD 可再并行处理多个字。缺少 BMI2 时，论文提出只压缩无需跨字段操作的部分。论文 §IV、§VI

## 实验能支持多强的判断

| 会议版结果 | 应怎样解读 |
| --- | --- |
| 平均约 57% 的节点被压缩，加入 pack/unpack 等重排开销后，图规模净减 **34.51%**（图 9）。图 10 单列 Conv2D-16×16 和 BOOM-8C，静态指令平均少 **29.4%**，动态指令少 **24.54%**。 | 节点覆盖、净图规模、宿主指令数是不同口径。图 9 单列的重排开销已经达到原图节点数的 22.7%。 |
| CPU 设计平均 **1.63×**，AI 加速器平均 **2.69×**（图 11）。 | 分母是 **RepCut**。主表 CPU 使用 2／8 核 BOOM、8 核 Rocket 等配置。图 15 也测了单核 BOOM，相对 RepCut 约 **1.79×**，说明单核内部同样可能有足够的并行结构。 |
| 同一 ARMOR 框架以关闭节点压缩为基线，完整方案在 BOOM-8C 为 **1.59×**，取消模块感知发现后只有 **1.16×**。Conv2D-16×16 和 Gemmini-32×32 的完整方案分别为 **2.08×**、**2.50×**（图 19c）。 | 这是更接近迁移问题的消融。稳定的跨实例对应关系有独立价值。图 19a/b 在作者所测配置上切换编译器 SLP 和 O2/O3 的提升小于 5%。 |
| 平均 front-end bound 为 ARMOR **47.6%**、Verilator **76.1%**。作者另查供给不足的微操作数、L1I miss 及 MPKI（图 12–13）。 | 两个百分比各自以本程序的可用流水线槽位为分母，不能相减换算成节省的秒数。图 14 的字内有效位占比由 25.57% 升至 45.61%，也不能直接换算成加速比。 |

论文实验主要使用 FIRRTL 输入、全周期求值、Intel Xeon Platinum 8338 和 Clang 12 `-O2`。其跨模拟器比较包含 ESSENT 和 Dedup 等事件驱动实现，作者也讨论了节点压缩与事件驱动、分区仿真的兼容性。GrhSIM 的活动通知、条件锥、数据布局和测量主机都会改变净收益。论文 §V–VI，表 I

## GrhSIM 已有的能力和剩余空间

**已有实现比“逐节点仿真”更接近 ARMOR。** XiangShan 生成流程在 `hier-flatten` 后通常执行 `comb-lane-pack`，关闭 declared roots，从存储写数据端等根寻找签名相同的组合树。它检查根间依赖，能把等宽按位树合并成宽运算，能为 mux 构造掩码，叶子用 concat，根用 slice 接回原消费者。历史一次 XS 运行已经得到 4,161 组、55,863 个根。它按根签名和操作序号邻近性分组，没有实现 ARMOR 在压缩域间沿消费者扩展、协调不同包布局的完整算法。[XS 流程](../../scripts/wolvrix_xs_grhsim.py) · [打包实现](../../wolvrix/lib/transform/comb_lane_pack.cpp) · [历史覆盖及未命中例](../grhsim_opt/NO0030_sched124_llvm_ir_gvn_memdep_root_cause_20260424.md)

**现有根筛选恰好漏掉最窄的一类。** 缺省 `minGroupSize=4`、`minPackedWidth=32`。收集根时先检查 `rootWidth × minGroupSize`；在这些参数下，1–7 bit 的根在尝试更多成员前就被过滤。例如，64 个独立的一位 AND 可以占满一个字，但单个根先算出 `1 × 4 < 32`。这只描述此 pass 的根资格，树的条件输入、后续 emitter 规则以及 Clang 仍可优化窄值。把阈值直接放宽也解决不了作用域和拆装问题。[默认参数](../../wolvrix/include/transform/comb_lane_pack.hpp) · [根筛选](../../wolvrix/lib/transform/comb_lane_pack.cpp#L719)

**已有真机正例，也有反例。** XiangShan 的标量 concat 归约父规则及其命中路径做过单核八对，开启后 walltime 降低 **9.97%**。其中有多个谓词复用一个输入掩码，也有宽 concat 的专用 lowering，这一整组开关的收益已经计入后续基线。相反，FTQ 曾因合并共同激活的范围过大，让一个字段变化带动 64 份独立数组构造，物理 lane 步长也从 1 B 变成 64 B；后续 connected 方案恢复了连续访问。已有 shared-equality 还会稀疏地清旧谓词、置新谓词，保留原 reader 通知，ARMOR 的 Eq 表在这里与现有方案重叠。[归约八对](../kunminghu_v3_grhsim_merge_20261110/TNO0072_scalar_concat_reduction_parent_default_20261114.md) · [FTQ 布局与激活](../cv32e40p_grhsim_20261114/TNO0046_cv32_xiangshan_optimization_asymmetry_20261117.md) · [等值译码](../../wolvrix/docs/emit/grhsim-shared-equality-decode.md)

### 本次静态核验

1. **窄位逻辑有足够的原始规模。** 复用 CV32 系列 TNO0026 的单核 `DefaultConfig` 冻结图，在既有前端 lowering 和 `comb-lane-pack` 之后、RepCut 和活动调度之前计数。沿用其存活性定义，从公开输出及状态／副作用等边界回溯。在 5,174,672 个存活纯组合操作中，**1,714,885 个（33.14%）**为全部输入和输出均为 1 bit 的 `kAnd/kOr/kXor/kNot`。其中 **1,202,815 个**至少直接流向另一个属于这四类的一位操作；进一步限定非公开结果且只有一次存活使用，仍有 **980,717 个**。按生产者唯一计数，允许相邻链重叠。此数只证明多级位运算大量存在；同形并行的份数、实际活动条件、布局、已融合的机器指令和执行频率仍待核定。[图的来源与存活性口径](../cv32e40p_grhsim_20261114/TNO0026_xiangshan_unpartitioned_mux_opportunity_20261115.md) · [统计结果](../../build/armor-paper-review/graph-counts.json)
2. **机器码已经利用了部分表面并行。** 在 CV32 系列 TNO0049 冻结 XS 的 `eval_compute_batch_0()`、supernode 520 中，D-cache `probeQueue` 八个 entry 各把 2-bit 状态归约成一个 valid。八个状态实际占连续八字节。核对字段偏移后可见，地址 `0xd3014` 的一条 `vmovq` 已读入八路，向量掩码计算后，`0xd305b` 的 `cmpq` 和 `0xd3062` 的 `vmovq` 已把八个 valid 一起比较、写回。然而同一组末尾又读出八个 Boolean 字节求和。可检验的假设是将已有的八位谓词掩码直接用于 `popcount`，同时满足原有标量消费者和通知。这是说明如何计算**增量**的实例；其动态权重尚未测量，也不能拿一个计数器代表整机。[字段、输入与 ELF 身份](../../build/armor-paper-review/baseline.json) · [目标反汇编](../../build/armor-paper-review/probequeue.s)
3. **前端瓶颈仍是待测假设。** 直接读取 CV32 系列 TNO0049 候选 ELF 的 `.text`，XiangShan 为 **88,856,754 B**，CV32 为 **69,309 B**。这是完整可执行文件的静态节大小，每个 guest cycle 实际触及哪些代码取决于活动分布。两侧沿用 CV32 系列 TNO0049 启用 shared-arm 的实验配置；CV32 系列 TNO0050 在同一配置上验证了快照选项取新默认时的源码身份。以前的 XS PMU 有过 I-cache 和 ITLB miss 密度下降、前端整周期无操作的空槽反而增加的实例，不能仅凭代码大就归因为 L1I 容量。本次只读冻结数据和 ELF，没有新增仿真计时或 PMU 样本。[冻结候选](../cv32e40p_grhsim_20261114/TNO0049_indexed_concat_snapshot_arrays_20261117.md) · [配置身份](../cv32e40p_grhsim_20261114/TNO0050_indexed_snapshot_default_20261117.md) · [历史前端 PMU](../grhsim_opt/NO0317_no0286_no0300_frontend_latency_itlb_gate_20260712.md)

## 建议的首轮实验与停止条件

1. **先量合法覆盖与宿主瓶颈。** 在现有调度及存储计划上做只读统计，按同一 compute supernode、同一实际 guard／mux 分支、同一快照时点分桶。收集同层无依赖的平行链，报告每包有效位、连续使用 packed 结果的层数、入口 gather、重排、出口 extract、仍需维护的标量槽，以及与既有 lowering 的重叠。层次线索可取自 flatten 前的“特化后的模块定义、局部节点、实例”映射，扁平 GRH 再验证操作、位宽和边；经过 Yosys 或 simplify 后只剩生成名字的节点可用局部结构签名作候选。单核 XS 优先调查队列 entry 的 valid/ready、唤醒匹配后的布尔网和重复译码。模块名用于解释统计，生成规则仅依据静态结构。[层次扁平化](../../wolvrix/docs/transform/hier-flatten.md) · [活动调度语义](../../wolvrix/docs/emit/grhsim-scheduling.md)
2. **一个小原型就能区分机制。** 同一活动条件内先支持一位 AND/OR/XOR/NOT，使用 `uint64_t`，优先选择能跨多级使用、或直接被归约／计数消费的包。初版保留持久状态布局和所有 guard，只在原有快照时点取值。需要逐 lane 通知时，由 `(old_word ^ new_word) & valid_mask` 还原各 lane 的原 reader 集合。跨时钟、compute→commit、memory intent、DPI、公开观测和缓存所有权都是需要证明的边界。掩码之外的无效位尤其要在 NOT、比较和归约时屏蔽。Eq LUT、BMI2 特化、持久状态打包、跨组或跨线程合并分别留给有独立证据的后续实验。
3. **用同一个 GrhSIM 关／开比较净效果。** 在 node030 的 AMD EPYC 9684X 上，先独立采集基线，区分 compute、commit 和 host harness/NEMU。按 guest cycle 报告退休指令、host cycles、L1I miss、前端供给空槽，并检查分支失败、op-cache/iTLB 与新增数据访问。该机提供 `de_no_dispatch_per_slot.no_ops_from_frontend` 和 `ic_tag_hit_miss.instruction_cache_miss`，可结合前端延迟／带宽指标使用。再对同一冻结输入、Clang 23 `-O3 -march=native` 进行源码和目标函数 ELF 对照。功能先过逐 lane 参考值、初始化／重置／重复 eval、精确通知，再过 XS 双 seed 100k DiffTest 和 CV32 完整 CoreMark 总线轨迹。整机性能沿用 node030 CPU96／NUMA1 串行配对，计数另采，规则冻结后再看 walltime。

若同一 guard 内的大部分候选已被宿主编译器向量化，或每经过一级都要拆包、静态净节省很小，就可以在覆盖审计后结束这条路线。若代表性链的目标代码确实缩短、有效活动范围也保持一致，再投入整机验证。**是否值得继续取决于能保留多少跨级复用，以及这些链在真实仿真窗口里占了多少宿主工作。**

后续各轮的实验记录见[目录索引](./README.md)。
