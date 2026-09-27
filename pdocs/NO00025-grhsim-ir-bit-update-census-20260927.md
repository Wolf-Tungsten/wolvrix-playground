# NO00025：逐位寄存器更新的计算量与合并约束

| 字段 | 值 |
|---|---|
| 父节点 | NO00024（当前最佳） |
| 角色 | 诊断 |
| 状态 | ACCEPTED |
| 锚定指标 | M-bit：一位寄存器更新局部逻辑的去重动态执行量；M-exclusive：其中无外部消费者的执行量；M-controls：事件兼容组与使能分裂；M-proof：旧状态的布尔依赖 |
| 指标阈值 | 交付四项定量基线、前三个高执行量组的两侧 IR 解释，G1–G5 全过 |
| 回退预算 | 生产语义与生成源码零改动；同窗口重建 Host 均值回退 ≤2%，不据重建扰动更新最佳指针 |
| RUN_ID | no00025_bit_update_census_20260927，各实验追加唯一后缀 |
| 工作区 | ptmp/no00025_bit_update_census_20260927/ |

## 基础选定（BASELINE）

启动时根仓库 `286f8a4`、wolvrix `c80ae7e`，工作区干净，全部既有节点已终态。选择 NO00024，无迂回。本节点不修改生产算法、冻结 GRH 或设计源码。

配置不变，复用父节点 Host **48.719667 s**（样本 SD 0.064 s）、M-net **3,657,941.361 instr/guest-cycle**，gsim+PGO **27.376 s**。CoreMark 两次迭代，100,000 cycle 上限、1 core、1 thread、CPU 2，waveform/commit/RAM trace 关闭。机器 32 核、187 GiB 内存，编译 -j32、clang 22.1.2 三阶段 PGO、PGO_BOLT=0，训练启用 difftest。

完整 SV→C++ 生成和 PGO 编译各从 Make 启动计时，1800 s 截止并杀进程组；生产仿真截止 **73.0795005 s = 48.719667×1.5**。动态计数及 PGO 插桩训练单独限时 300 s，不混入生产时间。运行前 posix_fadvise 驱逐二进制页缓存；日志和临时产物均在 ptmp。

## 假设提出（HYPOTHESIS）

[NO00023](NO00023-grhsim-ir-residual-write-cones-20260927.md) 的 BusyTable 数据更新局部逻辑为 **1,495.283 execs/cycle**，但未计入写使能，也未检查这些 op 是否还有外部消费者。[NO00024](NO00024-grhsim-ir-or-write-recovery-20260927.md) 已消除另一类 OR 写网络，必须在新结构上重新计数。启动检查发现当前未分图 IR 尚有 **8,718** 个一位 regWrite，数据根以 bitSelect 6,027、or 1,196、and 1,134 为主。BusyTable 各位使能不同，现有 pack-bit-registers 按相同使能与掩码分组，无法仅靠扩大打包位数恢复字级更新。

本节点假设是：可以在未分图 IR 上，按类型、写目标和逻辑依赖建立一位更新的精确局部边界，再把实际动态计数连接到这些边界，分清可替换计算与共享上游逻辑，给后续分图前 IR 替换提供可复核的候选。分析覆盖全部符合类型的一位写，不以模块名选择候选；名称只用于报告及 gsim 寄存器配对。

**与总目标的定量关系**：NO00024 的分图前 IR 替换使 M-net 降 1.237%、Host 降 1.349%；NO00022 则为 6.095%/4.739%。因此本节点测实际执行量和外部消费者，定位下一次能减少 host 工作量的候选；不把 op 数、布尔决策节点数或静态压缩率换算为固定 instr/op，也不承诺诊断量等于性能收益。

定义：M-bit 从写 enable、data、mask 三个根向后遍历 compute op，遇到具名中间值、读取或常量即停止；根本身即使具名仍展开，相同 op 跨行/跨组只计一次。M-exclusive 进一步从消费者关系剔除被边界外使用的 op，并向其上游传播保留需求；状态读取与常量不算可删除计算，同一 writer 的事件输入也保留。M-controls 按事件值、边沿、私有历史初值、目标初值分类，再统计不同 enable/mask 组合，并单列已有 quiescence projection 的分裂情况。M-proof 用有界布尔决策图检查有效更新 `F = (enable && mask) ? data : old` 的旧状态依赖，只有支持的一位布尔运算参与化简，其他输出当作独立叶并检查隐藏反馈。可证明保持/置清形式或旧状态无关；反相反馈的抽象反例可能受真实输入相关性约束，不能直接声称可达。以上均非生产 IR 改写。

预注册检查：

- **G1**：生产重建的语义数组、映射与父模型一致，生成 C++/头文件/Makefile 逐字节一致；pre-partition 的语义数组与最终模型一致。动态构建只改变诊断计数发射，不重跑变换或分图，checkpoint 与生产一致。
- **G2**：动态运行端点正确，全部 compute unit 与计数键一一对应，按 op 所属 unit 展开的总执行次数与独立按分区树统计的 runtime 汇总精确闭合；grp_pub/grp_fire 还须与运行时总计相等；两次独立 100k 动态运行计数逐键相同。这里明确区分 body×静态 op 数与真实独立硬件指令计数，运行时没有逐 op 总执行计数器。
- **G3**：同一输入分析两次，正式 JSON/Markdown 结果逐字节一致；所有一位 writer 要么计入，要么有明确拒绝原因；M-exclusive≤M-bit 且去重总量≤逐组相加。
- **G4**：小图单测覆盖消费者外溢、共享子图、非单 writer、历史共享/初值/事件差异；布尔结果以独立真值枚举校验，包含禁写保持、mask=0、同拍 clear/set 冲突及反相反馈。
- **G5**：按 M-bit 排名前三个事件兼容组，交付完整 enable/data/mask 边界、动态份额、相同使能分组限制和至少一个精确同名同宽 gsim 更新树的具名展开；无法配对须列明原因，不把名称配对视为全设计等价证明。

生产性能按 **old1,new1,old2,new2,old3,new3** 六次无插桩交替；old 为 NO00024 归档，new 为相同生产代码重建。记录 Host/emu 墙钟、退出、端点、均值、SD、效应量和秩次；全部端点须为 `240349/99996/100001/0x80000c0c`，无 difftest mismatch。任何结构/计数门失败先按实现瑕疵修正；如无法建立准确边界或归因则定量复盘，REJECTED，不提前提交。

## 代码实施（IMPLEMENTED）

新增 `scripts/grhsim_bit_update_census.py`、对应测试及 `analyze_grhsim_bit_updates` / `test_grhsim_bit_updates` Make 入口。分析从 enable/data/mask 根建立局部 DAG，对外部消费者反向传播保留需求；按事件和初值分组，不按模块名分组。布尔证明仅接受二态一位运算，最多 24 个独立叶、10,000 个 BDD 节点，遇隐藏旧状态反馈或追踪超过 4,096 个值明确返回未知，不能据此声称可优化。输出包括未分图逻辑边界、动态份额、使能分组、布尔分类及 gsim 具名表达式展开。

`make test_grhsim_bit_updates` 首轮 **20/20** 通过，包括 100 个随机布尔电路各 32 项独立真值对照、反馈反例、外部消费者和共享锥、使能/事件/初值限制以及分析不修改输入。实施阶段修正启动计数手工加和：一位 writer 为 8,718，并非草稿中的 8,818；各 kind 原始计数未变。

静态预检发现并修正两项实现瑕疵：lower 的私有事件历史使用裸字符串 `0`，初版只识别带位宽字面量而误拒绝；运行时 `sn.grp` 是 group 调用数、`grp_pub` 是有发布输出的 group 调用数，两者不能直接相等。现按诊断生成源码逐 unit 计数两类增量点，分别与 body 次数和 runtime 总计闭合；`Σsn.chg=grp_fire` 仍直接核对。另加事件输入消费者反例，防止把仍用于边沿检测的计算列入可替换独占集合。这些修改只影响诊断解析和计量。

## 结果测试（TESTED）

**门槛与等价**：完整 SV→C++ 生成 **852.48 s**（<1800 ✓）、clang 三阶段 PGO 编译 **626.57 s**（<1800 ✓），编译 -j32；诊断动态 reemit 47.71 s、动态构建 226.99 s（不混入生产时间）。2 次动态 100k 与 6 次生产性能运行端点全部为 `instrCnt=240349 / cycleCnt=99996 / guest cycles=100001 / PC=0x80000c0c`，无 difftest mismatch，全部 exit 0。

**实现瑕疵（TESTED 首轮发现并同节点修正）**：首轮正式分析在 G2 前失败——`counter_sites` 正则要求 `cpu_dyn_sn_chg[N]+=cpu_dyn_any;++cpu_dyn_grp_pub` 同行相邻，而实际发射器输出为换行分隔（27,955 个站点逐一核实全部紧邻，仅间隔空白）。按实现瑕疵处理：正则放宽为允许空白分隔、两处测试夹具改为真实多行形态，单测 27/27 通过后两轮分析完整重跑。该瑕疵只影响诊断解析；生产代码与 checkpoint 在修复前后均通过 G1，计数闭式在修复后全部精确成立。

**G1 PASS**：parent/dynamic checkpoint 与 final 逐字节一致；pre-partition 九个语义数组（functions/init/inputs/interface/operations/outputs/states/types/values）与 final 一致、backend 追加字符串 0；生产生成源（.cpp/.hpp/Makefile）与父节点 NO00024 逐字节一致。

**G2 PASS**：两次独立动态 100k 运行计数逐键相同；运行时闭式全部精确——group 调用 836,431,500 = Σ(body×站点数)、grp_pub 772,617,598、grp_fire 245,705,479 与运行时总计相等；compute 执行 91,061,544,463 与按分区子树独立统计相等；无发布输出的 group 1,531 个。

**G3 PASS**：两轮完整分析 summary.json/summary.md 逐字节一致；覆盖闭式 8,718 = 8,689 eligible + 29 target_initial_unknown（无遗漏无重计）；exclusive ≤ local ≤ 逐组相加（18,801.780 ≤ 23,950.481 ≤ 23,962.145）成立。

**G4 PASS**：27/27 单测（含 100 个随机布尔电路 × 32 项独立真值对照、反馈反例、外部消费者/共享锥、事件/初值限制、计数解析、双轮闭式）。

**G5 PASS**：按 M-bit 前三事件兼容组交付完整边界、动态份额与使能分裂；gsim 具名展开 2 组 matched（组 1 样本 `itlbRepeater1$tlb_req_0_bits_r_getGpa`、组 3 样本 `RasStack$tosr_flag`，均精确同名同宽单候选，展开至 4 层具名引用），组 2 样本 `entryWriteBuffer$entries_1_3_entry_valid` 报 ambiguous_or_missing_name_width（规范化名称在 gsim 侧无唯一 1 位 NODE_REG_SRC 候选，原因列明，不视为配对）。

**微观指标基线**（compute_execs = 910,606.339/cycle）：

- **M-bit = 23,950.481 execs/cycle（2.630%）**；**M-exclusive = 18,801.780 execs/cycle（2.065%）**。跨组共享仅 0.049%（逐组相加 23,962.145），各组逻辑基本互不共享。
- **M-controls**：38 个事件兼容组。组 1（3,679 行，单 posedge、target_init=0，主体为 ssit valid_array 各 dataBank 64 行族）**3,679 个控制组、零共享**——每行 enable/mask 组合皆不同，quiescence projection 已覆盖 3,337 行；组 2（3,519 行，双 posedge、target_init=0，intBusyTable 223 / vecBusyTable 128 / isVec 族）3,518 控制组、仅 2 行共享；组 3（222 行，target_init=1）158 控制组、128 行成对共享 enable/mask。
- **M-proof**（8,689 eligible）：set_clear_hold **6,219（71.6%）**、hidden_feedback 1,876、atom_budget 403、old_independent 87、bdd_budget 56、may_toggle 30、feedback_check_budget 18。即七分之一位更新的有效写入可证明为保持/置清形式（旧值仅以单态方式参与），但隐藏反馈与原子数上限覆盖了大部分剩余行，保守口径下不能声称其可优化。
- 组 1 动态构成：and 6,548.4 / or 5,788.3 / bitSelect 1,274.4 / logicNot 861.1 execs/cycle，与 NO00023 的 BusyTable 局部（1,495.3 execs/cycle，未含 enable）互补——本节点首次把 enable/data/mask 三根的完整局部计入。

**生产性能**（预登记顺序 old1,new1,old2,new2,old3,new3；old=NO00024 归档，new=同源码重建；驱逐页缓存、CPU 2、无插桩）：

| 运行 | Host s | 端点 | 退出 |
|---|---|---|---|
| old1 | 48.889 | 240349/99996/100001/0x80000c0c | 0 |
| new1 | 48.730 | 同上 | 0 |
| old2 | 49.056 | 同上 | 0 |
| new2 | 48.704 | 同上 | 0 |
| old3 | 49.178 | 同上 | 0 |
| new3 | 48.926 | 同上 | 0 |

old 均值 49.041（SD 0.145），new 均值 48.787（SD 0.121），差 −0.254 s（−0.519%）；U=8/9，单侧精确 p=0.15 不显著，属重建/布局噪声。回退预算 +2% 满足；按预登记不据重建扰动更新最佳指针，当前最佳仍为 NO00024（48.720 s）。

**判定：ACCEPTED**。诊断节点交付 M-bit / M-exclusive / M-controls / M-proof 四项定量基线与前三组两侧 IR 解释，G1–G5 全过，门槛与等价全过，回退预算内。后续候选按实测排序：① 组 1 的 3,679 个互不相同 enable 的一位写（15,242.9 execs/cycle 局部、11,369.2 独占）是最大可定位目标，set_clear_hold 占 84%（3,095/3,679）支持按"条件置清"语义做分图前 IR 替换，但每行独立 enable 使 pack-bit-registers 的字级合并不可直接适用；② 组 2 busy table 族（6,393.8 execs/cycle）双事件结构须先处理 NO00022/24 已回收写网络之外的双时钟沿使能；③ 组 3 共享 enable 的 128 行（1,337.2 execs/cycle）最接近现有打包语义但体量最小。三者合计 23.0 K execs/cycle ≈ compute 2.5%，与 NO00021 因果臂结论一致——任何替换须保持 reg-to-mem/pack 的既有净收益。
