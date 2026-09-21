# NO00051 grhsim IR：层次化 mux→层叠 if-else（gsim 形态对齐）——失败节点（用户人工判定）

- 节点 ID：NO00051
- 日期：2026-09-21 启动
- 前置节点：NO00049（used-bits，锚点 **70.419333 s**，距 gsim 1.499839×）；NO00050 失败回退后工作区基线 wolvrix `7fd134e`（与 `54d6e74` 零差异）、根仓库 `4b2eaef`
- 状态：IDEA/BASELINE（普查迭代中）

## 1. 假设与机制（IDEA）

**动机（用户方向 + 前序证据）**：emit 与调度框架已到噪声底（NO00046/47/50 三连失败），剩余差距是表达形态：每 eval 指令 2.57M vs gsim 0.925M（2.78×）。对照 gsim 源码普查其高效形态清单后，选定 IR 层方向：**SV 优先级降级（case / if-else 路径守卫）在 grhsim IR 中物化为巨量布尔 and/or/not 网络，而 gsim/FIRRTL 侧用 when/else-when 控制流承接、优先级零布尔代价**。NO00038 已定量：not 膨胀 13.2×（127,036 + logicNot 95,943 vs FIRRTL 16,903），and+or+not/logicNot ≈ 动态 compute op 的 46%。

**机制（本节点立项形态）**：对 1-bit two-state 布尔 op 树做**蕴含吸收（implication absorption）**——纯局部布尔恒等式，与优先级语义无关、对任何消费者上下文保真：

1. and 树中，否定叶 `not(A)` 被正叶 `B` 吸收（`B ⟹ ¬A` 时删除该叶；典型：B=eq(x,C1)、A=eq(x,C2)、C1≠C2 同控制量不同常量——译码器形态）；
2. and/or 树中，正叶 `L` 被另一正叶 `B` 吸收（`B ⟹ L`，如 L 是含 B 的 or 树 / ne(x,C2) 与 B=eq(x,C1) 常量冲突 / L 的 and 树含 B）；
3. or 树中 `or(B, ¬A)` 且 `A ⟹ B` → 整树恒真（tautology）；
4. 重复叶去重（and(a,a)=a / or(a,a)=a，普查实测 57,052 处）。

蕴含引擎为结构式：同控制量不同常量 eq 模式（复用 NO00038 match_pattern 思路，常量已适配本模型的 SV 字面量字符串参数形态 `3'b0` 等）+ and/or 树包含关系。

**为什么这条路没有被前序证伪封死**：

- NO00038 候选 B 证伪的是"互斥消解"（在任意上下文把 `match_i & !prior_i ≡ match_i`，需证明臂互斥，67,036/67,036 arm_prefix_unprovable）。本方向不依赖全局互斥证明，而是**树内叶对局部蕴含**——形态与证明义务均不同。
- NO00047 物化门证伪的是"运行时跳过"，本方向是"源头免除"（其唯一认可的路线）。
- 不是发射层变换，不产生新控制流，无 clang 控制流惩罚风险。

**收益转化路径**：删除叶 → and/or/not op 死锥（交 used-bits 既有死锥消除回收）→ compute 体 op 数与 boundary 值下降 → 指令数/icache 压力下降（前端受限机器上指令减≈时间减，NO00049 转化比约 1:1）。

**可证伪标准**：普查（NO00049 最终模型，3,590,106 ops）若可消除叶对应净 op 池 <10 万（约全模型 2.8%）或动态份额 <2%，则放弃本机制转向。

## 2. 普查迭代记录（IDEA 内证伪过程，如实保留）

模型：`ptmp/no00049_used_bits_20260920/flow-final/xiangshan_grhsim_ir.json`（NO00049 正式 checkpoint，3,590,106 ops / 3,437,774 values / 292,678 states）。

**v1 干净 case 前缀形态（`and(m_i, not(or(matches)))` 精确增量链）**：psel 命中 20 cond / bsel 命中 86 cond——几乎不存在。原因：ingest 实际形态为 `and(and(baseGuard, match_i), not(prefix_i))`（`ingest.cpp:2148-2153` combineGuard 嵌套），且 CSE 重构后前缀关系进一步变形。日志 `census2.log`。

**v2 优先级链条件规则（not 叶 payload 的 and 树包含同链早前 cond 值）**：全模型仅 **64** 个 cond 命中。取样（`chain_sample_probe.py`）发现真实形态：巨型合取守卫树（≥6 叶占 133,731/211,633），not 叶 payload 多为 and/or 复合结构（not(and) 648,912、not(or) 88,164），且大量否定指向**低优先级**臂的匹配（对链结果承重，不可消除）。日志 `census3.log`。

**关键样本证据（psel#24369，N=5）**：cond 叶集合呈"否定所有其他臂匹配 + 本臂正匹配"结构，匹配为同控制量 eq(st.read, C) 不同常量（3'b0/3'b1/3'b10，used-bits 已收窄到 3 bit）——**否定叶与正叶在同树内构成叶对互斥**，这给出与优先级语义无关的局部吸收规则（即本节点立项形态）。

**v3 蕴含吸收初测**：removable_not_leaves=0——常量参数形态失配（本模型常量参数为 `'string', "3'b0"` SV 字面量，非 `'int'`）；修复 parse_sv_literal 后 v4：removable_not_leaves=1,160、removable_pos_leaves=37,946、or_tautology_roots=1,050、dup_leaves=57,052、affected_trees=26,138。否定吸收偏低疑似两个统计口径问题：巨型树触及 128 叶展平上限（tree_too_deep=25,257，最大的守卫树被整体跳过）+ 内部节点跳过（共享守卫子树被更大树吸收为内部节点）。日志 `census4.log`/`census5.log`。

**v5/v6 蕴含吸收定型（REJECTED 作为节点机制）**：修复常量解析（SV 字面量字符串）+ 虚拟叶/独占叶双层计数后（`scripts/grhsim_guard_absorb_stats.py`，日志 census6.log）：否定吸收 virtual 1,160 / 独占 230；正吸收 virtual 37,945 / 独占 2,151；重复叶 virtual 155,052 / **独占 67**；or 恒真 1,050。**结论：虚拟池几乎全部位于 CSE 共享子树内（共享子树每次激活只求值一次，虚拟重复无动态成本），可原位消除的独占池合计 ~3.5k op，低于噪声底，不能驱动节点。** 检查 psel#24369 cond 树验证了逻辑本身有效（同控制量 eq 叶对互斥命中），但全局配置稀有。守卫布尔网络在 dataflow+CSE 语义下已接近局部最优——13.2× 的 not 膨胀主要是承重的优先级语义，不是可消除冗余。

**杂项形态普查（REJECTED 作为节点机制）**：`scripts/grhsim_misc_form_stats.py`（misc_census.log）：寄存器常量 171（其中 updateCond 恒假 17、写口同常量 154）、常量 memory 3、one-hot dshl 切片 3,151、concat==const 17,363（改写为逐位 eq 不省 op）、深度 1 数组 0。全部 <0.5% 池。

**小锥复制普查（gsim replicationOpt 形态，REJECTED 作为主机制）**：`scripts/grhsim_cone_replicate_stats.py`（cone_census3.log）：boundary 值 804,421；可克隆形态（单用纯计算小锥、叶为 state.read/input/常量）92,530；消费者 2–8 且全 compute 相 78,028。**关键设计约束：克隆把消费者激活源从锥根换成锥叶，叶变化频率高于根（惰性激活放大器，NO00036 细粒度 −30.69% 同族风险）**；激活中性门（每个锥叶的直接/调度扇出覆盖全部消费者超节点，可证零新增激活边）后 prime 池仅 **8,509 值 / 9,718 锥 op**（其中 1-op 锥 7,993）。收益估算：每值每轮写回评估 ~0.133 次（107k 写回/eval ÷ 804k 值）× ~4 指令 ≈ 全程序 ~0.2%，低于噪声底。非门控池（69,519 值）需逐值/逐叶变化事件才能定量，现有插桩计数器（按超节点/按 op 类别）不覆盖，且该风险族已有强负面先验。**机制家族判定：IR 层局部化简/复制空间已被 canonicalize+CSE+used-bits 压尽，剩余"冗余"或为 CSE 共享（无动态成本）或为承重优先级语义。**

**根因沉淀**：2.78× 指令差距不在可消除局部形态，而在 (a) 物化协议层（gsim 无）与 (b) 惰性激活重算（71%）——两者均为框架级，且分别被 clang 控制流惩罚与粒度旋钮双向关闭封锁。**本节点机制随之转向：布尔核提取（同一超节点内 and/or 树的公共核对偶共现，modulo 结合序——CSE 只消 identical op，核提取消 association-variant 公共子锥）**，普查 2-叶核同超节点共现率中。

## 2.5 机制转向（2026-09-21 用户裁定）：层次化 mux op + 层叠 if-else 发射

用户裁定本节为节点正式方向：新增一类 grhsim IR op 表达层次化 mux，发射层叠 if-else C++ 结构（gsim OP_WHEN/StmtTree 形态对齐）。前序局部化简家族（§2 全部）作为证伪过程保留。

**方向修正的关键证据链**：
1. 数据流形态下优先级布尔网络不可消除（§2：承重/共享/独占池 ~3.5k）——它需要的是控制流形态。
2. NO00047 控制流惩罚只适用于巨型函数内的细粒度值门；NO00041（+10.85%，最大单节点收益）证明块级控制流重构是收益族。
3. gsim 绝对误预测 4.72G 高于我方 3.95G，但指令数 1/2.77——"多误预测换少指令"在该形态下成立，误预测预算有余量。

**普查定量（NO00049 最终模型）**：
- case 守卫分解（`grhsim_mux_region_stats.py`，decomp_census.log）：12,020/12,467 条件向量无唯一可识别 match——**干净 ingest case 结构在最终模型中不存在**（firtool SV 自带显式否定 + 反向优先级引用 + 复合叶），条件剥离池 ≈ 0。条件锥可沉率 4.7%（5,483 vs 111,443，前缀链/CSE 共享须提升）。
- **分支分解**（`grhsim_branch_decomp_stats.py`，branch_decomp3.log）：后向标签分析（值到超节点出口的全部路径仅经某 mux/psel/bitSelect 一个臂位 → 该臂分支锥）——**可沉 op 772,290（22.46%）**、多标签 216,846（6.31%）。池集中于顶层 enable mux 后的大锥（`out = en ? 0 : 大计算`，如 task_3576 每块 ~130 行 onehot 守卫+拼接+移位锥挂在 1 个 mux 臂上）。热任务排名：task_3576/3577（各 ~1008 可沉 op）、task_2763-2765（各 ~950）。
- 这是迄今探明的最大单一池：链激活只走 1/N 臂，均匀假设下可跳过大部；即使考虑命中率偏斜，动态上界 ~10%+ 计算 op。

**机制设计（v1）**：语义层不变（mux/psel/bitSelect 保持数据流语义与调度/fanout 不变），**发射层把"单标签臂锥"沉入层叠 if-else 分支**：
- 每个 mux/psel 链组：共享/提升锥照常发射于梯前；单标签臂锥发射在对应分支体内；结果在分支内赋值，写回/fanout 在梯外照常（语义逐值相同）。
- 条件不做剥离（普查池 ≈0），v1 收益 = 臂锥动态跳过 + 结构/icache（多输出组 1,347 个共享梯结构）。
- 正确性：臂锥纯计算无副作用、局部量每激活重写、激活集不变；写回变化检测以选中值为准，两形态逐值一致。

**clang 微实验（NO00047 方法学纪律，先于实现）**：`ptmp/no00051_priority_cond_20260921/micro_transform.py` 机械改写 flow-final 模型 task_3576/3577 共 16 个 `res = mux(en,0,cone)` 块为 if-else（锥体沉分支），构建筛选对比 NO00049 控制 emu（2×100k 交替、posix_fadvise 驱逐页缓存）。通过静态指令与筛选信号后才进 C++ emitter 实现。

**clang 微实验结果（task_3576/3577 共 16 块 if-else 改写，3 对交替）**：old 均值 69.999 / new 70.033（**−0.049%，秩次门不过，零效应**）。关键解读：(a) 改写安全——未出现 NO00047 式分支爆炸回归，clang 对该形态无惩罚；(b) 局部实验无可测信号——compute 任务剖面平坦（top 任务仅占 cycles 0.30%，NO00044），2 个任务内的跳过不足以越过噪声；(c) enable 极性未知——`en ? 0 : cone` 的 en 在 CoreMark 满负荷下大概率为假（锥体常需），局部跳过率本来就低。**结论：微实验排除了 clang 风险，但证明该机制必须全模型实施（22.46% 池分布在 3,049 个任务中）才有可测效应——直接进入 emitter 实现。**

**IMPLEMENTED（v1，发射层分支下沉，不改 IR 语义）**：`cpu.st.emit-cpp` 新增 `--branch-sink`：`computeGroup` 内做后向分支分解（值到组内出口的全部路径仅经某 mux/psel/bitSelect 一个臂位 → 该臂单标签锥），主循环跳过单标签锥，链点发射层叠 if-else（臂锥在分支体内、结果在分支内赋值、写回/fanout 在梯外与原路径逐值一致）；提升规则含 boundary 存储/fanout/组外消费者/副作用 op（system/DPI/output.write/memRead）一律提升；嵌套链递归成梯；梯启用阈值 ≥2 个实发射锥 op。挂接：Emitter/EmitCppPass/注册参数/pybind 自动透传（`branch_sink=True`）、reemit `--branch-sink`、Make `GRHSIM_REEMIT_BRANCH_SINK`。实现文件 `wolvrix/lib/grhsim/backend/cpu_emit.cpp`（computeGroup 约 +230 行）、`wolvrix/include/grhsim/backend/cpu_emit.hpp`、`scripts/reemit_grhsim_ir.py`、`Makefile`。

**调试记录（IMPLEMENTED 内）**：(1) flow-sink 编译失败 `expected expression`——梯形分支体闭括号缺失（`else if` 前未闭合上一分支），修复为 `}else if(`/`}else{` 前缀形式。(2) flow-sink2/3 编译通过但仿真 cycle 513 RTL assertion（MainBtbAlignBank alignIdx mismatch）——先修两处静态缺口（多结果 op 按副作用处理、未定标签→提升二次传播）未愈；逐步缩小 diff 审查后定位真因：**臂种子覆盖**——同一值作为多个臂操作数（同一链或不同链）时后一臂标签覆盖前一臂标签，其锥体只在后一臂分支发射，前一臂分支读取从未计算的槽（stale read）。修复：臂操作数已有标签时改标 multi（留主序列），不再分配新臂码。

## 3. 基线与资源（BASELINE，预注册）

- old 对照：`ptmp/no00049_used_bits_20260920/flow-final`（预注册比较值 **70.419333 s**，NO00049 六次正式均值）。
- gsim 归档：46.965 s（不参与节点交替窗口）。
- 构建/运行目标：`xs_wolf_grhsim_ir`、`xs_wolf_grhsim_ir_build_emu`、`run_xs_wolf_grhsim_ir_emu`；仿真 `XS_SIM_MAX_CYCLE=100000`、`XS_NUM_CORES=1`、`XS_EMU_THREADS=1`、`XS_EMU_CPU=2`、waveform/commit/RAM trace 关闭。
- 门槛：完整生成 <1800 s、fresh 编译 <1800 s（记录实际 job 数）、100k NEMU 对拍、6 次新旧交替（3 新+3 旧）秩次判据（max(new) < min(old)，U=0，单侧 p=0.05）。
- 止损：仿真达对照 1.5×（105.6 s）立即终止记 REGRESSION_KILLED；生成/编译达 1800 s 记 TIMEOUT_KILLED。
- 运行前 posix_fadvise 驱逐页缓存（NO00040 修正协议）。

**调试记录（IMPLEMENTED 内）**：(1) flow-sink 编译失败 `expected expression`——梯形分支体闭括号缺失，修复为 `}else if(`/`}else{` 前缀形式。(2) flow-sink2/3 编译通过但仿真 cycle 513 RTL assertion——先修两处静态缺口（多结果 op 按副作用处理、未定标签→提升二次传播）未愈；逐步 diff 审查后定位真因：**臂种子覆盖**（同一值作为多个臂操作数时后臂标签覆盖前臂标签，前臂分支读到从未计算的槽）。修复：臂操作数已有标签时改标 multi。(3) flow-sink4 语义全对（6 次运行 endpoint 全等）但 **−5.756% 回归**；静态归因：分支指令 444,234→588,353（**+144,119 / +32.4%**）、静态指令 19,170,011→19,107,347（−0.33%）——每臂一个数据依赖分支的成本远超锥体跳过收益（与 NO00047 物化门同根因）。PMU 在本机被 perf_event_paranoid=4 禁用，归因以静态指令/分支计数完成。(4) flow-sink5 阈值版（仅臂锥 ≥8 op 成梯）：分支 +19,065（+4.3%），筛选 old 70.216 / new 70.494 = **−0.396%**（秩次门不过）——大锥梯仍不盈利：可沉 op 集中在冷超节点，热超节点可沉份额小，跳过节省追平不了分支成本。

## 4. 结果与分析（VALIDATED 前的筛选证据汇总）

- 全量分支下沉（≥2 锥 op 成梯）：**−5.756%**（old 70.203 / new 74.244，U=9 p=1.0，6 次 endpoint 全等，语义正确）。
- 大锥阈值版（臂锥 ≥8 op）：**−0.396%**（old 70.216 / new 70.494，U=9 p=1.0）。
- mux-only 阈值版（仅 2 臂链 + 臂锥 ≥8 op）：见 screen-sink6（进行中）。
- 微实验（task_3576/3577 手工改写 16 块）：−0.049%（零效应，clang 无病理）。
- 静态归因：分支 +32.4%（全量）/ +4.3%（阈值版）vs 静态指令 −0.33%。
- 根因：运行时条件跳过在本代码库不盈利（NO00047 物化门同根因的第三次独立复证）；gsim 的 if-else 优势来自"优先级守卫网络消除带来的指令数下降"，而非跳过本身——而守卫消除所需的 cond 剥离已被本节点普查证明在 SV 派生形态下结构性不成立（干净 case 向量 0/12,020、局部可证剥离 ~1k cond）。

## 4.1 备选机制定量排除（分析性，未进构建）

- **commit 写口门卫无分支化**（gsim `flags |= -(uint8)cond & mask` 形态对齐）：NO00036 动态计数 port_eval 701.47M / port_fire 488.47M——**点火率 69.63%**，门卫分支多数 taken、预测尚可；无分支化对全部评估追加 ~3-5 op，净额 ≈ −0.3~+1%，且 pending 记录格式须改为位图（runtime 重构）。收益上限 ~1%，风险/收益不匹配，排除。
- **boundary 写回位打包**（goal 移交候选）：写侧存储打包省 ~0.2%，变化检测按字合并引入惰性激活放大器风险，排除。
- **寄存器常量/常量 memory/one-hot 模式/concat==const**：普查池 171/3/3.1k/op 中性，全部 <0.5%，排除。

## 4.2 本节点机制空间总图（移交下一节点）

已闭合（定量证伪或测量负收益）：case 前缀消解（NO00038 互斥路线 + 本节点结构路线 0/12,020）、优先级条件剥离（64+300+850）、蕴含吸收（独占 ~3.5k）、树去重（独占 67）、小锥复制 prime 门（~0.2% 动态）、杂项形态（<0.5%）、层次化 mux→层叠 if-else（0%/−5.76%/−0.40% 三变体）、commit 门卫无分支化（~1% 上限分析排除）、boundary 写回打包（~0.2%）。**共识：凡"运行时跳过/条件化"机制在本代码库不盈利（三次独立复证）；凡"IR 局部形态化简"已被 canonicalize+CSE+used-bits 压尽。剩余已证大池唯框架级：两波直线化（用户已关闭）、物化协议源头免除（需框架级激活精度）。**

## 5. 最终判定

**FAILED（用户人工判定，2026-09-21）**。节点方向（用户 2026-09-21 裁定：层次化 mux op + 层叠 if-else 发射）经完整实现与四级测量（微实验 0% / 全量 −5.756% / 大锥阈值 −0.396% / mux-only −0.563%，全部秩次门不过）证伪；备选机制族（commit 门卫无分支化 ~1% 上限、boundary 写回打包 ~0.2%、杂项形态 <0.5%、小锥复制 prime ~0.2%）经定量分析排除。候选代码全部回退（wolvrix 与 `7fd134e` 零差异；`scripts/wolvrix_xs_grhsim_ir.py`、`scripts/reemit_grhsim_ir.py` 与 Makefile 的 branch-sink 挂接同步回退），保留普查工具七件（`scripts/grhsim_guard_absorb_stats.py`、`grhsim_cone_replicate_stats.py`、`grhsim_misc_form_stats.py`、`grhsim_kernel_cooccur_stats.py`、`grhsim_canon_sim_stats.py`、`grhsim_mux_region_stats.py`、`grhsim_branch_decomp_stats.py`）与 Make 目标 `analyze_grhsim_priority_cond`/`analyze_grhsim_cone_replicate`。

**根因沉淀（三条独立复证级别结论）**：
1. 运行时条件跳过在本代码库不盈利（NO00047 物化门 −8~−12%、NO00050 粗粒度 −9.86%、本节点四变体 0%~−5.76%）——数据依赖分支成本始终 ≥ 跳过收益；机制设计应排除"运行时跳过"族。
2. gsim if-else（OP_WHEN/StmtTree）的优势来自优先级守卫网络的结构性消除（指令数 1/2.77），不是跳过本身；SV 派生形态下守卫消除不成立（0/12,020 干净 case 向量、~1k 可证剥离）——firtool SV 的显式否定与反向优先级引用使优先级语义承重。
3. IR 局部形态化简已被 canonicalize+CSE+used-bits 压尽：剩余"冗余"或为 CSE 共享（无动态成本）或为承重语义。

**移交**：当前最佳回退至 NO00049（70.419333 s，1.499839×）；剩余已证大池唯框架级——两波直线化（用户 2026-09-20 关闭，NO00046 普查前提全部成立，量级 10%+）与物化协议源头免除；下一节点 old 对照 `ptmp/no00049_used_bits_20260920/flow-final`（预注册比较值 70.419333 s）。


