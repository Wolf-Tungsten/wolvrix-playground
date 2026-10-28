# TNO0353：八份择优初解的完整生成与构建检查

日期：2026-10-28。承接 [TNO0352 流程](./TNO0352_grhsim_portfolio_selected_followup_runbook_20261028.md)，本篇仅记录生成与构建结果，普通运行和自动迁移另记。

## 固定配置核验

seed 1 标签经 assignment replay 后逐字节不变，301,184 个 ASC，SHA256 为 `f71f136171ad4759fca32435b9c57bdcf6d3fa3ae9302ff29229161bd62cc83a`。沿用固定历史 memory 输入及完整 26 项 preset，没有手工改写分配标签或指定迁移端点。

新 partitioned graph 为 4,131,848,610 B，SHA256 为 `96a6ff4be00929df4eef46d2be5d3ad4b4b2bee6254403566daf9181a930cc1d`。发射记录与固定 memory 对照的 library 和 options 逐项相同。执行计划分析显式使用这个新图；参考 emit 记录只提供同一 library/options，最终计划输入 hash 与实际发射输入一致。

## 通过结果

| 检查 | 结果 |
|---|---|
| 完整 C++ 发射 | PASS，7,719 个源文件 |
| execution-plan gate | PASS，32 分区，1,220.40 s |
| groups / batch_groups | 各 57,029 行 |
| Clang 23 / O3 / native / no-SLP | PASS，7,719 个对象，编译至链接 90.91 s |
| compute 入口 64B 对齐 | 7,116 / 7,116，未对齐 0 |
| 归档顺序 | 使用本包生成 Makefile 的 SRCS 顺序，未按文件名排序 |
| 编译并发与 CPU 许可集合 | 384 jobs，node030 CPU0–383 |

最终 emu 为 107,274,064 B，SHA256 为 `7c7eb1e3e126366839fba711b3e232bf478417f5430f34ee9c64a7237c2ada31`。archive 为 120,241,112 B，SHA256 为 `1303a301940769f7151073ee726d079d2c7042f8c270e6c41e608b52dc3fb240`。

`-fno-slp-vectorize` 与同编译恢复版一致，兼容性 fixture 的结果已保存。这是编译设置控制；与历史原始恢复版二进制的对照必须单列，不能全部归因于分配变化。

生成和计划任务均已结束后才进入 C100 smoke 与 C100000 的 8 对 fresh AB/BA。本阶段尚不作 walltime 优劣结论。

## 原始记录

- [分配 replay](../../build/grhsim_portfolio8_followup_20261028/initial/partition.json)、[完整发射配置](../../build/grhsim_portfolio8_followup_20261028/initial/emit.json)。
- [执行计划身份与行数](../../build/grhsim_portfolio8_followup_20261028/initial/plan/identity.json)。
- [构建、归档顺序及对齐结果](../../build/grhsim_portfolio8_followup_20261028/initial/build.json)。
