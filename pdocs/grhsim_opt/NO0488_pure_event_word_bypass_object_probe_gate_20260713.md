# NO0488 Pure-event word bypass object probe gate

日期：2026-07-13

## 1. Scope and build

按 [NO0487](./NO0487_pure_event_word_bypass_object_probe_plan_20260713.md) 在 6 个 generated 副本中包装 78 个 pure-event
words/624 nodes/3,127 producers/92 samples。78/78 masks 覆盖完整 dispatch word；6/6 baseline/candidate 编译无诊断，baseline
`.text` 等于 production，production source/object SHA 前后不变。

## 2. Whole-object result

| metric | baseline | candidate | delta | delta % |
|---|---:|---:|---:|---:|
| `.text` bytes | 6,118,218 | 6,117,384 | -834 | -0.014% |
| instructions | 1,289,373 | 1,289,274 | -99 | -0.008% |
| memory-form | 540,491 | 540,384 | -107 | -0.020% |
| jumps | 40,539 | 40,547 | +8 | +0.020% |
| calls | 7,236 | 7,236 | 0 | 0.000% |

aggregate 前三项改善，但 jumps 增加；batch 21/41/24 instructions 分别 `+7/+5/+7`，memory-form `+2/+1/+9`，
不满足 NO0487 的全指标与 local gate。batch 58/35/30 则分别减少 42/70/6 instructions。

## 3. Code-shape diagnosis

mnemonic delta 具有逐 word 的机械特征：`jns +78`、`jmp +78`、`xor +78`、`js -78`，同时 `je/or/test` 各约
`-68~-70`。当前 source 的：

```cpp
if (event_hit) {
    original_dispatch;
} else {
    activeWordFlags = 0;
}
original_restore;
```

使 Clang 为每个 word 生成 event branch、越过 else 的 jump 和 false-path zero materialization。虽能跳过 producer/entry tests，
但额外 CFG 导致 jumps 与三个对象小幅回退。

## 4. Decision

当前 else-zero 形态不进入 debug、emitter 或 runtime。

可继续一个语义等价但更简单的独立探针：underlying active word 已在 wrapper 前清除；edge-false 时无需 restore，且 local
`activeWordFlags` 随即离开作用域。因此可以把原 restore 保留在 event-hit wrapper 内，删除整个 else-zero：

```cpp
clear_underlying_word;
if (event_hit) {
    original_dispatch;
    original_restore;
}
```

该形态应只需一条跳过完整 word 的 event branch，不应再产生每 word 的 `jmp/xor`。必须重新做对象 gate，不能把本篇 aggregate
小改善视为通过。
