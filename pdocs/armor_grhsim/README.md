# ARMOR 节点压缩在 GrhSIM 上的评估

| 记录 | 内容 |
| --- | --- |
| [TNO0001](./TNO0001_armor_node_compression_assessment_20261118.md) | ARMOR 论文的方法与实验口径、GrhSIM 已有的打包能力、冻结图上的静态核验（33.14% 的存活纯组合操作是一位按位运算）及首轮实验与停止条件；无新增计时 |
| [TNO0002](./TNO0002_boolean_lane_experiment_20261118.md) | 同一活动区域内的一位节点压缩原型 `bool_lane_pack`：XiangShan 305 个包，受影响函数净增 6,459 条静态指令、24,024 B，按预定条件结束在机器码检查；walltime 未测，默认关闭 |
| [TNO0003](./TNO0003_mask_input_direction_20261118.md) | 方向分析：下一轮优化共享归约掩码的输入收集，按物理槽位重排私有位号并合并读取；只做离线核对，预先约定检验与停止条件 |
| [TNO0004](./TNO0004_reduction_mask_layout_20261118.md) | 掩码位号重排与八字节读取 `reduction_mask_layout`：XiangShan 27 个受影响批次少 11,502 条静态指令，八对 walltime +2.12%，CI [−1.46%, +7.47%] 跨零；CV32 零命中，默认关闭 |
| [TNO0005](./TNO0005_post_mask_headroom_20261118.md) | 掩码布局每 guest cycle 少约 0.24% 的退休指令；按真实活动次数核对生成 C++ 与 ELF 后，下一轮优先同读者连续寄存器提交，其次用公共输入跳过整组归约 |
| [TNO0006](./TNO0006_commit_and_common_guard_20261119.md) | 双模型八轮：同读者提交分组 walltime −2.845%，CI [−3.644%, −1.819%]；归约公共输入保护 `reduction_common_guard` 跳过 98.01% 的候选组访问、退休指令 −2.22%，walltime CI 跨零 |
| [TNO0007](./TNO0007_reduction_common_guard_retest_20261119.md) | 归约公共输入保护独立复测：同一对 ELF 相邻交替，walltime −1.638%，CI [−2.096%, −1.089%]，8/8 更快；与提交分组的组合收益未测 |
| [TNO0008](./TNO0008_frontend_bottleneck_and_direction_20261119.md) | 基线自顶向下定位：约 75% 的派发槽在等前端，86% 的取指填充来自 L2 之外，每 guest cycle 4.33 万次分支预测失败；方向排序为激活分发、提交成块比较、无条件热区内的节点压缩；仅分析 |
| [TNO0009](./TNO0009_static_hot_set_20261119.md) | “每拍都跑”的 supernode：两条结构规则选出 3,088 个，3,086 个在 profile 热集合里，占 compute 求值量 9.4%；其余主要是性能计数器的更新逻辑，占 17.9%；仅分析 |
| [TNO0010](./TNO0010_perf_counter_packing_20261119.md) | 性能计数器从 Chisel 到生成代码的打包路径：32,598 个计数器集中在 `LogPerfEndpoint`，占 `comb-lane-pack` 56,214 个被打包根的 57%，被并的只是复位和清零两层选择；无新运行 |
| [TNO0011](./TNO0011_perf_counter_lowering_20261119.md) | 逐寄存器观察：每拍只有 1,524 个计数器在变，却重算 24,444 路、比较 32,598 次；建议提交时无条件成排累加，先用删除模式量上限；一次只读观察运行，无计时 |
| [TNO0012](./TNO0012_perf_counter_bank_result_20261119.md) | `accumulate-sink` pass 与累加排，三模型八轮：删除计数器 walltime −27.99%，CI [−28.76%, −27.33%]；成排累加 −7.83%，CI [−8.46%, −7.25%]；差距来自设计侧事件逻辑和 22,402 个只为计数器存在的寄存器 |
| [TNO0013](./TNO0013_commit_group_and_accumulate_bank_20261120.md) | 提交分组与成排累加四组八轮，单开相对全关分别为 −3.47% 和 −9.09%，双开为 −9.57%；双开相对只开成排累加为 −0.53%，CI [−1.66%, +0.76%] |
| [TNO0014](./TNO0014_accumulate_bank_default_20261120.md) | XiangShan 单模型 GrhSIM 默认开启成排累加，支持显式关闭和从检查点恢复；声明信号波形走普通寄存器路径 |
| [TNO0015](./TNO0015_accumulate_bank_default_regression_20261120.md) | 正式入口默认开启与显式关闭的性能回归，node030 CPU 96 八轮配对，CoreMark 10 万周期从 113.71 s 降到 102.42 s，walltime −9.93%，CI [−10.49%, −9.35%]，8/8 更快 |
| [TNO0016](./TNO0016_branch_sources_and_eager_logic_20261120.md) | 预测失败按语句归类：值表达式 37%、分发测试 25%、提交 23%；新选项 `logic_eager_operand_chars` 加一个编译器开关，两次八轮计时 walltime −20.26% 和 −19.35%，CI [−21.57%, −18.70%] 和 [−19.64%, −19.05%]，16/16 更快；其上再做 PGO 合计 −25.57%；PGO 插桩构建的终点差异是编译器在一条语句上生成了错误代码；修复累加排读者过滤里的悬空引用，生成结果恢复可重复 |
| [TNO0017](./TNO0017_single_model_expression_defaults_20261120.md) | XiangShan 单模型默认采用 eager 阈值 4096 和 x86 Clang 内存条件传送。列出与通用入口的默认值差异及独立关闭方法。CV32E40P CoreMark 显式开启后八轮均慢，配对中位数 +2.92% |
| [TNO0018](./TNO0018_cv32_xiangshan_defaults_20261120.md) | CV32E40P CoreMark 使用 XiangShan 完整默认配置，walltime 从 2.470 s 增至 3.663 s，同轮 +48.31%。两项表达式优化在 XiangShan 入口内为 −2.09%，在 CV32 入口内为 +2.41% |
| [TNO0019](./TNO0019_cv32_xiangshan_slowdown_causes_20261120.md) | CV32E40P 降速归因。事件分组减少跨组比较和激活，条件 mux 与寄存器视图进一步减少重复求值。保留 XiangShan 的图与节点上限，只开三组规则便从 3.682 s 降至 2.544 s，收回与 CV32 基线 94.0% 的耗时差 |
| [TNO0020](./TNO0020_xiangshan_cv32_groups_20261120.md) | XiangShan 单核 CoreMark 10 万周期，三组全开 83.78 s → 86.60 s，同轮 +3.40%，5/5 轮更慢。单开事件分组 +14.85%。MicroBench 全开 +0.66%，四对样本区间跨零 |
| [TNO0021](./TNO0021_xiangshan_grhsim_gsim_pgo_20261120.md) | XiangShan 单核 10 万周期，CoreMark 训练后，PGO 使 GrhSIM / GSIM 的同轮耗时分别变化 -8.73% / -31.56%，换测 MicroBench 为 -7.41% / -32.52% |
| [TNO0022](./TNO0022_grhsim_gsim_gap_causes_20261121.md) | GrhSIM 与 GSIM 的差距归因。GrhSIM 忽略了两处组合逻辑里的 DPI 调用，GSIM 同样关掉后 PGO 版为 78.70 s 对 52.99 s。GrhSIM 的模型每拍多执行约五成指令，多在寄存器提交和跨组值的簿记。提交按 8 字节成块比较的原型 walltime −4.22%，PGO 版 −5.89%，四轮全部更快；两个按活动过滤的原型更慢 |
| [TNO0023](./TNO0023_grhsim_commit_pgo_partition_mux_20261121.md) | GrhSIM 成块提交、PGO、计算组划分与条件 mux。三组规则、160 超节点与宽块的联合版在 CPU 96 相对原 PGO 的 CoreMark / MicroBench 耗时为 −9.01% / −10.85%，两个负载均四轮更快。独立降低 mux 门槛和按热度过滤末端移动的对照见正文。 |
| [TNO0024](./TNO0024_xiangshan_gsim_grhsim_pgo_threeway_20261121.md) | GSIM PGO、原与新 GrhSIM PGO 同轮复测。CoreMark / MicroBench 新版相对原版耗时 −10.14% / −10.87%，相对原样 GSIM 为 +9.95% / +5.74%，对齐两处统计 DPI 后为 +31.24% / +26.02%。 |
| [TNO0025](./TNO0025_xiangshan_grhsim_mode_defaults_20261121.md) | XiangShan 单模型默认配置。普通版采用 108 个操作的超节点上限和四寄存器块，PGO 版采用 160 上限、十六寄存器块和三组 PGO 规则。 |

规则参考：[GrhSIM 文档管理规则](../grhsim_opt_thj/RULES.md)。评估对象是 Jiaping Tang 等发表于 MICRO 2026 的 ARMOR 论文，出处见 TNO0001。

静态核验：[论文核对与图计数](../../build/armor-paper-review/)。
一位节点压缩实验：[armor-lane-v1](../../build/armor-lane-v1/)，复现入口：[lane replay](../../scripts/armor_lane_replay.py)、[调度审计](../../scripts/armor_lane_audit.cpp)、[机器码对照](../../scripts/armor_lane_machine.py)。在机器码检查结束，保持默认关闭。
掩码输入方向：[armor-direction-v2](../../build/armor-direction-v2/)。
掩码布局实验：[armor-mask-read-v1](../../build/armor-mask-read-v1/)，复现入口：[mask layout compare](../../scripts/armor_mask_layout_compare.py)、[measure](../../scripts/armor_mask_layout_measure.py)。整机收益未确认，保持默认关闭。
掩码之后的动态计数：[armor-post-mask-analysis-v1](../../build/armor-post-mask-analysis-v1/)。
提交分组与公共输入保护：[armor-followup-v1](../../build/armor-followup-v1/)，复现入口：[followup compare](../../scripts/armor_followup_compare.py)、[measure](../../scripts/armor_followup_measure.py)；公共输入保护的复测在 [armor-reduction-common-guard-retest-v1](../../build/armor-reduction-common-guard-retest-v1/)。两项开关的全局默认均为关闭。
瓶颈定位：[armor-bottleneck-review-v1](../../build/armor-bottleneck-review-v1/)。静态热集合：[armor-static-hotset-v1](../../build/armor-static-hotset-v1/)。
性能计数器的打包与观察：[armor-perf-pack-v1](../../build/armor-perf-pack-v1/)。
性能计数器的删除与成排累加：[armor-acc-v1](../../build/armor-acc-v1/)，复现入口：[acc compare](../../scripts/armor_acc_compare.py)、[measure](../../scripts/armor_acc_measure.py)，功能说明：[accumulate-sink](../../wolvrix/docs/transform/accumulate-sink.md)、[累加排](../../wolvrix/docs/emit/grhsim-accumulate-bank.md)。
预测失败来源与表达式改动：[armor-dispatch-v1](../../build/armor-dispatch-v1/)，复现入口：[dispatch diag](../../scripts/armor_dispatch_diag.py)、[生成一个版本](../../scripts/armor_dispatch_emit.sh)、[结果表](../../scripts/armor_dispatch_results.py)，功能说明：[非短路逻辑与/或](../../wolvrix/docs/emit/grhsim-scheduling.md)。通用生成器默认关闭这两项，XiangShan 单模型的默认设置见 [TNO0017](./TNO0017_single_model_expression_defaults_20261120.md)。
GrhSIM 与 GSIM 的差距归因：[armor-gsim-gap-v1](../../build/armor-gsim-gap-v1/)，复现入口：[计数](../../build/armor-gsim-gap-v1/pmu.py)、[语句级采样](../../build/armor-gsim-gap-v1/ibs.py)、[提交按块比较的改写](../../build/armor-gsim-gap-v1/block_commit.py)、[计时](../../build/armor-gsim-gap-v1/timing.py)。脚本目前只在本地 `build/` 目录里。

本系列从父仓 `8f5bbdc`、Wolvrix `59e0f1e` 开始。逐轮计时 CSV 随对应记录归档。完整模型、ELF、运行日志和诊断数据保存在本地 `build/` 目录。[四组对比样本](./data/TNO0013_commit_bank_samples.csv) · [默认选项回归样本](./data/TNO0015_default_bank_pairs.csv) · [TNO0016 第一轮逐轮秒数](./data/TNO0016_rounds_v1.csv) · [TNO0016 第二轮逐轮秒数](./data/TNO0016_rounds_v2.csv)
