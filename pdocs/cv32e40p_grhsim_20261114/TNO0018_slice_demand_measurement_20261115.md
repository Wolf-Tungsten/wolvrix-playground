# TNO0018：宽运算按需位段计算的实现与测量

完成规划的第二项：沿最终的窄slice需求，把宽逻辑移位、mux和按位运算改成标量窗口计算。候选功能通过，生成C++中的4个1024位移位调用和2个宽mux全部消失；但8轮配对walltime只有 **−0.093%**，95% CI **[−0.826%, +0.740%]**，没有稳定收益。**保持实验关闭，不替换当前保留的单终点事件区域版。**

独立PMU表明退休指令只减少 **0.180%**。大compute函数净少24条静态指令，栈帧缩小400字节。这进一步说明宽源码不等于完整的逐word运行成本；原始inline helper经过Clang优化后，净可省的工作远小于源码形态暗示的量。此结论不依赖SV转V差异，两侧仍使用同一归一化RTL。

## 实现、适用范围与正确性

新增独立实验pass `slice-demand -semantics 2state`，没有加入`simplify`或默认pipeline。默认/显式四态模式不改变图。通用机制与例子见[功能文档](../../wolvrix/docs/transform/slice-demand.md)。

- 根是从128–4096位Logic源截取2–64位的合法static slice。本轮不把宽总线拆成逐位计算。
- 在纯组合的mux、按位And/Or/Xor/Not、同宽Assign和Concat中向前传递窗口。
- 遇到逻辑左右移时，要求输入能证明只有一个至多64位的非零/可变span，其余是零。支持宽常量、零填充和多个相邻scalar片段；算术右移、致密宽输入等回退。
- 用原SSA输入和scalar逻辑移位计算窗口。对任意64位移位量保留越界清零语义，避免移位量加法溢出；signed scalar先取其原始位模式再零扩展。
- 原结果身份及其它宽值用户保留。先完整计划再修改图，遇到未知常量、effect、循环、宽度错误或固定预算超限不会留下半完成变换。预算为深度32、256个计划表达式、64个concat片段。
- 不移动state/memory/event/effect，之后正常DCE和重建活动调度。候选scheduler/emitter仍是此前冻结的版本；没有叠加上一轮predicate-set或共享区域规则。

例如源为`concat(992'b0, data32)`，需求是左移后的`[111:96]`，转换为：

```text
low16(amount <= 96 ? uint64(data32) >> (96 - amount)
                   : uint64(data32) << (amount - 96))
```

这里的移位采用IR的overshift清零语义，生成器仍需处理大于等于64的shift，不能裸用未检查的C++移位。这个通用公式没有把具体CSR的地址步长、符号判断和写使能进一步还原为数组字段更新。

独立oracle覆盖左右移、窗口相对payload的两种偏移方向、2/16/32/64位结果、最大移位量`UINT64_MAX`、signed输入位模式、宽常量、跨concat窗口、多片段payload、mux/bitwise链、其它用户观察原1024位结果，以及寄存器和时钟保持时的输出。off/on模型均通过Clang O0与O3 ASan/UBSan。负面用例包括默认关闭、AShr、65位payload/amount、X、effects、循环、深度/宽度超限及错误slice/concat宽度。

最终复审补上了concat累加前的宽度检查和负面回归，防止畸形IR发生整数溢出。最终工具生成的control/candidate图与已经测量的图逐字节一致；未产生第二个性能候选，见[源码等价检查](../../build/cv32e40p/slice-demand-v1/validation/final-source-equivalence.json)。

## 冻结身份与功能门

| 后端 | binary SHA256 |
| --- | --- |
| 保留事件区域版 | `792ffa67830d766fd5418bd967e41615090141f8faa7c4ac58c0d3fa2438ee65` |
| 按需位段候选 | `33bf2b2fafebade375d3859666d01426ead4ebe1fdb0ccd8ad56bc0f842e8f03` |
| 归一化Verilator | `5396106991546a7aa0da975a44e9b92c21988bf6a4d60d4755bdafa370be7614` |

Clang23.1.2，`-std=c++20 -O3 -march=native -DNDEBUG -gline-tables-only`。同一输入图、CoreMark和harness；候选/控制复用同一冻结scheduler/emitter库，仅transform库不同。control正常DCE后生成的C++逐文件等于保留版。工具、输入图、源码和编译选项见[build.json](../../build/cv32e40p/slice-demand-v1/build.json)，测量前假设见[hypothesis.json](../../build/cv32e40p/slice-demand-v1/hypothesis.json)。

三侧smoke为253周期；CoreMark为3,376,065周期，UART、CRC、退出码和完整bus trace一致。CoreMark trace SHA为`ed2b490886767aa74524a6dd15e708e8f2b231bc3886814af0ba4d1919b3e098`；独立计数模型也通过相同trace。[功能产物](../../build/cv32e40p/slice-demand-v1/functional.json)。

## 实际改写范围

静态规则只命中两个16位根`_val_8`和`_val_11`，各自请求bit96–111，合计4个宽移位窗口。没有根据运行结果挑选信号。

| 指标 | 保留版 | 候选 |
| --- | ---: | ---: |
| generated宽Shl/LShr helper调用 | 4 | 0 |
| generated宽mux调用 | 2 | 0 |
| compute/commit组 | 32/4 | 32/4 |
| checked value | 413 | 414 |
| scalar中间槽 | 704 | 705 |
| 最大compute区域op | 4,810 | 4,822 |
| scheduler C++ bytes | 1,309,489 | 1,309,701 |

新增23个参与调度的scalar表达式，替换宽路径所需的运算，并非把全部宽IR删掉：其它声明位/用户仍保留原图关系。生成路径从宽helper变成比较、减法、带越界保护的scalar shift和窄mux。结构与根映射见[lowering-evidence.json](../../build/cv32e40p/slice-demand-v1/lowering-evidence.json)、[structure.json](../../build/cv32e40p/slice-demand-v1/structure.json)。

## 唯一一组8轮配对

固定node030 CPU96、单线程、NUMA1、ASLR关闭。每侧一次预热，8轮ABC/CBA，每样本完整重启数为1。24个样本一次通过功能和既有placement/locality门，没有重试或按快慢删样本；CPU288在各样本区间均记录为100% idle。

| 后端 | wall均值 | simulation loop均值 |
| --- | ---: | ---: |
| 保留版 | 3.659386 s | 3.627309 s |
| 按需位段候选 | 3.655965 s | 3.622676 s |
| 归一化Verilator | 3.211912 s | 3.174811 s |

- 候选/保留wall：**0.999074**，95% paired bootstrap CI **[0.991744, 1.007397]**；4轮更快、4轮更慢。
- 候选/保留loop：0.998741，CI [0.991514, 1.007014]。
- 候选/Verilator wall：1.138530，CI [1.127035, 1.147190]。
- 同轮保留/Verilator wall：1.139823，CI [1.120774, 1.152868]。

所有有效样本保留，本组存在轮间波动，不以个别慢样本为由追加选优。倍率是逐轮比值的均值。[report](../../build/cv32e40p/slice-demand-v1/report.json)、[pairs.csv](../../build/cv32e40p/slice-demand-v1/pairs.csv)、[测量策略](../../build/cv32e40p/slice-demand-v1/measurement-policy.json)。构建独立记录：transform 0.510 s、emit 2.055 s、并行编译24.007 s、harness链接1.200 s，不计入仿真walltime。

## 为何消除宽helper仍只有很小收益

一次独立PMU诊断，不混入配对数据：

| 每guest cycle | 保留版 | 候选 | Verilator |
| --- | ---: | ---: | ---: |
| retired instructions | 11,130.083 | 11,110.015 | 9,799.121 |
| Host cycles | 3,339.557 | 3,338.544 | 2,934.012 |
| branches | 471.673 | 467.960 | 568.442 |
| branch misses | 1.068 | 1.094 | 0.882 |
| IPC | 3.3328 | 3.3278 | 3.3398 |

退休指令只少20.07条/guest cycle（−0.180%），Host cycles约−0.030%。主函数的变化同样有限：

| `eval_compute_batch_3` | 保留版 | 候选 |
| --- | ---: | ---: |
| code bytes | 36,149 | 35,772 |
| 静态instructions | 7,596 | 7,572 |
| memory-operand instructions | 2,796 | 2,804 |
| stack-operand instructions | 1,676 | 1,680 |
| conditional branches | 99 | 91 |
| prologue中stack分配 | `0x9b8`（2,488 B） | `0x828`（2,088 B） |

栈帧少400字节，并不意味着动态栈访存减少400字节/周期；静态栈操作数还略增。原wide helper为always-inline模板，最终窄slice使Clang可以去掉不少无用word计算；候选同时增加通用shift guard与位移量算术。**净差异说明这两个窗口不是当前约14%差距的主要可回收成本**，但没有给原helper每条指令做因果占比分摊。

计数还发现小幅调度副作用：固定点仍是low一轮、high两轮，两个大region仍各执行一次；变化检测从185.655056到188.196314次/周期。新增一个原有32位slice `_val_352`的边界，贡献0.947699次/周期；其它保留值因重组增加净1.593559次。原组24的3个取指控制结果从约0.45137次/周期升到约0.99997次。旧共享decoder的init/clear/set形态没有丢失，所以此次没有重现上一轮大量译码缓存回退。

证据见[动态归因](../../build/cv32e40p/slice-demand-v1/attribution.json)、[调度变化](../../build/cv32e40p/slice-demand-v1/schedule-interaction.json)、[机器码/PMU](../../build/cv32e40p/slice-demand-v1/diagnostics.json)。候选自身采样约59.42%仍在大compute函数；[profile](../../build/cv32e40p/slice-demand-v1/candidate-perf.txt)只用于热点定位，不与历史百分比相减。

## 后续边界

按需位段机制功能成立，但当前适用范围只净省很少机器工作，不能凭“1024变64”继续扩展或默认开启。当前scalar路径仍计算一般的位移量与保护条件，没有恢复源RTL中的完整字段写入语义；若以后做代数化简，应以通用位宽/对齐证明为依据，不能硬编码CSR地址。

按既定顺序，下一条独立主线是条件求值：把昂贵且纯、独占的候选表达式放到真实使用条件中，同时保持共享计算和旧状态快照。开始前必须先证明目标在当前binary里仍有足够动态成本，避免再次只按源码复杂度估计收益。本轮没有叠加这一修改，也没有扫描阈值或扩展负载。

XiangShan的宽mask、packed-field更新和零填充向量可能出现同类窄需求；当前规则支持证明的稀疏span，不支持任意致密宽数据。这里没有XiangShan性能测量，不外推收益。

## 验证和复现

- 3项相关CTest通过：新规则oracle及`transform-pass-manager`、`transform-dead-code-elim`；[新规则日志](../../build/cv32e40p/slice-demand-v1/validation/slice-demand-test.log)、[相关日志](../../build/cv32e40p/slice-demand-v1/validation/related-test.log)。
- 23项Python runner/计数/机器码分析测试通过，包含倍率方向和phase计数；新增归因脚本运行时核对映射、trace和逐值/aggregate恒等式。[Python结果](../../build/cv32e40p/slice-demand-v1/validation/python-tests.json)。
- 输入/源码/binary SHA、全部样本、summary重算、`py_compile`、相对链接和两仓diff检查见[最终验证](../../build/cv32e40p/slice-demand-v1/validation/final.json)。

node030上用新目录执行，driver复用当前工作区冻结输入和emitter：

```sh
cmake -S testcase/cv32e40p-bench -B build/cv32e40p/tools
cmake --build build/cv32e40p/tools --target cv32e40p_slice_demand -j12
python3 scripts/cv32e40p_slice_demand_compare.py build --output build/cv32e40p/slice-demand-reproduce
python3 scripts/cv32e40p_slice_demand_compare.py verify --output build/cv32e40p/slice-demand-reproduce
python3 scripts/cv32e40p_slice_demand_compare.py measure --output build/cv32e40p/slice-demand-reproduce
PATH=/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin:$PATH python3 scripts/cv32e40p_slice_demand_compare.py diagnose --output build/cv32e40p/slice-demand-reproduce
python3 scripts/cv32e40p_event_region_counts.py --source build/cv32e40p/slice-demand-reproduce --backend grhsim_slice_demand --output build/cv32e40p/slice-demand-reproduce-counts --detailed
python3 scripts/cv32e40p_slice_demand_analysis.py --output build/cv32e40p/slice-demand-reproduce --counts build/cv32e40p/slice-demand-reproduce-counts
```

代码和负结果留在调查分支，未提交或push；默认流程与当前最佳实验配置不变。
