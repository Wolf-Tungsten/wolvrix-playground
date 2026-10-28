# TNO0340：自动 memory 与从头 32 分区初解的正式验收

日期：2026-10-27。生成策略及来源见 [TNO0338](./TNO0338_grhsim_automatic_rtl_flow_20261027.md)，编译兼容修正见 [TNO0339](./TNO0339_grhsim_clang23_change_reduction_20261027.md)。

## 构建与功能

对本轮自动初解的全部 7538 个对象统一使用 Clang23/O3/native/no-SLP，保持 Makefile 归档顺序，构建耗时 199.21 s。全部 6937 个 compute 入口通过 64B 对齐。NEMU C100000 最终 PC、提交数和周期签名匹配，正式 16 次加 2 次 C100 smoke 全部通过功能和 THP 核验。

没有把强制某个计算组活跃、只更换某个对象的诊断方案带入正式版本。可执行文件为 `build/grhsim_auto_flow_20261027_allcores/initial/harness/grhsim-compile/emu`，SHA256 `ea5aad2a0552d73ad1bad7e9a4328304201ffda5a47020e98ebe190c19890ed8`。

## Fresh AB/BA

node030 CPU96–127、N=K=32、C100000、preferred NUMA1、all-spin、ASLR off、代码 THP，8 对交错运行，保留全部功能通过的样本。

| 指标 | 恢复版 | 自动初解 | 逐对变化中位数 |
|---|---:|---:|---:|
| 进程 walltime (s) | 11.0150 | 14.7250 | +34.107% |
| Host (s) | 10.9305 | 14.6375 | +34.360% |
| global eval (µs) | 42.9855 | 59.2480 | +38.206% |
| global update (µs) | 7.5770 | 9.3750 | +24.020% |
| max part eval (µs) | 27.5800 | 38.8110 | +41.429% |
| sum part eval (µs) | 623.7805 | 642.9975 | +2.954% |

自动初解 walltime 0/8 更快，尚未超越恢复版。恢复版是原保留二进制，自动线额外启用了编译器兼容保护，故不能将全部差异归因为初始划分；这个对照回答的是本轮完整自动路线的实际性能。

[原始 summary](../../build/grhsim_auto_flow_20261027_allcores/reference_vs_initial/summary.json)、[THP 核验](../../build/grhsim_auto_flow_20261027_allcores/reference_vs_initial/thp_verification.json)、[构建身份](../../build/grhsim_auto_flow_20261027_allcores/initial/build.json)。

下一阶段按预定规则采集自动初解本身的 profile，自动选择迁移源与目的分区。自动初解与迁移候选使用相同编译兼容规则；不使用旧 assignment 的分区编号决定搜索范围。
