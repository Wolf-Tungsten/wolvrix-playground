# TNO0374：p0 / clock=1 / commit batch 345 详细分析

日期：2026-10-29。

本记录分析 [动态关键路径报告](./TNO0373_grhsim_dynamic_top1_all_partitions_20261029.md)
中 p0、`clock=1` 的 `commit batch 345`。它是诊断 binary 中的 batch 计时对象；
这里的计时不会被当成生产 binary 的逐信号耗时。

## 结论先行

`0:commit:345` 不是一条单独的 Verilog 组合路径，而是一个被 RepCut 合并到
同一个 commit supernode 的大规模状态提交函数：

- ASC：`5`；GRH group：`2725`；active id：`2734`。
- 5,986 个操作：5,697 个 `kRegisterWritePort`、289 个 `kMemoryWritePort`。
- 静态工作量 38,538，全部是 rise work，fall work 为 0；未知工作为 0，未映射操作只有 10 个。
- 这些操作来自 102 个 Verilog 文件、2,617 个 RTL source span。来源最多的模块是
  `LogPerfEndpoint` 2,000 个、`MSHR_64` 1,528 个、`Directory_Anon` 408 个、
  `MissEntry` 288 个、`SinkC_4` 260 个和 `SinkA_4` 172 个。
- 生成的 C++ 函数有 63,329 行、4,531,816 字节；链接后的函数符号大小为
  302,053 字节。函数静态包含 6,146 个 `if`、5,855 个 `unlikely` 守卫、
  8,186 次 active-flag 引用和 1,636 次 producer-dirty-word 引用。

两次独立 batch probe 在全局稳定拖尾样本中都把它排在 p0/clock=1 的第一名：

| 重复 | 稳定拖尾采样步数 | batch 调用 | 累计时间 |
|---:|---:|---:|---:|
| 1 | 140 | 280 | 225.552 µs |
| 2 | 140 | 280 | 250.043 µs |
| 合计 | 280 | 560 | 475.595 µs |

合计只占 p0/clock=1 同范围采样 batch 时间的 5.28%，所以“动态第一名”表示
它是该分区该 clock 下测到的最大单个 batch 成本，不表示它单独造成了全部 p0
拖尾或 5.28% 的普通 walltime。最大单次调用为 15.110 µs，出现在第二次重复；
这也是需要继续做组级 trace 的信号。

## 1. 它在执行计划中是什么

原始 batch 记录在 [`batch_map.csv:347`](../../build/xs/grhsim32_fresh_rtl_20261028/critical-path-dynamic-all32_20261029_v2/mapping/batch_map.csv:347)。完整操作记录从
[`operation_map.jsonl:340651`](../../build/xs/grhsim32_fresh_rtl_20261028/critical-path-dynamic-all32_20261029_v2/mapping/operation_map.jsonl:340651)
开始；对应的机器可读汇总是 [`batch345_detail.json`](../../build/xs/grhsim32_fresh_rtl_20261028/critical-path-dynamic-all32_20261029_v2/analysis/batch345_detail.json)。

它是一个 commit batch，而不是 compute batch。执行计划把它放在 p0 的提交阶段，
没有跨分区输入；提交值如果发生变化，则在本地 `supernode_active_curr_` 和
`producer_dirty_words_` 中重新激活读者。因而它的主要成本结构是：

1. 检查本 batch 的触发条件；
2. 读取待提交的值，与当前 state slot 比较；
3. 对变化的寄存器做写入；
4. 对变化的 memory 做数组写入；
5. 更新 active flag 和 dirty word，推动后续 fixed-point round。

这不是一个“执行一次算术表达式”的小函数，而是一个提交和传播边界。

## 2. 生成的 C++ 做了什么

生产 package 中的函数是 [`grhsim_Gpart_0_model_sched_345.cpp:8`](../../build/xs/grhsim32_fresh_rtl_20261028/initial/package/grhsim_Gpart_0_model_sched_345.cpp:8)，诊断 eval dispatcher 在 [`grhsim_Gpart_0_model_eval.cpp:8087`](../../build/xs/grhsim32_fresh_rtl_20261028/critical-path-dynamic-all32_20261029_v2/batch-probe/sources/grhsim_Gpart_0_model_eval.cpp:8087)
调用它。

函数开头先根据 `hot_event_posedge_` 把 active word 341 的 bit 64 放行，
再执行 supernode 2725；相关入口在生成 C++ 的第 14–26 行。该事件来自
`event_edge_storage_[0]`，而 p0 的静态端口表把 `repcut_port_126` 标成了
`clock`，因此这里是一个上升沿触发的提交 supernode，而不是任意 clock 电平
都执行的普通 batch。

前几项是 memory write，例如 `grhsim_assign_words` 和
`grhsim_assign_words_2` 写入 AXI buffer、L3 `sourceD.pbQueue` 等状态数组；
随后是大量 `Same-reader scalar commit group`。每组先比较多个 old/new
state slot，只有至少一个发生变化时才批量写回，并设置后续 active flags。

本 batch 的 289 个 memory write 分布在 173 个不同的生成 memory 对象上。它们
不是简单的一个数组顺序写，而是包含边界检查、索引计算、宽度适配和写后激活。
5,697 个寄存器写也不是 5,697 条无条件 store：生成器为它们保留了条件判断、
旧值比较和读者重新激活逻辑。因此代码体大、分支密集、状态存取密集。

相邻 commit batch 的静态形态可以帮助区分原因：

| batch | 操作数 | memory write | C++ 源码 | `unlikely` 守卫 | active 引用 | dirty 引用 |
|---:|---:|---:|---:|---:|---:|---:|
| 342 | 230 | 206 | 195 KB | 29 | 260 | 0 |
| 343 | 162 | 138 | 142 KB | 21 | 167 | 0 |
| 344 | 5,433 | 54 | 4.05 MB | 3,722 | 6,663 | 1,100 |
| **345** | **5,986** | **289** | **4.53 MB** | **5,855** | **8,186** | **1,636** |
| 346 | 2,639 | 2 | 2.29 MB | 2,395 | 6,895 | 1,442 |

batch 344 的源文件虽然也很大，但 batch 345 的操作数多 10.2%，memory write
多 5.35 倍，active 引用多 22.9%，dirty 引用多 48.7%。这与实际计时相符：

| batch | 第一次重复累计 | 第二次重复累计 |
|---:|---:|---:|
| 343 | 109.436 µs | 99.498 µs |
| 344 | 139.433 µs | 134.083 µs |
| **345** | **225.552 µs** | **250.043 µs** |
| 346 | 154.290 µs | 153.386 µs |

所以它慢的第一证据是**提交函数本身的代码和状态操作规模很大**，而不是某个
单一 Verilog expression 的算术复杂度。

## 3. 对应的 Verilog 来源

batch 的完整来源集合很大，不能压缩成一条唯一的 Verilog 箭头路径。以下是
报告中操作数量较高、且能直接打开核对的代表位置：

### LogPerfEndpoint

- [`LogPerfEndpoint.sv:79578`](../../build/xs/grhsim32_fresh_rtl_20261028/rtl/rtl/LogPerfEndpoint.sv:79578)
  的 `client_dir_conflictCounter_1`。
- [`LogPerfEndpoint.sv:79388`](../../build/xs/grhsim32_fresh_rtl_20261028/rtl/rtl/LogPerfEndpoint.sv:79388)
  的 `drop_prefetchCounter_3`。

这些位置位于生成 RTL 的大量性能计数器状态区域。它们在该 batch 中表现为
状态写操作；不能把它们解释成运行时真的执行了 `printf`。Chisel 的
`LogPerfEndpoint` 类声明在 [`LogUtils.scala:195`](../../testcase/xiangshan/utility/src/main/scala/utility/LogUtils.scala:195)，
但当前映射还不能把每个生成计数器唯一还原到某个 `XSPerf` 调用者。

### MSHR

- [`MSHR_64.sv:722`](../../build/xs/grhsim32_fresh_rtl_20261028/rtl/rtl/MSHR_64.sv:722)：
  `req_isBop <= io_alloc_bits_isBop`。
- 同一模块的相邻状态写还包括 `req_fromProbeHelper`、`req_needProbeAckData`、
  `req_reqSource` 和 `iam`。

对应的 Chisel 候选不唯一，报告保留了：
[`coupledL2/tl2chi/MSHR.scala:51`](../../testcase/xiangshan/coupledL2/src/main/scala/coupledL2/tl2chi/MSHR.scala:51)、
[`coupledL2/tl2tl/MSHR.scala:47`](../../testcase/xiangshan/coupledL2/src/main/scala/coupledL2/tl2tl/MSHR.scala:47)、
以及 HuanCun 和 Rocket-Chip 中的同名 `MSHR` 实现。这里的 `MSHR_64` 名字
不足以确定最终 elaboration 实例。

### Directory 和 MissEntry

- [`Directory_Anon.sv:806`](../../build/xs/grhsim32_fresh_rtl_20261028/rtl/rtl/Directory_Anon.sv:806)：
  `tagAll_s2_1` / `_tagArray_io_r_resp_data_1`。
- [`MissEntry.sv:959`](../../build/xs/grhsim32_fresh_rtl_20261028/rtl/rtl/MissEntry.sv:959)：
  `io_refill_to_ldq_bits_data_r` 相关状态更新。

`Directory_Anon` 是 elaboration 后的匿名/扁平化模块名，不能直接当成唯一
Chisel class；相关候选包括 coupledL2/huancun 的 `Directory`、`BaseDirectory`
和 `SubDirectory`。`MissEntry` 的候选较清楚，为
[`MissQueue.scala:368`](../../testcase/xiangshan/src/main/scala/xiangshan/cache/dcache/mainpipe/MissQueue.scala:368)。

batch 345 的其他主要来源还包括 `SinkC_4`、`SinkA_4`、`MSHRBuffer`、
`SubDirectory`、`SourceD`、`DataStorage_4`、`RequestBuffer_4`、各种 directory
array 和 queue wrapper。完整 source span 集合在报告的 JSON 和
[`batch345_operations.json`](../../build/xs/grhsim32_fresh_rtl_20261028/critical-path-dynamic-all32_20261029_v2/analysis/batch345_operations.json)。

## 4. 动态证据：它什么时候慢

稳定拖尾样本中，p0/clock=1 的 batch 345 两次都排名第一，第一名一致次数为
2/2。两次 probe 的 `stable_last` 统计如下：

- 第一次：140 个 clock=1 稳定拖尾采样步，280 次调用，225.552 µs。
- 第二次：140 个采样步，280 次调用，250.043 µs。
- 每次调用平均约 0.85 µs；最大单次分别为 3.38 µs 和 15.11 µs。
- trace 中 round=1 的累计时间为 467.904 µs，round>1 为 7.691 µs。

最后一项说明大部分测量成本集中在 trace 记录为 round=1 的提交调用，后续
round 的调用大多很便宜；但当前 trace 只记录 batch 区间和入口条件，没有记录
每个写操作是否真正改变、哪个 active group 被重新激活，因此还不能把这项差异
归因给某一组寄存器或某一个 memory write。

p0 在两次 discovery 中作为 clock=1 最后完成线程的累计次数很高，但 batch 345
本身只占 p0/clock=1 稳定采样 batch 时间约 5.3%。因此更准确的判断是：

> batch 345 是 p0 上升沿提交阶段最值得先拆解的单个 batch；它很可能是拖尾的
> 重要组成部分，但现有证据不足以说它独自决定 p0 的全局 eval 完成时间。

## 5. 下一步怎么继续

下一步应只对 ASC 5 / group 2725 做窄范围诊断，避免重新采集全 32 分区：

1. 在 5,986 个操作外层保留原始代码，只统计每个 commit operation 的 guard
   命中、old/new value 是否变化、memory write 是否实际写入。
2. 按来源簇分别汇总：`LogPerfEndpoint` 计数器、L3 directory、D-cache/MissEntry、
   SinkA/SinkC/SourceD 和 memory queue。计时仍以整个 batch 为准，操作计数只用于归因。
3. 记录每个 active flag 的新增读者数量和下一轮实际进入的 compute/commit batch，
   判断主要成本是当前提交，还是提交后固定点传播。
4. 如果大部分时间集中在少数可独立的 memory/状态簇，再研究保持语义不变的
   emitter 分组；如果时间均匀分散，则应从 active propagation 和 ASC/超节点形成
   规则入手。当前不直接改 RTL 或拆这个 batch。

本轮没有改变生产 GrhSIM、Verilator 或 RTL，只有诊断报告和可复查分析产物。
