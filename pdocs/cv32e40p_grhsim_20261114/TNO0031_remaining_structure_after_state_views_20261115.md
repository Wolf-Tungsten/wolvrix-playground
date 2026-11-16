# TNO0031：直接状态视图之后的剩余结构开销

本轮仅分析 TNO0030 已冻结的直接读取版与同归一化 RTL Verilator，复用已有计数和测量，不运行模拟器、不采集新 profile、不生成优化候选，也不修改生产代码。最明确的后续方向是**把单运算状态视图扩展为可组合的状态表达式证明**，其次是让空 compute batch 在进入大函数前退出。compute→commit 的暂存／通知契约仍有开销，但需要更完整的状态快照设计。

## 当前差距的口径

| 项目 | GrhSIM 直接读取版 | 同 RTL Verilator |
| --- | ---: | ---: |
| ELF SHA 前缀 | `32771c541f782bf6` | `5396106991546a7a` |
| TNO0030 外部 walltime 均值 | 2.838107 s | 2.810657 s |
| 每模拟周期退休指令（各一次独立 PMU） | 10131.255 | 9799.122 |
| 每模拟周期分支 | 465.788 | 568.442 |
| 每模拟周期分支失败 | 1.284 | 0.876 |

原 8 轮配对的外部 walltime 比值为 **1.009767**，95% CI **[1.008574, 1.011121]**；仿真循环为 **1.011137**，CI **[1.010223, 1.012157]**。GrhSIM 初始化均值 5.960 ms，Verilator 为 9.533 ms，当前持续运行差距不能归因于 GrhSIM 启动较慢。

退休指令净差约 **332.133 条／模拟周期（3.389%）**，比时间差的百分比大。分支总量反而更少，而分支失败更多；没有对应当前 ELF 的事件采样，不能根据这几个总数把剩余约 1% 分摊给某种微架构因素。本报告列出可验证的额外工作与结构原因，不声称这些开销的毛额恰好等于两后端净时间差。

身份核对包含两份 ELF、计数原模型、CoreMark 的 **3,376,065 周期**及 trace SHA `ed2b490886767aa74524a6dd15e708e8f2b231bc3886814af0ba4d1919b3e098`。重新对应当前 ELF 的 DWARF 与生成 C++，GrhSIM 7 个、Verilator 2 个被使用文件的内嵌 MD5 全部匹配。source mapping 与冻结图的 op／结果也逐一验证。[离线报告](../../build/cv32e40p/post-view-structure-v2/report.json)、[原配对结果](../../build/cv32e40p/covered-state-views-v1/summary.json)。

## 1. 简单视图消除了，但状态来源没有贯穿复合表达式

当前还有 **188 个 checked values、147.383499 次检查／周期**。其中 178 个只跨 compute 边界，没有直接 commit／公开输出／event 用途，贡献 **139.356774 次／周期，占 94.5539%**。另按位宽统计，165 个一位结果贡献 128.999263 次／周期；这与前一类别有交集，不能相加。

最直接的例子是指令 bit14：TNO0030 已删去 value 37838 的槽位，但它的反相结果 value **7797** 仍然物化。在当前 [compute batch 1](../../build/cv32e40p/covered-state-views-v1/grhsim_covered_view_inline/grhsim_Cv32Bench_sched_1.cpp) 第 785–791 行，其代码仍等价于：

```cpp
next = !(instruction_register & (1u << 14));
changed = old_view != next;
any_changed |= changed;
old_view = next;
```

这里反相前的位读取已经内联，外层仍背着旧副本与通知。类似地，ALU `operand_a_neg[11]`（value 26812）是 `Slice(Not(q))`，仍独立保存和比较。两例的 ELF 都保留了槽位读取／写入及 `setne`／OR 等维护操作，而不只是未优化的源码注释。实际检查次数分别约为 0.999956 和 0.718136 次／周期。

原因在 [buildCoveredStateViews](../../wolvrix/lib/emit/grhsim_cpp.cpp) 的证明边界：它要求结果只有一个操作数，而且其直接定义就是本区域 `RegisterReadPort`。因此 `Not(Slice(q))` 在第二层停止，`Slice(Not(q))` 同样停止；带常量的 `Eq(q, C)` 则因有两个操作数被排除。当前规则消掉的是一层接口，没有传递“这个结果仍是同一寄存器快照的纯函数”这一事实。

Verilator 的事件块可在消费者表达式中组合位段、取反和谓词，不要求这些可导出的内部值逐个维护变化通知。它也有跨函数临时值，不能说它完全没有存储；这里的区别是 GrhSIM 的通用活动调度先把区域输出定为持久接口，之后的局部视图规则尚不能组合消解这个接口。

本轮对所有剩余边界做了统一静态筛查：表达式只由本生产区域内的 scalar 位段、逻辑／位运算、Eq、concat、常量和直接寄存器读取构成，所有寄存器叶子归于同一状态符号；生产者及外部消费者已是该状态的直接 reader。先完成结构筛查，再附上已有执行计数；改变计数不会改变筛查集合。

| 静态范围 | 根数量 | 说明 |
| --- | ---: | --- |
| 满足上述初筛 | 101 | 表达式根，不是互不重叠的计算锥 |
| 依赖现有稀疏译码缓存 | 30 | 包含 18 个缓存结果本身及 12 个后继表达式 |
| 排除整个缓存依赖链后 | **71** | 合计 65.547866 次原有检查／周期 |
| 其中仅含 1–4 个非 read／constant 运算 | **64** | 合计 58.548173 次原有检查／周期 |

71 个根分别来自六个寄存器；其中指令寄存器 `core$_11272_` 占 42 个、控制状态 `core$_11356_` 占 17 个。它们的表达式有共享子图，不能按根数或运算数独立相加来估算机器指令节省。

**71 不代表已经证明可以删除。** 初筛尚未代替完整的单写者、类型／常量语义、快照版本、别名与槽位所有权、隐含 event／cache 用户、特殊执行 guard、顺序及重算成本证明。尤其不能把已缓存的 Eq 重新展开成每次比较。此列表仅为诊断产物，没有送入生成器。

建议的结构修复是建立有快照约束的状态表达式表示：把 `Not(Slice(q))`、`Slice(Not(q))`、常量比较等追溯到状态来源，分别决定“通知是否冗余”和“值是否值得直接读取”。较长或共享表达式可以先去掉冗余通知而保留计算结果；短表达式才在静态成本与共享条件允许时内联，避免把维护成本换成重复计算。现有稀疏缓存应继续拥有其表达式，而不是被普通 DAG 展开穿透。

## 2. 大函数的空调用仍支付完整入口开销

当前 `eval()` 每轮无条件调用 4 个 compute batch 和 1 个 commit batch，约 3 轮／模拟周期。重型 group 28 本体仍只在高电平第二轮执行一次，**没有三倍重复计算**；但函数入口的费用是另一回事。

`eval_compute_batch_2()` 包含 8 个 compute group，完整覆盖一个 8-bit 活动字。所有 group 在高电平第一轮的执行次数为零；低电平仅有初始化边界的四次 group 进入。用各 group 的边缘计数计算上下界，不假定这些稀有进入同一时刻发生，可以得到：每模拟周期空函数调用为 **[1.999999111, 2.0] 次**。

当前 ELF 的入口顺序为：

```asm
0x89e0  pushq %rbp              # 共六个保存
...
0x89ea  subq $0x9b8, %rsp       # 分配 2488 B
0x89f1  movzbl 0x83(%rdi), %ebx # 此后才读取活动字
0x89f8  testb %bl, %bl
0x89fa  jne 0x8a11             # 非空才进入主体
0x89fc  addq $0x9b8, %rsp
...                            # 六个恢复
0x8a0d  vzeroupper
0x8a10  retq
```

从函数入口到空返回恰好 **19 条指令**，含六次 push、六次 pop；不含 caller 的 call 指令。已有计数与这个单一路径对应，说明本负载每周期约支付 **38 条空入口路径指令**。栈分配本身只是调整 rsp，不表示访问了全部 2488 B。

Verilator 的 `eval_nba` 也会多轮求稳，但其重型 `nba_sequent__TOP__0` 在调用前经过触发判断；既有计数为每周期一次。当前 ELF 的 caller 在 `0x6561b` 做 `testb $0x6`，`0x6561d` 的分支决定是否到 `0x65622` 的 call。[调用方反汇编](../../build/cv32e40p/post-view-structure-v2/verilator-nba-caller.s)。两边的函数职责并非逐项等价，这个例子证明的是 guard 相对重型函数入口的位置不同。

这与生成文件的边界直接相关：GrhSIM 的 `eval.cpp` 无条件调用单独编译的 batch 方法，活动检查放在各 batch 的 C++ 文件内部；当前构建没有 LTO。调用方因而没有表达“活动字为空就不进入这个函数”的条件，优化依赖 callee 内部的入口布局。Verilator 在生成的调用方已经显式表达触发条件，不需要编译器跨文件把 guard 搬出来。

可研究将纯 compute batch 的活动字检查放到调用点、或一个不建立大栈帧的薄入口中。检查必须紧挨各次调用，读取前一 batch 刚更新过的活动位，不能在整轮开始一次性缓存所有 batch 的状态；commit／latch 的事件语义另行保留。新 guard 也有自己的检查和分支成本，**38 条是当前毛开销，不是承诺能净省 38 条**。batch 1 已有不同的提前返回布局，不能把 batch 2 的结论套给所有函数。

## 3. compute→commit 仍是暂存、读回、再判变的接口

上一轮的 21 个删除均位于 compute→compute，未触及提交接口。当前仍有 **273 个非常量物化 IR 值仅由 commit 直接消费**，235 个来自 group 28；这些值可能共享物理槽位，不能叫作 273 次实际机器写入。

以计数器 `core$_11244_` 为例，GrhSIM 的 commit 代码仍读取保存的 enable 和 next-value，与旧状态比较，条件写状态，并 OR 读者活动位。Verilator 对同一寄存器保留 enable 和赋值，事件块内没有相同的逐状态读者通知。它也保存 `__VdfgRegularize_*` next-state，因此此处能确认的额外契约是**逐状态判变与重新激活读者**，并非所有 next-state 暂存都只有 GrhSIM 才有。

这条路径适合未来研究按事件／状态快照组织提交和合并读者激活，但改动范围比前两项大。不能把 next-state 直接在逐寄存器提交时重算，否则可能读到已经被前一个写更新的状态。没有当前逐寄存器提交比较的精确计数，本轮不估算它在剩余时间中的比例。[两侧具体代码](../../build/cv32e40p/post-view-structure-v2/report.json) 的 `commit.examples`。

## 仍在的宽值／译码问题与优先级

直接读取版本没有叠加 TNO0029 的宽值条件执行或局部译码消费者实验。重新做当前 ELF 的 CFG 检查后，两份 2048-bit CSR view 仍各有 4 条向量清零 store 支配需求 guard；即使后续消费者不执行，准备也先发生。group 28 仍是 4,810 个 scheduled IR op、无 scalar changed 检查，DWARF 归属 7,117 条静态指令与 1,482 条栈内存操作数。它不能靠继续消除跨区域通知全部解决。

不过 TNO0029 已显示，仅把宽值准备下沉有控制形态抵消，单独测得 wall −0.34%；局部译码消费者单独的外部 walltime CI 跨零。它们可以继续改进，但不能把历史单项收益直接相加到当前版本，也不能把静态栈访问数解释成动态 spill 次数。Verilator 自身也有宽 view 与大函数，本轮没有 I-cache 瓶颈证据。

后续建议顺序为：**可组合状态视图证明 → 纯 compute 空入口 → 更完整的 compute/commit 快照接口**。前两项都有明确、局部的代码证据，可以形成不依赖工作负载频率的规则；第三项需要先设计状态可见性。保持对缓存和公共／事件边界的保护，不根据本次零变化、低命中或热度常量化任何逻辑。

这些机制也可能作用于 XiangShan 的状态译码和批次入口，但需分别确认其状态／内存表示、激活覆盖与 ELF guard 位置。reg-to-mem 存储和多分区通信不自动继承单寄存器视图证明；本轮没有 XiangShan 新测量或收益外推。

## 复现与验证

[分析脚本](../../scripts/cv32e40p_post_view_structure.py) 只读取冻结文件，并调用 nm、readelf、LLVM 反汇编／符号化工具；[回归测试](../../scripts/test_cv32e40p_post_view_structure.py) 验证状态符号合并、区域边界、传递性缓存依赖、计数不影响结构筛查、循环拒绝及空调用上下界。连同原有分析测试共 **21 项通过**。`py_compile`、输入 SHA、统计闭合、两仓 `git diff --check` 和文档链接检查通过。[验证记录](../../build/cv32e40p/post-view-structure-v2/validation.json)。

```sh
python3 scripts/cv32e40p_post_view_structure.py --output build/cv32e40p/post-view-structure-reproduce
PYTHONPATH=scripts python3 -m unittest test_cv32e40p_post_view_structure test_cv32e40p_current_structure test_cv32e40p_binary_shape test_cv32e40p_structure
python3 -m py_compile scripts/cv32e40p_post_view_structure.py scripts/test_cv32e40p_post_view_structure.py
```

产物含[总报告](../../build/cv32e40p/post-view-structure-v2/report.json)、[当前逐值／区域审计](../../build/cv32e40p/post-view-structure-v2/current-source.json)、[分函数反汇编](../../build/cv32e40p/post-view-structure-v2/assembly/)及压缩的源码／指令映射。本轮的离线结论没有自动导出开关、参数、候选配置或新的优化实现。
