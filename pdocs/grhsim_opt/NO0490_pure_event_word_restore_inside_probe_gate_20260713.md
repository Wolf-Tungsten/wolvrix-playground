# NO0490 Pure-event word restore-inside probe gate

日期：2026-07-13

## 1. Scope and build

按 [NO0489](./NO0489_pure_event_word_restore_inside_probe_plan_20260713.md) 在 6 个 generated 副本中包装相同 78 个
pure-event words/624 nodes/3,127 producers/92 samples。candidate 每 word 只增加 clear 后的 event-hit `if` 和原 restore 后的
closing brace；原 source line 序列 byte-exact。

78/78 masks 等于 entry/dispatch/clear mask；6/6 baseline/candidate 编译无诊断，baseline `.text` 等于 production，production
source/object SHA 前后不变。

## 2. Whole-object result

| metric | baseline | candidate | delta | delta % |
|---|---:|---:|---:|---:|
| `.text` bytes | 6,118,218 | 6,116,356 | -1,862 | -0.030% |
| instructions | 1,289,373 | 1,288,994 | -379 | -0.029% |
| memory-form | 540,491 | 540,252 | -239 | -0.044% |
| jumps | 40,539 | 40,474 | -65 | -0.160% |
| calls | 7,236 | 7,236 | 0 | 0.000% |

batches 58/21/35/30 的 instructions 分别减少 `121/13/212/31`；batch 41 为 `-5`，仅 memory-form `+4`；batch 24
只有一个 pure word，局部为 `.text +21/instructions +3/memory +7/jumps -1`。后两者相对约 200k instructions 的变化低于
0.005%，不构成明显 local regression；aggregate 全部核心指标改善。

NO0488 的 per-word zero materialization 已消失：`xor` 从 `+78` 降到 `+3`。虽然 unconditional `jmp +81`，但 entry
`je -150`，总 jumps 减少 65。

## 3. Debug proof

batch 35 active word 4112 的 candidate debug sequence：

1. 读取 nonzero active word 后，将 underlying `supernode_active_curr_[4112]` 写 0；
2. load/cmp `event_edge_slots_[0]`；
3. edge-false `jne` 直接跳到下一 active word 4113 的 load；
4. 8 个 entry tests、全部 producer/side effects 和 word 4112 restore 均在该 transfer 之后；
5. edge-hit 才进入原 entry dispatch，hit path restore 后回到同一下一-word continuation。

因此 unconditional jump 是 hit path 的 continuation，不是 NO0488 的 else branch；edge-false 确实不 restore 已清的 pure word。
内部 exact side-effect guards仍存在，跨 external/member calls 没有被错误消除。

## 4. Decision

NO0489 object/machine gate 通过，进入默认关闭 emitter implementation 与结构测试。实现范围只允许 pure-event compute words：
word 中全部 dispatched supernodes 必须通过 NO0479 purity 且共享同一 exact event key；mixed/multi-event/commit words 保持原样。

实现后先加入 dynamic pure-word active hit/miss counters 并跑功能 gate；miss 比例闭合后才规划 SimTop runtime A/B，不能用本篇静态
改善替代动态证据。
