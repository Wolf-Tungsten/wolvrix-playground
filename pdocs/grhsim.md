# GrhSIM 当前实现

本文描述当前源码中的 GrhSIM：统一 GRH 上的仿真方言、六阶段调度、八个
transform pass，以及单线程 C++ emitter。它是 `pdocs/` 唯一保留的文档；
旧迁移计划、阶段记录、性能实验和调查报告不再作为当前实现说明。

## 1. 架构与数据边界

GrhSIM 全程使用普通 GRH 的 `Design / Graph / Operation / Value / LogicalType`、
use-def 和 JSON。输入是完成层次展开、必要的数组规范化、组合环处理、verify
和普通 `simplify` 的 flattened top Graph。仿真转换继续修改这个 Graph，
没有独立的 GrhSimModel、CPU IR、仿真 pass registry 或 CPU planning pipeline。

- 基础计算、状态声明/读取、数组、端口和 DPI import 复用基础 GRH op。
- 仿真事件、写端口、调用和优化 op 属于 `grhsim` / `grhsim.cpu` 方言，
  不加入基础 GRH 算子集。完整扩展列表见第 4 节。
- `grhsim.partition` 是 op 上的 string-vector 虚拟归属路径。它表达执行责任，
  不创建第二棵图；共享状态声明不属于执行分区。
- `SinkSchedule` 是 pass 间首个额外分析产物，保存在外部 session 的 typed
  scratchpad。它仅描述 sink 分组、writer 顺序及依赖，不复制计算图或写入参数。
- emitter 私下分析存储、数组访问、激活关系、C++ 函数和 chunk 布局，
  不把这些结果序列化成另一套 CPU plan。

JSON 的 per-graph `formatVersion=2`；方言版本为 `grh:2`、`grhsim:1`，
使用 CPU 优化 op 时还有 `grhsim.cpu:1`。类型、stage、归属和配置随 JSON
保存，session 中的 schedule 和 emitter 私有分析不随 JSON 保存。

实现入口：[方言定义](../wolvrix/include/transform/grhsim/ops.hpp)、
[共享流程](../scripts/grhsim_flow.py)、
[CPU emitter](../wolvrix/lib/emit/grhsim/cpu-st-cpp.cpp)。

## 2. 六阶段调度模型

六个阶段是 `Input → Event → General → LargeSink → Publish → Output`。
其中四个中间阶段组成固定点循环；Input 和 Output 每次 `eval()` 各执行一次。
这里的 round 是仿真收敛轮次，不能直接当作硬件时钟周期。

```text
eval():
    清空本 eval 的 sampled 标志和 timeslot sticky trigger
    激活本 eval 需要采样的非纯 system-function 所在 nonsink
    P_input()
    pending = true
    round = 0
    while pending:
        if ++round > max-round: 报错退出，不执行 Output
        P_event()
        P_general()
        P_large_sink()
        P_publish()     // 更新 pending
    P_output()
    如启用波形，在这里记录本 eval 的最终状态
```

`max-round` 的 emitter 默认值是 100000。超过上限是收敛失败，
不能把未收敛结果作为正常输出。

### 2.1 Input：固定本次 eval 的输入

`pInput()` 比较公开输入端口与 `inputStore` 中的快照；变化时更新快照，
激活依赖这些输入的 nonsink。后续阶段读取快照，使一次 eval 内的输入保持一致。
初次初始化还负责建立必要的初始 activity，不能只依赖外部输入变化启动模型。

### 2.2 Event：逐 round 检测事件

`pEvent()` 求 Event 的纯计算/状态读取锥，然后执行 `grhsim.edge-detect`。
检测器比较当前事件值与 `prevEventStore`，产生本 round 的 fire；
每个 round 都无条件采样、更新前值，即使相关 writer 的 enable 为假。
因此时钟已经越过的边沿不能在之后 enable 变真时被补发。

事件型 monitor/strobe 的触发被 OR 到 `timeslotTriggerStore`。这个 sticky
trigger 在本 eval 内累积，直到 Output 使用；最后一轮 fire 为零不会清掉先前事件。

Event 在 General 之前执行。派生时钟、组合产生的事件和 latch/ICG 变化，
通过状态发布及后续 round 传播。不能把所有纯计算都放进事件门控，
否则产生事件本身所需的计算也可能停止。

### 2.3 General：先 nonsink，再按序采样 writer

`pGeneral()` 先清空大型 writer 的本 round enable 记录，再依次执行：

1. activity bitmap 驱动的 nonsink `sn_N()`；
2. `SinkSchedule.generalRuns` 对应的 `writer_run_batchN()`。

nonsink 负责共享计算、状态读取和普通效果调用，按消费者角色发布
`nonSinkBoundaryStore` 和 small-sink 的 enable/payload boundary。边界变化激活后继；按顺序扫描时，尚未访问的后继
可以在本轮执行。反向/延后活动进入下一轮。每次调用前读取 live activity bit，
不提前缓存整段 bitmap。

writer 是 sink 的采样执行代码，**同时包括 small-sink 和 large-sink**，
不是 nonsink activity 函数，也不能把 `writer_run_batch` 理解成 SmallNonSink。
只有完全属于一个 writer 的纯参数锥随 writer 移动；共享计算和效果仍在 nonsink。

- 小状态：按 fire、enable、index、data、mask 执行写入，更新 next；
  后续 General 读取仍看到本轮 current。
- 大状态：在这里采样有效写入的 enable、index、data、mask 到 boundary，
  不修改大型 current。未触发的写入不保留上一轮的有效 enable。
- 如果一个 sink-local 值还是可观察边界，writer 禁用也不能遗漏必要的边界刷新。

small-sink 的外部动态 enable 同步到稠密位图。连续 eligible writer 段先用
相关 bit 的 mask 探测全零，再读取 payload；常量和 sink-local enable 截断该段。
同一 run 的 enable 全部可探测且没有可观察的局部边界时，还可在进入 run 前跳过整段。
位图不是 nonsink activity：数据未变而发生新 fire 时，已启用的 writer 仍执行。

同一状态的重叠写遵守 `writerOrder`，同优先级保留声明顺序；
后执行的有效写覆盖先执行的相应位/元素。所有 writer 参数都必须在大型提交前采样，
避免先提交的写改变后续 writer 的 data 或动态 index。

### 2.4 LargeSink：提交已采样的大型写入

`pLargeSink()` 遍历 `SinkSchedule.largeCommitRuns`，按规定顺序提交 General
保存的 payload，原地修改大型 current；不重新求 writer 数据锥。
这使大型数组不需要每轮复制一份完整 next。

提交记录 dirty / before 信息。对读者的 activity 和下一轮需求在 Publish
归并；本轮 General 已经结束，不允许提交中的状态变化反过来影响本轮采样。
数组部分写入、掩码写入及别名源读取必须保留写前快照语义。

### 2.5 Publish：发布状态并判定收敛

`pPublish()` 按 dirty-state bitmap 扫描状态：

- 小状态比较 current 与 next；变化则发布 next→current，并激活下一轮读者。
- 大状态已经原地提交；根据配置检查变化或有效写入，发布 activity，
  不执行整个大型存储的 next→current 拷贝。
- 清除已处理的 dirty 标志，将 `activeNext` 转给 `activeCurrent` 并清空来源。
- 状态要求后续观察或仍有 activity 时保留 `pending_`，否则本 eval 收敛。

`mem-write-activate=on-change` 以实际变化为依据；`on-write` 将有效大型写入
本身视为调度事件，即使新旧数值相同也保留所需轮次。emitter 默认
`on-change/on`（write-activate / enable-bitmap），生产 Make 流程显式使用
`on-write/on`，两者不要混为同一默认口径。

### 2.6 Output：只观察收敛结果，最后统一写 history

`pOutput()` 求输出锥、执行时隙任务，再写公开输出端口。
自由形式 monitor/strobe 对 callCond 和参数的变化敏感；事件形式使用本 eval
积累的 sticky trigger。全部观察完成后，才统一提交 `grhsim.history-write`
对应的 history 快照。Output-end history 不激活本 eval 的 General 固定点循环。

例如小寄存器 `q <= d`：Event 产生 fire，General 采样 d 并写 q.next，
Publish 发布 q.current，后续 round 传播 q 的读者，收敛后 Output 才观察最终 q。

### 2.7 效果调用的次数与顺序

普通 DPI/task 和非纯 system-function 保留原始调用身份。General 的因果顺序由
`grhsim.effectOrder` 保证；跨 Event/Output 的结果通过
`grhsim.sampleBoundary=true` 的 held sample 传递，不复制原始 DPI/random 调用。
非纯 system-function 还保留 `sampleId/sampleScope` 和本 eval 的 sampled 标志。

`grhsim.effectPolicy=single-original-call` 表示保留一个原始调用位置，
不表示任意 DPI 在整个 eval 中无条件只执行一次：实际次数仍受原进程、fire、
callCond、activity 和采样策略约束。旧实现曾有在 Output 再调用 DPI 的 fixture，
不能把那个历史行为当作当前调用次数规范。

## 3. Pass 划分与流水线

共有 **8 个 registered transform pass**；C++ emission 是 emitter，不是第九个 pass。
共享流程按下面的顺序推进，packing / masked-OR recovery 默认开启：

```text
普通 GRH frontend / flatten / comb-loop-elim / verify / simplify
  → grh-to-grhsim
  → grhsim-simplify
  → grhsim-pack-bit-registers → grhsim-simplify       [开启时]
  → grhsim-recover-masked-or → grhsim-simplify        [开启时]
  → grhsim-split-event-and-output
  → grhsim-split-nonsink-and-sink
  → grhsim-partition-nonsink
  → grhsim-simplify                                 [partition_simplify 开启时]
  → grhsim-partition-sink
  → emit grhsim-cpu-st-cpp
```

| Pass | 主要职责 | 参数与默认值 |
| --- | --- | --- |
| `grh-to-grhsim` | 原地转换写端口、task/function/DPI，显式建立事件 detector、writer 顺序、调用效果和逻辑域；保留计算、声明、数组及结果身份 | `top`：唯一 top；`logic-domain=2state`，也接受 `4state` |
| `grhsim-simplify` | 仿真方言的常量折叠、类型感知 CSE/DCE、位运算改写、prefix used-bit 收窄、保守等价状态合并、mux 链折叠 | `max-rounds=8`；没有 `scope` / `role` 参数 |
| `grhsim-pack-bit-registers` | 打包满足条件的单 bit 寄存器，最多 64 bit/word，保留旧状态的类型视图和声明来源 | 可选 `report`，默认不输出 TSV |
| `grhsim-recover-masked-or` | 从 mux-to-zero / AND-mask 的 OR 归约恢复 `grhsim.cpu.maskedOr`，保留多项同时匹配的 OR 语义 | `min-terms=16`；可选 `report` |
| `grhsim-split-event-and-output` | 提取 Event/Output 纯计算和读锥；建立 held samples、效果顺序、monitor/strobe history 和 sticky trigger 语义 | `top` |
| `grhsim-split-nonsink-and-sink` | 将 General 分成 nonsink、small-sink、large-sink；分离 writer 私有参数锥和共享 boundary | `mem-min-bytes=64` |
| `grhsim-partition-nonsink` | 建立可激活 node/supernode DAG，做有界边界 clone，保持数据/效果依赖无环 | `max-node-work=128`、`max-supernode-work=128`、`segment-penalty=1`、`semantic-nodes=0`；clone 选项见下文 |
| `grhsim-partition-sink` | 按 clock/fire、状态优先级和合法共享 enable 细分 sink，生成有序 General/large-commit runs，并发布 SinkSchedule | pass 自身 `enable-guard-min-size=8`，0 关闭 hoisting；共享 Python FlowOptions 默认显式传 0 |

Factory 参数沿用普通 pass 的 `-key=value` 形式；Python 使用下划线关键字。
显式 top 必须存在；不指定时要求唯一 top。report 是诊断输出，不是执行计划。

### 3.1 转换和优化的边界

`grh-to-grhsim` 只产生 `converted`：此时没有 partition、Output history
提取、小/大状态选择或 session schedule。逻辑域转换修改真实 LogicalType、
常量及 InitSpec，不依靠 emitter 隐式丢弃 X/Z。同域重复转换是 no-op；
转换后半途失败的图标记 `conversion-failed`，不能继续使用。

`grhsim-simplify` 在未分区图上全局优化；完整分区后逐 complete leaf 优化，
保护导出值/类型，不跨 owner 把 clone 合回。共享状态收窄/合并只在分区前做。
等价 detector 只有输入、完整类型、edge、prevInit 和 sample/update 策略
全部相同才能合并；random / 外部效果不能当作纯计算 CSE。

bit-register packing 仅处理未分区图中满足条件的 unsigned TwoState 单 bit
状态：常量初始化、完整读、单 writer、共享 fire/enable/mask 控制；其余保持原样。
masked-OR recovery 不假设 one-hot，多 mask bit 同时为 1 时必须按位 OR。

### 3.2 大小状态与 nonsink 分区

Logic 状态按 `ceil(totalWidth / 8) >= mem-min-bytes` 判为 large；
其余状态和 Output history 为 small。依据逻辑字节数，不能按有无数组 shape
选择 large；一个足够宽的标量也可能 large。

nonsink 的 work 至少为每 op 一份，并随 Logic result word 数增加；mul/div/mod
计四倍，外部 function/DPI 计八倍。单个不可分 node 可以超过预算。
`semantic-nodes=1` 保留声明 anchor 不被吸收；work 预算控制激活粒度，
不是 C++ 行数预算。

clone 默认 `clone-shared=1`、`clone-max-fanout=8`、`max-clones=250000`、
`clone-lossy-compare=1`。仅对合法便宜的 scalar TwoState 边界计算做一轮有界
复制，例如 not/assign、常量 xor/add/sub 及允许的 lossy eq/ne；常量随目标复制。
leaf 和 supernode 的数据及 effect-order 依赖必须保持无环。

### 3.3 分区路径与 stage

| `grhsim.stage` | 可执行 op 的 owner |
| --- | --- |
| `converted` | 无 partition |
| `event-output-split` | `[general]`、`[event]`、`[output]` |
| `nonsink-sink-split` | General 变为 `[general,nonsink]` / `[general,small-sink]` / `[general,large-sink]` |
| `nonsink-partitioned` | nonsink 变为 `[general,nonsink,supernodeKey,nodeKey]` |
| `sink-partitioned` | sink 变为 `[general,small-sink,groupKey]` 或 `[general,large-sink,groupKey]` |

Event/Output 始终各是一个 leaf；共享声明不带 owner。每个 executable op 必须
恰好属于一个完整 leaf，父容器不直接拥有 op。detector 属于 Event，普通效果属于
General nonsink，时隙任务和 history 属于 Output。跨阶段依赖只接受定义好的
Event pulse / held General sample 等边界；sink 私有计算不能逃出自己的 owner。

### 3.4 SinkSchedule 与 checkpoint

`SinkSchedule` 含 DesignStamp、配置 hash、completeness、`sinkGroups`、
`generalRuns`、`largeCommitRuns`。group 记录 partition key、fire（latch 可空）
和 hoisted guards；run 引用原 writer IDs、必要 nonsink prerequisites 和既定顺序。
它不含重复 operands、Output history plan、CPU 存储或 chunk。

分组不能破坏全局写顺序。`A(clock0), B(clock1), C(clock0)` 可能要求
clock0 group 在 run 序列中出现两次，不能把 A/C 跨过 B 强行聚合。
同优先级的先后由声明顺序决定，不由 symbol 拼写决定。

pass 与 emitter 使用同一个外部 session；`requireSinkSchedule` 校验 slot 类型、
instance/top/revision/config 和当前图的归属、依赖及顺序。load、clone、freeze
重编号、rename 或其他图修改后，旧 schedule 失效。加载 completed checkpoint
后重跑 `grhsim-partition-sink`，在当前 session 重建 schedule 再 emit。

同配置重复 completed pass 会校验并保持图不变；sink pass 仍重建 artifact。
修改大小阈值从 Event/Output checkpoint 重来，修改 nonsink 配置从 General-split
checkpoint 重来，修改 sink 配置从 nonsink checkpoint 重来。失败的部分状态
不能当作 checkpoint；sink schedule 只在最终校验成功后原子发布。

## 4. GrhSIM 方言扩展 op：完整列表

当前共 **14 个：13 个 `grhsim` op，1 个 `grhsim.cpu` op**。
下表 operands 按真实签名顺序列出；未注明的 op 没有 result。
状态声明、read/readArray、普通算术、assign、arrayCreate、sliceArray 和
DPI import 都是基础 GRH op，不计入此表。

| # | Op | Ordered operands | Result 与语义 |
| --- | --- | --- | --- |
| 1 | `grhsim.edge-detect` | `event` | unsigned scalar TwoState bit `fire`；按 edge 和前值检测事件 |
| 2 | `grhsim.write` | `fire, enable, data` | 完整写寄存器 |
| 3 | `grhsim.writeMask` | `fire, enable, data, mask` | 按位掩码写寄存器 |
| 4 | `grhsim.writeArray` | `fire, enable, index0 … indexK-1, data` | 写前 K 维索引定位的元素或子数组 |
| 5 | `grhsim.writeArrayMask` | `fire, enable, index0 … indexK-1, data, mask` | 对所定位宽度做按位掩码写 |
| 6 | `grhsim.fill` | `fire, enable, data` | leaf 广播或完整 packed 填充 |
| 7 | `grhsim.latchWrite` | `enable, data, mask` | 电平敏感 latch 写；没有 fire operand |
| 8 | `grhsim.system-task` | `fire, callCond, args…` | 执行系统任务 |
| 9 | `grhsim.system-function` | `args…` | 一个原始类型 result；保留 pure/random/external 效果 |
| 10 | `grhsim.dpi-call` | `fire, callCond, inputs…, inoutInputs…` | `return?, outputs…, inoutOutputs…` |
| 11 | `grhsim.history-write` | `data` | Output 全部观察后的 history 更新 |
| 12 | `grhsim.bitSelect` | `mask, whenSet, whenClear` | mask 每 bit 选择 whenSet 或 whenClear |
| 13 | `grhsim.prioritySelect` | `c0 … cN-1, a0 … aN-1, default` | 第一个真条件对应的 arm，否则 default |
| 14 | `grhsim.cpu.maskedOr` | `mask, dataArray`，或由 `views` 指定的源 operands | OR 所有被 mask 选中的元素；无匹配为零 |

### 4.1 Event 和 writer 合约

`edge-detect` 输入必须是一位 scalar Logic；必需属性为
`edge=posedge|negedge|both`、一位 literal `prevInit`、`sampleScope`
（通常 `event-round`）和 `historyUpdate=unconditional`。TwoState 前值不能含 X/Z。
物理 history 由 emitter 分配，语义在尚未分区时已经成立。

clocked writer 以 `regSymbol` 指向原状态，latch writer 用 `latchSymbol`；
都有非负 `writerOrder`。enable 是 scalar Logic bit。clocked fire 只能是
detector 结果、合法的 pulse OR/assign 或化简出的零；不能直接传 raw clock
或用常量一表示每轮发生边沿。

索引按前 K 维寻址，data 覆盖剩余 shape；mask 是被寻址总宽度的 bit mask，
不是每元素一个布尔位。fill 允许 leaf-width 广播或完整 packed 宽度。
例如 `q` 总宽 64、shape `[4,2]`、leaf 8 bit：

```text
grhsim.writeArray(fire, enable, i, row16)
    // K=1，row16 覆盖 shape [2] 的一行
grhsim.writeArrayMask(fire, enable, i, j, byte8, mask8)
    // K=2，mask8 控制该 byte 的各 bit
```

普通寄存器写转换示意：

```text
转换前：registerWritePort @q(enable, data, clk) {eventEdge=[posedge]}
转换后：fire = grhsim.edge-detect(clk) {
            edge=posedge, prevInit=1'h0,
            sampleScope=event-round, historyUpdate=unconditional
        }
        grhsim.write(fire, enable, data) {regSymbol=q, writerOrder=0}
```

基础 GRH 原始写/调用仍使用自己的 raw-event 合约，不向基础方言加入仿真 phase。

### 4.2 调用与 history 合约

system-task 要求 `name/procKind/hasTiming/eventDriven`；system-function
要求 `name/effect`，非纯函数还要求 `sampleId/sampleScope`。显式
`hasSideEffects=true` 可以阻止原本可纯化的函数被当成纯函数。

DPI 要求 `targetImportSymbol/procKind/hasTiming/eventDriven`。参数/结果
在各 direction 内保持 import 声明顺序，return 在 output results 之前；
数量、kind、宽度和符号性都与基础 `kDpicImport` 校验。无事件调用可以
`fire=1, eventDriven=false`；这与 clocked writer 禁止 fire=1 是不同合约。
被 guard 禁用时，结果的 held 语义仍要保持。

history-write 要求 `regSymbol` 指向 `grhsim.history=output-end` 的共享
register，并有 `grhsim.outputEnd=true`。data 和状态的完整 LogicalType
必须相同，每个 history 恰好一个 history-write；没有普通 fire/enable/
writerOrder，也不能同时存在 General writer。

自由 monitor/strobe 用 callCond/参数与 history 的变化触发：Logic 用 case
inequality，Real/String 用相应 inequality；history 初始化为类型零/空串。
所有 history 必须在 Output 观察后一起提交，不能先更新一部分再供其他任务读取。

### 4.3 优化 op 的类型限制

- bitSelect 的三个 operands 和 result 是完全相同的 scalar TwoState Logic，
  当前宽度 1–64；它与整值 mux 不同。
- prioritySelect 的 N 为 3–64；条件为 unsigned scalar TwoState bit，
  arms/result 是 1–64 bit scalar TwoState Logic，按已有 mux 类型规则规范化。
- maskedOr 的 N 项（N≥2）、每项 W bit：mask 宽 N，data 总宽 N×W、shape `[N]`，
  result 宽 W，均为 TwoState Logic。多项匹配按 OR 合并，不假设 one-hot。
  `views` 是 `(maskOperand, maskBit, dataOperand, dataLow)` 元组；
  offsets 校验后引用普通 GRH value，不嵌套另一份计算图。

## 5. C++ emitter：存储、batch 与 chunk

### 5.1 Named stores

当前 emitter 固定声明下面 18 个 `*Store` 成员，再单独声明
`smallSinkStoreNext`，共 **19 个 named store 对象**。字段按模型及配置添加；
没有字段的 store 仍生成空 struct 和成员。因此，出现名称不等于该模型
实际用它保存了 payload。完整清单如下：

| Store | 内容 |
| --- | --- |
| `inputStore` | 本 eval 输入快照 |
| `smallSinkStore` | 小状态 current |
| `smallSinkStoreNext` | 小状态 next，与 current 复用同一 store type |
| `largeSinkStore` | 大状态 current |
| `nonSinkBoundaryStore` | 非 small-sink 专用的跨分区结果、可观察边界及 held sample |
| `smallSinkEnableBoundaryStore` | small-sink enable 锥的跨分区输入字段；可探测的动态 writer enable 另有稠密 `words` 位图 |
| `smallSinkPayloadBoundaryStore` | small-sink index / data / mask 参数锥的跨分区输入字段 |
| `largeSinkEnableBoundaryStore` | 大 writer 本 round 的有效位；bitmap 模式使用 `words`，关闭 bitmap 时使用逐 writer bool |
| `largeSinkPayloadBoundaryStore` | 大 writer 在 General 采样的 index / data / mask，供 LargeSink 提交 |
| `prevEventStore` | detector 的前一次事件值，每个 Event round 无条件更新 |
| `eventActStore` | detector 本 round 产生的 fire |
| `timeslotTriggerStore` | 事件型 monitor/strobe 在本 eval 内累积的 sticky trigger |
| `sampledStore` | 非纯 system-function 的本 eval 已采样标志；采样结果保存在 boundary，不在此 store |
| `onceStore` | initial system-task 已执行标志，init 时清空 |
| `largeBeforeStore` | `on-write` 时每大状态一个 bool，记录有效写入；`on-change` 时保存首次变化前的元素值 map |
| `largeWholeBeforeStore` | `on-change` 且有合格 whole-array 写时保存完整数组的写前快照 |
| `largeWholeDirtyStore` | 与 whole-array 快照配套的 dirty 标志，Publish 比较后清除 |
| `memoryReadIndexStore` | 精准唤醒使用的最近一次实际 indexed read 的 flattened leaf 起点；N 表示无效读取、N+1 表示尚未采样 |
| `memoryTouchedStore` | 本轮已实际提交的大状态 leaf 触碰位图，Publish 完成激活后清除 |

两个 `smallSink*BoundaryStore` 保存 small sink 的输入，不是目标状态的
current/next；小 writer 在 General 消费输入并直接更新 `smallSinkStoreNext`。
`analyze()` 从 writer 的 enable 和 payload 参数分别向上遍历同 owner 参数锥，
在跨 execution-owner 的位置分配相应 boundary。只供 small sink 的值直接以
对应 small boundary 为发布位置；同时供其他分区、波形或 held sample 使用的值
保留普通 boundary，并在发布时同步 small boundary。输入端口保留 `inputStore`
快照，再同步其 sink 消费视图。同一 value 可以同时拥有 enable、payload 和
普通 boundary 字段；这些视图在 input/producer 发布时一起更新。

sink 输入按来源读取：

| 输入来源 | 当前物理位置 |
| --- | --- |
| 外部输入端口 | `inputStore.vN`；small-sink 使用按角色同步的 enable/payload 字段 |
| detector fire | `eventActStore.vN`；合法 OR/assign 可展开组合使用 |
| nonsink 或其他 owner 产生的 small-sink enable 锥输入 | `smallSinkEnableBoundaryStore.vN`，producer 发布 |
| nonsink 或其他 owner 产生的 small-sink index / data / mask 锥输入 | `smallSinkPayloadBoundaryStore.vN`，producer 发布 |
| 其他跨分区结果、可观察边界或 held sample | `nonSinkBoundaryStore.vN`；必要时同时有 small-sink 消费视图 |
| 只属于该 sink 的私有参数锥 | writer batch 的 `vN` / temporary，拆 chunk 时可能进入该 batch 的 private frame |
| 私有参数锥中的状态读取 | 从 `smallSinkStore` / `largeSinkStore` current 求值，再进入 local 或必要 boundary |

small-sink 的 `read(value)` 优先使用对应消费视图，writer payload 参数优先
读取 payload 字段；没有跨 owner 存储需求才生成 local。small boundary 是
按 value 去重的共享输入字段，不是逐 writer 的额外采样记录。
large writer 读取 input/普通 boundary 或局部值，再将 index/data/mask 及有效位另存到
`largeSink*BoundaryStore`，保证后续 LargeSink 提交不重新读取已变化的源。

`grhsim-partition-sink` 仍可依据 GRH 的 fire/priority/enable 身份建立静态 group
和 runs，分组本身不依赖 C++ store 名称。emitter 在此有序 schedule 上为
外部动态单 bit writer enable 按 value 分配稠密 bit；共享 enable 共用一个 bit。
input 变化、普通 producer、DPI 等发布结果时，在同一个 compare-store 分支
同步字段和 bit，enable 从 1 变 0 时也清除 bit。init 同时清零所有 boundary
和位图，首轮激活所有 nonsink，由真实求值发布非零初值；不生成巨型 OR 初始化式。

每个 run 内连续 eligible writer 形成探测段，每段最多引用 **8 个 bitmap words**。
探测表达式只 OR 各 word 中属于本段的掩码，不能被同 word 的无关 enable 误触发。
常量 enable、sink-local/state-read enable 不使用旧的 shadow bit 跳过，遇到它们
先结束当前探测段，再按普通路径求值。段全零时跳过逐 writer guards、私有 payload
和 writer 执行；已有的无条件共享/可观察计算留在段外。若整个 run 都可探测且
没有可观察的局部边界，再把相同探测提升到 run 入口。

large-sink 的 `largeSinkEnableBoundaryStore.words` 是 General 采样后供
LargeSink 提交的有效写入位图，不能替代 small-sink 的 enable 探测位图。
另外，`activeCurrent/activeNext` 只驱动 nonsink，不负责 sink activity。
探测不跨 run 重排，保持 writer 优先级、多消费者值的一致性及 sink-local
可观察边界的刷新；`mem-enable-bitmap=off` 关闭两类位图优化但保留 boundary 字段。时钟型 writer 仍须
响应新的 fire，不能仅因 data 数值未变就被当作无 activity 而跳过。

`largeWholeBeforeStore` / `largeWholeDirtyStore` 的字段仅在相应 on-change
whole-array 路径需要时生成；生产默认 on-write 时这两个 store 可以为空。

这些 named stores 无论多大都保留语义字段，不能因字段多就改写为不透明的
`cells_*` 数组。enable bitmap 本身可以有 `words` 数组，这是明确的数据结构。

模型还含有不以 Store 命名的存储，不属于上述语义 store：

- `activeCurrent` / `activeNext`：当前及下一 round 的 nonsink activity bitmap；
  `dirtyStateFlags`：待 Publish 的状态 bitmap；`pending_`：继续收敛标志。
- `chunkFrame_<function>` 类型及调用时的局部 `chunkFrame`：函数拆分后的
  temporary / spill 存储，生命周期属于原函数调用，不是长期模型状态。
  这里的 `cells_*` 是 private frame 布局，详见 5.3。
- `cpu_rng`：随机数状态；`perf_`、`profileEnabled_`、`snTimeTicks_` /
  `snTimeFires_`：性能/计时控制和计数；启用 execution counters 时还有
  `opExecCounts_` / `opExecEvals_`。
- 启用波形时的 `waveform_ctx_`、`waveform_entries_`、`waveform_enabled_`、
  `waveform_path_`、`waveform_time_`：FST writer、观察缓存及输出控制。

精确声明来源是 [cpu-st-cpp.cpp](../wolvrix/lib/emit/grhsim/cpu-st-cpp.cpp)
的 `CpuStEmitContext::generate()`；字段创建及启用条件在 `analyze()`，
实际读写在 writer、各 phase 和 init 中。

### 5.2 General / LargeSink 的有序函数组织

`pGeneral` 用有序 member-function-pointer 列表循环调用 activity batches，
然后调用 writer batches；`pLargeSink` 同样分派 commit batches。phase driver
保持固定规模的调度代码，计算 locals 放在对应的有限 batch 内，
不制造全模型 `pGeneral_chunkN` 和巨型 spill frame。

- 每个 nonsink supernode 一个 `sn_N()`，内部按拓扑顺序执行其 leaf 的 op；
  leaf 仍是 pass 优化的归属边界。activity batch 负责连续 **24 个 bitmap bytes**，
  每 byte 最多 8 个 nonsink；调用前即时读取、清除该 bit。
- 每个 writer batch 最多 **128 个连续 General runs**，不是 128 个 writer。
- 每个 commit batch 最多 **128 个连续 large-commit runs**。
- clock/fire、共享 gate 和相邻相同 enable 可以在合法范围内合并 guard。
  这是保持 run/优先级顺序的局部连续聚合，不是全局按同一时钟重新排序。
- small-sink 连续段按相关 enable bit 的掩码探测全禁用，单次探测最多 8 个 words；
  无局部可观察边界且全段 enable 可探测时，可提升到 run 入口。

示意代码（省略真实类型名及 guards）：

```cpp
void Model::pGeneral() {
    largeSinkEnableBoundaryStore = {};
    for (const auto phase : {&Model::pGeneral_active_batch0,
                             &Model::writer_run_batch0}) {
        (this->*phase)();
    }
}
```

### 5.3 函数行数限制与 private frame

`max-function-lines=1024` 按最终生成的真实函数行数计数，包含 scaffolding；
`max-tu-bytes=1048576` 控制翻译单元分割。它们与 nonsink work 预算不同。

[function-writer](../wolvrix/lib/emit/grhsim/function-writer.cpp) 按预算拆分函数。
General/LargeSink 的计算 locals 已限制在各自 batch 内，不汇总到 phase driver。
跨 chunk 的 shared locals 属于原函数的私有 `chunkFrame`；声明本身使函数
超预算时，也可以将必要 locals spill 到该 frame。没有 shared/spill local
或跨 chunk 返回控制时不分配 frame。拆分保持初始化、loop lifetime、
作用域和 return 语义。

只有 private chunkFrame 超过 **1024 个 logical fields** 时，才允许将默认
初始化字段按完整 C++ type 聚合成 indexed `cells_*`；显式初始化和返回控制
字段继续独立。这个规则不能应用到 named stores。

纯 sink-run locals 沿 guarded path 使用前必定赋值，因此不强制整块清零；
显式初始值、return 控制和其他函数仍保留初始化要求。这个优化不允许跳过
可观察 boundary 更新。store/frame 构造函数显式 default，需零默认的使用点
做 value initialization；String 保留构造和正确 reset。

### 5.4 数值、数组和运行时边界

- CPU execution 只接受显式 TwoState Logic；FourState 在 GRH/JSON 中合法，
  但此 emitter 拒绝，不做隐式 X/Z 投影。scalar Real/String 分别用
  `double/std::string`。当前 CPU emitter 不支持 top-level inout ports。
- Logic width 是 total width，shape 为 outermost-first。状态动态访问逐维
  检查索引；`sliceArray` 保持独立的 flattened-offset 合约，不能互换两者
  以绕过边界规则。重叠源写入采用必要的 snapshot。
- 生成代码要求 little-endian Clang 的 `_BitInt` 支持。超过 64 bit 的
  TwoState leaf 使用单个 `unsigned _BitInt` 和 native 表达式，并执行逻辑宽度
  mask；不使用按值返回 `std::array` 的 wide helper 链。该策略来自 wide
  word-loop helper 的 -O3 inliner/SLP 编译热点测量。剩余 helper、DPI/task
  边界仍遵守 caller-provided output buffer / pointer ABI，避免宽值临时复制。
- InitSpec 支持常量、fill、readmem、seeded random 和使用后的重新 init。
  runtime random 当前支持无参数、至多 32 bit 的 scalar `$random`。
  不支持的 live op、system-function/task 或签名使 emission 失败，
  candidate 生成成功前不替换已有模型。

## 6. 使用、诊断与验证

生产入口经项目 Makefile 执行：

```sh
make xs_grhsim_emu
make run_xs_grhsim_emu XS_SIM_MAX_CYCLE=100000
make reemit_grhsim
```

`reemit_grhsim` 的 checkpoint/输出参数见根 Makefile 和对应脚本；加载后由
共享流程校验 stage、补齐剩余 pass，并重建当前 session 的 SinkSchedule。
旧 independent-model / CPU-plan API 和已移除选项不能继续使用，
即使旧选项被设为 0 或空串也应显式拒绝。

FST、性能计数和原生 operation execution counts 是可选诊断。
`execution-counters` 默认 off；开启时记录 operation、effect、writer-sample、
writer-commit、history-write，`evals` 是 eval 调用数，不是周期数。
counter graph、sites 和生成源码绑定；跨 chunk 预算比较按原 op/category
对齐。模块归因使用原生 graph source/ownership 和 manifest，不借用旧 IR IDs。
带 instrumentation 的模型不能直接作为无 instrumentation 的性能候选。

行为对比必须明确 SV 来源：XiangShan 的 Verilator 基准使用 plain 版本 SV，
不能把 aggregate 版本独有的断言失败当成当前 GrhSIM 的偏差。100k 是
指定周期窗口，可做 NEMU difftest 和输出序列逐条比较，不等于跑完 CoreMark。

当前实现的主要代码及测试入口：

| 内容 | 源码 / 检查入口 |
| --- | --- |
| 方言注册和校验 | [ops.cpp](../wolvrix/lib/transform/grhsim/ops.cpp) |
| 八个 pass | [transform/grhsim](../wolvrix/lib/transform/grhsim) |
| SinkSchedule 合约 | [sink-schedule.hpp](../wolvrix/include/transform/grhsim/sink-schedule.hpp) |
| C++ 六阶段、存储和数组访问 | [cpu-st-cpp.cpp](../wolvrix/lib/emit/grhsim/cpu-st-cpp.cpp) |
| batch 内 chunk 和 frame | [function-writer.cpp](../wolvrix/lib/emit/grhsim/function-writer.cpp) |
| 生产 stage/checkpoint/reemit | [grhsim_flow.py](../scripts/grhsim_flow.py)、[Makefile](../Makefile) |
| 方言/转换回归 | `make test_remove_grhsim_ir_foundation`、`make test_grh_to_grhsim`、`make test_grhsim_transforms` |
| 分区、schedule、emitter 回归 | `make test_grhsim_virtual_partitions`、`make test_grhsim_sink_schedule`、`make test_grhsim_cpu_st_cpp` |

small-sink boundary 回归包含：70 个动态 enable 跨 bitmap word、共享 value 的
三种 boundary 角色、DPI/普通 producer 发布、非零状态初值、首次 eval 已有
clock edge、重复 init、常量/局部 enable、混合时钟优先级和私有 payload 的
精确执行计数。`max-function-lines=16/1024` 以及 `mem-enable-bitmap=on/off`
均由生成代码的编译执行验证；已有 waveform、数组别名和 large capture 回归保留。

描述的工作树基线：root `bb563b9`、wolvrix `0437a9a` 加 small-sink boundary
修复；更新日期 2026-10-27。

## 7. 单线程性能修复记录（2026-10-27）

约束：不使用 PGO，不使用仿真多线程，不以单时钟假设替换六阶段收敛；
保留多时钟、派生时钟、同轮 NBA 快照及写入优先级。先用孤立 ROB 缩短
生成和验证周期，再回到 XiangShan CoreMark 100k；诊断采样时间不混入性能基线。

### 7.1 修复前基线与结构证据

small-sink boundary 修复后的非 PGO 模型，CPU2 单核、NEMU difftest on、
waveform/execution counters/SN timing off：100k host **1009.903 s**，
99.019 cycles/s，峰值 RSS 203380 KiB。10 个逐万周期检查点及终点与历史
plain SV Verilator 记录一致：238535 条指令，guest cycles 100001，
cycleCnt 99996，最终 PC `0x80000cde`。
证据：`ptmp/sink-boundary-coremark100k-20261027/{result.json,run.time,xs/generation-identity.json}`。

当前生成模型有 38808 个 nonsink、203 个 activity batches、1415 个顶层
writer batches 和 993 个顶层 commit batches；function writer 拆分后 writer
family 共 13807 个函数、commit family 5311 个函数，原 pPublish 有 2332 个 chunks。
每轮即使 fire/dirty 为零也先调用大部分 helper，再在 helper 内判断。
`nm -S` 归类的 nonsink/writer/commit/publish 机器码分别约
73.7/55.4/21.4/5.9 MB，emu text 共 191.1 MB。
非 PGO gsim 历史三轮 100k 是 46.960/47.111/47.100 s，text 55.5 MB；
其 checkpoint/周期端点略不同，且该实现对部分派生时钟有限制，
只用作性能量级参考，不能据此删掉 GrhSIM 多时钟能力或作为逐周期行为 oracle。

### 7.2 首批修改：避免空闲 phase 进入冷 helper

1. `activate()` 对同一目标 bitmap byte 合并 OR 掩码。current/next 分别合并，
   不跨计算/发布边界移动 activation；减少生成代码及重复 read-modify-write。
2. 每个 writer batch 在入口检查其 run 的 fire 析取，最多收集 16 种 fire
   表达式；无 fire 的 level-sensitive run 保守执行。检查发生在函数拆分
   helper 之前，下降沿和 NBA 后无新 edge 的 round 不再进入冷 writer chunks。
   payload enable 不提前采样，因为同 batch 较早 run 可能发布较晚 run 的输入。
3. large commit batch 在入口探测涉及的 capture-enable bitmap words；
   空位图不进入 commit chunks。普通 batch 最多收集 8 words，单个不可重排
   run 若本身更大则保留完整 run；bitmap off 保留原路径。采样仍发生于 General，
   提交仍发生于 LargeSink，不用源 data/enable 替代已采样 payload。
4. pPublish 每 16 个 dirty bytes（128 状态）生成独立 batch，入口 probe 为零
   时不调用其中的状态发布 helper；保留 state ordinal 顺序、current/next
   比较、large on-write 所需额外 round 和 activeNext 转移。

首批已通过 `make test_grhsim_cpu_st_cpp` 和 `make test_grhsim_sink_schedule`。
新增稀疏 dispatch 回归覆盖 145 状态跨 publish batch、两输入时钟和 NBA 后
派生时钟、多 writer A/B/A 的 scalar/array masked 优先级、large memory 互读
capture-before-commit，以及 16/1024 函数预算与 bitmap on/off。
ROB 同一 100050 周期完整 trace：baseline **262.747 s**，首批 candidate
**246.229 s**，耗时减少 **6.287%**（1.0671x），checksum 同为
`11266713584084230617`。前 2k 是 1.96653 → 1.73068 s（-11.99%），
后半 trace 工作量不同，因此不采用短样本推算完整收益。
4,394,996,424 bytes 全输出验证已通过：100050 cycles × 5491 words，
零排除，与已用 plain SV 验证的 r78 golden `cmp` 完全一致；SHA256 为
`688ac2f6e9c5509eb00dad368ead600a07ec27d956b1ec9a429d8e46309a7df1`。
每版本仅测一轮，baseline timing 与另一 CCD 上编译有重叠，candidate
timing 无并行编译；这些局部结果不替代整机测量。
证据：`ptmp/grhsim-speed-20261027/rob-{baseline,dispatch}/runtime-100050.{log,time}`。

采样证据：同一未改动的整机 baseline 用 `perf record -e cpu-clock:u -F 199`
跑满 100k，214920 samples、无丢样。nonsink 82431（38.35%）、writer 88899
（41.36%）、commit 14341（6.67%）、publish 15082（7.02%）、activity dispatcher
4069（1.89%）、event 853（0.40%）；emu 本体占 96.58%，NEMU shared object
仅 0.05%。因此外部 difftest 不是主要差距来源，单独消除 dispatcher 也不足以
完成目标，后续要减少 writer 与 nonsink 的实际计算、访存及机器码工作集。
采样路径：`ptmp/grhsim-speed-20261027/profile/{perf.data,symbols.txt,dso.txt}`。

### 7.3 第二批修改：固定位置读取与局部共同 gate

1. `masked_or` 的 `views` 控制只需固定单 bit；旧 emitter 先将 bool[352]
   全数组逐 bit 打包为 384bit 临时值，再选固定 bit，且多个热点重复此过程。
   新路径将静态 offset 映射到 flat leaf 与 leaf 内 bit：单 leaf 范围直接
   读取 named boundary 字段，跨 leaf 保留原 packing。`sliceStatic` 的 shaped
   单 leaf 提取复用此路径。不会以新 state 读取替换已保存的边界快照。
2. writer enable 的不同表达式常为 `shared_gate & wide_bits[index]`。
   既有 guard 仅识别完整 enable 同值，动态 bit-select 仍无条件执行。
   新路径仅在没有既有 group guard、local cone 没有可观察 storage 结果时，
   沿本 run 内两态 scalar 1bit AND/LogicAnd/Assign 求全部 writer 的共同
   boundary/input 因子，在该 run 原执行位置即时探测后跳过私有计算。
   不提升到整个 batch，不重排 A/B/A，不跨 General/LargeSink 移动采样。

第二批 `make test_grhsim_cpu_st_cpp`（含固定 bit/slice oracle）和
`make test_grhsim_sink_schedule` 均通过。新增共同 gate 专项用例的初次
生成检查发现 fixture 中共享 enable 被合法迁到 nonsink；已用独立动态
索引输入修正构造，确保存在真实 sink-local AND cone，生成检查已通过。
专项生成模型完整执行时，16/1024 两预算均检出纯 small-state 派生时钟
遗漏：首个 NBA 更新时 `derived` 保持 0，而 oracle 要求 24。定位到
`analyze()` 的 `stateRound_` 只登记 nonsink 与 General reader，漏掉 Event
直接读取的状态；publish 后没有 `pending_=true`，detector 无下一轮。
最小修复将 Event-owned state read 也登记为需要收敛续轮，既不改 fire
采样也不把所有 state 变化都强制续轮。既有 sparse case 被 large memory
`on-write` 的额外 round 掩盖，新 case 仅 small state，保留其失败检查。
修后完整 `make test_grhsim_cpu_st_cpp` 和 `make test_grhsim_sink_schedule`
均已通过，包含两个预算的纯 small
派生时钟与 observed FST 检查；`python-optimized` 和下述 ROB 数字均标为
中间候选，最终接受与整机 100k 改用 `python-eventfix` / `xs-eventfix`。

固定候选 stage library SHA256 为
`9789e1f798fe72f7610d6aea9cb8a3480f8ff676931775fe81f6a485760e941b`。
ROB 完整 100050 cycles 为 **129.659 s**，相对 baseline 262.747 s
耗时减少 **50.65%**（2.0265x），相对首批 246.229 s 减少 47.34%；
checksum 仍为 `11266713584084230617`，text 由 20,969,818 降到
19,359,660 bytes（-7.68%）。完整全输出比较已通过：与同一 plain SV
golden 的 4,394,996,424 bytes `cmp` 完全一致、零排除，SHA256 与首批相同。
生成代码审计中，ROB bool pack 循环由 1543 降至 19；nonsink 中由 131
降至 15，涉及 59 个 nonsink owner 的 114 个长度 352 全量 packing 均消失。
例如 `sn_1372` 原先打包全部 352 位再抽取，现在直接读取对应数组元素。
这提供了完整活跃 trace 明显加速的具体根因证据，详见
`ptmp/grhsim-speed-20261027/rob-generated-audit.json`。
本轮 timing 后段与另一 CCD 上整机构建重叠，仍是单轮结果，需要无并行
构建复测；不能用 ROB 的 2x 推算整机。整机已用相同 checkpoint 重新
生成（235.38 s）并开始普通 `-O3 -march=native` 编译，无 PGO。
证据：`ptmp/grhsim-speed-20261027/rob-optimized/` 和 `xs-optimized/`。
修后固定 library SHA256：
`96bc47bdb8836d15b224de8f40da371a6c2baf9550d91c1220339344ffc6f442`；
最终性能与全输出验证单独记录，不能混用修前 binary。

### 7.4 最终候选：XiangShan CoreMark 100k

`python-eventfix` / `xs-eventfix` 已完成单线程正式测量。使用与 7.1
相同的 r78 checkpoint、guest image、NEMU、seed 0 和 100000 host cycles，
CPU2 独占，避开 SMT sibling CPU18；测量期间没有编译或 ROB 运行。
普通 `-O3 -march=native`，无 PGO，waveform、execution counters 和
SN timing 均关闭，NEMU difftest 开启。此前因 CPU2 上两个 timing
误并发而中止的结果不计入统计，保留在 `aborted-concurrent/`。

| 指标 | 修复前 baseline | 最终候选 |
| --- | ---: | ---: |
| Host time | 1009.903 s | **646.352 s** |
| Wall time | 1009.94 s | 646.39 s |
| 100k host cycles/s | 99.019 | 154.714 |
| 峰值 RSS | 203380 KiB | 201128 KiB |
| emu text | 191091083 bytes | 188943615 bytes |
| 生成源码 packing 片段数 | 29010 | 23788 |

相对 baseline，host 耗时减少 **35.999%**，加速 **1.5625x**；
text 仅减少约 1.12%，不能将这次收益全部解释为二进制缩小。
packing 计数是生成源码中 `packed* |=` 的出现数，不是动态执行次数，
也不是全部循环的统一计数。writer/commit/publish 入口 probe 增加了
部分 helper 数量，其价值是跳过空闲调用，不能只按函数总数判断收益。

本次退出码为 0，无 difftest 错误。10k、20k……100k 的十个检查点
（host/model cycles、指令数、commit PC、trap PC）和最终端点，均与
baseline 及历史 **plain SV Verilator** 记录一致：guest cycles 100001，
238535 条指令，cycleCnt 99996，最终 PC `0x80000cde`。这是 NEMU
difftest 加十个检查点和端点比较，不是新跑的完整波形等价证明，
也不是 CoreMark 两次迭代跑完 PASS。plain 参考的输入及归档编译元数据
另有 SHA256 清单，未把 aggregate SV 当作行为 oracle。

最终重生成耗时 **211.17 s**。2465 个 CPP、全部 header 及生成 Makefile
与已完整编译的 `xs-optimized` 逐文件 SHA256 一致；先在最终目录重新
生成 PCH，再复用内容和编译标志均一致的 object，重新归档、链接，
没有拷贝旧 PCH、archive 或 executable。最终 `build.time` 的 **18.81 s**
仅为复用后的归档/链接阶段；fresh PCH 单列于 `pch.time`。此前候选的
完整 16-job 编译耗时 **986.67 s**，与其他 CCD 上的 ROB timing 有部分
重叠，不能把 18.81 s 宣称为整模型全量编译时间或直接比较编译收益。

证据目录：`ptmp/grhsim-speed-20261027/xs-eventfix/`：
`logs/xs_grhsim_optimized_100k.log`、`run.time`、`result.json`、
`run-inputs.sha256`、`model-metrics.json`、`object-reuse-plan.json`。
脚本同时校验 baseline 成功状态、plain 来源清单、三方 workload 身份和
明确的十个检查点范围，汇总证据另存 `summary-artifacts.sha256`。

这是一轮候选对已记录 baseline 的比较，尚未做交错多轮 A/B。
整机仍约 646 s，远未达到 gsim 历史约 47 s 的量级，性能目标**未完成**；
后续需对最终 binary 重新采样，区分活跃 writer 计算、剩余 nonsink
宽值搬运及状态发布/收敛成本，不能将旧 profile 的占比直接作为最终热点。

### 7.5 最终二进制重采样与后续候选

对同一 `xs-eventfix` binary 用 `perf record -e cpu-clock:u -F 199`
完整跑 100k，128385 samples、无丢样，difftest 与端点仍正确。采样耗时
645.526 s 仅作诊断，不替代 7.4 的未插桩正式 timing。writer family
51968（40.48%）、nonsink 45054（35.09%）、commit 9723（7.57%）、
publish 9019（7.02%）、activity 3529（2.75%）、event 873（0.68%）；
`memmove` 为 5532（4.31%）。最高 writer owner 是 `writer_run_batch1420`
及其 chunks 合计 5221（4.07%），成本分布在许多 writer/nonsink，
没有一个 helper 能单独解释剩余十余倍差距。
证据：`xs-eventfix/{prefix.perf.data,prefix.perf-all.txt,profile-summary.json}`。

下一批先减少 shaped 动态单 bit 选位的全数组 packing，同时补齐
writer enable 分支中的 packing 缓存作用域回归。原先 `packedNames_`
按整个 run 缓存，而私有 payload 仅在各自 enable 分支赋值；只恢复
旧的 `packed_` 集合不能阻止另一分支引用未赋值的 packed 临时。
此项必须独立验证 enable A/B/A、首次仅 B 以及输入更新后的 B，
不能用零初值偶然正确或整机前缀通过替代专门 oracle。动态选位及缓存
修复已通过下述专项回归，但其整机收益尚未验收，不计入 7.4。

新动态单 bit 路径仅作用于 shaped `sliceDynamic` 的 1bit 结果：先按
原 index 无符号位宽比较语义总宽，再缩窄为 `size_t`，定位
`offset / leafWidth` 的 leaf 并读 `offset % leafWidth`。读取仍使用
原 `read(value)` 字段或本地值，不绕过 boundary 去读最新 state；
负 signed index、高 64bit 非零的宽 index 及末端 padding 返回 0。
多 bit、跨 leaf 的动态 slice 保留旧路线。

条件缓存回归在修复前的 16/1024 两种预算均真实失败：首次
`enableA=0, enableB=1, data=0xabcd` 上升沿，B 应写 `0xabc`，
但 B 分支使用了只在 A 分支赋值的临时值。修复同步保存、恢复
`packedNames_`，不跨 guard 复用非支配定义。证据保存在
`ptmp/grhsim-speed-20261027/conditional-packed-before-{run.log,writer.cpp}`。
完整回归包含 bool[2][176]、signed 3bit leaf、多维数组、128bit
index、NBA 旧值采样、三次 init，以及 A/B/A 启停与同时有效。
`make test_grhsim_cpu_st_cpp` 已完整通过（生成检查及全部生成 C++
编译执行），日志 `dynamic-cache-emitter-test.log`。saved 值通过合法
declared-symbol observation 保留存储，local 值另有无 Store 断言；
没有给纯 op 伪造仅允许 effectful producer 使用的 sampleBoundary。
冻结绑定为 `python-dynamic`，ROB 已单独重生成，性能尚未测量。

进一步候选针对 Demand 只记录一个 enable 的限制：两个不同 enable
共享同一私有 payload 时旧实现将其标成 unconditional，即使两个
enable 都为 false 仍会计算。计划保留无条件 enable/observed 祖先
闭包，其余用需求 enable 集合逆拓扑求并集，按原拓扑和相同集合
连续分块，只在任一消费者 enable 为真时计算。writer 仍保持原顺序，
每个 guard 使用独立的 packed cache 作用域。实现已落盘，新增专项
覆盖 small/large、需求集合包含关系、全关与任一打开时的执行计数、
held observation、NBA 旧值及 A/B/A 优先级。完整
`make test_grhsim_cpu_st_cpp`（含生成 C++ 编译执行）及
`make test_grhsim_sink_schedule` 均退出 0；后者三项 CTest 全过。
日志为 `shared-enable-emitter-test.log`、`shared-enable-sink-schedule-test.log`。
目前仍不能算作已获得的整机性能收益。

同批还将 shaped Logic 常量的 `packed()` 改为直接输出归一化 literal，
避免从已初始化数组再次逐 leaf 打包。整体结果保持 unsigned，防止
signed 8/16bit all-ones 在宿主整数提升后改变 `ReduceAnd` 结果。
常量不可变，此路径不绕过可变 boundary 快照。新增 zero/all-ones、
非均匀宽常量、多维 signed 3bit leaf、mux 与 reduction 回归；
同批专项已随上述完整回归通过。冻结绑定 `python-current` 的
`libwolvrix-lib.so` SHA256 为
`3223e3d977661351458d60057436c831d52bbd29ca9b2e2d68ff81f71dfc93a2`。
当前整机 100k 的正式重测结果见 7.6。

### 7.6 当前候选整机 CoreMark 100k 重测

`xs-current` 使用 7.5 冻结的 `python-current`，同一 aggregate GRH
checkpoint、CoreMark 镜像、NEMU 参考和 seed 0，重新生成并全量编译。
生成耗时 **210.48 s**；因 header 和 generated Makefile 变化，2466 个
TU **零对象复用**，fresh PCH 后编译/链接 **919.91 s**。这是 checkpoint
重生成时间，不能称为从 SV 开始的完整生成时间。普通非 PGO 构建路径，
2466 条实际模型编译命令均为 `-O3 -march=native`、PERF=0、SN_TIMING=0，
无 profile 参数；harness/link 的 `@` 命令未完整打印，其可见范围在
`build-flags.json` 中单独说明，未用 `+ CXX` 标签冒充完整命令。

正式运行 host **642.001 s**，wall **642.06 s**，max RSS **203792 KiB**，
退出码 0，NEMU difftest 开启且无错误。对上轮 646.352 s 减少
**4.351 s（0.673%）**；对最初 baseline 1009.903 s 减少 **36.429%**，
为 **1.5731×**。单次新旧记录之间的 0.67% 不足以证明稳定收益，未做
交错多轮 A/B，不能将本批动态选位、常量或 Demand 优化分别归因。

10k、20k……100k 十个检查点及端点，与 baseline 和历史 **plain SV
Verilator** 记录均一致：guest cycles 100001，238535 条指令，
cycleCnt 99996，最终 PC `0x80000cde`。`result.json` 的检查项全部通过，
包括候选源码/fixture/library 身份、三方输入和 plain 来源哈希清单。
这是 100k 前缀的 NEMU difftest 加检查点/端点比较，未重新运行 plain
Verilator，不是完整波形等价，也不是 CoreMark 两次迭代跑完 PASS。

正式窗口无并发编译或 ROB；波形、commit trace、执行计数器和 timing
诊断关闭。固定 CPU2，运行中一次 `/proc` 采样确认实际 emu **1 线程**、
affinity `{2}`。前后 `/proc/stat` 记录 CPU2 busy 100%，SMT sibling
CPU18 busy **0.0031%**；线程采样不是全程连续监控。观察器固定 CPU8，
不在热循环采样。

静态 packing 片段进一步降到 21826，但 text 从上轮 188943615 bytes
增至 190804118 bytes；这也说明减少源码循环不等于同比运行收益。
整机仍约 642 s，距离 gsim 历史约 47 s 的量级仍很远，性能目标未完成。

证据目录：`ptmp/grhsim-speed-20261027/xs-current/`，重点为
`result.json`、`logs/xs_grhsim_current_100k.log`、`run.time`、
`runtime-observation.json`、`build-flags.json`、`object-reuse-plan.json`、
`model-metrics.json`、`run-inputs.sha256` 和 `summary-artifacts.sha256`。

### 7.7 跨 leaf 静态窗口候选与 ROB 对照

7.5 冻结绑定 `python-current` 对独立 ROB 重生成并构建后，在 CPU2
单线程跑同一 trace 的 100050 cycles：`run_seconds=128.559`，wall
128.75 s，checksum `11266713584084230617`。随后独立 dump 全部
5491 output words/cycle，零排除项，与原 golden 逐字节 `cmp` 一致，
两者 SHA256 均为
`688ac2f6e9c5509eb00dad368ead600a07ec27d956b1ec9a429d8e46309a7df1`。
本次 timing 窗口无并发编译；验证的 wall 134.50 s 包含全输出写盘，
不作为性能结果。证据在 `ptmp/grhsim-speed-20261027/rob-current/`。

下一候选将 shaped Logic 的合法静态 slice 扩展为仅读取覆盖窗口的
leaf，仍从原 `read(value)` 的 boundary/local 快照取值，不穿透
producer 或最新 state。各 leaf 先按语义位宽清理，再 unsigned shift
和拼接；最多展开 32 个 leaf，更大窗口保留原 packing 路径，避免
生成数千项表达式。例：16×6bit 数组的未对齐 48bit 窗口只需读
8–9 个 leaf。新增专项包含 bool、signed 3/6/64bit、多维、宽结果、
末端窗口、32 leaf 上限与 NBA 旧值。不能把上述 ROB 对照归为
该优化收益；它使用的是之前冻结的 `python-current`。

同批候选只消除可证明 identity 的数组重建：同一已存储快照的
升序、完整、整叶静态切片，按原顺序 `arrayCreate` 回完全相同
LogicalType 时，可直接引用该快照。仅限同一 execution owner 的
私有局部值；output、observation、boundary 或中间位宽变化均保留
物化。scalar mux 前的等宽 view 可复用原快照 packing，不能越过
已存储的 scalar 快照。原图 Demand 和 writer 顺序不变；仅当局部
切片/Assign 的全部用户已证明省略，才递归删除死链，省略项明确
列入 counter metadata。审查中排除了将 `viewOnly` 用户直接视为
dead 的错误，因为它仍可能是后续 shaped 输出的有效源。

两项候选的完整 `make test_grhsim_cpu_st_cpp` 已退出 0，包括全部
生成 C++ 的编译和执行；`make test_grhsim_sink_schedule` 三项
CTest 全过。静态窗口专项两种预算都只保留 >32 leaf 的整源 pack
fallback；identity 专项真实消除重建，reordered 和 observed 仍有
执行 site，NBA 旧值 oracle 通过。原 A/B/A packing 专项改用动态
12bit slice，保持真实 packing 覆盖，不因静态快路而丢失回归意义。
第一次失败仅因新增 fixture 使用 ArrayCreate 白名单之外的自定义
属性，已修成 operation symbol，失败日志单独保留；其后还分开了
三条投影链，确保 observation 不将命中路径变成跨 owner boundary。

本轮冻结 `python-windows` library SHA256 为
`0513d72b4dbefdeb188c4bf0a2c1eab9213b6983f5ab5e49fedbefe9d25f2182`，
源码身份 `b6cf47702dd7ca66ed2c73525b09b67bf43a7e3bca18f52ba5856386f7cd347c`，
fixture SHA256 `5537cf070f79eed59c5fb22048c370f2a8384dbd568f1e94b154cd88a582e1a0`。
回归证据为 `windows-regression.json`、`windows-emitter-test.log` 和
`windows-sink-schedule-test.log`，位于 `ptmp/grhsim-speed-20261027/`。
整机 `xs-windows` checkpoint 重生成耗时 210.77 s，退出 0；生成
2467 个 TU，fresh PCH 后全量构建，零旧 object 复用。实际
writer1420 的 256×u64 路线已命中：旧 256 个切片、ArrayCreate 和
数组中间 copy 消失，新 `grhsim_SimTop_tu1925.cpp` 的
`writer_run_batch1420_chunk34` 直接从
`nonSinkBoundaryStore.v3008759` memcpy 2048 bytes 到 packed scalar，
再进入 scalar mux。300×u64 路线仍保留
`nonSinkBoundaryStore.v3338989` 的 copy/pack：其生产者拼接 300 个
已存储 scalar snapshot，结果自身也跨区存储，不能绕过边界。
`array_view_elisions` 总数未变，不能用该字段代替实际代码命中检查。
该候选整机结果见 7.8。

### 7.8 静态窗口与重建消除候选整机 100k 重测

`xs-windows` 使用 7.7 的冻结绑定，同一 checkpoint、CoreMark 镜像、
NEMU 参考和 seed 0。2467 个 TU 全量编译、零旧对象复用，fresh
PCH 后编译/链接 wall **916.76 s**，退出 0。模型实际编译命令
2467/2467 均为普通 `-O3 -march=native`、PERF=0、SN_TIMING=0，
无 profile 参数；harness/link 隐藏完整命令的证据限制仍保留在
`build-flags.json`。本轮校验按新 generated `SOURCES` 验证，未
沿用旧固定 TU 数。

正式运行 host **643.369 s**，wall **643.43 s**，max RSS
**203000 KiB**，退出 0，NEMU difftest 全程启用且无错误。对上一
冻结版 642.001 s 慢 **1.368 s（0.2131%）**，没有测出整机性能
收益；这不是交错多轮 A/B，不能判定稳定退化，也不能将各局部优化
分别归因。对最初 baseline 1009.903 s 仍减少 **36.2940%**，
为 **1.5697×**。静态 packing 片段从 21826 降至 21003，text
从 190804118 降至 190753206 bytes；这些静态变化没有转化成
本轮可观测的性能改善。

10k、20k……100k 十个检查点及端点，与上一冻结版、最初 baseline
及历史 **plain SV Verilator** 记录全部一致：guest cycles 100001，
instructions 238535，cycleCnt 99996，最终 PC `0x80000cde`。
`result.json` 的全部 checks 通过；输入、候选源码/fixture/library、
生成身份、构建日志和最终结果均有哈希校验，上一版结果也绑定其
独立 manifest。未重新运行 plain；这是 100k 前缀的 NEMU difftest
与检查点/端点对照，不是完整 CoreMark PASS 或完整波形等价。

正式窗口无并发构建或 ROB，固定 CPU2、关闭波形/commit trace/
执行计数器及 timing 诊断。一次运行中 `/proc` 采样确认 emu
**1 线程**、affinity `{2}`；CPU2 全窗口 busy 100%，CPU18 为
13/64339 jiffies，即 **0.0202% busy**。观察器固定 CPU8；该
线程/affinity 证据是一次采样，不是全程连续监控。

证据目录：`ptmp/grhsim-speed-20261027/xs-windows/`，重点为
`result.json`、`logs/xs_grhsim_windows_100k.log`、`run.time`、
`runtime-observation.json`、`build-flags.json`、`model-metrics.json`、
`run-inputs.sha256`、`summary-artifacts.sha256` 和 `result.json.sha256`。
本轮重测完成；距离 gsim 历史约 47 s 的性能目标仍未完成，未提交。

### 7.9 同一冻结版本整机 100k 独立复测

按要求再次运行 XiangShan CoreMark 100k。本次直接复用 7.8 已全量
构建并通过回归的二进制，未重新生成或编译；当前源码、fixture、
冻结库及生成身份仍与 7.8 一致。二进制 SHA256 为
`b23bdc5145f27c020f525dac4c957391e334c18447d31c7e437cefe20f3f60f7`。
输入、NEMU 参考及 seed 0 不变，正式运行通过 Makefile target，
新证据单独保存，不覆盖上一轮测量。

结果 host **647.746 s**，wall **647.80 s**，max RSS **203472 KiB**，
退出 0。同一二进制上一轮为 643.369 s，本次慢 **4.377 s（0.6803%）**；
两次同版本测量不是不同优化的交错 A/B，不能将该差异归因于源码变化。
相对最初 baseline 1009.903 s 减少 **35.8606%**，为 **1.5591×**，
距离 gsim 历史约 47 s 的目标仍有较大差距。

NEMU difftest 全程启用且无错误；10k 至 100k 的十个检查点及端点
与 7.8、最初 baseline 和归档 **plain SV Verilator** 全部一致：
guest cycles 100001，instructions 238535，cycleCnt 99996，
最终 PC `0x80000cde`。plain 本次未重跑，来源及结果由原 manifest
和产物哈希重新核验。`result.json` 全部 checks 为 true；当前输入、
旧候选输入、旧结果、新结果及 summary artifacts 哈希校验均通过。
这是 100k 周期前缀，不是完整 CoreMark PASS 或完整波形等价。

仍固定 CPU2，无 PGO、无并发构建或 ROB，波形、commit/RAM trace、
执行计数器及 timing 诊断关闭。运行中一次采样确认 emu **1 线程**、
affinity `{2}`，观察器在 CPU8；全窗口 CPU2 busy 100%，CPU18
仅 1/64775 jiffies busy（约 **0.0015%**）。线程/affinity 为单次
观测，未将其表述为持续监控。

证据目录：`ptmp/grhsim-speed-20261027/xs-windows-repeat1/`，包含
`benchmark.mk`、`result.json`、`logs/xs_grhsim_windows_repeat1_100k.log`、
`run.time`、`runtime-observation.json`、`run-inputs.sha256`、
`summary-artifacts.sha256`、`result.json.sha256` 和对应验证日志。
本轮仅完成重复测量及记录，未新增优化、未提交；性能目标保持未完成。

### 7.10 目标数组直接叶装配候选

7.9 的同版本重复测量没有缩小与 gsim 的差距。本批针对已确认的
`sn_4296` 数据搬运路线：读取 `[224][3]`、每叶 2 bit 的本轮快照，
先 pack 成 1344-bit；另将选中行的 6-bit 快照重复 32 次得到
192-bit，再 concat 成 1536-bit，最后 unpack 到 `[256][3]`。
原生成代码为此执行大宽度移位和多次完整中间值搬运。

新增编译期叶装配计划，在 shaped 结果原计算位置直接填充现有
目标 buffer。首批支持叶边界对齐的等宽 Assign、Concat、Replicate
和 Mux：Concat 最后 operand 填低位叶，Replicate 重复完整叶段，
Mux 读取原条件并在分支内填同一目标。只沿同一 execution owner
内未存储、未观测的私有 scalar 中间链展开；终点读取现有 shaped
快照或不超过 64-bit 的已计算标量。暂限 Logic、相同 domain、
目标总宽大于 64 bit、目标叶不超过 64 bit，不对齐或无法完整证明
的路径回原实现；递归深度/计划节点有上限。

终点不追 RegisterRead，也不跨 storage、small sink boundary、
output 或 owner 重新读取最新状态。保留原 source snapshot、sink
Demand/enable guard、写入顺序、结果比较和 publish/activation。
只有全部 users 都已被叶计划覆盖的私有中间操作才能省略，并在
execution counter metadata 中列为 elided。最终计划中的所有
Source 和 Mux condition 都固定保留其 materialized producer：
审查发现，同一 scalar 可能被一种目标叶宽展开，而被另一种叶宽
当作终点读取，仅检查 consumer 有计划会误删它；现已按最终计划
终点保留修正，并加入专门反例。

本节先记录实现与不变量，完整回归、诊断和性能结果随后追加；
静态候选数或中间值减少均不作为运行收益结论。
新增测试先修正两处 fixture 构造：pure Concat 不能手工标记
effectful sampleBoundary，改用 declared/waveform 的合法观测存储；
nonsink owner 是四级路径，并用两个独立时钟确认真实跨 owner
消费。完整生成 C++ 编译又暴露新 Mux 的 if/else 在小预算下被拆到
不同 helper，产生孤立 else；修为一次采样原条件到 bool，再输出
两个独立 if(condition)/if(!condition)，由原局部值存活分析保存
跨 helper 条件。失败日志独立归档，修正后重新冻结并全量回归，
未用生成检查通过代替编译运行通过。

调度诊断另存 `ptmp/grhsim-speed-20261027/xs-round-probe/`：
基于冻结 `xs-windows` 只替换 eval、七个 active dispatcher 和
`sn_4296` 所在的九个 TU，沿用相同 header/PCH、PERF=0、
SN_TIMING=0 和类布局；用独立全局计数与 RDTSCP，不修改正式候选。
10k/20k 诊断都以单仿真线程 CPU2 运行，NEMU 无错误、对应检查点
与冻结日志一致，诊断 `result.json` 为 passed。

| 前缀 | eval | 总 round | 一轮 eval | 两轮 eval | 三轮 eval | R1 nonsink 调用 | R2 nonsink 调用 | R3 nonsink 调用 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10k | 20102 | 40254 | 52 | 19948 | 102 | 8038744 | 31248273 | 103 |
| 20k | 40102 | 80354 | 52 | 39848 | 202 | 15998744 | 109036467 | 203 |

第二轮占大量 nonsink 调用，但首轮 RDTSCP 总 ticks 仍更高，不能
用调用次数直接替代耗时；writer/commit 也在第一轮执行。20k 中
`sn_4296` 执行 6058 次，输出变化 4088 次，`s1502357` 的 commit
前后值变化 4088 轮。pPublish 后该 SN 从 inactive 到 active 共
6057 次，此计数包含所有来源，不能归因于单一 state。该 SN 同时
读取完整数组，任何 cell 改变后仍需唤醒；精准 indexed wake 无法
跳过它的完整快照处理，因此本批叶装配与后续精准唤醒是不同成本点。

这些运行含计数、phase 计时和指定 state 的写前后比较，会扰动
运行时间，不作为正式性能成绩，也没有取得全程线程/affinity
观测证据。正式候选仍关闭这些诊断。
20k 的六 phase 内部计时占比为 pGeneral **82.6102%**、pLargeSink
约 **8.65%**、pPublish 约 **7.97%**、pEvent 约 **0.74%**。这里
分母为六 phase ticks 总和；按 round 计的首轮 **63.89%**、第二轮
**36.08%** 使用另一分母，后者包含探针的写前后快照比较等开销。
诊断 binary/header/PCH/九个 TU 和对象、原 harness 对象及日志共
82 项产物已分别绑定哈希；构建前 manifest 与后补 verify 目标的
Makefile 版本差异也在诊断结果 limitations 中明示。

本批修正版完整 `test_grhsim_cpu_st_cpp`（含生成 C++ 编译运行的
88 个样例）及 transform/virtual-partition/sink-schedule 回归均以
exit 0 完成。冻结 source SHA 为
`b288ee975f8df09067f2afab907268d24712cba213744d40837a09ff5d0218e8`，
库 SHA 为 `679801bfcfa38e20c20c3182d42eda646e97ba9f70acdf6b4dabed5a97113501`；
证据保存在 `ptmp/grhsim-speed-20261027/leaves-regression.json`。
香山新模型生成耗时 207.30s，2468 个 C++ TU；使用独立目录
`xs-leaves`，fresh PCH、全部 TU 重新编译，不复用旧对象。
实际 `sn_4296` 已改为直接复制 672 叶并重复写入 32×3 叶，
保留原 selected/whole snapshot、结果比较及 activation。
2026-10-27 的正式香山 CoreMark 100k 已完成，结果位于
`ptmp/grhsim-speed-20261027/xs-leaves/result.json`，`passed=true`；
运行、汇总及所有产物 SHA 校验均 exit 0。生成物、双 generation
identity、回归通过库、fresh PCH、全部 headers、模型 archive、
最终 executable 与输入均绑定校验。实际编译日志确认 2468 个 TU
各一次、PCH 一次、40 个 harness 源及一次 link，关闭 PGO、
执行计数、SN timing、波形、commit trace 和运行时 profile。
模型编译链接耗时 916.48s；后置日志解析曾将 18 条与诊断混行的
bash trace 重复计数，修正为只统计真实执行 trace 后全部门禁通过，
原编译日志与 binary 未改，也未重新构建。

| 版本 / 证据目录 | Host time | 比较范围 |
| --- | ---: | --- |
| 本批 `xs-leaves` | 654.182s | 当前版本重新生成、全量编译后的一次正式运行 |
| 相邻候选 `xs-windows` | 643.369s | 历史正式记录；本批慢 10.813s / 1.681% |
| 同版复测 `xs-windows-repeat1` | 647.746s | 历史复测记录；本批慢 6.436s / 0.994% |
| 原 named sink boundary baseline | 1009.903s | 历史记录；本批耗时减少 35.223% |
| plain SV Verilator | 182.793s | 历史归档，本次未重跑；本批耗时为其 3.579 倍 |

本次 wall 654.25s、峰值 RSS 202896KiB，吞吐约 152.86 host
cycles/s。CPU2 单线程运行，启动后一份 /proc 样本确认 Threads=1
且 affinity=[2]，observer 在 CPU8；CPU18 全运行区间 busy
6/65413 jiffies（0.00917%），不能将单次线程样本写成全程监控。
NEMU difftest 无错误；10k 至 100k 十个检查点及终点与
`xs-windows`、原 baseline、历史 plain SV Verilator 一致：
seed=0、guest cycles=100001、instr=238535、cycleCnt=99996、
final PC=0x80000cde。plain 的 provenance 来自归档构建 metadata
和 binary hash，本次没有重新哈希其当年编译的原始 RTL 内容。
这只验证 100k 前缀，既非完整 CoreMark PASS，也非全波形 /
每输出等价证明。

该次运行未观察到叶装配的净性能收益；局部热点的宽中间值消除
不能直接推断整机加速。相邻版本对照各只有一次正式测量，历史
同版也存在波动，不据此作统计显著回退结论。整体性能目标仍未
达到；当前源码保留待后续分析，未提交。

### 7.11 按实际读取范围过滤大型状态唤醒

`on-write` 原先在大型数组任一位置写入后唤醒其全部 nonsink 读者。
独立旁路探针以冻结 `xs-leaves` 为输入，记录最近实际读取的 leaf
范围与本轮实际写入位置的交集；原计算和 activation 均未改变。
`ptmp/grhsim-speed-20261027/xs-index-probe/result20000.json` 为
passed，结果 SHA 校验通过，20k 前缀 NEMU、10k/20k 检查点和
终点均一致；运行时采样为 CPU2 单线程，CPU18 busy 0.00959%。

| Bank | 原发布请求 | 命中读取范围 | 可过滤请求 | 可过滤 inactive→active 请求 |
| --- | ---: | ---: | ---: | ---: |
| `s3021820`（170 owners） | 3408670 | 32 | 3408638（99.9991%） | 320206 / 320206 |
| `s3598796`（172 owners） | 3448772 | 3260319 | 188453（5.46435%） | 28468 / 38562 |

这是原调度下的局部预测，优化后 coalescing 和执行次数可能改变，
不能把请求过滤比例或含探针时间写成整机收益。后一个 bank 在
20k 内有 19751594 次 leaf 触碰，其中 19751563 次新旧值相同，
触碰范围仍然很广；触碰语义没有擅自缩成数值变化语义。

生产候选只优化 large、shaped、`on-write` register bank 的纯
nonsink indexed owners。whole read、包含 External effect 的
owner 和未分类 fanout 保留全唤醒；`on-change` 沿用原逻辑。
每个 read 在原执行位置记录 flattened leaf 起点，partial row 的
count 为未索引维度乘积。有效性按原 unsigned index 全宽判断，
通过后才缩窄为地址；每次无效读取覆盖旧订阅为 N。init 设 N+1
以保守匹配首次写，held sample 的订阅跨 eval/round 保持。

所有合法提交分支累计 touched bitmap：同值、零 mask、掩码写及
A/B/A 写回原值都触碰，非法地址不触碰；whole/fill 标记全范围。
Publish 按订阅范围与 touched 的交集激活 owner，最后统一清 bitmap。
不改 writer 顺序、采样位置、NBA 快照、pending、requiresRound
或 stateRound，保留派生时钟所需固定点轮次。

候选实现和专项 fixture 已落盘；本阶段构建先修复 operationEffect
命名空间及小函数预算下 helper 参数/return 的结构化表达。测试
修正为比较实际执行 supernode，并扩到 8×12 叶，partial row5
覆盖索引 60..71，包含 bit63/64 两侧读写。temporal 中 selective
read 与 peer whole read 共享 owner，peer 写仍会执行整个 owner，
计数 oracle 必须按这种合并激活判断；额外补齐八个 temporal
组合的生成程序 Make 注册，避免只有生成检查而没有执行覆盖。

首轮完整回归在执行日志长时间未推进后被中止，未作为通过证据；
独立有界重跑已有 95 个生成 driver 均 exit0。修正版重新 snapshot
并完整回归；在全部生成 C++ 编译运行和 sink schedule 通过前，
不复用 `xs-leaves` 的通过身份，也不报告新候选性能成绩。

修正版完整回归现已通过：生成 C++ 编译运行（含八个 temporal
组合）exit0，transform / virtual-partition / sink-schedule 三项
均通过。temporal 驱动补充显式 `<cassert>`；此前缺少头文件的
失败日志另存，不用失败尝试代替通过记录。长时间静默来自
packed-array-constants 测试 driver 的编译，生成程序不存在
已确认的卡死。通过身份为 source
`2aa33f9c3650eb1168d81bdced0f117b493b7426655a6774fb163d82e471112b`，
library `610308b7d9f50a231a542af68baffb09dc9885a75e62b3befdcdde27b637e99b`，
fixture `35637b8a4f80d57af4d71ea1fab16a90f7ba1645258ea8c5c3da96245f1935f6`；
记录在 `ptmp/grhsim-speed-20261027/indexed-regression.json`。
正式候选使用新 `xs-indexed` 目录和 `python-indexed` binding，
重新生成、fresh PCH、全量模型 TU 和 harness 编译后再测 100k。

2026-10-27 正式香山 CoreMark 100k 已完成，结果保存于
`ptmp/grhsim-speed-20261027/xs-indexed/result.json`，passed=true。
运行、汇总和独立终审全部通过：运行前后 20 项输入、57 项汇总
产物及 result SHA 均一致；历史 baseline 和 plain 归档校验通过。
双 generation identity 对应上述回归库，生成文件集 SHA 为
`6a8794235b6be2a7c2fdaa2faeccaa40ea0730b35a8d4fd25d45e4a86ea67869`。
生成耗时 211.00s，完整编译链接 948.14s；实际命令核对为
2544 个模型 TU 各编译一次、fresh PCH 一次、40 个 harness 源和
一次 link，零对象复用。PGO、执行计数、SN timing、波形、
commit trace 和运行时 profile 均关闭，仿真线程关闭并行。

| 版本 / 证据目录 | Host time | 本批对照 |
| --- | ---: | --- |
| 本批 `xs-indexed` | 681.820s | 一次新生成、全量编译后的正式运行 |
| 前一候选 `xs-leaves` | 654.182s | 本批慢 27.638s / 4.225% |
| 历史 `xs-windows` | 643.369s | 本批慢 38.451s / 5.977% |
| 历史同版 `xs-windows-repeat1` | 647.746s | 本批慢 5.260% |
| 原 named sink boundary baseline | 1009.903s | 本批耗时减少 32.487% |
| 历史 plain SV Verilator | 182.793s | 本批耗时为其 3.730 倍；本次未重跑 plain |

本次 wall 681.87s、峰值 RSS 208436KiB、吞吐 146.6663 host
cycles/s；相较 `xs-leaves` RSS 增加 5540KiB。运行固定 CPU2，
启动后的一份 /proc 样本为 Threads=1、affinity=[2]，observer
在 CPU8；CPU18 全运行区间 busy 4/68172 jiffies（0.00587%）。
这是单次线程样本，低 sibling 负载也不证明完全没有外部干扰。

NEMU difftest 启用且无错误，10k..100k 十个检查点和终点与
`xs-leaves`、baseline、历史 plain SV Verilator 逐字段相同：
seed=0、guest cycles=100001、instr=238535、cycleCnt=99996、
final PC=0x80000cde。plain 仍是归档 build metadata 和 binary
hash 的来源证明，本次没有重新生成 plain SV 或重跑 Verilator。
此结果仅覆盖 100k 前缀与指定检查点，不是完整 CoreMark PASS、
逐输出或全波形等价证明。

本次精准 indexed wake 未取得净性能收益，单次实测比前一候选
慢 4.225%；原调度下可过滤请求的比例不能代表整机收益。
不据单次测量声称统计显著回退，也不在本轮继续定位开销或
追加优化。按用户要求，本次测量完成并更新文档后停止优化；
随后按用户要求将当前实现、回归用例和测量文档归档提交，保留
全部证据，不再启动额外测速。前述各阶段“未提交”均指当时状态。
