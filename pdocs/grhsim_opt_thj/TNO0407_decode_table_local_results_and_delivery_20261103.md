# TNO0407：译码表局部实证与最终交付

日期：2026-11-03。实施与全部要求的测量完成。

## 结论

本轮统一替换使 TLConfig/CoreMark 的单线程整机 Host time 平均从 99.255 s 降至 97.229 s，8 对均更快，配对均值 −2.041%。局部结果显示大译码表的总运算量明显减少，但不是所有小表都适合无条件替换；恒零向量偏移表和很小的 CSR 权限表存在退化。开关仍默认 none，没有依据微基准重新筛选整机范围。

24 张表、246 个“表×分布×测量范围”组合，每项 8 对 AB/BA，共 **1,968 对、3,936 次正式局部样本**。每次进程检查固定 CPU96、单线程、目标节点文件页与匿名页、SMT sibling，全部通过；没有按性能删样本。两侧均使用生产 Clang 与优化选项。

## 全部表的随机输入／完整 eval 结果

这里的 ns 是独立案例的完整 eval，包含输入读取、输出写回、活动调度和变化检测；不包含全香山其余逻辑。kernel 数据与其他输入分布完整保留在 report.md／results.json／local_results.csv。

| 案例 | A 中位 ns | B 中位 ns | 配对变化中位数 | B 更快对数 |
|---|---:|---:|---:|---:|
| 00_Ifu | 4.697 | 4.169 | -11.20% | 8/8 |
| 01_RobImp | 28.876 | 4.549 | -84.27% | 8/8 |
| 02_RobImp | 18.168 | 4.553 | -74.91% | 8/8 |
| 03_indexedLSUopTable | 3.044 | 4.764 | +56.56% | 0/8 |
| 04_indexedLSUopTable | 7.151 | 4.819 | -32.66% | 8/8 |
| 05_indexedLSUopTable | 9.498 | 4.820 | -49.27% | 8/8 |
| 06_indexedLSUopTable | 8.098 | 4.816 | -40.53% | 8/8 |
| 07_indexedLSUopTable | 8.106 | 4.817 | -40.62% | 8/8 |
| 08_indexedLSUopTable | 7.035 | 4.813 | -31.48% | 8/8 |
| 09_indexedLSUopTable | 9.798 | 4.818 | -50.81% | 8/8 |
| 10_indexedLSUopTable | 7.277 | 4.818 | -33.76% | 8/8 |
| 11_DecodeUnit | 748.642 | 10.055 | -98.66% | 8/8 |
| 12_strdiedLSNumOfUopTable | 13.632 | 4.637 | -65.99% | 8/8 |
| 13_indexedLSNumOfUopTable | 21.660 | 4.483 | -79.32% | 8/8 |
| 14_CompressUnit | 6295.790 | 4.661 | -99.93% | 8/8 |
| 15_Rename | 33.139 | 4.398 | -86.75% | 8/8 |
| 16_PrivilegePermitModule | 5.941 | 8.885 | +49.52% | 0/8 |
| 17_I2F | 11.638 | 4.816 | -58.61% | 8/8 |
| 18_FliHTable | 19.160 | 4.521 | -76.43% | 8/8 |
| 19_FliSTable | 22.551 | 4.418 | -80.42% | 8/8 |
| 20_FliDTable | 23.007 | 4.520 | -80.33% | 8/8 |
| 21_VIAluDecoder | 23.847 | 4.713 | -80.23% | 8/8 |
| 22_VCVT | 9.977 | 4.735 | -52.46% | 8/8 |
| 23_VCVT | 7.569 | 5.268 | -30.42% | 8/8 |

## 主要发现与边界

- 主译码 739 行、14 字段在真实有效提交槽序列下，完整局部 eval 中位数为 A **1,171.210 ns**、B **10.39675 ns**。原表、原 Verilator、普通 GrhSIM 和原语对该额外输入序列的 233,280 条向量再次通过 cared-bit 验证。
- CompressUnit 是 ROB 分组压缩控制，非压缩指令扩展器。其 6,561 行表在随机输入下为 **6,295.790 ns → 4.661 ns**；匹配表项分布同样改善，详细数字见逐表报告。
- 向量索引偏移表 `uopIdx=0` 的输出恒零，原普通实现已经很便宜。B 虽能由 C++ 编译器折叠表函数的结果，GRH 中仍保留输入依赖及调度，完整局部成本为 **3.044 ns → 4.764 ns**。未来若处理这个机制，应该在语义 IR 中识别整表常量，而不是按这一轮计时挑宽度。当前没有追加该优化。
- CSR PrivilegePermitModule 的普通逻辑很小，查表形式在此案例退化：**5.941 ns → 8.885 ns**。本轮未据此移除实际实例。
- 输入保持时，原有活动度已经节省大量工作。BranchAttribute 在 99% 保持分布下完整 eval 约 3.07 ns，两侧基本相同；只看 kernel 的收益会夸大完整局部改善。
- ROB 6→5 位表在整机中已被优化消除，尽管局部有明显改善，不能解释整机速度变化。
- 独立案例与整机在输出使用、全局优化、数据布局和活动度上不同。局部倍率不能外推为整机加速，也没有对 2.04% 的整机收益做未经测量的逐模块分摊。

原始输入分布包括随机、表项命中、密集置位、单比特变化、99% 保持。32 位指令表另有表项未命中分布；“未命中表”不等同于所有 ISA 非法指令。主译码额外使用有效提交槽的真实序列。循环次数为各版本独立预校准的整数输入周期；原始 A/B 次数保留，不混淆为整机 C100000。

## 验证和接口交付

- utility 同名 ListLookup、DecodeLogic、decoder，默认保留硬件路线，decode-table 开关隔离到单次 elaboration。设计调用只需显式导入或替换完整限定名前缀。
- 自包含版本化常量表 transport；Wolvrix 接为一个动态输入的纯组合 kDecodeTable，正式 C++ 无外部 DPI。
- 主译码按共同 mask 递归，自然形成 opcode/funct3 等层次；小表根据预定阈值转只读 LUT，重复输出合并。没有历史输入缓存。
- 原表 value/care 解释器、原库 Verilator、普通 GrhSIM、原语四方验证；小表穷举，较大表两种子各至少 100,000 随机向量，加逐行命中及边界。额外验证部分 DontCare、兼容重叠、宽输入／输出和无共同约束位的合并叶子。
- native 测试覆盖常量折叠、CSE、DCE、来源和序列化、局部 SSA／必要物化、无关输入以及结果不变时不传播。错误 transport 拒绝和普通 DPI 回归通过。
- 两组整机 C100000 NEMU/Difftest 逐条一致；8 对整机与全部 3,936 次局部正式样本的环境核验通过。

## 文件与复现

- 中文逐表报告：[report.md](../../build/xs/decode_table_20261103_v3/report.md)。
- 机器可读汇总：[results.json](../../build/xs/decode_table_20261103_v3/results.json)、[local_results.csv](../../build/xs/decode_table_20261103_v3/local_results.csv)。
- 整机原始样本：[pairs.csv](../../build/xs/decode_table_20261103_v3/comparison-v2/pairs.csv)。
- 覆盖／回退／来源链：[coverage.json](../../build/xs/decode_table_20261103_v3/coverage.json)、[fallback_detail.json](../../build/xs/decode_table_20261103_v3/fallback_detail.json)、[source_chain.json](../../build/xs/decode_table_20261103_v3/source_chain.json)。
- 所有局部样本与审计：`build/xs/decode_table_20261103_v3/local-measure-v1`；案例的 Scala／SV／GRH／C++／机器码路径在 `results.json`。
- 使用说明：[decode-table-intrinsic.md](../../wolvrix/docs/emit/decode-table-intrinsic.md)。
- 脚本：`grhsim_decode_table_study.py`、`decode_table_replay.py`、`decode_table_measure.py`、`decode_table_trace_inputs.py`、`decode_table_evidence.py`、`decode_table_results.py`。具体命令和源／工具身份随每一步输出保存。

阶段记录：[TNO0402 语义与 NEMU](./TNO0402_decode_table_intrinsic_contract_20261103.md)、[TNO0403 覆盖与 36 次回退](./TNO0403_decode_table_full_coverage_20261103.md)、[TNO0404 等价](./TNO0404_decode_table_native_build_and_equivalence_20261103.md)、[TNO0405 中断续测](./TNO0405_decode_table_pair_runner_resume_20261103.md)、[TNO0406 全部整机样本](./TNO0406_decode_table_whole_walltime_20261103.md)。

## 增量诊断：CSR 退化原因

后续汇编与 80 对局部对照发现，CSR 表的 LUT 已被 Clang 化为 bit-test；其退化
主要线索是对 1 字节输入的 4 字节读取覆盖相邻字段。约束成字节读取后，
完整局部 eval 约 8.85→4.59 ns。原始局部／整机样本不变，生产实现未改。
详见 [TNO0408](./TNO0408_decode_table_regression_mechanisms_20261103.md)。
