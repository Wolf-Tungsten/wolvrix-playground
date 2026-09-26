# NO00020: 未分图 gsim IR 与 GrhSIM IR 的模块级语义对比画像（诊断）

| 字段 | 值 |
|---|---|
| 父节点 | NO00019（当前最佳） |
| 角色 | 诊断 |
| 状态 | ACCEPTED（终态；四阶段完成，修订口径下 G1a/G1b/G1c/G2/G3/G4 全过，G1c 修订已登记） |
| 锚定指标 | **M-name**（寄存器位加权锚点匹配率）、**M-opcount**（模块级 op/enode 计数对照）、**M-kinddelta**（公共 bucket 的 op 构成差分解）、**M-cone**（配对寄存器更新表达式规模比分布） |
| 指标阈值 | 诊断节点：交付四项定量基线 + 有效性门 G1a/G1b/G1c/G2/G3/G4 全过；G3 匹配率 <80% 寄存器位 → 名称锚定的模块级对比路线机制证伪（REJECTED） |
| 回退预算 | 零语义改动：wolvrix 与 reference/gsim 零改动，根仓库仅新增默认关闭的导出开关与分析脚本；生产模型与 emu 不变，指针不动，无性能回退预算 |
| RUN_ID | no00020_gsim_module_compare_20260926 |
| 工作区 | ptmp/no00020_gsim_module_compare_20260926/ |

## 基础选定（BASELINE）

- **父节点**：NO00019（当前最佳指针，GrhSIM-IR PGO 构建 Host **52.580 s**，wolvrix `a59e1b6` + 根仓库 `0c9bdb7`）。诊断节点不改生产路径，代码基线即最新提交，工作区干净，无迂回。
- **立项动机**：用户 2026-09-26 22:26 提示——gsim 直接读 XiangShan 的 FIRRTL，GrhSIM-IR 读同一 FIRRTL 经 firtool 生成的 SV；相同设计到达 GrhSIM IR 时经历了 firtool、GRH IR 两重转换，形态被破坏，最终 host 指令量显著大于 gsim。建议方向：**把未分图的 gsim IR 与 GrhSIM IR 导出，按模块逻辑语义精确对比，寻找差异，定向优化**。本节点是该方向的诊断第一步：建立对比设施并交付形态差异的定量地图。已有设施 `scripts/compare_ir_shapes.py` 只做全设计聚合计数（gsim Final stats 对 GRH JSON），无模块轴、无逐寄存器语义对比，不满足需求。
- **基线测量（配置未变，复用归档值，不重跑）**：
  - gsim+PGO 锚点：Host **27.376 s**（3 次有效均值，SD 0.065 s）。
  - GrhSIM-IR 当前最佳：Host **52.580 s**（NO00019，3+3 均值，SD 0.216 s）；端点 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`；差距 **1.921×（~25.2 s）**。
  - 形态差距的既有定量锚点：NO00005（2.04× Host = 原生指令量 2.4386× × CPI 0.8389）；NO00008 因子表（指令差距闭合于每单位工作指令密度 **8.54×**：ir 3.86 instr/dynOp vs gsim 0.45 instr/enode；粒度覆盖 4.28×；变化流密度 1.175× 非主因）。
- **输入核对**：
  - gsim 侧输入 `build/xs/rtl/rtl/SimTop.fir`（1.67 GB，sha256 `4087ae26…95cfef`）——与 gsim+PGO 锚点构建所用同源（锚点模型由同一 firtool 输出生成）。
  - GrhSIM 侧输入 `build/xs/rtl/rtl/SimTop.sv`（sha256 `15e4d8dc…f00e72`）+ 全量 filelist `build/xs/wolf/wolf_emit/xs_wolf.f`；本次经 `--resume-from-flat-grh` 从 NO00019 归档 flat GRH（`ptmp/no00019_migrate_ec_20260926/flow/xiangshan_flat_grh.json`，3.4 GB）恢复，GRH 管线冻结、输入未变，恢复路径与完整 SV 路线等价。
  - 仿真负载 `coremark-2-iteration.bin`（sha256 `c764afb8…69542`）与 NO00001–NO00019 相同；本节点不跑仿真。
- **代码状态核对**：wolvrix `a59e1b6`、根仓库 `0c9bdb7` + 本节点工具改动（Makefile 新增导出目标与两个默认关开关接线、`scripts/wolvrix_xs_grhsim_ir.py` 新增两个默认关 dump 参数；均不改变默认管线输出）。gsim 使用安装版二进制 `reference/gsim/build/gsim/gsim`（版本串 `master-3b19dc1…-11-ga7f2113-dirty`，2026-08-12 构建）——与 gsim+PGO 锚点模型生成同源；导出为只读操作，不重构建 gsim、不动子模块。冻结面（GRH IR、GRH 已有 pass、XiangShan 与测试源码、reference/gsim）零改动。
- **导出点定义**：
  - gsim 侧「未分图」= **PreCoarsen 边界**：gsim 全部优化 pass（ExprOpt/UsedBits/SplitNodes/ConstantAnalysis/AliasAnalysis/PatternDetect/CommonExpr/末次 RemoveDeadNodes）之后、`graphPartition()`（合并+DP 划分）入口。用 `--dump-json --dump-assign-tree --dump-stages=PreCoarsen --stop-after-stage=PreCoarsen` 导出全图 JSON（节点名/类型 + assignTree 表达式树，ENode 带 op/width/sign），同时导出 `--export-executable-grh` / `--export-precoarsen-grh` 两个 GRH 投影供对照。
  - GrhSIM 侧「未分图」= 全部语义 pass（reg-to-mem、canonicalize-compute、clone-shared-compute、bitwise-predicates、pack-bit-registers、canonicalize-compute、bitwise-muxes、mux-chain-fold、used-bits）之后、第二趟 CPU 映射（`cpu.st.split-phase`）之前。本节点在 `scripts/wolvrix_xs_grhsim_ir.py` 新增 `--dump-pre-partition-json`（该点存储）与 `--dump-post-lower-json`（grhsim.verify 后、语义 pass 前的raw形态，用于区分"转换链引入"与"本侧语义 pass 引入"）。两个开关默认关闭；关闭时代码路径只多一个条件判断，默认管线输出不变。
- **资源配置**：导出与分析为离线诊断，无仿真性能门槛；机器 32 核/187 GB；生成/导出墙钟如实记录（非门槛项）。生产门槛（生成/编译各 <1800 s）不适用于本节点（零生产改动，不重跑生产构建）。
- **止损线**：若 gsim 导出因二进制/输入不兼容失败，先归因；归因表明安装版二进制不支持所需导出（与 `--help` 广告不符）则记实现瑕疵并改用 `--dump-stages=CommonExpr` 等替代边界重试。

## 假设提出（HYPOTHESIS）

- **假设 H1（可对比性）**：两侧的命名都保留设计实例路径（gsim 用 `__DOT__` 连接，GrhSIM 用 `$` 连接，来自同一 RTL 层级），归一化后能在寄存器/存储器/顶层 IO 三类锚点上建立高覆盖对应（门 G3：按寄存器位加权的匹配率 ≥80%），支撑按模块（实例路径前缀）分组的语义对比。
- **假设 H2（形态差异是系统性的）**：firtool（FIRRTL→SV）与 GRH ingest（SV→GRH IR）两重转换引入的 op 量/构成差异集中在若干可枚举的转换模式上（例如条件赋值展开方式、位选/拼接的物化、聚合类型标量化、临时值命名），可按模块定位并定量排序——而不是均匀散布的随机噪声。若差异均匀散布且无主导模式，该结论本身即负向知识（登记后续"定向消除形态差异"路线的可行性上限）。
- **创新点**：本分支首个**两侧未分图 IR 的直接语义对比**。既有 `compare_ir_shapes.py` 只做全设计聚合计数（无模块轴、无表达式锥）；本节点按模块分组、按公共 op bucket 对照构成、并对配对寄存器的更新表达式做规模对比。
- **微观指标与总目标的定量关系**：总目标差距 = host 指令量差距（NO00005：2.4386×）× CPI 比（0.8389）；NO00008 把指令量差距闭合到「每单位工作指令密度 8.54×」与「粒度覆盖 4.28×」两个因子。这两个因子都是**静态形态**的动态投影：每个动态 dynOp/enode 的成本由其在未分图 IR 中的 op 构成决定。本节点的模块级形态地图（M-opcount/M-kinddelta/M-cone）把这两个因子定位到具体模块与转换模式，为后续「GrhSIM IR 层变换消除形态差异」的优化节点提供目标集与量级锚点（与 NO00012 M-econ 普查锚定 NO00013/14/15/19 优化节点的关系同构）。
- **指标定义与测量方法**：
  - **M-name**：归一化名称匹配率。锚点集：gsim `NODE_REG_SRC` 节点 ↔ GrhSIM states（寄存器类），另列存储器与顶层 IO。分子 = 配对成功的寄存器位数，分母 = 双侧各自的寄存器总位数（分别报 gsim 侧与 GrhSIM 侧覆盖率）。归一化规则与未匹配桶归因写入报告。
  - **M-opcount**：按模块（实例路径前缀）分组的计数对照表：gsim 侧 node 数与 ENode 数、GrhSIM 侧 op 数与 value 数、双侧比值；全局总计与逐模块行，闭合校验（逐模块求和 == 全局）。
  - **M-kinddelta**：公共 bucket 分类法下的 op 构成对照（全设计 + Top-N 差异模块），给出每种 bucket 的「GrhSIM 多出的 op 数」排序——即形态膨胀的构成分解。
  - **M-cone**：对配对成功的寄存器，比较其更新表达式的规模：gsim 侧 = 该寄存器 assignTree 的 ENode 数；GrhSIM 侧 = 该 state 写值在「命名值处截断」的反向锥内 op 数（命名值 = 带 SV 变量名的 value，对应 gsim 侧的具名 node 边界）。报分布（中位/p90/均值）与离群样本。
- **预注册门**：
  - **G1a（导出闭合）**：gsim 导出 JSON 的节点/边/ENode 计数与导出运行内部一致（JSON 行数 == 解析计数）；GrhSIM dump 的 `counts` 段与实际数组行数一致。
  - **G1b（dump 点代表性）**：pre-partition dump 与同一次运行产出的最终 checkpoint 的 op（按 kind 计）多重集相等——证明第二趟 CPU 映射不改变 op 集，dump 点形态即生产形态。若失败须归因（如映射 pass 增删 op），并据此修订 dump 点定义。
  - **G1c（复现性）**：本次默认管线（无附加 pass）最终 checkpoint 与 NO00015 归档 checkpoint（`ptmp/no00015_edge_complete_20260925/flow/xiangshan_grhsim_ir.json`）逐字节一致——NO00016/19 新增 pass 默认关闭，默认管线自 NO00015 起应无行为变化；失败须归因。
  - **G2（确定性）**：对比脚本对同一对输入运行两次，输出逐字节一致。
  - **G3（锚点有效性）**：M-name 寄存器位加权匹配率 ≥80%（双侧分别计）。<80% → 名称锚定的模块级对比路线机制证伪。
  - **G4（存储/IO 锚点）**：存储器与顶层 IO 锚点全部配对成功，或未配对项逐一归因到可枚举的转换原因（重命名/聚合拆分/常量剔除）。
- **证伪标准**：G3 失败 → 机制性错误，节点 REJECTED 并登记机制证伪表；G1b/G1c 失败且归因表明 dump 点不代表生产形态或默认管线已漂移 → 实现瑕疵，回 IMPLEMENTED 修正后重测。
- **回退预算**：无（零语义改动；对比脚本与导出开关不改变任何生产产物）。

## 代码实施（IMPLEMENTED）

- **对比脚本** `scripts/grhsim_gsim_module_compare.py`（约 1,500 行，编排与纯函数分离，确定性输出：排序键、无时间戳、无输出路径）：
  - **gsim 侧归约**：整载 5.6 GB `SimTop_PreCoarsen.json`（~85 s，峰值 ~40 GB）；node 记录归约为名称/类型/位宽/assignTree ENode 计数（ENode children 为扁平 nodes 数组的整数 id，逐序列化树出现计数）；`NODE_REG_SRC`→`NODE_REG_DST` 锥链接（dst_linked 148,876 / no_dst_ref 80）；模块归属 = 名称去末段 `__DOT__`。
  - **GrhSIM 侧归约**：`wolvrix.grhsim.v1` 紧凑 checkpoint（states 292,678 / values 3,379,131 / ops 3,531,463）；values 命名边界分类（生成名 `_val_<digits>`、`packed_bits_<digits>`、`_op_*` 视为无名；state.read/input.read/memRead 结果经引用对象计入命名边界）；**前向 owner 传播**——无名 value 继承其全部消费方（不越命名边界）的合并 owner（唯一→该模块；多模块→`(mixed)`；无→`(dead)`，DEAD 为合并单位元）；无结果 sink op（regWrite/memWrite/output.write）贡献被写对象的模块；op 模块归属五级规则（命名结果 → 首个 state ref → 结果 owner → 首个命名操作数 → `(anonymous)`）。
  - **pass 产物独立桶**（`module_of_state_name`）：`__event_*` 边沿簿记 → `(events)`，`packed_bits_<digits>`（pack-bit-registers 产物）→ `(packed)`，`__reg_to_mem_<digits>`（reg-to-mem 产物）→ `(reg-to-mem)`——三类均为 GrhSIM-IR 单方产物，在 gsim 侧无对应。
  - **M-name**：两阶段锚点匹配（归一化精确键 + chunk-strip 去尾段 `_<digits>` 回退）；双侧位加权覆盖率；未匹配桶归因（`module_path_absent_on_other_side` / `renamed_or_split_within_module` / `memory_port_node`）。
  - **M-opcount / M-kinddelta**：逐模块 node/op/value/ENode 计数（闭合校验：逐模块求和 == 全局）与联合 bucket 分类法构成差分（gsim ENode op 经 `compare_ir_shapes.GSIM_OP_BUCKETS`、GrhSIM op kind 经内建 `GRHSIM_KIND_BUCKETS` 映到同一分类法；全局 + Top-N 差异模块，按「GrhSIM 多出 op 数」排序）。
  - **M-cone**：配对寄存器组的更新表达式规模——gsim = REG_DST assignTree 的 ENode 数；GrhSIM = regWrite nextValue 操作数的反向 op 锥（命名边界值截断为叶，对应 gsim 的 OP_EMPTY node-ref 叶）；分布（中位/p90/p99/均值）+ 离群样本。
  - **门**：G1a（gsim 节点计数 == 导出日志末次 RemoveDeadNodes 值、全部 assignTree child id 在界；GrhSIM `counts` 段 == 实际数组长度含稠密 id）；G1b（pre-partition 与同 run 最终 checkpoint 的 op-kind 多重集差）；G1c（三 checkpoint sha256 两两比对 + 结构化 diff：逐数组首异行/异行数/样本，分类 `string_table_content_drift` 等）；G2（`--g2-reference` 指向前次报告，排除 gates.G2 子树后字节比较）；G3（位加权覆盖率 ≥80%）；G4（存储器/IO 锚点，存储器名先剥 firtool `_ext$Memory` 包装，未配对项逐一归因到 `_RANDOM`/`__reg_to_mem_`/`__event_` 等可枚举类）。
- **单测** `scripts/test_grhsim_gsim_module_compare.py`：**28 用例**——名称归一化/生成名判定/`_ext$Memory` 剥除/`module_of_state_name` 桶、锚点匹配（精确/chunk-strip/位加权）、owner 传播（含 sink-owner 继承、sink 与结果消费方汇合为 mixed、DEAD 单位元）、联合 bucket 映射双向覆盖、锥组装（去重 + 命名边界截断）、计数门、结构化 diff 分类、opcount 闭合、kinddelta excess 排序——全过。
- **Makefile 目标**：`analyze_grhsim_gsim_module_compare`（变量 `GRHSIM_MODCMP_GSIM/GRHSIM_PRE/GRHSIM_FINAL/GRHSIM_FULL/GRHSIM_ARCHIVE/OUTPUT/TOP_N/G2REF`）、`test_grhsim_gsim_module_compare`。
- **口径细化（实现期发现，按预注册「G 失败→实现瑕疵，修正后重跑」条款处理，均经全量重跑验证）**：
  1. **M-name 锚点排除 `__event_*`**：185,067 个 1 位边沿触发簿记状态非设计寄存器（双侧均无对应）；规格原文「GrhSIM states（寄存器类）」按排除事件口径执行（100,776 个 / 2,951,647 位），含事件口径（285,843 个 / 3,136,714 位）在报告 `referenceCaliberIncludingEventStates` 并列。
  2. **无名 value 判定**：`wolvrix.grhsim.v1` values 行 name_idx=0 表示无名（初版按 1 索引回绕取到 strings 表尾串，54,496 个无名 value 被误判为命名）。
  3. **sink-owner 规则**：regWrite 等无结果写 op 的模块归属取被写 state（对齐 gsim 中 REG_DST 树属于寄存器自身模块的事实；初版 1,127,036 个 value 落入 `(dead)`，修正后 1,127）。
  4. **pass 产物桶分离**：初版 `(top)` 承载 682,256 ops（packed_bits 合并链、reg-to-mem 访问机、事件簿记混入），分离后 `(top)` 仅剩 881 个 value、退出 Top 差异表。
  5. **`_op_*` 生成名**（28,887 个 GRH ingest 临时名 value）纳入无名判定。
  6. **G4 存储器包装**：GrhSIM `..._ext$Memory`（firtool 存储器包装）剥后缀后参与归一化（初版存储器 0 配对）。
- 运行命令（多轮同参数，仅输出目录不同）：
  `make analyze_grhsim_gsim_module_compare GRHSIM_MODCMP_OUTPUT=ptmp/no00020_gsim_module_compare_20260926/analysis/runN [GRHSIM_MODCMP_G2REF=.../run2/module_compare_report.json]`；
  单次全量 **~191 s** 墙钟（gsim JSON 解析 ~85 s 主导 + 三个 1.3 GB checkpoint 的 sha256 与结构化 diff ~50 s）。

## 结果测试（TESTED）

- **单测**：28/28 PASS（`make test_grhsim_gsim_module_compare`）。全量分析三轮（run1/run2/run3）各 ~191–196 s 墙钟，输出于 `ptmp/no00020_gsim_module_compare_20260926/analysis/run{1,2,3}/`。
- **G1a 导出闭合：PASS**。gsim 解析 2,710,353 条 node 记录 = 2,708,079 非存储器节点（与导出日志末次 RemoveDeadNodes `-> 2708079` 精确一致）+ 2,274 个 NODE_MEMORY；全部 assignTree child 引用在界；GrhSIM `counts` 段 18 项（states 292,678、values 3,379,131、operations 3,531,463、operands 8,024,415、results 3,379,131、object_refs 462,920、strings 11,420,714、origins 11,320,354、types 830、functions 34、io 8/5、稠密 id 等）与实际数组逐项相等。
- **G1b dump 点代表性：PASS**。pre-partition dump 与同 run 最终 checkpoint 的 op-kind 多重集 **0 差异**——dump 点形态即生产形态。
- **G1c 复现性：FAIL（预注册字节判据），归因完成，建议修订判据**。
  - 三 checkpoint sha256 互异（final `c698a62f…`、full `2a2b094e…`、archive `6cee8eff…`）。
  - 结构化 diff 定位：两对比较（final_vs_full、final_vs_archive）的 counts 段与**全部语义数组逐行相等**——states 292,678 / values 3,379,131 / operations 3,531,463 / init 292,678 / types 830 / inputs 8 / outputs 5 / interface 13 / functions 34，0 异行；差异仅三处，且可枚举：
    1. **strings**：438,263 个异行，全部为 `__event_<N>_0` 事件名重编号（样本 `__event_126_0` vs `__event_12621_0`），分类 `string_table_content_drift`；
    2. **origins**：11,320,103 个异行，仅 sourceIndex 字段漂移（样本 `[235,5,242,238,…]` vs `[235,5,242,12724,…]`）——origin 对事件名字符串的反向引用随 1 联动；
    3. **mappings**：仅 final_vs_archive 一对存在 1 行差异，载荷 op id 段重编号（1062353… vs 1049770…）；final_vs_full 的 mappings 相等。
  - **归因结论**：字节差 = 事件簿记对象的命名编号及其反引（origin sourceIndex、mapping op 列表）随运行路径的重编号；语义 IR（states/values/operations）三 checkpoint 完全一致。非默认管线漂移、非嵌入路径差异。事件编号依赖运行路径（resume-from-flat-grh 与全新全量 run 的事件分配序号不同）——此为 wolvrix 事件编号跨路径不稳定的事实登记（本节点零语义改动，仅记录）。
  - **判据修订建议**：G1c 改判「语义等价」——语义数组（states/values/operations/init/types/inputs/outputs/interface/functions）逐行相等，且其余数组差异可分类为事件重编号。**按修订判据 G1c PASS**。G1c 校验对象为最终 checkpoint 而非度量所用 pre-partition dump，本节点度量不受该差异影响。
- **G2 确定性：PASS**。run1 与 run2 的 report/summary 经独立 `cmp` 逐字节一致；run3 以 `--g2-reference` 指向 run2 报告，内置比较（排除 gates.G2 子树）PASS。
- **G3 锚点有效性：PASS**。寄存器位加权匹配率 **gsim 85.93%**（2,567,488 / 2,987,952 位）、**GrhSIM 87.79%**（2,591,137 / 2,951,647 位），双超 80% 门；含事件簿记的参照口径 82.61%（2,591,137 / 3,136,714）亦过线。名称锚定的模块级对比路线**未证伪**。
- **G4 存储/IO 锚点：PASS**。存储器配对 **499 组**（gsim 2,274、GrhSIM 6,835），未配对项全部归因到可枚举类：gsim 侧 1,775 个（`renamed_or_split` 1,710——splitNodes 存储器拆分/字段拆分后缀；`no_name_overlap_on_other_side` 65），GrhSIM 侧 6,336 个（`firtool_randomize_artifact` 3,965、`grhsim_reg_to_mem_pass_product` 2,026、`renamed_or_split` 307、`no_name_overlap_on_other_side` 38）。顶层 IO 配对 **12/12 组**，GrhSIM 侧唯一未配对项 `difftest_exit` 已归因（difftest 引脚，gsim 模型无对应）。

### 四项定量基线

- **M-name（寄存器锚点）**：锚点 gsim 148,956 REG_SRC（2,987,952 位）↔ GrhSIM 100,776 非事件 logic states（2,951,647 位，另排除 `__event_*` 185,067 个/185,067 位）；匹配 67,474 组（精确 67,099 + chunk-strip 375），覆盖 gsim 67,627 寄存器 / GrhSIM 69,231 states。未匹配桶：gsim 侧 `module_path_absent_on_other_side` 78,313 个/361,037 位（样本为 `…axi4xbar…idle/state_0` 等 1 位状态寄存器——其位被 pack-bit-registers 并入 `packed_bits_*` 字的直接证据）、`renamed_or_split_within_module` 2,724 个/57,058 位（队列 ram 字段拆分）、`memory_port_node` 292 个/2,369 位（gsim 存储器端口占位节点）；GrhSIM 侧 `module_path_absent_on_other_side` 29,723 个/354,972 位（含 346 个 `_op_*` 顶层临时 state）、`renamed_or_split_within_module` 1,822 个/5,538 位（firtool 聚合标量化后缀）。
- **M-opcount（模块计数对照）**：全局 gsim 2,710,353 nodes / 13,159,630 enodes vs GrhSIM 3,531,463 ops / 3,379,131 values，enode/op = **3.73**；46,064 个模块行，双侧四项闭合校验全过。Top 差异（|Δ|）：`…ctrlBlock_rob` enodes 1,361,151 vs ops 266,541（5.11 en/op）、`logEndpoint` 768,050 vs 252,682（3.04）、`(reg-to-mem)` +409,314、`(packed)` +271,174、`…decoderComp_csBundle` 571,423 vs 0、`…rob_rab` 427,588 vs 87,716、`(mixed)` +120,709、`cpu` +101,306（`cpu$_RANDOM` 等 firtool 随机化产物）、`…rat_fpRat` +70,584 / `…rat_vecRat` +66,737（重命名映射表 GrhSIM 单方膨胀）。
- **M-kinddelta（构成差分，全局）**：node_ref gsim 8,337,148 / GrhSIM 0（Δ −8,337,148）；const 1,017,652 / 28,504；mux_control 1,230,877 / 353,933；bitwise_logic 917,837 / **1,827,551（Δ +909,714）**；slice_index 770,341 / 464,843；compare 311,905 / 218,887；aggregate_concat 287,838 / 230,903；arithmetic 122,959 / 109,570；shift 108,285 / 7,316；cast_width 40,738 / 0；state_reg_access 0 / 201,551；memory 6,870 / 69,446；special 7,180 / 13,763；statement 0 / 5,183；io 0 / 13。两个结构性观察：(a) gsim enode 的 63.4% 是 OP_EMPTY node-ref 叶（SSA 下免费的命名引用），扣除 node_ref+const 叶后 gsim 计算类 enode 3,804,830 与 GrhSIM op 3,531,463 同量级（1.08×）——enode/op 3.73 的差距主体是叶物化风格而非计算量；(b) bitwise_logic 单方膨胀 +909,714 中 **434,340（47.7%）落于三类 pass 产物桶**（reg-to-mem 247,894 + packed 163,664 + events 22,782），另 38,471 落于 `(mixed)`（clone-shared-compute 跨模块共享）。
- **M-cone（更新表达式规模）**：67,474 对全部链接成功（misses 0）。gsim 锥中位 4 / p90 7 / p99 12 / 均值 4.79 / max 944；GrhSIM 锥中位 5 / p90 15 / p99 40 / 均值 10.90 / max 9,406；grhsim/gsim 比中位 **1.50** / p90 2.29 / p99 10.5 / 均值 2.59。离群样本集中于重命名映射表：`…rat_vecRat_arch_table`（GrhSIM 锥 1,973 / 边界叶 1,176 vs gsim 2）、`…rat_vecRat_difftest_table_1`（2,575 / 1,534 vs 3）。

### H2 判定证据（形态差异系统性）

三类 GrhSIM 单方 pass 产物桶合计 **743,824 ops = GrhSIM 全部 op 的 21.1%**（`(reg-to-mem)` 409,314、`(packed)` 271,174、`(events)` 63,336），构成可枚举：reg-to-mem = 访问机 bitwise 掩码合并 247,894 + memRead/memWrite 62,766 + 索引 slice 41,335 + 写使能 mux 40,479；packed = 合并/提取 bitwise 163,664 + slice 72,728 + 边界比较 17,976；events = 边沿检测 special 13,763 + 条件链。叠加 `(mixed)` 120,709（跨模块共享计算）与 `(top)` 残余（881 values，difftest/clock/reset 顶层真实对象），差异集中于可枚举的转换模式而非均匀噪声——**H2 成立**，后续「GrhSIM IR 层变换消除形态差异」的目标集与量级锚点已就位（报告全表见 `analysis/run1/module_compare_report.json`）。

## 门槛修订登记（2026-09-27，判定前登记）

**修订 1：G1c 复现性判据由「checkpoint 逐字节一致」改为「语义等价」**——语义数组（states/values/operations/init/types/inputs/outputs/interface/functions）逐行相等，且其余数组差异可分类为事件重编号。机制性依据（结构化 diff 实测，见 TESTED G1c 节）：三 checkpoint 的全部语义数组逐行相等；字节差异仅三处且全部可枚举——`__event_<N>_0` 事件名重编号（strings 438,263 行）、其 origin sourceIndex 反引联动（11,320,103 行）、mapping op-id 载荷重编号（final_vs_archive 1 行）。即字节流含事件簿记命名编号这一**运行路径依赖**成分（resume-from-flat-grh 与全量路线的事件分配序号不同），不属于管线行为；预注册字节判据系过严起草（与 NO00018 修订同类：参照系误设，非迁就数值）。原始字节判据结果（FAIL）并列留存于 TESTED 节。**附带事实登记：wolvrix 事件编号跨运行路径不稳定**——后续节点凡做 checkpoint 级复现比对，判据必须用语义数组口径，不得用字节口径。

## 判定

**ACCEPTED**（诊断节点，修订口径下 G1a/G1b/G1c/G2/G3/G4 全过，四项定量基线全数交付）。G3 双超门（gsim 85.93% / GrhSIM 87.79% ≥ 80%），名称锚定的模块级对比路线成立，H1 成立；H2 成立（差异系统性集中：三类 GrhSIM 单方 pass 产物桶 743,824 ops = 全部 op 的 21.1%，bitwise_logic 单方膨胀 +909,714 的 47.7% 落于该三桶）。交付基线与对后续节点的定向含义：

1. **M-opcount/M-kinddelta**：enode/op 3.73 的主体是叶物化风格——gsim enode 的 63.4% 为 OP_EMPTY node-ref 叶（SSA 下免费的命名引用），扣除 node_ref+const 叶后 gsim 计算类 enode 3,804,830 与 GrhSIM ops 3,531,463 同量级（1.08×）。**静态 op 计数两侧已基本对等，NO00008 的 8.54× instr/work 动态密度差距不是静态 op 量差距的投影**——与 NO00009/11/16/17 合流（动态成本 ≠ 静态存在），后续节点不得再以「GrhSIM 静态 op 更多」立项。
2. **三类单方 pass 产物桶（21.1% op）是首个可枚举的静态形态差异目标集**：`(reg-to-mem)` 409,314（访问机掩码合并 247,894 + memRead/memWrite 62,766 + 索引 slice 41,335 + 写使能 mux 40,479）、`(packed)` 271,174（合并/提取 bitwise 163,664 + slice 72,728）、`(events)` 63,336。gsim 侧无对应结构（其存储器/打包/边沿簿记走 runtime 原生机制）。但注意 NO00016/17 教训：静态存在 ≠ 动态成本，立项前须用动态口径（NO00018 定价表）核实这些 op 的动态份额。
3. **M-cone**：配对寄存器更新锥规模比中位 1.50 / p90 2.29 / 均值 2.59，离群集中 RAT 重命名映射表（arch_table GrhSIM 锥 1,973 vs gsim 2——firtool 聚合标量化 + GRH ingest 把 gsim 单表达式树展成逐字段逐位链）；逐模块 Top 差异表（rob 5.11 en/op、logEndpoint、decoderComp_csBundle GrhSIM 侧 0、rat_fpRat/vecRat 单方膨胀）为模块级定向优化提供坐标。
4. **M-name 副产物**：78,313 个 gsim 1 位寄存器（361K 位）在 GrhSIM 侧被 pack-bit-registers 并入 `packed_bits_*`——打包机制的跨侧证据，其动态成本待定。
5. 复现比对教训（修订 1）：checkpoint 字节口径含运行路径依赖的事件编号，后续比对一律走语义数组口径。

当前最佳指针不动（**NO00019，52.580 s**；本节点零语义改动——wolvrix 保持 `a59e1b6`、reference/gsim 零改动，根仓库仅新增默认关导出开关与分析脚本，生产模型与 emu 不变，无性能重测）。设施留存：`scripts/grhsim_gsim_module_compare.py` + 28 单测 + Makefile 双目标（`analyze_grhsim_gsim_module_compare`/`test_grhsim_gsim_module_compare`），三轮全量分析产物（report.json/summary.md，run1==run2 逐字节）在 `ptmp/no00020_gsim_module_compare_20260926/analysis/` 可直接复用；gsim PreCoarsen 导出与 GrhSIM 双侧 dump（post-lower/pre-partition）在同目录 `gsim-export/`、`flow/`。
