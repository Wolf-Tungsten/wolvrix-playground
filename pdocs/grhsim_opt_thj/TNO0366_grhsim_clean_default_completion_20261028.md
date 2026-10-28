# TNO0366：干净默认流程的端到端完成与公开入口复测

日期：2026-10-28。承接 [TNO0365](./TNO0365_grhsim_clean_initial_runtime_20261028.md)。

## 自动迁移与最终保留

本轮从 Verilog 开始的默认流程已全部完成。8 份新求解均满足六维容量条件，自动选择 seed 6，完整图 km1=39,450,970。完整配置发射、原始 O3/native 编译、最终功能检查和普通 walltime 测量完成后，工具从本轮 profile 自动提出 51 个迁移候选，7 个满足通信预算，6 个位于 Pareto frontier，其中 3 个预计改善关键路径。

工具选择 `piece_592581_p6_to_31`，迁移 7 个完整 ASC；来源、目的地和集合没有手动指定。候选重新生成全部 32 分区并编译，随后完成 8 对 fresh AB/BA：

| 指标 | 自动初解 | 自动迁移候选 |
|---|---:|---:|
| walltime 中位数 | 13.141647 s | 13.468487 s |
| Host 中位数 | 13.044000 s | 13.348500 s |

逐对 walltime 变化的中位数为 **+2.277079%**，候选 0/8 获胜。脚本自动拒绝候选，不进行第二轮，最终保留已通过测试的初解。16 次正式交错运行均通过最终功能检查，代码页全部被大页覆盖。

最终 `build/xs/grhsim32/result.json` 为 `status=pass, retained=initial, selected_seed=6, migration.accepted=false`。公开产物为 `emu` launcher、`emu.bin` 和 `package` 链接。

## 公开入口复测

直接调用 `make run_xs_repcut_grhsim`（本次测试显式使用 node030 CPU96–127；源码默认不固定机器或核号），完成 C100 smoke 和另 8 次 C=100000 运行：walltime 中位数 **13.102951 s**，Host **13.016000 s**，全部通过功能检查。结果位于 `build/xs/grhsim32/rerun-20261028-131322/summary.json`。

另直接执行生成的 `build/xs/grhsim32/emu -C 100`，launcher 正常设置运行环境并完成 smoke。运行入口由工具生成，无需用户填写线程、NUMA、preload 或优化开关。

上述数据验证新流程能够从本轮 Verilog 生成并运行，不构成超过历史恢复版的性能结论；没有额外加入历史二进制比较阶段。

## 新 clone 的使用边界

默认命令为 `git submodule update --init --recursive` 后 `make xs_grhsim`。系统依赖、首次网络下载、XiangShan RTL 尚未生成时的 JDK/mill 前提，以及输出/重跑方法见 [使用文档](../../docs/grhsim32.md)。配置仍沿用用户指定的三处 memory 控制口径；迁移端点自动选择。

已在不含旧构建及设计产物的独立源码目录构建全部原生工具，并实际运行小型 Verilog 前端/六维图。实际求解回归覆盖零权重维度；启动回归覆盖 taskset exec 与 dlmopen 的一次性大页处理。默认流程 13 项、critical profile 8 项、rank 5 项、piece candidates 6 项、auto flow 5 项、backend 7 项，共 **44 项测试通过**，Python 编译与 `git diff --check` 通过。

本轮已完成工作树实现和本机实测，尚未提交或推送主仓库及子模块修改，因此不声称远端现有 HEAD 已包含这条新流程。

## 勘误 2026-10-28：上游 RTL 缓存未对齐

后续 [TNO0367](./TNO0367_grhsim_initial_km1_input_drift_20261028.md) 确认，本轮默认入口复用了旧 `build/xs/rtl/rtl`，没有继承当前 Scala 已有的 counter-print 改动。以上功能和计时仍是该输入的实际结果，但不能视为完整历史优化路线的同输入固化。默认入口已修正为未显式指定 RTL 时重新生成；修正后尚无新的全量 km1 或 walltime。
