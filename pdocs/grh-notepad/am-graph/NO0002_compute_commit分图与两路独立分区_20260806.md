# NO0002 compute/commit 分图与两路独立分区

日期：2026-08-06
状态：已落地并验证（划分结果与发射产物字节级不变）

## 1. 目标

用户指令：AM 图建立后，先做一次 compute 和 commit 分图，然后两个图分别分区处理——
compute 按活动度划分，commit 按事件聚类。

改造前 `scheduleGrhSimAmActivityBlocks` 是单体式实现：内部虽已按两套标准分别处理
compute/commit atom，但对外只有一次调用、一张图。本次把分图显性化为调度管线的独立
阶段，让两个分区 pass 各自消费自己的子图，便于后续在 compute 图上独立演进分区策略
（supernode-align 线的直接抓手）以及在 commit 图上调整事件聚类规则。

## 2. 结构

`activity_schedule.hpp/cpp` 拆为三段公开 API + 一个等价组合入口：

- `splitGrhSimAmActivityGraph`：atom DAG → compute/commit 两张诱导子图。局部 id 保持
  全局 atom 相对次序（保证后续所有优先队列裁决顺序不变）；跨类边（compute→commit）
  不属于任一子图；commit→compute 依赖在此判非法
  （"AM dependency requires a state commit before pre-commit work"）。
- `partitionGrhSimAmComputeGraph`：compute 子图按活动度划分——out1/in1/sibling 三路
  迭代 coarsen + 确定性拓扑 + segment DP（跨段 incoming 激活 value 成本 +
  segmentPenalty），算法内核逐行平移自原单体实现，仅把全局 atom 索引换成分图局部
  索引；DP 的 def-use 成本仍读全局变量空间，commit atom 内的 use 经分图表跳过
  （与原 `atomIsCommit` 过滤同语义）。
- `partitionGrhSimAmCommitGraph`：commit 子图按事件聚类——按 (eventRank,
  minInstruction) 优先级 Kahn + 同事件签名桶内限量合并（原实现逐行平移）。
- `scheduleGrhSimAmActivityBlocks`：保留为「分图 + 两 pass + 合并」的等价组合入口，
  供单测与对账使用。

生产调用点（`production_activity_schedule.cpp`）改为显式三段：split → compute 分区 →
commit 分区 → 合并回全局 atom 编号（commit Block 序接 compute 段之后，input sink 位
置逻辑不变）。

## 3. 验证

- 新增单测 `testComputeCommitGraphSplitMatchesComposition`：混合图（compute DAG +
  compute→commit 边界边 + commit 链、两种事件签名）上，分段执行与组合入口的
  atomBlock/atomTopo 完全一致；分图诱导边数、事件聚类成桶均符合预期。AM 套件 10/10。
- 香山全设计（3,209,648 指令）字节级比对：
  - `instruction_graph.jsonl` 与基线逐字节一致（导出点在分图之前，理应不变）；
  - `block_assignment.jsonl` 逐字节一致（28,826 块：compute 28,344 + commit 481 +
    input sink；dag_edges=256,340、compute_compute_value_pairs=1,913,302、
    incoming_copy_cost=5,008,284）；
  - C++ 发射产物与 rmpack 干净基线逐文件一致（`diff -rq` 全等）。
- 发射字节与已两次通过 difftest 的基线（73,580/49,996，325.8s/324.4s）完全相同，
  本轮不重复 difftest。

## 4. 备注

- 排查中发现 emit 工具不清理输出目录：canonical `build/xs/grhsim-am/grhsim_emit` 里
  残留更早（保留读旧链时代）的 `blocks_13_part_57+`、`blocks_14_part_*` 源文件。emu
  构建按发射清单选源，不受影响（324.4s 复核通过），但做目录级比对时需用干净目录。
- 分图是纯结构重构，无数值变化；后续若要换 compute 分区算法，只需替换
  `partitionGrhSimAmComputeGraph` 一处。
