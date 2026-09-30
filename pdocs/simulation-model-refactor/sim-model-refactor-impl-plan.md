# GRHSIM IR 仿真模型重构 实施计划

## 0. 定位

- 语义基线：`pdocs/simulation-model-refactor/sim-model-refactor-plan.md`（commit 95a4456）。所有语义决策以该文档为准，本文档只管工程落地；落地过程中发现语义缝隙时，先回改语义文档并与作者确认，再改代码。
- 目标产物：新 CPU 后端生成的仿真类按六阶段模型（P_input/P_event/P_general/P_mem/P_publish/P_output）运行，正确性对黄金参照全绿，性能达到旧实现同一量级。
- 三条工程方针（作者指定）：
  1. **逐 pass 落地**：每个主要步骤都是独立 pass，中间结果全部落到 GrhSimModel（含 CpuBackendMapping）上，pass 间可 JSON dump 观察、`grhsim.verify` 逐 pass 校验；
  2. **直接替换**：不设新旧并存开关；旧版 grhsim ir 的 cpp emit 与 legacy 仿真一并删除，只留新实现；
  3. **可观测存储**：各 store 认真设计存储形态，具名、易调试，禁止"一个大数组不可观察"；变量名尽可能用 declaredSymbol 推演；头文件过大时用 PCH。

## 1. 总策略

- **pass 化流水线**：重构体现为 `flows/cpu-st.md` 中 pass 序列的整体重写。每个新 pass 输入/输出均为 GrhSimModel，命名沿用 `grhsim.*` / `cpu.st.*` 约定，pass 间挂 `grhsim.verify`；调试时可在任意 pass 后 dump JSON 检查中间形态。
- **直接替换，黄金参照兜底**：
  - M0 先用现实现抓取**黄金参照**（各测试逐 eval 输出 + 性能快照），长期保留在 `ptmp/`；
  - 正确性验证 = 新实现对黄金参照逐 eval 比对 + hdlbits 流程的 Verilator 参照；
  - 删除清单（M5 执行，依赖允许可提前）：`wolvrix/lib/emit/grhsim_cpp.cpp` 及对应头文件（legacy 仿真）、`wolvrix/lib/grhsim/backend/cpu_emit.cpp`（旧 emit，含 shadow/pending/domain-arm/边沿历史批处理等专属机制）、`cpu_shape_share.cpp`/`cpu_block_share.cpp`（已关闭的文本共享）；`grhsim_runtime.{hpp,cpp}` 保留为新 emit 的 runtime 头生成器；`cpu_partition/cpu_layout/cpu_schedule` 为改造而非删除；system_verilog.cpp 等 hdlbits 流程设施**保留**。
- **先正确后优化**：第一版严格按语义文档做最简形态（全量 memcpy、无跳过机制），差分全绿后再逐项回填优化，每次回填回归差分。
- **构建/测试一律经 Makefile 目标**（AGENTS.md 约束），缺目标先补目标；日志与大 artifact 落 `ptmp/`。
- **文档同步**：每个里程碑收尾同步 `wolvrix/docs/grhsim_ir/`（overview.md、dialects/core.md、backends/cpu.md、flows/cpu-st.md 重写 pass 序列）；行为变化涉及 AGENTS.md 所述流程时一并更新。

## 2. 存储形态与可观测性设计（方针 3 落细）

总原则：**每个 store 生成为具名结构体**，仿真类成员即 `regLatchStore`/`regLatchStoreNext`/`memStore`/`boundaryValueStore`/`prevEventStore` 等具名实例；调试器中可直接按信号名观察，无需查偏移表。

- **命名推演**：字段名首选 declaredSymbol（清洗规则：层次分隔符与非法字符→下划线；全图唯一化——冲突时确定性追加 state/value id 后缀）；无 declaredSymbol 的合成信号回退为"来源 op 类别前缀 + id"的可读名。清洗与唯一化逻辑集中在 layout pass 一处实现，emit 只消费。
- **RegLatchStore / regLatchStoreNext**：每 reg/latch 一个具名字段；2-state 小位宽用原生整数类型，宽值/4-state 用具名定长数组成员；被 `pack-bit-registers` 打包的位寄存器：具名打包字字段 + 成员名→位区间的注释表（后续可演进为访问器方法）。
- **MemStore**：每 mem 一个具名数组字段（cell 类型按位宽选型）。
- **BoundaryValueStore**：输入字段按端口名；跨界值按来源信号 declaredSymbol；mem 写 data/addr 槽按写 op 命名（如 `<mem>__w<idx>__data`）。
- **prevEventStore / eventActStore**：按 (event,edge) 聚类命名（`<信号名>__<posedge|negedge|both>`）；act 若保留位图/字节数组形态，生成常量名表（`static const char* const`）或 enum 供调试索引。
- **flag 数组**（eventActiveFlag/dataActiveFlag/Next、timeslotTriggerFlag）：热路径保留紧凑字节数组，配套生成超节点/op→名字的常量表，调试时可按索引反查。
- **调试设施**：生成 `dumpState()`（宏开关，默认关），按名打印各 store 字段——差分定位首个分歧 eval 时用；代价为一份打印代码，不需要时可裁剪。
- **PCH**：store 定义集中于一个生成头文件，被全部 task TU 包含；字段数超阈值（默认 5 万字段，实测调整）或 TU 编译时间超阈值时启用 PCH，接线进 sim 构建的 Makefile 目标。

## 3. 现状代码地图（改动落点）

| 模块 | 文件 | 处置 |
| --- | --- | --- |
| dialect | `wolvrix/lib/grhsim/dialect/core.cpp`（+include 镜像） | 加 `core.event.edgeDet` |
| IR/验证 | `wolvrix/lib/grhsim/ir/model.hpp`、`verifier.cpp` | model 增加 phase 区域/op 归属与新 store/表结构；verifier 加结构断言 |
| lowering | `wolvrix/lib/grhsim/convert/grh_to_grhsim.cpp` | 摘除 `:621-649` 的 `__event_*` 历史状态生成，改为产出待新 pass 消费的原始事件标注 |
| 语义 pass | `wolvrix/lib/grhsim/pass/` | 新增锥提取/迁移 pass；`demonitor-*`、`clone-shared-compute` 适配 |
| 后端分区 | `backend/cpu.cpp`、`cpu_partition.cpp` | `split-phase`→四类；合并框架加事件域禁止条件；`form-event-domains` 保留复用 |
| 布局/调度 | `cpu_layout.cpp`、`cpu_schedule.cpp` | 具名 store 布局；新增静态表 pass |
| 旧 emit | `backend/cpu_emit.cpp`、`cpu_shape_share.cpp`、`cpu_block_share.cpp` | **删除**，新 emit 另起文件 |
| legacy 仿真 | `lib/emit/grhsim_cpp.cpp`（+头文件） | **删除**；`grhsim_runtime.{hpp,cpp}` 由新 emit 使用，保留 |
| checkpoint | `wolvrix/lib/grhsim/io/json.cpp` | `wolvrix.grhsim.v2`，覆盖新 store/flag/触发位 |
| 保留 | `lib/emit/system_verilog.cpp`、hdlbits 流程 | 不动 |

## 4. 语义→pass→代码 改动地图

pass 命名为新管线草案，实现时可微调；每个 pass 后均可 dump + verify。

| 语义条款 | pass / 落点 |
| --- | --- |
| edgeDet op（edge 枚举含 both；act/prev 下标 attribute） | dialect/core.cpp + verifier + `docs/grhsim_ir/dialects/core.md` |
| IR 承载 phase 区域（P_event/P_general/P_mem/P_output op 归属） | model.hpp + verifier + io/json |
| 纯事件输入判定 | `grhsim.classify-event-inputs`（convert 内分析独立成 pass） |
| 事件锥复制+edgeDet 挂接+(event,edge) 去重+prev init；摘除原 event 操作数、删纯事件 op、保留双用途数据通路 | `grhsim.lower-edge-detect` |
| 输出锥复制+剥离 | `grhsim.extract-output-cones` |
| $monitor/$strobe 迁移（历史判定 / timeslotTriggerFlag） | `grhsim.migrate-timeslot-tasks` |
| 四类 split；write op 合入；事件域约束（完全相等+传递闭包） | `cpu.st.split-phases`（替换 split-phase）+ `merge-compute-supernodes` 改造（复用 `form-event-domains` 的 key） |
| eventActiveFlag 倒追位图（含 P_mem sink） | `cpu.st.build-event-bitmaps` |
| mem 写优先级、读者表（静态精确/动态保守）、event-free 写清单 | `cpu.st.build-mem-write-plan` |
| 具名 store 布局、命名推演 | `cpu.st.layout-data` 改造 |
| 静态 fanout 表（input/supernode/state） | `cpu_schedule.cpp` 改造 |
| 六阶段 eval、写 op 变化检测、P_publish、init 形态 | 新 emit（M5） |
| checkpoint 新字段 | `io/json.cpp` v2 |

## 5. 里程碑

### M0 黄金基线与差分设施（不动生产代码）

- 验证集：`testcase/hdlbits` 全套、`testcase/openc910`、`testcase/xiangshan`（coremark）、`testcase/xs-bugcase`；现实现逐 eval 输出落黄金文件，性能快照存 `ptmp/sim-refactor-baseline/`。
- 差分 harness：新仿真类对黄金文件逐 eval 比对全部输出（可抽样内部 reg）；hdlbits 流程确认 Verilator 参照可用；做成 Makefile 目标 + ctest。
- 完成标志：黄金文件落盘且覆盖率检查通过（每个测试的每个输出端口、每个 eval 都有记录）；"旧 vs 黄金"自校验通过。

### M1 IR 承载：dialect / model / verifier / io

- `core.event.edgeDet` op（语义文档定稿形态）；model.hpp 增加 phase 区域/op 归属表达与新 store、静态表结构（空壳，后续 pass 填充）。
- verifier 结构断言框架（供 M2/M3 启用：general 图无 event 操作数、锥自包含、edgeDet 去重正确等）。
- JSON v2 序列化框架（roundtrip 空壳结构）。
- 完成标志：相关 ctest 通过；core.md 增补 edgeDet 一节（含操作数/参数/产物定义与小例子）。

### M2 lowering pass 系列

依次实现四个独立 pass，每个配"verify + JSON dump 结构单测"：

1. `grhsim.classify-event-inputs`：纯事件输入判定（只用作 event 操作数；rst 类因进 en 合成路径判为数据使用者）；
2. `grhsim.lower-edge-detect`：事件锥提取复制、edgeDet 挂接、(event,edge) 去重与 act/prev 下标分配、prev init=event init 值、原 op 事件操作数摘除、纯事件 op 删除、双用途逻辑保留数据通路份；
3. `grhsim.extract-output-cones`：输出锥复制剥离，general 侧纯输出逻辑删除；
4. `grhsim.migrate-timeslot-tasks`：$monitor/$strobe 分类迁移（无事件→P_output+历史值判定；带事件→P_output+timeslotTriggerFlag 占位分配；always_comb $display 不动）。

- 完成标志：四个 pass 的结构单测全绿；既有语义 pass（`clone-shared-compute` 等）在新结构上回归通过；convert 中 `__event_*` 生成代码删除。

### M3 划分 pass 改造

- `cpu.st.split-phases`（替换 `split-phase`）：op 归入四 phase（P_event 锥+edgeDet / P_general / P_mem 四种 mem 写 / P_output 锥+time-slot 任务）。
- 合并框架沿用（node→supernode、coarsen、DP 分段、规模上限），新增：①reg/latch write op 可合并；②事件域约束为合并禁止条件——候选 op 扇出传递闭包内所有带事件 op 的 canonical event key 完全相等；纯组合/latch-only 豁免。
- 完成标志：划分单测四组用例（同域可合、子集域禁合、跨域传递禁合、纯组合豁免）全绿。

### M4 布局 / 调度 pass

- `cpu.st.layout-data` 改造：按第 2 节生成具名 store 布局（含命名推演、pack 字注释表、超阈值 PCH 判定）。
- `cpu.st.build-event-bitmaps`：(event,edge)→受影响超节点位图（P_general+P_mem sink 倒追传递闭包）。
- `cpu.st.build-mem-write-plan`：P_mem 写 op 优先级序、读者表（静态地址精确/动态保守）、event-free 写清单。
- `cpu_schedule.cpp` 改造：inputFanout（区分纯事件输入）、supernodeFanout、stateFanout（publish 置位用）。
- 完成标志：静态表单测 + verifier 交叉检查（位图与图一致、stateFanout 覆盖全部读者、命名唯一性）。

### M5 新 emit + 旧代码删除

- 新 emit（新源文件）：六阶段 eval 骨架（P_input diff / P_event 锥+edgeDet+位图重建 / P_general 双门控分派、点火清位、同轮后继激活、写 op next 合并+current 变化检测 / P_mem 优先级原地写+cell 变化检测+读者激活 / P_publish 并入+memcpy+fixedPoint+MAX_ROUND bail / P_output 输出锥+time-slot 任务）；init（全脏、next=current、prev=event init）；`dumpState()` 调试设施；PCH 接线。
- 删除：第 3 节删除清单全部落地，构建系统同步摘除；`docs/grhsim_ir/backends/cpu.md`、`flows/cpu-st.md` 重写为新模型。
- 差分推进顺序：hdlbits → openc910 → xiangshan → xs-bugcase，逐级全绿才进下一级；分歧定位用 `dumpState()` 对黄金文件逐 eval 比对。
- 完成标志：差分全绿 + 删除清单落地 + 文档重写完成。

### M6 性能对齐与优化回填

- 基准对照：`scripts/benchmark_grhsim_ir.py` + xiangshan coremark 对 M0 快照，指标对齐现有 NO 档案口径。
- 回填候选（逐项回填、逐项回归）：整店无写跳过/分块 dirty 拷贝；edgeDet 批量检测与向量化；无输入变化 eval 快路径；direct commit 等价物；宽值 helper 沿用 legacy 性能路线（AGENTS.md 约束：指针+调用方缓冲）。
- 完成标志：关键基准不低于旧实现同一量级；结论与数据归档新 NO 文档。

## 6. 测试策略

- 单元（`wolvrix/tests/grhsim/` 按模块放，ctest 注册）：edgeDet 校验、各新 pass 结构、划分禁止条件、位图/静态表正确性、命名唯一化。
- 语义定向用例（每条激活代数一条）：计数器自环收敛、A→B 残留下一沿采样、多次异步复位、clk0/clk1 双域不吞标志、glitch 时钟多边沿、latch 环收敛、event-free mem 写收敛、$monitor 每 eval 至多一报、上电无伪边沿。
- 集成差分：M0 黄金文件逐级比对；hdlbits 走 Verilator 参照双保险。
- 性能：M0/M6 快照对比，记录落 `ptmp/`。

## 7. 风险与对策

- **激活代数实现偏差**（最可能出 bug 处）：语义定向用例在 M5 前写完；verifier 结构断言随 pass 启用；`dumpState()` + 黄金文件逐 eval 定位首个分歧。
- **失去活参照系**（旧代码删除后无法现跑旧实现对比）：M0 黄金覆盖率列为门禁；黄金文件与基线性能快照在 `ptmp/` 长期保留；极端情况用 git 历史重建旧实现出参考。
- **性能回退**：M6 回填清单按预期收益排序；全量 memcpy 在 Xiangshan 规模的开销在 M5 完成后第一时间实测，超阈值则把"整店无写跳过"提前（不改语义）。
- **checkpoint 兼容**：首版 `wolvrix.grhsim.v2` 不兼容升级；需 v1 兼容另立任务。
- **范围蔓延**：不含多线程后端、P_output 门控跳过、mem 地址区间精细化；确有需要另立 NO 文档。

## 8. 开放项（实现中取默认值，影响语义才回报）

- 命名清洗细则：层次分隔替换字符、关键字避让、超长名截断策略；默认"原名清洗 + 冲突追加 id 后缀"。
- PCH 阈值：默认字段数 5 万或单 TU 编译超 30s，实测调整。
- eventActiveFlag 存储形态：默认每 act bit 一个超节点位图（P_event 里 OR 重建）。
- P_event 是否分任务：默认单任务顺序执行（锥小）；profiling 后再议拆分。

## 9. 进展记录（2026-09-30）

代码在 `wolvrix` 子模块（branch `grh/grhsim-ir`），脚本/Makefile 在根仓库
（branch `grh/grhsim-ir-gap-driven`）。本次按作者要求先提交当前检查点，
同步前移根仓库的子模块指针；M5c 全绿后再做最终验收提交。

### 已完成

- **M0**：黄金基线设施落成——161/162 hdlbits DUT 黄金轨迹 + MANIFEST + XS
  coremark 快照（`ptmp/sim-refactor-baseline/`，端点 instrCnt=240349 /
  cycleCnt=99996 / pc=0x80000c0c）；`make check_sim_refactor_baseline` 门禁可用。
  openc910 无任何 grhsim 流程（在案），差分链不含它；dut_105 在 M0 采集时因
  used-bits dangling value 失败，故旧黄金集不含该例；M5b-1 已修复并通过
  GrhSIM testbench，全量 162 例均可运行，黄金轨迹仍待补录。
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

### 进行中：M5（已拆 M5a/M5b/M5c 执行）

- 规格已写定：`ptmp/spec-m5.md`（生成代码契约、六阶段 eval 骨架、管线切换 12
  pass 序列、删除清单及其消费方盘点、差分推进门禁、xs-bugcase IR 接线方案）。
- **M5a（新 emit 实现）：已完成**（本次检查点提交）。因"一步到位"被卡一上午，
  拆成 5 片逐片端到端验证后落地：
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
    契约桩；剩余占位仅 `taskCpp`（多 TU）与 `core.compute.expr`（新管线不产生）；
  - M5a-5 硬化（修 M3/M4 三缺陷，定向用例全部去掉 `--max-op-in-compute-supernode 1`
    绕行）：**D1** merge rule 2 字面允许无事件 sink 并入事件域→event-free 成员
    被双门控丢执行，修法=EventDomainInfo 加 `unboundFree` 禁合第三条
    （cpu_partition.cpp）+ verifier 锁步；**D2** sink 边门控 × 电平敏感 mem 读者，
    修法=emit 侧 `eventGated_` 按"超节点含≥1 个带 event_acts 成员"计算（纯
    event-free 超节点 dataActiveFlag 单门控，依据 plan §112/§115；位图仍驱动
    eventActiveFlag 重建）；**D3** 整表 state.read 读者缺席 memWritePlan.readers，
    修法=build-mem-write-plan 补收（恒 dynamic 读者）。pass 文档同步。
    **遗留风险**：General 分枝超节点序=拓扑序无显式保证（同 eval 输入+沿到达时
    boundary fanout 落 Next 可能滞后一个沿）——M5c 差分若出沿采样偏差先查这里，
    修法备选=build-phase-schedule 对 General 分枝拓扑排序。
  - 测试：`test_cpu_phase_emit.cpp`（1291 行）21 子项全绿（生成模型经系统
    clang++ -O2+UBSan 编译驱动比对）；phases/stores/event_lowering/mapping/
    schedule 套件无回归。
- **M5b（管线切换+删除+文档）**：拆为四个里程碑。M5b-1 管线切换与主要
  回归已通过；big-comb/xs-components 本地 benchmark 仍待实测：

  **M5b-1 管线切换与旧 emit/legacy 删除（主要验证已通过）**
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
    旧 emitter API/源文件在生产代码和构建注册中无引用；历史文档与注释的旧路径文字
    留待 M5b-3 文档收口。big-comb/xs-components 新 IR 本地入口已接线，实际生成与
    benchmark 验证按当前优先级暂缓。修复 CPU `sliceArray` C++ 括号生成、`$random`
    跨 output-cone clone 的单次采样，以及 1-bit DPI `svBit` ABI；新增对应 emit 回归。
    xs-bugcase 汇总 `make run_xs_bugcase_grhsim` 24/24 通过；2026-10-01 在
    CASE_001..003 的运行入口加入旧 coverage 文件清理后复测仍为 24/24，结果见
    `ptmp/xs-bugcase-grhsim/summary.txt`（各例日志位于同目录）。原 SV 路径 CASE_002
    仍有独立已知差异（cycle 3：`exit ref=1 wolf=0`），不影响 GrhSIM 对 Verilator
    的 120-cycle 对拍（JTAG DPI 59 次、RAM read 60 次、write 40 次）。
  - 清理：新 `cpu.st.emit-cpp` 拒绝旧 emit 选项；其注册测试确认旧选项已移除。

  **M5b-2 旧 mapping pass 实现删除（未开始）**
  - 范围：`cpu.st.split-phase`/`form-event-domains`/`build-compute-nodes`/
    `merge-compute-supernodes`/`pack-active-words`/`pack-emit-functions`/
    `layout-data`/`build-schedule` 的注册与实现；随之孤儿化的
    `refreshCpuDataLayout`/`refreshCpuSchedule`/`computeDemonitorEdgeCompletionSelection`；
    针对旧结构的语义/调度 pass（`grhsim.demonitor-redundant`/
    `demonitor-edge-completion`/`migrate-boundary-ops(-ec)`/`fuse-expr-chains`/
    `fold-residue`）逐个处置（删除或保留需论证）；
    `CpuMappingStage` 旧档位枚举值保留（JSON 兼容），处理代码删除。
  - 完成标志：pass 注册表只剩新管线 + 保留语义 pass；`make build` 与全部
    ctest 绿；被删 pass 名全仓 grep 无引用。

  **M5b-3 文档重写收口（部分已开始，完成度待核）**
  - 范围：`docs/grhsim_ir/backends/cpu.md`、`flows/cpu-st.md` 按新六阶段模型
    重写完成（已开始的改动核对补全）；`dialects/core.md` 复核；
    impl plan §3 删除清单已修订（grhsim_runtime 保留）；
    AGENTS.md 若涉流程变化同步。
  - 完成标志：两篇文档完整反映新管线/新 emit，无旧机制（shadow/pending/
    domain-arm/激活字）残留描述。

  **M5b-4 最终验收提交（依赖 M5c 全绿）**
  - 本次先按作者要求提交当前检查点（HDLBits 子模块默认 IR、wolvrix 新 emit+
    删除、根仓库脚本/Makefile/文档与子模块指针）；M5c 全绿后再提交后续修复与验收
    结果。提交说明点名 GRHSIM_DIRECT_MEM 备份位置提醒属主。

- **M5c（差分推进）**：xs-bugcase 24 例 GrhSIM 双驱动已全绿；hdlbits 黄金集与 XS
  coremark 的后续差分仍待推进。

### 环境注意事项（持续有效）

- ~~cpu_emit.cpp/test_cpu_emit.cpp 他人未提交改动~~：已随 M5b-1 删除，改动备份在
  `ptmp/grhsim_direct_mem_backup_20260930.diff`（903 行 diff），**最终报告与提交
  说明里必须点名提醒属主**。
- `make test_wolvrix` 全量有 3 个既有失败（transform-comb-lane-pack、
  transform-repcut、ingest-write-back-slice SEGFAULT），与本重构无关，不修。
- `scripts/grhsim_unpaired_registers.py` 是他人的未跟踪文件，不动。
- `testcase/hdlbits` 子模块 Makefile 的 `GRHSIM_BACKEND ?= legacy→ir` 已改（实质改动，
  提交时与子模块指针一起处理）。
