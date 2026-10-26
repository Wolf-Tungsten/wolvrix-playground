# 统一 GRH 仿真：能力、实现与证据

更新：2026-10-26。R0–R8 已完成；删除后的最终验证结果见
[R7/R8 报告](20261026-r7-r8-validation.md)。本表是现行实现索引，历史
[R0 清单](baseline-and-capabilities.md)继续保存迁移前事实。
R8 后 named store 与 phase helper 的修订、最终回归及 ROB/XS 代码检查见
[store/phase 修复](20261026-store-phase-fix.md)，本次未复用历史整机性能结论。

正式契约以 [标准流程](../../wolvrix/docs/grhsim.md)、
[GRH 类型/op](../../wolvrix/docs/grh/grh-ir.md)、
[JSON](../../wolvrix/docs/grh/grh-json-spec.md)、
[仿真方言](../../wolvrix/docs/grh/grhsim-dialect.md)、
[transform](../../wolvrix/docs/transform/grhsim-transforms.md) 和
[emitter](../../wolvrix/docs/emit/grhsim-cpu-st-cpp.md) 为准。

## 能力映射

下表的测试均通过项目 Make 入口运行。公共 CTest 负责图/转换和模型生成，
`test_grhsim_cpu_st_cpp` 另行编译并执行生成模型；不能将前者当作后者的证据。

| 能力与边界 | 主要实现 | 测试入口/用例 | 执行证据 |
| --- | --- | --- | --- |
| 统一 LogicalType、shape/domain、等宽 assign、InitSpec；异型/溢出构造拒绝 | [grh.hpp](../../wolvrix/include/core/grh.hpp)、[verify.cpp](../../wolvrix/lib/transform/verify.cpp) | `test_remove_grhsim_ir_foundation`、`test_array_create`；[基础](../../wolvrix/tests/grh/test_grh_sim_foundation.cpp)、[数组](../../wolvrix/tests/grh/test_array_create.cpp) | R7/R8 公共 64 项及数组域负例 |
| GRH JSON v2、方言版本、来源、重载/clone 身份；旧 kind/未知方言拒绝 | [store.cpp](../../wolvrix/lib/core/store.cpp)、[load.cpp](../../wolvrix/lib/core/load.cpp)、[ops.cpp](../../wolvrix/lib/transform/grhsim/ops.cpp) | 基础/方言套件、`test_grhsim_flow` | 10 个分阶段 checkpoint 生成执行与原始 SV roundtrip |
| 原图六类写口、edge、task/function/DPI 转换；源形态先检查，无独立 model | [grh-to-grhsim.cpp](../../wolvrix/lib/transform/grhsim/grh-to-grhsim.cpp) | `test_grh_to_grhsim`；[转换测试](../../wolvrix/tests/transform/test_grh_to_grhsim.cpp) | 公共回归、HDLBits、27 XS bugcase |
| 全图/完整叶 simplify、detector CSE、状态窄化/合并；effects 和跨叶 clone 保留 | [simplify.cpp](../../wolvrix/lib/transform/grhsim/simplify.cpp)、[used-bits.cpp](../../wolvrix/lib/transform/grhsim/used-bits.cpp) | `test_grhsim_transforms`；[执行 oracle](../../wolvrix/tests/transform/test_grhsim_transforms.cpp) | [R4 报告](r4-validation.md)、R7/R8 公共及生成执行 |
| bit-state packing、maskedOr、bitSelect/prioritySelect；不合格类型/控制不改写 | [pack-bit-registers.cpp](../../wolvrix/lib/transform/grhsim/pack-bit-registers.cpp)、[recover-masked-or.cpp](../../wolvrix/lib/transform/grhsim/recover-masked-or.cpp)、[ops.cpp](../../wolvrix/lib/transform/grhsim/ops.cpp) | transform/oracle 与生成模型矩阵 | 冻结 168 条逐次观测、ROB/XS |
| Event/Output 闭包、动态地址、sticky timeslot、typed output-end 历史；原 effect 不复制 | [split-event-and-output.cpp](../../wolvrix/lib/transform/grhsim/split-event-and-output.cpp) | `test_grhsim_virtual_partitions`；[分区测试](../../wolvrix/tests/transform/test_grhsim_virtual_partitions.cpp) | 多 round、门控时钟、无变化 eval、monitor/strobe 执行 |
| 按总字节划分 small/large；writer 私有锥与 General 参数采样 | [split-nonsink-and-sink.cpp](../../wolvrix/lib/transform/grhsim/split-nonsink-and-sink.cpp) | 分区与 emitter 小/大状态、whole-array-before-image 用例 | ROB 全 trace、旧值/别名执行矩阵 |
| 活动度分区、合法 DAG、边界 clone、完整叶归属；工作预算不等于函数行数 | [partition-nonsink.cpp](../../wolvrix/lib/transform/grhsim/partition-nonsink.cpp) | 分区/执行 oracle、multiple-nonsink-activation | 10 checkpoint 重启、真实图 manifest |
| clock/gate/priority 分组、有序 run、必要 nonsink 依赖；交错 writer 不重排 | [partition-sink.cpp](../../wolvrix/lib/transform/grhsim/partition-sink.cpp)、[sink-schedule.hpp](../../wolvrix/include/transform/grhsim/sink-schedule.hpp) | `test_grhsim_sink_schedule`；[调度测试](../../wolvrix/tests/transform/test_grhsim_sink_schedule.cpp) | 小/大 sink-run 共享锥执行、冻结状态比较 |
| 六段、current/next、large 原地提交、固定点与首 eval/重 init；超限报错 | [cpu-st-cpp.cpp](../../wolvrix/lib/emit/grhsim/cpu-st-cpp.cpp) | `test_grhsim_cpu_st_cpp`；[执行矩阵](../../wolvrix/tests/emit/test_grhsim_cpu_st_cpp.cpp) 的 models、nonconvergence、memory activation | 54 个生成执行用例、ROB 全输出、XS 100k |
| DPI 混合方向/宽值/Real/String、held sample、任务/random；CPU Logic 限两态 | 同上及 [runtime](../../wolvrix/lib/emit/grhsim_runtime.cpp) | mixed-DPI、trigger、alias、effects、random；四态图契约由基础/转换套件检查 | 8 fixture/168 条；18 条明确批准的差异，其他差异不豁免 |
| rank 1/2/3、[1]、动态/部分访问、宽叶、packed 双消费、掩码/别名/非零填充 | 同上私有访问分析 | array views/wide、contiguous images、large concat、view elision、whole-array-before-image | 生成执行矩阵、162 HDLBits、27 bugcase、ROB 零排除比较 |
| 常量/fill/readmem/random InitSpec、FST 内容、profile；拒绝未实现任务/函数 | 同上及运行时 helpers | readmem/random init、waveform contents、`test_grhsim_cpu_profile` | 执行矩阵含波形/副作用检查；profile 工具回归 |
| 所有函数统一 chunk、实际行数、跨块数组/返回控制/局部初值、七万字段构造 | [function-writer.cpp](../../wolvrix/lib/emit/grhsim/function-writer.cpp) | chunk writer/execution、128 门控 scope、large store construction；多预算执行 | 所有模型 manifest 逐函数限制；ROB/XS 1024 行上限 |
| declared/generate/module 来源、合并 union、native op/site 计数与 family 定价 | [grhsim_grh_reader.py](../../scripts/grhsim_grh_reader.py)、[execution counts](../../scripts/grhsim_execution_counts.py)、[origin](../../scripts/grhsim_supernode_origin_stats.py) | `test_grhsim_execution_counts`、reader/provenance、family/paired/module 工具测试 | 两次独立执行绑定；最终图定价，不重建不可得的旧 packed 成员 |
| typed session 生命周期：instance/top/revision/config、freeze/rename/transfer、失败清空/重建 | [partition-sink.cpp](../../wolvrix/lib/transform/grhsim/partition-sink.cpp)、[session ops](../../wolvrix/app/pybind/native/session/ops.cpp) | sink schedule 套件、`test_grhsim_flow` | 隔离候选和普通安装包的 checkpoint/API 检查 |
| 标准 Make/Python/XS/HDLBits/ROB/reemit 统一入口，旧导出/构建依赖删除 | [grhsim_flow.py](../../scripts/grhsim_flow.py)、[Makefile](../../Makefile)、[audit](../../scripts/check_remove_grhsim_ir.py) | `test_remove_grhsim_ir_tooling`、`check_remove_grhsim_ir`、`make py_install` | 全新构建、128 源文件/完整库符号审计、标准安装导出检查 |

## 报告与证据边界

- [R8 后 store/phase 修复](20261026-store-phase-fix.md)：named store 直接字段、
  有序 activity/writer/commit helper、函数预算与 ROB 全输出验证；当前 XS
  100k Host=1019.552s、wall=16:59.63、exit=0，238,535 条提交、无 mismatch，
  十个进度点及终点与前次一致。相对 R7/R8 历史记录 Host +5.64%，非交替 A/B；
  当前版未重测原始 SV→emu 完整生成计时。另与 plain SV Verilator 独立重跑
  100k：231,568 条提交 trace 含周期逐条一致、零排除、周期偏移 0；参考
  来源、二进制及 CoreMark/NEMU 摘要核对通过。
- [R5/R6 验证](20261026-r5-r6-validation.md)：迁移后的最终 emitter/入口功能、
  ROB 逐次输出和动态诊断，原始 SV→emu 2032.020s；同一二进制 CoreMark 100k
  Host=943.703s。该历史版本结果不替代删除后的重建和回归。
- [R7/R8 验证](20261026-r7-r8-validation.md)：删除后新编译器、Python 导出、
  构建图和模型依赖审计，以及本轮回归、ROB/XS 原始 SV 验证。
  完整 SV→emu 1954.081s，最终同一二进制 100k Host=965.162s、exit=0、
  238,535 条提交、无 mismatch，运行前后摘要相同。
- [单原调用决定](20261025-single-call-decision.md)：冻结原始比较保留
  `equal=false`；只有精确匹配的重复调用消除及原图顺序差异允许
  `accepted=true`，其他输入/输出/状态/参数/触发差异都须解决。
- 四态/Real/String 的图验证不自动证明 CPU ABI；当前 CPU 的 Logic 只接受
  TwoState，Real/String 与混合 DPI 由独立生成执行用例验证。
- 100k 是周期窗口，非完整 CoreMark 程序结束；单次 Host 时间不构成受控
  加速比。旧侧性能 A/B 已取消；保留新版原始 SV→emu 小于 2100 秒的门禁。
- native counter 是诊断插桩，不用于运行性能计时；writer visit 不等于成功
  写入次数，原成员无法恢复时保持 unpriced。

## S9 的直接基线

R7/R8 完成版本是 S9 的直接基线：复用统一 GRH 类型、等宽 assign、数组
操作与来源，在分区前实施计算优化，在 emitter 私有分析内实施访问优化。
不能重新引入独立 SimModel/CpuProgram、CPU planning pass、双 assign kind
或第二套 JSON。S9 保持位序、动态索引/越界、写前快照、效果和 chunk 契约，
另行验证收益。本轮不实现 S9；原 S9 草案中被替代的接口仅供历史追溯。
