# GrhSIM AM 运行时调度模型简化：严格对齐 legacy 的两阶段 round 模型

日期：2026-07-28
状态：规划（尚未实施）
相关文档：

- 现行 AM 语义：[grhsim-am.md](../../wolvrix/docs/grhsim/grhsim-am.md) §3–§5（本文计划将其替换）
- legacy 运行时模型：[grhsim-scheduling.md](../../wolvrix/docs/emit/grhsim-scheduling.md) "Runtime model" / "Runtime eval"
- 差异分析：[grhsim-am-vs-legacy-analysis-20260727.md](grhsim-am-vs-legacy-analysis-20260727.md)

## 0. 背景与决策

现行 AM 运行时调度模型（epoch + `act.f`/`act.b` + commit 独立通道）在实现中膨胀出一整套
legacy 不存在、且语义收益无法证明的机制：

- commit 双通道 activity（`nextCommitWords_`/`pendingCommitWords_`/`forcedCommitWords_`/
  `capturedCommitWords_` + 独立的 commit summary drain）；
- commit operand 批量快照（`capture_pending_commit_operands`、`kCommitOperandCapture*` 表、
  `preCommitSnapshots`）；
- commit group 静态执行计划（`commitGroupOffsets`/`commitBlockOrder`、
  `execute_next_commit_group`）；
- consume-on-event 的 pending commit event 槽（`dirtyCommitEventSlots_`、
  `pendingCommitEventSlots_`/`Bits`、`completedCommitWrites_` 及
  capture/restore/clear 三个辅助函数）；
- 双缓冲 next-active + swap 的 epoch 推进、summary 位图层、writer-frontier 跨 commit
  Block 激活链。

功能 gate 已关闭（XiangShan CoreMark/NEMU 2k/20k/50k 全过），但 50k host time 为
4,178,703 ms，是 legacy 基线 355,000 ms 的 11.77 倍。2026-07-27 的差异分析给出过
P1–P9 的逐项 emitter 优化计划；本文的决策是**不再做增量优化，而是把 AM 的运行时调度
模型整体替换为 legacy 的 generic fixed-point round 模型**：

1. 每轮严格分 compute、commit 两个阶段，先 compute 后 commit；
2. compute Block 按 active bit 过滤，commit Block 对齐 legacy **总是扫描**（按 guard
   聚合、块内 guard/event 决定写是否发生）；
3. 不动点判断严格简化：一次完整遍历中没有 `act.b` 执行（激发），即视为收敛；
4. 正确性不由形式化证明保证，由 difftest 裁决；
5. activity-schedule 实现收敛：删除 baseline smoke bridge 与 Greedy 分块路径，全仓只
   保留一份从 legacy 移植的 coarsen + segment DP 实现，参数默认值与公式向 legacy
   `ActivityScheduleOptions` 对齐（§3.4）。

EntryBlock B0 保留不变。**旧模型严格删除，不保留兼容开关、不留并行路径**；interpreter
与 C++ emitter 同时切换，AM 规范文档同步改写。

## 1. 目标执行模型

### 1.1 Block 布局与指令约束

```text
B0            EntryBlock（保留，语义不变）
B1 .. Bc      compute Block（组合计算、state read、raw changed、DPI/system call）
Bc+1 .. Bn    commit Block（reg.write / latch.write / mem.write / mem.fill + 判变 + act.b）
```

commit Block 占据连续后缀区间（现行 scheduler 已满足，改为强制不变量）。commit Block
按 normalized event + update guard 聚合分块，对齐 legacy `commitGuardEventBuckets`
的默认行为；同一 event/guard 桶内的写保持静态 priority/effect order。

指令放置约束（validator 强制）：

| 指令 | 允许所在 Block | target 约束 |
| --- | --- | --- |
| `act.f` | 仅 B0 和 compute Block | 更大的 compute BlockId |
| `act.b` | 仅 commit Block | 仅 compute Block（即受写入影响的 reader Block），BlockId 任意 |
| state write | 仅 commit Block | — |
| `changed` | B0 / compute / commit 均可 | 每条 `changed` 独占 `old`，语义不变 |

`act.f` 不指向 commit Block：commit Block 每轮总是扫描，不需要激活边。compute 段内
`act.f` 严格前向，单趟升序扫描天然排空当轮全部 compute 活动——这与 legacy 的
"forward 校验通过后 compute 当轮一定排空"等价，但由 Block 编号规则结构性保证，
不再需要单独校验 pass。

### 1.2 运行时状态

```text
active[b]        每个 compute Block 一个 bit（单一集合；不分 current/next，
                 没有 summary 层，commit Block 不占用激活状态）
firstEval        语义不变
roundCounter     仅诊断用（取代 EpochCounter；超过上限报 "did not converge"）
changed 结果     round-local，见 §1.4
host 状态        onceCompleted / finalized / pending host event，语义不变
```

删除：`NextEpochActive`、epoch 概念、全部 commit 专用 activity/快照/event 槽状态。

### 1.3 eval() 流程

```text
eval(S):
    require Finalized = false
    拷贝 input 端口
    清空 active、清 changed 结果
    execute(B0)                      // 输入净变化 -> act.f 初始激活 compute Block
    if firstEval: 激活全部 compute Block
    loop:
        backwardFired = false
        // compute 阶段：按 BlockId 升序遍历 B1..Bc，不激活则整段跳过
        for b = 1 .. c:
            if active[b]:
                active[b] = false
                execute(Bb)          // act.f 置位更大的 compute bit，本趟内被消费
        // commit 阶段：按 BlockId 升序遍历 Bc+1..Bn，总是执行
        for b = c + 1 .. n:
            execute(Bb)              // 块内 guard/event 决定写是否发生；
                                     // 实际写变 -> act.b 置位 reader bit 并置 backwardFired
        清 changed 结果              // round 末，见 §1.4
        roundCounter += 1；超上限则报错
        if not backwardFired: break
    收尾：输出端口、firstEval = false（正常返回时）
```

要点：

- `act.f` 只允许指向更大的 compute BlockId，在**同一趟 compute 扫描内**被消费；每个
  compute Block 每轮最多执行一次（bit 幂等，前向约束保证被消费的 bit 本趟不会被
  重新置位）。
- `act.b` 只指向已经扫过的 compute 段，置位的 bit 留给下一轮；它是唯一的"需要
  下一轮"信号。
- 不动点判断就是循环条件：一趟完整遍历下来没有任何 `act.b` 激发（event == 1）即
  收敛。逐项对应 legacy 的 `pending_eval_round = commit_activated_readers_`。

### 1.4 changed / event 生命周期

先区分 `changed` 指令触碰的两块状态：

- `old` 基线：检测后立刻 `old = new`，跨轮、跨 eval 一直保持。它是"检测状态"，
  不需要也不允许被清理。
- result（event Variable）：可能被其他 Block 在执行点读取的"通信媒介"。是否需要
  轮末清理按消费者位置分类：

| result 的消费者 | 轮末清理 | 理由 |
| --- | --- | --- |
| 全部在同一块内（典型：同块 `act.f`/`act.b`） | **不需要** | 块每次执行时 `changed` 必定先于消费者重写 result；块不执行时消费者也不执行，旧值没有读者 |
| 存在跨块消费者（`reg.write`/`mem.write` 的 event/guard operand、其他块的 host/组合指令） | **必须清零** | 生产块下一轮若未被激活就不重新执行，而消费块（尤其常扫描的 commit Block）仍会读，残留的 event=1 会让写每轮重复发生、`act.b` 每轮激发，不动点判断直接失效 |

由此得到规则：

- 轮末清空集合 = **跨块消费的 `changed` 结果子集**：为真才入 dirty-list，轮末只清
  这些。commit Block 内的判变 `changed`（喂同块 `act.b`）属同块消费，且 commit
  Block 每轮必跑、result 每轮重写，不进 dirty-list。
- compute 阶段产生的跨块 event（如 clock posedge）在同一轮的 commit 阶段可读；下一轮
  若未重新产生则为 0。这与 legacy 的 event edge slot "round-local、下轮重新产生"
  完全一致，取代现行 consume-on-event/pending 语义。跨 eval 衔接自然成立：每轮末都
  清，最后一次循环结束时已归 0，下次 eval 首轮天然干净。
- B0 的输出 event 同理：输入 clock 的 posedge 在 B0 检测、流向其他块（commit 的
  `reg.write`、compute 里的 `dpi.call`/`system.task`）属典型跨块消费，不需要同块。
  B0 每次 eval 只执行一次且不会重跑，这类 event 必须轮末清，否则会在本次 eval 的
  所有轮次保持为 1，导致下游写/DPI 每轮重复触发。
- `changed` 的 `old` 基线语义不变：独占、`Init = undef`、执行后 `old = new`；B0 的
  基线跨 eval 保持，用于检测两次调用间的外部净变化。
- validator 约束：act 消费的 event 必须同块先行写入；跨块 event 只允许流向 state
  write 的 event/guard operand、host 指令（`dpi.call`/`system.task`）的 event
  operand 或普通指令的数据 operand，且生产块 BlockId 必须小于消费块（保证同轮先产
  后读；B0 为 0 号块，天然满足）。

### 1.5 state write 与 reader 重激活

- commit Block 每轮总是执行，对齐 legacy "generic round 调用全部 commit batch"：写
  指令按文本顺序读取执行点可见的操作数和 event，由块内 guard/event 决定是否真正
  写入；**没有** operand 快照、没有 pending event、没有跨轮保留。
- 实际变化检测与写路径融合（对齐 legacy 的 tracked write）：写使 visible state 实际
  变化且存在 reader 时产生块内 event，供同块 `act.b` 消费，激活该 state 的 reader
  compute Block（对齐 legacy `stateHeadSupernodesBySymbol` 置位）。
- 同一 target 多写：由 commit 段内静态 BlockId 顺序保证 priority/effect order；reader
  一律在下一轮才执行，只看到本轮最终值，因此**不存在**轮内瞬态暴露问题——现行
  writer-frontier（earlier writer 快照 guard + `act.f` 激活 final frontier）机制整体
  删除。可能出现"写变又被写回"导致的多余一轮激活，legacy 行为相同，属允许的多执行。

> **2026-07-28 difftest 修正（§1.5 第一条部分收回）**：XS difftest 裁决表明，"没有
> operand 快照"在"commit 写指令的操作数**直接引用寄存器 state**"时不成立——就地
> read-new 会破坏 commit 段内/段间的先写后读链（XiangShan BPU 预测 PC 管线
> 16954→17116，首取指地址被多推进一个 64B 块）。legacy 的正确语义是 read-old（sink
> 数据来自 compute 已收敛值）。修复方式不是恢复任何运行时快照机制，而是在 lowering
> 把这类操作数替换为快照变量 + 一条普通 compute `assign`（commit 段前收敛、随
> state 变化经 act.b 重激活），其余语义（无 capture 表、无 pending event、无跨轮保留）
> 不变。详见 `grhsim-am-pipeline.md` 的 2026-07-28 进展记录。

### 1.6 host / DPI / system call

- host 指令仍在 compute Block 中；`event_mode = immediate/pending`、once/final 生命周期
  语义不变。pending host event 是逐调用的跨轮保留状态（轮内未成功则保留到同一 eval
  的后续轮），与本次删除的 commit 调度机制无关，予以保留。
- `finalize()` 语义不变。

### 1.7 首次 eval 与未定义行为边界

- 首次 eval 激活全部 compute Block（commit Block 本就每轮扫描），正常返回时清
  `firstEval`，不变。
- `undef` 初值、首次 event 的 AM 层未定义行为边界不变。

## 2. 与 legacy 的逐项对齐

| 方面 | legacy（grhsim-scheduling.md） | 新 AM 模型 |
| --- | --- | --- |
| 迭代单位 | fixed-point round | round（取消 epoch） |
| 每轮结构 | 先按生成顺序调用全部 compute batch，再全部 commit batch | compute 阶段升序遍历 B1..Bc，commit 阶段升序遍历 Bc+1..Bn |
| compute 执行过滤 | batch 内按 active bit 过滤 | 按 active bit 整段跳过 |
| commit 执行过滤 | batch 总是调用，guard/event 过滤 sink op | commit Block 总是执行，块内 guard/event 决定写入 |
| commit 分块 | 按 normalized event + update guard 聚合 | 同左（`commitGuardEventBuckets` 默认行为） |
| compute 当轮排空 | emitter 校验激活严格前向后成立 | `act.f` 前向约束结构性保证 |
| 下轮判定 | `pending_eval_round = commit_activated_readers_` | 任一发 `act.b` 激发 |
| reader 重激活 | state 写变后查 `stateHeadSupernodesBySymbol` 置 reader bit | commit Block 内判变 event + `act.b` 指向 reader compute Block |
| event 生命周期 | event edge slot round-local，round 末清 | changed 结果 round-local，round 末清 |
| 输入播种 | eval seed 比较 `prev_*`，置 input head bit / event slot | B0（保留）：`changed` + `act.f` |
| 首次 eval | 激活全部 compute supernode | 激活全部 compute Block |
| 多写 priority | commit node 链 + 静态顺序 | commit 段 BlockId 静态顺序 |
| 不收敛 | 无上限（死循环） | 保留 round 上限诊断（实现保护，非语义） |

## 3. 改造点

### 3.1 严格删除清单

`wolvrix/lib/grhsim/am/cpp_emitter.cpp`：

- `nextActiveWords_`/`nextActiveSummary_` 双缓冲与 swap、summary 位图两层结构；
- `nextCommitWords_`/`nextCommitSummary_`/`pendingCommitWords_`/`pendingCommitSummary_`/
  `forcedCommitWords_`/`capturedCommitWords_` 及 `drain_next_active_activity()`/
  `drain_next_commit_activity()`/`has_pending_commit_blocks()`；
- `capture_pending_commit_operands()`、`kCommitOperandCapture*` 表、`preCommitSnapshots`；
- `commitGroupOffsets`/`commitBlockOrder`、`execute_next_commit_group()`；
- `dirtyCommitEventSlots_`/`pendingCommitEventSlots_`/`pendingCommitEventBits_`/
  `completedCommitWrites_`、`capture_commit_events()`/`restore_commit_events()`/
  `clear_pending_commit_events()`、`mark_commit_changed_result()` 的 commit 专用路径；
- eval 主循环中的 epoch 推进逻辑（换成 §1.3 的两阶段遍历 + `backwardFired` 循环）。

`wolvrix/lib/grhsim/am/interpreter.cpp`：同一套机制的解释器副本（`nextActive`、
`pendingCommitBlocks`/`forcedCommitBlocks`、`pendingCommitEvent*`、epoch 循环），同步
替换为同一 round 模型。

`wolvrix/lib/grhsim/am/production_activity_schedule.cpp`：

- commit group 执行计划的构建（`commitGroupOffsets`/`commitBlockOrder`）；
- commit operand capture 表与 `preCommitSnapshots` 的物化；
- commit event 槽分配与 consume-on-event 物化；
- writer-frontier 跨 commit Block 的 `act.f` 链（含 signed guard 的 unsigned 规范化
  专用逻辑）；
- 指向 commit Block 的激活边（`act.f` 不再以 commit Block 为 target，commit Block 常
  扫描，相关边生成与统计全部删除）。

文档：`grhsim-am.md` §3–§5（State、`act.f`/`act.b` 语义、eval 流程）按 §1 改写；
`grhsim-am-pipeline.md` §3.2、§4.3、§7 相应段落更新；`grhsim-am-instructions.md` 中
`act`/`changed` 与 commit event 相关条目同步修订。

### 3.2 保留不动

- B0 EntryBlock 与其 `changed` + 组合派生 + `act.f` 形态；
- 静态 Block 划分算法（SCC atom、coarsen + segment DP、compute 侧容量上限）；commit
  侧按 event/guard 桶聚合及容量上限；
- `ProgramInterface`、single-result-writer normal form、C++ emitter 的分片/ABI 外壳；
- changed 结果 dirty-list 稀疏清零；
- host 调用语义（immediate/pending、once/final）、finalize；
- firstEval、undef 基线等未定义行为边界。

### 3.3 Scheduler / validator 规则变化

- commit Block 连续后缀（`kCommitBlockBegin/End`）成为 validator 强制不变量；
- `act.f`/`act.b` 按 §1.1 表校验所在 Block 类别与 target 范围（结构性合法性检查）；
- `act.b` target 取自该 commit Block 所写 state target 的 reader compute Block 集合
  （来自 state reader set，对齐 legacy `state_read_supernodes`）；
- 同 target 多写仅由 commit 段静态顺序表达，scheduler 保持 priority/effect order 与
  BlockId 顺序一致；
- 行为正确性（激活是否完备、reader 集合是否精确）不由 validator 形式化证明，统一由
  difftest 裁决；validator 只保留结构性检查。

### 3.4 activity-schedule 收敛：全仓只保留 legacy 对齐实现

当前 AM 侧存在两份调度实现，加上 production 内部的两种分块模式，实际有三条路径。
收敛后只保留一条：

| 现行实现 | 处置 | 理由 |
| --- | --- | --- |
| `lib/grhsim/am/activity_schedule.cpp` + `include/grhsim/am/activity_schedule.hpp`（`BaselineActivityScheduleStage`，B0+B1 单块 smoke 桥） | **删除** | Phase 0 迁移桥，不做拓扑调度、不作物件划分，与 legacy 无任何对应；`test_pipeline.cpp`（7 处）、`test_cpp_emitter.cpp`（3 处）的引用改用 `ProductionActivityScheduleStage` 重写或删除 |
| `AmBlockFormation::Greedy`（production 默认，Kahn ready-set 装桶） | **删除**，连同 `AmBlockFormation` 枚举 | 不是 legacy 形态 |
| `AmBlockFormation::CoarsenDp` → `scheduleGrhSimAmActivityBlocks`（`grhsim_am_activity_schedule.cpp`，SCC atom → out1/in1/sibling coarsen → topo 序列 segment DP） | **保留，成为唯一分块实现** | 从 legacy `activity_schedule.cpp` 逐行移植（coarsen 三 stage + 连续分段 DP），commit 侧按 event/guard 桶聚合也对齐 `commitGuardEventBuckets` |

删除 baseline 后，将 `grhsim_am_activity_schedule.{hpp,cpp}` 更名为
`activity_schedule.{hpp,cpp}`，全仓只留一份 activity schedule 源文件。

参数对齐（`ActivityScheduleOptions`，默认值与公式向 legacy 看齐）：

| AM 现行 | 现行默认 | 处置 | legacy 对应 |
| --- | --- | --- | --- |
| `maxInstructionsPerBlock` | 128 | 保留，对齐 `maxOpInComputeSupernode` | 128 |
| `maxCommitInstructionsPerBlock` | 4096 | 保留，对齐 `maxOpInCommitSupernode` | 4096 |
| `maxStateWritesPerBlock` | 4096 | **删除** | legacy 无此维度，commit 只受 `maxOpInCommitSupernode` 约束 |
| `enableCoarsening` | true | 保留，对齐 `enableCoarsen`（chain merge 的 out1/in1 与 siblings 均内建，不另设开关） | `enableCoarsen`/`enableChainMerge` = true |
| `blockFormation` | Greedy | **删除**（随枚举） | — |
| `dpSegmentPenalty` | 64.0 | 默认改 **1.0**，对齐 legacy `cost(segment) = incoming_distinct_boundary_values + 1` | 硬编码 +1 |
| `dpCoarsenBudget` | 0（自动 = max/8，≥16） | 自动公式改 **32 × maxInstructionsPerBlock**，对齐 legacy coarsen 上限 | `32 * maxOpInComputeSupernode`（= 4096） |
| `collectStats` | false | 保留（工程选项，不影响调度结果），对齐 `summary_stats` 输出 | `summary_stats` |
| —（AM 无对应） | — | 不引入：AM atom 是指令依赖图的 SCC，没有 legacy 的 compute-node 吸收步骤 | `maxOpInComputeNode` = 8192 |

legacy 其余调度选项（`finalTopoPolicy`、`splitOversizeComputeNodes` 等）按需要在
CoarsenDp 实现内对齐语义，不新增 AM 独有开关。

## 4. 语义影响与风险

- **可观察行为以 legacy 为准，不保证与现行 AM 逐 bit 相同**：consume-on-event 的边角
  （跨 epoch 保留的 commit event 与旧 operand 组合）是现行模型独有的语义，删除后以
  legacy round-local event 为准。
- **正确性由 difftest 裁决**：不做激活完备性、reader 精确性、host 调用次数的形式化
  证明；裁决手段为 XS CoreMark/NEMU difftest（2k -> 20k -> 50k 严格升档）、HDLBits
  全量、xs-components 与 legacy 的 bit-exact 对比，以及既有 differential corpus 的
  两后端（interpreter / C++ emitter）逐 eval 一致。
- **host 调用次数**：合并 compute Block 的重复执行语义不变；如有疑虑用逐次
  call-trace 对比排查，同样以 difftest 结论为准。
- **性能预期**：单一位图 + compute 过滤扫描 + commit 常扫描后，每轮开销应与 legacy
  generic round 同量级；50k CoreMark 目标是回到 legacy 基线（355,000 ms）附近的
  同一数量级，具体阈值在 Phase 0 基线上批准。
- **解释器与生成代码必须同构**：两个后端共用同一 round 语义。

## 5. 实施步骤与验收

1. **规范与 validator**：改写 `grhsim-am.md` §3–§5、指令集相关条目；实现 §3.3 的
   结构性校验。Gate：非法 act 放置/target 范围被拒绝。
2. **Scheduler**：删除 §3.1 列出的物化逻辑，按新规则生成 `act.f`/`act.b` 与判变；
   按 §3.4 删除 `BaselineActivityScheduleStage`、`AmBlockFormation::Greedy` 与
   `maxStateWritesPerBlock`，`CoarsenDp` 成为唯一分块实现并对齐参数默认值。
   Gate：`tests/grhsim/am` 单测更新后全绿；全仓只剩一份 activity schedule 源文件。
3. **运行时**：`cpp_emitter.cpp` 与 `interpreter.cpp` 同步换成 §1.3 主循环，删除旧
   机制代码（不留开关）。Gate：differential corpus 两后端逐 eval 一致。
4. **回归**：HDLBits 全量；xs-components 代表用例与 legacy 输出 bit-exact。
5. **XS 产品 gate**：CoreMark/NEMU 严格按 2k -> 20k -> 50k difftest 升档；三档全过
   且 host time 进入批准的阈值后，更新 `grhsim-am-pipeline.md` 的进展记录与
   notepad。

完成标准：仓库中不存在 epoch/commit 双通道/operand capture/commit group/consume-on-event
的任何实现与文档残留；AM 与 legacy 的运行时模型可以用同一段伪代码描述（本文 §1.3）；
全仓只保留一份 activity schedule 实现（legacy 移植的 coarsen + segment DP），不存在
baseline/Greedy 第二路径与 AM 独有的调度参数。
