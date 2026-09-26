# NO00019: 补边迁移——profile 定价的选择性 boundary op 迁移（允许新激活边，widen/重算受控）

| 字段 | 值 |
|---|---|
| 父节点 | NO00015（当前最佳） |
| 角色 | 优化 |
| 状态 | HYPOTHESIS（BASELINE/HYPOTHESIS 已登记；IMPLEMENTED/TESTED 待补） |
| 锚定指标 | **M-net** = 总 instr/cycle（perfstat 确定性口径；基线 **3,949,943.3/cycle**，NO00015 同窗口 3 次均值） |
| 指标阈值 | M-net ≤ **3,947,941.1/cycle**（降 ≥0.0507% = 闭式点估计 −0.0831% 的 61%，沿用 NO00015 阈值推导比率） |
| 回退预算 | Host ≤ +2%（≤53.73 s）；等价/构建门槛不放宽 |
| RUN_ID | no00019_migrate_ec_20260926 |
| 工作区 | ptmp/no00019_migrate_ec_20260926/ |

## 基础选定（BASELINE）

- **父节点**：NO00015（当前最佳指针，GrhSIM-IR PGO 构建 Host 52.672 s，wolvrix `61b092e` + 根仓库 `4e4e40f`）。当前 wolvrix `dfa59d2`（= `61b092e` + NO00016 fold-residue 设施，门关 = NO00015 管线逐字节一致已验证）+ 根仓库 `e6e949d`（NO00018 分析设施），工作区干净、正对 NO00015 终态配置，以其为实施基线，无迂回。
- **立项动机（为什么是这个方向）**：NO00013（零新边迁移）与 NO00015（补边去监测）的结论都把本方向登记为后续第一候选——NO00013："profit>0 选择性子集需动态 widen 控制"；NO00015："迁移变体留作后续节点"。NO00013 只迁移"操作数已在消费单元可用"的零新边内核（静态 widen≡0 证明）；本节点把合格条件放宽到**允许新边**：操作数 w 是受监测 boundary 值且扇出行运行时存活时，迁移 X 进 B 后 B 直接读 w，schedule 重建自动把 B 补进 activate(fanout(w))——**新边由迁移本身经 schedule 重建产生，不需要独立的加边机制**；代价（B 在 w 变化时多火 + X 在 B 既有 fire 中重算）用同负载 dyn profile 定价，profit>0 才选。安全规则全静态（依赖/消费属性触发，IR 层重分区，符合 2026-09-25 用户约束），动态数据只做定价。
- **基线测量（配置未变，复用归档值，不重跑）**：
  - GrhSIM-IR 当前最佳：Host **52.672 s**（NO00015，3 次有效均值，SD 0.015 s）；端点 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`。
  - gsim+PGO 锚点：Host **27.376 s**（SD 0.065 s）；差距 **1.924×（~25.3 s）**。
  - 动态聚合（NO00015 dyn run1 归档，确定性）：boundary 检测写 **209,872.37/cycle**（对 gsim 87,965 仍 2.39×）、受监测行 571,497（本节点普查复核）；总 **3,949,943.3 instr/cycle**（NO00015 perfstat）。
- **输入核对（sha256，与 NO00001–NO00018 相同，输入未变）**：
  - `testcase/xiangshan/ready-to-run/coremark-2-iteration.bin` = `c764afb8…83e8e`
  - `testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so` = `094c1c4…ff9e`
- **代码状态核对**：wolvrix `dfa59d2`、根仓库 `e6e949d`（均为最新提交，工作区干净）。冻结面（GRH IR、GRH 已有 pass、XiangShan 与测试源码、reference/gsim）零改动；改动限 GrhSIM-IR 后端新增 BackendMapping pass + 流程接线 + 分析脚本（goal 文档允许修改 GrhSIM-IR 语义/分区/调度）。
- **归档产物核对**：生产 checkpoint `ptmp/no00015_edge_complete_20260925/flow/xiangshan_grhsim_ir.json`（1.4 G）；dyn run1 日志 `ptmp/no00015_edge_complete_20260925/run1/logs/xs_wolf_grhsim_no00015_edgecomplete_run1_20260926.log`（vchg/sn/kind 行全）；PGO 二进制 `ptmp/no00015_edge_complete_20260925/flow/emu/emu`（3+3 旧侧对照）。
- **立项普查（`scripts/grhsim_migrate_ec_census.py` 对 NO00015 生产 checkpoint + NO00015 dyn run1 profile，`ptmp/no00019_migrate_ec_20260926/analysis/`）**：
  - boundary 值 799,651、受监测（活行）571,497；**候选 15,953 值**（单消费单元 + 边可行；含 79 个零新边残余 = NO00013 单遍未取的二阶机会——消费者迁入 B 后其生产者新变成单消费单元）、新边需求 23,716 条；
  - 拒绝桶：multi_consumer_unit 349,430（结构性不可单点迁移）、no_fanout_row 208,536（已去监测/静默）、producer_kind 86,110、edge_not_boundary 83,969（操作数单元内局部 = 锥迁移域，本节点 cap 1 不进）、closure_source 21,066 / closure_edge 9,050（去监测闭包排除，见假设节）、edge_aliased 6,434、side_effect_unit 5,612、edge_row_missing 4,480、width 8,589、constant_orphan 1（NO00013 常数拒绝规则镜像命中同类边界例）；
  - **去监测闭包（管线位置安全性，新机制）**：本 pass 在 `grhsim.demonitor-edge-completion` 之后运行；NO00015 的移除集在每次 buildSchedule 重验证（树变化致存储值不合格会硬抛错）、NO00014 的规则全量静默重算。被迁 v 若充当已去监测值的覆盖/补边来源（v 的行消失 → 重验证抛错或静默反去监测），或新边目标行携带 NO00015 补边（B 的加入可能使该行新变成 NO00014 可删 → 存储集重验证抛错），均不可接受。排除规则：**v 或任一新边来源 w 落在"已去监测值的非常量生产操作数"闭包内即拒绝**（已去监测值 = 存储行缺失但从树重建的完整行非空的 boundary 值 = NO00014 重放集 ∪ NO00015 存储集，精确刻画无需重实现规则）。普查校验：完整行重建的 NO00014 重放集 = **19,308 值、级联修剪 491，与 NO00014 归档逐点一致**（重建忠实性实证）；NO00015 存储集 22,244（checkpoint 尾字段直读）；闭包 21,396 值；
  - **动态定价（整数缩放 ×4：profit×4 = wr_v×16 − Σ ch_w×((ops_B+1)×13+4) − body_B×K_EVAL×4(kind_X)；K_DETECT=3/K_STORE=1/K_SET=1/K_OP=3.25/K_EVAL 同 NO00012/13 常数）**：profit>0 选中 **6,003 值**（pre-fixpoint 6,359、级联修剪 356；零新边 76）、新边 **8,817 条**（5,805 条 ch_w=0 冷边）；检测写移除 **187,492,791/run = 1,874.91/cycle**；save **7,499.6** − widen 上界 **1,499.2** − reeval 上界 **2,718.1** = **净利 +3,282.3 instr/cycle ≈ M-net 基线的 −0.0831%**；
  - 对照：候选全集静态无差别选择聚合净利 **−264,100.9 instr/cycle**（widen+reeval 主导）——定价选择是机制必需（NO00015 同构教训再现）；
  - 选中集构成（Top：kind×宽度×冷度）：1-bit and 零变化（n=818，profit 816.2）、1-bit logicNot [0.1%,1%)（n=718，808.3）、1-bit not [0.1%,1%)（322.4）、1-bit not (0,0.1%)（272.8）等，详见 `analysis/summary.md`。
- **资源配置**：与 NO00001–NO00018 一致：`XS_EMU_CPU=2`、`XS_EMU_THREADS=1`、`XS_NUM_CORES=1`、`XS_SIM_MAX_CYCLE=100000`、waveform/commit/RAM trace 全关；编译 `VM_BUILD_JOBS=32`；测量时机器空载；逐次 `posix_fadvise(DONTNEED)` 驱页缓存。
- **计时边界与止损线**：
  - SV→C++ 生成 <1800 s（NO00015 同流程 793.17 s 量级）；C++ 编译（PGO 三阶段）<1800 s（NO00015 同流程 651.58 s 量级）；超限记 `TIMEOUT_KILLED`。
  - 生产仿真：比较值预选为 NO00015 归档均值 **52.672 s**，运行上限 **1.5× = 79.01 s**，超时记 `REGRESSION_KILLED`；动态统计诊断运行上限 300 s。
  - 等价性：ir 侧端点四字段精确匹配 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c` 且 DIFFTEST 无 mismatch，否则 `INVALID`（按实现瑕疵处理）。

## 假设提出（HYPOTHESIS）

- **假设**：NO00013 的零新边迁移内核之外存在一个**补边可迁移子类**——v 的全部消费者位于同一计算 supernode B（side-effect free），X 的部分操作数 w 不在 B 可用，但 w 是受监测 boundary 值且扇出行运行时存活（非别名、非 DPI、非 pinned、非 event-gate、不在去监测闭包内）：迁移 X 进 B 后 B 经 X 直接读 w，schedule 重建自动把 B 补入 activate(fanout(w))。NO00013 的五点等价论证逐条保持：① init() 首轮全激活按扁平拓扑序传播初值；② 轮内 w 变化 ⇒ 同轮激活 w 的生产单元与 B（新边），拓扑序 producer(w) < A < B 保证 B 读到新鲜 w（producer(w) < A 因 A 原读 w，A < B 因 B 读 v），激活图无环；③ B 的点火集**只增**（新边 widen），增量上界 Σ ch_w，多火幂等（B side-effect free，纯重算输出不变）语义不可观察；④ A 的点火集只缩不增（X 的操作数离开 A 的输入集）；⑤ 纯二态计算逐比特确定。新鲜性证明与 NO00015 补边同源。**安全规则全静态；w 的热度不可静态知**，利润定价用同负载 dyn profile（PGO 式三阶段方法论向 IR pass 的扩展：安全集合静态决定，profile 只在安全集合内定价选择——NO00015 已立先例）。
- **创新点**：① 本分支首个**允许新边的选择性迁移**——NO00013（移 op、零新边静态内核）与 NO00015（补边、profile 定价）两个 ACCEPTED 机制的组合节点（组合本身即假设：迁移产生的自动补边使 widen 可定价，单遍迁移的 reeval 上界可闭式）；② 首个**去监测闭包**管线位置安全规则（对已去监测值的覆盖/补边来源的精确静态刻画：存储行缺失 ∧ 完整行非空 ⇒ 不可迁、不可作新边来源），解决"后位 pass 改树 → 前位去监测重验证/重放失效"的管线交互；③ 定价含**重算项**（reeval = body_B×K_EVAL(X)，X 在 B 既有 fire 中重算、A 侧节省不计——保守下界方向与 NO00013 实测 4× 一致）。
- **瓶颈证据**：见 BASELINE 立项普查——候选 15,953、选中 6,003、净利闭式 +3,282.3 instr/cycle；残余受监测集 209,872 wr/cycle 对 gsim 87,965 仍 2.39×（NO00015 登记），本节点移除 1,874.9/cycle（−0.893%）。
- **微观指标与总目标的定量关系**：
  - **M-net**（锚定）= 总 instr/cycle（perfstat，确定性 spread ≤2.3e-6，NO00013/15 校准）：基线 3,949,943.3。净利闭式 −3,282.3 ⇒ −0.0831%；未建模正向项（NO00013/15 实测 measured/model = 1.29–4×）：donor 侧 A 每次 fire 少执行 X（≈fires(A)×K_EVAL）、被迁行发布路径（组臂分支 + pending 置位）随行消失、self-retrigger 轮回移除（v 原为 B 的 boundary 输入，A 轮内前一轮产 v 再触发 B 第二轮）、真变化回调移除（cpu_direct_state_changed ≈ ch×回调成本）；未建模负向项：NO00014 重放的奖励性新移除（安全、只缩）。预期实测 M-net −0.08% ~ −0.33% ⇒ Host −~0.06% ~ −0.25%（CPI 中性假设；本机制不新增分支——新边只增长既有发布循环迭代，低于 3+3 秩次分辨底 ~3%，预登记"不判显著、如实登记"，指针依据 = 均值最优 + 确定性计数严格收缩）。
  - **M-shrink**（辅，确定性整数计数）= 动态 boundary 检测写/cycle：基线 209,872.37；移除闭式精确 −187,492,791/run（−1,874.91/cycle）+ widen 侧新增写（有界，见语义门 ⅲ；8,817 新边中 5,805 条 ch_w=0 冷边，预期新增 << 上界，NO00015 实测为上界 7.5%）。
- **预注册**：
  - **测量方法与运行秩序**：①聚焦测试（`test_grhsim_cpu_emit`/`test_grhsim_cpu_schedule`/`test_grhsim_cpu_mapping` + 普查/门脚本单测 + hdlbits 抽样）→ ②门关一致性（默认管线无本 pass，reemit 对 NO00015 归档生产模型逐字节）→ ③生产全流程 gen（migrate + demonitor + edge-completion + migrate-ec 四门开，fold 保持关，edge-completion profile 自 NO00014 dyn run1 导出同 NO00015、migrate-ec profile 自 NO00015 dyn run1 导出）+ 模型语义中性检查（checkpoint strings/types/values/operations 段对 NO00015 归档逐字节）→ ④dyn reemit（四门开 + dynamic-stats）+ dyn 构建 + 2×100k dyn 运行（端点/确定性/sn/kind/vchg/移除集闭式门）→ ⑤PGO 生产构建 → ⑥perfstat 总指令（M-net，新旧同窗口各 3 次）→ ⑦3+3 交替 Host 复测（顺序 old1,new1,old2,new2,old3,new3，逐次 posix_fadvise，`taskset -c 2`）。
  - **改善门槛（锚定）**：M-net ≤ **3,947,941.1/cycle**（降 ≥0.0507% = 闭式点估计 −0.0831% 的 61%；低于此值说明逐写/逐 op 常数或 widen/reeval 上界在迁移+新边机制下失真）。
  - **辅助门槛**：M-shrink 移除量闭式精确吻合（Σwr 移除 = **187,492,791/run**，误差 0）；widen 侧新增检测写 ≤ Σ_B W_B×|B 的受监测输出数|（逐值有界，W_B = 补入 B 的各新边 ch_w 之和）。
  - **语义门**：ⅰ 端点四字段精确 + difftest 干净（dyn ×2 与生产 ×6 全部）；ⅱ dyn sn 行：**未获新边的单元** act/body fires ≤ 基线逐键（donor 收缩允许），**获新边的单元 B** act/body 增量 ≤ W_B（同轮共激活塌缩 ⇒ 实际 ≤ 上界）；ⅲ dyn kind/vchg 行：逐键 ch ≤ 基线（补边单元额外点火输入不变 ⇒ 输出不变 ⇒ ch 不增），wr 对非补边单元产出值 ≤ 基线，对补边单元产出值增量 ≤ W_B；ⅳ 模型语义中性：checkpoint strings/types/values/operations 段对 NO00015 归档逐字节一致（仅 partition/dataLayout/schedule 段变化）；ⅴ hdlbits 161/162（DUT=105 预存失败）；ⅵ 门关：默认管线（无本 pass）reemit 对 NO00015 归档模型逐字节一致；ⅶ 闭式对账：pass 实际迁移值集 == 普查 selected.json 经 restore 规则投影（donor 至少留 1 op，按 donor flat 序 spare 最后候选），零误差；无新 boundary 值产生（slot 翻转集 == 迁移集，零新增）、op 隶属闭式吻合、被迁值不再出现 fanout 行。
  - **构建门槛**：生成 <1800 s、编译（PGO 三阶段合计）<1800 s。
  - **回退预算**：Host 新构建均值 ≤ **53.73 s**（+2%）；改善时以秩次判据登记显著性（预期低于分辨底，预登记"不判显著、如实登记"）。
  - **证伪标准**：M-net 降 <0.0507% 且闭式门全过 → "逐写常数（K_DETECT+K_STORE=4）/ widen/reeval 上界在迁移+新边机制下成立"命题机制性证伪 → REJECTED 并登记机制证伪表；widen 实际超预注册上界、语义门 ⅱ–ⅶ 或构建门槛失败 → 实现瑕疵，回 IMPLEMENTED 修正后重测（同一节点内）。
  - **验收**：锚定门 + 辅助门 + 语义门全过 + 构建门槛通过 + Host 在回退预算内。
  - **预注册修订（2026-09-26，冒烟静态门归因分析之后、任何 TESTED 测量之前登记）**：语义门 ⅳ 的 fanout 闭式原表述基于两个未验证假设——①存活行的 activate == 树导出完整行；②行键集 == 完整行 − NO00014 重放 − NO00015 存储表。冒烟实测 13,362 行 activate 偏离完整行、412 个行键多余。归因分析（`ptmp/no00019_migrate_ec_20260926/closure_analysis.log`，removed=6,070=迁移 6,003+重放漂移 67、appeared=5、零未解释项）证明两者皆非迁移缺陷，而是镜像公式本身偏离 buildSchedule 的实际构造：compute 边以**布局属主**（layout owner）而非生产 op 所在单元判异（迁移值的消费者与存储属主同单元 ⇒ 天然无行，非经去监测删除）、不按 compute-supernode 过滤边目标、event-gate 值携带 arm 边（armed 行重放拒绝移除）、NO00015 存储表重放时向操作数行**补边**（资格重验证后重导 missing edges）。修订后门 5 为 **buildSchedule 精确镜像**：按 C++ 构造规则（ScheduleGraph owner/domain、布局属主边、event-gate arm、空属主触发的空行）重建完整行 → NO00014 最大不动点重放 → NO00015 存储表重放，要求**新树与旧树的存储行（键集、activate 序、arm）逐字节复现**——旧树复现为镜像自校验，新树复现闭合迁移。该门严格强于原表述（镜像逐字节相等蕴含原表述的一切派生断言），属加强而非放宽；单测同步覆盖（布局属主边/域排除/arm/空行/补边重放/存储表重验证）。镜像实测：旧树 full 613,461 → 重放 19,308 → 存储 571,909 逐字节一致；新树 full 607,458 → 重放 19,370 → 存储 565,844 逐字节一致。
  - **预注册修订 2（2026-09-26，首轮 dyn 门 ⅱ/ⅲ FAIL 归因完成之后、修订门重测之前登记）**：首轮 dyn 门实测门 ⅱ 有 1 单元 chg 越界（+1）、门 ⅲ 有 5 值 ch 增长（3326349/3327304/3327647/3327774/3327778，基线 (0,0) → 新 (8713,1)/(1,1) 等）。归因：该 5 值恰为门 5 note 登记的重监测行——旧树经 NO00014 去监测（存储行缺失 ⇒ 基线计数恒为 (0,0)），新树因迁移改变了去监测覆盖条件使重放不再移除其行（监测恢复，安全方向，NO00015 已登记同型漂移）。门 ⅱ/ⅲ 原表述"逐键 ch/chg ≤ 基线"未为此漂移留例外，属门设计盲点而非实现瑕疵（同轮门 ⅷ PASS 且 added_writes=−304,616 证明净漂移为**奖励**：67 条额外移除远超 5 值重监测代价）。修订引入**重监测例外集闭式投影**：例外集 R == 重监测值集（新树存储行键 − 旧树存储行键，门 5 镜像已逐字节给出，不得扩大）；门 ⅲ 对 v∈R 要求基线计数恰为 (0,0)（否则按违例计），其新计数免于增长界限；门 ⅱ 对 R 中值的生产单元放宽 chg 上界 Σ_{v∈R(unit)} ch_v(run1)（闭式：该单元 chg 增长的唯一来源是重监测值自身的变化计数）；R 之外一切键/单元保持原门——投影门而非放宽。单测同步覆盖（例外内基线 (0,0) 通过/例外内基线非零违例/例外外增长仍违例；chg 在宽免内通过、超宽免违例、无宽免仍违例）。

## 代码实施（IMPLEMENTED）

- **pass**：`wolvrix/lib/grhsim/pass/migrate_boundary_ops_ec.cpp`（+ 头）：`grhsim.migrate-boundary-ops-ec`（BackendMapping）带 `--profile <path>`（`# grhsim-migrate-ec-profile v1` 头 + `v id wr ch` / `u id act body grp ch` 标签行，`from_chars` 解析，id 越界报 stale profile 错）。管线位置：edge-completion 之后、fold-residue 之前（`pass.cpp` 注册 + 两脚本 `--migrate-boundary-ops-ec-profile` 选项 + `Makefile` 的 `XS_WOLF_GRHSIM_IR_MIGRATE_EC_PROFILE` / `GRHSIM_REEMIT_MIGRATE_EC_PROFILE`）。资格全静态（NO00013 内核 + 消费者同单元 B side-effect free + 去监测闭包排除：v 自身、其非常量操作数、B 的任何输入不得落在已去监测集——存储行缺失 ∧ 完整行非空的精确刻画），定价整数缩放闭式（save×16 对 Σ ch_w×((ops_B+1)×13+4) + reeval body_B×K_EVAL(X)×4），选择 = 最大不动点（被迁值的非常量操作数不得同被迁），donor 至少留 1 op 的 restore 规则与 NO00013 同源。只置迁移计划并 `refreshCpuSchedule` 重建——新边由 schedule 重建按布局属主规则自动补入，幂等。
- **分析设施**：`scripts/grhsim_migrate_ec_census.py`（资格 + 整数定价 + 不动点 + `--profile-output` 导出 vchg/sn profile；`select()` 为权威实现供门脚本进程内复用）；`scripts/grhsim_migrate_ec_gates.py`（预注册语义门 1–9，门 5 为上述 buildSchedule 精确镜像）；`scripts/grhsim_demonitor_census.py` 增 `stored_ec_removed` 视图字段。单测：普查 13 + 门 18 全过。
- **冒烟对账（NO00015 checkpoint + 本 pass reemit）**：pass 诊断 `migrate_boundary_ops_ec=6003 donors=1383 targets=1762 dropped_nodes=6003 restored=0 eligible=15953 profitable=6359 cascade_trimmed=356 demonitored=41552(=19308+22244) save_x4=2999884656 widen_x4=599688705 reeval_x4=1087249568` 与普查**逐项一致**；静态门 5/5 PASS（门 4 迁移集 == 普查 restore 投影零误差；门 5 镜像如上逐字节）。
- **聚焦测试**：`test_grhsim_cpu_emit`/`test_grhsim_cpu_schedule`/`test_grhsim_cpu_mapping`（+ir）全过；门关：默认管线（无本 pass）reemit 对 NO00015 归档模型逐字节一致（NEUTRAL-IDENTICAL，`gateoff_reemit2.log`）；hdlbits（GrhSIM-IR 管线 `run_all_hdlbits_grhsim_ir_tests` + 逐个 106–162，与 NO00015 同口径）**161/162**——001–104 全过，DUT=105 预存失败错误文本与预注册逐字一致，106–162 全过（57/57）。（附带登记：Verilator 流 `run_all_hdlbits_tests` 在 DUT=042 TB 编译失败，系 NO00014 起登记的预存环境不兼容，非本节点回归口径。）
- **过程记录**：本轮曾因两个依赖 `py_install` 的 make 目标并发跑导致 venv 轮子损坏（`ImportError: _wolvrix`）；串行 `make py_install` 修复后补跑全部受影响任务。纪律：依赖 wolvrix 构建/安装的目标一律串行。

## 结果测试（TESTED）

> 管线脚本 `tested_pipeline.sh`（4 子脚本：`gen_build_pgo.sh` / `dyn_flow.sh` / `gates_dyn.sh` / `measure.sh`），全部产物在 `ptmp/no00019_migrate_ec_20260926/`。dyn 门为首轮 ⅱ/ⅲ FAIL 归因 + 预注册修订 2 后的重测（见 HYPOTHESIS 节）。

### 构建门槛（migrate + demonitor + edge-completion + migrate-ec 四门开，生产全流程）

| 区间 | 墙钟 | 门槛 | 结果 |
|---|---|---|---|
| SV→C++ 生成（`xs_wolf_grhsim_ir` + `XS_WOLF_GRHSIM_IR_MIGRATE_BOUNDARY_OPS=1` + `XS_WOLF_GRHSIM_IR_DEMONITOR_REDUNDANT=1` + `XS_WOLF_GRHSIM_IR_EDGECOMPLETE_PROFILE` + `XS_WOLF_GRHSIM_IR_MIGRATE_EC_PROFILE`，edge-completion profile 自 NO00014 dyn run1 导出、migrate-ec profile 自 NO00015 dyn run1 导出） | **822.13 s**（exit 0） | <1800 s | PASS |
| C++ 编译 PGO 三阶段（`xs_wolf_grhsim_ir_emu_pgo`，-j32） | **680.45 s**（exit 0，profile-use 链接完成） | <1800 s | PASS |
| dyn reemit（四门开 + dynamic-stats）+ dyn 构建 | 76.38 s + 231.42 s | 诊断口径，不占门槛 | — |

pass 诊断 `migrate_boundary_ops_ec=6003 donors=1383 targets=1762 dropped_nodes=6003 restored=0 eligible=15953 profitable=6359 cascade_trimmed=356 demonitored=41552 save_x4=2999884656 widen_x4=599688705 reeval_x4=1087249568` 与普查**逐项一致**（闭式门 ⅶ 一部分；仅 reemit 日志可见此行，xs gen 日志无此行，同 NO00015）。生产静态门 5/5 PASS（gates-prod）。

### 语义门（修订后 dyn 门 9/9 全部通过）

- **ⅰ 端点精确 + difftest 干净**：dyn run1/run2、perfstat 新旧 IR 侧 6 次、bench 6 次共 **14 次 IR 侧运行**端点四字段全部精确 = `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`；perfstat 全 12 次（含 gsim 侧）difftest 干净，bench `--expected-endpoint` 强制校验 exit 0；gsim 侧端点 `[238550,99998,100001,0x80000b40]` 与归档 gsim 口径逐窗口一致。
- **ⅱ sn 行（dyn run1 对 NO00015 dyn run1 基线）**：31,612 单元逐键比较全过——获新边单元（W_B>0）**1,080** 个 act/body/grp 增量全部 ≤ W_B；**260** 个单元严格收缩（donor 侧预期副产物）；chg 逐键 ≤ 基线 + 重监测宽免（2 个新树单元 +2/+3，恰为 Σ_{v∈R(unit)} ch_v(run1) 闭式上界，R 之外零宽免）。
- **ⅲ kind/vchg 行逐键有界**：669,868 值逐键比较全过——迁移集 6,003 值 wr/ch 全为 0；**重监测例外集 R = 5 值**（3326349/3327304/3327647/3327774/3327778，== 新存储行键 − 旧存储行键，门 5 note 交叉吻合）基线计数全部恰为 (0,0)、新计数免检增长；补边单元产出值 22,176 个 wr 增量全部 ≤ 逐值 W_B；34 个 kind 逐键 ch ≤ 基线、wr ≤ 基线 + 类别宽免。
- **ⅳ 模型语义中性**：生产与 dyn checkpoint 的 strings/types/values/operations 段对 NO00015 归档**逐字节一致**（门 1 两侧 PASS）；门 5 buildSchedule 精确镜像在**旧树与新树**的存储行（键集、activate 序、arm）均逐字节复现（旧 571,909 行 / 新 565,844 行）——旧树复现为镜像自校验，新树复现闭合迁移；迁移值无 fanout 行。
- **ⅴ hdlbits**（GrhSIM-IR 管线 `run_all_hdlbits_grhsim_ir_tests` + 逐个 106–162，与 NO00015 同口径）：**161/162**——001–104 全过，DUT=105 预存失败错误文本与预注册逐字一致，106–162 全过（57/57）。（附带登记：Verilator 流 `run_all_hdlbits_tests` DUT=042 TB 编译失败系 NO00014 起登记的预存环境不兼容，非本节点回归口径。）
- **ⅵ 门关中性**：默认管线（无本 pass）reemit 对 NO00015 归档生产模型逐字节一致（`diff -r --exclude='*.o' --exclude='*.a'`，`gateoff_reemit2.log`）。
- **ⅶ 闭式对账**：pass 迁移值集 == 普查 selected 经 restore 规则投影 **6,003 逐一吻合**（门 4 零误差，restore spare 0）；无新 boundary 值（门 2：slot 翻转集 == 迁移集）；op 隶属闭式（门 3：supernode 按 op 集签名无歧义匹配，未迁 op 隶属不变、被迁 op 全部落入共同消费单元）。
- **ⅷ M-shrink 闭式**：removed Σwr = **187,492,791/run 误差 0**；added_writes = **−304,616** ≤ 上界 9,406,094——新增写为**负**（NO00014 重放漂移使 67 行额外移除，奖励远超 5 值重监测代价，净收缩超出迁移集闭式）。
- **ⅸ 确定性**：dyn run1/run2 `[grhsim-vchg]`/`[grhsim-dyn]` 流逐字节一致（门 9 PASS）。

### 锚定微观指标：M-net —— PASS（确定性口径）

perfstat 总 instr/cycle（`analyze_grhsim_native_work`，新旧同窗口各 3 次）：

| 侧 | 3 次 instructions | 均值 instr/cycle | 端点/difftest |
|---|---|---|---|
| 新（NO00019 PGO 二进制） | 394,418,139,317 / 394,417,421,113 / 394,417,216,754 | **3,944,136.5**（spread 2.3e-6） | 四字段精确、difftest 干净 ×3 |
| 旧（NO00015 归档二进制，同窗口复测） | 394,998,436,087 / 394,998,659,493 / 394,997,948,457 | 3,949,944.0（spread 1.8e-6） | 四字段精确、difftest 干净 ×3 |

- **Δ = −5,807.5/cycle = −0.1470%** ≤ **3,947,941.1** 预注册门（降 ≥0.0507%），**PASS**（实测降幅为门槛的 2.9×）。旧侧同窗口复测对归档基线 3,949,943.3 漂移仅 +0.7/cycle，口径确定性确认。
- 实现率 = 实测 −5,807.5 / 闭式点估计 −3,282.3 = **1.77×**（与 NO00013 1.42×、NO00014 1.42×、NO00015 1.29× 同向：利润模型对静态安全内核为保守下界——donor 侧 A 每次 fire 少执行 X、被迁行发布路径、self-retrigger 轮回与真变化回调移除均未建模）。
- CPI 0.6598 vs 0.6577（**+0.33%**，与 NO00013/15 的 CPI 中性微负方向不同，量级在噪声内，如实登记）；branch-misses −0.22%（本机制不新增分支，与预注册论证一致）；cycles +0.18%（instr −0.147% × CPI +0.33% 闭合）。
- gsim 侧参照：新 196,545,336,107 vs 旧 196,545,336,155 均值 instr（同二进制逐窗口一致），模型侧改动对 gsim 无涉印证。

### 辅助微观指标：M-shrink —— PASS（确定性计数闭式精确）

| 指标 | 基线（NO00015 dyn） | 新构建（dyn run1/run2 逐字节一致） | Δ | 判定 |
|---|---|---|---|---|
| M-shrink = Σwr/guest-cycle | 209,872.37/cycle（20,987,446,923/100,001） | **207,994.58/cycle**（20,799,649,516/100,001） | **−1,877.96/cycle = −0.895%** | **PASS** |

- 迁移集移除闭式**零误差**（187,492,791/run = 1,874.91/cycle）；净收缩 −187,797,407/run 超出闭式 304,616（NO00014 重放奖励，见门 ⅷ）。
- 残余受监测集 207,995 wr/cycle 对 gsim 87,965 仍 **2.36×**。

### 最终性能：3+3 交替复测（bench 脚本 preregister 顺序 old1,new1,old2,new2,old3,new3）

逐次 posix_fadvise 驱页缓存、`taskset -c 2`、上限 79.01 s（1.5×52.672），全部 6 次 VALID、端点四字段精确。

| 侧 | 3 次 Host s | 均值 | SD |
|---|---|---|---|
| 旧（NO00015 归档二进制） | 52.620 / 52.545 / 52.898 | 52.688 | 0.186 |
| 新（NO00019 PGO 二进制） | 52.727 / 52.332 / 52.682 | **52.580** | 0.216 |

- **Δ = −0.108 s（−0.204% 同窗口）**；Mann-Whitney 单侧精确 **p=0.5**、秩次判据 FAIL——按预登记**"不判显著、如实登记"**（预期效应低于 3+3 分辨底 ~3%）。bench 口径 −0.204% 落在预登记区间 [−0.06%, −0.25%]；perfstat 窗口附带墙钟口径反号（新 52.528 vs 旧 52.351，+0.34%），两口径差 0.5pp 低于分辨底，以交替协议口径为准。
- 对 NO00015 归档均值 52.672 s：**−0.175%**；对 gsim+PGO 锚点 27.376 s = **1.921×**（剩余差距 ~25.2 s）。
- 回退预算 Host ≤53.73 s：52.580 s，预算内（改善方向）。

### 判定

**ACCEPTED**。预注册验收五项全满足：锚定 M-net 达门（**−0.1470% ≥ 0.0507%**，确定性口径，实现率 1.77×）；辅助 M-shrink 闭式**零误差**（移除 187,492,791/run，widen 新增写 −304,616 ≤ 上界 9,406,094）；语义门 ⅰ–ⅸ 全过（14 次运行端点精确 + difftest 干净、sn/vchg 逐键有界（重监测例外集闭式投影）、模型语义中性逐字节、fanout 镜像新旧树逐字节、hdlbits 161/162、门关 NEUTRAL-IDENTICAL、迁移集与普查投影零误差、确定性逐字节）；构建门槛（822.13 s / 680.45 s）通过；Host 52.580 s 在回退预算内（均值最优，不判显著如实登记）。

- **机制知识（正）**：① 首个**允许新激活边的选择性迁移**兑现——NO00013 零新边迁移内核 × NO00015 profile 定价补边的组合节点：迁移产生的自动补边（8,817 条，5,805 冷边）使 widen 可定价，widen 上界 W_B 动态严格成立（1,080 单元全部 ≤ 上界，同轮共激活塌缩）；② **去监测闭包排除规则**（存储行缺失 ∧ 完整行非空 ⇒ 不可迁、不可作新边来源）解决"后位 pass 改树 → 前位去监测重验证/重放失效"的管线交互，动态零违例；③ 利润模型在迁移+新边机制下仍为保守下界（1.77×）。
- **机制知识（负/边界）**：① **NO00014 重放重监测漂移**——改树可使旧树去监测覆盖不再成立（本节点 5 值重监测，基线恒 (0,0)，安全方向），逐键计数门必须给例外集闭式投影（R = 新存储行键 − 旧存储行键，R 内基线恰 (0,0)、chg 宽免 Σ_{v∈R} ch_v），不能裸用"逐键 ≤ 基线"；② buildSchedule 行构造以**布局属主**判异（非生产 op 单元）、不按 compute-supernode 过滤边目标、event-gate 值带 arm 边、存储表重放向操作数行**补边**——行级镜像公式必须按 C++ 构造规则，朴素"生产 op 单元 + 全量减集"公式在真实模型上偏差 13,362 行 activate + 412 行键；③ CPI +0.33%（branch-misses −0.22% 反向）与历次 CPI 中性微负不同，量级在噪声内、方向如实登记；④ 残余受监测集对 gsim 仍 2.36×，去监测闭包内 41,552 值（覆盖/补边来源）为后续节点须先突破的静态限制。
- **利润模型校准**：M-net 实测 −5.8K/cycle vs 点估计 −3.3K/cycle（1.77×）；Host bench −0.204% ≈ 预登记区间 [−0.06%, −0.25%] 中位。
- **设施留存**：`grhsim.migrate-boundary-ops-ec` pass（`--migrate-boundary-ops-ec-profile` / `GRHSIM_REEMIT_MIGRATE_EC_PROFILE` / `XS_WOLF_GRHSIM_IR_MIGRATE_EC_PROFILE` 门控，门关 = NO00015 管线逐字节一致已验证）+ `grhsim_migrate_ec_census.py` / `grhsim_migrate_ec_gates.py`（单测 13+20，含 buildSchedule 镜像与重监测例外集用例）。
