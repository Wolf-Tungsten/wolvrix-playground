# TNO0350：对齐初解与历史初解不一致的求解器归因

日期：2026-10-28。承接 [TNO0347 方法对齐](./TNO0347_grhsim_fixed_memory_initial_method_alignment_20261028.md)、[TNO0349 walltime](./TNO0349_grhsim_aligned_initial_walltime_20261028.md)。

## 结论

静态模型和求解方法对齐没有保证初解标签可复现。当前使用的patched多约束Mt-KaHyPar的default preset属于非确定性并行求解；即使HGR、二进制、preset、seed、线程数全部固定，重新求解也会得到不同的社区、粗化图和最终ASC分组。32线程及384线程的重复控制均复现了这个现象。

本轮只重复初始solver和独立静态审计，不生成新的模型、不运行新的walltime，不修改已有分配或最佳恢复版。上一轮的+12.465% walltime不能仅归因于历史局部迁移。

## 已排除的输入差异

- 固定memory的ASC/piece/value模型与历史模型逐字节一致，SHA256为0c8b244a8f728d8267471964435e1b53b97830882ad5779c5b84d121c6fdf17f。
- 同一历史六维超图，自动隔离出的节点和权重相同。
- reduced HGR与历史resource_isolate_node5.hgr逐字节一致，SHA256为05f1bb458b7a3125cd66ecc30420b094ac8dfb31a200358e2a6a0d9757f4b1ca。
- 新初解在assignment replay前后标签相同；历史isolated_lane_v1标签也与历史31-way标签还原结果相同。
- 新旧初解经最大权重二分匹配消除分区编号差异后，仍有210,097/301,184个ASC改变分组，占69.757%。匹配实现与30组独立穷举排列核验一致。不能直接用逐行分区编号不同的比例表示真实结构差异。

## 重复求解控制

在node030连续、串行执行4次solver-only控制。进程可使用全部CPU0–383；只分别设置solver线程数为384和32。四次使用同一HGR、同一binary SHA256、同一config SHA256、k=31、epsilon=0.05、seed=0、objective=km1，各有独立输出目录。所有求解均达到约0.05的imbalance。

以下km1均在同一份移除隔离ASC后的31-way HGR上计算，越小表示该超图目标越好，不等价于walltime。

| 标签来源 | solver线程数 | reduced km1 |
|---|---:|---:|
| 历史保留初解，独立复算 | 未完整留档 | 26,174,480 |
| 上一轮新初解 | 384 | 30,680,594 |
| 本轮重复1 | 384 | 32,664,980 |
| 本轮重复2 | 384 | 29,768,381 |
| 本轮重复1 | 32 | 29,428,613 |
| 本轮重复2 | 32 | 30,388,382 |

同384线程两次重复的最优重编号后ASC分组差异为67.827%，同32线程两次为65.096%。因此将solver线程数固定成32，也不能恢复历史标签。四次控制不足以估计线程数对质量的平均影响，也不能据此判定哪种线程数更好。

同384线程的两个日志在忽略输出文件路径后，首个观测到的差异为预处理社区数：615对678；粗化后节点数为9409对9491。这说明差异早在初始双分和后续refinement之前就已形成。

## 代码机制

1. [command_line_options.cpp](../../build/repcut_grhsim_balance_20261013/redesign/mt-kahypar_multiconstraint_esa26/mt-kahypar/io/command_line_options.cpp)中deterministic默认false，p-stable-io默认false；default_preset.ini未启用它们。
2. [randomize.h](../../build/repcut_grhsim_balance_20261013/redesign/mt-kahypar_multiconstraint_esa26/mt-kahypar/utils/randomize.h)为每个worker生成seed+i的随机流，parallelShuffleVector在TBB并行任务中按THREAD_ID取流。当前构建thread pinning关闭，[macros.h](../../build/repcut_grhsim_balance_20261013/redesign/mt-kahypar_multiconstraint_esa26/mt-kahypar/macros.h)中的THREAD_ID来自TBB task arena slot。固定全局seed不固定任务由哪个worker执行，也不固定随机调用顺序。
3. [multilevel_coarsener.h](../../build/repcut_grhsim_balance_20261013/redesign/mt-kahypar_multiconstraint_esa26/mt-kahypar/partition/coarsening/multilevel/multilevel_coarsener.h)使用并行shuffle和明确deterministic=false的图收缩。preset还开启自适应初始分配、并行LP/FM及rebalancing；这些阶段不能保证重复得到同一解。
4. [context.cpp](../../build/repcut_grhsim_balance_20261013/redesign/mt-kahypar_multiconstraint_esa26/mt-kahypar/partition/context.cpp)显示，显式启用deterministic会启用稳定构图、关闭adaptive IP和非确定性FM、切换coarsening/LP/rebalancing算法。因此它是另一套算法路径，不能无验证地称为原恢复方法的等价开关。

## 新旧初解质量差异

| 独立静态指标 | 历史原始初解 | 上一轮新初解 | 变化 |
|---|---:|---:|---:|
| full HGR km1 | 28,274,932 | 32,781,046 | +15.937% |
| recurring work | 13,726,932 | 13,859,727 | +0.967% |
| piece copies | 698,661 | 708,340 | +1.385% |
| send calls | 6,018 | 7,760 | +28.946% |
| send bytes | 378,921 | 468,023 | +23.515% |
| 最大receive bytes | 36,438 | 69,782 | +91.509% |

历史reduced km1与历史full km1来自同一标签在不同图上的独立审计，不能混在同一目标列比较。新解不是对旧解的简单编号置换，切边和通信质量已有差距；这些静态变化支持剩余性能差距包含初解质量，不能直接换算成12.465%的walltime归因。

## 历史可复现性的边界与后续控制

历史multiconstraint_esa26/solver.log为空，isolated求解目录仅保存标签；周边patched_verbose.txt显示32线程，但它对应未隔离的32-way求解，不能把32线程直接认定为那次历史31-way求解的精确参数。历史同一路径的binary和config修改时间早于保留标签，但未留当时的binary哈希和完整命令，不能据此严格证明历史执行环境完全相同。

新驱动将solver线程数与编译jobs都取flow.jobs=384，这是本轮实际选择；使用所有核符合生成授权，却增加了需要单独冻结的求解变量。此前方法对齐的门禁缺失了“默认模式非确定性及重复求解稳定性”的核查，现明确修正。

若目标是单独评价自动迁移，应以历史原始初解标签作为已验证固定输入，使用同一preset/compiler构建，再由工具自动提出迁移；这属于固定初解的消融实验，不能称为重新从头求解。若目标是完整可复现的从头求解，则需另验证确定性多约束算法，冻结solver及config哈希、线程参数并做标签等价复验；不能通过只固定seed或线程数宣称实现。

## 产物

- [4次控制与两两分组比较](../../build/grhsim_fixed_memory_aligned_initial_20261028/solver_diagnosis/result.json)、[归因摘要](../../build/grhsim_fixed_memory_aligned_initial_20261028/solver_diagnosis/analysis_summary.json)。
- [重复求解驱动](../../build/grhsim_fixed_memory_aligned_initial_20261028/solver_diagnosis/run.py)、[独立审计驱动](../../build/grhsim_fixed_memory_aligned_initial_20261028/solver_diagnosis/audit.py)、[结构对比](../../build/grhsim_fixed_memory_aligned_initial_20261028/solver_diagnosis/structural_comparison.json)。
- [384线程重复1日志](../../build/grhsim_fixed_memory_aligned_initial_20261028/solver_diagnosis/t384_r1/solver.log)、[384线程重复2日志](../../build/grhsim_fixed_memory_aligned_initial_20261028/solver_diagnosis/t384_r2/solver.log)、[32线程重复1日志](../../build/grhsim_fixed_memory_aligned_initial_20261028/solver_diagnosis/t32_r1/solver.log)、[32线程重复2日志](../../build/grhsim_fixed_memory_aligned_initial_20261028/solver_diagnosis/t32_r2/solver.log)。
