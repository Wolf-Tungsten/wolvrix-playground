# NO0482 Outer event guard object probe gate

日期：2026-07-13

## 1. Scope and identity

按 [NO0481](./NO0481_outer_event_guard_object_probe_plan_20260713.md) 在 batches 58/21/35/41/24/30 generated 副本中给
855 个 event-pure payload 增加 outer exact-edge guard，覆盖 151 profile samples。

6/6 baseline/candidate 使用 NO0357 PCH、`clang++ -std=c++20 -O3` 编译成功且无诊断。baseline rebuild `.text`
逐对象等于 production；6 个 production source/object SHA 前后不变。每个 candidate 只增加两条 guard/brace lines，原始 source
lines 保序且 byte-exact。

## 2. Whole-object result

| metric | baseline | candidate | delta | delta % |
|---|---:|---:|---:|---:|
| `.text` bytes | 6,118,218 | 6,122,137 | +3,919 | +0.064% |
| instructions | 1,289,373 | 1,289,115 | -258 | -0.020% |
| memory-form | 540,491 | 540,371 | -120 | -0.022% |
| jumps | 40,539 | 40,540 | +1 | +0.002% |
| calls | 7,236 | 7,236 | 0 | 0.000% |

结果不是跨对象稳定改善：

| batch | instructions delta | memory-form delta | `.text` delta |
|---:|---:|---:|---:|
| 21 | -149 | -99 | -1,005 |
| 41 | -235 | -217 | -2,787 |
| 58 | -1 | +1 | +2,669 |
| 35 | +1 | 0 | +2,781 |
| 24 | +20 | +88 | +996 |
| 30 | +106 | +107 | +1,265 |

aggregate instructions/memory 略降，但 `.text`、jumps 增加，且 batches 24/30 有明确 local regression，违反 NO0481 gate。

## 3. Machine-path proof

batch 35 supernode 41912 的 baseline 在 active-bit test 后立即执行 assertion producer，包括 slot loads、SIMD mask/unpack、
`psadbw` 和 compares，之后才检查 `event_edge_slots_[0]`。

candidate debug object 中：

1. active bit 正常测试并清除；
2. 随即 load/cmp event edge；
3. edge-false `jne` 跳到 payload 末尾后的下一个 supernode；
4. producer slot/SIMD sequence 只在 edge-hit 后执行。

因此 outer guard 确实解决了 NO0478 的 producer-before-event 问题。Clang 能删除首次 side-effect call 前的 redundant inner edge
check；但跨 SystemTask/DPIC call 后仍重读 edge，因为外部/member call 可能别名修改 object state。

## 4. Decision

本形态不进入 emitter implementation：855 个逐 supernode outer guards 的 dynamic skip 语义成立，但 object gate 不稳定，不能用
未测的 edge-miss 收益覆盖已见静态回退。

下一条独立形态应在 active-word 层预过滤 event-pure bits：同一 event key 每个 active word 只判断一次；edge-false 时从 local
`activeWordFlags` 清掉对应 bits，而 underlying active word 仍按原逻辑消费，posedge 路径不新增逐 supernode branch。需先量化 1,611
个 supernodes 聚合成多少 `(batch, active-word, event-key)` groups 及其 profile 覆盖，再决定是否做对象探针。
