# TNO0331: XiangShan residual giant separator audit

日期：2026-09-20

状态：`STRUCTURAL AUDIT PASS; SMALL FIFO SEPARATORS FOUND; NO NEW RUNTIME CLAIM`。

## 1. 范围与基线

承接 [TNO0323](./TNO0323_xiangshan_counter_print_asc_split_result_20260915.md) 的
counter-print 修改后残余 giant，以及
[TNO0330](./TNO0330_xiangshan_counter_print_node030_reserved96_plan_20260915.md) 的
all-spin 实现与性能验证。本轮执行用户选定的第一步：找出残余 392-memory ASC 内的
真实连接关系、单点/双点切口，并估算拆开后的工作量。没有修改 RTL、求解器或生产
runtime，没有运行新分区模型，不能据此声称 Host walltime 已改善。

输入沿用 `build/asc_counter_print_20260915/candidate_ingest_v1/xs_wolf.json`，
SHA-256 `16d4febf66cf3b1a38afe5c87e0d1fa973620600d2326eaaae6ca628ea1ab73c`。
隔离分析运行于 node030、CPU96–127；产物集中在 `build/asc_separator_20260920/`。
主仓库基线 `2cb0f0f`，Wolvrix `5f6bb8b`；分析器在旧只读 Phase A/B/C overlay 上增加导出，
没有执行 solver 或 Phase E 重建，没有改动 Wolvrix 工作树。

重新导入与分析精确复现：5,817,258 nodes、329,697 sinks、301,182 ASCs；目标 ASC 4
有 24,574 sinks、341,119 comb entries、883,100 full closure weight。
ASC 数字 ID 仅用于此次同输入查表。

## 2. 连接图与可信度

sink 是一次状态写入或有副作用的操作等计算终点；ASC 是当前 RepCut 认为必须放在同一
分区的 sink 集合。memory 的写端点，与组合逻辑中读取它的所有 sink，会形成共置关系。
多个 memory 被同一 sink 读取时，这些关系能够传递，最终合并成大 ASC。

本轮导出所有 sink→memory 读依赖，而非只导出并查集实际成功的合并边；同时保留同一
寄存器/latch 的多写端点以及有副作用操作结果的消费者约束。否则，已经合并后的冗余边
丢失会造成虚假的“桥”。全图导出 85,361 条 sink-memory incidence、18 条 effect-result
incidence；按全部约束重新构造后，301,182 个 ASC 的成员集合逐一完全一致。

分析中先把不可切的寄存器/latch/effect 约束收缩为 anchor（必须一起移动的 sink 小组），
再建立 anchor↔memory 二部图。目标图包含 24,568 anchors、392 memories 和 81,911 条
去重边；其中 24,562 个 anchor 含 1 个 sink，6 个含 2 个 sink。

| 结构指标 | 结果 | 含义 |
| --- | ---: | --- |
| memory 割点 | 204 | 删除此 memory 约束后图会断开，很多只分离叶子 sink |
| 能分开两组以上 memory 的单 memory 割点 | 49 | 更值得关注的单点切口 |
| anchor 割点 | 60 | 只作拓扑观察，未假设可以删除真实 sink |
| 桥 | 11,265 | 去掉一条关系即可断开，数量多不代表可均衡拆分 |
| 最大双连通块 | 327 memories、12,138 sinks | 此块不能只靠删除一个顶点拆开；不排除双点切口 |
| proper 双 memory 切口 | 41 | 两个点单独都不是割点，联合移除后分开至少两组 memory |

单顶点与单边检查覆盖完整目标图。双点检查对上述 proper 定义穷举，做了 188 次
Tarjan 分析；没有搜索三点以上切口，并排除了包含任一已有单割点的双点组合。
最大双连通块中的 memory 并非都无法分割；后文的双切口正是内部存在小分隔集的例子。

## 3. 最有代表性的切口

表内省略共同层级前缀 `cpu$l_soc$` 和尾缀 `$ram_ext$Memory`。删除的是分析图中的
memory 共置约束，memory 及其状态写操作在实际设计中仍必须保留；两边 memory 数不含
被选作切口的 1 或 2 个 memory，sink 则完整分配，无删除或漏计。

| 候选 | 切口 | 两侧 memory 数 | 两侧 sink 数 |
| --- | --- | ---: | ---: |
| `single_00` | `core_with_l2$l2top$inner_buffers_2$nodeIn_d_q` | 381 / 10 | 22,901 / 1,673 |
| `single_06` | `core_with_l2$l2top$inner_ptw_to_l2_buffer$nodeIn_d_q` | 390 / 1 | 24,261 / 313 |
| `pair_00` | `socMisc$buffers_1$nodeIn_d_q` + `socMisc$buffers_1$nodeOut_a_q` | 197 / 193 | 20,370 / 4,204 |
| `pair_04` | `socMisc$PeripheralXbar_to_MemXbar_buffer_0$nodeIn_d_q` + `...buffer_1$nodeOut_a_q` | 290 / 100 | 21,616 / 2,958 |

按最大 sink 数选取前 10 个有意义的单切口、前 10 个双切口进一步重算组合闭包。
这是结构筛选后的 20 个候选，不是对所有可能改写方案的全局最优证明。

## 4. 切口具体是什么

四个重点 memory 均是 TileLink 缓冲队列的两项存储体：

| 候选 | 深度 × 位宽 | 物理读口 / 写口 | 读结果影响的 sink 数 |
| --- | ---: | ---: | ---: |
| `single_00` | 2 × 80 bit | 1 / 1 | 1 |
| `single_06` | 2 × 281 bit | 1 / 1 | 1 |
| `pair_00` D 响应通道 | 2 × 275 bit | 1 / 1 | 189 |
| `pair_00` A 请求通道 | 2 × 359 bit | 1 / 1 | 1 |

这里的 189 是同一读结果经组合逻辑影响的终点数，绝不是 189 个 memory 读端口。
这些终点包括 181 个寄存器写、4 个 memory 写、2 个 SystemTask 和 2 个 DPI；其中仍有
`busPMU.latencyRecord_*` 与 BusPerfMonitor 断言。因此“已移除 PERF 打印对 next_counter
的集中依赖”并不意味着所有监控逻辑都脱离这个 ASC。

RTL 采用 `Memory[0:1]`，`posedge` 下非阻塞写，连续赋值读出；上层将读使能接常 1，
读地址接 dequeue 指针、写地址接 enqueue 指针，写使能为实际入队事件。对应默认
TLBuffer 为 depth=2、flow=false、pipe=false，没有本拍穿透的 FIFO 旁路。
`single_00` 唯一读消费者是下一层 `inner_buffers_3` 队列的写端点；`single_06` 则是
MemBlock 内 PTW 缓冲队列的写端点。两个 single 都是清楚的“一级队列→下一级队列”链。

可复查的源位置：

- `testcase/xiangshan/src/main/scala/xiangshan/L2Top.scala:149–150`：MMIO buffer 链；
  `:100` 与 `XSTile.scala:71`：PTW buffer 连接。
- `testcase/xiangshan/src/main/scala/system/SoC.scala:323`：`TLBuffer.chainNode(2)` 与
  `TLCacheCork` 的连接，对应 `socMisc.buffers_1`。
- `testcase/xiangshan/rocket-chip/src/main/scala/diplomacy/Parameters.scala:284–286`：
  默认缓冲参数；`tilelink/Buffer.scala:38–39`：A/D 通道队列。
- `build/asc_counter_print_20260915/candidate_v4/rtl/ram_2x{80,281,275,359}.sv`：
  第 71 行数组声明、第 74 行写、第 90 行读；实例连接见同目录的
  `Queue2_TLBundleD_31.sv:120`、`Queue2_TLBundleD_23.sv:120`、
  `Queue2_TLBundleD.sv:120`、`Queue2_TLBundleA.sv:122`。

存储位数不是 runtime 通信量。实际展开后的状态分配、复制路径及字节数，需要真实
重建才能统计；本轮没有将 2×位宽或 reader sink 数直接换算为通信代价。

## 5. 工作量重算与下一步

对每个候选的每个组件重新调用实际 `collectAscCone`，收集其组合前驱和操作 sink，
逐节点去重并调用 `calculateNodeWeight`。该模型根据操作种类、位宽和扇出赋予成本；
这里的“精确”指节点集合及现有成本模型的准确求和，不代表准确预测机器执行时间。
基线去重后为 365,684 nodes、883,100 weight，与原 full closure weight 完全一致。
每个候选都通过 sink 无重无漏，以及所有组件节点并集与原 ASC 节点集合完全相等的检查。

| 候选 | 两侧逐节点权重 | 最大权重下降 | 两侧权重总和 | 额外重复权重 / 基线 |
| --- | ---: | ---: | ---: | ---: |
| 原 ASC | 883,100 | — | 883,100 | — |
| `pair_00` | 642,462 / 256,815 | 27.249% | 899,277 | 16,177 / 1.832% |
| `pair_04` | 667,375 / 231,996 | 24.428% | 899,371 | 16,271 / 1.842% |
| `single_00` | 713,907 / 185,607 | 19.159% | 899,514 | 16,414 / 1.859% |
| `single_06` | 857,795 / 27,102 | 2.865% | 884,897 | 1,797 / 0.203% |

额外重复权重为“各组件闭包权重之和−原 ASC 闭包权重”。它假设各组件独立计算；实际
求解器可能将部分组件放回同一 partition，编译优化也会改变最终机器码。它不包含新状态
接口、额外 mux 等真实改写成本，更不是字节通信量。

重算还排除了一个测量陷阱：piece 是原图中有相同 ASC 归属的节点块，原 giant 的 piece
可能很大。若拆分后某组件只触碰其中一小部分，仍把旧 piece 整块记账，会严重高估。
例如 `pair_00` 按旧整块口径得到两侧 736,243 / 716,953，而逐节点实际只有
642,462 / 256,815。正式结论采用后者；schema 2 中前者明确标为 `frozen_piece_*`，
仅供核对。原基线的 piece 权重本身没有问题，问题在于假想拆分后没有相应细分旧 piece。

`pair_00` 只重复 7,924 个组合节点，相对基线 341,119 comb entries 为 2.323%，
并非大部分逻辑都必须复制。两侧 memory 数接近一半，但成本为约 2.5:1，说明不能用
memory 数量衡量计算均衡。最大双连通块也并不意味着所有 327 个 memory 都拆不开；
它只排除了单顶点切割。

建议下一步做有明确目标的少量 memory 展开：

1. 先用 `single_00` 的 2×80 bit 队列验证机制：将两行数组改为两个寄存器，读端改为
   按地址选择的 mux；保持时钟、队列深度、写使能和读旧状态的时序。
2. 同一机制再应用到 `pair_00` 的 A/D 两个队列，检验最大 ASC 的实际下降。
   从本次候选的收益/重复比例看，双切口是更有吸引力的性能候选。
3. 实际重建后再核算新最大 ASC、partition 负载、复制字节，完成功能检查后，以 node030
   CPU96–127、N=K=32、all-spin 下的交错 Host walltime 作为最终裁决。

代码已有 `wolvrix/lib/transform/mem_to_reg.cpp` 的逐行寄存器化实现，可作为实现基础。
当前选项主要按 `rowLimit` 控制，没有按具体 memory symbol 的白名单；下一轮应限定到
选定队列，避免一开始同时改动全图小 memory。还需核对初始化、mask 和 X 语义，不能仅
去掉共置约束、让两个 partition 无序读写同一个 memory。两个 `pair_00` 队列的读数据还
影响监控与断言，功能检查需要保留这些事件。

以上仍是下一步建议。本轮只完成结构分析，没有实施寄存器化或产生新的运行时间样本。

## 6. 产物与验证

本议题集中记录在这一篇文档中。相对 `build/asc_separator_20260920/` 的主要产物：

- `capture_node030_v1/run.json`：输入身份与完整基线复现。
- `capture_node030_v1/capture/sink_memory_cone.tsv`：完整 memory 读关联；SHA-256
  `3c39e9229cffc3a0086e30865b1502eaed1fa37e6de496d9a7daaa3df3840d0a`。
- `separator_audit_v2.json`：全 ASC 成员重建核验、图结构、候选、读写关联计数。
- `refinement_requests_v1.tsv`：20 个候选的完整 sink→组件分配；491,480 条数据行。
- `metric_node030_v2/run.json`、`metric_node030_v2/metric/{summary.json,component_closure.tsv}`：
  正式逐节点权重、旧 piece 对照值与全部 20 个候选的核验结果，status=pass。
- `metric_overlay_v2/build.json`：隔离库构建记录，库 SHA-256
  `db8f40495118b72ba60c8be4a0775b56593afc60f31449c267861761a67821b0`。
- `prepare_capture_overlay.py`、`analyze_separator.py`、`prepare_metric_overlay.py`、
  `run_capture.py`、`run_metric.py`：隔离工具与可复现入口。

图算法自测覆盖链、环、超边形态、单割点/桥快速统计与逐个删除后的 BFS 对照、双点切口。
实际全图的全部 ASC 成员精确复现，以及 20 个候选逐节点并集与基线完全相等，是本次
分析最重要的正确性核验；五个 Python 工具语法检查、隔离 C++ overlay 构建也通过。

## 7. 增量更新：single_00 选择性寄存器化（2026-09-20）

本节接续第 5 节的建议，更新此前“未实施寄存器化、未执行 solver”的阶段状态；前文保留
原始审计时点的结论。现已完成定点转换、结构复测与 K=32 分区/emit，尚无新运行时间结果。
XiangShan 源码和当前 all-spin runtime 的语义均未改变。

### 7.1 实现与隔离转换

在 Wolvrix 的 `mem-to-reg` pass 中新增 exact-symbol 白名单：C++ 参数为重复的
`-memory-symbol <symbol>`，Python 参数为 `memory_symbols=[...]`。筛选发生在收集读写端点
之前，未选 memory 不会付出完整引用扫描开销。默认不传白名单时行为不变。

目标为：

```text
cpu$l_soc$core_with_l2$l2top$inner_buffers_2$nodeIn_d_q$ram_ext$Memory
```

在 node030 CPU96–127 上对原始 `xs_wolf.json` 做隔离转换，输入 SHA 为
`16d4febf66cf3b1a38afe5c87e0d1fa973620600d2326eaaae6ca628ea1ab73c`。转换结果记录于
`build/asc_separator_20260920/targeted_single00_node030_v3/`，输出 SHA 为
`ddbcf518b0c7f8805c3c985e1cbf307be51d44d8c33a94614726ac88f2f0cb81`。pass 统计为：

```text
memory_total=4809 converted=1 regs_created=2 read_rewritten=1 write_rewritten=1
skipped_unselected=4808 skipped_row_limit=0 skipped_nonconst_mask=0 skipped_init=0
```

这确认当前实验只把目标 2×80 bit memory 改成两个行寄存器和地址选择读端，其他 memory
保持原状；`production_source_modified=false`。

### 7.2 结构复测

对转换后的 JSON 用同一 closure-aware Phase A/B/C 分析（未执行 solver、未生成模型）得到：

| 指标 | 原始基线 | single_00 转换后 | 变化 |
| --- | ---: | ---: | ---: |
| nodes | 5,817,258 | 5,817,274 | +16 |
| sinks | 329,697 | 329,698 | +1 |
| ASCs | 301,182 | 301,183 | +1 |
| 最大 ASC comb entries | 341,119 | 280,341 | −17.82% |
| 最大 ASC full closure weight | 883,100 | 713,917 | −19.16% |

目标 ASC 仍为 `asc_id=4`，最大 sink 数从 24,574 降为 22,902；拆出的第二个 ASC closure
为 185,637。最大 closure 的下降与
先前按逐节点模型估算的 `713,907` 基本一致（差异来自转换新增的少量节点和全图统计口径），
说明该切口确实消除了 memory 共置约束，而不是仅改变了统计脚本。

### 7.3 实际分区与静态通信

随后对转换后的完整图执行 closure-aware RepCut，使用 K=32、imbalance=0.015、
mt-kahypar quality、32 个 solver 线程，完成 Phase E 重建与生产 emit。
与 `build/asc_counter_host_20260915/B_v1/emit.json` 的 counter-print 基线比较：

| 指标 | 原始基线 | single_00 转换后 | 变化 |
| --- | ---: | ---: | ---: |
| 最大 partition exact closure weight | 883,100 | 713,917 | −19.158% |
| 全部 partition exact closure weight 总和 | 13,052,827 | 13,052,048 | −779 / −0.006% |
| 重建后最大 partition ops | 447,447 | 360,450 | −19.443% |
| 重建后全部 partition ops 总和 | 6,188,556 | 6,193,679 | +5,123 / +0.083% |

真实分区后，最大的负载依然恰好等于剩余最大 ASC 的闭包，说明这个不可再分块仍是
静态均衡的下界。全图闭包总量基本不变，重建后操作数仅小幅增加；不能把候选拆分时
局部闭包的重复比例，直接当成整个设计真实分区后的总工作量增幅。

以 `analyze_allspin_comparison.py` 的 `communication()` 对生成 wrapper 和 update 代码
逐条统计，基线为 `build/asc_counter_host_20260915/production_allspin_20260920/package`，
候选为本轮 `single00_emit_node030_v1/package`：

| 每步静态跨分区复制量 | 原始基线 | single_00 转换后 | 变化 |
| --- | ---: | ---: | ---: |
| 赋值/复制条数 | 4,836 | 5,751 | +915 / +18.921% |
| 逻辑位数 | 3,494,515 bit | 4,119,503 bit | +624,988 bit / +17.885% |
| Verilator 值存储复制字节数 | 441,866 B | 521,171 B | +79,305 B / +17.948% |

此处按每个目的 partition 计扇出，标量按实际存储类型、宽向量按 32-bit word 对齐计字节；
不包含顶层 IO，也不是 PMU 测得的内存总线流量或 cache-line 传输量。整个图重新求解后，
通信变化来自新的全局分区布局，不能全归因于这 160 bit 的队列状态。
以上权重、ops 和复制量都是静态指标，不能直接换算成 eval 时间、通信时间或 Host walltime。

### 7.4 代码验证与当前边界

Wolvrix 隔离构建通过，新增 CTest `transform-mem-to-reg-selection` 通过；测试同时覆盖
“只转换指定 memory”和“空白名单保持默认全转换”两种行为，`git diff --check` 通过。

当前结果仍是结构性正向信号，不等于仿真加速：K=32 RepCut 和 emit 已通过，32 个
Verilator model 的完整构建尚在进行，之后需用当前 all-spin runtime 做 C=100 功能门和
C=10000 交错 Host walltime。由于 stage4 的旧脚本带有冻结的 legacy runtime 支持文件，完整构建后还要
核对并接入当前 all-spin wrapper/runtime，不能直接把旧 stage4 二进制当作最终性能结果。

### 7.5 本次增量产物

以下路径相对 `build/asc_separator_20260920/`；仅列已成功的转换、分析和分区产物：

- `targeted_single00_node030_v3/{run.json,xs_wolf_mem_to_reg.json}`：single_00 选择性
  `mem-to-reg` 隔离转换及输出身份。
- `targeted_single00_node030_v3/analysis3/{run.json,analysis/summary.json}`：转换后
  Phase A/B/C 结构复测，status=pass。
- `single00_emit_node030_v1/run.json`：完整 solver 与 Phase E 统计，status=pass；
  同目录 `package/` 为此次 emit 的 wrapper/update 代码。
- `run_targeted_mem_to_reg.py`、`analyze_allspin_comparison.py`：定点转换与静态通信统计入口。

### 7.6 single_00 完整构建及六对交错结果

上述构建待验证状态现已推进为通过。`build_current_allspin.py` 直接使用新生成的 all-spin
package，只规范化 filelist 路径；全部 32 个 model archives、1,363 个 model objects
重新编译，未复用旧模型对象，也未注入旧 stage4 的 runtime 模板。构建约 206.31 s，
模型端口与 SV 对照、Clang 标记及 wrapper 编译参数检查通过。
新旧 common 调度源文件 SHA 完全一致：
`91a0f60c1150a60e335f91c8b64d8a378f5eea05ceb94354adee00e03de2b53b`；
外层 `partitioned_verilator.cpp` SHA 同为
`96ac7a309444d0838e87bf094aa36be24cb74a4dbc6411800c327c666bdade88`。

在 node030 CPU96–127、NUMA1、N=K=32、fixed-ASLR、默认 all-spin 下，先做双方 C=100
初始化检查，再执行六对交替 AB/BA 的 C=10000。A 为冻结生产 all-spin，B 为 single_00。
全部 12 次 C=10000 均启用 Difftest，功能签名一致：`pc=0x800027c6`、`instrCnt=458`、
`cycleCnt=9996`、guest cycles=10001、steps=20102；C=100 尚无指令退休，只作为初始化检查。

| 指标（六次各自中位数） | 原始 all-spin | single_00 | 配对变化中位数 |
| --- | ---: | ---: | ---: |
| Host time | 7.7665 s | 6.6285 s | −14.581% |
| 进程 walltime | 7.865 s | 6.730 s | −14.340% |
| 仿真 step 总时间 | 7.7064 s | 6.5495 s | −14.944% |
| input_load 阶段 | 11.838 µs/step | 12.147 µs/step | +2.615% |
| eval 阶段 | 300.287 µs/step | 190.333 µs/step | −36.646% |
| update 阶段 | 71.113 µs/step | 123.592 µs/step | +73.733% |
| 最大 partition eval | 295.288 µs/step | 182.823 µs/step | −38.098% |
| 全部 partition eval 之和 | 1832.123 µs/step | 1843.072 µs/step | +0.598% |
| 全部 partition update 之和 | 1104.434 µs/step | 1305.529 µs/step | +18.196% |

Host 六对全部改善，逐对变化为 −15.106% 至 −14.223%；AB 中位变化 −14.310%，BA
−14.654%。进程 walltime 六对也全部改善。表中的百分比是逐对比值中位数，不是两列中位数
直接相除，因此可能有小幅差异。

single_00 已经获得真实运行收益，同时也暴露出通信阶段的负载不均：最慢 eval 从旧
`part_7` 转为新 `part_4`（182.823 µs）；保有剩余最大静态 ASC 的新 `part_0` eval
为 166.714 µs。静态成本大小与运行时排序并不完全一致。最慢 update 从旧 `part_1`
60.245 µs 转为新 `part_16` 117.243 µs；后者承担 539 条跨分区目标复制、26,342 B/step。
全体 update 时间只增加约 18%，但阶段等待最慢线程，阶段耗时增加约 74%。这解释了
为什么约 110 µs 的 eval 阶段收益，有约 52 µs 被 update 阶段抵消。字节量、复制条数和
内存位置共同影响单线程耗时，不能把上述比例当作纯带宽因果证明。

成功产物相对 `build/asc_separator_20260920/`：

- `single00_build_node030_v1/build-manifest.json`：工具链、32 模型独立构建与对象检查。
- `single00_build_node030_v1/partitioned-emu/verilator-compile/emu`：SHA-256
  `3bc2658f99835c95825eff3d32696e0e73f7ad9fe1e909982c9b02b6facf5bbc`。
- `single00_interleave6_node030_v2/{manifest.json,summary.json,runs.csv,pairs.csv,parts.csv}`：
  成功的双方初始化检查与六对交错原始日志/统计。
- `run_allspin_comparison.py`、`analyze_allspin_comparison.py`：固定条件运行及逐次结果校验。

### 7.7 pair_00 实际改写的结构结果

第二候选从原始输入独立展开 `socMisc$buffers_1` 的 A/D 两个队列，未累积 single_00。
目标分别为 2×359 / 2×275 bit，均为单读单写、1-bit 地址和全 1 常量写 mask；共生成
四个行寄存器。single_00 的 2×80 bit memory 在这个候选中仍保持原样。

Phase A/B/C 全部检查通过，最大两侧 closure 为 642,580 / 256,951；最大值比原始
883,100 下降 27.236%，比 single_00 的 713,917 低 9.992%。两侧总和为 899,531，
相对原 ASC 增加 16,431（1.861%，含实际改写成本，不能全归为重复）。最大 comb entries
为 249,876，ASCs=301,183，sinks=329,699，nodes=5,817,290。

转换输出 SHA-256 为 `439dfa2c3f1e9ea8ece7ee8cc84d2f606102bc87523d59c063c19a19ec1577d6`，
成功记录在 `targeted_pair00_node030_v1/run.json` 与
`targeted_pair00_node030_v1/analysis/{run.json,analysis/summary.json}`。
此小节仅是 pair_00 的结构结果；其模型构建及 Host 时间还需后续实测。

两种实际改写的共同语义边界：三个目标均为一位地址、单异步读/单 posedge 写、全 1
常量写 mask，原 GRH 不含初始化属性或 fill 操作。原写数据、mask 和 eventEdge 保留，
仅按地址限定行寄存器写使能。现有 pass 的读 mux 默认值是零，因此不保证任意 X/Z
地址下的四态等价，也不保证重新启用随机存储初始化后的同 seed 位值一致；此次结论
限定当前二态、`EMU_RANDOMIZE=0` 配置。没有将全图小 memory 自动展开或改为默认管线。

### 7.8 pair_00 完整 K=32 分区

后续完整 solver、Phase E 和 emit 已通过，产物为 `pair00_emit_node030_v1/`。
最大 partition exact closure 保持 642,580；全部 partition closure 总和为
13,047,051（相对基线 −0.044%）。重建后最大 partition ops 为 321,862（−28.067%），
总 ops 为 6,193,109（+0.074%）。

| 每步静态跨分区复制量 | 原始基线 | pair_00 | 变化 |
| --- | ---: | ---: | ---: |
| 赋值/复制条数 | 4,836 | 6,181 | +27.812% |
| 逻辑位数 | 3,494,515 bit | 3,670,805 bit | +5.045% |
| Verilator 值存储复制字节数 | 441,866 B | 465,379 B | +23,513 B / +5.321% |

相比 single_00 的 521,171 B，pair_00 的字节量更低，但复制条数更多；最终 update
耗时仍需实测。共同 all-spin 调度源码 SHA 与 §7.6 一致，保持同一 runtime。
有效 assignment SHA 为 `dfbf647b8b141d9808def8c6ea81f4de91d4163430e38ca26263683554a59a3f`；
partitioned JSON SHA 为 `c9d0efd3c69b5f0d63f0e0a8a101df2034021a271df648e31c29d71901ac6c10`。

### 7.9 pair_00 完整构建及六对交错结果

沿用 §7.6 的 current all-spin 独立构建方式，32 个 model archives、1,373 个 model
objects 全量编译和链接通过（约 240.14 s），随后在同一 node030 CPU96–127、NUMA1、
N=K=32、fixed-ASLR 下完成双方 C=100 初始化检查及六对 AB/BA C=10000。
全部签名、Difftest、runtime 配置与退出状态检查通过，与 §7.6 的功能签名一致。

| 指标（六次各自中位数） | 同批原始 all-spin | pair_00 | 配对变化中位数 |
| --- | ---: | ---: | ---: |
| Host time | 7.7125 s | 5.7870 s | −24.893% |
| 进程 walltime | 7.815 s | 5.890 s | −24.568% |
| 仿真 step 总时间 | 7.6519 s | 5.7093 s | −25.331% |
| input_load 阶段 | 11.951 µs/step | 11.973 µs/step | +0.003% |
| eval 阶段 | 297.694 µs/step | 186.970 µs/step | −37.274% |
| update 阶段 | 70.917 µs/step | 85.219 µs/step | +20.207% |
| 最大 partition eval | 292.466 µs/step | 181.725 µs/step | −37.943% |
| 全部 partition eval 之和 | 1816.376 µs/step | 1810.393 µs/step | −0.441% |
| 全部 partition update 之和 | 1099.585 µs/step | 1254.730 µs/step | +14.153% |

六对 Host 与进程 walltime 全部改善。Host 逐对变化范围 −25.165% 至 −24.744%，
AB 中位变化 −24.776%，BA −24.932%。完整新构建和同批对照支持保留 pair_00 作为
当前探索性最优候选，不代表更长负载、所有输入或四态语义已经验证。

pair_00 与 single_00 属于不同批次、各自相对同一个冻结 baseline 做六对交错；两批
baseline Host 中位数相差约 0.7%。不把候选两列直接相除冒充候选间配对结果。
就各自同批对照看，pair_00 的收益更大。两者 eval 阶段相近（190.333 / 186.970 µs），
主要差异是 pair_00 的 update 阶段只有 85.219 µs，低于 single_00 的 123.592 µs。

此时静态最大 ASC 位于 `part_1`，实际 eval 只有 140.820 µs；实际最慢线程是
`part_6`，eval 181.725 µs，其主要 ASC 的静态 closure 为 256,951。最大静态成本
已经不是当前动态最慢分区。下一步应先分析 `part_6` 的运行热点及状态/控制行为，再决定
新的切口；同时观察最慢 update `part_22`（76.647 µs，36,804 B/step）。继续只追求
最大静态 ASC 数字，已经不足以预测 walltime。

成功产物相对 `build/asc_separator_20260920/`：

- `pair00_build_node030_v1/build-manifest.json`：全量构建与对象核验。
- `pair00_build_node030_v1/partitioned-emu/verilator-compile/emu`：SHA-256
  `c9044eb59ea7aec9200095ad20ec5cc04dcaf7d285ef0a56299d484095920f2d`。
- `pair00_interleave6_node030_v1/{manifest.json,summary.json,runs.csv,pairs.csv,parts.csv}`：
  成功初始化检查及六对交错的原始日志和统计。

代码侧 `transform-pass-manager`、`transform-reg-to-mem`、
`transform-mem-to-reg-selection` 三项 CTest 均通过，Python wrapper/实验脚本语法与
主仓库、Wolvrix `git diff --check` 通过。新增 API 文档见
[`mem-to-reg`](../../wolvrix/docs/transform/mem-to-reg.md)。本轮没有改动 XiangShan 源码，
没有自动启用全局 memory 展开，也没有提交代码；选择性 pass、测试和文档留在工作树。

### 7.10 增量更新：三方案统一 wrapper `-O3` 后的公平复测

前述 single_00 update 回退的进一步检查发现，baseline、single_00、pair_00 的四个
generated wrapper（common/load/eval/update）原编译命令均未包含 `-O`。实际汇编中，
宽信号每复制一个 32-bit word 都保留两次 `VlWide` 指针转换调用；模型字段访问也保留
多层 `unique_ptr` 辅助调用。此前六对结果仍对应当时的真实可执行文件，但不应据此
判断优化过的通信框架下两种切分的收益。

本轮按用户要求将三方案四个 wrapper 全部以同一 Clang 21.1.5、相同非优化参数加
`-O3` 重编译。每个方案复用自己的全部 32 个 Verilator model archives 及其他 runtime
对象，保持原链接顺序，只精确替换四个 wrapper 对象；复用输入在链接前后核对 SHA-256。
所有 RTL、分区、端口布局、复制方向和 all-spin 源码均未改变。这里是 **wrapper -O3**，
并非全工程重新以 `-O3` 编译；模型原本的 fast/Slow 编译设置继续保持。

同时修正 `testcase/xiangshan/difftest/verilator.mk`：生成 wrapper 的编译规则默认使用
`WOLVRIX_PARTITIONED_WRAPPER_OPT ?= $(OPT_FAST)`，当前默认 `OPT_FAST=-O3`，允许显式
覆盖。该参数仅用于四个 generated wrapper，不扩展到其他 runtime 对象。实际 Make
dry-run 验证了默认 `-O3`、覆盖 `-O2`，并确认除此以外与冻结 wrapper 命令逐参数一致，
outer runtime 参数保持原样。此处是本轮新增的构建规则修改，区别于 §7.9 时尚未修改
XiangShan 子模块的状态；未修改 Scala/RTL，也未提交代码。

在 node030 CPU96–127、NUMA1、关闭 ASLR、`N=K=32`、默认 Host/worker all-spin 条件下，
先做三次 C=100 初始化检查，再做六轮 C=10000。令 A=baseline、B=single_00、C=pair_00，
执行顺序为 `ABC / CBA / BCA / ACB / CAB / BAC`，三方案各六次、各在每个位置出现两次。
每个候选与同轮 baseline 配对，恰好各三次 AB 和 BA；两个候选也可直接按轮配对。
没有同时运行编译或 perf 采样。21 次运行全部退出成功、runtime config 和功能签名吻合；
C=100 仅初始化/reset，18 次 C=10000 均启用 difftest、退休 458 条指令、20102 个 step。

| 指标（各六次中位数） | baseline `-O3` | single_00 `-O3` | pair_00 `-O3` |
| --- | ---: | ---: | ---: |
| Host time | 6.3480 s | 4.3065 s | 4.2050 s |
| 进程 walltime | 6.440 s | 4.395 s | 4.295 s |
| input_load | 3.935 µs/step | 4.260 µs/step | 4.265 µs/step |
| eval 阶段 | 287.065 µs/step | 174.665 µs/step | 173.602 µs/step |
| update 阶段 | 22.101 µs/step | 32.012 µs/step | 28.346 µs/step |
| 最大 partition eval | 283.644 µs/step | 168.324 µs/step | 170.214 µs/step |
| 最大 partition update | 15.170 µs/step | 27.233 µs/step | 22.974 µs/step |
| 全部 partition eval 之和 | 1924.966 µs/step | 1773.764 µs/step | 1774.740 µs/step |
| 全部 partition update 之和 | 252.582 µs/step | 339.358 µs/step | 365.118 µs/step |

| 同轮配对变化中位数 | single_00 / baseline | pair_00 / baseline | pair_00 / single_00 |
| --- | ---: | ---: | ---: |
| Host time | −32.168% | −33.691% | −2.339% |
| 进程 walltime | −31.726% | −33.204% | −2.273% |
| eval 阶段 | −39.095% | −39.518% | −0.755% |
| update 阶段 | +44.848% | +28.602% | −11.614% |

所有 Host/wall 配对均为改善。single_00 的 Host 逐对范围为 −32.552% 至 −31.869%，
AB 中位 −32.346%、BA −32.080%；pair_00 为 −34.006% 至 −33.559%，AB 中位 −33.937%、
BA −33.607%。上述百分比使用逐对比值中位数，不是三列绝对中位数直接相除。

相对先前未优化 wrapper 的历史结果，update 阶段从 baseline 约71、single_00 约124、
pair_00 约85 µs，分别降到约22、32、28 µs；single_00 的 part_16 从117.243降到27.233 µs。
这些跨批绝对数用于解释变化幅度，不冒充本轮 O0/O3 配对实验；正式划分收益以上述
同批、双方均 O3 的比较为准，而且四个 wrapper 同时优化，不能把全部收益归给 update。

single_00 相对 baseline 的额外 update 从历史约52.5 µs缩小到本轮约9.9 µs，原先的
未优化复制实现确实遮蔽了大量 eval 收益。优化后 single_00 Host 收益由历史约14.6%
变为本轮约32.2%；pair_00 由约24.9%变为约33.7%。pair_00 仍为当前最佳候选，但领先
single_00 的幅度已缩小到同轮约2.34%，此前两候选较大的差距受到 wrapper O0 明显放大。

update 差异未完全消失，不能据本轮宣称分区通信已无成本。优化后三方案的最慢 update
按分区中位数分别为 baseline part_5、single_00 part_16、pair_00 part_7；旧 pair_00
瓶颈 part_22 现为21.172 µs。pair_00 的 update 总和比 single_00 更大，却有更低的
阶段时间，再次说明最慢发送线程比所有线程耗时之和更直接决定阶段关键路径。
实际最慢 eval 仍分别为 part_7、part_4、part_6；两个候选下一步主要瓶颈仍在 eval。
结论限于当前早期 C=10000 工作负载，不外推为完整 CoreMark 或全部输入表现。

成功产物相对 `build/asc_separator_20260920/`：

- `build_wrapper_o3.py`、`wrapper_o3_build_node030_v1/{manifest.json,make-audit.json}`：
  重编译脚本、三方案构建清单及 Make 规则展开核验；各方案目录含四个新对象和完整链接命令。
- `wrapper_o3_build_node030_v1/baseline/emu`：SHA-256
  `340748b543b6256a00e2f832216fcce03eb5d4aa48c28c50fc57bc1644592713`。
- `wrapper_o3_build_node030_v1/single00/emu`：SHA-256
  `b130120845bdd44f8203bbdf156b47cf0664be99f939c6499480c6710911dd9d`。
- `wrapper_o3_build_node030_v1/pair00/emu`：SHA-256
  `0708a76eae6418c98b78cbd7f08a2bc3f71d1bf36a9c8ceb2007170e58b8ddf4`。
- `run_wrapper_o3_comparison.py`、`wrapper_o3_interleave6_node030_v1/manifest.json`：
  全部21次成功运行、原始日志、时间统计、JSONL 和真实顺序。
- `wrapper_o3_interleave6_node030_v1/{summary.json,three-arm-summary.json}` 与
  `{single00,pair00}/{summary.json,runs.csv,pairs.csv,parts.csv}`：配对及逐分区统计。

独立构建/汇编审计通过：每组仅替换四个 wrapper 对象，复用32个模型 archive 与43个
其他 runtime 对象；源文件与历史清单一致。三组 update 实际汇编中的 `copy_wide_words_`、
`unique_ptr` 和逐字 `VlWide` 指针转换调用均已消除，single part_16 使用直接 SIMD
搬运；common 的自旋路径也已内联为字节读取、条件跳转和 `pause`。保留对象中的旧弱
模板符号没有把热点重新变回 O0。现有 Make 对象不会仅因优化参数改变而自动重编，
后续复用旧构建目录时须显式重编 wrapper；本轮采用独立新对象及新 ELF，已规避此问题。

### 7.11 增量更新：single_00 + pair_00 组合转换及四方案交错复测（2026-09-21）

按用户要求从同一原始 GRH 同时展开 single_00 的 L2 D 队列和 pair_00 的 socMisc A/D
两个队列，称为 `combined`。不是合并已划分模型，而是一次选择三个 exact memory symbol，
随后完整重跑 K=32 RepCut、重建、emit 和全部模型编译。输入 SHA 与 §7.1 相同，转换统计：

```text
memory_total=4809 converted=3 regs_created=6 read_rewritten=3 write_rewritten=3
skipped_unselected=4806 skipped_row_limit=0 skipped_nonconst_mask=0 skipped_init=0
```

转换 JSON SHA-256 为 `c7b8b36adaf98f8bd794593f0d2f5c18e418f6566dae48edc5fabfb5f8d56e8e`。
保持 closure-aware、K=32、imbalance=0.015、quality（实际 deterministic-quality）、seed=0、
32 个 solver 线程、默认 all-spin。三个旧对照复用 §7.10 的 wrapper-O3 ELF；组合全量构建
32 个 archive、1375 个模型对象，模型 fast `-Os` / Slow 无显式优化，四 generated wrapper
均且仅 `-O3`。common/header 与全部旧对照 SHA 一致，outer source、工具链文件身份及
规范化后的编译参数均与旧对照一致。独立审计未发现构建公平性差异。

#### 结构与通信

| 指标 | baseline | single_00 | pair_00 | combined |
| --- | ---: | ---: | ---: | ---: |
| ASC 数 | 301,182 | 301,183 | 301,183 | 301,184 |
| 最大 ASC full closure weight | 883,100 | 713,917 | 642,580 | 642,580 |
| 最大 partition exact closure weight | 883,100 | 713,917 | 642,580 | 642,580 |
| 全部 partition exact closure 总和 | 13,052,827 | 13,052,048 | 13,047,051 | 13,018,341 |
| 重建后最大 partition ops | 447,447 | 360,450 | 321,862 | 321,867 |
| 重建后全部 partition ops | 6,188,556 | 6,193,679 | 6,193,109 | 6,176,620 |
| 每步跨分区赋值/复制条数 | 4,836 | 5,751 | 6,181 | 6,541 |
| 每步跨分区 logical bits | 3,494,515 | 4,119,503 | 3,670,805 | 3,635,104 |
| 每步 Verilator 值存储复制字节 | 441,866 B | 521,171 B | 465,379 B | 460,987 B |

组合相对 pair_00：最大 ASC 不变，全部 partition ops −0.266%、exact closure 总和
−0.220%、复制字节 −0.944%，但复制条数 +5.824%。复制量仍按每个目标累计，不是 PMU
缓存行流量。组合相对 baseline 的最大 ASC −27.236%，复制字节 +4.327%。

从结构看，组合未继续拆 pair_00 剩余的642,580大块；它进一步拆的是另一侧。
pair_00 第二大 ASC closure 为256,951，组合后第二大为185,637，第三大已为85,400。
组合最大 ASC 位于新 part_4，185,637 的块位于新 part_3。分区编号在不同方案间不代表
同一逻辑，不把 part_6→part_3 简单解释为直接改名。

#### 同批八轮四方案运行

node030 CPU96–127、NUMA1、关闭 ASLR、N=K=32、Host lane9、Host/worker all-spin、
step timing 开启；先四次 C=100 初始化检查，再32次 C=10000。令 A=baseline、B=single_00、
C=pair_00、D=combined，顺序为：

```text
ABCD / DCBA / BCDA / ADCB / CDAB / BADC / DABC / CBAD
```

每个方案在每个位置各出现两次，combined 对任一对照各四次 AB、四次 BA；这是均衡
位置及相对顺序，不是全部24种排列。所有36次运行均通过退出码、功能签名及 runtime
配置检查；32次 C=10000 启用 difftest，均退休458条指令、20102个 step。测量期间没有
并行编译或 perf 采样，运行前后 ELF/image/NEMU 身份保持不变。

| 指标，各八次中位数 | baseline | single_00 | pair_00 | combined |
| --- | ---: | ---: | ---: | ---: |
| Host time | 6.6460 s | 4.5415 s | 4.3620 s | 4.1560 s |
| 进程 walltime | 6.760 s | 4.645 s | 4.465 s | 4.260 s |
| input_load | 4.039 µs/step | 4.306 µs/step | 4.319 µs/step | 4.269 µs/step |
| eval 阶段 | 301.107 µs/step | 185.040 µs/step | 179.960 µs/step | 169.462 µs/step |
| update 阶段 | 22.486 µs/step | 32.822 µs/step | 29.049 µs/step | 28.920 µs/step |
| 最大 partition eval | 297.390 µs/step | 178.009 µs/step | 176.347 µs/step | 163.281 µs/step |
| 全部 partition eval 之和 | 2022.700 µs/step | 1860.807 µs/step | 1828.482 µs/step | 1810.480 µs/step |
| 最大 partition update | 15.931 µs/step | 27.788 µs/step | 23.690 µs/step | 24.344 µs/step |
| 全部 partition update 之和 | 260.684 µs/step | 347.648 µs/step | 377.718 µs/step | 383.785 µs/step |

| combined 相对同轮对照，配对变化中位数 | baseline | single_00 | pair_00 |
| --- | ---: | ---: | ---: |
| Host time | −37.981% | −7.884% | −5.031% |
| 进程 walltime | −37.419% | −7.741% | −4.844% |
| eval 阶段 | −43.650% | −7.933% | −6.321% |
| update 阶段 | +28.591% | −11.301% | −0.653% |
| Host / wall 胜出次数 | 8/8 | 7/8 | 7/8 |

百分比是同轮比值的中位数，不是绝对中位数直接相除。本批绝对耗时波动明显高于 §7.10，
所有成功样本均保留。combined 对 pair_00 的逐轮 Host 变化范围 −14.207% 至 +1.218%，
AB 中位 −3.506%、BA −5.031%；wall 范围 −13.870% 至 +1.373%，AB 中位 −3.330%、
BA −4.946%。两个顺序方向均正向，但不是每一轮都胜出，不把探索性中位收益称为固定
保证，也不拿今日 combined 与昨日 pair_00 的绝对时间直接比较。

#### 结论与关键路径

组合获得额外约4.8%的同批 walltime 改善，当前可作为更优探索性候选保留，未自动改默认
管线。相对 pair_00 的主要收益来自 eval，update 近乎持平；不能解释为通信带宽改善。
实际最慢 eval 从 pair_00 的 part_6（176.347 µs）变为 combined 的 part_3
（163.281 µs）；combined 持有最大静态 ASC 的 part_4 只有142.166 µs。最慢 update
为 part_15（24.344 µs）。这与“最大 ASC 不变，但拆开原动态瓶颈所在的另一块后仍能
改善运行时间”相符；重新全局划分也会改变其他分区，尚未逐逻辑隔离各因素的贡献。
结论仍限于当前早期 C=10000 工作负载，不代表完整 CoreMark、所有输入或四态语义验证。

成功产物相对 `build/asc_separator_combined_20260921/`：

- `pipeline.json`、`targeted/run.json`、`emit/run.json`：三个目标转换、输入/库身份、
  分区结构与 assignment；`static-summary.json`：四方案静态汇总。
- `build/build-manifest.json`：全量新构建、编译参数、对象清单；ELF
  `build/partitioned-emu/verilator-compile/emu` SHA-256 为
  `16acc0fa0456699305340bf1687a2c040b0842a70fc52d36cfb5304f34527b68`。
- `interleave8_node030_v1/{manifest.json,summary.json,four-arm-summary.json}`：全部成功
  原始日志、顺序、绝对时间与统计；`combined_vs_{baseline,single00,pair00}/` 含每组
  `summary.json,runs.csv,pairs.csv,parts.csv`。
- 复现入口保存在 `build/asc_separator_20260920/` 下的 `run_combined_pipeline.py`、
  `run_combined_comparison.py`、`summarize_combined.py`；当前全量 builder 本地核验
  wrapper 必须为 `-O3`，不再调用历史仅接受 O0 的审计函数，历史 helper 未改动。

本轮没有新增生产算法或 RTL 修改、没有提交代码；继续保留此前工作树中的选择性 pass
及 wrapper 优化构建规则。主仓库、Wolvrix 和 difftest 的 `git diff --check` 均通过。

### 7.12 四方案单步时空图（2026-09-21）

复用 §7.11 同批32次 C=10000 成功运行，未重新运行仿真，未混用历史未优化 wrapper
或历史事件 probe 的结果。四方案使用同一横轴，分别展示32个线程的 eval/update；
Host 为 lane9 / CPU105，输入加载全部画在该行。红框标出各阶段最长 callback，紫色
菱形标出持有最大静态 ASC 的分区。按用户要求继续追加本篇，不另开文档。

- [四方案时空图 PNG](../../build/asc_separator_combined_20260921/interleave8_node030_v1/visual/four_arm_timeline.png)
- [可放大的 SVG](../../build/asc_separator_combined_20260921/interleave8_node030_v1/visual/four_arm_timeline.svg)
- [全部分区耗时 CSV](../../build/asc_separator_combined_20260921/interleave8_node030_v1/visual/four_arm_part_durations.csv)
- [重建数据及输入 SHA-256](../../build/asc_separator_combined_20260921/interleave8_node030_v1/visual/four_arm_timeline_data.json)
- [绘图脚本](../../build/asc_separator_combined_20260921/interleave8_node030_v1/visual/plot_four_arm_timeline.py)

**计量口径：这是阶段耗时重建图，不是真实单步事件 trace。** 原始 JSONL 仅记录每次
20102步的累计/平均耗时；图中每条长度是每次均值的八轮中位数，并在所属阶段起点
对齐示意。灰色是阶段剩余时间，包含等待、派发、同步等，不能解读为测得的连续等待
区间、CPU空闲或精确启动延迟；当前 Host/worker 仍永久忙等。有色区间也为墙钟耗时，
并非纯 CPU time。不同方案的同编号 partition 不是同一逻辑。

图的终点为 load、eval、update 三个独立中位数之和，依次为
327.631 / 222.168 / 213.327 / 202.6495 µs；不冒充整步计时中位数，后者依次为
328.0325 / 222.702 / 213.740 / 202.949 µs。图不包含 step() 外层 Host 工作以及
进程初始化、退出；各子图标题另列完整实测 Host / walltime 的八轮中位数。
最长条按“各分区先取中位数，再比较”选择；例如 baseline update 为 part_5 的15.884 µs，
与 §7.11 表中“每轮先取最大，再取八轮中位数”的15.931 µs不矛盾。

图中可见 baseline 的 eval 长尾显著缩短，但组合后仍有多数线程提前完成；相对 pair_00，
组合的最慢 eval 从176.347降至163.281 µs，而最大ASC所在分区分别为138.009和
142.1655 µs，并非实际最慢者。组合的 update 阶段仍约28.920 µs，高于 baseline 的
22.486 µs；当前主要改善来自 eval，不是 update 变短。

绘图时重新校验32份原始日志、退出码、功能签名、runtime mapping、计时记录完整性及
八轮统计，并与 `four-arm-summary.json` 逐项核对；独立审计结果一致。PNG 已人工查看，
SVG可无损放大，CSV保留未在小条上标出的数值。复现示例（仓库根目录）：

```bash
/tmp/gsim-timeline-20260917-venv/bin/python \
  build/asc_separator_combined_20260921/interleave8_node030_v1/visual/plot_four_arm_timeline.py \
  --font /tmp/gsim-timeline-20260917-NotoSansCJKsc-Regular.otf
```

本次使用已有 Matplotlib 3.11.2 绘图环境及 Noto Sans CJK SC 字体；也可使用安装了
Matplotlib 的 Python，向 `--font` 提供等效的完整中文字库。没有生产代码变更或提交。

#### 同日补充：交互式 HTML

补齐[离线交互式时空图](../../build/asc_separator_combined_20260921/interleave8_node030_v1/visual/four_arm_timeline.html)，
复用上述同批统计，未新增仿真。支持四方案/两两/单方案切换、完整阶段或 eval/update
独立视图、1/2/4倍横轴放大、按耗时排序、关键线程过滤、悬停/点击固定详情及当前
所示分区CSV导出。所有显示面板共用刻度；Host加载、阶段和/整步统计分离、灰色剩余
的非事件语义保持不变。没有逐步 trace，因此不提供虚构的“选择某一步”。

HTML内嵌绘图统计数据、源文件SHA清单、脚本和字体，可单文件离线打开；不包含32次
运行的原始日志。`plot_four_arm_timeline.py` 现在同时输出HTML；单独生成可运行同目录
`make_interactive.py --font <字体路径>`，需要 FontTools。同目录 `check_interactive.py`
用 Playwright/Chromium 验证离线加载、48种视图/阶段/过滤组合、128行CSV与静态数据
一致、排序/缩放/悬停/键盘选择及窄屏滚动；无浏览器异常、无外部请求，报告为
[interactive-check.json](../../build/asc_separator_combined_20260921/interleave8_node030_v1/visual/interactive-check.json)。

### 7.13 每分区权重与 eval/update 对照条形图（2026-09-21）

复用 §7.11 四方案同批八轮时间数据，与各方案原始 emit 诊断的
`partition_static_features` 按 `part_name` 连接，共128个分区；未新增运行。
输出[交互条形图 HTML](../../build/asc_separator_combined_20260921/interleave8_node030_v1/visual/four_arm_partition_work.html)、
[完整原始值 CSV](../../build/asc_separator_combined_20260921/interleave8_node030_v1/visual/four_arm_partition_work.csv)
及[数据与源文件 SHA 清单](../../build/asc_separator_combined_20260921/interleave8_node030_v1/visual/four_arm_partition_work_data.json)。
原时空图也增加了跳转入口。三个指标在每个分区内并排画条，不堆叠；可独立勾选、
切换方案、排序、缩放、悬停/固定详情并导出当前指标。

默认权重为 `estimated_node_weight_sum`：重建前该分区 `partitionOps` 中原始 Phase-A
操作的类型/位宽/扇出启发式权重和；共享逻辑分配给多个分区时各自计入，不含重建新增
的连接操作，亦不是 Verilator 编译后的指令数或动态工作量。代码位置为
`wolvrix/lib/transform/repcut.cpp:3493`、`:3563`、`:5677`。页面另提供两种口径切换：

- `exact_referenced_closure_weight`：该分区 ASC 引用 piece 的并集权重，分区内去重、
  跨分区重复计入；仅覆盖被 ASC 引用的 piece。exact 仅指静态求和精确。
- `hyper_partition_weight`：当前 closure-aware 下共享 piece 先在 ASC 间平摊，再按
  分区汇总求解器节点权重；不等于复制后的实际负载。

时间仍为每次20102步平均值的八轮中位数，单位 µs/step，仅计对应分区 eval/update
callback 墙钟跨度，不含 callback 外的忙等、同步；不是纯 CPU time。Host lane9 行
也只统计自身分区 callback，不是 Host 总时间。分区编号跨方案不对应同一逻辑。

默认归一化为“该值 / 本方案全部32分区该指标均值”，三项分别归一化，以比较相对
分布；时间分母由32个分区的八轮中位数求平均。条长不能用于比较 eval 与 update 的
绝对耗时。原始值模式中权重读上轴、eval/update 共用下轴；跨单位条长亦不可直接比
大小。刻度由全部四方案、全部三指标固定计算，隐藏指标或方案不会重定标。悬停始终
显示原始数值；CSV保留原始精度。计算权重主要针对 eval；update 更直接受复制条数、
宽度、扇出及缓存行为影响，不预期与计算权重同比例。

复现脚本为同目录 `make_partition_work.py --font <字体路径>`，使用既有绘图 Python
环境、FontTools和字体；复用原运行解析器重新检查32份日志的退出码、功能签名、线程
映射及计时完整性。三种权重分别与原诊断逐项对账，hyper及closure总量与汇总对账，
独立审计确认128行时间与原始JSONL一致。浏览器测试
`check_partition_work.py` 通过48种权重/刻度/勾选组合、32种方案/排序组合、3档缩放、
三种权重CSV及部分指标导出、条长计算、悬停/键盘和窄屏滚动；离线无外部请求和
浏览器异常，报告为[partition-work-check.json](../../build/asc_separator_combined_20260921/interleave8_node030_v1/visual/partition-work-check.json)。
没有生产代码修改或提交，继续追加本篇，不另开文档。
