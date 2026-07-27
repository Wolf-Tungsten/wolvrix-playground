# GrhSIM AM 路线 vs legacy 路线：activity-schedule 与生成代码差异分析

日期：2026-07-27
代码基线：`wolvrix` @ `7c979c7`（工作区另含 1 处本地修复，见 §5.3）
实验 case：`testcase/xs-components` 的 `XsReal053FtqFtqLarge`（356 KB SystemVerilog，含寄存器堆/队列状态）
实验产物：`build/analysis/am_vs_legacy_20260727/`（legacy、am/model-greedy、am/model-codp 三份生成模型 + 对比驱动）

## 0. 摘要

- **调度算法**：两条路线的 compute 侧调度是同构的——都是"依赖图 → 粗化（out1/in1/sibling 三类合并）→ topo 序列上的连续分段 DP（cost = 跨段输入变量数 + 段罚）"。AM 的 segment DP 代码是从 legacy 逐行移植的（`grhsim_am_activity_schedule.cpp:532` 注释自证）。差异在输入表示（GRH op 图 + session side table vs AM 线性指令流 + 强类型 ScheduledProgram）、atom 定义（clone 后的 op cluster vs 指令级 SCC）、粗化规则细节、以及 commit 侧的物化方式。
- **生成代码**：activity 传播的**语义**一致（都是"值变化 → 置位目标执行单元 → eval 内不动点"），但**机制**不同：legacy 是编译期常量掩码 + 静态批量 dispatch + 值级内联检测；AM 是逐 target 函数调用置位 + 位图动态扫描 + Block 尾部物化 detector 指令。两条路线在同一 case 上 20,000 个随机向量输出 **bit-exact 一致**（§5.2）。
- AM 当前为语义清晰性付出的代价值得注意：本 case 上 AM 的 detector 站点数约为 legacy 的 2.5 倍（1374+153 vs 600），每个 commit 写各配一个 posedge 检测器（153 个）而 legacy 全设计共享 1 个 event slot；小 case 上 AM 运行时间约为 legacy 的 8 倍（与 XiangShan 上 ~11.8x 的既有记录同向）。
- **发现并修复了 HEAD 的一个 AM emitter 编译 bug**（`emitEventfulStateWrite` 少发一个 `}`，commit `7c979c7` 引入，见 §5.3）。

## 1. 两条路线与实验设置

```text
legacy:  read_sv → normalize passes → activity-schedule pass（写 session side table）
         → emit_grhsim_cpp（读 Graph + session，生成 GrhSIM_<top>）
AM:      read_sv → normalize passes → post-stats JSON
         → grhsim-am-lower-json = GRH→AM lowering → production activity scheduler
           → ScheduledProgram/ExecutableModel → AM C++ emitter
```

- legacy 实现：`wolvrix/lib/transform/activity_schedule.cpp`（6510 行调度 pass）+ `wolvrix/lib/emit/grhsim_cpp.cpp`（23429 行 emitter）。
- AM 实现：`wolvrix/lib/grhsim/am/`（lowering 2749 行、production_activity_schedule 1804 行、grhsim_am_activity_schedule 745 行、cpp_emitter 4555 行）。
- 复现命令（xs-components 的 Makefile 已带 `grhsim-am-emit` target，本次直接复用其等价命令行）：

```bash
# legacy（同时落 AM 共用的 post-stats JSON）
python3 testcase/xs-components/scripts/emit_grhsim.py \
  --sv <case>.sv --top XsReal053FtqFtqLarge --out legacy/model \
  --json legacy/graph.json --pre-schedule-json am/normalize/<case>.json \
  --max-op-in-compute-supernode 128 --max-op-in-commit-supernode 768
# AM（greedy 是 production 默认；coarsen-dp 是可选）
wolvrix/build/bin/grhsim-am-lower-json am/normalize/<case>.json XsReal053FtqFtqLarge \
  --emit am/model-greedy --block-formation greedy
```

两侧 cap 对齐：legacy `max_op_in_compute_supernode=128`，AM `maxInstructionsPerBlock=128`。

## 2. Activity-schedule 对比

### 2.1 依赖图的建立：输入与边

| | legacy | AM |
|---|---|---|
| 输入 | 单个 normalized GRH graph 的 **operation 图**（`activity_schedule.cpp:6127`） | `LinearProgram` 的**线性指令流**（已 lower 到 AM 指令集） |
| 节点 | op → compute node / commit node（中间层）→ cluster | 指令 → **SCC atom**（指令依赖图的强连通分量，`production_activity_schedule.cpp:212` 迭代 Tarjan）→ cluster |
| def-use 边 | operand 的 def-use | `DefUseIndex`（同左），但**过滤两类 operand**（`production_activity_schedule.cpp:54`）：`changed.*` 的 old 基线不算 use（detector 私有历史）；state 写的 target 不算 use（reader 激活走 activation edge，不进数据依赖图） |
| 顺序边 | ordered memory write（priorityGroup/priority）保持不可拆 unit；ordered DPI group 合成 indivisible node | `orderedEffects` 显式组内相邻连边 + 所有 `hasOrderedEffect` 指令（reg/mem/latch 写、system/DPI）按线性序**隐式成链**（`production_activity_schedule.cpp:964`） |
| memory 依赖 | 无 alias 分析 | 同样无 alias 分析；写之间靠隐式有序链保序，read-after-write 靠**相位分离**（commit BlockId 恒大于 compute）+ writer→reader activation edge（整 memory 粒度保守激活） |
| 中间预处理 | `cloneSourceUsesForCompute`（`:1831`）：把 Source（reg/mem read、const）→ Compute 的 use clone 一份吸收进 compute node（本 case 克隆 819 个，所以 legacy 统计的 5891 op > AM 看到的 5072 op） | 无 clone；AM lowering 阶段已把 state read 变成显式指令 |

要点：AM 把 legacy 的"op 分类（Source/Sink/Compute/Declaration）+ clone"这一步换成了"指令级 def-use + SCC atom"。SCC atom 是不可拆调度单元（组合环在 AM 层显式成环，legacy 靠前端的 `comb-loop-elim` 保证无环、靠 node builder 吸收局部组合）。混合 atom（同 SCC 内既有 commit 又有 compute 指令）直接报错（`production_activity_schedule.cpp:1100`）。

### 2.2 粗化（coarsening）

两边都是三类合并规则 + DSU，但规则定义和预算不同：

- **legacy**（`activity_schedule.cpp:5571-5696`）：每轮依次跑 out1（单后继并入后继 `:4531`）/ in1（单前驱 `:4625`）/ **siblings（前驱集合相同批量合并 `:4425`）**；合并上限 = `32 × maxOpInComputeSupernode`（即 4096 op，`:720`）；大图尾部保护（cluster ≥100k 且连续 3 轮减少 <1024 则停，`:716-718`）。
- **AM**（`grhsim_am_activity_schedule.cpp:247-417`）：**每轮只跑一种规则**，Out1/In1/Sibling 三轮转；Sibling 改成"同一前驱且 Kahn 最长路径同层"的后继链式合并（`:285-353`）；预算 = `max(maxInstructionsPerBlock/8, 16)` = **16 条指令**（`production_activity_schedule.cpp:1271`）；同样的尾部早退常量（`:21-23`）；并有显式的无环安全性论证注释（`:226-235`，指出混用规则不安全，这是改成单规则轮转的原因）。

即：legacy 粗化激进（簇可达 4096 op），AM 刻意保守（16 指令/簇）——AM 把"压图规模"交给粗化、把"选边界"交给 DP，分工更清。

### 2.3 Segment DP：同一公式的移植

两边都在**粗化后 topo 序列上做连续分段**（不是任意 DAG 划分）：

```text
dp[end] = min over start ( dp[start] + incomingCost(start,end) + segmentPenalty )
incomingCost = 段内使用、但定义在段外（或无定义）的去重变量数
约束：segment 指令/op 数 ≤ cap；单个超限 cluster 允许自成一段
tie-break：同 cost 偏好更长的段；双 stamp 数组 O(1) 摊还维护 incoming
```

AM 版是逐行移植（`grhsim_am_activity_schedule.cpp:532-611` 对 `activity_schedule.cpp:4719-4839`），差异四点：

1. **penalty**：legacy 固定 1.0（`:5734-5740` 调用点）；AM 可配、默认 **64.0**（`pipeline.hpp:154`，`dpSegmentPenalty`）——更高的段罚倾向更少更大的 Block。
2. **permanent boundary**：AM 新增——定义在 compute atom 之外（commit-defined、外部输入、无定义）的变量对每个消费段恒计入 incoming（`:457-460`），把 state read/输入显式建模为永久激活源；legacy 留过 `valueWeights` 口子但生产传 nullptr。
3. 节点从 op cluster 换成 atom cluster；commit atom 内的 use 不参与（`:498-500`）。
4. legacy 生产路径只有这一套（coarsen+DP）；AM 默认走 **Greedy 装桶**（`pipeline.hpp:153` 默认 `AmBlockFormation::Greedy`），coarsen-dp 需显式 `--block-formation coarsen-dp`。Greedy 无双局 DP，按 class 分开的 ready 堆在 cap 内装桶（`production_activity_schedule.cpp:1307-1381`）。

### 2.4 commit 侧分块

- **legacy**：sink op 按 normalized event key 分组（`:893`），再按 update guard 分桶（`:1212`，上限 4096）；所有 commit node 串成一条链；emitter 侧 1 个 commit node = 1 个 commit supernode。本 case：`commit_event_keys=1`（全设计只有 posedge clock 一个事件）→ 1 个 commit supernode 装 153 个写。
- **AM**：commit atom 按 `(commitEventRank, guardRank, minInstruction)` 确定性 Kahn 排序，**同一 eventRank 桶内**在 cap（4096 指令 / 4096 state 写）内合并（`grhsim_am_activity_schedule.cpp:664-725`）；event 规范化为 (kind, watched variable)（`production_activity_schedule.cpp:335`）。本 case 同样得到 1 个 commit Block。
- AM 额外有 **commit 执行计划**（`buildCommitExecutionPlan`，`:579-819`）：对 commit Block 子图求 SCC 分组（互相依赖的写必须同批提交）、组间拓扑排序，以及 **commit operand capture**（guard/addr/data 在 commit 前批量快照到 fresh 变量，本 case 249 个 capture）——这些在 legacy 里没有对应物（legacy 的 commit 每轮无条件扫描、直接读 live 值）。

### 2.5 激活边（activity 传播边）的生成

- **legacy**：pass 导出扁平 session 表 `value_fanout`（value → 目标 supernode）+ `state_read_supernodes`（state → reader supernode），emitter 读表后构建 `boundaryFanoutByValue`（过滤掉 commit target，`grhsim_cpp.cpp:7690-7727`）。传播关系只是数据表，没有"指令"形态。
- **AM**：显式生成四类 `ActivationEdge`（`production_activity_schedule.cpp:1461-1568`）：
  1. 外部输入：source = B0；
  2. 跨 Block def-use（含同 Block 内 use 早于 def 的环回）；定义指令本身是 `changed.*` 时标 `directEvent`（raw event 不再套新 detector）；
  3. **state final-writer → reader**（每个 target 只取最大 (block, position) 的写前沿，`:1507-1524`）；
  4. writer-frontier 前递（写跨多个 commit Block 时，较早 writer 插 `ReduceOr(guard)` 快照 + `act.f → finalWriterBlock`，保证一个 target 只有一个 watcher）。
  然后**物化为真实指令**（`appendWatchGroups` `:847-904`）：按 (sourceBlock, variable, directEvent) 分组，每组新建 old/event 两个变量 + 一条 `changed.any` + forward/backward 各一条 `act.f`/`act.b`（多 target 合并成一条 act 的 targets 列表），追加在 source Block 尾部。

### 2.6 调度实测数据（XsReal053FtqFtqLarge）

| 指标 | legacy | AM greedy | AM coarsen-dp |
|---|---|---|---|
| 输入规模 | 5072 op / 4775 value（clone 后 5891 op） | 4656 linear 指令 / 5081 变量 | 同左 |
| 计算单元 | 24 compute supernode（含 1457 compute node） | 36 compute Block | 37 compute Block |
| commit 单元 | 1 commit supernode（153 写） | 1 commit Block（153 写，249 capture） | 同左 |
| 调度产物规模 | — | 7557 scheduled 指令 | 8293 |
| detector（生成代码中站点数） | 600 个 tracked-value 检测点 | 1374 changed + 153 commit-event | 1742 + 153 |
| 激活边/传播语句 | 337 条掩码传播语句（初始边界边 1866） | 2441 个 activate 调用点 | 2525 |
| 生成 C++ 源体积 | 1.16 MB | 1.56 MB | 1.59 MB |
| 调度耗时 | （pass 内，秒级以下） | schedule 3 ms | schedule 3 ms（coarsen 1 ms） |

注：AM greedy 与 coarsen-dp 在此 case 上 Block 数接近（36 vs 37），因为 greedy 的 128 cap 装桶与 DP 切割在这个规模上效果相近；XiangShan 规模才有区分度。

## 3. 生成代码对比

### 3.1 总体结构

| | legacy | AM |
|---|---|---|
| 文件 | `*_sched_<B>.cpp`（batch 函数）+ `*_eval.cpp` + `*_state*.cpp` + `*_runtime.hpp` | `*_blocks_<S>[_part_P].cpp`（巨型 `switch(block)`，每 Block 一个 case）+ `*_runtime.cpp` + `*_support.hpp`；按 2048 Block / 4 MiB 分片多 TU |
| 执行单元 | supernode；batch 函数内按 8-bit activity word 分块 | Block；`execute_block` 一级 dispatch → `execute_blocks_<S>` switch |
| 值存储 | 分类槽数组：`value_bool_slots_` / `value_u64_slots_` / `value_words_N_slots_` / `state_logic_storage_`，带语义化引用名和 op 注释 | 扁平 `values_[]`（≤64bit 一律 uint64 槽）+ `wideValues_[]` word 池 + `realValues_`/`stringValues_`；块内逃逸分析把局部值降为 `local_N`（ST00009） |
| activity 存储 | `supernode_active_curr_[4]`（**8-bit**/word，byte 内 8 个 supernode） | `activeWords_`/`nextActiveWords_`（**64-bit** packed）+ 二级 summary + commit 专用 4 个位图（pending/forced/next/captured） |

### 3.2 eval 主循环

**legacy**（生成的 `*_eval.cpp`，直接 dispatch）：

```cpp
// 输入变化播种：内联比较 + 直接置位目标 supernode（编译期常量掩码）
if (!initial_eval && ((io_ctrl != prev_in_io_ctrl))) {
    grhsim_or_active_u16(supernode_active_curr_.data(), 0u, UINT16_C(32797));
    pending_eval_round = true;
}
event_edge_slots_[0] = event_baseline_initialized_ ? grhsim_classify_edge(prev_in_clock, clock) : none;
while (pending_eval_round) {                    // 无 round 上限
    pending_eval_round = false;
    eval_compute_batch_0(); eval_compute_batch_1(); eval_compute_batch_2();
    commit_activated_readers_ = false;
    eval_commit_batch_3();                       // commit batch 每轮无条件扫描
    pending_eval_round = commit_activated_readers_;   // 前向校验已证明，免扫 bitset
    event_edge_slots_[0] = grhsim_event_edge_kind::none;  // event 是 round 级信号
}
```

**AM**（生成的 `*_runtime.cpp`）：

```cpp
values_[153] = clock & mask; ...                 // 端口拷入 values_[]
activeWords_.fill(0); nextActiveWords_.fill(0); pendingCommitWords_.fill(0); ... // 清 8+ 个位图
clear_changed_results();                          // 稀疏清上一 eval 的脏 event
execute_block(0);                                 // B0：用 changed 指令检测输入净变化
if (initial) activate_all_blocks();
while (true) {
    execute_active_blocks();                      // 64-bit 位图 + summary 动态扫描 dispatch
    if (has_next_active_blocks()) {               // epoch 推进：整数组拷贝 next→curr
        activeWords_ = nextActiveWords_; pendingCommitWords_[w] |= nextCommitWords_[w]; ...
        ++epochCounter_; clear_changed_results();
        if (epochCounter_ > 1000000) throw ...;   // 有收敛上限
        continue;
    }
    if (has_pending_commit_blocks()) {            // commit 相位
        capture_pending_commit_operands(); capture_commit_events(); restore_commit_events();
        if (!execute_next_commit_group()) throw ...;
        ...
    }
    break;
}
```

结构性差异：legacy 的 batch 调用是**编译期展开的直接调用**（batch 内自查 activity word，空调用代价极小）；AM 每个 Block 都要经过 `execute_block` → `switch` 间接 dispatch（外加 runtime profile 计数分支）。legacy 的 round 收敛条件经前向校验后简化为一个 bool；AM 每 epoch 做数组拷贝 + 稀疏清零 + commit event 保存/恢复。

### 3.3 输入播种与 B0

- **legacy**：输入检测内联在 `eval()` 里——每个输入一次比较，命中后直接把编译期算好的目标掩码 OR 进 activity bitset；输入基线 `prev_in_*` 在 eval 收尾更新。clock 等 event 输入额外做一次 `classify_edge` 写入共享 event slot。
- **AM**：输入检测是 **B0（EntryBlock）里的普通 `changed.any` 指令**（`grhsim-am.md:314-321` 规范）：

```cpp
case 0: {
    set_changed_result(5331, values_[153] != values_[5330]);   // clock 净变化
    values_[5330] = values_[153];                              // old 基线无条件更新
    if ((values_[5331] != 0)) {
        activate_forward(18); activate_forward(19); ...        // 每个 reader Block 一次调用
    }
    ...
}
```

语义等价（都是"跨 eval 的净变化 → 初始激活"，0→1→0 不产生虚假激活），但 AM 走通用 detector 路径，每次 eval 对每个输入付出 compare + dirty 簿记 + 逐 target 调用；legacy 一次比较一条掩码。

### 3.4 activity 的传播：和 legacy 是否一致？

**结论：传播语义一致，实现机制不同。**

语义上两边都是"值变化 → 置位目标执行单元 → 同一 eval 内不动点直到无新激活"，且都要求严格前向（legacy 有编译期校验 `validateForwardComputeActivations`；AM 规范要求 `act.f` 只指更大 BlockId，`grhsim-am.md:301`）。机制差异四处：

**(a) 检测位置/粒度。** legacy 在**每个 tracked value 的赋值点内联检测**（跨 supernode 边界的值，本 case 600 点）：

```cpp
const bool next_value = ((io_in0) >> 61) & UINT64_C(1);
const bool grhsim_changed_626 = (grhsim_value_626_0_slot != next_value);
grhsim_any_changed_0_0 |= grhsim_changed_626;   // 汇入 deferred 聚合组
grhsim_value_626_0_slot = next_value;           // 写回缓存值
```

AM 只在 **Block 尾部的 watch group** 检测（每个 (source Block, 被外块使用的变量) 一组，本 case 1374+153 点）：

```cpp
set_changed_result(5349, values_[170] != values_[5348]);   // event 入 values_[] + 脏表
values_[5348] = values_[170];                              // old 无条件更新
if ((values_[5349] != 0)) { activate_forward(2); ... }
```

AM 的 detector 是 AM 指令流里的真实指令（可验证、可解释），legacy 的检测是 emitter 私有代码模式。AM 检测点更多是因为 Block 更小（36 vs 24）且每条跨块 def-use 都物化；legacy 通过 `grhsim_any_changed_<sn>_<i>` 把扇出重叠的检测聚合成组，supernode 末尾一次性刷出（`buildDeferredActivationGroups`，`grhsim_cpp.cpp:5244`）。

**(b) 传播代码形态。** legacy 是**编译期常量掩码**（小扇出按 8/4/2/1 字节聚合 `grhsim_or_active_u64/u32/u16`，大扇出 ≥32 用 `kActivationMasks[]` 表 + 循环；同 word 的目标直接接力给局部 `activeWordFlags`，batch 结束才回写全局）：

```cpp
activeWordFlags |= (-static_cast<std::uint8_t>(grhsim_any_changed_0_0)) & UINT8_C(32);  // 无分支
supernode_active_curr_[1u] |= (-...) & UINT8_C(8);
```

AM 是**逐 target 函数调用**，目标 BlockId 是编译期常量但置位逻辑在运行时函数里：

```cpp
if ((values_[5349] != 0)) {
    activate_forward(2);      // activeWords_[2/64] |= bit; activeSummary_ 同步
    activate_forward(3);      // commit 目标则进 pendingCommitWords_ 并触发重新 capture
}
```

legacy 一次掩码写覆盖 ≤16 个目标；AM 每目标一次带分支的调用（内部还有 `is_commit_block` 特判）。这就是"关键频繁处"最大的形态差异。

**(c) event 生命周期。** 一致——都是"检测后置位、周期边界清零"。legacy 的 event slot 是 round 级（每 round 末 `emitClearAllEventEdges`）；AM 的 changed event 是 epoch 级（`grhsim-am.md:285-286`：进入每个 epoch 前清零），实现用 **dirty list 稀疏清零**（`clear_changed_results` 只清本 epoch 置位过的 event）。AM 额外把 commit 写消费的 event 在 epoch 边界快照到 `pendingCommitEventBits_`（capture/restore），保证 commit 相位还能看见 compute epoch 产生的边沿。

**(d) 后向/自激活。** legacy：同 word 后向位或跨 word 激活留在 bitset 自然落入下一 round（组合环由前端 pass 消除，round 无上限）；AM：显式 `act.b` 指令进 `nextActiveWords_`，epoch 边界换入（1e6 epoch 上限，超限 throw 而非死循环）。AM 不允许 `directEvent` 跨后向激活（`production_activity_schedule.cpp:1580`）。

### 3.5 state commit 与 reader 重激活

**legacy**：commit supernode **不由 compute 激活**——每轮无条件扫描所有 commit batch，用 event 表达式门控（本 case `event_edge_slots_[0] == posedge`）；写体直接更新可见 state，**内联**判变并重激活 reader：

```cpp
if ((value_bool_slots_[290]) != 0) {          // update guard
    const auto next_value = static_cast<std::uint64_t>(value_u64_slots_[225]);
    if (unlikely(grhsim_state_scalar_4_slot_512 != next_value)) {
        grhsim_state_scalar_4_slot_512 = next_value;      // 就地写
        commit_activated_readers_ = true;                  // 决定再来一轮
        supernode_active_curr_[0u] |= UINT8_C(2);          // reader 直接置位
    }
}
```

**AM**：commit Block 需要被激活（`pendingCommitWords_`），compute 收敛后才执行；写是 masked in-place，配 consume-on-event 槽位；reader 重激活走 Block 尾部 detector + `act.b`：

```cpp
case 37: {   // commit Block
    { const bool commit_event_hit_2284 = ((values_[4776] != 0));
    if (commit_event_hit_2284 && !completedCommitWrites_[0]) {
        completedCommitWrites_[0] = true;                  // 本 eval 内消费一次
        if ((values_[5081] != 0)) {                        // guard（capture 后的快照值）
            values_[0] = ((values_[0] & ~values_[2579]) | (values_[5082] & values_[2579])) & UINT64_MAX;
        } }
    ... }
    // 尾部 watch group：final writer → reader
    set_changed_result(7773, values_[0] != values_[7772]);
    values_[7772] = values_[0];
    if ((values_[7773] != 0)) { activate_backward(1); activate_backward(17); ... }
}
```

对照要点：

1. **判变位置**：legacy 在写点内联判变（写抑制和 reader 激活共用一次比较）；AM 写本身不判变（masked write 无条件执行），由尾部 `changed.any`  detector 判变——多一次全量比较 + old 更新。AM 的 consume-on-event 防止的是"同一 eval 内 event 重放导致重复写"，不是判变抑制。
2. **reader 激活时机**：legacy 在同一 round 的 commit 相位末尾置位 reader，下一 round compute 读新 state；AM 经 `act.b` 进下一 epoch。净效果相同（eval 内不动点、reader 看到新值），§5.2 的 bit-exact 结果印证了这一点。
3. **事件检测器数量**：legacy 全设计共享 1 个 clock event slot（`commit_event_keys=1`）；AM **每条 commit 写指令一个 posedge detector**（本 case 153 个 `set_commit_changed_result`，各自带 old 存储、dirty 簿记和 capture/restore）。lowering 为每个写口生成独立 event 变量，物化时未按 (kind, watched var) 共享——这是一个明确的去重优化点。
4. **guard/数据快照**：AM 的 commit operand capture（249 个）把 compute 产生的 guard/addr/data 在 commit 前快照，防止 compute 后续 epoch 覆盖；legacy 没有对应物（commit 每轮紧随 compute，直接读 live 值，靠 round 结构保证时序）。

### 3.6 首次 eval

两边都"首次 eval 全量执行 + 后续增量"。legacy：`kInitialComputeActiveMasks` 表置位全部 compute supernode；event 基线未建立时边沿分类抑制为 none（异步 reset 特例除外）。AM：`activate_all_blocks()` 置位全部 Block，commit Block 走 `forcedCommitWords_`；`changed.old` 初值 undef（规范禁止 scheduler 给 old 塞初始化）。本 case 首次行为经 20k 向量含 reset 序列验证一致。

### 3.7 其他值得知道的差异

- **memory**：legacy 对常量地址行读者 ≥32 的 memory 生成行级 reader 激活表（`activate_memory_row_readers_N`）；AM 目前是整 memory 粒度保守激活（writer→所有 reader Block）。AM 越界语义（读 0/写丢弃）由 `index_words` 统一实现，legacy 按地址模式（kGeneric/kInRange/kPow2Wrap）特化。
- **wide 值**：AM 把所有 ≤64bit 值统一放 uint64 槽，运算套 `resize_value(...) & mask`；legacy 按宽度分槽（bool/u8/u16/u32/u64/words_N），表达式更瘦。
- **DPI/system**：AM 只绑定 fwrite/finish，不支持 system.function、DPI String output、inout 端口、waveform；legacy 覆盖更全（$strobe deferred flush、$finish/$stop/$fatal finalize 等）。
- **可读性**：legacy 生成代码带 op 注释（`// op _op_8169 [kRegisterWritePort] reg=tags_64`）；AM 生成代码无注释、纯数字索引，但 AM 层有 `ScheduledProgram` 可验证中间态（legacy 的 session side table 只有 emitter 能解释）。

## 4. 差异根因小结

| 维度 | legacy | AM | 影响 |
|---|---|---|---|
| 调度输入 | GRH op 图 + session 拼接 | AM 指令流 → 强类型 ScheduledProgram | AM 可验证/多后端；legacy 耦合 emitter |
| 传播机制 | 编译期常量掩码 + 静态 dispatch | 逐 target 调用 + 位图动态扫描 | AM 每激活一次开销更大 |
| 检测粒度 | 值级内联 + 聚合组 | Block 尾部物化 detector 指令 | AM detector 站点 ~2.5x |
| event 共享 | normalized key 去重（153 写共享 1 slot） | 每写指令一个 detector（153 个） | AM 明确优化点 |
| commit 驱动 | 每轮无条件扫描 + event 门控 | 激活驱动 + capture + consume-on-event | AM 簿记更多但更精确 |
| 收敛保证 | 前向校验证明后免扫描 | epoch cap 1e6 throw | 风格差异 |

## 5. 实验验证

### 5.1 编译

legacy 模型、AM greedy 模型、AM coarsen-dp 模型均用 `clang++ -std=c++20 -O3` 编译通过（注意：生成的 Makefile 需 `CXX=clang++`，g++ 不支持 `-include-pch`）。

### 5.2 功能等价：20,000 随机向量 bit-exact

`build/analysis/am_vs_legacy_20260727/compare_driver.cpp` 以 bench 同款协议（reset → 每向量 drive → clock=0 eval → 采样 → clock=1 eval）驱动三个模型，逐拍打印 `io_out0..3/io_flags/io_checksum`：

```text
diff out_legacy.txt out_am_greedy.txt  → 一致（20000/20000 行）
diff out_legacy.txt out_am_codp.txt    → 一致（20000/20000 行）
```

### 5.3 过程中发现的 HEAD bug（已在本地修复，未提交）

`wolvrix/lib/grhsim/am/cpp_emitter.cpp:1113-1117`（`emitEventfulStateWrite`）：commit `7c979c7` 把返回串末尾的 `"}\n}\n"` 改成了 `"}\n"`，外层 `{ const bool commit_event_hit_* ...` 块少闭合一个 `}`，**任何带 commit 写槽位的 AM 模型都编译失败**（reg.write/mem.write/mem.fill 全中招）。`39c2ef2`（XiangShan 50k gate 通过时）是正确的。本地已补回 `"}\n}\n"` 后三条路线全部编译并通过 §5.2。建议尽快提交此修复。

> **2026-07-27 P0 完成记录（更正）**：本节此前称"现有 `test_cpp_emitter` 只断言文本形态，未覆盖该配对"——**此判断有误**。`testPhasedCommitRuntime`（`test_cpp_emitter.cpp:1599`）会用含 reg.write/mem.write/mem.fill + event + consume-on-event 槽位的 phased commit 模型走"emit → make 编译 → 运行"全流程，实测回退该修复后 `grhsim-am-cpp-emitter` 在编译生成代码时即失败（`jump bypasses variable initialization` 等 8 个错误），即回归覆盖**已存在**，无需新增测试。`7c979c7` 漏网的真正原因是提交前未跑 ctest。P0 验收结果：① AM 相关 ctest 全绿（全量 57 个中另有 3 个既有失败 `transform-comb-lane-pack`/`transform-repcut`/`ingest-write-back-slice`，已用"回退修复重跑"确认与本次改动无关）；② 本 case 用修复后的 `grhsim-am-lower-json` 重新 emit 两条 AM 路线（调度统计与 §2.6 完全一致），三路线 `clang++ -std=c++20 -O3` 编译通过，20,000 向量 bit-exact 一致。

### 5.4 性能采样（小 case，仅作方向参考）

20k 向量驱动时间：legacy 0.07 s / AM greedy 0.57 s / AM codp 0.71 s。AM 慢 ~8x，与 XiangShan 记录的 ~11.8x（4,178,703 ms vs 355,000 ms 基线）同向。此 case 仅 25/38 个执行单元，固定开销占比高，不宜外推；但 §3.4/§3.5 列出的机制差异（逐 target 调用、detector 密度、event 簿记、动态 dispatch）正是差距的代码层来源。

## 6. 后续建议（按收益排序）

1. **commit event detector 去重**：按 (kind, watched variable) 共享 posedge detector（本 case 153→1），同时减少 dirty 簿记和 capture/restore 表。
2. **act 物化的聚合**：同一 watch group 的多 target 在生成代码里合并成掩码写（借鉴 legacy `grhsim_or_active_u16`），或在 emitter 识别连续 BlockId 区间用循环/位段。
3. **dispatch 静态化**：对固定 Block 拓扑，生成直接调用的 batch 函数（legacy 形态）替代 `execute_block` switch 扫描；至少把 runtime profile 分支编译期关掉（当前 `runtimeProfileEnabled_` 是运行期判断，dispach 热路径每次 `execute_block` 都查）。
4. **detector 降密度**：提高 AM Block cap 或对纯组合长链启用更大的 coarsen budget，减少跨块边界数量（detector 数 ∝ 边界变量数）。
5. 修复 §5.3 的回归并加编译型回归测试。

## 附：关键源码位置

- AM 调度主流程：`wolvrix/lib/grhsim/am/production_activity_schedule.cpp:907`（`schedule`）
- AM 依赖图/SCC：同文件 `:126`（buildInstructionGraph）、`:212`（Tarjan）、`:54`（operand 过滤）
- AM 粗化+DP：`wolvrix/lib/grhsim/am/grhsim_am_activity_schedule.cpp:247`（coarsenRound）、`:532`（segment DP，移植自 legacy）
- AM 激活边/物化：`production_activity_schedule.cpp:1461` / `:847`
- legacy 调度主流程：`wolvrix/lib/transform/activity_schedule.cpp:6127`；粗化 `:5571`；DP `:4719`；session 导出 `:6337`
- legacy emitter 激活：`wolvrix/lib/emit/grhsim_cpp.cpp:530`（掩码发射）、`:5359`（changed 检测）、`:5244`（deferred 聚合）、`:13928`（commit 写 + reader 激活）、`:22519-23222`（eval）
- AM emitter：`wolvrix/lib/grhsim/am/cpp_emitter.cpp:1579`（act 发射）、`:3905`（activate_*）、`:4107`（稀疏清零）、`:4173`（eval）、`:1096`（consume-on-event）
- 语义差异官方审计表：`wolvrix/docs/grhsim/grhsim-am-pipeline.md` §7

---

# 7. AM 路线逐项对齐 legacy 的修改计划

对应 §4 差异表逐项给出对齐方案。总原则：**只对齐性能相关的代码形态与开销，不回退 AM 的架构收益**（ScheduledProgram 可验证中间态、act.b/epoch 语义、指令级可解释性不动）。每项注明改动层：emitter-local（最安全，只改生成代码形态）> scheduler（改调度/物化）> lowering（改指令生成）。

## 7.1 逐项计划总表

| # | 差异项（§4） | 对齐目标 | 改动层 | 风险 | 预期收益 | 优先级 |
|---|---|---|---|---|---|---|
| P0 | §5.3 emitter 少 `}` | 可编译 | emitter | 低 | 前置项 | 立即 |
| P1 | event 共享：153 写各配 1 个 posedge detector vs legacy 共享 1 slot | 按 (edge, watched var) 去重 | lowering | 低-中 | detector −10%、commit 簿记大降 | 高 |
| P2 | 传播：逐 target `activate_*` 调用 vs 常量掩码 | 同类 target 合并为掩码写 | emitter | 低 | 传播语句 −80%+ | 高 |
| P3 | dispatch 热路径运行期 profile 分支 | 编译期开关 | emitter | 低 | 每次 activate/execute 省分支 | 高 |
| P4 | 动态位图扫描 + switch dispatch vs 静态 batch 直接调用 | word 级跳过 + 顺序 dispatch | emitter | 中 | XiangShan 规模才显著 | 中（需 profile） |
| P5 | commit 写不判变 + 尾部 detector 二次比较 vs 写点内联判变 | 单写场景融合写与 detector | scheduler+emitter | 中-高 | 每 state 写省一次比较+old | 中 |
| P6 | 分块粒度：36 block/128 cap/budget 16 vs legacy 24 SN/budget 4096 | 扫参选默认，对齐 budget 公式 | scheduler 参数 | 低 | detector 密度下降 | 中 |
| P7 | B0 通用 detector 播种 vs eval 内联比较播种 | B0 形态特化 | emitter | 低-中 | 小（输入少） | 低 |
| P8 | epoch 推进整数组拷贝 | swap/双缓冲 | emitter | 低 | 每 epoch 省 O(words) 拷贝 | 低 |
| P9 | memory 整粒度 reader 激活 vs 行级激活表 | 行级 reader 激活 | scheduler | 高 | memory 密集设计显著 | 后置 |
| — | 值级内联检测粒度、session side table | **不对齐**（架构方向，见 §7.7） | — | — | — | — |

统一验证基线（每项必过，全部已有基建）：

1. `ctest --test-dir wolvrix/build --output-on-failure`（AM 全套测试）。
2. xs-components 回归：`XsReal053FtqFtqLarge` 重新 emit → `clang++ -std=c++20 -O3` 编译 → `compare_driver` 20,000 向量与 legacy 模型 bit-exact（§5.2 流程，产物在 `build/analysis/am_vs_legacy_20260727/`）。改动涉及 commit/memory 语义时，加跑 `XsReal100BackendNfmappedelemidxSmall` 和一个 SRAM 密集 case（如 `XsReal044SramSramtemplateLarge`）。
3. XiangShan gate：`make run_xs_wolf_grhsim_am_emu` difftest 2k/20k/50k + host time 与 legacy 基线（355,000 ms）对比；阶段目标：阶段 1 完成后 host time 倍率显著下降，最终逼近 <3x（需实测修正）。

## 7.2 阶段 0：前置修复（P0）——已于 2026-07-27 完成

- **内容**：提交 §5.3 的 `emitEventfulStateWrite` 修复（本地 diff：`cpp_emitter.cpp:1117` 末尾 `"}\n"` → `"}\n}\n"`）。**修复已落实并通过验收，待提交。**
- **补测试**：~~新增回归用例~~ **不需要**。原计划依据"现有文本断言 `test_cpp_emitter.cpp:1292-1347` 不查配对"推断覆盖缺失，但该区间只是 `testPackedActivityRuntime` 的文本断言；`testPhasedCommitRuntime`（`:1599`）早已覆盖"含 commit 写槽位模型 → emit → make 编译 → 运行"全路径（reg.write/mem.write/mem.fill 三种写均在 commit 块内带 event + consume-on-event 槽位）。已做阴性验证：回退修复后 `grhsim-am-cpp-emitter` 在编译生成代码时失败，恢复后通过。漏网根因是 `7c979c7` 提交前未跑 ctest，而非覆盖缺口。
- **验收（已通过）**：AM 相关 ctest 全绿；本 case 两条 AM 路线用修复后二进制重新 emit（调度统计与 §2.6 一致）+ legacy，三路线 `clang++ -std=c++20 -O3` 编译通过，compare_driver 20,000 向量两两 bit-exact。注：全量 ctest 中 `transform-comb-lane-pack`、`transform-repcut`、`ingest-write-back-slice` 3 项为 HEAD 既有失败（与 AM emitter 无关，回退/恢复修复均复现），需另行排查。

## 7.3 阶段 1：emitter-local 高收益项（P1/P2/P3/P8）

### P1：commit event detector 按 (edge, watched var) 去重

- **现状**：`lowering.cpp` 的 `lowerEvents`（`lowering.cpp:1883-1933`）对每个写口的每条 event edge 都 `addVariable(old, undefInit)` + `addVariable(event, zeroInit)` + `addInstruction(ChangedPos/Neg)`，无跨写口共享。本 case 153 个写 → 153 个同语义 posedge(clock) detector（各带 old 存储、dirty 簿记、commit event slot、capture/restore）。
- **方案**：在 lowering 实例内加 memo：`map<(Opcode ChangedPos/Neg, VariableId raw), VariableId event>`；命中时直接复用已有 event 变量作为该写口的 event operand，不再建 old/event/指令。注意：
  - 共享后 `changed.old` 仍独占（只有一个 detector 指令更新它），满足规范 old 独占性；
  - consume-on-event 不受影响——`completedCommitWrites_` 槽位按写指令分配（`cpp_emitter.cpp:2088-2160`），各写独立消费同一 event；
  - scheduler 的 `canonicalCommitEvent` 本来就按 (kind, watched var) 规范化分桶（`production_activity_schedule.cpp:335`），天然兼容；kCommitEventVariables_ 表同步去重；
  - validator 的 commit event 所有权检查（`pipeline.cpp:346-474`）按变量判定，共享后仍合法，需跑 ctest 确认。
- **验证**：本 case `set_commit_changed_result` 站点 153→1；20k 向量 bit-exact；XiangShan difftest。
- **预期**：detector 总数 −10%（本 case 1527→1375），XiangShan 上 commit event 相关的 dirty/capture/restore 簿记随 detector 数等比下降。

> **2026-07-27 P1 完成记录**：已按上述方案落地——`lowering.cpp` `lowerEvents` 增加
> `eventDetectorMemo_`（`map<(Opcode, VariableId raw), VariableId event>`），同
> (edge kind, watched variable) 的 event 直接复用首个 detector，不再重复建
> old/event/指令；`ChangedPos/ChangedNeg` 以外的语义未动。`test_lowering.cpp` 的
> opcode inventory 断言同步更新（ChangedPos 4→1），并新增"posedge(clk) 各写共享同一
> detector 结果变量"的回归断言。验收结果：
>
> 1. `ctest -R grhsim-am` 8/8 全绿（含 lowering/pipeline/emitter/interpreter/end-to-end）。
> 2. `XsReal053FtqFtqLarge`：`set_commit_changed_result` 站点 **153→1**
>    （`kCommitEventCount=1`）；linear 指令 4656→4504；scheduled 指令 greedy
>    7557→7245 / coarsen-dp 8293→7973；activation 调用点 2441→2263（greedy）。
>    两条 AM 路线 `clang++ -std=c++20 -O3` 编译通过，compare_driver 20,000 向量与
>    legacy bit-exact。驱动时间 greedy 0.57→0.44 s、codp 0.71→0.55 s（小 case，仅作
>    方向参考）。
> 3. `XsReal100BackendNfmappedelemidxSmall`：纯组合 case（0 commit Block，不覆盖
>    P1 路径本身），AM-P1 模型 GSIM-verify 2048 向量 pass、100k bench checksum 与
>    GSIM 一致。
> 4. `XsReal044SramSramtemplateLarge`（SRAM 密集）：`kCommitEventCount=1`，
>    AM-P1 模型 GSIM-verify 2048 向量 pass、100k bench checksum 与 GSIM 一致。
> 5. XiangShan（复用既有 post-stats JSON 重新 emit）：commit detector 站点
>    **276,182→413**（413 = 全设计不同的 (edge, watched var) 对数）；linear 指令
>    4,950,236→4,660,708（−289,528）；detector 总数 1,875,970→1,875,379；
>    activation edges 3,218,269→2,908,430；scheduled 指令 8,992,117→8,411,879。
>    difftest（coremark-2-iteration + NEMU，新旧 emu 同机对照）：
>
>    | 周期 | 旧 AM host ms | P1 host ms | 加速 | instrCnt/cycleCnt |
>    |---|---|---|---|---|
>    | 2k | 145,442 | 49,630 | 2.93x | 一致（3 / 1,996，无 mismatch） |
>    | 20k | 1,730,723 | 696,928 | 2.48x | 一致（14,121 / 19,996，pc 相同） |
>    | 50k | 4,178,703（历史记录） | 1,953,414 | 2.14x | 一致（73,580 / 49,996，与历史通过记录相同） |
>
>    host time 倍率（对 legacy 355,000 ms 基线）由 ~11.8x 降至 **~5.5x**；收益主体是
>    commit event dirty/capture/restore 簿记从 276k 槽位降到 413 的每 eval 固定开销
>    压缩。

### P2：act 传播合并为掩码写

- **现状**：`cpp_emitter.cpp:1579-1592` 对每个 target 生成一次 `activate_forward/backward` 调用，函数内做 word/bit 定位、summary 更新、`is_commit_block` 特判（`:3901-3932`）。本 case 2441 个调用点 vs legacy 337 条掩码语句。
- **方案**：emit 一条 act 指令时，把 targets 按四类目标位图分组（compute-forward `activeWords_` / compute-backward `nextActiveWords_` / commit-forward `pendingCommitWords_` / commit-backward `nextCommitWords_`），同类内按 64-block word 聚合，生成：
  ```cpp
  if ((values_[e] != 0)) {
      activeWords_[0] |= UINT64_C(0x....); activeSummary_[0] |= UINT64_C(0x1);
      // commit-forward 组：先算 newly = mask & ~pendingCommitWords_[w];
      //   capturedCommitWords_[w] &= ~newly; pendingCommitWords_[w] |= mask; pendingCommitSummary_ 置位
  }
  ```
  summary 位无条件置位是安全的（误置只多一次空扫，漏置才会丢 Block，见 `execute_active_blocks` `:805-825`）；commit 组的 `capturedCommitWords_` 失效逻辑按 word 批量做，与现行逐 block 逻辑等价（现行：该 block 此前不 pending 则清 captured）。
- **前提**：BlockId 静态已知（现状如此），同一 act 的 targets 编译期可分组——无需改 AM 指令语义，`act.f/act.b` 的 targets 列表不变，只是发射形态变化。
- **验证**：生成代码 `activate_*` 调用点计数（本 case 2441 → 预计 <400）；bit-exact；ctest。
- **预期**：传播热点指令数 −80%+；XiangShan 322 万 activation target 的调用开销大幅压缩。

### P3：runtime profile 改为编译期开关

- **现状**：`execute_block`（`:942-952`）、`activate_*`、`capture_*` 等热路径每次都查运行期 `runtimeProfileEnabled_`。
- **方案**：`GrhSimAmCppOptions.attributes` 增加 `runtimeProfile`（编译期 bool，默认 off）；off 时完全不生成 profile 分支与计数字段，`set_runtime_profile_enabled/dump_runtime_profile` 退化为 no-op stub 保持 host 接口（`afcd5fd` 引入的接口不变）。on 时保持现状。
- **验证**：off 时生成代码 grep 无 `profilePerBlockExecs_`；bit-exact；开/关两态各编一次。

### P8：epoch 推进避免整数组拷贝

- **现状**：eval 主循环 `activeWords_ = nextActiveWords_; activeSummary_ = nextActiveSummary_;`（生成代码 `:992-997`）每 epoch 全量拷贝，随后 `fill(0)` next 侧。
- **方案**：双缓冲——生成代码用 `cur`/`next` 两组存储的指针/索引互换（或直接 `std::swap`），换出的 next 侧只需清"本 epoch 被置过位"的 word；commit 的 `pendingCommitWords_ |= nextCommitWords_` merge 语义保持不变。eval 开头的 8 个 `fill(0)`（37k Block 时约 37 KB/次）同理可保留（首次必须），但 epoch 内不再全清。
- **验证**：bit-exact；多 epoch 设计（state 反馈密集 case）重点回归。

## 7.4 阶段 2：参数与中风险项（P6/P4）

### P6：分块粒度扫参与默认值对齐

- **现状对比**：legacy coarsen budget = 32×cap（4096 op）、DP penalty 1.0 → 本 case 24 supernode；AM budget = max(cap/8,16)=16、penalty 64 → 36 Block。AM 块更小 → 边界更多 → detector/act 更密。
- **方案**：
  1. 用 xs-components 3~5 个 case（含 SRAM 密集与控制密集）做参数扫描：`blockFormation ∈ {greedy, coarsen-dp}`、`dpCoarsenBudget ∈ {16, 64, 256, 1024}`、`dpSegmentPenalty ∈ {1, 8, 64}`，记录 blocks/detectors/activation_targets/生成体积/运行时间。
  2. 依据扫描结果决定是否把默认 budget 公式对齐 legacy 的 32×cap（`production_activity_schedule.cpp:1271-1274`），以及 XiangShan 是否切 coarsen-dp 为默认。
  3. 注意权衡反方向：块过大时无关指令被整束执行，激活局部性下降——legacy 的 24 超级块/平均 215 op 是本 case 的实测最优点附近，不代表普适；以运行时间而非块数为目标函数。
- **验证**：扫参矩阵 + bit-exact + XiangShan host time。

### P4：静态顺序 dispatch（对齐 legacy batch 形态）

- **现状**：每 epoch `execute_active_blocks` 位图扫描 + `execute_block` switch 间接调用（`:805-825, :942-952`）。legacy 是编译期展开的 batch 直接调用，word 级 `dispatchMask` 批量跳过。
- **方案**：emitter 生成 `eval_epoch_compute()`，按 64-block word 展开：
  ```cpp
  if (activeWords_[w] != 0) {
      if (activeWords_[w] & bit_b) { activeWords_[w] &= ~bit_b; <block b 代码> }
      ...
  }
  ```
  利用 act.f 严格前向，按 BlockId 升序单遍扫描即为一个 epoch（与现位图扫描同构，省 countr_zero 逐位扫描与 switch 间接）。Block 体积分片仍按 `blocksPerSource` 控制单函数规模。
- **前提**：先做 P2/P3 后在 XiangShan 上 profile（开编译期 profile），确认 dispatch 开销占比仍显著再动手；37k Block 全展开可能反而增大 I-cache 压力，需要实测。
- **风险**：中——必须保持"同 epoch 按 BlockId 升序、每 Block 最多执行一次"的消费语义；B0 不在 epoch 扫描内。

## 7.5 阶段 3：语义相关后置项（P5/P7/P9）

### P5：commit 写与 reader 判变融合

- **现状**：AM commit 写无条件 masked write，reader 激活靠 Block 尾部 `changed.any(target, old)` 再比较一次（比较 + old 存储双份开销）；legacy 写点内联 `if (state != next) { state = next; 激活 }` 一次比较两用。
- **方案（保守子集先行）**：scheduler 物化 final-writer watch group 时（`appendWatchGroups` `:847-904`），识别可融合模式——target 在本 commit Block 内只有一个写指令、mask 为全 1、event 命中即写、old 无其他读者——给 detector 打 `fuse-with-write` 属性；emitter 遇到该属性时把比较上移到写点：
  ```cpp
  if (commit_event_hit && !completedCommitWrites_[s]) {
      completedCommitWrites_[s] = true;
      if (cond && (values_[t] != values_[next])) {
          set_changed_result(e, true); values_[t] = values_[next];
      } else { set_changed_result(e, false); }
  }
  ```
  不可融合的情形（多写、有 mask、old 被多处引用）保持现状。等价性论证：写是确定的（`t' = f(t, next, mask)`），`t' != old` 与"先比较再写"在单写/全 1 mask/无中途读者时相同；mask 非全 1 时 `t' != old ⇔ (t&~m|n&m) != old`，也可直接表达，但保守起见一期不做。
- **风险**：中-高，触碰 consume-on-event 与多写时序，必须过 commit 语义相关 ctest（`test_production_activity_schedule.cpp`、`test_end_to_end.cpp`）+ SRAM case + XiangShan difftest。
- **注意**：这项本质是把 AM 的"detector 判变"向 legacy 的"写点判变"靠拢，与 P1 叠加后 commit Block 尾部 watch group 应基本消失。

### P7：B0 输入播种特化

- **现状**：B0 每 eval 对每个输入跑通用 `set_changed_result`（compare + old 更新 + dirty 簿记）+ act；legacy 在 eval 内联一次比较 + 常量掩码。
- **方案**：P2 落地后 B0 的 act 已掩码化；进一步当 validator 的 B0 provenance 分析（`pipeline.cpp:489-629`）能证明某 B0 event 只被本 Block act 立即消费时，emitter 对该 detector 不记 dirty（event 不需要跨 epoch 清零，因为下次 B0 执行必然先重写它），生成 `if (in != old) { old = in; masks }` 形态。
- **收益**：小（XiangShan 仅 clock/reset/difftest 等少数输入）；低优先级。

### P9：memory reader 行级激活

- **现状**：AM 的 writer→reader 激活是整 memory 变量粒度（`production_activity_schedule.cpp:1525-1541`）；legacy 对常量地址行读者 ≥32 的 memory 生成行级激活表（`grhsim_cpp.cpp:8239-8290, 20499-20553`）。
- **方案**：scheduler 在建 writer→reader 边时对 mem.read 地址做常量/仿射分析，按行分组 reader Block；物化需要 AM 层能表达"按行激活"（新属性或 emitter 特化），生成 `activate_memory_row_readers_N(row)` 同类 helper。
- **风险**：高（新分析 + 新物化形态），但对 SRAM 密集的 XiangShan 收益直接（Legacy 已有成熟实现可移植）。建议阶段 1/2 见效后单独立项。

## 7.6 建议执行顺序与里程碑

```text
M0（立即）   P0 提交 + 编译回归测试
M1（1~2 天） P1 + P2 + P3：三项 emitter/lowering-local，叠加后做一次完整验证
             （ctest + 3 case bit-exact + XiangShan 2k/20k/50k difftest + host time）
M2（2~3 天） P8 + P6 扫参；XiangShan profile 后决定 P4 是否做、做到什么程度
M3（评估后） P5（先论证等价性）、P7；P9 视 memory 收益单独立项
```

每项改动都是独立 PR 粒度，conventional prefix（`fix(grhsim-am): ...` / `perf(grhsim-am): ...`），并同步更新 `docs/grhsim/grhsim-am-pipeline.md` 的进度注记与 `pdocs/grh_notepad` 的 NO00030 记录。

## 7.7 明确不对齐的项

- **值级内联 change 检测**（legacy 每个 tracked value 内联比较）：AM 的 Block 边界物化 detector 是 ScheduledProgram 可验证性的基础，回退等于放弃 AM 架构目标；应通过 P1/P5/P6 降低 detector 总量，而不是改变检测粒度模型。
- **session side table ↔ ExecutableModel 的耦合差异**：方向相反，legacy 侧才是要被替代的一方（pipeline 文档 §5）。
- **round ↔ epoch 语义**：官方已认定不同构（pipeline 文档 `:655`），对齐只到"eval 内不动点"的净效果等价（§5.2 已验证），不追求逐 round/epoch 对齐。
