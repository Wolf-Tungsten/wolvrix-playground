# TNO0022：恢复共享区域内的稀疏译码缓存

本轮完成缓存与区域变换组合的第一项修复：**源值局部化、谓词交错排列后，仍按同一SSA源维护独立谓词槽的稀疏缓存。** 同源对照中，修复相对原共享区域版walltime降低2.73%；共享区域加本修复相对此前保留版降低4.45%。两项95% CI均低于零，8/8轮同方向。与同RTL Verilator的walltime倍率从本轮基线的1.09363降至1.04488。

候选保留为新的最佳实验配置；新规则及共享区域仍默认关闭，不改变生产默认值。本轮没有展开区域内部激活条件保留、消费者打包或predicate-set重试，也没有测试原始SV Verilator或XiangShan性能。

## 原因与实现

此前共享区域把`_val_176`（instruction低7位，opcode）变成group31内的局部值。原共享译码要求输入或持久源及连续Eq段，因此18个独立存储的opcode谓词退回每次执行比较。local one-hot方案又拒绝组内源，无法恢复该缓存。

新增[emitter规则](../../wolvrix/lib/emit/grhsim_cpp.cpp)与[功能说明](../../wolvrix/docs/emit/grhsim-shared-equality-families.md)：

- `shared_equality_families` / `WOLVRIX_GRHSIM_SHARED_EQUALITY_FAMILIES`默认关闭，父开关`shared_equality_decode=0`同时关闭它。
- 在同一纯compute区域内，按源SSA值收集16–256个不同常量的Eq；域宽仍为2–12。每个结果必须拥有独立canonical bool槽，排除事件、直接状态视图和复用槽。
- 内部源的定义必须早于首个谓词。缓存维护放在**首个谓词处**，在源已计算之后；整个区域不得跨越副作用、透明存储、memory操作或reg-to-mem intent。
- 初始化计算所有结果；以后源不变便复用，源改变时只清旧地址对应槽、置新地址对应槽。使用原逐值变化/通知逻辑，消费者和其它操作保持原执行位置。

本规则不新增one-hot表，不恢复已删除的activity边界，也没有CV32信号名或性能profile特判。仅增加一个previous/valid缓存；候选中的209个checked values、39个supernodes、原scalar槽数量和conditional-mux位置均与共享区域控制相同。

真实命中只有一组18个谓词。生成的源临时值在`sched_1.cpp:924`，缓存维护紧接在925行。输入图、归一化图、成员及顺序保持一致；关闭规则时，当前保留版和原共享区域版的生成源码均逐文件复现。[结构检查](../../build/cv32e40p/equality-families-v1/structure.json)。

## 固定对照及功能门

| 后端 | binary SHA前缀 | 配置 |
| --- | --- | --- |
| 此前保留版 | `c7b8546489ba` | 单终点区域 + 条件求值 |
| 原共享区域控制 | `86169e7dc3a9` | 保留版 + 共享区域，原首次使用顺序 |
| 修复版 | `ac8a4dbdc7b2` | 共享区域控制 + 语义家族缓存 |
| Verilator | `539610699154` | 同一归一化RTL |

冻结GRH、固件、harness、native tools和编译器；两侧均使用Clang23.1.2、`-O3 -march=native -DNDEBUG -gline-tables-only`。布尔one-hot、slice-demand及已撤回的排序成本门均未启用。原共享区域控制直接复用此前binary，先核验新工具生成的feature-off源码与其相同。[输入身份与构建命令](../../build/cv32e40p/equality-families-v1/build.json)。

四后端均通过253周期smoke及3,376,065周期CoreMark。CRC、UART、退出码和每周期有效总线trace一致，CoreMark trace SHA仍为`ed2b490886767aa74524a6dd15e708e8f2b231bc3886814af0ba4d1919b3e098`。[完整功能证据](../../build/cv32e40p/equality-families-v1/functional.json)。

新增CTest包含交错消费者、同域局部源随寄存器变化、两源交错、重复/未匹配地址、输入存储高位、重初始化、时钟保持时输入变化；检查小家族、重复常量及effect区域回退。还覆盖父开关、环境优先级、split、fullpass、共享通知和conditional-mux组合。Clang O0/O3、ASan/UBSan全部通过，原有shared/local equality CTest也通过。

单测开发中修正了fixture临时对象寿命、spare storage bits的oracle预期，以及planner调用前过早清除环境变量的问题。失败日志与最终测试源码均归档；**这些修正没有改变候选emitter源码或binary，也没有产生新的性能候选**。[最终单测日志](../../build/cv32e40p/equality-families-v1/validation/equality-families-ctest4.log)、[验证归档](../../build/cv32e40p/equality-families-v1/validation/validation.json)。

## 8轮配对测量

node030、CPU96、NUMA1、单线程、关闭ASLR；每后端预热一次，随后固定8轮四后端正反序`ABCD/DCBA`，每样本完整运行一次。没有与编译、诊断或其它自己的测量并发。32个正式样本全部在attempt0通过功能和placement门，没有删样本、重试或追加跑分；CPU288在本组样本中的记录均为100% idle。

| 后端 | 外部wall均值 | 仿真循环均值 | 初始化均值 | 平均模拟周期/秒 |
| --- | ---: | ---: | ---: | ---: |
| 此前保留版 | 3.465175 s | 3.432986 s | 6.828 ms | 983,443 |
| 原共享区域控制 | 3.403756 s | 3.372461 s | 6.695 ms | 1,001,120 |
| 修复版 | 3.310856 s | 3.279172 s | 6.714 ms | 1,029,598 |
| Verilator | 3.168693 s | 3.132631 s | 10.757 ms | 1,077,781 |

下列均为`修复版/对照 − 1`，负值更快；CI为配对bootstrap，不能跨历史轮次相减。

| 对照 | 外部wall变化，95% CI | 仿真循环变化，95% CI |
| --- | ---: | ---: |
| 原共享区域控制 | **−2.727%，[−3.139%, −2.306%]** | −2.764%，[−3.174%, −2.348%] |
| 此前保留版 | **−4.452%，[−4.996%, −3.992%]** | −4.479%，[−5.020%, −4.021%] |
| Verilator | +4.488%，[+4.153%, +4.778%] | +4.680%，[+4.337%, +4.975%] |

2.73%是本次恢复缓存的收益；4.45%包含共享区域与条件求值组合，不能全部归给新增缓存规则。[逐对数据](../../build/cv32e40p/equality-families-v1/pairs.csv)、[统计汇总](../../build/cv32e40p/equality-families-v1/summary.json)。编译/链接耗时在`logs/*.result.json`单独记录，不计入运行walltime。

## 节省发生在哪里

另编译一份仅用于计数的诊断模型，验证同一完整trace；不使用其时间作性能结论。原共享控制计数来自SHA一致的既有binary。源SSA、value ID、group ID只在归一化图SHA相同时配对。

| 每模拟周期 | 原共享区域控制 | 修复版 |
| --- | ---: | ---: |
| 18个opcode谓词变化检测 | 17.999211 | **1.141998** |
| 这18个谓词的结果变化 | 1.141998 | 1.141998 |
| 新缓存访问/源检查 | — | 0.999956 |
| 新缓存源变化 | — | 0.570999 |
| 全部scalar变化检测 | 185.112525 | **168.255312** |

计时负载开始前已完成缓存初始化，因此该区间初始化次数为零。源改变时通常恰好清旧、置新两个匹配项；不变时不扫描18个旧结果。每周期省下16.857213次谓词检测，另外付出约一次源检查及变化时的分派。

285项区域执行、逐值变化、conditional-mux分支及fixed-point探针逐项一致；其它谓词的比较次数也完全一致。全部scalar检测减少量精确等于这18项减少量，未丢失变化通知、改变区域次数或通过少执行guest周期取得收益。固定点仍为低相位一轮、高相位两轮。[逐值归因](../../build/cv32e40p/equality-families-v1/family-attribution.json)。

## 机器码与剩余差距

每后端一次独立PMU统计，按相同guest周期归一化；包含进程初始化，不替代正式配对时间。

| 指标/模拟周期 | 原共享区域控制 | 修复版 | Verilator |
| --- | ---: | ---: | ---: |
| retired instructions | 10614.482 | **10325.326** | 9799.122 |
| host cycles | 3134.169 | 3073.620 | 2930.453 |
| branches | 456.466 | 465.027 | 568.442 |
| branch misses | 1.171 | 1.334 | 0.884 |

修复相对共享控制少289.155条退休指令/周期（2.724%）。受影响的batch1静态指令2330→2267，内存操作数指令947→870，栈操作数指令496→321，compare/test 382→325，cmov/setcc 459→369。稀疏分派增加分支，但避免了每次区域执行时18套比较/保存/通知相关临时计算。该源码改动同时改变Clang的局部寄存器分配，不能把289条差全部折算成某条IR比较的固定成本；静态栈指令也不是动态spill次数。[PMU及逐函数反汇编](../../build/cv32e40p/equality-families-v1/repair-analysis.json)。

当前修复版仍比Verilator多526.204条退休指令/周期（5.370%），正式walltime仍慢4.49%。剩余的168.255次scalar检测、区域调度和无关输入变化引起的区域内部计算没有被本规则消除。

本轮证明了此前负结果中的**缓存组合遗漏确实掩盖收益**。下一步应研究如何同时保留有价值的子区域触发条件和输出缓存，避免共享区域把低频计算提升为高频计算；不能仅跳过局部临时量的生产而让消费者读取未定义值，也不能据此重新采用已经失败的IR活跃距离成本门。局部消费者紧凑表示与predicate-set组合仍是未验证工作。

对XiangShan，这条规则也可用于同一纯区域内的窄CSR/enum判定，不依赖opcode名称；但不会跨分区或副作用边界维护共享缓存。本轮没有XiangShan性能数据，不外推本次2.73%的收益。

## 复现

在node030、仓库根执行，使用新目录；[runner](../../scripts/cv32e40p_equality_family_compare.py)复用已验证的placement与配对统计实现：

```bash
python3 scripts/cv32e40p_equality_family_compare.py build \
  --tools build/cv32e40p/equality-families-v1/native-frozen \
  --output build/cv32e40p/equality-families-reproduce
python3 scripts/cv32e40p_equality_family_compare.py verify --output build/cv32e40p/equality-families-reproduce
python3 scripts/cv32e40p_equality_family_compare.py measure --output build/cv32e40p/equality-families-reproduce
PATH=/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin:$PATH \
  python3 scripts/cv32e40p_equality_family_compare.py diagnose --output build/cv32e40p/equality-families-reproduce
python3 scripts/cv32e40p_event_region_counts.py \
  --source build/cv32e40p/equality-families-reproduce --backend grhsim_equality_families \
  --output build/cv32e40p/equality-families-counts-reproduce --detailed
python3 scripts/cv32e40p_equality_family_analysis.py \
  --source build/cv32e40p/equality-families-reproduce --counts build/cv32e40p/equality-families-counts-reproduce
```

候选只有这一份，无参数搜索或运行后挑选。全部产物：[report.json](../../build/cv32e40p/equality-families-v1/report.json)。
