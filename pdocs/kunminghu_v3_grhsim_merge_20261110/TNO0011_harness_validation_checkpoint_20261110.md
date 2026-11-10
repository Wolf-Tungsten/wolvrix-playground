# TNO0011 GrhSIM harness 验证 checkpoint

## 检查结果

完整 `test_grhsim*.py` 测试组 83 项通过，覆盖 native 日志、DiffTest build modes、NUMA locality、trace 有效载荷与周期覆盖、默认/performance 流程分离、配对 runner，以及 native source-map/RTL-rewrite 集成检查。集成测试包含实际 Verilator 的两组 100,000 周期轨迹。

最初宽范围运行因未构建 `grhsim32_rtl_rewrite` / `grhsim32_source_map_fixture` 而在 setUpClass 报错。随后显式构建这两个 focused target，并重新完成整组测试；失败日志保留，未通过跳过测试来获得通过结果。

- [完整 83 项测试日志](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/logs/grhsim-python-tests-final.log)
- [focused native tools 构建日志](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/logs/extra-focused-tools.log)
- 主仓改动的 Python 编译检查、各仓 `git diff --check` 通过。
- canonical Make 检查和干净子模块状态见 [TNO0010](./TNO0010_merge_checkout_completion_20261110.md)。

## 32 线程 placement 门补强

配对 runner 除检查 runtime-config 外，直接核对 `/proc/<pid>/task/*/status` 的 CPU affinity。稳定运行阶段必须观测到 32 个线程，每个线程只允许一个 CPU，且恰好覆盖配置的 32 CPU 集。检查不依赖 `Difftest enabled` 日志是否已刷新；允许线程建立/退出时的短暂快照。

新增测试拒绝“32 个线程各自允许全部 CPU”“所有线程绑定同一 CPU”和“绑定到另一组 CPU”等情形。已有真实 10k RepCut smoke 的 `/proc` 样本也通过新增门。正式样本使用同一检查。

## 已完成的整图证据

- before/after native：两组 seed 的 100k 完整 DiffTest/trace 和 placement 门均通过，见 [TNO0008](./TNO0008_native_trace_and_structure_gate_20261110.md)。
- before RepCut：initial、两轮迁移 AB/BA、最终 candidate 共 48 次 100k 运行全部通过完整 DiffTest，PC/指令数/周期数/UART 签名完全一致，且与 before native 一致。100-cycle 初始化 smoke 不计入这 48 次。
- before 保留 seed 3 的 initial assignment 经迁移后的 candidate；两轮内部选择各 6/8 对获胜。此内部候选比较不等同于上游合并前后对比。

[before-repcut-functional.json](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/before-repcut-functional.json) 保存 48 个日志身份和功能签名。native 的参数核对见 [controlled-parameters.json](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/controlled-parameters.json)：C++ 编译器、模型选项、完整 DiffTest 和输入字节一致；native 构建并发 64/32 仅用于资源隔离，运行均为 CPU96 单线程。

本 checkpoint 形成时 after RepCut 尚在生成分区图，正式配对未开始。不得用此记录替代之后的 8 对前后 walltime 结果。
