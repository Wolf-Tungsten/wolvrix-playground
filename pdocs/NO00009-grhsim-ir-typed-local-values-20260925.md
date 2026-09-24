# NO00009: unit 内窄值类型化局部变量提升——消除 cpu_local 字节帧的逐 op 内存往返（每 dynOp 指令密度主因子）

| 字段 | 值 |
|---|---|
| 父节点 | NO00004（当前最佳） |
| 角色 | 优化 |
| 状态 | REJECTED |
| 锚定指标 | M-idens = compute_task instr/cycle ÷ dynOps/cycle（基线 **3.863 instr/dynOp**） |
| 指标阈值 | M-idens 降 **≥8%**（≤3.554），且 dynOps 逐键一致（语义中性门） |
| 回退预算 | Host ≤ +2%（≤56.98 s）；等价/构建门槛不放宽 |
| RUN_ID | no00009_typed_local_20260925 |
| 工作区 | ptmp/no00009_typed_local_values_20260925/ |

## 基础选定（BASELINE）

- **父节点**：NO00004（当前最佳指针，GrhSIM-IR PGO 构建 Host 55.864 s）。当前 wolvrix `b335525`（= NO00004 的 `dc3e3cb` + NO00007 门控设施，`GRHSIM_CONE_GUARD` 默认关、门关与 NO00004 发射逐字节一致——NO00007 已验证），以其为实施基线，无迂回。
- **立项动机（为什么是这个方向）**：NO00008 因子表 F（闭合残差 0%）把 2.0× 指令差距**完全闭合于每单位工作指令密度**（ir 3.863 instr/dynOp vs gsim 0.452 instr/enode，比值 8.54×；粒度覆盖仅 4.28×），变化流密度（1.175×）与每激活工作量（0.456×）均非主因；方向排序第一即"每 dynOp 指令密度"。本节点对该主因内部的**可压缩构成**下手。
- **瓶颈证据（本节点立项勘察，生成代码 `ptmp/no00004_compiler_pgo_20260924/flow/model/` 实例 + 发射器 `wolvrix/lib/grhsim/backend/cpu_emit.cpp` + 反汇编普查）**：
  - 3.863 instr/dynOp 的单 task 实例解剖（task_1000 热 unit，490 条热指令/128 结果-op ≈ 3.8 条/op，与全局均值一致）：load 26.5% + frame/boundary store 12.1%（**内存往返合计 ~39% ≈ 1.5 条/op**）、ALU 34.5%、cmp/set 21.0%、分派+fanout 5–8%。
  - **承载形式是内存往返的结构来源**：unit 内中间值一律写入 `alignas(8) std::byte cpu_local[N]{}` 栈帧字节数组的常量偏移槽位（发射点 `cpu_emit.cpp:6033`；取值经 `cpu_at<T>(cpu_local,off)` = `reinterpret_cast`，choke point `value()` `cpu_emit.cpp:2892-2902`），消费者再从数组读回。`std::byte*` 可别名一切，阻碍编译器 SRA/寄存器提升；被切成 `cpu_helper_<id>_<i>(cpu_local,...)` 的 unit 因帧地址逃逸（`cpu_emit.cpp:6047`），其 frame 访问 100% 是真实内存往返，且 `cpu_local[N]{}` 零初始化在逃逸时成为真实 `pxor+movdqu` 清零开销（反汇编实例 12 处）。
  - 编译器已部分挽救（直线路径链的中间 store 可被消除），残余可压缩量即本节点的目标空间：实例普查 frame store 38 条 + spill reload（约占 load 的 1/4）≈ **0.5–0.6 条/op（占 3.863 的 13–16%）**。
  - 与 NO00006 证伪的兼容性：NO00006 证伪的是"缩小 supernode 粒度"（激活数 +60.6% 反弹）；本节点**不动分区/调度/激活/change-detect/boundary 形式**，只改 unit 内值的承载表达，dynOps 预期逐字节一致（与 NO00002 关闭文本共享同类：发射形式变化、语义中性）。
- **gsim 环比（科学问题：哪种映射特征导致逐 op 成本差异）**：gsim 的 super 内 enode 是表达式树节点，codegen 把整树内联为 straight-line C++，中间值为编译器临时（可驻留寄存器），实测 0.452 instr/enode；ir 的 unit 内值以字节 arena 槽位承载是本差距的具体映射特征。本节点即检验该特征的归因强度：若类型化提升后 M-idens 降幅 <门，说明残余差距不在值承载形式（编译器本已大部提升），转入证伪表。
- **基线测量（配置未变，复用归档值，不重跑）**：
  - GrhSIM-IR 当前最佳：Host **55.864 s**（NO00004，3 次有效均值，SD 0.270 s）；端点 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`。
  - gsim+PGO 锚点：Host **27.376 s**（3 次有效均值，SD 0.065 s）；端点 `238550/99998/100001/0x80000b40`。差距 2.041×。
  - dynOps = **99,479,933,605**（994,789.4/guest cycle；NO00001 M4 传递链锁定值，NO00008 复核当前代码态逐键一致）；activations 993,413,585；bodies 904,557,815；boundary 写 22,134,521,354、真变化 1,267,630,634。
  - compute_task = **3.843 M instr/cycle**（NO00005 M-attr，perf 任务归因链路已修复并双链路互证）⇒ M-idens 基线 = 3.843 M / 994,789.4 = **3.863 instr/dynOp**。
  - 静态值形态（NO00008 mix probe / 本节点勘察）：宽值（>64 位）结果仅占 0.84%（28,226/3.36M）⇒ >99% 的 unit-local 值可被 ≤64 位类型承载；1 位值占 op 多数（and 的 896,170/912,702 为 1 位）；cpu_local 帧均值 140 B、p50 101 B、max 4,168 B。
- **输入核对**（sha256，与 NO00001–NO00008 相同，输入未变）：
  - `testcase/xiangshan/ready-to-run/coremark-2-iteration.bin` = `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`
  - `testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so` = `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`
- **代码状态核对**：wolvrix `b335525`（工作区干净）；根仓库 `d58bcd2`（NO00008 提交）；xiangshan/reference 子模块不动。冻结面（GRH IR、GRH 已有 pass、XiangShan 与测试源码）零改动；改动仅限 GrhSIM-IR CPU 发射器（goal 文档允许修改 emit）。
- **资源配置**：与 NO00001–NO00008 一致：`XS_EMU_CPU=2`、`XS_EMU_THREADS=1`、`XS_NUM_CORES=1`、`XS_SIM_MAX_CYCLE=100000`、waveform/commit/RAM trace 全关；编译 `VM_BUILD_JOBS=32`（nproc=32）；测量时机器空载；逐次 `posix_fadvise(DONTNEED)` 驱页缓存。
- **计时边界与止损线**：
  - SV→C++ 生成 <1800 s（NO00004 归档 195.95 s 量级）；C++ 编译 <1800 s（PGO 三阶段合计 NO00004 归档 695.95 s 量级）；超限记 `TIMEOUT_KILLED`。
  - 生产仿真：比较值预选为 NO00004 归档均值 **55.864 s**，运行上限 **1.5× = 83.8 s**，超时记 `REGRESSION_KILLED`；动态统计（dynOps 核对）构建与诊断运行参照先例上限 300 s。
  - 等价性：ir 侧端点四字段精确匹配 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c` 且 DIFFTEST 无 mismatch，否则 `INVALID`（按实现瑕疵处理）。

## 假设提出（HYPOTHESIS）

- **假设**：unit 内窄值（≤64 位、非 Boundary、非 String、不跨 helper-chunk 边界、非地址逃逸）由 `cpu_local` 字节帧槽位承载改为**类型化 C++ 局部变量**（SSA 形式：body 顶部声明、定值点赋值、使用点直呼其名），可消除字节别名导致的 SRA 阻塞与帧逃逸内存往返，使每 op 的 frame store/reload 被编译器寄存器分配吸收——**M-idens 降 ≥8%**，且分区/调度/激活/change-detect/boundary/dynOps 全部不变（语义中性）。机制表述：3.86 instr/dynOp 中 ~1.5 条是内存往返，其中 frame 往返残余（编译器未能提升部分）~0.5–0.6 条是可压缩空间；类型化局部变量把"可被提升"的决定权从别名分析交还给显式 SSA 形式。
- **创新点**：本分支首个针对**值承载表达**（byte-arena slot vs typed SSA local）这一映射特征的单变量实验——直接检验 goal 科学问题中"表达/映射特征 → 逐 op 成本"的归因；与 NO00006（分区粒度）、NO00007（单位内输入精度）正交，两者证伪均不约束本机制（不动粒度、不动激活语义）。
- **微观指标与总目标的定量关系**：
  - **M-idens** = compute_task instr/cycle ÷ dynOps/cycle（NO00005 M-attr/M-vol 口径，perf 任务归因；基线 3.863）。与总目标关系：compute_task 占模型指令 81.5%（3.843/(3.843+0.520+0.174+0.171) M/cycle），M-idens −8% ⇒ 模型指令 ≈ −6.5% ⇒ CPI 不变下 Host ≈ −3.6 s 量级；gsim 环比口径为 0.452 instr/enode（NO00008 M-gwork），本指标即因子表 F 的 instr/work 行（ir 侧）。
  - **语义中性门**：dynOps 全键（evals/per_eval/totals/kind/sn 行）与归档（NO00008 复核的 `ptmp/no00006_supernode_granularity_20260924/dyn-old/logs/xs_wolf_grhsim_no00006_dyn_old_20260924.log`）**逐键一致**；任何差异 = 实现瑕疵（发射形式变化不产生计数差异）。
  - 辅助登记（不设门）：编译后 .text 尺寸、生成墙钟、PGO 三阶段墙钟、Host 6 次交替（3 新 3 旧）。
- **预注册**：
  - **测量方法与运行秩序**：①聚焦测试（hdlbits 抽样 + 既有 ctest）→ ②动态统计构建跑 100k，dynOps 与归档逐键比对 → ③PGO 生产构建（`make xs_wolf_grhsim_ir_emu_pgo`，与 NO00004 同 clang 三阶段流程）→ ④perf 任务归因测 compute_task instr/cycle（新旧各 1 次，M-attr 链路）→ ⑤3+3 交替 Host 复测（执行顺序 新-旧-新-旧-新-旧，逐次 posix_fadvise，`taskset -c 2`）。
  - **改善门槛**：M-idens ≤ **3.554**（3.863 × 0.92，降 ≥8%）。
  - **语义中性门**：dynOps 逐键一致 + 端点四字段精确匹配（见 BASELINE 止损线）。
  - **回退预算**：Host 新构建均值 ≤ **56.98 s**（+2%）；若 Host 改善则以秩次判据（全部 3 次新运行优于全部 3 次旧运行，n=3+3 等价 Mann-Whitney 单侧 p≤0.05）登记显著性。
  - **构建门槛**：生成 <1800 s、编译（PGO 三阶段合计）<1800 s。
  - **证伪标准**：M-idens 降 <8% 且归因显示编译器对 byte-frame 的既有提升已覆盖大部分往返（类型化增量 <门）→ 机制性错误（"值承载形式是 per-op 成本的可压缩主因"证伪），登记索引证伪表；实现瑕疵（dynOps/端点不一致、构建失败）回 IMPLEMENTED 修正重测。
  - **验收**：M-idens 达门 + dynOps 逐键一致 + 端点等价 + 构建门槛通过 + Host 在回退预算内。

## 代码实施（IMPLEMENTED）

优化节点，改动仅限 GrhSIM-IR CPU 发射器（goal 文档允许修改 emit）；冻结面（GRH IR、GRH 已有 pass、XiangShan/测试源码）、分区/调度/激活/change-detect/boundary 形式、帧 layout（方案 A：偏移与尺寸不动）全部不变。唯一改动文件 **`wolvrix/lib/grhsim/backend/cpu_emit.cpp`（+106 行，纯新增，无删改行）**：

1. **`planLocalValuePromotion()`**（新增，:2239-2313，构造期 `planConeGuards()` 后调用）：仿 `planComputeEdgeGuards` 的 task→word→unit 三层遍历建 unit 扁平 op 序（= 依赖序，def 先于 use）；chunk 划分取 `partition.attrs.helperChunks`（空则单 chunk fallback）；单遍扁平扫描记 def 位置（`model_.operands(op)` 覆盖 event_edges 尾部操作数），def 与任一 use 不同 chunk 即排除；**排除集**＝非 PartitionLocal、非两态标量 logic 1–64 位（复用 `isScalarLogic` 判定）、`readAliases_`/`staticScalars_`/`staticStrings_` 命中；防御性断言（fanout/portArm 命中、def-before-use 违例即 throw）；第二遍全局 use 复核（跨 owner 引用即降级回帧槽）。
2. **`value()`**（:2982-2983，+2 行）：static/alias 重定向之后、layout 槽位查询之前插入提升名查询，命中返回 `cpu_l<value.index>`（全局唯一名）。
3. **`emitPromotedLocals()`**（新增，:5842-5851）：逐值 `cppType(type)` 发射 `[[maybe_unused]] <type> cpu_l<index>{};`（bool/std::uint8_t/…/std::int64_t，不统一 uint64_t，保持符号语义与 codegen 质量）。
4. **声明发射点**（各 +1 行）：非切分 unit——task body 帧声明/string 槽之后、`emitComputeGuardLocals` 之前（:6159）；切分 unit——各 helper 定义体 `emitBufferLocals` 之后（:6194），只声明本 chunk 提升值。helper 签名不变。
5. **成员**（:6250-6253）：`promotedLocalChunk_`（value.index→chunk 序号）、`promotedLocalDecls_`（unit.index→per-chunk 值索引，按 def 序）。
6. **门控（TESTED 负向后追加，设施留存）**：`planLocalValuePromotion()` 开头 `if (!std::getenv("GRHSIM_PROMOTE_LOCALS")) return;`（:2243，默认关，同 GRHSIM_CONE_GUARD 模式）；门关时 chunk 表全-undef、decls 表为空，`value()` 走帧槽路径、`emitPromotedLocals` 空转，发射回到改动前形态。

- **语义约束**：表达式文本（trunc/cast/helper 调用）逐字节不变，仅值引用形式从 `cpu_at<T>(cpu_local,off)` 变为变量名 + 新增顶部声明；cone-guard 路径由 downward-closure 保证"use 发射 ⇒ def 发射"，`[[maybe_unused]]`+`{}` 覆盖"声明未用"；GRHSIM_CONE_GUARD 门关闭路径行为不变。
- **与父节点差异**：生成 C++ 中 PartitionLocal 窄值的引用形式（预期 dynOps 逐键一致）；发射器无新增命令行/开关（提升恒启用，属发射形式演进）。
- **聚焦测试（全部通过）**：
  - `make test_grhsim_cpu_emit`：**一次通过，零期望更新**（精确文本期望均为 Boundary/cpu_bnd_ 文本，不受提升影响；多处 fixture 以 ASan/UBSan 编译并真实执行生成代码，语义被执行覆盖）；`GRHSIM_CONE_GUARD=1` 变体亦通过（cone-guard run 与 `cpu_l` 声明同 body 共存）。
  - `make test_grhsim_cpu_schedule test_grhsim_cpu_mapping`：通过。
  - `make run_hdlbits_test DUT=001`：通过；`run_all_hdlbits_grhsim_ir_tests`：**161/162**（DUT=105 失败经 stash 复跑确认为基线预存问题——used-bits pass 上游 dangling value，与本改动无关，登记待另案排查；DUT=056 首批 SIGBUS 为并发资源争抢，独占复跑通过）。
  - 生成文本人工抽查（非切分/切分两形态）：顶部声明、定值直呼其名、帧原样保留、helper 体内只声明本 chunk 值，均符合设计。

## 结果测试（TESTED）

**判定：REJECTED（机制性错误）**——微观指标 M-idens 未达预注册门槛且方向相反（+3.85% vs 要求 −8%）；语义中性门与构建门槛全部通过；Host 回退 1.48%（在 +2% 预算内但无济于事）。定量复盘见下「负向结果复盘」。

- **构建门槛（通过）**：全流程 SV→C++ 生成 810.95 s（<1800 s；NO00004 归档 791.31 s，+2.5% 为声明文本增量）；PGO 三阶段编译 673.02 s（<1800 s；NO00004 归档 695.95 s）。**mapped checkpoint 与 NO00004 归档逐字节一致**（发射侧改动的直接证明）。
- **流程纯净性（bench 对照有效性）**：新 flow/model 与 NO00004 归档 model 的逐文件差异集（3,895 个）**精确等于**含 `cpu_l` 声明的文件集（3,895 个）——commit 任务等其余全部文件逐字节一致，3+3 对照只含本节点单变量。
- **语义中性门（通过）**：动态统计构建 100k 运行，`[grhsim-dyn]` **32,145 键与 NO00006 dyn-old 归档逐字节一致**（dynOps 99,479,933,605 锁定）；端点四字段精确匹配 `240349/99996/100001/0x80000c0c`，DIFFTEST 无 mismatch。
- **微观指标 M-idens（未达门，方向相反）**（M-attr 链路，新旧同窗口各 1 次；perfstat 3 跑 instr spread ~1.4e-6，计数差非噪声）：

  | 侧 | instructions | CPI | compute 份额 | compute instr/cycle | M-idens |
  |---|---|---|---|---|---|
  | 旧（NO00004 归档二进制，本窗口复测） | 4.793e11 | 0.5761 | 80.13% | 3,840,551 | **3.8607** |
  | 新（本节点 PGO） | 4.930e11 | 0.5734 | 80.90% | 3,988,062 | **4.0090** |
  | Δ | **+2.86%** | −0.47% | +0.77pp | **+3.84%** | **+3.85%（门：≤3.554 / −8%）** |

  旧侧复测 3.8607 对归档基线 3.863 偏差 −0.06%（口径一致）；次级效应：L1-icache-miss **+16.8%**、iTLB +3.3%（.text +2.45% 的前端代价）。
- **最终性能 3+3 交替复测**（执行顺序 新-旧-新-旧-新-旧，逐次 posix_fadvise，`taskset -c 2`）：

  | 侧 | 3 次 Host s | 均值 s | SD s |
  |---|---|---|---|
  | 旧 | 56.109 / 56.671 / 55.316 | 56.032 | 0.681 |
  | 新 | 57.021 / 57.015 / 56.551 | **56.862** | 0.270 |

  Δ = **+1.48%（回退，预算 +2% 内）**；Mann-Whitney U=8，单侧精确 p=0.95（反向），秩次判据不通过；Cohen d=1.60、Cliff δ=0.78。旧侧窗口均值 56.032 对归档 55.864 偏差 +0.3%（机器漂移容忍内）。
- **负向结果复盘（REJECTED 必要组成；全量数据 `ptmp/no00009_typed_local_values_20260925/taskA_attribution.md`、`taskA_census_{old,new}.json`）**：
  对两 PGO 二进制全部 4,439 个同名 cpu_task/cpu_helper 函数做反汇编分类普查（覆盖 perf 样本 90.9%）：静态指令 22,096,998 → 22,675,605（**+578,607 / +2.62%**），与动态 +2.86%、.text +2.45% 同源。top-20 热函数（样本 ~14%）新旧近乎逐字节一致；增长全在中尾部（2,666 函数变大，携带 59.0% 样本）——增长就在热路径上，冷拷贝膨胀证伪。
  类别差值（静态全量）：**cmov +156,548（+39%）、SSE +152,537（+13.4%）**、cmp/test +118,038、branch +110,854、load +85,341、mov_rr +74,942、零写 +61,176、setcc +61,244；抵消项 alu_mem −76,727（折叠分解为 load+op）、非-cmov 标量 alu −213,574；rsp 引用合计 +184,191。机制归因三层：
  1. **PHI 合并物化**：`cpu_l{}` 的零 PHI 输入使条件 def 在合并点物化为 `mov $0+cmovne` 选择序列（实例 task_2204 零写 2→271，其中 268 条该形态、逐块散布）；**帧形态下内存槽本身就是合并点，合并免费**。
  2. **SLP 自动向量化走火**：195 个函数从 0 SSE → 共 110,158 条 SSE；帧形态 `std::byte[]+cpu_at<>` 的不透明访问抑制了 clang SLP，干净 SSA bool/uint8 链暴露可向量形态触发打包走火（实例 task_3380：847→2,456 条、0→722 SSE，`pmovmskb` 后逐位提取再溢出，远超标量链成本）。
  3. **寄存器分配压力**：更多活值竞争使 RA 驻留减少（实例 task_731：栈槽数相同 227→227，栈触碰指令 4,970→7,530；基址指针溢出后每两条指令 reload 一次），折叠形态部分分解（alu_mem −76,727 对 load +85,341）。
  **机制性判定**：cpu_local 字节帧形态并非"未优化基线"——它无意中给 clang 三层保护：**内存槽即 PHI 合并点**（条件 def 免 cmov 物化）、**不透明字节访问抑制 SLP**（免 bool 链打包走火）、**小帧集中驻留 L1 且不占寄存器**（免 RA 压力）。类型化提升把 250 万个值强制转为干净 SSA 标量，同时剥夺三层保护，使 clang 的 PHI 物化/SLP/RA 在数万指令级超大函数体上系统性做出更差决策。**"SSA 必优于帧"的前提在该编译器+代码形态下不成立**——NO00008 因子表 instr/work 8.54× 差距**不能**归因于值承载形式的可压缩空间；语义全对（dynOps 逐键一致、端点精确、checkpoint 一致）、提升转换忠实、帧 layout 未动 ⇒ 非实现瑕疵，判**机制性错误**。
- **设施留存**：提升设施门控化为 **`GRHSIM_PROMOTE_LOCALS`**（默认关；`planLocalValuePromotion()` 开头早退，同 GRHSIM_CONE_GUARD 模式）。门关 `make test_grhsim_cpu_emit` 通过、门开变体通过（设施可用）；**门关重发射与改动前逐字节一致**（stash 对照：同 checkpoint 同 reemit 路径，`diff -rq` 全模型无差异；另证：本节点 flow 与 NO00004 归档 model 的差异文件集精确等于含 `cpu_l` 声明的文件集 3,895 个，commit 任务等其余文件逐字节一致）。
- **当前最佳指针**：不动（NO00004 = 55.864 s，如实登记）。
