# TNO0014 两侧 RepCut retained 构建门

## 标准 performance 流程均完成

两侧 `result.json` 均为 `status=pass`、`performance=true`，32 partitions、8 solver seeds、相同 solver/options/epsilon、C++ 编译器、CoreMark/NEMU 输入字节。runtime 均为 CPU0–31、NUMA0、ASLR disabled、codepages=auto、thread pinning enabled。

| 项目 | before | after |
| --- | --- | --- |
| 初始 assignment | seed 3 | seed 7 |
| 初始容量门 | pass | pass |
| Retained | candidate | initial |
| Migration | 接受 | 无满足通信预算且预测更好的候选 |
| 完整 NEMU/DiffTest | 通过 | 通过 |
| 同版本 native/RepCut 功能签名 | 一致 | 一致 |

before 的迁移候选为 `piece_594744_p18_to_3`，移动 27 atoms。两轮内部 AB/BA 均有 6/8 对获胜，配对 walltime delta 中位数分别 −3.721% / −2.130%，随后完成 retained candidate 的重复运行。

after 完成 8 次初始 100k、两次 instrumented trace、context extraction 和候选 ranking；既有通信预算要求各项 send/receive calls/bytes 的 sum/peak 均不增加。没有满足预算且预测更好的候选，因此标准流程保留 initial，未人为放宽预算。

完整配置、selection、migration、assignment/binary SHA 和 runtime gate 汇总：[repcut-build-gates.json](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/repcut-build-gates.json)。各阶段原始日志、分区与 C++/binary 位于对应 [before/repcut](../../build/xs/kunminghu-v3-grhsim-merge-20261110/before/repcut/) 和 [after/repcut](../../build/xs/kunminghu-v3-grhsim-merge-20261110/after/repcut/)。

## 正式对测边界

以上内部时间仅用于标准 pipeline 决定 retained 版本。上游合并前后差异由独立的 8 对 AB/BA 确定，输出到 `single-comparison/` 和 `repcut-comparison/`，与 selection/migration 样本分开。

两侧构建完成且 [TNO0013](./TNO0013_backend_compatibility_equivalence_gate_20261110.md) 的旧 C++ 字节一致性门通过后，正式驱动已获得构建锁并开始 native 预热。native 和 RepCut 正式测量串行；每个样本均检查完整 DiffTest、功能签名和 placement/locality。

硬件与环境快照见 [node030-runtime-hardware.json](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/node030-runtime-hardware.json)。所读 CPU governor 为 schedutil；本次未更改 governor，也未执行用户取消的外部任务空闲准入检查。配对统计将保留全部通过功能与 placement 门的样本，并报告 bootstrap CI。
