# NO0483 Active-word event-mask audit plan

日期：2026-07-13

## 1. Motivation

[NO0482](./NO0482_outer_event_guard_object_probe_gate_20260713.md) 证明 event-pure producer 可以在 edge-false 时安全跳过，但 855 个
逐 supernode outer guards 导致跨 batch 不稳定的 code shape。当前 compute dispatch 已把至多 8 个 supernodes 放进一个
`activeWordFlags` word，因此应先在 word 层合并相同 event key。

目标形态为：

```cpp
if ((activeWordFlags & eventPureMask) != 0 &&
    event_edge_slots_[slot] != requiredEdge) {
    activeWordFlags &= static_cast<std::uint8_t>(~eventPureMask);
}
```

该过滤位于 underlying `supernode_active_curr_[word]` 按 `clearMask` 消费之后、各 supernode entry test 之前。edge-false bits
不会在 word 尾部 restore；non-event/mixed/external-write bits 保持原值和原顺序。

## 2. Audit

逐 TU 恢复：

- active word index、dispatch/clear mask；
- 每个 supernode 的 entry bit；
- NO0479 event-pure classification 和 exact event key；
- 同 word 中其他 rejected/non-event supernodes；
- NO0448 payload profile samples。

按 `(batch, active_word, event_slot, event_edge)` 聚合 event-pure mask，要求每个 bit 唯一且与 generated entry mask 精确一致。
统计：

1. 1,611 supernodes 压缩后的 word-event groups 数与 compression ratio；
2. pure-event words、mixed words 和 multi-event-key words；
3. 每组 static producers/side effects/profile samples；
4. batches 58/21/35/41/24/30 的代表覆盖。

## 3. Gate

只有 word-event groups 仍覆盖至少 67 direct samples，且 group 数相对 supernodes 至少减少 2 倍，才进入 generated-copy
object probe。

object candidate 必须：

- 只插入 word-level local-mask filter，不改 payload 或内部 side-effect guards；
- baseline `.text` 与 production 一致，production source/object SHA 不变；
- aggregate `.text`、instructions、memory-form、jumps、calls 不增加，单对象无明显回退；
- debug 证明 edge-false 清 mask 后不会执行 producer，posedge call order 不变。

即使 object gate 通过，runtime 前仍须用低开销 counter 测量 active event-pure bits 的 edge hit/miss；308 samples 是 payload 上界，
不是可直接兑现的收益。
