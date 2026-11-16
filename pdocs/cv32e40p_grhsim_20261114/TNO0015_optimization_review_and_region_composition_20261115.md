# TNO0015：优化复审、区域与译码的组合，以及剩余结构差距

## 结论

本轮先复审已有优化，再对照事件区域版和**同一归一化 RTL**的 Verilator。没有重测或讨论 SV→V 转换造成的差距。

发现一个此前没有覆盖的组合问题：事件区域合并把一组171个 CSR 等值谓词从持久槽变成局部值，原来的共享译码缓存因要求持久槽而不再适用。CoreMark 中该源没有变化，但这些局部比较在源码中每周期重新计算。原先只统计 boundary change checks，会漏掉这种重复工作。

实现并验证了独立于 activity 边界的局部 one-hot 缓存。不过，**功能正确不等于生成代码更快**：一组8轮对照中它回退2.39%，因此保留为默认关闭的实验，不替代上一轮事件区域版。诊断证实缓存确实跳过了重复译码，但表访问和下游表达式的机器码成本抵消了收益。

当前保留的事件区域版仍比归一化 Verilator 慢约14%。后续主线应是**共享/多终点组合区域的边界与值表示**，并把译码及其消费表达式作为整体处理。不能仅按减少的比较数、缓存数或源代码行数选优化。

## 复审范围与修正

| 已有优化 | 本轮检查 | 仍存在的边界或不足 |
| --- | --- | --- |
| 寄存器堆 indexed concat/slice | 单一用途、源快照、跨word读取、alias/副作用保护 | 宽常量扩展此前已实测回退，继续关闭；不能只看宽数组声明判断成本 |
| packed scalar slices | canonical目标槽、源/目标不别名、bool布局与portable回退 | 只减少拆位存储成本，没有改变逐位跨组缓存的执行契约 |
| concat-slice coalescing | 同SSA、连续且同位序、cycle检查、signed/4-state测试 | 反序和重复位不能替换成原word；仍需word视图或局部计算 |
| shared equality decode | 首次初始化、old/new更新、重复/非法地址、exact通知与独立槽 | 与区域局部化不组合；源码谓词数、变化检测数、机器比较指令数必须分开 |
| event regions及首次使用顺序 | 旧状态快照、事件/副作用屏障、whole-node所有权、op集合不变 | 只合并单终点尾部；大型多用途控制锥仍停留在原活动组中 |

本轮没有复现这些既有生产路径的功能错误，但补齐了事件区域的负面测试：

- 有effect的原组保留完整成员和顺序，同时其它region确实形成，避免空测试。
- 8,300-op尾部超过固定上限后，组、fanout、topological order全部保持原样。
- 实际发生oversize compute-node splitting时明确拒绝；非法CLI布尔值明确拒绝。
- 原有双时钟、门控latch、异步复位、外部输入变化、交叉寄存器快照oracle继续通过O0/O3和ASan/UBSan。

另修正了[诊断脚本](../../scripts/cv32e40p_event_region_counts.py)的相位标记：原来`round`计数插在更新phase之前，会把高相位第二轮计入第一轮。现在先为即将执行的轮次标记phase，再计数。**旧产物的group计数正确，只有round分类有误**，不影响TNO0014对两个region各执行一次的判断。新增编译执行的oracle覆盖low、high round1/2/3+，以及局部缓存检查/更新和逐值计数。

## 当前事件区域版还在做什么

这里的审查基线是冻结binary `792ffa67830d766fd5418bd967e41615090141f8faa7c4ac58c0d3fa2438ee65`，不是区域合并前的`9642e07f…`。

新的[逐值、逐相位计数](../../build/cv32e40p/event-regions-review-counts-v2/counts.json)通过完整CoreMark trace。周期为3,376,065，trace SHA与Verilator一致。每周期仍为low一轮、high两轮；两个新region均在high第二轮各执行一次，未发生反复整区重算。

| 当前边界工作 | 数量或每guest cycle次数 |
| --- | ---: |
| 有变化检测的不同值 | 413 |
| scalar变化检测 | 185.6551 |
| 其中结果实际变化 | 37.1157 |
| 只为跨compute使用而检测的值 | 404 |
| 这404个值的变化检测 | 177.3213，全部检测的95.51% |
| 最大一类多终点用途集合的值 | 340 |
| 该集合的变化检测 | 128.4221 |

最大集合同时通向commit34、commit35和公共取指请求/地址输出。当前算法把“多个终点或公共输出”向前传播为屏障，相关纯组合逻辑因此不能进入单终点region；很多本可以位于一个共享组合执行区内部的wire仍承担存储、比较和传播责任。这说明剩余问题集中在**区域划分及其接口**，而不是缺少某一条按位OR指令优化。

ALU操作数`core$_11281_`是具体例子：TNO0013中的36个持久slice值已减到8个，检测从31.563降到7.481次/周期。剩余slice仍分布在组2/7，由组8/12/14/31消费，最终具有多个commit/output用途。归一化Verilator的对应[反序路径](../../build/cv32e40p/run2/verilator/VCv32Bench___024root__0.cpp:3286)直接从word产生局部表达式。继续缓存每个bit，与直接在共享组合区使用word视图的结构仍不同。

详见[边界及IR映射报告](../../build/cv32e40p/event-regions-review-v1/report.json)。报告中的终点集合是只读def-use归因，不代表可以跨越memory、event或effect屏障。

## 区域合并为何使一组共享译码退化

`_val_6162`是12-bit CSR地址选择结果，对应生成值42115。其171个等值比较原先为跨组持久结果；合并后全部位于region31，变为局部值。当前源码仍有171条直接比较这个源的表达式，例如[局部谓词](../../build/cv32e40p/event-regions-v3/grhsim_event_regions/grhsim_Cv32Bench_sched_3.cpp:503)。

逐值计数证明源42115在CoreMark计时区间内变化次数为0；region31执行约1次/周期。但共享译码旧规则要求每个结果具有独立canonical bool槽，因而不接受这些局部谓词。它们也不再进入`grhsim_changed_*`计数。因此185.655次/周期是**边界变化检测**，不能用来描述全部逻辑比较。

归一化Verilator仍保留[清旧地址、置新地址的one-hot表](../../build/cv32e40p/run2/verilator/VCv32Bench___024root__0.cpp:4299)，下游直接读表项。区别来自后端组织方式，不需要归因于不同RTL输入。

为验证此处能否转成收益，新增默认关闭的`local_equality_decode`：

- 一个纯compute组中，收集共享同一稳定源的16–256个局部等值谓词，不要求它们连续排列。
- 源必须是input或组外定义、独立拥有的canonical scalar槽；宽度2–12，拒绝event、alias、组内源和effects。
- 每组用一张`2^width`字节表，只在源变化时清旧地址、置新地址；原位置读表，不恢复activity边界。
- 保留非法高位的既有比较语义；超域地址无匹配；init清表；fullpass复用相同不变量。

机制与限制见[功能文档](../../wolvrix/docs/emit/grhsim-local-equality-decode.md)。没有按CV32信号名或profile选择规则。固定规则匹配两组：region31的171谓词，以及组15的23个局部谓词，合计新增8,192字节表和16字节previous字段。**value slots数量不包含这些memoization字段。**

## 单次对照的负结果

node030 CPU96、NUMA1、ASLR关闭，Clang23.1.2，同一CoreMark、归一化图、调度和编译选项。每侧一次预热，随后8轮ABC/CBA；三侧smoke/CoreMark的周期、CRC/UART、退出码和完整bus trace全部一致。新工具关闭此选项逐文件复现旧事件区域版源码。

| 后端 | wall均值 | simulation loop均值 |
| --- | ---: | ---: |
| 保留的事件区域版 | 3.655353 s | 3.623148 s |
| 局部译码缓存实验 | 3.742549 s | 3.710449 s |
| 归一化Verilator | 3.205239 s | 3.169147 s |

- 实验/事件区域版wall倍率：**1.023878**，95% paired bootstrap CI **[1.018303, 1.028365]**；8/8轮变慢。
- 事件区域版/Verilator：**1.140473**，CI **[1.134289, 1.148188]**。
- 实验/Verilator：1.167643，CI [1.163386, 1.171201]。

因此不采纳实验作为更快配置；`local_equality_decode`全局默认仍为false，事件区域版仍为当前保留结果。没有追加参数扫描或另选子集复测。`local-decode-v1`仅完成早期功能验证；单元测试发现通用端口名`address`会被临时变量遮蔽，修正命名后重新生成v2，正式性能样本全部来自v2。

## 为什么省去重复译码仍然更慢

[缓存动态计数](../../build/cv32e40p/local-decode-v2/diagnostics.json)确认实现按设计工作：

- 171谓词组每周期源检查1次，表更新0次。
- 23谓词组每周期源检查0.78952次、更新0.78628次；该源几乎每次进入组都会变化。
- 两侧boundary检测和变化总数完全一致，仍是185.6551/37.1157次/周期。

但这条规则只替换了谓词产生方式，仍让下游逐个读取、归一化和组合谓词。小家族也建立了自己的表，而其它组对同一源保留原有稀疏缓存。它没有把整个多输出译码及其消费网络合成一份紧凑控制结果。

| 大计算函数`eval_compute_batch_3` | 事件区域版 | 局部缓存实验 |
| --- | ---: | ---: |
| 机器码bytes | 36,149 | 37,234 |
| 静态指令 | 7,596 | 7,781 |
| compare/test指令 | 847 | 807 |
| 带内存操作数的指令，同一反汇编口径 | 2,796 | 2,939 |
| 带栈操作数的指令 | 1,676 | 1,756 |

逻辑比较减少，机器比较/测试只净少40条，其它指令反而增加185条。表项读取不能视为免费替代寄存器中的常量比较；已有Clang优化、布尔结果表示和局部值生命周期共同决定最终成本。静态栈操作数并不是动态spill次数，不能把80条差值直接换算为时间。

一次独立PMU对照中，Host指令/guest cycle从**11,130.083升到11,317.478（+1.684%）**，Host cycles从3,355.294升到3,433.679（+2.336%）；IPC从3.317到3.296。方向与正式配对回退一致。这证明此次实现的净机器工作没有减少，但不声称已经分离每项load、spill或branch的因果贡献。

保留版的新profile把约57.89%的样本归到大compute函数；该组含4,810个IR op，包括669个mux、519个concat和350个Eq。mux helper、CSR宽拼接及ALU位变换仍出现在热点行。插桩/采样只用于自身binary定位，**不把不同运行的profile百分比相减来解释性能差值**，也不把IR op数当退休指令数。

## 后续结构方向

1. **共享/多终点组合区域。** 维护明确的输入与外部可见输出集合，把共享纯组合锥内部的wire也局部化；事件检测、公开输出的及时可见性、旧状态快照和commit顺序仍独立保留。不能简单删掉“多终点屏障”或扩大8192上限；需要防止quotient-DAG环、额外重算和大范围live range。
2. **译码与消费网络一起处理。** 评估同一源的一组判定最终用于哪些OR/mux/控制字段，尽可能输出紧凑control word或共享decision DAG。缓存寿命应由源与消费域决定，不应偶然依赖某个谓词是否有activity槽。本次负结果否定的是“每个局部谓词改成表项读取就能收回差距”，不是否定所有译码复用。
3. **控制需求和word表示。** 在安全的纯组合区域内分析mux未选分支和位变换；先区分真实机器工作与已被Clang消掉的宽临时量。把helper改成`?:`本身不能让已经求值的操作数变成惰性计算。这里仍是后续方向，本轮没有追加候选。

这些机制也可能用于XiangShan的共享控制锥、窄CSR/enum译码和word拆位路径，但不能跨分区通信、memory intent和effects。大设计还需限制累计缓存容量和区域live range。本轮未重建或测试XiangShan，不外推收益。

## 验证与产物

- 3项相关CTest通过：事件区域边界/独立oracle、新局部译码、原共享译码；生成模型覆盖Clang O0/O3和ASan/UBSan。
- 20项相关Python测试通过，包含轮次标记、缓存计数、动态backend命名与倍率方向；`py_compile`及两仓`git diff --check`通过。
- [审查报告与完整边界明细](../../build/cv32e40p/event-regions-review-v1/report.json)、[审查基线profile](../../build/cv32e40p/event-regions-v3/review-perf.txt)、[源码行采样](../../build/cv32e40p/event-regions-v3/review-lines.txt)。
- [正式实验report](../../build/cv32e40p/local-decode-v2/report.json)、[配对CSV](../../build/cv32e40p/local-decode-v2/pairs.csv)、[功能trace](../../build/cv32e40p/local-decode-v2/functional.json)、[机器码/PMU/缓存报告](../../build/cv32e40p/local-decode-v2/diagnostics.json)。
- [保留版汇编](../../build/cv32e40p/local-decode-v2/grhsim_event_regions-batch3.s)、[实验汇编](../../build/cv32e40p/local-decode-v2/grhsim_local_decode-batch3.s)、[测试日志索引](../../build/cv32e40p/event-regions-review-v1/validation.json)。

冻结binary：保留版`792ffa67…`，实验`10acf7d6fb6271072c2a9d7552f546afc1626c9fa017bf50e38c567807f1abe4`，Verilator`53961069…`。完整SHA、源码快照、native工具、编译选项均见[build.json](../../build/cv32e40p/local-decode-v2/build.json)。

复现时使用新目录，构建/功能/测量阶段在node030执行：

```sh
python3 scripts/cv32e40p_local_decode_compare.py build --output build/cv32e40p/local-decode-reproduce
python3 scripts/cv32e40p_local_decode_compare.py verify --output build/cv32e40p/local-decode-reproduce
python3 scripts/cv32e40p_local_decode_compare.py measure --output build/cv32e40p/local-decode-reproduce
python3 scripts/cv32e40p_event_region_counts.py --source build/cv32e40p/local-decode-reproduce --backend grhsim_local_decode --output build/cv32e40p/local-decode-reproduce-counts --detailed
```

[边界分析器](../../scripts/cv32e40p_event_region_review.py)核对binary、生成源码、IR映射、counter集合及逐值/aggregate和；[机器码诊断汇总](../../scripts/cv32e40p_local_decode_diagnostics.py)消费已采集的perf/counter产物，不启动性能运行。

本轮改动仍在现有调查分支，未提交或push。
