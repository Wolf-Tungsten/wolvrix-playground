# NO0487 Pure-event word bypass object probe plan

日期：2026-07-13

## 1. Scope

从 [NO0486](./NO0486_active_word_event_mask_object_probe_gate_20260713.md) 的失败 mixed-word filter 中只保留
`pure_event_word`：word 中全部 entry bits 都是同一 exact event key。

全量为 107 words/856 nodes/4,230 producers/125 samples/direct `1.873%`；代表 batches 58/21/35/41/24/30
为 78 words/624 nodes/3,127 producers/92 samples/direct `1.378%`。

## 2. Generated-copy transformation

underlying active word 按 `clearMask` 消费后生成：

```cpp
if (event_edge_slots_[slot] == requiredEdge) {
    // byte-exact original eight-supernode dispatch
} else {
    activeWordFlags = UINT8_C(0);
}
// byte-exact original activeWordFlags restore
```

edge-false 同时跳过 entry tests 和 payload，且 local flags 清零后不会 restore。posedge 路径的 entry clear、payload、side-effect guards、
calls 与 restore 顺序不变。mixed words 0 修改。

transform 必须逐 word 验证：event-pure mask == entry/dispatch mask、首 marker 与 restore line 精确命中；candidate 只增加 wrapper/else
lines，原始 source line 序列 byte-exact，production source/object SHA 不变。

## 3. Gate

用 NO0357 PCH、`clang++ -std=c++20 -O3` 重编 6 对 objects；baseline `.text` 必须等于 production。aggregate
`.text`、instructions、memory-form、jumps、calls 均不得增加，单对象无明显回退。

debug 必须证明：

- edge-false 从 word-level guard 跳到 restore/next word，不执行 8 个 entry tests；
- posedge 进入原 dispatch，call order 不变；
- 内部 exact guards 不因 wrapper 被错误删除到跨 call 不安全的范围。

通过后才进入默认关闭 emitter implementation、结构测试和 dynamic hit/miss counter；不直接跑 runtime。
