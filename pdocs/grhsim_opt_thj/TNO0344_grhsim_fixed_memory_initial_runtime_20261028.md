# TNO0344：固定历史 memory 后的初解性能对照

日期：2026-10-28；策略和控制变量见 [TNO0343](./TNO0343_grhsim_restored_memory_control_20261028.md)。

本轮固定恢复版的三个 memory，row_limit=2、strict_init=false。复用同一份经全部 RTL/header SHA 校验的 pre-mem-to-reg 图，重新求解32分区。没有使用历史分区标签；新的 assignment SHA256 为 `3d578661f88df4ffd9db3ff92abf02a180bd66e9b75f2068c12404b5f9783560`。mem-to-reg 输出 SHA256 为 `493a8fe12f1639bebaa8069e7d7495c3023297f108b8917778432705a6fcb24b`。

7504个对象完整编译通过，Clang23/O3/native/no-SLP，耗时195.13s；6905个compute入口全部64B对齐。32分区/10表执行计划核验通过，耗时741.07s，源结构账本完整。

node03096–127、N=K=32、C100000、preferred NUMA1、all-spin、ASLR off、THP，8对fresh AB/BA。两个版本的库、完整26项preset、编译器与兼容选项相同；本对照量化memory策略改变和它引起的全局重新划分的合计影响，不能将结果理解为只换某个memory的局部代码耗时。

| 指标 | 上轮自动memory初解 | 固定历史memory初解 | 配对变化中位数 | 候选更快 |
|---|---:|---:|---:|---:|
| walltime(s) | 13.7900 | 13.1900 | -4.455% | 7/8 |
| Host(s) | 13.7025 | 13.1120 | -4.498% | 7/8 |
| global eval(µs) | 55.3360 | 52.3905 | -5.411% | 7/8 |
| global update(µs) | 9.0120 | 9.3235 | +3.575% | 0/8 |

全部16次C100000与2次C100 smoke通过功能、代码THP及输入身份检查，原始成功样本完整保留。固定历史memory改善约4.46%walltime，eval改善而update退化。尚不能用该结果判定已追平恢复版；后续仍需与相同编译兼容设置的恢复版直接对比。

[summary](../../build/grhsim_fixed_restored_memory_20261028/reference_vs_initial/summary.json)、[THP核验](../../build/grhsim_fixed_restored_memory_20261028/reference_vs_initial/thp_verification.json)、[构建](../../build/grhsim_fixed_restored_memory_20261028/initial/build.json)。后续在本轮固定memory初解上采集新trace，按预先相同的自动规则选择迁移来源和目的分区。
