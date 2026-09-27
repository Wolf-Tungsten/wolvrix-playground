# NO00025：declaredSymbol 基线上的 gsim×GrhSIM 模块级图差分重测（诊断）

> 本报告**覆盖前版 NO00025**（`NO00025-grhsim-ir-bit-update-census-20260927.md`，一位寄存器更新普查，2026-09-27 归档）。前版内容留存于 git 历史（本提交之前的任意父提交可见）。覆盖系用户 2026-09-28 明确指示，节点编号单调递增惯例本次让位于该指示；前版的动态普查结论不受本节点影响，但其文档槽位被重用。

| 字段 | 值 |
|---|---|
| 父节点 | declaredSymbol 基线（非节点：wolvrix `c69ac80` / 根仓库 `b6543d1`，谱系上接 NO00024） |
| 角色 | 诊断 |
| 状态 | ACCEPTED |
| 锚定指标 | M-name（寄存器位加权锚点匹配率）、M-opcount（模块级 op/enode 计数对照）、M-kinddelta（公共 bucket 构成差分）、M-cone（配对寄存器更新锥规模比）——沿用 NO00020 设施口径重测；新增 **M-decl**（declaredSymbol 覆盖率普查） |
| 指标阈值 | 交付五项定量基线；G1a/G1b/G1c（语义口径）/G2/G3/G4 全过；新增归因门 **G1d**：新代码 final 对 NO00024 归档（同生产开关）的 op-kind 多重集、state 名多重集、init 语义全部 0 差 |
| 回退预算 | 零生产改动；最佳指针不动（declaredSymbol 基线 Host 48.798 s），无性能重测 |
| RUN_ID | no00025_gsim_module_rediff_20260928 |
| 工作区 | ptmp/no00025_gsim_module_rediff_20260928/ |

## 基础选定（BASELINE）

- **代码基线**：declaredSymbol 语义锚点基线已落地并提交（wolvrix `c69ac80`、根仓库 `b6543d1`，2026-09-28；计划与实施记录见 [grhsim-ir-declared-symbol-plan.md](grhsim-ir-declared-symbol-plan.md) §7）。生产开关全开（行常量填充/OR 写合并/边界迁移/冗余监听关闭 + edge-completion/migrate-ec 动态 profile + 三阶段 PGO），基线 Host 48.798 s。工作区干净，无迂回。
- **立项动机**：用户指示在 declaredSymbol 基线上重做 NO00020 的 gsim×GrhSIM 模块级图差分，并覆盖前版 NO00025 槽位。两个待答问题：(a) declaredSymbol 落地是否改变 NO00020 的形态对比结论；(b) declaredSymbol 在生产 IR 上的实际覆盖画像——计划第 5 步（GRHSIM pass 取用语义）需要这个基线。
- **输入**：
  - gsim 侧复用 NO00020 归档导出 `ptmp/no00020_gsim_module_compare_20260926/gsim-export/SimTop_PreCoarsen.json`（PreCoarsen 边界，同源未变，不重导出）。
  - GrhSIM 侧 pre-partition / final dump 取自基线生产管线归档 `ptmp/declsym_baseline_20260928/flow/`（pre_partition.json、xiangshan_grhsim_ir.json）；full = keep-origins 变体 `ptmp/declsym_baseline_20260928/full/xiangshan_grhsim_ir_full.json`（本轮新生成，276 s）；archive = NO00024 归档 final `ptmp/no00024_or_write_recovery_20260927/flow/xiangshan_grhsim_ir.json`（**同生产开关的旧代码 checkpoint**）。
- **口径声明**：NO00020 轮 GrhSIM dump 是**默认管线**（NO00022/NO00024 写恢复开关关闭），本轮是**生产配置**（全开）。因此对 NO00020 的任何指标差异都混合两个因素：写恢复的形态效果 + declaredSymbol 落地。归因手段：以 archive 为 final 再跑一轮同一分析（下称 **archive 归因轮**）——它与本轮新代码共享全部生产开关，唯一变量是 declaredSymbol 落地本身。
- **资源配置**：离线诊断，无仿真性能门槛；机器 32 核/187 GiB；墙钟如实记录（非门槛项）。

## 假设提出（HYPOTHESIS）

- **H1（语义中性）**：declaredSymbol 落地不改变最终 IR 语义——对 NO00024 归档（同生产开关）的 op-kind 多重集、state 名多重集、init 语义（属性名解析后）全部 0 差；净增仅为 declaredSymbols 尾表与字符串表/事件重编号漂移。
- **H2（归因）**：M-name/M-opcount/M-kinddelta/M-cone 对 NO00020 轮的一切变动全部来自 NO00022/24 写恢复的形态效果；declaredSymbol 落地对四项指标零扰动（archive 归因轮与新轮逐点相等）。
- **预注册门**（沿用 NO00020 设施，G1c 按其修订后的语义口径）：
  - **G1a** 导出闭合：gsim 节点计数与导出日志一致；GrhSIM counts 段与实际数组逐项相等。
  - **G1b** dump 点代表性：pre-partition 与同 run final 的 op-kind 多重集 0 差。
  - **G1c** 复现性（语义口径）：final vs full 语义数组逐行相等（差异可归类为字符串/事件重编号）；final vs archive 的行对齐异行须全部可归因。
  - **G1d**（本节点新增，归因门）：final vs archive 的 op-kind 多重集 0 差、state 名多重集 0 差、init 行解析字符串表索引后 0 语义差。**出现非零语义差 → declaredSymbol 落地存在未登记副作用，节点 REJECTED 并回查基线提交。**
  - **G2** 确定性：分析脚本同输入两轮输出逐字节一致。
  - **G3** 锚点有效性：寄存器位加权匹配率双侧 ≥80%。
  - **G4** 存储/IO 锚点：全部配对或未配对项逐一归因。
- **回退预算**：零生产改动（wolvrix 与 reference/gsim 零改动，根仓库仅 pdocs 与 ptmp 产物），指针不动，无性能回退预算。

## 代码实施（IMPLEMENTED）

零生产改动。实施内容全部为离线分析与一次性校验脚本：

- 复用 NO00020 设施 `scripts/grhsim_gsim_module_compare.py`（未修改）；单测 `make test_grhsim_gsim_module_compare` 本轮 **28/28 PASS**。
- 三轮正式分析 run1/run2/run3（`make analyze_grhsim_gsim_module_compare`，各 **~180 s** 墙钟）；archive 归因轮一轮（**142.6 s**；`--grhsim-full/--grhsim-archive` 自比占位，仅消费 M-name/M-opcount/M-kinddelta/M-cone 与 owner 桶，门结论不取自该轮）。
- 新增 **M-decl 普查**（一次性脚本 `decl_coverage.py`，读 pre-partition dump）：declaredSymbols/generateGroups 计数、states 与 values 的 declared 覆盖（计数与位加权）、非 declared 命名态归因桶（`__event_`/`__reg_to_mem_`/internal_tmp/other）、层次深度直方图与顶层模块集中度。
- 新增 **G1d 校验**（一次性内联脚本，口径与分析器一致）：op-kind 多重集按 `strings[op[1]-1]` 解码；state 名多重集；init 行按结构解析属性名索引（`start`/`count` 等字符串表引用）后逐行比较。

## 结果测试（TESTED）

**门**（run1；G2 由 run2/run3 承担）：

- **G1a PASS**：gsim 2,708,079 非存储器节点（与导出日志末次 RemoveDeadNodes 精确一致）+ 2,274 NODE_MEMORY；assignTree 引用全在界。GrhSIM counts 段 18 项逐项相等：states 284,362、values 3,113,262、operations 3,261,518、operands 7,421,860、results 3,113,262、object_refs 453,849、strings 11,422,110、origins 11,320,354、types 846、functions 34、inputs 8、outputs 5、interface 13、dialects 1、稠密 id 全真。
- **G1b PASS**：pre-partition vs final op-kind 多重集 **0 差**——「dump 点形态即生产形态」在 declaredSymbol 基线上继续成立。
- **G1c PASS（语义口径）**：final vs full 仅 strings（438,263 行）与 origins（11,320,103 行）漂移，**全部语义数组 0 异行**——keep-origins 变体不改变语义；final vs archive 行对齐异行为 operations 233,119 / values 28,896 / states 6,264 / init 2,048 / mappings 1 / strings 内容漂移，经 G1d 全部归因为重编号（见下）。
- **G1d PASS（归因门）**：final 对 NO00024 归档——**op-kind 多重集 44/44 kind 全等**（总 ops 两侧同为 3,261,518）；**state 名多重集 0 差**；values/states/operations/init 计数逐项相等；init 的 2,048 个行对齐异行全部解析为属性名（`start`/`count`）字符串表索引漂移，解析后 **0 语义异行**。两侧唯一净增 = `declaredSymbols` 尾表 **1,208,313 条**。**H1 成立。**
- **G2 PASS**：run2 以 run1 为参照（排除 gates.G2 子树）逐字节一致；run1==run3 同为真。
- **G3 PASS**：位加权匹配率 **gsim 85.69% / GrhSIM 88.08%** ≥ 80%。
- **G4 PASS**：存储器配对 **499 组**（gsim 2,274 / GrhSIM 6,857），未配对全部归因到可枚举类；顶层 IO 配对 **12/12**。

### 五项定量基线

**M-name（寄存器锚点）**：锚点 gsim 148,956 REG_SRC（2,987,952 位）↔ GrhSIM 97,461 非事件 logic states（2,925,994 位；另排除 `__event_*` 180,044 个/位）。匹配 **67,279 组**（精确 66,913 + chunk-strip 366），覆盖 gsim 67,432 寄存器 / GrhSIM 68,357 states。位加权覆盖 **gsim 85.69%**（2,560,499/2,987,952）、**GrhSIM 88.08%**（2,577,257/2,925,994）；含事件参照口径 82.98%（2,577,257/3,106,038）。未匹配桶：GrhSIM 侧 `module_path_absent` 27,282 个/343,199 位、`renamed_or_split` 1,822 个/5,538 位；gsim 侧 `module_path_absent` 78,508 个/368,026 位、`renamed_or_split` 2,724 个/57,058 位、`memory_port_node` 292 个/2,369 位。

对 NO00020 轮的变动：GrhSIM 覆盖 87.79%→88.08%（+0.29pp），`module_path_absent` −2,441 个/−11,773 位；gsim 覆盖 85.93%→85.69%（匹配组 67,474→67,279，gsim `module_path_absent` +195 个/+6,989 位）；`renamed_or_split` 两侧逐点不变。**archive 归因轮的全部 M-name 字段与本轮逐点相等**——以上变动全部是 NO00022/24 写恢复的形态效果（寄存器总数 100,776→97,461、事件态 185,067→180,044 同源于此），declaredSymbol 落地零扰动。**H2 对 M-name 成立。**

**M-opcount（模块计数对照）**：全局 gsim 2,710,353 nodes / 13,159,630 enodes（不变）vs GrhSIM **3,261,518 ops / 3,113,262 values**（NO00020 轮 3,531,463 / 3,379,131，**−269,945 ops = −7.6%**，写恢复效果）；enode/op = **4.03**（NO00020 轮 3.73）；扣除 node_ref+const 叶后 gsim 计算类 enode 3,804,830 对 GrhSIM ops 之比 1.08×→**1.17×**——「静态 op 量两侧基本对等」的 NO00020 结论仍成立，且 GrhSIM 侧已更少。46,067 个模块行，四项闭合校验全过。Top 差异（|Δ|，括号为 NO00020 轮值）：`…ctrlBlock_rob` enodes 1,361,151 vs ops 227,245（266,541），en/op 5.99（5.11）；`…decoderComp_csBundle` 571,423 vs 0（不变）；`logEndpoint` 768,050 vs 252,682（不变）；`(reg-to-mem)` +401,787（+409,314）；`…rob_rab` 427,588 vs 87,813（87,716）；`(packed)` +271,202（+271,174）；`(mixed)` +104,738（+120,709）；`cpu` +101,356（不变，`_RANDOM` 等 firtool 随机化产物）。

**M-kinddelta（构成差分，全局）**（bucket：gsim / GrhSIM / Δ，括号为 NO00020 轮 Δ）：node_ref 8,337,148/0/−8,337,148（不变）；const 1,017,652/28,526/−989,126（−989,148）；mux_control 1,230,877/328,034/**−902,843**（−876,944）；bitwise_logic 917,837/**1,612,927**/**+695,090**（+909,714）；slice_index 770,341/464,867/−305,474（−305,498）；compare 311,905/193,484/−118,421（−93,018）；aggregate_concat 287,838/230,282/−57,556（−56,935）；arithmetic 122,959/110,153/−12,806（−13,389）；shift 108,285/7,316/−100,969（不变）；cast_width 40,738/0/−40,738（不变）；state_reg_access 0/194,921/+194,921（+201,551）；memory 6,870/72,028/+65,158（+62,576）；special 7,180/13,763/+6,583（不变）；statement 0/5,204/+5,204（+5,183）；io 0/13/+13（不变）。

三类 GrhSIM 单方 pass 产物桶合计 **736,193 ops = 全部 op 的 22.6%**（NO00020 轮 743,824 = 21.1%）：`(reg-to-mem)` 401,787（bitwise 掩码合并 243,407 + memRead/memWrite 62,828 + 索引 slice 41,335 + 写使能 mux 36,498）、`(packed)` 271,202（bitwise 163,692 + slice 72,728 + 边界比较 17,976）、`(events)` 63,204（bitwise 22,771 + const 16,587 + 边沿 special 13,763）。bitwise_logic 单方膨胀 +695,090 的 **61.8%**（429,870）落于该三桶（NO00020 轮 47.7%），加 `(mixed)` 38,561 后 67.4%——即写恢复削掉的 214,624 个 bitwise 膨胀几乎全在三桶**之外**的设计逻辑侧（被恢复的 OR 写网络本体），桶内形态基本未变。owner 桶 values 口径（archive 归因轮逐点相等）：(reg-to-mem) 338,959、(packed) 262,500、(events) 49,441、(mixed) 104,738、(dead) 1,127、(top) 881。

**M-cone（配对寄存器更新锥规模）**：67,279 对全部链接成功（misses 0）。gsim 锥中位 4 / p90 7 / p99 12 / 均值 4.79 / max 944（不变）；GrhSIM 锥中位 5 / p90 15 / p99 38 / **均值 8.08 / max 2,209**（NO00020 轮均值 10.90 / max 9,406 / p99 40）；grhsim/gsim 比中位 1.50 / p90 2.29 / **均值 1.76**（NO00020 轮 2.59）。离群样本：`…rat_v0Rat_difftest_table`（GrhSIM 锥 1,540 / 边界叶 1,534 vs gsim 2，chunk-strip 配对）、`…LoadUnit_0/1/2_s3_merged_data_frm_pipe`（各 1,082/1,153 vs 4）、`…AluDiv_Div_divDataModule_rCarryReg`（817/348 vs 6）。NO00020 轮的最大离群族 `…rat_vecRat_difftest_table_*`（锥 2,575）与 `…vecRat_arch_table`（1,973，47 成员）**消失**——OR 写恢复收敛 RAT 重命名表写网络的直接形态效果。archive 归因轮 M-cone 逐点相等。

**M-decl（declaredSymbol 覆盖普查，新增口径；pre-partition dump）**：`declaredSymbols` **1,208,313 条**，`generateGroups` **0**（XiangShan 经 firtool 后无 generate 块，计划的 generate 特别标注在本设计无实例可验）。states 284,362 中 **declared 97,708（34.36%）**，**位加权覆盖 91.57%**（2,844,300 / 3,106,038 位）；其中数组态 4,809 个。非 declared 命名态全部可归因：`__event_` 180,044（边沿簿记）、`__reg_to_mem_` 2,048（reg-to-mem 产物）、internal_tmp 346、other 4,216。values 3,113,262 中命名 3,052,741，其中 declared 407,585（占命名 **13.35%**）——中间 SSA 计算值不带声明语义，符合设计（declaredSymbol 锚定 wire/reg 声明点而非全部中间值）。层次深度直方图峰值 9 层（319,861 条），8/10 层次之（274,337/228,035），最深 16 层（512 条）；顶层集中度 `cpu$l_soc` 1,135,166 条（93.9%）。

### 归因汇总

| 因素 | 证据 | 结论 |
|---|---|---|
| declaredSymbol 落地（c69ac80） | G1d 三口径 0 差；archive 归因轮 M-name/M-opcount/M-kinddelta/M-cone/owner 桶与本轮逐点相等 | **语义与形态双重中性**；净增仅 declaredSymbols 尾表 |
| NO00022/24 写恢复（相对 NO00020 默认管线） | archive 轮对 NO00020 轮的全量差异 | ops −7.6%、M-name 覆盖 +0.29pp、M-cone 均值 10.90→8.08、bitwise 膨胀 −214,624 的全部来源 |

## 判定

**ACCEPTED**（诊断节点：G1a/G1b/G1c（语义口径）/G1d/G2/G3/G4 全过，五项定量基线全数交付，零生产改动，指针不动）。核心结论：

1. **declaredSymbol 落地的语义中性被结构级证实**（H1）：对同开关旧代码 checkpoint 的 op-kind/state 名/init 三口径 0 差，唯一净增是 1,208,313 条 declaredSymbols——新基线「功能正确」的声明从仿真端点扩展到 IR 结构级。
2. **NO00020 的图差分画像在生产配置下的更新全部归因于写恢复**（H2）：archive 归因轮与本轮逐点相等，declaredSymbol 对四项形态指标零扰动。静态 op 总量 −7.6% 后两侧静态计算量仍基本对等（1.17×），「8.54× 动态密度差距非静态 op 量投影」的 NO00020 结论**不被推翻**。
3. **首个 declaredSymbol 覆盖画像（M-decl）**：states 位加权 91.57%、计数 34.36%，命名 values 13.35%，generateGroups 空集——语义锚点基础设施在位率良好，第 5 步（GRHSIM pass 取用语义）的覆盖基线就位。
4. **形态差异目标集更新**：三桶 736,193 ops（22.6%）、bitwise 膨胀 61.8% 落于三桶；M-cone 离群从 RAT vecRat 族转移到 v0Rat_difftest_table 与 LoadUnit 合并数据锥。后续图差分对照一律以本轮 run1（`ptmp/no00025_gsim_module_rediff_20260928/analysis/run1/module_compare_report.json`）为准，NO00020 轮报告仅作历史参照。

当前最佳指针不动（declaredSymbol 基线 `c69ac80`，Host **48.798 s**；本节点零生产改动，无性能重测）。设施留存：NO00020 对比设施（脚本 + 28 单测 + Makefile 双目标）未修改；本轮三轮 + archive 归因轮报告、M-decl 普查（`decl_coverage.py`/`decl_coverage.json`）均在 `ptmp/no00025_gsim_module_rediff_20260928/`。
