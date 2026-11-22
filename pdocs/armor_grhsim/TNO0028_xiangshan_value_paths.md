# TNO0028　香山 FTQ 写口求值、ROB 重复结果及逐站点分支复核

第四条已经落在生成器中。保留 0.5% 稀疏写回和 20% 无分支提交，额外给单写口的长 mux 链开启按需计算。每项计时 100,001 个 guest cycles，先后顺序交换四轮，两个负载均为 4/4 轮加快。CoreMark 与 MicroBench 四轮的耗时变化范围分别是 −2.99% 至 −1.66% 和 −1.62% 至 −0.71%。以下基线是上轮已经开启两种写回优化的 GrhSIM。相对 GSIM 的差距也在本轮直接测量。[逐轮原始数据](./data/TNO0028_value_path_samples.csv) · [ELF 身份与完整计数](./data/TNO0028_value_paths.json)

| 负载 | 上轮基线 | 开启 FTQ 规则 | 同轮 GSIM PGO | 相对基线耗时 | 退休指令/拍变化 | 相对 GSIM 的耗时差 |
|---|---:|---:|---:|---:|---:|---:|
| CoreMark | 70.70 s | 68.97 s | 56.77 s | −2.45% | −69,436 | +24.54% → +21.49% |
| MicroBench | 64.81 s | 64.02 s | 53.74 s | −1.22% | −54,945 | +20.59% → +19.12% |

绝对秒数取四轮墙钟均值，百分比先按轮配对再平均。CoreMark 训练，MicroBench 留出。node030 上两种负载分别固定 CPU 104、120，关闭 ASLR，程序、参考模型和固件在本地 NUMA。汇总只纳入完成同轮对照、通过 SMT 空闲率、进程占用、PMU 运行比例及 guest 终点检查的样本。阈值与结构探索使用独立轮次，额外的缓存诊断用了不同物理核。一次重放使用了普通构建的 108 操作上限，配置核对后改回 PGO 的 160，正式对照使用了相同调度设置。[实验脚本与复现顺序](./data/TNO0028_experiment_scripts.tar.gz)

正式版相对 GSIM 每拍还多执行约 66.6 万 / 55.2 万条指令。两边都有失去源码行号的指令；这部分差距和上轮的多读者边界仍需分别定量。将一条热表达式的采样权重全部视作可节省指令，会高估窄改动的空间。

## FTQ 的执行次数更正

上轮的归属器把 GSIM 名字中的每个 `__DOT__` 都当成实例层级。FIRRTL 在 `Ftq` 中声明了寄存器 `perfQueue`，其中有字段 `cfiAttr.branchType`。遇到 `perfQueue` 后，原归属器还在子模块表中查这个名字，把整条赋值记成归属未知。现在先沿真实实例向下走，遇到当前模块声明的信号后，将剩余的聚合字段归给该模块。两种负载的指令采样和源码覆盖均已重算。[采样归属器](../../scripts/armor_xs_gap_diagnostics/value_modules.py) · [动态赋值计数](../../scripts/armor_xs_gap_diagnostics/module_assignments.py)

| CoreMark，每 guest 拍 | GSIM 赋值 | GrhSIM 赋值 | GSIM 归属指令/次 | GrhSIM 归属指令/次 |
|---|---:|---:|---:|---:|
| FTQ | 19,409 | 21,084 | 0.45 | 6.33 |
| ROB | 108,681 | 60,732 | 0.86 | 4.67 |
| VectorDecodeChannel | 64,680 | 45,148 | 5.09 | 6.52 |

MicroBench 的 FTQ 是 19,271 和 16,762 次/拍，对应 0.41 和 6.86 条归属指令/次。赋值分母来自 Clang 覆盖，指令分子来自有对应生成语句和模块的 ELF 采样。二者一起刻画代码形态。GSIM 的聚合赋值尤其容易被合并，单行的指令数不能直接乘作可节省的工作量。[两侧模块归属及事件原始数](./data/TNO0028_value_paths.json)

## 第四条　把 FTQ 下一值放到需要它的写口

以 `perfQueue[36].cfiAttr[10].branchType` 为例。GSIM 在 `SimTop238.cpp` 把该字段从 `s3PerfQueue` 拷给 `perfQueue$NEXT[36][10]`，同一个函数依次复制 `branchType` 和 `rasAction` 各 64×32 个字节。CoreMark 和 MicroBench 都执行了 100,101 遍这两个字段的赋值，共约 4,100 次源码赋值/拍，包含复位。编译后只有 64 个赋值行号挂有可核对的指令，覆盖多个控制流副本。ELF 地址 `0x2c9a6d9` 的 `vmovups` 一次读入 64 字节，`0x2c9a708` 一次写回 64 字节。数组赋值之前仍有生成写入数据的工作。[GSIM 字段及 ELF 摘录](../../build/armor-xs-value-paths-v1/gs_copy.json)

GrhSIM 从展开后的 RTL 产生 4,096 条 13 层优先级 mux 链。在例子中，计算组先形成局部值 772201、772207，把结果 772208 存入 `value_u8_slots_[35685]`。提交分片 81 先检查 `value_bool_slots_[712676]`，打开才取这个槽并与寄存器比较。逐槽核对发现 4,096 个结果都只有一个标量写口读者，数据块比较也没有读取它们。各链的输入合计使用 26,624 个布尔槽和 198 个字节槽。本布局的提交代码对这些输入槽均为只读。[生成的计算代码](../../build/armor-xs-mode-defaults-v1/pgo/model/grhsim_SimTop_sched_54.cpp#L87847) · [生成的提交代码](../../build/armor-xs-mode-defaults-v1/pgo/model/grhsim_SimTop_sched_81.cpp#L2098)

| 次数/guest 拍 | CoreMark | MicroBench |
|---|---:|---:|
| 原布局计算完整链 | 2,004.1 | 1,587.3 |
| 进入对应写口的比较 | 30.3 | 22.2 |
| 按源码展开的 mux 选择数，原布局 → 写使能内 | 26,053.8 → 393.8 | 20,634.8 → 288.1 |
| 原 PGO 中映射到链赋值行的退休指令估计 | 51,835 | 41,809 |

独立核对版保留全部旧计算，在每次有效写口上重新计算链并逐值断言相等。CoreMark 前 100,001 拍和完整 MicroBench 均通过。短窗口里，两种负载各自都访问过这 4,096 个写口，CoreMark 比较了 3,028,992 次，MicroBench 前 100,001 拍比较了 2,216,512 次。两种窗口内发生的具体输入组合受固件限制。[源级覆盖和叶子读写核对](../../build/armor-xs-value-paths-v1/chain_counts.json) · [逐写口核对](../../build/armor-xs-value-paths-v1/shadow)

冻结布局只移动上述 4,096 条链，重新训练 Clang PGO。相对上一轮已经开启稀疏写回及无分支提交的基线，两轮同核换序，CoreMark / MicroBench 分别少执行 64,666 / 50,887 条指令每拍，耗时下降 1.82% / 2.17%。计算分片 54 的 ELF 函数从 1,527,026 字节降到 707,363 字节，例子对应的行从 53 条可定位指令降到 0。提交分片 81 从 359,170 字节增至 1,035,267 字节，相同写口在保留使能判断后出现了 mux 输入读取。各分片长度包括其他字段，行号摘录的静态指令数也包含多个分支，整机时间采用实际计时。[基线分片](../../build/armor-xs-value-paths-v1/elf/both05) · [移入写口后的分片](../../build/armor-xs-value-paths-v1/elf/ftq)

## ROB 的算术和调度

CoreMark 在 ROB 的可识别赋值中，`kMux`、`kOr`、`kAnd` 分别占约 76,769、76,166、53,722 条指令/拍，`kConcat` 为 6,264 条。按位 OR 的冻结模型试验将 640 个至少读取 5 个布尔槽的表达式改成有界的 8 字节读取和掩码，共 1,117 处合并读取。值 975546 的行表映射从 10 条指令减至 3 条。检查邻接机器码可见，宽读版还在该行之前执行了 `movq`、`andq` 和 `bzhiq`，部分字节为其他输出复用。全模型只少了 1,291 / 1,127 条指令每拍，耗时两轮均值为 +0.27% / −0.98%。该试验的收益不足以支持优先改写整个 ROB 的布尔表达式。[原函数邻近指令](../../build/armor-xs-value-paths-v1/elf/both05/or-window.asm) · [宽读版邻近指令](../../build/armor-xs-value-paths-v1/elf/rob/or-window.asm)

第三条的七路信号在两个调度轮次内先后失去了上轮规则的两个适用条件。以第 4 路为例，第一次兄弟合并前，1 个操作的生产簇有两个读者簇，各含 4 和 75 个操作。下一轮两个读者已经合到同一个 80 操作的簇，生产簇却已含 5 个操作。它除了输出 `uopCanEnqSeq_4_67`，还向两个簇输出 `entryEnqValid_4_67`，因此共有 3 个后继。随后一次兄弟合并让该生产簇增至 160 个操作、27 个后继。前一次规则要求至多 4 个操作且只有 1 个可行后继，两个时刻都选不到这条线。[逐阶段簇和边的值来源](../../build/armor-xs-value-paths-v1/cluster.json)

继续追到原 RTL，`Rob.sv` 的第 189189 和 267603 行给两个名字赋的都是 `uopCanEnqueue_4 & robIdxMatchSeq_4_67`。图中操作 1229963、1283334 的输入 ID 和次序完全相同。生成器在同一簇把相同结果存进两个槽。前一份的读者通知已覆盖后一份的所有通知。冻结模型试验逐对检查输入、组号、第一次写入位置、唯一写者和通知集合，并排除通过指针区间访问的槽。以先计算的槽服务两组读者，条目 67 的 7 路全部合并，全 ROB 有 1,051 对符合条件。每拍消掉 644 / 493 次重复检查。[重复槽原型](../../build/armor-xs-value-paths-v1/duplicates.py) · [入选寄存器和读者掩码](../../build/armor-xs-value-paths-v1/dup/dup.json)

全模型进一步审计了同一计算组中结果类型、操作种类、属性和有序输入全同的标量计算检查点。所查的 13 类表达式里，5,677 个重复结果在两边负载的逐点访问数、变化数、方向翻转数和两位预测器错误数都与原值一致。即使都能证明共享槽合法，该集合每拍最多可删约 1,717 / 1,401 次检查，其中 AND 占 1,580 / 1,270 次。其余多读者和容量受限的单读者边仍需从各自的热路径分析。此上限只覆盖有站点计数的指定操作，允许交换输入、跨组重算和其他代数等价会得到不同的集合。[按操作的上限](../../build/armor-xs-value-paths-v1/equivalent_ops.json)

合槽单开经过三轮对照，CoreMark / MicroBench 的退休指令每拍减少 7,132 / 5,200 条，耗时分别为 −0.91% / +1.01%。在 MicroBench 上换两个物理核补测，各做三轮。一个核上平均慢 0.33%，前端没有指令可分发的计数增加 0.68%，从 L2 以外填入的指令行少 0.17%。另一个核上平均快 0.62%，L1D 读减少 0.37%，L1D 读未命中减少 0.05%。直接删除重复结果能稳定减少工作，首次观察到的 1% 耗时回退在换核后没有稳定复现。将其与 4,096 条 FTQ 原型一起开启，相对同轮基线快 2.37% / 1.70%。此次保留合槽实验，优先合入已有跨负载收益的 FTQ 规则。[配对计时、前端与数据缓存事件](./data/TNO0028_value_path_samples.csv)

剩余 ROB 指令里还有一类可以具体定位。6,080 个布尔 mux 的两条分支都与同一个值做 OR 或 AND。例如，值 959726 对应 `Rob.sv:244578` 的 `cond ? (a | common) : (b | common)`。在原 PGO 的两个窗口里，这一类表达式每拍分别执行 2,784 / 2,099 次，采样估计对应约 29,792 / 24,017 条宿主指令。冻结正式 FTQ 模型，只在这六个计算分片把它改写为 `(cond ? a : b) | common` 或相应的 AND。首次在分片 20 复用旧 PGO，Clang 检测到控制流哈希变化并丢弃该函数计数，所以单分片大小未计入速度对照。随后用自己的 CoreMark profile 完整重建。[表达式计数](../../build/armor-xs-value-paths-v1/rob-residual.json) · [被拒绝的旧 profile](../../build/armor-xs-value-paths-v1/factor.log)

重新训练后，代表性的计算分片 20 只缩小 1,140 字节。样例赋值行关联的指令从 6 条变为 12 条，两个 ELF 都用了带掩码的向量读取，改写后该行还有独立的字节 OR 和槽读取。与正式 FTQ 版交换顺序各测三轮，宿主退休指令每拍增加 1,853 / 2,990 条，CoreMark 墙钟变化 +0.15%，MicroBench +1.24% 且三轮都慢。保持原有布尔表达式。两个短窗口及完整 MicroBench 的 DiffTest 均通过。[重新训练后的 ELF](../../build/armor-xs-value-paths-v1/elf/factorrob/shard-20.json) · [三轮实测](./data/TNO0028_value_path_samples.csv)

另一个具体消费者是 `debug_sqIdx_79_1_value`。原 RTL 在第 648389 行用类似 mux 产生写回选择条件，第 136405 行将 6 位状态拼入数组，八个 DiffTest 提交端口以出队指针读取该数组。冻结代码的寄存器写口 1501704 在 CoreMark 窗口里进入 617 次，实际变化 37 次。这组 320 个写口合计进入 247,536 次，变化 22,374 次。后续可追踪写回端口号、ROB 索引和前后半条目的解码是否能为多个字段共享，保留出队读取及原写入优先级，用已有的完整 DiffTest 轨迹复核。[RTL 的索引读取](../../../wolvrix-playground-new-xiangshan/build/xs/kunminghu-v3-grhsim-merge-20261110/after/rtl-preparation/rtl/rtl/Rob.sv#L136574) · [写口生成代码](../../build/armor-xs-site-pgo-v1/native/model/grhsim_SimTop_sched_69.cpp#L58030)

## 第一、二条　变化率与实际分支


在单线程模拟器里为每个候选站点按真实访问顺序增记方向翻转和独立两位饱和预测器的预测错误。计数器从强不变化开始，站点第一次访问不计方向翻转。CoreMark 每一个站点的访问数与变化数均与上一轮训练文件一致。两位计数器用于描述各站点自身的历史。硬件还受其他分支、代码布局和预测器容量影响。[训练序列](../../build/armor-xs-value-paths-v1/sequence/coremark/buckets.json) · [留出负载](../../build/armor-xs-value-paths-v1/sequence/microbench/buckets.json)

| CoreMark 训练站点 | 访问/拍 | 变化/拍 | 方向翻转/拍 | 独立两位预测错误/拍 |
|---|---:|---:|---:|---:|
| 计算侧 ≤0.5% | 72,948 | 60 | 66 | 86 |
| 计算侧 0.5% 至 5%，不含下端点 | 22,855 | 378 | 433 | 523 |
| 提交侧 20% 至 50%，不含上端点 | 1,761 | 597 | 528 | 566 |
| 提交侧 50% 至 80%，不含上端点 | 925 | 575 | 288 | 271 |
| 提交侧 80% 至 100%，不含上端点 | 619 | 580 | 44 | 34 |
| 提交侧每次访问都变化 | 264 | 264 | 0 | <0.1 |

稀疏写回增加分支后，单次孤立变化结束时也可能产生方向翻转。单独从 0.5% 放宽到 5% 曾令 CoreMark 分支预测失败多 745 次/拍。两位模型对新增站点给出 523 次/拍，能说明误差规模的一部分。此次进一步按生成语句选择，仅给 0.5% 至 5% 区间中能直接跳过读者激活字写入的 17,679 个站点增加分支，新增覆盖约 8,319 次检查/拍和 136 次变化/拍。

提交侧另做了一项单变量试验。在原先选中的 17,187 个写口里，把两位预测错误低于访问次数 10% 的 3,909 个恢复为条件写入。训练期间，它们每拍访问 764 次、变化 729 次、方向翻转 16 次、两位预测错误 14 次。AMD IBS 在原 PGO 的实际比较分支上，对“训练中总变化”这一组依然记录到 CoreMark 60 个退休分支样本、22 个预测失败样本。例子 `0x51d654d` 是与状态比较的 `cmpb`，下一条 `jne` 前往状态写入路径。这一组的单站点局部历史很规则，整机硬件计数才能确定恢复分支的净效果。[硬件分支样本](../../build/armor-xs-value-paths-v1/ibs/commit.json) · [分支地址与写口 ID](../../build/armor-xs-value-paths-v1/ibs/always.json)

| 相对 0.5% 稀疏写回和 20% 无分支提交的基线 | CoreMark 耗时 | CoreMark 指令/拍 | CoreMark 预测失败/拍 | MicroBench 耗时 | MicroBench 指令/拍 | MicroBench 预测失败/拍 |
|---|---:|---:|---:|---:|---:|---:|
| 只给能跳过直接激活字写入的计算点放宽门槛 | +0.60% | −47,398 | +543 | −0.59% | −35,750 | +444 |
| 还原局部两位预测器容易预测的提交分支 | +2.05% | −342 | +267 | −0.59% | +682 | +235 |

放宽计算门槛后，每拍节省约 4,100 / 2,326 个宿主周期，与原先约 220 万个宿主周期/拍相比，变化很小。提交侧恢复分支后每拍反而增加 8,658 / 9,214 个宿主周期。CoreMark 中上述 22 个 IBS 错误样本分布在 21 个静态地址，这些地址采到的 23 个分支样本全部实际跳转。仅凭这些样本不能进一步区分预测器容量、历史别名或目标预测各占多少。两种策略的整机 PMU 和跨负载耗时支持保留上轮的两项门槛。[三轮对照和每个 PMU 事件](./data/TNO0028_value_paths.json)

## 生成器与复现

`priority_mux_commit_demand` 现在可以独立启用。生成器检查根值只有一个提交写口数据消费者，操作是纯标量 mux，叶子是已保存的值、输入或常量。根值要有独占槽，没有变化通知或外部观察者。写口位于相应 event 和写使能下，提交代码在需要读取值或做数据块比较之前生成数据。此模式保留其他计算组的普通求值方式，可以与稀疏写回、无分支提交和数据块比较组合。执行计划导出也标记了移至提交的根值。[生成器源码](../../wolvrix/lib/emit/grhsim_cpp.cpp) · [选项与适用条件](../../wolvrix/docs/emit/grhsim-scheduling.md)

在已有香山构建环境中，从正常入口生成并训练。

```sh
WOLVRIX_GRHSIM_PRIORITY_MUX_COMMIT_DEMAND=1 \
WOLVRIX_GRHSIM_PRIORITY_MUX_MIN_CHAIN_LENGTH=13 \
make xs_wolf_grhsim_emu \
  PGO_WORKLOAD=testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  XS_GRHSIM_SITE_PGO=both XS_GRHSIM_SPARSE_PERMILLE=5
```

本次取 13 是依据已经追到写口的 FTQ 链长。通用规则未读取模块名或信号名。在 67,314 个计算组里，最终选中 4,352 条，长度都是 13。冻结原型所针对的 4,096 条全部入选，另外 256 条来自 FTQ 的 `mispredictBranchInfo`，包含 64 项的 `taken`、`cfiPosition`、`attribute.branchType`、`attribute.rasAction` 四个字段。再次训练后，92 个翻译单元内的 599,596 个计算站点和 208,820 个提交站点与基线逐项比较，访问数与变化数完全相同。[生成器选点清单](../../build/armor-xs-value-paths-v1/generator/inventory.json) · [训练文件逐行核对](../../build/armor-xs-value-paths-v1/generator/profile-check.json)

正式 ELF 的计算函数合计缩小 943,811 字节，提交函数增加 999,132 字节，整份 `.text` 增加 55,344 字节，约 0.06%。核对调试对象与计时 ELF 的函数长度和指令字节，字段样例对应的片段在计算分片 54 消失，提交分片 81 在写使能处跳转后才读取选择条件。[正式 ELF 摘录](../../build/armor-xs-value-paths-v1/elf/generator)

通过 Make 入口独立重生成，140 份 C++、头文件和生成的 Makefile 与受测模型逐字节一致。4,352 条链都用其原计算槽逐写口核对过 CoreMark 短窗口和完整 MicroBench。用正式 ELF 单独核对两种负载的前 100,001 拍，各比较 99,999 条 DiffTest 记录，CoreMark 的 35,063 行期末性能计数相同。完整 MicroBench 在 PC `0x80003a4e` 正常退出，报告 225,601 个 guest cycles，225,599 条 DiffTest 记录全部一致。生成器的 priority mux、提交块、独立写口求值和执行计划四项 CTest 通过，独立模式也验证了写使能关断再打开的行为和执行计划里的根值计数。XiangShan 的 40 项选项测试、站点计数测试和 GSIM 聚合字段归属测试通过。[重生成校验](../../build/armor-xs-value-paths-v1/reemit/matched.json) · [逐写口校验](../../build/armor-xs-value-paths-v1/shadow-generator) · [完整轨迹](../../build/armor-xs-value-paths-v1/long/generator/coverage.json) · [CTest](../../build/armor-xs-value-paths-v1/final-ctest.log)
