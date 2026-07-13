# NO0485 Active-word event-mask object probe plan

日期：2026-07-13

## 1. Candidate

在 [NO0484](./NO0484_active_word_event_mask_audit_gate_20260713.md) 的 batches 58/21/35/41/24/30 generated 副本中，
对 133 个 unique active words 各插入一个 clock-posedge mask filter：

```cpp
if ((activeWordFlags & UINT8_C(eventPureMask)) != UINT8_C(0) &&
    event_edge_slots_[0] != grhsim_event_edge_kind::posedge) {
    activeWordFlags = static_cast<std::uint8_t>(
        activeWordFlags & static_cast<std::uint8_t>(~UINT8_C(eventPureMask)));
}
```

插入位置固定在 `supernode_active_curr_[word] &= ~clearMask` 后、该 word 第一个 supernode marker 前。这样：

- underlying active bits 已消费，不会重复激活；
- edge-false event-pure bits 不会在 word 尾 restore；
- mixed word 的其余 bits 不变；
- payload、entry tests、side-effect guards 和 schedule order byte-exact。

## 2. Build gate

用 NO0357 PCH、`clang++ -std=c++20 -O3` 各编 6 个 baseline/candidate objects。要求：

- 133/133 filters 与 audit `(batch, word, mask, event-key)` 精确对应；
- baseline rebuild `.text` 等于 production；
- production source/object SHA 前后不变；
- candidate 只增加 filter lines，原始 source line 序列 byte-exact。

## 3. Machine gate

aggregate `.text`、instructions、memory-form、jumps、calls 均不得增加，单对象无明显回退。debug 至少检查：

1. pure-event word：edge-false mask 后跳过全部 8 个 payloads；
2. mixed word：edge-false 跳过 event-pure payload，但仍可进入 non-event bit；
3. posedge：event-pure bits 保留，原 call order 不变。

若 gate 通过，下一阶段才实现默认关闭 emitter 开关与结构测试，并先运行 dynamic event hit/miss counter；不以 object 静态改善直接
替代 SimTop runtime 证据。
