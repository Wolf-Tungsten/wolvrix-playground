# 旧实现能力与冻结证据

本文件记录 R0 的迁移依据，更新于 2026-10-24。源码路径指冻结时的旧实现；新步骤指 [目标管线](passes-and-emitter.md)，不表示该步骤已经实现或验收。

## 冻结范围

证据根目录为 [ptmp/remove-grhsim-ir/r0-20261024](../../ptmp/remove-grhsim-ir/r0-20261024/)。该目录保持旧输入和旧产物，candidate 使用另一目录。

| 证据 | 已完成的内容 | 证明边界 |
| --- | --- | --- |
| manifest.json、source.tar.gz、工作树 diff/status | 首次冻结 4,768 个产物及主仓库/子模块脏源码；wolvrix 起点为 0627d04637123953af1bfd0dd8997364da341773 | commit 加 diff/untracked 摘要共同确定基线，不能只用 commit 重建 |
| old-tests.log | 改核心前通过 Make 公共回归，67/67 | 旧实现回归结果 |
| replay.json | ROB 同一 trace 重放 100,050 cycles；4,394,996,424 bytes 全输出相同，exclusions=0 | 旧模型可复现，尚非旧→新等价证明 |
| inputs-supplement.json | 补充 2,156 条 XS 实际 filelist 输入、include、read args、历史日志、CoreMark image、NEMU 库和旧共享库记录 | 原始源码仍以首次 manifest/source.tar.gz 为准；补充清单不重置基线 |
| frozen/wolvrix/build/libwolvrix-lib.so | R1 首次链接前冻结的配套旧库 | 冻结测试二进制不能动态链接新库来冒充旧路线 |
| old-fixtures.json、old-fixtures.log | 冻结旧 emitter 测试配旧库运行，976 个产物，包括生成源码/driver/可执行、69 份 dump_state.txt、4 份 task_output.txt | 旧 fixture 的行为、任务文本及最终状态证据；不是新路线结果 |
| [r0-observations-v2/manifest.json](../../ptmp/remove-grhsim-ir/r0-observations-v2/manifest.json)、prepared.json、各 fixture 的 observations.jsonl | 8 个冻结源码 fixture 的副本保留原断言并插桩执行；168 条 init/eval 记录、66 次 DPI、30 条 task 输出、18 次 random 采样 | 这份 R0 证据仅记录旧侧；后续新旧 C++ 比较另存 r5-observations，不覆盖冻结结果 |

ROB 输出 SHA256 为 `688ac2f6e9c5509eb00dad368ead600a07ec27d956b1ec9a429d8e46309a7df1`。XS 配置补录 seed=0、coremark-2-iteration.bin；历史日志 good trap 为 guest cycles=296754，该数字不是本轮新运行。生产默认 comb-pack 关闭、pack-bit-registers 开启；实验开关与默认配置分别核对。

复现入口均经过 Make：capture_remove_grhsim_ir_baseline、replay_remove_grhsim_ir_baseline、supplement_remove_grhsim_ir_baseline、replay_remove_grhsim_ir_fixtures、replay_remove_grhsim_ir_observations。冻结只读快照不能被后续 capture 覆盖成新实现。观测目标也拒绝覆盖已完成目录；另一次运行应显式指定新的 REMOVE_GRHSIM_IR_OBSERVATIONS。

## 能力到新步骤的映射

以下路径均相对 wolvrix/；同一 fixture 可以覆盖多个能力，不能将表格行数当测试数量。

| 能力 | 旧源码 | 旧测试/观测 | 新归属 |
| --- | --- | --- | --- |
| 公共计算、完整 shape、arrayCreate/sliceArray、assign | lib/grhsim/convert/grh_to_grhsim.cpp、dialect/core.cpp、pass/canonicalize_compute.cpp | tests/grhsim/test_array_create.cpp、test_grhsim_simplify.cpp | 公共语义留 GRH；grh-to-grhsim 保留；独立 grhsim-simplify 改写 |
| 常量、used-bits、bitwise/mux、bitSelect/prioritySelect | lib/grhsim/pass/{const_fold,used_bits,bitwise_predicates,bitwise_muxes,mux_chain_fold}.cpp | test_grhsim_simplify.cpp、test_grhsim_whole_opt.cpp、test_cpu_phase_emit.cpp | R3 无分区优化；select op 契约属于 grhsim |
| 共享状态/初值与 bit-register packing | lib/grhsim/pass/{simplify_internal,pack_bit_registers}.cpp | test_grhsim_whole_opt.cpp、test_cpu_phase_emit.cpp 的 packed/state fixture | R3 维护全部读写和来源引用；不依赖分区或 CPU mapping |
| maskedOr | lib/grhsim/pass/recover_masked_or.cpp、dialect/cpu.cpp | test_masked_or.cpp、test_cpu_phase_emit.cpp | grhsim-recover-masked-or；grhsim.cpu 契约；emitter 生成 |
| 原始事件/多事件、检测器历史初值 | lib/grhsim/convert/grh_to_grhsim.cpp、pass/lower_edge_detect.cpp | test_grhsim_event_lowering.cpp、test_cpu_phase_emit.cpp | grh-to-grhsim 创建 detector/fire；grhsim-simplify 等价合并；emitter 分配历史槽 |
| 独立 fire 写口、mask/index/fill/latch | lib/grhsim/convert/grh_to_grhsim.cpp、ir/verifier.cpp | test_grhsim_ir.cpp、test_cpu_stores.cpp、test_cpu_phase_emit.cpp | grhsim op；grh-to-grhsim 转换；sink pass 顺序；emitter 实现 |
| system-task/function、DPI import/call、ABI | lib/grhsim/convert/grh_to_grhsim.cpp、backend/cpu_phase_emit.cpp | test_cpu_phase_emit.cpp 的 monitor/strobe/DPI bit ABI 与 random fixture；新增逐次调用日志 | grh-to-grhsim 保留 effect/sample identity；R4 单原调用与旧 Output 重复调用的差异见下文；emitter 生成 |
| Event 输入锥、Output 端口锥、共享副本 | lib/grhsim/pass/{classify_event_inputs,extract_output_cones,cone_extract,split_phases}.cpp | test_grhsim_split_phases.cpp、test_cpu_phase_emit.cpp 的 CDC/状态驱动 clock | grhsim-split-event-and-output 首次创建三区域；无额外持久成员树 |
| monitor/strobe、粘滞事件、变化历史 | lib/grhsim/pass/migrate_timeslot_tasks.cpp、backend/cpu_phase_emit.cpp | monitorFreeTest、monitorEventTest 的任务文本/次数 | grh-to-grhsim 先转换 op；split-event-and-output 提取并合成所需 history；emitter output-end |
| small/large 状态策略、General 参数采样 | lib/grhsim/pass/select_state_stores.cpp、backend/cpu_layout.cpp | test_grhsim_select_state_stores.cpp、test_cpu_stores.cpp | grhsim-split-nonsink-and-sink 分类并写属性；emitter 布局与快照 |
| nonSink 活动度分区/层次、boundary clone | lib/grhsim/backend/{cpu_partition,cpu_clone_shared}.cpp | test_cpu_phases.cpp、test_cpu_phase_emit.cpp 的 clone/activation fixture | grhsim-partition-nonsink；分区后 simplify 仅在完整叶内 |
| sink 分组、覆盖次序、large commit | lib/grhsim/backend/{cpu_partition,cpu_schedule,cpu_emit_plan}.cpp | test_cpu_stores.cpp、test_cpu_phase_emit.cpp 的多写/commit fixture | grhsim-partition-sink 发布 SinkSchedule；emitter 按顺序生成 |
| 六段、固定点、current/next、激活/fanout | lib/grhsim/backend/{cpu_layout,cpu_schedule,cpu_phase_emit}.cpp | test_cpu_phases.cpp、test_cpu_stores.cpp、test_cpu_phase_emit.cpp | 六段语义不变；归属在图，sink 次序在 SinkSchedule，其余发射数据私有 |
| init/readmem/random、有序覆盖、重 init | lib/grhsim/convert/grh_to_grhsim.cpp、backend/cpu_phase_emit.cpp | test_cpu_phase_emit.cpp 的 init/readmem/random fixture | 原声明的 InitSpec；转换显式域投影；emitter 初始化 |
| 数组 direct/packed 双消费、动态索引、别名快照、宽值 ABI | lib/grhsim/backend/cpu_phase_emit.cpp | test_array_create.cpp、test_cpu_phase_emit.cpp；S8 ROB 全输出 | R3 保留语义；emitter 私有访问/寿命分析；S9 新优化另行验收 |
| FST/profile、声明与模块来源 | lib/grhsim/convert/grh_to_grhsim.cpp、backend/cpu_phase_emit.cpp | tests/transform/test_origin_attribution.cpp、tests/store/test_store_load_origin_attrs.cpp、旧生成模型及 ROB/XS 工具 | GRH 来源/声明绑定全程维护；emitter trace/profile |
| checkpoint/Python/标准工作流 | lib/grhsim/io/json.cpp、旧 Python model API、生产脚本 | test_grhsim_ir.cpp、XS/HDLBits/ROB Make 流程 | 统一 GRH JSON 和普通 design/pass/emit，R6 切换 |
| 函数/TU/frame 组织 | lib/grhsim/backend/{cpu_emit_plan,cpu_phase_emit}.cpp | test_cpu_phase_emit.cpp 的 tinyTu fixture | emit/grhsim/cpu-st-cpp.cpp 内统一按行数拆全部函数，跨块局部值进 chunkFrame |
| comb-pack、独立 IR/PassManager/mapping 壳 | lib/grhsim/pass/comb_pack.cpp、ir/、io/、pass/pass.cpp | 生产默认关闭 comb-pack；专用实验不是保留依据 | comb-pack 删除；其余旧基础设施待对应能力迁移验收后删除 |

## 逐次观测与证据边界

通过 `make replay_remove_grhsim_ir_observations` 构建并运行以下旧侧 fixture 的副本：dpi_smoke、dpi_smoke_tu、dpi_bit_abi、random_function、random_function_tu、monitor_free、monitor_event、monitor_event_tu。先对照 old-fixtures.json 校验所有原始源码/header/Makefile 的摘要，再在副本中记录实际 DPI mock 和 RNG helper 的调用，保留原输出断言。prepared.json 同时记录原始及插桩源码摘要；未修改冻结目录。

每条记录含 epoch、step、inputs、outputs、states、effects；step=-1 表示 init，其余对应冻结 driver 的 eval 输入。manifest 中的完整类型给出总宽、shape、signedness 和 domain，输出/状态按原声明投影，剥离物理 store 布局；DPI effects 保留实参、原始返回值和输出参数，random effects 记录实际采样值，task effects 保留文本及顺序。当前 fixture 不混用这三类 effect，不据此宣称验证了混合 DPI/task/random 的交错顺序。

每个 driver 在同一个模型对象上初始化三次，验证每次完整观测序列相同；所有单文件/TU 成对 fixture 的规范化日志摘要相同。v2 是有效证据；v1 的 random 输入/echo 类型元数据曾错误写成 8 bit，实际为 bool/1 bit，保留旧目录但不再引用其类型信息。

本轮实际执行的冻结 DPI fixture 覆盖 input/return/output、结果保持与 bit ABI。另一个旧 cpu_calls_main.cpp 中的 inout/wide/string 断言未执行：配套的废弃 grhsim-cpu-emit-tests 二进制与冻结库 ABI 不兼容，其失败日志不计作通过证据。R2 已有 inout 转换/签名及执行 oracle 覆盖，但不能代替旧 C++ ABI 验收；R5 必须补齐该矩阵。

R0 已交付旧行为冻结、能力映射和上述旧侧共同观测格式。R5 初次接入同输入/观测格式时，[历史严格比较](../../ptmp/remove-grhsim-ir/r5-observations/comparison.json)的 outputs/states 相同、DPI effects 未匹配；该报告原样保留。随后修复触发/次数并按用户选择记录精确的调用与排序差异，最新 accepted=true 结果见本节末段，不将历史失败回填为成功。更广泛的状态/ABI/混合 effect 矩阵仍属 R5/R6 门禁。R2/R3 的独立 oracle 对照原 GRH 与转换/优化后的图，R4 对照无分区参考与 owner/SinkSchedule 驱动的分区 interpreter；这些局部证据不能替代冻结旧 C++ 比较。投影轨迹允许 DCE 消去没有可观测变化的内部 round，effect 序列仍严格比较。

## R4/R5 的旧 DPI 行为差异

冻结的 dpi_bit_abi 在每次 eval 中实际调用 DPI 两次：一次在 General 的 sn_0()，一次在 Output 的 pOutput_c0()。源码见 [冻结生成文件](../../ptmp/remove-grhsim-ir/r0-20261024/old-fixtures/cpu_phase_emit/dpi_bit_abi/model/grhsim_phase_dpi_bit_abi_tu0.cpp)，逐次证据见 [observations.jsonl](../../ptmp/remove-grhsim-ir/r0-observations-v2/dpi_bit_abi/observations.jsonl)。输入 0 时两次原始调用均为 `[in=0, return=0, out=2]`，输入 1 时均为 `[in=1, return=3, out=2]`。输出结果断言无法揭示这次额外调用。

dpi_smoke 还记录到同一时钟沿上 dbl 先于 inc，free inc 会随另一输入的活动再次执行；不得由图遍历顺序或一次输出结果推断实际调用顺序/次数。

R0 原样冻结两次调用，不修改旧日志。R4 实现按 effect/sample identity 约束采用**单个原调用**：General 中保留原 DPI/random op，提取 Output/Event 锥时使用 held sample，不克隆调用；图中显式记录 `grhsim.effectPolicy=single-original-call`。2026-10-25 用户明确接受这一目标语义，见 [决定与精确验收范围](20261025-single-call-decision.md)。

R4 的执行对照验证该选择内部的输出、状态与 effect 身份/顺序，也包含 task/random 混合序列；[R4 验收](r4-validation.md)列出当时证据，该阶段未运行新 C++ emitter。后续 [R5 严格比较](../../ptmp/remove-grhsim-ir/r5-observations/comparison.json)已确认：dpi_bit_abi 由每次 eval 两次变成一次，共 6 条 effects 差异；dpi_smoke 及 TU 版本各有 9 条 effects 差异，包含同沿调用顺序和 falling-edge eval 的额外 free 调用。其余 random/monitor fixture 无差异，全部 fixture 的 outputs/states 相同。

冻结记录、原始严格比较和失败结果继续保留。2026-10-25 用户进一步明确保留原图独立调用顺序；新报告区分严格相等与已批准策略下的接受情况。仅 dpi_bit_abi 的精确 Output 重复调用去除，以及 dpi_smoke/TU 中两个完整调用记录相同的 `[dbl, inc] → [inc, dbl]` 排序差异归入已批准项，不豁免触发、调用增减、参数或结果变化。[最新比较](../../ptmp/remove-grhsim-ir/r5-observations-source-order/comparison.json)保留 18 条原始差异，equal=false、accepted=true，未解决项为 0。R5/R6 的其他门禁仍未完成。
