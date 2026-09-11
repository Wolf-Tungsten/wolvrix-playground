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
| NO00018 | [commit-port-arm](NO00018-grhsim-ir-candidate-commit-port-arm-20260911.md) | ACCEPTED：192,340/192,348 个 direct-commit 写端口改为操作数变化武装（24,303 个 cpu_pflags 字节、291,411 个 compute 侧武装站点，操作数未变的端口在边沿跳过求值）；证伪门实测武装比例上界 3.49%；生成 611.30 s（Make 墙钟）、编译 256.08 s；50k 两次均值 **87.0055 s**，相对同场控制 99.475 s 降低 **12.5352%**；相位 commit 52.36→31.61 s（−39.6%），轮次结构不变 |
| NO00019 | [activity-word-scan](NO00019-grhsim-ir-candidate-activity-word-scan-20260911.md) | ACCEPTED：三处逐字节稠密活动扫描统一加 uint64 空测试预过滤（调度 5,588 检查/758 组、domain 交接 461 槽/121 组、pflags 走查 23,898/24,303 字/3,027 组），语义逐位不变；生成 612.45 s、编译 263.03 s；50k 两次均值 **68.223 s**，相对同场控制 87.585 s 降低 **22.1061%**；相位 compute 53.48→44.82 s、commit 31.61→22.13 s，轮次结构不变 |
| NO00020 | [seed-quiesce](NO00020-grhsim-ir-candidate-seed-quiesce-20260911.md) | ACCEPTED：341 个全边沿守卫 compute unit（45 个播种 system/DPI 任务的 355 槽中）按入口守卫静默跳过（hist==event 时边沿守卫全假且内嵌采样无操作）；生成 618.66 s、编译 258.25 s；50k 四次均值 **66.962 s**，相对同窗口交错控制 70.720 s 降低 **5.3137%**（全控制池 4.3485%）；探针跳过率 50.26% 与预注册模型 50.25% 一致；轮次结构不变 |

当前搜索复盘（每 3 节点更新，本节点触发）：八个已接受机制可组合（共享 commit history、commit 边沿快照、compute history 共享、compute guard 提升、状态读变化激活、提交端口变化激活、活动扫描字打包、边沿静默跳过）。seed-quiesce 消除了播种层惰性一半的调用体成本：compute 44.82→42.96 s（诊断口径），轮次结构不变（2.0105 轮/eval），跳过率 50.26% 与预注册模型逐点一致；实测 −5.3137%（同窗口交错控制）落在预注册 +3.5..+5% 收益带上沿。当前最佳均值 **66.962 s**，距约 40 s 目标仍差 27.0 s；前三节点 −12.54%、−22.11%、−5.31%，活动没有陷入低收益微调。警示：约 90 分钟尺度的机器状态漂移已达 ~4%，超过小个位数收益——后续预期收益低于 ~6% 的节点应在启动前预注册交错控制/候选块设计。已排除方向维持：ready queue/间接 dispatch、frame 清零移除、activity-mask packing、pending 记录去重、从不写状态读者解除播种。后续按残余证据探索：42.96 s compute 相位（2,662 个任务的真实变化工作 + 播种层触发一半的真实求值与每轮播种调度残余，需输入粒度或值级机制）；commit 残余 22.06 s（5141/5142 未批处理多引用事件历史采样、memory cell staged 端口 2.73%、稳定历史扫描）；publication 1.89 s；约 11% 冻结 harness。本节点为上次复盘后第三个节点，复盘即本条。
