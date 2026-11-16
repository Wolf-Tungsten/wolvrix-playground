# TNO0017：译码消费者集合化简的实现与负结果

本轮实施规划的第一项：在活动调度之前，把同源等值谓词及其OR消费者转换成精确的区间集合判断。功能验证通过，但node030上的唯一一组8轮配对显示 **walltime增加1.579%**，95% CI **[+1.155%, +1.978%]**，8/8轮更慢。**不采纳为更快配置，不加入生产默认流程。** 当前保留的单终点事件区域版在同轮为归一化Verilator的 **1.14086倍**。

这次不是“IR没简化”：大组合区域的Eq从350降到223，机器码也缩小。但新依赖关系使部分谓词从稀疏缓存退化为直接计算，区间条件还形成了新的跨组边界；最终退休指令仅减少0.439%，Host cycles反而增加1.719%。IPC下降是实测结果，尚不能精确归因于某一种访存、分支或流水线瓶颈。

## 规则和冻结范围

新增独立、实验性pass：`predicate-set -semantics 2state`。它没有加入`simplify`或任何默认pipeline；默认/显式四态模式不改图。规则不使用CPU名、信号名或profile。

- 接受Boolean OR树，以及Boolean concat的ReduceOr消费者。每组叶子是同一无符号Logic SSA源与相同位宽的已知常量之间的Eq。
- 对每个源独立去重、排序常量，合并成最大的不回绕连续区间；区间用unsigned Ge/Le/And，单点用Eq，0/最大值端点省掉冗余条件。相同新常量、区间条件和Boolean组合在图内共享。
- 固定预算：源宽2–64，最多512个Boolean叶子、2,048次遍历，至少16个不同常量，平均每区间至少8个常量。稀疏集合、signed、未知常量、超限或循环Boolean锥回退。
- 保留不属于已选家族的Boolean输入。保留原结果SSA、公开端口和其它原谓词用户，由DCE决定无用op；不移动memory、event、effect或state读写。
- 在activity schedule之前执行，并正常重建依赖、组和通知。复用此前最快的单终点事件区域规则，不启用共享区域或局部one-hot实验。

这是一种固定的区间表示，并未同时试验mask、bitset、查表等其它表示后选优。此前讨论的“紧凑control word”尚未完成，不能把本次局部集合化简称为整个译码网络的最终方案。语义和限制见[功能文档](../../wolvrix/docs/transform/predicate-set.md)。

使用相同归一化RTL、CoreMark、Clang23.1.2与`-O3 -march=native`。候选和control从同一输入图开始，使用同一份冻结scheduler/emitter库；只有新transform库参与候选图改写。control经相同DCE后生成的C++逐文件等于保留版。输入、编译选项和工具SHA见[build.json](../../build/cv32e40p/predicate-set-v1/build.json)，运行前假设见[hypothesis.json](../../build/cv32e40p/predicate-set-v1/hypothesis.json)。

| 后端 | binary SHA256 |
| --- | --- |
| 保留的事件区域版 | `792ffa67830d766fd5418bd967e41615090141f8faa7c4ac58c0d3fa2438ee65` |
| 集合消费者候选 | `0c15e89eea5d08002a0423325a7831a0757eb73331fb019abc34bd63dc0a238d` |
| 归一化Verilator | `5396106991546a7aa0da975a44e9b92c21988bf6a4d60d4755bdafa370be7614` |

测量后通用代码复审补上循环OR锥拒绝和full-domain回归。最终transform重新生成的control/candidate图与已测量输入图均**逐字节相同**，未产生新的性能候选或重跑选优；原native库、源码和最终版本分别保留。见[最终源码等价验证](../../build/cv32e40p/predicate-set-v1/validation/final-source-equivalence.json)。

## 功能与实际结构变化

独立oracle穷举12位源全部4096个值和两个残余Boolean值，第二个输入采用遍历全域的置换；覆盖重复/交换操作数、多源家族、原谓词独立输出、64位两端、全域集合，以及时钟保持时的组合变化和寄存器保持。off/on生成模型均通过Clang O0、O3 ASan/UBSan。负面测试覆盖默认关闭、signed、65位、X常量、稀疏/小/超限集合、effect及循环根。pass-manager和DCE测试也通过。

三侧完整smoke/CoreMark功能门通过：smoke为253周期，CoreMark为3,376,065周期，退出码、UART和预期CRC一致，逐周期bus trace SHA均为`ed2b490886767aa74524a6dd15e708e8f2b231bc3886814af0ba4d1919b3e098`。计数诊断模型通过相同trace。[功能证据](../../build/cv32e40p/predicate-set-v1/functional.json)。

规则命中16个消费者、16个家族，计数器累计处理990个常量成员、77个区间；不同消费者可能重叠，**990不是被删除的不同Eq数**。

| 静态指标 | 保留版/control | 候选 |
| --- | ---: | ---: |
| 调度前图op | 44,296 | 44,466 |
| 调度前图Eq | 684 | 702 |
| 调度前图ReduceOr | 168 | 156 |
| 调度前图Concat | 631 | 619 |
| 最大组合区域op | 4,810 | 4,623 |
| 该区域Eq | 350 | 223 |
| checked value | 413 | 273 |
| 中间scalar槽 | 704 | 564 |
| compute/commit组 | 32/4 | 30/4 |
| scheduler C++ bytes | 1,309,489 | 1,009,516 |

图op增加，是因为保留了还有其它用户的原谓词，同时增加新的区间条件；调度后的最大区域反而缩小，两者口径不同。原两条62项和一条126项归约均被改写，但不能据此宣称相应谓词全部消失。完整结构见[structure.json](../../build/cv32e40p/predicate-set-v1/structure.json)和[源映射](../../build/cv32e40p/predicate-set-v1/sources.csv)。

## 唯一一组8轮配对

node030 CPU96、NUMA1、单线程、ASLR关闭。三侧各一次预热，随后8轮ABC/CBA，完整重启数为1。24个样本均一次通过功能与placement/locality门，无重试或按速度删样本；CPU288在所有区间记录为100% idle。

| 后端 | wall均值 | simulation loop均值 |
| --- | ---: | ---: |
| 保留的事件区域版 | 3.663938 s | 3.629920 s |
| 集合消费者候选 | 3.721714 s | 3.689289 s |
| 归一化Verilator | 3.211678 s | 3.176543 s |

- 候选/保留wall：**1.015788**，95% paired bootstrap CI **[1.011552, 1.019775]**，8/8更慢。
- 候选/保留loop：1.016373，CI [1.012463, 1.020202]。
- 候选/Verilator wall：1.158856，CI [1.153479, 1.163946]。
- 同轮保留/Verilator wall：**1.140861**，CI [1.135774, 1.145736]。

倍率是每轮比值的均值。[report](../../build/cv32e40p/predicate-set-v1/report.json)、[pairs.csv](../../build/cv32e40p/predicate-set-v1/pairs.csv)、[策略及预热](../../build/cv32e40p/predicate-set-v1/measurement-policy.json)。构建不进入上述时间：候选transform 0.550 s、emit 2.039 s、并行编译20.223 s、harness链接1.198 s。

## 为何没有转成收益

### 1. 稀疏缓存被新的调度形态破坏

完整CoreMark计数显示，fixed-point仍是low一轮、high两轮，最大组合区域仍每周期一次。scalar变化检测却从 **185.655056升到209.037636次/周期**，实际变化从37.115703到37.309054，几乎没变。

| 每周期变化检测增减 | 次数 |
| --- | ---: |
| 消失的155个旧边界 | −0.002141 |
| 新增/无法按原输入身份对应的15个边界 | +10.557984 |
| 保留值的执行变化 | +12.826736 |
| 合计 | **+23.382579** |

155个消失的边界全是旧共享decoder的稀疏更新结果，原本几乎没有执行成本。11个新边界属于区间表达式，贡献9.613408次/周期检测，变化仅0.195491次/周期。

15个保留Eq从缓存的init/clear/set三处变成直接检查，合计增加13.014176次/周期。它们的源仍是`_val_134`，并未丢失源槽；这里与上一轮的局部源问题不同：**新组4混排了局部和持久谓词、区间条件，打断旧规则要求的“至少16个连续、独立存储谓词”**。可缓存的持久Eq连续段最多12个，因此全部回退为普通Eq。其组执行率为0.873946次/周期，许多原来计数为0的检查随之接近该频率。

这条相互作用可以在[cache-interaction.json](../../build/cv32e40p/predicate-set-v1/cache-interaction.json)逐谓词核验。旧新图numeric ID不同，分析按原输入中稳定的value名称及各自映射对照，不直接连接同号ID。逐值总和与aggregate核对见[attribution.json](../../build/cv32e40p/predicate-set-v1/attribution.json)。

### 2. 静态机器码减少远多于动态指令减少

| 机器码指标 | 保留版 | 候选 |
| --- | ---: | ---: |
| 所选eval/compute/commit函数bytes | 75,828 | 65,226 |
| 所选函数静态instructions | 15,404 | 13,397 |
| 大compute函数instructions | 7,596 | 7,483 |
| 大compute函数memory-operand instructions | 2,796 | 2,788 |
| 大compute函数stack-operand instructions | 1,676 | 1,672 |
| 大compute函数compare/test | 847 | 822 |
| 大compute函数conditional branches | 99 | 107 |

大函数只减少113条静态指令，栈操作数基本不变。整组源码/机器码缩小还包括原本很少执行的decoder初始化和清旧/置新路径消失。静态减少13%的指令，并不意味着每周期工作减少13%。

### 3. 动态指令净省很少，吞吐还下降

两侧各一次独立PMU诊断，不混入正式配对统计：

| 每guest cycle | 保留版 | 候选 | Verilator |
| --- | ---: | ---: | ---: |
| retired instructions | 11,130.083 | 11,081.201 | 9,799.121 |
| Host cycles | 3,340.331 | 3,397.744 | 2,934.918 |
| branches | 471.673 | 473.369 | 568.442 |
| branch misses | 1.096 | 1.081 | 0.881 |
| IPC | 3.3320 | 3.2613 | 3.3388 |

指令 −0.439%，Host cycles +1.719%，IPC −2.122%。branch miss未增加，不能解释成“区间分支预测失败”；栈访问静态数量也不足以证明spill增加。当前证据只支持**净工作节省很小且执行吞吐变差**，没有将1.58%耗时归因到某个CPU微结构事件。

候选profile仍以大compute函数为主（58.85%）；只用于候选自身热点定位，不与旧采样百分比直接相减。[机器码与原始PMU](../../build/cv32e40p/predicate-set-v1/diagnostics.json)、[profile](../../build/cv32e40p/predicate-set-v1/candidate-perf.txt)。

## 结论对后续工作的约束

这次负结果否定的是当前“最大连续区间集合+普通重调度”的净收益，不能据此否定所有消费者融合。已有共享decoder对谓词连续排列、独立槽以及最小家族规模的依赖，再次成为优化组合的障碍。后续需要先形成不依赖偶然排列的源/消费域描述，并避免把新条件拆回逐值activity接口；不能只按区间数或Eq数给收益打分。

按原先顺序，下一独立方向仍可检查宽值的按需位域计算：它直接减少区域内部的数据路径工作，较少依赖译码家族布局。但本轮不叠加该修改，不调阈值、不按本次profile选择子集、不追加性能选优。

对XiangShan同样需注意优化组合：CSR/opcode分类可能压缩，但也可能打断既有译码缓存或增加跨partition接口。此次没有XiangShan测量，不外推性能。生产默认值及当前最佳事件区域配置均保持原状。

## 验证、产物与复现

- 3项相关CTest通过，其中新transform生成模型覆盖O0/O3及ASan/UBSan；[新规则日志](../../build/cv32e40p/predicate-set-v1/validation/predicate-test.log)、[pass-manager/DCE日志](../../build/cv32e40p/predicate-set-v1/validation/related-test.log)。
- 23项既有Python runner/计数/机器码分析测试通过，包含倍率方向和phase计数；新增分析执行时检查图映射、trace、逐值和aggregate恒等式。[Python结果](../../build/cv32e40p/predicate-set-v1/validation/python-tests.json)。
- 最终graph SHA、frozen inputs/binaries、24个样本、paired summary重算、文档链接、`py_compile`和两仓diff检查见[最终验证](../../build/cv32e40p/predicate-set-v1/validation/final.json)。
- [运行入口](../../scripts/cv32e40p_predicate_compare.py)、[归因脚本](../../scripts/cv32e40p_predicate_analysis.py)、[计数产物](../../build/cv32e40p/predicate-set-counts-v1/counts.json)。

node030上构建native工具后，使用新目录复现：

```sh
cmake -S testcase/cv32e40p-bench -B build/cv32e40p/tools
cmake --build build/cv32e40p/tools --target cv32e40p_predicate -j12
python3 scripts/cv32e40p_predicate_compare.py build --output build/cv32e40p/predicate-set-reproduce
python3 scripts/cv32e40p_predicate_compare.py verify --output build/cv32e40p/predicate-set-reproduce
python3 scripts/cv32e40p_predicate_compare.py measure --output build/cv32e40p/predicate-set-reproduce
PATH=/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin:$PATH python3 scripts/cv32e40p_predicate_compare.py diagnose --output build/cv32e40p/predicate-set-reproduce
python3 scripts/cv32e40p_event_region_counts.py --source build/cv32e40p/predicate-set-reproduce --backend grhsim_predicate_set --output build/cv32e40p/predicate-set-reproduce-counts --detailed
python3 scripts/cv32e40p_predicate_analysis.py --output build/cv32e40p/predicate-set-reproduce --counts build/cv32e40p/predicate-set-reproduce-counts
```

driver复用当前工作区已冻结的输入图、保留版binary、Verilator binary和native emitter，完整身份由build manifest记录。本轮改动未提交或push。
