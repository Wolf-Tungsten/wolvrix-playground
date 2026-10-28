# TNO0343：固定恢复版 mem-to-reg 的自动分配与迁移对照

日期：2026-10-28。上一轮完整自动路线见 [TNO0342](./TNO0342_grhsim_automatic_flow_acceptance_20261027.md)。

用户要求控制 mem-to-reg 与恢复版一致，后续迁移来源和目的地继续由工具选择。

## 固定与变化

恢复版的原始转换记录来自 `build/asc_separator_combined_20260921/targeted/run.json`，三个 memory 为：

```text
cpu$l_soc$core_with_l2$l2top$inner_buffers_2$nodeIn_d_q$ram_ext$Memory
cpu$l_soc$socMisc$buffers_1$nodeIn_d_q$ram_ext$Memory
cpu$l_soc$socMisc$buffers_1$nodeOut_a_q$ram_ext$Memory
```

本轮 `row_limit=2、strict_init=false`，与原转换脚本一致。相较上一轮自动 memory，只有第一个由 PTW 队列换回 L2 buffers_2 D 队列。历史名单作为用户要求的显式控制输入，不记作本轮工具自动发现。

复用上一轮从 Verilog 新 ingest 的 pre-mem-to-reg 图，逐一重新校验 2100 个 RTL 文件、header、文件列表、read args 和 raw JSON 的 SHA256；避免重新 ingest 引入顺序/输入变化。没有复用历史 assignment；从头 K=32、384 solver 线程，后处理、冻结库、完整 26 项 emitter preset 与上一轮自动线一致。迁移来源、piece 和目的地仍由新 profile 与结构预算自动决定，最多完整验证一个候选，接受门槛保持两轮各 8 对负 walltime 中位且至少 6/8 更快。

入口新增 `--memory-reference-run` 和 `--ingest-record`；默认仍是结构自动 memory 模式。historical 参数只控制 memory 阶段，不提供分区编号接口。工具记录区分历史固定名单与自动迁移。

## 性能对照设计

1. 上轮自动 memory 初解 vs 本轮固定 memory 新初解：同一 raw、冻结库、solver 参数、preset、Clang23/O3/native/no-SLP，比较 memory 策略及其诱发的新全局划分。
2. 本轮新初解 vs 自动迁移：两者完整生成并按相同配置构建，fresh AB/BA。
3. 恢复版原 binary vs 从其相同生成源码全量 no-SLP 重编的副本：量化编译兼容保护的合计影响。
4. no-SLP 恢复版 vs 本轮保留版本：消除 SLP 参数不一致后比较实际剩余差距。

生成/分析/编译允许 CPU0–383，正式测试仍在 node03096–127，32 线程、C100000、preferred NUMA1、all-spin、ASLR off、完整代码 THP、compute 入口64B对齐。构建、分析结束后才允许计时，不与其它本轮生成任务并发。

本轮目录为 `build/grhsim_fixed_restored_memory_20261028`。[run.sh](../../build/grhsim_fixed_restored_memory_20261028/run.sh) 和 [command.json](../../build/grhsim_fixed_restored_memory_20261028/command.json) 保存实际入口；[experiment.json](../../build/grhsim_fixed_restored_memory_20261028/experiment.json) 保存对照来源。结果另立验收记录，不提前推断性能。
