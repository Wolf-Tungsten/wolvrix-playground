# TNO0422 恒零译码表前端差分与频率观察

承接 [调查启动](./TNO0421_decode_constant_investigation_start_20261104.md)。这一阶段只报告已完成的前端结构核对和运行观察，尚未确认整机性能根因。

## 消除范围

使用 [图差分脚本](../../scripts/decode_constant_graph_diff.py)，按 `kind + 完整输入/结果名称 + 类型化属性` 的 SHA256 多重集合比较。OperationId、`_op_` 编号和源码位置不参与同一语义判定；相同指纹的重复项只做多重集合统计，不宣称逐个实例已经唯一对齐。

E 的 `pre_reg_to_mem.json` 有 5,210,978 个操作；C 有 5,210,929 个。差分呈现为 E 独有 66 条操作记录、C 独有 17 条记录。其中 17 个 Mux 保留相同结果名称但输入被改写，净删除 49 个操作。

| E 中被删除或改写的类型 | 数量 |
| --- | ---: |
| Mux | 25 |
| 静态 slice | 14 |
| 动态 slice | 12 |
| Or | 7 |
| Assign | 3 |
| 左移 | 3 |
| DecodeTable | 1 |
| Concat | 1 |

所有差分来源均位于 `WolvrixDecodeTable_17.sv`、`indexedLSUopTable.sv`、`DecodeUnitComp.sv`；未发现这一阶段对其他模块的操作进行改写。恒零输出折叠后，影响沿 `outOffsetVs2/outOffsetVd`、移位和寄存器索引选择向下传播。

C 中部分 Mux 的条件变成 `cpu$l_soc$io_pll0_lock` 或 `_val_24329`，这是既有常量池的 1 和 0：定义分别为 `kConstant 1'b1` 和 `kConstant 1'b0`。不能根据这些名称误解为译码开始依赖 PLL 动态输入。

完整证据：[前端差分 JSON](../../build/xs/decode_constant_investigation_20261104_v1/static/pre_graph_diff.json)。这份 JSON 保留每条差分的原始属性、来源与文件偏移。

## 调度导出实现进度

增加默认关闭的 `WOLVRIX_ACTIVITY_STAGE_TRACE`，记录：原操作拓扑序、原始 source 遍历序、逐条 source clone 的来源/消费者、共享表达式决策与首个失败条件、初始计算节点、每次环拆分、每轮 out1/in1/sibling 合并、最终 supernode，以及 batch/active ID/存储引用。

研究开关 `WOLVRIX_RESEARCH_FOLD_CONSTANT_DECODE=1` 仅用于重现冻结 C 的原实现；未设置时保留 E 的当前行为。为避免 JSON 重新载入压缩内部 ID 干扰调查，阶段导出从冻结 RTL 重新生成，随后要求所有生成 C++ 和头文件逐字节匹配冻结参照。导出未通过该 gate 时，不把它用于因果结论。

## 频率变化已有直接观察

正式第一对：C 98.213 s，E 97.487 s。第二对：E 109.935 s，C 110.721 s。第三对又回到 C 98.045 s、E 97.369 s。三个完整配对均保留。

CPU96 的 APERF/MPERF 比值第一对约 1.432/1.434，第二对约 1.291/1.307，第三对约 1.425/1.423。第二对的整体变慢伴随实际频率明显下降，NUMA、亲和性和 sibling gate 仍通过。系统负载、CPU pressure 和逐秒频率计数均已保存。

这说明仅靠 NUMA 和亲和性 gate 不能保证频率状态不变。当前尚未完成八对，不能据这几对给最终性能结论；后续独立 PMU 计数用于区分执行工作量与单位工作成本。
