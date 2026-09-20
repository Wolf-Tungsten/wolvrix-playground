# TNO0323: XiangShan counter-print ASC split result

日期：2026-09-15

状态：`STRUCTURAL POSITIVE; PARTIAL GIANT SPLIT; RUNTIME NOT TESTED`。

## 1. 实验闭环

仅测试用户授权的 XSPerfAccumulate 打印 next_counter→counter。
RTL 构建见 [TNO0320](./TNO0320_xiangshan_counter_print_rtl_build_result_20260915.md)，
重生成差异审计见 [TNO0321](./TNO0321_xiangshan_counter_print_rtl_semantic_audit_20260915.md)，
旧 RTL fresh ingest 完整复现冻结基线见
[TNO0322](./TNO0322_xiangshan_counter_print_fresh_ingest_control_gate_20260915.md)。

新 GRH：`build/asc_counter_print_20260915/candidate_ingest_v1/xs_wolf.json`，
3,453,953,912 bytes，SHA-256：
`16d4febf66cf3b1a38afe5c87e0d1fa973620600d2326eaaae6ca628ea1ab73c`。
ingest 与分析 run.json 均 pass。相同安装库和冻结 overlay_v1；arm O，不叠加
selector/write-pack、求解器调权、runtime 改动；phase A/B/C guard 全通过，solver/phase E 未执行。

候选在 node039 运行，初始 CPU184–199；12:08因这些物理核出现其他负载，将本任务
移到快照空闲的105–111、126–127、180、182；12:21加入208–231以加快统计。
全程nice10，不是runtime性能样本，不由两臂生成wall time比较加速。

## 2. 总体结构

| 指标 | 原版 fresh control | counter-print 候选 | 变化 |
| --- | ---: | ---: | ---: |
| nodes | 5,826,569 | 5,817,258 | −9,311 / −0.160% |
| pieces | 1,327,211 | 1,320,603 | −6,608 |
| hyperedges | 303,108 | 296,489 | −6,619 |
| sinks | 329,697 | 329,697 | 不变 |
| ASCs | 301,172 | 301,182 | +10 |
| max sinks | 26,852 | 24,574 | −2,278 / −8.48% |
| max comb entries | 464,601 | 341,119 | −123,482 / −26.58% |
| max full closure weight | 1,115,421 | 883,100 | −232,321 / −20.83% |
| referenced unique weight | 12,450,769 | 12,441,458 | −9,311 / −0.0748% |

comb entries 是该 ASC 闭包内组合节点数；full closure weight 是闭包按现有 node-weight
模型汇总的静态工作量估计，既不是运行时间也不是重建后 partition wall time。
referenced unique weight 对全图被引用的 piece 去重计数。

关键解读：总图估算工作量仅略降，但最大不可拆组件明显变小，主要价值是解除共置、释放
可分配性，而不是删除约20%的全芯片计算。hyperedge 数减少也不能直接当通信字节减少，
尚未运行求解器、分区重建或通信统计。

## 3. 原429个memory的稳定归属

全图844个memory symbol全部保留，无新增、丢失或不同旧组件的新合并；旧组件中只有
原giant的memory成员发生拆分。按稳定symbol追踪得到以下5个ASC，不靠数字ID判断拆分：

| 候选 ASC ID | 原giant memory数 | sinks | comb entries | full closure weight | 主要成员 |
| --- | ---: | ---: | ---: | ---: | --- |
| 4 | 392 | 24,574 | 341,119 | 883,100 | 仍然巨大的主组件 |
| 192278 | 18 | 1,255 | 27,663 | 50,986 | PTW页表遍历器：L0/L1页表缓存与miss queue |
| 181827 | 8 | 191 | 15,901 | 37,648 | L1 DCache tag array，数据缓存标签阵列 |
| 49151 | 10 | 774 | 9,300 | 20,345 | ITTAGE间接跳转预测器，5张表各2个bank |
| 246947 | 1 | 53 | 1,617 | 6,670 | SMS预取器PHT表 |

合计392+18+8+10+1=429，无缺失。ASC ID 仅供查表，不是稳定名称。
各ASC闭包可以共享/复制组合前驱，不能把这些closure weight简单相加来计算全图总工作。
这是“确实拆开部分原大ASC”，与前一轮A/B仅缩小表示、429成员仍全共置的结果不同。

## 4. 剩余giant

主组件内：寄存器writer 21,361→19,761；memory writer 3,529→2,864；SystemTask
971→963；DPI 986→983；logEndpoint寄存器writer 2,384→2,064。
主组件移出的320个logEndpoint writer仍在上述4个memory组件中（96+80+128+16），
没有删除这些计数器。

最大ASC仍有392个memory、883,100估算权重；候选第二大ASC权重85,400。瓶颈明显减轻，
但尚未接近均匀分布，不能认为单行修改已解决所有memory共置问题。

## 5. 证据和边界

完整比较：`build/asc_counter_print_20260915/candidate_vs_control_v1.json`。
原始 summary/asc_table/memory_symbol_to_asc/state_sink_to_asc 在两臂 `asc/analysis/`。
`compare_asc.py` 对O自身自测及新旧比较均通过，输入/artifact SHA记录随结果保存。

RTL审计已排除非目标memory依赖变化，足以将此memory组件拆分归因于counter-print实验；
精确节点编号及微小weight变化仍受等价生成重排/元数据差异影响，详见TNO0321。
打印语义排除了本拍增量，且重生成有条件组之间的日志顺序变化；未做严格日志等价、
partition重建、功能运行或Host性能测试。−20.83%是静态最大closure变化，不是已测Host加速。
