# TNO0049：indexed-concat 的紧凑快照数组

本轮承接预先列出的第二条独立方向：修复 indexed-concat 按需读取仍支付大闭包捕获成本的问题。在 TNO0048 固定 shared-arm 候选上，只新增 `indexed_concat_snapshot_array`；不叠加 TNO0047 aligned-array 规则，不修改调度、状态视图、条件锥、缓存或激活路径。生成选择仅使用图与静态存储成本，不输入实际运行数据。

## 规则及边界

现有 indexed-concat 先把局部 scalar 保留为原定义点快照，再生成引用这些快照的 word-reader lambda。XS ROB 的一个256-bit源、1-bit结果曾在ELF中出现256个指针、2048 B捕获对象。CV32两个32×32-bit寄存器视图各捕获31个局部值，再由reader拼接所选word。

新增默认关闭规则仅接受原本已经通过 indexed-concat 快照与寿命证明的视图，并要求：

- 所有字段等宽，1–64 bit；非常量字段必须是已有的局部命名快照。
- 不接受持久槽、输入端口或covered-state view，避免为它们新增全数组的提前读取。
- native lane数组字节数不大于“独立非常量快照数×host pointer字节数”。重复字段不会被无条件展开为大数组；常量占数组空间但不增加指针成本额度。

在原concat位置按从低位到高位顺序初始化`std::array<T,N>`，值先按声明位宽截断。索引仍是bit offset；结果至多等于一个lane时只读取一个或必要的相邻两个lane，结果更宽时按边界逐片段汇合。超出源范围补零，宽索引高word非零返回零；不执行移位64。原producer和result的快照位置、状态提交及通知均保留。[功能说明](../../wolvrix/docs/emit/grhsim-indexed-snapshot-arrays.md)

这不是恢复状态数组，也不是去掉逐bit生产者；本轮只替换临时快照表示和读取方式。

## 验证与构建记录

扩展原 indexed-concat 独立逐bit oracle，覆盖等宽1/3/7/8/16/29/32/63/64-bit字段、1/32/64-bit结果，129-bit索引、尾部部分读取、越界、非规范scalar高位、重复operand、mixed宽度及原有公开/多用户/跨区域/effect回退。寄存器bank检查写使能、时钟沿、重复eval及重新init。默认关闭、环境/attribute优先级、planner、split helper和runtime-profile均检查。O0/O3 ASan/UBSan生成模型通过。最终库上的专项、原indexed-concat及execution-plan共3项CTest通过；18项Python回归通过，日志已冻结。

构建预检先两次发现关闭选项的runtime header多一行空白：编译过程中模板边界改动后，增量构建仍使用旧目标文件。`v1/v2`均停在off-source身份门，XS重放任务中止，没有性能样本；移开旧object并重编后，`v3`逐文件复现TNO0048关闭模式，native库SHA也变化。生产语义规则未因这一修复改变；旧/新生成文件差异仅为runtime模板空白。前期记录保留在 [preflight-history](../../build/cv32e40p/indexed-snapshot-preflight-history.json)。

CV32命中两处，各32个32-bit字段，数组各128 B，总256 B。原2个indexed视图保持2个，持久模型header、eval及全部调度/通知/cache/conditional标记保持一致；runtime header只新增开启时才输出的helper。三后端smoke、完整CoreMark及逐周期总线trace通过。与TNO0048的smoke/CoreMark分别核对331项区域、函数、固定点、变化检查、缓存和条件分支计数，完全一致。[结构门](../../build/cv32e40p/indexed-snapshot-v3/structure.json)、[计数门](../../build/cv32e40p/indexed-snapshot-v3/count-gate.json)

XiangShan生成门也通过：11个原indexed视图中只有ROB的`value1055061`命中，256个1-bit快照生成256 B的`std::array<bool,256>`，其余10个reader逐字不变。除runtime新增helper外，137个模型CPP中仅`sched_19.cpp`变化，其余136个逐字一致。所有条件锥、共享闭包成员、缓存、状态视图及激活标记hash不变；持久header和eval相同。[XS结构门](../../build/xs/indexed-snapshot-20261117-v3/structure.json)、[源码差异范围](../../build/xs/indexed-snapshot-20261117-v3/source-diff-scope.json)

## 固定测量协议

同一份冻结库用于XS和CV32。固定基线为TNO0048 shared-arm；新选项关闭时源码必须精确一致。双方各三对探索对照，XS为10k smoke、两个seed各100k周期DiffTest和预热后AB/BA；CV32为完整CoreMark的基线/候选/同RTL Verilator三轮正反序。全部性能测量待构建/测试结束后在node030 CPU96、NUMA1、单线程、ASLR off与共同锁下串行执行。无重试、删点、追加组合或运行反馈选优。本轮预先声明只做离线ELF和CV32行为计数，不追加PMU。[驱动](../../scripts/indexed_snapshot_compare.py)

## C++ 与 ELF

CV32两处各61条静态指令的reader辅助函数以及两次调用均消失。新结果直接从紧凑数组读取。主函数batch1指令2492→2325、栈减法680→296 B；batch2指令7536→7357、栈减法2392→1920 B。

| CV32 compute静态指标 | shared-arm基线 | snapshot候选 | 差额 |
| --- | ---: | ---: | ---: |
| 指令（含原两个reader） | 10558 | 10090 | −468（−4.4327%） |
| code bytes | 50049 | 46528 | −3521 |
| 调用 | 2 | 0 | −2 |
| 条件跳转 | 153 | 150 | −3 |
| RSP/RBP引用位置 | 2090 | 1794 | −296 |

commit/eval不变。栈指标中的RBP也可能是普通指针，不把全部引用位置视为spill。以上是静态代码形态，不等同于每周期退休指令。

候选`sched_1.cpp`的DWARF5行表未携带MD5；其源码归因只能依靠冻结编译输入链，报告逐文件标记为`absent`，没有声称通过内嵌checksum。其余被归因编译单元存在的checksum均与源码匹配。[ELF报告](../../build/cv32e40p/indexed-snapshot-v3/machine-analysis.json)

XiangShan当前shared-arm基线的目标reader位于`0x16214f0`，调用点`0x155152d`；此前记录中的connected地址没有直接沿用。重新逐项证明了RSP+`0x16b0..0x1ea8`的256次指针写，覆盖2048 B捕获对象。

开启版不再有该reader函数。RSP+`0x15a0/0x15e0/0x1620/0x1660`由四条64 B向量store写入，总计256 B；随后`0x154fa41`读索引、`0x154fa48`直接从栈数组读一个byte、`0x154fa50`保存结果。这里消除的是捕获与选word拼接成本，原标量producer及其输入读取仍然存在。[逐指令证明](../../build/xs/indexed-snapshot-20261117-v3/capture-evidence.json)

| XS compute静态指标 | shared-arm基线 | snapshot候选 | 差额 |
| --- | ---: | ---: | ---: |
| 指令 | 13,753,118 | 13,751,464 | −1654（−0.01203%） |
| 调用 | 22,623 | 22,622 | −1 |
| 条件跳转 | 563,338 | 563,338 | 0 |
| RSP相对访存位置 | 1,126,608 | 1,125,835 | −773 |
| 带内存操作数指令，不含lea/nop | 5,478,910 | 5,477,850 | −1060 |

目标batch19主函数219865→218948条静态指令，栈减法9912→7880 B；另删除737条指令、280 B栈减法的reader。commit/eval统计不变。XS release ELF没有源码DWARF行表，本轮通过固定符号、相同模型布局、索引field和上述调用/数组寻址核对局部证据；不宣称这些静态数字等于每周期节省。[XS ELF报告](../../build/xs/indexed-snapshot-20261117-v3/machine-analysis.json)

XS两个seed的100k周期DiffTest窗口全部通过，各99,999条trace记录一致；终点PC `0x80000c1a`、instrCnt250838、cycleCnt99995、guest cycles100001。10k smoke也通过，全部运行保留DiffTest。`.text`为88,867,554→88,856,754 B，减少10800 B；这是整个ELF的静态节变化，不代表热路径份额。

## 结果

两侧固定三对均完成，全部样本保留，无重试、删点或追加。结果为：

| 同轮对照 | 基线wall均值 | 候选wall均值 | 配对平均变化 | bootstrap 95% CI |
| --- | ---: | ---: | ---: | --- |
| XS shared-arm→snapshot | 112.552794 s | 112.505557 s | **−0.04198%** | **[−0.08382%, +0.00254%]** |
| CV32 shared-arm→snapshot | 2.599653 s | 2.437258 s | **−6.24669%** | **[−6.68886%, −5.48185%]** |
| CV32 同RTL Verilator→snapshot | 2.733726 s | 2.437258 s | −10.83969% | [−11.98060%, −9.71762%] |

| XS对次 | 顺序 | shared-arm wall秒 | snapshot wall秒 | 候选变化 |
| --- | --- | ---: | ---: | ---: |
| 0 | 基线→候选 | 112.576654 | 112.579511 | +0.00254% |
| 1 | 候选→基线 | 112.453035 | 112.358779 | −0.08382% |
| 2 | 基线→候选 | 112.628691 | 112.578381 | −0.04467% |

XS为2/3对更快但CI跨零，当前100k周期窗口**没有可确认的整机收益**。CV32相对shared-arm为3/3对更快，完整CoreMark有明确的本轮收益。小样本区间仅描述这次固定对照，不推广到其他工作负载，也不跨轮用绝对秒数拼接累计收益。

XS独立复核覆盖14次运行、2724个线程/CPU快照、278个原始NUMA快照，正式样本CPU288空闲率均100%。CV32独立复核覆盖9个正式样本、18个首尾放置/NUMA快照，逐对统计重新计算一致。[XS统计](../../build/xs/indexed-snapshot-20261117-v3/report.json)、[XS原始轮次](../../build/xs/indexed-snapshot-20261117-v3/measurement/rounds.json)、[XS独立复核](../../build/xs/indexed-snapshot-20261117-v3/independent-review/review.json)、[CV32统计](../../build/cv32e40p/indexed-snapshot-v3/summary.json)、[CV32独立复核](../../build/cv32e40p/indexed-snapshot-v3/independent-review.json)

## 判断与保留项

本轮完成了一个具体的快照表示修复：同时保留原计算时刻，又避免让小标量快照以逐值指针闭包的形式传递。CV32两个寄存器bank读取的辅助函数、调用和较大临时栈负担都减少；结合其相同的331项行为计数，收益来自相同硬件活动下的实现改变，而非改变调度或跳过必要计算。没有单独PMU，不能把6.25%精确分解成捕获、指令、栈或cache份额。

XS只命中一个视图，静态compute指令净减少0.012%；余下10个视图保留原路径。大范围重复字段、持久字段读取和其他表示边界仍存在。这支持“局部修复已实现，整机覆盖有限”的判断；没有据此扩大预算、按当前负载选站点，或给不同设计设置专属生成规则。

新开关继续默认关闭；本轮固定候选与shared-arm基线同时保留。源码规则在性能测量前冻结，之后没有修改，不读取运行结果作为输入。没有新增PMU、组合搜索或正式八对。本轮修改尚未提交。
