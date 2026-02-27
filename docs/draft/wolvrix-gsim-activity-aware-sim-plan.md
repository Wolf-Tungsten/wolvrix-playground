# 在 Wolvrix 上实现 GSim 式活动度感知仿真优化（逐 pass 里程碑）

> 目标：在 Wolvrix 上实现 GSim 风格活动度感知仿真，但**Wolvrix 表达能力更强**（更丰富 clk/rst 语义、多事件、async reset、mask 语义等），因此必须先做语义统一，再做活动分析与调度落地。

## 总体思路（从输入到可输出 C++ 仿真代码）

**核心假设**：Wolvrix 采用 full-cycle 仿真模型。时钟/复位信号通过 `eventEdge` 显式记录，但**不引入事件队列**；`eventEdge` 只用于“边沿发生判定”，作为活动度门控条件。  

**主线流程**：
1. **读入与结构规范**：解析 SV → GRH，先消除 XMR，展平层次，并执行 blackbox 检查（若存在则终止）。  
2. **语义统一**：将所有“事件相关操作”（时序写口、DPI/system task 等）统一成标准形，确保 `eventEdge / updateCond / mask` 语义一致可用。  
3. **组合环路处理**：在组合 use-def 子图上消除伪环路（仅允许显式时序回路）。  
4. **活动度源与事件分组**：  
   - 从输入端口与状态读口定义活动度源（roots）。  
   - 按 `eventList` 对所有状态更新操作分组，形成粗粒度事件门控。  
5. **组合锥分区与传播**：  
   - 先按事件组切分组合逻辑锥，得到“粗粒度分区”。  
   - 在每个分区内构建组合活动传播图，用于后续排序、region 划分与细粒度活动度。  
6. **调度与时序更新**：  
   - 基于组合传播图建立拓扑序与 region DAG。  
   - 建立时序更新集合（含 `kDpicCall`），并与 region 关联。  
   - 生成 full-cycle 调度计划：事件组激活 → 组合 region 计算 → 时序更新。  
7. **代码生成**：根据调度计划与 GRH 结构生成可执行 C++ 仿真代码（cppEmitter），实现活动度门控与 full-cycle 推进。

**最终产物**：可输出的 C++ 仿真代码，具备：  
- full-cycle 时序推进  
- 基于 eventList 的粗粒度门控  
- 组合逻辑内的细粒度活动度优化  

## 逐 pass 里程碑（每步完成一个 pass）

### 1. `hier-flatten`
**交付**：层次扁平图。  
**前置条件**：若 design 恰好只有一个顶层模块则自动使用；否则用户必须显式指定顶层模块。且 design 中不得残留 XMR（必须先完成 `xmr-resolve`）。  
**可配置项**：  
- `preserveFlattenedModules`（是否保留被 flatten 掉的模块图以便复用/调试）。  
- `symProtect`（符号保护策略）：  
  - `all`：保护所有 `declaredSymbol`，形成层次化命名。  
  - `hierarchy`：保护所有层次端口与 `reg/mem/latch`。  
  - `stateful`：仅保护 `reg/mem/latch` 等有状态操作。  
  - `none`：不保护，全部改为内部符号。  
**命名策略**：  
- 对 `declaredSymbol` 使用 `$` 分割的层次 sym 合成，保证可读性与稳定性。  
- 对非 `declaredSymbol` 采用 plain internal symbol，避免 symbol 过度膨胀。  
**引用保护**：flatten 过程中必须重写所有基于 symbol 的引用，确保一致性（如 read/write port 对应的 `regSymbol/memSymbol/latchSymbol`、端口别名、以及相关依赖边）。  
**验收**：跨实例依赖不被截断，名称稳定、端口连接转换为直接 def-use 边，且 read/write port 与 storage 引用保持一致。

### 2. `blackbox-guard`
**交付**：确保设计不含 `kBlackbox`（否则报错终止）。  
**验收**：设计中不存在 `kBlackbox` 操作；若存在必须报错并停止后续 pass。  

### 3. `seq-event-normalize`
**交付**：reg/mem/latch 写入统一语义形。  
**验收**：
- `eventEdge` 与 events 数量对齐
- `updateCond` 归一为 1-bit
- `mask` 语义规范化（含全 0/全 1 标记）
- richer clk/rst 语义被吸收并统一到 `updateCond/event/mask`

**处理范围**：
- `kRegisterWritePort`
- `kMemoryWritePort`
- `kLatchWritePort`
- `kDpicCall`
- `kSystemTask`

**处理规则（可执行，按操作类型）**：
1. **`kRegisterWritePort`**  
   - 操作数布局：`[updateCond, nextValue, mask, evt0..evtN]`。  
   - 属性要求：必须有 `regSymbol`；必须有 `eventEdge` 且非空；`eventEdge.size == evtCount`。  
   - 标准化：`updateCond` 归一为 1-bit；`mask` 归一为 1-bit 或数据同宽（1-bit 需扩展）；记录全 0/全 1 常量标记。

2. **`kMemoryWritePort`**  
   - 操作数布局：`[updateCond, addr, data, mask, evt0..evtN]`。  
   - 属性要求：必须有 `memSymbol`；必须有 `eventEdge` 且非空；`eventEdge.size == evtCount`。  
   - 标准化：同寄存器写（`updateCond` 1-bit，`mask` 归一，常量标记）。

3. **`kLatchWritePort`**  
   - 操作数布局：`[updateCond, nextValue, mask]`。  
   - 属性要求：必须有 `latchSymbol`；`eventEdge` 必须不存在或为空；禁止事件操作数。  
   - 标准化：`updateCond` 归一为 1-bit；`mask` 归一为 1-bit 或数据同宽（1-bit 需扩展）。

4. **`kDpicCall`**  
   - 操作数布局：`[updateCond, inArgs..., evt0..evtN]`。  
   - 属性要求：必须有 `targetImportSymbol`、`inArgName`、`outArgName`、`hasReturn`；`inoutArgName` 可选；必须有 `eventEdge` 且非空；`eventEdge.size == evtCount`。  
   - 计数校验：`inArgs.count == inArgName.size + inoutArgName.size`。  
   - 标准化：`updateCond` 归一为 1-bit；事件顺序固定为输入顺序；若 `eventEdge` 缺失或为空则报错。

5. **`kSystemTask`**  
   - 操作数布局：`[updateCond, args..., evt0..evtN]`。  
   - 属性要求：必须有 `name`；必须有 `procKind` 与 `hasTiming`。  
   - 事件规则：  
     - 若 `eventEdge` 存在，则 `eventEdge.size == evtCount`。  
     - 若 `hasTiming == true` 或 `procKind == "always_ff"`，则 `eventEdge` 必须非空（必须是边沿触发）。  
     - 若 `eventEdge` 为空，则禁止事件操作数，并按 `procKind` 走组合/initial/final 语义。  
   - 标准化：`updateCond` 归一为 1-bit；事件顺序固定为输入顺序。

6. **更丰富 clk/rst 语义吸收（通用规则）**  
   - 多 clk / 多 rst 统一落到 `eventEdge + updateCond`。  
   - async reset 必须显式体现在事件/条件路径中（不可隐式丢失）。  
   - 若存在优先级（reset > enable），在此阶段落成标准的条件结构。

### 4. `comb-loop-elim`
**交付**：组合依赖视图的环路检查结果 + 伪环路拆分结果。  
**验收**：  
- 组合子图无环（仅允许通过显式时序边形成回路）。  
- 对“位片段自依赖”的伪环路（如 `assign a[7:4] = a[3:0]`）完成拆分，保持语义不变。  
**处理规则（可执行）**：  
1. **构建组合 use-def 子图**  
   - 节点：`Value` 与 `Operation` 的二部图。  
   - 边：`Value -> 使用该 Value 的 Operation`，以及 `Operation -> 其结果 Value`。  
   - 时序边处理：  
     - `kRegisterReadPort/kLatchReadPort/kMemoryReadPort` 结果视为**源**（不引入来自状态的回边）。  
     - `kRegisterWritePort/kLatchWritePort/kMemoryWritePort` 视为**汇**（不引出到状态的回边）。  
2. **检测组合 SCC（强连通分量）**  
   - SCC 仅含单点且无自环：通过。  
   - 其余进入“伪环路判定”。  
3. **伪环路判定（位片段映射环）**  
   - 允许以下两类伪环路：  
     - **同一 Value 的不重叠位片段拷贝**。  
     - **通过别名/中间 Value 的不重叠位片段映射**（例如 `b = a`，随后 `a[7:4] = b[3:0]`）。  
   - 判定条件：在 SCC 内构建“位片段映射图”，若每条映射边都是**不重叠 slice 的纯拷贝**，且按 bit 级展开后不存在同一 bit 自依赖，则视为伪环路。  
4. **拆分策略（可执行）**  
   - 为涉及的 Value 集合构建“片段值”集合（按被写入/读取的 slice 划分，并跨别名链传播），**原始 Value 被拆成多个独立 Value**。  
   - 将对原 Value 的读取改为读取对应片段值；将对原 Value 的写入改为写入片段值。  
   - 对“别名拷贝”（`kAssign` 全宽拷贝）改写为片段级拷贝。  
   - 若有外部使用需要完整 Value，仅在**环外边界**追加 `kConcat` 生成“只读视图”；该视图**不得**再回流到片段写入路径（否则环路会被重新引入）。  
   - 拆分后重跑 SCC 检测；若仍有环，视为真实组合环并报错。  
5. **诊断输出**  
   - 对真实组合环输出 SCC 内的 op/value 列表与相关 slice 范围，便于定位。  

### 5. `activity-source-build`
**交付**：活动度源集合（roots）。  
**验收**：roots 至少包含输入端口与时序元件输出（寄存器/锁存器/内存读口），并统一作为“组合信号”参与活动传播。  
**输入**：  
- 扁平化设计图  
- 已归一的时序/事件语义（`seq-event-normalize` 输出）  
**输出（写入 scratchpad）**：  
- `sim.roots`：roots 的 ValueId 列表  
- `sim.rootKind`：ValueId -> {InputPort, StateRead}  
- `sim.rootChangePolicy`：ValueId -> {Diff, Edge}（变更检测策略）  
**算法流程**：  
1. **输入端口**：  
   - 收集所有输入端口 Value。  
   - 标记为 `rootKind=InputPort`，变更检测策略为 `Diff`（比较前后值）。  
2. **状态读口**：  
   - 收集 `kRegisterReadPort/kLatchReadPort/kMemoryReadPort` 的结果 Value。  
   - 标记为 `rootKind=StateRead`；策略为 `Diff`（写后比较新旧值，未变化则不激活）。  
3. **去重与稳定排序**：  
   - 去重 roots 并按 ValueId 稳定排序，保证后续结果可复现。  
4. **运行期使用约定**：  
   - `Diff`：维护 prev 值快照，变化才置 active。  
   - `Edge`：仅用于时钟/复位类事件信号（由 `event-group-build` 标注并使用）。  

### 6. `event-group-build`
**交付**：按 `eventList` 分组的状态 op 集合。  
**验收**：  
- 组键为标准化 `EventKey(eventEdge + 事件操作数)`。  
- 状态 op 覆盖 `kRegisterWritePort/kMemoryWritePort/kLatchWritePort/kDpicCall`。  
- 无 `eventEdge` 的状态 op 进入 `always-eligible` 组（例如 latch）。  

### 7. `comb-cone-partition`
**交付**：组合逻辑锥的粗粒度分区（按 event group 划分）。  
**验收**：  
- 每个 event group 有对应的组合锥集合。  
- 允许组合 op 属于多个 group（共享锥不丢失）。  
- 组合锥覆盖从 roots 到时序更新点的组合路径。  

### 8. `activity-comb-propagate-build`
**交付**：组合活动传播图（组内细分）。  
**验收**：传播边仅沿组合逻辑与普通 use-def 建立；时序写口与 `kDpicCall` 视为传播终点，不从其结果继续扩展。  
**输入**：  
- `sim.roots`（由 `activity-source-build` 输出）  
- `sim.eventGroups` / `sim.eventGroupOfSeqOp`（由 `event-group-build` 输出）  
- `sim.combGroupMap`（由 `comb-cone-partition` 输出）  
- 当前扁平化设计（包含所有组合/时序 op）  
**输出（写入 scratchpad）**：  
- `sim.combGraph`：组合传播图（邻接表或边列表，按 op/value 建模均可）  
- `sim.combUse`：Value -> 使用该 Value 的组合 op 索引（便于增量传播）  
- `sim.combGraphByGroup`（可选）：每个 event group 的组合子图视图  
**算法流程**：  
1. 以 `sim.roots` 为起点遍历组合逻辑，限制在 `sim.combGroupMap` 覆盖的组合锥内。  
2. 建立组合传播边（`Value -> Op -> Value`），不穿越时序写口与 `kDpicCall`。  
3. `kRegisterReadPort/kMemoryReadPort/kLatchReadPort` 结果作为组合源；`kRegisterWritePort/kMemoryWritePort/kLatchWritePort` 作为传播终点。  
4. 若组合 op 同时属于多个 group，允许其在多个 group 子图中复用。  

### 9. `activity-toposort`
**交付**：稳定拓扑序（基于组合传播图）。  
**验收**：组合子图无环或明确诊断，后续 pass 只消费该序。  
**输入**：  
- `sim.combGraph`（或 `sim.combGraphByGroup`）  
**输出（写入 scratchpad）**：  
- `sim.combOrder`：组合 op 拓扑序（可按 group 分块）  
- `sim.combTopoDiag`：组合环路诊断（若存在）  
**算法流程**：  
1. 对组合子图执行拓扑排序（Kahn/DFS 均可）。  
2. 若检测到环路，输出诊断并终止（真实组合环，必须修复）。  
3. 可选：对每个 event group 子图分别排序，以便后续分区与调度分组。  

### 10. `activity-region-build`
**交付**：region 划分 + region DAG。  
**验收**：region 图可执行，region 元数据完整（size、in/out degree）。  
**输入**：  
- `sim.combGraph`  
- `sim.combOrder`  
- `sim.combGroupMap`（决定 region 归属的 event group）  
**输出（写入 scratchpad）**：  
- `sim.regionMap`：op -> regionId  
- `sim.regionDAG`：region 依赖图  
- `sim.regionMeta`：region 统计（size、in/out degree、所属 event group）  
**算法流程**：  
1. 按 `sim.combOrder` 线性扫描，构建 region（支持 size 上限或边界条件）。  
2. region 不跨越 event group（若 op 属于多个 group，则允许复制归属或标注多归属）。  
3. 根据 `sim.combGraph` 折叠成 `sim.regionDAG`，并统计入/出度。  

### 11. `activity-seq-update-build`
**交付**：时序更新集合与触发条件（可按 region 归并）。  
**验收**：  
- 时序更新集合包含 `kRegisterWritePort/kMemoryWritePort/kLatchWritePort` 与 `kDpicCall`。  
- `eventEdge` 被转换为“边沿发生判定”，仅作为 full-cycle 的激活条件，不引入事件队列。  
- 组合传播结果能正确连接到这些时序更新点；若已有 region 划分，需生成 region→seq-update 映射。  
**输入**：  
- 设计中的时序 op（写口与 `kDpicCall`）  
- `sim.eventGroups` / `sim.eventGroupOfSeqOp`  
- `sim.regionMap` / `sim.regionDAG`  
**输出（写入 scratchpad）**：  
- `sim.seqUpdateSet`：时序更新点列表（含 opId、eventKey、updateCond、mask、targetSymbol）  
- `sim.regionToSeqUpdate`：regionId -> 时序更新点集合  
- `sim.eventGroupToSeqUpdate`：eventGroup -> 时序更新点集合  
**算法流程**：  
1. 枚举所有时序更新 op，提取 `eventEdge` 与事件操作数，形成 `eventKey`。  
2. 将 `updateCond/mask` 归入该更新点，形成可执行的更新记录。  
3. 依据 `sim.regionMap` 把更新点归并到对应 region（用于调度阶段）。  

### 12. `activity-schedule-lower`
**交付**：substep + active flags + nextActive/alwaysActive/activateAll 规则。  
**验收**：full-cycle 调度可执行，活动度从“event group → 组合传播 → 时序更新”闭环一致。  
**输入**：  
- `sim.combOrder`  
- `sim.regionMap` / `sim.regionDAG` / `sim.regionMeta`  
- `sim.eventGroups` / `sim.eventGroupToSeqUpdate`  
- `sim.seqUpdateSet` / `sim.regionToSeqUpdate`  
**输出（写入 scratchpad）**：  
- `sim.schedulePlan`：可执行调度计划（substep 列表、active flag 位布局、group→region 执行顺序）  
**算法流程**：  
1. **运行期前置判定**：根据 `eventKey` 做边沿检测，得到本拍激活的 event groups。  
2. **组合阶段**：按 `sim.regionDAG` 与 `sim.combOrder`，仅执行激活组内的 region。  
3. **时序更新阶段**：执行 `sim.seqUpdateSet` 中属于激活组/激活 region 的更新。  
4. **状态提交**：更新寄存器/内存状态与输出，进入下一拍。  

**6-12 交付结果依赖关系（明确数据流）**：  
1. `event-group-build` 输出 `eventGroups/eventGroupOfSeqOp` → 供 `comb-cone-partition` 与 `activity-seq-update-build` 使用。  
2. `comb-cone-partition` 输出 `combGroupMap` → 供 `activity-comb-propagate-build` 与 `activity-schedule-lower` 使用。  
3. `activity-comb-propagate-build` 输出 `combGraph/combUse` → 供 `activity-toposort` 与 `activity-region-build` 使用。  
4. `activity-toposort` 输出 `combOrder` → 供 `activity-region-build` 与 `activity-schedule-lower` 使用。  
5. `activity-region-build` 输出 `regionMap/regionDAG` → 供 `activity-seq-update-build` 与 `activity-schedule-lower` 使用。  
6. `activity-seq-update-build` 输出 `seqUpdateSet` + `regionToSeqUpdate` → 供 `activity-schedule-lower` 使用。  
7. `activity-schedule-lower` 汇总上述结果生成可执行 full-cycle 调度。  

---

## 建议执行 pipeline（严格顺序）

1. `xmr-resolve`
2. `hier-flatten`
3. `blackbox-guard`
4. `const-fold`
5. `redundant-elim`
6. `dead-code-elim`
7. `seq-event-normalize`
8. `comb-loop-elim`
9. `activity-source-build`
10. `event-group-build`
11. `comb-cone-partition`
12. `activity-comb-propagate-build`
13. `activity-toposort`
14. `activity-region-build`
15. `activity-seq-update-build`
16. `activity-schedule-lower`

`clock-gate-lower` 放在 6 与 7 之间（可选）。

---

## 数据契约（落地必须先定）

为避免 pass 之间“口头约定”，建议统一使用 scratchpad key：
- `sim.flatGraph`：flatten 后图句柄或映射
- `sim.depGraph`：活动依赖图（节点、边、特殊边类型）
- `sim.topoOrder`：稳定序
- `sim.regionMap`：op->region，region 元数据
- `sim.nextActive`：region->bitset
- `sim.alwaysActive`：bitset
- `sim.schedulePlan`：substep + flag layout
