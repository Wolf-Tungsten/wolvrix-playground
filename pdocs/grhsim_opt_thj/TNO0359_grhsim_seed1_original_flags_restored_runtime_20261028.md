# TNO0359：seed 1 原始选项与恢复版直接对照

日期：2026-10-28。产物通过 [TNO0358 构建检查](./TNO0358_grhsim_seed1_original_flags_build_20261028.md)，双方均为 Clang 23/O3/native、未使用 no-SLP 的模型构建。

## Fresh 8 对 AB/BA

| 指标 | 原始恢复版 | seed 1 原始选项版 | 配对变化 | seed 1 胜出 |
|---|---:|---:|---:|---:|
| 进程 walltime | 8.925 s | 9.480 s | +6.352% | 0/8 |
| Host | 8.858 s | 9.414 s | +6.238% | 0/8 |
| global eval | 34.700 µs | 37.5005 µs | +8.114% | 0/8 |
| global update | 6.166 µs | 6.059 µs | −2.103% | 8/8 |
| max-part eval | 22.378 µs | 26.9245 µs | +20.222% | 0/8 |
| sum-part eval | 494.779 µs | 483.0055 µs | −2.400% | 8/8 |

百分比均取逐对变化的中位数，不能以两列中位数的比值替代。各分区 eval 总量减少，但最长分区和全局 eval 增加；去掉 no-SLP 后仍未超过恢复版。

本轮所有运行均固定 node030 CPU96–127、N=K=32、C100000、push、all-spin、preferred NUMA1、ASLR off 和完整代码 THP；16 次长测加 2 次 C100 smoke 全部通过功能与大页检查。7116 个候选 compute 入口的 64-byte 对齐检查通过，双方输入身份在运行前后未变。

本轮结果证明这个 seed 1 产物通过当前 C100000 workload；不据此撤销 [TNO0339](./TNO0339_grhsim_clang23_change_reduction_20261027.md) 已独立复现的通用编译器问题或改变默认兼容规则。

## 数据

- [原始结果](../../build/grhsim_seed1_original_flags_20261028/original_reference_ab_ba/summary.json)。
- [功能签名与实际线程配置](../../build/grhsim_seed1_original_flags_20261028/original_reference_ab_ba/functional_signatures.json)。
- [THP 审计](../../build/grhsim_seed1_original_flags_20261028/original_reference_ab_ba/thp_verification.json)、[运行策略与对齐](../../build/grhsim_seed1_original_flags_20261028/original_reference_ab_ba/measurement_policy.json)。
- [7719 个编译命令的控制变量核验](../../build/grhsim_seed1_original_flags_20261028/compile_control_verification.json)。
