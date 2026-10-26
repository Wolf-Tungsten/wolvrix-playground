# 移除独立 GrhSIM IR：进度

- 更新日期：2026-10-26。
- 当前交付：R7 删除旧实现及 R8 规范与证据收口已完成，性能深挖与 S9 留待后续。验收输入固定 `preserve-aggregate=all`，完整原始 SV → emu 二进制用时须小于 2100 秒，保留生产优化、O3/march=native、24 job 和 JSON roundtrip。
- 当前状态：**R0–R8 已完成对应阶段验证；源码、流程与文档随本轮提交。** R5/R6 证据见 [20261026-r5-r6-validation.md](20261026-r5-r6-validation.md)，最终删除及收口记录见 [R7/R8 验证](20261026-r7-r8-validation.md)和[能力索引](capability-evidence.md)。
- R8 后生成代码修订：named store 恢复直接语义成员；General 固定按 nonsink/activity/writer 有序 helper 调度，移除小图 inline 分支和无状态 frame。最新 [store/phase 修复](20261026-store-phase-fix.md)版已补测 CoreMark 100k：**Host=1019.552s、wall=16:59.63、RSS=201,236 KiB**，退出 0、238,535 条提交、无 mismatch，十个进度点及终点与前次一致；相对前次记录 Host +5.64%，非交替 A/B。另与有来源记录的 **plain SV Verilator** 重跑完整 100k trace：两侧各 231,568 条记录逐周期完全一致，零排除、周期偏移 0，二进制/输入摘要通过。此前完整 SV 编译时间仍只属于 R7/R8 验证版本。
- 最新完整原始 SV→emu **1954.081s（32 分 34.081 秒）**，2100 秒预算通过，余量 145.919 秒；同一二进制 **CoreMark 100k / NEMU difftest Host=965.162s（16 分 05.162 秒）**、wall=16:05.20，退出 0、238,535 条提交、无 mismatch。100k 是周期窗口，不代表完整 CoreMark 结束。此前 R5/R6 的 2032.020s / 943.703s 保留于对应历史报告，不作为本次结果。
- 旧侧生成/编译性能基线与交替 A/B 已按用户决定停止，历史失败记录保留。v24/bitmap/sink-run 的结果不替代本轮证据，旧编译优化过程见 [20261025-compile-speed.md](20261025-compile-speed.md)。
- 最新约束：op 转换、无分区优化、区域提取/拆分、活动度切图、sink 调度和 emitter 各自负责明确步骤。

## 阶段状态

| 阶段 | 状态 | 主要证据 |
| --- | --- | --- |
| 计划重写 | 已完成 | README、architecture、virtual-partitions、six-phase-and-arrays、passes-and-emitter、migration-and-validation；文档检查通过 |
| R0 基线/能力清单 | 已完成 | 冻结工作树、旧库/模型、XS 输入与配置；旧公共回归、ROB、976 个旧 fixture 产物；8 个逐次观测 fixture，已记录旧 DPI 重复调用及 ABI 证据边界 |
| R1 统一 GRH 基础 | 已完成 | 等宽 assign、LogicalType/domain、方言描述符、InitSpec、JSON、实例/revision 与 typed session；类型/层次/clone/load/失效/未知方言边界通过 |
| R2 grh-to-grhsim | 已完成 | 原图转换六类写口、任务/函数/DPI、显式逻辑域；无分区/无 session 产物；签名/fire/初值/失败前检查、checkpoint 和执行 oracle 通过 |
| R3 无分区优化 | 已完成 | 独立 simplify、共享 detector、状态窄化/合并、打包、maskedOr 与 select；数组越界差异及来源累积已修复，comb-pack 全部删除；专项 4/4、公共 71/71 通过 |
| R4.1 Event/Output 提取 | 已完成 | 根/闭包、三区域、动态地址 read、effect 单原调用、sticky timeslot/typed output-end 历史 |
| R4.2 General 拆分 | 已完成 | nonsink/small-sink/large-sink、按总字节数分类、writer 私有参数锥及 General 采样 |
| R4.3 nonSink 分区 | 已完成 | 工作量 node/超节点、加权活动度切图、合法 DAG、边界 clone 和叶内化简 |
| R4.4 sink 分区/调度 | 已完成 | clock/gate/priority、交错 run、必要数据/effect 依赖、typed session/stamp、失败/重启 |
| R5 cpu-st-cpp emitter | 已完成 | 最终 54 个生成执行用例、函数预算、七万字段构造通过；168 条冻结观测 accepted=true，18 条批准、0 未解决；ROB 原 SV 全输出及动态计数、最终 XS 100k 通过 |
| R6 入口切换 | 已完成 | 最终公共 74/74、重启 10 模型、HDLBits 162/162、bugcase 27/27、ROB/XS 生产依赖审计通过；完整原 SV→emu 2032.020s，最终同一二进制 XS 100k 943.703s、238,535 提交、无 mismatch |
| R7 删除旧实现 | 已完成 | 旧 IR/API/实现已删除，干净与默认构建 64/64、全部导出/符号审计通过；HDLBits 162/162、bugcase 27/27、ROB 全输出及动态诊断、XS 完整构建与 100k 均通过 |
| R8 收口 | 已完成 | 正式类型/op/JSON、pass、六段/chunk、标准入口和[能力/测试/证据索引](capability-evidence.md)收口；旧规范归档，支持/拒绝边界明确，最终版本为 S9 直接基线 |

## 2026-10-26 R7/R8 删除后验证

独立 IR、旧转换器/方言/PassManager/CPU mapping/JSON 与 Python model 类别已删除；
有效数组测试迁到统一 GRH，兼容 Make 名称转发新路径。干净构建及默认构建公共
64/64、54 个生成执行用例、10 个 checkpoint 重启、标准安装旧 API 缺席检查通过。
完整源码/构建图/核心库/binding 审计覆盖 128 源文件，未发现旧依赖。
HDLBits 162/162、XS bugcase 27/27、ROB 原始 SV 全输出零排除比较通过。
原始 SV→XS emu 已在 **1954.081s** 完成，函数最大实际行数 1023/1024，
JSON roundtrip/调度重建通过。同一新二进制 100k **Host=965.162s**、exit=0、
238,535 条提交，无 mismatch，运行前后摘要一致。R7/R8 已关闭，完整记录见
[R7/R8 报告](20261026-r7-r8-validation.md)。

## 2026-10-26 R5/R6 必要验证

本轮覆盖当前 sink run 内联版本，修复大量作用域导致函数分块器反复扫描整函数的问题，补回未注册的混合 DPI 测试，并修正跨函数预算计数测试对函数名稳定性的错误要求。完整矩阵、实际 ROB 动态诊断、整机输入与产物身份见 [本轮验证报告](20261026-r5-r6-validation.md)。

- ROB 从原始 SV 完整重生，100,050 条记录、4,394,996,424 bytes 全输出相同，exclusions=0；同一最终图的两次 4000 eval 原生计数相同，10 个 family 动态定价及 NonSink 模块来源 100% 覆盖通过。
- XS 从原始 aggregate-all SV 生成，JSON roundtrip/调度重建通过；59,820 函数、2,355 TU，最大实际行数 1023/1024。完整编译 2032.020s，峰值同时 RSS 84,405,172 KiB，详见 [资源结果](../../ptmp/remove-grhsim-ir/r56-validation-20261026/xs-final-resources/result.json)。
- 最终同一二进制 XS 100k / NEMU difftest 通过：Host=943.703s、wall=15:43.75，exit=0，238,535 条指令、cycleCnt=99,996、Guest cycles=100,001、PC=0x80000cde；运行前后 SHA256 相同。见 [运行日志](../../ptmp/remove-grhsim-ir/r56-validation-20261026/logs/xs_wolf_grhsim_r56_final_100k.log)及 [time-v](../../ptmp/remove-grhsim-ir/r56-validation-20261026/xs-final-100k.time)。R5/R6 本轮验收完成。

## 2026-10-25 历史交付记录（v24）

本轮先优化新版编译速度，已停止旧侧性能基线与交替 A/B。优化包括 use-list 更新、状态元数据只读访问、连续叶分组、分区/调度 CSR、借用 JSON store，以及按完整 C++ 类型索引组织大型 chunkFrame；named store 保持直接成员布局。普通 GRH simplify 和生产优化轮数不变。详见[优化记录](20261025-compile-speed.md)。

| 检查 | 当时结果 | 证据 |
| --- | --- | --- |
| 输入与配置 | 2149 个冻结原始 SV，preserve-aggregate=all；不从 checkpoint 恢复；生产优化、O3/march=native、24 job 和 JSON roundtrip 保持 | [输入身份](../../ptmp/remove-grhsim-ir/xs-compile-speed-v24-paired-fresh/inputs.json)、[生成身份](../../ptmp/remove-grhsim-ir/xs-compile-speed-v24-paired-fresh/graph.generation-identity.json) |
| 完整 SV→emu | 2018.820s（33 分 38.820 秒），exit=0，2100 秒预算通过，余量 81.180 秒；峰值同时 RSS 84,126,652 KiB | [资源结果](../../ptmp/remove-grhsim-ir/r6-xs-compile-speed-v24-paired-full-resources/result.json) |
| 生成与函数预算 | 生成含 roundtrip/调度重建共 1828.547s；2276 TU、356,896 函数，最大实际函数行数 1024/1024 | [生成日志](../../ptmp/remove-grhsim-ir/xs-compile-speed-v24-paired-fresh/generation.log)、[manifest](../../ptmp/remove-grhsim-ir/xs-compile-speed-v24-paired-fresh/model/manifest.json) |
| 最新 XS CoreMark 100k | 同一 v24 二进制，NEMU difftest、seed=0、固定 CPU 2；Host=1006.031s（16 分 46.031 秒），完整命令 wall=16:46.07，exit=0 | [运行日志](../../ptmp/remove-grhsim-ir/logs/xs_wolf_grhsim_compile_speed_v24_100k.log)、[wall/RSS/退出状态](../../ptmp/remove-grhsim-ir/r6-xs-compile-speed-v24-100k.time) |
| 100k 行为 | 238,535 条指令，cycleCnt=99,996，Guest cycles=100,001，最终 pc=0x80000cde，未报告 mismatch；按 100k 周期上限结束，不是完整 CoreMark 两次迭代结束 | [Make 驱动日志](../../ptmp/remove-grhsim-ir/r6-xs-compile-speed-v24-100k-driver.log) |
| 最新回归 | 公共 74/74、完整生成执行矩阵、10 个 checkpoint 重启、168 条冻结观测（18 批准、0 未解决）、资源工具 4/4、tooling 14/14 通过 | [公共回归](../../ptmp/remove-grhsim-ir/r6-compile-speed-v24-public-tooling.log)、[矩阵与重启](../../ptmp/remove-grhsim-ir/r6-compile-speed-v24-matrix-regressions.log)、[tooling 补跑](../../ptmp/remove-grhsim-ir/r6-compile-speed-v24-tooling-retry.log) |

编译和两次运行前后核对的二进制 SHA256 均为 `7387973185910515ca8b774cbea4a6ac95ec000a775a59a10e1ee6f75f265b0e`，大小 218,149,720 bytes。100k 是新版自身单次实测，不据历史不同负载下的数据宣称受控加速比。

v24 当时尚缺最终真实 ROB 动态诊断及 R5/R6 证据收口，R7/R8 当时也尚未开始；最新进展以上方 2026-10-26 记录为准。不再追跑旧侧性能基线。

## 已确定的流程

```text
现有 GRH 前端与原 simplify
→ grh-to-grhsim
→ 无分区优化（grhsim-simplify / pack-bit-registers / recover-masked-or）
→ grhsim-split-event-and-output
→ grhsim-split-nonsink-and-sink
→ grhsim-partition-nonsink
→ grhsim-partition-sink + SinkSchedule
→ emit/grhsim/cpu-st-cpp.cpp
```

活动度切图之后可按需插入一次按叶分区的 grhsim-simplify；它不是主流程的必需步骤。

## 已明确的决策

1. GrhSIM 形态使用原 GRH 图基础设施和公共计算/声明/读口，不创建第二套实体 ID/use-def 或可执行 IR。
2. grh-to-grhsim 只按需转换，建立 edge-detect、独立写口、system-task、system-function 和 dpi-call；结果无任何虚拟归属，也不复制事件/输出锥。
3. 分区前 simplify 全图工作，等价 edge-detect 可合并并共享一次历史更新；不同输入/edge/prevInit/采样规则不合并，DPI/random 继续遵守 effect/sample identity。
4. split-event-and-output 是首次创建虚拟分区的唯一位置；它实际提取 Event/Output 锥，重接输出/事件根并处理任务粘滞触发、变化历史和 output-end 写回。
5. split-nonsink-and-sink 将 General 拆成三个区域；按总逻辑字节数分类 small/large，large 写参数仍在 General 采样。
6. partition-nonsink 仅做活动度切图和可选 boundary clone；不使用函数行数或 TU 预算。
7. partition-sink 按时钟、门控、优先级分区并发布 SinkSchedule，这是首个跨 pass 的额外分析数据，只标注 sink 有序 run 和必要依赖；不包含全部 nonsink/Output/CPU 计划。跨 clock 组交错的 writerOrder 不得被整组提交打乱。
8. 归属放在 op 的文本路径属性，之前只有 pass 内临时分析。现有 GRH simplify 不增加仿真模式；grhsim-simplify 分区后只在完整叶 owner 内工作，无 role 分支，clone 不合回。
9. 所有操作始终在一个展开 top Graph；readArray 可以和地址/数据同分区，不改成整体读取再 sliceArray 来适配切图。
10. freeze 会重编号并重置 generation；ID/SymbolId 数字和可重命名/转交的 symbol 文本都不是永久 UID。属性可恢复，调度按实例/revision 重建。
11. emitter 固定为 wolvrix/lib/emit/grhsim/cpu-st-cpp.cpp；它内部按需建立布局、访问、激活、函数和文件数据，不设置统一 CPU planner 或 StCpuPlan。
12. max-function-lines 限制全部生成函数，包括 Event/Output/init/eval/trace/helper 和 dispatcher；跨块局部变量用 chunkFrame。chunk 不属于虚拟分区，预算变化只重做 emit。
13. 六段、current/next、large in-place、事件/时隙、写优先级、采样、数组及初始化/FST/profile 逐项对照。2026-10-25 用户明确选择单个原调用、共享 held sample 与原图独立调用顺序，并要求记录旧实现差异；[语义决定](20261025-single-call-decision.md)只批准已确认的 Output 重复调用消除与精确的独立调用排序差异，不扩张为触发、参数/结果或任意 effect 差异的豁免。冻结日志不变，报告分别记录原始 equal 与所选策略下的 accepted。
14. 删除 assignAs，按完整输入/输出类型含 shape 使用等宽 assign；bitSelect/prioritySelect 属于 grhsim，基础 grh 写口/调用不增加 TriggerSpec 或 pulse 模式。
15. comb-pack 生产默认关闭，彻底删除；pack-bit-registers 默认开启，保留在无分区优化阶段并适配新的 fire 写口。maskedOr 继续迁移；S9 新优化单独归因。
16. 仅统一 GRH JSON 保存各完成阶段、语义/归属/配置及实际 clone；调度不序列化，load 后运行 partition-sink 重建，再 emit。旧独立 SimModel/CpuProgram/artifact 方案由本目录替代。

## 验证记录

规划已核对转换无分区、分区前 edge 合并、首次事件/输出提取、sink 调度产物及全部函数 chunk 的职责；两类锥先收集根和共享关系，独占计算可移动，共享计算才复制，fire 不复制检测器及历史。以下区分旧基线、各阶段证据和未完成门禁；不能用局部结果推断整机或性能通过。

此前 R0 已通过 Make 完成的旧实现基线记录如下，均不代表新流程验收：

- [冻结清单](../../ptmp/remove-grhsim-ir/r0-20261024/manifest.json)：旧输入/模型产物、工作树差异与摘要。
- [公共回归日志](../../ptmp/remove-grhsim-ir/r0-20261024/old-tests.log)：67/67 通过。
- [ROB 旧模型复跑](../../ptmp/remove-grhsim-ir/r0-20261024/replay.json)：4,394,996,424 bytes 的全输出摘要相同，exclusions=0；这是同一旧模型的可复现性检查。
- [XS 输入/旧库补充清单](../../ptmp/remove-grhsim-ir/r0-20261024/inputs-supplement.json)：2,156 条记录；原始源码权威快照仍为首次 manifest/source.tar.gz。
- [旧 emitter fixture](../../ptmp/remove-grhsim-ir/r0-20261024/old-fixtures.json)：冻结旧可执行文件配套旧共享库运行，976 个产物，含 69 份状态输出和 4 份任务输出。

R0 的逐次观测新增证据：

- [有效观测清单](../../ptmp/remove-grhsim-ir/r0-observations-v2/manifest.json)：8 个 fixture，168 条 init/eval、66 次 DPI、30 条任务输出、18 次随机采样；每个模型对象初始化三次，单文件/TU 成对日志相同。
- [源码摘要](../../ptmp/remove-grhsim-ir/r0-observations-v2/prepared.json)及[构建/运行日志](../../ptmp/remove-grhsim-ir/r0-observations-v2-driver.log)：先校验冻结源码，再在副本插桩；原冻结目录未改动。
- [旧 DPI 重复调用及未执行 ABI 范围](baseline-and-capabilities.md#r4r5-的旧-dpi-行为差异)：dpi_bit_abi 每次 eval 调用两次，不能用原输出断言推断调用次数。废弃 cpu-calls 二进制的失败不计作通过。

R1–R3 最终验证：

- [公共回归](../../ptmp/remove-grhsim-ir/r1-r3-public-final.log)：`make test_wolvrix`，71/71 通过；覆盖生产修订及来源断言。
- [最新专项](../../ptmp/remove-grhsim-ir/r2-r3-select-final.log)：`make test_grhsim_transforms`，4/4 通过；在公共回归之后新增的 bitSelect/prioritySelect/纯函数折叠执行用例也通过。之后仅修改文档。
- [基础与方言正式规范](../../wolvrix/docs/grh/grhsim-dialect.md)、[变换接口与支持边界](../../wolvrix/docs/transform/grhsim-transforms.md)：记录实际选项、类型、effects、阶段、分区隔离及已支持的保守优化范围。

R4 最终验证：

- [公共回归](../../ptmp/remove-grhsim-ir/r4-complete-public.log)：`make test_wolvrix`，73/73 通过，包含最后的等优先级重命名/freeze 与负活动度/溢出用例。
- [功能专项](../../ptmp/remove-grhsim-ir/r4-focused-final.log)：`make test_grhsim_virtual_partitions test_grhsim_transforms`，R4/变换 3/3、R1–R3 4/4 通过。
- [最新 R4 专项](../../ptmp/remove-grhsim-ir/r4-priority-final.log)：3/3 通过，包含 checkpoint/逐次观测导出、幂等、等优先级与成本拒绝；之后增加的 writer rename 断言也通过上述最终公共回归。[验收矩阵与边界](r4-validation.md)列出逐项证据。

历史定位记录保留，以下旧通过数不替代上面的最终结果：

- [公共回归](../../ptmp/remove-grhsim-ir/r1-public-regression.log)：68/68 通过；发生在最新方言/InitSpec 补充之前，不代表当前全部改动已经跑完公共套件。
- [基础与方言测试](../../ptmp/remove-grhsim-ir/r1-dialect-build.log)：通过 `make test_remove_grhsim_ir_foundation`，2/2 通过；验证类型、assign、checkpoint、stamp/session 和新 op 契约。
- [R1/R2 公共回归](../../ptmp/remove-grhsim-ir/r1-r2-public-regression.log)：70/70 通过，早于后续层次边界修订和 R3，不能代表当前全部改动已通过。
- [层次类型边界](../../ptmp/remove-grhsim-ir/r1-type-boundaries.log)：通过 `make test_grh_type_boundaries`，3/3 通过。
- [R2/R3 执行比较（第二次）](../../ptmp/remove-grhsim-ir/r2-r3-execution-check-2.log)：当时失败于数组 sample 0。已定位为多维 arrayCreate/sliceArray 消去外层时改变了扁平索引越界行为；仅在剩余索引可证明在界内时允许消去，未改变参考语义，最终专项与公共回归均已通过。

## R5/R6 历史实施记录

以下保留历次实现、执行及当时未完成的门禁，不将旧记录中的“最新”或“待完成”解释为当前状态。当前状态以上方阶段表和 [2026-10-26 验证报告](20261026-r5-r6-validation.md)为准：

- [alias 收敛反例](../../ptmp/remove-grhsim-ir/r6-alias-convergence-before.log)及[修复专项](../../ptmp/remove-grhsim-ir/r6-alias-convergence-after.log)：保留声明/output 的等型 identity assign 不再参与表达式 CSE，避免每轮延长 alias 链；4/4 通过，普通 GRH simplify 未修改。[ROB 探针](../../ptmp/remove-grhsim-ir/simplify-probe-alias-fix/report.json)在第 3 轮达到 op/value 零变化。
- [超节点与 writer 扩展性专项](../../ptmp/remove-grhsim-ir/r6-function-writer-scaling.log)、[checkpoint 执行](../../ptmp/remove-grhsim-ir/r6-flow-supernodes.log)：runtime 按 nonsink 超节点前缀聚合，完整叶 owner 仍约束 simplify；局部变量占位符和字段登记改为索引查找。16 个生成模型、10 个重启/预算模型通过。ROB 发射从 110,222 个叶激活单元纠正为 2,260 个超节点；生成耗时变化仅作定位信息，不是正式性能结果。
- [ROB 初始化定位与修复](20261024-rob-init-and-runtime.md)：91,906 字段结构中字符串默认构造缺失由独立程序复现；新 store/chunkFrame 省略冗余零成员初始化，显式 defaulted 构造函数，实例值初始化。七万字段及原结构探针通过。[ROB checkpoint 全输出](../../ptmp/remove-grhsim-ir/r6-rob-storefix/comparison.json)比较 4,394,996,424 bytes 相同，exclusions=0，SHA256 为 688ac2f6e9c5509eb00dad368ead600a07ec27d956b1ec9a429d8e46309a7df1。这是已知原 SV 派生 checkpoint 的重发验证，不是最新源完整 SV 重生或正式性能 A/B；该运行采用零 DMI/值初始化修复，早于显式 defaulted 构造函数的补充。
- [入口与最新依赖审计](../../ptmp/remove-grhsim-ir/r6-entry-guards-and-audit.log)：HDLBits/bugcase/XS/reemit 的退役选项拒绝检查补齐；显式关闭 pack/maskedOr、bitmap、写激活策略和 overwrite 正确转发。9 项工具回归通过，新路线 30 份源码、12 个对象加 ROB 生成库共 13 个编译产物未发现独立 IR 引用。旧导出/实现的 R7 删除仍未执行。
- [最终生成执行矩阵](../../ptmp/remove-grhsim-ir/r6-runtime-matrix-final.log)：调度/分区/变换 3/3，新 emitter 生成 28 个模型执行通过，并执行七万字段压力用例。覆盖 latch 振荡/round-limit/重复 init、预算 16/1024 下 libfst 实际名称/数组/130-bit 值/三次波形 epoch，以及 bitmap × on-change/on-write × 两种预算的取消写/越界写与精确计数。
- sink 依赖改为每个有序 run 展开一次完整叶闭包，内部使用稠密下标；公开 SinkSchedule 的完整叶前置集合和顺序不变。共享长锥/128 writer 用例通过。[同 ROB checkpoint 探针](../../ptmp/remove-grhsim-ir/r6-sink-probe-dense.json)：load 4.725s，重建 6.075s，峰值 RSS 5,521,504 KiB；只是定位实测，不是完整生成或正式 A/B。
- [最新公共及安装](../../ptmp/remove-grhsim-ir/r6-current-public-and-install.log)：74/74 通过，104.20s，随后 make py_install 成功。[HDLBits](../../ptmp/remove-grhsim-ir/r6-hdlbits-storefix/logs/summary.txt) 162/162、[bugcase](../../ptmp/remove-grhsim-ir/r6-bugcases-storefix.log) 27/27、[checkpoint 执行](../../ptmp/remove-grhsim-ir/r6-flow-storefix.log) 10 个模型通过。
- [原生 GRH 读者](../../ptmp/remove-grhsim-ir/r6-native-readers.log)：读取限定图内的原生 symbol/attrs/完整类型，不伪造旧 input op、事件状态或 objectRef。ROB census、写口第 3 个操作数的数据锥、数组不透明边界及等型 assign 适配；历史 paired-cone 31/31、census 23/23 和工具 9/9 通过。新增读者的 11 项测试及 [真实 ROB 静态读取](../../ptmp/remove-grhsim-ir/r6-native-rob-census.log)通过：422 状态、176 数组、2 个 detector。保留未使用的悬空 value symbol，遍历缺失 producer 才报错。冻结动态计数 gate 仍只支持旧 mapping，明确拒绝拿旧 ID 给新图定价。

- [调用归一化与生成模型日志](../../ptmp/remove-grhsim-ir/r5-r6-call-normalization.log)：转换与局部 C++ 矩阵已执行，包含两种函数预算、DPI SV 类型别名/有符号视图及非零宽条件；不代替完整 ABI/effects/全部函数类别验收。
- [冻结新旧比较](../../ptmp/remove-grhsim-ir/r5-observations/comparison.json)：8 个 fixture、168 条记录；outputs/states 相同，random/monitor 用例相同，但 dpi_smoke 及 TU 版本各有 9 条 effects 差异，dpi_bit_abi 有 6 条，严格比较未通过。
- [分区化简规模修订](../../ptmp/remove-grhsim-ir/r6-partition-simplify-scaling.log)：局部专项通过；ROB/XS 大图规模效果及无分区 simplify 的轮数上限问题仍待验证。
- [最终 sink 共享纯锥修订](../../ptmp/remove-grhsim-ir/r6-sink-cse-clones.log)：补充粗 sink 化简后、最终时钟/优先级分组时复制纯锥的执行用例，变换/分区/调度专项 3/3 通过；未据此宣称整机通过。
- [统一图重启局部执行](../../ptmp/remove-grhsim-ir/r6-flow-current.log)、[profile 入口](../../ptmp/remove-grhsim-ir/r6-profile-model.log)及[归属计时单位](../../ptmp/remove-grhsim-ir/r6-profile-units.log)：已有局部结果，实际整机 profile 与完整生产依赖审计仍待完成。

- [连续数组执行矩阵](../../ptmp/remove-grhsim-ir/r6-contiguous-array-matrix.log)：30 个生成模型及七万字段构造用例通过。参考旧 emitter 的 pack/unpack 路径，8/16/32/64/128-bit 无填充叶数组用调用方缓冲区 memcpy，等宽等叶宽 reshape 直接复制；带填充叶保留原路径。覆盖两种函数预算、三次 init、多维 shape 与 8192-bit byte image。
- [最新公共和安装](../../ptmp/remove-grhsim-ir/r6-contiguous-public-and-install.log)通过后，[原始 SV 完整重生](../../ptmp/remove-grhsim-ir/r6-rob-contiguous-fresh/generation.log)、304 TU 编译及 [ROB 全输出比较](../../ptmp/remove-grhsim-ir/r6-rob-contiguous-fresh/comparison.json)完成：4,394,996,424 bytes、exclusions=0，SHA256 仍为 688ac2f6e9c5509eb00dad368ead600a07ec27d956b1ec9a429d8e46309a7df1；单次运行 385.669s。
- [最新 bounded perf](../../ptmp/remove-grhsim-ir/r6-rob-contiguous-profile.log)：原 trace 前 2000 周期、checksum=14806783039636027445，运行 4.824s；修复前同探针 12.393s、59.96% 样本集中在 pOutput_chunk3。最新 957 个样本已无该集中热点。这是定位测量，不是正式 A/B 或性能通过结论。
- [XS 生成](../../ptmp/remove-grhsim-ir/xs-storefix/logs/xs_wolf_grhsim_ir_r6_storefix.log)退出 0：从捕获 flat GRH 重启，生成总计 3777.054s，36,659 个 nonsink 超节点。首轮 simplify 触及 8 轮上限，不能记为收敛；该模型早于连续数组修复。后续 xs-contiguous 重发的编译失败已定位并修复，见追加记录；重发不替代完整 SV 生成计时。

### 2026-10-25 追加验证与用户决定

- [单个原调用决定](20261025-single-call-decision.md)已落实到比较器的显式策略。[新报告](../../ptmp/remove-grhsim-ir/r5-observations-single-call-v1/comparison.json)保留全部原始差异：dpi_bit_abi 六条精确的“两个相同调用 → 一个相同调用”已批准；dpi_smoke/TU 各九条顺序或触发差异仍未解决，整体 accepted=false。工具回归 10 项通过；原始严格报告未修改。
- [最新公共与重启回归](../../ptmp/remove-grhsim-ir/r6-view-lifetime-public-flow-tests.log)：公共 74/74，106.02s；统一图重启执行 10 个模型，provenance 3 项及原生图读者 16 项通过。[最新生成执行矩阵及安装](../../ptmp/remove-grhsim-ir/r6-view-lifetime-matrix-install.log)：34 个模型及七万字段构造用例通过。
- [ROB dispatch 全输出](../../ptmp/remove-grhsim-ir/r6-rob-dispatch/comparison.json)和 [array-view 全输出](../../ptmp/remove-grhsim-ir/r6-rob-arrayview/comparison.json)各比较 4,394,996,424 bytes 相同，exclusions=0，摘要保持不变；单次分别 348.191s、247.164s，均为 checkpoint 重发，不能称为最新原 SV 重生。前者历史报告的 source 字段过于宽泛，原报告保留；新报告按生成 sidecar 的 kind 标记来源，绑定源码/库/driver/bench/input 摘要，并在运行前后检查。
- [array-view bounded perf](../../ptmp/remove-grhsim-ir/r6-rob-arrayview/runtime.perf-all.txt)：前 2000 周期 1.84131s、checksum=14806783039636027445；359 个样本约 59.57% 为 writer、16.19% 为 nonSink、15.11% 为 largeCommit，Output 约 1.10%。后续定位集中到 writer/提交，正式性能门禁仍未通过。
- XS 的原生 concat 左折叠表达式触发本机 Clang parser 栈溢出；[重现](../../ptmp/remove-grhsim-ir/r6-xs-tu154-reproduce.log)及[回溯](../../ptmp/remove-grhsim-ir/r6-xs-tu154-backtrace.log)保留。emitter 改为保持位序/宽度的平衡表达式树，1217 操作数 concat/replicate 在两种预算及三次 init 下执行通过。
- XS 后续重发暴露 array-view 分析遍历临时 Value 的 users span 生命周期问题，已持有 Value snapshot 后再遍历；新增 96 消费者反例。最新矩阵/公共回归包含修复。XS 已在 xs-viewlife 隔离重发成功，2349 TU 正在编译。[ROB 原 SV 完整重生](../../ptmp/remove-grhsim-ir/r6-rob-viewlife-fresh/comparison.json)已完成并绑定生成身份：4,394,996,424 bytes、exclusions=0、相同摘要，单次 409.398s（同时进行 XS 编译），不能作为受控性能结果。
- [原生静态读者回归](../../ptmp/remove-grhsim-ir/r6-native-static-readers-tests.log)：reader 16、历史 family 23、历史 paired 31 项通过；[真实 ROB family](../../ptmp/remove-grhsim-ir/r6-native-rob-families/summary.json)覆盖 231 个声明 scalar state 和 10 个 family。新 family/paired 直接读取原生 writer 的 data 操作数及完整类型；动态计数绑定/定价仍明确不支持，不复用旧 mapping ID。

- [DPI 触发修复矩阵](../../ptmp/remove-grhsim-ir/r5-dpi-trigger-matrix.log)36 个模型通过：脉冲只在断言时激活消费者，清零不当作数据变化；eval 仅主动唤醒按 eval 采样的函数，不无条件唤醒 DPI/任务。[冻结重比](../../ptmp/remove-grhsim-ir/r5-observations-triggerfix/comparison.json)中 smoke/TU 各从九条降至六条差异，仅剩旧 dbl→inc 与新 inc→dbl 的排序；次数、触发、参数、返回值、状态及输出一致，排序尚待决定。
- [混合 ABI 修复与矩阵](../../ptmp/remove-grhsim-ir/r5-dpi-mixed-matrix-fixed.log)38 个生成模型通过：void、real/string 返回、128-bit output/inout、real/string output/inout、交错参数声明、同沿混合调用顺序及 held sample。ABI 沿用旧 emitter：string input 用 const char*，string output/inout 用 std::string*，string 返回用 std::string；不据此声称标准 C DPI ABI。新增测试发现的宽 output 临时值初始化语法错误已修复。
- sink writer 先计算 enable 依赖，再在使能 guard 内计算私有 payload 锥，沿用 legacy guard 的采样边界，不在禁用写口上搬运大 payload；[新矩阵及安装](../../ptmp/remove-grhsim-ir/r6-enable-guard-matrix-install.log)通过。ROB 正在 r6-rob-enable-guard 隔离重发并做全输出/perf 检查；公共与工具回归正在执行。

### 原图调用顺序决定与 sink-run 发射验证

- 用户进一步明确保留原图独立调用顺序，见[决定](20261025-single-call-decision.md)。比较策略新增 single-original-call-source-order；精确匹配 smoke/TU 的 `[dbl, inc] → [inc, dbl]`，两个完整调用记录必须逐项相等，不豁免触发、增减调用、参数或返回值变化。[工具回归](../../ptmp/remove-grhsim-ir/r5-source-order-policy-tests.log)12 项通过；[最新冻结重比](../../ptmp/remove-grhsim-ir/r5-observations-source-order/comparison.json)8 fixture、168 记录，原始 equal=false、accepted=true：18 条原始 effects 差异全部属于两项明确决定，未解决项为 0；outputs/states/inputs 无差异。
- [early-guard 公共回归](../../ptmp/remove-grhsim-ir/r6-enable-guard-regressions.log)公共 74/74（121.21s），重启 10 模型、provenance 3、reader 16、历史 family 23、paired 31 通过；[实际生产依赖审计](../../ptmp/remove-grhsim-ir/r6-enable-guard-production-audit.json)通过，覆盖 30 源文件、13 编译产物。
- [early-guard ROB 全输出](../../ptmp/remove-grhsim-ir/r6-rob-enable-guard/comparison.json)为 GRH checkpoint 重发，4,394,996,424 bytes、exclusions=0、摘要不变，运行 325.794s（与 XS 工作并行）。[2000 周期交替诊断](../../ptmp/remove-grhsim-ir/r6-rob-enable-guard/runtime-screen/comparison.json)固定 CPU 0，预热后 3+3，checksum 相同；旧/新中位数 3.00652s / 1.92103s。旧侧是冻结静态库重新链接的探针，不是历史 49.296s 的 dump_outputs 程序；这仅定位诊断，不是正式生成/编译/RSS/100k 性能门禁。
- [XS viewlife 执行](../../ptmp/remove-grhsim-ir/r6-xs-viewlife-run.log)与 [XS early-guard 执行](../../ptmp/remove-grhsim-ir/r6-xs-enable-guard-run.log)均退出 0，difftest 开启，100,000 host cycles、238,535 committed instructions，未报告 mismatch；host 时间分别约 2888.733s、2412.270s。前者早于 DPI/guard 修订，后者包含这些修订；两者均早于本轮 sink-run 发射调整，不能代替最终版本 XS 证据。
- emitter 改为复用 SinkSchedule 的连续 writer run：每 run 只计算一次共享纯锥、保留有序 writer 和 General 采样；large commit 同样按 run 发射并复用连续 bitmap-word guard。新增 small/large 各 48 writer、双门控、三次 init 与两种预算执行用例；不同初值阻止合法状态合并掩盖批次规模。
- tiny budget 首次生成卡住，日志保留在 [原始矩阵](../../ptmp/remove-grhsim-ir/r6-sink-run-matrix.log)。发现单个 scope 的局部声明超预算时，移动到辅助函数不减少声明，会重复包裹同一 scope；现在将该组局部值显式 spill 到 chunkFrame，保持初值并计入实际函数行数。新增 20 局部值、单 guard/statement 的执行反例；[本轮矩阵](../../ptmp/remove-grhsim-ir/r6-sink-run-frame-matrix-distinct-init.log)42 个生成模型及七万字段构造用例全部通过，实际行数检查未放宽；[安装](../../ptmp/remove-grhsim-ir/r6-sink-run-install.log)完成。
- [sink-run 公共回归](../../ptmp/remove-grhsim-ir/r6-sink-run-public.log)74/74，105.33s；[重启/读者](../../ptmp/remove-grhsim-ir/r6-sink-run-flow-readers.log)10 模型、provenance 3、reader 16、tooling 12、历史 paired 31 均通过。最终 ROB/XS、HDLBits/bugcase 正在隔离目录验证，不能提前引用前版成功作为本版结果。
- [sink-run 补充结果](20261025-sink-run-validation.md)：HDLBits 162/162、bugcase 27/27、生产依赖审计通过。ROB checkpoint 重发全输出 4,394,996,424 bytes、零排除、摘要不变，362.606s；当前短程交替诊断受并行 XS 编译负载影响，不是正式性能门禁。XS 最终版重发及 2374 TU 编译完成，独立 100k 执行目前到 40k、未报告 mismatch；profile 分类器已适配 writer_run/commit_run。
- [最终原 SV ROB](../../ptmp/remove-grhsim-ir/r6-rob-sink-run-fresh/comparison.json)完整重生、编译及全输出通过，4,394,996,424 bytes、零排除、摘要不变，243.998s。单次生成/编译 time-v 记录分别为 4:04.09 / 2:37.61，不是正式旧/新性能结论。
- 迁移计时新增独立 Make 入口，双侧完整预热后固定 CPU 4 交替 3+3，按冻结 3% Host/5% RSS 预算与预登记 5% 噪声门槛判定；不复用要求严格加速的优化排名门槛。[工具回归](../../ptmp/remove-grhsim-ir/r6-migration-runtime-gate-tests-final.log)6 项及 tooling 12 项通过；实际 r6-xs-runtime-ab-v1 已启动，目前预热，尚无正式结果。剩余动态诊断及生成/编译/并发峰值内存门禁保持未完成。

2026-10-25 用户决定停止旧侧性能基线及交替 3+3 性能对照；上面的历史 A/B 结果只保留事实。v24 的完整编译为 2018.820s、XS 100k Host=1006.031s，当时尚缺最终动态诊断及证据收口；这些缺项已由 [2026-10-26 验证](20261026-r5-r6-validation.md)补齐。不同程序/时点/负载的数据不能混作正式比值，R7 仍为独立后续阶段。

## 阶段审计与后续边界

- R1：原 GRH 前端/transform/SV emit 的等宽 assign 和完整类型传播已同步，state/read/domain/InitSpec、JSON 版本及未知 kind、clone/load/new instance、改图/freeze/rename/端口失效均有检查；通用 PassManager 拒绝未适配方言，普通 simplify 不增加仿真模式。旧 assignAs 仅保留拒绝诊断及负例。
- R2：原图实体/公共 op 不复制，六类 writer、system-task/function、DPI 逐项转换；多事件 OR、边沿初值及回退、调用方向/签名、逻辑域投影和 undriven 支持边界有用例。重复转换幂等，非法源形态在改图前拒绝，结果没有虚拟归属或 session 计划。
- R3：全图 detector CSE 及 edge/init/sample 反例、分区 owner 隔离、effects 存活/顺序/保持、数组构造和动态/越界访问、write/mask/fill/latch、packed 双消费、状态等价/窄化、打包正反例、maskedOr 与 select 由执行 oracle 和契约测试覆盖。四态未知位保留，纯求值复用基础工具，普通 simplify 驱动保持独立。
- R4：四步分别提交可重载的阶段与唯一叶 owner；动态地址 read 在各区域重新求值，检测器/外部调用不复制，时隙 history 在 Output 末统一提交。活动度边界成本包含输入/事件脉冲，leaf/超节点与 effect-order 的 DAG 校验阻止非法收缩；sink 分组不改变 writerOrder，调度含必要依赖并按实例/top/revision/config 验证。freeze、rename、symbol 转交、load/clone、隔离 dryrun、失败/清空后重建均有用例。
- 来源审计修复了旧 inheritOrigin 覆盖目标来源的问题：新优化在合并/打包/alias 时累积有序去重 union；声明 view 仅保留自身声明来源，packed read 保留全部原读来源，均有断言。comb-pack 实现、注册、构建、Make/脚本/CLI/报表及专用 fixture 已清除，混合套件的有效行为/provenance 覆盖保留。

独立 oracle 比较 outputs、声明状态及 ordered effects；投影 round 轨迹只折叠连续无变化项，允许删除纯内部空 round，effects 不折叠。R4 interpreter 执行图中归属和调度，四态/Real/String 的 R4 证据仅覆盖 IR/JSON；它不等同于旧 C++ emitter，也不证明运行时活动度激活或性能。R5/R6 已由混合 ABI/effects、全部函数 chunk、真实 ROB 全输出/动态计数/归属、完整编译预算及 XS 100k 执行完成验收；未借用历史通过数或恢复已取消的旧侧性能门禁。R7 删除后另行完成干净重建和全部必要回归，R8 正式规范与证据索引已收口。S9 尚未实施，其直接基线为本次 R7/R8 验证版本。

实施阶段的日志与临时产物统一使用 ptmp/remove-grhsim-ir/<run-id>/。未完成相应执行门禁前，不更新代码阶段状态或引用旧通过数作为新结果。
