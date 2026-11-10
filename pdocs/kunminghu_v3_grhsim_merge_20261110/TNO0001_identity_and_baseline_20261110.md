# 001：身份与合并前基线

本阶段固定父仓、XiangShan、difftest、Wolvrix、workload 和工具链身份，并在 XiangShan 合并前构建当前 native GrhSIM 基线。

- XiangShan 合并前 commit：`77ed568fc`
- 上游目标：`origin/kunminghu-v3`
- 目标配置：`DefaultConfig`，单核，完整 DiffTest
- workload：`coremark-2-iteration.bin`，正式运行 100,000 周期
- 机器可读身份：[identity-before.json](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/identity-before.json)

构建、功能门和正式 walltime 样本将在本阶段完成后追加。
