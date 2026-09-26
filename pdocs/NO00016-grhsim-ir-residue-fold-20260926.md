# NO00016: 转换伪影残余折叠——canonicalize 后位 pass 再引入的恒等/常量 op 消除（locals 域）

| 字段 | 值 |
|---|---|
| 父节点 | NO00015（当前最佳） |
| 角色 | 优化 |
| 状态 | REJECTED（机制性错误；四阶段走完，门 1–7 全过，锚定门 FAIL） |
| 锚定指标 | **M-net** = 总 instr/cycle（perfstat 确定性口径；基线 **3,949,943.3/cycle**，NO00015 同窗口 3 次均值） |
| 指标阈值 | M-net ≤ **3,940,463.4/cycle**（降 ≥0.24% ≈ 点估计 −0.36% 的 2/3） |
| 回退预算 | Host ≤ +2%（≤53.73 s）；等价/构建门槛不放宽 |
| RUN_ID | no00016_residue_fold_20260926 |
| 工作区 | ptmp/no00016_identity_fold_20260926/ |

## 基础选定（BASELINE）

- **父节点**：NO00015（当前最佳指针，GrhSIM-IR PGO 构建 Host 52.672 s，wolvrix `61b092e` + 根仓库 NO00015 提交 `4e4e40f`）。当前工作区两仓库干净、正对 NO00015 终态，以其为实施基线，无迂回。
- **立项动机（为什么是这个方向）**：用户最新提示（2026-09-25）要求从 GRHSIM IR 层面消除 Firtool/GRH IR 两重转换破坏的形态差异。NO00008 因子表把 2.0× 指令差距闭合于每单位工作指令密度（8.54×），其中 dynOps 两个乘数（粒度 NO00006、输入精度 NO00007）与值承载/融合两条密度路线（NO00009/NO00011）均已证伪；尚**未**被检验的分量是"转换伪影残余 op"——canonicalize-compute 之后运行的语义 pass（bitwise-muxes/mux-chain-fold/used-bits）会再引入恒等/常量 op，而 canonicalize 自身缺少 slice-of-const、not-not、自比较、bitSelect 恒等等规则。这类 op 是**语义空操作**（恒等）或**编译期可求值**（常量切片），其消除直接减少 dynOps（真实工作量），不触碰激活结构/调度/值承载，与全部证伪条目正交。本节点立项普查（下节）实测残余 523.3M dyn execs/run ≈ dyn 总量的 0.567%。
- **基线测量（配置未变，复用归档值，不重跑）**：
  - GrhSIM-IR 当前最佳：Host **52.672 s**（NO00015，3 次有效均值，SD 0.015 s）；端点 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`。
  - gsim+PGO 锚点：Host **27.376 s**（SD 0.065 s）；差距 **1.924×（~25.3 s）**。
  - 指令归因（NO00015 生产构建 perfstat）：总 **3,949,943.3 instr/cycle**（compute 80.35% / commit 11.61% / evaluator 3.38% / infra 2.61%）。
  - 动态聚合（NO00015 dyn 归档）：boundary 检测写 **209,872.37/cycle**；compute op 动态执行总量（本节点普查口径，sn body × unit ops 静态连接）**92,212.3M/run（922,113/cycle）**。
- **输入核对**（sha256，与 NO00001–NO00015 相同，输入未变）：
  - `testcase/xiangshan/ready-to-run/coremark-2-iteration.bin` = `c764afb8…83e8e`
  - `testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so` = `094c1c4…ff9e`
- **代码状态核对**：wolvrix `61b092e`（工作区干净）；根仓库 `4e4e40f`（NO00015 提交）；xiangshan/reference 子模块不动。冻结面（GRH IR、GRH 已有 pass、XiangShan 与测试源码）零改动；改动限 GrhSIM-IR 后端语义 pass 与 XS 流程 pass 序（goal 文档允许修改 GrhSIM-IR 语义；机制为位宽/语义恒等特征触发的 IR 层替换，非 emit 形态替换，符合 2026-09-25 用户约束）。
- **既有设施核对（关键）**：`grhsim.canonicalize-compute` 已在 XS 流程中运行两次（`scripts/wolvrix_xs_grhsim_ir.py:41,53`：reg-to-mem 后与 pack-bit-registers 后），其 simplify() 覆盖 mux 恒等/常量条件、and/or(x,x)、add/sub/xor/mul/div/and/or/logic* 中性-吸收元；**不覆盖** sliceStatic-of-const、not(not)、自比较、bitSelect 恒等、单元素 concat；其 assign 折叠要求 TypeId 完全相同。第二次 canonicalize 之后仍运行 bitwise-muxes、mux-chain-fold、used-bits 三个语义 pass，残余由它们再引入（待 reemit 探针证实各类归因）。
- **emit 侧事实核对**（决定各类残余的真实成本）：常量 op 在 emit 侧免费（staticScalars_ 内联于读点，任务体内无常量物化语句——对 NO00015 生产模型 4,539 个 task 文件 grep 零命中）；assign 发射为 `grhsim_cast_u64`（载入+掩码+存储，真实指令）；sliceStatic(const) 的表达式被 clang 常量折叠但**存储仍每 fire 发生**；恒等类 op 的消费者读其 slot（载入）——折叠后消费者改读源 slot 或内联常量，消除"计算+存储+载入"全链。
- **资源配置**：与 NO00001–NO00015 一致：`XS_EMU_CPU=2`、`XS_EMU_THREADS=1`、`XS_NUM_CORES=1`、`XS_SIM_MAX_CYCLE=100000`、waveform/commit/RAM trace 全关；编译 `VM_BUILD_JOBS=32`（nproc=32）；测量时机器空载；逐次 `posix_fadvise(DONTNEED)` 驱页缓存。
- **计时边界与止损线**：
  - SV→C++ 生成 <1800 s（NO00015 同流程 793.17 s 量级）；C++ 编译（PGO 三阶段）<1800 s（NO00015 同流程 651.58 s 量级）；超限记 `TIMEOUT_KILLED`。
  - 生产仿真：比较值预选为 NO00015 归档均值 **52.672 s**，运行上限 **1.5× = 79.01 s**，超时记 `REGRESSION_KILLED`；动态统计诊断运行上限 300 s。
  - 等价性：ir 侧端点四字段精确匹配 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c` 且 DIFFTEST 无 mismatch，否则 `INVALID`（按实现瑕疵处理）。

## 假设提出（HYPOTHESIS）

- **假设**：XS 流程的语义 pass 链（reg-to-mem → canonicalize → clone-shared → bitwise-predicates → 映射 → pack-bit-registers → canonicalize → bitwise-muxes → mux-chain-fold → used-bits）中，**第二次 canonicalize 之后仍有三个语义 pass 再引入恒等/常量残余 op**，且 canonicalize 的 simplify() 缺少若干恒等类规则。这些 op 是语义空操作（恒等）或编译期可求值（常量切片），在最终映射模型中实测 **13,397 个静态残余**（下表）。把它们在 IR 层折叠（消费者重接线到源值 + 级联 DCE 不动点）可直接移除其每 fire 的"计算+存储+消费者载入"指令链，**dynOps（真实工作量）下降 0.54%**，不触碰激活结构/分区/调度/值承载/检测集——与全部机制证伪条目（NO00003/06/07/09/11）正交。
- **创新点**：① 首个针对**转换伪影残余**（canonicalize 后位 pass 再引入的恒等/常量 op）的消除节点——直接兑现用户 2026-09-25 提示的"消除 Firtool/GRH 两重转换造成的形态差异"；② 首个 **post-schedule 局部（locals 域）op 消除**机制：折叠集只含非 boundary 结果（无 fanout 行、无检测站点），分区树与调度逐字节不动，语义中性可由确定性计数器**精确**（而非有界）验证——sn/kind/vchg/totals 逐键相等是充分必要条件级的强门；③ 触发特征是位宽/语义恒等属性（全宽切片、同型 assign、常量切片、自比较、双非），非 emit 形态替换。
- **瓶颈证据（立项普查：`ptmp/no00016_identity_fold_20260926/probe_identity{,2,3,4}.py` 对 NO00015 生产 checkpoint + NO00015 dyn run1 归档，同模型连接有效）**：
  - compute op 动态执行总量 92,212.3M/run（922,113/cycle；sn body fires × unit ops 静态连接）；
  - 单级残余（探针 v3，仅恒等类）：13,397 静态 / 565.0M dyn（local 523.3M）；其中 `and` 常量掩码普查显示 neutral 类已被 canonicalize 清零（v2 全空），常量掩码占 `and` 动态量仅 0.33%——宽度规范化掩码在 IR 层无残余空间（emit 层 grhsim_cast_u64 掩码为另一议题，旧分支 NO00056 被用户判定失败，不立项）；
  - **全规则普查（探针 v4，含合格性过滤：结果 LOCAL 非 pinned 非 event-gate、消费者全部同单元纯计算、常量 CSE 命中、not_not 内层单用、assign_width 消费者符号性无关过滤、级联 DCE 不动点 uses 转移修正）**：选中 **11,881 op**，动态移除 **500,439,669/run = 5,004.4/cycle = dyn 总量的 0.543%**：
    | 类 | 静态 | 动态/run | /cycle |
    |---|---|---|---|
    | const_slice（sliceStatic(常量)→CSE 常量值） | 4,893 | 162,190,418 | 1,621.9 |
    | assign_strict（同型 assign→源） | 3,474 | 237,230,097 | 2,372.1 |
    | slice_full_strict（全宽切片→源） | 1,835 | 46,835,373 | 468.3 |
    | dce_cascade（折叠后零使用纯计算局部 op 不动点） | 1,362 | 43,022,574 | 430.2 |
    | self_eq/ne/lt（x,x 自比较→常量） | 203 | 9,705,983 | 97.1 |
    | not_not（not(not(x))→x，内层单用） | 97 | 1,335,157 | 13.4 |
    | assign_width（等宽异型 assign，消费者符号性无关） | 17 | 100,067 | 1.0 |
  - 拒绝桶：assign_type 1,504（等宽异型且消费者含符号敏感 op）、const_slice_cse_miss 79（无同型同值常量可 CSE）；
  - **归因探针**（reemit 追加第三次 canonicalize，现有规则）：assign_strict 3,568→0、const_slice 6,052→163——残余确为 canonicalize 后位 pass（used-bits 等）再引入 + 规则缺失两类叠加（canon3 的 op id 重排使逐 id diff 无效，静态计数已证实）。
  - emit 侧成本核对：常量 op 免费（staticScalars_ 内联，生产模型 4,539 个 task 文件无常量物化语句）；assign/slice 每 fire 物化"载入+cast/切片+存储"（≈3 instr）；const_slice 每 fire 仍有存储（≈1.5 instr）且消费者载入在折叠后变为免费字面量。
- **微观指标与总目标的定量关系**：
  - **M-net**（锚定）= 总 instr/cycle（perfstat 确定性口径，spread ≤2.3e-6）：基线 3,949,943.3。点估计 = 5,004.4/cycle × ~2.75 instr/op ≈ **−13.8K/cycle ≈ −0.35%**；未建模正向项（NO00013/14/15 实测实现率 1.29–1.42×：消费者载入移除、函数体缩短的 icache/分支副收益）预期把实测推向 −0.4~−0.5%；负向项（NO00009/11 的 cmov/SLP 走火类）在本机制不成立的理由：只删语句、不改值承载、不融合表达式，函数体单调变短。
  - **M-fold**（辅，确定性整数闭式）= 折叠 op 的动态执行移除量：闭式精确值 **500,439,669/run**（选中集 × 单元 body fires 静态连接；须与 pass 诊断逐点一致，零误差容限）。
- **预注册**：
  - **测量方法与运行秩序**：①聚焦测试（`test_grhsim_cpu_emit`/`test_grhsim_cpu_schedule` 等 + 普查/门脚本单测 + hdlbits 抽样）→ ②门关一致性（默认管线无本 pass，reemit 对 NO00015 归档生产模型逐字节）→ ③生产全流程 gen（migrate + demonitor + edgecomplete + fold-residue 四门开）+ 模型语义门（checkpoint strings/types/values/partition 段对 NO00015 归档逐字节；operations 段差异 == 普查重接线集；schedule 段仅尾部新字段；dataLayout 重建重放一致）→ ④dyn reemit（四门开 + dynamic-stats）+ dyn 构建 + 2×100k dyn 运行（端点/sn/kind/vchg/totals 逐键精确门 + 移除集闭式门）→ ⑤PGO 生产构建 → ⑥perfstat 总指令（M-net，新旧同窗口各 3 次）→ ⑦3+3 交替 Host 复测（逐次 posix_fadvise，`taskset -c 2`）。
  - **改善门槛（锚定）**：M-net ≤ **3,940,463.4/cycle**（降 ≥0.24% ≈ 点估计 −0.35% 的 2/3；低于此值说明"局部 op 每 fire ≈2.5–3 条指令"的成本模型在该代码形态下机制性失真）。
  - **辅助门槛**：M-fold 移除量闭式**零误差**（pass 实际折叠集 == 普查选中集 11,881 op 逐点吻合，分类计数一致；动态移除闭式 == 500,439,669/run）。
  - **语义门**：ⅰ 端点四字段精确 + difftest 干净（dyn ×2、perfstat ×6、bench ×6 全部 14 次运行）；ⅱ dyn sn/kind/vchg/totals 行对 NO00015 dyn run1 **逐键精确相等**（locals 域折叠不改变任何 boundary 写、激活、检测——不相等即实现瑕疵；dyn run1/run2 亦逐字节一致）；ⅲ 模型语义中性：checkpoint strings/types/values/partition 段对 NO00015 归档逐字节一致，operations 段差异精确等于普查重接线集（消费者操作数 v→源），schedule 段仅尾部新增折叠集字段，dataLayout 重建重放一致（NO00011 先例）；ⅳ hdlbits 161/162（DUT=105 预存失败）；ⅴ 门关：默认管线（无本 pass）reemit 对 NO00015 归档模型逐字节一致（NEUTRAL-IDENTICAL）。
  - **构建门槛**：生成 <1800 s、编译（PGO 三阶段合计）<1800 s。
  - **回退预算**：Host 新构建均值 ≤ **53.73 s**（+2%）；改善时以秩次判据（3+3，全部新优于全部旧 ⇔ 单侧 p≤0.05）登记显著性。
  - **证伪标准**：M-net 降 <0.24% 且闭式/语义门全过 → "恒等/常量残余 op 的逐 fire 物化成本 ≈2.5–3 instr"命题机制性证伪 → REJECTED 并登记机制证伪表；语义门或构建门槛失败 → 实现瑕疵，回 IMPLEMENTED 修正后重测（同一节点内）。
  - **验收**：锚定门 + 辅助门 + 语义门全过 + 构建门槛通过 + Host 在回退预算内。

## 代码实施（IMPLEMENTED）

- **改动面（语义约束）**：冻结面（GRH IR、GRH 既有 pass、XiangShan 与测试源码、reference/gsim）零改动。改动为 GrhSIM-IR 后端新 pass + emit 跳过 + 序列化 + 流程接线 + 分析设施：
  - `wolvrix/include/grhsim/pass/fold_residue.hpp` + `wolvrix/lib/grhsim/pass/fold_residue.cpp`（新）：`grhsim.fold-residue`（BackendMapping），post-schedule 运行（要求完整 CPU schedule mapping）。选择规则逐点镜像普查（`scripts/grhsim_residue_fold_census.py` 的 `select()` 为权威实现）：合格结果（LOCAL 存储、非 pinned、非 event-gate、producer 在 compute supernode 单元内、消费者全部同单元纯计算）上的七类规则——assign_strict / assign_width（等宽异型 + 消费者符号性无关）/ slice_full_strict / slice_full_width / const_slice（sliceStatic(常量)→CSE 命中既有同型同值常量，不新建常量）/ not_not（内层单用）/ self_{eq,ne,lt,gt,le,ge}（two-state，CSE 0/1 常量），随后级联 DCE 不动点（零使用纯计算 local op，常量除外；uses 统计跳过已选中 op 的 operand 读并把折叠结果的 uses 转移到源值）。应用方式：未选中消费者经 `model.replaceOperation` 重接线（链解析到最终未折叠值）；选中 op 留在模型与分区表中（op/value id 全部不变、不 compact），id 记入 `CpuSchedulePlan.foldResidueOps`，CPU 发射器跳过其语句。
  - `wolvrix/include/grhsim/ir/model.hpp`：`CpuSchedulePlan` 新增 `foldResidue` 标志 + `foldResidueOps`（排序 op id 集，defaulted operator== 纳入比较，verify 重建重放一致）。
  - `wolvrix/lib/grhsim/backend/cpu_schedule.cpp`：fold-residue 视图的 pinned/unit 识别等（复用 demonitor 同源计算）。
  - `wolvrix/lib/grhsim/backend/cpu_emit.cpp`：compute 单元 body 逐 op 发射处跳过折叠集 op（+20 行）。
  - `wolvrix/lib/grhsim/io/json.cpp`：schedule 第 12 个可选尾字段（fold 标志 + op id 数组；读取端顺序 `if (comma())`，旧归档 checkpoint 兼容——门关 checkpoint 与 NO00015 格式逐字节一致已由门 5 验证）。
  - `wolvrix/lib/grhsim/pass/pass.cpp`、`wolvrix/CMakeLists.txt`、`wolvrix/tests/grhsim/test_grhsim_ir.cpp`（`runFoldResidueTest`，143 行）。
  - 流程接线：`scripts/wolvrix_xs_grhsim_ir.py --fold-residue`（追加于 demonitor-edge-completion 之后，默认关）、`scripts/reemit_grhsim_ir.py --fold-residue`（remap 后运行）、`Makefile` `XS_WOLF_GRHSIM_IR_RESIDUE_FOLD` / `GRHSIM_REEMIT_RESIDUE_FOLD` + 新目标 `analyze_grhsim_residue_fold_census` / `analyze_grhsim_residue_fold` / `test_grhsim_residue_fold_census` / `test_grhsim_residue_fold_gates`。
  - 分析设施：`scripts/grhsim_residue_fold_census.py`（单测 6）、`scripts/grhsim_residue_fold_gates.py`（预注册语义门 1–7；单测 14）。
- **与父节点差异**：wolvrix `61b092e` + 上述 9 文件（2 新 7 改）；根仓库 + 普查/门/单测 4 脚本 + 2 流程脚本改动 + Makefile 变量与 4 目标 + 本报告。
- **聚焦测试（全部通过）**：wolvrix 增量构建通过；`make test_grhsim_cpu_emit test_grhsim_cpu_schedule test_grhsim_cpu_mapping` 全过（含新 runFoldResidueTest）；普查/门脚本单测 6+14 全过。
- **冒烟验证（flow-smoke reemit，四门开，`ptmp/no00016_identity_fold_20260926/gates-smoke2/`）**：门 3/4/5/7 全 PASS——fold 集 **11,880 op** 与普查 `selected.json` 逐点一致；闭式动态移除 **500,361,576/run（5,003.6/cycle）**；门关 neutral reemit 对 NO00015 归档 **4,544 文件逐字节一致（NEUTRAL-IDENTICAL）**。

### 预注册修订（2026-09-26，实施期正确性驱动，任何生产测量之前登记）

1. **顺序感知 CSE**：验证器要求 defined-before-use（常量 emit 内联无 slot 依赖，但 verifier 按 compute 游走序检查），CSE 命中从"首个模型序常量"细化为"首个 verifier 游走序前置常量"。实证 5,096 个 CSE 命中中 332 个原引用迟到常量，331 个被更早常量救回，仅 1 个 op（self_lt）被拒。**修订后选中 11,880 op、闭式动态移除 500,361,576/run**（= 预注册 11,881 / 500,439,669 − 恰该 op 的 78,093）。普查与 C++ pass 双侧同步实现同一判定。锚定阈值 M-net ≤3,940,463.4 不变（修订差 78,093/run = 点估计的 0.016%，不影响阈值推导）。
2. **门 ⅲ schedule 前缀规则修订**：refreshCpuSchedule 在重接线后的 operand 图上重放 NO00014 去监测不动点/NO00015 补边规则，computeSupernodeFanout 合法变化（预注册"仅尾部新字段"未料到此交互）：203 个丢弃行（producer 经 fold 改线后新图中每个非常量 operand 的 fanout 覆盖全部旧目标，行冗余）+ 13 个生长行（全部为重接线目的地、activate 只增不减、arm 不变）；其余 10 个 schedule 字段（含 quiescenceProjection，未缩小）严格相等。门 3 按此精确规则实现并含反向用例（不可归因丢弃/activate 收缩/非重接线目的地生长均判 FAIL）。该变化是 NO00014/15 既有安全规则在更精确依赖图上的**收缩性**重放（只删冗余项/只增冷 activate），新鲜性证明链不受影响。
3. **门 ⅱ 动态计数器规则修订（counters-equal → counters-projection，2026-09-26，dyn 门首轮运行后、任何性能测量之前登记）**：预注册门 ⅱ 假设"locals 域折叠不改变任何 boundary 写、激活、检测"，但修订 2 已登记 refresh 时 NO00014 重放丢弃 203 条冗余 fanout 行（静态侧由门 3 验证并含反向用例），门 ⅱ 未同步覆盖该**已登记静态变化**的动态投影。dyn 门首轮门 2 失败，归因分析（一次性探针 `ptmp/no00016_identity_fold_20260926/attribute_gate2.py`，其全部闭式核对随后固化进 `scripts/grhsim_residue_fold_gates.py` 门 2 成为权威实现）证实全部动态差量**零残差**等于该 203 行的投影：① vchg 消失集 == 丢弃行值集（203==203 精确集合相等，无新键，669,660 存活键逐键相等）；② kind 仅 `core.compute.concat` 变化：wr −1,500,569 == silent +1,500,569 == Σ wr(203 值基线 vchg 行)，ch −43,484 == Σ ch（203 值全部由 concat 产生，与唯一变化的 kind 一致）；③ sn 仅 95 键变化，全在丢弃值生产单元内（103 个生产单元的真子集——chg 仅在"该 body 执行中只有丢弃值变化"时才下降，机制上必为子集），仅 chg 场严格下降，act/body/grp 31,612 键逐键不变（激活与 body 执行精确保持，调度语义零变化）；④ totals 仅 grp_fire −17,513 == Σ sn chg 下降（同一发射点 `cpu_dyn_grp_fire+=cpu_dyn_any` 与 `cpu_dyn_sn_chg[u]+=cpu_dyn_any` 的内部一致性）。例外集**不是**从动态数据拟合：它由静态 checkpoint diff 推导（门 3 在 dyn 运行前已验证），1,500,569/43,484/17,513 是静态+基线数据对新运行的精确预测且逐点命中。修订后门 ⅱ（比 NO00014 的 ≤ 门更强，为"例外集闭式相等"门）：vchg 消失集==丢弃集、无新键、存活键逐键相等；kind 变化仅限丢弃值生产 kind 且 wr 下降==silent 上升==Σ wr、ch 下降==Σ ch（反向：有投影量却无变化亦判 FAIL）；sn 无新/失键、变化键⊆生产单元、仅 chg 严格下降；totals 仅 grp_fire 且下降==Σ chg 下降。无丢弃行时退化为逐键精确相等。门脚本实现新增 10 个反向单测（非丢弃集消失/镜像不匹配/应有增量缺失/chg 上升/act 漂移/生产单元外变化/grp_fire 不匹配/新键/无丢弃退化/存活键漂移）。

## 结果测试（TESTED）

- **构建门槛**：生产全流程 gen（四门开）墙钟 **816.65 s**（<1800 s 门）；PGO 三阶段编译墙钟 **662.06 s**（<1800 s 门）；dyn reemit 75.94 s、dyn 构建 229.47 s。
- **生产模型语义门（门 3/4，`gates-prod`）**：ALL PASS——checkpoint 顶层段（strings/types/values/partition）对 NO00015 归档逐字节一致；operations 段差异 == 普查重接线集；schedule 11→12 字段（尾部 fold 列表 11,880 op），computeSupernodeFanout 按修订 2 规则变化（丢弃 203 / 生长 13，全部通过反向用例校验）；fold 集 11,880 op 与普查选中集逐点一致。
- **门关一致性（门 5，`gates-smoke2`）**：默认管线（无本 pass）neutral reemit 对 NO00015 归档 **4,544 文件逐字节一致（NEUTRAL-IDENTICAL）**。
- **dyn 运行（2×100k，四门开 + dynamic-stats）**：run1/run2 端点四字段精确匹配 `instrCnt=240,349、cycleCnt=99,996、guest=100,001、PC=0x80000c0c`，DIFFTEST 无 mismatch（显式 grep 0 命中），run1/run2 vchg+dyn 键流 **26,784,610 字节逐字节一致（DETERMINISM-IDENTICAL）**；退出码 0，无 INVALID。
- **dyn 语义门（门 1/2/3/4/7，`gates-dyn`）**：ALL PASS——
  - 门 1 端点/确定性/difftest：PASS（如上）；
  - 门 2（修订 3 投影规则）：PASS——vchg 消失 203 键 == 静态丢弃行集（无新键、669,660 存活键逐键相等）；kind 仅 concat 变化且 wr −1,500,569 == silent +1,500,569 == 丢弃值基线 wr 和、ch −43,484 == 丢弃值基线 ch 和（精确镜像）；sn 95 键仅 chg 场下降（合计 −17,513，全部在 103 个丢弃值生产单元内），act/body/grp 31,612 键逐键不变（**激活与 body 执行零变化**）；totals 仅 grp_fire −17,513 == Σ sn chg 下降；
  - 门 3/4 同生产模型门（dyn checkpoint 独立复核通过）；
  - 门 7 动态移除闭式：**500,361,576/run（5,003.6/cycle）零误差** == 预注册修订值；分类 assign_strict 237,230,097 / const_slice 162,190,418 / slice_full_strict 46,835,373 / dce_cascade 43,022,574 / self_eq 9,020,350 / not_not 1,335,157 / self_ne 627,540 / assign_width 100,067。
- **首轮门 2 失败与处置（如实记录）**：修订前门 ⅱ（逐键精确相等）首轮 FAIL（vchg 203 消失、concat/sn chg/grp_fire 差量）；归因分析闭式证明全部差量 == 修订 2 已登记静态变化的动态投影（零残差），按修订 3 修订门规则后 PASS。修订 3 登记于任何性能测量之前；例外集由静态 checkpoint diff 推导而非动态数据拟合。
- **M-net（锚定，同窗口 3+3 perfstat，逐次 fadvise；14 次运行全部 VALID：端点四字段精确、mismatch=0）**：
  - 旧（NO00015 归档构建）：3,949,938.61 instr/cycle（394,997,810,704/run，3 次 […743,930 / …743,097 / …945,085]，spread 5.1e-7）；
  - 新（NO00016）：3,949,724.13 instr/cycle（394,976,362,688/run，3 次 […037,932 / …524,498 / …525,634]，spread 1.2e-6）；
  - **Δ = −214.48/cycle = −0.00543%，门 ≤3,940,463.4（−0.24%）差距 44 倍，FAIL**；对点估计 −0.35% 的实现率 **1.6%**；折合每次被移除 op 动态执行仅省 **0.0429 instr**（成本模型预测 ≈2.5–3，误差 ~65×）；同窗口 gsim 侧 1.9655e11 instr 不变（ratio 2.0096）。
  - 辅助计数同向微缩：branch-misses −0.083%（1,591,383,232→1,590,061,207）、L1-dcache-loads −0.056%、CPI 0.66002→0.66216（+0.32%）。
- **Host（3+3 交替，预注册秩序，逐次 fadvise，`taskset -c 2`）**：旧 [52.894, 52.287, 52.373] 均值 52.518（SD 0.328）；新 [52.154, 52.256, 53.071] 均值 **52.494**（SD 0.503）；**+0.046%**（−0.024 s），Mann-Whitney U=3、单侧精确 **p=0.35 不显著**（秩次判据不成立）、Cliff δ=−0.333；在回退预算 ≤53.73 s 内。
- **实现瑕疵排除（REJECTED 前的必要核对，全部否定实现瑕疵）**：① 生产 checkpoint fold 列表 11,880 op == 普查选中集（门 4）；② 发射源真实变化：task 源 1,052,852,667 vs 1,055,017,408 字节（−2,164,741 B）、总行数 −13,294 ≈ 折叠 op 数、`grhsim_cast_u64` 语句 −3,814（assign_strict 3,474 + assign_width 17 + 部分级联 DCE）；③ 二进制 .text 130,183,301 vs 130,194,157（−10,856 B）；④ M-net 差量 −21.4M instr 为组内 spread（±0.5M）的 40 倍且方向正确；⑤ 动态侧 203 行投影逐点命中（修订 3）。即折叠**确实**删除了语句且只省了 0.043 instr/次——成本模型而非实现被证伪。

### 定量复盘与机制性判定（负向结果）

- **数据**：静态删除 11,880 op（13.3K 源行）→ .text 仅 −0.91 B/op（−0.0083%）；动态移除 500,361,576 op 执行/run（闭式零误差，占 dyn 总量 0.543%）→ 总指令仅 −21,448,016/run（−0.00543%）。**每次 op 执行的边际成本实测 0.043 instr，而非成本模型假设的 2.5–3**。
- **机制归因（机制性错误，非实现瑕疵）**：locals 域字节帧槽位在 clang（PGO）下对每个 unit body 的单次执行是**执行内临时量**——constant-offset 访问可被 BasicAA/GVN 穿透：恒等链在直线代码中被 copy/constant 传播完全塌缩，消费者载入被 store-to-load 前递吸收（槽位只在控制流合并点物化，即 NO00009 的"内存槽即 PHI 合并点"保护的重述）；重接线后被折叠值的槽位无读者，存储被 DSE 消除。故基线二进制中这些 op **本来就接近零成本**（静态 0.91 B/op、动态 0.043 instr/exec），"转换伪影残余 op 的逐 fire 物化浪费"在本代码形态下不存在可压缩空间。
- **与机制证伪表既有条目的合流**：NO00009（值承载 typed-SSA 提升反优）、NO00011（表达式树融合反优）之后，本节点补全第三格——**整条删除**恒等/常量 op 也只能取得 ~0.04 instr/op：三层字节帧保护在"变更值承载/融合表达式/删除语句"三种粒度变体上全部成立。NO00008 因子表 8.54× instr/work 密度差距**不可**归因于语义平凡局部 op 的物化浪费；以静态语句数定价动态指令成本的成本模型作废。
- **判定**：锚定指标未达预注册阈值且闭式/语义门全过——按预注册证伪条款，**REJECTED**（机制性错误）。Host 52.494 s（+0.046%，不显著）在预算内，当前最佳指针不动（NO00015，52.672 s）。设施门控留存（`--fold-residue` / `GRHSIM_REEMIT_RESIDUE_FOLD` 默认关，门关 = NO00015 管线逐字节一致 NEUTRAL-IDENTICAL）；普查/门/归因脚本与 30 个单测留存。
- **hdlbits（门 6）**：`run_all`（001–105，至预存失败止）+ 逐个 106–162——**161/162 通过**，唯一失败 DUT=105 且错误文本与预注册逐字一致（预存失败，与 NO00010–NO00015 相同）。门 6 解析器修复（工具性，非语义放宽）：逐个 DUT 目标打印 `[RUN] DUT=x GRHSIM` 而非 run_all 横幅、dut_162 的 passed 行无冒号后缀，两种格式均有单测覆盖。

## 判定

**REJECTED**（机制性错误）。锚定指标 M-net −0.00543% 未达预注册阈值 −0.24%（差 44 倍），闭式/语义门 1–7 全过、构建门槛通过、Host +0.046%（p=0.35 不显著）在 +2% 预算内——按预注册证伪条款精确命中"恒等/常量残余 op 的逐 fire 物化成本 ≈2.5–3 instr"命题机制性证伪。当前最佳指针不动（NO00015，52.672 s）。设施门控留存：`--fold-residue` / `GRHSIM_REEMIT_RESIDUE_FOLD` 默认关（门关 neutral reemit 对 NO00015 归档 4,544 文件逐字节一致）；普查/门/单测（6+25）与归因核对逻辑固化于 `scripts/grhsim_residue_fold_census.py` / `scripts/grhsim_residue_fold_gates.py`。
