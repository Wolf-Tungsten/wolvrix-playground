# 移除独立 GrhSIM IR

- 制定日期：2026-10-23；本次修订：2026-10-26。
- 状态：**R0–R8 已完成必要验证，源码、流程与文档随本轮提交。** 旧独立 IR 已删除，规范和证据已收口；[R5/R6 报告](20261026-r5-r6-validation.md)保留迁移证据，删除后的最终结果见 [R7/R8 报告](20261026-r7-r8-validation.md)和 [进度](PROGRESS.md)。
- 交付边界：完成迁移及必要验证，性能深挖与 S9 留待后续。已取消的旧侧性能基线与交替 A/B 不恢复；保留生产优化、-O3 -march=native、24 job、JSON roundtrip 和 aggregate-all 原始 SV→emu 小于 2100 秒的验收口径。
- 最新运行结果：[store/phase 修复版](20261026-store-phase-fix.md) CoreMark 100k / NEMU difftest **Host=1019.552s（16 分 59.552 秒）**、wall=16:59.63、RSS=201,236 KiB，退出 0、238,535 条提交、无 mismatch；相对前次记录 Host +5.64%，非交替 A/B。最近一次完整原始 SV→emu 连续测量仍为 R7/R8 版本 **1954.081s**，该版本 100k Host=965.162s；当前修复版未重测完整 SV 构建时间。100k 按周期上限结束，不代表完整 CoreMark 两次迭代结束。
- 目标：在 GRH 的同一套图实体上承载基础 grh 和 grhsim 方言，保留六段调度、数组和 C++ 模型接口，删除独立 GrhSimModel 及其基础设施。
- 当前行为对照：与有来源记录的 **plain SV Verilator** 分别重跑 CoreMark 100k，两侧各 **231,568 条提交 trace 逐周期完全一致**，有效写回数据/目标一致、周期偏移 0、退出码均为 0。见 [plain 对照证据](20261026-store-phase-fix.md#plain-sv-verilator-行为对照)。

流程职责以 [Pass 与 emitter 清单](passes-and-emitter.md)为准：先转换 op，再优化无分区大图，然后依次提取 Event/Output、拆 General、切 nonsink、分 sink 并给出顺序，最后由 emitter 生成 C++。各个步骤的名字、顺序和首次产生的内容如下，不把某一单独阶段称为 lower。

## 1. 必须满足的边界

1. 始终使用 GRH 的 Design / Graph / Operation / Value、类型、use-def、属性和 JSON。下文“GrhSIM 形态”指同一张 GRH 图包含 grhsim 方言 op，不是第二套图、实体 ID 或可执行 IR。
2. grh-to-grhsim 只按需转换 op，主要引入 edge-detect、grhsim 写端口、system-task、system-function 和 dpi-call；公共计算、数组、状态声明、读口和 DPI import 复用原定义。转换结果是平整的无分区大图，不能预先创建 General、Event 或 Output。
3. 转换后先在无分区图上按需优化。独立 grhsim-simplify 可以在全图合并等价计算，包括输入、边沿模式、历史初值和采样规则一致的共享 edge-detect。现有 GRH simplify 保持原职责。
4. grhsim-split-event-and-output 首次提取 Event 和 Output 锥并建立 General / Event / Output 三个虚拟区域，明确处理状态读、输出端口、时隙任务与共享采样。
5. grhsim-split-nonsink-and-sink 再将 General 划为 nonsink / small-sink / large-sink；small/large 按状态总逻辑字节数选择，默认阈值 64 bytes，与 shape 解耦。
6. grhsim-partition-nonsink 做活动度切图、多级 nonSink 归属及真实边界上的可选 clone。grhsim-partition-sink 按时钟、门控和优先级细分两类 sink，并产生标注 sink 采样/写入顺序的 SinkSchedule；它是首个需要在 pass 之间传递的额外分析产物，不扩张为整个 CPU 的执行计划。
7. 计算、状态、带地址 read、写口和调用一直留在一个展开后的 top Graph。虚拟归属保存在 grhsim.partition 属性；此前只有各 pass 的局部临时分析，没有另一份持久成员树或 CPU 计划。
8. 有分区后，grhsim-simplify 只在完整叶分区内改写，不跨界合回复制的操作；无逐 op role，也不按 Event/General/Output 分别实现化简器。副作用和采样语义仍须校验。
9. C++ emitter 固定为 **wolvrix/lib/emit/grhsim/cpu-st-cpp.cpp**，公开 ID 为 grhsim-cpu-st-cpp。它读取 GRH 和 SinkSchedule，按需建立私有的布局、激活、访问与代码生成数据；不再设置单独的 CPU planning pass。
10. chunk 是 emitter 的函数大小控制参数，不是虚拟分区。所有生成函数均受 max-function-lines 限制，跨 chunk 的局部变量由 chunkFrame 传递；调节该参数不改变任何虚拟归属或调度顺序。
11. 保留 P_input / P_event / P_general / P_large_sink / P_publish / P_output 六段协议，固定点、多写覆盖、事件历史、时隙任务、DPI/随机采样与 output-end 提交逐项验收。2026-10-25 用户明确采用[单个原调用、共享 held sample 与原图调用顺序](20261025-single-call-decision.md)，旧 Output 重复调用消除和独立调用的旧调度排序差异单独分类并保留原始报告；其他次数/触发/参数/结果差异仍须解决，见 [基线记录](baseline-and-capabilities.md#r4r5-的旧-dpi-行为差异)。
12. 数组保留总宽 + shape、位序、构造、整体/部分/动态索引、掩码写、fill/readmem 和数组/packed 双消费；不为分区将索引 read 改成整体 read 再 sliceArray。
13. 基础 grh 删除 assignAs，统一使用等宽 assign；完整输入/输出类型含 shape 决定传递或合法转换。基础写口和调用契约不变，不加入 TriggerSpec 或 pulse 模式；grhsim 时钟写口的首 operand fire 接 edge-detect 结果或其合法 OR。
14. OperationId/ValueId 仅在当前 revision 内使用；freeze/压缩会重编号，SymbolId 不是持久 key，symbol 文本也不是永久 UID。属性保存文本分区 key，所有 resolved 分析按实例和 revision 重建。
15. comb-pack 当前生产默认关闭，彻底删除实现、注册、开关、报表和专用 fixture，不迁移。pack-bit-registers 当前生产默认开启，迁移后仍默认开启，在无分区优化阶段执行并适配新的脉冲写口。
16. 决定语义和归属的信息保存在统一 GRH；SinkSchedule 使用现有 SessionStore scratchpad，可从图和显式选项重建。不引入 prepare、统一 StCpuPlan、第二套 PassManager 或独立执行 JSON。

## 2. 目标管线

主流程严格采用以下七步，优化 pass 是第二步内按需插入的选择；verify/store 是检查和保存边界，不增加新的转换阶段。`grh-to-grhsim` 是 op 形态转换的名称；从 SV 到 C++ 的整个过程才是完整的编译转换流程，不用 lower 命名单独阶段。

| 顺序 | 入口 | 本步完成后新增的内容 | 跨 pass 的额外数据 |
| --- | --- | --- | --- |
| 1 | grh-to-grhsim | edge-detect、grhsim 写口及 system-task/system-function/dpi-call；仍无虚拟分区 | 无 |
| 2 | 按需优化，包括 grhsim-simplify | 优化后的无分区大图；等价 edge-detect 可以合并 | 无 |
| 3 | grhsim-split-event-and-output | 首次建立 general、event、output，并实际提取、重接事件/输出锥 | 无 |
| 4 | grhsim-split-nonsink-and-sink | 仅将 general 拆成 nonsink、small-sink、large-sink | 无 |
| 5 | grhsim-partition-nonsink | nonsink 内部的活动度分区及其层次 | 无 |
| 6 | grhsim-partition-sink | 两类 sink 的 clock/gate/priority 分区，以及顺序标注 | 首个：SinkSchedule |
| 7 | emit/grhsim/cpu-st-cpp.cpp | C++ 程序；布局、函数、chunk/chunkFrame 均在发射内部处理 | 仅 emitter 私有便利数据 |

```text
SV ingest → 现有 GRH 前端变换与原 simplify
  → grh-to-grhsim                         # op 转换；无虚拟分区
  → 按需优化：grhsim-simplify / pack-bit-registers / recover-masked-or
  → grhsim-split-event-and-output         # 首次形成 general / event / output
  → grhsim-split-nonsink-and-sink          # general → nonsink / small-sink / large-sink
  → grhsim-partition-nonsink              # 活动度切图与边界 clone
  → grhsim-partition-sink                 # 时钟、门控、优先级分区 + SinkSchedule
  → emit grhsim-cpu-st-cpp
      wolvrix/lib/emit/grhsim/cpu-st-cpp.cpp
```

如活动度切图中的 clone 需要再化简，可在 partition-nonsink 之后、partition-sink 之前显式插入 grhsim-simplify；这不是主流程的必需步骤，只能在各完整叶分区内工作。

数据承载也按这个顺序收敛：计算/状态/调用在 GRH，虚拟分区归属在 op 属性，sink 顺序在 scratchpad 的 SinkSchedule，C++ 布局和函数便利结构在 emitter 私有 scratchpad。partition-sink 以前不建立跨 pass 的状态计划、成员树或 CPU 计划。所有生成函数统一应用 max-function-lines，通过 chunkFrame 传递跨 chunk 的局部变量；chunk 不改变虚拟分区。

每个完成阶段均可保存统一 GRH checkpoint。转换后的 checkpoint 明确没有分区；细分后的 checkpoint 保存属性和实际 clone，不保存 CPU 内存布局、chunk 或 SinkSchedule。重载后按阶段运行后续 pass，已完成 sink 分区的图也要重新运行 grhsim-partition-sink 重建调度产物，再交给 emitter。

## 3. 阅读顺序

| 文档 | 解决的问题 |
| --- | --- |
| [统一 GRH 与 scratchpad](architecture.md) | 方言、完整类型、脉冲写口/调用、SinkSchedule、emitter 私有数据与生命周期 |
| [单图与虚拟分区](virtual-partitions.md) | 首次提取的位置、各次归属变化、共享锥、全图/分区内化简及 ID/symbol |
| [六段调度与数组契约](six-phase-and-arrays.md) | 六段数据流、提交与采样、数组操作数/位序、快照及统一 chunk |
| [Pass 与 emitter 清单](passes-and-emitter.md) | 按指定顺序定义每个 pass 的输入、结果、检查与文件位置 |
| [迁移步骤与验收](migration-and-validation.md) | R0–R8 交付、Make 门禁、行为比较、新版编译预算与旧代码删除 |
| [实施进度](PROGRESS.md) | 当前状态、已确认决策与证据 |
| [R4 验收](r4-validation.md) | 四步变换、执行对照、各阶段 checkpoint、调度与生命周期证据 |
| [R5/R6 必要验证](20261026-r5-r6-validation.md) | 当前 emitter/入口的最终回归、ROB 全输出与动态诊断、XS 完整构建及 100k 验收 |
| [R7/R8 删除与收口](20261026-r7-r8-validation.md) | 删除后的干净构建、导出/依赖审计、回归与整机验证 |
| [能力与证据索引](capability-evidence.md) | 每项能力的实现、测试、报告及支持/拒绝边界 |
| [正式仿真流程](../../wolvrix/docs/grhsim.md) | 统一 GRH、Python/Make、checkpoint、六段与 ABI 的现行规范入口 |
| [sink-run 与函数预算验证](20261025-sink-run-validation.md) | 历史 emitter 改动、分块停滞修复及当时执行结果 |
| [原生计数与空 sink 调用](20261025-native-counters-and-idle-dispatch.md) | 动态绑定/定价口径、XS 100k、热点定位和各候选版本边界 |
| [旧实现能力与证据](baseline-and-capabilities.md) | R0 冻结范围、旧能力到各新步骤的映射及观测缺口 |

## 4. 当前事实与本计划的关系

冻结的旧生产路线以独立 GrhSimModel 为核心，复制公共计算和实体，依赖旧事件/输出 pass、CPU mapping 和 cpu_phase_emit.cpp。当前标准入口使用统一 GRH、grh-to-grhsim、无分区优化、两次拆分、两类分区、SinkSchedule 及 cpu-st-cpp emitter。comb-pack 和其余独立 IR/API/JSON/backend 实现已删除；实际使用的 emit runtime 保留。R5/R6 验证及 R7 删除后的干净重建/整机回归均已完成，R8 规范/证据已收口；本版本作为 S9 直接基线。

现有可复用入口：

- [transform.hpp](../../wolvrix/include/core/transform.hpp)：普通 PassManager、PassContext::session 和 SessionStore typed slot。
- [emit.hpp](../../wolvrix/include/core/emit.hpp)：EmitOptions::session，将 SinkSchedule 传给 emitter。
- [GRH 实现](../../wolvrix/lib/core/grh.cpp)：属性、符号与 freeze；裸 ID 不适合作为长期归属映射。
- [生产脚本](../../scripts/wolvrix_xs_grhsim.py)：当前能力、有效开关与测试迁移的核对入口。
- [六段记录](../simulation-model-refactor/grhsim-six-phase-data-flow.md)：当前运行行为的核对入口。

[原边界审查](../grh-ir-array-support/pre-s9-grhsim-ir-boundary-review.md)继续作为重复定义的证据；[原目标模型](../grh-ir-array-support/pre-s9-grhsim-target-model.md)中的独立 SimModel → CpuProgram → CpuStArtifact 与独立 JSON 方案由本计划替代。

[S9 数组计划](../grh-ir-array-support/stage-09-array-normalize-mapping.md)中的新计算优化放到合适的分区前变换，访问优化接入 emitter 私有访问分析。先验收当前能力的等价迁移，再单独评价 S9 收益。旧文件顶部已标注历史方案及替代关系，正文保留原审查和 S8 证据。

## 5. 完成定义

标准入口依次完成 op 转换、无分区优化、两次区域拆分、nonSink/sink 分区和 C++ 发射。能够直接检查每一步的 GRH；清空 scratchpad 或重载后可重建 SinkSchedule，改变 chunk 行数上限只改变生成代码的函数组织，全部模型行为保持等价。

六段、数组、任务/DPI/随机、初始化、FST/profile、声明与模块归属均有迁移证据后，删除独立 GrhSIM 模型、旧转换器、JSON、PassManager、CPU backend 壳、comb-pack 和 Python grhsimModels 类别。历史证据允许保留，生产路径不再依赖旧 IR。
