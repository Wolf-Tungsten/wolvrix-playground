# NO00023：剩余寄存器表写逻辑的动态排序与 gsim 对照

| 字段 | 值 |
|---|---|
| 父节点 | NO00022（当前最佳） |
| 角色 | 诊断 |
| 状态 | ACCEPTED |
| 锚定指标 | M-residual：剩余寄存器族写锥的去重执行次数；M-shape：同名同宽寄存器的局部更新表达式规模；M-cover：配对和动态计数覆盖率 |
| 指标阈值 | 交付三项定量基线、排序与前五个差异族的结构解释；G1–G5 全部通过 |
| 回退预算 | 生产代码零改动；重建时间变化如实登记，不用诊断重建更新最佳指针 |
| RUN_ID | no00023_residual_write_cones_20260927（各步骤追加独立后缀） |
| 工作区 | ptmp/no00023_residual_write_cones_20260927/ |

## 基础选定（BASELINE）

没有未完成节点，选择 NO00022，无迂回。根仓库启动时为 `32a01ae`，期间用户将既有 codex loop 改动提交为 `2178907`；本节点以该提交为根仓库基础，wolvrix 为 `56c12e3`，不修改子模块。保留用户提交。

配置不变，复用 NO00022 基线：Host 50.009 s（样本 SD 0.545 s），总 host 指令 3,703,751.496/guest cycle；gsim+PGO 27.376 s，不重新测量。四个已恢复 RAT 族的原私有写锥 31,358.0 execs/cycle，新数组完整写锥 8,970.87 execs/cycle。输入固定 CoreMark 两次迭代、100,000 cycle 上限、1 core、1 thread、CPU 2，所有 waveform/commit/RAM trace 关闭。

机器 32 核，编译实际使用 -j32。生成从 Make 目标启动至完整 C++/Makefile 结束，编译从 PGO Make 目标启动至 emu 完成，各 1800 s 截止并杀进程组。生产仿真截止预选 50.009×1.5=75.0135 s。PGO 训练属于插桩运行，单独限时 300 s，不混入生产性能。每次生产运行前 posix_fadvise 驱逐二进制页缓存。日志、临时文件均放本节点 ptmp 目录。

## 假设提出（HYPOTHESIS）

NO00020 的静态排序发现逐行写逻辑膨胀，NO00022 恢复索引写后全机指令减少 6.095%、Host 减少 4.739%。但后者通用规则影响 16 个族，不能由四个 RAT 族推导固定的每 op 指令成本。本节点重新对**剩余标量寄存器族**普查，将结构差异和真实执行频率相连，避免继续按旧静态榜单选择目标。

假设：剩余族中仍有局部表达式明显大于 gsim、且动态执行量集中的写网络；也允许测得差异已分散或主要来自统计边界，后者同样是诊断交付，不伪报可优化收益。族仅用实例路径及末尾数字下标聚合、要求相同位宽且至少四行；名称只用于诊断，不作为优化规则。

- **M-residual**：每行 regWrite 数据操作数的完整反向锥（在 state.read/input.read/memRead 截止），按族计算行私有/共享 op，并按整个候选集合去重。每 op 执行数取最终生产结构对应的动态 body 计数。完整锥允许跨具名中间值，避免把展开网络藏在名称后面。读边界本身纳入完整锥，但不扩展 memRead 地址；它表示写值上游工作，不能全部视作可删除工作。
- **M-shape**：对归一化名称唯一、位宽相等且 gsim REG_SRC→REG_DST 可解析的行，比较具名值边界截断的 GrhSIM op+叶数与 gsim 原始 assignTree ENode 数，同时列出 gsim 非叶计算节点数。该口径是表达式形态对照，不是功能等价证明，也不与完整锥执行数混称。
- **M-cover**：报告所有族/行、精确配对行/位数、拒配原因、动态映射覆盖率。不能将零匹配族悄悄丢弃；全局执行量按 op 去重，不能相加各族的共享锥冒充全机工作量。

指标与目标的定量联系来自 NO00022 的实测机制：结构恢复减少完整写锥 76.141%，伴随全机指令 -6.095%；本节点只交付执行量与形态交叉排序，不沿用已被 NO00016/17 证伪的线性逐 op 指令定价。生产模型无变换。

预注册有效性门：**G1** 新鲜分图前 IR 与最终 IR 的 states/types/values/operations 语义一致（如仅 origin 不同需显式归因）；**G2** 最终 checkpoint 和 C++/头文件/Makefile 与父节点一致，才能复用父节点动态计数；**G3** 每个定价 op 均有唯一 compute 单元和 body 计数，全部单元计数无缺失/孤儿，族私有+共享=族并集且全局并集不重复；**G4** 两次分析分别用父节点两次有效 100k 动态日志，结果逐字节一致；**G5** 对 M-residual 前五个已配对且局部规模比 ≥4 的族（不足五个则全部）给出实际 IR/源码的结构解释和优化约束。脚本缺陷归实现瑕疵，修复重测；若配对方法无法提供可信样本，应 REJECTED 并定量复盘，不强行解释。

完整 SV 生成附加已有默认关闭的分图前 dump 开关；随后重新三阶段 PGO 构建。最终性能固定 **old1,new1,old2,new2,old3,new3**，old 为父节点归档构建、new 为相同生产代码的新构建，逐次验证四字段端点、退出码和 difftest。此为诊断重建对照，不以更快的一组更新最佳指针。报告均值、SD、效应量及秩次结果；任一失效运行作废并补足 3+3。

## 代码实施（IMPLEMENTED）

新增只读[分析脚本](../scripts/grhsim_residual_write_cones.py)、[对应单测](../scripts/test_grhsim_residual_write_cones.py)和三个 Make 入口（test/analyze/inspect）。脚本复用已验证的名称规范化与端点解析，严格拒绝规范化碰撞、位宽不符、缺失更新树、缺失/重复动态计数和缺失 compute 映射。完整锥按 DAG 去重；私有/共享在族内划分，全局另做去重。所有未配对行仍参与动态普查，并给出拒配原因。inspect 模式对前五族代表行展开两层 gsim 具名引用，检查局部规模差是否只是命名边界造成；引用缺失直接报错。

gsim 序列化 assignTree 包含 lvalue；除原 NO00020 的序列化节点数，新增从 root 可达的 RHS 节点数与非叶数，明确剔除 lvalue 对形态解读的影响。生成模型校验包含源文件集合（额外/缺失文件也判不一致），复用计数前校验父节点生产与 dyn checkpoint 均相同。全量两轮结果仅写 ptmp，不把生成报告或 IR 入库。

聚焦单测最终 25 例全部通过；覆盖 DAG 重复边、read/memRead 边界、两族共享逻辑不能重复累计、未配对/无 writer、位宽和名称冲突、gsim 左值排除、具名引用展开、事件历史引用以及计数缺失/重复。已有模块对比 28 例、benchmark 3 例也通过。仅根仓库诊断代码和文档有修改，wolvrix、GRH、emit、调度和设计源码均未修改。

最终复核时，非交互 shell 未继承 `WOLF_ENV_SOURCED`，系统 Python 也缺少复用计数模块所需的 `numpy`；这两次入口失败均在测试执行前。指定已有项目环境 `WOLF_ENV_SOURCED=1`、`PYTHON=.venv/bin/python` 后，25 例测试通过，未改依赖或测试逻辑。

## 结果测试（TESTED）

完整 SV→C++ 生成 **809.22 s**，退出 0，含默认生产流程加分图前 dump，最终 checkpoint round-trip 逐字节一致，低于 1800 s。随后完成 PGO 重建与两轮全量普查。

实施期校验失败如实登记：

1. 首次全量分析的进程在日志格式修复前启动，旧动态日志的 `240,349` 等千位分隔数字不能通过原端点正则；生成物身份检查已通过，端点门停止该轮，未产生结果。修正为只去除数字间逗号，并补回归测试。
2. 第二轮在 G3 发现 **489** 个“缺失”单元、孤儿 0。原因是 `CpuPartitionKind::Supernode` 同时用于 compute 与 commit，单看 kind=3 不足以区分。改用已验证的 schedule 遍历，只选 ActivityDrivenCompute 任务的子单元，保留零缺失/零孤儿门。补入 commit supernode 反例后再跑全量。

### 有效性门与构建

- **G1 通过**：分图前与最终模型的九组语义数组逐项指纹一致，既有字符串表逐项相同，后端追加字符串也为 0。图结构从分图前语义得出，最终 mapping 仅用于连接动态计数。
- **G2 通过**：最终 checkpoint 与父节点生产及父节点 dyn checkpoint 均逐字节一致；全部 C++、头文件、模型 Makefile 的文件集合和内容一致；reg-to-mem TSV 也一致。故父节点两次 100k 动态计数可复用，无陈旧 value ID 或单元 ID。
- **G3 通过**：**29,850 compute 单元、3,183,564 compute ops**，counter 键缺失 0、孤儿 0，所有定价 op 唯一映射；各族私有+共享执行数等于族并集。全模型 compute 执行数 **94,338,968,308/run**。
- **G4 通过**：分别读取父节点 run1/run2 的两轮完整分析用时 **703.88/673.60 s**，均退出 0，summary.json、summary.md、families.tsv 三个输出逐字节一致。父节点两次 dyn 端点也通过校验。
- **G5 通过**：前五个差异族全部同名同宽配对，检查其实际 GrhSIM IR、源 RTL 和 gsim 两层具名引用，结果见下节。没有把名称配对当作功能证明。

三阶段 PGO 构建总墙钟 **615.80 s**，退出 0，实际 -j32，低于 1800 s。训练前驱逐页缓存、CPU 2、单线程，100k Host **111.368 s**，端点 `240349/99996/100001/0x80000c0c`，difftest 干净；该插桩时间不进入性能基线。

### 三项诊断基线

**M-cover**：2,250 个至少四行的同宽标量族，共 **28,968 行 / 1,139,477 bit**。严格唯一名称且同宽匹配 **25,954 行 / 1,089,270 bit**，行覆盖 **89.595%**、位覆盖 **95.594%**。其余 2,958 行无精确同名项、56 行位宽不同；没有模糊去行号配对，也未把未配对行排除出执行量统计。候选族没有无 writer 行。本口径不覆盖已恢复数组、packed_bits、事件历史、不足四行或不带数字后缀的状态。

**M-residual**：所有族完整写锥的全局并集为 **583,977 ops / 15,867,638,416 execs/run**，即 **158,674.797 execs/cycle**，占全部 compute 的 **16.820%**。各族内私有集合跨族再去重后为 433,619 ops / 13,260,442,721 execs（132,603.101/cycle）；“行私有”只表示该族内出现一次，不等于全机无其他消费者。若直接相加各族完整锥，得到 **176,168,882,943 execs**，是并集的 **11.1024×**；这不是可相加的优化空间。

直接按完整锥排序，前三名都是 logEndpoint 的 issue_datasource forward/bypass/reg histogram 族（各 20 行），每族约 19,534 execs/cycle，但局部比仅 2.229，局部执行各仅 111.456/cycle。大量上游设计逻辑被这些统计寄存器共同读取，不能为了优化这些计数器而删掉整条上游锥。

**M-shape**：局部规模比 ≥4 的集合为 **254 族 / 2,971 行**，这些行全部精确配对。完整锥并集 **2,691,623,773 execs/run = 26,915.969/cycle（全模型 2.853%）**；对应局部 op 并集为 **721,528,631 execs/run = 7,215.214/cycle（0.765%）**。两者均是执行量，不能乘固定 instr/op 换算性能收益。前五族完整锥去重 **1,458,577,961 execs/run = 14,585.634/cycle**，占全模型 **1.546%**。

| 族（实例尾名） | 行×位宽 | 完整锥 execs/cycle | 族内行私有 execs/cycle | 局部 execs/cycle | 局部规模比 |
|---|---:|---:|---:|---:|---:|
| dispatch/intBusyTable/table_r | 223×1 | 6,614.466 | 5,219.671 | 1,495.283 | 7.607 |
| dispatch/conserveFlowTotal | 8×8 | 2,619.531 | 96.135 | 86.888 | 9.525 |
| intDataPath/intRegFile/mem（剩余标量部分） | 95×64 | 2,404.626 | 2,382.606 | 979.364 | 9.000 |
| dispatch/rcTagTable/IntRCTagTable/tag | 16×8 | 2,400.052 | 368.182 | 175.559 | 7.250 |
| loadQueue/virtualLoadQueue/uopIdx | 72×7 | 1,622.347 | 1,444.808 | 255.368 | 6.000 |

### 前五族的结构解释与约束

五族的 gsim 寄存器末端 RHS 都只有一个 `OP_WHEN` 加 2–3 个具名引用；GrhSIM 局部锥把其中部分数据计算保留在无名表达式中。代表行的 GrhSIM“op+叶”分别为 **31/94/36/29/24**，gsim 末端序列化节点分别 **4/5/4/4/4**，去掉左值后 RHS 为 **3/4/3/3/3**。但沿 gsim 引用展开，计算逻辑仍存在：

1. **BusyTable**：`tableUpdate_129` 自身 RHS 为 **7 节点、2 个 OP_WHEN**，其下仍有 OR、位提取和旧 table 引用。GrhSIM 族局部构成为 bitSelect 223、and 446、or 892、reduceOr 446、not 223、concat 223 及位选/常量。语义可写为：清除条件 `clear`、置忙条件 `set`、旧位 `q`，使能时 `q' = !clear & (set | q)`，无使能则保持，reset 清零。不能只因末端比 7.607 就删除条件；值得后续检查的是分图前把一组相同位操作还原为字级集合运算，必须保留清除优先、复位、各位使能和历史事件。
2. **conserveFlowTotal**：gsim 两个分支的具名节点各为 **4 RHS 节点（ADD+PAD）**，再下层存在 SHL、ADD、PAD；SV/GrhSIM 展开窄位宽计数、拼接和加法。族的完整锥很大，但行私有仅 96.135/cycle、局部仅 86.888/cycle，不宜由 9.525 的规模比推断大收益。可能的规范化是保留各截断宽度的共享计数表达式；不能按普通无限精度加法改写。
3. **IntRegFile**：95 个剩余标量行的局部图有 **855 mux、760 or**，每行 9 个 `(hit_k ? data_k : 0)` 做 OR，写使能为 hit 的并。gsim `wData` RHS 为 OR，两层下明确有 `OP_MUX` 与零常量，同样执行数据选择。reg-to-mem 当前 parser 恢复的是 mux 优先链，未覆盖这类 OR 归约。不能换成现有 memWriteSeq 的“后写覆盖”：两个使能同时命中时，`data0=1,data1=2` 的原结果是 **3**，顺序覆盖结果是 **2**。若后续恢复数组，应证明冲突不可能，或新增保留同址 OR 合并语义的 IR 写操作；本节点未证明互斥。另有两组 64 行已做 indexed-read，不属于此 95 行集合。
4. **IntRCTagTable**：局部 **96 mux+80 or**，每行 6 端口 OR；gsim `wTag` 为 OR，两层下同样有带零分支 MUX。与 IntRegFile 属同类候选，但只有 175.559 局部 execs/cycle。只有同时保持同址数据 OR、全局使能和 pre-commit 读语义的 IR 恢复才可等价。
5. **VirtualLoadQueue/uopIdx**：GrhSIM 局部 **288 mux+144 or+72 prioritySelect**；每行在 entryCanEnq 下从八个入队请求选择数据。gsim `selectBits.uopIdx` 及下一层是 MUX，选择逻辑并未消失。可研究的是将同一行选择关系用于多个字段的共享索引计算，并保持优先级、无使能保持、越界行为；不能把局部比 6 当作已有 6 倍冗余。

**诊断结论**：剩余候选可以定量定位，但高局部规模比受具名边界强烈影响，五个样本均不能只靠该比例证明可删逻辑。若做下一优化节点，优先建立 OR 合并写或位集合更新的小型等价测试，再在分图前替换 IR，并重新测量全机指令；不走 emit-only、分区后 op 微调或旧的整树内联路线。这里是候选和约束，不是已实现的优化收益。

### 六次生产性能复测

预注册顺序为 old1,new1,old2,new2,old3,new3；old 是 NO00022 归档二进制，new 是本节点相同生产源码重建的二进制。每次运行前均用 posix_fadvise 驱逐对应二进制页缓存，CPU 2、单线程、100k 上限，关闭 waveform/commit/RAM trace。所有运行 Make/emu 退出码均为 0，difftest 开启且无 mismatch，端点均为 `instrCnt=240349`、`cycleCnt=99996`、guest cycles `100001`、PC `0x80000c0c`。

| 顺序 | Host s | emu 墙钟 s | 退出 / 等价性 |
|---|---:|---:|---|
| old1 | 50.173 | 50.20 | 0 / 通过 |
| new1 | 49.501 | 49.53 | 0 / 通过 |
| old2 | 49.758 | 49.79 | 0 / 通过 |
| new2 | 49.828 | 49.90 | 0 / 通过 |
| old3 | 49.714 | 49.74 | 0 / 通过 |
| new3 | 49.642 | 49.71 | 0 / 通过 |

old Host 均值 **49.882 s**、样本 SD **0.253 s**；new 均值 **49.657 s**、样本 SD **0.164 s**。new-old 为 **-0.225 s**，相对 old 为 **-0.450%**；Cohen d（new-old）**-1.053**、Cliff delta **-0.556**。秩次交错：`new2=49.828 > old2=49.758`、`old3=49.714`，Mann-Whitney U=2、单侧精确 **p=0.2**，未过“全部新优于全部旧”的提升判据。两侧模型与生成源码逐字节一致，本节点只有诊断代码变化；这组差值是重建扰动，不能宣称优化收益，也不更新当前最佳指针。

**最终判定：ACCEPTED。** G1–G5、完整生成/编译时间和 100k 等价性全部通过，交付三项预注册的定量诊断基线及前五族解释。性能秩次门未过，只否决“重建提速”的说法，不影响诊断交付；当前最佳仍为 NO00022。

### 复现入口

先按 [NO00022](NO00022-grhsim-ir-writenet-factor-20260927.md) 的源码重建步骤生成父节点 profile 和两次 dyn 记录，再执行：

```sh
export WOLF_ENV_SOURCED=1
export PYTHON="$PWD/.venv/bin/python"
make xs_wolf_grhsim_ir \
  XS_GRHSIM_IR_BUILD=ptmp/no00023_residual_write_cones_20260927/flow \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=ptmp/no00023_residual_write_cones_20260927/flow/model \
  XS_WOLF_GRHSIM_IR_ROW_CONSTANT_FILL=1 \
  XS_WOLF_GRHSIM_IR_MIGRATE_BOUNDARY_OPS=1 \
  XS_WOLF_GRHSIM_IR_DEMONITOR_REDUNDANT=1 \
  XS_WOLF_GRHSIM_IR_EDGECOMPLETE_PROFILE=ptmp/no00022_writenet_factor_20260927/vchg_profile.txt \
  XS_WOLF_GRHSIM_IR_MIGRATE_EC_PROFILE=ptmp/no00022_writenet_factor_20260927/migrate_ec_profile_gendyn.txt \
  XS_WOLF_GRHSIM_IR_DUMP_PRE_PARTITION_JSON=ptmp/no00023_residual_write_cones_20260927/flow/pre_partition.json
make test_grhsim_residual_write_cones
make analyze_grhsim_residual_write_cones
make analyze_grhsim_residual_write_cones \
  GRHSIM_RESIDUAL_RUN=ptmp/no00022_writenet_factor_20260927/run2/run.log \
  GRHSIM_RESIDUAL_OUTPUT=ptmp/no00023_residual_write_cones_20260927/analysis/run2
make inspect_grhsim_residual_write_cones
```

所有运行还需统一设置本报告的线程、CPU、输入、trace、日志/RUN_ID 和 TMPDIR；生产生成/编译外包 `timeout --signal=KILL 1800s` 与 `/usr/bin/time`。PGO 用 `xs_wolf_grhsim_ir_build_emu_pgo`，编译 `VM_BUILD_JOBS=32`，训练输入仍为 100k 带 difftest。完整重建新二进制与父节点做 `benchmark_grhsim_ir`，`GRHSIM_IR_BENCH_OLD`/`NEW` 分别指向父/本节点 flow，`BASELINE_SECONDS=50.009`、`PAIRS=3`；输出必须是新的 ptmp 子目录。gsim 导出复用 NO00020 同输入 PreCoarsen 归档，其重建入口见该节点报告。
