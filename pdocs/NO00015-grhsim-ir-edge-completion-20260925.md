# NO00015: 补边去监测——为覆盖缺失的操作数补激活边后删除冗余检测（widen 受控、利润>0 选择性）

| 字段 | 值 |
|---|---|
| 父节点 | NO00014（当前最佳） |
| 角色 | 优化 |
| 状态 | **ACCEPTED** |
| 锚定指标 | **M-net** = 总 instr/cycle（perfstat 确定性口径；基线 **3,968,258.2/cycle**，NO00014 同窗口 3 次均值） |
| 指标阈值 | M-net ≤ **3,959,656.9/cycle**（降 ≥0.217% = 修正后闭式点估计 −0.3577% 的 61%；**修订**：原阈值 3,944,448.7 基于含别名伪冷定价的错误选择集（点估计 −0.99%），实施期正确性修正后作废，见假设提出节"预注册修订"） |
| 回退预算 | Host ≤ +2%（≤53.81 s）；等价/构建门槛不放宽 |
| RUN_ID | no00015_edge_completion_20260925 |
| 工作区 | ptmp/no00015_edge_complete_20260925/ |

## 基础选定（BASELINE）

- **父节点**：NO00014（当前最佳指针，GrhSIM-IR PGO 构建 Host 52.757 s，wolvrix `32be521` + 根仓库 NO00014 提交 `c1259a0`）。当前工作区两仓库干净、正对 NO00014 终态，以其为实施基线，无迂回。
- **立项动机（为什么是这个方向）**：NO00014 的去监测只覆盖**直接覆盖**类（消费单元 B 已被 v 的生产 op 的全部非常量操作数激活，19,308 值）；其普查最大拒绝桶是 **operand_not_covering 496,396 值**——B 缺失部分操作数边，检测无法无偿删除，被标注为"机制上限"。本节点针对该桶的一个**利润>0 子集**：缺失边本身可以**补上**（w 是受监测 boundary 值且已激活 A，把 B 加入 activate(fanout(w)) 即得到与 NO00014 逐字相同的新鲜性证明），补边后 v 的检测同样冗余；代价是 B 在 w 变化但 v 结果不变时多火一轮（widen，纯计算单元重火幂等、语义不可观察）。是否合算是**纯性能问题**：save = wr_v×4 instr（检测+写移除，NO00012 常数）对 widen = Σ ch_w×(ops_B×K_OP+1)（补边引入的额外点火上界），利润>0 才选。安全性与利润解耦：安全规则全部静态（与 NO00014 同源），动态数据只做定价，语义门与回退预算兜底定价误差。该方向是 NO00012 M-econ 排序的后续第一候选（"profit>0 选择性子集需动态 widen 控制"），本节点用补边（不动 op、不动 partition 树）而不是迁移（移 op、改 partition 隶属）兑现——实现面与 NO00014 完全同构（只改 schedule fanout 表），迁移变体留作后续节点。
- **基线测量（配置未变，复用归档值，不重跑）**：
  - GrhSIM-IR 当前最佳：Host **52.757 s**（NO00014，3 次有效均值，SD 0.209 s）；端点 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`。
  - gsim+PGO 锚点：Host **27.376 s**（SD 0.065 s）；差距 **1.927×（~25.4 s）**。
  - 动态聚合（NO00014 dyn 归档）：boundary 检测写 **213,863.4/cycle**（对 gsim 87,965 仍 2.43×）、受监测行 594,153。
  - 指令归因（NO00014 生产构建 perfstat）：总 **3,968,258.2 instr/cycle**。
- **输入核对**（sha256，与 NO00001–NO00014 相同，输入未变）：
  - `testcase/xiangshan/ready-to-run/coremark-2-iteration.bin` = `c764afb8…83e8e`
  - `testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so` = `094c1c4…ff9e`
- **代码状态核对**：wolvrix `32be521`（工作区干净）；根仓库 `c1259a0`（NO00014 提交）；xiangshan/reference 子模块不动。冻结面（GRH IR、GRH 已有 pass、XiangShan 与测试源码）零改动；改动限 GrhSIM-IR 后端 schedule 层（goal 文档允许修改 GrhSIM-IR 语义/分区/调度；机制为依赖特征触发的 IR 层调度变换，非单纯 emit 形态替换，符合 2026-09-25 用户约束）。
- **资源配置**：与 NO00001–NO00014 一致：`XS_EMU_CPU=2`、`XS_EMU_THREADS=1`、`XS_NUM_CORES=1`、`XS_SIM_MAX_CYCLE=100000`、waveform/commit/RAM trace 全关；编译 `VM_BUILD_JOBS=32`；测量时机器空载；逐次 `posix_fadvise(DONTNEED)` 驱页缓存。
- **计时边界与止损线**：
  - SV→C++ 生成 <1800 s（NO00014 同流程 795.46 s 量级）；C++ 编译（PGO 三阶段）<1800 s（NO00014 同流程 678.98 s 量级）；超限记 `TIMEOUT_KILLED`。
  - 生产仿真：比较值预选为 NO00014 归档均值 **52.757 s**，运行上限 **1.5× = 79.14 s**，超时记 `REGRESSION_KILLED`；动态统计诊断运行上限 300 s。
  - 等价性：ir 侧端点四字段精确匹配 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c` 且 DIFFTEST 无 mismatch，否则 `INVALID`（按实现瑕疵处理）。

## 假设提出（HYPOTHESIS）

- **假设**：NO00014 普查最大拒绝桶 operand_not_covering（496,396 值）中存在一个**补边去监测**子类——v 的消费单元 B 缺失 v 生产 op X 的部分非常量操作数 w 的激活边，但每条缺失边 (B,w) 都可**补上**（w 是受监测 boundary 值、其 fanout 行已激活 X 所在单元 A、w 非 pinned 非 event-gate）；补边后"任何 w 变化 ⇒ 同轮激活 A（重算 X）与 B（拓扑序 A<B 读到新鲜 v）"成立，与 NO00014 逐字同源的新鲜性证明闭合，v 的检测/发布随即冗余可删。代价是 widen：w 变化但 v 结果不变时 B 多火一轮（纯计算单元重火幂等、输出不变、无下游传播，语义不可观察）。**安全规则全静态**（与 NO00014 同源，依赖/位宽/读写属性触发）；**w 的热度（ch_w）不可静态知**，故利润定价用同负载 dyn profile（PGO 式三阶段方法论向 IR pass 的扩展：安全变换集合静态决定，profile 只在安全集合内定价选择）。
- **创新点**：① 本分支首个**补边机制**——向 compute fanout 表增加激活边（恢复 gsim 原生存在的"操作数变化 ⇒ 消费者激活"依赖边；NO00013 移 op、NO00014 删行，本机制加边后删行）；② 首个 **profile 定价的 IR 层变换**：普查实测证明纯静态选择在机制上不可能——全集（64,118 合格值）静态无差别选择的 widen 上界高达 **9,270,905 instr/cycle**（= 总指令的 2.3 倍，被少数热 w 主导），任何不含热度的静态规则无法约束 widen；安全（静态）与定价（动态）解耦是本机制成立的唯一方式；③ 定价用**整数缩放闭式**（save×16 对 Σ ch_w×(ops_B×13+4)，K_OP=3.25=13/4 精确可表），C++ pass 与 Python 普查在同一整数式上判定 profit>0，排除浮点求和序差异导致的集合漂移。
- **瓶颈证据（立项普查：`scripts/grhsim_edgecomplete_census.py` 对 NO00014 生产 checkpoint + NO00014 dyn run1 vchg 归档，ptmp/no00015_edge_complete_20260925/analysis/）**：
  - boundary 值 799,651、受监测行 593,741（NO00014 去监测后）；**补边可行候选 80,316 值**，候选需补边 303,460 条；
  - 拒绝桶：operand_not_boundary 281,503（操作数非 boundary，无法传边）、port_arm 138,308、producer_not_activated 124,314（w 的行不激活 A，补边后 v 失新鲜性保证）、producer_kind 83,339、no_fanout_row 59,066、side_effect_unit 16,952、width 8,589、edge_row_missing 6,824、event_gate 417+19、pinned 4；
  - **动态定价（K_DETECT=3、K_STORE=1、K_SET=1、K_OP=3.25，NO00012/13/14 常数；整数缩放判定 profit×4>0）**：profit>0 选中 38,707 值，**选中集上级联不动点修剪 5,030 个链内候选**（被选中值的非常量操作数不得同被选中——合格但未选中的操作数保留其行，是合法的补边来源；注意普查首版把不动点错误地跑在合格集上，多剪 16,198 个本可安全移除的候选，已修正为选中集语义）后 **33,677 值 / 补边 117,054 条**（其中 109,947 条 ch_w=0 冷边，widen 集中于 7,107 条温边）；检测写移除 **10,441.76/cycle**（精确整数闭式 1,044,186,826/run ÷ 100,001）；save **41,767.1 instr/cycle**，widen 上界 **1,816.6 instr/cycle**（= save 的 4.4%，同轮共激活塌缩使真实 widen 更小），**净利 39,950.5 instr/cycle ≈ M-net 基线的 1.007%**；
  - 对照：静态全集 save 101,562.5 对 widen 12,878,202.7（净利 **−12.78M instr/cycle**）——profit≤0 的 41,609 个候选独自贡献 −12.82M；定价选择不是优化偏好而是机制必需；
  - 选中集构成（Top：kind×宽度×冷度）：1-bit eq 三档（[0.1%,1%) 4,014 值 profit 12,086.6；零变化 4,995 值 7,083.1；(0,0.1%) 2,039 值 4,770.2）、1-bit sliceDynamic 零变化 5,631 值 3,294.9、1-bit and 零变化 3,078 值 1,238.5 等，详见 summary.md。
- **微观指标与总目标的定量关系**：
  - **M-net**（锚定）= 总 instr/cycle（perfstat，确定性 spread ≤2.3e-6，NO00013 校准）：基线 3,968,258.2。净利闭式 −39,950.5 ⇒ −1.007%；未建模正向项（NO00014 实测 measured/model = 1.42 倍）：被删行的发布路径（组臂分支 + 目标 pending 置位，NO00010 组级分支化后仍按行计费）随行删除消失；负向项 widen ≤1,816.6 已计入净利。预期实测 M-net −1.0%~−1.5% ⇒ Host −~0.7%~−1.1%（CPI 中性假设；NO00010 教训：新增分支可能抬 branch-miss，本机制不新增分支——补边只增长既有发布循环的迭代、删行走既有静默退化路径）。
  - **M-shrink**（辅，确定性整数计数）= 动态 boundary 检测写/cycle：基线 213,863.38；移除闭式精确 −10,441.76 ⇒ 203,421.62 + widen 侧新增写（有界，见语义门 ⅲ）。
- **预注册**：
  - **测量方法与运行秩序**：①聚焦测试（`test_grhsim_cpu_emit`/`test_grhsim_cpu_schedule` 等 + 普查脚本单测 + hdlbits 抽样）→ ②门关一致性（默认管线无本 pass，reemit 对 NO00014 归档生产模型逐字节）→ ③生产全流程 gen（migrate + demonitor + edge-completion 三门开，profile 自 NO00014 dyn run1 导出）+ 模型语义中性检查（checkpoint strings/types/values/operations/partition 段对 NO00014 归档逐字节，仅 schedule 段 fanout 行与新字段变化）→ ④dyn reemit（三门开 + dynamic-stats）+ dyn 构建 + 2×100k dyn 运行（端点/确定性/sn/kind/移除与补边集闭式门）→ ⑤PGO 生产构建 → ⑥perfstat 总指令（M-net，新旧同窗口各 3 次）→ ⑦3+3 交替 Host 复测（逐次 posix_fadvise，`taskset -c 2`）。
  - **改善门槛（锚定）**：M-net ≤ **3,944,448.7/cycle**（降 ≥0.6% = 点估计的 61%；低于此值说明逐写常数或 widen 上界在机制层面失真）。
  - **辅助门槛**：M-shrink 移除量闭式精确吻合（Σwr 移除 = 1,044,186,826/run，误差 0）；widen 侧新增检测写 ≤ Σ_B W_B×|B 的受监测输出数|（逐值有界，W_B = 补入 B 的各边 ch_w 之和）。
  - **语义门**：ⅰ 端点四字段精确 + difftest 干净（dyn ×2 与生产 ×6 全部）；ⅱ dyn sn 行：**未获补边的单元** act/body fires ≤ 基线逐键（收缩允许），**获补边的单元 B** act/body 增量 ≤ W_B（同轮共激活塌缩 ⇒ 实际 ≤ 上界）；ⅲ dyn kind/vchg 行：逐键 ch ≤ 基线（补边单元的额外点火输入不变 ⇒ 输出不变 ⇒ ch 不增），wr 对非补边单元产出值 ≤ 基线，对补边单元产出值增量 ≤ W_B；ⅳ 模型语义中性：checkpoint strings/types/values/operations/partition 段对 NO00014 归档逐字节一致（仅 schedule 段 fanout 行 + 新标志/选择集字段变化）；ⅴ hdlbits 161/162（DUT=105 预存失败）；ⅵ 门关：默认管线（无本 pass）reemit 对 NO00014 归档模型逐字节一致；ⅶ 闭式对账：pass 实际移除值集与补边集 == 普查 selected.json（整数定价逐点一致，零误差），无新 boundary 值、无 slot 翻转、补边仅出现在受监测 w 的行且目标为静态合格单元。
  - **构建门槛**：生成 <1800 s、编译（PGO 三阶段合计）<1800 s。
  - **回退预算**：Host 新构建均值 ≤ **53.81 s**（+2%）；改善时以秩次判据登记显著性。
  - **证伪标准**：M-net 降 <0.6% 且闭式门全过 → "逐写常数（K_DETECT+K_STORE=4）在该代码形态下成立"或"widen 上界可控"命题机制性证伪 → REJECTED 并登记机制证伪表；widen 实际超预注册上界、语义门 ⅱ–ⅶ 或构建门槛失败 → 实现瑕疵，回 IMPLEMENTED 修正后重测（同一节点内）。
  - **验收**：锚定门 + 辅助门 + 语义门全过 + 构建门槛通过 + Host 在回退预算内。

- **预注册修订（2026-09-26，实现瑕疵修正后、任何修正版测量之前登记）**：结果测试首轮 dyn 运行触发 difftest 分歧（INVALID），二分定位为合格性规则的机制性漏洞（详见代码实施节修正记录）：emit 的 `planReadAliases` 把合格 `core.state.read` 结果别名到状态槽位，其 fanout 行是死代码，且 vchg 计数器在别名结果上不发射（wr=ch=0，伪冷）——补边加到别名操作数 w 的死行上运行时零效果，新鲜性证明断裂；同时原普查给这些边的 widen 定价为 0（**原 −0.99% 点估计中含 14,391 个伪冷定价候选，作废**）。修正规则：missing edge 的 w 为发射别名读或 DPI 产生值（DPI publish 站点无 vchg 计数，widen 不可定价；本设计实测 0 例，防御性拒绝）时拒绝该候选。修正后普查（同一 NO00014 归档 + 同一 dyn run1 profile，规则镜像逐点一致）：合格候选 80,316→**63,607**（operand_aliased 拒绝 16,709、operand_dpi_blind 0），选中 33,677→**22,244** 值、补边 117,054→**59,761** 条（51,525 冷边）、移除检测写 10,441.76→**3,994.58/cycle**（闭式精确 399,462,112/run）、save **15,978.3**、widen 上界 **1,784.8**（= save 的 11.2%）、净利 **14,193.5 instr/cycle = M-net 基线的 −0.3577%**。
  - **锚定阈值修订**：M-net ≤ **3,959,656.9/cycle**（降 ≥0.217%，= 修正点估计的 61%，沿用原阈值推导比率；低于此值说明逐写常数或 widen 上界在机制层面失真）。修订发生在修正版任何测量之前，由正确性根因驱动，非测量结果驱动。
  - **辅助门槛修订**：M-shrink 移除量闭式精确吻合值改为 Σwr 移除 = **399,462,112/run**（误差 0）；widen 侧新增检测写上界定义不变（逐值 W_B = 补入 B 的各边 ch_w 之和）。
  - 语义门、构建门槛、回退预算、证伪标准（机制层面）不变。

## 代码实施（IMPLEMENTED）

- **改动面（语义约束）**：全部改动限于 GrhSIM-IR 后端 schedule 层 + 流程接线；冻结面（GRH IR、既有 GRH pass、XiangShan 与测试源码、发射器）零改动。partition 树、数据布局、值 slot 全部不动；computeSupernodeFanout 仅发生两类变化——选中值的行整行删除（同 NO00014 静默退化路径兑现检测消除）、受监测操作数 w 的行 activate 集按 activeId 序补入消费单元 B。
  - `wolvrix/include/grhsim/ir/model.hpp`：`CpuSchedulePlan` 新增 `demonitorEdgeCompletion` 标志 + `demonitorEdgeCompletionRemoved`（排序后的移除值集，defaulted operator== 自动纳入比较，verify 重建重放一致）。
  - `wolvrix/lib/grhsim/backend/cpu_schedule.cpp`：整数定价常数 `kEdgeCompletionSaveX4=16 / OpX4=13 / SetX4=4`（profit×4 = wr_v×16 − Σ ch_w×(ops_B×13+4)，与普查同一整数式）；`EdgeCompletionView`（pinned/portArm/rowOf/unitOps/safeMemo/sideEffectFree/activates/constantProduced/eligible——合格判定逐条镜像普查，含"kind==Supernode 且首子 kind==Node"的计算 supernode 识别）；`selectDemonitorEdgeCompletion`（合格集 → 整数定价 profit>0 → **选中集上**级联不动点修剪）；`applyDemonitorEdgeCompletion`（校验移除集 sorted-unique、逐值合格、不动点性质成立后，对补边目标行 `sortActive` 加边、删除选中行）；规则于 `buildSchedule` 内 `demonitorRedundant` 之后运行，标志与移除集随 plan 携带，verify 重建重放等式两侧一致；匿名命名空间外公开 `computeDemonitorEdgeCompletionSelection` 供 pass 取诊断计数。
  - `wolvrix/include/grhsim/backend/cpu.hpp`：`DemonitorEdgeCompletionSelection` 结构 + 函数声明。
  - `wolvrix/lib/grhsim/pass/demonitor_edge_completion.cpp`（+ 头）：`grhsim.demonitor-edge-completion`（BackendMapping）带 `--profile <path>`（扁平文本 `id wr ch`，`from_chars` 解析，id 越界报 stale profile 错），只置标志 + 移除集并 `refreshCpuSchedule` 重建；幂等（已置标志报 already applied）。
  - `wolvrix/lib/grhsim/io/json.cpp`：schedule 可选尾字段——`demonitorRedundant || demonitorEdgeCompletion` 时写去监测标志，`demonitorEdgeCompletion` 时追加写移除集 id 数组；读取端两个顺序 `if (comma())`，旧归档 checkpoint 兼容（门关 checkpoint 与 NO00014 格式逐字节一致）。
  - `wolvrix/lib/grhsim/pass/pass.cpp`、`wolvrix/CMakeLists.txt`：注册与编译接线。
  - 流程接线：`scripts/wolvrix_xs_grhsim_ir.py` / `scripts/reemit_grhsim_ir.py` 的 `--demonitor-edge-completion-profile`（追加于 demonitor-redundant 之后）；`Makefile` 的 `XS_WOLF_GRHSIM_IR_EDGECOMPLETE_PROFILE`（abspath 传参）/ `GRHSIM_REEMIT_EDGECOMPLETE_PROFILE`；新目标 `analyze_grhsim_edgecomplete_census` / `test_grhsim_edgecomplete_census` / `analyze_grhsim_edgecomplete` / `test_grhsim_edgecomplete_gates`。
  - 分析设施：`scripts/grhsim_edgecomplete_census.py`（全集/静态子集定价、整数缩放判定、`select()` 为权威实现供门脚本进程内复用、`--profile-output` 导出 vchg profile；单测 12）；`scripts/grhsim_edgecomplete_gates.py`（预注册语义门 1–7；单测 10）。
- **实施期修正（已验）**：门脚本首版按 NO00014 合成模型的 schedule 布局读索引，真实 checkpoint 中 quiescenceProjection 的 bits（int）与 words（list）是两个独立元素（[7]/[8]），去监测标志在 [9]、移除集在 [10]；修正门脚本与合成模型后冒烟门全过。
- **与父节点差异**：wolvrix `32be521` + 上述 8 文件（2 新 6 改）；根仓库 + 普查/门/单测 4 脚本 + 2 流程脚本改动 + Makefile 变量与 4 目标。
- **聚焦测试**：`make build` 增量通过；`make test_grhsim_cpu_emit test_grhsim_cpu_schedule test_grhsim_cpu_mapping` 全过；普查/门脚本单测 12+10 全过；**门关 neutral reemit 对 NO00014 归档生产模型逐字节一致（NEUTRAL-IDENTICAL，排除 *.o/*.a）**。
- **冒烟验证（flow-smoke reemit，三门开）**：pass 诊断 `rows=33677 remaining=560476 eligible=80316 profitable=38707 cascade_trimmed=5030 added_edges=117054 save_x4=16706989216 widen_x4=726640522` 与普查**逐项一致**；冒烟门 1–3（old=NO00014 归档生产 checkpoint，baseline-run=NO00014 dyn run1）PASS——移除行 33,677、拓宽操作数行 16,068、唯一补边 (w,B) 46,298 条、剩余行 560,476，全部闭式吻合。

### 修正记录（2026-09-26，实现瑕疵：正确性门失败 → 定位 → 修正 → 重测）

- **失败现象**：首轮结果测试中 dyn run1 触发 difftest 分歧（instr 16，pc=0x80000014，mstatus/mepc/mtval/mcause 不符，mcause=3），cycle 8,261 abort；生产 PGO 构建复测同一签名。判定为 INVALID，按 goal 文档默认按实现瑕疵处理，回本阶段修正。
- **二分定位**（`bisect_queue.sh`，源 checkpoint = NO00004 flow + migrate+demonitor+edgecomplete+dynamic-stats，20k cycles，逐配置 reemit/build/run；全程记录于 `ptmp/no00015_edge_complete_20260925/debug_journal.md` 与各 `bisect-*/verdict.txt`）：14 个配置、3 个独立失败签名（instr16 断点、instr176 IntRegFile "two or more writePorts write same addr" 断言、instr94/83 pc=0x0）；关键证据：**cold-only 配置（全部补边 ch_w=0）仍按 instr16 分歧**——补边动态上零触发，理论应与基线等价，证明存在未建模机制。
- **根因**（emit 语义复查 + 精确判定镜像验证）：emit 的 `planReadAliases`（`cpu_emit.cpp:473-512`）把满足条件的 `core.state.read` 结果直接别名到状态槽位（状态在 quiescence 投影、无 compute 单元外/event-gate 读者、类型与状态一致），**该值的 computeSupernodeFanout 行仍是计划中的活行但发射为死代码**（`cpu_emit.cpp:4356` 提前 return、`:4098` 排除出 ChangedGroup），运行时消费者激活改由状态 commit-publish 的 `aliasConsumers_` 路径承担；且 vchg 计数器只在 compute 检测站点发射，别名值 wr=ch=0（伪冷）。原合格性规则只查"w 的行在表中激活 A"，不查该行运行时是否真实发射——补边加到别名 w 的死行上零效果，状态变化只激活 A（重算 v，v 行已删静默退化），B 永不激活读陈旧 v。NO00014 不受影响的原因：全覆盖要求 B∈activate(w) ⟺ B 直接读 w ⟹ B∈aliasConsumers，偶发健全。镜像验证（`analysis/alias_mechanism_check.py`）：精确别名判定下选中集 33,677 中 **14,391** 个候选带别名缺失边；全部 FAIL 配置富含别名候选（onlyA 10,328/11,113、fixAB 3,811/21,124、L2h1 237/258），PASS 的 only8129 为 0——单一根因解释所有签名（onlyB 1,440 值含 252 别名候选但 20k 窗 PASS：那些别名源状态在窗口内未变化/未传播至可观察态，非独立洞类；classB "init fixup" 由 emit 语义复查确认不存在——compute 值无 init fixup 路径）。
- **修正（规则镜面同步，C++/Python 同一判定）**：missing edge 的补边源 w 满足以下任一即拒绝该候选：① w 为发射别名读（`operand_aliased`，镜像 `planReadAliases` 全谓词：compute 单元归属 = numaNodes[0].cores[0] 下 execution==ActivityDrivenCompute 任务的三层 walk、snapshot = compute 外 op 操作数 + event-gate 值、quiescence 投影位、值/状态 TypeId 相等）；② w 为 `core.dpi.call` 产生值（`operand_dpi_blind`，DPI publish 站点无 vchg 计数、widen 不可定价；本设计实测 0 例，防御性）。已覆盖的边（B 直接读 w）不受影响：别名消费者经状态 publish 激活的路径真实存在。改动文件：`wolvrix/lib/grhsim/backend/cpu_schedule.cpp`（EdgeCompletionView 增 aliased/dpiProduced 位图 + eligible() missing-edge 拒绝）、`scripts/grhsim_demonitor_census.py`（view 增 aliased_read_values/dpi_produced 镜像计算）、`scripts/grhsim_edgecomplete_census.py`（candidates() 拒绝路径 + docstring）、`scripts/test_grhsim_edgecomplete_census.py`（+3 用例：别名缺失边拒绝/别名已覆盖放行/DPI 盲拒绝）。
- **修正后聚焦测试**：普查/门脚本单测 15+10 全过，NO00014 脚本单测 18 全过（view 扩展回归）；`make build` 增量通过；`test_grhsim_cpu_emit` / `test_grhsim_cpu_schedule` / `test_grhsim_cpu_mapping` 全过。
- **修正后普查闭式**（同一 NO00014 归档、同一 dyn run1 profile）：合格 63,607（operand_aliased 拒绝 16,709），选中 **22,244** 值（pre-fixpoint 24,303、级联修剪 2,059）、补边 **59,761** 条（51,525 冷边）、移除检测写 **3,994.58/cycle**（精确 399,462,112/run）、save **15,978.3** / widen 上界 **1,784.8** / 净利 **14,193.5 instr/cycle（−0.3577% M-net）**。锚定阈值按预注册比率修订（见假设提出节）。
- **20k 决定性验证**：修正 pass + 修正 profile 的 dyn reemit/构建/20k difftest 运行（flow-bisect-fixalias）：pass 诊断 `rows=22244 remaining=571909 eligible=63607 profitable=24303 cascade_trimmed=2059 added_edges=59761 save_x4=6391393792 widen_x4=713923859` 与修正普查**逐项一致**；20k 运行 rc=0、`instrCnt=14,121、cycleCnt=19,996`、guest 20,001、difftest 干净——与基线 20k 端点逐字段相同，别名根因判定成立。

## 结果测试（TESTED）

> 本轮为**修正后重测**（首轮 INVALID → 根因修正 → 预注册修订 → 全管线重跑，见代码实施节修正记录）。管线脚本 `tested_pipeline.sh` / `tested_pipeline_s2.sh`，全部产物在 `ptmp/no00015_edge_complete_20260925/`。

### 构建门槛（migrate + demonitor + edge-completion 三门开，生产全流程）

| 区间 | 墙钟 | 门槛 | 结果 |
|---|---|---|---|
| SV→C++ 生成（`xs_wolf_grhsim_ir` + `XS_WOLF_GRHSIM_IR_MIGRATE_BOUNDARY_OPS=1` + `XS_WOLF_GRHSIM_IR_DEMONITOR_REDUNDANT=1` + `XS_WOLF_GRHSIM_IR_EDGECOMPLETE_PROFILE`，profile 自 NO00014 dyn run1 导出） | **793.17 s**（exit 0） | <1800 s | PASS |
| C++ 编译 PGO 三阶段（`xs_wolf_grhsim_ir_emu_pgo`，-j32） | **651.58 s**（exit 0，profile-use 链接完成） | <1800 s | PASS |
| dyn reemit（三门开 + dynamic-stats）+ dyn 构建 | 68.92 s + 235.01 s | 诊断口径，不占门槛 | — |

pass 诊断 `rows=22244 remaining=571909 eligible=63607 profitable=24303 cascade_trimmed=2059 added_edges=59761 save_x4=6391393792 widen_x4=713923859` 与修正后普查**逐项一致**（闭式门 3 一部分）。生产门 1–3 对 NO00014 归档 PASS：移除行 **22,244**、拓宽操作数行 13,362、唯一补边 **32,978** 条、剩余行 **571,909**。

### 语义门（全部通过）

- **ⅰ 端点精确 + difftest 干净**：dyn run1/run2、perfstat 新旧 6 次、bench 6 次共 14 次运行端点四字段全部精确 = `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`；difftest 干净（perfstat 两侧 `nodiff` pass、bench `--expected-endpoint` 强制校验 exit 0）。
- **ⅱ sn 行（dyn run1 对 NO00014 dyn run1 基线）**：31,612 单元逐键比较全过——获补边单元（bound>0）2,038 个 act/body 增量全部 ≤ W_B 上界（同轮共激活塌缩使实际远低于上界）；473 个单元严格收缩（预期副产物：移除行的发布轮消失）；无任一键超限。
- **ⅲ kind/vchg 行逐键有界**：692,107 值逐键比较全过——移除集 22,244 值 wr 全为 0（检测站点已删）；补边单元产出值 27,931 个 wr/ch 增量全部 ≤ 逐值上界；非补边值逐键 ≤ 基线。
- **ⅳ 模型语义中性**：生产 checkpoint 的 strings/types/values/operations 段及 partition 树对 NO00014 归档**逐字节一致**（gates-prod 门 1–2 PASS，仅 schedule 段 fanout 行 + 标志/移除集字段变化）；dyn 侧同门 PASS。
- **ⅴ hdlbits**（GrhSIM-IR 管线 `run_all_hdlbits_grhsim_ir_tests`，与 NO00009–NO00014 同口径）：**161/162**——DUT 001–104 全过，DUT=105 命中预存失败（`used-bits dangling value 101 produced by core.compute.sliceStatic consumed by op 105 core.compute.concat (originalOps=124) (grhsim.used-bits)`，错误文本与预存逐项一致），DUT 106–162 全过（57/57）。附带登记（与本节点无关的预存环境事实，同 NO00014）：Verilator 流 `run_all_hdlbits_tests` 在 DUT=042 TB 编译失败（`VlWide<4>`→`const uint32_t*` 无隐式转换，Verilator 5.051 头文件预存不兼容），非本节点回归口径。
- **ⅵ 门关中性**：默认管线（无本 pass）reemit 对 NO00014 归档生产模型 **NEUTRAL-IDENTICAL**（model diff rc=0、checkpoint 排除 *.o/*.a 逐字节一致；reemit 须带 `GRHSIM_REEMIT_COMMIT_COMPACT_WALK=1 GRHSIM_REEMIT_COMMIT_MEM_WALK=1` 与生产 emit 对齐，已固化进流程脚本）。
- **ⅶ 闭式对账**：pass 移除值集 **== 修正普查 selected 22,244 逐一吻合**（整数定价逐点一致，零误差）；模型段/分区中性门蕴含无新 boundary 值、无 slot 翻转；补边仅出现在受监测 w 的行且目标为静态合格单元（门 3 通过）。

### 锚定微观指标：M-net —— PASS（确定性口径）

perfstat 总 instr/cycle（`analyze_grhsim_native_work`，新旧同窗口各 3 次）：

| 侧 | 3 次 instructions | 均值 instr/cycle | 端点/difftest |
|---|---|---|---|
| 新（NO00015 PGO 二进制） | 394,998,430,880 / 394,998,662,504 / 394,997,743,762 | **3,949,943.3**（spread 2.3e-6） | 四字段精确、difftest 干净 ×3 |
| 旧（NO00014 归档二进制，同窗口复测） | 396,828,988,810 / 396,828,969,681 / 396,828,972,626 | 3,968,250.1（spread 4.8e-8） | 四字段精确、difftest 干净 ×3 |

- **Δ = −18,306.8/cycle = −0.461%** ≤ **3,959,656.9** 修订门（降 ≥0.217%），**PASS**。旧侧同窗口复测对 NO00014 归档基线 3,968,258.2 漂移仅 8.1/cycle，口径确定性确认。
- 实现率 = 实测 −18,306.8 / 修正闭式点估计 −14,193.5 = **1.29×**（同 NO00013 1.42×、NO00014 1.42× 方向：利润模型对静态安全内核为保守下界——被删行的发布路径组臂分支与 pending 置位、473 个单元冗余次轮重火移除的 dynOps 副降未建模）。
- CPI 0.6625 vs 0.6619（+0.08%，中性假设成立）；branch-misses −0.20%（本机制不新增分支，与预注册论证一致）。

### 辅助微观指标：M-shrink —— PASS（确定性计数闭式精确）

| 指标 | 基线（NO00014 dyn） | 新构建（dyn run1/run2 逐字节一致） | Δ | 判定 |
|---|---|---|---|---|
| M-shrink = Σwr/guest-cycle | 213,863.38/cycle（21,386,551,923/100,001） | **209,872.37/cycle**（20,987,446,923/100,001） | **−3,991.01/cycle = −1.866%** | **PASS** |

- 移除量闭式**零误差**：removed = **399,462,112/run**（3,994.58/cycle）与修订普查逐项一致；widen 侧新增检测写 added_writes = 357,112/run（3.57/cycle）≤ 闭式上界 4,750,570（实际为上界的 7.5%，同轮共激活塌缩）。
- 残余受监测集 209,872 wr/cycle 对 gsim 87,965 仍 **2.39×**。

### 最终性能：3+3 交替复测（bench 脚本 preregister 顺序 old1,new1,old2,new2,old3,new3）

逐次 posix_fadvise 驱页缓存、`taskset -c 2`、上限 79.14 s（1.5×52.757），全部 6 次 VALID、端点四字段精确。

| 侧 | 3 次 Host s | 均值 | SD |
|---|---|---|---|
| 旧（NO00014 归档二进制） | 52.542 / 53.188 / 53.519 | 53.083 | 0.497 |
| 新（NO00015 PGO 二进制） | 52.690 / 52.663 / 52.664 | **52.672** | 0.015 |

- **Δ = −0.411 s（−0.774% 同窗口）**；Mann-Whitney 单侧精确 **p=0.35**、秩次判据 FAIL（old run1 52.542 优于全部新运行）——按预登记**"不判显著、如实登记"**。
- 对 NO00014 归档均值 52.757 s：**−0.161%**；对 gsim+PGO 锚点 27.376 s = **1.924×**（剩余差距 ~25.3 s）。
- 回退预算 Host ≤53.81 s：52.672 s，预算内（改善方向）。

### 判定

**ACCEPTED**。预注册验收五项全满足：锚定 M-net 达修订门（**−0.461% ≥ 0.217%**，确定性口径，实现率 1.29×）；辅助 M-shrink 闭式**零误差**（移除 399,462,112/run，widen 新增 357,112 ≤ 上界 4,750,570）；语义门 ⅰ–Ⅶ 全过（14 次运行端点精确 + difftest 干净、sn/vchg 逐键有界、模型语义中性逐字节、hdlbits 161/162、门关 NEUTRAL-IDENTICAL、移除/补边集与普查逐点吻合）；构建门槛（793.17 s / 651.58 s）通过；Host 52.672 s 在回退预算内。

- **机制知识（正）**：① 首个**补边去监测**节点兑现——为覆盖缺失的操作数补激活边（32,978 条唯一补边，86% 为冷边）后删除 22,244 值的冗余检测行，与 NO00014 同源新鲜性证明闭合；② 首个 **profile 定价的 IR 层变换**成立——安全规则全静态、定价动态（整数缩放闭式 C++/Python 同一判定），实测 −0.461% 对点估计 −0.358%（1.29×，方向与历次一致）；widen 实测新增写仅为上界的 7.5%（同轮共激活塌缩），"widen 上界可控"命题成立；③ 利润模型在含 widen 代价的机制下仍为保守下界。
- **机制知识（负/边界）**：emit `planReadAliases` 别名值的 compute fanout 行是死代码且 vchg 计数器不发射（伪冷）——别名操作数候选（16,709 值）必须拒绝，否则补边零效果、新鲜性断裂（首轮 INVALID 根因，已固化为合格性规则）；DPI 产生值无 vchg 计数站点，widen 不可定价，防御性拒绝（实测 0 例）；残余受监测集对 gsim 仍 2.39×，未覆盖拒绝桶（operand_not_boundary 281,503、producer_not_activated 124,314 等）为后续节点空间。
- **利润模型校准**：M-net 实测 −18.3K/cycle vs 修正估计 −14.2K/cycle（1.29×）；Host 同窗口 −0.774% ≈ instr −0.461% × CPI 中性闭合（branch-misses −0.20% 同向）。
- **设施留存**：`grhsim.demonitor-edge-completion` pass（`buildSchedule` 内规则，verify 重建重放一致）+ `--demonitor-edge-completion-profile` / `GRHSIM_REEMIT_EDGECOMPLETE_PROFILE` / `XS_WOLF_GRHSIM_IR_EDGECOMPLETE_PROFILE` 门控（门关 = NO00014 管线逐字节一致，NEUTRAL-IDENTICAL 已验证）+ `grhsim_edgecomplete_census.py` / `grhsim_edgecomplete_gates.py`（单测 15+10）。
- **当前最佳指针更新**：新构建 Host 均值 **52.672 s** 优于 NO00014 归档 52.757 s（−0.161%）与同窗口复测 53.083 s（−0.774%，p=0.35 不显著、预登记如实登记），且确定性工作计数严格下降（M-net −0.461%、M-shrink −1.866%）——按索引"最终性能最优的节点"规则指针移至 **NO00015**（如实登记：Host 差低于 n=3+3 秩次分辨底，指针依据为均值最优 + 确定性计数严格收缩）。
