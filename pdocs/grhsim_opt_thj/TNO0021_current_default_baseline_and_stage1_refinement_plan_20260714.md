# TNO0021 Current default baseline and Stage 1 refinement plan

记录日期：2026-07-14

状态：启动 activity-schedule 新阶段；先 fresh 固化当前默认 NO0300/fixed-ASLR 基线，再实现 plain-seeded exact post-DP refinement。本文只定义实验口径和停止条件，不预写实现或性能结论。

## 1. 唯一优化基线

本阶段的唯一候选对照是**当前仓库 HEAD 的默认 GrhSIM 生成配置**，即 NO0300 所代表的 ordered memory-write affine-loop 口径。它不是历史 NO0300 emu 的直接复用，也不是早期 plain artifact：

- 从当前 HEAD、当前 `wolvrix` 子模块 HEAD 和相同 SimTop 输入 fresh 执行生成、O3 编译与链接；
- 保持默认 plain activity-schedule、108-op compute cap、ordered writes 和 affine-loop codegen；
- direct state-read、full active-word consume、pure-event bypass/profile 等默认关闭的后续实验功能不得混入；
- 不设置本阶段新增的 refinement 开关时，生成结果必须与同轮 fresh default baseline 一致；
- schedule-only 候选可以复用本轮 fresh 产生的 pre-reg-to-mem checkpoint，但不能用旧实验目录中的 checkpoint 替代基线。

每轮基线必须归档主仓和子模块 SHA、filelist/top/read args、checkpoint SHA、完整生成环境变量、activity-schedule stats、generated source SHA 和最终 emu SHA。工作区现存 `build/xs/grhsim` 可能来自其他历史配置，只能用于定位文件格式，不能成为本阶段数值基线。

历史 NO0300 fresh 结构值作为重建锚点：

| Metric | NO0300 anchor |
| --- | ---: |
| graph ops | `7,204,108` |
| supernodes | `63,726` |
| compute supernodes | `63,241` |
| commit supernodes | `485` |
| DAG edges | `528,622` |
| boundary values | `1,000,463` |
| boundary activation edges | `1,983,923` |
| compute-compute value pairs | `1,721,698` |
| compute-commit value pairs | `262,225` |

若当前 HEAD fresh default 与这些锚点不同，先用提交、输入和默认配置变化解释差异并记录新的 current-default 数值；不得通过恢复旧开关把结构强行调回历史数字。NO0300 原始 fresh gate 见 [NO0300](../grhsim_opt/NO0300_ordered_memory_write_affine_loop_fresh_gate_20260712.md)，fixed-ASLR 校准见 [TNO0010](./TNO0010_code_layout_aslr_and_fixed_profile_20260713.md)。

## 2. Stage 1 目标与边界

现有优化主要减少单个 supernode 内的生成代码和动态工作；下一阶段改从 activity schedule 入手，减少 compute supernode 之间因 value 跨界产生的 activation 工作。Stage 1 只在当前 plain coarsen 和 DP 分区结果之上做 bounded refinement，不恢复历史 prob/CBAW/FM 全局路径，也不改变 reg-to-mem、commit 语义或 emitter activation contract。

refinement 接在 DP segments 形成之后、最终 flatten 之前，以 current-default plain partition 为初始解：

1. 建立 exact evaluator。对每个 value 按 distinct target segment 精算 compute BAE；对 compute/commit quotient pair 维护 refcount，精算 move 或 swap 后的 DAG edge 变化。
2. 单点 move 的 destination 只取 cluster incident value owners 与 DAG 邻居，稳定排序后最多检查 16 个；容量阻塞的正收益 move 可以生成 capacity-neutral swap。
3. 始终保持 segment 数、非空 segment、108-op cap、reg-to-mem intent 原子性和 quotient DAG 无环；oversize 与 intent clusters 首版不移动。
4. 依次试验 `strict`、`bae-budget` 和 `balanced` 策略。`strict` 要求 BAE/DAG 均不退；另两种允许单项小幅回退以换取另一项或最终 runtime，默认单项预算 `1%`。
5. 扫描 rounds `1/2/4`，默认总移动 ops 不超过全图 `1%`；记录候选数、接受的 move/swap、移动 ops、拒绝原因、exact before/after、耗时和最终 stats 对预测值的校验。

关闭 refinement 时，session、stats 和 generated source 必须与同轮 current-default baseline byte-identical。该 identity 是公共实现的第一门禁。

## 3. 结构门槛改为软门槛

BAE、DAG edges 和 compute-compute value pairs 是重要的 activity-work proxy，但不再是进入 SimTop 50k 的三项硬性 Pareto 条件。此前 prob/FM 相对 plain 出现接近翻倍的结构回退，足以直接判负；这不能外推成“任一指标增加就禁止 runtime”。

Stage 1 使用以下分级：

| 级别 | 条件 | 处置 |
| --- | --- | --- |
| 正向或轻微 mixed | 关键结构指标改善，或单项回退不超过 `1%` | fresh emit/build，并跑完整功能与 50k |
| 可解释 mixed | 单项回退 `1%..5%`，同时存在 BAE、DAG、生成代码或 evaluator 明确反向收益 | 原则上仍跑 50k；机器安静时优先形成正式 A/B/A |
| 诊断候选 | 结构回退最多 `5%`，但有明确 codegen/runtime 假设 | 机器安静且生成代价可接受时允许跑一次 50k，避免错过非单调收益 |
| 明显失败 | 关键结构或生成代码任一恶化超过 `10%`，且没有可解释的反向收益 | 不进入完整 50k，记录原因后停止该候选 |

这里的百分比只用于控制搜索规模，不构成正收益结论。即使 BAE 降低，若 generated C++、`.text`、host instructions 或 50k cycles 回退，候选仍可能判负；反之，结构轻微回退但 50k 稳定改善的候选可以保留。

## 4. 功能与 50k 裁决

每个非明显失败候选均从同一 fresh checkpoint 生成独立目录和 emu，依次通过：

- activity-schedule 单测、`transform-activity-schedule`、`emit-grhsim-cpp` 与完整 CTest；
- SimTop 100-cycle smoke；
- 10k difftest；
- CoreMark 50k difftest。

50k 正确终点固定为 guest/model cycle `50,001`、`cycleCnt=49,996`、`instrCnt=73,580`、PC `0x80001312`，且不得出现 mismatch、assert、fatal 或 `input_fullpass_blocked`。功能错误、cap/原子性/无环性破坏和 exact evaluator 与最终 stats 不闭合属于硬失败，不因潜在性能收益放宽。

最终性能口径始终是 SimTop CoreMark 50k。正式比较采用 current-default baseline / candidate / current-default baseline：

- 三轮均用 `setarch $(uname -m) -R` 关闭 ASLR，并固定 CPU、NUMA 和 SMT sibling；
- 每轮执行前要求双 sibling idle `>=99%`，PMU 事件 `100% scheduled`；
- 两次 baseline host cycles spread 必须 `<=1%`；
- candidate cycles 改善超过 `max(1%, baseline spread)` 才称为可信正收益。

机器不安静时仍可跑 50k 完成功能检查并记录粗略 host time，但不能把该 wall/cycles 写成性能结论。结构与 runtime 不一致时，继续比较 generated C++、object `.text`、emu host instructions 和本轮 fresh perf profile；schedule ID 变化后不得套用旧 profile 的 ID 映射。

## 5. Kill criteria 与阶段产物

满足任一条件即停止当前候选，不继续调参掩盖问题：

- activity schedule 产生环、违反容量/intent 不变量、功能门禁失败，或 exact 增量值无法由 final full recount 复现；
- schedule、emit 或 build 时间超过 current-default baseline `2x`，且没有已验证的显著 runtime 收益；
- 关键结构或生成代码恶化超过 `10%` 且没有相反指标或代码形态提供可信解释；
- bounded search 没有合法 move/swap，或在 `1%` moved-op 预算内的 exact compute-BAE headroom 小于 `0.1%`；
- quiet fixed-ASLR A/B/A 中 candidate cycles 稳定回退超过 `max(1%, baseline spread)`。

负向 refinement 策略在阶段提交前回退；可复用的 exact evaluator、统计和测试只有在默认关闭且 identity gate 通过时才保留。正向策略仍先保持 core 默认关闭，经 fresh current-default/candidate 对照确认后再决定是否纳入 XiangShan 默认生成配置，并保留显式 `off` 回滚入口。

后续为实现 gate、fresh 结构结果、50k/perf 结果分别新增 TNO 文档，不把执行数据回填到本文。阶段完成时按任务整体提交：若修改 `wolvrix`，先提交子模块，再在父仓提交子模块指针和本阶段文档。
