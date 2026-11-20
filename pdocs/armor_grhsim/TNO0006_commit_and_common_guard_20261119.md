# TNO0006：单核 XiangShan 的寄存器提交分组与归约公共输入保护

**优先把同读者寄存器提交分组纳入这份单核 XiangShan 的后续性能基线。** 它的端到端 walltime 下降 2.845%，八轮配对区间完整落在零以下。归约公共输入保护将退休指令降低约 2.22%，当前窗口的整机时间区间仍跨零。

A 使用 CV32 系列 TNO0049 的 shared-arm 和紧凑快照，沿用原掩码位序。C 只启用已有的 `commit_scalar_same_reader_groups`，F 只启用本轮新增、默认关闭的 `reduction_common_guard`。两项分别和 A 比较。新 emitter 关闭选项时逐字复现 XS 的 140 个和 CV32 的 21 个生成文件。[上轮诊断](./TNO0005_post_mask_headroom_20261118.md) · [生成配置与发布二进制](../../build/armor-followup-v1/policy.json) · [源码对照](../../build/armor-followup-v1/source-audit.json)

## 提交分组

C 面向同一写使能和同一组读者的连续标量寄存器写入。它先计算各成员的 `changed`，任一成员变化时才写回这一组，同时更新精确的读者通知。XS 的 31 个 commit 文件中，24,428 组覆盖 111,506 次写入。逐文件核对了原操作身份和次序。CV32 命中 11 组、34 次写入。[原有选项和语义条件](../../wolvrix/docs/emit/grhsim-scheduling.md#L772) · [逐批覆盖](../../build/armor-followup-v1/source-audit.json)

上轮定位的 APLIC 中断同步器把八个相邻布尔输入写到八个相邻状态。原 ELF 在整组相等的路径上执行八套字节加载、比较和条件跳转，候选编成 `mov rax,QWORD PTR [rdi+0x16193]`、`cmp QWORD PTR [rdi+0x35775c],rax` 和一条 `jne`。在 batch 90 已对齐源／目标的 35,738 个寄存器中，A 能逐项匹配到 35,738 处单成员比较。C 能匹配到 2,925 处八成员比较和 203 处四成员比较，共覆盖 24,212 个成员。这里仅统计相邻的、地址和寄存器均可核对的加载、比较、跳转序列，其他指令形态另计。该函数由 3,713,239 B 降到 2,018,895 B。沿用编译器已经产生的宽比较即可评价这一机制。[生成 C++](../../build/armor-followup-v1/C/xs/model/grhsim_SimTop_sched_90.cpp#L209) · [原 ELF 八路](../../build/armor-followup-v1/machine/full-aplic-eight.s) · [候选 ELF 八路](../../build/armor-followup-v1/machine/commit-aplic-eight.s) · [地址核对](../../build/armor-followup-v1/machine/witnesses.json)

在 C 的实际分组中额外记录每次组判断的成员变化数。100k 窗口共执行 1,393,242,538 次组判断，93.55% 整组相等。89,896,249 次组内有变化，共有 170,787,673 个成员变化。每个变化组只发布一次共同读者集合，因此比逐成员发布少了 80,891,424 次重复集合通知。同时，变化组写回全部成员，源码层面多写回 170,182,780 个未变成员。二者是逻辑成员和通知集合数，实际宿主 store 可按字或向量合并。这份诊断副本也逐条通过 99,999 条 DiffTest 记录，耗时不进入配对。[按批次的真实变化和额外写回](../../build/armor-followup-v1/commit-counters/verified.json)

## 归约公共输入

只有当整个 compute supernode 都由一个已经打包的输入字及其 AND/NAND 或 OR/NOR 归约组成，且各标量输出槽均由本组独占时，F 才能跳过整组。它读取原快照里所有谓词共有的位。以 AND 家族为例，任一公共位为零便能确定每一个输出。首次满足条件仍正常计算并发布各输出，连续满足条件时才短路。每个模拟器实例为每个符合条件的组保存一个布尔标记，重新初始化清零，完整求值路径先使标记失效。生成带性能计数、运行时 profile 或波形的模型沿用普通路径。[选项、适用条件及示例](../../wolvrix/docs/emit/grhsim-bool-reduction-masks.md)

F 在 XS 命中 329 组、15,502 个归约。逐组对回冻结调度图，这个设计命中的均为一位 AND 归约。相比上轮的 328 组文本筛选，图和存储证明还接纳了 28132，其中有一个结果直接更新活动位。按原生成代码核对了全部 329 组公共输入的物理槽号。剥除保护语句、私有标记和初始化后，所有文件均逐字还原为 A。CV32 命中零组，21 个文件及发布 ELF 的 `.text/.rodata/.data` 与 A 完全相同。[原调度操作](../../build/armor-followup-v1/factor-grh.json) · [逐组输入核对](../../build/armor-followup-v1/source-audit.json) · [CV32 ELF 节](../../build/armor-followup-v1/F/cv/sections.json)

在独立计数版的 100k 周期窗口中，共激活 16,616,117 次，实际跳过 16,286,184 次（98.014%）。逐组命中数与 A 的原始输入历史完全一致，99,999 条 DiffTest 记录通过。batch 21 的 28016 组在发布 ELF 里先读原有的三个布尔快照，再查本实例的阻断标记。连续阻断时，自活动判断通过到跳过最后两个读者通知共 11 条指令，原版对应路径是 616 条。F 也增加了控制分支，必须单独观察整机执行效果。[实测跳过次数](../../build/armor-followup-v1/factor-counters/verified.json) · [原始判定](../../build/armor-post-mask-analysis-v1/A-group28016.s) · [候选保护路径](../../build/armor-followup-v1/machine/factor28016-short.s) · [分支目标](../../build/armor-followup-v1/machine/factor28016-target.s)

| XS 静态机器码，以各自有改动的调度批次为范围 | C 相对 A | F 相对 A |
| --- | ---: | ---: |
| 批次 | 31 个 commit | 12 个 compute |
| 机器指令 | −644,515（−25.14%） | +5,214（+0.19%） |
| 条件跳转位置 | −154,386 | +618 |
| 受影响函数的代码字节 | −4,176,731 | +25,359 |
| 整份 ELF 的 `.text` 字节 | −4,176,736 | +25,392 |

静态统计汇总了受影响批次中的主函数和 helper。两种方案的工作方式不同，C 将重复的比较合并；F 保留普通路径，在入口增加能够越过整个计算体的判断。[逐符号 ELF](../../build/armor-followup-v1/machine.json)

## 验证与测量口径

- 最终五项 CTest 全部通过，覆盖新保护、已有同读者提交、掩码布局、共享归约与 execution plan。新用例包含两种极性的 AND/NAND、OR/NOR、混合家族、无公共位及额外独立运算的回退、公开输出、重复 eval、重复 init、两个实例、完整求值和 O0／O3 ASan／UBSan。首次回归把性能模式写成 `on`，修正成仓库实际使用的 `eval` 后重跑。编译和发布功能验证使用相同型号的 EPYC 9684X，node029 与 node030 的 Clang 23 native 目标 CPU 和 115 个目标特性条目逐项相同。[最终 CTest](../../build/armor-followup-v1/final-ctest.log) · [目标特性](../../build/armor-followup-v1/native-target.json)
- XS 的功能验证在 node029 上与已冻结的 A 对齐，另在 node030 单线程 CPU96／NUMA1、关闭 ASLR 后测量 walltime。每种设计每轮运行 A、C、F 三份发布二进制，八轮交替 A→C→F、F→C→A，每个候选与同轮 A 配对。两项共用每轮的基线样本。外部 walltime 的主统计是八个 `100 × (候选/A − 1)` 的算术均值及原固定种子的 10,000 次配对 bootstrap 区间。PMU 另用 A→C→F→F→C→A 的顺序，按完整 enabled/running 纳秒校正用户态进程计数，区分退休指令、周期与前端供给。[测量程序](../../scripts/armor_followup_measure.py)

XS 的 C 和 F 均通过 10k smoke，两个 seed 各 100k 周期，每份 release trace 的 99,999 条记录与冻结 A 一致，终点均为 PC `0x80000c1a`、250,838 条 guest 指令和 100,001 个 guest cycles。CV32 在 smoke 和完整 CoreMark 上逐周期核对总线轨迹。C 的 331 项诊断中有 330 项（包括区域访问、求值轮数和具体值变化）逐项相同。唯一变化项记录真正执行的活动位 OR 次数，CoreMark 少 2,190,870 次，smoke 少 134 次。另在各提交组按实际变化成员数、共同读者掩码数计算省去的 OR，四个时钟相位分别与差值完全相等。F 的 331 项原始计数全部相同。[XS 发布版核验](../../build/armor-followup-v1/functional-xs/verified.json) · [CV32 完整轨迹](../../build/armor-followup-v1/measurement/cv/functional.json) · [逐相位通知复核](../../build/armor-followup-v1/measurement/cv/counts-check.json)

## 固定八轮的 walltime

| 设计 | 独立候选 | A 平均秒数 | 候选平均秒数 | 配对均值 | 配对 bootstrap 95% CI | 候选较快 |
| --- | --- | ---: | ---: | ---: | --- | ---: |
| XiangShan | C 提交分组 | 121.383 | 117.859 | -2.845% | [-3.644%, -1.819%] | 7/8 |
| XiangShan | F 公共输入 | 121.383 | 119.391 | -1.503% | [-5.147%, +2.303%] | 7/8 |
| CV32 | C 提交分组 | 2.868 | 2.861 | -0.227% | [-0.469%, -0.004%] | 6/8 |
| CV32 | F 公共输入 | 2.868 | 2.861 | -0.252% | [-1.009%, +0.248%] | 5/8 |

每个设计保留全部 24 个正式样本。区间由同轮比值重采样，秒数列为各自的算术均值。第四轮 XS 的 A/C/F 分别约为 112.59/112.92/122.77 秒，与前三轮的绝对时间有明显差别。完整功能、CPU 和 NUMA 检查均通过，该轮完整保留。[逐轮秒数与放置](../../build/armor-followup-v1/paired-walltime.csv) · [独立复算](../../build/armor-followup-v1/review.json)

## 发布 ELF 的成组硬件计数

| 每 guest cycle 的用户态事件 | A 第一份原值 | C/A 两次配对变化 | F/A 两次配对变化 |
| --- | ---: | --- | --- |
| 退休指令 | 3,656,555 | -3.878% / -3.852% | -2.228% / -2.214% |
| host cycles | 4,007,128 | -3.504% / -4.961% | +21.378% / -3.413% |
| 前端未提供操作的槽位 | 18,019,495 | -4.070% / -5.713% | +26.176% / -3.881% |
| L1I miss | 731,420 | -7.367% / -7.668% | -3.454% / -5.349% |

事件包含初始化、模型、harness 和 NEMU。六份样本在 CPU96 单线程完成，事件实际运行时间最低为 99.52%。计数按完整 enabled/running 纳秒校正，两组配对主要用于判断执行工作是否减少。[事件原值和运行比例](../../build/armor-followup-v1/pmu/raw.json) · [计数差值](../../build/armor-followup-v1/pmu/summary.json)

## 对下一轮的取舍

提交分组在两对 PMU 中均少执行约 3.85%–3.88% 的宿主指令，L1I miss 下降 7.37%–7.67%，前端供给空槽也下降。连同宽比较的发布机器码和八轮外部计时，这支持在当前 XS 配置中选用 `commit_scalar_same_reader_groups=1`；现有记录不能把节省的秒数在前端和执行端之间精确分摊。CV32 的同方向时间变化较小，95% 区间上界仅为 −0.004%。

归约保护可在 `reduction_common_guard=1` 下复现。退休指令稳定下降，但两组 PMU 的 host cycles 分别为 +21.38% 与 −3.41%，前端供给空槽分别为 +26.18% 与 −3.88%。正式八轮中同核 CPU288 的最低空闲率为 99.94%；现有记录无法确定耗时波动的具体来源。F 适合留作独立候选，下一步可在启用 C 的发布基线上，用另一段工作负载直接测 F 的增量及组合收益。两项开关的全局默认均为关闭。
