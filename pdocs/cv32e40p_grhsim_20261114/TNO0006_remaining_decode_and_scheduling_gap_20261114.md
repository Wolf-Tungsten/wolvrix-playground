# TNO0006：concat-slice 优化后的译码与调度差距

本轮最明确的新发现是 **同源常量等值译码的表示不同**：归一化 RTL Verilator 使用两张可增量更新的 one-hot 表，GrhSIM 仍物化两组各 171 个独立谓词，分别比较旧值、保存和通知。两组每 guest cycle 合计执行 **180.706 次 scalar 比较**，占新版 scalar 比较的 **24.466%**，结果变化仅 **0.09716 次**。这是下一步比“统一减少调度开销”更具体的优化目标。

另一个关联形态是同源等值谓词的长 OR。例如一处 62 项 OR 的集合其实只包含四段地址区间；这部分在 Verilator 中也没有完全化简，不能以“照搬所有查表”为目标。优先 mux 的表示仍有差别，但目前只有采样和源码线索，尚未隔离收益。

本轮新增诊断脚本和计数归因，没有修改生产 Wolvrix、RTL、emitter 参数或优化策略，没有新的配对性能测量。

## 冻结基准与新增证据

继续使用 [TNO0005](./TNO0005_concat_slice_coalescing_20261114.md) 的冻结 binary 和正式八轮结果：

| 后端 | walltime 均值 | 新 GrhSIM / 该后端 | 95% CI |
| --- | ---: | ---: | ---: |
| concat-slice 优化后的 GrhSIM | 4.812177 s | 1 | — |
| 相同归一化 RTL Verilator | 3.171653 s | 1.517265 | [1.512762, 1.521102] |
| 原始 RTL Verilator | 1.483320 s | 3.244243 | [3.235530, 3.252061] |

当前 GrhSIM SHA256 为 `091c95311c5b08274c1b91a796c7e50f2c241f14373b7c6614ca05fd46d7315b`。两种 Verilator binary 与 TNO0004 完全相同，因此复用其已经验证的动态调用次数；读取前检查 binary hash，不重编/重跑其计数版本。

本轮只运行五次诊断：新版 GrhSIM 的独立计数 binary 跑 smoke/CoreMark，两种 Verilator 和生产 GrhSIM 各一次 `perf stat`。全部在 node030 CPU96、NUMA1、ASLR disabled、单线程执行，通过功能和 placement；三个 PMU 样本的 CPU288 sibling 均 100% idle，计数 CoreMark 样本为 99.8818%。源码行采样复用 TNO0005 的生产 `perf.data`，不把计数版本的耗时纳入性能结论。

## 同 RTL 的剩余差距仍主要是指令量

新一组生产 binary PMU，计数包含初始化/退出，按 3,376,065 guest cycles 归一化：

| 每模拟周期 | 当前 GrhSIM | 归一化 Verilator | 原始 Verilator |
| --- | ---: | ---: | ---: |
| Host instructions | 14,294.09 | 9,799.12 | 5,355.19 |
| Host cycles | 4,470.21 | 2,933.28 | 1,363.69 |
| Branches | 567.80 | 568.44 | 674.09 |
| Branch misses | 1.458 | 0.913 | 0.948 |
| IPC | 3.1976 | 3.3407 | 3.9270 |

PMU running fraction 均为 100%。当前 GrhSIM / 归一化 Verilator：

```text
Host instructions 倍率 1.458712 × IPC 因子 1.044730 = Host cycles 倍率 1.523961
```

相比 TNO0004 的 2.1274 倍指令量，concat-slice 合并确实消除了大量工作；剩余差距仍主要在工作量，而不是额外的完整仿真轮次。两侧分支总数已经接近，也不能将全部差距简单归因为“GrhSIM 分支多”。PMU 恒等式只解释总量，不分摊各类代码的精确耗时，也不替代正式 walltime CI。

对选定模型计算函数的机器码统计，GrhSIM 从 TNO0004 的 178,724 bytes 降为 **88,794 bytes**，归一化/原始 Verilator 为 **65,387 / 44,932 bytes**。统计包含 compute/commit/eval 或 NBA/ACT/ICO 模型函数，范围和符号清单见 [static.json](../../build/cv32e40p/remaining-gap-v1/static.json)；不以包含通用 runtime 的整个 ELF `.text` 反推热点大小。

## 代码形态：CSR 等值译码与 one-hot 表

当前图中有两个对应的 12-bit 源：

| 源 | 实际语义 | 所有不同常量等值比较 | 其中物化的谓词 |
| --- | --- | ---: | ---: |
| `_val_134` | decode 阶段指令的 `[31:20]` 字段，来自 `core$_11272_` | 215 | 171 |
| `_val_6162` | execute 阶段 CSR 地址：`csr_access_ex_o ? operand_b[11:0] : 0` | 172 | 171 |

上表的“物化”表示生成 C++ 有独立值存储和 `grhsim_changed_*` 检测；其余比较被内联。脚本核对了 **全部 215/172 个 IR 常量集合与 Verilator 两张表的常量读取集合逐项完全相同**，不是只按函数名猜测对应关系。

GrhSIM 典型生成片段，简化变量名后：

```cpp
bool next = address == 3231;
bool changed = old_predicate != next;
changed_for_readers |= changed;
old_predicate = next;
// 其他常量各自重复比较、保存和通知。
```

实际位置为 [sched_0](../../build/cv32e40p/concat-slices-v1/grhsim_concat_slices/grhsim_Cv32Bench_sched_0.cpp) 2343 行起，以及 [sched_1](../../build/cv32e40p/concat-slices-v1/grhsim_concat_slices/grhsim_Cv32Bench_sched_1.cpp) 3105 行起。decode 阶段的 171 个物化谓词分布在 group 4/14/15；execute 阶段分布在 group 6/19/20/31。

归一化 Verilator 的对应结构为两张 `VlUnpacked<CData,4096>` 表和两个 previous-index 字段，计算主体每次执行时：

```cpp
table[previous_address] = 0;
table[current_address] = 1;
previous_address = current_address;
// 下游的 address == K 直接读取 table[K]。
```

源地址及更新分别见 [Verilator root_0](../../build/cv32e40p/run2/verilator/VCv32Bench___024root__0.cpp) 的 3977/4299 行（execute）和 6192 行（decode）；例如常量 3231 的读取在 4649、6760 行。两表常量读取源码位置数为 359/271，许多下游直接使用同一个表项，不需要重新计算每个相等式。

**这两张是运行时维护的 one-hot 表，区别于 TNO0004 统计的 219 张只读 ConstPool LUT。** 现有 Wolvrix `kDecodeTable` intrinsic 依赖 Chisel 表语义输入，也不会自动把这些普通 RTL 等值比较转换成此结构。

原始 RTL Verilator 则保留了较高层的条件选择，例如 [CSR read 分支](../../build/cv32e40p/run2/verilator-original/VCv32Bench___024root__1.cpp) 639 行起。它没有这两张 one-hot 表，仍是三者最快的版本，说明 one-hot 是当前相同 RTL 对照中的明确结构差异，不是所有译码的唯一最优表示。

### 对上次存储数量解释的补充

TNO0004/0005 的 GrhSIM `value_bool_slots` 数量是 3,142→1,038；Verilator root 的 273 个一位 CData **标量字段**没有包含这两张表的 8,192 个元素。因此不能据此说 Verilator 的全部 Boolean 存储更少。关键是这些存储的使用方式：Verilator 用更大的直接寻址空间换取每个 decoder 两个条目的更新，GrhSIM 用独立谓词值并逐项检测/通知。

## 动态计数：开销在哪里，activity 又跳过了什么

计数器在镜像装载和复位之后清零，按 clock 低/高相位记录。它们描述生成 C++ 的执行次数；插桩可能阻止部分编译器消除，不能当作退休指令数。正式 binary 的 PMU 独立采集。

| 每 guest cycle | concat-slice 优化前（TNO0004） | 当前版本 |
| --- | ---: | ---: |
| fixed-point 调度轮数 | 3.0000003 | 3.0000003 |
| 真正进入 compute groups | 111.598356 | 52.875129 |
| 真正进入 commit groups | 6 | 6 |
| scalar old/new 比较 | 913.159239 | 738.601079 |
| scalar 结果变化 | 149.712012 | 96.145399 |
| 显式 activity flag OR 语句执行 | 491.461676 | 304.223493 |

旧模型另有每周期 73.506 次八项 packed 比较，新模型为零；上表 scalar 行不包含旧 packed 路径，不能把两行相减当作全部比较成本的降幅。direct OR 也不包含 helper 中的 OR，且 mask 可能为零，不等于非零激活次数。

当前低相位 compute groups 合计约 1，高相位约 51.875。高相位除时钟相关 group 18 在整个 workload 额外执行一次外，其余 compute group 均不超过每周期一次。三轮调度仍不能解释成整机重算三遍；循环自身采样约 2.95%，而变化跟踪还分布在 compute 函数内。

990 个 scalar 比较位置中，有 493 个 `kEq`，其余包括 slice、mux 和逻辑运算结果的 old/new 检测。动态 `kEq` 结果的 old/new 比较约 **316.716 次/cycle**，仅 **2.658%** 发生变化；所有 scalar 检测的变化比例约 **13.017%**。

两组 CSR 谓词的细分如下，均只统计上表物化的 171 个谓词：

| 每 cycle | decode 地址 | execute 地址 |
| --- | ---: | ---: |
| source 自身比较次数 | 0.873946 | 0.592382 |
| source 自身变化次数 | 0.786282 | 0 |
| 等值谓词比较次数 | 143.570533 | 37.135300 |
| 等值谓词变化次数 | 0.097157 | 0 |
| 执行时为真的谓词数量之和 | 0.057977 | 0 |

两组共有 180.706 次/cycle，占全部 scalar 比较次数的 24.466%；两组合计变化比例仅 0.05377%。这些是**次数占比**，不是“至少 24.466% 的 CPU 时间可删除”。

activity schedule 也确实在工作：execute decoder 的 group 19/20 在本 workload 未执行；group 6 的 61 个谓词随该混合 group 平均每周期运行 0.592382 次，贡献 36.1353 次比较；group 31 的一个谓词每周期运行一次，合为 37.1353。source 未变化不代表整个 group 的其他输入和操作可以跳过。

不能据此将 CSR 逻辑删除或设为常量。结论应是：共享同源译码能避免重复检查大量互斥谓词，并有机会仅传播旧/新地址对应的变化；仍需保留所有输入情况下的行为、初始值和通知语义。

## 同一译码链上的长 OR

[GrhSIM sched_4](../../build/cv32e40p/concat-slices-v1/grhsim_concat_slices/grhsim_Cv32Bench_sched_4.cpp) 380 行是一条 62 项 OR。已由执行 planner 映射回 IR `_val_12607` / `_op_18006` 和归一化 RTL 第 42439 行。62 项都是 `_val_6162 == constant`，常量集合严格等于：

```text
{0xB00} ∪ [0xB02,0xB1F] ∪ {0xC00} ∪ [0xC02,0xC1F]
```

435 行另一条 126 项 OR 有 125 个同源等值谓词和一个额外 Boolean 输入。其 125 个常量可归为九段区间，完整集合在 [shape-evidence.json](../../build/cv32e40p/remaining-gap-v1/shape-evidence.json)。当前 wide-concat reduction 已去掉宽临时值，但仍逐个读取 bool 并 OR。

归一化 Verilator 同样有长 one-hot 表项 OR，例如 [root_0](../../build/cv32e40p/run2/verilator/VCv32Bench___024root__0.cpp) 4649 行起。因此共享 one-hot 更新不等于解决所有下游工作。对“同源等值集合的 OR”做通用集合/区间判断，是另一个清晰的结构机会；要按真实常量集合化简，保留额外输入及原结果可观测性，不能只按本次全 false 的结果进行折叠。

本轮复用的生产采样中，62 项与 126 项 OR 对应源码行约占 2.04%/1.44%；此类源码行可能包含调度后的指令归因，百分比经过舍入，不作为严格的可回收时间上界或下界。

## 其他剩余形态与优先级

寄存器堆已经恢复 word 输入：两个 indexed-concat 按需区间由两个 32-bit 值拼装，上一轮减少的 bit 拆分路径没有重新出现。下一步不应继续围绕同一问题重复优化。

优先 mux 仍有结构差异。当前 `grhsim_mux_u64` 先将两侧实参求值，再用全字 mask 选择；[sched_8](../../build/cv32e40p/concat-slices-v1/grhsim_concat_slices/grhsim_Cv32Bench_sched_8.cpp) 149 行的 aligner `next_state` 表达式包含五层此 helper。planner 将其映射为 `_op_46916` / `_val_32500`、RTL 第 44287 行，采样约 2.44%。原始 Verilator 的 aligner 保留 state 值和条件表达式，例如 [root_0](../../build/cv32e40p/run2/verilator-original/VCv32Bench___024root__0.cpp) 1305 行起的 `instr_valid`/`update_state`。

这是进一步检查条件计算与物化边界的线索，尚不能推出“把所有 mask mux 换成 ternary 一定更快”：编译器还可能 if-convert、共享或消除表达式，且 side effect 和 snapshot 会限制延迟求值。本轮没有执行 mux 候选实验。

下一步建议优先落在 **有限域、同一 SSA source 的常量等值译码共享**，连同它的消费者集合一起建立静态成本模型；同源等值 OR 的集合化简也有明确输入/输出恒等式。选择条件应由域宽、谓词数量、使用者、内存成本和语义约束确定，不用 profile 决定删除哪些值，也不做运行后的候选选优。实现必须处理表初始化、地址不变、仅旧/新项变化、多用户、跨 group snapshot 和精确 reader 激活；不能直接跨多个调度 scope 共享可变表而跳过这些证明。

XiangShan 的 CSR 地址与较窄枚举字段可能具有相同形态，但完整 32-bit 指令不能直接展开成 `2^32` 项 one-hot 表。已有 decode-table intrinsic 的元数据路径也与普通 RTL 自动识别不同。当前只给出通用适用边界，没有重建 XiangShan、修改其配置或宣称性能收益。

## 验证、复现与产物

新计数 binary 的 smoke 为 253 cycles，CoreMark 为 3,376,065 cycles；UART、CRC、exit 和完整 bus trace 与冻结参考一致。五次诊断均通过 placement；PMU 与计数数据分开。四项 Python 计数回归通过，新增用例检查逐值结果在写回前采样，非一位结果不误记为 Boolean true。990 个比较的 per-value 合计与原 aggregate probe 完全一致，planner 映射的 value/group 与生成源码全部对应。

脚本：[cv32e40p_remaining_gap.py](../../scripts/cv32e40p_remaining_gap.py)。保留 `run2`、`code-shapes-v1`、`concat-slices-v1` 的冻结产物，在 node030 本项目目录运行，新输出目录必须不存在：

```bash
python3 scripts/cv32e40p_remaining_gap.py prepare --output build/cv32e40p/gap-reproduce
python3 scripts/cv32e40p_remaining_gap.py build --output build/cv32e40p/gap-reproduce
python3 scripts/cv32e40p_remaining_gap.py count --output build/cv32e40p/gap-reproduce
python3 scripts/cv32e40p_remaining_gap.py pmu --output build/cv32e40p/gap-reproduce
python3 scripts/cv32e40p_remaining_gap.py mapping --output build/cv32e40p/gap-reproduce
python3 scripts/cv32e40p_remaining_gap.py report --output build/cv32e40p/gap-reproduce
PYTHONPATH=scripts python3 -m unittest test_cv32e40p_code_shapes
```

- [汇总报告](../../build/cv32e40p/remaining-gap-v1/report.json)、[静态身份与逐值类型](../../build/cv32e40p/remaining-gap-v1/static.json)、[形态/常量集合证据](../../build/cv32e40p/remaining-gap-v1/shape-evidence.json)
- [独立计数构建](../../build/cv32e40p/remaining-gap-v1/count-build.json)、[完整计数](../../build/cv32e40p/remaining-gap-v1/counts.json)、[逐次功能/placement](../../build/cv32e40p/remaining-gap-v1/runs/)
- [GrhSIM PMU](../../build/cv32e40p/remaining-gap-v1/grhsim-stat.csv)、[同 RTL Verilator PMU](../../build/cv32e40p/remaining-gap-v1/verilator-stat.csv)、[原始 Verilator PMU](../../build/cv32e40p/remaining-gap-v1/verilator-original-stat.csv)
- [源码行采样](../../build/cv32e40p/remaining-gap-v1/grhsim-lines.txt)、[解析后的采样行](../../build/cv32e40p/remaining-gap-v1/hot-lines.json)、[源码/IR/planner 映射](../../build/cv32e40p/remaining-gap-v1/sources.csv)、[映射身份](../../build/cv32e40p/remaining-gap-v1/mapping-identity.json)
- [最终验证](../../build/cv32e40p/remaining-gap-v1/validation.json)、[计数回归](../../scripts/test_cv32e40p_code_shapes.py)

分析代码和文档留在当前调查分支工作树，尚未新增提交；生产实现与 TNO0005 一致。
