# TNO0025：生产者出口通知聚合及剩余归约重复

## 结论

承接[TNO0024](./TNO0024_producer_change_cache_20261115.md)，实现了固定、默认关闭的生产者区域出口聚合。原来的两个缓存站点、依赖、存储和执行区域均不改变。相对逐源通知版，8轮配对外部walltime改善 **0.6568%**，95% CI **[−1.2429%, −0.0401%]**；但相对既有精确键缓存基线仍慢 **1.3620%**，CI **[+1.0503%, +1.6510%]**，8/8轮均慢于基线。因此不启用这个扩展，继续保留原基线。

聚合确实生效：每周期持久dirty赋值语句从37.7367次降至5.7381次，但新增/保留33.9985次局部OR，退休指令仅净减14.4307条。**源码中的dirty赋值次数不等于实际机器store次数**：旧版也已有一部分通知被Clang寄存器化。手工挪到出口主要改变写回位置，没有消除逐来源的归约工作。

进一步定位到可以继续研究的具体关系：两个新归约分别有20和14个来源，共享7个；现有一个调度归约包含这两组的全部来源，合计33个。当前只能复用完全相等的集合，因此仍生成两棵额外OR树。下一步应考虑把调度和缓存通知放进同一个精确集合分解计划，而非再追加独立谓词。这里仅完成离线定位，没有根据测量结果生成下一候选。

## 固定实现与输入

新选项`conditional_mux_change_grouped` / `WOLVRIX_GRHSIM_CONDITIONAL_MUX_CHANGE_GROUPED`默认off，要求原change-cache和conditional-mux父规则开启。规则按生产者supernode收集每个缓存的标量来源：

- 同一生产者至少两个来源指向同一缓存时，局部归约后在区域出口一次更新sticky dirty位。
- 完全相同的来源集合可在多个缓存间共享；与既有普通deferred predicate完全相等时直接复用。
- 同区域消费者保留即时通知，避免消费者先执行、出口才标脏。单来源、外部输入和state commit保留原路径。
- 不是经deferred activation上报的赋值路径使用单独fallback局部谓词，不能通过修改已有调度标志来补缓存通知。

不按信号名、profile、命中率挑选站点；没有改变5–32来源预算或做阈值搜索。功能说明和边界见[Wolvrix文档](../../wolvrix/docs/emit/grhsim-grouped-cache-notifications.md)。

当前CV32E40P只在producer31生成两组，20/14来源，各一个目标；均没有完全匹配已有谓词。原49个持久dirty赋值点变成17个，另有34个局部累积点。原两个change-cache和IRQ单键缓存不变。关闭新选项的源码与TNO0024逐源版本逐文件一致；normalized graph、checked values、slots、region membership及全部原条件锥一致。[结构检查](../../build/cv32e40p/grouped-notify-cache-v1/structure.json)、[源码语句统计](../../build/cv32e40p/grouped-notify-cache-v1/notification-source-shape.json)。

| 后端 | binary SHA-256 |
| --- | --- |
| 既有精确键缓存基线 | `600e92ca3a1dd83660d1aaa4341f5de9038b6529a528fbfefe0746c7cd98d98d` |
| TNO0024逐源通知 | `fb860a8df06b779a0f8b8e92740da4d1928a79422cbee1d282fcc27481c38e0a` |
| 本轮出口聚合 | `0a2fbabc4590f8c2e1dba0ae01df256339e80581de8e1304f8c35c0438d72787` |
| 同归一化RTL Verilator | `5396106991546a7aa0da975a44e9b92c21988bf6a4d60d4755bdafa370be7614` |

输入、native tools和源码快照见[build.json](../../build/cv32e40p/grouped-notify-cache-v1/build.json)。生成模型在node030用Clang 23.1.2、`-O3 -march=native`编译，沿用同一CoreMark和harness。生产默认值未改变。

## 功能与测量

四后端smoke、CoreMark、UART和退出状态一致，CoreMark均为3,376,065周期，完整总线trace SHA-256为`ed2b490886767aa74524a6dd15e708e8f2b231bc3886814af0ba4d1919b3e098`。独立诊断版本也匹配完整trace。[功能证据](../../build/cv32e40p/grouped-notify-cache-v1/functional.json)。

node030 CPU96、NUMA1、ASLR关闭；四后端各预热一次，8轮正反序，每样本一个完整CoreMark。全部功能和placement/locality门通过，未重试、未删样本、未追加测量。

| 外部walltime | 均值 |
| --- | ---: |
| 既有基线 | 3.174389 s |
| 逐源通知 | 3.238850 s |
| 出口聚合 | 3.217555 s |
| Verilator | 3.044108 s |

聚合/逐源的仿真循环变化为−0.5668%，CI [−1.0722%, +0.0156%]，仍跨零；只有外部walltime CI刚好低于零，不将其夸大为强稳定收益。聚合/基线的循环变化为+1.3927%，CI [+1.0891%, +1.6813%]。

同轮聚合/Verilator为1.057052倍，CI [1.051693, 1.062962]；继续保留的基线/Verilator为 **1.042868倍**，CI [1.036618, 1.049144]。不把历史轮次相减，不把未采用候选的差距当作保留版差距。[逐轮数据](../../build/cv32e40p/grouped-notify-cache-v1/pairs.csv)、[统计汇总](../../build/cv32e40p/grouped-notify-cache-v1/summary.json)、[完整报告](../../build/cv32e40p/grouped-notify-cache-v1/report.json)。

## 成本到底改在哪里

| 每模拟周期，源码级诊断 | 逐源通知 | 出口聚合 |
| --- | ---: | ---: |
| 持久dirty赋值语句执行 | 37.736727 | 5.738130 |
| 其中通知谓词为true | 2.812091 | 2.803299 |
| 新局部OR累积 | 0 | 33.998510 |
| PC控制缓存miss | 0.220465 | 0.220465 |
| 分支地址缓存miss | 0.947699 | 0.947699 |
| IRQ精确键缓存miss | 0 | 0 |

持久赋值与局部OR分开计数，不能只报“少了约32次写回”而忽略新增局部工作。“通知谓词为true”不是dirty位实际0→1翻转次数，多个变化可以合并。516项消费者、比较、变化、区域、fixed-point、activation和译码计数完全一致；两个缓存的命中率仍为77.95%和5.23%，无隐藏的执行次数变化。[通知归因](../../build/cv32e40p/grouped-notify-cache-v1/notify-attribution.json)、[原始计数](../../build/cv32e40p/grouped-notify-counts-v1/counts.json)。

每后端一次独立PMU采集，包含初始化，不替代配对统计：

| 每模拟周期 | 既有基线 | 逐源通知 | 出口聚合 | Verilator |
| --- | ---: | ---: | ---: | ---: |
| retired instructions | 10276.327 | 10376.343 | 10361.913 | 9799.122 |
| host cycles | 3043.688 | 3129.943 | 3100.215 | 2928.602 |
| branches | 465.027 | 466.631 | 469.630 | 568.442 |
| branch misses | 1.243 | 1.279 | 1.261 | 0.894 |

聚合相对逐源只净省14.431条指令（0.139%）；相对基线仍多85.586条（0.833%）。两个缓存避开的IR工作没有增加，而逐来源维护依然存在，所以仍无法覆盖成本。

汇编进一步修正了对源码赋值的直觉：逐源版已经出现`orb %r8b, %r12b`这样的寄存器累积，并非每条`dirty |= changed`都变成一次内存RMW。聚合版出口可见`orb %r10b, 0x51(%rdi)`与`orb %dl, 0x52(%rdi)`，但新局部源行仍对应大量`orb`，还出现栈操作数。减少源码持久赋值不等于消灭归约机器工作。

相关compute batch1的静态指令数2334→2338、字节10771→10849、栈操作数指令363→365；既有基线为2267条指令、321条栈操作数。不能把这些静态数当作动态spill次数，也不能据此认定全部回退由spill导致。DWARF源行归因只作为形态证据，存在优化移动/合并限制。[PMU和机器码](../../build/cv32e40p/grouped-notify-cache-v1/repair-analysis.json)、[源行汇编归因](../../build/cv32e40p/grouped-notify-cache-v1/notification-machine/attribution.json)。

## 下一步的结构依据

生成源码恢复出的producer31来源集合显示：

- 新缓存归约A有20个来源，B有14个，共享7个，合集27个。
- 已有`grhsim_any_changed_31_1`涵盖A的全部20个并多13个，也涵盖B的全部14个并多19个；恢复出的总集合为33个。
- 直接复用这个总谓词会引入额外来源触发，不能保持当前精确miss行为。因此本轮不把它当作相等集合复用。

可以研究将公共7、A独有13、B独有7以及已有归约剩余6个来源联合分解，产出三个所需的精确结果。重点是让调度与缓存共享已经执行的归约，而非把两棵新OR树换个存放位置。实施前仍需用IR/planner核实完整来源与赋值路径；这里的集合来自已发射的谓词语句，不是收益预测。[来源集合与包含关系](../../build/cv32e40p/grouped-notify-cache-v1/group-source-overlap.json)。

这个方向同样可用于XiangShan多终点控制网络，但必须证明来源集合、跨区域顺序与持久输出有效性。没有运行XiangShan，也不外推当前收益。

## 回归与复现

4项相关CTest通过，包括独立双时钟、held-clock更新、重复初始化、精确deferred复用及默认/关闭/父规则/环境优先级，生成代码运行O0及O3 ASan/UBSan。15项Python测试通过，包括局部OR和持久赋值的分phase探针以及不得改变cache miss的检查。`py_compile`和两仓`git diff --check`通过。[验证归档](../../build/cv32e40p/grouped-notify-cache-v1/validation/checks.json)。预冻结覆盖测试发现并修正了Operation临时对象span生命周期问题；还收紧测试调度构造，使其确实包含独立共享生产者，未放宽生产规则。

在node030仓库根，用新目录复现：

```bash
python3 scripts/cv32e40p_grouped_notify_compare.py build \
  --tools build/cv32e40p/grouped-notify-cache-v1/native-frozen \
  --output build/cv32e40p/grouped-notify-reproduce
python3 scripts/cv32e40p_grouped_notify_compare.py verify --output build/cv32e40p/grouped-notify-reproduce
python3 scripts/cv32e40p_grouped_notify_compare.py measure --output build/cv32e40p/grouped-notify-reproduce
PATH=/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin:$PATH \
  python3 scripts/cv32e40p_grouped_notify_compare.py diagnose --output build/cv32e40p/grouped-notify-reproduce
python3 scripts/cv32e40p_event_region_counts.py \
  --source build/cv32e40p/grouped-notify-reproduce --backend grhsim_grouped_notify_cache \
  --output build/cv32e40p/grouped-notify-counts-reproduce --detailed
python3 scripts/cv32e40p_grouped_notify_analysis.py \
  --source build/cv32e40p/grouped-notify-reproduce --counts build/cv32e40p/grouped-notify-counts-reproduce
python3 build/cv32e40p/grouped-notify-cache-v1/notification-machine-analysis.py \
  --source build/cv32e40p/grouped-notify-reproduce
```

本轮实现及证据留在当前调查分支，未更改生产默认值、未提交或push；聚合和底层change-cache均保持关闭。
