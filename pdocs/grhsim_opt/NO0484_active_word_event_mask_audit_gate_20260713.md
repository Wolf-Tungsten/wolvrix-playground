# NO0484 Active-word event-mask audit gate

日期：2026-07-13

## 1. Mapping closure

按 [NO0483](./NO0483_active_word_event_mask_audit_plan_20260713.md) 恢复 66 个 compute TUs 的 dispatch 结构：

- 7,932 active words；
- 63,241 supernode-to-word mappings，与 NO0480 supernode 总数精确一致；
- 每个 entry bit 为 single bit、word 内唯一，entry mask 等于 dispatch/clear mask；
- 1,611/1,611 event-pure supernodes 均命中精确 `(batch, active-word, bit)`。

## 2. Grouping result

按 `(batch, active-word, event-slot, event-edge)` 聚合得到 355 groups、354 unique words；1,611 supernodes 压缩
`4.538x`。group size 分布：

| nodes/group | groups |
|---:|---:|
| 1 | 87 |
| 2 | 46 |
| 3 | 27 |
| 4 | 18 |
| 5 | 21 |
| 6 | 25 |
| 7 | 24 |
| 8 | 107 |

word classes：

| class | groups | event-pure nodes | profile samples |
|---|---:|---:|---:|
| pure event word | 107 | 856 | 125 |
| event/non-event mixed word | 246 | 749 | 182 |
| multi-event mixed word | 2 | 6 | 1 |

总 profile coverage 保持 308 samples/direct `4.614%`。两个非 clock groups（slot 5/149）均无 samples；multi-event 的规模
只有 1 sample，后续代表对象无需纳入。

## 3. Representative scope

batches 58/21/35/41/24/30 的 855 supernodes 聚合为 133 groups/133 unique words，压缩 `6.429x`，仍覆盖
4,527 producers 与 151 samples/direct `2.262%`：

| batch | groups | supernodes | producers | samples |
|---:|---:|---:|---:|---:|
| 58 | 26 | 189 | 757 | 30 |
| 21 | 25 | 148 | 800 | 28 |
| 35 | 41 | 308 | 1,232 | 28 |
| 41 | 13 | 65 | 751 | 23 |
| 24 | 15 | 77 | 551 | 21 |
| 30 | 13 | 68 | 436 | 21 |

133/133 groups 都是 clock slot 0 posedge，且每个 active word 只需一个 event mask filter。

## 4. Decision

compression `4.538x` 与 profile direct `4.614%` 同时通过 NO0483 gate，进入 6-batch generated-copy object probe。
candidate 只在 underlying active word 清除后、首个 supernode entry 前插入 133 个 local-mask filters，不修改任何 payload 或
side-effect guard。
