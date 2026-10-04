# GrhSIM IR Pass 流程说明：从 GRH 平坦图到仿真 C++

> 版本：2026-10-03，对齐 wolvrix 子仓库 M5d-7 之后的流水线形态。
> 权威定义以 `wolvrix/docs/grhsim_ir/` 下的设计文档为准；本文是按工作流程组织的导读，
> 不另立规范。流水线编排代码在 `scripts/wolvrix_xs_grhsim_ir.py`（HDLBits 入口
> `scripts/wolvrix_hdlbits_grhsim.py` 直接复用它的 `CPU_PIPELINE`）。

## 1. 这份文档讲什么

给一份 SystemVerilog 设计（例如 XiangShan 核），wolvrix 先把它解析成 GRH IR——一张
描述**电路结构**的层次化图；再经过展平和清理，得到一张平坦的 GRH 图。从这张平坦图
出发，到最终生成一组可编译、可运行的 C++ 仿真源文件为止，中间经过的全部处理就是
本文所说的"grhsim IR 侧 pass 流程"。

整条流水线分五站：

```text
平坦 GRH 图
   │  lower_grhsim（结构图 → 仿真行为模型，一次性转换，不是 pass）
   ▼
初始 GrhSimModel ── grhsim.verify（体检）
   │
   │  A 段：全图优化（6 个 pass，改语义图，不碰后端）
   ▼
   │  B 段：相位分区（7 个 pass，仍只改语义图，最后"封板"）
   ▼
   │  C 段：CPU 映射（9 个 pass，只写 mapping，单向推进一次；
   │        唯一例外 C2.5 是注册的语义微调 pass）
   ▼
   │  cpu.st.emit-cpp（发射，只读消费 mapping）
   ▼
多个 .cpp + 共享头 + runtime + Makefile（make -j 并行编译出仿真器）
```

读完全文，你应该能回答：每个 pass 拿到什么样的模型、交出什么样的模型、它为什么
必须排在这个位置。

## 2. 先约定概念

后面每一节都会用到这些词，先一次性定义清楚。

**GRH IR 与 GrhSIM IR。** GRH IR 描述电路结构：有哪些模块、端口、寄存器、线网，
彼此之间怎么连。GrhSIM IR 描述电路的**仿真行为**：给定一组输入，输出是什么、内部
状态变成什么。前者回答"电路长什么样"，后者回答"电路怎么算"。本文的流程就是把前
者转成后者、再把后者打磨到适合生成高速 C++ 的过程。

**GrhSimModel。** 用 GrhSIM IR 书写的一份具体产物叫一个 `GrhSimModel`，由六个语义
分量加若干后端映射组成（`wolvrix/docs/grhsim_ir/overview.md`）：

```text
GrhSimModel
  I, O     外部输入 / 对外输出对象列表
  S        持久内部状态对象列表（寄存器、锁存器、memory 都是 S 的一员）
  F        外部函数声明（如 DPI 调用）
  G        仿真流图：op 是顶点，value 是 op 之间的数据流边
  Init     S 中每个状态的初始值
  mappings 每个仿真后端（如 "cpu"）一份映射方案，初始为空
```

**op、value、state。** op 是图里的一个操作（加法、多路选择、寄存器写……）；value
是 op 之间传递的一次性计算结果（相当于 SSA 值）；state 是会跨仿真轮次存活的持久
对象。寄存器、锁存器、memory 的区别不体现在 state 的类型上，而体现在读写它们的
op 上：`core.state.regWrite` 写寄存器，`core.state.memWrite` 写 memory 等。

**方言（dialect）。** 模型里能出现哪些类型和 op，由方言定义。`core` 方言是后端无关
的公共承接层（`core.compute.*` 纯计算、`core.state.*` 状态读写、`core.event.*` 事件、
`core.input/output.*` 端口读写、`core.dpi.call`、`core.system.task` 等）。引用写法是
`"方言名.定义名"`，如 `core.state.regWrite`。

**pass、pass manager、pass 类别。** pass 是对模型的一次处理：`run(model) ->
结果模型`。pass manager 按编排顺序逐个执行，每个 pass 返回后都会重新验证模型合法性；
任何一步失败立即停线。pass 按改动范围分四类（`include/grhsim/pass/pass.hpp` 的
`PassKind`）：**分析**（只读不改）、**语义改写**（增删改 G/Init 等语义分量）、
**元数据改写**（只加注解）、**后端映射**（只推进 mapping，不碰语义分量）。还有一类
**发射**（只读消费模型、产出文件）。这条边界很重要：语义改写会让已生成的 mapping
失效（mapping 引用具体的 op/value，图一变引用就悬空），所以流水线被刻意安排成
"先把语义改完、封板，再一次性做映射"。

**mapping 与 stage。** mapping 是后端记录的"实现选择"：状态放在哪块内存、op 分成
哪些函数、按什么顺序执行。它只决定"怎么算"，不改变"算什么"。CPU 后端的 mapping
（`CpuBackendMapping`）分阶段构建，每完成一个 pass 就推进到一个新的 **stage**（如
`GeneralNodes`、`PhaseSchedule`），后一个 pass 以前一个的 stage 为前置条件。

**相位（phase）。** 仿真一轮求值时，op 被分成四组按固定顺序执行：
**P_event**（边沿检测：判断时钟等事件信号有没有出现上升/下降沿）、
**P_general**（通用计算：组合逻辑与寄存器/锁存器写入，是主体）、
**P_mem**（大数组 memory 的写入，单独成组以便按优先级原地提交）、
**P_output**（收敛之后刷新对外输出、跑 `$strobe`/`$monitor` 一类任务）。
相位归属在 B 段完成，之后不再改变。

**活动度仿真与超节点。** 生成代码的核心优化思想是"只算变化的部分"：输入没变、
状态没变，相关逻辑就跳过。要做到这一点，需要把 General 相的海量 op 切成若干
**超节点（supernode）**作为激活/跳过的粒度，并配套"谁的变化唤醒谁"的激活表。
超节点的编号、激活表、任务序列都是 C 段的产物。

**封板（seal）。** B 段最后一步 `grhsim.verify --seal semantic` 给语义层盖章：相位
归属完整、旧的事件注解形态已无残留。封板之后不允许再有任何语义改写，C 段只读
语义、只写 mapping，单向推进、绝不回头。这是当前流水线最重要的结构性约定
（旧管线"映射—再改语义—再映射"的往返已被拆除）。

## 3. 起点：GRH 侧预处理与 lowering

### 3.1 上游：从层次化 GRH 到平坦 GRH

进入本文流程之前，GRH IR 上先跑一串结构变换（`scripts/wolvrix_xs_grhsim_ir.py`
的 `GRH_PIPELINE`，实现在 `wolvrix/lib/transform/`）：

| 顺序 | pass | 一句话作用 |
| --- | --- | --- |
| 1 | `xmr-resolve` | 解析跨模块引用（XMR），把层次化引用落到本地 |
| 2 | `memory-read-retime` | 调整 memory 读时序形态 |
| 3 | `multidriven-guard` | 处理多驱动信号 |
| 4 | `blackbox-guard` | 给黑盒模块补守卫 |
| 5 | `latch-transparent-read` | 处理锁存器透明读 |
| 6 | `hier-flatten` | **展平**：层次化模块图 → 单张平坦图（本文流程的起点） |
| 7 | `comb-loop-elim` | 消除组合逻辑环 |
| 8 | `simplify`（2 态语义） | GRH 侧化简 |
| 9 | `memory-init-check` | 检查 memory 初始化完备性 |

这些属于 GRH IR 侧，不是本文主体；列出它们是为了说明平坦图是怎么来的。

### 3.2 lower_grhsim：结构图 → 仿真行为模型

`session.lower_grhsim(..., logic_domain="2-state")`（实现
`wolvrix/lib/grhsim/convert/grh_to_grhsim.cpp`）把平坦 GRH 图一次性转成初始
`GrhSimModel`：电路对象归入 I/O/S，计算与读写归入 G，初值归入 Init，并按 core 方言
落地。两个值得知道的细节：

- 对没有驱动源但仍被引用的两态 logic 值，lowering 会显式补一个同位宽的零常量
  producer（`core.compute.constant`），与 legacy 二态仿真的零初始化一致；四态或
  非 logic 的此类值直接报错。
- GRH 图的 `declaredSymbols`、`generateGroups` 被原样携带为只读元数据，并为能解析
  到存活实体的声明建立 `declProvenance`（声明 → 实体的来源记录）。它们只是来源
  注解，不参与仿真语义；生产流程一律开启 `keep_origins` 与 `keep_declared_symbols`。

转换完成后先跑一次 `grhsim.verify` 做体检，确认模型结构合法，随后进入 A 段。

## 4. A 段：全图优化（语义层，6 个 pass）

目标：在不考虑任何后端的情况下，把语义图本身化简、整理到"形状规整"——冗余消除、
散碎的位级寄存器/逻辑合并成宽操作、被 RTL 综合打散的表恢复成数组。这一段全部改
写语义图，因此必须在任何 mapping 建立之前做完。编排见
`scripts/wolvrix_xs_grhsim_ir.py` 的 `CPU_SEMANTIC_PIPELINE`。

### A1 `grhsim.canonicalize-compute` —— 归一化

- **职能**：把图整理成规范形态，让后续所有模式匹配看到统一输入。做四件事：消除
  同类型的赋值链（`x -> assign y -> assign z` 直接把 z 的消费者接回 x）；拓扑序
  上共享完全相同的纯计算（CSE，可交换运算按操作数编号排序，乱序写法也能合并）；
  应用代数恒等式（`add(a,0)→a`、`mul(a,0)→0`、`mux(常量条件)` 选分支等）；折叠
  同源连续切片的 concat（`concat(slice(x,hi),…,slice(x,lo))` 收回成 x 或单个
  slice）。
- **起点**：lower + verify 之后的初始模型（无相位、事件注解内联、寄存器逐位）。
- **终点**：语义上等价但更规整的图；赋值链、重复计算、恒等式包装被清除。语义
  改写类 pass。

### A2 `grhsim.reg-to-mem` —— 把打散的寄存器族恢复成表

- **职能**：RTL 前端常把"按地址读写的一组寄存器"（寄存器堆、小表）综合成一堆
  独立标量寄存器加一串地址译码 mux。该 pass 反向识别这类模式：地址译码 guard
  （`enable && addr==i`）、零回退 mux、全 1 掩码，把兼容的标量状态族重新合并成
  一个数组状态。写侧归并为 `memWriteSeq`（一个 op 内按优先级排列的有序写三元组，
  同地址后写覆盖先写）/`memWrite`/`memFill`，读侧压缩成按下标的 `memRead`。
  动机：地址译码写序列比逐寄存器 mux 更新链省存储、省更新。
- **起点**：A1 归一化后的图；要求候选族元素是两态类型、常量初始化，不依赖 RTL
  模块名。
- **终点**：出现 `core.array` 类型的数组状态与 mem 系读写 op；被合并声明的
  `declProvenance` 以 Merged 形式重定向到数组元素。语义改写类。参数如
  `--min-element-count`（默认 4）、`--report`。

### A3 `grhsim.comb-pack` —— 同构组合逻辑打包

- **职能**：设计里常有几十条结构完全相同的组合逻辑"车道"（lane），比如逐位
  译码、逐位比较。该 pass 按结构签名把同构 lane 找出来，合并成一条宽的逐位
  逻辑：叶子 concat 成宽值、内部 op 加宽、mux 降为掩码选择；原来的 lane 根改
  从宽结果上切 slice。动机：一条宽运算替代几十条标量运算，op 数量大幅下降。
  可利用声明来源（`declProvenance`）发现与排序 lane。
- **起点**：A2 之后的全图；候选根来自声明指向的值、output.write 的输入、各
  状态/memory 写口的数据 operand。
- **终点**：同构 lane 被宽操作取代。语义改写类。会拒绝跨根依赖（否则造出组合
  环）、相位不一致等情形；参数有 `--min/max-group-size`（默认 4/16）等。

### A4 `grhsim.pack-bit-registers` —— 一位寄存器打包成字

- **职能**：把共享同一控制签名（同一个 enable、同一个 mask、同一组事件沿）的
  2–64 个一位寄存器合并成一个标量字寄存器：写入端 concat 数据、replicate 掩码、
  一次 `regWrite` 完成；读出端改为对打包字的 `sliceStatic`。动机：一位寄存器各自
  提交代价高，打包后一次提交一整字（以更多计算换更少提交，收益经基准验证）。
- **起点**：A3 之后的全图。决策只看原始事件注解（`event_edges`）加读写引用
  分析——这要求它必须排在 B2 事件降级**之前**。
- **终点**：一位寄存器成组消失，出现打包字状态；逐 bit 读变成字切片（这正好给
  A5 里 canonicalize-compute 的 concat 折叠制造了原料）。语义改写类，幂等。

### A5 `grhsim.simplify(scope=whole)` —— 全图不动点化简

- **职能**：把一组化简子 pass 按固定顺序编成一轮，反复执行直到整轮无变化
  （不动点）或达到轮数上限（默认 8，未收敛也正常返回并告警）。固定子序列：
  `const-fold`（常量折叠）→ `canonicalize-compute`（归一化/CSE/恒等式/concat
  折叠）→ `bitwise-predicates`（1 位 `logicAnd/logicOr` 降为按位 `and/or`，
  让发射端不用引入短路分支）→ `bitwise-muxes`（1 位 `mux` 降为 `bitSelect`
  纯位表达式）→ `mux-chain-fold`（`mux(c0,a0,mux(c1,a1,…))` 优先链折成单个
  `prioritySelect`）→ `used-bits`（反向"实际用到哪几位"分析：高位无人观测的
  值按更窄类型重建，顺带清掉死锥）。各子 pass 的匹配/拒绝规则见
  `wolvrix/docs/grhsim_ir/passes/` 下各自文档。
- **起点**：A4 之后的图。`whole` scope 表示每轮对整张图执行一遍子序列。
- **终点**：图收敛到局部最优形态。语义改写类。

### A6 `grhsim.select-state-stores` —— 存储分类（语义层收尾）

- **职能**：给每个状态贴一个存储类别标签：`regLatch` 或 `mem`。两类在语义上都
  是"写下一值、轮末才生效"（NBA 语义），区别只在实现与成本：regLatch 类整块
  双缓冲拷贝提交，mem 类按单元原地更新。分类规则刻意简单：只有 `core.array`
  且线性字节数 ≥ `--mem-min-bytes`（默认 64）才归 mem，其余一切（任意宽度标量、
  小数组、real/string）归 regLatch。这是全流水线**唯一**做存储分类决策的地方，
  下游一律只消费标签、不再决策。
- **起点**：A5 收敛后的图（用优化后的最终形态做决策才准）。
- **终点**：每个 state 带上 `storeClass` 注解；**不增删改任何 op/value**——这是
  元数据改写类 pass。B5 与 C3 是它的两个消费者。

## 5. B 段：相位分区（仍是语义层，7 个 pass）

目标：把"一轮求值里每个 op 属于哪个相位"这件事在语义层彻底定下来，并把事件
检测、输出刷新从主图中剥离成独立结构。这一段仍不改后端映射（mapping 还不存在），
最后一步给语义层封板。编排见 `CPU_PARTITION_PIPELINE`。

### B1 `grhsim.classify-event-inputs` —— 标记纯事件输入

- **职能**：有些输入端口只当时钟/复位等事件信号用，从不参与数据运算。该 pass
  把这种输入的 `core.input.read` 打上 `event_only=true` 标记，使后续不必为它们
  维护数据变化跟踪，改由事件相位统一做边沿检测。
- **起点**：A 段之后的图。判定标准：结果只出现在事件敏感 op 的事件槽位上；
  有任何数据用途（比如复位信号还兼作 mux 选择）就不标。
- **终点**：纯事件输入带注解。只加注解不改图（元数据改写类），幂等。必须排在
  B2 前，因为 B2 克隆事件锥时会带上这个标记。

### B2 `grhsim.lower-edge-detect` —— 事件检测独立成相位

- **职能**： lowering 之后，事件信息以内联注解形态挂在消费者 op 上
  （`event_edges` 参数 + 尾部事件操作数），每个消费者各自判定边沿。该 pass 把
  同一 `(事件信号, 沿方向)` 的判定去重合并：每个这样的聚类生成一个
  `core.event.edgeDet` op（归入 P_event，内部保存上一轮事件值 prevEvent），原
  消费者删掉事件操作数、改为引用聚类编号（`event_acts`）。同时把判定所需的
  事件锥克隆进 P_event，并清扫遗留的边沿历史状态。
- **起点**：B1 之后的图（仍是原始事件注解形态）。
- **终点**：出现 P_event 相位的 edgeDet 结构，消费者共享判定结果。语义改写类，
  幂等。edgeDet 的 prevEvent 初值由静态求值得到，求不出来回退为零并计数。

### B3 `grhsim.extract-output-cones` —— 输出逻辑剥离到 P_output

- **职能**：喂对外输出的那部分组合逻辑没必要参与主循环迭代。该 pass 把每个
  `core.output.write` 的生产者锥克隆进 P_output，原锥里只服务于输出的 op 由
  定点死代码清扫移除（与主图两用的 op 保留在原侧）。
- **起点**：B2 之后、B4 之前。
- **终点**：输出锥归 P_output；验证器随后要求 Output 相位的 op 只能消费 Output
  相位的值。语义改写类，幂等。

### B4 `grhsim.migrate-timeslot-tasks` —— 时隙任务迁入 P_output

- **职能**：`$strobe`/`$monitor` 这类系统任务应该在每轮求值收敛后、按仿真时间
  槽执行。该 pass 把它们迁入 P_output：带事件的任务分配 `timeslotFlag` 编号；不
  带事件的任务补建"上一轮操作数"历史状态和变化检测（操作数变了才触发）。
  其余系统任务不动。
- **起点**：B2、B3 之后（消费降级后的事件形态；还带旧注解的任务原样跳过）。
- **终点**：时隙任务带 flag 归 P_output。语义改写类。

### B5 `grhsim.split-phases` —— 相位总归属

- **职能**：给所有还没有相位的 op 一次性打上相位标签：reg/latch 写和其余普通
  op 归 P_general；edgeDet 归 P_event；output.write 归 P_output；四个 mem 写
  （memWrite/memFill/memAssign/memWriteSeq）看目标状态的 A6 存储类别——mem 类
  归 P_mem，regLatch 类（含小数组）归 P_general。注意区分：这里说的是语义层
  pass `grhsim.split-phases`；旧管线里还有一个 mapping 侧 pass
  `cpu.st.split-phases`，已在 M5d-6 删除，不要混淆。
- **起点**：B1–B4 之后，且 A6 已完成存储分类。
- **终点**：全部 op 相位无遗漏。只打标签、不改图结构（元数据改写类）；二次
  运行为空操作。这是 C 段的直接契约——C 段只消费 `op.phase`，绝不重新归因。

### B6 `grhsim.simplify(scope=phase)` —— 逐分区化简

- **职能**：与 A5 是同一个 pass、同一套子序列，但 `phase` scope 每轮按
  Event→General→Mem→Output 逐分区各执行一遍，且只许改写本分区内的 op：
  跨分区引用的值/状态不合并、不窄化、不删除（分区接口必须保持完整），used-bits
  分析仍按全图跑、把分区外的消费者当作"全部位都被使用"。动机：相位归属已固定，
  分区内可以放心化简，但绝不能碰跨分区接口。
- **起点**：B5 之后的图。集成侧有调试开关
  `XS_WOLF_GRHSIM_IR_PHASE_SIMPLIFY=0/1`。
- **终点**：各分区内部收敛，分区边界原样。语义改写类。

### ~~B7 `grhsim.clone-shared-compute`~~（已撤除，V3-M3）

该 pass 曾在语义层"预测"未来的超节点边界并克隆共享计算以消边界（用
`predictGeneralBoundaries` 预演 C1 的锥吸收规则）。因层次倒置（语义层依赖后端
划分规则、需专门测试维持"预测==实际"）、预测性浪费（XS 实测高估 19%）等设计
缺陷，已于 V3-M3 整体撤除；其职责由 C 段微调 pass **C2.5
`cpu.st.clone-shared-boundaries`** 基于真实超节点边界接管（见 §6 C2.5）。
B 段至此不再有任何边界感知逻辑。

### B8 `grhsim.verify --seal semantic` —— 封板

- **职能**：不做任何改写，只做检查并盖章：相位归属完整无遗漏、全图不再有
  `event_edges` 残留、P_mem 写的操作数确实产自 P_general。盖章意味着：此后
  只允许后端映射 pass，不允许再改语义图——**唯一例外**是经框架注册的 C 段
  语义微调 pass（当前仅 C2.5 `cpu.st.clone-shared-boundaries`，经
  `commitSemanticMicroMutation` 申报，revision++ 但不整份失效 mapping）。
- **起点**：B6 之后。**终点**：带语义封板的模型，进入 C 段。

## 6. C 段：CPU 映射（9 个 pass，单向推进一次）

这一段在封板模型上从零建立唯一一份 CPU mapping。九个 pass 各推进一个 stage，
前一个的产出是后一个的前置，**只运行一次、单向不回退**；除 C2.5（注册的语义
微调 pass，就地复制廉价共享计算并同步维护分区树）外全部只写 mapping 字段、
不碰语义分量，因此互相之间不存在失效问题。编排见 `CPU_MAPPING_PIPELINE`；
stage 的先后顺序以 `cpuMappingStageRank`（`include/grhsim/ir/model.hpp`）为准——
枚举数值顺序是历史遗留，不代表流水线顺序。

C 段围绕两样东西展开，先在这里认识它们：

- **分区树（PartitionTree）**：mapping 里的树形结构。root 下固定四个相位分枝；
  General 分枝挂若干**超节点**（活动度粒度）和尾随的 **EmitFunction** 叶子
  （代码组织粒度，每个只记录一段连续超节点编号区间）；Event/Mem/Output 分枝
  各塌缩成一个 EmitFunction。
- **七具名 store**：模型里所有持久数据在 C++ 侧的"安身之处"——regLatch 双缓冲
  （`regLatchStore`/`regLatchStoreNext`）、mem store、boundary（输入端口值与
  跨超节点值的持久槽）、prevEvent、eventAct（边沿判定结果位）、
  timeslotTrigger、activeFlags（每个超节点一位的激活旗标位图，V3-M1 起
  `Array(UInt64, ceil(N/64))`）。

### C1 `cpu.st.build-general-nodes` —— 建分区树骨架

- **职能**：从零初始化 mapping：建 root 和 Event/General/Mem/Output 四个平铺
  分枝；Event 枝装锥拓扑序（edgeDet 殿后）、Mem 枝按 op 编号、Output 枝拓扑序；
  General 相做"锥吸收"形成 node——一个 op 的结果若被唯一消费者使用就吸收进
  对方的 node，被多方共享或消费者落在别处则自立门户；sink op（寄存器/锁存器
  写、General 相 mem 写、无返回值的任务/DPI）各自成单例 node。这是唯一的
  mapping 初始化点，重跑即丢弃重建。
- **起点**：B8 封板模型；发现无相位 op 即报错并指向 B5。不要求任何前置 mapping。
- **终点**：mapping 推进到 `GeneralNodes` stage。

### C2 `cpu.st.merge-general-supernodes` —— 合并超节点、固定编号

- **职能**：把 C1 的 node 聚成超节点，定下活动度粒度，并且**就此固定超节点编号**
  （General 分枝子节点的顺序，0..N-1）——此后所有 pass 和 emit 共用这套编号，
  永不重排。非 sink node 走合并框架（聚类初始化 + 三种合并模式 + 商图合法性
  检查 + 动态规划分段成本模型，`--max-op-in-compute-supernode` 默认 128）；
  sink node 不进框架，按规范事件签名聚类：空签名的是 SinkEscape（每轮无条件
  点火，用于门控时钟的 latch 等场景），非空的是 SinkEvent（按 eventAct 签名
  组合门控），两类互不合并。
- **起点**：`GeneralNodes` stage。
- **终点**：`GeneralSupernodes` stage；每个超节点带 `eventActs` 与类别标注。

### C2.5 `cpu.st.clone-shared-boundaries` —— 克隆跨边界的共享计算（V3-M3 起）

- **职能**：A 段 CSE 合并出的共享计算，若消费者被 C2 切进不同超节点，共享点
  就成为一条跨超节点**边界值**——落 boundaryValueStore 槽位、每轮"真变化"
  比较、变化后激活传播，三笔运行时开销。该 pass 给每个消费超节点各克隆一份
  私有副本（粒度：每消费超节点一份），克隆被锥吸收进消费者内部、不再成为
  边界；死源删除并同步 op-id remap 分区树。只克隆**廉价且双射**的候选
  （单结果、两态、1–64 位、`not`/`logicNot`/`xor`/`add`/`sub` 且恰一个常量
  操作数），双射保证删掉边界上的变化比较后点火逐轮等价。
- **为什么在这里**：它是 B7（`grhsim.clone-shared-compute`，已撤除）的正当
  继任——B7 在语义层"预测"边界，层次倒置且高估 19%；C2.5 直接消费 C2 决定
  的**真实**超节点边界（`sixPhaseBoundaryValues`），下游 C3–C8 尚未执行，
  mapping 无需失效重建，只需就地维护。这是框架唯一注册的 C 段语义微调 pass，
  经 `commitSemanticMicroMutation()` 申报（revision++ 但保留 mapping），
  pass 后 verify 以全相位归属 + 分区覆盖为硬护栏。
- **起点**：`GeneralSupernodes` stage。
- **终点**：边界值集合被削减（XS 实测 candidates=35,420、boundary_hits=25,268、
  cloned=40,702、boundary_values_eliminated=22,048），stage 不变。

### C3 `cpu.st.layout-named-stores` —— 数据布局与命名

- **职能**：为所有持久数据选 CPU 物理表示、分配 store、完成全部命名（emit 只
  消费名字、不再起名）。**零分类决策**：状态归哪个 store 只读 A6 的
  `storeClass` 标签，遇到未分类状态直接报错并指回 A6。输入端口、跨超节点值、
  General→Mem 的写参数进 boundary store（写参数槽命名如
  `<mem>__w<idx>__<enable|addr|data|mask>`）；activeFlags 的位下标就是 C2
  超节点编号（V3-M1 位图化：每超节点 1 bit，64 位一个字）。
- **起点**：`GeneralSupernodes` stage（前置要求已降低，不再等函数打包）。
- **终点**：填好 `mapping.dataLayout`（物理类型表 + 七具名 store），推进到
  `LayoutNamedStores` stage。

### C4 `cpu.st.build-event-activation-map` —— 事件激活表

- **职能**：回答"某个边沿聚类命中后，要唤醒哪些超节点"。对每个事件聚类 act，
  列出包含该 act 的**非 sink** 超节点位图（位 i 就是 C2 编号 i）；运行时
  P_event 把命中 act 的位图直接 OR 进激活标志。sink 超节点不配位图：
  SinkEvent 在调用点自查 eventAct 签名，SinkEscape 本来就每轮跑。
- **起点**：`LayoutNamedStores` stage。
- **终点**：填好 `schedule.eventActivation`，推进到 `EventActivationMap` stage。

### C5 `cpu.st.build-mem-write-plan` —— mem 写计划

- **职能**：为 P_mem 相位服务：给每个 mem 类数组的写口定优先级（按 op 编号，
  同地址后写覆盖先写，保持源程序序），并建立"写 → 该数组的 General 相读者"
  激活表，使 P_mem 原地提交后能精确唤醒读者（地址是常量时按行精确激活，动态
  地址保守地在任意写时激活）。无事件门控的写口标记 `eventFree`，每轮都跑、
  靠单元变化检测收敛。
- **起点**：`EventActivationMap` stage。
- **终点**：填好 `schedule.memWritePlan`，推进到 `MemWritePlan` stage。

### C6 `cpu.st.pack-general-functions` —— 函数打包

- **职能**：把超节点组织成发射侧的代码单元，分两步。①每个超节点内部按估计
  行数切成连续 chunk（`--helper-max-estimated-lines` 默认 2048），驱动 emit 把
  大超节点拆成 `sn_<i>__c<j>` 成员函数，跨 chunk 的局部值经栈上 spill 帧
  （`SnFrame<i>`）传递。②把 C2 编号连续的一段超节点区间记为一个 EmitFunction
  尾随叶子（`supernodeRange` 属性，区间铺满 [0,N)）——**不重挂超节点**，编号
  不因函数边界而变；`--target-batch-count`（默认 64）是函数数量的软目标。
  Event/Mem/Output 三枝各塌缩为恰好一个 EmitFunction。
- **起点**：`MemWritePlan` stage（注意：它排在 C5 之后，尽管 stage 枚举数值
  更小）。
- **终点**：`GeneralFunctions` stage。EmitFunction 决定任务粒度，超节点决定
  活动度粒度，两者解耦。

### C7 `cpu.st.build-phase-schedule` —— 相位调度

- **职能**：把分区映射到执行顺序与激活依赖。产出三张 fanout 表（目标一律只
  含非 sink 超节点、按 C2 编号排序去重）：`inputFanout`——某个输入变了唤醒
  哪些超节点（纯事件输入无条目）；`computeSupernodeFanout`——某个 boundary
  值真变化唤醒哪些消费者超节点；`commitStateFanout`——某个 reg/latch 状态真
  变化唤醒哪些读者超节点，并决定是否还要再迭代一轮。另有 `timeslotTriggers`
  （Output 相时隙任务的触发展开）和单核 task 序列：P_event（每轮扫描提交）→
  每个 General EmitFunction 叶子一个数据门控 task → P_mem（每轮扫描提交）→
  P_output（轮次循环外，收敛后执行一次）。
- **起点**：`GeneralFunctions` stage。
- **终点**：`PhaseSchedule` stage——首个"完整"终态。

### C8 `cpu.st.plan-translation-units` —— 翻译单元计划

- **职能**：XiangShan 规模的模型若只 emit 一个 .cpp，编译时间会失控。该 pass
  把 emit 输出组织成规模受控的多翻译单元：按固定块流（Core → Init → Event →
  GeneralScan → Supernode → Mem → Output → Dump）把块按估计行数装箱
  （`--chunk-max-estimated-lines` 默认 2048、`--unit-max-estimated-lines` 默认
  32768），每个单元一个 `tu<N>`。超单元上限且 helper chunk ≥2 的超节点
  （典型：{posedge clock} 巨簇）再拆为 wrapper-only Supernode 块 + 若干
  **SupernodePart** 块摊到多个 TU（V3-M2 起；part→helper 区间由共享 helper
  `cpuSupernodePartRanges` 在 C8 与 emit 双侧确定性重放）。并行的只是
  **C++ 编译**，仿真执行仍是单线程顺序执行。
- **起点**：`PhaseSchedule` stage；对已规划 mapping 重跑会确定性地丢弃重排
  （用于旧 checkpoint 重新发射）。
- **终点**：写入 `translationUnits` payload，推进到终态 `TranslationUnits`——
  emit 唯一接受的 stage。

## 7. 发射：`cpu.st.emit-cpp`

- **职能**：只读消费完整 mapping，逐翻译单元输出一个 `.cpp`，外加一个共享头
  （端口、store、成员与块函数声明、spill 帧结构）、一份不变的 runtime 头，以及
  承载完整源文件清单的 `Makefile`（`make -j` 并行编译，链接为单一静态库）。
  开启波形时追加 `*_wave_<g>.cpp` 与 vendored libfst 规则。DPI import 声明不进
  公共头，由引用它的单元各自声明。
- **起点**：mapping 处于 `TranslationUnits` 终态，且语义封板后语义 revision 未
  再变化（否则 mapping 已失效，必须重建）。**输出目录必须为空**。
- **终点**：一组 C++ 源文件 + Makefile，经编译得到仿真可执行/静态库。波形自
  M5d-8 起以 declared-symbols 模式提供（`--waveform declared-symbols`）。

## 8. 运行时一瞥：pass 产物如何被使用

生成的仿真器每次 `eval()` 固定外部输入后按轮次迭代，直读上面各 pass 的产物：

```text
加载输入；按 inputFanout（C7）差分，置位对应超节点的激活标志
重复执行轮次：
  P_event：edgeDet（B2 形态）判定边沿写 eventActStore、采样 prevEvent；
          命中 act 按 eventActivation（C4）把对应超节点置位
  P_general：按 task 序列（C7）与 C2 编号顺序分三类点火超节点——
             非 sink：dataActiveFlag 位图（C3 activeFlags，V3-M1 起每超节点
             1 bit）按 64 位字外层跳过扫描、字内逐位清位点火；
             SinkEvent：调用点按 eventActStore 签名析取门控；
             SinkEscape：每轮无条件点火；三类体内 reg/latch 写均以 NBA
             方式提交 regLatchStoreNext
  P_mem：按 memWritePlan（C5）的优先级原地提交 mem 类数组
  P_publish：regLatchStoreNext 整块提交回 regLatchStore；状态真变化经
             commitStateFanout（C7）唤醒读者，决定要不要再来一轮
  收敛则退出轮次循环（上限 100000 轮，超限报错）
P_output：收敛后执行一次，刷新对外输出、跑时隙任务（B3/B4 形态）
```

可以看到：A/B 段决定"算什么、谁在哪个相位"，C 段决定"存在哪、按什么顺序、
谁唤醒谁、代码怎么切"，emit 只是忠实的翻译者。

## 9. 全程速查表

| 段 | 顺序 | pass | 类别 | 起点（前置） | 终点（产物） |
| --- | --- | --- | --- | --- | --- |
| 入口 | — | `lower_grhsim` + `grhsim.verify` | 转换/分析 | 平坦 GRH 图 | 合法的初始 GrhSimModel |
| A | A1 | `grhsim.canonicalize-compute` | 语义 | 初始模型 | 归一化图（链消除/CSE/恒等式/concat 折叠） |
| A | A2 | `grhsim.reg-to-mem` | 语义 | A1 | 寄存器族恢复为数组 + mem 系写 op |
| A | A3 | `grhsim.comb-pack` | 语义 | A2 | 同构组合 lane 打包成宽逻辑 |
| A | A4 | `grhsim.pack-bit-registers` | 语义 | A3（事件注解仍内联） | 一位寄存器打包成字 |
| A | A5 | `grhsim.simplify(scope=whole)` | 语义 | A4 | 全图化简到不动点 |
| A | A6 | `grhsim.select-state-stores` | 元数据 | A5 | 每个 state 带 `storeClass`（regLatch/mem） |
| B | B1 | `grhsim.classify-event-inputs` | 元数据 | A6 | 纯事件输入带 `event_only` |
| B | B2 | `grhsim.lower-edge-detect` | 语义 | B1 | edgeDet 聚类入 P_event，消费者挂 `event_acts` |
| B | B3 | `grhsim.extract-output-cones` | 语义 | B2 | 输出锥克隆入 P_output |
| B | B4 | `grhsim.migrate-timeslot-tasks` | 语义 | B3 | 时隙任务入 P_output |
| B | B5 | `grhsim.split-phases` | 元数据 | B4 + A6 分类 | 全部 op 相位归属完毕 |
| B | B6 | `grhsim.simplify(scope=phase)` | 语义 | B5 | 逐分区化简，接口不动 |
| B | B8 | `grhsim.verify --seal semantic` | 分析 | B6 | 语义层封板（此后只许 mapping + 注册的 C 段微调） |
| C | C1 | `cpu.st.build-general-nodes` | 映射 | 封板模型 | `GeneralNodes`：四分枝 + General node |
| C | C2 | `cpu.st.merge-general-supernodes` | 映射 | C1 | `GeneralSupernodes`：超节点编号固定 |
| C | C2.5 | `cpu.st.clone-shared-boundaries` | 映射+语义微调 | C2 | 跨边界共享计算按真实边界克隆（B7 继任） |
| C | C3 | `cpu.st.layout-named-stores` | 映射 | C2.5 + A6 标签 | `LayoutNamedStores`：物理类型 + 七具名 store |
| C | C4 | `cpu.st.build-event-activation-map` | 映射 | C3 | `EventActivationMap`：事件激活位图 |
| C | C5 | `cpu.st.build-mem-write-plan` | 映射 | C4 | `MemWritePlan`：写优先级 + 读者表 |
| C | C6 | `cpu.st.pack-general-functions` | 映射 | C5 | `GeneralFunctions`：helperChunks + 函数区间 |
| C | C7 | `cpu.st.build-phase-schedule` | 映射 | C6 | `PhaseSchedule`：三 fanout + task 序列 |
| C | C8 | `cpu.st.plan-translation-units` | 映射 | C7 | `TranslationUnits`：TU 装箱计划（终态） |
| 发射 | — | `cpu.st.emit-cpp` | 发射 | C8 终态 + 空输出目录 | 多 .cpp + 共享头 + runtime + Makefile |

## 10. 参考索引

- 流水线编排：`scripts/wolvrix_xs_grhsim_ir.py`（`CPU_SEMANTIC_PIPELINE` /
  `CPU_PARTITION_PIPELINE` / `CPU_MAPPING_PIPELINE`）
- 权威流程规范：`wolvrix/docs/grhsim_ir/flows/cpu-st.md`
- 模型与概念定义：`wolvrix/docs/grhsim_ir/overview.md`、`dialects/core.md`
- 各 pass 详细规则：`wolvrix/docs/grhsim_ir/passes/*.md`
- 后端 mapping 与 emit 约束：`wolvrix/docs/grhsim_ir/backends/cpu.md`
- pass 框架实现：`wolvrix/lib/grhsim/pass/pass.cpp`（注册表与执行/验证规则）
- C 段实现：`wolvrix/lib/grhsim/backend/cpu_partition.cpp`（C1/C2/C6）、
  `cpu_clone_shared.cpp`（C2.5）、`cpu_layout.cpp`（C3）、
  `cpu_schedule.cpp`（C4/C5/C7）、
  `cpu_emit_plan.cpp`（C8）、`cpu_phase_emit.cpp`（emit）
  ——均位于 `wolvrix/lib/grhsim/backend/`
