# TNO0023：在合并区域内保留条件计算锥的输入复用

本轮延续[TNO0022](./TNO0022_sparse_cache_region_composition_20261115.md)的剩余问题：区域合并虽然减少了中间存储和通知，也让部分低频计算随整个区域反复执行。新增固定、默认关闭的条件锥输入缓存，不改变区域和调度顺序。CoreMark上命中IRQ优先级选择锥，正式walltime下降 **0.385%**，95% CI **[−0.728%, −0.043%]**；相对同一归一化RTL的Verilator仍为 **1.04078倍**。

收益较小，CI上界接近零。动态证据证明重复计算已经消除，但这一处只占原退休指令量约0.47%，没有解决其余结构差距。没有追加测量、改阈值或根据跑分再选候选。

## 实现及边界

新选项`conditional_mux_input_cache` / `WOLVRIX_GRHSIM_CONDITIONAL_MUX_INPUT_CACHE`默认关闭，依赖原`conditional_mux_cones`。只处理已经通过纯度、私有使用、别名和标量lowering检查的条件锥；根结果必须有独占持久scalar slot。

按SSA收集条件及两个分支的完整输入依赖，穿过局部纯表达式，在持久值、模型输入或寄存器读取处停止。固定上限为4个精确scalar键、32层依赖、256个访问值，父规则每个选中分支仍为16–256个操作。没有hash、信号名匹配或profile筛选。

```text
每次区域执行：读取精确输入键
首次执行或输入改变：执行原条件锥，比较/保存/通知原结果，更新键
输入不变：直接使用原持久结果
init：使缓存无效
```

局部临时量不能跨调用复用，因此没有持久结果的表达式仍回退。缓存命中不会跳过其余区域，也不改变fixed-point循环、commit或通知目标。[功能说明与安全条件](../../wolvrix/docs/emit/grhsim-conditional-mux-input-cache.md)。

开发回归发现同寄存器源克隆被计成两个独立键，导致寄存器用例超出预算。已在证明纯净、无中间写入的区域内合并同寄存器、同位宽和符号属性的本地无操作数读取，并增加不同寄存器不能合并的反例。该修复在候选冻结和整机测量之前完成。

## 输入与功能验证

| 后端 | binary SHA前缀 | 配置 |
| --- | --- | --- |
| 本轮基线 | `ac8a4dbdc7b2` | TNO0022共享区域、条件求值、稀疏家族缓存 |
| 输入缓存候选 | `600e92ca3a1d` | 基线加固定输入缓存规则 |
| Verilator | `539610699154` | 相同归一化RTL |

源码图、固件、harness和编译器沿用冻结版本，均为Clang23.1.2、`-O3 -march=native -DNDEBUG -gline-tables-only`。关闭新选项时，生成C++与基线逐文件相同。开启后归一化图、209个checked values、39个supernode块、存储slot数、conditional mux及equality family位置均不变。[输入清单](../../build/cv32e40p/mux-input-cache-v1/build.json)、[结构核验](../../build/cv32e40p/mux-input-cache-v1/structure.json)、[事前假设](../../build/cv32e40p/mux-input-cache-v1/hypothesis.json)。

三后端均通过253周期smoke和3,376,065周期CoreMark；CRC、UART、退出码和每周期总线trace一致。CoreMark trace SHA为`ed2b490886767aa74524a6dd15e708e8f2b231bc3886814af0ba4d1919b3e098`。[功能证据](../../build/cv32e40p/mux-input-cache-v1/functional.json)。

原conditional mux与新增input-cache两个CTest通过，生成模型分别运行Clang O0、O3及ASan/UBSan。覆盖输入变化、保持时钟、寄存器更新、重复输入、重新初始化、fullpass命中、环境优先级及各类保守回退。相关Python回归14项通过，包含缓存计数的四相位oracle、变化通知不丢失与倍率方向。[CTest日志](../../build/cv32e40p/mux-input-cache-v1/validation/mux-input-cache-ctest3.log)、[Python日志](../../build/cv32e40p/mux-input-cache-v1/validation/python-tests.log)。

## 固定八轮测量

node030、CPU96、NUMA1、单线程、关闭ASLR；每后端预热一次，八轮固定三后端正反序，每样本完整重启运行一次。24个正式样本全部在attempt0通过功能及placement门，没有删除或重试；CPU288 sibling的记录均为100% idle。编译、PMU和计数诊断与正式测量串行。

| 后端 | 外部wall均值 | 仿真循环均值 | 初始化均值 | 平均模拟周期/秒 |
| --- | ---: | ---: | ---: | ---: |
| 基线 | 3.289869 s | 3.257527 s | 6.892 ms | 1,036,410 |
| 候选 | 3.277149 s | 3.243583 s | 6.842 ms | 1,040,853 |
| Verilator | 3.148770 s | 3.113176 s | 10.701 ms | 1,084,464 |

下列为`候选/对照 − 1`，负数更快，CI为配对bootstrap。

| 对照 | 外部wall变化与95% CI | 仿真循环变化与95% CI |
| --- | ---: | ---: |
| 基线 | **−0.385%，[−0.728%, −0.043%]** | −0.426%，[−0.746%, −0.128%] |
| Verilator | +4.078%，[+3.863%, +4.288%] | +4.190%，[+3.945%, +4.433%] |

候选7/8轮外部wall更快，仿真循环6/8轮更快。本轮基线/Verilator为1.04482倍，不能用不同历史轮次直接相减。[逐对数据](../../build/cv32e40p/mux-input-cache-v1/pairs.csv)、[统计汇总](../../build/cv32e40p/mux-input-cache-v1/summary.json)。候选发射1.992秒、编译17.360秒、链接1.086秒，单独记录在`logs/*.result.json`，不计入运行时间。

## 节省的计算及其占比

唯一命中是group33的`_op_41354` / root14891，结果`_val_28730`（value43365）：RTL的`int_controller_i`中断优先级选择。原条件锥true分支无私有操作、false分支有30个私有操作。

其局部条件和中间输入最终都来自group32的19位`_val_5926`（value42110）。生成代码只比较这一个输入，而非逐个比较局部派生值。缓存输出继续使用原5位结果slot。新缓存有4项固定容量的64位键存储和一个valid位，实际使用一个键；初始化和布局成本包含在正式测量内。

独立计数版本也通过完整trace。计数区间开始前已经初始化；此CoreMark没有外部中断，资格向量保持不变，因此此区间miss为零。这是该负载的性质，不是对任意中断负载的假设。

| 每模拟周期 | 基线 | 候选 |
| --- | ---: | ---: |
| 该条件锥实际执行 | 0.999986 | **0** |
| false分支与根mux的IR运算 | 30.999559 | **0** |
| 根结果变化检测 | 0.999986 | **0** |
| 新增精确键检查 | 0 | 0.999986 |
| 全部scalar变化检测 | 168.255312 | 167.255326 |
| 全部scalar结果变化 | 30.917438 | 30.917438 |

493项未受影响的逐值比较、结果变化、区域执行、其它conditional分支与译码探针一致。fixed-point仍约3轮/周期，直接activation OR仍为30.219621次/周期；总scalar检测减少量精确归属于这个根。IR操作计数不等于机器指令。[缓存归因](../../build/cv32e40p/mux-input-cache-v1/cache-attribution.json)、[原始诊断计数](../../build/cv32e40p/mux-input-cache-counts-v1/counts.json)。

每后端另做一次PMU统计，包含进程初始化，不用于配对walltime结论：

| 每模拟周期 | 基线 | 候选 | Verilator |
| --- | ---: | ---: | ---: |
| retired instructions | 10325.326 | **10276.327** | 9799.121 |
| host cycles | 3061.855 | 3050.222 | 2931.159 |
| branches | 465.027 | 465.027 | 568.442 |
| branch misses | 1.277 | 1.238 | 0.897 |

候选净少48.999条退休指令/周期，即0.475%；仍比Verilator多477.206条/周期，即4.870%。受影响batch2的静态指令反而8212→8221、字节39536→39563，新增guard使冷路径代码略大；栈操作数指令保持1836。收益来自热路径跳过计算，不能用静态代码体积推断是否生效，也不能把49条指令都解释成31个IR运算的固定换算。[PMU、静态机器码与对照](../../build/cv32e40p/mux-input-cache-v1/repair-analysis.json)。

## 剩余问题与XiangShan适用性

本次证明“输出持久化 + 完整输入依赖”可以安全补回部分区域内部复用。但规则只处理已有条件锥且结果已有独占slot的情形，固定预算下只覆盖一处。因此仍有167.255次scalar检测/周期，区域及通知次数没有下降，整机差距仍约4%。

结构扫描中，branch request/控制网络等其它较大持久结果锥常有十几个到二十几个边界输入。为少量运算逐项比较这么多键，可能重新引入合并前的开销；局部结果也不能直接在下次调用使用。下一步应分析怎样沿生产者的现有变化信息形成可共享的子区域触发条件，并同时保证输出有效性，而不是单纯扩大键数量或用运行频率挑选信号。本轮没有实现或测量这一步。

规则不依赖CV32E40P名称，XiangShan中稳定输入驱动的优先级/控制锥可能满足同样的证明。但该负载没有外部中断，不能把此处命中率或0.385%收益外推到XiangShan；本轮没有XiangShan跑分，也没有更改生产默认值。

## 复现

在node030仓库根执行，使用新输出目录：[runner](../../scripts/cv32e40p_mux_input_cache_compare.py)。

```bash
python3 scripts/cv32e40p_mux_input_cache_compare.py build \
  --tools build/cv32e40p/mux-input-cache-v1/native-frozen \
  --output build/cv32e40p/mux-input-cache-reproduce
python3 scripts/cv32e40p_mux_input_cache_compare.py verify --output build/cv32e40p/mux-input-cache-reproduce
python3 scripts/cv32e40p_mux_input_cache_compare.py measure --output build/cv32e40p/mux-input-cache-reproduce
PATH=/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin:$PATH \
  python3 scripts/cv32e40p_mux_input_cache_compare.py diagnose --output build/cv32e40p/mux-input-cache-reproduce
python3 scripts/cv32e40p_event_region_counts.py \
  --source build/cv32e40p/mux-input-cache-reproduce --backend grhsim_mux_input_cache \
  --output build/cv32e40p/mux-input-cache-counts-reproduce --detailed
python3 scripts/cv32e40p_mux_input_cache_analysis.py \
  --source build/cv32e40p/mux-input-cache-reproduce --counts build/cv32e40p/mux-input-cache-counts-reproduce
```

完整结果：[report.json](../../build/cv32e40p/mux-input-cache-v1/report.json)。本轮只保留这一份实验实现及证据，默认仍关闭。
