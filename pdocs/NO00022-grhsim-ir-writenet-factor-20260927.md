# NO00022：恢复逐行常量复位寄存器表的索引写入

| 字段 | 值 |
|---|---|
| 父节点 | NO00019（立项时当前最佳） |
| 角色 | 优化 |
| 状态 | **ACCEPTED**（2026-09-27；四阶段与验收通过，Git 写入恢复后完成最终归档） |
| 锚定指标 | M-gcone：目标寄存器族逐行私有写锥的动态执行次数/cycle |
| 指标阈值 | M-gcone 降 ≥70%；关联门 M-net（总 host instr/cycle）降 ≥0.8% |
| 回退预算 | 同窗口 3+3 Host 均值回退 ≤+0.5% |
| RUN_ID | no00022_writenet_factor_20260927；恢复验证使用 overlap_review_gen、native-final、bench-final 后缀 |
| 工作区 | ptmp/no00022_writenet_factor_20260927/ |

## 基础选定（BASELINE）

父节点为 NO00019，无迂回。代码基础为 wolvrix `a59e1b6`、根仓库 `7e7b51a`（含 NO00020/21 诊断设施）。恢复时 NO00022 尚处于 IMPLEMENTED，故继续此节点；NO00019 正文和索引早已 ACCEPTED，遗留的 HYPOTHESIS 头部在本次同步纠正。

配置不变，复用立项锚点：父节点 Host **52.580 s**（SD 0.216 s），M-net **3,944,136.5 instr/cycle**，boundary 检测写 **207,994.58/cycle**；gsim+PGO 为 **27.376 s**，配置未变不重跑。运行输入为 `coremark-2-iteration.bin`，100,000 cycle 上限、1 core、CPU 2、`XS_EMU_THREADS=1`，waveform/commit/RAM trace 全关。机器 32 核、187 GiB；PGO 模型编译实际 **-j32**，clang 22.1.2，三阶段训练启用 difftest，训练输入与测量输入相同。

生成、编译各以对应 Make 目标启动为起点，1800 s 截止并终止进程树。生产运行止损值预先选父节点归档均值，52.580×1.5 = **78.87 s**。每次计时前 `posix_fadvise(DONTNEED)` 驱逐二进制页缓存。动态插桩运行只用于计数/正确性，时间不计入生产性能。

## 假设提出（HYPOTHESIS）

[NO00020](NO00020-grhsim-ir-gsim-module-compare-20260926.md) 的未分图语义对比发现：vecRat arch_table 单行更新锥为 GrhSIM 1,973 ops、gsim 2 enodes；difftest_table 为 2,575 对 3。gsim 保留索引写入，SV→GRH 路线形成逐行地址比较和优先选择链。[NO00021](NO00021-grhsim-ir-bucket-dyn-price-20260927.md) 又证明整个 reg-to-mem pass 净正，禁用它使 Host 增长 13.747%，因此本节点保留其压缩机制并扩大可恢复范围。

普查确定的根因是**寄存器分组键包含复位数据**：各行复位写自己的行号，导致本来同构的写网络被拆成单例。地址条件、写源、事件和掩码可相同；intRat 复位全写零，原 pass 已能合并。变换应在 **lower 后、CPU 分图前的 GrhSIM IR** 完成，不改变 GRH、测试 RTL、emit 或调度算法，不按模块名称触发。

### 指标与预注册

M-gcone = 对每族取仅属于一行的 regWrite 数据反向锥，再跨族去重，求和 `body(unit(op))/100001`。body 是仿真内确定性计数；动态构建两次 100k 计数流逐字节一致。最终普查基线：

| 目标族 | 行数 | 私有 ops | 私有 execs/cycle |
|---|---:|---:|---:|
| fpRat/arch_table | 34 | 1,394 | 870.4 |
| fpRat/difftest_table | 32 | 82,015 | 20,958.0 |
| vecRat/arch_table | 47 | 1,927 | 1,197.0 |
| vecRat/difftest_table | 31（行基址 1） | 79,453 | 19,583.0 |
| 跨族去重 | **144** | **148,483** | **31,358.0** |

去重执行数精确为 **3,135,833,978/run**，共享但不属私有锥部分为 624,154,611/run。候选覆盖初探池 39,114.1 execs/cycle 的 80.2%，超过立项的 ≥50% 覆盖条件。spec_table 缺可译码地址，v0/vl 单行表不足最小组大小 4，不纳入本指标。

假设：把逐行网络还原为数组的索引写入，消除逐行比较/选择及相关检测。原定量估计取 NO00013–15 同类 boundary 写成本测量的保守折扣 1.5–3 instr/exec，由初探池预期 M-net 减少 59–117K/cycle（1.5–3.0%）；这是待验证的量级估计，不是逐 op 成本可加的证明。

预注册标准保持不变：M-gcone 降 ≥70%，M-net 降 ≥0.8%，Host 均值回退 ≤+0.5%。原机制证伪条件为无法覆盖 ≥50% 的池、M-gcone 降幅 <50% 或 Host 超预算；50–70% 仍不满足 ACCEPTED。正确性/构建/截止失败先按实现瑕疵修正。时间测量顺序固定为 **old1,new1,old2,new2,old3,new3**，计数诊断和无插桩性能各自执行完整六次。

## 代码实施（IMPLEMENTED）

[reg-to-mem 实现](../wolvrix/lib/grhsim/pass/reg_to_mem.cpp) 增加默认关闭的 `enableRowConstantFill`：

1. 无地址守卫的整表赋值分支，其数据若为编译期常量，分组键不再包含常量具体值；其他分支保持原规则。
2. 若各行数据相同，继续使用原 memFill；若不同，为每行生成 `(enable, 相对行地址, 该行数据)` 三元组，放在 memWriteSeq 最前。后续三元组依次为原索引写入，保留优先级。
3. 必须证明整表赋值与索引写互斥；两个可同时发生的整表赋值，只有**每一行**的数据都相等才可合并。状态引用、二态类型、事件历史、掩码约束沿用原检查。
4. 成本估计保留所有被新三元组使用的常量，不把它们误计为可删。读路径通过固定地址 memRead 连接；没有新增 runtime helper。

例如每行 `if (reset) q[i]=i; else if(en && addr==i) q[i]=data`，可恢复为一张数组与 `(reset,0,0),(reset,1,1),...,(!reset && en,addr,data)`。三元组操作数和事件顺序见 [pass 文档](../wolvrix/docs/grhsim_ir/passes/reg-to-mem.md)。

接线为 `XS_WOLF_GRHSIM_IR_ROW_CONSTANT_FILL=1`；新增 `XS_WOLF_GRHSIM_IR_DYNAMIC_STATS=1` 仅开启诊断计数。父节点四个既有迁移/去监测步骤保持原实现，因 value ID 和单元结构改变而重新导出 profile；本节点没有新增分区后的优化。

默认关闭路径经小模型序列化逐字节比较及完整 post-lower 输入的 pass TSV 对账验证。未额外执行门关全量 SV 生成，不将其作为证据。

### 聚焦测试

- `make test_grhsim_reg_to_mem`：通过。逐行常量复位覆盖门关不变、门开三元组地址/数据、幂等和 32,768 次状态转换对照；使用无规律状态名，证明不依赖名称。
- 重叠 fill 反例：首行都写零、后续行数据不同，修正前用例失败，改为逐行等价检查后通过，并证明拒绝时模型不变。
- `make test_grhsim_reg_to_mem_generated`：**10 种形态 ×4,096 样本**全部通过，包含正常逐行复位与重叠 fill 拒绝路径；生成 C++ 对标量解释器，ASan/UBSan 开启。
- Python 检查：benchmark 3 例、native-work 15 例、M-gcone 11 例全通过。新增数组 origin 追溯、缺失计数器拒绝和指令/guest-cycle 归一化测试。
- HDLBits：前期 IR 全量 **161/162**，105 为已登记的预存失败；恢复后 `run_hdlbits_grhsim_ir DUT=001` 和 `run_hdlbits_test DUT=001` 均通过。前期 Verilator 全量的 042 为预存 TB 编译不兼容，不伪报全量通过。

## 结果测试（TESTED）

### 全流程与实现瑕疵修正

| 步骤 | 墙钟 | 结果 |
|---|---:|---|
| 首次完整 SV→C++ 自举 | 792.17 s | 通过 |
| 最终 profile 的完整生产生成 | 798.68 s | 通过 |
| 三阶段 PGO 编译（含训练与合并） | **590.97 s** | 通过，-j32 |
| 最终结构的 dyn 全量生成 / 编译 | 805.08 / 215.77 s | 通过，仅计数用途 |
| 修正重叠 fill 后的完整 SV→C++ 复核 | **829.30 s** | 通过 |

最后一次重生成的 TSV、checkpoint、全部 C++/头文件和模型 Makefile 均与生产产物逐字节一致，round-trip 一致。因此复用已验证的 PGO 二进制；不是用 checkpoint 恢复时间代替完整生成。

本节点中断前经历的校验失败均有量化定位，保留其原因与修正：

| 轮次 | 观测 | 原因及修正 |
|---|---|---|
| 1 | 模型语义数组相等，结构门 4 项失败；迁移 5,012 ≠普查 4,280 | old 用 reemit、生产用 gen，单元结构不同。old 改为同一路径完整 gen |
| 2 | 同路径结构门 5/5 通过，迁移 3,507；生成 802.87 s、PGO 608.33 s | 结构检查闭合，但定价计数仍来自 reemit，尚非最终结果 |
| 3 | dyn 重放多迁移 1,829 ops；计数普查 4,280 ≠3,507 | 已带迁移的 checkpoint 再施加同 pass。改用 gen 路径计数，避免双重施加 |
| 4 | gen 模型逐字节相同，但自身计数选择 4,284 ≠旧 profile 的 3,507 | 计数器依赖实际单元结构。用 gen 自身 dyn 计数重导 profile；并发 pip 构建冲突改为串行 |
| 5 | 最终选择与实际迁移均为 4,284 | 生产与 dyn 同结构、单次施加，结构门 5/5、动态门 9/9 全过 |
| 恢复复核 | 重叠 fill 首行相等不足以证明整表相等 | 新反例先失败后通过；最终全量产物不受此边界修正影响 |

最终动态门比较 **29,850 单元、612,117 个值、34 种 op**：新增激活全部在静态上界内，4 个重监测值按既有精确例外集处理。迁移 4,284 ops（1,566 donor、1,737 target），与普查一致。自举对照的检测写 19,453,290,398→19,263,950,654；迁移集合移除 188,314,762 次，额外净减少 1,024,982 次，闭合检查通过。这个自举 old 不是最终性能对照。

最终两次 dyn、六次 perf-stat、六次无插桩运行共 **14 次**，均达到同一端点：`instrCnt=240349, cycleCnt=99996, guest=100001, PC=0x80000c0c`，退出 0，difftest 无 mismatch。dyn 两轮计数流逐字节一致。

### M-gcone：保守计费仍下降 71.392%，通过

原逐行 regWrite 锥已消除，但不能把状态改名当作零成本。补充检查按保留的 origin 追溯四张新数组，核对每张的行数、唯一 memWriteSeq 和读路径，并对**所有写入使能、地址、数据的完整反向锥**计费：

| 族 | 数组行数 | 写三元组 | memRead | 完整写锥 ops | execs/cycle |
|---|---:|---:|---:|---:|---:|
| fpRat/arch_table | 34 | 76 | 34 | 144 | 92.4 |
| fpRat/difftest_table | 32 | 575 | 32 | 10,948 | 6,444.5 |
| vecRat/arch_table | 47 | 102 | 47 | 170 | 102.6 |
| vecRat/difftest_table | 31 | 582 | 31 | 12,590 | 7,510.7 |
| 去重 | **144** | **1,335** | **144** | **15,104** | **8,970.87** |

新完整写锥精确执行 **897,096,121/run**，包含原指标排除的共享逻辑。全部算作原私有锥的残余，仍有 `1−897096121/3135833978 = 71.392%` 改善，严格超过 ≥70% 门槛。按两侧完整锥比较为 37,599.51→8,970.87/cycle，下降 76.141%；这项只作补充，不替换预注册标准。

两轮普查逐字节一致，op/计数器映射零缺失。父基线也使用其实际 dyn checkpoint 重算，与立项数字逐项一致。[普查脚本](../scripts/grhsim_rat_gcone_census.py) 的模块名筛选只用于诊断目标集，优化实现没有名称筛选。

### M-net：下降 6.095%，通过

2026-09-27 14:19–14:24（Asia/Shanghai）直接交替比较父节点和候选 PGO 二进制；CPU 2、相同输入、逐次驱页缓存。PMU 事件全部 100% 运行，没有多路复用缩放。以下 Host 时间属于计数诊断，不能当生产性能基线。

| 顺序 | instructions:u | Host s | emu 墙钟 s | 退出/等价 |
|---|---:|---:|---:|---|
| old1 | 394,417,963,518 | 52.586 | 52.66 | 0 / 通过 |
| new1 | 370,378,617,818 | 50.738 | 50.79 | 0 / 通过 |
| old2 | 394,418,188,000 | 53.227 | 53.32 | 0 / 通过 |
| new2 | 370,379,324,548 | 50.268 | 50.32 | 0 / 通过 |
| old3 | 394,417,959,138 | 52.604 | 52.66 | 0 / 通过 |
| new3 | 370,378,617,604 | 49.535 | 49.63 | 0 / 通过 |

M-net 均值 **3,944,140.927→3,703,751.496 instr/cycle，−6.094849%**；样本 SD 为 1.309/4.081 instr/cycle。重复计数极差/均值为 5.80e−7/1.91e−6，远小于效应；硬件计数不是逐字节确定量，不与 dyn 计数混称。旧侧相对归档漂移仅 +4.4 instr/cycle。

CPI **0.661842→0.671191（+1.412%）**，抵消部分指令收益；host cycles −4.768%、branch misses −3.721%、L1 loads −5.615%、L1 load misses +0.421%。结果支持减少 host 工作量，不能据此声称每条 IR op 有固定成本。

### 最终性能：六次无插桩交替复测

2026-09-27 14:24–14:30，顺序、绑定、输入、cache 驱逐与预注册一致，运行时统计关闭。全部 make/emu 退出 0、端点一致；12 次计数/性能测量都成功驱逐页缓存。

| 顺序 | Host s | emu 墙钟 s | 退出/等价 |
|---|---:|---:|---|
| old1 | 52.620 | 52.65 | 0 / 通过 |
| new1 | 50.442 | 50.48 | 0 / 通过 |
| old2 | 52.605 | 52.64 | 0 / 通过 |
| new2 | 50.188 | 50.24 | 0 / 通过 |
| old3 | 52.266 | 52.34 | 0 / 通过 |
| new3 | 49.397 | 49.43 | 0 / 通过 |

旧均值 **52.497 s**、样本 SD **0.200 s**；新均值 **50.009 s**、样本 SD **0.545 s**。差 **−2.488 s / −4.739318%**，Cohen d=−6.060、Cliff δ=−1；三次新运行全部快于全部旧运行，U=0、单侧精确 **p=0.05**，秩次门通过。窗口内新旧均有变快趋势，按六次预注册数据全量统计，不删除较快/较慢样本。

旧均值对 52.580 s 归档为 −0.158%；新均值对归档为 −4.890%，但判定采用同窗口 −4.739%。预算上限为 52.497×1.005=**52.759 s**，候选无回退。

### 判定依据与归因范围

**最终判定：ACCEPTED。** M-gcone 保守降幅 71.392%、M-net −6.095%、正确性和生成/编译门槛均通过，Host 改善 4.739%。当前最佳更新为 NO00022 **50.009 s**。相对 gsim+PGO 为 **1.827×**，仍差 **22.633 s**；总 goal 未关闭。

通用规则实际新增 **16 个写合并族、963 行**：除四个预注册 RAT 族，另有 12 个空闲表（int/fp/vec/vl/v0、loadQueue RAR/Replay/RAW、vl/vsMergeBuffer、uncacheBuffer），均由相同逐行常量结构触发。写合并族 1,417→1,433、indexed-read 族 609→602，总转换族 2,026→2,035。最终 ops **3,531,463→3,321,192（−5.954%）**、状态减少 2,608、检测写减少 7.383%。因此全机收益属于**完整通用变换和继承管线 profile 重导**，不能全部归因四个 RAT 族，也未宣称独立测得每个新增族的收益。

本节点机制未被证伪，不向机制证伪表增加负向结论。须保留的实现约束是：逐行常量分组后，重叠 fill 的等价证明必须覆盖每行；profile 定价必须与使用它的实际单元结构一致。

## 复现与归档

按顺序归档：wolvrix 子模块代码、测试及规则文档提交为 `56c12e3f8c158fa2a90b80b24729589d2ff98f26`；根仓库随后提交 Make 入口、测量/普查脚本、测试、报告、索引、goal 锚点和子模块指针。生成代码、日志、profile、波形、二进制不入库。工作区原有 codex_goal_loop 文件及其 Make 入口不属于本节点，保留未提交；不 push。

**归档阻塞（2026-09-27）**：实际执行子模块暂存时失败：`Unable to create '.git/modules/wolvrix/index.lock': Read-only file system`。`findmnt` 确认根仓库 `.git` 挂载选项为 `ro`，子模块 Git 数据也位于该挂载；没有创建任何本节点提交或改变暂存区。未绕过只读限制。恢复到 `.git` 可写环境后继续 NO00022：复核差异，先提交子模块，再更新本报告/索引/goal 为 ACCEPTED 和当前最佳 NO00022，最后提交根仓库。代码、数据未变则复用本报告验证，不另开节点、不重跑性能。

**再次续接复核（2026-09-27）**：子模块四个待提交文件的差异与上次验证后保存的补丁逐字节一致；留存的六次无插桩测量与六次指令计数汇总均与上述报告一致。再次执行子模块 `git add` 仍以退出码 128 失败，错误仍为 `index.lock: Read-only file system`；`findmnt` 再次确认 `.git` 为 `ro`。本次未改实现、未重复性能测试，未创建提交；NO00022 保持 TESTED，已归档最佳仍为 NO00019，未启动新节点。

**最终续接与归档（2026-09-27）**：上述两次只读阻塞现已解除。子模块实现与已验证补丁逐字节一致，根仓库测量脚本、测试及本节点 Make 入口也与留存补丁相符；父/新二进制、CoreMark 和 NEMU 的 SHA256 与测量登记一致。复核六次无插桩测量、六次 perf-stat、M-gcone 两轮结果及结构/动态门均与正文相符，故按恢复约定复用完整生成、编译和 100k 性能证据，不重复测量。通过 Make 目标再次运行 benchmark 3 例、native-work 15 例、M-gcone 11 例、reg-to-mem 语义测试及 10×4,096 样本生成代码 ASan/UBSan 检查，全部通过。正常 Git 暂存与子模块提交成功；本报告、索引和 goal 随根仓库归档登记 ACCEPTED 与当前最佳 NO00022，不启动下一节点。

父节点生产二进制 SHA256 为 `c870e5ce168f9b717ab01a12467cd2874c0ebee3a0b6e7304aba3e27619d9200`，候选为 `657d72363e569cd7ba076eb5d771964d7d938ec9d5cad639081f0158ff7147bc`。输入 SHA256：CoreMark `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`；NEMU `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`。这些只用于辨认复现输入，不代替上述结果。

### 从源码重建的顺序

全部操作通过根 Makefile 目标，串行完成各次安装/生成。工作区设为新的 `ptmp/` 子目录，设置独立 RUN_ID、日志路径和 TMPDIR；生产完整生成/PGO 目标外加 `timeout --signal=KILL 1800s`。

通用生成参数：`XS_WOLF_GRHSIM_IR_ROW_CONSTANT_FILL=1`、`XS_WOLF_GRHSIM_IR_MIGRATE_BOUNDARY_OPS=1`、`XS_WOLF_GRHSIM_IR_DEMONITOR_REDUNDANT=1`，以及对应 `XS_GRHSIM_IR_BUILD`、`XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR`。

| 阶段 | Make 目标及差异 |
|---|---|
| F0 | `xs_wolf_grhsim_ir`，通用参数，不带两份 profile；得到 flow0 |
| F0 计数 | `reemit_grhsim_ir`，输入 flow0 checkpoint，MIGRATE_BOUNDARY_OPS/DEMONITOR_REDUNDANT/COMMIT_COMPACT_WALK/COMMIT_MEM_WALK/DYNAMIC_STATS 五个 GRHSIM_REEMIT 旋钮为 1；普通 `xs_wolf_grhsim_ir_build_emu` 构建、两次 100k dyn 运行 |
| EC profile | `analyze_grhsim_edgecomplete_census`，GRHSIM_EDGECOMPLETE_MODEL=flow0 checkpoint、RUN=F0 dyn run1、PROFILE=vchg_profile.txt |
| E 与 E-dyn | `xs_wolf_grhsim_ir`，通用参数加 `XS_WOLF_GRHSIM_IR_EDGECOMPLETE_PROFILE=vchg_profile.txt`；第二次增加 DYNAMIC_STATS=1，checkpoint 必须相同。普通构建 E-dyn，两次 100k 计数相同 |
| 迁移 profile | `analyze_grhsim_migrate_ec_census`，GRHSIM_MIGRATE_EC_MODEL=E-dyn checkpoint、RUN=E-dyn run1、PROFILE=migrate_ec_profile_gendyn.txt；预期 selected 4,284 |
| 最终生产与 dyn | `xs_wolf_grhsim_ir`，通用参数加上述两份 PROFILE；dyn 独立生成仅增加 DYNAMIC_STATS=1，checkpoint 与生产必须相同 |
| 构建/正确性 | 生产 `xs_wolf_grhsim_ir_build_emu_pgo`、dyn 普通构建；`analyze_grhsim_migrate_ec` 以 E-dyn 为 old、最终 dyn 为 new、E-dyn run1 为 baseline、新两轮为 RUN1/2、迁移普查 selected.json 为 CENSUS；应 9/9 通过 |

运行统一用 `run_xs_wolf_grhsim_ir_emu`，显式设置 1 core/1 thread、CPU 2、100k 和所有 trace 为 0；dyn 设 `EMU_RUNTIME_PROFILE=1`，生产测量必须关闭。profile ID 绑定具体模型，不能复用父节点 profile，不能在已迁移的 checkpoint 再施加同迁移。

现有归档的最终生成位置为 flow/flow-review（逐字节相等）、dyn 为 flow-dyn2；自举 E-dyn 为 flow0-ecg-dyn2。性能可直接重测：
```sh
source env.sh
make benchmark_grhsim_ir \
  GRHSIM_IR_BENCH_OLD=ptmp/no00019_migrate_ec_20260926/flow \
  GRHSIM_IR_BENCH_NEW=ptmp/no00022_writenet_factor_20260927/flow \
  GRHSIM_IR_BENCH_OUTPUT=ptmp/no00022_remeasure_host \
  GRHSIM_IR_BENCH_BASELINE_SECONDS=52.580 GRHSIM_IR_BENCH_CPU=2 \
  GRHSIM_IR_BENCH_PAIRS=3 XS_EMU_THREADS=1
```
M-net 使用同一目标与新输出目录，加 `GRHSIM_IR_BENCH_PERF_STAT=1`，保持与无插桩结果分开。[benchmark 脚本](../scripts/benchmark_grhsim_ir.py) 自动预注册顺序/输入/二进制、驱逐缓存、检查端点并实施 78.87 s 截止。M-gcone 使用 `analyze_grhsim_rat_gcone`，新侧四族 EXPECT_FAMILIES 均为 0，EXPECT_MEMORIES 为 34/32/47/31，检查两轮输出逐字节一致。
