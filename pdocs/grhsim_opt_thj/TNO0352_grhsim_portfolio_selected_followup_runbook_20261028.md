# TNO0352：八份择优初解的生成、自动迁移及对照流程

日期：2026-10-28。承接 [TNO0351](./TNO0351_grhsim_parallel_eight_initial_selection_20261028.md) 自动选择的seed 1。本记录固定后续执行方案，结果按阶段另记。

## 固定输入

- 初解读取portfolio8/selection.json选中的标签，验证文件SHA256为f71f136171ad4759fca32435b9c57bdcf6d3fa3ae9302ff29229161bd62cc83a。它由8份并行求解按最小合格full km1=27,912,141自动选出，不重新求解、不人工改标签。
- 沿用固定历史三个memory的mem-to-reg输入，SHA256为493a8fe12f1639bebaa8069e7d7495c3023297f108b8917778432705a6fcb24b。
- 使用同一冻结library和26项完整历史preset，Clang23/O3/native/no-SLP，各自Makefile归档顺序及compute入口64B对齐；不复用缺失选项的早期组合线。
- source context复用相同raw图的已验证产物，核对input、library、options与本轮一致。

## 执行顺序

1. assignment replay重建完整32分区图，校验导出标签逐行不变。
2. 图完成后并行进行完整C++发射和执行计划分析。计划通过--partitioned显式使用新图，成功的旧emit记录仅提供固定library/options；不伪造新的成功emit记录。发射结束后编译、64B对齐、归档和harness链接。
3. 生成、分析、编译全部完成后，与相同no-SLP设置的恢复版做8对fresh AB/BA，C100 smoke及C100000正式运行均检查功能、THP和对齐。
4. 对本轮初解采集4次C100000逐步trace，由工具按动态关键路径自动选3个来源分区、每源8个piece、每piece3个目的地，最多72个提案。精确评估复制/通信账本，保持已有通信预算和Pareto/improvement规则，最多完整验证一个自动选中候选。没有通过者就保留初解，不手工挑迁移。
5. 自动迁移候选相对本轮初解须通过两轮各8对AB/BA，分别walltime配对中位数下降且至少6/8胜，才保留。
6. 最终版本与同编译恢复版做fresh比较；另与历史原始恢复版二进制做独立8对比较，区分兼容编译开销与分配差距。若没有迁移，初解的同编译对照就是最终版本对照。

生成/分析/编译使用node030全部CPU0–383，384 compile jobs。正式普通运行固定node030 CPU96–127、N=K=32、C=100000、all-spin、preferred NUMA1、ASLR off、代码THP。任何后台生成/诊断任务都须在普通测量前完成。

## 判断边界

km1择优只用于选初解，不能直接视为walltime收益。恢复版保留其历史累计迁移，本轮后续只由工具自动提案和选择。raw图和历史精细六维权重复用的来源边界仍遵循TNO0351，不声称本次重新从RTL提取了六维权重。

## 产物

- [独立可复现驱动](../../build/grhsim_portfolio8_followup_20261028/run.py)、[源身份及选择](../../build/grhsim_portfolio8_followup_20261028/source.json)、[生成/运行规则](../../build/grhsim_portfolio8_followup_20261028/automatic_policy.json)。
- [上游择优结果](../../build/grhsim_fixed_memory_aligned_initial_20261028/portfolio8/selection.json)。

在node030执行 python3 build/grhsim_portfolio8_followup_20261028/run.py。步骤完成后保存身份记录，驱动支持复用已经通过的产物。
