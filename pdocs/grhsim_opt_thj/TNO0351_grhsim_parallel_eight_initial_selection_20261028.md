# TNO0351：八份并行初解与按 km1 自动择优

日期：2026-10-28。承接 [TNO0350求解器非确定性核查](./TNO0350_grhsim_initial_solver_reproducibility_20261028.md)。

## 规则及资源

使用固定历史memory、与历史完全相同的六维source/value HGR以及自动隔离后的31-way HGR。冻结同一个patched多约束Mt-KaHyPar binary和default preset，k=31、epsilon=0.05。启动8份独立求解，seed=0–7，每份48线程，总线程预算384。

CPU集合从node030全部在线CPU0–383及实际SMT sibling拓扑自动分组，8份互不重叠，每组48个逻辑CPU，同一物理核的SMT siblings留在同一组。既不指定ASC编号，也不指定迁移来源/目的分区。允许全核的上游约定继续有效；本轮没有运行性能仿真。

## 自动审计及选择

每份结果恢复为完整32-way标签，检查ASC数量、标签范围和全部非空分区。用独立C++审计器重新计算reduced/full HGR的km1，并核对reduced值与solver报告相同；对剩余31路逐维检查六维容量不超过epsilon=0.05预算。隔离ASC保留单独分区，不错误套用32路平均容量来拒绝不可拆超大节点。

选择规则在运行前固定：在容量合格的8份fresh结果中，取完整HGR的km1最小者；仅在完全同分时按seed排序。输入图、solver、config及audit probe均保留哈希并在运行后再次检查，独立求解与审计日志全部保存。

## 结果

8/8求解及容量审计通过。以下km1是两种明确区分的图口径；排序使用full HGR列。

| seed | reduced 31-way km1 | full 32-way km1 | 单份solver经过时间(s) |
|---|---:|---:|---:|
| 0 | 29,992,327 | 32,092,779 | 35.11 |
| 1 | 25,811,689 | 27,912,141 | 28.40 |
| 2 | 29,813,882 | 31,914,334 | 25.10 |
| 3 | 28,680,227 | 30,780,679 | 25.77 |
| 4 | 28,619,685 | 30,720,137 | 27.51 |
| 5 | 25,814,250 | 27,914,702 | 35.92 |
| 6 | 28,326,318 | 30,426,770 | 26.43 |
| 7 | 27,286,666 | 29,387,118 | 35.62 |

选中 **seed 1**：full km1=**27,912,141**，reduced km1=25,811,689。并行求解、独立审计及结束身份核查阶段耗时57.41s，不含开始前输入哈希检查；单份solver时间25.10–35.92s。不是8份时间相加。

| 对比标签 | full HGR km1 | 本轮选中解相对变化 |
|---|---:|---:|
| 上一轮单份fresh新初解 | 32,781,046 | -14.853% |
| 历史原始初解 | 28,274,932 | -1.283% |
| 恢复版最终分配 | 27,752,000 | +0.577% |

本轮8份中最好的新初解已经优于历史原始初解的km1，但尚未低于恢复版最终分配。这里的最优只表示8份容量合格结果中的最小km1，不代表全局最优划分或最快walltime。

## 选中解的精确账本

使用与历史模型逐字节相同的assignment model，独立oracle完成32分区记账：

| 指标 | 历史原始初解 | 本轮seed 1 |
|---|---:|---:|
| closure work | 14,088,752 | 13,855,685 |
| recurring work | 13,726,932 | 13,501,623 |
| piece copies | 698,661 | 691,676 |
| send calls | 6,018 | 6,527 |
| send bytes | 378,921 | 354,246 |

总work、复制和通信字节下降，但调用数增加。未按这些事后指标改选seed，也未声称walltime已经改善；下游如要评价性能，需要只生成/编译选中解并与同编译恢复版做fresh AB/BA。

## 工具与产物

- [通用并行择优工具](../../scripts/repcut_grhsim_solver_portfolio.py)、[单元测试](../../scripts/test_repcut_grhsim_solver_portfolio.py)。CPU集合、SMT保持、容量边界、不合格解排除及审计解析有测试；连同已有isolated/auto-flow测试共16项通过，Python编译与diff空白检查通过。
- [复现入口](../../build/grhsim_fixed_memory_aligned_initial_20261028/portfolio8/run.sh)、[运行前规则和输入哈希](../../build/grhsim_fixed_memory_aligned_initial_20261028/portfolio8/policy.json)。
- [8份结果及自动选择](../../build/grhsim_fixed_memory_aligned_initial_20261028/portfolio8/selection.json)、[选中标签](../../build/grhsim_fixed_memory_aligned_initial_20261028/portfolio8/best_assignment.part32)、[完整图独立审计](../../build/grhsim_fixed_memory_aligned_initial_20261028/portfolio8/seed01/full.audit.txt)。
- [选中解精确账本](../../build/grhsim_fixed_memory_aligned_initial_20261028/portfolio8/inventory_summary.json)、[逐分区账本](../../build/grhsim_fixed_memory_aligned_initial_20261028/portfolio8/selected_inventory.parts.csv)。

通过记录可以复用已选中的标签；另起一批fresh并行求解仍可能选出不同结果，应使用新输出目录并保存新的选择记录。最佳恢复版、默认分配入口和Verilator路径均未改。
