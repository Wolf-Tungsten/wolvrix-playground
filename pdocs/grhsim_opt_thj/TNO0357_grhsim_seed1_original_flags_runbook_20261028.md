# TNO0357：seed 1 原始编译选项对照计划

日期：2026-10-28。承接 [TNO0356](./TNO0356_grhsim_portfolio_followup_final_comparison_20261028.md)。用户要求 seed 1 使用原始编译选项，不使用 no-SLP。

## 固定条件与唯一改动

直接复用八份初解中 km1 最低的 seed 1 生成源码，不重新运行 memory 选择、求解、分配或 emitter。7719 个模型对象全部重编，编译器仍为 Clang 23.1.2，选项为 `-std=c++20 -O3 -march=native -pthread`，显式移除 `-fno-slp-vectorize`。

保持原始源码路径、头文件路径、归档成员顺序、完整后端 preset 和 64-byte compute 入口对齐。编译使用 node030 全部 CPU0–383；原 seed 1 no-SLP 的 archive、binary 及恢复版锚点均保留并校验身份。

本实验按用户要求绕过 [TNO0339](./TNO0339_grhsim_clang23_change_reduction_20261027.md) 的编译兼容保护，仅对独立产物生效。不改变通用构建默认规则，也不在失败后自动切回 no-SLP。

## 检查顺序

1. 完整编译、按原始顺序重归档、链接；审计全部 compute 入口对齐。
2. 在 node030 CPU96–127、N=K=32、all-spin、preferred NUMA1、ASLR off、完整代码 THP 下，执行 C100 smoke 和 C100000 NEMU 检查。
3. 功能通过后，对恢复版原始 ELF 运行 fresh 8 对 AB/BA；再对同一 seed 1 的 no-SLP ELF 运行 fresh 8 对，区分划分与编译选项影响。
4. 若功能失败，保留完整日志，不使用失败运行时间得出性能结论。

可重现驱动：[run.py](../../build/grhsim_seed1_original_flags_20261028/run.py)。所有输出写入独立的 `build/grhsim_seed1_original_flags_20261028/`。构建及运行结果另立增量记录。
