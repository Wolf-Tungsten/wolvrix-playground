# 迁移步骤与验收

本计划按指定七步流程交付，具体 pass 职责以 [Pass 与 emitter](passes-and-emitter.md)为准。R0–R8 已完成对应阶段验证；2026-10-26 已完成生成执行、批准策略下的旧→新比较、ROB 行为/动态诊断、XS 完整编译预算及 100k difftest，并删除旧实现、完成规范收口。阶段证据见 [R5/R6 报告](20261026-r5-r6-validation.md)、[R7/R8 报告](20261026-r7-r8-validation.md)、[实施进度](PROGRESS.md)和 [能力索引](capability-evidence.md)。冻结之前的数组、来源与 ROB 未提交改动属于基线，实施时不得覆盖或回滚；本工作树未提交，S9 尚未实施。

## 1. 实施顺序与工作目录

按“冻结行为 → 统一 GRH 基础 → op 转换 → 无分区优化 → 两次拆区域和两类分区 → emitter → 入口切换 → 删除旧实现”交付。每步有可审阅代码、规范和证据，不把事件/输出提取、存储分类、活动度切图和调度合并成含糊的一步。

所有构建、测试、安装和脚本工作流必须通过项目 Makefile；无目标时先添加。日志、模型、报告和比较数据放 ptmp/remove-grhsim-ir/<run-id>/；测试框架固定 artifacts 遵循仓库规范，不写 /tmp，不覆盖当前 XS/ROB/S8 工作目录。

## 2. 分阶段交付

### R0：冻结基线与能力清单

- 记录主仓库/子模块 revision、tracked diff 与相关 untracked 摘要；不能用单个 commit hash 代表脏工作树。
- 固定原 aggregate-all SV、原 GRH/旧 GrhSIM checkpoint、模型源码/可执行文件、配置、seed、trace、工具链/flags 和摘要。
- 生产默认基线为 comb-pack 关闭、pack-bit-registers 开启；记录实际有效值，不能用开启 comb-pack 的实验产物代替。
- 建立“能力 → 源码 → 测试 → 新步骤”清单，覆盖计算/数组、状态/事件、任务/函数/DPI/随机、六段、初始化、FST/profile 和来源。
- 在改旧 emitter 前保留独立可运行的旧模型与同 trace 输出；调用次数、顺序和状态投影通过 Make 构建旧侧观测 harness，固定共同记录格式；新 emitter 对接和旧→新比较在 R5/R6 完成。
- 同步 pre-S9/S9 旧文档的状态引用，冻结 S8 证据。

退出条件：旧结果可复现，新旧目录隔离；回归口径、已有失败、噪声范围与性能门槛在 candidate 运行前确定。

R0 的旧侧记录已完成。实际覆盖与未执行的旧 ABI 用例见 [能力清单](baseline-and-capabilities.md#逐次观测与证据边界)；冻结 dpi_bit_abi 的两次调用原样保留。2026-10-25 用户明确采用单个原调用、共享 held sample 与原图独立调用顺序，见[语义决定](20261025-single-call-decision.md)。精确的旧 Output 重复调用消除及独立调用旧调度排序差异单独分类；其他触发及参数/返回值差异仍须解决，不伪造一次调用基线。

### R1：GRH 类型、方言与生命周期

- 统一完整 LogicalType、shape 几何、逻辑域和 InitSpec，状态/值/JSON/verifier 同步。
- 定义 OpDescriptor 及 grhsim.edge-detect、独立写口、system-task、system-function、dpi-call、bitSelect/prioritySelect；CPU maskedOr 属于特化方言。公共 op 不复制定义，基础写口/调用契约不变。
- 删除 assignAs，统一等宽 assign；完整输入/输出类型含 shape 决定传递或合法转换。同步 producer、ingest、工厂、优化、store/load、clone/flatten、view 和 emit，不再有 assignKindFor 双 kind 选择。
- 补齐实例身份、保守 revision 和 typed session getter，覆盖 mutation、freeze/压缩、符号/归属及 load/clone。旧 ID/SymbolId 数字不作永久身份。
- 定义转换/拆分的阶段元信息、文本 owner 属性 schema 和所有阶段的统一 GRH JSON。未适配的通用 transform 明确拒绝 GrhSIM 形态；原 GRH simplify 不增加仿真 role/partition 模式。

退出条件：类型/shape/域/assign 正负例、未知方言/版本、JSON、clone/dryrun 和 ID 重建通过；原 GRH 前端/transform/emit 无新增失败。

### R2：grh-to-grhsim，无分区转换

- 在原图按需转换写口及 system-task / system-function / DPI call；创建 edge-detect 与多事件 OR，将 fire 接到新写口/调用的固定位置。
- 实际完成显式逻辑域策略；保留原声明、DPI import、公共计算/数组/读口、InitSpec、writerOrder、sample identity 和来源。
- 不提取 Event/Output 锥，不生成监视任务 output-end 历史，不分类 small/large，不产生任何虚拟分区或跨 pass 规划结构。
- converted checkpoint 完成 store/load/verify；允许等价检测器尚未去重，不要求转换器替代 simplify。

退出条件：转换结果为平整无分区大图；基础契约保持，每个原 writer 只替换一次；任务/函数/DPI 无遗漏。原 clock 误接 fire、非法脉冲、漏转原写口和带分区的转换结果等负例被拒绝。

### R3：无分区优化与数组

- 独立 grhsim-simplify 在 converted 图上做全图化简，不包装调用整套 GRH simplify。全局共享状态等价合并/窄化在此维护全部引用。
- 覆盖共享 edge-detect 的合并及反例：同输入/edge/prevInit/完整类型/采样规则可共享结果和历史，不同边沿/初值/采样范围不能合并；消费者重接后每 round 历史仅更新一次。
- DPI、random 和系统任务保持 effect/sample identity，不因 CSE/DCE 增减调用。必要的非确定性结果缓存按既有行为迁移。
- pack-bit-registers 继续默认开启，适配新脉冲写口的控制签名，更新打包读写、初值和全部声明绑定；不再依赖旧 event_edges 或 CPU mapping。
- recover-masked-or 继续默认开启，适配无分区匹配及方言契约；bitSelect/prioritySelect 规则在 grhsim 模块。
- 覆盖数组构造/索引读/写-mask-fill/等宽 assign、混合 packed 消费、shape 与位序；保留当前合法边界和明确拒绝。
- comb-pack 不迁移，专用 fixture 删除；混合套件的有效用例及通用 provenance 覆盖保留并改用现存变换验证。

退出条件：优化前后执行等价，全图 edge-detect 合并有效且历史/调用次数正确；仍没有虚拟分区。S9 新优化单独排期，不混入迁移收益。

### R4：依次拆区域、活动度切图和 sink 顺序

本阶段已有 [R4 验收](r4-validation.md)所列的变换和 interpreter 证据。当前实现按 effect/sample identity 约束采用单个原调用与 held sample，在图上记录 effectPolicy。[旧 Output 重复 DPI 调用](baseline-and-capabilities.md#r4r5-的旧-dpi-行为差异)的冻结日志保留；R5 新旧 C++ 已确认次数及顺序/触发差异。因此 R4 内部执行对照不等于完整兼容通过，不能仅把差异列出来就关闭 R5 门禁。

按以下四个独立交付点推进，不能只交付一个最终“partitioned”结果：

| 顺序 | Pass | 交付与验证 |
| --- | --- | --- |
| R4.1 | grhsim-split-event-and-output | 首次提取事件输入锥/检测器与输出端口/时隙任务锥，建立 General/Event/Output；保留共享原锥、采样身份、粘滞触发和 output-end 历史 |
| R4.2 | grhsim-split-nonsink-and-sink | 按总逻辑字节数分类状态，将 General 拆成 nonsink/small-sink/large-sink；明确共享/私有计算及 General 采样、large 延迟提交 |
| R4.3 | grhsim-partition-nonsink | 仅对 nonsink 做活动度 node/超节点切图与一轮可选 boundary clone；无模块、跨图端口或函数大小预算 |
| R4.4 | grhsim-partition-sink | 按 clock/fire、enable/门控、writerOrder 细分两类 sink，发布第一个跨 pass 额外产物 SinkSchedule |

- 各阶段 owner 唯一，父容器不直接持有后代计算；属性是归属事实来源。带地址 read 与地址/数据计算可以同分区。
- R4.3 后如需再 simplify，仅在当前完整叶 owner 内执行；CSE/常量池/alias/used-bits 不能跨界合回 clone，共享状态不能局部窄化。粗 sink 内合并的纯锥由 R4.4 按最终分组私有化、重接；不复制 effect，不增加 role。
- SinkSchedule 标注 sink 参数采样、small next、大状态提交的有序 run 及必要 nonsink 依赖，不扩张为整个 CPU 计划。Output 的 output-end 由图中语义及六段协议保证。不同 clock 组的 writerOrder 交错时，不得为整组执行重排覆盖。
- 所有阶段完成单图 JSON 往返和重启；ID freeze 重编号、generation 重置、symbol rename/转交、load/clone 后归属可恢复。
- sink pass 在最终 revision 原子发布完整调度，失败/改图/改分区配置后失效。此前不发布统一 CPU plan 或另一份成员树。

退出条件：每个步骤的输入/输出独立可检查；Event/Output 确实在 R4.1 提取而不是在转换或 emitter 补做。动态地址与状态变化依赖保持，调度覆盖优先级交错、掩码和多事件；重启及重跑幂等。chunk/TU 参数不参与任何分区。

### R5：cpu-st-cpp emitter 与全部函数 chunk

- 实现 **wolvrix/lib/emit/grhsim/cpu-st-cpp.cpp**，公开 ID grhsim-cpu-st-cpp，通过现有 EmitOptions/session 读取统一图和有效 SinkSchedule。
- 发射内部集中建立布局、named stores、初始化、激活/fanout、数组访问/别名/快照、函数及 TU 数据，不增加公开 planning pass 或可执行 IR。
- 保留六段 eval、端口、DPI/系统任务/函数/random、FST/profile 和构建清单；保持原宽值 ABI、原生两态宽 _BitInt 及调用方缓冲策略。
- max-function-lines 统一限制所有生成函数的最终定义行数，包含 init/eval、六段、Event/Output、两类 sink、nonSink、trace/profile、调用包装和 helper；计入函数支架、guard 和 chunk 调用，dispatcher 超限也继续拆分。chunk 仅是 emit 参数，不产生虚拟分区。
- chunkFrame 保存跨 chunk 活跃局部值/控制状态，以及为满足声明行数预算而 spill 的不可分语句局部值，保持初值和原局部寿命，以引用/指针传递；状态/nonSink/写参数语义快照不因拆块移动或丢失。
- 写文件前验证调度/阶段/支持范围，源码 staging 与最终清单发布避免留下半套输出。

退出条件：同图/同 SinkSchedule 在多个函数预算和 TU 参数下生成、编译、执行等价；扫描所有生成函数实际行数达标。tiny 预算强制拆 Event/Output/init/trace 等各类函数，保持循环/early return、采样次数、历史和提交顺序；不可拆超预算有明确诊断。六段×数组/调用/初始化的全部矩阵与冻结旧模型逐项比较；仅用户明确批准的原调用重复消除和独立调用旧排序差异可另列为 accepted，原始差异及 equal 保留。

### R6：入口与整机切换

- Python 普通 design/pass/emit、XS、HDLBits、xs-bugcase、ROB、reemit、benchmark、归属/profile 工具迁入新顺序，删除独立 model key/JSON 依赖。
- 原 GRH 管线之后依次运行 grh-to-grhsim、无分区优化、两次拆区域、partition-nonsink、partition-sink 和新 emitter。无隐藏旧转换器/调度 fallback。
- 分阶段 checkpoint 重启及 SinkSchedule 重建进入 Make；兼容旧 target 名称只转发新路径。
- 同一原 SV 重生 candidate；ROB 同 trace 全输出无排除比较，XS/HDLBits/bugcase 保持当前黄金检查，补齐调用/状态/trace/profile 证据。

退出条件：功能、重启、同 trace 行为比较及新版完整编译预算通过。2026-10-25 用户取消旧侧性能基线与交替性能 A/B；不再将旧侧生成、编译或运行性能对照作为退出条件。先完成新版编译速度，再开展 S9。

### R7：删除独立 IR 和退役入口

| 删除范围 | 前置条件与处置 |
| --- | --- |
| include/grhsim/ir、lib/grhsim/ir | 图/类型/op/verify 全部使用统一 GRH，没有改名后的 SimGraph/CpuProgram |
| 旧 grh_to_grhsim 转换器 | 按需转换已进入 grh-to-grhsim；公共实体复制和名字翻译直接删除 |
| 旧 grhsim/dialect、pass registry/PassManager | 有效契约/变换按新步骤迁出，独立基础设施删除 |
| comb-pack 全部代码及入口 | R3 已删除实现、注册、构建、pipeline/CLI/Make 开关、报表及专用 fixture；R7 只复查无残余入口 |
| 旧 CPU backend/mapping/planner | sink 顺序已归 partition-sink，其余有效生成分析归 emitter；NUMA/core/task 镜像删除 |
| 独立 JSON/io、Python grhsimModels/API | 统一 GRH checkpoint/普通 design 已可重启，旧 v3 loader 不长期保留 |
| kAssignAs/双 kind 接口与旧构建引用 | 全部 producer/消费者、导出、CLI/help/正式规范同步清理 |

删除前扫描 include/link/export/脚本与生成模型的实际依赖；仍被新模型使用的 runtime、task/FST helper 保留或迁移，不能按旧目录名误删。历史报告和冻结模型允许留在只读证据目录。

退出条件：生产路径没有 GrhSimModel / lowerGrhToGrhSim / run_grhsim_pass / grhsimModels、独立 IR 或 comb-pack 可执行入口；完整干净重建及必要回归通过，不能只依赖已有对象文件。

### R8：规范与证据收口

更新正式类型/op/JSON、各 pass、六段 emitter、统一 chunk 和标准 Make 流程文档；每项能力列出实现/测试/报告、支持及拒绝边界。[完成定义](README.md#5-完成定义)逐项满足后更新进度；S9 以该版本为直接基线。

## 3. 验证矩阵

| 类别 | 必须检查 |
| --- | --- |
| 转换 | 平整无分区；新 edge/write/task/function/DPI 完整；原契约不变，无双重 writer |
| 全图 simplify | 等价 detector 可合并且只更新一次历史；不同 edge/init/scope 不合并，DPI/random 调用次数不变 |
| Event/Output 提取 | 仅在 split-event-and-output 发生；门控时钟、状态/动态地址闭包、输出收敛后读取、共享原锥和时隙历史 |
| General 拆分 | 三个区域、唯一 owner、小数组/大标量、阈值、私有/共享依赖和 large 参数先采样 |
| 活动度切图 | nonsink 多级归属、合法 clone、动态地址激活，不引入模块或函数行数策略 |
| sink 分区/顺序 | clock/gate/priority、交错 writer、mask/whole/indexed/fill 覆盖、small next/large/output-end |
| 分区后 simplify | 同根不同叶 clone 不合回，边界输出/完整类型保持，将外部输入视为不透明值，无局部共享状态窄化 |
| 六段/副作用 | 多 round、旧值、无变化 eval、首 eval/重 init、不收敛、调用日志及 finish/error 行为 |
| 数组/类型 | rank 1/2/3、[1]、部分/动态索引、mixed packed、等宽异型 assign、别名/非零 fill/readmem/宽叶 |
| 全部函数 chunk | 最终行数含支架/dispatcher，跨块数组与控制状态，所有函数类别，预算变化不改分区/调度 |
| 生命周期 | freeze/压缩、symbol rename/转交、load/clone、错 session/type/design/top/revision、失败/清空与重建 |
| 来源与整机 | declaredSymbols/generateGroups/FST/profile/模块归属、HDLBits/bugcase/ROB/XS 同输入比较 |

四态 IR 合法性与 CPU 明确拒绝的组合分别验证。测试要比较实际执行结果和调用顺序，不能只看更少 op、源码或 checksum。

## 4. Make 门禁

实施时复核 Makefile，下列入口需要按新流程迁移；已有旧实现执行记录只计入 R0，不视为迁移通过：

| 现有入口 | 迁移要求 |
| --- | --- |
| make test_wolvrix | 公共回归及删除旧代码后的干净重建 |
| make test_array_create、test_array_create_cpu | 统一图与新 emitter 的数组执行能力 |
| make test_grhsim_simplify、test_grhsim_whole_opt | 无分区 simplify/edge 合并、打包及分区后隔离；删除 comb-pack 专用项 |
| make test_grhsim_event_lowering、test_grhsim_split_phases | 保留有效行为 fixture，分配给转换、split-event-and-output、split-nonsink-and-sink |
| make test_grhsim_select_state_stores、test_grhsim_cpu_phases、test_grhsim_cpu_stores | 状态区域分类、sink 调度及 emitter 存储/六段 |
| make test_grhsim_cpu_phase_emit、test_grhsim_masked_or | 生成模型矩阵和保留特化计算 |
| make run_all_hdlbits_grhsim_tests | 黄金 trace，直接走当前 GrhSIM 流程 |
| make run_xs_bugcase_grhsim、check_sim_refactor_baseline | 现有 bugcase/行为基线，不扩张排除项 |
| make xs_grhsim、xs_grhsim_build_emu、run_xs_grhsim_emu | XS 标准重生/编译/运行，候选在隔离目录 |
| make benchmark_grhsim_ir | 保留历史诊断入口；当前不执行旧侧性能 A/B |
| make measure_remove_grhsim_ir_resources REMOVE_GRHSIM_IR_RESOURCE_TARGET=build_remove_grhsim_ir_xs_from_sv | 连续测量 aggregate-all 原始 SV 到链接好的 emu；生产优化与 24 job 保持，wall 必须小于 2100 秒 |
| make -C testcase/xs-components rob-bench-proof 等 | 同 trace 全输出证明，不复制 gsim 排除项 |

同组省略 make 前缀的名称也必须作为 Make target 调用，不直接运行其内部命令。

R1–R4 入口已存在：make test_remove_grhsim_ir_foundation、make test_grh_to_grhsim、make test_grhsim_transforms、make test_grhsim_virtual_partitions 和 make test_grhsim_sink_schedule。两个 R4 入口均运行虚拟分区、sink 调度及变换三个套件；实际结果与产物见进度和 R4 验收。R5/R6 使用以下入口，当前实际通过证据见 [2026-10-26 验证报告](20261026-r5-r6-validation.md)：

- make test_grhsim_cpu_st_cpp：新 emitter 的功能矩阵、全部函数 chunk/实际行数及生成模型执行。
- make compare_remove_grhsim_ir：固定旧/新模型同输入比较输出、状态投影和调用日志；显式选择 single-original-call-source-order 策略并保留原始 equal/批准项/未解决项。该策略只批准 dpi_bit_abi 的精确重复调用消除，以及 smoke/TU 中参数/结果不变的 dbl→inc 与原图 inc→dbl 差异；REMOVE_GRHSIM_IR_EFFECT_POLICY=strict 可复查严格比较。
- make compare_remove_grhsim_ir_rob：从冻结原 SV 重新生成候选，同 trace 做 ROB 全输出无排除比较；r6-rob-contiguous-fresh 已比较 4,394,996,424 bytes 相同，exclusions=0，尚不表示性能通过。
- make reemit_remove_grhsim_ir_rob：从统一图 checkpoint 重建调度并重发；r6-rob-storefix 已完成全输出零排除比较，不能替代完整 SV 生成。
- make test_grhsim_flow：统一图各阶段重启、调度重建与源码归属的局部执行检查。
- make test_remove_grhsim_ir_tooling / test_grhsim_grh_reader：标准入口的退役开关拒绝、保留开关转发及原生图读者反例；make inspect_remove_grhsim_ir_graph 保存指定 checkpoint 的符号/类型/状态统计。
- make test_grhsim_provenance：检查生成 sidecar、脏/未跟踪源码身份、发布一致性及比较前后绑定；make inspect_remove_grhsim_ir_families / inspect_remove_grhsim_ir_pairs 提供原生 family/paired 诊断，可显式绑定原生执行计数，不声称支持旧动态定价。
- make test_grhsim_execution_counts / inspect_remove_grhsim_ir_execution / inspect_remove_grhsim_ir_rob_execution：验证或读取原生图/完整生成源码绑定的两次独立执行计数；writer visits 与真实 effects 分开，缺失 packed 原成员不补零，插桩模型不参与性能计时。
- make profile_remove_grhsim_ir_rob：原 trace 的 bounded 运行与 perf 热点诊断，不代替全输出行为比较。
- make benchmark_remove_grhsim_ir_runtime：保留历史工具及回归记录；用户已取消旧侧性能基线与交替 3+3，不再运行或将其作为当前验收门禁。

make check_remove_grhsim_ir 审计完整生产 C++/Python 源码中的退役定义/调用、旧实现目录、CMake 源列表、实际 compile_commands，以及当前完整核心库/Python binding 的符号；同时检查新路线对象的未解析依赖。可用 REMOVE_GRHSIM_IR_AUDIT_MODEL 指定生成库，检查其源码与编译库不依赖编译器/独立 IR。报告默认保存 ptmp/remove-grhsim-ir/production-audit.json，含源码和库摘要。允许冻结证据、退役选项拒绝诊断及历史报告读者，不要求全仓库旧名称零出现；当前安装包的导出另外由 test_grhsim_flow 运行时检查。变更实现后重新构建并复跑；此门禁不替代整机或性能检查。

## 5. 功能与性能口径

首要门槛是冻结旧实现→新实现同输入行为比较。ROB 全输出无排除比较；XS/HDLBits/bugcase 保持原观测契约；副作用按日志比较次数、顺序和参数。独立参考仿真器的历史差异另列，不能放宽旧→新比较。用户已批准单个原调用及保留原图独立调用顺序，比较器仅将已确认的旧 Output 重复调用消除和 smoke/TU 的精确排序差异分类为批准项；原始 equal 仍为 false，accepted 要求无任何未解决差异。历史触发错误已经修复，不能作为批准项掩盖；冻结基线不变，R5/R6 不据局部批准标记完成。

R0 固定同机、工具链/flags、线程、seed、trace、warm-up、周期和 chunk/TU 选项。分别记录 grh-to-grhsim、全图优化、两次拆区域、partition-nonsink、partition-sink 和 emit；emit 内部再记录布局/访问/激活/chunk 耗时及内存。记录生成源码/函数/chunk/TU、chunkFrame/快照开销、编译 wall/RSS、运行吞吐/RSS，以及分区/边界/clone/round/激活/数组 pack 数。

2026-10-25 用户明确取消旧侧性能基线和正式交替 3+3 A/B，优先提升新版编译速度。当前性能验收固定为 preserve-aggregate=all 的完整原始 SV → 链接好的 emu 小于 2100 秒；保持生产优化、-O3 -march=native、24 个编译 job 及 JSON roundtrip，连续计时并记录峰值同时 RSS、工具链、输入和实际加载库身份。检查点恢复、分段数字相加或生成完成都不能替代完整二进制验收。历史 A/B 结果只保留事实，不再追跑旧编译器或建立新旧性能比值。

大数组还需确认没有逐行循环内重复整表 pack、错误快照或大型返回值复制。单纯变少的图节点、JSON 或函数数量不是运行收益证明。架构迁移与 S9 新优化分开比较、单独归因。

## 6. 状态记录

阶段只有满足对应退出条件才标记完成；未执行的构建、功能和性能检查均写“未运行”。旧 checkpoint/可执行基线始终只读，新入口不静默 fallback。调度过期必须修复失效/重建，不能修改 stamp 绕过；不以历史通过数代替本次结果。
