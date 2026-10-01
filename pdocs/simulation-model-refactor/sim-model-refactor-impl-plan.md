# GRHSIM IR 仿真模型重构 实施计划

## 0. 定位

- 语义基线：`pdocs/simulation-model-refactor/sim-model-refactor-plan.md`（初版 commit 95a4456，2026-10-01 已补充作者明确的优化、存储与多 TU 约束）。所有语义决策以该文档为准，本文档只管工程落地；落地过程中发现新的语义缝隙时，先回改语义文档并与作者确认，再改代码。本次作者建议已明确，作为第 10 节改造计划的依据。
- 任务入口：第 1-8 节记录工程约束、现有基础及风险，第 9 节保留已执行的检查点；所有仍必要的未完成任务统一纳入第 10 节，不再并行维护旧 M5b/M5c/M6 待办。
- 目标产物：新 CPU 后端生成的仿真类按六阶段模型（P_input/P_event/P_general/P_mem/P_publish/P_output）运行，正确性对黄金参照全绿，性能达到旧实现同一量级。
- 三条工程方针（作者指定）：
  1. **逐 pass 落地**：每个主要步骤都是独立 pass，中间结果落到 GrhSimModel；全图与分区语义 pass 不预建 CpuBackendMapping，第二轮 General 分解时才建立最终 mapping。pass 间可 JSON dump 观察、`grhsim.verify` 逐 pass 校验；
  2. **直接替换**：不设新旧并存开关；旧版 grhsim ir 的 cpp emit 与 legacy 仿真一并删除，只留新实现；
  3. **性能优先的可读存储**：各 store 按优化后的状态规模、连续性和更新代价设计，允许折叠、合并、打包及恢复高维数组；具名字段和 declaredSymbol 来源映射提供可读性。大块连续状态避免 publish 全量拷贝；生成 C++ 必须分 TU 并行编译，控制公共头体积并实测后决定是否使用 PCH。

## 1. 总策略

- **pass 化流水线**：重构体现为 `flows/cpu-st.md` 中 pass 序列的整体重写。每个新 pass 输入/输出均为 GrhSimModel，命名沿用 `grhsim.*` / `cpu.st.*` 约定，pass 间挂 `grhsim.verify`；调试时可在任意 pass 后 dump JSON 检查中间形态。
- **分而治之**：按“图 → 分区 → 映射调度”三段推进（与语义文档构建顺序一致）：A 大图优化（全图 `reg-to-mem` / `comb-pack` 等 → 全图 `simplify` → store 分类决策）→ B 第一轮分解与分区优化（拆出 P_event/P_general/P_output → 各分区独立 `simplify` → 边界感知克隆）→ C 第二轮分解与映射调度（仅在 P_general 内划分 node/supernode，建立一次最终 CPU mapping，随后布局/静态表/执行计划/TU 划分单向推进，不回改语义）。全部语义改写在最终 mapping 之前完成；旧管线曾存在的“mapping → packing 等语义改写 → mapping”往返在目标流水线中不再出现。
- **声明来源贯穿优化**：GRH `simplify` 保留 declaredSymbol，lower 到 GrhSIM IR 后继续维护，供全图和分区优化使用；折叠/合并/拆分时保留原声明到优化结果的来源映射。
- **多 TU 是整核构建前置要求**：代码按函数和规模分 TU，生成完整源文件清单，经 Makefile 并行编译和链接；公共头重复解析开销实测后决定是否使用 PCH。
- **直接替换，黄金参照兜底**：
  - 已采集的 M0 **黄金参照**（逐 eval 输出 + 性能快照）长期保留在 `ptmp/`，实际覆盖范围见第 9 节；
  - 正确性验证 = 新实现对黄金参照逐 eval 比对 + hdlbits 流程的 Verilator 参照；
  - 旧 emit/legacy 主体已删除，证据见第 9 节；剩余旧 mapping 与旧 schedule 消费者的清理归入 M5d-6。`grhsim_runtime.{hpp,cpp}` 保留为新 emit 的 runtime 头生成器，`cpu_partition/cpu_layout/cpu_schedule` 承载后续改造，system_verilog.cpp 等 hdlbits 流程设施保留。
- **优化逐项验证等价性**：全图优化与分区 simplify 属于目标流水线的必要步骤，每步做结构校验和相关差分；regLatchStore 的整块 publish 拷贝仅覆盖优化后零碎状态，memStore 通过独立阶段实现 NBA。进一步优化由瓶颈实测确定，并验证等价性。
- **构建/测试一律经 Makefile 目标**（AGENTS.md 约束），缺目标先补目标；日志与大 artifact 落 `ptmp/`。
- **文档同步**：随第 10 节各阶段同步 `wolvrix/docs/grhsim_ir/`（overview.md、dialects/core.md、backends/cpu.md、flows/cpu-st.md 及对应 pass 文档）；流程变化涉及 AGENTS.md 时同步，最终一致性检查归入 M5d-8。

## 2. 存储形态与可观测性设计（方针 3 落细）

总原则：**性能优先，提供优化后状态的可读性**。每个 store 生成为具名结构体，仿真类成员即 `regLatchStore`/`regLatchStoreNext`/`memStore`/`boundaryValueStore`/`prevEventStore` 等具名实例；字段对应优化后的状态，可折叠、合并、打包、数组化，保留来源到字段/位段/索引的映射以支持调试。store 归属由规模、连续性和更新代价决定。

- **声明来源与命名推演**：GRH `simplify` 必须保留 declaredSymbol 及相关声明来源，lower 到 GrhSIM 后贯穿全图优化、分区 simplify 和布局；用于指导状态同族识别、打包和数组维度恢复。字段名首选来源 declaredSymbol（清洗规则：层次分隔符与非法字符→下划线；全图唯一化——冲突时确定性追加 state/value id 后缀）；无来源的合成信号回退为"来源 op 类别前缀 + id"的可读名。清洗与唯一化集中在 layout pass，emit 只消费；声明注解指导候选识别，等价性仍需由数据流、事件和读写关系保证。
- **RegLatchStore / regLatchStoreNext**：承载优化后的零碎状态，允许小数组或打包字，以紧凑、可整块拷贝的布局在 publish 实现 NBA。2-state 小位宽用原生整数类型，宽值/4-state 用定长成员；打包后保留成员名→位区间映射。
- **MemStore**：承载优化后的大块连续状态，包括从标量寄存器恢复的数组；在独立 P_mem 阶段更新，保持同轮旧值读取，避免 publish 大规模拷贝。数组是合法 IR 类型，鼓励恢复高维数组；保留维度及原声明→索引映射。数组类型本身不决定 store 归属。
- **BoundaryValueStore**：输入字段按端口名；跨界值按来源信号 declaredSymbol；mem 写 data/addr 槽按写 op 命名（如 `<mem>__w<idx>__data`）。
- **prevEventStore / eventActStore**：按 (event,edge) 聚类命名（`<信号名>__<posedge|negedge|both>`）；act 若保留位图/字节数组形态，生成常量名表（`static const char* const`）或 enum 供调试索引。
- **flag 数组**（eventActiveFlag/dataActiveFlag/Next、timeslotTriggerFlag）：热路径保留紧凑字节数组，配套生成超节点/op→名字的常量表，调试时可按索引反查。
- **调试设施**：已有 `dumpState()` 按名打印各 store 字段，用于定位首个分歧 eval；随优化后布局维护来源与字段对应关系。
- **多 TU / 公共头**：按函数和规模生成多个 TU，限制过大函数规模并控制公共头体积；PCH 是否启用由重复解析耗时与内存实测决定，不设未经测量的字段数门槛。实现与验收归入 M5d-7。

## 3. 现有代码基础

本表描述已落地的基础和后续代码所在模块，不再列原 M1-M5 的待执行清单。具体改造、清理和验收任务以第 10 节为准。

| 模块 | 文件 | 现有基础 |
| --- | --- | --- |
| dialect / IR / 验证 | `wolvrix/lib/grhsim/dialect/core.cpp`、`wolvrix/include/grhsim/ir/model.hpp`、`wolvrix/lib/grhsim/ir/verifier.cpp` | edgeDet、阶段归属、具名 store 与六阶段结构校验已落地 |
| GRH / lower | `wolvrix/lib/transform/`、`lib/grhsim/convert/grh_to_grhsim.cpp` | 已保留声明文本元数据；convert 已摘除旧 `__event_*` 生成 |
| 语义 pass | `wolvrix/lib/grhsim/pass/` | 事件/输出锥、time-slot 迁移和现有计算优化可作为改造基础 |
| 后端分区 | `wolvrix/lib/grhsim/backend/cpu.cpp`、`cpu_partition.cpp` | 六阶段 mapping、General node/supernode 和事件域约束已落地；旧 mapping 注册仍存在 |
| 布局 / 调度 | `wolvrix/lib/grhsim/backend/cpu_layout.cpp`、`cpu_schedule.cpp` | 具名布局、事件位图、mem 写计划和六阶段 schedule 已落地 |
| 新 emit / runtime | `wolvrix/lib/grhsim/backend/cpu_phase_emit.cpp`、`wolvrix/lib/emit/grhsim_runtime.cpp`（头文件在 `wolvrix/include/emit/`） | 单 TU 六阶段 emit 已落地，runtime 使用指针与调用方缓冲 |
| checkpoint | `wolvrix/lib/grhsim/io/json.cpp` | 已支持 `wolvrix.grhsim.v2` 和六阶段表；新契约沿此路径扩展 |
| 已删旧实现 | `backend/cpu_emit.cpp`、`cpu_shape_share.cpp`、`cpu_block_share.cpp`、`lib/emit/grhsim_cpp.cpp` 及对应头文件 | 删除已完成；备份与验证证据见第 9 节 |

## 4. 阶段语义约束

- 三个计算分区为 P_event/P_general/P_output；运行时仍有 P_input/P_event/P_general/P_mem/P_publish/P_output 六阶段，二者不混用。
- 全图优化和第一轮分区化简阶段不建立 CPU mapping；第二轮在 P_general 内建立 node/supernode，并从此时开始构建一次最终 CPU mapping。
- regLatchStore 的 next/current 在 publish 实现 NBA；memStore 的写入参数在 P_mem 原地更新前采样；状态归属由优化后形态与更新代价决定。
- Event 历史、time-slot 历史保留各自提交时机；事件锥/输出锥的复制不能导致 DPI、随机采样或系统任务重复执行。
- General 事件域约束、数据激活粘滞和同轮拓扑传播同时成立；静态表与实际图的对应关系由 verifier 检查。
- 语义 pass 输出和最终 mapping 都可 JSON dump/verify；多 TU 只改变代码组织，不改变活动度粒度和六阶段执行顺序。

## 5. 原里程碑归档

原 M0-M6 不再作为后续执行队列。已执行范围保留在第 9 节；未完成工作经审视后并入第 10 节，原完成状态不代表 2026-10-01 新要求已经实现。

| 原里程碑 | 已落地范围 | 未完成项归属 |
| --- | --- | --- |
| M0 | 黄金采集、覆盖 manifest、差分门禁及 XS 截断快照 | 黄金覆盖与后续差分归入 M5d-8 |
| M1 | edgeDet、阶段表达、verifier/JSON v2 基础 | 新来源/存储契约随 M5d-1、M5d-4 扩展 |
| M2 | 事件/输出锥与 time-slot 迁移 pass | 目标分区改造归入 M5d-5 |
| M3 | General 分区、node/supernode 和事件域约束 | 语义分区解耦归入 M5d-5；最终 mapping 归入 M5d-6 |
| M4 | 具名布局、位图、mem 写计划和六阶段 schedule | 按新存储契约适配归入 M5d-6 |
| M5 | 新单 TU emit、旧 emit/legacy 主体删除、HDLBits 和 xs-bugcase 回归 | 旧 mapping 清理归入 M5d-6；多 TU 归入 M5d-7；集成验收归入 M5d-8 |
| M6 | 性能对齐尚未验收 | 性能测量归入 M5d-8；无测量依据的优化回填清单取消 |

## 6. 测试策略

- 单元（`wolvrix/tests/grhsim/` 按模块放，ctest 注册）：edgeDet 校验、各新 pass 结构、划分禁止条件、位图/静态表正确性、命名唯一化。
- 语义定向用例（每条激活代数一条）：计数器自环收敛、A→B 残留下一沿采样、多次异步复位、clk0/clk1 双域不吞标志、glitch 时钟多边沿、latch 环收敛、event-free mem 写收敛、$monitor 每 eval 至多一报、上电无伪边沿。
- 集成差分：M0 实际覆盖的黄金文件与 Verilator/NEMU 参照；完整范围与顺序见 M5d-8。
- 性能：相同负载、周期范围、编译选项及运行环境下比较 M0 与新实现，记录落 `ptmp/`；测量与结论归入 M5d-8。

## 7. 风险与对策

- **激活代数偏差**：各改造阶段使用已有定向用例并补足受影响行为；General 同轮拓扑传播风险归入 M5d-6，首个分歧通过 `dumpState()` 与参照定位。
- **参照覆盖不足**：M0 不含 DUT=105，XS 快照是截断记录；覆盖补充和独立参照校验归入 M5d-8，不能将新实现自身输出作为黄金。
- **性能回退**：实测 store 大小、publish 拷贝字节数、生成规模、构建资源及运行性能；根据测量定位瓶颈，不预设优化回填任务。
- **checkpoint 兼容**：沿用现有 JSON v2 与字节稳定往返，兼容所需枚举值保持稳定；本轮不引入 v1 兼容工程。
- **范围边界**：本轮不含模拟器多线程执行、P_output 门控跳过或 mem 地址区间精细化；C++ 多 TU 并行编译属于必做范围。

## 8. 默认策略与工作流约束

- 命名沿用“原名清洗 + 冲突追加 id 后缀”，确定性命名与来源映射由最终 layout 维护。
- eventActiveFlag 沿用每 act bit 对应超节点位图、P_event 中 OR 重建的紧凑形式。
- 各阶段运行时保持语义顺序，代码组织按规模拆函数和 TU；PCH 为测量后采用的构建手段。
- 全部构建、测试和脚本工作流经项目 Makefile；临时日志与工作流产物落 `ptmp/`。当前仍暂停编译，本次只调整计划。

## 9. 进展记录（截至 2026-10-01）

代码在 `wolvrix` 子模块（branch `grh/grhsim-ir`），脚本/Makefile 在根仓库
（branch `grh/grhsim-ir-gap-driven`）。已提交检查点为根仓库 `f239652`、
wolvrix `466d1bd`；本节保留历史结果，所有后续工作统一由第 10 节安排。

### 已完成

- **M0**：黄金基线设施落成——161/162 hdlbits DUT 黄金轨迹 + MANIFEST + XS
  coremark 快照（`ptmp/sim-refactor-baseline/`，端点 instrCnt=240349 /
  cycleCnt=99996 / pc=0x80000c0c）；`make check_sim_refactor_baseline` 门禁可用。
  openc910 无任何 grhsim 流程（在案），差分链不含它；dut_105 在 M0 采集时因
  used-bits dangling value 失败，故旧黄金集不含该例；M5b-1 已修复并通过
  GrhSIM testbench，全量 162 例均可运行，旧黄金覆盖仍为 161/162。
- **M1**（wolvrix `9bacb94`）：edgeDet op / SimPhase / verifier 框架 / JSON v2 /
  namedStores 等空壳。
- **M2a**（`d42c19d`）：`grhsim.classify-event-inputs` +
  `grhsim.lower-edge-detect` + cone_extract helper。
- **M2b**（`4cc25ff`）：`grhsim.extract-output-cones` +
  `grhsim.migrate-timeslot-tasks`。偏差：convert 的 `__event_*` 生成摘除从 M2
  推迟到 M5 随旧管线一起删。
- **M3**（`0dc0709`）：`cpu.st.split-phases` / `build-general-nodes` /
  `merge-general-supernodes` / `pack-general-functions` + 事件域禁合 +
  verifyCpuPhases + eventActs attr。**关键修正（计划外、已做主落地）**：事件域
  影响图只含值扇出边，不含 state 写→读边——否则双域设计被禁合规则打死且会丢
  更新；依据是语义文档"reg/latch/mem read 直接读 S 天然自由"。
- **M4**（`42fe2e8`，根仓库 `0144f63`）：`cpu.st.layout-named-stores` /
  `build-event-bitmaps` / `build-mem-write-plan` / `build-phase-schedule`，
  终态 `PhaseSchedule`=complete 合法档位（旧管线 complete==Schedule 判定不变）。
  七具名 store、supernode 序号=General 分枝树序展开、timeslotTriggers（JSON v2
  位置化尾字段，在 memWritePlan 后）、verifyCpuPhases 逐级放宽校验（位图/写计划/
  fanout/task/trigger 全量重算比对）。接受偏差：ActiveFlags aux 记总数 N（序号==
  数组下标）；mem 写 priority=per-mem op id 升序；latch-only 锥豁免事件位图。
  详见 `wolvrix/docs/grhsim_ir/passes/{layout-named-stores,build-event-bitmaps,
  build-mem-write-plan,build-phase-schedule}.md`。

### M5 检查点记录

- 原 M5 草稿规格：`ptmp/spec-m5.md`（生成代码契约、六阶段 eval 骨架、管线切换
  12 pass 序列、删除清单及其消费方盘点、差分推进门禁、xs-bugcase IR 接线方案）。
  其中旧执行队列已经由第 10 节替代。
- **M5a（新单 TU emit 实现）：已完成**，分片端到端验证后落地：
  - M5a-1 骨架+纯组合端到端：`cpu_phase_emit.{hpp,cpp}`（cpp 现 2922 行）全函数体
    实现；`grhsim-cpu-phase-emit-tests` ctest exe + 根 `test_grhsim_cpu_phase_emit`
    目标；七具名 store 生成、端口契约（第一个 public 块最前段）、eval/init/
    pInput/pPublish/pGeneral(双门控)/pOutput 主干、宽值走 `writeGrhSimRuntime`
    的指针+调用方缓冲 helper、`dumpState()`、MAX_ROUND=100000+未收敛 throw；
  - M5a-2 P_event+事件门控：edgeDet（prev 无条件更新）、eventAct 字节数组位打包
    （act/8 字节 act%8 位，三处一致）、位图 OR 重建 eventActiveFlag、timeslot
    flag 生命周期（P_event 置位/P_output 消费即清）；6 个事件定向用例（计数器
    自环、A→B 残留、上电无伪边沿、异步复位、双钟不吞标志、glitch 跨 round
    出沿——"同 eval 多边沿"按语义文档 §72 字面=派生信号跨 round 翻转）；
  - M5a-3 P_mem：四种写（memWrite/memFill/memAssign/memWriteSeq）act guard、
    cell 级变化检测（宽值 `grhsim_apply_masked_words_inplace`）、读者表静态
    精确/动态保守激活、优先级=plan 序原地顺序写（后写赢）；latch 环收敛、
    event-free mem 写收敛用例；
  - M5a-4 system task/DPI/timeslot/契约桩：$display/$monitor/$strobe 全路径
    （$monitor 历史值判定+每 eval 至多一报、timeslot flag 沿任务数据无关每沿
    都报——与 P_general 双门控任务的语义差已记录）、DPI import marshal、
    `configure_waveform`/`perf_counters()`（8 字段名固定、新语义计数、
    `GRHSIM_PERF_COUNT` 宏零开销）/`set_runtime_profile_enabled`/`dump_runtime_profile`
    契约桩；该检查点仍为单 TU，`taskCpp` 多 TU 占位未实现；目标管线不产生
    `core.compute.expr`，不为此追加旧形态支持任务；
  - M5a-5 硬化（修 M3/M4 三缺陷，定向用例全部去掉 `--max-op-in-compute-supernode 1`
    绕行）：**D1** merge rule 2 字面允许无事件 sink 并入事件域→event-free 成员
    被双门控丢执行，修法=EventDomainInfo 加 `unboundFree` 禁合第三条
    （cpu_partition.cpp）+ verifier 锁步；**D2** sink 边门控 × 电平敏感 mem 读者，
    修法=emit 侧 `eventGated_` 按"超节点含≥1 个带 event_acts 成员"计算（纯
    event-free 超节点 dataActiveFlag 单门控，依据 plan §112/§115；位图仍驱动
    eventActiveFlag 重建）；**D3** 整表 state.read 读者缺席 memWritePlan.readers，
    修法=build-mem-write-plan 补收（恒 dynamic 读者）。pass 文档同步。
    **检查点风险**：General 分枝超节点序=拓扑序无显式保证；同 eval 输入+沿到达时
    boundary fanout 落 Next 可能滞后一个沿。此性质在该检查点尚未充分验收。
  - 测试：`test_cpu_phase_emit.cpp`（1291 行）21 子项全绿（生成模型经系统
    clang++ -O2+UBSan 编译驱动比对）；phases/stores/event_lowering/mapping/
    schedule 套件无回归。
- **M5b-1 管线切换与旧 emit/legacy 删除（主要验证已通过）**：
  - 已删：旧 CPU emit 三件套（cpu_emit/cpu_shape_share/cpu_block_share + 头 +
    test_cpu_emit.cpp，GRHSIM_DIRECT_MEM 改动备份 `ptmp/grhsim_direct_mem_backup_20260930.diff`）；
    legacy 仿真（lib/emit/grhsim_cpp.cpp + 头 + 两个 emit 测试 exe）；
    `grhsim_runtime.{hpp,cpp}` 按修订后的清单保留供新 emit 生成 runtime 头；
    孤立的 `cpu_emit_shape` 测试 fixture 与 `scripts/wolvrix_xs_grhsim.py`、
    testcase/{big-comb,xs-components}/scripts/emit_grhsim.py；
  - 已切换：新 emit 正名 `cpu.st.emit-cpp`；`wolvrix_xs_grhsim_ir.py`
    CPU_MAPPING_PIPELINE=12 pass 新序列+旧选项清除；`HDLBITS_GRHSIM_BACKEND ?= ir`、
    hdlbits legacy 分支摘除；根 Makefile 旧 XS 目标摘除；pybind emit 接口适配；
    convert `__event_*` 生成摘除（grh_to_grhsim.cpp -21 行，lower-edge-detect
    适配原始事件标注，相关测试同步）；xs-bugcase CASE_001..005 新增独立
    GrhSIM IR 双驱动 `run_grhsim` 并保留原 SV `run`，CASE_006..024 继续由
    `run` 执行 GrhSIM 双驱动，根 `run_xs_bugcase_grhsim` 汇总入口已加入。
  - 验证完成：`source env.sh && make build` 全树通过；`make test_wolvrix` 为
    52/55，通过项无新增失败，三项失败与既有记录一致
    （`transform-comb-lane-pack`、`transform-repcut`、`ingest-write-back-slice`
    SEGFAULT）；GrhSIM 定向目标 `test_grhsim_cpu_phase_emit`、`test_grhsim_cpu_schedule`、
    `test_grhsim_cpu_mapping`、`test_grhsim_event_lowering`、`test_grhsim_cpu_phases`、
    `test_grhsim_cpu_stores` 全绿；本轮 GrhSIM CPU phase emit、event lowering、IR 与
    CPU mapping 回归全绿；默认 IR 管线 HDLBits 冒烟 DUT=001（组合）、023
    （时序）、116（512 位状态）、162（128-entry memory、异步复位、`$display`）全绿。
    HDLBits DUT 没有 `$monitor`/`$strobe`，两类 task 由 phase emit 与 event lowering
    定向测试覆盖。`grhsim.used-bits` 保留输出完整使用的截断 concat 全部操作数依赖，
    修复 DUT=105 的 dangling value；回归 `test_grhsim_cpu_mapping` 与
    `test_grhsim_reg_to_mem_rtl`（8192 样本）通过；默认 IR 管线 HDLBits 162/162
    testbench 全绿（`ptmp/hdlbits-grhsim-full/20260930-dut105-fixed/summary.txt`）。
    旧 emitter API/源文件在生产代码和构建注册中无引用；该检查点的部分文档与注释
    仍含旧路径。big-comb/xs-components 新 IR 本地入口已接线，尚无本地 benchmark
    实测结果。修复 CPU `sliceArray` C++ 括号生成、`$random`
    跨 output-cone clone 的单次采样，以及 1-bit DPI `svBit` ABI；新增对应 emit 回归。
    xs-bugcase 汇总 `make run_xs_bugcase_grhsim` 24/24 通过；2026-10-01 在
    CASE_001..003 的运行入口加入旧 coverage 文件清理后复测仍为 24/24，结果见
    `ptmp/xs-bugcase-grhsim/summary.txt`（各例日志位于同目录）。原 SV 路径 CASE_002
    仍有独立已知差异（cycle 3：`exit ref=1 wolf=0`），不影响 GrhSIM 对 Verilator
    的 120-cycle 对拍（JTAG DPI 59 次、RAM read 60 次、write 40 次）。
  - 清理：新 `cpu.st.emit-cpp` 拒绝旧 emit 选项；其注册测试确认旧选项已移除。

- **差分与整核检查点**：HDLBits testbench 162/162、xs-bugcase 24/24 已通过；
  HDLBits 黄金逐 eval 差分尚未完成。2026-10-01 完整 XiangShan 模型已生成并完成
  GrhSIM JSON 字节稳定往返，随后按作者要求停止编译；emu 构建未完成、CoreMark
  未运行，暂无整核编译失败证据。

### 环境注意事项（持续有效）

- ~~cpu_emit.cpp/test_cpu_emit.cpp 他人未提交改动~~：已随 M5b-1 删除，改动备份在
  `ptmp/grhsim_direct_mem_backup_20260930.diff`（903 行 diff），**最终报告与提交
  说明里必须点名提醒属主**。
- `make test_wolvrix` 全量有 3 个既有失败（transform-comb-lane-pack、
  transform-repcut、ingest-write-back-slice SEGFAULT），与本重构无关，不修。
- `scripts/grhsim_unpaired_registers.py` 是他人的未跟踪文件，不动。
- `testcase/hdlbits` 默认 GrhSIM 后端已切到 IR；相关修改已纳入检查点。

## 10. 2026-10-01 改造计划

### 作者建议与设计决议

以下四点来自作者本次明确指示，已同步到语义文档；原计划中有关逐 RTL 字段布局及优化顺序的描述据此调整。

1. **生成 C++ 分 TU 并行编译**：作者指出当前整核只生成一个巨大 cpp 的方案无法承担编译，必须实现多个 TU 的生成、并行 C++ 编译和完整链接。
2. **GRH simplify 保留 declaredSymbol**：声明来源必须带到 GrhSIM IR 流水线中指导优化，并在折叠、合并、打包、分区和序列化后保持可追溯。
3. **先全图优化，再两轮分解**：全图上执行 `reg-to-mem`、`comb-pack` 等优化后全图 `simplify`；第一轮拆出 P_event/P_general/P_output，各分区独立 `simplify`；第二轮在 P_general 内划分 supernode，实现活动度调度。
4. **按性能动机区分 store**：允许改变、折叠、合并状态，性能优先并提供可读性，允许数组且鼓励恢复高维数组。regLatchStore 负责零碎状态，通过 publish 整块拷贝实现 NBA；memStore 负责大块连续状态，在独立阶段处理以避免大规模拷贝，同时实现 NBA。

### 当前检查点

- 2026-10-01 08:36 生成的完整 XiangShan 模型位于 `ptmp/xs-coremark-six-phase-20261001/model/`：单个 `grhsim_SimTop.cpp` 约 1.3 GiB、15,080,494 行，公共头约 99 MiB；生成 Makefile 仅列一个 cpp。生成和 JSON 往返成功只说明生成流程完成，整核可编译性与运行正确性均未验收。
- 构建已按作者要求停止，停在 difftest 支撑代码编译期间；没有编译失败结论，也没有 CoreMark/NEMU 运行结果。本次仅记录建议和计划，后续实施前保持暂停编译。
- 当前脚本两轮完整 CPU mapping 之间插入 packing/used-bits 等语义变换。`pack-bit-registers` 仍匹配旧 `event_edges`/私有历史状态，第一轮 `lower-edge-detect` 已改成 `event_acts`，正常 regWrite 无法匹配打包；生成头未出现 `packed_bits_` 字段。旧排布和无匹配的 packing 均需在新优化层次中处理。
- HDLBits 162/162、xs-bugcase 24/24 是既有检查点结果；流水线重排后必须重新验证。原 M5b/M5c/M6 的必要工作已并入下列任务，本节为唯一后续执行队列，全部改造项待实施。

### 原未完成任务的处置

| 原任务 / 开放项 | 处置 | 新归属 |
| --- | --- | --- |
| M0 黄金覆盖缺口、M5c 黄金差分与完整 XS CoreMark | 保留，区分旧黄金、Verilator 独立参照和完整 NEMU difftest | M5d-8 |
| M5b-2 旧 mapping、旧 schedule 消费者及孤儿 helper 清理 | 保留，目标 mapping 接续后清理并同步注册/测试/构建 | M5d-6 |
| M5b-3 文档重写收口 | 合并到各改造阶段同步，最终核对生产文档与入口 | M5d-1 至 M5d-8 |
| M5b-4 最终验收提交 | 合并到统一验收，不再维护独立提交里程碑 | M5d-8 |
| M5a General 同轮拓扑传播风险 | 保留，补足调度约束和定向验证 | M5d-6 |
| M5b-1 big-comb/xs-components 本地入口验证 | 入口适配与小规模验证纳入集成；完整 benchmark 继续暂缓，不作为整核验收前置 | M5d-8 |
| M6 性能对齐、宽值 helper 性能约束 | 保留同负载测量及指针/调用方缓冲约束 | M5d-7、M5d-8 |
| M6 dirty 拷贝、edge 向量化、eval 快路径、direct commit 等预设回填清单 | 删除独立待办，后续仅凭瓶颈测量确定新增优化 | 不列本轮任务 |
| 原 openc910 差分链、`core.compute.expr` 旧形态支持、JSON v1 兼容 | 当前无必要目标管线消费者或既定要求，删除本轮待办 | 不列本轮任务 |
| 强制 PCH 与固定字段数/编译秒数阈值 | 删除强制门槛，改为公共头体积控制及实测后决定 | M5d-7 |

### GRH IR 完整 pass 流水线（目标顺序）

以下为待实施的目标顺序，不代表当前脚本已经采用。“复用”表示沿用现有职责；“改造”表示已有 pass 需要调整；“新增”中的名称为拟定名称，尚未注册实现。构建与测试仍保持暂停。

GRH IR 负责 RTL 归一化、层次消除和基础化简，同时保留声明来源。前端 ingest 在这些 pass 之前执行。

| 顺序 | Pass | 职责 | 状态 |
| --- | --- | --- | --- |
| 1 | `xmr-resolve` | 解析跨层次引用 | 复用 |
| 2 | `memory-read-retime` | 归一化存储读时序；改写后维护声明来源关联 | 改造 |
| 3 | `multidriven-guard` | 在 flatten 前检查并报告多驱动冲突 | 复用 |
| 4 | `blackbox-guard` | 处理 blackbox，满足后续 lowering 约束 | 复用 |
| 5 | `latch-transparent-read` | 展开 latch 透明读的数据通路 | 复用 |
| 6 | `hier-flatten` | 平坦化层次，保留完整声明层次名 | 复用 |
| 7 | `comb-loop-elim` | 处理组合环 | 复用 |
| 8 | `simplify` | 按 2-state 语义做固定点化简，保留 declaredSymbol 来源 | 改造 |
| 9 | `memory-init-check` | 检查最终存储初始化形式 | 复用 |

`simplify` 的现有内部顺序为：

```text
const-fold -> redundant-elim -> dead-code-elim
```

迭代至稳定或达到轮数上限（当前默认最多 8 轮）。现有 `simplify` 已向子 pass 传递 `keepDeclaredSymbols`，`Session.run_pass` 和 lower 的 `keep_declared_symbols` 默认均为 true；下一阶段显式启用并验证贯穿，完善折叠、合并之后的来源映射，使声明信息继续指导优化。保留来源不要求永久保留已经可消除的计算或字段。

随后执行 GRH 结构/声明来源校验与 checkpoint，再通过 `lower_grhsim` 进入 GrhSIM IR。lower 属于转换 API，不是 pass；目标是保留 declaredSymbols、generateGroups、数组形状和 origin，并建立原声明到新 Value、State、位段、数组索引的关联。当前 lower 携带的声明信息是只读文本来源元数据，尚无语义改写后持续维护来源映射的契约；此关联属于下一阶段新增工作。复用已有声明元数据承载，显式启用 `keep_declared_symbols` 和 `keep_origins`，补齐优化可使用的关联契约。

### GrhSIM IR 完整 pass 流水线（目标顺序）

按“图 → 分区 → 映射调度”三段推进，与语义文档的构建顺序一致：A 大图优化与 B 第一轮分解/分区优化全部在纯语义层进行，不建立任何 CPU mapping；B 末尾语义层封板后，C 段建立一次最终 CPU mapping 并单向推进到 emit，不回改语义。旧管线“mapping → 语义改写 → mapping”的往返不再出现。以下为待实施的目标顺序，不代表当前脚本已经采用；“复用/改造/新增”含义同前。构建与测试仍保持暂停。

#### 阶段 A：大图优化（纯语义层，无分区、无 mapping）

入口：lower 完成、携带声明来源关联的全图。出口：完成全部全图改写与 store 分类决策的优化后全图。

| 顺序 | Pass | 职责 | 状态 |
| --- | --- | --- | --- |
| A1 | `grhsim.verify` | 校验 lower 结果及声明来源关联 | 改造 |
| A2 | `grhsim.canonicalize-compute` | 全图归一化（赋值链/CSE/恒等式/concat 折叠），为模式识别准备输入 | 改造 |
| A3 | `grhsim.reg-to-mem` | 在全图恢复连续表状态及数组结构，支持高维形状 | 改造 |
| A4 | `grhsim.comb-pack` | 全图组合逻辑打包，利用声明、位段和数组形状信息 | 新增 |
| A5 | `grhsim.pack-bit-registers` | 合并适合打包的零碎状态，改为依赖事件域和读写安全分析 | 改造 |
| A6 | `grhsim.simplify(scope=whole)` | 对上述改写结果做全图固定点化简 | 新增 |
| A7 | `grhsim.select-state-stores` | 唯一 store 分类决策点：按优化后的规模、连续性及更新方式确定 regLatchStore/memStore 归属与 NBA 契约，规范化读写 | 新增 |

#### 阶段 B：第一轮分解与分区优化（纯语义层，无 mapping）

入口：A 段优化后、已分类的全图。出口：三个独立化简的计算分区及 P_mem 写入职责；B8 封板后不再有任何语义改写。

| 顺序 | Pass | 职责 | 状态 |
| --- | --- | --- | --- |
| B1 | `grhsim.classify-event-inputs` | 在原始事件边仍存在时确定事件输入类别 | 改造 |
| B2 | `grhsim.lower-edge-detect` | 生成边沿检测和 Event 专有历史状态，建立 P_event 计算锥 | 改造 |
| B3 | `grhsim.extract-output-cones` | 提取 P_output 计算锥 | 改造 |
| B4 | `grhsim.migrate-timeslot-tasks` | 确定 time-slot task 归属，对新增监测状态增量分类并保留提交时机 | 改造 |
| B5 | `grhsim.split-phases` | 完成 P_event/P_general/P_output 分区及阶段边界，确定 P_mem 写入职责 | 新增，拆出旧职责 |
| B6 | `grhsim.simplify(scope=phase)` | 分别化简三个计算分区，保留各自边界和副作用根 | 新增 |
| B7 | `grhsim.clone-shared-compute` | 边界感知克隆：只克隆能消除预测超节点边界的廉价共享计算 | 改造，可选；语义层最后一个改写 pass |
| B8 | `grhsim.verify` | 语义层封板：校验分区、状态读写、来源映射及 NBA 契约 | 改造 |

#### 阶段 C：第二轮分解与映射调度（一次最终 CPU mapping，单向不回改语义）

入口：B8 封板后的分区 IR。出口：多 TU C++、共享头文件及构建清单。

| 顺序 | Pass | 职责 | 状态 |
| --- | --- | --- | --- |
| C1 | `cpu.st.build-general-nodes` | 初始化最终 CPU mapping；锥吸收构造 General 调度节点 | 改造 |
| C2 | `cpu.st.merge-general-supernodes` | 仅在 P_general 中按事件域约束形成活动度 supernode；超节点序号按划分结果顺序在此确定 | 改造 |
| C3 | `cpu.st.layout-named-stores` | 纯物理布局：消费 A7 分类注解，排布字段/偏移/命名，零分类决策 | 改造 |
| C4 | `cpu.st.build-event-bitmaps` | 生成事件触发与 General 活动传播静态表，基于 C2 超节点序号 | 改造 |
| C5 | `cpu.st.build-mem-write-plan` | 生成大块存储的延迟写入、冲突和提交计划 | 改造 |
| C6 | `cpu.st.pack-general-functions` | 将 supernode 分批组织为任务/函数粒度（调度的输入与代码组织，非划分） | 改造 |
| C7 | `cpu.st.build-phase-schedule` | 建立六执行阶段及收敛循环的最终计划 | 改造 |
| C8 | `cpu.st.plan-translation-units` | 按源码规模拆 TU，覆盖所有阶段、初始化及静态表 | 新增 |
| C9 | `grhsim.verify` | 校验最终 mapping、布局、调度及 TU 依赖 | 改造 |
| C10 | `cpu.st.emit-cpp` | 输出多 TU C++、共享头文件及构建清单 | 改造 |

#### 三个归位决议

1. **clone-shared-compute 的位置与成本模型**：该 pass 减少的是 P_general 超节点边界（boundary 槽位、变化检测与激活通知），不是分区边界——事件/输出锥按“复制+剥离”自包含，不存在跨分区共享计算。它被两条硬约束夹在语义层末尾：作为语义改写必须在唯一一次最终 mapping 之前（禁止“mapping → 语义改写 → mapping”）；又必须在最后一次含 CSE 的化简之后（否则克隆被 CSE 重新合并）。相对旧表位置不变，但成本模型从“fanout≥2 即克隆”的盲启发式改为边界感知：build-general-nodes 的锥吸收规则是确定性的（多消费者、或其消费者跨 General 集合的值必然成为边界候选），不建立超节点也能静态模拟出预测边界集；只克隆能消除预测边界的廉价双射生产者（沿用现有 not/xor/add/sub 常数等候选定义与 max-fanout/max-clones 预算）。边界预测逻辑抽成与 build-general-nodes 共享的 helper，保证两遍规则一致；未启用或零命中时记录原因与边界消减计数。曾考虑并入 build-general-nodes 在锥吸收停下时就地克隆，因会把语义改写混入 BackendMapping pass（破坏 pass 分类、revision 规则与逐 pass dump/verify 粒度）而不采用。
2. **第二轮分解只有两步，函数打包移到调度段**：build-general-nodes（锥吸收 → node）与 merge-general-supernodes（coarsen+DP+事件域约束 → supernode）是第二轮分解本体，保留为两个 pass 对应两个可独立校验的 stage。pack-general-functions 是任务粒度与代码组织（helperChunks 控制单函数规模；EmitFunction 即 P_general 的 task 粒度），移至 build-phase-schedule 之前。移位前置：超节点序号与函数打包解耦——序号在 merge-general-supernodes 输出时按划分结果顺序确定（0..N-1），不再按“emit function 子序 → supernode 子序”派生；函数打包只记录各 EmitFunction 持有的超节点区间。解耦后 layout-named-stores 的 stage 前置从 GeneralFunctions 降为 GeneralSupernodes（其实际输入只是超节点集合：boundary=跨超节点 value 集、activeFlags N=超节点数）。
3. **store 分类与布局的职责边界**：分类是语义决策，布局是物理决策，二者不重复。现实现中 layout-named-stores 凭 TypeKind::Array 做隐式分类（non-array→regLatch、array→mem）属于残留，M5d-6 摘除。

   | 决策 | 负责 pass | 时机 | 产物 |
   | --- | --- | --- | --- |
   | 状态归属 regLatchStore/memStore 与读写/提交契约 | `grhsim.select-state-stores` | A7（唯一分类决策点） | 逐状态 store 归属注解 + NBA 契约 |
   | prevEvent/eventAct 的 (event,edge) 聚类与槽位资格 | `grhsim.lower-edge-detect` | B2 | 聚类与 act/prev 索引注解（专有 store，不参与 regLatch/mem 分类） |
   | timeslotTrigger 资格与新增监测状态增量分类 | `grhsim.migrate-timeslot-tasks` | B4 | timeslot flag 注解 |
   | boundaryValueStore 成员集与全部物理布局 | `cpu.st.layout-named-stores` | C3 | 字段/偏移/对齐/命名；boundary 集由第二轮分解结果（跨超节点与 General→Mem 写参数边界）确定 |

拟新增的 `grhsim.simplify` 内部顺序为：

```text
grhsim.const-fold          # 新增：完整常量运算折叠
-> grhsim.canonicalize-compute
-> grhsim.bitwise-predicates
-> grhsim.bitwise-muxes
-> grhsim.mux-chain-fold
-> grhsim.used-bits         # 位需求分析、窄化及死锥清理
```

整个序列迭代至稳定或达到轮数上限。分区模式禁止跨阶段 CSE；共享状态的位需求先取各分区需求的并集，不能仅凭单个分区的需求窄化或删除共享状态。保留分区接口和副作用根；`clone-shared-compute` 放在固定点化简之后，避免与 CSE 反复抵消——它是语义层最后一个改写 pass，其后不再回到含 CSE 的化简，分区优化段因此为单向链：“迭代”体现在各 simplify 内部不动点与 clone 的边界反馈；未来若实测需要“改写后重新分区”的真迭代，只能在语义层闭环且不建 mapping，当前不列。语义改写后按需 verify/dump，不要求每个子 pass 都建立 CPU mapping。

实施时遵守以下阶段约束：

- **语义分区与 CPU mapping 解耦**：从旧 `cpu.st.split-phases` 拆出语义归属处理；A/B 段不存在任何 CpuBackendMapping，B8 语义层封板后不再改写 G；C 段由 `cpu.st.build-general-nodes` 初始化唯一一次最终 mapping 并构造 General 节点，随后单向推进到 emit。
- **事件依赖顺序**：`reg-to-mem` 和 `classify-event-inputs` 在 `lower-edge-detect` 消除原始 `event_edges` 之前执行；`pack-bit-registers` 改造为可在全图层进行安全分析，不依赖预先生成的完整 CPU schedule。
- **历史状态的归属与提交**：`lower-edge-detect` 当前使用独立 PrevEventStore，其事件沿历史按 Event 所属阶段更新，不默认转入 NBA publish。`migrate-timeslot-tasks` 新增的 `__tslot_prev_*` StateObjects 在分区 simplify 前增量完成语义存储分类，并保留 time-slot 监测所需的提交时机；这不触发第二轮完整 CPU mapping。分区化简后校验分类和写入阶段的一致性。
- **三计算分区与六执行阶段分别定义**：计算分区为 P_event/P_general/P_output，运行顺序仍为 `P_input -> [P_event -> P_general -> P_mem -> P_publish]* -> P_output`；P_mem 承接已采样的大块存储写入，P_publish 承接零碎状态发布。
- **store 分类体现性能动机**：零碎状态进入 regLatchStore，publish 整块拷贝实现 NBA；大块连续状态进入 memStore，独立提交以避免大规模拷贝。数组类型、原 RTL 声明类别均不能直接决定 store；分类决策唯一在 A7（另有 B2/B4 两个专有 store 增量点，见归位决议 3 职责表），B5 split-phases 依此分类确定 P_mem 写入职责；字节布局在 C3，C3 只消费分类注解做物理排布，不得再做分类决策。
- **函数打包与序号解耦**：超节点序号在 C2 按划分结果顺序确定，与函数打包无关；函数打包（C6）只决定任务粒度与单函数规模，TU 划分（C8）是纯代码组织；二者均不改变活动度粒度和六阶段执行顺序。
- **TU 拆分覆盖全部生成代码**：Input/Event/General/Mem/Publish/Output、初始化和静态表均需规模受控；拆 TU 不改变模拟执行顺序或活动度粒度。并行编译与链接由 Makefile 工作流负责，属于生成后的构建步骤。

### 实施顺序、依赖与检查点

以下重新划分 M5d-1 至 M5d-8，取代本节此前的六项任务编号。pass 运行顺序与开发排期分别约束：开发时先完成可复用的 simplify 基础设施，再接通全图和分区调用；运行时仍严格执行上面的目标 pass 顺序。

主依赖链为 `M5d-1 -> M5d-2 -> M5d-3 -> M5d-4 -> M5d-5 -> M5d-6 -> M5d-7 -> M5d-8`。多 TU 框架和 Makefile 多源编译接线可基于现有小模型提前并行开发；M5d-7 的目标 TU 规划、最终 emit 与整核可编译性验收依赖 M5d-6 的最终布局和调度。每个阶段独立验收自身契约，不将后续尚未实现的优化或 emit 作为前置门禁。

| 任务 | 覆盖 pass / 工作流 | 输入 -> 输出检查点 |
| --- | --- | --- |
| M5d-1 声明来源与 GRH/lower | GRH 1-9、lower、A1 | RTL/GRH -> 携带可维护来源关系的全图 GrhSIM IR |
| M5d-2 simplify 基础设施 | `grhsim.const-fold`、`grhsim.simplify` 与现有化简子 pass | 具备来源关系的 IR -> 支持 whole/phase scope 的化简能力 |
| M5d-3 全图优化 | A2-A6 | 未分区全图 -> 数组恢复/打包及全图 simplify 后的 IR |
| M5d-4 语义存储分类 | A7 | 优化后全图 -> 明确 store 归属、读写与提交契约的 IR |
| M5d-5 第一轮分解与分区优化 | B1-B8 | 已分类全图 -> 三个独立化简的计算分区及 P_mem 写入职责 |
| M5d-6 第二轮分解与最终 mapping | C1-C7、阶段 verify、旧实现清理 | 分区 IR -> General supernode、物理布局、静态表与执行计划 |
| M5d-7 多 TU 规划与 emit | C8-C10、Makefile 多源构建 | 最终 mapping -> 规模受控且可并行编译链接的 C++ 模型 |
| M5d-8 入口、回归与整核验收 | 统一工作流、参照差分、资源/性能测量、提交收口 | 目标管线与生成模型 -> 可复现的完整验收证据 |

M5d-1、M5d-2、M5d-3 已完成（见上文）；M5d-4 至 M5d-8 均待实施。下述构建和测试是后续验收要求。

### M5d-1 声明来源与 GRH/lower 契约（已完成，2026-10-01）

- 范围：审查 GRH `memory-read-retime`、`simplify` 三个子 pass、hier-flatten、store/load 和 lower；显式保留 declaredSymbol，避免以关闭声明保留换取优化。
- 交付：定义可维护的声明到 Value/State/位段/数组索引的来源表示和更新规则，关联 generateGroups、数组维度及 origin；支持折叠别名、合并来源和拆分范围，并扩展 GrhSIM model/verifier/JSON。复用已有文本元数据，不把它当作已实现的持久关联。
- 检查点：GRH 最终结果与 lower 后全图均可定位原声明；基础追溯和 JSON 往返通过。不要求本阶段已实现 comb-pack、数组恢复或最终布局，这些变换的来源维护在所属阶段验收。
- 文档：同步来源表示、GRH/lower 接口和 JSON 契约；给出声明被折叠或拆分后的映射小例子。

**GRH 侧审查结论**（均有既有或新增回归锁定，本阶段不需改语义代码）：

- `simplify` 三个子 pass 已保留声明：const-fold 物化新驱动 op 保留 declared 值、
  redundant-elim 无条件不合并 declared、DCE 把 declared 值/存储当存活根；
  新增用例（transform-simplify Case 10/11）覆盖折叠物化、别名保护、未读声明
  寄存器存活及关闭开关后的对照消除。
- `memory-read-retime` ROM 模式守卫跳过 declared 地址寄存器（改写会擦除它），
  SimpleRam 模式只擦除读口 op 不动声明；新增用例（transform-memory-read-retime）
  覆盖声明阻断 ROM 改写与关闭开关后的对照改写。
- `hier-flatten` 改名 + 重新登记 + 组重映射完整传播，既有
  test_hier_flatten_pass.cpp 覆盖；store/load 对 declaredSymbols（必需键）、
  generateGroups（可选键）与 `loc.origin/pass/note` 全量往返。
- `Graph::validateDeclaredSymbols()` 提供"声明可定位"的 GRH 侧自检，新增用例
  在各 pass 后调用确认无悬空锚点。

**GrhSIM 侧新增持久关联**：

- 表示（`include/grhsim/ir/model.hpp`）：`DeclProvenance`（symbol/origin/width/
  shape/slices）+ `DeclProvenanceSlice`（kind ∈ direct/alias/merged，target ∈
  value/state/function + 线性位偏移区间）。数组位偏移按行主序线性化，`shape`
  保留维度还原信息；`width=0` 的 slice 是整体关联标记（非 logic 目标与 DPI
  函数专用）。模型 API：`upsertDeclProvenance`（要求 declared 成员）/
  `findDeclProvenance`/`declProvenances()`；`compact()` 重映射 slice 目标并丢弃
  已删除目标的 slice（记录保留、可为空，表示"声明已知、当前未实现"），
  `clone()`/`reserve()` 同步支持。
- lower（`lib/grhsim/convert/grh_to_grhsim.cpp`）：`keepDeclaredSymbols` 开启时
  为每个能解析到存活 value/state/function 的声明写入一条 direct 全覆盖 slice，
  数组声明沿嵌套 array 类型恢复 shape；解析不到的声明只留名单锚点。
- verifier（`lib/grhsim/ir/verifier.cpp`）：结构校验——symbol 必须是 declared
  成员、origin/目标下标在界内、slice 范围不越过声明与目标的线性大小、同一
  记录内声明区间不重叠、whole-object 标记只允许零偏移；语义等价性仍由执行
  改写的 pass 负责。
- JSON（`lib/grhsim/io/json.cpp`）：`declProvenance` 作为 `mappings` 之后第三个
  可选尾键（位置化；非空时拖出前两个键），旧 checkpoint 直接可读，字节稳定
  往返由测试锁定。

**检查点证据**：

- `make build` 全树通过；`grhsim-ir-tests` 新增 `runDeclProvenanceTest` 全绿
  （lower 覆盖 7 类声明、关闭开关清空、JSON 字节稳定往返、clone、compact
  重映射/丢弃、verifier 拒绝 5 类腐败记录 + API 拒绝未声明符号）；
  `transform-simplify`/`transform-memory-read-retime` 新用例全绿。
- `make test_wolvrix` 52/55，三项既有失败不变（transform-comb-lane-pack、
  transform-repcut、ingest-write-back-slice SEGFAULT），无新增失败；
  `make run_xs_bugcase_grhsim` 24/24 通过。
- GrhSIM IR 流程 HDLBits 冒烟 DUT=001/023/116/162 全绿（hdlbits 脚本已显式
  `keep_origins=True, keep_declared_symbols=True`）；`test_grhsim_reg_to_mem_rtl`
  8192 样本通过（同开关）。dut_116 lower 后 4/4 声明含 direct 全覆盖 slice
  （证据 `ptmp/m5d1_dut116_lower_only.json`；管线末端 JSON 中 clk 的 slice 被
  后续 pass 的 compact 按安全网规则丢弃，pass 级维护属 M5d-2 起）。
- Makefile 新增目标：`test_grhsim_ir`、`test_transform_simplify`、
  `test_transform_memory_read_retime`；XS 脚本 GRH pass 循环与 lower 均显式
  `keep_declared_symbols=True`（lower 另加 `keep_origins` 由
  `--keep-origins` 控制，默认开）。
- 附带发现（非本任务引入，不修）：纯 Verilator 流程 `run_hdlbits_test DUT=116`
  的 tb_116.cpp 与本机 Verilator 5.051 的 `VlWide`（无隐式指针转换）不兼容，
  属既有问题——emit 产物字节未变（Verilator 未重写任何模型文件），9-30 的
  162/162 全绿记录基于 `run_all_hdlbits_grhsim_tests_report`（GrhSIM 流程），
  该流程下 116 依然全绿。
- 文档：`docs/grhsim_ir/overview.md` 新增 §3.4.1（表示、线性化约定、维护契约、
  折叠别名/合并来源/拆分范围小例子、JSON 尾键）；`flows/cpu-st.md` lower 段
  同步；`docs/grh/grh-ir.md` §4.3.2 补 lower 去向；`json.hpp` 格式注释更新。

### M5d-2 统一 simplify 基础设施（已完成，2026-10-01）

- 范围：新增 `grhsim.const-fold` 与统一 `grhsim.simplify`，组合 canonicalize-compute、bitwise-predicates、bitwise-muxes、mux-chain-fold、used-bits，按既定顺序迭代至稳定或轮数上限。
- 交付：whole/phase scope、变化汇总和固定点终止规则；phase 模式保留分区接口、副作用根和跨分区引用，禁止跨阶段 CSE。共享状态的位需求取全分区并集，局部需求不能单独删除或窄化共享状态。全部子 pass 维护 M5d-1 的来源关联。
- 检查点：使用全图及已有阶段标注的定向模型验证常量折叠、窄化、死锥清理、跨阶段共享状态、DPI/随机采样和副作用保留；化简结果 verify/JSON 往返通过。分区构建本身由 M5d-5 完成。
- 文档：记录子流程、scope 边界、终止条件和来源更新规则；clone-shared-compute 不加入此固定点。

**交付清单**（wolvrix 子模块，branch grh/grhsim-ir）：

- 内部复用层 `lib/grhsim/pass/simplify_internal.{hpp,cpp}`：`SimplifyScope`
  （wholeGraph 或限定单相）+ `SimplifyStepReport`（changed + 结构化计数）+ 六个
  子步骤函数；来源维护 helper——`redirectProvenanceValueSlices/StateSlices`
  （折叠重定向，direct→alias/merged）与 `clampProvenanceValueSlices/StateSlices`
  （窄化重切片并截到存活前缀，kind 不变，整段超出则丢弃）。
- 新 pass `grhsim.const-fold`（`lib/grhsim/pass/const_fold.cpp`）：全常量 operand 的
  两态 logic 计算 op 就地改写为 `core.compute.constant`（result/ID/依赖不变，来源零
  维护）；worklist 一次传播到位；四态值不折叠；div/mod 除零不折叠（保留原运行时
  行为）；任意宽度经 slang SVInt 求值，字面量 `<width>'h<hex>` 回写。
- 统一 pass `grhsim.simplify`（`lib/grhsim/pass/simplify.cpp`）：固定子序列
  const-fold → canonicalize-compute → bitwise-predicates → bitwise-muxes →
  mux-chain-fold → used-bits；`--scope whole|phase`（phase 按 Event→General→Mem→
  Output 逐分区执行，可选 `--phase` 限定单分区）、`--max-rounds N`（默认 8）；整轮
  无变化即收敛，撞限 warning；汇总头行（scope/phases/rounds/converged）+ 各子步骤
  累计计数。
- 五个既有子 pass 内部化（standalone 注册名与计数键不变，委托 step 函数）：
  - canonicalize-compute：phase scope 下赋值链来源/CSE 表/concat 折叠/删除/rewire
    全部限本相 op，等价状态合并要求全部引用 op 在本相；新增来源维护——被折叠 value
    的 slice 重定向为 alias，被合并状态重定向为 merged（compact 前执行）。
  - bitwise-predicates / bitwise-muxes / mux-chain-fold：就地改写或限相 eligibility；
    mux-chain-fold 的内层 link 无等价存活体，slice 由 compact 安全网丢弃（空锚点）。
  - used-bits：分析始终全图（共享状态位需求天然为全分区并集）；新增 opaque 规则
    ——分区外 op 的 operand/result 全使用、引用状态全宽，局部需求不能单独窄化/删除
    共享状态；变换只动本相 op（收窄要求 producer 与全部消费者同相，状态收窄要求
    全部引用同相）；窄化重建的 value/state 的 slice 经 clamp helper 截到存活前缀。
- 测试 `tests/grhsim/test_grhsim_simplify.cpp`（新目标 `grhsim-simplify-tests`，
  Makefile `test_grhsim_simplify`）：常量折叠 26 项（含 128 位环绕、有符号 ashr、
  二阶传播、除零/四态拒绝）；whole scope 定向模型（折叠别名 alias、CSE 声明重定向、
  mux 链折叠、窄化 clamp、死锥空锚点、等价状态 merged、DPI/system task/随机函数保留、
  9 个 output 全保留）；phase scope（单相死锥对照、共享状态不窄化 vs whole scope 收窄
  至并集 8 位、相内状态窄化至 4 位）；lower 后真实模型全图 simplify 声明全部可定位；
  参数拒绝（未知键、--phase 脱离 scope、none 相、max-rounds 0）与轮数上限 warning；
  各用例 verify + JSON 字节稳定往返。

**检查点证据**：

- `make build` 通过；`make test_grhsim_simplify` 全绿；`make test_grhsim_ir` 及
  `make test_wolvrix` 53/56，恰为 3 项既有失败（transform-comb-lane-pack、
  transform-repcut、ingest-write-back-slice SEGFAULT），无新增失败。
- `make run_xs_bugcase_grhsim` 24/24；HDLBits GrhSIM 冒烟 DUT=001/023/116/162 全绿，
  且 `run_all_hdlbits_grhsim_tests_report` 162/162 全绿；
  `test_grhsim_reg_to_mem_rtl` 8192 样本 PASS（以上流程 exercising 重构后的各独立
  子 pass）。
- 文档：`docs/grhsim_ir/passes/const-fold.md`、`passes/simplify.md` 新增；
  `passes/used-bits.md` 补相位 scope 与来源维护节；`overview.md` §3.4.1 维护契约
  注明 simplify 子 pass 主动维护、compact 仅为安全网；`flows/cpu-st.md` 注明统一
  入口已就绪、生产流程接线属后续阶段。
- 备注：`grhsim.simplify`/`grhsim.const-fold` 尚未接入 XS/HDLBits 生产 pass 列表
  （A6 接线属 M5d-3，B6 属 M5d-5）；整核 XS emu 编译按既定决定仍暂停。

### M5d-3 全图优化与全图 simplify（已完成，2026-10-01）

- 范围：依次接通全图 canonicalize-compute、reg-to-mem、拟新增 comb-pack、改造后的 pack-bit-registers，再调用 `simplify(scope=whole)`；此时没有计算分区或 CPU mapping。
- 交付：利用声明及结构关系识别同族状态、恢复数组与高维维度、打包组合逻辑和零碎状态。pack-bit-registers 使用原始事件标注及读写安全分析，不依赖旧私有历史引用、quiescenceProjection 或完整 CPU schedule；候选不能安全合并时显式拒绝。
- 检查点：结构校验、来源追溯、JSON 往返与可用的定向差分通过；依赖新布局/调度的运行差分在 M5d-7 接通后完成，不作为本阶段的反向依赖。记录操作/状态数量、数组维度与规模及各优化命中数，无匹配不计作优化已生效。恢复数组类型不自动选择 memStore。
- 文档：写明各全图 pass 的匹配条件、拒绝条件和输入/输出例子，保留优化前后 checkpoint。

**交付清单**（wolvrix 子模块，branch grh/grhsim-ir）：

- 共享来源维护 helper（`lib/grhsim/pass/simplify_internal.{hpp,cpp}`）新增
  `mergeProvenance{Value,State}Slices`：被合并实体的 slice 重定向为目标实体内的偏移位段
  （kind Direct→Merged，targetOffset += 每实体 bit 基址；width==0 整体标记丢弃，因为合并后
  声明由位段实现）。A3/A4/A5 三个 pass 共用。
- A3 `grhsim.reg-to-mem`（`lib/grhsim/pass/reg_to_mem.cpp`）：本就纯语义层（无 mapping/phase
  依赖），本次补齐两项契约——(1) 来源维护：compact 前把每个被合并行的 slice 重定向为新表
  状态的 Merged 元素位段（targetOffset=行号×元素宽）；(2) 声明族形状恢复：当一族全部行都是
  声明符号且层次名只在 `_` 分隔的数字 token 位上变化、数字覆盖从 0 开始的完整矩形网格且行序
  等于行主序线性化时，恢复形状（`64` / `16x4`），新表命名为 `__reg_to_mem_<pattern>__<首行id>`
  （pattern 用 `@` 标出变化位）；TSV 增加尾部 `shape` 列（ DictReader 消费方兼容），info 新增
  `provenance_records`/`declared_families`/`max_array_dims`。高维不改成嵌套数组类型：状态类型保持
  一维平坦（mem op 寻址语义不变），维度信息按 M5d-1 行主序约定落在来源记录与命名上，物理布局
  归 C3。
- A4 `grhsim.comb-pack`（新，`lib/grhsim/pass/comb_pack.cpp` + hpp）：GRH comb-lane-pack 的
  GrhSIM 移植。根来源三路（声明 provenance slice 命中的 value / output.write 操作数 / 写口数据
  操作数 regWrite·latchWrite=1、memWrite=2、memFill·memAssign=1、memWriteSeq 每个三元组
  data）；内部 op 白名单 not/and/or/xor/xnor/assign 与 mux（mux 仅限两态——四态 sel 的 X 合并
  语义 masked-select 无法复现）；签名含 op 名+结构化类型键（宽/符号/逻辑域）+排序参数，叶子只看
  类型键；桶内按声明族（名字数字 token → `@` 模式，行主序索引）+锚点位置排序，maxRootGap 分段、
  贪心成组。拒绝显式计数：宽度越界 / 跨根依赖（防组合环）/ 来源不可迁移（非 Direct 全覆盖 slice）
  / 相位不一致 / build 漂移。改写：叶子 MSB-first concat、内部 op 加宽、mux→masked-select、lane 根
  全部用途重定向到 sliceStatic、声明 slice Merged 到打包值位段、死锥扫除（保留仍带来源 slice 的
  锥内声明 op 作为活锚点）后 compact。新 op 继承组相位。
- A5 `grhsim.pack-bit-registers`（重写 `lib/grhsim/pass/pack_bit_registers.cpp`）：删除
  schedule/quiescenceProjection 硬依赖与"私有历史 state"判定（两者在当前 IR 形态都不存在，旧
  pass 实为 no-op）。候选判定全静态：1 位两态无符号、单条已知 init、唯一写者、refs==普通读+1、
  写 op 形状 enable/data/mask/events 且唯一参数 event_edges（posedge/negedge）；分组键 =
  (enable, mask, phase, [(event value, edge)])——同键即同拍更新（锁步论证），事件值同源使
  prevInit 推导（B2 ConeInitEval）天然一致，无需历史初值进键。显式拒绝计数
  `pack_bits_rejected_<reason>`（按写口计），无伙伴候选计 `pack_bits_singleton`。改写保持
  lane0=LSB、concat/replicate、init 按位拼装、读重定向 sliceStatic；成员声明 slice Merged 到
  打包字位段。TSV 格式不变。
- A6 接线（`scripts/wolvrix_xs_grhsim_ir.py`）：`CPU_SEMANTIC_PIPELINE` =
  canonicalize-compute → reg-to-mem → comb-pack → pack-bit-registers → simplify(scope=whole) →
  clone-shared-compute（保持在最后一次含 CSE 化简之后）；既有"后置化简 + 第二轮 mapping"段保持
  不变（仅移除其中已失效的旧 pack-bit-registers 调用）。HDLBits 与 reg-to-mem RTL 差分脚本经
  CPU_PIPELINE 自动继承。新增 `--comb-pack/--no-comb-pack`、`--comb-pack-report`（Makefile 旋钮
  `XS_WOLF_GRHSIM_IR_COMB_PACK{,_REPORT}`）；pass 循环逐个打印 info 诊断（命中计数入日志）。
  `--bitwise-predicates` 旋钮随独立调用移除而成为空操作（该子 pass 已并入 simplify 固定点）。
- 测试 `tests/grhsim/test_grhsim_whole_opt.cpp`（新目标 `grhsim-whole-opt-tests`，Makefile
  `test_grhsim_whole_opt`）：pack-bit 打包+四类拒绝+来源+init 拼装+差分；comb-pack 按位树打包
  /mux masked-select /跨根拒绝（lane_0 留 Direct 来源，lane_1-3 打包）/四态 mux 不成候选/参数
  校验；reg-to-mem 声明行来源重定位（tbl_0..3 与 mat_0_0..1_1 两族，行主序偏移断言）+ TSV
  shape 列；A 段全管线冒烟（canonicalize→reg-to-mem→comb-pack→pack-bit→simplify 后 verify、
  JSON 字节稳定往返、512 步解释器差分）。

**检查点证据**（均实跑）：

- `make build` 通过；`make test_grhsim_whole_opt` 全绿；`make test_grhsim_simplify`、
  `make test_grhsim_ir` 全绿；`make test_wolvrix` 54/57，恰为 3 项既有失败
  （transform-comb-lane-pack、transform-repcut、ingest-write-back-slice SEGFAULT），无新增失败。
- `make run_xs_bugcase_grhsim` 24/24（逐 case 日志含命中计数，如 CASE_003：reg-to-mem 合并 25
  表、states 434→259、comb-pack 4 组 33 lane、pack-bits 131 bit/5 字；CASE_014：comb-pack 17 组
  262 lane）；`run_all_hdlbits_grhsim_tests_report` 162/162 全绿；
  `test_grhsim_reg_to_mem_rtl` 8192 样本 PASS（新管线顺序）。
- XS 整核管线（`make xs_wolf_grhsim_ir`，无 emit）A 段实跑计数：reg-to-mem 7448 候选合并
  1945 表、states 291961→179592、ops 4684247→4023462、来源重定位 118374 条、声明族 1591、
  max_array_dims=1；comb-pack 74550 候选、打包 4152 组 53486 lane、显式拒绝 cross_root=559 /
  provenance=1800 / build=116；pack-bit-registers 打包 67290 bit / 3774 字（旧 pass 恒为 0），
  显式拒绝 target_type=94603 / no_reads=1802、singleton=8733；simplify(whole) 4 轮收敛。
  优化前后 checkpoint 经既有 store/roundtrip 字节稳定断言（流水线末尾）。
- 恢复数组不自动选择 memStore（store 分类属 M5d-4 的 A7）；reg-to-mem 高维仅落在命名/报告/
  来源记录，类型保持一维平坦。
- 附带发现（非本任务引入，不修）：`test_grhsim_reg_to_mem_generated` 在 wolvrix HEAD（466d1bd，
  全部 M5d 改动 stash 后）同样 ASan 失败（or_word64 init memset 越界），属既有问题。
- 文档：`docs/grhsim_ir/passes/comb-pack.md` 新增（匹配/拒绝/例子）；`passes/reg-to-mem.md` 补
  来源维护与声明族形状节；`passes/pack-bit-registers.md` 重写（新门禁、显式拒绝、无 schedule
  依赖）；`overview.md` §3.4.1 维护契约补 merge helper；`flows/cpu-st.md` 更新 A 段顺序与
  simplify 接线注记。

### M5d-4 优化后状态的语义存储分类（未开始，依赖 M5d-3）

- 范围：新增 `grhsim.select-state-stores`，按优化后的规模、连续性和更新代价确定 regLatchStore/memStore 归属及读写/提交契约；本阶段不分配最终字节布局。
- 交付：零碎状态以 next/current 和 publish 整块拷贝实现 NBA，大块连续状态通过 P_mem 处理。允许小数组进入 regLatchStore、恢复的大数组进入 memStore；语义 verifier/JSON 承载明确分类，规定消费端不得仅凭 TypeKind::Array 决定归属，并为 M5d-5 至 M5d-7 定义接口（首个消费者是 B5 split-phases 的 P_mem 写入职责判定）。
- 检查点：分类及 JSON/verify 覆盖旧值读取依赖、部分写、多写优先级和多轮更新的契约；生成布局和运行时 NBA 等价性分别在 M5d-6/M5d-7 接通后验证。不依赖后续 emit 才能验收分类接口。
- 文档：定义分类依据、提交时机和新增状态的增量分类规则，给出小数组与大块恢复数组的对照例子。

### M5d-5 第一轮分解与分区优化（未开始，依赖 M5d-4）

- 范围：覆盖 B1-B8——接通 B1-B5（classify-event-inputs、lower-edge-detect、extract-output-cones、migrate-timeslot-tasks，新增语义层 split-phases），随后 B6 分区化简、B7 边界感知克隆、B8 封板校验；从旧 cpu.st.split-phases 拆出阶段归属处理，形成 P_event/P_general/P_output 三个计算分区，并确定 P_mem 写入职责。
- 交付：保持事件/输出锥的自包含、边界接口及副作用归属；PrevEventStore 按事件检测时机更新，不默认经 NBA publish。time-slot 新增监测状态在局部 simplify 前增量分类，保持其监测/提交时机。
- 分区化简：分别调用 `simplify(scope=phase)`（B6），遵守共享状态需求并集；随后 B7 clone-shared-compute 按归位决议 1 改造为边界感知成本模型——与 build-general-nodes 共享锥吸收预测的 helper，只克隆能消除预测超节点边界的候选，只有边界消减收益成立时启用，未启用或零命中时记录原因与边界消减计数。不得复制 DPI、随机采样和有副作用的系统任务。B8 verify 后语义层封板，本阶段之后不再有任何语义改写。
- 检查点：三个分区独立 dump/verify，跨分区引用、状态归属、事件沿和 time-slot 生命周期定向测试通过；需要新 emit 的事件/DPI/随机采样/time-slot 运行差分在 M5d-7 接通后完成。此时尚未建立 General supernode 或 CPU mapping。
- 文档：记录语义分区与 CPU mapping 的新边界、锥复制规则、阶段接口及新历史状态处理。

### M5d-6 General supernode、最终 mapping 与旧实现清理（未开始，依赖 M5d-5）

- 范围：C 段第二轮分解与映射调度——由 build-general-nodes（C1）初始化一次最终 mapping，merge-general-supernodes（C2）形成超节点并按划分结果顺序确定超节点序号，随后 layout-named-stores（C3）、build-event-bitmaps（C4）、build-mem-write-plan（C5）、pack-general-functions（C6）、build-phase-schedule（C7）单向推进。
- 序号与函数打包解耦（归位决议 2）：超节点序号不再按“emit function 子序 → supernode 子序”派生，build-event-bitmaps 改用 C2 序号；pack-general-functions 从划分段移至 build-phase-schedule 之前，EmitFunction 只记录持有的超节点区间；layout-named-stores 的 stage 前置从 GeneralFunctions 降为 GeneralSupernodes。CpuMappingStage 枚举顺序与 verifyCpuPhases 逐级校验相应重排，兼容所需枚举数值保持稳定。
- 交付：仅在已 simplify 的 P_general 中形成活动度 supernode；保留事件域禁合、数据激活粘滞与同轮拓扑传播，显式保证 General 执行顺序和静态 fanout 一致，覆盖同 eval 输入变化与事件沿同时到达的风险。
- 布局与静态表：消费 M5d-4 的 store 分类，替换 layout/后端 verifier 中仅凭 TypeKind::Array 判断归属的逻辑（C3 零分类决策，只消费 A7 注解），生成具名字段/数组维度/来源映射、边界与局部缓冲；生成事件位图、fanout、mem 写优先级/读者表及六阶段执行计划，记录各 store 字节数和 publish 拷贝字节数。
- 旧 mapping 清理：移除 `cpu.st.split-phase`/`form-event-domains`/`build-compute-nodes`/`merge-compute-supernodes`/`pack-active-words`/`pack-emit-functions`/`layout-data`/`build-schedule` 的旧注册和实现；旧 `cpu.st.split-phases` 的语义职责由 M5d-5 接替，mapping 初始化由本阶段接续。
- 旧 schedule 消费者：处置 `grhsim.demonitor-redundant`/`demonitor-edge-completion`/`migrate-boundary-ops(-ec)`/`fuse-expr-chains`/`fold-residue`；有独立收益的语义能力需迁入前序优化层并证明适用性，依赖旧 mapping 的实现删除。随消费者退出删除孤儿化的 refreshCpuDataLayout、refreshCpuSchedule、computeDemonitorEdgeCompletionSelection，兼容所需 CpuMappingStage 枚举数值保留稳定。
- 检查点：最终图/布局/位图/读者表/fanout/schedule 交叉校验及 JSON 字节稳定往返通过，事件域和同轮传播定向回归通过。同步构建注册与相关测试，生产入口无旧 mapping 消费者；历史说明、兼容枚举和拒绝旧参数的测试不计作残留实现。
- 文档：同步 backend、flow 和 mapping pass 文档，明确一次最终 mapping 与三段式流水线结构；不恢复旧 shadow/pending/domain-arm 执行路线。

### M5d-7 多 TU 规划、emit 与并行构建（未开始，最终集成依赖 M5d-6）

- 可提前并行的范围：基于现有小模型开发 TU 划分、源文件清单和 Makefile 多源编译/链接框架（函数分块属 C6/M5d-6，不在此项）；此项优先推进，但框架通过不代表目标管线或整核已验收。
- 目标交付：新增 plan-translation-units，消费最终布局/调度；最终 verify 后由 emit-cpp 输出多个规模受控 TU。Input/Event/General/Mem/Publish/Output、初始化与静态表都受单函数/单 TU 规模约束，不保留其他巨大阶段或初始化函数。
- ABI 与数据移动：明确跨函数参数、局部值生命周期、写入优先级及静态表链接关系；runtime 宽值 helper 沿用指针与调用方缓冲，避免热路径大临时副本。公共头、runtime、DPI 声明与完整源文件清单保持一致，控制公共头体积，实测后决定 PCH。
- 检查点：小模型跨 TU 生成、Makefile 并行编译和链接及语义差分通过，完成 M5d-3 至 M5d-6 改写后的状态/NBA、事件、DPI/随机采样和 time-slot 定向运行差分；目标管线的完整 XS 模型生成规模受控，构建日志证明实际并行编译且链接完整。记录最大函数/TU 规模、头文件体积、并发数、耗时和峰值内存；CoreMark 运行验收归入 M5d-8。
- 文档：同步 emit、生成构建清单及 XS/difftest 接线，区分 C++ 编译并行与模拟器执行顺序。

### M5d-8 统一入口、回归与完整 XiangShan 验收（未开始，依赖 M5d-1 至 M5d-7）

- 入口统一：XS、HDLBits、xs-bugcase 和本地 benchmark 入口消费同一目标 pass 顺序；可随前序阶段逐步接线，最终核对不含“mapping -> 语义改写 -> mapping”。big-comb/xs-components 做入口适配与小规模验证，完整 benchmark 继续暂缓；不新增 openc910 GrhSIM 工作流。
- 定向与全量回归：先完成受影响 pass/IR/layout/emit 的定向验证，再复测 HDLBits 162/162、xs-bugcase 24/24 和 Makefile 全量测试。三项既有失败单独对照记录，要求无新增失败，不能将既有 52/55 写成全绿。
- 黄金差分：使用已有 161 例逐 eval 黄金及覆盖 manifest；DUT=105 使用独立 Verilator 参照补足覆盖，记录黄金来源、采样范围和命令，不将待验收模型自身输出作为黄金。运行既有 baseline 门禁并完成实际覆盖范围内的差分。
- 完整整核：M5d-7 完成多 TU 编译/链接后运行完整 XiangShan CoreMark，不设置周期截断，启用 NEMU difftest，以无 mismatch、`HIT GOOD TRAP` 和退出码 0 为验收。旧约 100k 周期快照仅用于截断对照和同负载测量，不能替代完整运行。
- 首个失败：沿用作者已确定的范围，先记录首个失败、命令、退出码、日志及复现证据，再讨论修复；当前仍保持暂停编译。
- 资源与性能：归档模型操作/状态/数组规模、store 及 publish 字节数、TU/公共头规模、构建耗时/峰值内存和运行性能；同负载、周期范围和环境下对照 M0，判断是否达到旧实现同一量级。存在瓶颈时先记录数据，再确定后续优化，不预设 M6 回填清单。
- 文档与提交收口：核对语义文档、overview/dialect/backend/flow/pass 文档及本计划一致，生产文档无失效机制；按需同步 AGENTS.md。按验收范围提交 wolvrix 与根仓库修改并同步子模块指针，说明中点名 `ptmp/grhsim_direct_mem_backup_20260930.diff` 提醒属主。此项替代旧 M5b-3/M5b-4 的独立收口任务。
