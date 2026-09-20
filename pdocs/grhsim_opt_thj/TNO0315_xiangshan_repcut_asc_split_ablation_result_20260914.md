# TNO0315: XiangShan RepCut ASC split ablation result

日期：2026-09-14

状态：`STRUCTURAL NEGATIVE; KEEP EXPERIMENTAL CODE ISOLATED`

## 1. 范围与复现条件

承接 [TNO0311](./TNO0311_xiangshan_repcut_asc_split_ablation_plan_20260914.md)，在同一冻结输入
`build/xs/wolf/wolf_emit/xs_wolf.json`（SHA-256
`82a29e6e2f715c18ffd61ab0106ed5abb6d0fbb6843eea58d8782eb3d30994ba`）上完成 O/A/B/AB 四臂。
四臂均加载一次全图、执行同一 RepCut phase A/B/C（`partition_count=32`、
`weight_mode=closure-aware`），在 solver/phase E 前返回；运行节点为 node039，实验库位于
`build/asc_split_20260914/overlay_v1/`，生产 `repcut.cpp` 未修改。

- O：仅观测。
- A：64 路 AXI pending decrement 的动态 `last[selector]` 改为对应固定 lane `last[i]`，保留
  `onehot & fire` guard；只在明确二态语义许可下运行。
- B：对同 memory、地址、事件、等价 enable 且掩码为互不重叠常量单 bit 的写口做宽写聚合；
  有序 priority、未知掩码、冲突条件均拒绝。
- AB：先 A 后 B。

局部门禁：A 的 64 路 fixture 通过 2,113,536 次二态检查及负向拒绝；B 通过 66,048 组含
X/Z 控制和数据的等价检查、7 项拒绝条件与幂等性检查；全图四臂均通过 def-use/reverse-use
完整性和 phase A/B/C guard。A 明确不具备 Verilog 四态等价性，未进入生产默认。

## 2. 全图结果

| 臂 | ASC 数 | 最大 sinks | 最大 comb | 最大 full closure | memory 成员数 | 原 giant memory 分量 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| O | 301,172 | 26,852 | 464,601 | 1,115,421 | 429 | 1 |
| A | 301,172 | 26,852 | 464,601 | 1,115,420 | 429 | 1 |
| B | 301,172 | 24,812 | 461,865 | 1,108,213 | 429 | 1 |
| AB | 301,172 | 24,812 | 461,865 | 1,108,212 | 429 | 1 |

memory 成员数是全图 unique memory symbol 数；“原 giant memory 分量”把 O 中最大 closure
ASC（O 的 `asc_id=4`）的 429 个 memory symbol 按稳定 symbol 追踪到各臂。四臂始终只有一个
组件，且 429 个成员没有丢失，故没有发生 ASC 拆分。

B/AB 的实际改写记录为：4,184 个 memory write 中 8 组命中，257/255 个逐位写分别压成
一个宽写，共移除 2,040 个写端点；rewrite-cascade cleanup 移除 5,132 个由此失效的
operation/value。该表示压缩解释了 sinks/comb/weight 下降，但没有改变 memory 共置连接。
A 只使 closure weight 减少 1，AB 相对 B 也只再减少 1，说明 selector 依赖不是 giant
ASC 的边界决定因素。

四臂结构汇总和稳定 symbol 归属对照见：
`build/asc_split_20260914/arm_comparison_v1.json`；单臂原始记录在
`build/asc_split_20260914/runs/{O,A,B,AB}_node039_v1/`。运行均声明
`solver_run=false`、`phase_e_run=false`，不能据此宣称仿真 Host 加速。

## 3. 根因与后续边界

只删除动态 selector 依赖不足以断开 giant：只读 bounded witness 显示 64 路 deinterleaver
FIFO DATA 写入都可沿 routing 回溯到同一个
`cpu$l_soc$socMisc$axi4buf_2$nodeIn_r_deq_q$ram_ext$Memory`，路径不经过被 A 改写的 64 个
pending decrement。B 只压缩写端点，读/数据上游及 memory-symbol union 仍完整存在，因此
RepCut 继续把 429 个 memory 归到一个 ASC。证据文件为
`build/asc_split_20260914/residual_bridge_v1.json`；它是路径见证，不是全图功能等价证明。

结论：本轮两点优化对表示规模有局部收益（主要来自 B），但不能解决逻辑锥边界问题，也不
应改变 `hyper_partition_weight` 或生产默认。若继续拆分，应针对 memory 共置策略/跨 memory
读写依赖设计保持语义的分区准则，并先做独立结构 gate，再做完整功能与 runtime gate。

## 勘误 2026-09-15：主机与 memory 计数口径

后续 counter-print 对照重新核验原始 run.json：O 实际在 node039，A/B/AB 实际在 node029；
后者目录名中的 node039 不是实际运行主机。原文“四臂运行节点为 node039”不准确。
本轮为静态结构分析而非 wall-time 比较，结构结论不因主机名称修正而改变。

表中 429 是最大 ASC 的 unique memory write symbol 数，不是全图 unique memory 数。
O 的 memory_symbol_to_asc.tsv 全图有 844 个 unique symbol；其中429个属于 giant。
原文表后“全图 unique memory symbol 数”应按此更正；429个追踪成员仍然没有发生拆分。
