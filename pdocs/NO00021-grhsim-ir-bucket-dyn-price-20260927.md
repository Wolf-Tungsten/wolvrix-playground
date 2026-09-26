# NO00021: 三类单方 pass 产物桶的动态定价画像（诊断）

| 字段 | 值 |
|---|---|
| 父节点 | NO00019（当前最佳） |
| 角色 | 诊断 |
| 状态 | **ACCEPTED**（诊断：G1–G5 全过 + 四项定量基线 + D2 两臂 M-bnet 与链闭合交付；2026-09-27 终判） |
| 锚定指标 | **M-bexec**（分桶动态 op 执行/cycle，compute 域）、**M-bmon**（分桶受监测检测写 wr 与变化 ch/cycle）、**M-bwake**（分桶变化驱动的消费单元唤醒/cycle）、**M-bcommit**（提交域分桶静态构成 + 全局计数上下文） |
| 指标阈值 | 诊断节点：交付四项定量基线 + 有效性门 G1–G5 全过；G2 静态对账或 G4 监测域对账失败且归因于机制 → 分桶动态定价路线证伪（REJECTED） |
| 回退预算 | 零生产改动：默认管线、当前最佳指针、生产二进制不动；条件触发的反事实臂只在隔离工作区构建测量，不进生产。无性能回退预算 |
| RUN_ID | no00021_bucket_dyn_price_20260927 |
| 工作区 | ptmp/no00021_bucket_dyn_price_20260927/ |

## 基础选定（BASELINE）

- **父节点**：NO00019（当前最佳指针，GrhSIM-IR PGO 构建 Host **52.580 s**，wolvrix `a59e1b6` + 根仓库 `e458679`）。诊断节点不改生产路径，代码基线即最新提交，工作区干净，无迂回。
- **立项动机**：NO00020（ACCEPTED）结论第 2 条——三类 GrhSIM 单方 pass 产物桶合计 743,824 ops = 全部 op 的 21.1%，是首个可枚举的静态形态差异目标集（`(reg-to-mem)` 409,314 / `(packed)` 271,174 / `(events)` 63,336，gsim 侧无对应结构）；但该结论同时登记"静态存在 ≠ 动态成本（NO00016/17 教训），立项前须用动态口径核实这些 op 的动态份额"。本节点即该核实步骤：对三桶做动态定价，为后续"GrhSIM IR 层变换消除形态差异"（用户 2026-09-26 22:26 提示方向）的优化节点提供目标集与量级锚点。
- **基线测量（配置未变，复用归档值，不重跑）**：
  - gsim+PGO 锚点：Host **27.376 s**（3 次有效均值，SD 0.065 s）。
  - GrhSIM-IR 当前最佳：Host **52.580 s**（NO00019，3+3 均值，SD 0.216 s）；端点 `instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c`；差距 **1.921×（~25.2 s）**。
  - 既有定量锚点：NO00008 因子表（指令差距闭合于每单位工作指令密度 8.54×）；NO00019 M-net 3,944,136.5 instr/cycle、M-shrink 207,994.58 wr/cycle（Σwr=20,799,649,516/run）；NO00020 三桶静态 op 计数（上）。
- **输入核对**：
  - 生产 checkpoint `ptmp/no00019_migrate_ec_20260926/flow/xiangshan_grhsim_ir.json`（1.4 GB `wolvrix.grhsim.v1`；NO00019 语义门 ⅳ 已证其 strings/types/values/operations 段与 NO00015 归档逐字节一致，NO00020 G1c（修订语义口径）再证三 checkpoint 语义数组逐行相等——分桶静态计数必须精确复现 NO00020 值，见 G2）。
  - dyn run1 日志 `ptmp/no00019_migrate_ec_20260926/run1/logs/xs_wolf_grhsim_no00019_migrateec_run1_20260926.log`（NO00019 生产模型的 dynamic-stats 运行：31,612 条 sn 行、663,798 条 vchg 行、488 条 commit 行、kind/totals 行；NO00019 门 ⅸ 已证 run1/run2 逐字节一致，取 run1 即可）。
  - NO00020 分桶口径来源 `scripts/grhsim_gsim_module_compare.py`（分类器 `module_of_state_name`/`is_generated_value_name` 与 op 归属五级规则原样复用，保证静态对账同口径）。
- **代码状态核对**：wolvrix `a59e1b6`、根仓库 `e458679` + 本节点工具改动（新增分析脚本/单测/Makefile 目标；条件触发时新增隔离反事实臂的流程开关）。冻结面（GRH IR、GRH 已有 pass、XiangShan 与测试源码、reference/gsim）零改动。
- **资源配置**：离线分析为诊断，无性能门槛；机器 32 核/187 GB。条件触发的反事实臂遵循生产门槛：生成/编译（PGO 三阶段）各 <1800 s，仿真上限 = NO00019 归档均值 52.580 s × 1.5 = 78.87 s，`XS_EMU_CPU=2`、`XS_EMU_THREADS=1`、逐次 posix_fadvise、测量窗口机器空载。
- **止损线**：若分桶归属在最终 checkpoint 上无法精确复现 NO00020 静态计数（语义数组同一性不成立），先归因；归因表明归属口径与 dump 点不兼容 → 记实现瑕疵并改用 NO00020 pre-partition dump 重新锚定（动态 fires 键仍须连回最终模型，连不回则记机制证伪）。

## 假设提出（HYPOTHESIS）

- **假设 H1（可定价性）**：三类桶的动态成本可在既有确定性口径下闭式定价，无需新仿真运行：
  - **compute 域**（op 驻留于 compute supernode）：分桶静态归属 × 单元确定性 body fires（`[grhsim-dyn] sn` 行）→ 逐桶 execs/cycle，闭式精确（NO00017 G1 同款连接已验证，但只做执行计数、不做线性成本拟合）；
  - **监测域**（boundary 值的变化检测）：`[grhsim-vchg]` 逐值计数器按值名分桶 → 逐桶 Σwr/Σch，逐值精确；
  - **提交域**（commit 任务中的 memRead/memWrite/事件采样等）：计数器无逐 op 分辨率，交付逐桶静态构成 + 全局计数上下文（port_eval/port_fire/mw_gate/mw_fire/pub_*），不作逐桶动态分配——登记为口径限制。
- **假设 H2（可优化量级）**：至少一个桶的动态份额达到预注册触发线（见下），值得后续优化节点定向消除；若三桶全部低于触发线，则"消除单方 pass 产物形态"路线的收益上限被定量封死，该结论本身作为负向知识登记。
- **创新点**：本分支首个按**转换产物桶**轴的动态定价——把 NO00020 的静态形态地图与 NO00015/19 的确定性动态计数（单元 fires + 逐值 vchg）闭式连接；与 NO00012（逐值经济学普查锚定 NO00013/14/15/19）的诊断→优化锚定关系同构。
- **微观指标定义与测量方法**（分母 = NO00019 生产模型 + dyn run1，cycles=100,001）：
  - **M-bexec**：逐桶 execs/cycle = Σ_unit body(unit) × |unit 内该桶 op 数|，另给 (other) 与全模型总量（all-ops 口径 = Σ body×|unit ops|）；同时交付逐桶 × 逐 kind 构成。驻留分类：compute（compute supernode 内）/ commit（commit 任务子树内）/ detached（不在任何任务子树，如仅 init 可达）。
  - **M-bmon**：逐桶受监测值（vchg 行）数、Σwr/cycle、Σch/cycle 及占全模型份额；值分桶按值名走 `module_of_state_name` 同款规则，无名值经 owner 传播归属。
  - **M-bwake**：逐桶变化唤醒 = Σ_v ch(v) × n_consumer_units(v)（v 的不同消费 compute 单元数；commit 消费计入 commit 桶单列）——上界代理口径，登记为代理而非精确激活数。
  - **M-bcommit**：逐桶 commit 域驻留 op 的静态计数 × kind 构成 + commit 单元 488 个 ent 与 totals 行全局计数（port_eval/port_fire/mw_gate/mw_fire/pub_calls/pub_pending/pub_changes/cm_*）作上下文。
- **微观指标与总目标的定量关系**：总目标差距 = host 指令量 2.44× × CPI 0.84（NO00005），指令量差距闭合于每 dynOp 指令密度 8.54×（NO00008）。桶的指令成本量级带 = M-bexec × 全模型均值 instr/exec（NO00019：3,944,136.5 / ~995K ≈ 3.96 instr/exec）——只做量级带，不做逐 op 线性定价（NO00017 已证伪"逐 op 边际成本线性可加"）；反事实臂（若触发）给出该桶机制的**因果净值**（A/B Host 差），这是比任何闭式定价都强的量级证据。
- **预注册门**：
  - **G1（归属闭式）**：每个 op 恰好归属 (reg-to-mem)/(packed)/(events)/(other) 之一；归属管线与 NO00020 同码复用。
  - **G2（静态对账）**：三桶静态 op 计数 == NO00020 报告值**逐点相等**（409,314 / 271,174 / 63,336）；不等且归因于口径漂移 → 实现瑕疵；归因于语义数组同一性不成立 → 机制证伪。
  - **G3（动态闭合）**：sn 行单元键集 == checkpoint compute 单元键集（零孤儿）；Σ chg == totals.grp_fire 精确相等；分桶 execs + (other) execs == 全模型 all-ops 总量（构造闭式，误差 0）；驻留分类计数闭式（compute+commit+detached == totalOps）。
  - **G4（监测域对账）**：vchg 值 id 全部在界；Σ_vchg wr == **20,799,649,516**（NO00019 M-shrink 整数，归档值）精确相等；分桶 wr/ch 求和与总计闭式。
  - **G5（确定性）**：分析脚本对同一输入运行两次，summary 输出逐字节一致。
- **预注册 D2 触发规则（反事实因果臂）**：对桶 B ∈ {(reg-to-mem), (packed)}（两者分别有 `--disable-reg-to-mem` 隔离开关与待补的隔离 pack 开关），若 **M-bexec(B) ≥ 2% 全模型 all-ops 总量 或 M-bmon wr 份额 ≥ 2% 或 M-bwake 份额 ≥ 2%**，则构建其隔离反事实臂：与 NO00019 生产管线逐 knob 一致、仅去掉对应 pass（reg-to-mem 臂跳过 `grhsim.reg-to-mem`；pack 臂从 CPU_PIPELINE 中仅滤除 `grhsim.pack-bit-registers`，保留两次 canonicalize、bitwise-muxes、mux-chain-fold、used-bits 与两轮映射——不沿用既有 `--no-pack-bit-registers` 非隔离接线）。臂全门槛：gen <1800 s、PGO 编译 <1800 s、端点四字段精确 + difftest 干净（否则该臂记 INVALID 并按实现瑕疵处理）、3+3 交替 Host 对 NO00019 归档 PGO 二进制（`ptmp/no00019_migrate_ec_20260926/flow/emu/emu`）。交付 **M-bnet**（因果净值 = 臂均值 − 生产均值，带秩次判据）。`(events)` 为 ingest 级机制、无开关 → 不建臂（登记为口径限制）。
- **证伪标准**：G2/G4 失败且归因于机制（语义数组同一性不成立 / vchg 口径与生产模型不符）→ 机制性错误，节点 REJECTED 并登记机制证伪表；其余门失败归因于脚本错误 → 实现瑕疵，修正后重测（同一节点内）。
- **回退预算**：无（零生产改动；反事实臂仅隔离测量）。

## 代码实施（IMPLEMENTED）

- **分析脚本** `scripts/grhsim_bucket_dyn_price.py`（编排与纯函数分离，确定性输出：排序键、无时间戳）：
  - **分桶归属**：与 NO00020 `analyze_grhsim` 同码路径复用（`module_of_state_name`/`is_generated_value_name` 分类器 + 命名结果 → 首个 state ref → owner 传播 → 首个命名操作数 → `(anonymous)` 五级规则），op 恰好归属 `(reg-to-mem)`/`(packed)`/`(events)`/`(other)` 之一（G1）。
  - **驻留分类**：compute（compute supernode，`compute_task_units` schedule 走查）/ commit（commit 任务分区子树直挂 op）/ detached（不在任何任务子树）。
  - **动态连接**：`load_dyn_fires`（sn 行 body/chg/totals）+ vchg/commit 行解析；M-bexec = Σ body×桶内 op 数（逐桶 × 逐 kind）；M-bmon = vchg 逐值分桶 Σwr/Σch；M-bwake = Σ ch×消费 compute 单元数（上界代理）；M-bcommit = commit 驻留静态构成 + totals 全局计数上下文。
  - **门**：G1 归属闭式、G2 静态对账（`--expect-ops`）、G3 动态闭合（sn 键零孤儿/missing、Σchg==grp_fire、驻留计数闭式）、G4 监测域对账（vchg id 在界、Σwr==`--expect-vchg-wr`）、G5 两轮逐字节（调用方 cmp）。
- **单测** `scripts/test_grhsim_bucket_dyn_price.py`：**17 用例**——桶标签映射、五级归属（命名结果/sink state ref/owner 传播/普通模块/state.read 结果命名/全 op 有归属）、驻留分类（compute/commit/detached、compute 优先）、execs 连接（分桶 × kind、孤儿/缺失/静默单元）、监测域聚合（named 优先于 owner、越界检出）、唤醒数学、静态/驻留计数、vchg/commit 行解析——全过。
- **Makefile 目标**：`analyze_grhsim_bucket_dyn_price`（变量 `GRHSIM_BUCKET_MODEL/RUN/OUTPUT/EXPECT_OPS/EXPECT_WR/CYCLES`）、`test_grhsim_bucket_dyn_price`。
- **反事实臂流程**：`scripts/wolvrix_xs_grhsim_ir.py` 新增 `--disable-pack-bit-registers`（隔离接线：仅从 CPU_PIPELINE 滤除 `grhsim.pack-bit-registers`，保留两次 canonicalize、bitwise-muxes、mux-chain-fold、used-bits 与两轮映射；不沿用 `--no-pack-bit-registers` 非隔离旧接线）+ Makefile 旋钮 `XS_WOLF_GRHSIM_IR_DISABLE_PACK_BIT_REGISTERS`；reg-to-mem 臂用既有隔离旋钮 `XS_WOLF_GRHSIM_IR_REG_TO_MEM=0`（`--disable-reg-to-mem`，仅跳过该 pass）。臂脚本 `ptmp/no00021_bucket_dyn_price_20260927/arm_pipeline.sh`（gen 门槛 1800 s、PGO 编译门槛 1800 s、端点四字段经 `benchmark_grhsim_ir --expected-endpoint` 强制校验、3+3 交替、逐次 posix_fadvise、`taskset -c 2`）。
- 运行命令（两轮同参数，仅输出目录不同）：
  `make analyze_grhsim_bucket_dyn_price GRHSIM_BUCKET_OUTPUT=ptmp/no00021_bucket_dyn_price_20260927/analysis/runN`；单次全量 **~46 s** 墙钟（1.4 GB checkpoint 解析 + owner 传播主导）。

## 门槛修订登记（2026-09-27，任何臂测量之前登记）

**修订 1（反事实臂参照系）**：预注册 D2 触发规则原文要求臂"与 NO00019 生产管线逐 knob 一致、仅去掉对应 pass"并对 NO00019 归档二进制做 3+3。实施期发现该表述不可行：NO00019 管线中 `demonitor-edge-completion` 与 `migrate-boundary-ops-ec` 两个 profile 驱动 pass 的 profile 键为**值 id**（`v id wr ch`/`u id ...`），而臂去掉 reg-to-mem 或 pack-bit-registers 属语义变换、会整体重编号值空间——NO00015/NO00019 的 profile 在臂模型上必然 stale（pass 对越界 id 硬报错）。修订为：臂管线 = `migrate-boundary-ops + demonitor-redundant`（NO00014 等价边界配置，两个静态 pass 无 profile 依赖）± 目标 pass；参照系 = 同配置 REF 新鲜构建（而非 NO00019 归档二进制），两个 3+3 窗口分别测量 REF↔ARM-R2M、REF↔ARM-PACK；另加第三个窗口 NO00019↔REF 闭合与生产配置的链（NO00019 = REF 配置 + edge-completion + migrate-ec，其已知增量 −0.175% 可对照）。该修订保持对比的因果纯度（±pass 唯一差异），代价是测得净值对应 NO00014 等价配置而非 NO00019 精确配置——edge-completion/migrate-ec 合计仅削 ~2.4% boundary 写（NO00015/19 实测），与目标 pass 机制的交互为二阶，登记为口径限制。触发判定沿用预注册 2% 线（M-bexec/M-bmon/M-bwake 三选一）。

## 结果测试（TESTED）

> 管线：分析两轮（`analysis/run1`/`run2`，各 ~46 s）→ 门判定 → D2 触发判定 → 反事实臂三流构建（`arm_pipeline.sh`）→ 三个 3+3 测量窗口。全部产物在 `ptmp/no00021_bucket_dyn_price_20260927/`。

### 有效性门（D1 分析，G1–G5 全过）

- **G1 归属闭式：PASS**。3,531,463 个 op 全部获得唯一桶标签（未归属 0）。
- **G2 静态对账：PASS**。三桶静态 op 计数与 NO00020 报告值**逐点精确相等**：`(reg-to-mem)` 409,314、`(packed)` 271,174、`(events)` 63,336——最终 checkpoint 语义数组与 NO00020 pre-partition dump 同一（NO00020 G1c 修订口径）的直接再证。
- **G3 动态闭合：PASS**。sn 行 31,612 单元键与 checkpoint compute 单元键**零孤儿、零缺失**；Σchg == totals.grp_fire == **254,170,299** 精确；驻留分类闭式（compute+commit+detached == 3,531,463，detached=0）。
- **G4 监测域对账：PASS**。663,798 条 vchg 值 id 全部在界；Σwr == **20,799,649,516** 与 NO00019 归档 M-shrink 整数精确相等。
- **G5 确定性：PASS**。run1/run2 的 summary.json/summary.md 经 `cmp` 逐字节一致。
- 附带交叉核验：本模型 all-ops 总量 99,461,779,346/run 对 NO00017 登记的 NO00015 模型 99,495,719,495 偏差 −0.034%，方向与 NO00019 迁移收缩 fires 一致。

### D1 定价表（四项定量基线）

**M-bexec（compute 域动态执行，总量 994,607.8 execs/cycle）**：

| 桶 | 静态 ops | execs/cycle | 份额 |
|---|---|---|---|
| (reg-to-mem) | 409,314 | **148,526.2** | **14.93%** |
| (packed) | 271,174 | **75,370.3** | **7.58%** |
| (events) | 63,336 | **43,025.3** | **4.33%** |
| (other) | 2,787,639 | 727,686.1 | 73.16% |

三桶合计 **266,921.8 execs/cycle = 全模型动态 op 执行的 26.83%**（静态占比 21.1% 的 1.27 倍——桶 op 所在单元的平均点火率高于全模型均值）。逐 kind 构成（execs/cycle）：(reg-to-mem) = and 53,703.7 + or 44,312.3 + bitSelect 11,673.3 + logicNot 11,603.1 + mux 11,156.9（地址译码/掩码合并机）；(packed) = and 26,698.1 + or 19,836.8 + bitSelect 11,825.6 + eq 7,677.9（位提取/合并机）；(events) = constant 16,759.2 + system.task 7,432.4（事件历史常量与携带事件引用的系统任务）。

**M-bmon（受监测 boundary 值，总量 663,798 值、208K wr/cycle）**：

| 桶 | 受监测值 | wr/cycle | wr 份额 | ch/cycle | ch 份额 |
|---|---|---|---|---|---|
| (reg-to-mem) | 63,977 | 24,090.4 | 11.58% | 117.1 | 0.95% |
| (packed) | 32,171 | 8,046.0 | 3.87% | 521.6 | 4.23% |
| (events) | 5,686 | 1,468.4 | 0.71% | 7.7 | 0.06% |
| (other) | 561,964 | 174,389.6 | 83.84% | 11,692.6 | 94.76% |

(reg-to-mem) 的 wr:ch = 206:1——检测写绝大多数静默（写使能点火但数据极少变化），检测簿记成本真实存在而变化流贡献极小。

**M-bwake（变化驱动唤醒，上界代理，总量 ~57.5K wakes/cycle）**：(packed) 522.6/cycle（0.91%）、(reg-to-mem) 391.5/cycle（0.68%）、(events) 17.8/cycle（0.03%）——三桶状态的变化唤醒贡献全部 <1%，"打包字变化唤醒读者并集"的 widen 担忧在本负载下不成立（packed 桶 ch 份额 4.23% × 读者单元数有限）。

**M-bcommit（提交域静态构成 + 全局计数上下文）**：commit 驻留 op（静态）：(reg-to-mem) 33,616（memWrite 33,024 + memWriteSeq 434 + memFill 158）、(packed) 4,216（全部 regWrite）、(events) 0。全局计数（/cycle）：mw_gate **36,229.2** vs mw_fire 6,640.4（写使能门评估：实际点火 = **5.46:1**，门评估本身是大头）、port_eval 6,695.9 vs port_fire 4,696.1、grp_pub 8,541.9、pub_pending 277.8、pub_changes 172.6；commit 单元 488 个、ent 中位 49,597。逐桶动态分配受计数器分辨率限制（预登记口径限制），但 memWrite 静态构成的 88.7%（33,024/37,208）属于 (reg-to-mem) 桶——mw_gate 36.2K/cycle 的主要贡献者。

**指令成本量级带**（M-bexec × 全模型均值 3.96 instr/exec，NO00019 perfstat；NO00017 已证伪逐 op 线性定价，仅作量级带）：(reg-to-mem) ≈ 588K instr/cycle（~14.9% 总指令）、(packed) ≈ 298K（~7.6%）、(events) ≈ 170K（~4.3%）。注意 NO00016/17 教训方向：簿记/译码类 op 的单次执行成本大概率低于全模型均值（帧塌缩），量级带偏上界；因果净值由反事实臂直接测量（下节）。

### D2 触发判定

预注册触发线（2%，三选一）：**(reg-to-mem)** M-bexec 14.93%、M-bmon wr 11.58% → **触发**；**(packed)** M-bexec 7.58%、M-bmon wr 3.87% → **触发**；**(events)** 无开关不建臂（预登记限制）。按修订 1 构建 REF/ARM-R2M/ARM-PACK 三流。

### D2 反事实臂（构建与测量）

> 中断与恢复登记：04:06 构建链（`gen_build ARM-R2M && gen_build ARM-PACK`）在 ARM-R2M 构建完成后（04:33）随上一会话中断终止，ARM-PACK 未进入；残留的 04:00–04:13 无旋钮 ARM-PACK gen（日志含 `pass grhsim.pack-bit-registers`，= REF 配置，臂无效）整体废弃，04:35 以隔离旋钮重跑 gen（日志 0 匹配，旋钮生效）。恢复不改变预注册口径：REF/ARM-R2M 产物为中断前完成且校验通过，测量三窗口在恢复后同一空载窗口内执行。

**构建记录（门槛 gen/编译各 <1800 s，编译 -j32）**：

| 流 | gen 墙钟 | gen 出口 | PGO 编译墙钟 | 编译出口 | 臂隔离校验 | 训练运行端点 |
|---|---|---|---|---|---|---|
| REF | 801.47 s | 0 | 658.79 s | 0 | —（migrate+demonitor 两 pass 均在日志） | — |
| ARM-R2M | 894.00 s | 0 | 731.10 s | 0 | `grhsim.reg-to-mem` 0 匹配（未运行） | 四字段精确（240349/99996/100001/0x80000c0c），difftest 干净 |
| ARM-PACK | 845.73 s | 0 | 692.88 s | 0 | `grhsim.pack-bit-registers` 0 匹配（未运行） | 四字段精确，difftest 干净 |

emu sha256：REF `c20f349e…03fda1`、ARM-R2M `9f409e8e…1c8e96`、ARM-PACK `f2e7bd6f…40d02b`。PGO 三阶段（插桩编译 → difftest 训练 → profile-use 重建）与生产口径一致。

**测量口径**：三个 3+3 交替窗口（`benchmark_grhsim_ir`，逐次 posix_fadvise、`taskset -c 2`、`XS_EMU_THREADS=1`、waveform/commit/RAM trace 关、cutoff 78.87 s = 52.580×1.5，运行前预登记）；全部 18 次运行端点四字段精确（240349/99996/100001/0x80000c0c）、退出 0、difftest 干净（端点由 benchmark 强制校验，任一不符即 INVALID 中止——未发生）。

**窗口 1：REF ↔ ARM-R2M**（reg-to-mem 隔离移除，Host s）：

| 运行 | REF | ARM-R2M |
|---|---|---|
| 1 | 53.190 | 59.980 |
| 2 | 52.416 | 60.156 |
| 3 | 52.574 | 59.789 |
| 均值（SD） | 52.727（0.409） | 59.975（0.184） |

**M-bnet(R2M) = +7.248 s = +13.747%**：全部 3 次 ARM-R2M 运行慢于全部 3 次 REF（U=9、单侧 p=1.0、Cohen d +22.9、Cliff δ +1.0）——方向一致性极强的大回退。

**窗口 2：REF ↔ ARM-PACK**（pack-bit-registers 隔离移除，Host s）：

| 运行 | REF | ARM-PACK |
|---|---|---|
| 1 | 52.444 | 55.029 |
| 2 | 52.453 | 55.149 |
| 3 | 52.564 | 54.932 |
| 均值（SD） | 52.487（0.067） | 55.037（0.109） |

**M-bnet(PACK) = +2.550 s = +4.858%**：同样全部新慢于旧（U=9、p=1.0）。

**窗口 3：NO00019 ↔ REF**（链闭合，Host s）：

| 运行 | NO00019 | REF |
|---|---|---|
| 1 | 52.144 | 52.298 |
| 2 | 52.361 | 52.374 |
| 3 | 52.353 | 52.426 |
| 均值（SD） | 52.286（0.123） | 52.366（0.064） |

REF 慢 +0.080 s = **+0.153%**（U=7、单侧 p=0.9、秩次不显著）——edge-completion + migrate-ec 两 profile pass 在本窗口的增量与 NO00019 登记的 −0.204%（Host）/−0.147%（M-net）同号同量级，REF ≈ 生产配置成立，两臂净值对 NO00019 配置的代表性（修订 1 口径限制）得到实测支撑。

### 判定（终判：ACCEPTED）

- **H1（可定价性）成立**：三桶动态成本在既有确定性口径下闭式交付（G1–G5 全过、零新仿真；commit 域逐桶动态分配按预登记口径限制交付静态构成 + 全局计数上下文）。
- **H2 实测走向与预期相反**：(reg-to-mem)/(packed) 两桶动态份额均超 2% 触发线（M-bexec 14.93%/7.58%），按预注册建臂后，**M-bnet 两个均为大回退**（+13.747%/+4.858%，秩次全序、p=1.0）。含义：这两个静态份额巨大的单方 pass 产物桶，恰恰对应**净正价值最大的两个转换 pass**——它们产物形态的动态成本（合计 26.83% execs）远小于被它们消除的替代形态成本。"**回退/消除 (reg-to-mem)、(packed) 单方产物形态以提速**"的路线被因果测量封死；NO00020 三桶目标集中仅 (events) 未被本实验覆盖。
- **口径边界（如实登记）**：臂移除的是**整个 pass**（回退到 pass 前 IR 形态），测得净值界定"回退 pass"的代价；保持 pass 压缩语义、仅替换产物形态（如把 reg-to-mem 的访存形态换成 gsim 式别的承载）的变换不受本次测量直接约束，但立项门槛已被定量抬高——新形态须先保住 pass 的 +7.25 s/+2.55 s 收益再谈改进。(events) 为 ingest 级机制、无开关（预登记口径限制），未建臂；其 4.33% M-bexec 中 constant 16,759.2/cycle 占大头，NO00016 已证伪常量/恒等 op 逐条删除路线。
- **验收对照**：诊断节点预注册验收 = 四项定量基线交付 + G1–G5 全过；D2 触发规则执行完毕，M-bnet（两臂 + 链闭合）交付。正确性门槛（18 次端点精确 + difftest 干净）、时间门槛（gen/编译均 <1800 s）全过，零生产改动、当前最佳指针不动（NO00019 52.580 s）→ **ACCEPTED**。
- **后续方向约束（登记）**：① 不得再以"删除/回退 reg-to-mem 或 pack-bit-registers 产物"立项（本节点因果证据）；② (reg-to-mem) 桶 wr:ch=206:1 的静默检测写（24,090 wr/cycle 对 117 ch/cycle）与 mw_gate 36,229/cycle vs mw_fire 6,640/cycle（5.46:1）是两个已定量的簿记过剩点，但消除方式必须保住 pass 的收益语义（例如收紧检测/门评估的触发精度，而非回退形态）；③ (events) 桶如需定价须先在 ingest 层造隔离开关。
