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

nonsink 负责共享计算、状态读取和普通效果调用，并发布
`nonSinkBoundaryStore`。边界变化激活后继；按顺序扫描时，尚未访问的后继
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

语义存储保持直接命名字段，典型成员包括：

| Store | 内容 |
| --- | --- |
| `inputStore` | 本 eval 输入快照 |
| `smallSinkStore` | 小状态 current |
| `smallSinkStoreNext` | 小状态 next，与 current 复用同一 store type |
| `largeSinkStore` | 大状态 current |
| `nonSinkBoundaryStore` | nonsink / 跨分区结果及 held sample |
| `prevEventStore`、`eventActStore` | detector 前值和本轮 fire |
| `largeSinkEnableBoundaryStore`、`largeSinkPayloadBoundaryStore` | 大 writer 有效位和采样 payload |
| `timeslotTriggerStore`、`sampledStore`、`onceStore` | 时隙 sticky、采样和 initial-once 控制 |
| `largeBeforeStore` 等 | on-change 比较所需的写前信息 |

这些 named stores 无论多大都保留语义字段，不能因字段多就改写为不透明的
`cells_*` 数组。enable bitmap 本身可以有 `words` 数组，这是明确的数据结构。

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

描述的工作树基线：root `d94af83`、wolvrix `45772eb`；整理日期 2026-10-27。
