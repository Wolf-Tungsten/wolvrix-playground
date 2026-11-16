# TNO0032：可组合状态表达式与独立空入口验证

可组合状态表达式的有限内联版，相对 TNO0030 的直接读取版降低外部 walltime **3.5247%**，95% CI **[−4.1448%, −3.1584%]**；相对同归一化 RTL Verilator 为 **0.976343 倍**，即 walltime 低 **2.3657%**，CI **[低 2.1976%, 低 2.5748%]**，8/8 轮更快。

随后独立验证已有的 compute 调用守卫，仍以 TNO0030 为基线，没有叠加复合表达式。它使 walltime 平均降低 **0.1515%**，CI **[−0.3331%, +0.0127%]**，尚不能确认稳定时间收益。

两个实验各自只有一组固定 8 轮测量。所有生成规则、预算和比较关系均在计时前确定；没有按运行结果选择站点、调整参数、筛除慢样本或生成组合候选。新复合表达式开关及原守卫仍默认关闭，结果限定于这份冻结 CoreMark 对照。

## 可组合状态表达式实现

在现有激活覆盖证明基础上，新增默认关闭的 `covered_state_view_composition` 及 `covered_state_view_composition_inline`；对应环境变量为 `WOLVRIX_GRHSIM_COVERED_STATE_VIEW_COMPOSITION` 和 `WOLVRIX_GRHSIM_COVERED_STATE_VIEW_COMPOSITION_INLINE`。原 parent／inline 选项仍控制原有一层视图，不因新选项改变其决定。

新证明追溯本区域的 scalar DAG：assign、静态 slice、按位／逻辑 not、Eq、按位／逻辑 and/or、concat、reduce-or。寄存器叶子必须是本区域的直接读取，且全部归于同一状态符号；不同 SSA read 可以代表同一寄存器快照。单写者、类型、位宽、有符号属性、定义顺序、独立激活覆盖、纯消费者和完整 fanout 条件继续检查。每个节点复用现有 typed scalar renderer，保留中间截断语义。

公开／event／别名／cache key／cache result 在整个依赖链上作为边界保护，不能只检查根节点。外部输入、多寄存器、未知常量、memory／latch read 和不支持的操作均回退。证明所用状态激活集合在删除任何边之前冻结。

固定预算为：最多 32 个不同的非 read／constant 运算、深度上限 16；内联还要求展开后的表达式树最多 4 个运算，树运算数乘 scheduled operand uses 不超过 16，文本不超过 4096 B。共享子表达式在展开预算中重复计费。较长表达式可只去通知、保留结果存储，不因全局 inline 开关而一并删除槽位。[功能说明](../../wolvrix/docs/emit/grhsim-covered-state-views.md)。

两个预先固定阶段分别是：

1. 原 21 个视图保持内联；对新增证明只删除比较／通知，保留计算和槽位。
2. 使用完全相同的新证明集合；对通过上述静态预算的表达式进一步去槽位／赋值。

最终新增证明 **70 个根**，其中 **52 个内联、18 个保留存储**。TNO0031 初筛的 71 个非缓存结果依赖根中，`fencei_insn_i`（30733）还经过缓存键 43898（`_val_176`），完整保护将它保留。这是静态所有权边界，不是根据执行频率选择。独立预算审计确认所有 70 个存储决定均与预先固定的树成本／使用次数门一致。[结构与逐根证明](../../build/cv32e40p/state-expressions-v1/structure.json)、[预算审计](../../build/cv32e40p/state-expressions-v1/inline-budget-audit.json)、[计时前假设](../../build/cv32e40p/state-expressions-v1/hypothesis.json)。

| 结构 | TNO0030 基线 | 仅去新通知 | 有限内联 |
| --- | ---: | ---: | ---: |
| checked values | 188 | 118 | 118 |
| bool/u8/u16/u32/u64 槽位 | 336/46/4/90/2 | 336/46/4/90/2 | 285/46/4/89/2 |
| scheduler C++ 字节 | 1,040,219 | 1,037,729 | 1,049,346 |

关闭新选项时，生成源码逐文件等于 TNO0030 基线。两阶段保持相同冻结 IR、39 个区域、旧 21 个视图及全部共享译码／精确输入缓存／条件锥站点。

## 功能与行为计数

两项实验使用同一冻结图、CoreMark、harness、Clang 23.1.2 和 `-O3 -march=native`，均在 node030 编译。所有后端的 smoke 和完整 CoreMark 输出、CRC、退出状态、完成周期及逐周期总线 trace 一致。CoreMark 为 **3,376,065 周期**，trace SHA 为 `ed2b490886767aa74524a6dd15e708e8f2b231bc3886814af0ba4d1919b3e098`。

| binary | SHA-256 |
| --- | --- |
| TNO0030 基线 | `32771c541f782bf6d1ed443be30479591f9cf2cdebd14e5ae00078ea0d103849` |
| 复合表达式，仅去通知 | `b60d1f80d6e7f522166e4000dc9ce3f28bd8bda0e813d6ce269fe2aff412ce13` |
| 复合表达式，有限内联 | `e8d9d685fd24a18b4a9cc478a5ceeea998b1ce65fb51a1818d1f4cc91fbf1faf` |
| 独立 compute 调用守卫 | `d51faca74a3a5f273c446ee31e331505eb824b2344058a9741615b44233be25a` |
| 同 RTL Verilator | `5396106991546a7aa0da975a44e9b92c21988bf6a4d60d4755bdafa370be7614` |

复合表达式两阶段的全部诊断计数相同。删除所选 70 个根的比较／变化探针后，**327 项保留行为计数与基线完全一致**，包括区域／函数执行、fixed-point 轮数、缓存、条件分支和其余逐值检查。每周期检查 **147.383499 → 82.835589**，减少 **64.547910 次（约 43.80%）**；相应 true-change 判定减少 6.733851 次／周期。每个 phase 都能按删去根的原计数闭合，没有扩大激活范围或减少模拟周期。

输入、源代码、native tools、编译参数及各 binary 身份见两个 [expression build](../../build/cv32e40p/state-expressions-v1/build.json)、[entry build](../../build/cv32e40p/compute-entry-guard-v1/build.json)。功能和计数见 [expression functional](../../build/cv32e40p/state-expressions-v1/functional.json)、[expression count gate](../../build/cv32e40p/state-expressions-v1/count-gate.json)、[entry functional](../../build/cv32e40p/compute-entry-guard-v1/functional.json)、[entry count gate](../../build/cv32e40p/compute-entry-guard-v1/count-gate.json)。诊断计数仅验证／解释冻结模型，没有传入生成器。

## 复合表达式配对测量

node030 CPU96、NUMA1、单线程、ASLR 关闭；每后端预热一次，一组 8 轮四后端正反序。32 个正式样本全部通过功能和 placement/locality 门，attempt 均为 0，无重试或删除。CPU288 sibling 记录为空闲 100%。

| 后端 | 外部 walltime 均值 | 相对同轮基线的配对变化 | 95% CI |
| --- | ---: | ---: | --- |
| TNO0030 基线 | 2.848842 s | — | — |
| 仅去新通知 | 2.772577 s | −2.6688% | [−3.3766%, −2.2277%] |
| 有限内联 | 2.748218 s | −3.5247% | [−4.1448%, −3.1584%] |
| Verilator | 2.814824 s | — | — |

有限内联相对仅去通知再降低 **0.8782%**，CI **[−1.0543%, −0.7220%]**。两个阶段相对基线、相对 Verilator 以及内联相对通知都是 8/8 轮更快。

有限内联的仿真循环相对基线降低 **3.3785%**，CI [−3.5711%, −3.2253%]；相对 Verilator 循环降低 **2.2794%**，CI [−2.4990%, −2.0995%]。初始化均值约为基线 6.062 ms、通知版 6.096 ms、内联版 6.101 ms，收益位于持续仿真。

同轮基线／Verilator 比值为 1.012090；通知版为 **0.985002**，CI [0.982057, 0.987963]；内联版为 **0.976343**，CI [0.974252, 0.978024]。使用同轮配对结果，不把历史轮次的绝对时间相减。[逐对数据](../../build/cv32e40p/state-expressions-v1/pairs.csv)、[汇总](../../build/cv32e40p/state-expressions-v1/summary.json)、[完整报告](../../build/cv32e40p/state-expressions-v1/report.json)。

每后端一次独立 PMU 计数（含初始化，不替代配对计时）：

| 每模拟周期 | 基线 | 仅去新通知 | 有限内联 | Verilator |
| --- | ---: | ---: | ---: | ---: |
| retired instructions | 10131.255 | 9749.532 | 9720.246 | 9799.122 |
| branches | 465.788 | 465.788 | 460.143 | 568.442 |
| branch misses | 1.276 | 1.261 | 1.319 | 0.881 |

仅去通知就少 **381.723 条退休指令／周期**，内联后累计少 **411.010 条（约 4.06%）**。这次主要减少的是中间值维护协议；内联又减少 29.287 条／周期。分支失败没有随所有指标一起改善，不能将时间收益全部归因于单一微架构因素。

ELF 中 compute batch 1 的静态指令 **2280→1915→1816**，字节 **10317→8882→8206**；batch 2 指令 **8100→8098→8101**，字节 **39133→39093→38632**。batch 1 栈分配 **184→160→160 B**，batch 2 为 **2488→2488→2408 B**。这些是静态形态，不是动态 spill 或时间占比。

逐个核对新增 70 个根的比较标记消失、52 个内联根的原槽位引用消失；同时核对 ELF 内嵌源文件 MD5。`Not(Slice(q))` 与 `Slice(Not(q))` 的计算保留其位宽语义，前者现在可越过原单层证明断点进入消费者。[源码／ELF 与预算证据](../../build/cv32e40p/state-expressions-v1/machine-evidence/report.json)、[计数／PMU 分析](../../build/cv32e40p/state-expressions-v1/analysis.json)。

## 独立验证已有空入口开关

审阅 emitter 后确认已有 `compute_batch_dispatch_guard` / `WOLVRIX_GRHSIM_COMPUTE_BATCH_DISPATCH_GUARD` 实现所需机制：每个 compute 调用前读取它精确对应的活动字掩码。复用这项机制，没有新增重复实现，也没有只挑选 batch 2。

对照基线在复合表达式计时前已固定为 TNO0030。本实验复合表达式关闭，仅调用守卫开启。生成文件中只有 **`grhsim_Cv32Bench_eval.cpp`** 改变，所有 batch body、header、布局、IR、188 个 checked values 和缓存站点保持一致。[结构检查](../../build/cv32e40p/compute-entry-guard-v1/structure.json)、[预先固定假设](../../build/cv32e40p/compute-entry-guard-v1/hypothesis.json)。

实际 group 执行、值检查／变化、缓存及轮数保持一致；除四个 compute 函数调用计数外，**463 项计数完全相同**。每周期减少的调用为 batch 0：2.245464，batch 1：0.0000435，batch 2：2，batch 3：2，合计 **6.245508 次**。最大 batch 的调用由每周期约 3 次降至约 1 次，前一 batch 在本轮产生的激活仍会被后面的调用点看到。

相同 placement 条件下，三后端各预热一次，独立一组 8 轮正反序，全部通过门，attempt 均为 0：

| 后端 | 外部 walltime 均值 |
| --- | ---: |
| TNO0030 基线 | 2.834389 s |
| compute 调用守卫 | 2.830092 s |
| Verilator | 2.815933 s |

守卫相对基线 walltime **−0.1515%**，CI **[−0.3331%, +0.0127%]**，7/8 轮更快；循环 **−0.1407%**，CI **[−0.3177%, +0.0168%]**。相对 Verilator 为 **1.005040**，CI [1.002384, 1.007544]。尚不能确认稳定时间收益；没有因此调整守卫范围或再跑一轮选择。

PMU 指令 **10131.256→10083.353**，净少 **47.903 条／周期（约 0.473%）**。caller 的 `eval()` 从 154 增至 164 条静态指令，新增调用前检查；活跃 callee 仍保留自身入口检查，batch 2 保持 8100 条／39133 B。空调用确实消失，但它的毛开销不能全部当作净节省，也不足以保证这组样本中稳定的 walltime 改善。[逐对结果](../../build/cv32e40p/compute-entry-guard-v1/pairs.csv)、[汇总](../../build/cv32e40p/compute-entry-guard-v1/summary.json)、[诊断分析](../../build/cv32e40p/compute-entry-guard-v1/analysis.json)。

本轮没有同时开启复合表达式与守卫的测量，不能将两个独立结果相加。

## 测试、适用边界与复现

**3 项 CTest** 通过：原状态视图回归、复合表达式回归、compute 入口回归。使用 Clang 23，覆盖 O0、O3 与 ASan/UBSan；复合表达式包含 1／17／64 bit、signed state、多时钟、异步复位、masked write、重复 eval、重新初始化，以及未知常量、公开值、多状态来源、缓存键和长表达式预算回退。

入口回归特别将生产者和消费者放在不同活动字，保持外部数据不变只推进时钟，验证前一 batch 产生的激活能被后一调用点立即看到。最初的 fixture 将同一活动字内的 group 误认为多个 batch；改为跨字 fixture 后通过，没有修改候选或生产守卫规则。两组整机 trace 也覆盖原始时钟门控和 RTL RAM。

**16 项相关 Python 测试**、`py_compile`、两仓 `git diff --check`、输入／输出身份和文档链接检查通过。计数门允许入口实验减少 compute 函数调用，但拒绝 group、commit、比较或 cache 行为漂移；倍率测试使用明确后端名称。[统一验证记录](../../build/cv32e40p/state-expressions-v1/validation.json)。

复合表达式规则可作用于具有相同寄存器快照和激活覆盖条件的其他设计；XiangShan 的 reg-to-mem 或跨分区存储仍不在这个证明范围内。调用守卫也需遵守其现有调度入口，不能替代 commit／latch 的事件语义。本轮没有 XiangShan 新跑分，未外推收益。

使用新输出目录，在 node030 复现：

```sh
python3 scripts/cv32e40p_state_expression_compare.py build --output build/cv32e40p/state-expressions-reproduce
python3 scripts/cv32e40p_state_expression_compare.py verify --output build/cv32e40p/state-expressions-reproduce
# 对两个候选分别运行已有 detailed counter driver，再执行 counts 门。
python3 scripts/cv32e40p_event_region_counts.py --source build/cv32e40p/state-expressions-reproduce --backend grhsim_state_expression_notify --output build/cv32e40p/state-expression-notify-counts-reproduce --detailed
python3 scripts/cv32e40p_event_region_counts.py --source build/cv32e40p/state-expressions-reproduce --backend grhsim_state_expression_inline --output build/cv32e40p/state-expression-inline-counts-reproduce --detailed
python3 scripts/cv32e40p_state_expression_compare.py counts --output build/cv32e40p/state-expressions-reproduce --notify-counts build/cv32e40p/state-expression-notify-counts-reproduce --inline-counts build/cv32e40p/state-expression-inline-counts-reproduce
python3 scripts/cv32e40p_state_expression_compare.py measure --output build/cv32e40p/state-expressions-reproduce
python3 scripts/cv32e40p_state_expression_compare.py diagnose --output build/cv32e40p/state-expressions-reproduce
python3 scripts/cv32e40p_state_expression_compare.py analyze --output build/cv32e40p/state-expressions-reproduce
python3 scripts/cv32e40p_state_expression_evidence.py --source build/cv32e40p/state-expressions-reproduce

python3 scripts/cv32e40p_compute_entry_compare.py build --output build/cv32e40p/compute-entry-reproduce
python3 scripts/cv32e40p_compute_entry_compare.py verify --output build/cv32e40p/compute-entry-reproduce
python3 scripts/cv32e40p_event_region_counts.py --source build/cv32e40p/compute-entry-reproduce --backend grhsim_compute_entry_guard --output build/cv32e40p/compute-entry-counts-reproduce --detailed
python3 scripts/cv32e40p_compute_entry_compare.py counts --output build/cv32e40p/compute-entry-reproduce --counts build/cv32e40p/compute-entry-counts-reproduce
python3 scripts/cv32e40p_compute_entry_compare.py measure --output build/cv32e40p/compute-entry-reproduce
python3 scripts/cv32e40p_compute_entry_compare.py diagnose --output build/cv32e40p/compute-entry-reproduce
python3 scripts/cv32e40p_compute_entry_compare.py analyze --output build/cv32e40p/compute-entry-reproduce
```

发射／编译／链接时间单列于各 `logs/*.result.json`，未计入运行时间；约为通知版 1.854／16.750／1.084 s、内联版 1.864／16.822／1.079 s、入口版 1.793／16.657／1.079 s。构建阶段存在其他验证任务，不据这些单次数字宣称构建速度改善。
