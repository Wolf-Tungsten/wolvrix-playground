# TNO0048：扩大既有 mux 分支中的共享计算闭包

承接 TNO0046/0047，主线转为扩大既有条件执行覆盖。本轮固定 TNO0044 connected-shared 为基线，保留其调度、状态视图、缓存及条件锥；不叠加上一轮 aligned-array 实验。新增规则在测量前冻结，只读取图、调度和 emitter 所有权，不使用运行反馈选站点、改阈值或产生下一候选。

## 实现与静态证明

新增默认关闭的 `conditional_mux_shared_arm`。旧规则先选定所有 root 和原始 arm；新规则仅扩展非空、无持久输入/变化缓存的 arm，既不新增 root，也不建立新缓存。例子为 `a=f(x); b=g(a); c=h(a); mux(sel,b^c,other)`：原规则因为 `a` 有两次使用而把它留在分支外；新规则证明两次使用都在同一分支后，可将 `a` 及其合法祖先移入该分支，各结果仍只生成一次。

先向后建立候选集合，再按反向拓扑顺序删除有分支外使用的新成员及其祖先。selector、另一分支、公开观察值、跨区域、持久/判变值、存储 alias、状态视图和其他 lowering 所有权均形成边界。新增操作仅限 scalar，沿用原 scalar renderer 的截断、有符号移位及越界规则。原 region 的纯度、状态快照及生产者顺序证明继续生效；不跨 commit。扩展总量超过原有 256-op 上限时，整个扩展回退，不做基于运行频率的部分选择。

`conditional_mux_shared_arm_audit` 在优化关闭时仅输出审计注释；删除这些注释后必须逐文件精确复现旧候选。审计与开启版的逐 root/arm 操作成员必须完全相同。执行计划报告新增操作静态上限，继续将其标为 selector-dependent work。[功能文档](../../wolvrix/docs/emit/grhsim-shared-arm-closures.md)

## 回归与模型身份

专项 `emit-grhsim-shared-arm` 已通过：同分支共享、重复 operand、外部/另一分支/selector 使用、跨区域与公开观察、缓存和大小回退；17/32/64 位独立状态 oracle 在 O0 和 O3 ASan/UBSan 下验证双时钟、异步复位、掩码写、符号与超大移位、输入单独变化、重复 eval 和重新初始化。默认关闭、环境变量/attribute 优先级、audit/off 源码身份及 audit/on 成员一致也通过。

初次 fixture 把复位事件信号混入普通计算区域，旧规则就拒绝了整个区域；这导致预期命中断言失败。将复位包装移到独立区域后，原 cone 和新扩展均被实际覆盖。此修正只改测试，没有改生成规则。

既有 conditional-mux、conditional-wide、execution-plan 三项通过，合计 4 项 CTest。19 项 Python 回归覆盖审计身份、成员/根漂移、重复成员、缓存回退及统计/指令分析工具。日志在 [CV32 构建目录](../../build/cv32e40p/)。

CV32 保持 12 个 root，扩展其中 6 个 root 的 8 个 arm。原 601 个 arm 操作增加 163，涉及 56 个多用结果；原始向后可达新增量 1148，因外部使用剪除 872，另 1 个 oversized 扩展回退、1 个缓存 arm 回退。这些统计是静态计数，不能解释为执行次数。

CV32 三后端 smoke、完整 CoreMark 和逐周期总线 trace 一致。候选与 connected 旧诊断的 331 项计数完全一致（smoke/CoreMark 分别核对），包含区域、函数、固定点轮数、变化检查、cache 和原有 mux 分支。按冻结分支计数换算，新增条件化每周期可跳过约 85.0162 个 IR 操作；这不是退休机器指令的节省量。[结构门](../../build/cv32e40p/shared-arm-v1/structure.json)、[计数门](../../build/cv32e40p/shared-arm-v1/count-gate.json)

XiangShan 静态门随后通过：11540 个旧 root、12397 个非空原 arm 不变；2291 个 root 的2354个 arm 新增33596个操作，涉及10136个多用结果。原459363个条件化操作变为492959，增加7.3136%。向后初筛87721个新增候选，44914个因分支外使用剪除；18个闭包超过上限回退，188个缓存root的212个非空arm回退。新增量分布为1–4操作849个arm、5–16操作648个、17–64操作838个、大于64操作19个。区域、活动更新、判变值、状态视图、缓存接口及header/eval保持一致。audit去注释后精确复现旧模型。[XS结构门](../../build/xs/shared-arm-20261117-v1/structure.json)、[静态汇总](../../build/xs/shared-arm-20261117-v1/census-summary.json)

## 固定评价协议

两边均用冻结 connected 候选作对照。XS 先重放同一份 pre-reg-to-mem JSON，完成 audit/source 身份及静态覆盖检查，再决定是否值得进入整机编译；这一门不读取速度或运行热度。正式评价沿用探索阶段 3 对，不追加组合或按速度重试。XS 为两个 seed 的 100k 周期 DiffTest 窗口、10k smoke、预热后 AB/BA 三对；CV32 为基线/候选/同 RTL Verilator 三轮完整 CoreMark。XS 窗口不称完整 CoreMark 完成。

性能计时均在自身构建及回归结束后，使用 node030 CPU96、NUMA1、单线程、ASLR off、同一个测量锁，串行执行。预先声明 XS 每模型各一次独立 PMU，放在正式计时后，只评价冻结模型。[驱动](../../scripts/shared_arm_compare.py)、[XS policy](../../build/xs/shared-arm-20261117-v1/policy.json)

## C++ 与 ELF 证据

CV32 原/新 compute 静态指令为 10565/10558，条件跳转 153/153，总 code bytes 49875/50049。commit/eval 的统计保持不变。batch1 栈帧分配从 696 降到 680 字节，batch2 仍为 2392 字节。源分支数不增加，也不意味着机器码大小或所有函数指标都会变小；本轮主要改变原有分支中的计算范围。

按静态新增操作最多选择 root14263 true arm 作例子：它增加49个操作，局部声明由5个变为18个。新增声明的旧/新位置和 DWARF 指令归因已保存；ELF 内嵌源码 MD5 全部匹配。该函数存在间接跳转，分析没有假装完成完整 CFG 支配证明，也没有把源码行指令数当作独立退休指令收益。[ELF 分析](../../build/cv32e40p/shared-arm-v1/machine-analysis.json)、[移动位置](../../build/cv32e40p/shared-arm-v1/local-movement-evidence.json)

此例也暴露源码统计的上限：原版14个后来移入的局部声明，共47条有DWARF归因的指令，已经全部落在旧guard `0x7792`与其跳转目标`0x7b53`之间；开启版对应70条落在`0x77a3..0x7c37`之间。说明编译器早已将不少准备工作移进相应代码范围，不能把49个新增IR操作或源码位置变化全部算作新获得的动态节省。这里仅陈述地址位置与归因，存在间接跳转，未证明完整路径排他性。

XiangShan 扩展落在58个源文件、1419个区域，58个compute主函数的机器形态发生变化；commit/eval统计不变。

| XS compute ELF静态指标 | connected基线 | shared-arm候选 | 差额 |
| --- | ---: | ---: | ---: |
| 指令 | 13,755,365 | 13,753,118 | −2247（−0.01634%） |
| 条件跳转 | 563,299 | 563,338 | +39 |
| 调用 | 22,623 | 22,623 | 0 |
| 带内存操作数指令，不含lea/nop | 5,480,957 | 5,478,910 | −2047 |
| RSP相对访存位置 | 1,129,226 | 1,126,608 | −2618 |

静态指令并非各函数都下降：batch58少1373条，batch43多526条，batch42多336条。7个函数入口栈分配增大、9个减小；甚至batch43/42栈分配减小但指令增多。因此不能用“闭包变大”或“栈帧变小”单独预测walltime。[XS ELF与源码证据](../../build/xs/shared-arm-20261117-v1/machine-analysis.json)

增加7.31%是相对于原有条件锥的459363个操作；相对于调度的6926383个compute-node操作，新增33596个仅约0.485%。按静态新增量排序的最大四个扩展均为94操作，附近寄存器路径属于Vfcvt向量转换逻辑。这说明覆盖面积仍需结合实际活动理解，不能因静态命中较大就宣称CoreMark热路径节省同样比例；本轮没有按该运行热度筛选或禁用站点。XS release ELF没有DWARF源码行映射，本轮只报告确定的函数级形态及冻结源位置。

XS两侧10k smoke、两个seed的100k周期DiffTest均通过，两个seed各99,999条记录完全一致；终点PC `0x80000c1a`、instrCnt250838、cycleCnt99995、guest cycles100001。没有关闭DiffTest或放宽中间线比较。

## 测量结果

两侧各三对均已完成，所有样本保留，没有性能重试或调整候选。

| 对照 | 基线wall均值 | 候选wall均值 | 配对平均变化 | bootstrap 95% CI |
| --- | ---: | ---: | ---: | --- |
| XS connected→shared-arm | 112.922344 s | 112.516269 s | **−0.3595%** | **[−0.4412%, −0.2288%]** |
| CV32 connected→shared-arm | 2.656896 s | 2.643430 s | **−0.5057%** | **[−0.7699%, −0.3409%]** |
| CV32 同RTL Verilator→shared-arm | 2.747503 s | 2.643430 s | −3.7872% | [−4.2284%, −3.0599%] |

| XS对次 | 顺序 | connected wall秒 | shared-arm wall秒 | 候选变化 |
| --- | --- | ---: | ---: | ---: |
| 0 | 基线→候选 | 112.932559 | 112.434279 | −0.4412% |
| 1 | 候选→基线 | 113.051092 | 112.589251 | −0.4085% |
| 2 | 基线→候选 | 112.783380 | 112.525277 | −0.2288% |

两种设计相对各自connected基线均为3/3对更快；这是固定小样本和指定负载下的小幅收益，不是跨负载稳定性保证。XS仅测100k周期窗口；CV32完成CoreMark。没有把本轮XS与历史pre-CV32绝对时间跨轮相除，本轮只与同轮connected比较。

XS独立审计已通过：14次运行、2731个线程/CPU快照、278个原始NUMA快照，正式样本CPU288空闲率均100%。CV32独立审计检查9个正式样本、18个首尾NUMA/放置快照，并重算全部统计。[XS统计](../../build/xs/shared-arm-20261117-v1/report.json)、[XS原始轮次](../../build/xs/shared-arm-20261117-v1/measurement/rounds.json)、[XS独立审计](../../build/xs/shared-arm-20261117-v1/independent-review/review.json)、[CV32统计](../../build/cv32e40p/shared-arm-v1/summary.json)、[CV32独立审计](../../build/cv32e40p/shared-arm-v1/independent-review.json)

## PMU与结论

独立PMU按原定协议在两边计时结束后，每个XS模型串行运行一次；功能签名、CPU/NUMA和冻结身份均通过。采样为启动后attach，`--no-scale`，包含剩余初始化、model、harness及NEMU，并非纯eval。原始每guest cycle计数如下：

| PMU原始指标 | connected | shared-arm | 变化 |
| --- | ---: | ---: | ---: |
| instructions:u | 3,658,044.19 | 3,644,911.77 | −0.3590% |
| cycles:u | 4,042,661.92 | 4,083,634.72 | +1.0135% |
| branches:u | 364,964.16 | 364,000.42 | −0.2641% |
| branch-misses:u | 43,061.15 | 42,913.31 | −0.3433% |

两边running percent分别100%/99%。原始指令差小于此覆盖率差异，因此**不能据此宣称精确减少0.359%的退休指令，也不能把它当作walltime下降的独立因果证明**。同样，单次PMU的cycles增加不能替代正式三对结果。没有按此诊断追加样本、调整选点或产生新候选。[PMU原始总结](../../build/xs/shared-arm-20261117-v1/pmu/summary.json)、[计数与身份复核](../../build/xs/shared-arm-20261117-v1/pmu-review.json)

本轮解决了“同分支共享节点使私有锥提前停止”的通用结构缺口，并在两种设计的固定三对中均观察到小幅收益。收益规模受全设计覆盖率、已存在的编译器下沉及寄存器分配变化限制。规则继续默认关闭；保留该固定候选和完整正负证据，生产生成策略与测量前冻结源码一致。本轮没有追加组合搜索，也没有移动既有connected基线。
