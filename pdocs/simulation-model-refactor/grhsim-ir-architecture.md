# GrhSIM IR 仿真架构说明（当前架构 · 备查）

日期：2026-10-04
描述对象：V3-M3 终态（wolvrix `66000f6`，XiangShan 完整 CoreMark + NEMU difftest 通过）
权威细节层：`wolvrix/docs/grhsim_ir/`（`overview.md` 为总纲，pass 级细节在 `passes/`）
本文地位：仿真模型迁移（六阶段重构）全部记录的**蒸馏收口**。下列文档已被本文取代并删除，
原文可在 git 历史查阅：`sim-model-refactor-plan.md`、`sim-model-refactor-impl-plan.md`、
`sim-model-refactor-plan-v2.md`、`sim-model-refactor-impl-plan-v2.md`、
`pdocs/NO00029-grhsim-ir-icg-activation-deadlock-20261003.md`。

---

## 1. 这份文档讲什么

一句话：GrhSIM IR 把 SystemVerilog 整核设计（经 GRH IR）编译成一个**多翻译单元 C++ 仿真器**，
运行时按**六阶段事件驱动调度**执行。本文说明三件事：

1. 架构为什么长现在这样（历史决策与其教训，避免重蹈覆辙）；
2. 当前架构是什么（编译流水线 + 运行时模型，概念级）；
3. 当前状态在哪里（验证基线、性能位置、优化方向的入口）。

实现细节（每个 op 的语义、每个 pass 的规则、每个字段的编码）不在本文范围，
以 `wolvrix/docs/grhsim_ir/` 为准；同目录的 `grhsim-ir-pass-flow.md` 是逐 pass 的
输入/输出/职能说明。

## 2. 简史：为什么长现在这样

### 2.1 起点与 v1 六阶段

旧 GrhSIM C++ 模型逐 op 全量求值，整核性能不可用。2026-09 起重构（M0 基线）：
组合逻辑合并成"超节点"按需激活，存储双缓冲实现非阻塞赋值（NBA），eval 拆成
P_input / P_event / P_general / P_mem / P_publish / P_output 六个阶段。
M0 性能：100k CoreMark 周期宿主时间 85.9s。

### 2.2 v1 的硬伤：latch-ICG 激活死锁（NO00029 蒸馏）

v1 的超节点激活用**双重门**：带事件的超节点必须"事件发生（eventActiveFlag）
且数据变化（dataActiveFlag）"同时成立才点火。这在 XiangShan 的锁存式时钟门控
（latch-ICG）上形成死锁。用孤立案例（xs-bugcase CASE_025，约 60 行 RTL）讲：

XiangShan 每个 SRAM 宏实例自带一个 ClockGate（全芯片 elaborate 出 189 个实例，
每实例一套，互不共享）：

```systemverilog
// ClockGate.sv：低电平采样的锁存使能 + 与门
always_latch begin
  if (!CK) EN = TE | E;   // CK 低电平窗口内 EN 透明跟随 E
end
assign Q = CK & EN;        // Q = 该实例自己的门控时钟输出
```

宏内部的寄存器（读地址/读使能等）全部工作在该实例自己的 `Q` 的上升沿上，
而门控使能 `E = rckEn | wckEn` 是组合逻辑输出。v1 的 C2 合并把 **E 的生产者**
和一个**按 Q 门控的寄存器写**熔进了同一个 eventGated 超节点，于是：

1. 该超节点要点火，必须 Q 出现 posedge（eventActive）；
2. Q 要出现 posedge，必须 EN 在 CK 低电平窗口已锁存为 1；
3. EN 要锁存 1，必须 E 在低电平窗口已发布为 1；
4. E 要发布，必须它所在的超节点点火——回到 1。

四个条件互为前提，从上电起恒不成立：全芯片 189 个 ICG 批量冻结，SRAM 写不进、
读恒 0，最终 CoreMark 第 238 条指令处触发 DCache 断言。把合并粒度强制为 1 op
（`--max-op-in-compute-supernode 1`）环即拆开、一切正常——证明锁存器语义、
透明读、边沿检测、不动点迭代全部正确，**唯一失效的是 eventGated 超节点的
激活条件**。

原理要点：使能锥（数据驱动，需要随数据变化随时发布）与事件写（沿驱动，只在
边沿提交）被合并进同一节点后，节点的单一门控条件不可能同时满足两种语义。
这不是实现 bug，是划分自由度缺失——旧"事件域约束"允许两者同节点。

### 2.3 v2 决策（2026-10-03，当前架构的基石）

保留六阶段框架，做两处激活语义调整：

1. **全面移除 eventActiveFlag**：不存在"事件+数据"双重门。超节点按结构分两类——
   **非 sink 超节点**（体内全是有返回值的 op）纯以 dataActiveFlag 数据驱动点火；
   **sink 超节点**（体内全是无返回值的写类 op）带事件的以 eventActStore 组合
   门控点火、无事件的每个 round 无条件点火（逃逸机制）。
2. **sink op 按事件签名聚类**：sink op（reg/latch/mem 写、无返回值的事件触发
   调用）不进入非 sink 的合并框架，按事件签名（canonical event key，含边沿
   方向；空签名自成一类）聚成 sink 超节点，**不与非 sink 超节点合并**。

构造性效果：使能锥生产者永远在非 sink 超节点、随数据变化即时发布；EN 锁存写
落入逃逸类、每轮求值门控——§2.2 的环在构造上不可能形成（CASE_025 在划分
改造落地当天转绿，并作为常驻回归）。

### 2.4 V3 工程化三项（2026-10-03/04）

- **V3-M1 dataActiveFlag 位图化**：一字节一超节点改一位一超节点，扫描按 64 位字
  外层跳过；XS 上激活旗标存储 70,690→8,848 字节，完整 CoreMark 宿主时间 -17.3%。
- **V3-M2 sink 超节点参与 TU 划分**：{posedge clock} 单签名簇（88.5k op）不再是
  不可分的编译单元，拆为 wrapper + SupernodePart；最大 TU 139 MB→7.5 MB，
  全量编译 16.8→14.5 min，运行再 -2.6%。
- **V3-M3 克隆共享计算移入 C 段**：原 B7（语义层预测式克隆，层次倒置的设计缺陷）
  撤除，改为 C2 之后的微调 pass `cpu.st.clone-shared-boundaries`，基于真实
  超节点边界克隆；克隆量 -55%，框架新增"受控语义微调"通道
  （`commitSemanticMicroMutation`）。

三项相对 v2 净提速 18%（完整 CoreMark 791.8s→648.4s），行为逐拍不变。

## 3. 设计约束（作者 2026-10-01 四条，继续有效）

1. **生成 C++ 必须分 TU 并行编译**：整核代码按函数和规模分批生成多个 translation
   unit，初始化和过大的阶段函数也受控拆分；经项目 Makefile 并行编译链接。
2. **declaredSymbol 贯穿两侧 IR 流水线**：GRH simplify 保留声明来源，lower 后
   继续维护，用于状态同族识别、数组恢复、打包优化与最终命名；折叠/合并/拆分后
   保留来源映射。
3. **分而治之的优化顺序**：先全图优化（reg-to-mem、comb-pack 等）再全图
   simplify；第一轮分解出计算分区后各分区独立 simplify；第二轮只在 P_general
   内划分超节点；最后才做 CPU mapping。
4. **性能优先，允许改变状态形态**：允许折叠、合并、打包、数组化状态，数组是
   合法 IR 类型；regLatchStore 承载零碎状态（双缓冲 + publish 整块拷贝实现
   NBA），memStore 承载大块连续状态（独立阶段原地更新）；具名字段与来源映射
   服务于阅读和调试。

## 4. 编译流水线总览

```text
SystemVerilog → GRH IR（层次化） → 平坦 GRH
  → lower_grhsim → GrhSimModel（语义图）
  → A 段：全图优化（canonicalize / reg-to-mem / comb-pack / pack-bit-registers /
          simplify(whole) / select-state-stores）
  → B 段：相位分区（classify-event-inputs / lower-edge-detect /
          extract-output-cones / migrate-timeslot-tasks / split-phases /
          simplify(phase) / verify --seal semantic）
  → C 段：CPU 映射（C1 建 node → C2 合并超节点、定编号 → C2.5 克隆共享边界
          → C3 store 布局 → C4 事件激活映射 → C5 mem 写计划
          → C6 函数打包 → C7 相位调度 → C8 TU 规划）
  → cpu.st.emit-cpp → 多 TU C++ + Makefile → 并行编译 → 仿真器
```

- **语义层与映射层的边界**：B8 封板（seal）之后语义图冻结，唯一例外是注册的
  C 段微调 pass（当前仅 C2.5 `cpu.st.clone-shared-boundaries`，经
  `commitSemanticMicroMutation` 申报，revision++ 但不整份失效 mapping）。
- 逐 pass 的输入/输出/职能：同目录 `grhsim-ir-pass-flow.md`；
  权威规则：`wolvrix/docs/grhsim_ir/passes/*.md`、`flows/cpu-st.md`。
- 流水线编排实体：`scripts/wolvrix_xs_grhsim_ir.py` 的
  `CPU_SEMANTIC_PIPELINE` / `CPU_MAPPING_PIPELINE`。

## 5. 运行时模型

### 5.1 六阶段 eval 骨架

```text
eval():
  P_input()                        # 装载输入到 boundaryValueStore，按 inputFanout 置位
  loop round = 1..MAX_ROUND:       # 不动点迭代
    P_event()                      # 事件锥求值；edgeDet 检边沿写 eventActStore（当轮脉冲）
    P_general()                    # 按拓扑序扫描超节点，三类调用点按需点火
    P_mem()                        # memStore 大状态写原地提交，变化检测唤醒读者
    if P_publish(): break          # regLatchStoreNext→regLatchStore；dataActiveFlagNext 并入
  P_output()                       # 输出锥 + 时隙任务（$monitor/$strobe），每 eval 一次
```

### 5.2 存储布局（七具名 store）

| store | 内容 | 关键性质 |
| --- | --- | --- |
| `regLatchStore` / `regLatchStoreNext` | 零碎状态（寄存器/锁存器，允许打包合并） | 双缓冲；写全部落 next，P_publish 整块 memcpy 回 current 实现 NBA，同时维持"每轮开始 next==current"不变式（部分位写以 next 为合并基准） |
| `memStore` | 大块连续状态（数组/恢复的高维数组） | 单实例、P_mem 原地更新，不进 publish 拷贝 |
| `boundaryValueStore` | 输入端口值 + 跨超节点边界值 | 每个边界值带"上一轮值"槽用于真变化比较 |
| `prevEventStore` | 每个 edgeDet 一个 prev 槽位 | 边沿检测的历史值；init 为 event 初值，上电不报假沿 |
| `eventActStore` | (event, edge) 去重聚类后每聚类 1 bit | **当轮脉冲**：每轮 P_event 覆盖重算，仅检出边沿的当轮为 1 |
| `timeslotTriggerFlag` | 带事件时隙任务的触发记录 | eval 级粘滞，P_output 消费后清除 |
| `dataActiveFlag` / `dataActiveFlagNext` | 每个**非 sink** 超节点 1 bit（V3-M1 位图化） | current 轮消费、next 跨轮传递；P_publish 并入 |

### 5.3 两类超节点、三种点火（架构核心）

P_general 的全部 op 按"有没有返回值"分两类，点火方式随之确定：

- **非 sink 超节点**（有返回值的 op，含带事件的 DPI/系统调用返回值）：
  走合并框架（锥吸收、coarsen、DP 分段、规模上限 128 op）；点火条件是
  `dataActiveFlag[i]`，置位来源两类——数据通路（输入变动、前驱发布、
  P_publish 并入）和 P_event 静态映射（检出边沿时唤醒**少量**含事件非 sink
  op 的超节点，XS 全核仅 4 个）。点火即清自己的旗标。
- **sink 超节点**（无返回值的写类 op）：不合并，按事件签名聚类；内部**不再
  重复事件判断**（聚类已保证同签名），只求值 en、地址、数据条件。
  - **SinkEvent**（带事件）：调用点把签名内各 act 位析取门控
    （`if (eventActStore[a] || eventActStore[b]...) sn_i();`）——事件发生即点火，
    不消耗任何 flag；
  - **SinkEscape**（无事件，如数据门控的 latch 写、ClockGate 的 EN 写）：
    **逃逸机制——每个 round 无条件点火**。电平敏感语义要求逐轮求值门控
    （`!CK` 窗口内 latch 必须透明）；写侧变化检测兜底，无变化不置
    dataActiveFlagNext，收敛不受影响。XS 实测逃逸类仅 409 op，成本可忽略。

三条边界规则（v2 决策第 3 条，违反即破坏语义）：

1. P_event 经静态映射只激活非 sink 超节点（sink 不需要——事件类自查签名、
   逃逸类每轮跑）；
2. 非 sink 超节点**不向** sink 超节点传递 dataActiveFlag 激活（fanout 表在
   C7 过滤为只含非 sink 目标）；
3. sink 超节点内部不重复事件判断（写 op 的 `if(eventActStore[act])` 包裹已
   删除，由调用点签名门控覆盖）；P_mem 写簇不在超节点体内，保留逐 op 判断。

### 5.4 事件检测

- 事件逻辑锥（从状态 S 到各 op 的 event 操作数）整体复制进 P_event 自包含
  计算（复制+剥离：P_general 侧仅为事件服务的 op 删除，数据/事件两用的保留
  数据通路那份）。
- `edgeDet` op：操作数是事件锥末端值，按 (event, edge) 去重聚类，每个聚类
  静态分配 eventActStore 位与 prevEventStore 槽；执行即对比 prev、命中写位、
  更新 prev。同一信号可挂多个 edgeDet（不同边沿方向各占各的 prev 槽）。
- eventActStore 是**脉冲**：下一轮 P_event 覆盖重算。同 eval 内跨 round 的
  事件翻转会产生多个边沿（glitch 时钟下同 eval 可多次写同一 reg），与
  event-driven 行为一致，有意接受。

### 5.5 NBA 与收敛如何成立

- 写落 next、publish 拷贝：边沿当轮所有读看到的都是 pre-publish 状态；
  后续 round 里 eventActStore 已覆盖重算、边沿不再可见，写不会重复提交。
- **写侧变化检测**：reg/latch 写比较新值与 current 可见值，真变化才置
  dataActiveFlagNext（写 shadow 时天然能看到旧值）；mem 写做 cell 级比较，
  无变化不写、不唤醒。这是逃逸类与无事件 mem 写的收敛保证。
- **拓扑序**：非 sink 超节点编号恒小于其消费者及全部 sink 超节点（C2 定序、
  mapping 校验强制），同轮内 sink 读到的 boundary 必是本轮已刷新的活值；
  逆向信息流（状态写→读者）只经 dataActiveFlagNext 走跨轮通道。
- **P_publish 不变式**：publish 开始时 dataActiveFlag 必然全 0（扫描按拓扑序
  见旗即消费，不存在残留），因此"并入"与"覆盖"等价，OR 仅是实现便利；
  fixedPoint = dataActiveFlagNext 全 0。

### 5.6 P_mem 为什么独立

mem 写是从 sink 中按存储类属剥离的大状态写，共享同一套签名聚类与两级点火，
但单独成阶段，原因有二：

1. memStore 单实例原地更新，避免 P_publish 对大阵列做双缓冲拷贝；
2. 集中到 P_general 之后提交，保证"本轮所有 memRead 读到上一轮结束时的
   状态"，与 reg 写一致的 NBA 效果（若在 P_general 中间原地写，同轮靠后的
   memRead 会看到新值）。

写簇内按静态优先级依次写（同地址后写覆盖先写）；读者唤醒按地址形态区分：
常量地址精确比对、动态地址保守全唤醒。

### 5.7 P_output 与时隙任务

输出锥复制进 P_output，收敛后每 eval 全量算一次（锥小，暂不做门控）。
$monitor/$strobe 类时隙任务也移入此阶段，对齐 IEEE"time slot 末只报一次"：
无事件的靠历史值判定变化；带事件的触发记录由 timeslotTriggerFlag 承载
（eventActStore 到 eval 末已被覆盖，故需 eval 级粘滞的旗标）。always_comb
里的 $display 留在 P_general，delta-cycle 内重复触发符合 IEEE 语义。

### 5.8 初始化

init 把全部非 sink 超节点的 dataActiveFlag 置位（全脏起动）：首个 eval 全图
求值一遍，之后靠变化传播收敛——否则第一个边沿到来时，从未有过数据变化的
常量锥不会点火。regLatchStoreNext 初值与 current 一致；prevEventStore 各槽
置对应 event 初值。

### 5.9 逃逸机制的已知行为后果（有意接受，记录备查）

- 无事件 $display（数据条件门控、落入逃逸类）每个 eval 都会执行：旧"操作数
  变化才打"变为每轮重打，可观测输出增多但语义合法；
- 事件门控 $display 现在每个边沿都触发：旧实现"边沿无数据变化不重复触发"
  的 IEEE 偏离被消除；
- 写类 op 有变化检测兜底无成本问题；纯副作用 op 靠自身 en 条件门控。

## 6. 生成的 C++ 长什么样（人工审查指引）

产物目录 `build/xs/grhsim-ir/`（XS 全核：1091 个 TU、约 1.5 GB 源码、
emit 约 6.7 min、clang -O3 -j32 编译约 14.5 min）：

- `grhsim_SimTop.hpp`：仿真类。成员 = 七具名 store 结构体实例 + 端口 +
  各阶段函数与超节点函数声明；大超节点的跨 chunk 局部值经 `SnFrame<i>`
  栈帧传递。
- `grhsim_SimTop_tu<N>.cpp`：按 C8 计划装箱的块流（Core → Init → Event →
  GeneralScan → Supernode → Mem → Output → Dump）。关键形态：
  - `pEvent()`：事件锥 + edgeDet，命中 act 的激活位图直接字 OR 进
    dataActiveFlag；
  - `pGeneral()` 扫描：非 sink 前缀按 64 位字外层跳过、字内逐位读 live word
    清位点火（`sn_<i>()` 需编译期序号，故不用 ctz 动态位扫描）；随后
    SinkEvent 调用点签名析取门控、SinkEscape 无条件调用；
  - 超节点函数：过大者（估算行数超 unit 上限且 helper chunk ≥2）拆为
    wrapper + 若干 SupernodePart，part 摊到多个 TU（V3-M2）；part→helper
    区间由 `cpuSupernodePartRanges`（`include/grhsim/backend/cpu_phase_common.hpp`）
    在 C8 与 emit 双侧确定性重放；
  - `pMem()`：按写计划优先级原地提交 + cell 级变化检测；
  - `pPublish()`：next→current 整块 memcpy + dataActiveFlagNext 字级并入
    与收敛判定。
- 波形：`--waveform declared-symbols` 追加 `*_wave_<g>.cpp` 与 vendored
  libfst；`tools/fst_tools/fst_diff` 可与 Verilator 参考波形对比。

## 7. 验证资产与当前基线

| 套件 | 口径 | 防什么 |
| --- | --- | --- |
| `make test_wolvrix` | 54/57（恰基线三项 transform-comb-lane-pack、transform-repcut、ingest-write-back-slice SEGFAULT，与 grhsim 无关） | 单测（划分/布局/调度/emit 逐机制夹具，含 ICG 形状 `icgGatedSramTest`） |
| `make run_all_hdlbits_grhsim_ir_tests` | 162/162 | 小设计端到端行为 |
| `make run_xs_bugcase_grhsim` | 25/25 | XS 故障最小复现（CASE_025 = ICG 死锁常驻回归） |
| `make check_sim_refactor_baseline` | 161/161 逐 eval 与 M0 黄金一致 | 逐 eval 状态轨迹回归 |
| XS 完整 CoreMark + NEMU difftest | 无 mismatch、HIT GOOD TRAP、exit 0；**逐拍轨迹钉住 instrCnt=663,688 / cycleCnt=297,291**（IPC 2.23） | 整核最终验收；任何改动须同迹或有意变更 |

## 8. 已知性能差距与优化方向

当前唯一性能基线（`pdocs/perf-optimization/20261004-v3-sixphase-baseline.md`）：
M0 存档 85.9s vs V3-M3 223.4s（100k CoreMark 周期，3+3 交替同口径）= **2.60× 回退**。
回退源自 v2 六阶段架构本身，不是 V3 三项（V3 相对 v2 净提速 18%）。两大成本项：

1. **"事件即激活"**：{posedge clock} 单签名 sink 簇（88.5k op：74,967 寄存器写 +
   7,188 系统任务 + 6,365 断言）每 guest 周期整体点火、逐 op 查 en——旧数据门控
   下这些写只在输入变化时运行；
2. **boundary_fields +33.6%**（683,995→913,245）：sink 操作数全部经 boundary，
   带来更多每轮比较-store 与激活传播。

优化候选与记录规范集中在 `pdocs/perf-optimization/`（README 附 backlog）。
已确认的非问题（不必再查）：逃逸类成本（409 op）、编译时间（14.5 min 可接受）。

## 9. 文档地图

- 本文：架构概念层（当前文档）。
- `grhsim-ir-pass-flow.md`（同目录）：逐 pass 输入/输出/职能。
- `wolvrix/docs/grhsim_ir/`：权威细节——`overview.md`（模型与执行语义）、
  `dialects/`（op 语义）、`flows/cpu-st.md`（流水线规范）、`passes/`（逐 pass
  规则）、`backends/cpu.md`（mapping 与 emit 约束）。
- `pdocs/perf-optimization/`：性能优化记录（模板 + 基线 + 后续每条优化一档）。
- 历史档案（已删，git 历史可查）：v1/v2 计划与实施计划、NO00001–NO00029
  分析与优化记录。**注意：NO00001–NO00028 针对旧架构，结论不适用于当前模型。**
