# 001. Exact-event commit lowering 与 cold-layout 提示

这是 SimpleTES 在当前 Wolvrix 工作线中落地的第一组优化。它来自 2026-07-23 至
2026-07-25 的 gen20/gen24 研究，最终由 Wolvrix 提交
`8f6ba14397b0c3d00cb909153af1c6464f4f1ed9` 合入（该提交的父提交仍是
SimpleTES 启动时固定的基线）。[^scope][^commit]

## 做了什么

候选把一类“同一个输入事件、同一个提交阶段、且结构证明成立”的寄存器写路径
识别为 exact-event 路径，并在生成 C++ 时利用这个事实：

* 对满足拓扑、active-id、边界扇出、compute-only head 等证明的路径，生成
  event-qualified bitmap continuation，并只对实际激活的提交路径调用
  `trackCommitActivation`；证明失败时保留原始通用路径（fail closed）。
* 对同一标量类型/宽度、单写者、相同 next/init 形态的提交写入进行 lockstep
  分组，减少重复的提交状态更新。
* 对选中的 exact-event run 做对齐，并在 singleton register-write run 达到
  `>=1024` 条 guard 时将生成的条件写成 `if (unlikely(cond))`。后一个 cold
  hint 是约 18% 端到端收益的主要来源；gen20 中没有达到阈值的普通 `if` 作为
  对照保留。[^ablation][^source]
* 引入独立的 `commit_exact_event_policy=off|targeted-cold-layout`。C++/Python
  的默认生成路径使用 `targeted-cold-layout`，Python 的 `None` 继承 C++ 默认；
  `targeted-direct` 只属于 gap-pack，不再是 exact-event 的隐含开关。[^policy]

因此，这不是针对 SimTop 名字、ValueId 或某个负载字符串的特判：selector 只
使用事件图的结构性质和固定阈值，且没有通过时会回退到旧 emitter。[^policy]

## 为什么这样做

早期搜索看到 gen24 相对基线约 18% 的 walltime 下降，但 gen24 是一个复合候选，
不能直接把整份 patch 当作因果结论。SimpleTES 随后构造了 gen20（去掉 cold
hint）和 gen24（只增加 `>=1024` run 的 `unlikely`）两个 fresh、单变量候选。
两者的结构、options 和其余 exact-event lowering 相同，所以可以把增量归因给
分支布局提示，而不是把动态指令减少误认为性能来源。[^ablation]

`unlikely` 会向编译器传达“该 guard 通常不成立”的信息，使冷路径从热路径中移开，
改善生成代码的热/冷布局和前端供给；它不改变条件的语义，也不要求运行时识别
SimTop。PMU 对照显示两 arm 的 instructions 减少几乎相同，而 gen24 的 cycles、
frontend no-op 和 severe frontend empty 额外下降约 18%，与这个解释一致。[^ablation]

## 收益（SimTop 50k walltime）

正式口径是固定地址空间随机化关闭、固定 NUMA/CCD、ABBA+BAAB 的 SimTop 50k
`Host time spent` walltime。改善定义为
`(control - candidate) / control`；表中绝对值均为毫秒。[^ablation]

| 对比 | control（ms） | candidate（ms） | walltime 减少（ms） | 相对改善 |
| --- | ---: | ---: | ---: | ---: |
| gen20：exact-event、无 cold hint | 73,928.00 | 73,237.50 | 690.50 | 0.934017% |
| gen24：exact-event + `>=1024` cold hint | 74,055.00 | 60,648.25 | 13,406.75 | 18.103774% |
| cold hint 的单变量增量（gen24−gen20） | — | — | — | **17.169757 个百分点** |

gen20 的 `0.934017%` 小于该 arm 的 control spread（4.823612%），不能作为可靠
提升；gen24 为 18.103774%，高于 1.432719% 的 spread 可信线，且 ABBA/BAAB 分别
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
  单独打开；XS 只有显式 override 才改变策略。[^policy][^landing]
* `active_mask_gap_pack_policy=targeted-direct` 不再被借用。SimpleTES 的依赖审计
  证明 exact-event 路径不读取 gap-pack 状态；gap-pack 自己的增量只有
  `0.155120%` 且低于门槛，因此继续关闭。[^policy][^fourarm]
* 所有结构证明、功能测试、100/10k/50k gate、固定 ASLR、NUMA/CCD、PMU 和
  artifact identity 检查均要求通过；证明不成立时 fail-closed。[^ablation][^landing]

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
