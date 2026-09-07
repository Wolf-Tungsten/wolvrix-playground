# GrhSIM IR CPU Backend 重规划：活动度调度 + Compute/Commit + 多时钟域

- 日期：2026-09-05
- 状态：规划草案
- 范围：新一代 GrhSIM IR（`wolvrix/lib/grhsim`，`wolvrix/docs/grhsim_ir/`）的 CPU backend（`CpuBackendMapping` + emit，即 infrastructure-plan 的 M5/M6）；不涉及 GRH legacy 路线本身的改动。

## 1. 背景与目标

legacy 路线（GRH `activity-schedule` pass + `grhsim_cpp` emit）已经沉淀了一套成熟且经过性能验证的活动度调度体系：compute/commit 两阶段 fixed-point、supernode activity bitset、event edge slot、input/posedge fullpass 快路径。新一代 GrhSIM IR 的 CPU backend 尚未实现。

本规划回答一个问题：**新 IR 的 CPU backend 如何完整承接 legacy 的活动度调度能力，并原生支持多时钟域**，而不是退回 gsim 的简单模式（单时钟 step、`$NEXT` 扫描头提交、无时钟域概念，`reference/gsim/src/clockOptimize.cpp` 对多时钟只能 warning 退化或 Panic）。

目标：

1. compute/commit 两阶段是 backend 结构的一等层次，不是代码生成技巧。
2. 多时钟域原生支持：commit 按域分组、域级动态门控，慢速域不在每次 eval 空扫。
3. 单时钟设计语义逐点等价于 legacy 现状（开销只减不增），复用现有 10k/50k gate。
4. 调度结果全部物化进 `CpuBackendMapping`，禁止再走 session 暗传（infrastructure-plan §12.3 的硬性要求）。

## 2. 核心思路：结构复用 PartitionTree，新概念只进 SchedulePlan

`PartitionTree` 已是通用的层次化 op 分组结构（叶分区 = node，非叶分区 = supernode，`backends/cpu.md` §3）。审视 legacy 的所有调度/发射结构，会发现**没有一个是结构上的新概念**，全部对应树的一个层次：

```
root
└─ compute（phase 标注）                          ← cpu.st.split-phase
│  └─ 函数分区（生成函数边界）                     ← cpu.st.pack-emit-functions
│     └─ word 分区（active word：8 supernode/字）  ← cpu.st.pack-active-words
│        └─ supernode（活动度调度单元）            ← cpu.st.merge-compute-supernodes
│           └─ node（叶，直接含 ops）              ← cpu.st.build-compute-nodes
└─ commit（phase 标注）
   └─ 事件域分区（event_gate 标注）                ← cpu.st.form-event-domains
      └─ 函数分区（生成函数边界，同 compute）
         └─ commit supernode（叶/子树）
```

每个层次的语义只有一个，几处有意的取舍：

- **函数分区的唯一语义是"生成函数边界"**（eval 直接调用的单元，控制单函数体积）。fullpass 首版不实现（§4.10 的决策与依据）；若未来引入，其特化单元跟随函数边界，不构成第二种语义。
- **TU 不进 mapping**。`.cpp` 文件划分是纯发射期打包（legacy 的 `batchesPerCpp` 选项），一个文件需要混装不同域/不同位置的函数分区，与树层次正交；TU 归属由 `cpu.st.emit-cpp` 按选项决定并写入 stats，不占用分区标注。
- **word 层只存在于 compute 枝**。它是 active bitmap 的物理分组（8 bit/字），运行时整字零测试一次跳过 8 个 supernode（快速激活判断），并支持同字内局部 flags 短链。commit 枝的调度单元由事件域门控接管，legacy 中 commit "word" 本就退化为 per-supernode（`buildScheduleBatches` 对 commit phase 每个 supernode 强制开新 word），不再保留这一层。

因此本规划**不引入 Domain、函数、word 等新的 mapping 实体**：

- **phase、时钟域、函数边界、word、supernode、node 都是 PartitionTree 的层次**。唯一对 `PartitionTree` 的扩展是给分区附带少量语义标注（见 §4.1–§4.6），标注是已有结构的属性，不是新实体。
- **真正的新概念都在 SchedulePlan（执行语义层）**：task 的**执行条件**（activity bit / eventDomainArm+event guard / always scan）与三张**激活辅助表**（`inputFanout`、`computeSupernodeFanout`、`commitStateFanout`，见 §4.8）。这正好填补 infrastructure-plan §12.3 标注的未决项（compute/commit phase、activation fanout 如何表达；fixed-point round 不物化为数据，由 `commitStateFanout` 的命中驱动，见 §4.8④）。

## 3. 现状与差距

| | gsim（简单模式） | grhsim legacy（当前生产） | GrhSIM IR（目标载体） |
| --- | --- | --- | --- |
| 时钟模型 | 结构性单时钟；gated clock 折叠为数据使能 | 单一全局假设：harness 翻转 `clock` 输入，一次 eval = 一次输入跳变；posedge 快路径按端口名 `"clock"` 启发式 | event 是 per-op operands + `event_edges` + 每 (op,event) 历史 state，数据上已支持任意多事件 |
| 提交语义 | `$NEXT` 双命名，下一拍扫描头提交（无独立 commit 阶段） | compute/commit 两阶段 fixed-point，commit 直写 visible state | IR 语义是 NBA 式 `eval_G` + 静止投影；两阶段属 backend 自由度 |
| 调度结构 | supernode 扁平列表 + cppId bitset | compute/commit supernode + word/batch/TU 发射层次 + 按 canonical event key 的 commit 分桶（NO0029/NO0092） | `PartitionTree` 通用层次结构，**标注与执行语义空白** |

关键差距三条：

1. **分区无语义标注**：`Partition` 目前只有 `parent/children/ops`，无法表达"这棵子树属于 commit phase、由这组 event 边沿门控、按这个 active word 跳过"。legacy 里最接近的结构是 commit 的 canonical event key 分桶和 emit 内部的 word/batch 打包，但它们只为 codegen 形态服务，不进 mapping。
2. **SchedulePlan 无执行条件与激活语义**：`ScheduledTask` 只有 `partition + waits_for`（静态顺序），没有"何时值得执行"（activity bit / 域门控）和"执行后唤醒谁"（fanout）的表达。legacy 的 `boundaryFanoutByValue`、`stateHeadSupernodesBySymbol`、event edge slot 等都无处物化。
3. **多时钟的派生时钟**：门控/分频时钟是内部 value 而非输入，其边沿只能在 fixed-point 迭代内动态产生——这决定了域门控必须是迭代级动态执行条件（eventDomainArm 可在迭代内由 compute 置位），而非 eval 级静态分支。

## 4. 总体架构

**命名约定**：pass 名采用 `cpu.<方案>.<谓语-宾语>` 三级形式——动作必须是谓语宾语结构，避免名词式命名的歧义（如 `pack-emit-functions` 明确宾语是"生成函数边界"，而非 DPI function 或别的"func"）。本规划这一组 pass 是 CPU 后端上的**单线程活动度调度方案**，统一用 `cpu.st.*` 前缀；未来的多线程方案以 `cpu.mt.*` 独立成族，共享 `PartitionTree`/`DataLayout`/`SchedulePlan` 的结构定义，各自产出独立 mapping。

**结构约束：每个 pass 只在 PartitionTree 上生长一个层次（或只产出一个 mapping 分量），不把多个拆分动作合并在一个 pass 里**。前六个 pass 都是 `BackendMapping` kind：不碰 model（不触发 semantic revision 递增、不使 mapping 自我失效），只在 `CpuBackendMapping` 上逐层建树，每层的产物显式可见、可独立 dump，并由 PassManager 的 per-pass verify 逐层校验结构不变量。

```
GRH lowering（已完成）
  → cpu.st.split-phase               # 建 PartitionTree：root → compute | commit 两枝，确定每个 op 的 phase 归属
  → cpu.st.form-event-domains        # commit 枝内按 canonical event key 形成事件域分区，挂 event_gate 标注
  → cpu.st.build-compute-nodes       # compute 枝内构造叶 node
  → cpu.st.merge-compute-supernodes  # compute 枝内 node 聚合为 supernode（coarsen + DP 分段）
  → cpu.st.pack-active-words         # compute 枝内分配 activeId，8 个 supernode 打包一个 word 分区
  → cpu.st.pack-emit-functions       # 两枝：按函数体积把连续 word / 域内 supernode 打包为生成函数边界
  → cpu.st.layout-data               # DataLayout：object/value 存储（依赖最终分区确定 partition_local/boundary）
  → cpu.st.build-schedule            # SchedulePlan：task + 执行条件 + 三张激活辅助表
  → cpu.st.emit-cpp                  # 只读消费 mapping，生成 C++；TU 装箱在此发生
```

每一层的显式产物同时就是与 legacy 中间结果的 parity 对照点（phase 分类 ↔ legacy `supernode_kind`；事件域分区 ↔ commit 分桶统计；supernode/word/函数分区 ↔ legacy supernode/word/batch 统计）。

### 4.1 `cpu.st.split-phase`（第一层：compute | commit）

- 产物：`PartitionTree` v1——root + 两个第一层分区，携带 `PartitionAttrs.phase: compute | commit` 标注；每个 op 归属其一。
- 分类规则：commit 类 = 四种状态写口（`core.state.regWrite/latchWrite/memWrite/memFill`）；其余全部进 compute——包括 `system.task/dpi.call`（自 NO0033 起它们留在 compute 路径，side-effect 的 event guard 走 compute 内的 event 表达式，不参与后续的事件域分区）。
- 校验：commit 枝只含写口 op；两枝不互含（phase 纯净性从 legacy emitter 的运行时检查上升为树约束）。

### 4.2 `cpu.st.form-event-domains`（commit 枝内：事件域分区）

- 产物：commit 枝下插入事件域分区层——"时钟域"在结构上的落点：以 event 边沿集合（canonical event key）划分的 commit 分组。对 commit 枝内每个写口 op 收集 event operands + `event_edges`，规范化成 canonical event key（复用 legacy NO0029 的归一规则，作为本 pass 内部步骤，不单独设 analysis pass）；key 相同的 op 归入同一事件域分区，挂标注：

```text
PartitionAttrs（在 §4.1 的 phase 上扩展）
  phase: compute | commit
  event_gate: { values: ValueId[], edges: [posedge|negedge], source: input | derived }?
      # 仅 commit 事件域分区携带；缺省 = general（每轮扫描）
```

- key 分类：`Edge`（边沿域）/ `Level`（latch 电平使能）/ 无法归一（并入 general 分区）。`source` 区分 `InputClock`（event value 全为 graph input，eval 入口即可判定）vs `DerivedClock`（含内部 value，迭代内动态判定）。
- 域内按 topo 序把写口 op 切成 commit 叶分区（chunk 大小上限沿用 NO0092 的 `max-op-in-commit-supernode` 结论）。
- CDC 只标注不处理：reader 与 writer 不同域的 state 记入报告供调试，语义仍按 IR 的 NBA 规则（读旧写新）。
- 校验：同域内所有 op 的 canonical key 相同；事件域分区完整覆盖 commit 枝。

### 4.3 `cpu.st.build-compute-nodes`（compute 枝内：叶 node）

- 产物：compute 枝的叶分区层——以 boundary value 切分构造 compute node（移植 legacy `activity_schedule.cpp` 的 compute node 构造路径），每个叶分区直接含 ops。

### 4.4 `cpu.st.merge-compute-supernodes`（compute 枝内：supernode 层）

- 产物：compute 枝的中间层——node 聚合为 supernode，移植 legacy 的 coarsen + DP 分段主路径；聚合时控制跨分区边密度（NO0010 的稠密 hub 教训）。
- 校验/可观测：supernode 数量、规模分布、跨分区边数可 dump，与 legacy 统计对照。

### 4.5 `cpu.st.pack-active-words`（compute 枝内：active word 层）

- 产物：compute 枝内、supernode 之上的 word 分区层——按调度序给每个 compute supernode 分配 activeId（决定其在 activity bitset 中的位址），每 8 个连续 activeId 打包为一个 word 分区，挂 `active_word: { word_index }` 标注；word 内预估代码体积过大时记录 helper 拆分（对应 legacy 的 `HelperChunk`/`emitAsHelper`）。
- 运行时语义（供 §4.8 的执行条件使用）：整字零测试一次跳过 8 个 supernode；同字内允许局部 flags 短链（前一 supernode 的激活在同字后序目标上当场生效，不等下一轮）。
- 校验：activeId 连续无空洞；word 分区边界与 8 对齐。

### 4.6 `cpu.st.pack-emit-functions`（两枝：生成函数边界）

- 产物：compute 枝在 word 之上、commit 枝在域内各插入函数分区层。语义只有一个：**函数分区 = eval 直接调用的生成函数边界**。动作是打包：按调度序连续累积 word / 域内 supernode，达到体积上限即封包，规则沿用 legacy `buildScheduleBatches`（`batchMaxOps / batchMaxEstimatedLines / targetBatchCount`）。
- **与 supernode 的区别**（为什么必须是一层独立结构）：supernode 是运行时调度单元——占 active bit、由值变化激活、不激活不执行，划分依据是图结构；函数分区是编译期代码组织——无门控、永远被调用、内部做 word 整字测试，划分依据是生成代码体积。两者正交：若让 supernode 兼作函数边界，其大小就被函数体积绑架（XiangShan 62,823 个 compute supernode，平铺即数万小函数，合并即单函数编译爆炸）；若让函数分区兼作调度单元，粒度太粗（一个函数含几十~几百个 supernode），活动度调度失效。gsim 也有同样的一层（`step()` 拆 `subStep0..N()`）。
- 不承载的语义：fullpass 特化单元（首版不实现，见 §4.10；若未来引入，按生成函数复制即可）；TU 归属（emit 期装箱，不进 mapping）。
- 校验：函数分区不跨 word 边界（compute 枝）/ 不跨域（commit 枝）——打包只能沿既有调度结构聚合，不能反过来切割它。

### 4.7 `cpu.st.layout-data`

无新概念：沿用 legacy 已验证布局（state 字节数组 + 分宽度 value slot 数组、按 word 分区对齐的 activity bitset、event history slot）。跨分区 value 由 `G` 的定义/使用关系推导（`cpu.md` §3 既有规则），`partition_local/boundary` 语义自动适用；eventDomainArm 数组、edge slot 属于分区运行态存储，按 `partition_local` 挂到对应分区。

### 4.8 `cpu.st.build-schedule`（SchedulePlan 完整结构，自顶向下）

前面六个 pass 只回答了"每个 op 在树的哪棵子树里"（静态结构）；本 pass 产出执行所需的完整 `SchedulePlan`。先给自顶向下的完整 schema，标注每项的来源（`cpu.md` §4 既有 / 本方案新增）：

```text
SchedulePlan
  numa_nodes: NumaNodeSchedule[]                    # [既有] 硬件资源槽位。本方案恒为 1 个
  inputFanout:            Map<ValueId, ActivationTargets>  # [新增] eval 入口输入差分，见 ③
  computeSupernodeFanout: Map<ValueId, ActivationTargets>  # [新增] 见 ③
  commitStateFanout:      Map<StateId, ActivationTargets>  # [新增] E(S)，见 ③

ActivationTargets                      # [新增] 三张表共用的值类型
  activate: PartitionId[]              # compute supernode 分区；emit 解析为 activeId 置位
  arm: PartitionId[]                   # commit 事件域分区；置位其 eventDomainArm

NumaNodeSchedule                       # [既有] 一个 NUMA 内存域
  numa_node: NumaNodeId
  cores: CpuCoreSchedule[]             # 本方案恒为 1 个

CpuCoreSchedule                        # [既有] 一个 CPU 核
  core: CpuCoreId
  tasks: ScheduledTask[]               # 数组顺序 = 该 core 上的执行顺序

ScheduledTask                          # [既有] 的前三个字段保持不变
  id: TaskId
  partition: PartitionId               # 引用一个函数分区（见 ①）
  waits_for: TaskId[]                  # 跨 core 顺序依赖；单线程恒为空
  execution: ActivityDrivenCompute     # [新增] 见 ②
           | DomainGatedCommit
           | AlwaysScanCommit
```

NUMA node / CPU core 在这里只是**硬件资源槽位**：`cpu.md` 定义 SchedulePlan 时预留了多核并行的骨架，本方案是单线程方案，把骨架填成最简形态（1 个 NUMA node、1 个 core、`waits_for` 全空），执行语义全部挂在 task 和 plan 级的三张表上。未来 `cpu.mt.*` 方案复用同一骨架，把任务分配到多个 core 并用 `waits_for` 表达跨核依赖，`execution` 与三张激活表的定义不需要变。

在此骨架上，本 pass 依次回答四个问题：

**① 谁来执行——task 列表。** task 粒度 = 函数分区（eval 直接调用的单元，`partition` 字段引用它）：compute 枝按调度序、commit 枝按域分组顺序，展开为唯一 core 上的 `tasks` 数组。word/supernode 只是函数任务内部的派发层次，不构成 task。

**② 什么时候执行——task 的 `execution` 字段。**

- `ActivityDrivenCompute`：compute 函数——函数永远被调用，body 内按 word 整字测试 + active bit 门控执行各 supernode，执行即消费该 bit；
- `DomainGatedCommit`：commit 函数——所属域的 eventDomainArm 置位才进入，内部按 event guard 精判。两层不重复：eventDomainArm 是调度级粗门控（宁多勿少的保守近似，省的是扫描成本）；event guard 是语义本体——其中的数据使能部分（updateCond/mask）从不属于域 key，边沿部分则兜底 arm 的保守性（多事件 key 的析取、Level/general 域）；
- `AlwaysScanCommit`：general 域 commit 函数——每轮都进，event guard 精判。

**③ 执行后唤醒谁——三张以 id 为键的激活辅助表（plan 级旁表）。** 不设统一的 trigger 抽象：激活信息直接物化为三张 map，emit 在写站点按 id 查表，命中才生成激活代码，查不到（无扇出的 input、partition_local value、无 reader 的 state、不被任何域引用的时钟值）则什么都不生成。

- **`inputFanout`（键为 top input 的 valueId）**：eval 入口的输入检测表。键集合同时就是"需要 prev 影子拷贝做变化检测的 input 清单"——无条目的 input 不生成影子与比较代码。命中且真变化 → `activate` 目标 supernode、`arm` 输入时钟域（InputClock 域的唯一 arm 来源；对时钟 input 任意变化即 arm，入口不做边沿方向判断，方向由 event guard 精判）。对应 legacy 的 `inputHeadSupernodesByValue`。
- **`computeSupernodeFanout`（键 valueId）**：compute 内 value 写站点的扇出表——跨分区 boundary value 的真变化（`activate` = reader 所在 compute supernode）；compute 求值出的 event value 边沿（`arm` = 引用它的 commit 事件域分区，派生时钟在此生效；eventDomainArm 是唯一新增的激活种类）。对应 legacy 的 `boundaryFanoutByValue`。
- **`commitStateFanout`（键 stateId，即仿真模型语义中的 E(S)）**：commit 内每个 state 写站点查表——命中且可见值真变化时生成 `{ continue_eval = true; 激活/重 arm 目标 }`。`activate` = 读该 state 的 compute supernode（对应 legacy `stateHeadSupernodesBySymbol`，与 `commitContinue` 合体）；`arm` = 事件守卫数据条件可能受该 state 影响的域——state 更新后这些域需要在下一轮重看（保守可填全部域，由 event guard 精判兜底正确性；与 legacy"每轮重扫全部 commit"语义等价，代价从全函数体降到 O(域数) 的 arm 检查）。

**为什么 `activate` 的目标是 supernode 而不是 task**：task 是函数边界——永远被调用、无门控，只是代码组织；active bit 挂在 supernode 上（activeId 由 §4.5 分配），激活粒度必须等于调度单元粒度，否则函数内几十~几百个 supernode 会被一次唤醒全部执行，活动度调度失效。emit 把条目中的 supernode 分区解析为其 activeId，生成 `active[word] |= 1 << lane` 置位；函数层与 word 层无需激活——函数永远被调用，word 的整字零测试自动拾取该位（同字短链见 §4.5）。条目在 schedule 期按 activeId 排序去重，emit 按序生成置位语句（同 legacy fanout 表的做法）。

**为什么是三张表、为什么在 plan 级**：消费位置只有三处——eval 入口差分（`inputFanout`）、compute 内 value 写站点（`computeSupernodeFanout`）、commit 内 state 写站点（`commitStateFanout`，附带"继续 eval"语义）；键类型即消费位置，emit 无需再推导。统一 trigger 代数（InputChange / ValueChange / EventEdge / StateWrite）按此自然折叠：InputChange 独立成表还因为它的键集合直接决定哪些 input 需要 prev 影子拷贝；EventEdge 与 ValueChange 同为 value 写站点触发，合并成一张。三张表是唤醒关系（活动度图的边集）的索引，与 NumaNode→CpuCore→ScheduledTask 的包含层次正交——同一 value 可唤醒多个 supernode、输入没有产生者 task，挂不进任何单一节点；这与 `cpu.md` §3"跨分区 value 关系不进 PartitionTree、由 `G` 推导"的原则一致。

条目只为**跨边界触发源**建立：分区内部 value 随任务体无条件求值，无需激活传播；无扇出的 input 不进 `inputFanout`（也不生成 prev 影子拷贝）；无 reader 的 state 不进 `commitStateFanout`。不变量（verifier 可检查）：`activate` 目标只能是 compute 枝的 supernode 分区，`arm` 目标只能是 commit 侧事件域分区；不存在任何指向 commit 的 `activate` 条目（commit 不吃 compute 激活位，成本依据见 §4.9 注）——commit 函数只经由三张表的 `arm` 目标获得执行机会。

**④ 什么时候停——没有独立的轮结构，E(S) 成员资格即循环条件。** eval 的 fixed-point 主循环是 emit 的固定样板（见 §4.9），plan 不需要 `RoundStructure` 数据："是否再来一轮"恰好就是"本轮 commit 是否有 `commitStateFanout` 命中的 state 被实际更新"。轮末清 edge slot / eventDomainArm 也是样板的一部分，不构成 plan 字段。

### 4.9 eval 主循环（`cpu.st.emit-cpp` 生成形态）

```
eval():
  1. 输入差分：仅对 inputFanout 列出的 input 做 prev 比较，真变化则查表 —— seed compute active bits、arm 输入时钟域。
  2. do {
       a. compute：按 task 序执行，逐 word 整字零测试跳过，命中字内按 bit 门控执行 supernode（同 legacy）；
          每个 boundary value 写站点：真变化时查 computeSupernodeFanout，命中则置位目标 active bit；
          event value 边沿则 arm 目标域 + 更新 edge slot（派生时钟在此生效）。
       b. commit：按域组序执行，eventDomainArm 未置位整域跳过，命中域内 event guard 精判执行；
          每个 state 写站点：可见值真变化时查 commitStateFanout，命中则 continue_eval = true、
          激活 reader compute bits、按条目重 arm 相关域。
       c. 清轮内 edge slot 与 eventDomainArm。
     } while (continue_eval);
  3. refresh_outputs；发布 prev 输入。
```

- **无边沿的域零成本跳过**——多时钟性能收益的来源（慢速域/未触发域不扫）。
- **单时钟语义逐点等价**：唯一 InputClock 域在时钟输入变化时 arm，等价于 legacy 每轮扫描后 event guard 精判的结果；guard 为 false 的空扫被整域跳过，开销只减不增。数据输入变化只喂 commit 数据口时甚至不再触发空轮（legacy 会 `pending=true` 白扫一轮 commit）。
- **事件历史的采样纪律**：每 (op, event) 的历史值在 fixed-point 迭代内只读，eval 结束时统一更新（即迭代内所见历史值 = 上一次 eval 结束时的值）。这保证迭代内"重看"（`commitStateFanout` 的 arm 目标）与 legacy 每轮重扫的守卫判定逐点一致，同一输入边沿在一次 eval 内只被解释为一个事件。
- **初始化**：首次 eval 前全部 supernode 激活、全部事件域 arm，history slot 按 IR 初值装载——等价 legacy 的首轮全量执行路径。

> 注（legacy 的成本依据，约束门控粒度）：legacy 刻意不让 commit 吃 compute 激活位——commit supernode 少（XiangShan 6,231 vs compute 62,823，NO0092）、event 表达式逐 word 评估极便宜，而 compute→commit 激活边极多（388,044 对）、数据通路抖动远多于时钟边沿。两次把 commit 激活做细的尝试均失败撤回：NO0034（event-delta 收窄，仅 +1.75%）、NO0206（activation mask grouping，慢 1.88x）。因此 eventDomainArm 必须保持**粗粒度**：每域一个标志、每轮至多一次置位/清零，门控成本 O(域数)；严禁演化为 per-supernode / per-write-group 的细粒度 commit 激活。

### 4.10 快速路径：首版不实现 fullpass（决策）

**决策：grhsim IR 路线首版不实现任何 fullpass 快路径（input fullpass / edge fullpass / sparse-pure-event 等），只保留通用活动度主循环 + 域门控。** 依据是 legacy 的完整实验链：

- fullpass 的收益集中在小组件：input fullpass 总时间 -8%~-12%（NO0242），posedge fullpass high phase -10%~-17%（NO0244）；
- 在主目标 XiangShan SimTop 上净收益≈0：完全关闭 event 快路径（~19.5s/10k，NO0252）与密度自适应 settle（~19.2s/10k，NO0253）持平，而无条件全图 fullpass 曾劣化到 ~88s；
- fullpass 跳过事件精判，是 multi-clock 正确性雷区的主要载体（NO0243/NO0248）；不实现即整体回避该雷区，域门控主循环的唯一正确性依据就是通用的 event guard 精判。

重新引入的触发条件（未来可选，按 RULES 单独立项）：单时钟 parity 后存在可归因于"激活检查/传播记账"的差距且有密度 profile 支撑。届时特化版本按生成函数边界复制，post-commit settle 必须密度自适应（NO0253），multi-clock 同 eval / 混合边沿 / DerivedClock 域一律禁用。

## 5. CpuBackendMapping 扩展清单

| 位置 | 新增内容 | 产生 pass | 对应 legacy 机制 |
| --- | --- | --- | --- |
| `partition_tree` 第一层 + `PartitionAttrs.phase` | compute/commit 两枝 | cpu.st.split-phase | `supernode_kind` |
| `partition_tree` commit 枝 + `PartitionAttrs.event_gate` | 事件域分区层 | cpu.st.form-event-domains | commit event key 分桶 |
| `partition_tree` compute 枝叶/中间层 | node / supernode | cpu.st.build-compute-nodes / cpu.st.merge-compute-supernodes | compute node、`supernode_to_ops` |
| `partition_tree` compute 枝 + `PartitionAttrs.active_word` | word 分区层（activeId 分配） | cpu.st.pack-active-words | active flag word、helper chunk |
| `partition_tree` 两枝 | 函数分区层（生成函数边界） | cpu.st.pack-emit-functions | `buildScheduleBatches`（TU 装箱不进 mapping，由 emit 选项决定） |
| `schedule_plan` task 附加 | `execution` 执行条件 | cpu.st.build-schedule | active bit 派发 / commit 每轮扫描 |
| `schedule_plan` | `inputFanout`（input ValueId → ActivationTargets） | cpu.st.build-schedule | `inputHeadSupernodesByValue` |
| `schedule_plan` | `computeSupernodeFanout`（ValueId → ActivationTargets） | cpu.st.build-schedule | `boundaryFanoutByValue` + eventDomainArm（新） |
| `schedule_plan` | `commitStateFanout` E(S)（StateId → ActivationTargets） | cpu.st.build-schedule | `stateHeadSupernodesBySymbol` / `commitContinue` |
| `data_layout` | 沿用现有字段 | cpu.st.layout-data | state/value slot、active flag word、edge slot |

失效仍走 identity + semantic revision 机制（既有）。`cpu.md` §5 验证规则需补：phase 子树不互含；`activate` 目标只能是 compute 枝的 supernode 分区、`arm` 目标只能是 commit 侧事件域分区（commit 不激活 commit）。

## 6. 里程碑与验证

实施前置：infrastructure-plan 的 M1–M4（GRH model、mapping 容器、PassManager/per-pass verify）就绪；本规划对 `cpu.md` 的扩展（`PartitionAttrs` 三项、`ScheduledTask.execution`、三张激活表）随首个 pass 落地时同步写回 `cpu.md`，保持单一权威定义。

- **M5.0 phase 切分 + 时钟域**：`cpu.st.split-phase` + `cpu.st.form-event-domains`。验收：phase 分类与 legacy `supernode_kind` 全量一致；XiangShan 归一结果恰为 1 个 Edge 域（+ 可能的 Level 类），hdlbits 全量域统计符合人工核查。
- **M5.1 单时钟 parity**：compute 侧 `build-compute-nodes`/`merge-compute-supernodes`/`pack-active-words` + 两枝 `pack-emit-functions` + `layout-data` + `build-schedule` + `emit-cpp` 最小链路。验收：hdlbits 全量过；XiangShan coremark difftest 10k/50k 过；性能对齐 legacy（50k 不差于基线 5%；小组件 benchmark 允许因未实现 fullpass 落后 ~8-17%，记录为已知差距）。
- **M5.2 多时钟域求值**：event_gate 标注 + DomainGatedCommit 执行条件 + 事件域门控主循环。验收：新增多时钟测试台（双时钟 FIFO/CDC 计数器等 2–3 个 DUT，与 Verilator 逐步 difftest）；XiangShan 回归不退。
- **M5.3 性能评估与调优（不含 fullpass）**：对照 legacy 做差距归因。fullpass 不在默认路线，仅当差距可归因于激活检查/传播记账且有密度 profile 支撑时，按 §4.10 的触发条件单独立项。验收：50k 性能报告 + 差距归因结论。

每个里程碑遵循 `pdocs/grhsim_opt/RULES.md` 的增量记录方式单独归档 plan/gate 文档。

## 7. 风险与开放问题

1. **派生时钟的域判定成本**：DerivedClock 域的 eventDomainArm 依赖迭代内 compute 传播，最坏情况（时钟由大组合锥驱动）门控收益被激活传播本身吃掉；profile 后决定是否把派生域退回 general 分区。
2. **latch/电平**：Level 类归入每轮扫描（general 语义），多时钟+latch 混合设计下无门控收益；首轮接受，后续可引入 enable 表达式合成精判。
3. **跨域 state 读写（CDC）**：IR 语义已覆盖（NBA + 读旧写新），但 legacy 的"同拍读旧写新"激活时序假设需在多时钟 DUT 上重点 difftest。
4. **调度粒度与并行**：事件域分区与函数分区天然是多核 `waits_for` 并行的划分单元；多线程支持走独立的 `cpu.mt.*` pass 族（共享 mapping 结构定义，各自产出 SchedulePlan），本规划只做 `cpu.st.*`。
5. **`core.state.memWriteSeq`（有序多写口）** lowering 尚未产生，与多时钟正交，落地时在 commit 分区内按单 op 顺序 store 处理。
6. **同一 state 多写口的 commit 侧形态**：首轮假设写合并在 compute 侧完成、commit 内每个 state 至多一个写站点；实现 `split-phase`/`form-event-domains` 时对照 legacy 写合并路径验证该假设，若不成立则在事件域内按 topo 序串行并保持读旧写新。

## 8. 参考

- 权威现状：`wolvrix/docs/emit/grhsim-scheduling.md`、`wolvrix/docs/transform/activity-schedule.md`
- legacy word/batch/TU 层次：`wolvrix/lib/emit/grhsim_cpp.cpp`（`ScheduleBatch` 2338、`buildScheduleBatches` 10252、`emitSchedBatchFile` 14498）
- IR 语义与 CPU backend 骨架：`wolvrix/docs/grhsim_ir/overview.md`、`.../backends/cpu.md`、`pdocs/draft/grhsim_ir/infrastructure-plan.md`（§12.3、§18）
- compute/commit 语义：`pdocs/grhsim_opt/NO0023_grhsim_compute_commit_two_phase_eval_plan_20260423.md`
- sink 收窄（system task/dpi 出 commit）：`pdocs/grhsim_opt/NO0033_activity_schedule_simplification_plan_20260427.md`
- event 分桶（事件域分区的原型）：`pdocs/grhsim_opt/NO0029_sink_supernode_event_cluster_plan_20260424.md`、`NO0092_..._commit_bucket_snapshot_20260514.md`
- commit 激活粒度教训（细粒度均负收益）：`pdocs/grhsim_opt/NO0034_sink_activation_event_delta_plan_20260427.md`、`NO0206_commit_activation_mask_group_plan_20260624.md`
- 多时钟雷区：`pdocs/grhsim_opt/NO0243_..._posedge_fullpass_probe_20260709.md`、`NO0248–NO0253` SimTop event fullpass 系列
- gsim 机制：`reference/gsim/src/cppEmitter.cpp`（activeFlags/genActivate/activateNext）、`reference/gsim/src/clockOptimize.cpp`（单时钟假设）
- 图密度教训：`pdocs/grhsim_opt/NO0010_current_grhsim_supernode_graph_vs_gsim_20260419.md`
