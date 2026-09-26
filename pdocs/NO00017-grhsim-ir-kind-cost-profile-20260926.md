# NO00017: 逐 op-kind 动态指令归因——compute 侧编译后边际代价与份额基线（诊断）

| 字段 | 值 |
|---|---|
| 父节点 | NO00015（当前最佳） |
| 角色 | 诊断 |
| 状态 | REJECTED（机制证伪：逐 op 边际成本线性可加性不成立；G1/G2 全过，G3/G4 全粒度 FAIL） |
| 锚定指标 | **M-kinddyn**（逐 op kind 动态 instr/cycle 份额表）；**M-kindcost**（逐 kind 边际静态指令代价表）；辅 M-widthdyn（位宽桶动态份额）、M-bkacct（簿记边际代价校准） |
| 指标阈值 | 诊断节点：数据连接门 G1、确定性门 G2、拟合质量门 G3（加权 R² ≥ 0.90；主力 kind 系数 bootstrap 95% CI 半宽 ≤30%）、闭式闭合门 G4（残差 ≤10%）全过 + 四表交付 |
| 回退预算 | 无性能语义改动；当前最佳指针不动（NO00015，52.672 s）；回退预算 N/A |
| RUN_ID | no00017_kind_cost_20260926 |
| 工作区 | ptmp/no00017_kind_cost_20260926/ |

## 基础选定（BASELINE）

- **父节点**：NO00015（当前最佳指针，GrhSIM-IR PGO 构建 Host 52.672 s，wolvrix `61b092e` + 根仓库 NO00015 提交 `4e4e40f`）。NO00016（REJECTED）未移动指针；本节点为诊断节点，零语义改动，分析对象取 NO00015 归档（生产 checkpoint、PGO 二进制、dyn run1 日志），无迂回。
- **立项动机（为什么是这个诊断）**：NO00008 因子表把 2.0× 指令差距闭式归因于每单位工作指令密度（ir 3.86 instr/dynOp vs gsim 0.452 instr/enode，8.54×；NO00010 后 3.24）。其后三条密度压缩路线被机制证伪：NO00009（值承载 typed-SSA 提升）、NO00011（表达式树融合）、NO00016（恒等/常量 op 整条删除，实测每次执行仅 0.043 instr——"以静态语句数定价动态成本"的成本模型作废）。**剩余密度差距的结构归属（哪类 op、哪个位宽、哪块簿记携带动态指令）在当前分支从未被编译后口径实测过**：NO00010 的活动追踪税（~1.51M/cycle）基于发射形态常数（检测 ~3.5、置位 ~2.5、清零 ~1）；NO00012 M-wide 只覆盖检测侧（宽值 1.06%），compute 侧位宽分布未知。本节点用**编译后（clang -O3 + PGO）反汇编静态指令计数 × 确定性动态 fires 闭式连接**，把 compute 侧 3,173,679.4 instr/cycle 分解到 kind × 位宽 × 簿记维度，为后续优化节点交付可定价目标清单。
- **基线测量（配置未变，复用归档值，不重跑）**：
  - GrhSIM-IR 当前最佳：Host **52.672 s**（NO00015，3 次有效均值，SD 0.015 s）；端点 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`。
  - gsim+PGO 锚点：Host **27.376 s**（SD 0.065 s）；差距 **1.924×（~25.3 s）**。
  - 指令归因（NO00016 基线测量，NO00015 生产构建 perfstat）：总 **3,949,943.3 instr/cycle**；compute 80.35% ⇒ **3,173,679.4 instr/cycle**（本节点闭式闭合门 G4 的对照基线）；commit 11.61% / evaluator 3.38% / infra 2.61%。
  - 动态聚合（NO00015 dyn run1 归档）：supernode body 执行 **904,549.9/cycle** 量级（sn 行逐键），boundary 检测写 **209,872.37/cycle**；compute op 动态执行总量 **92,212.3M/run = 922,113/cycle**（NO00016 普查口径：sn body fires × unit ops 静态连接，本节点复用同口径）。
  - gsim 环比（NO00008）：0.452 instr/enode；监测比较 87,965 次/cycle（ir 2.39×）。
- **输入核对（sha256，与 NO00001–NO00016 相同，输入未变）**：
  - `testcase/xiangshan/ready-to-run/coremark-2-iteration.bin` = `c764afb8…83e8e`
  - `testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so` = `094c1c4…ff9e`
- **代码状态核对**：wolvrix `dfa59d2`（NO00016 提交，门关 = NO00015 管线逐字节一致已由 NO00016 门 5 验证）、根仓库 `8d49e42`（NO00016 提交）；两仓库工作区干净。冻结面（GRH IR、GRH 已有 pass、XiangShan 与测试源码、reference/gsim）零改动；本节点改动仅限根仓库分析脚本 + Makefile 目标 + 本报告。
- **归档产物核对（数据链路全部在位）**：
  - 生产 checkpoint：`ptmp/no00015_edge_complete_20260925/flow/xiangshan_grhsim_ir.json`（1.4 G，含 partition/schedule/dataLayout；NO00013–16 普查同源解析路径可复用）。
  - 生产 PGO 二进制与对象：`ptmp/no00015_edge_complete_20260925/flow/emu/emu`（PGO 三阶段 phase-3 产物；`flow/model/*.o` 4,540 个为 profile-use 重编译对象）。
  - dyn 归档：`ptmp/no00015_edge_complete_20260925/run1/logs/xs_wolf_grhsim_no00015_edgecomplete_run1_20260926.log`（sn/kind/totals/vchg 行全；确定性计数，NO00015 门 ⅰ–ⅲ 已验证）。
  - 既有设施：`scripts/grhsim_disasm_census.py`（NO00009 反汇编分类普查；符号模式 `_ZN13GrhSIM_SimTop\d+cpu_(task|helper)_\d+Ev` 已对 NO00015 PGO 二进制验证：**4,439 task 符号命中**）、`grhsim_demonitor_census.view_from_model`（unit/op/partition 视图）、`grhsim_vchg_profile.SN_LINE/KIND_LINE`（dyn 行解析）、numpy 2.5.1（无 scipy，NNLS 用 numpy 自实现 active-set）。
  - 结构事实（发射器代码核对）：task 函数 = 派发组（`cpu_flags[w]` 载入→清 0→逐 unit 活跃位测试）；`computeGroup` 以 **unit 为粒度**调用（`cpu_emit.cpp:6345/6379`），ChangedGroup/检测点/帧清零均在 unit 体内；helper 函数名 `cpu_helper_<unitIndex>_<i>` 直接携带单元归属（99 个）；unit 体每 fire 无条件执行全部 op（NO00006 已核实），epilogue 置位臂经 NO00010 组级分支守卫（组开火率由 dyn `chg` 列精确给出）。
- **资源配置**：本节点无新仿真运行（dyn/perfstat 复用归档）；分析步骤为 checkpoint 解析（~分钟级）、objdump 反汇编（实测 ~10 s 级）、NNLS 拟合（秒级）。机器空载要求不适用（纯离线分析，无计时类测量）。
- **计时边界与止损线**：无生成/编译/仿真门槛（诊断节点不触发生产流程，先例 NO00008/NO00012）；分析脚本单次全量运行预期 <30 min 墙钟，超限登记为工程问题并优化解析路径（不构成机制失败）。

## 假设提出（HYPOTHESIS）

- **假设（诊断性）**：compute task 函数的编译后静态指令数可在函数级以 **(逐 kind op 数 + 簿记特征 + 帧字节) 的线性模型**拟合（4,439 样本、加权 R² ≥ 0.90），即逐 kind 存在良定义的**边际静态指令代价**；该代价与确定性动态 fires 闭式连接后，compute 侧动态指令总量可对 perfstat 基线（3,173,679.4 instr/cycle）闭合到 ≤10% 残差。若成立，逐 kind/位宽的动态指令份额表就是剩余密度差距的结构归属；若不成立（R² 或闭合失败），"每 op 成本线性可加"本身被证伪——说明成本由跨 op 上下文效应主导，同样是指导后续节点方向的机制结论。
- **创新点**：① 本分支首个**编译后逐 kind 边际代价**测量——取代 NO00010 起沿用的发射形态普查常数（检测 ~3.5 instr 等），并规避 NO00016 证伪的"静态语句数定价"陷阱（反汇编目标 = clang 实际保留的指令）；② 首个 kind×位宽动态指令**闭式分解**（确定性连接：反汇编静态计数 × dyn 确定性 fires，无采样）；③ 簿记四系数（每检测/每组守卫/每置位臂/每单元派发）的编译后实测校准（NO00010 常数的首次实测复核）；④ 双段宽度模型（kind 模型 + 位宽桶模型）回答 NO00012 遗留的 compute 侧宽值份额问题。
- **瓶颈证据（本分支实测，无新增测量）**：NO00008 因子表（密度 8.54× 唯一主因子）；NO00009/11/16 机制证伪表三条密度路线证伪（结构归属缺失）；NO00010 活动追踪税 ~1.51M/cycle（发射形态常数估计，未编译后核实）；NO00016 实测 0.043 instr/exec（平凡 op 近零成本 ⟹ 动态指令必集中于非平凡 kind/位宽/簿记，分布未知）。
- **微观指标与总目标的定量关系**：
  - **M-kinddyn**（锚定）= 逐 kind 动态 instr/cycle 表：`dynInstr_k = Σ_u body_u × n_{u,k} × c_k`（body_u = NO00015 dyn run1 确定性 body fires；n_{u,k} = checkpoint 静态组成；c_k = NNLS 边际代价）。与总目标关系：compute 占总量 80.35%，逐 kind 动态 instr/cycle 即"该类可压缩空间的上界"（类份额 × 52.672 s ≈ 完全消除该类成本的 Host 上界），直接决定后续优化节点的立项排序（NO00008 方向排序"每 dynOp 指令密度"的结构性落地）。
  - **M-kindcost**（锚定）= c_k 表 + bootstrap 95% CI。与总目标关系：边际代价识别"高价类"（c_k ≫ 均值 3.44 的类是 emit/语义形态问题候选；c_k ≈ 0 的类坐实 clang 塌缩域），并替换 NO00013/14/15 利润模型的定价常数（该序列节点实测实现率 1.29–1.42× 的根源诊断）。
  - **M-widthdyn**（辅）= 位宽桶（w=1 / 2–64 / >64）动态执行与动态 instr 份额。与总目标关系：回答"宽值是否是 compute 侧密度主因"（NO00012 只否定检测侧）；若 >64b 桶指令份额 ≫ 执行份额，宽值车道化/聚合恢复成为强候选，反之封禁该方向。
  - **M-bkacct**（辅）= c_det/c_grp/c_arm/c_unit 边际代价与动态簿记总量（对 NO00010 常数 3.5/2.5/1 的偏差），给出簿记块的真实残余规模（NO00010 后估计 ~1.07M/cycle）。
  - 确定性来源：反汇编静态计数与 dyn fires 均为确定性计数（NO00015 门 ⅱ 已证逐键可复现）；拟合为同一矩阵上的确定性算法（固定种子的 bootstrap 除外，其仅用于 CI 不影响点估计）。
- **预注册**：
  - **测量方法与运行秩序**：①普查脚本与单测（`scripts/grhsim_kind_cost_census.py` + `test_grhsim_kind_cost_census.py`，纯函数 + 编排分离）→ ②checkpoint 解析与逐 task 特征提取（34 kind 计数 + n_units + n_groups + n_arms + n_det + frameBytes + helper 归属）→ ③反汇编普查（NO00015 PGO 二进制，objdump 确定性输出，helper 按名并入所属 task）→ ④dyn run1 归档连接（sn body/chg）→ ⑤NNLS（active-set，numpy 自实现）+ bootstrap 200 次 → ⑥G1–G4 判定 → ⑦报告交付（summary.md/json 归档 ptmp 工作区并整理入正文）。
  - **G1 数据连接有效性**：disasm cpu_task 符号数 == checkpoint 活动驱动 compute task 数（预期 4,439）；helper 符号 99 个全部按名归属单元；Σ_u body_u×|ops_u| == 92,212.3M/run 口径偏差 ≤0.01%；Σ_u chg_u == totals.grp_fire == 254,174,928 精确相等。
  - **G2 确定性**：同一输入两次完整分析，summary.json 逐字节一致。
  - **G3 拟合质量**：函数级静态指令 NNLS（加权，权重 ∝ 1/max(instr,50) 抑制巨函数主导）R² ≥ 0.90；动态份额 ≥1% 的 kind 其系数 bootstrap 95% CI 半宽 ≤ 30% 点估计。降级路径（预注册）：R² 不达标时按语义类聚合为 ~12 桶（logic1/logicN/arith/muldiv/cmp/mux/slice/concat/shift/reduce/state/mem/other）重拟合直至 R² ≥ 0.90 或桶数 <5；仍不达标则 M-kindcost/M-kinddyn 不交付，节点以 REJECTED 登记"每 op 成本线性可加性不成立"的机制结论（此时 M-widthdyn/M-bkacct 若在聚合粒度达标仍交付）。
  - **G4 闭式闭合**：预测动态总量 = Σ_u[body_u×(Σ_k c_k·n_{u,k} + c_grp·grp_u + c_det·det_u) + chg_u×c_arm·arms_u] + Σ_task calls 固定项（计入未建模残差）对 **3,173,679.4 instr/cycle** 的残差 |Δ| ≤ 10%。
  - **G5（辅助登记，不设门）**：宽位（>64b）动态执行/指令份额与 NO00012 M-wide（宽检测站 550、宽 boundary 值 1.06%、宽变化 0.52%）方向一致性核对；逐函数"动态指令份额 vs perf record 采样份额"对照（若 `analyze_grhsim_cpu_profile` 设施对 NO00015 二进制可用）——识别 cache/branch -bound 热点函数，仅登记不设阈。
  - **证伪标准**：G3 拟合质量经降级路径仍不达标，或 G4 闭合残差 >10% 且残差不可归因于已登记未建模项（task 调用固定开销、quiescence/edge 包装、提交相位混入）→ "逐 op 边际成本线性可加"机制性证伪 → REJECTED 并登记机制证伪表（后续节点不得再以逐 kind 成本模型立项）。G1/G2 失败 → 实现瑕疵，修正后重跑（同一节点内）。
  - **验收（诊断节点）**：G1–G4 全过 + M-kinddyn/M-kindcost/M-widthdyn/M-bkacct 四表交付 + 当前最佳指针不动（52.672 s 如实登记）。
  - **构建/性能门槛**：本节点无生产构建、无 100k 新仿真、无 3+3 Host 复测（零性能语义改动，先例 NO00008/NO00012）。

## 代码实施（IMPLEMENTED）

- **普查脚本** `scripts/grhsim_kind_cost_census.py`（编排与纯函数分离）：
  - checkpoint 镜像（对照 `cpu_emit.cpp` 构造规则逐条核对）：`compute_task_units`（schedule[0]→numa[1]→core[1] 走查任务行 `[task_id,part,waits,execution]`，execution==0 为 compute，task→word→unit 两级 children）、`direct_commit_states`（planDirectCommits 镜像：单写端口 + 引用全部来自 state.read/该端口 + 二态 logic ≤64b）、`mirror_port_arms`（planPortArms 镜像：三操作数 boundary + 非别名校验，ordinal 打包 (word,mask) 按 offset 合并）、`active_offsets`（ActiveWord 槽位 → unit 掩码）、`unit_group_features`（ChangedGroup key=(activate,arm,ports) 去重 + 检测站点 + epilogue 置位臂行数）、`frame_sizes`（dataLayout localFrames）。
  - 反汇编普查：`objdump -d --no-show-raw-insn`，符号模式 `_ZN13GrhSIM_SimTop\d+(cpu_(task_\d+|helper_\d+_\d+))E[^>]*>`（对 NO00015 PGO 二进制实测命中 **4,439 task + 238 helper** 函数符号；同址别名 **0**，排除 ICF/折叠混淆）；helper 按名（`cpu_helper_<unit>_<i>`）并入所属 task 的拟合目标。
  - 拟合：Lawson–Hanson active-set NNLS（numpy 自实现，无 scipy），权重 1/max(instr,50)，加权 R²；bootstrap 200 次（固定种子 20260926）出 95% CI；预注册降级路径（34 kind → 13 语义桶 logic1/logicN/arith/muldiv/cmp/mux/slice/concat/shift/reduce/state/mem/other）内建于同一编排。
  - 输出：`summary.json`（门细节 + 三模型系数/CI + 四表数据）+ `summary.md`。
- **单测** `scripts/test_grhsim_kind_cost_census.py`：21 用例覆盖各镜像函数（含 local-mask 同字高位语义、八端口共字打包、非 boundary 拒绝）、NNLS（精确恢复/非负/零解）、加权 R²、dyn 行解析、符号正则、语义桶映射——全过。
- **Makefile 目标**：`analyze_grhsim_kind_cost_census`（GRHSIM_KINDCOST_MODEL/RUN/EMU/OUTPUT/CYCLES）、`test_grhsim_kind_cost_census`。
- **口径细化（实现期发现，按预注册"G1 失败→实现瑕疵，修正后重跑"条款处理）**：预注册 G1 的 dynOps 参照 92,212.3M 实为 NO00016 的"core.compute.* 且排除 constant"子口径；全 op 口径为 **99,495,719,495/run**（本节点独立连接与既有 `grhsim_dynamic_stats.py` 逐点一致，双向交叉验证）。G1 实现为双口径门（compute-excl-constant == 92,212.3M±0.01% 且 all-ops == 99,495,719,495 精确相等）。另：helper 符号实测 **238** 个（BASELINE 节引用的"99 个"来自旧 `Ev` 结尾模式——helper 带参改编码实际以 `EPSt4byteRh` 结尾，本节点正则已按二进制实测修正）。
- 运行命令（两轮同参数，仅输出目录不同）：
  `make analyze_grhsim_kind_cost_census GRHSIM_KINDCOST_MODEL=ptmp/no00015_edge_complete_20260925/flow/xiangshan_grhsim_ir.json GRHSIM_KINDCOST_RUN=ptmp/no00015_edge_complete_20260925/run1/logs/xs_wolf_grhsim_no00015_edgecomplete_run1_20260926.log GRHSIM_KINDCOST_EMU=ptmp/no00015_edge_complete_20260925/flow/emu/emu GRHSIM_KINDCOST_OUTPUT=ptmp/no00017_kind_cost_20260926/census/run_{a,b}`；
  单次全量 ~59 s 墙钟（checkpoint 解析 + objdump + 三模型拟合 + 2×bootstrap 200）。

## 结果测试（TESTED）

- **单测**：21/21 PASS（`make test_grhsim_kind_cost_census`）。
- **G1 数据连接：全过**。

  | 门 | 实测 | 参照 | 结果 |
  |---|---|---|---|
  | task 符号数 == schedule compute+commit 任务数 | 4,439 | 4,439 | PASS（精确） |
  | helper 全部归属 | 238 归属 / 0 孤儿 | — | PASS |
  | dynOps compute-excl-constant | 92,212,256,068 | 92,212.3M（NO00016 口径） | PASS（偏差 0.00005%） |
  | dynOps all-ops | 99,495,719,495 | 99,495,719,495（grhsim_dynamic_stats 交叉） | PASS（精确） |
  | Σ chg == totals.grp_fire | 254,174,928 | 254,174,928 | PASS（精确） |

- **G2 确定性：过**。run_a 与 run_b 的 summary.json / summary.md 逐字节一致。
- **G3 拟合质量：FAIL（全粒度）**。

  | 模型 | 粒度 | 加权 R² | 门 ≥0.90 |
  |---|---|---|---|
  | kind（主） | 34 kind + 6 簿记 | **0.8486** | FAIL |
  | 语义桶（预注册降级） | 13 桶 + 6 簿记 | **0.8136** | FAIL |
  | 位宽桶（M-widthdyn 用） | 4 桶 + 6 簿记 | **0.6987** | FAIL |

  聚合单调降质（0.849→0.814→0.699）：残差是结构性的，非聚合噪声；继续降桶（<5）无意义，降级路径穷尽。CI 门：kind 模型 10 个份额 ≥1% 的 kind 中 4 个 CI 超宽（div 点估计 884.7 而 95% CI 上界 384,840；mux/dpi.call/system.task 同病）。
- **G3 退化证据（不可识别性的直接表现）**：NNLS 把 7 个高频 kind 系数打到精确 **0.000**（eq 68,485.7 exec/cycle、state.read 33,758.2、add 30,930.4、not 16,294.9、gt 10,032.3、assign 3,213.5、sub 1,829.1）——物理不可能（一次 load/cmp 至少 1 条指令）；语义桶模型同样把 13 桶中的 5 桶打到 0（cmp 91,160.6 exec/cycle、logicN 65,757.5、concat 43,085.5、state 33,770.6、arith 32,759.5）。设计矩阵跨 task 共线（RTL op 配比在 4,439 个 task 间近似恒定），逐 kind/逐桶边际代价在该静态信号上不可识别。
- **G4 闭式闭合：FAIL（全粒度）**。预测动态 compute instr/cycle：kind 模型 **5,991,089.3（+88.8%）**、语义桶模型 **3,913,690.9（+23.3%）**，对基线 3,173,679.4 均超 10% 门。已登记未建模项（task 调用固定开销、quiescence/edge 包装、提交相位混入）全部是实际侧的**正**贡献，无法解释模型**高估**——残差方向不符，按预注册证伪条款成立。
- **G5（辅助登记，不设门）**：宽度执行份额实测 w1 640,840.4 exec/cycle（64.4%）、w2_64 323,165.6（32.5%）、**w65p 2,502.1（0.25%）**、无结果 28,439.1（2.9%）——与 NO00012 M-wide（宽检测站 1.06%、宽变化 0.52%）方向一致：宽值在 compute 侧执行占比同样极小。perf record 采样份额对照未做：其校验对象（拟合份额表）已被证伪，对照失去标定目标，按"仅登记不设阈"条款记录为不适用。
- **有效交付与不可交付的边界**：
  - **交付（G1/G2 验证的确定性连接数据，非拟合产物）**：逐 kind 执行计数表（execs/cycle：and 259,568.1、or 214,756.1、mux 115,666.2、eq 68,485.7、bitSelect 47,427.6、concat 42,177.9、sliceStatic 35,752.0、state.read 33,758.2、add 30,930.4、logicNot 21,058.9、constant 18,702.7、sliceDynamic 15,011.0……全表见 `ptmp/no00017_kind_cost_20260926/census/run_a/summary.json` `kind_dynamic.execs_per_cycle`）；位宽执行份额（上条）；簿记**计数**（检测 209.8K/cycle、组守卫 107.0K/cycle、置位臂 123.0K/cycle——计数经 grp_fire 精确锚定）。
  - **不交付（预注册条款）**：M-kindcost/M-kinddyn 的**代价/份额列**（拟合系数物理无效）；M-widthdyn 代价列；M-bkacct 校准系数（n_grp 12.70、n_det 4.02、frame 0.156 均为吸收静态方差的退化解，非真实边际代价）。簿记计数侧（每 fire 的检测/守卫次数）有效，但其单价仍只能引用 NO00010 发射形态常数，编译后校准未达成。
- **机制结论（证伪登记）**：**"逐 op 边际成本线性可加"在编译后口径下不成立**——静态指令计数不能在函数级被逐 kind op 数线性解释（R² ≤ 0.85 且随聚合单调降质），静态×fires 的闭式连接对动态基线高估 23–89%。与 NO00016（0.043 instr/exec）合流：clang -O3+PGO 对超大函数体内 RTL op 代码的塌缩/调度是**跨 op 上下文效应**（常量传播穿透帧槽、分支/宽度分派的执行期跳过、冷块静态存在但不执行），op 的动态成本不是其静态存在的加性函数。后续节点**不得**再以"静态逐 kind 成本 × fires"闭式模型立项做指令归因；归因须走动态测量路径（perf record 符号采样如 NO00009/NO00016，或 PGO 块计数）。

## 判定

**REJECTED**（机制证伪）。G1（数据连接，5 项）与 G2（确定性，逐字节）全过；G3 拟合质量门在 34-kind 与预注册 13 语义桶降级两个粒度均 FAIL（加权 R² 0.8486 / 0.8136 < 0.90），G4 闭式闭合门在两粒度均 FAIL（+88.8% / +23.3%，残差方向不可归因于已登记未建模项）——按预注册证伪条款精确命中"每 op 成本线性可加性不成立"，M-kindcost/M-kinddyn/M-widthdyn/M-bkacct 四表的代价侧不交付。当前最佳指针不动（NO00015，**52.672 s**；本节点零性能语义改动，无重测）。设施留存：`scripts/grhsim_kind_cost_census.py` + 21 单测 + Makefile 双目标；G1 验证的**执行侧**确定性计数（逐 kind execs/cycle、位宽执行份额、簿记计数）与双 dynOps 口径（compute-excl-constant 92,212.3M / all-ops 99,495,719,495）可供后续节点直接引用。
