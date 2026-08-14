# 001. Exact-event commit lowering 与 cold-layout 提示

这是 SimpleTES 在当前 Wolvrix 工作线中落地的第一组优化。它来自 2026-07-23 至
2026-07-25 的 gen20/gen24 研究，最终由 Wolvrix 提交
`8f6ba14397b0c3d00cb909153af1c6464f4f1ed9` 合入（该提交的父提交仍是
SimpleTES 启动时固定的基线）。[^scope][^commit]

## 先理解 GrhSIM 的一轮执行

Wolvrix 会把若干 IR（intermediate representation，中间表示）操作合并成调度单元，
称为 **supernode**。compute supernode
负责计算组合值，commit supernode 负责寄存器/存储器写入和其他有副作用的操作。每个
需要按需执行的 compute supernode 都有一个 **active ID**，也就是活动位图
`supernode_active_curr_` 中对应 bit 的位置；bit 为 1 表示该 supernode 仍待执行。

一次 `eval()` 可能需要反复执行多个 **fixed-point round（定点迭代轮次）**，直到本轮
不再产生需要重新计算的工作：[^runtime]

```text
外部输入变化
  -> 激活第一批读取它的 compute supernode（input head）
  -> compute 结果变化，沿 boundary fanout 激活后续 compute supernode
  -> commit 根据事件和写入条件更新可见状态
  -> 状态若变化，则激活第一批读取该状态的 compute supernode（state-reader head）
  -> 仍有有效工作时进入下一轮，否则本次 eval 结束
```

这里的 **head** 是一次变化传播的入口 supernode，不是源码文件或 CPU 中的“头部”。
`compute-only head` 证明具体要求两张入口表里的所有 active ID 都指向 compute
supernode：一张表来自外部输入，另一张来自 commit 后可见状态的 reader。它是整个
模型能否使用本优化的一部分静态证明，并不是一个单独的运行时优化。

**boundary fanout** 是某个跨 supernode 值变化后需要激活的下游 compute
supernode 集合。**exact event** 则表示生成器能把一个操作的触发条件精确还原为
posedge、negedge 或任意边沿表达式；没有事件采样的写入，其事件表达式视为恒真。
本篇所说的 **continuation** 是“本轮结束后是否需要继续下一轮”的判断；**lowering**
则是 emitter 把这些内部操作和判断转换为具体 C++ 代码的过程。

## 做了什么

### 先看总结

这不是一个单点改动，而是一组围绕“生成器已经精确知道某批提交操作由什么事件触发”
展开的优化。它不减少硬件模型应执行的逻辑，也不改变寄存器、memory 或 assertion 的
结果；它主要让生成的 C++ 少做重复判断，并让编译器把低概率提交代码移出热路径。

| 层面 | 旧生成形式 | 新生成形式 | 目的 |
|---|---|---|---|
| 是否再跑一轮 | 每轮末尾都检查活动位图 | 证明安全后，仅在存在相关 event edge 时才用位图触发下一轮；无事件写入仍由独立标志兜底 | 避免没有事件时的无效检查和空轮次 |
| 一组同步寄存器 | 每个寄存器分别计算 next 值并判断是否变化 | 对能够证明始终同步的寄存器，只计算一次 next 值并用一个代表寄存器判断变化，随后仍写回组内每个寄存器 | 去掉重复计算和比较 |
| 大量低概率写 guard | 普通 `if (cond)` 与热代码混排 | 对足够大的 singleton register-write run 使用 `if (unlikely(cond))`，并把活动位图按缓存行对齐 | 改善编译器生成的冷热代码布局和 CPU 前端供给 |
| 启用与回退 | 早期候选曾借用别的实验开关 | 使用独立 policy；任一结构证明失败就完整生成旧通用路径 | 保证通用默认可用，不依赖 SimTop 特判 |

如果只记住一个结论：**完整 patch 提供了安全的 exact-event 专用生成框架，但约 18%
端到端提升的主要来源，是第三行的大规模 cold-layout `unlikely` 提示。**后面的内容是在
解释每一行具体如何实现，以及为何不会改变仿真语义。

### 实现与安全细节

该候选先判断整个模型是否满足 exact-event continuation 的安全条件，再在生成 C++
时利用这些条件：

* 静态证明要求：调度图是无环图，topological order（依赖拓扑顺序）有效，active ID
  与该顺序一致；每个 boundary value 都由 compute supernode 产生，且只激活排在
  它后面的 compute supernode；input head 和 state-reader head 也全部是 compute
  supernode。任一条件不成立，生成器就完整回退到旧 lowering，也就是 fail closed。
  [^source]
* 此外，在性能诊断、波形、runtime profile、input/posedge full-pass、state shadow 等
  会改变执行协议的模式下，或者设计根本没有事件边时，该路径也会保守关闭。这里的
  full-pass 是跳过 active-bit 筛选、直接运行整段 compute schedule 的另一种快路径；
  state shadow 是为提交阶段暂存可见状态的兼容机制。[^source]
* 旧 continuation 在每轮末尾执行
  `commit_activated_readers_ || any_active(bitmap)`；新路径改为
  `commit_activated_readers_ || (any_event_edge && any_active(bitmap))`。也就是说，
  没有任何事件边时先短路，不再扫描整张活动位图。`trackCommitActivation` 是 emitter
  内部决定是否生成 tracking 语句的布尔参数，不是运行时调用的函数：有显式事件的
  commit write 由“事件仍存在 + reader bit 已置位”负责续轮；无事件条件的 write
  仍使用 `commit_activated_readers_`。该标志只会在可见状态确实变化并且存在 reader
  时置位。[^source]
  这个短路之所以安全，依赖前述整组证明：有效拓扑顺序和只向前的 boundary fanout
  保证 compute 在本轮激活的后继会在同一轮后续位置耗尽；compute-only head 保证入口
  位也只表示 compute 工作。需要跨轮保留的 reader 工作只能由 commit 新激活：有显式
  事件条件的 commit 若能激活 reader，必然伴随本轮存在相应 event edge；没有事件条件
  的 commit 则仍由 `commit_activated_readers_` 独立兜底。因此在
  `any_event_edge == false` 且运行时 `commit_activated_readers_ == false` 时，残留
  bitmap 不代表需要开始新一轮的有效工作。任一前提无法静态证明，就不使用这个公式。
* **run** 是同一个 supernode 中连续出现且共享同一 exact-event 表达式的一段 write-port
  操作；**guard** 是决定写入是否执行的布尔条件。对同一 guard 下、同一标量类型和
  宽度、单写者、全 1 写掩码、相同 next 表达式及 init 初值的寄存器写，生成器建立
  **lockstep** 组：只计算一次 `next_value`，只用代表寄存器做一次变化比较，但条件成立
  时仍会逐个写回所有寄存器。同一初值、单写者、同 guard/next 和完整写入保证组内
  寄存器从初始化开始始终同步，所以用一个代表寄存器判断“值是否变化”是安全的；它没有
  省略任何应发生的写入。[^source]
* 整张活动位图以 `alignas(64)` 对齐到 64-byte cache line（CPU 缓存传输和存放的
  基本块）；这不是“把某个 run 对齐”。当一个
  exact-event run 中有至少 `1024` 个 **singleton register-write guard** 时，生成器
  把这些条件写成 `if (unlikely(cond))`。singleton 在这里表示该 guard group 只有一个
  写操作，不是单 bit 寄存器。这个 cold hint 是约 18% 端到端收益的主要来源；gen20
  中没有该 hint 的普通 `if` 作为对照保留。[^ablation][^source]
* 引入独立的 `commit_exact_event_policy=off|targeted-cold-layout` 配置项。C++/Python
  的默认生成路径使用 `targeted-cold-layout`，Python 的 `None` 继承 C++ 默认；
  `targeted-direct` 只属于 gap-pack，不再是 exact-event 的隐含开关。[^policy]

因此，这不是针对 SimTop 名字或某个负载字符串的特判。实现当然会使用 `ValueId`
作为图中值的通用内部身份，但不会匹配某个固定的 ValueId 编号；selector 只检查事件
图的结构性质和固定阈值，没有通过时会回退到旧 emitter（C++ 代码生成器）。[^policy]

## 为什么这样做

早期搜索看到 gen24 相对基线约 18% 的 walltime 下降。gen20/gen24 是 SimpleTES
搜索树中的候选 generation 编号，并不是 Wolvrix 版本号；gen24 又是一个复合候选，
不能直接把整份 patch 当作因果结论。SimpleTES 随后构造了 gen20（去掉 cold
hint）和 gen24（只增加 `>=1024` run 的 `unlikely`）两个 fresh、单变量候选；这里
fresh 表示从同一个固定基线重新物化、生成和构建，不复用可疑的旧工作树或二进制。
两者的结构、options 和其余 exact-event lowering 相同，所以可以把增量归因给
分支布局提示，而不是把动态指令减少误认为性能来源。[^ablation]

`unlikely` 会向编译器传达“该 guard 通常不成立”的信息，使冷路径从热路径中移开，
改善生成代码的热/冷布局和 CPU 前端供给；它不改变条件的求值或语义，也不要求
运行时识别 SimTop。PMU（CPU 硬件性能计数器）对照显示两个实验 arm（变体）的
retired instructions 减少几乎相同，而 gen24 的 cycles、frontend no-op 和 severe
frontend empty 额外下降约 18%。后两项反映前端没有及时提供可执行指令的程度，因而
与“代码布局改善”这一解释一致；PMU 只用于解释，最终裁决仍看 walltime。[^ablation]

## 收益（SimTop 50k walltime）

正式口径是关闭 ASLR（地址空间随机化），并控制 NUMA 内存节点与空闲 CCD（AMD
处理器中共享末级缓存的一组核心），以减少代码地址、跨节点访存和共享缓存负载造成的
波动。control 是旧实现，candidate 是待测实现；ABBA 表示按
control-candidate-candidate-control 交错执行，BAAB 是反向顺序。pooled 值是合并
两个顺序中有效样本后，分别计算 control 与 candidate 的均值。headline 只取 SimTop
50k 日志中的 `Host time spent` walltime。改善定义为
`(control - candidate) / control`；表中绝对值均为毫秒。[^ablation]

| 对比 | control（ms） | candidate（ms） | walltime 减少（ms） | 相对改善 |
| --- | ---: | ---: | ---: | ---: |
| gen20：exact-event、无 cold hint | 73,928.00 | 73,237.50 | 690.50 | 0.934017% |
| gen24：exact-event + `>=1024` cold hint | 74,055.00 | 60,648.25 | 13,406.75 | 18.103774% |
| cold hint 的单变量增量（gen24−gen20） | — | — | — | **17.169757 个百分点** |

gen20 的 `0.934017%` 小于该 arm 的 control spread（control 样本极差相对均值，
4.823612%），不能作为可靠提升；gen24 为 18.103774%，高于 1.432719% 的 spread
可信线，且 ABBA/BAAB 分别
为 18.046108%/18.160818%，方向一致。[^ablation]

落地到 Wolvrix 后，在 native 默认路径做的独立回归仍观察到 exact-event 相对
旧基线 pooled `74,773.25 -> 61,284.00 ms`，减少 `13,489.25 ms`、改善
`18.040208%`；ABBA/BAAB 为 `18.100624%`/`17.979760%`。这一次是 landing
验证，不能与前一轮不同测量窗口的绝对值直接相减，但确认了端到端方向和数量级。[^fourarm]

## 落地与安全边界

* 提交：`8f6ba14397b0c3d00cb909153af1c6464f4f1ed9`，改动主要在
  `lib/emit/grhsim_cpp.cpp`，并带有对应测试；完整 stat 为 7 个文件、
  `+1335/-14`。[^commit]
* 默认：通用 C++/Python 流程默认启用 `targeted-cold-layout`，不是只给 SimTop
  单独打开；XS（XiangShan 集成脚本）只有显式 override 才改变策略。[^policy][^landing]
* `active_mask_gap_pack_policy=targeted-direct` 不再被借用。SimpleTES 的依赖审计
  证明 exact-event 路径不读取 gap-pack 状态；gap-pack 自己的增量只有
  `0.155120%` 且低于门槛，因此继续关闭。gap-pack 是另一项重新组织 activity
  bitmap 相邻写入的候选优化，不是 exact-event continuation 的组成部分。[^policy][^fourarm]
* 所有结构证明、功能测试、100/10k/50k gate、固定 ASLR、NUMA/CCD、PMU 和
  artifact identity 检查均要求通过；gate 是进入下一阶段前必须通过的验收条件，
  artifact identity 则用提交和 SHA-256 等身份确认两边实际测试的是预期源码与二进制。
  证明不成立时 fail closed。[^ablation][^landing]

## 其他信息

约 18% 的提升不是“删除了 18% 的仿真工作”：gen20/gen24 的 instructions 相对
各自 control 分别减少 1.181418%/1.185308%，而 gen24 的 cycles 减少 18.240417%，
frontend no-op 减少 18.807172%。这说明主要收益来自编译器对冷分支的布局/预测处理，
而不是针对 SimTop 变量名的作弊式匹配。[^ablation]

### 数据来源（尾注）

[^scope]: [`TNO0156`：SimpleTES bench 启动与固定基线](../grhsim_opt_thj/TNO0156_simpletes_auto_research_bench_and_launch_gate_20260720.md)，其中记录了 SimpleTES 研究起点和 Wolvrix 基线 pin；该文档以前的手工优化不计入本目录。
[^ablation]: [`TNO0173`：gen20/gen24 cold-guard 单变量消融](../grhsim_opt_thj/TNO0173_gen20_gen24_fresh_cold_guard_hint_ablation_result_20260724.md)，含 fresh 50k 的绝对 walltime、相对变化、ABBA/BAAB、PMU 与 artifact 证据。
[^policy]: [`TNO0174`：targeted-direct 依赖审计](../grhsim_opt_thj/TNO0174_gen24_targeted_direct_dependency_audit_and_landing_plan_20260725.md)，以及 [`TNO0175`：独立 policy 实现与静态 gate](../grhsim_opt_thj/TNO0175_gen24_independent_policy_implementation_and_static_gate_20260725.md)。
[^fourarm]: [`TNO0176`：gen24 四臂正式 walltime 与默认决策](../grhsim_opt_thj/TNO0176_gen24_four_arm_function_formal_walltime_and_default_decision_20260725.md)。
[^landing]: [`TNO0179`：native 默认路径 canary 与继续研究准备](../grhsim_opt_thj/TNO0179_simpletes_v2_pinned_native_control_canary_and_continuation_ready_20260725.md)，记录提交后的默认路径身份和回归门禁。
[^commit]: Wolvrix 子模块提交 `8f6ba14397b0c3d00cb909153af1c6464f4f1ed9` 的 Git metadata 与 diff：`lib/emit/grhsim_cpp.cpp`、相关测试及提交说明；可在 `wolvrix` 子模块中用 `git show --stat --summary 8f6ba14397b0c3d00cb909153af1c6464f4f1ed9` 复核。
[^source]: 同一提交的 `lib/emit/grhsim_cpp.cpp` 中 `CommitExactEventPolicy`、`canUseEventQualifiedBitmapContinuation`、lockstep 分组和 cold-guard emitter；当前源文件对应区域约为 policy/parser 322–346、2524–2548，证明 selector 18726–18800，lockstep 20266–20380，cold emit 21295–21408。
[^runtime]: Wolvrix [`grhsim-scheduling.md`](../../wolvrix/docs/emit/grhsim-scheduling.md) 的 Runtime model/eval 小节，说明 `activeIdBySupernode`、两张 head map、活动位图、commit reader tracking 和 fixed-point round 的时序。
