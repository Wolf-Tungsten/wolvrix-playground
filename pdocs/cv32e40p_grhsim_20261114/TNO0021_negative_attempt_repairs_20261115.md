# TNO0021：负结果修复与固定对照测量

本轮实际修复并分别测量了TNO0020提出的三个具体遗漏。**布尔表和字段窗口的机器工作确实减少，但没有获得稳定的整机净收益；按IR活跃距离拒绝排序反而明显变慢，已撤回该成本门。** 当前保留模型和生产默认值不变。缓存跨变换组合、区域内部激活条件保留尚未实现，不能把这三个小范围修复当成对那些结构问题的完整解决。

## 对照范围与结果

共同保留版本是`conditional-mux-v4`，SHA `c7b8546489badb40431547248db1a6098b633f7592a94f9fba415eaed43dd5f3`；包含单终点区域和私有mux条件求值。Verilator为同一归一化RTL的既有binary，SHA `5396106991546a7aa0da975a44e9b92c21988bf6a4d60d4755bdafa370be7614`。本轮不分析SV转V影响，不重新选择RTL、负载、区域、阈值或编译参数。

每项采用四份模型：当前保留版、同基线上的旧实现、修后实现、Verilator。三个修复各自独立，未叠加布尔表、字段变换和共享区域。关闭所测功能时，生成源码必须与保留版本逐文件一致。三个实验均通过该检查。

测试仍为node030、CPU96、NUMA1、关闭ASLR、单线程，Clang 23.1.2、`-O3 -march=native -DNDEBUG -gline-tables-only`。两份GrhSIM变体使用同一harness、镜像和相应冻结工具；字段实验的旧/新transform使用**完全相同的冻结scheduler/emitter**。每份模型预热一次，每项只有一组8轮正反序`ABCD/DCBA`，每样本完整运行一次CoreMark。未因时间快慢删除样本，96个正式样本都在attempt0通过placement及功能门；CPU288在这些样本中的记录均为100% idle。

下表为配对`修后/对照 − 1`，负值更快。95% CI来自配对bootstrap；不能跨实验相减或把各项收益相加。

| 修复 | 对照 | 外部wall变化，95% CI | 仿真循环变化，95% CI |
| --- | --- | ---: | ---: |
| byte表改bool | 旧byte表 | +0.626%，[+0.290%, +0.978%] | +0.638%，[+0.293%, +1.003%] |
| byte表改bool | 当前保留版 | +2.602%，[+1.824%, +3.320%] | +2.636%，[+1.826%, +3.386%] |
| 已知对齐字段窗口 | 旧通用窗口 | −0.213%，[−0.684%, +0.320%] | −0.205%，[−0.688%, +0.346%] |
| 已知对齐字段窗口 | 当前保留版 | −0.614%，[−1.337%, +0.319%] | −0.602%，[−1.339%, +0.345%] |
| 排序活跃距离成本门 | 原共享区域排序 | +6.281%，[+5.402%, +7.367%] | +6.362%，[+5.483%, +7.446%] |
| 排序活跃距离成本门 | 当前保留版 | +4.539%，[+3.612%, +5.608%] | +4.595%，[+3.653%, +5.683%] |

各轮外部wall均值（秒）：

| 实验 | 当前保留版 | 旧实现 | 修后 | Verilator |
| --- | ---: | ---: | ---: | ---: |
| 布尔表 | 3.479478 | 3.547740 | 3.570036 | 3.165150 |
| 字段窗口 | 3.522217 | 3.507759 | 3.500075 | 3.215733 |
| 排序成本门 | 3.475203 | 3.418353 | 3.632897 | 3.185611 |

三份修后模型相对Verilator分别为1.12790倍、1.08841倍、1.14040倍。GrhSIM初始化均约6.7–7.1ms，循环时间与外部wall同方向。排序实验的**原共享区域控制**平均比保留版更快；这是共享区域与条件求值组合的附带观察，不是成本门修复的收益，本轮没有据此后验切换保留配置。

## 1. 布尔表：类型信息修复生效，逐项消费成本仍在

[emitter](../../wolvrix/lib/emit/grhsim_cpp.cpp)把局部表改成`std::array<bool, N>`，仅写`false/true`，消费者直接读bool；家族、更新位置、活动边界及条件求值位置不变。独立检查只归一化这些表示差异及相应冗余括号后，旧/新生成源码完全相等。[表示检查](../../build/cv32e40p/local-bool-repair-v2/representation-check.json)。

各后端一次独立PMU诊断显示，每模拟周期指令数：

| 模型 | 指令/模拟周期 |
| --- | ---: |
| 当前保留版 | 10603.610 |
| byte局部表 | 10763.707 |
| bool局部表 | 10728.392 |

bool比byte少35.315条、约0.328%；但仍比不启用局部表多124.782条。主要batch3的静态指令从7843降到7790，compare/test从799降到775，cmov/setcc从891降到873；包含栈操作数的指令却从1778增到1788。表读取、源变化检查、旧地址清除和新地址置位，以及逐谓词消费网络全部仍在。不能把减少归一化指令直接解释为等比例时间收益，也没有证据把0.626%的wall变化精确归因于某一种访存或分支。

布尔表示保留在原有**默认关闭**的local-equality实验实现中；它使0/1契约可传递，但当前数据不支持启用该缓存。尚未解决组内源维护位置、家族对排列的依赖或消费者紧凑表示。[分析及反汇编](../../build/cv32e40p/local-bool-repair-v2/repair-analysis.json)。

## 2. 字段窗口：从通用移位降到选择，但范围有限且重调度成本未消失

[slice-demand](../../wolvrix/lib/transform/slice_demand.cpp)增加通用证明：零填充concat产生`unsigned(index) << k`，payload跨度不超过步长，请求窗口完整位于一个字段内；同宽赋值、单元素concat和`0 - amount`可传递证明。至少一个前导零保证正负量在signed位宽中可表示。方向mux的比较量、左移量和右移量必须具有同一索引、步长和位宽，否则回退。

真实模型命中两个根，日志为`roots=2 wide_shift_windows=2 aligned_fields=2`。原先的方向比较、变量移位、相减及overshift分支变成共享的`index5 == 3`，分别选择mask和data，保留其余宽用户。实际batch3生成了等值条件与窄字段选择；机器码可见`cmpl $3`与选取旧字段/新字段的控制流，不再保留该窗口的通用移位链。[IR与生成源码片段](../../build/cv32e40p/aligned-field-repair-v1/field-lowering.json)、[带行号机器码](../../build/cv32e40p/aligned-field-repair-v1/assembly/grhsim_aligned_window/batch3-lines.s)。

相对旧通用窗口，每周期少34.147条退休指令（0.323%）；相对保留版少62.563条（0.590%）。batch3静态指令7729→7688，栈操作数指令1720→1696。改写确实发挥了作用，但只有两个窄窗口，削减的整机工作量很小。

独立诊断仍观察到413→414个checked values和额外一个u32槽；scalar变化检测185.655→188.196次/周期，变化次数37.116→37.263次/周期。fixed-point仍是低相位一轮、高相位两轮。也就是说，窗口本身已简化，原transform后重调度引入的额外边界检查仍在。不能把全部62.563条指令差归到字段公式，更不能声称边界副作用已解决。[完整计数、PMU与静态统计](../../build/cv32e40p/aligned-field-repair-v1/repair-analysis.json)。

此证明及边界测试保留在显式二态、非默认的slice-demand pass中；CI跨零，因此不加入当前保留pipeline。

## 3. 排序成本门：静态IR指标方向与机器码相反，撤回

候选对每个新区域比较原拓扑顺序和首次使用顺序，仅在def-to-last-use距离总和不增加时采用后者。六个共享区域中有一个被挡住；合并区域的原顺序总和104055，首次使用方案134294，采用成本门后99089。这里比较的是**同一批已合并区域的排序**，不是融合前后，也不是寄存器spill计数。

归一化图与区域成员完全相同，只有group31的操作顺序改变。507项动态探针逐项相等，包括全部区域次数、比较/变化计数、条件mux分支次数；group31仍约每周期执行一次。源代码变化在batch1的排列及batch2引用的槽号；消除槽号重编号后batch2文本完全一致。[隔离检查](../../build/cv32e40p/region-order-repair-v1/order-isolation.json)。

然而主要受影响的batch1机器码变为：

| 指标 | 原排序 | 成本门 |
| --- | ---: | ---: |
| 函数字节 | 10501 | 12084 |
| 静态指令 | 2330 | 2514 |
| 带内存操作数的指令 | 947 | 1313 |
| 带栈操作数的指令 | 496 | 870 |
| prologue栈分配 | 224字节 | 424字节 |

独立PMU的整机指令10614.481→10864.402条/周期，增加249.921条（2.355%）；IPC 3.370→3.229。新增成本集中于不同顺序所产生的机器码与寄存器/栈使用，而非区域执行次数增加。仍不能把374处静态栈指令直接换算成374次动态spill，槽布局变化也不能从本次对照中剥离。[分析与逐函数反汇编](../../build/cv32e40p/region-order-repair-v1/repair-analysis.json)。

IR距离按原op位置求和，忽略emitter内联、Clang消除/融合、不同位宽的机器表示、寄存器分配和持久槽布局。该候选给出了直接反例：它降低了代理指标，却生成更多栈工作。因此本轮撤回此成本门，scheduler文件已与保留版本快照逐字节一致。候选代码、native tools、测试、binary和[补丁](../../build/cv32e40p/region-order-repair-v1/withdrawn-order-guard.patch)仍冻结在实验目录，可以重放，不加入新的默认开关。

## 功能验证、实现边界与下一步

全部12份对照模型均通过253周期smoke及3376065周期CoreMark，CRC、UART、退出码和完整有效总线trace一致；CoreMark trace SHA为`ed2b490886767aa74524a6dd15e708e8f2b231bc3886814af0ba4d1919b3e098`。诊断版本另外验证同一trace，不参与正式计时。机器码指标和PMU均使用对应冻结binary；PMU每后端仅一次，包含进程启动开销并按相同guest周期归一化，不作独立时间收益证据。

focused CTest覆盖局部译码、slice-demand及event-regions，使用Clang O0/O3与ASan/UBSan；字段新增用例覆盖全部5位索引、signed方向、mask/data更新、56位索引、跨字段回退和不同索引拒绝。Python回归检查表示归一化不能吞掉常量/逻辑变化、计数分项与总量一致，以及已有功能门和倍率方向。[最终验证与产物索引](../../build/cv32e40p/repair-review-v1/report.json)。

当前证据支持继续处理**缓存的语义身份与区域内部执行条件**。局部表示修补已不足以抵消每个谓词单独消费；少两个宽窗口只能减少有限工作；IR活跃距离成本门已被实际反例否定。后续应保留有价值的缓存和触发条件，再评估消费者融合与区域扩大。不能直接删掉组内源排除检查，必须证明维护点位于源可用之后、首次消费之前。

这些类型契约和对齐证明没有CV32信号名特判，可用于XiangShan中满足相同条件的表达式；但本轮没有XiangShan实测。分区、状态可见性与宽值比例不同，不外推性能数值，也不在XiangShan开启这些实验项。

## 复现入口

[对照runner](../../scripts/cv32e40p_repair_compare.py)、[归因脚本](../../scripts/cv32e40p_repair_analysis.py)。每项的`build.json`保存binary、工具、源码快照、镜像链及编译器身份；`logs/*.command.json`、`*.result.json`保存完整构建命令和单独耗时；`pairs.csv`保存每轮wall、loop、init时间。

下例在node030、仓库根运行，使用新输出目录。`--tools`明确使用已冻结候选，尤其排序成本门已经从当前源码撤回：

```bash
python3 scripts/cv32e40p_repair_compare.py build --repair bool \
  --tools build/cv32e40p/local-bool-repair-v2/native-frozen \
  --output build/cv32e40p/local-bool-reproduce
python3 scripts/cv32e40p_repair_compare.py build --repair aligned \
  --tools build/cv32e40p/aligned-field-repair-v1/native-transform \
  --output build/cv32e40p/aligned-field-reproduce
python3 scripts/cv32e40p_repair_compare.py build --repair order \
  --tools build/cv32e40p/region-order-repair-v1/native-frozen \
  --output build/cv32e40p/region-order-reproduce

# 对所选的一个独立实验依次执行；不要与编译或其它计时并发。
python3 scripts/cv32e40p_repair_compare.py verify --output build/cv32e40p/region-order-reproduce
python3 scripts/cv32e40p_repair_compare.py measure --output build/cv32e40p/region-order-reproduce
PATH=/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin:$PATH \
  python3 scripts/cv32e40p_repair_compare.py diagnose --output build/cv32e40p/region-order-reproduce
```

已有结果：[布尔表](../../build/cv32e40p/local-bool-repair-v2/report.json)、[字段窗口](../../build/cv32e40p/aligned-field-repair-v1/report.json)、[排序成本门](../../build/cv32e40p/region-order-repair-v1/report.json)。`local-bool-repair-v1`仅因源码等价检查未归一化冗余括号而提前停止，没有计时样本；修正检查后使用v2，未修改候选参数。
