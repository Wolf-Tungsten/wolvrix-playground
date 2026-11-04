# TNO0427 恒零表回退的 PMU、IP 采样与阶段调查结论

本轮完成恒零 `indexedLSUopTable` 调查的独立动态诊断。C 是恒定表提前折叠开启的版本，E 是关闭该折叠、保留 CSR 优化的版本。普通 walltime、阶段导出、动态计数、硬件计数器和冻结二进制 IP 采样分别运行；诊断插桩和采样时间不写入正式性能结论。

## 已复现的性能差异

同场 CPU96、NUMA node1、单线程、私有运行库和相同负载的 8 对 C/E：E 的 walltime 相对 C 平均 **−0.628268%**，中位 **−0.657699%**，bootstrap 95% 区间为 **[−0.687882%, −0.556768%]**，8/8 对 E 更快。两版有效 Difftest 签名和运行窗口一致。

## 后端工作量证据

动态计数窗口中，C 相比 E 的变化不是少量前端译码调用，而是后端调度和活动传播整体增加：

| 计数 | C 相对 E |
| --- | ---: |
| supernode fire | +0.584% |
| 结果/宽值检查 | +0.405% |
| 变化结果 | +0.015% |
| 活动写入语句 | +1.026% |
| 写入非零 mask | +0.129% |
| 新增活动位 | +0.359% |
| batch 调用 | +1.053% |
| batch 空调用 | +0.663% |

变化检测次数几乎相同；计数器没有可靠匹配到 dirty-word 写入，因此该项不作结论。四对核心 PMU 诊断也显示 E 的 cycles 平均少 **0.615%**、instructions 少 **0.571%**，branches 只少 **0.031%**，branch-misses 反而增加约 **0.324%**。这支持“C 执行了更多后端工作”，不支持“主要由分支预测退化造成”。

## 缓存、TLB 和地址采样

四对 cache PMU 中，E 的 instructions 少 **0.576%**，指令缓存 miss 约少 **0.998%**，L1 数据缓存 miss 仅增加 **0.069%**。数据缓存不是当前回退的主要证据。

TLB 诊断中 E 的 dTLB-load-misses 增加约 **48.1%**，但 E 仍然更快；这说明页表事件受代码/数据布局影响，不能把它解释成 C 回退的根因。iTLB miss 约少 **1.0%**，方向与指令数和 I-cache 观察一致，但幅度不足以单独解释全部 walltime。

冻结二进制的 4 对 IP 采样中，raw batch 编号不能跨版本比较。经生成函数中的 `// op` 语义注释对齐，C 的 `commit batch 93` 与 E 的 `commit batch 92` 是同一组 42,937 个操作；对应 C++ 函数体文本大小分别约 28.483 MB/28.486 MB，链接函数大小约 0x20877d/0x20805a。该组的采样占比分别为 4.071%/4.291%，方向受地址布局、采样和运行状态影响，不能据此声称某个 batch 本身多做了工作。另一个 18,439 操作的提交组也能跨版本对齐，采样占比 1.532%/1.520%。

采样产物：[IP 总表](../../build/xs/decode_constant_investigation_20261104_v1/ip-sample-diff.json)、[语义对齐的高采样组](../../build/xs/decode_constant_investigation_20261104_v1/pmu-sample/ip-sample-semantic-top.json)。

## 因果链目前能确认到哪里

1. 恒零表消除在前端只净删除 49 个操作、改写 17 个 Mux，来源集合仍然相同。
2. source clone 的语义集合相同，但遍历顺序大幅改变；共享归属有 4,835 次已可靠对齐的决策不同。
3. 额外的 1,487 个 compute node 在初次创建时已经出现，并非后续环拆分才产生。
4. 这种结构变化在运行时表现为更多 supernode fire、batch 调用和活动写入，最终对应约 0.57% 的 instructions 和约 0.63% 的 walltime 差异。
5. source-order 重放因阶段快照不合法而被严格拒绝，尚没有满足单变量条件的干预结果。因此“遍历顺序/共享归属变化是性能根因”仍是最强的工作假设，而不是已完成的因果证明。

已排除或明显降级的解释包括：CSR 优化本身（已有消融）、单次频率档位漂移、单纯 branch-miss 增加、L1 数据缓存 miss 以及 raw batch 编号对应关系。仍未知的是：共享归属变化、存储/中间值布局和代码地址布局各自贡献多少。

## 后续方向

应先导出 `reg-to-mem` 之后的完整合法快照，或者在 activity-schedule 内实现稳定的语义排序，并在自身重放 gate 通过后再做 C→E 的单变量干预。只有干预同时保持语义、动态计数方向和 walltime 方向一致，才能把结构链升级为性能根因。当前不改生产默认行为。

主要证据：[walltime summary](../../build/xs/decode_constant_investigation_20261104_v1/walltime1/summary.json)、[阶段差分](../../build/xs/decode_constant_investigation_20261104_v1/stage-comparison/stage_diff.json)、[动态计数](../../build/xs/decode_constant_investigation_20261104_v1/count-runs/summary.json)、[PMU core](../../build/xs/decode_constant_investigation_20261104_v1/pmu-core/joined.csv)、[PMU cache](../../build/xs/decode_constant_investigation_20261104_v1/pmu-cache/joined.csv)、[PMU TLB](../../build/xs/decode_constant_investigation_20261104_v1/pmu-tlb/joined.csv)。

