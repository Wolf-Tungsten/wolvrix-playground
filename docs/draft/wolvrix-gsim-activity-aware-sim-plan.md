# 在 Wolvrix 上实现 GSim 式活动度感知仿真优化（可执行方案）

> 这版聚焦“必须环节 + pass 依赖 + 工程落地”。
> 关键结论：你提到的两件事是硬要求——**实例层次展开（flatten）** 与 **拓扑排序**。

## 1. 先回答核心问题

### 1.1 是否必须有 instance 内联 pass？

**必须有。**

`gsim` 在 `AST2Graph` 阶段做了等价于 flatten 的动作：
- `visitInst()` 递归进入实例模块。
- 用层次前缀拼接信号名（`prefixTrace + SEP_MODULE/SEP_AGGR`）。
- 最终得到单图上的扁平依赖关系（extmodule 作为特殊节点保留）。

换到 `wolvrix`，如果不做 flatten：
- 活动传播图会被实例边界截断。
- `nextActive` 无法覆盖跨实例数据路径。
- 最后只能退化成粗粒度 activateAll，收益大幅下降。

所以应新增 **`hier-flatten` pass（必需）**，或提供等价预处理并保证活动分析输入是扁平图。

### 1.2 是否必须有拓扑排序 pass？

**必须有。**

`gsim` 的 `topoSort()` 在 supernode 依赖图上建立全序；后续 pass（分区、语句生成、active 调度）都依赖这个顺序。

换到 `wolvrix`，需要至少两层顺序：
1. op 级 DAG 顺序（数据依赖）。
2. region 级 DAG 顺序（调度依赖）。

因此应新增 **`activity-toposort` pass（必需）**，并要求后续 pass 只消费它输出的 order。

---

## 2. 从 gsim 逆向得到的“硬前置链”

按 gsim 主流程（`main.cpp`）和关键实现（`AST2Graph.cpp/topoSort.cpp/graphPartition.cpp/instsGenerator.cpp/cppEmitter.cpp`）抽象，活动优化必须经过这条链：

1. **层次展开**（flatten + extmodule 保留）
2. **时序语义归一**（`updateCond/next/mask/events`）
3. **依赖图建立**（含 reg/mem 特殊依赖）
4. **拓扑排序**（先有序，后分区）
5. **region 构造与分区**
6. **活动传播边构建**（nextActive）
7. **alwaysActive / needActivate 归约**
8. **调度计划生成**（active flag 位图、substep）

缺任何一个，都会变成“可跑但不快”或“快但不正确”。

---

## 3. Wolvrix 必需 pass 清单（MUST）

下面是建议的 **MUST pipeline**，每个 pass 都是可交付项，不是“可选增强”。

## 3.1 `hier-flatten`（必需）

**目标**：把多 Graph/实例层次展平到活动分析目标图；保留 blackbox/extmodule 边界。  
**输入**：含 `kInstance` 的 design。  
**输出**：
- 扁平 op/value 命名空间（层次前缀稳定化）。
- 实例端口连接被替换为直接 def-use 边。
- 外部模块节点标注 `isExternalRegionSeed`（供 alwaysActive 判定）。

**对应 gsim**：`AST2Graph::visitInst` + 前缀命名。

---

## 3.2 `seq-write-normalize`（必需）

**目标**：把寄存器/内存/锁存写统一为活动分析可消费的标准形。  
**输入**：`kRegisterWritePort/kMemoryWritePort/kLatchWritePort`。  
**输出**：
- 校验并补齐 `eventEdge` 与 events 数量一致性。
- 规范 `updateCond` 为 1-bit 逻辑表达式。
- 规范 `mask` 语义（全 0 / 全 1 常量标注）。

**对应 gsim**：`clockOptimize` + 写树归一思路。

---

## 3.3 `activity-dep-graph-build`（必需）

**目标**：建立活动传播依赖图，不仅是普通 def-use，还包括时序与存储依赖。  
**输出**：
- `depPrev/depNext` 等价关系（可放 scratchpad）。
- memory 写->读、reg 写->读的跨拍触发依赖。
- async reset 强制传播边。

**对应 gsim**：`Node::updateDep` + `constructSuperConnect` 前后关系。

---

## 3.4 `activity-toposort`（必需）

**目标**：在依赖图上给出稳定拓扑序。  
**输出**：
- opOrder（或后续 regionOrder 的基础）。
- 对环路给出诊断（不能静默处理）。

**对应 gsim**：`topoSort.cpp`（按 depPrev/depNext 排序）。

---

## 3.5 `activity-region-build`（必需）

**目标**：构造调度基本块（region/supernode 等价物）。  
**输出**：
- 每个 op 的 `regionId`。
- region DAG 与基础统计（size、in/out degree）。

**实现建议**：
- MVP：按 topo 连续切块 + size 上限。
- 后续可接 `region-partition-refine`（性能增强）。

**对应 gsim**：`constructSuperNode` + `graphPartition`。

---

## 3.6 `activity-next-set-build`（必需）

**目标**：预计算“当前 region/value 变化会激活哪些 region”。  
**输出**：
- `nextActiveRegions`。
- 输入口变化激活集合。
- reg/mem writer 的额外激活集合。

**对应 gsim**：`Node::updateActivate()`。

---

## 3.7 `activity-always-on-mark`（必需）

**目标**：识别 alwaysActive 区域并从 next-set 中扣除。  
**输出**：
- `alwaysActiveRegions`。
- `needActivate = nextActive - alwaysActive`。

**对应 gsim**：`alwaysActive` + `updateNeedActivate()`。

---

## 3.8 `activity-schedule-lower`（必需）

**目标**：输出可执行调度计划（不是仅注解）。  
**输出 artifact**：
- substep 序列。
- activeFlags 位布局（id/bit）。
- activateAll 触发规则。

**对应 gsim**：`cppEmitter::genActivate/genStep`。

---

## 4. 可选增强 pass（SHOULD / LATER）

1. `clock-gate-lower`：把门控时钟白名单模式下沉到 `updateCond`。  
2. `region-partition-refine`：类似 gsim graph refine，减少跨区边。  
3. `activity-propagation-prune`：冗余激活边裁剪。  
4. `activity-profile-feedback`：用运行 profile 反哺分区。

这些不是 MVP 必需，但直接影响性能上限。

---

## 5. 推荐执行 pipeline（严格顺序）

建议新增 `sim-activity` 专用 pipeline：

1. `xmr-resolve`
2. `const-fold`
3. `redundant-elim`
4. `dead-code-elim`
5. `hier-flatten`  ← 必需
6. `seq-write-normalize`  ← 必需
7. `activity-dep-graph-build`  ← 必需
8. `activity-toposort`  ← 必需
9. `activity-region-build`  ← 必需
10. `activity-next-set-build`  ← 必需
11. `activity-always-on-mark`  ← 必需
12. `activity-schedule-lower`  ← 必需

`clock-gate-lower` 放在 6 与 7 之间（可选）。

---

## 6. 数据契约（落地必须先定）

为避免 pass 之间“口头约定”，建议统一使用 scratchpad key：

- `sim.flatGraph`：flatten 后图句柄或映射。
- `sim.depGraph`：活动依赖图（节点、边、特殊边类型）。
- `sim.topoOrder`：稳定序。
- `sim.regionMap`：op->region，region 元数据。
- `sim.nextActive`：region->bitset。
- `sim.alwaysActive`：bitset。
- `sim.schedulePlan`：substep + flag layout。

如果需要落盘调试，再镜像到 op attr（debug-only）。

---

## 7. 正确性与性能验收标准

## 7.1 正确性（必须）

1. 与基线仿真逐拍比对（寄存器 + memory + IO）。
2. 多时钟 + 异步复位 case 不退化。
3. extmodule/DPI 副作用时序一致。
4. flatten 前后输出等价。

## 7.2 性能（目标）

至少输出以下统计：
- region 总数。
- 平均每拍激活 region 数。
- `activateAll` 触发频率。
- 总执行时间与基线比。

没有这些指标，就无法判断 pass 是否真正带来收益。

---

## 8. 与 Wolvrix 代码的直接改动点

1. `wolvrix/lib/include/transform/`：新增 8 个 MUST pass 头文件。  
2. `wolvrix/lib/transform/`：新增 pass 实现。  
3. `wolvrix/lib/src/transform.cpp`：注册新 pass 与参数解析。  
4. （建议）新增 `sim-schedule` artifact 输出接口（JSON）。

---

## 9. 实施分期（可执行）

### Phase A（两周）：跑通闭环
- `hier-flatten`
- `seq-write-normalize`
- `activity-dep-graph-build`
- `activity-toposort`
- `activity-region-build`（简单切块）
- `activity-next-set-build`
- `activity-always-on-mark`
- `activity-schedule-lower`（先输出 plan，不接 JIT）

### Phase B（两到三周）：提速
- `clock-gate-lower` 白名单
- `region-partition-refine`
- `activity-propagation-prune`

### Phase C（持续）：工程化
- profile feedback
- 回归基准自动化

---

## 10. 结论

你指出的缺口是准确的：
- **instance flatten 是前提，不是可选项**；
- **topo sort 是中枢，不做无法稳定调度**。

按本文的 MUST pipeline 实施，才是对齐 gsim 实现逻辑、且在 wolvrix 中可真正落地的方案。
