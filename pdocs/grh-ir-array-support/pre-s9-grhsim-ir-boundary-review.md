# S9 前置 — GrhSIM IR 定义与 CPU 计划边界审查

- 日期：2026-10-23。
- 状态：2026-10-23 的代码事实审计存档；其后提出的 [独立目标模型](pre-s9-grhsim-target-model.md) 已被 [移除独立 GrhSIM IR 计划](../remove-grhsim-ir/README.md) 替代。下文容器和计划边界的判断是当时分析，不是当前实施指令。
- 当前顺序、保留/删除项与接口以新计划为准，再推进 [S9 数组优化](stage-09-array-normalize-mapping.md)。本文保留重复定义、现有消费关系等历史证据；不代表新架构已经验收。
- 本轮范围：读取定义、lowering、verifier、pass、CPU planner 和 emitter，整理实际生产/消费关系；没有运行新测试或性能实验。

## 1. 判断

用户提出的方向基本成立，但需要区分三个结论：

1. **通用算子定义重复，应先收敛。** add、concat、sliceArray、arrayCreate 等不应在 GRH 和 GrhSIM 中各维护一份独立的语义契约、类型规则和求值实现。GrhSIM 应复用公共 IR 定义，仅增加仿真所需内容。
2. **通用 task 调度模型没有成为当前 CPU ST 的执行顺序来源。** 当前 NUMA/core/task/waitsFor 表由分区树确定性生成，verifier 要求与重新生成结果完全相同，emitter 不读取这张 task 表，而是直接生成固定六阶段调用。
3. **不能因此删掉全部 mapping 数据。** 分区树、物理类型/具名存储、激活表、写计划、helper/TU 计划都在生成代码时使用。它们是实际的 CPU 实现计划，只是被一个泛化的 mapping/schedule 外壳包在一起。

“最小扩展”首先指**共享定义和明确归属**。是否复用同一个 graph 容器、是否保留独立仿真图，是下一层问题；不能把两套算子定义的重复，直接等同于“lowering 后拥有一份可独立优化的图就是错误”。

## 2. op 与类型：重复在哪里，哪些扩展必要

### 2.1 当前共有 op 是手工映射和分别维护

[GRH OperationKind](../../wolvrix/include/core/grh.hpp#L24) 定义 kAdd、kConcat、kArrayCreate、kSliceArray 等；[GrhSIM core 注册](../../wolvrix/lib/grhsim/dialect/core.cpp#L12) 再列出 core.compute.add、concat、arrayCreate、sliceArray 等名字。

[computeOpName](../../wolvrix/lib/grhsim/convert/grh_to_grhsim.cpp#L49) 手写对应关系，例如：

```text
kAdd         → core.compute.add
kConcat      → core.compute.concat
kArrayCreate → core.compute.arrayCreate
kSliceArray  → core.compute.sliceArray
```

这几项本身没有新仿真语义。当前 [DialectRegistry](../../wolvrix/include/grhsim/dialect/registry.hpp) 主要登记名字/所属方言，不携带完整 arity、类型推导、shape 和参数契约；这些规则另写在构造器、verifier 和 pass 中。只把字符串注册表合并，不能解决定义重复。

类型也有共同部分：Logic/Real/String、width、signedness、shape。GrhSIM 额外显式携带 logic domain，这是有用的仿真信息；它不构成再手写一套 shape 算法的理由。

### 2.2 已观察到契约漂移

GRH 的 [kSliceArray 校验](../../wolvrix/lib/transform/verify.cpp#L699) 除了结果位宽，还要求结果 shape 等于 base.shape 去掉已索引前缀后的后缀。

GrhSIM 的 [sliceArray 校验](../../wolvrix/lib/grhsim/ir/verifier.cpp#L1329) 调用 indexedAccessGeometry 算出了 accessWidth 和 accessShape，但 [indexedAccessTypeMatches](../../wolvrix/lib/grhsim/ir/verifier.cpp#L348) 只检查 Logic 种类和 width，没有检查这个 shape。

例如：

```text
base : u9[4,8]
sliceArray(base,i) 的结果应为 u9[8]，总宽72

GRH：结果声明为无 shape 的 u72，会因 shape 不匹配而拒绝。
GrhSIM：该分支的类型检查仅要求总宽72，未校验剩余 [8]。
```

这是本轮静态代码核对发现的校验缺口，尚未新增 fixture 执行复现。状态读写允许同总宽不同 shape 是另一项已有设计，不能把 state 边界的宽松规则自动套到 sliceArray 的结果契约上。

另一项不能忽略的差异是 [assign lowering](../../wolvrix/lib/grhsim/convert/grh_to_grhsim.cpp#L87)：GRH 的 kAssign 和 kAssignAs 都映射成 core.compute.assign。GRH 分别表达同型改名与等总宽的类型重解释；共享定义时必须明确保留、区分或有意归一化这两种行为，不能逐名字机械替换。

常量求值也分别存在于 `lib/transform/const_fold.cpp` 和 [GrhSIM const-fold](../../wolvrix/lib/grhsim/pass/const_fold.cpp#L83)。可以共享算子的定宽位语义，但两态/四态、除零策略、折叠预算及 phase 内重写策略需要显式参数，不能直接认定整套 pass 可无条件合并。

### 2.3 已选定的定义边界

| 类别 | 例子 | 处理方向 |
| --- | --- | --- |
| 公共计算定义 | add、比较、mux、concat、arrayCreate、slice、replicate | 一份 OpKind/descriptor、参数/类型契约、shape 几何及可共享求值；两层用适配器访问自身实体 |
| 公共值类型 | Logic/Real/String、width、signedness、shape、domain | 一份 LogicalType 与几何规则；GRH 适配器默认 FourState，TwoState 由仿真转换显式选择 |
| 状态/接口归一化 | GRH 的 register/latch/端口 → I/O/S/Init/object refs | 保留有实质作用的仿真归一化；不要求继续复制公共计算定义 |
| 仿真扩展 | edgeDet、边沿历史、一次采样、多轮求稳、任务执行条件 | edgeDet 保留为 lowered 仿真原语；CPU 历史槽位、采样执行方式与求稳协议由 CPU 专属结构承载 |
| 纯计算组合扩展 | bitSelect、prioritySelect | 提升到公共 ComputeKind；完整契约见目标模型 §2.2，不再列为仿真专属 |
| CPU 专用组合 | cpu.compute.maskedOr | 留在 CPU 扩展或等价 lowering；其他后端必须支持、展开或明确拒绝 |
| 历史表达 | core.compute.expr | 删除定义与遗留处理，旧产物拒绝并提示重生 |

这里的“仿真扩展”不表示每项都需要新 op。例如分区归属可以是结构/注解，Init 可以是模型对象；先确定语义，再选表达。

公共 op 契约至少包含有序 operands/results、静态参数、对象访问/副作用、完整类型约束、shape 推导和位布局。arrayCreate 的例子必须继续满足：N 个同型 W-bit、shape S 的值组成 width=N×W、shape=[N]+S，result[i]=operand[i]。

共享 op 定义不要求把仿真器直接接到 ingest 的可变 GRH 图上。目标明确保留独立 SimModel，并由 CPU 建立独立 CpuProgram；不合并全部 graph 容器、ID 和生命周期。公共定义、仿真归一化与 CPU 扩展的完整白名单见 [目标模型 §2–§5](pre-s9-grhsim-target-model.md#2-公共定义只维护一次的内容)。

## 3. partition、mapping、schedule 的实际用途

### 3.1 分区正在使用，而且部分执行顺序已经放在分区中

CPU 的 partitionTree 是 CpuBackendMapping 的一部分；“分区有效、mapping 无效”不能直接作为数据结构上的划分。

[SixPhaseEmitter](../../wolvrix/lib/grhsim/backend/cpu_phase_emit.cpp#L597) 从分区树取得 General 超节点顺序、每个节点内的 op 列表及 Event/Output 的拓扑列表。C6 的 [packGeneralFunctions](../../wolvrix/lib/grhsim/backend/cpu_partition.cpp#L746) 又在分区属性中保存 helperChunks 和 supernodeRange。

所以当前分区同时承载：成员关系、活动度单元、部分 op 顺序，以及函数分块信息。后续应明确哪些属于分区、哪些属于代码生成计划，但不能删除这项实际能力。

### 3.2 mapping 内的实用数据

| 当前数据 | 实际消费者/用途 | 判断 |
| --- | --- | --- |
| partitionTree | emitter 提取超节点、op 顺序、函数区间；其他 planner 据此分析边界 | 保留分区能力，明确顺序归属 |
| dataLayout / namedStores | [emitter 构造](../../wolvrix/lib/grhsim/backend/cpu_phase_emit.cpp#L552)、类型/字段/边界访问 | 必要的 CPU 存储计划 |
| inputFanout / computeSupernodeFanout / commitStateFanout | [emitter 读取三表](../../wolvrix/lib/grhsim/backend/cpu_phase_emit.cpp#L713)，变化时激活读者 | 有实际作用，不能随 task 壳删除 |
| eventActivation / timeslotTriggers | 边沿事件点火 nonSink 超节点和 timeslot 标志 | 有实际作用 |
| memWritePlan | [memChunkFn](../../wolvrix/lib/grhsim/backend/cpu_phase_emit.cpp#L6115) 按计划写入，保留优先级、读者激活与收敛 | 必须保留写入计划能力 |
| translationUnits | [emitter 遍历计划](../../wolvrix/lib/grhsim/backend/cpu_phase_emit.cpp#L827)，安排 chunk 和文件 | 必要的发射计划 |
| sourceIdentity / sourceSemanticRevision | verifier 检测计划是否过期；语义修改清除旧 mapping | 生命周期保护有用 |
| numaNodes / cores / tasks / waitsFor | builder 生成、JSON 往返、verifier 重建对照；当前 emitter 不按它执行 | 当前 CPU ST 的重复表达/未使用的泛化空间 |

这些表能从图推导，不代表它们都是无用冗余：将编译期分析结果交给 emitter，并让校验检查一致性，是合理用途。需要收敛的是无独立消费者的重复表达、混乱的职责归属，以及多个互相竞争的事实来源。

泛化外壳也需审查：`BackendMapping` 名义上以 backend/schema 保存多个后端方案，实际 typed payload 是 [optional CpuBackendMapping](../../wolvrix/include/grhsim/ir/model.hpp#L700)，通用 model.hpp 直接定义大量 CPU 类型。当前核对未发现第二套同等实现的 typed backend plan。保留接口扩展能力，不等于必须维持“已经实现通用多后端映射框架”的结构假设。

### 3.3 独立 task schedule 没有驱动当前执行顺序

代码证据形成完整链条：

1. [buildSixPhaseTasks](../../wolvrix/lib/grhsim/backend/cpu_schedule.cpp#L318) 按分区树生成单 NUMA node、单 core 的 task 序列，waitsFor 为空。
2. [verifyCpuSchedule](../../wolvrix/lib/grhsim/backend/cpu_schedule.cpp#L498) 要求 task 表精确等于从当前分区树重新生成的结果，不能表示另一个合法的调度选择。
3. 当前 backend 中 numaNodes 的使用在生成、日志、校验和 JSON 上；CPU emitter 不遍历这张表。
4. [evalBody](../../wolvrix/lib/grhsim/backend/cpu_phase_emit.cpp#L6499) 直接生成固定流程：

```text
pInput
repeat until converged:
    pEvent
    pGeneral
    pLargeSink
    pPublish
pOutput
```

因此，“固定相位顺序没有意义”是错误结论；它是当前仿真执行契约。没有发挥独立作用的是：**在固定流程之外，再保存一份带 NUMA/core/task/waitsFor 的通用调度表。**

同样不能删除数据流拓扑顺序或同一状态的多写优先级。顺序审查要按用途区分：

| 顺序 | 当前来源/约束 | 收敛要求 |
| --- | --- | --- |
| 纯计算先生产后使用 | 依赖图、分区内拓扑列表 | 保留，明确唯一规范顺序 |
| General 超节点扫描 | C2 超节点 ordinal 与活动位规则 | 保留，影响本轮/下轮激活 |
| 同状态多个 writer | 声明顺序优先级和写计划 | 保留，后声明覆盖 |
| 相位与多轮求稳 | emitter 固定六阶段协议 | 明文规范或一份真正被消费的执行策略 |
| helper/chunk/TU | C6/C8 发射计划 | 只组织代码和快照生存，不能改变上述语义 |
| generic task 表 | 从分区再次生成的镜像 | 目标删除；调试时直接打印固定协议和分区顺序，不另存可编辑任务镜像 |

## 4. 还有一处反向的边界问题

[StateStoreClass](../../wolvrix/include/grhsim/ir/model.hpp#L206) 的 SmallSink/LargeSink 放在语义 StateObject 中，由 [select-state-stores](../../wolvrix/lib/grhsim/pass/select_state_stores.cpp#L73) 按字节阈值选择；B 段 phase 和 C 段布局据此组织执行。

这个分类确实在使用，但它描述“小状态用 next 双缓冲、大状态用采样参数后原地提交”的实现策略。应重新区分：

- 电路/仿真的语义：读哪个快照、什么时候提交、mask 和多 writer 如何覆盖。
- CPU 实现选择：哪类状态用哪种缓冲方式、阈值是多少、放哪个具名 store。

目标将分类迁到 CpuStatePolicy.commitMode，由 cpu.st.lower 按 CpuStOptions 的字节阈值选择；phase 迁到独立 CpuOp。采样/提交由 CpuWritePlan 与 CpuValuePlan 明确定义，不能只挪 enum 就让旧值可见性失去表达。字段、冻结点与验证要求见 [目标模型 §5–§12](pre-s9-grhsim-target-model.md#5-cpu-专属产物id-与-lowered-program)。

反过来，部分重要 CPU 决定又还在 emitter 内计算，例如 [computeFrameFields](../../wolvrix/lib/grhsim/backend/cpu_phase_emit.cpp#L1428) 和 [buildViewRoots](../../wolvrix/lib/grhsim/backend/cpu_phase_emit.cpp#L1500)。这说明当前问题同时包含“无用计划保存过多”和“实用表示选择没有形成共同计划”，不能靠一律删除 mapping 解决。

## 5. 前置工作顺序

以下单元的目标与顺序已经选定，代码尚未实施；完整交付和字段定义以 [目标模型 §14](pre-s9-grhsim-target-model.md#14-旧结构去向与实施单元) 为准。

| 单元 | 交付 | 验收重点 |
| --- | --- | --- |
| R0 事实与归属 | 本文代码核对与明确目标模型 | 文档已完成，不代表重构已完成 |
| R1 共享计算定义 | 公共 compute/type/attribute、适配器；保留 assignAs 区别，提升两个选择 op，补 sliceArray 校验 | 公共契约不双维护，完整类型/shape/X/Z 正负例一致 |
| R2 CPU lowered program | 独立 CpuProgram/ID 空间；迁入 state policy、phase、事件/调用执行方式 | 源模型没有 CPU 字段；旧值、采样次数和提交语义等价 |
| R3 CPU 计划与发射 | partition/storage/activation/write/value/codegen typed plans；删除 generic mapping/task/伪分区，落地新 JSON/verifier | 每项发射决定有唯一来源；recipe 依赖进入分块/frame，完整计划才可发射 |
| R4 封板与 S9 接入 | 前置版本回归与 ROB 验收；固定 CPU4 的 CpuValuePlan 扩展接口 | 前置收益单独归因；两个数组 pass 在此后实施 |

推荐方向可表示为：

```text
公共 IR 定义/类型/位语义
    ├─ GRH：层次、声明和 RTL 图
    └─ GrhSIM：复用公共计算，增加仿真状态/采样/事件语义

CPU 实现计划：分区、存储、激活、写入、物化、代码组织
    → 固定协议下的 C++ 发射
```

具体结构已由目标模型选定：SimModel 不持有 mappings；CpuStArtifact 与源模型配对且绑定 stamp/摘要，CPU 字段全部放在 backend 头文件；不保留 generic mappings 容器。

## 6. 对 S9 计划的修正与门禁

上一版 S9 的数组访问需求继续保留，旧接法现在明确不采用：不新增 CpuArrayAccessPlan 平行容器、ArrayAccessPlan stage 或 cpu.st.v2 mapping schema。CPU4 的 cpu.st.plan-array-access 更新同一 CpuValuePlan，CPU5/CPU6/Emit 共同消费；新格式采用 v4 容器与 cpu.st.artifact.v1 完整 CPU 产物。具体定义见目标模型 §9、§12–§13。

性能和正确性基线分开归因：

- S8 candidate 仍是不可覆盖的历史总基线。
- 如果前置实施改变代码，先单独验证“S8 → 架构收敛版本”，从原 aggregate-all SV 重生模型，做全输出比较和同 trace A/B。
- S9 两个数组 pass 的直接增量基线改为**前置架构收敛并验收后的版本**；再比较“架构收敛版本 → 数组优化版本”。不能把前置重构收益归到数组 pass。

重构前后功能验收至少包含共享 op 正/负例、两态/四态边界、同位宽不同 shape、scalar/array 混合消费、状态采样和多写覆盖、DPI/随机次数、phase 边界及强制小 helper/TU。全量 Make 门禁和 ROB 同 trace 全输出无排除对照保持；gsim 的历史比较排除不扩张。

所有 build/test/workflow 必须通过项目 Makefile，产物和日志放 ptmp。当前仅代码审计和文档检查，**无新测试通过或速度改善结论**。
