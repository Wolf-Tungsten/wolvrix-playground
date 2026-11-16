# CV32E40P GrhSIM 单线程调查

| 记录 | 内容 |
| --- | --- |
| [TNO0001](./TNO0001_reproduction_and_compute_cost_20261114.md) | CoreMark 复现、前端兼容性边界、8 对测量与 compute 热点定位 |
| [TNO0002](./TNO0002_indexed_register_bank_reads_20261114.md) | Wolvrix 按需拼装寄存器堆读取、语义回归与 11.92% walltime 降幅 |
| [TNO0003](./TNO0003_packed_scalar_slices_and_xiangshan_20261114.md) | 合并 scalar bit-slice 存储、当前 Verilator 差距及 XiangShan 形态调查 |
| [TNO0004](./TNO0004_generated_code_shape_gap_20261114.md) | 三后端生成代码对照、动态调度/变化计数、Host 指令差距及调度前 word 合并机会 |
| [TNO0005](./TNO0005_concat_slice_coalescing_20261114.md) | 调度前 concat-slice 合并、完整功能门、35.61% walltime 降幅及剩余 Verilator 差距 |
| [TNO0006](./TNO0006_remaining_decode_and_scheduling_gap_20261114.md) | 新版与 Verilator one-hot 译码对照、逐值执行计数及集合归约机会 |
| [TNO0007](./TNO0007_shared_equality_decode_20261115.md) | 共享等值译码与精确通知、7.76% walltime 降幅及 1.40/2.99 倍剩余差距 |
| [TNO0008](./TNO0008_shared_decode_dynamic_counts_20261115.md) | 两组 CSR 比较从 180.71 降至 1.96 次/周期，缓存分派计数与 Verilator 剩余结构差异 |
| [TNO0009](./TNO0009_post_decode_code_shape_gap_20261115.md) | CSR 2048→32 读取、1024→16 写入、长 OR 消费者与细粒度通知的剩余开销 |
| [TNO0010](./TNO0010_indexed_constant_padding_20261115.md) | 宽常量按需读取功能通过，但 walltime 增加 0.735%，保留为默认关闭的实验扩展 |
| [TNO0011](./TNO0011_binary_shape_comparison_20261115.md) | 三份冻结 binary 的反汇编、profile 热点映射及 RTL 归一化影响 |
| [TNO0012](./TNO0012_shared_deferred_activation_20261115.md) | 合并同 supernode 重复 deferred-activation 归约；8 对测量 walltime 改善 0.79%，保留默认关闭 |
| [TNO0013](./TNO0013_execution_structure_20261115.md) | 执行区域、跨组值缓存与 ALU word 路径审计；63.25% scalar 比较位于同一 commit 终点的组合区域 |
| [TNO0014](./TNO0014_event_regions_and_use_order_20261115.md) | 同事件尾部区域与首次使用顺序：walltime降低18.65%，相对归一化Verilator缩至1.143倍 |
| [TNO0015](./TNO0015_optimization_review_and_region_composition_20261115.md) | 优化复审与边界回归；发现区域局部化与译码缓存不组合，局部one-hot实验回退2.39%，定位共享/多终点区域及消费网络问题 |
| [TNO0016](./TNO0016_shared_regions_measurement_20261115.md) | 共享区域使checked value从413降到209，但walltime +0.55%、CI跨零；逐值计数定位稀疏缓存失效与区域内额外计算，保持默认关闭 |
| [TNO0017](./TNO0017_predicate_consumer_fusion_20261115.md) | 同源译码消费者区间化简功能通过，但walltime +1.58%；动态指令仅降0.44%，新调度打断缓存并增加变化检测，不纳入默认 |
| [TNO0018](./TNO0018_slice_demand_measurement_20261115.md) | 宽逻辑移位按窄窗口计算，4个wide shift和2个wide mux消失；walltime −0.09%、CI跨零，动态指令仅降0.18%，保持实验关闭 |
| [TNO0019](./TNO0019_conditional_mux_cones_20261115.md) | 私有mux分支条件求值；修正lambda拆函数的22.91%回退，最终wall −4.40%、指令 −4.73%，相对同RTL Verilator缩至1.0932倍 |
| [TNO0020](./TNO0020_unsuccessful_attempts_review_20261115.md) | 负结果复审：局部表丢失0/1类型信息、缓存与调度不组合、共享区域无防退化排序，以及窄窗口缺少已知对齐化简；仅离线证据，无新跑分 |
| [TNO0021](./TNO0021_negative_attempt_repairs_20261115.md) | 三项修复独立对测：bool表与字段窗口减少指令但无稳定整机收益；IR活跃距离成本门反而慢6.28%，已撤回；保留版本和默认值不变 |
| [TNO0022](./TNO0022_sparse_cache_region_composition_20261115.md) | 按SSA源恢复共享区域内18个opcode谓词的稀疏缓存；修复本身wall −2.73%，组合相对此前保留版 −4.45%，与同RTL Verilator缩至1.04488倍；默认关闭 |
| [TNO0023](./TNO0023_conditional_input_cache_20261115.md) | 条件锥精确输入缓存；IRQ优先级重复计算减少约31个IR运算/周期，wall −0.385%，同RTL Verilator差距约4.08%；默认关闭 |
| [TNO0024](./TNO0024_producer_change_cache_20261115.md) | 多输入条件锥变化通知缓存：功能正确，37.74次新增通知只省14.61个IR运算/周期；wall +2.32%，保持关闭 |
| [TNO0025](./TNO0025_grouped_cache_notifications_20261115.md) | 出口聚合把dirty赋值降至5.74次/周期，但仍有34次局部OR；相对逐源wall −0.66%、相对保留基线 +1.36%，定位现有33来源归约与20/14缓存集合的重复 |
| [TNO0026](./TNO0026_xiangshan_unpartitioned_mux_opportunity_20261115.md) | XiangShan 未分图全图的单侧锥：唯一覆盖37.65%，0.5假设下嵌套封闭锥少执行25.20%的纯组合op，全图需求模型为28.27%；仅静态潜力，非实测加速 |
| [TNO0027](./TNO0027_joint_notification_factoring_20261115.md) | 纯静态精确集合联合分解：OR贡献222.65→196.37次/周期，少65条退休指令；相对聚合wall −0.55%、相对既有基线 +0.87%，无运行反馈选优 |
| [TNO0028](./TNO0028_current_cpp_elf_structure_20261115.md) | 当前 C++／ELF 联合审计：95.2%变化检查仅服务跨 compute 边界；等价宽 CSR view 重复物化且准备留在 guard 前，核对冷路径与 Verilator 清零反例；无新跑分 |
| [TNO0029](./TNO0029_wide_demand_and_local_predicate_consumers_20261115.md) | 两项独立修复：宽值准备进入条件分支，wall −0.34%；局部译码消费者保持调度／缓存边界，wall −0.25%但CI跨零；512项计数一致，无运行反馈选优 |
| [TNO0030](./TNO0030_covered_state_view_boundaries_20261115.md) | 静态证明已有寄存器激活覆盖：21个跨区域视图先去判变通知、再去槽位，wall分别−1.34%和−3.11%；467项行为计数不变，与同RTL Verilator缩至1.00977倍 |
| [TNO0031](./TNO0031_remaining_structure_after_state_views_20261115.md) | 直接读取后的离线审计：复合状态视图仍留边界，71个非缓存依赖根需补证明；大batch约两次空入口/周期仍付栈帧成本，提交接口暂存／通知保持 |
| [TNO0032](./TNO0032_composed_state_expressions_and_entry_guard_20261115.md) | 复合状态表达式新增70个通知覆盖、52个有限内联，wall−3.52%，比同RTL Verilator低2.37%；独立空入口少6.25次调用/周期，但wall−0.15%的CI跨零 |

入口：[runner](../../scripts/cv32e40p_compare.py)、[testbench 与使用说明](../../testcase/cv32e40p-bench/README.md)。
初始复现：[report.json](../../build/cv32e40p/run2/report.json)。
默认emitter参考：[shared-equality report](../../build/cv32e40p/shared-equality-validated/report.json)，复现入口：[equality compare](../../scripts/cv32e40p_equality_compare.py)。
共享通知实验：[shared deferred report](../../build/cv32e40p/shared-deferred-activation-v1/report.json)，复现入口：[deferred activation compare](../../scripts/cv32e40p_deferred_activation_compare.py)。
事件区域实验：[event regions report](../../build/cv32e40p/event-regions-v3/report.json)，复现入口：[event regions compare](../../scripts/cv32e40p_event_regions_compare.py)。全局默认尚未开启。
局部译码复用实验：[local decode report](../../build/cv32e40p/local-decode-v2/report.json)，复现入口：[local decode compare](../../scripts/cv32e40p_local_decode_compare.py)。功能通过但性能回退，保持默认关闭；该轮保留了事件区域版。
共享区域实验：[shared regions report](../../build/cv32e40p/shared-regions-v3/report.json)，[动态工作增减](../../build/cv32e40p/shared-regions-v3/work-decomposition.json)，复现入口：[shared regions compare](../../scripts/cv32e40p_shared_regions_compare.py)。功能通过但没有稳定收益，保持默认关闭；该轮保留版为归一化Verilator的1.1395倍。
译码消费者融合实验：[predicate report](../../build/cv32e40p/predicate-set-v1/report.json)，[动态归因](../../build/cv32e40p/predicate-set-v1/attribution.json)，复现入口：[predicate compare](../../scripts/cv32e40p_predicate_compare.py)。8/8轮更慢，不纳入默认；同轮保留版为归一化Verilator的1.14086倍。
按需位段实验：[slice-demand report](../../build/cv32e40p/slice-demand-v1/report.json)，[动态归因](../../build/cv32e40p/slice-demand-v1/attribution.json)，复现入口：[slice-demand compare](../../scripts/cv32e40p_slice_demand_compare.py)。功能通过但没有稳定收益，不纳入默认。

TNO0019保留了事件区域与条件求值组合：[conditional-mux report](../../build/cv32e40p/conditional-mux-v4/report.json)、[动态归因](../../build/cv32e40p/conditional-mux-v4/attribution.json)，复现入口：[conditional-mux compare](../../scripts/cv32e40p_conditional_mux_compare.py)。8/8轮更快，walltime再降4.40%；它是后续缓存修复的固定基线。

负结果修复对照：[汇总与验证](../../build/cv32e40p/repair-review-v1/report.json)，复现入口：[repair compare](../../scripts/cv32e40p_repair_compare.py)。三个修复分别与同源旧实现、当前保留版及Verilator测量，未扩大阈值或组合搜索；排序成本门已撤回，布尔表与字段证明仅保留为默认关闭的实验实现。

TNO0022的保留实验为共享区域、条件求值与语义家族稀疏缓存组合：[equality families report](../../build/cv32e40p/equality-families-v1/report.json)、[逐值归因](../../build/cv32e40p/equality-families-v1/family-attribution.json)，复现入口：[family compare](../../scripts/cv32e40p_equality_family_compare.py)。本轮8/8轮更快，修复本身wall −2.73%，整体相对TNO0019版 −4.45%；新规则和区域扩展仍默认关闭。

当前对照基线见TNO0023的精确键缓存：[报告](../../build/cv32e40p/mux-input-cache-v1/report.json)。TNO0024新增的生产者变化通知缓存[报告](../../build/cv32e40p/change-trigger-cache-v1/report.json)显示walltime回退2.32%，8/8轮更慢，因此保持默认关闭，继续使用既有基线；本轮基线/归一化Verilator为1.04445倍。

TNO0025完成生产者出口聚合：[报告](../../build/cv32e40p/grouped-notify-cache-v1/report.json)、[516项计数一致性与通知成本](../../build/cv32e40p/grouped-notify-cache-v1/notify-attribution.json)。聚合仍慢于TNO0023基线，继续关闭；本轮基线/归一化Verilator为1.04287倍。后续方向是联合分解调度与缓存的精确来源集合。

TNO0027按固定图结构联合分解调度与缓存集合：[报告](../../build/cv32e40p/joint-notify-cache-v1/report.json)、[520项行为一致性与OR成本](../../build/cv32e40p/joint-notify-cache-v1/joint-attribution.json)。一组8轮测量后仅归档评价，未反馈调整生成规则或默认配置；同轮既有基线/归一化Verilator为1.04238倍。

TNO0028结合上述冻结 ELF、生成 C++ 和既有精确计数分析剩余结构差距：[总报告](../../build/cv32e40p/current-structure-v1/report.json)、[CFG／内嵌源码 checksum／具体接口证据](../../build/cv32e40p/current-structure-v1/path-evidence.json)。进一步区分区域接口协议、按需宽值构造和已被编译器下沉的冷代码；没有新的模拟执行、性能采样或生产改动。

TNO0029独立验证后两类问题的修复：[配对报告](../../build/cv32e40p/consumer-structure-v2/report.json)、[PMU／ELF／计数归因](../../build/cv32e40p/consumer-structure-v2/consumer-analysis.json)、[规则说明](../../wolvrix/docs/emit/grhsim-consumer-structure.md)。宽值规则支持小幅收益，译码消费者的外部walltime收益尚不明确；两项均保持实验默认关闭，跨区域接口问题暂留。

TNO0030落实跨区域简单状态视图的两阶段静态证明：[配对报告](../../build/cv32e40p/covered-state-views-v1/report.json)、[计数／PMU／ELF归因](../../build/cv32e40p/covered-state-views-v1/boundary-analysis.json)、[规则说明](../../wolvrix/docs/emit/grhsim-covered-state-views.md)。比较从167.26降至147.38次/周期，直接读取版walltime降低3.11%，与同RTL Verilator差约0.98%；两项开关仍默认关闭，没有以运行结果调整站点、规则或组合。

TNO0031对这一冻结版本继续做源码／ELF／既有计数审计：[离线报告](../../build/cv32e40p/post-view-structure-v2/report.json)。建议优先使状态视图证明可组合，其次把纯compute批次的空入口移到大函数之前；compute→commit快照接口另行设计。没有模拟执行、profile采样、优化候选生成或生产修改。

TNO0032完成两条独立验证：[复合表达式配对报告](../../build/cv32e40p/state-expressions-v1/report.json)、[源码／ELF](../../build/cv32e40p/state-expressions-v1/machine-evidence/report.json)、[空入口配对报告](../../build/cv32e40p/compute-entry-guard-v1/report.json)。有限内联版的walltime比同RTL Verilator低2.37%；两项仍默认关闭，没有基于运行结果调预算、选批次或追加组合测量。

## 2026-11-15 提交检查点

父仓、Wolvrix、XiangShan 和 difftest 均切换到新分支 `thj/cv32e40p-grhsim-checkpoint-20261115`。Wolvrix 实现、回归与功能文档提交为 `8523dc1`；父仓对照工具、testbench 和对应 gitlink 提交为 `9c8def9`。XiangShan 与 difftest 分别保持 `defb18e13`、`b17a43a`，本次仅创建分支。

本次归档覆盖 TNO0001–TNO0032 及其代码，保留各阶段的实验边界和默认值。生成模型、下载依赖、binary 与逐对原始数据继续存放在忽略的 `build/` 目录，未纳入 Git。

提交前 71 项 Python 回归、71 个 Python 文件的语法检查、715 个相对文档链接和两仓 diff 检查通过。源码 SHA 与 TNO0032 已验证快照一致；复用此前完成的 CTest、CoreMark 功能及性能记录，本次没有新增跑分。检查记录见 [commit-checkpoint-20261115](../../build/cv32e40p/commit-checkpoint-20261115/)。
