# NO0407 Full-width logic machine realization plan

日期：2026-07-12

## 1. Scope and prior constraints

[NO0404](./NO0404_global_compute_machine_source_attribution_gate_20260712.md) 的 current production profile 中，
`grhsim_or_words_full/grhsim_and_words_full` 分别有 117/83 samples，合计约为 direct compute `3.58%`。本轮只判断
这 200 个 samples 中还有多少可删的 temporary/copy/spill，不重新设计宽字语义。

已有实现与负向边界：

- [NO0225](./NO0225_full_width_words_helper_ab_20260709.md) 已删除 full-width path 的 runtime width/tail；
- [NO0226](./NO0226_full_width_words_always_inline_ab_20260709.md) 已强制内联，production object 中没有独立 helper call；
- [NO0227](./NO0227_words_assign_fusion_negative_ab_20260709.md) 的 producer/assign fusion 没有收益；
- [NO0236](./NO0236_manual_wide_slice_fusion_negative_ab_20260709.md) 的手工 producer-consumer 挪动使 VtypeBuffer
  回退 `3.61%`。

因此不重复 generic/full、always-inline、朴素 assign fusion 或 wide-slice fusion，只接受 current O3 仍保留的新机器冗余。

## 2. Exact attribution

复用 NO0388 的 200 个 fixed-period leaf samples 和 NO0401 66/66 byte-identical debug objects。对 runtime helper line-only
sample，在同一基本块内向前后各搜索 32 条指令；仅当前后最近 generated lines 属于同一 supernode 时接受 caller 归属，
并从 caller expression 提取 helper kind、template word count、operation kind、value 和 direct fire。其余保持 unresolved。

输出 sample 级：

```text
helper kind / N / batch / supernode / direct fire
opcode / assembly / stack operand
generated caller line / operation kind
```

## 3. Machine categories

结合 sample opcode 与代表 block disassembly，互斥拆分：

```text
lane_logic       and/or/pand/por and fused bitwise forms
input_output_move
changed_or_consumer_fusion
stack_spill_or_reload
control
other_or_unresolved
```

对 top dynamic caller、N=16 及至少 3 个不同 batches 的代表，检查完整基本块中的 stack operands、load/store、SIMD lane
instructions、temporary materialization 和 changed compare。若 helper result 已被 SROA/vectorize 并与 consumer/changed-check 融合，
不能把 line-table 下的全部 helper samples当作可删 overhead。

## 4. Decision rule

只有同时满足以下条件才进入实现：

1. 明确可删的 copy/spill/reload 动态上界至少为 direct compute `139.750B` instructions 的 1%；
2. 机会覆盖至少 3 个 batches，且 representative O3 probe 确实减少 instructions；
3. whole-function `.text` 增幅不超过 1%，不通过增大 live range 换取局部删指令；
4. 新方案不能复现 NO0227/NO0236 已失败的 producer/assign 或跨 consumer 搬移。

若 samples 主要是不可约 lane logic、已融合 changed/consumer 或 copy/spill 上界不足 1%，则停止 full-width logic 方向，下一步
回到 NO0404 唯一仍有正 excess 的 change tracking，先量化 `grhsim_any_changed` accumulate 是否能按 successor mask 合并。

预期产物：

```text
build/logs/xs_perf/no0407/full_logic_sample_rows.tsv
build/logs/xs_perf/no0407/{helper_width,class,batch}_summary.tsv
build/logs/xs_perf/no0407/representative_machine_blocks.tsv
build/logs/xs_perf/no0407/full_logic_machine_summary.txt
```
