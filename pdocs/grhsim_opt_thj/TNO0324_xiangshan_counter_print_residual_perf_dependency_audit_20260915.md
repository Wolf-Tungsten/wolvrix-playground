# TNO0324: XiangShan counter-print residual perf dependency audit

日期：2026-09-15

状态：`ALL PERF PRINT MEMORY DEPENDENCIES REMOVED; GIANT STILL PARTIAL`。

## 1. 问题与方法

[TNO0323](./TNO0323_xiangshan_counter_print_asc_split_result_20260915.md) 已确认原429个
memory拆为5个ASC，但最大组件仍有392个memory。本节核验是否还有批量perf打印经未修改
的Max/Reference等项目继续构成memory桥梁。

脚本 `build/asc_counter_print_20260915/audit_candidate_perf_memory.py`；正式结果
`candidate_perf_memory_v2.json`，SHA-256：
`e38981b26d831ee2ec5fc444ab6c07066a34f093aed33bb89bd75b93d564c7ea`。
输入为同一候选GRH，SHA `16d4febf66cf3b1a38afe5c87e0d1fa973620600d2326eaaae6ca628ea1ab73c`。

重新流式扫描全图5,817,258个operation，自建紧凑def-use依赖图；不复用旧op ID/snapshot。
对loc指向LogPerfEndpoint.sv的全部fwrite回溯所有条件、参数、事件输入，在Constant、
RegisterRead、LatchRead处停止，与当前RepCut source边界一致；不按运行时打印条件剪枝。

## 2. 全量结果

- 共822条LogPerfEndpoint fwrite：35 PERF、787 ERROR。
- 35 PERF共68,750个operand（含控制/格式/事件，不是计数器数量），全部逐根检查。
- 35 PERF全部memory_count=0；包括实际仍存在的Max/Reference等输出，没有残余memory路径。
- 对照候选state_sink_to_asc/asc_table：35条PERF分别归属35个独立ASC，每个只有1个sink，
  没有任何一个位于剩余giant ASC4。
- 全部822个fwrite回溯均完整解析，无可达的未解析值。全图另有56个无定义debug值，均不在
  所选打印回溯范围内，结果文件列出这些值，不将它们静默视为常量。

唯一有memory依赖的是一条ERROR打印的条件，不是perf数据参数：
`_op_10987576`，候选LogPerfEndpoint.sv:45437，`llptw enq, to cache conflict with to mem`。
条件经llptw.to_mem_out、dup_wait_resp、io_mem_resp_valid等回溯至
`inner_ptw_to_l2_buffer$nodeIn_d_q$ram_ext$Memory`，仅1块memory；完整18步见证在JSON。
Scala来源为PageTableWalker.scala:820的XSError条件。

## 3. 工具修正与结论边界

v1分类器按`[PERF]`匹配，漏掉RTL实际`[PERF ]`的填充空格，导致PERF汇总无效。
保留v1，并用`candidate_perf_memory_v1_superseded.json`明确废弃；v2修正匹配后重新扫描、
重新全量回溯，不是直接修改旧结果。只引用v2的分类和汇总。

本轮已切断集中perf打印造成的memory连接；因此不能继续把392-memory残余giant归因于
这些35条perf打印，也没有证据为进一步拆ASC而盲目修改Max/Reference打印。
剩余连接需要另查功能读写、DPI、断言等实际路径；计数器writer依然可能因自身事件来源
而属于giant，这与打印已经独立不矛盾。此次只读审计不证明剩余连接均由哪一类主导，
也不提供Host性能或全芯片功能等价结论。
