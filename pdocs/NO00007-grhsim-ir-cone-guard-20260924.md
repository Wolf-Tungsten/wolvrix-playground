# NO00007: 输入端口级精度——变化 token 掩码 + 锥级守卫削减单位内 dynOps（优化）

| 字段 | 值 |
|---|---|
| 父节点 | NO00004（当前最佳；NO00005 诊断、NO00006 配置实验均无代码改动，代码状态同源） |
| 角色 | 优化 |
| 状态 | REJECTED（机制性错误，F1 诊断门 + M-act 阈值双触发；分支不再延伸） |
| 锚定指标 | M-act（动态 compute op 执行量 dynOps，确定性计数）；辅 M-tput（原生 instr/cycle） |
| 指标阈值 | M-act 降 ≥40%（新口径实际执行 op 数）；M-tput 降 ≥10% |
| 回退预算 | Host 相对 55.864 s 允许回退 ≤+3%（≤57.540 s） |
| 最终性能 | 未测量（F1 预注册提前止损，不做 PGO 生产构建）；当前最佳指针不动（NO00004 55.864 s） |
| RUN_ID | no00007_census_20260924（静态锥普查）；no00007_dyn_new_20260924（中间代码态 dyn 诊断）；no00007_dyn_leak_20260925（leakcheck 诊断）；no00007_dyn_gate_20260925（终态门控代码 dyn 复跑） |
| 工作区 | ptmp/no00007_cone_guard_20260924/ |

## 基础选定（BASELINE）

- **父节点**：NO00004（当前最佳指针，Host 55.864 s，PGO 构建）。无迂回：NO00005（诊断）、NO00006（配置实验，REJECTED 后未固化任何代码）均无代码改动，代码状态同为 wolvrix `dc3e3cb` + 根仓库 `9833959`。本节点在其上改动唯一变量：compute unit 内执行的输入精度（发射器锥级守卫），分区/扇出/调度结构不变。
- **代码状态核对**：wolvrix `dc3e3cb`（工作区干净）；根仓库 `9833959`（本节点新增测量设施：`scripts/grhsim_cone_guard_census.py` + Makefile `analyze_grhsim_cone_guard` 目标）；xiangshan 子模块未动。冻结面零改动。
- **输入核对**（sha256，与 NO00001–NO00006 相同）：
  - `coremark-2-iteration.bin` = `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`
  - `riscv64-nemu-interpreter-so` = `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`
- **基线测量（配置未变，复用归档值，不重跑未插桩基线）**：
  - Host：NO00004 归档 **55.864 s**（3 次有效均值，SD 0.270 s）。
  - 原生指令量：NO00005 归档 **479,295,135,474 instr**（4.793 M/guest cycle；compute_task 80.18%）。
  - M-act 基线：dynOps = **99,479,933,605**（NO00006 以当前 wolvrix `dc3e3cb` 对 NO00004 归档 mapped checkpoint 重发重测，同计数器定义，与 NO00001 M4 逐键一致；per_eval=497,146，evals=200,102；supernode 激活 993,413,585，body 执行 904,557,815，quiescence 跳过 8.94%，productive 29.88%，chg/act 31.36%）。
  - 静态结构基线（NO00001 M3）：supernode 32,101，op 均值 110.01，boundary results 812,234（25.30/unit）。
- **方向约束（机制证伪表，立项合规性）**：
  - 不触碰"下降沿 eval 消除"（NO00003 证伪）与"尺寸上限细化"（NO00006 证伪）。
  - NO00006 结论登记："后续激活率机制（支撑集纯化锥、输入端口级精度、扇出结构、单 pass 调度）不受证伪约束，但立项须论证如何在不增长扇出边密度的前提下降低激活率"。本节点属**输入端口级精度/支撑集纯化锥**：扇出边（value→consumer-unit）数量与目标完全不增——发布路径仍置同一组 consumer flag，仅附加 token 掩码负载；unit 激活次数不承诺下降（激活条件不变），下降的是**每次激活执行的 op 数**。合规。
- **机制勘察（本节点新增，两侧发射器/调度源码实证）**：
  - ir 侧（`wolvrix/lib/grhsim/backend/cpu_schedule.cpp:195-241`、`cpu_emit.cpp`）：激活粒度 = unit 级——任一 boundary operand 变化（值级精确比较，producer 体内联 `if(old!=new)`）→ 置 consumer unit flag → **整个 unit body 无条件顺序执行**；round 内静态拓扑序扫描、round 内至多执行一次、多 round 可重入（multi_round 0.37%）；commit/publish 严格变化门控；roundSeed（system/DPI）单元每 round 无条件激活（4.27%）；无 compute unit 的输入端口级掩码设施（仅 commit port 有 arm 位）。
  - gsim 侧（`reference/gsim/`）：单相单 pass 静态拓扑序 + 跨 cycle 持久 flag；值级精确变化检测；寄存器不变则零下游激活（clock gating 折叠为 WHEN）；分区显式最小化切割边 + 复制/位段拆分降低被监测值密度（442,722 监测值/84,643 supers ≈ 5.2/super，对 ir 25.3/unit）；activation edge 1.38 M（3.12 consumer/monitored value）。
  - 差距结构（NO00005/NO00006 实测）：compute_task 3.843 M instr/cycle = dynOps 995 k × 3.86 instr/op；同尺寸（~60 op）下 ir 激活率 27.4% vs gsim ~10.6%；尺寸细化因扇出边密度反弹被证伪 → **剩余可动乘数是"每激活执行的 op 数"的输入精度，而非单元尺寸或边数**。
- **静态锥普查（本节点新增设施 `analyze_grhsim_cone_guard`，对 NO00004 分区（cap128）mapped checkpoint + NO00006 dyn-old 逐 unit body 加权）**：
  - endpoint（roundSeed，含 `core.dpi.call`/`core.system.task`）单元 316 个，dynOps 份额 4.27%（与 NO00001 M4 every_round 桶一致）——此类单元每 round 强制激活，守卫不适用（实施时 seed 置全 1 掩码保持全执行），不计入守卫池。
  - 守卫池 31,785 单元：tokens/unit 均值 72.4（p50=55，p99=232，max=7977）；outputs/unit 均值 25.5（p50=14，p99=128）；unit 内无输出通路的死 op 均值 1.6%；不同输出可达掩码（守卫区域数）均值 29.7/unit。
  - 单 token 变化的支持锥覆盖率（unit 均值口径）与 k=1..4 并集残余见「假设提出」（普查 v3 闭合后登记精确值）。
- **资源配置**：与 NO00001–NO00006 一致：`XS_EMU_CPU=2`、`XS_EMU_THREADS=1`、`XS_NUM_CORES=1`、`XS_SIM_MAX_CYCLE=100000`、trace 全关；编译 `VM_BUILD_JOBS=32`；测量时机器空载；逐次 `posix_fadvise(DONTNEED)` 驱页缓存。
- **计时边界与止损线**：
  - 生成：make 启动 → 完整 C++ 与 Makefile 生成完成，墙钟 <1800 s（NO00004/NO00006 实测 775–880 s 量级）。
  - C++ 编译：PGO 三阶段合计 <1800 s（NO00004 695.95 s / NO00006 629.94 s）。
  - 仿真：仅 emu 执行区间；运行截止 = 55.864×1.5 = **83.796 s**（基线取归档均值，预注册）；dynamic-stats 插桩诊断运行上限 300 s（先例，时间不进基线）。
  - perf stat 运行为插桩诊断运行，Host 读数记录但不入基线。

## 假设提出（HYPOTHESIS）

- **假设**：GrhSIM-IR compute unit 的激活语义是"任一 boundary 输入变化 → 全 body 顺序执行"（unit 级粒度），而 unit 内 op 对输入的**依赖锥覆盖率中位仅 ~12%（单 token）**——每次激活重算了大量与变化输入无关的锥。在**不改变分区、不增加扇出边、不改变激活条件**的前提下，给每次激活附加"变化 token 掩码"负载（发布路径在置 flag 的同时 OR 该值在目标单元内的 token 位），并在 body 内按 op 的**输出可达支持掩码（RS）**做相邻合并守卫（`if (chgmask & RS_region)`，仅执行其下游输出可能被本批变化影响的 op 区域；执行集祖先闭合，帧内临时值安全），可把**每激活执行的 op 数**压到变化输入的支撑锥并集上。静态选择器（单 token 祖先覆盖 ≤0.5 的通用依赖锥特征）只对约六成单元施加守卫，回避高覆盖单元的守卫纯开销。
- **创新点**：方法论重启后首个**单位内输入精度**节点；把 NO00006 证伪的"尺寸换精度"替换为"掩码换精度"——dynOps 的两个乘数（激活数 × 每激活 op 数）中，前者由扇出边密度结构决定（NO00006 证伪尺寸路径），本节点直击后者且不触碰前者。RS 守卫直接落在 token 空间（无需 output 空间中转），相邻 op 共享同一 RS 常量的合并使守卫数从 op 数（110）降到 ~31/unit（相邻游程均值）；守卫语义为**粘性掩码**（掩码仅在 body 实际执行时清零，quiescence/边沿跳过路径天然安全，只会保守多执行）。同时建立与 gsim 环比的新维度：gsim 以"小 super + 低激活率"达到低 op 求值量，本节点检验互补命题——**"粗 unit + 锥级精度"能否在保持低边密度的同时达到同等有效求值精度**。
- **瓶颈证据（本分支实测 + 本节点普查）**：
  1. NO00005：compute_task 3.843 M instr/cycle = dynOps 995 k × 3.86；M4：69% 激活无产出（productive 29.88%）。
  2. 本节点静态锥普查（`analyze_grhsim_cone_guard`，NO00004 分区 + dyn-old 逐 unit body 加权）：eventful（含事件语义/对象写，含 316 endpoint）单元 810 个、dynOps 仅 4.30%（非 endpoint eventful 494 单元、0.03%）——排除后守卫池 31,291 单元；单 token **支持锥**覆盖（unit 均值）12.3%、**祖先锥**覆盖 38.7%；body 加权残余：支持口径 k=1..4 = 13.1/21.9/28.7/34.4%，祖先口径 = 41.6/54.7/63.1/69.0%；区域合并与祖先口径执行集相同（残余逐 k 一致），仅降守卫数（相邻游程均值 31.7/unit）。
  3. 静态选择器（cov_ancestor k=1 ≤ T）响应表：T=0.5 覆盖 57.1% 单元、70.0% dynOps，区域残余 k=1/2/3 = 23.4/38.4/49.1%；T=0.7 覆盖 78.0% dynOps 但残余升至 27.1/42.7/53.2%（边际单元接近盈亏平衡）→ **选定 T=0.5**（预注册固定值）。
  4. 帧安全性证明（实施语义的正确性前提）：op j 执行 ⟺ chgmask ∩ RS_j ≠ ∅；j 读取 i ⟹ RS_i ⊇ RS_j（i 的输出可达集是 j 的超集）⟹ i 必执行——被执行 op 读取的一切 unit 内临时值都在同次调用中新鲜计算；被跳过 op 的 boundary 结果值持久于 boundary arena 且其支持不含变化 token ⟹ 旧值仍正确，无需重写/发布。
- **微观指标与总目标的定量关系**：
  - **M-act**（锚定）= 新口径动态 compute op 执行量（dynamic-stats 构建新增 `sn_exec` 逐 run 计数实际执行 op；旧口径 = body × 静态 op 数仍可同日志导出，基线 99,479,933,605 锁定不变）。传导链：compute instr ≈ dynOps × 3.86 + 守卫开销（~31 区域 × ~2.5 instr ≈ 78/激活 ≈ 0.71 op 当量/区域）+ 掩码管理（~15/激活）；M-act −50% ⇒ compute instr ≈ −40%（含守卫开销）⇒ 总 instr −32% ⇒ Host ≈ −18 s（CPI 不变假设，NO00005 频率闭合支持线性传导）。
  - **M-tput** = 生产口径 perf stat instructions:u ÷ 100k cycle；基线 4.793 M/cycle（NO00005 归档 479,295,135,474）。该指标把守卫分支/掩码负载/CPI 响应全部计入，是净效益判定量。
  - 辅助登记：k 分布（每次激活消耗 token 数，dyn 构建新计数器）、区域执行残余实测值、boundary 写总量、branch-miss/icache 密度（NO00006 教训：CPI 回吐风险专项跟踪）、生成代码行/函数数。
- **预注册**：
  - **判定阈值**：M-act 降 ≥40%（预测 −50%~−60%：选择器覆盖 70% dynOps ×（1 − k≤2 残余 23~38%）− 未选择池不变）；M-tput 降 ≥10%（预测 −15%~−25%）。两阈值同时达成且门槛通过为 `ACCEPTED`。
  - **回退预算**：Host 3+3 交替均值相对 55.864 s 回退 ≤+3%（≤57.540 s）；实际值如实登记。
  - **证伪标准**：
    - F1（诊断门，提前止损）：dynamic-stats 构建实测的 k 分布代入逐 unit 区域残余曲线后，**守卫池预测残余 >60%**（多 token 激活把锥并集推向全覆盖，单/双 token 假设在动态下不成立）→ 不做 PGO 生产构建，节点以机制性 `REJECTED` 收尾（成本限于诊断构建）。
    - F2：M-act 降 ≥40% 但 M-tput 降 <8% → 守卫分支/掩码负载吞没 op 节省（CPI 机制）→ `REJECTED`（登记分支/icache 密度变化供后续引用）。
    - 正确性/门槛失败（`INVALID`/`TIMEOUT_KILLED`/`REGRESSION_KILLED`）→ 按实现瑕疵处理，节点内修正重测。
  - **测量方法与运行秩序**：
    - 守卫安全性边界（实施语义约束，预注册）：endpoint（含 `core.system.*`/`core.dpi.*`）与 eventful（任一 op 带 `event_edges` 参数或非读类 objectRefs）单元不施加守卫（其副作用无 boundary 输出通路，会被守卫永久跳过）；roundSeed 单元不受影响（均为 endpoint）；无输出通路的死 op 在守卫单元内永不执行（结果无消费者，语义安全）。
    - M-act：同计数器定义链——新 wolvrix 全流生成 dynamic-stats 诊断构建，`make analyze_grhsim_dynamic` 导出旧口径（body × 静态 op，应与 99.48G 一致，偏差 >1% 即排查）+ 新口径（Σ sn_exec）；确定性计数精确比对。
    - k 分布与区域残余：dyn 构建新增计数器直接输出（先于 PGO 构建，作 F1 判定依据）。
    - M-tput：新 PGO 二进制 perf stat 3 次（同 NO00005 pass1 事件组），对归档值比对；gsim 侧 196.545 G 作环比锚。
    - Host：3+3 交替，顺序 **old1,new1,old2,new2,old3,new3**（预注册），同窗口、CPU 2、逐次 fadvise；任一构建 `INVALID` 该次作废补跑；报告均值、离散度、秩次判据（全部 3 次新优于全部 3 次旧方判提升真实）。
    - 生成/编译门槛：墙钟计时写 `*.time`，超时即 `TIMEOUT_KILLED`。
    - 聚焦测试：`make run_hdlbits_test DUT=001` 及若干抽样 DUT 通过（守卫发射路径的语义等价），100k 端点四字段精确匹配。

## 代码实施（IMPLEMENTED）

- **实现内容**（wolvrix `dc3e3cb` 之上唯一改动文件 `lib/grhsim/backend/cpu_emit.cpp`，+660/−32；语义约束全部来自 `model_`+`schedule_`+`layout_`，调度 schema 不动）：
  - `planConeGuards()`：token 分配（`computeSupernodeFanout`+`inputFanout` 的 activate 目标 → value token；`commitStateFanout` activate+`aliasConsumers_` → state token）；资格排除（endpoint：`core.system.function/task`、`core.dpi.call`；eventful：带 `event_edges` 参数或非读类 objectRefs；以及已被 quiescence/guard-group/direct-sample/edge-direction 挂靠的单元，防御性重叠）；unit 内 def-use 位置表；**SUPP 前向定点**（支持锥：op 读到的全部外部 token）；**isOutput 锚定**（结果落在 boundary 存储的 op）；**RS 反向定点**（输出可达支持掩码；j 读 i ⟹ RS_i ⊇ RS_j 向下闭合，帧内临时值安全）；**静态选择器**（unit 均值 per-token op 覆盖率 ≤ 0.5，预注册 T）；**纯源修复**（boundary 存储但 RS=∅ 的常量锥 op 置全 1 掩码，保证初值传播）+ 二次重传播；**死区不发射**（RS=∅ 无输出通路，结果无消费者）；相邻同 RS 合并为 run（实测 30.1 runs/unit，预注册估计 ~31.7）；chgmask 字分配（W=⌈tokens/64⌉，全局 `cpu_chgmask[]` 布局）。
  - 发布路径 token 负载（与 flag 置位**同位置、同条件**，branchless）：computeGroup 尾声按 changed 组 OR 成员值 token；inline boundary 存储走 `activateChanged`；input fanout 变化；commit 直达路径（`cpu_direct_state_changed{,_one}` 增 chg range 参数 + `cpu_cw_chgb/chgc` 表）；publish 循环（非 memory 经 `cpu_chg_ranges[state]`，memory 经 `cpu_memory_chg` 平行表 + `read_offsets` 门控）；init 全 1 掩码（初次强制全激活必须全执行，否则初值永不下传）。
  - body 入口：load+zero 粘性掩码字（quiescence/edge 跳过仅存于 eventful 单元，守卫单元天然不含，掩码不会丢失）；守卫区域 `if (cpu_chg_w & RS)`；动态计数器（`sn_exec`/snx 行、`tok_sum`/`tok_hist`、`exec_ops`、snl 泄漏行）。
  - 调试设施（仅 dynamic-stats 构建）：`GRHSIM_CONE_LEAKCHECK`（无条件执行全部区域，掩码区组 flag 翻转计入 `cpu_dyn_sn_leak`，死区以 fire=false 同样执行）；`GRHSIM_CONE_DEADPUB`（死区结果仍可发布的 op 列表，验证死区消除不掉 flag 翻转）；`GRHSIM_CONE_AUDIT`（指定 unit 的 token 表 + 生产者归属转储）。
  - 测量设施（根仓库）：`scripts/grhsim_cone_guard_census.py` + Makefile `analyze_grhsim_cone_guard` 目标（BASELINE 普查）；`scripts/grhsim_dynamic_stats.py` 增加 snx/tok/exec_ops 解析（无 snx 行的旧日志优雅降级）。
- **与父节点差异**：wolvrix 仅 `cpu_emit.cpp`；根仓库新增 census 脚本与 Makefile 目标、dynamic_stats 解析扩展。冻结面（GRH IR、GRH 已有 pass、XiangShan、测试源码）零改动。
- **终态门控（判定后固化，REJECTED 分支留存方式）**：锥守卫整体置于 `GRHSIM_CONE_GUARD=1` 环境变量之后，**默认关闭**；三个调试变量从属于主门。关闭时全部发射路径回退——`cpu_chgmask` 数组、`ChgTarget/ChgRange` 结构与表、commit/publish 的 chg 遍历、`cpu_cw_chgb/c` 表、sn_exec/snl/tok 计数与 totals 扩展全部条件化；`emitChgmaskOr`/`activateChanged`/`coneGuardParams`/`coneGuard()` 在空表下自然退化为父节点文本。验证：门关生产发射（含生产 `commit_compact_walk`+`commit_mem_walk` flag）与 NO00004 归档 `flow/model` **逐字节一致**（`diff -rq` 排除 `.o`/`.a`，0 差异）；门关 dynamic-stats 发射与 NO00006 `flow-dyn-old/model` 逐字节一致。当前最佳点（NO00004 PGO 路线）的源同一性证明链不受影响。
- **聚焦测试**（终态门控代码）：`make run_hdlbits_test DUT=001`（门关，Verilator 路线）PASS；`make run_hdlbits_grhsim_ir` 门关 DUT=001、门开 DUT=001/106/118/131/137 全部 PASS（118 为 16×16 Game of Life，门开时 33/42 单元受守卫，覆盖守卫发射路径）。`run_hdlbits_test DUT=118` 在门关下同样失败（`tb_118.cpp` `get_bit` 不能接受 Verilator 宽信号 `VlWide<8>`；Verilator 模型来自本节点未触碰的 SV 发射路径，门关/门开结果相同）——预存的 tb/Verilator 兼容问题，与本节点无关，冻结测试源码不修。

## 结果测试（TESTED）

### 运行登记（全部诊断口径；仿真均 CPU 2、`XS_EMU_THREADS=1`、逐次 posix_fadvise 驱页缓存）

| 构建/运行 | 代码态 | 生成（checkpoint 筛选口径） | 编译墙钟 | 运行 | Host | 退出 | 端点四字段 | 判定 |
|---|---|---|---|---|---|---|---|---|
| flow-dyn-new / no00007_dyn_new_20260924 | 中间态（leakcheck 设施加入前，门常开） | 53.55 s | 312.30 s（<1800 ✓） | 100k，dynamic-stats | 241.773 s（<300 s 上限） | 0 | `0x80000c0c / 240,349 / 99,996 / 100,001` 精确匹配，DIFFTEST 无 mismatch | VALID |
| flow-leak / no00007_dyn_leak_20260925 | 中间态 + `GRHSIM_CONE_LEAKCHECK=1` | 54.90 s | 322.36 s（<1800 ✓） | 100k，无条件执行+泄漏计数 | 366.757 s（<900 s 上限） | 0 | 同上精确匹配，DIFFTEST 无 mismatch | VALID |
| flow-gateon-dyn / no00007_dyn_gate_20260925 | 终态门控代码（`GRHSIM_CONE_GUARD=1`） | 未单独计时（同 checkpoint 筛选路线，同批两次实测 53.55/54.90 s） | 311.18 s（<1800 ✓） | 100k，dynamic-stats | 240.431 s（<300 s 上限） | 0 | 同上精确匹配 | VALID |

终态门控代码复跑（no00007_dyn_gate_20260925）与中间态 dyn-new 的 totals 行**逐项一致**（`grp_pub=854663026 … tok_sum=5832298687`，hist 八桶、`exec_ops=42090933654` 全同），snl 行 0 条——下文全部微观指标同时代表两个代码态，证据链对提交代码闭合。全流程 SV→C++ 生成门槛未走（F1 预注册提前止损，允许成本限于诊断构建；生成计时均为 checkpoint 筛选口径，不冒充全 SV 路线）。

### 微观指标测量（确定性计数，固定输入精确比对）

- **M-act（锚定）**：新口径 `total_executed_ops_newdef = 73,469,067,656` op（per_eval 367,158.1 = guarded_exec 42,090,933,654 + unguarded_body_ops 31,378,134,002）。旧口径同日志导出 99,479,926,871，对锁定基线 99,479,933,605 偏差 −6.8e-9（<1% 预注册排查线，计数链一致 ✓）。**M-act 降幅 26.15% < 40% 阈值 ✗**。
- **F1 诊断门（预注册）**：守卫池 18,132/31,612 单元（57.4%），覆盖 dynOps 68.46%（body_ops 68,101,792,869/99,479,926,871）；**残余 = 42,090,933,654/68,101,792,869 = 61.81% > 60% → F1 触发**，不做 PGO 生产构建（F2 成本侧证伪不再可达，也未到达）。
- **k 分布**：k̄ = 9.5945（bodies_with_mask 607,880,801；tok_hist0=0，守卫 body 必携掩码）；k=1/2/3/4/5–8/9–16/≥17 = 121.45M/69.63M/43.38M/41.81M/92.96M/121.28M/117.37M，**k≤2 仅 31.4%，k≥9 占 39.3%**——单/双 token 假设在动态下不成立（F1 情形原文）。
- **正确性交叉验证**：snl 泄漏 0 条（无条件执行下无任何掩码区组 flag 翻转）；`GRHSIM_CONE_DEADPUB` 输出 0 行（死区结果无可发布通路，死区消除不掉 flag 翻转）；tok_sum 守卫构建 5,832,298,687 vs 无条件构建 5,832,547,369（+0.004%）；激活总数 993,413,530 vs 归档基线 993,413,585（−55，归因见复盘 4）；`GRHSIM_CONE_AUDIT` 抽 unit 1032683/1035188 的 token 表与生产者归属核对无异常。
- **生成代码形态**：chg words 29,062、tokens 1,295,826、runs/unit 30.1；eventful 排除 810 单元（316 endpoint + 494 非 endpoint），与普查一致。
- **M-tput**：未测量（F1 提前止损，无生产构建）；**Host 最终性能未测量**，回退预算未动用，当前最佳指针不动（NO00004 55.864 s）。

### 定量复盘（机制判定依据）

1. **残余-k 曲线闭合**：静态普查（选择池区域口径）k=1/2/3 残余 23.4/38.4/49.1%（祖先口径 k=1..4 = 41.6/54.7/63.1/69.0%），外推至 k̄≈9.6 ⇒ ~62%，与实测 61.81% 一致。测量链无异常，假设的 k≤2 主导前提被动态分布证伪。
2. **k 爆炸的结构原因（机制性错误所在）**：ir 激活语义为"任一 boundary 输入变化 → unit flag"，掩码仅在 body 实际执行时消费清零；两次执行之间到达的全部变化被批进同一粘性掩码。实测 chg/act=31.36%、rounds/eval=2.005、multi-round 重入 0.37%，每执行间隔平均积累 ~10 个变化 token（72.4 token/unit 的 13.2%）。锥并集在 k≈10 时覆盖 ~62% unit ops，守卫可省上限 = 38.2%×68.46% = 26.1%——恰为实测 M-act 降幅，机制自洽。
3. **阈值距离非边际**：M-act −40% 阈值在未守卫池 31.54% 不变时要求池残余 ≤41.6%，按普查曲线对应 k̄≤~2.3；实测 k̄=9.59 差 4 倍。实现经双重正确性验证（两个构建端点四字段精确匹配 + difftest 干净；snl=0；deadpub=0；tok_sum 0.004% 一致；旧口径计数链 7e-9 一致；终态代码复跑逐项一致），排除实现瑕疵 → **机制性错误成立**。
4. **±55 激活差异归因**：无条件（leak）构建激活 993,413,585 与归档基线逐一一致；守卫构建 −55（相对 5.5e-8）。两构建其余 totals 计数器（pub_pending/pub_changes/port_eval/port_fire/cm_ent/in_chk/in_chg/grp_fire）逐项一致——被抑制的 55 次激活在无条件构建中同样无产出（重算无变化），属活动驱动模拟固有的静默激活尾；instrCnt 逐位一致（240,349）支持该归因，对残余测量无影响（需 >1.8pp 才能翻转 F1 门，实际效应 5.5e-8）。
5. **gsim 环比（第二角度证实 NO00006 结论）**：gsim 低 op 求值量的前提是"变化到达 ⇒ 按单变化即时重估"（k≈1 语义：每值持久 flag + 单 pass 静态拓扑序）；ir 的 unit 级批量激活把 k 推到 ~10。单位内精度机制（锥守卫）在不打破激活批量的前提下，残余下限被 k 分布锁死在 ~62%；这与"尺寸细化被扇出边密度否决"（NO00006）合流：dynOps 两个乘数（激活数、每激活 op 数）的削减都被**激活语义本身**（边密度 / 批量）卡住，剩余路径指向激活结构而非单位内或单元尺寸。
6. **不受本条证伪约束的后续方向**：能把每激活 token 批量压到 k̄≤2.3 的机制（逐变化即时求值、round 级掩码消费、逐变化扇出精度等）可让池残余 ≤40%，与本条不冲突；立项须先用本节点设施（census + snx/tok 计数器）实测论证 k̄ 可达。

### 判定

**REJECTED（机制性错误）**：预注册 F1 诊断门（池残余 61.81% > 60%）与 M-act 阈值（−26.15% < −40%）双触发；实现正确性经多重交叉验证，非实现瑕疵。节点分支不再延伸。设施留存并已随节点提交：`GRHSIM_CONE_GUARD` 门控发射器（门关与 NO00004 逐字节一致，对最佳点零影响）、`analyze_grhsim_cone_guard` 普查、snx/tok/snl 动态计数器与解析。机制证伪结论登记索引证伪表。
