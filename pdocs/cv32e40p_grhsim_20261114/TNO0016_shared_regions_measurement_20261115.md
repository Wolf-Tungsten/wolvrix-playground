# TNO0016：共享组合区域的实现、测量与未获收益原因

本轮实现了TNO0015提出的共享/多终点组合区域，并完成同一归一化RTL上的功能门和一次8轮对照。**静态边界明显减少，但未获得稳定性能收益。** 共享区域版相对保留的单终点事件区域版，walltime变化为 **+0.547%**，95%配对bootstrap CI **[−0.134%, +1.117%]**。新扩展保持默认关闭，不替换保留配置。

原因已分解到生成代码和逐值执行次数：省去的边界大部分原本已有稀疏译码缓存；合并又破坏了部分缓存的前提，并提高了其它逻辑的执行频率。调度边界数减少不能直接转成动态工作量减少。没有继续扩大区域上限、扫描参数或根据性能挑选子集。

## 实现与语义边界

新增 `ActivityScheduleOptions::eventRegionsShared`、CLI `-event-regions-shared true` 和Python `event_regions_shared=True`。它要求原 `eventRegions` 开启，并在原单终点区域构造之后执行。两个选项全局默认均为false；单终点区域是当前保留的实验配置。

- 对完整compute node计算下游终点集合。终点包括commit的数据/使能/地址消费者、公共输出，以及受保护的compute组。
- memory/latch、事件产生、effect、非Logic结果和reg-to-mem intent所在的**原组整体**保留。其上游纯逻辑把该组视为独立终点，不能越过该组；不能因为地址最终流入memory就禁止整个地址组合锥合并。
- 只合并跨至少两个原组、终点集合相同且包含多个终点的完整node。固定上限为32个终点、8,192个op，不使用信号名、profile或运行结果选择。
- 剩余纯组按终点集合细分，避免混合残片使收缩后的组图产生环。新区域按首次使用排列，未改变的组保持原成员与顺序。
- 重建严格DAG、fanout和state-read activation，检查op多重集合完全不变。commit成员与顺序不变；memory写入仍按原机制重新激活读取。区域由输入/状态变化触发，不按commit时钟门控。

详细契约见[功能文档](../../wolvrix/docs/transform/activity-shared-event-regions.md)。CV32的6,744个scheduled op全部保留；原两个单终点区域从组30/31映射到27/28，原commit组32–35映射到35–38，成员及顺序逐项一致，见[membership-check](../../build/cv32e40p/shared-regions-v3/membership-check.json)。

实现过程中的两个早期目录只用于结构检查：v1按整个原组分类，形成0个共享区域；v2允许细分纯组，但仍把屏障向全部上游传播，只形成7-op区域，边界没有下降。这两版均未做整机性能测量。静态诊断发现374个原checked value到达memory read，说明屏障传播过宽。最终v3保留屏障原组、以它为终点，经过memory快照回归后才进入本轮唯一正式对照。[v1诊断](../../build/cv32e40p/shared-regions-v1/whole-group-diagnosis.json)、[v2诊断](../../build/cv32e40p/shared-regions-v2/barrier-diagnosis.json)。

## 冻结输入与功能验证

本轮不讨论SV转V的影响。两侧GrhSIM与Verilator复用同一归一化RTL、CoreMark RV32IM镜像和harness。Clang23.1.2，`-std=c++20 -O3 -march=native -DNDEBUG -gline-tables-only`，无波形与计数插桩。`local_equality_decode`保持关闭。

| 后端 | binary SHA256 |
| --- | --- |
| 保留的单终点事件区域版 | `792ffa67830d766fd5418bd967e41615090141f8faa7c4ac58c0d3fa2438ee65` |
| 新共享区域版 | `240b648b6d61559d850518d73117de29c06680c6033a64e56b9f2aceb859fa9f` |
| 归一化Verilator | `5396106991546a7aa0da975a44e9b92c21988bf6a4d60d4755bdafa370be7614` |

输入图SHA为`e1ccc2928b055e022eb5a7a6637265af19a762e8fdf964ad26ee5833b5f9191b`。新工具关闭共享区域选项后，逐文件复现旧事件区域版源码；打开后normalized graph仍完全相同。源码快照、native工具和库、harness、镜像、编译选项和测量前假设见[build.json](../../build/cv32e40p/shared-regions-v3/build.json)、[hypothesis.json](../../build/cv32e40p/shared-regions-v3/hypothesis.json)。

三侧smoke均为253周期；完整CoreMark均为3,376,065周期，退出码、UART及预期CRC一致，完整bus trace SHA均为`ed2b490886767aa74524a6dd15e708e8f2b231bc3886814af0ba4d1919b3e098`。独立计数模型也通过相同trace。见[功能门](../../build/cv32e40p/shared-regions-v3/functional.json)。

扩展后的独立oracle涵盖共享纯锥同时供给公共输出和两个时钟域、透明时钟门、异步复位、时钟保持时的输入变化、交叉寄存器旧状态、masked memory write及依赖旧memory的寄存器更新。O0、O3与ASan/UBSan均通过。额外检查保护组原序、8,300-op超限回退、33公共输出的终点溢出、compute node拆分拒绝及非法/缺失父选项。

## 静态变化与单次8轮测量

形成6个共享区域，覆盖24个原组中的489个node、1,533个op；3个混合纯组发生细分。以下区分调度边界值、生成器的变化检测值和所有中间槽，三者口径不同。

| 静态指标 | 保留版 | 共享区域版 |
| --- | ---: | ---: |
| 调度跨组boundary value | 698 | 494 |
| 带变化检测的不同值 | 413 | 209 |
| 变化检测源码位置 | 791 | 209 |
| 中间scalar槽总数 | 704 | 499 |
| compute / commit supernode | 32 / 4 | 35 / 4 |
| compute batch函数 | 4 | 4 |
| scheduler C++ bytes | 1,309,489 | 1,010,303 |

口径更正：日志中的local-value live steps为104,055→134,294，比较的是**同一批新共享区域在首次使用重排前后**，不属于上表的保留版/候选模型对照。当前排序记录这两个值后仍无条件采用新顺序，静态代理指标上升29.06%；它不是物理寄存器数量或实测spill，不能据此量化walltime损失。该设计遗漏的代码审查见[TNO0020](./TNO0020_unsuccessful_attempts_review_20261115.md)。结构明细见[structure.json](../../build/cv32e40p/shared-regions-v3/structure.json)、[emit.log](../../build/cv32e40p/shared-regions-v3/logs/emit.log)。

正式运行固定node030 CPU96、单线程、NUMA1、ASLR关闭。三侧各一次预热，然后8轮ABC/CBA，完整进程重启数固定为1。24个样本均一次通过功能与既有placement/locality门，没有重试或按快慢删样本；CPU288 sibling在每个样本区间记录为100% idle。

| 后端 | 外部wall均值 | simulation loop均值 | 模型init均值 |
| --- | ---: | ---: | ---: |
| 保留版 | 3.752657 s | 3.718736 s | 7.202 ms |
| 共享区域版 | 3.773016 s | 3.739935 s | 7.041 ms |
| 归一化Verilator | 3.293311 s | 3.257191 s | 10.998 ms |

- 共享/保留wall倍率：**1.005467**，95% CI **[0.998658, 1.011173]**；2轮更快、6轮更慢，无法认定稳定收益或稳定回退。
- 共享/保留loop倍率：1.005744，CI [0.998790, 1.011524]。差异主要在持续仿真，启动成本没有掩盖收益。
- 共享/Verilator wall倍率：1.145671，CI [1.141510, 1.149711]。
- 同轮保留/Verilator wall倍率：**1.139496**，CI [1.134630, 1.144717]。

倍率是逐轮比值的均值，不是两个总均值之比。见[report](../../build/cv32e40p/shared-regions-v3/report.json)、[逐轮CSV](../../build/cv32e40p/shared-regions-v3/pairs.csv)、[测量策略](../../build/cv32e40p/shared-regions-v3/measurement-policy.json)。

构建单独记录：共享区域模型发射2.111 s，Clang并行编译20.215 s，harness链接1.200 s；不计入仿真walltime，且不以这一次构建耗时推断编译性能收益。

## 边界减半为什么没有减少动态工作

逐值counter记录的是`grhsim_changed_*`的**变化检测**，不包括已经局部化的逻辑Eq，也不等于退休比较指令数。完整CoreMark计数给出：

| 每guest cycle | 保留版 | 共享区域版 |
| --- | ---: | ---: |
| scalar变化检测 | 185.655056 | 185.112525 |
| 检测结果实际变化 | 37.115703 | 30.917438 |
| low / high fixed-point轮数 | 1 / 2 | 1 / 2 |

净少204个checked value，实际检测却只下降 **0.292%**。精确分解如下，所有数均为每guest cycle：

| 变化来源 | 检测次数变化 |
| --- | ---: |
| 移除207个旧边界 | −30.538274 |
| 新增3个边界 | +2.411415 |
| 保留值中19个Eq失去共享缓存 | +17.857169 |
| 其余保留值执行频率变化 | +9.727158 |
| 合计 | **−0.542531** |

207个消失的边界中，**170个原本位于共享译码缓存**，这些值合计只执行 **0.097157次/周期**的变化检测。它们由初始化/清旧地址/置新地址路径更新，不能按170次/周期估算收益；局部化后，逻辑谓词仍需供消费者使用。

19个保留Eq失去缓存的具体原因也可在代码中核验：

1. 18个opcode判定共享源`_val_176`。源从独立槽变为区域内局部值，违反旧shared-equality规则的materialized-source条件。以`core$_07936_`为例，原来位于[稀疏更新](../../build/cv32e40p/event-regions-v3/grhsim_event_regions/grhsim_Cv32Bench_sched_0.cpp:872)，变化检测仅0.005514次/周期；新[直接计算](../../build/cv32e40p/shared-regions-v3/grhsim_shared_regions/grhsim_Cv32Bench_sched_1.cpp:942)为0.999956次/周期。
2. 另1个判定共享CSR源`_val_134`。该源的大量其它结果已经局部化，原规则要求连续的至少16个独立bool结果槽；剩余存储结果不再组成可缓存家族。生成器中已没有原shared-equality更新块。
3. 原组22部分控制结果只执行约0.220473次/周期，合并后接近1次。例如`core$_07272_`和`if_stage_i.branch_req`；它们所在新区域被其它输入/状态变化一起激活。固定点轮数相同，所以这里是**区域粒度导致额外计算**，不是fixed-point发散。

源`_val_134`的新区域包含214个局部Eq，组执行0.999956次/周期；原来已有23个局部Eq执行0.789520次/周期，其余较大部分有稀疏更新保护。另一个源`_val_6162`的171个局部Eq及4,810-op单终点区域原序保持不变。这里的“Eq个数×区域次数”只能说明潜在逻辑工作，不用于替代Clang优化后的指令测量。

[work-decomposition.json](../../build/cv32e40p/shared-regions-v3/work-decomposition.json)保存逐值增减、旧新组号、局部译码家族及恒等式检查。分析器验证两份normalized graph的SHA、周期、value ID/名称/位宽/类型和aggregate总和，不把不同图中的同号value误配。

## 二进制与PMU证据的边界

三侧各一次独立`perf stat`，并对共享区域版采样一次；这些不加入配对统计。计数模型也不参与正式性能数据。

| 每guest cycle的Host工作 | 保留版 | 共享区域版 | Verilator |
| --- | ---: | ---: | ---: |
| retired instructions | 11,130.083 | 11,257.492 | 9,799.122 |
| branches | 471.673 | 446.999 | 568.442 |
| branch misses | 1.127 | 1.227 | 0.883 |
| Host cycles | 3,353.387 | 3,325.788 | 2,932.929 |

指令量增加 **1.145%**，分支减少5.23%，净动态工作未随边界数下降。单次诊断的Host cycles略低，不用于推翻8轮配对“没有稳定收益”的结论，也不能据此给每项结构变化分配耗时比例。

| 所选eval/compute/commit函数静态总量 | 保留版 | 共享区域版 |
| --- | ---: | ---: |
| machine code bytes | 75,828 | 61,611 |
| instructions | 15,404 | 12,718 |
| 含内存操作数的指令 | 6,519 | 5,264 |
| 含栈操作数的指令 | 2,372 | 2,354 |
| compare/test | 1,775 | 1,789 |
| cmov/setcc | 1,497 | 1,568 |

源码和机器码缩小包括稀疏decoder的初始化、清旧/置新路径消失；这些路径原本不是每周期全跑。因而静态指令减少与退休指令增加可以同时发生。栈操作数不是spill计数，不能宣称栈访问贡献了确定比例的耗时。

新profile主要落在batch2（64.90%）、batch1（16.09%）和commit（8.25%）。batch2含原4,810-op区域及新增区域；不能把它的38,548 bytes直接与旧batch3的36,149 bytes相减，视作“同一组新增了2,399 bytes”。原组的精确成员保持不变，函数分批发生变化。详见[诊断汇总](../../build/cv32e40p/shared-regions-v3/diagnostics.json)、[profile](../../build/cv32e40p/shared-regions-v3/shared-perf.txt)、[源码行采样](../../build/cv32e40p/shared-regions-v3/shared-lines.txt)。

## 对下一步的约束

本轮验证了共享组合区域能够安全消除更多activity接口，但**只依据终点集合合并，不能保证减少总成本**。后续若继续该主线，需要把区域、译码复用和消费表达式一起处理：源变局部值不应自动丢掉跨周期复用，结果失去activity槽也不应要求逐项重新译码；同时应保留有价值的执行条件，控制高频大区域中的额外工作。

TNO0015的局部表实验已表明，只把直接比较换成逐项table load同样可能回退。本轮不重新开启该选项，不扩大region上限，不选择profile中较冷/较热的子集再测。当前约14%的剩余差距仍需从控制结果表示、消费网络及条件计算结构解决，不能以“少204个边界”宣布问题已解决。

上述耦合也适用于XiangShan：更大的共享控制锥可能因局部化丢失译码复用，也可能增加整个区域的触发频率；分区通信、memory intent、effects和live range仍是约束。本轮未构建或测量XiangShan，不能外推收益。

## 验证与复现

- 2项CTest通过：`emit-grhsim-event-regions`、`transform-activity-schedule`，见[日志](../../build/cv32e40p/shared-regions-v3/validation/ctest.log)。前者包含Clang O0/O3及ASan/UBSan oracle。
- 23项Python分析/runner测试通过；9项Python option-forwarding用例通过。后者从binding源文件提取纯参数转换函数验证，未重建Python native扩展，见[option日志](../../build/cv32e40p/shared-regions-v3/validation/python-options.log)。
- frozen binary、源快照、op集合、24个样本功能/placement、trace、配对汇总、`py_compile`、文档链接及两仓diff检查见[最终验证](../../build/cv32e40p/shared-regions-v3/validation/final.json)。

先按[testbench说明](../../testcase/cv32e40p-bench/README.md)准备native工具，再在node030以新目录执行：

```sh
python3 scripts/cv32e40p_shared_regions_compare.py build --output build/cv32e40p/shared-regions-reproduce
python3 scripts/cv32e40p_shared_regions_compare.py verify --output build/cv32e40p/shared-regions-reproduce
python3 scripts/cv32e40p_shared_regions_compare.py measure --output build/cv32e40p/shared-regions-reproduce
```

独立诊断入口：

```sh
python3 scripts/cv32e40p_shared_regions_analysis.py profile --output build/cv32e40p/shared-regions-reproduce
python3 scripts/cv32e40p_event_region_counts.py --source build/cv32e40p/shared-regions-reproduce --backend grhsim_shared_regions --output build/cv32e40p/shared-regions-reproduce-counts --detailed
python3 scripts/cv32e40p_shared_regions_analysis.py analyze --output build/cv32e40p/shared-regions-reproduce --counts build/cv32e40p/shared-regions-reproduce-counts
python3 scripts/cv32e40p_event_region_review.py --source build/cv32e40p/shared-regions-reproduce --backend grhsim_shared_regions --counts build/cv32e40p/shared-regions-reproduce-counts --mapping build/cv32e40p/shared-regions-reproduce/sources.csv --output build/cv32e40p/shared-regions-reproduce/boundaries.json
python3 scripts/cv32e40p_shared_regions_analysis.py decompose --before build/cv32e40p/event-regions-review-v1/report.json --after build/cv32e40p/shared-regions-reproduce/boundaries.json --output build/cv32e40p/shared-regions-reproduce/work-decomposition.json
```

本轮改动留在现有调查分支，未提交或push。共享区域扩展保持默认关闭，功能通过的负结果及原保留版均完整归档。
