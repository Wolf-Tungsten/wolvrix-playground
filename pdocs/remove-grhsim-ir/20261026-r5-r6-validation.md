# R5/R6 必要验证

状态：R5/R6 必要验证已完成。按用户 2026-10-26 的决定，先完成迁移必要验证，性能深挖留待后续；R7/R8 尚未开始。既定功能契约和完整原始 SV→emu 的 2100 秒编译预算均通过，未恢复已取消的旧侧性能 A/B。

本轮验证当前工作树，包括 bitmap 之后的 sink run 内联发射。历史 v24/bitmap 的通过记录不替代本轮结果。日志和隔离模型统一放在 `ptmp/remove-grhsim-ir/r56-validation-20261026/`；Python binding 与核心库由 `make stage_remove_grhsim_ir_candidate_python` 重新构建并保存到该目录。Python 使用 `-S`，避免 editable install 覆盖隔离库。

| 必要检查 | 本轮状态 | 证据 |
| --- | --- | --- |
| emitter 生成/编译/执行、全部函数预算、波形与副作用矩阵 | 修复分块后的 54 个生成执行用例及 11 项原生计数通过，含补回的混合 DPI 和大量门控作用域执行 | [batched-matrix-2.log](../../ptmp/remove-grhsim-ir/r56-validation-20261026/batched-matrix-2.log) |
| 公共回归 | 修复后 74/74、107.19s；重启 10 模型、provenance 3 与 tooling 15 也重新通过 | [修复后](../../ptmp/remove-grhsim-ir/r56-validation-20261026/batched-public-flow.log)、[CTest 明细](../../ptmp/remove-grhsim-ir/r56-validation-20261026/public-final-ctest.log) |
| checkpoint 重启、provenance、原生读者/计数及工具回归 | 重启 10 模型、provenance 3、reader 16、计数 11、tooling 15、resources 4、family 23、paired 31、profile 4、benchmark 6、module 2 + 13 自检通过 | [重启与最终入口回归](../../ptmp/remove-grhsim-ir/r56-validation-20261026/batched-public-flow.log)、[工具](../../ptmp/remove-grhsim-ir/r56-validation-20261026/tooling.log)、[计数](../../ptmp/remove-grhsim-ir/r56-validation-20261026/batched-matrix-2.log) |
| 168 条冻结逐次观测，批准项之外零差异 | accepted=true，equal=false；18 条批准，0 未解决，输出/状态/输入无差异 | [comparison.json](../../ptmp/remove-grhsim-ir/r56-validation-20261026/observations-batched/comparison.json) |
| ROB 原始 SV 重生，全 trace 输出零排除比较 | 原 SV 完整生成与 JSON roundtrip 184.110s，emit 22.166s；100,050 条记录、4,394,996,424 bytes 全输出相同，exclusions=0 | [生成](../../ptmp/remove-grhsim-ir/r56-validation-20261026/rob-final/generation.log)、[比较结果](../../ptmp/remove-grhsim-ir/r56-validation-20261026/rob-final/comparison.json) |
| 同一 ROB 图的两次独立执行计数、family 与模块来源归属 | 2000 trace cycles / 4000 eval，两次 757,319 位点计数相同，完整源码/图绑定通过；checksum=14806783039636027445，与历史参考一致。10 个 family 全部完成动态定价；NonSink 来源覆盖 403,510/403,510 操作 | [计数](../../ptmp/remove-grhsim-ir/r56-validation-20261026/rob-counters/execution-summary.json)、[family](../../ptmp/remove-grhsim-ir/r56-validation-20261026/rob-families/summary.json)、[模块来源](../../ptmp/remove-grhsim-ir/r56-validation-20261026/rob-origin/report.md) |
| HDLBits 黄金检查、27 个 XS bugcase | 最终编译器重跑 HDLBits 162/162、XS bugcases 27/27 通过 | [HDLBits](../../ptmp/remove-grhsim-ir/r56-validation-20261026/hdlbits-report-final/summary.txt)、[XS bugcases](../../ptmp/remove-grhsim-ir/r56-validation-20261026/bugcases-final/summary.txt) |
| 当前 XS 原始 SV→emu 连续编译预算与生成函数行数 | 2032.020s，exit=0、within_compile_budget=true，预算余量 67.980s；59,820 函数、2,355 TU、最大实际行数 1023/1024 | [资源结果](../../ptmp/remove-grhsim-ir/r56-validation-20261026/xs-final-resources/result.json)、[生成日志](../../ptmp/remove-grhsim-ir/r56-validation-20261026/xs-final/generation.log)、[manifest](../../ptmp/remove-grhsim-ir/r56-validation-20261026/xs-final/model/manifest.json) |
| 同一 XS 二进制 CoreMark 100k / NEMU difftest | Host=943.703s（15 分 43.703 秒），wall=15:43.75，exit=0；238,535 条提交，未报告 mismatch | [运行日志](../../ptmp/remove-grhsim-ir/r56-validation-20261026/logs/xs_wolf_grhsim_r56_final_100k.log)、[wall/RSS/退出状态](../../ptmp/remove-grhsim-ir/r56-validation-20261026/xs-final-100k.time) |
| 当前源码/实际对象/生成模型依赖审计 | ROB 与 XS 均通过，各覆盖 30 源文件、13 个对象/生成库检查，零退役依赖 | [ROB 审计](../../ptmp/remove-grhsim-ir/r56-validation-20261026/rob-production-audit.json)、[XS 审计](../../ptmp/remove-grhsim-ir/r56-validation-20261026/xs-production-audit.json) |

所有构建、执行和分析使用项目 Make 入口。阶段只在对应检查通过后关闭；100k 表示周期窗口，未声明完整 CoreMark 程序结束。原生动态计数中的 writer visits 与成功写入次数分别解释，未恢复的 packed 原成员保持 unpriced。

ROB 全输出 SHA256 为 `688ac2f6e9c5509eb00dad368ead600a07ec27d956b1ec9a429d8e46309a7df1`，执行耗时 308.501s；该执行与其他验证并行，不作受控性能结论。生成模型含 5,379 个函数、329 个 TU，最大实际函数行数 1021/1024。

真实 ROB 诊断保留 117 个 elided assignments，记录 938,635,853 次 operation visits，其中 compute 为 833,642,479；writer-sample 为 49,717,194，writer-commit 为 28,201,397。此窗口的 effect/history-write 计数为零。family 统计覆盖最终图中的 231 个 scalar state、3,851 bits、10 个 family，union compute visits 为 371,641；它不重建打包前的原成员。3,886 个 NonSink 超节点中的 403,510 个操作均有模块来源，1,924 个超节点为单一来源。插桩计数仅作诊断，未用于运行性能计时。

XS 使用 Clang 22.1.2、生产 `-O3 -march=native` 和 24 个编译 job。完整生成含 JSON 往返与调度重建为 1833.641s，其中 C++ 发射为 173.716s；完整 SV→emu 测量的峰值同时进程 RSS 为 84,405,172 KiB。生成身份记录实际加载的隔离库，见 [graph.generation-identity.json](../../ptmp/remove-grhsim-ir/r56-validation-20261026/xs-final/graph.generation-identity.json)。最终二进制为 189,172,376 bytes，SHA256 为 `4d607a29e84ac4733d8ca1c4b427e7caf38e449b1872027f7ebe59fddfec2fcf`。

100k 运行固定 CPU 2、seed=0，关闭波形和性能插桩，启用 NEMU difftest。终点为 instrCnt=238,535、cycleCnt=99,996、Guest cycles=100,001、PC=0x80000cde，与既定终点相同；按周期上限正常结束，不是完整 CoreMark 两次迭代结束。Host 吞吐约 105.97 host cycles/s，运行最大 RSS 为 197,328 KiB。运行前后二进制 [摘要核对](../../ptmp/remove-grhsim-ir/r56-validation-20261026/xs-final-binary-verification.log)通过；[Make 驱动日志](../../ptmp/remove-grhsim-ir/r56-validation-20261026/xs-final-100k-driver.log)保存了完整运行参数。这是当前版本的一次实测，不据历史不同负载的数据宣称受控加速比。

R5/R6 的生成执行、兼容策略、入口重启、黄金检查、真实 ROB 行为与诊断、XS 完整编译预算和 100k difftest 均已通过。旧导出/独立 IR 实现的删除属于 R7，正式规范及全项目证据索引收口属于 R8；本报告不将这些后续阶段标记完成。

## 本轮发现与修正

- `testDpiMixedTypes` 已有测试正文但未在入口调用；补回后验证宽 output/inout、real/string、混合调用顺序和 held sample。
- 计数测试此前把不同函数预算下的函数名要求为相同。现在逐模型检查源码绑定，再跨预算比较完整图、所有 operation/category visits 和 elided 集合；不要求内联/分块布局相同。
- 首轮 ROB 原始 SV 已完成图转换，但 C++ 发射超过 6 分钟仍未完成。分块器每次只处理一个超预算片段并重新分析全函数，内联布局放大了重复工作。本轮改为每轮批量处理超预算片段和作用域，新增 128 个门控作用域的实际执行，覆盖 64/1024 行预算、各自初值和提前返回。
- 修复后 ROB 同图检查点加载、调度重建与发射共 26.61s，退出 0，见 [定位计时](../../ptmp/remove-grhsim-ir/r56-validation-20261026/rob-batched-screen2.time)。它只证明生成阻塞已解除，完整原始 SV 验收另跑 `rob-final` / `xs-final`。
- 最终编译器固定于 `python-batched`，核心库 SHA256 为 `9d754c7d151a2494904eb83776d84099a740c54a509c8ce638da2597d639231e`。首轮 ROB/XS 流程中断日志保留，不能作为已完成测量。首次工具回归因 `-S` 缺少 NumPy 搜索路径失败，已显式加入现有 site-packages，仍不执行 editable install 的 `.pth`。

## 复跑入口

本轮所有入口先加载 `ptmp/remove-grhsim-ir/r56-validation-20261026/validation.env`，以固定 Python binding 和核心库。下表列出主要 Make 目标；完整展开命令保存在对应驱动日志中。重新生成或资源测量须选择新的 `ptmp/remove-grhsim-ir/` 子目录，避免覆盖本轮证据。

| 范围 | Make 入口与关键参数 |
| --- | --- |
| 公共与生成模型 | `make test_wolvrix`；`make test_grhsim_cpu_st_cpp test_grhsim_execution_counts` |
| 重启与入口工具 | `make test_grhsim_flow test_grhsim_provenance test_remove_grhsim_ir_tooling` |
| 冻结观测 | `make compare_remove_grhsim_ir REMOVE_GRHSIM_IR_EFFECT_POLICY=single-original-call-source-order`，新输出目录通过 `REMOVE_GRHSIM_IR_COMPARISON` 指定 |
| HDLBits / XS bugcases | `make run_all_hdlbits_grhsim_tests`；`make run_xs_bugcase_grhsim` |
| ROB 原 SV 全输出 | `make compare_remove_grhsim_ir_rob REMOVE_GRHSIM_IR_ROB=<新目录>` |
| ROB 计数与来源 | `make reemit_grhsim GRHSIM_REEMIT_EXECUTION_COUNTERS=1`；`make inspect_remove_grhsim_ir_rob_execution REMOVE_GRHSIM_IR_ROB_EXECUTION_COUNTERS=1`；`make inspect_remove_grhsim_ir_families`；`make analyze_grhsim_supernode_origins`，输入绑定最终 ROB 图和两次运行日志 |
| XS 完整构建 | `make measure_remove_grhsim_ir_resources REMOVE_GRHSIM_IR_RESOURCE_TARGET=build_remove_grhsim_ir_xs_from_sv REMOVE_GRHSIM_IR_XS_FRESH=<新目录> REMOVE_GRHSIM_IR_RESOURCE_OUTPUT=<新计时目录> VM_BUILD_JOBS=24` |
| XS 100k | `make run_xs_grhsim_emu XS_GRHSIM_BUILD=<同一XS目录> XS_SIM_MAX_CYCLE=100000 XS_PROGRESS_EVERY_CYCLES=10000`，另用 `/usr/bin/time -v` 包裹该 Make 命令保存 wall/RSS |
| 生成模型依赖 | `make check_remove_grhsim_ir REMOVE_GRHSIM_IR_AUDIT_MODEL=<模型目录> REMOVE_GRHSIM_IR_AUDIT_REPORT=<报告路径>` |
