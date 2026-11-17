# TNO0035：XiangShan shared regions 与 conditional cones 消融

**本轮最强证据指向 shared-region 处理：关闭它8/8轮更快，配对walltime均值−6.60%（中位−4.40%），独立退休指令−4.08%、分支失败−8.26%。关闭条件锥的时间CI跨零，且退休指令增加1.77%，不能同样定性。**

用户在 TNO0033/34 后授权调查原因并进行消融，要求性能测量串行。本轮在计时前固定两个独立消融，不测试组合，不调参数、预算或站点。生产生成规则没有使用运行反馈。

## 候选与控制

| 模型 | 相对 TNO0033 after 的变化 |
| --- | --- |
| full | 复用冻结 after 二进制 |
| no_shared | 只关闭 eventRegionsShared；保留 eventRegions=true、splitOversizeComputeNodes=false |
| no_cones | 显式关闭 conditional_mux_cones 与依赖的 conditional_mux_input_cache；其他选项保留 |

同一 Wolvrix 8523dc1 库、同一 pre-reg-to-mem 图、DefaultConfig guest 单核、原 simplify/reg-to-mem 和编译流程。关闭缓存会解除 cache key/result 对 covered state view 的保护，因此 no_cones 的 view 命中集合可能变化；这是机制组合效果，不是保证只有一个 C++ if 消失。shared-only 不合法（shared要求parent eventRegions=true），本轮没有构建该配置。

静态审查发现 shared pass 一旦有合并类，就会遍历其余原 compute group，按终点集合细分未移动 node。故 shared-off 对全图细分与通知维护是直接消融。空组先只做静态入边审查，不据运行结果删站点。

## 协议

两项构建并行；所有模拟器执行由一个串行驱动和 CPU96 文件锁管理。每模型先10k smoke、seed0/1各100k DiffTest轨迹，三侧逐有效字段对照；再各预热一次。固定8轮 full/no_shared/no_cones 与反序交替，每轮三个程序依次执行。每项消融除以同轮 full，形成8对；无自适应重试/删样本/追加轮次。node030 CPU96、NUMA1、ASLR关闭，完整NEMU开启，正式时间没有trace/诊断。

正式8轮结束后，另对冻结三模型各做一次串行100k PMU计数（instructions/cycles/branches/branch-misses），不并入正式walltime，不反馈生成。attach会遗漏短启动区间；单次计数只辅助解释。

构建与规则见 [policy](../../build/xs/cv32-ablation-20261116-v2/policy.json)、[builder](../../scripts/xiangshan_cv32_ablation_build.py)、[measurement](../../scripts/xiangshan_cv32_ablation_measure.py)、[PMU](../../scripts/xiangshan_cv32_ablation_pmu.py)。比较/锁/失败门/计数解析等44项测试通过。[日志](../../build/xs/cv32-ablation-20261116-v2/runner-tests.log)。

## 执行记录

v1辅助工具复制时误将include/emit目录与emit二进制一起排除，在编译阶段失败，没有生成或仿真。v2只排除顶层旧binary。失败日志保留，未根据性能修改候选。

构建、双seed功能门、8轮串行性能测量、独立PMU诊断和静态审计全部完成。

## 计时前静态证据

| compute 静态指标 | full | no_shared | no_cones |
| --- | ---: | ---: | ---: |
| 活动字检查 | 12,151 | 9,601 | 12,151 |
| 组入口检查 | 94,581 | 74,181 | 94,581 |
| 持久活动更新位置 | 519,217 | 479,876 | 519,217 |
| ELF 条件跳转 | 590,475 | 544,688 | 572,475 |
| ELF 全部指令 | 14,105,230 | 14,271,836 | 14,063,213 |
| 入口栈减法中位数 | 2,048 B | 1,144 B | 2,024 B |
| 入口栈减法最大值 | 20,728 B | 7,464 B | 20,728 B |

no_cones 保持全部组映射、117个共享译码家族、2870个状态视图、1456个复合表达式一致；缓存解除保护在本图未增加新view。因此它可以较干净地检验条件锥/缓存效果。no_shared 则改变调度，锥命中11563→11658、缓存215→224、状态视图2870→2226；必须把这些自然联动算入该消融。

[no_shared结构报告](../../build/xs/cv32-ablation-20261116-v2/offline-structure/no-shared-vs-full.md)、[no_cones结构报告](../../build/xs/cv32-ablation-20261116-v2/cone-analysis/report.json)。静态指令不是退休指令，入口栈金额不等于动态spill/访存；正式计时另列。

## 对上轮空组线索的收窄

TNO0034的group6636只识别到初始激活，不能作为反复执行的热路径例子。更准确的例子是full group753，视图内联后组体为空，而fetch pointer寄存器提交仍显式通知word56 bit16。全部613个空体中，只有39个有识别到的runtime activation writer；no_shared对应467个空体、3个runtime writer。无writer是静态源码扫描范围内的结论，不代替完整可达性证明。

按op注释得到的“简单组”包括未输出op注释的真实缓存/条件逻辑，不应把全部14,289项理解为纯搬运。直接读取状态的特殊标记减少，也可能被普通局部内联代替，不证明重新物化。实际state-copy总位置下降，但更多分散到小组，支持入口维护方向。[详细审计](../../build/xs/cv32-transfer-20261116-v3/empty-followup/README.md)。

## 八轮性能结果

三个版本均通过10k smoke和seed0/1各100k轨迹，每对99,999条DiffTest记录一致。正式24样本全部保留；均在node030 CPU96、NUMA1、关闭ASLR、单线程运行。

| 版本 | 外部wall均值 | 同轮相对full均值变化 | 配对变化中位数 | 95% bootstrap CI | 更快轮数 |
| --- | ---: | ---: | ---: | --- | ---: |
| full | 125.876503 s | — | — | — | — |
| no_shared | 117.025888 s | **−6.6022%** | **−4.3969%** | **[−11.0415%, −3.2692%]** | 8/8 |
| no_cones | 121.284428 s | −3.0627% | −1.4933% | [−8.2669%, +1.5529%] | 6/8 |

Host time结论相同：no_shared −6.6051%，CI[−11.0467%,−3.2708%]；no_cones −3.0626%，CI[−8.2681%,+1.5538%]。本轮时间波动较大，尤其full两轮约143–147秒；没有剔除。shared-off有一致方向，幅度不宜当作精确稳定常数；cone-off区间跨零，不能确认时间收益。

| 轮次 | full外部秒 | no_shared外部秒 | no_cones外部秒 |
| --- | ---: | ---: | ---: |
| 1 | 119.876867 | 114.610642 | 116.235128 |
| 2 | 147.316814 | 131.558814 | 128.627011 |
| 3 | 143.519144 | 114.729818 | 120.807295 |
| 4 | 118.790715 | 113.563040 | 124.549651 |
| 5 | 121.276752 | 121.029439 | 120.702536 |
| 6 | 119.171036 | 114.168368 | 116.735066 |
| 7 | 118.019195 | 113.420559 | 124.699323 |
| 8 | 119.041499 | 113.126421 | 117.919412 |

这是一组独立消融，不能把两项变化相加；本轮没有再跑优化前74d80cf，不能将no_shared和历史旧版时间跨轮相减以声称完全恢复。静态变化与shared-off的时间方向共同支持“共享区域处理是主要嫌疑”；仍无法将其内部的分片、缓存/view变化和机器布局分别做精确因果分摊。

[完整测量](../../build/xs/cv32-ablation-20261116-v2/measurement/summary.json)、[原始样本CSV](../../build/xs/cv32-ablation-20261116-v2/measurement/samples.csv)。

## 独立 PMU 计数

正式时间采样结束后，三个冻结模型各一次100k串行诊断，仍在node030 CPU96/NUMA1/ASLR off，完整DiffTest和功能签名一致。四事件运行比例均通过99%门，无新增候选。perf附着在进程创建后，遗漏短启动区间；计数含模型、harness及NEMU，不是纯eval，单次采样无CI。

| 每guest cycle | full | no_shared | no_cones |
| --- | ---: | ---: | ---: |
| instructions:u | 3,925,948.295 | 3,765,676.520 | 3,995,401.297 |
| cycles:u | 4,179,004.794 | 3,958,668.934 | 4,121,365.845 |
| branches:u | 370,100.286 | 359,410.891 | 366,456.539 |
| branch-misses:u | 44,646.644 | 40,957.166 | 42,249.099 |

相对full：no_shared退休指令−4.0824%、cycles−5.2724%、branches−2.8882%、branch-misses−8.2637%。no_cones退休指令**+1.7691%**、cycles−1.3793%、branches−0.9845%、branch-misses−5.3700%。

关闭shared虽使静态机器指令总量略增，动态退休指令却减少，说明静态代码大小不是成本代理；其调度／激活／布局和其他优化联动改变了实际执行工作。关闭cones则动态算得更多、分支失败更少，体现经典的计算与控制流取舍，不能根据静态跳转数量判定净收益。

[PMU完整结果](../../build/xs/cv32-ablation-20261116-v2/pmu/summary.json)。

## 原因结论与下一步

目前应优先解决shared-region处理的成本模型与组合方式：它为保证无环而按终点集合细分所有剩余混合组，产生大量小入口、更多活动扫描与通知，并改变局部生命周期。no_shared消融撤掉大部分入口/栈增长，8轮方向一致，动态指令和分支失败也下降；这是比单纯看源码更强的因果证据。

但这是关闭整个shared机制的总效应，连带改变了条件锥、缓存和视图资格，不能声称已把6.60%全部归给某一行分片逻辑。后续可研究在合并前同时计算分片、入口、通知的静态成本；或仅细分维持本次合并无环所需的部分，而不是全图剩余混合组。必须先证明调度无环及激活完整性，不从测量中挑站点或阈值。本轮没有实施这些新优化，也没有按结果追加组合实验。

条件锥不宜一刀切关闭：它确实减少部分动态算术，但增加控制流。本轮关闭它的CI跨零，说明其净成本仍不够确定。空活动组清理是明确的小型组合缺口，但规模远不足解释主要差距，应与上述主线分开。

## 独立审计与波动限制

24样本、5,813个线程/CPU快照、592个NUMA快照全部通过；CPU288空闲率99.9586%–100%。full两轮偏慢时CPU驻留仍约99.988%/99.949%，非自愿切换不异常；round02较多自愿切换仅对应约0.073秒监控区间非CPU时间，解释不了二十多秒增幅。缺少同期频率/微架构计数，原因未定，不将其武断归为抢占或删除。独立PMU在另一时间运行，不能用它倒推这两个样本的慢因。

[独立复核](../../build/xs/cv32-ablation-20261116-v2/independent-review/review.json)、[构建命令审计](../../build/xs/cv32-ablation-20261116-v2/build-audit.json)。44项比较/锁/解析回归通过，所有生成源码、binary和输入身份测量前后校验。生产Wolvrix、XiangShan、DiffTest工作树没有修改。

复现使用新目录，构建可并行，测量和PMU各由CPU96锁串行管理：

```sh
python3 scripts/xiangshan_cv32_ablation_build.py prepare --output build/xs/ablation-reproduce
# 两个build必须在node030执行
python3 scripts/xiangshan_cv32_ablation_build.py no_shared --output build/xs/ablation-reproduce
python3 scripts/xiangshan_cv32_ablation_build.py no_cones --output build/xs/ablation-reproduce
python3 scripts/xiangshan_cv32_ablation_measure.py --source build/xs/ablation-reproduce --output build/xs/ablation-reproduce/measurement
python3 scripts/xiangshan_cv32_ablation_pmu.py --source build/xs/ablation-reproduce --measurement build/xs/ablation-reproduce/measurement --output build/xs/ablation-reproduce/pmu
```
