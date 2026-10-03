# GRHSIM IR 仿真模型重构实施计划 v2（六阶段架构调整版）

日期：2026-10-03
状态：实施中（V2-M1..V2-M4 已完成 2026-10-03）
上游文档：`sim-model-refactor-plan-v2.md`（架构基准）、`pdocs/NO00029-grhsim-ir-icg-activation-deadlock-20261003.md`（旧双重门失效的原理分析）

## 0. 目标与定位

从当前代码基线（v1 计划 M5d-1..M5d-7 完成、M5d-8 除"首个失败修复与完整 CoreMark"外
全部完成）出发，按 v2 架构调整六阶段调度与划分，**最终跑通完整 XiangShan CoreMark
（不设周期截断）+ NEMU difftest（无 mismatch、`HIT GOOD TRAP`、退出码 0）**。

v2 三条核心决策（2026-10-03 作者决策，见 plan-v2.md）：

1. 保留六阶段框架，全面移除 `eventActiveFlag`：非 sink 超节点以 `dataActiveFlag`
   点火（数据通路 + P_event 少量静态映射）；sink 超节点带事件的以 `eventActStore`
   组合门控点火、无事件的走逃逸机制（每个 round 无条件激活）。
2. 划分按 sink / 非 sink 分类：非 sink op（有返回值，含带事件非 sink op）走现有
   合并框架；sink op（无返回值的写类 op）按事件签名（canonical event key，含边沿
   方向，空签名自成一类）聚类成 sink 超节点，**不与非 sink 超节点合并**。
3. 三条边界：P_event 经静态映射激活少量非 sink 超节点；非 sink 超节点不向 sink
   超节点传递 dataActiveFlag；sink 超节点内部不再重复事件判断（只查 en、地址等
   逻辑）。P_mem 写簇共享同一套签名聚类与两级点火规则。

## 1. 当前基线与可复用件

**已完成且直接复用**：

- A 段（GRH transforms：latch-transparent-read、hier-flatten、comb-loop-elim、
  simplify、memory-init-check）与 B 段（grhsim lowering：classify-event-inputs、
  lower-edge-detect、extract-output-cones、migrate-timeslot-tasks、
  select-state-stores、split-phases、simplify）——v2 不涉及，保持不动。
- C3 七具名 store 布局（regLatch/regLatchNext/mem/boundary/prevEvent/eventAct/
  timeslot）、C5 mem 写计划、C6 函数打包、C8 TU 规划与多 TU emit 机制、
  FST 波形基础设施（`--waveform declared-symbols`）、`tools/fst_tools/fst_diff`。
- 验证资产：xs-bugcase CASE_025（latch-ICG 死锁最小复现，当前唯一失败项）、
  黄金差分 161 例、HDLBits 162、xs-bugcase 24、test_wolvrix 57、DUT=105 双参照。
- 事件签名素材：`readCpuPhaseEventActs`（`include/grhsim/backend/cpu_phase_common.hpp`）
  已提供排重排序的 event_acts 读取，canonical event key 直接由此构造。

**需要替换的机制**：

- `eventGated_` 分类与双重门调用点（`cpu_phase_emit.cpp:411-428` 及生成的
  `if(eventActiveFlag[i]&&dataActiveFlag[i])` 调用点）。
- C4 `cpu.st.build-event-bitmaps`（`cpu_schedule.cpp`）的 sink 向事件位图
  （eventActiveFlag 重建用途）。
- activeStore 三字段（eventActive/dataActive/dataNext）中的 eventActive。
- 超节点内逐 op `eventActStore` guard（sink 超节点部分，边界③）。

## 2. 里程碑总览

| 里程碑 | 内容 | 验收 |
|---|---|---|
| V2-M1 ✅(2026-10-03) | sink/非 sink 分类与事件签名聚类（C1/C2 划分改造） | 映射校验新增分类不变式；单测含 ICG 形状的划分形态 |
| V2-M2 ✅(2026-10-03) | 调度与布局改造（去 eventActiveFlag、fanout 收窄、P_event 非 sink 映射、逃逸类） | 调度/layout 校验通过；单测 |
| V2-M3 ✅(2026-10-03) | emit 三类调用点与体内 guard 规则 | **CASE_025 转绿**；emit 单测编译运行 |
| V2-M4 ✅(2026-10-03) | 小回归全绿（test_wolvrix、HDLBits、xs-bugcase、黄金差分） | 57 项无新增失败、162/162、25/25、161/161 |
| V2-M5 | XiangShan 整核复测与完整 CoreMark | emit/编译/链接通过；完整 CoreMark + NEMU difftest 退出码 0 |
| V2-M6 | 文档收口与提交 | 文档一致；wolvrix 与根仓库提交 |

依赖链：`V2-M1 → V2-M2 → V2-M3 → V2-M4 → V2-M5 → V2-M6`。M3 是功能转折点
（CASE_025 转绿），M5 是最终验收。

## 3. V2-M1 sink/非 sink 分类与事件签名聚类（C1/C2 划分改造）

### 目标

`P_general` 的超节点集合分两类产出：非 sink 超节点（走现有合并框架）与 sink 超
节点（按事件签名聚类，不参与合并）；序保证"非 sink 先于 sink"（拓扑）。

### 范围（文件级）

- `wolvrix/lib/grhsim/backend/cpu_partition.cpp`（`cpu.st.build-general-nodes`、
  `cpu.st.merge-general-supernodes`）：
  1. op 分类：`results` 为空者为 sink 候选（reg/latch/mem 写、无返回值的 DPI/
     系统调用），其余为非 sink（含带事件且有返回值的 op）。
  2. sink op 从 General 节点划分中剥离，不参与 coarsen/合并；按
     `readCpuPhaseEventActs` 的集合构造 canonical event key（空集合单列），同
     key 聚为一个 sink 超节点；空签名的 sink（数据门控 latch 写等）归入逃逸类。
  3. 非 sink op 继续走现有 node→supernode 合并框架（单消费锥吸收、coarsen、
     DP 分段、规模上限），产出非 sink 超节点。
  4. 序号分配：非 sink 超节点在前（保持 C2 拓扑序），sink 超节点按签名稳定
     排序追加在后；sink 超节点的 boundary 生产者序号必须更小（注册为映射
     校验不变式）。
- `wolvrix/include/grhsim/ir/model.hpp`：`CpuPartitionAttrs` 增加超节点类别
  （nonSink / sinkEscape / sinkEvent）与 sink 事件签名（act 集合，sinkEvent 类
  必填）字段；checkpoint 读写同步（`wolvrix/lib/grhsim/io/json.cpp`，enum 值追加
  不改序）。
- `wolvrix/lib/grhsim/backend/cpu.cpp`（`verifyCpuMapping`）：新增分类不变式——
  sink 超节点只含 sink op 且同签名；sink 不与非 sink 合并；sink 的 boundary 生产
  者序号小于 sink。

### 设计要点

- 删除旧"事件域约束"的合并禁止检查（由构造保证同域），合并框架本身不改动。
- latch 写（数据条件门控、无事件操作数）天然落入逃逸类；ClockGate 的 EN 写即
  典型成员（NO00029 的环在此被构造性拆除）。

### 验收

- 新增/改写单测（`wolvrix/tests/grhsim/test_cpu_stores.cpp` 或新文件）：小夹具
  验证分类（reg 写入簇、latch 写逃逸、事件 DPI 有返回值入非 sink）、签名聚类
  （同 key 一簇、空 key 逃逸类）、拓扑序（sink 在最后）。
- 一个含 ClockGate latch ICG 形状的小模型（CASE_025 RTL 同构）通过划分并得到
  预期形态：rcg_E 生产者在非 sink 超节点、EN 写在逃逸 sink 簇、宏寄存器写在
  事件签名簇。
- `make build && make test_wolvrix` 中 mapping 相关用例按新校验通过（允许本里
  程碑内暂时改写或标注后续 emit 里程碑修复的失败用例，须逐条记录）。

### 完成记录（2026-10-03）

**实现**（与计划的两处细化偏差，均属简化）：

- `cpu_partition.cpp`：C1 将 General op 按 `results` 是否为空分两类——sink op
  不进入节点形成，各自锚定单例 Node 附在非 sink 节点之后（op-id 序）；C2 非
  sink 节点走原 coarsen+DP 框架（**合并时事件域禁止检查已删除**，
  EventDomainInfo 机制整体移除），sink 节点按 `readEventActs` 签名经
  `std::map` 聚类（空签名→SinkEscape，非空→SinkEvent），分支孩子序 = 非 sink
  超节点（框架拓扑序）→ sink 超节点（签名字典序，逃逸类最前）。
- `model.hpp`：`CpuSupernodeCategory { NonSink, SinkEscape, SinkEvent }` +
  `CpuPartitionAttrs::supernodeCategory`（GeneralSupernodes 起必填）。**偏差 1**：
  sink 事件签名不设独立字段，直接复用 `attrs.eventActs`（sink 超节点上签名即
  成员 acts 的全等集合，与"eventActs = 成员 acts 并集"不变式天然一致）。
- `cpu.cpp` 校验器新增分类不变式：类别标注恰好覆盖 General 超节点；sink 超节点
  只含无返回值 op（SinkEvent 全等签名、SinkEscape 无事件 op）、非 sink 超节点
  只含有返回值 op；非 sink 超节点在分支序中先于 sink 超节点；sink 操作数的生产
  者必须位于序号更小的超节点。旧事件域约束校验（uniform/influence/unboundFree）
  同步删除；`eventActs == 成员 acts 并集`保留。
- `json.cpp` checkpoint：attr tail 追加标量 category（与 supernodeRange 数组互
  斥——emit function 有 range、supernode 有 category），读侧经新增的
  `StreamReader::arrayStarts()` peek 区分。**偏差 2（checkpoint 兼容）**：pre-v2
  的 GeneralSupernodes+ checkpoint 缺 category，载入后按新校验明确报错拒绝
  （v2 划分语义已变，旧 mapping 不可复用；schema 仍为 `cpu.st.v1`，与 M5d-6 移除
  legacy checkpoint 的先例一致）。
- `general_boundaries.cpp/.hpp`（B7 clone-shared-compute 消费的 C1 镜像）：同步
  新规则——op 集只含非 sink op，sink op 各得单例 node，使预测 boundary 与 C1
  逐值一致（否则 B7 克隆决策基于过时边界）。

**测试改写/标注清单**（逐条记录，符合验收第 3 条）：

- `test_cpu_phases.cpp`：f1（同签名写入聚一簇 + 锥入非 sink）、f2（子集签名分
  簇）、f3（共享锥留非 sink 框架，删 event_domain_blocked 断言）、f4（组合链自
  由合并）、f5（regWrite→SinkEvent 独簇、latchWrite→SinkEscape 独簇）、f6（类
  别标注存在性）、f9（state.read 锥入非 sink 框架）、f10（regLatch memWrite→
  SinkEvent 独簇）按新形状改写；f7 腐蚀用例 (b) 由"rule-2 域违反"改为"非 sink
  节点混入 sink 超节点"，新增 (f) 缺类别标注、(g) 类别篡改为 NonSink 两条；
  **新增 f12 `latchIcgShapeTest`**（ICG 形状验收：rcg_E 生产者在非 sink 超节
  点、EN 写单独成 SinkEscape 簇、两个宏寄存器写同簇 SinkEvent、sink 序在最后、
  roundTrip + 函数打包通过）。
- `test_cpu_stores.cpp`：layout boundary 字段 15→25（sink 操作数天然跨界，
  断言同步并新增 5 个具名槽）；mem plan 两个 event-free mem 读合并为同一非
  sink 超节点（断言反转并注明 staticRow 区分仍有效）；schedule 的 shnv fanout
  期望由 {w0,w1 超节点} 收窄为 {w0 超节点}（x1g 与 shnv 同超节点，注明 V2-M2
  fanout 收窄后该条目将消失）；**`memSinkBitmapTest` 标注停用**（钉住的
  "sink 向事件位图"机制正是 V2-M2 替换对象，`[[maybe_unused]]` + main() 注
  释，M2 按新语义重写）。
- `test_cpu_phase_emit.cpp`：**`dpiSmokeTest`（两个 TU 变体）标注停用**——
  event-free DPI 调用与 posedge-gated 调用并入同一非 sink 超节点后，旧
  `eventGated_` 双重门压制 event-free 成员发布（o 恒陈旧），归 V2-M3 的新点
  火规则修复；`perfCountersTest` compute batch 期望 4→8（latch 写独立成
  escape sink 批次，计数语义随划分粒度自然变化，功能正确）。
- `test_grhsim_split_phases.cpp`：无需改写（库镜像对齐后预测与实际逐值一致）。

**验证结果**：

- `make build` 通过；`make test_wolvrix` 54/57，三个失败
  （transform-comb-lane-pack、transform-repcut、ingest-write-back-slice）为
  基线已知失败，与本轮改动模块（grhsim 后端）无关。
- mapping 相关套件全绿：grhsim-cpu-phases（f1-f12）、grhsim-cpu-stores、
  grhsim-split-phases、grhsim-cpu-phase-emit（31 个 runtime case，2 个
  dpi_smoke 变体按上条标注停用）。
- **xs-bugcase 25/25 全过——CASE_025（latch-ICG 死锁最小复现）提前转绿**：
  EN 写落入逃逸类（无事件签名 → 不受旧 `eventGated_` 双重门约束，纯数据
  驱动点火），NO00029 的循环激活死锁在构造上被拆除，比计划的 M3 转折点
  提前两个里程碑。XS 全核修复仍以 V2-M5 验收为准。
- HDLBits 162/162 全过；黄金差分 161/161 全过。

**后续里程碑关注项**：

- V2-M2：重写 `cpu.st.build-event-bitmaps` 为"边→非 sink 超节点"静态映射并
  恢复重写 `memSinkBitmapTest`；fanout 收窄后 `phaseScheduleTest` 的 shnv 断言
  需再次更新（条目消失）。
- V2-M3：恢复 `dpiSmokeTest`；注意"无事件副作用 sink（如数据条件 $display）
  落入逃逸类后每 round 点火"的语义需在 emit 侧以 en 自查保证可观测行为不变
  （写类 op 有变化检测兜底，纯副作用 op 依赖 en 门控）。
- 非 sink 超节点内的带事件 op（如事件触发 DPI 返回值）在 M3 前仍受旧双重门
  压制——M1 已验证该形态普遍存在（dpi_smoke），M3 是唯一的修复点。

## 4. V2-M2 调度与布局改造（去 eventActiveFlag、fanout 收窄、P_event 非 sink 映射、逃逸类）

### 目标

调度数据结构对齐三类点火：删 eventActiveFlag；fanout 只指向非 sink；P_event
产出少量非 sink 映射；逃逸类无旗标需求。

### 范围（文件级）

- `wolvrix/lib/grhsim/backend/cpu_layout.cpp`（`cpu.st.layout-named-stores`）：
  activeStore 从三字段（eventActive/dataActive/dataNext）减为两字段
  （dataActive/dataNext）；fanout 表（inputFanout/supernodeFanout/stateFanout）
  的目标集合过滤为非 sink 超节点（边界②）。
- `wolvrix/lib/grhsim/backend/cpu_schedule.cpp`：
  1. `cpu.st.build-event-bitmaps` 改为 **`cpu.st.build-event-activation-map`**（或
     同名改造）：产物从"sink 向事件位图"改为"edgeDet 聚类 → 含该事件非 sink op
     的非 sink 超节点"的静态映射（覆盖面小，只含事件非 sink op 的超节点）；
     sink 超节点不再配位图（其签名即门控条件）。
  2. `cpu.st.build-phase-schedule`：task/fanout 结构同步（无 eventActive 引用）；
     PhaseSchedule 校验同步更新（`verifyCpuSchedule`）。
- `wolvrix/lib/grhsim/backend/cpu.cpp`：`computeCpuEventDomainSets` 若仅服务旧
  位图则随之收缩或删除（登记使用点逐一核对）。

### 验收

- 调度/layout 校验 pass；单测：fanout 不含 sink 目标；映射表覆盖全部含事件非
  sink op 的超节点（漏映射即失败）；逃逸类无映射项。
- `make build && make test_wolvrix`（同 M1 口径记录暂时性失败）。

### 完成记录（2026-10-03）

**实现**：

- `cpu_layout.cpp`：activeFlags 从三字段（eventActiveFlag/dataActiveFlag/
  dataActiveFlagNext）减为两字段（dataActiveFlag/dataActiveFlagNext），布局
  校验同步；`activeBytes` 统计与字段 aux/offset 语义不变。
- `cpu_schedule.cpp`：`cpu.st.build-event-bitmaps` 更名为
  **`cpu.st.build-event-activation-map`**，产物从"influence 闭包的全超节点
  位图"改为 **`eventActivation`：act → 含该 act 事件 op 的非 sink 超节点位图**
  （bit i = C2 序号 i，直接扫超节点 `attrs.eventActs`；无非 sink 载体的 act
  不配条目，稀疏）。旧 `supernodeActSets`/`computeCpuEventDomainSets` 影响
  传播机制随之整体删除（含 `cpu.hpp` 声明与 `cpu_partition.cpp` 定义——最后
  一个消费点消失）。三张 fanout 表目标一律过滤为 NonSink（边界②；input/
  state 表按构造本就只含非 sink，过滤为显式不变式）。`CpuExecution::
  EventDataGated` 更名 `DataGated`、`CpuMappingStage::EventBitmaps` 更名
  `EventActivationMap`（枚举数值均不变，checkpoint 兼容）。诊断键改为
  `event_acts=/supernodes=/mapped_supernodes=`。`verifyCpuSchedule` 对激活
  映射做重算全等比对——同时即"覆盖全部非 sink 载体"与"无 sink 出现"校验。
- `model.hpp`：`CpuEventBitmap`→`CpuEventActivation{act, supernodeWords}`、
  `schedule.eventBitmaps`→`eventActivation`；`json.cpp` 位置化 wire 形状不变
  （M1 时代 checkpoint 载入后会被 verify 重算比对明确拒绝，fail-closed）。
- **emit 适配（计划偏差：M3 §5 第 1/2 项被迫提前）**：两字段化后 emit 对
  `fields[2]` 的引用即越界、新映射不再覆盖 sink 超节点导致 eventActiveFlag
  无法重建——双重门在 M2 的 payload 下无法存活，故同步完成：`eventGated_`
  与双重门删除；scanRange 按 `supernodeCategory` 生成**三类调用点**（非
  sink：`dataActiveFlag` 点火并清零；SinkEvent：签名 act 位析取门控；
  SinkEscape：每轮无条件）；emitEdgeDet 改为把命中 act 的激活字直接 OR 进
  `dataActiveFlag`；pEvent/initGlue 的 eventActiveFlag 填充删除。sink 超节
  点体内 per-op `actGuard` 保留（与调用点门控冗余但无害，归 M3 删除，边界
  ③）。init 的 `dataActiveFlag.fill(1)` 对 sink 序号残留置位（无任何调用点
  读取，无害，代码注释说明）。

**测试改写/恢复清单**（逐条记录）：

- `test_cpu_stores.cpp`：`eventBitmapsTest`→`eventActivationMapTest`
  （MainFixture 事件载体全为 sink → 映射为空 + 诊断键）；`latchConeExemptTest`
  →`latchEscapeTest`（latch 写锚定 SinkEscape、映射为空）；
  **`memSinkBitmapTest`（M1 标注停用）重写为 `eventActivationCoverageTest` 并
  恢复**——夹具含带事件非 sink op（posedge 门控 DPI 调用有返回值）断言其
  超节点被 act 条目恰好覆盖（验收"漏映射即失败"）、SinkEvent/SinkEscape/Mem
  相写均不出现；`phaseScheduleTest` 的 shnv fanout 断言按预期二次更新为
  **整表为空**（跨界消费者全是 sink，边界②）；`verifierRejectsTest`(b) 改为
  注入伪激活条目；`namedStoreLayoutTest`/`emptyModelTest` 按两字段同步。
- `test_cpu_phases.cpp`、`test_grhsim_ir.cpp`、`test_reg_to_mem_semantics.cpp`、
  `scripts/wolvrix_xs_grhsim_ir.py`：pass 更名同步。
- `test_cpu_phase_emit.cpp`：`passthroughTest`/`fanoutTest` 按两字段同步；
  counter/nbaChain/asyncReset/dualClock/glitchClock 的位图断言改写为"sink-only
  载体 → 激活映射为空"；**`dpiSmokeTest` 两个 TU 变体恢复并新增激活映射断言
  （M3 计划项提前转绿）**；**`generalDisplayTest` 按 v2 语义重写预期**（见下
  条）；`perfCountersTest` 计数不变（逐 eval 一轮、两类超节点各点一次）。
- **行为语义变化（用户决策的逃逸机制的直接后果，记录备查）**：逃逸类每轮
  无条件点火 ⇒ 无事件 $display 每个 eval 重打（旧行为为"操作数变化才打"）；
  SinkEvent 签名门控 ⇒ 事件 $display 每个边沿都触发，旧"边沿无数据变化不
  重复触发"（旧 plan §100）的 IEEE 偏离被消除。写类 op 有变化检测兜底，纯
  副作用 op 由 en 自查门控（M1 记录的风险项如期出现，$display 形态已钉入
  generalDisplayTest 新预期）。

**验证结果**（日志 `ptmp/v2m2_*.log`）：

- `make build` 通过；`make test_wolvrix` 54/57（transform-comb-lane-pack、
  transform-repcut、ingest-write-back-slice(SEGFAULT) 为基线已知失败，与
  本轮改动模块无关）；grhsim-cpu-phase-emit 全绿（含恢复的 dpiSmokeTest
  两个 TU 变体与按 v2 语义重写的 generalDisplayTest）。
- xs-bugcase **25/25**（含 CASE_025）；HDLBits **162/162**；黄金差分
  **161/161** 逐 eval 与 M0 黄金一致。

**后续里程碑关注项**：

- ~~V2-M3 剩余工作收窄为：sink 超节点体内 per-op `actGuard` 删除（边界③；
  写 op 的 `if(eventActStore[act])` 包裹去除，en/地址等数据条件保留）、
  emit 侧 ICG 夹具（latch 门控 SRAM 形状的写-读回断言）。CASE_025 与
  dpiSmokeTest 已分别于 M1/M2 提前转绿，M3 验收改为"保持绿 + guard 删除后
  回归不褪色"。~~（已于 V2-M3 完成，见 §5 完成记录）
- V2-M5 性能 A/B 时关注：逃逸类每轮点火的成本（plan §9 风险 1）与
  boundary 流量增长（风险 2）的实测归档。
- 整核（XS）上的激活映射规模：SRAM 同步读等带事件非 sink op 的条目数，
  M5 emit 时归档统计。

## 5. V2-M3 emit 三类调用点与体内 guard 规则（CASE_025 转绿）

> **范围更新（2026-10-03，V2-M2 完成记录）**：本里程碑的主体已被提前消化——
> 三类调用点、`eventGated_`/双重门删除、activeStore 两字段同步在 V2-M2 完成
> （payload 变更使其无法拆分）；CASE_025 在 V2-M1 提前转绿；dpiSmokeTest 在
> V2-M2 恢复。**V2-M3 剩余范围 = sink 超节点体内 per-op `actGuard` 删除（边界
> ③）+ emit 侧 ICG 夹具 + 回归保持**。以下原文保留作参考，实施时以此注记
> 为准。

### 目标

生成的 P_general sweep 按类别生成三种调用点；sink 体内去除逐 op 事件判断；
非 sink 体内事件 op 保留逐 op guard；删除 eventActiveFlag 成员与双重门。

### 范围（文件级）

- `wolvrix/lib/grhsim/backend/cpu_phase_emit.cpp`：
  1. 删除 `eventGated_` 计算与双重门；activeStore 成员同步为两字段。
  2. 三类调用点：
     - 非 sink：`if(dataActiveFlag[i]){dataActiveFlag[i]=0; sn_i();}`
     - sink 事件簇：`if((eventActStore[a/8]>>(a%8))&1 || ...) sn_i();`（签名逐 act
       或起来）
     - sink 逃逸：`sn_i();`（每轮无条件）
  3. sink 超节点体内的写 op 去掉 `if(eventActStore[act])` 包裹（边界③；en、
     地址等数据条件保留）；非 sink 超节点内的事件 op 保留逐 op guard。
  4. pEvent 末尾按 M2 的静态映射置位 dataActiveFlag（替代原 eventActiveFlag
     重建）；eventActStore、prevEvent、timeslotTriggerFlag 逻辑不动。
  5. 头部成员、dumpState、checkpoint 同步；`WOLVRIX_GRHSIM_WAVEFORM` 波形能力
     不受影响（信号集不变）。
- `wolvrix/tests/grhsim/test_cpu_phase_emit.cpp`：改写依赖旧门控的断言
  （bitmapBits、双重门形态等），新增 ICG 夹具（latch 门控 SRAM 形状，断言
  写-读回数据一致）。

### 验收（本计划的转折点）

- **`make -C testcase/xs-bugcase/CASE_025 run` 通过**（合并粒度默认；即 NO00029
  的最小复现从已知失败转为常驻回归）。
- emit 单测编译并运行通过；`make test_grhsim_cpu_phase_emit` 全绿。

### 完成记录（2026-10-03）

**实现**（`wolvrix/lib/grhsim/backend/cpu_phase_emit.cpp`）：

- 新增 `bodyGuard(op, current)`：`current` 为 P_general 超节点序号时查
  `supernodeCategory`——sink（SinkEvent/SinkEscape）返回 `"true"`（SinkEvent
  全体 op 与超节点签名同集，调用点签名门控已覆盖，结构性不变式见
  `cpu.st.merge-general-supernodes` 的 mixed-signature 抛出；SinkEscape op 本就
  无事件）；非 sink 与 `current == ~0u`（P_event/P_output op 列表）回落
  `actGuard`。
- sink 体内 per-op guard 删除落点：`emitRegWrite`、`emitGeneralMemWrite`、
  `emitSystemTask`（签名补 `current` 参数）、`emitDpiCall` 四处由 `actGuard`
  改 `bodyGuard`；en、地址等数据条件原样保留。**P_mem 的 `emitMemWrite` 保持
  `actGuard`**（P_mem 不在超节点体内，无调用点门控兜底）；Output 相路径不经
  `actGuard`，不受影响。

**测试**：

- `test_cpu_phase_emit.cpp` 新增 **`icgGatedSramTest`**（CASE_025 同构 ICG
  夹具）：透明低 latch 在 clk 低时捕获请求使能，`gclk = clk & EN`，三个
  posedge-gclk 写（raddr_d/ren_d regWrite + Memory memWrite）聚为一个
  SinkEvent 超节点。断言三层：(a) 结构——regLatch 类写不进 P_mem 计划
  （`memWritePlan` 为空）、无非 sink 事件载体（`eventActivation` 为空）；
  (b) 源码——全源中 guard 形态的 act 位读取恰好 1 处（SinkEvent 调用点
  签名门控；dumpState 的位读取按 `static_cast<unsigned>(` 前缀排除，M3 前
  为 4 处）；(c) 功能——13 步驱动覆盖死锁复现（使能在 clk 低时发布、
  gclk 随 clk 上升、宏寄存器更新）、门控保持（EN=0 时 clk 翻转无扰动）、
  写使能保留（读周期 posedge 不写 Memory）与 latch 透明性（clk 高时使能
  变化不穿透）。无既有断言改写（本里程碑纯新增）。

**验证结果**（日志 `ptmp/v2m3_*.log`）：

- `make build` 通过；`make test_grhsim_cpu_phase_emit` 全绿（含
  `icgGatedSramTest`）；`make test_wolvrix` 54/57（transform-comb-lane-pack、
  transform-repcut、ingest-write-back-slice(SEGFAULT) 为基线已知失败，与
  M2 相同）。
- xs-bugcase **25/25**（含 CASE_025 常驻绿）；HDLBits **162/162**；黄金差分
  **161/161** 逐 eval 与 M0 黄金一致——guard 删除后回归不褪色，M3 验收闭环。

**后续里程碑关注项**：

- V2-M4 按 §6 口径全量复跑并归档（本里程碑已按同口径验证，M4 补 DUT=105
  双参照项）。
- V2-M5 关注项（逃逸类成本、boundary 流量、XS 激活映射规模统计）不变。

## 6. V2-M4 小回归全绿

### 目标

全部小/中规模套件回到绿色基线，无新增失败。

### 范围与验收

- `make test_wolvrix`：54/57 基线（transform-comb-lane-pack、transform-repcut、
  ingest-write-back-slice 三项既有失败，无新增）；M1-M3 期间标注的暂时性失败
  全部清零。
- `make run_all_hdlbits_grhsim_ir_tests`：162/162。
- `make run_xs_bugcase_grhsim`：25/25（含 CASE_025）。
- `make check_sim_refactor_baseline`：161/161 逐 eval 与 M0 黄金一致；
  `make -C testcase/hdlbits run_tb DUT=105` 与 `make run_hdlbits_grhsim DUT=105`
  双参照通过。
- 日志落 `ptmp/`（命名 `v2m4_*.log`），逐项记录入档。

### 完成记录（2026-10-03）

自 V2-M3 提交（wolvrix `66c5024`）起无代码改动，本轮为 §6 口径的全量复跑
确认（日志 `ptmp/v2m4_*.log`）：

| 项 | 结果 | 日志 |
| --- | --- | --- |
| `make test_wolvrix` | 54/57，失败恰为基线三项（transform-comb-lane-pack、transform-repcut、ingest-write-back-slice SEGFAULT），无新增 | `v2m4_test_wolvrix.log` |
| `make run_all_hdlbits_grhsim_ir_tests` | 162/162（162 个 RUN、0 fail/mismatch/error） | `v2m4_hdlbits.log` |
| `make run_xs_bugcase_grhsim` | 25/25（含 CASE_025 常驻绿） | `v2m4_xs_bugcase.log` |
| `make check_sim_refactor_baseline` | 161/161 逐 eval 与 M0 黄金一致 | `v2m4_golden.log` |
| `make -C testcase/hdlbits run_tb DUT=105` | 通过（Verilator 参照，exit 0） | `v2m4_dut105_verilator.log` |
| `make run_hdlbits_grhsim DUT=105` | 通过（`dut_105 passed: 4-digit BCD counter with enables`） | `v2m4_dut105_grhsim.log` |

M1-M3 期间标注的暂时性失败已确认全部清零：M1 停用的
`memSinkBitmapTest`（M2 重写为 `eventActivationCoverageTest` 恢复）与
`dpiSmokeTest` 两个 TU 变体（M2 恢复）均在绿；无遗留标注项。

**后续里程碑关注项**：

- V2-M5 整核复测：逃逸类每轮点火成本、boundary 流量增长、XS 激活映射
  规模统计（SRAM 同步读等带事件非 sink op 的条目数）按 §7 口径归档。

## 7. V2-M5 XiangShan 整核复测与完整 CoreMark 验收

### 目标

整核 emit/编译/链接/运行全链路，最终通过完整 CoreMark + NEMU difftest。

### 范围与验收

1. 整核 emit：`make xs_wolf_grhsim_ir`（管线复用既有
   `build/xs/grhsim-ir/xiangshan_flat_grh.json`，脚本与 pass 参数不变）；记录
   新模型的 op/状态/超节点分类统计（非 sink / sink 事件簇 / sink 逃逸的数量与
   boundary 规模对比旧模型，归档 `ptmp/`）。
2. 编译与链接：多 TU clang -j32 并行编译；difftest emu 链接 exit 0。
3. 15k 周期烟测：无断言、无 mismatch。
4. **完整 CoreMark（不设周期截断）+ NEMU difftest：无 mismatch、`HIT GOOD
   TRAP`、退出码 0**（本计划最终验收）。
5. 性能 A/B：`scripts/benchmark_grhsim_ir.py` 同口径对照 M0 存档（安静机器、
   同负载同周期范围），记录逃逸类与边界增量的性能影响；达到旧实现同一量级
   为合格，数据归档 `ptmp/`。

## 8. V2-M6 文档收口与提交

- 同步 `wolvrix/docs/grhsim_ir/`（overview/backends/cpu/flows/cpu-st/相关 pass
  文档）与 plan-v2.md、NO00029（补"已按 v2 修复"结论）、本计划状态；
  涉及流程变化时同步 AGENTS.md。
- 提交：wolvrix 仓库与根仓库分别 conventional commit（根仓库含子模块指针）；
  提交说明点名 `ptmp/grhsim_direct_mem_backup_20260930.diff` 提醒属主。

## 9. 风险与开放项

1. **逃逸类成本**：无事件 sink 每轮运行（与现状 latch 超节点相当，预计无回退；
   M5 实测确认）。
2. **边界流量增长**：sink 簇操作数全部经 boundary；C3 布局规模与 fanout 置位
   次数增长，M5 归档对比数据，若超阈值再评估 sink 簇内合并小操作数锥的豁免
   （不破坏非 sink/sink 分界的前提下）。
3. **P_event 映射完备性**：漏映射 = 事件非 sink op 在边沿当轮执行不到；M2 以
   校验强制（映射必须覆盖全部含事件非 sink op 的超节点），M4 回归兜底。
4. **拓扑序强制**：sink 簇操作数新鲜度依赖非 sink 先于 sink；M1 注册为映射
   校验不变式，防止后续划分优化悄悄破坏。
5. **测试改写面**：test_cpu_phase_emit 多个用例锚定旧门控形态，M3 内逐条改写
   并记录理由，禁止以降低断言强度换取通过。
