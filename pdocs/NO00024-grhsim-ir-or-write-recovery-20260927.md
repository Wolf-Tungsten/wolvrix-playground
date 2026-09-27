# NO00024：把逐行 OR 写网络恢复为共享索引写入

| 字段 | 值 |
|---|---|
| 父节点 | NO00022（启动时当前最佳；诊断依据来自 NO00023） |
| 角色 | 优化 |
| 状态 | ACCEPTED |
| 锚定指标 | M-net：100k CoreMark 总 host instructions / guest cycle |
| 指标阈值 | 同窗口 M-net 降 ≥0.10%；辅助记录转换族、行数与 op 差量 |
| 回退预算 | 同窗口三次 Host 均值回退 ≤+0.5% |
| RUN_ID | no00024_or_write_recovery_20260927，各实验追加唯一后缀 |
| 工作区 | ptmp/no00024_or_write_recovery_20260927/ |

## 基础选定（BASELINE）

启动时根仓库 `803d88d`、wolvrix `56c12e3`，工作区干净，NO00023 已 ACCEPTED 并提交，没有待续节点。选择当前最佳 NO00022，无迂回。NO00023 仅有诊断设施，生产语义仍为 NO00022。

配置不变，复用父节点 Host **50.009 s**、样本 SD **0.545 s**，M-net **3,703,751.496 instr/cycle**、SD **4.081**；gsim+PGO **27.376 s**。输入为 coremark-2-iteration.bin，100,000 cycle 上限、1 core、1 thread、CPU 2，waveform/commit/RAM trace 关闭。32 核、187 GiB 内存，模型编译使用 -j32、clang 22.1.2 三阶段 PGO，训练启用 difftest。

完整 SV→C++ 生成与 PGO 编译分别以 Make 启动为起点、1800 s 截止并终止进程组；未完成产物不得用于验收。生产仿真预选截止 **75.0135 s = 50.009×1.5**；插桩训练/动态计数单独限时 300 s，不混入生产时间。每次 emu 运行前 posix_fadvise 驱逐二进制页缓存。所有日志和临时产物放本节点 ptmp。

## 假设提出（HYPOTHESIS）

[NO00023](NO00023-grhsim-ir-residual-write-cones-20260927.md) 已定位剩余 IntRegFile 95×64 位、IntRCTagTable 16×8 位的逐行 OR 写网络，局部执行量分别 **979.364/175.559 execs/cycle**。其中 IntRegFile 每行九个零分支 mux 和八个 OR；gsim 具名引用下也保留 OR，不能把名字边界产生的规模比直接当作收益。

本节点恢复的是跨行共享：令 `hit_j(r)=en_j && addr_j==r`，原式在任一 hit 时写入 `OR_j(hit_j(r) ? data_j : 0)`，否则保持。对端口 i 构造 `merged_i = data_i | OR_{j<i}(en_j && addr_j==addr_i ? data_j : 0)`，然后按 i 顺序写入 `(en_i, addr_i, merged_i)`。某地址最后一个使能端口包含该地址此前全部有效数据，故结果仍是 OR；不同地址、无写保持和旧状态读取不变。例：同址写 1、2，结果仍为 3，不能直接改成后写覆盖的 2。

变换在 GrhSIM reg-to-mem 中、任何 CPU 分图之前进行，复用已有 compute 与 memWriteSeq 操作；不改 emit、runtime helper、调度、冻结 GRH 或设计源码。名称只用于检查结果，不参与匹配。首版保守要求二态、零分支 OR 树、可解析地址、相同事件和历史初值、写使能等于 hit 并集（允许共同全局 AND），不接受未证明的使能、冲突屏蔽、局部掩码或不完整地址族。

**指标与总目标的定量关系**：NO00022 同窗口指令 -6.095%、CPI +1.412%，对应 host cycles -4.768%、Host -4.739%。因此直接测 M-net 评估 host 工作量，另测 CPI 与 Host 防止代价转移；不以静态 op 数或固定 instr/op 定价。门宽 0.10% 对归档约 **3,703.75 instr/cycle**，是父节点测量 SD 的约 908 倍，足以区分计数噪声。局部执行数只定位候选，不承诺线性收益。

预注册：M-net 降 ≥0.10%、Host 均值回退 ≤0.5%、正确性和构建门槛全部通过才 ACCEPTED。性能与 perf-stat 计数分别按 **old1,new1,old2,new2,old3,new3** 做六次交替测量；old 为 NO00022 归档构建，new 为本节点 PGO 构建。记录全部时间、端点、退出、均值、SD、效应量与秩次。每次端点必须为 `240349/99996/100001/0x80000c0c`，difftest 无 mismatch。实现正确但指标或预算不达标时，量化共享计算、实际转换规模和指令/CPI变化，区分机制性错误与实现瑕疵；不提前提交。

聚焦检查包括关闭开关不变、同址 OR 冲突、不同地址、禁止写、范围外地址、非零行基址、事件保持、旧状态反馈、拒绝形态不变及生成 C++ 对标量解释器。父节点依赖数值 ID 的两个 profile 必须在新结构上重新导出，不能直接复用旧 ID。最终仍需完整 SV 生成，恢复 checkpoint 仅可用于自举诊断。

## 代码实施（IMPLEMENTED）

新增默认关闭的 `enableOrWriteMerge` / `--enable-or-write-merge`，由 `XS_WOLF_GRHSIM_IR_OR_WRITE_MERGE=1` 接入全量流程。匹配 OR-of-zero-mux 写树，精确核对写使能并集（含 reduceOr/concat），保留共同 AND 条件。按无行号的 guard/data 键排列端口，生成共享的前序同址数据 OR，再复用 memWriteSeq。范围判断、非零基址、旧状态读、事件历史和 DCE 沿用已验证实现。每对端口新增计算纳入已有静态成本筛选，未改 emit 或调度。

`make test_grhsim_reg_to_mem_generated` 通过：新增 7 类接受形态各 **32,768** 次状态转换对照，共 **229,376** 次；6 类拒绝形态及开关关闭均序列化不变。覆盖三端口同址 1|2、不同地址、禁写、非零基址、越界、共同全局使能、重复事件、同一地址输入、1/64 位数据和旧状态反馈。原 10 类加新 4 类生成 C++，各 **4,096** 样本，ASan/UBSan 全过。实现只按语义/类型/数据依赖匹配，测试状态使用无规律名称。

全量开始于 2026-09-27。本节点先生成不带两个 profile 的新结构动态构建，采样得到 edge-completion profile；随后在该 profile 下生成动态构建，采样 migrate-ec profile；最终重新走完整 SV→C++ 和 PGO。原有 pass 算法、阈值和顺序保持，重采只是新结构的必需校准。

首轮真实设计的 pass 报告已确认 **19 个 OR 写族、4,217 行**通过静态筛选：10 个 ROB 字段各 351 行（8 端口）；fpRegFile 256 行（8）；intRegFile 223 行（9）；vfRegFile 128 行（6）；v0RegFile 两族各 22 行（4）；IntRegCache/IntRCTagTable 各 16 行（6）；MemRegCache/MemRCTagTable 各 12 行（3）。IntRegFile 的整族恢复同时接管原先仅 indexed-read 的行，不能只统计 NO00023 所剩的 95 个标量行。以上规模是通用匹配结果，未按模块名扩展规则；最终收益须对完整变换计量。

## 结果测试（TESTED）

首轮完整 SV→C++ 自举 **824.65 s**，动态模型编译 **232.23 s**（-j32），均退出 0、低于 1800 s；checkpoint 回环逐字节一致。首次动态 100k Host **180.011 s**（插桩时间，不计入性能），退出 0，difftest 无 mismatch，端点精确为 `240349/99996/100001/0x80000c0c`。运行前驱逐页缓存、CPU 2、单线程。

HDLBits `run_hdlbits_grhsim_ir DUT=001` 与 `run_hdlbits_test DUT=001` 均通过。benchmark / edge-completion 普查与门 / migrate-ec 普查与门脚本单测 **3+15+10+13+20=61** 例全部通过。

第二轮从 GRH checkpoint 自举 **280.93 s**、动态编译 **224.33 s**，端点相同、退出 0、无 mismatch，插桩 Host **173.812 s**。两次 reg-to-mem TSV 逐字节相同。

首轮 profile 门未全部通过：G2–G6 通过，G1 原始逐字节门报告 origins/strings 不同。完整差分确认 **11,320,103** 个 origin 仅第 3 字段 `sourceIndex` 改变；**438,263** 个字符串全部为 `__event_<源opID>_<事件序号>`，无其他字符串差异；所有语义数组及 GrhSIM op/value/state ID 逐项相同。原因是 GRH JSON 重载压紧源 ID，lower 依源码用源 op ID 生成来源索引与私有事件名，属于 NO00020 已登记的非语义重编号。

新增默认关闭的 `GRHSIM_CHECKPOINT_ALLOW_SOURCE_RENUMBER=1`，只允许上述两类有证明的差异：origin 其他字段必须相同；事件名必须能由 grh.event origin 的旧/新源索引对解释，事件序号不变，且不能同时被接口、类型、运算种类、参数键或普通状态名使用。运算、值、状态、初始化、接口及计数数组仍逐项相等；不直接忽略字符串表或全部来源信息。保留原始失败，新增对应正反例单测，再按此语义口径重测。

修正后的 edge-completion **G1–G6 全过**：29,341 单元、624,738 个值逐项检查；移除集合 21,655 值、实际新增唯一边 31,771；原检测写 **19,296,334,704**，新 **18,952,744,183**，移除集闭式 **343,856,811**，额外写 **266,290 ≤3,093,424** 静态上界。来源一致性最终 11 例测试通过，含旧/新 mapping 名称与参数键碰撞反例；原有四组门测试仍通过。每个 dyn 模型仅运行一次，未执行双跑确定性检查，不将其宣称通过。

最终完整 SV→C++ 生成 **798.88 s**，退出 0、低于 1800 s，checkpoint 回环及三轮 reg-to-mem TSV 均逐字节一致。migrate-ec 静态 **5/5 门通过**：实际迁移 **4,289 ops**（1,568 donor、1,739 target），与普查逐项相同；所有语义数组相同，sourceIndex/私有事件名仅为前述逆向重编号。存储 fanout 行 506,995→502,649；移除 4,350（迁移 4,289 加既有规则重放差异 61），重监测 4 行均被既有闭合规则解释，没有缺失激活边。

三阶段 PGO 总墙钟 **642.49 s**（-j32），退出 0、低于 1800 s。训练运行先驱逐页缓存，CPU 2、单线程、100k 带 difftest，Host **108.325 s**，端点精确相同且无 mismatch。第三阶段成功产出 profile-use 二进制，PGO_BOLT=0。最终来源检查再次独立复核两对 checkpoint，均通过。最终模型 **3,261,518 ops**，对父节点 3,321,192 减少 59,674（1.797%）；这是结构变化，不代替 M-net。

### M-net：六次计数交替，下降 1.237%

2026-09-27 17:36–17:41（Asia/Shanghai），按 old1,new1,old2,new2,old3,new3 比较父节点和候选 PGO 二进制。全部退出 0、100k 端点一致、difftest 无 mismatch，逐次成功驱逐页缓存；PMU 全部事件均 100% 运行，无多路复用缩放。以下 Host 时间仅为计数诊断，不充当生产性能基线。

| 顺序 | instructions:u | Host s | emu 墙钟 s | 退出/等价 |
|---|---:|---:|---:|---|
| old1 | 370,379,317,360 | 49.577 | 49.66 | 0 / 通过 |
| new1 | 365,797,696,546 | 48.933 | 49.02 | 0 / 通过 |
| old2 | 370,379,315,888 | 49.889 | 49.94 | 0 / 通过 |
| new2 | 365,798,194,681 | 48.937 | 48.99 | 0 / 通过 |
| old3 | 370,379,316,482 | 49.538 | 49.62 | 0 / 通过 |
| new3 | 365,797,490,924 | 48.962 | 49.02 | 0 / 通过 |

M-net 均值 **3,703,756.128→3,657,941.361 instr/guest-cycle**，下降 **45,814.767/cycle，1.236981%**，超过预注册 0.10%。旧/新样本 SD **0.0074/3.6186 instr/cycle**，极差/均值 **3.97e−9/1.92e−6**；硬件计数有微小波动，不宣称逐字节确定。旧侧相对归档仅 +4.632 instr/cycle。

CPI **0.663089→0.661689（−0.211%）**，host cycles **−1.445%**，branch misses **−0.196%**，L1 loads **+0.874%**、L1 load misses **−0.291%**。共享索引写减少总 host 工作量，但存储访问并非每项都下降；不能以静态删 op 数推出固定 instr/op 成本。计数组 Host 均值 old/new **49.668/48.944 s**、SD **0.192/0.016 s**，Cohen d **−5.304**、Cliff delta **−1**，U=0、单侧精确 p=0.05，仅附记，不与下一组无插桩时间混合。

### 最终性能：六次无插桩交替复测

2026-09-27 17:41–17:46，顺序与预注册一致，所有构建和分析进程已结束。全部 Make/emu 退出 0、端点精确相同、difftest 无 mismatch；各次页缓存驱逐成功，没有失效或替换样本。

| 顺序 | Host s | emu 墙钟 s | 退出/等价 |
|---|---:|---:|---|
| old1 | 49.433 | 49.46 | 0 / 通过 |
| new1 | 48.683 | 48.72 | 0 / 通过 |
| old2 | 49.308 | 49.35 | 0 / 通过 |
| new2 | 48.682 | 48.75 | 0 / 通过 |
| old3 | 49.417 | 49.48 | 0 / 通过 |
| new3 | 48.794 | 48.84 | 0 / 通过 |

old 均值 **49.386 s**、样本 SD **0.068 s**；new 均值 **48.719667 s**、样本 SD **0.064 s**。效应 **−0.666333 s / −1.349235%**，Cohen d **−10.062**、Cliff delta **−1**；`max(new)=48.794 < min(old)=49.308`，U=0、单侧精确 **p=0.05**，秩次门通过。预算上限 **49.63293 s = old×1.005**，候选无回退。

同窗口旧侧对父节点归档 50.009 s 已变快 **1.246%**，故不能把候选对历史值的 **2.578%** 全部当作本节点收益；判定只使用同窗口 **1.349%**。对 gsim+PGO 归档为 **1.780×**，剩余差 **21.344 s**，只是沿用配置不变的历史锚点，没有声称本窗口重测 gsim。

### 判定与归因范围

**ACCEPTED**：M-net 降 1.237% 超过 ≥0.10%；Host 改善 1.349%、秩次门通过；完整生成 798.88 s、PGO 642.49 s 均低于 1800 s；两次自举 dyn、一次 PGO 训练及十二次最终计数/性能运行，共 **15 次 100k** 端点一致、difftest 干净。当前最佳更新为 **NO00024，48.720 s**；总 goal 未关闭。

本节点验证了“把逐行 OR 写网络改为共享端口冲突计算再索引写入”的净收益，覆盖全部 19 个族及新结构下的既有 profile 重采，不能把收益只归给 IntRegFile 或 IntRCTagTable。没有证明写端口互斥，也未改变同址 OR 语义。剩余计算仍包含 O(P²) 端口比较和原有固定地址读成本，不能由此次结果推断任意端口数、任意表深度都获益。默认开关仍关闭，按本报告显式启用；没有改冻结 GRH、设计/共享测试源码、emit 或调度算法。

## 从源码复现

父节点代码为 wolvrix `56c12e3`；本节点子模块提交 `c80ae7e3e6e62a2730f135413af42c3ec5636c7e`，包含实现、语义测试及 [pass 文档](../wolvrix/docs/grhsim_ir/passes/reg-to-mem.md)。根仓库随节点提交 Make 入口、脚本与校验测试、报告、索引、goal 当前锚点和子模块指针。本节点默认开关关闭，父构建仍采用 NO00022 报告中的显式参数。重建新模型需 `XS_WOLF_GRHSIM_IR_OR_WRITE_MERGE=1`，无须回退或挑选其他节点。所有 Make 命令在根目录执行，`PYTHON=$PWD/.venv/bin/python`、`WOLF_ENV_SOURCED=1`、`TMPDIR=$PWD/ptmp/<本次RUN_ID>/tmp`、`LC_ALL=C`。创建新 ptmp 目录，不能覆盖归档基线。

共同参数：`XS_NUM_CORES=1 XS_EMU_THREADS=1 XS_EMU_CPU=2 XS_SIM_MAX_CYCLE=100000 XS_WAVEFORM=0 XS_COMMIT_TRACE=0 XS_RAM_TRACE=0 VM_BUILD_JOBS=32`；生成再加 `XS_WOLF_GRHSIM_IR_ROW_CONSTANT_FILL=1 XS_WOLF_GRHSIM_IR_OR_WRITE_MERGE=1 XS_WOLF_GRHSIM_IR_MIGRATE_BOUNDARY_OPS=1 XS_WOLF_GRHSIM_IR_DEMONITOR_REDUNDANT=1`。每步骤设置独立 RUN_ID、XS_LOG_DIR；`XS_GRHSIM_IR_BUILD=<阶段目录>`、`XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=<阶段目录>/model`。

1. `make xs_wolf_grhsim_ir`，设 `XS_WOLF_GRHSIM_IR_DYNAMIC_STATS=1`，不传两个 profile。生成 bootstrap，然后 `make xs_wolf_grhsim_ir_build_emu`，`EMU_RUNTIME_PROFILE=1 make run_xs_wolf_grhsim_ir_emu` 采 100k。
2. `make analyze_grhsim_edgecomplete_census`，`GRHSIM_EDGECOMPLETE_MODEL/RUN` 指向 bootstrap checkpoint/运行日志，`OUTPUT` 指向新普查目录，`PROFILE` 输出 vchg_profile.txt。
3. 再用 `make xs_wolf_grhsim_ir` 生成 edge-dyn：保留动态开关，传 `XS_WOLF_GRHSIM_IR_EDGECOMPLETE_PROFILE=<vchg_profile.txt>`。可通过 `XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=1` 和 `XS_WOLF_GRHSIM_IR_FLAT_GRH_JSON=<bootstrap/xiangshan_flat_grh.json>` 恢复自举；该时间不算最终完整生成。编译、采 100k 后，用 `make analyze_grhsim_edgecomplete` 检查 bootstrap→edge-dyn 的模型/动态边界；设置 `GRHSIM_CHECKPOINT_ALLOW_SOURCE_RENUMBER=1`，使用本节点提交的严格来源校验。
4. `make analyze_grhsim_migrate_ec_census`，`GRHSIM_MIGRATE_EC_MODEL/RUN` 使用 edge-dyn 的实际 checkpoint/日志，`OUTPUT` 为新普查目录，`PROFILE` 输出 migrate_profile.txt。
5. 最终 `make xs_wolf_grhsim_ir` 使用两个新 profile，关闭动态统计和 resume，`XS_WOLF_GRHSIM_IR_MIGRATE_EC_PROFILE=<migrate_profile.txt>`，`XS_WOLF_GRHSIM_IR_DUMP_PRE_PARTITION_JSON=<flow/pre_partition.json>`。完整计时后，用 `make analyze_grhsim_migrate_ec` 检查 edge-dyn→flow，传 BASELINE_RUN、CENSUS（selected.json）及来源校验开关。
6. `make xs_wolf_grhsim_ir_build_emu_pgo`，三阶段训练保持相同 100k 输入和 difftest。训练 `XS_EMU_PREFIX="timeout --signal=KILL 300s taskset -c 2 $PYTHON $PWD/scripts/evict_exec.py"`；动态运行同样经此驱页缓存入口，运行 profile 的开关只用于动态模型。生产生成和 PGO 各用 `timeout --signal=KILL 1800s /usr/bin/time -f 'wall=%e exit=%x' -o <ptmp计时文件> make ...` 包围；失败停止，不复用不完整产物。
7. `make benchmark_grhsim_ir`：`GRHSIM_IR_BENCH_OLD=<NO00022/flow>`、`NEW=<本节点flow>`、`BASELINE_SECONDS=50.009`、`PAIRS=3`、`CPU=2`、`OUTPUT=<全新ptmp目录>`。先设 `GRHSIM_IR_BENCH_PERF_STAT=1` 采指令计数，再另一个全新目录设 0 采无插桩 Host；入口内置 old/new 交替、驱页缓存、超时和端点检查。

聚焦入口为 `make test_grhsim_reg_to_mem_generated test_grhsim_checkpoint_identity` 和本报告列出的已有测试目标。测试/分析只输出到 ptmp；不提交生成模型、日志、profile 或二进制。
