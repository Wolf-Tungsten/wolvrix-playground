# TNO0014：事件尾部区域与按首次使用排列

## 结果

已在 Wolvrix `activity-schedule` 实现默认关闭的 `eventRegions` 路径：合并只服务同一个 register commit 事件的纯组合尾部区域，并在新区域内按首次使用展开依赖，减少中间值缓存和过长的局部值存活期。

同一冻结归一化 RTL/IR、CoreMark 和编译器下，node030 CPU96、NUMA1、ASLR 关闭，8 轮 ABC/CBA 对照得到：

| 后端 | 外部 wall 均值 | 仿真循环均值 | 相对归一化 Verilator 的配对 wall 倍率 |
| --- | ---: | ---: | ---: |
| GrhSIM 原基线 | 4.475617 s | 4.442504 s | 1.40562，CI [1.39854, 1.41162] |
| GrhSIM 事件区域 + 首次使用顺序 | 3.640804 s | 3.608087 s | **1.14343，CI [1.13761, 1.14916]** |
| 同一归一化 RTL Verilator | 3.184151 s | 3.148192 s | 1 |

候选/基线 wall 比率为 **0.81348**，95% paired bootstrap CI **[0.81059, 0.81646]**，即 walltime 降低 **18.65%**，CI 对应 **[18.35%, 18.94%]** 的改善。仿真循环降低 **18.78%**。8/8 轮均改善，无样本剔除或 placement 重试。CPU288 sibling 在24个正式样本记录中均为100% idle。

三侧 smoke 和完整 CoreMark 的周期、UART/CRC、退出码、逐周期总线 trace 完全一致：smoke 253 cycles，CoreMark 3,376,065 cycles，CoreMark trace SHA `ed2b490886767aa74524a6dd15e708e8f2b231bc3886814af0ba4d1919b3e098`。本轮不研究或重测原始 SV 与转换后 RTL 的差异。

## 实现与语义边界

实现位于 [activity_schedule.cpp](../../wolvrix/lib/transform/activity_schedule.cpp)，开关为 C++ `ActivityScheduleOptions::eventRegions`、pass `-event-regions true`、Python `event_regions=True`。功能说明见 [activity-event-regions.md](../../wolvrix/docs/transform/activity-event-regions.md)。

规则由图结构决定，没有使用 CV32 信号名、profile 热点或性能结果选 region：

1. 从 commit 事件及 public output/event/effect 屏障向前传播终点分类。只有全部最终用途均属于一个同质寄存器 commit 组的完整纯组合尾部，才可合并。
2. 保留 memory/latch read、reg-to-mem intent、非 Logic 及副作用屏障；有可观测 compute effect 的原始组整体保护。只合并跨越多个旧 supernode、总 op 数不超过固定8192上限的完整区域。
3. 合并区域内部的 wire 使用局部值；输出给 commit 或区域外的结果继续物化。区域入口仍由现有 activity 机制触发，没有增加一个无条件全电路执行路径。
4. 所有 compute 仍先于 commit，保留旧状态快照、原始 commit 操作及组间顺序；重建 DAG、value fanout 和状态读者集合，并验证 scheduled op 集完全不变。
5. 新区域从外部使用的结果回追，在首次使用前生成纯依赖；共享 producer 只生成一次。未改变的 compute 组保留原 op 顺序。

此次形成2个 region，覆盖1,505个 compute node、4,875个 op。最终图 JSON 与原基线逐字节一致；关闭模式在新 native tools 上逐文件复现原基线所有生成 C++/header。因此正式对照没有混入前端、图优化、负载或编译选项变化。

| 生成结构 | 原基线 | 最终候选 |
| --- | ---: | ---: |
| 跨组 boundary values（含 commit 使用） | 1,276 | 698 |
| 持久标量 value slots，不含硬件状态/RAM | 1,282 | 704 |
| 有 scalar change check 的不同值 | 990 | 413 |
| scalar check 源码位置 | 1,698 | 791 |
| compute supernode / compute 函数 | 65 / 9 | 32 / 4 |
| commit supernode | 4 | 4 |

共享译码初始化、clear、set 可能在多处检查同一值，因此 check 源码位置和不同值数量分开报告。槽位减少45.09%，被跟踪值减少58.28%；这些静态指标不直接代表时间改善。

## 为何合并还必须配合区域内排列

初版只合并区域、沿用按拓扑层展开的顺序，功能全部通过，却在独立8轮对照中 **walltime 回退19.34%**（候选/基线 CI [1.18236, 1.20349]）。失败版本和逐轮数据保存在 [event-regions-v2](../../build/cv32e40p/event-regions-v2/report.json)，没有用修正版结果覆盖。

针对这一回退的诊断表明：

- 两个新 region 都只在高相位第二轮各执行1次/周期，并非同一周期反复整区重算。
- scalar 比较从约543.05次降到185.66次/周期，但 retired Host 指令只下降约2%；IPC 从3.19降到2.53。
- 新大 compute 函数占自身 profile 的74.27%，有3,751条静态 stack-operand 指令，超过旧基线选定模型函数合计2,194条。这里是含栈操作数的指令计数，不等同于精确 spill 次数。

这定位到区域融合后沿用层序排列的问题：许多独立中间值过早产生，随后长期同时存活。按首次使用展开是对这一具体代码生成问题的修正；本轮没有调整区域大小，也没有扫描多种分组参数。

| 同一大区域所在 batch | 初版层序 | 最终首次使用顺序 |
| --- | ---: | ---: |
| 局部值 def-to-last-use 距离总和，两个 region 合计 | 1,397,529 | 703,257 |
| 该函数机器码 bytes | 50,769 | 36,149 |
| 该函数静态指令 | 9,098 | 7,596 |
| 含栈操作数的静态指令 | 3,751 | 1,676 |
| 函数入口栈空间预留 | `0xe98` | `0x9b8` |

对照 [初版汇编](../../build/cv32e40p/event-regions-v2/region-batch3.s)、[最终汇编](../../build/cv32e40p/event-regions-v3/region-batch3.s) 和 [PMU诊断](../../build/cv32e40p/event-regions-v3/diagnostics.json)：

| 独立 PMU 样本，每 guest cycle | 原基线 | 初版层序 | 最终首次使用顺序 |
| --- | ---: | ---: | ---: |
| Host instructions | 13,104.52 | 12,838.80 | 11,130.08 |
| Host cycles | 4,110.13 | 5,067.21 | 3,364.56 |
| Branches | 599.61 | 448.87 | 471.67 |
| IPC | 3.188 | 2.534 | 3.308 |

最终 retired 指令减少15.07%，IPC也恢复并略高于基线，与正式配对改善方向一致。PMU为独立运行的诊断样本，不用它重算配对CI或精确分解耗时。初版逐相位计数只用于定位初版回退，没有把其插桩时间作为性能数据，也未把其动态计数冒充最终版测量。

## 验证、默认值和 XiangShan

新增 [emit-grhsim-event-regions](../../wolvrix/tests/emit/test_emit_grhsim_event_regions.cpp) 测试，用独立参考计算覆盖双时钟、门控 latch、异步复位、持续变化的外部输入、public 组合输出和交叉寄存器旧值依赖。默认/off生成结果一致，off/on模型均通过Clang23 O0、O3+ASan/UBSan。测试图的 boundary values 从45降到8。

完整 `transform-activity-schedule` CTest通过；18项相关Python分析/runner测试通过。Python pass参数转换的8项测试以AST加载纯Python函数方式运行通过；当前环境没有构建 `_wolvrix` native扩展，因此没有声称验证了完整Python native绑定。`py_compile`及两仓`git diff --check`通过。

全局默认仍为关闭。这是通用scheduler功能，已在CV32冻结配置上验证，不是按电路名写的特殊分支。XiangShan可复用同事件区域和首次使用排列的机制，但大区域可能超过8192-op上限而整体回退，memory intent、分区通信及副作用仍需保留；本轮未重建或测量XiangShan，不外推收益。

还存在约14.34%的 walltime 差距。这次已经把主要结构改动落实为可运行、可回退的实现，后续可以在此基础上研究共享/多终点区域，而不能据此取消所有 activity 或状态缓存。

## 冻结身份与复现

| 后端 | SHA256 |
| --- | --- |
| GrhSIM 基线 | `9642e07f8a0add9eaf1b0962005f60aadc5e4d6ce8382622de99489cb8860037` |
| 事件区域 + 首次使用顺序 | `792ffa67830d766fd5418bd967e41615090141f8faa7c4ac58c0d3fa2438ee65` |
| 归一化 Verilator | `5396106991546a7aa0da975a44e9b92c21988bf6a4d60d4755bdafa370be7614` |

使用相同Clang23.1.2、`-std=c++20 -O3 -march=native -DNDEBUG -gline-tables-only`。候选C++编译21.04秒、链接1.21秒，未计入仿真时间。新工具、源快照、补丁、graph和binary身份均归档。

在node030运行，输出目录必须不存在：

```sh
cmake --build build/cv32e40p/tools --target cv32e40p_emit -j12
python3 scripts/cv32e40p_event_regions_compare.py build --output build/cv32e40p/event-regions-reproduce
python3 scripts/cv32e40p_event_regions_compare.py verify --output build/cv32e40p/event-regions-reproduce
python3 scripts/cv32e40p_event_regions_compare.py measure --output build/cv32e40p/event-regions-reproduce
```

- [最终report](../../build/cv32e40p/event-regions-v3/report.json)、[功能与trace](../../build/cv32e40p/event-regions-v3/functional.json)、[逐轮CSV](../../build/cv32e40p/event-regions-v3/pairs.csv)、[策略与预热](../../build/cv32e40p/event-regions-v3/measurement-policy.json)
- [构建身份](../../build/cv32e40p/event-regions-v3/build.json)、[源码快照](../../build/cv32e40p/event-regions-v3/source-snapshot/manifest.json)、[生成结构](../../build/cv32e40p/event-regions-v3/structure.json)、[功能CTest日志](../../build/cv32e40p/event-regions-v3/validation/ctest-detail.log)
- [初版诊断计数](../../build/cv32e40p/event-regions-counts-v1/counts.json)、[初版perf](../../build/cv32e40p/event-regions-v2/region-perf.txt)、[最终PMU](../../build/cv32e40p/event-regions-v3/grhsim_event_regions-stat.csv)
- [对照runner](../../scripts/cv32e40p_event_regions_compare.py)、[逐轮次计数runner](../../scripts/cv32e40p_event_region_counts.py)

工作仍在 `thj/cv32e40p-grhsim-investigation-20261114`，本轮没有提交或push；已有未提交改动保留。
