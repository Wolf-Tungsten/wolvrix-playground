# grhsim-ir-st-opt 第 1 周 PI 规划

## 本周判断与目标

本周是第一周：检查时任务目录只有调度器的 `job.json`，没有既有需求文件、历史 `week_*/pi_final_report.md` 或上次尝试留下的规划；工作区干净。起始提交为 `a15682e`，分支为 `grh/grhsim-ir`。本次仅完成研究规划，不声称已执行性能实验或实现优化。

核心目标是在保持 XiangShan 与前序 GRH IR 不变的条件下，尽可能降低单线程 GrhSIM IR 的 CoreMark 50k 耗时。以当前路线作为直接 A/B 基线，以用户报告约 40 秒的 gsim 作为外部目标。gsim 与 legacy GrhSIM 是两个不同参照，不能将 legacy 的结果写成 gsim 的结果。

仓库已有实现提供以下起点，属于代码与文档证据，不是本任务的历史实验结论：

- `wolvrix/docs/grhsim_ir/flows/cpu-st.md` 定义 compute/commit、事件域、活动度分区、布局和调度；当前 emitter 已有安全 state-read 别名、部分直接提交、变化发布合并和内存按行发布。
- `wolvrix/lib/grhsim/backend/cpu_partition.cpp` 已实现 coarsen 与 DP，DP 目标使用不同输入激活值数量加分段开销，仍有引入实际执行与数据搬运成本的空间。
- `wolvrix/docs/grhsim_ir/passes/reg-to-mem.md` 说明该 pass 已默认启用并带收益筛选；宽于 64 位的动态窗口和任意多位掩码优先写等模式仍有边界，活动度成本也未被完整建模。
- `wolvrix/docs/grhsim_ir/backends/cpu.md` 与 `passes/overview.md` 要求后端决策进入 mapping，语义改写使旧 mapping 失效。已有优化不能重复包装为本周新增成果。

四个方向是竞争候选，不是串行流水线。全部从上述同一基线出发，只依赖现有能力；任一方向应能在其他三个方向没有实现的情况下独立验收。首轮排名只比较各方向单独打开的版本，组合收益留待独立结果成立后再研究。

## 统一实验与判定规则

1. **冻结输入。** 记录根仓库、wolvrix 和参考工具的提交、flat GRH checkpoint、RTL/filelist、CoreMark 镜像、NEMU、生成模型及可执行文件的指纹。四个候选使用相同前序 GRH 输入、默认开启的 reg-to-mem 和相同宿主编译设置；只能改变本方向的 GrhSIM IR pass 或 CPU mapping/emit 策略。禁止改 XiangShan 或前序 GRH。
2. **建立可比基线。** 在同一宿主 CPU 上固定单核运行，记录 CPU、频率策略、编译器和普通 O3 参数、seed、初始化、日志、DPI/NEMU 配置。先核对 gsim 与 GrhSIM IR 的 50k 工作量和计时口径。记录进程总 wall time及可取得的纯仿真时间；生成、编译、初始化成本分列，禁止拿不同区间的秒数直接比较。40 秒未经本周复测，不作为已达到的基线。
3. **正确性先行。** 先做候选覆盖的最小语义回归、mapping verifier 和新会话 JSON roundtrip，再做生成 C++ 回归及 HDLBits 全量。最终完成 `XS_SIM_MAX_CYCLE=50000` 的 XiangShan/NEMU 对拍，检查完整退出结果、周期数、全部有序提交记录和终态；需要额外采集或比较支持时先增加 Makefile 目标。达到周期上限与 CoreMark 整个程序结束分别记录，不能混为一谈。
4. **公平计时。** 正确性追踪与性能测量分开；性能运行统一关闭波形和提交 trace、固定进度输出，NEMU 配置保持一致。每组基线与候选先各预热一次，再按 A/B、B/A 交替顺序各测至少五次，串行执行且不与构建或其他仿真重叠。报告原始时间、median、min/max、相对基线加速比以及与同条件 gsim 的差距。
5. **证据与筛选。** 各方向优先取得真实热点或静态成本证据，再完成一个最小有效候选。profiling 构建不参加普通 O3 排名；如当前 IR 路线缺少计数能力，新增独立开关和 Makefile 入口。建议晋级门槛为耗时下降至少 5% 且超过实测波动；这是筛选标准，不是收益承诺。所有正确候选仍报告实际收益，波动覆盖收益时结论记为未证实。
6. **成本与交付。** 同时记录生成耗时、编译耗时与峰值内存、代码/二进制大小及运行峰值内存，避免把不可承受的编译膨胀隐藏在运行收益中。每个方向交付独立开关、最小补丁、语义说明、回归结果、原始日志路径和性能表；无收益或错误候选交付原因、反例和停止条件。第 1 周结束由 PI 根据正确性、收益稳定性和维护成本推荐保留方案，不强行合并四个方向。

以下是后续实验的现有 Makefile 入口，本次规划不运行这些实验：

- 基础验证：`make test_grhsim_cpu_mapping`、`make test_grhsim_cpu_schedule`、`make test_grhsim_cpu_emit`。
- 集成安装与回归：`make py_install`、`make run_all_hdlbits_grhsim_ir_tests SKIP_PY_INSTALL=1`。
- IR 模型生成和构建：`make xs_wolf_grhsim_ir`、`make xs_wolf_grhsim_ir_build_emu`，分别显式设置候选专属 `XS_GRHSIM_IR_BUILD` 和新的空目录 `XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR`。
- 运行：`make run_xs_wolf_grhsim_ir_emu` 与 `make run_xs_gsim_emu`，均设置 `XS_SIM_MAX_CYCLE=50000 XS_WAVEFORM=0 XS_WAVEFORM_PATH= XS_COMMIT_TRACE=0 XS_PROGRESS_EVERY_CYCLES=0`，使用相同的 `XS_EMU_PREFIX` 单核绑定设置。
- gsim 需要构建时使用 `make xs_gsim_emu`，核对它消费的固定 XiangShan 输入。日志显式使用 `XS_LOG_DIR=ptmp/grhsim-ir-st-opt/week_1/<候选>/logs` 和唯一 `RUN_ID`；临时文件、分析产物及候选生成目录均在本仓库 `ptmp/` 下。所有新增脚本工作流也必须先有 Makefile 入口。

## 方向 1：面向执行成本与数据搬运的活动度分区

**目标：** 改进 `cpu.st.merge-compute-supernodes` 及其分区成本模型，在减少跨 supernode 激活、boundary 搬运与重复执行之间取得更好的平衡，降低每周期计算与派发时间。

**理由：** 现有 coarsen/DP 主要采用操作数量、输入激活数量等代理成本；一个宽值运算与一个标量操作的代价不同，合并冷热点也可能导致无效重算。单纯增加 supernode 或函数容量不能证明性能改善，需要将这些代价直接纳入 GrhSIM IR 分区决策。

**探索与边界：** 固定语义 op、emit 模式和调度机制，统计位宽、跨区字节数、扇出以及可取得的激活频率。第一候选采用确定性的静态加权成本，探索少量容量/权重组合；只有热点证据支持时才加入 profile 引导，并记录 profile 与输入指纹及无 profile 回退。分区输出仍是 `PartitionTree`，后续 layout/schedule 正常重建；保持拓扑合法性、事件域和 word/function 层次，不将函数打包误当作活动度合并。新增权重必须可配置和序列化复现。

**预期产出：** 一个独立可选的分区策略；分区前后 supernode/word/function 数、跨区字节数、激活与重算成本报告；拓扑与 mapping 回归；同一 emitter 下的 50k A/B 结果及参数消融。若减少边界开销却增加执行量导致总耗时不降，明确记录该负结果。

## 方向 2：显式变化发布计划与稀疏调度

**目标：** 在固定分区下，减少活动字扫描、重复 fanout 更新及无效事件域/history 处理，将执行与变化发布之间的关系显式写入 CPU mapping。

**理由：** 现有路线已经按活动度执行、按真变化传播，并具备局部 mask 合并和 history batching。尚需测量 task/word 扫描、roundSeeds、fanout 发布及事件采样各自的成本，验证差距是否来自调度管理，而非计算本身。

**探索与边界：** 在 `cpu_schedule.cpp` 和对应 mapping 中描述去重后的激活目标与消费顺序，以“非空活动字摘要 + 有序稀疏派发”为第一候选，直接使用基线分区。该摘要只跳过已证明无待处理活动的 word，不改变 op 语义。保持当前/后续轮 arm 缓冲、当前或前序 bit 的待处理状态和完整 E 闭包；下降沿仍采样 history。不得直接删除 roundSeeds、合并不同 history 状态或以单时钟假设省略边沿判断。没有调度热点证据时停止扩大方案，不先引入 fullpass。

**预期产出：** 独立可关闭的 schedule/mapping 扩展与序列化、verifier 支持；扫描次数、非空比例、激活发布次数及调度耗时报告；同轮后序激活、跨轮前序激活、多时钟和重复 eval 回归；固定分区与语义模型的 50k A/B 结果。新增元数据和摘要维护的成本须计入净收益。

## 方向 3：扩展表访问与掩码优先写的 IR 模式替换

**目标：** 在已默认开启的 reg-to-mem 之上，消除仍留在 GrhSIM IR 中的高成本表访问和寄存器选择网络，优先验证多位掩码有序写的紧凑表达。

**理由：** 现有 pass 已覆盖标量表恢复、多写口顺序、部分动态读与广播填充，新增收益应来自有实例和热点支撑的未覆盖模式。当前 `memWriteSeq` 不含每条写的 mask，任意多位掩码优先写被拒绝；这提供了一个明确、可独立验证的 IR 扩展切口。

**探索与边界：** 先用现有分析/报告找出拒绝原因及残留操作规模，确认掩码模式在目标负载中存在且成本显著，再实现相应语义 pass。若无有效候选，则在本方向内转向文档列出的宽于 64 位动态窗口，选择其一完成，不同时展开。全部匹配位于 GRH lowering 之后，不依赖 XiangShan 模块名。保留收益筛选并计入读者唤醒、固定读回退和新边界检查的开销。

拟议的掩码顺序写可用 `maskedWriteSeq` 表达（研究名称，当前未实现）：对象引用为表状态及原有事件历史；operands 为按低到高优先级排列的 `(enable, address, data, mask)` 四元组，末尾是事件值，`event_edges` 逐项对应这些事件。`enable` 控制本条写，`address` 选择行，`data` 是候选数据，`mask` 逐位选择更新范围。所有 operands 从旧状态求值，按原写口的有效顺序累计到该行待发布值，最后发布。事件历史采样不受 enable 限制。例如同址的旧值 `1010`，先以 `data=0101, mask=0011` 写得 `1001`，再以 `data=0000, mask=0101` 写得 `1000`；两条均使能时结果必须为 `1000`。不具备确定优先关系的写口不能按此模式合并，地址越界、初始化和读旧写新行为均沿用原语义。

**预期产出：** 一个有实际命中证据的模式扩展或明确的无候选结论；操作定义、输入/输出示例、verifier/JSON/CPU 支持及拒绝条件；命中与成本报告；掩码重叠、多写口碰撞、复位和越界等反例回归。复用 `make test_grhsim_reg_to_mem`、`make test_grhsim_reg_to_mem_generated`、`make test_grhsim_reg_to_mem_rtl` 并按需要扩充测试，最终与默认 reg-to-mem 基线做完整 50k 对比。

## 方向 4：以 IR 发射计划表达融合与临时存储消除

**目标：** 固定语义计算图、分区及调度策略，减少生成 C++ 中的中间值物化、宽值搬运和重复 mask/compare，使 CPU 执行更接近 legacy helper 的低搬运模式。

**理由：** 已有 state-read 别名与 fanout 合并不能保证其他表达式链没有多余读写。宽值临时数组、连续 slice/concat/mux 等组合及过多函数边界可能增加内存流量和指令体积，需要检查实际生成物与热点后选择优化。

**探索与边界：** 在 `cpu_layout.cpp` / `cpu_emit.cpp` 周边增加可验证的后端发射计划，显式记录安全的单使用者表达式融合、存储生存期和 out-buffer 选择。第一候选只处理同一 supernode/helper 范围内、无副作用的单使用者链，不跨越需要变化检测的边界，不重复求值 DPI/system task，也不提前覆盖 commit 需要的旧快照。沿用 legacy 的指针与调用者缓冲 ABI，先核对别名约束再进行原地操作；不引入按值返回大 `std::array` 的 helper。该方向不改变方向 1 的分区算法、不采用方向 2 的稀疏派发、不依赖方向 3 的新操作。

**预期产出：** 独立发射策略开关及持久化的计划字段；优化前后 IR/mapping 与生成 C++ 小例子；宽值复制字节、临时槽大小、生成代码体积及热点变化报告；跨 64 位边界、符号扩展、移位、别名和读旧写新回归；普通 O3 下的 50k A/B 及编译资源对比。若减少源码操作却导致机器码或编译成本膨胀，按实测净收益收缩规则。
