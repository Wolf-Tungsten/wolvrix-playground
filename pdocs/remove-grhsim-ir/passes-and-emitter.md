# Pass 顺序与 C++ emitter

本文件按本轮指定的七步流程重写，是其他规划的职责依据。所有 transform 复用现有 PassManager，在同一张已经展开的 GRH top Graph 上工作；“GrhSIM IR”仅表示包含 grhsim 方言 op 的 GRH 图，不是独立 GrhSimModel，也不产生第二套实体。

## 1. 按指定顺序执行

```text
现有 GRH 前端变换与原 simplify
  → grh-to-grhsim
      # 只按需转换 op；没有任何虚拟分区
  → 按需插入优化 pass
      # grhsim-simplify、grhsim-pack-bit-registers、grhsim-recover-masked-or
      # 仍是无分区大图；等价 edge-detect 可以合并
  → grhsim-split-event-and-output
      # 首次提取并建立 general / event / output
  → grhsim-split-nonsink-and-sink
      # 仅将 general 拆成 nonsink / small-sink / large-sink
  → grhsim-partition-nonsink
      # 在 nonsink 内做活动度切图
  → grhsim-partition-sink
      # 在 small-sink / large-sink 内按时钟、门控、优先级分区
      # 发布调度顺序 SinkSchedule：首个跨 pass 的额外分析产物
  → emit/grhsim/cpu-st-cpp.cpp
      # 生成仿真程序；内部处理布局、访问、激活、函数与 chunk
```

主流程按上面的七步执行，不增加 prepare、CPU planner 或某个单独的 lower 阶段。无分区优化是第二步的可配置插入位置，不强制固定一串优化调用；打包等变换产生新机会时，可以再次调用 grhsim-simplify。若活动度切图后需要化简 clone，也可在 partition-nonsink 与 partition-sink 之间显式插入同一 grhsim-simplify，此时只在完整叶分区内工作。

verify/store 可以放在每个完成步骤之后。它们不替代上述步骤；阶段是否完成由图的阶段元信息及实际内容决定，不通过临时 session slot 猜测。单独阶段不用 lower 命名；从 SV 到 C++ 才是完整的编译转换过程。

| 步骤 | 必需输入 | 提交到 GRH 的结果 | 跨 pass 的额外数据 |
| --- | --- | --- | --- |
| grh-to-grhsim | 已展开、已验证的基础 grh | 方言 op、显式 fire、调用语义；无分区 | 无 |
| 按需优化 | 无分区的 GrhSIM 形态 | 优化后的无分区大图 | 无 |
| grhsim-split-event-and-output | 优化后的无分区图 | event/general/output 归属、实际锥提取及重接 | 无 |
| grhsim-split-nonsink-and-sink | 已完成前三个区域提取 | general 的三个子区域、状态分类 | 无 |
| grhsim-partition-nonsink | general 已拆分 | nonsink 活动度分区、层次及合法 clone | 无 |
| grhsim-partition-sink | nonsink 已分区，两类 sink 待细分 | sink 分区及其归属 | **SinkSchedule** |
| grhsim-cpu-st-cpp | 完成分区的图与有效 SinkSchedule | 不改图；输出 C++ 与构建清单 | 仅本次 emit 的私有便利数据 |

逐步验收图的形态：步骤 1、2 没有任何 grhsim.partition 属性，不能提前标 general；步骤 3 首次产生 general/event/output；步骤 4 只细分 general；步骤 5 只切 nonsink；步骤 6 细分两类 sink 并首次发布额外调度结构。步骤 7 只读取完成的图与调度，不能补做事件/输出提取或任何分区。所有状态、读口、计算和写口一直留在同一个 top Graph。

## 2. grh-to-grhsim：转换 op，保持无分区

此 pass 按需替换原图中的操作，复用公共计算、数组、端口、状态声明/读口、DPI import 和现有实体引用。转换覆盖以下操作，不能只处理写口而遗漏调用：

| 原操作 | 转换结果 | 必须保留的含义 |
| --- | --- | --- |
| 原时钟事件 operands / eventEdge | grhsim.edge-detect；多事件以 1-bit OR 合成 fire | edge、历史初值、每 round 采样/历史更新规则 |
| 基础 grh 六类写口 | grhsim.write / writeMask / writeArray / writeArrayMask / fill / latchWrite | 状态目标、完整类型、索引/掩码/fill 几何、writerOrder；时钟写口首 operand 为 fire |
| kSystemTask | grhsim.system-task | fire、callCond、参数、任务名、procKind、hasTiming、effect |
| kSystemFunction | grhsim.system-function | 参数与完整结果类型；纯函数、random/time 等分别定义 effect 与采样身份 |
| kDpicCall | grhsim.dpi-call | fire、callCond、原 import 引用、return/input/output/inout ABI、结果保持与调用顺序 |

无事件 task/DPI 的 fire 为常量 1；latchWrite 保留独立的电平写契约。需要两态投影时，通过显式逻辑域选项实际更新类型、常量和 InitSpec。原 GRH 写口/调用不添加 TriggerSpec 或 pulse 模式。

例如，同一张无分区图中可以先出现两个等价检测器：

```text
%f0 = grhsim.edge-detect(%clk) {edge=posedge, prevInit=0}
%f1 = grhsim.edge-detect(%clk) {edge=posedge, prevInit=0}
grhsim.write @q(%f0, %en, %d) {writerOrder=0}
grhsim.system-task(%f1, %cond, %q) {name=display}
```

后续全图 simplify 可将 %f0/%f1 合并成一个检测器，两个消费者共享结果与一份历史。转换器也可以局部复用检测器，但转换正确性不依赖其完成全局 CSE。

转换完成时，所有可执行 op 都没有 grhsim.partition 属性，结果是平整的无分区大图。系统任务、系统函数和 DPI 必须在此完成对应方言 op 的转换，不能等分区或 emit 时补齐。这里不提取 Event/Output、不复制其计算锥、不创建 monitor/strobe 的 output-end 历史、不分类 small/large，也不发布调度或 CPU 计划。writerOrder、InitSpec、来源、采样语义与 converted 阶段信息保存在统一 GRH 中。

## 3. 无分区优化：独立 grhsim-simplify

保留现有 GRH simplify；grhsim-simplify 有自己的驱动与改写策略，可复用公共算子的求值、类型几何等基础工具。它没有 role/phase 参数：

- 无分区时，全图是一个改写范围。执行 constant-fold、canonicalize、CSE、DCE、used-bits、bitwise/mux 和方言规则；共享状态的等价合并/窄化在此维护全部读写、初值及声明引用。
- 有分区时，每个完整叶 PartitionKey 是一个改写范围。CSE、常量池、alias 追溯和队列不跨 owner，不能将为了分区复制的计算合回去。保持跨界输出、完整类型与采样/effect 语义。
- 部分归属或非法阶段报错，不能把缺少 owner 的 op 当作允许跨区改写的入口。

edge-detect 使用专门的等价规则：同输入、同 edge、同 prevInit、同完整类型与采样/历史更新契约，且处于相同改写范围时，可以共享结果及一次历史更新。也就是说，上一步示例中的 %f0/%f1 在这个无分区阶段应允许被合并，消费者重接到同一 fire，每 round 只更新一次历史。不同边沿、初值或采样范围不合并；不能人为给每个检测器一个永不相同的 sample ID 来阻断共享。DPI、random、system-task 的 effect 与采样身份分别处理，不套用检测器的合并规则。

其余保留优化也在无分区阶段适配：

| Pass | 处理与默认配置 |
| --- | --- |
| grhsim-pack-bit-registers | 当前生产默认开启；按新写口的 fire、enable/mask、类型和覆盖关系打包，维护初值、读写与全部声明映射 |
| grhsim-recover-masked-or | 当前生产默认开启；在无分区图中匹配，不再要求旧 split-phases 的 phase 属性 |
| grhsim-comb-pack | 当前生产默认关闭；删除实现、注册、构建引用、开关、报表及专用 fixture，不进入新管线 |

默认值核对入口为 [Makefile](../../Makefile) 与 [生产脚本](../../scripts/wolvrix_xs_grhsim.py)。reemit 的可选打包配置不替代生产默认值。bitSelect/prioritySelect 的定义与改写属于 grhsim 方言，不加入基础 grh 算子集。

## 4. grhsim-split-event-and-output：第一次产生分区

**Event 与 Output 就在本 pass 中提取。** 输入是优化后的平整大图，结果是同一 Graph 中三个区域，不是新模块。

| 区域 | 提取根与处理 |
| --- | --- |
| event | 以 edge-detect 的输入为根反向提取事件计算锥，包含状态 read、readArray 及其地址锥；已有检测器本身归 event |
| output | 以 top 输出绑定值和 monitor/strobe 的 callCond/参数为根提取读取/计算锥，重接输出与任务；建立必要的粘滞触发、变化历史与 output-end 写回 |
| general | 保留常规写口、调用及其仍有用途的计算；清除提取后无用途的纯死锥 |

先收集两类根及其用途，再决定移动或复制。只供一个区域使用的普通 op 直接归该区域；跨区域共享的普通计算/读口按需 clone。每个源 op 在每个目标区域至多提取一个副本；声明和初值继续共享，不复制状态对象。

普通状态读在目标区域重新求值，保证 Output 读取收敛后的状态。fire 是允许跨区消费的显式结果，Output 提取遇到它时停止，不复制检测器及历史。DPI/随机等结果按既有 effect/sample identity 使用合法的采样依赖；不能为闭包而增加一次调用。

R4 当前实现采用单个原调用与 held sample，图中记录 effectPolicy。2026-10-25 用户已批准消除冻结 dpi_bit_abi 的旧 Output 重复调用，并保留原图独立调用顺序；比较器仅接受已确认的精确差异，不扩大到触发、调用增减或参数/结果变化。原日志和严格比较继续保留，见 [语义决定](20261025-single-call-decision.md)和 [基线记录](baseline-and-capabilities.md#r4r5-的旧-dpi-行为差异)。

提交时每个可执行 op 恰有 event/general/output 中的一个 owner；空区域无须合成无用 op。转换与前面的优化阶段绝不预先标记 general。锥提取、跨区依赖及属性示例见 [虚拟分区](virtual-partitions.md)。

## 5. grhsim-split-nonsink-and-sink：只拆 general

保留 event/output，将 general 拆为 nonsink、small-sink、large-sink：

1. 按状态总逻辑字节数分类，沿用 ceil(totalWidth/8) 与 memMinBytes 的比较，默认阈值 64 bytes；小数组和大标量都支持。同一状态的所有普通 writer 使用同一策略。
2. 以 writer 的 fire/enable/index/data/mask 为根，仅当全部用途属于同一个 writer 时，将可私有化的纯参数锥归入对应 sink；不同 writer 之间的共享计算、一般副作用和不能私有化的结果归 nonsink，通过同图 value 连接。这里形成三个粗区域，最终 clock/gate/priority 分组在 partition-sink 中完成。
3. 写入 grhsim.partition 与状态策略属性。readArray 与地址/数据仍在同一个 Graph，不为分区转换为 whole-read + sliceArray。

区域归属不等于运行时阶段：small-sink 在 P_general 求值并写 next；large-sink 的参数也在 P_general 采样，P_large_sink 只提交快照。这里不分 clock/gate 组，不产出 SinkSchedule、物理布局、激活表或 chunk。

## 6. grhsim-partition-nonsink：活动度切图

只对 nonsink 做基于活动度的 node/超节点切图、合并与多级归属。带地址 read 可以和地址、数据计算同分区；不建立子 Graph、Instance 或跨层端口。

真实边界确定后，可按保留的生产开关执行一轮 boundary clone；新 op/value 设置目标 owner 与新 symbol，并维护来源和采样约束。需要进一步化简时，显式调用按叶分区工作的 grhsim-simplify。

本 pass 的结果是 GRH 属性与真实 clone。候选、拓扑、成本和成员索引是本次调用内的临时数据；函数行数、chunk 与 TU 参数不参与切图，也不发布跨 pass 的活动度计划对象。

## 7. grhsim-partition-sink：分区并标注顺序

分别在 small-sink、large-sink 内，按 fire/时钟签名、enable/门控及 writerOrder 建立 sink 分区。在图上提交归属后，向现有 SessionStore 发布 **SinkSchedule**。

SinkSchedule 仅记录 sink 分区的 guard 引用、P_general 中的参数采样/small-next 有序 run、P_large_sink 中的有序提交 run，以及所需 nonsink 依赖。writer 的 operands、类型、状态目标和归属仍只定义在 GRH 中。完整契约见 [架构](architecture.md#4-sinkschedule-与-emitter-私有数据)。

例如同一状态原顺序为 A(clock0,0)、B(clock1,1)、C(clock0,2)，即使 A/C 属于同一时钟分区，也要保持 A→B→C 的覆盖顺序。一个分区可以在有序 run 中出现多次；缓存同一 gate 的结果不能改变提交顺序。

如果此前粗 sink 区域内部的 simplify 合并了纯计算，本步按最终分组将需要私有化的纯锥复制、重接到各组，并在发布调度前校验唯一 owner 和依赖。不能复制 effect，不能要求 simplify 在粗区域内预知尚未形成的时钟/优先级分组，也不为此恢复 role 参数。

这是第一个跨 pass 保留的额外分析结构。它不承载全体 nonsink 的执行图、Output 历史计划、物理 offset、访问配方、函数或 chunk。Output 的 output-end 提交遵守图中语义与固定六段协议，由 emitter 生成。

调度在最终 revision 校验后原子发布；缺失、失败或过期时不可消费。图或 sink 配置变化后重新运行本 pass；重载已分区 checkpoint 时复用属性、重建当前实例的调度。emitter 不补做分区或重新选择 writer 优先级。

## 8. emit/grhsim/cpu-st-cpp.cpp

实现文件固定为 **wolvrix/lib/emit/grhsim/cpu-st-cpp.cpp**，公开 ID 为 grhsim-cpu-st-cpp，复用现有 Emit 接口与 EmitOptions::session。输入是完成分区的 GRH 与有效 SinkSchedule。

nonsink 的执行/激活单元取 `[general,nonsink,supernodeKey]`；末级 `nodeKey` 约束局部化简，不额外生成一次活动度调度。emitter 在不改属性的前提下按该前缀收集成员、建立拓扑和边界。manifest 的 `nonsink_functions` 记录超节点前缀及完整 op symbol 集合；`virtual_partition_count` 仍按完整叶 owner 计数。chunk 在函数内进一步拆分。

发射器内部按需建立便利结构，直接引用原 GRH 实体：

- 状态/输入/边界存储、事件历史/脉冲、时隙触发、初始化及物理布局；
- nonsink 依赖与激活路由、writer 参数快照、数组访问/别名/局部寿命；
- 六段调度、各区域/分区、调用、FST/profile、helper 和源码清单；
- 全部函数的行数计数、chunkFrame、chunk/dispatcher 与 TU 组织。

这些数据只服务本次 emit，可按需放在 emitter 私有 scratchpad，不能成为新的公开 planning pass 或可编辑执行 IR。固定六段、small current/next、large in-place、采样/调用和数组契约见 [六段与数组](six-phase-and-arrays.md)。

**chunk 只是 emitter 参数控制的函数拆分。** max-function-lines 限制单个生成函数的最终定义行数，对所有生成函数生效，包括 init、eval、六段包装、Event/Output、nonsink、两类 sink、DPI/任务、trace/profile、helper 和 dispatcher。最终计数包含函数支架、guard 与 chunk 调用；超限则在合法控制流边界拆分，dispatcher 超限也继续拆分，无法满足的预算明确报错。不能以 op 数、语句数或 TU 拆分代替实际函数行数限制。

跨 chunk 活跃的局部变量及必要控制状态放入 chunkFrame，以引用/指针传递；其余值通常保留 local。单个不可分语句/guard 本身可满足预算、但其私有声明导致超限时，也允许将这组局部值 spill 到同一源函数的 frame，并保持原局部初值和寿命；不能反复包裹不减少声明的 helper。数组使用调用方缓冲，不引入大型返回值复制。拆分保持 guard、循环、early return、一次性采样/调用、写覆盖与历史提交顺序。

named store 与 chunkFrame 使用不同的布局契约：store 的每个语义字段直接作为结构成员，chunkFrame 只保存跨 chunk 的局部值，字段很多时才按完整 C++ 类型组织索引数组。两者的 C++ 文本都由值初始化结构 writer 产生：省略冗余的字段 `{}`，保留非零初值，结构声明显式 defaulted 默认构造函数，所有实例使用 `{}` 值初始化。这样不为大图每个零标量产生一项隐式构造初始化，也避免在每个使用点展开庞大的聚合初始化列表；String/数组的正常构造、初值与重复 init 必须经过执行测试，不能用 memset 代替非平凡对象构造。该布局细节不进入 GRH 或跨 pass 调度数据。

General 固定先按 ordinal 调度 nonsink 函数，再执行 writer 批次；活动度 helper 顺序覆盖连续 24 个 bitmap byte，writer/commit helper 各覆盖至多 128 个连续 SinkSchedule run。helper 可以按实际行数拆 chunk，但不能把全图计算及局部值塞进 `pGeneral` 再切分。`pGeneral` 与 `pLargeSink` 使用固定大小的有序调用循环，既不生成全图 frame，也不产生无状态的 phase chunk。纯调用拆分没有跨块局部值及 return 控制时，不生成空 frame 或 frame 参数。活动度逐 bit 读取实时 bitmap，跨 batch 的后继激活仍在当前轮执行。

同一虚拟分区可生成多个 chunk，init 等非分区函数也能拆 chunk。chunk 不增加 grhsim.partition，不形成激活边界；chunkFrame 不替代状态、nonsink boundary 或 writer 采样快照。改变行数/TU 选项只重新 emit，不重做虚拟分区、不使有效 SinkSchedule 失效。

## 9. 文件位置与实现验收

以下路径相对 wolvrix/：

| 职责 | 目标位置 |
| --- | --- |
| op 转换 | lib/transform/grhsim/grh-to-grhsim.cpp |
| 独立化简与保留优化 | lib/transform/grhsim/{simplify,pack-bit-registers,recover-masked-or}.cpp |
| 两次区域拆分 | lib/transform/grhsim/{split-event-and-output,split-nonsink-and-sink}.cpp |
| 两类分区 | lib/transform/grhsim/{partition-nonsink,partition-sink}.cpp |
| SinkSchedule 公共契约 | include/transform/grhsim/sink-schedule.hpp |
| C++ 发射 | lib/emit/grhsim/cpu-st-cpp.cpp；头文件 include/emit/grhsim/cpu-st-cpp.hpp，私有 helper 按需拆文件 |

逐步检查：转换/全图优化之后没有分区；第一次 split 后只有三区域；第二次 split 只改变 general；活动度切图只细分 nonsink；sink pass 的顺序覆盖交错时钟 writer；emit 改变 chunk 参数后图与调度不变，所有函数实际行数达标且执行结果相同。

四个 R4 pass 已实现，实际选项和调度 API 见 [正式变换规范](../../wolvrix/docs/transform/grhsim-transforms.md)，完成情况见 [R4 验收](r4-validation.md)。R5/R6 已有在途代码与局部执行证据，整体兼容、整机和性能门禁尚未完成；本次重写不把它们标为验收通过。

旧 edge-detect/写口/调用转换归 grh-to-grhsim；旧事件/输出锥处理归 split-event-and-output；状态分类归 split-nonsink-and-sink；活动度切图归 partition-nonsink；sink 分组/顺序归 partition-sink；其余有效布局、访问、激活与代码组织归 emitter。删除独立 IR/JSON/registry/PassManager、comb-pack 和退役的 NUMA/core/task 镜像，不保留隐藏旧路线。
