# TNO0356：八份择优初解后续流程及恢复版最终对照

日期：2026-10-28。完成 [TNO0352 流程](./TNO0352_grhsim_portfolio_selected_followup_runbook_20261028.md)。分阶段记录见 [构建检查](./TNO0353_grhsim_portfolio_selected_build_gate_20261028.md)、[同编译初解对照](./TNO0354_grhsim_portfolio_initial_runtime_20261028.md)、[自动迁移筛选](./TNO0355_grhsim_portfolio_automatic_migration_gate_20261028.md)。

## 最终结果

本轮完成 seed 1 初解的 assignment replay、完整 preset 发射、32 分区 execution-plan gate、全包编译/对齐/链接、普通运行对照、动态 trace 和自动迁移筛选。51 个自动提案均未通过既有通信预算，没有实施迁移；因此最终测试对象仍为 seed 1 初解。

| fresh AB/BA 对照 | baseline walltime 中位数 | seed 1 walltime 中位数 | 配对变化 | seed 1 胜出 |
|---|---:|---:|---:|---:|
| 同编译恢复版，双方 no-SLP | 9.785 s | 10.350 s | +5.518% | 0/8 |
| 历史原始恢复版二进制 | 8.920 s | 10.360 s | +16.002% | 0/8 |

每行均独立完成 8 对 AB/BA，百分比取逐对比值的中位数。两行属于不同测量窗口，不能用两行差值精确分解编译开销。

历史原始恢复版对照中，Host 为 8.850→10.289 s（配对 +16.043%），global eval 为 34.764→41.6515 µs（+19.407%），update 为 6.142→6.355 µs（+3.426%）。这一行是最终产物的直接比较，同时包含编译兼容设置差异，不能全部归因于划分。

同编译行控制了 `-fno-slp-vectorize`。其中各分区 eval 之和下降约 2.50%，最长分区平均 eval 却上升约 18.76%，全局 eval 上升约 7.46%。这说明 km1 择优和总工作减少尚未解决实际拖尾；不能将更低 km1 直接当成 walltime 收益。

**本轮没有超过恢复版，历史恢复版继续作为全局性能锚点。** 驱动中的 `retained=initial` 仅表示“这次自动流程未接受迁移后的最终对象”，不是晋级为全局最佳。

## 运行与身份复核

所有普通测量固定 node030 CPU96–127，N=K=32，C=100000，all-spin、push、preferred NUMA1、ASLR off、完整代码 THP 与 64B compute 对齐。生成/分析/编译可用全部 CPU0–383；后台生成与编译在普通计时开始前均已完成。

- 两组普通对照共 32 次 C100000，全部功能和 THP 通过；另有 4 次 C100000 诊断 trace、6 次 C100 smoke，同样全部通过。
- 新分配 replay 与 portfolio 自动选中标签逐字节一致；完整 26 项 options 与参考记录相同，计划和发射输入 hash 一致。
- 7,116 个 compute 入口全部 64B 对齐，归档使用本包 Makefile 的生成顺序。
- 两份恢复版参考二进制的 SHA256 与启动前记录一致，新 emu 与 build 记录一致。
- 初解/portfolio/auto-flow/plan-gate 的 26 项相关测试已通过；本轮未改变这些工具实现。

## 范围

本轮遵照控制变量要求，继续使用历史固定 memory 的 mem-to-reg 输入及已选择的六维初解；没有重新选择 memory，也没有重新从 RTL 提取六维权重。后续迁移来源 p8/p9/p0 和 51 个目的地提案均由工具自动选择，没有人工指定端点。未改变默认生产路径或旧最佳产物。

当前结论只覆盖该初解和这批受零通信增长预算约束的自动提案，不代表扩大搜索或采用显式通信成本模型后也不存在有益迁移。也未用不同窗口的旧单次求解 walltime 推断“八份择优”的具体加速百分比。

## 产物

- [总结果](../../build/grhsim_portfolio8_followup_20261028/result.json)、[最终复核](../../build/grhsim_portfolio8_followup_20261028/verification.json)、[可复现驱动](../../build/grhsim_portfolio8_followup_20261028/run.py)。
- [同编译对照](../../build/grhsim_portfolio8_followup_20261028/reference_vs_initial/summary.json)、[历史原始二进制对照](../../build/grhsim_portfolio8_followup_20261028/original_reference_vs_retained/summary.json)。
- [自动迁移取舍](../../build/grhsim_portfolio8_followup_20261028/automatic_migration/result.json)、[最终 emu](../../build/grhsim_portfolio8_followup_20261028/initial/harness/grhsim-compile/emu)。
