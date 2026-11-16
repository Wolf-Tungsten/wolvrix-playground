# TNO0027：调度与缓存通知的精确集合联合分解

## 结果与约束

按[TNO0025](./TNO0025_grouped_cache_notifications_20261115.md)的静态结构证据，实现了调度与缓存通知的联合分解。候选在测量前冻结；没有把任何执行次数、缓存命中率、PMU或walltime输入生成器，也没有按结果选择站点、修改阈值、组合候选或启动下一轮搜索。

固定8轮配对中，相对上一版出口聚合，联合分解外部walltime **−0.5487%**，95% CI **[−0.6427%, −0.4505%]**，8/8轮更快；但相对既有精确键缓存基线仍慢 **0.8666%**，CI **[+0.5971%, +1.0947%]**，8/8轮更慢。本轮是实验实现与验证，默认开关始终关闭，没有依据测量结果自动切换生产配置。

这次减少的是实际重复归约：每模拟周期局部OR贡献（含目标重组）222.646→196.368，退休指令10361.913→10296.914，约少65条。缓存、消费者、dirty通知和调度行为520项一致，收益不是来自改变失效粒度或漏算。既有基线同轮为归一化RTL Verilator的 **1.042380倍**；实验候选为1.051397倍，仍未追平。

## 仅依赖图结构的规则

新选项`conditional_mux_change_joint` / `WOLVRIX_GRHSIM_CONDITIONAL_MUX_CHANGE_JOINT`默认off，要求已有grouped/change-cache/conditional-mux规则开启。输入是编译时来源集合与通知目标，不含运行数据。

对一个生产者区域，将普通deferred scheduler谓词和非重复的cache谓词视作目标。来源按“需要通知的完整目标集合”分成互不重叠的桶；每个来源只更新对应桶一次，出口用这些桶重组各目标。

例如scheduler需要`{a,b,c,d,e}`、cache需要`{a,b,c,d}`，先归约公共四项，再将`e`只合入scheduler。改变`e`不能增加cache miss。此处不能直接复用scheduler的超集标志。

静态成本门同时计入来源归约和桶到目标的重组：后者总贡献数必须严格少于原贡献数。固定上限为64目标、1024来源、64桶。精确来源集合、来源纯度、持久输出及别名证明沿用已有规则；同区域消费者仍即时通知。packed/direct deferred、已有shared cohort和strict overlay路径保留原lowering。非deferred赋值路径保留原fallback，不将其偷换成新的scheduler激活。[功能与安全边界](../../wolvrix/docs/emit/grhsim-joint-cache-notifications.md)。

CV32E40P命中producer31，目标为原3个scheduler谓词与2个cache谓词。它们的来源数131、33、9、20、14，总贡献207；140个不同来源分成14个桶，再做39次出口贡献，总成本179，静态减少28。三个scheduler谓词也有交集，因此最终是14桶，不是只分解先前看到的两个cache集合。所有站点由统一规则覆盖，未按名字或热度挑选。

构建阶段独立读取生成代码，重建分解前后的目标来源集合，确认每个目标精确相等、桶之间不重叠，并核对207/179计数；检查在编译和跑分前完成。[分解明细](../../build/cv32e40p/joint-notify-cache-v1/joint-partition.json)、[结构检查](../../build/cv32e40p/joint-notify-cache-v1/structure.json)。

## 冻结输入与测量

| 后端 | binary SHA-256 |
| --- | --- |
| 既有精确键缓存基线 | `600e92ca3a1dd83660d1aaa4341f5de9038b6529a528fbfefe0746c7cd98d98d` |
| 上一版出口聚合 | `0a2fbabc4590f8c2e1dba0ae01df256339e80581de8e1304f8c35c0438d72787` |
| 联合分解候选 | `0f5e03c9f84fb95318153b626dde0d8fef6b464744862298e213391db02f4dab` |
| 同归一化RTL Verilator | `5396106991546a7aa0da975a44e9b92c21988bf6a4d60d4755bdafa370be7614` |

同一冻结图、CoreMark和harness。Clang 23.1.2、`-O3 -march=native`，在node030编译。关闭joint选项时，生成源码逐文件等于上一版出口聚合；开启后graph、region membership、checked values、slots、条件锥、精确键缓存和change-cache站点均不变。来源、选项、工具及源码快照见[build.json](../../build/cv32e40p/joint-notify-cache-v1/build.json)。候选发射1.779秒、编译18.272秒、链接1.097秒，单独记录，不计入运行时间。

四后端smoke、完整CoreMark、UART、退出状态和总线trace一致；CoreMark均3,376,065周期，trace SHA-256为`ed2b490886767aa74524a6dd15e708e8f2b231bc3886814af0ba4d1919b3e098`。[功能证据](../../build/cv32e40p/joint-notify-cache-v1/functional.json)。

node030 CPU96、NUMA1、ASLR关闭，四后端各预热一次，8轮正反序，每样本完整重启一次CoreMark。全部功能和placement/locality门通过，无重试或删样本。sibling活动按原runner记录，不干预其他用户。

| 外部walltime | 均值 |
| --- | ---: |
| 既有基线 | 2.930450 s |
| 上一版出口聚合 | 2.972126 s |
| 联合分解 | 2.955813 s |
| Verilator | 2.811331 s |

联合分解/上一版的仿真循环变化−0.5193%，CI [−0.6239%, −0.4130%]；联合分解/基线为+0.8694%，CI [+0.6040%, +1.0981%]。初始化相对两版GrhSIM的CI均跨1，不能把循环回退归因于初始化。

联合分解/Verilator的配对倍率1.051397，CI [1.049943, 1.052613]；既有基线/Verilator为1.042380，CI [1.038991, 1.045816]。只比较本轮同口径配对，不对不同历史轮次的walltime做减法。[逐轮数据](../../build/cv32e40p/joint-notify-cache-v1/pairs.csv)、[汇总](../../build/cv32e40p/joint-notify-cache-v1/summary.json)、[完整报告](../../build/cv32e40p/joint-notify-cache-v1/report.json)。

## 减少了什么，为什么还未超过基线

为计入原scheduler归约和新的重组语句，两版各生成一次独立诊断binary。它们不参与正式walltime结论，均通过完整trace。下表是整个模型每模拟周期的源码OR贡献语句执行次数，不是机器指令数。

| 每模拟周期 | 出口聚合 | 联合分解 |
| --- | ---: | ---: |
| 普通scheduler局部归约/重组 | 188.647456 | 61.231839 |
| 新联合桶累积 | 0 | 123.136650 |
| cache局部归约/重组 | 33.998510 | 11.999474 |
| 上述局部贡献合计 | 222.645966 | 196.367963 |
| 持久dirty更新 | 5.738130 | 5.738130 |

真实执行少26.278003次OR贡献，而非简单把静态节省28乘周期数：存在条件路径，不是每个源码贡献每周期都执行。持久dirty更新及其谓词保持一致，没有用更宽的超集触发器换取少量代码。

两个控制锥的miss仍为0.220465和0.947699次/周期，IRQ单键miss仍为零；scalar检查166.423519、结果变化30.917438、activation OR 30.219621以及约3轮fixed-point均不变。520项计数一致，包含缓存访问、miss、消费者执行、逐值变化、dirty和调度；计数只用于验证这个冻结候选。[联合归因](../../build/cv32e40p/joint-notify-cache-v1/joint-attribution.json)、[旧版计数](../../build/cv32e40p/joint-notify-baseline-counts-v1/counts.json)、[候选计数](../../build/cv32e40p/joint-notify-counts-v1/counts.json)。

每后端一次独立PMU采样，包含初始化，作为机器执行证据而非替代8轮统计：

| 每模拟周期 | 既有基线 | 出口聚合 | 联合分解 | Verilator |
| --- | ---: | ---: | ---: | ---: |
| retired instructions | 10276.327 | 10361.913 | 10296.914 | 9799.122 |
| host cycles | 3034.743 | 3097.854 | 3087.162 | 2936.101 |
| branches | 465.027 | 469.630 | 469.766 | 568.442 |
| branch misses | 1.230 | 1.241 | 1.300 | 0.879 |

联合分解比出口聚合少64.9989条退休指令/周期（−0.6273%），比基线仍多20.5869条（+0.2003%）。新增cache有效性维护、guard、未共享的输入/state/同区域通知路径仍然存在；联合分解只消除了通知归约的重复，未消除这套机制的全部成本。

机器码支持“归约工作确实减少”，但不支持把时间变化完全等同于指令变化：compute batch1静态指令2338→2283，字节10849→10611；栈操作数指令365→386、访存操作数指令921→939，两版栈帧分配均`subq $0xb0, %rsp`。这说明编译器对更多局部谓词重新安排了寄存器/栈使用。不能把静态栈操作数当作动态spill次数，也没有足够事件采样量化它对walltime的贡献。

DWARF归因到归约源行的`orb`从227降到186；这些源行本身的栈操作数反而70→55，而整个batch的栈操作数增加，表明变化还影响到附近代码。只看新增OR树或单一行数会遗漏编译器的整体重排。[PMU和函数形态](../../build/cv32e40p/joint-notify-cache-v1/repair-analysis.json)、[源行汇编证据](../../build/cv32e40p/joint-notify-cache-v1/reduction-machine/attribution.json)。

这轮已经验证了结构方向，并划清其范围：共享来源的精确归约可以省指令，但不能自动证明增加子锥缓存整体划算。静态贡献门尚未建模谓词存活期、寄存器压力和完整缓存维护成本；这些是实现/成本模型的边界，不将本次数据变成新的热度阈值或自动筛选器。本轮没有再调整规则或挑选子集。

对XiangShan，集合分解机制不依赖CV32E40P名称，可能适用于多终点控制通知；仍需证明来源集合和跨区域顺序，也需考虑更多局部谓词的存活期。本轮没有XiangShan测量或性能外推。

## 测试与复现

5项相关CTest通过，生成代码在O0、O3 ASan/UBSan下运行；新增回归覆盖集合部分重叠、独立/同时钟边沿、held-clock更新和重新初始化，特别断言只改变scheduler独有来源不能增加cache miss。默认/关闭源码一致、环境优先级、父/分组关闭以及静态成本不降低时的回退均通过。

20项Python测试通过，包括从源码重建精确目标集合、拒绝把超集用于cache、计入出口重组成本，以及失效/消费者计数不能改变。`py_compile`、两仓`git diff --check`和文档链接检查通过。[验证归档](../../build/cv32e40p/joint-notify-cache-v1/validation/checks.json)。测量后生产源码、测试及runner仍与冻结快照一致。

在node030仓库根，用新目录复现同一固定规则：

```bash
python3 scripts/cv32e40p_joint_notify_compare.py build \
  --tools build/cv32e40p/joint-notify-cache-v1/native-frozen \
  --output build/cv32e40p/joint-notify-reproduce
python3 scripts/cv32e40p_joint_notify_compare.py verify --output build/cv32e40p/joint-notify-reproduce
python3 scripts/cv32e40p_joint_notify_compare.py measure --output build/cv32e40p/joint-notify-reproduce
PATH=/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin:$PATH \
  python3 scripts/cv32e40p_joint_notify_compare.py diagnose --output build/cv32e40p/joint-notify-reproduce
python3 scripts/cv32e40p_event_region_counts.py \
  --source build/cv32e40p/joint-notify-reproduce --backend grhsim_grouped_notify_cache \
  --output build/cv32e40p/joint-notify-baseline-counts-reproduce --detailed
python3 scripts/cv32e40p_event_region_counts.py \
  --source build/cv32e40p/joint-notify-reproduce --backend grhsim_joint_notify_cache \
  --output build/cv32e40p/joint-notify-counts-reproduce --detailed
python3 scripts/cv32e40p_joint_notify_analysis.py \
  --source build/cv32e40p/joint-notify-reproduce \
  --baseline-counts build/cv32e40p/joint-notify-baseline-counts-reproduce \
  --counts build/cv32e40p/joint-notify-counts-reproduce
python3 build/cv32e40p/joint-notify-cache-v1/reduction-machine-analysis.py \
  --source build/cv32e40p/joint-notify-reproduce
```

实现与报告留在当前调查分支；默认值不变，未提交或push。没有引入实际运行结果驱动的优化流程。
