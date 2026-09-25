# NO00011: GrhSIM IR 表达式树融合——单-use 纯计算链替换为 `core.compute.expr` 复合 op（每 op 语句粒度物化消除）

| 字段 | 值 |
|---|---|
| 父节点 | NO00010（当前最佳） |
| 角色 | 优化 |
| 状态 | **REJECTED**（机制性错误：锚定 M-fuse 反 **+15.00%**（门 ≤−6%），Host +9.05% 破预算；逐 op 语句物化的帧形态给 clang 三层保护在 op 图粒度变体上再次成立） |
| 锚定指标 | M-fuse = compute_task instr/guest-cycle（基线 **3,227,616**，NO00010 同窗口实测） |
| 指标阈值 | M-fuse 降 **≥6%**（≤3,033,959）；语义门：端点四字段精确 + DIFFTEST 无 mismatch + `[grhsim-dyn]` 日志逐键一致 |
| 回退预算 | Host ≤ **+2%**（≤54.49 s，基线 NO00010 归档 53.426 s）；等价/构建门槛不放宽 |
| RUN_ID | no00011_expr_fusion_20260925 |
| 工作区 | ptmp/no00011_expr_fusion_20260925/（立项勘察 ptmp/no00011_scout_20260925/） |

## 基础选定（BASELINE）

- **父节点**：NO00010（当前最佳指针，GrhSIM-IR PGO 构建 Host **53.426 s**，3 次有效均值，SD 0.099 s）。当前 wolvrix `eed8839`（= NO00010 提交，含 NO00007/NO00009 门控设施、两门默认关）+ 根仓库 `3ffb36a`（NO00010 提交 `1737a34` + 文档提示提交），工作区干净，以其为实施基线，无迂回。
- **立项动机（为什么是这个方向）**：NO00008 因子表 F（闭合残差 0%）把 2.0× 指令差距完全闭合于"每单位工作指令密度"（ir 3.86 instr/dynOp vs gsim 0.452 instr/enode，8.54×）；NO00009 证伪了值承载表达分量（byte-frame→typed SSA 提升反 +3.85%，三层保护机制），NO00010 削减了 fanout 簿记（M-idens 3.8607→3.2445）。用户最新提示（2026-09-25）指出原理性问题：gsim 直读 FIRRTL，GrhSIM-IR 经 Firtool+GRH IR 两重转换形态受损，须在 **GRHSIM IR 层面做 IR 替换**（非单纯 emit 形态替换）消除形态差异。本节点勘察（下方普查）定位出当前最大的形态差异：**gsim 把 FIRRTL 表达式树内联为 straight-line C++（中间值为编译器临时），而 ir 逐 op 物化到 cpu_local/cpu_boundary 槽位**——每个 op 一条语句、一次定宽规范化、一次帧往返。
- **瓶颈证据（本节点立项普查；checkpoint = `ptmp/no00004_compiler_pgo_20260924/flow/xiangshan_grhsim_ir.json`，NO00010 已验证其与当前代码态逐字节一致；动态口径 = NO00006 dyn-old 归档日志，NO00008/NO00009/NO00010 复用同源）**：
  - **融合池普查**（`scripts/grhsim_fuse_chain_stats.py` 口径 + 本节点 chunk 感知/标量限定复核脚本）：单-use、非 boundary、同 supernode 且同 helperChunk、结果与全部操作数均为 ≤64 位二态 logic 的纯 `core.compute.*` op = **2,166,405 个静态 op**（分区 op 总量 3,531,463 的 **61.3%**），组成 **607,300 棵表达式树**（均值 3.57 个被融合 op/树）；按 sn body 加权连接动态日志：**动态可融合 op 执行 612,239.3 次/guest cycle = dynOps（994,789.4/cycle）的 61.54%**。可融合 op 的 kind 分布头部：or 562,644 / and 493,394 / mux 239,591 / concat 191,402 / bitSelect 120,847 / eq 109,811 / sliceStatic 90,222 / add 85,735。
  - 逐 op 成本解剖（NO00009 实测，task_1000 热 unit）：load 26.5% + frame/boundary store 12.1% ≈ 内存往返 ~39% ≈ 1.5 条/op；逐 op 语句粒度是这些往返的结构来源（每 op 一次定值存储 + 消费者读回）。
  - **替代方向排除（全部量化）**：代数残余（自反/补对/吸收/双否定）全模型仅 **1,229** 个候选；bijective change-sharing **1,188** 个；slice 链（slice-of-concat + nested）17,128/199,646（8.6% sliceStatic）；mux 代数池合计 0.32% writebacks；`grhsim_cast_u64` 静态站点 2,080,726 处中 **99.58% 为同宽/无符号加宽**（编译器常量折叠，无运行时代价）。以上均不足以支撑节点。
- **与 NO00009 证伪条目的兼容性（机制证伪表要求：值承载变体立项须定量反驳三层保护）**：本节点不是"帧往返浪费"的重提——NO00009 证伪的是"逐值 byte-frame→typed SSA 重命名"（值承载替换，保留逐 op 语句），本节点是 **op 图粒度替换**（多 op → 单复合 op，中间值根本不物化为任何具名实体）。逐项：
  1. **内存槽即 PHI 合并点**（NO00009 cmov +156,548/+39% 的机制）：融合不产生任何中间值的条件定值——树内部值单-use 直线依赖，无汇合点；树根保持原有帧槽位与条件定值形态（内存合并点原样保留）。结构上不适用。
  2. **不透明字节访问抑制 SLP**（NO00009 SSE +13.4%）：融合后的表达式内部是干净 SSA——该保护**确实被剥夺**，此为残余风险；反驳证据是 gsim 全模型即表达式树形态（`cppEmitter` 整树内联），同一设计、同一 clang 族编译器实测 0.452 instr/enode——该形态在本负载上的效率上限已被存在性证明。本节点以反汇编普查 SSE 计数作哨兵登记（辅助，不设门）。
  3. **小帧集中驻留 L1 且不占寄存器**：融合使 61.3% 的槽位访存指令消失（L1 流量单调下降），表达式临时只在树根语句内活跃（均值 3.57 节点/树，寄存器压力有限且寿命短）。gsim 形态存在性证明同 (2)。
- **gsim 环比**：gsim super 内 enode = 表达式树节点，codegen 整树内联、中间值为编译器临时（NO00009 报告实证 0.452 instr/enode）；ir 逐 op 语句化是经 SV→GRH→GrhSIM 转换后的形态退化（每 op 独立定宽+槽位物化）。本节点即从 GRHSIM IR 层面把 op 图改写回表达式树形态（IR 替换：新 op kind + 中间 op 移除），直接检验 goal 科学问题的"表达/映射形态 → 逐 op 成本"归因。
- **基线测量（配置未变，复用归档值，不重跑）**：
  - GrhSIM-IR 当前最佳（NO00010）：Host **53.426 s**（3 次有效均值，SD 0.099 s）；端点 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`。
  - gsim+PGO 锚点：Host **27.376 s**（SD 0.065 s）；端点 `238550/99998/100001/0x80000b40`。差距 **1.952×**。
  - M-fuse 基线：compute_task = **3,227,616 instr/guest-cycle**（NO00010 TESTED 同窗口实测新侧）；参照：总 instr 4.0210e11、CPI 0.6679、branch-misses 16,044.4/cycle、L1-icache-miss 826.9M、compute_share 80.27%。
  - dynOps = 99,479,933,605（994,789.4/guest cycle）；activations 993,413,585；bodies 904,557,815；boundary 写 22,134,521,354、真变化 1,267,630,634（5.73%）。
- **输入核对（sha256，与 NO00001–NO00010 相同，输入未变）**：
  - `testcase/xiangshan/ready-to-run/coremark-2-iteration.bin` = `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`
  - `testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so` = `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`
- **代码状态核对**：wolvrix `eed8839`（工作区干净）；根仓库 `3ffb36a`；xiangshan/reference 子模块不动。冻结面（GRH IR、GRH 已有 pass、XiangShan 与测试源码）零改动；改动范围：GrhSIM IR 新 pass（新增文件）、`core.compute.expr` op 注册、CPU 发射器 expr  lowering、流程脚本接线、分析与测试脚本（goal 文档允许修改 GrhSIM-IR 语义/op/emit）。
- **资源配置**：与 NO00001–NO00010 一致：`XS_EMU_CPU=2`、`XS_EMU_THREADS=1`、`XS_NUM_CORES=1`、`XS_SIM_MAX_CYCLE=100000`、waveform/commit/RAM trace 全关；编译 `VM_BUILD_JOBS=32`（nproc=32）；测量时机器空载；逐次 `posix_fadvise(DONTNEED)` 驱页缓存。
- **计时边界与止损线**：
  - SV→C++ 生成 <1800 s（NO00010 同流程 791.47 s 量级）；C++ 编译（PGO 三阶段合计）<1800 s（NO00010 同流程 667.30 s 量级）；超限记 `TIMEOUT_KILLED`。
  - 生产仿真：比较值预选为 NO00010 归档均值 **53.426 s**，运行上限 **1.5× = 80.1 s**，超时记 `REGRESSION_KILLED`；动态统计诊断运行上限 300 s。
  - 等价性：ir 侧端点四字段精确匹配 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c` 且 DIFFTEST 无 mismatch，否则 `INVALID`（按实现瑕疵处理）。

## 假设提出（HYPOTHESIS）

- **假设**：compute unit 内单-use、非 boundary、同 supernode 同 helperChunk、全标量（≤64 位二态）的纯计算 op 链，在 GrhSIM IR 层面替换为 **`core.compute.expr` 表达式树复合 op**（新 op kind；operands = 树的叶值；parameters 编码后缀序树结构；中间 op 从分区 op 表中移除、结果值槽位不再被发射），可把 61.54% 的动态 op 执行从"逐 op 语句 + 帧槽往返"形态改写为 gsim 式整树内联形态——中间值成为编译器表达式临时（可驻留寄存器、参与 DAG 调度），消除每 op 的独立定值存储/读回与逐 op 规范化语句边界。**M-fuse（compute_task instr/guest-cycle）降 ≥6%（预期 −10%~−20%）**，分区/调度/激活/检测/扇出/提交全部不变（行为语义中性：树内求值顺序与原依赖序一致，检测只在树根保留）。
- **创新点**：本分支首个针对 **op 图粒度**（逐 op 语句 vs 表达式树）的 IR 级替换——直接对齐 gsim 的 enode 内联形态（该形态在同设计同编译器族下实测 0.452 instr/enode，NO00009 报告）；与 NO00006（激活粒度）、NO00007（输入精度）、NO00009（逐值承载）、NO00010（fanout 簿记形态）正交：不动分区、不动激活、不动任何值的语义与监测集。方法学上这是对"Firtool+GRH 转换破坏表达式树形态"这一原理性问题的首个直接 IR 级修复实验。
- **微观指标与总目标的定量关系**：
  - **M-fuse** = compute_task instr/guest-cycle（NO00005 M-attr perf 任务归因链路，基线 3,227,616）。与总目标关系（本分支实测链）：compute_task 占模型指令 ~80%（NO00010：3.227M/4.021M）；Host ≈ instr × CPI/freq，CPI 由分支/icache 次级效应决定（NO00004/NO00010 均呈 instr 主导）。M-fuse −6% ⇒ 总 instr ≈ −4.8% ⇒ CPI 中性下 Host ≈ −2.5 s 量级。
  - **预期规模**：612,239 次/cycle 可融合执行 × 每 op 消除帧往返（NO00009 残余估计 0.5–0.6 条/op 为保守下界；完整槽位消除 ~1.5–2 条/op 为上界）⇒ compute 预期 −9.5%~−28%；门取 −6%（保守）。注：dynOps 口径将随 op 移除下降 ~61.5%（分母变化），故锚定指标取绝对口径 compute instr/cycle 而非 M-idens 比值。
  - **语义中性门**：①端点四字段精确匹配 + DIFFTEST 无 mismatch；②`[grhsim-dyn]` 日志（totals/kind/sn/edge/round 全键）与归档逐键一致——boundary 写检测只在树根发生且树根 kind 由参数保留，激活/变化/组计数全不变（实现须保证 expr op 的动态计数归属树根原 kind）；任何差异 = 实现瑕疵。
  - 辅助登记（不设门）：dynOps 新值（预期 ~383K/cycle）、.text 尺寸、L1-icache-miss、branch-misses、反汇编 SSE 静态计数（NO00009 的 SLP 哨兵）、生成/编译墙钟、Host 3+3 交替。
- **预注册**：
  - **测量方法与运行秩序**：①聚焦测试（`test_grhsim_cpu_emit` + 新 pass 单测 + `run_hdlbits_test DUT=001`，全量 hdlbits IR 回归）→ ②重构中性验证（`reemit_grhsim_ir` 以归档 checkpoint 重发射：未启用融合时生成文本与 NO00010 归档逐字节一致）→ ③融合 reemit + 动态统计构建 100k，dyn 日志逐键比对 + 端点精确 → ④PGO 生产构建（`xs_wolf_grhsim_ir_emu_pgo`，同 NO00004/NO00009/NO00010 流程）→ ⑤perf 任务归因（M-attr 链路，新旧同窗口各 1 次：M-fuse、CPI、branch-misses、icache）→ ⑥3+3 交替 Host 复测（顺序 新-旧-新-旧-新-旧，逐次 posix_fadvise，`taskset -c 2`）。
  - **改善门槛**：M-fuse ≤ **3,033,959**（3,227,616 × 0.94，降 ≥6%）。
  - **语义中性门**：端点四字段精确 + DIFFTEST 无 mismatch + dyn 日志逐键一致（剥离 ANSI 转义后逐字节）。
  - **回退预算**：Host 新构建均值 ≤ **54.49 s**（+2%）；改善时以秩次判据（3+3，单侧 p≤0.05）登记显著性。
  - **构建门槛**：生成 <1800 s、编译（PGO 三阶段合计）<1800 s。
  - **判定规则（吸取 NO00010 绊线教训，显式合取/析取）**：验收 = 锚定指标达门 ∧ 语义门通过 ∧ 构建门槛通过 ∧ Host 在回退预算内（辅助哨兵仅登记不设门）。负向处置：锚定未达门 → 机制性错误（表达式树形态收益不存在，8.54× 因子的形态分量证伪）；锚定达门但 Host 破预算 → 机制性错误（形态收益被 CPI/前端副作用净吃掉）；语义门/构建门槛失败 → 实现瑕疵，回 IMPLEMENTED 修正重测。
  - **证伪标准**：M-fuse 降 <6%（融合消除的指令被编译器既有提升覆盖或新副作用抵消）→ 机制性错误登记索引证伪表（"逐 op 语句粒度物化是可压缩主因"证伪）。

## 代码实施（IMPLEMENTED）

- **实施基线**：wolvrix `eed8839` + 根仓库 `3ffb36a`（工作区干净开工）。全部改动经 Makefile 目标构建测试；日志在 `ptmp/no00011_expr_fusion_20260925/`。
- **改动清单**（wolvrix 子模块 6 改 2 新；根仓库 3 改 1 新）：
  1. `wolvrix/lib/grhsim/dialect/core.cpp`：剩余 op 白名单 6→7，注册 `"core.compute.expr"`。
  2. `wolvrix/lib/grhsim/ir/verifier.cpp`：expr 校验分支——单结果、无 objectRefs；必备参数 `tree`（非空 string 向量，后缀序编码）与 `rk`（树根原 kind 全名，`core.compute.` 前缀且 ≠expr）；token 栈机校验（叶下标界、节点字段 ≥6、width 1..64、arity ≤ 栈深、原 opId 有效、int64 键值数值合法）、终栈深 ==1、末 token 须为节点、操作数/结果全标量二态。
  3. `wolvrix/lib/grhsim/pass/fuse_expr_chains.{hpp,cpp}`（新）：`FuseExprChainsPass`（PassKind::BackendMapping，名 `grhsim.fuse-expr-chains`），工厂接受 `--max-tree-ops <n>`（默认 64，域 [2,4096]）。诊断输出 `fuse_expr_trees=/fuse_expr_nodes=/fuse_expr_max_tree=`。
  4. `wolvrix/lib/grhsim/pass/pass.cpp` + `wolvrix/CMakeLists.txt`：注册与入库。
  5. `wolvrix/lib/grhsim/backend/cpu_emit.cpp`：
     - 原 `expression()` 标量段逐字抽取为模板 `scalarExpression`（kind/result/arity/raw/typeOf/number 回调参数化），已用机械 diff 验证与 git HEAD 原文 0 差异（仅 `type(operands[i])→typeOf(i)`、`operands.size()→arity` 系统性替换）。
     - 新 `fusedExpression(op)`：栈机解释 `tree` token——叶 `l<k>` 走 `value()`，内部节点 `n;<kind>;<width>;<signed>;<arity>;<opId>[;key=int64...]` 调 `scalarExpression` 并按节点自身 (width,signed) 逐层 normalize（=原逐 op 语义）；根节点不 normalize（由 `compute()` 外层统一做，与原路径一致）。
     - 构造器：`dynKinds_` 遇 expr 用 `rk`；`fanout_` 填充后构建 `fusedAway_`（校验中间 op 单结果、无 fanout、非 boundary，违反即 throw）。
     - `dynKind()` 对 expr 查 `rk`；`emitsNothing` 加 fusedAway 检查（不 split gate run）；cone 路径 runOps 按树节点数加权（`fusedTreeWeight_`，sn_exec 不变）；`compute()` 顶部 fusedAway 早退（防御）。
  6. `scripts/wolvrix_xs_grhsim_ir.py`：**（最终态，判定后按 REJECTED 设施门控先例修订）** 共享 `CPU_PIPELINE` 保持 NO00010 原样（默认不含融合，hdlbits IR 流共用该管线故默认亦不融合）；XS 流程新增 `--fuse-expr-chains` 开关（默认关），开启时在管线末尾追加 `grhsim.fuse-expr-chains`。门关 == NO00010 管线逐字一致（由②重构中性字节级证据覆盖）。
  7. `scripts/reemit_grhsim_ir.py`：新增 `--fuse-expr-chains` 开关（所有 remap 动作之后追加）；`Makefile` `reemit_grhsim_ir` 目标新增 `GRHSIM_REEMIT_FUSE_EXPR_CHAINS=1` knob。
  8. `wolvrix/tests/grhsim/test_grhsim_ir.cpp`：新增 `runFuseExprChainsTest()`——完整 CPU mapping 管线 + 融合：三 op 链正向 + 幂等、tapped 中间值守卫、verifier 拒绝栈下溢畸形树。
  9. `scripts/grhsim_fuse_expr_census.py`（新）：立项普查脚本入库（chunk 感知标量限定口径）。
  10. `wolvrix/include/grhsim/backend/cpu.hpp` + `wolvrix/lib/grhsim/backend/cpu_layout.cpp`（修复追加）：新 `refreshCpuDataLayout()`——在映射的分区树上重算 canonical data layout 并仅替换映射的 dataLayout 载荷（stage/schedule/partitionTree 不动）；融合 pass 在有融合时调用。
- **实现瑕疵修复记录（首次融合 reemit 暴露）**：`cpu.layout` 校验报 "CPU data layout differs from canonical types, storage or runtime slots"。机制：`planHelperReadCaches`（`cpu_layout.cpp:76`）按 helperChunk 统计操作数使用次数并缓存 count>1 的 boundary 叶值——融合后树根直接引用叶值，叶值计数 +1 越过阈值，helperReadCaches 变化；而 dataLayout 是操作数结构的确定性函数，归档映射的 layout 与融合后模型不一致。定案修复：pass 末尾调 `refreshCpuDataLayout` 重算 dataLayout（stage 保持 Schedule，分区树/schedule 不动；`setCpuMapping` 对齐 sourceSemanticRevision，stale 检查不触发）。HYPOTHESIS 中"映射完全不动"据此修正为"分区树/schedule/值槽分类不动，dataLayout 载荷随操作数结构重算"——dataLayout 仅决定帧内偏移与读缓存局部变量，语义与 dyn 键不受影响。
- **实现瑕疵修复记录二（gen 流程 checkpoint 自检暴露）**：`store → 新会话 reload` 自检报 `serialized operand count is 10850544, payload contains 9726603`。机制：`replaceOperation` 的池是 append-only，旧区间成为孤儿；JSON 格式的载荷按 op 逐个序列化其区间（不含孤儿），而头部计数写 `operandPool().size()`（含孤儿），load 端重建池为纯拼接后与头部计数不符。此前所有 `replaceOperation` pass 之后都有 compact（清映射、重建池）兜底，融合是首个在最终映射之后、无 compact 的改 op pass，首次暴露该格式缺陷。修复：`wolvrix/lib/grhsim/io/json.cpp` `writeCounts` 的 operands/results/object_refs/parameters 四项头部计数改为逐 op 区间求和（=载荷真实内容）；旧归档 checkpoint 在存储时无孤儿（头部==求和），向后兼容。单测补 store→load→store 字节稳定 round-trip（融合模型小尺度复现）。gen 重跑自检通过（见 TESTED）。
- **对 HYPOTHESIS 的口径偏差（设计定案，须登记）**：HYPOTHESIS 写"中间 op 从分区 op 表中移除、dynOps 预期降 ~61.5%"。定案为 **中间 op 不从分区表删除**——保留在模型与分区 op 表中（producer 唯一性、verifier covered 检查天然满足，compact 不丢 mapping），emit 侧用 `fusedAway_` 集合跳过其发射；仅树根 `replaceOperation` 为 `core.compute.expr`（保 OpId/name/结果值/帧槽/boundary 检测/组扇出）。`replaceOperation` 不推进 semanticRevision，故 verifier "mapping is stale" 检查（`verifier.cpp:488`）不触发，pass 无需重建 CPU mapping。**dyn 日志逐键一致的实现手段**：expr op 的动态计数经 `rk` 参数归属树根原 kind；cone 路径 runOps 按树节点数加权（sn_exec 不变）；中间 op 本无 fanout/boundary，wr/ch/silent/组计数不变。因此 **dynOps 不变**（非 HYPOTHESIS 预期的 −61.5%）；锚定指标 M-fuse 为绝对口径 instr/cycle，不受分母口径影响。
- **资格与截断（定案）**：42 个 kind（add/sub/mul/and/or/xor/xnor/not/shl/lshr/ashr/div/mod/eq/ne/caseEq/caseNe/wildcardEq/wildcardNe/lt/le/gt/ge/logicAnd/logicOr/logicNot/reduce×6/mux/bitSelect/prioritySelect/concat/replicate/sliceStatic/sliceDynamic/sliceArray/assign）；单结果、无 objectRefs、参数全 int64、结果与全部操作数 1..64 位二态 logic。中间边另需 uses==1、soleConsumer、非 protected（boundary 槽/computeSupernodeFanout/inputFanout/runtime 槽/eventGate 事件/inputShadows）、同 chunkKey；根须 inComputeUnit（kind==Supernode 且 children 全 Node）且 uses≥1（uses==0 死 op 跳过，保证幂等）。cap=64 节点/树，截断处残余链由"consumer 已 claim 则为新根"规则同次 sweep 分段。commit 侧（无 children 的 kind-3）不融。
- **聚焦测试（全过）**：`make test_grhsim_cpu_mapping`（grhsim-ir-tests + grhsim-cpu-mapping-tests，含新单测）；`make test_grhsim_cpu_emit`（96.87 s）；`make run_hdlbits_grhsim_ir DUT=001`（`[GrhTB] dut_001 passed: one=1`）。修复记录：转写错误一处（sliceArray 窄源行 `">=64/"` 误为 `")>=64/"`），由 emit 测试捕获并修复。

## 结果测试（TESTED）

- **运行秩序**：①聚焦测试（全过，见 IMPLEMENTED）→ ②重构中性 → ③dyn 语义门 → 全量 hdlbits 回归（与③后并行补跑）→ ④PGO 生产构建 → ⑤perf 归因 → ⑥3+3 Host。
- **②重构中性**（`reemit_neutral.sh`）：新代码**不带**融合重发射归档 checkpoint（双 walk flag），与 NO00010 归档生产模型逐字节 `diff -rq`——4541 行差异全部为 NO00010 归档侧的编译产物（`.o`/`libgrhsim_SimTop.a`），源文件零内容差异、新侧零独有文件，**NEUTRAL-IDENTICAL**（reemit 49.64 s）。
- **③dyn 语义门**（`dyn_gate_unfused.sh` / `dyn_gate_fused.sh`，均干净重跑）：
  - 融合规模：**fuse_expr_trees=444,828、fuse_expr_nodes=2,398,422、fuse_expr_max_tree=64**（触及 cap）；对拍立项普查（607,300 树/2.17M 被融合 op）：pass nodes 口径含树根（2,398,422 − 444,828 = 1,953,594 个被融合 op = 普查估计的 90%），差异来自 protected 集排除、cap=64 截断分段与 uses==0 根跳过，方向与量级一致。
  - **逐键一致（双比对）**：融合构建 `[grhsim-dyn]` 32,145 键与同码未融合参照 **IDENTICAL**，与 NO00006 归档 dyn-old **IDENTICAL**。
  - **端点四字段精确**：`instrCnt=240,349、cycleCnt=99,996`、PC=`0x80000c0c`（EXCEEDING CYCLE/INSTR LIMIT 于 100k 窗口，guest=100001），DIFFTEST 无 mismatch。两侧构建/运行 exit=0（融合 reemit 含 layout 刷新后通过 cpu.layout 校验）。
  - **结论：语义中性门通过。**
- **全量 hdlbits IR 回归**（融合构建，③后并行补跑）：**161/162 通过**。DUT=001–104 全过（`hdlbits_all.log`，104 passed）；DUT=105 失败——逐字核对与 NO00010 归档日志（`hdlbits_ir_all.log`/`hdlbits_ir_all_k.log`）**同一 pre-existing 失败**（`used-bits dangling value 101 … (originalOps=124)` 错误文本逐字一致，非融合引入）；DUT=106–162 全过（`hdlbits_ir_106_162.log`，57 PASS）。与父节点完全持平。
- **④PGO 生产构建**（`gen_build_pgo.sh`，门槛 1800 s/1800 s）：
  - SV→C++ 生成：前两轮 exit=2（分别暴露 layout 刷新与 JSON 计数两处实现瑕疵，修复记录一/二）；修复后干净全量重跑 **gen3：gen_wall=794.01 s，exit=0**（store→reload 自检 + round-trip 逐字节验证通过，融合 pass 6.2 s），**过门**。模型 4,543 个源文件与构建所用 gen1 产物逐哈希一致（`model_hashes_*` 比对，唯一差异为构建产物 `.a/.o`）——bench/perf 所用 emu（sha256 `48b1fd3d…`）对应最终源。
  - C++ 编译（PGO 三阶段合计）：**build_pgo_wall=696.70 s，exit=0**，**过门**。
- **⑤perf 任务归因**（M-attr 链路，`grhsim_native_work_compare.py`，新旧同窗口各 3 次 perfstat + 1 次 record，gsim+PGO 同窗口环比；guest=100,001）：

  | 指标（每 guest cycle） | 旧（NO00010 同窗口） | 新（NO00011） | Δ | 判定 |
  |---|---|---|---|---|
  | **M-fuse = compute_task instr/cycle** | 3,223,194 | **3,711,673** | **+15.00%**（对归档基线 3,227,616） | **≤3,033,959（−6%）：FAIL，方向反转** |
  | 总 instr/cycle | 4,020,951 | 4,493,551 | **+11.75%** | 辅助 |
  | CPI | 0.6621 | 0.6440 | −2.73% | 辅助 |
  | cycles/cycle | 2,662,189 | 2,893,778 | +8.69% | 辅助 |
  | branch-misses/cycle | 16,038.4 | 15,781.4 | −1.6% | 辅助（无分支形态恶化） |
  | L1-dcache-loads/cycle | 2,014,511 | 2,408,248 | **+19.54%**（Δ=393,737 = 指令总增量的 **83.3%**） | 辅助 |
  | L1-dcache-load-misses/cycle | 104,691 | 106,471 | +1.70% | 辅助 |
  | L1-icache-miss（总量） | 903.3M | 884.3M | −2.1% | 辅助 |
  | compute_task 份额 | 80.16% | 82.60% | +2.44pp | 辅助 |

  旧侧同窗口 M-fuse=3,223,194 对归档基线 −0.14%，口径一致性自证。指令增量几乎全部落在 compute_task（+488,479/cycle；commit +8,681、evaluator/infra 噪声级）。**每被融合动态 op 执行（612,239/cycle）净增 +0.80 instr**——假设预期 −0.5~−2.0，符号反转。
- **⑥3+3 交替 Host 复测**（`benchmark_grhsim_ir.py`，逐次 posix_fadvise 驱页缓存，`taskset -c 2`，执行顺序 old1,new1,old2,new2,old3,new3——预注册文本为新-旧起手，实际执行为旧-新起手，交替结构与 3+3 口径不变，属记录偏差非方法偏差）：

  | 次 | 旧 Host s | 新 Host s | 端点四字段 | 退出 |
  |---|---|---|---|---|
  | 1 | 53.393 | 58.072 | 240349/99996/100001/0x80000c0c 两侧精确 | 0/0 |
  | 2 | 53.337 | 58.337 | 同上 | 0/0 |
  | 3 | 53.377 | 58.195 | 同上 | 0/0 |
  | 均值 | **53.369**（SD 0.029） | **58.201**（SD 0.133） | DIFFTEST 两侧无 mismatch | — |

  **Host +9.05%，破回退预算 +2%（54.49 s）**；秩次判据反向（3 次新全部慢于 3 次旧，单侧 p=1.0）。旧侧均值对 NO00010 归档 53.426 偏差 −0.11%，窗口有效。
- **辅助哨兵登记**：.text 132,460,025 → 142,794,889 B（**+7.80%**，+10.33 MB）；dynOps 不变（dyn 日志逐键一致，设计定案）；生成/编译墙钟见④。
- **定量复盘（REJECTED 判定的必要组成）**：
  - **反汇编普查**（`grhsim_disasm_census.py`，两侧各 4,439 个 task/helper 函数全量分类；静态计数）：总计 23,540,147 → 25,537,501（**+8.48%**，与 .text +7.80% 互证）。头部类别：

    | 类别 | 旧 | 新 | Δ | 机制归属 |
    |---|---|---|---|---|
    | load | 4,764,214 | 5,366,726 | **+602,512（+12.6%）** | 保护③：RA 溢出重载 |
    | store | 3,239,016 | 3,786,919 | **+547,903（+16.9%）** | 保护③：溢出写回 |
    | mov_rr | 1,378,209 | 1,540,817 | +162,608（+11.8%） | 保护③：寄存器腾挪 |
    | setcc | 701,053 | 827,282 | **+126,229（+18.0%）** | 保护①：select/条件定值物化 |
    | sse | 1,117,781 | 1,232,360 | **+114,579（+10.3%）** | 保护②：SLP 走火 |
    | zero_store | 419,578 | 488,373 | +68,795（+16.4%） | 保护①：零写物化 |
    | **%rsp 引用** | 5,070,397 | 6,452,589 | **+1,382,192（+27.3%）**，份额 21.54%→25.27% | 保护③直接证据 |

  - **归因链**：静态消除 61.5% 逐 op 帧物化站点，动态内存流量反而上升——L1-dcache-loads +19.54% 占指令总增量的 83.3%，%rsp 引用 +27.3% 锁定寄存器溢出/重载为主机制：均值 3.57 节点（cap 64 触及）的整树表达式把叶值临时量的活跃区间拉长到整条树语句，在已逼近 RA 极限的超大函数体（NO00009 实测 frame 不占寄存器是其核心保护）中引发溢出，其代价超过被消除的逐 op 帧往返。setcc/zero_store 增长对应 mux/select 在树内失去字节槽合并点后的物化；SSE +10.3% 为干净 SSA 触发 SLP 走火的既有签名。三者与 NO00009 的三层保护逐类同构——**在 op 图粒度变体上再次成立**。
  - **机制性判定依据**：锚定指标方向反转（+15.00% vs 门 −6%，差 21 个百分点，非边际）且 Host 同步破预算（+9.05% vs +2%）；收益不存在而非被次级效应掩盖（CPI 反而改善 −2.73%，指令增长本身即是回退来源）；与 NO00009 合流——"SSA/表达式树形态必优于字节帧"在本代码库超大函数体形态下不成立，gsim 0.452 instr/enode 的存在性证明不可迁移到本形态（其函数粒度/状态聚合结构不同，NO00008 因子表显示差距闭合于每单位工作指令密度而非值/语句形态本身）。按预注册析取条款（锚定未达门 → 机制性错误；锚定达门但 Host 破预算 → 机制性错误——本节点两条同时成立）：**机制性错误**。
  - **对后续节点的约束**：融合变体（更小 cap、树内临时变量序列发射、按 hotness 选择性融合、mux 排除）均须先给出可反驳三层保护（%rsp 溢出、setcc/cmov 物化、SLP 走火）的定量证据方可立项；NO00008 因子表"每 dynOp 指令密度 8.54×"的剩余可压缩空间**不可**归因于逐 op 语句粒度——剩余构成（宽度规范化、change-detect 与 fanout 簿记、宽值 helper、commit 结构开销）中簿记类已由 NO00010 部分削减，其余待新机制假设。
- **设施门控留存**（同 NO00007/NO00009 先例）：融合设施（op 注册、verifier、pass、发射器支持、单测、普查脚本）全部保留，XS 流程 `--fuse-expr-chains`（默认关）与 reemit `GRHSIM_REEMIT_FUSE_EXPR_CHAINS=1` 双开关；门关时共享 `CPU_PIPELINE` 逐字等于 NO00010（hdlbits 流默认不融合），②重构中性字节级证据覆盖门关代码路径；门开路径由 gen3 + 全量 hdlbits（161/162 持平）验证。JSON 头部计数修复（`json.cpp`）为独立缺陷修复，无前向兼容性问题（旧归档无孤儿区间，头部==求和），随节点保留。
- **判定：REJECTED（机制性错误）**。锚定 M-fuse +15.00%（门 ≤−6%）∧ Host +9.05%（预算 +2%）∧ 语义门/构建门槛/hdlbits 全过——假设在机制层面不成立，按预注册条款证伪登记索引机制证伪表。最终性能如实登记 **58.201 s**（不更新当前最佳指针，指针保持 **NO00010 = 53.426 s**）。
