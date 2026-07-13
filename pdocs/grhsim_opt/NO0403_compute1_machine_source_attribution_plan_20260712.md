# NO0403 Compute1 machine/source attribution plan

日期：2026-07-12

## 1. Problem

[NO0388](./NO0388_direct_state_read_instruction_profile_gate_20260712.md) 中 direct compute1 有 243 个
`instructions:u` fixed-period samples，是当前最大的 compute hotspot；但 NO0394/NO0400 证明它没有 repeated read-only
scalar candidate，[NO0402](./NO0402_production_scalar_load_realization_gate_20260712.md) 也已停止 typed-local。下一步不能继续
根据 `107,121` 个 source slot references 猜测成本，需要把真实采样指令归到 generated source 与 supernode 机制。

## 2. Reused exact inputs

本轮不重跑仿真，复用：

1. NO0388 CPU188/NUMA1/fixed-ASLR、25M period、0 lost 的 50k `instructions:u` perf script；
2. exact-entry direct 中 `eval_compute_batch_1()` 的 243 个 leaf sample offsets；
3. NO0401 与 production `.text` SHA256 相同的 batch1 line-table object；
4. NO0399 direct 50k compute fire；
5. NO0357 production generated C++ 与 NO0392 scalar locality rows。

函数内 offset 不受 ASLR 基址影响。先要求 243 个 leaf samples 全量解析、object `.text` 继续匹配 production，任一门禁失败则
不作 source attribution 结论。

## 3. Attribution stages

### 3.1 Sample to supernode

从 perf script 每个 sample 的第一条 callchain frame提取 compute1 offset，经 `addr2line -i` 映射 generated source line，再按
`// Supernode N:` 区间归属。helper-only line 沿用 NO0402 的严格规则：只在同一基本块内搜索，且前后最近 generated line
必须属于同一 supernode；其余保留 unresolved，不强行分配。

### 3.2 Generated mechanism class

结合采样行、相邻源码和采样指令，互斥分类为：

```text
entry_active_scan
operand_or_state_read
payload_compute
changed_compare
changed_accumulate
slot_writeback
activation_propagation
runtime_helper
other_or_unresolved
```

同时记录 opcode、memory operand 所属 class member 区域、supernode fire、operation kind、value name 和 source block 大小。
输出按 class、supernode、operation kind、fire bucket 和 opcode 汇总，区分“高 fire 的普通 payload”与 GrhSIM 特有的
changed/activation 持久化框架。

### 3.3 GSim contrast

对 compute1 样本最高的 value/op 家族，使用稳定 value/origin token 在 same-FIR GSim generated C++ 中查找对应实现；若无法建立
一一语义映射，只报告可验证的代码形态和机器指令差异，不把 GSim top subStep 当作伪对应。重点检查 GSim 是否存在同等粒度的
active flag scan、persistent changed OR、slot writeback 和 successor activation。

## 4. Decision rule

本篇先形成诊断 gate，不直接修改 emitter：

1. 若单一可删除/可合并的 GrhSIM framework class 覆盖 compute1 至少 20% samples，并且静态形态在多个 top compute batches
   重复出现，则另起默认关闭的窄实现计划；
2. 实现前还必须证明全 compute 动态上界至少覆盖 direct compute instructions 的 1%；
3. 若样本主要是 payload、类别分散或只属于 compute1 的局部逻辑，则停止该候选，回到全 compute/commit excess 排序；
4. fixed-period 的 243 samples 只用于类别级信号，不把少量单 IP 或相邻 supernode 差值解释成精确比例。

预期产物：

```text
build/logs/xs_perf/no0403/compute1_sample_rows.tsv
build/logs/xs_perf/no0403/{class,supernode,operation,opcode}_summary.tsv
build/logs/xs_perf/no0403/compute1_attribution_summary.txt
```
