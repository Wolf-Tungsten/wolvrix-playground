# TNO0384：专用单线程历史对照与编译兼容选项核对

日期：2026-10-30。状态：对照进行中；正式结论在后续章节追加。

## 问题与比较口径

用户要求比较本轮从 Chisel 新生成的单线程结果与历史结果，确认有无明显异常。
当前冻结基线见 [TNO0383](./TNO0383_native_single_thread_cpu96_walltime_baseline_20261030.md)，
100k cycles、8 次 Host 均值 118.524875 秒，CV 1.59%。本轮比较不重新生成或覆盖该 binary。

最接近的历史记录是 [TNO0335](./TNO0335_xiangshan_grhsim_single_thread_old_flow_20261012.md)
第 8 节：10 月 13 日 node030 的原生单模型、C100000、无 PERF dump 两次为
100.078 / 98.599 秒，均值 99.3385 秒。历史亲和性为 CPU0–7；本轮全部固定 CPU96。
相对于这个历史均值，新基线约慢 19.31%，但跨日期/运行配置的直接比值只用于发现问题。
不能使用旧版带大量 PERF dump 的 116–120 秒结果掩盖这个差异，也不能将 C50000 的
约 41–43 秒线性乘二；CoreMark 后 50k cycles 参与工作的逻辑更活跃。

## 已确认的构建差异

当前生成的 Makefile 自动给 Clang 21/23 x86 加入 `-fno-slp-vectorize`，
旧版 Makefile 没有这条规则。当前实际模型编译日志也包含该选项；因此有效选项为
`-std=c++20 -O3 -march=native -fno-slp-vectorize`，不能仅凭外部传入的 CXXFLAGS
认定新旧编译口径相同。

该规则来自 [TNO0339](./TNO0339_grhsim_clang23_change_reduction_20261027.md)
记录的 bool change-reduction wrong-code：丢失变化通知导致后续逻辑未被激活。
这里保留兼容保护；旧 binary 在给定输入前缀通过 Difftest 不能证明无保护编译对所有输入正确。

初步结构核对：新旧 activity-schedule 统计、emitter 统计、模型头文件和 eval 调度文件一致。
当前 ELF 的 size 工具 text 列从 79,039,716 增至 85,775,409 字节；该列包括只读数据，
不应解释为纯指令大小。后续会单独检查 .text 段和生成源文件差异。

## 同 CPU 对照正在执行

使用仍保留且 SHA256 与历史记录一致的 `emu_noperf_20261012`，与新冻结 emu
交替运行 4 对 AB/BA，另外各预热一次。固定 node030 CPU96、membind=1、ASLR 关闭，
相同 CoreMark、NEMU、seed=0、C100000，记录真实线程数、CPU 亲和性与 sibling 空闲率。
这是诊断对照；没有整个 CCD/PMU 隔离 gate，也不作为新优化的 8 对正式验收。

旧 noperf harness 把 `trigger_stat_dump()` 整体置空，因此 Guest cycle=100000；
当前 harness 保留收尾 single_cycle，但不强制日志输出，Guest cycle=100001。
主窗口和提交状态均应为 PC=0x80000c0c、instrCnt=240349、cycleCnt=99996。
两者必须分别校验，不能把这个已知差异误报为仿真功能失败，也不能将收尾差异隐藏。

首次诊断的旧版预热实际通过且耗时 97.356 秒，但借用的新基线日志解析器要求
Guest=C+1，因而在解析阶段拒绝旧版。原始日志保留在 `comparison_20261030/`；
只修正独立对照脚本的结束协议，重新在 `comparison_20261030_v2/` 收集完整序列。
新基线解析器与冻结产物未修改。

对照产物根目录：`build/xs/grhsim_single_fresh_20261030/`。

- [对照脚本](../../build/xs/grhsim_single_fresh_20261030/comparison_20261030_v2/compare.py)
- [新旧 binary、输入及实验身份](../../build/xs/grhsim_single_fresh_20261030/comparison_20261030_v2/manifest.json)
- [进行中的日志](../../build/xs/grhsim_single_fresh_20261030/comparison_20261030_v2/driver.log)
- [旧/新 Makefile 差异](../../build/xs/grhsim_single_fresh_20261030/comparison_20261030/Makefile.diff)

## 增量：结构和机器码证据

已对全部生成源文件、两个完整统计文件和最终 ELF 逐项检查。

| 项目 | 10 月 12 日旧模型 | 本轮新模型 |
|---|---:|---:|
| 最终 activity-schedule graph_ops | 7,204,108 | 7,204,108 |
| graph_values | 6,833,009 | 6,833,009 |
| compute / commit supernodes | 63,191 / 468 | 63,191 / 468 |
| boundary activation edges | 1,978,472 | 1,978,472 |
| topo edges | 10,141,598 | 10,141,598 |
| C++ 文件数 | 131 | 131 |
| C++ 文件总字节数 | 1,264,893,991 | 1,264,958,111 |
| ELF .text 指令段 / B | 71,642,468 | 79,453,857 |
| ELF .rodata / B | 6,666,584 | 5,590,312 |

activity-schedule 统计 JSON 与 emitter 统计 JSON **整文件一致**，不只是选定指标相同；
模型头文件及 `grhsim_SimTop_eval.cpp` 也完全一致。
C++ 源码总量只增加 0.00507%，而 `.text` 增加 10.9033%。

131 个 C++ 文件中，64 个逐字节相同；只去掉完整 `//` 注释行后，68 个相同。
其余差异包括局部生成 ID、`xs_assert_v2` 内的源码目录字符串，以及新生成 RTL
中 Ftq/LogPerfEndpoint 的顺序或命名。另存了双射重命名 `grhsim_v<id>_<port>` 后的
文本差异，但没有把这项归一化当作形式等价证明，也没有宣称全部模型源码完全相同。

更直接的机器码例子是原生完整模型的 **compute batch 13**（与 RepCut 的 p0 batch 345
无关）。它的 C++ 去除完整注释行后逐字节相同，SHA256 为
`e52af04ba8a02bd2b0f88bb6eeb3f195da34d78e7ea60a5a96985503bfe93c68`：

| 指标 | 旧版 | 新版 |
|---|---:|---:|
| eval_compute_batch_13 符号大小 / B | 938,949 | 1,198,516 |
| 对象反汇编静态指令数 | 177,515 | 236,850 |
| v 开头的向量指令助记符计数 | 35,577 | 15 |
| 条件跳转指令计数 | 2,846 | 3,779 |

以上是静态机器码计数，不是动态执行次数，也不能直接换算为时间。
它表明相同计算表达式已经因为构建口径产生明显不同的机器码，为 no-SLP 导致成本上升
提供直接支持。完整 walltime 的全部差值是否都由此造成，仍需要同源码、同 harness
的编译选项消融；当前没有做这个因果分离。

已从实际编译日志抽取 131/131 个对象命令：旧版均无 `-fno-slp-vectorize`，新版均有。
新版第一次调用 clang 的 C driver 只影响最终 C++ 链接库选择；模型 `.cpp` 的编译
参数已明确记录，成功 relink 沿用这些对象。不能把第一次 link 失败解释为后来运行了
不完整或混用的模型。

证据文件位于同一 `comparison_20261030_v2/`：

- [完整结构及源文件哈希](../../build/xs/grhsim_single_fresh_20261030/comparison_20261030_v2/structure_comparison.json)
- [新旧 262 条实际模型编译命令](../../build/xs/grhsim_single_fresh_20261030/comparison_20261030_v2/effective_compile_commands.json)
- [去除完整注释后的文本比较](../../build/xs/grhsim_single_fresh_20261030/comparison_20261030_v2/noncomment_comparison.json)
- [模型函数体积比较](../../build/xs/grhsim_single_fresh_20261030/comparison_20261030_v2/model_symbol_comparison.json)
- [batch 13 静态指令分类](../../build/xs/grhsim_single_fresh_20261030/comparison_20261030_v2/batch13_opcode_counts.json)

## 增量：发现第二个混杂因素——可执行代码页位于远端 NUMA

两对 AB/BA 已观察到约 20% 的差异，但检查实际页面分布后，不能把它全部归因于 no-SLP。
CPU96 属于 node1；旧版可执行映射启动快照为 `N1=16480`，新版为 `N0=18400`。
回查 TNO0383 的 8 次正式样本，同样均为新版主要已驻留代码页在 node0。
两边都设置 `membind=1` 仍不足以消除已存在的文件缓存页位置差异。

[页面证据](../../build/xs/grhsim_single_fresh_20261030/comparison_20261030_v2/executable_page_locality.json)
按 maps 的 `r-x` 区域起址关联 numa_maps，避免把匿名状态页与文件代码页混在一起。
目前这些是启动时驻留页的快照，不外推到之后才 fault 的全部页面。

为量化这个因素，将在现有交替序列结束后，创建 SHA256 与当前 emu 完全相同的独立
文件副本，在 CPU96/node1 上写入并预热，检查实际代码页面，再对原 inode 与副本进行
2 对 AB/BA 诊断。使用相同编译产物和 harness，不改 SLP 设置，不迁移或覆盖原文件，
不清除全机 page cache。这个控制仅改变文件实例及其缓存页布局，仍记录布局/缓存等
可能伴随因素；不会用两对诊断冒充 8 对正式优化验收。

局部性控制作为独立实验记录在 [TNO0385](./TNO0385_native_single_thread_code_page_locality_control_20261030.md)；
本篇继续保留完整历史新旧对照及混杂因素的发现过程。

## 完成：历史二进制与本次二进制的 4 对 CPU96 复测

| 顺序 | 旧版无 PERF / 秒 | 本次冻结 emu / 秒 | 本次耗时增加 |
|---|---:|---:|---:|
| 第 1 对 AB | 96.616 | 115.865 | 19.923% |
| 第 2 对 BA | 95.173 | 114.655 | 20.470% |
| 第 3 对 AB | 95.705 | 111.421 | 16.421% |
| 第 4 对 BA | 96.727 | 115.251 | 19.151% |

旧版均值 **96.055250 秒**，本次均值 **114.298000 秒**，均值比慢 **18.992%**；配对百分比中位数 **19.537%**。四对方向一致。

8 次正式对照全部退出成功，无 PERF 输出，提交终点一致；1681 份线程监控均为 CPU96 上一个 TID，CPU288 整段空闲，ASLR 均关闭。预热未纳入均值。

本次重测均值低于 TNO0383 的 118.525 秒，表明绝对 walltime 会随当时环境变化；
新旧交替测量仍持续出现约 16.4–20.5% 的差距。不能把历史日期的 99.339 秒作为固定分母，
也不能用“本次比上次快了几秒”代替新旧配对结果。

两项已确认差异是 no-SLP 编译兼容保护和代码页 NUMA 位置。上述 19.0% 包含这两项
及未完全隔离的源码/harness 差异，**不是 no-SLP 单独造成 19.0% 的证明**。
局部性控制结果见 TNO0385；本轮没有更改编译器保护或生产默认选项。

- [完整样本及汇总](../../build/xs/grhsim_single_fresh_20261030/comparison_20261030_v2/summary.json)
- [逐对 CSV](../../build/xs/grhsim_single_fresh_20261030/comparison_20261030_v2/pairs.csv)
- [独立验收结果](../../build/xs/grhsim_single_fresh_20261030/comparison_20261030_v2/audit.json)

## 补充：直接比较历史 RTL 输入

直接读取 TNO0335 的 `common/rtl/rtl`，与本次 Chisel 新生成目录对比：
两边均为 2,097 个 Verilog 文件，文件集合完全相同，2,093 个逐字节一致。
变化的四个文件是 Ftq、Ifu、PreDecode、LogPerfEndpoint，且各自字节数均未改变。
Ifu/PreDecode 的可见差异是 BranchType 枚举合法性检查项的排列及相应 WIRE 临时名；
Ftq/LogPerfEndpoint 包含计数器排列/命名变化。完整 diff 已保留。
这说明不能宣称历史/本次 RTL 全部相同，也未发现模块数量或生成图规模膨胀。

这里的四文件比较对象是 **10 月 12 日** 的旧流程输入，不是 TNO0382 中使用的
10 月 28 日 RTL 比较对象；两种对照不能混用。

[RTL 哈希对照](../../build/xs/grhsim_single_fresh_20261030/comparison_20261030_v2/rtl_comparison.json)。

## 局部性控制已完成

[TNO0385](./TNO0385_native_single_thread_code_page_locality_control_20261030.md) 的相同字节
控制为 114.8685→109.7375 秒，耗时减少 4.47%，两对方向一致；整个正式窗口的周期性
页面快照都通过。确认页面布局确实贡献成本，但不能把剩余差值全部归因于编译器。
没有发现本轮的 Difftest、CPU 绑定或图规模异常；确认了性能比较口径的两项实质差异，
并修正了 TNO0383 对有效编译参数及 NUMA 页面位置的遗漏/不准确概括。
