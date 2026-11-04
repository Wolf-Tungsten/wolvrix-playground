# TNO0414：译码表两处调整的局部复测与最终结论

日期：2026-11-03。状态：代码调整、功能验证、整机八组三版对照、24 张表局部复测全部完成。

## 结论

两项局部退化机制已得到修复，但组合后的完整香山比旧 intrinsic 慢 0.6167%，八组均慢。相对原 RTL 仍快 1.4284%；本轮不是新的整机性能提升。实现作为可审阅实验保留，默认 Chisel 开关仍为 none，冻结的旧 intrinsic binary 和全部原始样本保留。尚未拆开做单项消融，不归因到某一条指令，也不继续扩展优化范围。

实现：[TNO0409](./TNO0409_decode_table_lowering_adjustments_20261103.md)；局部结构：[TNO0410](./TNO0410_decode_table_adjusted_local_verification_20261103.md)；整机正确性：[TNO0411](./TNO0411_decode_table_tuned_whole_build_and_equivalence_20261103.md)；布局差异：[TNO0412](./TNO0412_decode_table_local_vs_whole_codegen_20261103.md)；整机样本：[TNO0413](./TNO0413_decode_table_tuned_whole_walltime_20261103.md)。

## 两项局部效果

本节 A=旧 intrinsic，B=调整版，不是原硬件与 intrinsic 的对照。中位 ns 与配对变化均值分别计算，不用两个中位数之比冒充配对均值。

| 表 | 范围 | 分布 | 旧版中位 ns | 调整版中位 ns | 配对变化均值 | 更快对数 |
|---|---|---|---:|---:|---:|---:|
| 03_indexedLSUopTable | kernel | random | 1.3819 | 1.3812 | -0.108% | 5/8 |
| 03_indexedLSUopTable | full | random | 4.7238 | 3.0318 | -34.869% | 8/8 |
| 03_indexedLSUopTable | kernel | hold99 | 1.3819 | 1.3811 | -0.153% | 6/8 |
| 03_indexedLSUopTable | full | hold99 | 3.0666 | 3.0309 | -2.453% | 8/8 |
| 16_PrivilegePermitModule | kernel | random | 9.0947 | 1.5398 | -83.049% | 8/8 |
| 16_PrivilegePermitModule | full | random | 8.8581 | 4.5470 | -49.370% | 8/8 |
| 16_PrivilegePermitModule | kernel | hold99 | 9.0966 | 1.5430 | -83.042% | 8/8 |
| 16_PrivilegePermitModule | full | hold99 | 3.0573 | 3.0601 | +0.073% | 1/8 |

恒零表的 kernel 基本不变，完整 eval 改善，说明在 GRH 阶段消除动态依赖和调度确实必要。CSR 窄读约束明显修复了独立模型中的读取形态，高保持率下完整 eval 基本不变。

完整香山中的 CSR 输入来自多个字段打包，原本已通过寄存器和 shift 位图计算；新约束额外留下掩码。常量表消除还改变了完整模型的聚类和布局。两处局部效果不能直接相加得到整机收益。

## 全覆盖与不确定性

24 张真实表均完成，246 个分布×测量范围组合各八对，共 1,968 对、3,936 个接受样本。22 张表的 ELF .text 与旧版逐字节相同。所有结果，包括无收益、退化和代码相同却有时延差异的情况，均保留。

例如代码段相同的 CompressUnit 在若干分布测得约 4% 改善；没有新机器码证据支持把这种变化归到本次 lowering，因此不报告为新增优化收益。独立微基准受到放置与运行状态等影响，不能仅根据显著配对区间就做因果归因。

## 环境拒绝与恢复

先完成的 Ifu、第一张 RobImp 使用原 150 ms 目标时长。第三张表前后出现短窗口 sibling 活动及缺少库页面观察，保留四个不完整案例尝试后，后续改用 300 ms 目标和至少一千万次校准输入。

NUMA、CPU96 单线程、CPU288 空闲率≥98% 的标准未放宽。只有明确的 sibling_busy 或 missing_mappings、且进程 exit=0，才整对重跑；固定输入、迭代次数和 A/B 顺序不变。10 个正式局部配对有环境重试，全部旧样本和失败 audit 保留；合计14个被拒绝的单样本审计。没有按速度重试。

全部接受的3,936个样本已逐个重新读取 audit：exit=0、errors为空。每个分布/范围均完整八对，顺序为 AB/BA 交替。整机24个正式样本没有拒绝，也没有因局部重试重测。

## 验证与代码状态

native decode-table/CTZ 两项测试和10项 Python/frontend/DPI 相关测试通过。24张表每张两组固定输入复验通过；完整C两组各100,000条有效 DiffTest 轨迹分别与原A/旧B一致。来源、SSA、活动依赖和常量消除检查已随实现补充。

本轮代码位于 `wolvrix/include/core/decode_table.hpp`、`wolvrix/lib/transform/const_fold.cpp`，新增 native 测试在 `wolvrix/tests/emit/test_grhsim_decode_table.cpp`。构建/复测入口为 `scripts/decode_table_tune.py`、`decode_table_tune_local.py`；汇总入口为 `decode_table_tune_results.py`。局部测量脚本增加可选长窗口和仅环境拒绝的整对重试，原默认测量行为不变。

没有提交 commit，没有切换默认开关，没有把该组合调整推荐为新的整机性能基线。若继续探索，优先分离常量依赖消除与窄读保护，并按实际输入表达式确认必要性；这属于下一次独立实验。

## 交付

[完整中文报告](../../build/xs/decode_table_tuned_20261103_v1/report.md)、[结构化结果](../../build/xs/decode_table_tuned_20261103_v1/results.json)、[逐表CSV](../../build/xs/decode_table_tuned_20261103_v1/local_results.csv)、[整机逐轮CSV](../../build/xs/decode_table_tuned_20261103_v1/comparison/triads.csv)。

`source_chain.json` 提供原始 Chisel 调用、GRH操作和生成C++位置；`csr_full_model_codegen.json` 提供完整模型输入及汇编对照；`local-measure/protocol_update.json` 记录短样本处理。所有已完成阶段可复查，不需要重做 Chisel 生成或前一轮测量。
