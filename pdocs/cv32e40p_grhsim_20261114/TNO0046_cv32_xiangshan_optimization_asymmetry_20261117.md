# TNO0046：CV32 与 XiangShan 优化收益为何不同

**主要原因是可消除工作的覆盖比例不同，以及跨优化阶段的反向成本。在 CV32 上，恢复 word 表示、收缩事件尾部和消除状态视图边界，消掉了原实现的大块冗余；在 XiangShan 上，同类机会占比小得多，原共享规则又引入了活动细分、访问布局退化和额外控制流。最新候选已修复其中一部分，但仍未把局部计算节省稳定转化为超过旧版的整机收益。**

这不说明 XiangShan 没有优化空间，也不能把结果单独归因于设计规模、编译器或 DiffTest。下文区分已验证事实、历史消融和仍待定量的机制解释。

本轮只读取冻结 C++、ELF、源码配置及已有测量，重新编译 offsetof 常量并反汇编两个当前函数。未执行模拟器、采集 PMU、重新计时、改变生产代码或生成候选。新分析脚本见 [grhsim_cross_design_analysis.py](../../scripts/grhsim_cross_design_analysis.py)，[机器可读结果](../../build/xs/cross-design-explanation-v1/report.json)。

## 1. 先固定比较边界

XiangShan 的正式直接结果是 TNO0045：优化前 `74d80cf` 与最新 connected-shared 候选在 node030 CPU96 上固定八对，walltime **−0.0692%**，95% CI **[−0.1485%, −0.0075%]**，均值 114.530630→114.451320 s。工程意义上基本持平。它替代此前把不同轮次串接得到的约 −1.18% 估算。[正式结果](./TNO0045_pre_cv32_vs_connected_formal_20261117.md)

CV32 的“大幅收益”由多轮独立对照支持：indexed-concat −11.92%、concat/slice 合并 −35.61%、共享等值译码 −7.76%、事件区域与首次使用顺序 −18.65%、条件锥 −4.40%、简单状态视图 −3.11%、复合状态表达式 −3.52%。这些是相应阶段对其同轮基线的结果，**不能相加，也不在本轮拼出一个累计置信区间**。最新 connected 候选相对此前 full 又改善约 0.57%，该轮是三对初测。

两个负载的范围不同：CV32 是十迭代完整 CoreMark、3,376,065 周期与总线 trace 验证；XiangShan 是 CoreMark 两迭代镜像的前 100k 周期，完整 DiffTest/NEMU，停止于 cycle limit。CPU96/NUMA1/ASLR off 一致不意味着工作负载阶段、调试硬件或宿主框架相同。因此不能从两边绝对秒数或每 guest cycle 成本推断某个算法的可迁移收益。

## 2. CV32 的早期大收益包含“修复输入表示的放大”

| 层面 | 当前 CV32 基准 | 当前 XiangShan 基准 | 对优化的含义 |
| --- | --- | --- | --- |
| 核心与外围 | RV32、四级顺序流水；FPU/CORE-V 扩展关闭；简单 RAM、确定性单周期响应，无随机 stall/外部 IRQ | RV64 DefaultConfig；源码默认八路 decode/rename/commit，含 ROB/多发射队列、FTQ、TLB/cache、FP/vector 及观测逻辑 | XS 有大量独立状态与多消费者，不能期待少数标量变换覆盖大部分工作 |
| 导入表示 | sv2v + Yosys proc/flatten/splitnets；整数寄存器堆一度成为逐 bit concat | Chisel 生成设计，经已有 packed-lane、memory/reg-to-mem 等路径；旧版已经存在专用数组读取 | CV32 的机会部分来自恢复被归一化拆散的 word/数组结构 |
| 当前生成规模 | 25 个全部区域，3 个 compute 主函数；compute 静态指令 10,565 | 84,690 个 compute 区域、346 个 commit 区域；66 个 compute 主函数；compute 静态指令 13,755,365 | 新增一个入口或一套控制协议在 XS 上可能复制到数万个位置 |
| ELF `.text` | 初始 207,991 B → 当前 72,637 B | 初始 91,922,786 B → 当前 88,889,586 B | CV32 的代码结构缩减是数量级更大的比例；`.text` 仍不是动态时间 |

设计依据：[CV32 fixture](../../testcase/cv32e40p-bench/README.md)、[原 CV32 描述](../../build/cv32e40p/run2/inputs/cv32e40p/README.md)、[XS 默认配置](../../testcase/xiangshan/src/main/scala/top/Configs.scala)、[XS 参数](../../testcase/xiangshan/src/main/scala/xiangshan/Parameters.scala)。参数描述的是硬件配置，不意味着相应单元在本窗口内都繁忙。FP/vector 等控制和观测逻辑存在，也不证明其占了多少动态时间。

CV32 的两个寄存器堆 concat 各有 **993 个 operand**，读 32 bit 前先拼出 1024 bit；同源 slice 合并后变为 **32 个 operand**。相应阶段 bool 槽 3142→1038，全部调度组 183→69，ELF `.text` 192,295→102,249 B，退休指令约下降 31.43%。所以 −35.61% 并非普通小型 CSE 的普遍效果，而是一次同时改变数据表示、物化和活动边界的修复。[TNO0005](./TNO0005_concat_slice_coalescing_20261114.md)

相同 simplify 变化在 XS 上只使约 592 万 op 中的 Concat 少 107、SliceStatic 少 2090；不能仅从 op 数定性能，但结合生成形态，确实没有复现 CV32 的两个巨大逐 bit 寄存器堆热点。XS 旧 emitter 已有 814 个专用 packed view 和 2624 个 select，初次迁移反而降到 807/2598。**旧版 XS 已经利用的表示优势，不能再次算作 CV32 新规则的新增收益。**[TNO0043](./TNO0043_cv32_series_xiangshan_codegen_lineage_20261116.md)

也不能把“32 位对 64 位”本身作为主因：两者标量均可落在宿主 64 位计算中。更重要的是位段/数组是否被保留，以及多输入计算、状态边界和消费方式。

## 3. 状态视图和事件尾部的适用比例悬殊

CV32 的同事件尾部规则一次就把受跟踪值 **990→413**，持久标量槽 **1282→704**。后续简单及复合状态视图在 209 个受跟踪值中覆盖 **21+70=91 个**；对应已有计数从 **167.26→82.84 次检查/周期**。最新 connected 候选保留逐项相同的 91 个视图，检查为 84.57 次/周期，差异来自区域恢复后少数检查执行次数改变。[TNO0014](./TNO0014_event_regions_and_use_order_20261115.md)、[TNO0032](./TNO0032_composed_state_expressions_and_entry_guard_20261115.md)、[TNO0044](./TNO0044_connected_shared_candidates_20261116.md)

XS 最新候选有 **2551 个 covered view，其中 1155 个复合表达式**；原始版本有 762,833 个受检查值。2551 仅相当于该分母的 **0.33% 量级**，不能当作动态收益百分比。最新不同 scalar 检查值为 687,318，源码检查位置为 700,624；位置会因条件/缓存分支重复，二者必须分开。总减少还包含区域局部化等，不能把它全归给状态视图。

当前证明只处理纯 scalar 表达式，叶子归于同一单写者寄存器，且生产者和全部消费者已经拥有独立寄存器激活路径；事件、缓存、别名、memory/intent 和公开观测用途都构成边界。简单流水中的指令字段和控制位容易满足；XS 的多源队列选择、依赖唤醒、memory intent、提交/观测路径则不是同一类问题。这里对 XS 的具体拒绝原因还没有全图分类，不能把 CV32 的拒绝统计外推过去。[证明实现](../../wolvrix/lib/emit/grhsim_cpp.cpp)、[规则说明](../../wolvrix/docs/emit/grhsim-covered-state-views.md)

条件计算也有相同的覆盖缺口。XS 最新命中 11,540 个 cone、188 个输入缓存；之前全图静态分析的“约 25%–28% 潜力”允许更广的嵌套、共享和宽值，并假设 selector 概率；当前 emitter 仍受区域、单使用/纯 scalar、16–256 op 等条件限制。**全图潜力没有等额落地为当前可跳过的宿主工作。** 这些静态假设值不是 walltime 预测。[TNO0026](./TNO0026_xiangshan_unpartitioned_mux_opportunity_20261115.md)

## 4. 同终点不等于共享计算：最主要的历史退化已有消融支撑

CV32 的主共享组是一个 621-op 计算连通分量，内部化 **765 条旧跨组计算 operand 边**，因此有大量真实中间接口可消除。XS 原 6542 个共享候选中，**4647 个计算不连通、3090 个没有消除旧计算边界，其中2087个还切出了新边界**。同一个终点集合可能包含很多相互独立的队列字段，并不说明它们适合共用活动位。

FTQ 的旧坏例子尤其明确：64 个独立 concat、4096 个状态被放进同一组，一个字段变化即可激活全部数组构造及出口通知。合并又让状态读者签名趋同，使字段 lane 的地址步长 **1 B→64 B**。原本可用向量 load/mask/store 的路径变成逐字节拼接，单数组出现63条 `vpinsrb`。这是候选选择、状态布局和 SIMD 生成的相互作用，不只是调度函数多了一次调用。[TNO0039](./TNO0039_shared_region_layout_activity_and_lifetimes_20261116.md)

历史八轮消融关闭 shared：8/8 更快，walltime 均值约 −6.60%；独立 PMU 退休指令 −4.08%、branch-misses −8.26%。它是整个机制的总效应，连带改变 cones/cache/views，不能全归给一个循环或 FTQ 单点。该轮波动较大，幅度不是固定常数。[TNO0035](./TNO0035_xiangshan_shared_regions_and_cones_ablation_20261116.md)

最新 connected 规则已经修正候选组成，结合局部 SCC，细分旧组 **10,388→2433**，compute 组 **97,204→84,690**；FTQ 已恢复64个独立组和1 B lane步长。当前同一数组的构造核心回到三条向量指令。因此 **不能再把 FTQ 的63条拼接当成当前瓶颈**。这一轮主要是在恢复初次迁移丢失的性能，而不是已经证明相对最初旧版存在8%的净收益；正式旧/新八对仍是 −0.0692%。

直接全关 shared 也不是跨模型答案：CV32 曾失去77个状态视图，实际独立激活前沿不再满足证明；跨区域追溯本身无法恢复。优化资格与调度形态是联动的，不能独立把每个开关收益相加。[TNO0038](./TNO0038_cross_region_state_expression_proofs_20261116.md)

## 5. 最新 C++/ELF 仍显示“少算术、更多控制”的交换

本轮从两端冻结报告重新逐项计算，校验全部 **140+140 个生成文件**及测量 ELF 身份：

| XS 指标 | 优化前 | 当前最新 | 变化 |
| --- | ---: | ---: | ---: |
| compute 区域 | 77,041 | 84,690 | +9.93% |
| compute 组入口检查位置 | 74,427 | 82,067 | +10.27% |
| compute 活动字检查位置 | 9,653 | 10,587 | +9.68% |
| compute 持久活动更新位置 | 475,136 | 479,924 | +1.01% |
| scalar 检查源码位置 | 762,833 | 700,624 | −8.15% |
| compute ELF 静态指令 | 14,303,483 | 13,755,365 | −3.83% |
| compute ELF 条件跳转 | 524,790 | 563,299 | +7.34% |
| compute 带内存操作数指令，排除 lea/nop | 5,730,033 | 5,480,957 | −4.35% |
| compute RSP 相对访存位置 | 1,181,765 | 1,129,226 | −4.45% |
| 66 个 compute 主体入口栈减法中位数 | 1304 B | 2008 B | 增大 |
| 入口栈减法最大值 / 超4 KiB主体数 | 6008 B / 3 | 20,616 B / 15 | 增大 |
| commit ELF 静态指令 | 2,582,410 | 2,563,328 | −0.74% |

表中所有源码/ELF计数都是静态量，**不代表执行次数、branch-miss率、spill流量或时间份额**。栈帧变大与RSP操作数总量下降同时成立，不能声称全局spill必然增加。`.text` 约88.9MB说明宿主面对的代码规模与CV32相差很大，但没有当前I-cache/iTLB/frontend-stall证据，不能直接断言已被指令缓存主导。

历史 cone-off 消融提供一个具体成本交换：关闭条件锥后退休指令 **增加1.77%**，branch-misses **减少5.37%**，walltime CI跨零。它证明条件锥在XS确实省了计算，同时付出控制流代价；不能把它描述成“完全无效”，也不能凭跳转多就一律删除。上述计数是旧full消融，不能冒充最新candidate/old的动态PMU。

compute→commit的暂存、状态比较、读者通知，以及未命中的内存/队列/多输入组合仍大体保留。commit静态只降0.74%是覆盖边界证据；没有当前动态阶段占比，不能据此认定commit占了大多数时间。完整DiffTest/NEMU及debug数据也是同一边界：它们会稀释模型局部改进，但尚未测得当前份额，不能将其当作主要解释。

## 6. 两个当前仍存在的表示组合缺口，重新绑定了最新 ELF

**相邻 slice 合并可能破坏已有 lane 专用表示。** `redundant_elim` 合并concat操作数，emitter的`buildPackedArrayLaneViewFromConcat`则要求操作数与等宽lane元数据一致。旧审计确认7个宽view、26个读取降级。当前 bitmapcache 的同一 `_op_12496825` / `_val_11840339` 仍使用 `grhsim_slice_words<1>`。

用当前header编译偏移，确认array/index/result分别为对象偏移`0x1f9c68`、`0x12f680`、`0xe192c`；在当前batch12，入口`0xe5e683`和尾部`0xec7e19`保留 **17条静态指令、2个条件跳转、额外word读取与shrd**。旧版读取核心为5条。合法index为0..31，每次4bit且start=index×4，数学上不跨64-bit边界；通用路径没有利用这个事实。17条含两条分支路径，且不含构造端成本，不能直接解释为每次比旧版多12条。[当前源码](../../build/xs/cross-design-explanation-v1/latest-bitmapcache.cpp.txt)、[当前入口](../../build/xs/cross-design-explanation-v1/latest-bitmapcache-entry.s)、[当前尾部](../../build/xs/cross-design-explanation-v1/latest-bitmapcache-tail.s)

**按word读取还没有消除快照与捕获准备。** 当前ROB的256-bit concat最终只读1bit，源码仍先保留256个bool快照，再建立`[&]`word-reader。它已从旧batch20移到当前batch19，不能沿用旧函数地址。本轮在`0x1551088..0x155207f`逐项核对 **256次指针写、RSP+0x16b0..0x1ea8、共2048B捕获对象**，随后`0x155209c`调用helper。当前helper为737条静态指令、280B栈减法，按选中字先拼64bit再截成1bit。[当前捕获窗口](../../build/xs/cross-design-explanation-v1/latest-closure-window.s)、[当前helper](../../build/xs/cross-design-explanation-v1/latest-helper19.s)

当前独立word-reader共有11个，少于初次迁移的15个，但这个256快照案例仍在。该点来自ROB的`debug_lsTopdownInfo`观测数据，既展示了控制/调试路径的实际生成成本，也说明不能按CoreMark没有使用某架构特性便删除相关硬件。

这两处都与CV32主收益相反：CV32从逐bit重新得到word；XS却有已有lane读取退回通用words，以及小结果仍承担整批快照准备。**它们是明确的待修结构点，但运行频率和净时间份额未知，不能承诺修掉两点就会获得若干个百分点。**

## 7. 原因的证据强度与下一步含义

| 判断 | 已有证据 | 尚缺什么 |
| --- | --- | --- |
| CV32主要收益来自高覆盖率冗余表示/边界削减 | 同轮计时、逐值计数、C++、ELF、PMU相互支持 | 无需假设其比例能外推到XS |
| 原XS共享处理是迁移退化的重要来源 | 八轮消融方向一致、动态指令/分支失败下降、布局及活动路径实例 | 内部各因素的精确时间分摊 |
| 最新规则恢复了布局和部分调度成本 | 同一FTQ字段/操作身份、偏移和ELF核验；正式旧/新基本持平 | 当前各区域的动态加权成本 |
| 其他优化在XS的适用范围较小，且仍有组合缺口 | 状态视图覆盖、当前17指令读取及2KiB捕获证据 | 全图拒绝原因分类、这些点的动态份额 |
| 编译器控制流/代码与数据工作集可能抵消计算节省 | 当前静态形态、历史cones消融的计算/branch-miss取舍 | 当前旧/新同协议PMU及分类归因，尤其frontend/cache/stall |

下一步的重点应是保留已有lane/数组语义，按结果bit/元素需求降低读取，并把状态快照表示做得紧凑；调度侧继续把计算连通、精确激活、存储布局和临时生命周期一起考虑。覆盖率分析应区分单寄存器视图、多状态表达式、memory intent、effect/debug和真正跨执行阶段的缓存，不能继续只扩大现有标量规则的预算。

如后续补动态诊断，应固定最新/旧两端与相同窗口，区分compute/commit/harness/NEMU和控制流代价；仅用于验证、归因，不输入生成器选择站点或阈值。此次没有启动该实验。

## 核验与复现

```sh
python3 scripts/grhsim_cross_design_analysis.py --output build/xs/cross-design-explanation-reproduce
```

脚本验证两份XS ELF和280个生成文件、两份CV32 ELF；读取既有静态统计，重新统计当前规则与不同检查值；对当前函数反汇编，并只编译offsetof探针，不运行生成程序。早期探针未加`-fno-access-control`而被私有成员访问检查拒绝，补齐已有分析所用编译选项后成功，没有改生成header。分析结果中的输入、输出及脚本身份供复核；记录与链接检查见[validation.json](../../build/xs/cross-design-explanation-v1/validation.json)。
