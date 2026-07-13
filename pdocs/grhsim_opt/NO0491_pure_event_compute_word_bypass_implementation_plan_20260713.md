# NO0491 Pure-event compute-word bypass implementation plan

日期：2026-07-13

## 1. Scope

[NO0490](./NO0490_pure_event_word_restore_inside_probe_gate_20260713.md) 已证明 restore-inside whole-word
形态在代表 SimTop objects 上同时减少 text、instructions、memory-form 与 jumps。本阶段将该形态实现为默认关闭的 emitter
候选，不改变 activity schedule、active-bit layout、supernode payload、side-effect call order 或内部 exact-event guards。

配置：

```text
EmitOptions attribute: pure_event_compute_word_bypass
Environment:          WOLVRIX_GRHSIM_PURE_EVENT_COMPUTE_WORD_BYPASS
Default:              false
```

unset/0 的 generated source 必须与当前输出 byte-exact。开关不作用于 commit batch、fullpass variant、split helper
chunk 或 `full_active_word_consume` 命中的 word。

## 2. Conservative eligibility

只有整个 compute active word 都满足以下条件时才生成 wrapper：

1. word 中每个 dispatched supernode 至少含一个非 final 的 `kSystemTask` 或无 result 的 `kDpicCall`；
2. 所有这些 side effects 都有同一非 `true` exact event expression；
3. 排除 timed initial once-only task、无 event side effect、multi-event word 和有 output/return result 的 DPIC；
4. 其余 operation 必须属于显式 pure producer/read 白名单；
5. producer 的所有 results 均不 materialize，也不需要 event/change tracking 或 boundary activation；
6. dispatch/clear mask 一致，确保 miss path 清掉的就是本次已消费 word。

任何无法证明的 operation/result 都保守保持原代码。

## 3. Emit shape

普通路径先读取 nonzero local flags，再按原逻辑清 underlying word。eligible word 在 clear 后生成唯一 exact-event wrapper：

```cpp
supernode_active_curr_[word] &= ~clearMask;
if (event_hit) {
    // original entry tests and payloads
    supernode_active_curr_[word] |= activeWordFlags;
}
```

miss path 不生成 `else`、不清 local flags、也不 restore；local flags 在作用域结束时自然死亡。hit path 保留原逐 entry
consume、forward activation、payload 和 restore。

## 4. Gates

新增 synthetic pure/mixed/multi-event fixture，并执行以下门禁：

- default 与 explicit 0 source byte-exact，只有 explicit 1 出现 marker/wrapper；
- pure homogeneous word 的 clear 在 wrapper 前、restore 在 wrapper 内；
- mixed、multi-event、materialized producer、once-only task、commit、fullpass 与 full-word consume 不包装；
- generated sources 编译，hit/miss/再次激活的 harness 与 baseline 输出及 side-effect 次数一致；
- `emit-grhsim-cpp` 与 `emit-grhsim-cpp-memory-fill` 回归通过。

结构 gate 通过后另建文档实现低开销 dynamic pure-word active hit/miss counters；先用 SimTop 功能运行闭合
`active = hit + miss`，再规划 fixed-ASLR runtime A/B/A。

## 5. Stop conditions

- default source 变化或 pure 判定接受任何 externally visible producer；
- miss 后丢失后续应执行的 activation，或 hit path side-effect 次数/顺序变化；
- split/fullpass/commit 路径被意外包装；
- SimTop eligible word 数明显偏离 NO0484 的 107 words，且无法由生产判定更保守解释。

命中任一条件即修正或停止，不进入 runtime 性能实验。
