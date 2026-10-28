# TNO0346：固定恢复版 memory 的自动分配/迁移最终验收

日期：2026-10-28。入口与固定变量见 [TNO0343](./TNO0343_grhsim_restored_memory_control_20261028.md)，memory对照见 [TNO0344](./TNO0344_grhsim_fixed_memory_initial_runtime_20261028.md)，编译对照见 [TNO0345](./TNO0345_grhsim_restored_no_slp_control_20261028.md)。

## 自动迁移的真实结果

在固定历史memory的新初解上采集4次完整C100000 trace，共800008个非reset step。按exclusive eval margin自动选出p2、p9、p13作为来源，每源8个piece，每piece自动提3个共享目的地，共72个提案。没有提供来源/目标分区编号。

全部72个提案和baseline完成精确assignment记账；20个满足send/receive calls/bytes总量及峰值不增长预算，Pareto frontier有17个，但improving frontier为0。因此自动工具没有选择迁移，保留新初解，不手工挑一个被模型判为无改善的提案，也没有以旧版的p4→p7代替。

[新profile](../../build/grhsim_fixed_restored_memory_20261028/trace_initial/profile.json)、[提案](../../build/grhsim_fixed_restored_memory_20261028/automatic_migration/proposals/selection.json)、[评估](../../build/grhsim_fixed_restored_memory_20261028/automatic_migration/evaluation/report.json)、[排序](../../build/grhsim_fixed_restored_memory_20261028/automatic_migration/ranking.json)、[不迁移决策](../../build/grhsim_fixed_restored_memory_20261028/automatic_migration/result.json)。

这是有限提案空间和当前筛选模型下的结论，不证明所有合法迁移都无收益。

## 相同编译选项下与恢复版直接比较

两边均为历史三个memory、Clang23/O3/native/no-SLP、相同26项preset，compute入口全部64B对齐，保留各自生成Makefile的archive顺序。恢复版保留其累计优化assignment，新版本为从头求解assignment。原始图的存储序列化、后端生成版本和划分诱发的代码形态仍有差异，因此剩余差距是这条新路线相对恢复版的合计差距，不能仅归给某一个solver权重。

node03096–127、32线程、C100000、preferred NUMA1、all-spin、ASLR off、代码THP，8对fresh AB/BA：

| 指标 | no-SLP恢复版 | 固定memory新初解 | 配对变化中位数 | 新初解更快 |
|---|---:|---:|---:|---:|
| walltime(s) | 11.1900 | 13.0400 | +16.325% | 0/8 |
| Host(s) | 11.1115 | 12.9655 | +16.377% | 0/8 |
| global eval(µs) | 43.7480 | 51.6110 | +17.563% | 0/8 |
| global update(µs) | 7.8545 | 9.4095 | +19.892% | 0/8 |
| max part eval(µs) | 27.8775 | 34.3250 | +23.010% | 0/8 |
| sum part eval(µs) | 635.3535 | 582.6865 | -8.529% | 8/8 |

新初解walltime慢16.325%，0/8更快。sum-part eval下降8.529%，但max-part eval增加23.010%、global eval增加17.563%，update增加19.892%。这支持“总计算开销降低，但工作分布/拖尾及通信阶段未优化好”的方向；尚无逐批次计时证据把差距归给单个机制。

## 本轮收束

1. memory控制生效：同配置下，自动memory初解→历史memory初解walltime为13.790→13.190s，配对−4.455%、7/8更快。
2. 编译兼容影响：原恢复版→同源码no-SLP重编为10.420→11.340s，配对+8.987%、0/8更快。
3. 消除上述两项配置差异后：no-SLP恢复版→固定memory新初解为11.190→13.040s，配对+16.325%、0/8更快。

三行是独立8对窗口，绝对时间和百分比不能跨行直接相减。较早自动路线的+34.1%不能据此做简单加法拆分。

本轮完成48次普通C100000正式运行、6次普通C100 smoke，另有4次C100000 trace与2次trace smoke，全部通过功能、THP、对齐和输入身份核验。生成/分析/编译用全CPU0–383，普通性能测试固定96–127。20项相关Python测试、Python编译、两个仓库层级diff空白检查通过。

完整受控结果：[controlled_result.json](../../build/grhsim_fixed_restored_memory_20261028/controlled_result.json)。保留的新自动初解位于 `build/grhsim_fixed_restored_memory_20261028/initial/harness/grhsim-compile/emu`，这只表示本次自动流程保留，不表示替换历史最佳恢复版。

复现入口：[run.sh](../../build/grhsim_fixed_restored_memory_20261028/run.sh)，后续两组归因对照：[post_compare.py](../../build/grhsim_fixed_restored_memory_20261028/post_compare.py)。恢复版源码和原binary保持原样，历史最佳线仍为恢复版。

后续若继续优化，应在相同memory和编译设置下改进初始分配/动态拖尾目标，或研究更窄的通用编译器规避方法；本轮不继续扩大阈值或人为迁移范围。
