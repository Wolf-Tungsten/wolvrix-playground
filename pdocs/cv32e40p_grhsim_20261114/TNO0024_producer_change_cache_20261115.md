# TNO0024：生产者变化驱动的子锥缓存——功能正确，但通知成本超过收益

## 结论

沿[TNO0023](./TNO0023_conditional_input_cache_20261115.md)提出的方向，实现了一个固定、默认关闭的规则：为已有条件锥的5–32个精确标量来源注册变化通知，用sticky dirty位代替每次逐项比较输入。原1–4键缓存保持不变。没有选择具体信号、根据跑分筛选锥、调整阈值或修改生产默认值。

node030 CPU96、NUMA1、ASLR关闭，三后端各预热一次，8轮正反序配对：候选相对固定基线外部walltime **+2.3247%**，95% paired bootstrap CI **[+1.5458%, +3.0710%]**，8/8轮更慢；仿真循环 **+2.3087%**，CI **[+1.5479%, +3.0506%]**。因此不启用该实验扩展，继续使用此前的精确键缓存基线。没有追加跑分或删去较慢样本。

问题并非缓存没有命中，而是通知路径恢复了过细的工作粒度：每模拟周期新增37.7367次dirty更新，只避免14.6113个私有锥IR运算。一个锥的输入通常稳定，另一个依赖频繁变化的取指/地址输入，后者几乎每次都需重算。即使采用已有变化谓词，写回dirty位仍是新增机器工作。

## 输入身份与实现边界

| 后端 | binary SHA-256 |
| --- | --- |
| 固定基线：原精确键缓存 | `600e92ca3a1dd83660d1aaa4341f5de9038b6529a528fbfefe0746c7cd98d98d` |
| 候选：额外变化通知缓存 | `fb860a8df06b779a0f8b8e92740da4d1928a79422cbee1d282fcc27481c38e0a` |
| 同归一化RTL Verilator | `5396106991546a7aa0da975a44e9b92c21988bf6a4d60d4755bdafa370be7614` |

同一冻结图、CoreMark镜像和harness；Clang 23.1.2，`-O3 -march=native`。候选在node030编译。关闭新开关时生成源码逐文件等于基线；开启后normalized graph、region membership、checked values、value slots、原条件锥和原精确键缓存站点全部不变。源码、native tools、编译命令和身份见[build.json](../../build/cv32e40p/change-trigger-cache-v1/build.json)、[structure.json](../../build/cv32e40p/change-trigger-cache-v1/structure.json)。

新开关为`conditional_mux_change_cache` / `WOLVRIX_GRHSIM_CONDITIONAL_MUX_CHANGE_CACHE`，默认off。仅处理原条件锥：完整依赖含selector和两侧分支，5–32个scalar来源，展开深度32、访问值上限256，根必须有独占持久slot。复用既有结果；不重新分区或持久化任意局部临时值。

失效通知区分三个时点：外部input变化；直接读取的寄存器实际提交；已物化的中间值/寄存器读取快照实际更新。最后一类不能只在更早的state commit标脏，否则缓存可能在快照更新前消费掉通知。状态/值别名、未跟踪变化的持久值、latch、reg-to-mem、fullpass及不能组合的lowering保守回退。`init()`标脏，计算后清除，通知在两次计算间累积。详见[功能文档](../../wolvrix/docs/emit/grhsim-conditional-mux-change-cache.md)。

## 功能与性能

三后端smoke和完整CoreMark均通过，CoreMark均为3,376,065周期、相同UART/退出状态和完整总线轨迹；trace SHA-256为`ed2b490886767aa74524a6dd15e708e8f2b231bc3886814af0ba4d1919b3e098`。全部正式样本通过placement/locality门；同原口径记录sibling活动，不干预其他用户。[功能证据](../../build/cv32e40p/change-trigger-cache-v1/functional.json)、[测量政策](../../build/cv32e40p/change-trigger-cache-v1/measurement-policy.json)。

| 外部walltime | 均值 |
| --- | ---: |
| 原精确键缓存基线 | 3.200396 s |
| 变化通知候选 | 3.274486 s |
| 归一化RTL Verilator | 3.064248 s |

候选/Verilator配对倍率1.068610，95% CI [1.064210, 1.073371]；同轮基线/Verilator为1.044451，CI [1.037765, 1.054509]。不从不同历史测量直接相减。本轮基线仍比该Verilator约慢4.45%，不采用候选后不应把差距写成6.86%。初始化耗时比值0.98592、CI跨1；主要回退在仿真循环，不能归因于启动。编译与链接时间单列在`logs/*.result.json`。[逐轮数据](../../build/cv32e40p/change-trigger-cache-v1/pairs.csv)、[完整报告](../../build/cv32e40p/change-trigger-cache-v1/report.json)。

## 缓存为什么生效却更慢

固定规则新增两个站点，均在group33、compute batch2。root13335对应`_op_37098` / `_val_25650`，映射到PC选择控制；root16429对应`_op_45948` / `_val_31842`，映射到取指分支地址选择。原IRQ单键缓存root14891保持原来的visits/misses。两处在此CoreMark计数区间均只走false arm。

| 每模拟周期 | PC选择控制：23来源 | 分支地址：26来源 |
| --- | ---: | ---: |
| 原执行/新guard访问 | 0.999986 | 0.999986 |
| 缓存后实际执行 | 0.220465 | 0.947699 |
| 命中率 | 77.95% | 5.23% |
| 原私有分支加根mux的IR运算 | 16.999758 | 25.999630 |
| 缓存后IR运算 | 3.747909 | 24.640171 |
| 新dirty更新语句执行 | 21.146088 | 16.590639 |
| 其中来源真正发生变化 | 0.311534 | 2.500557 |

两个锥合计少14.611309个IR运算和0.831807次根结果比较，但多了约2次guard和37.736727次通知更新。只有2.812091次通知对应来源真的变化；多数语句即使谓词false也执行`dirty |= changed`，或者重复更新已为true的dirty位。多个变化可合并成一次miss，所以通知变化次数不能当作消费者重算次数。49个静态通知站点列在[notification-sites.json](../../build/cv32e40p/change-trigger-cache-v1/notification-sites.json)。

分支地址锥的高miss不是实现漏掉缓存：基线逐值计数中，边界value42884每周期变化0.872542次、value42985变化0.146979次；它还依赖多个寄存器地址来源。保守的完整依赖发生变化就需重算，这个负载给它的复用空间很小。PC控制锥虽能复用约78%，仍要承担23来源的通知路径。此处只解释两个预先固定站点，不据此挑掉一个站点再跑分。

全部scalar检测从167.255326降到166.423519次/周期；全部scalar变化保持30.917438，直接activation OR保持30.219621，fixed-point保持约3轮。489项未受影响的逐值比较、变化、区域执行和译码计数一致。减少量完整归因于两根结果比较；没有偷偷减少区域工作或丢掉通知。[逐锥归因](../../build/cv32e40p/change-trigger-cache-v1/cache-attribution.json)、[原始诊断计数](../../build/cv32e40p/change-trigger-cache-counts-v1/counts.json)。

## 机器码证据与解释限度

每后端一次独立PMU采集，包含初始化，不用于替代8轮walltime结论：

| 每模拟周期 | 基线 | 候选 | Verilator |
| --- | ---: | ---: | ---: |
| retired instructions | 10276.327 | 10376.343 | 9799.122 |
| host cycles | 3052.065 | 3127.165 | 2932.100 |
| branches | 465.027 | 466.631 | 568.442 |
| branch misses | 1.244 | 1.228 | 0.893 |

候选净增100.016条退休指令/周期（+0.973%），不是“减少IR操作等价于减少机器指令”。源码通知对应的汇编可见`orb %cl, 0x51(%rdi)`，以及`orb 0x52(%r14), %dl`后`movb %dl, 0x52(%r14)`。这些是读取/更新同两个缓存位的额外路径，不是免费的现成activation。部分组提交能合成`movw $0x101, 0x51(%rdi)`，但普通生产者的通知仍散落在多个赋值之间。

DWARF把40/49个通知源行映射到89条静态指令，包括38条`orb`、21条`movb`；其余可能被合并或移动。这个89不能直接乘执行次数，更不能当成动态净增100条的逐条分解。batch2本身静态字节39563→39586、指令8221→8230，栈操作数1836→1833，不能据此声称发生了大量新spill。重复dirty更新带来的依赖/访存负担是有机器码支持的解释，但没有额外stall事件采样来量化其walltime占比。[机器码与PMU](../../build/cv32e40p/change-trigger-cache-v1/repair-analysis.json)、[通知源行汇编映射](../../build/cv32e40p/change-trigger-cache-v1/notifier-machine/line-attribution.json)。

结构性教训是：合并区域消除了中间通知，若再给每个源逐个追加消费者dirty通知，会重新支付细粒度调度成本。需要证明通知能在生产者区域出口聚合/共享，并与计算根本身的成本一起计价；只有缓存命中率不足以构成收益依据。当前Verilator对照不包含这轮新加的子锥通知机制，但本轮也不能将所有剩余指令差额都归因于它。后续应优先研究复用已有区域级变化信息，避免恢复逐信号扇出，而非继续扩大输入预算。没有在本轮实现或测量下一候选。

该规则不依赖CV32E40P命名。XiangShan也可能存在稳定控制锥，但更高扇出可能进一步放大重复通知成本；应先分析共享触发集合和输出有效性，不能外推本轮命中率。未运行XiangShan测量。

## 验证与复现

原conditional mux及精确键缓存CTest通过；新增change-cache测试在O0和O3 ASan/UBSan下通过，涵盖重复init、纯时钟变化、held-clock输入更新、无关区域激活、只读/可写状态与保守回退。13项Python测试通过，包括通知探针的逐phase独立C++ oracle和倍率方向。

新增持久输出fixture最初错误预期一定命中，实际该值没有跟踪变化的边界，规则正确回退。修正测试预期后通过，没有放宽生产规则。冻结binary之后仅完善了测试；最终测试文件及日志单独归档在[validation](../../build/cv32e40p/change-trigger-cache-v1/validation/checks.json)，保留了此前覆盖断言失败的日志，冻结的生产emitter源码未改变。

在node030仓库根执行，使用新输出目录：

```bash
python3 scripts/cv32e40p_change_trigger_cache_compare.py build \
  --tools build/cv32e40p/change-trigger-cache-v1/native-frozen \
  --output build/cv32e40p/change-trigger-cache-reproduce
python3 scripts/cv32e40p_change_trigger_cache_compare.py verify --output build/cv32e40p/change-trigger-cache-reproduce
python3 scripts/cv32e40p_change_trigger_cache_compare.py measure --output build/cv32e40p/change-trigger-cache-reproduce
PATH=/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin:$PATH \
  python3 scripts/cv32e40p_change_trigger_cache_compare.py diagnose --output build/cv32e40p/change-trigger-cache-reproduce
python3 scripts/cv32e40p_event_region_counts.py \
  --source build/cv32e40p/change-trigger-cache-reproduce --backend grhsim_change_trigger_cache \
  --output build/cv32e40p/change-trigger-cache-counts-reproduce --detailed
python3 scripts/cv32e40p_change_trigger_cache_analysis.py \
  --source build/cv32e40p/change-trigger-cache-reproduce --counts build/cv32e40p/change-trigger-cache-counts-reproduce
```

本轮只保留默认关闭的实验实现、回归和负结果证据；没有修改生产默认值、继续组合选优或提交/push仓库。
