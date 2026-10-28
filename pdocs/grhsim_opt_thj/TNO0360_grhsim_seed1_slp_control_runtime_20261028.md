# TNO0360：同一 seed 1 的 SLP 编译选项对照

日期：2026-10-28。承接 [原始选项构建](./TNO0358_grhsim_seed1_original_flags_build_20261028.md) 和 [原始恢复版直接对照](./TNO0359_grhsim_seed1_original_flags_restored_runtime_20261028.md)。

## 同源 fresh 8 对 AB/BA

| 指标 | seed 1 no-SLP | seed 1 原始选项 | 配对变化 | 原始选项胜出 |
|---|---:|---:|---:|---:|
| 进程 walltime | 10.390 s | 9.430 s | −9.007% | 8/8 |
| Host | 10.309 s | 9.372 s | −8.895% | 8/8 |
| global eval | 41.648 µs | 37.389 µs | −10.011% | 8/8 |
| global update | 6.405 µs | 6.013 µs | −6.432% | 8/8 |
| max-part eval | 28.998 µs | 26.709 µs | −7.790% | 8/8 |
| sum-part eval | 541.765 µs | 481.779 µs | −11.057% | 8/8 |

百分比均取逐对变化的中位数。walltime 的逐对变化范围为 −9.674% 到 −8.535%，AB/BA 两种顺序的中位变化分别为 −8.845%/−9.152%。

两边采用同一份 seed 1 生成代码、同一 Clang 23.1.2、O3/native、同一原始 archive 成员顺序和 compute 入口对齐，唯一移除的模型编译选项为 `-fno-slp-vectorize`。memory、初始标签及 emitter preset 均未重新选择，未实施人工或自动迁移。

## 合并判断

| 独立测量窗口 | baseline walltime | seed 1 原始选项 walltime | 配对变化 |
|---|---:|---:|---:|
| 原始恢复版 → seed 1 原始选项 | 8.925 s | 9.480 s | +6.352% |
| 同 seed 1 no-SLP → seed 1 原始选项 | 10.390 s | 9.430 s | −9.007% |

去掉 no-SLP 对该 seed 1 有明确性能收益；该原始选项产物仍慢于原始恢复版，恢复版继续作为全局性能锚点。两行属于独立窗口，不跨行相减；此前含 no-SLP 的 +16.002% 对照不能全部归因于划分。

两组共 32 次 C100000 和 4 次 C100 smoke，功能、完整代码 THP、N=K=32、CPU96–127、all-spin、push、preferred NUMA1 和 64-byte compute 对齐核验均通过。所有长测的 PC=0x80000c0c、instrCnt=240349、cycleCnt=99996、guest=100001、steps=200102；保留全部成功样本，未作离群值筛除。

本轮明确尝试的是用户指定的原始编译选项。现有 Clang 23 兼容默认规则未更改；C100000 通过仅覆盖本次产物与 workload。原 no-SLP binary/archive、原始恢复版 ELF 的身份均与运行前一致。原始选项 ELF 单独保留，未覆盖任何旧产物。

## 产物

- [同 seed 编译选项对照](../../build/grhsim_seed1_original_flags_20261028/same_seed_no_slp_ab_ba/summary.json)、[原始恢复版对照](../../build/grhsim_seed1_original_flags_20261028/original_reference_ab_ba/summary.json)。
- [最终核验](../../build/grhsim_seed1_original_flags_20261028/verification.json)、[总结果](../../build/grhsim_seed1_original_flags_20261028/result.json)、[构建与选项记录](../../build/grhsim_seed1_original_flags_20261028/build.json)。
- [原始选项 emu](../../build/grhsim_seed1_original_flags_20261028/harness/grhsim-compile/emu)、[可复现驱动](../../build/grhsim_seed1_original_flags_20261028/run.py)。
