# NO00027：gsim×GrhSIM 配对寄存器更新锥微观结构差分（诊断）

| 字段 | 值 |
|---|---|
| 父节点 | declaredSymbol 基线（非节点：wolvrix `c69ac80` / 根仓库 `d830b7c`，谱系上接 NO00024） |
| 角色 | 诊断（优化前置普查臂，同 NO00026 模式） |
| 状态 | **立项（预注册，待执行）** |
| 锚定指标 | M-pair（配对覆盖）、M-cone-cover（配对锥并集对全模型 compute 的静态/动态覆盖率）、M-leaf（锥叶对应率）、M-match（锥内 op/enode 结构签名匹配率）、M-xo（GrhSIM 单方多余 op 来源分类 × 静态 × 动态）、M-xg（gsim 单方多余 enode 分类）、**M-xo-dyn**（决策指标：排除三桶后 GrhSIM 单方多余 op 的动态份额） |
| 指标阈值 | 交付七项定量基线，G1–G6 全过；**优化节点立项继续条件**：M-xo-dyn ≥ 1.0% compute execs/cycle → 立项形态恢复节点（NO00022/24 模板）；< 0.3% → 微观图差分路线登记负向知识并关闭；中间区间附敏感性论证后由用户裁定 |
| 回退预算 | 零生产改动（wolvrix 与 reference/gsim 零改动，根仓库仅 scripts/pdocs/Makefile/ptmp）；指针不动，无性能重测 |
| RUN_ID | no00027_paired_cone_diff_20260928 |
| 工作区 | ptmp/no00027_paired_cone_diff_20260928/ |

## 基础选定（BASELINE）

- **代码基线**：declaredSymbol 语义锚点基线（wolvrix `c69ac80`、根仓库 `d830b7c`）。生产开关全开，基线 Host 48.798 s（SD 0.168 s），对照锚点 gsim+PGO 27.376 s，差距 1.780×。工作区干净，无迂回。
- **立项动机**：用户 2026-09-28 指示：先做微观配对锥对比，完成 NO00027。既有图差分（NO00020/25）止于模块级计数与锥规模比；NO00023 只普查写合并族残余写锥（ratio≥4 的 254 族局部 op 仅占全模型执行 0.765%，该前沿已采空）。**从未做过**：逐信号把 gsim enode 更新树与 GrhSIM op 锥做结构对齐，逐 op 标注来源并连接确定性动态计数。战役最大两笔收益（NO00022 −4.739%、NO00024 −1.349%）正是静态形态差分驱动，本节点把该方法推广到全量配对锥。
- **与既有证伪表的关系**：本节点不以"静态语句数定价动态指令成本"（NO00016/17 已证伪），动态份额一律取确定性 fires 闭式连接；不改变值承载/融合/删除任何 op（NO00009/11/16 证伪对象），产出仅为后续形态恢复节点的目标集与量级锚点。
- **输入**（全部为既有归档，零新生成）：
  - gsim 侧：`ptmp/no00020_gsim_module_compare_20260926/gsim-export/SimTop_PreCoarsen.json`（PreCoarsen 边界，5,588,394,875 B，NO00020/25 同输入）。
  - GrhSIM 侧 final：`ptmp/declsym_baseline_20260928/flow/xiangshan_grhsim_ir.json`（1,413,060,068 B）；pre-partition：`…/flow/pre_partition.json`（1,267,853,298 B，G1 语义一致门用）。
  - 动态臂：NO00026 诊断构建两次 100k 运行日志 `ptmp/no00026_declared_pack_census_20260928/dynamic-run{1,2}.log`（各 29,341 条 `sn` 行 + totals 行）；诊断 checkpoint `…/dynamic/xiangshan_grhsim_ir.json` 已与基线 final **逐字节一致**（NO00026 G1 已建立，本节点 G1a 复核 sha256）。生成源码目录 `…/dynamic/model/`（计数点闭式用）。
- **资源配置**：离线诊断，无仿真性能门槛；机器 32 核/187 GiB；墙钟如实记录（非门槛项）。gsim 全量解析约 85 s/40 GiB RSS（NO00020/25 实测）。

## 假设提出（HYPOTHESIS）

既有证据（NO00008 因子表：差距主因是每单位工作指令密度 8.54×；NO00020/25：扣除叶后静态 op 比 1.17× 基本对等）预测配对锥的 op 量大体相当，但不排除存在 gsim 没有对应物的 **ir 单方语义工作类**（非簿记、非三桶已知形态）——例如 ingest/firtool 标量化展开残留、位宽规范化冗余、写恢复未覆盖的表达式形态。本节点对其定量：

- **H1（结构匹配是主体）**：配对锥内大部分 GrhSIM op 可与 gsim enode 建立 1:1 结构签名对应（M-match 高位）；不匹配部分主要落在三桶已知形态与位宽/标量化规范化类。
- **H2（决策相关）**：排除三桶后，ir 单方多余 op 的动态份额 M-xo-dyn 可能低于 1.0% 立项线——此时微观图差分路线带证据关闭；若 ≥1.0% 则构成立即的形态恢复目标集。两个结果都是有效交付，不伪报方向。
- **口径声明**：
  - **配对**：复用 NO00020/25 的 `match_anchor_sets` 两阶段配对（精确规范化名 + chunk-strip），锚点集为 gsim REG_SRC ↔ GrhSIM 非 `__event_` logic states；组内成员按带后缀全名再配 1:1，剩余记未配对。declaredSymbols 用于校验 GrhSIM 侧锚点纯度（declared 覆盖率引用 NO00025 M-decl：位加权 91.57%）与多余 op 的模块归属标注。
  - **锥定义（两侧对称的全锥口径）**：GrhSIM 侧 = 寄存器 `core.state.regWrite` 数据操作数的完整反向锥，在 `core.state.read`/`core.input.read`/`core.state.memRead` 截断（读 op 本身计入锥、其操作数不展开），DAG 去重——复用 NO00023 `cone()` 全模式。gsim 侧 = REG_DST assignTree 从 root 展开的 ENode 锥，**递归内联命名引用**（NODE_OTHERS/REG_DST 引用展开其 assignTree），在 REG_SRC/NODE_INP/存储器端口节点/常量截断为叶，环保护（in-progress 引用记 `reg_dst_ref` 叶类）；lvalue 不可达天然排除。两侧"寄存器当前值/输入/常量/存储器读"四类叶一一对应。
  - **结构对齐（签名法，非图同构）**：两侧分别计算规范化签名——叶按配对关系给同一符号键；内部节点按（操作类, 子签名序列）递归，可交换操作子签名排序；规范化规则预注册：gsim `OP_PAD`/位宽填充透明穿透，`OP_WHEN` 压平为分支序列，GrhSIM 嵌套 `mux`/`prioritySelect` 链检测后压平为同构分支序列，常量按（值, 位宽）等价。签名相等即结构匹配；不等即不匹配，不做模糊匹配（不匹配部分由分类与 G5 解释）。distinct 签名口径为主、出现次数加权口径为辅。
  - **多余 op 来源分类（M-xo，穷尽且互斥，优先级序）**：① 三桶属主（owner ∈ {(reg-to-mem),(packed),(events)}，复用 NO00021 `attribute_op_modules` 属主传播）；② width_norm（位宽规范化 kind）；③ scalarization（位选/拼接/slice 类）；④ event_bookkeeping（非属主捕获的边沿簿记形态）；⑤ other_semantic（**决策相关类**——纯语义多余）。gsim 单方多余 enode（M-xg）同样分类（node_ref 复制/pad/when 重塑/存储器端口/other），仅作信息参考（gsim 侧无逐 enode 动态计数）。
  - **动态连接**：每 op execs = 所属 compute 单元 body fires（NO00023/26 闭式链路，`unit_index` schedule 驱动遍历 + `checked_fires` 端点校验）；族/类份额一律全局并集去重，禁止逐对相加（NO00023 11.1× 高估教训）；分母 = 全模型 compute 执行数/cycle（基线口径 91,061,544,463 execs/run ÷ 100,001 guest cycles）。
- **预注册门**：
  - **G1a（输入身份）**：final == NO00026 诊断 checkpoint（sha256）；pre vs final 语义数组逐项一致（NO00023 指纹口径）；gsim 导出与 NO00020 归档一致（sha256）；GrhSIM counts 段 18 项逐项相等；gsim 非存储器节点数 == 2,708,079。
  - **G1b（动态臂身份）**：dynamic-run1/run2 端点四字段 == (240349, 99996, 100001, 0x80000c0c)；两运行 fires/totals 逐键一致。
  - **G2（确定性）**：分析脚本同输入两轮全量输出逐字节一致（排除 gates.G2 子树）。
  - **G3（动态闭式）**：计数点闭式（group/publish 点数与生成源码一致）、grp_pub/grp_fire 闭式、compute 执行闭式、单元覆盖 missing/orphan = 0、锥 op 计数器覆盖 100%——全部复用 NO00026 口径。
  - **G4（对齐精度）**：固定种子抽样 ≥100 个配对，用独立重算实现复核签名匹配/不匹配判定与分类标注，一致率须 100%（实现瑕疵修复后全量重跑）。
  - **G5（闭式与解释）**：分类穷尽闭合（Σ 各类 == 不匹配总量，静态与动态双口径）；对 M-xo 动态份额 Top-5 类/族给出实际 IR/源码结构解释（NO00023 G5 模板）。
  - **G6（覆盖有效）**：M-pair 位加权覆盖双侧 ≥80%（沿用 NO00025 G3 门槛）；M-cone-cover 如实报告，若配对锥动态覆盖 < 30% compute，决策阈值结论限定于覆盖范围并显式声明。
- **证伪标准**：G4 不达标 → 对齐器不可用，节点 REJECTED；门失败且归因为实现瑕疵 → 修正后全量重跑。节点 ACCEPTED 判据 = 七项基线交付 + G1–G6 全过；是否立项变换节点按 M-xo-dyn 预注册阈值裁定。
- **回退预算**：零生产改动；指针不动（48.798 s），无性能回退预算。

## 代码实施（IMPLEMENTED）

（待执行后填写。）

## 结果测试（TESTED）

（待执行后填写。）

## 判定

（待执行后填写。）
