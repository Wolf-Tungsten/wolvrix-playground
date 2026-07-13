# NO0489 Pure-event word restore-inside probe plan

日期：2026-07-13

## 1. Delta from NO0487

[NO0488](./NO0488_pure_event_word_bypass_object_probe_gate_20260713.md) 的唯一失败来源是 `else { activeWordFlags = 0; }`
形成每 word 的额外 `jmp/xor`。本轮保持相同 78 pure-event words 和相同 source/audit inputs，只把 original restore 放进
event-hit wrapper：

```cpp
clear_underlying_word;
if (event_hit) {
    original_eight_supernode_dispatch;
    original_restore;
}
```

edge-false 时 underlying word 已清，无需 restore；local `activeWordFlags` 随 block 结束销毁。posedge 的原 dispatch/restore 顺序不变。

## 2. Transform and build gate

- wrapper open 插在 clear line 后；close 插在原 restore line 后；
- 不新增 else/assignment，不移动或改写 original restore；
- 78/78 words 必须满足 event-pure mask == entry/dispatch/clear mask；
- candidate 原始 source line 序列 byte-exact，只增加两条 brace lines；
- 6 对 baseline/candidate 用 NO0357 PCH、`clang++ -std=c++20 -O3` 编译；baseline `.text` 等于 production，
  production source/object SHA 不变。

## 3. Machine gate

aggregate `.text`、instructions、memory-form、jumps、calls 均不得增加，单对象无明显回退。mnemonic 必须确认 NO0488 的逐 word
`jmp/xor` 消失。

representative debug word 要证明 edge-false branch 位于 8 个 entry tests 前，并跳过 original restore 到 word scope end；posedge
进入原 dispatch，跨 side-effect call 的 exact guards仍保留。

通过后才进入 emitter implementation 与动态 hit/miss 统计，不直接跑 runtime。
