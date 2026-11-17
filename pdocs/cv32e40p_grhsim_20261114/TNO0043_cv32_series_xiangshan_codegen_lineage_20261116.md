# TNO0043：从 Wolvrix 改动重新追溯 XiangShan 的 C++ 与 ELF 变化

用户要求重新调查引入 CV32 系列优化前后的结构变化及其代码来源。本轮比较 `74d80cf`、`8523dc1` 的冻结生成器/模型，并用最近的修复版、消融版作分层参照。**没有修改生产代码、生成新模拟器、执行仿真、采集 PMU 或新增计时。** 新 C++ 工具只用对应冻结库重放 simplify/schedule，输出静态清单；辅助 offsetof 编译只用于绑定已有 ELF。

主要结论有三条：

1. 共享候选池化是最值得优先重构的系统性问题。终点集合相同不保证共享计算；全图静态对齐发现 3,090 个候选未消除计算之间的旧边界，其中 2,087 个反而产生新边界。
2. 简化器的相邻 slice 合并破坏了 7 个既有 packed-array 表示，影响 26 个读取。一个已绑定 ELF 的读取从直接字节加载变成通用跨 word 取片段，存在明确的表示组合缺口。
3. 新增默认开启的 indexed-concat 并不总是避免上游准备：一个 1-bit 读取生成捕获 256 个快照的 lambda，ELF 调用前构造了 2 KiB 指针捕获对象。需要把快照与捕获准备也纳入按需读取设计。

这三条是实现与机器码证据，尚未将原始 7.17% 的时间回退精确分摊。此前的 FTQ/ROB 数组局部改写有效，但基本没有改变活动组与控制流规模，这正是继续只修数组难以解决整机问题的原因之一。

## 1. 版本边界与实际进入流水线的改动

原始对照 [TNO0033](./TNO0033_xiangshan_cv32_optimization_transfer_20261116.md)：同一 4 GB `pre_reg_to_mem.json`，分别用 `74d80cf` 与 `8523dc1` 的 native 库、匹配头文件，执行 two-state simplify、ordered reg-to-mem、activity-schedule、emit。完整 DiffTest，Clang 23.1.2、C++20、O3、march=native；两侧均无 profile 输入或 PGO/BOLT。

`74d80cf..8523dc1` 的生产目录差异共 9 个文件、增加 3,697 行、删除 27 行：主要为 emitter 2,219/20 行、activity_schedule 581/0 行、redundant_elim 94/7 行。其余包括两个实验 transform 及注册/选项，并非全部进入本次流水线。[精确生产 patch](../../build/xs/cv32-lineage-audit-v1/production-series.patch)

| Wolvrix 改动 | 本次是否执行 | XiangShan after 的生成结果 | 主要结构影响 |
| --- | --- | --- | --- |
| `redundant_elim` 合并同源相邻 SliceStatic | simplify 中自动执行 | simplify 后 Concat −107、SliceStatic −2,090 | 恢复 word 运算；也可能破坏已有 lane 元数据形态 |
| `buildEventRegions` 单终点收缩 | 显式启用 | 13 个区域、20,425 ops | 收缩局部计算边界 |
| `buildSharedEventRegions` 多终点共享 | 显式启用 | 6,542 个候选、1,078,464 ops；细分 10,388 个旧混合组 | 边界减少与新增入口/通知/活动扩大同时发生 |
| `orderEventRegionByUse` 首次使用排序 | 随区域规则执行 | 共享候选的静态 live-step 176,790,616→57,628,068 | 改善 IR 顺序；不保证 C++ 对象生命周期或最终寄存器分配 |
| `packed_scalar_slices` | **新增默认开启** | 391 个八 bit 打包写组 | 精确逐 bit 判变；改变 bool 槽读写方式 |
| `shared_equality_decode` + families | 前者新增默认开启，后者显式开启 | 129 个 decode，含 117 个 family、5,058 个 family 谓词 | 引入地址/valid 检查及稀疏状态更新 |
| `indexed_concat_slice` | **新增默认开启** | 15 个按 word 选取点；15 个独立 word-reader lambda 出现在 ELF | 选择部分 word，但可能保留全部快照及捕获准备 |
| conditional mux cones / input cache | 显式启用 | 11,563 个 cone、215 个缓存 | 少做未选分支计算，同时新增控制与缓存维护 |
| covered state views / composition | 显式启用 | 2,870 个 view，含 1,456 个复合证明 | 减少部分持久中间值，收益依赖区域与激活前沿 |
| predicate-set / slice-demand pass | **未调用** | 无 | 不能当成本次回退的原因 |
| wide-demand、local-predicate、change-cache/grouped/joint 等 | **默认关闭且未启用** | 无 | 不纳入这次前后归因 |

`scalar_concat_reduction` 在 before 已默认开启，不能重复记为本次新增；reg-to-mem 实现与 simplify 驱动本身在两个提交间未改，实际 simplify 差异来自 `redundant_elim`。后续 TNO0036–42 的成本门、局部 SCC、跨区域证明、布局、scope、no-init/select 属于另一个时间层，不能反过来解释最初迁移。

“必须保留完整 compute node”是区域实现的归属约束，两侧 oversized split 日志实际均为零。关闭拆分开关不等于本图发生了大规模取消拆分。

## 2. 宏观变化：compute 控制结构扩大，局部优化没有逆转它

| 指标 | before | after | 最新 corrected full + layout/no-init/select |
| --- | ---: | ---: | ---: |
| compute 组 | 77,041 | 97,204 | 97,204 |
| compute 单组入口源码检查 | 74,427 | 94,581 | 保持 after 结构 |
| compute 活动字检查 | 9,653 | 12,151 | 保持 after 结构 |
| compute 活动数组更新源码位置 | 475,136 | 519,217 | 保持 after 结构 |
| compute ELF 静态指令 | 14,303,483 | 14,105,230 | 14,100,956 |
| compute ELF 条件跳转 | 524,790 | 590,475 | 590,473 |

原始迁移减少了代码总量，但组入口增加 27.08%、活动更新位置增加 9.28%、机器条件跳转增加 12.52%。静态指令更少与运行更慢并不矛盾；更新位置也不等同实际内存写次数。

TNO0042 最近组合相对其共同 corrected full，仅减少 7,828 条 compute 静态指令，约 **0.0555%**；条件跳转从 590,476 降到 590,473。它没有改变区域或活动协议。ROB 一个组从 1,604 条降到 107 条是局部事实，不能代表整机的主要动态工作已经消除。

历史消融进一步区分来源：

| `8523dc1` 冻结版本 | compute 静态指令 | 条件跳转 | 已有独立 PMU 退休指令/guest cycle |
| --- | ---: | ---: | ---: |
| full | 14,105,230 | 590,475 | 3,925,948.295 |
| no_shared | 14,271,836 | 544,688 | 3,765,676.520 |
| no_cones | 14,063,213 | 572,475 | 3,995,401.297 |

共享关闭后静态指令反而增加，动态指令减少约 4.08%；关闭 cones 后静态更小，但动态指令增加约 1.77%。这支持优先处理共享候选与活动结构，同时保留条件计算的真实价值。不能把两次消融相加，也不能把 no_shared 与另一轮 before 的绝对时间直接相减。

PMU 是 [TNO0035](./TNO0035_xiangshan_shared_regions_and_cones_ablation_20261116.md) 已有单次记录，包含 harness/NEMU，启动有短暂遗漏，无本轮新采样。TNO0042 的 corrected no_shared 仍比 corrected full 快 3.65%，也只是该轮固定窗口结果。

## 3. 共享候选：全图精确对齐了什么

用 `8523dc1` 冻结库分别重放 shared/on 与 shared/off 静态流水线。验证 **7,205,528 个已调度 op 的集合相同**，**9,047,711 条计算 operand 边的完整多重集相同**。其中 1 条边的源未归入已调度组，明确排除，未算作消除；见日志 `_op_15262706 -> _op_15262708`。

原冻结 after C++ 的 **2,486,315 个 op 注释**又逐项核对了静态重放的 group 归属，全部一致。两次独立 shared 静态重放的连通统计也一致。因 emitter 会内联操作，这个源码注释数量不是全图 op 数。

分析排除 Constant、RegisterRead、LatchRead 作为计算连通点；外部相同输入、相同状态读和共同 commit 终点不自动把两个计算分量连在一起。计数对象是 operand 边出现次数，不是不同 value 数，也不是活动掩码更新次数。

| 6,542 个共享候选的静态性质 | 数量 |
| --- | ---: |
| 含多个计算连通分量 | **4,647（71.03%）** |
| 只有多个独立操作、计算间无内部边 | 1,532 |
| 没有消除旧组之间的计算边界 | **3,090（47.23%）** |
| 上一行中又新切出计算边界的候选 | **2,087** |

全图计算 operand 边中，收缩消除 216,941 条旧跨组边，同时切出 118,877 条新跨组边，净减少 98,064 条。这说明“边界总数下降”掩盖了内部不同方向的变化。3,090 个零消除候选涉及 17,872 条新切出的出边和 15,146 条新切出的入边；这两数不能直接相加当作不同边数，因为同一边可能被两端计入。

FTQ group93956 是明确例子：64 个旧组，64 个互不连接的 concat，4,096 个不同源状态；没有消除计算间旧边界，反而新切出 64 条出边。旧组中贴着消费者的构造被抽离到共同活动位下。对应 [TNO0039](./TNO0039_shared_region_layout_activity_and_lifetimes_20261116.md) 的活动范围扩大证据仍成立。

ROB group94733 则不同：45 个非读/常量计算 op 是一个连通分量，内部有 65 条 operand 边，确实消除了 16 条旧跨组计算边界。因此不能根据 FTQ 的坏例子推导“共享都应该关闭”。

**上述零消除不是最终拒绝条件。** 状态读合并、相同激活前沿、缓存与视图组合仍可能有价值，尚未被这一边计数涵盖。它指出当前候选选择遗漏了什么，不能替换成另一个只数边的硬阈值。

代码来源很直接：`buildSharedEventRegions` 用终点集合做 `regions` 的 key，把同集合节点全部放进一个候选；原路径又对未移动余部按 `terminals[node]` 全面细分。只加候选过滤而保留全量余部细分，仍可能留下大量新入口。上次局部 SCC 只改变无环维护，保留全部原候选，所以无法解决候选本身的独立计算池化。

[全图候选与收益清单](../../build/xs/cv32-lineage-audit-v1/shared-class-benefits.json)、[精确边界迁移](../../build/xs/cv32-lineage-audit-v1/schedule-lineage.json)、[原始日志](../../build/xs/cv32-lineage-audit-v1/schedule-lineage.log)。

## 4. 简化器与 packed-array 表示没有组合

单独用两个版本的库重放同一 simplify，输入清单逐字节相同。simplify 后总 op 数 5,921,874→5,919,677，只变化 Concat −107、SliceStatic −2,090。3,955 个带 packed 元数据的 concat 名称集合不变，其中 39 个的操作数形态被改变。

39 个中，7 个宽度超过 64 bit，原本是等宽 lane，合并后出现混合宽度；比如 PTW bitmapcache 的 32×4-bit concat 变成 16 个 4-bit 操作数加 1 个 64-bit 操作数，元数据仍描述 32×4。emitter 检查 operand 数/位宽与元数据一致是正确的保护，因此回退到普通 packed-bit words。7 个案例合计 26 个 SliceArray 用户，与完整模型专用 view 从 814→807、select 从 2,624→2,598 的差额一致。

源码根因在 `redundant_elim`：只改 concat 操作数列表，没有保留 lane 结构的独立语义；emitter 的 `buildPackedArrayLaneViewFromConcat` 依赖这个列表仍逐 lane 排列。不能通过删掉 emitter 校验来“修复”，也不能宣称所有合并都变慢。

PTW bitmapcache 的同一个结果 `_val_11840339`（SliceArray `_op_12496825`）提供了 C++/ELF 对应：

```text
before：32 个 byte 槽中的一个 → mask 4 bit → 结果
after ：2 个 uint64 word 的通用 bit slice → mask 4 bit → 结果
```

before 的结果读取核心只有 5 条机器指令：准备 bit-extract 常数、`bextr`、索引字节加载、mask、结果存储。after 对应核心跨两个代码块有 17 条静态指令，包含 2 个条件跳转、word 选择，以及可能加载下一 word 后的 `shrd`。17 条包含不同分支，不能当作每次动态执行 17 条。

这里 index∈[0,31]，start=index×4，结果宽度为 4。`(start % 64)+4≤64` 对全部合法 index 成立，读取**不可能跨 word**；通用 `grhsim_slice_words` 却只检查 shift 非零就准备下一 word，再在最后截断，Clang 未在这个 ELF 中消除该工作。

这给出两个静态修复方向：让简化保留/重建 lane 语义；或让 `SliceArray` 降低直接使用已知元素宽度/对齐证明，避免通用跨 word 路径。需要同时检查构造端：紧凑 words 比 byte-lane 表占更小空间，且可能减少构造计算，不能只比较读取端便决定整体赢家。

[七个形态变化](../../build/xs/cv32-lineage-audit-v1/changed-packed-shapes.json)、[旧读取 ELF](../../build/xs/cv32-lineage-audit-v1/bitmapcache-before-window.s)、[新读取入口](../../build/xs/cv32-lineage-audit-v1/bitmapcache-after-entry-window.s)、[新读取尾部](../../build/xs/cv32-lineage-audit-v1/bitmapcache-after-tail-window.s)、[编译期偏移](../../build/xs/cv32-lineage-audit-v1/bitmapcache-evidence.json)。

## 5. 新默认 indexed-concat：按 word 计算之前仍准备全部捕获

after 有 15 个 indexed-concat 点，ELF 中有 15 个独立 word-reader lambda；before 没有这一批函数。代表点在 after batch20/group95771：ROB 的 256-bit valid 向量，最后只读取 1 bit。规则先保留 256 个局部 bool 快照，再生成四个 64-bit case 的引用捕获 lambda。

ELF 在调用前向 RSP+0x6e0..0xed8 写入 **256 个指针，构造 2,048 B 捕获对象**。源码中被捕获的命名局部快照也正好是 256 个。callee 另有 280 B 栈减法和 737 条静态指令，按 word 选择后仍拼出 64 bit，再由调用者截取 1 bit。

并不是 737 条都会执行，调用前窗口也混有其他工作；本报告只把可对应的 256 次指针写明确归给捕获准备，不把整个 1,014 条窗口都称为新开销。

根因是 `collectIndexedConcatSlices` 为了快照安全，把局部输入加入 `preserveLocalSnapshot`；后续 `emitIndexedConcatSliceOperation` 生成 `[&]` 捕获 lambda。快照证明是必要的，但实现把“不延迟可变输入”与“必须先物化全部局部标量并逐个捕获”绑定了。

可研究保留快照语义的直接选中状态读取，或传递紧凑、类型明确的源描述；对 1-bit 结果将需求继续下推到 bit，避免先拼 64 bit。不能直接删除快照检查，也不宜只用 `always_inline` 强制把大 helper 展开回主函数。新数据表、额外间接加载、代码大小和生命周期需要一起评估。此前 TNO0042 的 typed member table 只覆盖 packed `SliceArray`，没有覆盖这条 bit-offset concat 路径。

[调用前捕获窗口](../../build/xs/cv32-lineage-audit-v1/indexed-word-closure-build.s)、[helper ELF](../../build/xs/cv32-lineage-audit-v1/indexed-word-helper20.s)。这仍是静态机会，没有该点运行频率，不将其单独当成 7.17% 的主要来源。

## 6. 如何让下一步区别对待 XiangShan 与 CV32

用同样的非读/常量 def-use 连通定义检查 CV32 的六个共享组：

| 组 | 计算分量 | 内部化的旧跨组计算 operand 边 |
| --- | ---: | ---: |
| 29 | 1 | 17 |
| 30 | 2 | 0 |
| 31 | 1 | **765** |
| 32 | 1 | 12 |
| 33 | 1 | 18 |
| 34 | 1 | 9 |

主组31是一个621-op计算连通分量，与FTQ的64个独立构造有本质结构区别。group30的两个 Eq 虽然不连通，却都直接读取同一寄存器 `core$_12641_`；这是“完整激活支持相同”的潜在合理合并，而非“终点相同就合并”。是否可用还要按实际激活前沿证明，不能把同源符号当作所有情况下都足够的条件。

据此建议下一步先落实一套候选构造规则，而不是继续排列组合开关：

1. 在完整 compute node 约束下，以真实计算依赖形成候选组件；区分候选内部新消除的边界与原组内本来就存在的边。
2. 不连通组件只有在**完整静态激活支持相同**、状态快照一致、无副作用且不会引入额外活动传播时，才研究共同入口。不同支持保留独立活动位，函数分块可共用。
3. 被拒绝的节点保留原分组；仅对实际接受的收缩做必要的局部无环细分。不能继续无条件按全部终点集合切碎余部，也不能把所有余部直接并回去。
4. 对 CV32 保留候选前后实际 state-reader frontier 的核对：此前丢失的77个view全部受到前沿约束。保住765条计算边收缩仍不自动证明视图收益全保留，需验证源码与计数。

另开两个小而明确的表示修复：packed-array 元数据与 simplify 的组合、已知对齐 SliceArray 的单 word 读取；indexed-concat 捕获准备作为后续需求下推问题。它们不与主调度改动盲目捆绑，也不先根据现有计时挑模块或阈值。

下一轮若实施，应固定规则和双模型对照，沿用 node030 CPU96 串行计时；同时检查实际活动计数或预先声明的只读诊断来解释成本，但这些观测只用于验证/评价，不进入生成决策。本轮止于静态证据与设计，不新增性能实验。

## 归档与可复现检查

[完整报告](../../build/xs/cv32-lineage-audit-v1/report.json)、[静态重放工具](../../scripts/xiangshan_cv32_simplify_audit.cpp)、[精确边界对齐工具](../../scripts/xiangshan_schedule_lineage.cpp)、[汇总脚本](../../scripts/xiangshan_cv32_lineage_report.py)、[CV32 连通性](../../build/xs/cv32-lineage-audit-v1/cv32-components.json)。工具保留了库、头文件所在冻结目录、编译命令、辅助 ELF 和源代码身份；早期仅simplify版本及第一版schedule探针源文件逐字节归档，避免后续增加分析输出造成身份混淆。

静态工具校验覆盖精确 op/edge 集合、冻结 C++ op 所属组、候选 op 总和、七个表示差额、256 个捕获指针写、位对齐证明及输入身份。边界对齐工具的小型独立 oracle 检查“一条消除、一条新增”的分类，并验证错误边集合、错误源码归属会被拒绝。[验证记录](../../build/xs/cv32-lineage-audit-v1/lineage-tool-validation.json)

最终核对汇总脚本与报告的源码身份、上述 oracle 工具身份、生产源码与 TNO0042 冻结快照一致性、文档链接及两仓 diff 格式；见 [归档检查](../../build/xs/cv32-lineage-audit-v1/validation.json)。

首次远程静态重放缺少 `PYTHONPATH`，在导入 driver 时退出；补齐路径后执行，未启动任何模拟器，失败日志保留在 `replay.log`。首次 offsetof 探针试图对 `std::array::operator[]` 使用 `__builtin_offsetof`，编译器正确拒绝；改为取得成员数组基址，再按标准数组元素大小计算槽位偏移。以上均为分析工具准备问题，不计作生产或功能错误。
