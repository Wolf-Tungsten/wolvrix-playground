# NO0408 Full-width logic machine realization gate

日期：2026-07-12

## 1. Exact input and attribution

按 [NO0407](./NO0407_full_width_logic_machine_realization_plan_20260712.md)，从 NO0404 的 byte-identical O3 sample rows
提取 `grhsim_or_words_full` 117 个、`grhsim_and_words_full` 83 个 samples，共 200 samples / 198 unique IP / 38
batches。没有重跑仿真或重编 production code。

严格 caller 归属结果为 direct 15、同基本块 unique caller 32、同 supernode 但 caller 不唯一 15、unresolved 138。DWARF
缺 caller 不影响本篇的核心 gate：200/200 的 opcode、完整 assembly operand 和 `%rsp` 使用均直接来自 NO0401 与 production
`.text` SHA 相同的 O3 objects。已闭合的 caller 中主要为 N=16（41 samples）和 N=8（6 samples），并覆盖 AND16 的
batches52/53/58 与 OR8 的 batches59/60 等代表。

## 2. Machine classification correction

首次按“出现 `%rsp`”粗分会得到 71 个 stack samples，但其中 51 个是：

```text
and register, stack-slot
or  register, stack-slot
```

这些 x86 memory RMW instructions 在一条指令中同时完成真实 lane AND/OR 和保存结果，不是纯 spill。另有 2 个 stack
`cmovne` 属于 consumer fusion。只有 stack `mov*` 才计入 removable copy/spill upper；`%rbp` 在当前 O3 function 中是
普通基址寄存器，函数序言没有建立 frame pointer，也不误计为 stack。

最终分类：

| Machine class | Samples | Share | Approx instructions | Interpretation |
| --- | ---: | ---: | ---: | --- |
| Register lane logic | 51 | 25.5% | 1.275B | 必要 AND/OR/PAND/POR |
| Stack RMW lane logic | 51 | 25.5% | 1.275B | 必要 lane op，结果落在宽 temporary |
| Memory input/output move | 43 | 21.5% | 1.075B | 读取 operands / 写回结果 |
| Changed/consumer fusion | 27 | 13.5% | 0.675B | shuffle/test/cmov 等已融合后继 |
| Stack spill/reload `mov*` | 18 | 9.0% | 0.450B | 保守视为全部可删 |
| Control | 6 | 3.0% | 0.150B | block control |
| Register copy | 4 | 2.0% | 0.100B | 保守视为全部可删 |

O3 已把 full helper 展开成 scalar/SIMD lane logic，并在多处把 result 与 changed/consumer 合并；production object 中不存在独立
helper call。栈上 RMW 表明 512/1024-bit local 的 register pressure 真实存在，但把它改成寄存器 lane op并不会减少 retired
instruction，且 NO0227/NO0236 已证明扩大 live range/跨 consumer 搬移会回退。

## 3. Removable upper bound

最宽松地把 18 个 stack `mov*` 和 4 个 register copies 全部删除：

```text
candidate samples                    22
candidate batches                    14
approx removable instructions 550,000,000
share of direct compute          0.393560%
```

22 个 samples 分布于 AND/OR `12/10`，14 个 batches；不是单点，但总量低于 NO0407 的 1% 实现门槛 2.54 倍。这个上界还
把必要的 input/output materialization 和寄存器分配 copy 当成可删，实际收益只会更低。

## 4. Decision

copy/spill source gate 失败，不进入新 code probe，不修改 emitter，也不重复 producer/assign、wide-slice 或 supernode-size
实验。full-width OR/AND 的剩余 samples 主体是不可约 lane payload、宽 temporary 的内存 RMW 和已融合 consumer；它们支持
NO0404 的“payload 粒度/宽值寄存器压力”归因，但当前没有满足门槛的局部实现。

下一步按 NO0407 fallback 回到 change tracking。NO0404 显示该类是剩余唯一明确的正 excess：GrhSIM 603 vs GSim 313
samples，约多 7.25B instructions。先诊断 `grhsim_any_changed_*` accumulate 与最终 successor mask 是否存在多级重复 OR；不做
全局 branchless changed-check，避免重复 NO0083 及后续负向路径。

产物：

```text
build/logs/xs_perf/no0407/analyze_full_logic_samples.py
build/logs/xs_perf/no0407/{full_logic_sample_rows,helper_width_summary,
    class_summary,batch_summary,representative_machine_blocks}.tsv
build/logs/xs_perf/no0407/full_logic_machine_summary.txt
```
