# NO00018: 生产二进制动态指令类别归因——地址级采样 × 反汇编分类，确定性计数锚定闭合（诊断）

| 字段 | 值 |
|---|---|
| 父节点 | NO00015（当前最佳） |
| 角色 | 诊断 |
| 状态 | ACCEPTED（修订口径 G1–G4 全过；首轮原始门 G2/G3/G4 FAIL 已机制归因并登记修订 1/2/3，原始门并列留存；指针不动 NO00015 52.672 s） |
| 锚定指标 | **M-iclass**（动态指令类别份额表：逐类周期份额 + bootstrap 95% CI）；**M-fhot**（函数级动态份额表）；**M-coldbias**（闭式静态×fires 口径对采样口径的逐类比值） |
| 指标阈值 | G1 样本有效性（合并 ≥100K 样本、地址映射覆盖 ≥99%）；G2 三次运行逐类份额一致（≥1% 的类两两 \|Δ\| ≤ max(0.5pp, 2×SE)）；G3 闭合（cpu_task+helper 周期份额对既有互证口径 91.0–91.5% 偏差 ≤1.0pp）；G4 确定性锚定（heap 目的操作数 or 类动态 instr/cycle ∈ [100K, 250K]，锚 123.0K arm/cycle）——**首轮失败后修订 1/2/3 已登记（见"门槛修订登记"节），修订门为准、原始门并列留存** |
| 回退预算 | 无性能语义改动；当前最佳指针不动（NO00015，52.672 s）；回退预算 N/A |
| RUN_ID | no00018_iclass_20260926 |
| 工作区 | ptmp/no00018_iclass_20260926/ |

## 基础选定（BASELINE）

- **父节点**：NO00015（当前最佳指针，GrhSIM-IR PGO 构建 Host 52.672 s，wolvrix `61b092e` + 根仓库 `4e4e40f`）。NO00016/NO00017 均未移动指针且零生产语义改动（fold-residue 门关 = NO00015 管线逐字节；NO00017 仅分析脚本）。本节点为诊断节点，零语义改动，分析对象取 NO00015 归档（生产 checkpoint、PGO 二进制、dyn run1 日志），无迂回。
- **立项动机（为什么是这个诊断）**：NO00017 机制证伪登记明确指定"归因须走动态测量路径（perf record 符号采样或 PGO 块计数）"。本分支既有归因全部止于**函数级**（NO00005 M-attr、NO00009/NO00016 perf record 符号份额），结论是分布平坦、无单点热点；而 NO00016（成本模型误差 65×）与 NO00017（线性可加性证伪）连续负向的直接教训是：**静态存在 ≠ 动态执行**，静态普查被冷块/上下文塌缩混淆，不能用于池定价。本节点把归因推进到**逐指令类别**粒度（地址级采样 × 反汇编分类），并以确定性计数锚定闭合，给出唯一可信的候选池动态定价。
- **基线测量（配置未变，复用归档值，不重跑）**：
  - GrhSIM-IR 当前最佳：Host **52.672 s**（NO00015，3 次有效均值，SD 0.015 s）；端点 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`。
  - gsim+PGO 锚点：Host **27.376 s**（SD 0.065 s）；差距 **1.924×（~25.3 s）**。
  - 指令归因（NO00016 基线 perfstat）：总 **3,949,943.3 instr/cycle**；compute 80.35% / commit 11.61% / evaluator 3.38% / infra 2.61%。
  - 动态聚合（NO00015 dyn run1 归档，确定性）：boundary 检测写 **209,872.37/cycle**；簿记计数（NO00017 G1 验证）：检测 209.8K / 组守卫 107.0K / 置位臂 123.0K per cycle；publish：pub_calls 401,257、pub_pending 27,779,013（**277.8/cycle**）、pub_changes 17,258,455（**172.6/cycle**）per run。
  - 逐 kind 执行计数（NO00017 交付）：and 259,568.1、or 214,756.1、mux 115,666.2、eq 68,485.7、bitSelect 47,427.6、concat 42,177.9、sliceStatic 35,752.0、state.read 33,758.2、add 30,930.4 exec/cycle（全表见其 summary.json）；位宽执行份额 w1 64.4% / w2_64 32.5% / w65p 0.25%。
- **输入核对（sha256，与 NO00001–NO00017 相同，输入未变）**：
  - `testcase/xiangshan/ready-to-run/coremark-2-iteration.bin` = `c764afb8…83e8e`
  - `testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so` = `094c1c4…ff9e`
- **代码状态核对**：wolvrix `dfa59d2`、根仓库 `9a7bbe6`（均为最新提交，工作区干净）。冻结面（GRH IR、GRH 已有 pass、XiangShan 与测试源码、reference/gsim）零改动；本节点改动仅限根仓库分析脚本 + Makefile 目标 + 本报告。
- **归档产物核对（数据链路全部在位）**：
  - 生产 PGO 二进制：`ptmp/no00015_edge_complete_20260925/flow/emu/emu`（PGO 三阶段 phase-3 产物）。
  - 生产 checkpoint：`ptmp/no00015_edge_complete_20260925/flow/xiangshan_grhsim_ir.json`（1.4 G，含 partition/schedule/dataLayout）。
  - dyn 归档：`ptmp/no00015_edge_complete_20260925/run1/logs/xs_wolf_grhsim_no00015_edgecomplete_run1_20260926.log`（sn/kind/totals/vchg 行全，确定性计数）。
  - 既有设施：`scripts/grhsim_native_work_compare.py`（NO00005 perf record/stat 通路：`perf record -F 999 -e cycles:u`，make 目标 `run_xs_wolf_grhsim_ir_emu XS_GRHSIM_IR_BUILD=<flow>` + `XS_EMU_PREFIX` 注入）；`scripts/grhsim_kind_cost_census.py`（NO00017 checkpoint↔任务连接镜像，本节点 M-coldbias 复用其 task→unit 与 helper 归属函数）。
- **BASELINE 静态复核（本节点立项前对生产二进制的静态普查，工作区 `disasm_full.txt` 866 MB objdump 全量 + `static_mix.json`；4,677 函数 = 4,439 task + 238 helper，静态总量 24,187,223 条指令）**：

  | 类别 | 静态条数 | 份额 |
  |---|---|---|
  | mov（全部） | 8,409,312 | 34.77%（其中非栈内存操作数 15.74%） |
  | and | 1,847,586 | 7.64% |
  | or + orb | 2,443,008 | 10.10%（orb 带内存操作数 822,129 = fanout 置位臂形态） |
  | movzbl/movzwl | 1,401,676 | 5.80% |
  | cmp + cmpb + test | 2,234,566 | 9.24% |
  | j*（branch） | 2,132,566 | 8.81% |
  | lea | 540,764 | 2.24% |
  | SSE（movups/movdqa/movdqu/movaps/movd/por/pxor 等） | ~850,000 | ~3.5% |
  | setcc（sete/setne/…） | 674,642 | 2.79% |
  | 宽度掩码（and imm=2^n−1 非原生长度） | 420,776 | 1.74%（w1 131,594 / w2 66,294 / w9 44,693 / w6 35,986 / w3 29,416 / w4 28,795 / w5 26,813 / w7 23,242 / 其余长尾） |
  | 栈溢出/重填（%rsp/%rbp 相对 mov） | 3,286,116 | 13.59% |

  静态复核直接排除/降权三个候选假设（静态池存在但被冷块或编译器混淆，正是 NO00016/NO00017 证伪的定价方式）：
  1. **宽度掩码消除**：静态上限仅 1.74%，且 w1 掩码部分为真实 bitSelect 语义（非冗余），可消除子集估计 <1%——池过薄，不立优化节点。
  2. **帧零初始化选择化**：热函数 cpu_task_480 的 77 B 帧零初始化在二进制中已被 clang DSE 完全消除（逐指令核对无零存）；SSE 块操作集中于冷函数（cpu_task_3946 单函数 56,320 条 SSE vs w65p 动态执行份额仅 0.25%）——静态 SSE 池 3.5% 绝大部分是冷块，热残余未知但量级存疑。
  3. **publish 循环 memcmp 专门化**：动态实测 pub_pending 仅 277.8/cycle（dyn 计数器），publish 相位总份额 ~1.7%——静态怀疑的"memcmp 23,724/cycle"不构成池。
- **资源配置**：与 NO00001–NO00017 一致（`XS_EMU_CPU=2`、`XS_EMU_THREADS=1`、`XS_NUM_CORES=1`、`XS_SIM_MAX_CYCLE=100000`、trace 全关、逐次 posix_fadvise 驱页缓存、机器空载）；采样侧 `perf record -F 999 -e cycles:u`（生产口径 difftest 开启，与 NO00005/NO00016 同法）。
- **计时边界与止损线**：无生成/编译/仿真门槛（诊断节点不触发生产流程，先例 NO00008/NO00012/NO00017）；采样运行仿真墙钟 cutoff = 1.5 × 52.672 = **79.0 s**（超出记 REGRESSION_KILLED）；分析脚本单次全量预期 <30 min 墙钟。

## 假设提出（HYPOTHESIS）

- **假设（诊断性）**：生产 PGO 二进制的动态周期可在**逐指令类别**粒度经地址级采样（perf record IP）× 反汇编机械分类可靠归因；归因表与既有函数级/相位级口径闭式互证（G3），并与确定性动态计数锚定一致（G4）。该表把 NO00008 因子表的"每单位工作指令密度 8.54×"从函数粒度推进到指令类别粒度，给出后续优化节点候选池的动态定价——静态口径已被本节点 BASELINE 复核实证会被冷块/编译器塌缩混淆（NO00016 65×、NO00017 线性可加证伪的同源教训），动态类别表是唯一可信的定价依据。
- **创新点**：① 本分支首个**地址级**（逐指令）动态归因（此前全部止于函数级）；② 首个逐类**冷块偏差**量化 M-coldbias（闭式静态×fires 口径对采样口径的逐类比值，直接测量"静态存在但动态不执行"的类别结构——NO00017 证伪条目的定量对应物）；③ 首个确定性计数锚定的采样闭合（heap 目的操作数 or 类 ↔ 置位臂 123.0K/cycle 确定性计数）。
- **瓶颈证据（本分支实测 + 本节点 BASELINE 复核）**：NO00008 因子表（密度 8.54× 唯一主因子）；NO00005 M-attr 函数级平坦分布（单任务 ≤1.35%）；NO00016/NO00017 静态定价连续证伪；BASELINE 静态普查三项排除（上文）；簿记确定性计数 440K events/cycle（NO00017）对 gsim 监测比较 87,965/cycle（NO00008）= 残余 2.39× 结构差距未定价值归属。
- **微观指标与总目标的定量关系**：
  - **M-iclass**（锚定）= 逐指令类别动态周期份额表（17 个机械类，定义下述）。与总目标关系：类份额 × 52.672 s ≈ 完全消除该类指令的 Host 上界——这是全部后续优化节点的**池定价表**；检测/簿记类份额给出 NO00013/14/15 去监测序列残余空间（209.9K wr/cycle 对 gsim 88.0K）的真实指令权重，栈流量份额给出寄存器压力（NO00009 三层保护第③条）的动态实证，掩码/SSE 份额终裁 BASELINE 复核的两项存疑池。
  - **M-fhot**（锚定）= 函数级动态份额表（4,677 函数 + 框架/nemu/libc 桶）。与总目标关系：复核 NO00005 长尾结论在当前最佳构建上是否仍成立，并定位类别归因的函数分布（类别 × 函数二维表的行边际）。
  - **M-coldbias**（锚定）= 逐类 `静态条数 × 确定性 fires` 口径份额对采样份额的比值。与总目标关系：量化"静态×fires"定价在各指令类别上的偏差倍率——后续节点若用闭式静态口径预注册微观指标，该表给出逐类校正因子（NO00016 0.043 instr/exec、NO00017 +88.8%/+23.3% 高估的类别分解）。
- **预注册**：
  - **测量方法与运行秩序**：① 3 次 perf record 采样运行（生产口径：difftest 开启、同一 NO00015 PGO 归档二进制、逐次 posix_fadvise、`taskset -c 2`、`-F 999 cycles:u`；采样运行的 Host 时间仅登记不充当基线）→ ② `perf script -F ip` 提取采样地址 → ③ objdump 全量反汇编机械分类器（类别清单固定如下）→ ④ 逐类份额 + 逐次份额 + bootstrap 95% CI（固定种子 20260926，类别份额多项分布 10,000 次重采样）→ ⑤ 闭式口径（dyn run1 逐 sn fires × 静态逐函数类计数，task 级聚合，helper 按名并入）→ ⑥ G1–G4 判定 → ⑦ 交付表 + 报告整理。
  - **类别清单（预注册固定，objdump 助记符 + 操作数形态机械判定）**：`mask_and`（and 且立即数 = 2^n−1 且 n∉{8,16,32,64}）、`logic`（and/or/xor/not/test 之外其余布尔运算；test 归 cmp）、`flag_rmw`（or/and/add 以堆内存为目的操作数，即 flags 置位/清零惯用法）、`cmp`（cmp/cmpb/test）、`setcc`（set*）、`branch`（j* 全部）、`cmov`、`shift`（shl/shr/sar/rol/ror）、`stk_ld`、`stk_st`（%rsp/%rbp 相对寻址的读/写）、`heap_ld`、`heap_st`（其余内存操作数读/写，含 movz）、`mov_rr`（纯寄存器 mov）、`sse`（movups/movaps/movdqa/movdqu/movd/movq-sse/por/pxor 等 SSE/AVX）、`lea`、`call`、`arith`（add/sub/imul/idiv/inc/dec）、`misc`（其余全部，18 类含 misc）。
  - **G1 样本有效性**：3 次运行合并样本（cpu_task/cpu_helper/cpu_publish/cpu_direct_state_changed/eval 等模型函数内）≥ 100,000；采样地址 → 反汇编指令映射覆盖率 ≥ 99%（未命中计入 misc 单独登记）。
  - **G2 运行间一致性**：份额 ≥1% 的类别，三次运行两两份额差 ≤ max(0.5pp, 2×合并 SE)。
  - **G3 闭合**：cpu_task + cpu_helper 合并**周期份额**对既有互证口径偏差 ≤ 1.0pp——参照系 = NO00005 同法 perf record 函数级口径 91.03%（compute 80.18 + commit 10.85）与 gperftools 口径 91.47%（80.51 + 10.96）的双链路互证区间 [90.5%, 92.0%]。
  - **G4 确定性锚定**：`flag_rmw` 类动态指令/cycle ∈ [100K, 250K]——确定性锚 = 置位臂执行 123.0K/cycle（NO00017 G1 验证计数）+ commit/publish 侧同形态 RMW（pub_changes 172.6/cycle × 每 publish 扇出数，量级 ≤ 数十 K）；区间按 CPI 中性的周期份额→指令份额换算放宽。
  - **G5（辅助登记，不设门）**：M-coldbias 逐类比值表；M-fhot Top Pareto 对 NO00005 长尾结论（单任务 ≤1.35%）的复核；采样 skid 对类别边界的敏感性（相邻指令异类比例）仅登记。
  - **证伪标准**：G1/G2 失败 → 实现瑕疵，修正后重跑（同一节点内）；G3 或 G4 失败且偏差不可归因于已登记口径差异（周期份额 vs 指令份额的 CPI 非均匀性、采样 skid、计数器口径边界）→ 地址级采样归因方法在本二进制形态下不适用，节点 REJECTED 并登记机制证伪表。
  - **验收（诊断节点）**：G1–G4 全过 + M-iclass / M-fhot / M-coldbias 三表交付（含候选池动态定价解读）+ 当前最佳指针不动（52.672 s 如实登记）。
  - **构建/性能门槛**：本节点无生产构建、无 100k 新基线仿真、无 3+3 Host 复测（零性能语义改动，先例 NO00008/NO00012/NO00017）；采样运行仅作诊断，端点四字段与 difftest 仍需 VALID（作废补跑条款同计时类测量）。

## 门槛修订登记（2026-09-26，首轮 G2/G3/G4 失败之后、修订复测之前登记）

首轮复测 G1 PASS、G2/G3/G4 FAIL（数值见 TESTED 首段）。三条修订均为**机制性口径修正**（参照系错误/形态分解缺失/方差模型误设），非迁就数值；原始门与修订门的双向结果均在 TESTED 节如实并列。修订登记先于修订口径下的任何门判定。

- **修订 1（G3：参照系与同量对齐）**：
  - 原门缺陷：参照区间 [90.5%, 92.0%] 来自 NO00005 时代构建的函数级互证（NO00004 PGO 谱系之前）；其后 NO00010/NO00013/NO00014/NO00015 连续改动发射代码（任务切分、组守卫、commit 路径、边沿完备），跨构建参照违反 goal 文件"配置变化时重建基线"规则。
  - 修订参照系：**同一二进制**（NO00015 PGO 归档 `flow/emu`）的相位计时——补采 perf4/perf5 两次运行（同一生产口径 + `EMU_RUNTIME_PROFILE=1`；profile 开销实测 Host 53,343/53,168 ms 对无 profile 53,372/52,687/53,335 ms，扰动 ≤1.3%，忽略）。
  - 同量对齐（发射代码核对，`cpu_emit.cpp` 相位发射点 + `flow/model/grhsim_SimTop.cpp:469425/470155/470157` tick 位置）：compute 段 = compute task（0–3950）派发+本体，commit 段 = commit task（3951–4439）派发+本体，publish 段 = `cpu_publish()`；派发测试/handoff 在 eval 符号内（样本桶 simtop_other）。故样本侧对应量 = **(task+helper+simtop_other)/全部样本**，计时侧 = **(compute_ns+commit_ns+publish_ns)/eval_ns × eval_ns/Host**。
  - 修订门：两侧差 ≤ **1.0pp**。证伪含义不变：修订后仍大幅失败 → 地址级采样归因方法证伪。
- **修订 2（G4：形态分解区间）**：
  - 原门缺陷：锚 123.0K arm/cycle 是**全部**置位臂形态的确定性计数（NO00017 G1），而 `flag_rmw` 类只覆盖**堆内存目的操作数 OR** 一种发射形态；原区间下限 100K 是未做形态分解的圆整数。
  - 形态普查（`arm_form_census.py` × flow-dyn 4,439 task 源 × dyn run1 逐 sn `grp` fires 加权，确定性连接无采样，产物 `arm_form_census.json`）：静态站点 heap_flags 505,814 / heap_pflags 121,687 / local(`cpu_active_word|=`) 27,303 / writeback 3,952；fires 加权动态份额 77.44% / 18.17% / 3.88% / 0.51% → 内存目的 OR 形态合计 **f_mem = 96.12%**（task 粒度加权与静态几乎一致，形态间动态偏斜可忽略）。
  - 修订门：flag_rmw ∈ **[123,000 × f_mem × 0.80, 250,000] = [94.6K, 250K]**。0.80 = 守卫选择率容差：普查按 unit body fires 加权，站点实际执行还需 `if(cpu_changed_k)` 守卫通过（聚合量级：加权站点总额 178.2 万/cycle 对锚 12.3 万/cycle ⇒ 守卫通过率 ~7%）；三种形态守卫结构相同故份额一阶中性，残余相关性由该容差吸收（严于 NO00017 n_arm 编译系数 CI95 相对半宽 ±39%）。
  - 残差登记（发现 F-arm-residual）：测量 100.0K 对形态修正期望 118.2K = −15%，指向 ① changed 守卫通过率与形态相关，或 ② 锚的图级口径按行计数而非按守卫通过计数——列入后续节点候选线索。
  - 旁证：flag_rmw 逐次份额 2.613%/2.543%/2.438%，运行间相对散布 ±3.5% ≈ ±3.5K instr/cycle——首轮缺口 7.1 instr/cycle 比测量自身运行级噪声小约两个数量级。
- **修订 3（G2：散布模型与运行数）**：
  - 原门缺陷：`两两|Δ| ≤ max(0.5pp, 2×SE)` 中的 SE 是**采样噪声**（多项二项），但实测 branch 最坏对 Δ=0.515pp 对应 z≈3.1（SE≈0.17pp），证明存在**真实运行级方差**（逐次独立 ASLR 进程 + 采样相位与循环相位混合），原门混淆两种方差来源。
  - 修订：运行数 3 → **5**（perf4/perf5 已按同一生产口径补采，端点四字段与 difftest VALID）；门改经验散布模型：份额 ≥1% 的类，5 次逐次份额**样本 SD（n−1）≤ 0.5pp**。

## 代码实施（IMPLEMENTED）

- `scripts/grhsim_dyn_iclass_profile.py`：纯函数与编排分离。分类器 `classify_insn` 按预注册固定 18 类机械判定（先匹配先生效；`mov` 族加载限定 mov/movz*/movs*（movss/movsd 归 sse），`mov_rr` 严格寄存器到寄存器（imm→reg 归 misc），push/pop/pause 不受 sse p 前缀规则影响，`leave` 不归 lea）。反汇编解析 `parse_disasm` 同名符号多段合并、逐函数 (地址数组, 类 id 数组, 18 类静态计数)；分类结果按指令文本 memoize。perf 提取 `perf script -F dso,ip --ns` 子进程。**地址偏移自动校正（逐次）**：emu 为 PIE，且 3 次采样是 3 个独立 ASLR 进程、各有 load bias——`estimate_offset` 取该次最密集样本 IP 为锚，枚举低 12 位相同的指令 VMA 候选偏移（偏移必页对齐），以去重样本 IP 的精确指令地址命中数评分取最大（numpy searchsorted，确定性 tie-break），再经函数区间覆盖率验证。函数归属桶 task/helper/simtop_other/emu_other/dso:*/unknown；c++filt 批量管道 demangle。G1–G4 门、G5 登记表（M-coldbias 逐类比值、M-fhot Top30 + ≥0.1% 函数数、skid 相邻指令异类比例、逐类 bootstrap 95% CI：固定种子 20260926、合并类向量多项重采样 10,000 次）。checkpoint task→unit 映射缓存为输出目录 `task_units_cache.pkl`（键 = 路径+mtime+size；复用 `compute_task_units`/`load_dyn_fires`）。输出 `summary.json`/`summary.md`/`iclass_per_run.tsv`，同一输入两次运行逐字节一致（真实数据已验证）。
- `scripts/test_grhsim_dyn_iclass_profile.py`：30 个 unittest 用例（分类器逐类、操作数解析、反汇编多段合并、perf 文本解析、偏移估计（零偏移/平移/空）、逐样本聚合与 skid、G2 过/不过、bootstrap 确定性、coldbias 闭式、helper 并入、端到端两次运行逐字节一致、逐次 ASLR 偏移恢复），全部合成小样本。
- Makefile：`analyze_grhsim_dyn_iclass` / `test_grhsim_dyn_iclass`，`GRHSIM_ICLASS_*` 变量（disasm/emu/perf 根/checkpoint/dyn 日志/输出目录）含 NO00018 默认路径。
- 口径取舍：① load bias 逐次估计（ASLR），首次实现曾用全局合并锚+页级 FFT 相关，因三次运行基址不同且 .text 页连续导致相关峰平坦而失败，改为逐次锚点对齐后以 perf 自身符号化验证（perf1 bias=0x5fcf8a661000，与 `cpu_task_1` 符号核对一致）；② emu 内未映射样本归 misc 并单独登记（实测 0）；③ G4 换算按预注册 = flag_rmw 占全部样本份额 × 3,949,943.3（全进程口径）；④ M-coldbias 闭式分子仅覆盖 compute task（3950 个；commit task 489 个无 sn 行，已在 summary 注明），helper 静态计数按名并入所属 task，orphan helper = 0。
- **修订实施（2026-09-26，对应"门槛修订登记"）**：脚本实现修订门——`gate_g2_sd`（≥1% 类逐次份额样本 SD(n−1) ≤ 0.5pp）、G3 同构建相位闭合（`--phase-csv` 输入 `phase_ref.csv`，样本侧 task+helper+simtop_other 对计时侧 (compute+commit+publish)/Host，门 \|Δ\| ≤ 1.0pp；缺参照时 fail-closed）、G4 形态分解区间（常数 `G4_ANCHOR_ARMS=123,000`、`G4_F_MEM=0.96119`、`G4_GUARD_ALLOWANCE=0.80`、上限 250K）；原始三门作为 `informational.*_orig` 并列输出（不参与判定）。Makefile 目标扩为 5 次 `--perf` + `--phase-csv`（`GRHSIM_ICLASS_PHASE` 变量）。新增产物：`run_perf.sh`（采样运行编排，含逐次 posix_fadvise 与 `EMU_RUNTIME_PROFILE` 开关）、`phase_ref.csv`（perf4/5 相位计时提取）、`arm_form_census.py`/`arm_form_census.json`（置位臂形态 fires 加权普查，sn→task 映射经 flow-dyn 任务源内 `cpu_dyn_sn_grp[]` 计数器建立）。单测 30 → 33（G2-SD 成败两路、相位参照解析、修订 G3 过/不过/缺参照三路、G4 修订区间常数）。

## 结果测试（TESTED）

### 首轮复测（3 运行，原始预注册门槛）

- 单测：`make test_grhsim_dyn_iclass` → Ran 30 tests, OK。
- 全量分析：`make analyze_grhsim_dyn_iclass`（产物在 `ptmp/no00018_iclass_20260926/analysis/`；两次运行 summary.json 逐字节一致）。合并样本 158,720（emu 156,776，地址映射覆盖率 **100.0000%**，unmapped 0，inexact 0；三次 load bias 分别为 0x5fcf8a661000 / 0x5a1319d2e000 / 0x609c3a61f000，精确指令命中 46103/45420/46165 = 100%）。
- **G1 PASS**：模型函数样本 156,385 ≥ 100,000；覆盖率 1.0000 ≥ 0.99。
- **G2 FAIL（边际）**：14/15 个 ≥1% 类通过；`branch` 最坏对（perf2 15.516% vs perf3 15.001%）差 0.515pp > 0.500pp 上限（超出 0.015pp）。
- **G3 FAIL**：cpu_task+cpu_helper 合并份额 **93.82%**（逐次 93.89/93.79/93.79%），高于互证区间 [90.5%, 92.0%] 上限 +1.82pp（参照系为 NO00005 时代非 PGO 构建；当前为 NO00015 PGO 构建）。
- **G4 FAIL（边界）**：flag_rmw = **99,992.9 instr/cycle**，距下限 100K 差 7.1（0.007%）；份额 2.532% × 3,949,943.3。

### 门槛修订（2026-09-26 登记，见上文"门槛修订登记"节）后修订复测（5 运行）

- **修订采样运行 perf4/perf5 VALID**：与 perf1–3 同一生产口径 + `EMU_RUNTIME_PROFILE=1`；端点四字段五次完全一致（`instrCnt=240349、cycleCnt=99996、IPC=2.403586、guest=100001`、退出 PC `0x80000c0c`），difftest 开启且无 mismatch（运行以 CYCLE_LIMIT 终止为本工作负载正常终态，与 NO00015 端点口径一致）；profile 扰动实测 ≤1.3%（Host 53,343/53,168 ms）；相位行齐全（`phase_ref.csv`）。
- 单测：`make test_grhsim_dyn_iclass` → **Ran 33 tests, OK**（新增 G2-SD/相位参照/修订 G3 成败两路/修订 G4 区间常数用例）。
- 全量分析（5 运行，`make analyze_grhsim_dyn_iclass`）：合并样本 **264,733**（emu 261,292，覆盖率 **100.0000%**；五次 load bias 0x5fcf8a661000 / 0x5a1319d2e000 / 0x609c3a61f000 / 0x5f72fdb6e000 / 0x55732085d000）。**确定性复核：三次独立全量运行产物逐字节一致**（analysis 与 analysis_dup2 的 summary.json/summary.md/iclass_per_run.tsv `cmp` 全同）。
- **G1 PASS**：模型函数样本 260,636 ≥ 100,000；覆盖率 1.0000。
- **G2 PASS（修订门）**：≥1% 类逐次份额样本 SD 全部 ≤ 0.5pp——最坏四类 heap_ld 0.245pp / branch 0.209pp / misc 0.193pp / stk_st 0.139pp。（原始两两门仍 FAIL：branch 对差 0.515pp——并列登记于 summary `informational.g2_consistency_orig`，证实该方差为真实运行级效应而非采样噪声。）
- **G3 PASS（修订门）**：样本侧 (task+helper+simtop_other)/全部 = **98.452%**；同构建相位参照 (compute+commit+publish)/Host = **99.299%**（perf4 99.3025% / perf5 99.2955%）；**Δ = 0.847pp ≤ 1.0pp**。残余 0.85pp 归 nemu/difftest/uart 等 emu_other 与相位口径边界（计时侧 eval 段外的模型初始化几乎为零、样本侧 emu_other 实测 1.22%）。（原始门仍 FAIL：task+helper 93.73% 对 [90.5%, 92.0%]——并列登记 `informational.g3_closure_orig`。）
- **G4 PASS（修订门）**：flag_rmw = **99,445.0 instr/cycle**（份额 2.518% × 3,949,943.3）∈ **[94,581.1, 250,000]**（= 123,000 × f_mem 0.96119 × 0.80 守卫容差 至 250K）。（原始门仍 FAIL：99,445 < 100,000——并列登记 `informational.g4_flag_rmw_anchor_orig`；形态普查 `arm_form_census.json`：静态站点 505,814/121,687/27,303/3,952，fires 加权份额 77.44%/18.17%/3.88%/0.51%。）
- **M-iclass**（5 运行合并份额 / instr·cycle⁻¹ / bootstrap 95% CI 见 `analysis/summary.md`）：branch 15.16%/598.7K、logic 14.91%/589.0K、heap_ld 13.75%/543.2K、cmp 13.72%/541.8K、stk_st 6.88%/271.6K、heap_st 5.78%/228.4K、stk_ld 5.29%/208.9K、misc 5.22%、sse 3.55%/140.3K、setcc 3.01%、mov_rr 2.80%、flag_rmw 2.52%/99.4K、arith 2.09%、mask_and 1.40%/55.3K、shift 1.26%、lea 0.74%、cmov 0.43%、call 0.20%。
- **M-fhot**：≥0.1% 函数 **107** 个；Top 为 simtop::eval 3.37%、cpu_direct_state_changed 1.35%、dso:libc 0.90%；最热 task cpu_task_3970 仅 **0.843%**（NO00005 长尾结论在 NO00015 PGO 构建上再次成立：单任务 ≤0.85% < 1.35%）。
- **M-coldbias**：闭式/采样逐类比值 5.3×（misc）到 91.2×（call；cmov 88.4×、lea 84.0×、heap_st 58.0×、sse 31.9×、mask_and ~15×、branch 8.7×）——"静态×fires"口径在所有类上系统性高估约一个数量级（NO00016 65×、NO00017 +88.8%/+23.3% 高估的逐类定量对应物；后续节点用闭式静态口径预注册微观指标时必须按本表逐类校正）。
- skid 敏感性（登记）：**77.5%** 样本的函数内前驱指令与命中指令异类——类别边界对 skid 敏感，逐类份额不确定性以 bootstrap CI 为准。
- 工作区计时边界核对：采样运行 Host 全部 ≤ 53.4 s < 79.0 s cutoff；分析单次全量 ~90 s < 30 min 预算。

## 判定

**ACCEPTED**（诊断节点，预注册修订口径下 G1–G4 全过）。首轮原始门 G2/G3/G4 FAIL 的归因均已机制性定位并登记（修订 1/2/3：跨构建参照系错误、锚的形态分解缺失、方差模型误设），修订后全部门通过且原始门结果并列留存（summary `informational` 节）。交付：**M-iclass** 逐类动态份额表（18 类，含 bootstrap 95% CI 与逐类 instr/cycle 定价）、**M-fhot** 函数级表（107 函数 ≥0.1%，单任务 ≤0.85% 长尾复核成立）、**M-coldbias** 逐类冷块偏差表（5.3×–91.2×）。候选池动态定价解读（后续节点立项依据）：① 池定价必须走动态口径——静态×fires 高估 5–91×，冷块混淆是结构性的；② 头部四类 branch/logic/heap_ld/cmp 合计 57.5% 且跨函数长尾分布，单点优化无可行池，类别级优化须面对"份额大但语义必需"的现实（cmp+branch 28.9% 主要是检测/守卫/派发的固有条件代价）；③ 寄存器压力动态实证成立：stk_st+stk_ld 12.2%（480.4K instr/cycle）——NO00009 三层保护第③条的量化对应，是 task 体粒度过粗（NO00006）的直接代价；④ mask_and 动态仅 1.40%（55.3K/cycle），终裁 BASELINE 静态复核的存疑池"宽度掩码消除"不成立；⑤ sse 3.55%（140.3K/cycle）为真实热执行（非全冷块），与 w65p 宽值操作相关，量级不足以独立立节点；⑥ 残余开放线索 F-arm-residual（flag_rmw 实测较形态修正期望低 15%，指向 changed 守卫通过率与形态相关性或锚的图级口径）与 G2 运行级方差机制（ASLR/相位混合）留待后续。当前最佳指针不动（**NO00015，52.672 s**；本节点零性能语义改动，无重测——wolvrix 保持 `dfa59d2`，冻结面零改动）。设施留存：`scripts/grhsim_dyn_iclass_profile.py` + 33 单测 + Makefile 双目标（`analyze_grhsim_dyn_iclass`/`test_grhsim_dyn_iclass`），5 次 perf 采样归档、`phase_ref.csv` 同构建相位参照、`arm_form_census.json` 置位臂形态普查均在 `ptmp/no00018_iclass_20260926/` 可直接复用。
