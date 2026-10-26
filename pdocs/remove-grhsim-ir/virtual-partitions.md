# 单图与虚拟分区的逐步形成

始终操作一个已经展开的 top Graph；状态、带地址 read、计算、写口和调用不离开这张图。虚拟分区表达归属和执行/优化边界，没有模块、端口或第二套 use-def。

## 1. 转换与分区是两个步骤

**grh-to-grhsim 不创建虚拟分区。** 转换及随后的全图优化完成后，才由 **grhsim-split-event-and-output** 首次提取 Event/Output。

这里的先后顺序固定：op 转换 → 无分区优化 → 首次提取三区域 → General 三分 → nonsink 活动度切图 → sink 时钟/门控/优先级分区并发布顺序 → emit。不能把虚拟归属提前到转换，也不能推迟到 emitter。

| 完成的步骤 | 可执行 op 的归属示意 |
| --- | --- |
| grh-to-grhsim 与无分区优化 | 没有 grhsim.partition 属性 |
| grhsim-split-event-and-output | ["event"]、["general"]、["output"] |
| grhsim-split-nonsink-and-sink | General 细分为 ["general","nonsink"]、["general","small-sink"]、["general","large-sink"] |
| grhsim-partition-nonsink | 如 ["general","nonsink","sn_17","node_3"]；两类 sink 暂不细分 |
| grhsim-partition-sink | 如 ["general","small-sink","group_2"]、["general","large-sink","group_4"]，并发布 SinkSchedule |

grhsim.partition 是 string[] 属性，完整路径为 PartitionKey，前缀表达层次。阶段 schema 规定前三类区域及 General 的三个子区域，后续路径项是稳定文本 key；不是 OperationId、SymbolId 或扫描 ordinal。

已分区阶段，一个可执行 op 只属于一个叶 owner；阶段细化后父容器不直接持有 op。无分区阶段则统一没有 owner，不能提前挂 ["general"] 或 ["unpartitioned"] 来冒充“尚未分区”。混合缺失/已有归属的图不能提交为完整阶段。

声明、端口元数据和初值是共享资源；状态 read、常量、edge-detect、writer 和调用等可执行 op 在拆分后各有归属。空区域不需要合成无用 op，区域层级由阶段 schema 与已有属性共同确定。

## 2. Event 与 Output 在哪里、怎样提取

位置固定为：

```text
grh-to-grhsim
→ 无分区优化（包括 edge-detect 等价合并）
→ grhsim-split-event-and-output
→ grhsim-split-nonsink-and-sink
```

split-event-and-output 收集两组根，使用同图 producer/use-def 提取闭包：

| 目标 | 根与反向闭包 | 重接与归属 |
| --- | --- | --- |
| Event | 每个 edge-detect 的事件输入；沿其 producer 递归，包含输入/状态读、常量、readArray 及动态地址计算 | 事件锥进入 Event，已有检测器移入 Event 并重接输入；检测器本身及其历史不额外复制 |
| Output | top 输出端口绑定值；monitor/strobe 的 callCond/参数 | 输出锥进入 Output，重接端口和任务，建立所需变化历史/output-end 写回 |
| General | 提取后仍有常规消费者的原操作，以及普通写口/调用等执行根 | 原侧保留被使用的计算，清理失去所有用途的纯死锥 |

Event 的一次提取对同一源 op 使用一张局部 clone 映射；所有 Event 根共享同一 Event 副本。Output 的输出根和任务参数根也共享本次 Output 提取映射。同一表达式被三个区域使用时，三个区域的普通计算/读口分别持有自己的 op，而不是共享一个仍只有单一 owner 的计算。

先收集 Event/Output 两组根和全部用途，再决定移动或复制。只供一个区域使用的普通 op 直接取得该区域归属；跨区域共享时才复制，并重接各区域消费者。fire 属于允许跨区使用的结果：Output 遇到检测器时停止提取，不复制检测器及其历史。声明只作引用目标，状态 read/readArray 及地址锥则按消费者所在区域提取。

例如转换后尚未分区：

```text
%q    = read @q
%addr = add(%q, %sel)
%v    = readArray @mem(%addr)
%gclk = and(%clk, %gate)
%fire = grhsim.edge-detect(%gclk) {edge=posedge, prevInit=0}
grhsim.write @q(%fire, %en, %v)
top.output = %v
```

首次拆分后仍是同一 Graph：

```text
["event"]:
    %gclk.ev = and(%clk, %gate)
    %fire    = grhsim.edge-detect(%gclk.ev)

["general"]:
    %q.gen    = read @q
    %addr.gen = add(%q.gen, %sel)
    %v.gen    = readArray @mem(%addr.gen)
    grhsim.write @q(%fire, %en, %v.gen)

["output"]:
    %q.out    = read @q
    %addr.out = add(%q.out, %sel)
    %v.out    = readArray @mem(%addr.out)
    top.output = %v.out
```

这里的缩进只是展示 op 属性；不是 region、子模块或新端口。输出读与地址计算在收敛后重新求值，General 写参数按本 round 采样；两处引用同一个 @mem 声明。

Event fire 跨区域供写口/任务使用是明确允许的依赖；monitor/strobe 需要 eval 内粘滞触发，不能只用最后一轮 pulse。DPI/随机等非纯结果则按原 effect/sample identity 使用合法的采样代理/快照，不能无条件复制调用，也不能为锥闭包增加调用次数。所有普通锥依赖和这些例外均由 verifier 明确校验。

R4 已实现上述提取，并在图中记录 single-original-call 策略；跨区域的 effect 结果使用 held sample。冻结 dpi_bit_abi 在旧 General/Output 中确实各调用一次；R5 实际比较也暴露了 DPI 顺序/触发差异。2026-10-25 用户已明确选择单个原调用与原图独立调用顺序，见[决定](20261025-single-call-decision.md)；已确认的精确差异单列为批准项，触发错误修复而不豁免。原日志和严格比较保留，不能把这两项决定推广成任意行为变化许可，见 [基线记录](baseline-and-capabilities.md#r4r5-的旧-dpi-行为差异)。

## 3. General 的区域与活动度切图

grhsim-split-nonsink-and-sink 以 writer 目标的状态策略区分 small/large。writer 私有且允许移动的纯参数锥可归对应 sink，共享计算或不能私有化的效果结果留在 nonsink；各区域通过同图 value 明确连接，不能让同一个 op 同时属于两个区域。

此时 large-sink 的“归属”不表示它的全部计算都等到 P_large_sink 执行：其 enable/index/data/mask 在 P_general 采样，提交才在 P_large_sink。small-sink 更新 next；output-end 历史保持在 Output。状态分类、采样和提交不是一张模糊的 op→role 表。

grhsim-partition-nonsink 随后只对 nonsink 做活动度切图，形成 node/超节点等多级归属。地址计算、readArray 和数据计算可以同属一个叶分区；跨分区仍直接使用同图 value。不得把索引读改为 whole-read + sliceArray 来迁就切图，它们的基线越界路径必须保持。

真实活动度边界确定后，允许按生产开关执行一轮便宜共享计算 clone。每个 clone 设置目标 owner 和新 op/value symbol，维护来源及采样合法性；之后局部 simplify 不得跨 owner 合回。局部候选表、成本与拓扑在 pass 内使用，不成为跨 pass 的可编辑成员树。

## 4. Sink 分区与顺序数据

grhsim-partition-sink 对 small-sink / large-sink 按时钟 fire、门控和优先级细分虚拟分区。它同时产生 SinkSchedule，标注 sink 在 General 中的求值/采样、小状态 next 写入及大状态提交的顺序，以及每个 run 所需的 nonsink 依赖。Output 的历史仍在 Output 内按 output-end 契约生成，不并入这份 sink 调度。

同一 guard 的 writer 可能因优先级被其他组的 writer 隔开；可以缓存 gate 判定，但提交 run 必须维持原 writerOrder。归属回答“属于哪个虚拟分区”，SinkSchedule 回答“这些分区/写操作按什么顺序执行”；两者不能互相替代。

粗 sink 区域中的纯计算可能已被叶内 simplify 合并。最终分组时，partition-sink 负责按各组需求私有化共享纯锥、重接 operands 并校验 owner；不能复制 effect，也不要求 simplify 提前预知最终分组。完成这些改图后才发布调度。

SinkSchedule 是首个需要跨 pass 保留的额外分析产物。此前归属只在 GRH 属性，必要的成员/边界查询从当前图临时构建。结构与生命周期见 [架构](architecture.md#4-sinkschedule-与-emitter-私有数据)。

## 5. grhsim-simplify 的两个改写范围

不修改现有 GRH simplify；独立 grhsim-simplify 不需要 role 参数：

- 无分区阶段，全图是同一个范围。CSE/常量传播/alias 可以全图进行，等价 edge-detect 也通过专门规则合并；全局共享状态优化维护全部引用。
- 分区后，完整叶 PartitionKey 是范围边界。每个叶有独立的常量池、CSE、alias 追溯及队列，把外部 operands 视为不透明输入；不能跨 Event/General/Output，也不能跨两个不同 nonSink/sink 叶分区合并。
- 局部改写保持跨界输出的 value 身份、symbol 和完整类型，不重接外部消费者；可以就地改写或保留同分区等宽 assign 作为出口。此 ID 保留只约束本次改写，不承诺跨 freeze 稳定。
- DCE 把出口、端口和 effects 作为根；真正无人使用的 clone 可删除。used-bits 可读取全图需求并集，但只能改当前 owner，不能局部窄化共享状态。
- 新 op/常量继承当前 owner；跨区 clone 显式设置目标 owner。采样、历史、writerOrder 和完整类型继续限制重写，同 owner 不代表任意 effect 都能合并。

例如两个等价 detector 在无分区时可以合并；两个分别属于 nonsink/sn0 与 nonsink/sn1 的 and(%x,%mask) 则必须保留各自计算。第一次拆区域就是从全图化简切换到局部化简的界线。

“完整叶”取当前图实际完成的细化层次：General 三分后 small-sink 是一个粗叶，最终 sink 分组后 group_2 才是叶。不能按共同前缀 general 或 nonsink 将不同叶重新放进一个 CSE 范围；不另设 role/phase 分支。

## 6. ID、symbol 与属性维护

当前 [GRH 实现](../../wolvrix/lib/core/grh.cpp) 的 GraphBuilder::freeze 会重编号存活 op/value 并将 generation 重置为 0；旧 ID 的数字可能重新指向别的实体。不能长期保存裸 ID→partition 表。

| 对象 | 使用约束 |
| --- | --- |
| PartitionKey | 属性中的稳定文本路径，与 op ID、op symbol 和运行时 ordinal 解耦 |
| OperationId / ValueId | 当前 design/top/revision 内的高效引用；图或编号重建后丢弃 resolved 表 |
| SymbolId | symbol table 内部编号，不作持久 key |
| graph + op/value symbol 文本 | checkpoint 引用、诊断和必要的重绑定；rename、删除和 symbol 转交必须维护引用 |

symbol 文本不是永久 UID。属性随 op 保留，因此 rename 不影响 owner；新建/替换 op 明确维护 owner，删除自然删除成员。clone/load 保留属性和来源但获得新实例身份，重建所有本地引用。

sink 调度只在最终改图/编号完成后发布，之后的图变更使其失效。热路径使用本地 ID/ordinal，文本解析和哈希只在扫描/建立结构时完成，不在每次 value 访问时查 symbol。

## 7. chunk 与虚拟分区无关

活动度分区和 sink 分区由 transform 确定；**chunk 只在 emit/grhsim/cpu-st-cpp.cpp 内按 max-function-lines 拆函数**。同一分区可生成多个 chunk，Event/Output、init、eval 和所有其他生成函数也同样受限。

chunkFrame 保存跨 chunk 的局部活跃变量；它不保存分区归属，不产生新的激活边界，不替代 state/nonSink/writer 参数快照。改变预算不改 grhsim.partition、不重做活动度切图、不使有效 SinkSchedule 失效。

checkpoint 只保存图阶段、归属、选项和实际 clone。重新载入 sink-partitioned 图后运行 partition-sink 重建调度，再由 emitter 选择当前预算下的布局/函数/chunk；不存在独立分区 JSON 或可执行 CPU IR。
