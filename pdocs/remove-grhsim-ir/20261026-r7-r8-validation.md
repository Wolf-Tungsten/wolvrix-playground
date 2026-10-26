# R7/R8 删除与收口验证

状态：**R7/R8 已完成必要验证与收口，工作树未提交。** 独立 GrhSIM IR 的实现、构建与导出已删除，统一 GRH 路线的干净重建、回归、ROB 与 XS 验证通过，正式规范及能力证据索引已完成。R5/R6 的通过记录未被用来替代本轮删除后的检查；本版本作为 S9 直接基线，S9 尚未实施。

本轮日志与模型保存于 `ptmp/remove-grhsim-ir/r78-validation-20261026/`。删除前源码及未提交差异已保存在该目录的 `pre-r7-sources.tar.gz`、`root-before.patch` 和 `wolvrix-before.patch`；R0 与 R5/R6 冻结证据不改写。

| 要求 | 当前状态与证据 |
| --- | --- |
| 删除独立 IR/旧转换器/dialect/pass registry/backend/mapping/JSON | 已删除 `include/grhsim`、`lib/grhsim` 及旧 Python action；统一 transform/emitter 和 `emit/grhsim_runtime` 保留 |
| 删除 Python model API 和 session 存储 | 包装、native 方法表、声明、keys/kind/clone/transfer/erase 中的旧 model 类别已移除；隔离候选与普通安装包的旧导出缺席检查均通过 |
| 清理旧构建与保留有效测试覆盖 | CMake 移除 10 个旧套件，数组测试迁至 `tests/grh/test_array_create.cpp`；旧 Make 测试目标转发至统一 GRH 套件 |
| 完整干净重建 | 全新 `clean-build` 目录编译，修复后公共 **64/64**；数组专项 2/2，见 [public-matrix-flow.log](../../ptmp/remove-grhsim-ir/r78-validation-20261026/public-matrix-flow.log) |
| 全部生产源码/实际构建图/共享库与 Python 导出审计 | **通过**；128 源文件、14 个对象/完整库检查，零旧依赖，见 [production-audit.json](../../ptmp/remove-grhsim-ir/r78-validation-20261026/production-audit.json) |
| 生成执行、checkpoint、冻结观测、工具回归 | **54 个生成执行用例**、11 项计数、10 模型 checkpoint 通过；冻结 8 fixture/168 记录 accepted=true、equal=false、18 批准、0 未解决，见 [比较](../../ptmp/remove-grhsim-ir/r78-validation-20261026/observations/comparison.json)；provenance 3/tooling 15/reader 16/resources 4/family 23/paired 31/profile 4/benchmark 6/module 2+13 通过，见 [工具日志](../../ptmp/remove-grhsim-ir/r78-validation-20261026/tooling.log) |
| 标准 Python 安装和入口 | `make py_install` 完成；普通 `.venv` 安装包通过旧 API 检查和 10 个 checkpoint 执行，见 [installed-flow.log](../../ptmp/remove-grhsim-ir/r78-validation-20261026/installed-flow.log) |
| 默认构建目录 | 默认 `wolvrix/build` 重新配置/构建、公共 **64/64** 及完整符号审计通过，见 [default-public-audit.log](../../ptmp/remove-grhsim-ir/r78-validation-20261026/default-public-audit.log) |
| HDLBits 与 XS bugcases | **162/162、27/27**，见 [HDLBits 汇总](../../ptmp/remove-grhsim-ir/r78-validation-20261026/hdlbits-report/summary.txt)、[bugcase 汇总](../../ptmp/remove-grhsim-ir/r78-validation-20261026/bugcases/summary.txt) |
| ROB 原始 SV 重生与全输出比较 | **通过**；4,394,996,424 bytes、零排除、SHA256 与冻结参考相同，见 [comparison.json](../../ptmp/remove-grhsim-ir/r78-validation-20261026/rob/comparison.json) |
| ROB 动态计数、来源与生成模型依赖 | 两次 4000 eval/757,319 位点计数一致，覆盖检查通过，见 [execution-summary.json](../../ptmp/remove-grhsim-ir/r78-validation-20261026/rob-counters/execution-summary.json)；来源 403,510/403,510 覆盖，128 源/15 对象及库的依赖审计通过，见 [审计与来源](../../ptmp/remove-grhsim-ir/r78-validation-20261026/rob-audit-origin.log)；10 个 family 全部定价，见 [family 报告](../../ptmp/remove-grhsim-ir/r78-validation-20261026/rob-families/summary.json) |
| XS 原始 SV 完整编译 | **1954.081s**，exit=0、within_compile_budget=true；2100 秒预算余量 145.919s，见 [资源结果](../../ptmp/remove-grhsim-ir/r78-validation-20261026/xs-resources/result.json) |
| XS 生成模型依赖审计 | **通过**；128 源文件、15 个对象/完整库/生成库检查，零旧依赖，见 [xs-production-audit.json](../../ptmp/remove-grhsim-ir/r78-validation-20261026/xs-production-audit.json) |
| XS 同一二进制 100k difftest | **Host=965.162s**、wall=16:05.20、exit=0；238,535 条提交，无 mismatch，见 [运行日志](../../ptmp/remove-grhsim-ir/r78-validation-20261026/logs/xs_wolf_grhsim_r78_100k.log)、[wall/RSS](../../ptmp/remove-grhsim-ir/r78-validation-20261026/xs-100k.time) |
| 正式类型/op/JSON、pass、六段与 chunk、Make 流程 | 已更新 [正式流程](../../wolvrix/docs/grhsim.md)及各专题；32 份旧独立 IR 文档移入 `docs/history/grhsim-ir/`，旧直接 emitter 笔记标注历史 |
| 能力→实现→测试→报告、支持/拒绝边界、S9 基线 | [能力索引](capability-evidence.md)与正式规范已收口；本次完整验证版本为 S9 直接基线 |

迁移数组反例发现 `kArrayCreate` verifier 只比较 kind/width/sign/shape，遗漏 LogicDomain。已要求全部元素及结果的 domain 一致，补齐异域结果和非法属性的负例；合法的两态/四态、嵌套 shape、X/Z 折叠、JSON/SV 往返和 packed 消费覆盖保留。

首次干净配置在沙箱内拉取 fmt 时 DNS 失败，保留 `clean-public.log`；权限重试后完整依赖/项目构建完成，见 `clean-public-retry.log`。不将失败回填为成功，也不以旧对象文件作为本轮干净构建证据。

公共套件从 74 变为 64，是移除 10 个只针对独立 IR/CPU mapping 的套件；有效数组覆盖迁入 GRH，生成 C++ 仍单独编译执行。兼容 Make 测试名转发到当前转换、分区、调度和 emitter 套件。

本轮隔离核心库 SHA256 为 `0716f1768581e247308b31e2a9d23879cdca957fb9cb92e184c78b0a749012ea`，binding 为 `96e43826e0ac8d9689ad875949c0c9948674e8e755813e4acb3c959497ab1da8`，与本轮干净构建一致。普通安装包在 `.venv/lib/python3.12/site-packages/wolvrix/`，核心库摘要为 `94648c3bf390635a336a734c8a3a686a2e2818a1e0a80d4ef9a7fbe3fadd4e16`，来自单独的 scikit-build 安装构建；它的运行时身份保存于 [installed-flow generation identity](../../ptmp/remove-grhsim-ir/r78-validation-20261026/installed-flow/sink-partitioned-b1024/model/generation-identity.json)。

ROB 从原始 SV 完整生成和 JSON roundtrip 共 172.489s，emit 21.317s；5,379 函数、329 TU，最大实际函数行数 1021/1024。100,050 条 trace 的全输出 SHA256 为 `688ac2f6e9c5509eb00dad368ead600a07ec27d956b1ec9a429d8e46309a7df1`；比较执行 312.298s，与其他验证并行，仅作行为证据，不是受控性能结论。

本轮 ROB 计数使用同一最终图重发的插桩候选，两次 2000 trace cycles 的 checksum 均为 `14806783039636027445`。记录 operation visits=938,635,853，其中 compute=833,642,479；writer-sample=49,717,194，writer-commit=28,201,397，effect/history-write=0，117 个 view assign 被 elide。首次计数命令漏了模型库构建前置步骤，保留 `rob-counters.log`；随后通过 `make build_remove_grhsim_ir_rob inspect_remove_grhsim_ir_rob_execution` 完整编译/执行通过，见 [build-run 日志](../../ptmp/remove-grhsim-ir/r78-validation-20261026/rob-counters-build-run.log)。

XS 使用冻结的 aggregate-all 原始 SV、Clang 22.1.2、`-O3 -march=native` 和 24 job。完整生成（含 JSON roundtrip 和 SinkSchedule 重建）1759.533s，C++ emit 182.002s；59,820 个函数、2,355 TU，最大实际函数行数 1023/1024，见 [生成日志](../../ptmp/remove-grhsim-ir/r78-validation-20261026/xs/generation.log)与 [manifest](../../ptmp/remove-grhsim-ir/r78-validation-20261026/xs/model/manifest.json)。完整 SV→emu 连续计时 1954.081s，峰值同时进程 RSS 84,097,852 KiB。最终二进制大小 189,172,376 bytes、SHA256 为 `c80cd450c08bc8e76ff626a83682faf4a2455f3776c805472a90be6cee9faabc`，由本轮隔离新编译器生成，[generation identity](../../ptmp/remove-grhsim-ir/r78-validation-20261026/xs/graph.generation-identity.json)保存实际加载库身份。此为单次本版本测量，不建立新旧性能比值。

同一 XS 二进制固定 CPU 2、seed=0，关闭波形/性能插桩并启用 NEMU difftest，100k 周期窗口通过。Host=965.162s，wall=16:05.20，最大运行 RSS=197,036 KiB；instrCnt=238,535、cycleCnt=99,996、Guest cycles=100,001、最终 PC=0x80000cde，与既定终点一致。按周期上限正常退出，不代表完整 CoreMark 程序结束。运行前后 [二进制摘要核对](../../ptmp/remove-grhsim-ir/r78-validation-20261026/xs-binary-verification.log)通过；[驱动日志](../../ptmp/remove-grhsim-ir/r78-validation-20261026/xs-100k-driver.log)保存完整命令。

## 复跑入口

先加载本轮 `validation.env` 固定隔离 Python 和核心库。复跑时另选新的 `ptmp/`
子目录；不要覆盖 R0、R5/R6 或本轮证据。所有构建、执行和分析通过 Make。

| 范围 | Make 入口及关键参数 |
| --- | --- |
| 公共/生成/计数 | `make test_wolvrix test_grhsim_cpu_st_cpp test_grhsim_execution_counts` |
| 入口/重启/工具 | `make test_grhsim_flow test_grhsim_provenance test_remove_grhsim_ir_tooling`；`GRHSIM_FLOW_TEST_WORK=<新目录>` |
| 冻结观测 | `make compare_remove_grhsim_ir REMOVE_GRHSIM_IR_COMPARISON=<新目录>`；策略 `single-original-call-source-order` |
| 标准安装 | `make py_install` 后用普通 `.venv/bin/python` 运行 `make test_grhsim_flow`，不设置隔离 PYTHONPATH/LD_LIBRARY_PATH |
| 黄金检查 | `make run_all_hdlbits_grhsim_tests_report run_xs_bugcase_grhsim`，分别设置 HDLBits build/report 和 bugcase work 目录 |
| ROB 原 SV | `make compare_remove_grhsim_ir_rob REMOVE_GRHSIM_IR_ROB=<新目录>` |
| ROB 计数 | `make prepare_remove_grhsim_ir_rob reemit_grhsim`，使用最终 roundtrip、`GRHSIM_REEMIT_EXECUTION_COUNTERS=1`；再 `make build_remove_grhsim_ir_rob inspect_remove_grhsim_ir_rob_execution REMOVE_GRHSIM_IR_ROB_EXECUTION_COUNTERS=1` |
| ROB family/模块来源 | `make inspect_remove_grhsim_ir_families analyze_grhsim_supernode_origins`，输入绑定最终图、manifest 和两次计数日志 |
| XS 原 SV→emu | `make measure_remove_grhsim_ir_resources REMOVE_GRHSIM_IR_RESOURCE_TARGET=build_remove_grhsim_ir_xs_from_sv VM_BUILD_JOBS=24`，另设 fresh/output 目录 |
| XS 100k | `make run_xs_grhsim_emu XS_GRHSIM_BUILD=<同一目录> XS_SIM_MAX_CYCLE=100000`，固定 CPU 2、seed=0、NEMU difftest |
| 生产/模型审计 | `make check_remove_grhsim_ir REMOVE_GRHSIM_IR_AUDIT_MODEL=<模型目录> REMOVE_GRHSIM_IR_AUDIT_REPORT=<新报告>` |
