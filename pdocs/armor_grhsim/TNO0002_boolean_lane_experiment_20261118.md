# TNO0002：XiangShan 同一活动区域内的一位节点压缩

**本轮在机器码检查结束。** 按 ARMOR 的方法将独立的一位计算沿多级数据流打成 `uint64_t`，305 个包通过静态估算，但同一配置下实际受影响的 compute 函数净增 **6,459 条静态指令、24,024 B、127 个条件跳转**。这触发了试验前约定的停止条件。记录的是代码膨胀，整机 walltime 未测。实验开关 `bool_lane_pack` 默认关闭。[机器码逐函数比较](../../build/armor-lane-v1/frozen/machine/report.json) · [功能文档](../../wolvrix/docs/emit/grhsim-bool-lane-pack.md)

## 冻结范围和基线测量

当前工作区从父仓 `8f5bbdc` 和 Wolvrix `59e0f1e` 开始。A 是另一工作区 CV32 系列 TNO0049 的真实候选 ELF，沿用 connected、shared-arm、快照数组配置。B 使用同一份图、生成选项、Clang 23.1.2、harness 和编译命令，只开启这项实验。用新库显式关闭选项重放，XS 的 140 个 C++／header／Makefile 与 A 逐文件相同，CV32 的 21 个也相同。审计 TSV 单独写入输出目录。CV32 开启后仍为同样的 21 个文件，独立编译后 `.text/.rodata/.data` 哈希均一致。[原配置与工具链身份](../../build/armor-lane-v1/frozen/inputs.json) · [XS 关闭重放](../../build/armor-lane-v1/frozen/xs-off/sources.json) · [CV32 源文件](../../build/armor-lane-v1/frozen/cv/sources.json) · [CV32 ELF 节](../../build/armor-lane-v1/frozen/cv/sections.json)

A 的两次独立诊断使用 node030 CPU96／NUMA1、ASLR off、旧工作区共用锁、100k CoreMark 窗口和完整 DiffTest/NEMU。两次均达到 PC `0x80000c1a`、250,838 条 guest 指令、100,001 个 guest cycles；单线程、放置与 locality 检查通过。第一次进程附着采集四项用户态事件，running fraction 均为 99%，以下是未缩放的原始计数除以 guest cycles。第二次独立采样前端供给空槽事件。样本归属基于 ELF 符号，包含剩余初始化、运行框架和参考模型。[PMU 原值、签名和采样分类](../../build/armor-lane-v1/pmu-A/report.json)

| A 端指标 | 每 guest cycle |
| --- | ---: |
| host cycles | 4,066,429 |
| 退休指令 | 3,644,626 |
| 无前端操作可分派的槽位 | 18,345,957 |
| L1I tag miss 事件 | 734,798 |

在 184,975 个前端事件样本中，compute 有 153,320 个（82.89%），commit 有 30,290 个（16.38%），其余为其他模型函数、harness、库或 NEMU。它支持优先调查 compute 指令供给，但没有把这些事件归因到 305 个包。最初 `perf script` 在未请求 IP 时输出空符号行，随后从同一份 `perf.data` 以 `ip,sym,dso` 重新解码，全部样本保留。

## 调度后的机会与成本

审计在实际 emitter 完成 supernode 内排序、条件锥形成、存储分配和现有 lowering 选择后进行。每个区域输出 op/SSA 身份、当前 arm、效应分隔、宽度、读写关系、物理槽、符号和源码位置。改变 pack 开关共用同一 C++ 规划器。离线重放的首成员、lane 数、层数与覆盖大小逐包核对生成 C++，另查成员表去重。以下分母包含调度产生的克隆，不能和论文评估前一轮的 171.49 万个调度前操作直接相减。[XS 调度审计](../../build/armor-lane-v1/frozen/detail-xs/summary.json) · [CV32 调度审计](../../build/armor-lane-v1/frozen/detail-cv/summary.json)

| 调度后筛选口径 | XiangShan | CV32 |
| --- | ---: | ---: |
| 一位输入／输出 AND、OR、XOR、NOT | 1,589,304 | 489 |
| 已有 lowering、别名、事件或公开结果等保护条件排除 | 1,182 | 10 |
| 同域同层缺同类伙伴的根 | 203,791 | 94 |
| 同域同层具有同类伙伴，可尝试组成平行根 | 1,384,331 | 385 |
| 最终 pack 数 | 305 | 0 |
| 最终唯一覆盖的位运算 | 15,903（1.00%） | 0 |

XS 的 203,791 个单根进一步分为同域但局部依赖深度不同 187,503、同 epoch 不同 arm 1,651、同 arm 不同 epoch 632、整组唯一操作类型 14,005。一个 op 不能作为并行根时，仍可能作为另一个包的内部节点。规划器还记录了 179,782 次快照／求值位置拒绝和 477,039 次成本非正的尝试；试探大小和路径会重叠，这两个数不能作为互斥操作数从表中扣减。

305 个包包含 2,099 个输出 lane。3 个包以归约结束，其余 302 个包有 **2,067 个标量出口**。累计需逐位装入 **3,624 个输入位**，另有 **1,878 个广播字**。按规划器的标量表达式操作估算，原式 15,932，候选 14,299，预计节省 1,633。深度为 2、5、6、7、8、9 的包分别为 3、140、11、44、1、106。只有 2 个包由可用的同源位置和扁平符号对齐产生，其余使用局部结构与真实边；冻结图已扁平化，未重建论文 FIRRTL 的模块定义到实例映射。[规划器](../../wolvrix/lib/emit/grhsim_bool_lane_pack.hpp) · [逐包成本清单示例](../../build/armor-lane-v1/frozen/detail-xs/grhsim_SimTop_sched_62.packs.tsv)

## C++ 和 ELF

XS 137 个模型 C++ 中 14 个 compute 翻译单元有变化，header、eval、commit 源和其余单元逐字一致。下表汇总对应 17 个目标函数符号（含相应辅助函数）。RSP 访存位置可能包含局部量和保存恢复，不能全部归为 spill。[发生变化的源文件](../../build/armor-lane-v1/frozen/xs/changed-sources.json) · [ELF 数值与函数明细](../../build/armor-lane-v1/frozen/machine/report.json)

| 静态指标 | A | B | B − A |
| --- | ---: | ---: | ---: |
| 受影响 compute 代码字节 | 15,998,566 | 16,022,590 | +24,024 |
| 指令 | 3,033,999 | 3,040,458 | +6,459 |
| 条件跳转 | 143,852 | 143,979 | +127 |
| RSP 相对访存 | 292,030 | 291,667 | −363 |
| 调用 | 4,459 | 4,459 | 0 |
| 完整 ELF 的 `.text` 字节 | 88,856,754 | 88,880,770 | +24,016 |

batch 62 主函数有 115 个包，净增 6,138 条指令和 27,426 B；batch 55 主函数却少 204 条指令和 3,018 B，说明改动对不同函数的影响并不一致。batch 62 第一处 8-lane 计算需要从分散的 bool 槽收集输入，并广播若干标量。用相同 header 的字段偏移绑定其输出字节槽 192895，确认两个 ELF 各自只有一个对应的八字节向量写。A 已用向量谓词构造并存储这些结果，B 在对应写入前出现 `kshiftlb/kshiftrb/korb` 等重排。该窗口说明局部 IR 费用为何会低估宿主代价，但无法把整个函数的增长都归于这一包。先前的 probeQueue 作为独立的原编译器向量化对照保留。[目标字段与地址](../../build/armor-lane-v1/frozen/machine/witness.json) · [A 指令窗口](../../build/armor-lane-v1/frozen/machine/A-batch62-store.s) · [B 指令窗口](../../build/armor-lane-v1/frozen/machine/B-batch62-store.s) · [probeQueue 对照](../../build/armor-paper-review/probequeue.s)

## 功能与决策范围

专项 CTest 的生成模型与独立逐 lane 参考在 O0/O3 ASan 和 UBSan 下运行，覆盖 1／2／63／64／65 路、部分字 NOT、公开标量和跨区域消费者、正常时钟／异步复位和重复 eval；另核对环境和 attribute，及规划器的水平归约、计数与跨分支回退。父仓保留基线 PMU 与候选机器码，故障排查未按性能结果更改生成规则。另一个端到端 fixture 让第 0 路输入同时流向分支外观察端口，在随选择信号切换的 105-op 真分支内生成 8 路打包和 popcount，逐 lane 对比两种选择和重复 eval。只读 execution plan 复用同一规划器，其逐组包数在 fixture 上与生成代码逐项汇总一致。[专项测试](../../wolvrix/tests/emit/test_emit_grhsim_bool_lane_pack.cpp) · [三项兼容回归](../../build/armor-lane-v1/final-ctest.log) · [最终源码回归](../../build/armor-lane-v1/accepted-ctest.log)

机器码门在功能长测和八对计时之前。因此 B 没有新增 XS 双 seed DiffTest、CV32 CoreMark 总线／331 项行为计数、整机配对 walltime 或 B 端 PMU。局部语义回归和 CV32 机器码一致性分别报告。对本轮临时表示，证据支持结束；对能贯通持久布局、减少标量出口的其他算法，本轮数据尚不能给出结论。

## 复核入口

`scripts/armor_lane_replay.py` 在本工作区构建的库上重放旧 manifest。`prepare` 冻结库、驱动、图和工具链；`xs`／`cv` 及 `--candidate` 生成四组输出。`scripts/armor_lane_audit.cpp` 调用同一个 C++ 规划器，`scripts/armor_lane_census.py` 对每个 sidecar 去重、核对生成标记并汇总结果。`scripts/armor_lane_machine.py` 的 `build` 使用 node030 的原编译参数，`analyze` 可在本地读 ELF。原始汇总、源码身份和反汇编位于本工作区的 `build/armor-lane-v1/`。PMU 使用 `scripts/armor_frontend_pmu.py` 独立运行。

整机 ELF 冻结后补充了只读 execution-plan 的四个特征字段和专项测试。对比冻结快照，最终生成器差异仅含排版和该分析分支。重复启动验证曾因共用 fixture 目录而删除另一次编译中的 header，现改为为每次调用原子分配独立的产物目录，最终回归重新执行。结果与文件身份见[核验记录](../../build/armor-lane-v1/validation.json)。
