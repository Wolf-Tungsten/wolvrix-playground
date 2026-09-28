# NO00027：gsim×GrhSIM 配对寄存器更新锥微观结构差分（诊断）

| 字段 | 值 |
|---|---|
| 父节点 | declaredSymbol 基线（非节点：wolvrix `c69ac80` / 根仓库 `d830b7c`，谱系上接 NO00024） |
| 角色 | 诊断（优化前置普查臂，同 NO00026 模式） |
| 状态 | **ACCEPTED**（已完成 TESTED；G1–G6、全流程门槛与 +2% 回退预算全部通过） |
| 锚定指标 | M-pair（配对覆盖）、M-cone-cover（配对锥并集对全模型 compute 的静态/动态覆盖率）、M-leaf（锥叶对应率）、M-match（锥内 op/enode 结构签名匹配率）、M-xo（GrhSIM 单方多余 op 来源分类 × 静态 × 动态）、M-xg（gsim 单方多余 enode 分类）、**M-xo-dyn**（决策指标：排除三桶后 GrhSIM 单方多余 op 的动态份额） |
| 指标阈值 | 交付七项定量基线，G1–G6 全过；**优化节点立项继续条件**：M-xo-dyn ≥ 1.0% compute execs/cycle → 立项形态恢复节点（NO00022/24 模板）；< 0.3% → 微观图差分路线登记负向知识并关闭；中间区间附敏感性论证后由用户裁定 |
| 回退预算 | 零生产改动；指针不动。按总 goal 补齐完整生成/编译与 6 次交替复测；同配置诊断臂预算 +2%，超出时排查配置或机器漂移 |
| RUN_ID | no00027_paired_cone_diff_20260928 |
| 工作区 | ptmp/no00027_paired_cone_diff_20260928/ |

## 基础选定（BASELINE）

- **代码基线**：declaredSymbol 语义锚点基线（wolvrix `c69ac80`、根仓库 `d830b7c`）。生产开关全开，基线 Host 48.798 s（SD 0.168 s），对照锚点 gsim+PGO 27.376 s，差距 1.783×。初始立项工作区干净，本轮恢复状态见代码实施节，无迂回。
- **立项动机**：用户 2026-09-28 指示：先做微观配对锥对比，完成 NO00027。既有图差分（NO00020/25）止于模块级计数与锥规模比；NO00023 只普查写合并族残余写锥（ratio≥4 的 254 族局部 op 仅占全模型执行 0.765%，该前沿已采空）。**从未做过**：逐信号把 gsim enode 更新树与 GrhSIM op 锥做结构对齐，逐 op 标注来源并连接确定性动态计数。战役最大两笔收益（NO00022 −4.739%、NO00024 −1.349%）正是静态形态差分驱动，本节点把该方法推广到全量配对锥。
- **与既有证伪表的关系**：本节点不以"静态语句数定价动态指令成本"（NO00016/17 已证伪），动态份额一律取确定性 fires 闭式连接；不改变值承载/融合/删除任何 op（NO00009/11/16 证伪对象），产出仅为后续形态恢复节点的目标集与量级锚点。
- **诊断输入**（复用归档；验收另做完整生产生成）：
  - gsim 侧：`ptmp/no00020_gsim_module_compare_20260926/gsim-export/SimTop_PreCoarsen.json`（PreCoarsen 边界，5,588,394,875 B，NO00020/25 同输入）。
  - GrhSIM 侧 final：`ptmp/declsym_baseline_20260928/flow/xiangshan_grhsim_ir.json`（1,413,060,068 B）；pre-partition：`…/flow/pre_partition.json`（1,267,853,298 B，G1 语义一致门用）。
  - 动态臂：NO00026 诊断构建两次 100k 运行日志 `ptmp/no00026_declared_pack_census_20260928/dynamic-run{1,2}.log`（各 29,341 条 `sn` 行 + totals 行）；诊断 checkpoint `…/dynamic/xiangshan_grhsim_ir.json` 已与基线 final **逐字节一致**（NO00026 G1 已建立，本节点 G1a 复核 sha256）。生成源码目录 `…/dynamic/model/`（计数点闭式用）。
- **资源配置**：32 个逻辑 CPU / 187 GiB；编译 jobs=32。离线分析绑定 CPU=8，墙钟如实记录。仿真 CPU=2、单线程，性能窗口暂停离线分析；全流程门槛与比较口径见实施节。

## 假设提出（HYPOTHESIS）

既有证据（NO00008 因子表：差距主因是每单位工作指令密度 8.54×；NO00020/25：扣除叶后静态 op 比 1.17× 基本对等）预测配对锥的 op 量大体相当，但不排除存在 gsim 没有对应物的 **ir 单方语义工作类**（非簿记、非三桶已知形态）——例如 ingest/firtool 标量化展开残留、位宽规范化冗余、写恢复未覆盖的表达式形态。本节点对其定量：

- **H1（结构匹配是主体）**：配对锥内大部分 GrhSIM op 可与 gsim enode 建立 1:1 结构签名对应（M-match 高位）；不匹配部分主要落在三桶已知形态与位宽/标量化规范化类。
- **H2（决策相关）**：排除三桶后，ir 单方未匹配 op 的动态份额 M-xo-dyn 可能低于 1.0% 立项线；按头部原阈值，<0.3% 才关闭，0.3%–1.0% 需用户裁定，≥1.0% 则支持继续形态恢复研究。结构不匹配不自动证明语义冗余。
- **口径声明**：
  - **配对**：复用 NO00020/25 的 `match_anchor_sets` 两阶段配对（精确规范化名 + chunk-strip），锚点集为 gsim REG_SRC ↔ GrhSIM 非 `__event_` logic states；组内成员按带后缀全名再配 1:1，剩余记未配对。declaredSymbols 校验 GrhSIM 侧锚点纯度（既有 NO00025 M-decl 位覆盖 91.57%）；op 模块归属沿用 NO00021 的具名值传播。
  - **锥定义（两侧均展开命名引用）**：GrhSIM 侧 = 寄存器 `core.state.regWrite` 数据操作数的完整反向锥，在 `core.state.read`/`core.input.read`/`core.state.memRead` 截断（读 op 本身计入锥、其操作数不展开），DAG 去重——复用 NO00023 `cone()` 全模式。gsim 侧 = REG_DST assignTree 从 root 展开的 ENode 锥，**递归内联命名引用**（NODE_OTHERS/REG_DST 引用展开其全部 assignTree），在 REG_SRC/NODE_INP/存储器端口节点/常量截断为叶，环保护（in-progress 引用记 `gsim_cycle` 叶类）；lvalue 不可达天然排除。两侧均有寄存器当前值、输入、常量、存储器读四类边界；是否能可靠配对由实施节的规则决定。
  - **结构对齐（签名法，非图同构）**：两侧分别计算规范化签名——叶按配对关系给同一符号键；内部节点按（操作类, 子签名序列）递归，可交换操作子签名排序；规范化规则预注册：gsim `OP_PAD`/位宽填充透明穿透，三子项 `OP_WHEN` 压平为分支序列，GrhSIM 嵌套 `mux`/`prioritySelect` 链检测后压平为同构分支序列，常量按（值, 位宽）等价。没有 else 的 WHEN 不补造默认值。签名相等即结构匹配；不等即不匹配，不做模糊匹配（不匹配部分由分类与 G5 解释）。distinct 签名口径为主、出现次数加权口径为辅；重复出现同一签名不建立出现次数的双射。
  - **未匹配 op 来源分类（M-xo，穷尽且互斥，优先级序）**：① 三桶属主（owner ∈ {(reg-to-mem),(packed),(events)}，复用 NO00021 `attribute_op_modules` 属主传播）；② width_norm（位宽规范化 kind）；③ scalarization（位选/拼接/slice 类）；④ event_bookkeeping（非属主捕获的边沿簿记形态）；⑤ other_semantic（余下未匹配操作，不预设可删除）。gsim 单方未匹配 enode（M-xg）同样分类（node_ref 复制/pad/when 重塑/存储器端口/other），仅作信息参考（gsim 侧无逐 enode 动态计数）。
  - **动态连接**：每 op execs = 所属 compute 单元 body fires（NO00023/26 闭式链路，`unit_index` schedule 驱动遍历 + `checked_fires` 端点校验）；族/类份额一律全局并集去重，禁止逐对相加（NO00023 11.1× 高估教训）；分母 = 全模型 compute 执行数/cycle（基线口径 91,061,544,463 execs/run ÷ 100,001 guest cycles）。
- **预注册门**：
  - **G1a（输入身份）**：final == NO00026 诊断 checkpoint（sha256）；pre vs final 语义数组逐项一致（NO00023 指纹口径）；gsim 导出与 NO00020 归档一致（sha256）；GrhSIM counts 段逐项相等（实施时扩展到全部字段）；gsim 非存储器节点数 == 2,708,079。
  - **G1b（动态臂身份）**：dynamic-run1/run2 端点四字段 == (240349, 99996, 100001, 0x80000c0c)；两运行 fires/totals 逐键一致。
  - **G2（确定性）**：分析脚本同输入两轮全量输出逐字节一致（排除 gates.G2 子树）。
  - **G3（动态闭式）**：计数点闭式（group/publish 点数与生成源码一致）、grp_pub/grp_fire 闭式、compute 执行闭式、单元覆盖 missing/orphan = 0、锥 op 计数器覆盖 100%——全部复用 NO00026 口径。
  - **G4（对齐精度）**：固定种子抽样 ≥100 个配对，用独立重算实现复核签名匹配/不匹配判定与分类标注，一致率须 100%（实现瑕疵修复后全量重跑）。
  - **G5（闭式与解释）**：分类穷尽闭合（Σ 各类 == 不匹配总量，静态与动态双口径）；对 M-xo 动态份额 Top-5 类/族给出实际 IR/源码结构解释（NO00023 G5 模板）。
  - **G6（覆盖有效）**：M-pair 位加权覆盖双侧 ≥80%（沿用 NO00025 G3 门槛）；M-cone-cover 如实报告，若配对锥动态覆盖 < 30% compute，决策阈值结论限定于覆盖范围并显式声明。
- **证伪标准**：G4 不达标 → 对齐器不可用，节点 REJECTED；门失败且归因为实现瑕疵 → 修正后全量重跑。节点 ACCEPTED 判据 = 七项基线交付 + G1–G6 全过；是否立项变换节点按 M-xo-dyn 预注册阈值裁定。
- **回退预算**：零生产改动，指针不动（48.798 s）；同配置重建臂相对同窗口旧臂均值最多 +2%，不以历史均值代替对照。

## 代码实施（IMPLEMENTED）

恢复记录（2026-09-28）：启动时根仓库 `2871cbd`，唯一未跟踪代码为本节点 `scripts/grhsim_paired_cone_diff.py` 草稿；子模块全部干净，wolvrix `e49d454` 仅比 `c69ac80` 增加默认关闭的 pack 诊断导出。沿用本节点，不新建编号。

实施前澄清：

- 配对组内必须按带后缀全名及位宽建立 1:1 成员对应；不能把组内不同成员当同一叶。结构匹配必须发生于对应更新锥内，再对动态 op 取全局并集；不能拿另一寄存器锥的同签名抵消本锥差异。
- 签名保留运算结果位宽、移位/选择参数与有符号比较语义；OP_PAD 只在本节点的形态归一化口径下透明。结构不匹配只证明形态不同，不证明语义工作可删除；叶缺失与不支持形态单独计数，避免冒充确定优化空间。
- 存储读不能仅凭 memory 名判为同一叶，地址/读端口不同会造成假匹配。本轮没有可靠跨侧地址端口表，故保留两侧独立的存储读叶；完整动态份额同时报告未配对叶传播、已支持且叶完全锚定子集、输入已匹配的首层差异。后两项用于敏感性分析，原 M-xo-dyn 阈值不变。`bitSelect(mask,a,b)=(mask&a)|(~mask&b)` 属掩码合并，不归为索引切片；`assign` 属位宽规范化，不归为事件簿记。
- 依用户本轮对总 goal 的验收要求，原稿“无性能重测”不作豁免。本轮独立 `flow/` 完整 SV 生成和三阶段 PGO，均设 1800 s 截止，编译 jobs=32；复用父基线两份动态 profile。性能预注册顺序 `old1,new1,old2,new2,old3,new3`，old=`declsym_baseline_20260928/flow`，new=本节点 `flow`；CPU=2、单线程、100k、关闭 trace、每次驱逐 page cache；比较基线 48.798 s，仿真截止 73.197 s。

设施为 [分析器](../scripts/grhsim_paired_cone_diff.py)、[测试](../scripts/test_grhsim_paired_cone_diff.py) 和 [Makefile](../Makefile) 的 `analyze_grhsim_paired_cone_diff` / `test_grhsim_paired_cone_diff`。签名用无碰撞的 tuple 驻留表表示，命名引用以显式栈展开，独立复核用另一套递归实现。输出逐对表、抽样根结构及摘要；所有多锥执行数按 op ID 的全局并集去重。已有生产 IR、pass、发射器和测试 RTL 均无改动，子模块无本节点差异。

聚焦测试 **31 项**通过，覆盖完整名字与位宽配对、符号碰撞拒绝、有符号操作数、位选范围、分支优先级、无 else 更新、多 assignTree 顺序、引用展开与环保护、存储读边界、未知常量叶分母、跨锥假匹配拒绝及动态并集；复用模块配对/位更新/写锥/benchmark 四套 **83 项**通过。生产臂完整生成 **814.69 s**、三阶段 PGO **637.43 s**，均退出 0；最终 checkpoint 与父基线 SHA256 完全相同，生成模型全部 C++/头文件/Makefile 逐字节相同。PGO 训练使用父基线插桩训练 **107.411 s** 作为可比较基线，截止 **161.1165 s**；本轮训练 Host **109.483 s**，100k 端点一致、difftest 干净。避免把插桩时间混入 48.798 s 的未插桩口径；整个三阶段仍受 1800 s 截止约束。

实施瑕疵与修复：首轮因独立复核逐 op 重建递归缓存，在深锥重复展开，562.25 s 后终止；改为每对独立缓存。第二轮完整输出耗时 600.35 s，内部检查均过，但人工核对发现 2,117 个 `REG_DST` 含多个 assignTree，被错误当作缺少唯一根。实例 sbuffer `data_12_0_8` 实为两个 `WHEN(write_byte, data)` 更新。修复为遍历所有 RHS，并用有序虚拟 `assign_sequence` 保存多更新树次序（虚拟节点不算 enode），也展开被命名引用的多树节点。前两轮数值作废，第三轮复现任务中止。第四轮全量成功；复核又发现未知常量虽已保持两侧独立，却漏进 M-leaf 分母，补齐这些叶及对应测试，第五轮中止。正式结果以修正后的第六、七轮为准；上述旧轮次不作验收依据。以上均为诊断实现瑕疵，不作为机制证伪。

## 结果测试（TESTED）

全流程验收完成：从 Make 启动经完整 SV 路线至全部模型产物 **814.69 s**，三阶段 PGO **637.43 s**；二者均退出 0、均 <1800 s。编译器 clang **22.1.2**，PGO 使用同 CoreMark 输入并开启 difftest。完整 checkpoint 往返逐字节一致，父基线与本轮 checkpoint 也逐字节一致；模型目录源文件比较 0 差。最终聚焦测试复跑 **31 项通过**，依赖测试 **83 项通过**。

六次交替性能测试（2026-09-28 13:49:55–13:54:51，同一窗口）如下。每次 `posix_fadvise` 驱逐 page cache，CPU=2、`XS_EMU_THREADS=1`、100k、无 waveform/trace；分析进程暂停 296 s，测量窗口无本节点编译或离线分析负载。

| 顺序 | 构建 | Host s | emu 墙钟 s | 退出 | 等价性 |
|---|---|---:|---:|---:|---|
| 1 | old1 | 48.791 | 48.86 | 0 | 四字段一致，DIFFTEST 干净 |
| 2 | new1 | 48.990 | 49.06 | 0 | 同上 |
| 3 | old2 | 48.643 | 48.68 | 0 | 同上 |
| 4 | new2 | 49.428 | 49.47 | 0 | 同上 |
| 5 | old3 | 48.746 | 48.79 | 0 | 同上 |
| 6 | new3 | 48.644 | 48.71 | 0 | 同上 |

端点均为 `instrCnt=240349 / cycleCnt=99996 / guestCycles=100001 / PC=0x80000c0c`，IPC=2.403586。旧臂均值 **48.726667 s**、样本 SD **0.075871 s**；新臂 **49.020667 s**、SD **0.392899 s**；新减旧 **+0.294 s / +0.603366%**，预算 +2% 通过。Cohen d=+1.0390、Cliff delta=+0.5556、Mann–Whitney U(new)=7，改善方向单侧精确 p=0.90，秩次门未过。新臂离散度更高，三次样本不足以把微小漂移归因于离线脚本；本节点不声称性能改善，指针不动。

### 检查门与定量基线

第六、七轮全量分析均退出 0：Make 墙钟分别 **556.32 / 558.03 s**，分析器内部 **547.99 / 549.71 s**，峰值 RSS 均 **27.88 GiB**。两轮输出通过 G2 确定性比较。所有 **66,664 对**均找到两侧更新根，没有因多 assignTree 漏掉的寄存器；命名引用循环数为 0。

| 检查 | 结果证据 |
|---|---|
| G1a 输入身份 | final 与 NO00026 动态 checkpoint SHA256 同为 `44d6a1cd…a34740`；gsim 为预注册 `abed2a4e…c2411`。pre/final 语义数组及字符串前缀一致；counts 全部 **21 项**重算相等，另核对 state/value/op 稠密 ID；gsim 非存储器节点 **2,708,079** |
| G1b 动态身份 | 两次 100k 端点均为 `240349/99996/100001/0x80000c0c`；**29,341** 行全部计数器字段及 totals 逐键相同 |
| G2 确定性 | 第六、七轮摘要去除 `gates.G2` 后一致；`pairs.tsv`（**7,226,848 B**）和 `sample_roots.json`（**210,506 B**）均逐字节相同；摘要及两份文件比较全部通过 |
| G3 动态闭式 | group 调用 **836,431,500** = Σ(body×源码计数点数)；grp_pub **772,617,598**、grp_fire **245,705,479** 与运行总计精确相等；compute **91,061,544,463** 与分区子树独立统计精确相等；missing/orphan unit 均 **0**，锥 op 计数器覆盖 **100%** |
| G4 独立重算 | 种子 **20260928** 抽 **100 对**，独立重算完整锥、双方签名、匹配/不匹配集合及 GrhSIM 分类；两轮一致率均 **100%**、错误 0 |
| G5 分类闭合与解释 | Σ分类 ops = **1,245,296**，Σ分类 execs = **28,172,779,042**，gsim 分类 enodes 和 = **2,240,498**；均与集合统计精确相等。前五类实际结构见下节 |
| G6 覆盖 | 严格配对位率双侧超过 **80%**；配对锥动态覆盖 **35.7044% ≥ 30%**。达到预注册门，但仍不代表未覆盖部分已被分析 |

动态分母是 **91,061,544,463 execs/run ÷ 100,001 guest cycles = 910,606.339 execs/cycle**。它表示 compute 单元每次 body 执行所覆盖的 IR op 数，不是 host 指令数。固定 checkpoint、输入、周期和计数器位置使计数可精确复现；不把离线分析耗时混入仿真性能。

| 指标 | 定量结果与口径 |
|---|---|
| M-pair | 67,279 个候选组内按完整名字及位宽严格配对 **66,664 对 / 2,538,871 位**。gsim 总 2,987,952 位，覆盖 **84.9703%**；GrhSIM 总 2,925,994 位，覆盖 **86.7695%**。全部配对态在 declaredSymbols 中。组内未配对 gsim 768 成员/21,628 位、GrhSIM 1,693 成员/38,386 位，含 1 个规范名冲突；不以组覆盖 85.6941%/88.0814% 冒充成员覆盖 |
| M-cone-cover | GrhSIM 锥并集 **1,355,571 / 3,127,019 compute ops = 43.3503%**；执行并集 **32,512,934,178/run = 325,126.091/cycle = 35.7044%**。gsim 锥并集 2,770,431 个 RHS enode；命名别名与虚拟多树节点不计为运算 |
| M-leaf | 全局叶签名 GrhSIM **102,442**、gsim **173,427**，交集 **64,276**。每对内交集再汇总为 **1,705,043**，两侧叶分母 **10,522,407 / 11,871,970**，对应率 **16.2039% / 14.3619%**。两侧未解析常量、未配对寄存器及存储读仍进分母；GrhSIM 有 371 个无法解析的常量 op，不擅自解释为两态值 |
| M-match | 每对先对签名集合求交，再汇总各对分子/分母：共享签名次数 **2,176,318**，GrhSIM 60,877,079、gsim 62,352,814，匹配率 **3.5749% / 3.4903%**。出现次数加权为 **3.5754% / 14.2623%**。这两个口径只描述匹配率，不用逐对累计量给动态份额定价 |
| M-xo | 任何配对锥内未匹配的 GrhSIM op 全局并集 **1,245,296 ops / 28,172,779,042 execs/run**；分类见下表。同一 op 在另一对中能匹配时，仍保留本对差异 |
| M-xg | gsim 未匹配并集 **2,240,498 enodes / 1,549,107 distinct signatures**；node_ref_unpaired 294,745、pad 23,752、when_reshape 601,212、memory_port 3,019、other 1,317,770，合计精确闭合。gsim 无逐 enode 动态计数，不由此推算双方 host 成本差 |
| M-xo-dyn | 去掉三桶属主后 **1,229,238 ops / 27,933,259,279 execs/run = 279,329.799/cycle = 30.6751% compute**。这里的“多余”仅指对应锥中没有相同签名，不表示语义冗余 |

M-xo 分类优先级互斥，动态量均取全局并集：

| 来源类 | ops | execs/run | execs/cycle | 全模型 compute 份额 |
|---|---:|---:|---:|---:|
| owner_(reg-to-mem) | 13,455 | 192,950,640 | 1,929.487 | 0.211890% |
| owner_(packed) | 2,603 | 46,569,123 | 465.687 | 0.051140% |
| owner_(events) | 0 | 0 | 0 | 0% |
| width_norm | 4,002 | 254,811,028 | 2,548.085 | 0.279823% |
| scalarization | 312,127 | 4,844,251,404 | 48,442.030 | 5.319755% |
| event_bookkeeping | 0 | 0 | 0 | 0% |
| other_semantic | 913,109 | 22,834,196,847 | 228,339.685 | 25.075565% |
| **合计** | **1,245,296** | **28,172,779,042** | **281,724.973** | **30.938174%** |

三桶属主在本口径只有读边界等少量 op；打包叶影响却会传到桶外使用者，故不能把“非桶属主”理解为“与打包无关”。`other_semantic` 是排除其他类后的集合名，也包含状态读及常量；它不构成可删除性证明。

### 敏感性与假设复盘

原 M-xo-dyn **30.6751% ≥ 1.0%**，达到预注册的继续研究条件，未落入需用户裁定的 0.3%–1.0% 区间。以下都是补充口径，不替换原决策指标：

- 再要求某 op 在所有配对锥中都从未匹配，剩 **27,810,867,607 execs/run**，说明跨锥共用造成的重复判定不是高数值主因。
- 仅保留 GrhSIM 一侧叶全部有锚点、递归经过的操作均有规范化规则的子集，降到 **2,630,151,601 execs/run = 2.8883% compute**。这只证明本侧可解释，未证明另一侧存在等价局部子图。
- 仅取“当前 op 不匹配，但每个直接输入签名都能在对应 gsim 锥中找到”的首次差异，剩 **29,644 ops / 478,749,355 execs/run = 4,787.446/cycle = 0.525743% compute**。主要为 sliceStatic 1,130.320、eq 937.560、sliceDynamic 726.406、not 537.351、concat 509.961 execs/cycle；单个输入各自出现也不保证它们构成同一等价输出。
- 若要求整对更新锥的叶集合完全相同，仅余 **27 个未匹配 op / 976,898 execs/run = 0.001073% compute**。这一筛选同时排除了大量有条件更新和打包态，因此不能用它代替 M-xo-dyn 来关闭路线。

因此 **H1“大部分操作可由当前签名规则匹配”未获支持**：GrhSIM 匹配率只有 3.5749%。原因包括寄存器打包后的叶改变、存储读地址未配对、条件保持逻辑移到写端口以及中间位宽不同；递归签名会把这些差异传到祖先操作。H2 的“小于 1%”预测也未出现，但原始 30.6751% 不能证明有同等规模的优化空间，更不能乘 Host time 作收益估计。下一节点可从首次差异定位通用位宽/位选/条件写模式；必须纳入完整更新语义并以确定性计数和交替性能测试验证收益。本轮不实施下一节点，不关闭微观图差分路线。

### Top-5 差异的结构解释

前五项按分类内 kind 的全局执行并集排名；样例从对应类选执行次数最高的 op，并核对两侧 IR 与原 SV：

| kind | 未匹配 ops | execs/cycle | 实际结构与解释 |
|---|---:|---:|---|
| and | 287,110 | 75,027.008 | `TLSourceShrinker.nextFree_lo`：GrhSIM 为 64 位 AND；gsim 为 65 位 AND 后截取低 64 位。签名差异源于截位位置，未证明多做 AND |
| mux | 156,332 | 46,201.399 | `auto_out_a_bits_source`：GrhSIM 条件来自打包字切片，gsim 来自原始 1 位态；`TimeAsync.time_o` 则是数据 mux 与无 else WHEN 的差异 |
| or | 186,093 | 38,146.659 | `TLSourceShrinker._nextFreeOH_T_3` 等前缀 OR：GrhSIM 63 位中间量，gsim 64 位中间量 |
| concat | 137,904 | 22,031.056 | 同一前缀网络把固定左移改写为切片与零拼接；gsim 保留 SHL |
| sliceStatic | 115,617 | 16,699.173 | 同一网络删掉不用的高位并截取左移输入；gsim 截位边界不同 |

`TLSourceShrinker` 的最低空闲位选择网络提供了可直接核对的代表例。令 `x=~allocated`：

```text
GrhSIM: y63 = x[62:0] OR concat(x[61:0], 1'b0)
gsim:   y64 = x64 OR SHL1(BITS62:0(x64))
```

后续相同模式继续以 2/4/8/16/32 位展开；GrhSIM 把不用的最高位收窄到 63 位，gsim 保留 64 位中间量，左移在 SV 中变为切片与零拼接。它同时解释 `or`、`concat`、`sliceStatic` 三类未匹配：两侧都在执行前缀 OR，签名不同不能证明 GrhSIM 的 OR 全属额外工作。另一端，GrhSIM 的 `nextFree_lo` 是 64 位 AND，gsim 的对应组合为 65 位 AND 后 `BITS63:0`；因此 `and` 未匹配也可能由中间位宽位置不同产生。

`mux` 代表例 `auto_out_a_bits_source` 的条件在 GrhSIM 中读 `packed_bits_*` 再切片；gsim 读原来的 `a_first_counter` 1 位寄存器。打包改变叶表示，条件差异向整棵 mux 传播；移除已知产物桶不能消除这种传递影响。另一代表 `TimeAsync.time_o` 在 GrhSIM 数据锥中为 `mux(enable,data,0)`，gsim 为没有 else 的 `WHEN(enable,data)`；保持旧值的条件在 GrhSIM 写端口 enable/mask 中，按预注册仅取数据锥的口径不包含它。两者都实现有条件更新，数据锥结构本身不是完整状态转换。

以上实例已从真实 IR 和 SV 核对；模块名只用于解释和定位，不是生产优化触发条件。后续变换必须以位宽/操作依赖模式触发，并验证包括 enable、mask、保持值和多次更新次序的完整语义。

### 复现与提交范围

生产代码取根仓库 `2871cbd` 的子模块集合（wolvrix `e49d454`），有效生产行为继承 `c69ac80`；无需 revert 或挑选其他分支。本节点只增加离线分析器、测试、Makefile 入口、报告与索引。输入文件内容身份与量级已在上文登记；若归档输入需重建，按 [NO00020](NO00020-grhsim-ir-gsim-module-compare-20260926.md)、[declaredSymbol 基线记录](grhsim-ir-declared-symbol-plan.md) 和 [NO00026](NO00026-grhsim-ir-declared-pack-census-20260928.md) 重建相同输入并先通过 G1。

在已初始化的项目 Python 环境中，分析与测试入口为：

```sh
source ./env.sh
make test_grhsim_paired_cone_diff
taskset -c 8 make analyze_grhsim_paired_cone_diff \
  GRHSIM_PAIRED_OUTPUT=ptmp/no00027_paired_cone_diff_20260928/reproduce/a
taskset -c 8 make analyze_grhsim_paired_cone_diff \
  GRHSIM_PAIRED_OUTPUT=ptmp/no00027_paired_cone_diff_20260928/reproduce/b \
  GRHSIM_PAIRED_REFERENCE=ptmp/no00027_paired_cone_diff_20260928/reproduce/a/summary.json
```

输出目录必须尚不存在。Makefile 默认输入就是本报告登记的归档；`GRHSIM_PAIRED_BASE` 可替换 pre/final 目录，`GRHSIM_PAIRED_DYNAMIC` 可替换动态 checkpoint、源码和两次计数日志的公共目录。复跑时为每次实验使用新目录和 RUN_ID，并将 stdout/stderr 重定向到仓库 `ptmp/`。

完整生产验收使用 `make xs_wolf_grhsim_ir` → `make xs_wolf_grhsim_ir_build_emu_pgo` → `make benchmark_grhsim_ir`：

- 生成的 `XS_GRHSIM_IR_BUILD` 指向本节点 `flow`，`XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR` 指向其 `model`；从 SV 起步，不启用 resume。`ROW_CONSTANT_FILL`、`OR_WRITE_MERGE`、`MIGRATE_BOUNDARY_OPS`、`DEMONITOR_REDUNDANT` 四个 `XS_WOLF_GRHSIM_IR_*` 开关均为 1；两份 profile 分别取 declaredSymbol 基线的 `vchg_profile.txt`、`migrate_profile.txt`，通过 `XS_WOLF_GRHSIM_IR_EDGECOMPLETE_PROFILE`、`XS_WOLF_GRHSIM_IR_MIGRATE_EC_PROFILE` 传入。
- 生成与 PGO 目标分别由 `timeout --signal=KILL 1800s` 包围并单独计时。`VM_BUILD_JOBS=32`，clang 22.1.2；PGO 训练沿用生产 difftest 与 CoreMark 输入，通过 `XS_EMU_PREFIX` 限制 161.1165 s、绑定 CPU=2 并用已有 `scripts/evict_exec.py` 驱逐 cache。日志/临时文件设置到本节点 `ptmp` 目录。
- 性能目标设置 `GRHSIM_IR_BENCH_OLD=ptmp/declsym_baseline_20260928/flow`、`GRHSIM_IR_BENCH_NEW` 为新构建、`GRHSIM_IR_BENCH_BASELINE_SECONDS=48.798`、`GRHSIM_IR_BENCH_PAIRS=3`、`GRHSIM_IR_BENCH_CPU=2`、`GRHSIM_IR_BENCH_PERF_STAT=0`，输出目录用新名字。所有仿真固定 `XS_NUM_CORES=1`、`XS_EMU_THREADS=1`、`XS_SIM_MAX_CYCLE=100000`，waveform/commit/RAM trace 关闭；禁止在性能窗口并行构建或分析。

本报告保留自包含的正式数值及结构例；生成代码、日志、profile、逐对导出表、波形和二进制均留在 `ptmp/`，不提交。节点树当前最佳仍为 NO00024，工作基线仍为 declaredSymbol 基线，总 goal 继续开放。

## 判定

**ACCEPTED（诊断节点）**。七项定量基线已经交付，G1a/G1b/G2–G6 全部通过；31 项聚焦测试、83 项依赖测试、完整生成/PGO 编译及六次交替 100k 等价检查均通过。新臂 Host 均值 **49.020667 s**，相对同窗口旧臂 **48.726667 s** 名义回退 **+0.603366%**，低于预注册 **+2%** 预算。改善秩次门未通过，不登记性能提升，最佳指针保持 NO00024。

H1 的高匹配率预测未获当前签名规则支持（GrhSIM distinct 签名匹配率 **3.5749%**），H2 的低于 1% 预测也未出现；诊断交付本身达到验收标准。原决策指标 **M-xo-dyn=30.6751% ≥ 1.0%**，支持继续形态恢复研究。叶表示、条件更新边界和中间位宽会传播结构差异，故该份额不能作为可删除工作量或性能收益估计；敏感性子集也不能代替预注册指标关闭路线。本节点不新增机制证伪条目。

后续立项应从输入已匹配的首次差异及实际 IR/SV 结构例中选择通用模式，在分区前的 GrhSIM IR 层验证完整状态更新语义，并重新测量动态计数与最终性能。本轮止于 NO00027 的完成与归档，不启动新节点；生产代码及子模块无本节点改动。
