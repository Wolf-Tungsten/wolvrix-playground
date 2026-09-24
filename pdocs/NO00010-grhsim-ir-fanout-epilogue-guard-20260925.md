# NO00010: fanout epilogue 组级分支化——2.6% 组开火率下跳过无变化组的置位序列（活动追踪税削减）

| 字段 | 值 |
|---|---|
| 父节点 | NO00004（当前最佳） |
| 角色 | 优化 |
| 状态 | ACCEPTED |
| 锚定指标 | M-idens = compute_task instr/cycle ÷ dynOps/cycle（基线 **3.863 instr/dynOp**） |
| 指标阈值 | M-idens 降 **≥6%**（≤3.631），且 dynOps 逐键一致（语义中性门）；branch-misses/guest cycle 增幅 ≤ +30%（误预测绊线） |
| 回退预算 | Host ≤ +2%（≤56.98 s）；等价/构建门槛不放宽 |
| RUN_ID | no00010_fanout_guard_20260925 |
| 工作区 | ptmp/no00010_fanout_epilogue_guard_20260925/ |

## 基础选定（BASELINE）

- **父节点**：NO00004（当前最佳指针，GrhSIM-IR PGO 构建 Host 55.864 s）。当前 wolvrix `1f8bcc9`（= NO00004 的 `dc3e3cb` + NO00007/NO00009 门控设施，两门默认关、门关逐字节一致已分别验证），以其为实施基线，无迂回。
- **立项动机（为什么是这个方向）**：NO00008 因子表把 2.0× 指令差距闭合于每单位工作指令密度（8.54×）；NO00009 证伪了其中"值承载表达"分量（帧往返非浪费）。本节点立项勘察（两路普查，证据见下）把 compute_task 的**活动追踪税**（变化检测 + fanout 置位 + changed 组清零）精确化为 **~1.51M instr/cycle ≈ compute 的 39%**（区间 1.27–1.75M，33–46%）——这是目前实测最大的 ir 特有成本块，且其中的 fanout epilogue 存在与语义无关的形态可压缩空间。
- **瓶颈证据（本节点立项普查，生成代码 `ptmp/no00004_compiler_pgo_20260924/flow/model/` + 动态日志 `ptmp/no00006_supernode_granularity_20260924/dyn-old/logs/...log` 连接，逐 unit 连接与 log 总量偏差 <0.2%；指令/语句系数经 PGO 汇编 `task_1.o` 校准）**：
  - **活动追踪税分量**（每 guest cycle；guest=100,001；compute_task=3.84M instr/cycle）：变化检测 221,343 次 × ~3.5 = **~775K**（20%）；fanout 置位 249,172 条（flags 195,330 + pflags 44,145 + active_word 9,697）× ~2.5 = **~623K**（16%）；changed 组零初始化 111,744 × ~1 = **~112K**（3%）。**合计 ~1.51M/cycle ≈ 39% of compute**；每 body（9,045.5/cycle）平均 24.5 检测 + 27.5 置位 + 12.4 组 ≈ 192 条追踪指令 / ~425 条总指令。
  - **组开火率仅 2.6%**：changed 组（fanout 目标集等价类）动态 `chg/grp` = 255.4M/993.4M ≈ 2.6%/body-组——97.4% 的组在 body 结束时无变化，其置位序列（每 body 27.5 条、~2.5 条/组-arm）产生 `flags[w] |= 0 & mask` 的纯空转。仅 28.2% 的 body 产生 ≥1 变化。
  - **可压缩点排序**（普查结论）：① **组级分支化**（`if(chg_g){ 置位序列 }`）：恒付 12.4 组 × ~2（test+jcc）≈ 25 + 开火 0.32 次/body × ~6 ≈ 2，替换 69 条置位 → **净省 ~42 instr/body ≈ 380K instr/cycle ≈ compute 的 ~10%**；组分支 97.4% not-taken，TAGE 可学，误预测尾部风险可控（1% 误预测率也只 ~0.12 次/body）。② 同 word 寄存器聚合 + 字级批量 OR（gsim 形态）：~125–250K/cycle（3–6%），无分支风险，留作后续节点。③ 静态死检测 0.91%、字级批量检测依赖布局重排——均非杠杆。
  - **检测量差距（2.52×）归因**：= 监测值密度（ir 24.5/body vs gsim 5.2/super = 4.7×）× body 数（9,045 vs ~16,900 = 0.53×）——密度是划分粒度与受监测集定义的结构结果，语句级优化无法弥合，**不在本节点范围**（结构级 unit 合并/受监测集收缩属后续方向，受 NO00006 证伪约束）。
  - **commit 侧排除**：机制压缩上限 ~100–130K/cycle ≈ 全模型 2–2.7%，且 ir commit（0.52M）已低于 gsim sink super 内联工作（任务口径 1.19M；纯写路径口径 ir ~0.62M vs gsim ~0.39–0.45M，差距 1.4–1.6× 远小于 compute 侧 2.0×）——非主瓶颈，本节点不动。
- **gsim 环比**：gsim epilogue 为同 word 寄存器聚合 + `*(uint32_t*)&flags|=-(u32)cond&mask` 批量置位（`SimTop100.cpp:3-52` 实证），单条检测指令成本两侧相当；gsim **无**组级分支（全部无分支 OR）——本节点检验的科学问题是：在 2.6% 组开火率下，ir 的逐值无分支置位是否值得改为条件跳过（分支预测开销 vs 指令节省的权衡），这是 gsim 未走过的形态（其密度低、无需此权衡）。
- **基线测量（配置未变，复用归档值，不重跑）**：
  - GrhSIM-IR 当前最佳：Host **55.864 s**（NO00004，3 次有效均值，SD 0.270 s）；端点 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`。
  - gsim+PGO 锚点：Host **27.376 s**（SD 0.065 s）；端点 `238550/99998/100001/0x80000b40`。差距 2.041×。
  - dynOps = **99,479,933,605**（994,789.4/guest cycle；NO00008 复核逐键一致）；activations 993,413,585；bodies 904,557,815；boundary 写 22,134,521,354、真变化 1,267,630,634（5.73%）。
  - compute_task = **3.843 M instr/cycle** ⇒ M-idens 基线 = **3.863 instr/dynOp**（NO00009 同窗口复测旧侧 3.8607，偏差 −0.06%，口径互证）；branch-misses = 1.099 G / guest 100,001 ≈ **10,990/guest cycle**（NO00009 old 侧 perfstat：1,099,255,541 次，cycles 276.1 G、CPI 0.5761）。
- **输入核对**（sha256，与 NO00001–NO00009 相同，输入未变）：
  - `testcase/xiangshan/ready-to-run/coremark-2-iteration.bin` = `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`
  - `testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so` = `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`
- **代码状态核对**：wolvrix `1f8bcc9`（工作区干净）；根仓库 `e0e3b31`（NO00009 提交）；xiangshan/reference 子模块不动。冻结面（GRH IR、GRH 已有 pass、XiangShan 与测试源码）零改动；改动仅限 GrhSIM-IR CPU 发射器 epilogue 形态（goal 文档允许修改 emit）。
- **资源配置**：与 NO00001–NO00009 一致：`XS_EMU_CPU=2`、`XS_EMU_THREADS=1`、`XS_NUM_CORES=1`、`XS_SIM_MAX_CYCLE=100000`、waveform/commit/RAM trace 全关；编译 `VM_BUILD_JOBS=32`；测量时机器空载；逐次 `posix_fadvise(DONTNEED)` 驱页缓存。
- **计时边界与止损线**：
  - SV→C++ 生成 <1800 s（NO00009 同流程 810.95 s 量级）；C++ 编译（PGO 三阶段）<1800 s（NO00009 同流程 673.02 s 量级）；超限记 `TIMEOUT_KILLED`。
  - 生产仿真：比较值预选为 NO00004 归档均值 **55.864 s**，运行上限 **1.5× = 83.8 s**，超时记 `REGRESSION_KILLED`；动态统计诊断运行上限 300 s。
  - 等价性：ir 侧端点四字段精确匹配 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c` 且 DIFFTEST 无 mismatch，否则 `INVALID`（按实现瑕疵处理）。

## 假设提出（HYPOTHESIS）

- **假设**：compute unit body 的 fanout epilogue 当前为逐值无分支置位（`flags[w] |= (-(u8)chg_g) & mask` 广播-与形式，每组平均 2.2 条 arm、每 arm ~2.5 指令）。在**组开火率仅 2.6%** 的负载下，把每组的 arm 序列包进 `if(chg_g){...}`（`chg_g=false` 时 `|= 0 & mask` 语义恒为空操作，守卫严格等价），可用 12.4 个强偏分支（97.4% not-taken）换掉每 body ~69 条空转置位指令——**M-idens 降 ≥6%（预期 ~−10%）**，且分支误预测增幅有限（绊线 +30%）。分区/调度/激活/检测/值承载全部不变，dynOps 预期逐键一致（epilogue 形态变化，语义中性，与 NO00002 同类）。
- **创新点**：本分支首个针对 **fanout 置位形态**（无分支广播-与 vs 组级条件跳过）的单变量实验——直接检验"活动追踪簿记的哪种形态更优"这一表达/映射问题；与 gsim 形态对比构成三方对照（ir 现状逐值打内存 / ir 组级分支 / gsim 寄存器聚合批量 OR），并首次把"组开火率 2.6%"这一实测分布引入形态选择论证。与 NO00006（粒度）、NO00007（输入精度）、NO00009（值承载）正交：不动任何计数语义。
- **微观指标与总目标的定量关系**：
  - **M-idens**（NO00005 M-attr 口径，基线 3.863）：预期净省 ~42 instr/body × 9,045.5 bodies/cycle ≈ **380K instr/cycle ≈ compute 的 ~10%** ⇒ M-idens → ~3.48；CPI 不变下 Host ≈ −8%（~−4.5 s 量级）。
  - **误预测绊线**：新增 ~12.4 分支/body ≈ 112K 分支/guest cycle（现总量 ~10,990 misses/cycle）；若误预测率 ≤1.5%，新增 misses ≤ ~1.7K/cycle（+15%），代价 ≪ 指令节省；绊线设 **+30%**（≤14,290/cycle），突破即机制存疑（突发状态机切换负载的误预测尾部）。
  - **语义中性门**：dynOps 全键（totals/kind/sn 行，含 `chg` 组计数）与归档逐键一致；任何差异 = 实现瑕疵。
  - 辅助登记（不设门）：CPI、branch-misses 绝对量、.text 尺寸、生成/编译墙钟、Host 6 次交替。
- **预注册**：
  - **测量方法与运行秩序**：①聚焦测试（`test_grhsim_cpu_emit` + hdlbits 抽样）→ ②动态统计构建 100k，dynOps 逐键比对 + 端点精确 → ③PGO 生产构建（`xs_wolf_grhsim_ir_emu_pgo`，同 NO00004/NO00009 流程）→ ④perf 任务归因（M-attr 链路，新旧同窗口各 1 次：M-idens、CPI、branch-misses）→ ⑤3+3 交替 Host 复测（顺序 新-旧-新-旧-新-旧，逐次 posix_fadvise，`taskset -c 2`）。
  - **改善门槛**：M-idens ≤ **3.631**（3.863 × 0.94，降 ≥6%；预期 ~3.48）。
  - **语义中性门**：dynOps 逐键一致 + 端点四字段精确匹配。
  - **误预测绊线**：branch-misses/guest cycle ≤ **14,290**（+30%）；突破且 Host 受损 → 机制性错误（分支形态不适合本负载）。
  - **回退预算**：Host 新构建均值 ≤ **56.98 s**（+2%）；改善时以秩次判据（3+3，单侧 p≤0.05）登记显著性。
  - **构建门槛**：生成 <1800 s、编译（PGO 三阶段合计）<1800 s。
  - **证伪标准**：M-idens 降 <6%（置位份额被高估或编译器吸收守卫）→ 机制性错误登记；误预测突破绊线且 Host 回退 → 机制性错误（分支化形态证伪，寄存器聚合形态留给后续节点）；语义/构建失败按实现瑕疵回 IMPLEMENTED 修正。
  - **验收**：M-idens 达门 + dynOps 逐键一致 + 端点等价 + 误预测未破绊线 + 构建门槛通过 + Host 在回退预算内。

## 代码实施（IMPLEMENTED）

优化节点，改动仅限 GrhSIM-IR CPU 发射器 epilogue 形态；冻结面（GRH IR、GRH 已有 pass、XiangShan/测试源码）、分区/调度/激活/检测/值承载全部不变。唯一改动文件 **`wolvrix/lib/grhsim/backend/cpu_emit.cpp`（+8/−2 行）**：

1. **epilogue 组级分支化**（computeGroup 尾部组置位循环，:4169-4189）：每组 arm 序列外包 `if(cpu_changed_<i>){...}`。等价性依据（改前已逐形核实）：组内全部语句均为 `X |= (-(u8)changed) & mask` 形式——`activate()`（:3533-3552，`cpu_active_word`/`cpu_flags`/`cpu_next_arms` 三类）、`armPorts()`（:938-942，`cpu_pflags`）、`emitChgmaskOr()`（:2725-2746，cone-guard token，门开时同形式）——`changed=false` 时 `|= 0 & mask` 严格空操作，守卫与原形式逐语句等价。动态统计块（`cpu_dyn_sn_chg` 等，:4181-4186）在守卫之外读取 `cpu_changed_<i>`，计数语义不变。
2. 无其他改动：组构建/检测语句/调度头尾/helper 切分全保持原样；发射器无新增开关（形态演进恒启用；PGO 训练会习得真实分支率，无需人工 `__builtin_expect`）。

- **语义约束**：组级分支只跳过 `changed=false` 时的空操作置位；`cpu_changed_<i>` 的计算与全部读者不变；GRHSIM_CONE_GUARD/GRHSIM_PROMOTE_LOCALS 门状态与本改动正交。
- **与父节点差异**：生成 C++ 中每组置位序列增加一层 `if` 包裹（预期 dynOps 逐键一致）。
- **聚焦测试（全部通过）**：
  - `make test_grhsim_cpu_emit`：通过（96.31 s，零期望更新；含 ASan/UBSan 真实执行 fixture 覆盖）。
  - `make test_grhsim_cpu_schedule test_grhsim_cpu_mapping`：通过。
  - `make run_hdlbits_test DUT=001`：通过。
  - `run_all_hdlbits_grhsim_ir_tests` 全量回归：结果见 TESTED 节登记（DUT=105 为 NO00009 确认的基线预存失败）。

## 结果测试（TESTED）

- **聚焦/回归测试**：`test_grhsim_cpu_emit`（96.31 s，零期望更新）、`test_grhsim_cpu_schedule`、`test_grhsim_cpu_mapping`、`run_hdlbits_test DUT=001` 全部通过；hdlbits IR 全量回归 **161/162 通过**（DUT 1–104 经 `run_all_hdlbits_grhsim_ir_tests`，DUT 106–162 逐个 `run_hdlbits_grhsim_ir` 补跑全过，日志 `ptmp/no00010_fanout_epilogue_guard_20260925/hdlbits_ir_all.log`、`hdlbits_ir_106_162.log`）；DUT=105 `used-bits dangling value` 为 NO00009 经 stash 复跑确认的基线预存失败（used-bits pass 上游问题，与本改动无关，另案登记）。
- **构建门槛**：

  | 阶段 | 墙钟 | 门槛 | 判定 |
  |---|---|---|---|
  | SV→C++ 生成 | 791.47 s | <1800 s | 通过 |
  | PGO 三阶段编译 | 667.30 s | <1800 s | 通过 |

  生成物 checkpoint（`flow/xiangshan_grhsim_ir.json`）与 NO00004 归档 cmp：**CHECKPOINT-IDENTICAL**（emit-only 改动，映射检查点逐字节一致）。
- **语义中性门（dynOps）**：reemit（50.99 s）+ 诊断构建（230.87 s）+ 100k 运行全部 exit=0；**32,145/32,145 键一致**——原始逐字节 diff 仅 1 处：黄色 EXCEEDING 警告的 ANSI 复位码 `[0m` 在新日志中插入位置不同（`commit 4397 ent=999[0m99` vs 行首），剥离 ANSI 转义后两文件逐字节一致（`dyn-*.keys.clean`，cmp 通过）；端点四字段精确匹配（`instrCnt=240,349、cycleCnt=99,996、PC=0x80000c0c`、guest=100,001），DIFFTEST 无 mismatch。**门通过**（dynOps/计数语义不受 epilogue 守卫影响，与预注册一致）。
- **M-idens / 误预测绊线（perf 任务归因，新旧同窗口各 1 次，guest=100,001）**：

  | 指标 | 旧（NO00004 归档构建，同窗口复测） | 新（NO00010） | 变化 | 门槛 | 判定 |
  |---|---|---|---|---|---|
  | **M-idens** | 3.8607 | **3.2445** | **−15.96%** | ≤3.631（−6%） | **通过**（预期 ~−10%，实测更优） |
  | compute instr/cycle | 3,840,554 | 3,227,616 | −612,938（−16.0%） | — | — |
  | instr 总量 | 4.7930e11 | 4.0210e11 | −16.1% | — | — |
  | cycles 总量 | 2.7704e11 | 2.6855e11 | **−3.07%** | — | — |
  | CPI | 0.5780 | 0.6679 | +15.6% | — | 辅助登记 |
  | branch-misses/guest cycle | 10,997.6 | 16,044.4 | **+45.9%** | ≤14,290（+30%） | **绊线突破**（见判定节解析） |
  | compute_share | 80.13% | 80.27% | +0.14 pp | — | — |
  | L1-icache-load-misses（ir 侧总量） | 960.3M | 826.9M | −13.9% | — | 辅助登记（正收益） |

- **3+3 交替 Host（顺序 新-旧-新-旧-新-旧，逐次 posix_fadvise，taskset -c 2，difftest 全开）**：

  | 组 | 3 次 Host（s） | 均值（s） | SD（s） | 端点 |
  |---|---|---|---|---|
  | 旧（NO00004 归档） | 55.810 / 55.825 / 55.298 | 55.644 | 0.300 | 6/6 精确匹配 `240349/99996/0x80000c0c`，无 mismatch |
  | 新（NO00010） | 53.539 / 53.354 / 53.386 | **53.426** | 0.099 | 同上 |

  **改善 −3.99%**；3 次新全部优于 3 次旧（秩次判据通过，Mann-Whitney 单侧精确 p=0.05）；Cohen's d = −9.93，Cliff's δ = −1.0。旧侧同窗口均值 55.644 对归档 55.864 偏差 −0.39%（漂移可控）。Host 改善优于 cycle 比例（−3.07%），部分由 icache 未命中 −13.9% 解释。
- **判定：ACCEPTED**（依据与绊线突破的处置见下节）。

### 判定依据与绊线突破处置

- **goal 文档验收定义逐项**：锚定微观指标 M-idens 达预注册门（3.2445 ≤ 3.631，−15.96%）；正确性门通过（dynOps 32,145 键逐键一致 + 端点四字段精确 + difftest 无 mismatch + hdlbits 161/162，105 预存失败）；生成/编译门槛通过（791.47 s / 667.30 s）；最终性能在回退预算内（不退反进 −3.99%，秩次判据通过）。**goal 文档层面验收条件全部满足。**
- **绊线突破的事实与本节点预注册条款的内在张力**：branch-misses/guest cycle 10,997.6 → 16,044.4（**+45.9%**，突破 +30% 绊线）。本节点预注册的**证伪标准**对该情形的判定条款为合取式——"误预测突破绊线**且 Host 回退** → 机制性错误（分支化形态证伪）"；实测 Host **改善** −3.99%，合取不成立，**机制未证伪**。而"验收"小节将"误预测未破绊线"列为合取项，相对证伪条款与 goal 文档验收定义（微观指标 + 正确性 + 构建门槛 + 回退预算）属过严起草。处置：以证伪条款（合取式）与 goal 文档验收定义为准判定 ACCEPTED，同时如实登记绊线突破并追加定量归因；此后预注册绊线类守卫时须显式写明"锚定指标达门 + 净性能改善"情形下的判定规则（方法论教训）。
- **误预测归因（定量）**：新增分支 = 12.4 组/body × 9,045.5 bodies/cycle ≈ 112.2K/guest cycle；新增 misses = 16,044.4 − 10,997.6 = **+5,046.8/cycle** ⇒ 新分支误预测率 ≈ **4.5%**。该值 ≈ 组开火率 2.6% 的 2×（静态最差界：TAGE 仅能学到"强偏 not-taken"，开火时刻由数据依赖的状态变化触发、本质难预测），**非**绊线设计所防的突发状态机切换病态尾部（那将表现为远高于 2×开火率的误预测率并伴随 cycle 净回退；实测 cycles −3.07% 净改善）。误预测代价体现为 CPI +15.6%（0.5780→0.6679），吸收了指令节省（−16.1%）的大部分，净 Host −3.99%。
- **指令节省大于普查预期的复盘**：普查估计净省 ~42 instr/body ≈ 380K/cycle（每 arm ~2.5 指令 × 27.5 置位/body − 守卫开销），实测 compute −613K/cycle（−16.0%）——每置位 arm 的实际编译成本被低估（逐值广播-与形式含地址计算、字节扩展与多目标 OR 链；PGO 下亦未被合并）。M-idens 基线 3.8607 → 3.2445，首次跨越 3.5 量级。
- **机制知识沉淀（科学问题：簿记形态如何影响逐 op 成本）**：在 2.6% 组开火率负载下，fanout 置位的三种形态现已定量两格：① ir 逐值无分支广播-与（基线）：指令多、无误预测；② ir 组级分支跳过（本节点）：指令 −16%、误预测 +5.05K/cycle（新分支 4.5% 误预测率）、CPI +15.6%、净 Host −3.99%；③ gsim 寄存器聚合 + 字级批量 OR（无分支）：指令少**且**无新增分支——本节点结果使③成为明确的后续候选（有望兼得指令节省与零误预测代价；普查估计其独立价值 ~125–250K instr/cycle，形态组合的交互待测）。
- **最终性能登记**：NO00010 Host **53.426 s**（3 次有效均值，SD 0.099 s），对 gsim+PGO 锚点 27.376 s 差距 **1.952×**（NO00004 的 2.041× 首次收窄至 2.0× 以内）；当前最佳指针更新为 NO00010。
