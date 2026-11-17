# TNO0037：共享区域合并后的局部环细分

TNO0036 的全局成本门拒绝了两个模型的共享布局，导致 CV32 明显退化。本轮按用户要求先改造分组构造方式；随后另行验证跨区域状态表达式证明。两项各设默认关闭开关，不按本轮性能选择组合。

## 静态规则与证明边界

保留原共享类选择：相同多终点集合、跨至少两个旧组、最多8192个操作，完整compute node、硬边界和commit顺序不变。提取共享类后，其余节点先保留原分组。根据compute-node依赖构造组图，以迭代Kosaraju找非平凡SCC；仅对SCC内的旧组余部按终点集合细分。环下游但不在环内的组不拆分。

如果仍有环但无法继续细分，只撤回环内的共享类，再从原分组构造；其他类继续保留。每步增加细分或永久撤回至少一个类，因此终止。最终对完整操作集合、真实依赖、拓扑和commit顺序作严格重建。此处局部不是“全局最小拆分”的保证；同一SCC内所有可细分余部都会被细分。

开关 `eventRegionsSharedCycleRefinement` / `-event-regions-shared-cycle-refinement` / Python `event_regions_shared_cycle_refinement`，默认关闭，要求shared开启。本轮全局成本门关闭。没有模型名称、运行频率、profile或拟合阈值。

## 固定对照

CV32：TNO0032 full优化版、新局部细分版、同RTL Verilator，8轮正反序。
XiangShan：TNO0033 full优化版与新局部细分版，3对AB/BA，延续用户上轮指定的短测规模；smoke及seed0/1各100k完整DiffTest先通过。

新开关关闭必须重现旧full所有生成源码。两模型使用同一冻结规则。所有性能测量串行在node030 CPU96、NUMA1、关闭ASLR，计时前暂停自己的生成/构建任务。

## 初始结构与验证

CV32保留6个共享类，SCC细分0轮、撤回0类；原来的3处余部拆分被省去。总组数39→26，受跟踪值118→117；91个状态视图和70个复合表达式证明保留，边界值494→493。图及新开关关闭源码一致。

纯图回归覆盖：保留无关混合组、仅细分环内余部、保留环下游组、不能细分时撤回相关类并保留独立合并、5万节点深DAG。完整emitter场景覆盖双时钟、异步复位、门控时钟、时钟保持时输入变化、存储器旧状态及masked写入，O0/O3 sanitizer运行通过。3项CTest通过。CV32完整smoke/CoreMark和总线trace通过。

CV32固定8轮完成：相对当前优化版walltime **−0.0668%**，95% CI **[−0.6964%, +0.6334%]**，5/8轮更快，不能确认稳定增益或证明严格性能等价；相对同RTL Verilator **−2.5622%**，CI **[−3.1221%, −1.9103%]**。没有上一轮全局回退的明显损失。所有样本保留。

行为计数：compute group执行17.0759→13.5421次/周期，但比较82.8356→84.5730，activation OR 28.5263→29.4323。减少细分会让部分保留逻辑执行更频繁；槽位、静态比较数减少不意味着动态比较必然减少。固定点轮数、条件锥root/arm、缓存访问/miss及共享译码访问计数保持一致。compute函数数4→3，函数调用不要求逐项相同。

XiangShan候选生成与重新编译完成：6,542个共享类全部保留，一轮仅细分3,266个环内余部，撤回0类。compute groups 97,204→83,828；shared阶段边界值1,206,574→1,204,790；covered views 2,870→2,888，composed 1,456→1,463。

离线compute统计：group guard 94,581→81,205，activity word guard 12,151→10,479，持久activation更新位置519,217→502,343，scalar检查位置738,086→736,190。ELF条件跳转590,475→561,522，静态指令14,105,230→14,106,285，RSP访存操作数1,104,143→1,157,313，入口栈减法中位2,048→2,216 B、最大20,728→20,744 B。静态分支减少不等于动态加速，栈和寄存器布局仍有取舍。条件锥11,563→11,550、输入缓存215→213；分组也改变了其他静态优化的适用集合，不能当成仅删除入口指令的单一变化。详见[源码/ELF](../../build/xs/shared-cycle-refinement-20261116-v1/offline-structure/candidate.json)。

计时驱动第一次从snapshot目录启动，被同目录的快照模块遮蔽，错误解析ROOT，在任何仿真启动前失败。保留`paired-runner-path-failure/`，从无同名模块的runtime-driver目录运行字节相同的三对runner；额外correction记录保存脚本身份，所有模型/规则/样本计划不变。修正后的功能及测量已完成。产物：[CV32](../../build/cv32e40p/shared-cycle-refinement-v1/)、[XiangShan](../../build/xs/shared-cycle-refinement-20261116-v1/)。

## XiangShan三对结果

双seed各99,999条DiffTest记录一致。相对full外部walltime配对均值 **+2.8803%**，中位 **+2.6905%**，描述性95% bootstrap区间 **[+2.6761%, +3.2743%]**，0/3更快。

这条局部规则保住了CV32的大部分既有收益，但XiangShan反而退化，尚未达到双模型同时受益。保持默认关闭；没有据测量调SCC规则、类选择或预算。少入口不等于少动态工作，保留混合余部会改变活动粒度；同时缓存资格和机器布局变化仍需单独证据，当前不能将时间差精确分摊。
[XiangShan结果](../../build/xs/shared-cycle-refinement-20261116-v1/report.json)、[CV32结果](../../build/cv32e40p/shared-cycle-refinement-v1/report.json)。

从原始样本重新核对CPU/NUMA放置、ASLR、输入与binary身份、配对方向及统计，两个模型均通过：[XiangShan复核](../../build/xs/shared-cycle-refinement-20261116-v1/independent-review/review.json)、[CV32复核](../../build/cv32e40p/shared-cycle-refinement-v1/independent-review/review.json)。没有删样、追加样本或按结果修改规则。后续跨区域证明使用预先指定的未共享对照，见[TNO0038](./TNO0038_cross_region_state_expression_proofs_20261116.md)。
