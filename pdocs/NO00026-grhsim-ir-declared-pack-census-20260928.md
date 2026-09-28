# NO00026：同源 declared 信号的零散位重组普查（诊断）

| 字段 | 值 |
|---|---|
| 父节点 | declaredSymbol 基线（非节点，wolvrix `c69ac80`；谱系上接 NO00025） |
| 角色 | 诊断（优化节点的前置普查臂） |
| 状态 | **ACCEPTED**（五项基线交付，G1–G5 全过；两条候选路线按预注册阈值关闭） |
| 锚定指标 | M-fam（同源族规模）、M-align（现有打包的同源对齐度）、M-iso（族内更新锥同构率）、M-ctrl（控制签名相容子族规模）、M-dyn（候选族更新锥动态份额） |
| 指标阈值 | 交付五项定量基线，G1–G5 全过；**优化节点立项继续条件**：M-ctrl 可合并位具相当规模且 M-dyn ≥ 1.0% compute execs/cycle；M-dyn < 0.3% → 重组路线登记负向知识，不再立项变换节点 |
| 回退预算 | 零生产改动（仅新增默认关闭的诊断开关与分析脚本；门关时生产生成源逐字节一致）；最佳指针不动（declaredSymbol 基线 48.798 s），无性能回退预算 |
| RUN_ID | no00026_declared_pack_census_20260928 |
| 工作区 | ptmp/no00026_declared_pack_census_20260928/ |

## 基础选定（BASELINE）

- **代码基线**：declaredSymbol 基线 wolvrix `c69ac80` / 根仓库 `4fb7d2c`。生产开关全开，基线 Host **48.798 s**（SD 0.168 s），gsim+PGO 对照锚点 27.376 s。启动时工作区干净，无迂回。
- **立项动机**：NO00025（图差分重测）交付了 declaredSymbol 覆盖画像（M-decl：states 位加权 91.57%、declared 97,708/284,362、数组态 4,809、generateGroups 空集），证明语义锚点在位率足以支撑消费；同轮 M-cone 显示配对寄存器更新锥规模比均值 1.76（GrhSIM 8.08 vs gsim 4.79），离群集中于 firtool/ingest 标量化展开的同源散位族（RAT 表、LoadUnit 合并数据锥）。用户在 2026-09-28 指示立项：用 declaredSymbol 加强 GrhSIM IR 侧的零散操作打包。按惯例先做普查臂——静态候选规模与动态份额实测后再决定是否立项变换节点。
- **可测性前提（立项前已核实）**：
  - declaredSymbol 在 GrhSIM 侧为**纯符号名只读 metadata**（层次路径形态，`lowerGrhToGrhSim` 尾部注入，checkpoint 往返携带；计划文档 S4 设计原则：compact() 重编号使实体 ID 悬空，消费方按名字现查）。族聚类键 = 模块路径 + 去尾段 `_<digits>` 词干（NO00020 chunk-strip 规则），仅在 declared 集合内聚类——锚点内推断，不是名称匹配优化（纪律关系见 HYPOTHESIS）。
  - 更新锥测量设施现成（NO00020 M-cone：regWrite nextValue 反向锥、命名值截断为叶）；动态计数设施现成（前版 NO00025/NO00021 的诊断 reemit + 计数闭式校验）。
  - 打包来源（哪个原始 1-bit state 进了哪个 `packed_bits_*` 字）在现有 checkpoint 中**不可重建**（成员名在打包后消失，`mappings` 不记录）——本节点给 pack-bit-registers 加**默认关闭的诊断 dump 开关**记录成员名单（与 NO00020 导出开关先例同类：门关时生产输出逐字节不变）。
- **输入**：post-lower dump（`grhsim.verify` 后、语义 pass 前 raw 形态，打包前，普查候选空间）；pre-partition/final checkpoint（生产形态，形态分类与 M-dyn）；pack 成员名单 TSV（本节点新增开关）；reg_to_mem.tsv（既有报告）；动态负载 coremark-2-iteration 100k（端点 `240349/99996/100001/0x80000c0c`）。全部取自同一条 resume-from-flat-grh 流程（基线归档 flat GRH 复用）。
- **口径**：宇宙 = post-lower dump 中 name ∈ declaredSymbols 的 logic states（排除 `__event_`）；`__reg_to_mem_`/internal_tmp/`_op_*` 等非 declared 命名态为 pass 产物不进族。values 不独立成族，经更新锥进入分析。M-ctrl 签名沿用前版 NO00025 M-controls 口径（事件/边沿/历史初值/目标初值 + enable/mask 身份）；post-lower 无 quiescence projection，签名不含该位（近似，已注明）。
- **资源配置**：机器 32 核/187 GiB。诊断节点不重跑生产 PGO 构建；诊断 reemit/构建/运行为独立目录独立计时。日志与产物均在 ptmp 工作区。

## 假设提出（HYPOTHESIS）

- **H1（同源族是打包的天然单位）**：firtool 聚合标量化与 GRH ingest 展开的散位是模板化产物，declared 集合内按词干聚族能回收其绝大部分；若 M-fam 显示族规模可忽略，重组路线价值重估。
- **H2（族内更新锥普遍同构）**：同一声明的逐位/逐元素副本的更新逻辑同形（模位索引置换），预期同构率 >80%；若同构率低，说明散位差异是语义固有的，重组路线证伪。
- **H3（控制签名细分后仍有可合并余量）**：前版 NO00025 实测 ssit valid_array 族 3,679 行**逐行使能全不同**——字级合并的正确性前提（同 event/enable/mask/init 签名）不被 declaredSymbol 放宽。但全设计 declared states 中同签名子族的规模未知；M-ctrl 正面回答"细分后还剩多少可字级合并的位"。
- **与"禁止名称匹配优化"纪律的关系**（呼应计划文档 R6）：declaredSymbol 是来源属性不是名称文本，作诊断锚点/候选集合规；本节点纯诊断零变换；未来变换节点以族为**候选来源**时，触发与等价判定必须落在语义验证（控制签名相容 + 逐位等价）上。
- **与总目标的定量关系**：NO00016/17 已证伪"静态 op 数定价动态成本"，故本普查直接锚定动态份额 M-dyn（execs/cycle），静态规模（M-fam/M-ctrl）只作过程指标；方向顺风——NO00021 因果臂证明 pack-bit-registers 净正价值巨大（隔离移除 +4.858% Host），"加强打包"是在已证正方向上加码，而非被证伪的"消除 pass 产物"方向。

**指标定义与测量方法**：

- **M-fam（同源族规模）**：declared 符号（states 侧，排除事件簿记）按模块路径 + 词干聚族（尾段 `_<digits>` 逐段剥离）。报：族数、成员数分布、位宽分布、族成员位占宇宙位比例；成员生产形态分类（standalone=final 同名 state 存在 / packed=成员名单 TSV / memified=reg_to_mem.tsv / other）。
- **M-align（现有打包对齐度）**：每 `packed_bits_*` 字的成员族数/模块数；单族字比例；族→字散布分布。
- **M-iso（族内更新锥同构率）**：族成员 regWrite 的 enable/data/mask 三根反向锥（命名边界截断），规范化签名 = 操作数序 DFS 后序的 (kind, 位宽, 操作数引用) 序列，叶标签符号化（`FAM[k]`/`SELF`/原名/常量值）。同构 = 签名相等；另以独立回朔匹配器抽样复核（G3）。
- **M-ctrl（控制签名相容子族）**：族内按签名细分；报可字级合并子族（成员≥2）位规模、按生产形态细分。
- **M-dyn（动态份额）**：候选族（M-iso 同构 ∧ ≥2 成员）的生产侧锥（standalone 成员→自身 regWrite 锥；纯族 packed 字→字锥；混合字/形态不全→分列 mixed/incomplete 桶），跨族并集去重，execs/cycle = Σ body fires[op 所属 unit]/cycles；另报 M-ctrl 可合并子份子份额与安全上界（mixed 桶按整字锥超额归属 + incomplete 桶可测成员）。

**预注册门**：

- **G1（诊断纯净）**：诊断开关关闭时生产管线生成源与基线一致；同路径门关/门开双跑全产物逐字节一致；分析脚本同输入两轮输出逐字节一致。
- **G2（覆盖闭式）**：全部 declared states 计入某族或具名拒绝原因；族间位零重复计数；Σ族位+singleton位+拒绝位 == 宇宙位；形态分类和 == 宇宙成员数。
- **G3（同构判定正确性）**：合成夹具覆盖正例（位索引置换同构）/负例（拓扑/位宽/叶引用差异）；生产样本随机 ≥100 族独立复核，一致率 ≥99%。
- **G4（动态计数闭式与端点）**：两次独立 100k 动态运行计数逐键相同；Σ(body×站点数) 与 runtime 总计精确闭合；端点四字段精确、无 difftest mismatch。
- **G5（Top 交付）**：按 M-dyn 前五族交付完整成员清单、锥边界、动态份额、控制签名细分，及至少一族的 gsim 侧具名对照。

**证伪标准**：G3 精度不达标 → 同构检测器不可用，节点 REJECTED；门失败且归因为实现瑕疵 → 修正后全量重跑。节点 ACCEPTED 判据 = 五项基线交付 + G1–G5 全过；**是否立项变换节点按预注册阈值裁定**（M-dyn ≥1.0% 立项；<0.3% 登记负向知识；中间区间附敏感性论证后由用户裁定）。

## 代码实施（IMPLEMENTED）

**wolvrix 侧（子模块，pack-bit-registers 成员名单 dump，默认关闭）**：

- `wolvrix/lib/grhsim/pass/pack_bit_registers.cpp`（+42/-3）：pass 构造函数接 `std::filesystem::path report = {}`；合并循环内（`model.compact()` 前）仅当 report 非空时缓存成员名/初值为 std::string（reg_to_mem.cpp:1173-1175 同款先例）；compact 后写 TSV（表头 `packed_state\tbit_index\tmember_name\tinit_bit`，字内位升序、字间创建序）；工厂逐对解析 `--report <path>`，其余参数仍拒绝；**无参时零 I/O、零行为差异**。注意语义：packed 字名中的 id 是 **chunk 首成员的 regWrite op id**，非各成员自身 id。
- `wolvrix/tests/grhsim/test_cpu_emit.cpp`（+117/-2）：fixture 提取为 `packedBitRegistersFixture(bool)`，新增 `testPackedBitRegistersReport`——204 成员 8 字的 TSV 逐项断言（表头、成员名集合、位序号/初值、字名预算、顺序不变量）、不带 `--report` 时目录为空（零 I/O）、工厂仍拒绝未知选项。
- `wolvrix/docs/grhsim_ir/passes/pack-bit-registers.md`：删 "It has no options"，补 `--report` 段。

**根仓库侧**：

- `scripts/wolvrix_xs_grhsim_ir.py`：`--pack-bit-registers-report` 参数 + pass_options 接线（reg-to-mem-report 同款先例）。
- `Makefile`：`XS_WOLF_GRHSIM_IR_PACK_BIT_REGISTERS_REPORT ?=`（空=关）+ 命令行条件传参；普查双目标 `analyze_grhsim_declared_pack_census` / `test_grhsim_declared_pack_census`（惯例对齐既有 analyze_/test_ 块，含 `GRHSIM_DECLARED_PACK_SAMPLE_VERIFY/SEED`）。
- `scripts/grhsim_declared_pack_census.py`（约 1,000 行，编排与纯函数分离、确定性输出）+ `scripts/test_grhsim_declared_pack_census.py`（**23 单测**）。复用零复制：`Model`/`check_dynamic`（grhsim_bit_update_census）、`unit_index`（grhsim_residual_write_cones）、日志正则（grhsim_dynamic_stats）。
- **实施期口径修正登记**（TESTED 首轮发现，按惯例同节点修正）：
  1. `declaredSymbols` 尾键实测为**字符串表 1 基索引列表**（非名字面量列表）——脚本兼容两种形态。
  2. memified 形态只匹配 reg_to_mem.tsv 的 `first_state` 列（每个合并 memory 仅代表元可命中），非代表元成员落 other——欠计数口径在报告 note 注明。
  3. **M-iso 打包交叉校验的 premise 修正**：初版把"生产打包 ⇒ 同族同构"当校验门；pack-bit-registers 只按控制签名分组（data 锥不进 key，pack_bit_registers.cpp:94-103），混签名是预期而非违例——降级为信息统计（`m_align_iso_info`）。M-ctrl 交叉校验保留为门并加违例归因（`structural_control_signature` 解释项）。
  4. G3 抽样复核模式：`--sample-verify N` 用**独立实现**（显式有序双射图匹配，不走签名摘要）复核族同构判定，确定性种子。

## 结果测试（TESTED)

**设施验证**：wolvrix `make test_grhsim_cpu_emit` 1/1 PASS（97.56 s，含 report 新测）；`make test_wolvrix` 全量 54 测 51 过 3 失败——`transform-comb-lane-pack`/`transform-repcut`/`ingest-write-back-slice` 与计划文档登记的**预存失败基线逐点一致**（不经由本 pass）。scripts 侧 `test_grhsim_declared_pack_census` **23/23 PASS**；聚焦回归 `test_grhsim_checkpoint_identity` 11/11、`test_benchmark_grhsim_ir` 3/3 PASS。

**流程与计时**：py_install 重建（含新开关）→ flow 双跑（resume-from-flat-grh，基线 flat GRH + 双 profile）：门关 296.30 s、门开 301.37 s（<1800 门）；动态臂：reemit 48.21 s、构建 229.44 s、两次 100k 运行 173.365/174.990 s；普查四轮 89.05/85.27/85.55/85.71 s。

**G1 诊断纯净：PASS**。门关/门开双跑全产物逐字节一致（pre_partition.json、最终 checkpoint、post_lower.json、emit 生成源 `diff -r` 全等）——开关中性。门开轮对基线归档（full 路径）：counts 五项全等（values 3,113,262 / states 284,362 / operations 3,261,518 / init 284,362 / declaredSymbols 1,208,313）、op-kind 多重集 0 差、init 0 异行、declaredSymbols 逐条相等；state 名差异 357,266 条 **100% 为 `__event_` 重编号**（NO00020 登记的跨路径事件编号不稳定现象，0 条非事件差异）。诊断 reemit checkpoint 与基线生产 checkpoint **逐字节一致**。普查 run1==run2、run3==run4 输出逐字节一致。

**G2 覆盖闭式：PASS**。bit 闭式：族位 2,493,981 + singleton 位 2,056,590 + 拒绝位 0 == 宇宙位 4,550,571；形态闭式：92,899 standalone + 66,935 packed + 2,537 memified + 149,029 other == 311,400 宇宙成员。

**G3 同构判定：PASS**。23 单测含正例（位索引置换同构）/负例（拓扑/位宽/叶引用/多 writer）；生产抽样复核 100 族（同构判定 50 + 异构判定 50，种子 20260928）独立双射匹配 **一致率 100%**（≥99% 门），0 跳过。交叉校验：M-ctrl 门 22/1,697 违例**全部归因**——13 字差在 target_initial（普查签名含目标初值、pack key 不含，口径差异非缺陷）、9 字差在 enable_cone（post-lower 上结构相异、生产 pack 前被中间 pass 统一——样本 `packed_bits_1385205` 字内 7 个 `fusionDecoder$instrPairValid_*` 位按 pack 分组定义必然同键，属跨表单签名漂移）；结构化统一解释 0 条（初版"canonicalize 去重"假设不成立，实为 pass 重写）。M-iso 信息项：混签名字 1,654/1,697（97.5%）——pack 不约束 data 锥同构的直接实证。

**G4 动态闭式：PASS**。两次独立 100k 运行计数逐键相同；闭式精确闭合——group 调用 836,431,500 = Σ(body×站点数)、grp_pub 772,617,598、grp_fire 245,705,479 与 runtime 总计相等、compute 执行 91,061,544,463 与分区子树独立统计相等（与前版 NO00025 动态基线逐点一致）；端点四字段全对、无 difftest mismatch。

**G5 Top 交付：PASS**。按 M-dyn 前五族（并列 64.002 execs/cycle）交付：均为 `logEndpoint` 的 `*NSamples` 族（utilNSamples / enq_entry_valid_cntNSamples / other_entry_valid_cntNSamples / valid_cntNSamples / issue_datasource_bypass_histNSamples），各 21 成员 × 64 位、M-iso 全同构（1 签名类）、生产形态全 standalone；成员单 regWrite，锥 4 ops（add×1 + mux×2 + logicNot×1），叶含 `endpoint$step`（日志步进计数）与被观测信号（如 `cpu$l_soc$memory_araddr`）——日志采样寄存器族。gsim 具名对照（utilNSamples）：**21/21 精确同名同宽配对**（`logEndpoint__DOT__utilNSamples[_N]`，w=64），REG_DST assignTree 各 5 enodes vs GrhSIM 锥 4 ops（差 1 为 gsim 的 node-ref 叶物化风格，NO00020 已登记的口径差）。

### 五项定量基线

- **宇宙（post-lower）**：311,400 declared logic states / 4,550,571 位；declaredSymbols 总 1,208,313 中 896,913 无 logic state（wire/中间声明）、4,809 非 logic（数组态）。
- **M-fam**：**10,284 族** / 123,831 成员 / 2,493,981 位（**宇宙位的 54.8%**）；singletons 187,569 / 2,056,590 位。成员分布中位 4 / p90 19 / max 4,736。位宽分布：1 位族成员 56,700；64 位族成员 30,306 / 1,939,584 位（logEndpoint 日志阵列主导）。形态：standalone 92,899 / packed 66,935 / memified 2,537（欠计数口径）/ other 149,029（样本：`cpu$jtag$__jtag_TRSTn` 端口、`..._mem_ext$_R0_addr_d0` 存储器端口占位——DCE/端口类消亡态）。
- **M-align**：4,433 packed 字 / 66,935 成员行；**单族字仅 643（14.5%，位加权 20.6%）**；每字族数中位 3 / p90 20 / max 64；每字模块数中位 1 / p90 2；663 族成员跨字散布（散布中位 1 字）——现打包是纯控制签名驱动，族对齐度低但模块局部性尚可。
- **M-iso**：**全同构族仅 436/10,284（4.2%），成员 1,639/123,831（1.3%）**。按规模分层：2 成员族 244/3,240（7.5%）、3–4 成员 131/2,964、5–8 成员 36/2,386、9–16 成员 10/592、17–64 成员 15/910、**65+ 成员 0/192**——族越大越不同构。标量化兄弟的更新锥差异是语义固有的（逐位常量/邻接逻辑/边界截断各不相同），**H2 证伪**。
- **M-ctrl**：eligible 56,700（1 位族成员；拒绝：non_read_target_reference 54,713、target_initial_unknown 12,416、unsupported 2）；10,732 子族，可合并子族（≥2 成员）4,089 个 / **50,057 位**。**可合并位按生产形态：packed 31,705 / other 17,863 / memified 479 / standalone 仅 10**——控制签名相容但未被现打包器捕获的残余池 ≈ **10 位**（other 桶为消亡态无机会）。**H3 证伪**：现打包器已把相容位基本吃尽，无残余打包机会。
- **M-dyn**：候选族 436（同构 ∧ ≥2 成员）；可定价 162、混合字桶 111（423 位）、形态不全桶 163（3,870 位）。**union 171,068,759 execs = 1,710.67 execs/cycle = compute 的 0.188%**（compute 910,606.34/cycle）；M-ctrl 可合并子份额 0.898 execs/cycle。**安全上界**（混合字整锥超额归属 + 形态不全桶可测成员）：7,911.24 execs/cycle = **0.869%**（21,039 ops；不可归属成员 610 个为 memified/other 形态，成本在存储访问机，不属打包路线）。

## 判定

**ACCEPTED**（诊断节点：五项基线交付，G1–G5 全过，零生产改动，指针不动）。**两条候选路线均按预注册阈值关闭**：

1. **同源重组（向量化）路线关闭**：M-dyn 点估计 **0.188% < 0.3%** 负向知识线；安全上界 **0.869% < 1.0%** 立项线——即使归属不确定性全部按最大计，可寻址动态池也不达立项门槛。根因是 H2 证伪：族内锥同构率仅 4.2%，标量化散位的更新逻辑语义固有不同。
2. **打包补强/族对齐路线关闭**：M-ctrl 可合并但未打包残余池 = **10 位**——现打包器（纯控制签名分组）已捕获几乎所有相容位；M-align 显示单族字仅 14.5%，但在无残余可打包位的前提下，"按族重排已有打包"只剩生成代码局部性收益，无 op 量或动态份额收益，不值得变换节点。

**结论性知识**：declaredSymbol 上线后的首个消费测量表明，XiangShan 上"零散操作打包"方向无油水——不是因为锚点不够（覆盖 91.57% 位、族聚类 54.8% 位全部就位），而是因为**(a) 散位锥语义固有不同构、(b) 控制签名打包已近饱和**。declaredSymbol 的价值方向应转向章程第 5 步的其余用途（模块层次识别、语义信号锚定、generate 并行化——XS 无 generate 实例），而非打包增强。若未来 IR 形态大变（如新前端/新标量化策略），本普查设施可直接重测。

**机制证伪登记**（入索引证伪表）：declaredSymbol 同源族重组与打包补强路线——证据本节点 M-iso 4.2% / M-ctrl 残余 10 位 / M-dyn 0.188%（上界 0.869%）。

当前最佳指针不动（declaredSymbol 基线 `c69ac80`，Host **48.798 s**；本节点零生产改动，无性能重测）。设施留存：wolvrix `--report` 开关（默认关，门关逐字节中性已证）+ `scripts/grhsim_declared_pack_census.py`（23 单测）+ Makefile 双目标；工作区 `ptmp/no00026_declared_pack_census_20260928/`（flow-off/flow-on 双跑、dynamic 臂、四轮普查 run1–run4、全部日志）。
