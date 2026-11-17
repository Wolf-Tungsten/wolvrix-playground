# TNO0038：独立验证跨区域状态表达式证明

在TNO0037局部细分候选冻结后，按用户授权继续第二项工作。该实验使用固定未共享调度作为对照，不依据TNO0037性能选择组合，局部细分开关与全局成本门均关闭。

## 规则

`covered_state_view_cross_region` / `WOLVRIX_GRHSIM_COVERED_STATE_VIEW_CROSS_REGION`，默认关闭，依赖原通知及复合证明选项。沿表达式追溯时可跨越更早的纯compute组，仍要求所有依赖按组内顺序或active ID向前，读源为同一单写者寄存器的非物化读取；提交发生在compute之后，读取同一快照。操作种类、32-op/16-depth证明预算、4-tree-op与use预算均不变。

准入仍要求生产者与所有消费者已有独立寄存器激活前沿；不增加读者、不用候选删除互相证明。缓存键/结果、事件、别名、公开/波形观察及effect/commit边界不放宽。启用后新增标记 `Cross-region state expression`，关闭时源码必须精确重现旧版。

## 对照与验证

- CV32：未共享布局、跨组证明版、TNO0032 full共享参考、同RTL Verilator，固定8轮正反序。
- XiangShan：预先计划TNO0035 no_shared与同调度跨组证明，3对AB/BA，先smoke及双seed100k DiffTest；实际生成和ELF身份检查证明没有代码变化，因此省去这组重复运行，详见下文。
- 性能串行在node030 CPU96、NUMA1、ASLR off；运行中不调整证明规则或后续候选。

跨组专项fixture使用真正的独立q读取和图用户；检查O0/O3 sanitizer语义及组执行次数，覆盖1/17signed/64位、双时钟、异步复位、masked写、重复eval、长表达式notify回退。缓存键、公开值、effect与缺少独立读者回退通过。已有复合表达式回归通过。

测试过程有两类保留记录：一次误重复启动导致生成目录互相覆盖，取消重叠后重新运行；初始正例把原始寄存器读本身搬到跨组使用，触发既有“物化读源不可展开”保护，修正fixture使读源保持局部后通过。生产证明未为这些测试放宽语义边界。

## CV32静态结果

**未命中新视图。** 开关前后全部生成C++/header一致，两个ELF的`.text`、`.rodata`、`.data`也逐节相同；这是代码无变化，不能从计时噪声宣称此规则改善性能。

进一步对TNO0036丢失的77个视图作独立图筛查：77个都仍是单寄存器表达式；20个跨组且生产者缺少直接q读者路径，74个缺少至少一个消费者直接q读者路径。两类集合的并集覆盖全部77个。因此仅解除“表达式必须同组”限制不足以恢复它们；独立激活条件才是本图的主要阻碍。初筛依据IR直接读者集合；随后从emitter实际execution plan导出active ID与states.targets，重算同样得到20个生产者缺失、74个消费者集合缺失，并集77，确认该结论也适用于真实激活前沿。映射CSV逐文件一致，没有用运行共激活作证明。[实际前沿审计](../../build/cv32e40p/cross-region-views-v1/actual-frontier-audit.json)、[导出输入身份](../../build/cv32e40p/cross-region-views-v1/frontier-inputs.json)。

[静态筛查](../../build/cv32e40p/cross-region-views-v1/cross-region-opportunity.json)、[ELF节一致性](../../build/cv32e40p/cross-region-views-v1/section-equality.json)、[CV32产物](../../build/cv32e40p/cross-region-views-v1/)、[XiangShan产物](../../build/xs/cross-region-views-20261116-v1/)。

CV32完整功能及trace一致，8轮外部walltime相对未共享控制 **+0.0044%**，95% CI **[−0.5751%, +0.5032%]**。这是相同源码/关键ELF节的独立编译对照，差异属于测量波动，不能据此宣称优化。相对TNO0032共享full参考仍慢 **9.5680%**，CI **[+9.0249%, +10.1050%]**；相对Verilator慢 **6.9529%**。所有样本保留。

## XiangShan结果与停止重复测量

重新生成、编译与冻结身份核对完成。**新增跨区域证明为0**，140个生成文件与no_shared基线逐文件相同，保留视图数量仍为2,226。编译命令归一化后相同，模型/仿真编译选项及生成harness输入也一致。

两个ELF都是99,865,024字节，`.text`与`.data`逐字节相同。完整文件仅4字节不同，全部位于DiffTest启动横幅的`__TIME__`字符串（`17:12:03`→`21:17:04`）；将这一个8字节字符串归一化后，完整ELF逐字节相同。不是笼统忽略rodata或debug节，也没有用新运行结果推断等价。[身份审计](../../build/xs/cross-region-views-20261116-v1/no-codegen-effect-audit.json)、[审计脚本](../../scripts/xiangshan_no_codegen_effect_audit.py)、[原始节哈希](../../build/xs/cross-region-views-20261116-v1/section-equality.json)。

据此在任何第二步XiangShan仿真启动前停止串行测量协调器；**本实验新增XiangShan性能对数为0，也没有新增XiangShan DiffTest运行**。旧no_shared的功能与消融记录仍属于历史验证，不能写成本轮新测结果。[省略重复测量的记录](../../build/xs/cross-region-views-20261116-v1/measurement-omission.json)。第一步局部细分的XiangShan三对结果不受影响，且CV32本轮8对全部保留。[CV32原始样本复核](../../build/cv32e40p/cross-region-views-v1/independent-review/review.json)。

## 结论

解除表达式同组限制本身没有恢复两个整机的机会，未实现“保留未共享布局，同时恢复CV32状态视图收益”。CV32的77个丢失视图均受实际独立激活前沿约束；这一项已由execution plan核对，不能通过直接给所有消费者增加寄存器通知来绕过，否则可能增加执行次数。XiangShan本轮仅证明零命中与代码不变，没有将CV32的具体阻碍数量外推到XiangShan。

与TNO0037合看，本轮仍未获得两边同时受益的方案。下一项设计需要同时表达精确状态依赖和消费者激活条件，再评估物化、重复计算及活动粒度的成本；仅减少组数或放宽追溯范围不足以保证收益。两项新开关均保持默认关闭，没有基于本轮运行结果调整规则、预算或选组合。
