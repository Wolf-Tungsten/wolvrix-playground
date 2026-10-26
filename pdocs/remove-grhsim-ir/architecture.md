# 统一 GRH 与 scratchpad

本文规定按新 pass 顺序实施的目标结构。GrhSIM 形态仍使用 GRH 图基础设施，转换后先保留无分区大图。功能等价边界见 [六段调度与数组](six-phase-and-arrays.md)，迁移单元见 [实施计划](migration-and-validation.md)。

## 1. 一套实体与公共定义

保留 GRH 的 `Design / Graph / Operation / Value / GraphId / OperationId / ValueId`。仿真流程先展开原 RTL 层次，此后在同一个 top Graph 上归一化、复制和分区，不用 Graph/Instance 表达计算分区。复制维护原 GRH 的 define/use、符号与声明来源。CPU 表中的 state 引用就是 top 的 `kRegister / kLatch` 声明 `OperationId`，函数引用就是 `kDpicImport` 声明 ID，端口引用来自 GRH 的 ports。

不新增 `SimValue / SimOp / StateObject / InputObject / OutputObject` 及其 ID。端口列表、状态索引等可在 scratchpad 中建立便于访问的索引，索引中的条目必须引用原实体，不能成为可单独修改的另一份语义声明。

### 1.1 逻辑类型

统一的类型视图至少为：

```text
LogicalType = { kind: Logic|Real|String, width, isSigned, domain, shape[] }
domain = TwoState | FourState
```

- Logic 的 `width` 是总逻辑位宽，必须大于零；shape 维度为正数，乘积无溢出且整除 width，叶宽为 `width / product(shape)`。
- shape 空表示标量，`[1]` 仍是数组。相同总宽不能替代完整类型相等。
- Real/String 不接受 shape；无意义的 width/signed/domain 字段规范化为统一哨兵，不以宿主对象大小代替逻辑位宽。
- GRH 现有 width/signed/type/shape 访问器委托给同一类型规则；状态声明与 value 共用规则，不另建 GrhSIM 类型库。是否 intern 是存储选择，不改变定义。
- ingest 默认保持原四态含义。`grh-to-grhsim` 通过显式 `logic-domain=2state` 选项承接生产流程已有的 X/Z 投影策略，实际更新逻辑类型/常量及相应声明，而非只设置后端选项；不能由 emitter 静默投影。四态 IR/常量仍合法，CPU 支持范围沿用现状并显式拒绝不支持的组合。不为该操作另设无独立产物的 prepare。

### 1.2 Op 方言与描述符

GRH 图基础设施增加携带、识别和分派少量方言 op 的能力，使用统一 `OpDescriptor` 接口和静态注册，不先建设运行时插件框架。基础 `grh` 算子集与扩展方言分别持有各自的 kind 和描述符：

| 方言 | 内容 |
| --- | --- |
| `grh` | 现有计算、数组、状态声明/读写端口、层次、系统调用和 DPI；write 系列保留原始事件契约，不加入 bitSelect/prioritySelect |
| `grhsim` | 独立的脉冲驱动 write port 系列、edge-detect、归一化调用、bitSelect/prioritySelect 等仿真优化算子及受校验的执行属性 |
| `grhsim.cpu` | 现有 maskedOr 这类已验证有效的 CPU 特化计算；物理类型和布局放 scratchpad，不放 value 类型中 |

公共 `grh` op 仍只有一个 kind 和一个契约。描述符包含操作数/结果数量、类型与 shape 校验、参数 schema、对象读写/外部副作用、可否复制/折叠/CSE、支持的归一化形态。公共计算的常量求值和类型几何共用定义；方言扩展的校验、求值与特化规则由所属方言模块定义，通过同一描述符接口使用。GRH simplify 与 grhsim-simplify 分别实现自己的驱动和改写策略；后者在分区前全图工作，分区后限制在各完整叶分区，不改造现有 GRH simplify。复杂规则允许使用具名 callback，不追求用一张表编码全部规则。

现有 `core.compute.bitSelect / core.compute.prioritySelect` 分别迁为 `grhsim.bitSelect / grhsim.prioritySelect`，其 kind、契约和优化规则放在 grhsim 模块，不提升为基础 `grh` 算子。GRH 容器与序列化支持携带这些方言 op，不要求通用 GRH pass 或其他 emitter 自动支持它们；相应消费者通过描述符使用已实现的能力，或明确展开/拒绝。

赋值统一使用 `assign`，删除 `assignAs`，具体契约见 §1.3。bitSelect、prioritySelect、maskedOr 沿用现有完整运算语义与支持边界。历史 `core.compute.expr` 删除。已知但不支持的方言由 pass/emitter 报出名称和位置；禁止未知 op 默认当纯计算。

所有现有 `switch(OperationKind)`、字符串解析、store/load、verify、DCE、clone、flatten、used-bits 和 emit 都纳入 R1 审计。通用 transform 必须声明支持的形态；公共 `grh` 计算规则适用于图中对应的 op，`grhsim` 特化规则只处理所属方言。未适配的 RTL 状态重写必须明确拒绝 GrhSIM 形态。

### 1.3 统一赋值 assign

基础 `grh` 仅保留 `kAssign`：一个 source operand、一个 result，无需额外属性标记“同型”或“转换”。**输入输出总位宽必须一致**，由 verifier 强制检查；完整输入/输出类型包含 kind、width、signedness、domain 和 shape。

- 完整类型相同时，assign 传递同型值，可以按已有可观测性/来源约束消除。
- 完整类型不同时，由输入/输出类型判断所需的合法转换。Logic 的 shape/signedness 变化按同一逻辑位序重解释，位内容保持；数组 pack/unpack、重新分组不增加或减少位数。
- 类型种类/域的转换遵守对应的已定义规则；仅总宽相等不足以允许任意跨 kind/domain 的转换。Real/String 继续执行各自合法的传递规则，仿真两态投影仍由显式逻辑域策略决定。
- 位宽变化必须由显式截取、拼接/复制等已有 resize 路径表达；assign 不执行隐式截断、零扩展或符号扩展，位宽不等直接报错。

例：

```text
assign u32      -> u32          # 同型传递
assign u32      -> u8[4]        # 总宽均为32，重解释为四个低地址在前的8位元素
assign u8[4]    -> u16[2]       # 总宽均为32，按原位序重新分组
assign u32      -> s32          # 总宽均为32，位图不变，后续按有符号类型解释
assign u16      -> u32          # 非法：位宽不等，必须先显式扩展
```

类型边界仍由 assign 的 result 类型表达，value 创建时定型；不能为消除 assign 向 source 回填 shape。alias/DCE/CSE、constant-fold、used-bits、数组 view 追溯和 emitter 必须比较完整类型，不能再假定“看到 kAssign 就必为同型改名”。CSE 键包含完整 result 类型；折叠保留目标类型及位序，转换不能直接用异型 source 替换 result。

删除 `OperationKind::kAssignAs`、对应 kind 解析/序列化与 `assignKindFor` 的双 kind 选择接口。ingest、flatten、inline、组合环处理和其他 producer 统一创建 kAssign；`replaceAllUsesWithView` 等需要保持目标类型的接口改为插入等宽 kAssign，位宽不等拒绝。旧含 kAssignAs 的 checkpoint 明确提示重新生成，新格式仅保存 kAssign；基线仍由冻结旧实现读取。

## 2. grh-to-grhsim 的无分区结果

grh-to-grhsim 在已经展开的原 top Graph 上按需转换 op。转换覆盖 edge-detect、独立写口、system-task、system-function 和 DPI call，输出仍是平整无分区大图。它不复制公共 op/声明/value 到另一套实体，不提取 Event/Output，不设置 grhsim.partition（包括占位 general），也不发布调度或内存计划。

### 2.1 状态、类型与初始化

状态声明、状态读/索引读、端口和 DPI import 复用原 GRH。基础写口及调用的原始事件契约保持不变；本 pass 将需仿真契约的实例替换为 grhsim 方言操作，目标仍引用同一个声明。

状态目标、DPI import 等引用经所属 typed accessor 解析到原 GRH 实体。writerOrder 从合法原写口顺序固定，后声明覆盖先声明的重叠位；不以转换后物理 ID、扫描 ordinal 或分区顺序决定优先级。writer 合并/删除必须维护覆盖关系。

初值以绑定原 GRH 声明的有序 InitSpec 保存，复用并补齐 const/fill/readmem/random 的参数与覆盖顺序；不能将唯一初值放在 scratchpad。显式逻辑域转换实际更新完整类型、常量、声明及初值，无需另设 prepare。

### 2.2 edge-detect 与脉冲写口

grhsim.edge-detect(%event) -> %fire 接受无 shape 的 1-bit Logic，返回无 shape 的 1-bit unsigned TwoState Logic。静态参数包括 edge=posedge|negedge|both、符合输入域的 prevInit 以及采样/历史更新契约。其含义是每次 P_event round 计算一次沿并无条件更新历史；物理 prev/pulse 槽位稍后由 emitter 分配。**此语义不要求转换时已经存在 Event 分区。**

```text
grhsim.write          @state (%fire, %en, %data)
grhsim.writeMask      @state (%fire, %en, %data, %mask)
grhsim.writeArray     @state (%fire, %en, %i0..%ik-1, %data)
grhsim.writeArrayMask @state (%fire, %en, %i0..%ik-1, %data, %mask)
grhsim.fill           @state (%fire, %en, %data)
grhsim.latchWrite     @state (%en, %data, %mask)
```

时钟写口无结果，第一个 operand 为检测器结果或多个结果的合法 1-bit OR；enable 再决定是否写入，fire 不重复检测边沿。索引与 data/mask 的几何约束见 [数组契约](six-phase-and-arrays.md#22-操作契约)。电平写使用独立 latchWrite，不带 fire。原 grh write/call 不增加 TriggerSpec 或 pulse 模式。

```text
基础 grh：
  write @q(%en, %d, %clk) {eventEdge=[posedge]}
GrhSIM 形态，尚无 partition 属性：
  %fire = grhsim.edge-detect(%clk) {edge=posedge, prevInit=0}
  grhsim.write @q(%fire, %en, %d) {writerOrder=0}
```

输入相同、edge/prevInit/完整类型和采样更新契约相同的检测器可由分区前 grhsim-simplify 合并，所有 fire 使用者重接到一个结果，并共享一份历史。不同边沿、初值或采样范围不能合并；普通“纯 op CSE”规则不能替代这一专门规则。检测器没有人为阻止等价合并的独立 sample ID。

verifier 在 converted 阶段校验 fire 来源、完整类型、写口/调用转换完整性和历史初始化；在拆区域后再追加 owner/跨阶段可见性校验。不能要求无分区结果已经满足 Event 锥闭包。

### 2.3 系统任务、系统函数和 DPI

对应的 GrhSIM op 必须在 grh-to-grhsim 中建立：

| 原操作 | GrhSIM 操作 | 操作数、结果及引用 |
| --- | --- | --- |
| kSystemTask | grhsim.system-task | (%fire, %callCond, %args...)，无结果；保留任务名、procKind、hasTiming 等 |
| kSystemFunction | grhsim.system-function | (%args...) -> 原返回结果；保留函数名、effect、完整结果类型与采样契约 |
| kDpicCall | grhsim.dpi-call | (%fire, %callCond, %inArgs..., %inoutArgs...) -> 原 return/out/inout 结果；引用原 kDpicImport |

无事件 task/DPI 的 fire 为常量 1，有事件的 fire 为检测器结果或 OR。纯系统函数与 random/time 等按各自描述符区分；不得因接口相似就把非确定性函数当纯 op。调用次数、返回值保持、guard、sample identity 和 input/output/inout ABI 与当前行为逐项对照。

冻结旧模型存在 Output 克隆 DPI 后重复调用的具体用例。2026-10-25 用户明确选择单个原调用与 held sample，记录为 [语义决定](20261025-single-call-decision.md)；`effectPolicy` 继续使用 `single-original-call`。旧日志及原始严格差异保持原样，精确的 Output 重复调用去除单独归类为已批准；调用顺序和触发次数等其他差异继续逐项检查。详见 [旧调用证据](baseline-and-capabilities.md#r4r5-的旧-dpi-行为差异)。

此时 monitor/strobe 也已经是 grhsim.system-task，但仍在无分区大图中。split-event-and-output 才将它们及参数锥迁入 Output，建立粘滞触发、变化历史和 output-end 写回；grh-to-grhsim 不提前进行这些锥提取。

R4 将 free monitor/strobe 的 callCond 和每个参数分别保存到原 GRH register 声明，初始化为完整类型的零/空值；比较当前值与旧历史，Logic 使用 caseNe，Real/String 使用 ne。`grhsim.history-write(data)` 是无结果的 History-effect op，唯一 operand data 与目标 `regSymbol` 声明的完整类型一致；要求声明 `grhsim.history=output-end`、写口 `grhsim.outputEnd=true`、owner 为 Output。每个历史恰有一个这种写口，不进入普通 sink writerOrder，全部在 Output 末一起提交。事件任务只建立 sticky trigger 属性，不改成变化检测。操作数示例见 [方言规范](../../wolvrix/docs/grh/grhsim-dialect.md#output-histories-and-effect-boundaries)。

### 2.4 来源与声明映射

declaredSymbols / generateGroups / SrcLoc / originModules 及声明到优化值的映射保存在 GRH。DeclarationBinding 表达声明身份/完整类型，加有序的 {targetKind=Value|State, target=GRH 实体引用, declaredLow, targetLow, width} 片段。

所有目标在同一 top Graph；片段按逻辑位校验，打包、克隆、合并/删除和重载同步维护。JSON 用 graph/op/value 的 symbol 文本保存引用，load 重新解析为当前 ID；symbol rename/转交必须维护文本引用。它不依赖旧 GrhSIM ValueId/StateId 或 InstancePath。

## 3. 分区产生的位置与归属

第一次创建虚拟分区的是 **grhsim-split-event-and-output**，在转换及无分区优化之后。它提取检测器的事件输入锥，提取 top 输出端口/时隙任务的输出锥，重接根及清理死原锥；剩余可执行操作归 General。

这一步之前没有分区，grhsim-simplify 可以全图合并等价 edge-detect；这一步之后才按完整叶 owner 约束局部化简。后续两个 partition pass 和 emitter 都不能补做 Event/Output 提取。

之后按顺序：

1. grhsim-split-nonsink-and-sink 将 General 拆为 nonsink / small-sink / large-sink，状态分类由总逻辑字节数及显式阈值决定。
2. grhsim-partition-nonsink 根据活动度细分 nonsink，并在真实边界上可选 clone。
3. grhsim-partition-sink 根据时钟、门控、优先级细分两类 sink，并发布 SinkSchedule。

归属使用 op 的 grhsim.partition 文本路径，阶段示意见 [虚拟分区](virtual-partitions.md)。没有逐 op role；前述 pass 在属性上完成归属，临时分析局限于各次调用，不发布另一棵成员树。

副作用、edge 历史和 random 采样不由分区替代。事件 pulse 跨区域供写口/调用使用是合法依赖；普通计算和状态读取按所需执行上下文提取，不能以共享 value 绕过采样或收敛后读取。

grhsim-simplify 在无分区阶段可全图优化；一旦有分区，只比较完整叶 owner，在内部 CSE/传播并保护出口和 clone。共享状态的全局优化放在分区前；局部 used-bits 不得窄化其他分区共享的状态。

small-sink/large-sink 尚未细分时，各自就是当前叶 owner。其内部 simplify 可以合并纯计算；partition-sink 确定最终时钟/门控/优先级分组后，负责为各组私有化所需纯锥并重接引用，再发布 SinkSchedule。不能提前建立一套 role 来阻止这种合法化简，也不能复制 effect。

## 4. SinkSchedule 与 emitter 私有数据

使用现有 transform::SessionStore、SessionSlotValue 和 EmitOptions::session；不再引入平行 scratchpad 容器。关键产物缺失、slot 类型错误或 session 生命周期不足时明确报错，不允许静默返回。

### 4.1 首个跨 pass 的额外数据：SinkSchedule

grhsim-partition-sink 完成属性和最终 ID 变更后，原子发布一份只读 SinkSchedule：

```text
SinkSchedule {
    stamp: {designInstance, topGraph, revision}
    partitionConfigHash
    complete
    sinkGroups: [
        {partitionKey, fire, guards}
    ]
    generalRuns: [
        {partitionKey, orderedWriters, requiredNonsinkKeys}
    ]
    largeCommitRuns: [
        {partitionKey, orderedWriters, requiredNonsinkKeys=[]}
    ]
}
```

generalRuns 是 P_general 中 sink 的有序采样/写入 run：small writer 求值并更新 next，large writer 求值并保存提交参数。requiredNonsinkKeys 只标注这个 run 需要的数据及 effect-order 的传递前驱，不列出整个 nonsink 执行计划。largeCommitRuns 是 P_large_sink 中对快照的有序提交，依赖列表为空。一个 sink 分区可出现于多个 run，以保留被其他时钟组穿插的 writerOrder。实际 API 位于 include/transform/grhsim/sink-schedule.hpp；requireSinkSchedule 检查实例/top/revision、配置和当前图中分组/guard/优先级/依赖/顺序。

所有引用均指向原 GRH 或稳定分区 key。列表是执行顺序标注，不是另一份可编辑归属；成员归属始终以 GRH 属性为准，operands、类型和状态目标也不重复存入调度。依赖、guard、writerOrder 和采样/提交职责必须一致。不能只按 clock 分组而丢掉跨组写优先级，也不能在 large 提交时重新计算已采样参数。

Output 的历史提交不属于这份 sink 调度：相关读写 op 与 output-end 语义留在 Output，由 emitter 按固定六段协议生成。全部 nonsink 的遍历/激活、物理布局、函数与文件组织同样属于 emitter 的私有便利数据。

它不包含物理字段/offset、数组访问配方、helper/chunk/TU 或第二套 OpId/ValueId。无需在此前建立 StatePolicy、PhasePlan、PartitionIndex、ActivationPlan、WritePlan 或统一 StCpuPlan 这些跨 pass 产物；各 pass 可以使用自己的临时扫描、队列和索引。

slot 按 design 实例、top 与 sink/分区配置隔离，不能使用会相互覆盖的全局 grhsim.schedule。调用者显式提供覆盖 pass 与 emit 的同一 session；PassManager 临时创建并在 run 后销毁的 session 不支持分次发射。

### 4.2 emitter 的便利结构

wolvrix/lib/emit/grhsim/cpu-st-cpp.cpp 在一次调用内创建私有 CpuStEmitContext，按需包含：

| 数据 | 职责 |
| --- | --- |
| 存储布局 | small current/next、large in-place、输入/边界、prevEvent、eventAct、timeslotTrigger、activeFlags 的类型、字段及 offset |
| 激活与访问 | 三类 fanout、事件/时隙路由；按 (consumer OperationId, operandIndex) 的数组访问、采样快照、guard/别名与寿命 |
| 函数与文件 | 根据既定调度生成六段、各分区、init、调用、FST/profile 和 helper；组织 TU 与清单 |
| chunk 与 chunkFrame | 按发射参数控制全部生成函数的行数；分析跨 chunk 的局部活跃值并通过 frame 引用传递 |

这些数据可以协同计算，但只服务本次 emit；默认随调用释放。若实现为了复用把它们暂存到 session，也必须是发射器私有、带完整图/选项 stamp 的可重建缓存，不能成为新的公开规划阶段或另一套计算 IR。

继续保留当前 12 类 named store 的职责：smallSink、largeSink、input、nonSinkBoundary、small/large 的 enable/payload 四类 boundary、prevEvent、eventAct、timeslotTrigger、activeFlags。smallSinkStoreNext 复用 smallSink 布局。chunkFrame 只传递函数内部跨块局部值，不等于这些语义边界存储。

max-function-lines 与 TU 参数仅影响 emit；不参与虚拟切图或 SinkSchedule 的配置摘要。行数限制覆盖全部生成函数，计入支架、guard、chunk 调用及 dispatcher；超限时拆分函数，跨块局部变量及控制状态由 chunkFrame 传递。修改预算可使用同一图与有效调度重新发射，不能重新克隆计算、重编号分区或改变激活语义。统一函数预算规则见 [pass 与 emitter](passes-and-emitter.md#8-emitgrhsimcpu-st-cppcpp)。

## 5. 生命周期与失败

GRH/session 的通用实例身份与保守 revision 在 R1 补齐，不由仿真模块私藏一份图版本：

1. 所有影响实体、类型、符号、端口、初值、归属、采样、writerOrder、来源的变更，以及 freeze/压缩的 ID 重建，均更新 revision。当前 freeze 会对存活 op/value 重编号并重置 generation，不能只靠 ID 字段判断旧引用是否有效。
2. grh-to-grhsim 和前面的各拆分/优化 pass 只提交图。局部 ID 表不跨 revision 使用；freeze 后扫描属性及原 use-def 重建。
3. SinkSchedule 在任何相关图或 sink 配置变更后失效。partition-sink 进入时使旧 complete 失效，完成全部改图、必要编号重建和校验后才发布；失败无可消费旧/半套结果。
4. emit 在读图和调度后建立私有数据，不隐式改图、freeze 重编号、分区或改变 sink 顺序。发射参数变化只重建私有数据；源图/调度过期必须明确拒绝。
5. clone/load/replacement 获得新 design 实例身份，保留阶段/归属属性，不继承 resolved 调度或私有缓存；相同 ID/SymbolId 数字不代表同一实体。dryrun 使用隔离的 design 和 session。
6. 改变 small/large 阈值从 event-output-split 阶段重新拆 General 并运行后续步骤；改变活动度选项从 nonsink-sink-split 阶段重新切图；改变 sink 策略重新运行 partition-sink。重复同配置的已完成步骤验证后无操作，sink 调度缺失时仍须重建。

首版采用 O(1) revision/stamp 比较和保守失效，内容摘要在冻结/checkpoint 等边界按需计算，不在每次 value 访问时重扫全图。

## 6. 统一持久化与重启

只保存统一 GRH JSON，含 format/dialect 版本、逻辑域、完整类型/来源、阶段、分区属性及对应配置。阶段依次为：

```text
converted                  # 无分区
event-output-split         # general / event / output
nonsink-sink-split          # General 拆成三个子区域
nonsink-partitioned         # 活动度切图与真实 clone
sink-partitioned            # sink 分区已写回；调度另行重建
```

SinkSchedule、物理布局、访问/激活表、chunk/TU 不进语义 JSON。调试可导出只读摘要，不能作为另一套执行输入。重启先 load/verify，按阶段完成尚未执行的 pass，再运行 partition-sink 发布当前实例的 SinkSchedule，最后 emit。

旧无版本 GRH 的默认值与新 dialect 版本必须明确；未知版本/kind、部分转换/分区和缺失关键语义不能靠猜测恢复。旧 wolvrix.grhsim.v3 只供冻结基线读取，新入口明确提示从原 SV/统一 GRH 重生，不长期保留另一套 loader。
