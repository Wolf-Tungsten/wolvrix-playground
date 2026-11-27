# F38 GRHSIM 五阶段调度简化

F38 为 GRHSIM 与 FIRRTL 输入合拢做准备。FIRRTL ingest 及普通 GRH 优化完成后的 Wolvrix IR 图是仿真转换的输入，F35/F36 使用的第四次 DCE 后图可作为香山验证入口。F38 简化 GRHSIM 的执行分区和调度，输入合拢留待后续阶段。现行调度为 Input、Event、General、LargeSink、Publish、Output 六阶段，General 同时执行主体计算和写口采样，LargeSink 提交大状态，Publish 发布状态、传递 activity 并判定是否继续。F38 将主体求解与状态提交定义为两个调度阶段。 [F35 Node 对齐](F35-fourth-dce-alignment-plan.md) · [F36 状态访问对齐](F36-state-port-alignment-plan.md) · [现行 GRHSIM 调度](../grhsim.md#2-六阶段调度模型)

## 1. 五阶段和 `eval()`

```cpp
void eval() {
    p_input();
    do {
        p_event();
        p_compute();
    } while (p_commit());
    p_output();
}
```

| 阶段 | 调用频率 | 职责 |
| --- | --- | --- |
| `p_input` | 每次 `eval()` 一次 | 装载并固定本次输入，包括 inout 的输入侧，初始化本次时隙的触发记录。输入变化激活对应的计算分区，模型初始化负责建立首轮所需的活动。 |
| `p_event` | 每轮开头，无条件执行 | 从本次输入快照和轮首状态求出检测器的输入电平，与该检测器上一次采样的输入电平比较，记录本轮是否命中边沿，再保存此次电平。IR 操作数 `fire` 表示本轮的事件条件，可以由一个或多个边沿结果组成。每次触发时激活订阅它的 `p_compute` 分区。写口 enable 与计算分区活动位均不参与事件检测。 |
| `p_compute` | 每轮一次 | 按拓扑序执行已激活的分区，求出跨分区值、写口的提交前操作数和系统调用参数。系统任务和系统函数按各自的调用条件执行，通过 `system_state_value` 记录需要保留的调用状态。 |
| `p_commit` | 每轮末尾 | 遍历全图按 `{priority, canonicalized_edges}` 聚类的写口块。每条写口就地更新目标。任一标量写口改变当前值，或任一数组写口有效写入，就激活该状态的全部 Compute 读者并安排下一轮。 |
| `p_output` | 收敛后一次 | 从输入快照和最终设计状态求顶层输出锥，更新 output 及 inout 输出值、输出使能。按 `system_state_value` 中的待输出记录，从 `compute_boundary_value` 读取收敛后的显示参数，执行延迟系统任务并消费对应记录。 |

**收敛条件。** `p_commit()` 在本轮有任何一条标量写口实际改变其目标，或有任何一条数组写口发生有效写入时返回 `true`。一旦满足条件，本轮后续写口即使把值写回轮首值，也保留续轮请求。所有标量写口均未改变各自执行时的目标值，且没有数组有效写入时，返回 `false` 进入 `p_output`。输入采样、事件检测和系统调用的私有记录都不单独触发续轮。

例如，假设本轮只有一个写口。时钟上升沿使能 `q <= d`，且 `q` 与 `d` 都是 1，本轮组合逻辑已按 `q = 1` 求完，可以直接输出。若 `q` 从 0 提交为 1，则下一轮 `p_event` 可以检测由 `q` 派生的边沿，`p_compute` 可以传播新值。

## 2. 剥离 `p_event` 和 `p_output`

运行时，事件锥和顶层输出锥从输入快照和设计状态取数。建图时从事件检测、output 和 inout 的 out/oe 沿 use-def 反向提取各自的锥。延迟系统任务在 Output 使用 Compute 已发布的参数。状态写口操作数、系统调用参数和其他主体使用点都进入用途分析，确保剥离后各消费者仍有定义。

1. 只在一个剥离阶段需要的计算移入该阶段。多个阶段都需要的可复制计算按需克隆，各阶段的使用点接到自己的定义。只有主体或提交仍需要该计算时，才在主体计算图中保留相应定义。
2. 完成 use-def 和输出绑定的重连后，删除主体大图中已无用途的原 op 及死依赖。一个 op 如果只被 Event 和 Output 使用，可以在这两个阶段各有一份，主体分区应有零份。活动度分区基于剥离清理后的主体图建立。
3. 状态声明与存储身份保持共享。对于 DPI 或有副作用的系统函数等不可复制的调用，保留原调用身份和顺序，通过显式采样值供其他阶段读取。延迟系统任务在 Compute 保留源调用点的执行条件和次数。显示参数由 Compute 按数据依赖更新，其生产者即使只服务于该任务也保留在 Compute。Output 通过边界读取最终值。

不可复制的调用结果若进入事件锥或输出锥，须从具有明确采样时点的存储读取。例如，现有 DPI 用例中，Event 读取已保存的样本，General 随后刷新样本，无状态提交时下一次 `eval()` 才观察到它。若某类事件要求本轮的新样本，提取时必须保证样本在检测前就绪，并维持调用顺序。 [现有 DPI 事件采样用例](../../wolvrix/tests/emit/test_grhsim_cpu_st_cpp.cpp#L6685)

例如，`gated_clk = clk & gate` 只被边沿检测使用时，AND 移入 `p_event`，从主体图移除。如果主体逻辑也读取 `gated_clk`，两个阶段各保留所需计算。另一个仅用于公开输出的 `out = q ^ mask` 则在 `p_output` 读取收敛后的 `q`。现有 `split-event-and-output` 的用途传播、克隆重连和死 op 清理可作为实现起点。 [现有剥离实现](../../wolvrix/lib/transform/grhsim/split-event-and-output.cpp#L97)

### 系统任务和系统函数的取值与状态

系统任务统一用 `grhsim.systemTask` 表达，系统函数统一用 `grhsim.systemFunction` 表达。`$monitor` 和 `$strobe` 分别对应 `name="monitor"` 和 `name="strobe"` 的 `grhsim.systemTask`。调用点保留任务或函数名称、参数绑定及适用的格式和执行条件。事件型调用由本轮 `fire` 触发，动态数据参数从 `compute_boundary_value` 取值。系统函数的结果也按其 IR Value 发布，供下游计算读取。

每个模型实例用一份 `system_state_value` 保存系统调用需要跨阶段、跨轮或跨 `eval()` 记住的信息。生成器按图中实际的调用和调度方式确定存储内容。调用点自己的执行记录按调用点区分，活动监视器和延迟调用的先后次序在实例内共享。各类记录按自己的生命周期更新。

- `initial $monitor("q=%0h", q);` 实际执行时，在 `system_state_value` 中登记当前活动调用点并安排首次报告。后续注册替换当前调用点。即使注册事件没有再次触发，活动参数的可报告变化仍安排报告。例如同一时隙内 `q` 先变为 1 再变为 2，`p_output` 从 `compute_boundary_value[q]` 读取 2，打印一次，再清除本次报告请求。活动监视器跨时隙保留。
- `$strobe("q=%0h", q);` 每次实际调用时，在同一份 `system_state_value` 中按发生顺序追加调用点。若同一时隙调用两次，`p_output` 按两条记录读取最终的 `q`，打印两次并消费记录。[IEEE 1800-2017 §21.2.2–3](https://fpga.mit.edu/6205/_static/F25/documentation/1800-2017.pdf)
- 对当前按 `eval()` 采样的 `$random` 调用点，若分区可能重入，首次执行时在 `system_state_value` 中标记本次已采样，随机值本身发布到 `compute_boundary_value`。后续轮复用该值，下次 `eval()` 可重新采样。对 `initial $display("boot");`，若调度需要防止重复执行，记录从实际打印起保留到模型重新初始化。调度已保证执行次数的调用点可省去相应标志。

现行 `split-event-and-output` 为部分延迟任务合成历史寄存器、读口、比较和 `grhsim.historyWrite`。F38 移除该生成路径以及 `grhsim.historyWrite` 的定义、注册和发射处理。系统调用对 `system_state_value` 的更新不进入设计状态写口集合，也不计入 `p_commit()` 的续轮判定。 [现有历史生成逻辑](../../wolvrix/lib/transform/grhsim/split-event-and-output.cpp) · [现有方言定义](../../wolvrix/lib/dialect/grhsim/ops.cpp)

## 3. `partition-compute` 从语义 Node 构建活动分区

`partition-compute` 以 GSIM 的 Node 为基本分图单位。先用 Wolvrix IR 的 `SemanticTree` 建立 Compute Node 图，再对照 GSIM 将 Node 合成超节点（SuperNode）。最终每个 Compute 超节点是一个按活动位调度的分区。

### 3.1 从 `SemanticTree` 取得 Node 和依赖

沿用 F35 第四次 DCE 后的 Node 库存作为对照起点。`grh-to-grhsim` 和两个 split 在替换、复制或移走 op 时保留可追溯的 Node 归属。`partition-compute` 读取存活语义 Node 的 `SemanticId`、成员 op 和锚点 Value，只纳入实际归属 Compute 的部分。一个 Node 可以包含多个 op。仅归 Event、Commit 或 Output 的部分记录去向；共享 op、拆分片段和新增辅助 op 要能追溯到对应的执行归属。每个待执行的 Compute op 都应有明确归属，多个语义名字指向同一计算时保留对应关系。[F37 对 SemanticTree 的定义](F37-core-dialect-decoupling.md#L22) · [Node 成员、锚点及语义边界接口](../../wolvrix/include/core/wolvrix.hpp#L1408)

Node 间的数据边从实际 use-def 和语义边界用途导出，并保留影响执行顺序的依赖。两端先对齐分图入口的 Node、依赖边和已有的超节点成员关系。跨端以 F35 的层级全名建立对应，重名、别名、拆分或单侧 Node 用来源和连接消歧，并列出仍未配对的成员。本次运行内用各自的 ID 追踪演变。GSIM 普通 Node 初建时各自形成超节点，外部模块及其输出等有共同归属，分图入口应以当时的实际成员为准。[F35 全名与谱系口径](F35-fourth-dce-alignment-plan.md#L7) · [GSIM 初始成员和连边](../../reference/gsim/src/Node.cpp#L91)

### 3.2 对齐 GSIM 的超节点合并

用相同 FIRRTL 输入和分图配置，将 F38 的 Compute 范围与 GSIM 在 `RemoveDeadNodes3` 后、`replicationOpt` 前执行的 `graphPartition()` 对照。在已配对的主体 Node 上逐阶段核对成员集合、超节点间的边和拓扑顺序。由五阶段剥离、特殊 Node 或输入图差异造成的不同，记录具体成员和首个受影响的步骤。[GSIM 流水线入口](../../reference/gsim/src/main.cpp#L1008)

| GSIM 步骤 | F38 要核对的合并决定 |
| --- | --- |
| `graphCoarsen` | 依次对照 `mergeResetAll`、`mergeWhenNodes`、重排、`mergeOut1`、`mergeIn1`、`mergeSublings`。核对 reset 的特殊节点、共享 when 条件、单后继或单前驱的合并方向、兄弟节点的前驱集合，以及规则使用的依赖和容量限制。 |
| `graphInitPartition` | 以粗化后的拓扑顺序做动态规划，核对按成员 Node 数计算的容量、跨边代价、等价代价的选择、回溯切点和特殊超节点的强制边界。按选定区间核对归入同一超节点的成员。 |

当前 GSIM 的 `graphPartition()` 实际执行粗化和初始分图，`graphRefine()` 调用已注释。对齐时以实际启用的阶段和参数为准。现有 GRHSIM `partition-nonsink` 已能读取语义成员并做粗化、分段，可复用其中的建图和检查逻辑；其候选、合并次序及切点仍需逐项与 GSIM 核对。[GSIM 粗化与初始分图](../../reference/gsim/src/graphPartition.cpp#L49) · [GSIM 合并规则](../../reference/gsim/src/mergeNodes.cpp#L78) · [现有 GRHSIM 分区](../../wolvrix/lib/transform/grhsim/partition-nonsink.cpp#L691)

### 3.3 合并 trace 和对账

两端的分图过程都要支持导出可重放的合并 trace。起始快照记录输入、版本、分图参数、Node 对应关系、初始超节点及其有向边。每次合并记录阶段、规则、决策顺序、源和目标超节点、迁移的 Node，以及成员归属和相邻边的变化。阶段末保存成员划分与跨区边，能从初始快照和 trace 重建最终的 `Node → SuperNode` 映射。GSIM 已有粗化后和初始分图后的快照位置，可用于校验重放结果。[GSIM 阶段快照位置](../../reference/gsim/src/graphPartition.cpp#L367)

按 Node 或超节点查 trace 时，还要能看到分歧候选在两侧是否出现、被接受或跳过，以及当时实际参与判断的前驱、后继、顺序约束、大小和阈值。对动态规划保留候选区间、代价和最终切点。例如 GSIM 在 `mergeOut1` 把 `A` 并入唯一后继 `B`，而 F38 仍将两者分开，报告应能指出 F38 在这一步多了一条后继边、命中了某项限制，还是两端在更早阶段已形成不同的成员集合。全图 trace 可用成员迁移增量和按 Node 筛选的决策明细控制体量。

### 3.4 分区执行与活动传播

组合强连通分量（SCC）在分区前消解，或在收缩节点内部求稳。每次合并须保持分区间的组合依赖图为 DAG。执行时按拓扑序访问分区，并读取当时的活动位。生产者的值变化时，其组合消费者排在它之后，可以在同一次 `p_compute` 内执行。`p_compute` 返回时，本轮组合传播及本轮命中的即时调用都已处理完毕。

**分区激活的来源和时点。** `p_input` 对发生变化的输入激活其数据消费者，供本次 `eval()` 的首轮使用。`p_event` 每轮检测事件，对本轮触发的事件激活其订阅分区。`p_commit` 执行每条写口时，只要它改变了标量或有效写入了数组，就将该目标的全部读者并入下一轮活动位图。进入 `p_compute` 时，各来源设置的活动位取并集，同一分区在该轮只需调度一次。分区被调度后，事件驱动的 op 仍逐个检查自己的 `fire` 和调用条件。输入和事件产生的激活在当前轮消费，续轮遵循第 1 节的判据。

例如 FIRRTL 的 `printf(clk, en, "x=%d", x)`。固定 `en = 1` 和 `x = 7`，每次上升沿都由 `p_event` 激活调用所在分区，各打印一次。若 `x` 与上升沿同时变化，调用按拓扑序读取本轮的新值，仍只打印一次。订阅组合事件的调用按每轮实际触发激活，即使相邻两轮的组合 `fire` 都是 1，两轮都要执行。没有触发时，脉冲回落本身不会触发调用。即时 DPI 调用同样保留顺序，有返回值时在同轮消费者之前发布结果。 [FIRRTL 系统任务的时钟与使能](../../wolvrix/lib/ingest/firrtl/lower.cpp#L1437) · [现有事件订阅](../../wolvrix/lib/emit/grhsim/cpu-st-cpp.cpp#L1012)

对于 `q <= a + b`，写口所在的 `p_commit` 事件块直接检查本轮 `fire`。若只有时钟上升，独立的加法分区可复用此前的和。时钟同时用作普通数据时，读取其电平的分区按数据依赖激活，订阅边沿的分区按事件激活。

## 4. `p_commit` 按全图优先级和规范化边沿列表分块

1. `partition-commit` 依据各目标的 `writerOrder` 确定其写口的相对优先级，随后用 `{priority, canonicalized_edges}` 在全图聚类。各目标的首个写口都属于第 0 层，第二个写口都属于第 1 层。两个写口只要优先级和规范化边沿列表相同，就归入同一块，可以写不同的寄存器或数组。
2. `canonicalized_edges` 从写口 `fire` 所包含的边沿检测器得到。展开边沿脉冲的 OR，按检测器身份排序并去重。身份包含采样源、边沿类型和初始采样等语义。因此 `posedge clk or negedge rst` 和 `negedge rst or posedge clk` 对应同一列表。列表中任一边沿命中即可执行块内的使能检查。电平敏感的 latch 写口使用空边沿列表，每轮检查各自的 enable。
3. `p_commit()` 依次执行全图第 0、1、2……层。当前层的所有块处理完毕，才进入下一层。每条写口通过使能检查后直接更新目标。enable、index、data 和 mask 均取自本轮提交前求好的操作数。掩码写用该写口执行时的目标值保留未覆盖位。所有块完成后才可能开始下一轮 Event 和 Compute。

例如，`a` 初值为 5。下表三个块的边沿在本轮都命中，各写口均使能。

| 优先级 | 规范化边沿列表 | 该块实际执行的写口 |
| --- | --- | --- |
| 0 | `[posedge clk]` | `a ← 9`、`b ← 7` |
| 0 | `[negedge rst]` | `c ← 0` |
| 1 | `[posedge clk]` | `a ← 5` |

前两个块都处理完才执行第三块。`a` 的第 0 级写口将 5 改为 9，当场标记其读者。第 1 级写口将 9 改回 5，活动位保留。下一轮的边沿检测器和计算分区读到的是 5，提交过程中的 9 不会被当成一个可见的边沿。

### 块内 enable bitword

保留现有 enable 位图的批量探测方式。块的事件命中后，按 word（当前为 64 位）读取写口使能 `writer_enable_words`，用该块的静态掩码 `commit_block_writer_masks` 筛出属于该块的写口位。对应位全零时跳过整段，否则按写口顺序检查使能并读取参数。未打包到位图的写口直接检查已求出的 enable 值。输入使能保持为真时，其位可以跨轮保留，但每轮都要重新检查该块的事件条件。单个写口的数据掩码决定目标值中哪些位被写入。

例如，块内一段 writer 共用一个 word，当该段对应的 enable 位全零时，可以一次检查跳过整段。如果其中两位有效，则按原顺序检查并执行相应写入。enable bitword 与 `p_compute` 的 activity 位图区分使用，批量筛选不能改变事件含义或写入次序。 [现有小状态位图说明](../grhsim.md#23-general先-nonsink再按序采样-writer) · [现有大状态 bitword 探测](../../wolvrix/lib/emit/grhsim/cpu-st-cpp.cpp#L3063)

## 5. GRHSIM 分图流程

F38 规划的五个 pass 按以下顺序处理同一张已展开、完成普通 GRH 优化的 Wolvrix IR 图。前两次 split 确定运行时阶段归属，随后两次 partition 分别产生 Compute 和 Commit 的最终分块。`p_input` 装载顶层端口，并使用 Compute 分区给出的输入订阅关系。

```text
grh-to-grhsim → split-event-output → split-compute-commit → partition-compute → partition-commit
```

| Pass | 处理内容 | 供后续步骤使用的结果 |
| --- | --- | --- |
| `grh-to-grhsim` | 将 GRH 中的时钟边沿等事件规格转换为显式的 `grhsim.edgeDetect`，把带事件的写口和调用转换为消费 `fire` 的 GRHSIM op。保留写口优先级、调用条件和采样语义。系统任务和系统函数分别映射到 `grhsim.systemTask` 和 `grhsim.systemFunction`，保留调用名称和参数。 | 一张显式表达事件来源与消费者的混合方言图。普通组合运算、状态声明和状态读口沿用 GRH。 |
| `split-event-output` | 提取事件锥和顶层输出锥。按任务名称识别时隙末输出，将其显示参数绑定到 Compute 边界。保留实际调用时点，以及持续监视所需的参数变化通知。按第 2 节重连使用点、复制共享计算并清除死依赖。 | Event 锥、Output 锥和清理后的主体。延迟任务在 Compute 记录调用或变化，在 Output 读取最终参数并输出。 |
| `split-compute-commit` | 从剩余主体中只剥离写设计状态的 write op 本身，边界止于 write op 的操作数。即使一个生产者只服务于一个写口，其归属也按原阶段保留。 | Commit 的成员集合恰好等于剩余主体中的设计状态写口集合。产生 enable、index、data、mask 的读口和组合 op 归 Compute，事件条件由 Event 提供。 |
| `partition-compute` | 依托 `SemanticTree` 建立 Compute Node 图，对照 GSIM 的粗化和初始分图聚合超节点。建立输入端口、事件、状态到读者分区的订阅，以及分区间的值传播关系。每个数组按整个状态聚合读者。 | Node 到最终超节点的映射、超节点 DAG、拓扑顺序、激活关系及所需边界值。对齐运行同时导出第 3 节的合并 trace。 |
| `partition-commit` | 将全图的 Commit 写口按 `{priority, canonicalized_edges}` 聚类，每个写口恰好进入一个块。生成按优先级排列的块序列，对块内可批量检测的 enable 安排 bitword 检测。 | 当前层所有块执行完才进入下一层。每条有效写口就地提交，按第 6.3 节判定激活及续轮。 |

当前写设计状态的六种 op 是 `grhsim.write`、`grhsim.writeMask`、`grhsim.writeArray`、`grhsim.writeArrayMask`、`grhsim.fill` 和 `grhsim.latchWrite`。状态声明由各阶段共享。[方言写口分类](../../wolvrix/lib/dialect/grhsim/ops.cpp#L563)

例如，时钟上升沿在 `en` 有效时写入 `q <= a + b`，顶层输出为 `out = q ^ mask`。边沿检测归 Event，输出异或归 Output。即使加法结果只供该写口使用，`a + b` 仍归 Compute，Commit 中只有消费这个结果的 `grhsim.write`。按活动度划分加法所在分区、按事件与优先级划分写口所在块后，仍保持这条操作数边界。

现行流水线依次调用 `grhsim-dialect-translate`、`split-event-and-output`、`split-nonsink-and-sink`、`partition-nonsink` 和 `partition-sink`。上表给出 F38 实施后的 pass 名称和职责，其中后三级按五阶段模型的 Compute/Commit 边界重新划分。 [现行流程入口](../../scripts/grhsim_flow.py#L224)

## 6. 运行时数据结构

以下名称用于 F38 生成模型的设计。字段名包含所属对象和保存的内容，涉及时间时还注明采样或发布的时点。`round` 从一次 `p_event` 开始，到对应的 `p_commit` 结束。`eval` 覆盖一次输入装载到最终输出之间的全部 round。方括号给出逻辑索引，emitter 可以把索引编成定型字段、位偏移或直接引用。

### 6.1 分图结果怎样进入生成模型

| 静态调度数据 | 索引和内容 | 使用位置 |
| --- | --- | --- |
| `edge_detector_specs[detector]`、`event_conditions[event]` | 前者给出一个检测器的采样源、边沿类型和初始采样电平。后者定义某个事件如何组合检测结果。事件驱动的写口、即时调用和延迟任务引用各自的事件条件。 | `p_event` 采样并计算本轮事件。 |
| `compute_subscriber_masks[source]` | 来源区分输入端口、检测器脉冲、跨分区值和设计状态。数组以状态身份索引，掩码覆盖读取其任意位置的所有 Compute 分区。每项给出要置位的分区 word 及掩码，分区位号取拓扑序。 | Input、Event、Compute、Commit 把目标位并入实例的待执行分区位图。 |
| `commit_blocks_in_priority_order[block]`、`commit_block_writer_masks[block, word]` | 前者保存全图按优先级排列的块，每块记录规范化边沿列表、成员写口及各写口的目标。后者标出某个写使能 word 中属于该块的写口位。 | Commit 按层遍历块，在块内做 enable bitword 探测并逐口写入。 |
| `writer_operand_sources[writer, operand]`、`value_storage_bindings[value]` | 前者将写口的使能、各动态索引、数据和掩码分别映射到来源 IR Value。后者确定该值的存储位置。多个写口引用同一个 Value 时共用其来源。 | 生成器据此发射类型匹配的读取，每个写口按自己的事件、使能和优先级使用这些值。 |

同一生成模型的所有实例共享这些静态对应关系。它们可以编成直接调用、定长掩码或只读表，由生成器按模型选择。现有 `SinkSchedule` 属于编译 session，生成的 `eval()` 只需访问已确定的字段和分块代码。[现行调度结构](../../wolvrix/include/transform/grhsim/sink-schedule.hpp#L26) · [现行存储布局](../grhsim.md#51-named-stores)

### 6.2 每个模型实例保存什么

| 实例字段与逻辑索引 | 保存的值和使用者 | 更新时点与有效期 |
| --- | --- | --- |
| `input_port_value[port]`、`input_port_last_sampled_value[port]` | 前者是调用方写入的端口值，后者是 `p_input` 最近一次采到的端口值。 | 每次 `eval()` 开头，`p_input` 先比较两者，若有变化就激活该端口的消费者，再保存本次采样值。此值在本次所有轮次中保持稳定，并保留到下次 `p_input` 比较。 |
| `output_port_value[port]` | 调用方读取最后发布的输出。inout 的输入侧走输入路径，输出数据和输出使能各有对应的输出字段。 | `p_output` 在收敛后写入，保留到下次发布。 |
| `committed_state_value[state]` | 已提交的寄存器、锁存器或存储器值。Event 和 Compute 读轮首设计状态，Output 读收敛后的设计状态。 | 初始化时装载，Commit 写入，跨轮、跨 `eval()` 保存。 |
| `edge_last_sampled_level[detector]` | 一个边沿检测器上一次采到的输入电平。例如 `posedge clk` 检测器保存上次采到的 `clk`。 | 按检测器定义初始化。每次 `p_event` 先读取它来判边，再保存刚采到的电平，跨 `eval()` 保留。 |
| `edge_fired_this_round[detector]` | 同一检测器本轮是否命中指定边沿。生成的 `event_conditions` 表达式读取这些位，得到各使用点的 `fire`。 | 每次 `p_event` 覆写，包括写入未命中的零值。 |
| `compute_partition_pending_bits[partition]` | 每位对应一个等待执行的 Compute 分区。初始化标记首轮需执行的分区，调度器按订阅置位。 | `p_compute` 访问分区时清其位。Commit 此后设置的位供下一轮消费。 |
| `compute_boundary_value[value]` | 按来源 IR Value 提供跨分区结果、写口操作数、系统调用的数据输入和需要保留的调用结果（含 DPI）。多个消费者共用同一值，常量和稳定的输入快照可以直接绑定。 | `p_compute` 在消费者执行前发布对应值，整个 `p_commit` 期间只读。延迟任务在 `p_output` 读取最后一轮的有效值。未激活的生产者沿用仍有效的边界值，采样结果保留至下次实际采样。 |
| `writer_enable_words[word]` | 每位是一个可批量探测写口的 enable 电平。Commit 用块掩码筛选写口，再检查各自的写入条件。 | enable 的来源变化时更新位值，允许跨轮保留。事件触发只对当轮有效。 |
| `system_state_value` | 每个实例统一保存 `systemTask` 和 `systemFunction` 所需的运行状态。按调用语义分配必要内容，例如一次性执行记录、采样标志、活动监视器和本时隙的待输出记录。 | 模型初始化时建立。进入 `eval()` 时重置本次采样标志并调度需采样的调用。Compute 按实际调用或观察参数变化更新记录。Output 消费本时隙的待输出记录。跨 `eval()` 的记录按第 2 节保留。 |

例如，端口 `clk` 和它的上升沿检测器上次都采到 0，调用方把 `input_port_value[clk]` 改为 1。`p_input` 检测到端口变化，激活数据消费者，并把 `input_port_last_sampled_value[clk]` 更新为 1。首轮 `p_event` 读取这个 1，与检测器自己的 `edge_last_sampled_level[posedge_clk]` 中的 0 比较，报告上升沿并将检测器电平更新为 1。如果发生续轮，端口采样值仍为 1，检测器这次比较的是 1 和 1，边沿触发位为假。

`compute_partition_pending_bits` 在连续轮次间复用。拓扑下游在访问前仍能收到本轮的置位。遍历结束后，Commit 向已消费完的位图写入下一轮的状态读者，接下来的 Event 再并入新触发的订阅者。若某状态只被 Event 锥读取，满足第 1 节的续轮条件时，即使 Compute 位图为空，也会再次执行 `p_event`。 [现有活动位消费](../../wolvrix/lib/emit/grhsim/cpu-st-cpp.cpp#L2620)

### 6.3 Commit 的局部变量与读者激活

`p_commit()` 共用一套写口调度和 `committed_state_value` 存储。函数入口设一个栈上的 `bool needs_next_round = false`。块的事件或电平条件命中后，按第 4 节检查写口使能，再使用提交前已求出的操作数。以下两条规则直接设置下一轮的活动位，函数结束时返回 `needs_next_round`。

1. **标量逐写口判变。** 在该写口执行处，用局部变量算出本次写后值，与目标存储此刻的值比较。两者不同时，就地写入、激活该目标的读者并置 `needs_next_round` 为真。各优先级块都执行这条规则。第 4 节中 `a` 经历 `5 → 9 → 5`，仍会续轮，整次 Commit 无需为 `a` 暂存候选值或轮首值。
2. **数组按有效写入激活。** 点写、行写、整写和填充都按写口顺序直接更新目标。事件命中、写使能有效且所用索引合法时，执行写口，把该数组的全部 Compute 读者并入下一轮活动位图，并置 `needs_next_round` 为真。沿用数组写口的 `on-write` 语义，有效的掩码写即使 mask 全零也触发。写入时无需保存写前镜像、比较数组内容或跟踪读写行号。[现有数组写口用例](../../wolvrix/tests/emit/test_grhsim_cpu_st_cpp.cpp#L5718)

例如，`mem[3]` 原值为 5，一个上升沿写口又写入 5。读取 `mem[3]` 和读取 `mem[7]` 的分区都会在下一轮执行，其他数组的读者保持原有活动位。若下一轮没有新的边沿，写口即使仍使能也不会再写。对于 `mem[i] <= mem[j]`，右侧数据仍由 `p_compute` 的读口发布到 `compute_boundary_value`。掩码写使用目标位置此刻的值保留未覆盖位。

## 7. 实施与验证顺序

1. 检查 `grh-to-grhsim` 产生的事件、写口及调用的对应关系，再检查 `split-event-output` 完成后的主体图。核对仅供剥离阶段使用的 op 已离开主体分图，共享计算按需复制，状态和有副作用的调用保留原身份。覆盖事件独占、输出独占、仅 Event/Output 共享和三阶段共享四类依赖锥。
   对该主体记录设计状态写口的 op ID 集合。检查 `split-compute-commit` 的 Commit 成员与该集合相等，再检查 `partition-commit` 的各块恰好覆盖这些 ID 各一次。用独占的地址计算、使能比较和数据读口验证其 op ID 均留在 Compute。
2. 建立剩余主体图上的活动分区和提交块，用第 4 节的 `a`、`b`、`c` 检查块成员和执行顺序，覆盖跨寄存器同键聚类、同层不同边沿分块、全图第 0 层先于第 1 层。将同一 OR 事件的边沿顺序对调，核对聚类键相同。另检查跨 word 的 enable 筛选。固定数据与使能，只切换时钟，检查每个边沿的写入与即时调用次数，以及无关纯计算分区的执行次数。再覆盖仅数据变化、数据与事件同轮到达、组合事件连续两轮触发。用同轮双事件、禁用写口、重叠掩码和动态索引覆盖提交行为。 [现有时钟隔离用例](../../wolvrix/tests/emit/test_grhsim_cpu_st_cpp.cpp#L2938)
3. 接上五阶段 `eval()`，以跨多个活动分区的组合链验证输入变化在首轮传到末端、无写入时全程只执行一轮。验证标量单口同值写回时收敛，两个边沿写口在同轮写出 `5 → 9 → 5` 时激活读者并续轮。核对读者只观察到 5，派生边沿检测不会看到中间值 9。另测实际可见的状态变化能在下一轮触发派生时钟及锁存器反馈。对数组分别覆盖有效同值写、零掩码写和同轮覆盖恢复，检查每种情形都续轮并激活读不同行的全部订阅分区，无关分区保持原有活动位。事件未命中、使能为零或索引越界的单个写口均不触发续轮。检查每次 `eval()` 只装载一次输入、只发布一次最终输出，收敛前触发的延迟任务能在输出阶段执行。
   对 `$monitor` 和 `$strobe` 检查每个调用点都生成一个保留原名的 `grhsim.systemTask`。两者显示同一信号时共用该信号的 Compute 边界值，加入任务前后的设计状态和 Commit 写口集合相同。覆盖监视器首次报告、稳定时隙无输出、同一时隙参数多次变化只报告最终值，以及注册新参数表后继续观察。让同一 `$strobe` 调用点在一个时隙实际执行两次，并让参数在调用后变化，核对两条输出都使用最终值。
4. 先用含条件分支、单前驱链及扇出的 FIRRTL 小模块对照两端的 Node 图，重放合并 trace，检查每个超节点的成员、跨区边和动态规划切点。再以香山第四次 DCE 后的同源图核对分图，报告入口 Node 配对情况、逐阶段划分差异，并对差异样本给出首处分歧及双端 trace。核对剥离结果、提交块与最终输出，同时记录主体超节点数量、活动次数、提交块和 enable word 的跳过情况。运行时行为用相同激励的参考仿真验证。
5. 验证运行时存储的生命周期。用两个交错运行的模型实例检查 `system_state_value` 的隔离。让一次 `eval()` 经历多轮 Compute，核对同一 `$random` 调用点只采样一次，下次 `eval()` 重新采样。一次性任务只在重新初始化模型后才可再次执行。重新初始化后也检查检测器前值和首轮边界值。让 enable 和数据跨轮保持相同而只有事件改变，核对写口仍使用正确参数。让两个写口复用同一读口结果，并在提交过程中覆盖源元素，核对两者读到相同的提交前值。用点写与整写重叠检查优先级和最终数组内容，检查生成模型的实例布局中没有专用的写前镜像或判变字段。
