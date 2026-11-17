# TNO0036：共享事件区域静态成本门的跨模型验证

本轮落实 TNO0035 后用户授权的静态成本门，并同时验证 XiangShan 与 CV32。规则在两模型性能测量前冻结：共享候选相对共享前调度，compute group 数、边界值数、边界激活边数、状态读者激活边数均不得增加，且至少一项严格减少。否则恢复完整共享前调度。没有权重、设计名称判断、运行数据输入或测量后调整。

实现为默认关闭的 `ActivityScheduleOptions::eventRegionsSharedCostGuard`，CLI `-event-regions-shared-cost-guard`，Python `event_regions_shared_cost_guard`，要求启用 `eventRegionsShared`。graph/rewrite 保持不变，完整备份并恢复 `ActivityScheduleBuild`，包括操作分组、拓扑、commit 顺序、fanout 和状态读者。

这里的状态读者激活边是 `sum(stateReadSupernodes)`，与旧 schedule summary 中统计 state-read 值 fanout 的同名字段不同。guard 日志给出候选前后指标；随后原有 shared 日志也描述候选，拒绝时最终布局须看最终 schedule summary。

## 冻结输入与协议

- CV32：TNO0032 有限内联版的全部选项保持开启，只切换本次调度 guard。guard-off 源码与 TNO0032 逐文件一致；两侧用同一新库生成、独立编译，归一化图一致。第三后端为同 RTL Verilator。完整 smoke/CoreMark、总线 trace 后固定 8 轮正反序。
- XiangShan：TNO0033 full 优化版作控制，仍用同一 DefaultConfig 图、完整 DiffTest 和原有参数；新库分别生成 guard-off/on。要求 off 精确重现 full，on 根据静态判定精确重现 full 或 TNO0035 no_shared。预先允许在全部生成 C++/header/Makefile、编译配置及生成 harness 输入相同的情况下复用历史 ELF。复用是编译等价检查，不使用历史性能选择候选。之后重新做双 seed trace，原计划固定 8 轮 AB/BA；用户在第2对完成后明确要求只测3对，保留前三对连续完整样本。
- 所有计时串行运行于 node030 CPU96、NUMA1、ASLR off、单线程。与既有协议一致记录 SMT sibling CPU288 及 CPU/NUMA 放置。CV32 计时期间暂停自己的 XiangShan 生成进程。
- v1 XiangShan 目录仅为准备记录；v2 补齐 harness 和 driver 身份检查，正式生成/测量使用 v2。

## 静态结构

CV32 共享前→共享候选：compute groups 32→35、边界值 698→494、边界激活边 1116→574、状态读者激活边 259→250。因 group 数增加，规则拒绝共享候选。最终相对当前优化版 group 35→32，但受跟踪值 118→399，源码字节 1,049,346→1,316,994。

这揭示 guard 的明确局限：共享区域带来的少量 group 增长可以换取大量边界消除，并进一步使状态视图的静态覆盖证明成立。简单的逐维不增长规则会拒绝这种取舍；不能因“静态成本门”就认为性能一定安全。

CV32 独立诊断计数中，每周期 scalar 比较 **82.8356→171.8536**，compute group 执行总数 **17.0759→24.4167**，直接 activation OR **28.5263→87.7894**。区域编号变了，不能逐ID对齐；函数调用及求稳轮次的11项计数保持一致。

覆盖状态视图 **91→14**（其中内联 **73→14**）、复合表达式证明 **70→7**。失去的77个view全部重新出现比较，每周期贡献62.3503次额外检查，占全部额外89.0180次检查的约70.04%。12个条件锥的root与arm预算不变，输入缓存root/keys不变、miss仍为0；因此主要损失来自调度与视图证明的组合，不能解释为关闭了条件锥/缓存。

具体例子 value43824：原 `sched_1.cpp:487` 是直接内联状态视图；回退版 `sched_0.cpp:785` 起重新分配 value_u8 槽位、比较，并合入两条通知归约。源码、计数来源核对及脚本见 [离线归因](../../build/cv32e40p/shared-cost-guard-v1/guard-source-count-analysis.json)、[分析脚本](../../scripts/cv32e40p_shared_cost_guard_analysis.py)。旧诊断ELF与当前重新链接ELF哈希不同，报告以全部被插桩源码及probe顺序逐项一致证明计数对应关系，未声称ELF字节相同。

XiangShan 共享前→共享候选：compute groups **76,804→97,204**，边界值 **1,254,538→1,206,574**，边界激活边 **2,454,964→2,415,048**，状态读者激活边 **787,734→763,440**。同样只有group数增长，触发全局回退。两个模型都被拒绝，不能将这个静态判定误读为它已区分出模型之间的收益差异。

## 验证与结果

CV32 完整 smoke/CoreMark 和逐周期总线 trace 三后端一致。固定8轮外部 walltime：guard / 当前优化版均值 **+9.6715%**，95% CI **[+9.3533%, +9.9644%]**，8/8轮更慢；相对同RTL Verilator **+7.1573%**。原优化版在本轮仍快于 Verilator。所有轮次保留。

独立PMU（每guest cycle，仅一次，不是时间分摊）：退休指令 **9720.25→10367.08**（+6.65%），cycles **2860.54→3136.72**，branches **460.14→481.58**，branch-misses **1.316→1.156**。分支失败减少不足以抵消计算和边界维护增加。

XiangShan 源码门已通过：新库 guard-off 与 TNO0033 full 的所有生成 C++/header/Makefile逐文件一致；guard-on 与 TNO0035 no_shared逐文件一致。编译命令（路径归一化）、模型配置和生成harness输入也一致，故按预先策略复用同一 no_shared ELF，SHA256 `e0c46621336ed5b9e74cebdca8e99966fe3f582d1a0734402ad8ea8bc62a3ce8`。这说明新静态准入确实落到了原消融对应的程序，不是另一个未经归因的候选。[复用证明](../../build/xs/shared-cost-guard-20261116-v2/candidate/binary-reuse.json)。

XiangShan 双seed功能门及3对正式测量完成：每个seed的99,999条DiffTest记录一致，完整NEMU开启。外部wall配对均值 **−3.8855%**，中位 **−4.1660%**，3/3更快。三对变化依次 **−6.0689%、−4.1660%、−1.4215%**；原始秒数见下表。

| 对次 | full wall秒 | guard wall秒 |
| --- | ---: | ---: |
| 1 | 119.641734 | 112.380759 |
| 2 | 117.842170 | 112.932822 |
| 3 | 118.690240 | 117.003021 |

三对固定seed bootstrap的描述性95%区间为 **[−6.0689%, −1.4215%]**；样本很少且用户在运行中缩短原定样本数，不把它作为泛化收益的充分证据。TNO0035独立历史8对no_shared消融均值−6.60%、8/8更快，同一程序支持相同方向；两组不混合、不相加。

[原始配对与汇总](../../build/xs/shared-cost-guard-20261116-v2/paired/summary.json)、[用户调整记录](../../build/xs/shared-cost-guard-20261116-v2/user-policy-amendment.json)。[XiangShan独立审计](../../build/xs/shared-cost-guard-20261116-v2/independent-review/review.json)覆盖14个运行、2,823个CPU/线程快照、289个NUMA快照，全部通过。原始8对策略文件保持不变。外部停止监控在第3对保存后结束runner，没有启动第4个模拟器（children为空）；runner日志非零退出来自用户要求停止，不是功能失败。汇总由离线脚本重新构建，不删已完成样本。

## 结论与后续边界

**该成本门对XiangShan有益，但对CV32明显有害，不能作为通用默认规则。** 保持新guard默认关闭，保留两模型原有配置；未按本轮结果调整规则、阈值或加入模型例外。当前实现是一个已验证的实验开关，不能称为跨模型优化解决方案。

共同根因是共享处理同时包含类合并和残余组细分，而后续状态视图证明又依赖最终分组/读者前沿。XiangShan的大规模细分增加入口及维护；CV32仅增加3个group却消除了大量边界，并支撑更多view消除。下一步若继续，应设计局部、可证明无环的合并/细分方案，并把视图消除后的真实静态接口纳入评价，而非对总group数设一票否决；这属于待实现方向，本轮没有追加候选。

验证包括活动调度回归、新guard专项回归、完整event-region O0/O3 sanitizer回归、10项Python参数转发（仅Python层，native stub）与14项测量脚本回归。初次专项fixture未制造成本增长，修正后通过；失败日志保留。CV32独立审计覆盖36个运行与72个原始CPU/NUMA快照。[审计](../../build/cv32e40p/shared-cost-guard-v1/independent-review/review.json)。

复现入口：[CV32 驱动](../../scripts/cv32e40p_shared_cost_guard_compare.py)、[XiangShan 驱动](../../scripts/xiangshan_shared_cost_guard_compare.py)、[功能规则](../../wolvrix/docs/transform/activity-shared-event-regions.md)。

产物：[CV32](../../build/cv32e40p/shared-cost-guard-v1/)、[XiangShan](../../build/xs/shared-cost-guard-20261116-v2/)。
