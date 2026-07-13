# NO0512 Sparse-batch volatile threshold audit plan

日期：2026-07-13

## 1. Objective

[NO0511](./NO0511_batch27_event_predicate_codegen_probe_gate_20260713.md) 证明 local volatile copy 可消除低计数 batches
27/57/61 的 codegen cliff，但全 107 words 使用时会削弱 hot dense batches 的 direct-predicate simplification。本轮寻找只依赖
emitter 可见结构的 per-batch 规则，不按 batch id 或编译后 object 结果硬编码。

候选规则为：

```text
if eligible_pure_event_words_in_batch <= threshold:
    all eligible words in this batch use local volatile copy
else:
    all eligible words keep the direct event predicate
```

## 2. Inputs and sweep

复用 NO0503 plain 与 NO0511 all-volatile 的 22 对 production objects，无需重新编译。对 threshold `0..37` 逐项组合：

- `.text`、instructions、memory forms、jumps、calls 相对 NO0357 baseline 与 plain candidate 的 aggregate delta；
- 进入 volatile subset 的 batches/eligible words；
- 联结 NO0500 50k TSV，统计 volatile subset 的 hit/miss/total 及占全部 hit/miss 的比例；
- 明确 batches 35/58/21/41/30 五个 miss-hot batches 在每个 threshold 下的 direct/volatile 选择。

由于每个 batch 的 source variant 是全 direct 或全 volatile，组合 aggregate 可以直接复用真实 O3 objects，不做指标线性估算。

## 3. Gates

可进入实现的 threshold 必须同时满足：

1. text/instructions/memory/jumps 四项 aggregate 均不比 plain candidate 差，calls 不增；
2. text 与 instructions 最好低于 NO0357 baseline，避免只把 NO0503 cliff 从一个 batch 移到另一个 batch；
3. batches 35/58/21 保持 direct predicate；前五 miss-hot batches 若有任何切换必须单独说明；
4. volatile subset 不超过 20% eligible words，并报告其 dynamic hit share，限制重新执行内部 event checks 的范围；
5. threshold 必须是稳定的 batch eligible-count 规则，不能引用 active-word index、batch id 或本次 object delta。

若没有 threshold 同时过门，停止 sparse-batch 规则并等待 plain candidate runtime；若存在连续阈值区间，优先选择最小且能消除
主要 cliff 的阈值，再验证 emitter 是否可在输出 word body 前稳定得到 batch eligible 总数。

本篇只声明 audit，尚未形成 threshold 结论或修改 emitter。
