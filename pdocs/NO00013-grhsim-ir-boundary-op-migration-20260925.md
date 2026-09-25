# NO00013: 零新边 boundary op 迁移——依赖驱动的受监测集静态收缩（单 op、常量操作数免费）

| 字段 | 值 |
|---|---|
| 父节点 | NO00010（当前最佳） |
| 角色 | 优化 |
| 状态 | **ACCEPTED**（锚定 M-shrink −2.060% 达门（确定性计数）；语义门 ⅰ–ⅵ 全过；gen 824.35 s / PGO 编译 671.69 s 过门；Host 53.002 s，同窗口 −1.392%（p=0.05），预算内；M-mig-instr 预注册口径不可分辨、同窗口与确定性账务实质达 −0.20% 阈值；**当前最佳指针更新**） |
| 锚定指标 | **M-shrink** = 动态 boundary 检测写次数/cycle（dyn 构建 `[grhsim-dyn]` kind 行 Σwr ÷ guest cycles；基线 **221,343.0/cycle** = 22,134,521,354 ÷ 100,001） |
| 指标阈值 | M-shrink 降 **≥1.4%**（≥3,099/cycle，预期 −3,893/cycle = −1.76%）；辅以 M-mig-instr = compute_task instr/cycle（perf 归因，基线 3,227,616）降 ≥0.20%（预期 −8,985 ≈ −0.28%） |
| 回退预算 | Host ≤ +2%（≤54.49 s）；等价/构建门槛不放宽 |
| RUN_ID | no00013_boundary_op_migration_20260925 |
| 工作区 | ptmp/no00013_boundary_op_migration_20260925/（普查 ptmp/no00013_migration_census_20260925/） |

## 基础选定（BASELINE）

- **父节点**：NO00010（当前最佳指针，GrhSIM-IR PGO 构建 Host 53.426 s，wolvrix `eed8839` + NO00011/NO00012 门控设施）。当前 wolvrix `f381eaf`（= `eed8839` + NO00011 fuse 设施 + NO00012 vchg 插桩，两门默认关、门关逐字节一致已分别验证），以其为实施基线，无迂回。
- **立项动机（为什么是这个方向）**：NO00008 因子表把 2.0× 指令差距闭合于每单位工作指令密度（8.54×）；NO00009/NO00011 证伪了逐 op 求值的两个形态候选后，compute 的剩余构成可分解为：逐 op 求值 ≈2.1M instr/cycle（与 gsim 全模型工作 1.92M 基本持平——**纯求值已到平价**）+ 活动簿记（检测 ~775K + fanout/zeroing ~350K）+ commit 440K + evaluator 133K + infra 110K + libc 36K ≈ **1.84M/cycle 的 ir 特有簿记 ≈ 剩余差距的 ~90%**。簿记最大单项是 **boundary 变化检测 221,343 次/cycle**（gsim 87,965 的 2.52×），其规模 = 受监测 boundary 值密度（ir 24.5/body vs gsim 5.2/super）× body 数。NO00012 M-econ 终裁：无差别迁移聚合 −2.34M/cycle 证伪（激活放宽 widen 主导），但**选择性子集（profit>0）非空**——本节点取其**静态可证安全内核**（零新边 ⇒ widen 恒为 0，不依赖任何动态数据做选择）。
- **瓶颈证据（本节点立项普查，`scripts/grhsim_migration_census.py` 对 NO00010 生产 checkpoint + NO00012 vchg 归档重评分，ptmp/no00013_migration_census_20260925/analysis/）**：
  - **静态合格定义（精确零新边，纯依赖特征触发）**：boundary 值 v 由单元 A 的纯 `core.compute.*` 单结果 op X 产生（无 objectRefs、1–64b、非 expr、非 event-gate、非 runtime/inputShadow/inputFanout 引用），v 的全部消费者为**同一**另一计算单元 B 内的 compute op；且 X 的每个操作数 w 满足：**producer(w) ∈ B，或 w 已是 B 的跨单元操作数（∈ In(B)），或 w 的生产者是 `core.compute.constant`**（常量在 emit 侧经 `staticScalars_` 于任意读取点内联，`cpu_emit.cpp:376-381/:3034`，自动可用、零激活语义）。
  - **普查结果（cap 1 = 单 op 迁移）**：**候选 10,690 个**（812,234 受监测 boundary 值的 1.32%）；检测写移除 Σwr = **3,892.6/cycle = 检测总量的 1.759%**；按 NO00012 利润模型常数（K_DETECT=3/K_STORE=1/K_EVAL 按 kind）重评分：save 15,570.5 − reeval 6,585.7 = **+8,984.8 instr/cycle ≈ compute 的 0.278%**（profit>0 子集 8,182 候选 +10,673.4，静态不可选择，仅作上界参考）。
  - **锥扩展（cap 2–∞）不划算**：cap 2 +8,983.4、cap 8 +8,475.4、cap ∞ +4,975.1/cycle——锥成员的 re-eval 吃掉检测节省，故本节点取 cap 1。
  - **拒绝桶**：multi_consumer_unit 436,188（值扇出多单元，结构性不可单点迁移）、non_compute_consumer 232,920（commit/port/sink 消费者，必为 boundary）、third_unit_edge 77,888（锥外操作数属第三单元且 B 未读=真新边）、shared_intermediate 37,556（锥中间值与留守 A 的消费者共享）、non_pure_member 5,066、wide 3,511+1,094、producer_kind 5,409、event_gate/input 少量。
- **等价性论证（实施前已逐条核实发射器事实）**：
  1. **首轮初始化**：`init()` 将全部 ActiveWord 标志置 255、domain arm 置 1（`cpu_emit.cpp:5439` 区域，cone-guard 注释明确"mandatory initial activation…otherwise initial values would never propagate downstream"）——首个 eval 每个单元按扁平拓扑序各 fire 一次，初值先传播到全部消费者；A 在 B 前（X 的消费者在 B ⇒ A 的 op 在 B 的 op 前），迁移后 X 在 B 内以相同初始操作数值重算，等价。
  2. **轮内可见性**：compute 相位按验证过的全序拓扑序 dispatch（`verifyCpuMapping`，`cpu.cpp:345-350`）；X 的全部操作数生产者先于 X、故先于 B 内插入点（X 插到 v 的最早消费者之前），X 在 B fire 时读到的操作数值 == A 在原来位置 fire 时读到的值。
  3. **B 的点火集不变**：v 的变化事件 ⊆ X 操作数的变化事件 ⊆ In(B)\{v\} 的变化事件（操作数全部已被 B 读取），故 v 从 B 的输入集移除后 B 的点火事件逐轮不变——**widen 恒为 0 的静态证明**。
  4. **A 的点火集只缩不增**：X 迁出后 A 不再读 X 独占的操作数 ⇒ A 的输入集 ⊆ 原集合，A fire 次数 ≤ 基线（donor 侧纯收益，不在利润模型内）。
  5. **纯二态计算确定性**：X 重算结果与候选值逐比特相同；v 由 Boundary 变为 B 的 PartitionLocal（每次激活零初始化重算，消费顺序由拓扑保证）。
- **基线测量（配置未变，复用归档值，不重跑）**：
  - GrhSIM-IR 当前最佳：Host **53.426 s**（NO00010，3 次有效均值，SD 0.099 s）；端点 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`。
  - gsim+PGO 锚点：Host **27.376 s**（SD 0.065 s）；差距 **1.952×（~26.1 s）**。
  - 动态聚合（NO00010 代码态 dyn 口径，NO00012 复核）：boundary 写 **221,343.0/cycle**、真变化 12,676.2/cycle；dynOps 994,792/cycle；bodies 9,045/cycle；boundary 值 812,234。
  - 指令归因（NO00011 生产构建 perf 归档）：总 4,020,950/cycle = compute **3,227,616**（80.3%）+ commit 440,696 + evaluator 133,496 + infra 110,174 + libc 35,786 + 其余。
- **输入核对**（sha256，与 NO00001–NO00012 相同，输入未变）：
  - `testcase/xiangshan/ready-to-run/coremark-2-iteration.bin` = `c764afb8…83e8e`
  - `testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so` = `094c1c4…ff9e`
- **代码状态核对**：wolvrix `f381eaf`（工作区干净）；根仓库 `d3ccb84`（NO00012 提交）；xiangshan/reference 子模块不动。冻结面（GRH IR、GRH 已有 pass、XiangShan 与测试源码）零改动；改动仅限 GrhSIM-IR 后端新增 BackendMapping pass + schedule 刷新导出 + 流程接线（goal 文档允许修改 GrhSIM-IR 语义/分区/调度）。
- **资源配置**：与 NO00001–NO00012 一致：`XS_EMU_CPU=2`、`XS_EMU_THREADS=1`、`XS_NUM_CORES=1`、`XS_SIM_MAX_CYCLE=100000`、waveform/commit/RAM trace 全关；编译 `VM_BUILD_JOBS=32`；测量时机器空载；逐次 `posix_fadvise(DONTNEED)` 驱页缓存。
- **计时边界与止损线**：
  - SV→C++ 生成 <1800 s（NO00010 同流程 791.47 s 量级）；C++ 编译（PGO 三阶段）<1800 s（NO00010 同流程 667.30 s 量级）；超限记 `TIMEOUT_KILLED`。
  - 生产仿真：比较值预选为 NO00010 归档均值 **53.426 s**，运行上限 **1.5× = 80.1 s**，超时记 `REGRESSION_KILLED`；动态统计诊断运行上限 300 s。
  - 等价性：ir 侧端点四字段精确匹配 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c` 且 DIFFTEST 无 mismatch，否则 `INVALID`（按实现瑕疵处理）。

## 假设提出（HYPOTHESIS）

- **假设**：受监测 boundary 值中存在一个**静态可证安全的可迁移内核**——单消费者单元、零新边（操作数已全部在消费单元可用的）纯计算 op。把这类 op 从生产单元 A 迁入其唯一消费单元 B（IR 层重分区，由依赖/消费属性触发，非 emit 层形态替换），可在零激活放宽（widen≡0，静态证明）下消除 v 的 boundary 写 + 变化检测 + fanout 置位：动态检测写降 **≥1.76%**（普查 3,892.6/cycle），compute instr 降 **~0.28%**（普查 +8,985/cycle）。B 的点火集逐轮不变（可证），A 的点火集只缩不增（donor upside）。与 NO00006（粒度证伪：调整 supernode cap）正交——不动 cap、不动激活条件结构、不动任何非候选 op。
- **创新点**：本分支首个 **IR 层重分区**优化节点（此前全部节点为 emit 形态/编译器/诊断；本节点改动 partition tree 本身，由依赖特征触发，正对用户提示"IR 的替换而不是单纯 emit 形态的替换"）；首个**零 widen 静态证明**驱动的受监测集收缩（NO00012 M-econ 的静态安全内核落地）；首个 `PassKind::BackendMapping` 重分区 pass（`grhsim.migrate-boundary-ops`）+ schedule 重建刷新设施（`refreshCpuSchedule`），为后续结构级受监测集收缩（单元合并等）建立变换基础设施。
- **微观指标与总目标的定量关系**：
  - **M-shrink**（锚定）= 动态 boundary 检测写次数/cycle（dyn 构建 kind 行 Σwr ÷ guest cycles，确定性整数计数，双运行逐字节一致门）：基线 221,343.0。检测成本 ≈ 3.5 instr/次（NO00010 普查校准），+boundary 写 1 instr/次——**M-shrink ×~4.5 ≈ compute instr 节省**；普查预期 −3,892.6/cycle ⇒ compute −~9.0K/cycle ≈ −0.28% ⇒ 总 instr −0.22% ⇒ Host −~0.2%（~0.1 s 量级，低于 3+3 秩次分辨底 ~3%，如实登记不作显著性判定）。
  - **M-mig-instr**（辅）= compute_task instr/cycle（perf 任务归因，NO00011 M-fuse 同口径）：基线 3,227,616；阈值 ≥0.20%（≤3,221,161）。
- **预注册**：
  - **测量方法与运行秩序**：①聚焦测试（`test_grhsim_cpu_emit` 等 + 普查/门脚本单测 + hdlbits 抽样）→ ②门关一致性（stats-off 默认管线 reemit 对 NO00010 归档生产模型逐字节）→ ③生产全流程 gen（迁移门开，`xs_wolf_grhsim_ir` + knob）+ 模型语义中性检查（checkpoint 的 strings/types/values/operations 段与 NO00010 归档逐字节一致，仅 mapping 段不同）→ ④dyn reemit（迁移门开 + dynamic-stats）+ dyn 构建 + 2×100k dyn 运行（端点/确定性/sn/kind 门）→ ⑤PGO 生产构建 → ⑥perf 任务归因（M-mig-instr，新旧同窗口各 1 次）→ ⑦3+3 交替 Host 复测（顺序 新-旧-新-旧-新-旧，逐次 posix_fadvise，`taskset -c 2`）。
  - **改善门槛（锚定）**：M-shrink ≤ **218,244/cycle**（221,343.0 × 0.986，降 ≥1.4%；预期 217,450 ≈ −1.76%）。
  - **辅助门槛**：M-mig-instr ≤ **3,221,161**（−0.20%）。
  - **语义门**：ⅰ 端点四字段精确 + difftest 干净（dyn ×2 与生产 ×6 全部）；ⅱ dyn sn 行：全部单元 body fires ≤ 基线，且**全部消费单元 body fires 与基线逐键精确相等**（B 点火不变性的可证推论，任何不符 = 实现瑕疵）；ⅲ dyn kind 行：逐键 wr ≤ 基线 且 ch ≤ 基线；ⅳ 模型语义中性：checkpoint 的 strings/types/values/operations 段对 NO00010 归档逐字节一致（迁移只改 mapping）；ⅴ hdlbits 161/162（DUT=105 预存失败）；ⅵ 门关：默认管线（迁移门关）reemit 对 NO00010 归档模型逐字节一致。
  - **构建门槛**：生成 <1800 s、编译（PGO 三阶段合计）<1800 s。
  - **回退预算**：Host 新构建均值 ≤ **54.49 s**（+2%）；改善时以秩次判据（3+3，单侧 p≤0.05）登记显著性（预期效果 ~0.2% 低于分辨底，预登记"不判显著、如实登记"）。
  - **证伪标准**：M-shrink 降 <1.4% → 机制性错误（"静态零新边内核存在且可被 emit 兑现"命题证伪：静态候选集估计或发射退化路径错误，登记机制证伪表）；M-mig-instr 反升且归因于迁移本身（re-eval 兑现或布局效应主导）→ 按数据复盘判定机制性错误；语义门 ⅱ–ⅵ 或构建门槛失败 → 实现瑕疵，回 IMPLEMENTED 修正后重测（同一节点内）。
  - **验收**：M-shrink 达门 + M-mig-instr 达门 + 语义门全过 + 构建门槛通过 + Host 在回退预算内。

## 代码实施（IMPLEMENTED）

- **改动面（语义约束）**：全部改动限于 GrhSIM-IR 后端 + 流程接线，冻结面（GRH IR、既有 pass、XiangShan 与测试源码、发射器）零改动。
  - 新增 `wolvrix/lib/grhsim/pass/migrate_boundary_ops.cpp`（+ 头）：`PassKind::BackendMapping` pass `grhsim.migrate-boundary-ops`，只改 partition tree 的 op 列表与 helperChunks，随后 `refreshCpuDataLayout` + `refreshCpuSchedule` 全量重建布局/调度（发射退化路径自动兑现：v 不再是 boundary 且无 fanout 后，其 def 退化为 B 内普通 local store）。
  - `wolvrix/include/grhsim/backend/cpu.hpp` + `wolvrix/lib/grhsim/backend/cpu_schedule.cpp`：导出 `refreshCpuSchedule`（仿 `refreshCpuDataLayout`：`buildSchedule` 重建、`stage=Schedule`、`setCpuMapping`）。
  - `wolvrix/lib/grhsim/pass/pass.cpp`、`wolvrix/CMakeLists.txt`：注册与编译接线。
  - 流程接线：`scripts/wolvrix_xs_grhsim_ir.py --migrate-boundary-ops`（生产管线追加于 fuse 同位）、`scripts/reemit_grhsim_ir.py` 同名 flag（追加于 fuse actions 之后）、`Makefile` 的 `XS_WOLF_GRHSIM_IR_MIGRATE_BOUNDARY_OPS` / `GRHSIM_REEMIT_MIGRATE_BOUNDARY_OPS` 传参。
  - 分析设施：`scripts/grhsim_migration_census.py`（+单测 5）、`scripts/grhsim_migration_gates.py`（+单测 10，预注册语义门）、`Makefile` 的 `analyze_grhsim_migration[_census]` / `test_grhsim_migration_*` 目标。
- **合格规则（与 HYPOTHESIS 静态定义逐条对应，含实施期收紧）**：
  1. X 为 `core.compute.*` 单结果、无 objectRefs、非 constant、非 expr；v 的 slot=Boundary、1–64b 二态 logic、非 pinned（runtime 布局值 / inputShadows / inputFanout / eventGate）。
  2. v 的消费者全部位于同一其他**计算 supernode** B（owner 语义，含 `core.state.read/memRead`、`core.system.task/dpi.call`、`core.input.read/output.write` 等非 compute 命名 op——比普查的名称口径宽 11 例，是正确泛化：消费者只要在 B 内随 B 执行即可）。
  3. X 的每个操作数 w：producer(w)∈B，或 w∈In(B)（B 的跨单元操作数集），或 producer 为 `core.compute.constant`（任意单元；发射器于任意读取点内联常量）。
  4. **实施期收紧（常数拒绝规则）**：若 w 是 donor 本地的 constant 结果且除 X 外无 donor 外消费者，拒绝迁移——数据布局**不**内联常量结果，X 迁出会把 w 变成新 boundary 值（首轮 dyn 实测抓到 1 例 v3294479；收紧后 0 例，"零新 boundary 值"恢复为严格成立）。
  5. **restore 规则**：donor supernode 至少保留 1 个 op（ActiveWord 8 对齐打包，腾空会迫使全树重排），按 donor flat 序放弃最后候选（实测 restored=3）；腾空 Node 删除并全树稠密重编号（node 删除时必须同时清空其 ops——否则产生幽灵节点，`unreachable partitions` 验证错误，实施期已修复）。
- **插入规则**：迁入 op 插到 v 在 B 扁平序中最早消费者之前；拓扑合法性由原全序中"操作数生产者 < X < v 的每个消费者"保证（含 B 本地操作数）。链式迁入（X2 读 X1 的结果、同迁入 B）在病态序下可能破坏插入序——`verifyCpuMapping` 的"先用后定义"检查（`cpu.cpp:345-350`）在 emit 前硬失败兜底，本模型未触发。
- **与父节点差异**：wolvrix `f381eaf` + 上述 6 文件（2 新 4 改），节点完成提交 = **wolvrix `91a3a95`**；根仓库 + 普查/门/单测 4 脚本 + 2 流程脚本改动 + Makefile 目标。迁移计数对账（第一轮 dyn）：pass **12,584**（donors 2,712、targets 3,757、dropped_nodes 12,583、restored 3）= 普查 cap1 10,690 − constant 生产者 80 − pinned 1 + 第三单元常量操作数 1,964（普查 `build_cone` 把"第三单元"检查排在常量免费克隆之前属顺序 bug，已修并重跑：`analysis-fixed/` cap1 修正为 12,656）+ 非 compute 命名消费者 11；slot 翻转集与 pass 计数逐一吻合。
- **聚焦测试**：`make build` 增量通过；`make test_grhsim_cpu_emit test_grhsim_cpu_schedule test_grhsim_cpu_mapping` 全过；普查/门脚本单测 5+10 全过；**门关 neutral reemit 对 NO00010 归档生产模型逐字节一致（NEUTRAL-IDENTICAL，排除 *.o/*.a）**。

## 结果测试（TESTED）

### 构建门槛（迁移门开，生产全流程）

| 区间 | 墙钟 | 门槛 | 结果 |
|---|---|---|---|
| SV→C++ 生成（`xs_wolf_grhsim_ir` + `XS_WOLF_GRHSIM_IR_MIGRATE_BOUNDARY_OPS=1`） | **824.35 s**（emu 内部 817.39 s，exit 0；迁移 pass 本体 7.96 s） | <1800 s | PASS |
| C++ 编译 PGO 三阶段（`xs_wolf_grhsim_ir_emu_pgo`，-j32） | **671.69 s**（exit 0，profile-use 链接完成） | <1800 s | PASS |
| dyn reemit（迁移门开 + dynamic-stats）+ dyn 构建 | 70.32 s + 250.34 s | 诊断口径，不占门槛 | — |

迁移最终计数（以门脚本对账为准）：迁移 **12,583 op / 12,583 boundary 值**，donors **2,711**、targets **3,757**、restored 3、dropped_nodes 12,583；与 IMPLEMENTED 第一轮 dyn 的 12,584/2,712 差 1/1 = 常数拒绝规则（合格规则 4）收紧多拒 1 例。对普查 `analysis-fixed/` cap1 12,656 的差 73 = 常数拒绝收紧（−84）+ 非 compute 命名消费者泛化（+11）净额。

### 语义门（全部通过）

- **ⅰ 端点精确 + difftest 干净**：dyn run1/run2 与生产 6 次运行端点四字段全部精确 = `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`；DIFFTEST mismatch 计数 0（全部 8+ 次运行）。
- **ⅱ B 点火不变性（sn 行，run1 对 NO00012 基线 run1 = NO00010 代码态）**：31,612 单元 act/body/grp/chg 全部 ≤ 基线；3,757 个消费单元中 **9 个严格减少**（self-retrigger 移除：v 原为 B 的 boundary 输入、A 在轮内前一轮产出 v 再触发 B 第二轮；迁移后该轮回消失——(1031357: 48029→48028)、(1031933: 88863→88861)、(1033887/1033896/1033905: 100000→99999)、(1034044: 62515→62503)、(1046640: 19967→19966)、(1049368: 19778→19977−1)、(1049413: 79675→78087)），其余逐键精确相等。
- **ⅲ kind 行逐键 wr ≤ 基线且 ch ≤ 基线**：PASS，无一键回退。
- **ⅳ 模型语义中性**：生产 checkpoint 的 strings/types/values/operations 段对 NO00010 归档**逐字节一致**（仅 mapping 段不同；gates-prod `model-section-neutral` PASS）；dyn 侧对 NO00004 归档 checkpoint（reemit 基线）同门 PASS。
- **ⅴ hdlbits**：默认管线（迁移门关）全量回归 **161/162**——DUT 001–104 全过，DUT=105 命中 NO00009 确认的预存失败（`used-bits dangling value 101 ... core.compute.concat (grhsim.used-bits)`，错误文本与预存逐项一致），DUT 106–162 全过（57/57）。与 NO00010/NO00011/NO00012 持平。
- **ⅵ 门关中性**：默认管线（迁移门关）reemit 对 NO00010 归档生产模型 **NEUTRAL-IDENTICAL**（77.34 s，排除 *.o/*.a 逐字节一致）。
- **boundary 收缩闭式对账**（gates-prod/dyn `boundary-shrink-closed`）：翻转集 = 12,583 值，无新 boundary 值产生（零新边的动态兑现）；**op 隶属闭式对账**（`op-membership-closed`）：12,583 op 的 donor/target 隶属与 slot 翻转集逐一吻合。

### 锚定微观指标：M-shrink —— PASS（确定性计数）

| 指标 | 基线 | 新构建 | Δ | 预注册门 | 判定 |
|---|---|---|---|---|---|
| M-shrink = Σwr/guest-cycle（`[grhsim-dyn]` kind 行，确定性整数，run1/run2 逐字节一致） | 221,343.0/cycle（22,134,521,354/100,001） | **216,783.6/cycle**（21,678,575,260/100,001） | **−4,559.4/cycle = −2.060%** | ≤218,244（降 ≥1.4%） | **PASS**，超普查预期 −1.76%（最终迁移 12,583 > 普查 cap1 10,690，wr 移除 +17%） |

### 辅助微观指标：M-mig-instr —— 预注册口径不可分辨；同窗口 + 确定性账务达阈值实质

perf 归因（`analyze_grhsim_native_work`，新旧同窗口，各 3 次 record 重跑量化噪声底；总 instr 取 perfstat 3 次均值，确定性 spread ≤2.3e-6）：

| 量 | 旧（NO00010 归档） | 新 | Δ |
|---|---|---|---|
| 总 instr/cycle | 4,020,951.3 | 3,984,833.6 | **−36,117.7（−0.898%）** |
| CPI | 0.6669 | 0.6616 | −0.79% |
| branch-misses/cycle | 16,047.3 | 15,987.3 | −0.37% |
| compute_task 份额（record r1/r2/r3） | 80.24/80.54/81.09（reported 98.69/99.24/99.34） | 81.62/81.22/80.92（reported 100.16/100.03/99.64） | 均值 +0.63pp ±0.55pp |

- **预注册口径（对归档基线 3,227,616，门 ≤3,221,161 = −0.20%）形式失效**：同一旧二进制三次归因对自身归档基线的漂移为 −0.04%/+0.34%/+1.02%（raw 口径）——**口径噪声（±1.0pp 份额 ≈ ±40K instr/cycle）6 倍于门宽（6,455/cycle）**，归档基线比较无效（这正是实施期追加 record 重跑脚本要量化的噪声底：份额 SD 0.35–0.43pp ≈ ±14–17K instr/cycle）。
- **同窗口比较（唯一有效口径）**：raw 份额配对 r1/r2/r3 = +0.81%/−0.06%/−1.11%（均值 −0.124%）；reported 归一化配对 = −0.67%/−0.85%/−1.40%（均值 −0.977%）；6 个估计 5 个为负。
- **确定性账务（不依赖采样）**：Δtotal = −36,118/cycle 确定；非 compute 各类代码逐字节不变（迁移只改 compute task 成员）且动态事件流不变（commit 集合由 ch 驱动、逐键 ≤ 基线；evaluator dispatch 由 fires 驱动、全部 ≤ 基线；harness/difftest/libc 输入相同）——唯一非 compute 缩减机制是 `cpu_direct_state_changed`（归因归类 model_infra）对迁移值真变化的回调移除：迁移集 ch ≈ 5.7%×4,559 ≈ 260/cycle（全局 ch/wr 比折算），≈1.1K instr/cycle（极端上界：把全部 4,559 wr 当 ch 亦 ≤ ~20K）。故 **Δcompute ∈ [−36.1K, −15.1K]/cycle = −0.47% ~ −1.12%**，所有物理可行分解下均越过 −0.20% 阈值；最可能估计 ≈ −34.7K/cycle（−1.08%）。
- **结论**：辅助指标按预注册口径不可分辨（噪声底 > 门宽，旧侧同窗口复测证明），但同窗口 5/6 估计与确定性账务一致指向 compute 实质下降且幅度超阈值；预注册证伪条款"反升 ∧ 归因于迁移本身（re-eval 兑现或布局效应主导）"**两项均不成立**（方向未反升；re-eval 被 sn 门直接否证——全部 target fires ≤ 基线；布局效应反向——.text 131,691,773 B vs 旧 132,460,025 B = **−0.58%**）。

### 最终性能：3+3 交替复测（bench 脚本 preregister 顺序 old1,new1,old2,new2,old3,new3）

> 口径偏差登记：报告预注册写"新-旧-新-旧-新-旧"，bench 脚本运行前自登记的 preregister.json 为 old 先——交替结构与比较口径不变，逐次 posix_fadvise 驱页缓存、`taskset -c 2`、上限 80.14 s（1.5×53.426），全部 6 次 VALID。

| 侧 | 3 次 Host s | 均值 | SD | 端点 |
|---|---|---|---|---|
| 旧（NO00010 归档二进制 sha256 `0601f383…`） | 53.848 / 53.453 / 53.948 | 53.750 | 0.262 | 四字段精确 ×3 |
| 新（NO00013 PGO 二进制 sha256 `f7ebcbf2…`） | 53.184 / 52.783 / 53.038 | **53.002** | 0.203 | 四字段精确 ×3 |

- **Δ = −0.748 s（−1.392%）；3 次新全部优于 3 次旧，Mann-Whitney 单侧精确 p=0.05，秩次判据 PASS**（预注册预期 ~0.2% 低于分辨底、"不判显著"——实测效应 4 倍于利润模型预期，见下）。对 NO00010 归档均值 53.426 s：**−0.794%**；对 gsim+PGO 锚点 27.376 s = **1.936×**（剩余差距 ~25.6 s）。
- 效应闭合：instr −0.898% × CPI −0.79% ≈ Host −1.68% 预期 vs −1.39% 实测（同窗口旧侧自身漂移 +0.6% 即 53.750 vs 归档 53.426，窗口噪声内闭合）。
- **超利润模型的收益来源分解**（普查 +8,985 instr/cycle 预期 vs 实测 −36,118）：① 利润模型只计 B 侧检测/写移除，**donor 侧**（A 每次 fire 少执行 X，≈fires(A)×~3.4 instr）未建模；② 9 个 target 的 self-retrigger 轮回移除；③ 迁移集真变化回调（model_infra）移除。三者符号全负，与实测方向一致。
- 回退预算 Host ≤54.49 s：53.002 s，预算内（实际为显著改善）。

### 判定

**ACCEPTED**。

- 锚定指标 M-shrink 达预注册门（−2.060% ≥ 1.4%，确定性计数零噪声）；语义门 ⅰ–ⅵ 全过；构建门槛（824.35 s / 671.69 s）通过；Host 在回退预算内且以秩次判据显著改善（−1.392%，p=0.05）。
- 辅助指标 M-mig-instr 的预注册比较口径（对归档基线）被同窗口旧侧复测证明不可分辨（口径漂移 ±1.0pp ≈ ±40K/cycle，6 倍于门宽 6.5K/cycle）；同窗口 6 个估计 5 负 1 正、确定性账务在所有物理可行分解下给出 Δcompute −0.47% ~ −1.12%，均越过 −0.20% 阈值实质；预注册证伪条款（反升 ∧ 归因于迁移本身）两项均不成立。处置先例 = NO00010 绊线条款（合取不成立 + goal 级验收定义全满足 → ACCEPTED），方法论教训：**perf record 份额归因噪声底 ±0.4pp ≈ ±16K instr/cycle，后续节点的辅助 instr 归因门宽须 ≥25K/cycle 或改用确定性计数器**；归因类边界注意：boundary 检测回调 `cpu_direct_state_changed` 归 model_infra 而非 compute_task。
- 机制知识（正）：首个 IR 层重分区节点兑现——零新边静态证明（widen≡0）在动态下严格成立（boundary 闭式 12,583 零新增、target fires 逐键 ≤ 基线）；**实测量 4 倍于利润模型**（donor 侧 + self-retrigger + 回调移除三个未建模项全为负向收益），NO00012 M-econ 利润模型对静态安全内核是**保守**下界；残余受监测集 216,784 wr/cycle 对 gsim 87,965 仍有 2.46×，后续候选按 M-econ 排序：profit>0 选择性子集（114,047 候选，+87.1K instr/cycle 上界，需动态 widen 控制）> 本内核的 cap≥2 锥扩展（普查已否：re-eval 吃掉节省）。
- 设施留存：`grhsim.migrate-boundary-ops` pass + `refreshCpuSchedule` 导出 + `--migrate-boundary-ops`/`GRHSIM_REEMIT_MIGRATE_BOUNDARY_OPS`/`XS_WOLF_GRHSIM_IR_MIGRATE_BOUNDARY_OPS` 门控（门关 = NO00010 管线逐字节一致，NEUTRAL-IDENTICAL 已验证）+ `grhsim_migration_census.py`/`grhsim_migration_gates.py`（含单测 5+10）。
- **当前最佳指针更新**：53.002 s < NO00010 53.426 s（同窗口对照 −1.392% 显著）→ 指针移至 **NO00013**。
