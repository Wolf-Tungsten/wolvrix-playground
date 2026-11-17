# TNO0040：保持 packed 状态访问顺序与缩短私有数组生命周期

按照 TNO0039 的前两项建议，分别实现并冻结两个默认关闭的 emitter 规则。两项均以原 `full` 优化流水线为基线，未组合试验，也未根据测量结果更改准入条件。共享区域、条件锥和状态视图证明保持原配置。

## 固定规则

**状态布局**：在原有 reference-demand 排序的最后一个图顺序 tie-break 中，保留已知 packed-array 的 lane 顺序。所有成员必须是不同的直接标量状态、类型/位宽一致、完整引用签名和 demand 完全相同。按图中 concat 顺序处理，冲突时第一个不相交 bundle 保留；没有运行频次、模型名称、阈值或打分。公开选项 `state_layout_packed_access`，环境变量 `WOLVRIX_GRHSIM_STATE_LAYOUT_PACKED_ACCESS`。

**数组作用域**：私有 packed-array 只有一个同区域的标量 SliceArray 消费者，而且 index 是在本区域不变的外部存储值或输入时，在原构造位置用立即调用 lambda 完成构造和选取，只把标量结果带出作用域。结果赋值、截断、判变和通知仍在原 SliceArray 位置。可观察数组、多用户、本地计算 index、状态别名 index、物理槽位写入别名、事件、副作用及吸收进其他计划的操作保守回退。公开选项 `packed_array_local_scope`，环境变量 `WOLVRIX_GRHSIM_PACKED_ARRAY_LOCAL_SCOPE`。

详细合法性与使用方式见[功能说明](../../wolvrix/docs/emit/grhsim-packed-storage.md)。这两项没有改变共享候选组成或分离活动位，因此 TNO0039 的激活范围放大问题不在本轮修复范围内。

## 候选与验证协议

最终固定对照为 XiangShan 的 `build/xs/packed-storage-fixed-20261116-v1` 和 CV32 的 `build/cv32e40p/packed-storage-fixed-v1`。在首个性能样本开始前发现 users-span 生命周期错误，因此加入独立正确性控制；两项静态优化规则没有调整。

| 模型 | 五个版本 | 固定轮数 |
| --- | --- | ---: |
| XiangShan | 旧 full、仅修复生成器悬空 span 的 fixed、fixed+layout、fixed+scope、历史 no_shared | 3 |
| CV32 | TNO0032 旧 full、仅修复生成器悬空 span 的 fixed、fixed+layout、fixed+scope、同 RTL Verilator | 8 |

XiangShan 按表中顺序正反序交替。每个版本先做 10k-cycle smoke、seed 0/1 各 100k-cycle DiffTest/逐周期 difftrace，以及一次 warmup，再取 3 个正式 100k-cycle 样本。这里不是完整 CoreMark 完成运行，Host time 含 harness 与 NEMU。三轮 bootstrap CI 只描述小样本，不代表跨负载保证。

CV32 使用完整 CoreMark 和总线 trace 门。所有计时串行运行于 node030 CPU96、NUMA1、关闭 ASLR、单线程；原有 CPU/NUMA/thread 检查保留。XiangShan 沿用此前 skip external idle admission 的政策，但记录 CPU288 使用率。CV32 仅允许原协议中的 placement 拒绝重试，不依据时间丢弃样本。

layout/fixed 与 scope/fixed 分别隔离两项 emitter 规则，fixed/旧 full 单独报告正确性修复自身的代码重排影响；两项没有组合。布局版要求全部生成 `.cpp` 与 fixed 不变；作用域版要求头文件/存储、逐组运算顺序与 fixed 不变。每份候选归档源码 patch、头文件、native library、编译器、生成源码和 ELF 身份。

早期 `packed-state-layout-20261116-v2` 与 CV32 对应版本只有功能、结构和机器码分析，没有性能样本；其证据属于修复 users-span 之前的冻结快照。最终结论使用上述共同控制重新编译和计时。

## 实现期修正

最初布局准入只查跨区域 direct-read 表，漏掉普通非物化的 RegisterReadPort/LatchReadPort。静态偏移回归在计时前发现此问题，现已补齐。早期 `packed-state-layout-v1` / `packed-state-layout-20261116-v1` 保留为失败尝试，未作性能样本。回归 fixture 最初只有 64-bit 总宽度，不属于既有 wide packed-view 表示，改为 10 lanes 后再测试实际路径；这不是修改生产准入阈值。

另一个复现门在 `packed-array-scope-20261116-v1` 拦截了关闭新选项时 5 个文件的局部表达式顺序漂移。既有代码使用 `for (... : graph.getValue(id).users())`：C++20 下临时 Value 在遍历前销毁，其 users span 引用失效。独立 ASan 探针实际报 `heap-use-after-free`；保留 owner 后退出正常。调度和 emitter 中本次发现的同类遍历均改为保留 Value/Operation 对象，再遍历借用的 span。

这一正确性修复使 XiangShan 的 23 个、CV32 的 2 个生成 `.cpp` 改变局部排序和部分布尔打包形态。XiangShan 的静态区域、运算类别、判变、缓存和通知站点数量保持一致。修复后 scope/fixed 逐组运算顺序和头文件一致。`packed-array-scope-20261116-v2`、CV32 `packed-array-scope-v2` 被原来的“必须等于旧 full”门拒绝，作为新固定共同控制的输入保留；没有删除或选择性能样本，因为尚未计时。

[ASan 复现](../../build/cv32e40p/packed-storage-user-lifetime-probe/temporary.log)、[owner 存活的对照](../../build/cv32e40p/packed-storage-user-lifetime-probe/owned.log)、[修复后源码检查](../../build/xs/packed-array-scope-20261116-v2/fixed-control-precheck.json)。

另一个同类失效来自临时 Operation 的 results span，可能漏记区域内写入。例如旧 XiangShan group39118 在入口先把 `value_bool_slots_[607264/607265]` 打入归约 word，之后才对它们赋值；修复后这两个输入正确回退到原位置求值。新增回归把区域内写入值绑定为可观察输出，使其真正拥有持久槽位，避免原“纯局部值”用例仅被其他存储条件挡住、未覆盖 written 集合的错误。

## 静态与机器码证据

布局版 XiangShan 命中 188 个 bundle、6,556 个状态；619 个 view 不满足完整签名/类型等条件，0 个重叠冲突。全部生成计算源码逐文件相同，唯一变化为 `grhsim_SimTop.hpp`。

预先指定的 FTQ 案例中，同一字段跨队列项的物理步长由 64 B 恢复为 1 B。ELF compute batch5 的 `vpinsrb` 从 6,781 条降到 2,749 条，减少 4,032 条，正好对应 TNO0039 的 64 组数组拼接。第一份数组从 63 条 byte insert 变为连续内存向量运算及存储。在最终 fixed 控制下，全 compute 的静态指令从 14,108,784 降到 14,104,154，减少 4,630 条；commit 静态指令数不变，但地址排列改变仍可能影响写侧缓存局部性。以上均不是退休指令或执行频次。

两项 CV32 候选均为零命中，与仅修复生成器悬空 span 的 fixed 生成源码逐文件一致；`.text`、`.rodata`、`.data` section 哈希也完全一致，功能和完整 CoreMark 总线 trace 通过。因此计时差不能解释为新的代码优化收益。

作用域版命中 116 处，改变 29 个 `.cpp`，存储头文件及逐组运算顺序与 fixed 一致。ROB 的 8 份数组均进入短作用域；compute batch9 主函数栈减法由 20,728 B 降到 5,368 B。

但不能据此说数组构造消失或全部工作被内联：Clang 把这 8 个 lambda 编成独立函数，每个仍有 2,048 B 的栈减法、198 条静态指令和一次数组下标读取。caller 从包含 8 个不同栈基址的 1,604 条窗口变成含 8 次 helper 调用的 106 条窗口；后者没有计入 helper 内的工作。整个 compute 范围（包括这些 helper）的 lambda 函数数从 15 增到 117，静态 call 从 22,627 增到 22,729，总静态指令仅减少 116 条，RSP 访存操作数减少 644 个。主函数与被调用函数的栈帧不能直接相加为所有 helper 的同时存活量，也不能把静态访存数当作动态 spill。

[最终布局证据](../../build/xs/packed-storage-fixed-20261116-v1/layout-evidence/report.json)、[最终作用域及 helper 证据](../../build/xs/packed-storage-fixed-20261116-v1/scope-evidence/report.json)。

## XiangShan 固定 3 轮

负值表示分子版本更快。旧 full 是包含此前 CV32 优化的原 XiangShan 二进制；no_shared 是此前消融的历史二进制，在本轮重新计时，没有重生成或混入正确性修复。

| 比较 | 外部 walltime 变化 | 95% 配对 bootstrap CI | 数值更低的轮次 |
| --- | ---: | --- | ---: |
| fixed / 旧 full | +0.304% | [-3.039%, +3.696%] | 1/3 |
| layout / fixed | -1.109% | [-2.558%, -0.001%] | 3/3 |
| scope / fixed | -1.064% | [-1.529%, -0.661%] | 3/3 |
| layout / 旧 full | -0.829% | [-3.785%, +1.044%] | 1/3 |
| scope / 旧 full | -0.769% | [-4.011%, +2.111%] | 2/3 |
| no_shared / 旧 full | -3.389% | [-8.505%, -0.329%] | 3/3 |
| layout / no_shared | +2.715% | [+1.377%, +5.159%] | 0/3 |
| scope / no_shared | +2.765% | [+0.937%, +4.911%] | 0/3 |

相对 fixed，两项在本轮呈现约 1.1% 的改善；相对历史 no_shared 仍慢约 2.7%，3/3 轮更慢。相对旧 full，两项的区间均跨零，不能宣布已经稳定超过原完整版。

**样本限制需要保留。** 三轮存在明显的时间漂移，第一轮普遍更慢；CPU/NUMA 门通过并不排除频率或其他系统干扰。布局在第二轮的外部 walltime 只比 fixed 少约 1.0 ms；其 Host time 比 fixed 多 2 ms，Host time 的 CI 为 [−2.551%, +0.002%]，2/3 轮更快，因此“外部 walltime 3/3”不能解释为稳定胜出。scope 的 Host time 变化为 −1.062%，CI [−1.527%, −0.657%]。不据此追加样本、丢弃慢轮或修改规则。

原始外部 walltime（秒）：

| 轮次 | 顺序 | full | fixed | layout | scope | no_shared |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | full → fixed → layout → scope → no_shared | 128.232580 | 132.972268 | 129.570694 | 130.939182 | 127.810904 |
| 2 | no_shared → scope → layout → fixed → full | 120.404253 | 120.712337 | 120.711302 | 119.913978 | 118.800467 |
| 3 | full → fixed → layout → scope → no_shared | 125.272145 | 121.464712 | 120.530764 | 120.247055 | 114.617857 |

独立复核覆盖 15 个正式样本、全部 35 次运行、7,385 份线程/CPU 快照、752 份原始 NUMA 快照和 45 个运行文件身份。两个种子的 8 组 trace 对比均通过，每组 99,999 条记录。CPU288 idle 为 99.631%–100%。没有重试或样本删除。

[全部配对统计](../../build/xs/packed-storage-fixed-20261116-v1/report.json)、[逐轮原始数据](../../build/xs/packed-storage-fixed-20261116-v1/measurement/rounds.json)、[独立复核](../../build/xs/packed-storage-fixed-20261116-v1/independent-review/review.json)、[功能与 trace 门](../../build/xs/packed-storage-fixed-20261116-v1/measurement/functional.json)。

## CV32 固定 8 轮

| 比较 | 外部 walltime 变化 | 95% 配对 bootstrap CI |
| --- | ---: | --- |
| fixed / 旧 full | −0.309% | [−0.521%, −0.133%] |
| layout / fixed | +0.069% | [−0.163%, +0.333%] |
| scope / fixed | −0.087% | [−0.293%, +0.143%] |
| fixed / 同 RTL Verilator | −3.122% | [−3.651%, −2.694%] |

两个新选项为零命中，fixed/layout/scope 的代码及数据 section 完全相同；它们之间的差异属于计时噪声。修复后的 CV32 仍保留已有收益。40 个正式样本、80 份 start/end 原始 CPU/NUMA 记录复核通过，全部首次 placement 通过，CPU288 idle 均为 100%。

[CV32 全部比较](../../build/cv32e40p/packed-storage-fixed-v1/all-comparisons.json)、[独立复核](../../build/cv32e40p/packed-storage-fixed-v1/independent-review.json)、[代码 section](../../build/cv32e40p/packed-storage-fixed-v1/elf-sections.json)。

## 验证与后续边界

8 项相关 CTest、18 项 Python 测试通过。持久内部写入的新增 long-field 回归通过 O0/O3 sanitizer oracle；short-field 新用例完成生成策略检查，原 short-field 的完整 oracle 也在修复后的生产库上通过。验证记录明确区分 fixture 版本与检查范围。两组生产源码的当前 SHA 与最终冻结库的源码快照一致。

两个新选项仍默认关闭；悬空 span 的正确性修复已应用。布局改善了已证明的连续访问，作用域缩短了 caller 的数组生命周期，但它们没有改变共享块的触发范围。下一步静态方向是：用普通 C++ 块作用域表达“构造→选取”，研究能否避免独立 lambda 调用；共享候选的依赖连通性与独立活动位仍按 TNO0039 另行设计。本轮没有追加组合、按测量选择站点或调阈值。


## 复现与归档

[XiangShan 固定对照脚本](../../scripts/xiangshan_packed_storage_fixed_compare.py)、[CV32 对照脚本](../../scripts/cv32e40p_packed_storage_fixed_compare.py)、[离线 C++/ELF 检查](../../scripts/xiangshan_packed_storage_analysis.py)、[原始采样独立复核](../../scripts/xiangshan_packed_storage_review.py)。

[最终冻结输入](../../build/xs/packed-storage-fixed-20261116-v1/inputs.json)、[源码形态门](../../build/xs/packed-storage-fixed-20261116-v1/structure.json)、[验证记录与源码身份](../../build/xs/packed-storage-fixed-20261116-v1/test-validation.json)。早期修复前的[布局证据](../../build/xs/packed-state-layout-20261116-v2/machine-evidence/report.json)仅用于追溯实现过程，没有对应性能样本。
