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
| NO00021 | [history-cohorts](NO00021-grhsim-ir-candidate-history-batch-overwrite-20260912.md) | ACCEPTED：逐 history 证明采样等价，在混合 commit task 内共享存储与边沿谓词；独立 bool 地址减少 8404、批量采样站点 212→0；完整生成 **597.25 s**、编译 **265.58 s**；六次交替 50k 均 NEMU PASS，新均值 **64.585333 s**、旧均值 **66.792333 s**，降低 **3.304271%**；max(new) 65.287 < min(old) 66.480 s，U=0、单侧精确 p=0.05。旧 0.534% 比较因样本交叉和 harness 配置不一致作废 |
| NO00022 | [shared-port-edge](NO00022-grhsim-ir-candidate-shared-port-edge-20260913.md) | ACCEPTED：497 个任务共享端口边沿，3412 个块检查归为任务入口检查，按实际端口掩码一次消费活动字节；完整生成 **615.88 s**、编译 **253.93 s**；六次交替 50k 均 NEMU PASS，新均值 **63.223 s**、旧均值 **65.386 s**，降低 **3.308048%**；max(new) 63.589 < min(old) 64.625 s，U=0、单侧精确 p=0.05。多种通知/值分支尝试未通过，全部撤销 |
| NO00023 | [compute canonicalization](NO00023-grhsim-ir-candidate-compute-residual-20260913.md) | ACCEPTED：GrhSIM 同类型赋值归一化后共享精确重复的纯计算，删除 **434931** 个操作/值，任务 **5595→5036**；完整生成 **609.71 s**、fresh 编译 **240.37 s**；六次交替 50k 均 NEMU PASS，新均值 **60.645667 s**、旧均值 **63.169000 s**，降低 **3.994575%**；max(new) 60.678 < min(old) 62.719 s，U=0、单侧精确 p=0.05。结果转发、bool 包装及仅 identity 尝试未通过，失败结果全部保留、源码撤销 |

前次定期搜索复盘（NO00020，每 3 节点更新）：八个已接受机制可组合（共享 commit history、commit 边沿快照、compute history 共享、compute guard 提升、状态读变化激活、提交端口变化激活、活动扫描字打包、边沿静默跳过）。seed-quiesce 消除了播种层惰性一半的调用体成本：compute 44.82→42.96 s（诊断口径），轮次结构不变（2.0105 轮/eval），跳过率 50.26% 与预注册模型逐点一致；实测 −5.3137%（同窗口交错控制）落在预注册 +3.5..+5% 收益带上沿。当时最佳均值 **66.962 s**，距约 40 s 目标仍差 27.0 s；NO00018–NO00020 分别 −12.54%、−22.11%、−5.31%，未陷入低收益微调。约 90 分钟尺度的机器状态漂移已达 ~4%，后续所有节点均须按最新 goal 要求预注册六次交错比较。已排除方向维持：ready queue/间接 dispatch、frame 清零移除、activity-mask packing、pending 记录去重、从不写状态读者解除播种。

NO00021 收尾更新（距上次定期复盘 1 个节点）：将 commit history 共享扩展至混合 task，删除 8404 个独立 history 地址和全部 212 个 batch 采样站点。新旧六次交错全秩分离，当前最佳均值 **64.585333 s**，同窗口降低 **3.304271%**，距约 40 s 仍差 **24.585333 s**。候选样本标准差 1.098814 s，高于对照 0.484114 s，全部样本均保留。前期 helper/cache 微调未通过，最终收益来自已验证的组合机制，不能将历史配置不一致的 0.534% 比较算作收益。最新相位诊断仍属于 NO00020（compute 42.96 s、commit 22.06 s、publication 1.89 s），本节点未重新采样；5141/5142 的私有多引用 history 已覆盖。后续先刷新残余证据，再考虑 compute 输入粒度/值级重复求值与 staged memory 访问，避免继续围绕已无 batch 的 helper 微调。本节点已完成，未启动 NO00022。

NO00022 收尾更新（距上次定期复盘 2 个节点）：共享提交端口的缓存边沿，将每个
活动端口的边沿判断与 consumed 累积改为任务共同判断和字节掩码消费，混合边沿
继续原路径。当前最佳 **63.223 s**，同窗口六次全秩分离、降低 **3.308048%**，距
40 s 仍差 **23.223 s**。最终相位 compute **41.914338 s（67.44%）**、commit
**18.606339 s（29.94%）**、publication **1.557333 s**，轮次仍 201258/100102。
本节点先刷新了 NO00021 profile，随后否定 inline 通知、enable 条件传播、提交
签名通知合并、目标活动字聚合、高扇出 compute 门、pflag 目标汇聚、变化组提前
发布、单生产者分支及两个通知机制组合；平均数改善但未全秩分离的版本也未保留。
静态少写/少代码/局部生命周期变短均不能代替运行证据，下一节点应从残余 compute
与稀疏端口执行等机制出发，避免循环通知阈值微调。NO00023 收尾须做三节点定期
复盘。本次节点完成，未启动 NO00023。

本次定期搜索复盘（NO00023，覆盖 NO00021–23）：三个节点分别共享混合 task 的
history、共享提交端口边沿、归一化并共享 GrhSIM 纯计算，各自同窗口六次交替收益
为 **3.304271% / 3.308048% / 3.994575%**，都满足全秩分离；不同窗口间的均值
不能相减或相乘作为累计实测。当前最佳正式样本 **60.669 / 60.678 / 60.590 s**，
均值 **60.645667 s**、样本标准差 **0.048418 s**，距约 40 s 仍差
**20.645667 s**（约需再降低 34.04%）。完整生成/编译 609.71/240.37 s 与全部
等价门槛通过，长期目标仍未完成。

最终相位（独立诊断，未混入六次）：Host **59.157 s**，compute **38.935131 s
（66.01%）**、commit **18.505281 s（31.37%）**、publication **1.468784 s**，
evals/rounds 仍 **100102/201258**。删除 233816 个 identity assigns 与 201115 个
重复 compute 使操作数减少 9.60%、text 减少 3.36%，状态与初始化保留；仅 identity
版本反而回退 6.10%，说明减少操作量还需结合分区与运行验证。无条件结果转发在
正式交替中回退 2.46%，多使用转发筛选回退 4.90%；bool 直接转换首先出现语义
INVALID，修正后未进入 XiangShan 实验。这些失败全部归档，不能复用早期单对改善。

近三节点降幅较 NO00017–19 收窄，前两节点在已有 history/边沿机制上扩大覆盖，
本节点最终转向语义层去重，避免继续消耗在 helper/cache 或通知阈值上。保留早期
已排除方向，同时新增排除块内局部结果转发、直接 bool 包装简化、仅 identity
删减。下一步优先研究依赖驱动的细粒度 compute、稀疏 commit 端口执行或 staged
memory 访问；先刷新当前构建的动态覆盖和收益上界，避免用 NO00022 的平坦 profile
推断 NO00023 的具体热点。单次相位比正式均值更快也再次说明机器状态可漂移，
下一节点仍需重新预选截止并预注册六次交替。本节点已完成，不启动下一节点。
