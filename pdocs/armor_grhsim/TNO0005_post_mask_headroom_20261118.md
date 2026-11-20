# TNO0005：XiangShan 的掩码读取、归约输出与寄存器提交

**下一轮优先验证相同读者的连续寄存器提交；compute 的第二选择是让公共输入一次决定整组归约结果。** 在现有 100k 周期 CoreMark 窗口，上一轮输入掩码优化确实少执行了约 0.24% 的宿主指令，正式八对 walltime 仍未确认加速。下列两个方向都能针对大段重复执行的比较，在当前生成 C++ 和实际 ELF 中有可定位的样例。[上一轮八对原始数据](../../build/armor-mask-read-v1/measurement/paired-walltime.csv) · [本轮计数汇总](../../build/armor-post-mask-analysis-v1/findings.json)

## 上一轮的收益去了哪里

较早的逐 lane 打包在 305 个包上仍须收集输入，302 个包还须逐路交付输出，受影响函数实际增加 6,459 条静态指令，实验停在 ELF 检查。后续实验把改动收窄到已经共享的归约输入字。[逐 lane 打包实验](./TNO0002_boolean_lane_experiment_20261118.md)

A 是保留 shared-arm 和紧凑快照的 CV32 系列 TNO0049 基线。P 只在原 32 位半字内重排布尔槽和谓词常量，B 再将连续八个布尔字节一起读取。B 改了 XS 的 433 个共享输入字，27 个 compute 批次所含的 28 个函数合计少 11,502 条静态指令，约占这些函数原指令数的 0.19%。完整 ELF 的 `.text` 少 64,208 B，占 88,856,754 B 的 0.072%。CV32 零命中，三版生成文件相同，原 A/B 的关键 ELF 节相同。[冻结源码和机器码](../../build/armor-mask-read-v1/frozen/machine.json) · [双模型功能和配对结果](./TNO0004_reduction_mask_layout_20261118.md)

以 batch 21 的 supernode 28016 为例，63 个输入布尔槽生成一个字，54 个 AND 归约各自与旧结果比较、更新槽位，最后按两个读者集合汇总通知，分别覆盖 51 个和 3 个输出。先前量到的 52→33 个输入地址访存位置只覆盖到第一个输出写回。从活动判断通过后数到最后一条读者通知，A/P/B 的无内部分支路径分别有 **616/625/636 条指令**，代码字节为 3,370/3,328/3,397。B 确实用了两条 PEXT，但谓词寄存器搬动、掩码运算、旧输出比较和通知仍在。该组在窗口内执行 50,030 次，54 个输出共比较了 2,701,620 次，实际变化为零。这一例与整个 batch 21 净少 4,494 条指令并不矛盾。[生成的 A](../../build/armor-mask-read-v1/frozen/xs/A/model/grhsim_SimTop_sched_21.cpp#L113491) · [生成的 B](../../build/armor-mask-read-v1/frozen/xs/B/model/grhsim_SimTop_sched_21.cpp#L113840) · [A 反汇编](../../build/armor-post-mask-analysis-v1/A-group28016.s) · [P](../../build/armor-post-mask-analysis-v1/P-group28016.s) · [B](../../build/armor-post-mask-analysis-v1/B-group28016.s)

对三份 ELF，用活动位、全部目标槽的实际地址和全部读者通知字节匹配，得到 228 条可逐指令计数、彼此不重叠的直线路径。其中属于本轮命中组的 153 条，按 A 的实测激活次数加权，A 约占全进程退休指令的 **1.10%**，B 在这批路径上约少 **1,616 条/guest cycle**。这里沿用 A/B 相同调度、活动语义及 trace 对应的访问次数，结果只覆盖成功匹配的指令区间。历史 A 端前端供给空槽采样中，27 个完整 compute 批次合计占 compute 样本的 52.23%，这 153 段本身只有 762 个样本，占全进程 184,975 个样本的 0.41%。采样 PC 可能有 skid。按整个函数的热度估计一次局部改动，会明显放大它的权重。[路径、地址和匹配方法](../../build/armor-post-mask-analysis-v1/paths.json) · [按访问次数加权](../../build/armor-post-mask-analysis-v1/findings.json) · [基线符号采样](../../build/armor-lane-v1/pmu-A/report.json)

在 node030 CPU96／NUMA1 单线程、关闭 ASLR、共享测量锁下，对原 A/B 发布 ELF 独立运行 ABBA，顺序为 A₁、B₁、B₂、A₂。以下为同一组用户态事件按 guest cycle 归一的数值，覆盖从进程启动至退出，包括初始化、harness、DiffTest 和 NEMU。

| 指标 | A₁ | B₁ | B₁/A₁ | B₂/A₂ |
| --- | ---: | ---: | ---: | ---: |
| 退休指令 | 3,655,548 | 3,647,057 | −0.232% | −0.244% |
| host cycles | 4,082,616 | 4,048,253 | −0.842% | −0.227% |
| 前端未提供操作的槽位 | 18,441,130 | 18,254,347 | −1.013% | −0.258% |
| L1I miss | 736,593 | 735,064 | −0.208% | −0.196% |

PMU 直接表明该窗口执行的工作量小幅下降。两对 PMU 不足以分解前端和执行端各自节省的时间。曾先用 `perf stat --no-scale` 取得一组显示运行比例为整数的计数；表中使用另外一组 `perf stat record`，从内核记录读取完整 enabled/running 纳秒后缩放。运行比例最低 99.55%，四次同核 CPU288 均为空闲。正式八对 walltime 为 **+2.122%，95% CI [−1.459%, +7.472%]，4/8 更快**，最大差异一对的兄弟线程占用也有明显变化，全部样本均保留。[四次精确 PMU](../../build/armor-post-mask-analysis-v1/pmu-record/raw.json) · [计数方法](../../build/armor-post-mask-analysis-v1/perf_exact.py) · [perf stat 手册](https://man7.org/linux/man-pages/man1/perf-stat.1.html) · [八对独立复核](../../build/armor-mask-read-v1/measurement/review.json)

## 首选验证连续寄存器的整段比较

`eval_commit_batch_90()` 在 A 的 ELF 中占 3,713,239 B。它是原前端空槽采样中样本最多的单个 commit 批次，7,968 个样本，占全进程样本的 **4.31%**、commit 样本的 26.3%。函数只含一个上升沿活动组 85029，生成 C++ 有 66,062 个寄存器写。这里可以直接检查两排连续数据，即 compute 已保存的 next 值和 commit 即将更新的状态。跨 C++ 字段的物理相邻性已用同一份头文件编译得到的实际字段偏移核对。[生成的 commit](../../build/armor-mask-read-v1/frozen/xs/A/model/grhsim_SimTop_sched_90.cpp#L42) · [源码匹配及 ELF 身份](../../build/armor-post-mask-analysis-v1/commit90.json)

在同一写使能下，只接受语句连续、类型和读者通知完全相同、源槽和目标字段都按元素宽度相邻的普通标量写，最短四项。3,972 段共 **35,738 项**，占该批次写入的 54.10%。APLIC 中断源同步器有一段 63 个布尔寄存器，前四项均通知活动字节 7 的掩码 128。实际 ELF 对四个相邻输入和四个相邻目标生成了 **四套 `movzx / cmp / jne`**。Clang 23 在这个发布二进制里仍逐成员分支。[四项的 C++](../../build/armor-mask-read-v1/frozen/xs/A/model/grhsim_SimTop_sched_90.cpp#L209) · [同四项的反汇编](../../build/armor-post-mask-analysis-v1/commit90-release.s) · [逐段地址](../../build/armor-post-mask-analysis-v1/commit90-runs.json)

另外用观察版 eval 在调用原 commit 函数前比较这 3,972 段，在调用后核对每段状态。100,050 次上升沿的写使能均为真。整段检查中，有 **383,503,922 / 397,398,600（96.50%）整段相等**。逐成员统计则只有 **37,486,914 / 3,575,586,900（1.05%）** 不等。APLIC 的 63 项在全部 100,050 次都相等。提交后检查的全部目标都等于对应 next，完整 DiffTest 也通过。该结果只描述这一负载窗口，任何允许的输入仍须走正确的变化路径。[实际整段及成员计数](../../build/armor-post-mask-analysis-v1/commit-run/verified.json) · [逐段原值](../../build/armor-post-mask-analysis-v1/commit-run/counts.txt) · [trace](../../build/armor-post-mask-analysis-v1/commit-run/trace.json)

**首个单变量实验可直接复用 `commit_scalar_same_reader_groups`。** 现有实现已证明普通单写者、全掩码、同一 guard、精确读者集合和已保存的 next 值，并将 2–8 项的变化汇总为一个判断。先看当前单核模型实际接纳哪些段，以及代表性 ELF 是否出现一次宽比较和一次跳转。若组内还在逐项计算比较，再对源和目标物理连续且表示可按字节比较的成员显式合并。在全部相等的路径直接越过整段，变化路径保留精确写回、通知和诊断计数。3,972 段是 C++ 与布局筛选结果，最终适用数量由 execution plan 和可见性证明确认。旧的 32 分区实验曾观察到 16 对 walltime 中位变化 −0.626%，该结果属于另一调度和线程配置。[现有分组实现](../../wolvrix/lib/emit/grhsim_cpp.cpp#L27819) · [选项和语义](../../wolvrix/docs/emit/grhsim-scheduling.md#L772) · [历史对照](../grhsim_opt_thj/TNO0333_repcut_grhsim_backend_20260925.md#L3779)

## 第二选择是利用整组归约共有的输入

在 667 个含共享归约掩码的 compute 区域中，335 个只包含输入收集、谓词计算、标量输出写回和活动位通知。再要求单个输入字、全部谓词同属 AND 或 OR、共同掩码非空，并筛掉字面地址扫描可见的其他写入和指针接触，剩 **328 组、15,448 个谓词**。这些组完成了 780,239,378 次输出比较，输出实际变化 **50 次**。连续激活有 16,564,577 次，整个输入字重复 **0 次**。在这些组上每次构造完整输入字再查上次缓存，仍需付全部收集成本，且此次没有一次命中。[纯归约组筛选](../../build/armor-post-mask-analysis-v1/closed.json) · [动态计数](../../build/armor-post-mask-analysis-v1/findings.json)

一个 AND 归约家族的全部谓词若都用到某组公共位，只要其中一位是 0，全部 AND 结果便已确定。对 OR 家族，只要有一个公共位是 1 即可，末端的取反沿原极性处理。首次满足条件时仍须把结果和通知正常落地；若下次激活仍满足条件，且这些槽一直由本组独占，就有机会在读取其余输入前跳过整个区域。

| 在 328 组的相邻激活中检查的条件 | 能连续确定整组结果的次数 | 比例 |
| --- | ---: | ---: |
| 上下两次完整输入字相等 | 0 | 0% |
| 只检查原私有位序中最低的公共位 | 1,045,389 | 6.31% |
| 检查来自所有谓词交集的 3–14 个公共位 | 16,238,028 | **98.03%** |

公共位的选择由原表达式静态决定。按实际激活加权，完整输入字平均包含 43.57 项，公共部分平均为 6.68 项。310 组的公共位均可追到直接的标量切片，51 组的切片还来自同一标量和同一生产区域。例如 28016 的三个公共输入来自同一 `uint32_t` 的 bit 0、1、2。若要改为读原标量并一次做掩码比较，还须证明使用时读到的是这些快照对应的同一版本。现有 `bool_zero_group_guard` 面向共享一个状态操作数的标量 AND 赋值，在当前归约 lowering 上需单独验证适用性。[公共位的生产位置](../../build/armor-post-mask-analysis-v1/factor-sources.json) · [示例的生产 C++](../../build/armor-mask-read-v1/frozen/xs/A/model/grhsim_SimTop_sched_0.cpp#L238294) · [现有零值保护](../../wolvrix/docs/emit/grhsim-scheduling.md#L130)

在上述 328 组中，221 组能逐条绑定原 ELF 直线路径。按实际相邻激活加权，检查所有公共位可判定结果的访问中，这些旧路径占 A 全程退休指令 **1.51%**；只查固定一位时为 **0.091%**。前者是这 221 组可绕过的旧代码体量，尚须支付公共输入读取、分支和阻断状态维护，另外 107 组未计算机器码贡献。优先使用少数已有物化值能决定结果的家族，并在初始化、复位、恢复快照、全求值及其他写者出现时保护状态有效性。代码审计不能凭一次 trace 把某个输出折成常量。[全部匹配的 ELF 指令范围](../../build/armor-post-mask-analysis-v1/paths.json) · [加权复算](../../build/armor-post-mask-analysis-v1/findings.json)

## 证据边界与复现

- 生产 PMU 与按地址统计的指令均来自冻结的发布 ELF，Clang 23 `-O3 -march=native`。两次逻辑计数和一次提交观察均在 node029 CPU96／NUMA1 独立运行，仅使用逻辑计数。两种 compute 观察版有一个仅供计数的编译单元改用 `-O1`，其余模型单元沿用原优化级别；第二版复现了第一版的所有共有计数。commit 观察版复用原 A 的模型静态库，仅替换包围调用的 eval 对象。三份独立运行各自与原版 99,999 条 DiffTest 记录逐条一致，终点 PC 为 `0x80000c1a`、guest 指令 250,838、guest cycles 100,001。观察版的耗时均未纳入性能结果。[首份计数](../../build/armor-post-mask-analysis-v1/counter-run/verified.json) · [公共输入计数](../../build/armor-post-mask-analysis-v1/factor-run/verified.json) · [提交计数](../../build/armor-post-mask-analysis-v1/commit-run/verified.json) · [诊断编译记录](../../build/armor-post-mask-analysis-v1/instrumented/compile-note.json)
- 整个 compute 中，每 guest cycle 有约 141,257 次可识别的标量新旧值检查，其中 5.43% 不等。此口径只覆盖直接比较 `value_*_slots_[i] != next_value` 的位置，其他控制流、向量路径和 commit 的状态比较另计。全局低变化率本身不足以删除检查。连续提交与公共输入归约分别提供了能保持原活动语义的具体条件。本轮只分析并构造观察副本，正式 walltime 沿用上一轮，两个新方向均待生产对照验证。[计数插入位置](../../build/armor-post-mask-analysis-v1/instrument_model.py) · [提交观察方法](../../build/armor-post-mask-analysis-v1/commit_observe.py) · [证据复核](../../build/armor-post-mask-analysis-v1/verified.json)
