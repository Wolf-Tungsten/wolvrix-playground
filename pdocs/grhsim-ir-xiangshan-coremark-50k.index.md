# GrhSIM-IR XiangShan CoreMark 50k 报告索引

本索引从 [goal](grhsim-ir-xiangshan-coremark-50k.goal.md) 分离单独维护。报告文件按创建顺序以 `NOxxxxx` 编号前缀命名，编号单调递增、不复用；新节点完成时在表尾追加登记，并同步更新文末复盘。

保留历史结果；旧报告中按阶段拆分执行或提交的做法不再适用。后续按完整节点登记。

| 编号 | 报告 | 状态 / 关键结论 |
|---|---|---|
| NO00001 | [M0 baseline](NO00001-grhsim-ir-m0-baseline-20260910.md) | 基线：gsim 20.640 s；原始 IR 304.197 s |
| NO00002 | [frame-init](NO00002-grhsim-ir-candidate-frame-init-20260910.md) | REJECTED：305.17 s，移除清零无收益 |
| NO00003 | [activity-guard](NO00003-grhsim-ir-candidate-activity-guard-20260910.md) | 前一基线：均值 284.699 s |
| NO00004 | [batch-packing](NO00004-grhsim-ir-candidate-batch-packing-20260910.md) | REJECTED / INCOMPLETE：编译未完成，无性能结论 |
| NO00005 | [ready-queue](NO00005-grhsim-ir-candidate-ready-queue-20260910.md) | REJECTED / INVALID：cycle 0 RTL assertion，0 instructions |
| NO00006 | [ready-dispatch](NO00006-grhsim-ir-candidate-ready-dispatch-20260910.md) | REJECTED / REGRESSION：737.862 s，对拍通过但显著变慢 |
| NO00007 | [activity-mask-pack](NO00007-grhsim-ir-candidate-activity-mask-pack-20260910.md) | REJECTED：仅减少 0.1179477% 静态 guard 检查项，无运行收益证据 |
| NO00008 | [scalar-stage-elision](NO00008-grhsim-ir-candidate-scalar-stage-elision-20260910.md) | VALIDATED / 最低均值：279.9485 s，仍有噪声限制 |
| NO00009 | [phase-profile](NO00009-grhsim-ir-phase-profile-20260910.md) | 诊断：off/on 287.162/292.350 s，均对拍通过；完整生成/编译 606.29/477.30 s |
| NO00010 | [task-hotspots](NO00010-grhsim-ir-task-hotspots-20260910.md) | 诊断：283.389 s，56,397 样本，对拍通过；未实施优化 |
| NO00011 | [shared-history](NO00011-grhsim-ir-candidate-shared-history-20260910.md) | ACCEPTED：共享同一 commit task 内等价私有 event history；生成 615.95 s、编译 246.50 s；50k 候选均值 268.947 s，对照均值 292.113 s，提升 7.9303% |
| NO00012 | [edge-snapshot](NO00012-grhsim-ir-candidate-edge-snapshot-20260910.md) | ACCEPTED：496 个 task 的 226,510 次重复边沿条件引用复用 496 个快照；生成 611.87 s、编译 255.12 s；50k 两次均值 215.6715 s，相对最终控制 270.194 s 降低 20.1790% |
| NO00013 | [pending-dedup](NO00013-grhsim-ir-candidate-pending-dedup-20260910.md) | REJECTED：四处入队路径均由 dirty 位保证同一 key 每轮最多一条记录；内存按 cell 分配 key。静态证伪，未运行性能实验 |
| NO00014 | [residual-hotspots](NO00014-grhsim-ir-residual-hotspots-20260910.md) | 诊断：当前最佳构建相位 compute 70.3274% / commit 24.6039% / publication 5.0300%；flat 热点 `cpu_write_scalar<bool>` 8.7076%、commit 5141 2.2560%；两次诊断运行 NEMU PASS，性能基线不变 |
| NO00015 | [compute-history](NO00015-grhsim-ir-candidate-compute-history-20260911.md) | ACCEPTED：51 个 compute task 的 13,382 个等价私有 event history 按 unit 共享代表元；生成 609.89 s、编译 254.56 s；50k 两次均值 182.415 s，相对同场控制 213.636 s 降低 14.6141% |
| NO00016 | [compute-guard-hoist](NO00016-grhsim-ir-candidate-compute-guard-hoist-20260911.md) | ACCEPTED：51 个 assert/DPI task 的 13,630 次重复事件 guard 归并为 323 个 unit 级局部量；生成 601.22 s、编译 251.18 s；50k 两次均值 169.560 s，相对同场控制 183.520 s 降低 7.6068% |
| NO00017 | [seed-elision](NO00017-grhsim-ir-candidate-seed-elision-20260911.md) | ACCEPTED：状态读者全部改为 commit fanout 真变化激活（仅 system/DPI 保留播种），投影位图物化且只决定收敛标记；每轮播种存储 1,716→51；生成 600.89 s（Make 墙钟 960.06 s）、编译 253.02 s；50k 两次均值 **98.915 s**，相对同场控制 165.820 s 降低 **40.3461%**；相位 compute 116.62→45.65 s |

当前搜索复盘（每 3 节点更新）：五个已接受机制可组合（共享 commit history、commit 边沿快照、compute history 共享、compute guard 提升、状态读变化激活）。seed-elision 消除了播种状态读层这一成本中心：compute 相位 116.62→45.65 s（−60.9%），commit 相位不变（52.36 s，占 eval 52.4% 成为主要成本），轮次结构不变（2.0105 轮/eval）。当前最佳均值 **98.915 s**，距约 40 s 目标仍差 58.915 s；活动没有陷入低收益微调（本节点 −40.35%）。已排除方向维持：ready queue/间接 dispatch、frame 清零移除、activity-mask packing、pending 记录去重、从不写状态读者解除播种（静态证伪仅 31 单元）。后续按残余证据探索：commit 相位（task 5141 仍最热 2.65%、commit 前十 8.6%、5141 的 4,094 个 2 项边沿判定此前界 2-3%）；约 45.65 s compute 残余（DPI/system 播种单元与真实变化驱动工作，需新 profile）；诊断中观察到的 80% 入队但无变化 publish 记录（2,154 条/轮 vs 431 变更，staging 侧候选）；evaluator 每轮固定成本。本次完成 seed-elision 节点。
