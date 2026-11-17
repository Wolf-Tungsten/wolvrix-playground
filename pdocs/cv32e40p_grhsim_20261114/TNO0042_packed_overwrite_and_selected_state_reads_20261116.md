# TNO0042：省去 packed-array 初始化与按索引读取状态

实现、回归和双模型固定对照已完成。**结构改写生效，但本轮没有确认 XiangShan 整机净收益；CV32 的已有收益保留。两项新规则继续默认关闭。**

本轮落实 [TNO0041](./TNO0041_post_storage_demand_and_initialization_20261116.md) 的前两项建议。新增两个默认关闭的通用 emitter 规则，保持图、区域、状态布局和结果通知接口不变。用户允许与此前优化叠加，因此在生成前固定一个 layout + no-init + select 组合；没有测量后再选择组合或调整阈值。共享候选与激活粒度仍是另行处理的结构问题。

## 实现与静态证明

`packed_array_no_init` / `WOLVRIX_GRHSIM_PACKED_ARRAY_NO_INIT`：仅当 packed view 的 destination lane 映射完整且每项写一次，所有来源都是与目标数组分离的直接标量状态，类型与元素宽度一致时，省去覆盖前的初始化。局部数组保留未初始化声明，持久数组跳过赋零数组；所有元素赋值仍在原 concat 位置。其他表达式、未证明的物化读取快照、memory/intent 存储和不匹配类型保守回退。

`packed_array_state_select` / `WOLVRIX_GRHSIM_PACKED_ARRAY_STATE_SELECT`：复用稳定索引、纯区域、别名写和其他 emitter 计划排除条件，只处理私有、单用户的 packed-array → SliceArray。进一步证明所有来源都是直接状态后，在原 concat 点通过类型安全的成员指针表读取被选中的状态，并保留截断后的标量快照；结果赋值、比较和通知仍在原 slice 点。没有把独立 C++ struct 成员伪装成数组。

重复 lane 保留原语义，连续重复第 0 项的尾部可以缩短静态表。ROB 的 lane 160–255 仍读取实际的 lane 0 状态，不能视为零；超出原数组范围的索引才返回零。多用户、跨区域持久数组、公开观察值、本地修改的索引、副作用及被条件/优先级/布尔计划吸收的操作不参与选中读取。启用旧 scope 时，选中读取优先，其余符合 scope 条件的数组继续原路径。

实现与使用说明见 [packed-storage 文档](../../wolvrix/docs/emit/grhsim-packed-storage.md)。两项规则不含模型名称、运行频次、计时输入、调优阈值或站点白名单。

## 冻结比较

XiangShan 目录为 [packed-demand-20261116-v1](../../build/xs/packed-demand-20261116-v1/policy.json)。六个版本固定为：

| 名称 | 配置 |
| --- | --- |
| full | TNO0040 的 ownership-corrected fixed，所有本轮和上一轮 storage 选项关闭 |
| layout | TNO0040 的 fixed + packed state layout |
| no_init | full + 本轮省初始化 |
| select | full + 本轮按需状态读取 |
| combined | full + layout + no-init + select；scope 关闭 |
| no_shared | 同一新 native 库重新生成，关闭 shared；layout/no-init/select/scope 均关闭 |

新 no_shared 相对历史版本有 15 个生成 C++ 文件变化，来自共同的 ownership 修复背景，因此本轮使用新控制隔离规则影响。[对应记录](../../build/xs/packed-demand-20261116-v1/no-shared-correctness-control.json)

所有新选项关闭后，XiangShan 的全部 140 个生成文件逐一复现原 fixed。三个候选的区域/op 顺序、变化检查与通知代码摘要相同；no_init/select 头文件与 full 相同，combined 头文件与 layout 相同。

| 静态命中 | no_init | select | combined |
| --- | ---: | ---: | ---: |
| 省初始化的剩余数组 | 420 | 0 | 352 |
| 按需状态读取 | 0 | 68 | 68 |

独立源代码检查重建了 68 个原数组与新表，逐项核对全部 5,732 个 lane 的状态成员及索引表达式。去除重复尾部后共声明 4,056 个成员表项；这是源码表项数，不等于最终 ELF 数据占用。组合与独立 select 的映射完全相同。[独立映射](../../build/xs/packed-demand-20261116-v1/selected-source-mapping.json)、[组合映射](../../build/xs/packed-demand-20261116-v1/combined-source-mapping.json)、[源码门](../../build/xs/packed-demand-20261116-v1/structure.json)

CV32 目录为 [packed-demand-v1](../../build/cv32e40p/packed-demand-v1/hypothesis.json)。对照 fixed、no-init、select、combined 和同 RTL Verilator。新规则及组合均为零命中，全部生成源码与 fixed 一致，`.text/.rodata/.data` section 也一致。

计时预先固定：XiangShan 三轮正反序，CV32 八轮；串行运行于 node030 CPU96、NUMA1、关闭 ASLR、单线程。先完成 CV32，再运行 XS。XS 仍是 10k-cycle smoke、两个种子各 100k-cycle DiffTest/trace、一次预热、三次正式 100k-cycle 样本，并非完整 CoreMark 完成运行。所有本轮构建和编译回归均在正式计时前结束。

## ELF：数组构造确实消失，而非转入 helper

以下组体窗口由活动字偏移、分支位与相邻组入口交叉定位，包含组尾检查。没有源码行 DWARF，也没有把整个函数的指令都归到该组。

| 冻结版本 | FTQ group93956 静态指令 | ROB group94733 静态指令 | ROB `memset` 调用 | ROB 栈索引读取 | compute batch9 栈帧 |
| --- | ---: | ---: | ---: | ---: | ---: |
| full | 4,869 | 1,604 | 8 | 8 | 20,728 B |
| layout | 235 | 1,604 | 8 | 8 | 20,728 B |
| no_init | 4,804 | 1,539 | 0 | 8 | 20,712 B |
| select | 4,869 | 107 | 0 | 0 | 5,368 B |
| combined | 175 | 107 | 0 | 0 | 5,368 B |

组合的 FTQ 组体仅有 64 次向量源读取与 64 次向量结果写入；layout 中的 59 次 64 B 覆盖前清零及零寄存器设置消失。原通知在 layout 中已由编译器大幅合并，本轮没有把收益归给再次合并 192 处源码通知。

ROB 的 8 个选中读取不再构造数组，没有独立 lambda 调用，也没有把原构造隐藏到其他 helper。旧 scope 版本只缩小 caller frame，而 helper 仍各构造 2 KiB 数组；当前的 107 条是保留结果检查/通知后的整个组体窗口。因此这是不同于单纯缩短生命周期的改进。

全模型 compute 静态指令数为 full 14,108,784、layout 14,104,154、no_init 14,107,995、select 14,106,123、combined 14,100,956；新 no_shared 为 14,274,240。静态规模不等于执行次数，帧大小不等于 spill 流量，这些数值不能单独预测整机加速。

[完整 ELF 报告与窗口](../../build/xs/packed-demand-20261116-v1/machine-evidence/report.json)

## CV32：代码保持一致，已有收益保留

五后端 smoke、完整 CoreMark 和逐周期总线 trace 一致。8 轮外部 walltime：

| 比较 | 均值变化 | 95% 配对 bootstrap CI |
| --- | ---: | --- |
| no_init / fixed | +0.328% | [+0.025%, +0.720%] |
| select / fixed | +0.101% | [−0.055%, +0.261%] |
| combined / fixed | +0.149% | [−0.083%, +0.453%] |
| fixed / Verilator | −2.726% | [−2.968%, −2.521%] |
| combined / Verilator | −2.582% | [−2.853%, −2.311%] |

这些新选项没有改变 CV32 的源码和上述 ELF section。进一步检查确认，除 build ID 外，27 个带分配标记的 section 连内容、地址、大小、对齐及 BSS 布局也全部一致。因此与 fixed 的时间差不能归因为新算法收益或代价。no_init 的小样本区间虽略高于零，仍属于相同代码和数据的运行差异，本轮没有进一步归因环境因素；原始数据全部保留，没有删除慢样本或追加测量。[分配段身份](../../build/cv32e40p/packed-demand-v1/allocated-section-identity.json)

独立复核通过 40 个正式样本、80 份 start/end CPU/NUMA 原始记录，全部首次 placement 通过，CPU288 idle 均为 100%。[统计](../../build/cv32e40p/packed-demand-v1/all-comparisons.json)、[独立复核](../../build/cv32e40p/packed-demand-v1/independent-review.json)、[代码 section 身份](../../build/cv32e40p/packed-demand-v1/elf-sections.json)

## XiangShan：结构收益没有转化为整机净收益

六个版本的 smoke、两个种子的运行签名与十组 trace 比较全部通过。三轮外部 walltime 的配对结果如下；负数表示表中分子的版本更快。

| 比较 | 均值变化 | 95% 配对 bootstrap CI | 分子更快的轮次 |
| --- | ---: | --- | ---: |
| layout / full | −0.445% | [−0.575%, −0.295%] | 3/3 |
| no_init / full | +1.106% | [+0.899%, +1.236%] | 0/3 |
| select / full | −0.059% | [−0.181%, +0.141%] | 2/3 |
| combined / full | +0.223% | [−0.223%, +0.739%] | 1/3 |
| combined / layout | +0.672% | [+0.072%, +1.209%] | 0/3 |
| combined / no_shared | +4.019% | [+3.574%, +4.744%] | 0/3 |
| no_shared / full | −3.649% | [−3.823%, −3.458%] | 3/3 |

原始外部 walltime（秒）：

| 轮次 | 顺序 | full | layout | no_init | select | combined | no_shared |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 正序 | 119.664670 | 119.109089 | 121.143457 | 119.499581 | 120.549287 | 115.089609 |
| 2 | 反序 | 119.396584 | 118.709699 | 120.807933 | 119.564851 | 119.579686 | 115.267871 |
| 3 | 正序 | 119.887010 | 119.533584 | 120.964473 | 119.670022 | 119.620242 | 115.493048 |

省初始化版虽然减少了机器码中的清零与 `memset`，却在三轮均更慢。选中读取确实消除了 ROB 的全量构造，整机时间则接近不变，区间跨零。固定组合没有恢复 layout 的全部收益，仍明确慢于新 no_shared。不能用两个局部组体的静态指令下降来推算全部动态工作，也不能仅据本轮计时把退化归给表读取、寄存器分配或某个缓存层；本轮没有新增 PMU 或执行次数归因。

这仍是同一 CoreMark 前 100k-cycle 窗口的三对小样本，不能推广为跨负载结论。Host time 给出相同方向：no_init/full 为 +1.104%、select/full 为 −0.061%、combined/full 为 +0.222%、combined/no_shared 为 +4.022%。所有样本保留，没有重试、删点、追加组合、调整站点或门槛。代码规则在正式测量前已冻结，结果仅用于评价。

独立复核通过 18 个正式样本、全部 42 次运行、8,650 份线程/CPU 快照、881 份原始 NUMA 快照和 54 个 staged 文件身份。十组 trace 各覆盖 99,999 条记录，CPU288 idle 均为 100%。

[完整配对统计](../../build/xs/packed-demand-20261116-v1/report.json)、[逐轮数据](../../build/xs/packed-demand-20261116-v1/measurement/rounds.json)、[功能门](../../build/xs/packed-demand-20261116-v1/measurement/functional.json)、[独立复核](../../build/xs/packed-demand-20261116-v1/independent-review/review.json)。

当前保留配置和新选项默认值不变。本轮完成的是数组准备工作的两项局部修复；共享区域将互不依赖的计算放到同一活动位下的问题仍未解决。后续重点仍应是预先提出的真实依赖连通性与激活粒度，单独保留 CV32 的计算依赖收缩，并重新验证两边；不把本轮负结果转成模型名称开关或运行反馈准入。

## 验证与复现

6 项相关 CTest、14 项 Python 回归通过。新规则比较默认/开关/环境优先级，生成模型执行 O0 与 O3（O3 配 ASan/UBSan）独立 oracle，覆盖双时钟、异步复位、掩码写、重复 eval、带符号元素、越界、重复来源、持久数组和固定叠加。旧布局、scope、late-index 和 indexed-concat 回归通过。

初次 no-init 测试错误地要求公开数组输出保留 packed-lane 表示；现有 emitter 会对此回退。修正测试预期，并补上跨区域持久数组的实际路径回归。生产规则没有因此修改，失败日志保留；性能测量开始前全部回归通过。

[测试记录](../../build/xs/packed-demand-20261116-v1/test-validation.json)、[最终冻结检查](../../build/xs/packed-demand-20261116-v1/preflight.json)、[XiangShan 对照脚本](../../scripts/xiangshan_packed_demand_compare.py)、[CV32 对照脚本](../../scripts/cv32e40p_packed_demand_compare.py)、[离线分析](../../scripts/xiangshan_packed_demand_analysis.py)、[XS 独立复核](../../scripts/xiangshan_packed_demand_review.py)、[CV32 独立复核](../../scripts/cv32e40p_packed_demand_review.py)。
