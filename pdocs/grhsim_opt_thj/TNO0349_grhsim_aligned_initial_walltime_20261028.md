# TNO0349：固定 memory、对齐恢复版初始分配后的 walltime

日期：2026-10-28。方法与可复现入口见 [TNO0347](./TNO0347_grhsim_fixed_memory_initial_method_alignment_20261028.md)，构建及静态账本见 [TNO0348](./TNO0348_grhsim_aligned_initial_build_gate_20261028.md)。

## 实际对齐内容

固定上一轮历史三个memory的mem-to-reg输入，ASC/piece/value模型与恢复线历史模型逐字节相同。复用同一份历史六维source/value超图，按归一化容量规则自动隔离超大ASC，再由相同patched研究求解器重新31-way求解、epsilon=0.05、seed=0、km1。自动识别的ASC和reduced HGR与历史记录完全一致，但384线程fresh求解产生新标签；未读取旧assignment，也未复制历史接受的局部迁移。

完整26项preset、冻结library、Clang23/O3/native/no-SLP保持不变。7857对象编译通过，7249个compute入口全部64B对齐，各自保留生成Makefile归档次序。32分区execution-plan全部对账通过，耗时1579.22s，10张CSV检查完整。

## Fresh AB/BA结果

生成/分析/编译允许全部CPU0–383。正式运行固定node030 CPU96–127、N=K=32、C=100000、all-spin、preferred NUMA1、ASLR off、完整代码THP。每行是一组独立8对AB/BA；百分比逐对计算后取中位数，不能跨窗口直接相减。

| 对照→候选 | 对照walltime中位数(s) | 候选walltime中位数(s) | 配对变化 | 候选更快 |
|---|---:|---:|---:|---:|
| 上一轮普通32-way初解→本轮对齐初解 | 12.550 | 12.130 | -3.595% | 8/8 |
| 同no-SLP编译的恢复版→本轮对齐初解 | 10.695 | 12.020 | +12.465% | 0/8 |

| 阶段指标 | 相对上一轮普通初解 | 相对同编译恢复版 |
|---|---:|---:|
| Host | -3.675% | +12.454% |
| global eval | -5.053% | +12.310% |
| global update | -3.273% | +16.123% |
| max-part eval | +4.029% | +27.304% |
| sum-part eval | +15.080% | +4.744% |

共32次普通C100000正式运行及4次C100 smoke，全部功能检查、THP覆盖、compute对齐和输入身份通过。没有剔除成功样本。

## 结论及归因边界

对齐初始方法后，新线相对上一轮普通初解有3.595%的配对walltime改善，但尚未追平同编译恢复版，仍慢12.465%。因此上一轮差距中确实存在初始方法不一致，单独修正它不足以恢复历史最佳性能。

本轮只改变初解方法，没有执行后续自动迁移。当前新初解可以作为后续自动迁移的受控起点，历史恢复版仍为性能锚点。剩余差距包含fresh求解标签、历史多轮迁移以及由分配诱发的后端形态/布局差异；未做直接中间版本对照，不能把12.465%全部归因于人为迁移，亦不能把当前新标签称为恢复版同一assignment。

本轮显式复用了历史精细来源权重，不声称已实现从fresh RTL重新提取完全相同六维权重的一键流程。其复用前提由完整ASC模型哈希一致和reduced HGR逐字节一致核验支持。

最佳恢复版与默认路径未改。

## 数据与复现

- [综合结果](../../build/grhsim_fixed_memory_aligned_initial_20261028/result.json)与[复现驱动](../../build/grhsim_fixed_memory_aligned_initial_20261028/run.py)。
- [对上一轮初解的8对数据](../../build/grhsim_fixed_memory_aligned_initial_20261028/ab_ba_previous_initial/summary.json)、[manifest](../../build/grhsim_fixed_memory_aligned_initial_20261028/ab_ba_previous_initial/manifest.json)。
- [对同编译恢复版的8对数据](../../build/grhsim_fixed_memory_aligned_initial_20261028/ab_ba_restored_same_compiler/summary.json)、[manifest](../../build/grhsim_fixed_memory_aligned_initial_20261028/ab_ba_restored_same_compiler/manifest.json)。
- [完整执行计划](../../build/grhsim_fixed_memory_aligned_initial_20261028/initial/plan/identity.json)、[构建身份](../../build/grhsim_fixed_memory_aligned_initial_20261028/initial/build.json)。

复现：在node030执行 python3 build/grhsim_fixed_memory_aligned_initial_20261028/run.py。通过的步骤及fresh比较都有身份记录，重复执行不重跑已完成测量；若要新测，应使用新的比较输出目录，保持双方新鲜交错运行。

## 增量核查：初解标签的可复现性（2026-10-28）

详见 [TNO0350](./TNO0350_grhsim_initial_solver_reproducibility_20261028.md)：当前default多约束solver为非确定性并行路径，同线程数和seed的重复求解也产生不同社区、粗化图和标签。因此本记录的方法对齐不代表恢复历史初解；与恢复版的差距仍包含初解质量及历史迁移，不能全部归给迁移。
