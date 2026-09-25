# NO00014: 冗余变化检测消除——消费单元激活已被生产操作数变化覆盖的 boundary 值去监测化（依赖驱动、激活语义保持）

| 字段 | 值 |
|---|---|
| 父节点 | NO00013（当前最佳） |
| 角色 | 优化 |
| 状态 | **ACCEPTED**（锚定 M-shrink −1.347% 达门（确定性计数，与普查闭式逐点一致）；辅助 M-demon-instr −0.416% 达门；语义门 ⅰ–ⅶ 全过；gen 795.46 s / PGO 编译 678.98 s 过门；Host 52.757 s，同窗口 −0.553%（p=0.2 不显著，预登记如实登记），预算内；**当前最佳指针更新**（均值最优 + 确定性计数严格收缩）） |
| 锚定指标 | **M-shrink** = 动态 boundary 检测写次数/cycle（dyn 构建 `[grhsim-dyn]` kind 行 Σwr ÷ guest cycles；基线 **216,783.6/cycle** = 21,678,575,260 ÷ 100,001，NO00013 归档） |
| 指标阈值 | M-shrink 降 **≥1.2%**（≤214,182/cycle；普查预期 −2,920.2/cycle = −1.347%）；辅以 M-demon-instr = 总 instr/cycle（perfstat 确定性口径，基线 3,984,833.6）降 ≥0.20%（≤3,976,864；普查预期 −11,681 ≈ −0.29%） |
| 回退预算 | Host ≤ +2%（≤54.06 s）；等价/构建门槛不放宽 |
| RUN_ID | no00014_redundant_demonitor_20260925 |
| 工作区 | ptmp/no00014_redundant_demonitor_20260925/（普查 ptmp/no00014_demonitor_census_20260925/） |

## 基础选定（BASELINE）

- **父节点**：NO00013（当前最佳指针，GrhSIM-IR PGO 构建 Host 53.002 s，wolvrix `91a3a95` + 根仓库 NO00013 提交 `2ad2c25`）。当前工作区两仓库干净、正对 NO00013 终态，以其为实施基线，无迂回。
- **立项动机（为什么是这个方向）**：NO00013 把 compute 分解为逐 op 求值 ≈2.1M instr/cycle（与 gsim 全模型工作 1.92M 平价）+ ir 特有簿记 ≈1.84M/cycle ≈ 剩余差距的 ~90%；簿记最大单项仍是 **boundary 变化检测 216,784 次/cycle（gsim 87,965 的 2.46×）**。NO00013 的迁移机制只覆盖**单消费单元 + 零新边**内核（12,583 值）；其拒绝桶中最大类是 **multi_consumer_unit 436,188 值**（值扇出到多个单元，结构性不可迁移）。本节点针对一个正交且更大的静态可证安全类：**v 的变化事件集被其生产 op 操作数的变化事件集覆盖、且每个消费单元都直接被这些操作数的变化激活**——此时 v 的变化检测对激活语义完全冗余（不迁移任何 op、不增删任何激活边能证明的事件），消除检测 + fanout 置位簿记。该机制：① 纯依赖特征静态触发（不动态数据做选择，与 NO00013 同戒律）；② widen≡0 可静态证明（每个消费单元的点火事件集是原集合的子集——只减不增）；③ 是 NO00013 机制的补集（迁移要求消费单元唯一；去监测要求操作数覆盖，对消费单元数量不设限）。
- **机制定义（静态安全规则，逐条可证）**：boundary 值 v（1–64b 二态 logic、非 pinned、非 event-gate），生产者 X = 纯 `core.compute.*` 单结果 op（无 objectRefs、非 constant、非 expr）位于单元 A；v 的 compute fanout 行 arm 表为空；对激活表中的每个消费单元 B：B 只含 `core.compute.*`/`core.state.read`/`core.state.memRead`（无副作用 op，重火幂等），且 X 的每个非常量操作数 w 满足 **B ∈ activate(fanout(w))**（w 的变化直接激活 B）。则：v 变化 ⇒ 某非常量 w 变化 ⇒ 同轮 B 被 w 激活；拓扑序 A < B（v 的消费者在 B ⇒ A 的 op 在 B 的 op 前）保证 B 在同轮 fire 时读到 A 已更新的 v——**v 的检测/发布对 B 的激活与可见性均冗余**。
- **基线测量（配置未变，复用归档值，不重跑）**：
  - GrhSIM-IR 当前最佳：Host **53.002 s**（NO00013，3 次有效均值，SD 0.203 s）；端点 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`。
  - gsim+PGO 锚点：Host **27.376 s**（SD 0.065 s）；差距 **1.936×（~25.6 s）**。
  - 动态聚合（NO00013 dyn 归档）：boundary 检测写 **216,783.6/cycle**、dynOps 994,792/cycle（NO00012 口径）、bodies 9,045/cycle。
  - 指令归因（NO00013 生产构建 perf 归档）：总 **3,984,833.6 instr/cycle**（compute ≈3.19–3.23M、commit 440,696、evaluator 133,496、infra 110,174、libc 35,786，NO00011/NO00013 口径）。
- **输入核对**（sha256，与 NO00001–NO00013 相同，输入未变）：
  - `testcase/xiangshan/ready-to-run/coremark-2-iteration.bin` = `c764afb8…83e8e`
  - `testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so` = `094c1c4…ff9e`
- **代码状态核对**：wolvrix `91a3a95`（工作区干净）；根仓库 `2ad2c25`（NO00013 提交）；xiangshan/reference 子模块不动。冻结面（GRH IR、GRH 已有 pass、XiangShan 与测试源码）零改动；改动限 GrhSIM-IR 后端 schedule/mapping 层（goal 文档允许修改 GrhSIM-IR 语义/分区/调度）。
- **资源配置**：与 NO00001–NO00013 一致：`XS_EMU_CPU=2`、`XS_EMU_THREADS=1`、`XS_NUM_CORES=1`、`XS_SIM_MAX_CYCLE=100000`、waveform/commit/RAM trace 全关；编译 `VM_BUILD_JOBS=32`；测量时机器空载；逐次 `posix_fadvise(DONTNEED)` 驱页缓存。
- **计时边界与止损线**：
  - SV→C++ 生成 <1800 s（NO00013 同流程 824.35 s 量级）；C++ 编译（PGO 三阶段）<1800 s（NO00013 同流程 671.69 s 量级）；超限记 `TIMEOUT_KILLED`。
  - 生产仿真：比较值预选为 NO00013 归档均值 **53.002 s**，运行上限 **1.5× = 79.5 s**，超时记 `REGRESSION_KILLED`；动态统计诊断运行上限 300 s。
  - 等价性：ir 侧端点四字段精确匹配 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c` 且 DIFFTEST 无 mismatch，否则 `INVALID`（按实现瑕疵处理）。

## 假设提出（HYPOTHESIS）

- **假设**：受监测 boundary 值中存在一个**静态可证安全的去监测类**——v 的全部消费单元已被 v 的生产 op 的非常量操作数的变化事件直接激活（B ∈ activate(fanout(w)) ∀w），则 v 的变化检测/发布对激活语义完全冗余：v 变化 ⇒ 某非常量 w 变化 ⇒ w 的发布同轮激活 A（w 是其输入）与 B；拓扑序 A<B 保证 B 同轮读到 A 已更新的 v；v 自己的发布只带来冗余的次轮重火（幂等）。删除 v 的 compute fanout 行后（写/存储保留，发射器既有 `targets==nullptr && !ports` 静默退化路径自动兑现），检测 + fanout 置位簿记消失而激活语义保持：每个单元的点火事件集是原集合的**子集**（widen≡0 静态可证），最终状态逐比特等价。
- **创新点**：本分支首个**激活保持的去监测**机制（NO00013 迁移要求消费单元唯一并移动 op；本机制不移动任何 op、对消费单元数量不设限，正对 NO00013 最大拒绝桶 multi_consumer_unit 436,188 值的一个可证子集）；首个**只改 schedule fanout 表**的 IR 层重分区变体（行删除由依赖覆盖关系触发，checkpoint 的 strings/types/values/operations/partition 段全部不动，仅 mapping schedule 段变化）；多跳覆盖（经中间值传递）已在假设阶段从机制上证明不安全（轮错位：B 会在中间值更新前读到陈旧 v），静态安全规则即为直接覆盖规则本身，无松弛空间。
- **瓶颈证据（本节点立项普查，`scripts/grhsim_demonitor_census.py` 对 NO00013 生产 checkpoint + NO00013 dyn run1 vchg 归档，ptmp/no00014_demonitor_census_20260925/analysis/）**：
  - boundary 值 799,651（NO00013 迁移后），受监测行（activate 非空）**613,049**；
  - **合格（全覆盖）19,799 值**，级联不动点修剪 491 个链内候选后 **19,308 值**（规则：被移除值的非常量生产操作数不得同被移除——否则生产单元 A 可能失去维持 v 新鲜的激活；取最大不动点），动态检测写移除 **2,920.2/cycle = 受监测的 1.347%**；按 NO00012 常数 K_DETECT=3 + K_SET=1 估计 **−11,680.8 instr/cycle ≈ 总指令的 0.29%**；
  - 合格子集构成：constant 6,755（平凡冗余：常量永不变）、sliceStatic 3,598、not 1,895、eq 1,766、logicNot 1,548、sliceDynamic 1,531、and 1,267 等；位宽 1b 11,407 / 9–32b 6,289；
  - **拒绝桶**：operand_not_covering 496,396（机制上限：直接覆盖规则不可松弛）、no_fanout_row 174,568（本就不受监测）、refs_or_results 82,236、side_effect_unit 17,569（消费单元含副作用 op，重火次数收缩可能可观察，排除）、width 8,589、port_arm 74（精确口径下仅 74 个"否则合格"值被保守排除，精确化 armableCommitPort 谓词无价值）、event_gate 417、pinned 3；
  - **state.read 覆盖规则实测为空**（0 值）：消费单元不含同一状态的自有 read（读取本就从单点扇出），该扩展机制证伪、不再考虑；
  - 部分覆盖（可删部分 target）26,289 值 / 6,289 wr/cycle：仅省置位位、保留比较分支，边际收益，本节点不取。
- **微观指标与总目标的定量关系**：
  - **M-shrink**（锚定，同 NO00013 口径）= 动态 boundary 检测写/cycle（确定性整数计数）：基线 216,783.6。被删行的 Σwr 即机械移除量（确定性闭式），每次移除省检测 ~3 instr + fanout 置位 ~1 instr（NO00012/NO00013 常数）——普查预期 −2,920.2/cycle ⇒ 总 instr −~11.7K/cycle ≈ −0.29% ⇒ Host −~0.2–0.3%（低于 3+3 秩次分辨底 ~3%，预登记"不判显著、如实登记"）。
  - **M-demon-instr**（辅）= 总 instr/cycle（perfstat，确定性 spread ≤2.3e-6，NO00013 教训：不用 perf record 份额归因）：基线 3,984,833.6；未建模正向项：消费单元冗余次轮重火移除（dynOps 小副降）。
- **预注册**：
  - **测量方法与运行秩序**：①聚焦测试（`test_grhsim_cpu_emit` 等 + 普查/门脚本单测 + hdlbits 抽样）→ ②门关一致性（默认管线 reemit 对 NO00013 归档生产模型逐字节）→ ③生产全流程 gen（migrate + demonitor 门开）+ 模型语义中性检查（checkpoint 的 strings/types/values/operations 段对 NO00013 归档逐字节一致，partition 段逐字节一致，仅 schedule 段 fanout 行变化）→ ④dyn reemit（双门开 + dynamic-stats）+ dyn 构建 + 2×100k dyn 运行（端点/确定性/sn/kind/移除集闭式门）→ ⑤PGO 生产构建 → ⑥perfstat 总指令（M-demon-instr，新旧同窗口各 3 次）→ ⑦3+3 交替 Host 复测（逐次 posix_fadvise，`taskset -c 2`）。
  - **改善门槛（锚定）**：M-shrink ≤ **214,182/cycle**（216,783.6 × 0.988，降 ≥1.2%；预期 213,709.9 ≈ −1.418%）。
  - **辅助门槛**：M-demon-instr ≤ **3,976,864**（−0.20%）。
  - **语义门**：ⅰ 端点四字段精确 + difftest 干净（dyn ×2 与生产 ×6 全部）；ⅱ dyn sn 行：全部单元 act/body fires ≤ 基线逐键（收缩允许且为预期副产物，任何增加 = 实现瑕疵）；ⅲ dyn kind 行：逐键 wr ≤ 基线 且 ch ≤ 基线；ⅳ 模型语义中性：checkpoint 的 strings/types/values/operations 段及 partition 树对 NO00013 归档逐字节一致（仅 schedule fanout 行变化）；ⅴ hdlbits 161/162（DUT=105 预存失败）；ⅵ 门关：默认管线（demonitor 门关）reemit 对 NO00013 归档模型逐字节一致；ⅶ 移除集闭式：pass 移除值集 == 普查合格集（逐一吻合对账），且无新 boundary 值、无 slot 翻转。
  - **构建门槛**：生成 <1800 s、编译（PGO 三阶段合计）<1800 s。
  - **回退预算**：Host 新构建均值 ≤ **54.06 s**（+2%）；改善时以秩次判据登记显著性（预期 ~0.2–0.3% 低于分辨底，预登记"不判显著、如实登记"）。
  - **证伪标准**：M-shrink 降 <1.2% → 机制性错误（"直接覆盖类存在且发射退化路径兑现"命题证伪，登记机制证伪表）；M-demon-instr 反升且归因于去监测本身（布局/icache 效应主导）→ 按数据复盘判定机制性错误；语义门 ⅱ–ⅶ 或构建门槛失败 → 实现瑕疵，回 IMPLEMENTED 修正后重测（同一节点内）。
  - **验收**：M-shrink 达门 + M-demon-instr 达门 + 语义门全过 + 构建门槛通过 + Host 在回退预算内。

## 代码实施（IMPLEMENTED）

- **改动面（语义约束）**：全部改动限于 GrhSIM-IR 后端 schedule 层 + 流程接线，冻结面（GRH IR、既有 pass、XiangShan 与测试源码、发射器）零改动。partition 树、数据布局、值 slot 全部不动；仅 computeSupernodeFanout 行按静态规则删除（写/存储保留，发射器既有 `targets==nullptr && !ports` 静默退化路径兑现检测消除——该路径自 NO00012 起即服务于无 fanout 的 boundary 写，15,654/cycle 静默写为生产现存先例）。
  - `wolvrix/include/grhsim/ir/model.hpp`：`CpuSchedulePlan` 新增 `demonitorRedundant` 标志（defaulted operator== 自动纳入比较）。
  - `wolvrix/lib/grhsim/backend/cpu_schedule.cpp`：去监测规则实现于 `buildSchedule` 内（`applyDemonitorRedundant`），仅当标志开启时运行——**规则必须活在 buildSchedule 内**，因为 `verifyCpuSchedule` 要求"已安装 schedule == buildSchedule 重建结果"严格相等；标志随 plan 携带，verify 重建时重放同一规则，等式两侧一致。门关时行为与改动前逐字节一致（NO00010 归档 NEUTRAL-IDENTICAL 已验证）。
  - `wolvrix/lib/grhsim/pass/demonitor_redundant.cpp`（+ 头）：`grhsim.demonitor-redundant`（PassKind::BackendMapping）只置标志并 `refreshCpuSchedule` 重建；幂等（已置标志时报 already applied）。
  - `wolvrix/lib/grhsim/io/json.cpp`：标志序列化为 schedule 可选尾字段（仅置位时写出——门关 checkpoint 与旧格式逐字节一致；读取缺省 false，旧归档 checkpoint 兼容）。
  - `wolvrix/lib/grhsim/pass/pass.cpp`、`wolvrix/CMakeLists.txt`：注册与编译接线。
  - 流程接线：`scripts/wolvrix_xs_grhsim_ir.py --demonitor-redundant`（追加于 migrate 之后）、`scripts/reemit_grhsim_ir.py` 同名 flag、`Makefile` 的 `XS_WOLF_GRHSIM_IR_DEMONITOR_REDUNDANT` / `GRHSIM_REEMIT_DEMONITOR_REDUNDANT` 传参。
  - 分析设施：`scripts/grhsim_demonitor_census.py`（+单测 8）、`scripts/grhsim_demonitor_gates.py`（+单测 10，预注册语义门 1–7）、`Makefile` 的 `analyze_grhsim_demonitor[_census]` / `test_grhsim_demonitor_*` 目标。
- **合格规则（与 HYPOTHESIS 静态定义逐条对应）**：v 为 Boundary slot、1–64b 二态 logic、非 pinned（runtime 布局值/inputShadows/inputFanout 源）、非 event-gate、非 port-arm 源（regWrite/latchWrite 前三操作数的保守超集）；生产者 X 为 `core.compute.*` 单结果、无 objectRefs、非 expr（constant 允许：常量永不变，检测平凡冗余）；fanout 行 activate 非空且 arm 为空；每个 target 为计算 supernode、非 A、只含 `core.compute.*`/`core.state.read`/`core.state.memRead`（重火幂等）；X 的每个非常量操作数 w 满足 B ∈ activate(fanout(w)) ∀B。**级联不动点**：被移除值的非常量操作数不得同为候选（否则 A 的激活可能随操作数行的删除而丢失，v 失去新鲜性保证），取最大不动点。**计算 supernode 判定**（实施期修正）：checkpoint 的 partition 树中 `attrs.phase` 全为 None——计算 supernode 须以"kind==Supernode 且首子节点 kind==Node"识别，不能依赖 phase 字段（首版实现误用 phase 判定导致 0 行移除，dyn 模型与 NO00013 零差异，已在 dyn 验证前修复并以移除行数对账确认）。
- **与父节点差异**：wolvrix `91a3a95` + 上述 6 文件（2 新 4 改）；根仓库 + 普查/门/单测 3 脚本 + 2 流程脚本改动 + Makefile 目标。
- **聚焦测试**：`make build` 增量通过（55.87 s）；`make test_grhsim_cpu_emit test_grhsim_cpu_schedule test_grhsim_cpu_mapping` 全过；普查/门脚本单测 8+10 全过；**门关 neutral reemit 对 NO00010 归档生产模型逐字节一致（NEUTRAL-IDENTICAL，排除 *.o/*.a）**。

## 结果测试（TESTED）

### 构建门槛（migrate + 去监测双门开，生产全流程）

| 区间 | 墙钟 | 门槛 | 结果 |
|---|---|---|---|
| SV→C++ 生成（`xs_wolf_grhsim_ir` + `XS_WOLF_GRHSIM_IR_MIGRATE_BOUNDARY_OPS=1` + `XS_WOLF_GRHSIM_IR_DEMONITOR_REDUNDANT=1`） | **795.46 s**（exit 0） | <1800 s | PASS |
| C++ 编译 PGO 三阶段（`xs_wolf_grhsim_ir_emu_pgo`，-j32） | **678.98 s**（exit 0，profile-use 链接完成） | <1800 s | PASS |
| dyn reemit（双门开 + dynamic-stats）+ dyn 构建 | 73.23 s + 247.71 s | 诊断口径，不占门槛 | — |

去监测最终计数（以门脚本对账为准）：移除 fanout 行 **19,308**、剩余 **594,153**；与普查合格集 19,308 **逐一吻合**（闭式门 3，零误差）。

### 语义门（全部通过）

- **ⅰ 端点精确 + difftest 干净**：dyn run1/run2、perfstat 新旧 6 次、bench 6 次共 14 次运行端点四字段全部精确 = `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`；perfstat 6 次 difftest=True、DIFFTEST mismatch 计数 0。
- **ⅱ sn 行（run1 对 NO00013 基线 run1）**：31,612 单元 act/body/grp/chg 全部 ≤ 基线逐键；**504 个单元严格减少**——预期副产物：v 自身的发布原先给消费单元带来冗余的变化驱动重火轮，去监测后该轮消失（样例：1014208 chg 79,459→79,458、1014228 chg 55→4、1014410 chg 66,753→57,197），act/body 计数无增加。
- **ⅲ kind 行逐键 wr ≤ 基线且 ch ≤ 基线**：PASS，无一键回退。
- **ⅳ 模型语义中性**：生产 checkpoint 的 strings/types/values/operations 段及 partition 树对 NO00013 归档**逐字节一致**（gates-prod 门 1–2 PASS，仅 schedule fanout 行变化）；dyn 侧对 NO00013 dyn 归档同门 PASS。
- **ⅴ hdlbits**（GrhSIM-IR 管线 `run_all_hdlbits_grhsim_ir_tests`，与 NO00009–NO00013 同口径）：**161/162**——DUT 001–104 全过，DUT=105 命中预存失败（`used-bits dangling value 101 produced by core.compute.sliceStatic consumed by op 105 core.compute.concat (originalOps=124) (grhsim.used-bits)`，错误文本与预存逐项一致），DUT 106–162 全过（57/57）。附带登记（与本节点无关的预存环境事实）：Verilator 流 `run_all_hdlbits_tests` 在 DUT=042 TB 编译失败（`VlWide<4>`→`const uint32_t*` 无隐式转换，Verilator 5.051 头文件预存不兼容），非本节点回归口径。
- **ⅵ 门关中性**：默认管线（demonitor 门关）reemit 对 NO00010 归档生产模型 **NEUTRAL-IDENTICAL**（IMPLEMENTED 阶段验证，排除 *.o/*.a 逐字节一致）。
- **ⅶ 移除集闭式**：pass 移除值集 **== 普查合格集 19,308 逐一吻合**；模型段/分区中性门蕴含无新 boundary 值、无 slot 翻转。

### 锚定微观指标：M-shrink —— PASS（确定性计数）

| 指标 | 基线 | 新构建 | Δ | 预注册门 | 判定 |
|---|---|---|---|---|---|
| M-shrink = Σwr/guest-cycle（`[grhsim-dyn]` kind 行，确定性整数，run1/run2 逐字节一致） | 216,783.6/cycle（21,678,575,260/100,001） | **213,863.4/cycle**（21,386,551,923/100,001） | **−2,920.2/cycle = −1.347%** | ≤214,182（降 ≥1.2%） | **PASS**，与普查预期 −2,920.2/cycle **逐点一致** |

### 辅助微观指标：M-demon-instr —— PASS（确定性口径）

perfstat 总 instr/cycle（`analyze_grhsim_native_work`，新旧同窗口各 3 次）：

| 侧 | 3 次 instr/cycle | 均值 | 端点/difftest |
|---|---|---|---|
| 新（NO00014 PGO 二进制） | 3,968,257.6 / 3,968,259.4 / 3,968,257.6 | **3,968,258.2**（spread ≤1.8） | 四字段精确、difftest=True ×3 |
| 旧（NO00013 归档二进制，同窗口复测） | 3,984,831.9 / 3,984,828.0 / 3,984,831.9 | 3,984,830.6 | 四字段精确、difftest=True ×3 |

- **Δ = −16,572.4/cycle = −0.416%**（对预注册归档基线 3,984,833.6：−16,575.4 = −0.416%）≤ 3,976,864 门，**PASS**。旧侧同窗口复测对归档基线漂移仅 3.0/cycle，口径确定性确认（NO00013 教训已遵守：不用 perf record 份额归因）。
- 超普查估计 −11,681/cycle（−0.29%）的 1.42 倍：未建模正向项 = 504 个消费单元冗余次轮重火移除带来的 dynOps 副降（方向与 NO00013 donor 侧未建模收益一致：利润模型对静态安全内核为保守下界）。

### 最终性能：3+3 交替复测（bench 脚本 preregister 顺序 old1,new1,old2,new2,old3,new3）

逐次 posix_fadvise 驱页缓存、`taskset -c 2`、上限 79.5 s（1.5×53.002），全部 6 次 VALID、端点四字段精确。

| 侧 | 3 次 Host s | 均值 | SD |
|---|---|---|---|
| 旧（NO00013 归档二进制 sha256 `f7ebcbf2…`） | 53.403 / 52.596 / 53.151 | 53.050 | 0.413 |
| 新（NO00014 PGO 二进制 sha256 `6c905fc2…`） | 52.732 / 52.561 / 52.977 | **52.757** | 0.209 |

- **Δ = −0.293 s（−0.553% 同窗口）**；Mann-Whitney 单侧精确 p=0.2、秩次判据 FAIL——按预登记**"不判显著、如实登记"**（预期 −0.2~0.3% 低于 n=3+3 秩次分辨底）。
- 对 NO00013 归档均值 53.002 s：**−0.462%**；对 gsim+PGO 锚点 27.376 s = **1.927×**（剩余差距 ~25.4 s）。
- 回退预算 Host ≤54.06 s：52.757 s，预算内（改善方向）。

### 判定

**ACCEPTED**。预注册验收五项全满足：锚定 M-shrink 达门（**−1.347% ≥ 1.2%**，确定性计数与普查闭式逐点一致）；辅助 M-demon-instr 达门（**−0.416% ≥ 0.20%**，确定性口径）；语义门 ⅰ–ⅶ 全过；构建门槛（795.46 s / 678.98 s）通过；Host 52.757 s 在回退预算内。

- **机制知识（正）**：首个**激活保持的去监测**节点兑现——直接覆盖类 19,308 值（constant 6,755 平凡冗余 + sliceStatic 3,598 + not 1,895 + eq 1,766 + logicNot 1,548 + sliceDynamic 1,531 + and 1,267 等）的检测/发布对激活语义完全冗余；widen≡0 静态证明动态严格成立（sn/kind 逐键 ≤ 基线、504 单元 chg 收缩 = 预登记的冗余重火移除副产物、零新增）；移除量与普查**闭式对账零误差**；发射器 `targets==nullptr && !ports` 静默退化路径兑现检测消除（NO00012 起 15,654/cycle 静默写先例的延伸）；级联不动点修剪 491 链内候选为安全性必需（否则生产单元 A 失活、v 失新鲜）。实施期教训：checkpoint partition 树 `attrs.phase` 全为 None，计算 supernode 须以"kind==Supernode 且首子节点 kind==Node"识别。
- **机制知识（负/边界）**：多跳覆盖轮错位不安全（假设阶段机制证明，未实施）；state.read 覆盖规则普查为空（0 值，机制证伪）；port_arm 精确化无价值（仅 74 值/14.7 wr）；部分覆盖（26,289 值/6,289 wr）仅省置位位、保留比较分支，边际收益未取；残余受监测集 213,863 wr/cycle 对 gsim 87,965 仍 **2.43×**（operand_not_covering 496,396 为机制上限，直接覆盖规则不可松弛）。
- **利润模型校准**：M-demon-instr 实测 −16.6K/cycle vs 估计 −11.7K/cycle（1.42×，冗余重火移除未建模，同 NO00013 方向）；Host 同窗口 −0.553% ≈ instr −0.416% × CPI 改善闭合。
- **设施留存**：`grhsim.demonitor-redundant` pass（`buildSchedule` 内规则，verify 重建重放一致）+ `--demonitor-redundant` / `GRHSIM_REEMIT_DEMONITOR_REDUNDANT` / `XS_WOLF_GRHSIM_IR_DEMONITOR_REDUNDANT` 门控（门关 = NO00010 管线逐字节一致，NEUTRAL-IDENTICAL 已验证）+ `grhsim_demonitor_census.py` / `grhsim_demonitor_gates.py`（单测 8+10）。
- **当前最佳指针更新**：新构建 Host 均值 **52.757 s** 优于 NO00013 归档 53.002 s（−0.462%）与同窗口复测 53.050 s（−0.553%，p=0.2 不显著、预登记如实登记），且确定性工作计数严格下降（M-shrink −1.347%、总 instr −0.416%）——按索引"最终性能最优的节点"规则指针移至 **NO00014**（如实登记：Host 差低于秩次分辨底，指针依据为均值最优 + 确定性计数严格收缩）。
