# S9 前置 — GrhSIM 最小扩展与 CPU ST 目标数据模型

- 日期：2026-10-23。
- 状态：**历史方案，已由 [移除独立 GrhSIM IR 计划](../remove-grhsim-ir/README.md) 替代。** 下文独立 SimModel/CpuProgram/CpuStArtifact、共享 bitSelect/prioritySelect、assignAs 及独立 JSON 设计不再实施；保留正文供追溯。
- 当前顺序与实施状态以 [新 pass 规划](../remove-grhsim-ir/passes-and-emitter.md) 和 [进度](../remove-grhsim-ir/PROGRESS.md) 为准，再推进 [S9 数组优化](stage-09-array-normalize-mapping.md)。[代码事实审查](pre-s9-grhsim-ir-boundary-review.md) 保留历史证据。
- 范围：先服务已经实现的 CPU 单线程 backend；不为未实现的 NUMA、多核或其他 backend 定义通用 mapping/task 框架。

## 1. 已定边界

保留独立的 GrhSIM 仿真图，但不再独立定义一遍 GRH 的计算语义。计算 op、逻辑类型、属性值、shape 几何和定宽求值规则只有一份公共定义；GRH 与 GrhSIM 的容器、ID、图生命周期可以不同。

CPU backend 拥有自己的 lowered program 和生成计划。CPU 的 phase、状态缓冲策略、物理类型、分区、激活、写入、值表示、frame、函数和 TU 全部放在 CPU 专属结构中。通用仿真模型不包含 CPU 类型定义，也不保存 generic mappings。

```text
公共定义：ComputeKind / LogicalType / OpDescriptor / 位与数组语义
    ├─ GRH：层次、RTL 声明、端口、实例、XMR
    └─ SimModel：I/O/S/F/Init、SSA 图、事件条件和调用语义
                │ cpu.st.lower：建立独立 CPU ID 空间
                ▼
          CpuProgram：CPU lowered SSA、phase、状态策略、事件与调用执行方式
                ▼
          CpuStArtifact：分区、存储、激活、写入、值访问、frame/函数/TU
                ▼
          emitCpuSt(source, artifact)：只读发射固定 eval 协议
```

**删除** `BackendMapping` 泛化壳、`CpuSchedulePlan` 混合壳、NUMA/core/task/waitsFor 镜像及历史 stage 枚举。它们内部真正使用的表按下文迁移，不能连同壳一起删除。固定 eval 协议、拓扑顺序、写入优先级继续保留，各有唯一来源。

## 2. 公共定义：只维护一次的内容

### 2.1 类型、属性和描述符

下列声明归 `include/ir/`、实现归 `lib/ir/`，命名空间为 `wolvrix::lib::ir`。这是 GRH 与仿真层共同依赖的定义库，不依赖任一图容器或 CPU 头文件。

| 定义 | 必需字段/接口 | 明确含义 |
| --- | --- | --- |
| `LogicalType` | `kind: Logic/Real/String`；`width`；`isSigned`；`domain: TwoState/FourState`；`shape: int64[]` | width 是**总逻辑位宽**，不是叶宽。Logic 的 width>0；shape 每维>0、乘积无溢出且整除 width；叶宽=width/乘积。Real/String 规范字段为 width=0、shape为空、isSigned=false、domain=FourState（后两项为无语义的统一哨兵），不把 C++ 对象大小当逻辑位宽 |
| 类型几何接口 | `elementCount`、`elementWidth`、`indexedSuffix(type,k)`、`linearBitOffset`、`sameType`、`sameBitLayout` | 都接收完整 LogicalType；同总宽不代表同型。suffix 返回完整剩余 shape；所有乘加检查溢出。空 shape 是标量，`[1]` 不等于空 shape |
| `AttributeValue` | bool/int64/double/string 及其 vector 的现有 variant | GrhSIM 的 ParameterValue 直接使用此定义；属性名可由各自 string interner 管理，不复制 variant |
| `ComputeKind` | §2.2 的封闭枚举 | 公共计算 op 的唯一身份；GRH enum 入口和 GrhSIM 文本名字由同一表生成，不手写第二份 switch/注册列表 |
| `OpDescriptor` | `kind`、稳定文本名；operands/results 的角色和数量规则；参数 schema；类型/shape 校验与推导入口；effect 分类；定宽求值入口 | 描述符是编译器代码中的只读定义，不作为每个 op 的 payload 重复序列化。effect 至少区分 Pure、ReadObject、WriteObject、ExternalCall、EventHistory |
| `EvalPolicy` | logic domain；除零/未知值处理规则；结果转换规则 | 参数化公共位语义。GRH/GrhSIM pass 保留各自遍历、预算、scope 和重写策略；不强行合并整个 const-fold pass |

GRH 适配器把当前未显式携带 domain 的值按 FourState 解释；选择 TwoState 是仿真转换的显式策略。类型结构定义共享，不要求共享 TypeId 或 interner。`u9[4,8]` 在两层都必须由 `sliceArray(base,i)` 得到 `u9[8]`；不能在仿真层仅校验总宽72。

### 2.2 公共计算 op 白名单

以下全部保留为公共计算定义，**不计为 GrhSIM 新 op 扩展**。现有 `core.compute.*` 可作为由公共表生成的文本编码，名字相同不意味着继续独立维护定义。

| 族 | 保留的 kind | operands/results 与契约来源 |
| --- | --- | --- |
| 常量 | `constant` | 0→1；参数 value 是结果完整类型的定宽字面量，四态保留 X/Z |
| 算术 | `add sub mul div mod` | `[lhs,rhs]`→1；定宽、signedness、domain、结果转换使用公共 GRH 契约 |
| 比较 | `eq ne caseEq caseNe wildcardEq wildcardNe lt le gt ge` | `[lhs,rhs]`→1位结果；普通、case、wildcard 比较的 X/Z 行为分别定义，不互相代替 |
| 位运算 | `and or xor xnor not` | 二元或一元→1；按总逻辑位图计算，结果的 shape 不授权 elementwise 算术 |
| 逻辑/归约 | `logicAnd logicOr logicNot reduceAnd reduceOr reduceXor reduceNor reduceNand reduceXnor` | 二元逻辑或一元归约→1位；truth/未知值规则共享 |
| 移位 | `shl lshr ashr` | `[value,amount]`→1；amount 位宽、过宽移位和符号扩展规则共享 |
| 选择 | `mux` | `[condition,whenTrue,whenFalse]`→1；condition 的真假选择整个值，臂转换规则共享 |
| 赋值/视图 | **`assign`、`assignAs` 两个 kind** | 各1→1；assign 要求完整同型；assignAs 对同 domain 的 Logic 保持总逻辑位图、允许等宽 shape/符号重解释，不作截断/扩展或未知值擦除。Real/String 仅允许同种类型改名。转换不再把两者都映成 assign |
| 位拼接/重复 | `concat replicate` | concat 的 operands 从高位到低位；replicate 一个 operand、参数 rep>0；保留已有带 shape 结果的合法表达 |
| 数组构造 | `arrayCreate` | `[e0,...,eN-1]`→1，N>=1；元素完整同型，总宽 W、shape S，结果宽 N×W、shape `[N]+S`；result[i]=ei，无额外语义参数 |
| 切片 | `sliceStatic sliceDynamic sliceArray` | static `[base]`+闭区间 bit 起止；dynamic `[base,bitOffset]`+sliceWidth；array `[base,i0,...,ik-1]`、1<=k<=rank，结果**精确**为剩余 suffix 几何，无 sliceWidth |
| 从仿真层提升 | **`bitSelect prioritySelect`** | 都是纯组合；提升到公共定义，见下文。暂时只有仿真优化生产它们也不改变归属 |

公共定义不新增 arrayConcat、reshape、pack、unpack；数组的物理读取/物化交给 CPU 值计划。register/latch 声明、实例、blackbox、XMR、DPI import 仍是 GRH 结构定义，不复制到仿真 compute 枚举。

`bitSelect(mask,a,b)`：三个 operands 与结果完整同型，逐位 `r[i]=mask[i]?a[i]:b[i]`。首批支持 two-state、总宽1..64，带 shape 时仍按相同总位图选择；不借此新增四态或任意宽支持。例如 `bitSelect(4'b1010,4'b1100,4'b0011)=4'b1001`。

`prioritySelect(c0..cN-1,a0..aN-1,d)`：2N+1 个 operands、一个结果，3<=N<=64；ci 是无 shape、unsigned、two-state 1位条件。第一个为真的 ci 选择 ai，无命中选择 d；等价于相同结果类型的嵌套 mux。首批保留 two-state、总宽1..64的范围；臂到结果的转换调用**同一公共 mux 规则**，不能另写一套符号扩展。构造器和 verifier 对完整 shape 也执行该规则，修正现有“诊断称 scalar、实际不检查 shape”的含混。此 op 不使未选分支的已有 producer 变成可重采样或可省略的副作用。

例子：`arrayCreate(8'h11,8'h22)` 是 `u8[2]`，扁平位图为 `16'h2211`；`concat(8'h11,8'h22)` 的位图为 `16'h1122`。同型数组经过 `assignAs(a):u72` 再 `assignAs(...):u9[8]` 才是后续 S9 要消除的视图链，不能继续用严格同型的 assign 表示这种转换。

## 3. GrhSIM 保留的最小 op 扩展

下面列出全部保留项。状态端口、system/DPI 复用 GRH 已有的访问与调用契约，只把 symbol/declaration 引用归一化为对象 ID；它们不是第二套算术语义。扩展 descriptor 复用公共端口/调用校验内核，额外校验仿真对象和事件条件。

### 3.1 接口与状态：13 个常规归一化 op

| Sim kind（文本名沿用 core 前缀） | operands | object refs / results | 参数与执行约束 |
| --- | --- | --- | --- |
| `input.read` | 无 | InputId / 一个完整同型结果 | 读取本次 eval 固定的输入快照 |
| `output.write` | value | OutputId / 无 | 消费已计算值，在 eval 返回前发布；不触发重新计算其 producer |
| `state.read` | 无 | StateId / 一个状态完整同型结果 | 读取所在转移轮的旧状态快照 |
| `state.readArray` | i0..ik-1 | StateId / 一个元素或子数组结果 | k 与结果的 suffix 几何复用公共数组状态口契约；允许的等总宽端口视图见下文 |
| `state.write` | enable,data,events... | StateId / 无 | event_edges 与尾部 events 对应 |
| `state.writeMask` | enable,data,mask,events... | StateId / 无 | mask 为逻辑逐位掩码，宽等于状态总宽 |
| `state.writeArray` | enable,i0..ik-1,data,events... | StateId / 无 | k 由目标 rank、event 数和 operand 角色确定 |
| `state.writeArrayMask` | enable,i0..ik-1,data,mask,events... | StateId / 无 | mask 宽等于寻址子数组的总逻辑宽 |
| `state.fill` | enable,data,events... | StateId / 无 | data 为单叶广播值，或合法的等总宽 packed fill；区分方式由公共端口类型契约判定 |
| `state.latchWrite` | enable,data,mask | StateId / 无 | 无 event、标量 latch；enable 按电平生效 |
| `system.function` | args... | 无 / 一个结果 | name、has_side_effects、proc_kind、has_timing；有副作用时不能作为纯计算复制 |
| `system.task` | callCond,args...,events... | 无 / 无 | name、event_edges、proc_kind、has_timing；保留一个调用的完整粒度 |
| `dpi.call` | callCond,inputArgs...,inoutArgs...,events... | FuncId / return?、outputArgs...、inoutArgs... | 方向与类型从 FuncId signature 取得；一次调用整体执行，禁止拆成多个调用/读写 |

源模型中有事件的 state write 至少有一个 event，latchWrite 为电平敏感；CPU lowering 可产生归一化的 event-free 写，但不能把源时序含义丢掉。enable/event 的1位要求、调用条件的非零 truth、OOB、mask、fill 的精确定义沿用对应公共端口/调用规则；CPU 的既有 OOB 补零/忽略写等具体行为必须在降低时保留，不通过“逐维 clamp”改写。

**状态端口边界的等总宽视图继续合法**：如源 `u1[352,11]` 整体写到状态 `u11[352]`，数据总宽同为3872，可按规范的逻辑位图重解释。这项许可只作用于明确允许它的状态 operand/result；不是 sliceArray 的 suffix shape 校验例外。读取、掩码和写数据分别验证，不能仅凭总宽相等放过全部 operand。

### 3.2 一个 lowered 仿真原语

保留 `event.edgeDet` 的语义定义，但它只出现在 **CpuProgram 的 lowered graph**，不要求未降低的 SimModel 存在它：

```text
operands = [eventSignal]          # 一个无 shape 的1位 logic SSA值
results = []
attributes = {edge, prevInit, event:CpuEventId}
```

edge 为 posedge/negedge/both；prevInit 为定宽初始电平。执行时比较旧历史与当前 eventSignal，写本轮 event act，并立即保存新历史；下轮不能再次报告同一电平的同一边沿。`event` 是逻辑事件身份，**不是 bitmap 位号或历史数组下标**。物理位置由 CpuStoragePlan 给出。相同 `(eventSignal,edge)` 归一化为一个检测器；不同 edge 可以保留独立历史。四态 edge 规则继承已有仿真规则，不能直接拿 C++ bool 不等式代替。

这是一个确有历史更新副作用的仿真扩展，不提升为公共 Pure compute。保留定义不意味着建立通用调度器；当前只有 CPU lowerer 生产，未来消费者自行定义其实现计划。

### 3.3 CPU 专用 op 与删除项

保留 **`cpu.compute.maskedOr` 一项 CPU 专用计算扩展**，只允许出现在 CpuProgram。结果为 `OR_i(select_i ? data_i : 0)`，不假定 one-hot，不能改为优先选择。

- Dense：operands `[mask:uN,data:uW[N]]`，无参数；result 总宽 W。
- Views：operands 为既有 SSA 值列表，参数 views 的每四项为 `[selectOperand,selectBit,dataOperand,dataBitOffset]`；operand 编号从0起，偏移是最低位为0的逻辑 bit 偏移，data 片段宽为结果总宽 W。
- N>=2、W>=1，two-state，范围检查和完整结果类型沿用现有 CPU op 契约。结果只消费既定 SSA 快照；没有授权重新读 state/DPI/随机值。

删除 `core.compute.expr` 和对应遗留 pass/编码/旧 stage 支持；新加载器给出“旧产物需重生”诊断。保留的 CPU op 不复制公共 ComputeKind；其他 backend 将来需要 maskedOr 时必须显式实现、展开或拒绝。

初始化 const/random/readmem/fill **继续是 InitStep 的四个 tagged payload，不加入 G 的 op 枚举**。不再把 init 指令名、CPU store class、helper/TU 节点冒充新的电路计算 op。

## 4. 后端无关的 SimModel：明确保留的数据结构

本节结构位于 `include/grhsim/ir/`，完全不依赖 `include/grhsim/backend/cpu_*`。表中 ID 均为本模型的强类型 ID。

### 4.1 基础实体与生命周期

| 结构 | 字段定义 | 生产者 → 消费者 |
| --- | --- | --- |
| `Id<Tag>` | index（0无效）、generation；不同 Tag 不可混用 | 图容器 → verifier/pass/IO；删除后旧 generation 不得命中新实体 |
| `TypeEntry` | TypeId、公共 LogicalType；可选可读名称 | 转换/type interner → 所有 op/object 校验 |
| `SimValue` | ValueId、TypeId、可选 name/origin | 唯一定义 op → uses/变换；一个 value 只有一个 producer |
| `SimOp` | OpId；code=`ComputeKind或SimKind`；有序 operands/results；typed object refs；schema 限定的 attributes；origin；可选 effectOrdinal | 转换/语义 pass → CPU lowerer、解释/检查工具。无 CPU phase、storeClass、CPU op |
| `ModelStamp` | ModelIdentity（128位）+ semanticRevision | 语义容器 → CpuStArtifact 过期检查；不把 metadataRevision 当语义版本 |
| `SimModel` | name、stamp、metadataRevision；strings/types；I/O/S/F/接口表；G；Init；metadata | 转换/全图优化 → CPU lowering/语义 checkpoint；不持有 mappings、CPU plan 或编译中间缓存 |

`effectOrdinal` 是从 GRH 声明顺序产生的无符号有序号，仅赋给 state write、task、DPI/有副作用 function 等有序操作。它明确保留可观察顺序：同一状态按 ordinal 递增应用，后者覆盖前者；外部副作用按源过程/调用顺序约束执行。纯 compute 的容器排列可变，不据此重新编号写口。新建/合并 effect 时必须显式维护顺序；不得用新的 OpId 大小推导优先级。它是语义顺序，**不是调度表**。

typed object ref 只取 InputId/OutputId/StateId/FuncId；公共 compute 不携带对象引用。可继续使用紧凑 ranges+共享 operand arena 存储，但 Range 必须说明所属 arena，所有访问通过带边界检查的 span；它不额外承载语义。

### 4.2 对象、接口和初始化

| 结构 | 必需字段与约束 | 生产者 → 消费者 |
| --- | --- | --- |
| `InputObject` / `OutputObject` | id、name、TypeId、origin；名称在所属接口空间唯一 | graph ports → read/write、host接口 |
| `StateObject` | StateId、name、TypeId、origin、`kind:Register/Latch` | GRH 声明 → 状态 op、Init、CPU策略选择；**不含 SmallSink/LargeSink** |
| `ExternFunction` | FuncId、声明名、宿主 symbol、按声明顺序的 DpiArgument、可选返回 TypeId、origin | DPI import → call 校验和宿主 ABI |
| `DpiArgument` | name、direction:Input/Output/Inout、TypeId | declaration → operand/result 排列、调用代码 |
| `InterfacePort` | name、direction、input?、output?、outputEnable? | 转换 → host接口；input/output 分别引用 I/O，inout 必须同时有两侧与 outputEnable，不能丢掉三态使能 |
| `InitRecord` | StateId、非空且有序的 InitStep[] | 转换 → 初始化；每状态恰一条，覆盖全状态，无隐式未初始化部分 |
| `InitStep` | 下述四种 payload 之一 | 转换 → CPU init action；步骤有覆盖顺序，不是普通 SSA op |

InitStep 的 payload 明确定义为：

| tag | 字段 | 作用 |
| --- | --- | --- |
| Const | value：状态完整类型的常量 | 全量初始化；未显式给初值时转换器补全四态全X或相应显式两态策略 |
| Random | seed?：有符号整数种子 | 对 Logic 状态整体初始化；缺省用既有无参随机流 |
| ReadMem | file；format:Hex/Bin；start?；count? | 仅数组；start/count 是行主序叶元素的线性行地址，缺省0/到末尾 |
| Fill | element：常量或 Random(seed?)；start?；count? | 仅数组；每行常量填充或**逐行独立随机采样**，不能把一次随机结果复制全表 |

标量只允许一个 Const/Random 步骤。数组部分覆盖前必须有全量打底。跨状态初始化按转换时保留的 InitRecord 顺序执行，各 record 内按步骤顺序执行；CPU 不得为分文件而改变随机流、文件读取或覆盖顺序。

`proc_kind`、`has_timing`、`has_side_effects`、event_edges 等是 op schema 的明确语义属性，保留在 SimModel；不是随意扩展的参数袋。不支持的过程/timing 在转换或 lowering 时明确拒绝。CPU 的 sample-once 标志、timeslotFlag 和物理事件号不写回这些属性。

### 4.3 来源数据

| 保留结构 | 字段定义/用途 |
| --- | --- |
| `Origin` | OriginId、sourceKind、symbol/sourceIndex、file、起止行列、pass、note；用于诊断和归因，不决定执行 |
| `declaredSymbols` | 源声明名的稳定有序集合；优化掉的声明仍可保留名字 |
| `GenerateGroup` | scope、name、按展开轮次排列的 symbols；供 generate 来源查看 |
| `DeclProvenance` | symbol、origin、声明总 width、slices[]；slices 可以为空表示已消失 |
| `DeclProvenanceSlice` | kind:Direct/Alias/Merged；typed target:Value/State/Function；targetBitOffset、declBitOffset、width |

slice 的偏移均为规范逻辑 bit 偏移，width=0只表示非 Logic 整体关联，此时两个偏移为0。CPU program clone 保存 sourceOp/sourceValue/origin 供调试反查；这不是需要泛化的独立 mapping 系统。来源丢失不能通过名字猜回。metadata 更新只使 debug/dump 绑定重建；不要求重做无关的执行分析。

## 5. CPU 专属产物、ID 与 lowered program

CPU 结构放在 `include/grhsim/backend/cpu_program.hpp`、`cpu_plan.hpp`、`cpu_codegen_plan.hpp`；CPU 序列化放 `io/cpu_st_json.*`。通用 `ir/model.hpp` 不再定义任何 Cpu* 类型。下面的名字是目标接口，实施时不能再用 optional cpu 塞回 generic BackendMapping。

### 5.1 产物根与配置

```text
CpuStArtifact {
    sourceStamp, sourceDigest, metadataRevision,
    targetAbi, options,
    program,
    partitions, storage, activation, writes, values, codegen
}
```

| 字段/结构 | 完整定义与约束 |
| --- | --- |
| sourceStamp / sourceDigest | 被编译的 SimModel identity+semanticRevision 与规范语义内容摘要；运行中前者防过期，跨进程由规范内容摘要防止错误配对；不使用文件路径替代身份 |
| metadataRevision | 生成 debug/dump 绑定时的来源版本；仅执行发射可不依赖来源内容，启用 debug 发射须匹配 |
| `CpuTargetAbi` | pointerBytes、byteOrder、标量 size/alignment 表、宽值 padding/alignment 规则、nativeBitInt 支持及最大宽度；用于布局、代码选择与 static_assert，不以构建宿主 ABI 暗中替代目标 ABI |
| `CpuStOptions` | 下表的明确字段；保存解析后的全部有效值，不保存任意 key/value 扩展袋 |
| program | §5.2 的独立 CpuProgram，不是对已变更源图的裸 OpId 列表 |
| partitions/storage/activation/writes/values/codegen | §6–§10 的**必有** typed 计划；无相应工作时是合法空表，不用缺失 optional 代表“可能完成” |

CpuStOptions 的字段与单位：logicDomain；largeStateMinBytes（默认64，语义字节，Logic 按 ceil(totalLogicWidth/8) 判定）；nodeMaxOps、supernodeMaxOps、cloneMaxAddedOps（均为 op 数）；cloneMaxAddedLogicBits（复制结果的逻辑位数）；helperMaxEstimatedLines、unitMaxEstimatedLines（按统一 cost 估算的生成代码行数）；outputGate（bool）；maxSettleRounds（默认100000）；randomSeed（u64）；unknownInitPolicy（PreserveXZ/Zero，FourState 必须 PreserveXZ，TwoState 使用显式已选策略）；waveformEnabled、perfCountersEnabled（bool）。其余默认值在实施迁移时沿用对应现有 pass 的默认值，产物中必须记录解析后的数值，不能依赖另一进程的隐式默认。

上述分区预算是软上限，单个不可拆 op 可超限并诊断；maxSettleRounds 是硬运行上限。Real/String 采用 NextBuffer；达到阈值的 Logic 采用 SampledInPlace。策略选择只做一次，不再根据 shape 是否为空分类。现有 pass 的参数在迁移时必须逐项对应已定义字段，删除的调参入口须明确诊断；不能用 parameters 袋绕开定义。

CpuStArtifact 只表示可校验、可发射的完整编译结果。编译过程的 `CpuStBuilder` 是 CPU 编译器临时对象：持有工作 CpuProgram、配置、已构造表和分析缓存；不能当作完成产物传给 emitter，也不序列化为可恢复执行的半成品。各 pass 接收明确输入组、返回明确输出组，不再用 stage 数值比较和 complete bool 判断字段是否凑齐。

source 和 artifact 由调用方/文件 bundle 分别拥有；`emitCpuSt(const SimModel&, const CpuStArtifact&)` 先验证配对，再只读发射。源模型不反向拥有 CPU 计划。不得为了避免失效检查，把源模型的 revision 无条件重写成计划 stamp。

### 5.2 CpuProgram

| 结构 | 字段定义 | 唯一职责/消费者 |
| --- | --- | --- |
| `CpuProgram` | 公共 LogicalType 的本地 type table；CpuValue[]、CpuOp[]；statePolicies[]、events[]、effects[]；programRevision | CPU lowerer 建立，phase simplify/边界 clone 修改；计划构建后冻结 |
| `CpuValue` | CpuValueId、CpuLogicalTypeId、可选 sourceValue:ValueId、origin/name | lowered SSA 值；clone 可以多个 CpuValue 指回一个源 Value，不能反向假设1:1 |
| `CpuOp` | CpuOpId；code=`ComputeKind/SimKind/CpuKind`；本地 operands/results；源对象 refs；attributes；eventAny:CpuEventId[]；`phase:Event/General/LargeSink/Output`；sourceOp?、effectOrdinal?、origin | 共享语义定义下的 CPU lowered op；每个 op 总归属一个 phase，无 None/旧 Compute/Commit |
| `CpuStatePolicy` | StateId、`commitMode:NextBuffer/SampledInPlace` | 替代 StateObject.storeClass；仅 CPU lowerer 按 options 选一次，后续 layout/write/emit 必须消费此决定 |
| `CpuEvent` | CpuEventId、detector:CpuOpId | 逻辑事件集合；detector 指向唯一 edgeDet，其 signal/edge/prevInit 在 op 中，避免再复制一份；物理 prev/act 在 storage 中 |
| `CpuEffectExecution` | op:CpuOpId、mode、timeslot?:CpuTimeslotId | 记录调用执行方式；事件条件只读取 CpuOp.eventAny，mode/slot 定义如下，供激活规划、storage 和 emitter |

CpuValueId/CpuOpId/CpuLogicalTypeId 与源 ValueId/OpId/TypeId 是**不同 C++ 强类型**。CPU 增删/clone 只改变 CpuProgram，不再调用源模型的 commitSemanticMicroMutation。CPU 的 I/O/S/F 引用仍明确指向配对 SimModel 的对象表；新临时状态使用 CPU slot/event 身份，不能伪造源 StateId。复制 artifact 必须重映射所有 CPU ID；不能把其中的引用当源 ID compact。

CPU 的 Value/Op/LogicalType/PhysicalType/Event/Timeslot/Supernode/Write/Slot/Use/Recipe/Snapshot/Materialization/Function/Frame ID 各用不同 Tag，复用 index=0无效的 Id 容器契约；表的 ordinal=id.index-1，不能把原始 index 直接当 bitmap 位号。TimeslotId 由 AtEvalEnd 记录分配且唯一。CpuProgram 是 CPU 编译副本，不增加第三套 op/type 语义；共享 descriptor/基础图存储实现，额外字段只承载上述 CPU 决定。

lowering 将源 op 尾部的 events 与 event_edges 一起替换为 CpuOp.eventAny，operands 保留 enable/index/data/mask/调用实参；低层不再留 event_edges 或物理 act/prev 参数。eventAny 是排序去重的逻辑事件集合，任一事件命中即满足事件条件；空集表示无事件限制。shared 端口/调用 descriptor 通过明确的 source/lowered 适配校验不同事件编码，不复制 data/mask/签名契约。edgeDet 的 event 身份是自身 typed attribute，其 eventAny 为空。

CpuEffectExecution.mode 的封闭取值：

| mode | 定义 |
| --- | --- |
| ValueCall | 已确认无外部副作用的系统函数，按所属计算区域求值；跨 helper 不新增求值 |
| OncePerEval | 当前 random/urandom 等已有“一次 eval 采样、后续复用”的系统函数；按 op 分配 sampled 标志与结果槽，进入 eval 清标志 |
| OnActivation | DPI 和普通有副作用 task/function，按原条件/事件激活执行一个完整调用；不能用结果去重合并不同调用，也不能因多个 consumers 增加调用 |
| AtEvalEnd | monitor 等既有 timeslot 任务；timeslot 是该记录的唯一 CpuTimeslotId，任一相关事件发生即锁存，到 Output 执行并清理；initial/final 的既有过程门控也须显式保留 |

State write 的采样/提交由 CpuWritePlan 负责，不再重复列为 CpuEffectExecution。CpuEffectExecution 不允许无条件把全部系统调用改为 OncePerEval。pure source compute 可按 phase/边界 clone；state read 的重读需可见性证明，DPI/随机/副作用 producer 不 clone。

## 6. CpuPartitionPlan：保留分区，去掉函数伪分区

持久化分区采用当前 CPU 真正需要的**四相与 General 超节点**，不保留泛化的 root/phase/node/EmitFunction 树。node 锥吸收、合并候选和依赖图是分区 pass 的临时分析对象。

| 结构 | 字段定义 | 生产者 → 消费者 |
| --- | --- | --- |
| `CpuPartitionPlan` | eventOrder:CpuOpId[]；general:CpuSupernode[]；outputOrder:CpuOpId[] | partition builder → activation/value/codegen；LargeSink 的有序写归 CpuWritePlan，不重复保存 largeOps 镜像 |
| `CpuSupernode` | CpuSupernodeId；ops:CpuOpId[]；category；eventAny:CpuEventId[]；enableGuard?:CpuValueId | 合并器 → runtime 扫描/激活/分块；id 的 ordinal 就是 general 数组下标，构建后固定 |

category 仅三种：`Data`（数据活动位驱动、只含值计算/采样）、`StateEvent`（NextBuffer 状态写簇、共享非空 eventAny）、`StateAlways`（无事件的电平状态写簇、每轮扫描）。enableGuard 仅可在 StateEvent 中记录所有成员相同的一位已采样 enable；否则为空，不能由名字相似猜测。

eventOrder/outputOrder 和每个 supernode.ops 是各自区域的**唯一规范 op 顺序**，保证先定义后使用并满足 effectOrdinal 约束；eventOrder 的检测器在其信号锥完成后执行。纯图重排不能重新决定 state writer 的优先级。General ordinal 固定之后，函数打包不重排 supernode、不改变分类/事件签名。

每个非 LargeSink CpuOp 恰由一个区域列表覆盖；LargeSink 的 effect op 由 writes 覆盖。跨区域值必须有 CpuValuePlan 绑定的快照。旧 PartitionId 的各种含义分别迁为 CpuSupernodeId/函数 ID，禁止继续把“EmitFunction 叶子”同时当活动度单元。

## 7. CpuStoragePlan：CPU 类型、存储、位号和临时槽

### 7.1 物理类型与具名 store

| 结构 | 必需字段与定义 |
| --- | --- |
| `CpuPhysicalType` | CpuPhysicalTypeId；kind:Bool/UInt/SInt/F32/F64/String/Array；logicalBits（整数）；elementType/count（仅Array）；sizeBytes/alignment。Array 通过嵌套保留 rank；padding 不是逻辑内容 |
| `CpuStoragePlan` | physicalTypes[]、namedStores[]、slots[]、enableCaches[]、eventBindings[]、timeslotBindings[]、beforeImages[]；尺寸及对齐来自 targetAbi |
| `CpuNamedStore` | kind（下表12种之一）；fields:CpuSlotId[]；sizeBytes/alignment。不存在的内容用0字段store表示，不用 None 分类 |
| `CpuSlot` | CpuSlotId；唯一生成名；CpuPhysicalTypeId；binding；home。binding 定义值身份，home 定义物理归属；见 §7.2 |
| `CpuEnableCache` | owningStore；sources:CpuSlotId[] |
| `CpuBeforeImage` | StateId；elementType:CpuPhysicalTypeId；rowCount。对应一个 `unordered_map<uint64_t,elementStorageType>` 运行时成员；key 是线性叶行号、value 为该轮首次写前的旧叶值 |

CpuEnableCache.sources 仅含对应 enable store 的已采样一位字段，顺序定义 cache bit。cache 是生成运行时的派生 u64 bitmap，wordCount=ceil(sources.size/64)，随原 enable 槽更新，不能通过重读 producer 构建；大小单独计入 runtime footprint，不混进 store.sizeBytes。没有消费者的 cache 不产生。

CpuBeforeImage 只为需要最终净变化检测的 SampledInPlace 状态生成；rowCount 为逻辑叶数，标量为1；每轮开始清空，首次写前 try_emplace，全部 writer 之后比较并释放该轮条目。它是运行时容器，不是 CpuPhysicalType 的 Logic/Array 类型，不塞入 CpuSlot；动态占用单独报告。规划和 helper ABI 沿用 legacy 的调用方缓冲/别名策略，不用此迁移改变宽值 helper ABI。

| store kind（保留现有12类能力） | 只允许的主要内容 |
| --- | --- |
| SmallSink | commitMode=NextBuffer 的当前状态；运行时 Next 镜像**复用同一布局**，不是另一份 layout 表 |
| LargeSink | commitMode=SampledInPlace 的状态 |
| Input | 本次 eval 的输入快照 |
| NonSinkBoundary | General 超节点间需要保存的既定 SSA 快照 |
| SmallSinkEnableBoundary / SmallSinkPayloadBoundary | NextBuffer writer 的 enable 与 payload（data、mask、index 按实际需要） |
| LargeSinkEnableBoundary / LargeSinkPayloadBoundary | SampledInPlace writer 的 enable 与 payload |
| PrevEvent | 按 CpuEventId 绑定的历史电平 |
| EventAct | 本轮事件的 u64 bitmap |
| TimeslotTrigger | 本次 eval 锁存的任务触发 bitmap |
| ActiveFlags | General Data 超节点的 Current/Next u64 bitmap；非 Data 位和尾部 padding 恒0 |

u11 元素可存 uint16；宽两态整数沿用已测定的 native unsigned _BitInt 表示与 padding ABI，禁止改回 hot path word-loop/按值返回大 std::array。四态 aggregate 继续明确拒绝，不由迁移引入静默两态化。

### 7.2 消除 state/value/aux 的多义字段

CpuSlot.binding 使用以下**封闭 tagged union**，不再同时放若干无效 ID 和一个 aux 整数：

| binding tag | payload 与含义 |
| --- | --- |
| State | StateId；当前状态；Next 镜像由访问时的 Current/Next bank 指定 |
| Input | InputId；加载后的输入快照 |
| ValueSnapshot | CpuValueId、capturePoint（§9）；保存该次生产结果，不代表随时可重读的源 |
| EventHistory | CpuEventId；该检测器的历史电平 |
| EventWords | wordCount；逻辑事件 ordinal 通过下面的 bit binding 定位 |
| TimeslotWords | wordCount；对应 CpuTimeslotId 集合 |
| ActiveWords | bank:Current/Next、wordCount；bit号是 General ordinal，仅 Data 位可置1 |
| EvalSampleFlag / EvalSampleResult | CpuOpId；OncePerEval 调用的标志/结果，result 多个时另带 resultOrdinal |
| OutputPending | CpuOpId、operandOrdinal；Output 阶段延后回写所需的 enable/index/data/mask |
| Scratch | CpuValueId 或具体 useId、capturePoint；访问快照/物化产生的临时空间，不指向新电路状态 |

home 仅取 `NamedField(storeKind,byteOffset)`、`FunctionLocal(CpuFunctionId)`、`FrameField(CpuFrameId,byteOffset)`、`RuntimeMember`。RuntimeMember 用于 sampled 标志/结果、staged output 等跨函数或跨 eval 内步骤的实现槽；名字、类型由 slot 唯一决定。非法 binding/home 组合由 verifier 拒绝。局部槽和 frame 的最终 home 在函数切块后完成，提前分析只能使用 slot ID，不能保存某个 C++ 局部变量文本。

事件与 timeslot 的**位绑定**分别为 `(CpuEventId,historySlot,actWordsSlot,bitOrdinal)`、`(CpuTimeslotId,wordsSlot,bitOrdinal)`；bitOrdinal 是该 bitmap 内的逻辑位序，实际 word/bit 为 `/64`、`%64`，不能与 CpuEventId 数值混用。bindings 是 storage 的有序子表，cover 每个事件/任务恰一次。FirstEval、输出脏位、收敛轮数、FST/perf 支持对象沿固定运行时协议生成；它们没有任意布局决策，不伪造成语义对象或通用调度节点。

## 8. CpuActivationPlan 与 CpuWritePlan：保留正在使用的表

### 8.1 激活

```text
CpuActivationPlan {
    inputChanged:      (InputId -> CpuSupernodeId[])[],
    boundaryChanged:   (CpuValueId -> CpuSupernodeId[])[],
    stateCommitted:    (StateId -> CpuSupernodeId[])[],
    eventRaised:       (CpuEventId -> CpuSupernodeId[])[],
    timeslotRaised:    (CpuEventId -> CpuTimeslotId[])[]
}
```

前四张表的目标只允许 General Data 超节点，按 ordinal 升序去重。inputChanged 由 Input 槽差分触发；boundaryChanged 由指定 SSA boundary 发布差分触发；stateCommitted 对应 NextBuffer 发布后的读者；eventRaised 对应边沿命中。SampledInPlace 写后的精确/保守行读者保留在写计划中，不能再靠 stateCommitted 重复点火。timeslotRaised 置位锁存标志，不是一张 task schedule。

这是 CPU planner 生产、pInput/pEvent/boundary publish/pPublish 消费的数据。序列化目标采用 ID 集合这一种权威表达；生成的位图常量是其确定性编码，不再把 bitmap 和 targets 两份独立内容都存为可修改事实。

### 8.2 写入与采样

| 结构 | 必需字段与约束 |
| --- | --- |
| `CpuWritePlan` | entries:CpuWriteEntry[]；largeOrder:CpuWriteId[]。entries 覆盖所有状态写，含 General 与 Output 延后写；largeOrder 只含 LargeSink phase 写 |
| `CpuWriteEntry` | CpuWriteId、op:CpuOpId、state:StateId；commitPoint:GeneralNext/LargeSinkInPlace/OutputDeferred；samples[]；readers[] |
| sample 项 | role:Enable/Index/Data/Mask、indexOrdinal（仅Index）、useId（§9）；capturePoint 只在该 use 引用的快照/recipe 中定义，不重复保存 |
| reader 项 | owner:CpuSupernodeId、staticRows?；空表示任何被写行都可能命中，非空为按 begin 排序、不重叠的半开 `[begin,end)` 行区间列表；单位为线性叶行，end<=状态叶数 |

索引/data/mask 的实际值通过 samples 的 useId 解析，不再重复保存一套源表达式。eventAny 从 CpuOp 的对应字段读取，写优先级从 CpuOp.effectOrdinal 读取，不在 entry 中再存一个可以不一致的 priority 字段。largeOrder 由 StateId 稳定分组、组内 effectOrdinal 递增确定；不同状态的数据都已采样，不以跨状态重排改变可见值。General/Output 的写执行顺序同样校验 effectOrdinal。

General 中先采样写参数，NextBuffer 写入 Next bank；SampledInPlace 的参数在任何目标原地修改前保存，LargeSink 阶段只消费这些快照。guard 为假时不引入新的数据读取/DPI/随机采样。mask 逐逻辑位应用，后声明写覆盖先声明写；alias 或部分重叠时必须在第一次写前保存原源值。Layout 和 commitMode 不改变这些契约。

SampledInPlace 写记录旧行并在全部相关 writer 应用后比较最终净变化，激活相交的读者到 Next 活动位。event-free 电平写、输出/事件依赖闭包和收敛相关读者不得漏掉；不能把“发生一次写”直接当作必定有净变化。现有按事件簇/enable cache 跳过批次属于执行优化，必须服从同状态 effectOrdinal，不能借聚类重排两个有效 writer。

## 9. CpuValuePlan：访问、快照与物化的唯一决定

这组结构先给 CPU 发射建立统一表示接口，S9 的 `cpu.st.plan-array-access` 再增加具体数组 recipe 优化。**不新增独立 ArrayAccessPlan stage，不另外平行维护一份数组 mapping。** scalar 与数组使用同一套 use、依赖和快照绑定。

### 9.1 记录与字段

| 结构 | 必需字段与定义 |
| --- | --- |
| `CpuValuePlan` | uses[]、recipes[]、snapshots[]、materializations[]；每个 use 唯一绑定 recipe，其 ReadValue 叶子引用明确 snapshot；每个需独立产生的值都有物化记录或明确 InlinePure 决定 |
| `CpuUse` | CpuUseId；consumer=`OpOperand(CpuOpId,operandOrdinal)` 或 `Publish(CpuSlotId)`；source:CpuValueId；destinationType:CpuLogicalTypeId；recipe:CpuRecipeId；materialization?；reason |
| `CpuSnapshotBinding` | CpuSnapshotId；sourceValue:CpuValueId；capturePoint；sourceSlot?；borrowUntil |
| `CpuCapturePoint` | region=`Event/General(supernode)/LargeSink(write)/Output/Init`；position=`Entry/BeforeOp(op)/AfterOp(op)/BeforeFirstWrite`；guardOwner?:CpuOpId |
| `CpuMaterialization` | CpuMaterializationId；value 或 useId；representation:Scalar/Elements/Packed；decision:InlinePure/Borrow/CaptureOnce；slot?；producer=`OpResult(CpuOpId,resultOrdinal)` 或 `Recipe(CpuRecipeId)`；region；referencedValues[]；cost |
| `CpuAccessRecipe` | CpuRecipeId；tag+下述 payload；完整 source/target 几何；referencedValues[]；cost |
| `CpuCost` | estimatedLines、readLogicBits、writeLogicBits、scratchBytes、loopTripCounts |

capturePoint 的位置相对于 §6 的规范区域顺序，guardOwner 表示必须在该 op 原有事件/enable 生效区内采样。borrowUntil 是同区域结束、指定提交点或指定 op 之前三者之一，必须能证明源在此之前不改变；否则 CaptureOnce 到 slot。sourceSlot 非空时指向已经存在的 boundary/frame/local 快照，不能改绑到较新的 State 槽。

CpuUse.source 是原 operand 的逻辑值；规范化/融合后实际读取的叶值由 recipe 的 snapshot 引用定义。例如 concat 可以读取两个不同的既定快照，不能强行用一个 sourceSlot 表示它们。相同 `(sourceValue,capturePoint,sourceSlot,borrowUntil)` 绑定可驻留复用；不同采样时刻不能因源 ValueId 相同而合并。写 samples 只通过 useId 消费这些绑定。

InlinePure 仅用于可融合的纯 compute；Borrow 不复制底层稳定数组；CaptureOnce 保存本次所需结果一次，跨 helper 则 slot 归 frame。cost 记录生成循环的代码体积和运行搬运量，不能把 compact loop 的运行次数当文本展开行数。use.reason 为可验证的规则名或 fallback 原因，如 SameShape、AlignedSlice、Regroup、AliasSnapshot、RealPackedConsumer、UnprovedOffset；不是任意 C++ 文本。

OpResult 物化按原 op descriptor 发射，输入从其 CpuUses 读取；例如 add 不必再用 recipe 复制一份算术语义。Recipe 物化只用于已选的访问/表示重组。ReadValue 只能读取已支配当前 use 的结果/槽，不能把“读取自身”同时当作产生自身的 recipe；物化依赖与 recipe DAG 合并检查无环。同一 value 可因真实 packed 与元素消费者有两种必要表示，但每种表示在同一采样区域只生成一次。

consumer OpOperand 覆盖所有 op 语义读取；Publish 覆盖 boundary、state/output 等目标的类型转换。两者发生串联时共享同一已有快照，不再执行 producer。planner 必须完整分类一个 value 的全部 uses；只有无独立消费者且所有 use 已覆盖的 Pure producer 才能省去物化，不能留下“下游按元素、上游仍无用打包”。

### 9.2 recipe 的封闭定义

recipe 是无环数据 DAG，不保存 C++ lambda/表达式字符串。子节点通过 CpuRecipeId 引用；Value 叶子只能引用当前 program 中可见的既定 SSA 值或已绑定 slot。

| tag | payload | 输出元素的精确定义 |
| --- | --- | --- |
| ReadValue | snapshot:CpuSnapshotId、可选既定 OpResult 物化引用 | 读取该绑定的 sourceValue/slot；Elements 时按 row-major 下标读逻辑叶元素，Packed 时保留一次已存在整数值 |
| Create | 按外维下标排序的子 recipe[] | 第i个完整子数组来自第i项；与公共 arrayCreate 顺序一致 |
| Slice | base recipe、静态 bit 区间或原 bitOffset ValueId、输出总宽、OOB规则标识 | 读取覆盖目标元素的源位段；动态 offset 的原位宽截断必须保留，不能自创逐维 clamp |
| Repeat | block recipe、repeatCount | 输出第r块来自**同一快照**的 block，不能重复执行 block 的 producer |
| Concat | 从低位到高位的 segments[]，每段为 recipe+逻辑长度 | 根据目标 bit 偏移选择相交段；此顺序与 IR concat 的 operand 顺序相反 |
| Regroup | base recipe、sourceElementBits、destinationElementBits | 目标叶r的bit b来自逻辑位t=r*Ed+b，即源叶t/Es的bit t%Es；不生成总宽整数 |
| ConstantFill | 完整定宽叶常量、元素数量、proof | proof 是源 value/快照在该 capturePoint 恒为此值的证据引用；不能只因远端 producer 是constant就跨 mutable boundary 下结论 |
| PackedOnce | base recipe、总逻辑宽、capturePoint、scratchSlot | 在 guard 内、目标行循环前打包一次，后续只切片；这是显式 fallback，不是可重复展开的表达式 |

proof 采用 `ConstantProducer(CpuOpId)` 或 `ImmutableSnapshot(CpuSlotId,initialLiteral,noWriters)` 两种可由 verifier 重验的形式；证明过程的工作集/cache 不持久化。ReadValue、PackedOnce 是前置重构即必须覆盖的正确 fallback；S9 再补 Create/Slice/Repeat/Concat/Regroup/ConstantFill 的消除打包规则。

`referencedValues` 由 recipe payload/子节点求并集后排序去重，verifier 重算检查；它是分块存活分析必须使用的依赖。不能依旧仅分析旧 op.operands，然后让 recipe 越过 helper 引用已消失的局部值。来源值可被内联时，真实叶依赖仍必须完整。

例子：replayCause 的 source 为 `u1[352,11]`、target 为 `u11[352]`，Regroup 的 Es=1、Ed=11。第r行只读 source[r][0..10] 组11位，不在352行循环里反复构造3872位整数。无法按元素实现时，PackedOnce 在原 enable/事件 guard 内、352行循环外取得快照一次。mask、变化检测和写入优先级继续由 writes 执行，不被该 recipe 替代。

## 10. CpuCodegenPlan：函数、frame、初始化与 TU

代码组织是 CPU 专属需求，定义如下。helper 不再是分区属性，TU chunk 不再用随 kind 改变单位的 offset/count。

| 结构 | 必需字段与约束 |
| --- | --- |
| `CpuCodegenPlan` | functions[]、frames[]、translationUnits[]、initActions[]、dumpBindings[]；helper/unit 上限来自 artifact.options，不重复一套参数 |
| `CpuFunction` | CpuFunctionId、唯一生成名、kind+payload（下表）、frame?:CpuFrameId、estimatedLines |
| `CpuFrame` | CpuFrameId；owner=`Event/Output/General(supernode)/Init/Dump`；slots:CpuSlotId[]；sizeBytes/alignment |
| `CpuTranslationUnit` | fileStem；按发射顺序的 CpuFunctionId[]；estimatedLines。每个函数恰属一个 TU；声明头由函数签名和 slot/type 计划确定 |
| `CpuInitAction` | 下表 tagged payload；有序执行，切块不重排 |
| `CpuDumpBinding` | source=`InputId/OutputId/StateId/DeclProvenanceSlice或CpuSlotId`；logicalType；规范 bit 范围；最终 slot/use 读取绑定；displayName/origin |

函数 payload 的范围一律为半开区间 `[begin,end)`，下表明确每种区间索引哪张表：

| Function kind | payload 与范围单位 |
| --- | --- |
| CoreDriver | role=`Init/Eval/Input/Event/General/LargeSink/Publish/Output/Dump`；需要切块的 role 持有有序 child FunctionId[]。Eval 的六阶段顺序由固定协议生成，不另存 task list |
| EventChunk | eventOrder 的 op ordinal 区间 |
| GeneralScan | general 的超节点 ordinal 区间；只扫描/门控，不复制超节点成员 |
| SupernodeDriver | supernodeId；按执行顺序的 helper FunctionId[] |
| SupernodeChunk | supernodeId；其 ops 的 ordinal 区间 |
| LargeSinkChunk | writes.largeOrder 的 entry ordinal 区间 |
| OutputChunk | outputOrder 的 op ordinal 区间 |
| InitChunk | initActions 的 action ordinal 区间 |
| DumpChunk | dumpBindings 的 binding ordinal 区间 |

每个 stream 的 chunks 无重叠、无遗漏且按原顺序调用。为 TU 上限拆分超大 supernode 时直接分配 helper 函数到不同 TU；不再用 SupernodePart 的 count 暗指 partIndex，也不由 emitter 重新算一次 part ranges。

CpuFrame 由**实际 recipe 依赖**跨函数的存活分析生成；数组只分配需要的一次快照，所有 helpers 通过引用/调用方缓冲访问同一 frame。不能把跨 helper 的 state.readArray 变成重读当前 state，不能用返回大数组的 helper 替代 frame。局部到 frame 的提升只改变 CpuSlot.home，不改变 sourceValue/capturePoint。

| InitAction tag | payload/顺序 |
| --- | --- |
| ResetRuntime | 对照 storage 的固定运行时槽初始化；先于读取这些槽 |
| StateStep | 源 InitRecord ordinal + step ordinal；按原 init 序列执行，不拷贝第二份 InitStep 内容 |
| PreloadSnapshot | slotId、typed literal；仅证明恒定的 boundary 初值 |
| EventHistory | CpuEventId、historySlot；初值来自 detector.prevInit |
| SyncNext | NextBuffer 当前状态→Next镜像；所有状态初值生效后执行 |
| SeedActivation | 精确置位所有 Data 超节点的 Current 位；清 Next 与 padding |

dumpBindings 用于 dump/FST/来源查看，需要展示的内容固定为 inputs、outputs、具名 stores/声明关联；没有 debug consumer 时可为空。FST 压缩器、文件句柄、perf 计数器本身仍归固定 runtime 支持库，不建立通用 IR 数据结构。

## 11. 执行协议与各种顺序的唯一来源

CPU ST 固定采用以下协议；它属于 backend 实现契约，不伪装成每份模型都不同的 NUMA/task 数据：

```text
eval:
    清 OncePerEval sampled 标志，准备本次 timeslot 锁存
    Input
    for round = 1..maxSettleRounds:
        Event
        General          # 固定超节点 ordinal 扫描
        LargeSink
        Publish
        if 无下一轮活动与必需的收敛工作: break
    未收敛则报错
    Output               # 包括应执行的 timeslot 调用与延后写回
```

| 必须保留的顺序 | 唯一权威来源 |
| --- | --- |
| 阶段、轮次、返回时机 | 上述 CPU ST 固定协议 + maxSettleRounds |
| 区域内先定义后使用 | CpuPartitionPlan 的规范 op 顺序；LargeSink 数据从预采样值取得 |
| General 扫描与本轮/下轮活动 | general ordinal；向尚未经过节点的传播可进 Current，必须下一轮可见的 state commit/已扫描目标进入 Next；不能吞掉 pPublish 新唤醒 |
| 同状态写覆盖 | 源 effectOrdinal；writes 只提供可执行索引，不再发明 priority |
| 事件脉冲与历史更新 | edgeDet 语义 + event bit/history binding |
| 外部调用、随机次数、timeslot | 源调用语义 + CpuEffectExecution；recipe 只读结果 |
| 快照可见性 | CpuValuePlan 的 capturePoint、binding、slot 和 borrowUntil |
| helper/函数/TU | CpuCodegenPlan；只改变代码位置，不能改变以上语义 |

输出门控、large-state 净变化、event-free latch、初次 eval 等现有行为都须在对应数据或固定协议中明示保留。不能因为删除 task 表，就改成每个 op 每轮无条件执行、丢事件或提前终止。

## 12. 生产流程、冻结点和 S9 接口

| 顺序 | 工作与输出 | 此后不能再暗改的决定 |
| --- | --- | --- |
| A | GRH→SimModel；共享定义校验、whole simplify；S9 的 array-normalize whole 在此接入 | CPU 不能回写源模型；语义变化产生新 sourceStamp |
| CPU0 | `cpu.st.lower`：建立独立 CpuProgram；选择 statePolicies；事件/输出/timeslot 降低、phase 归属 | 源 I/O/S/F/Init 只读；所有 CPU compute/effect 使用本地 IDs |
| CPU1 | phase simplify；S9 的 array-normalize phase 在此接入；maskedOr 恢复 | phase scope 不跨快照；CPU op 不泄漏回源模型 |
| CPU2 | 建/合并 General 分区、按真实边界 clone pure compute，修复本地 IDs/顺序，再冻结 program 和 partitions | 后面不再改 op/value/phase/超节点 ordinal；修改就使后续全部结果失效重建 |
| CPU3 | 规划主要 named stores、事件/位绑定、写入采样和 activation 表 | 状态策略、boundary 身份及写语义确定；临时槽的 home 可稍后确定 |
| CPU4 | `cpu.st.plan-values` 建立完整 scalar/array fallback；S9 的 **`cpu.st.plan-array-access` 在此变换同一 CpuValuePlan** | 所有 uses 的实际依赖、访问方式、alias 与 capturePoint 确定；不修改 G/partition/main stores |
| CPU5 | 依据 value cost 和 helper/unit 上限决定所有函数切块，包括超大 supernode 的 helper 拆分 | op→函数范围冻结；不能在 TU 装箱或 emit 时临时再切函数 |
| CPU6 | 依据实际 recipe 依赖分配 local/frame/runtime scratch，完成 slot.home 与 frame 布局 | 不得重读 producer 来节省 frame；布局完成 |
| CPU7 | TU 装箱、init/dump 绑定收口、全 artifact verifier，生成 CpuStArtifact | 必需表完整；无旧 stage/complete bool |
| Emit | `cpu.st.emit-cpp` 只读消费 source+artifact | 不重新推导 viewRoots、frameFields、写优先级或 helper ranges |

initActions 与 dumpBindings 的逻辑 stream 在 CPU5 切块前建立，CPU7 仅填完物理/调试绑定，不改变范围长度和顺序。CPU5 若估算需新 materialization，必须回到 CPU4 显式重建，再一次性规划；不能在隐藏 emitter cache 中补决策。

数组 pass 的目标接口据此定为：共享数组规范化算法分别作用于 A 的源图和 CPU1 的 lowered 图；仿真适配器提供 effect/phase 安全规则。CPU4 的数组 pass 输出 `CpuValuePlan` 内的 recipe/materialization 增量，CPU5/CPU6/Emit 共同消费。**旧 C5.5 编号、CpuMappingStage::ArrayAccessPlan、cpu.st.v2 mapping schema 不采用。** S9 不重新设计泛化框架，也不新增 array pack/unpack 语义 op。

## 13. 持久化、失效和迁移

### 13.1 只持久化可解释的完整对象

| 类别 | 是否持久化 | 恢复/失效规则 |
| --- | --- | --- |
| 公共 descriptor/求值代码 | 否，记录契约 fingerprint | 工具版本契约不匹配则拒绝；不是把代码指针写入 JSON |
| SimModel | 是，独立 semantic checkpoint | source semantic mutation 增 revision；metadata 单独计数 |
| CpuProgram + 完整 typed plans | 是，一个完整 cpuSt artifact | 同时绑定 sourceStamp、规范摘要、options、targetAbi、programRevision；不得跨源图重用 IDs |
| partition 候选、拓扑工作集、view追踪cache、proof搜索、反向use索引 | 否，编译器临时分析 | 相关图/配置变更即丢弃；完整结果只保存上述明确数据 |
| 运行时状态、活动位、event历史、sampled值、frame内容 | 不写入编译 IR artifact | artifact 仅定义其布局/初始化；运行中内容是 simulator instance，不混为编译 checkpoint |

CPU 计划构建中的局部变化按生产依赖丢弃后续表；完成 artifact 不允许原地零散修改。改变源语义、CPU lowering、分区、ABI、布局策略或访问规则后重建 artifact；纯 metadata 变化只重新绑定 debug/dump 并更新相应版本。source clone/compact 产生新的身份或显式全量重映射；不得仅改 stamp 就声称旧 plan 可用。

### 13.2 明确选择的新格式

目标编译 checkpoint 使用 `wolvrix.grhsim.v4`，根对象是 `model` 和可选 **`cpuSt`**；不保留 `mappings[]`。model 可单独读取；cpuSt 存在即必须完整。共享/core 契约 fingerprint 升为 `wolvrix.grhsim.core.v4`，包含 assign/assignAs 分离、公共选择 op 和新边界。CPU maskedOr 的计算契约未改变时仍使用其现有方言 fingerprint，不把 plan 格式版本当作 op 版本。

CPU 产物使用新的 **`cpu.st.artifact.v1`** tag，与旧 `cpu.st.v1` / 候选 `cpu.st.v2` mapping schema 区分。S9 已被本版本定义的 recipe tag 预留明确契约，前置阶段可只生产正确 fallback；加载器拒绝未知 tag、缺失绑定、循环 recipe、过期 stamp。将来真实改变已定义契约再升级，不预设无限扩展的插件 payload。

旧 v3/mapping 产物不自动灌入空计划、不靠兼容枚举伪装完成；从原 SV/GRH 重生。历史 ROB S8 产物原样留存，旧 binary 仍用于对照。本轮只是选择目标版本，**现有源码/生成物仍是原格式**。

## 14. 旧结构去向与实施单元

### 14.1 删除/迁移对照

| 旧定义/行为 | 目标去向 |
| --- | --- |
| 独立 core.compute 注册、computeOpName 手工映射、两份 shape 校验/位求值 | 公共 ComputeKind/OpDescriptor + 图适配器；不以别名包装保留双维护 |
| StateObject.storeClass、SimOp.phase | CpuStatePolicy、CpuOp.phase；源语义明确旧值/NBA/事件/效果顺序 |
| BackendMapping、CpuBackendMapping、optional cpu、complete、CpuMappingStage/rank 与 legacy值 | 删除；CpuStArtifact 仅完整产物，CpuStBuilder 仅临时编译对象 |
| CpuExecution、CpuTaskId、CpuScheduledTask、CpuCoreSchedule、CpuNumaSchedule、waitsFor | 删除；需要调试时直接打印固定协议/分区顺序，不生成另一份可编辑计划 |
| CpuSchedulePlan | 删除混合壳；fanout/event/timeslot→activation；memWritePlan→writes |
| CpuPartitionTree 的 root/phase/node/EmitFunction、helperChunks/supernodeRange | 持久化只保留 CpuPartitionPlan；node 分析留编译期；helper/range→codegen.functions |
| CpuStoreField.state/value/aux | CpuSlot 的 typed binding + home；事件/任务 bit binding 单独明确定义 |
| emitter.computeFrameFields/buildViewRoots/私有表示选择缓存 | 计算迁到 values/codegen planner；emitter 只做选择分支的文本发射 |
| CpuEmitChunk.offset/count、SupernodePart 的隐式范围重算 | typed CpuFunction payload；范围单位唯一；TU只存 FunctionId |
| commitSemanticMicroMutation 的 CPU 例外 | CPU 只改自己的 program；删除源模型为保 mapping 开的例外通路 |
| core.compute.expr | 删除定义/生产与遗留处理；旧产物拒绝并重生 |

### 14.2 实施顺序与交付

| 单元 | 具体交付 | 验收 |
| --- | --- | --- |
| R0 | 已有事实审计 + 本文目标定义 | 文档完成；不代表代码完成 |
| R1 公共定义 | 建立 ir/ 公共库与生成入口；全部公共 compute/type/attribute 迁移；assignAs 不再丢失；bitSelect/prioritySelect 提升；修 sliceArray shape 漂移 | 两容器一致正/负例、常量位语义与X/Z；共有契约不留两份实现 |
| R2 CPU lowered program | 引入独立 CPU IDs/CpuProgram；搬迁 store policy、phase、edge/timeslot/调用执行方式；去掉源图 CPU micro-mutation | 旧值、事件历史、多 writer、随机/DPI次数等价；源模型没有 CPU 字段/头文件依赖 |
| R3 CPU 计划与发射 | 按 §6–§10 迁移现有有效表，建立 fallback ValuePlan、frame/function/TU 共同消费；删 task/generic mapping/伪分区；落地新 JSON/verifier | 所有 emitter 实现决定有唯一计划/协议来源；缺失/篡改/过期拒绝，强制小 helper/TU 执行等价 |
| R4 封板与 S9 接入 | 用 Make 门禁和 ROB 全输出/同 trace A/B 验收前置版本；钉死 CPU4 recipe 扩展接口；同步正式规范与脚本入口 | S8→前置单独报告；此时才将两数组 pass 从“未开始”改为实施，不提前宣称收益 |

所有编译、测试、安装、Python workflow 必须走项目 Makefile；缺 target 先补，日志/产物放 ptmp。纯文档检查不需要构建。

正确性门禁包含 shared op/type 正负例、完整 shape、同位宽状态视图、copy/compact/JSON/失效、四态边界、事件电平/派生时钟、全部状态写族、mask/alias/多写优先级、event-free 收敛、随机与 DPI 计数、timeslot 与 output deferred write、实际执行的强制小 helper/TU；不能只有结构文本测试。ROB 从固定 aggregate-all SV 重生，新旧 GrhSIM 全输出零排除对照，gsim 的历史排除不扩张。

性能基线分两步：先 S8→本文架构版本，再架构版本→S9 数组优化。所有历史哈希/trace/计时口径见 [S9 §7](stage-09-array-normalize-mapping.md#7-验证门禁与豁免)。结构清理可能改变 C++ 形态与构建成本，收益与风险由各阶段实测，不把删除未消费 task 表当作已证明的运行加速。

当前尚需实测的是分区/物化的成本阈值、scratch 峰值和速度；**保留哪些 op、哪些表、每张表表示什么、CPU 字段归谁，已按本文选定，不再列为架构待定项。**
