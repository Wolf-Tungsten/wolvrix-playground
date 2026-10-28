# TNO0347：固定 memory 的初始分配方法与恢复版对齐

日期：2026-10-28。承接 [TNO0346](./TNO0346_grhsim_fixed_memory_acceptance_20261028.md)。

## 控制变量与方法

复用上一轮 fresh Verilog 生成、按历史三个 memory 执行 mem-to-reg 的输入。该阶段不重做筛选、不修改 memory 名单；mem-to-reg JSON SHA256 为 `493a8fe12f1639bebaa8069e7d7495c3023297f108b8917778432705a6fcb24b`。

此前固定 memory 初解使用普通 32-way scalar closure-aware solver、epsilon=0.015。恢复线的原始初解实际是六维 source/value 超图，先隔离不可拆超大 ASC，再用研究副本的多约束 Mt-KaHyPar 对其余节点做 31-way 求解，epsilon=0.05、seed=0、km1。不是只改变分区数量。历史依据见 [TNO0337 §28.25–28.26](./TNO0337_grhsim_partition_system_redesign_20261013.md)。

当前固定 memory 的 `source_model.txtdata` 与历史 `audit/model.txtdata` 均为 1,550,144,817 字节，SHA256 完全相同：`0c8b244a8f728d8267471964435e1b53b97830882ad5779c5b84d121c6fdf17f`。因此本轮显式复用历史静态六维权重和超图，重新求解标签；这是为了对齐历史方法，未声称重新提取的简化 context 与历史精细来源 context 相同。

六维分别为 unguarded rising/falling、guarded rising/falling、control risk、scalar inventory；原超图 301,184 个 ASC、584,259 条边。隔离工具按最大归一化容量违反量选择节点，不接受 ASC 编号或迁移来源/目标参数。解完后恢复完整 32-way 标签顺序，逐行校验 replay 未修改标签。重新求解可使用全部 CPU，因此不要求新标签与历史标签相同。

## 构建与验证

- 26 项完整 emit preset、冻结 library、Clang23/O3/native/no-SLP、各自 Makefile archive 顺序、64B compute 入口对齐均沿用上一轮。
- 生成/分析/编译使用全部在线 CPU0–383；运行仍为 node030 CPU96–127、N=K=32、C=100000、all-spin、preferred NUMA1、ASLR off、代码 THP。
- 分别与上一轮普通固定 memory 初解、相同 no-SLP 编译设置的恢复版各做 8 对 fresh AB/BA。后者含历史已接受的局部迁移，因此这组比较仍包含历史迁移累计收益，不代表原始初解标签相同。
- 本轮先单独测初解方法，不手工迁移，也不把旧迁移序列复制到新解。

隔离、图重编号、标签还原、缺失分区拒绝、越界 pin 检查共 5 项单元测试通过。

## 产物

- [通用隔离工具](../../scripts/repcut_grhsim_isolated_initial.py)与[测试](../../scripts/test_repcut_grhsim_isolated_initial.py)。
- [可复现驱动](../../build/grhsim_fixed_memory_aligned_initial_20261028/run.py)、[实验配置](../../build/grhsim_fixed_memory_aligned_initial_20261028/experiment.json)、[方法与身份核验](../../build/grhsim_fixed_memory_aligned_initial_20261028/method.json)。

本记录为方法与启动记录；性能结论在完整运行后另建记录，不以中途输出推断收益。

## 初解结构检查补充

自动选中 atom 5，六维权重为 50,900 / 50,900 / 166,904 / 165,719 / 196,596 / 217,808；剩余图有 301,183 节点、575,747 条边。新工具产生的 reduced HGR 与历史 resource_isolate_node5.hgr 逐字节一致，SHA256 为 05f1bb458b7a3125cd66ecc30420b094ac8dfb31a200358e2a6a0d9757f4b1ca。384 线程 fresh solver 29.09s 完成，最终 imbalance=0.0499989、km1=30,680,594；返回全部 32 个非空分区，已进入原始图 assignment replay。

## 增量核查：初解标签的可复现性（2026-10-28）

详见 [TNO0350](./TNO0350_grhsim_initial_solver_reproducibility_20261028.md)：当前default多约束solver为非确定性并行路径，同线程数和seed的重复求解也产生不同社区、粗化图和标签。因此本记录的方法对齐不代表恢复历史初解；与恢复版的差距仍包含初解质量及历史迁移，不能全部归给迁移。
