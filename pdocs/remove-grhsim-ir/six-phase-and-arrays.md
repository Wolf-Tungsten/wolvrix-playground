# 六段调度与数组契约

移除的是独立 IR；本文件规定迁移后保留的运行时行为。现行实现见 [CPU emitter](../../wolvrix/lib/emit/grhsim/cpu-st-cpp.cpp)、[状态/数组契约](../../wolvrix/docs/grh/grh-ir.md) 和 [仿真方言](../../wolvrix/docs/grh/grhsim-dialect.md)。[六段数据流记录](../simulation-model-refactor/grhsim-six-phase-data-flow.md)与 R0 冻结源码保留历史语义证据；现行规范及验证索引见 [能力映射](capability-evidence.md)。

## 1. 固定六段执行协议

生成模型保持现有 `init()`、端口、`eval()`、DPI/FST 和 profile 对外接口。运行时协议固定为：

```text
eval():
    reset_per_eval_sampling_flags()
    P_input()
    converged = false
    for round in 1..MAX_ROUND:
        P_event()
        P_general()
        P_large_sink()
        if P_publish():
            converged = true
            break
    if not converged:
        fail("CPU model did not converge")
    P_output()
    optional_waveform_record_at_eval_boundary()
```

当前 MAX_ROUND 为 100000；迁移期保持默认值和不收敛错误，不能达到上限后继续输出。Input/Output 在一次 eval 各执行一次，中间四段按 round 运行。该协议表达现有 GrhSIM 模型的行为，不扩大为完整 SystemVerilog 时间轮仿真器。

| 阶段 | 读取与执行 | 写入、激活与可见性 |
| --- | --- | --- |
| `P_input` | 固定本次 eval 的外部输入，与 inputStore 比较；数组逐元素比较/复制 | 更新 inputStore，变化时通过 inputFanout 激活 General nonSink；event-only 输入由事件阶段处理 |
| `P_event` | 运行事件锥，清除本 round 的 eventAct，执行 edge-detect | 读取并更新跨 round 的 prevEvent；脉冲激活 nonSink/event 消费者；timeslot 触发位跨 round 粘滞 |
| `P_general` | 按计划执行 nonSink 虚拟分区与 smallSink，分区内包含相应的计算/读口/调用；grhsim 写端口消费本轮 pulse，状态读取使用本 round 的可见快照 | 发布 nonSink boundary；采样 small/large 写参数；small 写入 next，不直接改变 current |
| `P_large_sink` | 消费 General 已采样的 enable/index/data/mask 和事件条件 | 按覆盖顺序原地提交大型状态，检测真实变化并激活下一 round 读者；不能重新求值数据锥 |
| `P_publish` | 合并下一 round 激活、提交 small next | next→current，清理 next 激活并判定固定点；large 状态不整块复制 |
| `P_output` | 收敛后计算最终输出、运行允许的时隙任务 | 消费/清理 timeslot 触发；输出锥全部求值后才提交 output-end 历史写入 |

固定六段协议由 emitter 实现，具体 sink 求值/采样/提交顺序来自 grhsim-partition-sink 发布的 SinkSchedule。计算归属来自完成拆分后的 GRH 属性，布局与激活表由 emitter 内部建立；不设置独立 CPU planning pass 或另一份 op→role/通用 task 图。SinkSchedule 只标注 sink 的有序 run 和必要依赖；Output 的历史读取/末尾写回由图中的 output-end 语义及本协议保证。

### 1.1 状态策略与旧值

grhsim-split-nonsink-and-sink 按现有 `ceil(totalWidth/8) >= memMinBytes` 规则选择 large-sink / LargeInPlace，默认阈值 64 bytes；其他状态选择 small-sink / SmallNextBuffer。分类保存在 GRH 属性，emitter 据此分配存储。按总宽选择，与 shape 解耦，支持小数组和大标量；物理 padding 不改变阈值。

- small 的 current/next 在 init 时得到相同初值；未命中写口的 next 保持原值。General 的读只看 current，写只更新 next；publish 后才对下一 round 可见。
- large 在 General 完成所有必要读取和写参数采样后才原地更新。索引、使能、data、mask 都属于本次 writer 的快照，不能在写入循环中从已变化的 state 重新读取。
- output-end 历史读取看上一次输出求值留下的历史；本次输出阶段的全部读完成后才写回，不受 small/large 分类影响。
- 状态策略只改变实现方式。用 fixture 强制改变阈值后，两种策略对受支持模型的最终输出、调用和状态投影必须等价。

例：`q<=d; r<=q` 同沿触发时，r 必须取得本 round 的旧 q；q 是否为数组、writer 是否跨 chunk/TU、q 使用 small 还是 large 存储，都不能改变这一结果。

### 1.2 激活与收敛

保留三张独立 fanout：input→读者、nonSink boundary value→读者、state commit→读者。事件激活和 timeslot 触发另表维护。

nonSink value 改变时，目标执行位置大于当前位置可进入 current 激活；目标位置小于等于当前位置进入 next。small/large 状态提交的读者激活进入 next。smallSinkEvent 在扫描点直接检查自己的 event 签名，smallSinkEscape 每 round 检查电平条件；不能把它们统统交给 nonSink bitmap。

fanout 沿同一 Graph 的 use-def 和虚拟分区边界追到读者。动态读口可与地址/数据计算同属一个分区，在地址 producer 就绪后执行；地址变化和状态提交都必须正确触发其读者，不能只在 init 取值。缓存遵守所属分区的采样范围，不因分区建立而复制整张状态数组。

固定点判断依赖 General 已消费 current 工作、next 无新工作及全部必要提交完成。首次 eval/init 重新激活、Output dirty、event-only 输入也必须覆盖；不能以“没有状态写入”或“输入没变”替代该条件。重规划 ordinal 后重建全部 ordinal 相关表。

### 1.3 多写、事件与副作用

同一状态的全部 grhsim whole/indexed/masked/fill writer 使用 grh-to-grhsim 从原 GRH 写口顺序固定的 writerOrder。最终应用顺序从低到高，后声明覆盖先声明的重叠位；不同事件域也遵守此规则。事件 guard 聚类、enable bitmap 跳过和读者去重都不能重排最终覆盖。

edge-detect 的历史跨 round，eventAct 是 round 脉冲，timeslot flag 是 eval 内粘滞位。相同事件连续多个求稳 round 不得重复触发；门控时钟在后续 round 变化时仍可检测新沿。首次历史初始化沿用当前策略，并以首 eval、复位释放和重 init 用例固定。

时钟写入由 grhsim 独立写端口的第一个 operand fire 驱动，fire 显式依赖 edge-detect 的返回值；多个检测器可 OR 合成 fire。基础 grh 的 write 系列仍接受原始事件和 eventEdge，grh-to-grhsim 用不同 op kind 替换它们，不能把其事件位置改作 pulse。P_large_sink 消费已采样的 fire/enable/data/index/mask，不重新检测 clock。

DPI、系统任务和随机函数保留现有 guard、过程种类、采样身份、结果保持与调用次数。事件/输出锥只复制允许复制的计算；随机函数现有每 eval 采样缓存、带返回值调用的触发与零结果调用的存活都要测试。`$monitor/$strobe` 的粘滞触发和 output-end 历史提交不能按普通组合计算折叠。

旧调用次数以实际冻结日志为准。2026-10-25 用户明确采用 [单个原调用与原图独立调用顺序](20261025-single-call-decision.md)，图中保留 effectPolicy；去除 Output 重复 DPI 及独立调用旧调度排序的精确差异单列为已批准。其他次数/触发/参数/结果差异仍须解决，不能以最终输出相同替代六段/effect 检查。冻结日志和原始严格比较保留，详见 [逐次观测](baseline-and-capabilities.md#r4r5-的旧-dpi-行为差异)。

### 1.4 六段与虚拟分区

grh-to-grhsim 之后是无分区的单图，edge-detect、写口和系统任务/函数/DPI 已转换；随后可全图 simplify，包括合并等价检测器。grhsim-split-event-and-output 才首次提取 Event/Output，grhsim-split-nonsink-and-sink 再拆 General 的 nonsink / small-sink / large-sink，最后依次进行活动度切图和 sink 分区/顺序标注。

large-sink 区域仍有 P_general 的参数求值和 P_large_sink 的提交两个职责；不能把区域名直接当成所有成员的执行位置。Output 的历史最后提交，Input/Publish 是固定协议，无需建空分区。分区后的 simplify 只比较完整叶 owner，没有 role 分支；采样/effect 规则继续有效。属性和提取示例见 [虚拟分区](virtual-partitions.md)。

六段是运行协议，虚拟分区是 transform 逐步建立的计算归属，chunk 是 emit 中的函数行数控制。这三者分别遵守上述契约：chunk 不新增分区，分区不替代参数快照，SinkSchedule 只在 partition-sink 首次发布，六段的具体生成由 emit/grhsim/cpu-st-cpp.cpp 承担。

## 2. 数组类型、位序与 GRH 操作

### 2.1 几何

统一使用总宽 W 和外维在前的 shape `[d0,...,dn-1]`，叶宽 E=`W/∏shape`。规范索引从零开始，行主序：

```text
linearRow(i0,...,in-1) = (...(i0*d1+i1)*d2+...)*dn-1+in-1
bitOffset = linearRow * E
```

索引前 k 维产生剩余 shape `shape[k:]`，总宽为 `E*∏shape[k:]`。空 shape 的乘积为 1；维度乘积、偏移和字节大小都做溢出检查。

例：叶宽 9、shape `[4,8]` 的值总宽 288；索引第一维 i 后，总宽 72、shape `[8]`，而非无 shape 的 72 位标量。`[1]` 与标量不同。`concat(a,b)` 的 a 在高位；`arrayCreate(a,b)` 的 a 是低地址元素，位布局不可混用。

### 2.2 操作契约

基础 grh 操作保持原契约。下表的 `E...` 仅表示由既有 eventEdge 属性描述的原始事件 operands，`k` 为索引个数；这里没有 pulse 模式。目标状态通过 GRH 声明引用关联，数据 operands 不混入声明 ID。mask 始终是位掩码。

| GRH 操作 | operands → results | 必须保留的规则 |
| --- | --- | --- |
| `kArrayCreate` | `e0,...,eN-1 → a` | N≥1，元素完整类型相同；result 宽 N×元素总宽，shape `[N]+元素shape`，`a[i]=ei` |
| `kSliceArray` | `base,i0,...,ik-1 → r` | 1≤k≤rank；结果继承剩余 shape、signedness/domain；不能只校验总宽 |
| `kRegisterReadPort` | `[] → r` | 整体读取当前状态，保留全 shape |
| `kRegisterReadArrayPort` | `i0,...,ik-1 → r` | 读取元素或剩余维子数组；快照由阶段决定 |
| `kRegisterWritePort` | `en,data,E... → []` | 整体更新，原 guard、边沿触发和多写优先级保持 |
| `kRegisterWriteMaskPort` | `en,data,mask,E... → []` | mask 宽为状态总宽，仅命中位更新 |
| `kRegisterWriteArrayPort` | `en,i0,...,ik-1,data,E... → []` | k<rank 时写入完整子数组，不限单行 |
| `kRegisterWriteArrayMaskPort` | `en,i0,...,ik-1,data,mask,E... → []` | mask 宽为被寻址区域总宽 |
| `kRegisterFillPort` | `en,data,E... → []` | 保留现有元素广播和合法 packed-fill 形式；两者由校验过的宽度/类型规则区分 |
| `kLatchWritePort` | `en,data,mask → []` | 原有电平敏感更新，不增加 pulse 模式或 output-end 提交模式 |
| `kAssign` | `source → result` | 输入输出总位宽必须一致；比较完整类型（含 shape）判断同型传递或合法转换，shape/signedness 重解释保持位图；异型 assign 不能无条件消除 |
| concat/replicate/static、dynamic slice | 原 GRH 契约 | 支持真实扁平消费者；保形优化需证明对齐、位序、域与快照，不改变一般位运算语义 |

grh-to-grhsim 将上面的写操作替换为下列 **grhsim 方言写端口**；这些操作共享状态声明和数据几何规则，使用独立 kind/descriptor/verifier：

| grhsim 操作 | operands → results | 执行与几何 |
| --- | --- | --- |
| `grhsim.write` | `fire,en,data → []` | 整体写，fire 与 en 为真时生效，data 总宽等于目标 |
| `grhsim.writeMask` | `fire,en,data,mask → []` | 整体位掩码写，data/mask 总宽等于目标 |
| `grhsim.writeArray` | `fire,en,i0,...,ik-1,data → []` | 1≤k≤rank，写入元素或剩余维子数组 |
| `grhsim.writeArrayMask` | `fire,en,i0,...,ik-1,data,mask → []` | mask 宽等于被寻址区域总宽 |
| `grhsim.fill` | `fire,en,data → []` | 按原契约完成叶元素广播或合法 packed fill |
| `grhsim.latchWrite` | `en,data,mask → []` | 独立电平敏感写，无 fire，不承担 Output 历史提交 |
| `grhsim.history-write` | `data → []` | 完整同型历史值；引用 output-end 历史声明，在全部 Output 观测后一起提交 |

fire 是无 shape 的 1-bit unsigned TwoState Logic，由 edge-detect 的返回值或其合法 OR/等价简化产生，writer 消费当前 round 的脉冲而不再检测边沿。en 是无 shape 的 1-bit Logic，沿用原写使能的域及条件判定规则，不因写口分离增加隐式四态投影。目标使用 typed 声明引用，索引及 data/mask 的完整类型规则与对应原访问形态一致；packed 兼容视图通过等宽 assign 显式表达。每个新写端口保存原 writerOrder，无原始 eventEdge 或触发模式属性。

当前 GRH 的 latch shape/类型限制继续由新方言对应操作继承，不随此次分离扩张。small/large 分类由 grhsim-split-nonsink-and-sink 写入 GRH 属性，partition-sink 据此标注采样/提交顺序，emitter 再分配物理存储；不能用状态 shape 替代分类。

状态端口中现有合法的“同总宽、不同 shape 的 packed 视图”兼容性单独保留：在需要规范形状时用输入/输出类型不同的等宽 `assign` 表达；不能把补齐 `sliceArray` 强校验扩大成对旧状态边界的无说明拒绝。`assignAs` 随统一契约删除。

数组索引、越界和未知位的行为在 R0 逐类冻结：复用当前 GRH/CPU 实现的有效域及截断/钳位路径，不借迁移新增 wrap/zero/报错策略。特化只在范围已证明时使用；无法证明时走同一基线路径，并测试范围边界、过宽/有符号索引。原有明确拒绝的形态继续明确拒绝。

位序示例：

```text
arrayCreate(8'h11,8'h22) -> width=16, shape=[2], packed bits=16'h2211
sliceArray(result,0)    -> 8'h11
arrayCreate(x[3],y[3])  -> shape=[2,3]，第一块来自 x
assign(u32, u8[4])      -> 总宽32，低8位成为第0个元素
assign(u8[4], u16[2])   -> 总宽32，按同一位序重新分组
grhsim.writeArray @a (pulse,en,i,data[8]) -> a[i][0..7] 更新为 data[0..7]
```

## 3. C++ 数组生成与访问配方

### 3.1 存储与按 use 选择表示

两态数组按原多维形状映射为嵌套 `std::array`；每个叶元素独立选择宿主标量/宽整数。总逻辑位宽与宿主 padding 分离，例如 11-bit 元素可以占 uint16，不能把数组对象的字节串当 packed 逻辑位串。

emitter 私有 `CpuStEmitContext.accesses` 以 `(consumer OperationId, operandIndex)` 为键，引用唯一 GRH ValueId；执行上下文结合 consumer 归属及 SinkSchedule 的采样/提交位置确定。它在一次 emit 中建立，配合布局、别名和 chunk 寿命求解，不另设访问规划 pass/slot，至少支持以下方案：

| 方案 | 含义与边界 |
| --- | --- |
| `Elements` | 引用稳定的 state/input/boundary/local/frame 元素序列，记录快照和寿命 |
| `Construct / Slice / Repeat / Concat` | 读取已有 GRH value 的有界元素区间；只描述访问，不替代算子语义或构建新 SSA |
| `Regroup` | 在等位图、对齐和已证明范围内重组元素；不能跨过可变 boundary 重新追溯 producer |
| `Materialized` | 由调用方拥有的 local/frame 数组，跨 helper/多消费者时只物化一次 |
| `PackedOnce` | 真实扁平消费者或无法证明的访问，按原 guard/采样时刻打包一次，后续只提取 |

首版迁移可先使用正确的 Elements/Materialized/PackedOnce 覆盖当前能力；S9 再增加访问消除规则。recipe 引用必须无环、有界、完整记录依赖，不承载任意计算操作。

同一 value 可同时有数组与扁平消费者：数组分支逐元素使用，只有需要整数的分支打包。`arrayCreate` 直接写调用方的 local/frame 数组；不能先构造总宽 `_BitInt` 再拆回元素，也不能返回大型 `std::array` 临时对象。

### 3.2 快照、别名、guard 与分块

每次写入明确其 trigger/enable、索引、源 data/mask 和使用阶段。源与目标可能重叠时，第一次写之前保存所需源快照；证明不别名且源稳定时才借用引用。部分重叠不能默认正向循环安全。

packed fallback 的位置必须是：

```text
原 writer 的 event/enable guard 内：
    source_snapshot = 取得本次写所需的旧值
    packed = pack_once(source_snapshot)
    for each destination row:
        write_from_extract(packed,row)
```

不能把整表 pack 嵌进逐行表达式，也不能跨不同 writer/enable/采样时刻提取公共 pack。mask 与 data 独立记录访问方案，非零、逐行不同数据必须覆盖；常量零 fill 不能替代一般路径验收。

边界 value 必须读取已发布的 boundary 快照，不能通过追溯其他虚拟分区的 producer 绕过采样。虚拟分区之间仍使用同图 GRH value，无隐式跨模块端口。emitter 内部协同分析访问/view root/别名与局部寿命，再按函数预算拆 chunk；跨 chunk 的局部值进入 chunkFrame，跨虚拟分区/采样阶段的值仍进入对应语义 boundary/快照，二者不可混淆。

保持 legacy 的指针/调用方输出缓冲方式。两态 >64-bit 宽运算继续使用已测量的原生 `_BitInt` 路径；剩余四态、task/FST helper 继续遵守原缓冲/别名策略。生成模型沿用现有工具链对宽类型的支持，不在本次重构更换宽值 ABI。

### 3.3 数组读者激活

LargeSink 写入按真实变化通知读者。完整常量索引可精确匹配线性行/区间；动态/部分索引、整体读和无法证明的视图保守激活，不能漏读者。优化读者范围必须同时覆盖 mask、子数组、多写最终值和同轮重叠覆盖。

读者范围从单图原读口及跨虚拟分区的 use-def 推导，分区本身不能把精确索引读降成全表读者。索引读与 sliceArray 保持各自基线越界路径，不为分区而互换。

### 3.4 所有生成函数的统一 chunk

chunk 是 emit/grhsim/cpu-st-cpp.cpp 的发射行为，与活动度分区和 sink 分区独立。max-function-lines 对所有生成函数应用同一计数/拆分机制，覆盖 init、eval、六段调度、Event/Output、nonSink、small/large sink、DPI/任务、trace/profile 和生成 helper；不是仅对 General 的特殊优化。

按最终函数定义行数计入 guard、函数支架和 chunk 调用，超限时拆分，并继续约束 dispatcher。chunkFrame 保存跨 chunk 活跃的局部值、必要控制状态，以及为满足声明行数预算而 spill 的不可分语句私有局部值，按指针/引用传递并保持原初值/寿命；它不承载虚拟分区或状态采样。数组采用调用方持有的缓冲，不为拆块引入大型返回值复制。循环、early return、写入覆盖、一次采样/调用、事件历史和 output-end 提交顺序均须保持。

改变该行数上限只重新 emit，不改 GRH 分区属性、不重建 SinkSchedule。验收除执行比较外还要扫描所有生成函数的实际行数；不能以“已有虚拟分区”或“已拆 TU”替代函数预算达标。

## 4. 数组初始化与支持边界

InitSpec 是绑定 GRH 声明的有序列表，每步包含 kind 与 typed 参数：

| 步骤 | 参数与含义 |
| --- | --- |
| `const` | `value` 为整个状态的逻辑字面量；数组按总宽与上述位序拆分 |
| `fill` | `value` 为叶元素值，`start/count` 为非负线性行范围；缺省 start=0、count=剩余行数，count=0 不写 |
| `readmem` | `file, format=hex|bin, start, count`；复用现有发射期解析，`@address` 为绝对行号，重复地址后者覆盖 |
| `random` | 保留当前支持类型及 seed/采样顺序；显式 seed 使用局部流，未指定 seed 使用原共享流 |

步骤按序覆盖，缺失或最终未覆盖的初始化报错；生成 arena 的清零不能代替语义初值。readmem 的相对路径基于当前发射工作目录，文件摘要写入构建记录；静态数据进入生成模型，运行期不重新读取文件。不得在重载 checkpoint 时改变路径解释而静默换数据。

保留当前 SplitMix64、无 seed 初值 `0x6a09e667f3bcc909`、init 重置、宽值低字到高字采样及尾字截断规则。现有 fill/random 的支持组合以 R0 清单和测试为准，不把表中步骤名推断为所有类型组合都已支持。

四态 aggregate 在 GRH 中合法，现有 CPU emitter 不支持时继续在输出文件前明确拒绝；real/string state 等已有拒绝也要保留。四态 scalar、DPI 类型等以当前真实支持矩阵逐项迁移，不声称本次移除扩展了支持范围。

## 5. 必须进入执行测试的组合

六段用例至少覆盖连续多 round、门控时钟/异步复位、同沿读旧值、不同事件 writer、output-end 历史、无变化 eval、重 init 与不收敛错误。grh-to-grhsim 写口转换测试验证基础 grh op 契约未变、单/多 pulse 接线与 writer 顺序保持、原 clock 接 fire 被拒绝，并验证每个原 writer 仅替换为一个生效的新 writer。

数组用例至少覆盖 rank 1/2/3、`[1]`、整体/全 rank/部分索引、mixed scalar/array/packed 消费、同总宽不同 shape、signed/非字节叶宽/>64-bit 叶宽、mask/fill/readmem、动态索引、源目标别名、跨阶段/虚拟边界和强制小函数行数上限/TU。增加地址/read/data 同分区与跨分区、同执行根下 clone 不合回、地址变化但状态不变、写后地址不变的激活检查。每项都比较生成模型执行结果，不能只比 IR/C++ 文本。

另外分别覆盖分区前等价 edge-detect 合并、分区后跨 owner 的 clone 不合回；以 tiny max-function-lines 强制 Event/Output/init/trace 等全部类型的函数拆块，并证明 chunkFrame 不改变快照、返回值和调用次数。
