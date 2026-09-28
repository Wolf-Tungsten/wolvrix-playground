# NO00028：写使能约束下的数据选择恢复普查（诊断）

| 字段 | 值 |
|---|---|
| 父节点 | declaredSymbol 基线（非节点，wolvrix `c69ac80`；当前代码 `e49d454`，根仓库 `c463b86`，谱系上接 NO00024） |
| 角色 | 诊断（分区前条件写恢复的优化前置普查） |
| 状态 | **ACCEPTED**（BASELINE→HYPOTHESIS→IMPLEMENTED→TESTED 全部完成，G1–G6 通过） |
| 锚定指标 | M-guard（可证明的数据选择替换数）、M-dead（全局移除候选的动态执行量）、M-boundary（候选中受监测值的动态检测写量）、M-shared（有其他使用者而不能删除的候选） |
| 指标阈值 | 四项定量基线交付，G1–G6 全通过；M-dead ≥1.0% compute 或 M-boundary ≥0.5% 检测写支持后续变换；否则关闭本节点的保守匹配子集，不关闭其他条件写恢复 |
| 回退预算 | 零生产改动；同窗口重建臂 Host 均值回退最多 +2% |
| RUN_ID | no00028_guarded_write_census_20260928 |

## 基础选定（BASELINE）

启动时工作区与各子模块干净，NO00001–NO00027 均已终态，本轮新增 NO00028。工作基线遵循 goal 的 declaredSymbol 重置，无迂回。NO00027 定量给出：未匹配 mux 46,201.399 execs/cycle；代表例 `TimeAsync.time_o` 的 GrhSIM 数据为 `mux(enable,data,0)`，gsim 为无 else 的 `WHEN(enable,data)`。两者的完整更新语义可能相同，故本节点先用写使能证明选择条件，不能直接删除单方未匹配 op。

固定输入和资源沿用父基线：CoreMark 2 iteration，100,000 cycles、CPU=2、单线程、waveform/commit/RAM trace 关闭。机器 32 逻辑 CPU、187 GiB，编译 jobs=32。基线 Host 48.798 s（SD 0.168 s）、gsim+PGO 27.376 s，配置未变不重测 gsim。离线分析 CPU=8，性能窗口停止离线分析。

完整 SV→C++ 和三阶段 PGO 各以 Make 启动计时，1800 s 截止；未插桩仿真以 48.798 s 为比较值，截止 73.197 s。PGO 训练以父基线插桩 107.411 s 为比较值，截止 161.1165 s。每次运行前 posix_fadvise 驱逐 page cache。六次性能顺序预登记为 old1,new1,old2,new2,old3,new3；old 为 declaredSymbol 归档，new 为本节点独立完整构建。所有临时输出归入 `ptmp/no00028_guarded_write_census_20260928/`；仅终态后提交。

## 假设提出（HYPOTHESIS）

**H1**：寄存器写使能蕴含数据根部选择条件时，可直接把该写端口的数据换为已存在的被选分支；禁写时数据不影响状态，事件、写掩码、旧状态保持与多写次序原样保留。不克隆表达式，不全局替换共享 mux，不改变任何其他消费点。根部 mux/单 bit bitSelect/prioritySelect 可连续剥离，但遇到不能证明的条件立即停下；中间 concat、位运算、存储写和 latch 不在本节点范围。

**H2**：端口替换不必然删除 mux。须把全部替换同时作用于虚拟使用图，再按所有实际消费者判断失活 op；有外部使用者的共享根不得算入 M-dead。动态量取失活 op 的全局并集，连接同 checkpoint 的 compute body 次数。读边界与常量不计入候选删除量，已有无用 op 不计本节点收益。

证明只解释二态 1 bit 的常量、not/logicNot、and/or/xor、logicAnd/logicOr、eq/ne、mux/bitSelect、同类型 assign，其余值作为彼此独立的 Boolean 原子。每条证明最多 12 个原子、4,096 个 BDD 节点、256 个展开值；超限/环/未知常量拒绝。写端口必须通过形状、二态类型、目标及事件引用检查；无需假定输入可达性、端口互斥或特定初值。enable 恒假单列，不把无条件选择归功于本假设。

指标与性能关系使用本分支实测：NO00027 未匹配 mux 为 **46,201.399 execs/cycle**，全模型 compute 为 **910,606.339 execs/cycle**。NO00016 删除 **0.543%** 平凡局部动态 op 仅降低 **0.00543%** 总 host 指令；相反 NO00013 删除 **4,559.4 次/cycle** 检测写使总 host 指令降低 **0.898%**。因此不按 op 个数线性预测时间，单列候选受监测值的实际检测写；1.0% compute / 0.5% 检测写仅为是否继续实施的成本筛选线，不是预期加速率。基线动态分母由 NO00026 两次确定性日志复核，候选指标本节点首次交付。

预注册检查：

- **G1 输入及语义身份**：pre-partition 与 final 的语义数组和字符串前缀一致；final 与 NO00026 dynamic checkpoint SHA256 一致；本轮完整生产 checkpoint/模型源与父基线逐字节一致。
- **G2 确定性**：离线分析同输入运行两轮，摘要和候选表逐字节相同。候选选择不使用模块名或源名。
- **G3 动态有效**：两份 100k 日志端点精确为 `240349/99996/100001/0x80000c0c`，body/vchg/totals 逐键一致；compute 和生成源码计数点闭式复核；候选 op 的 compute 归属与计数器无缺失。
- **G4 语义证明**：对所有接受的端口替换，使用独立布尔真值枚举，穷举 ≤12 个原子下 enable 与全部选择链，确认 enable 成立时原根恰为替换数据；无法独立验证则拒绝，不能当验收样本。
- **G5 全局失活与闭合**：使用者减计数与从全部副作用根反向活跃遍历两套实现得到同一新增失活 op 集合；M-dead 分类和、动态并集和精确闭合；共享根单列；给出动态 Top-5 实例及前后完整更新方程。
- **G6 正式验收**：聚焦语义反例测试及相关依赖测试通过；完整 SV 生成和 PGO 编译各 <1800 s；6 次 old/new 交替 100k 运行全部等价，新均值回退 ≤+2%，记录均值、样本 SD、效应量与秩次。

H1/H2 不成立或机会池低于筛选线不妨碍诊断基线交付；检查失败默认实施瑕疵，修复并重测。只有无法交付可信定量基线才考虑 REJECTED，且须定量复盘。

## 代码实施（IMPLEMENTED）

新增只读分析器 `scripts/grhsim_guarded_write_census.py`、聚焦测试及 Makefile 的 `analyze_grhsim_guarded_writes` / `test_grhsim_guarded_writes`。它在与 pre-partition 语义逐项一致的模型上做决定，分区仅用于连接已归档动态计数；不改变生产 pass、emit、调度或任何子模块。BDD 与独立真值位向量校验全部接受的替换；引用计数与全图活跃遍历校验全部新失活 op。已有失活 op、常量、读操作不冒充本次可删除量。初版 32 项聚焦测试通过，覆盖条件正反蕴含、优先级、共享消费者、重复操作数、已有死锥、未知/四态值、类型、事件、预算和环。

首轮诊断（85.16 s）发现证明器直接展开整个条件，连复杂表达式的 `E⇒E` 都可能因 12 原子预算而漏掉，不能据此判断机会大小。修复后先把选择条件的现有 ValueId 当作共同抽象叶，再尝试原有有界展开：独立任意赋值包含真实电路所有情况，故该抽象保守且不假定逻辑可达性；预算和筛选阈值不变。每层选择分别穷举，最终替换由等式传递保证。增加三项反例测试，35 项通过。首轮数字作废，仅保留为实现瑕疵记录；正式两轮均使用修复版。

第二、三轮输出一致，但人工复核 Top-5 发现 CSR 一例的条件本身为 `!w_wen & w_wen & ... = 0`，选择恒定，与写使能无关。按原口径“不把无条件选择归功于本假设”，新增 `unconditional_selection` 拒绝桶；共同抽象叶也须额外检查可识别的恒定使能/条件。此前两轮候选量不作最终验收。该修订收紧收益归因，不改筛选阈值。最终 **40 项聚焦测试**通过，另有 **86 项依赖测试**通过（配对锥 31、位更新 27、写锥 25、benchmark 3）。集成测试覆盖共享写端口计数去重、输入只读/确定性、计数器缺失和生产身份漂移拒绝。

首次完整生成尝试在 Makefile 环境检查处立即失败（wall 0.00 s，尚未生成任何文件）：当前 shell 未 source env.sh。现成 `.venv` 已可用，后续经项目显式提供的 `SKIP_WOLF_ENV_CHECK=1` 与绝对 `PYTHON` 路径运行，所有安装/构建仍只经 Makefile。失败记录保留，不计验收。

## 结果测试（TESTED）

### 已完成的全流程与静态检查

完整 SV→C++ **814.38 s**、三阶段 PGO **632.40 s**（均从各自 Make 启动计时、退出 0），分别低于 1800 s。本轮 final checkpoint、往返 checkpoint 均与父基线逐字节一致；pre-partition checkpoint 也逐字节一致，**4,255 个**模型 C++/头文件/Makefile 内容一致。因此复用父基线 profile、动态计数和 gsim 锚点的输入身份没有改变。PGO 训练 Host **108.170 s**，低于插桩训练截止 161.1165 s；端点 `240349/99996/100001/0x80000c0c`、IPC 2.403586、difftest 干净，不混入未插桩性能。六次交替性能全部有效，详见下表。

最终普查以第四、五轮为准，Make 墙钟分别 **106.21 / 103.99 s**，峰值 RSS **12,197,380 / 12,197,436 KiB**，均退出 0。两轮摘要、证明表、失活 op 表逐字节相同，分别为 **75,652 / 116,642 / 1,235 B**；下面数值来自修订后的选择集，不包含四个无条件选择。

| 门 | 定量检查 |
|---|---|
| G1 | pre/final 语义数组、字符串前缀一致；final 与动态 checkpoint SHA256 一致；counts 全部 21 项及 state/value/op 稠密 ID 通过；本轮生产身份亦通过 |
| G2 | 第四、五轮三份结果文件全部逐字节相同；分析器退出 0，确定性门通过 |
| G3 | 两个既有 100k 动态运行端点一致；29,341 单元全部字段和 totals 相同，vchg/kind 逐键相同。group **836,431,500**、grp_pub **772,617,598**、grp_fire **245,705,479** 与源码/运行闭式相等；compute **91,061,544,463 execs/run**；vchg 与 kind 检测写和均 **18,763,033,746**、变化和均 **1,191,179,119**；候选 compute 归属缺失 0 |
| G4 | **152 个**接受端口全部经独立真值向量验证，合计 **880 个**抽象输入赋值，最大 **6 个**原子；139 个用共同条件叶证明，13 个需展开证明；错误 0 |
| G5 | 两套全图算法所得新失活 op 集合完全相同，分类静态和 **154 ops**、动态和 **228,090 execs/run**、检测写和 **224,778/run** 精确闭合；基线原有 1,225 个失活计算不计本节点贡献 |
| G6 | 40 聚焦 + 86 依赖测试、完整生成与 PGO 编译通过；六次 100k 端点一致，全部退出 0；新均值名义变化 −0.304414%，+2% 回退预算通过 |

### 四项指标与范围

分母为 **100,001 guest cycles**，不是日志中的 `cycleCnt=99996`。固定 checkpoint、输入与周期下 body/vchg 计数两次逐键相同，计数类指标可精确比较；它们不是 host 指令数。

| 指标 | 实测 |
|---|---|
| M-guard | **97,051** 个 regWrite 中，**152** 个端口可替换；覆盖 **151** 个不同选择 op。只替换该端口的数据操作数，不全局改变原值 |
| M-dead | 全局新增失活 **154 ops**，**228,090 execs/run = 2.280877/cycle = 0.000250479% compute**；分母 **910,606.338567 execs/cycle**。距离 1.0% 筛选线约 **3,992 倍** |
| M-boundary | 候选中 **138 个**受监测值，**224,778 检测写/run = 2.247758/cycle = 0.001197983%**；全模型 **187,628.461175 检测写/cycle**。距离 0.5% 筛选线约 **417 倍** |
| M-shared | **16 个**可替换端口的数据根因仍有使用者而保留（对应 **15 个**不同选择 op）；不能把端口替换数当成 op 删除数 |

新增失活分类如下，动态量均为全局 op 并集，不累加各写锥：

| kind | ops | execs/run | 检测写/run |
|---|---:|---:|---:|
| mux | 139 | 224,985 | 224,364 |
| concat | 5 | 1,035 | 0 |
| eq | 3 | 621 | 0 |
| sliceArray | 3 | 621 | 0 |
| add | 2 | 414 | 414 |
| or | 1 | 207 | 0 |
| reduceOr | 1 | 207 | 0 |
| 合计 | 154 | 228,090 | 224,778 |

所有写端口按最终首要状态互斥分类：非选择数据根 **27,454**；使能恒真 **17,138**、恒假 **4**；无法证明 **28,914**；超过 12 原子预算 **23,129**、超过 256 展开值预算 **1**；选择类型不符合 **250**、写类型不符合 **5**；无条件选择 **4**；接受 **152**，合计 **97,051**。

**覆盖限制**：23,129 个原子超限端口的根 op 并集仍有 **859,687,356 execs/run**，未证明端口的根 op 并集有 **1,078,722,156 execs/run**；这些只是工作量，不能视为可删除量，也不是全锥上界。未展开存储写、concat/位运算内部选择、宽比较位级关系。因此本节点仅关闭“当前有界证明器已经证明的根选择替换集合”的生产立项，不能据此关闭所有条件写恢复或 NO00027 微观图差分路线。

### 完整更新语义与 Top-5 实例

`regWrite` 操作数为 `[E, D, M, event0, ...]`，分别表示 Boolean 写使能、新数据、逐位写掩码和事件输入；对象引用为 `[目标状态, event0历史, ...]`，`event_edges` 给出每项边沿极性。令 `F` 为原有事件检测结果、`q` 为旧值，则位宽内状态更新为：

```text
q' = F && E ? ((q & ~M) | (D & M)) : q
```

若在任意抽象输入赋值下证明 `E => C`，原数据 `D=mux(C,A,B)` 可在此写端口替换为 `A`；若证明 `E => !C` 则换为 `B`。`F/E/M`、历史更新、各写端口顺序全部保留，故任意旧值、掩码和事件都得到同一 `q'`；多写按相同次序逐项应用。优先选择必须先证明前序条件均假，不能直接跳到后序真条件。下一生产变换仍需重新分区、自举 profile 和运行等价检查。

以下名称仅用于定位说明，选择规则完全由类型、ValueId 和 Boolean 依赖决定。表中的“执行量”是被移除根的 body 次数，不能按例累加代替 M-dead。

| 实例（简写层次） | 宽度 | 原数据与证明 | 替换数据 | 根执行/run |
|---|---:|---|---|---:|
| memBlock.dtlb_st.req_out_0_debug_robIdx_value | 9 | `mux(s0_use_non_prf_flow, s0_uop_robIdx, 0)`；使能是请求来源 OR，展开证明蕴含前者 | 原有 `s0_uop_robIdx` prioritySelect，内部选择保留 | 73,248 |
| memBlock.dtlb_st.req_out_1_debug_robIdx_value | 9 | 同形；使能为 `io_stin_valid OR vector_valid`，展开证明蕴含条件 | 原有 9 bit 请求 robIdx 选择结果 | 73,248 |
| backend.memCtrl.ssit.data_array.r_ssid | 5 | `mux(C, D, 0)`，`E=C & P`；C 为 packed state 第 18 bit 的读取，P 为原写条件 | 原 5 bit D | 38,861 |
| backend.memCtrl.ssit.data_array.r_1_ssid | 5 | `E=地址不冲突 & C & P`，故 `E=>C`；无端口互斥假定 | 原 5 bit D | 38,861 |
| memBlock.prefetcher.bertiOpt.detlaTable.entries_0_counter | 4 | `E=!0 & (计数>5)`，`D=mux(E,0,选中计数+1)` | 常量 0，禁写时仍保持旧状态 | 2 |

上述五例均为 posedge、全位写掩码，改变数据的证明并不依赖这一特例。前四根占总新增失活执行量 **98.30%**，属于请求调试字段及 SSIT 更新；其余大多很冷。第五例虽有递增/数组选择等数据分支，实际只执行 2 次，不能按静态锥大小推断热点。四个被排除的 CSR 选择共 **45,420 execs/run**，条件本身矛盾，属于常量规范化而非写使能恢复。

NO00027 的 `TimeAsync.time_o` 仅是本节点动机，未进入本次接受集合。原 RTL 的完整更新含复位写零及有效变化时采样两种情况：`reset ? 0 : valid_changed ? input_time : old_time`。不能从数据锥的一条零分支推断它在所有有效写入下都无用，这也说明必须把选择条件和写使能分别命名、分别证明。

### 六次交替性能与判定

2026-09-28 **15:14:33–15:19:28（Asia/Shanghai）** 同一窗口，严格按预登记 old/new 交替；CPU=2、单线程、100k、关闭 trace，每次驱逐 page cache，窗口内无本节点编译或离线分析。

| 顺序 | 构建 | Host s | emu 墙钟 s | Make/emu 退出 | 等价性 |
|---|---|---:|---:|---|---|
| 1 | old1 | 49.108 | 49.14 | 0/0 | 四字段一致，difftest 干净 |
| 2 | new1 | 49.272 | 49.30 | 0/0 | 同上 |
| 3 | old2 | 48.904 | 48.95 | 0/0 | 同上 |
| 4 | new2 | 48.640 | 48.67 | 0/0 | 同上 |
| 5 | old3 | 49.156 | 49.22 | 0/0 | 同上 |
| 6 | new3 | 48.808 | 48.88 | 0/0 | 同上 |

全部端点为 `instrCnt=240349 / cycleCnt=99996 / guestCycles=100001 / PC=0x80000c0c`，无作废补跑。旧臂均值 **49.056000 s**、样本 SD **0.133806 s**；新臂均值 **48.906667 s**、SD **0.327349 s**。新减旧 **−0.149333 s / −0.304414%**，通过 +2% 回退预算；Cohen d **−0.597187**、Cliff delta **−0.333333**、Mann–Whitney U(new) **3**、改善方向单侧精确 **p=0.35**，秩次门未过。生产模型源码相同，本节点不声称性能改善，最佳指针不动。

**ACCEPTED（诊断）**：四项指标交付，G1–G6、完整生成/编译、100k 等价、六次交替性能和预算均通过。H1 的局部条件替换有 **152 个**实证；H2 的“共享使用决定能否删除”亦成立。可证明集合实际很小，且四个请求字段更新根占新失活工作 **98.30%**；不是把原始未匹配 mux 的 46,201 execs/cycle 转化为同等冗余。

按预登记关闭本节点已证明集合的生产立项：M-dead **0.000250479% < 1.0%**，M-boundary **0.001197983% < 0.5%**。这是否定当前候选规模足够的判断，不否定条件替换等价规则；超预算/未证明集合和更深数据条件化仍未裁定，索引的负向知识条目明确限制范围。未实现生产变换、未调整现有优化开关。当前最佳仍为 **NO00024**，工作基线仍为 declaredSymbol `c69ac80`，总 goal 未关闭，本轮不启动 NO00029。

## 复现与归档范围

根代码基线为 `c463b86`，wolvrix `e49d454`（生产行为继承 `c69ac80`，无需 revert/cherry-pick）。本节点只增加根仓库的分析器、测试、Makefile 入口及报告/索引，不修改任何子模块或生产 pipeline。

已初始化 `.venv` 下的入口：

```sh
make test_grhsim_guarded_writes SKIP_WOLF_ENV_CHECK=1 PYTHON="$PWD/.venv/bin/python"
taskset -c 8 make analyze_grhsim_guarded_writes \
  SKIP_WOLF_ENV_CHECK=1 PYTHON="$PWD/.venv/bin/python" \
  GRHSIM_GUARDED_OUTPUT=ptmp/no00028_reproduce/a
taskset -c 8 make analyze_grhsim_guarded_writes \
  SKIP_WOLF_ENV_CHECK=1 PYTHON="$PWD/.venv/bin/python" \
  GRHSIM_GUARDED_OUTPUT=ptmp/no00028_reproduce/b \
  GRHSIM_GUARDED_REFERENCE=ptmp/no00028_reproduce/a
make verify_grhsim_guarded_production \
  SKIP_WOLF_ENV_CHECK=1 PYTHON="$PWD/.venv/bin/python"
```

输出目录须尚不存在。`GRHSIM_GUARDED_BASE` 默认 declaredSymbol 归档 flow，`GRHSIM_GUARDED_DYNAMIC` 默认 NO00026 的 dynamic checkpoint、源码及两份 100k 日志。需要重建诊断输入时按 [declaredSymbol 基线记录](grhsim-ir-declared-symbol-plan.md) 与 [NO00026 报告](NO00026-grhsim-ir-declared-pack-census-20260928.md) 执行，并先通过 G1/G3；不接受异构 checkpoint 的数字 ID 拼接。

完整验收另执行 `make xs_wolf_grhsim_ir` → `make xs_wolf_grhsim_ir_build_emu_pgo` → `make benchmark_grhsim_ir`。重现本轮参数：

- `XS_GRHSIM_IR_BUILD=ptmp/no00028_guarded_write_census_20260928/flow`，`XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=<flow>/model`，`XS_WOLF_GRHSIM_IR_DUMP_PRE_PARTITION_JSON=<flow>/pre_partition.json`。完整生成不设置 resume。
- `XS_WOLF_GRHSIM_IR_ROW_CONSTANT_FILL`、`OR_WRITE_MERGE`、`MIGRATE_BOUNDARY_OPS`、`DEMONITOR_REDUNDANT` 全为 1。`XS_WOLF_GRHSIM_IR_EDGECOMPLETE_PROFILE` 与 `XS_WOLF_GRHSIM_IR_MIGRATE_EC_PROFILE` 分别用 declaredSymbol 基线的 `vchg_profile.txt` / `migrate_profile.txt`；生产 op 图不变，ID 身份已严格复核。
- 编译 `VM_BUILD_JOBS=32`、clang/llvm-profdata **22.1.2**，三阶段 PGO、PGO_BOLT=0。生成和编译各用 `/usr/bin/time` 计时，包围 `timeout --signal=KILL 1800s make ...`。PGO 训练的 `XS_EMU_PREFIX="timeout --signal=KILL 161.1165s taskset -c 2 $PWD/.venv/bin/python $PWD/scripts/evict_exec.py"`，环境 `EMU_THREADS=1`。`TMPDIR`、`XS_LOG_DIR` 和每次独立 `RUN_ID` 均指向本节点 ptmp；stdout/stderr 也归档到那里。
- 所有仿真 `XS_NUM_CORES=1`、`XS_EMU_THREADS=1`、`XS_EMU_CPU=2`、`XS_SIM_MAX_CYCLE=100000`，waveform/commit/RAM trace=0。
- benchmark 设置 `GRHSIM_IR_BENCH_OLD=ptmp/declsym_baseline_20260928/flow`、`GRHSIM_IR_BENCH_NEW=<本轮flow>`、`GRHSIM_IR_BENCH_BASELINE_SECONDS=48.798`、`GRHSIM_IR_BENCH_PAIRS=3`、`GRHSIM_IR_BENCH_CPU=2`、`GRHSIM_IR_BENCH_PERF_STAT=0`，`GRHSIM_IR_BENCH_OUTPUT` 为新的 ptmp 目录。入口内建交替顺序、驱页缓存、73.197 s 截止和端点验证；窗口内停止本节点编译/分析。

正式证据数值和结构例均已写入正文。生成代码、日志、profile、逐端口导出表与二进制仅留在 ptmp，不提交。
